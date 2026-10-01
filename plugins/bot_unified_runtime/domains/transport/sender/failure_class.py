"""发送失败的「可否安全重投」分类（TG 告警卡连接期修复波，2026-09-28）。

一句话判据：**只有确证「请求零字节出网、必然没到达对方服务器」的失败才算
可安全重投**；一切「请求可能已被对方处理」的形态（读超时、协议中途断、写
中途断、非 2xx 响应、bot 未就绪，以及任何分不出形状的异常）一律归
``uncertain``，维持台账 #47 M-63「九发零账」既有 UNKNOWN/停放语义——那条
红线是血泪账，本模块只准往里加保守判定，不许放宽。

为什么需要它（取证席 G 钉死的事实）：mixed 告警卡走原子整发，任何非「明确
拒绝」的失败都记 part=UNKNOWN，而生产 ``unknown_part_confirmer=None`` ⇒
UNKNOWN 永不重投 ⇒ 一次代理/网络瞬断＝请求永久丢弃、零重试。瞬断里最大一
类恰恰是**连接建立期失败**（代理拒连、DNS 解析失败），它零副作用、重投不
可能双发，却被同一把保守刀背砍死。本模块把这两类分开。

形态纪律：
- 纯函数、零网络、零配置读取、零副作用，可直接单测；
- 判定结果只随失败回执上抛（``OperationalIssue.retry_safety`` 新增字段），
  既有字段（``kind``/``safe_summary``/``retryable``）语义逐字节不动——
  ``kind`` 是 worker 判据与幂等去重逐字消费的承重串；
- 分类词是内部判据，不进会话文本；异常消息原文一个字符都不带上落库。
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable
from typing import Any

# ---- 三值口径（真身＝contracts OperationalIssue.retry_safety 的 Literal）----
#: 未分类＝既有语义逐字节不变（消费方绝不因缺标签而改变行为）。
RETRY_SAFETY_UNCLASSIFIED = ""
#: 连接建立期失败：TCP/代理/DNS 尚未把请求写出去 ⇒ 重投必不双发。
RETRY_SAFETY_CONNECT_PHASE = "connect_phase"
#: 结果不确定：请求可能已被对方服务器处理 ⇒ 维持 UNKNOWN/停放语义。
RETRY_SAFETY_UNCERTAIN = "uncertain"

RETRY_SAFETY_VALUES = frozenset(
    {RETRY_SAFETY_UNCLASSIFIED, RETRY_SAFETY_CONNECT_PHASE, RETRY_SAFETY_UNCERTAIN}
)

# 连接建立期类型名：只列「请求尚未写出」这一档，逐名核对过 httpx/httpcore
# 异常族谱（ConnectTimeout 只挂 TimeoutException、不挂 ConnectError；
# ProxyError 只挂 TransportError，故三型都得点名）。
_CONNECT_TYPE_NAMES = frozenset(
    {
        "ConnectError",
        "ConnectTimeout",
        "ProxyError",
        "ProxyConnectionError",
        "gaierror",
        "ConnectionRefusedError",
    }
)
# 真身类型（httpx 不可用时降级为空元组，仍按名判定）。
_CONNECT_TYPES: tuple[type[BaseException], ...] = (
    ConnectionRefusedError,
    socket.gaierror,
)
# 名判定允许的模块前缀：防业务侧同名类（如自造 ConnectError）把不确定失败
# 洗成可重投。网络栈之外的同名一律不算连接期证据。
_CONNECT_MODULE_PREFIXES = (
    "httpx",
    "httpcore",
    "h11",
    "anyio",
    "trio",
    "asyncio",
    "socket",
    "ssl",
    "urllib3",
    "aiohttp",
    "requests",
    "nonebot",
    "nonebot.adapters",
)
# 不确定族：请求已（或可能已）离开本机。刻意**不含** NetworkError /
# TransportError / HTTPError / OSError 这类宽口径基名——它们是
# httpx.ConnectError 自己的父链，列进来会把可安全重投误降为停放。
_UNCERTAIN_TYPE_NAMES = frozenset(
    {
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "ReadError",
        "WriteError",
        "RemoteProtocolError",
        "LocalProtocolError",
        "ProtocolError",
        "HTTPStatusError",
        "TimeoutError",
        "CancelledError",
        "ClosedResourceError",
        "BrokenResourceError",
        "EndOfStream",
        "ConnectionResetError",
        "ConnectionAbortedError",
        "IncompleteReadError",
        "SSLError",
        "SSLCertVerificationError",
        "SSLEOFError",
        "ActionFailed",
        "ApiNotAvailable",
    }
)
# DNS 解析失败的文本形态（仅英文侧；真身优先按类型判定，文本只兜底）。
_DNS_MESSAGE_MARKERS = (
    "getaddrinfo failed",
    "name or service not known",
    "nodename nor servname",
    "no such host",
    "failed to establish a new connection",
    "unable to connect to proxy",
)

_CONNECT_PHASE_RETRY_DELAY_SECONDS = 30.0

try:  # pragma: no cover - httpx 是硬依赖，缺装时走名判定降级路径
    import httpx as _httpx

    _CONNECT_TYPES = (
        *_CONNECT_TYPES,
        _httpx.ConnectError,
        _httpx.ConnectTimeout,
        _httpx.ProxyError,
    )
except Exception as exc:  # noqa: BLE001 - 分类器不得因缺库而炸发送主链路
    # 降级留痕（静默 pass 会让「按类型判定」这条腿悄悄失效，只剩文本兜底）。
    logging.getLogger(__name__).debug(
        "httpx unavailable (%s); connect-phase detection degrades to type names",
        type(exc).__name__,
    )

_MAX_CAUSE_DEPTH = 8


def _matches_names(
    exc: BaseException, names: frozenset[str], *, require_network_module: bool
) -> bool:
    """按 MRO 名判定；连接期一族另要模块前缀背书（防同名洗白）。"""
    for klass in type(exc).__mro__:
        if klass.__name__ not in names:
            continue
        if not require_network_module:
            return True
        module = str(getattr(klass, "__module__", "") or "")
        if module.startswith(_CONNECT_MODULE_PREFIXES):
            return True
    return False


def _verdict_for(exc: BaseException) -> str | None:
    """单个异常的判定（不确定优先：同族里存疑就停投）。"""
    if isinstance(exc, _CONNECT_TYPES) and not isinstance(exc, TimeoutError):
        return RETRY_SAFETY_CONNECT_PHASE
    if _matches_names(exc, _UNCERTAIN_TYPE_NAMES, require_network_module=False):
        return RETRY_SAFETY_UNCERTAIN
    if _matches_names(exc, _CONNECT_TYPE_NAMES, require_network_module=True):
        return RETRY_SAFETY_CONNECT_PHASE
    message = str(exc).lower()
    if any(marker in message for marker in _DNS_MESSAGE_MARKERS):
        return RETRY_SAFETY_CONNECT_PHASE
    return None


def classify_send_failure(exc: BaseException | None) -> str:
    """失败异常 → 三值判定；``None``（未抛异常）返回 ``""``＝不表态。

    判定顺序＝先看最外层，再顺 ``__cause__``/``__context__`` 链下探（httpx
    的 ConnectError 常包着 socket.gaierror/ConnectionRefusedError，nonebot
    的 NetworkError 也按这条链取证）。链上仍分不出 ⇒ ``uncertain``：
    保守侧默认，绝不因「认不出来」而放行重投。
    """
    if exc is None:
        return RETRY_SAFETY_UNCLASSIFIED
    seen: set[int] = set()
    current: BaseException | None = exc
    depth = 0
    while current is not None and depth < _MAX_CAUSE_DEPTH and id(current) not in seen:
        seen.add(id(current))
        verdict = _verdict_for(current)
        if verdict:
            return verdict
        following = current.__cause__
        if following is None or id(following) in seen:
            following = current.__context__
        current = following if following is not None and id(following) not in seen else None
        depth += 1
    return RETRY_SAFETY_UNCERTAIN


def issue_retry_safety(issue: Any) -> str:
    """读取 ``OperationalIssue.retry_safety``；老夹具/替身缺字段 ⇒ ``""``。"""
    value = getattr(issue, "retry_safety", None)
    if isinstance(value, str) and value in RETRY_SAFETY_VALUES:
        return value
    return RETRY_SAFETY_UNCLASSIFIED


def is_connect_phase_failure(issue: Any) -> bool:
    """失败回执是否「连接建立期失败」（唯一可安全重投的那一档）。"""
    return issue_retry_safety(issue) == RETRY_SAFETY_CONNECT_PHASE


def with_retry_safety(issue: Any, exc: BaseException | None) -> Any:
    """把分类结果随失败回执上抛（model_copy，不改既有字段）。"""
    if issue is None:
        return issue
    verdict = classify_send_failure(exc)
    if verdict == RETRY_SAFETY_UNCLASSIFIED:
        return issue
    try:
        return issue.model_copy(update={"retry_safety": verdict})
    except Exception:  # noqa: BLE001 - 打标失败绝不反噬发送主链路
        return issue


# ---- 告警文本直发腿的一次补发（根装配 _deliver_admin_alert 消费）----------
# 直发腿不入队（无 part 账、无退避、无重投），一次瞬断就是一条永久丢失的
# 管理员告警。这里只对连接期失败**至多补发一次**：短退避、后台任务
# （off-loop sleep，不占用调用方 await 预算），补发再失败就维持现状
# success=False——绝不入队、绝不二次补发、绝不对不确定失败补（那是双发）。
_pending_retry_tasks: set[asyncio.Task[Any]] = set()


def _spawn_retry_task(coro: Awaitable[Any]) -> asyncio.Task[Any]:
    task: asyncio.Task[Any] = asyncio.create_task(coro)  # type: ignore[arg-type]
    _pending_retry_tasks.add(task)
    task.add_done_callback(_pending_retry_tasks.discard)
    return task


async def _resend_once(
    resend: Callable[[], Awaitable[Any]], send_request: Any
) -> None:
    logger = logging.getLogger(__name__)
    request_id = str(getattr(send_request, "request_id", "") or "")
    try:
        await asyncio.sleep(_CONNECT_PHASE_RETRY_DELAY_SECONDS)
        result = await resend()
    except Exception:  # noqa: BLE001 - 补发是旁路，任何失败只留痕
        logger.warning(
            "admin alert connect-phase resend raised request_id=%s", request_id
        )
        return
    state = str(getattr(result, "state", "") or "")
    if state and "sent" not in state.lower():
        logger.warning(
            "admin alert connect-phase resend not delivered request_id=%s state=%s",
            request_id,
            state,
        )


def schedule_connect_phase_resend(
    send_request: Any,
    receipt: Any,
    resend: Callable[[], Awaitable[Any]],
) -> bool:
    """连接期失败的直发告警文本 → 排一次后台补发；返回是否已排。

    非连接期（含未分类）⇒ 零副作用返回 False，调用方行为逐字节不变。
    """
    if not is_connect_phase_failure(getattr(receipt, "operational_issue", None)):
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        logging.getLogger(__name__).debug(
            "connect-phase retry skipped: no running loop request_id=%s",
            str(getattr(send_request, "request_id", "") or ""),
        )
        return False
    _spawn_retry_task(_resend_once(resend, send_request))
    return True
