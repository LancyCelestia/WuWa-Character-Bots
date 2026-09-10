"""今日快报数据源：聚合国内可达的新闻 RSS 源（免 key）。

实测探针（2026-09-11，本机直连验证，浏览器 UA，≤1MB 限长读取）：

- 可用（4 源）：IT之家 ``https://www.ithome.com/rss/``、少数派
  ``https://sspai.com/feed``、华尔街见闻
  ``https://dedicated.wallstreetcn.com/rss.xml``、BBC 中文
  ``https://feeds.bbci.co.uk/zhongwen/simp/rss.xml``（注意：该源实际
  返回繁体中文条目，收录为「国际」类目）；
- 不可用已剔除：36kr ``/feed``、Solidot ``index?rss``、机器之心 ``/rss``
  三者实测均返回 HTML 页面而非 XML（feed 已下线），收录只会制造常态
  解析失败的静默噪音。

设计（与 market_data / meme_search 同一套底线）：

- 单源失败（超时/HTML 响应/XML 损坏/超限长）静默跳过，绝不上抛；
- 并发抓取类目内全部源（线程池，整类目共享 timeout_seconds 预算，
  最坏耗时 ≈ 单源超时而不是源数 × 超时）；
- 成功结果进进程内 TTL 缓存（按类目分桶，默认 10 分钟，≤64 条），
  失败不缓存，下一次调用立即重试；
- 解析同时支持 RSS 2.0 与 Atom（ElementTree ``{*}`` 通配命名空间），
  标题剥 HTML 标签 + 反转义实体 + 压空白（华尔街见闻 CDATA 标题
  实测带首尾空格）。
"""

from __future__ import annotations

import email.utils
import html as _html
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_text

# 响应体上限：单源 RSS 实测最大约 260KB（华尔街见闻），1MB 已是数倍冗余，
# 只为防异常超大响应撑爆内存。
_MAX_FEED_BYTES = 1024 * 1024
# 进程内缓存上限：先清过期，再按最旧丢弃（长驻进程防无界增长）。
_CACHE_MAX_ENTRIES = 64
_CACHE_TTL_DEFAULT_SECONDS = 600.0
# mix 类目每源最多取若干条（跨类目多样性优先于单源深度）。
_MIX_PER_FEED_CAP = 4
# mix 合并后的总量上限（缓存桶存合并结果，供不同 max_items 切片）。
_MIX_MERGE_CAP = 32


@dataclass(frozen=True)
class NewsItem:
    """单条新闻标题快照。"""

    title: str
    url: str
    source: str
    published_at: datetime | None = None
    category: str = "tech"


# (url, 展示名, 类目)；类目取值见 _CATEGORY_KEYS。
_FEEDS: tuple[tuple[str, str, str], ...] = (
    ("https://www.ithome.com/rss/", "IT之家", "tech"),
    ("https://sspai.com/feed", "少数派", "tech"),
    ("https://dedicated.wallstreetcn.com/rss.xml", "华尔街见闻", "finance"),
    ("https://feeds.bbci.co.uk/zhongwen/simp/rss.xml", "BBC中文", "world"),
)

# 类目 → 中文标签（对外展示与缓存分桶共用这一组键）。
CATEGORY_LABELS: dict[str, str] = {
    "tech": "科技",
    "finance": "财经",
    "world": "国际",
    "mix": "综合",
}

_EMPTY_DEGRADED_TEXT = "快报暂时拉不到，稍后再试试？"

# 进程内缓存：按类目分桶，缓存最后一次成功抓取（monotonic 时间戳, 快照）。
_CACHE: dict[str, tuple[float, tuple[NewsItem, ...]]] = {}


def reset_news_cache() -> None:
    """清空进程内快报缓存（测试与运维手动刷新用）。"""
    _CACHE.clear()


def _fetch_feed_text(url: str, timeout_seconds: float) -> str:
    """单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    _, text = http_get_text(
        url,
        timeout=max(1.0, float(timeout_seconds)),
        max_bytes=_MAX_FEED_BYTES,
    )
    return text


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_title(raw: str) -> str:
    """标题清洗：剥 HTML 标签、反转义实体、压空白（CDATA 常带首尾空格）。"""
    text = _HTML_TAG_RE.sub(" ", raw or "")
    text = _html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _parse_datetime(raw: str) -> datetime | None:
    """RSS pubDate（RFC 822）与 Atom updated/published（ISO 8601）都能解。"""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _entry_link(node: ET.Element) -> str:
    """条目链接：Atom 取 href 属性（优先 rel=alternate），RSS 取文本。"""
    first = ""
    for link_el in node.findall("{*}link"):
        href = (link_el.get("href") or link_el.text or "").strip()
        if not href:
            continue
        if not first:
            first = href
        if (link_el.get("rel") or "alternate").strip() == "alternate":
            return href
    return first


def _entry_date(node: ET.Element) -> str:
    """条目时间：RSS pubDate / Atom published|updated / RSS1 dc:date。"""
    for tag in ("pubDate", "published", "updated", "date"):
        raw = node.findtext("{*}" + tag)
        if raw and raw.strip():
            return raw
    return ""


def parse_feed(text: str, *, source: str, category: str) -> list[NewsItem]:
    """解析单源 XML（RSS 2.0 / Atom / RDF 均可）；坏 XML 返回 []。

    缺标题的条目跳过，缺链接/时间的条目保留（字段尽力而为）。
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    # {*}` 通配命名空间：RSS2 的 item 在 channel 下、RDF 的 item 在根下、
    # Atom 是 entry，全部用后代轴一网打尽。
    nodes = root.findall(".//{*}item") or root.findall(".//{*}entry")
    items: list[NewsItem] = []
    for node in nodes:
        title = _clean_title(node.findtext("{*}title") or "")
        if not title:
            continue
        items.append(
            NewsItem(
                title=title,
                url=_entry_link(node),
                source=source,
                published_at=_parse_datetime(_entry_date(node)),
                category=category,
            )
        )
    return items


def _feeds_for(category: str) -> list[tuple[str, str, str]]:
    """类目 → 源列表；mix 或未知类目回退全部源。"""
    if category in ("tech", "finance", "world"):
        return [feed for feed in _FEEDS if feed[2] == category]
    return list(_FEEDS)


def _fetch_single_feed(
    url: str,
    source: str,
    category: str,
    per_feed_cap: int,
    timeout_seconds: float,
) -> list[NewsItem]:
    """抓取并解析单源；任何失败静默返回 []，不给整体拖后腿。"""
    try:
        text = _fetch_feed_text(url, timeout_seconds)
    except Exception:  # noqa: BLE001 - 单源失败静默跳过，快报绝不抛异常。
        return []
    return parse_feed(text, source=source, category=category)[:per_feed_cap]


def _merge_dedup(lists: list[list[NewsItem]], *, interleave: bool, cap: int) -> list[NewsItem]:
    """合并 + 按 URL 去重；mix 用轮转合并保证类目多样性，其余保源序。"""
    merged: list[NewsItem] = []
    seen_urls: set[str] = set()
    if interleave:
        pools = [list(feed_items) for feed_items in lists]
        while len(merged) < cap and any(pools):
            for pool in pools:
                if len(merged) >= cap:
                    break
                if not pool:
                    continue
                item = pool.pop(0)
                if item.url and item.url in seen_urls:
                    continue
                if item.url:
                    seen_urls.add(item.url)
                merged.append(item)
        return merged
    for feed_items in lists:
        for item in feed_items:
            if item.url and item.url in seen_urls:
                continue
            if item.url:
                seen_urls.add(item.url)
            merged.append(item)
            if len(merged) >= cap:
                return merged
    return merged


def _evict_cache(ttl_seconds: float) -> None:
    """缓存上限治理：先清过期，再按最旧丢弃（≤64 条）。"""
    if len(_CACHE) <= _CACHE_MAX_ENTRIES:
        return
    now = time.monotonic()
    expired = [
        key
        for key, (cached_at, _snapshot) in _CACHE.items()
        if now - cached_at > ttl_seconds
    ]
    for key in expired:
        _CACHE.pop(key, None)
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))


def fetch_headlines(
    category: str = "mix",
    *,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _CACHE_TTL_DEFAULT_SECONDS,
    max_items: int = 8,
) -> list[NewsItem]:
    """按类目抓取今日头条列表；全部源失败返回 []，绝不抛异常。

    - 类目：tech / finance / world / mix（mix 跨类目轮转各取若干，未知
      类目按 mix 处理）；
    - timeout_seconds 是整类目的并发总预算（每源各自享受该超时，线程池
      并发，最坏耗时 ≈ 单源超时）；
    - 成功结果按类目进进程内 TTL 缓存（默认 600s），命中直接切片返回；
      失败不缓存，下一次调用立即重试。
    """
    key = category if category in CATEGORY_LABELS else "mix"
    ttl = max(0.0, float(cache_seconds))
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None and now - cached[0] <= ttl:
        return list(cached[1])[: max(1, int(max_items))]

    feeds = _feeds_for(key)
    if not feeds:
        return []
    per_feed_cap = _MIX_PER_FEED_CAP if key == "mix" else 20
    timeout = max(1.0, float(timeout_seconds))
    workers = min(len(feeds), 8)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="news-feed") as pool:
        futures = [
            pool.submit(_fetch_single_feed, url, source, feed_category, per_feed_cap, timeout)
            for url, source, feed_category in feeds
        ]
        per_feed_lists: list[list[NewsItem]] = []
        for future in futures:
            try:
                per_feed_lists.append(future.result())
            except Exception:  # noqa: BLE001 - 单源线程异常同样静默跳过。
                per_feed_lists.append([])

    merged = _merge_dedup(per_feed_lists, interleave=key == "mix", cap=_MIX_MERGE_CAP)
    if merged:
        _CACHE[key] = (now, tuple(merged))
        _evict_cache(ttl)
    return merged[: max(1, int(max_items))]


def format_news_brief(items: Sequence[NewsItem], category_label: str) -> str:
    """渲染纯文本快报：首行日期+类目，正文 ``1. 标题（来源）``；空给降级文案。"""
    if not items:
        return _EMPTY_DEGRADED_TEXT
    # 本地时区日期（astimezone 使 aware，规避 DTZ005）。
    date_text = datetime.now().astimezone().strftime("%Y-%m-%d")
    lines = [f"今日快报 · {date_text} · {category_label}"]
    for index, item in enumerate(items, 1):
        source_text = f"（{item.source}）" if item.source else ""
        lines.append(f"{index}. {item.title}{source_text}")
    return "\n".join(lines)
