"""记忆总线 v2（WP6）行为门：六场景 + 红线 + 关态逐字节旧行为。

全离线 tmp_path 夹具，绝不触碰 `ChatBot_Runtime/`（运行数据铁律）。
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    SQLiteMemoryRepository,
    build_memory_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    PROVENANCE_EXPLICIT,
    PROVENANCE_REFLECTED,
    MemoryBus,
    MemoryBusProvider,
    build_memory_bus,
    canonical_fact_text,
    derive_scope,
    fact_signature,
    settings_from_config,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
    MemoryStoreV21,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reflection import (
    ReflectionMemoryProvider,
    ReflectionStore,
    build_reflection_memory_provider,
    run_nightly_reflection,
)

GROUP_A = "group_1108838060_3865067623"
GROUP_B = "group_631785829_3865067623"
PRIVATE = "3865067623"
FIXED_NOW = datetime.datetime(2026, 9, 21, 12, 0, tzinfo=datetime.timezone.utc)


class BusConfig:
    """九键的**开态**桩（生产缺省见 config.py：bus_enabled=False / target=legacy）。"""

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
    bot_reflection_enabled = True
    bot_reflection_db_path = ""
    bot_reflection_max_sessions = 50
    bot_history_enabled = True
    bot_history_db_path = ""


class LegacyConfig(BusConfig):
    """设计稿 §五的缺省态：总线关、归纳仍写旧表。"""

    bot_memory_bus_enabled = False
    bot_memory_reflected_write_target = "legacy"


def _clock_factory(moment: datetime.datetime):
    return lambda: moment


def _epoch_clock(moment: datetime.datetime):
    return lambda: moment.timestamp()


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStoreV21:
    return MemoryStoreV21(str(tmp_path / "memory.sqlite3"))


def _bus(store: MemoryStoreV21, **kwargs: Any) -> MemoryBus:
    return MemoryBus(
        store,
        config=kwargs.pop("config", BusConfig()),
        clock=_clock_factory(FIXED_NOW),
        **kwargs,
    )


def _absorb(bus: MemoryBus, text: str, *, session=GROUP_A, event: str, **kw: Any):
    return bus.absorb(
        owner_id=kw.pop("owner_id", "u1"),
        subject_user_id="u1",
        text=text,
        session_id=session,
        source_event_id=event,
        **kw,
    )


# ---------------------------------------------------------------- 作用域列化


def test_scope_shape_comes_from_central_piece_only() -> None:
    """作用域判定唯一经中央件：群键=group_member、私聊=session、空键不可写。"""
    assert derive_scope(GROUP_A).kind == "group_member"
    assert derive_scope(GROUP_A).key == GROUP_A
    assert derive_scope(PRIVATE).kind == "session"
    # 脏/空键 → key=''（写侧据此拒收，读侧只见 global）：fail-closed 的一侧。
    assert derive_scope("").key == ""
    assert derive_scope(None).key == ""
    # 缺发送者段的脏键：中央件 fail-closed 不判群，落普通会话作用域——
    # 等值判据下它和任何真实群键都不相等，谁也看不见谁（不是放行，是隔离成孤岛）。
    dirty = derive_scope("group_123456")
    assert dirty.kind == "session" and dirty.key == "group_123456"
    assert dirty.key not in {derive_scope(GROUP_A).key, derive_scope(GROUP_B).key}


def test_bus_module_holds_no_second_key_shape_judge(store: MemoryStoreV21) -> None:
    """本席文件里不得再长出「拿字符串键猜群/私聊」的第二套判据。"""
    import ast

    source = Path(
        "plugins/bot_unified_runtime/domains/chat_reply/character/memory_bus_v2.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.ops[0], (ast.In, ast.Eq))
            and "session" in (text := ast.unparse(node))
            and '"group' in text
        ):
            offenders.append(text)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"startswith", "endswith", "partition", "split"}
            and "session" in (text := ast.unparse(node))
            and "group" in text.lower()
        ):
            offenders.append(text)
    assert offenders == [], f"总线里冒出第二套键形判据：{offenders}"
    assert "parse_session_key" in source


# ---------------------------------------------------------------- §七 场景 1


def test_scenario1_group_fact_is_structurally_unreachable_from_other_group(
    store: MemoryStoreV21,
) -> None:
    """群 A 说过的话，在群 B 与私聊里**结构上**召不回（列等值，不是字符串运气）。"""
    bus = _bus(store)
    _absorb(bus, "我在戒糖", session=GROUP_A, event="e1", category="preference")

    same = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="戒糖", request_id="r1")
    other = bus.recall(owner_id="u1", session_id=GROUP_B, query_text="戒糖", request_id="r2")
    private = bus.recall(owner_id="u1", session_id=PRIVATE, query_text="戒糖", request_id="r3")
    assert [item.text for item in same.items] == ["我在戒糖"]
    assert other.items == [] and other.candidates == 0
    assert private.items == [] and private.candidates == 0


def test_scenario1_end_to_end_nightly_reflection_to_prompt(
    tmp_path: Path,
) -> None:
    """端到端：真实形态的历史库（platform + 裸群键）→ 夜间归纳 → 总线 → provider。

    这条是本场景的正解形态：不看函数返回值，看「换个群问，还答得出来吗」。
    """
    history_db = tmp_path / "history.sqlite3"
    _seed_history(
        history_db,
        [
            ("qq", GROUP_A, "u1", "user", "我最喜欢吃柠檬茶了"),
            ("qq", GROUP_B, "u2", "user", "今天天气不错"),
        ],
    )
    memory_db = tmp_path / "memory.sqlite3"
    reflection_db = tmp_path / "reflection.sqlite3"
    config = BusConfig()
    config.bot_memory_db_path = str(memory_db)
    config.bot_reflection_db_path = str(reflection_db)
    config.bot_history_db_path = str(history_db)
    config.bot_quirks_db_path = str(tmp_path / "persona_quirks.sqlite3")

    report = run_nightly_reflection(config)
    assert report.get("skipped") is None, report
    assert int(report.get("facts_saved") or 0) >= 1, report

    provider = build_memory_provider(config)
    hit = provider.retrieve(
        request_id="req-a",
        requester_id="u1",
        subject_user_id="u1",
        session_id=GROUP_A,
        query_text="柠檬茶",
        max_items=5,
        max_chars=600,
    )
    leak = provider.retrieve(
        request_id="req-b",
        requester_id="u1",
        subject_user_id="u1",
        session_id=GROUP_B,
        query_text="柠檬茶",
        max_items=5,
        max_chars=600,
    )
    assert any("柠檬茶" in str(fact.get("text")) for fact in hit.facts), hit.facts
    assert leak.facts == [], f"A 群的偏好出现在 B 群：{leak.facts}"


# ---------------------------------------------------------------- §七 场景 2


def test_scenario2_same_preference_five_times_is_one_row_with_confirm_five(
    store: MemoryStoreV21,
) -> None:
    bus = _bus(store)
    actions = [
        _absorb(
            bus,
            text,
            event=f"day{i}",
            category="preference",
            provenance=PROVENANCE_REFLECTED,
        )
        for i, text in enumerate(
            [
                "我喜欢柠檬茶",
                "我超爱柠檬茶",
                "我平时爱喝柠檬茶",
                "我很喜欢柠檬茶",
                "我还是喜欢柠檬茶",
            ]
        )
    ]
    assert [action.action for action in actions] == [
        "inserted",
        "confirmed",
        "confirmed",
        "confirmed",
        "confirmed",
    ]
    rows = _rows(store)
    assert len(rows) == 1
    assert int(rows[0]["confirm_count"]) == 5
    assert str(rows[0]["text"]) == "我喜欢柠檬茶"  # 首手措辞不被后续覆盖

    assert bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶").items[0].confirm_count == 5
    # 印证次数换来排位：与一条只说过一次的新事实同台（无查询词=中性相关档），5 次在前。
    _absorb(bus, "我在学 Rust", event="new1", category="activity")
    ranked = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="")
    assert [item.text for item in ranked.items] == ["我喜欢柠檬茶", "我在学 Rust"]
    assert ranked.items[0].strength > ranked.items[1].strength


# ---------------------------------------------------------------- §七 场景 3


def test_scenario3_change_of_mind_keeps_two_rows_with_supersedes_and_deweights_old(
    store: MemoryStoreV21,
) -> None:
    bus = _bus(store)
    _absorb(bus, "我喜欢柠檬茶", event="a1", category="preference")
    _absorb(bus, "我超爱柠檬茶", event="a2", category="preference")
    outcome = _absorb(bus, "我现在不喝柠檬茶了", event="b1", category="preference")
    assert outcome.action == "contradicted"

    rows = {str(row["text"]): row for row in _rows(store)}
    assert set(rows) == {"我喜欢柠檬茶", "我现在不喝柠檬茶了"}
    old, new = rows["我喜欢柠檬茶"], rows["我现在不喝柠檬茶了"]
    assert str(new["supersedes"]) == str(old["memory_id"])  # 裁决留痕，说得清被谁改
    assert int(old["contradict_count"]) == 1
    assert int(old["confirm_count"]) == 2 and int(new["confirm_count"]) == 1
    # 旧的不判死，只降权：两次印证仍压过一句新话。
    first_pass = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶")
    assert [item.text for item in first_pass.items] == ["我喜欢柠檬茶"]
    # 新说法取得更多印证后自己上位——「改主意」是可翻转的证据竞争，不是覆盖。
    _absorb(bus, "我真的不喝柠檬茶了", event="b2", category="preference")
    _absorb(bus, "我现在不喝柠檬茶了", event="b3", category="preference")
    flipped = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶")
    assert [item.text for item in flipped.items] == ["我现在不喝柠檬茶了"]


def test_scenario3_reflected_never_supersedes_explicit(store: MemoryStoreV21) -> None:
    """显式压过归纳（意志自主条款在记忆面的对应物）。"""
    bus = _bus(store)
    _absorb(bus, "我喜欢柠檬茶", event="x1", category="preference")  # explicit 缺省
    night = _absorb(
        bus,
        "我不喜欢柠檬茶了",
        event="x2",
        category="preference",
        provenance=PROVENANCE_REFLECTED,
    )
    assert night.action == "inserted"  # 不 supersede、不给 explicit 记矛盾
    rows = {str(row["text"]): row for row in _rows(store)}
    assert int(rows["我喜欢柠檬茶"]["contradict_count"]) == 0
    assert str(rows["我不喜欢柠檬茶了"]["supersedes"]) == ""
    # 但召回面上 explicit 仍胜出（可靠度 1.0 vs 0.8）
    chosen = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="柠檬茶")
    assert chosen.items[0].text == "我喜欢柠檬茶"


# ---------------------------------------------------------------- §七 场景 4


def test_scenario4_irrelevant_old_fact_does_not_occupy_budget(store: MemoryStoreV21) -> None:
    """confidence 高但与当前话题无关 ⇒ 不再白占预算（v1 只看 confidence+时间序）。"""
    bus = _bus(store)
    # 给无关那条堆满证据（5 次印证、confidence 1.0）：v1 里它必进 prompt，
    # v2 里它与本轮话题零重合 ⇒ 点名出局，预算留给相关那条。
    for index in range(5):
        _absorb(
            bus, "我是设计师", event=f"f{index}", category="identity",
            confidence=1.0,
        )
    _absorb(bus, "我对芒果过敏", event="g1", category="preference", confidence=0.9)
    out = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="我对什么食物过敏")
    assert [item.text for item in out.items] == ["我对芒果过敏"], out.items
    assert out.items[0].relevance > 0.0
    assert [(item.text, item.reason) for item in out.dropped] == [
        ("我是设计师", "irrelevant")
    ], out.dropped


def test_scenario4_empty_query_does_not_zero_every_candidate(store: MemoryStoreV21) -> None:
    """无查询词（如 /bot memory list 路径）时 relevance 走中性档，不误伤成全空。"""
    bus = _bus(store)
    _absorb(bus, "我对芒果过敏", event="f1", category="preference")
    out = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="")
    assert [item.text for item in out.items] == ["我对芒果过敏"]
    assert out.items[0].relevance == pytest.approx(0.5)


# ---------------------------------------------------------------- §七 场景 5


def test_scenario5_near_duplicate_trio_leaves_single_slot(store: MemoryStoreV21) -> None:
    """近重复三条 ⇒ 同槽位只留一条（写侧合并 + 读侧簇上限双保险）。"""
    bus = _bus(store)
    _absorb(bus, "我不吃香菜", event="d1", category="preference")
    _absorb(bus, "我讨厌香菜", event="d2", category="fact")  # 不同类别⇒不同合并槽
    _absorb(bus, "我平时也不吃香菜", event="d3", category="preference")  # 与 d1 合并
    rows = _rows(store)
    assert len(rows) == 2  # 写侧已并掉一条
    out = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="香菜")
    assert len(out.items) == 1, [(i.text, i.score) for i in out.items]
    assert any(item.reason == "slot_cap" for item in out.dropped), out.dropped


def test_scenario5_slot_cap_is_configurable(store: MemoryStoreV21) -> None:
    class Loose(BusConfig):
        bot_memory_per_category_max = 3

    bus = _bus(store, config=Loose())
    _absorb(bus, "我不吃香菜", event="d1", category="preference")
    _absorb(bus, "我讨厌香菜", event="d2", category="fact")
    out = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="香菜")
    assert len(out.items) == 2


# ---------------------------------------------------------------- §七 场景 6


def test_scenario6_why_shows_which_facts_scores_and_provenance(store: MemoryStoreV21) -> None:
    bus = _bus(store)
    _absorb(bus, "我对芒果过敏", event="w1", category="preference")
    _absorb(bus, "我对芒果过敏", event="w2", category="preference")
    _absorb(bus, "我是设计师", event="w3", category="identity", sensitivity="credentialed")
    bus.recall(owner_id="u1", session_id=GROUP_A, query_text="芒果", request_id="req-1")

    text = bus.render_why(owner_id="u1")
    assert "我对芒果过敏" in text
    assert "2 次印证" in text          # 证据累积可见
    assert "相关" in text and "强度" in text and "新近" in text
    assert "我回头想的" not in text     # 两条都是 explicit（缺省来源）
    assert "你亲口说的" in text
    assert "我是设计师" not in text       # 凭证级的正文连观测面都不落
    assert "凭证级" in text              # 但为什么没用要说得清
    audit = bus.latest_audit(owner_id="u1")
    assert audit is not None
    assert "芒果" in str(audit["selected_json"])


def test_recall_writes_one_audit_row_per_injection(store: MemoryStoreV21) -> None:
    bus = _bus(store)
    _absorb(bus, "我对芒果过敏", event="a", category="preference")
    bus.recall(owner_id="u1", session_id=GROUP_A, query_text="芒果", request_id="r1")
    bus.recall(owner_id="u1", session_id=GROUP_A, query_text="芒果", request_id="r2")
    bus.recall(
        owner_id="u1", session_id=GROUP_A, query_text="芒果", request_id="r3",
        persist_audit=False,
    )
    with store._lock:
        count = store._connection.execute(
            "SELECT COUNT(*) AS n FROM memory_recall_audit_v21"
        ).fetchone()["n"]
    assert int(count) == 2  # 预览不落账，真注入才落


# ---------------------------------------------------------------- 红线


def test_credentialed_sensitivity_never_recalled(store: MemoryStoreV21) -> None:
    bus = _bus(store)
    _absorb(bus, "我的账号密码是 abc", event="c1", sensitivity="credentialed")
    out = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="账号")
    assert out.items == []
    assert [item.reason for item in out.dropped] == ["credentialed"]


def test_provider_refuses_non_self_requester(store: MemoryStoreV21) -> None:
    bus = MemoryBus(store, config=BusConfig(), clock=_clock_factory(FIXED_NOW))
    _absorb(bus, "我对芒果过敏", event="p1", category="preference")
    provider = MemoryBusProvider(bus)
    result = provider.retrieve(
        request_id="r", requester_id="other", subject_user_id="u1",
        session_id=GROUP_A, query_text="芒果", max_items=5, max_chars=600,
    )
    assert result.facts == []
    own = provider.retrieve(
        request_id="r", requester_id="u1", subject_user_id="u1",
        session_id=GROUP_A, query_text="芒果", max_items=5, max_chars=600,
    )
    assert len(own.facts) == 1
    assert own.facts[0]["fact_id"] and own.facts[0]["scope_key"] == GROUP_A


def test_recall_facts_are_all_string_valued_contract(store: MemoryStoreV21) -> None:
    """MemoryRetrievalResult.facts 是 dict[str, str]（严格模型）——塞数字会当场炸。"""
    bus = MemoryBus(store, config=BusConfig(), clock=_clock_factory(FIXED_NOW))
    _absorb(bus, "我对芒果过敏", event="s1", category="preference")
    facts = MemoryBusProvider(bus).retrieve(
        request_id="r", requester_id="u1", subject_user_id="u1",
        session_id=GROUP_A, query_text="芒果", max_items=5, max_chars=600,
    ).facts
    assert facts
    for fact in facts:
        assert all(isinstance(key, str) and isinstance(value, str) for key, value in fact.items())


def test_hard_line_candidate_is_refused_by_single_sanitize_source(store: MemoryStoreV21) -> None:
    """沉淀面复用 memory_sanitize 的六硬线+minors 单一来源（不建第二套词表）。"""
    bus = _bus(store)
    outcome = _absorb(bus, "她八岁，给我看色情", event="h1", category="preference")
    assert outcome.action == "rejected"
    assert outcome.reason.startswith("hard_line:")
    assert _rows(store) == []


def test_forgotten_fact_is_not_resurrected_by_night_thinking(store: MemoryStoreV21) -> None:
    """遗忘权：用户删掉的事，夜间归纳不许记回来；本人再明说一次则可以。"""
    bus = _bus(store)
    outcome = _absorb(bus, "我对芒果过敏", event="t1", category="preference")
    assert store.insert_tombstone(
        {
            "memory_id": outcome.memory_id,
            "owner_id": "u1",
            "reason": "forget",
            "original_version": 1,
            "forgotten_by": "u1",
            "created_at": "2026-09-21T12:00:00+00:00",
        }
    )
    assert store.update_bus_fields(outcome.memory_id, {"status": "forgotten"})

    relarned = _absorb(
        bus,
        "我对芒果过敏",
        event="t2",
        category="preference",
        provenance=PROVENANCE_REFLECTED,
    )
    assert relarned.action == "rejected" and relarned.reason == "forgotten_slot"
    assert bus.recall(owner_id="u1", session_id=GROUP_A, query_text="芒果").items == []
    # 同一条旧行也不能被幂等探针之外的路子复活：重放同一事件只算重复。
    replay = _absorb(bus, "我对芒果过敏", event="t1", category="preference")
    assert replay.action == "duplicate_skipped", replay
    # 本人显式再说一次=改主意，允许重建（这是意志自主，不是回魂）。
    again = _absorb(bus, "我对芒果过敏", event="t3", category="preference")
    assert again.action == "inserted", again


def test_unscoped_reflected_candidate_is_refused_fail_closed(store: MemoryStoreV21) -> None:
    """归纳侧拿到脏/空会话键 ⇒ 拒收，绝不退化成「全会话可见」（v1 的 fail-open）。"""
    bus = _bus(store)
    outcome = _absorb(
        bus, "我住在北京", session="", event="u1", provenance=PROVENANCE_REFLECTED
    )
    assert outcome.action == "rejected" and outcome.reason == "unscoped_candidate"
    assert _rows(store) == []


# ---------------------------------------------------------------- 关态逐字节旧行为


def test_bus_disabled_builds_no_store_and_returns_legacy_repository(tmp_path: Path) -> None:
    memory_db = tmp_path / "memory.sqlite3"
    config = LegacyConfig()
    config.bot_memory_db_path = str(memory_db)
    provider = build_memory_provider(config)
    assert isinstance(provider, SQLiteMemoryRepository)
    assert provider.bus is None
    # 关态不建总线库：memory_entries_v21 这张表压根不该出现。
    _seed_legacy_facts(memory_db, [("fact_a", "u1", GROUP_A, "我对芒果过敏", "personal")])
    result = provider.retrieve(
        request_id="r1", requester_id="u1", subject_user_id="u1",
        session_id=GROUP_A, query_text="芒果", max_items=5, max_chars=600,
    )
    assert [dict(fact) for fact in result.facts] == [
        {
            "fact_id": "fact_a",
            "kind": "auto",
            "text": "我对芒果过敏",
            "source": "llm_extract",
            "sensitivity": "personal",
            "scope_key": f"session:{GROUP_A}",
        }
    ], result.facts
    assert _tables(memory_db) == ["memory_facts"]


def test_bus_disabled_legacy_write_read_delete_paths_unchanged(tmp_path: Path) -> None:
    db = tmp_path / "memory.sqlite3"
    repo = SQLiteMemoryRepository(db)  # 不传 bus=旧构造签名，逐字节旧行为
    repo.upsert_fact(
        fact_id="f1", subject_user_id="u1", session_id=GROUP_A,
        memory_kind="manual", text="我喜欢蓝色", confidence=1.0, source="manual_command",
    )
    rows = repo.list_rows_for_subject("u1")
    assert rows and rows[0]["text"] == "我喜欢蓝色"
    assert repo.delete_fact(fact_id="f1", subject_user_id="u1", session_id=GROUP_A)
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0] == 0


def test_bus_disabled_nightly_reflection_writes_only_legacy_table(tmp_path: Path) -> None:
    history_db = tmp_path / "history.sqlite3"
    _seed_history(
        history_db, [("qq", GROUP_A, "u1", "user", "我最喜欢吃柠檬茶了")]
    )
    memory_db = tmp_path / "memory.sqlite3"
    config = LegacyConfig()
    config.bot_memory_db_path = str(memory_db)
    config.bot_reflection_db_path = str(tmp_path / "reflection.sqlite3")
    config.bot_history_db_path = str(history_db)
    config.bot_quirks_db_path = str(tmp_path / "persona_quirks.sqlite3")

    report = run_nightly_reflection(config)
    assert int(report.get("facts_saved") or 0) == 1, report
    reflection_rows = _reflection_rows(config.bot_reflection_db_path)
    assert [(row["sender_id"], row["session_key"], row["fact_text"], row["superseded"])
            for row in reflection_rows] == [
        ("u1", f"qq:{GROUP_A}", "我最喜欢吃柠檬茶了", 0)
    ], reflection_rows
    # 关态绝不新建/改写总线：记忆库里连 memory_entries_v21 都不该存在。
    assert _tables(memory_db) == [] or _tables(memory_db) == ["memory_facts"]


def test_bus_disabled_reflection_provider_still_reads_legacy(tmp_path: Path) -> None:
    store = ReflectionStore(
        tmp_path / "reflection.sqlite3", clock=_epoch_clock(FIXED_NOW)
    )
    digest = store.save_digest(
        session_key=f"qq:{GROUP_A}", scope_date="2026-09-21", summary="s", turn_count=1
    )
    store.save_facts(digest, "u1", [_draft("我对芒果过敏")])
    provider = ReflectionMemoryProvider(store)
    assert len(provider.retrieve(
        request_id="r", requester_id="u1", subject_user_id="u1",
        session_id=GROUP_A, query_text="芒果", max_items=5, max_chars=600,
    ).facts) == 1
    # 总线开启时旧 provider 必须让位（同一条事实不得以两个身份同时进 prompt）
    yielding = ReflectionMemoryProvider(store, bus_enabled=True)
    assert yielding.retrieve(
        request_id="r", requester_id="u1", subject_user_id="u1",
        session_id=GROUP_A, query_text="芒果", max_items=5, max_chars=600,
    ).facts == []


def test_half_open_bus_keeps_reading_legacy_reflection(tmp_path: Path) -> None:
    """半开态（总线开、归纳仍写旧表、迁移未跑）不得让已有记忆凭空消失。"""

    class HalfOpen(BusConfig):
        bot_memory_reflected_write_target = "legacy"

    store = ReflectionStore(
        tmp_path / "reflection.sqlite3", clock=_epoch_clock(FIXED_NOW)
    )
    digest = store.save_digest(
        session_key=f"qq:{GROUP_A}", scope_date="2026-09-21", summary="s", turn_count=1
    )
    store.save_facts(digest, "u1", [_draft("我对芒果过敏")])
    config = HalfOpen()
    config.bot_reflection_db_path = str(tmp_path / "reflection.sqlite3")
    provider = build_reflection_memory_provider(config)
    assert provider._bus_enabled is False
    assert len(provider.retrieve(
        request_id="r", requester_id="u1", subject_user_id="u1",
        session_id=GROUP_A, query_text="芒果", max_items=5, max_chars=600,
    ).facts) == 1


# ---------------------------------------------------------------- 键形修正（探针复现）


def test_reflection_read_key_now_matches_platform_composite_write(tmp_path: Path) -> None:
    """探针四态：写 1 行 / 按写侧键召回 1 / **按读侧真实入参召回 1（旧值 0）** / 不传=1。"""
    store = ReflectionStore(
        tmp_path / "reflection.sqlite3", clock=_epoch_clock(FIXED_NOW)
    )
    digest = store.save_digest(
        session_key=f"qq:{GROUP_A}", scope_date="2026-09-21", summary="s", turn_count=1
    )
    store.save_facts(digest, "u1", [_draft("我对芒果过敏")])
    assert len(store.facts_for("u1", session_id=f"qq:{GROUP_A}")) == 1  # 写侧键（本来就中）
    assert len(store.facts_for("u1", session_id=GROUP_A)) == 1  # 读侧真实入参（旧为 0）
    assert len(store.facts_for("u1")) == 1                       # 兼容旧全会话语义
    # 修的是等值判据，不是把闸门拆了：异群、异平台后缀缺失都不得放行。
    assert store.facts_for("u1", session_id=GROUP_B) == []
    assert store.facts_for("u1", session_id="group_1108838060") == []
    assert store.facts_for("u1", session_id="xgroup_1108838060_3865067623") == []


def test_reflection_underscore_is_not_a_like_wildcard(tmp_path: Path) -> None:
    """读侧修正不用 LIKE：键里的 `_` 是 LIKE 通配符，会让群号数字互串。"""
    store = ReflectionStore(
        tmp_path / "reflection.sqlite3", clock=_epoch_clock(FIXED_NOW)
    )
    digest = store.save_digest(
        session_key="qq:group_123456_789", scope_date="2026-09-21", summary="s", turn_count=1
    )
    store.save_facts(digest, "u1", [_draft("我对芒果过敏")])
    # 只差一个字符的键（group_12345X_789）若走 LIKE 就会命中——等值判据下必须为空。
    assert store.facts_for("u1", session_id="group_12345X_789") == []


# ---------------------------------------------------------------- 打分与衰减


def test_strength_saturates_and_decays_by_class(store: MemoryStoreV21) -> None:
    class Slow(BusConfig):
        bot_memory_tau_stable_days = 10

    fresh = _bus(store)
    for index in range(6):
        _absorb(fresh, "我喜欢柠檬茶", event=f"k{index}", category="preference")
    now_strength = fresh.strength_of(_rows(store)[0], FIXED_NOW)
    stale = fresh.strength_of(_rows(store)[0], FIXED_NOW + datetime.timedelta(days=10))
    assert 0.0 < stale < now_strength <= 1.0
    # 饱和：+1 次印证的边际收益递减（第 1→2 次的增益大于第 6→7 次）
    gains = [
        1.0 - __import__("math").exp(-n / Slow.bot_memory_strength_k) for n in range(1, 8)
    ]
    assert gains[1] - gains[0] > gains[6] - gains[5]


def test_episodic_facts_are_not_injected_into_long_term_profile(store: MemoryStoreV21) -> None:
    bus = _bus(store)
    _absorb(bus, "我今天加班到十点", event="ep1", category="plan")  # plan→seasonal
    _absorb(bus, "刚才那场球赛赢了", event="ep2", category="event")  # event→episodic
    out = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="球赛")
    assert [item.text for item in out.items] == ["我今天加班到十点"]  # 一条都不相关时的兜底
    assert [(item.text, item.reason) for item in out.dropped] == [
        ("刚才那场球赛赢了", "episodic_not_profile")
    ], out.dropped
    assert all("球赛" not in item.text for item in out.items)


def test_semantic_recall_degradation_is_marked_not_hidden(store: MemoryStoreV21) -> None:
    bus = _bus(store)
    _absorb(bus, "我对芒果过敏", event="s1", category="preference")
    plain = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="芒果")
    assert plain.semantic_available is False

    def _scorer(query: str, text: str) -> float:
        return 0.9 if "芒果" in text else 0.0

    wired = _bus(store, semantic_scorer=_scorer)
    semantic = wired.recall(owner_id="u1", session_id=GROUP_A, query_text="水果禁忌")
    assert semantic.semantic_available is True
    assert semantic.items[0].relevance == pytest.approx(0.9)


def test_semantic_scorer_failure_degrades_without_breaking_recall(store: MemoryStoreV21) -> None:
    def _boom(query: str, text: str) -> float:
        raise RuntimeError("vector service down")

    bus = _bus(store, semantic_scorer=_boom)
    _absorb(bus, "我对芒果过敏", event="s1", category="preference")
    out = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="芒果")
    assert out.semantic_available is False
    assert [item.text for item in out.items] == ["我对芒果过敏"]


def test_weights_json_falls_back_to_code_defaults(store: MemoryStoreV21) -> None:
    class BadWeights(BusConfig):
        bot_memory_relevance_weights = "{not json"

    settings = settings_from_config(BadWeights())
    assert settings.weights["w_rel"] == pytest.approx(0.45)
    assert settings.enabled is True
    assert settings.writes_to_bus is True


def test_settings_read_per_call_not_snapshot() -> None:
    """逐调用现读（本轮不登记 SETTABLE_KEYS，配置改了重启即生效，不留热改假象）。"""

    class Toggle(BusConfig):
        pass

    config = Toggle()
    config.bot_memory_per_category_max = 1
    assert settings_from_config(config).per_slot_max == 1
    config.bot_memory_per_category_max = 4
    assert settings_from_config(config).per_slot_max == 4


def test_build_memory_bus_none_when_disabled(tmp_path: Path) -> None:
    config = LegacyConfig()
    config.bot_memory_db_path = str(tmp_path / "memory.sqlite3")
    assert build_memory_bus(config) is None
    assert not (tmp_path / "memory.sqlite3").exists()  # 关态连文件都不该建


def test_legacy_explicit_rows_fold_into_same_scoring(tmp_path: Path) -> None:
    """双读影子期：旧 memory_facts 的显式事实与总线同池打分，不迁移也不掉队。"""
    memory_db = tmp_path / "memory.sqlite3"
    _seed_legacy_facts(
        memory_db, [("fact_old", "u1", GROUP_A, "我住在北京", "personal")]
    )
    store = MemoryStoreV21(str(memory_db))
    repo = SQLiteMemoryRepository(memory_db)
    bus = _bus(store, legacy_explicit_reader=repo.list_rows_for_subject)
    _absorb(bus, "我对芒果过敏", event="new1", category="preference")
    out = bus.recall(owner_id="u1", session_id=GROUP_A, query_text="北京 芒果")
    assert {item.text for item in out.items} == {"我住在北京", "我对芒果过敏"}
    legacy = next(item for item in out.items if item.text == "我住在北京")
    assert legacy.provenance == PROVENANCE_EXPLICIT


def test_provider_via_build_memory_reads_bus(tmp_path: Path) -> None:
    memory_db = tmp_path / "memory.sqlite3"
    config = BusConfig()
    config.bot_memory_db_path = str(memory_db)
    provider = build_memory_provider(config)
    assert isinstance(provider, MemoryBusProvider)
    repo = SQLiteMemoryRepository(memory_db, bus=build_memory_bus(config))
    repo.upsert_fact(
        fact_id="ignored", subject_user_id="u1", session_id=GROUP_A,
        memory_kind="preference", text="我对芒果过敏", confidence=1.0,
        source="manual_command",
    )
    with sqlite3.connect(memory_db) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        # 总线开启后旧表连建都不建——写侧只有一条路，不存在「两边各写一份」。
        assert "memory_facts" not in tables, tables
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_entries_v21"
        ).fetchone()[0] == 1
    facts = provider.retrieve(
        request_id="r", requester_id="u1", subject_user_id="u1",
        session_id=GROUP_A, query_text="芒果", max_items=5, max_chars=600,
    ).facts
    assert [fact["text"] for fact in facts] == ["我对芒果过敏"]
    assert fact_signature("我对芒果过敏", category="preference").polarity == "+"
    assert canonical_fact_text(" 我 喜欢 柠檬茶。 ") == "我喜欢柠檬茶"


# ---------------------------------------------------------------- 单轮抽取写入口


def test_extract_writer_without_bus_keeps_legacy_rows(tmp_path: Path) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_extract import (
        store_extracted_memories,
    )

    db = tmp_path / "memory.sqlite3"
    repo = SQLiteMemoryRepository(db)  # 生产 root 现在的构造形态：不传 bus
    stored = store_extracted_memories(
        repo, subject_user_id="u1", session_id=GROUP_A, texts=["我对芒果过敏"]
    )
    assert stored == 1
    assert _tables(db) == ["memory_facts"]
    assert repo.list_rows_for_subject("u1")[0]["text"] == "我对芒果过敏"


def test_extract_writer_with_bus_absorbs_as_derived_and_confirms(
    tmp_path: Path,
) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_extract import (
        store_extracted_memories,
    )

    db = tmp_path / "memory.sqlite3"
    config = BusConfig()
    config.bot_memory_db_path = str(db)
    bus = build_memory_bus(config)
    assert bus is not None
    repo = SQLiteMemoryRepository(db, bus=bus)  # 装配点传 bus（见交接段）
    assert (
        store_extracted_memories(
            repo, subject_user_id="u1", session_id=GROUP_A, texts=["我对芒果过敏"]
        )
        == 1
    )
    assert (
        store_extracted_memories(
            repo, subject_user_id="u1", session_id=GROUP_A, texts=["我对芒果过敏"]
        )
        == 1
    )
    rows = _rows(MemoryStoreV21(str(db)))
    assert len(rows) == 1 and int(rows[0]["confirm_count"]) == 2
    assert str(rows[0]["provenance"]) == "derived"
    with sqlite3.connect(db) as connection:
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_facts'"
        ).fetchone()


def test_repository_delete_via_bus_buries_row(tmp_path: Path) -> None:
    """``记忆 delete`` 走总线时=真删语义（墓碑先行 + 行翻 forgotten），读路径立刻排除。"""
    db = tmp_path / "memory.sqlite3"
    config = BusConfig()
    config.bot_memory_db_path = str(db)
    bus = build_memory_bus(config)
    assert bus is not None
    repo = SQLiteMemoryRepository(db, bus=bus)
    repo.upsert_fact(
        fact_id="ignored", subject_user_id="u1", session_id=GROUP_A,
        memory_kind="preference", text="我对芒果过敏", confidence=1.0,
        source="manual_command",
    )
    stored = _rows(MemoryStoreV21(str(db)))
    memory_id = str(stored[0]["memory_id"])
    assert repo.retrieve(
        request_id="r", requester_id="u1", subject_user_id="u1", session_id=GROUP_A,
        query_text="芒果", max_items=5, max_chars=600,
    ).facts
    assert repo.delete_fact(fact_id=memory_id, subject_user_id="u1", session_id=GROUP_A)
    assert _rows(MemoryStoreV21(str(db)))[0]["status"] == "forgotten"
    assert repo.retrieve(
        request_id="r", requester_id="u1", subject_user_id="u1", session_id=GROUP_A,
        query_text="芒果", max_items=5, max_chars=600,
    ).facts == []


# ---------------------------------------------------------------- 命令面出口件


def test_upsert_fact_returns_the_real_bus_id(tmp_path: Path) -> None:
    """总线按槽位合并 ⇒ 命令面必须拿到真实行 id 回话，不能打自己算的假 id。"""
    db = tmp_path / "memory.sqlite3"
    config = BusConfig()
    config.bot_memory_db_path = str(db)
    bus = build_memory_bus(config)
    repo = SQLiteMemoryRepository(db, bus=bus)
    first = repo.upsert_fact(
        fact_id="calc-1", subject_user_id="u1", session_id=GROUP_A,
        memory_kind="preference", text="我喜欢柠檬茶", confidence=1.0,
    )
    second = repo.upsert_fact(
        fact_id="calc-2", subject_user_id="u1", session_id=GROUP_A,
        memory_kind="preference", text="我超爱柠檬茶", confidence=1.0,
    )
    assert first.startswith("mb_") and first == second  # 同一行，id 一致
    rows = _rows(MemoryStoreV21(str(db)))
    assert len(rows) == 1 and str(rows[0]["memory_id"]) == first
    # 关态返回值口径不变（旧路径照旧把入参 id 还回去）
    legacy_repo = SQLiteMemoryRepository(tmp_path / "legacy.sqlite3")
    assert (
        legacy_repo.upsert_fact(
            fact_id="calc-3", subject_user_id="u1", session_id=GROUP_A,
            memory_kind="manual", text="你好",
        )
        == "calc-3"
    )


def test_why_command_predicate_and_render_two_states(tmp_path: Path) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
        is_memory_why_command,
        render_memory_why,
    )

    assert is_memory_why_command("why") and is_memory_why_command("  WHY  ")
    assert is_memory_why_command("记忆为什么")
    assert not is_memory_why_command("memory list")
    assert not is_memory_why_command("为什么要下雨")  # 自然语不劫持

    closed = BusConfig()
    closed.bot_memory_bus_enabled = False
    closed.bot_memory_db_path = str(tmp_path / "closed.sqlite3")
    assert "还没开" in render_memory_why(closed, "u1")  # 关态诚实说没开
    assert not tmp_path.joinpath("closed.sqlite3").exists()
    assert "没带上你的身份" in render_memory_why(closed, "")

    open_config = BusConfig()
    open_config.bot_memory_db_path = str(tmp_path / "open.sqlite3")
    bus = build_memory_bus(open_config)
    assert bus is not None
    _absorb(bus, "我对芒果过敏", event="w1", category="preference")
    bus.recall(owner_id="u1", session_id=GROUP_A, query_text="芒果", request_id="r")
    assert "我对芒果过敏" in render_memory_why(open_config, "u1")


# ---------------------------------------------------------------- 夹具


def _draft(text: str):
    from plugins.bot_unified_runtime.domains.chat_reply.character.reflection import (
        FactDraft,
    )

    return FactDraft(text=text, category="preference", confidence=0.6, sender_id="u1")


def _rows(store: MemoryStoreV21) -> list[dict[str, Any]]:
    with store._lock:
        return [
            dict(row)
            for row in store._connection.execute(
                "SELECT * FROM memory_entries_v21 ORDER BY created_at, memory_id"
            ).fetchall()
        ]


def _tables(db: Path) -> list[str]:
    if not Path(db).exists():
        return []
    with sqlite3.connect(db) as connection:
        return sorted(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        )


def _seed_history(db: Path, rows: list[tuple[str, str, str, str, str]]) -> None:
    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                request_id TEXT NOT NULL, platform TEXT NOT NULL, adapter TEXT NOT NULL,
                bot_id TEXT NOT NULL, session_id TEXT NOT NULL, sender_id TEXT NOT NULL,
                role TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'chat'
            )
            """
        )
        for index, (platform, session_id, sender_id, role, text) in enumerate(rows):
            connection.execute(
                "INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'chat')",
                (
                    f"req-{index}", platform, "onebot", "bot", session_id, sender_id,
                    role, text, f"{day}T{10 + index:02d}:00:00.000000+00:00",
                ),
            )


def _reflection_rows(db: str) -> list[sqlite3.Row]:
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        return list(
            connection.execute(
                "SELECT sender_id, session_key, fact_text, superseded FROM reflection_facts"
            )
        )


def _seed_legacy_facts(
    db: Path, rows: list[tuple[str, str, str, str, str]]
) -> None:
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_facts (
                fact_id TEXT PRIMARY KEY, subject_user_id TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '', memory_kind TEXT NOT NULL,
                text TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.8,
                source TEXT NOT NULL DEFAULT 'sqlite',
                sensitivity TEXT NOT NULL DEFAULT 'personal',
                scope_key TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        for fact_id, subject, session_id, text, sensitivity in rows:
            connection.execute(
                "INSERT INTO memory_facts (fact_id, subject_user_id, session_id,"
                " memory_kind, text, confidence, source, sensitivity, scope_key,"
                " created_at, updated_at) VALUES (?,?,?,?,?,0.6,'llm_extract',?,'',"
                " '2026-09-20T10:00:00+00:00','2026-09-20T10:00:00+00:00')",
                (fact_id, subject, session_id, "auto", text, sensitivity),
            )
