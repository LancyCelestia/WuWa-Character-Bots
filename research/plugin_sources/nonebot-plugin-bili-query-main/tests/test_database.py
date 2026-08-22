"""数据库读写集成测试（真实 sqlite，localstore 临时目录）"""
import pytest

from nonebot_plugin_bili_query.database import (
    init_db,
    add_subscription,
    remove_subscription,
    get_subscriptions,
    get_subscription_groups,
    update_last_video,
    set_subscription_baseline,
)


@pytest.fixture
async def db(app):
    await init_db()
    return None


async def test_add_and_remove(db):
    assert await add_subscription("9001", "111") is True
    # 重复订阅返回 False
    assert await add_subscription("9001", "111") is False
    assert await get_subscriptions() == [("9001", "111")]

    assert await remove_subscription("9001", "111") is True
    assert await remove_subscription("9001", "111") is False
    assert await get_subscriptions() == []


async def test_baseline_and_update(db):
    await add_subscription("9001", "222")
    await add_subscription("9002", "222")

    # 单条基线：只更新指定群
    await set_subscription_baseline("9001", "222", "BV1aaa00000", 100)
    rows = await get_subscription_groups("222")
    by_group = {r[0]: r for r in rows}
    assert by_group["9001"][2] == "BV1aaa00000"
    assert by_group["9001"][3] == 100
    assert by_group["9002"][2] is None

    # 按 UID 更新：全部行同步
    await update_last_video("222", "BV1bbb00000", 200)
    rows = await get_subscription_groups("222")
    assert all(r[2] == "BV1bbb00000" and r[3] == 200 for r in rows)
