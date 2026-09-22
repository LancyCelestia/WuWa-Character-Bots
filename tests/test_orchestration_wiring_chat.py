"""S-WIRE-CHAT 席（chat.py media 族直呼点真翻判定）· 非等值一手证据 + 中央门自证。

权威：``docs/design/capability-orchestration-adoption-spec.md`` §1 D-b / §4 Wave1/3 /
§5 两层边界 / §7 禁第三套。判定哲学与 SEAT-S-W1B / SEAT-V1(media.frames) 同型：
**不等值就不翻**——本席对 chat.py 四处 media 直呼（识图 ×2、转写、视频简报）逐字段核后
判 **可翻点 = 0**，因此 ledger（``tests/test_orchestration_callsite_single.py`` 三 dict）
一字不动。

本件不是"两路成功产出相等"的等值证明（那是通电点才有的形态，且"两路都用替身比 success
payload"正是本波刚定罪的假绿）。本件是**非等值锚**：让**中央 handler 真实执行**
（``default_invoker().invoke``），把它的 provider 工厂 / describe_images / transcribe_audio /
build_video_brief 的**入参构造**逐条抓到，证明它喂给真身的东西与 chat.py 今天喂的**不同**，
于是切换＝改行为。真身工厂 ``build_vision_provider`` 的 None 分支用**未打桩的真函数**跑实据。

全离线：零网络、零真实模型、零消息发送；provider/describe/transcribe/brief 仅作**入参记录仪**
（断言它们收到什么，从不拿它们的返回拼"看起来成功"的对照）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

# 复用（不复制）v1 门的纯扫描判据与在册 ledger——§7 禁第二套判据。
import test_orchestration_callsite_single as v1gate

# 中央 shell 与 media 真身**延迟到用例内 import**：本门被在飞波次（主会话正改
# capability_protocols.py）连坐的风险真实存在（SEAT-S-W1B §六即一例），collection 期不碰它。
_VISION_MODULE = "plugins.bot_unified_runtime.domains.media.ingest.vision_describe"
_TRANSCRIBE_MODULE = "plugins.bot_unified_runtime.domains.media.ingest.transcribe"
_VIDEO_MODULE = "plugins.bot_unified_runtime.domains.media.ingest.video_understanding"

#: 公网 IP 字面量（非 private/reserved）：中央 SSRF 门放行且零 DNS。
#: 教训沿 V1 席（192.0.2.1 被 ipaddress 判 private，_guard_http_url 触真身前即拒）。
_OK_URL = "http://104.16.0.1/ok.png"
_BLOCKED_URL = "http://127.0.0.1/secret.png"


def _invoke(cid: str, payload: dict[str, Any], config: Any, *, roles: tuple[str, ...] = ("user",)):
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        default_invoker,
    )

    return default_invoker().invoke(
        CapabilityRequest(
            capability_id=cid,
            payload=payload,
            principal="10000",
            roles=roles,
            context={"config": config},
        )
    )


def _config(**overrides: Any) -> SimpleNamespace:
    base = {
        "bot_vision_enabled": True,
        # 合法条目需 model + base_url 同时非空才被 _flatten_vision_entries 计入（:504-507）。
        "bot_vision_model_registry": {"m": [{"model": "gpt-4v", "base_url": "http://104.16.0.1/v1"}]},
        "bot_vision_max_images": 4,
        "bot_vision_max_chars": 2000,
        "bot_asr_enabled": True,
        "bot_asr_model_registry": {"m": [{"model": "whisper"}]},
        "bot_asr_timeout_seconds": 20.0,
        "bot_asr_max_chars": 300,
        "bot_video_understanding_enabled": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# ① provider 身份分叉：中央每调重建、且丢失 root 装配传入的 dynamic_registry/settings_store
# ---------------------------------------------------------------------------
def test_central_vision_rebuilds_provider_without_runtime_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat.py 用 root 装配（__init__.py:4624）建好的 provider：
    ``build_vision_provider(config, dynamic_registry=..., settings_store=...)``。
    中央 handler（:810）却 ``build_vision_provider(config)``——**省略两个 runtime 参数**，
    于是拿到一枚 wiring 不同的 provider（甚至 None，见下一条）。本条抓 handler 真实传入的 kwargs。"""
    import importlib

    vision = importlib.import_module(_VISION_MODULE)
    build_calls: list[dict[str, Any]] = []

    def _record_build(config: Any, **kwargs: Any):
        build_calls.append(kwargs)
        return SimpleNamespace(_config=config)  # 非 None，让 handler 越过 NOT_CONFIGURED 分支

    seen_args: dict[str, Any] = {}

    def _record_describe(provider: Any, **kwargs: Any) -> str:
        seen_args["kwargs"] = kwargs
        return "识别结果"

    monkeypatch.setattr(vision, "build_vision_provider", _record_build)
    monkeypatch.setattr(vision, "describe_images", _record_describe)

    result = _invoke("media.vision.image", {"image_urls": [_OK_URL], "query_text": "看这图"}, _config())

    assert build_calls, "中央 handler 未重建 provider（与预期不符，用例假设需重估）"
    # root 装配会带这两个 kwarg；中央 handler 一个都不带 ⇒ provider 身份/wiring 不等值。
    assert "dynamic_registry" not in build_calls[0] and "settings_store" not in build_calls[0], (
        f"中央 handler 传给 build_vision_provider 的 kwargs 竟含 runtime wiring：{build_calls[0]}"
    )
    assert result.status.value in {"ok", "degraded"}


def test_real_factory_returns_none_without_dynamic_registry_and_empty_env() -> None:
    """真函数实据（无桩）：env 注册表为空时，root 靠 dynamic_registry 点亮视觉，
    中央 config-only 重建拿不到 ⇒ 返回 None ⇒ handler NOT_CONFIGURED ⇒ 识图整条静默关闭。
    这是 provider 身份分叉最狠的一种，且**纯用真 ``build_vision_provider`` 跑出**。"""
    import importlib

    vision = importlib.import_module(_VISION_MODULE)
    empty_env = _config(bot_vision_model_registry={})
    # 中央 handler 风格：只给 config，无 dynamic_registry/settings_store
    handler_side = vision.build_vision_provider(empty_env)
    assert handler_side is None, "env 空且无 dynamic_registry 时真工厂应返回 None（据 :652-653）"
    # root 装配风格：带 dynamic_registry（返回合法条目），故能拿到可用 provider
    root_side = vision.build_vision_provider(
        empty_env,
        dynamic_registry=lambda: {"m": [{"model": "gpt-4v", "base_url": "http://104.16.0.1/v1"}]},
        settings_store=object(),
    )
    assert root_side is not None, "带 dynamic_registry 时真工厂应产出 provider"
    # 两者身份不同 ⇒ 同一条视觉链路，翻点前经 chat provider 能跑、翻点后经中央 NOT_CONFIGURED。


# ---------------------------------------------------------------------------
# ② 标量不可注入：max_images/max_chars 中央硬读 config，chat 传的是工厂期快照，payload 无覆盖道
# ---------------------------------------------------------------------------
def test_central_vision_forces_config_scalars_ignoring_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    vision = importlib.import_module(_VISION_MODULE)
    captured: dict[str, Any] = {}

    monkeypatch.setattr(vision, "build_vision_provider", lambda cfg, **k: SimpleNamespace(_config=cfg))

    def _record(provider: Any, **kwargs: Any) -> str:
        captured.update(kwargs)
        return "t"

    monkeypatch.setattr(vision, "describe_images", _record)
    # 即便 payload 试图携带 max_images（中央契约根本没有这个入参位），handler 也只从 config 取。
    _invoke(
        "media.vision.image",
        {"image_urls": [_OK_URL], "query_text": "q", "max_images": 2, "max_chars": 500},
        _config(bot_vision_max_images=4, bot_vision_max_chars=2000),
    )
    assert captured["max_images"] == 4 and captured["max_chars"] == 2000, (
        f"中央未按 config 覆盖标量（说明可注入，判定需重估）：{captured}"
    )
    # chat.py:3008-3009 今天喂的是工厂快照 vision_max_images/vision_max_chars（root:4720-4721 读 config，
    # 之后 config 热改则与 invoke 时再读的 config 分叉）⇒ 无 payload 通道携带 chat 快照，翻点即换值。


# ---------------------------------------------------------------------------
# ③ 新 SSRF 门：chat 直调对 http 图 URL 无 check_download_url，中央有 ⇒ 新增拦截
# ---------------------------------------------------------------------------
def test_central_ssrf_guard_blocks_url_that_direct_path_would_describe(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    vision = importlib.import_module(_VISION_MODULE)
    monkeypatch.setattr(vision, "build_vision_provider", lambda cfg, **k: SimpleNamespace(_config=cfg))
    describe_calls: list[Any] = []
    monkeypatch.setattr(vision, "describe_images", lambda p, **k: describe_calls.append(k) or "x")

    result = _invoke("media.vision.image", {"image_urls": [_BLOCKED_URL], "query_text": "q"}, _config())
    assert result.status.value == "failed", f"内网 URL 未被中央 SSRF 拒：{result.status}"
    assert describe_calls == [], "SSRF 命中却仍直呼 describe_images = 护栏没在真身前生效"
    # chat.py 直调路径从不跑 _guard_http_url：同一 URL 今日会进 describe_images → 行为分叉。


# ---------------------------------------------------------------------------
# ④ ASR：timeout 来源不同（provider._config vs request.config）+ provider 重建丢 settings_store
# ---------------------------------------------------------------------------
def test_asr_central_timeout_from_request_config_not_provider_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    transcribe = importlib.import_module(_TRANSCRIBE_MODULE)
    build_kwargs: list[dict[str, Any]] = []
    captured: dict[str, Any] = {}

    def _record_build(cfg: Any, **kwargs: Any):
        build_kwargs.append(kwargs)
        # chat 侧 provider 的 _config 超时=45，与注入的 request.config(=20) 刻意不同
        return SimpleNamespace(_config=SimpleNamespace(bot_asr_timeout_seconds=45.0))

    def _record(provider: Any, **kwargs: Any) -> str:
        captured.update(kwargs)
        return "文字"

    monkeypatch.setattr(transcribe, "build_asr_provider", _record_build)
    monkeypatch.setattr(transcribe, "transcribe_audio", _record)

    result = _invoke("media.asr.speech", {"audio_source": _OK_URL}, _config(bot_asr_timeout_seconds=20.0))
    assert build_kwargs and "settings_store" not in build_kwargs[0], (
        f"中央 ASR provider 重建 kwargs 意外含 runtime wiring：{build_kwargs}"
    )
    # 中央 handler 用注入的 request.config(=20)，chat.py 用 asr_provider._config(=45) ⇒ 超时语义分叉。
    assert captured["timeout_seconds"] == 20.0, (
        f"中央 timeout 取值来源与 chat 不同源已实证（chat 走 provider._config=45）：{captured}"
    )
    assert result.status.value in {"ok", "degraded"}


# ---------------------------------------------------------------------------
# ⑤ 视频：中央 handler 丢弃 deadline_seconds（B-1 生产修复）+ 双 provider 重建
# ---------------------------------------------------------------------------
def test_video_central_drops_deadline_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    video = importlib.import_module(_VIDEO_MODULE)
    vision = importlib.import_module(_VISION_MODULE)
    transcribe = importlib.import_module(_TRANSCRIBE_MODULE)
    brief_kwargs: dict[str, Any] = {}

    monkeypatch.setattr(vision, "build_vision_provider", lambda cfg, **k: SimpleNamespace(_config=cfg))
    monkeypatch.setattr(transcribe, "build_asr_provider", lambda cfg, **k: SimpleNamespace(_config=cfg))

    def _record_brief(config: Any, **kwargs: Any):
        brief_kwargs.update(kwargs)
        return SimpleNamespace(text="简报", signals={"has_subtitle": True})

    monkeypatch.setattr(video, "build_video_brief", _record_brief)

    result = _invoke(
        "media.video.recognize",
        {"video_source": _OK_URL, "question": "讲讲", "deep": True},
        _config(),
    )
    assert brief_kwargs, "中央未调用 build_video_brief（handler 未走到，用例假设需重估）"
    # chat.py:342 传 deadline_seconds=_video_deadline_seconds(request_budget)（B-1：剩余预算−60s、下限 30）；
    # 中央 handler（:992-1001）不接收也不转发该参数 ⇒ 翻点＝回退真实生产修复（深挖可烧光预算致 LLM 超时）。
    assert "deadline_seconds" not in brief_kwargs, (
        f"中央 video handler 竟携带 deadline_seconds（则分叉不成立，需重估）：{brief_kwargs}"
    )
    assert result.status.value in {"ok", "degraded"}


# ---------------------------------------------------------------------------
# ⑥ 中央权限门：blocked 无条件拒且真身一步未走（chat 直调无此门，翻点即新增拦截面）
# ---------------------------------------------------------------------------
def test_central_permission_gate_denies_blocked_and_true_body_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    vision = importlib.import_module(_VISION_MODULE)
    calls: list[Any] = []
    monkeypatch.setattr(vision, "build_vision_provider", lambda cfg, **k: SimpleNamespace(_config=cfg))
    monkeypatch.setattr(vision, "describe_images", lambda p, **k: calls.append(k) or "x")

    result = _invoke(
        "media.vision.image",
        {"image_urls": [_OK_URL], "query_text": "q"},
        _config(),
        roles=("blocked",),
    )
    assert result.status.value == "denied"
    assert calls == [], "blocked 仍执行识图 = 中央权限门是装饰"


# ---------------------------------------------------------------------------
# ⑦ 描述符限额前置：>4 图 / query>2000 在 handler 前即 LIMIT_EXCEEDED，chat 直调只内部截不拒
# ---------------------------------------------------------------------------
def test_descriptor_payload_limit_rejects_before_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    vision = importlib.import_module(_VISION_MODULE)
    calls: list[Any] = []
    monkeypatch.setattr(vision, "build_vision_provider", lambda cfg, **k: SimpleNamespace(_config=cfg))
    monkeypatch.setattr(vision, "describe_images", lambda p, **k: calls.append(k) or "x")

    many = [f"http://104.16.0.{i}/a.png" for i in range(1, 6)]  # 5 > max_images=4
    result = _invoke("media.vision.image", {"image_urls": many, "query_text": "q"}, _config())
    assert result.status.value == "limit_exceeded", f"限额未前置执法：{result.status}"
    assert calls == [], "超限却在 handler 后才拒（前置判据假设需重估）"
    # chat.py 直调 describe_images(max_images=2) 会把 5 张内部截到 2 张继续跑，从不整条拒 ⇒ 语义分叉。


# ===========================================================================
# ⑧ 注毒自证：复用 v1 门 scan/check_invariants——若未来有席翻点而不守规，各杀各锁
# ===========================================================================
def _invoke_src(cid: str) -> str:
    return (
        "def f():\n"
        f"    default_invoker().invoke(CapabilityRequest(capability_id='{cid}', payload={{}}, "
        "principal='u', roles=('user',)))\n"
    )


def _direct_src(symbol: str) -> str:
    return f"from x import {symbol}\ndef f():\n    return {symbol}(1)\n"


def test_poison_chat_second_invoker_site_is_red() -> None:
    """两模块各 invoke media.vision.image → media.vision 族第二调用点红。"""
    direct, invoker = v1gate.scan({"a.py": _invoke_src("media.vision.image"), "b.py": _invoke_src("media.vision.image")})
    v = v1gate.check_invariants(direct, invoker, wired=v1gate.WIRED, allowlist=v1gate.KNOWN_DIRECT_ALLOWLIST)
    assert any("第二调用点" in s and "media.vision" in s for s in v), f"第二 invoker 点未拦：{v}"


def test_poison_chat_half_migration_is_red() -> None:
    """chat.py 既直呼 describe_images 又 invoke media.vision.image → 半迁移红。"""
    chat = (
        "from y import describe_images\n"
        "def f(u):\n"
        "    describe_images(u)\n"
        "    default_invoker().invoke(CapabilityRequest(capability_id='media.vision.image', payload={}, principal='u', roles=('user',)))\n"
    )
    direct, invoker = v1gate.scan({"domains/chat_reply/capabilities/chat.py": chat})
    v = v1gate.check_invariants(direct, invoker, wired=v1gate.WIRED, allowlist=v1gate.KNOWN_DIRECT_ALLOWLIST)
    assert any("半迁移" in s and "media.vision" in s for s in v), f"半迁移未拦：{v}"


def test_poison_wired_but_still_direct_is_red() -> None:
    """假想 media.vision 已通电，chat.py 仍直呼 describe_images → '已通电却仍直呼' 红。"""
    direct, invoker = v1gate.scan({"domains/chat_reply/capabilities/chat.py": _direct_src("describe_images")})
    v = v1gate.check_invariants(
        direct,
        invoker,
        wired=v1gate.WIRED | {"media.vision"},  # 合成"通电"前提，专杀偷偷走回老路
        allowlist=v1gate.KNOWN_DIRECT_ALLOWLIST,
    )
    assert any("已通电却仍直呼" in s and "media.vision" in s for s in v), f"通电却仍直呼未拦：{v}"


# ---------------------------------------------------------------------------
# ⑨ 靶面实况锁：扫真 chat.py 源，直呼恰落 media.vision/asr/video_brief、无 invoker（本席零翻点自证）
# ---------------------------------------------------------------------------
def test_real_chat_source_direct_surface_unchanged() -> None:
    from pathlib import Path

    chat_path = Path(v1gate._PKG_ROOT) / "domains/chat_reply/capabilities/chat.py"
    src = chat_path.read_text(encoding="utf-8")
    direct, invoker = v1gate.scan({"domains/chat_reply/capabilities/chat.py": src})
    assert direct["media.vision"] == {"domains/chat_reply/capabilities/chat.py"}
    assert direct["media.asr"] == {"domains/chat_reply/capabilities/chat.py"}
    assert direct["media.video_brief"] == {"domains/chat_reply/capabilities/chat.py"}
    # 本席未翻点 ⇒ chat.py 不应出现任何 media invoker 调用点。
    assert invoker["media.vision"] == set()
    assert invoker["media.asr"] == set()
    assert invoker["media.video_brief"] == set()
    # 直呼面须与 ledger 中这三族登记对 chat.py 的集合一致（本席未改 ledger，故实况即登记）。
    assert "domains/chat_reply/capabilities/chat.py" in v1gate.KNOWN_DIRECT_ALLOWLIST["media.vision"]
    assert "domains/chat_reply/capabilities/chat.py" in v1gate.KNOWN_DIRECT_ALLOWLIST["media.asr"]
    assert "domains/chat_reply/capabilities/chat.py" in v1gate.KNOWN_DIRECT_ALLOWLIST["media.video_brief"]
