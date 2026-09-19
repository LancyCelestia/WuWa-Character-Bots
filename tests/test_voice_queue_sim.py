"""T65 语音队列仿真器自身单测（全绿基线，不含 Wave H RED 行为锁）。

只验证仿真器机械件（tests/helpers/voice_queue_sim.py）：
- 假 bot 台账记录与快照不可变性、脚本逐调用回放；
- 行为注入生效：failed dict retcode / ActionFailed(.info) / 断连异常 / 超时；
- 重试计数经泵驱动可观察；tmp SQLite 隔离与重开持久。

mixed/chunks 请求在此仅作**既有绿的语义载体**（对照
tests/test_part_idempotent_resume.py 家族）；Wave H 的 RED 行为用例
（report-T55.md §五 R1-R8）由 H 波施工席以 RED 形式另写，不入本文件。

离线运行：

    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
      tests/test_voice_queue_sim.py -q -p no:cacheprovider \
      --basetemp="../ChatBot_Runtime/cache/t65"
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from helpers.voice_queue_sim import (
    DEFAULT_STEP_SECONDS,
    FakeActionFailed,
    SimulatedOneBotBot,
    build_chunks_request,
    build_mixed_request,
    build_sqlite_queue,
    dispatch_count,
    freeze_inline_retries,
    issue_kind,
    make_failing_transport,
    make_transport,
    queue_row,
    read_queue_row,
    record_files,
    run_queue_rounds,
    sent_texts,
    unknown_part_indexes,
)

from plugins.bot_unified_runtime.contracts import ReceiptState, SessionType
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    send_onebot_v11,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    PART_STATE_PENDING,
    PART_STATE_SENT,
    PART_STATE_UNKNOWN,
)

# ==================== 假 bot：台账记录与快照 ====================


@pytest.mark.asyncio
async def test_bot_ledger_records_mixed_dispatch_snapshot(tmp_path) -> None:
    """mixed 成功路径：单次 dispatch、段序与 file 引用入台账、快照防改。

    T100 翻正注（M-38 闭合）：原用例以不存在的绝对路径当 record 引用、
    依赖旧「死路径原样透传」契约；闭合后死引用不出站，故改落**真 wav
    字节**（存活绝对路径→resolve 出站）——用例意图（台账快照）不变，
    且与生产形态一致（TTS 产物恒为刚写好的真实文件）。
    """
    bot = SimulatedOneBotBot()
    wav = tmp_path / "voice.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    voice = str(wav.resolve())
    request = build_mixed_request(
        "sim-ledger", text="早上好", record_file=voice
    )
    receipt = await send_onebot_v11(bot, request, timeout_seconds=1.0)

    assert receipt.state is ReceiptState.SENT
    assert dispatch_count(bot) == 1
    call = bot.calls[0]
    assert call.method == "send_private_msg"
    assert call.target_id == "user-1"
    assert call.segments[0] == {"type": "text", "data": {"text": "早上好"}}
    assert call.segments[1] == {"type": "record", "data": {"file": voice}}
    assert sent_texts(bot) == ["早上好"]
    assert record_files(bot) == [voice]

    # 台账快照保真：调用方复用/改写同一 segment dict 再发，历史条目不变。
    reused: list[dict[str, Any]] = [{"type": "text", "data": {"text": "v1"}}]
    await bot.send_private_msg(user_id="user-1", message=reused)
    reused[0]["data"]["text"] = "v2"
    await bot.send_private_msg(user_id="user-1", message=reused)
    assert bot.calls[1].segments[0]["data"]["text"] == "v1"
    assert bot.calls[2].segments[0]["data"]["text"] == "v2"
    assert bot.calls[0].segments[0]["data"]["text"] == "早上好"


@pytest.mark.asyncio
async def test_record_only_builder_models_say_command_shape(tmp_path) -> None:
    """「说 X」形态（单 record、无 text part）：构造器出段正确、成功单发。

    T100 翻正注（M-38 闭合）：同上改落真 wav 字节——死引用单 record 的
    「诚实终败」新契约由 tests/test_tts_outbound_chain.py::
    test_say_x_dead_record_fails_final_without_dispatch 锁定，本例专守
    存活语音的正常单发形态。
    """
    bot = SimulatedOneBotBot()
    wav = tmp_path / "say.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    voice = str(wav.resolve())
    request = build_mixed_request("sim-say", record_file=voice)
    receipt = await send_onebot_v11(bot, request, timeout_seconds=1.0)

    assert receipt.state is ReceiptState.SENT
    assert dispatch_count(bot) == 1
    assert record_files(bot) == [voice]
    assert sent_texts(bot) == []


@pytest.mark.asyncio
async def test_group_target_routes_to_group_msg() -> None:
    """群目标：走 send_group_msg，target_id 经 coerce（纯数字转 int）。"""
    bot = SimulatedOneBotBot()
    request = build_mixed_request(
        "sim-group",
        text="群播",
        target_scope=SessionType.GROUP,
        target_id="1108838060",
    )
    receipt = await send_onebot_v11(bot, request, timeout_seconds=1.0)

    assert receipt.state is ReceiptState.SENT
    assert bot.calls[0].method == "send_group_msg"
    assert bot.calls[0].target_id == 1108838060


# ==================== 行为注入逐形态生效 ====================


@pytest.mark.asyncio
async def test_script_replays_in_order_until_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """脚本逐调用回放：ok → failed dict(retcode=100) 后脚本耗尽回落兜底。"""
    freeze_inline_retries(monkeypatch)
    bot = SimulatedOneBotBot(behavior="ok", script=["ok", ("retcode", 100)])
    request = build_chunks_request("sim-script", ["一", "二", "三"])

    receipt = await send_onebot_v11(bot, request, timeout_seconds=1.0)

    # 第 2 段被 failed dict 拒绝（首段已送达 ⇒ 既有 result_unknown 终态语义），
    # 第 3 段不再触达；脚本耗尽回落兜底 behavior 的路数由 dispatch 数钉住。
    assert dispatch_count(bot) == 2
    assert bot.calls[0].segments[0]["data"]["text"] == "一"
    assert bot.calls[1].segments[0]["data"]["text"] == "二"
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert issue_kind(receipt) == "result_unknown"


@pytest.mark.asyncio
async def test_action_failed_exception_is_platform_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ActionFailed 形态（retcode 藏 .info）：平台明确拒绝，白名单码终态化。"""
    freeze_inline_retries(monkeypatch)
    bot = SimulatedOneBotBot(script=[("action_failed", 403)])
    request = build_chunks_request("sim-action-failed", ["单段"])

    receipt = await send_onebot_v11(bot, request, timeout_seconds=1.0)

    assert dispatch_count(bot) == 1  # 拒绝不内联重试（既有风暴根修语义）
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert issue_kind(receipt) == "retcode_failure"
    assert FakeActionFailed(1400).info["retcode"] == 1400  # R3/R4 注入形态自证


@pytest.mark.asyncio
async def test_connection_raise_exhausts_inline_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """断连/网络类异常（无 .info）：内联 3 次尝试后 FAILED_RETRYABLE。"""
    freeze_inline_retries(monkeypatch, (0.0, 0.0))  # 保 3 次、清 sleep
    bot = SimulatedOneBotBot(behavior="raise")
    request = build_chunks_request("sim-raise", ["单段"])

    receipt = await send_onebot_v11(bot, request, timeout_seconds=1.0)

    assert dispatch_count(bot) == 3
    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert issue_kind(receipt) == "send_exception"


@pytest.mark.asyncio
async def test_timeout_injection_hands_back_timeout_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超时注入：外层 wait_for 裁决，零送达 → timeout_zero_part_delivered。"""
    freeze_inline_retries(monkeypatch)
    bot = SimulatedOneBotBot(script=[("timeout", 0.5)])
    request = build_chunks_request("sim-timeout", ["单段"])

    receipt = await send_onebot_v11(
        bot, request, timeout_seconds=0.05  # 毫秒级仿真 15s 传输预算
    )

    assert dispatch_count(bot) == 1  # 超时不内联重试
    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert issue_kind(receipt) == "timeout_zero_part_delivered"


@pytest.mark.asyncio
async def test_custom_exception_instance_passthrough() -> None:
    """('raise', 异常实例)：注入任意异常类型（Wave H 模拟 NetworkError 用）。"""
    bot = SimulatedOneBotBot(script=[("raise", ConnectionResetError("reset"))])
    with pytest.raises(ConnectionResetError):
        # 不经 send_onebot_v11（其会把异常收敛为回执）：直接打 bot 协议面，
        # 验证注入通道本身保真。
        await bot.send_private_msg(
            user_id="user-1",
            message=[{"type": "text", "data": {"text": "单段"}}],
        )
    assert dispatch_count(bot) == 1  # 异常路径同样入台账


# ==================== 泵驱动与队列观测 ====================


@pytest.mark.asyncio
async def test_pump_rounds_make_retry_count_observable(tmp_path) -> None:
    """泵逐轮显式步进：行 retry_count 逐轮累加、预算烧尽转 FAILED_FINAL。"""
    queue = build_sqlite_queue(tmp_path, name="pump.sqlite3", max_attempts=3)
    base_now = datetime.now(timezone.utc)
    request = build_chunks_request("sim-pump", ["一段", "二段"])
    queue.submit(request, now=base_now)

    transport = make_failing_transport()
    results = await run_queue_rounds(
        queue, transport, rounds=2, base_now=base_now
    )
    assert all(result.retryable_failed == 1 for result in results)
    row = queue_row(queue, "sim-pump")
    assert row["state"] == "failed_retryable"
    assert row["retry_count"] == 2

    await run_queue_rounds(
        queue,
        transport,
        rounds=1,
        base_now=base_now,
        start_offset_seconds=120.0 + 2 * 120.0,
    )
    row = queue_row(queue, "sim-pump")
    assert row["state"] == "failed_final"
    assert row["retry_count"] == 3  # max_attempts=3 烧尽
    summary = queue.safe_summary()
    assert summary["sent"] == 0 and summary["failed_final"] == 1


@pytest.mark.asyncio
async def test_pump_drives_real_transport_happy_path(tmp_path) -> None:
    """泵 + 真身传输 + 假 bot 全链：chunks 3 段一轮全 SENT、part 行落库。"""
    queue = build_sqlite_queue(tmp_path, name="happy.sqlite3")
    bot = SimulatedOneBotBot()
    base_now = datetime.now(timezone.utc)
    queue.submit(
        build_chunks_request("sim-happy", ["甲", "乙", "丙"]), now=base_now
    )

    results = await run_queue_rounds(
        queue,
        make_transport(bot, timeout_seconds=1.0),
        rounds=1,
        base_now=base_now,
    )

    assert results[0].delivered == 1
    assert results[0].parts_delivered == 3
    assert sent_texts(bot) == ["甲", "乙", "丙"]
    progress = queue.part_progress("sim-happy")
    assert progress is not None
    assert {i: r.state for i, r in progress.records.items()} == {
        0: PART_STATE_SENT,
        1: PART_STATE_SENT,
        2: PART_STATE_SENT,
    }
    assert queue_row(queue, "sim-happy")["state"] == "sent"


def test_part_state_seed_and_read_roundtrip(tmp_path) -> None:
    """UNKNOWN 播种/读取通道（R1 转绿判据「part 行=UNKNOWN」的观测面）。"""
    queue = build_sqlite_queue(tmp_path, name="seed.sqlite3")
    base_now = datetime.now(timezone.utc)
    digests = [f"digest-{i}" for i in range(2)]
    request = build_chunks_request("sim-seed", ["一", "二"])
    queue.submit(request, now=base_now)
    queue.ensure_parts_planned("sim-seed", digests, now=base_now)
    assert queue.mark_part_unknown("sim-seed", 1, now=base_now)

    assert unknown_part_indexes(queue, "sim-seed") == [1]
    progress = queue.part_progress("sim-seed")
    assert progress is not None
    assert progress.records[0].state == PART_STATE_PENDING
    assert progress.records[1].state == PART_STATE_UNKNOWN
    row = read_queue_row(queue.db_path, "sim-seed")
    assert row["parts_progress"] == '{"0":"pending","1":"unknown"}'


# ==================== tmp SQLite 隔离与树卫生 ====================


def test_tmp_sqlite_queues_are_isolated_and_reopenable(tmp_path) -> None:
    """异名隔离：各自落 tmp_path、重开实例读回同一行、跨库请求不可见。"""
    queue_a = build_sqlite_queue(tmp_path, name="a.sqlite3")
    queue_b = build_sqlite_queue(tmp_path, name="b.sqlite3")
    base_now = datetime.now(timezone.utc)
    queue_a.submit(build_mixed_request("sim-iso-a", text="A"), now=base_now)
    queue_b.submit(build_mixed_request("sim-iso-b", text="B"), now=base_now)

    assert (tmp_path / "a.sqlite3").exists() and (tmp_path / "b.sqlite3").exists()
    assert (tmp_path / "a.sqlite3").is_relative_to(tmp_path)
    assert queue_a.safe_summary()["queued"] == 1
    assert queue_b.safe_summary()["queued"] == 1

    reopened = build_sqlite_queue(tmp_path, name="a.sqlite3")
    assert read_queue_row(reopened.db_path, "sim-iso-a")["state"] == "queued"
    with pytest.raises(LookupError):
        read_queue_row(reopened.db_path, "sim-iso-b")  # 隔离：B 请求不在 A 库


def test_step_constant_covers_grace_and_partial_backoff() -> None:
    """步进缺省覆盖内联宽限（60s）与 PARTIAL 补偿退避（90s）的文档锁。"""
    assert DEFAULT_STEP_SECONDS >= 90.0


def test_explicit_now_never_depends_on_wall_clock(tmp_path) -> None:
    """队列接受显式 now：提交时刻可冻结，行为按显式时间确定性排布。"""
    queue = build_sqlite_queue(tmp_path, name="clock.sqlite3")
    frozen = datetime(2026, 9, 20, tzinfo=timezone.utc)
    queue.submit(build_chunks_request("sim-clock", ["定"]), now=frozen)

    row = read_queue_row(queue.db_path, "sim-clock")
    assert datetime.fromisoformat(str(row["next_retry_at"])) >= frozen + timedelta(
        seconds=60
    )
