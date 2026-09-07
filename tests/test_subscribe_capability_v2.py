from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.subscribe_v2 import (
    build_subscribe_capability_v2,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.sources.subscription_runtime_v2 import (
    build_subscription_runtime_v2,
)


def _config(db_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        bot_subscribe_db_path=db_path,
        bot_subscribe_global_concurrency=2,
        bot_subscribe_platform_concurrency=1,
        bot_subscribe_min_interval_seconds=0,
        bot_subscribe_lease_seconds=30,
        bot_subscribe_retry_base_seconds=1,
        bot_subscribe_retry_cap_seconds=10,
        bot_admin_user_ids=["admin"],
    )


def _message(text: str, *, sender_id: str = "admin") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=f"private:{sender_id}",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
    )


def test_v2_subscribe_add_list_pause_resume_remove(tmp_path) -> None:
    config = _config(str(tmp_path / "subscriptions.sqlite3"))
    runtime = build_subscription_runtime_v2(config)
    capability = build_subscribe_capability_v2(
        store=runtime["store"], adapters=runtime["adapters"], config=config
    )

    added = capability(_message("订阅 add https://www.youtube.com/channel/UC1"), None)
    assert "订阅已添加" in added.body
    target_id = "youtube:channel:UC1"
    assert runtime["store"].get_target(target_id) is not None
    assert runtime["store"].list_destinations(target_id)[0].destination_id == "admin"

    listed = capability(_message("订阅 list"), None)
    assert target_id in listed.body

    paused = capability(_message(f"订阅 pause {target_id}"), None)
    assert "已暂停" in paused.body
    assert runtime["store"].get_target(target_id).enabled is False

    resumed = capability(_message(f"订阅 resume {target_id}"), None)
    assert "已恢复" in resumed.body
    assert runtime["store"].get_target(target_id).enabled is True

    removed = capability(_message(f"订阅 remove {target_id}"), None)
    assert "已删除" in removed.body
    assert runtime["store"].get_target(target_id) is None
    runtime["store"].close()
