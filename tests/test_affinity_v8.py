"""好感度 v8 回归（AFFINITY-V8 席，2026-09-27 用户裁定「边际递减 + 长尾效应」）。

规格基线：docs/affinity-design.md v8 章节。两把新尺——
① 边际递减：z 路径步进乘 γ(|z|)=half/(half+|z|)（half=z_hard，正负对称，
   |z| 越大每分增益的边际越小）；
② 长尾：更新处不再按 ±z_hard 截断，只保留浮点表示域护栏
   atanh(0.999999)，展示分严格落在 (−99.9999, +99.9999)，减速而永不冻结、
   永不触顶。
护栏不变量（红线第 13 条）：γ≤1 ⇒ 单事件帽与滚动 24h 位移帽在任何高度
仍是上界且只收紧；档位单调挪动判据照旧。零迁移：惰性映射
z=atanh(clamp(score/100,±0.985)) 逐字不动（v7 既有守恒锁原样保持绿，本件
补一条 v8 语境下的守恒复证）。

全部离线：tmp_path 建库 + 注入时钟，不碰 ChatBot_Runtime/，不写源码树 data/。
"""

from __future__ import annotations

import itertools
import json
import math
import sqlite3
import types

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _AFFINITY_BASE,
    _V7_CONFIG_FIELDS,
    _V7_DEFAULT_DAILY_MOVE_CAP_Z,
    _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z,
    _V8_DISPLAY_DOMAIN_BOUND,
    _V8_Z_REPR_DOMAIN,
    DynamicAffinityStore,
    resolve_v7_settings,
    tier_for_affinity,
    v7_display_fraction_to_z,
    v7_z_to_display_fraction,
    v8_marginal_gain,
)

_V7_ENV_KEYS = [name.upper() for name, _default in _V7_CONFIG_FIELDS]
_NEG_CAP = _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z   # 0.10z
_DAILY_CAP = _V7_DEFAULT_DAILY_MOVE_CAP_Z     # 0.12z
_TOL = 1e-9
_HALF_DEFAULT = math.atanh(0.985)             # 缺省 z_hard（γ 半衰减参考点）


class _Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _v8_config(**overrides: object) -> types.SimpleNamespace:
    base = {
        "bot_affinity_v7_enabled": True,
        "bot_affinity_base_step": 0.10,
        "bot_affinity_novelty_ratio": 0.90,
        "bot_affinity_novelty_halo_days": 21,
        "bot_affinity_rhythm_reference_turns": 8,
        "bot_affinity_negative_event_cap_z": 0.10,
        "bot_affinity_daily_move_cap_z": 0.12,
        "bot_affinity_fuse_daily_events": 25,
        "bot_affinity_repair_gain": 1.4,
        "bot_affinity_z_hard_bound": 0.985,
        "bot_affinity_quality_weights": "",
        "bot_affinity_decay_tau_days": "",
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _v8_store(tmp_path, clock: _Clock, name: str = "affinity.sqlite3", **config_over):
    return DynamicAffinityStore(
        tmp_path / name, clock=clock, config=_v8_config(**config_over)
    )


@pytest.fixture(autouse=True)
def _isolate_v8_env(monkeypatch):
    """12 枚在册 env 键一律剥离（与 v7 族同规）：配置面只由本件点名供给。"""
    for key in _V7_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _call_v7_delta(store, sender, *, z=0.0, override=9.9):
    """直调执法体：固定 z、顶格 override，鉴别"当前高度处的实发步进"。"""
    clock_now = float(store._clock())
    with store._lock, store._connect() as connection:
        return store._v7_delta(
            connection, sender, "", "neutral", z,
            v7=resolve_v7_settings(_v8_config()),
            state_json="{}",
            now=clock_now,
            day_index=int(clock_now // 86400),
            text="一句普通的话",
            gap_seconds=None,
            delta_override=override,
            mood_valence=None,
            first_impression=None,
            interaction_count=10,
            day_counters={},
            responded_to_question=None,
            source_event_id="",
        )


# =========================================================================
# A. γ 纯函数形态（边际递减的定义面）
# =========================================================================


def test_gamma_shape_monotone_symmetric_bounded() -> None:
    """γ(0)=1、随 |z| 严格递减、正负对称、恒落 (0,1]、半参考点恰 0.5。"""
    assert v8_marginal_gain(0.0, _HALF_DEFAULT) == pytest.approx(1.0)
    assert v8_marginal_gain(_HALF_DEFAULT, _HALF_DEFAULT) == pytest.approx(0.5)
    previous = 1.0
    for z in (0.1, 0.3, 1.0, 2.0, _HALF_DEFAULT, 4.0, 7.0, 50.0, 1000.0):
        gain = v8_marginal_gain(z, _HALF_DEFAULT)
        assert 0.0 < gain <= 1.0
        assert gain < previous, f"|z|={z} 处 γ 未继续递减"
        assert v8_marginal_gain(-z, _HALF_DEFAULT) == pytest.approx(gain), "正负不对称"
        previous = gain


def test_gamma_sanitizes_dirty_inputs_without_raising() -> None:
    """非有限入参消毒：脏 z 按 0 处理（γ=1）；脏/非正 half ⇒ γ≡1 退化为 v7
    原行为——宁保守不巨变，绝不抛、不产 inf。"""
    assert v8_marginal_gain(float("nan"), _HALF_DEFAULT) == pytest.approx(1.0)
    assert v8_marginal_gain(float("inf"), _HALF_DEFAULT) == pytest.approx(1.0)
    assert v8_marginal_gain(None, _HALF_DEFAULT) == pytest.approx(1.0)
    for bad_half in (0.0, -1.0, None, float("nan"), float("inf")):
        assert v8_marginal_gain(3.0, bad_half) == pytest.approx(1.0)


def test_gamma_reference_follows_registered_config() -> None:
    """half 现读配置面（在册键 bot_affinity_z_hard_bound，非新键）：bound 改
    0.9 ⇒ 参考点=atanh(0.9) 处恰为半额，旧参考点处不再是 0.5。"""
    settings = resolve_v7_settings(_v8_config(bot_affinity_z_hard_bound=0.9))
    assert v8_marginal_gain(settings.z_hard, settings.z_hard) == pytest.approx(0.5)
    assert v8_marginal_gain(_HALF_DEFAULT, settings.z_hard) < 0.5


# =========================================================================
# B. 边际递减的行为面（执法体内、任意高度）
# =========================================================================

_HEIGHTS = (0.0, 0.5, 1.0, 2.0, _HALF_DEFAULT, 3.0, 5.0, 7.0)


def test_single_event_step_diminishes_across_heights(tmp_path) -> None:
    """同一顶格 override 在越来越高的 z 上实发步进严格递减，且恰等于
    帽×γ(z)——「好感越高、每分增益边际越小」的直接读数。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "heights.sqlite3")
    applied_list: list[float] = []
    for index, z in enumerate(_HEIGHTS):
        applied, new_z, _ = _call_v7_delta(store, f"h{index}", z=z, override=9.9)
        expected = _NEG_CAP * v8_marginal_gain(z, _HALF_DEFAULT)
        assert applied == pytest.approx(expected, abs=1e-12), f"z={z} 步进≠帽×γ"
        assert new_z == pytest.approx(z + expected, abs=1e-12)
        assert 0.0 < applied <= _NEG_CAP + _TOL, "γ≤1：单事件上界只收紧不放宽"
        applied_list.append(applied)
    assert all(
        b < a for a, b in itertools.pairwise(applied_list)
    ), "步进序列未随高度递减 ⇒ 边际递减失守"


def test_negative_side_mirrors_positive(tmp_path) -> None:
    """对称面：同一顶格负 override 在 −z 处的实发 = −(正 z 处实发)。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "mirror.sqlite3")
    for index, z in enumerate((0.0, 1.0, _HALF_DEFAULT, 3.0, 5.0)):
        _, pos_applied, _ = _call_v7_delta(store, f"p{index}", z=z, override=9.9)
        _, neg_applied, _ = _call_v7_delta(store, f"n{index}", z=-z, override=-9.9)
        assert neg_applied == pytest.approx(-pos_applied, abs=1e-12), f"z={z} 正负不对称"


def test_two_shots_same_window_still_capped_at_every_height(tmp_path) -> None:
    """红线（禁瞬间剧烈加减）在高处的复证：同一 24h 窗内连打两发顶格
    override，任何起始高度的总位移 ≤ 滚动额度 0.12z 且单发 ≤ 0.10×γ。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "twoshot.sqlite3")
    for index, z in enumerate(_HEIGHTS):
        sender = f"w{index}"
        applied_1, z_mid, _ = _call_v7_delta(store, sender, z=z, override=9.9)
        clock.advance(90)  # 出冷却窗、仍在同一 24h 位移窗
        applied_2, z_end, _ = _call_v7_delta(store, sender, z=z_mid, override=9.9)
        assert applied_1 <= _NEG_CAP * v8_marginal_gain(z, _HALF_DEFAULT) + _TOL
        assert abs(applied_2) <= _NEG_CAP + _TOL
        assert abs(z_end - z) <= _DAILY_CAP + 1e-6, f"z={z} 两发合计越过滚动额度"


# =========================================================================
# C. 长尾（旧界不是冻结界；表示域最终兜底）
# =========================================================================


def test_long_tail_stream_crosses_old_bound_without_freezing(tmp_path) -> None:
    """逐日顶格连打（每发独占 24h 窗 ⇒ 实发=帽×γ 精确读数）：z 一路减速
    爬过旧 ±98.5 界、每发仍严格 >0（永不冻结），展示分单调升、触不到
    0.999999，档号不跳档。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "longtail.sqlite3")
    sender = "deep"
    settings = resolve_v7_settings(_v8_config())
    z_prev = v7_display_fraction_to_z(_AFFINITY_BASE)
    previous_fraction = _AFFINITY_BASE
    previous_applied = _NEG_CAP + 1.0
    crossed = False
    for _ in range(80):
        store.observe(sender, "neutral", text="持续的高质量陪伴的一句", delta_override=9.9)
        fraction = store.snapshot(sender)["affinity"]
        with sqlite3.connect(str(store.db_path)) as connection:
            z_now = float(
                connection.execute(
                    "SELECT z_latent FROM user_affinity WHERE sender_id = ?", (sender,)
                ).fetchone()[0]
            )
        applied = z_now - z_prev
        assert applied == pytest.approx(
            _NEG_CAP * v8_marginal_gain(z_prev, settings.z_hard), abs=1e-9
        ), "每发独占窗时实发应恰为帽×γ(发前高度)"
        assert applied > 0.0, "长尾流中出现零位移 ⇒ 贴界冻结回潮"
        assert applied < previous_applied, "步进未随高度继续减速"
        assert fraction > previous_fraction, "展示分未单调上行"
        assert abs(fraction) < _V8_DISPLAY_DOMAIN_BOUND, "触顶"
        assert abs(z_now) <= _V8_Z_REPR_DOMAIN + _TOL
        assert abs(
            tier_for_affinity(fraction) - tier_for_affinity(previous_fraction)
        ) <= 1, "单发跨了两档 ⇒ 高处的位移不再温和"
        if z_now > settings.z_hard:
            crossed = True
        previous_applied = applied
        previous_fraction = fraction
        z_prev = z_now
        clock.advance(86_400 + 90)  # 每发独占一个 24h 窗
    assert crossed, "80 发仍越不过旧 ±98.5 界 ⇒ 长尾没接上"


def test_repr_domain_is_the_final_guard_not_the_old_bound(tmp_path) -> None:
    """越界脏 z（事故/直改库形态）：最终兜底是表示域 atanh(0.999999)——
    new_z 恰被收回域界，且**展示口径纹丝不动**（tanh 饱和处收界=极小位移），
    旧 ±z_hard 截断已不在场（收回目标 7.25≠2.58）。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "domain.sqlite3")
    for index, z in enumerate((50.0, -50.0, 9.0)):
        _applied, new_z, _ = _call_v7_delta(store, f"d{index}", z=z, override=9.9)
        assert new_z == pytest.approx(
            math.copysign(_V8_Z_REPR_DOMAIN, z if z != 0.0 else 1.0), abs=1e-12
        )
        assert abs(new_z) <= _V8_Z_REPR_DOMAIN + _TOL
        assert abs(new_z) < abs(z), "越界脏 z 未被收回域内"
        display_move = abs(
            v7_z_to_display_fraction(new_z) - v7_z_to_display_fraction(z)
        ) * 100.0
        assert display_move < 0.01, "收界动作在展示口径上放出了瞬间巨变"


# =========================================================================
# D. 零迁移复证（v8 语境）
# =========================================================================


def test_v8_lazy_migration_still_conserves_every_legacy_row(tmp_path) -> None:
    """存量守恒（漏一行即红）：v8 不得改动惰性映射——零分事件写回后，
    |score|≤0.985 的行逐点不动，极端行仍按 v7 在册口径钳到 ±98.5。"""
    clock = _Clock()
    db = tmp_path / "conserve_v8.sqlite3"
    store = _v8_store(tmp_path, clock, "conserve_v8.sqlite3")
    rows = {
        f"u{i}": value
        for i, value in enumerate(
            [-1.0, -0.999, -0.985, -0.5, -0.1, 0.0, 0.1, 0.25, 0.5, 0.9,
             0.984, 0.985, 0.999, 1.0]
        )
    }
    with sqlite3.connect(str(db)) as connection:
        for sender, value in rows.items():
            connection.execute(
                "INSERT OR REPLACE INTO user_affinity"
                " (sender_id, affinity, interaction_count, updated_at)"
                " VALUES (?, ?, 40, '1970-01-01T00:16:40Z')",
                (sender, value),
            )
    for sender in rows:
        store.observe(sender, "refusal", text="")  # 零计分行为：只走写入路径（同 v7 守恒锁口径）
    with sqlite3.connect(str(db)) as connection:
        stored = dict(
            connection.execute("SELECT sender_id, affinity FROM user_affinity").fetchall()
        )
        z_map = dict(
            connection.execute(
                "SELECT sender_id, z_latent FROM user_affinity"
            ).fetchall()
        )
    for sender, original in rows.items():
        expected = max(-0.985, min(0.985, original))
        assert abs(stored[sender] - expected) < 1e-12, f"{sender} 存量被重置/漂移"
        assert z_map[sender] == pytest.approx(math.atanh(expected), abs=1e-12)
    # γ 不引入任何"读即改"：二次零分事件写回必须逐字节幂等。
    for sender in rows:
        store.observe(sender, "neutral", text="")
    with sqlite3.connect(str(db)) as connection:
        again = connection.execute(
            "SELECT sender_id, affinity, z_latent FROM user_affinity"
        ).fetchall()
    for sender, affinity, z_value in again:
        assert abs(affinity - stored[sender]) < 1e-12
        assert z_value == pytest.approx(z_map[sender], abs=1e-12)


def test_v8_state_json_schema_untouched(tmp_path) -> None:
    """零迁移的另一半：v8 不加 state 字段、不动既有键——读回消毒后仍是
    v7 形态（ema/types/day/recent/z 的在册集合），不改任何人。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "schema.sqlite3")
    store.observe("u1", "positive", text="谢谢你陪我聊天")
    with sqlite3.connect(str(store.db_path)) as connection:
        raw = connection.execute(
            "SELECT v7_state FROM user_affinity WHERE sender_id='u1'"
        ).fetchone()[0]
    state = json.loads(str(raw or "{}"))
    assert set(state) <= {"ema", "types", "day", "recent", "z"}, "v8 偷偷扩了 state 面"
