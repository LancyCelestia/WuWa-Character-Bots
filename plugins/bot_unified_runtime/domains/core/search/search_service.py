"""S10 多平台搜索统一协议——离线核心层（V2.1 W7 席，2026-09-17）。

合同：``docs/design/backend-v2-product-extensions.md`` §6。本模块是
**离线核心**：provider 一律注入（测试用 fake），自身零网络；真实网络
验收与 REST 路由（/search/*）不在本席范围（live=blocked 登记）。

职责与安全边界：
- 九源 + general 的 source_id 注册表（§6.1 表逐行能力元数据，含中文显示名）；
- ``plan_search / authorize_sources / search_provider / normalize_hit /
  deduplicate_hits / rank_hits / fetch_reference`` 函数面 +
  ``UnifiedSearchService`` 门面（缓存/游标/预算/并发编排）；
- 预算：总 deadline 12s、单源 6s、按源并发上限 2（线程池，业务内部
  I/O 并发，不代表派 AI 子代理）、失败最多一次安全重试；
- 缓存：TTL 普通 300s / 热点 60s，键含 owner/scope/query/source/version，
  私有内容绝不与公众共用（owner+workspace 进键，测试锁定）；
- **引用正文无执行权**：SearchHit / FetchedReference 的 title/snippet/
  content 一律是纯文本数据，原样透传、不解释、不路由到任何执行器——
  本模块结构上不存在以这些字段为输入的执行点（唯一的"取回"动作是
  ``fetch_reference`` 按 citation_id 取 URL，且必须先过 SSRF 护栏）；
- SSRF：``fetch_reference`` 只接受本次授权命中发放的 citation_id，
  结构上不接任意 URL；取回前对 canonical_url 复用既有护栏
  ``sources/parsers/ssrf_guard.guard_user_url``（拒绝 localhost/内网/
  metadata 端点/整型 IP，防御纵深）。

provider 接口（``SearchProvider``）刻意独立于 ``sources/web_search.py``
的 ``WebSearchProvider``：那是通用引擎链的具体实现（只读复用对象），
本模块是协议层——未来把 web_search 的链包装成本协议 provider 即可上车。
"""

from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import hmac
import json
import re
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol, TypeVar
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from plugins.bot_unified_runtime.domains.core.shared_pool import get_shared_pool
from plugins.bot_unified_runtime.domains.link_parse.parsers.ssrf_guard import (
    check_fetch_landing,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.ssrf_guard import (
    guard_user_url as _default_guard,
)

# 复用面再导出：本模块的引用取回护栏即既有 ssrf_guard 本体（单一事实源）。
guard_user_url = _default_guard

__all__ = [
    "ANSWER_SOURCE_LADDER_BACKGROUND",
    "ANSWER_SOURCE_LADDER_LATEST",
    "BACKGROUND_AUTHORITY_WEIGHTS",
    "CACHE_KEY_VERSION",
    "CACHE_TTL_HOT_SECONDS",
    "CACHE_TTL_NORMAL_SECONDS",
    "DEFAULT_LIMIT",
    "KB_SOURCE_PERSONA",
    "KB_SOURCE_WIKI",
    "LIMIT_MAX",
    "LOCAL_KB_SOURCE_IDS",
    "PER_SOURCE_CONCURRENCY",
    "PER_SOURCE_DEADLINE_SECONDS",
    "QUERY_MAX_CHARS",
    "RRF_K",
    "SOURCE_IDS_MAX",
    "SOURCE_REGISTRY",
    "TOTAL_DEADLINE_SECONDS",
    "TOTAL_TIMEOUT_SECONDS",
    "AnswerOrder",
    "ContentLevel",
    "CursorPrincipalMismatchError",
    "FetchedReference",
    "KnowledgeHitView",
    "KnowledgeMissDeclarationError",
    "MalformedCursorError",
    "OverallStatus",
    "ProviderAuthError",
    "ProviderCallResult",
    "ProviderQuery",
    "ProviderRawHit",
    "ProviderRestrictedError",
    "ProviderTransientError",
    "ReferenceBlockedError",
    "ReferenceNotAuthorizedError",
    "SearchCache",
    "SearchHit",
    "SearchPlan",
    "SearchProvider",
    "SearchRequest",
    "SearchResponse",
    "SearchServiceError",
    "SearchSnapshot",
    "SourceCapabilities",
    "SourceDecision",
    "SourceOutcome",
    "SourceRunStatus",
    "SourceTask",
    "UnifiedSearchService",
    "answer_source_rank",
    "authorize_sources",
    "check_fetch_landing",
    "chunk_source_library",
    "deduplicate_hits",
    "existence_denial_hit",
    "fetch_reference",
    "format_knowledge_citation",
    "format_knowledge_hit_lines",
    "guard_user_url",
    "issue_cursor",
    "iter_existence_denials",
    "knowledge_chunks_by_source",
    "knowledge_context_block",
    "knowledge_hit_view",
    "list_sources",
    "make_cache_key",
    "normalize_hit",
    "order_answer_sources",
    "order_retrievers",
    "ordered_retriever_legs",
    "plan_search",
    "query_fingerprint",
    "rank_hits",
    "reorder_knowledge_chunks",
    "resolve_answer_order",
    "rewrite_existence_denials",
    "search_provider",
    "source_library_label",
    "validate_miss_declaration",
]

# ===========================================================================
# 常量（§6.2 预算与缓存口径）
# ===========================================================================

QUERY_MAX_CHARS = 500
SOURCE_IDS_MAX = 5
DEFAULT_LIMIT = 10
LIMIT_MAX = 20
TOTAL_DEADLINE_SECONDS = 12.0
PER_SOURCE_DEADLINE_SECONDS = 6.0
PER_SOURCE_CONCURRENCY = 2
MAX_SAFE_RETRIES = 1  # 失败最多一次可安全重试
CACHE_TTL_NORMAL_SECONDS = 300.0
CACHE_TTL_HOT_SECONDS = 60.0
CACHE_HOT_ACCESS_THRESHOLD = 3  # 同键访问≥3 次判定为热点
CACHE_KEY_VERSION = "v21-w7-1"  # 缓存键版本（语义变更时递增防串味）
RRF_K = 60
TOTAL_TIMEOUT_SECONDS = TOTAL_DEADLINE_SECONDS  # 别名（合同口径"总 deadline"）

# 游标签名密钥：离线层固定常量（防篡改/跨主体，不承担跨进程密钥职责；
# 生产接入时从配置注入替换——届时游标即刻失效一次，属预期）。
_CURSOR_HMAC_KEY = b"shorekeeper-search-v21-w7-cursor-key"


# ===========================================================================
# 错误类型
# ===========================================================================


class SearchServiceError(Exception):
    """统一搜索协议错误基类。"""


class CursorError(SearchServiceError):
    """游标类错误基类。"""


class MalformedCursorError(CursorError):
    """游标缺失/篡改/签名不符/与当前查询不匹配。"""


class CursorPrincipalMismatchError(CursorError):
    """游标与当前主体不匹配（跨主体取游标——拒绝）。"""


class ReferenceNotAuthorizedError(SearchServiceError):
    """引用不在本次授权命中集合内（伪造/跨主体引用——拒绝）。"""


class ReferenceBlockedError(SearchServiceError):
    """引用取回被 SSRF 护栏拒绝（localhost/内网/metadata 等）。"""


class ProviderRateLimitedError(Exception):
    """provider 限流（不重试）。"""


class ProviderAuthError(Exception):
    """provider 鉴权失败（不重试）。"""


class ProviderRestrictedError(Exception):
    """provider 登录/风控受限（如小红书 restricted，不重试）。"""


class ProviderTransientError(Exception):
    """provider 瞬态故障（最多一次安全重试）。"""


# ===========================================================================
# 枚举
# ===========================================================================


class ContentLevel(str, Enum):
    """内容级别：metadata < snippet < full（绝不把 snippet 误标成 full）。"""

    METADATA = "metadata"
    SNIPPET = "snippet"
    FULL = "full"


class AccessStatus(str, Enum):
    """访问状态（§6.1：受限/保护内容必须显式标记）。"""

    PUBLIC = "public"
    RESTRICTED = "restricted"
    PROTECTED = "protected"
    UNKNOWN = "unknown"


class SourceRunStatus(str, Enum):
    """per-source 运行状态。"""

    OK = "ok"
    EMPTY = "empty"  # 源正常应答但零命中
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTH_FAILED = "auth_failed"
    RESTRICTED = "restricted"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"  # 未配置 provider 等
    UNAUTHORIZED = "unauthorized"  # 未知/未登记 source_id
    FAILED = "failed"


class OverallStatus(str, Enum):
    """整体状态：部分失败可 partial；全部失败 dependency_unavailable。"""

    OK = "ok"
    PARTIAL = "partial"
    EMPTY = "empty"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"


# ===========================================================================
# DTO（pydantic 严格模式；超限=ValidationError 带字段定位，上层映射 422）
# ===========================================================================


class _StrictModel(BaseModel):
    """严格配置基类：禁止额外字段、禁隐式类型矫正、不可变。"""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class DateRange(_StrictModel):
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def _check_order(self) -> DateRange:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("date_range.start 不能晚于 date_range.end")
        return self


class SearchRequest(_StrictModel):
    """统一搜索请求（§6.2 DTO）。"""

    query: str = Field(min_length=1, max_length=QUERY_MAX_CHARS)
    source_ids: list[str] = Field(min_length=1, max_length=SOURCE_IDS_MAX)
    kinds: list[str] = Field(default_factory=list)
    date_range: DateRange | None = None
    language: str | None = Field(default=None, max_length=16)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=LIMIT_MAX)
    cursor: str | None = Field(default=None, max_length=2048)
    workspace_id: str | None = Field(default=None, max_length=128)

    @field_validator("source_ids")
    @classmethod
    def _check_source_ids(cls, value: list[str]) -> list[str]:
        for sid in value:
            if not sid or len(sid) > 64:
                raise ValueError("source_ids 每项必须是非空且≤64 字符的来源标识")
        return value

    @field_validator("kinds")
    @classmethod
    def _check_kinds(cls, value: list[str]) -> list[str]:
        if len(value) > 10:
            raise ValueError("kinds 最多 10 项")
        for kind in value:
            if not kind or len(kind) > 40:
                raise ValueError("kinds 每项必须是非空且≤40 字符的内容类型")
        return value


class ProviderQuery(_StrictModel):
    """发给单个 provider 的子任务查询（scope 控制私库边界）。"""

    source_id: str
    query: str
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=LIMIT_MAX)
    kinds: list[str] = Field(default_factory=list)
    date_range: DateRange | None = None
    language: str | None = None
    scope: str = "public"  # public | private（github 私库须授予 scope）


class ProviderRawHit(_StrictModel):
    """provider 返回的原始命中（normalize 前的形态）。"""

    title: str = ""
    url: str = Field(min_length=1)
    snippet: str = ""
    item_id: str = ""
    author: str | None = None
    published_at: datetime | None = None  # 源站未知保持 None，绝不拿抓取时间顶替
    content_level: ContentLevel = ContentLevel.SNIPPET
    access_status: AccessStatus = AccessStatus.PUBLIC
    retrieval_mode: str = "provider"


class SearchHit(_StrictModel):
    """统一命中（§6.2 DTO）。正文类字段均为纯文本数据（无执行权）。"""

    id: str
    title: str
    canonical_url: str
    source_id: str
    author: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    snippet: str = ""
    content_level: ContentLevel = ContentLevel.SNIPPET
    retrieval_mode: str = "provider"
    access_status: AccessStatus = AccessStatus.PUBLIC
    relevance: float = 0.0
    citation_id: str = ""


class SourceOutcome(_StrictModel):
    """per-source 状态（§6.2：结果必须带 per_source 状态）。"""

    source_id: str
    status: SourceRunStatus
    detail: str = ""
    hit_count: int = Field(default=0, ge=0)
    attempts: int = Field(default=1, ge=1)
    elapsed_ms: int = Field(default=0, ge=0)


class SearchResponse(_StrictModel):
    """统一搜索响应。hits 已排序；分页由 next_cursor 承载。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str
    status: OverallStatus
    hits: list[SearchHit] = Field(default_factory=list)
    per_source: list[SourceOutcome] = Field(default_factory=list)
    ordering_reason: str = ""
    empty_reason: str | None = None
    next_cursor: str | None = None
    cache_state: str = "miss"  # hit | miss
    total_deadline_seconds: float = TOTAL_DEADLINE_SECONDS
    per_source_deadline_seconds: float = PER_SOURCE_DEADLINE_SECONDS


# ===========================================================================
# 源注册表（§6.1 表逐行）
# ===========================================================================


class SourceCapabilities(_StrictModel):
    source_id: str
    display_name: str  # 中文显示名
    preferred_mode: str  # 优先方式
    fallback_and_limits: str  # 有条件 fallback 与限制
    requires_authorized_provider: bool = False  # true=必须有授权 provider 才可用
    private_scope_supported: bool = False  # true=支持私域 scope（如 github 私库）


def _cap(
    source_id: str,
    display_name: str,
    preferred_mode: str,
    fallback_and_limits: str,
    *,
    requires_authorized_provider: bool = False,
    private_scope_supported: bool = False,
) -> SourceCapabilities:
    return SourceCapabilities(
        source_id=source_id,
        display_name=display_name,
        preferred_mode=preferred_mode,
        fallback_and_limits=fallback_and_limits,
        requires_authorized_provider=requires_authorized_provider,
        private_scope_supported=private_scope_supported,
    )


SOURCE_REGISTRY: dict[str, SourceCapabilities] = {
    caps.source_id: caps
    for caps in [
        _cap(
            "bilibili",
            "哔哩哔哩（B站）",
            "已授权官方接口/现有合规公开检索",
            "搜索引擎 site:bilibili.com；字幕单独标 available/unknown",
        ),
        _cap(
            "xiaohongshu",
            "小红书",
            "授权连接器或用户明确授权可访问内容",
            "搜索引擎 site:xiaohongshu.com；登录/风控受限返回 restricted",
            requires_authorized_provider=True,
        ),
        _cap(
            "youtube",
            "YouTube",
            "YouTube Data 检索及授权字幕能力",
            "搜索引擎 site:youtube.com；搜索命中不等于字幕已读取",
        ),
        _cap(
            "x",
            "推特/X",
            "授权 X API、已批准连接器",
            "搜索引擎 site:x.com 并标索引滞后，保护内容不访问",
        ),
        _cap(
            "github",
            "GitHub",
            "官方 repo/code/issues 搜索，各自权限/配额",
            "搜索引擎 site:github.com；私库只在授予 scope 内，不送公共搜索引擎",
            private_scope_supported=True,
        ),
        _cap(
            "linux_do",
            "Linux Do 论坛",
            "站点允许的 Discourse 检索或授权连接器",
            "搜索引擎 site:linux.do；会员区保持登录权限边界",
        ),
        _cap(
            "csdn",
            "CSDN 博客",
            "合规搜索 provider、公开页面读取",
            "搜索引擎 site:blog.csdn.net；付费正文不绕过",
        ),
        _cap(
            "zhihu",
            "知乎",
            "授权能力/公开索引",
            "搜索引擎 site:zhihu.com；片段与全文分别标记",
        ),
        _cap(
            "cnki",
            "知网（CNKI）",
            "有授权的知网检索/机构连接器",
            "搜索引擎 site:cnki.net 只提供可验证元数据/链接；无权不取全文",
            requires_authorized_provider=True,
        ),
        _cap(
            "general",
            "通用搜索（provider 链）",
            "已登记通用搜索 provider 链",
            "无 provider 就 dependency_unavailable，不编造结果",
        ),
    ]
}


def list_sources() -> list[SourceCapabilities]:
    """登记表全量（未来 GET /search/sources 的数据面）。"""
    return list(SOURCE_REGISTRY.values())


# ===========================================================================
# provider 协议与单源执行
# ===========================================================================


class SearchProvider(Protocol):
    """可注入 provider 接口：离线测试注入 fake，生产包装真实引擎链。"""

    def search(self, query: ProviderQuery) -> list[ProviderRawHit]:
        """返回原始命中；业务异常用上方 Provider*Error 表达。"""
        ...


@dataclass(frozen=True)
class SourceTask:
    """plan 产出的单源任务。"""

    source_id: str
    query: ProviderQuery
    budget_seconds: float


@dataclass(frozen=True)
class SourceDecision:
    """authorize 的产物：可执行（provider+scope）或带原因的跳过决定。"""

    source_id: str
    provider: SearchProvider | None
    scope: str
    outcome: SourceOutcome


@dataclass(frozen=True)
class SearchPlan:
    tasks: list[SourceTask]
    skipped: list[SourceDecision] = field(default_factory=list)
    started_at: float = 0.0
    total_deadline_seconds: float = TOTAL_DEADLINE_SECONDS
    per_source_deadline_seconds: float = PER_SOURCE_DEADLINE_SECONDS
    concurrency: int = PER_SOURCE_CONCURRENCY


@dataclass(frozen=True)
class ProviderCallResult:
    source_id: str
    hits: list[ProviderRawHit]
    status: SourceRunStatus
    attempts: int = 1
    detail: str = ""
    elapsed_ms: int = 0


def authorize_sources(
    request: SearchRequest,
    *,
    providers: Mapping[str, SearchProvider] | None,
    grants: Iterable[str] | None = None,
    registry: Mapping[str, SourceCapabilities] = SOURCE_REGISTRY,
) -> list[SourceDecision]:
    """来源授权：未知源→unauthorized；未配 provider→dependency_unavailable。

    私域 scope（github 私库）必须由 grants 显式授予（如 "github:private"），
    绝不默认放行；未授予时按 public 语义下发 provider。
    """
    grant_set = set(grants or ())
    seen: set[str] = set()
    decisions: list[SourceDecision] = []
    for sid in request.source_ids:
        if sid in seen:  # 重复 source_id 只授权一次
            continue
        seen.add(sid)
        caps = registry.get(sid)
        if caps is None:
            decisions.append(
                SourceDecision(
                    source_id=sid,
                    provider=None,
                    scope="public",
                    outcome=SourceOutcome(
                        source_id=sid,
                        status=SourceRunStatus.UNAUTHORIZED,
                        detail="未知来源：不在统一来源注册表中",
                    ),
                )
            )
            continue
        provider = (providers or {}).get(sid)
        if provider is None:
            decisions.append(
                SourceDecision(
                    source_id=sid,
                    provider=None,
                    scope="public",
                    outcome=SourceOutcome(
                        source_id=sid,
                        status=SourceRunStatus.DEPENDENCY_UNAVAILABLE,
                        detail="未配置 provider：该源暂不可用（不编造结果）",
                    ),
                )
            )
            continue
        scope = (
            "private"
            if caps.private_scope_supported and f"{sid}:private" in grant_set
            else "public"
        )
        decisions.append(
            SourceDecision(
                source_id=sid,
                provider=provider,
                scope=scope,
                outcome=SourceOutcome(source_id=sid, status=SourceRunStatus.OK),
            )
        )
    return decisions


def plan_search(
    request: SearchRequest,
    *,
    decisions: Sequence[SourceDecision],
    clock: Callable[[], float] = time.monotonic,
    total_deadline: float = TOTAL_DEADLINE_SECONDS,
    per_source_deadline: float = PER_SOURCE_DEADLINE_SECONDS,
    concurrency: int = PER_SOURCE_CONCURRENCY,
) -> SearchPlan:
    """编排计划：可执行源→任务（预算 6s，受总 12s 钳制）；其余→skipped。"""
    started_at = clock()
    tasks: list[SourceTask] = []
    skipped: list[SourceDecision] = []
    for decision in decisions:
        if decision.provider is None or decision.outcome.status is not SourceRunStatus.OK:
            skipped.append(decision)
            continue
        budget = min(per_source_deadline, max(0.0, total_deadline))
        tasks.append(
            SourceTask(
                source_id=decision.source_id,
                query=ProviderQuery(
                    source_id=decision.source_id,
                    query=request.query,
                    limit=request.limit,
                    kinds=list(request.kinds),
                    date_range=request.date_range,
                    language=request.language,
                    scope=decision.scope,
                ),
                budget_seconds=budget,
            )
        )
    return SearchPlan(
        tasks=tasks,
        skipped=skipped,
        started_at=started_at,
        total_deadline_seconds=total_deadline,
        per_source_deadline_seconds=per_source_deadline,
        concurrency=concurrency,
    )


def search_provider(
    provider: SearchProvider,
    task: SourceTask,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> ProviderCallResult:
    """单源执行（同步，含最多一次瞬态重试）。

    超时钳制由编排层负责（future.result 等待 budget）；本函数只负责
    异常分类与重试语义。elapsed 用注入时钟计量。
    """
    started = clock()
    attempts = 0
    detail = ""
    while True:
        attempts += 1
        try:
            hits = provider.search(task.query)
            return ProviderCallResult(
                source_id=task.source_id,
                hits=list(hits),
                status=SourceRunStatus.OK,
                attempts=attempts,
                elapsed_ms=int((clock() - started) * 1000),
            )
        except ProviderRateLimitedError as exc:
            detail = f"限流：{exc}"
            status = SourceRunStatus.RATE_LIMITED
        except ProviderAuthError as exc:
            detail = f"鉴权失败：{exc}"
            status = SourceRunStatus.AUTH_FAILED
        except ProviderRestrictedError as exc:
            detail = f"登录/风控受限：{exc}"
            status = SourceRunStatus.RESTRICTED
        except ProviderTransientError as exc:
            if attempts <= MAX_SAFE_RETRIES:
                continue  # 最多一次可安全重试
            detail = f"瞬态失败（已重试 {MAX_SAFE_RETRIES} 次）：{exc}"
            status = SourceRunStatus.FAILED
        except Exception as exc:  # noqa: BLE001 —— 未预期异常按失败分类，不外泄
            detail = f"未预期异常：{type(exc).__name__}"
            status = SourceRunStatus.FAILED
        return ProviderCallResult(
            source_id=task.source_id,
            hits=[],
            status=status,
            attempts=attempts,
            detail=detail,
            elapsed_ms=int((clock() - started) * 1000),
        )


# ===========================================================================
# URL 规范化 / 平台 item_id / 命中归一
# ===========================================================================

# 只剥已知跟踪参数；其余参数（内容标识等）一律保留——宁可少剥不可误剥。
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_name",
        "spm",
        "spm_id_from",
        "spm_from",
        "share_token",
        "share_source",
        "share_medium",
        "share_from",
        "share_app_id",
        "share_poi",
        "share_link",
        "share_to",
        "vd_source",
        "xd_token",
        "social_platform",
        "app_platform",
        "from_singlesource",
        "tt_from",
        "refer_from",
    }
)

# 平台 item_id 提取（dedupe 的平台标识优先口径）。cnki 无稳定公开
# item_id，回退 URL 指纹。
_ITEM_ID_PATTERNS: dict[str, tuple[tuple[str, ...], ...]] = {
    "bilibili": ((r"(BV[0-9A-Za-z]{10})",), (r"av(\d{6,})",)),
    "youtube": ((r"[?&]v=([\w-]{6,})",), (r"/shorts/([\w-]{6,})",)),
    "x": ((r"/status/(\d+)",),),
    "github": ((r"github\.com/([^/\s]+)/([^/\s?#]+)/?", r"(?:/(?:issues|pull|discussions)/(\d+))?"),),
    "zhihu": (
        (r"/question/(\d+)", r"(?:/answer/(\d+))?"),
        (r"/pin/(\d+)",),
        (r"zhuanlan\.zhihu\.com/p/(\d+)",),
    ),
    "xiaohongshu": ((r"/(?:explore|discovery/item)/([0-9a-fA-F]{12,32})",),),
    "csdn": ((r"/article/details/(\d+)",),),
    "linux_do": ((r"/t/(?:topic/)?(?:[^/\s]+/)?(\d+)",),),
    "cnki": (),
}


def normalize_canonical_url(url: str) -> str:
    """规范化 URL：小写 scheme/host、剥已知跟踪参数、保留其余原样。"""
    text = (url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        if not parts.scheme and not parts.netloc:
            return text
        query_pairs = [
            (k, v)
            for k, v in [
                item.split("=", 1) if "=" in item else (item, "")
                for item in parts.query.split("&")
                if item
            ]
            if k.lower() not in _TRACKING_PARAMS
        ]
        query = "&".join(f"{k}={v}" if v or v == "" else k for k, v in query_pairs)
        netloc = parts.netloc
        at = netloc.rfind("@")
        userinfo = netloc[: at + 1] if at != -1 else ""
        hostport = netloc[at + 1 :]
        slash = hostport.find("/")
        host = hostport[:slash] if slash != -1 else hostport
        rest = hostport[slash:] if slash != -1 else ""
        netloc = userinfo + host.lower() + rest
        return urlunsplit((parts.scheme.lower(), netloc, parts.path, query, parts.fragment))
    except ValueError:
        return text  # 畸形 URL 原样保留，交由上层/护栏拒绝


def extract_item_id(url: str, source_id: str) -> str:
    """平台 item_id（dedupe 平台标识优先）；无稳定 id 返回空串。"""
    for pattern_group in _ITEM_ID_PATTERNS.get(source_id, ()):
        matches = [re.search(p, url) for p in pattern_group]
        if all(m is not None for m in matches):
            values = [m.group(1) for m in matches if m is not None]
            if source_id == "github":
                owner, repo = values[0], values[1]
                number = values[2] if len(values) > 2 else ""
                return f"{owner}/{repo}#{number}" if number else f"{owner}/{repo}"
            return "/".join(values)
    return ""


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def derive_citation_id(source_id: str, item_id: str, canonical_url: str) -> str:
    """确定性派生 citation_id（后端发放；同源同内容永远同引用号）。"""
    basis = f"{source_id}|{item_id or canonical_url}"
    return f"cite_{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:12]}"


def normalize_hit(
    raw_hit: ProviderRawHit,
    *,
    source_id: str,
    retrieved_at: datetime,
) -> SearchHit:
    """原始命中 → 统一 SearchHit。

    - published_at 为 None 就保持 None，绝不拿 retrieved_at 顶替（合同明令）；
    - content_level 只取 provider 声明，本函数永不升级（snippet 不误标 full）；
    - snippet/title 原样透传（prompt 注入文本只是数据）。
    """
    canonical = normalize_canonical_url(raw_hit.url)
    item_id = raw_hit.item_id or extract_item_id(canonical, source_id)
    return SearchHit(
        id=f"{source_id}:{item_id or _short_hash(canonical)}",
        title=raw_hit.title,
        canonical_url=canonical,
        source_id=source_id,
        author=raw_hit.author,
        published_at=raw_hit.published_at,
        retrieved_at=retrieved_at,
        snippet=raw_hit.snippet,
        content_level=raw_hit.content_level,
        retrieval_mode=raw_hit.retrieval_mode,
        access_status=raw_hit.access_status,
        relevance=0.0,
        citation_id=derive_citation_id(source_id, item_id, canonical),
    )


def hit_identity(hit: SearchHit) -> tuple[str, str]:
    """去重身份（单键形态，保留给排序展示用）：item 键优先，回退 URL 键。"""
    item_id = hit.id.split(":", 1)[1] if ":" in hit.id else ""
    if item_id:
        return (hit.source_id, item_id)
    return ("", hit.canonical_url)


def hit_identity_keys(hit: SearchHit) -> tuple[tuple[str, str], tuple[str, str]]:
    """去重身份键组：①平台 item 键（item_id 优先口径）②规范化 URL 键。

    两组键任一已见即判重——同源同 item 的变体参数 URL、以及跨源转载
    的同一规范化链接都会收敛到先到者。
    """
    item_id = hit.id.split(":", 1)[1] if ":" in hit.id else ""
    item_key = (hit.source_id, item_id) if item_id else (hit.source_id, "\x00url:" + hit.canonical_url)
    url_key = ("", hit.canonical_url)
    return item_key, url_key


def _hit_is_duplicate(seen: set[tuple[str, str]], hit: SearchHit) -> bool:
    item_key, url_key = hit_identity_keys(hit)
    return item_key in seen or url_key in seen


def _mark_hit_seen(seen: set[tuple[str, str]], hit: SearchHit) -> None:
    item_key, url_key = hit_identity_keys(hit)
    seen.add(item_key)
    seen.add(url_key)


def deduplicate_hits(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """去重：同身份保留先到者（输入顺序决定优先级）。"""
    seen: set[tuple[str, str]] = set()
    out: list[SearchHit] = []
    for hit in hits:
        if _hit_is_duplicate(seen, hit):
            continue
        _mark_hit_seen(seen, hit)
        out.append(hit)
    return out


# ===========================================================================
# 排名：多路 RRF（k=60）+ 条件性时效加权
# ===========================================================================

_FRESHNESS_BONUS_1D = 0.25
_FRESHNESS_BONUS_7D = 0.10
_FRESHNESS_BONUS_30D = 0.05


@dataclass(frozen=True)
class RankResult:
    hits: list[SearchHit]
    reason: str


def _freshness_bonus(published_at: datetime | None, now: datetime) -> float:
    """时效加成只在任务要求新鲜度时由 rank_hits 启用。"""
    if published_at is None:
        return 0.0
    published = published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age = now - published
    if age < timedelta(days=1):
        return _FRESHNESS_BONUS_1D
    if age < timedelta(days=7):
        return _FRESHNESS_BONUS_7D
    if age < timedelta(days=30):
        return _FRESHNESS_BONUS_30D
    return 0.0


def rank_hits(
    per_source_lists: Sequence[Sequence[SearchHit]],
    *,
    freshness_required: bool,
    now: datetime,
    k: int = RRF_K,
) -> RankResult:
    """多路 RRF：score=Σ 1/(k+rank)；跨源重复只保留首现身份但累计名分。

    并列按（源序, 位次）稳定排序；时效加权（freshness_required）仅在
    任务带 date_range 等新鲜度要求时启用，理由随结果记录。
    """
    scores: dict[str, float] = {}
    first_seen: dict[tuple[str, str], SearchHit] = {}
    seen: set[tuple[str, str]] = set()
    for _source_index, hits in enumerate(per_source_lists):
        for position, hit in enumerate(hits, start=1):
            scores[hit.citation_id] = scores.get(hit.citation_id, 0.0) + 1.0 / (k + position)
            if not _hit_is_duplicate(seen, hit):
                _mark_hit_seen(seen, hit)
                first_seen[hit_identity(hit)] = hit
    entries = list(first_seen.values())

    def _final_score(hit: SearchHit) -> float:
        base = scores.get(hit.citation_id, 0.0)
        if not freshness_required:
            return base
        return base * (1.0 + _freshness_bonus(hit.published_at, now))

    ranked = sorted(entries, key=_final_score, reverse=True)  # 稳定排序保 (源序,位次)
    reason = f"rrf(k={k})"
    if freshness_required:
        reason += "+时效加权"
    out = [
        hit.model_copy(update={"relevance": round(_final_score(hit), 6)}) for hit in ranked
    ]
    return RankResult(hits=out, reason=reason)


# ===========================================================================
# 游标（签名绑定主体 + 查询指纹）
# ===========================================================================


@dataclass(frozen=True)
class _CursorPayload:
    owner_id: str
    workspace_id: str
    fingerprint: str
    offset: int


def query_fingerprint(request: SearchRequest) -> str:
    """查询指纹：影响结果集的请求字段的稳定摘要（不含 limit/cursor）。"""
    date_range = ""
    if request.date_range is not None:
        start = request.date_range.start.isoformat() if request.date_range.start else ""
        end = request.date_range.end.isoformat() if request.date_range.end else ""
        date_range = f"{start}..{end}"
    parts = [
        request.query,
        ",".join(sorted(set(request.source_ids))),
        ",".join(request.kinds),
        request.language or "",
        date_range,
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def issue_cursor(
    *,
    owner_id: str,
    workspace_id: str,
    fingerprint: str,
    offset: int,
) -> str:
    """签发主体绑定游标：payload+HMAC 签名（防篡改、防跨主体）。"""
    payload = json.dumps(
        {
            "owner": owner_id,
            "workspace": workspace_id,
            "fp": fingerprint,
            "offset": offset,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    sig = hmac.new(_CURSOR_HMAC_KEY, payload, hashlib.sha256).digest()[:12]
    return f"{_b64encode(payload)}.{_b64encode(sig)}"


def _parse_cursor(token: str) -> _CursorPayload:
    try:
        payload_part, sig_part = token.split(".", 1)
        payload = _b64decode(payload_part)
        expected = hmac.new(_CURSOR_HMAC_KEY, payload, hashlib.sha256).digest()[:12]
        if not hmac.compare_digest(expected, _b64decode(sig_part)):
            raise MalformedCursorError("游标签名校验失败（疑似篡改）")
        data = json.loads(payload.decode("utf-8"))
        owner = data["owner"]
        workspace = data["workspace"]
        fingerprint = data["fp"]
        offset = data["offset"]
        if not all(isinstance(v, str) for v in (owner, workspace, fingerprint)):
            raise MalformedCursorError("游标字段类型非法")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise MalformedCursorError("游标偏移量非法")
        return _CursorPayload(
            owner_id=owner,
            workspace_id=workspace,
            fingerprint=fingerprint,
            offset=offset,
        )
    except MalformedCursorError:
        raise
    except Exception as exc:
        raise MalformedCursorError(f"游标无法解析：{type(exc).__name__}") from exc


# ===========================================================================
# 缓存（TTL 300/60；键含 owner/scope/query/source/version）
# ===========================================================================


class SearchSnapshot(_StrictModel):
    """缓存的可复用结果（不含分页——分页在快照上按请求切）。"""

    ranked_hits: list[SearchHit] = Field(default_factory=list)
    per_source: list[SourceOutcome] = Field(default_factory=list)
    ordering_reason: str = ""


def make_cache_key(
    owner_id: str,
    workspace_id: str,
    fingerprint: str,
    source_ids: Sequence[str],
) -> str:
    """owner+scope(workspace)+query(指纹)+source+version 全部进键——
    同 query 不同 owner/工作区必然不同键（私有内容绝不与公众共用）。"""
    basis = "\x1f".join(
        [
            CACHE_KEY_VERSION,
            owner_id,
            workspace_id,
            fingerprint,
            ",".join(sorted(set(source_ids))),
        ]
    )
    return f"srch:{CACHE_KEY_VERSION}:{hashlib.sha256(basis.encode('utf-8')).hexdigest()}"


@dataclass
class _CacheEntry:
    snapshot: SearchSnapshot
    created_at: float
    accesses: int = 0


class SearchCache:
    """内存 TTL 缓存。普通 300s；热点（访问≥阈值）60s 保新鲜。"""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_normal: float = CACHE_TTL_NORMAL_SECONDS,
        ttl_hot: float = CACHE_TTL_HOT_SECONDS,
        hot_access_threshold: int = CACHE_HOT_ACCESS_THRESHOLD,
        max_entries: int = 512,
    ) -> None:
        self._clock = clock
        self._ttl_normal = ttl_normal
        self._ttl_hot = ttl_hot
        self._hot_threshold = hot_access_threshold
        self._max_entries = max_entries
        self._entries: dict[str, _CacheEntry] = {}

    def get(self, key: str) -> SearchSnapshot | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        now = self._clock()
        effective_ttl = (
            self._ttl_hot if entry.accesses >= self._hot_threshold else self._ttl_normal
        )
        if now - entry.created_at > effective_ttl:
            del self._entries[key]
            return None
        entry.accesses += 1
        return entry.snapshot

    def put(self, key: str, snapshot: SearchSnapshot) -> None:
        if len(self._entries) >= self._max_entries:
            # 简单 FIFO 淘汰（离线层够用；生产可换 LRU）。
            oldest = next(iter(self._entries))
            del self._entries[oldest]
        self._entries[key] = _CacheEntry(snapshot=snapshot, created_at=self._clock())


# ===========================================================================
# 引用取回（仅限本次授权命中 + SSRF 护栏）
# ===========================================================================


@dataclass(frozen=True)
class FetchedReference:
    """取回的引用全文。content 是纯文本数据（无执行权）。"""

    citation_id: str
    hit: SearchHit
    content: str
    content_level: ContentLevel  # 取回成功=full；命中自身的 level 不回写


def fetch_reference(
    citation_id: str,
    *,
    context: Mapping[str, SearchHit],
    fetcher: Callable[[str], str],
    guard: Callable[[str], str | None] = _default_guard,
) -> FetchedReference:
    """按 citation_id 取回引用（**结构性不接任意 URL**）。

    - citation 必须来自调用方提供的"本次授权命中"上下文，否则拒绝；
    - 取回前对 canonical_url 过既有 SSRF 护栏（拒绝返回原因→异常）；
    - 取回内容标记 full；命中记录本身的 content_level 不被改写。
    """
    hit = context.get(citation_id)
    if hit is None:
        raise ReferenceNotAuthorizedError(
            "引用不在本次授权命中集合内：只允许取回本次搜索发放的 citation_id"
        )
    reason = guard(hit.canonical_url)
    if reason is not None:
        raise ReferenceBlockedError(f"引用取回被 SSRF 护栏拒绝：{reason}")
    content = fetcher(hit.canonical_url)
    return FetchedReference(
        citation_id=hit.citation_id,
        hit=hit,
        content=content,
        content_level=ContentLevel.FULL if content else ContentLevel.METADATA,
    )


# ===========================================================================
# 服务门面：授权→计划→并发执行→归一→去重→排名→缓存/分页
# ===========================================================================


def _overall_status(outcomes: Sequence[SourceOutcome], hit_count: int) -> OverallStatus:
    """整体状态推导：全部失败/无可用源→dependency_unavailable；有成有败→partial；
    全部正常应答但零命中→empty（与超时明确区分）。"""
    ran = [o for o in outcomes if o.status in (SourceRunStatus.OK, SourceRunStatus.EMPTY)]
    failures = [o for o in outcomes if o.status not in (SourceRunStatus.OK, SourceRunStatus.EMPTY)]
    if not outcomes or not ran:
        return OverallStatus.DEPENDENCY_UNAVAILABLE
    if failures:
        return OverallStatus.PARTIAL
    if hit_count == 0:
        return OverallStatus.EMPTY
    return OverallStatus.OK


class UnifiedSearchService:
    """统一搜索门面（离线核心）。

    - provider 表注入；每源并发上限默认 2（线程池）；总 12s/单源 6s；
    - 每主体（owner+workspace）记住最近一次搜索的授权命中，供
      ``fetch`` 做"本次授权"校验；
    - 时钟注入（clock=单调秒；now_fn=业务时刻）保证可测。
    """

    def __init__(
        self,
        providers: Mapping[str, SearchProvider] | None,
        *,
        cache: SearchCache | None = None,
        clock: Callable[[], float] = time.monotonic,
        now_fn: Callable[[], datetime] | None = None,
        concurrency: int = PER_SOURCE_CONCURRENCY,
        total_deadline: float = TOTAL_DEADLINE_SECONDS,
        per_source_deadline: float = PER_SOURCE_DEADLINE_SECONDS,
        fetcher: Callable[[str], str] | None = None,
        guard: Callable[[str], str | None] = _default_guard,
        registry: Mapping[str, SourceCapabilities] = SOURCE_REGISTRY,
    ) -> None:
        self._providers = dict(providers or {})
        self._cache = cache
        self._clock = clock
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._concurrency = max(1, concurrency)
        self._total_deadline = total_deadline
        self._per_source_deadline = per_source_deadline
        self._fetcher = fetcher
        self._guard = guard
        self._registry = registry
        self._sessions: dict[tuple[str, str], dict[str, SearchHit]] = {}

    # ---- 搜索 ----------------------------------------------------------

    def search(
        self,
        request: SearchRequest,
        *,
        owner_id: str,
        workspace_id: str = "",
        grants: Iterable[str] | None = None,
    ) -> SearchResponse:
        fingerprint = query_fingerprint(request)
        offset = 0
        if request.cursor is not None:
            payload = _parse_cursor(request.cursor)
            if payload.owner_id != owner_id or payload.workspace_id != workspace_id:
                raise CursorPrincipalMismatchError(
                    "游标与当前主体不匹配：分页游标只允许原主体续用"
                )
            if payload.fingerprint != fingerprint:
                raise MalformedCursorError("游标与当前查询不匹配")
            offset = payload.offset

        key = make_cache_key(owner_id, workspace_id, fingerprint, request.source_ids)
        snapshot = self._cache.get(key) if self._cache is not None else None
        if snapshot is not None:
            page, next_cursor = self._paginate(
                snapshot.ranked_hits, request, fingerprint, owner_id, workspace_id, offset
            )
            return SearchResponse(
                request_id=self._new_request_id(),
                status=_overall_status(snapshot.per_source, len(snapshot.ranked_hits)),
                hits=page,
                per_source=list(snapshot.per_source),
                ordering_reason=snapshot.ordering_reason,
                empty_reason=(
                    "所有已授权来源均已应答：未检索到相关内容（与超时/失败不同）"
                    if _overall_status(snapshot.per_source, len(snapshot.ranked_hits))
                    is OverallStatus.EMPTY
                    else None
                ),
                next_cursor=next_cursor,
                cache_state="hit",
                total_deadline_seconds=self._total_deadline,
                per_source_deadline_seconds=self._per_source_deadline,
            )

        decisions = authorize_sources(
            request, providers=self._providers, grants=grants, registry=self._registry
        )
        plan = plan_search(
            request,
            decisions=decisions,
            clock=self._clock,
            total_deadline=self._total_deadline,
            per_source_deadline=self._per_source_deadline,
            concurrency=self._concurrency,
        )
        provider_by_source = {d.source_id: d.provider for d in decisions if d.provider}

        outcomes: list[SourceOutcome] = [d.outcome for d in plan.skipped]
        per_source_lists: list[list[SearchHit]] = []
        retrieved_at = self._now_fn()

        # P2 减量波：逐次新建池 → 共享有界池（线程 churn 治理）。
        # 原 ``with`` 退出会 join 全部 future（含 _collect 已判 TIMEOUT 的
        # 迟到源）；共享池没有退出语义，循环后显式 wait 等齐，保持
        # 「返回前所有 futures 已完成」的旧墙钟语义（shared_pool 边界④）。
        pool = get_shared_pool()
        all_futures: list[concurrent.futures.Future[ProviderCallResult]] = []
        index = 0
        while index < len(plan.tasks):
            batch = plan.tasks[index : index + plan.concurrency]
            index += plan.concurrency
            futures = [
                (task, pool.submit(search_provider, provider_by_source[task.source_id], task, clock=self._clock))
                for task in batch
            ]
            all_futures.extend(future for _, future in futures)
            for task, future in futures:
                result = self._collect(task, future, plan)
                outcomes.append(
                    SourceOutcome(
                        source_id=result.source_id,
                        status=(
                            SourceRunStatus.EMPTY
                            if result.status is SourceRunStatus.OK and not result.hits
                            else result.status
                        ),
                        detail=result.detail,
                        hit_count=len(result.hits) if result.status is SourceRunStatus.OK else 0,
                        attempts=result.attempts,
                        elapsed_ms=result.elapsed_ms,
                    )
                )
                if result.status is SourceRunStatus.OK and result.hits:
                    hits = [
                        normalize_hit(raw_hit, source_id=task.source_id, retrieved_at=retrieved_at)
                        for raw_hit in result.hits
                    ]
                    per_source_lists.append(deduplicate_hits(hits))

        concurrent.futures.wait(all_futures)

        ranked = rank_hits(
            per_source_lists,
            freshness_required=request.date_range is not None,
            now=retrieved_at,
        )
        overall = _overall_status(outcomes, len(ranked.hits))
        snapshot = SearchSnapshot(
            ranked_hits=ranked.hits,
            per_source=outcomes,
            ordering_reason=ranked.reason,
        )
        if self._cache is not None and overall is not OverallStatus.DEPENDENCY_UNAVAILABLE:
            self._cache.put(key, snapshot)
        session_key = (owner_id, workspace_id)
        self._sessions[session_key] = {h.citation_id: h for h in ranked.hits}
        page, next_cursor = self._paginate(
            ranked.hits, request, fingerprint, owner_id, workspace_id, offset
        )
        return SearchResponse(
            request_id=self._new_request_id(),
            status=overall,
            hits=page,
            per_source=outcomes,
            ordering_reason=ranked.reason,
            empty_reason=(
                "所有已授权来源均已应答：未检索到相关内容（与超时/失败不同）"
                if overall is OverallStatus.EMPTY
                else None
            ),
            next_cursor=next_cursor,
            cache_state="miss",
            total_deadline_seconds=plan.total_deadline_seconds,
            per_source_deadline_seconds=plan.per_source_deadline_seconds,
        )

    # ---- 引用取回 ------------------------------------------------------

    def fetch(
        self,
        citation_id: str,
        *,
        owner_id: str,
        workspace_id: str = "",
        fetcher: Callable[[str], str] | None = None,
        guard: Callable[[str], str | None] | None = None,
    ) -> FetchedReference:
        """取回本次（该主体最近一次）搜索授权命中的引用。

        结构性边界：本方法只收 citation_id，不收 URL——"不接任意服务
        URL"由签名保证；SSRF 由既有护栏在取回前强制执行。
        """
        context = self._sessions.get((owner_id, workspace_id))
        if not context:
            raise ReferenceNotAuthorizedError("该主体尚无本次授权命中集合：先搜索再取引用")
        return fetch_reference(
            citation_id,
            context=context,
            fetcher=fetcher or self._fetcher
            or (lambda _url: (_ for _ in ()).throw(SearchServiceError("未配置 fetcher"))),
            guard=guard or self._guard,
        )

    # ---- 内部 ----------------------------------------------------------

    def _collect(
        self,
        task: SourceTask,
        future: concurrent.futures.Future[ProviderCallResult],
        plan: SearchPlan,
    ) -> ProviderCallResult:
        """等待单源结果：预算=min(单源 6s, 总 12s 剩余)；超时→TIMEOUT。"""
        remaining_total = plan.total_deadline_seconds - (self._clock() - plan.started_at)
        budget = max(0.001, min(task.budget_seconds, remaining_total))
        try:
            return future.result(timeout=budget)
        except concurrent.futures.TimeoutError:
            return ProviderCallResult(
                source_id=task.source_id,
                hits=[],
                status=SourceRunStatus.TIMEOUT,
                attempts=1,
                detail=f"单源预算耗尽（{budget:.3f}s）",
            )
        except Exception as exc:  # noqa: BLE001 —— 编排层兜底，不外泄内部异常
            return ProviderCallResult(
                source_id=task.source_id,
                hits=[],
                status=SourceRunStatus.FAILED,
                attempts=1,
                detail=f"编排层异常：{type(exc).__name__}",
            )

    def _paginate(
        self,
        ranked: Sequence[SearchHit],
        request: SearchRequest,
        fingerprint: str,
        owner_id: str,
        workspace_id: str,
        offset: int,
    ) -> tuple[list[SearchHit], str | None]:
        page = list(ranked[offset : offset + request.limit])
        end = offset + len(page)
        next_cursor: str | None = None
        if page and end < len(ranked):
            next_cursor = issue_cursor(
                owner_id=owner_id,
                workspace_id=workspace_id,
                fingerprint=fingerprint,
                offset=end,
            )
        return page, next_cursor

    @staticmethod
    def _new_request_id() -> str:
        return f"sreq_{uuid.uuid4().hex[:12]}"


# ===========================================================================
# 本地知识命中的身份呈现 + 跨源先后单一判据
# （2026-09-25 S-T-ACG-1：用户第 3 项后半「库里已有的内容要稳定命中，
#  并且把检索到的信息准确无误反馈给用户」的机器形态）
# ===========================================================================
#
# 本段解决的三件事，各只有**一处**真身：
# ① 命中可核对：每条送进提示词的知识块都带「来源库 + 条目标题 + 条目 id」，
#    正文缺块/被裁剪必须显式说出来——「准确无误」的可机检定义就是
#    「给出的每一句都能追到一条命中，且看不全时说看不全」。
# ② 零命中只说「本轮没检索到」：措辞真身**不在这里**（见
#    ``validate_miss_declaration`` 的文档串），本模块只执法"两半俱全"，
#    绝不另写第二套话术。
# ③ 哪个库先答、何时降级到网络：唯一一份阶梯 ``ANSWER_SOURCE_LADDER_*``
#    与唯一一个判据函数 ``resolve_answer_order``；「要不要联网」的阈值判据
#    仍住在既有真身 ``question_intent.decide_web_search``（本段只**消费**
#    它算好的布尔值，绝不重算一遍阈值）。
#
# 分层：本段是纯函数 + 严格 DTO，零网络、零 LLM、零配置读取；调用点（chat
# 层渲染与装配层的检索器顺序）在禁写面内，坐标见本席报告的「需要主代理代接」。

#: 本地向量库源名——与装配层既有 bindings 同名（``providers.py`` 的
#: ``MergedKnowledgeRetriever`` 传入序、``knowledge_service`` 的 binding 名），
#: 这里只是把它们变成可声明、可排序的常量，不新建第二套命名。
KB_SOURCE_PERSONA = "persona"
KB_SOURCE_WIKI = "kb_wiki"

#: 「哪个库先答」的唯一声明表：背景档（角色/剧情/设定/人事物）。
#: 本地库先答——库里已有的内容不该被一条随手抓来的网页盖过去。
ANSWER_SOURCE_LADDER_BACKGROUND: tuple[str, ...] = (
    KB_SOURCE_PERSONA,
    KB_SOURCE_WIKI,
    "moegirl",
    "bangumi",
    "bilibili",
    "general",
)

#: 同一批源，时效档（最新动态/卡池/更新到第几集）：本地库退到"背景参考"位。
#: 库里的设定不会写着昨天发生了什么，让本地库先答会稳定地产出过期答案。
ANSWER_SOURCE_LADDER_LATEST: tuple[str, ...] = (
    "bilibili",
    "moegirl",
    "bangumi",
    "general",
    KB_SOURCE_WIKI,
    KB_SOURCE_PERSONA,
)

#: 只含本地知识库的档位集合（判「降级到网络」与「本地是否答上了」用）。
LOCAL_KB_SOURCE_IDS: frozenset[str] = frozenset({KB_SOURCE_PERSONA, KB_SOURCE_WIKI})

#: 背景档「竖源 vs 通用网页」权威度加权表——从本波起只有这一份。
#: ``acg_search`` 的融合权重由它派生（旧实现是竖源模块里另一张字面量表，
#: 与本表同义不同身，改一处必漏一处）。数值沿用落地前实况，零行为变更。
BACKGROUND_AUTHORITY_WEIGHTS: dict[str, float] = {
    "moegirl": 1.2,
    "bangumi": 1.1,
    "bilibili": 1.0,
    "general": 1.0,
}

#: 来源库的中文显示名（进提示词用；键与 ladder 同源，不另立枚举）。
_SOURCE_LIBRARY_LABELS: dict[str, str] = {
    KB_SOURCE_PERSONA: "人格资料库",
    KB_SOURCE_WIKI: "百科知识库",
    "moegirl": "萌娘百科",
    "bangumi": "Bangumi",
    "bilibili": "B站",
    "general": "通用网页",
}


def source_library_label(source_id: str) -> str:
    """来源库显示名；不认识的名字原样返回（绝不编一个中文名）。"""
    sid = str(source_id or "").strip()
    return _SOURCE_LIBRARY_LABELS.get(sid, sid)


def chunk_source_library(chunk: object) -> str:
    """一条知识块**属于哪座库**的唯一读点（合并点在装配时按路标注）。

    页级 ``source_id``（``明日方舟/prts_arknights/正文/…__94671``）不是库名：
    它长度可超 ``KnowledgeHitView.library`` 的 64 字符上限（生产已因此炸过
    ``ValidationError``），且永远对不上「谁先答」阶梯 ⇒ 拿它当库名判"本地命中"
    会让阶梯**结构上恒假**、每轮无谓降级联网。

    没标注（单路腿/假块/旧契约）一律交回空串，由调用方决定降级形态——
    **这里不猜前缀、不兜底造一个库名**。
    """
    declared = str(getattr(chunk, "source_library", "") or "").strip()
    return declared if declared in LOCAL_KB_SOURCE_IDS else ""


def answer_source_rank(source_id: str, *, wants_latest: bool) -> int:
    """某个来源在「谁先答」阶梯上的位置；未登记的源一律排最后（同权）。

    **本函数是全仓唯一的跨源先后判据**。任何"要不要把 A 排在 B 前"的新需求
    都必须改这张阶梯，不得在调用方另写 if——测试件里有 grep/AST 锁在看着。
    """
    ladder = (
        ANSWER_SOURCE_LADDER_LATEST if wants_latest else ANSWER_SOURCE_LADDER_BACKGROUND
    )
    sid = str(source_id or "").strip()
    try:
        return ladder.index(sid)
    except ValueError:
        return len(ladder)


def order_answer_sources(
    source_ids: Iterable[str], *, wants_latest: bool
) -> tuple[str, ...]:
    """按单一阶梯给来源排序（稳定：同秩保持传入序，重复只留第一次）。"""
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in source_ids:
        sid = str(raw or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        ordered.append(sid)
    return tuple(sorted(ordered, key=lambda sid: answer_source_rank(sid, wants_latest=wants_latest)))


def ordered_retriever_legs(
    retrievers: Sequence[tuple[str, object]], *, wants_latest: bool
) -> list[tuple[str, object]]:
    """把「(库名, 检索器)」按阶梯排成**成对**的腿（装配层用的那一形态）。

    存在意义与 ``order_retrievers`` 同一条：装配层不再靠"手写传参的先后"表达
    优先级。之所以要成对返回，是因为 ``MergedKnowledgeRetriever`` 的 ``libraries``
    必须与 ``retrievers`` **逐位对齐**——只排检索器不排库名就会标错来源库，
    而标错来源库等于把「谁先答」判错（``chunk_source_library`` 是本地命中的唯一依据）。
    """
    return sorted(
        ((str(name or "").strip(), retriever) for name, retriever in retrievers),
        key=lambda item: answer_source_rank(item[0], wants_latest=wants_latest),
    )


def order_retrievers(
    retrievers: Sequence[tuple[str, object]], *, wants_latest: bool
) -> list[object]:
    """把「(源名, 检索器)」按阶梯排成检索器列表。

    存在的意义只有一个：让装配层（``providers.py`` 构造
    ``MergedKnowledgeRetriever`` 的地方）不再靠"手写参数的先后"表达优先级
    ——先后由判据算出来，改阶梯即处处跟随，不会出现两处的顺序各说各话。
    """
    return [retriever for _, retriever in ordered_retriever_legs(
        retrievers, wants_latest=wants_latest
    )]


@dataclass(frozen=True)
class AnswerOrder:
    """一次「谁先答」的判定结果（纯数据，不含任何执行权）。"""

    ordered: tuple[str, ...]
    degrade_to_web: bool
    reason: str

    @property
    def first_answer_source(self) -> str:
        """第一优先应答源；一个都没命中时是空串（调用方须如实说没检索到）。"""
        return self.ordered[0] if self.ordered else ""

    @property
    def local_answered(self) -> bool:
        """本地知识库是否至少命中一条（与"够不够好"无关，那是置信度的活）。"""
        return any(source in LOCAL_KB_SOURCE_IDS for source in self.ordered)


def resolve_answer_order(
    *,
    hits_by_source: Mapping[str, int],
    wants_latest: bool,
    web_search_intended: bool,
) -> AnswerOrder:
    """跨源先后的**唯一**入口：谁先答 + 要不要降级到网络检索。

    参数口径（每条都刻意不做的事，写在这里防后来者"顺手加一套"）：
    - ``hits_by_source``：各源命中条数。条数 ≤0 的源不进阶梯（不占位）。
    - ``wants_latest``：时效档旗标，来自既有真身
      ``search_intent.AcgIntent.wants_latest``，本函数不重新判意图。
    - ``web_search_intended``：**调用方已经问过的** ``decide_web_search`` 结果。
      阈值/置信度/硬底线那套判据唯一住在
      ``domains/chat_reply/runtime/question_intent.py``，这里绝不重算——
      否则就是"两个函数各写一套 if"，正是本判据要消灭的东西。

    降级规则只有一条新东西：**本地一条都没命中 ⇒ 必须走网络**（在联网总闸
    允许的前提下）。这条与"本地有块但置信度低"是两回事，后者不归本函数管。
    """
    counted: dict[str, int] = {}
    for raw_id, count in (hits_by_source or {}).items():
        sid = str(raw_id or "").strip()
        if not sid:
            continue
        try:
            hits = int(count)
        except (TypeError, ValueError):
            hits = 0
        if hits > 0:
            counted[sid] = hits
    ordered = order_answer_sources(counted.keys(), wants_latest=wants_latest)
    order = AnswerOrder(
        ordered=ordered,
        degrade_to_web=False,
        reason="no_hits" if not ordered else "local_hit_first",
    )
    local_hit = any(sid in LOCAL_KB_SOURCE_IDS for sid in ordered)
    if bool(web_search_intended):
        return AnswerOrder(
            ordered=ordered,
            degrade_to_web=True,
            reason="web_intended" if local_hit else "web_intended_no_local_hit",
        )
    if not local_hit:
        return AnswerOrder(
            ordered=ordered,
            degrade_to_web=True,
            reason="no_local_hit" if ordered else "no_hits",
        )
    return order


def knowledge_chunks_by_source(chunks: Sequence[object]) -> dict[str, int]:
    """命中条数按**库名**聚合（``resolve_answer_order`` 入参形态的唯一构造处）。

    只认合并点标注的库名（``chunk_source_library``），没标注的一律不计——
    计进去就会造出一个阶梯上不存在的假库名，把「本地是否命中」判成假。
    """
    counted: dict[str, int] = {}
    for chunk in chunks or ():
        library = chunk_source_library(chunk)
        if not library:
            continue
        counted[library] = counted.get(library, 0) + 1
    return counted


_ChunkT = TypeVar("_ChunkT")


def reorder_knowledge_chunks(
    chunks: Sequence[_ChunkT], *, wants_latest: bool
) -> list[_ChunkT]:
    """每轮把已取回的知识块按「谁先答」阶梯**重排**（T3 的接线点）。

    元素类型用 TypeVar 透传：本函数只改顺序、不造新块，所以调用方拿回的仍是它
    交进来的那种块（`providers.py` 那边是 `KnowledgeChunk`，写成 ``object`` 会逼
    调用方 cast 一次、并把真类型信息丢掉）。

    为什么在取回之后重排、而不是在装配时排好就完事：装配时只知道有哪些库，
    不知道**这一轮**哪座库真的命中了几条。阶梯的语义正是"按本轮命中情况决定谁先答"，
    所以判据必须在有 ``hits_by_source`` 的地方跑一次——这就是 ``resolve_answer_order``。

    块序 = 按 ``resolve_answer_order(...).ordered`` 给出的库序做**轮询交错**
    （取完各家第一条再取第二条），而不是"整座库连排"：交错是合并检索器既有的
    交付形态，它保证提示词被裁剪时两座库都还在；本函数只改**谁先被取**这一维，
    不改"每座库各得若干条"这一维。没标注库名的块排在最后且保持原相对序
    （全是未标注时＝原样返回，行为与改前逐字节一致）。

    ``web_search_intended`` 在这里不参与：本函数只消费 ``.ordered``，
    降级联网与否由 chat 层那条既有判据决定（同一次 ``resolve_answer_order``
    的另一个字段），两块各读各的，不留第二套 if。
    """
    items = list(chunks or ())
    if len(items) < 2:
        return items
    order = resolve_answer_order(
        hits_by_source=knowledge_chunks_by_source(items),
        wants_latest=bool(wants_latest),
        web_search_intended=False,
    )
    groups: dict[str, list[_ChunkT]] = {}
    for chunk in items:
        groups.setdefault(chunk_source_library(chunk) or "", []).append(chunk)
    keys = [library for library in order.ordered if groups.get(library)]
    if "" in groups:
        keys.append("")
    if len(keys) < 2:
        return items
    reordered: list[_ChunkT] = []
    index = 0
    while len(reordered) < len(items):
        progressed = False
        for key in keys:
            stream = groups[key]
            if index >= len(stream):
                continue
            reordered.append(stream[index])
            progressed = True
        if not progressed:
            break
        index += 1
    return reordered


# ---------------------------------------------------------------------------
# ① 命中身份：知识块 → 可核对的提示词行
# ---------------------------------------------------------------------------

#: 单条正文的默认上限（字符）。旧实现是 300 且**静默**截断到残句；
#: 本表放宽到 520 并要求裁剪必须显式标注（见 ``_clip_body``）。
KNOWLEDGE_HIT_MAX_CHARS = 520

#: 正文裁剪时优先落点的句子终止符（含中文全角）。
_SENTENCE_ENDINGS: tuple[str, ...] = ("。", "！", "？", "；", "\n", ". ", "! ", "? ", "; ")

#: 表格分隔行（|---|:--:|）与"只剩骨架"的行（|、--、: 组成）——只有这类行
#: 允许整行丢弃，数据行不丢。
_MD_SKELETON_ONLY_RE = re.compile(r"^[\s|:-]*$")
_MD_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_HEADER_RE = re.compile(r"^#{1,6}\s*")
_WHITESPACE_RE = re.compile(r"\s+")

#: 引用/禁式检测用的引号跨度：被「」『』"" 包住的内容是**被引述的话**，
#: 不是本 bot 自己的断言（未命中声明里"不要说「记录里没有这个人」"正属此类）。
_QUOTED_SPAN_RE = re.compile(r"「[^」]{0,80}」|『[^』]{0,80}』|“[^”]{0,80}”")

#: 「把没查到说成不存在」型存在性断言：**唯一登记表**，元素是 ``(字面形态, 改写后的检索状态)``。
#: 探测器正则由本表现算拼出来（不再手写第二份词表），判据与改写因此天然同源：
#: 凡是判得出来的句子，必定有对应的改写项——加了形态却忘了配改写，这里当场失配，
#: 而不是上线后悄悄走兜底（规则 10：一张名单抄两处必漂）。
#: 检测口径与用户已批准的禁式同源（chat 层 ``_RUNTIME_CONTEXT_USAGE`` 与本模块的未命中
#: 声明执法同一族词），本表只用于**判别与改写**，不用于生成任何话术。
#: ⚠ 登记顺序＝正则的匹配优先级：长的必须排在它的前缀之前（"没有这个人物"先于"没有这个人"）。
_EXISTENCE_DENIAL_FORMS: tuple[tuple[str, str], ...] = (
    ("不存在", "我没能核实"),
    ("并未存在", "我没能核实"),
    ("查无此人", "我没能确认这个人"),
    ("没有这个角色", "我这轮没查到这个角色"),
    ("没有这个人物", "我这轮没查到这个人物"),
    ("没有这个人", "我这轮没查到这个人"),
    ("没有这个作品", "我这轮没查到这个作品"),
    ("没有这个设定", "我这轮没查到这个设定"),
    ("没有这个词条", "我这轮没查到这个词条"),
    ("没有这个条目", "我这轮没查到这个条目"),
    ("没有这个剧情", "我这轮没查到这段剧情"),
    ("没有这段剧情", "我这轮没查到这段剧情"),
    ("记录里没有", "记录里我没查到"),
    ("资料里没有", "资料里我没查到"),
    ("库里没有", "我这轮没查到相关条目"),
    ("从未有过", "我没查到有过"),
    ("官方从未公布", "官方有没有公布过这一点我没能核实"),
    ("官方没有公布", "官方有没有公布过这一点我没能核实"),
    ("官方没公布", "官方有没有公布过这一点我没能核实"),
)

_EXISTENCE_DENIAL_RE = re.compile(
    "|".join(re.escape(form) for form, _hedge in _EXISTENCE_DENIAL_FORMS)
)

#: 否认/禁说标记与它的可视窗口：命中词左侧出现这些连接词时，那句话是
#: **"不代表它不存在"**（对否定的否认），不是否定本身。窗口取 24 字覆盖
#: "不代表你问的人、作品、设定或事件不存在" 这类带列举的句式。
_DISCLAIM_CUES: tuple[str, ...] = (
    "不代表",
    "不等于",
    "并不意味着",
    "不能说明",
    "不是",
    "不要说",
    "别说",
    "不该说",
    "不要",
    "禁止",
    "切勿",
)
_DISCLAIM_WINDOW = 24


class KnowledgeMissDeclarationError(ValueError):
    """未命中声明缺半边（装配期程序错，不是运行时用户错）。"""


def _denial_scan_geometry(text: str) -> tuple[str, list[int]]:
    """``_QUOTED_SPAN_RE.sub(" ", …)`` 的同一次扫描，但保留**原文坐标**映射。

    执法面（``existence_denial_hit``）与改写面（``rewrite_existence_denials``）
    必须用同一份豁免几何：两处各算一次"这句话算不算被引述过"，迟早会判出
    两种结果——那正是本模块要消灭的"两个函数各写一套 if"。
    """
    chars: list[str] = []
    origin: list[int] = []
    cursor = 0
    for span in _QUOTED_SPAN_RE.finditer(text):
        for index in range(cursor, span.start()):
            chars.append(text[index])
            origin.append(index)
        chars.append(" ")
        origin.append(span.start())
        cursor = span.end()
    for index in range(cursor, len(text)):
        chars.append(text[index])
        origin.append(index)
    return "".join(chars), origin


def iter_existence_denials(text: object) -> list[tuple[int, int, str]]:
    """原文里每一处**真正的**存在性否定：``(起, 止, 命中文本)``。

    两重豁免与 ``existence_denial_hit`` 逐字同源（引述跨度 + 左侧否认连接词），
    所以"被禁的句子"与"只是禁止说某句"永远由同一把尺分开。
    """
    original = str(text or "")
    if not original:
        return []
    stripped, origin = _denial_scan_geometry(original)
    hits: list[tuple[int, int, str]] = []
    for match in _EXISTENCE_DENIAL_RE.finditer(stripped):
        left = stripped[max(0, match.start() - _DISCLAIM_WINDOW) : match.start()]
        if any(cue in left for cue in _DISCLAIM_CUES):
            continue
        hits.append((origin[match.start()], origin[match.end() - 1] + 1, match.group(0)))
    return hits


def existence_denial_hit(text: object) -> str:
    """返回文本里第一处「存在性否定」断言（先剥掉被引述的跨度）。

    用途是**执法**：未命中块必须不含它——否则"本轮没检索到"会被模型（或被
    后来改文案的人）写成"这件事不存在"，正是她点名的那类错误。

    两个必要的豁免（都不是放宽，是把"否定"与"对否定的否认"分开）：
    - 被 「」『』"" 引述的内容（"不要说「记录里没有这个人」"是在**禁**这句）；
    - 命中词左侧一小段里带否认/禁止连接词的（"不代表你问的作品不存在"）。
    """
    hits = iter_existence_denials(text)
    return hits[0][2] if hits else ""


#: 出口执法的改写表（T4②，2026-09-28）：把"不存在"讲回"我这轮没查到"。
#: 键从 ``_EXISTENCE_DENIAL_FORMS`` 现取（同源，不另立词表）；值一律是**第一人称的
#: 检索状态**，绝不换成另一句存在性断言（那只是换个方向编）。
#: ⚠ 这里刻意不出现"没接到"+"不代表"两句同现——那是未命中声明单真身锁的判定特征。
_MISS_HEDGE_BY_DENIAL: dict[str, str] = dict(_EXISTENCE_DENIAL_FORMS)
#: 词表万一被扩了却没配上改写，兜底只说一句最保守的检索状态，**不改写成另一句断言**。
_MISS_HEDGE_FALLBACK = "我这轮没查到能证实这一点的资料"


def rewrite_existence_denials(text: object) -> tuple[str, str]:
    """出口执法：把"没查到"被讲成"不存在"的地方改成不确定表述。

    返回 ``(改写后的文本, 第一处命中的原话)``；没有命中时**原样返回**且第二项为空串
    ——调用方据此判"这轮到底动没动过"，护栏锁（正常回复一字不动）就锁在这里。

    本函数**只管改写**：什么时候允许改（＝本轮确实零命中）是调用点的红线，
    留在 chat 层的出站缝，因为"有没有资料"是那一层才知道的事实。
    引述与否认豁免与执法面同源（``iter_existence_denials``），所以
    "不要说「记录里没有这个人」"这类禁句不会被改坏。
    """
    original = str(text or "")
    hits = iter_existence_denials(original)
    if not hits:
        return original, ""
    pieces: list[str] = []
    cursor = 0
    for start, end, matched in hits:
        if start < cursor:  # 理论不可达（正则不重叠），仍按最小安全动作跳过
            continue
        pieces.append(original[cursor:start])
        pieces.append(_MISS_HEDGE_BY_DENIAL.get(matched, _MISS_HEDGE_FALLBACK))
        cursor = end
    pieces.append(original[cursor:])
    return "".join(pieces), hits[0][2]


#: 未命中声明必须自带的两半：①"本轮没有资料接入"的事实陈述；
#: ② 明确否认"没资料 ⇒ 不存在"的连接句。缺一半即判不合格。
_MISS_STATEMENT_ANCHORS: tuple[str, ...] = (
    "没接到",
    "没检索",
    "没查到",
    "未能核实",
    "没有命中",
    "零命中",
    "未启用",
    "本轮没有",
)
_MISS_DISCLAIM_CONNECTIVES: tuple[str, ...] = ("不代表", "不等于", "并不意味着", "不能说明", "不是")


def validate_miss_declaration(declaration: object) -> str:
    """校验调用方交来的未命中声明是否"两半俱全"，合格则**原样**返回。

    措辞真身不在本模块——它是 chat 层 ``_KB_UNAVAILABLE_LINE``（2026-09-25
    事故驱动的既有件，与已批准的禁式同口径）。这里只执法结构：
    - 必须出现"本轮没接到/没检索到"这一半；
    - 必须出现"不代表/不等于……"这一半（把没查到与不存在切开）。
    任何一半缺失都抛 ``KnowledgeMissDeclarationError``：宁可装配期红，
    也不要上线后悄悄把「没查到」讲成「没有这个人」。
    """
    text = str(declaration or "").strip()
    if not text:
        raise KnowledgeMissDeclarationError("未命中声明为空：零命中必须显式说出来，不许静默缺块")
    if not any(anchor in text for anchor in _MISS_STATEMENT_ANCHORS):
        raise KnowledgeMissDeclarationError("未命中声明缺『本轮没有资料接入』这一半")
    if not any(conn in text for conn in _MISS_DISCLAIM_CONNECTIVES):
        raise KnowledgeMissDeclarationError("未命中声明缺『不代表不存在』那一半（否则等于换句否定）")
    if existence_denial_hit(text):
        raise KnowledgeMissDeclarationError(
            f"未命中声明自含存在性否定断言：{existence_denial_hit(text)!r}"
        )
    return text


class KnowledgeHitView(_StrictModel):
    """一条知识命中的最小可核对身份（呈现层，不改检索契约）。

    ``id_derived=True`` 表示这条命中没带库内 id，本模块按正文摘要现算了一枚
    ——**摘要 id 只能核对内容，不能回查库表**，所以呈现时用 ``id≈`` 而不是
    ``id=``，让下游与人都看得出这枚 id 的来历。
    """

    library: str = Field(min_length=1, max_length=64)
    chunk_id: str = Field(min_length=1, max_length=256)
    source_id: str = Field(default="", max_length=256)
    title: str = Field(default="", max_length=256)
    content: str = ""
    id_derived: bool = False


def knowledge_hit_view(*, library: str, chunk: object) -> KnowledgeHitView:
    """把一个检索块（duck-typed ``KnowledgeChunk``）收成带身份的视图。

    刻意不做 pydantic 强转：装配层递来的块可能来自不同契约代际（本仓已有
    两个同名 ``WebSearchHit`` 的前车），这里只按字段名取值，缺什么就如实
    标什么，绝不拿标题冒充 id、也绝不因为缺 id 就把整条丢掉。
    """
    lib = str(library or "").strip()
    if not lib:
        raise ValueError("知识命中必须点名来源库（persona/kb_wiki/…），否则无法核对")
    chunk_id = str(getattr(chunk, "chunk_id", "") or "").strip()
    derived = not chunk_id
    if derived:
        body = str(getattr(chunk, "content", "") or "")
        chunk_id = f"digest:{hashlib.sha256(body.encode('utf-8')).hexdigest()[:12]}"
    return KnowledgeHitView(
        library=lib,
        chunk_id=chunk_id,
        source_id=str(getattr(chunk, "source_id", "") or "").strip(),
        title=str(getattr(chunk, "title", "") or "").strip(),
        content=str(getattr(chunk, "content", "") or ""),
        id_derived=derived,
    )


def _identity_parts(hit: KnowledgeHitView) -> tuple[str, str, str]:
    """一条命中的三段身份（库名 / 标题 / 条目号）——**只在这里拼一次**。

    ``id≈`` 与 ``id=`` 的区别必须一路带到提示词里：前者是本模块现算的内容
    摘要（能核对"是不是这段文字"），后者才是库里那条记录的可回查主键。
    """
    label = source_library_label(hit.library)
    title = hit.title or hit.source_id or "(无标题条目)"
    id_part = f"id≈{hit.chunk_id}" if hit.id_derived else f"id={hit.chunk_id}"
    return label, title, id_part


def format_knowledge_citation(hit: KnowledgeHitView) -> str:
    """一条命中的可核对身份串：``库 人格资料库 · 标题 · id=xxx``（引用面用）。"""
    label, title, id_part = _identity_parts(hit)
    return f"库 {label} · {title} · {id_part}"


def _shape_knowledge_body(text: object) -> str:
    """正文整形：**保结构、不丢内容**。

    与旧实现（chat 层 ``_clean_knowledge_chunk``）的实质差别：旧实现把每一行
    ``|...|`` 表格行整行删掉——百科里角色属性/命座/发售表常常**全是**表格行，
    于是"命中了但正文被洗成空"，模型面对一条自己看不见内容的命中，最容易
    开始补全（=编）。这里改成：分隔线（|---|）仍丢，数据行折成 ``单元格｜单元格``。
    """
    kept: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line in {"---", "***", "___"}:
            continue
        if _MD_SKELETON_ONLY_RE.match(line):
            # 只剩 | : - 空白的行（分隔行、断掉的表格骨架）：确实无内容可留。
            continue
        if _MD_TABLE_ROW_RE.match(line):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            cells = [cell for cell in cells if cell and not _MD_SKELETON_ONLY_RE.match(cell)]
            if cells:
                kept.append("｜".join(cells))
            continue
        line = _MD_BOLD_RE.sub(r"\1", line)
        line = _MD_HEADER_RE.sub("", line)
        if line:
            kept.append(line)
    return _WHITESPACE_RE.sub(" ", " ".join(kept)).strip()


def _clip_body(body: str, budget: int) -> tuple[str, bool, int]:
    """裁剪到句子终止符，返回 ``(文本, 是否裁过, 未展示字数)``。

    地板取预算的 55%：找不到终止符才退回硬切——但**硬切也必须标注**，
    静默截断才是"把命中洗成残句"的根因。
    """
    if len(body) <= budget:
        return body, False, 0
    window = body[:budget]
    floor = int(budget * 0.55)
    cut = -1
    for token in _SENTENCE_ENDINGS:
        index = window.rfind(token)
        if index >= floor:
            cut = max(cut, index + len(token.rstrip()))
    if cut > 0:
        clipped = window[:cut].strip()
        return clipped, True, len(body) - len(clipped)
    return window.strip(), True, len(body) - len(window)


def format_knowledge_hit_lines(
    hits: Sequence[KnowledgeHitView],
    *,
    max_chars: int = KNOWLEDGE_HIT_MAX_CHARS,
    sanitizer: Callable[[str], str] | None = None,
) -> list[str]:
    """知识命中 → 提示词行（每行自带可核对身份，正文看不全就说看不全）。

    行形：``- [标题｜库 人格资料库｜id=chunk_id] 正文…（另有 N 字未展示，可回查该条目）``

    ``sanitizer`` 是调用方注入的消毒口（chat 层的
    ``_sanitize_untrusted_context_text`` 与注入行剥离留在原咽喉，本模块不
    复制一套正则）；未注入则原样呈现——安全面由调用点负责，这是刻意的分工，
    写清在这里免得后来者以为这里漏了。
    """
    budget = max(80, int(max_chars))
    lines: list[str] = []
    for hit in hits:
        label, title, id_part = _identity_parts(hit)
        identity = f"[{title}｜库 {label}｜{id_part}]"
        body = _shape_knowledge_body(hit.content)
        if not body:
            # 命中了却拿不出可读正文：显式说出来，绝不让模型对着空壳自由发挥。
            lines.append(f"- {identity} （条目已命中，但本轮取到的正文无可读文本，未展示内容）")
            continue
        clipped, truncated, hidden = _clip_body(body, budget)
        if sanitizer is not None:
            clipped = sanitizer(clipped)
        if truncated:
            lines.append(
                f"- {identity} {clipped}…（另有约 {hidden} 字未展示，可回查该条目）"
            )
        else:
            lines.append(f"- {identity} {clipped}")
    return lines


def knowledge_context_block(
    *,
    chunks: Sequence[object],
    library: str,
    miss_declaration: str,
    max_chars: int = KNOWLEDGE_HIT_MAX_CHARS,
    sanitizer: Callable[[str], str] | None = None,
) -> str:
    """【知识库】区的单一组装口：命中→带身份的行；零命中→既有未命中声明。

    ``library`` 为来源库名；一次调用只对应一路来源（多路由调用方合并后传，
    或按 ``order_retrievers`` 的先后逐路传入并各自保留身份）——本函数不猜库名。
    未命中时**原样**返回调用方交来的声明（先过两半校验），因此提示词里那句
    "本轮没检索到"的措辞真身仍然只有一处。
    """
    views = [
        knowledge_hit_view(library=library, chunk=chunk) for chunk in (chunks or ())
    ]
    if not views:
        text = validate_miss_declaration(miss_declaration)
        return text if sanitizer is None else sanitizer(text)
    lines = format_knowledge_hit_lines(views, max_chars=max_chars, sanitizer=sanitizer)
    return "\n".join(lines)
