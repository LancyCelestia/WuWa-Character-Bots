"""需求 11 记忆总线**消费腿**门（S-T-MEM-5）：读路径过总线一次，旧路 fail-open。

要判的病（不是「总线存不存在」，而是「用户看到的那几句是谁排的序」）：
打分召回 ``MemoryBus.recall`` 此前只在总线开闸时才是读路径的一环，而合并层
``_MergedMemoryProvider`` 会把「总线排过一遍」与「反思腿排过一遍」的两批结果
按 **provider 列表顺序**抢同一份预算——跨来源从不比分，高分旧事实会被低分新事实
挤掉；且任一路抛错时 ``except: continue`` **静默吞掉**，症状无法归因。

判据取向：

- **活性判据**：断言一律走装配口 ``build_memory_read_provider`` 构造的 provider 的
  ``retrieve``（真读路径），不直调 ``MemoryBus.recall`` 自证。
- **直查库文件**：候选是否并池、降级是否留痕，全部另开连接查 ``memory_entries_v21``
  / ``memory_recall_audit_v21``，不看返回值自我声明（台账 #50「存在性糊过活性判据」）。
- **关态同形**：同一份夹具下「本席闸门给出的合并层」与「今日字面形态的合并层」
  取数与渲染**逐字节相等**；另配正向对照，防两态本来就一样导致等值断言空跑。
- **时钟注入**：总线钟经 ``_utc_now`` 打桩定值，年龄差靠 backdate 真实列值制造。
- 全离线，库文件只在 ``tmp_path``，绝不碰 ``ChatBot_Runtime/``。
"""

from __future__ import annotations

import ast
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 as bus_mod
from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    SQLiteMemoryRepository,
    build_memory_read_path,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    DEGRADED_REASON_BUS_RECALL_FAILED,
    DEGRADED_REASON_LEGACY_NEWEST_N,
    MemoryBus,
    build_memory_bus,
    legacy_session_visible,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
    MemoryStoreV21,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    MEMORY_TRUNCATION_FACT_ID,
    REFLECTED_CANDIDATE_SOURCE,
    _filter_llm_safe_memory_results,
    _MergedMemoryProvider,
    _render_memory_results_with_kind_labels,
    build_memory_read_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reflection import (
    ReflectionStore,
    build_reflection_memory_provider,
)

PROVIDERS_PY = Path("plugins/bot_unified_runtime/domains/chat_reply/character/providers.py")
ROOT_INIT = Path("plugins/bot_unified_runtime/__init__.py")

SENDER = "3865067623"
OTHER = "1722380002"
GROUP_A = "group_1108838060_3865067623"
GROUP_B = "group_631785829_3865067623"
FIXED_NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


class _Config:
    """读路径要现读的键（生产缺省见 config.py：总线关、归纳落 legacy）。"""

    bot_memory_enabled = True
    bot_memory_db_path = ""
    bot_memory_max_items = 5
    bot_memory_max_chars = 1200
    bot_memory_bus_enabled = False
    bot_memory_reflected_write_target = "legacy"
    bot_memory_strength_k = 3.0
    bot_memory_tau_stable_days = 180
    bot_memory_tau_seasonal_days = 45
    bot_memory_tau_episodic_days = 14
    bot_memory_relevance_weights = ""
    bot_memory_per_category_max = 1
    bot_memory_semantic_recall_enabled = True
    bot_reflection_enabled = True
    bot_reflection_db_path = ""


class _BusOn(_Config):
    bot_memory_bus_enabled = True


class _BusOnWritesToBus(_BusOn):
    bot_memory_reflected_write_target = "bus"


class _ReflectionOff(_BusOn):
    bot_reflection_enabled = False


def _clock() -> datetime:
    return FIXED_NOW


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _days_ago(days: int) -> str:
    return _iso(FIXED_NOW - timedelta(days=days))


def _config_for(cls: type[_Config], tmp_path: Path) -> _Config:
    config = cls()
    config.bot_memory_db_path = str(tmp_path / "memory.sqlite3")
    config.bot_reflection_db_path = str(tmp_path / "reflection.sqlite3")
    return config


def _read_provider(config: _Config, monkeypatch: pytest.MonkeyPatch) -> _MergedMemoryProvider:
    """走生产装配口（总线钟打桩定值 ⇒ 断言不挂墙上时钟）。"""
    monkeypatch.setattr(bus_mod, "_utc_now", _clock)
    provider = build_memory_read_provider(config)
    assert isinstance(provider, _MergedMemoryProvider)
    return provider


def _bus(db: Path) -> MemoryBus:
    config = _BusOn()
    config.bot_memory_db_path = str(db)
    bus = build_memory_bus(config, clock=_clock)
    assert bus is not None
    return bus


def _backdate(store: MemoryStoreV21, memory_id: str, moment: datetime) -> None:
    """把一条总线行推到过去（created/last_confirmed 同推，否则 recency 与 strength 不动）。"""
    connection = store.connection
    connection.execute(
        "UPDATE memory_entries_v21 SET created_at = ?, last_confirmed_at = ?,"
        " first_seen_at = ?, updated_at = ? WHERE memory_id = ?",
        (_iso(moment), _iso(moment), _iso(moment), _iso(moment), memory_id),
    )
    connection.commit()


def _seed_memory_facts(db: Path, rows: list[tuple[str, str, str, str, str]]) -> None:
    """旧显式库 ``memory_facts`` 直插：(fact_id, 主体, 会话, 正文, updated_at)。

    走裸 SQL 而不是 ``upsert_fact``——后者用墙上时钟写时间戳，本件要的是可控年龄差。
    建表仍借仓储的 schema 入口，不在此抄一份 DDL。
    """
    SQLiteMemoryRepository(db)._ensure_schema()
    with sqlite3.connect(db) as connection:
        connection.executemany(
            """
            INSERT INTO memory_facts (
                fact_id, subject_user_id, session_id, memory_kind, text,
                confidence, source, sensitivity, scope_key, created_at, updated_at
            ) VALUES (?, ?, ?, 'preference', ?, 0.9, 'manual', 'personal', '', ?, ?)
            """,
            [
                (fact_id, owner, session, text, moment, moment)
                for fact_id, owner, session, text, moment in rows
            ],
        )
        connection.commit()


def _seed_reflection_facts(db: Path, rows: list[tuple[str, str, str, str]]) -> None:
    """旧归纳库 ``reflection_facts`` 直插：(fact_id, sender, session_key, 正文)。"""
    ReflectionStore(db)
    with sqlite3.connect(db) as connection:
        connection.executemany(
            """
            INSERT INTO reflection_facts (
                fact_id, sender_id, session_key, fact_text, category,
                confidence, source_digest_id, created_at, superseded
            ) VALUES (?, ?, ?, ?, 'preference', 0.8, 'dig_x', ?, 0)
            """,
            [
                (fact_id, sender, session, text, _days_ago(3))
                for fact_id, sender, session, text in rows
            ],
        )
        connection.commit()


def _texts(facts: list[dict[str, str]]) -> list[str]:
    return [str(fact.get("text", "")) for fact in facts]


def _retrieved(provider: _MergedMemoryProvider, query: str, **kw: Any) -> Any:
    return provider.retrieve(
        request_id=kw.pop("request_id", "req-1"),
        requester_id=kw.pop("requester_id", SENDER),
        subject_user_id=kw.pop("subject_user_id", SENDER),
        session_id=kw.pop("session_id", GROUP_A),
        query_text=query,
        max_items=kw.pop("max_items", 5),
        max_chars=kw.pop("max_chars", 1200),
    )


def _rendered(result: Any) -> str:
    """本轮真正进 prompt 的那段文本。

    格式**不在本件里另抄一份**：直接调唯一消费者 ``capabilities/chat.py`` 的
    ``_memory_lines``（先例：``tests/test_persona_prompt_and_memory.py`` 同法 import
    chat 侧私有件）。 duck-typed 的 ``SimpleNamespace`` 只喂它读的那一个属性
    ``memory_results``；换 chat 侧格式不需改本件，正是「一处变更处处跟随」。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        _memory_lines,
    )

    rendered = _render_memory_results_with_kind_labels(
        _filter_llm_safe_memory_results(result), max_chars=1200
    )
    return _memory_lines(SimpleNamespace(memory_results=rendered))


def _tables(db: Path) -> list[str]:
    if not db.exists():
        return []
    with sqlite3.connect(db) as connection:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]


# ---------------------------------------------------------------- 1. 唯一打分器


def test_gate_uses_one_ranker_when_the_bus_is_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """开态：合并层只剩一条腿，反思旧表并进同一打分池而不是另排一遍。"""
    config = _config_for(_BusOn, tmp_path)
    _seed_reflection_facts(
        Path(config.bot_reflection_db_path),
        [(  "rf_a", SENDER, GROUP_A, "我最近爱上柠檬茶")],
    )
    provider = _read_provider(config, monkeypatch)
    assert len(provider._providers) == 1
    assert provider.recall_mode == "memory_bus"
    assert provider._providers[0].bus.candidate_source_names() == (
        REFLECTED_CANDIDATE_SOURCE,
    )


def test_gate_does_not_fold_reflections_that_already_live_in_the_bus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """归纳已落总线时不再并旧表：同一条事实不得以两个身份进同一个池。"""
    config = _config_for(_BusOnWritesToBus, tmp_path)
    _seed_reflection_facts(
        Path(config.bot_reflection_db_path),
        [("rf_a", SENDER, GROUP_A, "我最近爱上柠檬茶")],
    )
    provider = _read_provider(config, monkeypatch)
    assert provider._providers[0].bus.candidate_source_names() == ()


def test_gate_keeps_two_legs_and_old_shape_when_the_bus_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config_for(_Config, tmp_path)
    provider = _read_provider(config, monkeypatch)
    assert len(provider._providers) == 2
    assert provider.recall_mode == DEGRADED_REASON_LEGACY_NEWEST_N
    assert all(getattr(leg, "bus", None) is None for leg in provider._providers)
    _retrieved(provider, "柠檬茶")
    # 关态不建总线库、不开新表（逐字节旧行为的物理面）
    assert "memory_entries_v21" not in _tables(Path(config.bot_memory_db_path))


def test_reflection_gate_agrees_with_the_leg_builders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两处反思门必须一致：本席的折叠源与反思腿自己的启停判据。

    折叠判据住在装配层、启停判据住在 ``reflection.build_reflection_memory_provider``
    ——两处若漂移就会出现「两条腿都在排」或「一条都没有」。共享真身做不到的话，
    至少要有这把一致性锁。
    """
    enabled_config = _config_for(_BusOn, tmp_path)
    disabled_config = _config_for(_ReflectionOff, tmp_path)
    disabled_config.bot_reflection_db_path = ""
    assert enabled_config.bot_reflection_enabled is True
    assert disabled_config.bot_reflection_enabled is False or disabled_config.bot_reflection_db_path == ""

    provider = _read_provider(enabled_config, monkeypatch)
    assert provider._providers[0].bus.candidate_source_names() == (
        REFLECTED_CANDIDATE_SOURCE,
    )
    off_provider = _read_provider(disabled_config, monkeypatch)
    assert off_provider._providers[0].bus.candidate_source_names() == ()


def test_merge_layer_is_never_constructed_outside_the_gate() -> None:
    """AST 锁：合并层只有 ``build_memory_read_provider`` 内两处构造点（开/关各一）。

    「谁排序」全仓只有一个决定点；生产根若出现第二处构造 = 第二条通路
    （台账 #49「禁第二真身」同族）。
    """
    tree = ast.parse(PROVIDERS_PY.read_text(encoding="utf-8"))
    gate = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_memory_read_provider"
    )
    gate_calls = {
        id(call)
        for call in ast.walk(gate)
        if isinstance(call, ast.Call)
        and getattr(call.func, "id", "") == "_MergedMemoryProvider"
    }
    all_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and getattr(call.func, "id", "") == "_MergedMemoryProvider"
    ]
    assert len(all_calls) == 2, all_calls
    assert {id(call) for call in all_calls} == gate_calls
    assert "_MergedMemoryProvider" not in ROOT_INIT.read_text(encoding="utf-8")


def test_read_path_returns_primary_and_fallback_only_when_the_bus_is_on(
    tmp_path: Path,
) -> None:
    """``build_memory_read_path`` 的配对语义：关态无兜底腿，开态兜底腿=旧仓储。"""
    off = _config_for(_Config, tmp_path)
    primary, fallback = build_memory_read_path(off)
    assert isinstance(primary, SQLiteMemoryRepository)
    assert primary.recall_mode == DEGRADED_REASON_LEGACY_NEWEST_N
    assert fallback is None

    on = _config_for(_BusOn, tmp_path)
    primary, fallback = build_memory_read_path(on)
    assert isinstance(primary, bus_mod.MemoryBusProvider)
    assert primary.recall_mode == "memory_bus"
    assert isinstance(fallback, SQLiteMemoryRepository)
    assert fallback.recall_mode == DEGRADED_REASON_LEGACY_NEWEST_N


# ---------------------------------------------------------------- 2. 相关性胜新近


def test_relevant_oldest_fact_wins_over_irrelevant_newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**故意让正确答案是最老那一行**（抓到上一个 bug 的那类夹具）。"""
    db = tmp_path / "memory.sqlite3"
    bus = _bus(db)
    old = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我喜欢柠檬茶",
        session_id=GROUP_A,
        category="preference",
        source_event_id="e_old",
    ).memory_id
    mid = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我在学手风琴",
        session_id=GROUP_A,
        category="preference",
        source_event_id="e_mid",
    ).memory_id
    newest = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我换了手机型号",
        session_id=GROUP_A,
        category="preference",
        source_event_id="e_new",
    ).memory_id
    store = MemoryStoreV21(str(db))
    _backdate(store, old, FIXED_NOW - timedelta(days=900))
    _backdate(store, mid, FIXED_NOW - timedelta(days=30))
    _backdate(store, newest, FIXED_NOW - timedelta(days=1))

    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)
    assert _texts(_retrieved(provider, "柠檬茶", max_items=1).facts) == ["我喜欢柠檬茶"]
    # 零相关地板：有相关项时，无关的新一律出局（不是「排后面」而是根本不注入）。
    assert _texts(_retrieved(provider, "柠檬茶").facts) == ["我喜欢柠檬茶"]
    # 同一条数据只换查询 ⇒ 答案跟着查询走（不是「永远同几句」）。
    assert _texts(_retrieved(provider, "手风琴").facts) == ["我在学手风琴"]


def test_bus_off_newest_wins_proving_the_two_states_differ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关态同一夹具给的是「最近一条」——正证开/关两态行为不同（防空跑等值）。"""
    db = tmp_path / "memory.sqlite3"
    _seed_memory_facts(
        db,
        [
            ("fact_old", SENDER, GROUP_A, "我喜欢柠檬茶", _days_ago(900)),
            ("fact_new", SENDER, GROUP_A, "我换了手机型号", _days_ago(1)),
        ],
    )
    off_config = _config_for(_Config, tmp_path)
    off_config.bot_memory_db_path = str(db)
    assert _texts(_retrieved(_read_provider(off_config, monkeypatch), "柠檬茶", max_items=1).facts) == [
        "我换了手机型号"
    ]

    on_config = _config_for(_BusOn, tmp_path)
    on_config.bot_memory_db_path = str(db)
    assert _texts(_retrieved(_read_provider(on_config, monkeypatch), "柠檬茶", max_items=1).facts) == [
        "我喜欢柠檬茶"
    ]


def test_prompt_memories_are_exactly_the_set_the_bus_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**归因正面锁**：进 prompt 的那几条，必须逐字等于总线审计 `selected_json` 记的那几条。

    这是「总线就是产出者」唯一的可证形态：
    - 多一条 ⇒ 合并层之外还有第二处在往 prompt 塞记忆（第二打分器回潮）；
    - 少一条 ⇒ 中间有人换了口径却不记账（预算/渲染层吞账）；
    - id 集合对不上 ⇒ 「打了分」与「被注入」是两件事，分数再好也不改模型看到的字。

    夹具里**旧 `memory_facts` 也埋一条**（经总线的影子读并池，id 形如
    ``legacy:…``）：只喂总线表的话，「再并列一条未打分的旧腿」这种回潮注毒
    第二腿取到空集、等值照样成立——本席第一发 M8 就是这么空过的，补上才有牙。
    总条数刻意压在 ``max_items=5`` 之下：合并层再裁一刀会让两侧天然不等。
    """
    db = tmp_path / "memory.sqlite3"
    bus = _bus(db)
    for text, event in (
        ("我喜欢柠檬茶", "e_a"),
        ("我在学手风琴", "e_b"),
    ):
        bus.absorb(
            owner_id=SENDER,
            subject_user_id=SENDER,
            text=text,
            session_id=GROUP_A,
            category="preference",
            source_event_id=event,
        )
    _seed_memory_facts(
        db,
        [
            ("fact_legacy_a", SENDER, GROUP_A, "我最近迷上手风琴", _days_ago(3)),
        ],
    )
    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)

    for query in ("柠檬茶", "手风琴"):
        result = _retrieved(provider, query, request_id=f"req-{query}")
        served = [
            str(fact.get("fact_id") or "")
            for fact in result.facts
            if str(fact.get("fact_id") or "") != MEMORY_TRUNCATION_FACT_ID
        ]
        audits = MemoryStoreV21(str(db)).list_recall_audits(owner_id=SENDER, limit=10)
        row = next(
            (item for item in audits if str(item.get("request_id")) == f"req-{query}"),
            None,
        )
        assert row is not None, f"本轮没有召回审计：{query} -> {audits}"
        selected = [
            str(item.get("fact_id") or "")
            for item in json.loads(str(row.get("selected_json") or "[]"))
        ]
        assert served == selected, (query, served, selected)
        assert served, (query, "两侧都空=等值断言空跑")
    # 同一份数据换查询，注入面跟着换（不是「永远同几句」）——两轮的 selected 必须不同
    first = _retrieved(provider, "柠檬茶", request_id="req-x1")
    second = _retrieved(provider, "手风琴", request_id="req-x2")
    assert _texts(first.facts) != _texts(second.facts)


def test_degraded_round_does_not_forge_a_bus_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """兜底腿顶上的那一轮，审计里 `selected_json` 必须还是空的。

    否则「总线挑了这几条」与「旧腿按时间捞了几条」在账上长得一模一样，
    事后翻审计根本无法归因——降级要留痕，但不能留**假**痕。
    """
    db = tmp_path / "memory.sqlite3"
    _bus(db).absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我喜欢柠檬茶",
        session_id=GROUP_A,
        category="preference",
        source_event_id="e_bus",
    )
    _seed_memory_facts(db, [("fact_legacy", SENDER, GROUP_A, "我住在海边", _days_ago(0))])
    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("probe: recall exploded")

    monkeypatch.setattr(MemoryBus, "recall", boom)
    result = _retrieved(provider, "海边", request_id="req-forged-check")
    assert _texts(result.facts) == ["我住在海边"], result.facts
    audits = MemoryStoreV21(str(db)).list_recall_audits(owner_id=SENDER, limit=10)
    row = next(
        item for item in audits if str(item.get("request_id")) == "req-forged-check"
    )
    assert json.loads(str(row.get("selected_json") or "[]")) == [], row
    reasons = [
        str(item.get("reason")) for item in json.loads(str(row.get("excluded_json") or "[]"))
    ]
    assert DEGRADED_REASON_BUS_RECALL_FAILED in reasons, reasons


def test_bus_off_writes_nothing_into_the_v2_store(tmp_path: Path) -> None:
    """关态必须**一片 v2 表都不建**：否则「关=逐字节旧行为」是假的（影子写仍在跑）。"""
    db = tmp_path / "memory.sqlite3"
    _seed_memory_facts(db, [("fact_a", SENDER, GROUP_A, "我喜欢柠檬茶", _days_ago(2))])
    config = _config_for(_Config, tmp_path)  # bot_memory_bus_enabled=False
    config.bot_memory_db_path = str(db)
    provider = build_memory_read_provider(config)
    served = _retrieved(provider, "柠檬茶")
    assert _texts(served.facts) == ["我喜欢柠檬茶"], served.facts
    tables = _tables(db)
    assert "memory_facts" in tables, tables
    assert not [name for name in tables if name.endswith("_v21")], tables


def test_off_leg_degradation_is_announced_once_per_library(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """关态「本轮没按话题打分」这件事必须说得出一次，且**不刷屏**。

    简报第 4 条要的「降级不许隐形」在关态的可执行形态：没有总线 ⇒ 没有审计表可写
    （上一件用例正锁着「关态不建 v2 表」），所以隐形与否只看装配期这一行。
    """
    db = tmp_path / "memory.sqlite3"
    _seed_memory_facts(db, [("fact_a", SENDER, GROUP_A, "我喜欢柠檬茶", _days_ago(2))])
    config = _config_for(_Config, tmp_path)
    config.bot_memory_db_path = str(db)
    with caplog.at_level("WARNING"):
        first = build_memory_read_provider(config)
        second = build_memory_read_provider(config)
    messages = [
        record.getMessage()
        for record in caplog.records
        if "memory recall ranker=" in record.getMessage()
    ]
    assert len(messages) == 1, messages  # 每库一次，不是每轮一次
    assert DEGRADED_REASON_LEGACY_NEWEST_N in messages[0]
    assert first.recall_mode == second.recall_mode == DEGRADED_REASON_LEGACY_NEWEST_N
    # 腿自己也必须把口径说清楚（装配层据此归因，不靠猜）
    leg = first._providers[0]
    assert leg.recall_mode == DEGRADED_REASON_LEGACY_NEWEST_N


def test_reflected_old_table_rows_are_ranked_in_the_same_pool(    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """折叠生效的活性判据：旧归纳表的一行，经总线打分后进 prompt。"""
    config = _config_for(_BusOn, tmp_path)
    _seed_reflection_facts(
        Path(config.bot_reflection_db_path),
        [("rf_a", SENDER, GROUP_A, "我最近爱上柠檬茶")],
    )
    provider = _read_provider(config, monkeypatch)
    facts = _retrieved(provider, "柠檬茶").facts
    assert _texts(facts) == ["我最近爱上柠檬茶"], facts
    assert str(facts[0]["provenance"]) == "reflected", facts[0]
    assert str(facts[0]["fact_id"]).startswith(f"{REFLECTED_CANDIDATE_SOURCE}:")
    # 审计里能看到它，且分数由总线给（不是反思腿自报）
    audits = MemoryStoreV21(config.bot_memory_db_path).list_recall_audits(
        owner_id=SENDER, limit=3
    )
    selected = json.loads(str(audits[0]["selected_json"]))
    assert [item["fact_id"] for item in selected] == ["reflected:rf_a"]


# ---------------------------------------------------------------- 3. 关态逐字节同形


def test_bus_off_rendered_output_is_byte_identical_to_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关态 = 本席开工前的字面形态：facts 与渲染串都必须逐字节相等。

    「今日形态」= 按旧构造式 ``_MergedMemoryProvider([旧仓储, 反思腿])`` 现场组装；
    「闸门形态」= ``build_memory_read_provider``。同一份库、同一组查询逐个比。
    """
    db = tmp_path / "memory.sqlite3"
    _seed_memory_facts(
        db,
        [
            ("fact_a", SENDER, GROUP_A, "我喜欢柠檬茶", _days_ago(9)),
            ("fact_b", SENDER, GROUP_A, "我住在海边", _days_ago(4)),
            ("fact_c", SENDER, "global", "我对芒果过敏", _days_ago(2)),
        ],
    )
    reflection_db = tmp_path / "reflection.sqlite3"
    _seed_reflection_facts(
        reflection_db,
        [
            ("rf_a", SENDER, GROUP_A, "用户常提到柠檬茶"),
            ("rf_b", SENDER, "global", "用户习惯夜里工作"),
        ],
    )
    config = _config_for(_Config, tmp_path)
    config.bot_memory_db_path = str(db)
    config.bot_reflection_db_path = str(reflection_db)
    monkeypatch.setattr(bus_mod, "_utc_now", _clock)

    compared = 0
    for query in ("", "柠檬茶", "海边 夜里", "完全不相干的话题"):
        for max_items in (1, 2, 5):
            today = _MergedMemoryProvider(
                [
                    SQLiteMemoryRepository(db),
                    build_reflection_memory_provider(config),
                ],
                ranker=DEGRADED_REASON_LEGACY_NEWEST_N,
            )
            gate = build_memory_read_provider(config)
            today_result = _retrieved(today, query, max_items=max_items)
            gate_result = _retrieved(gate, query, max_items=max_items)
            assert json.dumps(today_result.model_dump(), ensure_ascii=False, sort_keys=True) == (
                json.dumps(gate_result.model_dump(), ensure_ascii=False, sort_keys=True)
            ), (query, max_items)
            assert _rendered(today_result) == _rendered(gate_result), (query, max_items)
            compared += 1
    assert compared == 12
    # 至少一组查询真的产出了内容（否则「逐字节相等」可以是两个空串在自证）。
    probe = build_memory_read_provider(config)
    assert _rendered(_retrieved(probe, "柠檬茶")), "夹具没产出任何记忆行 ⇒ 等值断言空跑"


# ---------------------------------------------------------------- 4. 降级不许静默


def test_bus_exception_degrades_with_audit_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """总线抛错 ⇒ 本轮由兜底腿取数，且必须留下日志 + 一条降级审计。"""
    db = tmp_path / "memory.sqlite3"
    _bus(db).absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我喜欢柠檬茶",
        session_id=GROUP_A,
        category="preference",
        source_event_id="e_bus",
    )
    _seed_memory_facts(db, [("fact_legacy", SENDER, GROUP_A, "我住在海边", _days_ago(0))])
    provider = _read_provider(_config_for(_BusOn, tmp_path) | {}, monkeypatch) if False else None
    assert provider is None  # 占位防误用：下面按真实配置构造

    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("probe: recall exploded")

    monkeypatch.setattr(MemoryBus, "recall", boom)
    with caplog.at_level("WARNING"):
        result = _retrieved(provider, "海边", request_id="req-degraded")
    assert _texts(result.facts) == ["我住在海边"], result.facts

    audits = MemoryStoreV21(str(db)).list_recall_audits(owner_id=SENDER, limit=5)
    reasons = [
        str(item.get("reason"))
        for row in audits
        for item in json.loads(str(row.get("excluded_json") or "[]"))
    ]
    assert DEGRADED_REASON_BUS_RECALL_FAILED in reasons, audits
    assert any(str(row.get("request_id")) == "req-degraded" for row in audits), audits
    assert any("memory recall degraded" in r.getMessage() for r in caplog.records)
    assert any("served from fallback leg" in r.getMessage() for r in caplog.records)
    # 口径不被 per-request 污染：实例属性仍是装配期事实（并发会话不该互相改写）
    assert provider.recall_mode == "memory_bus"


def test_degraded_recall_still_answers_when_the_audit_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """审计写不进（库都挂了）也不许把回复带走——留痕尽力而为、回复优先。"""
    config = _config_for(_BusOn, tmp_path)
    provider = _read_provider(config, monkeypatch)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("probe: recall exploded")

    monkeypatch.setattr(MemoryBus, "recall", boom)
    monkeypatch.setattr(MemoryBus, "_write_audit", boom)
    with caplog.at_level("WARNING"):
        result = _retrieved(provider, "柠檬茶")
    assert result.facts == []
    assert any("memory degrade audit failed" in r.getMessage() for r in caplog.records)


def test_non_bus_leg_failure_is_attributed_to_that_leg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """关态反思腿故障：日志点名，但不得伪报「统一打分器挂了」（归因要分得清）。"""
    db = tmp_path / "memory.sqlite3"
    _seed_memory_facts(db, [("fact_a", SENDER, GROUP_A, "我喜欢柠檬茶", _days_ago(1))])
    provider = _read_provider(_config_for(_Config, tmp_path) | {"bot_memory_db_path": str(db)}, monkeypatch) if False else None
    assert provider is None

    config = _config_for(_Config, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)

    class _Boom:
        def retrieve(self, **kwargs: Any) -> None:
            raise RuntimeError("probe: reflection leg exploded")

    provider._providers[1] = _Boom()
    with caplog.at_level("WARNING"):
        result = _retrieved(provider, "柠檬茶")
    assert _texts(result.facts) == ["我喜欢柠檬茶"], result.facts
    messages = [r.getMessage() for r in caplog.records]
    assert any("memory recall degraded" in m for m in messages), messages
    assert not any(DEGRADED_REASON_BUS_RECALL_FAILED in m for m in messages), messages


def test_both_legs_failing_never_breaks_the_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """两路都挂 = 本轮没记忆，但对话链不断、两条故障各自留痕。"""
    db = tmp_path / "memory.sqlite3"
    _bus(db).absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我喜欢柠檬茶",
        session_id=GROUP_A,
        category="preference",
        source_event_id="e_bus",
    )
    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("probe: exploded")

    monkeypatch.setattr(MemoryBus, "recall", boom)
    monkeypatch.setattr(SQLiteMemoryRepository, "retrieve", boom)
    with caplog.at_level("WARNING"):
        result = _retrieved(provider, "柠檬茶")
    assert result.facts == []
    messages = [r.getMessage() for r in caplog.records]
    assert any("memory recall degraded" in m for m in messages), messages
    assert any("memory fallback leg also failed" in m for m in messages), messages


# ---------------------------------------------------------------- 5. 泄漏红线


@pytest.mark.parametrize(
    ("row_session", "current_session", "expected"),
    [
        (GROUP_A, GROUP_A, True),
        (GROUP_B, GROUP_A, False),
        (SENDER, GROUP_A, False),
        ("", GROUP_A, True),
        ("global", GROUP_A, True),
        ("*", GROUP_A, True),
        (GROUP_A, "", False),  # 本轮无会话键：只见全局行（fail-closed）
        ("group_1_2", "group_1X2", False),  # 绝不做前缀/通配式包含
    ],
)
def test_legacy_session_visibility_matches_v1(
    row_session: str, current_session: str, expected: bool
) -> None:
    assert legacy_session_visible(row_session, current_session) is expected


# 生产现算（2026-09-26 只读普查 ``ChatBot_Runtime/data/``）：
#   reflection_facts.session_key  去重 35 键 / 112 行 —— **100% 复合形** ``qq:…``
#   memory_facts.session_id       去重 39 键 / 376 行 —— 全裸键（group_…_… 276、
#                                 裸 uid 99、private_… 1），一枚复合形都没有
#   conversation_turns.platform   qq 5413 / console 85 / telegram 66 / email 15
# ⇒ 折叠闸只认裸键等值 = 把注入方 ``facts_for`` 已放行的整表再拒一次；而只测裸键
#   的夹具全绿（S-T-MEMKEY-1）。两档宽度按来源各自给定，见下面的逐字同宽锁。
_COMPOSITE_GROUP_A = f"qq:{GROUP_A}"
_COMPOSITE_GROUP_B = f"qq:{GROUP_B}"
_COMPOSITE_PRIVATE = f"qq:{SENDER}"
_COMPOSITE_REPL = "console:console:repl"


@pytest.mark.parametrize(
    ("row_session", "current_session", "expected"),
    [
        # 修复的本体：生产复合形必须进池（第一档 target=legacy 的唯一读路）。
        (_COMPOSITE_GROUP_A, GROUP_A, True),
        (f"telegram:{GROUP_A}", GROUP_A, True),
        (_COMPOSITE_REPL, "console:repl", True),
        (_COMPOSITE_GROUP_B, GROUP_A, False),  # 甲群 ⇄ 乙群
        (_COMPOSITE_GROUP_A, GROUP_B, False),  # 反向亦然
        (_COMPOSITE_REPL, GROUP_A, False),  # 别的会话的复合形照旧不认
        # 红线：私聊复合形不得折进群本轮键（尾巴前一位是 ``_`` 不是 ``:``）。
        (_COMPOSITE_PRIVATE, GROUP_A, False),
        # 红线反向：群复合形也进不了私聊本轮。
        (_COMPOSITE_GROUP_A, SENDER, False),
        # 红线：没有冒号分隔符就不算前缀——"qqxgroup_1_2" 与任何键都不折。
        (f"qqx{GROUP_A}", GROUP_A, False),
        ("group_1_2", "group_1X2", False),  # 绝不做前缀/通配式包含
        ("qq:group_1_2", "group_1X2", False),
        # 等值与全局两档不受开关影响。
        (GROUP_A, GROUP_A, True),
        ("global", GROUP_A, True),
        ("", GROUP_A, True),
        ("*", GROUP_A, True),
        (_COMPOSITE_GROUP_A, "", False),  # 本轮无键：fail-closed 优先于前缀档
    ],
)
def test_platform_prefix_width_matches_the_injecting_leg(
    row_session: str, current_session: str, expected: bool
) -> None:
    """``accept_platform_prefix=True`` 这一档只在「冒号 + 整尾等值」时放行。"""
    assert (
        legacy_session_visible(row_session, current_session, accept_platform_prefix=True)
        is expected
    )


@pytest.mark.parametrize(
    ("row_session", "current_session"),
    [
        (_COMPOSITE_GROUP_A, GROUP_A),  # 旧显式库那条腿没有这一档
        (_COMPOSITE_PRIVATE, SENDER),
        (_COMPOSITE_GROUP_A, ""),
    ],
)
def test_missing_width_flag_keeps_the_old_bare_equality_gate(
    row_session: str, current_session: str
) -> None:
    """缺省参数必须逐字维持旧行为：忘了传 True 只是少召回，不会放宽隐私闸。"""
    assert legacy_session_visible(row_session, current_session) is False


def _reflected_store(tmp_path: Path) -> ReflectionStore:
    return ReflectionStore(Path(tmp_path / "reflection.sqlite3"))


def test_folded_pool_never_wider_than_facts_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """总线折叠后可见集 == 注入方 SQL 放行集（五种本轮键各比一次）。

    这是「折叠闸比注入闸更严 ⇒ 整表拒收」与「折叠闸放宽 ⇒ 隐私闸拆了」两头共用的
    锁：判据一侧用**生产形态的复合键**真读 ``ReflectionStore.facts_for``（本件不复刻
    那条 SQL），另一侧走 ``build_memory_read_provider`` 的活路径；两边必须给出同一批
    正文，任何一头自己变宽/变窄都红。期望值另立一张表，防两边同错自我印证。
    """
    config = _config_for(_BusOn, tmp_path)
    # 预算放宽到不裁候选：本用例比的是**可见集合**，不是排序与截断。
    config.bot_memory_max_items = 30
    config.bot_memory_per_category_max = 30
    _seed_reflection_facts(
        Path(config.bot_reflection_db_path),
        [
            ("rf_a_bare", SENDER, GROUP_A, "甲群裸键行"),
            ("rf_a_comp", SENDER, _COMPOSITE_GROUP_A, "甲群复合行"),
            ("rf_b_comp", SENDER, _COMPOSITE_GROUP_B, "乙群复合行"),
            ("rf_priv_comp", SENDER, _COMPOSITE_PRIVATE, "私聊复合行"),
            ("rf_repl_comp", SENDER, _COMPOSITE_REPL, "控制台复合行"),
            ("rf_undelim", SENDER, f"qqx{GROUP_A}", "无冒号分隔行"),
            ("rf_glob", SENDER, "global", "全局行"),
            ("rf_empty", SENDER, "", "空会话行"),
        ],
    )
    store = _reflected_store(tmp_path)
    provider = _read_provider(config, monkeypatch)
    expectations: dict[str, list[str]] = {
        GROUP_A: ["空会话行", "全局行", "甲群复合行", "甲群裸键行"],
        GROUP_B: ["乙群复合行", "全局行", "空会话行"],
        SENDER: ["全局行", "私聊复合行", "空会话行"],
        "console:repl": ["控制台复合行", "全局行", "空会话行"],
        "": ["全局行", "空会话行"],  # 无本轮键：只见全局（两闸同侧 fail-closed）
    }
    for current, expected in expectations.items():
        admitted = sorted(fact.fact_text for fact in store.facts_for(
            SENDER, limit=40, max_chars=6000, session_id=current
        ))
        assert admitted == sorted(expected), (current, admitted)
        pool = _texts(
            _retrieved(
                provider,
                "行",
                session_id=current,
                max_items=30,
                max_chars=6000,
            ).facts
        )
        assert sorted(pool) == admitted, (current, pool, admitted)
        assert "无冒号分隔行" not in pool, (current, pool)


def test_composite_group_row_never_recalled_in_a_private_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端到端红线：群里说过的话（生产复合键形态）不得因为「修了折叠」就进私聊本轮。"""
    config = _config_for(_BusOn, tmp_path)
    _seed_reflection_facts(
        Path(config.bot_reflection_db_path),
        [
            ("rf_group_only", SENDER, _COMPOSITE_GROUP_A, "我在群里说的偏好"),
            ("rf_private_only", SENDER, _COMPOSITE_PRIVATE, "我私聊说的住址"),
        ],
    )
    provider = _read_provider(config, monkeypatch)
    in_private = _texts(_retrieved(provider, "偏好 住址", session_id=SENDER).facts)
    assert in_private == ["我私聊说的住址"], in_private
    in_group = _texts(_retrieved(provider, "偏好 住址", session_id=GROUP_A).facts)
    assert in_group == ["我在群里说的偏好"], in_group
    other_group = _texts(_retrieved(provider, "偏好 住址", session_id=GROUP_B).facts)
    assert other_group == [], other_group


def test_private_legacy_row_never_recalled_in_group_when_the_bus_is_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """私聊说过的旧库行，不得因为「开了总线」就在群里被召回。"""
    db = tmp_path / "memory.sqlite3"
    _seed_memory_facts(db, [("fact_home", SENDER, SENDER, "我住在某某小区三栋", _days_ago(1))])
    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)
    in_group = _texts(_retrieved(provider, "住址 小区", session_id=GROUP_A).facts)
    assert "我住在某某小区三栋" not in in_group, in_group
    # 同一条在私聊本轮仍可见（不是「一刀切不许读」）
    assert "我住在某某小区三栋" in _texts(
        _retrieved(provider, "住址 小区", session_id=SENDER).facts
    )


def test_group_a_row_never_recalled_in_group_b_when_the_bus_is_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "memory.sqlite3"
    _bus(db).absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我在 A 群说要组队打副本",
        session_id=GROUP_A,
        category="plan",
        source_event_id="e_a",
    )
    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)
    assert _texts(_retrieved(provider, "副本", session_id=GROUP_B).facts) == []
    assert _texts(_retrieved(provider, "副本", session_id=GROUP_A).facts) == [
        "我在 A 群说要组队打副本"
    ]


def test_legacy_global_row_still_visible_in_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """会话闸的反向锁：全局形态的旧行必须照常可见（否则第 5 组是「全禁」假绿）。"""
    db = tmp_path / "memory.sqlite3"
    _seed_memory_facts(db, [("fact_g", SENDER, "global", "我对芒果过敏", _days_ago(1))])
    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)
    assert "我对芒果过敏" in _texts(_retrieved(provider, "芒果", session_id=GROUP_B).facts)


def test_another_users_memory_never_enters_the_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "memory.sqlite3"
    _seed_memory_facts(
        db,
        [
            ("fact_mine", SENDER, "global", "我喜欢柠檬茶", _days_ago(1)),
            ("fact_theirs", OTHER, "global", "别人喜欢芒果", _days_ago(1)),
        ],
    )
    _bus(db).absorb(
        owner_id=OTHER,
        subject_user_id=OTHER,
        text="另一位的私密话",
        session_id=GROUP_A,
        category="fact",
        source_event_id="e_other",
    )
    _seed_reflection_facts(
        Path(str(tmp_path / "reflection.sqlite3")),
        [("rf_other", OTHER, GROUP_A, "另一位的归纳话")],
    )
    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)
    texts = _texts(_retrieved(provider, "柠檬茶 芒果 私密 归纳", session_id=GROUP_A).facts)
    assert texts == ["我喜欢柠檬茶"], texts
    # 替别人问（requester≠subject）连自己那批都不给（与 v1 隐私闸同语义）
    assert _retrieved(provider, "柠檬茶", requester_id=OTHER, subject_user_id=SENDER).facts == []


def test_reflected_row_from_another_session_is_not_folded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """折叠进来的归纳行同样受会话闸管：B 群的归纳不得在 A 群被念出来。"""
    config = _config_for(_BusOn, tmp_path)
    _seed_reflection_facts(
        Path(config.bot_reflection_db_path),
        [
            ("rf_b", SENDER, GROUP_B, "我在 B 群说过周末要加班"),
            ("rf_a", SENDER, GROUP_A, "我在 A 群说要组队打副本"),
        ],
    )
    provider = _read_provider(config, monkeypatch)
    in_b = _texts(_retrieved(provider, "加班", session_id=GROUP_B).facts)
    assert in_b == ["我在 B 群说过周末要加班"], in_b
    in_a = _texts(_retrieved(provider, "加班 副本", session_id=GROUP_A).facts)
    assert "我在 B 群说过周末要加班" not in in_a, in_a
    assert in_a == ["我在 A 群说要组队打副本"], in_a


# ---------------------------------------------------------------- 6. 证据列不是摆设


def _score_for(bus: MemoryBus, memory_id: str, query: str) -> Any:
    for item in bus.recall(owner_id=SENDER, session_id=GROUP_A, query_text=query).items:
        if item.fact_id == memory_id:
            return item
    raise AssertionError(f"row {memory_id} 不在召回面")


def test_contradict_count_actually_lowers_the_score(tmp_path: Path) -> None:
    """``contradict_count`` 必须进分数**并改变注入面**，否则该列是装饰。

    判据形状是现算出来的，不是随手写的（本席探针实跑）：同槽反极性两条在
    ``per_slot_max=1`` 下**只有胜者进 ``items``**，落选者以 ``dropped reason=slot_cap``
    出局（``per_slot_max=2`` 时改由 ``near_duplicate`` 出局）。所以「从 ``items`` 里
    读被降权那条的分数分量」结构上读不到——上一版断言就是这么写的，红在此。
    本席拆成三把各自能独立杀伤的锁：
      ① 分量等式走 ``recall`` 自己用的那个公开打分口 ``strength_of``（与池子无关）；
      ② 排序后果：只说过一次的旧行**让位**给反极性新行；
      ③ 它是**数量**不是一刀切：同一条旧行「又说起」三次后，带着矛盾仍占住槽位。
    """
    db = tmp_path / "memory.sqlite3"
    bus = _bus(db)
    store = MemoryStoreV21(str(db))

    def absorb(text: str, event_id: str) -> str:
        return bus.absorb(
            owner_id=SENDER,
            subject_user_id=SENDER,
            text=text,
            session_id=GROUP_A,
            category="preference",
            source_event_id=event_id,
        ).memory_id

    target = absorb("我喜欢柠檬茶", "e_like")
    before = bus.strength_of(dict(store.get_row_by_id(target) or {}), FIXED_NOW)
    absorb("我不喜欢柠檬茶", "e_dislike")
    row = dict(store.get_row_by_id(target) or {})
    assert int(row.get("contradict_count") or 0) == 1, row
    assert str(row.get("status")) == "active", row  # 偏好类矛盾不删旧行、不翻 superseded
    after = bus.strength_of(row, FIXED_NOW)
    # ① 精确比值：惩罚是一档一档的量（_CONTRADICT_PENALTY_STEP=0.25）
    assert after == pytest.approx(before * 0.75, abs=1e-9), (before, after)

    # ② 排序后果：被矛盾的那条今天进不了 prompt
    outcome = bus.recall(
        owner_id=SENDER, session_id=GROUP_A, query_text="柠檬茶", persist_audit=False
    )
    assert [item.text for item in outcome.items] == ["我不喜欢柠檬茶"], outcome.items
    assert any(
        item.fact_id == target and item.reason == "slot_cap" for item in outcome.dropped
    ), outcome.dropped

    # ③ 数量而非驱逐：同一条再说三次（confirm_count=4）后仍压得住新对手
    for extra in ("e_say_2", "e_say_3", "e_say_4"):
        assert absorb("我喜欢柠檬茶", extra) == target
    veteran = dict(store.get_row_by_id(target) or {})
    assert int(veteran.get("confirm_count") or 0) == 4, veteran
    assert int(veteran.get("contradict_count") or 0) == 1, veteran
    comeback = bus.recall(
        owner_id=SENDER, session_id=GROUP_A, query_text="柠檬茶", persist_audit=False
    )
    assert [item.text for item in comeback.items] == ["我喜欢柠檬茶"], comeback.items
    winner = comeback.items[0]
    assert winner.contradict_count == 1, winner
    # 分数分量等式（锁在真正进账的那条上）：score 三乘一加，无第四项
    weights = bus.settings().weights
    assert winner.score == pytest.approx(
        round(
            weights["w_rel"] * winner.relevance
            + weights["w_str"] * winner.strength
            + weights["w_rec"] * winner.recency,
            6,
        ),
        abs=1e-6,
    )


@pytest.mark.xfail(
    strict=False,
    reason=(
        "S-T-MEM-6 登记（需求 11 消费侧）：写腿称呼闸 _looks_like_form_of_address 用"
        "「单字包含」判动作/时间词，而 明/日/星/学/看/早/晚 这些字既是动作时间类用字"
        "又是常见人名用字 ⇒ 「我的名字是小明」落不进 attr:name 槽（identity_attribute"
        " 实测返回 ('','')），同属性改口于是永不置替。判据放宽会动生产写侧行为，"
        "归写腿席/主代理裁定，本席只把缺口钉成可见的 XPASS 而不是假装它不存在。"
    ),
)
def test_common_given_names_still_get_an_identity_slot(tmp_path: Path) -> None:
    """缺口证据锁：含「明」的人名今天进不了身份属性槽（改口不置替）。"""
    db = tmp_path / "memory.sqlite3"
    bus = _bus(db)
    store = MemoryStoreV21(str(db))
    old = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我的名字是小明",
        session_id=GROUP_A,
        category="identity",
        source_event_id="e_ming_old",
    ).memory_id
    new = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我的名字是李娜",
        session_id=GROUP_A,
        category="identity",
        source_event_id="e_ming_new",
    )
    assert str((store.get_row_by_id(old) or {}).get("status")) == "superseded", (
        "两条都该落 attr:name；实算第一条落 residual 槽 ⇒ 永不互相置替"
    )
    assert new.superseded_id == old


def test_superseded_identity_row_leaves_the_recall_pool_but_stays_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``supersedes`` 的作用点在**读侧候选集**：旧行退场留痕，不静默覆盖。

    如实登记两件事：
    - 本列**不参与**读侧加权公式（分数里没有它），效果由 ``status='superseded'``
      被 ``list_bus_candidates`` 排除来实现——所以它是一把「出局」的闸而非降权；
    - 夹具用 小红→阿澄 而不是 小明→小红：后者撞上面那条 xfail 记的称呼闸缺口
      （``我的名字是小明`` 今天根本不被识别为身份属性），拿它当夹具会把「机制没生效」
      和「机制生效了」混成同一种红，归因不了。
    """
    db = tmp_path / "memory.sqlite3"
    bus = _bus(db)
    old = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我的名字是小红",
        session_id=GROUP_A,
        category="identity",
        source_event_id="e_name_old",
    ).memory_id
    new = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我的名字是阿澄",
        session_id=GROUP_A,
        category="identity",
        source_event_id="e_name_new",
    ).memory_id
    store = MemoryStoreV21(str(db))
    assert str((store.get_row_by_id(old) or {}).get("status")) == "superseded"
    assert str((store.get_row_by_id(new) or {}).get("supersedes")) == old

    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)
    texts = _texts(_retrieved(provider, "名字", session_id=GROUP_A).facts)
    # 进 prompt 的只有新名；旧名不在（且不是被预算挤掉的——下面这条同时排除该解释）
    assert texts == ["我的名字是阿澄"], texts
    assert old in {str(r["memory_id"]) for r in store.list_entries_by_owner(SENDER)}
    evicted = bus.recall(
        owner_id=SENDER, session_id=GROUP_A, query_text="名字", persist_audit=False
    )
    assert not any(
        item.fact_id == old and item.reason in {"budget", "slot_cap", "near_duplicate"}
        for item in evicted.dropped
    ), evicted.dropped  # 旧行根本不在候选池里（status 闸），不是被预算挤掉


def test_confirm_count_actually_raises_the_score(tmp_path: Path) -> None:
    """「又说起」只加 ``confirm_count`` ⇒ 同一条更可信，分数必须跟着走。"""
    db = tmp_path / "memory.sqlite3"
    bus = _bus(db)
    target = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我喜欢柠檬茶",
        session_id=GROUP_A,
        category="preference",
        source_event_id="e1",
    ).memory_id
    before = _score_for(bus, target, "柠檬茶")
    outcome = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我喜欢柠檬茶",
        session_id=GROUP_A,
        category="preference",
        source_event_id="e2",
    )
    assert outcome.action == "confirmed" and outcome.memory_id == target
    row = MemoryStoreV21(str(db)).get_row_by_id(target) or {}
    assert int(row.get("confirm_count") or 0) == 2, row
    after = _score_for(bus, target, "柠檬茶")
    assert after.strength > before.strength
    assert after.score > before.score


def test_same_text_in_both_pools_counts_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """旧行迁进总线后两路都读到 ⇒ prompt 只留总线那一条身份。"""
    db = tmp_path / "memory.sqlite3"
    bus = _bus(db)
    bus_id = bus.absorb(
        owner_id=SENDER,
        subject_user_id=SENDER,
        text="我对芒果过敏",
        session_id=GROUP_A,
        category="preference",
        source_event_id="e_bus",
    ).memory_id
    _seed_memory_facts(db, [("fact_dup", SENDER, GROUP_A, "我对芒果过敏", _days_ago(1))])
    config = _config_for(_BusOn, tmp_path)
    config.bot_memory_db_path = str(db)
    provider = _read_provider(config, monkeypatch)
    facts = _retrieved(provider, "芒果", session_id=GROUP_A).facts
    assert _texts(facts) == ["我对芒果过敏"], facts
    assert str(facts[0]["fact_id"]) == bus_id, facts[0]
    assert not str(facts[0]["fact_id"]).startswith("legacy:"), facts[0]
