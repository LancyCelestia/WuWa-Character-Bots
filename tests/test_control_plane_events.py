"""事件层契约：仅使用隔离 TEMP，不启动 Bot 或采集器。"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading
import time

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane.api.events import build_event_router
from plugins.bot_unified_runtime.control_plane.events import (
    EVENT_CATEGORIES,
    EVENT_SOURCES,
    CursorExpired,
    EventStoreUnavailable,
    RuntimeEventBus,
    RuntimeEventService,
    RuntimeLogEvent,
)


def event(**changes):
    return RuntimeLogEvent(**{"source": "bot", "category": "info", **changes})


@pytest.fixture
def service(tmp_path):
    return RuntimeEventService(tmp_path / "events.sqlite3", max_events=100)


def test_fixed_taxonomy_validation_and_unique_ids():
    assert set(EVENT_CATEGORIES) == {
        "debug",
        "info",
        "warning",
        "error",
        "success",
        "critical",
        "detail",
    }
    assert len(EVENT_SOURCES) == 14
    assert {"telegram", "mail"} <= set(EVENT_SOURCES)
    assert event().event_id != event().event_id
    for changes in (
        {"source": "../../private"},
        {"category": "fatal"},
        {"event_id": "raw body"},
    ):
        with pytest.raises(ValueError):
            event(**changes)


def test_persistence_pagination_filters_idempotency_and_reopen(service):
    first = service.append(event())
    second = service.append(event(source="llm", category="error"))
    third = service.append(event(source="llm", category="success"))
    assert (first.cursor, second.cursor, third.cursor) == (1, 2, 3)
    assert service.append(first).cursor == first.cursor
    page = service.query(limit=2)
    assert [row["cursor"] for row in page["items"]] == [1, 2]
    assert page["has_more"] and page["next_cursor"] == 2
    assert service.query(after=2)["items"][0]["event_id"] == third.event_id
    assert service.query(source="llm", category="error")["items"] == [second.to_dict()]
    reopened = RuntimeEventService(service.db_path, max_events=100)
    assert reopened.get(first.event_id) == first.to_dict()
    assert reopened.get("missing") is None
    with pytest.raises(ValueError):
        service.query(source="bot' OR 1=1--")
    for changes in (
        {"limit": 0},
        {"limit": 501},
        {"after": -1},
        {"after": True},
        {"after": 999},
    ):
        with pytest.raises(ValueError):
            service.query(**changes)


def test_secrets_and_raw_text_never_persist_even_inside_allowed_keys(
    service, monkeypatch
):
    import plugins.bot_unified_runtime.control_plane.events as module

    calls = []
    original = module.redact_private_debug

    def spy(text):
        calls.append(text)
        return original(text)

    monkeypatch.setattr(module, "redact_private_debug", spy)
    raw = "我今天的私密正文 RAWPROMPT-private"
    item = event(
        message=raw + " cookie=top-secret authorization: Bearer private-key",
        details={
            "request_id": "req_123",
            "latency_ms": 12.5,
            "latency": 2,
            "credentials": "cred-secret",
            "cookie": "cookie-secret",
            "rawprompt": raw,
            "user": raw,
            "body": raw,
            "path": "C:\\private",
            "trace_id": raw,
            "model_id": "sk-1234567890123",
            "status": {
                "AUTHORIZATION": "nested-secret",
                "credentials": {"status": "nested-cred"},
                "status": "ok",
                "raw_prompt": raw,
            },
            "error_code": [{"cookie": "list-secret", "error_code": "timeout"}],
        },
    )
    row = service.append(item).to_dict()
    assert row["details"]["request_id"] == "req_123"
    assert row["details"]["latency_ms"] == 12.5
    assert calls, "Must call the existing redactor, not a replacement"
    serialized = json.dumps(row, ensure_ascii=False)
    disk = b"".join(
        p.read_bytes() for p in service.db_path.parent.glob("events.sqlite3*")
    )
    for secret in (
        raw,
        "top-secret",
        "private-key",
        "cred-secret",
        "cookie-secret",
        "nested-secret",
        "nested-cred",
        "list-secret",
        "sk-1234567890123",
        "C:\\private",
    ):
        assert secret not in serialized
        assert secret.encode() not in disk
    assert "credentials" not in serialized and "AUTHORIZATION" not in serialized
    # A safe-looking arbitrary user body must not become an operational message either.
    assert (
        service.append(event(message="my private conversation")).message
        != "my private conversation"
    )


def test_redaction_fails_closed_and_details_are_bounded(service, monkeypatch):
    import plugins.bot_unified_runtime.control_plane.events as module

    def fail(text):
        raise RuntimeError("sensitive exception")

    monkeypatch.setattr(module, "redact_private_debug", fail)
    row = service.append(
        event(message="secret", details={"request_id": "secret"})
    ).to_dict()
    assert "secret" not in json.dumps(row)
    monkeypatch.undo()
    cyclic = {}
    cyclic["status"] = cyclic
    row = service.append(
        event(
            details={
                "status": cyclic,
                "trace_id": "x" * 10000,
                "latency": float("nan"),
                "latency_ms": -1,
            }
        )
    ).to_dict()
    assert len(json.dumps(row, allow_nan=False)) < 4096


def test_retention_reports_expired_cursor_across_restart(tmp_path):
    service = RuntimeEventService(tmp_path / "retained.sqlite3", max_events=2)
    for _ in range(4):
        service.append(event())
    assert [x["cursor"] for x in service.query()["items"]] == [3, 4]
    for candidate in (service, RuntimeEventService(service.db_path, max_events=2)):
        with pytest.raises(CursorExpired):
            candidate.query(after=1)
        with pytest.raises(CursorExpired):
            candidate.query(after=0, source="llm")
        assert candidate.query(after=2)["items"][0]["cursor"] == 3
        assert candidate.query(after=4)["items"] == []


def test_bounded_bus_nonblocking_shutdown_and_detached_snapshot(service, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = service.append

    def blocked(item):
        entered.set()
        assert release.wait(3)
        return original(item)

    monkeypatch.setattr(service, "append", blocked)
    bus = RuntimeEventBus(service, capacity=1)
    assert not bus.publish(event())
    bus.start()
    bus.start()
    try:
        assert bus.publish(event())
        assert entered.wait(1)
        details = {"request_id": "req_original"}
        assert bus.publish(event(details=details))
        details["request_id"] = "mutated"
        begin = time.monotonic()
        for _ in range(500):
            assert not bus.publish(event())
        assert time.monotonic() - begin < 0.5
        assert bus.dropped_count == 500
        assert bus.pending_count == 1
        assert not bus.close(timeout=0.01)
        assert not bus.publish(event())
    finally:
        release.set()
        assert bus.close(timeout=3)
    assert bus.written_count == 2 and not bus.is_running
    assert bus.close()
    assert service.query()["items"][1]["details"]["request_id"] == "req_original"
    with pytest.raises(RuntimeError):
        bus.start()


def test_bus_writer_failure_is_counted_without_leaking(service, monkeypatch):
    def fail(item):
        raise EventStoreUnavailable()

    monkeypatch.setattr(service, "append", fail)
    bus = RuntimeEventBus(service)
    bus.start()
    assert bus.publish(event())
    assert bus.close(timeout=2)
    assert bus.write_error_count == 1
    assert bus.written_count == 0


def app_for(service):
    async def read_dependency(request: Request):
        if request.headers.get("authorization") != "Bearer test-token":
            raise HTTPException(401, "Unauthorized")
        return "reader"

    app = FastAPI()
    router = build_event_router(service, read_dependency)
    app.include_router(router)
    return app, router


AUTH = {"Authorization": "Bearer test-token"}


def test_router_auth_envelope_static_order_and_validation(service):
    first = service.append(event())
    app, router = app_for(service)
    paths = [route.path for route in router.routes]
    assert paths.index("/api/v1/logs/sources") < paths.index("/api/v1/logs/{event_id}")
    assert paths.index("/api/v1/logs/stream") < paths.index("/api/v1/logs/{event_id}")
    with TestClient(app) as client:
        for path in ("", "/sources", "/stream", "/" + first.event_id):
            assert client.get("/api/v1/logs" + path).status_code == 401
        response = client.get("/api/v1/logs", headers=AUTH).json()
        assert set(response) == {"data", "error", "meta"}
        assert response["data"]["items"][0]["cursor"] == 1
        assert response["meta"]["schema_version"] == "v1"
        sources = client.get("/api/v1/logs/sources", headers=AUTH).json()["data"]
        assert (
            set(sources["items"]) == set(EVENT_SOURCES)
            and sources["collector_status"] == "not_connected"
        )
        assert (
            client.get("/api/v1/logs/" + first.event_id, headers=AUTH).json()["data"]
            == first.to_dict()
        )
        assert client.get("/api/v1/logs/missing", headers=AUTH).status_code == 404
        for query in (
            "?limit=0",
            "?limit=501",
            "?source=bad",
            "?category=bad",
            "?after=-1",
        ):
            assert client.get("/api/v1/logs" + query, headers=AUTH).status_code == 422
        for cursor in ("bad", "-1", "1.5", "9" * 100, "999"):
            response = client.get(
                "/api/v1/logs/stream", headers={**AUTH, "Last-Event-ID": cursor}
            )
            assert response.status_code == 422
            error = response.json()["error"]
            # 随机十六进制ID可能碰巧包含bad/999；仅检查可展示错误字段不回显输入。
            assert cursor not in json.dumps({key: value for key, value in error.items() if key not in {"request_id", "debug_id"}})
            assert re.fullmatch(r"req_[0-9a-f]{32}", error["request_id"])
            assert re.fullmatch(r"cp_[0-9a-f]{32}|cp-\d{8}-[0-9a-f]{8}", error["debug_id"])


def test_router_expired_and_database_errors_are_safe(tmp_path, monkeypatch):
    service = RuntimeEventService(tmp_path / "small.sqlite3", max_events=1)
    service.append(event())
    service.append(event())
    app, _ = app_for(service)
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/logs/stream", headers={**AUTH, "Last-Event-ID": "0"}
        )
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "cursor_expired"
        assert client.get("/api/v1/logs?after=0", headers=AUTH).status_code == 410

        def fail(**kwargs):
            raise sqlite3.OperationalError("SELECT secrets FROM C:\\private.db")

        monkeypatch.setattr(service, "query", fail)
        response = client.get("/api/v1/logs", headers=AUTH)
        assert response.status_code == 503
        assert "private" not in response.text and "SELECT" not in response.text


async def stream_response(service, headers=(), **kwargs):
    _, router = app_for(service)
    endpoint = next(
        route.endpoint for route in router.routes if route.path == "/api/v1/logs/stream"
    )
    request = Request({"type": "http", "headers": list(headers)})
    return await endpoint(
        request, after=None, source=None, category=None, heartbeat=0.01, **kwargs
    )


def test_sse_replay_heartbeat_offload_and_cancellation(service, monkeypatch):
    first = service.append(event())
    second = service.append(event())
    calls = []
    original = service.query

    def tracked(**kwargs):
        calls.append(threading.get_ident())
        return original(**kwargs)

    monkeypatch.setattr(service, "query", tracked)

    async def scenario():
        loop_thread = threading.get_ident()
        response = await stream_response(
            service, [(b"last-event-id", str(first.cursor).encode())]
        )
        assert response.media_type == "text/event-stream"
        iterator = response.body_iterator
        data = await anext(iterator)
        assert f"id: {second.cursor}\n" in data and "event: log\n" in data
        payload = json.loads(
            next(line[6:] for line in data.splitlines() if line.startswith("data: "))
        )
        assert payload["data"]["event_id"] == second.event_id
        assert (await anext(iterator)).startswith(": heartbeat")
        pending = asyncio.create_task(anext(iterator))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await iterator.aclose()
        assert calls and all(thread_id != loop_thread for thread_id in calls)

    asyncio.run(scenario())


def test_sse_slow_client_gets_expiry_error_with_bounded_pages(tmp_path):
    service = RuntimeEventService(tmp_path / "slow.sqlite3", max_events=2)
    service.append(event())

    async def scenario():
        response = await stream_response(service)
        iterator = response.body_iterator
        assert "id: 1\n" in await anext(iterator)
        for _ in range(4):
            service.append(event())
        frame = await anext(iterator)
        assert "event: error\n" in frame and "cursor_expired" in frame
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    asyncio.run(scenario())


def test_invalid_numeric_query_never_echoes_sensitive_input(service):
    app, _ = app_for(service)
    with TestClient(app) as client:
        for path, key in (
            ("/api/v1/logs", "after"),
            ("/api/v1/logs", "limit"),
            ("/api/v1/logs/stream", "after"),
            ("/api/v1/logs/stream", "heartbeat"),
        ):
            response = client.get(
                path, headers=AUTH, params={key: "private-user-body C:\\secret.db"}
            )
            assert response.status_code == 422
            assert set(response.json()) == {"data", "error", "meta"}
            assert "private-user-body" not in response.text
            assert "secret.db" not in response.text


def test_publish_never_waits_for_lifecycle_lock(service):
    bus = RuntimeEventBus(service)
    entered, release, published = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    bus.start()

    def locked():
        with bus._lock:
            entered.set()
            release.wait(2)

    lock_holder = threading.Thread(target=locked)
    publisher = threading.Thread(target=lambda: (bus.publish(event()), published.set()))
    lock_holder.start()
    assert entered.wait(1)
    publisher.start()
    try:
        assert published.wait(0.2), "Ingress must not block behind lifecycle contention"
    finally:
        release.set()
        publisher.join(2)
        lock_holder.join(2)
        assert bus.close(timeout=2)


def test_filtered_cursor_advances_and_header_takes_precedence(service):
    service.append(event(source="llm"))
    last = service.append(event(source="bot"))
    page = service.query(source="llm")
    assert len(page["items"]) == 1 and page["next_cursor"] == last.cursor

    async def scenario():
        _, router = app_for(service)
        endpoint = next(
            route.endpoint for route in router.routes if route.path.endswith("/stream")
        )
        request = Request({"type": "http", "headers": [(b"last-event-id", b"1")]})
        response = await endpoint(
            request, after=0, source=None, category=None, heartbeat=0.01
        )
        iterator = response.body_iterator
        assert "id: 2\n" in await anext(iterator)
        await iterator.aclose()

    asyncio.run(scenario())


def test_sqlite_failure_is_sanitized_and_failed_write_does_not_kill_bus(
    service, monkeypatch
):
    with pytest.raises(EventStoreUnavailable) as exc:
        RuntimeEventService(service.db_path.parent / "absent" / "private.sqlite3")
    assert "private" not in str(exc.value)
    original = service.append

    def first_fails(item):
        if item.category == "error":
            raise sqlite3.OperationalError("private SQL exception")
        return original(item)

    monkeypatch.setattr(service, "append", first_fails)
    bus = RuntimeEventBus(service)
    bus.start()
    assert bus.publish(event(category="error"))
    assert bus.publish(event(category="success"))
    assert bus.close(timeout=2)
    assert bus.write_error_count == 1 and bus.written_count == 1


def test_sse_asgi_disconnect_and_thread_read_do_not_stall_loop(service, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    service.append(event())
    original = service.query
    reads = []

    def blocking_query(**kwargs):
        reads.append(threading.get_ident())
        entered.set()
        assert release.wait(2)
        return original(**kwargs)

    monkeypatch.setattr(service, "query", blocking_query)
    app, _ = app_for(service)

    async def scenario():
        disconnected = asyncio.Event()
        messages = []
        request_sent = False

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and b"event: log" in message.get(
                "body", b""
            ):
                disconnected.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/logs/stream",
            "raw_path": b"/api/v1/logs/stream",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"authorization", b"Bearer test-token")],
            "server": ("test", 80),
            "client": ("test", 123),
        }
        task = asyncio.create_task(app(scope, receive, send))
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.001)
            assert entered.is_set() and not task.done()
            # This code runs while SQLite query is blocked in another thread.
            assert all(tid != threading.get_ident() for tid in reads)
            release.set()
            await asyncio.wait_for(task, 2)
            assert disconnected.is_set()
            assert (
                next(m for m in messages if m["type"] == "http.response.start")[
                    "status"
                ]
                == 200
            )
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_cancellation_during_pending_sqlite_read_exits(service, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = service.query
    calls = 0

    def query(**kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            entered.set()
            assert release.wait(2)
        return original(**kwargs)

    monkeypatch.setattr(service, "query", query)

    async def scenario():
        response = await stream_response(service)
        iterator = response.body_iterator
        pending = asyncio.create_task(anext(iterator))
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.001)
            assert entered.is_set()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(pending, 0.5)
            await iterator.aclose()
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(scenario())


def test_concurrent_producers_preserve_queue_bound_and_accounting(service):
    bus = RuntimeEventBus(service, capacity=16)
    bus.start()
    outcomes = []

    def publish_batch():
        outcomes.extend(bus.publish(event()) for _ in range(50))

    producers = [threading.Thread(target=publish_batch) for _ in range(4)]
    for thread in producers:
        thread.start()
    for thread in producers:
        thread.join(3)
        assert not thread.is_alive()
    assert bus.pending_count <= 16
    assert bus.close(timeout=5)
    assert bus.written_count == sum(outcomes)
    assert bus.write_error_count == 0
    assert bus.dropped_count + bus.rejected_count == outcomes.count(False)


def assert_error_shape(body, *, retryable, request_id=None):
    assert set(body) == {"data", "error", "meta"}
    assert set(body["error"]) == {
        "code",
        "message",
        "request_id",
        "debug_id",
        "retryable",
        "field_errors",
    }
    assert body["error"]["request_id"] == body["meta"]["request_id"]
    if request_id:
        assert body["error"]["request_id"] == request_id
    assert body["error"]["debug_id"].startswith("cp-")
    assert body["error"]["retryable"] is retryable
    assert body["error"]["field_errors"] == []


def test_http_error_has_full_v1_shape_and_context(service, monkeypatch):
    from plugins.bot_unified_runtime.control_plane.api.protocol import (
        request_id_context,
    )

    app, _ = app_for(service)
    token = request_id_context.set("req_test_events")
    try:
        with TestClient(app) as client:
            for path in (
                "/api/v1/logs?limit=0",
                "/api/v1/logs/missing",
                "/api/v1/logs/stream?after=invalid",
            ):
                response = client.get(path, headers=AUTH)
                assert_error_shape(
                    response.json(), retryable=False, request_id="req_test_events"
                )
                assert response.headers["x-request-id"] == "req_test_events"

            def fail(**kwargs):
                raise EventStoreUnavailable()

            monkeypatch.setattr(service, "query", fail)
            response = client.get("/api/v1/logs", headers=AUTH)
            assert_error_shape(
                response.json(), retryable=True, request_id="req_test_events"
            )
    finally:
        request_id_context.reset(token)


def test_sse_errors_share_full_v1_shape_and_captured_request_context(
    service, monkeypatch
):
    from plugins.bot_unified_runtime.control_plane.api.protocol import (
        request_id_context,
    )

    async def scenario():
        service.append(event())
        token = request_id_context.set("req_sse_test")
        try:
            response = await stream_response(service)
        finally:
            request_id_context.reset(token)
        iterator = response.body_iterator
        first = await anext(iterator)
        body = json.loads(
            next(line[6:] for line in first.splitlines() if line.startswith("data: "))
        )
        assert body["meta"]["request_id"] == "req_sse_test"

        def fail(**kwargs):
            raise EventStoreUnavailable()

        monkeypatch.setattr(service, "query", fail)
        frame = await anext(iterator)
        assert "event: error\n" in frame
        body = json.loads(
            next(line[6:] for line in frame.splitlines() if line.startswith("data: "))
        )
        assert_error_shape(body, retryable=True, request_id="req_sse_test")
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    asyncio.run(scenario())


def test_structured_summary_retains_only_safe_schema(service):
    safe = {
        "status": "timeout",
        "capability_id": "weather",
        "model_id": "gpt-5.6-terra",
        "error_code": "upstream_timeout",
        "latency_ms": 1500,
        "retry_count": 2,
    }
    original = {
        **safe,
        "credentials": {"status": "unsafe-secret"},
        "cookie": "cookie-secret",
        "authorization": "Bearer hidden",
        "rawprompt": "用户私密原文",
        "message": "用户私密原文",
        "summary": {"status": "retrying", "user_body": "用户私密原文"},
    }
    row = service.append(event(details={"summary": original})).to_dict()
    assert row["details"]["summary"] == {**safe, "summary": {"status": "retrying"}}
    assert service.append(event(details={"summary": "raw user text"})).details == {}
