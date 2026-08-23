"""全问法矩阵回归：锁死每条问法 -> 路由 -> 能力 -> 归一化命令。"""

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.policy.gate import PolicySettings, evaluate_policy
from plugins.bot_unified_runtime.runtime.aliases import CommandAliasResolver
from plugins.bot_unified_runtime.runtime.base_router import RouteKind, classify_message_route

ALIAS = CommandAliasResolver(nickname="岸宝", nicknames=["岸宝", "守岸人"])


@pytest.mark.parametrize(
    ("text", "kind", "capability", "target", "normalized"),
    [
        ("/岸宝帮助", RouteKind.ALIAS, "bot.alias", None, None),
        ("/岸宝天气 杭州", RouteKind.ALIAS, "bot.alias", None, None),
        ("守岸人点歌 晴天", RouteKind.ALIAS, "bot.alias", None, None),
        ("/bot status", RouteKind.ADMIN, "bot.status", None, None),
        ("/bot routes", RouteKind.ADMIN, "bot.status", None, None),
        ("/订阅 状态", RouteKind.SUBSCRIBE, "bot.subscribe", None, None),
        ("报存 给 A 发邮件，主题：周末安排，内容根据你对他们的了解分别写", RouteKind.AUTO_SEND, "bot.auto_send", None, None),
        ("/表情 列表", RouteKind.MEME, "bot.meme", None, None),
        ("/meme petpet 可爱", RouteKind.MEME, "bot.meme", None, None),
        ("/点歌模式 卡片", RouteKind.MUSIC_MODE, "bot.music_mode", None, None),
        ("/点歌 晴天", RouteKind.MUSIC, "bot.music", None, None),
        ("/历史上的今天", RouteKind.TODAY_HISTORY, "bot.today_history", None, None),
        ("/wiki 鸣潮", RouteKind.WIKI, "bot.wiki", None, None),
        ("/WIKIPEDIA Python", RouteKind.WIKI, "bot.wiki", None, None),
        ("/epic", RouteKind.EPIC, "bot.epic", None, None),
        ("/Epic Free", RouteKind.EPIC, "bot.epic", None, None),
        ("/天气 杭州", RouteKind.WEATHER, "bot.weather", None, None),
        ("/查天气 上海", RouteKind.WEATHER, "bot.weather", None, None),
        ("帮我查一下杭州天气", RouteKind.NATURAL_COMMAND, "bot.natural_command", "bot.weather", "天气 杭州"),
        ("杭州天气怎么样", RouteKind.NATURAL_COMMAND, "bot.natural_command", "bot.weather", "天气 杭州"),
        ("帮我查天气 杭州", RouteKind.NATURAL_COMMAND, "bot.natural_command", "bot.weather", "天气 杭州"),
        ("来首晴天", RouteKind.NATURAL_COMMAND, "bot.natural_command", "bot.music", "点歌 晴天"),
        ("放首歌 晴天", RouteKind.NATURAL_COMMAND, "bot.natural_command", "bot.music", "点歌 晴天"),
        ("帮我放一首周杰伦的歌", RouteKind.NATURAL_COMMAND, "bot.natural_command", "bot.music", "点歌 周杰伦的歌"),
        ("帮我查维基 鸣潮", RouteKind.NATURAL_COMMAND, "bot.natural_command", "bot.wiki", "wiki 鸣潮"),
        ("今天有什么免费游戏", RouteKind.NATURAL_COMMAND, "bot.natural_command", "bot.epic", "epic"),
        ("今天历史上发生了什么", RouteKind.NATURAL_COMMAND, "bot.natural_command", "bot.today_history", "历史上的今天"),
        ("看这个 https://www.bilibili.com/video/BV1xx411c7mD", RouteKind.CONTENT, "bot.content", None, None),
        ("今天有点累，陪我说说话。", RouteKind.CHAT, "bot.chat", None, None),
        ("漂泊者是谁", RouteKind.CHAT, "bot.chat", None, None),
        ("今天天气不错", RouteKind.CHAT, "bot.chat", None, None),
        ("播放量好高", RouteKind.CHAT, "bot.chat", None, None),
        ("", RouteKind.IGNORE, "bot.ignore", None, None),
    ],
)
def test_route_matrix(text, kind, capability, target, normalized):
    decision = classify_message_route(text, config=Config(), alias_resolver=ALIAS)
    assert decision.kind is kind, text
    assert decision.capability_id == capability, text
    assert decision.target_capability_id == target, text
    assert decision.normalized_text == normalized, text


def _group_message(text, *, mention=False):
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="group:100",
        session_type=SessionType.GROUP,
        sender_id="42",
        group_id="100",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=mention,
        message_id="m1",
    )


def test_group_gate_matrix_with_alias_command_check():
    def command_check(text):
        return ALIAS.resolve(text) is not None or text.startswith("/bot")

    settings = PolicySettings(extra_command_check=command_check)
    cases = [
        ("/bot status", False, True),
        ("/岸宝帮助", False, True),
        ("岸宝 帮我查天气", True, True),
        ("大家晚上好", False, False),
    ]
    for text, mention, allowed in cases:
        evaluation = evaluate_policy(_group_message(text, mention=mention), "bot.chat", settings=settings)
        assert evaluation.allowed is allowed, text
