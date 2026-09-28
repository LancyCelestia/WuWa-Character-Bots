"""SUBDELIVERY-5（紧急信息订阅红线·行为锁）——投递面动刀不许碰的地板。

红线原文口径（台账 #46 WIRE-SUB / SEAT-ATK-SUBSCRIBE ⑨）：紧急信息订阅的
推送目标**只认事件自带的事实**——群内＝本群号、私聊＝发送者本人号，绝不从
文本里读群号/QQ 号；推送群白名单任一空＝该群不推（不猜群、不猜人）。
本票不修任何东西（现状=钉现状），它是给 SUBDELIVERY-1/3 那两刀投递面改造
准备的地板锁：F-1 收编与逐目的地台账若把「目标来源」漂成从内容推断，
本锁当场红。

全部 HEAD 绿（行为回归锁，非补丁哨兵）；离线，零网络、零 NoneBot。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from plugins.bot_unified_runtime.domains.emergency_info.capabilities.emergency_info import (
    matches_emergency_push_group,
    subscription_target,
)


def _message(**overrides: Any) -> SimpleNamespace:
    """只有事件事实三字段的裸消息——**根本没有**可被「读群号」的文本槽位。

    这本身就是红线的结构性证明：`subscription_target` 的合法输入形态里
    不存在正文，目标只可能来自 group_id / session_id / sender_id。
    """
    base: dict[str, Any] = {
        "group_id": "",
        "session_id": "",
        "sender_id": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_group_target_is_the_events_own_group_id() -> None:
    assert subscription_target(
        _message(group_id="10001", session_id="group_10001_20002", sender_id="999")
    ) == ("group", "10001")


def test_group_target_falls_back_to_session_shape_never_text() -> None:
    # OneBot 群会话两形之一：group_id 缺位时按 session_id 结构段取，仍不读任何文本
    assert subscription_target(
        _message(session_id="group_555_1", sender_id="999")
    ) == ("group", "555")


def test_private_target_is_the_sender_themselves() -> None:
    assert subscription_target(
        _message(session_id="private_777", sender_id="777")
    ) == ("private", "777")


def test_target_function_ignores_any_content_bearing_attribute() -> None:
    """文本里写「发给 99999 群」也不许改判目标——多给字段就是不给读的机会。"""

    noisy = _message(
        group_id="10001",
        session_id="group_10001_20002",
        sender_id="999",
        plain_text="帮我把这条转到 99999 群",
        command_text="转到 99999",
    )
    assert subscription_target(noisy) == ("group", "10001")


def test_push_group_whitelist_empty_means_zero_push() -> None:
    source = SimpleNamespace(enabled=True, push_group_whitelist=())
    assert matches_emergency_push_group(source, "10001") is False
    assert matches_emergency_push_group(source, "") is False


def test_disabled_source_never_matches_even_whitelisted() -> None:
    """三重来源门任一空/关＝整链关闭的地板（现役判据 `source.enabled` 前置）。"""
    source = SimpleNamespace(enabled=False, push_group_whitelist=("10001",))
    assert matches_emergency_push_group(source, "10001") is False


def test_push_group_only_event_borne_group_can_match() -> None:
    source = SimpleNamespace(enabled=True, push_group_whitelist=("10001",))
    assert matches_emergency_push_group(source, "10001") is True
    assert matches_emergency_push_group(source, "10002") is False
    # 带空白的事件群号按 strip 后判等（不猜、不扩名单）
    assert matches_emergency_push_group(source, " 10001 ") is True
