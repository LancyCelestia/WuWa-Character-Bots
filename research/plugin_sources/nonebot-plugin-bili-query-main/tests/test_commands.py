"""命令注册与事件分发测试（nonebug）"""
from datetime import datetime

import nonebot_plugin_bili_query as plugin
from nonebot.adapters.onebot.v11 import Message, GroupMessageEvent, PrivateMessageEvent

from nonebot_plugin_bili_query import help_cmd, user_cmd, video_cmd, subscribe_cmd


def make_group_event(text: str, group_id: int = 10000, user_id: int = 20000) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1122,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=1234,
        message=Message(text),
        raw_message=text,
        font=0,
        sender={"user_id": user_id, "nickname": "test"},
        group_id=group_id,
    )


def make_private_event(text: str, user_id: int = 20000) -> PrivateMessageEvent:
    return PrivateMessageEvent(
        time=1122,
        self_id=1,
        post_type="message",
        sub_type="friend",
        user_id=user_id,
        message_type="private",
        message_id=1234,
        message=Message(text),
        raw_message=text,
        font=0,
        sender={"user_id": user_id, "nickname": "test"},
    )


HELP_TEXT = (
    "📖 B站查询与提醒 插件指令：\n"
    "1. /用户查询 [UID/链接] - 查询B站用户信息（粉丝、投稿数等）\n"
    "2. /视频查询 [BV号/链接] - 查询B站视频信息（播放量、点赞等）\n"
    "3. /订阅 [UID/链接] - 订阅用户，有新视频时自动提醒\n"
    "4. /取消订阅 [UID/链接] - 取消订阅\n"
    "5. /help - 显示本帮助"
)


async def test_help_command_triggers(app):
    """单斜杠 /help 应当触发帮助命令并回复帮助文本"""
    async with app.test_matcher() as ctx:
        adapter = ctx.create_adapter()
        bot = ctx.create_bot(adapter=adapter)
        event = make_group_event("/help")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, HELP_TEXT, result=None, bot=bot)
        ctx.should_finished(help_cmd)


async def test_bare_word_does_not_trigger(app):
    """command_start 默认为 {"/"}，裸“帮助”不应触发任何回复"""
    async with app.test_matcher() as ctx:
        adapter = ctx.create_adapter()
        bot = ctx.create_bot(adapter=adapter)
        event = make_group_event("帮助")
        ctx.receive_event(bot, event)


async def test_user_query_missing_arg(app):
    """回归：args 注解为 str 时 handler 被静默跳过，必须能正常回复"""
    async with app.test_matcher() as ctx:
        adapter = ctx.create_adapter()
        bot = ctx.create_bot(adapter=adapter)
        event = make_group_event("/用户查询")
        ctx.receive_event(bot, event)
        ctx.should_call_send(
            event,
            "请提供要查询的 UID 或空间链接，例如：/用户查询 123456",
            result=None,
            bot=bot,
        )
        ctx.should_finished(user_cmd)


async def test_subscribe_in_private_gets_reply(app):
    """回归：私聊使用订阅命令应得到提示，而不是无响应"""
    async with app.test_matcher() as ctx:
        adapter = ctx.create_adapter()
        bot = ctx.create_bot(adapter=adapter)
        event = make_private_event("/订阅 123456")
        ctx.receive_event(bot, event)
        ctx.should_call_send(
            event, "订阅功能仅支持群聊使用", result=None, bot=bot
        )
        ctx.should_finished(subscribe_cmd)


async def test_subscribe_group_happy_path(app, monkeypatch):
    """群聊订阅成功：写入数据库并记录基线，回复订阅成功"""
    calls = []

    async def fake_add(group_id: str, uid: str) -> bool:
        calls.append(("add", group_id, uid))
        return True

    async def fake_videos(uid: str, ps: int = 1):
        return [{"bvid": "BV1baseline00", "created": datetime(2026, 1, 1, 12, 0)}]

    async def fake_baseline(group_id: str, uid: str, bvid: str, ts: int):
        calls.append(("baseline", group_id, uid, bvid, ts))

    monkeypatch.setattr(plugin, "add_subscription", fake_add)
    monkeypatch.setattr(plugin, "get_user_videos", fake_videos)
    monkeypatch.setattr(plugin, "set_subscription_baseline", fake_baseline)

    async with app.test_matcher() as ctx:
        adapter = ctx.create_adapter()
        bot = ctx.create_bot(adapter=adapter)
        event = make_group_event("/订阅 123456", group_id=777)
        ctx.receive_event(bot, event)
        ctx.should_call_send(
            event, "✅ 订阅成功！已订阅 UID：123456", result=None, bot=bot
        )
        ctx.should_finished(subscribe_cmd)

    assert ("add", "777", "123456") in calls
    assert any(
        c[0] == "baseline" and c[1] == "777" and c[3] == "BV1baseline00" for c in calls
    )


async def test_subscribe_duplicate(app, monkeypatch):
    """重复订阅提示已订阅"""
    async def fake_add(group_id: str, uid: str) -> bool:
        return False

    monkeypatch.setattr(plugin, "add_subscription", fake_add)

    async with app.test_matcher() as ctx:
        adapter = ctx.create_adapter()
        bot = ctx.create_bot(adapter=adapter)
        event = make_group_event("/订阅 123456")
        ctx.receive_event(bot, event)
        ctx.should_call_send(
            event, "⚠️ 该 UID 已被本群订阅", result=None, bot=bot
        )
        ctx.should_finished(subscribe_cmd)


async def test_video_query_b23_short_link(app, monkeypatch):
    """回归：b23.tv 短链应走解析分支并查询成功"""
    async def fake_resolve(url: str):
        assert "b23.tv" in url
        return "BV1xx411c7mD"

    async def fake_video_info(bv: str):
        assert bv == "BV1xx411c7mD"
        return {
            "title": "测试视频", "bvid": bv, "uploader": "测试UP",
            "duration": 125, "play": 1, "like": 2, "coin": 3,
            "favorite": 4, "share": 5,
            "pubdate": datetime(2026, 1, 1, 12, 0), "desc": "简介",
        }

    monkeypatch.setattr(plugin, "resolve_b23_url", fake_resolve)
    monkeypatch.setattr(plugin, "get_video_info", fake_video_info)

    expected = (
        "🎬 视频信息：测试视频\n"
        "BV号：BV1xx411c7mD\n"
        "UP主：测试UP\n"
        "时长：2分5秒\n"
        "播放量：1\n"
        "点赞：2\n"
        "投币：3\n"
        "收藏：4\n"
        "转发：5\n"
        "发布时间：2026-01-01 12:00\n"
        "简介：简介"
    )

    async with app.test_matcher() as ctx:
        adapter = ctx.create_adapter()
        bot = ctx.create_bot(adapter=adapter)
        event = make_group_event("/视频查询 https://b23.tv/AbCdEf")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, expected, result=None, bot=bot)
        ctx.should_finished(video_cmd)
