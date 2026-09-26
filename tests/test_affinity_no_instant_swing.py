"""好感度「瞬间巨变结构性不可能」的第二把机器锁 + 活性判据（席位 S-T-AFF-1，需求项 13）。

与既有件的分工（不重复、不覆盖）
--------------------------------
`tests/test_affinity_v7_structural_locks.py`（同席上一段交付）钉的是：单次/单日/
熔断三条上限的读回、逐档性派生、映射三态边界与脏值消毒。本件补它没盖住的四面：

1. **规模到 10^4 量级 + 确定性**：全部事件由 sha256 哈希流生成（本文件不
   ``import random``，``test_this_file_uses_no_random_module`` 自证）；同一 seed
   两次重放曲线逐字节一致（``test_same_seed_same_curve``）。
2. **时间不可作弊**（台账 #6 的坑 + A-1 裁定 2026-09-26 改判）：
   - 时钟**回拨** ⇒ 计分整体冻结（冷却门把「now < 上次落账」的负差也挡下），曲线恒平；
   - 时钟**跨日振荡** ⇒ 单事件上限仍绝对成立（位移额度自 A-1 起为**滚动 24h**，
     振荡与午夜均不再续额——本件如实钉的是任何时钟形态下**单步位移有界、档号不跳**）；
   - **离线补投积压** ⇒ 同一时刻灌几百条只放行头一发、总量 ≤ 滚动额度；
   - **午夜改判锁**：原「日界复位恰好钉在本地午夜（午夜前恒冻结、午夜后恢复）」
     是旧自然日桶语义的既成锁，A-1 裁定后方向翻转为「自然日翻页**不**再续额、
     额度只随 24h 窗滚出恢复」，见 ``test_move_budget_rolls_over_24h_not_local_midnight``
     （旧测试名与回滚点留在该用例注释里，不删锁、只改判）。
3. **活性判据（防假绿）**：不走任何门面，直接调内部写入口
   ``DynamicAffinityStore._v7_delta`` / ``_observe``，并对外部直改的 ``z_latent`` /
   ``affinity`` / ``v7_state`` 脏行做读回断言——护栏在执法体内，不在门面；
   另加一条 AST 扫描：全仓 ``plugins/``+``scripts/`` 里除真身与两台在册演练器外，
   **不存在第二处会写 ``user_affinity`` 分数列的代码路径**。
4. **牙齿自证（差分证据，A-1 后改判为三层）**：只放宽日额度（5.0z）⇒ 单发仍被
   **正向单事件帽**钉在 0.10z（两帽各自独立承重）；两帽同放 ⇒ 位移立刻越过 0.12z
   （并撞硬界、跨多档）⇒ 证明缺省断言非同义反复。"滚动窗形"与"日桶"的差分证据
   在午夜改判用例：把 v7 聚合换回 day["s"] 自然日桶，该用例当场红。

红线零回归：本件只**复跑**不放宽——末段再扫一遍注入文本（任何档位不攻击/不强硬、
算法说明无固定加减数值），既有锁族（test_affinity.py / test_affinity_query.py /
test_affinity_numerical.py）按交卷命令原样保持绿。

全部离线：``tmp_path`` 建库 + 注入时钟，不碰 ``ChatBot_Runtime/``，不写源码树 ``data/``。
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import re
import sqlite3
import time
import types
from functools import lru_cache
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _AFFINITY_BASE,
    _TIER_RED_LINES,
    _TIER_WIDTH_DISPLAY,
    _V7_CONFIG_FIELDS,
    _V7_DEFAULT_DAILY_MOVE_CAP_Z,
    _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z,
    _V7_DEFAULT_Z_HARD_BOUND,
    _V8_DISPLAY_DOMAIN_BOUND,
    _V8_Z_REPR_DOMAIN,
    DynamicAffinityStore,
    attitude_for_affinity,
    linear_transition_for_affinity,
    resolve_v7_settings,
    tier_for_affinity,
    v7_display_fraction_to_z,
    v7_display_move_for_z_cap,
    v7_raw_delta_z,
    v7_z_to_display_fraction,
    v8_marginal_gain,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_V7_ENV_KEYS = [name.upper() for name, _default in _V7_CONFIG_FIELDS]
_CAP_TOL = 1e-6
_DAILY_CAP = _V7_DEFAULT_DAILY_MOVE_CAP_Z       # 0.12z（缺省最坏 11.94 展示分 < 一档宽 25）
_NEG_CAP = _V7_DEFAULT_NEGATIVE_EVENT_CAP_Z     # 0.10z（单事件负向上限）
# v8（2026-09-27「边际递减 + 长尾」）前提重建用的公共量：γ 半衰减参考点（缺省
# z_hard）与其处系数；帽后缩放 ⇒ 基数档处实发 _CAP_AT_BASE、半参考点处半额。
_V8_HALF_DEFAULT = math.atanh(_V7_DEFAULT_Z_HARD_BOUND)
_GAMMA_BASE = v8_marginal_gain(v7_display_fraction_to_z(_AFFINITY_BASE), _V8_HALF_DEFAULT)
_CAP_AT_BASE = _NEG_CAP * _GAMMA_BASE
# 顶格存量读回锁的新域界（v8）：惰性映射仍钳 ±0.985，其后单发 ≤帽×γ(半参考点)
# =0.05z ⇒ 展示上界 tanh(atanh(0.985)+0.05)≈0.9891，判据放宽到 0.995（含余量、
# 仍远收在 0.999999 表示域之内）。
_V8_TAMPER_READBACK_BOUND = 0.995
# v5/v6（生产今日实跑路径）在册预算，展示分口径：单事件增益 ≤3 / 损失 ≤1；
# 滚动窗 24h 增益 ≤3、24h 损失 ≤4、6h 损失 ≤2。内部值 = 分 ÷ 100。
_V5_EVENT_GAIN = 0.03
_V5_EVENT_LOSS = 0.01
_V5_GAIN_24H = 0.03
_V5_LOSS_24H = 0.04
_V5_LOSS_6H = 0.02


@pytest.fixture(autouse=True)
def _isolate_v7_env(monkeypatch):
    """12 枚 v7 env 键一律剥离（与 test_affinity_v7 同规）；点名台账逐例清空。"""
    for key in _V7_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.chat_reply.character.affinity._V7_WARNED_KEYS",
        set(),
    )


# ---------------------------------------------------------------------------
# 基础设施：确定性哈希流 / 时钟 / store / 读回
# ---------------------------------------------------------------------------


class _Det:
    """sha256 链确定性随机流——本仓口径，禁 ``random`` 模块。"""

    def __init__(self, seed: str) -> None:
        self._state = hashlib.sha256(seed.encode("utf-8")).digest()
        self._counter = 0

    def _next(self) -> bytes:
        self._counter += 1
        self._state = hashlib.sha256(self._state + self._counter.to_bytes(8, "big")).digest()
        return self._state

    def unit(self) -> float:
        return int.from_bytes(self._next()[:8], "big") / 2**64

    def randint(self, low: int, high: int) -> int:
        return low + int(self.unit() * (high - low + 1)) % (high - low + 1)

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self.unit()

    def choice(self, seq):
        return seq[int(self.unit() * len(seq)) % len(seq)]


class _Clock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _v7_config(**overrides: object) -> types.SimpleNamespace:
    base: dict[str, object] = {
        "bot_affinity_v7_enabled": True,
        "bot_affinity_base_step": 0.10,
        "bot_affinity_novelty_ratio": 0.90,
        "bot_affinity_novelty_halo_days": 21,
        "bot_affinity_rhythm_reference_turns": 8,
        "bot_affinity_negative_event_cap_z": _NEG_CAP,
        "bot_affinity_daily_move_cap_z": _DAILY_CAP,
        "bot_affinity_fuse_daily_events": 25,
        "bot_affinity_repair_gain": 1.4,
        "bot_affinity_z_hard_bound": _V7_DEFAULT_Z_HARD_BOUND,
        "bot_affinity_quality_weights": "",
        "bot_affinity_decay_tau_days": "",
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _v7_store(tmp_path, name: str, clock: _Clock, **config_over) -> DynamicAffinityStore:
    return DynamicAffinityStore(
        Path(tmp_path) / name, clock=clock, config=_v7_config(**config_over)
    )


def _v5_store(tmp_path, name: str, clock: _Clock) -> DynamicAffinityStore:
    return DynamicAffinityStore(
        Path(tmp_path) / name,
        clock=clock,
        config=_v7_config(bot_affinity_v7_enabled=False),
    )


def _peek(store: DynamicAffinityStore, sender: str):
    """从库里读回真值（不信返回值）——写入口与读回面同锁同连接，确定性。"""
    with store._lock, store._connect() as connection:
        return connection.execute(
            "SELECT affinity, z_latent, v7_state FROM user_affinity WHERE sender_id = ?",
            (sender,),
        ).fetchone()


def _peek_state(store: DynamicAffinityStore, sender: str) -> tuple[float, float]:
    """(展示内部值, 有效 z)。无行 = 建档前 = 基数口径（与 ``_observe`` 一致）。"""
    row = _peek(store, sender)
    if row is None:
        return _AFFINITY_BASE, v7_display_fraction_to_z(_AFFINITY_BASE)
    fraction = float(row["affinity"])
    z = v7_display_fraction_to_z(fraction) if row["z_latent"] is None else float(row["z_latent"])
    return fraction, z


def _day_index(timestamp: float) -> int:
    return int(time.strftime("%Y%m%d", time.localtime(timestamp)))


def _seed_log_row(store: DynamicAffinityStore, sender: str, delta_value, *, offset: float = -90.0) -> None:
    """往唯一额度载体 `affinity_delta_log` 播一行 v7 记账（外部/事故形态）。

    A-1 起滚动 24h 额度的真身就是这张表——本函数是判据的播种面：
    `delta_value` 给字符串（如 "nan"）时按 SQLite 动态类型以 TEXT 落库，
    正是「非有限脏行」的真实事故形态（REAL 亲和列塞不进 NaN/Inf 的数值形态）。
    缺省 offset=-90s：落在 24h 窗内、又出 60s 冷却窗外（只喂额度不碰冷却）。
    """
    clock_now = float(store._clock())
    with store._lock, store._connect() as connection:
        connection.execute(
            "INSERT INTO affinity_delta_log (sender_id, bot_id, applied_at, delta, source)"
            " VALUES (?, '', ?, ?, 'v7')",
            (sender, clock_now + offset, delta_value),
        )


def _window_spent(store: DynamicAffinityStore, sender: str) -> float:
    """测试侧独立复算 24h 窗消耗（SUM 走 SQL、脏值由本侧现算判非有限）。"""
    clock_now = float(store._clock())
    with store._lock, store._connect() as connection:
        total = 0.0
        for (raw,) in connection.execute(
            "SELECT delta FROM affinity_delta_log"
            " WHERE sender_id = ? AND source = 'v7' AND applied_at >= ?",
            (sender, clock_now - 86_400.0),
        ):
            try:
                magnitude = abs(float(raw))
            except (TypeError, ValueError):
                return float("inf")
            if not math.isfinite(magnitude):
                return float("inf")
            total += magnitude
        return total


def _next_local_midnight(ts: float) -> float:
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, 0, 0, 0, 0, 0, -1))


# 事件总量台账：所有驱动经 `_obs`/`_op` 计数，末条测试断言 ≥10^4（需求项 13 规模口径）。
_TALLY: dict[str, int] = {"events": 0}


def _obs(store: DynamicAffinityStore, sender: str, behavior: str, **kwargs) -> float:
    _TALLY["events"] += 1
    return store.observe(sender, behavior, **kwargs)


def _op(store: DynamicAffinityStore, sender: str, points: float, **kwargs) -> float:
    _TALLY["events"] += 1
    return store.observe_points(sender, points, **kwargs)


def _no_tier_skip(who: str, prev: int, cur: int) -> None:
    assert abs(cur - prev) <= 1, (
        f"{who} 档号一次跨了 {abs(cur - prev)} 档（{prev} → {cur}）——"
        "需求项 13『逐档而行、禁止瞬间巨变』被破坏"
    )


# 事件文本池：长 praise / 复读短答 / 追问 / 引用前文 / 道歉修复 / 辱骂 / 戏弄
# ——把新鲜度、复读归零、修复通道、fuse 都喂到。
_TEXTS = [
    "谢谢你一直陪着我，今天也想跟你说说话",
    "有你在真的太好了呢",
    "上次你说的那件事我一直记着",
    "为什么今天这么安静呢？",
    "因为其实我也在想同样的事情，就说了出来",
    "在忙些什么",
    "今天挺累的",
    "外面在下雨",
    "嗯",
    "？？？",
    "滚开",
    "烦死了，别烦我",
    "对不起，刚才是我不好",
    "别生气啦，我们拉钩",
    "哈哈哈骗你的",
    "请先坐下喝口水，麻烦你了",
]
_INSULT = "你真差劲，废物闭嘴"
_PRAISE = "谢谢你一直陪着我，今天也想跟你说说话"
_REPAIR = "对不起，刚才是我不好"
_BEHAVIORS = (
    ["positive"] * 4 + ["neutral"] * 6 + ["tease"] * 2
    + ["negative"] * 4 + ["insult"] * 4 + ["refusal"] + ["mystery_kind"]
)


# ---------------------------------------------------------------------------
# 0. 自证：本件不用 random；哈希流 seed 敏感且稳定
# ---------------------------------------------------------------------------


def test_this_file_uses_no_random_module() -> None:
    """AST 级自证：本文件的 import 面里没有 ``random``（散文提及不算引入）。"""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "random" not in imported, "本席口径=确定性 hash，random 模块禁入"


def test_det_stream_is_seed_dependent_and_stable() -> None:
    assert _Det("t-1").unit() != _Det("t-2").unit(), "seed 无效 ⇒ fuzz 退化成同一序列"
    assert _Det("t-1").unit() == _Det("t-1").unit(), "同 seed 必须同流"


# ---------------------------------------------------------------------------
# A. 10^4 量级确定性 fuzz（v7 与 v5 两条路径）
# ---------------------------------------------------------------------------


def _fuzz_v7(tmp_path, name: str, seed_tag: str, events: int) -> list[str]:
    """v7 大 fuzz：任意信号序列 × 跨日 × 权威 override × 同刻并发 ⇒ 逐条护栏。"""
    det = _Det(f"v7fuzz::{seed_tag}")
    clock = _Clock(1_700_000_000.0)
    store = _v7_store(tmp_path, name, clock)
    senders = ["fx1", "fx2", "fx3"]
    prev: dict[str, tuple[float, float]] = {}
    day_sums: dict[tuple[str, int], float] = {}
    curve: list[str] = []
    moved = 0
    for index in range(events):
        sender = det.choice(senders)
        fraction_before, z_before = prev.get(
            sender, (_AFFINITY_BASE, v7_display_fraction_to_z(_AFFINITY_BASE))
        )
        tier_before = tier_for_affinity(fraction_before)
        behavior = det.choice(_BEHAVIORS)
        text = det.choice(_TEXTS)
        roll = det.unit()
        if roll < 0.05:
            _op(store, sender, det.choice([100.0, -100.0, 60.0, -60.0, 5.0, -5.0, 0.0]))
        elif roll < 0.09:
            _obs(store, sender, behavior, text=text, delta_override=det.uniform(-2.0, 2.0))
        else:
            mood = det.uniform(-1.0, 1.0) if det.unit() < 0.3 else None
            _obs(
                store, sender, behavior,
                text=text,
                mood_valence=mood,
                responded_to_question=det.choice([True, False, None]),
            )
        fraction_after, z_after = _peek_state(store, sender)
        # —— 表示层：结构上永不触顶、z 与展示值互逆、恒有限 ——
        # v8 长尾改判：截断界从 ±z_hard 换成表示域护栏 atanh(0.999999)（=0.999999
        # 展示域）——"不可触顶"主张不变，界按新前提重建，不删锁。
        assert math.isfinite(z_after) and math.isfinite(fraction_after)
        assert abs(z_after) <= _V8_Z_REPR_DOMAIN + 1e-9, f"z 越过表示域界：{z_after}"
        assert abs(fraction_after) <= _V8_DISPLAY_DOMAIN_BOUND + 1e-9, "展示值触到 ±100 域"
        assert -1.0 < fraction_after < 1.0, "tanh 值域：结构上触不到 ±1"
        assert abs(fraction_after - v7_z_to_display_fraction(z_after)) < 1e-9, "z/展示值失互逆"
        # —— 单事件位移：|Δz| ≤ 日上限（正负同尺；override 走同一执法体）——
        dz = z_after - z_before
        assert abs(dz) <= _DAILY_CAP + _CAP_TOL, f"单事件位移越界：Δz={dz}"
        disp = abs(fraction_after - fraction_before) * 100.0
        assert disp <= v7_display_move_for_z_cap(_DAILY_CAP) + 1e-3, f"单事件展示位移 {disp:.3f} 分"
        # —— 档位：相邻快照至多挪一档 ——
        tier_after = tier_for_affinity(fraction_after)
        _no_tier_skip(f"{sender}@#{index}", tier_before, tier_after)
        # —— 单自然人·自然日位移绝对和 ≤ 日上限 ——
        key = (sender, _day_index(clock.now))
        day_sums[key] = day_sums.get(key, 0.0) + abs(dz)
        assert day_sums[key] <= _DAILY_CAP + 1e-6, f"{key} 当日累计位移 {day_sums[key]}"
        if abs(dz) > 0.0:
            moved += 1
        prev[sender] = (fraction_after, z_after)
        curve.append(f"{index}|{sender}|{behavior}|{fraction_after!r}|{z_after!r}")
        # 时钟推进：常规 61..601s；偶发跨日；偶发同刻连发（离线补投形态进 fuzz）。
        step_roll = det.unit()
        if step_roll < 0.01:
            clock.advance(0.0)
        elif step_roll < 0.045:
            clock.advance(86_400 + det.randint(0, 1800))
        else:
            clock.advance(det.randint(61, 601))
    assert moved > 0, "整轮零位移 ⇒ fuzz 在空跑"
    assert len(day_sums) >= 2, "没有跨日覆盖 ⇒ 日桶判据空跑"
    return curve


def test_fuzz_v7_ten_thousand_scale_no_instant_swing(tmp_path) -> None:
    _fuzz_v7(tmp_path, "fuzz_v7_main.sqlite3", "main-20260926", 5_000)


def test_fuzz_v7_worst_mix_two_users_interleaved(tmp_path) -> None:
    """最坏组合加权：连环负向 + 顶格权威正负信号 + 修复连发 + 同刻成串——同一套判据全绿。"""
    det = _Det("v7fuzz::worst-20260926")
    clock = _Clock(1_700_001_234.0)
    store = _v7_store(tmp_path, "fuzz_v7_worst.sqlite3", clock)
    prev: dict[str, tuple[float, float]] = {}
    day_sums: dict[tuple[str, int], float] = {}
    for _ in range(2_500):
        sender = det.choice(["w1", "w2"])
        fraction_before, z_before = prev.get(
            sender, (_AFFINITY_BASE, v7_display_fraction_to_z(_AFFINITY_BASE))
        )
        tier_before = tier_for_affinity(fraction_before)
        roll = det.unit()
        if roll < 0.30:      # 连环辱骂夹带权威负信号
            _obs(store, sender, "insult", text=_INSULT, delta_override=det.uniform(-4.0, -0.5))
        elif roll < 0.45:    # 顶格正权威信号（管理员/事件服务口径）
            _op(store, sender, det.choice([100.0, 100.0, -100.0]))
        elif roll < 0.70:    # 修复通道连发
            _obs(store, sender, "neutral", text=_REPAIR)
        else:                # 正常混合
            _obs(store, sender, det.choice(_BEHAVIORS), text=det.choice(_TEXTS))
        fraction_after, z_after = _peek_state(store, sender)
        dz = z_after - z_before
        assert abs(dz) <= _DAILY_CAP + _CAP_TOL
        # v8 长尾改判：表示域护栏（同上，"不可触顶"主张不变、界按新前提重建）。
        assert abs(z_after) <= _V8_Z_REPR_DOMAIN + 1e-9
        assert abs(fraction_after) <= _V8_DISPLAY_DOMAIN_BOUND + 1e-9
        _no_tier_skip(f"{sender}-worst", tier_before, tier_for_affinity(fraction_after))
        key = (sender, _day_index(clock.now))
        day_sums[key] = day_sums.get(key, 0.0) + abs(dz)
        assert day_sums[key] <= _DAILY_CAP + 1e-6
        prev[sender] = (fraction_after, z_after)
        if det.unit() < 0.12:
            clock.advance(0.0)  # 同刻成串
        elif det.unit() < 0.05:
            clock.advance(86_400 + det.randint(0, 900))
        else:
            clock.advance(det.randint(61, 420))
    assert any(v > 0.0 for v in day_sums.values()), "worst-mix 全零位移 ⇒ 空跑"


def _fuzz_v5(tmp_path, name: str, seed_tag: str, events: int) -> None:
    """v5/v6（生产今日实跑路径）：滚动预算 = 瞬间巨变的既有唯一防线，逐窗钉死。"""
    det = _Det(f"v5fuzz::{seed_tag}")
    clock = _Clock(1_700_000_000.0)
    store = _v5_store(tmp_path, name, clock)
    senders = ["fv1", "fv2"]
    prev_fraction: dict[str, float] = {}
    prev_tier: dict[str, int] = {}
    history: dict[str, list[tuple[float, float]]] = {s: [] for s in senders}
    moved = 0
    for index in range(events):
        sender = det.choice(senders)
        before = prev_fraction.get(sender, _AFFINITY_BASE)
        tier_before = prev_tier.get(sender, tier_for_affinity(_AFFINITY_BASE))
        roll = det.unit()
        if roll < 0.06:
            _op(store, sender, det.choice([100.0, -100.0, 30.0, -30.0, 1.0, -1.0]))
        elif roll < 0.11:
            _obs(store, sender, det.choice(_BEHAVIORS), text=det.choice(_TEXTS),
                 delta_override=det.uniform(-3.0, 3.0))
        else:
            _obs(store, sender, det.choice(_BEHAVIORS), text=det.choice(_TEXTS))
        after = float(_peek(store, sender)["affinity"])
        delta = after - before
        assert math.isfinite(after) and -1.0 <= after <= 1.0
        # 单事件：增益 ≤3 分、损失 ≤1 分（V2.1 §2.3 预算口径）
        assert delta <= _V5_EVENT_GAIN + 1e-6, f"v5 单事件增益 {delta * 100:.2f} 分"
        assert delta >= -_V5_EVENT_LOSS - 1e-6, f"v5 单事件损失 {delta * 100:.2f} 分"
        _no_tier_skip(f"{sender}@v5#{index}", tier_before, tier_for_affinity(after))
        assert abs(after) < 0.995, "v5 路径也不许把展示分推到 ±100 附近"
        hist = [(t, d) for t, d in history[sender] if t > clock.now - 86_400.0]
        hist.append((clock.now, delta))
        history[sender] = hist
        gain_24h = sum(d for _, d in hist if d > 0.0)
        loss_24h = sum(-d for _, d in hist if d < 0.0)
        loss_6h = sum(-d for t, d in hist if d < 0.0 and t > clock.now - 6 * 3600.0)
        assert gain_24h <= _V5_GAIN_24H + 1e-6, f"24h 增益 {gain_24h * 100:.3f} 分 > 3 分"
        assert loss_24h <= _V5_LOSS_24H + 1e-6, f"24h 损失 {loss_24h * 100:.3f} 分 > 4 分"
        assert loss_6h <= _V5_LOSS_6H + 1e-6, f"6h 损失 {loss_6h * 100:.3f} 分 > 2 分"
        if delta != 0.0:
            moved += 1
        prev_fraction[sender] = after
        prev_tier[sender] = tier_for_affinity(after)
        step_roll = det.unit()
        if step_roll < 0.012:
            clock.advance(0.0)
        elif step_roll < 0.05:
            clock.advance(86_400 + det.randint(0, 1200))
        else:
            clock.advance(det.randint(61, 900))
    assert moved > 0, "v5 fuzz 整轮零位移 ⇒ 空跑"


def test_fuzz_v5_legacy_path_same_bounds(tmp_path) -> None:
    """她线上看到的是 v5/v6 ——「禁瞬间巨变」必须对今天真正在跑的路径同样成立。"""
    _fuzz_v5(tmp_path, "fuzz_v5.sqlite3", "prod-20260926", 3_000)


def test_same_seed_same_curve(tmp_path) -> None:
    """确定性：同 seed 两次重放 ⇒ 逐事件曲线（展示值与 z 的 repr）逐字节一致。"""
    curve_a = _fuzz_v7(tmp_path, "det_a.sqlite3", "det", 300)
    curve_b = _fuzz_v7(tmp_path, "det_b.sqlite3", "det", 300)
    assert curve_a == curve_b, "同输入不同曲线 ⇒ 存在隐藏的非确定源"


# ---------------------------------------------------------------------------
# B. 最坏固定序列：连续辱骂 / 熔断边界 / 修复通道 / 幂等重放
# ---------------------------------------------------------------------------


def test_worst_case_insult_bombardment_across_days(tmp_path) -> None:
    """连续辱骂 ×3 天（贴 60s 冷却间隔发）：每天恰好吃满负向额度，逐档下行、绝不触底。"""
    clock = _Clock()
    store = _v7_store(tmp_path, "pound.sqlite3", clock)
    tiers: list[int] = []
    fractions: list[float] = []
    day_sums: dict[int, float] = {}
    _, z_prev = _peek_state(store, "u1")
    tier_prev = tier_for_affinity(_AFFINITY_BASE)
    for index in range(183):  # 3 天 × 61 发
        _obs(store, "u1", "insult", text=_INSULT)
        fraction, z = _peek_state(store, "u1")
        dz = abs(z - z_prev)
        assert dz <= _NEG_CAP + _CAP_TOL, f"负向单事件 {dz} 越 0.10z"
        key = _day_index(clock.now)
        day_sums[key] = day_sums.get(key, 0.0) + dz
        assert day_sums[key] <= _DAILY_CAP + 1e-6, f"{key} 日累计 {day_sums[key]}"
        tier_now = tier_for_affinity(fraction)
        _no_tier_skip(f"pound#{index}", tier_prev, tier_now)
        z_prev, tier_prev = z, tier_now
        fractions.append(fraction)
        tiers.append(tier_now)
        assert abs(fraction) < 0.995, "连打 3 天也不许贴到谷值"
        clock.advance(61)
    assert tiers[0] >= tiers[-1]
    assert tiers[0] - tiers[-1] <= 3, "3 天最多挪 3 档（每天至多一档）"
    assert fractions[0] - fractions[-1] > 0.02, "全零位移 ⇒ 空跑"


def test_worst_case_fuse_25_takes_over_independently_of_daily_cap(tmp_path) -> None:
    """熔断边界：neutral 无 v5 兜底帽、单发位移极小 ⇒ 日额度**没**耗尽时，
    25 枚/日·类的熔断必须精确接管——证明它是独立护栏，不是日额度的影子。"""
    clock = _Clock(_next_local_midnight(1_000_000_000.0) + 3600.0)  # 当日起算，45 发不跨本地午夜
    store = _v7_store(tmp_path, "fuse_boundary.sqlite3", clock)
    texts = [f"闲聊句{i}呢" for i in range(45)]
    _, z_start = _peek_state(store, "u1")
    for text in texts:
        _obs(store, "u1", "neutral", text=text)
        clock.advance(61)
    _, z_end = _peek_state(store, "u1")
    state = json.loads(str(_peek(store, "u1")["v7_state"] or "{}"))
    assert int(state["day"]["c"].get("neutral", 0)) == 25, "熔断没有在 25 枚精确接管"
    assert 24.9 < float(state["types"]["neutral"][0]) <= 25.0, (
        "超限事件不得再喂新鲜度计数（计数跨 61s 有 seasonal τ=21d 的微量衰减，取带容差）"
    )
    total = abs(z_end - z_start)
    assert 0.0 < total < _DAILY_CAP - 0.05, (
        f"日累计位移 {total}：本用例要求日额度**未**耗尽而熔断独立收口"
    )


def test_worst_case_repair_channel_bounded(tmp_path) -> None:
    """修复通道：×1.4 加成后单事件仍被日额度咬住；且不喂新鲜度计数。"""
    clock = _Clock()
    store = _v7_store(tmp_path, "repair.sqlite3", clock)
    _obs(store, "u1", "neutral", text="在忙些什么")
    clock.advance(61)
    _obs(store, "u1", "neutral", text="今天挺累的")
    clock.advance(61)
    state = json.loads(str(_peek(store, "u1")["v7_state"] or "{}"))
    count_before = float(state["types"]["neutral"][0])
    assert 1.99 < count_before <= 2.0, "前提自证：计分事件喂了新鲜度计数（含跨 61s 的微量衰减）"
    moved_days = 0
    for index in range(6):
        _, z_prev = _peek_state(store, "u1")
        _obs(store, "u1", "neutral", text=f"{_REPAIR} 第{index}遍")
        _, z_after = _peek_state(store, "u1")
        assert 0.0 < z_after - z_prev <= _DAILY_CAP + _CAP_TOL, (
            f"修复单事件位移 {z_after - z_prev} 越界或恒零"
        )
        moved_days += 1
        clock.advance(86_400)  # 每天一句道歉：repair 不吃同类配额，每天都该动一点
    assert moved_days == 6
    state2 = json.loads(str(_peek(store, "u1")["v7_state"] or "{}"))
    count_after = float(state2["types"]["neutral"][0])
    # 修复只续时不喂数：计数只随 τ=21d 半衰微降（6 日 ≈ -0.17），绝不出现 +1/发的抬升。
    assert count_after < count_before, "修复事件喂了新鲜度计数（计数不降反升）"
    assert count_after > count_before - 0.5, f"计数跌出半衰解释域：{count_before} → {count_after}"


def test_authority_replay_is_idempotent(tmp_path) -> None:
    """同 source_event_id 重放（补偿/重投递形态）：零二次位移、零二次落账。"""
    clock = _Clock()
    store = _v7_store(tmp_path, "replay.sqlite3", clock)
    first = store.observe(
        "u1", "neutral", text="一条来自事件服务的权威信号",
        delta_override=0.05, source_event_id="evt-42",
    )
    _TALLY["events"] += 1
    clock.advance(90)
    second = store.observe(
        "u1", "neutral", text="同一条又被重放了一次",
        delta_override=9.9, source_event_id="evt-42",  # 重放体甚至带着更猛的额度
    )
    _TALLY["events"] += 1
    assert first == second
    with store._lock, store._connect() as connection:
        (count,) = connection.execute(
            "SELECT COUNT(*) FROM affinity_delta_log WHERE source_event_id = 'evt-42'"
        ).fetchone()
    assert int(count) == 1, "重放不得二次落账"


# ---------------------------------------------------------------------------
# C. 时间不可作弊
# ---------------------------------------------------------------------------


def test_clock_rewind_freezes_all_scoring(tmp_path) -> None:
    """时钟回拨：冷却门把负差也挡下 ⇒ 曲线恒平；回到正常时间后恢复护栏内计分。"""
    clock = _Clock(1_800_000_000.0)
    store = _v7_store(tmp_path, "rewind.sqlite3", clock)
    _obs(store, "u1", "positive", text=_PRAISE, delta_override=0.05)
    _, z_locked = _peek_state(store, "u1")
    rewound = clock.now - 3 * 3600.0
    for index in range(30):
        clock.now = rewound + index  # 深度回拨区内逐条灌
        _obs(store, "u1", "insult", text=_INSULT, delta_override=-1.0)
        _obs(store, "u1", "positive", text=_PRAISE, delta_override=1.0)
        _, z_now = _peek_state(store, "u1")
        assert z_now == z_locked, "回拨期间出现了位移 ⇒ 冷却门没挡住负差"
    clock.now = 1_800_000_000.0 + 120.0  # 回到最后落账时刻 +60s 之后
    _, z_before_resume = _peek_state(store, "u1")
    _obs(store, "u1", "positive", text="回到正轨后的一句好话")
    _, z_after_resume = _peek_state(store, "u1")
    assert 0.0 <= z_after_resume - z_before_resume <= _DAILY_CAP + _CAP_TOL
    # 回拨冻结不是永久拉黑：滚动 24h 额度未耗尽时恢复后必须重新能动
    # （A-1 后额度载体是 delta_log，不再读 state 的旧日桶字段）。
    window_spent = _window_spent(store, "u1")
    if window_spent < _DAILY_CAP - 1e-6:
        assert z_after_resume != z_before_resume, "解冻后仍恒零 ⇒ 回拨把计分永久打死"


def test_clock_oscillation_keeps_per_event_cap(tmp_path) -> None:
    """跨日振荡：回拨段恒平；每个前进段单事件 ≤ 上界、逐档而行。
    如实口径（A-1 改判后）：位移额度是**滚动 24h**，振荡/午夜都不再续额——
    本锁钉的是**任何时钟形态下单步位移有界、档号不跳、永不触顶**。"""
    t0 = 1_800_005_000.0
    midnight = _next_local_midnight(t0)
    clock = _Clock(t0)
    store = _v7_store(tmp_path, "oscillate.sqlite3", clock)
    _obs(store, "u1", "neutral", text=_PRAISE, delta_override=0.12)  # 正向帽先咬：≤0.10z 再乘 γ（v8）
    fraction, z_prev = _peek_state(store, "u1")
    tier_prev = tier_for_affinity(fraction)
    for cycle in range(6):
        clock.now = midnight + 90.0 + cycle * 90.0       # 次日前进段
        _obs(store, "u1", "insult", text=_INSULT, delta_override=-2.0)
        fraction, z = _peek_state(store, "u1")
        assert abs(z - z_prev) <= _DAILY_CAP + _CAP_TOL, f"cycle {cycle} 单事件越界"
        assert abs(fraction) <= _V8_DISPLAY_DOMAIN_BOUND + 1e-9  # v8 域界（改判重建）
        _no_tier_skip(f"oscillate#{cycle}", tier_prev, tier_for_affinity(fraction))
        z_prev, tier_prev = z, tier_for_affinity(fraction)
        clock.now = midnight - 3600.0                     # 回拨进前一日
        for probe in range(8):
            _obs(store, "u1", "positive", text=_PRAISE, delta_override=2.0)
            _, z_back = _peek_state(store, "u1")
            assert z_back == z, "回拨段出现位移 ⇒ 单事件界随时间操纵失守"
    assert abs(z_prev) <= _V8_Z_REPR_DOMAIN + 1e-9  # v8 表示域护栏（改判重建）


def test_offline_backlog_same_instant_moves_at_most_one_event(tmp_path) -> None:
    """离线补投积压（同一时刻灌入）：冷却门只放行头一发；日总量 ≤ 日额度。"""
    for tag in ("pos", "neg"):
        clock = _Clock(1_800_010_000.0)
        store = _v7_store(tmp_path, f"backlog_{tag}.sqlite3", clock)
        _, z_start = _peek_state(store, "u1")
        scored = 0
        z_prev_evt = z_start
        for index in range(250):
            behavior = "positive" if tag == "pos" else "insult"
            base_text = _PRAISE if tag == "pos" else _INSULT
            _obs(store, "u1", behavior, text=f"{base_text} #{index}")  # 不同文本，门都放行
            _, z_now = _peek_state(store, "u1")
            assert abs(z_now - z_start) <= _DAILY_CAP + 1e-6
            assert abs(float(_peek(store, "u1")["affinity"])) <= _V8_DISPLAY_DOMAIN_BOUND + 1e-9  # v8 域界
            if z_now != z_prev_evt:
                scored += 1  # 逐事件比较：同刻连发下应只有头一发改变 z
            z_prev_evt = z_now
        assert scored == 1, f"{tag} 同刻 250 发竟有 {scored} 发在冷却窗外改动了 z"
    # 补投按 61s 拉开重放（重放器带节奏形态）：每个日历日的总位移仍 ≤ 额度。
    # A-1 后这是**派生结论**而非判据本体：单日全部事件必落在某个 24h 窗内
    # （窗约束蕴含单日约束）；旧口径「日额度按本地日精确复位、跨日续额」已作废。
    clock = _Clock(1_800_020_000.0)
    store = _v7_store(tmp_path, "backlog_spaced.sqlite3", clock)
    _, z_prev_evt = _peek_state(store, "u1")
    day_sums: dict[int, float] = {}
    for index in range(300):
        _obs(store, "u1", "positive", text=f"补投第{index}句谢谢你陪着我")
        _, z_now = _peek_state(store, "u1")
        dz = abs(z_now - z_prev_evt)
        assert dz <= _DAILY_CAP + _CAP_TOL, f"补投第 {index} 发单事件位移 {dz}"
        key = _day_index(clock.now)
        day_sums[key] = day_sums.get(key, 0.0) + dz
        assert day_sums[key] <= _DAILY_CAP + 1e-6, f"{key} 日累计 {day_sums[key]} 越界"
        z_prev_evt = z_now
        clock.advance(61)
    assert len(day_sums) >= 1 and sum(day_sums.values()) <= _DAILY_CAP * len(day_sums) + 1e-6


def test_v5_backlog_and_rewind_same_gates(tmp_path) -> None:
    """v5 路径同判据：同刻 300 发只放行头一发（≤1 分损失帽），回拨段恒平。"""
    clock = _Clock(1_800_030_000.0)
    store = _v5_store(tmp_path, "v5_backlog.sqlite3", clock)
    start = _AFFINITY_BASE if _peek(store, "u1") is None else float(_peek(store, "u1")["affinity"])
    for index in range(300):
        _obs(store, "u1", "insult", text=f"滚开 {index}")
    now_fraction = float(_peek(store, "u1")["affinity"])
    assert start - now_fraction <= _V5_EVENT_LOSS + 1e-6, "同刻连发挪动超过单事件损失帽"
    clock.now -= 7200.0
    for index in range(50):
        _obs(store, "u1", "positive", text=f"谢谢你 {index}")
    assert float(_peek(store, "u1")["affinity"]) == now_fraction, "v5 回拨段出现位移"


def test_move_budget_rolls_over_24h_not_local_midnight(tmp_path) -> None:
    """午夜改判锁（A-1 裁定 2026-09-26；替换旧锁
    ``test_day_cap_resets_at_local_midnight_not_utc``——旧名保留在此作回滚指针，
    它断言的「额度耗尽后本地午夜即复位」正是被裁掉的自然日桶语义）。

    新语义两面都在本用例里钉死：
    ① **翻页不再续额**——旧形态下"23:59 吃满 + 00:01 再吃满"的两发排程路
      （120s 内两个全额、可跨档）现给出零位移；
    ② **额度只随 24h 窗滚出恢复**——把首发顶出窗后，同一发才重新能动。
    另钉正向 override 单事件帽：一发 0.12z 只走 0.10z×γ（v8 边际递减，帽后
      按当前高度缩放），剩下的余额由第二发吃掉
    ——「一发吃满全日额度」从此不再是可达形态。
    """
    midnight = _next_local_midnight(1_800_040_000.0)
    assert _day_index(midnight - 30.0) != _day_index(midnight + 90.0), (
        "前提自证：跨过的本地午夜必须翻转 day_index（否则本用例鉴别的是空气）"
    )
    first_at = midnight - 7_200.0  # 本地 22:00 吃满额度（旧形态的"午夜前"侧）
    clock = _Clock(first_at)
    store = _v7_store(tmp_path, "rolling.sqlite3", clock)
    z_base = v7_display_fraction_to_z(_AFFINITY_BASE)

    _obs(store, "u1", "neutral", text="顶格正向第一发（0.12 的授权）", delta_override=0.12)
    _, z_capped = _peek_state(store, "u1")
    # v8 改判重建：帽 0.10 在基数档高度被 γ 缩放 ⇒ 实发 _CAP_AT_BASE（<帽上界）。
    assert z_capped - z_base == pytest.approx(_CAP_AT_BASE, abs=1e-9), (
        "正向 override 未被单事件帽×γ 钳住 ⇒ 摘帽/摘 γ 注毒漏网"
    )
    assert _window_spent(store, "u1") == pytest.approx(_CAP_AT_BASE, abs=1e-9)

    clock.now = first_at + 90.0
    _obs(store, "u1", "neutral", text="吃掉剩余余额的第二发", delta_override=0.12)
    _, z_full = _peek_state(store, "u1")
    assert z_full - z_capped == pytest.approx(_DAILY_CAP - _CAP_AT_BASE, abs=1e-9)

    # —— 鉴别位：午夜两侧各一发（间隔 120s，旧日桶=两个全额）——
    clock.now = midnight - 30.0
    _obs(store, "u1", "neutral", text="午夜前三十秒的一句", delta_override=0.1)
    _, z_still = _peek_state(store, "u1")
    assert z_still == z_full, "本地午夜前额度就复位了 ⇒ 窗根本是 24h 还是别的"
    clock.now = midnight + 90.0
    _obs(store, "u1", "neutral", text="新历日第一句", delta_override=0.1)
    _, z_new = _peek_state(store, "u1")
    assert z_new == z_still, (
        "自然日翻页就续额 ⇒ 滚动 24h 窗退化回 day['s'] 日桶（本用例改判前的旧行为）"
    )
    assert z_new - z_base == pytest.approx(_DAILY_CAP, abs=1e-9), "两发合计应恰为全窗额度"

    # —— 恢复面：首发顶出 24h 窗后，额度才回来 ——
    clock.now = first_at + 86_400.0 + 120.0
    _obs(store, "u1", "neutral", text="首发顶出窗后的一句", delta_override=0.05)
    _, z_after_roll = _peek_state(store, "u1")
    assert z_after_roll - z_new == pytest.approx(
        0.05 * v8_marginal_gain(z_new, _V8_HALF_DEFAULT), abs=1e-9
    ), "24h 窗滚出后额度不恢复 ⇒ 窗没有现读 delta_log"


def test_positive_single_event_cap_bites_on_both_faces(tmp_path) -> None:
    """A-1 正向单事件帽，两面各一发：
    ① override 面（门面 observe 带巨大正 override）⇒ Δz 恰 0.10z×γ(z基数)（v8
      帽后缩放）——旧形态正向"直穿到当日剩余额度"（一发最多吃满 0.12z≈11.98
      展示分）自此不可能；
    ② 普通计分面（更新式真身 `v7_raw_delta_z`，所有计分发都经它）——满因子
      乘积再乘修复 ×1.4 的 raw 积 ≈0.2013z ⇒ 被同一枚帽钳回 0.10z。"""
    clock = _Clock()
    store = _v7_store(tmp_path, "poscap.sqlite3", clock)
    _, z_base = _peek_state(store, "u1")
    _obs(store, "u1", "neutral", text="一句普通的话", delta_override=1e6)
    _, z_after = _peek_state(store, "u1")
    assert z_after - z_base == pytest.approx(_CAP_AT_BASE, abs=1e-9), (
        "override 面正向未咬帽×γ"
    )
    settings = resolve_v7_settings(_v7_config())
    saturated = v7_raw_delta_z(
        1.0, novelty=1.0, rhythm=1.0, mood=1.15, impression=1.25, repair=True, settings=settings,
    )
    assert saturated == pytest.approx(settings.negative_event_cap_z, abs=1e-12), (
        "计分面满因子×修复增益的 raw 积必须被同一枚帽钳回（0.1×1.15×1.25×1.4≈0.2013 → 0.10）"
    )
    mild = v7_raw_delta_z(
        0.4, novelty=1.0, rhythm=1.0, mood=1.0, impression=1.0, repair=False, settings=settings,
    )
    assert mild == pytest.approx(0.04, abs=1e-12), "帽只钳越界值，合法步长逐字节不变"


# ---------------------------------------------------------------------------
# D. 活性判据：绕开门面直接打执法体
# ---------------------------------------------------------------------------


def test_display_move_bound_is_sound_on_zero_spanning_interval() -> None:
    """差分锁（本席 fuzz 抓到并根修的真红）：跨原点对称区间的单事件展示位移
    = 200·tanh(cap/2)，**大于**旧口径 100·tanh(cap) ⇒ 判据函数若取旧式即低报
    上界（机器锁自身有洞）。修正前实况：fuzz 实测单事件 11.958 分 > 旧上界
    11.943 分当场打红；修正后该界由真确界供给，本用例双向钉死。"""
    span_true = (v7_z_to_display_fraction(0.06) - v7_z_to_display_fraction(-0.06)) * 100.0
    old_formula_worst = 100.0 * math.tanh(_DAILY_CAP)
    assert span_true > old_formula_worst, (
        "对称区间不再越过旧公式 ⇒ 旧口径又成正确上界了？与本席修正对账"
    )
    assert span_true <= v7_display_move_for_z_cap(_DAILY_CAP) + 1e-9, "修正后的界函数仍低报上界"
    # 逐档性结论在修正后仍成立（真确界 11.979 ≪ 一档 25）——本件主张不因修正翻转。
    assert v7_display_move_for_z_cap(_DAILY_CAP) < _TIER_WIDTH_DISPLAY - 12.0


def _call_v7_delta(store, sender, *, z=0.0, state="{}", override=None, text="一句普通的话"):
    """不经 observe / observe_points / _observe，直调 v7 更新体。"""
    clock_now = float(store._clock())
    with store._lock, store._connect() as connection:
        return store._v7_delta(
            connection, sender, "", "neutral", z,
            v7=resolve_v7_settings(_v7_config()),
            state_json=state,
            now=clock_now,
            day_index=_day_index(clock_now),
            text=text,
            gap_seconds=None,
            delta_override=override,
            mood_valence=None,
            first_impression=None,
            interaction_count=10,
            day_counters={},
            responded_to_question=None,
            source_event_id="",
        )


def test_liveness_internal_v7_delta_enforces_caps_without_any_facade(tmp_path) -> None:
    """直接调 ``_v7_delta``：顶格正向 override 被**单事件帽×γ**钳住（不再是日额度）、
    额度将尽/耗尽由 **delta_log 滚动窗**供数、窗内脏行保守冻结、旧 state 日桶字段
    彻底离开判据面、坏 JSON、半衰减参考点处减速不冻结（v8 长尾）——位移护栏住在
    执法体内，门面拿不掉它。"""
    clock = _Clock()
    store = _v7_store(tmp_path, "internal_delta.sqlite3", clock)
    settings = resolve_v7_settings(_v7_config())
    today = _day_index(clock.now)

    # sA：全新窗口 + 顶格正向 override ⇒ 咬住它的是 0.10 单事件帽，不是 0.12 日额度。
    applied, new_z, dumped = _call_v7_delta(store, "sA", override=9.9)
    assert applied == pytest.approx(_NEG_CAP, abs=_CAP_TOL), (
        f"fresh-window 正向 override 位移 {applied} ≠ 0.10 ⇒ 正向单事件帽摘岗"
    )
    assert abs(new_z) <= settings.z_hard + 1e-9
    assert "s" not in json.loads(dumped)["day"], (
        "state 回写再现位移额度日桶字段 ⇒ 载体退役不彻底"
    )

    # sB：额度将尽——0.115 由**日志行**供给（新载体），只剩 0.005。
    _seed_log_row(store, "sB", 0.115)
    applied_b, _, _ = _call_v7_delta(store, "sB", override=9.9)
    assert 0.0 < applied_b <= 0.005 + 1e-6, f"额度只剩 0.005 时位移 {applied_b}"

    # sC：负向帽（既有语义）逐字节不变。
    applied_c, new_z_c, _ = _call_v7_delta(store, "sC", override=-9.9)
    assert applied_c == pytest.approx(-_NEG_CAP, abs=1e-9), f"负向未被单事件帽咬住：{applied_c}"
    assert new_z_c == pytest.approx(-_NEG_CAP, abs=1e-9)

    # sD：额度耗尽（一行大额日志）⇒ 零位移。
    _seed_log_row(store, "sD", 0.5)
    applied_d, new_z_d, _ = _call_v7_delta(store, "sD", override=9.9)
    assert applied_d == 0.0 and new_z_d == 0.0, "滚动额度耗尽仍位移 ⇒ 日上限不在执法体内"

    # sE：旧载体离场自证——state 塞大 s/坏日界都不再伸缩额度，剩余只认日志。
    #     （若聚合被换回 day["s"] 日桶：sE2 的坏日界会"翻篇重置"成满额放行 0.10，
    #      本组 0.005 的期望当场红——冷却窗外播行（-90s）保证鉴别位不被冷却门抢先。）
    _seed_log_row(store, "sE", 0.115)
    stale_state = json.dumps({"day": {"i": today, "s": 99.0, "c": {}}, "types": {},
                              "ema": [0.0, clock.now], "recent": []})
    applied_e, _, _ = _call_v7_delta(store, "sE", state=stale_state, override=9.9)
    assert 0.0 < applied_e <= 0.005 + 1e-6, 'state day["s"] 仍在判据面 ⇒ 载体切换不彻底'
    _seed_log_row(store, "sE2", 0.115)
    mismatched = json.dumps({"day": {"i": -99999, "s": -1e9, "c": {}}, "types": {},
                             "ema": [0.0, clock.now], "recent": []})
    applied_e2, _, _ = _call_v7_delta(store, "sE2", state=mismatched, override=9.9)
    assert 0.0 < applied_e2 <= 0.005 + 1e-6, (
        "坏日索引把额度刷回满格 ⇒ 聚合被换回 day[\"s\"] 日桶"
    )

    # sF：窗内**非有限脏行** ⇒ 按额度用满保守冻结（绝不"跳过脏行⇒少算⇒放行"）。
    #     REAL 亲和列对 'nan' 按 SQLite 动态类型以 TEXT 落库——外部直写/事故的真实形态。
    _seed_log_row(store, "sF", "nan")
    applied_f, _, _ = _call_v7_delta(store, "sF", override=0.05)
    assert applied_f == 0.0, "脏额度行被当 0 跳过 ⇒ 保守判据反转"

    # sG：坏 JSON 状态 + 无日志行 ⇒ 窗全新，帽仍咬合。
    applied_g, _, _ = _call_v7_delta(store, "sG", state="]]]坏 JSON 也进不来", override=9.9)
    assert applied_g == pytest.approx(_NEG_CAP, abs=_CAP_TOL)

    # sH：v8 改判——±z_hard 不再是冻结界，而是 γ 的半衰减参考点：该高度顶格
    # override 仍被帽×γ(=0.5) 咬到半帽 0.05z，且 new_z 必须越过旧界（长尾实证：
    # 减速而不冻结），最终由表示域护栏兜住。旧断言"硬界处不得再抬"随前提改判。
    applied_h, new_z_h, _ = _call_v7_delta(store, "sH", z=settings.z_hard, override=9.9)
    assert applied_h == pytest.approx(_NEG_CAP * 0.5, abs=1e-9), "半参考点处必须恰走半帽"
    assert new_z_h > settings.z_hard, "贴旧界冻结 ⇒ v7 硬界形态回潮（长尾改判失守）"
    assert abs(new_z_h) <= _V8_Z_REPR_DOMAIN, "表示域护栏最终必须兜住"


def test_teeth_loosening_the_caps_immediately_breaks_the_property(tmp_path) -> None:
    """差分证据（牙齿自证，A-1 改判后为三层对账）：
    ① 只放宽日额度（daily_move 5.0z）⇒ 单发正向 override 仍被钉在 0.10z——
      单事件帽与滚动额度**各自独立承重**，放掉一层不会造出"一发瞬间巨变"；
    ② 两帽同放（daily 5.0z + negative_event 5.0z，后者键名历史=只钳负向、
      A-1 起双向同帽）⇒ 同一发内部调用立刻位移 ≫0.12z 并贴向长尾顶端
      （v8 改判：兜底者从硬界换为表示域护栏）、跨多档——
      缺省 ≤0.10/≤0.12 的锁因此不是同义反复；
    ③ "滚动 24h 窗 vs 日桶"的**窗形**差分在
      ``test_move_budget_rolls_over_24h_not_local_midnight``（把 v7 聚合换回
      day["s"] 自然日桶，该用例与上一条的 sE2 组当场红）。"""
    clock = _Clock()
    loose_daily = resolve_v7_settings(_v7_config(bot_affinity_daily_move_cap_z=5.0))
    assert loose_daily.daily_move_cap_z == pytest.approx(5.0), "配置面原样接受该值（点名不夹值）"
    assert loose_daily.negative_event_cap_z == pytest.approx(_NEG_CAP), "单事件帽不随日额度联动"

    def _single_shot(store: DynamicAffinityStore, sender: str, settings) -> float:
        with store._lock, store._connect() as connection:
            applied, _new_z, _dumped = store._v7_delta(
                connection, sender, "", "neutral", 0.0,
                v7=settings, state_json="{}", now=clock.now,
                day_index=_day_index(clock.now), text="同一发", gap_seconds=None,
                delta_override=9.9, mood_valence=None, first_impression=None,
                interaction_count=10, day_counters={}, responded_to_question=None,
                source_event_id="",
            )
        return applied

    store = _v7_store(tmp_path, "teeth.sqlite3", clock)
    applied_daily_only = _single_shot(store, "t1", loose_daily)
    assert applied_daily_only == pytest.approx(_NEG_CAP, abs=1e-9), (
        "只放宽日额度后单发应仍被正向帽钉在 0.10 ⇒ 帽与日额度同点失守"
    )
    loose_both = resolve_v7_settings(_v7_config(
        bot_affinity_daily_move_cap_z=5.0, bot_affinity_negative_event_cap_z=5.0))
    applied_both = _single_shot(store, "t2", loose_both)
    assert applied_both > _DAILY_CAP * 10, "两帽同放后位移仍 ≤0.12 ⇒ 本件的差分证据是假的"
    assert abs(applied_both) <= _V8_Z_REPR_DOMAIN + 1e-9, "两帽同放后表示域护栏必须仍兜住"
    assert abs(
        tier_for_affinity(v7_z_to_display_fraction(applied_both)) - tier_for_affinity(_AFFINITY_BASE)
    ) >= 2, "两帽 5.0z 时展示跨档 ≥2 ⇒ 逐档性完全由缺省两帽供给"


def test_liveness_internal_observe_bypass(tmp_path) -> None:
    """直接 ``_observe``（内部口，跳过两个公开门面）×双日连打：单事件界与逐档仍成立。"""
    clock = _Clock()
    store = _v7_store(tmp_path, "internal_observe.sqlite3", clock)
    _, z_prev = _peek_state(store, "u9")
    tier_prev = tier_for_affinity(_AFFINITY_BASE)
    for index in range(40):
        store._observe(
            "u9", "insult" if index % 2 else "positive",
            delta_override=50.0 if index % 3 else -50.0,
            text=_TEXTS[index % len(_TEXTS)],
            mood_valence=1.0,
        )
        _TALLY["events"] += 1
        fraction, z_now = _peek_state(store, "u9")
        assert abs(z_now - z_prev) <= _DAILY_CAP + _CAP_TOL
        _no_tier_skip(f"internal#{index}", tier_prev, tier_for_affinity(fraction))
        z_prev, tier_prev = z_now, tier_for_affinity(fraction)
        clock.advance(61)
        if index == 19:
            clock.advance(86_400)


def test_liveness_external_row_tampering_is_read_back_bounded(tmp_path) -> None:
    """外部直改行（DB 手工/事故形态）后的读回：篡改不得被放大成瞬间巨变——
    脏 z 被 affinity 列权威重推、顶格存量被惰性映射钳回 ±98.5 且其后只按
    γ 减速移动（v8 长尾：不再被硬界吞发，也不再向外扩冲）、坏 state 被消毒、
    负数日额度不得凭空扩额。"""
    clock = _Clock()
    store = _v7_store(tmp_path, "tamper.sqlite3", clock)
    _obs(store, "u1", "positive", text=_PRAISE)
    clock.advance(90)

    with sqlite3.connect(str(store.db_path)) as connection:
        connection.execute("UPDATE user_affinity SET z_latent = 99.0 WHERE sender_id='u1'")
    fraction_before = float(_peek(store, "u1")["affinity"])
    _obs(store, "u1", "positive", text="篡改 z 后的一句好话")
    fraction, z = _peek_state(store, "u1")
    assert abs(z) <= resolve_v7_settings(_v7_config()).z_hard + 1e-9, "被篡改的 z=99 未被权威列重推收回"
    assert abs(fraction - fraction_before) < 0.25, "篡改后单事件把展示值推走 ⇒ 门面读回未走权威列"
    clock.advance(90)

    with sqlite3.connect(str(store.db_path)) as connection:
        connection.execute(
            "UPDATE user_affinity SET affinity = 1.0, z_latent = NULL WHERE sender_id='u1'"
        )
    _obs(store, "u1", "positive", text="顶格存量的一发")
    fraction, _z = _peek_state(store, "u1")
    # v8 改判重建：±100 存量仍被惰性映射钳回 ±98.5（零迁移口径不动），但
    # 其后一发的位移不再被硬界吞掉——从 98.5 处仍可减速上行（长尾），
    # 单发 ≤帽×γ(98.5 处)=0.05z ⇒ 展示上界按新前提放宽到 0.995（远超仍是
    # 一档之上域，档位判据原样保留）。
    assert fraction <= _V8_TAMPER_READBACK_BOUND, "±100 存量读回向外扩了（γ 失效？）"
    assert tier_for_affinity(fraction) == 3
    clock.advance(90)

    with sqlite3.connect(str(store.db_path)) as connection:
        connection.execute("UPDATE user_affinity SET affinity = -1.0 WHERE sender_id='u1'")
    _obs(store, "u1", "insult", text=_INSULT)
    fraction, _z = _peek_state(store, "u1")
    assert fraction >= -_V8_TAMPER_READBACK_BOUND, "谷值存量读回向外扩了（γ 失效？）"
    clock.advance(90)

    today = _day_index(clock.now)
    with sqlite3.connect(str(store.db_path)) as connection:
        connection.execute(
            "UPDATE user_affinity SET v7_state = ? WHERE sender_id='u1'",
            (json.dumps({"day": {"i": today, "s": -1e9, "c": {}}}),),
        )
    _, z_prev = _peek_state(store, "u1")
    _obs(store, "u1", "positive", text="负数旧日桶字段的一发（旧形态的凭空扩额面）")
    _, z_after = _peek_state(store, "u1")
    assert abs(z_after - z_prev) <= _DAILY_CAP + _CAP_TOL, "负数日额度未消毒 ⇒ 可凭空扩额度"
    state_after = json.loads(str(_peek(store, "u1")["v7_state"] or "{}"))
    assert "s" not in state_after["day"], (
        'v7 回写复活 day["s"] 位移字段 ⇒ A-1 载体退役不彻底（额度唯一真身是 delta_log）'
    )


_ALLOWED_STORE_WRITERS = frozenset({
    "affinity.py",                        # 唯一真身（_observe 的 INSERT OR REPLACE）
    "migrate_affinity_v7_rehearsal.py",   # 在册演练器：只补写派生列 z_latent
    "probe_affinity_migration.py",        # 本席合成演练器：根本不带 SQL
})
_USER_AFFINITY_WRITE_RE = re.compile(
    r"(UPDATE\s+user_affinity"
    r"|INSERT(?:\s+OR\s+\w+)?\s+INTO\s+user_affinity"
    r"|DELETE\s+FROM\s+user_affinity)",
    re.IGNORECASE,
)


def _sql_of_execute_call(node: ast.Call) -> str:
    if not node.args:
        return ""
    arg = node.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr):
        return " ".join(
            chunk.value for chunk in arg.values
            if isinstance(chunk, ast.Constant) and isinstance(chunk.value, str)
        )
    return ""


def test_no_second_writer_touches_user_affinity_outside_the_store() -> None:
    """AST 扫描 plugins/ 与 scripts/：以字面 SQL 改 ``user_affinity`` 的
    ``.execute(...)`` 调用除白名单外不存在 ⇒「绕过门面直改分数」在仓库代码面上
    结构不可能（运行时手工改库由上一条读回判据兜底；动态表名拼接不在静态扫描面内，
    故两条判据配对成立，不单独宣称完备）。"""
    offenders: list[str] = []
    for root in ("plugins", "scripts"):
        for path in (_REPO_ROOT / root).rglob("*.py"):
            if path.name in _ALLOWED_STORE_WRITERS:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                source = path.read_text(encoding="utf-8", errors="replace")
            if "user_affinity" not in source or ".execute" not in source:
                continue
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"execute", "executescript", "executemany"}
                ):
                    sql = _sql_of_execute_call(node)
                    if sql and _USER_AFFINITY_WRITE_RE.search(sql):
                        offenders.append(f"{path.relative_to(_REPO_ROOT)}: {sql[:70]}")
    assert not offenders, "出现第二处写 user_affinity 的代码路径：\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# E. 红线零回归（只复跑不放宽；三件既有锁由交卷命令一并跑）
# ---------------------------------------------------------------------------

_HOSTILE_PRESCRIPTIONS = (
    "攻击", "辱骂", "贬低", "谴责", "强硬", "敌意", "敌视", "冷暴力", "轻蔑",
    "憎恨", "鄙视", "厌恶", "嘲讽", "羞辱", "反击", "威胁", "教训",
)
_FIXED_MAGNITUDE_RE = re.compile(
    r"[加减扣乘增降]\s*\d+(?:\.\d+)?\s*(?:分|点|个单位)|±\s*\d+(?:\.\d+)?\s*分"
)


def test_red_lines_and_qualitative_text_hold_across_whole_domain() -> None:
    """全值域扫（±99 内部值网格）：红线在场、过渡语无敌意指令、注入面无固定加减数值。"""
    assert len(_TIER_RED_LINES) == 4
    for i in range(-99, 100):
        value = i / 100.0
        attitude = attitude_for_affinity(value)
        transition = linear_transition_for_affinity(value)
        assert "不攻击" in attitude and "不强硬" in attitude and "不冷暴力弃聊" in attitude
        for banned in _HOSTILE_PRESCRIPTIONS:
            assert banned not in transition, f"{value} 过渡语含敌意词 {banned}"
        assert not _FIXED_MAGNITUDE_RE.search(attitude + transition), f"{value} 注入面出现固定量级"


# ---------------------------------------------------------------------------
# F. 存量处置演练脚本（scripts/probe_affinity_migration.py）
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _probe():
    path = _REPO_ROOT / "scripts" / "probe_affinity_migration.py"
    assert path.exists(), f"演练脚本缺席：{path}"
    spec = importlib.util.spec_from_file_location("probe_affinity_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_probe_migration_quantifies_no_reset_and_no_elevation() -> None:
    module = _probe()
    summary = module.run(seed=20260926, rows=10_000)
    counts = summary["rows"]
    assert counts["rows_total"] == 10_000
    assert counts["conserved"] + counts["clamped"] + counts["dirty_to_base"] == 10_000
    assert counts["conserved"] >= 9_000, "绝大多数存量必须逐点守恒（|v|≤bound）"
    assert summary["elevated_rows"] == 0, "映射把任何人往上抬了 ⇒ 单调性/域钳位被破坏"
    assert summary["tier_changed_rows"] == 0, "映射本身不得改动任何人的档位"
    assert summary["monotone_on_numeric_rows"] is True
    # 唯一合法的位移 = 极端存量向零收（±100 → ±98.5），至多 1.5 个展示分。
    assert summary["abs_shift_display_pts"]["max"] <= 1.5 + 1e-9
    # float64 往返残差（atanh∘tanh 非逐位恒等）：p90 应为「数值零」而非字面 0.0。
    assert summary["abs_shift_display_pts"]["p90"] <= 1e-9
    # 「被重置」只发生在脏值行（消毒回基数 10 分）——量化点名，不含糊。
    assert counts["dirty_to_base"] > 0, "合成面必须含脏值桶，否则该判据空跑"
    # 开 v7 后的最坏位移是派生量（护栏 → 展示分），不是手写数。
    worst = summary["after_enable_worst_case"]["worst_single_day_display_pts"]
    assert worst == pytest.approx(v7_display_move_for_z_cap(_DAILY_CAP), abs=1e-3)  # 脚本侧 round(...,4)
    assert worst < _TIER_WIDTH_DISPLAY - 12.0


def test_probe_migration_is_deterministic_and_seed_sensitive() -> None:
    module = _probe()
    a = json.dumps(module.run(seed=7, rows=2_000), sort_keys=True)
    b = json.dumps(module.run(seed=7, rows=2_000), sort_keys=True)
    c = json.dumps(module.run(seed=8, rows=2_000), sort_keys=True)
    assert a == b, "同 seed 两次运行输出不一致 ⇒ 报告数字不可抄进交接文"
    assert a != c, "seed 不参与 ⇒ 覆盖面退化"


def test_probe_migration_has_no_db_access_and_no_second_math() -> None:
    """「绝不连真库」不是散文：AST 级禁 sqlite3/random/math import、禁 atanh/tanh、
    禁 connect/execute 属性调用——它**表达不出**一条碰真库的语句。"""
    source = (_REPO_ROOT / "scripts" / "probe_affinity_migration.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"sqlite3", "random", "math"} & imported
    assert not forbidden, f"演练脚本 import 了 {forbidden}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"atanh", "tanh", "connect", "execute"}, (
                f"演练脚本出现第二真身/库调用面：{node.attr}"
            )
    assert "v7_display_fraction_to_z" in source and "coerce_affinity_fraction" in source, (
        "映射必须走真身函数"
    )


def test_probe_migration_cli_is_stable(capsys) -> None:
    module = _probe()
    code_first = module.main(["--rows", "500", "--seed", "99"])
    out_first = capsys.readouterr().out
    code_second = module.main(["--rows", "500", "--seed", "99"])
    out_second = capsys.readouterr().out
    assert code_first == 0 and code_second == 0
    assert out_first == out_second
    assert "被抬高行数: 0" in out_first
    code_json = module.main(["--rows", "500", "--seed", "99", "--json"])
    out_json = json.loads(capsys.readouterr().out)
    assert code_json == 0 and out_json["elevated_rows"] == 0


# ---------------------------------------------------------------------------
# G. 规模台账（放在最后：pytest 按文件定义序执行）
# ---------------------------------------------------------------------------


def test_total_event_volume_reached_ten_thousand() -> None:
    assert _TALLY["events"] >= 10_000, (
        f"本件全部好感度事件合计 {_TALLY['events']}，未达 10^4 量级判据"
    )
