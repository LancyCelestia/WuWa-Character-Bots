from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.subscribe.capabilities.subscribe_v2 import (
    build_subscribe_capability_v2,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_runtime_v2 import (
    build_subscription_runtime_v2,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
    SubscriptionStoreV2,
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


def _group_message(text: str, *, platform: str, sender_id: str) -> IncomingMessage:
    return IncomingMessage(
        platform=platform,
        adapter="telegram" if platform == "telegram" else "onebot.v11",
        bot_id="bot",
        session_id=f"group:{sender_id}",
        session_type=SessionType.GROUP,
        sender_id=sender_id,
        group_id="-1001234567890",
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
    # 重审计 R10：pause/resume 按目的地粒度生效（对齐 v1），不再翻转 target。
    assert runtime["store"].list_destinations(target_id)[0].enabled is False

    resumed = capability(_message(f"订阅 resume {target_id}"), None)
    assert "已恢复" in resumed.body
    assert runtime["store"].list_destinations(target_id)[0].enabled is True

    removed = capability(_message(f"订阅 remove {target_id}"), None)
    assert "已删除" in removed.body
    assert runtime["store"].get_target(target_id) is None
    runtime["store"].close()


# ==================== F-A 残留：群内 add 管理门的平台域判定 ====================


def test_v2_group_gate_denies_telegram_same_number_as_qq_admin(tmp_path) -> None:
    """病根锁：QQ 管理员号 "admin" 的用户在 telegram 平台群内 add，不得再被
    无平台腿的裸名单直判放行（F-A 残留旁路点，subscribe_v2.py _is_admin）。"""
    config = _config(str(tmp_path / "subscriptions.sqlite3"))
    capability = build_subscribe_capability_v2(
        store=SubscriptionStoreV2(str(tmp_path / "gate.sqlite3")), adapters=[], config=config
    )
    result = capability(
        _group_message(
            "订阅 add https://www.youtube.com/channel/UC1",
            platform="telegram",
            sender_id="admin",
        ),
        None,
    )
    assert "subscribe_add_denied" in result.audit_tags, (
        f"TG 同号仍吃到 QQ 裸名单 admin：{result.audit_tags} / {result.body}"
    )


def test_v2_group_gate_still_allows_qq_admin_bare_number(tmp_path) -> None:
    """零回归正向锁：QQ 平台（onebot 写法）裸号管理员照旧过群管理门
    （门开后因 adapters=[] 停在解析，而非停在权限）。"""
    config = _config(str(tmp_path / "subscriptions.sqlite3"))
    capability = build_subscribe_capability_v2(
        store=SubscriptionStoreV2(str(tmp_path / "gate2.sqlite3")), adapters=[], config=config
    )
    result = capability(
        _group_message(
            "订阅 add https://www.youtube.com/channel/UC1",
            platform="onebot",
            sender_id="admin",
        ),
        None,
    )
    assert "subscribe_add_denied" not in result.audit_tags
    assert "subscribe_target_invalid" in result.audit_tags
