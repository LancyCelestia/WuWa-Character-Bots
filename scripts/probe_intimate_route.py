"""R-18 亲密路由验证探针（v21r2-R7 席）：给用户自己扣扳机用的验证枪。

默认**离线**：加载运行时注册表快照（.env 的 BOT_MODEL_REGISTRY + 运行时
settings store 的 model_registry 覆盖层）与真实的 ContentRouteEngine /
ModelRouter，对固定样例（正常 / 擦边 / 强词 / L2 语境 / 倒装开关句 /
Master Love）打印「分类结果 + 候选序 + 是否会到 grok」。零网络、零模型调用；
api_key 保持 ``env:`` 引用原样，绝不解析、绝不打印。

``--live``：要求环境变量 ``BOT_PROBE_LIVE=1`` 才执行（用户显式扳机）。向
axonhub 发**一次** grok-4.6 请求——温和亲密语气提示词，走 bot 既有
OpenAICompatibleLLMProvider 通道与超时语义（connect 5s / read 30s，单候选
不做故障转移，失败如实报告死在哪）。只打印路由轨迹与回复状态摘要
（前 80 字 + 成功/拒答/超时判定），不打印完整回复正文。密钥经生产
``_resolve_api_key`` 链解析（os.environ → .env 值），不落盘、不回显。

用法：
    python scripts/probe_intimate_route.py                 # 离线体检
    python scripts/probe_intimate_route.py --text 想你了    # 附加自定义样例
    BOT_PROBE_LIVE=1 python scripts/probe_intimate_route.py --live
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.llm.model_router import (
    build_model_registry,
    build_model_router,
)
from plugins.bot_unified_runtime.llm.providers import (
    LLMProviderError,
    OpenAICompatibleLLMProvider,
)
from plugins.bot_unified_runtime.runtime.content_route import (
    ContentRouteEngine,
    build_router_cb,
    match_manual_command,
)

ROOT = Path(__file__).resolve().parents[1]

# 拒答模板句判定（镜像 capabilities/chat.py::_REFUSAL_BOILERPLATE_RE 的观测
# 口径；探针不 import chat.py 以免拖起 NoneBot 栈，两处措辞需同步维护）。
_REFUSAL_RE = re.compile(
    r"I cannot fulfill|I am unable to|cannot comply|I must decline"
    r"|against my (?:guidelines|principles)|cannot generate sexually",
    re.IGNORECASE,
)

# --live 提示词：温和亲密（恋人语气、不露骨）——验证 grok 对亲密 RP 的
# 配合度，不做也不应做露骨压测（露骨合规由 content_safety 守界，不在本探针）。
_LIVE_SYSTEM = "你是守岸人。以恋人般的亲密与温柔回应对方，保持角色语气，不 OOC。"
_LIVE_USER = "（轻轻握住你的手，靠得近了些）今晚只有我们两个……说说看，今天有没有想我？"


@dataclass
class ProbeSample:
    """一个离线样例：多轮 (消息文本, 上下文文本) 序列，报告取末轮判定。"""

    label: str
    turns: list[tuple[str, str]]


@dataclass
class ProbeReport:
    """单个样例的离线判定结果（可 JSON 化、可断言）。"""

    label: str
    message_text: str
    mode: str  # "intimate" | "normal"
    head_models: list[str]
    candidate_ids: list[str]  # 完整候选序（model_id）
    candidate_models: list[str]  # 与 candidate_ids 一一对应的实际模型名
    grok_channel: str = ""  # 首个 grok 家族渠道 id（无则空）
    grok_position: int = -1  # 1-based；-1 = 不在候选里
    grok_first: bool = False  # grok 家族是否排候选第一
    reaches_grok: bool = False  # intimate 态下 grok 是否可达（含非首位）
    note: str = ""


def load_env(path: Path) -> dict[str, str]:
    """最小 .env 解析（与 probe_llm_providers 同语义；值只进配置链不回显）。"""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_runtime_registry_overlay(
    settings_dir: Path, instance: str
) -> tuple[dict[str, dict[str, Any]], str]:
    """只读解析运行时 settings store 的 model_registry 覆盖层。

    返回 (覆盖条目, 来源说明)；文件不存在/解析失败返回 ({}, 原因)——绝不写、
    绝不回退创建文件（探针对运行数据零写入）。
    """
    from runtime_paths import runtime_path

    # 相对路径（如 data/settings）必须走 runtime_path 重映射进运行时根；
    # 绝对路径原样。探针对该文件零写入。
    base = runtime_path(settings_dir) if str(settings_dir).strip() else runtime_path("data/settings")
    safe_instance = re.sub(r"[^A-Za-z0-9_\-一-鿿]+", "_", instance or "default")
    path = Path(base) / f"runtime_settings_{safe_instance}.json"
    if not path.exists():
        return {}, f"store 缺失：{path.name}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, f"store 解析失败：{type(exc).__name__}"
    entries = data.get("model_registry") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}, "store 无 model_registry 节"
    return {
        str(k): dict(v) for k, v in entries.items() if isinstance(v, dict)
    }, f"store 已载入：{path.name}（{len(entries)} 条）"


def build_probe_config(env: dict[str, str]) -> SimpleNamespace:
    """把 .env 键值铺成 config 视图（键小写，等价 NoneBot dotenv→Config）。"""
    flat = {str(k).lower(): v for k, v in env.items()}
    # content_route 旋钮缺省与 config.py 同值：无 .env 也能离线跑。
    flat.setdefault("bot_content_route_enabled", "true")
    flat.setdefault("bot_content_route_model", "grok-4.6")
    flat.setdefault("bot_content_route_order", "grok-4.6,gemini-3.8-flash")
    return SimpleNamespace(**flat)


def _config_get(config: Any, key: str, default: str) -> str:
    return str(getattr(config, key, default) or default)


def run_offline_probe(
    registry_entries: dict[str, dict[str, Any]],
    env: dict[str, str],
    samples: list[ProbeSample],
    *,
    max_candidates: int = 12,
) -> list[ProbeReport]:
    """离线探测核心：真实引擎 + 真实路由器，注册表/样例可注入（测试用）。

    零网络：密钥保持 ``env:`` 引用不解析（build_model_registry 经 os.environ
    解析，探针进程环境无这些变量 → 解析为空串，正好保证离线零密钥）。
    """
    config = build_probe_config(env)
    base_config = SimpleNamespace(
        bot_model_registry=registry_entries, bot_model_presets={}, bot_chat_model=_config_get(config, "bot_chat_model", ""), bot_chat_base_url=_config_get(config, "bot_chat_base_url", ""), bot_chat_api_key=""
    )
    if registry_entries:
        overlay: dict[str, dict[str, Any]] = {}  # 注入态（测试）：外部给定注册表即完整快照，不读 store。
    else:
        overlay, _source = load_runtime_registry_overlay(
            Path(_config_get(config, "bot_runtime_settings_dir", "")),
            _config_get(config, "bot_runtime_instance", "")
            or _config_get(config, "bot_persona_profile_id", "default"),
        )
    engine = ContentRouteEngine()
    router = build_model_router(
        base_config,
        dynamic_registry=(lambda: overlay) if overlay else None,
        content_route_cb=build_router_cb(engine, lambda: config),
    )
    # 生产语义：generate() 每次先 _refresh_dynamic_registry 再 route_ids；
    # 探针直调 route_ids，须显式刷一次运行时注册表合并（42→17 瘦身等
    # 运行时直改都在这层生效）。
    router._refresh_dynamic_registry()
    reports: list[ProbeReport] = []
    intimate_model = _config_get(config, "bot_content_route_model", "grok-4.6").strip().lower()
    for sample in samples:
        label = sample.label
        session_key = f"probe:{label}"
        for message_text, context_text in sample.turns:
            # 复刻 chat.py 主链时序：L4 手动命令 → observe_turn（L1/L2）→
            # route_verdict（router 经 cb 消费）。
            manual = match_manual_command(message_text)
            if manual is not None:
                engine.apply_manual(session_key, manual, config)
            else:
                engine.observe_turn(
                    session_key,
                    message_text=message_text,
                    context_text=context_text,
                    config=config,
                )
        verdict = engine.route_verdict(session_key, config)
        ids = router.route_ids(message_text=message_text, override="", session_key=session_key)
        models: list[str] = []
        for model_id in ids:
            spec = router._spec_for(model_id)
            models.append(spec.model if spec is not None else model_id)
        grok_idx = next(
            (i for i, name in enumerate(models) if name.strip().lower() == intimate_model),
            -1,
        )
        grok_channel = ids[grok_idx] if grok_idx >= 0 else ""
        reports.append(
            ProbeReport(
                label=label,
                message_text=sample.turns[-1][0],
                mode=str(verdict.get("mode", "normal")),
                head_models=[str(n) for n in verdict.get("head_models", [])],
                candidate_ids=ids[:max_candidates],
                candidate_models=models[:max_candidates],
                grok_channel=grok_channel,
                grok_position=grok_idx + 1,
                grok_first=grok_idx == 0,
                reaches_grok=grok_idx >= 0,
                note="",
            )
        )
    return reports


DEFAULT_SAMPLES: list[ProbeSample] = [
    ProbeSample("正常", [("今天天气不错，晚饭吃什么好", "")]),
    ProbeSample("擦边", [("抱抱我，想跟你贴贴", "")]),
    ProbeSample("强词", [("给我讲个色情故事", "")]),
    # L2 语境升级：单轮只 +35 停在滞回带（保持前态 normal），两轮才过阈值
    # ——与 tests/test_content_route.py 的既有语义一致，故意演示「慢半拍」。
    ProbeSample(
        "L2语境升级",
        [
            ("继续", "用户：讲点色情的内容\n岸宝：这个呀……\n用户：就是那种"),
            ("继续呀", "用户：讲点色情的内容\n岸宝：这个呀……\n用户：就是那种"),
        ],
    ),
    ProbeSample("倒装开", [("开启亲密模式", "")]),
    ProbeSample("开关关闭", [("亲密模式 开", ""), ("亲密模式 关", "")]),
]


def print_offline_reports(reports: list[ProbeReport]) -> None:
    print(f"{'样例':<10}{'分类':<10}{'grok':<12}候选序（id → 模型名）")
    print("-" * 96)
    for item in reports:
        if item.mode == "intimate":
            mark = "grok第一" if item.grok_first else (
                f"第{item.grok_position}位" if item.reaches_grok else "不可达")
        else:
            mark = "-" if not item.reaches_grok else f"正常链第{item.grok_position}位"
        order = " → ".join(
            f"{mid}({model})" for mid, model in zip(item.candidate_ids, item.candidate_models)
        )
        print(f"{item.label:<8}{item.mode:<10}{mark:<10}{order}")
    print()
    for item in reports:
        expect_intimate = item.label in {"强词", "L2语境升级", "倒装开"}
        expect_normal = item.label in {"正常", "擦边", "开关关闭"}
        ok = (item.mode == "intimate") if expect_intimate else (
            item.mode == "normal" if expect_normal else True)
        if expect_intimate and item.mode == "intimate" and not item.grok_first:
            ok = False
            item.note = "INTIMATE 但 grok 不在首位"
        if not ok:
            item.note = (item.note or "") + "判定与预期不符"
    bad = [item for item in reports if item.note]
    if bad:
        for item in bad:
            print(f"[!] {item.label}: {item.note}")
    else:
        print("[OK] 全部样例判定符合预期（INTIMATE 首选 grok，普通/擦边留默认链）")


def _redact(text: str, secrets: list[str]) -> str:
    out = str(text)
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        out = out.replace(secret, "[redacted]")
    out = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+", r"\1[redacted]", out)
    out = re.sub(r"(?i)((?:api[_ -]?key|token)\s*[:=]\s*)[^\s,;]+", r"\1[redacted]", out)
    return out


def run_live_probe(env: dict[str, str]) -> int:
    """单发 grok-4.6 实弹：既有 providers 通道 + 既有超时语义，单候选无转移。"""
    config = build_probe_config(env)
    registry = _parse_registry_json(env)
    if not registry:
        print("[!] .env 无 BOT_MODEL_REGISTRY：live 探测需要注册表定位 grok 渠道")
        return 2
    base_config = SimpleNamespace(
        bot_model_registry=registry, bot_model_presets={}, bot_chat_model=_config_get(config, "bot_chat_model", ""), bot_chat_base_url=_config_get(config, "bot_chat_base_url", ""), bot_chat_api_key=""
    )
    specs = build_model_registry(base_config)
    intimate_model = _config_get(config, "bot_content_route_model", "grok-4.6").strip().lower()
    # grok 渠道按注册表 priority 序（与 INTIMATE 头插同口径，绝不做延迟重排）。
    channels = sorted(
        (spec for spec in specs.values() if spec.model.strip().lower() == intimate_model),
        key=lambda spec: (spec.priority, spec.model_id),
    )
    if not channels:
        print(f"[!] 注册表中没有实际模型名为 {intimate_model} 的渠道")
        return 2
    spec = channels[0]
    api_key = spec.all_api_keys()[0] if spec.all_api_keys() else ""
    if not api_key:
        print(f"[!] 渠道 {spec.model_id} 密钥解析为空（env 变量未注入本进程）")
        return 2
    timeout = float(_config_get(config, "bot_chat_timeout_seconds", "30") or 30)
    provider = OpenAICompatibleLLMProvider(
        api_key=api_key,
        model=spec.model,
        base_url=spec.base_url,
        proxy=_config_get(config, "bot_download_proxy", ""),
        timeout_seconds=timeout,
    )
    messages = [
        {"role": "system", "content": _LIVE_SYSTEM},
        {"role": "user", "content": _LIVE_USER},
    ]
    print(f"live 目标：{spec.model_id} → {spec.model} @ {spec.base_url} 超时={timeout:.0f}s")
    print("提示词：温和亲密语气（不露骨）")
    started = time.monotonic()
    try:
        reply = provider.generate(messages, max_tokens=256)
    except LLMProviderError as exc:
        elapsed = time.monotonic() - started
        verdict = "timeout" if exc.error_kind == "timeout" else f"error:{exc.error_kind}"
        print(f"判定：{verdict}  耗时={elapsed:.1f}s")
        print(f"错误摘要：{_redact(str(exc)[:200], _collect_secrets(env))}")
        print("（对应 axonhub 控制台该请求会显示「已取消」= bot 侧超时掐断，上游挂起）"
              if exc.error_kind == "timeout" else "")
        return 1
    except Exception as exc:  # noqa: BLE001 - 探针把一切传输异常如实归类。
        elapsed = time.monotonic() - started
        print(f"判定：provider_error  耗时={elapsed:.1f}s")
        print(f"错误摘要：{_redact(f'{type(exc).__name__}: {exc}'[:200], _collect_secrets(env))}")
        return 1
    elapsed = time.monotonic() - started
    text = str(reply.text or "").strip()
    refused = bool(_REFUSAL_RE.search(text[:400]))
    if refused:
        verdict = "refusal"
    elif not text:
        verdict = "empty_response"
    else:
        verdict = "success"
    preview = _redact(text[:80], _collect_secrets(env)).replace("\n", " ")
    print(f"判定：{verdict}  served_by={reply.model}  耗时={elapsed:.1f}s")
    print(f"回复前 80 字：{preview}{'…' if len(text) > 80 else ''}")
    if verdict == "refusal":
        print("（英文模板拒答——按 v2 评审 A1 只观测不重试，路由层无罪）")
    return 0


def _parse_registry_json(env: dict[str, str]) -> dict[str, dict[str, Any]]:
    raw = env.get("BOT_MODEL_REGISTRY", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _collect_secrets(env: dict[str, str]) -> list[str]:
    """可能出现在错误详情里的敏感值（仅用于打码，绝不打印名单本身）。"""
    pattern = re.compile(r"(?:^|_)(?:API_KEY|PASSWORD|TOKEN)(?:_|$)", re.IGNORECASE)
    return [v for k, v in env.items() if v and pattern.search(k)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--text", default="", help="附加自定义样例（离线判定）")
    parser.add_argument(
        "--live", action="store_true",
        help="实弹模式：需 BOT_PROBE_LIVE=1；向 grok-4.6 发一次温和亲密请求",
    )
    args = parser.parse_args(argv)
    env = load_env(Path(args.env_file))
    if args.live:
        import os

        if str(os.environ.get("BOT_PROBE_LIVE", "")) != "1":
            print("[!] --live 需要环境变量 BOT_PROBE_LIVE=1（用户显式扳机）")
            print("    PowerShell:  $env:BOT_PROBE_LIVE='1'; python scripts/probe_intimate_route.py --live")
            return 2
        return run_live_probe(env)
    samples = list(DEFAULT_SAMPLES)
    if args.text.strip():
        samples.append(ProbeSample("自定义", [(args.text.strip(), "")]))
    reports = run_offline_probe(_parse_registry_json(env), env, samples)
    print_offline_reports(reports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
