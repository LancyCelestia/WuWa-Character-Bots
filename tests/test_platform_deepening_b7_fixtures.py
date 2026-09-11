"""B7 平台深化残余：TG/YouTube/微博/小红书离线 fixture 回归，全部不联网。

- Telegram：多消息块选择（置顶/旧消息在前）、嵌套 DOM（回复引用块、
  内联标签、实体）、多 reaction、编辑/删除事件语义；
- YouTube：shorts 直链归一成 watch 链接（oEmbed 收到归一化 URL）；
- 微博：长文补全（statuses/extend）成功/失败两路、置顶与 card_group
  等额外键的变体不干扰 status 规整；
- 小红书：user_posted 载荷形状（含正文时间/互动字段）纯解析。
"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.sources.parsers import (
    platforms_generic,
    platforms_telegram,
    platforms_weibo,
)
from plugins.bot_unified_runtime.sources.subscriptions.xiaohongshu_adapter import (
    XiaohongshuAdapter,
)


def _tg_page(body_blocks: str) -> str:
    return (
        '<html><head>'
        '<meta property="og:title" content="示例频道：新消息" />'
        '<meta property="og:description" content="频道正文兜底" />'
        '<meta property="og:image" content="https://cdn.example/cover.jpg" />'
        f'</head><body>{body_blocks}</body></html>'
    )


_TG_FULL_BLOCK = """
<div class="tgme_widget_message_wrap" data-post="example/42">
  <div class="tgme_widget_message_reply">
    <a class="tgme_widget_message_reply" href="https://t.me/example/41">
      <div class="tgme_widget_message_reply_title">置顶：频道公告</div>
    </a>
  </div>
  <div class="tgme_widget_message_text" dir="auto">完整 <b>重点</b><br/>尾行 &amp; &quot;引用&quot;</div>
  <div class="tgme_widget_message_footer">
    <span class="tgme_widget_message_views">2.5K</span>
    <span class="tgme_widget_message_reactions"><span class="tgme_widget_message_reaction"><tg-emoji emoji-id="heart">❤</tg-emoji>1.2K</span><span class="tgme_widget_message_reaction">🔥 12</span></span>
    <span class="tgme_widget_message_forwards">8</span>
    <time datetime="2026-08-30T10:00:00+00:00">10:00</time>
    <span class="tgme_widget_message_edited"><time datetime="2026-08-30T11:30:00+00:00">edited 11:30</time></span>
  </div>
</div>
"""


# ---------- Telegram ----------


def test_telegram_picks_requested_block_when_pinned_or_older_first(monkeypatch) -> None:
    """页面含多条消息（置顶/旧消息块在前）时，按 data-post 选中请求的块。"""
    page = _tg_page(
        '<div class="tgme_widget_message_wrap" data-post="example/40">'
        '<div class="tgme_widget_message_text">旧消息不应被选中</div></div>'
        + _TG_FULL_BLOCK
    )
    monkeypatch.setattr(
        platforms_telegram, "http_get_text", lambda url, **kwargs: (url, page)
    )

    result = platforms_telegram.parse_telegram("https://t.me/example/42")

    assert result.identity.item_id == "42"
    assert "旧消息不应被选中" not in result.content.summary
    assert "完整" in result.content.summary
    assert result.engagement.view_count == 2500


def test_telegram_nested_dom_reply_quote_and_entities(monkeypatch) -> None:
    """嵌套 DOM：回复引用块不混入正文；实体反转义。"""
    page = _tg_page(_TG_FULL_BLOCK)
    monkeypatch.setattr(
        platforms_telegram, "http_get_text", lambda url, **kwargs: (url, page)
    )

    result = platforms_telegram.parse_telegram("https://t.me/example/42")

    summary = result.content.summary
    assert "置顶：频道公告" not in summary  # 回复引用块不进正文
    assert "&amp;" not in summary and "&quot;" not in summary
    # 内联闭合标签（</b>）不再截断正文：`<br/>` 转换行，实体反转义。
    assert summary == "完整 重点\n尾行 & \"引用\""


def test_telegram_leading_inline_tag_keeps_full_summary(monkeypatch) -> None:
    """行内标签开头（<b>加粗</b>…）时正文不再截断，标签后文字保留。"""
    page = _tg_page(
        '<div class="tgme_widget_message_wrap" data-post="example/42">'
        '<div class="tgme_widget_message_text" dir="auto"><b>加粗开头</b> 后续文字</div>'
        "</div>"
    )
    monkeypatch.setattr(
        platforms_telegram, "http_get_text", lambda url, **kwargs: (url, page)
    )

    result = platforms_telegram.parse_telegram("https://t.me/example/42")

    assert result.content.summary == "加粗开头 后续文字"


def test_telegram_inline_markup_link_and_newlines_preserved(monkeypatch) -> None:
    """回归：内联加粗/链接/换行混合形态，正文完整提取（不截断、不吞实体）。"""
    page = _tg_page(
        '<div class="tgme_widget_message_wrap" data-post="example/42">'
        '<div class="tgme_widget_message_text" dir="auto">'
        '<b>加粗</b> 与 <a href="https://example.com/a">链接</a><br/>'
        "<i>斜体</i>第二行 &amp; 符号<br/>尾行</div></div>"
    )
    monkeypatch.setattr(
        platforms_telegram, "http_get_text", lambda url, **kwargs: (url, page)
    )

    result = platforms_telegram.parse_telegram("https://t.me/example/42")

    assert result.content.summary == "加粗 与 链接\n斜体第二行 & 符号\n尾行"


def test_telegram_edit_time_does_not_override_publish_time(monkeypatch) -> None:
    """编辑事件：块内出现第二个 <time>（edited）时发布时间权威不变。"""
    page = _tg_page(_TG_FULL_BLOCK)
    monkeypatch.setattr(
        platforms_telegram, "http_get_text", lambda url, **kwargs: (url, page)
    )

    result = platforms_telegram.parse_telegram("https://t.me/example/42")

    assert result.content.published_at is not None
    assert result.content.published_at.hour == 10
    assert result.content.published_at.minute == 0


def test_telegram_deleted_message_falls_back_to_og(monkeypatch) -> None:
    """删除事件：页面无 data-post 块时回退 og 元信息，不抛错。"""
    deleted = (
        "<html><head>"
        '<meta property="og:title" content="Telegram: Contact @example" />'
        '<meta property="og:description" content="这条消息已被删除" />'
        "</head><body></body></html>"
    )
    monkeypatch.setattr(
        platforms_telegram, "http_get_text", lambda url, **kwargs: (url, deleted)
    )

    result = platforms_telegram.parse_telegram("https://t.me/example/42")

    assert result.identity.item_id == "42"
    assert result.content.summary == "这条消息已被删除"


def test_telegram_multi_reaction_takes_first_and_parses_k_suffix(monkeypatch) -> None:
    """多 reaction：取首个反应计数并解析 K/M/万 缩写（1.2K→1200）。"""
    page = _tg_page(_TG_FULL_BLOCK)
    monkeypatch.setattr(
        platforms_telegram, "http_get_text", lambda url, **kwargs: (url, page)
    )

    result = platforms_telegram.parse_telegram("https://t.me/example/42")

    assert result.engagement.heart_count == 1200
    assert result.engagement.view_count == 2500
    assert result.engagement.repost_count == 8


# ---------- YouTube shorts ----------


def test_youtube_shorts_urls_normalize_to_watch(monkeypatch) -> None:
    """shorts 直链（含无 www/带参数形态）归一成 watch 链接再走 oEmbed。"""
    seen: dict[str, str] = {}

    def fake_json(url: str, **kwargs: Any) -> dict[str, Any]:
        seen["url"] = url
        return {
            "title": "Short 标题",
            "author_name": "UP主",
            "author_url": "https://www.youtube.com/@handle",
            "thumbnail_url": "https://i.ytimg.com/vi/abc12345678/hqdefault.jpg",
        }

    monkeypatch.setattr(platforms_generic, "http_get_json", fake_json)
    monkeypatch.setattr(platforms_generic, "_youtube_watch_enrich", lambda url, proxy="": {})
    monkeypatch.setattr(platforms_generic, "_youtube_innertube", lambda video_id, proxy="": {})
    monkeypatch.setattr(platforms_generic, "_youtube_about_enrich", lambda channel_url, proxy="": {})

    for shorts_url in (
        "https://www.youtube.com/shorts/abc12345678",
        "https://youtube.com/shorts/abc12345678?feature=share",
    ):
        seen.clear()
        result = platforms_generic.parse_youtube(shorts_url)
        assert result.identity.item_id == "abc12345678"
        assert result.identity.canonical_url == (
            "https://www.youtube.com/watch?v=abc12345678"
        )
        # oEmbed 收到归一化 watch 链接，而不是原始 shorts 链接。
        assert "watch%3Fv%3Dabc12345678" in seen["url"]
        assert "shorts" not in seen["url"]
        # 封面原图化 + 标题来自 oEmbed（cover 收进 content.platform_extra）。
        assert result.content.platform_extra["cover_url"] == (
            "https://i.ytimg.com/vi/abc12345678/maxresdefault.jpg"
        )
        assert result.content.title == "Short 标题"


# ---------- 微博 ----------


def _weibo_status(**overrides: Any) -> dict[str, Any]:
    status: dict[str, Any] = {
        "id": 1002,
        "text_raw": "短正文…全文",
        "created_at": "Wed Aug 26 17:35:31 +0800 2026",
        "user": {"id": 555, "screen_name": "微博博主"},
        "reposts_count": 1,
        "comments_count": 2,
        "attitudes_count": 3,
    }
    status.update(overrides)
    return status


def test_weibo_longtext_extend_api_fills_full_text(monkeypatch) -> None:
    """isLongText=1：经 statuses/extend 补全长文，摘要采用全文。"""
    calls: list[str] = []

    def fake_json(url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append(url)
        return {"data": {"longTextContent": "长文第一行<br/>长文第二行，远比截断版长"}}

    monkeypatch.setattr(platforms_weibo, "http_get_json", fake_json)

    item = platforms_weibo._weibo_status_result(
        _weibo_status(isLongText=1), "https://weibo.com/1/abc"
    )

    assert calls and "extend" in calls[0]
    assert "长文第一行" in item.content.summary
    assert "长文第二行" in item.content.summary


def test_weibo_longtext_failure_keeps_truncated_text(monkeypatch) -> None:
    """补全文接口失败不致命：回退截断正文。"""

    def fake_json(url: str, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("network down")

    monkeypatch.setattr(platforms_weibo, "http_get_json", fake_json)

    item = platforms_weibo._weibo_status_result(
        _weibo_status(isLongText=1), "https://weibo.com/1/abc"
    )

    assert "短正文" in item.content.summary


def test_weibo_without_longtext_flag_skips_extend(monkeypatch) -> None:
    """未标记长文时不发起 extend 请求。"""
    calls: list[str] = []

    def fake_json(url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append(url)
        return {}

    monkeypatch.setattr(platforms_weibo, "http_get_json", fake_json)

    platforms_weibo._weibo_status_result(_weibo_status(), "https://weibo.com/1/abc")

    assert calls == []


def test_weibo_pinned_and_card_group_keys_are_ignored(monkeypatch) -> None:
    """置顶/card_group 变体：profile API 的额外结构键不干扰 status 规整。"""
    monkeypatch.setattr(platforms_weibo, "http_get_json", lambda url, **kw: {})

    item = platforms_weibo._weibo_status_result(
        _weibo_status(
            isTop=1,
            title={"text": "置顶"},
            card_group=[{"card_type": 9, "mblog": {}}],
            cardid="2000001",
        ),
        "https://weibo.com/1/abc",
    )

    assert item.identity.item_kind == "post"
    assert "短正文" in item.content.summary
    assert item.content.platform_extra.get("badge") == "微博"


# ---------- 小红书 user_posted ----------


def _xhs_spec() -> Any:
    from plugins.bot_unified_runtime.contracts.subscription import SubscriptionSpec

    return SubscriptionSpec(
        id="xiaohongshu:creator:u1",
        platform="xiaohongshu",
        target_kind="creator",
        target_id="u1",
        target_name="小红书作者",
        created_at="2026-09-01T00:00:00+00:00",
    )


def test_xhs_user_posted_note_fields_parse_offline() -> None:
    """user_posted 笔记：时间/互动/封面/作者字段纯解析成条目。"""
    adapter = XiaohongshuAdapter(backend=object())
    note = {
        "note_id": "abc123",
        "type": "video",
        "display_title": "笔记标题",
        "publish_time": "06-12",
        "cover": {"url": "https://sns-img.xhscdn.com/cover.jpg"},
        "interact_info": {
            "liked_count": "1.2万",
            "collected_count": "300",
            "comment_count": "45",
        },
        "user": {"nickname": "小红书作者"},
    }

    item = adapter._build_item(note, _xhs_spec())

    assert item.item_id == "abc123"
    assert item.kind == "video"
    assert item.title == "笔记标题"
    assert item.url == "https://www.xiaohongshu.com/explore/abc123"
    assert item.author_name == "小红书作者"
    assert item.cover_url == "https://sns-img.xhscdn.com/cover.jpg"
    assert item.published_at == "06-12"
    assert item.stats == {"点赞": "1.2万", "收藏": "300", "评论": "45"}


def test_xhs_user_posted_missing_time_yields_empty_published_at() -> None:
    adapter = XiaohongshuAdapter(backend=object())
    item = adapter._build_item({"note_id": "n2"}, _xhs_spec())
    assert item.published_at == ""
    assert item.author_name == "小红书作者"  # 回退 spec.target_name


def test_xhs_extract_notes_supports_user_posted_shape() -> None:
    """_extract_notes 兼容 data.user_posted.notes 嵌套与列表包裹形状。"""
    nested = {"data": {"user_posted": {"notes": [{"note_id": "n1"}]}}}
    assert XiaohongshuAdapter._extract_notes(nested) == [{"note_id": "n1"}]

    wrapped = [{"data": {"notes": []}}, {"data": {"notes": [{"note_id": "n2"}]}}]
    assert XiaohongshuAdapter._extract_notes(wrapped) == [{"note_id": "n2"}]

    assert XiaohongshuAdapter._extract_notes({"data": {}}) == []
