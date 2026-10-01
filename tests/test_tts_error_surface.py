"""S50 · 语音失败面「用户与运维各看到什么」现算锁（全离线 mock，零引擎端口接触）。

席位：中央调度收编波 S50（总目标第 3 件「语音：要可用」四腿之**错误面**）。
任务：逐形态钉死语音合成失败今天的**终态三问**——
①终态是什么 ②用户看到什么 ③运维看到什么（诊断卡 / ``/bot status`` 行 / 中央告警
issue 三面的可达性）。判据看**终态**不看「有没有调用」。

形态清单（与报告 SEAT-S50 §1 三列账一一对应）：
  M1 引擎不可达（含退避窗快速失败）          → test_surface_command_unreachable_*
  M2 HTTP 200 但静音三指纹（含与结构坏字节的入窗分界） → test_surface_silent_*
  M3 超硬顶（2000 字 / 8 MiB 两把顶）         → test_surface_*_hard_cap / *_byte_cap
  M4 content_sha256 缓存命中与未命中两路      → test_surface_cache_* / *_digest_*
  M5 参考音缺失（命令路 + 自动配音中央路）    → test_surface_no_ref_*
  M6 voice hook 开态失败（合成败/内部炸/半程/TIMEOUT）→ test_surface_hook_*
  M7 creation.tts.synthesize 直呼失败         → test_surface_creation_*

缺口锁以 ``test_gap_`` 前缀显式命名：断言「今天确实没有出路」，将来补上出路时
必红、强制更新台账——这是现状快照，不是认可。注毒自证以 ``test_injection_`` 前缀：
往**测试可注入的缝**里注坏行为，证明对应行为锁有杀伤力（本席禁写生产文件，
杀伤力全部经 monkeypatch 在合成注入缝上验证，不碰 domains/ 任何落盘字节）。

纪律：绝不向 9880/8090 等本机端口发真请求——HTTP 层全部 sys.modules 注入假 httpx；
TCP 探针全部 monkeypatch ``_tcp_connect``；落盘全部 tmp_path；模块级全局态
（退避闸 / LRU 缓存 / 探针态 / creation 告警 pending）逐例 autouse 清零。
"""

from __future__ import annotations

import hashlib
import io
import sys
import wave
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Self

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import BotDecision
from plugins.bot_unified_runtime.domains.creation import (
    reserved_health_alert as reserved_alert,
)
from plugins.bot_unified_runtime.domains.media import voice_enricher as ve
from plugins.bot_unified_runtime.domains.media import voice_health_alert as probe_alert
from plugins.bot_unified_runtime.domains.media import voice_health_probe as probe
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    build_tts_capability,
)

# S91 退役内联后取文口/异常兜底住真身 result_transform（hook 只派发 media.tts.autodub_transform）：
# 内部异常类用例的取文口桩须打在这里、不是已被删除的 ve.resolve_speech_text。
from plugins.bot_unified_runtime.domains.media.tts import result_transform as rt
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

# ---------------------------------------------------------------------------
# 夹具与替身（全离线）
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_globals(monkeypatch: pytest.MonkeyPatch) -> Any:
    """模块级全局态逐例清零：退避闸 / LRU 缓存 / 探针态 / creation 告警 pending。"""
    tts_mod._clear_failure()
    tts_mod._CACHE.clear()
    probe._reset_state()
    reserved_alert.install_reserved_alert_sink(None)
    reserved_alert.reset_state()
    probe_alert.install_probe_alert_sink(None)
    yield
    tts_mod._clear_failure()
    tts_mod._CACHE.clear()
    probe._reset_state()
    reserved_alert.install_reserved_alert_sink(None)
    reserved_alert.reset_state()
    probe_alert.install_probe_alert_sink(None)


def _config(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_tts_enabled": True,
        "bot_tts_api_url": "http://127.0.0.1:9880",
        "bot_tts_gptsovits_dir": "",
        "bot_tts_ref_audios": [],
        "bot_tts_trigger_words": [],
        "bot_tts_output_dir": str(tmp_path / "tts_out"),
        "bot_tts_preset": "shorekeeper",
        "bot_tts_max_chars": 0,
        "bot_tts_hard_max_chars": 2000,
        "bot_tts_max_audio_bytes": 0,
        "bot_tts_cache_enabled": True,
        "bot_tts_cache_max_bytes": 0,
        "bot_tts_cache_max_age_days": 0,
        "bot_tts_timeout_seconds": 60.0,
        "bot_tts_speed_factor": 0.85,
        "bot_tts_temperature": 0.9,
        "bot_tts_top_k": 15,
        "bot_tts_top_p": 1.0,
        "bot_tts_text_lang": "zh",
        "bot_tts_text_split_method": "cut5",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _ref_entry(tmp_path: Path) -> str:
    ref = tmp_path / "ref.flac"
    ref.write_bytes(b"fLaC" + b"\x00" * 32)
    return f"{ref}|参考文本|zh"


def _msg(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id="private:20000",
        session_type=SessionType.PRIVATE,
        sender_id="20000",
        group_id="",
        plain_text=text,
    )


def _chat_result(body: str) -> CapabilityResult:
    return CapabilityResult(request_id="req-chat-1", capability_id="bot.chat", kind="text", body=body)


def _decision() -> BotDecision:
    """enrich 的 decision 形参在真身里从不被读（门链只用 message+result），
    这里给一枚形状合法的 BotDecision，只为满足 ``Enricher`` 的类型契约、无行为影响。"""
    return BotDecision(
        request_id="req-chat-1",
        should_respond=True,
        mode="command",
        trigger="你好",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        decision_reason="s98",
    )


def _wav_bytes(rate: int, frames: int, *, loud: bool = False) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        if loud:
            handle.writeframes(b"\x40\x1f" + b"\x00\x00" * max(0, frames - 1))
        else:
            handle.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


def _install_fake_httpx(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raise_exc: BaseException | None = None,
    response: bytes | None = None,
    status_code: int = 200,
) -> dict[str, Any]:
    """sys.modules 注入假 httpx：``_request_tts`` 函数内 import 即取到此替身。

    返回记账 dict：``calls``（真打「HTTP」次数）+ ``payloads``（请求体快照）。
    任何一次真实网络都不可能发生——这里根本没有 socket。
    """
    stats: dict[str, Any] = {"calls": 0, "payloads": []}

    class _FakeResponse:
        def __init__(self) -> None:
            self.status_code = status_code
            self.content = response or b""
            self.text = ""

        def json(self) -> Any:
            raise ValueError("not json")

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def post(self, endpoint: str, json: dict | None = None) -> _FakeResponse:
            stats["calls"] += 1
            stats["payloads"].append(json or {})
            if raise_exc is not None:
                raise raise_exc
            return _FakeResponse()

    fake = ModuleType("httpx")
    fake.Client = _FakeClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "httpx", fake)
    return stats


def _private_invoker(*capability_ids: str, audits: list[Any] | None = None) -> cp.CapabilityInvoker:
    """私有 invoker：与生产同一份 descriptor+handler（真身 `_handle_*`），绝不写 default 单例。

    可登记多枚 id——自动配音 hook 今天吃两枚中央能力（外层派发的
    ``media.tts.autodub_transform`` + 内层 ``_dub`` 打的 ``media.tts.autodub``），单枚 id 的旧
    用法（M7 creation 直呼面）逐字节不变。"""
    source = cp.default_invoker()
    registry = cp.CapabilityRegistry()
    handlers = cp.HandlerRegistry()
    hooks = cp.AuditHookRegistry()
    if audits is not None:
        hooks.register(lambda record: audits.append(record))
    invoker = cp.CapabilityInvoker(registry=registry, handlers=handlers, audit_hooks=hooks)
    for capability_id in capability_ids:
        descriptor = source.registry.get(capability_id)
        handler = source.handlers.get(capability_id)
        assert descriptor is not None and handler is not None, f"{capability_id} 未在册/未挂 handler"
        registry.register(descriptor)
        handlers.register(capability_id, handler)
    return invoker


# ===========================================================================
# M1 引擎不可达（含退避窗）
# ===========================================================================

def test_surface_command_unreachable_terminal_degrade_and_retryable_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """①终态：text 降级、零音频、不抛异常（⇒诊断卡面对此类结构性不可达）。
    ②用户：「嗓子还没接上」一句。③运维：issue=tts_service_unreachable 可重试（告警链
    前置件已挂上）；卡不出属 fail-open 设计语义，本锁把「不抛」钉成事实。"""
    _install_fake_httpx(monkeypatch, raise_exc=ConnectionError())
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    result = build_tts_capability(cfg)(_msg("说 今天的潮汐很安静"), None)

    assert result.kind == "text"
    assert not result.audio, "失败绝不携带音频部件"
    assert "嗓子还没接上" in (result.body or "")
    issue = result.operational_issue
    assert issue is not None
    assert (issue.stage, issue.kind, issue.retryable) == ("tts", "tts_service_unreachable", True)
    assert "synthesize_failed" in result.audit_tags


def test_surface_command_unreachable_backoff_window_skips_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """退避窗（30s）内第二条不同文本：终态同为不可达降级，但**第二次不再打引擎**
    （判据=HTTP 计数==1，不是「调没调用」而是窗内真快速失败）。"""
    stats = _install_fake_httpx(monkeypatch, raise_exc=ConnectionError())
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    capability = build_tts_capability(cfg)
    capability(_msg("说 第一句潮汐"), None)
    second = capability(_msg("说 第二句海风"), None)

    assert stats["calls"] == 1, "退避窗内不得再打引擎"
    issue = second.operational_issue
    assert issue is not None and issue.kind == "tts_service_unreachable"
    assert "退避冷却中" in (second.operational_issue.safe_summary or "") or "退避冷却中" in issue.safe_summary


def test_surface_unreachable_ops_face_status_line_and_probe_alert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """③运维面（引擎不可达形态）：``/bot status`` 语音行同时呈现 unreachable 与
    backoff；探针构造的 issue 经唯一消费者投一次清一次（读出路确有）。"""
    tts_mod._record_failure("服务不可达：ConnectError")

    def _refused(*_a: object, **_k: object) -> None:
        raise ConnectionRefusedError()

    monkeypatch.setattr(probe, "_tcp_connect", _refused)
    cfg = _config(tmp_path)
    line = probe.voice_status_line(cfg)
    assert "engine=unreachable" in line
    assert "backoff=" in line and "服务不可达" in line

    received: list[Any] = []
    probe_alert.install_probe_alert_sink(received.append)
    assert probe_alert.flush_probe_issue_to_alerts() is True
    assert received and received[0].kind == "tts_service_unreachable"
    assert received[0].retryable is True
    assert probe_alert.flush_probe_issue_to_alerts() is False, "投一次清一次，不得粘滞复投"


def test_injection_backoff_gate_dead_would_rehit_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """注毒①：把退避闸判据伪造成「永远不在窗内」→ 窗内第二发**真的又打引擎**。
    证明 M1b 锁（calls==1）有杀伤力，不是空转。"""
    stats = _install_fake_httpx(monkeypatch, raise_exc=ConnectionError())
    monkeypatch.setattr(tts_mod, "_backoff_reason", lambda: "")
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    capability = build_tts_capability(cfg)
    capability(_msg("说 注毒第一句"), None)
    capability(_msg("说 注毒第二句"), None)
    assert stats["calls"] == 2, "闸死之后必复打——锁的杀伤力反证"


# ===========================================================================
# M2 HTTP 200 静音三指纹（与结构坏字节的入窗分界）
# ===========================================================================

def test_surface_silent_trap_rejects_and_counts_backoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """①终态：200+恰 1s 静音被拒——不落盘、不入缓存、发文本；②用户首条见
    「这次没能发出声音」（体检失败话术，非「不可达」话术）；③issue=tts_bad_audio
    不可重试，且**计入退避窗**（WP4 归类：引擎以 200 伪装成功=部署类故障）。"""
    silent = _wav_bytes(16000, 16000)
    _install_fake_httpx(monkeypatch, response=silent)
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    result = build_tts_capability(cfg)(_msg("说 静音陷阱样本"), None)

    assert not result.audio
    assert "这次没能发出声音" in (result.body or "")
    issue = result.operational_issue
    assert issue is not None
    assert (issue.stage, issue.kind, issue.retryable) == ("tts", "tts_bad_audio", False)
    assert "静音陷阱" in issue.safe_summary
    out = tmp_path / "tts_out"
    assert not out.exists() or not any(out.iterdir()), "静音产物绝不落盘"
    assert not tts_mod._CACHE, "静音产物绝不入缓存"
    assert tts_mod._backoff_reason(), "静音陷阱必须计入退避窗"


def test_surface_silent_trap_second_message_speaks_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """静音陷阱进窗后的**第二发**（窗内快速失败）：用户话术翻成「嗓子还没接上」，
    issue 也翻成 tts_service_unreachable——两阶段用户可见面逐字钉死。"""
    _install_fake_httpx(monkeypatch, response=_wav_bytes(16000, 16000))
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    capability = build_tts_capability(cfg)
    capability(_msg("说 陷阱第一发"), None)
    second = capability(_msg("说 陷阱第二发"), None)

    assert "嗓子还没接上" in (second.body or "")
    issue = second.operational_issue
    assert issue is not None and issue.kind == "tts_service_unreachable"


def test_surface_structural_garbage_does_not_enter_backoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """分类学边界：非 RIFF 坏字节同样 tts_bad_audio，但**不入退避窗**
    （单次坏字节进窗会周期性误伤全员）。判据看窗态终值，不看日志。"""
    _install_fake_httpx(monkeypatch, response=b"definitely-not-a-wav")
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    result = build_tts_capability(cfg)(_msg("说 坏字节样本"), None)

    issue = result.operational_issue
    assert issue is not None and issue.kind == "tts_bad_audio"
    assert not tts_mod._backoff_reason(), "结构类坏字节不入窗（禁放宽也禁收紧）"


def test_injection_sanity_gate_removed_would_ship_silence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """注毒②：把体检闸伪造成「永远放行」→ 静音产物**真落盘进缓存出部件**。
    反证 M2 落盘/缓存/退避三条断言都咬在真判据上。"""
    _install_fake_httpx(monkeypatch, response=_wav_bytes(16000, 16000))
    monkeypatch.setattr(tts_mod, "_inspect_wav_bytes", lambda _data: "")
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    result = build_tts_capability(cfg)(_msg("说 注毒静音样本"), None)
    assert result.audio, "闸失效后毒件照发——锁有杀伤力的反证"
    assert tts_mod._CACHE, "闸失效后毒件入缓存"


# ===========================================================================
# M3 超硬顶（2000 字文本顶 / 8 MiB 字节顶）
# ===========================================================================

def test_surface_over_text_hard_cap_rejects_before_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """文本超硬顶：**不打引擎**直接拒（stats.calls==0），用户见「这段话太长了」，
    机读留痕 over_hard_cap+len/cap，issue=tts_service_rejected 不可重试。"""
    stats = _install_fake_httpx(monkeypatch, response=_wav_bytes(32000, 3200))
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)], bot_tts_hard_max_chars=20)
    long_text = "一二三四五六七八九十。" * 3  # 42 字 > 20
    result = build_tts_capability(cfg)(_msg(f"说 {long_text}"), None)

    assert stats["calls"] == 0, "超顶必须拒在打引擎之前"
    assert "太长了" in (result.body or "")
    assert any(tag.startswith("over_hard_cap") for tag in result.audit_tags)
    assert any(tag.startswith("len=") for tag in result.audit_tags)
    assert any(tag.startswith("cap=") for tag in result.audit_tags)
    issue = result.operational_issue
    assert issue is not None and (issue.kind, issue.retryable) == ("tts_service_rejected", False)


def test_surface_over_byte_cap_rejects_without_backoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """产物超 8 MiB 字节顶（G2-R3 缺省）：拒发不落盘、issue=tts_bad_audio、
    **不入退避窗**（分类学在册）；下一发照常真打（calls==2 为判据）。"""
    big = _wav_bytes(32000, 4_200_000, loud=True)  # ≈8.4 MB > 8 MiB
    stats = _install_fake_httpx(monkeypatch, response=big)
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    capability = build_tts_capability(cfg)
    first = capability(_msg("说 字节顶样本甲"), None)
    capability(_msg("说 字节顶样本乙"), None)

    issue = first.operational_issue
    assert issue is not None and issue.kind == "tts_bad_audio"
    assert "超字节顶" in issue.safe_summary
    assert not tts_mod._backoff_reason()
    assert stats["calls"] == 2, "字节顶不入窗 ⇒ 第二发必须真打"
    out = tmp_path / "tts_out"
    assert not out.exists() or not any(out.iterdir())


def test_gap_hook_over_cap_leaves_zero_machine_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """GAP-HOOK-OVERCAP（显式命名缺口锁）：voice hook 开态下自动配音超硬顶
    **原样返回、零留痕**——旧包装 ``maybe_attach_voice`` 会挂 ``over_hard_cap``
    审计标签（对照锁在同用例后半），键开反而比键关更可观测性差；也无 issue
    （设计语义：自动路无对话对象、防刷屏）⇒「为什么这句没配音」在 hook 开态
    三面（卡/status/issue）皆无处可查，只剩一条生产会丢的 logger.info。
    将来补留痕时此锁必红 ⇒ 强制摘牌更新台账。"""
    cfg = _config(
        tmp_path,
        bot_tts_ref_audios=[_ref_entry(tmp_path)],
        bot_tts_hard_max_chars=20,
        bot_tts_auto_reply_enabled=True,
        bot_tts_auto_reply_scope="private",
        bot_tts_auto_reply_probability=1.0,
        bot_tts_voice_hook_enabled=True,
    )
    long_body = "一二三四五六七八九十。" * 3
    enrich = ve.build_voice_enricher(cfg)
    out = enrich(_msg("无所谓"), _decision(), _chat_result(long_body))
    assert out.operational_issue is None
    assert "over_hard_cap" not in out.audit_tags, "键开态今天确实零留痕"
    assert not out.audio

    # 对照：旧包装（键关路）同输入有留痕——证明「零留痕」是 hook 路的回退而非全局语义。
    legacy = tts_mod.maybe_attach_voice(_msg("无所谓"), _chat_result(long_body), config=cfg)
    assert "over_hard_cap" in legacy.audit_tags


# ===========================================================================
# M4 content_sha256：缓存命中与未命中两路
# ===========================================================================

def test_surface_cache_miss_then_hit_same_digest_and_skips_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """未命中路：合成→落盘→部件带 content_sha256=落盘字节真值；命中路：**再打 HTTP
    计数为 1 不变**、同一路径、同一摘要；两路 audit_tags 各带 audio_sha256=[:16]。"""
    good = _wav_bytes(32000, 3200)
    stats = _install_fake_httpx(monkeypatch, response=good)
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    capability = build_tts_capability(cfg)
    first = capability(_msg("说 缓存两路样本"), None)
    second = capability(_msg("说 缓存两路样本"), None)

    assert stats["calls"] == 1, "命中路不得重打引擎"
    part1, part2 = first.audio[0], second.audio[0]
    assert part1["file"] == part2["file"]
    digest = hashlib.sha256(good).hexdigest()
    assert part1["content_sha256"] == digest, "未命中路摘要=落盘字节真值"
    assert part2["content_sha256"] == digest, "命中路与未命中路同一语义"
    assert f"audio_sha256={digest[:16]}" in first.audit_tags
    assert f"audio_sha256={digest[:16]}" in second.audit_tags


def test_surface_cache_hit_survives_backoff_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """缓存查找先于退避闸（synthesize docstring 在册语义）：窗内**已合成的句子照常
    出货**（部件+摘要俱在、零 issue、零新 HTTP），新句才吃快速失败。"""
    good = _wav_bytes(32000, 3200)
    stats = _install_fake_httpx(monkeypatch, response=good)
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    capability = build_tts_capability(cfg)
    capability(_msg("说 窗内旧句"), None)

    tts_mod._record_failure("服务不可达：模拟进窗")
    cached = capability(_msg("说 窗内旧句"), None)
    fresh = capability(_msg("说 窗内新句"), None)

    assert stats["calls"] == 1
    assert cached.audio and cached.operational_issue is None
    assert not fresh.audio and fresh.operational_issue is not None


def test_surface_digest_unavailable_degrades_honestly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """摘要算不出（中央件返回 None）：部件**不带键**、audit_tags 不带 audio_sha256、
    照常出货零 issue——「诚实降级」不许翻成静默假值，也不许阻断出站。"""
    good = _wav_bytes(32000, 3200)
    _install_fake_httpx(monkeypatch, response=good)
    monkeypatch.setattr(tts_mod, "media_digest_file", lambda *_a, **_k: None)
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    result = build_tts_capability(cfg)(_msg("说 摘要缺失样本"), None)

    assert result.audio, "摘要是增益件，缺摘要不拦出货"
    assert "content_sha256" not in result.audio[0]
    assert not any(tag.startswith("audio_sha256=") for tag in result.audit_tags)
    assert result.operational_issue is None


# ===========================================================================
# M5 参考音缺失
# ===========================================================================

def test_surface_no_ref_unconfigured_hint_and_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """BOT_TTS_REF_AUDIOS 未配：①text 引导+issue=tts_no_ref_audio 不可重试；
    ②用户拿到「怎么配」的可读方向；③不打引擎（calls==0）。status 面无专行
    （报告 §1 如实记：此类失败运维只经 issue 一路）。"""
    stats = _install_fake_httpx(monkeypatch, response=_wav_bytes(32000, 3200))
    cfg = _config(tmp_path, bot_tts_ref_audios=[])
    result = build_tts_capability(cfg)(_msg("说 无参考音样本"), None)

    assert stats["calls"] == 0
    assert "BOT_TTS_REF_AUDIOS" in (result.body or "")
    issue = result.operational_issue
    assert issue is not None and (issue.kind, issue.retryable) == ("tts_no_ref_audio", False)
    assert "未配置" in issue.safe_summary


def test_surface_no_ref_files_missing_names_the_search_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """配了但文件全找不到：引导文案指向路径基准，issue detail 说「全部读不到」
    ——与「未配置」形态**可判别**（运维据此分「没配」与「配错」两种修法）。"""
    _install_fake_httpx(monkeypatch, response=_wav_bytes(32000, 3200))
    ghost = tmp_path / "does-not-exist.flac"
    cfg = _config(tmp_path, bot_tts_ref_audios=[f"{ghost}|参考|zh"])
    result = build_tts_capability(cfg)(_msg("说 参考音失联样本"), None)

    assert "BOT_TTS_GPTSOVITS_DIR" in (result.body or "")
    issue = result.operational_issue
    assert issue is not None and issue.kind == "tts_no_ref_audio"
    assert "全部读不到" in issue.safe_summary


def test_surface_autodub_no_ref_maps_through_central_to_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """自动配音腿无参考音：hook 派中央变换形 → 真身逐块 dub 打产出步 → 产出步
    ``no_ref`` → 中央 handler 终态 NOT_CONFIGURED → 真身 ``_no_ref_audio_issue`` 映射
    tts_no_ref_audio issue（**有出路**：随呈现结果进告警链）。判据取终态枚举，
    而非「handler 有没有跑」；合成原语 ``boom`` 插雷证 no_ref 不触达引擎（stats==0）。
    S91 退役内联后本发走的是「派发 autodub_transform → 真身产出 → 错误映成可见 issue」
    这条生产真链，故 default_invoker 须同时在册变换形与产出步两枚真身 handler。"""
    stats = _install_fake_httpx(monkeypatch)

    def boom(**_kw: object) -> None:
        raise AssertionError("无 ref 不得触达合成原语")

    monkeypatch.setattr(ve, "synthesize", boom)
    monkeypatch.setattr(
        ve,
        "default_invoker",
        lambda: _private_invoker("media.tts.autodub_transform", "media.tts.autodub"),
    )
    cfg = _config(
        tmp_path,
        bot_tts_ref_audios=[],
        bot_tts_auto_reply_enabled=True,
        bot_tts_auto_reply_scope="private",
        bot_tts_auto_reply_probability=1.0,
        bot_tts_auto_reply_max_chars=0,
        bot_tts_voice_hook_enabled=True,
    )
    out = ve.build_voice_enricher(cfg)(_msg("无所谓"), None, _chat_result("潮汐很安静"))

    assert stats["calls"] == 0
    issue = out.operational_issue
    assert issue is not None and issue.kind == "tts_no_ref_audio"
    assert out.body == "潮汐很安静" and not out.audio, "文字照发、配音放弃"


# ===========================================================================
# M6 voice hook 开态失败面
# ===========================================================================

def _hook_cfg(tmp_path: Path, **over: object) -> SimpleNamespace:
    return _config(
        tmp_path,
        bot_tts_ref_audios=[_ref_entry(tmp_path)],
        bot_tts_auto_reply_enabled=True,
        bot_tts_auto_reply_scope="private",
        bot_tts_auto_reply_probability=1.0,
        # 真身 transform_presentation 缺此键即诚实放弃（SIZING_MISSING，永不到取文/合成/dub），
        # 故 hook 开态的产出/异常面用例必须带上它才能把链路真跑到；0=不限（M-35 语义）。
        bot_tts_auto_reply_max_chars=0,
        bot_tts_voice_hook_enabled=True,
        **over,
    )


def test_surface_hook_synth_failure_maps_issue_via_prefix_taxonomy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """首块合成失败（原因串带「服务不可达」前缀）：hook 派变换形 → 真身 dub 打产出步 →
    中央 handler FAILED.detail（原因串透传真身 seam）→ 真身 ``_failure_issue`` 前缀表 →
    kind=tts_service_unreachable 可重试；文字正文逐字保留。合成桩打在真 seam
    （``ve.synthesize``→`_dub` context→产出步 synth）上，非已消失的内联直呼。"""

    def failing_synth(**_kw: object) -> tuple[None, str]:
        return None, "服务不可达：注入式断网"

    monkeypatch.setattr(ve, "synthesize", failing_synth)
    monkeypatch.setattr(
        ve,
        "default_invoker",
        lambda: _private_invoker("media.tts.autodub_transform", "media.tts.autodub"),
    )
    out = ve.build_voice_enricher(_hook_cfg(tmp_path))(
        _msg("无所谓"), None, _chat_result("潮汐很安静")
    )

    issue = out.operational_issue
    assert issue is not None and (issue.kind, issue.retryable) == ("tts_service_unreachable", True)
    assert out.body == "潮汐很安静" and not out.audio


def test_surface_hook_internal_exception_attaches_visible_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """真身取文口抛异常 → 被兜成 tts_synthesize_failed issue、**不冒泡**（异常若冒泡会走
    pipeline._internal_error 出卡——今天到不了那里，本锁把「不抛=不出卡」钉成事实）。

    S91 退役内联后取文口住在 ``result_transform.transform_presentation``（hook 里已无
    ``resolve_speech_text``，故旧桩 ``ve.resolve_speech_text`` 指向不存在符号）；体内异常今天
    由**真身的 except** 兜（留痕词 ``voice transform failed``），不再是 hook 体的 ``voice hook
    failed``。kind=tts_synthesize_failed / 不冒泡 / 正文照发三条错误面语义逐字保留，未放宽。"""

    def exploding(*_a: object, **_k: object) -> tuple[str, str]:
        raise RuntimeError("取文炸了")

    monkeypatch.setattr(rt, "resolve_speech_text", exploding)
    monkeypatch.setattr(
        ve,
        "default_invoker",
        lambda: _private_invoker("media.tts.autodub_transform", "media.tts.autodub"),
    )
    out = ve.build_voice_enricher(_hook_cfg(tmp_path))(
        _msg("无所谓"), None, _chat_result("潮汐很安静")
    )

    issue = out.operational_issue
    assert issue is not None and issue.kind == "tts_synthesize_failed"
    assert "voice transform failed" in issue.safe_summary
    assert out.body == "潮汐很安静"


def test_surface_hook_partial_chunks_fail_without_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """拆条半程失败（S-VSPLIT 在册设计）：已合成块照发、失败**不挂 issue**，
    只有 split=a/b 机读标签——告警面对半程故障今天无感知（缺口在报告 §2 登记，
    本锁钉现状）。"""
    ok_wav = tmp_path / "chunk-ok.wav"
    ok_wav.write_bytes(_wav_bytes(32000, 800))
    calls = {"n": 0}

    def first_ok_then_fail(**_kw: object) -> tuple[Any, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            return ok_wav, ""
        return None, "服务不可达：第二块断网"

    monkeypatch.setattr(ve, "synthesize", first_ok_then_fail)
    monkeypatch.setattr(
        ve,
        "default_invoker",
        lambda: _private_invoker("media.tts.autodub_transform", "media.tts.autodub"),
    )
    cfg = _hook_cfg(tmp_path, bot_tts_auto_reply_split_max_chars=8)
    out = ve.build_voice_enricher(cfg)(_msg("无所谓"), None, _chat_result("一二三四五。六七八九十。"))

    assert calls["n"] == 2
    assert len(out.audio or []) == 1, "首块成品照发"
    assert out.operational_issue is None, "半程故障今天不挂 issue（现状快照）"
    assert any(tag.startswith("split=1/") for tag in out.audit_tags)


def test_gap_hook_timeout_ignores_invoker_error_key_no_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """GAP-HOOK-TIMEOUT-NO-CARD（显式命名缺口锁）：中央对 TIMEOUT 已把
    ``CapabilityTimeout`` 塞进 ``INVOKER_ERROR_DATA_KEY`` 交回层 1 出诊断卡
    （orchestrated_command 腿已执法），但 **hook 直呼腿不消费该键**——挂死满预算
    只有 issue、没有卡。本锁以伪造 TIMEOUT 信封（90s 预算离线不可真等）钉死：
    ①不抛 ②issue 挂上 ③载荷里的错误键被逐字无视。补上消费点后此锁必红⇒摘牌。"""
    timeout_error = cp.CapabilityTimeout("media.tts.autodub 超过中央预算 90s")
    envelope = cp.InvocationResult(
        capability_id="media.tts.autodub",
        status=cp.InvocationStatus.TIMEOUT,
        detail="超时 90s（线程跑到自然结束，结果弃用）",
        via="invoker",
        data={cp.INVOKER_ERROR_DATA_KEY: timeout_error},
    )

    class _TimeoutInvoker:
        def invoke(self, _request: Any) -> cp.InvocationResult:
            return envelope

    monkeypatch.setattr(ve, "default_invoker", lambda: _TimeoutInvoker())
    monkeypatch.setattr(ve, "synthesize", lambda **_kw: (_ for _ in ()).throw(AssertionError("不该被跑到")))
    out = ve.build_voice_enricher(_hook_cfg(tmp_path))(
        _msg("无所谓"), None, _chat_result("潮汐很安静")
    )

    assert out.operational_issue is not None, "TIMEOUT 至少要有 issue（M-13 自动半在册）"
    assert out.operational_issue.kind == "tts_synthesize_failed", "detail 无登记前缀 ⇒ 落兜底 kind"
    assert not out.audio and out.body == "潮汐很安静"
    # 缺口本体：INVOKER_ERROR_DATA_KEY 在场而 hook 不读 ⇒ 无异常冒泡 = 无诊断卡。
    assert cp.INVOKER_ERROR_DATA_KEY in envelope.data, "中央确实交了错误载荷（字段存在≠执法）"


def test_injection_kind_taxonomy_dead_breaks_surface_classification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """注毒③：把失败分类口伪造成恒定兜底 → 不可达形态的 issue kind 当场失真。
    反证各面 kind 断言咬在真前缀表上，不是「只要有 issue 就算绿」。"""
    _install_fake_httpx(monkeypatch, raise_exc=ConnectionError())
    monkeypatch.setattr(tts_mod, "_failure_kind_tag", lambda _reason: "tts_synthesize_failed")
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    result = build_tts_capability(cfg)(_msg("说 注毒分类样本"), None)
    assert result.operational_issue is not None
    assert result.operational_issue.kind != "tts_service_unreachable", "分类口失效必失真——锁杀伤力反证"


# ===========================================================================
# M7 creation.tts.synthesize 直呼失败面
# ===========================================================================

def _creation_request(cfg: Any, *, payload: dict[str, Any], synth: Any = None) -> Any:
    context: dict[str, Any] = {"config": cfg}
    if synth is not None:
        context["synthesize"] = synth
    return cp.CapabilityRequest(
        capability_id="creation.tts.synthesize",
        payload=payload,
        principal="u-direct",
        roles=("user",),
        request_id="req-direct",
        session_key="private:u-direct",
        context=context,
    )


def test_surface_creation_direct_engine_failure_is_failed_envelope_with_audit(
    tmp_path: Path,
) -> None:
    """provider 判定源在案（bot_tts_api_url 非空）⇒ 门放行、执行体真委派：引擎失败
    终态 FAILED、detail=「kind：原因」（过打码口），**不抛异常**；运维出路=中央审计
    一行（生产 sink 由 root attach_default_audit_sink 注册）+ 控制面 4xx/5xx 投影。
    诊断卡不出（直呼者非 pipeline，异常从未发生）。"""
    audits: list[Any] = []
    invoker = _private_invoker("creation.tts.synthesize", audits=audits)

    def failing_synth(**_kw: object) -> tuple[None, str]:
        return None, "服务不可达：直呼面断网"

    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    result = invoker.invoke(_creation_request(cfg, payload={"text": "潮汐很安静"}, synth=failing_synth))

    assert result.status is cp.InvocationStatus.FAILED
    assert result.detail.startswith("tts_service_unreachable：服务不可达")
    assert "audio_file" not in result.data
    assert len(audits) == 1 and audits[0].capability_id == "creation.tts.synthesize"
    assert audits[0].status is cp.InvocationStatus.FAILED


def test_surface_creation_provider_gate_absent_is_unavailable_not_raise(
    tmp_path: Path,
) -> None:
    """provider 判定源全空：终态 UNAVAILABLE，原因点名三枚待配键（禁静默）；
    不抛 ⇒ 直呼面无卡，出路只剩诚实 detail；控制面路则按状态表映射 503
    （``_FAILURE_HTTP`` 在册投影，本锁钉表条目防「态漂码不漂」）。"""
    invoker = _private_invoker("creation.tts.synthesize")
    cfg = _config(tmp_path, bot_tts_api_url="", bot_tts_ref_audios=[])
    result = invoker.invoke(_creation_request(cfg, payload={"text": "潮汐很安静"}))

    assert result.status is cp.InvocationStatus.UNAVAILABLE
    assert result.via == "creation_tts_provider_gate"
    for key in ("bot_tts_api_url", "bot_tts_ref_audios", "bot_creation_tts_provider"):
        assert key in result.detail, "缺什么必须点什么名"

    from plugins.bot_unified_runtime.domains.creation.tts.routes import _FAILURE_HTTP

    assert _FAILURE_HTTP[cp.InvocationStatus.UNAVAILABLE] == (503, "tts_unavailable")


def test_surface_creation_contract_missing_text_fails_before_provider_gate(
    tmp_path: Path,
) -> None:
    """契约面：payload 既无 job 又无 text ⇒ FAILED（先于 provider 判定），
    原因可读。钉「垃圾进不烧引擎」的次序终态。"""
    invoker = _private_invoker("creation.tts.synthesize")
    cfg = _config(tmp_path, bot_tts_ref_audios=[_ref_entry(tmp_path)])
    result = invoker.invoke(_creation_request(cfg, payload={}))

    assert result.status is cp.InvocationStatus.FAILED
    assert "缺少 text" in result.detail


def test_creation_reserved_alert_honours_execution_presence(
    tmp_path: Path,
) -> None:
    """GAP-CREAT-ALERT-STALE **已摘牌转正向回归锁**（2026-09-24T00:07Z 主代理落码）。

    原缺口：presence 键含 `bot_tts_api_url`（生产缺省恒非空）⇒ 每查一次
    ``/bot status`` 就产一条「provider 已配置但实现工厂未接入」的假告警，
    而 P4-C2 之后 `creation.tts.synthesize` 的 handler 早已在册——话术与事实相反。

    现行判据（两腿）：①provider 已配 ②**中央执行体不在场**。本锁用真册
    （``cp.has_registered_handler``，即根装配真正注入的那枚谓词）走一遍：
    执行体在场 ⇒ 该通道不得进 findings、不得 pending、不得投递。
    """
    cfg = _config(
        tmp_path,
        bot_tts_api_url="http://127.0.0.1:9880",
        bot_tts_ref_audios=[_ref_entry(tmp_path)],
    )
    handler = cp.default_invoker().handlers.get("creation.tts.synthesize")
    assert handler is not None, "前提：执行体今天确已在册（缺了这条本锁失去对照物）"
    assert cp.has_registered_handler("creation.tts") is True  # 通道稳定写法也认得

    reserved_alert.install_execution_presence_probe(cp.has_registered_handler)
    try:
        findings = reserved_alert.check_reserved_channels(cfg)
        received: list[Any] = []
        reserved_alert.install_reserved_alert_sink(received.append)
        assert reserved_alert.flush_reserved_issues_to_alerts() == 0
    finally:
        reserved_alert.install_execution_presence_probe(None)
        reserved_alert.install_reserved_alert_sink(None)

    # 语音通道不再被误判；绘画仍诚实（无 provider ⇒ 连"要而不得"都不算）。
    assert "creation.tts" not in findings
    assert received == []
