"""群摘要白/黑名单参与过滤回归（Task 1）。

名单键 BOT_GROUP_DIGEST_LIST_MODE/WHITELIST/BLACKLIST 此前只写入
运行时 store、代码零消费（死配置）。本文件锁定消费点
``build_shared_group_context_provider`` 的五态语义：

1. 白名单命中 → 参与摘要注入；
2. 白名单未命中 → 跳过（enabled=False）；
3. 黑名单命中 → 跳过；
4. 模式空/off/all/未知 → 不过滤（完全向后兼容）；
5. 全局开关关闭 → 名单无意义，行为与改动前一致。

另覆盖 int/str 群号混型的字符串化归一（配置侧 int、会话侧 str）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from plugins.bot_unified_runtime.character.shared_group import (
    NullSharedGroupContextProvider,
    build_shared_group_context_provider,
)
from plugins.bot_unified_runtime.config import Config

_LISTED_GROUP = "1108838060"  # 与简报示例一致的真实群号（store 侧曾为 int）


def _make_history_db(tmp_path: Path, group_id: str = _LISTED_GROUP) -> str:
    """建一个含群会话公共投影的最小 SQLite 历史（含 kind 列）。

    两个群各有一轮对话：``group_id`` 与名单外对照群 "999"，使
    "黑名单未误伤名单外群"可被真实数据证明。

    键形态用生产写侧实况 ``group_<群号>_<发送者>``（NoneBot
    get_session_id 群形态；F4 席根修同步——旧夹具 ``group:<群号>``
    是被测 bug 的死形态，生产 0 行，见 tests/test_shared_group_key_alignment.py）。
    """
    db_path = tmp_path / "history.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE conversation_turns (
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                kind TEXT
            )
            """
        )
        rows: list[tuple[str, str, str, str, str]] = []
        for gid, text in ((group_id, "早上好"), ("999", "对照组发言")):
            rows.append((f"group_{gid}_1001", "user", text, "2026-09-11T08:00:00", "chat"))
            rows.append((f"group_{gid}_1001", "assistant", "早", "2026-09-11T08:01:00", "chat"))
        connection.executemany(
            "INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?)", rows
        )
    return str(db_path)


def _build_provider(db_path: str, **config_overrides: object):
    payload: dict[str, object] = {
        "bot_shared_group_context_enabled": True,
        "bot_history_db_path": db_path,
    }
    payload.update(config_overrides)
    return build_shared_group_context_provider(Config(**payload))


def test_whitelist_hit_participates(tmp_path: Path) -> None:
    """白名单命中参与：配置侧 int 群号、会话侧 str，字符串化归一后命中。"""
    provider = _build_provider(
        _make_history_db(tmp_path),
        bot_group_digest_list_mode="whitelist",
        bot_group_digest_whitelist=[1108838060],  # int 混型
    )

    context = provider.load(
        request_id="req-1", group_id=_LISTED_GROUP, sender_id="user-1"
    )

    assert context.enabled is True
    assert "早上好" in context.summary


def test_whitelist_miss_skipped(tmp_path: Path) -> None:
    """白名单未命中跳过：名单外群不参与摘要注入。"""
    provider = _build_provider(
        _make_history_db(tmp_path),
        bot_group_digest_list_mode="whitelist",
        bot_group_digest_whitelist=["999"],
    )

    context = provider.load(
        request_id="req-1", group_id=_LISTED_GROUP, sender_id="user-1"
    )

    assert context.enabled is False
    assert context.summary == ""


def test_blacklist_hit_skipped_and_miss_participates(tmp_path: Path) -> None:
    """黑名单命中跳过；同一模式下名单外群仍正常参与。"""
    provider = _build_provider(
        _make_history_db(tmp_path),
        bot_group_digest_list_mode="blacklist",
        bot_group_digest_blacklist=[_LISTED_GROUP],
    )

    listed = provider.load(
        request_id="req-1", group_id=_LISTED_GROUP, sender_id="user-1"
    )
    unlisted = provider.load(
        request_id="req-2", group_id="999", sender_id="user-1"
    )

    assert listed.enabled is False
    assert listed.summary == ""
    # 名单外群有历史且未被黑名单误伤 → 正常参与。
    assert unlisted.enabled is True
    assert "对照组发言" in unlisted.summary


def test_mode_empty_off_all_or_unknown_no_filtering(tmp_path: Path) -> None:
    """模式空/off/all/未知均不过滤（向后兼容：名单不改变既有行为）。"""
    db_path = _make_history_db(tmp_path)
    for mode in ("", "off", "all", "bogus-mode"):
        provider = _build_provider(
            db_path,
            bot_group_digest_list_mode=mode,
            bot_group_digest_whitelist=["999"],
            bot_group_digest_blacklist=[_LISTED_GROUP],
        )

        context = provider.load(
            request_id="req-1", group_id=_LISTED_GROUP, sender_id="user-1"
        )

        assert context.enabled is True, f"mode={mode!r} 不应过滤"
        assert "早上好" in context.summary


def test_global_switch_off_ignores_list(tmp_path: Path) -> None:
    """全局开关关闭：行为与改动前一致（Null provider，名单无意义）。"""
    provider = _build_provider(
        _make_history_db(tmp_path),
        bot_shared_group_context_enabled=False,
        bot_group_digest_list_mode="whitelist",
        bot_group_digest_whitelist=[_LISTED_GROUP],
    )

    assert isinstance(provider, NullSharedGroupContextProvider)
    context = provider.load(
        request_id="req-1", group_id=_LISTED_GROUP, sender_id="user-1"
    )

    assert context.enabled is False
