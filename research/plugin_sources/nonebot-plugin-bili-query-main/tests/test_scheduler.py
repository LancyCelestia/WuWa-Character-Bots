"""定时订阅检查逻辑测试（mock 数据库与 API）"""
from datetime import datetime

import pytest

import nonebot_plugin_bili_query.scheduler as sched


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 8, 16, 12, 0)

    def video(self, bvid: str, minutes_ago: int = 0):
        from datetime import timedelta
        return {
            "title": f"视频 {bvid}",
            "bvid": bvid,
            "created": self.now - timedelta(minutes=minutes_ago),
        }


@pytest.fixture
def recorder(monkeypatch):
    """记录回调通知与数据库更新"""
    notified = []
    updates = []

    async def cb(group_id, uid, video_info):
        notified.append((group_id, uid, video_info["bvid"]))

    async def fake_update(uid, bvid, ts):
        updates.append((uid, bvid, ts))

    monkeypatch.setattr(sched, "update_last_video", fake_update)
    # 清空回调列表，只保留本测试注册的
    monkeypatch.setattr(sched, "_notify_callbacks", [cb])
    return notified, updates


def patch_data(monkeypatch, subs, groups_by_uid, api_videos):
    async def fake_subs():
        return subs

    async def fake_groups(uid):
        return groups_by_uid.get(uid, [])

    async def fake_videos(uid, ps=1):
        return api_videos.get(uid)

    monkeypatch.setattr(sched, "get_subscriptions", fake_subs)
    monkeypatch.setattr(sched, "get_subscription_groups", fake_groups)
    monkeypatch.setattr(sched, "get_user_videos", fake_videos)


async def test_no_subscriptions_noop(app, monkeypatch, recorder):
    notified, updates = recorder
    patch_data(monkeypatch, [], {}, {})
    await sched.check_subscriptions()
    assert notified == []
    assert updates == []


async def test_first_check_sets_baseline_without_announce(app, monkeypatch, recorder):
    """回归：首次见到订阅只建立基线，不把旧视频当作新视频播报"""
    notified, updates = recorder
    clock = FakeClock()
    patch_data(
        monkeypatch,
        subs=[("100", "42")],
        groups_by_uid={"42": [("100", "42", None, None)]},
        api_videos={"42": [clock.video("BV1old00000")]},
    )
    await sched.check_subscriptions()
    assert notified == []
    assert updates == [("42", "BV1old00000", int(clock.now.timestamp()))]


async def test_new_video_notifies_all_groups(app, monkeypatch, recorder):
    """回归：多个群订阅同一 UP 主时，所有群都收到通知"""
    notified, updates = recorder
    clock = FakeClock()
    patch_data(
        monkeypatch,
        subs=[("100", "42"), ("200", "42")],
        groups_by_uid={"42": [
            ("100", "42", "BV1old00000", 1),
            ("200", "42", "BV1old00000", 1),
        ]},
        api_videos={"42": [clock.video("BV1new00000", minutes_ago=10)]},
    )
    await sched.check_subscriptions()
    assert sorted(notified) == [("100", "42", "BV1new00000"), ("200", "42", "BV1new00000")]
    assert updates == [("42", "BV1new00000", int(clock.video("BV1new00000", 10)["created"].timestamp()))]


async def test_no_new_video_no_action(app, monkeypatch, recorder):
    notified, updates = recorder
    clock = FakeClock()
    patch_data(
        monkeypatch,
        subs=[("100", "42")],
        groups_by_uid={"42": [("100", "42", "BV1same0000", 1)]},
        api_videos={"42": [clock.video("BV1same0000", minutes_ago=30)]},
    )
    await sched.check_subscriptions()
    assert notified == []
    assert updates == []


async def test_deleted_video_not_announced(app, monkeypatch, recorder):
    """UP 主删除最新视频后旧视频重新置顶：不是新视频，不播报"""
    notified, updates = recorder
    clock = FakeClock()
    patch_data(
        monkeypatch,
        subs=[("100", "42")],
        groups_by_uid={"42": [("100", "42", "BV1new00000", int(clock.now.timestamp()))]},
        api_videos={"42": [clock.video("BV1old00000", minutes_ago=600)]},
    )
    await sched.check_subscriptions()
    assert notified == []
    assert updates == []


async def test_multiple_ups(app, monkeypatch, recorder):
    """不同 UP 主互不影响"""
    notified, updates = recorder
    clock = FakeClock()
    patch_data(
        monkeypatch,
        subs=[("100", "1"), ("100", "2"), ("200", "2")],
        groups_by_uid={
            "1": [("100", "1", "BV1a0000000", 1)],
            "2": [("100", "2", None, None), ("200", "2", None, None)],
        },
        api_videos={
            "1": [clock.video("BV1b0000000", minutes_ago=5)],
            "2": [clock.video("BV2c0000000", minutes_ago=5)],
        },
    )
    await sched.check_subscriptions()
    # UP 1 有旧基线且有更新 → 通知；UP 2 首次 → 只建立基线
    assert notified == [("100", "1", "BV1b0000000")]
    assert len(updates) == 2
