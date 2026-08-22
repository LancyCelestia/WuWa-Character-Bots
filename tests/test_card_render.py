from plugins.bot_unified_runtime.output.render_backends import (
    NullRenderBackend,
    PlaywrightRenderBackend,
    build_render_backend,
)
from plugins.bot_unified_runtime.output.templates import (
    card_payload_from_parse,
    render_media_card_html,
)


def test_card_template_escapes_user_content():
    html = render_media_card_html(
        {
            "title": "<script>alert(1)</script>",
            "platform": "bilibili",
            "author": '"测试"',
            "stats": {"播放": "<b>100</b>"},
            "summary": "正文 & 更多",
        }
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html
    assert 'class="card"' in html


def test_card_payload_from_parse():
    class FakeItem:
        title = "t"
        platform = "pixiv"
        author_name = "a"
        cover_url = "https://x/c.jpg"
        stats = {"播放": 1, "music_card": {"type": "qq"}}
        summary = "s"
        canonical_url = "https://x/1"

    payload = card_payload_from_parse(FakeItem())

    assert payload["title"] == "t"
    assert payload["stats"]["播放"] == 1


class FakeBackend:
    name = "fake"
    available = True

    def __init__(self) -> None:
        self.calls = 0

    def render_card(self, payload):
        self.calls += 1
        return b"\x89PNG fake"


def test_content_capability_renders_card_image(tmp_path):
    from plugins.bot_unified_runtime.capabilities.content_parser import (
        build_content_capability,
    )
    from plugins.bot_unified_runtime.sources.parsers import (
        build_content_parser_registry,
    )
    from plugins.bot_unified_runtime.sources.parsers.types import PlatformParse
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    backend = FakeBackend()

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

    assert backend.calls == 1
    assert len(result.images) == 1
    assert result.images[0]["file"].endswith(".png")
    assert "card_rendered" in result.audit_tags


def test_build_render_backend_falls_back_to_null():
    # playwright 已安装时返回 playwright，否则 null；两种都不抛异常。
    backend = build_render_backend("playwright")
    assert backend.name in {"playwright", "null"}
    assert build_render_backend("").name == "null"
    assert isinstance(NullRenderBackend().render_card({}), type(None))
