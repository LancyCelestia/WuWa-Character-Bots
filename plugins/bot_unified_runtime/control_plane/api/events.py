"""认证事件查询/SSE 工厂；主应用须替换原有 logs 占位路由后再挂载。

路由依赖由主装配注入；本模块不启动采集器、writer 或 FastAPI 应用。
Last-Event-ID 优先于 after；省略两者是显式读取当前保留窗口。客户端收到
cursor_expired 后应提示缺口并由用户选择重新订阅，不应自行静默重置 cursor。
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..events import (
    EVENT_CATEGORIES,
    EVENT_SOURCES,
    CursorExpired,
    EventStoreUnavailable,
    RuntimeEventService,
)
from ..log_collectors import disconnected_collectors
from . import new_debug_id
from .protocol import ERROR_RESPONSES, envelope, new_request_id, request_id_context

_CURSOR = re.compile(r"[0-9]{1,19}\Z")
_STORAGE_ERRORS = (EventStoreUnavailable, sqlite3.Error, OSError)


def _error_payload(
    status: int, code: str, message: str, *, request_id: str | None = None
) -> dict[str, Any]:
    request_id = request_id or request_id_context.get() or new_request_id()
    return envelope(
        None,
        request_id=request_id,
        error={
            "code": code,
            "message": message,
            "request_id": request_id,
            "debug_id": new_debug_id(),
            "retryable": status in (429, 503),
            "field_errors": [],
        },
    )


def _error(status: int, code: str, message: str) -> JSONResponse:
    body = _error_payload(status, code, message)
    return JSONResponse(
        body,
        status_code=status,
        headers={
            "X-Request-ID": body["meta"]["request_id"],
            "Cache-Control": "no-store",
        },
    )


def _frame(data: Any, *, event: str = "log", cursor: int | None = None) -> str:
    prefix = f"id: {cursor}\n" if cursor is not None else ""
    return (
        prefix
        + f"event: {event}\ndata: "
        + json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        + "\n\n"
    )


def _cursor(value: str | int | None) -> int | None:
    if value is None:
        return None
    if type(value) is int and 0 <= value <= 2**63 - 1:
        return value
    if isinstance(value, str) and _CURSOR.fullmatch(value) and int(value) <= 2**63 - 1:
        return int(value)
    raise ValueError("Invalid pagination")


def build_event_router(service: RuntimeEventService, read_dependency: Any, *, collector: Any | None = None) -> APIRouter:
    """Mount once; ALL routes (including SSE and sources) require read_dependency."""
    router = APIRouter(prefix="/api/v1/logs", dependencies=[Depends(read_dependency)], responses=ERROR_RESPONSES)

    @router.get("")
    async def logs(
        after: str | None = None,
        limit: str = "50",
        source: str | None = None,
        category: str | None = None,
    ):
        try:
            page_limit = _cursor(limit)
            if page_limit is None:
                raise ValueError("Invalid pagination")
            return envelope(
                await asyncio.to_thread(
                    service.query,
                    after=_cursor(after),
                    limit=page_limit,
                    source=source,
                    category=category,
                )
            )
        except CursorExpired:
            return _error(
                410, "cursor_expired", "游标已超出保留窗口，请明确选择重新订阅。"
            )
        except ValueError:
            return _error(422, "invalid_query", "事件筛选或分页参数无效。")
        except _STORAGE_ERRORS:
            return _error(503, "events_unavailable", "事件存储暂不可用。")

    @router.get("/sources")
    async def sources():
        return envelope(
            {
                "items": list(EVENT_SOURCES),
                "categories": list(EVENT_CATEGORIES),
                "collector_status": "process_summaries" if collector is not None and collector.active else "not_connected",
                "collectors": collector.status() if collector is not None else disconnected_collectors(),
            }
        )

    # Static paths MUST precede /{event_id}.
    @router.get("/stream")
    async def stream(
        request: Request,
        after: str | None = None,
        source: str | None = None,
        category: str | None = None,
        heartbeat: str = "15",
    ):
        try:
            request_id = request_id_context.get() or new_request_id()
            # Strings avoid FastAPI's default validation errors echoing raw input.
            raw_cursor = request.headers.get("last-event-id")
            cursor = _cursor(raw_cursor if raw_cursor is not None else after)
            if len(str(heartbeat)) > 16:
                raise ValueError
            heartbeat_seconds = float(heartbeat)
            if (
                not math.isfinite(heartbeat_seconds)
                or not 0.01 <= heartbeat_seconds <= 60
            ):
                raise ValueError
            # Preflight before HTTP headers commit: reconnects can receive 410.
            page: dict[str, Any] | None = await asyncio.to_thread(
                service.query, after=cursor, limit=100, source=source, category=category
            )
        except CursorExpired:
            return _error(
                410, "cursor_expired", "游标已超出保留窗口，请明确选择重新订阅。"
            )
        except ValueError:
            return _error(422, "invalid_cursor", "游标或事件筛选参数无效。")
        except _STORAGE_ERRORS:
            return _error(503, "events_unavailable", "事件存储暂不可用。")

        async def frames() -> AsyncIterator[str]:
            # Only one bounded page per subscriber; Starlette cancels this async
            # iterator on disconnect. No worker/subscriber queue or prefetch task.
            nonlocal page
            current, page = page, None
            assert current is not None
            loop = asyncio.get_running_loop()
            last_output = loop.time()
            while True:
                for row in current["items"]:
                    yield _frame(
                        envelope(row, request_id=request_id), cursor=row["cursor"]
                    )
                    last_output = loop.time()
                cursor = current["next_cursor"]
                if not current["has_more"]:
                    if loop.time() - last_output >= heartbeat_seconds:
                        yield ": heartbeat\n\n"
                        last_output = loop.time()
                    await asyncio.sleep(min(heartbeat_seconds, 0.25))
                current = None  # Release old page BEFORE fetching another.
                try:
                    current = await asyncio.to_thread(
                        service.query,
                        after=cursor,
                        limit=100,
                        source=source,
                        category=category,
                    )
                except CursorExpired:
                    yield _frame(
                        _error_payload(
                            410,
                            "cursor_expired",
                            "保留窗口已推进，当前订阅存在缺口。",
                            request_id=request_id,
                        ),
                        event="error",
                    )
                    return
                except _STORAGE_ERRORS:
                    yield _frame(
                        _error_payload(
                            503,
                            "events_unavailable",
                            "事件存储暂不可用。",
                            request_id=request_id,
                        ),
                        event="error",
                    )
                    return
                except ValueError:
                    yield _frame(
                        _error_payload(
                            422,
                            "invalid_cursor",
                            "事件游标失效，请重新查询。",
                            request_id=request_id,
                        ),
                        event="error",
                    )
                    return

        return StreamingResponse(
            frames(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/{event_id}")
    async def detail(event_id: str):
        try:
            item = await asyncio.to_thread(service.get, event_id)
        except ValueError:
            return _error(422, "invalid_event_id", "事件标识无效。")
        except _STORAGE_ERRORS:
            return _error(503, "events_unavailable", "事件存储暂不可用。")
        if item is None:
            return _error(404, "event_not_found", "事件不存在或已超出保留窗口。")
        return envelope(item)

    return router
