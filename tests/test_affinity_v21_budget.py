"""V2.1 好感度滚动预算补遗回归（A4 席第二波，规格 §2.2/§2.3 剩余条款）。

覆盖（承接 tests/test_affinity_v21.py 已锁的①拒答解耦/②预算钳制/③observe_points）：
⑥source_event_id 事务内幂等——重复事件只返回既有结果，不重复扣加；
⑦interaction_cooldown_seconds=60——去刷分、不阻止正常回复（计数器/标签照常）；
⑧预算按 (principal_id, bot_id) 跨会话汇总——切群不重置、跨 bot 隔离；
⑨passive_decay 默认 false（缺席不默认扣分；政策门开启后回归语义原样）；
⑩poke 增益默认 0.1 分且 24h≤0.5 分（config 注册域 affinity）；
⑪6h≤24h 预算常量校验；
⑫normalize_legacy_points 唯一适配器（×100 只此一处，points 边界钳制）。

全部离线 tmp_path + 注入时钟；不触碰生产库。
"""

from __future__ import annotations

import sqlite3

import pytest

import plugins.bot_unified_runtime.domains.chat_reply.character.affinity as affinity_module
from plugins.bot_unified_runtime.character.affinity import (
    _BUDGET_MAX_LOSS_6H_POINTS,
    _BUDGET_MAX_LOSS_24H_POINTS,
    _INTERACTION_COOLDOWN_SECONDS,
    _PASSIVE_DECAY_ENABLED,
    DynamicAffinityStore,
    normalize_legacy_points,
)

_DAY_SECONDS = 86400.0


class _Clock:
    """可手动推进的注入时钟（秒）。"""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _store(tmp_path, clock: _Clock, name: str = "affinity.sqlite3") -> DynamicAffinityStore:
    return DynamicAffinityStore(tmp_path / name, clock=clock)


def _log_rows(db_path: object, sender_id: str | None = None) -> list[tuple]:
    with sqlite3.connect(str(db_path)) as connection:
        if sender_id is None:
            return connection.execute(
                "SELECT sender_id, bot_id, applied_at, delta, source_event_id"
                " FROM affinity_delta_log ORDER BY applied_at"
            ).fetchall()
        return connection.execute(
            "SELECT sender_id, bot_id, applied_at, delta, source_event_id"
            " FROM affinity_delta_log WHERE sender_id = ? ORDER BY applied_at",
            (sender_id,),
        ).fetchall()


# ---------------------------------------------------------------------------
# ⑥ source_event_id 幂等：重复事件返回既有结果，不重复扣加
# ---------------------------------------------------------------------------

def test_duplicate_source_event_id_returns_existing_result(tmp_path) -> None:
    clock = _Clock()
    db = tmp_path / "affinity.sqlite3"
    store = _store(tmp_path, clock)
    first = store.observe_points(
        "u1", -3.0, source="probe", source_event_id="evt-1"
    )
    # 单事件负向 1 分封顶：-3 分申请只落 -1 分。
    assert first == pytest.approx(0.09, abs=1e-9)

    # 同一事件重放（同一 id）：返回既有结果，不重复扣加。
    second = store.observe_points(
        "u1", -3.0, source="probe", source_event_id="evt-1"
    )
    assert second == pytest.approx(first), "重复事件必须返回既有结果"
    assert len(_log_rows(db, "u1")) == 1, "重复事件不得再落预算日志"

    # 不同事件 id：正常按预算走（6h 预算还剩 1 分）。
    clock.advance(120)
    third = store.observe_points(
        "u1", -3.0, source="probe", source_event_id="evt-2"
    )
    assert third == pytest.approx(0.08, abs=1e-9)


def test_duplicate_source_event_id_via_observe_is_idempotent(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    first = store.observe("u1", "insult", source_event_id="evt-a")
    assert first == pytest.approx(0.09, abs=1e-9)
    replay = store.observe("u1", "insult", source_event_id="evt-a")
    assert replay == pytest.approx(first, abs=1e-12)
    # 重复事件也不重复累计互动计数（既有结果原样返回）。
    snapshot = store.snapshot("u1")
    interactions = store.factor_profile("u1")["interaction_count"]
    assert interactions == 1
    assert snapshot["affinity"] == pytest.approx(0.09, abs=1e-9)


# ---------------------------------------------------------------------------
# ⑦ interaction_cooldown 60s：去刷分，不阻止正常回复
# ---------------------------------------------------------------------------

def test_interaction_cooldown_zeroes_rapid_repeat_scores(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    first = store.observe("u1", "insult")
    assert first == pytest.approx(0.09, abs=1e-9), "冷却窗口外的首次计分不受影响"
    # 10s 后再骂：冷却期内记 0 分（不阻止回复，只是不重复计分）。
    clock.advance(10)
    assert store.observe("u1", "insult") == pytest.approx(0.09, abs=1e-9)
    # 61s 后：冷却已过，按滚动预算继续（6h 预算还剩 1 分）。
    clock.advance(51)
    assert store.observe("u1", "insult") == pytest.approx(0.08, abs=1e-9)


def test_interaction_cooldown_is_sixty_seconds_by_policy(tmp_path) -> None:
    assert _INTERACTION_COOLDOWN_SECONDS == 60.0


def test_cooldown_does_not_block_counters_tags_or_other_senders(tmp_path) -> None:
    clock = _Clock()
    db = tmp_path / "affinity.sqlite3"
    store = _store(tmp_path, clock)
    # 冷却期内计 0 分，但 insult 计数与印象标签照常累计（不阻止关系记录）。
    store.observe("u1", "insult")
    clock.advance(10)
    store.observe("u1", "insult")
    with sqlite3.connect(str(db)) as connection:
        row = connection.execute(
            "SELECT insult_count FROM user_affinity WHERE sender_id = 'u1'"
        ).fetchone()
    assert int(row[0]) == 2
    assert "口无遮拦" in store.snapshot("u1")["tags"]
    # 冷却按 (principal, bot) 维度：u1 冷却中不影响 u2 计分。
    assert store.observe("u2", "insult") == pytest.approx(0.09, abs=1e-9)


def test_neutral_and_budget_exhausted_events_do_not_extend_cooldown(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # 中性消息零增量：不占预算、不落日志，也不应触发冷却。
    store.observe("u1", "neutral")
    clock.advance(1)
    assert store.observe("u1", "insult") == pytest.approx(0.09, abs=1e-9), (
        "中性行为不得开启冷却窗"
    )


# ---------------------------------------------------------------------------
# ⑧ 预算按 (principal_id, bot_id) 汇总：切群不重置、跨 bot 隔离
# ---------------------------------------------------------------------------

def test_budget_shared_across_groups_for_same_principal_bot(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # 群 g1 用掉 6h 损失预算 2 分（两次间隔超冷却）。
    store.observe("u1", "insult", group_id="g1")
    clock.advance(61)
    store.observe("u1", "insult", group_id="g1")
    clock.advance(61)
    # 切到群 g2：同 (principal, bot) 预算继续，不得因切群重置。
    assert store.observe("u1", "insult", group_id="g2") == pytest.approx(0.08, abs=1e-9)


def test_budget_isolated_across_bots_for_same_principal(tmp_path) -> None:
    clock = _Clock()
    db = tmp_path / "affinity.sqlite3"
    store = _store(tmp_path, clock)
    # bot b1 侧用满 6h 损失预算 2 分。
    store.observe("u1", "insult", bot_id="b1")
    clock.advance(61)
    store.observe("u1", "insult", bot_id="b1")
    clock.advance(61)
    # bot b2 侧（同 principal）预算独立：b1 预算耗尽不得冻结 b2 计分。
    # 存储口径说明：分数行按 sender 共享（内部存储保持现状），隔离的是预算维度——
    # b2 的事件仍按自己的预算放行（再扣 1 分），落库分数在共享行上继续走。
    before = store.snapshot("u1")["affinity"]
    assert store.observe("u1", "insult", bot_id="b2") == pytest.approx(before - 0.01, abs=1e-9)
    # bot 维度落在日志行上（对账口径）。
    rows = _log_rows(db, "u1")
    assert {row[1] for row in rows} == {"b1", "b2"}


def test_gain_budget_isolated_across_bots(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # bot b1 侧用满 24h 全局增益 3 分。
    for _ in range(3):
        store.observe_points("u1", 1.0, source="probe", bot_id="b1")
        clock.advance(61)
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.13, abs=1e-9)
    # bot b2 侧预算独立：b1 耗尽不冻结 b2 增益（共享分数行 +1 分照常入账）。
    assert store.observe_points("u1", 1.0, source="probe", bot_id="b2") == pytest.approx(
        0.14, abs=1e-9
    )


# ---------------------------------------------------------------------------
# ⑨ passive_decay 默认 false：缺席不默认扣分
# ---------------------------------------------------------------------------

def test_passive_decay_disabled_by_default_policy() -> None:
    assert _PASSIVE_DECAY_ENABLED is False, "规格 §2.3：缺席不默认扣分"


def test_absence_does_not_decay_score_by_default(tmp_path) -> None:
    clock = _Clock()
    db = tmp_path / "seed.sqlite3"
    store = _store(tmp_path, clock, name="seed.sqlite3")
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO user_affinity (sender_id, affinity, interaction_count, updated_at)"
            " VALUES ('u1', 0.5, 1, ?)",
            (affinity_module._format_utc(clock.now),),
        )
    clock.advance(30 * _DAY_SECONDS)
    store.observe("u1", "neutral")
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.5, abs=1e-9), (
        "passive_decay 默认关：闲置 30 天不得向基准回归"
    )


def test_passive_decay_enabled_restores_legacy_regression(tmp_path, monkeypatch) -> None:
    # 政策门显式开启时，旧 §3 惰性回归语义原样（policy_revision 迁移，不两套并存）。
    monkeypatch.setattr(affinity_module, "_PASSIVE_DECAY_ENABLED", True)
    clock = _Clock()
    db = tmp_path / "seed2.sqlite3"
    store = _store(tmp_path, clock, name="seed2.sqlite3")
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO user_affinity (sender_id, affinity, interaction_count, updated_at)"
            " VALUES ('u1', 0.5, 1, ?)",
            (affinity_module._format_utc(clock.now),),
        )
    clock.advance(10 * _DAY_SECONDS)
    assert store.observe("u1", "neutral") == pytest.approx(0.40, abs=1e-9)


# ---------------------------------------------------------------------------
# ⑩ poke 增益默认 0.1 分且 24h≤0.5 分（config 注册域 affinity）
# ---------------------------------------------------------------------------

def test_poke_gain_defaults_match_spec() -> None:
    from plugins.bot_unified_runtime.config import Config

    config = Config()
    assert float(config.bot_poke_affinity_delta) == 0.1, "规格 §2.3 poke_gain_points=0.1 分"
    assert float(config.bot_poke_affinity_daily_max) == 0.5, "规格 §2.3 poke_gain_24h=0.5 分"


def test_poke_points_flow_through_observe_points_with_spec_defaults(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # 0.1 分/戳、24h 0.5 分封顶：第 6 戳起零增益（戳间隔超冷却，验证专项预算本身）。
    values: list[float] = []
    for _ in range(6):
        values.append(
            store.observe_points(
                "u1", 0.1, behavior="positive", source="poke", source_cap_24h_points=0.5
            )
        )
        clock.advance(61)
    assert values[-1] == pytest.approx(0.105, abs=1e-9), "poke 24h 专项预算 0.5 分封顶"


# ---------------------------------------------------------------------------
# ⑪ 预算常量校验：6h ≤ 24h
# ---------------------------------------------------------------------------

def test_budget_window_invariant_validated() -> None:
    assert _BUDGET_MAX_LOSS_6H_POINTS <= _BUDGET_MAX_LOSS_24H_POINTS
    # 校验器存在且对违例配置报错（防后续调参把 6h 配得比 24h 还大）。
    validator = getattr(affinity_module, "ensure_budget_invariants", None)
    assert callable(validator), "缺少 ensure_budget_invariants 校验器"
    validator()  # 当前常量必须通过
    with pytest.raises(ValueError):
        validator(max_loss_6h_points=5.0, max_loss_24h_points=4.0)


# ---------------------------------------------------------------------------
# ⑫ normalize_legacy_points 唯一适配器 + points 边界
# ---------------------------------------------------------------------------

def test_normalize_legacy_points_multiplies_once_and_clamps() -> None:
    assert normalize_legacy_points(0.005) == pytest.approx(0.5)
    assert normalize_legacy_points(0.1) == pytest.approx(10.0)
    assert normalize_legacy_points(-1.0) == pytest.approx(-100.0)
    assert normalize_legacy_points(1.0) == pytest.approx(100.0)
    # 越界内部值钳到 points 边界（防 unit mismatch 二次放大）。
    assert normalize_legacy_points(5.0) == pytest.approx(100.0)
    assert normalize_legacy_points(-5.0) == pytest.approx(-100.0)


def test_observe_points_clamps_points_domain(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # points 超 [-100,100] 在服务边界钳制（此后仍有预算兜底）。
    assert store.observe_points("u1", 500.0, source="probe") == pytest.approx(0.13, abs=1e-9)
    clock.advance(61)
    assert store.observe_points("u2", -500.0, source="probe") == pytest.approx(0.09, abs=1e-9)
