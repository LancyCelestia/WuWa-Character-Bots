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
  显式注进结果文本——最新档结果必须可判新旧；合理窗口内的未来日期（预放送/
  预约卡池）算强信号并标「未到期」，离谱未来值按无日期处理（脏数据不许冒充最新）；
- background 档：源权威度加权（萌百 1.2 > Bangumi 1.1 > B站/web 1.0）。

进提示词前还有一道筛（``screen_vertical_results``，编排口与融合口共用同一判据）：
声称来源与链接宿主不自洽的条目丢掉、同源同条目折叠，**丢弃一律留痕**不静默。
条目号与日期字段按「上游给的是不可信输入」处理：形态不对就当没给。

所有网络函数支持 transport 注入（测试全离线 mock，零真实 HTTP）。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

from plugins.bot_unified_runtime.domains.core.contracts.character import WebSearchHit
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    TIMELINESS_LATEST,
    AcgIntent,
)

# 跨源权威/先后的唯一声明表（真身在 search_service；本模块只派生，不另立一张表）。
from plugins.bot_unified_runtime.domains.core.search.search_service import (
    BACKGROUND_AUTHORITY_WEIGHTS,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    http_get_json,
    http_post_json,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SOURCE_LABELS",
    "TIMELINESS_HONESTY_LINE",
    "UNVERIFIABLE_MARK",
    "AcgResult",
    "bangumi_search",
    "bilibili_search",
    "fuse_into_web_hits",
    "moegirl_lookup",
    "parse_result_date",
    "screen_vertical_results",
    "search_acg_verticals",
    "source_identity_label",
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
# ⚠ 这句话必须**与实际渲染一致**：通用网页结果那几行没有日期可标
# （`WebSearchHit` 契约只有 title/snippet/url/source_domain 四个字段，
# 上游也没把发布日期带进来），所以旧口径那句「以下条目自带来源与日期」
# 对它们是假话——而提示词里的一句假话会被模型当成真话写进回答。
TIMELINESS_HONESTY_LINE = (
    "检索可能过时：带（来源·日期）标注的是二次元垂直站条目，未带标注的通用网页"
    "结果新鲜度未知，回答时以标注日期为准，没标注的别当成最新的；"
    "拿不准新旧就如实说「我查到的可能不是最新的」。"
)

#: 一条竖源命中既无条目号又无绝对链接时进文本的标记（见 `_annotate`）。
#: 刻意只用中文字：这条标记会拼进摘要行，任何 ASCII `id=` 形态都会撞上
#: 「没带条目号就不许出现 id=」那条既存锁（test_vertical_without_id_is_not_forged）。
UNVERIFIABLE_MARK = "〔无可回查链接〕"
#: 日期字段带回来了但根本不是日历日：明说存疑，不冒充有日期、也不冒充没日期。
_DATE_SUSPECT_LABEL = "日期存疑"

#: 条目号/日期的合法形态（上游 API 字段是**不可信输入**，会原样拼进提示词行）。
_ITEM_ID_RE = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
#: 未来日期的合理窗口：预放送/卡池预告最多提前两年，超出即按脏数据处理。
_FUTURE_HORIZON_DAYS = 730
#: 声称来源 ↔ 链接宿主的一致性表（`moegirl` 侧含官方镜像域名，见 moegirl.py 的
#: `DEFAULT_API_BASES`；漏一枚镜像就会把正当命中误杀成"越站"）。
_ALLOWED_HOST_SUFFIXES: dict[str, tuple[str, ...]] = {
    "bangumi": ("bgm.tv", "bangumi.tv", "bangumi.moe"),
    "moegirl": ("moegirl.org.cn", "moegirl.icu", "moegirl.org"),
    "bilibili": ("bilibili.com", "b23.tv"),
}
_BVID_RE = re.compile(r"^BV[0-9A-Za-z]{5,16}$")
#: unix 秒的合理上界（2100-01-01）。越界的时间戳一律不当真。
_PLAUSIBLE_EPOCH_MAX = 4102444800
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _one_line(value: object) -> str:
    """把任意上游文本压成一行——【联网检索】的结构前提就是"一行一条"。

    换行在这里不是排版问题：一行里塞进第二个换行，后面那条的文字就会被读成
    前一条的（跨条目串味），而提示词里没有任何别的手段能把它分回来。
    """
    return _WHITESPACE_RUN_RE.sub(" ", str(value or "")).strip()


def _safe_item_id(raw: object) -> str:
    """上游给的条目号只认「一串标识符」：形态不对就当作没给，绝不带病入册。

    为什么必须在这拦：`source_identity_label` 会把 id 原样拼进摘要行，
    而摘要行是一行一条的【联网检索】结构。**一行里塞进换行 = 后面那条的
    文字会被读成前一条的**，正是这类融合最常见的串味通道。
    """
    text = str(raw or "").strip()
    return text if _ITEM_ID_RE.fullmatch(text) else ""


def _safe_date_field(raw: object) -> str:
    """日期字段只收能解析成真实日历日的值；解析不出就留空（呈现侧标「日期未知」）。

    上游给 `"待定"`、`"2026-13-45"`、带换行的垃圾串都是实测过的形态——
    截断到 10 字符不等于它是日期，`[:10]` 之后照样能把控制字符带进那一行。
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    parsed = parse_result_date(text[:40])
    if parsed is None:
        return ""
    return parsed.isoformat()


def _canonical_item_url(source: str, item_id: str) -> str:
    """由**稳定条目号**推出的规范条目链接（确定性换算，不是猜测）。

    只认两种有据可依的形态：Bangumi 的 `/subject/<id>` 与 B站的 `/video/<bvid>`。
    萌百的规范链接按标题走，标题可被重定向/消歧改指 ⇒ 不猜。
    """
    if not item_id:
        return ""
    if source == "bangumi" and item_id.isdigit():
        return f"https://bgm.tv/subject/{item_id}"
    if source == "bilibili" and _BVID_RE.fullmatch(item_id):
        return f"https://www.bilibili.com/video/{item_id}"
    return ""


def _link_host(url: str) -> str:
    """绝对 http(s) 链接的宿主；非绝对链接返回空串（=「没有可核对的链接」）。"""
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return parsed.hostname.lower().strip(".")


def _url_declares_other_site(source: str, url: str) -> bool:
    """链接声称指向别处——**只有绝对链接才谈得上越站**，相对/不透明串一律放行。

    判据保守：拿不准就留条目。误杀一条正当命中的代价是"库里有的东西到不了
    用户眼前"，留下它的代价只是一行标注，两头不对等。
    """
    host = _link_host(url)
    if not host:
        return False
    suffixes = _ALLOWED_HOST_SUFFIXES.get(str(source or "").strip(), ())
    if not suffixes:
        # 这个源在本表没登记 ⇒ 本件不认识它的链接形态，不该由本件说话。
        return False
    return not any(host == s or host.endswith("." + s) for s in suffixes)


def _identity_key(result: AcgResult) -> str:
    """同一条目的身份指纹：只认「绝对链接」或「合法条目号」，两者都没有则不参与折叠。"""
    host_and_path = _link_host(result.url)
    if host_and_path:
        normalized = result.url.strip().lower().split("#", 1)[0]
        return f"u:{normalized}"
    if result.item_id:
        return f"i:{result.source}:{result.item_id}"
    return ""


def screen_vertical_results(
    results: Iterable[AcgResult],
) -> tuple[list[AcgResult], list[str]]:
    """竖源条目进提示词前的**唯一**一道筛。返回 ``(留下的, 丢弃原因)``。

    三条规则，全部朝「宁可少说也不说错」的方向偏：
    1. 声称来源与链接宿主不自洽（说萌百却指向别站）⇒ 丢，并留痕（不静默）；
    2. 同一来源内同一条目重复出现 ⇒ 折叠取首份。两行一模一样的条目会被模型
       读成「两个来源互相印证」，那是一条凭空多出来的证据；
    3. 其余一律保留，缺的东西交给 `source_identity_label` 如实标注。

    幂等：同一批筛两次结果相同 ⇒ 编排口与融合口可以各自过一遍而不产生第二本账。
    """
    kept: list[AcgResult] = []
    reasons: list[str] = []
    seen: set[str] = set()
    for result in results:
        if _url_declares_other_site(result.source, result.url):
            reasons.append(f"acg:{result.source}:link_offsite")
            continue
        key = _identity_key(result)
        if key:
            if key in seen:
                continue
            seen.add(key)
        kept.append(result)
    return kept, reasons

@dataclass(frozen=True)
class AcgResult:
    """竖源单条结果。date 为 ISO 日期字符串（未知=空串）。

    ``item_id`` 是**条目在来源站的稳定身份**（Bangumi subject id / 萌百
    pageid / B站 bvid），供"给出的每句话都能追到一条命中"这句话落地：
    没有它，用户与审计都只能拿标题去撞同名条目（取不到就留空，绝不编）。
    """

    source: str  # bangumi / moegirl / bilibili
    title: str
    snippet: str
    url: str
    date: str = ""
    extra: str = ""  # 补充行（如 UP主/评分），已消毒前由调用方保证非敏感
    item_id: str = ""  # 来源站条目号（空=该源没给，呈现时如实缺省）


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
        subject_id = _safe_item_id(item.get("id"))
        name_cn = str(item.get("name_cn") or "").strip()
        name = str(item.get("name") or "").strip()
        title = name_cn or name
        if not title:
            continue
        date_str = _safe_date_field(item.get("date"))
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
                # 拿不到 subject id 就留空链接。**旧实现这里填 `https://bgm.tv/`**——
                # 站点根页不是条目地址，点开什么都证明不了，却比空串更像"有据可查"，
                # 于是用户与模型都无从知道这条其实回查不了。
                url=_canonical_item_url("bangumi", subject_id),
                date=date_str,
                extra="；".join(extra_parts),
                item_id=subject_id,
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
        pageid = getattr(hit, "pageid", 0)
        results.append(
            AcgResult(
                source="moegirl",
                title=title,
                snippet=str(getattr(hit, "snippet", "") or "").strip()[:200],
                url=str(getattr(hit, "url", "") or "").strip(),
                # 萌百 pageid 是条目稳定身份（标题可改、id 不改）；取不到就留空，
                # 呈现侧会如实显示"该条未带条目号"，不拿标题冒充 id。
                item_id=_safe_item_id(pageid) if isinstance(pageid, int) and pageid > 0 else "",
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
        if (
            isinstance(pubdate, (int, float))
            and not isinstance(pubdate, bool)
            and 0 < float(pubdate) <= _PLAUSIBLE_EPOCH_MAX
        ):
            # unix 秒 → UTC → 本地时区日期（与用户口径一致）。
            # 上限是把「脏时间戳算出 33658 年」这类垃圾挡在日期换算**之前**：
            # 越界的 fromtimestamp 在 Windows 上直接抛，会带走整个 B站源。
            date_str = _safe_date_field(
                datetime.fromtimestamp(float(pubdate), tz=timezone.utc)
                .astimezone()
                .date()
                .isoformat()
            )
        author = str(item.get("author") or "").strip()
        bvid = _safe_item_id(item.get("bvid"))
        aid_raw = item.get("aid")
        aid = _safe_item_id(aid_raw) if isinstance(aid_raw, int) and aid_raw > 0 else ""
        item_id = bvid or aid
        arcurl = str(item.get("arcurl") or "").strip()
        if not _link_host(arcurl):
            # 旧端点常只给 bvid 不给 arcurl：bvid→规范链接是确定性换算，
            # 比留空多给一个能点开的地址，且不需要相信上游的字符串。
            arcurl = _canonical_item_url("bilibili", bvid)
        results.append(
            AcgResult(
                source="bilibili",
                title=title,
                snippet=str(item.get("description") or "").strip()[:160],
                url=arcurl,
                date=date_str,
                extra=f"UP主 {author}" if author else "",
                item_id=item_id,
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
    # 进提示词前的唯一一道筛（来源↔链接自洽 + 同源同条目折叠）。
    # 丢弃**必须留痕**：调用方把 error_kinds 并进 web_error_kinds 送进审计，
    # 于是"筛掉了几条"看得见——静默筛＝又一次"库里有的东西凭空消失"。
    kept, screen_reasons = screen_vertical_results(merged)
    return kept, error_kinds + screen_reasons


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
# 竖源内部的源名 → 跨源阶梯里的源 id（唯一的名字换算，不携带任何权重）。
_LADDER_SOURCE_IDS: dict[str, str] = {
    "bangumi": "bangumi",
    "moegirl": "moegirl",
    "bilibili": "bilibili",
    "web": "general",
}
# background 档的源权威度**不在这张文件里定义**：真身是
# ``search_service.BACKGROUND_AUTHORITY_WEIGHTS``（"哪个源更该先看"只有一份）。
# 本模块只按上面的换算表查表，查不到一律 1.0——不认识的源不偏心，也不歧视。


def background_authority_weight(source: str) -> float:
    """某竖源在背景档的权威度权重（查唯一真身表；未登记=1.0 中性）。"""
    ladder_id = _LADDER_SOURCE_IDS.get(str(source or "").strip(), "")
    return BACKGROUND_AUTHORITY_WEIGHTS.get(ladder_id, 1.0)


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
            if -age_days > _FUTURE_HORIZON_DAYS:
                # 脏值（2999-01-01 一类）不当"最新"：旧判据对未来日期一律给最高
                # 权重，于是一条坏数据能压过所有可信条目排在块首，模型会把它当新瓜。
                return _LATEST_UNKNOWN_WEIGHT
            # 合理窗口内的未来日期（预放送/预约卡池）：对「最新档」是强信号。
            return 1.6
        for bound, weight in _LATEST_WEIGHTS:
            if age_days <= bound:
                return weight
        return _LATEST_OLD_WEIGHT
    return background_authority_weight(source)


def _date_label(result: AcgResult, *, timeliness: str, today: date | None) -> str:
    """身份括号里的日期段：可解析才写，写不出来就如实说不知道。

    三态分开是刻意的：「没有日期」「日期是垃圾」「日期还没到」对回答的约束
    完全不同，把它们糊成同一个样就会让脏数据冒充最新。
    参照日用调用方传进来的 `today`（融合口本来就带着它），**本件不读挂钟**——
    读了就没有确定性可测，也和 `parse_result_date` 那套纯函数口径不一致。
    """
    text = str(result.date or "").strip()
    if not text:
        return "日期未知" if timeliness == TIMELINESS_LATEST else ""
    parsed = parse_result_date(text)
    if parsed is None:
        return _DATE_SUSPECT_LABEL
    if today is not None and parsed > today:
        if (parsed - today).days > _FUTURE_HORIZON_DAYS:
            return _DATE_SUSPECT_LABEL
        return f"{parsed.isoformat()}·未到期"
    return parsed.isoformat()


def source_identity_label(result: AcgResult, *, timeliness: str = "", today: date | None = None) -> str:
    """一条竖源命中的**可核对身份**括号段：``（萌娘百科·2026-09-16·id=123456）``。

    为什么身份必须进文本而不是只留在 ``url`` 字段里：渲染【联网检索】的那
    一层只取 title/snippet/source_domain，**url 不送进提示词**——于是模型
    与用户都无从回查"这条到底是谁"。取不到条目号时如实少一段，不拿标题冒充。
    """
    label = SOURCE_LABELS.get(result.source, result.source)
    parts = [label]
    date_part = _date_label(result, timeliness=timeliness, today=today)
    if date_part:
        parts.append(date_part)
    if result.item_id:
        parts.append(f"id={result.item_id}")
    return f"（{'·'.join(parts)}）"


def _can_be_checked_back(result: AcgResult) -> bool:
    """这条命中能不能被人核对：有合法条目号，或有一条指向本站的绝对链接。"""
    return bool(result.item_id) or bool(_link_host(result.url))


def _annotate(result: AcgResult, *, timeliness: str, today: date | None = None) -> str:
    """把「来源·日期·条目身份」注进摘要行（最新档必须可判新旧）。

    回查不了的那条要**明说**：一条长得和可核对命中一模一样的行，
    会让模型把它当有据可查的事实写进回答，也会让她以为点开就能看到出处。
    """
    snippet = result.snippet or result.extra
    if result.snippet and result.extra:
        snippet = f"{result.snippet}；{result.extra}"
    head = source_identity_label(result, timeliness=timeliness, today=today)
    if not _can_be_checked_back(result):
        head = f"{head}{UNVERIFIABLE_MARK}"
    return f"{head}{snippet}".strip()


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
    - ACG 条目 title 加竖源标签前缀，摘要行首注「（来源·日期·条目号）」；
    - web 结果文本保持原样，只参与加权排序；
    - 权重降序、同权重保持传入序（稳定）。
    """
    # 编排口已过一遍筛；这里再过一次同一道筛（幂等），因为**直连融合口的
    # 调用方不止 chat.py**（中央调度臂、以及任何后来接这条腿的人）。
    # 筛在两处调同一个函数、判据只有一份真身，不算第二道闸。
    acg_results, _reasons = screen_vertical_results(acg_results)
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
            # `_one_line`：一行一条是【联网检索】的结构前提。上游标题/摘要里
            # 混进换行时，前后两条会并成一条——那是这类融合里最容易发生、
            # 也最难在事后发现的"把 A 的说法安到 B 头上"。
            title=_one_line(f"[{label}] {result.title}"),
            snippet=_one_line(_annotate(result, timeliness=intent.timeliness, today=today)),
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
