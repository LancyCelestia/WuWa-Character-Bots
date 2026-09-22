"""进程日志只进入结构化摘要总线；不复制正文、异常或路径。"""
from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token
from plugins.bot_unified_runtime.control_plane.events import (
    RuntimeEventBus,
    RuntimeEventService,
)


@pytest.fixture
def collector_type():
    return importlib.import_module("plugins.bot_unified_runtime.control_plane.log_collectors").ProcessLogCollector


class Bus:
    def __init__(self):
        self.events = []
    def publish(self, event):
        self.events.append(event)
        return True


@pytest.mark.parametrize("level,category", [("DEBUG", "debug"), ("INFO", "info"), ("WARN", "warning"), ("ERROR", "error"), ("SUCCESS", "success"), ("FATAL", "critical"), ("TRACE", "detail")])
def test_seven_categories_and_untrusted_fields(collector_type, level, category):
    bus = Bus()
    collector = collector_type(bus)
    assert collector.ingest(source="napcat", level=level, details={"request_id": "req_fixture", "body": "private-chat", "token": "sk-secret", "path": "C:/private/file"})
    payload = bus.events[0].to_dict()
    assert payload["source"] == "napcat" and payload["category"] == category
    assert payload["details"] == {"request_id": "req_fixture"}
    assert "private" not in repr(payload) and "secret" not in repr(payload)
    assert collector.status()["napcat"] == "not_connected"  # ingest 是协议适配口，不伪装已连接进程


def test_invalid_or_unrelated_log_is_ignored(collector_type):
    bus = Bus()
    collector = collector_type(bus)
    assert not collector.ingest(source="../../private", level="INFO")
    assert not collector.ingest(source="bot", level="garbage")
    for name in ("httpx", "thirdparty", "plugins.bot_unified_runtime.control_plane.events"):
        collector.handle_stdlib(logging.LogRecord(name, logging.INFO, "secret.py", 1, "private", (), None))
    assert not bus.events


def test_stdlib_never_formats_raw_messages_or_exception(collector_type):
    class Secret:
        def __str__(self):
            raise AssertionError("must not format user content")
    bus = Bus()
    collector = collector_type(bus)
    record = logging.LogRecord("plugins.bot_unified_runtime.sender.worker", logging.ERROR, "C:/private.py", 1, Secret(), (), (ValueError, ValueError("private"), None))
    record.request_id = "req_test"
    collector.handle_stdlib(record)
    assert len(bus.events) == 1
    assert bus.events[0].source == "sender"
    assert bus.events[0].details == {"request_id": "req_test"}
    assert "private" not in repr(bus.events[0])
    # v21r2 W14：真身迁 domains/transport/ 后的新 logger 前缀同样归类 sender。
    new_record = logging.LogRecord("plugins.bot_unified_runtime.domains.transport.sender.worker", logging.ERROR, "C:/private.py", 1, Secret(), (), None)
    new_record.request_id = "req_test"
    collector.handle_stdlib(new_record)
    assert len(bus.events) == 2
    assert bus.events[1].source == "sender"


def test_failing_publisher_never_raises_or_logs(collector_type):
    collector = collector_type(SimpleNamespace(publish=Mock(side_effect=OSError("secret"))))
    assert not collector.ingest(source="bot", level="INFO")
    assert collector.status()["publish_failures"] == 1
    assert "secret" not in repr(collector.status())


def test_start_close_are_idempotent_and_remove_only_owned_handlers(collector_type):
    root = logging.Logger("fixture-root")  # noqa: LOG001 - 隔离测试 logger，避免污染全局层级。
    existing = logging.NullHandler()
    root.addHandler(existing)
    fake = SimpleNamespace(add=Mock(return_value=42), remove=Mock())
    bus = Bus()
    collector = collector_type(bus, root_logger=root, nonebot_logger=fake)
    collector.start()
    collector.start()
    assert len(root.handlers) == 2 and fake.add.call_count == 1
    sink = fake.add.call_args.args[0]
    sink(SimpleNamespace(record={"name": "nonebot.adapters.telegram.bot", "level": SimpleNamespace(name="SUCCESS"), "extra": {"request_id": "req_tg"}, "message": "private"}))
    assert bus.events[0].source == "telegram"
    assert bus.events[0].category == "success"
    assert collector.status()["nonebot"] == "attached"
    collector.close()
    collector.close()
    assert root.handlers == [existing]
    fake.remove.assert_called_once_with(42)
    assert collector.status()["stdlib"] == "not_connected"
    sink(SimpleNamespace(record={"name": "nonebot", "level": SimpleNamespace(name="INFO"), "extra": {}}))
    assert len(bus.events) == 1  # 已移除 sink 的迟到回调不再进入总线


def test_real_log_record_is_queryable_after_bus_drain(collector_type, tmp_path):
    service = RuntimeEventService(tmp_path / "events.sqlite3")
    bus = RuntimeEventBus(service)
    root = logging.Logger("fixture-root")  # noqa: LOG001 - 隔离测试 logger，避免污染全局层级。
    collector = collector_type(bus, root_logger=root)
    bus.start()
    collector.start()
    try:
        root.handle(logging.LogRecord("plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers", logging.WARNING, "private.py", 1, "Bearer private", (), None))
    finally:
        collector.close()
        assert bus.close()
    items = service.query(source="llm")["items"]
    assert len(items) == 1 and items[0]["category"] == "warning"
    assert "private" not in repr(items)


@pytest.mark.parametrize("attached", [True, False])
def test_app_lifespan_advertises_real_collector_status(tmp_path, collector_type, attached):
    config = SimpleNamespace(
        bot_control_plane_token_sha256=hash_token("reader"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
    )
    service = RuntimeEventService(tmp_path / "events.sqlite3")
    app = create_control_plane_app(config, event_service=service, audit_store=ControlPlaneAuditStore(tmp_path / "audit.sqlite3"), runtime_attached=attached)
    headers = {"Authorization": "Bearer reader"}
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        assert client.get("/api/v1/logs/sources").status_code == 401
        response = client.get("/api/v1/logs/sources", headers=headers).json()["data"]
        assert response["collectors"]["stdlib"] == ("attached" if attached else "not_connected")
        assert response["collectors"]["napcat"] == "not_connected"
        assert response["collectors"]["raw_content"] is False
        protocol = client.get("/api/v1/protocol", headers=headers).json()["data"]
        assert protocol["services"]["events"]["console_collectors"] == ("process_summaries" if attached else "not_connected")
    if attached:
        assert app.state.log_collector.status()["stdlib"] == "not_connected"


def test_real_nonebot_loguru_sink_captures_only_summary(collector_type):
    from nonebot.log import logger

    bus = Bus()
    root = logging.Logger("fixture-root")  # noqa: LOG001 - 不污染全局 logger。
    collector = collector_type(bus, root_logger=root, nonebot_logger=logger)
    collector.start()
    try:
        logger.patch(lambda record: record.update(name="nonebot.adapters.telegram.bot")).bind(request_id="req_live_fixture").success("fixture body excluded")
    finally:
        collector.close()
    assert len(bus.events) == 1
    assert bus.events[0].source == "telegram"
    assert bus.events[0].details == {"request_id": "req_live_fixture"}
    assert "fixture body excluded" not in repr(bus.events)
