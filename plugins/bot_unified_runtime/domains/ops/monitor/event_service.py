"""V2.1 S5 统一事件服务：best-effort 发布 + 提交即投递 + ASGI SSE 工厂（V21-SSE-001）。

合同来源：docs/design/backend-v2-implementation-guide.md §6 SSE 段 + §8：

- 「REST写、SSE读；持久化单调序号」：seq 由 EventStore 单调分配；
- 「先持久化后投递（提交=发布线性化点）」：写线程只在 store.append 的
  COMMIT 返回后才向订阅者广播；
- 「publish best-effort 不阻塞主链」：有界队列 + 丢弃计数，永不上抛、
  永不阻塞调用方（accepted=已入队，不等于已持久化）；
- 「Last-Event-ID、至少一次传递与客户端去重」：订阅先于回放建立，回放与
  实时缓冲的重叠段按 seq>已发送 去重；跨重连仍可能重复（至少一次），
  客户端必须按 event_id 幂等去重；
- 「历史回放衔接实时」「游标过期明确 resync，不静默丢失」：流内显式
  resync 事件（cursor_expired/slow_consumer/store_unavailable）；
- 「心跳 15s、有界缓冲、慢客户端断开并给重同步提示」：订阅缓冲
  ≤buffer_events 条且 ≤buffer_bytes 字节，超限→resync(slow_consumer)
  并结束流（客户端带 Last-Event-ID 重连）；
- 「凭据放请求头，不用 URL token；权限撤销后中断订阅」：auth 回调只看
  请求头；revocation 回调周期复查，False→unsubscribed 帧并断开。

模块结构：EventService（发布面）/ EventBroker+Subscription（投递面）/
event_stream（SSE 帧生成）/ create_event_stream_app（ASGI 兼容挂载）/
build_event_service（集成工厂）。

【集成点（本轮不接线，见 docs/design/v21-s5-events-log.md）】
1. control_plane/_app.py:321-342 —— lifespan 中 `RuntimeEventService(
   _path(events_path))` 换成 `build_event_service(events_path)`；
2. control_plane/api/events.py:build_event_router —— SSE 路由换挂
   `create_event_stream_app` 产物（或以 event_stream 重建 StreamingResponse）；
3. 能力/管线各出口 publish EventDraft（source 按出口选 §8 十二枚举）。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any
from urllib.parse import parse_qs

from plugins.bot_unified_runtime.domains.ops.monitor.event_store import (
    EVENT_CATEGORIES,
    EVENT_SEVERITIES,
    EVENT_SOURCES,
    CursorExpired,
    EventDraft,
    EventQuery,
    EventStore,
    EventStoreUnavailable,
    RuntimeEventV21,
    parse_cursor,
)

MAX_PAGE_LIMIT = 200  # §6 分页上限；SSE 单页取满以减少查询次数
DEFAULT_HEARTBEAT_SECONDS = 15.0  # §6：心跳 15s
DEFAULT_BUFFER_EVENTS = 128  # §6：每连接缓冲 ≤128 事件
DEFAULT_BUFFER_BYTES = 256 * 1024  # §6：且 ≤256KiB
DEFAULT_POLL_INTERVAL = 1.0  # P2 减量波 0.25→1.0：控制面 watcher 空闲轮询 4 倍降频（监控 UI 1s 延迟可接受）；要更密由调用方显式传 poll_interval
_STREAM_FILTERS = ("source", "category", "severity")

_RESYNC_HINTS = {
    "cursor_expired": "游标已超出保留窗口，已从最老可用事件重新回放；"
    "如需完整历史请显式重新订阅。",
    "slow_consumer": "消费速度低于事件产生速度，缓冲已超限断开；"
    "请带 Last-Event-ID 重连并按 event_id 去重。",
    "store_unavailable": "事件存储暂不可用，订阅终止；请稍后重连。",
    "cursor_reset": "游标超前于本事件库（可能库被重建），已从最老可用事件回放。",
}


class Subscription:
    """单连接有界投递缓冲：≤buffer_events 条且 ≤buffer_bytes 字节。

    offer 由写线程调用（永不阻塞，超限即溢出标记）；drain 由 SSE 生成器
    调用。溢出后不再接收新事件（后续一律计入 dropped_in_buffer），
    由 SSE 层显式 resync 并断开。
    """

    def __init__(self, broker: EventBroker, *, max_events: int, max_bytes: int) -> None:
        self._broker = broker
        self.max_events = max_events
        self.max_bytes = max_bytes
        self._items: deque[RuntimeEventV21] = deque()
        self._bytes = 0
        self._lock = threading.Lock()
        self.overflowed = False
        self.dropped_in_buffer = 0
        self.closed = False

    @property
    def buffered_bytes(self) -> int:
        with self._lock:
            return self._bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def offer(self, event: RuntimeEventV21) -> None:
        with self._lock:
            if self.closed:
                return
            if self.overflowed:
                self.dropped_in_buffer += 1
                return
            size = event.wire_bytes()
            if len(self._items) + 1 > self.max_events or self._bytes + size > self.max_bytes:
                self.overflowed = True
                self.dropped_in_buffer += 1
                return
            self._items.append(event)
            self._bytes += size

    def drain(self) -> list[RuntimeEventV21]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
            self._bytes = 0
            return items

    def close(self) -> None:
        with self._lock:
            self.closed = True
            self._items.clear()
            self._bytes = 0
        self._broker.unsubscribe(self)


class EventBroker:
    """进程内投递面：提交后事件的扇出注册表。无跨进程语义（单进程控制面）。"""

    def __init__(self, *, buffer_events: int = DEFAULT_BUFFER_EVENTS,
                 buffer_bytes: int = DEFAULT_BUFFER_BYTES) -> None:
        if not _valid_int(buffer_events, 1, 65536) or not _valid_int(buffer_bytes, 64, 64 * 1024 * 1024):
            raise ValueError("订阅缓冲边界非法")
        self.buffer_events = buffer_events
        self.buffer_bytes = buffer_bytes
        self._subscriptions: set[Subscription] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> Subscription:
        subscription = Subscription(
            self, max_events=self.buffer_events, max_bytes=self.buffer_bytes
        )
        with self._lock:
            self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            self._subscriptions.discard(subscription)

    def broadcast(self, event: RuntimeEventV21) -> None:
        # 写线程调用；offer 永不阻塞，扇出成本与订阅数线性、无 IO。
        with self._lock:
            snapshot = list(self._subscriptions)
        for subscription in snapshot:
            subscription.offer(event)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscriptions)


def _valid_int(value: Any, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


class EventService:
    """发布面：有界 MPSC 队列 + 单写线程，先持久化后投递。

    语义（与存量 control_plane RuntimeEventBus 同口径）：
    - publish 返回 True 仅表示「已入队」，不承诺持久化；
    - 队列满→dropped_count、生命周期争用→rejected_count、写失败→
      write_error_count，全部只计数不重试不阻塞；
    - close(timeout) 排空队列；返回 False 表示写线程仍在退出。
    """

    def __init__(
        self,
        store: EventStore,
        *,
        queue_capacity: int = 1024,
        buffer_events: int = DEFAULT_BUFFER_EVENTS,
        buffer_bytes: int = DEFAULT_BUFFER_BYTES,
    ) -> None:
        if not _valid_int(queue_capacity, 1, 65536):
            raise ValueError("queue_capacity 非法")
        self.store = store
        self.broker = EventBroker(buffer_events=buffer_events, buffer_bytes=buffer_bytes)
        self._queue: Queue[EventDraft] = Queue(maxsize=queue_capacity)
        self._lifecycle_lock = threading.Lock()
        self._counter_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._accepting = False
        self._writing = False
        self.dropped_count = 0
        self.rejected_count = 0
        self.written_count = 0
        self.write_error_count = 0

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._stop.is_set():
                raise RuntimeError("已关闭的事件服务不能重启")
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._write_loop, name="v21-event-writer", daemon=True
            )
            self._thread.start()
            self._accepting = True

    def publish(self, draft: EventDraft) -> bool:
        """best-effort 发布：True=已入队（不承诺持久化），False=被拒/丢弃。"""
        if not isinstance(draft, EventDraft):
            self._bump("rejected_count")
            return False
        if not self._lifecycle_lock.acquire(blocking=False):
            self._bump("rejected_count")
            return False
        try:
            if not self._accepting:
                self._bump("rejected_count")
                return False
            try:
                # 深拷贝脱离调用方可变 details，入队后再改不影响的已投递内容。
                self._queue.put_nowait(draft.model_copy(deep=True))
                return True
            except Full:
                self._bump("dropped_count")
                return False
        finally:
            self._lifecycle_lock.release()

    def flush(self, timeout: float = 5.0) -> bool:
        """等待队列清空且写线程不在写入中（测试与优雅关停用）。"""
        deadline = time.monotonic() + max(timeout, 0.0)
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0 and not self._writing:
                return True
            time.sleep(0.005)
        return False

    def close(self, timeout: float = 5.0) -> bool:
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
            raise TypeError("close 超时非法")
        if timeout < 0:
            raise ValueError("close 超时非法")
        with self._lifecycle_lock:
            self._accepting = False
            self._stop.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return not self.is_running

    def _bump(self, name: str) -> None:
        with self._counter_lock:
            setattr(self, name, getattr(self, name) + 1)

    def _write_loop(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                draft = self._queue.get(timeout=0.05)
            except Empty:
                continue
            self._writing = True
            try:
                # 提交=线性化点：append 返回（COMMIT 完成）才广播。
                event = self.store.append(draft)
                self.broker.broadcast(event)
                self._bump("written_count")
            except (
                EventStoreUnavailable,
                RuntimeError,
                sqlite3.Error,
                OSError,
                ValueError,
                TypeError,
            ):
                # best-effort：写失败只计数，不重试不阻塞主链（§8 拥塞可丢弃并计数）。
                self._bump("write_error_count")
            finally:
                self._writing = False
                self._queue.task_done()


# ---------------------------------------------------------------------------
# SSE 帧与流生成
# ---------------------------------------------------------------------------


def _event_frame(event: RuntimeEventV21) -> str:
    payload = json.dumps(
        event.to_wire(), ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    return f"id: {event.seq}\nevent: runtime_event\ndata: {payload}\n\n"


def _resync_frame(reason: str, *, oldest_seq: int | None = None,
                  dropped_events: int | None = None) -> str:
    data: dict[str, Any] = {"reason": reason, "hint": _RESYNC_HINTS[reason]}
    if oldest_seq is not None:
        data["oldest_seq"] = oldest_seq
    if dropped_events is not None:
        data["dropped_events"] = dropped_events
    # id 推进到重同步落点：即使连接随即断开，客户端 Last-Event-ID 也不会
    # 卡回已过期的游标上形成循环。
    prefix = f"id: {oldest_seq}\n" if oldest_seq is not None else ""
    return (
        prefix
        + "event: resync\ndata: "
        + json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        + "\n\n"
    )


def _unsubscribed_frame() -> str:
    return (
        "event: unsubscribed\ndata: "
        + json.dumps(
            {"reason": "permission_revoked", "hint": "权限已撤销，订阅中断。"},
            ensure_ascii=False,
        )
        + "\n\n"
    )


def _matches(
    event: RuntimeEventV21,
    filters: dict[str, str | None],
) -> bool:
    return all(
        value is None or getattr(event, name) == value
        for name, value in filters.items()
    )


async def event_stream(
    service: EventService,
    *,
    last_event_id: str | int | None = None,
    source: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = asyncio.sleep,
    keep_principal: Callable[[], bool] | None = None,
) -> AsyncIterator[str]:
    """SSE 帧生成器：历史回放无缝衔接实时；显式 resync；15s 心跳。

    可注入 clock/sleep 便于确定性测试（fake clock）；keep_principal 为
    权限撤销复查接口（False→unsubscribed 帧并结束）。

    Raises:
        ValueError: last_event_id 或过滤器形态非法（HTTP 层映射 422）。
    """
    cursor = parse_cursor(last_event_id)
    filters = {"source": source, "category": category, "severity": severity}
    enums = {
        "source": (source, EVENT_SOURCES),
        "category": (category, EVENT_CATEGORIES),
        "severity": (severity, EVENT_SEVERITIES),
    }
    for name, (value, allowed) in enums.items():
        if value is not None and value not in allowed:
            raise ValueError(f"{name} 非法")
    if not 0.01 <= float(heartbeat_seconds) <= 60.0:
        raise ValueError("heartbeat_seconds 非法")

    # 先订阅后回放：订阅时刻之后提交的事件必在缓冲或其后的查询里，
    # 回放与缓冲的重叠由 seq>已发送 去重——不丢、不重、无缝。
    subscription = service.broker.subscribe()
    sent: int | None = None
    last_output = clock()
    try:
        need_page = True
        while True:
            if need_page:
                try:
                    page = service.store.query(
                        EventQuery(
                            cursor=str(cursor) if cursor is not None else None,
                            limit=MAX_PAGE_LIMIT,
                            source=source,
                            category=category,
                            severity=severity,
                        )
                    )
                except CursorExpired as exc:
                    yield _resync_frame("cursor_expired", oldest_seq=exc.oldest_seq)
                    last_output = clock()
                    cursor = None  # 从最老可用处继续（显式 resync，不静默）
                    continue
                except EventStoreUnavailable:
                    yield _resync_frame("store_unavailable")
                    return
                except ValueError:
                    # cursor 超前于本库等查询侧非法 → 显式重置后继续。
                    yield _resync_frame("cursor_reset")
                    last_output = clock()
                    cursor = None
                    continue
                need_page = False

            for event in page.items:
                if sent is None or event.seq > sent:
                    if _matches(event, filters):
                        yield _event_frame(event)
                        last_output = clock()
                    sent = event.seq  # 不匹配的事件也推进游标

            if page.has_more:
                cursor = page.next_cursor
                need_page = True
                continue

            # 持久化历史已追平 → 排空实时缓冲（提交后广播的副本）。
            for event in subscription.drain():
                if sent is None or event.seq > sent:
                    if _matches(event, filters):
                        yield _event_frame(event)
                        last_output = clock()
                    sent = event.seq

            if subscription.overflowed:
                yield _resync_frame(
                    "slow_consumer",
                    dropped_events=subscription.dropped_in_buffer,
                )
                return
            if keep_principal is not None and not keep_principal():
                yield _unsubscribed_frame()
                return

            now = clock()
            if now - last_output >= heartbeat_seconds:
                yield ": heartbeat\n\n"
                last_output = now
            else:
                await sleep(min(poll_interval, heartbeat_seconds / 4.0))
            # 从已发送处继续补查：覆盖「提交在查询与缓冲排空之间」的竞态。
            if sent is not None:
                cursor = sent
            need_page = True
    finally:
        subscription.close()


# ---------------------------------------------------------------------------
# ASGI 兼容挂载
# ---------------------------------------------------------------------------


async def _send_json(send: Callable[..., Any], status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def create_event_stream_app(
    service: EventService,
    *,
    auth: Callable[..., Any] | None = None,
    revocation: Callable[[Any], bool] | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> Callable[[dict[str, Any], Callable[..., Any], Callable[..., Any]], Any]:
    """ASGI 兼容 SSE handler 工厂（可挂 Starlette/FastAPI/裸 uvicorn）。

    - auth(scope, headers) -> principal|None（同步或协程）：凭据只从请求头
      取（headers 为 {bytes: bytes}），不用 URL token；None→401 拒绝。
    - revocation(principal) -> bool：周期复查的权限撤销接口，False→
      unsubscribed 帧并中断订阅（§6：权限撤销后中断订阅）。
    - 查询参数：after（无 Last-Event-ID 时的起点）、source/category/severity、
      heartbeat（0.01..60，默认 15）。Last-Event-ID 优先于 after。
    - 游标「语法非法」→ 422（HTTP 层拒绝）；游标「过期/超前」→ 200 流内
      显式 resync 事件（合同：不静默丢，区别于存量实现的 HTTP 410）。
    - 存储不可用在流内 resync 后终止，客户端带 Last-Event-ID 退避重连。

    集成注意：本工厂不注册路由、不起服务；挂载点由集成席位决定
    （建议 control_plane 主应用 `/api/v1/logs/events/stream` 路径），
    并须替换 api/events.py 的 logs 占位路由（见该模块头注）。
    """

    async def application(
        scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        if scope.get("type") != "http":
            return
        if scope.get("method") != "GET":
            await _send_json(
                send, 405, {"error": {"code": "method_not_allowed",
                                      "message": "仅支持 GET 订阅。"}}
            )
            return
        headers = {k.lower(): v for k, v in scope.get("headers") or []}
        principal: Any = None
        if auth is not None:
            principal = auth(scope, headers)
            if inspect.isawaitable(principal):
                principal = await principal
            if principal is None:
                await _send_json(
                    send, 401, {"error": {"code": "unauthenticated",
                                          "message": "缺少有效凭据。"}}
                )
                return

        raw_last_event_id = headers.get(b"last-event-id")
        params = parse_qs(scope.get("query_string", b"").decode("latin-1"))

        def _single(name: str) -> str | None:
            values = params.get(name)
            return values[0] if values else None

        cursor_param: str | None
        if raw_last_event_id is not None:
            cursor_param = raw_last_event_id.decode("ascii", errors="strict")
        else:
            cursor_param = _single("after")
        try:
            parse_cursor(cursor_param)  # 语法预检：垃圾游标 422，不做存储 IO
            heartbeat = float(_single("heartbeat") or heartbeat_seconds)
            if not 0.01 <= heartbeat <= 60.0:
                raise ValueError("heartbeat 非法")
        except (ValueError, UnicodeDecodeError):
            await _send_json(
                send, 422, {"error": {"code": "invalid_cursor",
                                      "message": "Last-Event-ID 或参数非法。"}}
            )
            return

        keep: Callable[[], bool] | None = None
        if revocation is not None:
            keep = lambda: bool(revocation(principal))  # 接口回调（行内 lambda 有意为之）

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/event-stream; charset=utf-8"),
                    (b"cache-control", b"no-cache, no-transform"),
                    (b"x-accel-buffering", b"no"),
                ],
            }
        )
        disconnected = asyncio.Event()

        async def watch_disconnect() -> None:
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    disconnected.set()
                    return

        watcher = asyncio.create_task(watch_disconnect())
        try:
            async for frame in event_stream(
                service,
                last_event_id=cursor_param,
                source=_single("source"),
                category=_single("category"),
                severity=_single("severity"),
                heartbeat_seconds=heartbeat,
                poll_interval=poll_interval,
                clock=clock,
                sleep=sleep,
                keep_principal=keep,
            ):
                if disconnected.is_set():
                    break
                await send(
                    {
                        "type": "http.response.body",
                        "body": frame.encode("utf-8"),
                        "more_body": True,
                    }
                )
        finally:
            watcher.cancel()
            try:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            except Exception:  # noqa: BLE001,S110 - 客户端断开后 ASGI send 任何异常都无意义
                pass

    return application


# ---------------------------------------------------------------------------
# 集成工厂
# ---------------------------------------------------------------------------


def build_event_service(
    db_path: str | Path | None = None,
    *,
    max_events: int = 10_000,
    queue_capacity: int = 1024,
    buffer_events: int = DEFAULT_BUFFER_EVENTS,
    buffer_bytes: int = DEFAULT_BUFFER_BYTES,
    start: bool = True,
) -> EventService:
    """装配入口（本轮不接线）：默认库路径经 scripts.runtime_paths 重映射
    （data/ → ChatBot_Runtime 运行数据根），WAL + busy_timeout 由
    EventStore 保证。调用方须在生产装配处显式传入配置键解析出的路径
    （建议复用/新增 bot_control_plane_events_v21_db，属集成席工作）。
    """
    if db_path is None:
        from scripts.runtime_paths import runtime_path

        db_path = runtime_path("data/control_plane_events_v21.sqlite3")
    store = EventStore(db_path, max_events=max_events)
    service = EventService(
        store,
        queue_capacity=queue_capacity,
        buffer_events=buffer_events,
        buffer_bytes=buffer_bytes,
    )
    if start:
        service.start()
    return service


__all__ = [
    "DEFAULT_BUFFER_BYTES",
    "DEFAULT_BUFFER_EVENTS",
    "DEFAULT_HEARTBEAT_SECONDS",
    "DEFAULT_POLL_INTERVAL",
    "MAX_PAGE_LIMIT",
    "EventBroker",
    "EventService",
    "Subscription",
    "build_event_service",
    "create_event_stream_app",
    "event_stream",
]
