"""v6 好感度平滑层回归（用户裁定 2026-09-17「涨和跌太快」，R4 席）。

规范：docs/affinity-design.md 附录 v6 章节（曲线/递减/帽子与理由）。
四道机制叠加（全部门槛保留：-100..+100、8 档温和过渡、定性展示、
任何档位不攻击、拒答≠辱骂、滚动预算、幂等）：
① 饱和响应曲线（§v6.1）：距 ±1 一个档宽（展示 25 分）内步长 smoothstep
   收窄，边界处归零——远离中点步长渐近收窄，极端值附近自然钝化；
② 边际递减（§v6.2）：同日同类信号第 n 次重复只保留 0.6^n（下限 0.2），
   刷好感/刷负分都随重复迅速失味；
③ 日节奏硬帽：复用 V2.1 §2.3 滚动预算——增益 ≤3 分/24h、损失 ≤2 分/6h
   与 ≤4 分/24h、单事件负向 ≤1 分，正负向分开记账，单日不可能暴涨暴跌；
④ 平滑回归：既有惰性回归语义（_PASSIVE_DECAY_ENABLED 政策门）原样保留。

全部离线 tmp_path + 注入时钟；不触碰生产库。

v7 注记（2026-09-21 WP7 席）：本文件与 test_affinity*.py 的常数锁钉的是
**灰度关闭态**（bot_affinity_v7_enabled=False ⇒ v5/v6 逐字节现状）——这正是
设计 §三.4「一键回退」承诺的可验证保证，故保留不改写；v7 开启态的行为级
验收见 tests/test_affinity_v7.py（六场景表逐行实证）。
"""

from __future__ import annotations

import sqlite3
from itertools import pairwise

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _BUDGET_MAX_GAIN_24H_POINTS,
    _BUDGET_MAX_LOSS_6H_POINTS,
    _BUDGET_MAX_LOSS_24H_POINTS,
    _BUDGET_SINGLE_NEGATIVE_EVENT_POINTS,
    _INTERACTION_COOLDOWN_SECONDS,
    _NON_RELATIONSHIP_REASON_CODES,
    _SAME_SIGNAL_DECAY,
    _SAME_SIGNAL_DECAY_FLOOR,
    _SATURATION_BAND,
    DynamicAffinityStore,
    effective_delta,
    per_user_factor,
    repeat_decay_factor,
    saturation_factor,
    score_relationship_signal,
)


class _Clock:
    """可手动推进的注入时钟（秒）。"""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _store(tmp_path, clock: _Clock, name: str = "affinity.sqlite3") -> DynamicAffinityStore:
    return DynamicAffinityStore(tmp_path / name, clock=clock)


def _seed_row(db, sender_id: str, affinity: float) -> None:
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO user_affinity (sender_id, affinity, interaction_count, updated_at)"
            " VALUES (?, ?, 1, '1970-01-01T00:16:40Z')",
            (sender_id, affinity),
        )


# ---------------------------------------------------------------------------
# §v6.1 饱和响应曲线：单调、带外恒等、边界归零、C1 无折点
# ---------------------------------------------------------------------------

def test_saturation_constants_match_design() -> None:
    # 带宽 = §4 一个档宽（内部 0.25 = 展示 25 分）；衰减 0.6^n 下限 0.2。
    assert _SATURATION_BAND == 0.25
    assert _SAME_SIGNAL_DECAY == 0.6
    assert _SAME_SIGNAL_DECAY_FLOOR == 0.2


def test_saturation_factor_is_exactly_identity_outside_band() -> None:
    # 带外（中段六档）：恒为 1，v5 线性语义字节级不变。
    for affinity, direction in ((0.75, 1.0), (0.1, 1.0), (-0.5, 1.0), (0.5, -1.0), (0.97, -1.0)):
        assert saturation_factor(affinity, direction) == pytest.approx(1.0, abs=1e-15)
    # 带边起点（恰差一个档宽）连续收敛到 1。
    assert saturation_factor(0.75, 1.0) == pytest.approx(1.0)


def test_saturation_factor_monotone_tapers_to_zero_at_bounds() -> None:
    # 正向：affinity 越高保留比例越低；谷侧对称；边界处恰好 0（渐近钝化）。
    ups = [saturation_factor(a, 1.0) for a in (0.76, 0.8, 0.85, 0.9, 0.95, 0.99)]
    assert ups == sorted(ups, reverse=True)
    assert all(0.0 < u < 1.0 for u in ups)
    downs = [saturation_factor(a, -1.0) for a in (-0.76, -0.8, -0.85, -0.9, -0.95, -0.99)]
    assert downs == sorted(downs, reverse=True)
    assert all(0.0 < d < 1.0 for d in downs)
    assert saturation_factor(1.0, 1.0) == 0.0
    assert saturation_factor(-1.0, -1.0) == 0.0
    # smoothstep 中点：剩余半个带宽 → 保留一半。
    assert saturation_factor(1.0 - _SATURATION_BAND / 2.0, 1.0) == pytest.approx(0.5)
    # 越界防御：affinity 超出 [-1,1] 时不放大、不翻转。
    assert saturation_factor(1.5, 1.0) == 0.0
    assert saturation_factor(-1.5, -1.0) == 0.0


def test_effective_delta_far_from_extremes_is_full_and_direction_kept() -> None:
    # 中段首次信号：v5 全额（平滑层不改变日常手感）。
    m = per_user_factor("u1")
    assert effective_delta("u1", "positive", 0.1) == pytest.approx(0.02 * m, abs=1e-12)
    assert effective_delta("u1", "insult", 0.1) == pytest.approx(-0.10 * m, abs=1e-12)


def test_effective_delta_saturates_asymmetrically_by_direction() -> None:
    # 同一 affinity 上，朝边界移动的步长被收窄、离边界移动的全额：
    # 0.9 处正向（朝 +1）收窄，负向（朝中段，下方空间充裕）不收窄。
    m = per_user_factor("u1")
    up = effective_delta("u1", "positive", 0.9)
    down = effective_delta("u1", "insult", 0.9)
    assert 0.0 < up < 0.02 * m
    assert down == pytest.approx(-0.10 * m, abs=1e-12)
    # -0.9 处镜像：负向（朝 -1）收窄，正向不收窄。
    assert effective_delta("u1", "insult", -0.9) > -0.10 * m
    assert effective_delta("u1", "positive", -0.9) == pytest.approx(0.02 * m, abs=1e-12)


# ---------------------------------------------------------------------------
# §v6.2 边际递减：同日同类信号 0.6^n 下限 0.2，正负对称
# ---------------------------------------------------------------------------

def test_repeat_decay_schedule_matches_design() -> None:
    assert repeat_decay_factor(0) == 1.0
    assert repeat_decay_factor(1) == pytest.approx(0.6)
    assert repeat_decay_factor(2) == pytest.approx(0.36)
    assert repeat_decay_factor(3) == pytest.approx(0.216)
    # 下限 0.2 兜住长尾：第 4 次起不再低于下限。
    assert repeat_decay_factor(4) == pytest.approx(0.2)
    assert repeat_decay_factor(50) == pytest.approx(0.2)


def test_effective_delta_repeats_monotonically_weaken() -> None:
    m = per_user_factor("u1")
    full = effective_delta("u1", "positive", 0.1)
    first_repeat = effective_delta("u1", "positive", 0.1, repeat_index=1)
    second_repeat = effective_delta("u1", "positive", 0.1, repeat_index=2)
    tenth_repeat = effective_delta("u1", "positive", 0.1, repeat_index=10)
    assert full > first_repeat > second_repeat > tenth_repeat > 0.0
    assert first_repeat == pytest.approx(0.02 * m * _SAME_SIGNAL_DECAY, abs=1e-12)
    # 负向同样递减（刷负分同样失效）。
    insult_full = effective_delta("u1", "insult", 0.1)
    insult_repeat = effective_delta("u1", "insult", 0.1, repeat_index=3)
    assert 0.0 < -insult_repeat < -insult_full
    # 中性和无表行为不产生步长（递减乘上去也不放大）。
    assert effective_delta("u1", "neutral", 0.1, repeat_index=7) == 0.0


def test_store_same_day_repeated_praise_yields_shrinking_steps(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    values = [store.observe("u1", "positive")]
    for _ in range(5):
        clock.advance(_INTERACTION_COOLDOWN_SECONDS + 1)
        values.append(store.observe("u1", "positive"))
    steps = [b - a for a, b in pairwise(values)]
    # 每一步都非负且严格不增（预算钳制只会更紧，递减曲线不被反转）。
    assert all(step >= 0.0 for step in steps)
    assert steps == sorted(steps, reverse=True)
    assert steps[0] > steps[-1]
    # 单日总增益不破 24h 全局增益帽。
    assert values[-1] - 0.1 <= _BUDGET_MAX_GAIN_24H_POINTS / 100.0 + 1e-9


def test_store_same_day_repeated_insult_tapers_inside_loss_budget(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    values = [store.observe("u1", "insult")]
    for _ in range(4):
        clock.advance(_INTERACTION_COOLDOWN_SECONDS + 1)
        values.append(store.observe("u1", "insult"))
    steps = [b - a for a, b in pairwise(values)]
    # 第 1、2 击各顶到单事件负帽（1 分）→ 6h 损失预算（2 分）耗尽；其后预算
    # 咬合计 0——步长全程非增（递减让 raw 更小，预算钳制只会更紧，不会反转）。
    assert values[0] - 0.1 == pytest.approx(-_BUDGET_SINGLE_NEGATIVE_EVENT_POINTS / 100.0)
    assert steps[0] == pytest.approx(-_BUDGET_SINGLE_NEGATIVE_EVENT_POINTS / 100.0)
    assert all(step <= 0.0 for step in steps)
    assert steps == sorted(steps)
    assert steps[-1] > -_BUDGET_SINGLE_NEGATIVE_EVENT_POINTS / 100.0
    # 6h 损失帽兜底：总损失不超过 2 分。
    assert 0.1 - values[-1] <= _BUDGET_MAX_LOSS_6H_POINTS / 100.0 + 1e-9


def test_decay_resets_next_day_while_budget_rolls(tmp_path) -> None:
    # 递减按自然日重置（同日重复才失味）；滚动预算纯时间窗、跨日不重置——
    # 两者口径不同、各司其职：递减防「一天内刷」，预算防「跨日累积冲档」。
    clock = _Clock()
    store = _store(tmp_path, clock)
    first = store.observe("u1", "positive")
    clock.advance(_INTERACTION_COOLDOWN_SECONDS + 1)
    second_today = store.observe("u1", "positive")
    # 次日（跨过本地午夜，+86401s 必然跨日）：递减计数清零；24h 增益窗只
    # 滚出了最早一批，预算仍记着当日第二击——次日首击步长依然回升。
    clock.advance(86400.0)
    third_next_day = store.observe("u1", "positive")
    step_second = second_today - first
    step_next_day = third_next_day - second_today
    assert step_next_day > step_second, "递减按日重置：次日首击步长须大于当日末次递减步长"


# ---------------------------------------------------------------------------
# §v6.3 日节奏硬帽：正负向分开记账，单日不可能暴涨暴跌（复用滚动预算）
# ---------------------------------------------------------------------------

def test_single_day_net_gain_capped_even_with_many_events(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    last = 0.1
    for _ in range(30):
        clock.advance(_INTERACTION_COOLDOWN_SECONDS + 1)
        last = store.observe("u1", "positive")
    assert last - 0.1 == pytest.approx(_BUDGET_MAX_GAIN_24H_POINTS / 100.0, abs=1e-9), (
        "30 连赞单日总增益仍封在 24h 全局增益帽"
    )


def test_single_day_net_loss_capped_and_separate_from_gain(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # 30 连骂全部落在 6h 窗内（30×61s ≈ 31 分钟）：更紧的 6h 帽（2 分）先咬合。
    last = 0.1
    for _ in range(30):
        clock.advance(_INTERACTION_COOLDOWN_SECONDS + 1)
        last = store.observe("u1", "insult")
    assert 0.1 - last == pytest.approx(_BUDGET_MAX_LOSS_6H_POINTS / 100.0, abs=1e-9)
    # 6.5h 后（首批滚出 6h 窗、仍在 24h 窗内）：24h 帽继续封顶到 4 分。
    clock.advance(6.5 * 3600)
    last = store.observe("u1", "insult")
    clock.advance(_INTERACTION_COOLDOWN_SECONDS + 1)
    last = store.observe("u1", "insult")
    assert 0.1 - last == pytest.approx(_BUDGET_MAX_LOSS_24H_POINTS / 100.0, abs=1e-9), (
        "单日总损失封在 24h 损失帽（正负向分开记账的负向半边）"
    )
    # 正负分开记账：损失预算耗尽不得冻结增益通道（增益帽独立计数）。
    clock.advance(_INTERACTION_COOLDOWN_SECONDS + 1)
    praised = store.observe("u1", "positive")
    assert praised > last, "损失帽满不得冻结增益通道（正负向分开计帽）"


def test_saturation_keeps_behavior_path_off_the_hard_bounds(tmp_path) -> None:
    clock = _Clock()
    db = tmp_path / "affinity.sqlite3"
    store = _store(tmp_path, clock)
    # 播种到边界：行为路径步长在边界恰好归零（渐近钝化，永不击穿）；
    # 硬 clamp [-1,+1] 只由 override 路径验证（权威信号）。
    _seed_row(db, "u1", 1.0)
    assert store.observe("u1", "positive") == pytest.approx(1.0, abs=1e-12)
    _seed_row(db, "u2", -1.0)
    assert store.observe("u2", "insult") == pytest.approx(-1.0, abs=1e-12)
    _seed_row(db, "u3", 0.995)
    after = store.observe("u3", "positive")
    assert 0.995 < after <= 1.0
    assert after - 0.995 < 0.02 * per_user_factor("u3") * 0.05


# ---------------------------------------------------------------------------
# 既有防线不回归：预算/幂等/冷却/七类零计分/override 权威
# ---------------------------------------------------------------------------

def test_budget_idempotency_and_cooldown_survive_v6(tmp_path) -> None:
    clock = _Clock()
    db = tmp_path / "affinity.sqlite3"
    store = _store(tmp_path, clock)
    # 幂等：同一 source_event_id 重放只落一次。
    first = store.observe_points("u1", -3.0, source="probe", source_event_id="evt-1")
    replay = store.observe_points("u1", -3.0, source="probe", source_event_id="evt-1")
    assert first == pytest.approx(0.09, abs=1e-9)
    assert replay == pytest.approx(first, abs=1e-12)
    with sqlite3.connect(str(db)) as connection:
        rows = connection.execute(
            "SELECT COUNT(*) FROM affinity_delta_log WHERE sender_id='u1'"
        ).fetchone()
    assert int(rows[0]) == 1
    # 冷却：窗口内重复事件记 0 分。
    clock.advance(5)
    assert store.observe("u1", "insult") == pytest.approx(0.09, abs=1e-9)
    # 冷却过后：递减+预算下仍受单事件负帽约束（-1 分）。
    clock.advance(_INTERACTION_COOLDOWN_SECONDS)
    assert store.observe("u1", "insult") == pytest.approx(0.08, abs=1e-9)


def test_override_stays_authoritative_through_v6(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # override 不乘系数、不饱和、不递减——只过预算（正向 3 分/24h、负向单事件 1 分）。
    assert store.observe("u1", "neutral", delta_override=5.0) == pytest.approx(0.13, abs=1e-9)
    clock.advance(_INTERACTION_COOLDOWN_SECONDS + 1)
    assert store.observe("u2", "neutral", delta_override=-5.0) == pytest.approx(0.09, abs=1e-9)


@pytest.mark.parametrize("code", sorted(_NON_RELATIONSHIP_REASON_CODES))
def test_seven_non_relationship_reason_codes_still_score_zero(tmp_path, code) -> None:
    # v6 不改变 §2.2 解耦边界：七类非关系 reason_code 零计分。
    clock = _Clock()
    store = _store(tmp_path, clock)
    base = store.snapshot("u1")["affinity"]
    behavior, returned = score_relationship_signal(
        "你就是个废物，闭嘴", safety_category="harassment", reason_code=code
    )
    store.observe("u1", behavior)
    assert store.snapshot("u1")["affinity"] == pytest.approx(base, abs=1e-12)
    assert returned == code


def test_passive_regression_semantics_untouched_by_v6(tmp_path, monkeypatch) -> None:
    # 平滑回归：政策门开启后旧 §3 惰性回归语义原样（v6 不引入第二套回归）。
    import plugins.bot_unified_runtime.domains.chat_reply.character.affinity as affinity_module

    monkeypatch.setattr(affinity_module, "_PASSIVE_DECAY_ENABLED", True)
    # 时钟起点与 _seed_row 播种的 updated_at（1970-01-01T00:16:40Z = 1000.0）
    # 对齐，闲置天数从播种时刻起算。
    clock = _Clock(1000.0)
    db = tmp_path / "reg.sqlite3"
    store = _store(tmp_path, clock, name="reg.sqlite3")
    _seed_row(db, "u1", 0.5)
    clock.advance(10 * 86400.0)
    assert store.observe("u1", "neutral") == pytest.approx(0.40, abs=1e-9)


# ---------------------------------------------------------------------------
# §v6.4 展示纪律：算法说明保持定性口径，不暴露任何公式数值
# ---------------------------------------------------------------------------

def test_algorithm_copy_describes_smoothing_qualitatively() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
        ALGORITHM_TEXT,
    )

    assert "平滑" in ALGORITHM_TEXT, "必须反映 v6 平滑层"
    assert "递减" in ALGORITHM_TEXT, "必须反映边际递减"
    assert "饱满" in ALGORITHM_TEXT or "钝" in ALGORITHM_TEXT, "必须反映近极端钝化"
    # 定性红线：不出现步长/比例/预算数值口径（历史契约 + v6 新增数字）。
    for banned in ("+2", "-5", "0.6", "0.2", "3 分", "4 分", "1 分", "%"):
        assert banned not in ALGORITHM_TEXT, f"算法说明不得出现数值口径：{banned}"
