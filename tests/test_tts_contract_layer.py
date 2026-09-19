"""G-2 契约层 tts.py 行为回归（Wave G T61）。

覆盖（规格=docs/design/tts-contract-layer.md；裁定=progress.md G2-R3）：

- M-35 ``0=不限`` 语义：``bot_tts_max_chars=0`` 不再被 ``or DEFAULT`` 悄悄抬回 200；
- G2-R3 硬顶：文本超 2000 字 / 产物超 8 MiB = 拒绝 + OperationalIssue 留痕，不拆条；
- M-07 静音指纹闸：引擎「200+恰 1s 静音」伪装成功不得落盘/入缓存/出站；
- M-43 第二缺省族删除：模块常量清零，缺键回预设表；
- M-72/U-25 seed 确定性：``seed=-1`` 硬编码改 cache_key 派生，audit_tags 记 seed/preset；
- 缓存键收编 preset 身份 + identity_version（T54 规格 §5，T57 api_url+ref_fp 为基线）；
- U-04：``data/tts_output`` 顺接中央 cache_policy.enforce_quota（缺省关）；
- T56 反审转发：policy_unavailable 挂 issue vs 有意拦截不挂、
  ``<本机路径已隐藏`` 占位符第二形态、_FAILURE_KINDS 全表映射。

全离线，零网络（HTTP 一律 monkeypatch）；落盘只写 tmp_path。
"""

from __future__ import annotations

import io
import wave
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.media import tts_presets
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    RefAudio,
    TtsParams,
    build_tts_capability,
    clean_for_speech,
    resolve_speech_text,
    synthesize,
)

_API = "http://127.0.0.1:9880"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _params(**overrides: object) -> TtsParams:
    base = {
        "text_lang": "zh",
        "speed_factor": 0.85,
        "temperature": 0.9,
        "top_k": 15,
        "top_p": 1.0,
        "text_split_method": "cut5",
    }
    base.update(overrides)
    return TtsParams(**base)  # type: ignore[arg-type]


def _config(**overrides: object) -> SimpleNamespace:
    """最小配置对象：与 test_tts.py 同构，另含 G-2 新键。"""
    base = {
        "bot_tts_enabled": True,
        "bot_tts_api_url": _API,
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
        # G-2 新键（M-35 硬顶 / U-04 配额 / 预设选择）：
        "bot_tts_preset": "shorekeeper",
        "bot_tts_hard_max_chars": 2000,
        "bot_tts_max_audio_bytes": 8 * 1024 * 1024,
        "bot_tts_cache_max_bytes": 0,
        "bot_tts_cache_max_age_days": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _msg(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id="private:20000",
        session_type=SessionType.PRIVATE,
        sender_id="20000",
        group_id=None,
        plain_text=text,
    )


def _ref(tmp_path: Path, name: str = "ref.wav") -> RefAudio:
    path = tmp_path / name
    path.write_bytes(b"RIFF....WAVEfmt ")
    return RefAudio(path=str(path), text="你好", lang="zh")


def _wav_bytes(*, seconds: float = 0.2, rate: int = 32000, amplitude: int = 0) -> bytes:
    """真 PCM16 单声道 wav；amplitude>0 时写入非常量样本（非静音）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        if amplitude:
            frames = bytearray()
            for i in range(int(rate * seconds)):
                value = (amplitude * (i % 97)) % 32767
                frames += int(value).to_bytes(2, "little", signed=True)
            handle.writeframes(bytes(frames))
        else:
            handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod, "_CACHE", OrderedDict())
    monkeypatch.setattr(tts_mod, "_last_failure_at", 0.0)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "")


# ---------------------------------------------------------------------------
# M-35：0=不限 语义统一（or DEFAULT 反转修死）
# ---------------------------------------------------------------------------


def test_clean_for_speech_zero_means_unlimited() -> None:
    long_text = "这是一段很长的文本。" * 60  # 清洗后 > 200 字
    assert len(clean_for_speech(long_text, max_chars=0)) > 200
    assert len(clean_for_speech(long_text, max_chars=200)) <= 200


def test_resolve_speech_text_zero_max_chars_is_not_raised_back() -> None:
    """旧病：`int(x or DEFAULT)` 把显式 0 抬回 200——0 必须保持「不截断」。"""
    config = _config(bot_tts_max_chars=0)
    long_body = "守岸人念一段长文。" * 60
    speech, blocked = resolve_speech_text(config, _msg("说 长文"), long_body, max_chars=0)
    assert blocked == ""
    assert len(speech) > 200


def test_capability_zero_max_chars_reaches_synthesize_untruncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(bot_tts_max_chars=0)
    config.bot_tts_ref_audios = [f"{tmp_path / 'ref.wav'}|你好|zh"]
    (tmp_path / "ref.wav").write_bytes(b"RIFF....WAVEfmt ")
    captured: dict[str, str] = {}

    def _fake_synth(**kwargs: object) -> tuple[Path, str]:
        captured["text"] = str(kwargs.get("text", ""))
        target = tmp_path / "out.wav"
        target.write_bytes(_wav_bytes())
        return target, ""

    monkeypatch.setattr(tts_mod, "synthesize", _fake_synth)
    result = build_tts_capability(config)(_msg("说 " + "守岸人念长文。" * 60), None)
    assert len(captured.get("text", "")) > 200, "0=不限被悄悄抬回 200（M-35 反转面未修）"
    assert result.audio, "长文（0=不限）应照常合成出货"


# ---------------------------------------------------------------------------
# G2-R3 硬顶：超顶=拒绝+留痕，不拆条
# ---------------------------------------------------------------------------


def test_capability_rejects_text_over_hard_cap_with_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(bot_tts_max_chars=0)  # 0=不限也必过硬顶（G-R-M1：不限≠无界）
    config.bot_tts_ref_audios = [f"{tmp_path / 'ref.wav'}|你好|zh"]
    (tmp_path / "ref.wav").write_bytes(b"RIFF....WAVEfmt ")
    monkeypatch.setattr(
        tts_mod, "synthesize", _fail_if_called
    )

    result = build_tts_capability(config)(_msg("说 " + "超长文本。" * 500), None)
    assert not result.audio, "超硬顶必须拒绝合成（不拆条）"
    assert "over_hard_cap" in result.audit_tags
    assert result.body, "命令式拒绝要给引导文案"
    assert result.operational_issue is not None
    assert result.operational_issue.kind == "tts_service_rejected"


def _fail_if_called(**_kwargs: object) -> tuple[Path, str]:
    raise AssertionError("超硬顶/静音拒绝路径不得触达 synthesize")


def test_hard_cap_zero_config_uses_builtin_constant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0=禁配无界：取内置常量（2000），绝不放行无界文本。"""
    config = _config(bot_tts_hard_max_chars=0, bot_tts_max_chars=0)
    config.bot_tts_ref_audios = [f"{tmp_path / 'ref.wav'}|你好|zh"]
    (tmp_path / "ref.wav").write_bytes(b"RIFF....WAVEfmt ")
    monkeypatch.setattr(tts_mod, "synthesize", _fail_if_called)
    result = build_tts_capability(config)(_msg("说 " + "超长文本。" * 500), None)
    assert "over_hard_cap" in result.audit_tags, "硬顶配 0 必须回退内置常量而非无界"


def test_synthesize_rejects_audio_over_byte_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """产物侧超字节顶 → 体检闸拒（tts_bad_audio 族），不入缓存不落盘。"""
    monkeypatch.setattr(tts_mod, "_request_tts", lambda **_k: (_wav_bytes(seconds=0.3), ""))
    config_cap = 1024  # 1 KiB：必然超顶
    path, reason = synthesize(
        api_url=_API,
        text="正文",
        ref=_ref(tmp_path),
        params=_params(),
        output_dir=tmp_path / "out",
        max_audio_bytes=config_cap,
    )
    assert path is None
    assert reason.startswith("音频体检失败")
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").glob("*.wav"))
    issue = tts_mod._failure_issue(_msg("说 x"), reason)
    assert issue.kind == "tts_bad_audio" and issue.retryable is False


def test_byte_cap_zero_uses_builtin_constant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """字节顶 0=禁配无界：回退 8 MiB 内置常量（小产物照常通过）。"""
    monkeypatch.setattr(tts_mod, "_request_tts", lambda **_k: (_wav_bytes(seconds=0.2), ""))
    path, reason = synthesize(
        api_url=_API,
        text="正文",
        ref=_ref(tmp_path),
        params=_params(),
        output_dir=tmp_path / "out",
        max_audio_bytes=0,
    )
    assert path is not None and reason == "", "小于内置 8MiB 常量的产物不得被拒"


# ---------------------------------------------------------------------------
# M-07：静音指纹闸（引擎 200+恰 1s 静音伪装成功）
# ---------------------------------------------------------------------------


def test_engine_silence_trap_detected_by_inspector() -> None:
    """引擎陷阱指纹（T53 §3）：16000Hz + 恰 1s + 全零 int16。"""
    trap = _wav_bytes(seconds=1.0, rate=16000)
    reason = tts_mod._inspect_wav_bytes(trap)
    assert reason, "静音陷阱必须被拒"
    assert "静音" in reason


def test_silence_gate_spares_normal_audio_shapes() -> None:
    """非陷阱形态不得误杀：正常采样率短夹具 / 有声样本 / 非 1s 量级静音。"""
    assert tts_mod._inspect_wav_bytes(_wav_bytes(seconds=0.2, rate=32000)) == ""
    assert tts_mod._inspect_wav_bytes(_wav_bytes(seconds=1.0, rate=16000, amplitude=3000)) == ""
    assert tts_mod._inspect_wav_bytes(_wav_bytes(seconds=0.2, rate=16000)) == ""
    # T90 补锁（T81 m5a）：32000Hz+恰 1s+全零——与上方 16000Hz 正例（
    # test_engine_silence_trap_detected_by_inspector）对表，单列钉死指纹①的
    # 采样率维度：rate 合取被删时，本行与正例一组必红。
    assert tts_mod._inspect_wav_bytes(_wav_bytes(seconds=1.0, rate=32000)) == ""


def test_silence_trap_synthesis_fails_without_disk_or_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def _fake(**_kwargs: object) -> tuple[bytes, str]:
        calls.append(1)
        return _wav_bytes(seconds=1.0, rate=16000), ""

    monkeypatch.setattr(tts_mod, "_request_tts", _fake)
    out = tmp_path / "out"
    ref = _ref(tmp_path)
    path1, reason1 = synthesize(
        api_url=_API, text="正文", ref=ref, params=_params(), output_dir=out
    )
    assert path1 is None and "静音" in reason1, "静音=失败：不出站"
    assert not out.exists() or not list(out.glob("*.wav")), "静音产物不得落盘"
    assert tts_mod._lookup_cache(
        tts_mod._cache_key("正文", ref, _params(), api_url=_API,
                           preset_id="shorekeeper", identity_version=tts_presets.IDENTITY_VERSION)
    ) is None, "静音产物不得入缓存"
    # 不入缓存 ⇒ 第二次同句仍会真重试（毒件绝不复放）。
    path2, _r2 = synthesize(api_url=_API, text="正文", ref=ref, params=_params(), output_dir=out)
    assert path2 is None
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# M-43：第二缺省族删除，preset=唯一缺省源
# ---------------------------------------------------------------------------


def test_module_level_second_default_constants_are_gone() -> None:
    for name in (
        "_DEFAULT_MAX_CHARS",
        "_DEFAULT_SPEED_FACTOR",
        "_DEFAULT_TEMPERATURE",
        "_DEFAULT_TOP_K",
        "_DEFAULT_TOP_P",
        "_DEFAULT_TEXT_LANG",
        "_DEFAULT_SPLIT_METHOD",
    ):
        assert not hasattr(tts_mod, name), f"{name} 是 M-43 第二真值来源，必须删除"


def test_build_params_reads_config_single_source() -> None:
    assert tts_mod._build_params(_config()) == _params()


def test_build_params_falls_back_to_preset_for_missing_keys() -> None:
    """键缺失（鸭子配置）回预设表——第二真值删除后的正确兜底。"""
    config = _config()
    for stale in ("bot_tts_speed_factor", "bot_tts_temperature", "bot_tts_top_k"):
        delattr(config, stale)
    assert tts_mod._build_params(config) == _params()


def test_build_params_casefolds_text_lang() -> None:
    assert tts_mod._build_params(_config(bot_tts_text_lang="ZH")).text_lang == "zh"


# ---------------------------------------------------------------------------
# M-72/U-25：seed 确定性派生 + 请求体换线
# ---------------------------------------------------------------------------


def test_derived_seed_is_deterministic_and_stable() -> None:
    ref_a = RefAudio(path="/tmp/x.wav", text="你好", lang="zh")
    seed1 = tts_mod.derive_seed("正文", ref_a, _params(), api_url=_API, preset_id="shorekeeper")
    seed2 = tts_mod.derive_seed("正文", ref_a, _params(), api_url=_API, preset_id="shorekeeper")
    other = tts_mod.derive_seed("别的正文", ref_a, _params(), api_url=_API, preset_id="shorekeeper")
    assert seed1 == seed2
    assert seed1 != other
    assert 0 <= seed1 < 2**32


def test_request_payload_carries_preset_values_and_derived_seed() -> None:
    """出门层换线：8 硬编码收编自预设表，seed 派生（不再 -1），text_lang casefold。"""
    payload = tts_mod._build_request_payload(
        "正文",
        RefAudio(path="/tmp/x.wav", text="你好", lang="zh"),
        _params(),
        engine_params=tts_presets.PRESET_REGISTRY["shorekeeper"].params,
        seed=123456789,
    )
    assert payload["seed"] == 123456789
    assert payload["batch_size"] == 1
    assert payload["batch_threshold"] == 0.75
    assert payload["split_bucket"] is False
    assert payload["fragment_interval"] == 0.3
    assert payload["repetition_penalty"] == 1.35
    assert payload["media_type"] == "wav"
    assert payload["streaming_mode"] is False
    assert payload["parallel_infer"] is True
    assert payload["text_lang"] == "zh"


def test_payload_seed_defaults_to_cache_derivation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：synthesize 内部派生 seed 并进请求体（旧硬编码 -1 死亡）。"""
    seen: dict[str, object] = {}

    def _fake_request(**kwargs: object) -> tuple[bytes, str]:
        seen.update(kwargs)
        return _wav_bytes(seconds=0.2), ""

    monkeypatch.setattr(tts_mod, "_request_tts", _fake_request)
    path, reason = synthesize(
        api_url=_API, text="正文", ref=_ref(tmp_path), params=_params(),
        output_dir=tmp_path / "out",
    )
    assert path is not None and reason == ""
    seed = seen.get("seed")
    assert isinstance(seed, int) and seed != -1, "seed 必须 cache_key 派生（M-72）"
    assert seed == tts_mod.derive_seed(
        "正文", _ref(tmp_path), _params(), api_url=_API, preset_id="shorekeeper"
    )


def test_capability_audit_tags_record_preset_and_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    config.bot_tts_ref_audios = [f"{tmp_path / 'ref.wav'}|你好|zh"]
    (tmp_path / "ref.wav").write_bytes(b"RIFF....WAVEfmt ")
    monkeypatch.setattr(
        tts_mod,
        "synthesize",
        lambda **_k: _write_wav(tmp_path),
    )
    result = build_tts_capability(config)(_msg("说 今天的潮汐很安静"), None)
    assert result.audio
    assert "preset=shorekeeper" in result.audit_tags
    assert any(tag.startswith("seed=") for tag in result.audit_tags)


def _write_wav(tmp_path: Path) -> tuple[Path, str]:
    target = tmp_path / "out.wav"
    target.write_bytes(_wav_bytes())
    return target, ""


# ---------------------------------------------------------------------------
# 缓存键收编 preset 身份 + identity_version（T54 §5）
# ---------------------------------------------------------------------------


def test_cache_key_changes_with_preset_identity(tmp_path: Path) -> None:
    ref = _ref(tmp_path)
    key_shore = tts_mod._cache_key("正文", ref, _params(), api_url=_API,
                                  preset_id="shorekeeper", identity_version=2)
    key_other = tts_mod._cache_key("正文", ref, _params(), api_url=_API,
                                   preset_id="other", identity_version=2)
    assert key_shore != key_other, "预设身份必须参与缓存键"


def test_cache_key_generation_bump_cold_entire_key_space(tmp_path: Path) -> None:
    ref = _ref(tmp_path)
    key_v2 = tts_mod._cache_key("正文", ref, _params(), api_url=_API,
                                preset_id="shorekeeper", identity_version=2)
    key_v3 = tts_mod._cache_key("正文", ref, _params(), api_url=_API,
                                preset_id="shorekeeper", identity_version=3)
    assert key_v2 != key_v3, "identity_version 换代必须让旧键空间整体变冷"


def test_synthesize_uses_current_preset_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端到端：能力路径出的键含 preset 段（换预设=换键=真重合成）。"""
    from plugins.bot_unified_runtime.domains.media.tts_presets import TtsPreset

    variant = TtsPreset(
        preset_id="variant",
        params={**tts_presets.PRESET_REGISTRY["shorekeeper"].params, "top_k": 25},
    )
    monkeypatch.setitem(tts_presets.PRESET_REGISTRY, "variant", variant)
    config = _config()
    config.bot_tts_ref_audios = [f"{tmp_path / 'ref.wav'}|你好|zh"]
    (tmp_path / "ref.wav").write_bytes(b"RIFF....WAVEfmt ")
    seen: list[dict[str, object]] = []

    def _fake_synth(**kwargs: object) -> tuple[Path, str]:
        seen.append(kwargs)
        target = tmp_path / f"out{len(seen)}.wav"
        target.write_bytes(_wav_bytes())
        return target, ""

    monkeypatch.setattr(tts_mod, "synthesize", _fake_synth)
    capability = build_tts_capability(config)
    capability(_msg("说 第一句"), None)
    config.bot_tts_preset = "variant"
    capability(_msg("说 第一句"), None)
    assert len(seen) == 2
    assert seen[0].get("preset_id") == "shorekeeper"
    assert seen[1].get("preset_id") == "variant", "换预设必须换 preset_id 出门"


def test_unknown_preset_id_falls_back_to_default() -> None:
    """未知 id（鸭子配置绕过装载期校验）回缺省预设——诚实兜底不炸链。"""
    config = _config(bot_tts_preset="no-such")
    assert tts_mod._resolve_preset(config).preset_id == "shorekeeper"


# ---------------------------------------------------------------------------
# U-04：data/tts_output 顺接中央配额（缺省关=字节级不变）
# ---------------------------------------------------------------------------


def test_quota_enforced_after_write_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def _fake_quota(directory: object, *, max_bytes: int = 0, max_age_days: int = 0) -> dict[str, int]:
        seen["dir"] = directory
        seen["max_bytes"] = max_bytes
        seen["max_age_days"] = max_age_days
        return {"files_removed": 0, "bytes_removed": 0}

    monkeypatch.setattr(tts_mod, "enforce_quota", _fake_quota)
    monkeypatch.setattr(tts_mod, "_request_tts", lambda **_k: (_wav_bytes(seconds=0.2), ""))
    path, reason = synthesize(
        api_url=_API, text="正文", ref=_ref(tmp_path), params=_params(),
        output_dir=tmp_path / "out", quota_max_bytes=1024, quota_max_age_days=7,
    )
    assert path is not None and reason == ""
    assert seen["max_bytes"] == 1024 and seen["max_age_days"] == 7


def test_quota_off_by_default_is_no_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_quota(*_a: object, **_k: object) -> dict[str, int]:
        raise AssertionError("配额缺省关（0/0）不得触达 enforce_quota")

    monkeypatch.setattr(tts_mod, "enforce_quota", _fail_quota)
    monkeypatch.setattr(tts_mod, "_request_tts", lambda **_k: (_wav_bytes(seconds=0.2), ""))
    path, reason = synthesize(
        api_url=_API, text="正文", ref=_ref(tmp_path), params=_params(),
        output_dir=tmp_path / "out",
    )
    assert path is not None and reason == ""


# ---------------------------------------------------------------------------
# T56 反审转发三项
# ---------------------------------------------------------------------------


def test_policy_unavailable_attaches_issue_for_alerting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """P1-1：政策件异常/配置坏 ≠ 有意拦截——必须挂 issue 走 300s 抑制告警。"""
    def _boom(*_a: object, **_k: object) -> bool:
        raise RuntimeError("名单库打不开")

    monkeypatch.setattr(tts_mod, "explicit_allowed_for_session", _boom)
    config = _config()
    config.bot_tts_ref_audios = [f"{tmp_path / 'ref.wav'}|你好|zh"]
    (tmp_path / "ref.wav").write_bytes(b"RIFF....WAVEfmt ")
    result = build_tts_capability(config)(_msg("说 你好"), None)
    assert result.operational_issue is not None, "政策件异常必须留痕告警"
    assert result.audit_tags  # blocked_by_policy 仍在


def test_intentional_policy_block_does_not_spawn_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """有意拦截（政策拒绝）不挂 issue 防刷屏。"""
    verdict = SimpleNamespace(action="block", category="minors")
    monkeypatch.setattr(tts_mod, "assess_public_content", lambda *_a, **_k: verdict)
    monkeypatch.setattr(
        tts_mod, "explicit_allowed_for_session", lambda *_a, **_k: False
    )
    config = _config()
    config.bot_tts_ref_audios = [f"{tmp_path / 'ref.wav'}|你好|zh"]
    (tmp_path / "ref.wav").write_bytes(b"RIFF....WAVEfmt ")
    result = build_tts_capability(config)(_msg("说 你好"), None)
    assert not result.audio
    assert result.operational_issue is None, "有意拦截不得刷 issue"


def test_local_path_placeholder_second_form_is_readable() -> None:
    """T56 P2-②：`<本机路径已隐藏>`（含尖括号被清洗吃掉的残缺形态）要替换成可读词。"""
    config = _config()
    for raw in ("看 C:/secret/key.pem 就是 <本机路径已隐藏> 的那个",
                "路径 <本机路径已隐藏 后面的内容"):
        speech, blocked = resolve_speech_text(config, _msg("说 x"), raw)
        assert blocked == ""
        assert "本机路径已隐藏" not in speech, f"占位符残形不得入声：{speech}"
        assert "已隐去" in speech


def test_failure_kind_table_every_entry_has_mapping() -> None:
    """T56 P2-③：_FAILURE_KINDS 每个 kind 都必须有真映射用例（含两处曾漏登的）。"""
    message = _msg("说 x")
    for prefix, kind, retryable in tts_mod._FAILURE_KINDS:
        issue = tts_mod._failure_issue(message, f"{prefix}：细节")
        assert issue.kind == kind, f"前缀「{prefix}」必须映射 {kind}"
        assert issue.retryable is retryable


# ---------------------------------------------------------------------------
# 读法词典机制（M-77 占位，v1 空表零行为变更）
# ---------------------------------------------------------------------------


def test_lexicon_mechanism_applies_substitution() -> None:
    # T75：_apply_lexicon 返回 (文本, 命中数)——命中数进 M-14 机读审计。
    assert tts_mod._apply_lexicon("守岸人真棒", {"守岸人": "守 岸 人"}) == ("守 岸 人真棒", 1)
    assert tts_mod._apply_lexicon("普通文本", {}) == ("普通文本", 0)
