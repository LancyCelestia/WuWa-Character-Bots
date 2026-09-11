"""好感度基础回归（docs/affinity-design.md v4 线性版验收口径）。

覆盖：行为分类（否定守卫/成语防误捕/persona_degradation→insult）、
§4 八档态度表（档0含10、负向档无禁词、四条红线全文注入）、线性步长观察。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.character.affinity import (
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
    text = attitude_for_affinity(0.9)
    assert "独一份" in text
    assert "绝不出现性、R-18、引导上床类内容" in text


def test_effective_delta_is_linear() -> None:
    # v4 线性：步长与当前分无关（无幂律阻尼），恒为因子表 × 个人系数
    m = per_user_factor("u1")
    for affinity in (-0.99, -0.5, 0.1, 0.5, 0.97):
        assert abs(effective_delta("u1", "positive", affinity) - 0.02 * m) < 1e-12
        assert abs(effective_delta("u1", "insult", affinity) + 0.10 * m) < 1e-12
    # override 为权威信号：不乘系数、不衰减
    assert effective_delta("u1", "neutral", 0.5, delta_override=-0.42) == -0.42


def test_observe_updates_affinity_and_tags(tmp_path) -> None:
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_FakeClock())
    m = per_user_factor("u1")

    affinity = store.observe("u1", "positive")
    assert abs(affinity - (0.1 + 0.02 * m)) < 1e-9
    store.observe("u1", "insult")
    store.observe("u1", "insult")
    snapshot = store.snapshot("u1")
    # 线性步长（无阻尼）：每步 = 因子表 × m(uid)，写入路径 clamp 到 [-1,1]
    x2 = 0.1 + 0.02 * m - 0.10 * m
    expected = max(-1.0, x2 - 0.10 * m)
    assert abs(snapshot["affinity"] - expected) < 1e-9
    assert "口无遮拦" in snapshot["tags"]
    assert snapshot["attitude"] == attitude_for_affinity(snapshot["affinity"])
    assert tier_for_affinity(snapshot["affinity"]) in range(-4, 4)


def test_insult_drains_affinity_and_admin_can_set_nickname(tmp_path) -> None:
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_FakeClock())
    store.set_nickname("u2", "小澄")
    for _ in range(4):
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
