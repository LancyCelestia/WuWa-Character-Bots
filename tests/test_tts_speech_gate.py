"""语音侧内容门与打码定序回归（bot.tts，2026-09-19 修复波 S2/S3）。

审计实证（`.superpowers/sdd/2026-09-19-unify-audit/report-T29.md`）：

- **M-02（P0）**：`tts.py` 取正文 → 清洗 → 合成全链**零内容政策件**，语音侧对红线内容
  不设防；叠加审核层对 `audio` 结构性失明（`reviewer.py` 只看 `body or summary or title`），
  语音通道对内容安全**双重免疫**。
- **M-03（P0）**：命令式 `说 …` 全链零 `redact_local_secrets`；且 `_MARKDOWN_MARKS_RE`
  吃下划线 ⇒ 若「先清洗后打码」，`BOT_..._KEY=X` 会被洗成 `BOT...KEY=X`（下划线消失），
  中央两条打码正则双双失配，密钥跟着音频出门。**打码必须前置于一切有损变换**。

本文件的边界（刻意的）：**不在此重复测中央检测器命中什么**——那是
`tests/test_content_safety_v2.py` 的职责。本文件只锁三件事：
①语音面**服从**中央裁决（中央说 refuse 就必须不合成）；
②语音面与文字面**同源**（调的是同一个 `assess_public_content`、同一个
  `explicit_allowed_for_session`，参数口径一致）；
③打码**定序**（前置于清洗）与政策件不可用时的 **fail-closed**。
全离线，零网络零落盘，不含任何真实敏感语料。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.content_safety import (
    SafetyAssessment,
)
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    clean_for_speech,
    resolve_speech_text,
)

_HARMLESS = "今天的潮汐很安静，海风也很温柔。"
# 形如密钥的**假值**（不含任何真实凭据），只用来验打码定序。
_SECRET_SHAPE = "BOT_SUPER_ADMIN_API_KEY=sk-TESTFAKE12345 记得看海"


def _config(**overrides: object) -> SimpleNamespace:
    base = {
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
        "bot_tts_auto_reply_enabled": False,
        "bot_tts_auto_reply_scope": "private",
        "bot_tts_auto_reply_max_chars": 120,
        "bot_tts_auto_reply_probability": 0.05,
        "bot_tts_auto_reply_always": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _msg(text: str = "在吗", *, group_id: str = "") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id=f"group:{group_id}" if group_id else "private:20000",
        session_type=SessionType.GROUP if group_id else SessionType.PRIVATE,
        sender_id="20000",
        group_id=group_id,
        plain_text=text,
    )


def _refuse(monkeypatch, category: str = "minors") -> None:
    """把中央裁决桩成 refuse（测的是语音面服不服从，不是中央检测器）。"""
    monkeypatch.setattr(
        tts_mod,
        "assess_public_content",
        lambda *_a, **_k: SafetyAssessment("refuse", category, "stubbed", "stubbed"),
    )


def test_ordinary_text_passes() -> None:
    text, reason = resolve_speech_text(_config(), _msg(), _HARMLESS)
    assert reason == ""
    assert text == _HARMLESS


def test_speech_refused_when_central_policy_says_no(monkeypatch) -> None:
    _refuse(monkeypatch)
    text, reason = resolve_speech_text(_config(), _msg(), _HARMLESS)
    assert reason == "minors"
    assert text == "", "中央判定不放行时，语音面不得自行放行"


def test_voice_gate_shares_the_text_policies_single_source(monkeypatch) -> None:
    """同源锁：语音面必须调中央那一个 `assess_public_content`，且会话口径与
    `explicit_allowed` 都取自文字面同一事实源——否则就是第二条红线漂移面。"""
    seen: dict = {}

    def _spy(text: str, **kwargs: object):
        seen.update(kwargs)
        return SafetyAssessment("allow", "none", "", "")

    monkeypatch.setattr(tts_mod, "assess_public_content", _spy)
    allow_calls: list[tuple] = []

    def _spy_allow(session_type, group_id, config, sender_id=""):
        allow_calls.append((session_type, group_id, sender_id))
        return True

    monkeypatch.setattr(tts_mod, "explicit_allowed_for_session", _spy_allow)
    resolve_speech_text(_config(), _msg(group_id="30000"), _HARMLESS)
    assert seen.get("session_type") == "group"
    assert seen.get("explicit_allowed") is True
    assert allow_calls == [("group", "30000", "20000")]


def test_gate_is_fail_closed_when_policy_unavailable(monkeypatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("policy module unavailable")

    monkeypatch.setattr(tts_mod, "assess_public_content", _boom)
    text, reason = resolve_speech_text(_config(), _msg(), _HARMLESS)
    assert text == "", "政策件异常时绝不放行（fail-closed）"
    assert reason == "policy_unavailable"


def test_secrets_are_redacted_before_lossy_cleaning() -> None:
    text, reason = resolve_speech_text(_config(), _msg(), _SECRET_SHAPE)
    assert reason == ""
    assert "sk-TESTFAKE12345" not in text, "密钥值泄漏进朗读正文"
    assert "TESTFAKE12345" not in text
    assert "<" not in text and ">" not in text, "残缺占位符会被念成怪音"
    assert "已隐去" in text, "打码未生效或占位符未转为可读形态"


def test_cleaning_alone_would_have_destroyed_the_marker() -> None:
    """定序证据（特征化锁）：清洗本身确实吃下划线，故打码不能放在它后面。"""
    cleaned = clean_for_speech(_SECRET_SHAPE)
    assert "_" not in cleaned
    assert "sk-TESTFAKE12345" in cleaned, "清洗单独使用等于把密钥留给出站"


def test_auto_reply_path_never_synthesizes_refused_body(monkeypatch, tmp_path: Path) -> None:
    _refuse(monkeypatch)
    calls: list[dict] = []

    def _fake_synthesize(**kwargs: object):
        calls.append(kwargs)
        return (tmp_path / "voice.wav", "")

    monkeypatch.setattr(tts_mod, "synthesize", _fake_synthesize)
    monkeypatch.setattr(
        tts_mod,
        "pick_ref_audio",
        lambda *_a, **_k: tts_mod.RefAudio(path=str(tmp_path / "ref.flac"), text="", lang="zh"),
    )
    original = CapabilityResult(
        request_id="req-gate-1",
        capability_id="bot.chat",
        kind="text",
        body=_HARMLESS,
    )
    out = tts_mod.maybe_attach_voice(
        _msg(),
        original,
        config=_config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_always=True),
    )
    assert calls == [], "不放行的正文不得送去合成"
    assert out.audio == [], "被拒的回复不应带上语音"
    assert out.body == _HARMLESS, "文字回复必须原样保留"


def test_command_result_carries_review_text_for_central_review(monkeypatch, tmp_path: Path) -> None:
    """M-02 中央半的接线锁：语音正文必须以 `review_text` 随 audio 部件出门。

    2026-09-25 第 8 项裁定后，命令路的 `body` 不再是空串（出站＝原文本+语音），
    但 `review_text` 这一腿**必须保留**：它是「部件自带文本」的在册读法，
    与 body 走的是 reviewer 的两条采集路径（`_collect_scan_text` 会去重），
    删掉它会让只认部件键的读法（以及 `test_reviewer_media_visibility` 那批
    媒体免检锁）失去覆盖面。
    """
    wav = tmp_path / "voice.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    monkeypatch.setattr(
        tts_mod,
        "pick_ref_audio",
        lambda *_a, **_k: tts_mod.RefAudio(path=str(tmp_path / "ref.flac"), text="", lang="zh"),
    )
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kw: (wav, ""))
    cfg = _config(bot_tts_ref_audios=[f"{tmp_path}/ref.flac||zh"])
    result = tts_mod.build_tts_capability(cfg)(_msg("说 " + _HARMLESS), None)
    assert result.audio, "成功路径应带语音部件"
    assert result.audio[0]["review_text"] == _HARMLESS
    assert result.body == _HARMLESS, "出站须带原文本（第 8 项：原文本+语音音频一起发）"


def test_auto_reply_carries_review_text(monkeypatch, tmp_path: Path) -> None:
    wav = tmp_path / "voice.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kw: (wav, ""))
    monkeypatch.setattr(
        tts_mod,
        "pick_ref_audio",
        lambda *_a, **_k: tts_mod.RefAudio(path=str(tmp_path / "ref.flac"), text="", lang="zh"),
    )
    original = CapabilityResult(
        request_id="req-gate-2", capability_id="bot.chat", kind="text", body=_HARMLESS
    )
    out = tts_mod.maybe_attach_voice(
        _msg(),
        original,
        config=_config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_always=True),
    )
    assert out.audio and out.audio[0]["review_text"] == _HARMLESS


def test_command_capability_returns_hint_instead_of_audio(monkeypatch, tmp_path: Path) -> None:
    _refuse(monkeypatch)
    monkeypatch.setattr(
        tts_mod,
        "pick_ref_audio",
        lambda *_a, **_k: tts_mod.RefAudio(path=str(tmp_path / "ref.flac"), text="", lang="zh"),
    )
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kw: pytest.fail("不应触发合成"))
    cfg = _config(bot_tts_ref_audios=[f"{tmp_path}/ref.flac||zh"])
    message = _msg("说 " + _HARMLESS)
    result = tts_mod.build_tts_capability(cfg)(message, None)
    assert result.audio == []
    assert "blocked_by_policy" in result.audit_tags
    assert result.body, "拒绝要给可理解的回执，不能静默"
