"""SUB-1（S-ATK-SUBSCRIBE）：唯一构造口必须把 config 四键与 dead_letter_sink 传进 store。

旧实况：`build_subscription_runtime_v2` 裸 `SubscriptionStoreV2(db_path)` ⇒
①四枚 `bot_subscription_*` 键写了也不生效（D2：config=None 全回退模块常量）、
②死信只有 WARNING 一行、管理员通道永空（文档却写成活的）。J-03 注释点名
「接线属装配层职责」——本锁就是将那句兑现；根装配现场向 build 传 sink 的
一行另走 §待主代理落盘（root 管控面）。
"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import OperationalIssue
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_runtime_v2 import (
    build_subscription_runtime_v2,
)


def _config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_subscribe_db_path=str(tmp_path / "subs.sqlite3"),
        bot_subscription_outbox_max_attempts=2,
        bot_subscription_outbox_sent_retention_days=14,
        bot_subscription_seen_retention_days=90,
        bot_subscription_outbox_sending_stale_seconds=300.0,
    )


def test_build_passes_config_and_sink_into_store(tmp_path) -> None:
    captured: list[OperationalIssue] = []
    runtime = build_subscription_runtime_v2(
        _config(tmp_path),
        context_factory=lambda platform: {},
        dead_letter_sink=captured.append,
    )
    store = runtime["store"]
    assert store._outbox_max_attempts == 2, "config 四键没传进构造口（D2 假活）"
    # `list.append` 每次取都是新绑定方法对象，`is` 判永假——真打一发才算数。
    issue = OperationalIssue(
        stage="subscribe", kind="subscription_outbox_dead", retryable=False,
        safe_summary="probe",
    )
    store._dead_letter_sink(issue)
    assert captured == [issue], "sink 接了但不通气（非同一列表？）"


def test_sink_defaults_none_for_legacy_callers(tmp_path) -> None:
    runtime = build_subscription_runtime_v2(
        _config(tmp_path), context_factory=lambda platform: {}
    )
    assert runtime["store"]._dead_letter_sink is None
