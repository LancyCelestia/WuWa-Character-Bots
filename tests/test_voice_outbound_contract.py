"""出站语音部件中央契约回归（M-19①③ renderer 收口半，Wave G / T80）。

审计锚（report-T29.md M-19，P1）：出站语音部件无中央契约，三裂缝中本席收：

① ``type="voice"`` 渲染层放行、传输层丢弃（OneBot 只认 record；换装
SnowLuma 后对未知段类型更是整条拒发，report-T46 §2.2）⇒ 音频蒸发。
**修法=渲染入口把 voice 规范化为 record**（OneBot V11 语音段标准类型就是
record，voice 是能力层口误别名，不是第三种语义）+ warning 留痕。
③ ``audio`` 自由袋（``**audio`` 全键透传）可播性无表达 ⇒ 字段冻结：
``file`` 必填、``duration``/``bytes`` 可选可播性元数据（渲染期校验类型、
不上段），散键（含审查通道键 review_text/text）一律剥离留痕——审查文本
归 reviewer 在 ``CapabilityResult.audio`` 上消费，绝不进出站段
（reviewer 可见性回归 test_reviewer_media_visibility.py 的前提由此夯实）。

T78 对表锁（末节 e2e）：渲染产出 ``{"type":"record","file":<引用>}`` 唯一
形态，传输 ``record`` 分支产出 ``{"type":"record","data":{"file":…}}``，
data 白名单恰 ``{"file"}``（与 test_reviewer_media_visibility.py:126 同源）。

全离线零网络；音频字节是假 RIFF 头，非真实产物。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    ReviewResult,
)
from plugins.bot_unified_runtime.domains.render.renderer import (
    canonicalize_audio_parts,
    render_reviewed_output,
)
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    _mixed_segments,
)

_RENDERER_LOGGER = "plugins.bot_unified_runtime.domains.render.renderer"

_REVIEW = ReviewResult(request_id="rev-1", approved=True)

_FAKE_SECRET = "review_channel_probe_TESTFAKEVALUE"


def _wav(tmp_path: Path, name: str = "synth.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(b"RIFF....WAVEfmt ")
    return path


def _render(**overrides: object):
    base: dict = {
        "request_id": "req-t80",
        "capability_id": "bot.tts",
        "kind": "text",
        "title": "",
        "body": "",
    }
    base.update(overrides)
    result = CapabilityResult(**base)  # type: ignore[arg-type]
    return render_reviewed_output(result, _REVIEW)


# ---------------------------------------------------------------------------
# 裂缝①：voice 输入规范化为 record（禁静默吞 → warning 留痕）
# ---------------------------------------------------------------------------


def test_voice_typed_audio_normalizes_to_record(tmp_path: Path) -> None:
    """type="voice" 是非标别名：渲染入口必须归一为 record，不得放行。"""
    wav = _wav(tmp_path)
    rendered = _render(audio=[{"type": "voice", "file": str(wav)}])
    assert rendered.content_type == "mixed"
    assert rendered.content_ref["parts"] == [{"type": "record", "file": str(wav)}]


def test_voice_normalization_leaves_warning_trace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """归一必须留痕（禁静默吞）：anomalies 进 renderer warning 日志。"""
    wav = _wav(tmp_path)
    with caplog.at_level(logging.WARNING, logger=_RENDERER_LOGGER):
        rendered = _render(audio=[{"type": "voice", "file": str(wav)}])
    assert rendered.content_type == "mixed"
    assert any("voice" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# 裂缝③：自由袋收口——散键剥离、字段冻结、可播性元数据不上段
# ---------------------------------------------------------------------------


def test_free_bag_keys_stripped_to_canonical_record_shape(tmp_path: Path) -> None:
    """散键（审查键/冗余 url/任意杂键）一律剥离：出站 record 部件恰两键。"""
    wav = _wav(tmp_path)
    rendered = _render(
        audio=[
            {
                "file": str(wav),
                "review_text": "审查通道文本，不得外发",
                "url": "https://example.com/a.wav",
                "note": "自由袋杂键",
            }
        ]
    )
    assert rendered.content_type == "mixed"
    assert rendered.content_ref["parts"] == [{"type": "record", "file": str(wav)}]


def test_review_text_never_enters_outbound_part(tmp_path: Path) -> None:
    """审查通道文本停留在 CapabilityResult.audio，绝不混进出站部件。"""
    wav = _wav(tmp_path)
    rendered = _render(audio=[{"file": str(wav), "review_text": _FAKE_SECRET}])
    parts = rendered.content_ref["parts"]
    assert parts == [{"type": "record", "file": str(wav)}]
    assert _FAKE_SECRET not in rendered.text_fallback


def test_playability_metadata_frozen_not_wired(tmp_path: Path) -> None:
    """duration/bytes 是冻结后的可选可播性元数据：校验通过也不上出站段
    （线上表达归传输层白名单，今日 record data 恰 {file}）。"""
    wav = _wav(tmp_path)
    rendered = _render(audio=[{"file": str(wav), "duration": 3.5, "bytes": 1024}])
    assert rendered.content_ref["parts"] == [{"type": "record", "file": str(wav)}]


def test_invalid_playability_metadata_stripped_with_trace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """可播性元数据类型非法（如 duration="3s"）：剥离+留痕，部件本体保命。"""
    wav = _wav(tmp_path)
    with caplog.at_level(logging.WARNING, logger=_RENDERER_LOGGER):
        rendered = _render(audio=[{"file": str(wav), "duration": "3s"}])
    assert rendered.content_ref["parts"] == [{"type": "record", "file": str(wav)}]
    assert any("duration" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# 负样本自检：伪能力产物必须被抓（拒绝+留痕，绝不放行成蒸发段）
# ---------------------------------------------------------------------------


def test_unsupported_audio_type_rejected_with_trace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """未知类型（如 music_share）：显式拒绝，不放行到传输层蒸发。"""
    wav = _wav(tmp_path)
    with caplog.at_level(logging.WARNING, logger=_RENDERER_LOGGER):
        rendered = _render(audio=[{"type": "music_share", "file": str(wav)}])
    assert rendered.content_type == "text"
    assert rendered.content_ref.get("parts") is None
    assert any("music_share" in record.getMessage() for record in caplog.records)


def test_non_dict_audio_item_dropped_with_trace() -> None:
    """非 dict 部件：CapabilityResult.audio=list[dict] 在 pydantic 契约层已拒
    （实跑实证 ValidationError）；渲染入口函数作为独立防线同样拒绝+留痕。"""
    parts, anomalies = canonicalize_audio_parts(
        [{"file": "a.wav"}, "junk-not-a-dict"]  # type: ignore[list-item]
    )
    assert parts == [{"type": "record", "file": "a.wav"}]
    assert any("non-dict" in item for item in anomalies)


def test_contract_layer_rejects_non_dict_audio_item() -> None:
    """负样本（契约层）：伪能力往 audio 塞非 dict → pydantic 直接拒绝。"""
    with pytest.raises(ValidationError):
        CapabilityResult(
            request_id="req-t80",
            capability_id="bot.tts",
            kind="text",
            audio=[{"file": "a.wav"}, "junk-not-a-dict"],  # type: ignore[list-item]
        )


def test_record_part_without_file_rejected(tmp_path: Path) -> None:
    """无 file 的 record：拒绝（旧自由袋会造出没有 file 的空 record 段）。"""
    rendered = _render(audio=[{"note": "no file here"}])
    assert rendered.content_type == "text"
    assert rendered.content_ref.get("parts") is None


def test_non_string_file_ref_rejected(tmp_path: Path) -> None:
    """file 引用必须是非空 str（Path/None 等一律拒绝，防自由袋复辟）。"""
    rendered = _render(audio=[{"file": 12345}])
    assert rendered.content_type == "text"
    assert rendered.content_ref.get("parts") is None


# ---------------------------------------------------------------------------
# 既有形态保持（零回归锚：T61 tts.py / music.py 现行出站构造对表）
# ---------------------------------------------------------------------------


def test_tts_canonical_shape_unchanged(tmp_path: Path) -> None:
    """tts.py 现行构造 ``[{"file": str(path), "review_text": …}]`` 出站不变。"""
    wav = _wav(tmp_path)
    rendered = _render(audio=[{"file": str(wav), "review_text": "今天的潮汐很安静。"}])
    assert rendered.content_type == "mixed"
    assert rendered.content_ref["parts"] == [{"type": "record", "file": str(wav)}]


def test_music_card_part_shape_preserved(tmp_path: Path) -> None:
    """点歌 CQ:music 卡片（music.py 现行形态）保持；杂键仍被剥离。"""
    rendered = _render(
        audio=[
            {
                "type": "music",
                "music_type": "qq",
                "music_id": "30019675",
                "stray": "should-not-pass",
            }
        ]
    )
    assert rendered.content_ref["parts"] == [
        {"type": "music", "music_type": "qq", "music_id": "30019675"}
    ]


def test_music_part_without_ids_rejected(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_RENDERER_LOGGER):
        rendered = _render(audio=[{"type": "music"}])
    assert rendered.content_type == "text"
    assert caplog.records


def test_file_mode_audio_part_preserved() -> None:
    """点歌 file 模式（music.py：{"type":"file","file":<引用>}）保持。"""
    rendered = _render(audio=[{"type": "file", "file": "https://example.com/a.mp3"}])
    assert rendered.content_ref["parts"] == [
        {"type": "file", "file": "https://example.com/a.mp3"}
    ]


# ---------------------------------------------------------------------------
# canonicalize_audio_parts 单元面 + T78 对表 e2e
# ---------------------------------------------------------------------------


def test_canonicalize_returns_anomaly_list_for_voice() -> None:
    parts, anomalies = canonicalize_audio_parts([{"type": "voice", "file": "a.wav"}])
    assert parts == [{"type": "record", "file": "a.wav"}]
    assert any("voice" in item for item in anomalies)


def test_canonicalize_empty_and_none_inputs() -> None:
    assert canonicalize_audio_parts(None) == ([], [])
    assert canonicalize_audio_parts([]) == ([], [])


def test_e2e_renderer_to_onebot_record_data_whitelist(tmp_path: Path) -> None:
    """T78 对表锁：渲染唯一形态 → 传输 record 段 data 恰 {file}。"""
    wav = _wav(tmp_path)
    rendered = _render(audio=[{"file": str(wav), "review_text": _FAKE_SECRET}])
    segments = _mixed_segments(
        rendered.content_ref, text_fallback=rendered.text_fallback, request_id="req-t80"
    )
    assert segments == [{"type": "record", "data": {"file": str(wav.resolve())}}]
    assert all(set(segment["data"]) == {"file"} for segment in segments)
