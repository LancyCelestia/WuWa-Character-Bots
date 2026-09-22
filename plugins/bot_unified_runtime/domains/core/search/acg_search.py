"""ACG 专项检索竖源与时效加权融合（v21r2 SEARCH 席）。

三个无 key/复用既有链路的竖源，专补通用 web 检索（Tavily/DDG）在二次元域
时效差、SEO 农场噪声高的缺口：

| 竖源 | 能查什么 | 不能查什么 | 接口风险 |
|---|---|---|---|
| Bangumi (bgm.tv) | 番剧/漫画(书籍)/游戏条目元数据：中文名、原名、放送/发售日期、评分 | 剧情讨论、梗、社区热度、放送后的动态 | v0 API 强制要求自定义 User-Agent（默认 UA 403）；有速率限制，超限 429 |
| 萌娘百科 | ACG 条目/梗的中文圈释义与考据 | 时效动态；主站 WAF/风控可能拦截（ParseHttpError 诚实降级） | MediaWiki API 变更低风险；镜像域名列表随主站策略漂移 |
| B站公开搜索 | 视频/切片：标题、UP主、**发布日期（pubdate）**、链接 | 无 cookie 时大概率 -412 风控（诚实降级为空）；站内热度榜另需独立接口 | 2023 起 wbi 签名逐步强制，本模块走旧端点+可选 cookie，**接口随时可能收紧**，失败静默降级 |

时效加权融合（``fuse_into_web_hits``）为纯函数：
- latest 档：按结果日期距 today 的天数加权（≤7 天 ×1.6 / ≤30 天 ×1.3 /
  ≤180 天 ×1.1 / 更旧 ×0.8 / 无日期 ×0.7），并把「来源+日期（或日期未知）」
  显式注进结果文本——最新档结果必须可判新旧；
- background 档：源权威度加权（萌百 1.2 > Bangumi 1.1 > B站/web 1.0）。

所有网络函数支持 transport 注入（测试全离线 mock，零真实 HTTP）。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote

from plugins.bot_unified_runtime.domains.core.contracts.character import WebSearchHit
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    TIMELINESS_LATEST,
    AcgIntent,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    http_get_json,
    http_post_json,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SOURCE_LABELS",
    "TIMELINESS_HONESTY_LINE",
    "AcgResult",
    "bangumi_search",
    "bilibili_search",
    "fuse_into_web_hits",
    "moegirl_lookup",
    "parse_result_date",
    "search_acg_verticals",
    "timeliness_section_note",
]

BANGUMI_SEARCH_ENDPOINT = "https://api.bgm.tv/v0/search/subjects"
BILIBILI_SEARCH_ENDPOINT = "https://api.bilibili.com/x/web-interface/search/type"

# Bangumi v0 API 文档要求可识别的 UA（默认 UA/库 UA 会 403）。
_BANGUMI_UA = (
    "shorekeeper-bot/1.0 (nonebot2 personal bot; sync: local-operator)"
)
_BILIBILI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

SOURCE_LABELS: dict[str, str] = {
    "bangumi": "Bangumi",
    "moegirl": "萌娘百科",
    "bilibili": "B站",
    "web": "网页",
}

# 注入 chat 上下文的时效诚实口径（守岸人语气，一句话，不啰嗦）。
TIMELINESS_HONESTY_LINE = (
    "检索可能过时：以下条目自带来源与日期，回答时以标注日期为准，"
    "拿不准新旧就如实说「我查到的可能不是最新的」，别把旧料当新瓜。"
)

@dataclass(frozen=True)
class AcgResult:
    """竖源单条结果。date 为 ISO 日期字符串（未知=空串）。"""

    source: str  # bangumi / moegirl / bilibili
    title: str
    snippet: str
    url: str
    date: str = ""
    extra: str = ""  # 补充行（如 UP主/评分），已消毒前由调用方保证非敏感


def timeliness_section_note(now: datetime) -> str:
    """【联网检索】区头的检索截至口径。"""
    return f"检索截至 {now:%Y-%m-%d %H:%M}"


# ---------------------------------------------------------------------------
# Bangumi (bgm.tv) —— 无 key 条目元数据
# ---------------------------------------------------------------------------

def bangumi_search(
    query: str,
    *,
    limit: int = 3,
    timeout_seconds: float = 4.0,
    transport: Callable[..., Any] | None = None,
) -> list[AcgResult]:
    """Bangumi v0 条目搜索（POST /v0/search/subjects，无 key）。

    返回按 API 相关序的至多 ``limit`` 条；网络失败抛 ParseHttpError 由
    ``search_acg_verticals`` 统一降级。
    """
    cleaned = str(query or "").strip()
    if not cleaned:
        return []
    poster = transport or http_post_json
    payload = poster(
        BANGUMI_SEARCH_ENDPOINT,
        {"keyword": cleaned, "limit": max(1, min(int(limit), 10))},
        timeout=max(1.0, float(timeout_seconds)),
        user_agent=_BANGUMI_UA,
        referer="https://bgm.tv/",
    )
    subjects: list[Any] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            subjects = data
    results: list[AcgResult] = []
    for item in subjects[: max(1, int(limit))]:
        if not isinstance(item, dict):
            continue
        subject_id = str(item.get("id") or "").strip()
        name_cn = str(item.get("name_cn") or "").strip()
        name = str(item.get("name") or "").strip()
        title = name_cn or name
        if not title:
            continue
        date_str = str(item.get("date") or "").strip()[:10]
        score_raw = item.get("score")
        extra_parts: list[str] = []
        if isinstance(score_raw, (int, float)) and score_raw > 0:
            extra_parts.append(f"评分{float(score_raw):.1f}")
        if name_cn and name and name_cn != name:
            extra_parts.append(f"原名 {name}")
        results.append(
            AcgResult(
                source="bangumi",
                title=title,
                snippet=str(item.get("summary") or "").strip()[:160],
                url=f"https://bgm.tv/subject/{subject_id}" if subject_id else "https://bgm.tv/",
                date=date_str,
                extra="；".join(extra_parts),
            )
        )
    return results


# ---------------------------------------------------------------------------
# 萌娘百科 —— 复用既有 sources/moegirl.py（缓存+限速+镜像回退）
# ---------------------------------------------------------------------------

def moegirl_lookup(
    query: str,
    *,
    limit: int = 3,
    timeout_seconds: float = 4.0,
) -> list[AcgResult]:
    """萌百全文检索（同步、带模块级缓存）；网络失败抛 ParseHttpError。

    经由 ``sources.moegirl.moegirl_search``：主站 generator=search →
    opensearch 回退 → 镜像域名重试。WAF 拦截时上层诚实降级。
    """
    cleaned = str(query or "").strip()
    if not cleaned:
        return []
    # 延迟绑定：测试通过 monkeypatch acg_search 命名空间注入替身。
    from plugins.bot_unified_runtime.domains.location.data.moegirl import moegirl_search

    hits = moegirl_search(cleaned, limit=max(1, min(int(limit), 5)), timeout_seconds=max(1.0, float(timeout_seconds)))
    results: list[AcgResult] = []
    for hit in hits[: max(1, int(limit))]:
        title = str(getattr(hit, "title", "") or "").strip()
        if not title:
            continue
        results.append(
            AcgResult(
                source="moegirl",
                title=title,
                snippet=str(getattr(hit, "snippet", "") or "").strip()[:200],
                url=str(getattr(hit, "url", "") or "").strip(),
            )
        )
    return results


# ---------------------------------------------------------------------------
# B站公开搜索 —— 视频 pubdate 提供真实时效信号
# ---------------------------------------------------------------------------

_EM_TAG_RE = re.compile(r"</?em[^>]*>")


def bilibili_search(
    query: str,
    *,
    limit: int = 3,
    timeout_seconds: float = 4.0,
    cookie_header: str = "",
    transport: Callable[..., Any] | None = None,
) -> list[AcgResult]:
    """B站综合搜索（search/type video，可选 cookie；无 cookie 常见 -412）。

    成功时按站内相关序返回至多 ``limit`` 条，date=视频发布日期（本地时区）。
    code!=0（含 -412 风控）按空结果处理——调用方无法区分「无结果」与
    「被风控」，此处以空列表+日志记 code，属诚实降级。
    """
    cleaned = str(query or "").strip()
    if not cleaned:
        return []
    poster = transport or http_get_json
    params = f"search_type=video&keyword={quote(cleaned)}&page=1"
    payload = poster(
        f"{BILIBILI_SEARCH_ENDPOINT}?{params}",
        timeout=max(1.0, float(timeout_seconds)),
        user_agent=_BILIBILI_UA,
        referer="https://www.bilibili.com/",
        cookie=str(cookie_header or ""),
    )
    if not isinstance(payload, dict):
        return []
    code = payload.get("code")
    if code != 0:
        logger.debug("bilibili search degraded code=%s query_chars=%d", code, len(cleaned))
        return []
    data = payload.get("data")
    results_raw = data.get("result") if isinstance(data, dict) else None
    if not isinstance(results_raw, list):
        return []
    results: list[AcgResult] = []
    for item in results_raw[: max(1, int(limit))]:
        if not isinstance(item, dict):
            continue
        raw_title = str(item.get("title") or "").strip()
        title = _EM_TAG_RE.sub("", raw_title).strip()
        if not title:
            continue
        pubdate = item.get("pubdate")
        date_str = ""
        if isinstance(pubdate, (int, float)) and pubdate > 0:
            # unix 秒 → UTC → 本地时区日期（与用户口径一致）。
            date_str = datetime.fromtimestamp(
                float(pubdate), tz=timezone.utc
            ).astimezone().date().isoformat()
        author = str(item.get("author") or "").strip()
        results.append(
            AcgResult(
                source="bilibili",
                title=title,
                snippet=str(item.get("description") or "").strip()[:160],
                url=str(item.get("arcurl") or "").strip(),
                date=date_str,
                extra=f"UP主 {author}" if author else "",
            )
        )
    return results


# ---------------------------------------------------------------------------
# 竖源并发编排
# ---------------------------------------------------------------------------

def search_acg_verticals(
    query: str,
    intent: AcgIntent,
    *,
    enabled_sources: dict[str, bool] | None = None,
    timeout_seconds: float = 4.0,
    cookie_header: str = "",
    max_per_source: int = 3,
    max_total_seconds: float = 6.0,
) -> tuple[list[AcgResult], list[str]]:
    """并发跑启用的竖源，返回 ``(结果, 错误类型列表)``。

    - 单源失败只记 ``"{source}:{异常类型名}"``（不写异常文本，防泄漏），
      不阻断其余源；
    - 总预算 ``max_total_seconds``：超时未完成的源放弃（cancel_futures）；
    - 全部失败/禁用返回空列表——调用方按「无 ACG 竖源结果」继续原链路。
    """
    cleaned = str(query or "").strip()
    if not cleaned or not intent.is_acg:
        return [], []
    enabled = enabled_sources or {"bangumi": True, "moegirl": True, "bilibili": True}
    jobs: dict[str, Callable[[], list[AcgResult]]] = {}
    if enabled.get("bangumi"):
        jobs["bangumi"] = lambda: bangumi_search(
            cleaned, limit=max_per_source, timeout_seconds=timeout_seconds
        )
    if enabled.get("moegirl"):
        jobs["moegirl"] = lambda: moegirl_lookup(
            cleaned, limit=max_per_source, timeout_seconds=timeout_seconds
        )
    if enabled.get("bilibili"):
        jobs["bilibili"] = lambda: bilibili_search(
            cleaned,
            limit=max_per_source,
            timeout_seconds=timeout_seconds,
            cookie_header=cookie_header,
        )
    if not jobs:
        return [], []

    results: dict[str, list[AcgResult]] = {}
    error_kinds: list[str] = []
    lock = threading.Lock()

    def _run(source: str) -> None:
        try:
            found = jobs[source]()
        except Exception as exc:  # noqa: BLE001 - 单源失败降级，异常文本不外泄。
            with lock:
                error_kinds.append(f"acg:{source}:{type(exc).__name__[:40]}")
            return
        with lock:
            results[source] = found

    executor = ThreadPoolExecutor(
        max_workers=len(jobs), thread_name_prefix="chat-acg-search"
    )
    start = time.monotonic()
    try:
        futures = [executor.submit(_run, source) for source in jobs]
        deadline_hit = False
        for future in futures:
            remaining = max_total_seconds - (time.monotonic() - start)
            try:
                future.result(timeout=max(0.1, remaining))
            except Exception:  # noqa: BLE001 - 超时/异常源放弃，保留已完成源。
                deadline_hit = True
        if deadline_hit:
            with lock:
                error_kinds.append("acg:timeout")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # 稳定序：bangumi → moegirl → bilibili（与 SOURCE_LABELS 对齐）。
    merged: list[AcgResult] = []
    for source in ("bangumi", "moegirl", "bilibili"):
        merged.extend(results.get(source, []))
    return merged, error_kinds


# ---------------------------------------------------------------------------
# 时效加权融合（纯函数）
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")

# latest 档：按结果新旧加权
_LATEST_WEIGHTS: tuple[tuple[int, float], ...] = (
    (7, 1.6),
    (30, 1.3),
    (180, 1.1),
)
_LATEST_OLD_WEIGHT = 0.8
_LATEST_UNKNOWN_WEIGHT = 0.7
# background 档：源权威度加权
_BACKGROUND_WEIGHTS: dict[str, float] = {
    "moegirl": 1.2,
    "bangumi": 1.1,
    "bilibili": 1.0,
    "web": 1.0,
}


def parse_result_date(value: str) -> date | None:
    """解析结果日期（ISO / 带时间的 ISO 前缀）；失败返回 None。"""
    match = _DATE_RE.search(str(value or ""))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _result_weight(
    *,
    source: str,
    date_str: str,
    timeliness: str,
    today: date,
) -> float:
    if timeliness == TIMELINESS_LATEST:
        parsed = parse_result_date(date_str)
        if parsed is None:
            return _LATEST_UNKNOWN_WEIGHT
        age_days = (today - parsed).days
        if age_days < 0:
            # 未来日期（预放送/预约卡池）：对「最新档」是强信号。
            return 1.6
        for bound, weight in _LATEST_WEIGHTS:
            if age_days <= bound:
                return weight
        return _LATEST_OLD_WEIGHT
    return _BACKGROUND_WEIGHTS.get(source, 1.0)


def _annotate(result: AcgResult, *, timeliness: str) -> str:
    """把「日期与来源」注进摘要行（最新档必须可判新旧）。"""
    label = SOURCE_LABELS.get(result.source, result.source)
    date_part = result.date or ("日期未知" if timeliness == TIMELINESS_LATEST else "")
    parts = [f"（{label}·{date_part}）" if date_part else f"（{label}）"]
    snippet = result.snippet or result.extra
    if result.snippet and result.extra:
        snippet = f"{result.snippet}；{result.extra}"
    return f"{parts[0]}{snippet}".strip()


def fuse_into_web_hits(
    intent: AcgIntent,
    web_hits: list[WebSearchHit],
    acg_results: list[AcgResult],
    *,
    today: date,
) -> list[WebSearchHit]:
    """按意图时效档把 ACG 竖源结果与通用 web 结果合并重排。

    - 输出仍是 ``WebSearchHit``（复用 chat 链既有【联网检索】渲染、预算、
      消毒与遥测，零模板改动）；
    - ACG 条目 title 加竖源标签前缀，摘要行首注「（来源·日期）」；
    - web 结果文本保持原样，只参与加权排序；
    - 权重降序、同权重保持传入序（稳定）。
    """
    weighted: list[tuple[float, int, WebSearchHit]] = []
    for index, hit in enumerate(web_hits):
        weight = _result_weight(
            source="web", date_str="", timeliness=intent.timeliness, today=today
        )
        weighted.append((weight, index, hit))
    offset = len(web_hits)
    for index, result in enumerate(acg_results):
        weight = _result_weight(
            source=result.source,
            date_str=result.date,
            timeliness=intent.timeliness,
            today=today,
        )
        label = SOURCE_LABELS.get(result.source, result.source)
        hit = WebSearchHit(
            title=f"[{label}] {result.title}",
            snippet=_annotate(result, timeliness=intent.timeliness),
            url=result.url or "",
            source_domain=_source_domain(result.source),
        )
        weighted.append((weight, offset + index, hit))
    weighted.sort(key=lambda entry: (-entry[0], entry[1]))
    return [entry[2] for entry in weighted]


_DOMAINS: dict[str, str] = {
    "bangumi": "bgm.tv",
    "moegirl": "moegirl.org.cn",
    "bilibili": "bilibili.com",
}


def _source_domain(source: str) -> str:
    return _DOMAINS.get(source, source)
