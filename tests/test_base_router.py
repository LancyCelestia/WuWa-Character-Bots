"""基层统一路由器的确定性分类测试。"""

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.runtime.aliases import CommandAliasResolver
from plugins.bot_unified_runtime.runtime.base_router import (
    RouteKind,
    classify_message_route,
    extract_http_urls,
)


def _resolver():
    return CommandAliasResolver(
        nickname="岸宝",
        nicknames=["岸宝", "守岸人"],
    )


def test_plain_chat_text_routes_to_llm_chat():
    decision = classify_message_route("今天有点累，陪我说说话。", config=Config())
    assert decision.kind is RouteKind.CHAT
    assert decision.capability_id == "bot.chat"
    assert decision.priority == 50


def test_http_link_routes_to_content_parser():
    decision = classify_message_route(
        "看这个 https://www.bilibili.com/video/BV1xx411c7mD （视频）", config=Config()
    )
    assert decision.kind is RouteKind.CONTENT
    assert decision.capability_id == "bot.content"


def test_music_and_music_mode_routes():
    assert classify_message_route("/点歌 海阔天空", config=Config()).kind is RouteKind.MUSIC
    assert (
        classify_message_route("/点歌模式 卡片", config=Config()).kind
        is RouteKind.MUSIC_MODE
    )


def test_wiki_epic_weather_today_history_routes():
    config = Config()
    assert classify_message_route("/wiki Python", config=config).kind is RouteKind.WIKI
    assert classify_message_route("/epic", config=config).kind is RouteKind.EPIC
    assert classify_message_route("/天气 杭州", config=config).kind is RouteKind.WEATHER
    assert (
        classify_message_route("/历史上的今天", config=config).kind
        is RouteKind.TODAY_HISTORY
    )


def test_subscribe_and_admin_routes():
    config = Config()
    assert (
        classify_message_route("/订阅 状态", config=config).kind
        is RouteKind.SUBSCRIBE
    )
    assert classify_message_route("/bot status", config=config).kind is RouteKind.ADMIN


def test_auto_send_route():
    text = "报存 给 A、B 发邮件，主题：周末安排，内容根据你对他们的了解分别写"
    assert classify_message_route(text, config=Config()).kind is RouteKind.AUTO_SEND


def test_alias_route_beats_later_routes():
    decision = classify_message_route(
        "/岸宝天气 杭州", config=Config(), alias_resolver=_resolver()
    )
    assert decision.kind is RouteKind.ALIAS
    assert decision.priority == 19


def test_disabled_command_routes_to_ignore_not_llm():
    decision = classify_message_route(
        "/天气 杭州", config=Config(bot_weather_query_enabled=False)
    )
    assert decision.kind is RouteKind.IGNORE


def test_empty_text_routes_to_ignore():
    assert classify_message_route("  ", config=Config()).kind is RouteKind.IGNORE


def test_extract_http_urls_strips_trailing_punctuation():
    urls = extract_http_urls("链接 https://b23.tv/abc， 另一个 https://example.com/x。")
    assert urls == ["https://b23.tv/abc", "https://example.com/x"]


def test_decision_to_dict_is_auditable():
    decision = classify_message_route("/wiki Python", config=Config())
    data = decision.to_dict()
    assert data["kind"] == "wiki"
    assert data["capability_id"] == "bot.wiki"
    assert "base_route:wiki" in data["audit_tags"]
