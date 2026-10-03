"""MCP/native 工具注册审批账（席7 安全与文档波，2026-10-03）。

背景：``native_tools.py`` 现状「schema 在册即白名单」——任何新出现的工具名只要
进了 schema 就可执行，没有管理员审批环节。本波补超管审批账：

- **存量兼容**：``NATIVE_TOOL_ROSTER`` 在册九枚默认视为已批准（零落盘、零行为变化）；
- **新工具首次出现** → 落 pending 审计行 + fail-closed 拒执行，直到管理员批准；
- **命令面不归本席**（admin 域）：本件只交账本 API 与话术常量
  （``TOOL_ADMIT_COMMAND_HINT``），接线说明在席报。

账本形态照 ``consent.JsonSafetyLedger``：JSONL append-only、同工具名后写覆盖前写、
带锁；「谁批的、批的什么」不许被重写抹掉。账写不下去 ⇒ admit 一律 fail-closed
pending（绝不放行），approve/deny 则原样抛（批准必须落得住账）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.core.search.native_tools import (
    NATIVE_TOOL_ROSTER,
    TOOL_ADMIT_COMMAND_HINT,
    ToolAdmissionLedger,
    ToolAdmitWriteError,
)


@pytest.fixture()
def ledger_dir(tmp_path: Path) -> Path:
    return tmp_path / "runtime-data"


def _rows(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_roster_tools_are_grandfathered_without_touching_disk(ledger_dir: Path) -> None:
    """在册工具默认已批准：零落盘、零 pending（存量兼容=零行为变化）。"""
    ledger = ToolAdmissionLedger(ledger_dir)
    assert len(NATIVE_TOOL_ROSTER) >= 1
    for name in list(NATIVE_TOOL_ROSTER)[:3]:
        row = ledger.admit(name)
        assert row.status == "approved", f"在册工具 {name} 被审批账拦下＝存量兼容被破坏"
    assert not list(ledger_dir.glob("*.jsonl")), "在册工具命中却落了盘＝存量面被写脏"


def test_new_tool_first_sight_is_pending_and_audited(ledger_dir: Path) -> None:
    ledger = ToolAdmissionLedger(ledger_dir)
    row = ledger.admit("mcp_github_create_issue", source="mcp")
    assert row.status == "pending", f"新工具首见未进待批：{row}"
    assert row.source == "mcp" and row.at, f"审计行缺来源/时刻：{row}"
    on_disk = _rows(ledger_dir / "tool_admit_ledger.jsonl")
    assert len(on_disk) == 1 and on_disk[0]["status"] == "pending", f"pending 审计行没落账：{on_disk}"
    # pending 态的语义 = 拒执行；再次出现不刷屏（同工具 pending 去重）
    again = ledger.admit("mcp_github_create_issue")
    assert again.status == "pending"
    assert len(_rows(ledger_dir / "tool_admit_ledger.jsonl")) == 1, "pending 重复落账"


def test_approve_then_admit_passes_and_records_actor(ledger_dir: Path) -> None:
    ledger = ToolAdmissionLedger(ledger_dir)
    ledger.admit("mcp_github_create_issue")
    row = ledger.approve("mcp_github_create_issue", actor="10000")
    assert row.status == "approved" and row.actor == "10000"
    assert ledger.admit("mcp_github_create_issue").status == "approved"
    statuses = [r["status"] for r in _rows(ledger_dir / "tool_admit_ledger.jsonl")]
    assert statuses == ["pending", "approved"], f"审计序列不对：{statuses}"


def test_deny_refuses_and_last_row_wins(ledger_dir: Path) -> None:
    ledger = ToolAdmissionLedger(ledger_dir)
    ledger.admit("mcp_web_post")
    ledger.approve("mcp_web_post", actor="10000")
    ledger.deny("mcp_web_post", actor="10000", note="出站写类，不批")
    assert ledger.admit("mcp_web_post").status == "denied"
    assert ledger.status_of("mcp_web_post") is not None
    assert ledger.pending_names() == ()


def test_pending_names_lists_waiting_tools(ledger_dir: Path) -> None:
    ledger = ToolAdmissionLedger(ledger_dir)
    ledger.admit("mcp_alpha")
    ledger.admit("mcp_beta")
    ledger.approve("mcp_alpha", actor="10000")
    assert ledger.pending_names() == ("mcp_beta",)


def test_ledger_unavailable_is_fail_closed_pending(ledger_dir: Path) -> None:
    """账写不下去 ⇒ 拒执行（fail-closed），绝不因账本缺席而放行。"""
    blocker = ledger_dir.parent / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    ledger = ToolAdmissionLedger(blocker / "sub")  # 目录落点被一个文件挡死
    row = ledger.admit("mcp_github_create_issue")
    assert row.status == "pending" and row.note, f"账本不可用却给了执行许可：{row}"
    with pytest.raises(ToolAdmitWriteError):
        ledger.approve("mcp_github_create_issue", actor="10000")


def test_malformed_names_are_refused_without_rows(ledger_dir: Path) -> None:
    ledger = ToolAdmissionLedger(ledger_dir)
    for bad in ("", "   "):
        row = ledger.admit(bad)
        assert row.status == "denied", f"空工具名没被拒：{row}"
    assert not list(ledger_dir.glob("*.jsonl")), "畸形名落了账"


def test_clock_is_injectable_and_timezoned(ledger_dir: Path) -> None:
    fixed = datetime(2026, 10, 3, 8, 0, 0, tzinfo=timezone.utc)
    ledger = ToolAdmissionLedger(ledger_dir, clock=lambda: fixed)
    row = ledger.admit("mcp_x")
    assert row.at == fixed.isoformat()
    assert datetime.fromisoformat(row.at).tzinfo is not None


def test_command_hint_const_is_in_roster_voice() -> None:
    """话术常量在册：命令建议给到 admin 域接线（本席不实现命令本体）。"""
    assert "工具批准" in TOOL_ADMIT_COMMAND_HINT and "工具拒绝" in TOOL_ADMIT_COMMAND_HINT
