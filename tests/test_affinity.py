from __future__ import annotations

from plugins.bot_unified_runtime.character.affinity import (
    DynamicAffinityStore,
    attitude_for_affinity,
    classify_behavior,
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


def test_attitude_tiers_are_ordered_and_never_insulting() -> None:
    assert "绝不辱骂" in attitude_for_affinity(0.1)
    assert "严厉" in attitude_for_affinity(0.1)
    assert "亲近" in attitude_for_affinity(0.9)
    assert "友善" in attitude_for_affinity(0.6)
    assert "客气" in attitude_for_affinity(0.3)


def test_observe_updates_affinity_and_tags(tmp_path) -> None:
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_FakeClock())

    affinity = store.observe("u1", "positive")
    assert affinity > 0.5
    store.observe("u1", "insult")
    store.observe("u1", "insult")
    snapshot = store.snapshot("u1")
    # 0.5 + 0.02 - 0.10 - 0.10 = 0.32
    assert abs(snapshot["affinity"] - 0.32) < 1e-6
    assert "口无遮拦" in snapshot["tags"]
    assert snapshot["attitude"] == attitude_for_affinity(snapshot["affinity"])


def test_insult_drains_affinity_and_admin_can_set_nickname(tmp_path) -> None:
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", clock=_FakeClock())
    store.set_nickname("u2", "小澄")
    for _ in range(4):
        store.observe("u2", "insult")
    snapshot = store.snapshot("u2")
    assert snapshot["affinity"] <= 0.2
    assert snapshot["nickname"] == "小澄"


def test_store_persists_across_instances(tmp_path) -> None:
    db = tmp_path / "affinity.sqlite3"
    first = DynamicAffinityStore(db, clock=_FakeClock())
    first.observe("u3", "positive")

    second = DynamicAffinityStore(db, clock=_FakeClock())
    assert second.snapshot("u3")["affinity"] > 0.5
