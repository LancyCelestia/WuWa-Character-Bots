"""管理团队名单 + 超管角色回归（独立命名）。

覆盖两块：
A. policy/roles.py —— 超管自动叠加 admin 角色、普通用户不含超管、
   build_role_settings 从 config.bot_super_admin_user_ids 装配。
B. capabilities/chat.py build_admin_roster_text —— 空名单空串、
   档案行文案（超级管理员/管理员）、仅 super_ids 的兜底行。
"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.policy.roles import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
    RoleSettings,
    build_role_settings,
)

# ---------------------------------------------------------------------------
# A. roles.py：super_admin 角色解析
# ---------------------------------------------------------------------------


def _message(sender_id: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        sender_display_name="阿澄",
        plain_text="在吗",
    )


def _empty_settings(**overrides) -> RoleSettings:
    base = dict(
        admin_user_ids=frozenset(),
        enterprise_user_ids=frozenset(),
        trusted_user_ids=frozenset(),
        blocked_user_ids=frozenset(),
        super_admin_user_ids=frozenset(),
    )
    base.update(overrides)
    return RoleSettings(**base)


def test_super_admin_resolves_with_auto_stacked_admin() -> None:
    # 超管自动叠加 admin：既有 admin 判定点无需逐一感知超管的存在
    settings = _empty_settings(super_admin_user_ids={"999"}, admin_user_ids=set())
    roles = settings.resolve_roles(_message("999"))
    assert ROLE_SUPER_ADMIN in roles
    assert ROLE_ADMIN in roles
    # 顺序按 ROLE_ORDER：user < admin < super_admin
    assert roles == [ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN]


def test_plain_user_has_no_super_admin() -> None:
    settings = _empty_settings(super_admin_user_ids={"999"})
    roles = settings.resolve_roles(_message("12345"))
    assert ROLE_SUPER_ADMIN not in roles
    assert ROLE_ADMIN not in roles
    assert roles == [ROLE_USER]


def test_build_role_settings_reads_super_admin_ids_from_config() -> None:
    config = SimpleNamespace(
        bot_admin_user_ids={"111"},
        bot_telegram_admin_user_ids=set(),
        bot_super_admin_user_ids={"999"},
        bot_enterprise_user_ids=set(),
        bot_trusted_user_ids=set(),
        bot_blocked_user_ids=set(),
    )
    settings = build_role_settings(config)
    assert "999" in settings.super_admin_user_ids
    roles = settings.resolve_roles(_message("999"))
    assert ROLE_SUPER_ADMIN in roles and ROLE_ADMIN in roles


# ---------------------------------------------------------------------------
# B. chat.py：build_admin_roster_text 管理团队名单
# ---------------------------------------------------------------------------


def _roster_config(
    super_ids: list[str] | None = None, profiles: list[dict] | None = None
):
    return SimpleNamespace(
        bot_super_admin_user_ids=super_ids or [],
        bot_admin_profiles=profiles or [],
    )


def test_roster_empty_when_no_super_ids_and_no_profiles() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import build_admin_roster_text

    assert build_admin_roster_text(_roster_config()) == ""


def test_roster_profile_super_role_line() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import build_admin_roster_text

    text = build_admin_roster_text(
        _roster_config(
            profiles=[
                {
                    "qq": "999",
                    "name": "兰茜",
                    "nicknames": "茜茜",
                    "role": "super",
                    "note": "守岸人的主人，同一人",
                }
            ]
        )
    )
    # 行格式：- {who}｜{role_label}｜{detail}
    assert "｜超级管理员｜" in text
    assert "兰茜" in text
    assert "999" in text
    assert "可叫：茜茜" in text
    assert "同一人" in text


def test_roster_profile_admin_role_label() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import build_admin_roster_text

    text = build_admin_roster_text(
        _roster_config(
            profiles=[
                {"qq": "222", "name": "阿澄", "role": "admin"},
            ]
        )
    )
    assert "阿澄" in text
    # 档案行标「管理员」而非「超级管理员」（rules 段固定含「超级管理员」
    # 权威条款，故用行内分隔符锚定 role_label，避免误判）
    assert "｜管理员｜" in text
    assert "｜超级管理员｜" not in text


def test_roster_super_ids_only_lists_all_qq() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import build_admin_roster_text

    text = build_admin_roster_text(_roster_config(super_ids=["888", "999"]))
    assert "超级管理员 QQ" in text
    assert "888" in text
    assert "999" in text
    assert "888、999" in text
