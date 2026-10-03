"""「你对守岸人」展示读数有界化（席3，2026-10-03）。

判据：sentiment_for 裸比值一条辱骂可挪数十展示分 ⇒ 展示值过**滚动 24h 单向下行
限幅**（真身＝DynamicAffinityStore.bound_sentiment_display）；内部真值与档位
零改动；上行不限；故障 fail-open 回裸值；能力层接线（无方法的测试桩回裸值＝
旧行为逐字节不变）。
"""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
    build_affinity_capability,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    SENTIMENT_DISPLAY_LOG_TABLE,
    DynamicAffinityStore,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now

    def iso(self) -> str:
        return datetime.fromtimestamp(self.now, tz=UTC).isoformat()


def _store(tmp_path, clock: _Clock) -> DynamicAffinityStore:
    return DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _set_counts(store: DynamicAffinityStore, *, positive: int, insult: int) -> None:
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE user_affinity SET positive_count = ?, insult_count = ?,"
            " last_positive_at = ?, last_insult_at = ? WHERE sender_id = ?",
            (positive, insult, _now_iso(), _now_iso(), "u1"),
        )


# ---------------------------------------------------------------------------
# 限幅判据
# ---------------------------------------------------------------------------


def test_first_reading_recorded_as_is(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    store.observe("u1", "positive")
    raw = store.sentiment_for("u1") * 100
    assert store.bound_sentiment_display("u1", raw) == pytest.approx(raw)


def test_single_crash_is_clamped_to_daily_cap(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    store.observe("u1", "positive")
    high = store.sentiment_for("u1") * 100  # 100（正向占比满格）
    assert store.bound_sentiment_display("u1", high) == pytest.approx(high)
    # 一条辱骂砸盘：raw 从 100 挪到 20 出头，展示值只许下行 4 分。
    _set_counts(store, positive=1, insult=8)
    low = store.sentiment_for("u1") * 100
    assert low < 25.0
    shown = store.bound_sentiment_display("u1", low)
    assert shown == pytest.approx(high - 4.0)
    # 窗内反复砸：展示值钉在限幅位，不再多挪。
    assert store.bound_sentiment_display("u1", low) == pytest.approx(high - 4.0)


def test_window_slide_restores_true_value(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    store.observe("u1", "positive")
    store.bound_sentiment_display("u1", 100.0)
    _set_counts(store, positive=1, insult=8)
    low = store.sentiment_for("u1") * 100
    assert store.bound_sentiment_display("u1", low) == pytest.approx(96.0)
    clock.now += 25 * 3600.0  # 窗口滑走：峰值出窗，真值恢复可见。
    assert store.bound_sentiment_display("u1", low) == pytest.approx(low)


def test_upward_moves_not_clamped(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    assert store.bound_sentiment_display("u1", 50.0) == pytest.approx(50.0)
    assert store.bound_sentiment_display("u1", 90.0) == pytest.approx(90.0)


def test_internal_truth_and_affinity_untouched(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    store.observe("u1", "positive")
    affinity_before = store.snapshot("u1")["affinity"]
    _set_counts(store, positive=1, insult=8)
    truth = store.sentiment_for("u1")
    shown = store.bound_sentiment_display("u1", truth * 100)
    assert math.isfinite(shown)
    # 限幅只动展示：内部真值与好感值零触碰（复读一致＝无写副作用）。
    assert store.sentiment_for("u1") == pytest.approx(truth)
    assert store.snapshot("u1")["affinity"] == pytest.approx(affinity_before)


def test_fail_open_on_dirty_inputs(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    nan = float("nan")
    assert store.bound_sentiment_display("", 50.0) == 50.0
    assert math.isnan(store.bound_sentiment_display("u1", nan))
    assert store.bound_sentiment_display("u1", 30.0, cap_per_day=0.0) == 30.0
    assert store.bound_sentiment_display("u1", 30.0, cap_per_day=-1.0) == 30.0


def test_stale_rows_pruned(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    store.bound_sentiment_display("u1", 80.0)
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            f"UPDATE {SENTIMENT_DISPLAY_LOG_TABLE} SET shown_at = shown_at - 49 * 3600"
        )
    store.bound_sentiment_display("u1", 80.0)
    with sqlite3.connect(store.db_path) as connection:
        count = connection.execute(
            f"SELECT COUNT(*) FROM {SENTIMENT_DISPLAY_LOG_TABLE}"
        ).fetchone()[0]
    assert count == 1  # 49h 前的旧行被 prune，只剩本次落行。


# ---------------------------------------------------------------------------
# 能力层接线
# ---------------------------------------------------------------------------


def _message() -> SimpleNamespace:
    return SimpleNamespace(
        request_id="req_seat3", sender_id="u1", group_id="", plain_text="好感度",
        sender_roles=[],
    )


def test_capability_body_uses_bound_display(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    store.observe("u1", "positive")
    store.bound_sentiment_display("u1", 100.0)  # 先亮过 100 分的峰值。
    _set_counts(store, positive=1, insult=8)
    capability = build_affinity_capability(affinity_store=store)
    result = capability(_message(), SimpleNamespace())
    assert "你对：96.0" in result.body
    assert "5.9" not in result.body  # 裸值不出口。


def test_capability_with_stub_store_keeps_legacy_behavior() -> None:
    """旧形态测试桩没有 bound 方法 ⇒ getattr 容缺省回裸值（旧行为逐字节不变）。"""
    stub = SimpleNamespace(
        snapshot=lambda sender: {"affinity": 0.123},
        sentiment_for=lambda sender: 0.5,
        leaderboard=lambda group, limit: [],
    )
    capability = build_affinity_capability(affinity_store=stub)
    result = capability(_message(), SimpleNamespace())
    assert "你对：50.0" in result.body
