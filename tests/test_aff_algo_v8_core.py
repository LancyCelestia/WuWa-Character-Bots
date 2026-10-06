"""好感度 v8 第二腿·构造界核心锁（S-FIX-AFF-ALGO-R 收编席，2026-09-28）。

对账对象：docs/affinity-design.md §C.2/§C.3/§C.5.1（v8 凸组合冲量）。
本件锁的是「界来自数学、不来自 if」这条脊柱：

- 引理 1（|u|≤1）的源头是 ``v8_normalize_weights`` 的 ``Σ|w_i|=1`` 构造归一
  与 ``v8_impulse`` 内的 φ 钳位——**注毒自证**：把归一化行换成透传（等价于
  删掉它），同一输入的 |u| 必须破界（抓住＝FAILED 形态的违例读数，不是
  ERROR）；真实路径同输入必须仍在界内。
- 幂等面：``v8_impulse`` 对已归一权重再归一不变（防直调用带生权重）。
- resolve 域：非法/零/负 ⇒ 代码缺省；κ≤0.25、D≤0.5 域钳；blend 边缘
  [0.05,0.45]；非有限值不抛。
- 注入面（§C.5.1）：v8 启用 ⇒ 带边缘双句混拼（只用 ``_TIER_BY_ID`` 真身
  原句运行时拼接，源码零副本）、中段单句、``linear_transition_for_affinity``
  返空（两套过渡不并存）；红线四条款原样携带；措辞定性、无固定加减数值。

全部离线：纯函数 + tmp_path 注入时钟，不碰 ChatBot_Runtime/，不写源码树 data/。
"""

from __future__ import annotations

import json
import math
import re
import types

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    affinity as _affinity,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _TIER_BY_ID,
    _V8_CONFIG_FIELDS,
    _V8_DEFAULT_IMPULSE_CAP_Z,
    _V8_DEFAULT_IMPULSE_WEIGHTS,
    V8Settings,
    attitude_for_affinity,
    linear_transition_for_affinity,
    resolve_v8_settings,
    v8_ambient_update,
    v8_continuity,
    v8_impulse,
    v8_normalize_weights,
    v8_quality_centered,
)

_V8_ENV_KEYS = [name.upper() for name, _default in _V8_CONFIG_FIELDS]
_TOL = 1e-9


@pytest.fixture(autouse=True)
def _isolate_v8_env(monkeypatch):
    """v8 增量 env 键一律剥离：配置面只由本件点名供给（家规同 v7/v8 族）。"""
    for key in _V8_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# =========================================================================
# A. 凸组合界（引理 1）——含注毒自证
# =========================================================================

_EXTREMES = (-1.0, -0.5, 0.0, 0.5, 1.0)


def test_impulse_bound_holds_for_extreme_phi_grid_with_default_weights() -> None:
    """六 φ 取 ±1/±0.5/0 的代表格点（≤2 非零分量 + 全顶格）× 缺省权重 ⇒ |u| ≤ 1。"""
    for combo in _grid_combos():
        u = v8_impulse(combo, _V8_DEFAULT_IMPULSE_WEIGHTS)
        assert abs(u) <= 1.0 + _TOL, f"φ={combo} 破界 u={u}"
    # 顶格同向时 u 应恰达 ±1（界是紧的，不是虚设的松弛）
    assert v8_impulse((1.0,) * 6, _V8_DEFAULT_IMPULSE_WEIGHTS) == pytest.approx(1.0, abs=1e-9)
    assert v8_impulse((-1.0,) * 6, _V8_DEFAULT_IMPULSE_WEIGHTS) == pytest.approx(-1.0, abs=1e-9)


def _grid_combos():
    # 全格点 5^6=15625 太多：取「每个位置单独顶格 + 随机对角」的代表集。
    import itertools

    yield from (
        tuple(combo)
        for combo in itertools.product(_EXTREMES, repeat=6)
        # 只留稀疏但有代表性的一维：非零分量 ≤2，外加全顶格两例
        if sum(1 for x in combo if x != 0.0) <= 2 or all(abs(x) == 1.0 for x in combo)
    )


@pytest.mark.parametrize(
    "raw",
    [
        (2.0, 2.0, 2.0, 2.0, 2.0, 2.0),          # 生权重 Σ|w|=12
        [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],          # Σ|w|=3
        json.dumps({"w1": 3.0, "w2": -1.0, "w3": 0.0, "w4": 0.0, "w5": 0.0, "w6": 1.0}),
    ],
)
def test_impulse_renormalizes_raw_weights_by_construction(raw) -> None:
    """直调带生权重（Σ|w|≠1）⇒ v8_impulse 就地再归一 ⇒ |u|≤1 仍成立（幂等防线）。"""
    u = v8_impulse((1.0, 1.0, 1.0, 1.0, 1.0, 1.0), raw)
    assert abs(u) <= 1.0 + 1e-9
    w = v8_normalize_weights(raw)
    assert w is not None
    assert sum(abs(x) for x in w) == pytest.approx(1.0, abs=1e-9)
    # 归一是幂等的：归一后的权重再归一不变。
    w2 = v8_normalize_weights(w)
    assert w2 is not None
    assert all(abs(a - b) <= 1e-12 for a, b in zip(w, w2))


def test_poison_injection_removing_normalization_breaks_the_bound(monkeypatch) -> None:
    """注毒自证（规格 §C.2/§F「把归一化删掉此测试必红」的牙齿）：
    把 ``v8_normalize_weights`` 换成**透传不除 Σ|w|** 的形态（逐字等价"删掉
    归一化那一行"），同输入必须出现 |u|>1 ——违例被抓住（FAILED 形态的
    构造性违例读数），证明界确实来自数学构造、不是别处的兜底。
    真实路径同输入必须仍 ≤1，两侧都断言。"""
    raw_weights = (2.0, 2.0, 2.0, 2.0, 2.0, 2.0)
    phis = (1.0,) * 6
    # 真身：再归一 ⇒ 界内。
    assert abs(v8_impulse(phis, raw_weights)) <= 1.0 + _TOL

    def _passthrough(raw):
        data = json.loads(str(raw)) if isinstance(raw, str) else raw
        if isinstance(data, dict):
            return tuple(float(data[f"w{i}"]) for i in range(1, 7))
        return tuple(float(x) for x in data)  # 不除 Σ|w|：即"删掉归一化行"

    monkeypatch.setattr(_affinity, "v8_normalize_weights", _passthrough)
    poisoned = v8_impulse(phis, raw_weights)
    assert poisoned > 1.0, "注毒后界竟未破 ⇒ 界不来自归一化行（本锁失去牙齿，必须红）"
    # 事后 clamp 兜底不许存在：破界值必须原样传出（证明没有第二道 if 在偷偷救场）。
    assert poisoned == pytest.approx(12.0)


def test_normalize_weights_semantics() -> None:
    """构造归一口自己的判据：Σ=1 保留、Σ≠1 归一、坏输入 None（调用方回退缺省）。"""
    w = v8_normalize_weights([0.3, 0.25, 0.15, 0.1, 0.1, 0.1])
    assert w is not None and sum(abs(x) for x in w) == pytest.approx(1.0, abs=1e-12)
    w2 = v8_normalize_weights([2.0] * 6)
    assert w2 is not None and sum(abs(x) for x in w2) == pytest.approx(1.0, abs=1e-12)
    assert w2 == pytest.approx(tuple([1.0 / 6.0] * 6), abs=1e-12)
    assert v8_normalize_weights([1, 2, 3]) is None            # 长度错
    assert v8_normalize_weights([0.0] * 6) is None             # 全零
    assert v8_normalize_weights([float("nan")] * 6) is None    # 非有限
    assert v8_normalize_weights("not-json") is None
    assert v8_normalize_weights('{"w1":0.5}') is None          # 键不全
    assert v8_normalize_weights('{"w1":0.5,"w2":0.1,"w3":0.1,"w4":0.1,"w5":0.1,"w6":0.1}') == (
        pytest.approx((0.5, 0.1, 0.1, 0.1, 0.1, 0.1))
    )


# =========================================================================
# B. 纯函数分量形态（φ_q / φ_c / āmbient）
# =========================================================================


def test_quality_centered_shape() -> None:
    """φ_q=(q−ā)/(1−|ā|)：q=ā ⇒ 0；顶格基线不放大爆冲（分母下限钳）；值域 [−1,1]。"""
    assert v8_quality_centered(0.4, 0.4) == pytest.approx(0.0)
    assert v8_quality_centered(0.6, 0.2) == pytest.approx(0.5)  # (0.6-0.2)/(1-0.2)
    assert abs(v8_quality_centered(1.0, 0.999999)) <= 1.0
    assert abs(v8_quality_centered(float("nan"), 0.3)) <= 1.0   # 脏 q 归口 0 ⇒ 有界
    assert v8_quality_centered(0.5, float("inf")) == pytest.approx(0.5)  # 脏基线 ⇒ ā=0


def test_continuity_counted_once_per_day() -> None:
    """φ_c 每天只计一次：同日重复 ⇒ (原样, 0)；隔日 +1；断档重置为 1；7 天封顶 1.0。"""
    day = 86400.0
    streak, phi = v8_continuity(None, 0, 0.0)
    assert (streak, phi) == (1, pytest.approx(1.0 / 7.0))
    same, phi_same = v8_continuity(0.0, 1, 0.0)  # 同一日界再来
    assert (same, phi_same) == (1, 0.0)
    nxt, phi_nxt = v8_continuity(0.0, 1, day)
    assert (nxt, phi_nxt) == (2, pytest.approx(2.0 / 7.0))
    gap, phi_gap = v8_continuity(0.0, 5, 3 * day)  # 断档（隔了 3 天）
    assert (gap, phi_gap) == (1, pytest.approx(1.0 / 7.0))
    long_streak, phi_long = v8_continuity(0.0, 30, day)
    assert long_streak == 31 and phi_long == pytest.approx(1.0)  # min(1, n/7) 封顶


def test_ambient_update_is_long_tail_then_ema() -> None:
    """两段式：先 0.5^(Δt/τ) 向 0 半衰（纯衰减 α=0 时恰为指数长尾），再按步长 α
    向本次 q 收拢；返回 (a, now)，值域钳 [−1,1]；脏入参不抛。"""
    tau = 28.0
    # α=0 ⇒ 只衰减：Δt=τ 天恰半。
    a1, t1 = v8_ambient_update(0.8, 0.0, tau * 86400.0, 0.5, halflife_days=tau, alpha=0.0)
    assert a1 == pytest.approx(0.4) and t1 == pytest.approx(tau * 86400.0)
    # α=0.5 ⇒ 衰减后向 q 收拢一半。
    a2, _ = v8_ambient_update(0.8, 0.0, tau * 86400.0, 1.0, halflife_days=tau, alpha=0.5)
    assert a2 == pytest.approx(0.4 * 0.5 + 1.0 * 0.5)
    # 时间倒流（now ≤ ambient_at）⇒ 不衰减不抛。
    a3, _ = v8_ambient_update(0.5, 100.0, 50.0, 1.0, halflife_days=tau)
    assert a3 == pytest.approx(0.5 * 0.5 + 1.0 * 0.5)
    # 非有限入参全部归口，绝不信手放 inf 进状态。
    a4, _ = v8_ambient_update(float("nan"), float("inf"), float("nan"), 0.5, halflife_days=tau)
    assert math.isfinite(a4)


# =========================================================================
# C. resolve_v8_settings 配置面（域钳 + 回退 + 不抛）
# =========================================================================


def test_resolve_defaults_disabled_and_byte_stable() -> None:
    """缺省灰度关死 + κ/D/blend 取代码缺省（config=None、env 剥离时）。"""
    s = resolve_v8_settings(None)
    assert s.enabled is False
    assert s.impulse_cap_z == pytest.approx(_V8_DEFAULT_IMPULSE_CAP_Z)
    assert s.daily_move_cap_z == pytest.approx(_affinity._V8_DEFAULT_DAILY_MOVE_CAP_Z)
    assert s.tier_blend_edge == pytest.approx(_affinity._V8_DEFAULT_TIER_BLEND_EDGE)
    assert s.impulse_weights == _V8_DEFAULT_IMPULSE_WEIGHTS


def test_resolve_domain_clamps_and_falls_back() -> None:
    """尺度键：非正/非数值 ⇒ 代码缺省；过松 ⇒ 域钳（κ≤0.25、D≤0.5、edge∈[0.05,0.45]）。

    台账 F-16 键面拆轴（2026-10-06 用户裁定甲）：v8 收紧侧的日额度改读
    `bot_affinity_daily_move_cap_v8_z`，旧键 `bot_affinity_daily_move_cap_z` 只喂 v7
    评分判据侧。桩因此改**喂哪枚键**（断言一条没松）：本侧那枚仍喂过松值 99.0 ⇒
    仍须被域钳到 0.5（证收紧侧的值真被吃到），同批把旧键钉一枚**很紧**的 0.01 ——
    若两路还串着同一枚键，读数会掉到 0.01 而不是 0.5，拆轴就算没落地。
    """
    cfg = types.SimpleNamespace(
        bot_affinity_v8_enabled="true",
        bot_affinity_v8_impulse_cap_z=99.0,
        bot_affinity_daily_move_cap_v8_z=99.0,
        bot_affinity_daily_move_cap_z=0.01,
        bot_affinity_v8_tier_blend_band=99.0,
    )
    s = resolve_v8_settings(cfg)
    assert s.enabled is True
    assert s.impulse_cap_z == pytest.approx(0.25)
    assert s.daily_move_cap_z == pytest.approx(0.5)
    assert s.tier_blend_edge == pytest.approx(0.45)
    bad = types.SimpleNamespace(
        bot_affinity_v8_impulse_cap_z=0.0,
        bot_affinity_v8_ambient_halflife_days=float("nan"),
        bot_affinity_v8_impulse_weights="[1,2]",
    )
    s2 = resolve_v8_settings(bad)
    assert s2.impulse_cap_z == pytest.approx(_V8_DEFAULT_IMPULSE_CAP_Z)
    assert s2.ambient_halflife_days == pytest.approx(_affinity._V8_DEFAULT_AMBIENT_HALFLIFE_DAYS)
    assert s2.impulse_weights == _V8_DEFAULT_IMPULSE_WEIGHTS


def test_resolve_normalizes_over_sum_weights_and_keeps_band_pair() -> None:
    """Σ|w|≠1 的合法 JSON ⇒ 构造归一后执行；带值 band_min/band_max 原样透传。"""
    cfg = types.SimpleNamespace(
        bot_affinity_v8_impulse_weights='[0.5,0.5,0.0,0.0,0.0,0.0]',
        bot_affinity_goodwill_band_min=2.0,
        bot_affinity_goodwill_band_max=0.5,
    )
    s = resolve_v8_settings(cfg)
    assert sum(abs(x) for x in s.impulse_weights) == pytest.approx(1.0, abs=1e-12)
    assert s.goodwill_band_min == pytest.approx(2.0)
    assert s.goodwill_band_max == pytest.approx(0.5)


# =========================================================================
# D. 注入面（§C.5.1）：带内混合 · 原句复用 · 过渡不并存 · 红线全带 · 定性
# =========================================================================


def _attitude_body(text: str) -> str:
    # 取「）：」与「。共同态度红线」之间的基调正文。
    m = re.search(r"态度（档位「.+?」）：(.+?)。共同态度红线：", text, re.DOTALL)
    assert m is not None, f"态度文本形制破坏：{text[:60]}..."
    return m.group(1)


def test_blend_middle_of_tier_is_verbatim_single_sentence() -> None:
    """档中（λ∈[edge,1−edge]）：混合输出与真身单档原句逐字同（红线全带）。"""
    on = V8Settings(enabled=True)
    off = V8Settings(enabled=False)
    for tier, (_name, instruction) in _TIER_BY_ID.items():
        # 该档中心：λ=0.5 ⇒ 单档原句。
        lo = -100.0 + 25.0 * (tier - _affinity._TIER_MIN_ID)
        center = (lo + 12.5) / 100.0
        assert _attitude_body(attitude_for_affinity(center, v8=on)) == instruction
        # v8 关 ⇒ 逐字节旧形态。
        assert attitude_for_affinity(center, v8=off) == attitude_for_affinity(center)
        assert "共同态度红线" in attitude_for_affinity(center, v8=on)


def test_blend_at_edges_reuses_adjacent_verbatim_sentences() -> None:
    """带边缘：运行时拼接相邻两档**原句**（不新造句子）；极值档缺侧不混。"""
    on = V8Settings(enabled=True)
    name_lo, inst_lo = _TIER_BY_ID[0]      # 友善
    name_hi, inst_hi = _TIER_BY_ID[1]      # 亲近
    near_upper_edge = (0.0 + 24.6) / 100.0  # 友善档内 λ≈0.984 > 1−edge ⇒ 与上一档混
    body = _attitude_body(attitude_for_affinity(near_upper_edge, v8=on))
    assert "流向" in body and inst_lo in body and inst_hi in body
    assert f"「{name_lo}」" in body and f"「{name_hi}」" in body
    # 下缘对称。
    _name_dn, inst_dn = _TIER_BY_ID[-1]
    near_lower_edge = (0.0 + 0.4) / 100.0
    body_dn = _attitude_body(attitude_for_affinity(near_lower_edge, v8=on))
    assert inst_dn in body_dn and inst_lo in body_dn
    # 最高档（独一份）上缘无邻档 ⇒ 缺侧不混，仍是单档原句。
    top_center = (-100.0 + 25.0 * (3 - _affinity._TIER_MIN_ID) + 24.9) / 100.0
    top_name, top_inst = _TIER_BY_ID[3]
    assert _attitude_body(attitude_for_affinity(top_center, v8=on)) == top_inst
    assert top_name in attitude_for_affinity(top_center, v8=on)


def test_transition_mechanisms_do_not_coexist() -> None:
    """两套过渡不并存（禁第二真身）：v8 启用 ⇒ linear_transition 恒空串；
    v8 关 ⇒ 旧措辞行为逐字节如旧（边界内外各有断言）。"""
    on = V8Settings(enabled=True)
    for value in (-0.99, -0.34, -0.26, 0.09, 0.24, 0.26, 0.49, 0.74, 0.99):
        assert linear_transition_for_affinity(value, v8=on) == ""
    off = V8Settings(enabled=False)
    # 旧形态：档界 ±6 展示分内有过渡措辞、档中有空串——对照 v8 关的逐字节行为。
    assert linear_transition_for_affinity(0.245) == linear_transition_for_affinity(0.245, v8=off)
    assert linear_transition_for_affinity(0.245, v8=off) != ""
    assert linear_transition_for_affinity(0.10, v8=off) == ""


def test_blend_output_carries_no_fixed_add_sub_numbers() -> None:
    """展示红线（规则/§C.5）：混拼正文与旧措辞都不许出现「±N 分/点」固定数值。"""
    on = V8Settings(enabled=True)
    pattern = re.compile(r"[加减]\s*\d+(?:\.\d+)?\s*[分点]|\d+(?:\.\d+)?\s*[分点]\s*[每轮单日]")
    for hundredths in range(-100, 101, 3):
        value = hundredths / 100.0
        text = attitude_for_affinity(value, v8=on)
        assert not pattern.search(text), f"数值泄露形态 s={value}: {text}"
        assert not pattern.search(attitude_for_affinity(value)), f"旧路径数值泄露 s={value}"


def test_snapshot_attitude_follows_store_v8_config(tmp_path) -> None:
    """config 面开 v8 ⇒ snapshot 的态度注入走带内混合（与写路径同一把尺）；
    关 ⇒ 与 attitude_for_affinity(score) 逐字节同（既有快照锁不被扰动）。"""
    clock = _ClockStatic(1_000_000.0)
    store_off = _affinity.DynamicAffinityStore(
        tmp_path / "a.sqlite3", clock=clock, config=types.SimpleNamespace()
    )
    store_off.observe("u1", "positive", delta_override=0.0)
    snap_off = store_off.snapshot("u1")
    assert snap_off["attitude"] == attitude_for_affinity(snap_off["affinity"])

    cfg_on = types.SimpleNamespace(bot_affinity_v8_enabled=True, bot_affinity_v8_tier_blend_band=0.25)
    store_on = _affinity.DynamicAffinityStore(
        tmp_path / "b.sqlite3", clock=clock, config=cfg_on
    )
    store_on.observe("u1", "positive", delta_override=0.0)
    snap_on = store_on.snapshot("u1")
    assert snap_on["attitude"] == attitude_for_affinity(
        snap_on["affinity"], v8=resolve_v8_settings(cfg_on)
    )


class _ClockStatic:
    def __init__(self, start: float) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now
