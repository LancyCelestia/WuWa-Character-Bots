"""守岸人语音合成能力（bot.tts）：文本 → 守岸人音色的语音消息。

对接本机 GPT-SoVITS v2ProPlus 的 ``api_v2.py`` HTTP 接口（默认 9880）。

设计：

- **独立能力，零侵入既有链路**：本模块只读配置、只调 HTTP、只把 wav 落到
  运行时目录；出站复用 renderer 既有的 audio 部件通道
  （``CapabilityResult.audio`` → ``{"type":"record"}`` → ``sender/onebot``），
  不改 chat / pipeline / renderer / sender 任何一行。
- **参考音频**：``BOT_TTS_REF_AUDIOS`` 每项形如 ``路径|参考文本|语种``，
  多项时随机轮换，贴合不同语气；路径可为绝对路径，也可相对
  ``BOT_TTS_GPTSOVITS_DIR``（GPT-SoVITS 程序目录）。
  参考音频硬性要求 3~10 秒干声，超出会被服务端直接拒绝。
- **缓存**：文本 + 参考音频 + 采样参数 → sha256 命名，命中直接复用已有
  wav（``BOT_TTS_CACHE_ENABLED`` 默认开），同一句话不重复合成。
- **fail-open**：服务未启动 / 超时 / 非 200 → 返回守岸人口吻的降级文案，
  绝不抛异常、绝不阻断出站管线（与 randpic 同哲学）。
- **对话自动配音**（可选）：``BOT_TTS_AUTO_REPLY_ENABLED`` 开启后，
  ``maybe_attach_voice()`` 把人格回复正文一并合成为语音随消息发出，
  由 ``__init__`` 的 chat 能力包装层调用。是否真的配音由
  ``should_voice_reply()`` 统一裁决：总开关 / 自动配音开关 / 未带音频 /
  出自 ``bot.chat`` / 会话范围（``BOT_TTS_AUTO_REPLY_SCOPE``）/ 概率门
  （``BOT_TTS_AUTO_REPLY_PROBABILITY``，默认 5%，确定性哈希实现，
  同一条消息结果恒定可复现）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    OperationalIssue,
    SendPolicy,
)

# 合成前的内容门与打码：复用中央单一事实源，**绝不在本域抄一份**。
# 抄一份就等于再造一条「文字面拦、语音面放」的红线漂移面（审计 M-02 根因）。
# 分层注记：media → chat_reply/render 属跨域直连，正解是中央 hook（修复波 S13/S14
# 待施工）；在 hook 落地前，直连中央真身比各域自带副本更安全，故如此接线。
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    explicit_allowed_for_session,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.content_safety import (
    assess_public_content,
)
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)

# 触发词（T-Spec 口径）：中文 + 英文 + 拼音全拼/缩写。
# 边界判定沿用 randpic 的保守哲学——整句等于触发词，或触发词后紧跟
# 标点/空白，避免「说话」「念书」「语音消息」这类包含关系词误触发。
# 「语音合成」与 help 主题别名同源：帮助里列出的词，路由面必须真能命中
# （tests/test_trigger_bidirectional_gate.py 的词级双向门锁定这件事）。
DEFAULT_TRIGGER_WORDS: tuple[str, ...] = (
    "语音合成", "朗读", "语音", "念", "说",
    "tts", "say", "shuo", "yuyin", "nian", "langdu",
)
# 触发词与正文之间的分隔字符（取正文时剥掉）。
# ⚠️ 这里**只能放真分隔符**（标点与空白），一个词字符都不能进：曾经收录过
# 「了/的/呢/吗/呀/啊/哈」，于是「说了再见」「说的对」「语音哈喽」这类日常聊天
# 被整句吞进 bot.tts（priority 41 + block=True ⇒ 消息不再进人格对话），并把
# 「再见」「对」「喽」这种残片念出去。实测 312 句日常中文劫持率 68.1%。
# 回归锁见 tests/test_tts_hijack_guard.py（含"边界集合不得出现汉字"的棘轮断言）。
_TEXT_BOUNDARY_CHARS = "，,。！？!?：:、 　\t～~"

# 参考音频时长合规区间（3~10 秒）由服务端硬卡（TTS.py 的 _set_prompt_semantic），
# 本地不做重复预检：ChatBot 运行环境没有 soundfile/mutagen，读不了时长；
# 越界时服务端会在错误体 Exception 里给出可读原因，经 _request_tts 透传到
# _degrade 的「参考音频」分支，用户侧提示已经足够。
# 单次合成文本上限兜底（配置未给时生效）。
_DEFAULT_MAX_CHARS = 200
# 采样参数默认值（与守岸人预设卡一致）。
_DEFAULT_SPEED_FACTOR = 0.85
_DEFAULT_TEMPERATURE = 0.9
_DEFAULT_TOP_K = 15
_DEFAULT_TOP_P = 1.0
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_TEXT_LANG = "zh"
_DEFAULT_SPLIT_METHOD = "cut5"
# 对话自动配音的默认触发概率（5%）：常态下只有二十分之一的回复会带语音，
# 避免刷屏与合成排队；BOT_TTS_AUTO_REPLY_ALWAYS=true 可跳过概率门。
_DEFAULT_AUTO_REPLY_PROBABILITY = 0.05

# 合成结果缓存（进程内 LRU 索引）：key → (落盘路径, 写入时刻)。
# 键数封顶，避免长跑进程按文本无界增长（对齐 runtime/reactions.py 惯例）。
_CACHE_LRU_CAP = 512
_CACHE: OrderedDict[str, tuple[Path, float]] = OrderedDict()

# 服务健康探测节流：连续失败后短时间内不再重复打服务，避免刷日志。
_HEALTH_BACKOFF_SECONDS = 30.0
_last_failure_at: float = 0.0
_last_failure_reason: str = ""

# 朗读前清洗用正则：代码围栏 / 行内代码 / markdown 强调符 / 链接 / 颜文字括号。
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+")
_MARKDOWN_MARKS_RE = re.compile(r"[*_#>~|]+")
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-+•]|\d+[.)])\s*", re.MULTILINE)
# 中央打码占位符（`plain_text._SECRET_VALUE_PLACEHOLDER`）的残缺形态：清洗会吃掉
# 它的尖括号，朗读前替换成能念的词。
_REDACTION_PLACEHOLDER_RE = re.compile(r"<已隐藏[^<>]*>?")
_BLANK_LINES_RE = re.compile(r"\n{2,}")
_SPACES_RE = re.compile(r"[ \t]{2,}")
_SENTENCE_END = "。！？…!?；;"


@dataclass(frozen=True)
class RefAudio:
    """一条参考音频及其逐字文本（prompt_text）。

    ``text`` 为空表示走「无参考文本模式」——服务端自行从音频推断内容。
    """

    path: str
    text: str = ""
    lang: str = _DEFAULT_TEXT_LANG


@dataclass(frozen=True)
class TtsParams:
    """一次合成的采样参数快照（参与缓存键计算）。"""

    text_lang: str
    speed_factor: float
    temperature: float
    top_k: int
    top_p: float
    text_split_method: str


def is_tts_command(
    text: str, trigger_words: list[str] | tuple[str, ...] | None = None
) -> bool:
    """触发词判定：整句等于触发词，或触发词后紧跟标点/空白边界。"""
    return bool(extract_tts_text(text, trigger_words))


def extract_tts_text(
    text: str, trigger_words: list[str] | tuple[str, ...] | None = None
) -> str:
    """取出触发句里要合成的正文；不命中触发词返回空串。

    最长触发词优先匹配，避免短词截断长词（``tts`` 之于 ``tts`` 前缀词）。
    """
    triggers = tuple(trigger_words) if trigger_words else DEFAULT_TRIGGER_WORDS
    stripped = (text or "").strip()
    if not stripped:
        return ""
    for word in sorted({w.strip() for w in triggers if w.strip()}, key=len, reverse=True):
        if stripped == word:
            # 只发了触发词、没带正文：由调用方给引导文案。
            return ""
        if not stripped.startswith(word):
            continue
        tail = stripped[len(word):]
        if not tail or tail[0] not in _TEXT_BOUNDARY_CHARS:
            continue
        return tail.lstrip(_TEXT_BOUNDARY_CHARS).strip()
    return ""


def parse_ref_audios(
    items: list[str] | tuple[str, ...] | None, *, base_dir: str = ""
) -> list[RefAudio]:
    """解析 ``BOT_TTS_REF_AUDIOS``：每项 ``路径|参考文本|语种``（后两段可省）。"""
    parsed: list[RefAudio] = []
    for raw in items or []:
        item = str(raw).strip()
        if not item:
            continue
        parts = item.split("|")
        path = parts[0].strip()
        if not path:
            continue
        text = parts[1].strip() if len(parts) > 1 else ""
        lang = parts[2].strip() if len(parts) > 2 and parts[2].strip() else _DEFAULT_TEXT_LANG
        resolved = _resolve_ref_path(path, base_dir)
        parsed.append(RefAudio(path=str(resolved), text=text, lang=lang))
    return parsed


def _resolve_ref_path(path: str, base_dir: str) -> Path:
    """参考音频路径解析：绝对路径原样用；相对路径挂到 GPT-SoVITS 程序目录下。"""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if base_dir.strip():
        return Path(base_dir.strip()) / candidate
    return candidate


def pick_ref_audio(
    items: list[str] | tuple[str, ...] | None,
    *,
    base_dir: str = "",
    rng: random.Random | None = None,
) -> RefAudio | None:
    """随机挑一条**文件确实存在**的参考音频；一条都没有则返回 None。"""
    candidates = [
        ref for ref in parse_ref_audios(items, base_dir=base_dir) if Path(ref.path).is_file()
    ]
    if not candidates:
        return None
    return (rng or random).choice(candidates)


def clean_for_speech(text: str, *, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    """把回复正文清洗成适合朗读的纯文本。

    去掉代码块/行内代码/链接/markdown 标记与列表前缀——这些东西念出来只会
    变成一串噪音。超长文本在句子边界截断，避免读到一半断气。
    """
    value = str(text or "")
    if not value.strip():
        return ""
    value = _FENCE_RE.sub(" ", value)
    value = _INLINE_CODE_RE.sub(" ", value)
    value = _URL_RE.sub(" ", value)
    value = _MARKDOWN_MARKS_RE.sub("", value)
    value = _LIST_PREFIX_RE.sub("", value)
    value = _BLANK_LINES_RE.sub("\n", value)
    value = _SPACES_RE.sub(" ", value)
    value = value.replace("\n", " ").strip()
    if max_chars > 0 and len(value) > max_chars:
        value = _truncate_at_sentence(value, max_chars)
    return value


def _truncate_at_sentence(text: str, limit: int) -> str:
    """在 limit 以内尽量切在句末标点处。"""
    window = text[:limit]
    for index in range(len(window) - 1, max(0, limit - 40), -1):
        if window[index] in _SENTENCE_END:
            return window[: index + 1]
    return window


def _cache_key(text: str, ref: RefAudio, params: TtsParams) -> str:
    payload = json.dumps(
        {
            "text": text,
            "ref": ref.path,
            "ref_text": ref.text,
            "ref_lang": ref.lang,
            "params": {
                "text_lang": params.text_lang,
                "speed_factor": params.speed_factor,
                "temperature": params.temperature,
                "top_k": params.top_k,
                "top_p": params.top_p,
                "text_split_method": params.text_split_method,
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _lookup_cache(key: str) -> Path | None:
    cached = _CACHE.get(key)
    if cached is None:
        return None
    path, _at = cached
    if not path.is_file():
        _CACHE.pop(key, None)
        return None
    _CACHE.move_to_end(key)
    return path


def _store_cache(key: str, path: Path) -> None:
    _CACHE[key] = (path, time.monotonic())
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_LRU_CAP:
        _CACHE.popitem(last=False)


def _request_tts(
    *,
    api_url: str,
    text: str,
    ref: RefAudio,
    params: TtsParams,
    timeout_seconds: float,
) -> bytes | None:
    """调用 api_v2.py 的 ``POST /tts``，返回 wav 字节；失败返回 None。

    异常一律吞掉并记账（fail-open）——调用方据此给降级文案。
    """
    global _last_failure_at, _last_failure_reason
    try:
        import httpx
    except Exception:  # noqa: BLE001 - 缺依赖按服务不可用处理。
        _last_failure_reason = "httpx 不可用"
        return None

    endpoint = f"{api_url.rstrip('/')}/tts"
    payload: dict[str, Any] = {
        "text": text,
        "text_lang": params.text_lang,
        "ref_audio_path": ref.path,
        "prompt_text": ref.text,
        "prompt_lang": ref.lang,
        "top_k": params.top_k,
        "top_p": params.top_p,
        "temperature": params.temperature,
        "text_split_method": params.text_split_method,
        "batch_size": 1,
        "batch_threshold": 0.75,
        "split_bucket": True,
        "speed_factor": params.speed_factor,
        "fragment_interval": 0.3,
        "seed": -1,
        "media_type": "wav",
        "streaming_mode": False,
        "parallel_infer": True,
        "repetition_penalty": 1.35,
    }
    try:
        with httpx.Client(timeout=max(1.0, float(timeout_seconds))) as client:
            response = client.post(endpoint, json=payload)
    except Exception as exc:  # noqa: BLE001 - 连接/超时统一按失败降级。
        _last_failure_at = time.monotonic()
        _last_failure_reason = f"服务不可达：{type(exc).__name__}"
        logger.info("tts request failed: %s", exc)
        return None
    if response.status_code != 200:
        _last_failure_at = time.monotonic()
        # 错误体形如 {"message": "tts failed", "Exception": "<真原因>"}
        # （api_v2.py 的兜底包装）：真原因在 Exception 里，message 只是固定摘要，
        # 故必须先取 Exception，否则 3~10 秒越界这类可读原因会被吞成 "tts failed"，
        # 下游 _degrade 的「参考音频」分支永远命不中。
        try:
            error_body: Any = response.json()
        except Exception:  # noqa: BLE001 - 错误体非 JSON 时退回纯文本。
            error_body = None
        if isinstance(error_body, dict):
            detail = str(error_body.get("Exception") or error_body.get("message") or "")
        elif isinstance(error_body, str):
            detail = error_body[:200]
        else:
            detail = (response.text or "")[:200]
        _last_failure_reason = f"服务返回 {response.status_code}：{detail[:160]}"
        logger.info("tts request rejected: %s %s", response.status_code, detail)
        return None
    if not response.content:
        _last_failure_at = time.monotonic()
        _last_failure_reason = "服务返回空音频"
        return None
    _last_failure_reason = ""
    return response.content


def synthesize(
    *,
    api_url: str,
    text: str,
    ref: RefAudio,
    params: TtsParams,
    output_dir: Path,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    cache_enabled: bool = True,
) -> tuple[Path | None, str]:
    """合成一段语音并落盘，返回 ``(wav 路径, 失败原因)``；成功时原因为空串。"""
    key = _cache_key(text, ref, params)
    if cache_enabled:
        hit = _lookup_cache(key)
        if hit is not None:
            return hit, ""
    audio = _request_tts(
        api_url=api_url, text=text, ref=ref, params=params, timeout_seconds=timeout_seconds
    )
    if audio is None:
        return None, _last_failure_reason or "合成失败"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{key}.wav"
        target.write_bytes(audio)
    except OSError as exc:
        logger.info("tts write failed: %s", exc)
        return None, f"音频落盘失败：{type(exc).__name__}"
    if cache_enabled:
        _store_cache(key, target)
    return target, ""


def _build_params(config: Any) -> TtsParams:
    return TtsParams(
        text_lang=str(getattr(config, "bot_tts_text_lang", _DEFAULT_TEXT_LANG) or _DEFAULT_TEXT_LANG),
        speed_factor=float(getattr(config, "bot_tts_speed_factor", _DEFAULT_SPEED_FACTOR)),
        temperature=float(getattr(config, "bot_tts_temperature", _DEFAULT_TEMPERATURE)),
        top_k=int(getattr(config, "bot_tts_top_k", _DEFAULT_TOP_K)),
        top_p=float(getattr(config, "bot_tts_top_p", _DEFAULT_TOP_P)),
        text_split_method=str(
            getattr(config, "bot_tts_text_split_method", _DEFAULT_SPLIT_METHOD)
            or _DEFAULT_SPLIT_METHOD
        ),
    )


def _output_dir(config: Any) -> Path:
    raw = str(getattr(config, "bot_tts_output_dir", "") or "data/tts_output")
    return Path(raw)


def _degrade(reason: str) -> str:
    """合成失败时的守岸人口吻降级文案（不暴露内部细节，只给可读方向）。"""
    if "不可达" in reason:
        return "嗓子还没接上——语音服务好像没在跑，稍后再叫我一次吧。"
    if "3~10秒" in reason or "参考音频" in reason:
        return "还差一段合适的参考音频：3 到 10 秒的干声，我才能借到自己的音色。"
    return "这次没能发出声音……等一下再试，或者先听听我打字说的话吧。"


def _no_ref_audio_hint(config: Any) -> str:
    items = list(getattr(config, "bot_tts_ref_audios", []) or [])
    if not items:
        return (
            "还没有给我配参考音频。请在 BOT_TTS_REF_AUDIOS 里填一条 "
            "「音频路径|这段音频说的话」，3 到 10 秒的干声最合适。"
        )
    return (
        "配置里的参考音频文件都找不到——检查 BOT_TTS_REF_AUDIOS 的路径"
        "（相对路径以 BOT_TTS_GPTSOVITS_DIR 为基准）。"
    )


_ISSUE_STAGE = "tts"

_ISSUE_SUMMARY_MAX_CHARS = 200

# 失败原因前缀 → (kind, retryable)：`_request_tts`/`synthesize` 的原因串是本域
# 自己拼的固定前缀，故按前缀分类即可，不看引擎原文（原文只进 safe_summary）。
_FAILURE_KINDS: tuple[tuple[str, str, bool], ...] = (
    ("服务不可达", "tts_service_unreachable", True),
    ("httpx", "tts_service_unreachable", True),
    ("服务返回空音频", "tts_empty_audio", True),
    ("服务返回", "tts_service_rejected", False),
    ("音频落盘失败", "tts_write_failed", False),
)


def _issue(
    message: IncomingMessage,
    *,
    kind: str,
    retryable: bool,
    detail: str = "",
) -> OperationalIssue:
    """语音失败的结构化证据（审计 M-13）。

    本域 logger 不在 nonebot 日志树上，`logger.info` 在生产直接丢失；只有挂上
    ``operational_issue``，中央回执链才会告警、错误报告卡才会挂——否则引擎整夜
    不跑而管理员毫不知情。

    ``safe_summary`` 必过 ``redact_local_secrets``：issue 会进诊断卡与管理员私聊，
    而引擎错误体常带本机绝对路径（AGENTS 铁律 3：打码不得绕过）。
    """
    raw = f"{kind}: {detail}" if detail else kind
    return OperationalIssue(
        stage=_ISSUE_STAGE,
        kind=kind,
        retryable=retryable,
        debug_id=message.debug_id,
        safe_summary=redact_local_secrets(raw)[:_ISSUE_SUMMARY_MAX_CHARS].strip(),
    )


def _failure_issue(message: IncomingMessage, reason: str) -> OperationalIssue:
    for prefix, kind, retryable in _FAILURE_KINDS:
        if reason.startswith(prefix):
            return _issue(message, kind=kind, retryable=retryable, detail=reason)
    return _issue(message, kind="tts_synthesize_failed", retryable=False, detail=reason)


def _no_ref_audio_issue(message: IncomingMessage, config: Any) -> OperationalIssue:
    configured = list(getattr(config, "bot_tts_ref_audios", []) or [])
    detail = (
        "BOT_TTS_REF_AUDIOS 未配置"
        if not configured
        else "BOT_TTS_REF_AUDIOS 中的音频文件全部读不到（路径或基准目录不对）"
    )
    return _issue(message, kind="tts_no_ref_audio", retryable=False, detail=detail)


def build_tts_capability(config: Any | None = None) -> Any:
    """构建语音合成能力：返回 ``(message, decision) -> CapabilityResult``。

    与 randpic / eat 等能力同构，可在 offload 线程池里同步执行
    （HTTP 调用是阻塞的，绝不能跑在事件循环线程上）。
    """

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        if not bool(getattr(config, "bot_tts_enabled", False)):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["tts", "skip_disabled"],
            )
        triggers = list(getattr(config, "bot_tts_trigger_words", []) or [])
        body = extract_tts_text(message.plain_text or "", triggers or None)
        if not body:
            # 只发了触发词（「说」「语音」）：给用法引导，不做无意义的空合成。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                title="",
                body="在「说」后面接上想让我念的话就行，比如：说 今天的潮汐很安静。",
                audit_tags=["tts", "missing_text"],
            )

        max_chars = int(getattr(config, "bot_tts_max_chars", _DEFAULT_MAX_CHARS) or _DEFAULT_MAX_CHARS)
        speech, blocked = resolve_speech_text(
            config, message, body, max_chars=max_chars
        )
        if blocked:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body=_speech_refusal_hint(),
                audit_tags=["tts", "blocked_by_policy"],
            )
        if not speech:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body="这段话里没有能念出来的内容——换一句试试？",
                audit_tags=["tts", "empty_after_clean"],
            )

        ref = pick_ref_audio(
            getattr(config, "bot_tts_ref_audios", []) or [],
            base_dir=str(getattr(config, "bot_tts_gptsovits_dir", "") or ""),
        )
        if ref is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body=_no_ref_audio_hint(config),
                audit_tags=["tts", "no_ref_audio"],
                operational_issue=_no_ref_audio_issue(message, config),
            )

        path, reason = synthesize(
            api_url=str(getattr(config, "bot_tts_api_url", "") or "http://127.0.0.1:9880"),
            text=speech,
            ref=ref,
            params=_build_params(config),
            output_dir=_output_dir(config),
            timeout_seconds=float(
                getattr(config, "bot_tts_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
            ),
            cache_enabled=bool(getattr(config, "bot_tts_cache_enabled", True)),
        )
        if path is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body=_degrade(reason),
                audit_tags=["tts", "synthesize_failed"],
                operational_issue=_failure_issue(message, reason),
            )
        # 与 randpic 同口径：title/body 留空，只发媒体本体，
        # 否则 renderer 的 body→summary→title 兜底链会把标题当文案一起发出去。
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.tts",
            kind="text",
            title="",
            body="",
            audio=[{"file": str(path), "review_text": speech}],
            audit_tags=["tts", "sent"],
        )

    return capability


def _session_kind(message: IncomingMessage) -> str:
    """会话类型取字符串形态（枚举取 ``.value``，缺省按私聊口径）。"""
    kind = getattr(message, "session_type", "")
    return str(getattr(kind, "value", kind) or "")


def speech_block_reason(config: Any, message: IncomingMessage, text: str) -> str:
    """内容政策裁决：这段文字能不能被**念出来**。返回 ""=放行，非空=拒绝理由位。

    与文字面共用同一个 `assess_public_content` 与同一个 `explicit_allowed` 单一
    事实源——文字能说的语音就能说，文字被拦的语音必须一起被拦（M-02 的根修）。
    政策件不可用时 **fail-closed**：拒的是配音、留的是文字，用户侧几乎无损；
    反过来 fail-open 就是把红线音频永久落盘并发出去。
    """
    kind = _session_kind(message) or "private"
    try:
        explicit = explicit_allowed_for_session(
            kind,
            str(getattr(message, "group_id", "") or ""),
            config,
            str(getattr(message, "sender_id", "") or ""),
        )
        verdict = assess_public_content(
            text,
            session_type=kind,
            explicit_allowed=bool(explicit),
        )
    except Exception as exc:  # noqa: BLE001 - 政策件异常按不放行处理。
        logger.warning("tts speech policy unavailable, refusing synthesis: %s", exc)
        return "policy_unavailable"
    if str(getattr(verdict, "action", "allow")) != "allow":
        category = str(getattr(verdict, "category", "") or "policy_refused")
        logger.warning("tts speech refused by content policy: category=%s", category)
        return category
    return ""


def resolve_speech_text(
    config: Any,
    message: IncomingMessage,
    raw_text: str,
    *,
    max_chars: int | None = None,
) -> tuple[str, str]:
    """合成前**唯一**的取文口：打码 → 清洗 → 内容门。返回 ``(可朗读正文, 拒绝理由)``。

    打码必须在最前面：`clean_for_speech` 会吃掉 `_` 与 `>`，先把
    ``BOT_SUPER_ADMIN_API_KEY=x`` 洗成 ``BOTSUPERADMINAPIKEY=x`` 之后，
    中央两条打码正则（`_BOT_ENV_ASSIGN_RE` / `_BARE_KEY_VALUE_RE`）双双失配，
    密钥就跟着音频出门了（M-03 的根修）。
    """
    value = redact_local_secrets(str(raw_text or ""))
    limit = max_chars
    if limit is None:
        limit = int(getattr(config, "bot_tts_max_chars", _DEFAULT_MAX_CHARS) or _DEFAULT_MAX_CHARS)
    speech = clean_for_speech(value, max_chars=int(limit))
    # 打码占位符 `<已隐藏>` 的尖括号会被清洗吃掉，剩个残缺的 `<已隐藏` 念出来
    # 只会变成一串怪音；换成可读出的词（占位符本身仍不外泄原值）。
    speech = _REDACTION_PLACEHOLDER_RE.sub("已隐去", speech)
    if not speech:
        return "", ""
    reason = speech_block_reason(config, message, speech)
    if reason:
        return "", reason
    return speech, ""


def _speech_refusal_hint() -> str:
    """被内容门拦下时的守岸人口吻回执（不复述政策类别、不泄露被拦原文）。"""
    return "这段话我不念出声——留在文字里就好。想让我说点什么，换个说法试试？"


def auto_reply_scope_allows(config: Any, message: IncomingMessage) -> bool:
    """对话自动配音的会话范围判定：private / group / all。"""
    scope = str(getattr(config, "bot_tts_auto_reply_scope", "private") or "private").strip().lower()
    if scope == "all":
        return True
    is_group = bool(str(getattr(message, "group_id", "") or "").strip())
    if scope == "group":
        return is_group
    return not is_group


def _resolve_probability(value: Any) -> float:
    """把概率配置解析成 float；失败按 0（不配音）处理。

    与 ``policy/gate.py`` 的 ``_resolve_probability`` 同口径，支持实时
    callable——概率若由心情之类的动态量参与，必须在每次抽签时求值，
    不能在装配期冻成常量。
    """
    if value is None:
        return 0.0
    if callable(value):
        try:
            return float(value())
        except Exception:  # noqa: BLE001 - 求值失败按不配音处理。
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def should_voice_reply(
    config: Any,
    message: IncomingMessage,
    result: CapabilityResult,
) -> bool:
    """对话自动配音的完整门链判定（纯谓词，无副作用，可直测）。

    依次判定：总开关 → 自动配音开关 → 结果尚未带音频 → 结果出自 ``bot.chat``
    → 会话范围匹配 → 概率门。

    概率门用**确定性哈希**（与 ``policy/gate.py`` 的
    ``deterministic_group_reply_lottery`` 同款，media 域内自带一份以保持域边界）：
    seed 取 ``f"{session_id}:{message_id or request_id}"``，同一条消息永远得到
    同一结果——可复现、可审计，也避免用 ``random`` 让测试变成按概率 flaky。
    ``bot_tts_auto_reply_always`` 为真时跳过概率门（全量配音，调试/验收用）。
    """
    if not bool(getattr(config, "bot_tts_enabled", False)):
        return False
    if not bool(getattr(config, "bot_tts_auto_reply_enabled", False)):
        return False
    if result.audio:
        return False
    if str(getattr(result, "capability_id", "")) != "bot.chat":
        return False
    if not auto_reply_scope_allows(config, message):
        return False
    if bool(getattr(config, "bot_tts_auto_reply_always", False)):
        return True
    probability = _resolve_probability(
        getattr(config, "bot_tts_auto_reply_probability", _DEFAULT_AUTO_REPLY_PROBABILITY)
    )
    if probability <= 0:
        return False
    if probability >= 1:
        return True
    seed = (
        f"{getattr(message, 'session_id', '') or ''}:"
        f"{getattr(message, 'message_id', '') or getattr(message, 'request_id', '') or ''}"
    )
    bucket = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 10000
    return bucket < probability * 10000


def maybe_attach_voice(
    message: IncomingMessage,
    result: CapabilityResult,
    *,
    config: Any,
) -> CapabilityResult:
    """给 chat 结果附加语音（供 ``__init__`` 的 chat 能力包装层调用）。

    门链见 ``should_voice_reply``：总开关 / 自动配音开关 / 未带音频 /
    出自 bot.chat / 会话范围 / 概率门。任何失败都原样返回 result——
    配音是增益，绝不能影响文字回复。
    """
    if not should_voice_reply(config, message, result):
        return result
    try:
        max_chars = int(
            getattr(config, "bot_tts_auto_reply_max_chars", 120) or 120
        )
        speech, blocked = resolve_speech_text(
            config, message, result.body or result.summary or "", max_chars=max_chars
        )
        if blocked:
            # 配音是增益：被内容门拦下就只丢增益，文字回复原样出站。
            logger.info("tts auto reply blocked by policy: category=%s", blocked)
            return result
        if not speech:
            return result
        ref = pick_ref_audio(
            getattr(config, "bot_tts_ref_audios", []) or [],
            base_dir=str(getattr(config, "bot_tts_gptsovits_dir", "") or ""),
        )
        if ref is None:
            return result
        path, reason = synthesize(
            api_url=str(getattr(config, "bot_tts_api_url", "") or "http://127.0.0.1:9880"),
            text=speech,
            ref=ref,
            params=_build_params(config),
            output_dir=_output_dir(config),
            timeout_seconds=float(
                getattr(config, "bot_tts_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
            ),
            cache_enabled=bool(getattr(config, "bot_tts_cache_enabled", True)),
        )
        if path is None:
            logger.info("tts auto reply skipped: %s", reason)
            return result
        return result.model_copy(
            update={
                "audio": [{"file": str(path), "review_text": speech}],
                "audit_tags": [*result.audit_tags, "tts", "auto_reply"],
            }
        )
    except Exception as exc:  # noqa: BLE001 - 配音增益绝不阻断文字回复。
        logger.info("tts auto reply failed: %s", exc)
        return result
