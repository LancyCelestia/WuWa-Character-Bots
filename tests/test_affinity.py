from __future__ import annotations

from plugins.bot_unified_runtime.character.affinity import (
    DynamicAffinityStore,
    attitude_for_affinity,
    classify_behavior,
    effective_delta,
    per_user_factor,
)


class _FakeClock:
    def __call__(self) -> float:
        return 1000.0


def test_classify_behavior_maps_safety_and_text() -> None:
    assert classify_behavior("谢谢你陪我", safety_category="") == "positive"
    assert classify_behavior("哈哈笑死我了", safety_category="") == "tease"
    assert classify_behavior("别烦我了", safety_category="") == "negative"
    assert classify_behavior("随便什么", safety_category="harassment") == "insult"
    assert classify_behavior("正常聊两句") == "neutral"


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


def test_attitude_tiers_are_ordered_and_never_insulting() -> None:
    assert "绝不辱骂" in attitude_for_affinity(0.1)
    assert "严厉" in attitude_for_affinity(0.1)
    assert "亲近" in attitude_for_affinity(0.9)
    assert "友善" in attitude_for_affinity(0.6)
    assert "客气" in attitude_for_affinity(0.3)


def test_observe_updates_affinity_and_tags(tmp_path) -> None:
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_FakeClock())
    m = per_user_factor("u1")

    affinity = store.observe("u1", "positive")
    assert abs(affinity - (0.1 + 0.02 * m)) < 1e-9
    store.observe("u1", "insult")
    store.observe("u1", "insult")
    snapshot = store.snapshot("u1")
    # 第 1 次 insult 在全额区；第 2 次已在近极值区，步长按幂律衰减，最后 clamp ≥0
    x2 = 0.1 + 0.02 * m - 0.10 * m
    expected = max(0.0, x2 + effective_delta("u1", "insult", x2))
    assert abs(snapshot["affinity"] - expected) < 1e-9
    assert "口无遮拦" in snapshot["tags"]
    assert snapshot["attitude"] == attitude_for_affinity(snapshot["affinity"])


def test_insult_drains_affinity_and_admin_can_set_nickname(tmp_path) -> None:
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_FakeClock())
    store.set_nickname("u2", "小澄")
    for _ in range(4):
        store.observe("u2", "insult")
    snapshot = store.snapshot("u2")
    assert 0.0 <= snapshot["affinity"] <= 0.1
    assert snapshot["nickname"] == "小澄"


def test_store_persists_across_instances(tmp_path) -> None:
    db = tmp_path / "affinity.sqlite3"
    first = DynamicAffinityStore(db, clock=_FakeClock())
    first.observe("u3", "positive")

    second = DynamicAffinityStore(db, clock=_FakeClock())
    assert second.snapshot("u3")["affinity"] > 0.1
