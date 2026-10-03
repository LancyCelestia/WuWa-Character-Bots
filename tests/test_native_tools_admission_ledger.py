"""工具注册审批账（fail-closed）常驻门（安全与文档波 · 施工席7 · 2026-10-02）。

背景：``native_tools.py`` 此前对 MCP 腿是「schema 在册即白名单」——新工具名只要
服务器交来就可执行。本门锁 :class:`~...native_tools.ToolAdmissionLedger` 的四条判据，
全离线（零网络/零生产 .env 读；账落 ``tmp_path``，**不往源码树写一个字**）：

① 存量兼容：内置在册九枚 ``native_*`` admit 直接放行且**零落盘**（账文件不出现）。
② fail-closed：外来新工具名首见 ⇒ 落 pending 审计行 + 拒执行；同工具重复 admit
   不重复落账（调度循环防刷爆）；账本目录写不了 ⇒ 照样拒执行、绝不因账缺席放行；
   管理员批准/拒绝写失败必须原样抛（批准必须落得住账）。
③ 显式登记：只有 ``approve``/``deny`` 能翻转状态，deny 后 admit 恒拒；后写覆盖前写。
④ 接线口：``filter_mcp_tools_schema`` 只放行 approved，拒的逐枚回审计标签；
   畸形 schema 条目（非 Mapping/无名）也拒——审查器不因载荷怪形放行。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.core.search import native_tools as nt

_LEDGER_LINES = "tool_admit_ledger.jsonl"


def _ledger(tmp_path: Path, **kwargs: object) -> nt.ToolAdmissionLedger:
    return nt.ToolAdmissionLedger(tmp_path, **kwargs)


def _frozen_clock() -> datetime:
    return datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# ① 存量兼容：内置在册零落盘放行
# ---------------------------------------------------------------------------
def test_builtin_roster_tools_admit_without_touching_disk(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    for name in ("native_weather", "native_search", "native_divination"):
        row = ledger.admit(name)
        assert row.status == nt.TOOL_ADMIT_STATUS_APPROVED, name
    assert not (tmp_path / _LEDGER_LINES).exists(), "内置工具放行不该落账（零落盘）"


def test_non_native_prefix_mcp_tool_needs_approval(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    row = ledger.admit("acme_web_scraper")
    assert row.status == nt.TOOL_ADMIT_STATUS_PENDING
    assert (tmp_path / _LEDGER_LINES).exists(), "外来工具首见必须落 pending 审计行"
    # 同工具再问一遍：放行态不变，且账本不膨胀（防调度循环刷爆）
    row2 = ledger.admit("acme_web_scraper")
    assert row2.status == nt.TOOL_ADMIT_STATUS_PENDING
    lines = [ln for ln in (tmp_path / _LEDGER_LINES).read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1, f"pending 重复 admit 落了第二行（防刷失效）：{len(lines)}"


# ---------------------------------------------------------------------------
# ② fail-closed：账写不了也要拒；批准写不了要原样抛
# ---------------------------------------------------------------------------
def test_admit_is_fail_closed_when_ledger_cannot_be_written(tmp_path: Path) -> None:
    blocking = tmp_path / "not_a_dir"
    blocking.write_text("占位文件占住目录位", encoding="utf-8")
    ledger = nt.ToolAdmissionLedger(blocking)  # mkdir 将失败
    row = ledger.admit("acme_web_scraper")
    assert row.status == nt.TOOL_ADMIT_STATUS_PENDING, "账写不下去必须 fail-closed 拒执行"
    assert "fail-closed" in row.note


def test_approve_raises_when_ledger_cannot_be_written(tmp_path: Path) -> None:
    blocking = tmp_path / "not_a_dir"
    blocking.write_text("占位文件占住目录位", encoding="utf-8")
    ledger = nt.ToolAdmissionLedger(blocking)
    with pytest.raises(nt.ToolAdmitWriteError):
        ledger.approve("acme_web_scraper", actor="admin:10000")


# ---------------------------------------------------------------------------
# ③ 显式登记：批准/拒绝/后写覆盖
# ---------------------------------------------------------------------------
def test_approve_then_admit_passes_and_records_actor(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, clock=_frozen_clock)
    ledger.admit("acme_web_scraper")
    ledger.approve("acme_web_scraper", actor="admin:10000", note="审过来源")
    row = ledger.admit("acme_web_scraper")
    assert row.status == nt.TOOL_ADMIT_STATUS_APPROVED
    assert row.actor == "admin:10000"
    assert row.at == _frozen_clock().isoformat(), "时刻必须带时区（台账 #6 口径）"


def test_deny_is_terminal_against_admit_but_admin_can_flip(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.deny("sketchy_tool", actor="admin:10000", note="来路不明")
    assert ledger.admit("sketchy_tool").status == nt.TOOL_ADMIT_STATUS_DENIED
    ledger.approve("sketchy_tool", actor="admin:10000", note="主人亲自复核放行")
    assert ledger.admit("sketchy_tool").status == nt.TOOL_ADMIT_STATUS_APPROVED


def test_pending_names_roundtrip(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.admit("tool_b")
    ledger.admit("tool_a")
    ledger.approve("tool_a", actor="admin:10000")
    ledger.admit("native_weather")  # 内置：不进账
    assert ledger.pending_names() == ("tool_b",)


def test_malformed_tool_name_is_denied_without_ledger_write(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    for bad in ("", "   ", "x" * 129):
        row = ledger.admit(bad)
        assert row.status == nt.TOOL_ADMIT_STATUS_DENIED
    assert not (tmp_path / _LEDGER_LINES).exists(), "畸形名不该落账"


def test_corrupt_ledger_lines_are_skipped_not_fatal(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.admit("acme_web_scraper")
    with open(ledger.ledger_path, "a", encoding="utf-8") as handle:
        handle.write("{半截烂行不是 JSON\n")
    row = ledger.admit("acme_web_scraper")
    assert row.status == nt.TOOL_ADMIT_STATUS_PENDING, "烂行跳过后现行态仍应是 pending"


def test_status_of_unknown_tool_is_none(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    assert ledger.status_of("never_seen_tool") is None
    assert ledger.status_of("native_weather").status == nt.TOOL_ADMIT_STATUS_APPROVED


# ---------------------------------------------------------------------------
# ④ 接线口：schema 过滤 + 审计标签
# ---------------------------------------------------------------------------
def _schema(name: str) -> dict[str, object]:
    return {"type": "function", "function": {"name": name, "description": "x", "parameters": {}}}


def test_filter_mcp_tools_schema_partitions_by_approval(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    tools = [
        _schema("native_weather"),      # 内置：放行
        _schema("acme_web_scraper"),    # 外来未批：拒 + pending 落账
        _schema("acme_maps"),           # 外来先批：放行
        {"type": "function"},           # 畸形（无名）：拒
        "not-even-a-dict",              # 怪形：拒
    ]
    ledger.approve("acme_maps", actor="admin:10000")
    admitted, refused, tags = nt.filter_mcp_tools_schema(tools, ledger)
    names = [entry["function"]["name"] for entry in admitted]
    assert names == ["native_weather", "acme_maps"]
    assert refused == ("acme_web_scraper", "?", "?")
    assert tags == ("tool_not_in_admit_ledger",) * 3
    assert nt.TOOL_ADMIT_AUDIT_TAG in tags


def test_default_ledger_requires_explicit_directory() -> None:
    with pytest.raises(ValueError):
        nt.ToolAdmissionLedger("   ")


def test_custom_grandfathered_set_overrides_builtin_roster(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, grandfathered=frozenset({"only_this_one"}))
    assert ledger.admit("only_this_one").status == nt.TOOL_ADMIT_STATUS_APPROVED
    assert ledger.admit("native_weather").status == nt.TOOL_ADMIT_STATUS_PENDING
