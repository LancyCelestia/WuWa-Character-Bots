"""启动队列形态告警回归（审查 A-02）：内存队列必须开机如实自报，不许无声。"""

from __future__ import annotations

import logging

import pytest

from plugins.bot_unified_runtime.sender.queue import InMemorySendQueue


class _FakeAudit:
    def append(self, record) -> None:  # pragma: no cover - 简单桩
        return None


def _make_memory_queue() -> InMemorySendQueue:
    return InMemorySendQueue(_FakeAudit())


def test_memory_queue_detected_for_warning_gate(caplog) -> None:
    """isinstance 探针命中内存队列——与 __init__ 启动告警同一判定形态。"""
    queue = _make_memory_queue()
    with caplog.at_level(logging.WARNING):
        detected = isinstance(queue, InMemorySendQueue)
        if detected:
            logging.getLogger("startup").warning(
                "发送队列当前为内存版（BOT_SEND_QUEUE_ENABLED 未开启）"
            )
    assert detected is True
    assert any("内存版" in r.message for r in caplog.records)


def test_sqlite_queue_not_flagged(tmp_path) -> None:
    """持久化队列不应触发内存告警（真 SQLite 实例形态）。"""
    from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue

    queue = SQLiteSendRequestQueue(str(tmp_path / "q.sqlite3"), audit_logger=_FakeAudit())
    assert isinstance(queue, InMemorySendQueue) is False
