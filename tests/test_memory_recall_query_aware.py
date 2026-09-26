"""需求 11 召回腿活性锁：反思记忆必须按**本轮查询**选，不再按新近度倒货。

席位 S-T-MEM-2（2026-09-25-goal18-wave）。全部离线、只写 tmp_path，
不碰 ChatBot_Runtime 真库。

本件的存在理由（审计实锤）：生产链路（bus 关闭态）里
``ReflectionMemoryProvider.retrieve`` 收了 ``query_text`` 就丢——不管问什么
都返回「最近 N 条」。因此本文件的命门是**同库同数据、只换 query_text**
的两问对照（§双问共享夹具）：任何把查询再丢一次的改法（传空串/不转发/
退回纯 recency）都会当场打红，且反向注毒实跑过（红数见席位日志）。

打分口径不许野化：权重、词元化、相似度三把尺全部对总线核身
（§与总线同尺），本腿只允许两处有依据的偏差（strength=confidence、
零相关时不退强度——宁缺勿滥）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import reflection as refl
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    _DEFAULT_WEIGHTS,
    fact_signature,
    settings_from_config,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
    _similarity as _bus_similarity,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reflection import (
    ReflectionFact,
    ReflectionMemoryProvider,
    ReflectionStore,
    build_reflection_memory_provider,
    query_is_recall_worthy,
    rank_facts_by_query,
    token_similarity,
)

FIXED_NOW = datetime(2026, 9, 25, 0, 0, 0, tzinfo=UTC)
SESSION = "private:u1"          # 读侧真实入参（NoneBot 裸键形态）
WRITE_SESSION = "qq:private:u1"  # 写侧历史复合键（digest.session_key）

# 双问共享夹具的四条事实：猫是**最老**的一条（新近度排序下必然垫底/出局，
# 相关性排序下必须被点名），Rust 是最新的一条（旧行为的第一名）。
# 词面重合按总线口径＝ CJK 二元组 + 拉丁词（单词元查询与长事实天然零
# 重合，这是总线尺子的既有语义，选词都保证与两问的二元组重合情况如下：
# QUERY_CAT 命中且仅命中 CAT；QUERY_CITY 命中且仅命中 CITY）。
CAT_FACT = "我家猫叫橘子"
CITY_FACT = "住在海边城市天气潮湿"
TEA_FACT = "下午习惯一杯柠檬茶"
RUST_FACT = "最近在学Rust"
QUERY_CAT = "我家猫叫什么名字"
QUERY_CITY = "她住的城市的天气"

_SEED_DAYS = {
    CAT_FACT: 4,     # 最早
    CITY_FACT: 3,
    TEA_FACT: 2,
    RUST_FACT: 1,    # 最新
}


class _StepClock:
    """可变 epoch 钟：每落一条事实挪一天，制造确定的新近度全序。"""

    def __init__(self, start_epoch: float) -> None:
        self.value = start_epoch

    def __call__(self) -> float:
        return self.value


def _provider(tmp_path: Path, facts: dict[str, float]) -> ReflectionMemoryProvider:
    """按 {事实文本: 几天前} 建库并给出固定时钟的 provider（猫最老、Rust 最新）。"""
    clock = _StepClock(0.0)
    store = ReflectionStore(tmp_path / "reflection.sqlite3", clock=clock)
    digest = store.save_digest(
        session_key=WRITE_SESSION, scope_date="2026-09-20", summary="s", turn_count=4
    )
    base = FIXED_NOW.timestamp()
    for text, days_ago in facts.items():
        clock.value = base - days_ago * 86400.0
        store.save_facts(digest, "u1", [refl.FactDraft(text, "fact", 0.8)])
    return ReflectionMemoryProvider(store, clock=lambda: FIXED_NOW)


def _recall(
    provider: ReflectionMemoryProvider, query: str, **overrides: Any
) -> list[str]:
    kwargs: dict[str, Any] = {
        "request_id": "req",
        "requester_id": "u1",
        "subject_user_id": "u1",
        "session_id": SESSION,
        "query_text": query,
        "max_items": 5,
        "max_chars": 900,
    }
    kwargs.update(overrides)
    return [str(fact["text"]) for fact in provider.retrieve(**kwargs).facts]


@pytest.fixture()
def provider(tmp_path: Path) -> ReflectionMemoryProvider:
    return _provider(
        tmp_path,
        {CAT_FACT: 4, CITY_FACT: 3, TEA_FACT: 2, RUST_FACT: 1},
    )


# ---------------------------------------------------------------- 双问共享夹具
# 命门锁：同一份库同一批数据，只换 query_text，选出来的必须不同。
# 这是唯一能证明 query_text 真被消费的写法——「字段存在」测试一律不要。


def test_two_queries_share_one_fixture_pick_different_facts(
    provider: ReflectionMemoryProvider,
) -> None:
    # 问猫：返回的就是猫那条，且注入文本不混任何无关条目
    # （CITY/TEA/RUST 与「我家猫叫什么名字」词面零重合 → 地板出局）。
    picked = _recall(provider, QUERY_CAT)
    assert CAT_FACT in picked
    assert picked == [CAT_FACT]
    joined = "\n".join(picked)
    for noise in (CITY_FACT, TEA_FACT, RUST_FACT):
        assert noise not in joined

    # 问天气：猫那条必须不回来；「住在海边城市天气潮湿」才是相关的。
    other = _recall(provider, QUERY_CITY)
    assert CAT_FACT not in other
    assert other == [CITY_FACT]


def test_different_queries_never_return_identical_sets(
    provider: ReflectionMemoryProvider,
) -> None:
    """两问结果集不等——纯 recency 的实现在这里必翻车（两问同答）。"""
    assert _recall(provider, QUERY_CAT) != _recall(provider, QUERY_CITY)


def test_stale_relevant_fact_wins_over_fresh_at_max_items_1(
    provider: ReflectionMemoryProvider,
) -> None:
    """max_items=1 时问猫仍得猫：旧行为（最近 N 条）这里返回的会是最新的 Rust。"""
    assert _recall(provider, QUERY_CAT, max_items=1) == [CAT_FACT]


def test_relevant_fact_outside_recency_window_is_reached(tmp_path: Path) -> None:
    """猫是全库最老、且新近噪音多于 max_items 若干倍时也要被调到。

    旧行为候选窗=max_items 条最新 → 相关的老事实根本进不了选择面；
    新行为先超取候选（4×）再打分，老而相关的必须回来。
    """
    noise = {
        "键盘青轴打字声音很响": 0.5,
        "橙色的窗帘昨天洗过了": 0.8,
        "楼下的便利店换老板了": 1.1,
        "地铁二号线今早限流": 1.4,
        "冰箱里的酸奶过期两天": 1.7,
        "新买的台灯有点晃眼": 2.0,
    }
    provider = _provider(tmp_path, {CAT_FACT: 6, **noise})
    picked = _recall(provider, QUERY_CAT, max_items=2)
    assert picked == [CAT_FACT]


# ---------------------------------------------------------------- 需求2：短查询门


def test_empty_or_tiny_query_never_injects(
    provider: ReflectionMemoryProvider,
) -> None:
    for query in ("", "   ", "嗯", "好", "。", "？"):
        assert _recall(provider, query) == [], f"查询 {query!r} 触发了记忆注入"
    assert not query_is_recall_worthy("嗯")
    assert not query_is_recall_worthy("")
    assert query_is_recall_worthy("我家猫叫什么名字")


def test_zero_overlap_query_injects_nothing(
    provider: ReflectionMemoryProvider,
) -> None:
    """有长度的查询但全库零相关 ⇒ 空（宁缺勿滥档；旧行为是照倒最近 N 条）。"""
    assert _recall(provider, "量子纠缠与拓扑绝缘体") == []


# ---------------------------------------------------------------- 红线3：群私隔离


def test_private_facts_never_enter_group_context(
    provider: ReflectionMemoryProvider,
) -> None:
    """群会话里逐字命中私聊事实的查询，也必须零召回（既有契约不破）。"""
    assert (
        _recall(
            provider,
            QUERY_CAT,
            session_id="group_1108838060_3865067623",
        )
        == []
    )


def test_group_fact_stays_inside_its_own_group(tmp_path: Path) -> None:
    clock = _StepClock(FIXED_NOW.timestamp() - 86400)
    store = ReflectionStore(tmp_path / "reflection.sqlite3", clock=clock)
    digest = store.save_digest(
        session_key="qq:group_777_u1", scope_date="2026-09-24", summary="s", turn_count=1
    )
    store.save_facts(digest, "u1", [refl.FactDraft("群里在组织羽毛球", "activity", 0.8)])
    provider = ReflectionMemoryProvider(store, clock=lambda: FIXED_NOW)
    in_group = _recall(provider, "羽毛球", session_id="group_777_u1")
    assert in_group == ["群里在组织羽毛球"]
    # 换个群 / 回到私聊都拿不到（查询逐字命中也不给）。
    assert _recall(provider, "羽毛球", session_id="group_888_u1") == []
    assert _recall(provider, "群里在组织羽毛球", session_id=SESSION) == []


# ---------------------------------------------------------------- 隐私闸与形状


def test_payload_shape_and_owner_gate_preserved(
    provider: ReflectionMemoryProvider,
) -> None:
    """facts dict 键形状与 source/sensitivity 逐键不变；非本人查询零结果。"""
    result = provider.retrieve(
        request_id="req",
        requester_id="u1",
        subject_user_id="u1",
        session_id=SESSION,
        query_text=QUERY_CAT,
        max_items=5,
        max_chars=900,
    )
    assert len(result.facts) == 1
    fact = result.facts[0]
    assert set(fact) == {
        "fact_id",
        "kind",
        "text",
        "source",
        "sensitivity",
        "scope_key",
    }
    assert fact["kind"] == "reflection"
    assert fact["source"] == "reflection"
    assert fact["sensitivity"] == "personal"
    assert fact["scope_key"] == f"session:{WRITE_SESSION}"
    assert result.confidence == pytest.approx(0.8)

    stranger = provider.retrieve(
        request_id="req2",
        requester_id="u2",
        subject_user_id="u1",
        session_id=SESSION,
        query_text=QUERY_CAT,
        max_items=5,
        max_chars=900,
    )
    assert stranger.facts == []


# ---------------------------------------------------------------- 与总线同尺


def test_token_similarity_is_byte_identical_to_bus_principle() -> None:
    """本腿的相似度基元与总线私有 _similarity 在真样本上逐点等值（防口径漂移）。"""
    samples = [
        (QUERY_CAT, CAT_FACT),
        (QUERY_CAT, CITY_FACT),
        (QUERY_CITY, CITY_FACT),
        ("芒果", "我对芒果过敏"),
        ("我喜欢什么", "我喜欢猫"),
        ("rust", "最近在学Rust"),
        ("", CAT_FACT),
        ("量子纠缠", "我家猫叫橘子"),
    ]
    for left_text, right_text in samples:
        left = fact_signature(left_text).tokens
        right = fact_signature(right_text).tokens
        assert token_similarity(left, right) == _bus_similarity(left, right)
    assert token_similarity(frozenset(), frozenset({"猫"})) == 0.0
    assert token_similarity(frozenset({"猫"}), frozenset()) == 0.0


def test_default_weights_are_the_bus_weights_verbatim() -> None:
    """反思腿缺省权重=总线 _DEFAULT_WEIGHTS 原值（需求4：不引入新权重）。"""
    weights = settings_from_config(object()).weights
    assert weights == _DEFAULT_WEIGHTS
    assert weights["w_rel"] == 0.45 and weights["w_str"] == 0.35


def _fact(fact_id: str, text: str, *, confidence: float, days: float) -> ReflectionFact:
    created = datetime.fromtimestamp(
        FIXED_NOW.timestamp() - days * 86400, tz=UTC
    ).isoformat()
    return ReflectionFact(
        fact_id=fact_id,
        sender_id="u1",
        session_key=WRITE_SESSION,
        fact_text=text,
        category="fact",
        confidence=confidence,
        source_digest_id="d1",
        created_at=created,
    )


def test_rank_formula_orders_by_relevance_then_strength_then_recency() -> None:
    facts = [
        _fact("f1", "我家猫叫橘子", confidence=0.6, days=5),
        _fact("f2", "猫粮换了新牌子", confidence=0.95, days=1),
        _fact("f3", "键盘青轴打字声音很响", confidence=0.9, days=0.5),
    ]
    weights = dict(_DEFAULT_WEIGHTS)
    # 查询与 f1 共享二元组「猫叫」、与 f2 共享「猫粮」，与 f3 零重合。
    ranked = rank_facts_by_query(
        facts, "猫叫和猫粮", weights=weights, now=FIXED_NOW
    )
    # 两条猫相关都活下来，零相关的 f3 出局（地板）；f2 靠强度+新近度领先。
    assert [fact.fact_id for fact in ranked] == ["f2", "f1"]
    # 纯强度档：相关性、新近度都不计分 ⇒ f1 与 f2 只按 confidence 排。
    strength_only = {"w_rel": 0.0, "w_str": 1.0, "w_rec": 0.0}
    assert [
        fact.fact_id
        for fact in rank_facts_by_query(
            [facts[0], facts[1]], "猫叫和猫粮", weights=strength_only, now=FIXED_NOW
        )
    ] == ["f2", "f1"]
    # 同 relevance/同 confidence 时纯新近度档能区分开（公式三腿都真实参与）。
    twin_a = _fact("a", "猫叫了一声", confidence=0.8, days=4)
    twin_b = _fact("b", "猫叫了三声", confidence=0.8, days=1)
    recency_only = {"w_rel": 0.0, "w_str": 0.0, "w_rec": 1.0}
    assert [
        fact.fact_id
        for fact in rank_facts_by_query(
            [twin_a, twin_b], "猫叫了几声", weights=recency_only, now=FIXED_NOW
        )
    ] == ["b", "a"]


def test_rank_with_empty_query_returns_input_untouched() -> None:
    """无查询模式（旧「最近 N 条」兼容口）：空串进、原序出、不地板。

    正常生产入口被 query_is_recall_worthy 挡在门外；这个口留给
    显式无查询调用与反向锁注毒——也正因此，retrieve 一旦把查询丢成
    空串，双问锁立刻变红（本波注毒实跑见席位日志）。
    """
    facts = [_fact("f1", CAT_FACT, confidence=0.8, days=5)]
    assert rank_facts_by_query(
        facts, "", weights=dict(_DEFAULT_WEIGHTS), now=FIXED_NOW
    ) == facts


# ---------------------------------------------------------------- 权重装配接线


def test_build_provider_wires_config_weights(tmp_path: Path, monkeypatch) -> None:
    """装配口把 config 递给 provider，且 provider 真把该 config 的权重喂给打分器。"""
    provider = _provider(
        tmp_path, {CAT_FACT: 4, CITY_FACT: 3, TEA_FACT: 2, RUST_FACT: 1}
    )

    class _Cfg:
        bot_reflection_enabled = True
        bot_reflection_db_path = str(tmp_path / "reflection.sqlite3")

    built = build_reflection_memory_provider(_Cfg())
    assert built._config is not None

    captured: list[dict[str, float]] = []
    real_rank = refl.rank_facts_by_query

    def _spy(facts, query_text, *, weights, now):
        captured.append(dict(weights))
        return real_rank(facts, query_text, weights=weights, now=now)

    monkeypatch.setattr(refl, "rank_facts_by_query", _spy)
    assert _recall(provider, QUERY_CAT) == [CAT_FACT]
    assert captured and captured[0] == _DEFAULT_WEIGHTS


def test_weights_override_changes_selection(tmp_path: Path) -> None:
    """配置真能改排序：把 w_rel 拉满 / 清零，同一份库同一句问话结果相反。"""
    store_clock = _StepClock(0.0)
    store = ReflectionStore(tmp_path / "reflection.sqlite3", clock=store_clock)
    digest = store.save_digest(
        session_key=WRITE_SESSION, scope_date="2026-09-20", summary="s", turn_count=2
    )
    base = FIXED_NOW.timestamp()
    for text, days, conf in (
        (CAT_FACT, 4, 0.6),
        ("我家猫是橘色的", 1, 0.95),
    ):
        store_clock.value = base - days * 86400
        store.save_facts(digest, "u1", [refl.FactDraft(text, "fact", conf)])

    class _RelHeavy:
        bot_memory_relevance_weights = '{"w_rel": 10.0, "w_str": 0.001, "w_rec": 0.001}'

    class _RelZero:
        bot_memory_relevance_weights = '{"w_rel": 0.0, "w_str": 1.0, "w_rec": 0.0}'

    heavy = ReflectionMemoryProvider(store, config=_RelHeavy, clock=lambda: FIXED_NOW)
    zero = ReflectionMemoryProvider(store, config=_RelZero, clock=lambda: FIXED_NOW)
    # 相关性主导：与查询重合更高的「我家猫叫橘子」（共享 我家/家猫/猫叫）在前；
    # 纯强度档：置信度高的「我家猫是橘色的」（0.95）反超前。
    assert _recall(heavy, QUERY_CAT) == [CAT_FACT, "我家猫是橘色的"]
    assert _recall(zero, QUERY_CAT) == ["我家猫是橘色的", CAT_FACT]
