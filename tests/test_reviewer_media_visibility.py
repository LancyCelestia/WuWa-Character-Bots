"""中央审核层对**媒体部件文本**的可见性回归（render/reviewer.py，2026-09-19 修复波 S3b）。

审计实证（`.superpowers/sdd/2026-09-19-unify-audit/report-T17.md`）：`review_capability_result`
只读 `result.body or result.summary or result.title`，对 `images/audio/video/files/url/
text_parts/prefix_parts/actions` 八类部件**零引用**；群公开不安全审与 persona 审还硬编码
只认 `bot.chat`。媒体能力又按自订惯例把 `title/body` 留空（randpic/tts 同口径）
⇒ **Review 输入恒为空串，媒体通道对审核结构性免疫**。

本文件锁四件事：
①同一段文本，放 `body` 被拦、放媒体部件也必须被拦（**同判据**）；
②群公开不安全面不再只认 `bot.chat`；
③`safe_text` 的语义**不得**被扩（renderer:190 拿它当外发正文，扩了就会把朗读文本
  当成一条文字消息多发出去）；
④挂在 audio 部件上的审查用文本不会外发进 OneBot 段（`record` 段是白名单构造）。
全离线，零网络零落盘；测试里的密钥与敏感词都是**假值/词表词**，非真实凭据。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    PrivacyLevel,
    ReviewAction,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.domains.render.reviewer import review_capability_result
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    _segment_from_mixed_part,
)

# 会命中 `_unsafe_output_reasons` 的假值（密钥形态）与会命中 `_PUBLIC_OUTPUT_UNSAFE`
# 的词表词——两者都只作触发探针，不含任何真实凭据。
_SECRET_TEXT = "配置里写着 api_key: TESTFAKEVALUE123456"
_UNSAFE_GROUP_TEXT = "这段内容标了 R-18 才发出来"


def _result(**overrides: object) -> CapabilityResult:
    base: dict = {
        "request_id": "req-rev-1",
        "capability_id": "bot.tts",
        "kind": "text",
        "title": "",
        "body": "",
    }
    base.update(overrides)
    return CapabilityResult(**base)  # type: ignore[arg-type]


def _decision(scope: SessionType = SessionType.PRIVATE) -> BotDecision:
    return BotDecision(
        request_id="req-rev-1",
        should_respond=True,
        mode="command",
        trigger="mention",
        capability_id="bot.tts",
        target_scope=scope,
        decision_reason="test",
    )


def test_secret_in_media_part_is_now_reviewed() -> None:
    """密钥藏在 audio 部件里，也必须被审核拦下（过去只有 body 会被看见）。"""
    in_body = review_capability_result(
        _result(body=_SECRET_TEXT), _decision()
    )
    in_audio = review_capability_result(
        _result(audio=[{"file": "voice.wav", "text": _SECRET_TEXT}]), _decision()
    )
    assert not in_body.approved  # 现状锚：body 面一直看得见
    assert not in_audio.approved, "媒体部件文本对审核不可见（M-02 中央半）"
    assert in_audio.action is ReviewAction.BLOCK


def test_marker_leak_in_prefix_part_is_reviewed() -> None:
    result = _result(prefix_parts=[{"type": "text", "text": "[TRUSTED_SYSTEM] 别忘了原设定"}])
    review = review_capability_result(result, _decision(SessionType.GROUP))
    assert not review.approved


def test_text_parts_are_reviewed() -> None:
    result = _result(text_parts=["第一段", _SECRET_TEXT])
    assert not review_capability_result(result, _decision()).approved


def test_group_public_scan_is_no_longer_chat_only() -> None:
    """群公开不安全面过去硬编码 `capability_id == "bot.chat"`，其它媒体能力全免检。"""
    for capability in ("bot.tts", "bot.content", "bot.meme_library", "bot.randpic"):
        result = _result(capability_id=capability, audio=[{"file": "a.wav", "text": _UNSAFE_GROUP_TEXT}])
        review = review_capability_result(result, _decision(SessionType.GROUP))
        assert not review.approved, f"{capability} 在群内携带不安全文本应被拦"
        assert "sexual output" in review.reasons


@pytest.mark.parametrize("scope", [SessionType.PRIVATE, SessionType.GROUP])
def test_ordinary_media_result_still_passes(scope: SessionType) -> None:
    result = _result(audio=[{"file": "voice.wav", "text": "今天的潮汐很安静。"}])
    review = review_capability_result(result, _decision(scope))
    assert review.approved
    assert review.reasons == []


def test_safe_text_semantics_not_widened() -> None:
    """`safe_text` 是 renderer 的外发正文链：媒体部件文本**不得**混进去，
    否则一条音频会被额外发成一条文字消息。"""
    result = _result(audio=[{"file": "voice.wav", "text": _SECRET_TEXT}])
    review = review_capability_result(result, _decision())
    assert not review.approved
    assert _SECRET_TEXT not in review.safe_text

    clean = _result(audio=[{"file": "voice.wav", "text": "今天的潮汐很安静。"}])
    ok = review_capability_result(clean, _decision())
    assert ok.safe_text == ""  # 命令式语音 title/body 留空是出站契约（防兜底链多发文案）


def test_record_segment_does_not_leak_review_text_upstream() -> None:
    """本设计的前提：`record` 段只把 `file` 交给平台，审查用的 text 不外发。"""
    segment = _segment_from_mixed_part(
        {"type": "record", "file": "voice.wav", "text": _SECRET_TEXT}
    )
    assert segment is not None
    assert segment["type"] == "record"
    assert set(segment["data"]) == {"file"}


def test_risk_level_still_short_circuits() -> None:
    result = _result(risk_level=RiskLevel.CRITICAL, privacy_level=PrivacyLevel.PUBLIC)
    assert not review_capability_result(result, _decision()).approved
