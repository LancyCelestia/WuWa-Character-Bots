"""群摘要读写键一致性回归锁（F4 席：修「读写键永不相交」P1）。

背景（AGENTS.md 台账 #33 立项、审计 U1-05 端到端复现）：
写侧 conversation_turns.session_id 来自 NoneBot ``get_session_id()``
（群形态 ``group_<群号>_<发送者>``，生产库 wuwa_history.sqlite3 实测
2457 行全为此形态、``group:`` 形态 0 行）；旧读侧却按 ``group:<群号>``
等值查——两键永不相交 ⇒ 【群共享上下文】恒空、21:30 群摘要推送静默空转。

本文件锁死修复后的键口径统一（读侧按群前缀聚合，前缀与中央构造器
``session_key_from_ids`` 逐字同构），并覆盖：

1. 生产写入口落一条 → 读侧按群号一定能读到（RED→GREEN 主案）；
2. 群内多发送者聚合：三人发言 + bot 回复全部进群摘要；
3. 群间不串：他群内容不漏进；群号互为前缀（123456 vs 1234567）不误伤
   （LIKE 的 ``_`` 通配陷阱反证）；
4. 私聊裸 uid 行（键恰为群号数字）不被误当群消息聚合；
5. 跨键形态一致性反证锁：中央构造器产出的每个键都必然落在读侧前缀内；
6. 漂移死形态 ``group:<gid>`` 不再被读（防回潮）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    shared_group as shared_group_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.history import (
    SQLiteConversationHistoryRepository,
)
from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
    session_key_from_ids,
)


def _group_prefix(group_id: object) -> str:
    """读侧群前缀助手（修复落地前不存在——RED 时给出可读断言失败而非 ImportError）。"""
    prefix_fn = getattr(shared_group_module, "_group_prefix", None)
    assert callable(prefix_fn), "读侧缺少中央群前缀构造器 _group_prefix"
    return str(prefix_fn(group_id))

GROUP = "1108838060"
OTHER_GROUP = "631785829"
PREFIX_TRAP_GROUP = "123456"
PREFIX_TRAP_OTHER = "1234567"


def _write_turn(db: Path, *, session_id: str, sender_id: str, role: str, text: str) -> None:
    """走生产写入口落一条（conversation_turns 真实 schema 由仓储自建）。"""
    repository = SQLiteConversationHistoryRepository(db)
    repository.append_turn(
        request_id=f"req-{session_id}-{text[:4]}",
        platform="qq",
        adapter="onebot-v11",
        bot_id="bot-1",
        session_id=session_id,
        sender_id=sender_id,
        role=role,
        text=text,
        kind="chat",
    )


def test_write_entry_row_is_readable_by_group_id(tmp_path: Path) -> None:
    """主案：按生产写入口（get_session_id 群形态键）落库后，读侧按群号必读到。

    修复前此断言为 RED——旧读侧等值查 ``group:<gid>`` 恒空。
    """
    db = tmp_path / "history.sqlite3"
    _write_turn(
        db,
        session_id=session_key_from_ids(GROUP, "3865067623"),
        sender_id="3865067623",
        role="user",
        text="今天晚八点推版本",
    )

    context = shared_group_module.SQLiteGroupDigestProvider(db).load(
        "req-1", GROUP, "3865067623"
    )

    assert context.enabled is True
    assert "今天晚八点推版本" in context.summary


def test_multi_sender_group_rows_all_aggregated(tmp_path: Path) -> None:
    """群内多发送者：每位群友的发言与 bot 回复都进同一份群摘要。"""
    db = Path(tmp_path) / "history.sqlite3"
    senders = {
        "111": "甲的发言",
        "222": "乙的发言",
        "333": "丙的发言",
    }
    for uid, text in senders.items():
        _write_turn(
            db,
            session_id=session_key_from_ids(GROUP, uid),
            sender_id=uid,
            role="user",
            text=text,
        )
        _write_turn(
            db,
            session_id=session_key_from_ids(GROUP, uid),
            sender_id="bot",
            role="assistant",
            text=f"收到{uid}",
        )

    summary = shared_group_module.SQLiteGroupDigestProvider(
        db, max_turns=50
    ).load("req-1", GROUP, "").summary

    for text in (*senders.values(), "收到111", "收到222", "收到333"):
        assert text in summary


def test_other_group_rows_never_leak(tmp_path: Path) -> None:
    """他群行不进本群摘要（含互为数字前缀的群号陷阱）。

    若读侧用未转义 LIKE 前缀（``_`` 是单字符通配符），
    ``group_123456_%`` 会误吞 ``group_1234567_*`` 的行——本例即反证。
    """
    db = tmp_path / "history.sqlite3"
    _write_turn(
        db,
        session_id=session_key_from_ids(PREFIX_TRAP_GROUP, "111"),
        sender_id="111",
        role="user",
        text="本群内容",
    )
    _write_turn(
        db,
        session_id=session_key_from_ids(PREFIX_TRAP_OTHER, "222"),
        sender_id="222",
        role="user",
        text="长一号的别群内容",
    )
    _write_turn(
        db,
        session_id=session_key_from_ids(OTHER_GROUP, "333"),
        sender_id="333",
        role="user",
        text="无关他群内容",
    )

    summary = shared_group_module.SQLiteGroupDigestProvider(db).load(
        "req-1", PREFIX_TRAP_GROUP, ""
    ).summary

    assert "本群内容" in summary
    assert "长一号的别群内容" not in summary
    assert "无关他群内容" not in summary


def test_private_bare_uid_row_not_aggregated_into_group(tmp_path: Path) -> None:
    """私聊键（裸 uid 恰等于群号数字）不被群前缀误收——私聊内容绝不进群摘要。"""
    db = tmp_path / "history.sqlite3"
    _write_turn(
        db,
        session_id=GROUP,  # NoneBot 私聊 get_session_id() == user_id 原值
        sender_id=GROUP,
        role="user",
        text="只说给机器人的私话",
    )

    context = shared_group_module.SQLiteGroupDigestProvider(db).load(
        "req-1", GROUP, GROUP
    )

    assert context.enabled is False
    assert "只说给机器人的私话" not in context.summary


@pytest.mark.parametrize(
    ("group_id", "user_id"),
    [
        (GROUP, "3865067623"),
        (GROUP, ""),  # 中央构造器的 unknown 兜底形态也必须在读侧前缀内
        ("1076073471", "3113533731"),
    ],
)
def test_central_builder_key_always_matches_read_prefix(
    group_id: str, user_id: str
) -> None:
    """跨键形态一致性反证锁：中央构造器产出的写键 ⊆ 读侧群前缀。

    写侧键若未来换形（改 session_key_from_ids 或摄取层），本锁与
    test_write_entry_row_is_readable_by_group_id 一起报红，杜绝再次静默分叉。
    """
    assert session_key_from_ids(group_id, user_id).startswith(_group_prefix(group_id))


def test_legacy_colon_scheme_row_is_not_read(tmp_path: Path) -> None:
    """漂移死形态 group:<gid>（生产 0 行实证）不再被读侧消费，防回潮。"""
    db = tmp_path / "history.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            CREATE TABLE conversation_turns (
                request_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                adapter TEXT NOT NULL,
                bot_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                kind TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO conversation_turns VALUES"
            " ('r','qq','onebot-v11','b',?, 'u','user','死形态内容',"
            " '2026-09-11T08:00:00','chat')",
            (f"group:{GROUP}",),
        )

    context = shared_group_module.SQLiteGroupDigestProvider(db).load("req-1", GROUP, "")

    assert context.enabled is False


def test_group_prefix_shape_pinned() -> None:
    """读侧前缀与 OneBot 群键逐字同构：f"group_{gid}_"；空群号无前缀。"""
    assert _group_prefix(GROUP) == f"group_{GROUP}_"
    assert _group_prefix(f"  {GROUP}  ") == f"group_{GROUP}_"
    assert _group_prefix("") == ""
    assert _group_prefix(None) == ""
