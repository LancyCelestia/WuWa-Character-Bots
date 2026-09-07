"""订阅即时推送卡片化回归：转换映射、mixed 输出形状、失败回退。"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.content_parser import (
    build_subscription_push_capability,
    render_subscription_push_card,
    subscription_item_to_parse,
)
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.contracts.subscription import (
    NormalizedSubscriptionItem,
    PushCandidate,
    SubscriptionSpec,
)

_TEXT = "[订阅] bilibili 某UP主 发布新视频《标题》：https://example.com/v"


def _spec(platform: str = "bilibili") -> SubscriptionSpec:
    return SubscriptionSpec(
        id="spec-1",
        platform=platform,
        target_kind="user",
        target_id="42",
        target_name="某UP主",
    )


def _candidate(platform: str = "bilibili", url: str = "https://example.com/v") -> PushCandidate:
    return PushCandidate(
        spec_id="spec-1",
        item=NormalizedSubscriptionItem(
            item_id="v1",
            kind="video",
            title="标题",
            url=url,
            author_name="某UP主",
            cover_url="https://example.com/cover.jpg",
            summary="简介",
            stats={"点赞": 10},
        ),
        reason="new_item",
    )


class _FakeBackend:
    def __init__(self, *, available: bool = True, png: bytes = b"", error: bool = False) -> None:
        self.available = available
        self._png = png
        self._error = error

    def render_card(self, payload: dict) -> bytes:
        if self._error:
            raise RuntimeError("render boom")
        return self._png


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        bot_persona_display_name="",
        bot_persona_avatar_url="",
        bot_card_cache_max_bytes=0,
    )


def test_subscription_item_to_parse_maps_fields() -> None:
    parse = subscription_item_to_parse(_candidate().item, _spec())
    assert parse.identity is not None
    assert parse.identity.platform == "bilibili"
    assert parse.identity.item_id == "v1"
    assert parse.identity.item_kind == "video"
    assert parse.identity.canonical_url == "https://example.com/v"
    assert parse.content is not None
    assert parse.content.title == "标题"
    assert parse.content.summary == "简介"
    assert parse.creator is not None
    assert parse.creator.name == "某UP主"
    assert parse.engagement.like_count == 10
    assert parse.content.platform_extra.get("page_type") == "video"
    assert parse.media[0].url == "https://example.com/cover.jpg"


def test_subscription_item_to_parse_unknown_kind_has_empty_page_type() -> None:
    item = NormalizedSubscriptionItem(item_id="s1", kind="song", title="歌")
    parse = subscription_item_to_parse(item, _spec(platform="netease"))
    assert parse.identity is not None
    assert parse.content is not None
    assert parse.content.platform_extra.get("page_type", "") == ""
    assert parse.identity.item_kind == "song"


def test_push_capability_mixed_with_images() -> None:
    capability = build_subscription_push_capability(
        _TEXT, [{"file": "/tmp/card.png"}]
    )
    message = IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="group:1",
        session_type=SessionType.GROUP,
        sender_id="u",
    )
    result = capability(message, None)
    assert result.kind == "mixed"
    assert result.body == _TEXT
    assert result.images == [{"type": "image", "file": "/tmp/card.png"}]
    assert result.audit_tags == ["subscription_push"]


def test_push_capability_text_fallback_without_images() -> None:
    capability = build_subscription_push_capability(_TEXT)
    message = IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:2",
        session_type=SessionType.PRIVATE,
        sender_id="u",
    )
    result = capability(message, None)
    assert result.kind == "text"
    assert result.images == []


def test_render_push_card_success_writes_png(tmp_path) -> None:
    backend = _FakeBackend(png=b"png-bytes")
    card = render_subscription_push_card(
        backend,
        _candidate(platform="unknown_platform"),
        _spec(platform="unknown_platform"),
        config=_config(),
        card_dir=str(tmp_path),
    )
    assert card is not None
    path = tmp_path / card["file"].replace("\\", "/").split("/")[-1]
    assert path.is_file()
    assert path.read_bytes() == b"png-bytes"


def test_render_push_card_falls_back_without_url(tmp_path) -> None:
    backend = _FakeBackend(png=b"png-bytes")
    card = render_subscription_push_card(
        backend,
        _candidate(url=""),
        _spec(),
        config=_config(),
        card_dir=str(tmp_path),
    )
    assert card is None


def test_render_push_card_falls_back_on_backend_unavailable(tmp_path) -> None:
    backend = _FakeBackend(available=False, png=b"png-bytes")
    card = render_subscription_push_card(
        backend,
        _candidate(),
        _spec(),
        config=_config(),
        card_dir=str(tmp_path),
    )
    assert card is None


def test_render_push_card_falls_back_on_render_error(tmp_path) -> None:
    backend = _FakeBackend(error=True)
    card = render_subscription_push_card(
        backend,
        _candidate(),
        _spec(),
        config=_config(),
        card_dir=str(tmp_path),
    )
    assert card is None
