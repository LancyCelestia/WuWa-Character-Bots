"""语音失败的可见性回归（bot.tts，M-13 P1，2026-09-19 修复波 S8 首批）。

审计实证（`report-T14.md` / `report-T26.md`）：
- `tts.py` 五条失败出口**全部 `logger.info`**，而该 logger 不在 `nonebot` 日志树上
  （根 `__init__.py` 只 `attach_to_logging("nonebot")`）⇒ **生产必然丢失**；
- 结果里 **零 `OperationalIssue`** ⇒ 中央 `_notify_operational_receipt` 早退、
  错误卡不挂、告警零条：**引擎整夜不跑，管理员完全不知道**；
- 自动配音失败还返回**未改动的原 result**，事后连「配过但失败」都拿不出证据。

本波只锁**命令式路径**（`说 …`）：失败必须挂上结构化 issue，且 `safe_summary`
不得带盘符路径/密钥形态（AGENTS 铁律 3）。自动配音保持「失败原样返回」这条
既有不变量**刻意不动**（`test_maybe_attach_voice_survives_failure` 锁着它），
其可观测性属中央 post-process hook（T10 Phase 3 / T30 S14）的施工范围。
全离线，零网络零落盘。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    build_tts_capability,
)


def _config(**overrides: object) -> object:
    base: dict = {
        "bot_tts_enabled": True,
        "bot_tts_api_url": "http://127.0.0.1:9880",
        "bot_tts_gptsovits_dir": "",
        "bot_tts_ref_audios": [],
        "bot_tts_trigger_words": [],
        "bot_tts_output_dir": "data/tts_output",
        "bot_tts_max_chars": 200,
        "bot_tts_timeout_seconds": 60.0,
        "bot_tts_speed_factor": 0.85,
        "bot_tts_temperature": 0.9,
        "bot_tts_top_k": 15,
        "bot_tts_top_p": 1.0,
        "bot_tts_text_lang": "zh",
        "bot_tts_text_split_method": "cut5",
        "bot_tts_cache_enabled": True,
    }
    base.update(overrides)
    from types import SimpleNamespace

    return SimpleNamespace(**base)


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


def _run(monkeypatch, tmp_path: Path, *, reason: str, refs: list[str] | None = None):
    if refs is None:
        ref = tmp_path / "ref.flac"
        ref.write_bytes(b"fLaC")
        monkeypatch.setattr(
            tts_mod,
            "pick_ref_audio",
            lambda *_a, **_k: tts_mod.RefAudio(path=str(ref), text="", lang="zh"),
        )
    else:
        monkeypatch.setattr(tts_mod, "pick_ref_audio", lambda *_a, **_k: None)
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kw: (None, reason))
    cfg = _config(bot_tts_ref_audios=refs if refs is not None else [f"{tmp_path}/ref.flac||zh"])
    return build_tts_capability(cfg)(_msg("说 今天的潮汐很安静"), None)


def test_unreachable_service_attaches_structural_issue(monkeypatch, tmp_path: Path) -> None:
    result = _run(monkeypatch, tmp_path, reason="服务不可达：ConnectError")
    issue = result.operational_issue
    assert issue is not None, "失败必须留下结构化证据（M-13）"
    assert issue.kind == "tts_service_unreachable"
    assert issue.retryable is True
    assert issue.safe_summary


def test_rejected_service_attaches_issue_with_reason_kind(monkeypatch, tmp_path: Path) -> None:
    result = _run(monkeypatch, tmp_path, reason="服务返回 400：参考音频在3~10秒范围外")
    assert result.operational_issue is not None
    assert result.operational_issue.kind == "tts_service_rejected"


def test_missing_ref_audio_attaches_non_retryable_issue(monkeypatch, tmp_path: Path) -> None:
    result = _run(monkeypatch, tmp_path, reason="", refs=[])
    issue = result.operational_issue
    assert issue is not None
    assert issue.kind == "tts_no_ref_audio"
    assert issue.retryable is False


@pytest.mark.parametrize(
    "reason",
    [
        r"服务不可达：无法访问 C:\Users\lancy\Desktop\secret\note.txt",
        "服务返回 500：BOT_SUPER_ADMIN_API_KEY=sk-TESTFAKE12345",
    ],
)
def test_issue_summary_never_carries_paths_or_secrets(monkeypatch, tmp_path: Path, reason: str) -> None:
    """issue 会进诊断卡与告警面：`safe_summary` 不得带盘符路径或密钥形态。"""
    result = _run(monkeypatch, tmp_path, reason=reason)
    issue = result.operational_issue
    assert issue is not None
    summary = issue.safe_summary
    assert "sk-TESTFAKE12345" not in summary
    assert "C:\\" not in summary and "Desktop" not in summary
    assert result.body == result.body.strip()


def test_success_path_still_has_no_issue(monkeypatch, tmp_path: Path) -> None:
    wav = tmp_path / "voice.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    ref = tmp_path / "ref.flac"
    ref.write_bytes(b"fLaC")
    monkeypatch.setattr(
        tts_mod,
        "pick_ref_audio",
        lambda *_a, **_k: tts_mod.RefAudio(path=str(ref), text="", lang="zh"),
    )
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kw: (wav, ""))
    result = build_tts_capability(_config())(_msg("说 今天的潮汐很安静"), None)
    assert result.operational_issue is None
    assert result.audio and result.audio[0]["review_text"] == "今天的潮汐很安静"


def test_issue_severity_is_not_critical(monkeypatch, tmp_path: Path) -> None:
    """语音失败不该把整条结果的 risk 抬到 CRITICAL（那会让回执语义变形）。"""
    result = _run(monkeypatch, tmp_path, reason="服务不可达：ConnectError")
    assert result.risk_level is not RiskLevel.CRITICAL


# ==================== 群聊侧后果（挂 issue 的连带语义，必须显式记账）====================


def _group_msg() -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id="group:30000",
        session_type=SessionType.GROUP,
        sender_id="20000",
        group_id="30000",
        plain_text="说 今天的潮汐很安静",
        mentions_bot=True,
    )


@pytest.mark.parametrize(
    ("session_type", "expected_body_kept"),
    [(SessionType.PRIVATE, True), (SessionType.GROUP, False)],
)
def test_group_failure_hands_over_to_central_notice(
    monkeypatch, tmp_path: Path, session_type: SessionType, expected_body_kept: bool
) -> None:
    """挂上 issue 之后，群聊失败改走中央 A-19 降级通知（正文清空），私聊仍回人格文案。

    这是**有意的行为变更**：此前群里的「嗓子还没接上……」是本域自己拼的文案，
    与中央「失败细节不回群、降级正文只出自文案池、细节走管理员告警链」的既定
    语义分叉（统一协议 mandate）。私聊零变化。
    """
    from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
        RuntimePipeline,
    )
    from plugins.bot_unified_runtime.sender.queue import InMemorySendQueue

    message = _group_msg().model_copy(update={"session_type": session_type})
    if session_type is SessionType.PRIVATE:
        message = message.model_copy(update={"session_id": "private:20000", "group_id": ""})
    result = _run(monkeypatch, tmp_path, reason="服务不可达：ConnectError")
    assert result.operational_issue.kind == "tts_service_unreachable"

    def _capability(_msg: IncomingMessage, _dec: object) -> object:
        return result.model_copy(update={"request_id": message.request_id})

    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit)
    receipt = RuntimePipeline(queue, audit).handle(message, _capability, "bot.tts")

    if expected_body_kept:
        # 私聊零变化：人格降级文案照常送达，issue 只作为旁路证据跟着回执走。
        sent = queue.sent_requests[0]
        assert sent.capability_id == "bot.tts"
        assert "嗓子还没接上" in sent.content.text_fallback
        assert receipt.operational_issue is not None
        return
    # 群：主回执静默，降级正文改由中央池供给（恰好一句，且不含失败细节）。
    assert receipt.public_message == ""
    notices = [r for r in queue.sent_requests if r.capability_id == "bot.group_failure_notice"]
    assert len(notices) == 1
    assert "ConnectError" not in notices[0].content.text_fallback
