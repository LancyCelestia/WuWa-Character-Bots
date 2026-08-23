"""通用卡片渲染测试。

覆盖：
- Jinja2 自动转义 + bridge 对 | safe 字段的预处理（XSS）；
- 空 payload 渲染不抛异常；
- page_type / badge / stats 通用条目 / detail 各区块（episodes/live/
  comments/images/相关链接）渲染；
- card_payload_from_parse 的 detail 兼容字段；
- 平台配色与官方名映射；
- qrcode 可选依赖缺失时 QR 区块整体隐藏；
- build_content_capability 经 render_card 的 FakeBackend 集成（含
  viewport / device_scale_factor）。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from plugins.bot_unified_runtime.output.card_render.bridge import (
    _build_qr_data_url,
    parse_to_render_payload,
    render_universal_card_html,
)
from plugins.bot_unified_runtime.output.templates import card_payload_from_parse


def test_empty_payload_renders_card_without_error():
    html = render_universal_card_html({})
    assert isinstance(html, str)
    assert 'class="card"' in html
    assert "banner-img" in html  # 空卡片仍保留完整结构
    # None 也应等价于空 payload。
    assert render_universal_card_html(None) == html


def test_xss_is_escaped():
    html = render_universal_card_html(
        {
            "platform": "bilibili",
            "title": "<script>alert(1)</script>",
            "name": "<img src=x onerror=alert(2)>",
            "stats": {"播放": "<b>100</b>"},
            "summary": "<script>bad()</script>",
        }
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x onerror" not in html
    assert "&lt;img" in html
    assert "<b>100</b>" not in html
    assert "&lt;b&gt;100&lt;/b&gt;" in html


def test_page_type_badge_and_footer_render():
    html = render_universal_card_html(
        {
            "platform": "bilibili",
            "title": "标题",
            "page_type": "video",
            "badge": "独家",
        }
    )
    assert "独家" in html
    assert "Bilibili" in html
    assert "ShoreKeeper Parser" in html


def test_stats_generic_items_render():
    html = render_universal_card_html(
        {"platform": "bilibili", "stats": {"播放": 123456, "硬币": 4}}
    )
    assert 'class="stats-bar"' in html
    assert "播放" in html
    assert "123456" in html
    assert "硬币" in html
    assert "4" in html


def test_detail_blocks_render():
    payload = {
        "platform": "bilibili",
        "title": "视频标题",
        "page_type": "live",
        "summary": "正文内容",
        "detail": {
            "author": {
                "name": "作者",
                "avatar": "https://x/avatar.jpg",
                "signature": "签名",
                "fans": 1000,
                "official_title": "认证",
            },
            "episodes": [
                {
                    "index": 1,
                    "title": "P1",
                    "duration_seconds": 95,
                    "cover": "https://x/p1.jpg",
                }
            ],
            "images": ["https://x/1.jpg", "https://x/2.jpg"],
            "live": {
                "title": "直播标题",
                "cover": "https://x/live.jpg",
                "keyframe": "https://x/key.jpg",
                "area": "上海",
                "parent_area": "中国",
                "tags": ["游戏", "唱歌"],
                "start_time": "2026-08-23 10:00:00",
                "intro": "直播简介",
            },
            "comments": [
                {
                    "user": "评论者",
                    "level": 5,
                    "time": "2026-08-23",
                    "content": "好内容",
                    "likes": 12,
                }
            ],
            "goods": {
                "title": "周边",
                "price": 9.9,
                "origin_price": 19.9,
                "category": "手办",
                "brand": "品牌",
                "cover": "https://x/goods.jpg",
                "intro": "介绍",
            },
            "related": [{"title": "相关1", "url": "https://x/1"}],
        },
    }
    html = render_universal_card_html(payload)

    # header（作者映射）
    assert "作者" in html
    assert "签名" in html
    assert "1000 粉丝" in html
    assert "认证" in html
    # 分 P / 剧集
    assert "分P列表" in html
    assert "P1" in html
    # 图片
    assert 'class="image-gallery"' in html
    assert "https://x/1.jpg" in html
    # 直播间
    assert 'class="live-section"' in html
    assert "直播标题" in html
    assert "中国/上海" in html
    assert "游戏 唱歌" in html
    assert "直播简介" in html
    # 评论
    assert 'class="comments-section"' in html
    assert "评论区" in html
    assert "评论者" in html
    assert "好内容" in html
    assert "Lv.5" in html
    # 相关链接 → 转发块
    assert 'class="forward-box"' in html
    assert "相关1" in html
    assert "https://x/1" in html
    # 商品并入正文
    assert "商品：周边" in html
    assert "价格：9.9 / 19.9" in html
    # 正文
    assert "正文内容" in html


def test_card_payload_from_parse_contains_detail():
    class FakeItem:
        platform = "bilibili"
        item_id = "BV1"
        item_kind = "video"
        title = "t"
        author_name = "a"
        summary = "s"
        cover_url = "https://x/c.jpg"
        canonical_url = "https://x/1"
        stats = {"播放": 1}
        page_type = "video"
        badge = "独家"
        detail = {
            "author": {"name": "a", "fans": 2},
            "images": ["https://x/i.jpg"],
        }

    payload = card_payload_from_parse(FakeItem())
    assert payload["title"] == "t"
    assert payload["stats"]["播放"] == 1
    assert payload["page_type"] == "video"
    assert payload["badge"] == "独家"
    assert payload["detail"]["images"] == ["https://x/i.jpg"]
    # 作者映射与旧字段并存
    assert payload["name"] == "a"
    assert payload["author"] == "a"


def test_platform_color_and_official_name_mapping():
    colors = {
        "bilibili": "#fb7299",
        "xiaohongshu": "#ff2442",
        "xhs": "#ff2442",
        "youtube": "#ff0000",
        "twitter": "#1d9bf0",
        "x": "#1d9bf0",
        "pixiv": "#0096fa",
        "lofter": "#3fa1ad",
        "allcpp": "#2f6bff",
        "qqmusic": "#00c853",
        "unknown_platform": "#607080",
    }
    names = {
        "bilibili": "Bilibili",
        "xiaohongshu": "Xiaohongshu",
        "youtube": "YouTube",
        "twitter": "Twitter/X",
        "pixiv": "Pixiv",
        "lofter": "LOFTER",
        "allcpp": "AllCPP",
    }
    for platform, expected in colors.items():
        payload = parse_to_render_payload(SimpleNamespace(platform=platform))
        assert payload.platform_color == expected, platform
    for platform, expected in names.items():
        payload = parse_to_render_payload(SimpleNamespace(platform=platform))
        assert payload.platform_official_name == expected, platform


def test_qr_hidden_when_qrcode_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "qrcode", None)
    assert _build_qr_data_url("https://example.com/1") == ""
    html = render_universal_card_html({"url": "https://example.com/1"})
    assert 'class="qrcode-container"' not in html
    assert "data:image/png;base64" not in html


def test_qr_hidden_without_url():
    html = render_universal_card_html({"platform": "bilibili", "url": ""})
    assert 'class="qrcode-container"' not in html


def test_output_templates_forwards_universal_render():
    from plugins.bot_unified_runtime.output.templates import (
        render_universal_card_html as forwarded,
    )

    html = forwarded({"platform": "bilibili", "title": "转发入口"})
    assert 'class="card"' in html
    assert "转发入口" in html


class FakeBackend:
    name = "fake"
    available = True

    def __init__(self) -> None:
        self.calls = []

    def render_card(self, payload):
        self.calls.append(payload)
        return b"\x89PNG fake"


def test_content_capability_renders_universal_card(tmp_path):
    from plugins.bot_unified_runtime.capabilities.content_parser import (
        build_content_capability,
    )
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
    from plugins.bot_unified_runtime.sources.parsers import (
        build_content_parser_registry,
    )
    from plugins.bot_unified_runtime.sources.parsers.types import PlatformParse

    def fake_parser(url, **kwargs):
        return PlatformParse(
            platform="bilibili",
            item_id="BV1",
            item_kind="video",
            title="测试视频",
            author_name="UP",
            cover_url="https://x/c.jpg",
            stats={"播放": 100},
            canonical_url="https://www.bilibili.com/video/BV1",
        )

    built = build_content_parser_registry(["bilibili"])
    built["parsers"]["bilibili"] = fake_parser
    backend = FakeBackend()
    capability = build_content_capability(
        registry=built,
        render_backend=backend,
        card_dir=str(tmp_path / "cards"),
    )
    message = IncomingMessage(
        platform="test",
        adapter="test",
        bot_id="bot",
        session_id="s1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text="https://www.bilibili.com/video/BV1GJ411x7h7",
        raw_segments=[],
        mentions_bot=True,
    )

    result = capability(message, None)

    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert 'class="card"' in call["html"]
    assert "stats-bar" in call["html"]
    assert "测试视频" in call["html"]
    assert call["viewport"] == {"width": 1440, "height": 960}
    assert call["device_scale_factor"] == 2
    assert len(result.images) == 1
    assert result.images[0]["file"].endswith(".png")
    assert "card_rendered" in result.audit_tags


def test_content_capability_falls_back_to_media_card(tmp_path):
    from plugins.bot_unified_runtime.capabilities.content_parser import (
        build_content_capability,
    )
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
    from plugins.bot_unified_runtime.sources.parsers import (
        build_content_parser_registry,
    )
    from plugins.bot_unified_runtime.sources.parsers.types import PlatformParse

    def fake_parser(url, **kwargs):
        return PlatformParse(
            platform="mihuashi",
            item_id="P1",
            item_kind="project",
            title="米画师企划",
            author_name="画师",
            cover_url="https://x/c.jpg",
            stats={"点赞": 3},
            canonical_url="https://www.mihuashi.com/projects/1",
        )

    built = build_content_parser_registry(["mihuashi"])
    built["parsers"]["mihuashi"] = fake_parser
    backend = FakeBackend()
    capability = build_content_capability(
        registry=built,
        render_backend=backend,
        card_dir=str(tmp_path / "cards"),
    )
    message = IncomingMessage(
        platform="test",
        adapter="test",
        bot_id="bot",
        session_id="s2",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text="https://www.mihuashi.com/projects/11789469",
        raw_segments=[],
        mentions_bot=True,
    )

    result = capability(message, None)

    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert "cover-wrap" in call["html"]
    assert "banner-img" not in call["html"]
    assert result.images and result.images[0]["file"].endswith(".png")


def test_card_summary_strips_duration_and_intro_prefix():
    html = render_universal_card_html(
        {
            "platform": "bilibili",
            "title": "标题",
            "text": "时长：1分22秒\n发布时间：2026-08-22\n简介：为你，千千万万次",
        }
    )
    assert "时长：1分22秒" not in html
    assert "发布时间：2026-08-22" not in html
    assert "简介：" not in html
    assert "为你，千千万万次" in html
