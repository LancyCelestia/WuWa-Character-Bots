"""记忆**读侧**三处消费面的两态验收（S-T-MEM-4，需求 11「记住并在需要时说得出来」）。

为什么有这个测试件（前任席位 S-T-MEM-1 §陆① 的风险段，本席逐条现算证实）：
写腿一旦接上，新抽取**只写 ``memory_entries_v21``**（旧表 ``memory_facts`` 从此
不再长新行），而仓里有三处只读旧表的消费面——

1. 命令面 ``记忆 list`` / ``记忆 delete``（``capabilities/memory.py``）
2. WebUI 记忆图谱（``control_plane/webui_memory_graph.py``，端点
   ``GET /api/v1/memory/graph``；路由薄壳在 ``control_plane/api/webui_ext.py``）
3. 记忆隐私清洗的读侧（``security/memory_sanitize.py``）

开闸当天它们会集体看不见新记录。本席接的就是这三处的**读侧**；写侧与开关判定
一字不动。

判据取向（对应本席硬要求）：

- **两态各一把锁**：关态三处输出与**冻结的基线快照**逐字段相等（快照取自现网
  形态：只有 ``memory_facts`` 的库，字面量钉死而非跑一遍比一遍）；开态同一句话
  三处**各自**现算得到该行。只测关态等于测「这个功能不存在」。
- **不双读拼表、不写第二套开关判定**：三处读侧要么委托给既有唯一入口
  ``SQLiteMemoryRepository(bus=…)``（命令面），要么走本席新增的**一处**批量投影
  ``iter_stored_memory_rows``（图谱/清洗）。没有任何一处读 ``bot_memory_bus_enabled``
  ——由 AST 锁执法（§5 组）。
- **直查库文件**：断言一律另开连接查表，不看函数返回值自证（台账 #50
  「存在性糊过活性判据」同型教训）。
- 全离线：库文件只在 ``tmp_path``，绝不碰 ``ChatBot_Runtime/``；不删任何真实文件。
"""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.control_plane.webui_memory_graph import (
    MemoryGraphService,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.memory import (
    MEMORY_BUS_TABLE,
    MEMORY_LEGACY_TABLE,
    current_memory_rows,
    echo_safe_rows,
    is_echo_safe_sensitivity,
    iter_stored_memory_rows,
    memory_store_tables,
    memory_tables_with_columns,
    route_memory_command,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    SQLiteMemoryRepository,
    build_fact_id,
    build_memory_bus_for_writer,
    legacy_explicit_reader_for,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    MemoryBus,
    MemoryBusProvider,
    build_memory_bus,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
    MemoryStoreV21,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.memory_sanitize import (
    sanitize_memory_db,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

SENDER = "3865067623"
OTHER_SENDER = "1722380002"
GROUP_A = "group_1108838060_3865067623"
GROUP_B = "group_631785829_3865067623"
PRIVATE = "3865067623"

HARD_LINE_TEXT = "用户写了未成年角色的性爱情节"
CLEAN_TEXT = "我喜欢喝柠檬茶"

# ---- 关态基线快照（字面量冻结）----------------------------------------------
#
# 这些 id 与文案是本席动手**之前**的生产输出（探针实跑取回后钉在这里）。它们的全部
# 意义就是「别为了接总线把现网改坏」：任何一处输出形制漂移都会打红。唯一有意相对
# HEAD 的改变是「凭证级不外露」，单独锁在 §4 组并写明差异，不混进基线里。
_CLOSED_PRIVATE_SEEDS = [
    ("喜欢柠檬茶", "public"),
    ("群公告周末线下聚会", "group"),
    ("只说给机器人的私话", "personal"),
]
_CLOSED_PRIVATE_BASELINE_BODY = (
    "当前记忆：\n"
    "- fact_7465b7f706ea（sensitivity=personal）：只说给机器人的私话\n"
    "- fact_143b885bf1bf（sensitivity=group）：群公告周末线下聚会\n"
    "- fact_1b8892d29891（sensitivity=public）：喜欢柠檬茶"
)
_CLOSED_GROUP_SEEDS = [
    ("可以群内公示的偏好", "public"),
    ("群公告周三例会", "group"),
    ("只说给机器人的私话", "personal"),
    ("某个服务口令", "credentialed"),
]
_CLOSED_GROUP_BASELINE_BODY = (
    "当前记忆：\n"
    "- fact_db1b30381b9d（sensitivity=group）：群公告周三例会\n"
    "- fact_1ae38a0b1274（sensitivity=public）：可以群内公示的偏好"
)
_PRIVATE_FACT_IDS = {
    "喜欢柠檬茶": "fact_1b8892d29891",
    "群公告周末线下聚会": "fact_143b885bf1bf",
    "只说给机器人的私话": "fact_7465b7f706ea",
}


class MemoryConfig:
    """装配层给的 config 替身：两态只差 ``bot_memory_bus_enabled`` 一枚。"""

    bot_memory_enabled = True
    bot_memory_db_path = ""
    bot_memory_bus_enabled = False
    bot_memory_reflected_write_target = "legacy"
    bot_memory_max_items = 5
    bot_memory_max_chars = 1200
    bot_memory_strength_k = 3.0
    bot_memory_tau_stable_days = 180
    bot_memory_tau_seasonal_days = 45
    bot_memory_tau_episodic_days = 14
    bot_memory_relevance_weights = ""
    bot_memory_per_category_max = 1
    bot_memory_semantic_recall_enabled = True


def _config(db: Path, *, bus_enabled: bool) -> MemoryConfig:
    config = MemoryConfig()
    config.bot_memory_db_path = str(db)
    config.bot_memory_bus_enabled = bus_enabled
    config.bot_memory_reflected_write_target = "bus" if bus_enabled else "legacy"
    return config


def _command_bus(db: Path, *, bus_enabled: bool) -> MemoryBus | None:
    """命令面该拿的那枚 bus——**装配层判一次开关**，本函数只做转交。

    与召回侧同形（带 ``legacy_explicit_reader``）；这条不是洁癖而是实测，见
    ``test_command_bus_without_the_shadow_reader_blindfolds_legacy_rows``。
    """
    return build_memory_bus(
        _config(db, bus_enabled=bus_enabled),
        legacy_explicit_reader=legacy_explicit_reader_for(str(db)),
    )


def _seed_legacy(
    db: Path, seeds: list[tuple[str, str]], *, session_id: str = PRIVATE
) -> None:
    """走生产写入口落旧表（关态形状 = 现网存量的真实形状）。"""
    repository = SQLiteMemoryRepository(db)
    for text, sensitivity in seeds:
        repository.upsert_fact(
            fact_id=build_fact_id(SENDER, session_id, text),
            subject_user_id=SENDER,
            session_id=session_id,
            memory_kind="manual",
            text=text,
            confidence=1.0,
            source="manual_command",
            sensitivity=sensitivity,
        )


def _list_body(
    db: Path,
    *,
    session_id: str = PRIVATE,
    sender_id: str = SENDER,
    bus: object | None = None,
) -> str:
    return route_memory_command(
        "memory list",
        sender_id=sender_id,
        session_id=session_id,
        db_path=db,
        bus=bus,
    ).body


def _command(db: Path, text: str, *, session_id: str = PRIVATE, bus: object | None = None) -> str:
    return route_memory_command(
        text,
        sender_id=SENDER,
        session_id=session_id,
        db_path=db,
        bus=bus,
    ).body


def _add_body(
    db: Path,
    text: str,
    *,
    session_id: str = PRIVATE,
    sensitivity: str = "",
    bus: object | None = None,
) -> str:
    payload = f"--sensitivity={sensitivity} {text}" if sensitivity else text
    return _command(db, f"memory add {payload}", session_id=session_id, bus=bus)


def _echoed_id(body: str) -> str:
    return body.split("fact_id=", 1)[1].splitlines()[0].strip()


def _listed_ids(body: str) -> list[str]:
    return [line.split("（")[0].removeprefix("- ").strip() for line in body.splitlines()[1:]]


def _graph_envelope(db: Path) -> dict[str, Any]:
    return MemoryGraphService(
        history_db_path="",
        memory_db_path=str(db),
        quirks_db_path="",
        affinity_db_path="",
    ).graph(window="all")


def _graph_memories(db: Path) -> tuple[list[str], list[str]]:
    """(记忆节点 id 升序, about 边) ——图谱读侧的现算结果。"""
    data = _graph_envelope(db)["data"]
    nodes = sorted(str(node["id"]) for node in data["nodes"] if node["type"] == "memory")
    edges = sorted(
        f'{edge["source"]}->{edge["target"]}'
        for edge in data["edges"]
        if edge["kind"] == "about"
    )
    return nodes, edges


def _db_tables(db: Path) -> list[str]:
    with sqlite3.connect(db) as connection:
        return sorted(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        )


def _db_rows(db: Path, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """**直查库文件**（另开只读连接）——本件的活性判据一律走这里。"""
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


def _plant_bus_row(db: Path, memory_id: str, *, status: str, text: str) -> None:
    """直插一行到总线表：绕开 ``absorb`` 的硬线闸，模拟「迁移/历史遗留的脏行」。

    总线写入口自己就拒硬线内容（``memory_bus_v2._sanitize_violation``），所以清洗
    面要扫的东西只能是这么来的——这恰好也是「清洗读集必须是召回读集的超集」的原因。
    """
    store = MemoryStoreV21(str(db))
    try:
        store.insert_bus_entry(
            {
                "memory_id": memory_id,
                "owner_id": SENDER,
                "session_id": PRIVATE,
                "kind": "fact",
                "status": status,
                "text": text,
                "confidence": 0.9,
                "sensitivity": "personal",
                "source": "migrated",
                "created_at": "2026-09-26T00:00:00+00:00",
                "updated_at": "2026-09-26T00:00:00+00:00",
            }
        )
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 1. 关态：三处输出与基线快照逐字段相等（硬要求①之二 + 活性判据②）
# ---------------------------------------------------------------------------


def test_closed_state_command_body_equals_frozen_baseline(tmp_path: Path) -> None:
    """关态 ``记忆 list`` 私聊输出＝今天逐字节（不传 bus 与传 None 同形）。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, _CLOSED_PRIVATE_SEEDS)

    assert _list_body(db) == _CLOSED_PRIVATE_BASELINE_BODY
    assert _list_body(db, bus=None) == _CLOSED_PRIVATE_BASELINE_BODY


def test_closed_state_group_body_equals_frozen_baseline(tmp_path: Path) -> None:
    """关态群门只放 public/group：基线里 personal 与 credentialed 都不外露。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, _CLOSED_GROUP_SEEDS, session_id=GROUP_A)

    assert _list_body(db, session_id=GROUP_A) == _CLOSED_GROUP_BASELINE_BODY


def test_closed_state_graph_equals_frozen_baseline(tmp_path: Path) -> None:
    """关态图谱的节点/边/来源/统计与基线逐字段相等（防「为接总线改坏现网」）。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, _CLOSED_PRIVATE_SEEDS)

    envelope = _graph_envelope(db)
    data = envelope["data"]
    assert envelope["status"] == "ok"
    assert data["sources"] == {
        "history": "missing",
        "memory": "ok",
        "quirks": "missing",
        "affinity": "missing",
    }
    assert data["stats"]["long_term_memories"] == 3
    nodes = {
        str(node["id"]): str(node["label"])
        for node in data["nodes"]
        if node["type"] == "memory"
    }
    assert nodes == {f"memory:{fact_id}": text for text, fact_id in _PRIVATE_FACT_IDS.items()}
    edges = sorted(
        f'{edge["source"]}->{edge["target"]}'
        for edge in data["edges"]
        if edge["kind"] == "about"
    )
    assert edges == [
        f"person:{SENDER}->memory:{fact_id}"
        for fact_id in sorted(_PRIVATE_FACT_IDS.values())
    ]


def test_closed_state_sanitize_report_and_render_equal_frozen_baseline(tmp_path: Path) -> None:
    """关态清洗的扫描数/命中/分类/渲染文案/隔离表内容与基线逐字段相等。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(
        db,
        [
            ("喜欢柠檬茶", "personal"),
            (HARD_LINE_TEXT, "personal"),
            ("用户骂了人：真是个废物", "personal"),
        ],
    )

    dry = sanitize_memory_db(db, apply=False)
    assert (dry.scanned, dry.quarantined, dry.by_category) == (3, 1, {"minors": 1})
    assert dry.render(applied=False) == (
        "记忆清洗（dry-run 预览）：扫描 3 条，命中 1 条\n  - minors: 1"
    )

    applied = sanitize_memory_db(db, apply=True)
    assert applied.render(applied=True) == (
        "记忆清洗（已执行）：扫描 3 条，命中 1 条\n  - minors: 1"
    )
    assert _db_rows(
        db, "SELECT fact_id, category, source_table, text FROM memory_quarantine"
    ) == [
        {
            "fact_id": "fact_76c96d9f4567",
            "category": "minors",
            "source_table": MEMORY_LEGACY_TABLE,
            "text": HARD_LINE_TEXT,
        }
    ]
    assert [row["text"] for row in _db_rows(db, "SELECT text FROM memory_facts")] == [
        "喜欢柠檬茶",
        "用户骂了人：真是个废物",
    ]


def test_closed_state_reads_cause_no_schema_side_effects(tmp_path: Path) -> None:
    """关态三处读侧都得**零副作用**：不建总线那套表、不开新写路径。

    ``build_memory_repository`` 的 docstring 自己写「关态不建总线库、不开新连接」；
    图谱/清洗若为了能读 v21 就先把表建出来，现网库形制就被改坏了。
    """
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, [("喜欢柠檬茶", "personal"), (HARD_LINE_TEXT, "personal")])

    assert _command_bus(db, bus_enabled=False) is None
    _list_body(db)
    _graph_envelope(db)
    sanitize_memory_db(db, apply=False)
    sanitize_memory_db(db, apply=True)

    assert _db_tables(db) == [MEMORY_LEGACY_TABLE, "memory_quarantine"]


def test_shadow_reader_creates_an_empty_legacy_table(tmp_path: Path) -> None:
    """本席推荐给命令面的那枚 bus（带影子读）**有**一处副作用，登记不粉饰。

    影子读口 ``SQLiteMemoryRepository.list_rows_for_subject`` 起手
    ``_ensure_schema()`` ⇒ 纯开态的新库在被 ``记忆 list`` 读一次之后，库里会出现一张
    **空的** ``memory_facts``。不双写（零行），但「库里有没有这张表」从此不能当
    「接没接总线」的判据——判据只能是行数（上一条就是这么写的）。
    修法归禁写面（``character/memory.py`` 把读取口的 ``_ensure_schema`` 摘掉，或
    读前先探表），本席不动，移交主代理。
    """
    db = tmp_path / "memory.sqlite3"
    bus = _command_bus(db, bus_enabled=True)
    assert bus is not None
    assert MEMORY_LEGACY_TABLE not in _db_tables(db), _db_tables(db)

    assert _list_body(db, bus=bus) == "当前会话还没有可用记忆。"
    assert _db_tables(db).count(MEMORY_LEGACY_TABLE) == 1
    assert _db_rows(db, "SELECT fact_id FROM memory_facts") == []


def test_closed_state_read_of_missing_legacy_table_does_not_create_one(tmp_path: Path) -> None:
    """关态读取不建表这件事只在「表已在」时平凡成立；表不在时 v1 读取口也会建一张
    空表（既有行为，非本席引入）。这条把实况钉住，免得下轮把「表出现」当成回归。
    """
    db = tmp_path / "nothing.sqlite3"
    assert not db.exists()
    assert _list_body(db) == "当前会话还没有可用记忆。"
    assert _db_tables(db) == [MEMORY_LEGACY_TABLE]


# ---------------------------------------------------------------------------
# 2. 开态：同一句话三处各自现算得到（活性判据①）
# ---------------------------------------------------------------------------


def test_open_state_write_by_command_is_seen_by_all_three_read_sides(tmp_path: Path) -> None:
    """硬要求①：总线开着，一句话写进去，命令面/图谱/清洗**各自**都现算得到它。

    写入走命令面，顺带验到「回显的是落库真 id」那条链路。
    """
    db = tmp_path / "memory.sqlite3"
    bus = _command_bus(db, bus_enabled=True)
    assert bus is not None, "开态建不出总线：装配口本身坏了"

    fact_id = _echoed_id(_add_body(db, CLEAN_TEXT, bus=bus))
    assert fact_id.startswith("mb_"), f"开态回显的不是总线 id：{fact_id}"

    # 读侧 1：命令面列得出来，且库里真有一行（直查，不信返回值）。
    assert CLEAN_TEXT in _list_body(db, bus=bus)
    stored = _db_rows(db, "SELECT memory_id, text, status FROM memory_entries_v21")
    assert [row["text"] for row in stored] == [CLEAN_TEXT], stored
    assert stored[0]["status"] == "active"
    # 「不双写」的判据是**行数**，不是表名：影子读口 ``list_rows_for_subject`` 会
    # 顺手 ``_ensure_schema``，所以纯开态库也可能出现一张**空的** memory_facts
    # （实况见 test_shadow_reader_creates_an_empty_legacy_table）。有表无行=没双写。
    assert _db_rows(db, "SELECT fact_id FROM memory_facts") == []

    # 读侧 2：WebUI 图谱。
    nodes, edges = _graph_memories(db)
    assert nodes == [f"memory:{fact_id}"]
    assert edges == [f"person:{SENDER}->memory:{fact_id}"]

    # 读侧 3：清洗扫描面（dry-run 也得看得见，否则「扫不到」会被误报成「很干净」）。
    report = sanitize_memory_db(db, apply=False)
    assert report.scanned == 1 and report.by_table == {MEMORY_BUS_TABLE: 1}


def test_open_state_command_lists_row_written_through_the_bus_directly(tmp_path: Path) -> None:
    """命令面读的是总线**表**，不是命令自己写过的东西：absorb 直写也要列出来。"""
    db = tmp_path / "memory.sqlite3"
    bus = _command_bus(db, bus_enabled=True)
    assert bus is not None
    outcome = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="她习惯周四晚上跑步",
        session_id=PRIVATE,
        category="preference",
        source="nightly_reflection",
    )
    assert outcome.action in {"inserted", "confirmed"}, outcome

    body = _list_body(db, bus=bus)
    assert "她习惯周四晚上跑步" in body and outcome.memory_id in body


def test_open_state_legacy_rows_stay_visible_to_the_command_surface(tmp_path: Path) -> None:
    """开态不许「失忆」：旧表存量在命令面仍然列得出来。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, _CLOSED_PRIVATE_SEEDS)

    body = _list_body(db, bus=_command_bus(db, bus_enabled=True))
    for text in ("喜欢柠檬茶", "群公告周末线下聚会", "只说给机器人的私话"):
        assert text in body, f"开态命令面看不见旧行：{text}\n{body}"


def test_command_bus_without_the_shadow_reader_blindfolds_legacy_rows(tmp_path: Path) -> None:
    """装配配方**为什么**不能照抄写腿那枚 bus——实测差别，不是论述。

    ``build_memory_bus_for_writer(config)``（S-T-MEM-1 §陆② 的写法）不带
    ``legacy_explicit_reader`` ⇒ 开态 ``记忆 list`` 对着现网存量回「还没有可用
    记忆」。命令面要的是与召回同形的那枚 bus。
    """
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, _CLOSED_PRIVATE_SEEDS)
    writer_bus = build_memory_bus_for_writer(_config(db, bus_enabled=True))
    assert writer_bus is not None

    assert "还没有可用记忆" in _list_body(db, bus=writer_bus)
    assert "喜欢柠檬茶" in _list_body(db, bus=_command_bus(db, bus_enabled=True))


def test_open_state_graph_and_sanitize_read_both_tables_of_one_file(tmp_path: Path) -> None:
    """两表同库是批量读侧的前提（真身口径：召回与写入共用 ``bot_memory_db_path``）。

    混合库（旧存量 + 新总线行）里图谱与清洗都要两边都读到：图谱是管理员总览，
    清洗是「召回能读回的一切」的超集，漏一张就是假全图/假干净。
    """
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, [("旧库里说过的口味", "public")])
    _add_body(db, CLEAN_TEXT, bus=_command_bus(db, bus_enabled=True))

    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        tables = memory_store_tables(connection)
        rows = iter_stored_memory_rows(connection)

    assert tables == frozenset({MEMORY_LEGACY_TABLE, MEMORY_BUS_TABLE}), tables
    assert {row.store_table for row in rows} == tables, rows
    assert len(_graph_memories(db)[0]) == 2, _graph_memories(db)[0]
    assert sanitize_memory_db(db, apply=False).scanned == 2


def test_open_state_sanitizer_sweeps_bus_rows_and_they_stay_gone(tmp_path: Path) -> None:
    """清洗命中的总线行必须「永不复活」：墓碑先行，召回与图谱随后都读不到它。"""
    db = tmp_path / "memory.sqlite3"
    _plant_bus_row(db, "mb_hardline1", status="active", text=HARD_LINE_TEXT)

    report = sanitize_memory_db(db, apply=True)
    assert report.by_table == {MEMORY_BUS_TABLE: 1}, report
    assert report.by_category == {"minors": 1}

    assert _db_rows(db, "SELECT memory_id, status FROM memory_entries_v21") == [
        {"memory_id": "mb_hardline1", "status": "forgotten"}
    ]
    assert _db_rows(db, "SELECT memory_id, forgotten_by FROM memory_tombstones_v21") == [
        {"memory_id": "mb_hardline1", "forgotten_by": "memory_sanitize"}
    ]
    assert _db_rows(
        db, "SELECT fact_id, category, source_table FROM memory_quarantine"
    ) == [{"fact_id": "mb_hardline1", "category": "minors", "source_table": MEMORY_BUS_TABLE}]

    # 三处读侧随后都不该再看见它（墓碑 + status 双排除，与真身召回口同判据）。
    assert _graph_memories(db)[0] == []
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        assert current_memory_rows(connection) == []
    assert _list_body(db, bus=_command_bus(db, bus_enabled=True)) == "当前会话还没有可用记忆。"
    assert sanitize_memory_db(db, apply=True).quarantined == 0


def test_non_current_bus_rows_are_not_echoed_but_are_swept(tmp_path: Path) -> None:
    """``pending_review``/``superseded``：不回显（还没算数），但清洗照扫（不因状态降级）。"""
    db = tmp_path / "memory.sqlite3"
    _plant_bus_row(db, "mb_pending", status="pending_review", text=HARD_LINE_TEXT)
    _plant_bus_row(db, "mb_old", status="superseded", text="旧的称呼")

    report = sanitize_memory_db(db, apply=False)
    assert report.scanned == 2, report
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        assert [row.status for row in current_memory_rows(connection)] == []
        assert [row.status for row in iter_stored_memory_rows(connection)] == [
            "pending_review",
            "superseded",
        ]
    assert _graph_memories(db)[0] == []
    assert sanitize_memory_db(db, apply=True).quarantined == 1
    assert _db_rows(db, "SELECT memory_id, status FROM memory_entries_v21") == [
        {"memory_id": "mb_pending", "status": "forgotten"},
        {"memory_id": "mb_old", "status": "superseded"},
    ]


def test_sanitize_on_legacy_only_db_never_creates_bus_tables_even_when_applying(
    tmp_path: Path,
) -> None:
    """``_forget_bus_rows`` 只在真扫到总线行时才建 store——纯旧库跑清洗零建表。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, [("干净的偏好", "personal"), (HARD_LINE_TEXT, "personal")])

    assert sanitize_memory_db(db, apply=True).quarantined == 1
    assert _db_tables(db) == [MEMORY_LEGACY_TABLE, "memory_quarantine"]


# ---------------------------------------------------------------------------
# 3. delete 删得掉（硬要求③ + 活性判据③）
# ---------------------------------------------------------------------------


def test_delete_by_listed_id_removes_the_row_open_state(tmp_path: Path) -> None:
    """先列后删再列：真的少一条，且用的就是列表回显的那枚 id。"""
    db = tmp_path / "memory.sqlite3"
    bus = _command_bus(db, bus_enabled=True)
    _add_body(db, CLEAN_TEXT, bus=bus)
    _add_body(db, "周末要去跑步", bus=bus)

    ids = _listed_ids(_list_body(db, bus=bus))
    assert len(ids) == 2, ids

    assert _command(db, f"memory delete {ids[0]}", bus=bus).startswith("已删除记忆")
    after = _list_body(db, bus=bus)
    assert ids[0] not in after
    assert _listed_ids(after) == [ids[1]]
    statuses = {
        row["memory_id"]: row["status"]
        for row in _db_rows(db, "SELECT memory_id, status FROM memory_entries_v21")
    }
    assert statuses[ids[0]] == "forgotten"
    assert _graph_memories(db)[0] == [f"memory:{ids[1]}"]


def test_delete_by_listed_id_removes_the_row_closed_state(tmp_path: Path) -> None:
    """关态同款三步：旧路径是真 DELETE，行从库里消失。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, _CLOSED_PRIVATE_SEEDS)

    ids = _listed_ids(_list_body(db))
    assert len(ids) == 3, ids
    assert _command(db, f"memory delete {ids[0]}").startswith("已删除记忆")
    assert len(_listed_ids(_list_body(db))) == 2
    remaining = {row["fact_id"] for row in _db_rows(db, "SELECT fact_id FROM memory_facts")}
    assert ids[0] not in remaining
    assert set(ids[1:]) <= remaining


def test_self_computed_fact_id_cannot_delete_a_bus_row(tmp_path: Path) -> None:
    """前任点名的缺陷，正向证据：拿 ``build_fact_id`` 自算的 id 删不掉总线行。

    旧实现回显的正是这枚自算 id ⇒ 接上总线后 ``记忆 delete`` 永远删不掉。本席改成
    回显 ``upsert_fact`` 的返回值，这条用例就是「为什么必须那样改」的可复跑证明，
    也是注毒判据⑤的靶子（把回显改回自算 ⇒ 本条与 §3 第一条一起红）。
    """
    db = tmp_path / "memory.sqlite3"
    bus = _command_bus(db, bus_enabled=True)
    _add_body(db, CLEAN_TEXT, bus=bus)

    made_up = build_fact_id(SENDER, PRIVATE, CLEAN_TEXT)
    assert _command(db, f"memory delete {made_up}", bus=bus).startswith("未找到可删除的记忆")
    assert made_up not in _list_body(db, bus=bus)
    assert CLEAN_TEXT in _list_body(db, bus=bus)

    real_id = _listed_ids(_list_body(db, bus=bus))[0]
    assert real_id != made_up
    assert _command(db, f"memory delete {real_id}", bus=bus).startswith("已删除记忆")


def test_add_echoes_the_stored_id_in_both_states(tmp_path: Path) -> None:
    """两态回显都等于「库里真有的那枚 id」——关态逐字节不变，开态换形不换据。"""
    db_closed = tmp_path / "closed.sqlite3"
    closed_body = _add_body(db_closed, CLEAN_TEXT)
    assert _echoed_id(closed_body) == build_fact_id(SENDER, PRIVATE, CLEAN_TEXT)
    assert closed_body == (
        f"已记住：{CLEAN_TEXT}\nfact_id={build_fact_id(SENDER, PRIVATE, CLEAN_TEXT)}\n"
        "sensitivity=personal"
    )

    db_open = tmp_path / "open.sqlite3"
    bus = _command_bus(db_open, bus_enabled=True)
    echoed = _echoed_id(_add_body(db_open, CLEAN_TEXT, bus=bus))
    stored = [row["memory_id"] for row in _db_rows(db_open, "SELECT memory_id FROM memory_entries_v21")]
    assert stored == [echoed], (stored, echoed)


# ---------------------------------------------------------------------------
# 4. 隐私红线（硬要求④）
# ---------------------------------------------------------------------------


def test_credentialed_rows_never_echo_in_either_state(tmp_path: Path) -> None:
    """凭证级条目不进任何读侧回显：命令面两态、图谱两态。

    ⚠ **这是相对 HEAD 的有意收紧，不是保持原样**：旧代码私聊面
    （``allowed_sensitivities is None``）对 credentialed 逐字外显，图谱压根没读
    sensitivity 列。收紧理由是硬要求④；行本身不删不动（下一条锁着）。
    """
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, [("某个服务口令", "credentialed"), ("可见的偏好", "public")])
    visible_id = build_fact_id(SENDER, PRIVATE, "可见的偏好")

    private_body = _list_body(db)
    assert "某个服务口令" not in private_body
    assert "可见的偏好" in private_body
    assert _graph_memories(db)[0] == [f"memory:{visible_id}"]

    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        rows = iter_stored_memory_rows(connection)
    assert [row.sensitivity for row in rows] == ["credentialed", "public"]
    assert [row.text for row in echo_safe_rows(rows)] == ["可见的偏好"]

    bus = _command_bus(db, bus_enabled=True)
    echoed = _echoed_id(_add_body(db, "另一个服务口令", sensitivity="credentialed", bus=bus))
    assert is_echo_safe_sensitivity("credentialed") is False
    assert "另一个服务口令" not in _list_body(db, bus=bus)
    assert echoed not in _graph_memories(db)[0]
    # 行确实落库了（只是不回显）——清洗面还照扫它。
    assert echoed in [row["memory_id"] for row in _db_rows(db, "SELECT memory_id FROM memory_entries_v21")]


def test_credentialed_row_is_still_physically_stored(tmp_path: Path) -> None:
    """不外露 ≠ 删除：回显闸只挡展示，不悄悄改数据。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, [("某个服务口令", "credentialed")])
    _list_body(db)
    _graph_memories(db)
    assert [row["text"] for row in _db_rows(db, "SELECT text FROM memory_facts")] == [
        "某个服务口令"
    ]


def test_group_written_memory_is_not_readable_in_another_group_or_private(tmp_path: Path) -> None:
    """跨作用域负样本（活性判据④，开态）：群 A 写的行不得在群 B / 私聊读出来。"""
    db = tmp_path / "memory.sqlite3"
    bus = _command_bus(db, bus_enabled=True)
    assert bus is not None
    added = _add_body(db, "群 A 内部公告", session_id=GROUP_A, sensitivity="public", bus=bus)
    fact_id = _echoed_id(added)
    assert added.startswith("已记住"), added

    assert "群 A 内部公告" in _list_body(db, session_id=GROUP_A, bus=bus)
    assert "群 A 内部公告" not in _list_body(db, session_id=GROUP_B, bus=bus)
    assert "群 A 内部公告" not in _list_body(db, session_id=PRIVATE, bus=bus)
    assert fact_id not in _list_body(db, session_id=GROUP_B, bus=bus)
    # 图谱是管理员全局视图（不分会话），所以它**该**看见这一行——但看见的是本人
    # 名下的一条记忆，不是别的群的私话；这里锁它确实读到了总线行。
    assert _graph_memories(db)[0] == [f"memory:{fact_id}"]


def test_another_sender_cannot_read_my_memory_in_either_state(tmp_path: Path) -> None:
    """per-sender 归属两态都锁得住：换个人列就是空。"""
    db = tmp_path / "memory.sqlite3"
    bus = _command_bus(db, bus_enabled=True)
    _add_body(db, CLEAN_TEXT, bus=bus)
    assert _list_body(db, bus=bus, sender_id=OTHER_SENDER) == "当前会话还没有可用记忆。"
    assert CLEAN_TEXT in _list_body(db, bus=bus)

    db_legacy = tmp_path / "legacy.sqlite3"
    _seed_legacy(db_legacy, _CLOSED_PRIVATE_SEEDS)
    assert _list_body(db_legacy, sender_id=OTHER_SENDER) == "当前会话还没有可用记忆。"
    assert len(_listed_ids(_list_body(db_legacy))) == 3


def test_other_sender_cannot_delete_my_fact_in_either_state(tmp_path: Path) -> None:
    """删别人的记忆必须失败（两态）：真 id 也一样删不动，不是「删得掉但删错人」。"""
    db_legacy = tmp_path / "legacy.sqlite3"
    _seed_legacy(db_legacy, _CLOSED_PRIVATE_SEEDS)
    victim_id = _listed_ids(_list_body(db_legacy))[0]
    refused = route_memory_command(
        f"memory delete {victim_id}",
        sender_id=OTHER_SENDER,
        session_id=PRIVATE,
        db_path=db_legacy,
    ).body
    assert refused.startswith("未找到可删除的记忆"), refused
    assert victim_id in _list_body(db_legacy)

    db_bus = tmp_path / "bus.sqlite3"
    bus = _command_bus(db_bus, bus_enabled=True)
    victim_on_bus = _echoed_id(_add_body(db_bus, CLEAN_TEXT, bus=bus))
    refused_on_bus = route_memory_command(
        f"memory delete {victim_on_bus}",
        sender_id=OTHER_SENDER,
        session_id=PRIVATE,
        db_path=db_bus,
        bus=bus,
    ).body
    assert refused_on_bus.startswith("未找到可删除的记忆"), refused_on_bus
    assert [row["status"] for row in _db_rows(db_bus, "SELECT status FROM memory_entries_v21")] == [
        "active"
    ]


# ---------------------------------------------------------------------------
# 5. 中央入口结构锁（硬要求②：判定只有一处，读侧不各写一遍 if）
# ---------------------------------------------------------------------------

_CONSUMER_FILES = (
    PLUGIN_ROOT / "domains/chat_reply/capabilities/memory.py",
    PLUGIN_ROOT / "control_plane/webui_memory_graph.py",
    PLUGIN_ROOT / "domains/chat_reply/security/memory_sanitize.py",
)
_BUS_SWITCH_MARKERS = ("bot_memory_bus_enabled", "settings_from_config", "BusSettings")
_PROJECTION_NAMES = frozenset(
    {
        "iter_stored_memory_rows",
        "current_memory_rows",
        "memory_store_tables",
        "memory_tables_with_columns",
    }
)


def test_no_read_side_consumer_re_reads_the_bus_switch() -> None:
    """三处读侧一律不判开关——判定唯一住在装配口 ``memory_bus_v2.build_memory_bus``。

    执法的是本仓自己写进 docstring 的那个病灶：「同一份开关在两层各判一次而漂移」。
    消费面一旦自己读 ``bot_memory_bus_enabled``，装配层换形状它就跟着错。
    """
    offenders: list[str] = []
    for path in _CONSUMER_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Attribute):
                names.append(node.attr)
            elif isinstance(node, ast.Name):
                names.append(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.append(node.value)
            for name in names:
                if any(marker in name for marker in _BUS_SWITCH_MARKERS):
                    offenders.append(f"{path.name}:{getattr(node, 'lineno', 0)}:{name}")
    assert offenders == [], f"读侧长出了第二套开关判定：{offenders}"


def test_bulk_read_side_projection_is_defined_exactly_once() -> None:
    """批量读侧投影只有一个定义，且两个批量消费面都 import 它（不各写一遍 SELECT）。"""
    definitions: list[str] = []
    importers: set[str] = set()
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(PLUGIN_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in _PROJECTION_NAMES:
                definitions.append(f"{relative}:{node.name}")
            if (
                isinstance(node, ast.ImportFrom)
                and (node.module or "").endswith("capabilities.memory")
                and {alias.name for alias in node.names}
                & (_PROJECTION_NAMES - {"memory_store_tables"})
            ):
                importers.add(relative)
    assert len(definitions) == len(_PROJECTION_NAMES), f"投影被抄成了多份：{definitions}"
    assert importers >= {
        "control_plane/webui_memory_graph.py",
        "domains/chat_reply/security/memory_sanitize.py",
    }, f"批量消费面没走中央入口：{sorted(importers)}"


def test_no_consumer_holds_its_own_sql_against_the_fact_tables() -> None:
    """两张记忆表的 SQL 只在真身里：消费面一处都不留。

    允许清单= v1 真身 ``character/memory.py`` 与 v2 真身
    ``character/memory_store_v21.py``。图谱与清洗只能经投影拿行；命令面只能经
    ``SQLiteMemoryRepository(bus=…)``。

    判据是「语句**指向**这两张表」（FROM/INTO/UPDATE 后面的表名），不是「字符串里
    提到过」——``domains/ops/smoke/diagnostics.py`` 的 ``runtime_diagnostics`` 有
    一列就叫 ``memory_facts``，按后者判会假报（本席第一版就是这么写的）。
    """
    allowed = {
        "domains/chat_reply/character/memory.py",
        "domains/chat_reply/character/memory_store_v21.py",
    }
    heads = ("SELECT", "INSERT", "UPDATE", "DELETE")
    offenders: list[str] = []
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        relative = path.relative_to(PLUGIN_ROOT).as_posix()
        if relative in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            statement = node.value.lstrip()
            if not statement.startswith(heads):
                continue
            for table in (MEMORY_LEGACY_TABLE, MEMORY_BUS_TABLE):
                if re.search(rf"\b(?:FROM|INTO|UPDATE)\s+{table}\b", statement):
                    offenders.append(f"{relative}:{node.lineno}")
                    break
    assert offenders == [], f"记忆表 SQL 长出第二处持有者：{offenders}"


def test_projection_skips_tables_that_cannot_be_rendered(tmp_path: Path) -> None:
    """列不齐的表整张跳过（不拿默认值糊一行=不造数），并如实报「无可渲染表」。"""
    db = tmp_path / "half.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE memory_facts (fact_id TEXT PRIMARY KEY, text TEXT)")
        connection.execute("INSERT INTO memory_facts VALUES ('f1', '半张表')")
        connection.row_factory = sqlite3.Row
        assert memory_store_tables(connection) == frozenset({MEMORY_LEGACY_TABLE})
        assert memory_tables_with_columns(connection) == frozenset()
        assert iter_stored_memory_rows(connection) == []
        loose = {MEMORY_LEGACY_TABLE: frozenset({"fact_id", "text"})}
        assert memory_tables_with_columns(connection, minimum_columns=loose) == frozenset(
            {MEMORY_LEGACY_TABLE}
        )
        rows = iter_stored_memory_rows(connection, minimum_columns=loose)
    assert [row.text for row in rows] == ["半张表"]
    assert rows[0].subject_user_id == "" and rows[0].status == "active"
    # 图谱面（严格列集）对这种库如实 unreadable，不造空图。
    assert _graph_envelope(db)["data"]["sources"]["memory"] == "unreadable"


def test_projection_reports_missing_memory_store_honestly(tmp_path: Path) -> None:
    """一个文件库都没有 = 图谱 missing；有文件没表 = unreadable（都不崩、不造数）。"""
    absent = tmp_path / "absent.sqlite3"
    envelope = _graph_envelope(absent)
    assert envelope["data"]["sources"]["memory"] == "missing"
    assert envelope["status"] == "source_unavailable"

    empty = tmp_path / "empty.sqlite3"
    empty.touch()
    assert _graph_envelope(empty)["data"]["sources"]["memory"] == "unreadable"
    assert sanitize_memory_db(empty, apply=False).scanned == 0


# ---------------------------------------------------------------------------
# 6. 装配可达性（本席禁写根文件 ⇒ 挂账，摘牌信号=XPASS）
# ---------------------------------------------------------------------------


def _root_call_site_kwargs() -> list[str]:
    tree = ast.parse((PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "route_memory_command"
        ):
            return [str(keyword.arg) for keyword in node.keywords]
    return []


@pytest.mark.xfail(
    strict=False,
    reason=(
        "S-T-MEM-4 §需要主代理代接：根 __init__ 的 route_memory_command 调用点还没传 "
        "bus= ⇒ 开态命令面永远走旧路径，新抽取的行列不出来。落码后本条转 XPASS，请摘标记。"
    ),
)
def test_root_assembly_passes_a_bus_to_the_memory_command() -> None:
    kwargs = _root_call_site_kwargs()
    assert kwargs, "根装配里找不到 route_memory_command 调用点：判据本身失效"
    assert "bus" in kwargs, f"命令面没接到总线：{kwargs}"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "S-T-MEM-4 §需要主代理代接：bus 必须是**带影子读的召回同形**那枚"
        "（build_memory_bus + legacy_explicit_reader_for）。照抄写腿配方会让开态 "
        "记忆 list 对存量失忆——实测差别见 test_command_bus_without_the_shadow_reader_…"
    ),
)
def test_root_assembly_wires_the_shadow_reader_for_the_command_surface() -> None:
    text = (PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "legacy_explicit_reader_for" in text, "命令面接的是写腿 bus ⇒ 开态看不见旧表存量"


# ---------------------------------------------------------------------------
# 7. 旧表行的跨会话可见性（本席现算挂账 → 同波 S-T-MEM-5 已在真身收口，摘牌转正面锁）
# ---------------------------------------------------------------------------
#
# 本席开工时现算出的开闸阻断项：真身 ``MemoryBus._legacy_explicit_rows`` 把旧库行
# 一律标成 ``scope_kind=global`` 直接并池 ⇒ 开总线之后私聊写的旧行在**任意群**都能
# 被召回（v1 旧路径靠 SQL 的 ``session_id`` 等值挡着，开闸反而把这道闸拆了）。当时
# 以 ``xfail`` 挂账 + 一条正向证据用例钉住实况。同波 S-T-MEM-5 在禁写面收口（该件
# docstring 现写明「可见性与 v1 召回腿同宽、绝不更宽」），本席 15:5xZ 现算复核：
# 泄漏不复现 ⇒ **摘掉 xfail，改成正面常驻锁**（挂账不许在修好之后继续躺在账上，
# 也不许留一条只测「不存在」的 xfail 当功）。


def _recall_texts(db: Path, session_id: str, bus: MemoryBus) -> list[str]:
    facts = MemoryBusProvider(bus).retrieve(
        request_id="req-probe",
        requester_id=SENDER,
        subject_user_id=SENDER,
        session_id=session_id,
        query_text="",
        max_items=5,
        max_chars=1200,
    ).facts
    return [str(fact["text"]) for fact in facts]


def test_legacy_private_row_is_not_recallable_in_a_group_when_the_bus_is_on(
    tmp_path: Path,
) -> None:
    """开态隐私闸（正面锁）：私聊旧行不得进任何群的召回池。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, [("我只在私聊说过的住址", "personal")], session_id=PRIVATE)
    bus = _command_bus(db, bus_enabled=True)
    assert bus is not None

    assert _recall_texts(db, GROUP_A, bus) == []
    assert _recall_texts(db, GROUP_B, bus) == []
    # 同宽不等于更窄：本会话仍然召得回，别把闸做成「旧行全体失忆」。
    assert _recall_texts(db, PRIVATE, bus) == ["我只在私聊说过的住址"]
    assert "我只在私聊说过的住址" in _list_body(db, session_id=PRIVATE, bus=bus)


def test_legacy_group_row_stays_in_its_own_group_when_the_bus_is_on(tmp_path: Path) -> None:
    """群 A 写的旧行只在群 A 召得回；跨群、跨到私聊都不给。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, [("群 A 里说过的话", "group")], session_id=GROUP_A)
    bus = _command_bus(db, bus_enabled=True)
    assert bus is not None

    assert _recall_texts(db, GROUP_A, bus) == ["群 A 里说过的话"]
    assert _recall_texts(db, GROUP_B, bus) == []
    assert _recall_texts(db, PRIVATE, bus) == []


def test_closed_state_group_still_cannot_read_private_session_rows(tmp_path: Path) -> None:
    """关态那道闸一字未动（回归地板）：换会话读就是空。"""
    db = tmp_path / "memory.sqlite3"
    _seed_legacy(db, [("我只在私聊说过的住址", "personal")], session_id=PRIVATE)

    assert _list_body(db, session_id=GROUP_A) == "群聊中没有可公开查看的记忆；请在私聊中查看个人记忆。"
    assert "我只在私聊说过的住址" in _list_body(db, session_id=PRIVATE)
