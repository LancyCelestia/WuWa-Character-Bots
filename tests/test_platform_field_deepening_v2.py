"""六平台字段深化（交接 §10.4）离线 fixture 测试：全部不联网。

覆盖：B站分P/时长、小红书全图集+视频直链、YouTube 时长/简介/作者统计、
Pixiv 分镜媒体/作者结构化/R18 分类、微博全图/视频/作者字段。
"""

from __future__ import annotations

import re

from plugins.bot_unified_runtime.sources.parsers import (
    platforms_bilibili,
    platforms_generic,
    platforms_pixiv,
    platforms_weibo,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError


def test_truncate_keep_links_preserves_self_written_links() -> None:
    short = "短签名"
    assert platforms_generic._truncate_keep_links(short, 200) == short
    long_text = "博主简介" * 60 + " 合作邮箱 x@example.com"
    truncated = platforms_generic._truncate_keep_links(long_text, 80)
    assert "…" in truncated
    assert "x@example.com" not in truncated  # 邮箱非 http 链接，不保证
    with_link = "简介文字" * 30 + " 其他平台 https://b23.tv/abc123"
    kept = platforms_generic._truncate_keep_links(with_link, 40)
    assert "https://b23.tv/abc123" in kept
    # URL 恰被 limit 切断：回退到链接起点，不残留半个链接。
    half_cut = platforms_generic._truncate_keep_links("正文" * 30 + " https://example.com/path" * 3, 64)
    assert "…" in half_cut
    assert re.search(r"https?://\S+$", half_cut) or "https://" not in half_cut[-20:]


# ---------- B 站 ----------

_BILI_VIEW_PAYLOAD = {
    "code": 0,
    "data": {
        "bvid": "BV1xx411c7mD",
        "aid": 1001,
        "title": "测试视频",
        "pic": "https://i0.hdslb.com/bfs/archive/cover.jpg",
        "desc": "视频简介文字",
        "tname": "动画",
        "duration": 878,
        "pubdate": 1756540800,
        "owner": {"mid": 42, "name": "测试UP", "face": "https://i0.hdslb.com/face.jpg"},
        "stat": {
            "view": 1000, "danmaku": 10, "reply": 3,
            "like": 50, "coin": 7, "favorite": 20, "share": 2,
        },
        "pages": [
            {"cid": 1, "part": "第一P", "duration": 500},
            {"cid": 2, "part": "第二P", "duration": 378},
        ],
    },
}


def _bili_json(url: str, **kwargs):
    if "/x/web-interface/view" in url or "/view?" in url:
        return _BILI_VIEW_PAYLOAD
    raise ParseHttpError("bilibili: fixture only provides view api")


def test_bilibili_video_pages_and_engagement(monkeypatch) -> None:
    monkeypatch.setattr(platforms_bilibili, "http_get_json", _bili_json)
    item = platforms_bilibili.parse_bilibili(
        "https://www.bilibili.com/video/BV1xx411c7mD"
    )
    assert item.identity is not None
    assert item.identity.item_kind == "video"
    assert item.content is not None
    assert item.content.title == "测试视频"
    assert item.content.published_at is not None
    # 分 P 列表进 platform_extra（卡片「分P列表」区块数据源）。
    episodes = item.content.platform_extra.get("episodes")
    assert episodes is not None
    assert len(episodes) == 2
    assert episodes[0]["title"] == "第一P"
    assert episodes[0]["duration_seconds"] == 500
    # 时长进 video 资产。
    video_asset = next(a for a in item.media if a.asset_type == "video")
    assert video_asset.duration_ms == 878000
    # 互动与作者。
    assert item.engagement.view_count == 1000
    assert item.engagement.coin_count == 7
    assert item.creator is not None
    assert item.creator.name == "测试UP"


# ---------- 小红书 ----------

_XHS_HTML = """<html><script>window.__INITIAL_STATE__={
  "note": {"noteDetailMap": {"note1": {"note": {
    "noteId": "note1",
    "title": "测试笔记",
    "desc": "笔记正文",
    "type": "video",
    "user": {"userId": "u1", "nickname": "博主", "avatar": "https://xhs/avatar.jpg"},
    "imageList": [
      {"urlDefault": "https://xhs/p1.jpg"},
      {"urlDefault": "https://xhs/p2.jpg"}
    ],
    "video": {
      "media": {"stream": {"h264": [{"url": "https://sns-video-hw.xhscdn.com/v.mp4"}]}},
      "width": 1280, "height": 720, "duration": 12
    },
    "interactInfo": {"likedCount": 100, "collectedCount": 20, "commentCount": 3}
  }}}}
};</script></html>"""


def test_xiaohongshu_note_full_images_and_video_stream(monkeypatch) -> None:
    monkeypatch.setattr(
        platforms_generic,
        "http_get_text",
        lambda url, **kwargs: (url, _XHS_HTML),
    )
    item = platforms_generic._xhs_from_initial_state(_XHS_HTML, "https://www.xiaohongshu.com/explore/note1")
    assert item is not None
    assert item.identity is not None
    assert item.identity.item_kind == "video"
    # 全图集 + 视频直链（sns-video 无水印）。
    image_assets = [a for a in item.media if a.asset_type == "image"]
    assert [a.url for a in image_assets] == [
        "https://xhs/p1.jpg", "https://xhs/p2.jpg",
    ]
    video_asset = next(a for a in item.media if a.asset_type == "video")
    assert video_asset.url == "https://sns-video-hw.xhscdn.com/v.mp4"
    assert video_asset.width == 1280
    assert video_asset.height == 720
    assert video_asset.duration_ms == 12000
    # 互动与作者。
    assert item.engagement.like_count == 100
    assert item.creator is not None
    assert item.creator.name == "博主"


# ---------- YouTube ----------

_YOUTUBE_OEMBED = {
    "title": "油管测试视频",
    "author_name": "测试频道",
    "author_url": "https://www.youtube.com/@testchannel",
    "thumbnail_url": "https://i.ytimg.com/thumb.jpg",
}

_YOUTUBE_WATCH_HTML = """
<html><body>
<script>
var ytInitialPlayerResponse = {
  "videoDetails": {
    "viewCount":"1234",
    "lengthSeconds":"300",
    "shortDescription":"视频简介",
    "author":"测试频道",
    "authorId":"UCabc"
  },
  "microformat": {"playerMicroformatRenderer": {"publishDate":"2026-08-30"}},
  "channelUrl":"https://www.youtube.com/channel/UCabc",
  "avatar":{"thumbnails":[{"url":"https://yt3.ggpht.com/avatar.jpg"}]},
  "ownerBadges": [{"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_VERIFIED"}}]
};
</script>
</body></html>
"""

_YOUTUBE_ABOUT_HTML = """
<html><body>
<script>
var ytInitialData = {
  "header": {
    "pageHeaderViewModel": {
      "content": {"pageHeaderViewModel": {"metadata": {"contentMetadataViewModel": {
        "joinedDateText":{"content":"2020年1月1日"},
        "subscriberCountText":{"content":"5.6万位订阅者"},
        "videoCountText":{"content":"123"},
        "description":"频道简介文字",
        "verified":true
      }}}}
    }
  }
};
</script>
</body></html>
"""


def _youtube_get_text(url: str, **kwargs):
    if "/about" in url:
        return url, _YOUTUBE_ABOUT_HTML
    return url, _YOUTUBE_WATCH_HTML


def _youtube_get_json(url: str, **kwargs):
    if "oembed" in url:
        return _YOUTUBE_OEMBED
    raise ParseHttpError("youtube: fixture only provides oembed")


def test_youtube_duration_desc_and_author_stats(monkeypatch) -> None:
    monkeypatch.setattr(platforms_generic, "http_get_text", _youtube_get_text)
    monkeypatch.setattr(platforms_generic, "http_get_json", _youtube_get_json)
    item = platforms_generic.parse_youtube(
        "https://www.youtube.com/watch?v=abc1234567"
    )
    assert item.identity is not None
    assert item.identity.item_kind == "video"
    assert item.content is not None
    assert item.content.title == "油管测试视频"
    # 视频简介进 summary；发布时间进 content。
    assert "视频简介" in item.content.summary
    assert item.content.published_at is not None
    # 时长进 video 资产（lengthSeconds=300）。
    video_asset = next(a for a in item.media if a.asset_type == "video")
    assert video_asset.duration_ms == 300000
    # 互动与作者统计（订阅→follower、视频数→video_count、认证、频道 ID）。
    assert item.engagement.view_count == 1234
    assert item.creator is not None
    assert item.creator.name == "测试频道"
    assert item.creator.platform_creator_id == "UCabc"
    assert item.creator.follower_count == 56000
    assert item.creator.video_count == 123
    assert item.creator.verification is not None
    assert item.creator.verification.verified is True


# ---------- Pixiv ----------

def _pixiv_json(url: str, **kwargs):
    if "/ajax/illust/12345/pages" in url:
        return {
            "body": [
                {"width": 1280, "height": 1024, "urls": {"original": "https://i.pximg.net/p1.png"}},
                {"width": 800, "height": 600, "urls": {"regular": "https://i.pximg.net/p2.jpg"}},
            ]
        }
    if "/ajax/user/987/profile/all" in url:
        return {"body": {"illusts": {"a": None, "b": None}, "manga": {}, "novels": {"c": None}}}
    if "/ajax/user/987?full=1" in url:
        return {"body": {"follower": 100, "following": 5}}
    return {
        "body": {
            "id": 12345,
            "title": "测试插画",
            "userName": "画师",
            "userId": 987,
            "illustType": 0,
            "x_restrict": 1,
            "createDate": "2026-08-30T10:00:00+09:00",
            "width": 1280,
            "height": 1024,
            "pageCount": 2,
            "viewCount": 300,
            "likeCount": 40,
            "bookmarkCount": 15,
            "commentCount": 2,
            "description": "插画简介",
            "tags": {"tags": [{"tag": "测试"}]},
        }
    }


def test_pixiv_pages_media_author_and_r18(monkeypatch) -> None:
    monkeypatch.setattr(platforms_pixiv, "http_get_json", _pixiv_json)
    item = platforms_pixiv.parse_pixiv("https://www.pixiv.net/artworks/12345")
    assert item.identity is not None
    assert item.identity.item_kind == "illust"
    assert item.content is not None
    assert item.content.published_at is not None
    assert item.content.published_at.year == 2026
    # 全部分镜 URL/宽高进 media（第 0 位是 embed 代理封面）。
    image_assets = [a for a in item.media if a.asset_type == "image"]
    assert len(image_assets) == 3
    assert image_assets[0].url == "https://embed.pixiv.net/artwork.php?illust_id=12345"
    assert image_assets[1].url == "https://i.pximg.net/p1.png"
    assert image_assets[1].width == 1280
    assert image_assets[1].height == 1024
    assert image_assets[2].url == "https://i.pximg.net/p2.jpg"
    # 作者结构化统计。
    assert item.creator is not None
    assert item.creator.platform_creator_id == "987"
    assert item.creator.follower_count == 100
    assert item.creator.following_count == 5
    assert item.creator.platform_extra.get("illusts") == 2
    assert item.creator.platform_extra.get("novels") == 1
    # R-18 诚实分类。
    assert item.engagement.platform_extra.get("分级") == "R-18"
    # 封面走 embed 代理。
    assert item.media[0].url == "https://embed.pixiv.net/artwork.php?illust_id=12345"


# ---------- 微博 ----------

def test_weibo_status_images_video_and_author(monkeypatch) -> None:
    # 纯函数路径：status dict → ParsedContent，无网络。
    status = {
        "id": 1001,
        "text_raw": "微博正文第一行\n第二行",
        "created_at": "Wed Aug 26 17:35:31 +0800 2026",
        "user": {
            "id": 555,
            "screen_name": "微博博主",
            "profile_image_url": "https://wx1.sinaimg.cn/avatar.jpg",
            "description": "博主简介",
            "followers_count": "1.2万",
            "follow_count": 300,
            "statuses_count": 999,
            "verified": True,
            "verified_reason": "微博认证",
        },
        "reposts_count": 10,
        "comments_count": 3,
        "attitudes_count": 50,
        "favorites_count": 8,
        "pic_infos": {
            "p1": {"largest": {"url": "https://wx1.sinaimg.cn/large/p1.jpg"}},
            "p2": {"largest": {"url": "https://wx1.sinaimg.cn/large/p2.jpg"}},
        },
        "page_info": {
            "type": "video",
            "media_info": {
                "stream_url_hd": "https://f.video.weibocdn.com/v.mp4",
                "duration": 30,
                "width": 1280,
                "height": 720,
            },
            "page_pic": {"url": "https://wx1.sinaimg.cn/video.jpg"},
        },
    }
    item = platforms_weibo._weibo_status_result(status, "https://weibo.com/1/abc")
    assert item.identity is not None
    assert item.identity.item_kind == "post"
    assert item.content is not None
    assert item.content.published_at is not None
    # 全图 + 视频进 media。
    image_assets = [a for a in item.media if a.asset_type == "image"]
    assert [a.url for a in image_assets] == [
        "https://wx1.sinaimg.cn/large/p1.jpg",
        "https://wx1.sinaimg.cn/large/p2.jpg",
    ]
    video_asset = next(a for a in item.media if a.asset_type == "video")
    assert video_asset.url == "https://f.video.weibocdn.com/v.mp4"
    assert video_asset.duration_ms == 30000
    assert video_asset.width == 1280
    # 作者结构化统计。
    assert item.creator is not None
    assert item.creator.name == "微博博主"
    assert item.creator.follower_count == 12000
    assert item.creator.following_count == 300
    assert item.creator.post_count == 999
    assert item.creator.verification is not None
    assert item.creator.verification.verified is True
    assert item.creator.verification.label == "微博认证"
    # 互动。
    assert item.engagement.repost_count == 10
    assert item.engagement.favorite_count == 8
