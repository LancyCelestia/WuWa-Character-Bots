"""好感度数值化回归（C组，独立命名）：docs/affinity-design.md 的验收口径。

覆盖：画像不被 observe 清空、每日有效次数上限、时钟注入、惰性回归、
档位 id 边界、override 仅受 clamp 约束。既有 test_affinity.py 保持不改全过。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.character.affinity import (
    DynamicAffinityStore,
    attitude_for_affinity,
    tier_for_affinity,
)


class _Clock:
    """可推进的注入时钟（秒）。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_days(self, days: float) -> None:
        self.now += days * 86400.0


def test_observe_preserves_profile_notes(tmp_path) -> None:
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_Clock())
    store.learn_profile("u1", "我住在杭州")
    store.observe("u1", "positive")
    store.observe("u1", "insult")
    notes = store.snapshot("u1").get("profile_notes")
    assert notes == ["我住在杭州"]


def test_daily_cap_stops_repeated_positive_gain(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    affinity = 0.5
    for _ in range(15):
        affinity = store.observe("u1", "positive")
    # 每日有效 10 次 × +0.02 = +0.20，其后不再加分
    assert abs(affinity - 0.70) < 1e-6


def test_daily_counters_still_accumulate_for_tags(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    for _ in range(12):
        store.observe("u1", "positive")
    snapshot = store.snapshot("u1")
    # 超上限后 delta=0，但行为计数与印象标签照常累计
    assert snapshot["affinity"] <= 0.70 + 1e-6
    assert "老朋友" in snapshot["tags"]


def test_daily_cap_resets_next_day(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    for _ in range(15):
        store.observe("u1", "positive")
    clock.advance_days(1)
    affinity = store.observe("u1", "positive")
    assert abs(affinity - 0.72) < 1e-6


def test_insult_daily_cap_bounds_the_drain(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    high = store.observe("u1", "neutral", delta_override=0.4)  # 0.90
    assert abs(high - 0.90) < 1e-6
    affinity = 0.90
    for _ in range(10):
        affinity = store.observe("u1", "insult")
    # 前 8 次 × -0.10 = -0.80，其后封底
    assert abs(affinity - 0.10) < 1e-6


def test_clock_injection_drives_updated_at(tmp_path) -> None:
    clock = _Clock(1000.0)
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    store.observe("u1", "neutral")
    import sqlite3

    connection = sqlite3.connect(tmp_path / "affinity.sqlite3")
    row = connection.execute(
        "SELECT updated_at FROM user_affinity WHERE sender_id = 'u1'"
    ).fetchone()
    connection.close()
    assert row is not None
    assert row[0] == "1970-01-01T00:16:40Z"


def test_lazy_regression_toward_base_after_idle_days(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    for _ in range(15):
        store.observe("u1", "positive")
    clock.advance_days(10)
    affinity = store.observe("u1", "neutral")
    # 闲置 10 天：向 0.5 回归 0.10，中性事件不追加
    assert abs(affinity - 0.60) < 1e-6


def test_regression_never_crosses_base(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    near = store.observe("u1", "neutral", delta_override=0.02)  # 0.52
    assert abs(near - 0.52) < 1e-6
    clock.advance_days(30)
    affinity = store.observe("u1", "neutral")
    assert abs(affinity - 0.50) < 1e-6

    low = store.observe("u2", "neutral", delta_override=-0.20)  # 0.30
    assert abs(low - 0.30) < 1e-6
    clock.advance_days(30)
    assert abs(store.observe("u2", "neutral") - 0.50) < 1e-6


def test_tier_for_affinity_boundaries_are_left_closed() -> None:
    assert tier_for_affinity(0.75) == "close"
    assert tier_for_affinity(1.0) == "close"
    assert tier_for_affinity(0.749) == "friendly"
    assert tier_for_affinity(0.45) == "friendly"
    assert tier_for_affinity(0.449) == "polite"
    assert tier_for_affinity(0.25) == "polite"
    assert tier_for_affinity(0.249) == "distant"
    assert tier_for_affinity(0.0) == "distant"
    # attitude 文本与档位一一对应（providers 注入依赖）
    assert "亲近" in attitude_for_affinity(0.80)
    assert "严厉" in attitude_for_affinity(0.10)


def test_delta_override_clamped_only(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    assert store.observe("u1", "neutral", delta_override=5.0) == 1.0
    assert store.observe("u2", "neutral", delta_override=-5.0) == 0.0
