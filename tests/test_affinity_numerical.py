"""好感度数值化回归（C组，独立命名）：docs/affinity-design.md §3 v3 验收口径。

模型：基数 10（内部 0.1）；步长 = 因子表 × 幂律衰减 g(x) × 个人系数 m(uid)；
靠近 0/100 步长连续缩小（log-log 线性，γ=1）；个人系数由 sender_id 确定性派生 ±15%。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.character.affinity import (
    DynamicAffinityStore,
    attitude_for_affinity,
    per_user_factor,
    tier_for_affinity,
)


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_days(self, days: float) -> None:
        self.now += days * 86400.0


def _store(tmp_path) -> DynamicAffinityStore:
    return DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_Clock())


def test_default_base_and_personal_factor_contract() -> None:
    # 个人系数：确定性、同 sender 恒定、±15% 带宽
    assert per_user_factor("u1") == per_user_factor("u1")
    assert 0.85 <= per_user_factor("u1") <= 1.15
    assert 0.85 <= per_user_factor("u2") <= 1.15
    # 初始 10 分落在「疏离」档（低开缓升，与样本榜卡口径一致）
    assert tier_for_affinity(0.1) == "distant"


def test_first_positive_step_uses_personal_factor(tmp_path) -> None:
    store = _store(tmp_path)
    affinity = store.observe("u1", "positive")
    # 基准点(0.1)处幂律衰减=1，步长=0.02×m
    assert abs(affinity - (0.1 + 0.02 * per_user_factor("u1"))) < 1e-9


def test_damping_shrinks_steps_near_extremes(tmp_path) -> None:
    store = _store(tmp_path)
    m1 = per_user_factor("u1")
    high = store.observe("u1", "neutral", delta_override=0.85)  # 0.95，距极值 0.05
    expected = 0.95 + 0.02 * m1 * (0.05 / 0.1)
    assert abs(high - 0.95) < 1e-9
    assert abs(store.observe("u1", "positive") - expected) < 1e-9

    m2 = per_user_factor("u2")
    low = store.observe("u2", "neutral", delta_override=-0.05)  # 0.05，距极值 0.05
    assert abs(low - 0.05) < 1e-9
    # 负向步长同样衰减：-0.10 × m2 × 0.5（步长小于剩余距离时 clamp 在 0）
    expected_low = max(0.0, 0.05 - 0.10 * m2 * (0.05 / 0.1))
    assert abs(store.observe("u2", "insult") - expected_low) < 1e-9


def test_mid_range_steps_are_full(tmp_path) -> None:
    store = _store(tmp_path)
    store.observe("u1", "neutral", delta_override=0.40)  # 0.5，中段全额
    m = per_user_factor("u1")
    assert abs(store.observe("u1", "positive") - (0.5 + 0.02 * m)) < 1e-9


def test_per_user_factors_differ_by_sender(tmp_path) -> None:
    factors = {per_user_factor(f"user-{i}") for i in range(12)}
    assert len(factors) > 1, "不同 sender 的个人系数应可区分"


def test_daily_cap_still_bounds_positive_gain(tmp_path) -> None:
    store = _store(tmp_path)
    last = 0.1
    for _ in range(15):
        last = store.observe("u1", "positive")
    # 前 10 次有效：总增益必然小于 10×全额步长
    assert last < 0.1 + 10 * 0.02 * per_user_factor("u1")
    settled = store.observe("u1", "positive")
    assert abs(settled - last) < 1e-12, "超每日上限后不再增减"


def test_lazy_regression_targets_new_base(tmp_path) -> None:
    clock = _Clock()
    store2 = DynamicAffinityStore(tmp_path / "reg.sqlite3", clock=clock)
    store2.observe("u1", "neutral", delta_override=0.40)  # 0.5
    clock.advance_days(10)
    # 回归目标=基数 0.1：闲置 10 天向 0.1 回归 0.10
    assert abs(store2.observe("u1", "neutral") - 0.40) < 1e-9
    clock.advance_days(40)
    assert abs(store2.observe("u1", "neutral") - 0.10) < 1e-9, "回归不超过基数"


def test_tier_boundaries_and_attitude_unchanged() -> None:
    assert tier_for_affinity(0.75) == "close"
    assert tier_for_affinity(0.45) == "friendly"
    assert tier_for_affinity(0.25) == "polite"
    assert tier_for_affinity(0.1) == "distant"
    assert "亲近" in attitude_for_affinity(0.80)
    assert "严厉" in attitude_for_affinity(0.10)


def test_delta_override_clamped_only(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.observe("u1", "neutral", delta_override=5.0) == 1.0
    assert store.observe("u2", "neutral", delta_override=-5.0) == 0.0


def test_clock_injection_drives_updated_at(tmp_path) -> None:
    import sqlite3

    clock = _Clock(1000.0)
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    store.observe("u1", "neutral")
    connection = sqlite3.connect(tmp_path / "affinity.sqlite3")
    row = connection.execute(
        "SELECT updated_at FROM user_affinity WHERE sender_id = 'u1'"
    ).fetchone()
    connection.close()
    assert row is not None
    assert row[0] == "1970-01-01T00:16:40Z"
