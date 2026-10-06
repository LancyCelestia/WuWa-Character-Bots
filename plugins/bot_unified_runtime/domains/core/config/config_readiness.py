from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.character.documents import (
    SUPPORTED_CHARACTER_DOCUMENT_SUFFIXES,
    load_character_document,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    normalize_openai_chat_endpoint,
)

PERSONA_PROFILE_MIN_CHARS = 10
PERSONA_PROFILE_MIN_MEANINGFUL_LINES = 2

# ---- 配置面取值折成布尔的**词表中央真身**（F-13 乙案第一批，2026-10-06 搬家批落位）----
# 为什么这两枚词表住在配置体检件里：本件已经是「把配置面原始取值折成判定」的住处
# （`has_real_api_key`／`is_placeholder_model`／`base_url_error` 都是同一族——收字符串、
# 出判定），布尔字面量词表是同一件事的第四枚，不是外来的东西。
#
# 只收词表，不收判定逻辑：仓里同型判定今天有三份实现，形态并不同族——
# `domains/chat_reply/policy/gate.py` 的 `_flag_from_text` 之后还要**逐级回落**
# （driver config → os.environ → 安全缺省，None＝交给下一级），
# `control_plane/__init__.py` 与 `domains/chat_reply/llm_engine/channel_health.py`
# 的 `_flag_value` 各自落到自己那条链的安全缺省。逻辑硬合并会改掉「读不出」那一格的
# 落点，故本批只把**撞词面的字集**收成一处，逻辑各件照旧。第二批再谈把另两枚抄位
# 也折进来（它们今天在 `tests/test_trigger_word_single_source.py` 的 `INTENTIONAL_UNITS`
# 上逐枚署名在册）。
#
# 为什么这本账不会因此变瞎（写死在这里，防下一位误读本段）：两枚词表都含纯数字格
# （`1`/`0`），而两本触发词账的词形谓词本来就不收纯数字元素——同族的
# `domains/chat_reply/llm_engine/ledger.py` `_TRUE_WORDS` 与 `domains/ops/monitor/error_report.py`
# `_BOOL_TRUE` 今天同样落在谓词之外。所以**新增可见声明单元＝0**；债能降只可能来自
# 「调用侧不再手打字面」，谁把手打字面抄回去，该尺的内联口当场记债（注毒腿 `test_poison_*`）。
# 两枚词表各住一格、同文件同批，`tests/test_group_policy.py` 有「全仓只准一处定义」的结构锁。
#: 「真」的字面集（入参须已 ``strip().lower()``）。词面只住这一格。
ENV_TRUE_WORDS: Final[frozenset[str]] = frozenset({"1", "true", "on", "yes"})
#: 「假」的字面集（同上口径）。词面只住这一格。
ENV_FALSE_WORDS: Final[frozenset[str]] = frozenset({"0", "false", "off", "no"})


def has_real_api_key(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return False
    return normalized not in {
        "<api_key>",
        "<real_api_key>",
        "your-api-key",
        "your_api_key",
        "replace-me",
        "replace_me",
        "sk-your-api-key",
        "test-key",
    }


def is_placeholder_model(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or normalized in {
        "<model_name>",
        "your-model-name",
        "your_model_name",
        "replace-me",
        "replace_me",
        "model-name",
    }


def base_url_error(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return "openai_base_url_missing"
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "openai_base_url_invalid"
    if parsed.username or parsed.password:
        return "openai_base_url_unsafe"
    return ""


def safe_openai_endpoint_url(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    safe_netloc = parsed.netloc
    if parsed.username or parsed.password:
        hostname = parsed.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        port = f":{parsed.port}" if parsed.port else ""
        safe_netloc = f"[redacted]@{hostname}{port}" if hostname else "[redacted]"
    normalized = urlunsplit(
        (
            parsed.scheme,
            safe_netloc,
            parsed.path,
            "",
            "",
        )
    )
    return normalize_openai_chat_endpoint(normalized)


def openai_compatible_preflight_errors(config: Config) -> list[str]:
    errors: list[str] = []
    if not has_real_api_key(config.bot_chat_api_key):
        errors.append("openai_api_key_missing")
    if is_placeholder_model(config.bot_chat_model):
        errors.append("openai_model_missing")
    base_url_result = base_url_error(config.bot_chat_base_url)
    if base_url_result:
        errors.append(base_url_result)
    errors.extend(llm_generation_parameter_errors(config))
    return errors


def llm_generation_parameter_errors(config: Config) -> list[str]:
    errors: list[str] = []
    if not _is_valid_temperature(config.bot_chat_temperature):
        errors.append("openai_temperature_invalid")
    if not _is_valid_max_tokens(config.bot_chat_max_tokens):
        errors.append("openai_max_tokens_invalid")
    if not _is_valid_timeout_seconds(config.bot_chat_timeout_seconds):
        errors.append("openai_timeout_seconds_invalid")
    return errors


def diagnostic_llm_temperature(config: Config) -> float:
    if not _is_valid_temperature(config.bot_chat_temperature):
        return 0.0
    return min(config.bot_chat_temperature, 0.3)


def diagnostic_llm_max_tokens(config: Config) -> int:
    if not _is_valid_max_tokens(config.bot_chat_max_tokens):
        return 0
    if config.bot_chat_max_tokens <= 0:
        # 聊天不设上限，但诊断短调用保持 128，避免浪费 token。
        return 128
    return min(config.bot_chat_max_tokens, 128)


def persona_context_preflight_errors(config: Config) -> list[str]:
    persona_paths = _configured_paths(config.bot_persona_files)
    if not persona_paths:
        return ["persona_files_empty"]
    persona_missing = [path for path in persona_paths if not path.exists()]
    persona_unsupported = _unsupported_character_paths(persona_paths)
    persona_readiness = _inspect_character_paths(
        persona_paths,
        missing_paths=persona_missing,
        unsupported_paths=persona_unsupported,
    )
    errors: list[str] = []
    if persona_missing:
        errors.append("persona_file_missing")
    if persona_unsupported:
        errors.append("persona_file_unsupported")
    if persona_readiness["unreadable"]:
        errors.append("persona_file_unreadable")
    if persona_readiness["empty"]:
        errors.append("persona_file_empty")
    return errors


def run_config_smoke(
    config: Config,
    *,
    env_path: str | Path | None = None,
) -> dict[str, Any]:
    persona_paths = _configured_paths(config.bot_persona_files)
    knowledge_paths = _configured_paths(config.bot_knowledge_files)
    persona_missing = [path for path in persona_paths if not path.exists()]
    knowledge_missing = [path for path in knowledge_paths if not path.exists()]
    persona_unsupported = _unsupported_character_paths(persona_paths)
    knowledge_unsupported = _unsupported_character_paths(knowledge_paths)
    persona_readiness = _inspect_character_paths_cached(
        persona_paths,
        missing_paths=persona_missing,
        unsupported_paths=persona_unsupported,
    )
    knowledge_readiness = _inspect_character_paths_cached(
        knowledge_paths,
        missing_paths=knowledge_missing,
        unsupported_paths=knowledge_unsupported,
    )
    errors: list[str] = []
    warnings: list[str] = []
    persona_strength_status = _persona_strength_status(persona_readiness)

    if not config.bot_chat_enabled:
        errors.append("chat_disabled")
    if not persona_paths:
        errors.append("persona_files_empty")
    if persona_missing:
        errors.append("persona_file_missing")
    if persona_unsupported:
        errors.append("persona_file_unsupported")
    if persona_readiness["unreadable"]:
        errors.append("persona_file_unreadable")
    if persona_readiness["empty"]:
        errors.append("persona_file_empty")
    if persona_strength_status == "weak":
        warnings.append("persona_profile_weak")
    if knowledge_missing:
        errors.append("knowledge_file_missing")
    if knowledge_unsupported:
        errors.append("knowledge_file_unsupported")
    if knowledge_readiness["unreadable"]:
        errors.append("knowledge_file_unreadable")

    provider_name = config.bot_chat_provider.strip()
    if provider_name == "static":
        warnings.append("provider_not_real")
    elif provider_name == "openai_compatible":
        errors.extend(openai_compatible_preflight_errors(config))
    else:
        errors.append("chat_provider_unsupported")

    if not knowledge_paths:
        warnings.append("knowledge_files_empty")
    if knowledge_readiness["empty"]:
        warnings.append("knowledge_file_empty")

    endpoint_url = safe_openai_endpoint_url(config.bot_chat_base_url)
    base_url_result = base_url_error(config.bot_chat_base_url)
    api_key_state = "set" if has_real_api_key(config.bot_chat_api_key) else "missing"
    ready_for_real_llm = (
        not errors
        and provider_name == "openai_compatible"
        and api_key_state == "set"
        and bool(config.bot_chat_model.strip())
        and not base_url_result
    )
    llm_readiness_reasons = _dedupe_reasons([*errors, *warnings])
    llm_fix_hints = llm_readiness_fix_hints(errors=errors, warnings=warnings)
    if ready_for_real_llm:
        llm_readiness_status = "ready"
    elif errors:
        llm_readiness_status = "blocked"
    else:
        llm_readiness_status = "local_only"
    llm_next_action = _llm_next_action(
        ready_for_real_llm=ready_for_real_llm,
        errors=errors,
    )
    ok = not errors
    if ok and ready_for_real_llm:
        public_message = "配置体检通过：基础对话和真实 LLM provider 配置已具备。"
    elif ok:
        public_message = "配置体检通过：本地基础对话链路可用，但真实 LLM provider 尚未就绪。"
    else:
        public_message = "配置体检未通过：请先修复 errors 中的配置项，再接入真实 LLM 对话。"

    return {
        "ok": ok,
        "ready_for_real_llm": ready_for_real_llm,
        "llm_readiness_status": llm_readiness_status,
        "llm_readiness_reasons": llm_readiness_reasons,
        "llm_fix_hints": llm_fix_hints,
        "llm_next_action": llm_next_action,
        "env_file": str(env_path) if env_path is not None else "",
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "runtime_enabled": config.bot_runtime_enabled,
        "chat_enabled": config.bot_chat_enabled,
        "persona_profile_id": config.bot_persona_profile_id,
        "persona_display_name": config.bot_persona_display_name,
        "persona_files": len(persona_paths),
        "persona_missing": len(persona_missing),
        "persona_unsupported": len(persona_unsupported),
        "persona_readable": persona_readiness["readable"],
        "persona_empty": persona_readiness["empty"],
        "persona_unreadable": persona_readiness["unreadable"],
        "persona_total_chars": persona_readiness["total_chars"],
        "persona_meaningful_lines": persona_readiness["meaningful_lines"],
        "persona_strength_status": persona_strength_status,
        "knowledge_files": len(knowledge_paths),
        "knowledge_missing": len(knowledge_missing),
        "knowledge_unsupported": len(knowledge_unsupported),
        "knowledge_readable": knowledge_readiness["readable"],
        "knowledge_empty": knowledge_readiness["empty"],
        "knowledge_unreadable": knowledge_readiness["unreadable"],
        "knowledge_total_chars": knowledge_readiness["total_chars"],
        "knowledge_meaningful_lines": knowledge_readiness["meaningful_lines"],
        "memory_enabled": config.bot_memory_enabled,
        "history_enabled": config.bot_history_enabled,
        "history_max_items": config.bot_history_max_items,
        "emotion_enabled": config.bot_emotion_enabled,
        "rate_limit_enabled": config.bot_rate_limit_enabled,
        "rate_limit_window_seconds": config.bot_rate_limit_window_seconds,
        "rate_limit_chat_global_max_requests": (
            config.bot_rate_limit_chat_global_max_requests
        ),
        "rate_limit_chat_session_max_requests": (
            config.bot_rate_limit_chat_session_max_requests
        ),
        "rate_limit_chat_sender_max_requests": (
            config.bot_rate_limit_chat_sender_max_requests
        ),
        "rate_limit_target_min_interval_seconds": (
            config.bot_rate_limit_target_min_interval_seconds
        ),
        "rate_limit_bypass_roles": ",".join(config.bot_rate_limit_bypass_roles),
        "rate_limit_store": "sqlite" if config.bot_rate_limit_db_path else "memory",
        "rate_limit_db": "set" if config.bot_rate_limit_db_path else "missing",
        "quiet_hours_enabled": config.bot_quiet_hours_enabled,
        "quiet_hours_start": config.bot_quiet_hours_start,
        "quiet_hours_end": config.bot_quiet_hours_end,
        "quiet_hours_timezone": config.bot_quiet_hours_timezone,
        "quiet_hours_session_types": ",".join(config.bot_quiet_hours_session_types),
        "quiet_hours_bypass_roles": ",".join(config.bot_quiet_hours_bypass_roles),
        "diagnostics_enabled": config.bot_diagnostics_enabled,
        "audit_enabled": config.bot_audit_enabled,
        "receipts_enabled": config.bot_receipts_enabled,
        "send_queue_enabled": config.bot_send_queue_enabled,
        "send_queue_store": (
            "sqlite"
            if config.bot_send_queue_enabled and config.bot_send_queue_db_path
            else "memory"
        ),
        "send_queue_db": "set" if config.bot_send_queue_db_path else "missing",
        "send_queue_max_items": config.bot_send_queue_max_items,
        "send_queue_max_attempts": config.bot_send_queue_max_attempts,
        "send_queue_retry_base_seconds": config.bot_send_queue_retry_base_seconds,
        "send_queue_retry_max_seconds": config.bot_send_queue_retry_max_seconds,
        "send_queue_worker_enabled": config.bot_send_queue_worker_enabled,
        "send_queue_worker_interval_seconds": (
            config.bot_send_queue_worker_interval_seconds
        ),
        "send_queue_worker_batch_size": config.bot_send_queue_worker_batch_size,
        "chat_provider": provider_name,
        "chat_model": config.bot_chat_model,
        "chat_api_key": api_key_state,
        "chat_temperature": config.bot_chat_temperature,
        "chat_max_tokens": config.bot_chat_max_tokens,
        "base_url": endpoint_url.removesuffix("/chat/completions"),
        "endpoint_url": endpoint_url,
        "timeout_seconds": config.bot_chat_timeout_seconds,
        "public_message": public_message,
    }


def _configured_paths(paths: list[str]) -> list[Path]:
    return [Path(path).expanduser() for path in paths if str(path).strip()]


def _dedupe_reasons(reasons: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for reason in reasons:
        normalized = reason.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _persona_strength_status(readiness: dict[str, int]) -> str:
    if readiness["readable"] <= 0 or readiness["total_chars"] <= 0:
        return "missing"
    if (
        readiness["total_chars"] < PERSONA_PROFILE_MIN_CHARS
        or readiness["meaningful_lines"] < PERSONA_PROFILE_MIN_MEANINGFUL_LINES
    ):
        return "weak"
    return "ok"


def _llm_next_action(*, ready_for_real_llm: bool, errors: list[str]) -> str:
    if errors:
        return "fix_config"
    if ready_for_real_llm:
        return "llm_smoke"
    return "configure_real_llm"


def llm_readiness_fix_hints(*, errors: list[str], warnings: list[str]) -> list[str]:
    reasons = errors if errors else warnings
    hint_by_reason = {
        "chat_disabled": "BOT_CHAT_ENABLED=true",
        "persona_files_empty": "BOT_PERSONA_FILES=<existing_md_txt_docx_paths>",
        "persona_file_missing": "BOT_PERSONA_FILES=<existing_md_txt_docx_paths>",
        "persona_file_unsupported": "BOT_PERSONA_FILES=<existing_md_txt_docx_paths>",
        "persona_file_unreadable": "BOT_PERSONA_FILES=<existing_md_txt_docx_paths>",
        "persona_file_empty": "BOT_PERSONA_FILES=<existing_md_txt_docx_paths>",
        "knowledge_file_missing": (
            "BOT_KNOWLEDGE_FILES=<optional_existing_md_txt_docx_paths>"
        ),
        "knowledge_file_unsupported": (
            "BOT_KNOWLEDGE_FILES=<optional_existing_md_txt_docx_paths>"
        ),
        "knowledge_file_unreadable": (
            "BOT_KNOWLEDGE_FILES=<optional_existing_md_txt_docx_paths>"
        ),
        "knowledge_files_empty": (
            "BOT_KNOWLEDGE_FILES=<optional_existing_md_txt_docx_paths>"
        ),
        "knowledge_file_empty": (
            "BOT_KNOWLEDGE_FILES=<optional_existing_md_txt_docx_paths>"
        ),
        "provider_not_real": "BOT_CHAT_PROVIDER=openai_compatible",
        "chat_provider_unsupported": "BOT_CHAT_PROVIDER=openai_compatible",
        "openai_api_key_missing": "BOT_CHAT_API_KEY=<real_api_key>",
        "openai_model_missing": "BOT_CHAT_MODEL=<model_name>",
        "openai_base_url_missing": "BOT_CHAT_BASE_URL=<openai_compatible_base_url>",
        "openai_base_url_invalid": "BOT_CHAT_BASE_URL=<openai_compatible_base_url>",
        "openai_base_url_unsafe": "remove_credentials_from_BOT_CHAT_BASE_URL",
        "openai_temperature_invalid": "BOT_CHAT_TEMPERATURE=0.0..2.0",
        "openai_max_tokens_invalid": "BOT_CHAT_MAX_TOKENS>=0（0=不设上限）",
        "openai_timeout_seconds_invalid": "BOT_CHAT_TIMEOUT_SECONDS>0",
    }
    return _dedupe_reasons(
        [hint_by_reason[reason] for reason in reasons if reason in hint_by_reason]
    )


def _is_valid_temperature(value: float) -> bool:
    return math.isfinite(value) and 0.0 <= value <= 2.0


def _is_valid_max_tokens(value: int) -> bool:
    # 0 表示不设上限（不向 API 传 max_tokens）；负数非法。
    return not isinstance(value, bool) and value >= 0


def _is_valid_timeout_seconds(value: float) -> bool:
    return math.isfinite(value) and value > 0


def _unsupported_character_paths(paths: list[Path]) -> list[Path]:
    return [
        path
        for path in paths
        if path.suffix.lower() not in SUPPORTED_CHARACTER_DOCUMENT_SUFFIXES
    ]


# 诊断路径每条消息都会跑 run_config_smoke：人格/知识文件全文读盘（.docx 还要
# 解 zip）是热路径单点最重开销。按「路径+mtime+size」签名缓存文件检查结果，
# 文件未变化时零读盘；只缓存读取部分，配置标量仍每次现算。
_READINESS_INSPECT_CACHE: dict[tuple, dict[str, int]] = {}
_READINESS_INSPECT_CACHE_LOCK = threading.Lock()
_READINESS_INSPECT_CACHE_MAX_ENTRIES = 8


def _reset_readiness_cache() -> None:
    """清空文件检查缓存（测试用）。"""
    with _READINESS_INSPECT_CACHE_LOCK:
        _READINESS_INSPECT_CACHE.clear()


def _inspect_signature(
    paths: list[Path],
    *,
    missing_paths: list[Path],
    unsupported_paths: list[Path],
) -> tuple:
    missing_set = {path.resolve() for path in missing_paths}
    unsupported_set = {path.resolve() for path in unsupported_paths}
    signature: list[tuple] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            signature.append((str(path), "resolve_error"))
            continue
        if resolved in missing_set or resolved in unsupported_set:
            continue
        try:
            status = path.stat()
        except OSError:
            signature.append((str(resolved), "stat_error"))
            continue
        signature.append((str(resolved), status.st_mtime_ns, status.st_size))
    return tuple(signature)


def _inspect_character_paths_cached(
    paths: list[Path],
    *,
    missing_paths: list[Path],
    unsupported_paths: list[Path],
) -> dict[str, int]:
    signature = _inspect_signature(
        paths, missing_paths=missing_paths, unsupported_paths=unsupported_paths
    )
    with _READINESS_INSPECT_CACHE_LOCK:
        cached = _READINESS_INSPECT_CACHE.get(signature)
    if cached is not None:
        return cached
    result = _inspect_character_paths(
        paths,
        missing_paths=missing_paths,
        unsupported_paths=unsupported_paths,
    )
    with _READINESS_INSPECT_CACHE_LOCK:
        if len(_READINESS_INSPECT_CACHE) >= _READINESS_INSPECT_CACHE_MAX_ENTRIES:
            _READINESS_INSPECT_CACHE.clear()
        _READINESS_INSPECT_CACHE[signature] = result
    return result


def _inspect_character_paths(
    paths: list[Path],
    *,
    missing_paths: list[Path],
    unsupported_paths: list[Path],
) -> dict[str, int]:
    missing_set = {path.resolve() for path in missing_paths}
    unsupported_set = {path.resolve() for path in unsupported_paths}
    readable = 0
    empty = 0
    unreadable = 0
    total_chars = 0
    meaningful_lines = 0
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            unreadable += 1
            continue
        if resolved in missing_set or resolved in unsupported_set:
            continue
        try:
            text = load_character_document(path)
        except Exception:  # noqa: BLE001 - readiness emits safe counters, not raw parser errors.
            unreadable += 1
            continue
        readable += 1
        stripped_text = text.strip()
        if not stripped_text:
            empty += 1
            continue
        total_chars += len(stripped_text)
        meaningful_lines += len(_meaningful_lines(stripped_text))
    return {
        "readable": readable,
        "empty": empty,
        "unreadable": unreadable,
        "total_chars": total_chars,
        "meaningful_lines": meaningful_lines,
    }


def _meaningful_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
