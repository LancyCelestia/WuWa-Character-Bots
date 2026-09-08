"""萌娘百科查询（MediaWiki 公开 api.php 薄层，免 key 免登录）。

只依赖公开 Action API：``generator=search``（全文搜+引言摘要一次拿）、
``opensearch``（标题模糊搜回退）、``query`` 单页摘要。刻意不碰
``action=parse`` / ``prop=revisions`` / ``?action=raw``——萌百全站 ACL
屏蔽这些路径，匿名与 bot 账号都调不通。

主站 ``zh.moegirl.org.cn`` 失败自动回退镜像 ``mzh.moegirl.org.cn``；
短 TTL 缓存 + 最小请求间隔，避免重复外呼拖慢回复或触发风控。
"""

from __future__ import annotations

import threading
import time
import urllib.parse
from dataclasses import dataclass

from plugins.bot_unified_runtime.sources.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)

_USER_AGENT = (
    "BotCharacterBots/0.1 (NoneBot2 moegirl lookup; contact: local user)"
    " Mozilla/5.0"
)

DEFAULT_API_BASES = (
    "https://zh.moegirl.org.cn/api.php",
    "https://mzh.moegirl.org.cn/api.php",
)

# 萌百条目更新频率低：300s TTL 足够；未命中结果同样入缓存，
# 重复追问同一冷门词条时不再外呼，直接走降级链路。
MOEGIRL_CACHE_TTL_SECONDS = 300.0
MOEGIRL_MIN_REQUEST_INTERVAL_SECONDS = 0.5
MOEGIRL_CACHE_MAX_ENTRIES = 256

_CACHE_LOCK = threading.Lock()
_MOEGIRL_RESPONSE_CACHE: dict[str, tuple[float, object]] = {}
_LAST_MOEGIRL_REQUEST: list[float] = [0.0]


@dataclass(frozen=True)
class MoegirlHit:
    """一次搜索/摘要命中的最小字段集。"""

    title: str
    snippet: str = ""
    url: str = ""
    pageid: int = 0


def clear_moegirl_cache() -> None:
    """清空萌百响应缓存（测试与运行时管理用）。"""
    with _CACHE_LOCK:
        _MOEGIRL_RESPONSE_CACHE.clear()
        _LAST_MOEGIRL_REQUEST[0] = 0.0


def _cached_get_json(
    url: str, *, timeout: float, proxy: str
) -> object:
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _MOEGIRL_RESPONSE_CACHE.get(url)
        if hit is not None and now - hit[0] < MOEGIRL_CACHE_TTL_SECONDS:
            return hit[1]
        wait = (
            _LAST_MOEGIRL_REQUEST[0] + MOEGIRL_MIN_REQUEST_INTERVAL_SECONDS - now
        )
    if wait > 0:
        time.sleep(min(wait, 2.0))
    payload = http_get_json(
        url, user_agent=_USER_AGENT, proxy=proxy, timeout=timeout
    )
    with _CACHE_LOCK:
        _LAST_MOEGIRL_REQUEST[0] = time.monotonic()
        if len(_MOEGIRL_RESPONSE_CACHE) >= MOEGIRL_CACHE_MAX_ENTRIES:
            _MOEGIRL_RESPONSE_CACHE.clear()
        _MOEGIRL_RESPONSE_CACHE[url] = (time.monotonic(), payload)
    return payload


def _api_url(base: str, params: dict) -> str:
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_search_payload(payload: object) -> list[MoegirlHit]:
    """解析搜索响应，按相关性排序。

    ``generator=search``（formatversion=1）按 ``query.pageids`` 恢复顺序；
    ``opensearch`` 回退响应是 ``[query, [titles], [descs], [urls]]`` 数组。
    任何结构异常一律返回空列表（上层走降级，不抛异常）。
    """
    if not isinstance(payload, dict):
        if isinstance(payload, list) and len(payload) >= 2:
            titles = payload[1] if isinstance(payload[1], list) else []
            descs = payload[2] if len(payload) > 2 and isinstance(payload[2], list) else []
            urls = payload[3] if len(payload) > 3 and isinstance(payload[3], list) else []
            hits: list[MoegirlHit] = []
            for index, title in enumerate(titles):
                title = str(title or "").strip()
                if not title:
                    continue
                snippet = str(descs[index]) if index < len(descs) else ""
                url = str(urls[index]) if index < len(urls) else ""
                hits.append(MoegirlHit(title=title, snippet=snippet, url=url))
            return hits
        return []
    query = payload.get("query")
    if not isinstance(query, dict):
        return []
    raw_pages = query.get("pages")
    page_order = query.get("pageids")
    if not isinstance(raw_pages, (dict, list)):
        return []
    if isinstance(raw_pages, list):
        pages = {str(page.get("pageid") or index): page for index, page in enumerate(raw_pages)}
    else:
        pages = raw_pages
    ordered: list[dict] = []
    if isinstance(page_order, list):
        for key in page_order:
            page = pages.get(str(key))
            if isinstance(page, dict):
                ordered.append(page)
    ordered.extend(
        page for page in pages.values() if isinstance(page, dict)
    )
    hits = []
    seen: set[int] = set()
    for page in ordered:
        pageid = int(page.get("pageid") or 0)
        if pageid in seen:
            continue
        seen.add(pageid)
        title = str(page.get("title") or "").strip()
        if not title:
            continue
        hits.append(
            MoegirlHit(
                title=title,
                snippet=str(page.get("extract") or "").strip(),
                url=str(page.get("fullurl") or "").strip(),
                pageid=pageid,
            )
        )
    return hits


def _search_params(query: str, limit: int) -> dict:
    return {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": max(1, min(int(limit), 10)),
        "gsrnamespace": 0,
        "prop": "info|extracts",
        "inprop": "url",
        "exintro": 1,
        "explaintext": 1,
        "format": "json",
    }


def _opensearch_params(query: str, limit: int) -> dict:
    return {
        "action": "opensearch",
        "search": query,
        "limit": max(1, min(int(limit), 10)),
        "namespace": 0,
        "format": "json",
    }


def _summary_params(title: str) -> dict:
    return {
        "action": "query",
        "prop": "extracts|info",
        "inprop": "url",
        "redirects": 1,
        "exintro": 1,
        "explaintext": 1,
        "titles": title,
        "format": "json",
    }


def _effective_timeout(
    deadline: float, timeout_seconds: float
) -> float | None:
    remaining = deadline - time.monotonic()
    if remaining < 0.5:
        return None
    return max(0.5, min(timeout_seconds, remaining))


def _fetch_first(
    params_list: list[dict],
    *,
    api_bases: tuple[str, ...],
    timeout_seconds: float,
    proxy: str,
    budget_seconds: float,
) -> list[object]:
    """按「主站两法依次尝试 → 网络失败才换镜像」取第一个有内容的响应。

    空结果是主站的权威回答（词条不存在），不追打镜像——未命中路径
    固定至多 2 次外呼，保证降级链路不被拖慢；镜像只救主站不可达。
    总预算 ``budget_seconds`` 硬约束整体耗时，超预算直接放弃。
    """
    deadline = time.monotonic() + max(1.0, budget_seconds)
    payloads: list[object] = []
    for base in api_bases[:2]:
        network_error = False
        for params in params_list:
            timeout = _effective_timeout(deadline, timeout_seconds)
            if timeout is None:
                return payloads
            try:
                payload = _cached_get_json(
                    _api_url(base, params),
                    timeout=timeout,
                    proxy=proxy,
                )
            except ParseHttpError:
                network_error = True
                break
            payloads.append(payload)
            if parse_search_payload(payload):
                return payloads
        if not network_error:
            break
    return payloads


def moegirl_search(
    query: str,
    *,
    limit: int = 5,
    api_bases: tuple[str, ...] = DEFAULT_API_BASES,
    timeout_seconds: float = 5.0,
    proxy: str = "",
) -> list[MoegirlHit]:
    """全文搜索：主站 generator=search → opensearch 回退 → 镜像域名重试。"""
    query = str(query or "").strip()
    if not query:
        return []
    payloads = _fetch_first(
        [_search_params(query, limit), _opensearch_params(query, limit)],
        api_bases=api_bases,
        timeout_seconds=timeout_seconds,
        proxy=proxy,
        budget_seconds=timeout_seconds * 2,
    )
    for payload in payloads:
        hits = parse_search_payload(payload)
        if hits:
            return hits
    return []


def moegirl_page_summary(
    title: str,
    *,
    api_bases: tuple[str, ...] = DEFAULT_API_BASES,
    timeout_seconds: float = 5.0,
    proxy: str = "",
) -> MoegirlHit | None:
    """精确标题摘要（redirects=1 解析重定向）；页面不存在返回 None。

    注意：None 只代表「萌百确认无此页」，网络失败抛 ``ParseHttpError``，
    两者由上层区分（网络失败不等于未命中）。
    """
    title = str(title or "").strip()
    if not title:
        return None
    params = _summary_params(title)
    deadline = time.monotonic() + max(1.0, timeout_seconds * 2)
    last_payload: object | None = None
    for base in api_bases[:2]:
        timeout = _effective_timeout(deadline, timeout_seconds)
        if timeout is None:
            break
        try:
            payload = _cached_get_json(
                _api_url(base, params), timeout=timeout, proxy=proxy
            )
        except ParseHttpError:
            continue
        last_payload = payload
        if not isinstance(payload, dict):
            continue
        pages = (payload.get("query") or {}).get("pages")
        if not isinstance(pages, dict) or not pages:
            continue
        page = next(iter(pages.values()))
        if not isinstance(page, dict) or "missing" in page:
            return None
        page_title = str(page.get("title") or title).strip()
        return MoegirlHit(
            title=page_title,
            snippet=str(page.get("extract") or "").strip(),
            url=str(page.get("fullurl") or "").strip(),
            pageid=int(page.get("pageid") or 0),
        )
    if last_payload is None:
        raise ParseHttpError(f"moegirl summary unreachable: {title}")
    return None
