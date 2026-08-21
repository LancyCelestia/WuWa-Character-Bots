from __future__ import annotations

import inspect

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import PrivacyLevel


def _roles_config() -> Config:
    return Config(
        bot_admin_user_ids=["10001"],
        bot_enterprise_user_ids=["20001", "20002"],
        bot_trusted_user_ids=["30001"],
        bot_blocked_user_ids=["40001"],
        bot_rate_limit_bypass_roles=["admin", "trusted"],
        bot_quiet_hours_bypass_roles=["admin"],
        bot_runtime_group_command_prefix="!",
    )


def test_admin_roles_query_returns_safe_role_matrix_without_ids():
    from plugins.bot_unified_runtime.capabilities.debug import build_roles_query_result

    result = build_roles_query_result(
        _roles_config(),
        request_id="req_roles",
        actor_roles=["user", "admin"],
    )

    assert result.capability_id == "bot.roles"
    assert result.request_id == "req_roles"
    assert result.privacy_level is PrivacyLevel.PERSONAL
    assert "权限规则" in result.body
    assert "role_order=user,trusted,enterprise,admin,blocked" in result.body
    assert "admin_users=1" in result.body
    assert "enterprise_users=2" in result.body
    assert "trusted_users=1" in result.body
    assert "blocked_users=1" in result.body
    assert "blocked_policy=policy_stage_block_before_llm" in result.body
    assert "rate_limit_bypass_roles=admin,trusted" in result.body
    assert "quiet_hours_bypass_roles=admin" in result.body
    assert "group_command_prefix=!" in result.body
    assert "id_input_formats=json_array,comma,semicolon" in result.body
    assert "admin_commands=" in result.body
    assert "/bot roles" in result.body
    assert "ids_hidden=true" in result.body
    assert "不调用 LLM" in result.body
    assert "不连接 NapCat" in result.body

    forbidden_fragments = [
        "10001",
        "20001",
        "20002",
        "30001",
        "40001",
        "target_id",
        "provider_message_id",
        "private_debug",
        "session_id",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in result.body


def test_non_admin_roles_query_is_rejected_without_leaking_counts_or_ids():
    from plugins.bot_unified_runtime.capabilities.debug import build_roles_query_result

    result = build_roles_query_result(
        _roles_config(),
        request_id="req_roles",
        actor_roles=["user"],
    )

    assert result.capability_id == "bot.roles"
    assert "只有管理员可以查看运行时排障记录" in result.body
    assert "admin_users" not in result.body
    assert "10001" not in result.body
    assert "40001" not in result.body


def test_plugin_entry_exposes_admin_roles_command_without_self_overwrite():
    import plugins.bot_unified_runtime as plugin_entry

    source = inspect.getsource(plugin_entry)

    assert "build_roles_query_result" in source
    assert 'capability_id = "bot.roles"' in source
    assert "bot.roles" in plugin_entry.NO_RUNTIME_DIAGNOSTIC_CAPABILITY_IDS
    assert "bot.control" in plugin_entry.NO_RUNTIME_DIAGNOSTIC_CAPABILITY_IDS


def test_help_text_mentions_roles_command():
    from plugins.bot_unified_runtime.capabilities.echo import build_help_result

    result = build_help_result(request_id="req_help")

    assert "/bot roles" in result.body
