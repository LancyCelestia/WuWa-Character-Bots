"""提醒投递死路回归（审查 A-01）。

默认配置是内存发送队列——``InMemorySendQueue.submit`` 只入列并回假 sent
回执、没有任何网络调用；旧实现 submit 后立刻 ``mark_done``，提醒必然
无声消失。本文件锁定新契约：

1. submit 后必须就地内联投递，transport 返回 SENT/REDIRECTED 才销账；
2. 投递失败 / 无在线 bot 不销账，提醒保持 due 待下一轮重投；
3. 回执仓显示 worker 已送达时直接销账，不再内联重发（防双发）；
4. 调度器注册的是异步任务且带上回执仓与在线 bot 取数闭包。
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime as pkg
from plugins.bot_unified_runtime import (
    _deliver_due_reminders,
    _register_reminder_scheduler,
)
from plugins.bot_unified_runtime.contracts import DeliveryReceipt, ReceiptState
from plugins.bot_unified_runtime.domains.schedule.store import (
    reminders as reminders_mod,
)
from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
    build_outbound_gate,
)

#: 真身中央出站闸（缺省关闭=直通，与生产缺省同态）：投递出口已收进中央，
#: 这两条生产线必须有闸可用；用 None 假装没闸＝测的已经不是生产形态。
_GATE = build_outbound_gate(SimpleNamespace())


class _CountingStore:
    """闸的滑窗 store 假面：计数永远超限，且**绝不落盘**（不碰 data/ 边界）。"""

    def count_sends(self, subject_key, *, since_utc):
        return 9_999

    def record_send(self, subject_key, *, now_utc):
        return None

    def prune(self, *, before_utc):
        return 0


class _AllowingStore:
    """开态但绝不拦的滑窗 store：计数恒 0，且**绝不落盘**（不碰 data/ 边界）。"""

    def count_sends(self, subject_key, *, since_utc):
        return 0

    def record_send(self, subject_key, *, now_utc):
        return True

    def prune(self, *, before_utc):
        return 0


def _skip_gate():
    """开启且**拦下本轮**的真身闸（每分钟限额 1 条、滑窗计数恒超限 → 判顺延）。

    ⚠ 2026-09-22 R-CENTRAL 纠正本用例两条前提，都因原实现"因 bug 才绿"：

    1. 原先写 `max_per_target_per_minute=0`，而限流腿有 `>0` 守卫 ⇒ 限流分支根本没进，
       当时的拦下真原因是 `dedupe_key_shape`（提醒键 `reminder:` 不被只认 `emg` 前缀的
       键规范认账 = C-1）。限额改 1，拦下才真的来自限流。
    2. 限流给的是 **defer 不是 skip**：顺延态 `submit_active_push` 照旧入列、带
       `deliver_after`，由 worker 到点投（下一 tick 同 dedupe_key 被 `ON CONFLICT` 收敛，
       不双发）。所以旧断言"闸拦下 ⇒ 队列零入列"是错的，它只是在 skip-only 的 C-1 路径
       上碰巧成立。本闸唯一能给出的 skip 是键形不合法，而 `reminder_id` 由 store 生成、
       恒为合法段 ⇒ 提醒族生产上到不了 skip，别再为此造假日分支。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    return build_outbound_gate(
        SimpleNamespace(),
        settings_provider=lambda: OutboundGateSettings(
            enabled=True, max_per_target_per_minute=1, max_per_target_per_hour=6
        ),
        store=_CountingStore(),
    )


class _FakeQueue:
    def __init__(self) -> None:
        self.submitted: list[object] = []
        self.requests: dict[str, object] = {}

    def submit(self, request) -> None:
        self.submitted.append(request)
        self.requests[request.request_id] = request

    def find_request(self, request_id: str):
        return self.requests.get(request_id)


class _FakeRepo:
    def __init__(self) -> None:
        self.receipts: dict[str, DeliveryReceipt] = {}

    def latest(self, request_id: str):
        return self.receipts.get(request_id)


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[tuple[object, dict]] = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((func, kwargs))


def _receipt(state: ReceiptState) -> DeliveryReceipt:
    return DeliveryReceipt(request_id="r", state=state, transport="fake")


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(reminders_mod, "_STORES", {})
    config = SimpleNamespace(
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
        bot_persona_profile_id="default",
    )
    store = reminders_mod.build_reminder_store(config)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    reminder = store.add(
        session_key="group:1",
        sender_id="u1",
        target_scope="group",
        target_id="1",
        adapter="nonebot",
        bot_id="bot",
        remind_at=past,
        text="写作业",
    )
    return config, store, reminder


@pytest.mark.asyncio
async def test_delivers_via_transport_and_marks_done(tmp_path, monkeypatch) -> None:
    """送达（SENT）才销账：transport 被调用、提醒离开 due 队列。"""
    config, store, reminder = _setup(tmp_path, monkeypatch)
    calls: list[tuple[object, str]] = []

    async def _fake_deliver(bot, event, request, *args, **kwargs):
        calls.append((bot, request.request_id))
        return _receipt(ReceiptState.SENT)

    monkeypatch.setattr(pkg, "_deliver_transport_send_request", _fake_deliver)
    monkeypatch.setattr(pkg, "_select_queue_bot", lambda provider, request: object())

    delivered = await _deliver_due_reminders(
        config, _FakeQueue(), None, None, dict, outbound_gate=_GATE
    )

    assert delivered == 1
    assert [rid for _, rid in calls] == [f"reminder-{reminder.reminder_id}"]
    assert store.due() == []


@pytest.mark.asyncio
async def test_transport_failure_keeps_reminder_pending(tmp_path, monkeypatch) -> None:
    """投递失败（FAILED_FINAL）不销账：下一轮 due() 仍能取到重投。"""
    config, store, reminder = _setup(tmp_path, monkeypatch)

    async def _fake_deliver(bot, event, request, *args, **kwargs):
        return _receipt(ReceiptState.FAILED_FINAL)

    monkeypatch.setattr(pkg, "_deliver_transport_send_request", _fake_deliver)
    monkeypatch.setattr(pkg, "_select_queue_bot", lambda provider, request: object())

    delivered = await _deliver_due_reminders(
        config, _FakeQueue(), None, None, dict, outbound_gate=_GATE
    )

    assert delivered == 0
    assert [item.reminder_id for item in store.due()] == [reminder.reminder_id]


@pytest.mark.asyncio
async def test_central_gate_defer_neither_delivers_inline_nor_writes_off(
    tmp_path, monkeypatch
) -> None:
    """闸拦下那一轮（限流顺延）：不内联投递、不销账（A′ 的活性判据，光看"零裸 submit"不算证）。

    判据四件：本轮 `delivered=0`、内联投递零调用、提醒仍在 due() 里等收敛、
    队列里那条**带 deliver_after**（顺延交 worker 到点投＝中央出口的正解，不是丢消息）。
    """
    config, store, reminder = _setup(tmp_path, monkeypatch)
    inline_calls: list[object] = []

    async def _never_deliver(bot, event, request, *args, **kwargs):
        inline_calls.append(request)
        return _receipt(ReceiptState.SENT)

    monkeypatch.setattr(pkg, "_deliver_transport_send_request", _never_deliver)
    monkeypatch.setattr(pkg, "_select_queue_bot", lambda provider, request: object())

    queue = _FakeQueue()
    delivered = await _deliver_due_reminders(
        config, queue, None, None, dict, outbound_gate=_skip_gate()
    )

    assert delivered == 0
    assert inline_calls == [], "闸已拦下仍内联投递＝第二通路"
    assert len(queue.submitted) == 1, "顺延应入列带 deliver_after，交 worker 到点投"
    assert queue.requests, "拦下即丢消息＝中央出口做成了哑巴"
    assert [item.reminder_id for item in store.due()] == [reminder.reminder_id], (
        "被拦下却销账＝提醒无声消失"
    )


@pytest.mark.asyncio
async def test_enabled_central_gate_still_delivers_reminders(tmp_path, monkeypatch) -> None:
    """开态活性：闸**启用**后提醒必须真的还能投出去（R-CENTRAL C-1 的产线级证据）。

    只测关态等于测"闸不存在"。本波把提醒接进中央出口后，如果键规范仍只认紧急域
    `emg` 前缀，那么关态一片绿、开闸当天提醒全部静默消失且每分钟重投同一
    request_id，24 小时后被 `due(grace_hours=24)` 作废——用户收到的是"作废"不是提醒。
    这条就是那天的烟雾报警器（滑窗计数给 0，排除限流/静默窗一切其它拦因）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
        QuietHoursSettings,
    )
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGateSettings,
    )

    config, store, reminder = _setup(tmp_path, monkeypatch)
    inline_calls: list[object] = []

    async def _deliver(bot, event, request, *args, **kwargs):
        inline_calls.append(request)
        return _receipt(ReceiptState.SENT)

    monkeypatch.setattr(pkg, "_deliver_transport_send_request", _deliver)
    monkeypatch.setattr(pkg, "_select_queue_bot", lambda provider, request: object())

    gate = build_outbound_gate(
        SimpleNamespace(),
        settings_provider=lambda: OutboundGateSettings(enabled=True),
        quiet_settings_provider=lambda: QuietHoursSettings(enabled=False),
        store=_AllowingStore(),
    )
    queue = _FakeQueue()
    delivered = await _deliver_due_reminders(
        config, queue, None, None, dict, outbound_gate=gate
    )

    assert delivered == 1, "闸开态提醒被拦＝中央出口把现役投递做成了哑巴"
    assert len(queue.submitted) == 1
    assert len(inline_calls) == 1
    assert [item.reminder_id for item in store.due()] != [reminder.reminder_id], (
        "已投递却不销账＝下一轮再投一次"
    )


@pytest.mark.asyncio
async def test_no_online_bot_keeps_pending(tmp_path, monkeypatch) -> None:
    """bot 全离线：不投递也不销账，等 bot 回线后下一轮补投。"""
    config, store, reminder = _setup(tmp_path, monkeypatch)
    queue = _FakeQueue()

    delivered = await _deliver_due_reminders(
        config, queue, None, None, dict, outbound_gate=_GATE
    )

    assert delivered == 0
    assert len(queue.submitted) == 1, "仍要入列占位（SQLite 队列下 worker 可接管）"
    assert [item.reminder_id for item in store.due()] == [reminder.reminder_id]


@pytest.mark.asyncio
async def test_worker_already_sent_marks_done_without_redispatch(
    tmp_path, monkeypatch
) -> None:
    """回执仓显示 worker 已送达：直接销账，不再内联重发（防双发）。"""
    config, store, reminder = _setup(tmp_path, monkeypatch)
    queue = _FakeQueue()
    repo = _FakeRepo()
    request_id = f"reminder-{reminder.reminder_id}"
    repo.receipts[request_id] = _receipt(ReceiptState.SENT)

    async def _fail_deliver(*args, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("worker 已送达时不得再次内联投递")

    monkeypatch.setattr(pkg, "_deliver_transport_send_request", _fail_deliver)
    monkeypatch.setattr(pkg, "_select_queue_bot", lambda provider, request: object())

    delivered = await _deliver_due_reminders(
        config, queue, None, repo, dict, outbound_gate=_GATE
    )

    assert delivered == 1
    assert queue.submitted == []
    assert store.due() == []


@pytest.mark.asyncio
async def test_governance_receipt_rides_delivery_path(tmp_path, monkeypatch) -> None:
    """A-05：顺延/作废回执搭既有投递路径主动送达；真提醒保持 pending。

    错过（迟到 >30min ≤24h）的提醒被顺延不补投，但 ``due()`` 会附一句
    ``gov-`` 前缀的回执 Reminder——调度器照常内联投递它，文案原样放行
    （不被分型模板误包装），送达后的 mark_done 对回执 id 是空操作。
    """
    monkeypatch.setattr(reminders_mod, "_STORES", {})
    config = SimpleNamespace(
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
        bot_persona_profile_id="default",
    )
    store = reminders_mod.build_reminder_store(config)
    missed = datetime.now(timezone.utc) - timedelta(hours=2)  # 迟到 2h → 顺延
    reminder = store.add(
        session_key="group:1",
        sender_id="u1",
        target_scope="group",
        target_id="1",
        adapter="nonebot",
        bot_id="bot",
        remind_at=missed,
        text="写作业",
    )
    queue = _FakeQueue()
    calls: list[str] = []

    async def _fake_deliver(bot, event, request, *args, **kwargs):
        calls.append(request.request_id)
        return _receipt(ReceiptState.SENT)

    monkeypatch.setattr(pkg, "_deliver_transport_send_request", _fake_deliver)
    monkeypatch.setattr(pkg, "_select_queue_bot", lambda provider, request: object())

    delivered = await _deliver_due_reminders(
        config, queue, None, None, dict, outbound_gate=_GATE
    )

    assert delivered == 1, "本轮只送达治理回执，错过的提醒不原样补投"
    assert len(calls) == 1 and calls[0].startswith("reminder-gov-")
    receipt_request = queue.requests[calls[0]]
    fallback = receipt_request.content.text_fallback
    assert "写作业" in fallback and "你之前说过的" not in fallback
    pending = store.list_pending("group:1")
    assert [item.reminder_id for item in pending] == [reminder.reminder_id], (
        "顺延中的真提醒不得被回执销账"
    )


def test_register_scheduler_installs_async_job_with_receipt_repo(
    tmp_path, monkeypatch
) -> None:
    """注册契约：异步任务 + 回执仓/在线 bot 闭包齐备（缺失即退回死路）。"""
    config = _setup(tmp_path, monkeypatch)[0]
    scheduler = _FakeScheduler()
    repo = _FakeRepo()

    result = _register_reminder_scheduler(
        scheduler, config, _FakeQueue(), None, repo, dict, outbound_gate=_GATE
    )

    assert result == {"interval": "1m"}
    # 2026-10-03 全量修复批：注册子树同批挂了落盘点清扫作业（bot_file_sweep_tick，
    # 每 04:50 扫 incoming/）⇒ 本注册器共两作业；账随现势走，不写死枚数散文。
    assert len(scheduler.jobs) == 2
    job, kwargs = scheduler.jobs[0]
    assert inspect.iscoroutinefunction(job)
    assert kwargs["id"] == "bot_reminder_tick" and kwargs["minute"] == "*"
