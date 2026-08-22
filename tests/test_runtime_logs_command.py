"""/bot logs 查询命令测试。"""

from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.capabilities.runtime_logs import (
    build_logs_query_result,
)
from plugins.bot_unified_runtime.sources.runtime_event_log import RuntimeEventLog


def test_logs_query_denied_for_non_admin():
    result = build_logs_query_result(
        None, request_id="r1", actor_roles=["member"]
    )
    assert result.capability_id == "bot.logs"
    assert "管理员" in result.body


def test_logs_query_returns_filtered_lines(tmp_path):
    log = RuntimeEventLog(tmp_path / "events.log")
    log.info("startup", module="onebot")
    log.warning("retry", code=412)
    log.error("send_failed", target="x")
    result = build_logs_query_result(
        log,
        request_id="r1",
        actor_roles=["admin"],
        level="warning",
        limit=10,
    )
    assert result.capability_id == "bot.logs"
    assert "[WARNING]" in result.body
    assert "[ERROR]" in result.body
    assert "[INFO]" not in result.body


def test_logs_query_parses_level_and_limit_args():
    assert build_logs_query_result(
        None, request_id="r1", actor_roles=["admin"], level="error", limit=3
    ).body != ""
