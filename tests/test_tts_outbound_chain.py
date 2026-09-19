"""语音出站链路回归：``CapabilityResult.audio`` → 渲染 mixed 部件 → OneBot record 段。

守岸人语音合成（bot.tts）出站靠的是**既有**通道，本次未改 renderer / sender
任何一行。但此前测试树里 ``audio=[...]`` 一次都没出现过——这条链路完全没有
覆盖，等于"靠约定活着"。本文件把它钉死。

链路（三段，逐段断言）：

1. ``render_reviewed_output``：``result.audio`` → ``content_type="mixed"``，
   ``content_ref["parts"]`` 内为 ``{"type": "record", "file": <路径>}``。
2. ``_mixed_segments``：``{"type":"record"}`` → ``{"type":"record","data":{"file": ...}}``。
3. ``_resolve_local_file_ref``：本地存在的文件解析成绝对路径；``file://`` 等
   引用原样透传；**M-38 闭合（T100，2026-09-20）**：不存在的**绝对路径**
   （含 0 字节空文件）解析为 ``None`` ⇒ record/video/file 部件在构段期被
   跳过，绝不把死路径送上协议端（旧契约「原样透传照出站」由
   ``test_missing_local_path_is_returned_as_is`` 陷阱测试钉死，本批翻正）。
   相对路径保持既有透传（CWD 依赖的不完整引用，交平台侧裁决；T85 冻结
   棘轮 R6 毒件机制依赖此口，见 report-T100 §偏差）。混排死件跳过时其余
   部件照发、SENT 回执挂 ``missing_file`` OperationalIssue 留痕；纯语音
   （`说 X`）无文字可保 ⇒ 不派发平台、直接 FAILED_FINAL（诚实终败，
   零自拼文案）。

另外锁死一条**能力层约定**：发媒体时必须把 ``title``/``body`` 留空，否则
renderer 的 ``body → summary → title`` 兜底链会把标题当文案一起发出去。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.voice_queue_sim import (
    SimulatedOneBotBot,
    build_mixed_request,
    build_sqlite_queue,
    dispatch_count,
    freeze_inline_retries,
    make_transport,
    queue_row,
    run_queue_rounds,
    sim_utc_now,
)

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    ReceiptState,
    ReviewResult,
)
from plugins.bot_unified_runtime.output.renderer import render_reviewed_output
from plugins.bot_unified_runtime.sender.onebot import (
    _mixed_segments,
    _resolve_local_file_ref,
    _segment_from_mixed_part,
    send_onebot_v11,
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


def test_missing_absolute_local_path_resolves_to_none(tmp_path: Path) -> None:
    """M-38 闭合翻正（T100）：绝对路径死引用解析为 None ⇒ 部件被跳过不出站。

    旧契约（陷阱测试 ``test_missing_local_path_is_returned_as_is``）把
    「死路径原样透传照出站」钉成期望——NapCat 时期静默摘段谎报 SENT、
    SnowLuma 整条拒发拖垮文字部件（report-T97 M-38 残半判定）。本例锁
    新契约：不存在的绝对路径不出站。
    """
    missing = str(tmp_path / "not_there.wav")
    assert _resolve_local_file_ref(missing) is None


def test_zero_byte_local_file_is_dead(tmp_path: Path) -> None:
    """存在性+非空双门：0 字节文件（合成中断残骸）同判死引用。"""
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    assert _resolve_local_file_ref(str(empty)) is None


def test_relative_missing_path_keeps_passthrough() -> None:
    """相对路径保持既有透传（T100 闭合范围边界，report-T100 §偏差）。

    相对路径是 CWD 依赖的不完整引用；T85 冻结棘轮（test_h_voice_delivery
    R6 毒件机制）与既有毒语音形态依赖此口。本例把该边界显式钉住，防
    后续席位误以为全量死引用都已拦。
    """
    ref = "t100_no_such_relative_ref.wav"
    assert _resolve_local_file_ref(ref) == ref


def test_dead_record_part_is_skipped_text_part_survives(tmp_path: Path) -> None:
    """混排 [死 record, 文字]：死件构段期跳过，文字部件照走。"""
    dead = str(tmp_path / "gone.wav")
    segments = _mixed_segments(
        {
            "parts": [
                {"type": "record", "file": dead},
                {"type": "text", "text": "文字部件照走"},
            ]
        },
        text_fallback="",
    )
    assert segments == [{"type": "text", "data": {"text": "文字部件照走"}}]


def test_segment_from_mixed_part_dead_file_returns_none(tmp_path: Path) -> None:
    """构段单件视角：死引用 record 部件产 None（进 dropped_types 观测）。"""
    assert (
        _segment_from_mixed_part(
            {"type": "record", "file": str(tmp_path / "gone.wav")}
        )
        is None
    )


# ---------------------------------------------------------------------------
# M-38 闭合端到端：死引用不出站 + issue 留痕 + 纯语音诚实终败
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_dead_record_skipped_text_delivered_with_issue(
    tmp_path: Path,
) -> None:
    """混排 [文字, 死 record]：死件不出站、文字照发、SENT 挂 missing_file。

    与 worker W1 的衔接（report-T78 环境在本契约下的新形态）：文字不再
    依赖「死件拖垮整条 → 平台拒绝 → W1 补发」链路——它在同一次派发里
    直接送达；W1 保留给平台侧真拒绝形态。OperationalIssue kind 复用
    file_gateway 既有 ``missing_file`` 族（B3 失败分类同名）。
    """
    bot = SimulatedOneBotBot(behavior="ok")
    request = build_mixed_request(
        "t100-mixed-dead",
        text="文字部件照走",
        record_file=str(tmp_path / "gone.wav"),
    )
    receipt = await send_onebot_v11(bot, request, timeout_seconds=1.0)
    assert receipt.state is ReceiptState.SENT
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "missing_file"
    # 死 record 绝不出站：唯一派发只含文字段。
    assert len(bot.calls) == 1
    assert [seg["type"] for seg in bot.calls[0].segments] == ["text"]
    assert bot.calls[0].segments[0]["data"]["text"] == "文字部件照走"


@pytest.mark.asyncio
async def test_say_x_dead_record_fails_final_without_dispatch(
    tmp_path: Path,
) -> None:
    """诚实边界：纯语音 `说 X` 死件无文字可保 ⇒ 零派发、FAILED_FINAL。

    断言三面（不藏）：① 零平台派发（死路径绝不照出站）；② 终态失败
    （FAILED_FINAL + missing_file），不是「空文本假成功」；③ 零自拼文案
    （R-16②：传输层禁拼兜底话术，sent 段为空）。
    """
    bot = SimulatedOneBotBot(behavior="ok")
    request = build_mixed_request(
        "t100-sayx-dead",
        text=None,
        record_file=str(tmp_path / "gone.wav"),
    )
    receipt = await send_onebot_v11(bot, request, timeout_seconds=1.0)
    assert bot.calls == []  # ① 零派发
    assert receipt.state is ReceiptState.FAILED_FINAL  # ② 诚实终败
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "missing_file"
    assert bot.sent_texts == []  # ③ 零自拼文案


# ---------------------------------------------------------------------------
# M-38 闭合 × 队列路径（W1 环境衔接验证）
# ---------------------------------------------------------------------------

_QUEUE_BASE = sim_utc_now()


@pytest.mark.asyncio
async def test_queue_path_say_x_dead_record_terminal_without_textfb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """队列路径衔接验证：死件纯语音经 worker 收敛终态，零派发零降级。

    W1 环境（report-T78）衔接面：W1 文字兜底只由 worker 对平台明确拒绝
    （FAILED_FINAL ∧ kind=retcode_failure）触发；死件纯语音在 sender 门
    即 FAILED_FINAL+missing_file——既非 retcode 形态、亦无文字部件可保
    ⇒ 零 -textfb 降级尝试、零平台派发、行首收敛态终态，续轮零再认领。
    """
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    bot = SimulatedOneBotBot(behavior="ok")
    transport = make_transport(bot)
    request = build_mixed_request(
        "t100-queue-sayx",
        text=None,
        record_file=str(tmp_path / "gone.wav"),  # 不落盘=死引用
    )
    queue.submit(request, now=_QUEUE_BASE)

    results = await run_queue_rounds(queue, transport, rounds=1, base_now=_QUEUE_BASE)
    row1 = queue_row(queue, "t100-queue-sayx")

    await run_queue_rounds(queue, transport, rounds=2, base_now=_QUEUE_BASE)

    assert dispatch_count(bot) == 0  # 死路径零出站（含降级路径）
    assert bot.sent_texts == []  # R-16②：零自拼文案
    assert any(
        issue.kind == "missing_file" for issue in results[0].operational_issues
    )
    assert row1["state"] == "failed_final"  # 首轮终态，不烧重试预算
    assert queue_row(queue, "t100-queue-sayx")["state"] == "failed_final"
    assert dispatch_count(bot) == 0  # 终态行不再认领，续轮零增长


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
