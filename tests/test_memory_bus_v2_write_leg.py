"""记忆 v2 总线**写腿**验收（S-T-MEM-1，需求 11「记住昵称/名字/身份…并在需要时说得出」）。

判据取向（本席自锁，逐条对应硬要求）：

- 全部用例走**真实形态的会话键与真实写入口**（``store_extracted_memories`` /
  ``SQLiteMemoryRepository.upsert_fact`` / ``MemoryBus.absorb``），然后**直接查库
  断言行数与逐列值**——不看函数返回值自证，返回值糊过真实落库的例子本仓已经吃过
  （台账 #50「存在性糊过活性判据」）。
- 作用域一律经 ``domains/core/session_keys`` 派生，夹具里的键形逐字取 OneBot
  ``get_session_id()`` 的实测形态（群=``group_<gid>_<uid>``、私聊=裸 uid）。
- 全离线：库文件只在 ``tmp_path``，绝不碰 ``ChatBot_Runtime/``。
"""

from __future__ import annotations

import ast
import datetime
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    SQLiteMemoryRepository,
    build_fact_id,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    ATTRIBUTE_SLOT_PREFIX,
    PROVENANCE_DERIVED,
    PROVENANCE_EXPLICIT,
    PROVENANCE_REFLECTED,
    STATUS_PENDING,
    STATUS_SUPERSEDED,
    MemoryBus,
    derive_scope,
    fact_signature,
    identity_attribute,
    slot_namespace,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
    MemoryStoreV21,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
GROUP_A = "group_1108838060_3865067623"
GROUP_B = "group_631785829_3865067623"
PRIVATE = "3865067623"
SENDER_A = "3865067623"
SENDER_B = "1722380002"
FIXED_NOW = datetime.datetime(2026, 9, 25, 12, 0, tzinfo=datetime.timezone.utc)


class BusConfig:
    """总线开态桩（生产缺省见 config.py：bus_enabled=False，须她显式打开）。"""

    bot_memory_enabled = True
    bot_memory_db_path = ""
    bot_memory_max_items = 5
    bot_memory_max_chars = 1200
    bot_memory_bus_enabled = True
    bot_memory_reflected_write_target = "bus"
    bot_memory_strength_k = 3.0
    bot_memory_tau_stable_days = 180
    bot_memory_tau_seasonal_days = 45
    bot_memory_tau_episodic_days = 14
    bot_memory_relevance_weights = ""
    bot_memory_per_category_max = 1
    bot_memory_semantic_recall_enabled = True


def _clock() -> Any:
    return lambda: FIXED_NOW


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStoreV21:
    return MemoryStoreV21(str(tmp_path / "memory.sqlite3"))


def _bus(store: MemoryStoreV21, **kwargs: Any) -> MemoryBus:
    return MemoryBus(store, config=kwargs.pop("config", BusConfig()), clock=_clock(), **kwargs)


def _rows(store: MemoryStoreV21) -> list[dict[str, Any]]:
    return store.list_all_entries()


def _db_rows(db: Path, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """**直查库文件**（另开只读连接）——本席的活性判据一律走这里，不走总线内存。"""
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


def _absorb(bus: MemoryBus, text: str, *, session=GROUP_A, owner=SENDER_A, **kw: Any):
    return bus.absorb(
        owner_id=owner,
        subject_user_id=owner,
        text=text,
        session_id=session,
        source_event_id=str(kw.pop("event", "")),
        **kw,
    )


def _bus_repo(db: Path) -> tuple[SQLiteMemoryRepository, MemoryStoreV21]:
    """按「装配点传了 bus」的形态构造仓储（= 本席要接成的生产形状）。"""
    config = BusConfig()
    config.bot_memory_db_path = str(db)
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
        build_memory_bus_for_writer,
    )

    bus = build_memory_bus_for_writer(config)
    assert bus is not None, "总线开态却建不出实例：装配口本身坏了"
    return SQLiteMemoryRepository(db, bus=bus), MemoryStoreV21(str(db))


# ---------------------------------------------------------------- 端到端：抽取→落库


def test_write_leg_end_to_end_lands_every_column_in_the_bus(tmp_path: Path) -> None:
    """硬要求①活性判据：喂真实形态对话产出，直查库逐列断言，且旧表根本没被建。

    这条同时是「一个真身」的证据：总线开着时抽取路径**只**写
    ``memory_entries_v21``，``memory_facts`` 这张表连 schema 都不该出现。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_extract import (
        store_extracted_memories,
    )

    db = tmp_path / "memory.sqlite3"
    repo, store = _bus_repo(db)
    stored = store_extracted_memories(
        repo,
        subject_user_id=SENDER_A,
        session_id=GROUP_A,
        texts=["我对芒果过敏", "我最近在学 Rust"],
    )
    assert stored == 2

    rows = _db_rows(db, "SELECT * FROM memory_entries_v21 ORDER BY text")
    assert [row["text"] for row in rows] == ["我对芒果过敏", "我最近在学 Rust"]
    allergy = rows[0]
    assert allergy["owner_id"] == SENDER_A  # 归属=说话人本人（硬要求③）
    assert allergy["scope_kind"] == derive_scope(GROUP_A).kind == "group_member"
    assert allergy["scope_key"] == GROUP_A  # 键形唯一来自中央件，未手拼
    assert allergy["provenance"] == PROVENANCE_DERIVED
    assert allergy["source"] == "llm_extract"
    assert allergy["confirm_count"] == 1
    assert allergy["contradict_count"] == 0
    assert allergy["supersedes"] == ""
    assert allergy["slot_key"].startswith("preference|") or allergy["slot_key"].startswith(
        "|"
    ), allergy["slot_key"]  # 抽取面 memory_kind='auto' 已折进空命名空间
    assert allergy["status"] == "active"
    assert allergy["polarity"] == "+"

    with sqlite3.connect(db) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_facts'"
            ).fetchone()
            is None
        ), "总线开态还在建旧表 = 第二套写入路径"
    assert store.count_bus_rows(owner_id=SENDER_A) == 2


def test_repeated_extraction_never_accumulates_rows(tmp_path: Path) -> None:
    """硬要求①：同一条事实被反复抽出只累加印证，不累加行。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_extract import (
        store_extracted_memories,
    )

    db = tmp_path / "memory.sqlite3"
    repo, _store = _bus_repo(db)
    for _round in range(4):
        assert (
            store_extracted_memories(
                repo,
                subject_user_id=SENDER_A,
                session_id=PRIVATE,
                texts=["我喜欢柠檬茶"],
            )
            == 1
        )
    rows = _db_rows(db, "SELECT * FROM memory_entries_v21")
    assert len(rows) == 1, [row["text"] for row in rows]
    assert rows[0]["confirm_count"] == 4


def test_source_label_and_command_surface_share_one_slot(tmp_path: Path) -> None:
    """命名空间归一：命令面 ``manual`` 与抽取面 ``auto`` 说同一件事必须落同一行。

    修法前它们是 ``manual|柠檬茶`` 与 ``auto|柠檬茶`` 两行，「又说起=确认」与
    「显式压过归纳」在写入侧永远不成立。
    """
    db = tmp_path / "memory.sqlite3"
    repo, _store = _bus_repo(db)
    repo.upsert_fact(
        fact_id=build_fact_id(SENDER_A, PRIVATE, "我喜欢柠檬茶"),
        subject_user_id=SENDER_A,
        session_id=PRIVATE,
        memory_kind="manual",
        text="我喜欢柠檬茶",
        confidence=1.0,
        source="manual_command",
    )
    repo.upsert_fact(
        fact_id=build_fact_id(SENDER_A, PRIVATE, "我超爱柠檬茶"),
        subject_user_id=SENDER_A,
        session_id=PRIVATE,
        memory_kind="auto",
        text="我超爱柠檬茶",
        confidence=0.6,
        source="llm_extract",
        provenance=PROVENANCE_DERIVED,
    )
    rows = _db_rows(db, "SELECT * FROM memory_entries_v21")
    assert len(rows) == 1, [row["slot_key"] for row in rows]
    assert rows[0]["confirm_count"] == 2
    assert rows[0]["provenance"] == PROVENANCE_EXPLICIT  # 本人亲口说压过归纳
    assert rows[0]["status"] == "active"
    assert slot_namespace("auto") == slot_namespace("manual") == slot_namespace("") == ""
    assert slot_namespace("preference") == "preference"


# ---------------------------------------------------------------- 幂等三层


def test_same_source_event_replay_never_writes_a_second_row(store: MemoryStoreV21) -> None:
    """层①：同一来源事件重放（迁移/重试/双投）一律 skip，哪怕文本换了。"""
    bus = _bus(store)
    first = _absorb(bus, "我住在北京", event="evt-1")
    assert first.action == "inserted"
    replay = _absorb(bus, "我住在上海", event="evt-1")
    assert replay.action == "duplicate_skipped"
    assert replay.memory_id == first.memory_id
    rows = _rows(store)
    assert len(rows) == 1 and rows[0]["text"] == "我住在北京"
    assert rows[0]["confirm_count"] == 1


def test_concurrent_writers_of_the_same_fact_yield_one_row(tmp_path: Path) -> None:
    """层②的并发腿：多线程同抽一句 ⇒ 恰好一行、六次印证（读-改-写不串行就会多行）。

    顺带实证「SQLite 阻塞写不落事件循环线程」在本路径成立：断言全部落库发生在
    非主线程上（生产由 ``chat.py`` 的 ``chat-memory-extract`` 线程池外投递）。
    """
    db = tmp_path / "memory.sqlite3"
    store = MemoryStoreV21(str(db))
    bus = _bus(store)
    threads_seen: set[str] = set()
    barrier = threading.Barrier(6)
    outcomes: list[Any] = []
    lock = threading.Lock()

    def _worker() -> None:
        threads_seen.add(threading.current_thread().name)
        barrier.wait()  # 逼六个写者撞进同一段读-改-写
        outcome = _absorb(bus, "我喜欢柠檬茶", provenance=PROVENANCE_DERIVED)
        with lock:
            outcomes.append(outcome)

    workers = [threading.Thread(target=_worker, name=f"extract-{i}") for i in range(6)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    rows = _db_rows(db, "SELECT * FROM memory_entries_v21")
    assert len(rows) == 1, [row["text"] for row in rows]
    assert int(rows[0]["confirm_count"]) == 6, rows[0]["confirm_count"]
    assert len(outcomes) == 6
    actions = {outcome.action for outcome in outcomes}
    assert actions == {"inserted", "confirmed"}, actions
    assert "MainThread" not in threads_seen  # 落库全程不在主线程


# ---------------------------------------------------------------- 作用域窗（修①）


def test_said_in_group_then_privately_yields_two_each_visible_rows(
    store: MemoryStoreV21,
) -> None:
    """数据消失级缺陷的正解：跨作用域不许静默合流。

    修法前：私聊那一句被判「确认」并进群作用域行 ⇒ 私聊召回按 scope_key 等值取数
    看不见它，用户第二次说等于白说。
    """
    bus = _bus(store)
    group = _absorb(bus, "我喜欢柠檬茶", session=GROUP_A, event="e1", category="preference")
    private = _absorb(
        bus, "我喜欢柠檬茶", session=PRIVATE, event="e2", category="preference"
    )
    assert group.action == "inserted" and private.action == "inserted"

    rows = _rows(store)
    assert len(rows) == 2
    scopes = {str(row["scope_key"]) for row in rows}
    assert scopes == {GROUP_A, PRIVATE}

    in_group = bus.recall(owner_id=SENDER_A, session_id=GROUP_A, query_text="柠檬茶")
    in_private = bus.recall(owner_id=SENDER_A, session_id=PRIVATE, query_text="柠檬茶")
    assert [item.text for item in in_group.items] == ["我喜欢柠檬茶"]
    assert [item.text for item in in_private.items] == ["我喜欢柠檬茶"]
    # 另一个群仍然什么都看不见（fail-closed 的一侧没被放宽）。
    elsewhere = bus.recall(owner_id=SENDER_A, session_id=GROUP_B, query_text="柠檬茶")
    assert elsewhere.items == [] and elsewhere.candidates == 0


def test_two_groups_do_not_confirm_each_other(store: MemoryStoreV21) -> None:
    bus = _bus(store)
    _absorb(bus, "我在戒糖", session=GROUP_A, event="g1", category="preference")
    second = _absorb(bus, "我在戒糖", session=GROUP_B, event="g2", category="preference")
    assert second.action == "inserted"
    rows = _rows(store)
    assert len(rows) == 2 and all(int(row["confirm_count"]) == 1 for row in rows)


def test_same_scope_still_confirms(store: MemoryStoreV21) -> None:
    """收窗不能把「同处再说一次」也拆开——那正是印证证据的来源。"""
    bus = _bus(store)
    _absorb(bus, "我喜欢柠檬茶", session=PRIVATE, event="p1", category="preference")
    again = _absorb(bus, "我超爱柠檬茶", session=PRIVATE, event="p2", category="preference")
    assert again.action == "confirmed"
    assert again.confirm_count == 2
    assert len(_rows(store)) == 1


# ---------------------------------------------------------------- 身份属性（修③）


@pytest.mark.parametrize(
    ("text", "attribute", "value"),
    [
        ("我叫林澜", "name", "林澜"),
        ("我的名字是林澜", "name", "林澜"),
        ("我不叫林澜", "name", "林澜"),
        ("叫我小红", "nickname", "小红"),
        ("以后叫我小红", "nickname", "小红"),
        ("我的昵称是小满", "nickname", "小满"),
        ("我的性别是女", "gender", "女"),
        ("我是女生", "gender", "女生"),
        ("我的职业是程序员", "occupation", "程序员"),
        ("我住在北京", "location", "北京"),
        ("我的城市是上海", "location", "上海"),
        ("我的生日是3月14日", "birthday", "3月14日"),
        ("my name is Alice", "name", "alice"),
        ("call me Bob", "nickname", "bob"),
    ],
)
def test_identity_attributes_are_recognised(
    text: str, attribute: str, value: str
) -> None:
    assert identity_attribute(text) == (attribute, value)


@pytest.mark.parametrize(
    "text",
    [
        "我妹妹住在北京",  # 第三人称：不是她的所在地
        "我是在三月份入职的",  # 入职时间 ≠ 生日
        "我的爱好是摄影",  # 可并存多项，绝不成属性槽
        "我性格比较慢热",
        "我喜欢小明",  # 「喜欢X」不是「我叫X」
        "叫我起床",  # 提要求 ≠ 改称呼
        "叫我多喝水",
        "叫我复习",
        "叫我打卡",
        "别忘了叫我",
        "我住在隔壁那栋楼的第三个房间的门牌是甲乙丙丁戊己庚辛壬癸",  # 超长：不认
        "user 住在北京",
    ],
)
def test_non_identity_statements_never_take_an_attribute_slot(text: str) -> None:
    assert identity_attribute(text) == ("", "")
    signature = fact_signature(text)
    assert not signature.slot.startswith(ATTRIBUTE_SLOT_PREFIX)
    assert signature.slot == f"|{signature.residual}"


def test_nickname_change_supersedes_old_row_and_keeps_the_trace(
    store: MemoryStoreV21,
) -> None:
    """一个属性只留一个当前值，但**不是静默覆盖**：旧行留、指纹留、矛盾计数留。"""
    bus = _bus(store)
    first = _absorb(bus, "叫我小红", session=PRIVATE, event="n1")
    renamed = _absorb(bus, "叫我阿澜", session=PRIVATE, event="n2")
    assert renamed.action == "contradicted"
    assert renamed.superseded_id == first.memory_id

    rows = {str(row["text"]): row for row in _rows(store)}
    assert set(rows) == {"叫我小红", "叫我阿澜"}  # 行没被删、文本没被改
    assert rows["叫我小红"]["status"] == STATUS_SUPERSEDED
    assert int(rows["叫我小红"]["contradict_count"]) == 1
    assert rows["叫我阿澜"]["supersedes"] == rows["叫我小红"]["memory_id"]
    assert rows["叫我阿澜"]["slot_key"] == "attr:nickname" == rows["叫我小红"]["slot_key"]

    recalled = bus.recall(owner_id=SENDER_A, session_id=PRIVATE, query_text="")
    assert [item.text for item in recalled.items] == ["叫我阿澜"]

    # kind 带属性名：渲染腿（S-T-MEM-3）要的就是「这是称呼」，不该再从文本猜。
    assert rows["叫我阿澜"]["kind"] == "nickname"
    # 属性之外的类别词表一字未动（fact/preference/event 仍是老那三档）。
    # 放在召回断言之后：再多一条 active 事实会改召回面的条数，判据要各自干净。
    _absorb(bus, "我喜欢柠檬茶", session=PRIVATE, event="k9", category="preference")
    tea = next(row for row in _rows(store) if str(row["text"]) == "我喜欢柠檬茶")
    assert tea["kind"] == "preference"


def test_restating_the_same_nickname_confirms_and_does_not_supersede(
    store: MemoryStoreV21,
) -> None:
    bus = _bus(store)
    first = _absorb(bus, "叫我小红", session=PRIVATE, event="r1")
    again = _absorb(bus, "叫我小红", session=PRIVATE, event="r2")
    assert again.action == "confirmed" and again.memory_id == first.memory_id
    rows = _rows(store)
    assert len(rows) == 1
    assert int(rows[0]["confirm_count"]) == 2
    assert rows[0]["status"] == "active"


def test_two_different_attributes_coexist(store: MemoryStoreV21) -> None:
    """名字与称呼是两个属性，不该互相顶掉。"""
    bus = _bus(store)
    _absorb(bus, "我叫林澜", session=PRIVATE, event="a")
    _absorb(bus, "叫我小红", session=PRIVATE, event="b")
    rows = {str(row["slot_key"]) for row in _rows(store)}
    assert rows == {"attr:name", "attr:nickname"}


def test_machine_guessed_identity_waits_for_the_owner_then_becomes_visible(
    store: MemoryStoreV21,
) -> None:
    """修④两半：猜的身份先待审；本人说了之后**必须真的可见**（升格要连状态一起升）。

    旧写腿的漏网在升格分支只改 provenance 不改 status ⇒ 行永远留在
    pending_review，而召回口只取 active =「记了但说不出来」。
    """
    bus = _bus(store)
    guessed = _absorb(
        bus, "叫我小红", session=PRIVATE, event="m1", provenance=PROVENANCE_DERIVED
    )
    assert guessed.action == "inserted"
    assert _rows(store)[0]["status"] == STATUS_PENDING
    assert bus.recall(owner_id=SENDER_A, session_id=PRIVATE, query_text="称呼").items == []

    owner_said = _absorb(bus, "叫我小红", session=PRIVATE, event="m2")
    assert owner_said.action == "confirmed"
    row = _rows(store)[0]
    assert row["status"] == "active"
    assert row["provenance"] == PROVENANCE_EXPLICIT
    assert int(row["confirm_count"]) == 2
    assert [item.text for item in bus.recall(
        owner_id=SENDER_A, session_id=PRIVATE, query_text="称呼"
    ).items] == ["叫我小红"]


def test_reflection_never_supersedes_an_explicit_nickname(store: MemoryStoreV21) -> None:
    """夜间归纳不得作废本人明示的身份事实（硬要求②）。"""
    bus = _bus(store)
    explicit = _absorb(bus, "叫我小红", session=PRIVATE, event="k1")
    night = _absorb(
        bus,
        "叫我阿澜",
        session=PRIVATE,
        event="k2",
        provenance=PROVENANCE_REFLECTED,
    )
    assert night.action == "inserted"  # 不 supersede、不记矛盾
    rows = {str(row["memory_id"]): row for row in _rows(store)}
    incumbent = rows[explicit.memory_id]
    assert incumbent["status"] == "active"
    assert int(incumbent["contradict_count"]) == 0
    assert rows[night.memory_id]["status"] == STATUS_PENDING
    chosen = bus.recall(owner_id=SENDER_A, session_id=PRIVATE, query_text="")
    assert chosen.items[0].text == "叫我小红"


def test_attributes_are_scoped_too(store: MemoryStoreV21) -> None:
    """属性槽同样受作用域窗约束：私聊改称呼不得顶掉群里那行的可见性。"""
    bus = _bus(store)
    _absorb(bus, "叫我小红", session=GROUP_A, event="s1")
    _absorb(bus, "叫我阿澜", session=PRIVATE, event="s2")
    rows = _rows(store)
    assert len(rows) == 2 and all(row["status"] == "active" for row in rows)
    assert [
        item.text
        for item in bus.recall(owner_id=SENDER_A, session_id=GROUP_A, query_text="").items
    ] == ["叫我小红"]


# ---------------------------------------------------------------- 归属（硬要求③）


def test_owner_is_the_speaker_and_two_senders_never_share_rows(store: MemoryStoreV21) -> None:
    """「把 A 说的话记到 B 头上」的历史问题：owner 只认调用方给的说话人。"""
    bus = _bus(store)
    _absorb(bus, "我对芒果过敏", session=f"group_1108838060_{SENDER_A}", event="o1", owner=SENDER_A)
    _absorb(bus, "我对芒果过敏", session=f"group_1108838060_{SENDER_B}", event="o2", owner=SENDER_B)
    rows = _rows(store)
    assert {str(row["owner_id"]) for row in rows} == {SENDER_A, SENDER_B}
    assert len(rows) == 2
    assert bus.recall(owner_id=SENDER_B, session_id=GROUP_B, query_text="芒果").items == []
    for_a = bus.recall(
        owner_id=SENDER_A, session_id=f"group_1108838060_{SENDER_A}", query_text="芒果"
    )
    assert [item.text for item in for_a.items] == ["我对芒果过敏"]


def test_scope_key_is_the_central_normalized_form(store: MemoryStoreV21) -> None:
    """键形唯一真身：脏键/大写/冒号形都按中央件归一形落列，不手拼。"""
    bus = _bus(store)
    for raw, event in (("group:1108838060", "c1"), ("  3865067623  ", "c2")):
        outcome = _absorb(bus, "我在戒糖", session=raw, event=event, category="preference")
        assert outcome.action == "inserted"
    rows = _rows(store)
    assert {str(row["scope_key"]) for row in rows} == {"group:1108838060", PRIVATE}
    assert {str(row["scope_kind"]) for row in rows} == {"session"}


# ---------------------------------------------------------------- 一真身机器锁


_BUS_WRITE_METHODS = frozenset(
    {
        "insert_bus_entry",
        "update_bus_fields",
        "insert_entry",
        "update_entry",
        "insert_tombstone",
        "restore_tables",
    }
)
# 允许出现写调用的文件：真身自身 + 总线（唯一入口）+ 明确挂账的未装配件。
_WRITE_CALL_ALLOWED_FILES: dict[str, str] = {
    "domains/chat_reply/character/memory_store_v21.py": "SQL 层真身自身",
    "domains/chat_reply/character/memory_bus_v2.py": "总线=唯一事实写入口",
    "domains/chat_reply/character/memory_service.py": (
        "V2.1 记忆服务：L41 未裁决、生产未装配（见 HANDDBOOK 台账 #42），"
        "本锁同时执法「它不得被装配进生产」——见下一条用例"
    ),
}


def _plugins_python_files() -> list[Path]:
    return sorted(PLUGIN_ROOT.rglob("*.py"))


def test_only_the_bus_writes_the_v21_fact_table_in_production() -> None:
    """硬要求「不许出现第二套写入路径」的可机检形态。

    判据不是「有没有别的类」而是「有没有别的**写调用**」：AST 扫生产树里所有
    对 v21 事实表写方法的调用点，落在允许清单外的即红。
    """
    offenders: list[str] = []
    for path in _plugins_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 语法错由 lint 门管
            continue
        relative = path.relative_to(PLUGIN_ROOT).as_posix()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _BUS_WRITE_METHODS
            ):
                offenders.append(f"{relative}:{node.lineno}:{node.func.attr}")
    unexpected = [
        hit
        for hit in offenders
        if hit.split(":")[0] not in _WRITE_CALL_ALLOWED_FILES
    ]
    assert unexpected == [], f"总线之外又长出事实表写入口：{unexpected}"
    assert any("memory_bus_v2.py" in hit for hit in offenders), "扫描判据本身失效（零命中）"


def test_memory_service_v21_is_not_assembled_in_production() -> None:
    """允许清单里那枚挂账件必须真的还没接线，否则「一真身」立刻破。"""
    hits: list[str] = []
    for path in _plugins_python_files():
        relative = path.relative_to(PLUGIN_ROOT).as_posix()
        if relative.endswith("character/memory_service.py"):
            continue
        text = path.read_text(encoding="utf-8")
        if "MemoryServiceV21(" in text or "build_memory_service_v21" in text:
            hits.append(relative)
    assert hits == [], f"L41 未裁决的 V2.1 服务已被生产 import 面引用：{hits}"


def test_memory_writer_runs_off_the_event_loop() -> None:
    """硬要求④：落库这段 SQLite 必须跑在后台线程，不许挂在事件循环上。

    判据锁在**调用方**（那两个文件本席禁写，故只锁不改建）：
    ``chat.py`` 必须把 writer 交给 ``threading.Thread``，且派发函数自身是同步函数。
    """
    source = (
        PLUGIN_ROOT / "domains" / "chat_reply" / "capabilities" / "chat.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    scheduler = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_schedule_memory_extraction"
        ),
        None,
    )
    assert scheduler is not None, "找不到 _schedule_memory_extraction：坐标已漂，本锁要重算"
    assert isinstance(scheduler, ast.FunctionDef), (
        "_schedule_memory_extraction 被改成协程 ⇒ 记忆落库回到事件循环上"
    )
    runner = next(
        (
            node
            for node in ast.walk(scheduler)
            if isinstance(node, ast.FunctionDef) and node.name == "_run"
        ),
        None,
    )
    assert runner is not None, "writer 的后台执行体 _run 搬家了：本锁坐标要重算"
    calls_writer = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "memory_writer"
        for node in ast.walk(runner)
    )
    assert calls_writer, "memory_writer 不再由 _run 调用：本锁坐标要重算"
    threaded = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Thread"
        and any(
            isinstance(keyword, ast.keyword)
            and keyword.arg == "target"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "_run"
            for keyword in node.keywords
        )
        for node in ast.walk(scheduler)
    )
    assert threaded, "memory_writer 不再经 threading.Thread 派发 = 阻塞写落回事件循环"


# ---------------------------------------------------------------- 生产接线活性（已转正）


# 挂账结案（2026-09-27 S-FIX-ATK-MEMORY-FIX A 票）：装配腿已落码——根 __init__.py
# _build_memory_writer 构造 SQLiteMemoryRepository 时传入 bus=（开关关时该值为
# None、不碰库，缺省关态逐字节不变）。原 xfail(strict=False) 标记按台账约定摘除。
def test_production_memory_writer_builds_repository_with_bus() -> None:
    """生产抽取写入器必须把总线传给仓储，否则本席写的这条腿在现网仍是死件。

    期望形态（根 ``__init__.py`` ``_build_memory_writer`` 内）::

        repository = SQLiteMemoryRepository(config.bot_memory_db_path, bus=bus)
    """
    source = (PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    builder = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_build_memory_writer"
    )
    constructions = [
        node
        for node in ast.walk(builder)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "SQLiteMemoryRepository"
    ]
    assert constructions, "_build_memory_writer 里找不到仓储构造点：坐标已漂，本锁要重算"
    assert any(
        any(keyword.arg == "bus" for keyword in call.keywords) for call in constructions
    ), "生产写路径没把总线传给仓储 ⇒ 抽取仍落旧表 memory_facts"
