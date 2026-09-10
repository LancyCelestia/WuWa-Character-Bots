"""BotMoodStore 回归测试：衰减数学、钳位、速率帽、映射表、describe/意愿系数、持久化与线程安全。"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.character.mood import BotMood, BotMoodStore


class _MutableClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_default_state_is_baseline(tmp_path: Path) -> None:
    store = BotMoodStore(tmp_path / "mood.sqlite3", clock=_MutableClock())
    snap = store.snapshot()
    assert isinstance(snap, BotMood)
    assert snap.valence == 0.0
    assert snap.arousal == pytest.approx(0.3)


def test_decay_halves_offset_after_half_life(tmp_path: Path) -> None:
    clock = _MutableClock()
    store = BotMoodStore(tmp_path / "mood.sqlite3", clock=clock)
    store.apply_event(0.4, 0.4)  # arousal: 0.3 + 0.4 = 0.7
    clock.advance(120 * 60)  # 一个半衰期
    snap = store.snapshot()
    assert snap.valence == pytest.approx(0.2)
    assert snap.arousal == pytest.approx(0.3 + 0.4 / 2)
    clock.advance(120 * 60)  # 两个半衰期
    snap = store.snapshot()
    assert snap.valence == pytest.approx(0.1)
    assert snap.arousal == pytest.approx(0.3 + 0.4 / 4)


def test_decay_pulls_arousal_back_to_baseline_from_both_sides(tmp_path: Path) -> None:
    clock = _MutableClock()
    store = BotMoodStore(tmp_path / "mood.sqlite3", clock=clock, rate_cap_per_hour=10.0)
    store.apply_event(0.0, -0.25)  # 唤醒被压到基线以下
    clock.advance(120 * 60 * 10)  # 10 个半衰期，残差 0.25/1024 ≈ 0.00024
    assert store.snapshot().arousal == pytest.approx(0.3, abs=1e-3)

    store2 = BotMoodStore(tmp_path / "mood2.sqlite3", clock=clock)
    store2.apply_event(0.0, 0.5)  # 高唤醒
    clock.advance(120 * 60 * 10)
    assert store2.snapshot().arousal == pytest.approx(0.3, abs=1e-3)


def test_snapshot_write_back_persists_decay(tmp_path: Path) -> None:
    clock = _MutableClock()
    db = tmp_path / "mood.sqlite3"
    store = BotMoodStore(db, clock=clock)
    store.apply_event(0.4, 0.0)
    clock.advance(120 * 60)
    assert store.snapshot().valence == pytest.approx(0.2)
    # 重开进程：衰减已写回落库，不得从 0.4 重新衰减（否则会得到 0.1）。
    reopened = BotMoodStore(db, clock=clock)
    assert reopened.snapshot().valence == pytest.approx(0.2)


def test_apply_event_clamps_to_valid_ranges(tmp_path: Path) -> None:
    clock = _MutableClock()
    store = BotMoodStore(tmp_path / "mood.sqlite3", clock=clock, rate_cap_per_hour=10.0)
    store.apply_event(5.0, 5.0)
    snap = store.snapshot()
    assert snap.valence == 1.0
    assert snap.arousal == 1.0
    store.apply_event(-5.0, -5.0)
    snap = store.snapshot()
    assert snap.valence == -1.0
    assert snap.arousal == 0.0


def test_rate_cap_blocks_overswing_then_window_expires(tmp_path: Path) -> None:
    clock = _MutableClock()
    store = BotMoodStore(tmp_path / "mood.sqlite3", clock=clock)
    first = store.apply_event(-1.0, 0.15)
    assert first.valence == pytest.approx(-0.5)  # 请求 -1.0 被帽截到 -0.5
    assert first.arousal == pytest.approx(0.45)
    again = store.apply_event(-0.2, 0.0)
    assert again.valence == pytest.approx(-0.5)  # 窗口额度耗尽，增量记 0
    clock.advance(3601)  # 窗口滑出
    later = store.apply_event(-0.2, 0.0)
    # 期间旧心情也按半衰期衰减了约一半：-0.5 → -0.5 × 0.5^(3601/7200)，再叠 -0.2。
    assert later.valence == pytest.approx(-0.5 * 0.5 ** (3601 / 7200) - 0.2)


def test_rate_cap_truncates_partially_not_all_or_nothing(tmp_path: Path) -> None:
    clock = _MutableClock()
    store = BotMoodStore(tmp_path / "mood.sqlite3", clock=clock)
    store.apply_event(0.3, 0.0)
    second = store.apply_event(0.3, 0.0)  # 剩余额度 0.2，只施加 0.2
    assert second.valence == pytest.approx(0.5)


def test_observe_interaction_mapping_values(tmp_path: Path) -> None:
    clock = _MutableClock()
    store = BotMoodStore(tmp_path / "mood.sqlite3", clock=clock)
    snap = store.observe_interaction("insult", [])
    assert snap.valence == pytest.approx(-0.18)
    assert snap.arousal == pytest.approx(0.45)

    snap = store.observe_interaction("positive", ["low_energy"])
    assert snap.valence == pytest.approx(-0.18 + 0.06)
    assert snap.arousal == pytest.approx(0.45 + 0.0 - 0.05)

    snap = store.observe_interaction("mystery_label", ["also_unknown"])
    assert snap.valence == pytest.approx(-0.12)
    assert snap.arousal == pytest.approx(0.40)


def test_describe_covers_all_quadrants_without_numbers(tmp_path: Path) -> None:
    store = BotMoodStore(tmp_path / "mood.sqlite3")
    cases = {
        (0.6, 0.8): "心情不错，很想说话",
        (0.3, 0.8): "心情不错，有点兴奋",
        (0.4, 0.2): "心情不错，安安稳稳的",
        (0.4, 0.4): "心情不错，挺有精神的",
        (0.0, 0.8): "有点烦躁，静不下来",
        (0.0, 0.3): "挺平静的",
        (0.0, 0.1): "懒洋洋的，没什么劲",
        (-0.4, 0.8): "有点低落，也静不下来",
        (-0.6, 0.4): "有点低落，不太想搭理人",
        (-0.6, 0.1): "有点低落，不太想搭理人",
        (-0.3, 0.1): "有点低落，提不起劲",
        (-0.3, 0.4): "有点低落",
    }
    for (valence, arousal), expected in cases.items():
        assert store.describe(BotMood(valence=valence, arousal=arousal, updated_at=0.0)) == expected
        text = store.describe(BotMood(valence=valence, arousal=arousal, updated_at=0.0))
        assert not any(ch.isdigit() for ch in text)


def test_willingness_factor_bounds_and_monotonicity(tmp_path: Path) -> None:
    store = BotMoodStore(tmp_path / "mood.sqlite3")
    assert store.willingness_factor(BotMood(0.0, 0.3, 0.0)) == pytest.approx(1.0)
    assert store.willingness_factor(BotMood(-1.0, 1.0, 0.0)) == pytest.approx(0.75)
    assert store.willingness_factor(BotMood(1.0, 1.0, 0.0)) == pytest.approx(1.25)
    # 高唤醒放大正向意愿；低落方向 <1。
    high = store.willingness_factor(BotMood(0.8, 0.9, 0.0))
    low = store.willingness_factor(BotMood(0.8, 0.1, 0.0))
    assert high > low > 1.0
    negative = store.willingness_factor(BotMood(-0.8, 0.5, 0.0))
    assert negative < 1.0
    # 全网格都在界内且对 valence 单调不减。
    grid = [v / 10 for v in range(-10, 11)]
    for arousal in (0.0, 0.3, 0.6, 1.0):
        factors = [store.willingness_factor(BotMood(v, arousal, 0.0)) for v in grid]
        assert all(0.75 <= f <= 1.25 for f in factors)
        assert factors == sorted(factors)


def test_persistence_roundtrip_across_instances(tmp_path: Path) -> None:
    clock = _MutableClock()
    db = tmp_path / "mood.sqlite3"
    first = BotMoodStore(db, clock=clock)
    first.apply_event(0.3, 0.2)
    del first
    clock.advance(120 * 60)
    second = BotMoodStore(db, clock=clock)
    snap = second.snapshot()
    assert snap.valence == pytest.approx(0.15)
    assert snap.arousal == pytest.approx(0.3 + 0.2 / 2)  # 事件后 0.5，半衰期后回 0.4


def test_thread_safety_smoke_concurrent_apply_events(tmp_path: Path) -> None:
    store = BotMoodStore(tmp_path / "mood.sqlite3")
    threads_count = 8
    events_per_thread = 25
    barrier = threading.Barrier(threads_count)
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            barrier.wait()
            for _ in range(events_per_thread):
                store.apply_event(0.01, 0.02)
        except BaseException as exc:  # noqa: BLE001 - 冒烟测试收集一切异常
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    snap = store.snapshot()
    # 速率帽把本窗口 |valence| 总增量压在 0.5 内；唤醒被钳位 [0,1]。
    assert -1.0 <= snap.valence <= 0.5 + 1e-6
    assert snap.valence > 0.0
    assert 0.0 <= snap.arousal <= 1.0
