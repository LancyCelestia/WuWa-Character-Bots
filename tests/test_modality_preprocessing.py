"""#51 多模态接货腿（modality_preprocessing）离线回归。

纪律：全 mock、零网络、零 ffmpeg。只验证「纯决策 + 委托 handler 的诚实退让 +
作业表四态幂等 + 动态开关读不写死 + 记忆沉淀走总线单一真身」。
原生部件构造走真实的 ``build_native_audio_part`` / ``build_native_video_part``
（纯读本地字节、无网络），故允许喂临时文件。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.vision.capabilities import (
    modality_preprocessing as mp,
)
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    InvocationStatus,
    _gate_feature_id,
)

_WAV_BYTES = b"RIFF" + b"\x00" * 40


# ---------------------------------------------------------------- 纯决策函数


def test_preprocess_pure_and_deterministic() -> None:
    inp = mp.ModalityInput(
        kind="audio", is_local=True, suffix=".wav", native_supported=True, size_bytes=1000
    )
    first = mp.preprocess_for_modality(inp)
    second = mp.preprocess_for_modality(inp)
    assert first == second  # frozen dataclass 等值：纯函数无副作用
    assert first.route == mp.ROUTE_NATIVE
    assert first.uses_native is True


def test_preprocess_audio_native_vs_transcode() -> None:
    native = mp.preprocess_for_modality(
        mp.ModalityInput(
            kind="audio", is_local=True, suffix=".mp3", native_supported=True, size_bytes=10
        )
    )
    assert native.route == mp.ROUTE_NATIVE
    assert native.native_part_type == "input_audio"
    assert native.metadata["audio_format"] == "mp3"

    # 非本机 → 回落 ASR 转写（不二次实现，交给 transcribe 真身）
    fallback = mp.preprocess_for_modality(
        mp.ModalityInput(
            kind="audio", is_local=False, suffix=".mp3", native_supported=True, size_bytes=10
        )
    )
    assert fallback.route == mp.ROUTE_TRANSCODE
    assert fallback.steps == ("asr_transcribe",)

    # 未声明原生 → 即便本机也走转写（缺省不放行的声明式门）
    undeclared = mp.preprocess_for_modality(
        mp.ModalityInput(kind="audio", is_local=True, suffix=".mp3", native_supported=False)
    )
    assert undeclared.route == mp.ROUTE_TRANSCODE


def test_preprocess_video_native_vs_frame_extract() -> None:
    native = mp.preprocess_for_modality(
        mp.ModalityInput(
            kind="video", is_local=True, suffix=".mp4", native_supported=True, size_bytes=10
        )
    )
    assert native.route == mp.ROUTE_NATIVE
    assert native.native_part_type == "video_url"

    big = mp.preprocess_for_modality(
        mp.ModalityInput(
            kind="video",
            is_local=True,
            suffix=".mp4",
            native_supported=True,
            size_bytes=99_000_000,
            max_mb=20.0,
        )
    )
    assert big.route == mp.ROUTE_FRAME_EXTRACT
    assert big.steps == ("frame_extract", "vlm_brief")


def test_preprocess_image_uses_vision_leg_not_generation() -> None:
    plain = mp.preprocess_for_modality(mp.ModalityInput(kind="image"))
    assert plain.capability_id == mp.CAP_IMAGE_UPSCALE
    assert plain.route == mp.ROUTE_PLAIN
    # 明确不落在图像生成那条路上（两条不同路，红线）
    assert "generate" not in plain.capability_id

    upscale = mp.preprocess_for_modality(mp.ModalityInput(kind="image", want_upscale=True))
    assert upscale.route == mp.ROUTE_UPSCALE
    assert "upscale" in upscale.steps


def test_preprocess_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        mp.ModalityInput(kind="hologram")


# ---------------------------------------------------------------- 描述符


def test_descriptors_creation_family_and_real_targets() -> None:
    specs = {s.capability_id: s for s in mp.modality_capability_specs()}
    assert set(specs) == {
        mp.CAP_AUDIO_TRANSCRIBE,
        mp.CAP_VIDEO_UNDERSTAND,
        mp.CAP_IMAGE_UPSCALE,
    }
    for spec in specs.values():
        assert spec.family == "creation"
        assert spec.capability_id.startswith("creation.")
    # implementation_ref 指既有真身，不指本模块的第二实现
    assert specs[mp.CAP_AUDIO_TRANSCRIBE].implementation_ref.endswith("transcribe.py#transcribe_audio")
    assert specs[mp.CAP_VIDEO_UNDERSTAND].implementation_ref.endswith(
        "video_understanding.py#build_video_brief"
    )
    assert specs[mp.CAP_IMAGE_UPSCALE].implementation_ref.endswith("vision_describe.py#describe_images")
    # 图像走视觉、绝不落生成
    assert "generate" not in specs[mp.CAP_IMAGE_UPSCALE].implementation_ref


# ---------------------------------------------------------------- 委托 handler


def test_handle_audio_native_builds_part_from_local_bytes(tmp_path) -> None:
    wav = tmp_path / "voice.wav"
    wav.write_bytes(_WAV_BYTES)
    plan = mp.preprocess_for_modality(
        mp.ModalityInput(
            kind="audio", is_local=True, suffix=".wav", native_supported=True, size_bytes=len(_WAV_BYTES)
        )
    )
    result = mp.handle_audio_transcribe(str(wav), plan=plan)
    assert result.status is InvocationStatus.OK
    assert result.data["native_part"]["type"] == "input_audio"


def test_handle_audio_transcode_without_provider_is_unavailable() -> None:
    plan = mp.preprocess_for_modality(mp.ModalityInput(kind="audio", is_local=False, suffix=".mp3"))
    result = mp.handle_audio_transcribe("https://x.test/a.mp3", plan=plan, asr_provider=None)
    assert result.status is InvocationStatus.UNAVAILABLE
    assert result.detail  # 非成功态必带诚实说明


def test_handle_image_without_urls_or_provider_is_unavailable() -> None:
    plan = mp.preprocess_for_modality(mp.ModalityInput(kind="image"))
    assert mp.handle_image_upscale([], plan=plan, vision_provider=None).status is (
        InvocationStatus.UNAVAILABLE
    )
    assert mp.handle_image_upscale(["http://x/a.jpg"], plan=plan, vision_provider=None).status is (
        InvocationStatus.UNAVAILABLE
    )


# ---------------------------------------------------------------- 动态开关读


def test_gate_feature_id_matches_central_single_source() -> None:
    # 本席换算必须与唯一表 _gate_feature_id 逐字等价（不建第二张表、零漂移）
    assert mp.derive_gate_feature_id(mp.CAP_AUDIO_INPUT) == _gate_feature_id(mp.CAP_AUDIO_INPUT)
    assert mp.GATE_AUDIO_INPUT == "bot.plugin.audio_input"
    assert mp.GATE_VIDEO_UNDERSTANDING == "bot.plugin.video_understanding"


def test_feature_gate_enabled_settings_first_and_never_hardcoded() -> None:
    calls: list[tuple[str, bool]] = []

    def _settings(key: str, default: bool) -> bool:
        calls.append((key, default))
        return key == "BOT_AUDIO_INPUT_ENABLED"

    assert mp.feature_gate_enabled("bot.audio_input", settings_get=_settings, default=False) is True
    assert mp.feature_gate_enabled("bot.video_understanding", settings_get=_settings, default=False) is False
    assert ("BOT_AUDIO_INPUT_ENABLED", False) in calls

    # 无 settings 通道 → 回退 config 属性；都没有 → 用调用方 default，绝不写死 True
    cfg = SimpleNamespace(bot_audio_input_enabled=True)
    assert mp.feature_gate_enabled("bot.audio_input", config=cfg, default=False) is True
    assert mp.feature_gate_enabled("bot.audio_input", default=False) is False
    assert mp.feature_gate_enabled("bot.audio_input", default=True) is True


# ---------------------------------------------------------------- 作业表


def test_job_store_enqueue_idempotent_and_session_key(tmp_path) -> None:
    store = mp.ModalityPreprocessJobStore(str(tmp_path / "mpj.sqlite3"))
    plan = mp.preprocess_for_modality(
        mp.ModalityInput(kind="audio", is_local=True, suffix=".wav", native_supported=True)
    )
    key = store.enqueue(job_id="job-1", plan=plan, group_id="777", user_id="888", source_ref="file://a.wav")
    assert key == "group_777_888"  # 会话键走 session_keys，不自行拼接
    # 同 job_id 再入队不新增行（幂等）
    store.enqueue(job_id="job-1", plan=plan, group_id="777", user_id="888")
    rows = store.recent_jobs(key)
    assert len(rows) == 1
    assert rows[0]["status"] == "queued"
    assert rows[0]["capability_id"] == mp.CAP_AUDIO_TRANSCRIBE


def test_job_store_marks_honest_four_states(tmp_path) -> None:
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        InvocationResult,
    )

    store = mp.ModalityPreprocessJobStore(str(tmp_path / "mpj.sqlite3"))
    plan = mp.preprocess_for_modality(mp.ModalityInput(kind="video"))
    store.enqueue(job_id="v1", plan=plan, session_key="42")

    store.mark_result(
        "v1",
        InvocationResult(capability_id=mp.CAP_VIDEO_UNDERSTAND, status=InvocationStatus.UNAVAILABLE, detail="no provider"),
    )
    assert store.recent_jobs("42")[0]["status"] == "unavailable"

    store.mark_result(
        "v1",
        InvocationResult(capability_id=mp.CAP_VIDEO_UNDERSTAND, status=InvocationStatus.FAILED, detail="boom"),
    )
    assert store.recent_jobs("42")[0]["status"] == "failed"

    store.mark_result(
        "v1",
        InvocationResult(
            capability_id=mp.CAP_VIDEO_UNDERSTAND,
            status=InvocationStatus.OK,
            data={"brief_text": "画面里是猫"},
        ),
    )
    done = store.recent_jobs("42")[0]
    assert done["status"] == "done"
    assert done["summary"] == "画面里是猫"


# ---------------------------------------------------------------- 记忆沉淀（走总线单一真身）


def test_absent_bus_returns_none_no_second_store() -> None:
    assert mp.absorb_preprocessed_summary(None, owner_id="1", subject_user_id="1", session_id="group_1_1", summary="x") is None
    captured: dict[str, object] = {}

    def _absorb(**kwargs):
        captured.update(kwargs)
        return "absorbed"

    bus = SimpleNamespace(absorb=_absorb)
    out = mp.absorb_preprocessed_summary(
        bus, owner_id="9", subject_user_id="9", session_id="group_5_9", summary="用户发了一段视频，画面是猫"
    )
    assert out == "absorbed"
    assert captured["provenance"] == "derived"
    assert captured["source"] == "modality_preprocess"
    assert captured["session_id"] == "group_5_9"
    # 空摘要不写
    assert mp.absorb_preprocessed_summary(bus, owner_id="9", subject_user_id="9", session_id="g", summary="  ") is None
