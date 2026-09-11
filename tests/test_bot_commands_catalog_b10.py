"""B10 杂项批 · /bot commands 命令目录回归（离线）。

交付点：
1. resolve_help_query 把 commands/命令… 归一成目录请求（/bot commands 可达）；
2. build_commands_catalog_body 机器可读：[routes]/[commands] 区段 + 「 | 」字段行，
   数据源 = base_router 路由表 + _HELP_ENTRIES，非管理员只见公开模块；
3. build_help_result 对 commands 走纯文本目录，不渲染帮助卡（与 /bot help 不重复）；
4. /bot help 默认总览行为不回归。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.capabilities.echo import (
    build_commands_catalog_body,
    build_help_result,
    resolve_help_query,
)
from plugins.bot_unified_runtime.runtime.base_router import list_route_rules_for_audit


def test_resolve_help_query_maps_commands_variants() -> None:
    assert resolve_help_query("/bot commands") == "commands"
    assert resolve_help_query("commands") == "commands"
    assert resolve_help_query("/bot 命令列表") == "commands"
    # help 总览与主题查询不受影响。
    assert resolve_help_query("/bot help") == ""
    assert resolve_help_query("/bot help 点歌") == "点歌"
    assert resolve_help_query("/bot status") == ""


def test_catalog_is_machine_readable_and_complete() -> None:
    body = build_commands_catalog_body(is_admin=True)
    lines = body.splitlines()
    assert lines[0].startswith("命令目录 v1")
    route_lines = [ln for ln in lines if ln and ln[0].isdigit()]
    rules = list_route_rules_for_audit()
    assert len(route_lines) == len(rules)
    for line in route_lines:
        priority, kind, capability_id, label = [part.strip() for part in line.split("|")]
        assert priority.isdigit()
        assert capability_id.startswith("bot.")
        assert kind and label
    assert "[routes] priority | kind | capability_id | label" in body
    assert "[commands] topic | aliases | access" in body
    # 公共能力出现在目录中。
    assert "bot.weather" in body
    assert "天气 | 天气/weather" in body


def test_catalog_hides_admin_topics_for_public() -> None:
    public = build_commands_catalog_body(is_admin=False)
    admin = build_commands_catalog_body(is_admin=True)
    # 「状态」是 admin_only 帮助模块：非管理员目录不含，管理员目录含。
    assert "\n状态 | " not in public
    assert "\n状态 | " in admin
    # 路由表对两者一致（路由语义公开）。
    assert "bot.status | 11" in public or "| bot.status |" in public


def test_help_result_commands_is_text_not_card() -> None:
    result = build_help_result(request_id="req-1", query="/bot commands", is_admin=False)
    assert result.capability_id == "bot.commands"
    assert result.kind == "text"
    assert result.body.startswith("命令目录 v1")
    assert result.images == []
    assert "commands_catalog" in result.audit_tags


def test_help_index_default_unregressed() -> None:
    result = build_help_result(request_id="req-2", query="/bot help", is_admin=False)
    assert result.capability_id == "bot.help"
    assert "功能帮助总览" in result.body
