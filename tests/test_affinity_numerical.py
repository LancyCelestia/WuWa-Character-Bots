"""好感度数值化回归（docs/affinity-design.md v4 线性版 + 附录 v6 平滑层验收口径）。

模型：基准 0.1（展示 10）；步长 = 因子表 × 个人系数 m(uid)，中段（|展示分| ≤ 75）
保持 v4 线性全额（v3 幂律阻尼 γ 已废除）；v6 平滑层：距 ±1 一个档宽内 smoothstep
饱和收窄 + 同日同类信号边际递减（0.6^n 下限）；个人系数由 sender_id 确定性派生
±15%；写入 clamp [-1,+1]；存量 [0,1] 旧库值恒等沿用（无迁移）。
"""

from __future__ import annotations

import pytest

import plugins.bot_unified_runtime.domains.chat_reply.character.affinity as affinity_module
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _IDLE_REGRESSION_PER_DAY,
    _IDLE_REGRESSION_START_DAYS,
    _SENTIMENT_HALF_LIFE_DAYS,
    DynamicAffinityStore,
    attitude_for_affinity,
    effective_delta,
    per_user_factor,
    saturation_factor,
    tier_for_affinity,
    tier_name_for_affinity,
)


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def advance_days(self, days: float) -> None:
        self.now += days * 86400.0


def _store(tmp_path) -> DynamicAffinityStore:
    return DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_Clock())


def _seed_row(db, sender_id: str, affinity: float, updated_at: str = "1970-01-01T00:16:40Z") -> None:
    """直接播种目标分值行（V2.1 §2.3 滚动预算后，单日无法经 observe/override
    到达远端档位；线性/钳制/回归语义改由播种行验证，意图不变）。"""
    import sqlite3

    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO user_affinity (sender_id, affinity, interaction_count, updated_at)"
            " VALUES (?, ?, 1, ?)",
            (sender_id, affinity, updated_at),
        )


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


def test_saturation_tapers_steps_near_extremes() -> None:
    # v6 饱和响应（docs 附录 §v6.1）：带外（含 0.05/-0.05）保持 v5 全额线性；
    # 距边界一个档宽内步长 smoothstep 收窄——越近极端越钝，边界处恰好归零
    # （渐近逼近，永不因单次行为击穿 [-1,+1]）。
    m1 = per_user_factor("u1")
    m2 = per_user_factor("u2")
    assert abs(effective_delta("u1", "positive", 0.05) - 0.02 * m1) < 1e-12
    assert abs(effective_delta("u2", "insult", -0.05) + 0.10 * m2) < 1e-12
    # 带内：0.97 正向步长缩到全额的很小比例（0.03 剩余 / 0.25 带宽）。
    assert 0.0 < effective_delta("u1", "positive", 0.97) < 0.02 * m1 * 0.05
    assert -0.10 * m2 * 0.05 < effective_delta("u2", "insult", -0.97) < 0.0
    assert effective_delta("u1", "positive", 1.0) == 0.0
    assert effective_delta("u2", "insult", -1.0) == 0.0


def test_linear_observe_paths(tmp_path) -> None:
    store = _store(tmp_path)
    # V2.1 §2.3 滚动预算：override 一律过预算——正向 3 分/24h 封顶（原 0.87 直通
    # 87 分的口径随误扣修复废除；单事件负向 1 分封顶）。
    high = store.observe("u1", "neutral", delta_override=0.87)
    assert abs(high - 0.13) < 1e-9
    low = store.observe("u2", "neutral", delta_override=-1.07)
    assert abs(low - 0.09) < 1e-9

    # 带外全额步长与 [-1,1] 硬钳制语义保持（播种行验证，预算路径不可达极值）
    db = tmp_path / "affinity.sqlite3"
    _seed_row(db, "u3", 0.97)
    m3 = per_user_factor("u3")
    # v6 饱和响应：0.97 已进入最后一档，正向步长被 smoothstep 收窄（非全额）。
    step3 = 0.02 * m3 * saturation_factor(0.97, 1.0)
    assert abs(store.observe("u3", "positive") - (0.97 + step3)) < 1e-9
    # 写入路径硬钳制：override 不过饱和/递减但过预算（单事件负向 1 分封顶），
    # 从 -0.995 申请 -1 分 → -1.005 → clamp 到 -1.0。
    _seed_row(db, "u4", -0.995)
    assert store.observe("u4", "neutral", delta_override=-1.0) == -1.0


def test_mid_range_steps_are_full(tmp_path) -> None:
    store = _store(tmp_path)
    # 中段全额步长：播种 0.5 行后正步全额（原经 override 0.40 建立中段基线，
    # V2.1 §2.3 预算后 override 单日封顶 3 分，改播种，意图不变）
    _seed_row(tmp_path / "affinity.sqlite3", "u1", 0.5)
    m = per_user_factor("u1")
    assert abs(store.observe("u1", "positive") - (0.5 + 0.02 * m)) < 1e-9


def test_per_user_factors_differ_by_sender(tmp_path) -> None:
    factors = {per_user_factor(f"user-{i}") for i in range(12)}
    assert len(factors) > 1, "不同 sender 的个人系数应可区分"


def test_daily_cap_still_bounds_positive_gain(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    last = 0.1
    for _ in range(15):
        clock.advance(61)  # V2.1 §2.3 冷却：发间隔超 60s，被测对象保持每日有效次数上限
        last = store.observe("u1", "positive")
    # 前 10 次有效：总增益小于 10×全额步长×各因子上限（v5：第一印象 ±30%
    # 放大 + 说话温度 ≤1.4，正向首次印象会让好话来得更快——用户裁定语义）；
    # V2.1 起另有 24h 全局增益 3 分预算先于次数上限收紧（test_affinity_v21.py 已锁）。
    assert last < 0.1 + 10 * 0.02 * 1.4 * 1.3 * per_user_factor("u1")
    clock.advance(61)  # 超冷却后再验证：拦截者是每日次数上限而非冷却门
    settled = store.observe("u1", "positive")
    assert abs(settled - last) < 1e-12, "超每日上限后不再增减"


def test_regression_and_fadeout_constants_match_design() -> None:
    # §3 参数顶置常量：惰性回归 7 天起每日 0.01；淡出半衰期 insult 15 天、其余 30 天
    assert _IDLE_REGRESSION_START_DAYS == 7
    assert _IDLE_REGRESSION_PER_DAY == 0.01
    assert _SENTIMENT_HALF_LIFE_DAYS == {"positive": 30.0, "negative": 30.0, "insult": 15.0}


def test_lazy_regression_targets_new_base(tmp_path, monkeypatch) -> None:
    # V2.1 §2.3 passive_decay 默认关（缺席不默认扣分，policy_revision=v21.1）；
    # 本测试验证「政策门显式开启时旧 §3 惰性回归语义原样」——冲突值迁移，不并存。
    monkeypatch.setattr(affinity_module, "_PASSIVE_DECAY_ENABLED", True)
    clock = _Clock()
    db = tmp_path / "reg.sqlite3"
    store2 = DynamicAffinityStore(db, clock=clock)
    # 播种 0.5 基线（原经 override 0.40 建立，V2.1 §2.3 预算后不可达，语义不变）
    _seed_row(db, "u1", 0.5)
    clock.advance_days(10)
    # 回归目标=基准 0.1：闲置 10 天向 0.1 回归 0.10
    assert abs(store2.observe("u1", "neutral") - 0.40) < 1e-9
    clock.advance_days(40)
    assert abs(store2.observe("u1", "neutral") - 0.10) < 1e-9, "回归不超过基准"


def test_negative_side_regression_also_targets_base(tmp_path, monkeypatch) -> None:
    # 同上：政策门显式开启后验证负半轴回归原语义（V2.1 默认关，见 v21_budget 测试）。
    monkeypatch.setattr(affinity_module, "_PASSIVE_DECAY_ENABLED", True)
    clock = _Clock()
    db = tmp_path / "regneg.sqlite3"
    store = DynamicAffinityStore(db, clock=clock)
    # 播种负半轴 -0.40 基线（原经 override -0.50 建立，预算后不可达，语义不变）
    _seed_row(db, "u1", -0.40)
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
    # 步长延续：闲置 0 天不回归；0.8 已进入 v6 饱和带（最后一档），正向步长按
    # smoothstep 收窄（非全额），数值由 saturation_factor 单一来源给出。
    m = per_user_factor("old")
    expected = 0.8 + 0.02 * m * saturation_factor(0.8, 1.0)
    assert abs(second.observe("old", "positive") - expected) < 1e-9


def test_delta_override_bounded_by_rolling_budget(tmp_path) -> None:
    # V2.1 §2.3：override 一律过滚动预算（原「override 直通满值域 ±1.0」口径
    # 随误扣修复废除，测试改名以如实反映政策）；[-1,1] 硬钳制仍在写入路径
    # （由 test_linear_observe_paths 的播种极值行覆盖）。
    store = _store(tmp_path)
    assert store.observe("u1", "neutral", delta_override=5.0) == pytest.approx(0.13, abs=1e-9)
    assert store.observe("u2", "neutral", delta_override=-5.0) == pytest.approx(0.09, abs=1e-9)


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
