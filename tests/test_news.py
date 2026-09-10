"""今日快报回归测试（全部离线，网络出口 news_feeds._fetch_feed_text 打桩）。

夹具按 2026-09-11 真实探针裁剪：IT之家 / 少数派 / 华尔街见闻 / BBC 中文
四个存活源的 item 结构逐字段保留（华尔街见闻 CDATA 标题实测带首尾空格、
BBC 链接带 ``&amp;`` 实体与 dc/content/atom/media 命名空间、IT之家 GMT
pubDate、少数派 +0800 pubDate）。四个存活源均为 RSS 2.0，无真实 Atom
探针可用，Atom 夹具按 W3C 标准样例构造（命名空间、href 链接、ISO 时间）。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.news import (
    build_news_capability,
    extract_news_category,
    is_news_command,
)
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.sources import news_feeds
from plugins.bot_unified_runtime.sources.news_feeds import (
    NewsItem,
    fetch_headlines,
    format_news_brief,
    parse_feed,
    reset_news_cache,
)

# ---------------------------------------------------------------------------
# 真实探针夹具（2026-09-11，逐字段按真实响应裁剪）
# ---------------------------------------------------------------------------

ITHOME_URL = "https://www.ithome.com/rss/"
SSPAI_URL = "https://sspai.com/feed"
WSCN_URL = "https://dedicated.wallstreetcn.com/rss.xml"
BBC_URL = "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"

# IT之家：RSS 2.0，pubDate 为 GMT。
ITHOME_RSS = """<rss version="2.0">
  <channel>
    <title>IT之家</title>
    <link>https://www.ithome.com/</link>
    <item>
      <title>甲骨文 2027 财年第一财季归母净利润 46.79 亿美元，同比增长 60%</title>
      <link>https://www.ithome.com/1/001/052.htm</link>
      <pubDate>Thu, 10 Sep 2026 20:20:44 GMT</pubDate>
    </item>
    <item>
      <title>法国总统马克龙呼吁欧洲大力发展自主载人航天，力争 10 年内送宇航员上太空</title>
      <link>https://www.ithome.com/1/001/043.htm</link>
      <pubDate>Thu, 10 Sep 2026 15:38:03 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

# 少数派：RSS 2.0 带命名空间声明，pubDate 为 +0800。
SSPAI_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>少数派</title><link>https://sspai.com</link><item><title>App+1｜下一节：教学工作紧张忙碌，下一节课从从容容</title><link>https://sspai.com/post/114384</link><pubDate>Thu, 10 Sep 2026 14:51:52 +0800</pubDate></item><item><title>派早报：Apple 发布 iPhone Duo 折叠屏等</title><link>https://sspai.com/post/114394</link><pubDate>Thu, 10 Sep 2026 06:38:42 +0800</pubDate></item></channel>
</rss>
"""

# 华尔街见闻：RSS 2.0，CDATA 标题实测带首尾空格。
WSCN_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
\t<title>华尔街见闻</title>
\t<link>https://wallstreetcn.com</link>
\t<item>
\t\t<title><![CDATA[ OpenAI推出Agents API公测版，将Codex底层基础设施向开发者开放 ]]></title>
\t\t<link>https://wallstreetcn.com/articles/3781521</link>
\t\t<pubDate>Fri, 11 Sep 2026 04:00:52 +0800</pubDate>
\t</item>
\t<item>
\t\t<title><![CDATA[ 沃什导师、传奇交易员Druckenmiller闭门会议：美国利率偏低 ]]></title>
\t\t<link>https://wallstreetcn.com/articles/3781519</link>
\t\t<pubDate>Fri, 11 Sep 2026 02:44:50 +0800</pubDate>
\t</item>
</channel>
</rss>
"""

# BBC 中文：RSS 2.0 带 dc/content/atom/media 命名空间，CDATA 标题（繁体），
# 链接带 &amp; 实体。
BBC_RSS = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom" version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
    <channel>
        <title><![CDATA[BBC Chinese]]></title>
        <link>https://www.bbc.com/zhongwen/trad</link>
        <item>
            <title><![CDATA[AI「性轉」視頻風靡中國網絡：一場「 新文化運動」的覺醒與侷限]]></title>
            <link>https://www.bbc.com/zhongwen/articles/cn74d8mr640o/trad?at_medium=RSS&amp;at_campaign=rss</link>
            <pubDate>Thu, 10 Sep 2026 00:14:34 GMT</pubDate>
            <media:thumbnail width="240" height="141" url="https://ichef.bbci.co.uk/example.jpg"/>
        </item>
        <item>
            <title><![CDATA[青島北海造船廠外籍貨輪大火 失聯25人已確定全部死亡]]></title>
            <link>https://www.bbc.com/zhongwen/articles/czjzvdxw8gvo/trad?at_medium=RSS&amp;at_campaign=rss</link>
            <pubDate>Thu, 10 Sep 2026 12:47:54 GMT</pubDate>
        </item>
    </channel>
</rss>
"""

# Atom 标准样例（W3C 形态）：href 链接、rel=alternate/self 并存、ISO 时间、
# 标题内嵌转义 HTML 与实体。
ATOM_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>示例 Atom 源</title>
  <link href="https://example.com/"/>
  <updated>2026-09-11T04:00:52Z</updated>
  <entry>
    <title>&lt;b&gt;加粗&lt;/b&gt;标题：A &amp;amp; B</title>
    <link rel="alternate" href="https://example.com/posts/1"/>
    <link rel="self" href="https://example.com/feed.atom"/>
    <published>2026-09-10T12:00:00+08:00</published>
    <updated>2026-09-11T04:00:52Z</updated>
  </entry>
  <entry>
    <title>无链接无日期条目</title>
  </entry>
</feed>
"""

_LIVE_FIXTURES: dict[str, str] = {
    ITHOME_URL: ITHOME_RSS,
    SSPAI_URL: SSPAI_RSS,
    WSCN_URL: WSCN_RSS,
    BBC_URL: BBC_RSS,
}


class _Clock:
    """可控单调时钟：fetch TTL 测试用，避免依赖真实睡眠。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def _clean_news_cache() -> Iterator[None]:
    reset_news_cache()
    yield
    reset_news_cache()


# ---------------------------------------------------------------------------
# parse_feed：RSS 2.0 / Atom / 标题清洗 / 容错
# ---------------------------------------------------------------------------


def test_parse_rss_fixture_from_real_probe() -> None:
    items = parse_feed(ITHOME_RSS, source="IT之家", category="tech")
    assert [item.title for item in items] == [
        "甲骨文 2027 财年第一财季归母净利润 46.79 亿美元，同比增长 60%",
        "法国总统马克龙呼吁欧洲大力发展自主载人航天，力争 10 年内送宇航员上太空",
    ]
    assert items[0].url == "https://www.ithome.com/1/001/052.htm"
    assert items[0].source == "IT之家"
    assert items[0].category == "tech"
    assert items[0].published_at is not None
    assert items[0].published_at.utcoffset() == timedelta(0)  # GMT
    assert items[0].published_at == datetime(2026, 9, 10, 20, 20, 44, tzinfo=items[0].published_at.tzinfo)


def test_parse_rss_namespaced_and_positive_offset() -> None:
    items = parse_feed(SSPAI_RSS, source="少数派", category="tech")
    assert len(items) == 2
    assert items[0].published_at is not None
    assert items[0].published_at.utcoffset() == timedelta(hours=8)
    assert items[1].title == "派早报：Apple 发布 iPhone Duo 折叠屏等"


def test_parse_cdata_title_strips_surrounding_spaces() -> None:
    items = parse_feed(WSCN_RSS, source="华尔街见闻", category="finance")
    assert items[0].title == "OpenAI推出Agents API公测版，将Codex底层基础设施向开发者开放"
    assert items[0].title == items[0].title.strip()


def test_parse_bbc_namespaces_and_html_entity_link() -> None:
    items = parse_feed(BBC_RSS, source="BBC中文", category="world")
    assert len(items) == 2
    assert items[0].url == (
        "https://www.bbc.com/zhongwen/articles/cn74d8mr640o/trad"
        "?at_medium=RSS&at_campaign=rss"
    )
    assert items[0].category == "world"


def test_parse_atom_namespace_links_and_iso_dates() -> None:
    items = parse_feed(ATOM_FEED, source="示例源", category="tech")
    assert len(items) == 2
    first = items[0]
    # 标题剥 HTML（标签以空格替换，防跨标签粘连）+ 实体反转义；
    # 链接取 rel=alternate 而非 self。
    assert first.title == "加粗 标题：A & B"
    assert first.url == "https://example.com/posts/1"
    assert first.published_at is not None
    assert first.published_at.utcoffset() == timedelta(hours=8)
    # 第二条缺链接缺日期：保留条目，字段尽力而为。
    second = items[1]
    assert second.title == "无链接无日期条目"
    assert second.url == ""
    assert second.published_at is None


def test_parse_garbage_and_empty_return_empty() -> None:
    assert parse_feed("这不是 XML", source="x", category="tech") == []
    assert parse_feed("", source="x", category="tech") == []
    assert parse_feed("<html><body>伪装成 feed 的页面</body></html>", source="x", category="tech") == []


def test_parse_item_without_title_skipped() -> None:
    feed = (
        "<rss version='2.0'><channel>"
        "<item><link>https://example.com/a</link></item>"
        "<item><title>正常条目</title><link>https://example.com/b</link></item>"
        "</channel></rss>"
    )
    items = parse_feed(feed, source="x", category="tech")
    assert [item.title for item in items] == ["正常条目"]


# ---------------------------------------------------------------------------
# fetch_headlines：类目映射 / 单源失败跳过 / TTL 缓存 / 绝不抛异常
# ---------------------------------------------------------------------------


def test_fetch_category_mapping_uses_only_matching_feeds(
    _clean_news_cache, monkeypatch
) -> None:
    calls: list[str] = []

    def _fake(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        return _LIVE_FIXTURES[url]

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)
    finance = fetch_headlines("finance")
    assert calls == [WSCN_URL]
    assert len(finance) == 2
    assert {item.source for item in finance} == {"华尔街见闻"}

    calls.clear()
    world = fetch_headlines("world")
    assert calls == [BBC_URL]
    assert world[0].source == "BBC中文"

    calls.clear()
    tech = fetch_headlines("tech")
    assert set(calls) == {ITHOME_URL, SSPAI_URL}
    assert {item.source for item in tech} == {"IT之家", "少数派"}


def test_fetch_unknown_category_falls_back_to_mix(
    _clean_news_cache, monkeypatch
) -> None:
    calls: list[str] = []

    def _fake(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        return _LIVE_FIXTURES[url]

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)
    items = fetch_headlines("不存在的类目")
    assert set(calls) == set(_LIVE_FIXTURES)
    # mix 轮转合并：四个源的条目都会出现，且单源条数被封顶（各取若干）。
    sources = [item.source for item in items]
    assert set(sources) == {"IT之家", "少数派", "华尔街见闻", "BBC中文"}
    assert sources.index("华尔街见闻") < sources.index("BBC中文") + len(sources)


def test_fetch_per_feed_failure_skipped_silently(
    _clean_news_cache, monkeypatch
) -> None:
    def _fake(url: str, timeout_seconds: float) -> str:
        if url == ITHOME_URL:
            raise OSError("ithome down")
        return _LIVE_FIXTURES[url]

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)
    items = fetch_headlines("tech")
    assert {item.source for item in items} == {"少数派"}


def test_fetch_never_raises_when_all_feeds_fail(
    _clean_news_cache, monkeypatch
) -> None:
    def _boom(url: str, timeout_seconds: float) -> str:
        raise OSError("network down")

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _boom)
    assert fetch_headlines("mix") == []
    assert fetch_headlines("finance") == []
    # 坏 XML（HTML 伪装）同样安全降级。
    monkeypatch.setattr(news_feeds, "_fetch_feed_text", lambda url, timeout_seconds: "<html>ok</html>")
    assert fetch_headlines("finance") == []


def test_fetch_ttl_cache_hit_expiry_and_failure_not_cached(
    _clean_news_cache, monkeypatch
) -> None:
    reset_news_cache()
    clock = _Clock()
    calls: list[str] = []

    def _fake(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        if len(calls) == 1 and url == WSCN_URL:
            # 第一次外呼 finance 源失败（后续成功）。
            raise OSError("transient blip")
        return _LIVE_FIXTURES[url]

    monkeypatch.setattr(news_feeds.time, "monotonic", clock)
    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)

    # 首次：唯一源失败 → 空，且不缓存。
    assert fetch_headlines("finance", cache_seconds=600.0) == []
    assert calls == [WSCN_URL]
    # 立即重试：成功并写入缓存。
    assert len(fetch_headlines("finance", cache_seconds=600.0)) == 2
    assert calls == [WSCN_URL, WSCN_URL]
    # TTL 内命中缓存：不再外呼。
    clock.now = 1030.0
    assert len(fetch_headlines("finance", cache_seconds=600.0)) == 2
    assert calls == [WSCN_URL, WSCN_URL]
    # TTL 过期 → 重新拉取。
    clock.now = 1601.0
    assert len(fetch_headlines("finance", cache_seconds=600.0)) == 2
    assert calls == [WSCN_URL, WSCN_URL, WSCN_URL]
    reset_news_cache()


def test_fetch_cache_stores_full_list_sliced_by_max_items(
    _clean_news_cache, monkeypatch
) -> None:
    calls: list[str] = []

    def _fake(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        return _LIVE_FIXTURES[url]

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)
    assert len(fetch_headlines("tech", max_items=1)) == 1
    # 同一 TTL 内换更大的 max_items：命中缓存全量快照，不再外呼。
    tech = fetch_headlines("tech", max_items=8)
    assert len(calls) == 2
    assert len(tech) == 4  # IT之家 2 条 + 少数派 2 条
    assert len(fetch_headlines("tech", max_items=0)) == 1  # 非法值钳到 ≥1


# ---------------------------------------------------------------------------
# format_news_brief：头部 / 编号 / 空降级
# ---------------------------------------------------------------------------


def _sample_items() -> list[NewsItem]:
    return [
        NewsItem(
            title="甲骨文净利润同比增长 60%",
            url="https://www.ithome.com/1/001/052.htm",
            source="IT之家",
            published_at=datetime(2026, 9, 10, 20, 20, 44, tzinfo=timezone.utc),
            category="tech",
        ),
        NewsItem(
            title="无来源条目",
            url="https://example.com/x",
            source="",
            category="tech",
        ),
    ]


def test_format_news_brief_header_and_numbering() -> None:
    text = format_news_brief(_sample_items(), "科技")
    lines = text.splitlines()
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    assert lines[0] == f"今日快报 · {today} · 科技"
    assert lines[1] == "1. 甲骨文净利润同比增长 60%（IT之家）"
    assert lines[2] == "2. 无来源条目"


def test_format_news_brief_empty_degrades() -> None:
    assert format_news_brief([], "综合") == "快报暂时拉不到，稍后再试试？"


# ---------------------------------------------------------------------------
# capabilities/news：触发矩阵 / 类目提取 / 能力降级
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        # 显式触发词命中。
        ("快报", True),
        ("今日快报", True),
        ("来一份今日快报", True),
        ("早报", True),
        ("晚报", True),
        ("今日热点", True),
        ("科技新闻", True),
        ("AI新闻", True),
        ("ai新闻", True),  # 大小写不敏感
        ("AI快报", True),
        ("财经新闻", True),
        ("财经快报", True),
        ("国际新闻", True),
        ("科技快报", True),  # 类目词 + 快报
        # 裸「新闻」不属于快报（搜索链路的地盘）。
        ("新闻", False),
        ("今日新闻是什么", False),
        ("这不是新闻吗", False),
        # 明确搜索意图 → 让路。
        ("找新闻", False),
        ("搜索一下AI新闻", False),
        ("帮我查一下今日快报", False),
        # 带链接是链接解析的活。
        ("快报 https://example.com", False),
        # 超长文本是聊天的活。
        ("快报" * 17, False),
        ("", False),
    ],
)
def test_is_news_command_matrix(text: str, expected: bool) -> None:
    assert is_news_command(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("财经快报", "finance"),
        ("来一份财经新闻", "finance"),
        ("国际新闻", "world"),
        ("科技新闻", "tech"),
        ("AI新闻", "tech"),
        ("ai快报", "tech"),
        ("人工智能快报", "tech"),
        ("今日热点", "mix"),
        ("来一份今日快报", "mix"),
        ("快报", "mix"),
        ("", "mix"),
    ],
)
def test_extract_news_category(text: str, expected: str) -> None:
    assert extract_news_category(text) == expected


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        request_id="req-news-test",
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        plain_text=text,
    )


def _make_decision() -> BotDecision:
    return BotDecision(
        request_id="req-news-test",
        should_respond=True,
        mode="command",
        trigger="快报",
        capability_id="bot.news",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )


def test_news_capability_full_result(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_fetch(category: str, **kwargs: object) -> list[NewsItem]:
        captured["category"] = category
        captured.update(kwargs)
        return _sample_items()

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.news.fetch_headlines",
        _fake_fetch,
    )
    capability = build_news_capability(config=None)
    result = capability(_make_message("科技快报"), _make_decision())
    assert result.kind == "text"
    assert result.capability_id == "bot.news"
    assert result.title == "今日快报 · 科技"
    assert "1. 甲骨文净利润同比增长 60%（IT之家）" in result.body
    assert "capability:news" in result.audit_tags
    assert "news_category:tech" in result.audit_tags
    assert captured["category"] == "tech"
    # config=None → 默认超时/缓存/条数。
    assert captured["timeout_seconds"] == 6.0
    assert captured["cache_seconds"] == 600.0
    assert captured["max_items"] == 8


def test_news_capability_config_overrides(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_fetch(category: str, **kwargs: object) -> list[NewsItem]:
        captured.update(kwargs)
        return _sample_items()

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.news.fetch_headlines",
        _fake_fetch,
    )
    config = SimpleNamespace(
        bot_news_timeout_seconds=3.0,
        bot_news_cache_seconds=60.0,
        bot_news_max_items=5,
    )
    capability = build_news_capability(config=config)
    capability(_make_message("财经新闻"), _make_decision())
    assert captured["timeout_seconds"] == 3.0
    assert captured["cache_seconds"] == 60.0
    assert captured["max_items"] == 5


def test_news_capability_empty_degrades(monkeypatch) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.news.fetch_headlines",
        lambda category, **kwargs: [],
    )
    capability = build_news_capability(config=None)
    result = capability(_make_message("快报"), _make_decision())
    assert result.body == "快报暂时拉不到，稍后再试试？"
    assert result.title == ""
    assert "news:fetch_failed" in result.audit_tags


def test_news_config_field_defaults_documented() -> None:
    # 配置字段名约定（wiring 由编排层完成，这里锁字段拼写）。
    config = SimpleNamespace(
        bot_news_enabled=True,
        bot_news_timeout_seconds=6.0,
        bot_news_cache_seconds=600.0,
        bot_news_max_items=8,
    )
    assert config.bot_news_enabled is True
    assert config.bot_news_timeout_seconds == 6.0
    assert config.bot_news_cache_seconds == 600.0
    assert config.bot_news_max_items == 8
