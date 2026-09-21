"""V2.1 好感度急性风险修复回归（W1 席，规格合同节选）。

规格：docs/design/backend-v2-product-extensions.md §2.2/§2.3、
验收矩阵 V21-AFFINITY-001（「100 次路由/拒答不扣分、一晚限额、跨群/重启不绕过」）。

覆盖：
①拒答≠辱骂：safety_action="refuse" 且无类别证据 → 新行为 "refusal"，
  关系 delta=0，不计 insult 计数/标签（对人的直接辱骂类别照罚）；
②多因素乘积钳制 [0.5, 1.25]（§2.3 factor_product_min/max）；
③持久化滚动预算（affinity_delta_log，纯时间窗聚合）：单事件负向 ≤1 分、
  6h 损失 ≤2 分、24h 损失 ≤4 分、24h 全局增益 ≤3 分；override 一律过预算；
  重启（重开 store）与跨午夜均不重置；>48h 行 prune；
④observe_points 分值唯一适配器（points ÷100 转内部值）+ poke 来源专项
  24h 预算（source_cap_24h_points）；
⑤refusal 行为对 bot 心情为中性（mood.observe_interaction）。

全部离线 tmp_path + 注入时钟；不触碰生产库（历史误扣补偿属 S12 重放）。
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from plugins.bot_unified_runtime.character.affinity import (
    _FACTOR_PRODUCT_MAX,
    _FACTOR_PRODUCT_MIN,
    DynamicAffinityStore,
    classify_behavior,
    effective_delta,
    per_user_factor,
)

_DAY_SECONDS = 86400.0


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


def _insult_count(db_path: object, sender_id: str) -> int:
    with sqlite3.connect(str(db_path)) as connection:
        row = connection.execute(
            "SELECT insult_count FROM user_affinity WHERE sender_id = ?", (sender_id,)
        ).fetchone()
    return int(row[0]) if row else 0


def _log_rows(db_path: object) -> list[tuple]:
    with sqlite3.connect(str(db_path)) as connection:
        return connection.execute(
            "SELECT sender_id, applied_at, delta, source FROM affinity_delta_log"
            " ORDER BY applied_at"
        ).fetchall()


# ---------------------------------------------------------------------------
# ① A：拒答解耦——refuse 且无类别证据 → refusal，分毫不降、insult 计数不增
# ---------------------------------------------------------------------------

def test_refusal_without_category_evidence_is_not_insult() -> None:
    # 安全拒答（sexual/graphic_violence/political_sensitive 等主题类都给 refuse）
    # 只是模型拒绝内容，不是对人的攻击（规格 §2.2：拒答与路由失败不能证明辱骂）。
    assert classify_behavior("讲个露骨的故事", safety_category="sexual", safety_action="refuse") == "refusal"
    assert classify_behavior("随便什么", safety_action="refuse") == "refusal"
    assert classify_behavior("随便什么", safety_category="", safety_action="refuse") == "refusal"


def test_100_refusals_leave_affinity_and_insult_count_untouched(tmp_path) -> None:
    clock = _Clock()
    db = tmp_path / "affinity.sqlite3"
    store = _store(tmp_path, clock)
    base = store.snapshot("u1")["affinity"]
    for index in range(100):
        behavior = classify_behavior(
            f"第{index}条测试性话题消息",
            safety_category="sexual" if index % 2 else "",
            safety_action="refuse",
        )
        store.observe("u1", behavior)
    snapshot = store.snapshot("u1")
    assert snapshot["affinity"] == pytest.approx(base), "100 次拒答不得扣一分"
    assert _insult_count(db, "u1") == 0, "拒答不计入 insult 计数"
    assert snapshot["tags"] == [], "拒答不打任何印象标签"


def test_direct_abuse_category_still_punished_as_insult(tmp_path) -> None:
    # 对人的直接类别证据（骚扰/辱骂昵称/人格贬低）照走 insult 扣分路径；
    # 单事件负向上限 1 分（§2.3 max_negative_per_event）。
    assert classify_behavior("x", safety_category="harassment", safety_action="refuse") == "insult"
    assert classify_behavior("x", safety_category="insult_nickname") == "insult"
    assert classify_behavior("x", safety_category="persona_degradation") == "insult"
    clock = _Clock()
    store = _store(tmp_path, clock)
    store.observe("u1", "insult")
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.1 - 0.01, abs=1e-9)
    assert _insult_count(tmp_path / "affinity.sqlite3", "u1") == 1


# ---------------------------------------------------------------------------
# ⑨ refusal 对 bot 心情为中性
# ---------------------------------------------------------------------------

def test_refusal_behavior_is_neutral_for_mood(tmp_path) -> None:
    from plugins.bot_unified_runtime.character.mood import BotMoodStore

    clock = _Clock()
    mood = BotMoodStore(tmp_path / "mood.sqlite3", clock=clock)
    before = mood.snapshot()
    after = mood.observe_interaction("refusal", [])
    assert after.valence == pytest.approx(before.valence), "refusal 不得压低心情"
    assert after.arousal == pytest.approx(before.arousal)
    # 负对照：insult 确实会压低 valence（证明断言非空转）。
    worse = mood.observe_interaction("insult", [])
    assert worse.valence < before.valence


# ---------------------------------------------------------------------------
# ② B：多因素乘积钳制 [0.5, 1.25]
# ---------------------------------------------------------------------------

def test_factor_product_clamped_to_spec_bounds() -> None:
    assert _FACTOR_PRODUCT_MIN == 0.5
    assert _FACTOR_PRODUCT_MAX == 1.25
    m = per_user_factor("u1")
    # 上界：暖词密文本 × 长相处 × 极好第一印象 × 极好心情，乘积远超 1.25 → 钳到 1.25
    hot = effective_delta(
        "u1",
        "positive",
        0.5,
        text="谢谢！麻烦你啦，真是太棒了，厉害，好棒，抱抱",
        first_impression=1.0,
        interaction_count=0,
        companion_days=365.0,
        mood_valence=1.0,
    )
    assert hot == pytest.approx(0.02 * 1.25, abs=1e-12)
    assert hot < 0.02 * m * 1.4 * 1.15 * 1.3 * 1.15, "未钳制时的乘积确实更大（钳制生效前提）"


def test_factor_product_clamp_bounds_bind_via_extreme_factors(monkeypatch) -> None:
    import plugins.bot_unified_runtime.domains.chat_reply.character.affinity as affinity_module

    # 极端因子注入：单因子拉到 10 / 0.1，乘积必然越界，验证上下界都咬合。
    monkeypatch.setattr(affinity_module, "pleasantness_factor", lambda text, behavior: 10.0)
    assert effective_delta("u1", "positive", 0.5) == pytest.approx(0.02 * 1.25, abs=1e-12)
    monkeypatch.setattr(affinity_module, "pleasantness_factor", lambda text, behavior: 0.1)
    assert effective_delta("u1", "positive", 0.5) == pytest.approx(0.02 * 0.5, abs=1e-12)
    assert effective_delta("u1", "insult", 0.5) == pytest.approx(-0.10 * 0.5, abs=1e-12)


# ---------------------------------------------------------------------------
# ③ C：持久化滚动预算
# ---------------------------------------------------------------------------

def test_single_event_and_rolling_loss_caps(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # 单事件 ≤1 分：insult 基础 -10 分只落 -1 分。
    first = store.observe("u1", "insult")
    assert first == pytest.approx(0.09, abs=1e-9)
    # 连续辱骂（V2.1 冷却：每发间隔 61s，被测对象=预算窗而非冷却）：6h 内总损失
    # ≤2 分（第 3 条起记 0）。
    for _ in range(9):
        clock.advance(61)
        store.observe("u1", "insult")
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.08, abs=1e-9)


def test_loss_budget_rolls_without_midnight_reset(tmp_path) -> None:
    # 真实本地日界时间线（每批 2 发、发间隔 61s 超冷却，不触碰旧次数日上限，
    # 隔离验证滚动预算）：18:00 用掉 6h 窗口 2 分 → 跨午夜 01:00 回补（6h 滑出、
    # 24h 剩 2 分）→ 08:00 24h 窗口两批占满（4 分封顶）→ 19:00 最早一批滚出
    # 24h 窗，自然回补。
    clock = _Clock(start=time.mktime((2026, 1, 1, 18, 0, 0, 0, 0, -1)))
    store = _store(tmp_path, clock)
    for _ in range(2):
        store.observe("u1", "insult")
        clock.advance(61)
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.08, abs=1e-9)

    clock.advance(7 * 3600)  # 次日 01:00：跨午夜，滚动预算不重置
    for _ in range(2):
        store.observe("u1", "insult")
        clock.advance(61)
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.06, abs=1e-9)

    clock.advance(7 * 3600)  # 08:00：24h 内累计 4 分封顶
    for _ in range(2):
        store.observe("u1", "insult")
        clock.advance(61)
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.06, abs=1e-9)

    clock.advance(11 * 3600)  # 19:00：最早一批滚出 24h 窗，按时间窗回补 2 分
    for _ in range(2):
        store.observe("u1", "insult")
        clock.advance(61)
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.04, abs=1e-9)


def test_budget_survives_store_reopen(tmp_path) -> None:
    clock = _Clock()
    db = tmp_path / "affinity.sqlite3"
    first = DynamicAffinityStore(db, clock=clock)
    first.observe("u1", "insult")
    clock.advance(61)
    first.observe("u1", "insult")
    assert first.snapshot("u1")["affinity"] == pytest.approx(0.08, abs=1e-9)

    # 关店重开（同 db 新建实例 = 模拟重启）：6h 预算已耗尽，继续辱骂零扣分。
    second = DynamicAffinityStore(db, clock=clock)
    for _ in range(5):
        clock.advance(61)
        second.observe("u1", "insult")
    assert second.snapshot("u1")["affinity"] == pytest.approx(0.08, abs=1e-9)

    # 增益侧同理：poke 来源 24h 专项预算跨重启延续。
    second.observe_points("u2", 0.5, behavior="positive", source="poke", source_cap_24h_points=0.5)
    clock.advance(61)
    second.observe_points("u2", 0.5, behavior="positive", source="poke", source_cap_24h_points=0.5)
    assert second.snapshot("u2")["affinity"] == pytest.approx(0.105, abs=1e-9)
    third = DynamicAffinityStore(db, clock=clock)
    clock.advance(61)
    third.observe_points("u2", 0.5, behavior="positive", source="poke", source_cap_24h_points=0.5)
    assert third.snapshot("u2")["affinity"] == pytest.approx(0.105, abs=1e-9), "重启后 poke 仍受 24h 上限约束"


def test_budget_not_reset_at_midnight(tmp_path) -> None:
    clock = _Clock(start=time.mktime((2026, 1, 1, 23, 30, 0, 0, 0, -1)))
    db = tmp_path / "affinity.sqlite3"
    store = DynamicAffinityStore(db, clock=clock)
    # 23:30 用尽 6h 损失预算（-2 分；发间隔 61s 超冷却）。
    for _ in range(5):
        store.observe("u1", "insult")
        clock.advance(61)
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.08, abs=1e-9)
    # 跨午夜（次日 01:30）：滚动时间窗不重置，一分不多扣。
    clock.advance(2 * 3600)
    for _ in range(5):
        store.observe("u1", "insult")
        clock.advance(61)
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.08, abs=1e-9)

    # 增益侧跨午夜同理：24h 全局增益 3 分用尽后不再加。
    for _ in range(3):
        store.observe_points("u2", 1.0, source="probe")
        clock.advance(61)
    assert store.snapshot("u2")["affinity"] == pytest.approx(0.13, abs=1e-9)
    clock.advance(2 * 3600)
    store.observe_points("u2", 1.0, source="probe")
    assert store.snapshot("u2")["affinity"] == pytest.approx(0.13, abs=1e-9)


def test_delta_override_also_passes_budget(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # 负向 override：单事件 1 分封顶（旧政策 override 直通，-50 分一击成立 → 已废除）。
    assert store.observe("u1", "neutral", delta_override=-0.50) == pytest.approx(0.09, abs=1e-9)
    # 正向 override：24h 全局增益 3 分封顶。
    assert store.observe("u2", "neutral", delta_override=2.0) == pytest.approx(0.13, abs=1e-9)


def test_positive_gain_capped_at_3_points_per_24h(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    last = 0.1
    for _ in range(20):
        clock.advance(61)  # V2.1 冷却：间隔超 60s，被测对象=24h 增益预算
        last = store.observe("u1", "positive")
    assert last == pytest.approx(0.13, abs=1e-9), "24h 全局增益 ≤3 分"


def test_delta_log_schema_prune_and_bounds(tmp_path) -> None:
    clock = _Clock()
    db = tmp_path / "affinity.sqlite3"
    store = _store(tmp_path, clock)
    with sqlite3.connect(str(db)) as connection:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index')"
            )
        }
    assert "affinity_delta_log" in names
    assert "idx_affinity_delta_log_sender_time" in names

    # 落日志：每次被预算放行的增量都带来源落一行。
    store.observe_points("u1", 0.5, source="poke")
    rows = _log_rows(db)
    assert len(rows) == 1
    assert rows[0][0] == "u1" and rows[0][3] == "poke"
    assert rows[0][2] == pytest.approx(0.005)

    # >48h 行 prune：写入时顺手清理不再参与任何窗口的旧行。
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT INTO affinity_delta_log (sender_id, applied_at, delta, source)"
            " VALUES ('ghost', ?, -0.01, '')",
            (clock.now - 49 * 3600,),
        )
    clock.advance(61)
    store.observe("u1", "insult")  # 触发一次预算写路径（间隔超冷却，确保真落行）
    assert all(row[0] != "ghost" for row in _log_rows(db)), ">48h 行必须被 prune"


# ---------------------------------------------------------------------------
# ④ D：observe_points 分值唯一适配器 + poke 来源专项预算
# ---------------------------------------------------------------------------

def test_observe_points_normalizes_legacy_points(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # 规格 §2.2 normalize_legacy_points：points（展示分）÷100 转内部值。
    # 0.5 分 = +0.005 内部值（旧 poke 缺陷会把 0.5 当内部值 → 一戳 +50 分）。
    after = store.observe_points(
        "u1", 0.5, behavior="positive", source="poke", source_cap_24h_points=0.5
    )
    assert after == pytest.approx(0.105, abs=1e-9)
    # 来源专项 24h 预算：poke 24h 到 daily_max 后不再加（间隔超冷却，被测对象=专项预算）。
    clock.advance(61)
    again = store.observe_points(
        "u1", 0.5, behavior="positive", source="poke", source_cap_24h_points=0.5
    )
    assert again == pytest.approx(0.105, abs=1e-9)


def test_poke_source_cap_rolls_with_24h_window(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    for _ in range(3):
        clock.advance(61)  # 发间隔超冷却，被测对象=来源专项预算
        store.observe_points("u1", 0.2, behavior="positive", source="poke", source_cap_24h_points=0.5)
    # 0.2×2=0.4 分后，第 3 次只剩 0.1 分额度。
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.1 + 0.005, abs=1e-9)
    # 24h 滑过：专项预算整窗回补。
    clock.advance(_DAY_SECONDS + 1)
    store.observe_points("u1", 0.2, behavior="positive", source="poke", source_cap_24h_points=0.5)
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.1 + 0.007, abs=1e-9)


def test_source_cap_never_lifts_global_gain_budget(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    # 全局增益预算先被别的来源耗尽（3 分；间隔超冷却）。
    for _ in range(3):
        clock.advance(61)
        store.observe_points("u1", 1.0, source="other")
    # 来源专项额度还剩很多，但全局增益 24h 封顶仍兜底。
    clock.advance(61)
    store.observe_points("u1", 0.5, source="poke", source_cap_24h_points=5.0)
    assert store.snapshot("u1")["affinity"] == pytest.approx(0.13, abs=1e-9)


def test_observe_points_returns_updated_affinity_and_mirrors_group(tmp_path) -> None:
    clock = _Clock()
    store = _store(tmp_path, clock)
    result = store.observe_points(
        "u1", 0.5, behavior="positive", source="poke", group_id="g1", display_name="阿澄"
    )
    assert result == pytest.approx(0.105, abs=1e-9)
    assert store.snapshot("u1")["affinity"] == pytest.approx(result)
    rows = store.leaderboard("g1")
    assert len(rows) == 1 and rows[0]["sender_id"] == "u1"
