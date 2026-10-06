"""好感度 v7 重写回归（WP7 席，2026-09-21 用户裁定「算法全部重写」）。

规范唯一权威：docs/design/affinity-v7-design.md（潜变量 z + tanh 映射 +
质量分 q + 跨日新鲜度 + 按人 rhythm 归一 + 修复通道 + 三道护栏）。
本件按 §六 实施要求立**行为级**断言（不可触顶/单调/跨日边际递减/敷衍不涨/
修复通道/话痨不占便宜/八档边界不跳变/红线逐字不变），并逐行实证 §五 六场景表。
v5/v6 常数锁（test_affinity*.py）钉的是灰度关闭回退态，另行保留不改写
（设计 §三.4「缺省 False ⇒ 现行为逐字不变」的可验证保证）。
全部离线 tmp_path + 注入时钟；不触碰生产库。
"""

from __future__ import annotations

import json
import math
import sqlite3
import types
from itertools import pairwise

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _ATTITUDE_TIERS,
    _TIER_RED_LINES,
    _V7_CONFIG_FIELDS,
    _V7_DEFAULT_DAILY_MOVE_CAP_Z,
    _V7_NOVELTY_FLOOR,
    _V8_DEFAULT_DAILY_MOVE_CAP_Z,
    DynamicAffinityStore,
    attitude_for_affinity,
    classify_behavior,
    linear_transition_for_affinity,
    resolve_v7_settings,
    resolve_v8_settings,
    tier_for_affinity,
    v7_display_fraction_to_z,
    v7_novelty_factor,
    v7_quality_score,
    v7_raw_delta_z,
    v7_rhythm_factor,
    v7_z_to_display_fraction,
    v8_marginal_gain,
)

_V7_ENV_KEYS = [name.upper() for name, _default in _V7_CONFIG_FIELDS]

# v8（2026-09-27「边际递减 + 长尾」）：本文件按新前提重建的断言用此表示域界
# （展示分开区间 ±0.999999，等于 atanh 输入域钳位）。前提变更、锁不删。
_V8_DISPLAY_DOMAIN = 0.999999
_V8_HALF_DEFAULT = math.atanh(0.985)  # 缺省 z_hard（γ 半衰减参考点）


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
        "bot_affinity_negative_event_cap_z": 0.10,
        # 日额度随登记常量现取（台账 F-16 拆轴 2026-10-06：评分判据侧缺省 0.12z；键面/展示侧另册 0.04）
        "bot_affinity_daily_move_cap_z": _V7_DEFAULT_DAILY_MOVE_CAP_Z,
        "bot_affinity_fuse_daily_events": 25,
        "bot_affinity_repair_gain": 1.4,
        "bot_affinity_z_hard_bound": 0.985,
        "bot_affinity_quality_weights": "",
        "bot_affinity_decay_tau_days": "",
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _v7_store(tmp_path, clock: _Clock, name: str = "affinity.sqlite3", **config_over):
    return DynamicAffinityStore(
        tmp_path / name, clock=clock, config=_v7_config(**config_over)
    )


def _legacy_store(tmp_path, clock: _Clock, name: str = "affinity.sqlite3"):
    return DynamicAffinityStore(
        tmp_path / name, clock=clock, config=_v7_config(bot_affinity_v7_enabled=False)
    )


@pytest.fixture(autouse=True)
def _isolate_v7_env(monkeypatch):
    """套件内 12 枚 v7 env 键一律剥离——env 回退路径只由专测把玩。"""
    for key in _V7_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _seed(db: sqlite3.Connection | str, sender_id: str, affinity: float) -> None:
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO user_affinity"
            " (sender_id, affinity, interaction_count, updated_at)"
            " VALUES (?, ?, 40, '1970-01-01T00:16:40Z')",
            (sender_id, affinity),
        )


def _state_of(db, sender_id: str) -> dict:
    with sqlite3.connect(str(db)) as connection:
        raw = connection.execute(
            "SELECT v7_state FROM user_affinity WHERE sender_id = ?", (sender_id,)
        ).fetchone()[0]
    return json.loads(str(raw or "{}"))


_PRAISES = [
    "谢谢你陪我聊天",
    "早上好呀，昨晚睡得好吗？",
    "有你在真的太好了",
    "辛苦啦守岸人",
    "晚安，明天见",
]


def _run_days(store, clock, sender: str, events_per_day: int, days: int, texts=_PRAISES):
    """整日互动推进器：事件间隔 90s（>60s 冷却），日间隔按 24h 对齐。"""
    for day in range(days):
        for index in range(events_per_day):
            store.observe(
                sender, "positive", text=texts[(day * 3 + index) % len(texts)]
            )
            clock.advance(90)
        clock.advance(86400 - events_per_day * 90)


# =========================================================================
# A. 表示与迁移（§2.1/§三；守恒断言+负样本——§六.4「漏一人即红」）
# =========================================================================


def test_v7_mapping_roundtrip_and_clamp() -> None:
    # atanh/tanh 在域内逐点互逆；域外钳到 ±bound（极端 legacy 的唯一合法位移）。
    for fraction in (-0.985, -0.5, 0.0, 0.1, 0.75, 0.985):
        z = v7_display_fraction_to_z(fraction)
        assert abs(v7_z_to_display_fraction(z) - fraction) < 1e-12
    assert v7_display_fraction_to_z(1.0) == pytest.approx(math.atanh(0.985))
    assert v7_display_fraction_to_z(-2.0) == pytest.approx(-math.atanh(0.985))


def test_v7_legacy_rows_conserve_scores(tmp_path) -> None:
    """迁移=表示变换不是重算：seed 一批存量分值，v7 读经一次零分事件写入，
    除设计写明的 ±98.5 域钳外逐行守恒；任何一行漂移即红（漏一人即红）。"""
    clock = _Clock()
    db = tmp_path / "conserve.sqlite3"
    store = _v7_store(tmp_path, clock, "conserve.sqlite3")
    rows = {
        f"u{i}": value
        for i, value in enumerate(
            [-1.0, -0.999, -0.985, -0.5, -0.1, 0.0, 0.1, 0.25, 0.5, 0.9, 0.984, 0.985, 0.999, 1.0]
        )
    }
    for sender, value in rows.items():
        _seed(db, sender, value)
    for sender, value in rows.items():
        store.observe(sender, "refusal", text="")  # 零计分行为：只走写入路径（v7 分支全量回写）
    for sender, value in rows.items():
        snapshot = store.snapshot(sender)
        expected = max(-0.985, min(0.985, value))
        assert abs(snapshot["affinity"] - expected) < 1e-9, (
            f"存量 {sender} 的 {value} 被迁移改写为 {snapshot['affinity']}"
        )


def test_v7_state_survives_garbage(tmp_path) -> None:
    """负样本：v7_state 被写成垃圾 JSON / 坏类型也不崩、按空态重开（fail-open）。"""
    clock = _Clock()
    db = tmp_path / "garbage.sqlite3"
    store = _v7_store(tmp_path, clock, "garbage.sqlite3")
    store.observe("u1", "positive", text=_PRAISES[0])
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "UPDATE user_affinity SET v7_state = ? WHERE sender_id = 'u1'",
            ("{ not json ][",),
        )
    clock.advance(3600)
    after = store.observe("u1", "positive", text=_PRAISES[2])
    assert after > 0.1  # 正常计分，未因坏状态卡死
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "UPDATE user_affinity SET v7_state = ? WHERE sender_id = 'u1'",
            (json.dumps({"types": {"positive": ["x", None]}, "day": 5, "ema": "junk"}),),
        )
    clock.advance(3600)
    assert store.observe("u1", "positive", text=_PRAISES[3]) >= after


def test_v7_off_is_legacy_and_toggle_preserves_state(tmp_path) -> None:
    """灰度开关：关=逐字节 v5/v6；开→关→开 不丢 z 与新鲜度状态（一键回退承诺）。"""
    clock = _Clock()
    db = tmp_path / "toggle.sqlite3"
    legacy = _legacy_store(tmp_path, clock, "toggle.sqlite3")
    legacy.observe("u1", "positive", text="谢谢你陪我聊天")
    with sqlite3.connect(str(db)) as connection:
        z_after_legacy = connection.execute(
            "SELECT z_latent FROM user_affinity WHERE sender_id='u1'"
        ).fetchone()[0]
    assert z_after_legacy is None  # 关态不写潜变量列
    first = legacy.snapshot("u1")["affinity"]
    v7 = _v7_store(tmp_path, clock, "toggle.sqlite3")
    clock.advance(3600)
    second = v7.observe("u1", "positive", text="谢谢你一直陪着我呀")
    assert second > first
    with sqlite3.connect(str(db)) as connection:
        row = connection.execute(
            "SELECT z_latent, v7_state FROM user_affinity WHERE sender_id='u1'"
        ).fetchone()
    assert row[0] is not None and json.loads(row[1])["types"].get("positive")
    back = _legacy_store(tmp_path, clock, "toggle.sqlite3")
    clock.advance(3600)
    back.observe("u1", "positive", text="再谢一次")
    with sqlite3.connect(str(db)) as connection:
        row2 = connection.execute(
            "SELECT z_latent, v7_state FROM user_affinity WHERE sender_id='u1'"
        ).fetchone()
    assert row2[0] == pytest.approx(row[0])  # 关态透传，不清空
    assert row2[1] == row[1]


def test_v7_z_column_matches_display_mapping(tmp_path) -> None:
    """库内不变量：v7 写入后 affinity == tanh(z_latent)（两列一个事实源）。"""
    clock = _Clock()
    db = tmp_path / "column.sqlite3"
    store = _v7_store(tmp_path, clock, "column.sqlite3")
    for index in range(15):
        store.observe("u1", "positive", text=_PRAISES[index % 5] + f"{index}")
        clock.advance(90)
    with sqlite3.connect(str(db)) as connection:
        row = connection.execute(
            "SELECT affinity, z_latent FROM user_affinity WHERE sender_id='u1'"
        ).fetchone()
    assert float(row[0]) == pytest.approx(math.tanh(float(row[1])), abs=1e-12)


# =========================================================================
# B. 结构性护栏：不可触顶 / 单调 / 上限三道
# =========================================================================


def test_v7_display_never_touches_extremes_under_pounding(tmp_path) -> None:
    """注毒靶①：把 tanh 换成线性钳位后 200+ 事件必然踩到 ±100——本锁咬住
    「结构上不可触顶」（用户核心抱怨「一下子就到顶了」的根治判据）。"""
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "never.sqlite3")
    for index in range(220):
        store.observe("up", "positive", text=_PRAISES[index % 5] + f"{index}")
        store.observe("down", "insult", text=f"你就是个蠢货{index}")
        clock.advance(90)
        if index % 10 == 9:
            clock.advance(86400)
    for sender in ("up", "down"):
        affinity = store.snapshot(sender)["affinity"]
        # v8 长尾前提变更：±98.5 不再是截断界，展示域放宽为开区间 ±0.999999
        # （= atanh 输入钳位）；「结构上不可触顶」判据按新域重建，不删锁。
        assert -_V8_DISPLAY_DOMAIN - 1e-9 < affinity < _V8_DISPLAY_DOMAIN + 1e-9
        assert abs(affinity) < 1.0, "展示口径必须严格落在开区间内（永不触顶）"


def test_v7_long_positive_stream_keeps_moving(tmp_path) -> None:
    """注毒靶①b：novelty 恒 1 会被 #C 族咬住；本锁咬住「新鲜度下限」的另一半——
    持续高质量互动仍有慢速可累积位移（若把 floor 注成 0，30 天后纹丝不动）。"""
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "stream.sqlite3")
    _run_days(store, clock, "u1", events_per_day=6, days=20)
    mid = store.snapshot("u1")["affinity"]
    _run_days(store, clock, "u1", events_per_day=6, days=20)
    late = store.snapshot("u1")["affinity"]
    assert late > mid + 1e-4, "长期持续互动必须仍可缓慢累积（区分度不塌缩）"
    # v8 长尾：旧 ±98.5 触顶判据按新前提重建为表示域开区界（可越过半衰减
    # 参考点、结构上永不触顶）；本锁的「floor 注 0 ⇒ 30 天纹丝不动」注毒靶不变。
    assert late < _V8_DISPLAY_DOMAIN, "长尾：持续减速但不可触顶"


def test_v7_monotone_nondecreasing_under_pure_positive(tmp_path) -> None:
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "mono.sqlite3")
    previous = store.snapshot("u1")["affinity"]
    for index in range(60):
        current = store.observe("u1", "positive", text=_PRAISES[index % 5] + str(index))
        clock.advance(90)
        assert current >= previous
        previous = current


def test_daily_move_cap_z(tmp_path) -> None:
    """熔断·位移额度：任何事件组合下 |ΣΔz| ≤ 缺省日额度/人/滚动24h（界随
    _V7_DEFAULT_DAILY_MOVE_CAP_Z 现算；读 z_latent 差值；A-1 裁定起窗形=24h 现读
    delta_log，本用例 60 发×90s 全在同一日窗内，两窗形同解）。"""
    clock = _Clock()
    db = tmp_path / "cap.sqlite3"
    store = _v7_store(tmp_path, clock, "cap.sqlite3")
    start_z = v7_display_fraction_to_z(0.1)
    for index in range(60):
        store.observe("u1", "positive", text=_PRAISES[index % 5] + f"！{index}")
        clock.advance(90)
    with sqlite3.connect(str(db)) as connection:
        end_z = float(
            connection.execute(
                "SELECT z_latent FROM user_affinity WHERE sender_id='u1'"
            ).fetchone()[0]
        )
    assert end_z - start_z == pytest.approx(_V7_DEFAULT_DAILY_MOVE_CAP_Z, abs=1e-6)


def test_negative_event_cap(tmp_path) -> None:
    """单次负向事件 |Δz| ≤ negative_event_cap_z（override 同门）。"""
    clock = _Clock()
    db = tmp_path / "negcap.sqlite3"
    store = _v7_store(
        tmp_path, clock, "negcap.sqlite3",
        bot_affinity_negative_event_cap_z=0.05,
        # 场景隔离（test_daily_effective_caps_fallback_gates_positive 先例）：抬走日额度
        # 护栏——本锁只判单事件负向帽，日额度缺省比 0.05 窄时会抢先咬合改判对象。
        bot_affinity_daily_move_cap_z=99.0,
    )
    before = store.snapshot("u1")["affinity"]
    store.observe("u1", "neutral", delta_override=-0.9)
    with sqlite3.connect(str(db)) as connection:
        z_after = float(
            connection.execute(
                "SELECT z_latent FROM user_affinity WHERE sender_id='u1'"
            ).fetchone()[0]
        )
    z_before = v7_display_fraction_to_z(before)
    # v8 边际递减：帽后乘 γ(|z|)，帽 0.05 是该高度处的**上界**、实发 0.05×γ。
    # 断言按新前提重建（不删锁）：|Δz| 精确等于 0.05×γ(z_before)。
    expected = 0.05 * v8_marginal_gain(z_before, _V8_HALF_DEFAULT)
    assert z_before - z_after == pytest.approx(expected, abs=1e-6)
    assert z_before - z_after < 0.05, "γ≤1：实发位移严格不超帽（护栏上界只收紧）"


def test_fuse_daily_events_zero_further_scoring(tmp_path) -> None:
    """注毒靶②：熔断（同类信号每日计分上限）——40 条实质中性消息只计 25 条。"""
    clock = _Clock()
    # 场景隔离（同 test_daily_effective_caps_fallback_gates_positive 先例）：抬走日额度
    # 护栏——本锁只判熔断 25 枚精确接管，日额度不得成为影子收口者。
    store = _v7_store(tmp_path, clock, "fuse.sqlite3", bot_affinity_daily_move_cap_z=99.0)
    scored = 0
    previous = store.snapshot("u1")["affinity"]
    for index in range(40):
        current = store.observe(
            "u1", "neutral",
            text=f"关于方案我们补充第{index}条新想法，你觉得接下来该怎么推进？",
        )
        clock.advance(90)
        scored += 1 if abs(current - previous) > 1e-12 else 0
        previous = current
    assert scored == 25


def test_daily_effective_caps_fallback_gates_positive(tmp_path) -> None:
    """_DAILY_EFFECTIVE_CAPS 降级为兜底：positive 第 11 条起不计分（fuse 之前先到）。"""
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "fallbackcap.sqlite3", bot_affinity_daily_move_cap_z=99.0)
    scored = 0
    previous = store.snapshot("u1")["affinity"]
    for index in range(15):
        current = store.observe("u1", "positive", text=_PRAISES[index % 5] + f"{index}")
        clock.advance(90)
        scored += 1 if abs(current - previous) > 1e-12 else 0
        previous = current
    assert scored == 10


def test_cooldown_gate_survives_v7(tmp_path) -> None:
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "cool.sqlite3")
    before = store.snapshot("u1")["affinity"]
    store.observe("u1", "positive", text=_PRAISES[0])
    after_first = store.snapshot("u1")["affinity"]
    assert after_first > before
    clock.advance(30)  # 冷却窗内
    same = store.observe("u1", "positive", text=_PRAISES[1])
    assert same == pytest.approx(after_first)
    clock.advance(61)
    grown = store.observe("u1", "positive", text=_PRAISES[2])
    assert grown > after_first


def test_idempotency_and_override_in_v7(tmp_path) -> None:
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "idem.sqlite3")
    first = store.observe("u1", "positive", text="谢谢你", source_event_id="evt-1")
    clock.advance(90)
    replay = store.observe("u1", "positive", text="谢谢你", source_event_id="evt-1")
    assert replay == pytest.approx(first)
    clock.advance(3600)
    boosted = store.observe("u1", "neutral", delta_override=0.06)
    assert boosted > first


def test_delta_log_marks_v7_rows_and_legacy_budget_ignores_them(tmp_path) -> None:
    """单位不混用：source='v7' 行以 z 记账、带 z_after；v5 分口径预算查询排除之。"""
    clock = _Clock()
    db = tmp_path / "logmix.sqlite3"
    store = _v7_store(tmp_path, clock, "logmix.sqlite3")
    store.observe("u1", "positive", text="谢谢你陪我聊天")
    with sqlite3.connect(str(db)) as connection:
        rows = connection.execute(
            "SELECT source, delta, z_after FROM affinity_delta_log WHERE sender_id='u1'"
        ).fetchall()
    assert rows and all(str(r[0]) == "v7" for r in rows)
    assert all(r[1] <= _V7_DEFAULT_DAILY_MOVE_CAP_Z + 1e-9 for r in rows)  # z 域，不是百分口径
    assert all(r[2] is not None for r in rows)
    legacy = _legacy_store(tmp_path, clock, "logmix.sqlite3")
    clock.advance(3600)
    before = legacy.snapshot("u1")["affinity"]
    legacy.observe("u1", "positive", text="谢谢")  # v5 gain 预算应完全可用（0 gain）
    assert legacy.snapshot("u1")["affinity"] > before


# =========================================================================
# C. 设计 §五 六场景表逐行实证
# =========================================================================


def test_scenario1_ten_days_praise_lands_in_30_40_band(tmp_path) -> None:
    """场景1：每天 10 句好话 ×10 天 → 30~40 分带内（v6 同期 75+），顶端不可达。"""
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "s1.sqlite3")
    _run_days(store, clock, "u1", events_per_day=10, days=10)
    score = store.snapshot("u1")["affinity"] * 100.0
    assert 30.0 <= score <= 42.0, f"设计口径 30~40，实得 {score:.1f}"
    day7_before = score
    _run_days(store, clock, "u1", events_per_day=10, days=3)
    after = store.snapshot("u1")["affinity"] * 100.0
    assert after > day7_before, "仍在增长（区分度不塌缩）"
    assert after < 75.0, "10+3 天刷不进 v6 的饱和带"


def test_scenario2_dismissive_repeats_barely_move(tmp_path) -> None:
    """场景2：连发"嗯""哦"敷衍 ×10 天 → 几乎不动（v6 会按日涨分）。"""
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "s2.sqlite3")
    start = store.snapshot("u1")["affinity"]
    for _day in range(10):
        for word in ("嗯", "哦", "嗯嗯", "哦哦"):
            store.observe("u1", "neutral", text=word)
            clock.advance(90)
        clock.advance(86400 - 360)
    moved = abs(store.snapshot("u1")["affinity"] - start) * 100.0
    assert moved < 2.0, f"敷衍十日位移 {moved:.2f} 分，应 <2 分"


def test_scenario2b_same_short_praise_spam_grows_far_less_than_varied(tmp_path) -> None:
    """场景2 加强：复读同一句短夸（延展度归零 + 新鲜度衰减）显著劣于多样表达。
    放开日位移帽以隔离比较两种输入本身的增长差（帽的存在是另一道锁，另有专测）。"""
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "s2b.sqlite3", bot_affinity_daily_move_cap_z=1.0)
    for _ in range(8):
        store.observe("spammer", "positive", text="好棒")
        clock.advance(90)
    spam = store.snapshot("spammer")["affinity"] - 0.1
    clock2 = _Clock(clock.now)
    store2 = _v7_store(tmp_path, clock2, "s2b2.sqlite3", bot_affinity_daily_move_cap_z=1.0)
    for index in range(8):
        store2.observe(
            "sincere", "positive",
            text=f"你今天整理的资料真的帮大忙了，辛苦了，后续我还想请教第{index}节的做法",
        )
        clock2.advance(90)
    sincere = store2.snapshot("sincere")["affinity"] - 0.1
    assert sincere > spam * 1.5, "敷衍式连发不得与真诚表达同酬"


def test_scenario3_insult_capped_and_milder_at_height(tmp_path) -> None:
    """场景3：被骂一句 |Δz|≤0.10，且高位（s≈90）的实际降幅自动远小于低区。"""
    clock = _Clock()
    db = tmp_path / "s3.sqlite3"
    store = _v7_store(tmp_path, clock, "s3.sqlite3")
    _seed(db, "u1", 0.1)
    before = store.snapshot("u1")["affinity"]
    clock.advance(3600)
    after = store.observe("u1", "insult", text="你就是个蠢货")
    low_drop = (before - after) * 100.0
    assert 0 < low_drop <= 10.0 + 1e-6
    _seed(db, "u1", 0.9)
    high_before = store.snapshot("u1")["affinity"]
    clock.advance(3600)
    high_after = store.observe("u1", "insult", text="你真是个蠢货呀")
    high_drop = (high_before - high_after) * 100.0
    assert 0 < high_drop < low_drop / 3.0, "tanh 斜率钝化：高位降幅必须显著更小"


def test_scenario4_apology_repairs_without_consuming_quota(tmp_path) -> None:
    """场景4：吵架后道歉走独立修复通道——正向位移、不吃同类配额、非零即达。"""
    clock = _Clock()
    db = tmp_path / "s4.sqlite3"
    store = _v7_store(tmp_path, clock, "s4.sqlite3")
    for _ in range(12):
        store.observe("u1", "positive", text="谢谢你陪我聊天")
        clock.advance(90)
    before = store.snapshot("u1")["affinity"]
    clock.advance(86400)  # 次日（当日位移预算已复位）
    clock.advance(600)
    after = store.observe(
        "u1", "neutral", text="对不起昨天是我不对，你别生气好不好，我给你道歉"
    )
    gain = (after - before) * 100.0
    assert gain > 2.0, "修复通道必须实打实回血（实测 ≈4.3 分）"
    state = _state_of(db, "u1")
    # 修复事件不进新鲜度计数：neutral 计数须仍为 0（条目可因衰减记录落盘，数不许涨）。
    assert state["types"].get("neutral", [0.0])[0] == 0.0


def test_scenario4b_repair_gain_amplifies_positive_step() -> None:
    settings = resolve_v7_settings(_v7_config())
    plain = v7_raw_delta_z(
        0.4, novelty=1.0, rhythm=1.0, mood=1.0, impression=1.0, repair=False, settings=settings
    )
    repaired = v7_raw_delta_z(
        0.4, novelty=1.0, rhythm=1.0, mood=1.0, impression=1.0, repair=True, settings=settings
    )
    assert repaired == pytest.approx(plain * 1.4)
    never_negative = v7_raw_delta_z(
        -0.4, novelty=1.0, rhythm=1.0, mood=1.0, impression=1.0, repair=True, settings=settings
    )
    assert never_negative == pytest.approx(plain * -1.0), "增益只放大正向，负向只吃上限"


def test_scenario5_heavy_user_not_ahead_of_light_user(tmp_path) -> None:
    """场景5：重度（40 事件/天）与轻度（4 事件/天）增速同阶，且不占便宜。"""
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "s5.sqlite3")
    heavy_texts = [f"谢谢你陪我聊天{index}" for index in range(40)]
    light_texts = [f"今天也谢谢你的陪伴，聊得很好，晚安{index}" for index in range(4)]
    for day in range(10):
        for index in range(40):
            store.observe("heavy", "positive", text=heavy_texts[(day + index) % 40])
            clock.advance(90)
        for index in range(4):
            store.observe("light", "positive", text=light_texts[(day + index) % 4])
            clock.advance(90)
        clock.advance(86400 - 44 * 90)
    heavy_gain = store.snapshot("heavy")["affinity"] - 0.1
    light_gain = store.snapshot("light")["affinity"] - 0.1
    assert heavy_gain > 0 and light_gain > 0
    assert heavy_gain <= light_gain * 1.6, (
        f"重度增益 {heavy_gain:.3f} 碾压轻度 {light_gain:.3f}：rhythm 归一失效"
    )
    assert heavy_gain / 400 < light_gain / 40, "话痨的每一句平均效应必须被稀释"


def test_scenario6_absence_no_penalty_and_return_recovers(tmp_path) -> None:
    """场景6：半年不见面一分不扣；回归时新鲜度已回升、步长恢复量级。"""
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "s6.sqlite3")
    # 十日每天 6 条好话：新鲜度深累积但日帽未压满——末位步长是"被 novelty 压扁"的基线。
    _run_days(store, clock, "u1", events_per_day=6, days=10)
    before_leave = store.snapshot("u1")["affinity"]
    # 离场前的末位边际步长（连续同日轰炸后新鲜度已深衰减）——回归对比基线。
    clock.advance(120)
    tail = store.observe("u1", "positive", text=_PRAISES[1])  # 第 61 条
    tail_step = abs(tail - before_leave) * 100.0
    assert 0 < tail_step < 1.0, f"末位步长应已被新鲜度压扁（实得 {tail_step:.3f} 分）"
    before_absence = tail
    clock.advance(180 * 86400)
    assert store.snapshot("u1")["affinity"] == pytest.approx(before_absence), "缺席绝不扣分（在册裁定）"
    clock.advance(600)
    after_return = store.observe("u1", "positive", text="好久不见，谢谢你还在")
    return_step = (after_return - before_absence) * 100.0
    assert return_step > 2.0, "半年回归的首条好话应恢复到正常量级"
    assert return_step > 3.0 * max(tail_step, 1e-9), (
        "回归步长须显著大于离场前被新鲜度压扁的边际步长（novelty 已回升）"
    )


# =========================================================================
# D. 因子与纯函数行为
# =========================================================================


def test_quality_score_orders_signal_types() -> None:
    dismissive = v7_quality_score("嗯", behavior="neutral")
    smalltalk = v7_quality_score("今天天气不错", behavior="neutral")
    sincere = v7_quality_score(
        "谢谢你昨天陪我聊天，辛苦了，后来那件事怎么样了？", behavior="positive", gap_seconds=86400
    )
    apology = v7_quality_score("对不起昨天是我不对，你别生气", behavior="neutral")
    insult = v7_quality_score("你这个蠢货", behavior="insult")
    assert dismissive < 0.02 < smalltalk < sincere
    assert apology > 0.15
    assert insult < -0.3
    assert sincere > 0.4


def test_quality_score_penalizes_repeat_and_reward_context() -> None:
    fresh = v7_quality_score("上次你说的那首歌我又听了，真的太好听了，谢谢你推荐", behavior="positive")
    repeat = v7_quality_score(
        "上次你说的那首歌我又听了，真的太好听了，谢谢你推荐", behavior="positive", repeated_recently=True
    )
    assert repeat < fresh
    assert fresh > 0.4  # 引用前文 + 情绪词双加成


def test_novelty_monotone_with_floor() -> None:
    values = [v7_novelty_factor(n) for n in range(300)]
    assert values[0] == 1.0
    assert all(a >= b for a, b in pairwise(values))
    assert values[-1] == pytest.approx(_V7_NOVELTY_FLOOR)  # 注毒靶①b：floor→0 即红
    assert all(v >= _V7_NOVELTY_FLOOR for v in values)


def test_rhythm_identity_below_reference_and_damping_above() -> None:
    assert v7_rhythm_factor(0.0) == 1.0
    assert v7_rhythm_factor(8.0) == pytest.approx(1.0)
    assert v7_rhythm_factor(16.0) == pytest.approx(0.5)
    assert v7_rhythm_factor(64.0) < v7_rhythm_factor(32.0)


def test_neutral_scale_applied_to_presence_only() -> None:
    assert v7_quality_score("嗯", behavior="neutral") <= 0.012  # ≈1 分/千……量级即"几乎不动"
    text = "我想跟你聊聊最近的项目进展，有一些新的想法想听你的意见"
    engaged = v7_quality_score(text, behavior="neutral")
    same_as_positive = v7_quality_score(text, behavior="positive")
    assert 0 < engaged < 0.15
    assert engaged < same_as_positive, "中性陪伴必须远轻于真情实意（缓温不冒进）"
    assert v7_quality_score("随便骂", behavior="refusal") == 0.0
    assert v7_quality_score("内容无关", behavior="unknown") == 0.0


# =========================================================================
# E. 配置面（逐调用现读；12 键在册；env 回退）
# =========================================================================


def test_settings_read_per_call(tmp_path) -> None:
    """热改口径的证据件：同一 store，下一调用即读到改后的 config 值。"""
    clock = _Clock()
    # 场景隔离：抬走日额度护栏（同 test_daily_effective_caps_fallback_gates_positive
    # 先例）——本锁只判 base_step 逐调用现读，日额度不得挤压第二发的位移。
    config = _v7_config(bot_affinity_daily_move_cap_z=99.0)
    store = DynamicAffinityStore(tmp_path / "percall.sqlite3", clock=clock, config=config)
    slow = store.observe("u1", "positive", text="谢谢你陪我聊天")
    config.bot_affinity_base_step = 0.30  # 三倍步长
    clock.advance(3600)
    fast = store.observe("u1", "positive", text="谢谢你一直陪着我呢")
    step_slow = slow - 0.1
    step_fast = fast - slow
    assert step_fast > step_slow * 2.0, "逐调用现读：改 base_step 下一次 observe 即生效"


def test_settings_env_fallback_when_no_config(tmp_path, monkeypatch) -> None:
    clock = _Clock()
    store = DynamicAffinityStore(tmp_path / "env.sqlite3", clock=clock)
    before = store.snapshot("u1")["affinity"]
    store.observe("u1", "positive", text="谢谢")
    with sqlite3.connect(str(tmp_path / "env.sqlite3")) as connection:
        z_value = connection.execute(
            "SELECT z_latent FROM user_affinity WHERE sender_id='u1'"
        ).fetchone()[0]
    assert z_value is None  # env 无键 → 关态（现行为）
    monkeypatch.setenv("BOT_AFFINITY_V7_ENABLED", "true")
    monkeypatch.setenv("BOT_AFFINITY_BASE_STEP", "not-a-number")  # 非法 → 点名+缺省
    clock2 = _Clock(clock.now)
    store2 = DynamicAffinityStore(tmp_path / "env2.sqlite3", clock=clock2)
    moved = store2.observe("u1", "positive", text="谢谢你陪我聊天")
    assert moved > before
    with sqlite3.connect(str(tmp_path / "env2.sqlite3")) as connection:
        assert connection.execute(
            "SELECT z_latent FROM user_affinity WHERE sender_id='u1'"
        ).fetchone()[0] is not None


def test_twelve_v7_keys_registered_on_config_class() -> None:
    """配置面只读核对：12 枚 v7 键在 Config 真身在册且缺省与设计一致（本席不改 config.py）。

    台账 F-16 **键面**拆轴（2026-10-06 用户裁定）后，日额度一枚键喂两路的状态结束：
    旧键 `bot_affinity_daily_move_cap_z` 只喂评分判据侧、键面缺省与代码缺省**合流**成 0.12；
    展示收紧侧另住新键 `bot_affinity_daily_move_cap_v8_z`（缺省 0.04），本用例一并核。
    """
    from plugins.bot_unified_runtime.config import Config

    instance = Config()
    for field_name, default in _V7_CONFIG_FIELDS:
        assert hasattr(instance, field_name), f"{field_name} 未落 config.py"
        actual = getattr(instance, field_name)
        assert type(actual) is type(default), f"{field_name} 类型漂移"
        if field_name == "bot_affinity_daily_move_cap_z":
            # 键面拆轴后不再需要「键面随 v8 / 代码缺省随 v7」的双脸特例：两面同值 0.12。
            assert actual == _V7_DEFAULT_DAILY_MOVE_CAP_Z, (
                f"评分侧键面缺省漂移：Config {actual!r} != {_V7_DEFAULT_DAILY_MOVE_CAP_Z!r}"
            )
            assert actual != _V8_DEFAULT_DAILY_MOVE_CAP_Z, (
                "日额度两枚键的缺省又并回同值＝键面拆轴回潮"
            )
            continue
        assert actual == default, f"{field_name} 缺省漂移：{actual!r} != {default!r}"

    # v8 收紧侧新键：Config 在册、类型 float、缺省＝展示侧常量，且不读旧键的值。
    assert hasattr(instance, "bot_affinity_daily_move_cap_v8_z"), (
        "bot_affinity_daily_move_cap_v8_z 未落 config.py（三面齐缺第一面）"
    )
    v8_cap = instance.bot_affinity_daily_move_cap_v8_z
    assert type(v8_cap) is float, f"bot_affinity_daily_move_cap_v8_z 类型漂移：{type(v8_cap)!r}"
    assert v8_cap == _V8_DEFAULT_DAILY_MOVE_CAP_Z, (
        f"v8 收紧侧键面缺省漂移：Config {v8_cap!r} != {_V8_DEFAULT_DAILY_MOVE_CAP_Z!r}"
    )


def test_daily_move_cap_key_is_split_between_v7_and_v8(monkeypatch) -> None:
    """F-16 **键面**拆轴锁（2026-10-06 用户裁定：豁免「本波不新建配置键」自律）。

    上一批只拆了**常量面**（`_V7_DEFAULT_DAILY_MOVE_CAP_Z`=0.12 / `_V8_DEFAULT_...`=0.04），
    键名没分：一枚 `bot_affinity_daily_move_cap_z` 同时喂 v7 与 v8 两条评分路。
    病灶＝那枚键在 `.env` 里显式在场（钉 0.04）时，两路一起读它、代码缺省永不现形
    ⇒「同一天四条好评把滚动 24h 预算耗光后，一句辱骂实发 Δz 恰好 0.0」这条生产病理
    消不掉（`tests/test_affinity_display_vs_scoring_caps.py` 行为腿复现的正是它）。
    目标语义＝两枚键并存、各读各的：v7 评分读旧键（缺省 0.12）、v8 收紧侧读新键
    `bot_affinity_daily_move_cap_v8_z`（缺省 0.04）。
    """
    monkeypatch.delenv("BOT_AFFINITY_DAILY_MOVE_CAP_Z", raising=False)
    monkeypatch.delenv("BOT_AFFINITY_DAILY_MOVE_CAP_V8_Z", raising=False)

    # 腿 ①：只给旧键交值 ⇒ v7 必须照吃（拆轴后同样成立的一半）。
    only_old = _v7_config(bot_affinity_daily_move_cap_z=0.30)
    assert resolve_v7_settings(only_old).daily_move_cap_z == pytest.approx(0.30)
    # 腿 ②：v8 收紧侧**不该**吃旧键——今天它吃了 ⇒ 本腿 RED。
    assert resolve_v8_settings(only_old).daily_move_cap_z == pytest.approx(
        _V8_DEFAULT_DAILY_MOVE_CAP_Z
    ), "v8 侧读了 v7 那枚旧键＝两路同键未拆（F-16 键面另账未闭合）"

    # 腿 ③：只给新键交值 ⇒ v8 必须吃它（今天无人读这把键 ⇒ 本腿 RED）；v7 绝不跟吃。
    only_new = _v7_config(bot_affinity_daily_move_cap_v8_z=0.02)
    assert resolve_v8_settings(only_new).daily_move_cap_z == pytest.approx(
        0.02
    ), "新键无人读＝v8 侧仍挂在旧键上"
    assert resolve_v7_settings(only_new).daily_move_cap_z == pytest.approx(
        _V7_DEFAULT_DAILY_MOVE_CAP_Z
    ), "v7 评分侧吃了 v8 那枚键＝混轴回潮"

    # 腿 ④：两枚键同时在座且值不同 ⇒ 各取各的，谁也不覆盖谁。
    both = _v7_config(bot_affinity_daily_move_cap_z=0.30, bot_affinity_daily_move_cap_v8_z=0.02)
    assert resolve_v7_settings(both).daily_move_cap_z == pytest.approx(0.30)
    assert resolve_v8_settings(both).daily_move_cap_z == pytest.approx(0.02)


def test_quality_weights_env_json_parsed(tmp_path) -> None:
    clock = _Clock()
    config = _v7_config(
        bot_affinity_quality_weights='{"w1":0,"w2":0,"w3":1,"w4":0,"w5":0}',
        # 场景隔离：抬走日额度护栏——本锁只判单事件负向帽×γ 的精确值。
        bot_affinity_daily_move_cap_z=99.0,
    )
    store = DynamicAffinityStore(tmp_path / "weights.sqlite3", clock=clock, config=config)
    settings = resolve_v7_settings(config)
    assert settings.quality_weights == pytest.approx((0.0, 0.0, 1.0, 0.0, 0.0))
    # 情绪权重独占：辱骂步长顶到负向上限（v8：帽后乘 γ，基数档处实发 0.10×γ）
    store.observe("u1", "insult", text="你就是个蠢货")
    with sqlite3.connect(str(tmp_path / "weights.sqlite3")) as connection:
        z_value = float(
            connection.execute(
                "SELECT z_latent FROM user_affinity WHERE sender_id='u1'"
            ).fetchone()[0]
        )
    z0 = v7_display_fraction_to_z(0.1)
    assert z0 - z_value == pytest.approx(
        0.10 * v8_marginal_gain(z0, _V8_HALF_DEFAULT), abs=1e-6
    )


# =========================================================================
# F. 红线与滚字（§六.3 红线自证 + 设计 §2.3 另修项）
# =========================================================================

_TIER_INSTRUCTION_HOSTILE_BANNED = (
    "冷漠", "抗拒", "愤怒", "恶心", "肮脏", "低贱", "敌视", "厌恶",
    "鄙视", "憎恨", "憎恶", "仇视", "冷酷", "轻蔑", "讨厌",
)


def test_red_lines_verbatim_all_four() -> None:
    """八档态度全文与 _TIER_RED_LINES 逐条不变（在册四条款的钉死锁）。"""
    assert len(_TIER_RED_LINES) == 4
    assert "任何档位都不强硬、不粗鲁、不攻击、不辱骂、不贬低、不谴责" in _TIER_RED_LINES[0]
    assert "负向档位只是“距离感”：不表现出任何敌意" in _TIER_RED_LINES[1]
    assert "亲密与情色内容只发生在私聊" in _TIER_RED_LINES[2]
    assert "任何档位都不辱骂、不冷暴力弃聊" in _TIER_RED_LINES[3]
    assert tuple(tier_id for tier_id, _n, _i in _ATTITUDE_TIERS) == (-4, -3, -2, -1, 0, 1, 2, 3)
    assert [name for _id, name, _i in _ATTITUDE_TIERS] == [
        "初识", "生疏", "微凉", "稍淡", "友善（基准）", "亲近", "挚友", "独一份",
    ]


def test_no_hostile_word_at_any_z_value() -> None:
    """§六.3 新锁：任何 z 取值（全值域 400 点扫描，含 tanh 全域与 ±98.5 钳位）
    注入文本的档位指令段与过渡语段都不得出现敌意/攻击措辞；红线条款恒在。"""
    z_bound = math.atanh(0.985)
    seen_tiers: set[int] = set()
    for step in range(401):
        z = -z_bound + (2 * z_bound) * step / 400.0
        fraction = v7_z_to_display_fraction(z)
        attitude = attitude_for_affinity(fraction)
        transition = linear_transition_for_affinity(fraction)
        tier = tier_for_affinity(fraction)
        seen_tiers.add(tier)
        instruction = _ATTITUDE_TIERS[[t[0] for t in _ATTITUDE_TIERS].index(tier)][2]
        for banned in _TIER_INSTRUCTION_HOSTILE_BANNED:
            assert banned not in instruction, f"z={z:.4f} 档 {tier} 指令含敌意词 {banned}"
            assert banned not in transition, f"z={z:.4f} 过渡语含敌意词 {banned}"
        assert "不攻击" in attitude and "不辱骂" in attitude, "红线注入段全值域恒在"
    assert seen_tiers == set(range(-4, 4)), "全值域覆盖八档且无跳档缺失"


def test_tier_boundaries_do_not_jump() -> None:
    """八档边界不跳变：档位映射沿 z 单调不减；边界两侧 0.1 分差内无第三种措辞。"""
    z_bound = math.atanh(0.985)
    previous_tier = -4
    for step in range(1001):
        z = -z_bound + (2 * z_bound) * step / 1000.0
        tier = tier_for_affinity(v7_z_to_display_fraction(z))
        assert tier >= previous_tier, "z 增大时档位必须单调不减（无回跳跳变）"
        previous_tier = tier


def test_gun_word_action_variants_not_insult() -> None:
    """D3-6：「滚」辱骂判定收紧——动作词与第一人称不中招，驱逐语照打。"""
    for text in (
        "一个翻滚躲开了攻击", "滚动播放", "在地上打滚", "滚雪球效应",
        "我先滚了哈", "滚落山崖的石头", "水滚了", "汤圆滚烂了",
    ):
        assert classify_behavior(text) != "insult", text
    for text in ("滚！", "你给我滚", "快滚", "滚开", "滚蛋", "你滚出去", "都给我滚"):
        assert classify_behavior(text) == "insult", text
    assert classify_behavior("滚瓜烂熟") == "neutral"  # 存量锁复证


def test_responded_to_question_hook_changes_step(tmp_path) -> None:
    clock = _Clock()
    store = _v7_store(tmp_path, clock, "resp.sqlite3")
    answered = store.observe(
        "u1", "neutral", text="是关于昨晚那件事的补充说明，我想了想还是觉得要先说清楚",
        responded_to_question=True,
    )
    clock.advance(3600)
    ignored = store.observe(
        "u1", "neutral", text="是关于昨晚那件事的补充说明，我想了想还是觉得要先说清楚",
        responded_to_question=False,
    )
    step_answered = answered - 0.1
    step_ignored = ignored - answered
    assert step_answered > 0
    assert 0 < step_ignored < step_answered, "未作答同一文本步长必须更小"
