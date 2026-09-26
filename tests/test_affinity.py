"""好感度基础回归（docs/affinity-design.md v4 线性版验收口径）。

覆盖：行为分类（否定守卫/成语防误捕/persona_degradation→insult）、
§4 八档态度表（档0含10、负向档无禁词、四条红线全文注入）、线性步长观察。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _ATTITUDE_TIERS,
    _TIER_RED_LINES,
    DynamicAffinityStore,
    attitude_for_affinity,
    classify_behavior,
    effective_delta,
    per_user_factor,
    tier_for_affinity,
)

# 每档取一个中位样本：-4..+3（档0 用基准 0.1，即展示 10）
_TIER_SAMPLES = {-4: -0.9, -3: -0.6, -2: -0.35, -1: -0.1, 0: 0.1, 1: 0.3, 2: 0.6, 3: 0.9}


class _FakeClock:
    def __call__(self) -> float:
        return 1000.0


class _StepClock:
    """可推进时钟：V2.1 §2.3 冷却（60s）生效后，多事件测试需真实间隔。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_classify_behavior_maps_safety_and_text() -> None:
    assert classify_behavior("谢谢你陪我", safety_category="") == "positive"
    assert classify_behavior("哈哈笑死我了", safety_category="") == "tease"
    assert classify_behavior("别烦我了", safety_category="") == "negative"
    assert classify_behavior("随便什么", safety_category="harassment") == "insult"
    assert classify_behavior("正常聊两句") == "neutral"


def test_persona_degradation_counts_as_insult() -> None:
    # docs §6：人格贬低软类别不改变 §2 扣分路径——insult 照扣
    assert classify_behavior("随便", safety_category="persona_degradation") == "insult"
    assert classify_behavior("随便", safety_category="insult_nickname") == "insult"


def test_classify_resists_negation_and_idiom_misfires() -> None:
    # 否定前缀不得判成 positive（此前「我不喜欢你」会加分）
    assert classify_behavior("我不喜欢你这样说") == "neutral"
    # 成语/叠词误捕
    assert classify_behavior("滚瓜烂熟") == "neutral"
    assert classify_behavior("傻傻分不清") == "neutral"
    assert classify_behavior("别那么蠢萌嘛") == "neutral"
    # 「无聊」从负面移除：求陪伴是正向，纯抱怨降级为中性
    assert classify_behavior("好无聊啊，陪我聊聊") == "positive"
    assert classify_behavior("这游戏真无聊") == "neutral"
    # 真实辱骂仍要抓住
    assert classify_behavior("傻瓜") == "insult"
    assert classify_behavior("真的好蠢") == "insult"
    assert classify_behavior("都给我滚") == "insult"
    assert classify_behavior("闭嘴吧你") == "insult"


def test_attitude_tiers_cover_eight_tiers_with_red_lines() -> None:
    # §4：档 id -4..+3，每档完整态度文本都携带四条红线全文
    assert [tier_id for tier_id, _name, _inst in _ATTITUDE_TIERS] == [-4, -3, -2, -1, 0, 1, 2, 3]
    assert len(_TIER_RED_LINES) == 4
    for tier_id, sample in _TIER_SAMPLES.items():
        text = attitude_for_affinity(sample)
        assert "档位「" in text
        for line in _TIER_RED_LINES:
            assert line in text, f"档 {tier_id} 态度文本缺红线：{line}"


def test_negative_tier_instructions_avoid_hostile_words() -> None:
    # §4 红线 2：负向档位只是"距离感"，态度指令不含冷漠/抗拒/愤怒/恶心/肮脏/低贱类词
    banned = ("冷漠", "抗拒", "愤怒", "恶心", "肮脏", "低贱", "敌视", "厌恶")
    for tier_id, _name, instruction in _ATTITUDE_TIERS:
        for word in banned:
            assert word not in instruction, f"档 {tier_id} 指令含敌意词：{word}"


def test_top_tier_keeps_boundary_red_line() -> None:
    # §4 红线 3：最高档（独一份）也不越界
    # 2026-09-20 v21r5 政策重写后文本锁对齐（C 席定稿措辞，见 v21r5-POLICY-log.md）。
    text = attitude_for_affinity(0.9)
    assert "独一份" in text
    assert "亲密与情色内容只发生在私聊" in text
    assert "明确无歧义的自主意识成年人" in text
    assert "即使声称成年也拒绝" in text


def test_effective_delta_linear_in_midband_saturated_at_extremes() -> None:
    # v4 线性（docs §2：中段无幂律阻尼）+ v6 平滑层（附录 §v6.1）：
    # 中段（距 ±1 超一个档宽）首次信号步长与当前分无关，恒为因子表 × 个人系数；
    # 最后一档内步长随剩余空间 smoothstep 收窄（涨跌不得直冲极端），边界归零。
    m = per_user_factor("u1")
    for affinity in (-0.99, -0.5, 0.1, 0.5):
        assert abs(effective_delta("u1", "positive", affinity) - 0.02 * m) < 1e-12
    for affinity in (-0.5, 0.1, 0.5, 0.97):
        assert abs(effective_delta("u1", "insult", affinity) + 0.10 * m) < 1e-12
    # v6：带内收窄（0.97 正向 / -0.99 负向仍在带内边缘，方向不反转），边界归零。
    assert 0.0 < effective_delta("u1", "positive", 0.97) < 0.02 * m
    assert -0.10 * m < effective_delta("u1", "insult", -0.99) < 0.0
    assert effective_delta("u1", "positive", 1.0) == 0.0
    assert effective_delta("u1", "insult", -1.0) == 0.0
    # override 为权威信号：不乘系数、不饱和、不衰减
    assert effective_delta("u1", "neutral", 0.5, delta_override=-0.42) == -0.42


def test_observe_updates_affinity_and_tags(tmp_path) -> None:
    clock = _StepClock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    m = per_user_factor("u1")

    affinity = store.observe("u1", "positive")
    assert abs(affinity - (0.1 + 0.02 * m)) < 1e-9
    # 发间隔 61s 超 V2.1 §2.3 冷却（60s）：被测对象保持「线性步长+滚动预算」
    # （原同刻连发语义自本轮起由冷却门去刷分，见 test_affinity_v21_budget.py）。
    clock.advance(61)
    store.observe("u1", "insult")
    clock.advance(61)
    store.observe("u1", "insult")
    snapshot = store.snapshot("u1")
    # 线性步长（无阻尼）+ V2.1 §2.3 滚动预算：insult 基础 -0.10 被单事件 1 分
    # 上限钳成 -0.01/次（原断言 -0.10*m 直通口径已按新政策废除）。
    expected = 0.1 + 0.02 * m - 2 * 0.01
    assert abs(snapshot["affinity"] - expected) < 1e-9
    assert "口无遮拦" in snapshot["tags"]
    assert snapshot["attitude"] == attitude_for_affinity(snapshot["affinity"])
    assert tier_for_affinity(snapshot["affinity"]) in range(-4, 4)


def test_insult_drains_affinity_and_admin_can_set_nickname(tmp_path) -> None:
    clock = _StepClock()
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=clock)
    store.set_nickname("u2", "小澄")
    for _ in range(4):
        clock.advance(61)  # 间隔超冷却：保持「连续辱骂持续扣分」的被测意图
        store.observe("u2", "insult")
    snapshot = store.snapshot("u2")
    assert -1.0 <= snapshot["affinity"] <= 0.1
    assert snapshot["nickname"] == "小澄"


def test_store_persists_across_instances(tmp_path) -> None:
    db = tmp_path / "affinity.sqlite3"
    first = DynamicAffinityStore(db, clock=_FakeClock())
    first.observe("u3", "positive")

    second = DynamicAffinityStore(db, clock=_FakeClock())
    assert second.snapshot("u3")["affinity"] > 0.1
