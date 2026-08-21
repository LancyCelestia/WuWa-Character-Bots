from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    ReviewResult,
    ReviewAction,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.capabilities.content_parser import (
    build_content_capability,
)
from plugins.bot_unified_runtime.capabilities.music import (
    build_music_capability,
    extract_music_query,
    is_music_command,
)
from plugins.bot_unified_runtime.output.renderer import render_reviewed_output
from plugins.bot_unified_runtime.sender.onebot import (
    _segment_from_mixed_part,
    build_onebot_message_segments,
)
from plugins.bot_unified_runtime.contracts import SendRequest, RenderedOutput
from plugins.bot_unified_runtime.sources.parsers import (
    build_content_parser_registry,
    build_source_input,
    extract_http_urls,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_bilibili import (
    PlatformParse,
    parse_bilibili,
)
from plugins.bot_unified_runtime.sources.parsers.platforms_music import (
    parse_apple_music,
    parse_netease_music,
)


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="test",
        adapter="test",
        bot_id="bot",
        session_id="s1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
    )


def test_registry_matches_supported_platforms():
    registry = build_content_parser_registry()["registry"]

    matches = registry.match(
        build_source_input("看看这个 https://www.bilibili.com/video/BV1GJ411x7h7")
    )
    assert matches and matches[0].parser_id == "bilibili"

    matches = registry.match(
        build_source_input("分享首歌 https://music.163.com/song?id=1863310999")
    )
    assert matches and matches[0].parser_id == "netease_music"

    matches = registry.match(build_source_input("随便一个 https://example.com/x"))
    assert not matches


def test_registry_respects_enabled_platforms():
    registry = build_content_parser_registry(["bilibili"])["registry"]

    matches = registry.match(
        build_source_input("https://www.bilibili.com/video/BV1GJ411x7h7")
    )
    assert matches
    matches = registry.match(
        build_source_input("https://music.163.com/song?id=1863310999")
    )
    assert not matches


def test_extract_http_urls_strips_trailing_punct():
    urls = extract_http_urls("（https://www.bilibili.com/video/BV1GJ411x7h7）。")
    assert urls == ["https://www.bilibili.com/video/BV1GJ411x7h7"]


def test_parse_bilibili_uses_view_api(monkeypatch):
    calls: list[str] = []

    def fake_http_get_json(url, **kwargs):
        calls.append(url)
        return {
            "code": 0,
            "data": {
                "bvid": "BV1GJ411x7h7",
                "title": "测试视频",
                "owner": {"name": "测试UP"},
                "pic": "https://i0.hdslb.com/x.jpg",
                "desc": "简介",
                "pages": [{"cid": 1}],
                "stat": {"view": 100, "danmaku": 5, "like": 9, "favorite": 2},
            },
        }

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_bilibili.http_get_json",
        fake_http_get_json,
    )

    item = parse_bilibili("https://www.bilibili.com/video/BV1GJ411x7h7")

    assert calls and "bvid=BV1GJ411x7h7" in calls[0]
    assert item.title == "测试视频"
    assert item.author_name == "测试UP"
    assert item.item_kind == "video"
    assert item.stats == {"播放": 100, "弹幕": 5, "点赞": 9, "收藏": 2}
    assert item.cover_url.startswith("https://")


def test_parse_bilibili_resolves_b23_short_link(monkeypatch):
    def fake_resolve(url):
        return "https://www.bilibili.com/video/BV1GJ411x7h7"

    def fake_http_get_json(url, **kwargs):
        return {
            "code": 0,
            "data": {
                "bvid": "BV1GJ411x7h7",
                "title": "短链视频",
                "owner": {"name": "UP"},
                "pic": "https://x/p.jpg",
                "desc": "",
                "pages": [{"cid": 1}],
                "stat": {},
            },
        }

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_bilibili.resolve_short_link",
        fake_resolve,
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_bilibili.http_get_json",
        fake_http_get_json,
    )

    item = parse_bilibili("https://b23.tv/abc123")

    assert item.title == "短链视频"


def test_parse_netease_music_song_detail(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        assert "api/song/detail" in url
        return {
            "songs": [
                {
                    "name": "晴天",
                    "artists": [{"name": "周杰伦"}],
                    "album": {"name": "叶惠美", "picUrl": "https://p1.music.126.net/a.jpg"},
                }
            ]
        }

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_music.http_get_json",
        fake_http_get_json,
    )

    item = parse_netease_music("https://music.163.com/song?id=1863310999")

    assert item.title == "晴天"
    assert item.author_name == "周杰伦"
    assert item.audio_url == "https://music.163.com/song/media/outer/url?id=1863310999.mp3"


def test_parse_apple_music_lookup(monkeypatch):
    def fake_http_get_json(url, **kwargs):
        assert "itunes.apple.com/lookup" in url
        return {
            "results": [
                {
                    "trackId": 1440604975,
                    "trackName": "晴天",
                    "artistName": "周杰伦",
                    "collectionName": "叶惠美",
                    "artworkUrl100": "https://x/100x100bb.jpg",
                    "previewUrl": "https://audio-ssl.itunes.apple.com/a.m4a",
                    "trackViewUrl": "https://music.apple.com/cn/album/1440604973?i=1440604975",
                }
            ]
        }

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_music.http_get_json",
        fake_http_get_json,
    )

    item = parse_apple_music(
        "https://music.apple.com/cn/album/%E5%8F%B6%E6%83%A0%E7%BE%8E/1440604973?i=1440604975"
    )

    assert item.title == "晴天"
    assert item.audio_url.endswith(".m4a")
    assert "300x300" in item.cover_url


def test_content_capability_renders_card_and_passes_media():
    def fake_parser(url):
        return PlatformParse(
            platform="bilibili",
            item_id="BV1",
            item_kind="video",
            title="测试视频",
            author_name="测试UP",
            cover_url="https://i0.hdslb.com/x.jpg",
            stats={"播放": 100},
            canonical_url="https://www.bilibili.com/video/BV1",
        )

    built = build_content_parser_registry(["bilibili"])
    built["parsers"]["bilibili"] = fake_parser
    capability = build_content_capability(registry=built)

    result = capability(
        _message("https://www.bilibili.com/video/BV1GJ411x7h7"), None
    )

    assert result.capability_id == "bot.content"
    assert result.kind == "mixed"
    assert "测试视频" in result.body
    assert result.images == [{"file": "https://i0.hdslb.com/x.jpg"}]
    assert "platform:bilibili" in result.audit_tags
    assert "parse_depth:deep" in result.audit_tags


def test_content_capability_graceful_failure():
    def fake_parser(url):
        raise ValueError("boom")

    built = build_content_parser_registry(["bilibili"])
    built["parsers"]["bilibili"] = fake_parser
    capability = build_content_capability(registry=built)

    result = capability(
        _message("https://www.bilibili.com/video/BV1GJ411x7h7"), None
    )

    assert "parse_failed" in result.audit_tags
    assert "BV1GJ411x7h7" in result.body  # 原链接仍在正文里，方便用户复制。


def test_renderer_passes_media_parts_when_approved():
    result = CapabilityResult(
        request_id="r1",
        capability_id="bot.content",
        kind="mixed",
        body="卡片正文",
        images=[{"file": "https://x/cover.jpg"}],
        audio=[{"type": "record", "file": "https://x/a.m4a"}],
    )
    review = ReviewResult(
        request_id="r1",
        approved=True,
        action=ReviewAction.ALLOW,
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        reasons=[],
        safe_text="卡片正文",
    )

    rendered = render_reviewed_output(result, review)

    assert rendered.content_type == "mixed"
    parts = rendered.content_ref["parts"]
    assert parts[0] == {"type": "image", "file": "https://x/cover.jpg"}
    assert parts[1] == {"type": "record", "file": "https://x/a.m4a"}
    assert parts[2] == {"type": "text", "text": "卡片正文"}
    assert rendered.text_fallback == "卡片正文"


def test_onebot_mixed_parts_include_record():
    segment = _segment_from_mixed_part(
        {"type": "record", "file": "https://x/a.m4a"}
    )
    assert segment == {"type": "record", "data": {"file": "https://x/a.m4a"}}


def test_onebot_send_request_with_mixed_content():
    request = SendRequest(
        request_id="r1",
        session_id="s1",
        target_scope=SessionType.PRIVATE,
        target_id="u1",
        capability_id="bot.music",
        content=RenderedOutput(
            request_id="r1",
            content_type="mixed",
            content_ref={
                "parts": [
                    {"type": "record", "file": "https://x/a.m4a"},
                    {"type": "text", "text": "♪ 晴天"},
                ]
            },
            text_fallback="♪ 晴天",
            size_estimate=8,
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
        ),
        send_policy="immediate",
        priority="normal",
        max_messages=1,
        dedupe_key="k",
        cooldown_key="k",
        privacy_level=PrivacyLevel.PUBLIC,
        persona_profile_id="shorekeeper",
    )
    segments = build_onebot_message_segments(request)
    assert segments[0]["type"] == "record"
    assert segments[1]["type"] == "text"


def test_music_command_parsing():
    assert is_music_command("点歌 晴天")
    assert is_music_command("/点歌 晴天")
    assert extract_music_query("点歌 晴天") == "晴天"
    assert not is_music_command("晴天")


def test_music_capability_uses_provider_chain():
    class FakeItem:
        title = "晴天"
        author_name = "周杰伦"
        summary = ""
        audio_url = "https://x/a.m4a"
        cover_url = ""
        canonical_url = "https://music.163.com/song?id=1"

    calls: list[tuple[str, str]] = []

    def provider_a(query):
        calls.append(("a", query))
        return None

    def provider_b(query):
        calls.append(("b", query))
        return FakeItem()

    capability = build_music_capability(
        providers=[("a", "平台A", provider_a), ("b", "平台B", provider_b)]
    )

    result = capability(_message("点歌 晴天"), None)

    assert calls == [("a", "晴天"), ("b", "晴天")]
    assert result.kind == "mixed"
    assert "晴天" in result.body
    assert result.audio == [{"type": "record", "file": "https://x/a.m4a"}]
    assert "music_source:b" in result.audit_tags


def test_music_capability_not_found():
    capability = build_music_capability(providers=[("a", "A", lambda q: None)])

    result = capability(_message("点歌 不存在的歌"), None)

    assert "music_not_found" in result.audit_tags


def test_config_parses_platform_lists():
    config = Config(
        bot_content_parse_platforms="bilibili,netease_music",
        bot_music_platforms=["apple_music"],
    )
    assert config.bot_content_parse_platforms == ["bilibili", "netease_music"]
    assert config.bot_music_platforms == ["apple_music"]


def test_cookie_provider_parses_netscape_file(tmp_path):
    from plugins.bot_unified_runtime.sources.parsers.cookies import (
        build_platform_cookie_provider,
    )

    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "\n".join(
            [
                "# Netscape HTTP Cookie File",
                ".bilibili.com\tTRUE\t/\tTRUE\t2000000000\tSESSDATA\tfake-sessdata",
                ".bilibili.com\tTRUE\t/\tTRUE\t0\tbuvid3\tfake-buvid",
                ".xiaohongshu.com\tTRUE\t/\tTRUE\t2000000000\tweb_session\tfake-session",
                ".example.com\tTRUE\t/\tTRUE\t2000000000\tsecret\tnot-collected",
            ]
        ),
        encoding="utf-8",
    )

    provider = build_platform_cookie_provider(cookie_file)

    assert "SESSDATA=fake-sessdata" in provider.cookie_header("bilibili")
    assert "web_session=fake-session" in provider.cookie_header("xiaohongshu")
    # 白名单外的域名一律不加载。
    assert provider.cookie_header("bilibili").count("secret") == 0
    assert "secret" not in str(provider.summary())


def test_xhs_deep_parse_from_initial_state(monkeypatch):
    from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
        parse_xiaohongshu,
    )
    import urllib.parse

    initial_state = {
        "note": {
            "noteDetailMap": {
                "note1": {
                    "note": {
                        "noteId": "note1",
                        "title": "测试笔记",
                        "desc": "正文内容",
                        "type": "normal",
                        "user": {"nickname": "测试用户"},
                        "imageList": [{"urlDefault": "https://sns-img/1.jpg"}],
                        "interactInfo": {"likedCount": 10, "collectedCount": 2},
                    }
                }
            }
        }
    }
    html = (
        "<html><script>window.__INITIAL_STATE__="
        + urllib.parse.quote(str(initial_state).replace("'", '"'))
        + "</script></html>"
    )

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_generic.http_get_text",
        lambda url, **kwargs: (url, html),
    )

    item = parse_xiaohongshu(
        "https://www.xiaohongshu.com/explore/note1", cookie_header="web_session=x"
    )

    assert item.title == "测试笔记"
    assert item.author_name == "测试用户"
    assert item.parse_depth == "deep"
    assert item.cover_url == "https://sns-img/1.jpg"
    assert item.stats == {"点赞": 10, "收藏": 2}


def test_douyin_deep_parse_from_router_data(monkeypatch):
    from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
        parse_douyin,
    )

    router_data = {
        "loaderData": {
            "video_(id)/page": {
                "videoInfoRes": {
                    "item_list": [
                        {
                            "aweme_id": "1",
                            "desc": "测试视频",
                            "author": {"nickname": "测试作者"},
                            "video": {"cover": {"url_list": ["https://p3.douyinpic.com/c.jpg"]}},
                            "statistics": {"digg_count": 100, "comment_count": 5},
                        }
                    ]
                }
            }
        }
    }
    html = (
        "<script>window._ROUTER_DATA = "
        + str(router_data).replace("'", '"')
        + ";</script>"
    )

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_generic.http_get_text",
        lambda url, **kwargs: (url, html),
    )

    item = parse_douyin("https://www.douyin.com/video/1", cookie_header="ttwid=x")

    assert item.title == "测试视频"
    assert item.author_name == "测试作者"
    assert item.parse_depth == "deep"
    assert item.stats == {"点赞": 100, "评论": 5}


def test_douyin_anti_bot_page_falls_back_to_blocked_card(monkeypatch):
    from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
        parse_douyin,
    )

    challenge = "<html><body><script>var glb;</script></body></html>"

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_generic.http_get_text",
        lambda url, **kwargs: (url, challenge),
    )

    item = parse_douyin("https://www.douyin.com/video/123", cookie_header="ttwid=x")

    assert item.parse_depth == "blocked"
    assert "反爬" in item.summary
    assert item.canonical_url.endswith("/video/123")


def test_xhs_initial_state_tolerates_js_tokens(monkeypatch):
    from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
        _xhs_initial_state_payload,
    )

    raw = (
        '{"note":{"noteDetailMap":{}},"search":{"hintWord":'
        '{"searchWord":"小红书网页版","title":"x"},'
        '"feeds":[],"redMoji":{"mojiData":{"version":"","tabs":undefined},"map":new Map([])}}}'
    )
    html = f"<script>window.__INITIAL_STATE__={raw}</script>"

    payload = _xhs_initial_state_payload(html)

    assert payload is not None
    assert payload["search"]["hintWord"]["searchWord"] == "小红书网页版"


def test_xhs_search_result_card_extracts_keyword(monkeypatch):
    from plugins.bot_unified_runtime.sources.parsers.platforms_generic import (
        parse_xiaohongshu,
    )

    raw = (
        '{"search":{"searchContext":{"keyword":"鸣潮"},"hintWord":{"searchWord":"鸣潮"},'
        '"feeds":[],"redMoji":{"mojiData":{}}}}'
    )
    html = f"<script>window.__INITIAL_STATE__={raw}</script>"

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_generic.http_get_text",
        lambda url, **kwargs: (url, html),
    )

    item = parse_xiaohongshu(
        "https://www.xiaohongshu.com/search_result/abc123",
        cookie_header="web_session=x",
    )

    assert item.item_kind == "search"
    assert item.title == "小红书搜索：鸣潮"
    assert item.parse_depth == "shallow"


def test_registry_binds_cookie_header_to_parsers(monkeypatch):
    from plugins.bot_unified_runtime.sources.parsers import (
        build_content_parser_registry,
    )
    from plugins.bot_unified_runtime.sources.parsers.cookies import (
        PlatformCookieProvider,
    )
    import plugins.bot_unified_runtime.sources.parsers.platforms_bilibili as pb

    captured: dict[str, str] = {}

    def fake_http_get_json(url, **kwargs):
        captured["cookie"] = kwargs.get("cookie", "")
        return {
            "code": 0,
            "data": {
                "bvid": "BV1GJ411x7h7",
                "title": "t",
                "owner": {"name": "u"},
                "pic": "",
                "desc": "",
                "pages": [{"cid": 1}],
                "stat": {},
            },
        }

    monkeypatch.setattr(pb, "http_get_json", fake_http_get_json)

    provider = PlatformCookieProvider(headers={"bilibili": "SESSDATA=abc"})
    built = build_content_parser_registry(["bilibili"], cookie_provider=provider)

    built["parsers"]["bilibili"]("https://www.bilibili.com/video/BV1GJ411x7h7")

    assert captured["cookie"] == "SESSDATA=abc"


def test_music_card_fallback_when_no_audio_url():
    class FakeItem:
        title = "QQ歌"
        author_name = "歌手"
        summary = ""
        audio_url = ""
        cover_url = ""
        canonical_url = "https://y.qq.com/n/ryqq/songDetail/abc"
        stats = {"music_card": {"type": "qq", "id": "abc"}}

    capability = build_music_capability(
        providers=[("qqmusic", "QQ音乐", lambda q: FakeItem())]
    )

    result = capability(_message("点歌 QQ歌"), None)

    assert result.audio == [
        {"type": "music", "music_type": "qq", "music_id": "abc"}
    ]
    assert "已附带平台音乐卡片" in result.body
