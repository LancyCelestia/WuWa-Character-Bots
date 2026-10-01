"""好感度 v8 第二腿·善意底数值形制锁（S-FIX-AFF-ALGO-R 收编席，2026-09-28）。

对账对象：docs/affinity-design.md §C.4 与其散文 + 2026-09-28 换形裁定
（线性折线 ⇒ **凸递减半衰形态**）。⚠ 规格 C.4 首行公式与自身散文正反两读
（公式给线性 min(1,days/365) 且 days=0 端取 BAND_MAX，散文说新人可回全谱），
本锁钉的是实现采信的**散文义**：band(0)=BAND_MIN（新人≈全谱，起点不是惩罚），
days→∞ 渐近 BAND_MAX 且恒在其上（老关系底线只可逼近不可击穿）。
勘误登记：见 .superpowers/sdd/2026-09-27-fullload/logs/SEAT-FIX-AFF-ALGO-R.md。

形态判据（纯函数级，禁"恰好等于某常数"式脆断言，全部给形状/序/渐近）：
- 凸递减无折点：一阶差分恒负且严格升（朝 0），二阶差分恒正——分段线性在
  饱和点必有斜率断口，本形态没有；
- band(0)=band_min、band(saturate) 收敛到距底线 1/8 跨度（FOLDS=3 ⇒ 2^-3）；
- days 缺失/脏 ⇒ fail-open 回 band_min；配置倒挂 ⇒ 无保护（恒 band_min），
  绝不产生反向曲线。
行为面（store 级）：anchor 单调不减、只抬下界不改写既有 z、列持久化不丢态、
v8 关 ⇒ 两列零读写漂移。

全部离线：纯函数 + tmp_path 注入时钟，不碰 ChatBot_Runtime/。
"""

from __future__ import annotations

import math
import types
from itertools import pairwise

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _V8_BAND_SATURATE_FOLDS,
    _V8_CONFIG_FIELDS,
    _V8_DEFAULT_BAND_MAX,
    _V8_DEFAULT_BAND_MIN,
    _V8_DEFAULT_BAND_SATURATE_DAYS,
    DynamicAffinityStore,
    v8_goodwill_anchor,
    v8_goodwill_band,
)

_V8_ENV_KEYS = [name.upper() for name, _default in _V8_CONFIG_FIELDS]
_TOL = 1e-9
_DAY = 86400.0


@pytest.fixture(autouse=True)
def _isolate_v8_env(monkeypatch):
    for key in _V8_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class _Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _v8_config(**overrides: object) -> types.SimpleNamespace:
    base: dict[str, object] = {
        "bot_affinity_v7_enabled": False,
        "bot_affinity_v8_enabled": True,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _store(tmp_path, clock: _Clock, name: str, **config_over) -> DynamicAffinityStore:
    return DynamicAffinityStore(
        tmp_path / name, clock=clock, config=_v8_config(**config_over)
    )


def _peek_row(store, sender: str):
    with store._lock, store._connect() as connection:
        return connection.execute(
            "SELECT affinity, goodwill_anchor, v8_state, z_latent FROM user_affinity"
            " WHERE sender_id = ?",
            (sender,),
        ).fetchone()


# =========================================================================
# A. band(days) 数值形制（纯函数）
# =========================================================================


def test_band_endpoints_and_saturation_fold() -> None:
    """band(0)=BAND_MIN；saturate_days 处收敛到 1/2^FOLDS 跨度（缺省 1/8）；
    恒 >BAND_MAX 且单调逼近（渐近线不可击穿）。"""
    assert v8_goodwill_band(0.0) == pytest.approx(_V8_DEFAULT_BAND_MIN)
    at_sat = v8_goodwill_band(_V8_DEFAULT_BAND_SATURATE_DAYS)
    span = _V8_DEFAULT_BAND_MIN - _V8_DEFAULT_BAND_MAX
    assert at_sat - _V8_DEFAULT_BAND_MAX == pytest.approx(
        span / 2.0**_V8_BAND_SATURATE_FOLDS, rel=1e-9
    )
    for days in (_V8_DEFAULT_BAND_SATURATE_DAYS * k for k in (2, 4, 8)):
        assert _V8_DEFAULT_BAND_MAX < v8_goodwill_band(days) < at_sat


def test_band_shape_convex_strictly_decreasing_no_kink() -> None:
    """凸递减无折点：网格上一阶差分恒负、严格升（|斜率|单调衰减），二阶差分恒正。
    分段线性在饱和点必留斜率断口——此判据把「换形裁定」钉死在半衰族形态上。"""
    step = 7.0
    values = [v8_goodwill_band(days * step) for days in range(120)]  # 0..839 天
    first = [b - a for a, b in pairwise(values)]
    second = [y - x for x, y in pairwise(first)]
    assert all(d < -1e-12 for d in first), "band 非严格递减"
    assert all(d > 1e-12 for d in second), "band 非凸（存在斜率折点/凹段）"
    assert all(abs(y) < abs(x) for x, y in pairwise(first)), "|斜率|未单调衰减"


def test_band_fail_open_and_dirty_inputs() -> None:
    """days 缺失/非有限/负 ⇒ 一律 fail-open 回 BAND_MIN（含 +inf——脏龄不当老资格）；
    脏配置逐键回代码缺省，绝不抛。"""
    assert v8_goodwill_band(None) == pytest.approx(_V8_DEFAULT_BAND_MIN)
    assert v8_goodwill_band(float("nan")) == pytest.approx(_V8_DEFAULT_BAND_MIN)
    assert v8_goodwill_band(float("inf")) == pytest.approx(_V8_DEFAULT_BAND_MIN)
    assert v8_goodwill_band(-50.0) == pytest.approx(_V8_DEFAULT_BAND_MIN)
    # 脏 band_min ⇒ 回代码缺省曲线：10 天处仍是「起点与底线之间」的正常凸形读数。
    dirty_lo = v8_goodwill_band(10.0, band_min=float("nan"))
    assert _V8_DEFAULT_BAND_MAX < dirty_lo < _V8_DEFAULT_BAND_MIN


def test_band_inverted_config_produces_no_negative_width() -> None:
    """倒挂（band_max>band_min）⇒ 无保护平线恒 band_min：绝不产生
    「底线高于起点」的反向曲线。"""
    inverted = v8_goodwill_band(0.0, band_min=0.5, band_max=2.0, saturate_days=365.0)
    later = v8_goodwill_band(5000.0, band_min=0.5, band_max=2.0, saturate_days=365.0)
    assert inverted == pytest.approx(0.5)
    assert later == pytest.approx(0.5)


def test_band_follows_settings_not_hardcoded() -> None:
    """band 读数由 settings（config/env）供给：min/max 经配置改后曲线随动，
    形状不变（端点/渐近各就各位）。"""
    lo, hi = 2.0, 0.5
    assert v8_goodwill_band(0.0, band_min=lo, band_max=hi) == pytest.approx(lo)
    far = v8_goodwill_band(5000.0, band_min=lo, band_max=hi)
    assert hi < far < v8_goodwill_band(1000.0, band_min=lo, band_max=hi) < lo


# =========================================================================
# B. anchor 语义（纯函数）
# =========================================================================


def test_anchor_formula_monotone_envelope() -> None:
    """anchor ← max(prev, z−band)：无历史⇒现推；prev 更高⇒原样（单调不减）；
    band=0⇒anchor=z；band 脏⇒按 0 处理。"""
    assert v8_goodwill_anchor(None, 0.30, 0.20) == pytest.approx(0.10)
    assert v8_goodwill_anchor(0.25, 0.30, 0.20) == pytest.approx(0.25)  # prev 更高
    assert v8_goodwill_anchor(0.05, 0.30, 0.20) == pytest.approx(0.10)  # 抬升
    assert v8_goodwill_anchor(0.10, 0.30, 0.0) == pytest.approx(0.30)
    assert v8_goodwill_anchor(float("nan"), 0.30, 0.20) == pytest.approx(0.10)  # 脏 ⇒ 现推
    # 长尾性质：band→∞ 时 anchor 有下界 -inf？不——band 是正带宽，z−band 只会更低，
    # 而 prev 更高者胜 ⇒ anchor 永不因 band 变大而"下压"任何人。
    assert v8_goodwill_anchor(0.2, 0.0, 99.0) == pytest.approx(0.2)


# =========================================================================
# C. store 行为面（善意底真的接在写路径上）
# =========================================================================


def _hammer_down(store, clock, sender: str, events: int, sample: list | None = None) -> None:
    """满额负向连打：步长 43201s（>12h）——相邻 60s 冷却全过、滚动 24h 窗内
    恒只有上一发 0.02 ⇒ 稳态恰好吃满 D=0.04/日，不触冷却、不触额度墙。
    `sample` 给出时逐事件记录 (z, anchor)，供单调性检查。"""
    for _ in range(events):
        store.observe(sender, "insult", delta_override=-0.02, text="坏日子")
        if sample is not None:
            row = _peek_row(store, sender)
            sample.append((float(row["z_latent"]), float(row["goodwill_anchor"])))
        clock.advance(43201.0)


def test_old_relationship_cannot_be_spiked_below_band(tmp_path) -> None:
    """一年+老用户被满额负向连轰（可用负量 1.6z > band≈0.74z）⇒ 落点被
    善意底**托住且只被托住**：跌幅夹在 [band(峰龄+轰程), band(峰龄)]——
    §C.4 用事件时刻的当前龄取带，连轰期间 band 随龄半衰收缩、底线只可上收，
    故精确等号反而不成立（实现采散文义：底线随龄上收，寸土不让但不倒灌）。
    期间 goodwill_anchor 单调不减（推论 4 的实跑形；比较在 z 域，anchor 住 z 域）。"""
    clock = _Clock()
    store = _store(tmp_path, clock, "veteran.sqlite3")
    store.observe("v", "positive", text="初见")           # 建档，created_at=now
    clock.advance(420 * _DAY)                              # 处了 420 天
    store.observe("v", "positive", delta_override=0.02, text="久处")  # 爬到峰值
    row = _peek_row(store, "v")
    z_peak = float(row["z_latent"])
    anchor0 = float(row["goodwill_anchor"])
    assert math.isfinite(z_peak) and math.isfinite(anchor0)

    anchors: list[float] = [anchor0]
    trail: list[tuple[float, float]] = []
    _hammer_down(store, clock, "v", 120, sample=trail)
    anchors += [a for _, a in trail]
    final_row = _peek_row(store, "v")
    z_final = float(final_row["z_latent"])
    band_at_peak = v8_goodwill_band(420.0)
    hammer_span_days = 120 * 43201.0 / _DAY
    band_after_span = v8_goodwill_band(420.0 + hammer_span_days)
    assert z_final < z_peak - 1e-6, "满额负向竟没跌 ⇒ 本段在空跑"
    assert z_final >= z_peak - band_at_peak - 1e-9, (
        f"老用户被击穿峰值减保护带：z_final={z_final} z_peak={z_peak} band={band_at_peak}"
    )
    drop = z_peak - z_final
    assert band_after_span - 1e-9 <= drop <= band_at_peak + 1e-9, (
        f"保护带未咬合：跌幅 {drop:.6f} 不在 [band(480d)={band_after_span:.6f},"
        f" band(420d)={band_at_peak:.6f}]（anchor 没参与落点，或底线随龄上收越界）"
    )
    assert float(final_row["goodwill_anchor"]) == pytest.approx(z_final, abs=1e-9), (
        "连轰终态落点未贴住底线（floor 未生效或被绕过）"
    )
    assert all(b >= a - 1e-12 for a, b in pairwise(anchors)), "anchor 出现回降"
    assert all(z2 <= z1 + 1e-12 for z1, z2 in zip(
        [z_peak] + [z for z, _ in trail], [z for z, _ in trail]
    )), "满额负向连打中 z 未单调下行（落点异常回弹）"


def test_band_bites_by_age_new_user_falls_deeper(tmp_path) -> None:
    """同一连轰序列：新人 band≈全谱 2.6z 托不满（跌幅 < 带 ⇒ 自由回落可见）、
    老用户被收窄的 band 托住（跌幅落入随龄带区间）——band(days) 随龄接在
    写路径上的差分证据。"""
    def _drop(name: str, age_days: float, events: int) -> tuple[float, float]:
        clock = _Clock()
        store = _store(tmp_path, clock, name)
        store.observe("x", "positive", text="你好")        # 建档
        if age_days > 0:
            clock.advance(age_days * _DAY)
            store.observe("x", "positive", delta_override=0.0, text="久处")  # 只推龄/播种
        z_peak = float(_peek_row(store, "x")["z_latent"])
        _hammer_down(store, clock, "x", events)
        z_final = float(_peek_row(store, "x")["z_latent"])
        assert z_final < z_peak - 1e-6, f"{name}：负向序列空跑"
        return z_peak - z_final, v8_goodwill_band(age_days)

    fresh_drop, fresh_band = _drop("fresh.sqlite3", 0.0, 120)
    veteran_drop, veteran_band = _drop("vet.sqlite3", 420.0, 120)
    vet_lo = v8_goodwill_band(420.0 + 120 * 43201.0 / _DAY)
    assert fresh_band == pytest.approx(_V8_DEFAULT_BAND_MIN)          # 2.60：全谱
    assert vet_lo - 1e-9 <= veteran_drop <= veteran_band + 1e-9, (
        "老用户未被随龄收窄的 band 托住（跌幅越出 [band(峰龄+轰程), band(峰龄)]）"
    )
    assert fresh_drop < fresh_band - 1e-6, "新人也被托底 ⇒ 带不随龄放开"
    assert fresh_drop > veteran_drop + 1e-3, (
        f"带不随龄收紧：新人跌 {fresh_drop:.3f} ≤ 老用户跌 {veteran_drop:.3f}"
    )


def test_anchor_and_state_persist_across_paths(tmp_path) -> None:
    """flag 来回切换不丢态（可逆红线）：v8 写入的 anchor/v8_state 经
    v5 路径、v7 路径各走一轮后逐字节原样带回（列透传，不重置存量）。"""
    clock = _Clock()
    store = _store(tmp_path, clock, "persist.sqlite3")
    store.observe("p", "positive", delta_override=0.02, text="你好")
    row = _peek_row(store, "p")
    anchor, state = row["goodwill_anchor"], str(row["v8_state"])
    assert anchor is not None and state.startswith("{")

    # 切到关态（v5 路）：若干事件后两列原样。
    store_off = DynamicAffinityStore(
        tmp_path / "persist.sqlite3", clock=clock, config=types.SimpleNamespace()
    )
    for _ in range(3):
        store_off.observe("p", "positive", text="普通聊天", delta_override=0.0)
        clock.advance(61)
    row2 = _peek_row(store_off, "p")
    assert row2["goodwill_anchor"] == anchor
    assert str(row2["v8_state"]) == state

    # 再开 v8：anchor 以历史值为 prev 单调续推（绝不清零重播）。
    store.observe("p", "insult", delta_override=-0.02, text="坏消息")
    row3 = _peek_row(store, "p")
    assert float(row3["goodwill_anchor"]) >= float(anchor) - 1e-12


def test_v8_off_leaves_columns_untouched(tmp_path) -> None:
    """缺省关 ⇒ v5/v6/v7 路径对 goodwill_anchor/v8_state 零读写（灰度家规）：
    整轮 observe 后 anchor 恒 NULL、state 恒 '{}'，且不落 source='v8' 日志行。"""
    clock = _Clock()
    store = DynamicAffinityStore(
        tmp_path / "off.sqlite3", clock=clock, config=types.SimpleNamespace()
    )
    store.observe("o", "positive", text="在 v5 路聊天", delta_override=0.0)
    clock.advance(61)
    store.observe("o", "insult", text="还是 v5")
    row = _peek_row(store, "o")
    assert row["goodwill_anchor"] is None
    assert str(row["v8_state"]) == "{}"
    with store._lock, store._connect() as connection:
        n = connection.execute(
            "SELECT COUNT(*) FROM affinity_delta_log WHERE sender_id='o' AND source='v8'"
        ).fetchone()[0]
    assert n == 0
