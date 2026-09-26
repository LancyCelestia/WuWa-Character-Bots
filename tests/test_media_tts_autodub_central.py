"""VOICE-V12 · 自动配音产出步 `media.tts.autodub` 中央能力单测（全离线零网络）。

覆盖（设计件 VOICE-AUTO-DUB-CENTRAL-LEG-PLAN-20260922.md §1-C / §4 V1）：
- 四态逐字段等值 + 语义正确：
  1. 成功 → OK，`data` 带 `audio_file/review_text/content_sha256/preset_id/seed`，
     与直呼 `tts.synthesize_autodub` 逐字段相等（接入不改产出）；
  2. 无参考音频 → NOT_CONFIGURED（确定性失败，对应旧 tts_no_ref_audio 码族）；
  3. 合成失败 → FAILED，detail=原样失败原因串（层 1 交 _failure_issue 前缀表分类）；
  4. 政策拒绝≠故障：政策门在层 1（resolve_speech_text），**根本不进中央**（零终态审计行、
     零 issue、只留 audit_tag）——这是与「合成失败」相反的一类，本件锁死两者不混。
- 中央权限门真增量：blocked 主体 → DENIED 且 handler 一次没跑（旧直呼没有这层）。
- 注毒自证：非成功终态不得携带呈现载荷；把成功态的 audio_file 掏空 → 等值锁必红。
- 零副本纪律：合成原语经 context 注入到产出步 seam，生产注入的是 tts.synthesize 本体，
  与直接调用逐字节等价；生效顶（字节顶/落盘配额）唯一家仍是 tts_presets/synthesize。

全离线：合成原语与参考音频选择全部走 tmp_path + 注入替身，绝不打引擎、绝不碰 /control。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    IncomingMessage,
)
from plugins.bot_unified_runtime.domains.media.capabilities import tts
from plugins.bot_unified_runtime.runtime import capability_protocols as cp


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _config(tmp_path: Path, *, with_ref: bool) -> SimpleNamespace:
    ref_audios = [f"{tmp_path / 'ref.wav'}|参考文本|zh"] if with_ref else []
    return SimpleNamespace(
        bot_tts_enabled=True,
        bot_tts_api_url="http://127.0.0.1:9880",
        bot_tts_gptsovits_dir="",
        bot_tts_ref_audios=ref_audios,
        bot_tts_output_dir=str(tmp_path / "tts_out"),
        bot_tts_preset="shorekeeper",
        bot_tts_max_chars=200,
        bot_tts_hard_max_chars=2000,
        bot_tts_max_audio_bytes=0,
        bot_tts_cache_enabled=False,
        bot_tts_cache_max_bytes=0,
        bot_tts_cache_max_age_days=0,
        bot_tts_timeout_seconds=60.0,
        bot_tts_speed_factor=0.85,
        bot_tts_temperature=0.9,
        bot_tts_top_k=15,
        bot_tts_top_p=1.0,
        bot_tts_text_lang="zh",
        bot_tts_text_split_method="cut5",
    )


def _request(config: SimpleNamespace, text: str, *, synth: object, roles: tuple[str, ...] = ("user",)):
    return cp.CapabilityRequest(
        capability_id="media.tts.autodub",
        payload={"text": text},
        principal="u1",
        roles=roles,
        request_id="req-ad",
        session_key="private:u1",
        context={"config": config, "synthesize": synth},
    )


def _invoker() -> cp.CapabilityInvoker:
    """私有 invoker：注册与生产同一份 descriptor + handler，绝不写 default 单例（防跨门假红）。"""
    descriptor = cp.default_invoker().registry.get("media.tts.autodub")
    handler = cp.default_invoker().handlers.get("media.tts.autodub")
    assert descriptor is not None and handler is not None, "media.tts.autodub 未在册/未挂 handler"
    invoker = cp.CapabilityInvoker(
        registry=cp.CapabilityRegistry(), handlers=cp.HandlerRegistry()
    )
    invoker.registry.register(descriptor)
    invoker.handlers.register("media.tts.autodub", handler)
    return invoker


# ---------------------------------------------------------------------------
# 态①：成功 → OK + 音频元数据，与直呼真身逐字段等值
# ---------------------------------------------------------------------------
def test_autodub_success_returns_audio_metadata_and_equals_direct(tmp_path: Path) -> None:
    wav = tmp_path / "tts_out" / "a.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
    (tmp_path / "ref.wav").write_bytes(b"RIFFref")

    def fake_synth(**kwargs: object):
        return wav, ""

    config = _config(tmp_path, with_ref=True)
    result = _invoker().invoke(_request(config, "潮汐很安静", synth=fake_synth))

    assert result.status is cp.InvocationStatus.OK, result.detail
    assert result.via == "tts_autodub"
    data = result.data
    assert data["audio_file"] == str(wav)
    assert data["review_text"] == "潮汐很安静"
    assert data["preset_id"] == "shorekeeper"
    assert isinstance(data["seed"], int)
    # M-64/S2 同构：成功产物带落盘字节摘要（内容身份走中央件 media_digest_file，零本地哈希）。
    assert data["content_sha256"] and len(data["content_sha256"]) == 64

    # 逐字段等值：经中央 handler == 直呼 tts.synthesize_autodub（接入只换调用点、不改产出）。
    code, direct = tts.synthesize_autodub(config, "潮汐很安静", synth=fake_synth)
    assert code == "ok"
    assert direct == data, "经 invoker 的产出与直呼真身不逐字段等值"


# ---------------------------------------------------------------------------
# 态②：无参考音频 → NOT_CONFIGURED（确定性失败，不冒充成功、不带载荷）
# ---------------------------------------------------------------------------
def test_autodub_no_ref_is_not_configured(tmp_path: Path) -> None:
    def boom_synth(**kwargs: object):  # 无 ref 时合成原语绝不该被跑到
        raise AssertionError("无 ref 时不得触达合成")

    config = _config(tmp_path, with_ref=False)
    result = _invoker().invoke(_request(config, "潮汐很安静", synth=boom_synth))

    assert result.status is cp.InvocationStatus.NOT_CONFIGURED, result.status
    assert result.detail.strip()
    assert cp.PRESENTATION_DATA_KEY not in result.data
    assert "audio_file" not in result.data


# ---------------------------------------------------------------------------
# 态③：合成失败 → FAILED + 原样原因串（层 1 交 _failure_issue 分类）
# ---------------------------------------------------------------------------
def test_autodub_synth_failure_is_failed_with_reason(tmp_path: Path) -> None:
    (tmp_path / "ref.wav").write_bytes(b"RIFFref")
    reason = "服务不可达: connection refused"

    def failing_synth(**kwargs: object):
        return None, reason

    config = _config(tmp_path, with_ref=True)
    result = _invoker().invoke(_request(config, "潮汐很安静", synth=failing_synth))

    assert result.status is cp.InvocationStatus.FAILED, result.status
    assert result.detail == reason  # 原因串原样交回，分类在层 1（禁在中央另造 kind）
    assert "audio_file" not in result.data


# ---------------------------------------------------------------------------
# 中央权限门真增量：blocked 主体 → DENIED 且 handler 一次没跑
# ---------------------------------------------------------------------------
def test_autodub_denies_blocked_principal_without_running_handler(tmp_path: Path) -> None:
    (tmp_path / "ref.wav").write_bytes(b"RIFFref")

    def boom_synth(**kwargs: object):
        raise AssertionError("blocked 主体不得触达合成")

    config = _config(tmp_path, with_ref=True)
    result = _invoker().invoke(
        _request(config, "潮汐很安静", synth=boom_synth, roles=("blocked",))
    )

    assert result.status is cp.InvocationStatus.DENIED, result.status
    assert "audio_file" not in result.data


# ---------------------------------------------------------------------------
# 态④：政策拒绝≠故障——门链判「不配」根本不进中央（零终态审计行、零 issue）
# ---------------------------------------------------------------------------
def test_policy_refusal_never_reaches_the_central_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import plugins.bot_unified_runtime.domains.media.voice_enricher as ve

    calls: list[str] = []
    real_invoke = cp.CapabilityInvoker.invoke

    def spy_invoke(self: object, request: object, *a: object, **k: object):
        calls.append(getattr(request, "capability_id", "?"))
        return real_invoke(self, request, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(cp.CapabilityInvoker, "invoke", spy_invoke)
    monkeypatch.setattr(ve, "should_voice_reply", lambda *a, **k: True)
    import plugins.bot_unified_runtime.domains.media.tts.result_transform as rt

    # 门链在 hook（ve）与真身（rt）两处判（should_voice_reply 纯谓词幂等）；本例测政策面，
    # 放行两处门链以隔离他席在飞的门链逻辑，直达取文/政策判定。
    monkeypatch.setattr(rt, "should_voice_reply", lambda *a, **k: True)
    # S91 收编：门链过（should_voice_reply=True）后 hook 派一次中央第三形 result_transform，
    # 取文/内容政策在真身里判（rt.resolve_speech_text 返回 blocked）⇒ 政策拦下 ⇒ 零 dub、
    # 零合成原语、零 issue；合成原语若被触达即炸。mandate「所有内容走中央」后，"该不该配"
    # 的政策判定本身也可被中央审计（此前完全在层 1 内联、零来路记录）——本锁据实反映。
    monkeypatch.setattr(
        rt, "resolve_speech_text", lambda *a, **k: ("", "minors")
    )
    monkeypatch.setattr(
        ve,
        "synthesize",
        lambda **k: pytest.fail("政策拒绝不得触达合成/中央产出步"),
    )

    config = _config(tmp_path, with_ref=True)
    config.bot_tts_voice_hook_enabled = True
    # 真身纪律①：长度键按名字现读、缺省不在本件抄（生产 Config 恒有此键）；本最小夹具补齐，
    # 使流程直达取文/政策判定（0=不限，与命令半同义）。
    config.bot_tts_auto_reply_max_chars = 0
    enrich = ve.build_voice_enricher(config)

    message = IncomingMessage(
        platform="qq", adapter="onebot", bot_id="10000",
        session_id="private:u1", session_type=SessionType.PRIVATE,
        sender_id="u1", group_id="", plain_text="x", message_id="m1", debug_id="d1",
    )
    decision = BotDecision(
        request_id="r1", should_respond=True, mode="command", trigger="t",
        capability_id="bot.chat", target_scope=SessionType.PRIVATE, decision_reason="t",
    )
    result = CapabilityResult(
        request_id="r1", capability_id="bot.chat", kind="text",
        body="潮汐很安静", send_policy=SendPolicy.IMMEDIATE, audit_tags=["chat"],
    )

    enriched = enrich(message, decision, result)

    # 政策拒绝≠故障：不触达产出步/合成（无 autodub invoke、无合成）、不挂 issue、只留
    # blocked_by_policy 留痕；S91 收编后 hook 仍会派一次第三形（政策判定本身入中央审计）。
    assert calls == ["media.tts.autodub_transform"], (
        f"政策拒绝只准派一次中央第三形、绝不触达产出步/合成（实得 {calls}）"
    )
    assert enriched.operational_issue is None, "政策拒绝不得挂 issue"
    assert "blocked_by_policy" in enriched.audit_tags, enriched.audit_tags
    assert enriched.audio == []  # 不配音、文字照发
    assert enriched.body == result.body


# ---------------------------------------------------------------------------
# 注毒自证：掏空成功态的 audio_file → 逐字段等值锁必红（证明上面等值锁真在测）
# ---------------------------------------------------------------------------
def test_success_equality_lock_has_teeth(tmp_path: Path) -> None:
    wav = tmp_path / "tts_out" / "a.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    wav.write_bytes(b"RIFFfake")
    (tmp_path / "ref.wav").write_bytes(b"RIFFref")

    def fake_synth(**kwargs: object):
        return wav, ""

    config = _config(tmp_path, with_ref=True)
    envelope = _invoker().invoke(_request(config, "潮汐很安静", synth=fake_synth))
    assert envelope.status is cp.InvocationStatus.OK

    poisoned = dict(envelope.data)
    poisoned["audio_file"] = ""  # 注入「成功却丢产物路径」
    _, direct = tts.synthesize_autodub(config, "潮汐很安静", synth=fake_synth)
    assert direct != poisoned, (
        "掏空 audio_file 后仍与直呼真身相等＝等值锁空转（应红）"
    )
    assert poisoned != dict(envelope.data)


# ---------------------------------------------------------------------------
# 零副本纪律：产出步不含任何第二份字节顶/硬顶数值（生效顶唯一家在 tts_presets/synthesize）
# ---------------------------------------------------------------------------
def test_descriptor_carries_no_numeric_limits(tmp_path: Path) -> None:
    descriptor = cp.default_invoker().registry.get("media.tts.autodub")
    assert descriptor is not None
    assert descriptor.limits == {}, f"表内又拿数值当天花板（唯一家应是 tts_presets/synthesize）：{descriptor.limits}"
    assert descriptor.timeout_seconds == 90.0, "中央时限须高于域内 60s 权威计时，只做别吊死安全网"
