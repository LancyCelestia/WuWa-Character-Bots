"""SUBDELIVERY-1（ATK-SUB-1 端到端收口）——逐目的地台账在今天是「有形状、没生产」。

域半已随 `de39afc` 落：调度器能消费 `[(key, ok), ...]` 形状并逐目的地写台账；
但生产投递腿（根 `__init__.py::_deliver_v2_event`）今天交回单个 bool，且每轮
都对**全体启用目的地**再投一遍——部分失败时台账一行不写，已成功群最多再收
`_OUTBOX_MAX_ATTEMPTS` 轮（现值以机器册/代码常量为准，本文不手写计数）。

三腿（两态预期见各腿 docstring；补丁全文＝
`.superpowers/sdd/2026-09-27-fullload/patches/SUBDELIVERY-1.patch.md`）：

- ①HEAD 红 / scheduler 腿落地后绿：声明 `only_destination_keys` 形参的投递实现
  必须每轮只拿到「尚无成功台账」的子集——已记账目的地绝不再次经手；
- ②HEAD 绿 / 落地后绿（向后兼容腿）：旧单参 bool 实现照常单参调用，行为不变
  （在飞根件的过渡形态就是这条，不许瞬断）；
- ③AST 根锁（待 root 批，落前红/落后绿）：根 `_deliver_v2_event` 声明
  `only_destination_keys` 形参且体内调 `record_outbox_deliveries_async`。
  根件禁 import（装配副作用），只看盘上文本。

全部离线：tmp_path 真实 store、零网络、零 NoneBot、零 config。
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    ContentReference,
    SubscriptionDestinationV2,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_scheduler import (
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
    SubscriptionStoreV2,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

_NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _fixture(tmp_path: Path) -> tuple[SubscriptionStoreV2, str, list[str]]:
    """一个目标＋两枚启用目的地＋一条 outbox 事件；目的地键取库内真身（行主键）。"""
    store = SubscriptionStoreV2(str(tmp_path / "subs.sqlite3"))
    target = SubscriptionTarget(
        id="t:channel:1",
        platform="t",
        target_kind="channel",
        target_key="1",
        baseline_initialized=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    store.upsert_target(target)
    for slot in ("one", "two"):
        store.add_destination(
            SubscriptionDestinationV2(
                target_id=target.id,
                transport="onebot",
                scope="group",
                destination_id=f"g-{slot}",
                enabled=True,
            )
        )
    keys = [d.id for d in store.list_destinations(target.id) if d.enabled]
    assert len(keys) == 2, f"目的地行没建起来（{keys}）＝夹具失效"
    events = store.save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id="v1", item_kind="video", url="https://x/v1")]
        ),
        baseline=False,
    )
    assert len(events) == 1, "事件没生成＝夹具失效"
    return store, events[0].event_id, keys


def _run(store: SubscriptionStoreV2, delivery_fn: Any, now: datetime | None = None) -> datetime:
    """一轮投递；回传「下一轮」的钟点（拨过 retry 退避窗，保证第二轮真被 claim）。

    事件 `next_attempt_at` 由 store 用真钟写入 ⇒ 第一轮钟点必须 ≥ 真实当下。"""
    now = now or datetime.now(timezone.utc)
    scheduler = SubscriptionScheduler(store, [], delivery_fn=delivery_fn, clock=lambda: now)
    asyncio.run(scheduler.deliver_outbox_once())
    return now + timedelta(seconds=120)


def test_pending_subset_passed_to_pending_aware_delivery(tmp_path: Path) -> None:
    """①（HEAD 红→绿）已记账的目的地，第二轮绝不再次进入投递经手清单。

    形态＝修后根腿的调度器侧镜像：逐目的地结果交回、第二目的地恒失败。
    HEAD 上调度器不认识 `only_destination_keys`（单参调用），投递腿只能全体重投
    ⇒ calls[1] 含第一目的地＝双发旁路在案；补丁件落地后 calls[1] 只剩失败者。
    """
    store, event_id, keys = _fixture(tmp_path)
    first_key, failing_key = keys
    calls: list[list[str]] = []

    async def delivery(event: Any, *, only_destination_keys: list[str] | None = None) -> Any:
        scope = (
            list(only_destination_keys)
            if only_destination_keys is not None
            else [d.id for d in store.list_destinations(event.target_id) if d.enabled]
        )
        calls.append(scope)
        return [(key, key != failing_key) for key in scope]

    now = _run(store, delivery)  # 第一轮：first 成功、failing 失败 → retry
    assert calls[0] == [first_key, failing_key]
    assert store.outbox_state(event_id) == "retry"
    assert store.outbox_undelivered_destinations(event_id, keys) == [failing_key], (
        "第一轮成功台账就没写＝de39afc 域半回退，先修域半再谈根腿"
    )
    _run(store, delivery, now)  # 第二轮：只应把还没送到的那枚交下去
    assert calls[1] == [failing_key], (
        f"已成功目的地在第二轮再次被全体投递经手（双发旁路）：{calls}"
    )
    assert store.outbox_state(event_id) == "sent"


def test_legacy_bool_delivery_keeps_single_arg_call(tmp_path: Path) -> None:
    """②（HEAD 绿→绿）向后兼容腿：旧单参实现不得被新契约瞬断。

    在飞根件今天正是这枚形状（收 outcomes、回 bool）。scheduler 腿落地后
    本行为须逐字不变：照样单参调用、照样每轮全体投递（双发要收口得等根腿，
    诚实记账在案，不为凑绿放宽断言）。
    """
    store, event_id, keys = _fixture(tmp_path)
    calls: list[int] = []

    async def legacy(event: Any) -> bool:
        calls.append(len([d for d in store.list_destinations(event.target_id) if d.enabled]))
        return False  # 永远失败：模拟离线 bot / 平台拒发

    now = _run(store, legacy)
    _run(store, legacy, now)
    assert calls == [2, 2]
    assert store.outbox_state(event_id) == "retry"
    assert store.outbox_undelivered_destinations(event_id, keys) == keys, (
        "bool 形态下整事件零台账是既定语义；根腿（③）不改这条"
    )


def _root_delivery_fn() -> ast.AsyncFunctionDef:
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_deliver_v2_event"
        ),
        None,
    )
    assert fn is not None, "根文件里找不到 _deliver_v2_event＝锚点已漂，本锁失明"
    return fn


def test_root_delivery_declares_pending_param_and_writes_ledger() -> None:
    """③AST 根锁（**待 root 批**：SUBDELIVERY-1 根腿全文见 patch md 第三节）。

    修前红（HEAD 与在飞根件均无 `only_destination_keys` 形参、无逐目的地落账）；
    修后绿。与 `test_bool_return_contract.py` 的 `-> bool` 标注锁共存：根腿保持
    bool 契约，逐目的地记账由投递腿自己经 store 异步门面完成。
    """
    fn = _root_delivery_fn()
    argnames = {arg.arg for arg in (*fn.args.args, *fn.args.kwonlyargs)}
    assert "only_destination_keys" in argnames, (
        "根投递腿还没接「待投子集」形参＝部分失败双发在生产仍开敞（ATK-SUB-1 根半）"
    )
    called = {
        node.func.attr
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "record_outbox_deliveries_async" in called, (
        "根投递腿未逐目的地落台账：bool 形态下成功目的地永远没有账"
    )
