"""好感度 v7「瞬间巨变结构性不可能」机器锁 + 存量映射三态边界（席位 T-AFF-1，需求项 13）。

与既有件的分工（不重复、不覆盖）
--------------------------------
`tests/test_affinity.py` 钉 v4/v5 线性口径，`tests/test_affinity_v7.py` 钉 v7 的
行为级验收（不可触顶 / 单调 / 六场景表 / 八档边界静态网格不跳变）。本件钉的是
**"任何输入序列都造不出瞬间巨变"这一条结构性质本身**，三个角度：

1. **活性位移锁**：单次调用、单个自然日、单类信号日熔断三条上限，逐条从库里
   读回真值断言（不是只测纯函数）。既有件测过 `test_daily_move_cap_z` 一处，
   本件补上它没覆盖的**正向 `delta_override` 与 `observe_points(±100)`**——
   管理员命令与 poke 是今天唯一能送进"权威信号"通道的两个入口。
2. **逐档性派生**：`|Δz| ≤ 0.12` ⇒ 展示位移 ≤ `100·tanh(0.12)` ≈ 11.94 分 < 一档宽
   25 分 ⇒ **档号至多变一档**。"档"的真身 = `_ATTITUDE_TIERS`（八格，档 id
   `-4..+3`），档宽 = `_TIER_WIDTH_DISPLAY`，临界值 `_V7_ONE_TIER_Z_CEILING
   = atanh(_TIER_WIDTH_DISPLAY/100)` 由档宽**派生**，本件不手写任何档位数字。
   这条性质在旧口径里只是注释与散文，今天第一次变成可复跑判据。
3. **随机 fuzz**（seed 见 `_FUZZ_SEED`，固定可复跑）：v7 与 **v5 两条路径各跑一遍**
   ——v7 在生产 `.env` 里从未启用，用户线上看到的是 v5/v6 行为，所以"不许瞬间
   巨变"必须对**当前真正在跑的那条路**也成立，否则本需求项等于没交付。

另钉 (b) 存量映射三态边界：`±100`（atanh 发散点）、`|score|>100`（脏数据）、
`None`/非数/NaN/±inf 三态——**不崩、不产 ±inf、不外抛到入站链路**。本件同时是
这次根修的红样本锁：`affinity` 列一行脏数据旧代码会把 `TypeError` 抛进
`snapshot()`（每轮对话的 prompt 注入面）与 `observe()`（入站链路）。

全部离线：`tmp_path` 建库 + 注入时钟，不碰 `ChatBot_Runtime/`，不写源码树 `data/`。
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import itertools
import json
import math
import random
import re
import sqlite3
import time
import types
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    affinity as _affinity,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _AFFINITY_BASE,
    _ATTITUDE_TIERS,
    _TIER_RED_LINES,
    _TIER_WIDTH_DISPLAY,
    _V7_CONFIG_FIELDS,
    _V7_DEFAULT_DAILY_MOVE_CAP_Z,
    _V7_DEFAULT_FUSE_DAILY_EVENTS,
    _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z,
    _V7_DEFAULT_Z_HARD_BOUND,
    _V7_ONE_TIER_Z_CEILING,
    DynamicAffinityStore,
    V7Settings,
    attitude_for_affinity,
    coerce_affinity_fraction,
    coerce_optional_float,
    linear_transition_for_affinity,
    resolve_v7_settings,
    tier_for_affinity,
    tier_name_for_affinity,
    v7_display_fraction_to_z,
    v7_display_move_for_z_cap,
    v7_max_tier_step_for_z_cap,
    v7_raw_delta_z,
    v7_structural_guard_report,
    v7_z_to_display_fraction,
)

_V7_ENV_KEYS = [name.upper() for name, _default in _V7_CONFIG_FIELDS]
_EPS = 1e-9
# 一档宽的展示分口径（浮点安全余量）：断言"位移 < 一档"时必须留出这个余量，
# 免得哪天把 24.999999 也算成"不超过一档"。
_TIER_SAFETY_MARGIN_DISPLAY = 1.0
# 当日累计位移的判据容差：`_v7_dump_state` 把 `day.s`（当日已用额度）按
# `round(..., 8)` 落盘，每轮读回最多"少记"5e-9，于是可用额度会多出同量级的
# 正向偏置——实测 20 事件/日累积到 ~7e-9。这是序列化舍入，不是护栏漏判：
# 位移真实上界仍是 0.12，而结构主张（跨不过一档 25 分）的余量是 13 分。
# 用 1e-6 而非 1e-9，是为了让这条锁在任何一台机器上都稳定绿。
_DAY_CAP_TOLERANCE = 1e-6


@pytest.fixture(autouse=True)
def _isolate_v7_env(monkeypatch):
    """12 枚 v7 env 键一律剥离：env 回退路径不参与本件（与 test_affinity_v7 同规）。"""
    for key in _V7_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # 点名口是进程级去重，逐例清空才能让"越界必点名"这条判据可复跑。
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.chat_reply.character.affinity._V7_WARNED_KEYS",
        set(),
    )


class _Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _v7_config(**overrides: object) -> types.SimpleNamespace:
    base = {
        "bot_affinity_v7_enabled": True,
        "bot_affinity_base_step": 0.10,
        "bot_affinity_novelty_ratio": 0.90,
        "bot_affinity_novelty_halo_days": 21,
        "bot_affinity_rhythm_reference_turns": 8,
        "bot_affinity_negative_event_cap_z": _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z,
        "bot_affinity_daily_move_cap_z": _V7_DEFAULT_DAILY_MOVE_CAP_Z,
        "bot_affinity_fuse_daily_events": _V7_DEFAULT_FUSE_DAILY_EVENTS,
        "bot_affinity_repair_gain": 1.4,
        "bot_affinity_z_hard_bound": _V7_DEFAULT_Z_HARD_BOUND,
        "bot_affinity_quality_weights": "",
        "bot_affinity_decay_tau_days": "",
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _store(tmp_path, clock: _Clock, name: str, **config_over):
    return DynamicAffinityStore(
        tmp_path / name, clock=clock, config=_v7_config(**config_over)
    )


def _legacy_store(tmp_path, clock: _Clock, name: str):
    return DynamicAffinityStore(
        tmp_path / name, clock=clock, config=_v7_config(bot_affinity_v7_enabled=False)
    )


def _db_of(tmp_path, name: str) -> Path:
    return Path(tmp_path) / name


def _read_row(db: Path, sender_id: str) -> sqlite3.Row:
    with sqlite3.connect(str(db)) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT affinity, z_latent, v7_state FROM user_affinity WHERE sender_id = ?",
            (sender_id,),
        ).fetchone()


def _z_of(db: Path, sender_id: str) -> float:
    """该用户当前的有效 z：无行 = 建档前 = 基数 `tanh⁻¹(0.1)`（与 `_observe` 同口径）。"""
    row = _read_row(db, sender_id)
    if row is None:
        return v7_display_fraction_to_z(_AFFINITY_BASE)
    value = row["z_latent"]
    if value is None:
        return v7_display_fraction_to_z(float(row["affinity"]))
    return float(value)


def _daily_move_sum(db: Path, sender_id: str) -> float:
    """从**记账面**读回当日 v7 位移绝对和（不是从返回值倒推）。"""
    with sqlite3.connect(str(db)) as connection:
        rows = connection.execute(
            "SELECT delta FROM affinity_delta_log WHERE sender_id = ? AND source = 'v7'"
            " ORDER BY applied_at",
            (sender_id,),
        ).fetchall()
    return sum(abs(float(row[0])) for row in rows)


def _day_index(timestamp: float) -> int:
    return int(time.strftime("%Y%m%d", time.localtime(timestamp)))


def _tier_path_is_walking(tiers: list[int]) -> None:
    for previous, current in itertools.pairwise(tiers):
        assert abs(current - previous) <= 1, (
            "档号一次跳了 "
            f"{abs(current - previous)} 档（{previous} → {current}）——需求项 13 的"
            "『8 档温和连续过渡、档号必须逐档』被破坏"
        )


_PRAISE = "谢谢你一直陪着我，今天也想跟你说说话"
_INSULT = "你真差劲，废物闭嘴"
_SHORT_NEUTRALS = [
    "在忙些什么",
    "有点想你了",
    "今天挺累的",
    "外面在下雨",
    "刚吃完饭呀",
    "看到个好东西",
    "这个挺有意思",
    "晚点再聊可以吗",
]


# =========================================================================
# A. 活性位移锁：单次 / 单日 / 熔断窗口（从库里读回真值）
# =========================================================================


def test_single_positive_event_stays_within_daily_cap(tmp_path) -> None:
    clock = _Clock()
    db = _db_of(tmp_path, "single_pos.sqlite3")
    store = _store(tmp_path, clock, "single_pos.sqlite3")
    before_z = _z_of(db, "u1") if _read_row(db, "u1") is not None else v7_display_fraction_to_z(_AFFINITY_BASE)
    store.observe("u1", "positive", text=_PRAISE)
    after_z = _z_of(db, "u1")
    assert math.isfinite(after_z)
    assert abs(after_z - before_z) <= _V7_DEFAULT_DAILY_MOVE_CAP_Z + _DAY_CAP_TOLERANCE
    assert v7_display_move_for_z_cap(abs(after_z - before_z)) < _TIER_WIDTH_DISPLAY


def test_single_negative_event_stays_within_negative_cap(tmp_path) -> None:
    clock = _Clock()
    db = _db_of(tmp_path, "single_neg.sqlite3")
    store = _store(tmp_path, clock, "single_neg.sqlite3")
    # 先把人养到 z>0 再辱骂，否则基数以下没有负向空间可测。
    for text in _SHORT_NEUTRALS[:4]:
        store.observe("u1", "positive", text=text)
        clock.advance(3600)
    before_z = _z_of(db, "u1")
    store.observe("u1", "insult", text=_INSULT)
    after_z = _z_of(db, "u1")
    drop = before_z - after_z
    assert drop > 0.0, "辱骂必须扣分（否则本条锁是空跑）"
    assert drop <= _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z + _DAY_CAP_TOLERANCE
    assert drop <= _V7_DEFAULT_DAILY_MOVE_CAP_Z + _DAY_CAP_TOLERANCE


def test_authority_override_cannot_move_more_than_one_day_budget(tmp_path) -> None:
    """管理员/poke 走的权威通道（delta_override、observe_points）同样受上限约束。

    这是"瞬间巨变"最现实的入口：旧口径只写了"负向单事件上限"，正向 override
    名义上不受那把尺管，实际被日位移上限兜住——本条把这条兜底显式钉死。
    """
    clock = _Clock()
    db = _db_of(tmp_path, "override.sqlite3")
    store = _store(tmp_path, clock, "override.sqlite3")
    base_z = _z_of(db, "u1")
    for huge in (9.0, 1.0, 100.0):
        store.observe("u1", "neutral", text="普通的一句话补充说明", delta_override=huge)
        moved = _z_of(db, "u1") - base_z
        assert abs(moved) <= _V7_DEFAULT_DAILY_MOVE_CAP_Z + _DAY_CAP_TOLERANCE, f"override={huge} 位移 {moved}"
        base_z = _z_of(db, "u1")
        clock.advance(120)
    # 展示分口径：一次 override 也跨不过一档。
    assert abs(tier_for_affinity(_read_row(db, "u1")["affinity"]) - tier_for_affinity(_AFFINITY_BASE)) <= 1


def test_observe_points_full_scale_cannot_jump(tmp_path) -> None:
    clock = _Clock()
    db = _db_of(tmp_path, "points.sqlite3")
    store = _store(tmp_path, clock, "points.sqlite3")
    start_tier = tier_for_affinity(_AFFINITY_BASE)
    for points in (100.0, 100.0, -100.0, 55.0):
        store.observe_points("u1", points, source="affinity_command")
        fraction = float(_read_row(db, "u1")["affinity"])
        assert -1.0 < fraction < 1.0
        assert abs(tier_for_affinity(fraction) - start_tier) <= 1
        start_tier = tier_for_affinity(fraction)
        clock.advance(120)
    assert abs(_z_of(db, "u1")) < v7_display_fraction_to_z(1.0) + _EPS


def test_daily_absolute_cumulative_move_is_bounded_across_behaviors(tmp_path) -> None:
    """一日之内换着花样刷 40 件事，位移绝对和仍不得超过日上限（正负共享同额）。"""
    clock = _Clock()
    db = _db_of(tmp_path, "daily_sum.sqlite3")
    store = _store(tmp_path, clock, "daily_sum.sqlite3")
    start_z = _z_of(db, "u1")
    for index in range(40):
        behavior = ["positive", "insult", "neutral", "tease", "negative"][index % 5]
        store.observe("u1", behavior, text=_PRAISE if index % 2 else _INSULT)
        clock.advance(61)  # > 60s 交互冷却，确保不是靠冷却门挡住的
    assert abs(_daily_move_sum(db, "u1")) <= _V7_DEFAULT_DAILY_MOVE_CAP_Z + _DAY_CAP_TOLERANCE
    assert abs(_z_of(db, "u1") - start_z) <= _V7_DEFAULT_DAILY_MOVE_CAP_Z + _DAY_CAP_TOLERANCE
    assert abs(_daily_move_sum(db, "u1")) > 0.0, "全零位移 ⇒ 本条锁在空跑"


def test_thirty_insults_in_one_day_move_at_most_one_tier(tmp_path) -> None:
    clock = _Clock()
    db = _db_of(tmp_path, "pound.sqlite3")
    store = _store(tmp_path, clock, "pound.sqlite3")
    tiers: list[int] = []
    for _ in range(30):
        store.observe("u1", "insult", text=_INSULT)
        tiers.append(tier_for_affinity(float(_read_row(db, "u1")["affinity"])))
        clock.advance(61)
    _tier_path_is_walking(tiers)
    assert abs(tiers[-1] - tiers[0]) <= 1


def test_fuse_window_stops_scoring_per_behavior_and_resets_next_day(tmp_path) -> None:
    """同类信号日熔断：到达 `fuse_daily_events` 后不计分、不喂新鲜度，次日恢复。"""
    fuse = 3
    clock = _Clock()
    name = "fuse.sqlite3"
    db = _db_of(tmp_path, name)
    store = _store(tmp_path, clock, name, bot_affinity_fuse_daily_events=fuse)
    scored = 0
    for index in range(12):
        before = _z_of(db, "u1")
        store.observe("u1", "neutral", text=_SHORT_NEUTRALS[index % len(_SHORT_NEUTRALS)])
        if abs(_z_of(db, "u1") - before) > 0.0:
            scored += 1
        clock.advance(61)
    assert scored == fuse, f"熔断应只放行 {fuse} 次计分，实放 {scored}"
    state = json.loads(str(_read_row(db, "u1")["v7_state"] or "{}"))
    assert int(state["day"]["c"]["neutral"]) == fuse
    assert float(state["types"]["neutral"][0]) <= fuse + _EPS, "超限事件不得再喂新鲜度计数"
    # 次日恢复：熔断窗口是"每日"，不是一生一次。
    clock.advance(86_400 + 120)
    before = _z_of(db, "u1")
    store.observe("u1", "neutral", text="新的一天的第一句话")
    assert _z_of(db, "u1") != before, "跨日后应恢复计分"


def test_delta_log_abs_sum_matches_latent_movement(tmp_path) -> None:
    """记账面与状态面自证：日志绝对和 == z 的净移动（当日无跨日时）。"""
    clock = _Clock()
    db = _db_of(tmp_path, "ledger.sqlite3")
    store = _store(tmp_path, clock, "ledger.sqlite3")
    start_z = _z_of(db, "u1")
    for index in range(6):
        store.observe("u1", "positive", text=_PRAISE if index % 2 else "有你在真的太好了呢")
        clock.advance(90)
    assert abs(_daily_move_sum(db, "u1") - abs(_z_of(db, "u1") - start_z)) < 1e-12


# =========================================================================
# B. 逐档性：从档宽派生的临界值 + 越界必点名
# =========================================================================


def test_one_tier_ceiling_is_derived_from_tier_width_not_hand_written() -> None:
    assert _TIER_WIDTH_DISPLAY == 25.0, "档宽真身被改：本件的『档』口径需同步复核"
    assert len(_ATTITUDE_TIERS) == 8
    assert abs(_V7_ONE_TIER_Z_CEILING - math.atanh(_TIER_WIDTH_DISPLAY / 100.0)) < 1e-15
    assert v7_max_tier_step_for_z_cap(_V7_DEFAULT_DAILY_MOVE_CAP_Z) == 1
    assert v7_max_tier_step_for_z_cap(_V7_DEFAULT_NEGATIVE_EVENT_CAP_Z) == 1
    assert v7_display_move_for_z_cap(_V7_DEFAULT_DAILY_MOVE_CAP_Z) < (
        _TIER_WIDTH_DISPLAY - _TIER_SAFETY_MARGIN_DISPLAY
    )


def test_structural_guard_report_ok_on_defaults() -> None:
    report = v7_structural_guard_report(V7Settings())
    assert report["ok"] is True
    assert set(report["max_tier_step"]) == {
        "daily_move_cap_z",
        "negative_event_cap_z",
    }
    assert all(step <= 1 for step in report["max_tier_step"].values())


def test_loosened_cap_loses_the_property_and_is_named(tmp_path, caplog) -> None:
    """放宽到能一次跨两档 ⇒ 性质翻转，且必须点名（不静默改值）。"""
    loose = _v7_config(bot_affinity_daily_move_cap_z=0.40)
    report = v7_structural_guard_report(resolve_v7_settings(loose))
    assert report["ok"] is False
    assert report["max_tier_step"]["daily_move_cap_z"] >= 2
    assert v7_max_tier_step_for_z_cap(_V7_ONE_TIER_Z_CEILING) >= 1
    warned = _affinity._V7_WARNED_KEYS  # 点名口是模块活属性，autouse 夹具刚清空过
    with caplog.at_level("WARNING", logger=_affinity.__name__):
        settings = resolve_v7_settings(loose)
    assert "v7_move_cap_beyond_one_tier" in caplog.text
    assert "跳档" in caplog.text
    assert "v7_move_cap_beyond_one_tier" in warned
    # 点名但不越权：值仍是用户给的 0.40，代码没偷偷夹回来。
    assert settings.daily_move_cap_z == pytest.approx(0.40)
    # 第二次调用不再刷第二行日志（进程内每键一次）。
    caplog.clear()
    with caplog.at_level("WARNING", logger=_affinity.__name__):
        resolve_v7_settings(loose)
    assert "跳档" not in caplog.text


def test_default_config_never_trips_the_warning(tmp_path) -> None:
    resolve_v7_settings(_v7_config())
    assert "v7_move_cap_beyond_one_tier" not in _affinity._V7_WARNED_KEYS


def test_any_single_call_moves_less_than_one_tier_display(tmp_path) -> None:
    """穷举式活性扫描：八档每一档起步、五种行为 + 三种 override 各来一发。"""
    clock = _Clock()
    name = "sweep.sqlite3"
    db = _db_of(tmp_path, name)
    store = _store(tmp_path, clock, name)
    starts = [
        -0.95, -0.85, -0.60, -0.35, -0.10, 0.10, 0.35, 0.60, 0.85, 0.95,
    ]
    for sender_index, start in enumerate(starts):
        sender = f"s{sender_index}"
        with sqlite3.connect(str(db)) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO user_affinity"
                " (sender_id, affinity, z_latent, interaction_count, updated_at, created_at)"
                " VALUES (?, ?, ?, 40, ?, ?)",
                (
                    sender,
                    start,
                    v7_display_fraction_to_z(start),
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
            )
        start_tier = tier_for_affinity(start)
        moves: list[float] = []
        for behavior in ("positive", "neutral", "tease", "negative", "insult"):
            before = _z_of(db, sender)
            store.observe(sender, behavior, text=_PRAISE if behavior == "positive" else _INSULT)
            moves.append(abs(_z_of(db, sender) - before))
            clock.advance(61)
        for override in (5.0, -5.0):
            before = _z_of(db, sender)
            store.observe(sender, "neutral", text="一句普通的话", delta_override=override)
            moves.append(abs(_z_of(db, sender) - before))
            clock.advance(61)
        assert max(moves) > 0.0, f"起点 {start} 全零位移 ⇒ 本条在空跑"
        for move in moves:
            assert move <= _V7_DEFAULT_DAILY_MOVE_CAP_Z + _DAY_CAP_TOLERANCE
        assert abs(tier_for_affinity(float(_read_row(db, sender)["affinity"])) - start_tier) <= 1


# =========================================================================
# C. 随机 fuzz：固定 seed，v7 与 v5 两条路都不许跳档
# =========================================================================

_FUZZ_SEED = 20260925
_FUZZ_TRIALS = 6
_FUZZ_EVENTS = 120
_FUZZ_BEHAVIORS = ("positive", "neutral", "tease", "negative", "insult", "refusal", "unknown_kind")
_FUZZ_TEXTS = [
    _PRAISE, _INSULT, "嗯", "？？？", "在忙些什么", "上次你说的那件事我一直记着",
    "对不起，刚才是我不好", "哈哈哈骗你的", "滚开", "请先坐下喝口水，麻烦你了",
    "为什么今天这么安静呢？", "因为其实我也在想同样的事情，就说了出来",
]


def _fuzz_v7(tmp_path, seed: int, label: str) -> None:
    rng = random.Random(seed)
    clock = _Clock(1_700_000_000.0)
    name = f"fuzz_{label}.sqlite3"
    db = _db_of(tmp_path, name)
    store = _store(tmp_path, clock, name)
    z_hard = resolve_v7_settings(_v7_config()).z_hard
    # 档号轨迹与日额度都必须**按人**记：fuzz 交替两个用户，把两人的档号拼进同一条
    # 序列会拿"A 在挚友、B 在友善"这种毫不相干的相邻项去判跳档（本席第一版即如此，
    # 报出过一例假的"2 → 0 跳两档"；诊断脚本按人重放后零命中）。
    tiers: dict[str, list[int]] = {}
    day_of: dict[str, int] = {}
    day_start_z: dict[str, float] = {}
    moved_any = 0
    for _ in range(_FUZZ_EVENTS):
        sender = rng.choice(["u1", "u2"])
        row = _read_row(db, sender)
        z_before = v7_display_fraction_to_z(_AFFINITY_BASE) if row is None else (
            float(row["z_latent"]) if row["z_latent"] is not None
            else v7_display_fraction_to_z(float(row["affinity"]))
        )
        behavior = rng.choice(_FUZZ_BEHAVIORS)
        text = rng.choice(_FUZZ_TEXTS)
        roll = rng.random()
        if roll < 0.08:
            store.observe_points(sender, rng.choice([100.0, -100.0, 42.0, -7.5, 0.0]))
        elif roll < 0.13:
            store.observe(sender, behavior, text=text, delta_override=rng.uniform(-4.0, 4.0))
        else:
            store.observe(
                sender,
                behavior,
                text=text,
                mood_valence=rng.uniform(-1.0, 1.0) if rng.random() < 0.3 else None,
                responded_to_question=rng.choice([True, False, None]),
            )
        after = _read_row(db, sender)
        fraction = float(after["affinity"])
        z_after = after["z_latent"]
        assert z_after is not None, "v7 每次写入都必须落 z_latent"
        z_after = float(z_after)
        assert math.isfinite(z_after) and math.isfinite(fraction), f"非有限值 z={z_after} a={fraction}"
        assert abs(z_after) <= z_hard + _EPS
        assert -1.0 < fraction < 1.0, "tanh 值域：展示值结构上触不到 ±1"
        assert abs(fraction - v7_z_to_display_fraction(z_after)) < 1e-9, "z 与展示值必须互逆"
        assert abs(z_after - z_before) <= _V7_DEFAULT_DAILY_MOVE_CAP_Z + _DAY_CAP_TOLERANCE, "单次位移越界"
        if abs(z_after - z_before) > 0.0:
            moved_any += 1
        current_day = _day_index(clock.now)
        if day_of.get(sender) != current_day:
            day_of[sender] = current_day
            day_start_z[sender] = z_after
        assert abs(z_after - day_start_z[sender]) <= _V7_DEFAULT_DAILY_MOVE_CAP_Z + _DAY_CAP_TOLERANCE, (
            f"{sender} 当日累计位移越界（起点 {day_start_z[sender]:.9f} → {z_after:.9f}）"
        )
        # 结构主张的是"跨不过一档"，容差那一档余量还有 13 分，远宽于上面的浮点噪声。
        assert v7_display_move_for_z_cap(
            abs(z_after - day_start_z[sender])
        ) < _TIER_WIDTH_DISPLAY - _TIER_SAFETY_MARGIN_DISPLAY
        tiers.setdefault(sender, []).append(tier_for_affinity(fraction))
        _tier_path_is_walking(tiers[sender][-2:])
        assert -4 <= tiers[sender][-1] <= 3
        clock.advance(rng.randint(61, 900))
        if rng.random() < 0.06:
            clock.advance(86_400 + rng.randint(0, 600))
    assert moved_any > 0, "整轮零位移 ⇒ fuzz 是空跑"


def test_fuzz_v7_never_skips_a_tier(tmp_path) -> None:
    """seed=_FUZZ_SEED，{_FUZZ_TRIALS}×{_FUZZ_EVENTS} 事件：任意信号序列下逐档而行。"""
    for trial in range(_FUZZ_TRIALS):
        _fuzz_v7(tmp_path, _FUZZ_SEED + trial, f"v7_t{trial}")


def test_fuzz_v5_legacy_path_never_skips_a_tier(tmp_path) -> None:
    """生产今天真正在跑的 v5/v6 路径同样不许瞬间巨变（滚动预算 3 增益/4 损失分）。"""
    rng = random.Random(_FUZZ_SEED)
    clock = _Clock(1_700_000_000.0)
    name = "fuzz_v5.sqlite3"
    db = _db_of(tmp_path, name)
    store = _legacy_store(tmp_path, clock, name)
    tiers: list[int] = []
    moved = 0
    for _ in range(_FUZZ_EVENTS * 2):
        sender = rng.choice(["a1", "a2"])
        before = float(_read_row(db, sender)["affinity"]) if _read_row(db, sender) else _AFFINITY_BASE
        roll = rng.random()
        if roll < 0.1:
            store.observe_points(sender, rng.choice([100.0, -100.0, 30.0]))
        elif roll < 0.16:
            store.observe(sender, "neutral", text=rng.choice(_FUZZ_TEXTS), delta_override=rng.uniform(-3, 3))
        else:
            store.observe(sender, rng.choice(_FUZZ_BEHAVIORS), text=rng.choice(_FUZZ_TEXTS))
        after = float(_read_row(db, sender)["affinity"])
        assert math.isfinite(after) and -1.0 <= after <= 1.0
        assert abs(after - before) <= 0.04 + _EPS, (
            f"v5 单事件位移 {abs(after - before)} 内部值 = {abs(after - before) * 100:.2f} 展示分，"
            "越出滚动预算口径（增益 3 分 / 损失 1 分单事件上限）"
        )
        if after != before:
            moved += 1
        tiers.append(tier_for_affinity(after))
        _tier_path_is_walking(tiers[-2:]) if len(tiers) >= 2 else None
        clock.advance(rng.randint(61, 700))
        if rng.random() < 0.05:
            clock.advance(86_400)
    assert moved > 0, "整轮零位移 ⇒ 本条在空跑"


def test_fuzz_parameters_are_recorded_and_seed_dependent() -> None:
    """seed 与轮数是判据的一部分：换 seed 必须仍全绿，同 seed 必须结果一致。"""
    assert _FUZZ_SEED == 20260925
    assert _FUZZ_TRIALS >= 4 and _FUZZ_EVENTS >= 100
    rng_a = [random.Random(_FUZZ_SEED).random() for _ in range(1)]
    rng_b = [random.Random(_FUZZ_SEED + 1).random() for _ in range(1)]
    assert rng_a != rng_b, "seed 若无效则 fuzz 退化成固定序列，失去覆盖面"


# =========================================================================
# D. 存量惰性映射的三态边界（±100 / |score|>100 / None / 非数 / NaN / ±inf）
# =========================================================================

_DIRTY_SCALARS: tuple[Any, ...] = (None, "", "abc", "1,0", [], {}, float("nan"), float("inf"), float("-inf"))


def test_lazy_mapping_is_total_and_finite_on_dirty_inputs() -> None:
    bound_z = v7_display_fraction_to_z(1.0)
    for raw in _DIRTY_SCALARS:
        z = v7_display_fraction_to_z(raw)
        assert math.isfinite(z), f"脏值 {raw!r} 映射出非有限 z={z}"
        assert abs(z) < bound_z + _EPS
        assert abs(v7_z_to_display_fraction(z)) <= _V7_DEFAULT_Z_HARD_BOUND + _EPS
    # 脏值不得被读成顶格好感（这是"瞬间巨变"最隐蔽的一条路）。
    for raw in _DIRTY_SCALARS:
        assert abs(v7_z_to_display_fraction(v7_display_fraction_to_z(raw))) < 0.5, raw


def test_atanh_divergence_points_are_clamped_not_raised() -> None:
    ceiling_z = math.atanh(_V7_DEFAULT_Z_HARD_BOUND)
    for extreme in (1.0, -1.0, 1.375, -5.0, 100.0, -100.0):
        z = v7_display_fraction_to_z(extreme)
        assert math.isfinite(z)
        assert abs(abs(z) - ceiling_z) < _EPS, extreme
        assert math.copysign(1.0, z) == math.copysign(1.0, extreme)
        assert abs(v7_z_to_display_fraction(z) - math.copysign(_V7_DEFAULT_Z_HARD_BOUND, extreme)) < _EPS


def test_bound_argument_cannot_open_the_domain_hole() -> None:
    """调用方直传 bound≥1 旧形态会 `math.domain error`；现在一律钳进合法域。"""
    for bad_bound in (1.0, 1.5, 1e9, 0.0, -3.0, None, "abc", float("nan")):
        z = v7_display_fraction_to_z(0.5, bad_bound)
        assert math.isfinite(z), f"bound={bad_bound!r} 产出非有限 z"


def test_legal_values_are_conserved_point_by_point() -> None:
    for fraction in (-0.985, -0.9, -0.5, -0.1, 0.0, 0.1, 0.42, 0.75, 0.985):
        assert abs(v7_z_to_display_fraction(v7_display_fraction_to_z(fraction)) - fraction) < 1e-12


def test_coercion_helpers_return_base_not_extremes() -> None:
    for raw in _DIRTY_SCALARS:
        assert coerce_affinity_fraction(raw) == _AFFINITY_BASE, raw
        assert coerce_optional_float(raw) is None or isinstance(coerce_optional_float(raw), float)
    assert coerce_optional_float(None) is None
    assert coerce_affinity_fraction(0.42) == 0.42
    assert coerce_affinity_fraction(1.375) == 1.375, "合法越界值原样透传，由既有钳位处理"


def _corrupt(db: Path, column: str, value: object, sender: str = "u1") -> None:
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            f"UPDATE user_affinity SET {column} = ? WHERE sender_id = ?", (value, sender)
        )


def test_dirty_affinity_column_does_not_escape_into_inbound_chain(tmp_path) -> None:
    """脏 `affinity` 列：`snapshot()`（每轮 prompt 注入）与 `observe()`（入站）都不许抛。

    根修前实况：`float('abc')` → ValueError 直接冒到链路（本席 probe 复现）。
    """
    clock = _Clock()
    name = "dirty_col.sqlite3"
    db = _db_of(tmp_path, name)
    store = _store(tmp_path, clock, name)
    store.observe("u1", "positive", text=_PRAISE)
    for value in ("abc", "", "1,0", float("inf")):
        _corrupt(db, "affinity", value)
        snapshot = store.snapshot("u1")  # 旧形态：ValueError/TypeError
        assert math.isfinite(snapshot["affinity"])
        assert -4 <= snapshot["tier"] <= 3
        assert isinstance(snapshot["attitude"], str) and snapshot["attitude"]
        returned = store.observe("u1", "neutral", text="再来一句普通的话")
        assert math.isfinite(returned) and -1.0 < returned < 1.0
        clock.advance(90)


def test_null_affinity_in_legacy_shaped_table_is_survivable(tmp_path) -> None:
    """老/外部建表的库可能没有 NOT NULL 约束 ⇒ affinity 真的可以是 NULL 或 NaN。

    现网 `_ensure_schema` 用 CREATE TABLE IF NOT EXISTS，故预建的宽松表会被沿用
    （只 ALTER 补列、不加约束），这条用例就是在模拟那种历史形态。
    ⚠ 顺带钉一个 SQLite 事实：REAL 列写入 NaN 会被存成 NULL —— 所以"宽松表"也是
    NaN 唯一能进库的路径，`test_nan_cannot_be_read_as_top_affinity` 靠它。
    """
    db = _db_of(tmp_path, "legacy_shape.sqlite3")
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "CREATE TABLE user_affinity ("
            " sender_id TEXT PRIMARY KEY, affinity REAL, interaction_count INTEGER,"
            " positive_count INTEGER, negative_count INTEGER, tease_count INTEGER,"
            " insult_count INTEGER, nickname TEXT, impression_tags TEXT,"
            " profile_notes TEXT, counter_day_index INTEGER, day_counters TEXT,"
            " updated_at TEXT)"
        )
        connection.execute(
            "INSERT INTO user_affinity (sender_id, affinity, interaction_count, updated_at)"
            " VALUES ('u1', NULL, 5, '2026-01-01T00:00:00Z')"
        )
    clock = _Clock()
    store = DynamicAffinityStore(db, clock=clock, config=_v7_config())
    snapshot = store.snapshot("u1")
    # 脏值回退口径 = 建档基数 `_AFFINITY_BASE`（10 分,档 0 友善），不是 0 分。
    assert math.isfinite(snapshot["affinity"])
    assert snapshot["affinity"] == pytest.approx(_AFFINITY_BASE)
    assert snapshot["tier"] == tier_for_affinity(_AFFINITY_BASE)
    assert isinstance(snapshot["attitude"], str) and "不攻击" in snapshot["attitude"]
    moved = store.observe("u1", "positive", text=_PRAISE)
    assert math.isfinite(moved) and -1.0 < moved < 1.0
    with sqlite3.connect(str(db)) as connection:
        rows = connection.execute("SELECT affinity, z_latent FROM user_affinity").fetchall()
    for affinity, z in rows:
        assert affinity is None or math.isfinite(float(affinity))
        assert z is None or (math.isfinite(float(z)))
    # 宽松表也接得住"没有列的排行榜查询"：leaderboard 走的是 group_affinity，不受影响。
    assert store.leaderboard("g1") == []


def test_infinite_stored_z_does_not_produce_infinite_delta(tmp_path) -> None:
    """z_latent=±inf（SQLite 可存）+ affinity 顶格：旧形态 `new_z - z` 会算出 -inf 写进账。"""
    clock = _Clock()
    name = "dirty_z.sqlite3"
    db = _db_of(tmp_path, name)
    store = _store(tmp_path, clock, name)
    store.observe("u1", "positive", text=_PRAISE)
    for bad_z in (float("inf"), float("-inf"), "nonsense", ""):
        _corrupt(db, "z_latent", bad_z)
        returned = store.observe("u1", "positive", text="有你在真的太好了")
        assert math.isfinite(returned), f"z_latent={bad_z!r} 后返回非有限值"
        with sqlite3.connect(str(db)) as connection:
            deltas = [
                float(row[0])
                for row in connection.execute(
                    "SELECT delta FROM affinity_delta_log WHERE sender_id='u1' AND source='v7'"
                )
            ]
            stored_z = connection.execute(
                "SELECT z_latent FROM user_affinity WHERE sender_id='u1'"
            ).fetchone()[0]
        assert all(math.isfinite(delta) for delta in deltas), f"账里出现非有限位移 {deltas}"
        assert stored_z is None or math.isfinite(float(stored_z))
        clock.advance(90)


def test_nan_cannot_be_read_as_top_affinity(tmp_path) -> None:
    """NaN 经 `min/max` 钳位会静默变成 +bound ⇒「一条脏数据读成 98.5 分」。

    两条来路都要堵：① Python 侧算出来的 NaN 顺流到映射口（现网 `float('nan')`
    与 `min/max` 的组合是静默的，旧代码把它钳成顶格）；② 宽松表里落库即 NULL 的
    行（SQLite 把 REAL 列的 NaN 存成 NULL —— 实测，故 NOT NULL 列物理上进不来）。
    """
    assert v7_z_to_display_fraction(v7_display_fraction_to_z(float("nan"))) == pytest.approx(_AFFINITY_BASE)
    assert coerce_affinity_fraction(float("nan")) == _AFFINITY_BASE
    assert coerce_optional_float(float("nan")) is None
    # ①：顶格读法在根修前是实况（`max(-b, min(b, nan))` 恒等于 +b），注毒即红。
    assert v7_display_fraction_to_z(float("nan")) < v7_display_fraction_to_z(0.9)
    clock = _Clock()
    name = "nan_col.sqlite3"
    db = _db_of(tmp_path, name)
    store = _store(tmp_path, clock, name)
    store.observe("u1", "positive", text=_PRAISE)
    # 现网表形态：affinity 列 NOT NULL ⇒ NaN 落库即 NULL ⇒ 当场被约束拒（这条是前提自证）。
    with pytest.raises(sqlite3.IntegrityError):
        _corrupt(db, "affinity", float("nan"))
    # 宽松表形态：NaN 能以 NULL 进来，读出口不得给出顶格好感。
    loose = _db_of(tmp_path, "nan_loose.sqlite3")
    with sqlite3.connect(str(loose)) as connection:
        connection.execute(
            "CREATE TABLE user_affinity (sender_id TEXT PRIMARY KEY, affinity REAL,"
            " interaction_count INTEGER, positive_count INTEGER, negative_count INTEGER,"
            " tease_count INTEGER, insult_count INTEGER, nickname TEXT, impression_tags TEXT,"
            " profile_notes TEXT, counter_day_index INTEGER, day_counters TEXT, updated_at TEXT)"
        )
        connection.execute(
            "INSERT INTO user_affinity (sender_id, affinity, interaction_count, updated_at)"
            " VALUES ('u1', ?, 3, '2026-01-01T00:00:00Z')",
            (float("nan"),),
        )
    loose_store = DynamicAffinityStore(loose, clock=clock, config=_v7_config())
    snapshot = loose_store.snapshot("u1")
    assert snapshot["affinity"] < 0.5, "NaN/NULL 行不得被读成顶格好感"
    assert math.isfinite(loose_store.observe("u1", "neutral", text="一句普通的话"))


def test_snapshot_and_leaderboard_survive_dirty_group_mirror(tmp_path) -> None:
    clock = _Clock()
    name = "dirty_mirror.sqlite3"
    db = _db_of(tmp_path, name)
    store = _store(tmp_path, clock, name)
    store.observe("u1", "positive", text=_PRAISE, group_id="g1", display_name="小汐")
    with sqlite3.connect(str(db)) as connection:
        connection.execute("UPDATE group_affinity SET affinity = 'oops'")
    board = store.leaderboard("g1")
    assert isinstance(board, list)
    for entry in board:
        assert math.isfinite(float(entry["score"]))


# =========================================================================
# E. 红线与定性口径（AGENTS 规则 8，改测试不改红线）
# =========================================================================

_HOSTILE_PRESCRIPTIONS = (
    "攻击", "辱骂", "贬低", "谴责", "强硬", "敌意", "敌视", "冷暴力", "轻蔑",
    "憎恨", "鄙视", "厌恶", "嘲讽", "羞辱", "反击", "警告", "威胁", "教训",
)
_FIXED_MAGNITUDE_RE = re.compile(r"[加减扣乘增降]\s*\d+(?:\.\d+)?\s*(?:分|点|‰|‰|个单位)|±\s*\d+(?:\.\d+)?\s*分")


def test_no_tier_instruction_prescribes_hostility() -> None:
    """八档指令全文逐档扫：可以"有距离感"，不得"指令式敌意"。红线四条款原样在场。"""
    assert len(_TIER_RED_LINES) == 4
    for tier_id, name, instruction in _ATTITUDE_TIERS:
        for banned in _HOSTILE_PRESCRIPTIONS:
            assert banned not in instruction, f"档 {tier_id}「{name}」指令含 {banned}"
        assert "不攻击" in _TIER_RED_LINES[0] and "不强硬" in _TIER_RED_LINES[0]
    for fraction in (-0.99, -0.5, -0.1, 0.0, 0.1, 0.5, 0.9, 0.99):
        attitude = attitude_for_affinity(fraction)
        transition = linear_transition_for_affinity(fraction)
        assert "不攻击" in attitude and "不辱骂" in attitude and "不冷暴力弃聊" in attitude
        for banned in _HOSTILE_PRESCRIPTIONS:
            assert banned not in transition, f"过渡语含 {banned}（展示分 {fraction}）"


def test_injected_attitude_text_shows_no_fixed_step_numbers() -> None:
    """算法说明只许定性：注入面的八档措辞与过渡语都不得出现"加/扣 N 分"式量级。"""
    for fraction in [i / 100.0 for i in range(-99, 100)]:
        text = attitude_for_affinity(fraction) + linear_transition_for_affinity(fraction)
        assert not _FIXED_MAGNITUDE_RE.search(text), f"展示分 {fraction} 的措辞含固定量级"
    for _tier_id, _name, instruction in _ATTITUDE_TIERS:
        assert not _FIXED_MAGNITUDE_RE.search(instruction)
    assert not _FIXED_MAGNITUDE_RE.search(tier_name_for_affinity(_AFFINITY_BASE))


def test_raw_delta_formula_never_leaks_display_numbers() -> None:
    """纯函数层再钉一遍：更新式在护栏内产出有限 z 位移，且负向被单事件上限咬住。"""
    settings = V7Settings()
    for q in (-1.0, -0.5, -0.05, 0.0, 0.3, 1.0):
        for novelty in (0.02, 0.5, 1.0):
            for rhythm in (0.1, 1.0):
                for mood in (0.85, 1.0, 1.15):
                    for impression in (0.8, 1.0, 1.25):
                        for repair in (False, True):
                            delta = v7_raw_delta_z(
                                q, novelty=novelty, rhythm=rhythm, mood=mood,
                                impression=impression, repair=repair, settings=settings,
                            )
                            assert math.isfinite(delta)
                            if delta < 0:
                                assert delta >= -settings.negative_event_cap_z - _EPS
                            assert abs(delta) <= 1.0


# =========================================================================
# F. 迁移演练脚本（scripts/migrate_affinity_v7_rehearsal.py）
# =========================================================================

_REPO_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _rehearsal():
    path = _REPO_ROOT / "scripts" / "migrate_affinity_v7_rehearsal.py"
    assert path.exists(), f"演练脚本缺席：{path}"
    spec = importlib.util.spec_from_file_location("migrate_affinity_v7_rehearsal", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _store_db_with_extremes(tmp_path, name: str = "rehearsal.sqlite3"):
    clock = _Clock()
    db = _db_of(tmp_path, name)
    store = _store(tmp_path, clock, name)
    for index in range(4):
        store.observe(f"u{index}", "positive", text=_PRAISE if index % 2 else "早上好呀，昨晚睡得好吗")
        clock.advance(3600)
    with sqlite3.connect(str(db)) as connection:
        for sender, value in (
            ("legacy_max", 1.0), ("legacy_min", -1.0), ("over_range", 1.375),
            ("dirty_text", "abc"),
        ):
            connection.execute(
                "INSERT INTO user_affinity (sender_id, affinity, interaction_count, updated_at)"
                " VALUES (?, ?, 9, '2026-01-01T00:00:00Z')",
                (sender, value),
            )
    # 夹具卫生根修（S-T-AFFIN-GUARD，2026-09-25，需求项 13 家族跑期间稳定复现）：
    # DynamicAffinityStore 持有一条常驻 WAL 连接，store 在辅助函数返回后靠 GC 时机
    # 才释放——「最后连接关闭时自动 checkpoint」把 WAL 折回主库的时点不确定：
    # 单跑落进 digest_before 之前（绿），大套件里被前置用例挤到两次 sha256 之间
    # （红）。测的是 rehearsal 不写字节，竞态的却是析构时机（两枚不同老件组合
    # 均可复现且红项不定）。此处显式 checkpoint(TRUNCATE)+关连接，让主库字节
    # 在取 digest 前就静止；三处调用方均只用 db 文件、不回放还的 store，零影响。
    # 断言语义（DRY-RUN 不得写）零改动。
    with store._lock:
        store_connection = store._connect()
        store_connection.commit()
        store_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store_connection.close()
        store._connection = None
    return store, db, clock


def test_rehearsal_refuses_every_runtime_shape(tmp_path) -> None:
    """**指向 ChatBot_Runtime/ 的路径必被拒绝**（本席验收判据点名的一条）。"""
    module = _rehearsal()
    production = _REPO_ROOT.parent / "ChatBot_Runtime" / "data" / "user_affinity.sqlite3"
    assert production.parent.exists(), "前提：本机运行数据区在盘（否则本条退化成空跑）"
    shapes = [
        str(production),
        "../ChatBot_Runtime/data/user_affinity.sqlite3",
        str(production).upper().replace("CHATBOT_RUNTIME", "CHATBOT_RUNTIME"),
        str(tmp_path / "ChatBot_Runtime" / "nested" / "x.sqlite3"),
        str(_REPO_ROOT.parent / "ChatBot_Archive" / "x.sqlite3"),
        str(tmp_path / "chatbot_runtime" / "lower.sqlite3"),
    ]
    for shape in shapes:
        with pytest.raises(module.UnsafeTargetPath):
            module.guard_target_path(shape, repo_root=_REPO_ROOT)
    # 对照面：临时目录必须放行，否则整条演练链跑不起来。
    allowed = tmp_path / "copy.sqlite3"
    allowed.write_bytes(b"not a db yet")
    assert module.guard_target_path(allowed, repo_root=_REPO_ROOT).exists()


def test_rehearsal_cli_refuses_production_with_exit_code_2(tmp_path, capsys) -> None:
    module = _rehearsal()
    production = _REPO_ROOT.parent / "ChatBot_Runtime" / "data" / "user_affinity.sqlite3"
    code = module.main(["--db", str(production)])
    assert code == 2
    out = capsys.readouterr()
    assert "拒绝" in (out.err + out.out)
    assert "DRY-RUN" not in out.out
    before = hashlib.sha256(production.read_bytes()).hexdigest() if production.exists() else None
    after = hashlib.sha256(production.read_bytes()).hexdigest() if production.exists() else None
    assert before == after, "生产库字节变了 —— 拒绝路径没拒住"


def test_rehearsal_dry_run_prints_stats_and_writes_nothing(tmp_path, capsys) -> None:
    module = _rehearsal()
    _store_db_with_extremes(tmp_path)
    db = _db_of(tmp_path, "rehearsal.sqlite3")
    digest_before = hashlib.sha256(db.read_bytes()).hexdigest()
    code = module.main(["--db", str(db)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "DRY-RUN（未写任何字节）" in out
    assert "守恒断言: 通过" in out
    assert "逐点守恒" in out and "域钳位" in out and "脏值" in out
    assert hashlib.sha256(db.read_bytes()).hexdigest() == digest_before, "DRY-RUN  wrote bytes"
    report = module.plan(__import__("sqlite3").connect(str(db)))
    counts = report["counts"]
    assert counts["rows_total"] == 8
    assert counts["domain_clamped"] == 3, "±1 / 1.375 三行应判域钳位"
    assert counts["dirty"] == 1
    assert counts["conserved"] == 4
    assert counts["unexpected_drift"] == 0
    assert counts["z_latent_filled"] == 3, "手工插入的 4 行里 3 行待补，脏值行拒绝补写"
    assert "待人判" in out, "脏值必须点名给人看"


def test_rehearsal_execute_is_idempotent_and_never_touches_scores(tmp_path, capsys) -> None:
    module = _rehearsal()
    _store_db_with_extremes(tmp_path, name="exec.sqlite3")
    db = _db_of(tmp_path, "exec.sqlite3")
    with module.open_read_only(db) as connection:
        fingerprint_before = module.affinity_column_fingerprint(connection)
        plan_before = module.plan(connection)
    code = module.main(["--db", str(db), "--execute"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "EXECUTE（已写副本）" in out
    assert f"本次实际写回行数: {plan_before['counts']['z_latent_filled']}" in out
    with module.open_read_only(db) as connection:
        fingerprint_after = module.affinity_column_fingerprint(connection)
        plan_after = module.plan(connection)
    assert fingerprint_before == fingerprint_after, "affinity 列被改动 = 有人被重置/抬走"
    assert plan_after["counts"]["z_latent_filled"] == 0
    code2 = module.main(["--db", str(db), "--execute"])
    out2 = capsys.readouterr().out
    assert code2 == 0
    assert "本次实际写回行数: 0" in out2, "第二次执行必须零写（幂等）"
    assert "本次实际写回行数: 0" in out2
    # 幂等还要求分类计数逐字段不随重复执行漂移。
    third = module.main(["--db", str(db)])
    out3 = capsys.readouterr().out
    assert third == 0
    for key in ("逐点守恒", "域钳位", "脏值"):
        first_line = next(line for line in out.splitlines() if key in line)
        third_line = next(line for line in out3.splitlines() if key in line)
        assert first_line.split(":")[-1].strip() == third_line.split(":")[-1].strip(), key


def test_rehearsal_read_only_connection_physically_refuses_writes(tmp_path) -> None:
    """DRY-RUN 的"不写"不能只靠约定：连接本身必须写不进。"""
    module = _rehearsal()
    _store_db_with_extremes(tmp_path, name="ro.sqlite3")
    db = _db_of(tmp_path, "ro.sqlite3")
    with module.open_read_only(db) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("UPDATE user_affinity SET affinity = 0.99 WHERE sender_id = 'u0'")
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM user_affinity")


def test_rehearsal_conservation_math_is_exact(tmp_path) -> None:
    module = _rehearsal()
    for fraction in (-0.985, -0.3, 0.0, 0.1, 0.62, 0.985):
        result = module.inspect_row(fraction, None)
        assert result["category"] == "conserved", fraction
        assert result["abs_display_shift"] < 1e-9
        assert result["would_write"] is True
        assert abs(result["derived_z"] - v7_display_fraction_to_z(fraction)) < _EPS
    for fraction in (1.0, -1.0):
        result = module.inspect_row(fraction, None)
        assert result["category"] == "domain_clamped", fraction
        assert result["abs_display_shift"] <= 2.0, "服务口径 ±100 的极端存量最多掉 1.5 分"
        assert result["abs_display_shift"] < _TIER_WIDTH_DISPLAY
    for fraction in (1.375, -1.2, 5.0, -5.0):
        # 越出服务口径（observe_points 先钳 ±100 ⇒ 内部 ±1）的脏行：位移可以更大，
        # 但它同时落在档位面的 clamp 之外 ⇒ 钳前钳后都是同一档，仍跨不了档。
        result = module.inspect_row(fraction, None)
        assert result["category"] == "domain_clamped", fraction
        assert tier_for_affinity(fraction) == tier_for_affinity(result["projected_fraction"]), fraction
    for fraction in (-0.98, -0.985, 0.985, 0.9):
        assert abs(
            module.inspect_row(fraction, None)["projected_fraction"] - fraction
        ) <= _EPS, f"{fraction} 应零位移（贴着域上界也不许被吸走）"
    for dirty in (None, "abc", float("nan"), float("inf")):
        result = module.inspect_row(dirty, None)
        assert result["category"] == "dirty", dirty
        assert result["would_write"] is False, "脏值不得被写回掩盖"
    already = module.inspect_row(0.4, v7_display_fraction_to_z(0.4))
    assert already["z_latent_present"] and not already["z_latent_missing"]
    drifted = module.inspect_row(0.4, 1.23)
    assert drifted["z_latent_drift"] and not drifted["would_write"]


def test_rehearsal_script_does_not_reimplement_the_mapping() -> None:
    """禁第二真身：脚本里不得出现自己的 atanh/tanh 算式，只许调用 affinity 真身。"""
    source = (_REPO_ROOT / "scripts" / "migrate_affinity_v7_rehearsal.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"atanh", "tanh"}:
            raise AssertionError(f"演练脚本自行调用了 {node.attr} —— 映射算式只许住 affinity.py")
        if isinstance(node, ast.Name) and node.id in {"atanh", "tanh"}:
            raise AssertionError("演练脚本出现第二份双曲函数真身")
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("character.affinity")
        for alias in node.names
    }
    assert {"v7_display_fraction_to_z", "v7_z_to_display_fraction", "coerce_affinity_fraction"} <= imported
    assert "import math" not in source, "映射数学一律走真身，脚本不该再引 math"


def test_rehearsal_missing_z_column_plan_is_honest(tmp_path) -> None:
    """没有 z_latent 列的老库：plan 报"待补齐=行数"，但 --execute 前显式拒写结构。"""
    module = _rehearsal()
    db = _db_of(tmp_path, "no_z.sqlite3")
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "CREATE TABLE user_affinity (sender_id TEXT PRIMARY KEY, affinity REAL,"
            " interaction_count INTEGER, updated_at TEXT)"
        )
        connection.execute("INSERT INTO user_affinity VALUES ('u1', 0.3, 3, '2026-01-01T00:00:00Z')")
    with module.open_read_only(db) as connection:
        report = module.plan(connection)
    assert report["has_z_column"] is False
    assert report["counts"]["z_latent_filled"] == 1
    with pytest.raises(SystemExit):
        module.execute_plan(sqlite3.connect(str(db)), report)


def test_rehearsal_missing_table_refuses_without_guessing(tmp_path) -> None:
    module = _rehearsal()
    db = _db_of(tmp_path, "not_affinity.sqlite3")
    with sqlite3.connect(str(db)) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    with pytest.raises(SystemExit):
        module.main(["--db", str(db)])


def test_rehearsal_missing_file_exits_2(tmp_path, capsys) -> None:
    module = _rehearsal()
    assert module.main(["--db", str(tmp_path / "ghost.sqlite3")]) == 2
    assert "拒绝" in (capsys.readouterr().err + capsys.readouterr().out)
