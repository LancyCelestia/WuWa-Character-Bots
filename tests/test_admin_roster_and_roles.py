"""管理团队名单 + 超管角色回归（独立命名）。

覆盖三块：
A. policy/roles.py —— 超管自动叠加 admin 角色、普通用户不含超管、
   build_role_settings 从 config.bot_super_admin_user_ids 装配。
A2. policy/roles.py 平台域（F-A 2026-09-28）—— QQ/TG 同号互不放行、
   TG 名单条目在 QQ 侧不生效、缺平台事实 fail-closed 到普通用户、
   QQ 侧既有 admin 行为零回归（含 counts() 等值与 blocked 收权腿不破）。
B. capabilities/chat.py build_admin_roster_text —— 空名单空串、
   档案行文案（超级管理员/管理员）、仅 super_ids 的兜底行。
"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_ADMIN,
    ROLE_BLOCKED,
    ROLE_ENTERPRISE,
    ROLE_SUPER_ADMIN,
    ROLE_TRUSTED,
    ROLE_USER,
    RoleSettings,
    build_role_settings,
    is_admin_message,
)

# ---------------------------------------------------------------------------
# A. roles.py：super_admin 角色解析
# ---------------------------------------------------------------------------


def _message(sender_id: str, *, platform: str = "qq") -> IncomingMessage:
    return IncomingMessage(
        platform=platform,
        adapter="onebot",
        bot_id="10000",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        sender_display_name="阿澄",
        plain_text="在吗",
    )


def _empty_settings(**overrides) -> RoleSettings:
    base = {
        "admin_user_ids": frozenset(),
        "enterprise_user_ids": frozenset(),
        "trusted_user_ids": frozenset(),
        "blocked_user_ids": frozenset(),
        "super_admin_user_ids": frozenset(),
    }
    base.update(overrides)
    return RoleSettings(**base)


def _roles_config(
    *,
    admin: set[str] | None = None,
    telegram_admin: set[str] | None = None,
    super_admin: set[str] | None = None,
):
    """只喂 build_role_settings 需要的名单，不构造整个 Config。"""
    return SimpleNamespace(
        bot_admin_user_ids=admin or set(),
        bot_telegram_admin_user_ids=telegram_admin or set(),
        bot_super_admin_user_ids=super_admin or set(),
        bot_enterprise_user_ids=set(),
        bot_trusted_user_ids=set(),
        bot_blocked_user_ids=set(),
    )


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
# A2. 平台域（F-A）：管理/超管名单按平台匹配，跨平台同号不放行
# ---------------------------------------------------------------------------


def test_qq_admin_number_does_not_grant_admin_on_telegram() -> None:
    """同号两格①：QQ 管理员号 2002 在 Telegram 侧（TG 陌生人）不得吃出 admin。"""
    settings = build_role_settings(_roles_config(admin={"2002"}))
    qq_roles = settings.resolve_roles(_message("2002", platform="qq"))
    tg_roles = settings.resolve_roles(_message("2002", platform="telegram"))
    assert ROLE_ADMIN in qq_roles
    assert tg_roles == [ROLE_USER], f"QQ 名单跨平台提权未拦住：{tg_roles}"


def test_telegram_admin_number_does_not_grant_admin_on_qq() -> None:
    """同号两格②：TG 管理员号 1001 在 QQ 侧（同号 QQ 陌生人）不得吃出 admin。"""
    settings = build_role_settings(_roles_config(telegram_admin={"1001"}))
    qq_roles = settings.resolve_roles(_message("1001", platform="qq"))
    assert qq_roles == [ROLE_USER], f"TG 名单条目在 QQ 侧仍生效：{qq_roles}"


def test_telegram_admin_still_effective_on_telegram() -> None:
    """零回归（正向）：TG 名单条目在本域照旧是 admin——修跨平台不吃掉合法权。"""
    settings = build_role_settings(_roles_config(telegram_admin={"1001"}))
    roles = settings.resolve_roles(_message("1001", platform="telegram"))
    assert ROLE_ADMIN in roles
    assert settings.admin_user_ids == frozenset({"telegram:1001"})


def test_super_admin_roster_is_qq_scoped() -> None:
    """超管名单同样是 QQ 原生域：同号 TG 用户不吃超管脸（含其自动叠加的 admin）。"""
    settings = build_role_settings(_roles_config(super_admin={"999"}))
    tg_roles = settings.resolve_roles(_message("999", platform="telegram"))
    assert tg_roles == [ROLE_USER], f"超管跨平台提权未拦住：{tg_roles}"
    assert ROLE_SUPER_ADMIN not in settings.resolve_roles(
        _message("999", platform="email")
    )


def test_missing_or_unknown_platform_fails_closed_to_user() -> None:
    """缺平台事实 / 平台不认识 → 管理、超管一律不放行（取不到就不放行）。"""
    settings = build_role_settings(
        _roles_config(admin={"1001", "2002"}, super_admin={"3003"})
    )
    for platform in ("", "  ", "email", "mail", "console", "unknown_platform"):
        roles = settings.resolve_roles(_message("1001", platform=platform))
        assert roles == [ROLE_USER], f"平台={platform!r} 未 fail-closed：{roles}"
        assert ROLE_ADMIN not in settings.resolve_roles(
            _message("3003", platform=platform)
        )


def test_explicit_platform_prefix_honours_only_its_domain() -> None:
    """条目自带平台前缀的沿用既有形态：只在同域生效（不新建第二张名单）。"""
    settings = build_role_settings(_roles_config(admin={"telegram:7007", "8008"}))
    assert settings.admin_user_ids == frozenset({"telegram:7007", "8008"})
    assert ROLE_ADMIN in settings.resolve_roles(_message("7007", platform="telegram"))
    assert settings.resolve_roles(_message("7007", platform="qq")) == [ROLE_USER]
    assert ROLE_ADMIN in settings.resolve_roles(_message("8008", platform="qq"))
    assert settings.resolve_roles(_message("8008", platform="telegram")) == [ROLE_USER]


def test_existing_admin_behavior_unchanged_on_qq_side() -> None:
    """既有 admin 行为零回归：QQ 侧裸号照旧、OneBot/NoneBot 写法同属 QQ 域、
    超管照旧叠加 admin、counts() 与改动前逐枚等值。"""
    settings = build_role_settings(_roles_config(admin={"1001"}, super_admin={"999"}))
    assert settings.resolve_roles(_message("1001")) == [ROLE_USER, ROLE_ADMIN]
    assert settings.resolve_roles(_message("999")) == [
        ROLE_USER,
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN,
    ]
    for platform in ("qq", "onebot", "onebot.v11", "onebot_v11", "nonebot"):
        assert ROLE_ADMIN in settings.resolve_roles(
            _message("1001", platform=platform)
        ), f"QQ 协议域写法 {platform!r} 被误伤"
    assert settings.counts() == {
        ROLE_ADMIN: 1,
        ROLE_SUPER_ADMIN: 1,
        ROLE_ENTERPRISE: 0,
        ROLE_TRUSTED: 0,
        ROLE_BLOCKED: 0,
    }


def test_blocked_roster_still_applies_on_every_platform() -> None:
    """blocked 是收权腿，保持平台无关：不因本次改动在任一平台丢封禁标签。

    既有语义照旧——blocked 与 admin 可共存于角色列表，真正的拒答点在中央门
    （``policy/gate.py``：``ROLE_BLOCKED in actor_roles → sender_blocked``）。
    本次只把管理/超管的**授予**面按平台域收口，收权面一律不动。
    """
    settings = _empty_settings(
        blocked_user_ids={"6006"},
        admin_user_ids={"6006"},
    )
    for platform in ("qq", "telegram", "email", ""):
        roles = settings.resolve_roles(_message("6006", platform=platform))
        assert ROLE_BLOCKED in roles, f"平台={platform!r} 丢封禁：{roles}"
    # QQ 域：admin 与 blocked 共存（改动前后逐字等值，封禁由门裁决）。
    assert settings.resolve_roles(_message("6006", platform="qq")) == [
        ROLE_USER,
        ROLE_ADMIN,
        ROLE_BLOCKED,
    ]
    # 非 QQ 域：封禁照吃，管理授予不再跨侧生效。
    for platform in ("telegram", "email", ""):
        assert settings.resolve_roles(_message("6006", platform=platform)) == [
            ROLE_USER,
            ROLE_BLOCKED,
        ], platform


def test_is_admin_message_blocks_cross_platform_same_number() -> None:
    """旁路复用口（F-A 残留）：QQ 管理员号 2002 在 telegram 平台不放行，
    在 QQ 平台照旧放行——与 resolve_roles 的 admin 腿同判据、同一批原语。"""
    config = _roles_config(admin={"2002"})
    assert is_admin_message(config, _message("2002", platform="telegram")) is False
    assert is_admin_message(config, _message("2002", platform="qq")) is True
    assert is_admin_message(config, _message("2002", platform="onebot.v11")) is True


def test_is_admin_message_honours_telegram_roster_and_fails_closed() -> None:
    """旁路复用口：TG 名单条目在本域放行、在 QQ 侧不生效；
    缺平台事实/平台不认识/空号一律 fail-closed；超管名单不吃（旁路既有语义）。"""
    config = _roles_config(telegram_admin={"1001"})
    assert is_admin_message(config, _message("1001", platform="telegram")) is True
    assert is_admin_message(config, _message("1001", platform="qq")) is False
    for platform in ("", "email", "console", "unknown_platform"):
        assert is_admin_message(config, _message("1001", platform=platform)) is False
    assert is_admin_message(_roles_config(super_admin={"999"}), _message("999")) is False


def test_is_admin_message_tolerates_duck_and_none_config() -> None:
    """旁路复用口的 config 面与旁路点旧 getattr 语义同宽：字段缺、部分名单、
    ``None`` 都不炸；缺 admin 字段＝空名单不放行，只给 QQ 裸名单时 QQ 域照旧。"""
    assert is_admin_message(None, _message("2002")) is False
    assert is_admin_message(SimpleNamespace(), _message("2002")) is False
    partial = SimpleNamespace(bot_admin_user_ids=["999"])
    assert is_admin_message(partial, _message("999", platform="telegram")) is False
    assert is_admin_message(partial, _message("999", platform="onebot")) is True
    assert is_admin_message(partial, _message("999", platform="qq")) is True


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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_admin_roster_text,
    )

    assert build_admin_roster_text(_roster_config()) == ""


def test_roster_profile_super_role_line() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_admin_roster_text,
    )

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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_admin_roster_text,
    )

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
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_admin_roster_text,
    )

    text = build_admin_roster_text(_roster_config(super_ids=["888", "999"]))
    assert "超级管理员 QQ" in text
    assert "888" in text
    assert "999" in text
    assert "888、999" in text
