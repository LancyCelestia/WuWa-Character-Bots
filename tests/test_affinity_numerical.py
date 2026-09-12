"""好感度数值化回归（docs/affinity-design.md v4 线性版验收口径）。

模型：基准 0.1（展示 10）；步长 = 因子表 × 个人系数 m(uid)，全程线性（v3 幂律
阻尼 γ 已废除）；个人系数由 sender_id 确定性派生 ±15%；写入 clamp [-1,+1]；
存量 [0,1] 旧库值恒等沿用（无迁移）。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.character.affinity import (
    _IDLE_REGRESSION_PER_DAY,
    _IDLE_REGRESSION_START_DAYS,
    _SENTIMENT_HALF_LIFE_DAYS,
    DynamicAffinityStore,
    attitude_for_affinity,
    effective_delta,
    per_user_factor,
    tier_for_affinity,
    tier_name_for_affinity,
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
    # 基准 10 落在档0「友善（基准）」（docs §4：档0含10）
    assert tier_for_affinity(0.1) == 0
    assert tier_name_for_affinity(0.1) == "友善（基准）"


def test_first_positive_step_uses_personal_factor(tmp_path) -> None:
    store = _store(tmp_path)
    affinity = store.observe("u1", "positive")
    assert abs(affinity - (0.1 + 0.02 * per_user_factor("u1"))) < 1e-9


def test_linear_steps_stay_full_near_extremes() -> None:
    # v4 无阻尼：距极值 <0.1 步长仍全额（v3 的 (d/0.1)^γ 缩小已废除）
    m1 = per_user_factor("u1")
    assert abs(effective_delta("u1", "positive", 0.97) - 0.02 * m1) < 1e-12
    assert abs(effective_delta("u1", "positive", 0.05) - 0.02 * m1) < 1e-12
    m2 = per_user_factor("u2")
    assert abs(effective_delta("u2", "insult", -0.97) + 0.10 * m2) < 1e-12
    assert abs(effective_delta("u2", "insult", -0.05) + 0.10 * m2) < 1e-12


def test_linear_observe_paths(tmp_path) -> None:
    store = _store(tmp_path)
    # 新行从基准 0.1 出发：override 相对基准，0.1+0.87=0.97（近 +1 极值）
    high = store.observe("u1", "neutral", delta_override=0.87)
    assert abs(high - 0.97) < 1e-9
    # m ≤1.15 → 0.993 最大，不触发 clamp，正步全额
    assert abs(store.observe("u1", "positive") - (0.97 + 0.02 * per_user_factor("u1"))) < 1e-9

    # 0.1-1.07=-0.97（近 -1 极值）
    low = store.observe("u2", "neutral", delta_override=-1.07)
    assert abs(low + 0.97) < 1e-9
    # -0.97 - 0.10×m 会越下界：线性满步后 clamp 到 [-1,1]
    expected_low = max(-1.0, -0.97 - 0.10 * per_user_factor("u2"))
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
    # 前 10 次有效：总增益小于 10×全额步长×各因子上限（v5：第一印象 ±30%
    # 放大 + 说话温度 ≤1.4，正向首次印象会让好话来得更快——用户裁定语义）。
    assert last < 0.1 + 10 * 0.02 * 1.4 * 1.3 * per_user_factor("u1")
    settled = store.observe("u1", "positive")
    assert abs(settled - last) < 1e-12, "超每日上限后不再增减"


def test_regression_and_fadeout_constants_match_design() -> None:
    # §3 参数顶置常量：惰性回归 7 天起每日 0.01；淡出半衰期 insult 15 天、其余 30 天
    assert _IDLE_REGRESSION_START_DAYS == 7
    assert _IDLE_REGRESSION_PER_DAY == 0.01
    assert _SENTIMENT_HALF_LIFE_DAYS == {"positive": 30.0, "negative": 30.0, "insult": 15.0}


def test_lazy_regression_targets_new_base(tmp_path) -> None:
    clock = _Clock()
    store2 = DynamicAffinityStore(tmp_path / "reg.sqlite3", clock=clock)
    store2.observe("u1", "neutral", delta_override=0.40)  # 0.5
    clock.advance_days(10)
    # 回归目标=基准 0.1：闲置 10 天向 0.1 回归 0.10
    assert abs(store2.observe("u1", "neutral") - 0.40) < 1e-9
    clock.advance_days(40)
    assert abs(store2.observe("u1", "neutral") - 0.10) < 1e-9, "回归不超过基准"


def test_negative_side_regression_also_targets_base(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "regneg.sqlite3", clock=clock)
    # 新行从 0.1 出发：override -0.5 → -0.40
    store.observe("u1", "neutral", delta_override=-0.50)
    clock.advance_days(7)
    # 负半轴同样向基准回归：闲置 7 天 +0.07 → -0.33
    assert abs(store.observe("u1", "neutral") - (-0.33)) < 1e-9


def test_eight_tier_boundaries_left_closed_right_open() -> None:
    # docs §4：每档宽 25，左闭右开；最高档含 +100
    assert tier_for_affinity(-1.0) == -4
    assert tier_for_affinity(-0.75) == -3      # -75 属于档 -3（左闭）
    assert tier_for_affinity(-0.750001) == -4
    assert tier_for_affinity(-0.5) == -2
    assert tier_for_affinity(-0.25) == -1
    assert tier_for_affinity(0.0) == 0         # 档0 含 0
    assert tier_for_affinity(0.249999) == 0
    assert tier_for_affinity(0.25) == 1
    assert tier_for_affinity(0.5) == 2
    assert tier_for_affinity(0.75) == 3
    assert tier_for_affinity(1.0) == 3         # 最高档含 +100
    assert tier_name_for_affinity(-0.9) == "初识"
    assert tier_name_for_affinity(-0.3) == "微凉"
    assert tier_name_for_affinity(0.3) == "亲近"
    assert tier_name_for_affinity(0.6) == "挚友"


def test_attitude_text_follows_tier() -> None:
    assert "友善（基准）" in attitude_for_affinity(0.1)
    assert "初识" in attitude_for_affinity(-0.9)
    assert "独一份" in attitude_for_affinity(0.95)


def test_legacy_rows_in_0_1_range_are_kept_without_migration(tmp_path) -> None:
    # docs §1：存量 [0,1] 旧值恒等沿用（正半轴语义不变，display 同为 ×100），无迁移代码
    import sqlite3

    db = tmp_path / "legacy.sqlite3"
    DynamicAffinityStore(db, clock=_Clock())  # 建表
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO user_affinity (sender_id, affinity, updated_at) VALUES ('old', 0.8, ?)",
            ("1970-01-01T00:16:40Z",),
        )
    clock = _Clock()
    second = DynamicAffinityStore(db, clock=clock)
    snapshot = second.snapshot("old")
    assert abs(snapshot["affinity"] - 0.8) < 1e-9
    # 同步长的线性延续（闲置 0 天不回归）
    m = per_user_factor("old")
    assert abs(second.observe("old", "positive") - (0.8 + 0.02 * m)) < 1e-9


def test_delta_override_clamped_to_full_range(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.observe("u1", "neutral", delta_override=5.0) == 1.0
    assert store.observe("u2", "neutral", delta_override=-5.0) == -1.0


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
