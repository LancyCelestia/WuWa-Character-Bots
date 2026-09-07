from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.sources.parsers import platforms_telegram
from plugins.bot_unified_runtime.sources.parsers.context import ParseFailure

_HTML = """
<html>
<head><meta property="og:title" content="示例频道：新消息" />
<meta property="og:description" content="频道正文" />
<meta property="og:image" content="https://cdn.example/cover.jpg" /></head>
<body>
<div class="tgme_channel_info_header">
  <div class="tgme_channel_info_header_title">示例频道</div>
  <div class="tgme_channel_info_header_avatar"><img src="https://cdn.example/avatar.jpg" /></div>
  <div class="tgme_channel_info_description">频道简介文字</div>
  <span class="tgme_channel_info_counter"><span>1.2万</span> subscribers</span>
</div>
<div class="tgme_widget_message_wrap" data-post="example/42">
  <div class="tgme_widget_message_text">频道正文<br>第二行</div>
  <time datetime="2026-08-30T10:00:00+00:00"></time>
  <span class="tgme_widget_message_views">1.2K</span>
  <span class="tgme_widget_message_reactions">❤️ 34</span>
  <span class="tgme_widget_message_forwards">5</span>
  <img class="tgme_widget_message_photo" src="https://cdn.example/p1.jpg" />
  <img class="tgme_widget_message_photo" src="https://cdn.example/p2.jpg" />
  <video class="tgme_widget_message_video" src="https://cdn.example/v.mp4"></video>
</div>
</body></html>
"""


def test_public_telegram_message_maps_content_media_and_engagement(monkeypatch) -> None:
    monkeypatch.setattr(
        platforms_telegram,
        "http_get_text",
        lambda url, **kwargs: (url, _HTML),
    )

    result = platforms_telegram.parse_telegram(
        "https://t.me/example/42",
    )

    assert result.identity is not None
    assert result.identity.platform == "telegram"
    assert result.identity.item_id == "42"
    assert result.content is not None
    assert result.content.title == "示例频道：新消息"
    assert result.content.summary == "频道正文\n第二行"
    assert result.content.published_at is not None
    assert result.content.published_at.year == 2026
    # 媒体：封面 + 图集 + 视频直链。
    assert [asset.asset_type for asset in result.media] == ["image", "image", "image", "video"]
    assert [asset.url for asset in result.media[:3]] == [
        "https://cdn.example/cover.jpg",
        "https://cdn.example/p1.jpg",
        "https://cdn.example/p2.jpg",
    ]
    video_asset = result.media[3]
    assert video_asset.url == "https://cdn.example/v.mp4"
    assert video_asset.preview_url == "https://cdn.example/cover.jpg"
    # 互动。
    assert result.engagement.view_count == 1200
    assert result.engagement.heart_count == 34
    assert result.engagement.repost_count == 5
    # 频道资料。
    assert result.creator is not None
    assert result.creator.name == "示例频道"
    assert result.creator.handle == "example"
    assert result.creator.avatar_url == "https://cdn.example/avatar.jpg"
    assert result.creator.signature == "频道简介文字"
    assert result.creator.follower_count == 12000


@pytest.mark.parametrize("url", ["https://t.me/+private", "https://telegram.me/joinchat/abc"])
def test_private_telegram_invite_is_rejected(url: str) -> None:
    with pytest.raises(ParseFailure):
        platforms_telegram.parse_telegram(url)


def test_telegram_me_domain_is_supported(monkeypatch) -> None:
    monkeypatch.setattr(
        platforms_telegram,
        "http_get_text",
        lambda url, **kwargs: (url, _HTML),
    )
    result = platforms_telegram.parse_telegram("https://telegram.me/example/42")
    assert result.identity is not None
    assert result.identity.item_id == "42"
