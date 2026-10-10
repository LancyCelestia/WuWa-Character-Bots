"""今日快报回归测试（全部离线，网络出口 news_feeds._fetch_feed_text 打桩）。

夹具按 2026-09-11 真实探针裁剪：IT之家 / 少数派 / 华尔街见闻 / BBC 中文
四个存活源的 item 结构逐字段保留（华尔街见闻 CDATA 标题实测带首尾空格、
BBC 链接带 ``&amp;`` 实体与 dc/content/atom/media 命名空间、IT之家 GMT
pubDate、少数派 +0800 pubDate）。N4（2026-09-12）新增 V2EX 真 Atom 1.0
源：结构按当日真实响应裁剪（href 链接、ISO updated、tag:id）。
"""

from __future__ import annotations

import ast
import threading
import time
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.core.shared_pool import get_shared_pool
from plugins.bot_unified_runtime.domains.subscribe.capabilities.news import (
    build_news_capability,
    extract_news_category,
    is_news_command,
)
from plugins.bot_unified_runtime.domains.subscribe.feeds import news_feeds
from plugins.bot_unified_runtime.domains.subscribe.feeds.news_feeds import (
    NewsItem,
    format_news_brief,
    parse_feed,
    reset_news_cache,
)

# ---------------------------------------------------------------------------
# 真实探针夹具（2026-09-11，逐字段按真实响应裁剪）
# ---------------------------------------------------------------------------

ITHOME_URL = "https://www.ithome.com/rss/"
SSPAI_URL = "https://sspai.com/feed"
V2EX_URL = "https://www.v2ex.com/index.xml"
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

# V2EX：真 Atom 1.0（2026-09-12 实测探针裁剪），rel=alternate href 链接、
# ISO updated、tag:id。
V2EX_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>V2EX</title>
<subtitle>way to explore</subtitle>
<link rel="alternate" type="text/html" href="https://www.v2ex.com/" />
<link rel="self" type="application/atom+xml" href="https://www.v2ex.com/index.xml" />
<id>https://www.v2ex.com/</id>
<updated>2026-09-11T18:17:06Z</updated>
<entry>
\t<title>[问与答] 有做跨境电商和出海的吗</title>
\t<link rel="alternate" type="text/html" href="https://www.v2ex.com/t/1241462#reply0" />
\t<id>tag:www.v2ex.com,2026-09-11:nodeTopic/1241462</id>
\t<published>2026-09-11T18:17:06Z</published>
\t<updated>2026-09-11T18:17:06Z</updated>
</entry>
<entry>
\t<title>[分享创造] 如果用 iPhone Duo 来展示 App</title>
\t<link rel="alternate" type="text/html" href="https://www.v2ex.com/t/1241461#reply0" />
\t<id>tag:www.v2ex.com,2026-09-11:nodeTopic/1241461</id>
\t<published>2026-09-11T18:13:09Z</published>
\t<updated>2026-09-11T18:13:09Z</updated>
</entry>
</feed>
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
    V2EX_URL: V2EX_ATOM,
    WSCN_URL: WSCN_RSS,
    BBC_URL: BBC_RSS,
}

# 2026-10-02 席 F2（用户裁定「新闻只准正规源，不许用自媒体」）：少数派（社区投稿
# 平台）与 V2EX（论坛）已从名册除名，`_FEEDS` 派生自 `news_feeds.NEWS_SOURCES`。
# 上面两枚夹具**不删**——它们是「除名后不再被抓取」的反证样本（白名单门与运行期出站门的
# 注毒料在 tests/test_news_source_whitelist.py，本件只锁抓取与解析行为）。
#
# 🔴 2026-10-08 三批：下面这份「实装三枚」字典**不再是判据**（旧用法＝把抓取清单逐枚
# 钉死，二批放开后必红，本件的类目映射腿已改成读名册现算）。留着只当**存量反挤兑**样本：
# 判「放开清单有没有把最早的三枚真探针源挤出去」（``test_legacy_three_pinned_sources_...``），
# 以及「真裁剪夹具是否仍能过管线」。判「该接哪几枚」的唯一尺是名册派生。
_WIRED_FIXTURES: dict[str, str] = {
    url: _LIVE_FIXTURES[url]
    for url in (ITHOME_URL, WSCN_URL, BBC_URL)
}


# ---------------------------------------------------------------------------
# 派生式夹具（2026-10-08 三批：抓取清单不再逐枚硬钉，测试同批改**读名册**）
# ---------------------------------------------------------------------------


def _wired_rows(category: str) -> list[tuple[str, str, str]]:
    """类目 → 抓取行（**(url, 展示名, 类目)**），一律现算自名册派生。"""
    return list(news_feeds._feeds_for(category))


def _wired_urls(category: str) -> set[str]:
    return {row[0] for row in _wired_rows(category)}


def _roster_wired_keys() -> set[str]:
    """**绕过** ``_wired_sources()`` 从名册字面重推一遍「该被接线的是哪几枚」。

    尺与产线必须同源又不同路：这里逐条判 准入／端点／类目／档位**在不在册**／档位
    **在不在可接线索引**／否决标记，与 ``news_feeds._wired_sources()`` 现算比对。
    名册新行没登记档位 ⇒ 两边对不上，当场红（＝放宽钉尺同批配的更严替代锁的一半，
    另一半在 ``tests/test_news_source_whitelist.py`` 腿 ㉑）。
    """
    keys: set[str] = set()
    for source in news_feeds.NEWS_SOURCES:
        if not (source.admitted and source.endpoint and source.category):
            continue
        if source.reachability not in news_feeds.REACHABILITY_TIERS:
            continue  # 没登记档位＝结构上接不了线（不许「顺手新造一个档名」把它放进来）
        if source.reachability not in news_feeds._WIREABLE_REACH:
            continue
        if source.wire_block.strip():
            continue
        keys.add(source.key)
    return keys


def _synthetic_rss(url: str, *, count: int = 1) -> str:
    """按端点自域造一枚「N 条真条目」的 RSS 2.0（条目链落在同域 ⇒ 过运行期出站门）。"""
    host = news_feeds._news_domain(url) or "www.ithome.com"
    media = _media_of(url)
    items = "".join(
        f"<item><title>{media} 头条 {index}</title>"
        f"<link>https://{host}/news/{index}</link>"
        f"<description>{media} 的真实内容行，不是标题党。</description>"
        f"<pubDate>Thu, 10 Sep 2026 20:20:44 GMT</pubDate></item>"
        for index in range(1, count + 1)
    )
    return f'<rss version="2.0"><channel><title>{media}</title>{items}</channel></rss>'


def _media_of(url: str) -> str:
    return _MEDIA_BY_ENDPOINT.get(url, "未登记源")


_MEDIA_BY_ENDPOINT: dict[str, str] = {
    source.endpoint: source.media for source in news_feeds.NEWS_SOURCES if source.endpoint
}


@pytest.fixture(autouse=True)
def _news_fetch_isolation(monkeypatch) -> Iterator[None]:
    """每条用例从干净状态起，收尾把「补投/迟到」那批外呼**收干**。

    🔴 收干不是洁癖：本波把出卡路径改成只等一波，第二批跑在共享池里；monkeypatch 一
    还原，还在排队的后台任务就会打到**真网络**（本仓禁联网、禁外发）。finalizer 比
    monkeypatch 先跑＝因为本夹具显式吃 ``monkeypatch``（setup 顺序在后 ⇒  teardown 在前）。
    """
    news_feeds.reset_news_cache()
    news_feeds.reset_news_fetch_state()
    yield
    assert news_feeds.wait_for_outstanding_fetches(20.0), (
        "补投/迟到那批没收干就退出＝下一条评论可能带着上一轮的 monkeypatch 打到真网络"
    )
    news_feeds.reset_news_cache()
    news_feeds.reset_news_fetch_state()


class _Clock:
    """可控单调时钟：fetch TTL 测试用，避免依赖真实睡眠。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def _clean_news_cache() -> Iterator[None]:
    """（保留旧名）缓存/短路账/轮转位三件一起清——放开接线后光清缓存已不够隔离。"""
    reset_news_cache()
    news_feeds.reset_news_fetch_state()
    yield
    reset_news_cache()
    news_feeds.reset_news_fetch_state()


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


def test_parse_v2ex_atom_real_probe_fixture() -> None:
    items = parse_feed(V2EX_ATOM, source="V2EX", category="tech")
    assert [item.title for item in items] == [
        "[问与答] 有做跨境电商和出海的吗",
        "[分享创造] 如果用 iPhone Duo 来展示 App",
    ]
    assert items[0].url == "https://www.v2ex.com/t/1241462#reply0"
    assert items[0].published_at == datetime(
        2026, 9, 11, 18, 17, 6, tzinfo=timezone.utc
    )


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
# fetch_headlines：派生式类目映射 / 延迟预算 / 补投 / 短路 / TTL / 绝不抛异常
# ---------------------------------------------------------------------------


def test_fetch_category_mapping_is_derived_from_roster(monkeypatch) -> None:
    """类目抓取清单＝名册派生，不再逐枚钉 URL（钉死三枚是二批放开前的旧尺）。

    🔴 放宽同批配的**更严替代锁**（简报口径①）：抓到的每一枚都必须能从名册**字面**
    重推出来——准入 ∧ 有端点 ∧ 有类目 ∧ 档位**在 REACHABILITY_TIERS 里登记过** ∧ 档位
    **在可接线索引里** ∧ 无 ``wire_block`` 否决 ∧ 带实测证据。名册新行没登记档位
    ⇒ 产线派生与字面推导两边对不上，当场红（不是「在册留脏」）。
    """
    calls: list[str] = []

    def _fake(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        return _synthetic_rss(url)

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)

    assert _roster_wired_keys() == {source.key for source in news_feeds._wired_sources()}, (
        "抓取清单与名册字面推导不等＝有人手写了第二真身，或新行的档位/否决没登记"
    )

    for category in ("tech", "finance", "world", "ai_vendor"):
        rows = _wired_rows(category)
        assert rows, f"{category} 派生为空＝本腿空转（空类目请走腿 ㉓ 的诚实缺席登记）"
        calls.clear()
        news_feeds.reset_news_cache()
        items = news_feeds.fetch_headlines(category, cache_seconds=0.0, max_items=50)
        # ① 抓的正是这一类目派生出来的那几枚（一枚不多、一枚不少）
        assert set(calls) == {row[0] for row in rows}, f"{category} 抓取清单与派生不等"
        # ② 精确类目绝不回退成全量（旧硬编码把新类目当「未知类目」抓全量的坑）
        assert {row[2] for row in rows} == {category}
        assert {item.category for item in items} == {category}
        # ③ 条目归属逐枚落回登记名（展示名取名册，不取远端自称）
        assert {item.source for item in items} == {row[1] for row in rows}

    for url, _media, _category in news_feeds._FEEDS:
        source = news_feeds.news_source_for(url)
        assert source is not None and source.admitted, f"名册外端点在抓取列表里：{url}"
        assert source.reachability in news_feeds.REACHABILITY_TIERS, f"{url}: 档位没登记却上线"
        assert source.reachability in news_feeds._WIREABLE_REACH, f"{url}: 档位不可接却上线"
        assert not source.wire_block.strip(), f"{url}: 带着接线否决标记仍被抓取"
        assert source.probe.strip() and "测" in source.probe, f"{url}: 已接线却没有实测证据指针"


def test_fetch_unknown_category_falls_back_to_mix(monkeypatch) -> None:
    """未知类目按 mix 处理；🔴 派发覆盖率不缩水（每轮全量派发，波宽外的走补投）。

    旧断言 ``set(calls) == set(_WIRED_FIXTURES)`` 只有三枚，是「硬钉清单」的另一半；
    放开后它必须读名册。第二波不等出卡，但**照样派发**——所以这里先收干再断言覆盖。
    """
    calls: list[str] = []

    def _fake(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        return _synthetic_rss(url, count=2)

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)
    items = news_feeds.fetch_headlines("不存在的类目", cache_seconds=0.0, max_items=50)
    assert items, "未知类目回退 mix 却一条都没读到"
    assert news_feeds.wait_for_outstanding_fetches(20.0), "补投那批没收干"
    assert set(calls) == {row[0] for row in news_feeds._FEEDS}, (
        "mix 轮次的派发覆盖 ≠ 抓取清单全量＝有源被静默跳轮（不是延迟取舍，是没派发）"
    )
    snapshot = news_feeds.cached_snapshot("mix")
    assert {item.source for item in snapshot} == {row[1] for row in news_feeds._FEEDS}, (
        "收干后快照里仍缺源＝补投的结果没折回同一代次，条目被静默吃掉"
    )
    # mix 轮转合并：单源条数被封顶（各取若干），跨源多样性优先于单源深度。
    per_source = Counter(item.source for item in snapshot)
    assert max(per_source.values()) <= news_feeds._MIX_PER_FEED_CAP


def test_fetch_per_feed_failure_skipped_silently(monkeypatch) -> None:
    """一枚源挂掉不拖垮整批（台账 #12 语义，接线放开到 8 枚后判据照旧成立）。"""
    rows = _wired_rows("world")
    dead_url = rows[0][0]

    def _fake(url: str, timeout_seconds: float) -> str:
        if url == dead_url:
            raise OSError("one outlet down")
        return _synthetic_rss(url)

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)
    items = news_feeds.fetch_headlines("world", cache_seconds=0.0, max_items=50)
    assert {item.source for item in items} == {row[1] for row in rows} - {_media_of(dead_url)}


def test_fetch_never_raises_when_all_feeds_fail(monkeypatch) -> None:
    def _boom(url: str, timeout_seconds: float) -> str:
        raise OSError("network down")

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _boom)
    assert news_feeds.fetch_headlines("mix", cache_seconds=0.0) == []
    assert news_feeds.fetch_headlines("world", cache_seconds=0.0) == []
    # 坏 XML（HTML 伪装）同样安全降级——0 条目也算「这轮没取到东西」，不抛也不缓存。
    monkeypatch.setattr(news_feeds, "_fetch_feed_text", lambda url, timeout_seconds: "<html>ok</html>")
    assert news_feeds.fetch_headlines("world", cache_seconds=0.0) == []
    assert news_feeds.wait_for_outstanding_fetches(20.0)


def test_fetch_ttl_cache_hit_expiry_and_failure_not_cached(monkeypatch) -> None:
    """失败不缓存、成功进 TTL、到期重取（判据读派生清单，不再假设「类目只剩一枚源」）。"""
    urls = sorted(_wired_urls("finance"))
    assert len(urls) >= 2, "财经只剩一枚源＝旧的『唯一源』假设复活，先看接线账再改尺"
    clock = _Clock()
    monkeypatch.setattr(news_feeds.time, "monotonic", clock)
    calls: list[str] = []
    state = {"fail": True}

    def _fake(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        if state["fail"]:
            raise OSError("transient blip")
        return _synthetic_rss(url)

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)

    # 首次：整批失败 → 空，且不缓存（下一次调用立即重试）。
    clock.now += 1.0
    assert news_feeds.fetch_headlines("finance", cache_seconds=600.0) == []
    assert set(calls) == set(urls)
    # 立即重试：成功并写入缓存。
    state["fail"] = False
    calls.clear()
    clock.now += 1.0
    assert len(news_feeds.fetch_headlines("finance", cache_seconds=600.0)) == len(urls)
    assert set(calls) == set(urls)
    # TTL 内命中缓存：整批不再外呼。
    calls.clear()
    clock.now += 300.0
    assert len(news_feeds.fetch_headlines("finance", cache_seconds=600.0)) == len(urls)
    assert calls == []
    # TTL 过期 → 重新拉取。
    clock.now += 301.0
    assert len(news_feeds.fetch_headlines("finance", cache_seconds=600.0)) == len(urls)
    assert set(calls) == set(urls)


def test_fetch_cache_stores_full_list_sliced_by_max_items(monkeypatch) -> None:
    calls: list[str] = []

    def _fake(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        return _synthetic_rss(url, count=2)

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)
    tech_rows = _wired_rows("tech")
    assert len(news_feeds.fetch_headlines("tech", max_items=1)) == 1
    # 同一 TTL 内换更大的 max_items：命中缓存全量快照，不再外呼。
    tech = news_feeds.fetch_headlines("tech", max_items=8)
    assert len(calls) == len(tech_rows)  # tech 类目只抓它自己派生出来的那几枚
    assert len(tech) == 2 * len(tech_rows)
    assert len(news_feeds.fetch_headlines("tech", max_items=0)) == 1  # 非法值钳到 ≥1


# ---------------------------------------------------------------------------
# 延迟腿（2026-10-08 三批）：出卡路径只等一波——改前/改后现算墙钟，不许口头说快
# ---------------------------------------------------------------------------

#: 缩放预算：产线缺省 ``bot_news_timeout_seconds=6.0``（真身住 ``config.py``）的 1/6。
#: 墙钟用真睡眠量，比例读数（波数）与秒数同读一处，不外推成「大概几分钟」。
_LATENCY_BUDGET_SECONDS = 1.0


def test_fetch_outgoing_path_waits_one_wave_not_two(monkeypatch) -> None:
    """**延迟读数**：源数 > 共享池宽度时，出卡路径不再等第二波。

    读数符号＝``news_feeds.dispatch_wave_width``/``split_dispatch``/
    ``join_all_worst_case_seconds``（旧基线模型）/``budget_bound_worst_case_seconds``（新）。
    夹具用**真名册**派生的 mix 全量 + 真睡眠 + 真共享池，所以「改前 2 波」是跑出来的，
    不是算出来的；结构式读数（按生产预算 6.0s 换算）另由 ``test_latency_budget_*`` 锁。
    """
    rows = _wired_rows("mix")
    width = news_feeds.dispatch_wave_width()
    assert len(rows) > width, (
        f"前提不成立：mix 只有 {len(rows)} 枚 ≤ 波宽 {width}，这把尺今日空转"
    )
    budget = _LATENCY_BUDGET_SECONDS
    timeouts_seen: list[float] = []

    def _slow(url: str, timeout_seconds: float) -> str:
        timeouts_seen.append(timeout_seconds)
        time.sleep(timeout_seconds)
        return _synthetic_rss(url)

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _slow)

    # 改后（产线真身）：只等一波。
    started = time.perf_counter()
    news_feeds.fetch_headlines("mix", timeout_seconds=budget, cache_seconds=0.0)
    new_elapsed = time.perf_counter() - started
    assert news_feeds.wait_for_outstanding_fetches(30.0), "补投那批没收干"

    # 改前（退役写法）：提交全量后逐个 ``result()`` join，同夹具同池复跑。
    pool = get_shared_pool()
    started = time.perf_counter()
    old_futures = [pool.submit(_slow, url, budget) for url, _media, _category in rows]
    for future in old_futures:
        future.result()
    old_elapsed = time.perf_counter() - started

    assert new_elapsed < budget * 1.75, f"出卡路径仍在等第二波：{new_elapsed:.2f}s"
    assert old_elapsed >= budget * 1.8, f"基线没跑出第二波（夹具失效？）：{old_elapsed:.2f}s"
    # 读数按「波」比，不按毫毛比：改后 ≈1 波、改前 ≈2 波（睡眠粒度与调度抖动的容差 25%）。
    assert new_elapsed < old_elapsed * 0.75, (
        f"延迟没压到一波以内：改后 {new_elapsed:.2f}s vs 改前 {old_elapsed:.2f}s"
    )
    assert old_elapsed - new_elapsed >= budget * 0.5, (
        f"少等的那一波没有实据：改后 {new_elapsed:.2f}s / 改前 {old_elapsed:.2f}s"
    )
    # 🔴 天花板没被锯短：每枚源拿到的超时**逐枚等于**调用方预算（压的是排队不是投递）。
    assert set(timeouts_seen) == {budget}, f"单源超时预算被改动：{sorted(set(timeouts_seen))}"


def test_latency_budget_never_exceeds_the_callers_budget(monkeypatch) -> None:
    """**超延迟预算即红**（简报口径③）：任一候选类目按生产预算换算都不得超预算。"""
    budget = 6.0  # 生产缺省 bot_news_timeout_seconds；真身读数见 config.py
    over_budget: list[str] = []
    shaved: list[str] = []
    for category in news_feeds.CATEGORY_LABELS:
        rows = _wired_rows(category)
        blocking, _detached = news_feeds.split_dispatch(rows)
        if len(blocking) > news_feeds.dispatch_wave_width():
            shaved.append(f"{category}: 等待宽度 {len(blocking)} > 池宽 {news_feeds.dispatch_wave_width()}")
        new_worst = news_feeds.budget_bound_worst_case_seconds(budget)
        if new_worst > budget:
            over_budget.append(f"{category}: 出卡路径最坏 {new_worst}s > 预算 {budget}s")
        # 旧写法（join 全批）在这里超预算——反真空：证明「限一波」今天确实有活干。
        old_worst = news_feeds.join_all_worst_case_seconds(len(rows), timeout_seconds=budget)
        if len(rows) > news_feeds.dispatch_wave_width() and old_worst <= budget:
            over_budget.append(f"{category}: {len(rows)} 枚源的 join 基线竟没超预算＝尺空转")
    assert over_budget == [], over_budget
    assert shaved == [], shaved
    # mix 是唯一今日跨两波的类目：旧 2 波 × 6.0s＝12s，新＝6.0s（结构读数）。
    mix_rows = _wired_rows("mix")
    assert news_feeds.join_all_worst_case_seconds(len(mix_rows), timeout_seconds=budget) == 12.0
    assert news_feeds.budget_bound_worst_case_seconds(budget) == 6.0
    assert len(mix_rows) == len(news_feeds._FEEDS), "mix 应覆盖全部实装源"
    assert len(news_feeds.split_dispatch(mix_rows)[1]) == len(mix_rows) - news_feeds.dispatch_wave_width()
    # 波宽读的是共享池真身（不抄字面量）：池宽变了这把尺跟着走。
    monkeypatch.setattr(news_feeds.shared_pool, "SHARED_POOL_MAX_WORKERS", 4)
    assert news_feeds.dispatch_wave_width() == 4
    assert len(news_feeds.split_dispatch(mix_rows)[0]) == 4


def test_every_source_gets_the_callers_full_timeout(monkeypatch) -> None:
    """🔴 禁把超时天花板调小来消延迟：每源收到的超时＝调用方给的预算，一枚不差。"""
    calls: list[tuple[str, float]] = []

    def _record(url: str, timeout_seconds: float) -> str:
        calls.append((url, timeout_seconds))
        return _synthetic_rss(url)

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _record)
    news_feeds.fetch_headlines("mix", timeout_seconds=4.25, cache_seconds=0.0)
    assert news_feeds.wait_for_outstanding_fetches(20.0)
    assert {round(value, 3) for _url, value in calls} == {4.25}, sorted(calls)
    assert {url for url, _value in calls} == {row[0] for row in news_feeds._FEEDS}
    # 下限钳只抬不砍（``max(1.0, …)``）：给 0.5s 也不会被压成 0.5s 的假预算。
    calls.clear()
    news_feeds.reset_news_cache()
    news_feeds.fetch_headlines("tech", timeout_seconds=0.5, cache_seconds=0.0)
    assert {value for _url, value in calls} == {1.0}


def test_fetch_late_and_detached_results_fold_back_into_same_generation(monkeypatch) -> None:
    """补投不丢投递：出卡只等已完成那批，其余交卷后折回**同一代次**的快照。"""
    rows = _wired_rows("mix")
    width = news_feeds.dispatch_wave_width()
    assert len(rows) > width, "前提：mix 装得进一波 ⇒ 本腿空转（接线账变了先看清再改尺）"
    release = {row[0]: threading.Event() for row in rows}
    started: list[str] = []

    def _gated(url: str, timeout_seconds: float) -> str:
        started.append(url)
        assert release[url].wait(20), "测试没交卷"
        return _synthetic_rss(url)

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _gated)
    first = rows[0][0]
    release[first].set()  # 只有第一枚在预算内交卷
    items = news_feeds.fetch_headlines("mix", timeout_seconds=1.0, cache_seconds=0.0)
    assert {item.source for item in items} == {_media_of(first)}, (
        f"出卡不该等的第二批被等进来了：{[item.source for item in items]}"
    )
    assert len(started) >= width, f"波内源没全部起跑：{len(started)}"

    for gate in release.values():
        gate.set()
    assert news_feeds.wait_for_outstanding_fetches(20.0)
    snapshot = news_feeds.cached_snapshot("mix")
    assert {item.source for item in snapshot} == {row[1] for row in rows}, (
        "迟到/补投的结果没折回同代次快照＝接线了却永远读不到（在册≠已执法）"
    )
    assert set(started) == {row[0] for row in rows}


def test_fetch_consecutive_failure_short_circuits_then_expires(monkeypatch) -> None:
    """连续失败短路一个冷却窗（省无用功），到期无条件重试，且绝不因短路把类目关空。"""
    rows = _wired_rows("finance")
    assert len(rows) >= 2, "财经不足两枚源＝短路腿与『不关空类目』腿都会空转"
    dead_url, live_url = rows[0][0], rows[1][0]
    clock = _Clock()
    monkeypatch.setattr(news_feeds.time, "monotonic", clock)
    calls: list[str] = []
    state = {"dead": True}

    def _fake(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        if url == dead_url and state["dead"]:
            raise OSError("dead outlet")
        return _synthetic_rss(url)

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)

    for _round in range(news_feeds._FAILURE_SHORTCIRCUIT_THRESHOLD):
        clock.now += 1.0
        calls.clear()
        items = news_feeds.fetch_headlines("finance", cache_seconds=0.0)
        assert set(calls) == {dead_url, live_url}
        assert {item.source for item in items} == {_media_of(live_url)}

    # 连着失败到阈值 ⇒ 那枚暂时不发外呼，另一枚照抓（类目没被关空）。
    clock.now += 1.0
    calls.clear()
    news_feeds.fetch_headlines("finance", cache_seconds=0.0)
    assert calls == [live_url], f"短路没生效或把类目关空：{calls}"

    # 到期重试仍失败 ⇒ 继续冷却（滚动窗，不是永久拉黑：每轮到期都会再给它一次机会）。
    clock.now += news_feeds._FAILURE_SHORTCIRCUIT_COOLDOWN_SECONDS + 1.0
    calls.clear()
    news_feeds.fetch_headlines("finance", cache_seconds=0.0)
    assert set(calls) == {dead_url, live_url}, f"冷却到期没重试：{calls}"

    # 站点恢复 ⇒ 过一个冷却窗必然回到派发面，并且**取到一次就清零**、此后不再记仇。
    state["dead"] = False
    clock.now += news_feeds._FAILURE_SHORTCIRCUIT_COOLDOWN_SECONDS + 1.0
    calls.clear()
    news_feeds.fetch_headlines("finance", cache_seconds=0.0)
    assert set(calls) == {dead_url, live_url}
    for _round in range(4):
        clock.now += 1.0
        calls.clear()
        news_feeds.fetch_headlines("finance", cache_seconds=0.0)
        assert set(calls) == {dead_url, live_url}, f"站点已恢复却仍被短路：{calls}"


def test_short_circuit_never_shuts_a_category_empty(monkeypatch) -> None:
    """整类目都进冷却 ⇒ 仍照旧全量试一次：短路是省无用功，不是把类目关空。"""
    rows = _wired_rows("finance")
    assert len(rows) >= 2, "财经不足两枚源＝本腿空转"
    clock = _Clock()
    monkeypatch.setattr(news_feeds.time, "monotonic", clock)
    calls: list[str] = []

    def _boom(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        raise OSError("everything down")

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _boom)
    for _round in range(news_feeds._FAILURE_SHORTCIRCUIT_THRESHOLD + 2):
        clock.now += 1.0
        calls.clear()
        assert news_feeds.fetch_headlines("finance", cache_seconds=0.0) == []
        assert set(calls) == {row[0] for row in rows}, (
            f"第 {_round + 1} 轮短路把类目关空了：{calls}"
        )


def test_legacy_three_pinned_sources_survive_the_opened_list(monkeypatch) -> None:
    """放开清单不许把旧三枚挤出去：三枚真探针裁剪的夹具仍在抓取清单里、仍能解析出条目。

    这枚腿是「放宽一条腿要同批配一条更严的」里的**存量**那一半——旧尺钉的是「只有这三枚」，
    新尺钉的是「这三枚一枚都不能少 ∧ 每枚都得从名册字面推得出」（见上面两把）。
    """
    wired_urls = {row[0] for row in news_feeds._FEEDS}
    for url in _WIRED_FIXTURES:
        assert url in wired_urls, f"{url}（旧钉清单成员）被挤出实装清单＝静默除名"

    def _fake(url: str, timeout_seconds: float) -> str:
        return _WIRED_FIXTURES[url] if url in _WIRED_FIXTURES else _synthetic_rss(url)

    monkeypatch.setattr(news_feeds, "_fetch_feed_text", _fake)
    by_category = {
        "tech": ITHOME_URL,
        "finance": WSCN_URL,
        "world": BBC_URL,
    }
    for category, url in by_category.items():
        news_feeds.reset_news_cache()
        items = news_feeds.fetch_headlines(category, cache_seconds=0.0, max_items=50)
        assert url in {item.url for item in items} or items, f"{category} 读不到旧三枚的条目"
        titles = {item.title for item in items}
        fixture_titles = {
            parsed.title for parsed in parse_feed(_LIVE_FIXTURES[url], source="夹具", category=category)
        }
        assert titles & fixture_titles, f"{category} 的真夹具条目没走到管线里（旧覆盖被换掉了）"


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
    # 审查 Q-01：入 user_copy 池轮换（原固定「快报暂时拉不到，稍后再试试？」）。
    assert format_news_brief([], "综合") in {
        template.format(reason="快报暂时拉不到")
        for template in user_copy.DATASOURCE_FAILURE_TEMPLATES
    }


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
        "plugins.bot_unified_runtime.domains.subscribe.capabilities.news.fetch_headlines",
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
    assert captured["max_items"] == 20


def test_news_capability_config_overrides(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_fetch(category: str, **kwargs: object) -> list[NewsItem]:
        captured.update(kwargs)
        return _sample_items()

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.subscribe.capabilities.news.fetch_headlines",
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
        "plugins.bot_unified_runtime.domains.subscribe.capabilities.news.fetch_headlines",
        lambda category, **kwargs: [],
    )
    capability = build_news_capability(config=None)
    result = capability(_make_message("快报"), _make_decision())
    # 审查 Q-01：入 user_copy 池轮换（原固定「快报暂时拉不到，稍后再试试？」）。
    assert result.body in {
        template.format(reason="快报暂时拉不到")
        for template in user_copy.DATASOURCE_FAILURE_TEMPLATES
    }
    assert result.title == ""
    assert "news:fetch_failed" in result.audit_tags


def test_news_config_field_defaults_documented() -> None:
    # 配置字段名约定（wiring 由编排层完成，这里锁字段拼写）。
    config = SimpleNamespace(
        bot_news_enabled=True,
        bot_news_timeout_seconds=6.0,
        bot_news_cache_seconds=600.0,
        bot_news_max_items=20,
    )
    assert config.bot_news_enabled is True
    assert config.bot_news_timeout_seconds == 6.0
    assert config.bot_news_cache_seconds == 600.0
    assert config.bot_news_max_items == 20


# ---------------------------------------------------------------------------
# 静态离线锁：凡调用「会出网」取数口的用例，必须自带桩（乙案·用户 2026-10-08 裁定）
# ---------------------------------------------------------------------------
# 为什么是静态判据而不是运行时插桩：本域取数腿对失败**静默吞掉**（台账 #12「快报绝不
# 抛」语义），在网络咽喉上插一根 raising 桩，fetch_headlines 照样返回空列表、用例照绿。
# 现算取证＝把 news_feeds.http_get_text 换成「记账桩」（记下 URL 再抛）跑三件 news 用例
# ⇒ 记账 0 条、全绿：可见「绿」根本证明不了没出网，也证明不了没真拉 RSS。判据只能读 AST。
#
# 🔴 取数函数名单**不在本文件手抄**：由 _news_outbound_surface() 从真身派生（AST 扫
# news_feeds 自身的「网络可达闭包」）。名单要扩＝改 news_feeds 那一侧，本锁自动跟上；
# 取数口改名/搬家＝尺读空，当场红（不许静默绿）。
# 本锁不新增配置键、不放宽任何守卫、不碰生产代码。

#: 物理事实尺：调用链解到这些**顶层包**即算真出网（stdlib / 第三方 socket 入口）。
#: 这是派生的种子，不是「取数函数名单」——后者一律现派生。
_NETWORK_ROOT_PACKAGES: frozenset[str] = frozenset(
    {
        "aiohttp",
        "ftplib",
        "http",
        "httpx",
        "imaplib",
        "nntplib",
        "poplib",
        "requests",
        "smtplib",
        "socket",
        "ssl",
        "urllib",
        "urllib2",
        "urllib3",
    }
)

#: 简报点名的最低扫描面。glob 把它们洗掉＝本锁再也看不见那几枚违规，必须红。
_OFFLINE_LOCK_MIN_FILES: tuple[str, ...] = (
    "tests/test_news.py",
    "tests/test_news_card_outbound.py",
    "tests/test_news_source_whitelist.py",
)

#: 认作「打桩」的调用头：monkeypatch.setattr / mock.patch / monkeypatch.setitem。
_STUB_CALL_HEADS: frozenset[str] = frozenset({"patch", "setattr", "setitem"})


def _dotted_chain(node: ast.expr | None) -> str | None:
    """a.b.c(...) 这类被调用位置 → "a.b.c"；解不出（如 d[k](...)）→ None。"""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _last_segment(chain: str) -> str:
    return chain.rsplit(".", 1)[-1]


def _import_map(tree: ast.Module) -> dict[str, str]:
    """模块级 import：本文件里的名字 → dotted 来源（相对导入本树未用，不拼）。"""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                if alias.name != "*":
                    out[alias.asname or alias.name] = f"{node.module or ''}.{alias.name}"
    return out


def _module_functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _local_definition_names(tree: ast.Module) -> set[str]:
    """本文件自己定义/绑定的模块级名字（用来分辨「同名本地函数」与「搬进来的真身」）。"""
    names = set(_module_functions(tree))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    names |= set(_import_map(tree))
    return names


def _names_used(node: ast.AST) -> set[str]:
    return {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}


def _resolved_call_chains(node: ast.AST, imports: dict[str, str]) -> set[str]:
    """子树里所有被调用位置的 dotted 链，头段按本文件 import 表就地展开成来源。"""
    chains: set[str] = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        chain = _dotted_chain(sub.func)
        if not chain:
            continue
        head, _, rest = chain.partition(".")
        origin = imports.get(head, head)
        chains.add(f"{origin}.{rest}" if rest else origin)
    return chains


def _project_layout() -> tuple[Path, str]:
    """(仓库根, 顶层包名)——都从 news_feeds 真身文件位置现算，不写死路径。

    ``plugins/a/b/…/m.py`` 的模块全名有 N 段 ⇒ 文件之上第 N-1 层目录（＝顶层包的父
    目录）就是仓库根；news_feeds 搬家、改名、换深度都不用动本锁。
    """
    module_file = Path(news_feeds.__file__).resolve()
    segments = news_feeds.__name__.split(".")
    top_package = segments[0]
    return module_file.parents[len(segments) - 1], top_package


def _source_file_for(chain: str, root: Path, top_package: str) -> tuple[Path | None, str]:
    """项目内 dotted 调用链 → (定义它的源文件, 该文件里的符号名)；项目外/查不到 → 空。"""
    parts = chain.split(".")
    if parts[0] != top_package:
        return None, ""
    for cut in range(len(parts), 0, -1):
        stem = root.joinpath(*parts[:cut])
        for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
            if candidate.is_file():
                return candidate, parts[cut] if cut < len(parts) else ""
    return None, ""


def _file_outbound_surface(
    path: Path,
    root: Path,
    top_package: str,
    cache: dict[str, tuple[frozenset[str], frozenset[str]]],
    stack: frozenset[str] = frozenset(),
) -> tuple[frozenset[str], frozenset[str]]:
    """某个源文件里：(会出网的模块级函数, 直接踩在网络咽喉上的那一层)。

    派生法＝① 种子：某函数的调用链解到网络根包（``urllib`` 一类），或解到**别处已证实
    会出网**的符号（跨模块递归，``http_get_text`` 就是这么被认出来的）；② 沿「模块级
    函数引用了谁」扩散——引用按**名字**算而不是只按调用算，所以
    ``pool.submit(_fetch_feed_row, …)`` 这种「把函数当值递出去」的边一样看得见
    （补投/迟到那批正是这样排进共享池的，只按调用扫就会漏掉整条 ``fetch_headlines``）。
    """
    key = str(path)
    if key in cache:
        return cache[key]
    if key in stack or len(cache) > 60:
        return frozenset(), frozenset()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        cache[key] = (frozenset(), frozenset())
        return cache[key]
    funcs = _module_functions(tree)
    imports = _import_map(tree)
    deeper = stack | {key}
    direct: set[str] = set()
    for name, fn in funcs.items():
        for chain in _resolved_call_chains(fn, imports):
            if chain.split(".")[0] in _NETWORK_ROOT_PACKAGES:
                direct.add(name)
                break
            other, symbol = _source_file_for(chain, root, top_package)
            if other is None or not symbol or str(other) == key:
                continue
            names, _prev = _file_outbound_surface(other, root, top_package, cache, deeper)
            if symbol in names:
                direct.add(name)
                break
    reaching = set(direct)
    changed = True
    while changed:
        changed = False
        for name, fn in funcs.items():
            if name not in reaching and _names_used(fn) & reaching:
                reaching.add(name)
                changed = True
    result = (frozenset(reaching & set(funcs)), frozenset(direct))
    cache[key] = result
    return result


def _news_outbound_surface() -> tuple[frozenset[str], frozenset[str]]:
    """news_feeds 里「会出网」的取数函数集合（真名现派生，本文件不抄清单）。"""
    root, top_package = _project_layout()
    return _file_outbound_surface(
        Path(news_feeds.__file__).resolve(), root, top_package, {}
    )


def _stub_names_in(node: ast.AST) -> set[str]:
    """这一棵子树里认得出的「桩」：setattr/patch/setitem 的字符串目标 + 属性/下标赋值。"""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if _last_segment(_dotted_chain(sub.func) or "") not in _STUB_CALL_HEADS:
                continue
            for arg in sub.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.add(_last_segment(arg.value))
        elif isinstance(sub, ast.Assign):
            for target in sub.targets:
                if isinstance(target, ast.Attribute):
                    out.add(target.attr)
                elif (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                ):
                    out.add(_last_segment(target.slice.value))
    return out


def _autouse_stub_names(tree: ast.Module) -> set[str]:
    """本文件里 **autouse 夹具真打了桩**的名字。

    🔴 「反正夹具会罩」不算证据：必须 AST 认出那件 ``@pytest.fixture(autouse=True)``
    确实存在、且它体内真打了桩，才拿去豁免用例。test_news.py 那枚
    ``_news_fetch_isolation`` 只清缓存＋收干外呼、**不拦网**⇒ 豁免集为空，这是本锁
    现算出来的，不是我猜的。
    """
    out: set[str] = set()
    for fn in tree.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in fn.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if _last_segment(_dotted_chain(decorator.func) or "") != "fixture":
                continue
            autouse = next((kw.value for kw in decorator.keywords if kw.arg == "autouse"), None)
            if isinstance(autouse, ast.Constant) and autouse.value is True:
                out |= _stub_names_in(fn)
    return out


def _is_outbound_call(
    chain: str, outbound: frozenset[str], imports: dict[str, str], local_defs: set[str]
) -> bool:
    head, _, rest = chain.partition(".")
    if not rest:
        # 裸名调用：本文件自己定义的同名函数不算（防无关件里一枚本地 ``_submit`` 撞名误伤），
        # 从别处 import 进来的同名真身照样算。
        return head in outbound and not (head in local_defs and head not in imports)
    return _last_segment(chain) in outbound and head in imports


def _case_sites_and_stubs(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    helpers: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    outbound: frozenset[str],
    imports: dict[str, str],
    local_defs: set[str],
) -> tuple[list[tuple[str, int]], set[str]]:
    """这一枚用例（含它真正调用到的模块级 helper）里的取数调用 + 看得见的桩。"""
    sites: list[tuple[str, int]] = []
    stubs: set[str] = set()
    pending = [fn]
    walked: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in walked:
            continue
        walked.add(id(current))
        stubs |= _stub_names_in(current)
        for sub in ast.walk(current):
            if isinstance(sub, ast.Call):
                chain = _dotted_chain(sub.func)
                if not chain:
                    continue
                if _is_outbound_call(chain, outbound, imports, local_defs):
                    sites.append((_last_segment(chain), sub.lineno))
                head = _last_segment(chain)
                if head in helpers and id(helpers[head]) not in walked:
                    pending.append(helpers[head])
    return sites, stubs


def test_news_outbound_fetch_calls_carry_their_own_stub() -> None:
    """静态离线锁：调用会出网取数口的用例必须自带桩（不跑网络，只读 AST）。

    判据一句话：**用例体内（含它调用的模块级 helper、含真打了桩的 autouse 夹具）
    出现取数口调用，就必须看得见对这些调用名、或对「直接踩网络咽喉」那一层的桩**；
    踩咽喉那层被桩掉即等价拦截全链（``_fetch_feed_text`` 是本域声明的唯一出口）。

    已知边界（诚实登记，不许当成已封全）：本锁判的是**字面调用**。经能力层间接出网
    （``build_news_capability(...)`` 里那条 ``fetch_headlines``）不归本锁——那一路要靠
    能力层自身的桩（``test_news_card_outbound.py`` 的 ``_patch_items`` 一形）。
    """
    outbound, choke = _news_outbound_surface()
    assert outbound, "取数口搬家了：从 news_feeds 真身派生不出任何「会出网」的函数"
    assert choke, "取数口搬家了：派生不出直接踩网络咽喉的那一层（跨模块解析断了）"

    root, _top_package = _project_layout()
    files = sorted(root.glob("tests/**/test_*.py"))
    present = {p.relative_to(root).as_posix() for p in files}
    missing = sorted(set(_OFFLINE_LOCK_MIN_FILES) - present)
    assert not missing, f"取数口搬家了：扫描面里找不到简报点名的 {missing}"

    shared_stubs: set[str] = set()
    conftest = root / "tests" / "conftest.py"
    if conftest.is_file():
        shared_stubs |= _autouse_stub_names(ast.parse(conftest.read_text(encoding="utf-8")))

    scanned = 0
    violations: list[str] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(name in text for name in outbound):
            continue
        tree = ast.parse(text)
        imports = _import_map(tree)
        local_defs = _local_definition_names(tree)
        helpers = _module_functions(tree)
        autouse = shared_stubs | _autouse_stub_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test"):
                continue
            sites, stubs = _case_sites_and_stubs(node, helpers, outbound, imports, local_defs)
            stubs |= autouse
            for name, lineno in sites:
                scanned += 1
                if name in stubs or choke & stubs:
                    continue
                violations.append(f"{rel}::{node.name} 第 {lineno} 行调用 {name}() 未打桩")
    assert scanned, "取数口搬家了：扫描面里一枚取数调用都没读到（改名或搬家了，本锁已失明）"
    assert not violations, (
        "有调用会出网取数口却没打桩的用例＝测试会真去拉 RSS（网络一抖就是概率性假红）：\n"
        + "\n".join(sorted(violations))
        + "\n修法：在该用例里 monkeypatch.setattr(news_feeds, "
        + "\"<取数口或踩网络咽喉那一层>\", 假函数)；名单以真身派生为准，别手抄。"
    )
