"""语音出站链路回归：``CapabilityResult.audio`` → 渲染 mixed 部件 → OneBot record 段。

守岸人语音合成（bot.tts）出站靠的是**既有**通道，本次未改 renderer / sender
任何一行。但此前测试树里 ``audio=[...]`` 一次都没出现过——这条链路完全没有
覆盖，等于"靠约定活着"。本文件把它钉死。

链路（三段，逐段断言）：

1. ``render_reviewed_output``：``result.audio`` → ``content_type="mixed"``，
   ``content_ref["parts"]`` 内为 ``{"type": "record", "file": <路径>}``。
2. ``_mixed_segments``：``{"type":"record"}`` → ``{"type":"record","data":{"file": ...}}``。
3. ``_resolve_local_file_ref``：本地存在的文件解析成绝对路径；``file://`` 等
   引用原样透传。

另外锁死一条**能力层约定**：发媒体时必须把 ``title``/``body`` 留空，否则
renderer 的 ``body → summary → title`` 兜底链会把标题当文案一起发出去。
"""

from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    ReviewResult,
)
from plugins.bot_unified_runtime.output.renderer import render_reviewed_output
from plugins.bot_unified_runtime.sender.onebot import (
    _mixed_segments,
    _resolve_local_file_ref,
    _segment_from_mixed_part,
)


def _review() -> ReviewResult:
    return ReviewResult(request_id="rev-1", approved=True)


def _wav(tmp_path: Path, name: str = "synth.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(b"RIFF....WAVEfmt ")
    return path


def _render(result: CapabilityResult):
    return render_reviewed_output(result, _review())


# ---------------------------------------------------------------------------
# 第 1 段：能力结果 → 渲染部件
# ---------------------------------------------------------------------------


def test_audio_only_result_renders_mixed_with_record_part(tmp_path: Path) -> None:
    wav = _wav(tmp_path)
    result = CapabilityResult(
        request_id="req-1",
        capability_id="bot.tts",
        kind="text",
        title="",
        body="",
        audio=[{"file": str(wav)}],
    )
    rendered = _render(result)
    assert rendered.content_type == "mixed"
    assert rendered.content_ref["parts"] == [{"type": "record", "file": str(wav)}]
    # title/body 留空时不应混入 text 部件。
    assert all(part["type"] != "text" for part in rendered.content_ref["parts"])


def test_audio_part_type_defaults_to_record_and_is_overridable(tmp_path: Path) -> None:
    wav = _wav(tmp_path)
    default = _render(
        CapabilityResult(
            request_id="r1", capability_id="bot.tts", kind="text",
            audio=[{"file": str(wav)}],
        )
    )
    assert default.content_ref["parts"][0]["type"] == "record"

    explicit = _render(
        CapabilityResult(
            request_id="r2", capability_id="bot.tts", kind="text",
            audio=[{"type": "voice", "file": str(wav)}],
        )
    )
    # M-19 收口（T80）：type="voice" 归一为 record——OneBot V11 语音段标准类型，
    # SnowLuma 对未知段类型整条拒发（report-T46 §2.2）。
    assert explicit.content_ref["parts"][0]["type"] == "record"


def test_audio_part_without_file_or_url_is_dropped(tmp_path: Path) -> None:
    """空部件必须被丢弃——否则 sender 会造出一个没有 file 的 record 段。"""
    rendered = _render(
        CapabilityResult(
            request_id="req-1", capability_id="bot.tts", kind="text",
            audio=[{"note": "no file here"}],
        )
    )
    assert rendered.content_type == "text"
    assert rendered.content_ref.get("parts") is None


def test_body_present_adds_text_part_after_audio(tmp_path: Path) -> None:
    """反证 title/body 为何必须留空：一旦有正文，它会成为后续的 text 部件。"""
    wav = _wav(tmp_path)
    rendered = _render(
        CapabilityResult(
            request_id="req-1", capability_id="bot.tts", kind="text",
            body="这是一段会被念出来的说明文字",
            audio=[{"file": str(wav)}],
        )
    )
    parts = rendered.content_ref["parts"]
    assert parts[0] == {"type": "record", "file": str(wav)}
    assert parts[-1]["type"] == "text"
    assert "说明文字" in parts[-1]["text"]


def test_auto_reply_shape_is_record_then_text(tmp_path: Path) -> None:
    """对话自动配音的真实形态：人格正文 + 附加语音 → 先语音后文字。"""
    wav = _wav(tmp_path)
    rendered = _render(
        CapabilityResult(
            request_id="req-1",
            capability_id="bot.chat",
            kind="text",
            body="今天的潮汐很安静。",
            audio=[{"file": str(wav)}],
        )
    )
    parts = rendered.content_ref["parts"]
    assert [part["type"] for part in parts] == ["record", "text"]
    assert parts[0]["file"] == str(wav)


# ---------------------------------------------------------------------------
# 第 2 段：渲染部件 → OneBot 段
# ---------------------------------------------------------------------------


def test_record_part_becomes_onebot_record_segment(tmp_path: Path) -> None:
    wav = _wav(tmp_path)
    segments = _mixed_segments(
        {"parts": [{"type": "record", "file": str(wav)}]}, text_fallback=""
    )
    assert segments == [{"type": "record", "data": {"file": str(wav.resolve())}}]


def test_record_part_accepts_url_as_fallback(tmp_path: Path) -> None:
    segments = _mixed_segments(
        {"parts": [{"type": "record", "url": "https://example.com/a.silk"}]},
        text_fallback="",
    )
    assert segments == [
        {"type": "record", "data": {"file": "https://example.com/a.silk"}}
    ]


def test_record_part_without_ref_is_skipped() -> None:
    segments = _mixed_segments({"parts": [{"type": "record"}]}, text_fallback="兜底文案")
    # 段全被跳过时回退纯文本，绝不发一个空 record。
    assert segments == [{"type": "text", "data": {"text": "兜底文案"}}]


def test_mixed_segments_falls_back_when_parts_missing() -> None:
    assert _mixed_segments({}, text_fallback="兜底") == [
        {"type": "text", "data": {"text": "兜底"}}
    ]


# ---------------------------------------------------------------------------
# 第 3 段：路径解析
# ---------------------------------------------------------------------------


def test_local_existing_file_resolves_to_absolute(tmp_path: Path) -> None:
    wav = _wav(tmp_path)
    assert _resolve_local_file_ref(str(wav)) == str(wav.resolve())


def test_passthrough_refs_are_untouched() -> None:
    for ref in (
        "https://example.com/a.wav",
        "http://example.com/a.wav",
        "file:///C:/x/a.wav",
        "base64://AAAA",
        "data:audio/wav;base64,AAAA",
    ):
        assert _resolve_local_file_ref(ref) == ref


def test_missing_local_path_is_returned_as_is(tmp_path: Path) -> None:
    missing = str(tmp_path / "not_there.wav")
    assert _resolve_local_file_ref(missing) == missing


def test_empty_ref_is_returned_as_is() -> None:
    assert _resolve_local_file_ref("") == ""


# ---------------------------------------------------------------------------
# 端到端：一次真实的 bot.tts 结果走完三段
# ---------------------------------------------------------------------------


def test_tts_result_reaches_onebot_record_end_to_end(tmp_path: Path) -> None:
    wav = _wav(tmp_path, "tts_output.wav")
    result = CapabilityResult(
        request_id="req-e2e",
        capability_id="bot.tts",
        kind="text",
        title="",
        body="",
        audio=[{"file": str(wav)}],
    )

    rendered = _render(result)
    assert rendered.content_type == "mixed"

    segments = _mixed_segments(
        rendered.content_ref, text_fallback=rendered.text_fallback
    )
    assert segments == [{"type": "record", "data": {"file": str(wav.resolve())}}]
    # 纯语音出站：不应混入任何 text 段。
    assert all(segment["type"] == "record" for segment in segments)


def test_segment_from_mixed_part_returns_none_for_unknown_type() -> None:
    assert _segment_from_mixed_part({"type": "unknown_kind", "file": "x"}) is None
