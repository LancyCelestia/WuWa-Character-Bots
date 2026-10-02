"""S21 召回侧排除锁：``source='llm_extract_about_assistant'`` 不再当「她本人的事实」用。

要判的病（台账 #73 穗波事故）：S17 把抽取器存下来的 **bot 自己的角色扮演台词**标成
``llm_extract_about_assistant``（选这列的理由＝不进枚举、不进渲染），但召回侧的
``WHERE`` 只看 ``subject_user_id``、从不看 ``source`` ⇒ 那批「关于 bot 却挂在用户名下」
的陈述照旧被召回进 prompt，标记纯属装饰。

判据取向（两枚，缺一不可）：

① **活性 + 反空转**：临时库塞「带标记一行 + 正常一行」，走真读路径 ``retrieve`` 与
   影子读 ``list_rows_for_subject``，断言前者只回干净行；**同一条 SQL 摘掉排除条件
   （裸查同一份库）必须两行都回**——否则①在「本来就没有第二行」的假象里空转。
② **形状锁**：两条取数 SELECT 的函数体里必须都带 ``source <> ?`` 且绑定
   ``SOURCE_EXCLUDED_FROM_RECALL``。把那个条件摘掉，①②同时转红（有牙的证明）。

行为边界：只排除这一个值，其他 ``source``（``llm_extract`` / ``manual`` /
``reflection``…）逐字节不变；全离线，库文件只在 ``tmp_path``，绝不碰 ``ChatBot_Runtime/``。
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import plugins.bot_unified_runtime.domains.chat_reply.character.memory as memory_mod
from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    SOURCE_EXCLUDED_FROM_RECALL,
    SQLiteMemoryRepository,
)

_OWNER = "3865067623"
_POISON_TEXT = "只在穗波的旧画册里翻到过"
_CLEAN_TEXT = "柠檬茶要少冰"


def _seed(db: Path) -> None:
    """夹具走裸 SQL：``upsert_fact`` 会过消毒闸、且时间戳不可控（同 read-leg 口径）。"""
    SQLiteMemoryRepository(db)._ensure_schema()
    moment = "2026-10-03T00:00:00+00:00"
    with sqlite3.connect(db) as connection:
        connection.executemany(
            """
            INSERT INTO memory_facts (
                fact_id, subject_user_id, session_id, memory_kind, text,
                confidence, source, sensitivity, scope_key, created_at, updated_at
            ) VALUES (?, ?, '', 'preference', ?, 0.9, ?, 'personal', '', ?, ?)
            """,
            [
                ("poison", _OWNER, _POISON_TEXT, SOURCE_EXCLUDED_FROM_RECALL, moment, moment),
                ("clean", _OWNER, _CLEAN_TEXT, "llm_extract", moment, moment),
            ],
        )
        connection.commit()


def test_recall_drops_about_assistant_marker_and_keeps_own_fact(tmp_path: Path) -> None:
    db = tmp_path / "memory_s21.sqlite3"
    _seed(db)
    repository = SQLiteMemoryRepository(db)

    result = repository.retrieve(
        request_id="req-s21",
        requester_id=_OWNER,
        subject_user_id=_OWNER,
        session_id="",
        query_text="",
        max_items=5,
        max_chars=500,
    )
    ids = [fact["fact_id"] for fact in result.facts]
    assert ids == ["clean"], f"带标记的 bot 自陈仍被召回：{ids}"
    assert all(fact["source"] != SOURCE_EXCLUDED_FROM_RECALL for fact in result.facts)
    assert all(_POISON_TEXT not in fact["text"] for fact in result.facts)

    # 总线影子读来源同一条口径（第二处召回真身）。
    assert [row["fact_id"] for row in repository.list_rows_for_subject(_OWNER)] == ["clean"]

    # 反空转正对照：同一份库、同一条 WHERE，摘掉排除条件必须两行都回。
    with sqlite3.connect(db) as connection:
        bare = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT fact_id FROM memory_facts
                WHERE subject_user_id = ?
                  AND session_id IN (?, '', '*', 'global')
                ORDER BY updated_at DESC, fact_id DESC
                LIMIT ?
                """,
                (_OWNER, "", 5),
            ).fetchall()
        ]
    assert sorted(bare) == ["clean", "poison"], f"夹具本身没牙（裸查只回 {bare}）"


def test_both_recall_selects_carry_the_exclusion() -> None:
    assert SOURCE_EXCLUDED_FROM_RECALL == "llm_extract_about_assistant"
    tree = ast.parse(Path(memory_mod.__file__).read_text(encoding="utf-8"))
    for func_name in ("_fetch_candidate_rows", "list_rows_for_subject"):
        func = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == func_name
        )
        unparsed = ast.unparse(func)
        assert "source <> ?" in unparsed, f"{func_name} 的召回 SQL 丢了排除条件"
        assert "SOURCE_EXCLUDED_FROM_RECALL" in unparsed, f"{func_name} 没绑定排除值"
