"""关系档真身 `character/relationships.py`（2026-09-24 用户裁定 R2 A）。

裁定的原话：「L1 不仅仅是 Master Love，用户对 bot 的态度可能是多样的，不局限于
Master，可能还有恋人、情侣、夫妻、母亲和孩子（或颠倒）的关系」⇒ 亲密档的"关系身份"
必须是一张**受控词表**（不是自由文本，自由文本会把"你是我妈"之外的任何设定都吃进来），
且 Master Love 那段逐字保留为词表里的一格（改前行为不回归）。

方向以 **bot 为参照**命名：``parent`` = bot 是长辈/照护者，``child`` = bot 是晚辈。
"""
from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.relationships import (
    RELATIONSHIP_INSTRUCTIONS,
    normalize_relationship,
    relation_ids,
    relation_instruction,
    relationship_vocabulary_text,
)


def test_vocabulary_is_the_ruled_set() -> None:
    assert set(relation_ids()) == {
        "master",
        "lover",
        "couple",
        "spouse",
        "parent",
        "child",
        "family",
        "close_friend",
    }


def test_ids_and_instructions_are_the_same_keyset() -> None:
    """结构锁：词表与指令表不许分叉（有 id 没指令=那一档静默没有语气，最难查）。"""
    assert set(RELATIONSHIP_INSTRUCTIONS) == set(relation_ids())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("恋人", "lover"),
        ("情人", "lover"),
        ("情侣", "couple"),
        ("对象", "couple"),
        ("夫妻", "spouse"),
        ("老婆", "spouse"),
        ("爱人", "spouse"),
        ("master", "master"),
        ("创造者", "master"),
        ("挚友", "close_friend"),
        ("闺蜜", "close_friend"),
        ("家人", "family"),
        # 繁體：词表把简繁两式都登记在案（不是运行时折形），缺一条就查不到档。
        ("戀人", "lover"),
        ("  Lover  ", "lover"),
        ("LOVER", "lover"),
    ],
)
def test_alias_normalize_to_canonical(raw: str, expected: str) -> None:
    assert normalize_relationship(raw) == expected


def test_direction_does_not_collapse() -> None:
    """「母亲和孩子（或颠倒）」两格必须**分得开**：混了就是把长辈当晚辈叫。"""
    assert normalize_relationship("妈妈") == "parent"
    assert normalize_relationship("母亲") == "parent"
    assert normalize_relationship("我是你妈妈") == "parent"
    assert normalize_relationship("女儿") == "child"
    assert normalize_relationship("我是你女儿") == "child"
    assert normalize_relationship("妈妈") != normalize_relationship("女儿")


@pytest.mark.parametrize("raw", ["", "   ", None, "指挥官", "老师", "宠物", "12345"])
def test_unknown_is_never_guessed(raw: object) -> None:
    """词表外一律空串（不猜）：宁可没有关系身份，也不把没裁过的关系注入人格。

    ⚠ 本条原先还把「恋人未满」当反例，写实现时被推翻：它含词表内的"恋人"，
    按子串命中判成 lover 是对的行为（别名判定要能接住"我是你妈妈"这类整句声明），
    所以它不是"词表外"。留在此处记下这条边界。
    """
    assert normalize_relationship(raw) == ""  # type: ignore[arg-type]


def test_master_instruction_survives_byte_identical() -> None:
    """再导出垫片断不得改字：改前 ML 注入的是一段固定 system message，
    逐字进、逐字出，否则 09-24 复核过的锁（sha 等值）会漂。

    ⚠ 只比"两处相等"是**自证**（两边同源，永远绿）。故本锁钉的是迁入
    `relationships.py` 那一刻对 **git HEAD 原文** 实算出的 sha256 前 16 位
    （`cdd70f49c69e1b11`，167 字），改一个字就红。
    """
    import hashlib

    from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
        MASTER_LOVE_INSTRUCTION,
    )

    text = relation_instruction("master")
    assert text == MASTER_LOVE_INSTRUCTION
    assert len(text) == 167
    assert hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] == "cdd70f49c69e1b11"
    assert "不推翻" in text  # 身份事实锚还在原位


def test_empty_relation_has_no_instruction() -> None:
    assert relation_instruction("") == ""
    assert relation_instruction("没有这个档") == ""


@pytest.mark.parametrize("relation", sorted(relation_ids()))
def test_every_relation_carries_the_two_anti_abuse_anchors(relation: str) -> None:
    """每格指令都必须自带两句锚：①不推翻既有身份与称谓（不 OOC）；
    ②不越红线面（六条硬线任何设定压不过——落在措辞上是指向「亲密边界」/红线）。
    少一句就是给了越权面。

    ⚠ 锚②的判据写成三选一，是因为 ``master`` 那格必须**逐字不动**（上一条测试
    的 byte-identical 锁），而它改前的原文用的是「亲密边界」而不是「红线」二字。
    """
    text = relation_instruction(relation)
    assert text
    assert "不 OOC" in text or "不OOC" in text
    assert any(anchor in text for anchor in ("红线", "硬线", "亲密边界"))


def test_vocabulary_text_is_projection_not_second_copy() -> None:
    """帮助页/身份卡读的是投影：必须含全部档位名，且不许出现词表里没有的名字。"""
    text = relationship_vocabulary_text()
    for relation in relation_ids():
        assert relation in text
    assert "指挥官" not in text


# ---------------------------------------------------------------- 存储腿（按 (会话,人) 隔离）


def _store(tmp_path):
    from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
        AddressingPreferenceStore,
    )

    return AddressingPreferenceStore(tmp_path / "addressing.sqlite3")


def test_store_roundtrip_and_default_empty(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.get_relationship(session_type="private", sender_id="u1") == ""
    assert store.set_relationship(
        session_type="private", sender_id="u1", relationship="恋人"
    ) == "lover"
    assert store.get_relationship(session_type="private", sender_id="u1") == "lover"
    # 按人隔离：别人没设过就是空。
    assert store.get_relationship(session_type="private", sender_id="u2") == ""
    # 群内同人不同群也隔离（主键含 session_id）。
    assert store.get_relationship(
        session_type="group", session_id="g1", sender_id="u1"
    ) == ""


def test_store_rejects_unknown_without_destroying_existing(tmp_path) -> None:
    """词表外：回空串且**不动原值**——打错一个字不许把已设的关系洗掉。"""
    store = _store(tmp_path)
    store.set_relationship(session_type="private", sender_id="u1", relationship="夫妻")
    assert store.set_relationship(
        session_type="private", sender_id="u1", relationship="指挥官"
    ) == ""
    assert store.get_relationship(session_type="private", sender_id="u1") == "spouse"
    # 显式清空走空串，与"垃圾输入"分得开。
    store.set_relationship(session_type="private", sender_id="u1", relationship="")
    assert store.get_relationship(session_type="private", sender_id="u1") == ""


def test_store_does_not_disturb_addressing_columns(tmp_path) -> None:
    """加列不许动既有读面：称谓/性别仍按原样读写。"""
    store = _store(tmp_path)
    store.set(session_type="private", sender_id="u1", addressing_preference="船长", gender_identity="female")
    store.set_relationship(session_type="private", sender_id="u1", relationship="挚友")
    assert store.get(session_type="private", sender_id="u1") == ("船长", "female")
    assert store.get_relationship(session_type="private", sender_id="u1") == "close_friend"


def test_legacy_db_without_the_column_is_migrated(tmp_path) -> None:
    """旧库（无 relationship 列）打开即自动加列，且不搬动存量行。

    家规先例=affinity 三列的 ALTER-if-missing；本仓绝不要求人工迁移。
    """
    import sqlite3
    from datetime import datetime, timezone

    from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
        AddressingPreferenceStore,
    )

    path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS addressing_preferences (
            session_type TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            sender_id TEXT NOT NULL,
            addressing_preference TEXT NOT NULL DEFAULT '',
            gender_identity TEXT NOT NULL DEFAULT 'unknown',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (session_type, session_id, sender_id)
        )
        """
    )
    conn.execute(
        "INSERT INTO addressing_preferences VALUES (?,?,?,?,?,?)",
        ("private", "", "old-u", "老兵", "male", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    store = AddressingPreferenceStore(path)
    assert store.get(session_type="private", sender_id="old-u") == ("老兵", "male")
    assert store.get_relationship(session_type="private", sender_id="old-u") == ""
    columns = {
        row[1] for row in store._conn.execute("PRAGMA table_info(addressing_preferences)")
    }
    assert "relationship" in columns
