"""好感度「瞬间巨变结构性不可能」跨版本不变量锁（席位 S-T-AFFIN-GUARD，需求项 13 + 裁定 D3）。

D3 口径：今晚不切 v7——生产今天跑的是 v5/v6（`bot_affinity_v7_enabled` 代码缺省
False，**判据只看代码缺省，不读 .env**）。本件的验收语义是：

> **无论 v5/v6、v7、还是两旗来回切换，单条事件与单自然日的展示位移都不得超过
> 同一组上限，且一切非有限脏值（NaN/±inf 与脏 points）在任何一条路上都恰好零位移。**

与同族件的分工（不重复、不覆盖）
--------------------------------
- `test_affinity_v7_structural_locks.py`（T-AFF-1）：在册护栏读回、逐档性派生、
  **存量行**脏值消毒（库读面）；fuzz 的 override 只用有限值。
- `test_affinity_no_instant_swing.py`（S-T-AFF-1）：10^4 量级确定性 fuzz、时间不可
  作弊、绕门面直调执法体；override 同样只用有限值。
- **本件补那两件共同的盲区：`delta_override` / `observe_points(points)` 这两个
  「权威信号入口」对非有限值零消毒。** 改动前实测（日志 §4 RED 原文）三形态：
  ① v7 路 `observe(delta_override=nan)` ⇒ `min(z_hard, z+nan)` 返回 **z_hard 本身**，
     一发把展示分从 +10.1 顶到 **+98.5**（0.1010→0.9850），0.12z 日额度被整段绕过；
  ② v5 路同输入 ⇒ `sqlite3.IntegrityError`（delta 列 NOT NULL 拒绑 NaN），异常外抛；
  ③ `observe_points(nan/±inf)` 两路 ⇒ `max(-100, min(100, nan)) == 100.0`，
     脏值被读成**顶格授权**、恰好打满当日全部增益额度（v5 +3.00 分 / v7 +11.6 分）
     ——fail-open，与「保守缺省」正相反（触发面：BOT_POKE_AFFINITY_DELTA 写成非数）。

修法（全部在 character/affinity.py 单文件内，§5 改动说明）：唯一消毒口
`coerce_override_delta`（非有限 ⇒ 0.0＝本次不计分，计数器/标签照常）在 `_observe`
入口收口两条路；执法体 `_v7_delta` / `_clamp_delta_to_rolling_budget` 内部各留同
判据的第二道（活性判据：门面被绕开时护栏仍在）；落库前 `affinity_after_move` 第三道
（非有限残差 ⇒ 原地不动，绝不写脏行）。**有限值的既有行为逐字节不变 ⇒
不改变任何人的现存分数。**

上限组全部从真身常量**派生**（不手写会过期的数字）：公共单事件/单日界 =
`v7_display_move_for_z_cap(缺省日上限 0.12z)` ≈ 11.98 展示分；v5 专属紧界 =
滚动预算四常量派生（单负事件 1 分 / 6h 2 分 / 24h 4 分 / 24h 增益 3 分）。

牙齿自证（§E）：把真身 `_finite_float_or` 换成「无 NaN 卫」版本（=改动前形态）⇒
v7 顶格巨变与 v5 IntegrityError 都精确复现 ⇒ 本件的「零位移」断言咬的是真身，
不是同义反复。monkeypatch 自动还原，对真实源码零注毒。

全部离线：`tmp_path` 建库 + 注入时钟；不碰 `ChatBot_Runtime/`，不写源码树 `data/`；
不用 `random` 模块（确定性序列全部由固定列表/算术生成）。
"""

from __future__ import annotations

import ast
import dataclasses
import math
import sqlite3
import time
import types
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    affinity as _affinity,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _AFFINITY_BASE,
    _BUDGET_MAX_GAIN_24H_POINTS,
    _BUDGET_MAX_LOSS_24H_POINTS,
    _BUDGET_SINGLE_NEGATIVE_EVENT_POINTS,
    _V7_CONFIG_FIELDS,
    _V7_DEFAULT_DAILY_MOVE_CAP_Z,
    DynamicAffinityStore,
    tier_for_affinity,
    v7_display_move_for_z_cap,
    v7_z_to_display_fraction,
)

_V7_ENV_KEYS = [name.upper() for name, _default in _V7_CONFIG_FIELDS]
_EPS = 1e-6

# ---- 上限组（全部派生量，不手写数字）----
# 跨版本公共界：任何一条路上「单事件」「单自然日」展示位移都不可能超过
# v7 缺省日上限对应的展示位移（v5 预算界更紧，§C 单独钉）。
_COMMON_CAP_DISPLAY = v7_display_move_for_z_cap(_V7_DEFAULT_DAILY_MOVE_CAP_Z)
_COMMON_CAP_TOL = 0.05
# v5/v6 路专属紧界（展示分口径，来自真身常量）：
_V5_SINGLE_LOSS = _BUDGET_SINGLE_NEGATIVE_EVENT_POINTS
_V5_DAY_MOVE = _BUDGET_MAX_GAIN_24H_POINTS + _BUDGET_MAX_LOSS_24H_POINTS  # 3+4=7

_INSULT = "你真差劲，废物闭嘴"
_PRAISE = "谢谢你一直陪着我，今天也想跟你说说话，辛苦了"


@pytest.fixture(autouse=True)
def _isolate_v7_env(monkeypatch):
    """12 枚 v7 env 键一律剥离（与同族件同规）；点名台账逐例清空。"""
    for key in _V7_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.chat_reply.character.affinity._V7_WARNED_KEYS",
        set(),
    )


class _Clock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _config(v7: bool) -> types.SimpleNamespace:
    return types.SimpleNamespace(bot_affinity_v7_enabled=v7)


def _store(tmp_path, name: str, clock: _Clock, v7: bool) -> DynamicAffinityStore:
    return DynamicAffinityStore(Path(tmp_path) / name, clock=clock, config=_config(v7))


def _peek_fraction(store: DynamicAffinityStore, sender: str) -> float:
    """从库里读回展示内部值（不信返回值）。无行=基数口径。"""
    with store._lock, store._connect() as connection:
        row = connection.execute(
            "SELECT affinity FROM user_affinity WHERE sender_id = ?", (sender,)
        ).fetchone()
    return _AFFINITY_BASE if row is None else float(row["affinity"])


def _peek_z(store: DynamicAffinityStore, sender: str) -> float | None:
    with store._lock, store._connect() as connection:
        row = connection.execute(
            "SELECT z_latent FROM user_affinity WHERE sender_id = ?", (sender,)
        ).fetchone()
    return None if row is None or row["z_latent"] is None else float(row["z_latent"])


def _delta_rows(store: DynamicAffinityStore, sender: str) -> list[float]:
    with store._lock, store._connect() as connection:
        rows = connection.execute(
            "SELECT delta FROM affinity_delta_log WHERE sender_id = ?", (sender,)
        ).fetchall()
    return [float(row["delta"]) for row in rows]


_NONFINITE = ("nan", "inf", "-inf")


def _dirty(name: str):
    return {"nan": float("nan"), "inf": float("inf"), "-inf": float("-inf")}[name]


# ---------------------------------------------------------------------------
# A. 核心回归锁：非有限「权威信号」在任何一条路上恰好零位移
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["v5", "v7"])
@pytest.mark.parametrize("dirty", _NONFINITE)
def test_dirty_delta_override_moves_nobody_on_every_path(tmp_path, path, dirty) -> None:
    """改动前实况（日志 §4）：v7 nan 一发顶到 +98.5、+inf 打满日额度；
    v5 nan 抛 IntegrityError、±inf 被预算咬住但语义是「顶格申请」。
    改动后两路统一 = 零位移、不抛、不落增量日志。"""
    clock = _Clock()
    store = _store(tmp_path, f"dirty_{path}_{dirty}.sqlite3", clock, path == "v7")
    store.observe("u1", "neutral", text="先建个档")  # 建档走正常路径
    clock.advance(61)
    before = _peek_fraction(store, "u1")
    rows_before = len(_delta_rows(store, "u1"))

    result = store.observe("u1", "positive", text=_PRAISE, delta_override=_dirty(dirty))

    after = _peek_fraction(store, "u1")
    assert math.isfinite(result) and math.isfinite(after)
    assert abs(after - before) < _EPS, (
        f"{path} 路 delta_override={dirty} 造成 {abs(after - before) * 100:.2f} 分位移"
    )
    assert abs(result - before) < _EPS, "返回值与库内值脱节"
    assert len(_delta_rows(store, "u1")) == rows_before, "脏 override 不得落增量日志"
    assert store.snapshot("u1") is not None  # 门面读回仍健康


@pytest.mark.parametrize("path", ["v5", "v7"])
@pytest.mark.parametrize("points_case", _NONFINITE + ("none",))
def test_dirty_observe_points_moves_nobody_on_every_path(tmp_path, path, points_case) -> None:
    """observe_points 是 poke/管理命令的公开口：脏 points 旧形态被
    `max(-100, min(100, nan)) == 100` 读成顶格授权（fail-open），None 直接
    TypeError。改后 = 零位移（points 是必填参数，None 属脏值而非「不带 override」）。"""
    raw = None if points_case == "none" else _dirty(points_case)
    clock = _Clock()
    store = _store(tmp_path, f"dirtypts_{path}_{points_case}.sqlite3", clock, path == "v7")
    store.observe("u1", "neutral", text="先建个档")
    clock.advance(61)
    before = _peek_fraction(store, "u1")
    result = store.observe_points("u1", raw, source="poke")
    after = _peek_fraction(store, "u1")
    assert math.isfinite(result)
    assert abs(after - before) < _EPS, (
        f"{path} 路 observe_points({points_case}) 位移 {(after - before) * 100:.2f} 分"
    )


@pytest.mark.parametrize("path", ["v5", "v7"])
def test_finite_override_and_points_behavior_unchanged(tmp_path, path) -> None:
    """守恒对照（「缺省行为保守」= 有限值一字不变）：
    - observe_points(+100) 仍是「能打满额度的合法权威信号」（非零位移、界内）；
    - 有限负 override 仍按既有界扣分。二者数值上限走同一公共界。"""
    clock = _Clock()
    store = _store(tmp_path, f"finite_{path}.sqlite3", clock, path == "v7")
    store.observe("u0", "neutral", text="先建个档")
    clock.advance(61)
    before = _peek_fraction(store, "u0")
    moved = store.observe_points("u0", 100.0, source="admin") - before
    assert moved > 0.0, f"{path} 路有限 +100 权威信号应当计分（非零位移）"
    assert moved * 100.0 <= _COMMON_CAP_DISPLAY + _COMMON_CAP_TOL, "增益单事件越公共界"
    clock.advance(61)
    store.observe("u1", "neutral", text="先建个档")
    clock.advance(61)
    before1 = _peek_fraction(store, "u1")
    down = store.observe("u1", "neutral", delta_override=-5.0)
    assert down < before1, f"{path} 路有限 -5.0 override 应当按界扣分"
    assert (before1 - down) * 100.0 <= _COMMON_CAP_DISPLAY + _COMMON_CAP_TOL


@pytest.mark.parametrize("path", ["v5", "v7"])
def test_dirty_event_does_not_freeze_next_legitimate_event(tmp_path, path) -> None:
    """脏事件零位移且**不占冷却坑**：紧随其后的合法信号必须照常计分
    （否则消毒修的是巨变、造的是「一条脏数据永久封人」的新事故）。"""
    clock = _Clock()
    store = _store(tmp_path, f"nofreeze_{path}.sqlite3", clock, path == "v7")
    store.observe("u1", "neutral", text="先建个档")
    clock.advance(61)
    before = _peek_fraction(store, "u1")
    store.observe("u1", "positive", delta_override=float("nan"))
    assert abs(_peek_fraction(store, "u1") - before) < _EPS
    clock.advance(61)
    moved = store.observe("u1", "neutral", delta_override=0.01)
    assert moved > before + 0.005, f"{path} 路脏事件把后续合法信号冻住了"


# ---------------------------------------------------------------------------
# B. 跨版本位移上限组：三条路共用同一组界（D3 验收判据）
# ---------------------------------------------------------------------------


def _attack_sequence():
    """最坏混合序列：顶格权威正负信号 × 辱骂连发 × 好话连发 × 脏值穿插。
    每项 (kind, payload)；全程 61s 间隔 ⇒ 每发都过冷却门。"""
    steps = []
    for index in range(14):
        steps.append(("points", 100.0 if index % 2 else -100.0))
        steps.append(("observe", ("insult", f"{_INSULT}#{index}")))
        steps.append(("observe", ("positive", f"{_PRAISE}#{index}")))
        steps.append(("override", 3.0))
        steps.append(("override", -3.0))
        steps.append(("override", float("nan")))
    return steps


@pytest.mark.parametrize("path", ["v5", "v7"])
def test_common_caps_hold_for_event_and_day(tmp_path, path) -> None:
    """逐条打最坏序列，每发之后从库里读回真值断言：
    单事件 |Δdisplay| ≤ 公共界；本地自然日累计 |Δdisplay| ≤ 公共界；
    档号至多挪一档；展示值离两端 ≥40 分（最坏混合也碰不到极端）。"""
    clock = _Clock()
    store = _store(tmp_path, f"caps_{path}.sqlite3", clock, path == "v7")
    v7 = path == "v7"
    prev = _AFFINITY_BASE
    day_totals: dict[int, float] = {}
    tier_prev = tier_for_affinity(prev)
    moved_any = False
    for step_index, (kind, payload) in enumerate(_attack_sequence()):
        clock.advance(61)
        sender = "u1"
        if kind == "points":
            store.observe_points(sender, payload, source="mix")
        elif kind == "override":
            store.observe(sender, "neutral", text="一句普通的话", delta_override=payload)
        else:
            behavior, text = payload
            store.observe(sender, behavior, text=text)
        after = _peek_fraction(store, sender)
        assert math.isfinite(after)
        jump = abs(after - prev) * 100.0
        assert jump <= _COMMON_CAP_DISPLAY + _COMMON_CAP_TOL, (
            f"{path} 第{step_index}步单事件位移 {jump:.3f} 分 > 公共界 "
            f"{_COMMON_CAP_DISPLAY:.3f}"
        )
        tier_now = tier_for_affinity(after)
        assert abs(tier_now - tier_prev) <= 1, f"{path} 档号一次跨 {abs(tier_now - tier_prev)} 档"
        day = int(time.strftime("%Y%m%d", time.localtime(clock.now)))
        day_totals[day] = day_totals.get(day, 0.0) + jump
        assert day_totals[day] <= _COMMON_CAP_DISPLAY + 0.2, (
            f"{path} 第{day}日累计位移 {day_totals[day]:.3f} 分越公共界"
        )
        assert abs(after) < 0.55, "最坏混合序列也离两端很远"
        if v7:
            z = _peek_z(store, sender)
            assert z is not None and math.isfinite(z)
            assert abs(v7_z_to_display_fraction(z) - after) < 1e-9, "z 与展示值失互逆"
        if jump > _EPS:
            moved_any = True
        prev, tier_prev = after, tier_now
    assert moved_any, "全零位移 ⇒ 本用例在空跑"


def test_flag_switch_is_not_a_swing_channel(tmp_path) -> None:
    """第三条路：旗标来回切（v5→v7→v5→v7）。切档瞬间 z 由 affinity 现推
    （`v7_display_fraction_to_z` 单调保档），**换旗本身不是位移通道**——
    每一发的界与固定旗时同尺；且切换后紧接一发脏值 ⇒ 恰零位移。"""
    clock = _Clock()
    flag = {"v7": False}
    store = DynamicAffinityStore(
        Path(tmp_path) / "flag_switch.sqlite3",
        clock=clock,
        config=lambda: _config(flag["v7"]),
    )
    prev = _AFFINITY_BASE
    tier_prev = tier_for_affinity(prev)
    step = 0
    for path, count in [("v5", 8), ("v7", 8), ("v5", 4), ("v7", 4)]:
        flag["v7"] = path == "v7"
        for index in range(count):
            clock.advance(61)
            step += 1
            store.observe(
                "u1",
                "positive" if index % 2 else "insult",
                text=_PRAISE if index % 2 else _INSULT,
            )
            after = _peek_fraction(store, "u1")
            assert abs(after - prev) * 100.0 <= _COMMON_CAP_DISPLAY + _COMMON_CAP_TOL, (
                f"切换路第{step}发（{path}）位移越界"
            )
            tier_now = tier_for_affinity(after)
            assert abs(tier_now - tier_prev) <= 1, f"切换路第{step}发跨档"
            prev, tier_prev = after, tier_now
    clock.advance(61)
    before = prev
    store.observe("u1", "neutral", delta_override=float("nan"))
    assert abs(_peek_fraction(store, "u1") - before) < _EPS, "切换后脏值事件应恰零位移"


# ---------------------------------------------------------------------------
# C. v5/v6（今日生产路）真实数字：单发与五连发的最大位移（简报第 2 问）
# ---------------------------------------------------------------------------


def test_v5_worst_single_and_five_streak_real_numbers(tmp_path) -> None:
    """实测算式（读代码 + 实跑对账，全式见日志 §2）：
    - 单发正向自然信号 raw = 0.02×因子钳顶1.25×饱和1×递减1 = +2.5 分上限；
    - 单发负向自然信号 raw = -0.10×1.25 = -12.5 分，被「单负事件 ≤1 分」咬到 -1；
    - 辱骂五连发（61s 间隔同 6h 窗）：-1, -1, 0, 0, 0 ⇒ 总位移恰 -2.0 分（6h 帽）；
    - 好话五连发：+2.5(或更少), 补足到 +3, 0, 0, 0 ⇒ 总位移恰 +3.0 分（24h 增益帽
      ——凡因子乘积 ≥0.9375 前两发即打满，更小则第三发补足；两情形和恒=帽）。"""
    clock = _Clock()
    store = _store(tmp_path, "v5_numbers.sqlite3", clock, v7=False)

    single_pos = store.observe("n1", "positive", text=_PRAISE)
    assert (single_pos - _AFFINITY_BASE) * 100.0 <= 2.5 + 1e-9
    clock.advance(61)
    single_neg = store.observe("n2", "insult", text=_INSULT)
    assert (_AFFINITY_BASE - single_neg) * 100.0 <= _V5_SINGLE_LOSS + 1e-9

    for index in range(5):
        store.observe("s5", "insult", text=f"{_INSULT}#{index}")
        clock.advance(61)
    five_neg = _peek_fraction(store, "s5") - _AFFINITY_BASE
    assert five_neg == pytest.approx(-0.02, abs=1e-6), (
        f"辱骂五连发总位移 {five_neg * 100:.3f} 分，预期 -2.000 分（6h 损失帽）"
    )

    for index in range(5):
        store.observe("p5", "positive", text=f"{_PRAISE}#{index}")
        clock.advance(61)
    five_pos = _peek_fraction(store, "p5") - _AFFINITY_BASE
    assert five_pos == pytest.approx(0.03, abs=1e-6), (
        f"好话五连发总位移 {five_pos * 100:.3f} 分，预期 +3.000 分（24h 增益帽）"
    )
    assert abs(five_pos * 100.0) <= _COMMON_CAP_DISPLAY
    assert abs(five_neg * 100.0) <= _COMMON_CAP_DISPLAY
    assert _V5_DAY_MOVE <= _COMMON_CAP_DISPLAY  # v5 紧界(7)确在公共界(≈11.98)之内


# ---------------------------------------------------------------------------
# D. 活性判据：护栏住在执法体内，不在门面
# ---------------------------------------------------------------------------


def test_liveness_v7_delta_body_guard(tmp_path) -> None:
    """不经任何门面直调 `_v7_delta`：delta_override 非有限 ⇒ applied=0、z 不动。"""
    clock = _Clock()
    store = _store(tmp_path, "body_v7.sqlite3", clock, v7=True)
    v7 = _affinity.resolve_v7_settings(_config(True))
    day_index = int(time.strftime("%Y%m%d", time.localtime(clock.now)))
    with store._lock, store._connect() as connection:
        for slot, dirty in enumerate(_NONFINITE):
            applied, new_z, _state = store._v7_delta(
                connection, f"s{slot}", "", "neutral", 0.3,
                v7=v7, state_json="{}", now=clock.now, day_index=day_index,
                text="一句普通的话", gap_seconds=None, delta_override=_dirty(dirty),
                mood_valence=None, first_impression=None, interaction_count=5,
                day_counters={}, responded_to_question=None, source_event_id="",
            )
            assert applied == 0.0 and new_z == 0.3, f"执法体放行脏 override：{dirty}"


def test_liveness_rolling_budget_body_guard(tmp_path) -> None:
    """直调 `_clamp_delta_to_rolling_budget`：非有限 delta ⇒ 0、不落行。"""
    clock = _Clock()
    store = _store(tmp_path, "body_v5.sqlite3", clock, v7=False)
    with store._lock, store._connect() as connection:
        for slot, dirty in enumerate(_NONFINITE):
            applied = store._clamp_delta_to_rolling_budget(
                connection, f"s{slot}", "", _dirty(dirty), clock.now, "", None, ""
            )
            assert applied == 0.0, f"滚动预算放行脏 delta：{dirty}"
        (rows,) = connection.execute(
            "SELECT COUNT(*) FROM affinity_delta_log"
        ).fetchone()
    assert int(rows) == 0, "脏 delta 不得落增量日志"


def test_affinity_after_move_belt(tmp_path) -> None:
    """第三道闸（落库前）：合法值逐字节等于旧 clamp（含 ±1 边界钳位）；
    非有限残差 ⇒ 保持 current 原地不动，绝不产脏行、绝不抛。"""
    belt = _affinity.affinity_after_move
    assert belt(0.4, 0.1) == pytest.approx(0.5)
    assert belt(0.98, 0.5) == 1.0
    assert belt(-0.98, -0.5) == -1.0
    assert belt(0.3, float("nan")) == 0.3
    assert belt(0.3, float("inf")) == 0.3
    assert belt(0.3, float("-inf")) == 0.3
    assert math.isfinite(belt(0.3, float("nan")))


# ---------------------------------------------------------------------------
# E. 牙齿自证：拿掉消毒口，旧巨变/旧异常精确复现（断言非同义反复）
# ---------------------------------------------------------------------------


def _no_nan_guard(raw, default):  # 等价「改动前」形态：只挡非数文本，不挡 NaN/±inf
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(default)
    return value


def test_teeth_removing_the_guard_restores_the_old_swing_and_the_old_crash(
    monkeypatch, tmp_path
) -> None:
    """差分证据（A-1 后改判为三层对账，原"拿掉消毒口⇒必现 88 分巨变"的差分面
    现需**连 A-1 双帽一起摘掉**才复现——这本身就是纵深防线的差分锁）：
    ① 只把真身 `_finite_float_or` 换成无 NaN 卫版本（A-1 双帽在场）：
      v7 `observe(delta_override=nan)` 的伤害从 +88.4 收敛到单事件帽量级
      （≤ `v7_display_move_for_z_cap(0.10z)` ≈ 10 分）——**消毒口不再是唯一防线**；
    ② 再经在册配置面把两枚帽同放到 99z（逐字等价"A-1 之前"的正向直穿形态）：
      同一发旧巨变（≥40 分，实测 +88）精确复现 ⇒ ①的 ≤10 分断言非同义反复；
    ③ v5 路同输入 `sqlite3.IntegrityError` 复发（该路无 z 域帽，判据不变）。
    monkeypatch 出作用域自动还原 ⇒ 对真实源码零注毒。"""
    monkeypatch.setattr(_affinity, "_finite_float_or", _no_nan_guard)

    clock = _Clock()
    store = _store(tmp_path, "teeth_v7.sqlite3", clock, v7=True)
    store.observe("u1", "neutral", text="先建个档")
    clock.advance(61)
    before = _peek_fraction(store, "u1")
    store.observe("u1", "positive", delta_override=float("nan"))
    after = _peek_fraction(store, "u1")
    capped_move = (after - before) * 100.0
    cap_ceiling = v7_display_move_for_z_cap(_affinity._V7_DEFAULT_NEGATIVE_EVENT_CAP_Z)
    assert capped_move <= cap_ceiling + 0.05, (
        f"消毒口摘掉后伤害 {capped_move:.1f} 分越出单事件帽界 {cap_ceiling:.1f} 分"
        " ⇒ A-1 正向帽没接住这一层（纵深失守）"
    )
    assert capped_move > 0.0, "摘掉消毒口竟零位移 ⇒ 本段在空跑"

    real_resolve = _affinity.resolve_v7_settings
    monkeypatch.setattr(
        _affinity,
        "resolve_v7_settings",
        lambda config: dataclasses.replace(
            real_resolve(config),
            negative_event_cap_z=99.0,
            daily_move_cap_z=99.0,
        ),
    )
    clock_pre = _Clock()
    store_pre = _store(tmp_path, "teeth_v7_preA1.sqlite3", clock_pre, v7=True)
    store_pre.observe("u1", "neutral", text="先建个档")
    clock_pre.advance(61)
    before_pre = _peek_fraction(store_pre, "u1")
    store_pre.observe("u1", "positive", delta_override=float("nan"))
    after_pre = _peek_fraction(store_pre, "u1")
    assert (after_pre - before_pre) * 100.0 > 40.0, (
        "摘掉消毒口+摘掉双帽竟仍无巨变 ⇒ 本件的位移断言没咬到真身（同义反复）"
    )

    clock2 = _Clock()
    store2 = _store(tmp_path, "teeth_v5.sqlite3", clock2, v7=False)
    store2.observe("u1", "neutral", text="先建个档")
    clock2.advance(61)
    with pytest.raises(sqlite3.IntegrityError):
        store2.observe("u1", "positive", delta_override=float("nan"))


# ---------------------------------------------------------------------------
# F. 卫生自锁：入口收口一处 + 第二真身防立
# ---------------------------------------------------------------------------


def test_no_second_override_sanitizer_and_entry_is_single() -> None:
    """AST 判据：① `_observe` 里对 `delta_override` 的消毒调用恰一处（入口收口，
    不许每分支各夹一次）；② `coerce_override_delta` 的定义只住在真身 affinity.py
    （全 plugins 无第二份）。"""
    module_file = Path(_affinity.__file__).resolve()
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    obs = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_observe"
    )
    sanitizers = [
        node
        for node in ast.walk(obs)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "coerce_override_delta"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "delta_override"
    ]
    assert len(sanitizers) == 1, f"_observe 入口消毒点应恰为一处，实得 {len(sanitizers)}"
    repo_root = Path(__file__).resolve().parents[1]
    copies = []
    for path in (repo_root / "plugins").rglob("*.py"):
        if path.resolve() == module_file:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "def coerce_override_delta" in text:
            copies.append(str(path))
    assert not copies, f"coerce_override_delta 出现第二真身：{copies}"
