"""v8 守恒测试（席3，2026-10-03）——A 案「恒等迁移」在 store 级的端到端锁。

设计判据（docs/affinity-design.md §C 迁移段，A 案＝推荐案）：

1. **首启播种**：存量行 ``goodwill_anchor`` 为 NULL（v7 时代）⇒ 拨 v8 后第一次
   写入时 anchor 以**当前高度**现推（``z − band(companion_days)``），绝不重置成
   零/缺省——「这段关系曾经到过的地方」从第一轮起就在册。
2. **存量零重置**：``z_latent`` 惰性推导走 v8 长尾表示域（clamp ±0.999999），
   贴近旧硬界（±0.985）之外的存量高度**不回吞**；v7 腿的惰性推导 clamp ±0.985
   是设计写明的域变换（在册口径，不算重置）——展示值回到域界而非归零。
3. **v8 关态零触碰**：拨回关 ⇒ anchor/z 两列零读写。

注：影子记账（v8 影子并行计分不落库）在现行实现中**不存在**（全树 grep 零命中），
按席面简报「如实现已有则锁之」——无实现可锁，此处不虚构锁，缺口进席面报告。
"""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    DynamicAffinityStore,
    resolve_v8_settings,
    v7_z_to_display_fraction,
    v8_goodwill_anchor,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now

    def iso(self) -> str:
        return datetime.fromtimestamp(self.now, tz=UTC).isoformat()


def _config(*, v8: bool, v7: bool) -> SimpleNamespace:
    return SimpleNamespace(bot_affinity_v8_enabled=v8, bot_affinity_v7_enabled=v7)


def _row(store: DynamicAffinityStore, sender_id: str = "u1") -> sqlite3.Row:
    with sqlite3.connect(store.db_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT affinity, z_latent, goodwill_anchor, nickname, created_at"
            " FROM user_affinity WHERE sender_id = ?",
            (sender_id,),
        ).fetchone()


def _insert_legacy_row(store: DynamicAffinityStore, *, affinity: float, clock: _Clock) -> None:
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "INSERT INTO user_affinity"
            " (sender_id, affinity, nickname, updated_at, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("u1", affinity, "老朋友", clock.iso(), clock.iso()),
        )


def test_first_v8_start_seeds_anchor_from_current_state(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(
        tmp_path / "a.sqlite3", clock=clock, config=_config(v8=False, v7=False)
    )
    store.observe("u1", "positive")
    before = _row(store)
    assert before["z_latent"] is None and before["goodwill_anchor"] is None
    height_before = float(before["affinity"])

    # 拨 v8（同一份库）：A 案不做任何后台改写——列在第一次 v8 写入时才播种。
    store_v8 = DynamicAffinityStore(
        tmp_path / "a.sqlite3", clock=clock, config=_config(v8=True, v7=False)
    )
    clock.now += 120.0  # 过 60s 冷却，给一次真实计分路径。
    store_v8.observe("u1", "positive")
    after = _row(store_v8)
    assert after["z_latent"] is not None and after["goodwill_anchor"] is not None

    z_after = float(after["z_latent"])
    v8 = resolve_v8_settings(_config(v8=True, v7=False))
    created = datetime.fromisoformat(str(after["created_at"]))
    companion_days = max(0.0, (clock.now - created.timestamp()) / 86400.0)
    band = v8.band_for(companion_days)
    # 首启播种＝当前高度 − 保护带（单调不减锚的起点），不是任何缺省值。
    assert float(after["goodwill_anchor"]) == pytest.approx(
        v8_goodwill_anchor(None, z_after, band), abs=1e-9
    )
    # 锚只抬下界：anchor ≤ z 恒成立；且锚高度贴近拨闸前水位（未被重置）。
    assert float(after["goodwill_anchor"]) <= z_after + 1e-9
    assert float(after["goodwill_anchor"]) >= math.atanh(height_before) - band - 1e-6
    # 展示值＝tanh(z) 内部一致；距拨闸前只差一次合法计分的量级，绝无归零/跳档。
    assert float(after["affinity"]) == pytest.approx(math.tanh(z_after), abs=1e-9)
    assert abs(float(after["affinity"]) - height_before) <= 0.05


def test_legacy_top_value_not_swallowed_by_lazy_z_derivation(tmp_path) -> None:
    """存量贴顶值（0.99 > 旧硬界 0.985）在 v8 惰性推导下不回吞（长尾表示域）。"""
    clock = _Clock()
    store = DynamicAffinityStore(
        tmp_path / "a.sqlite3", clock=clock, config=_config(v8=False, v7=False)
    )
    _insert_legacy_row(store, affinity=0.99, clock=clock)

    store_v8 = DynamicAffinityStore(
        tmp_path / "a.sqlite3", clock=clock, config=_config(v8=True, v7=False)
    )
    clock.now += 120.0
    store_v8.observe("u1", "positive")
    after = _row(store_v8)
    z_after = float(after["z_latent"])
    # 未被钳回 ±atanh(0.985)：推导域是 0.999999，存量高度逐点守恒（atanh 单调）。
    assert z_after > math.atanh(0.985) + 1e-6
    assert float(after["affinity"]) >= 0.9885  # 不重置：展示值仍贴顶。
    assert float(after["goodwill_anchor"]) <= z_after + 1e-9
    assert after["nickname"] == "老朋友"


def test_v7_lazy_derivation_clamps_to_registered_bound(tmp_path) -> None:
    """v7 腿惰性推导 clamp ±0.985＝设计写明的域变换：展示值回到域界，不归零不重排。"""
    clock = _Clock()
    store = DynamicAffinityStore(
        tmp_path / "a.sqlite3", clock=clock, config=_config(v8=False, v7=False)
    )
    _insert_legacy_row(store, affinity=0.99, clock=clock)

    store_v7 = DynamicAffinityStore(
        tmp_path / "a.sqlite3", clock=clock, config=_config(v8=False, v7=True)
    )
    clock.now += 120.0
    store_v7.observe("u1", "positive")
    after = _row(store_v7)
    z_after = float(after["z_latent"])
    # 域界：z 落在 ±atanh(0.985) 邻域（正侧），展示值回到 98.5 展示分带内——
    # 不是 0.99 原值（域变换在册口径），更不是 0.1 基准（重置）。
    assert z_after == pytest.approx(math.atanh(0.985), abs=0.05)
    display = float(after["affinity"])
    assert v7_z_to_display_fraction(z_after) == pytest.approx(display, abs=1e-9)
    assert 0.98 <= display <= 0.992
    assert display == pytest.approx(math.tanh(z_after), abs=1e-9)


def test_v8_off_touches_anchor_columns_never(tmp_path) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(
        tmp_path / "a.sqlite3", clock=clock, config=_config(v8=True, v7=False)
    )
    store.observe("u1", "positive")
    assert _row(store)["goodwill_anchor"] is not None
    # 拨回关：v8 关态两列零读写（存量值原样保留，不清洗不回填）。
    store_off = DynamicAffinityStore(
        tmp_path / "a.sqlite3", clock=clock, config=_config(v8=False, v7=False)
    )
    clock.now += 120.0
    store_off.observe("u1", "tease")
    row = _row(store_off)
    assert float(row["goodwill_anchor"]) == float(_row(store)["goodwill_anchor"])
    assert row["z_latent"] == _row(store)["z_latent"]
