"""S-FIX-ATK-SCHED2 票1（ATK-SCHED 审计票1）：人物身份键唯一构造口回归。

锁两层：
- **单元层**：``core/session_keys.person_scope_key`` 键形矩阵（域隔离、消毒、
  空号 fail-closed、空域独立桶）——新建键形登记进中央件（T-1/T-2 先例），
  任何域内不得再自拼 ``f"{domain}:{uid}"`` 第二形。
- **折算层**：``schedule_board._board_owner_from_roster_id`` 与名单在册口径
  （policy/roles._qualify_entries）同尺：裸号=QQ 原生域、别名前缀归一、
  限定条目同域生效。

全离线，不碰网络/真库/进程。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    PLATFORM_QQ,
    platform_domain_of,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    PERSON_SCOPE_SEP,
    person_scope_key,
    sanitize_key_segment,
)
from plugins.bot_unified_runtime.domains.schedule.capabilities.schedule_board import (
    _board_owner_from_roster_id,
)


class TestPersonScopeKeyShape:
    def test_domain_qualifies_key(self) -> None:
        assert person_scope_key(PLATFORM_QQ, "10001") == "qq:10001"
        assert person_scope_key("telegram", "10001") == "telegram:10001"
        # 同号跨平台必须不同桶——裸号接管的病根就在这一格。
        assert person_scope_key("qq", "10001") != person_scope_key("telegram", "10001")

    def test_unknown_platform_is_separate_fail_closed_bucket(self) -> None:
        # 空域段是独立桶（fail-closed）：域归一在调用侧吃 platform_domain_of
        # （认不出的平台折成 ""），本件只负责把给到的域消毒拼键——两层分开锁。
        assert platform_domain_of("discord") == ""
        assert person_scope_key(platform_domain_of("discord"), "10001") == ":10001"
        assert person_scope_key("", "10001") == ":10001"
        assert person_scope_key(None, "10001") == ":10001"
        assert person_scope_key("", "10001") not in {
            person_scope_key("qq", "10001"),
            person_scope_key("telegram", "10001"),
        }
        # 域段照给到的原样消毒拼键（别名归一是调用方职责，不留第二判据口）。
        assert person_scope_key("discord", "10001") == "discord:10001"

    def test_empty_uid_returns_empty_key(self) -> None:
        # 无主键绝不成立：不给造出 "qq:" 这种可被空号消息认领的桶。
        assert person_scope_key("qq", "") == ""
        assert person_scope_key("qq", None) == ""
        assert person_scope_key("qq", "   ") == ""
        assert person_scope_key("", "") == ""

    def test_hostile_separator_in_uid_is_sanitized(self) -> None:
        # sender_id 塞分隔符伪不出嵌套键（T-2 消毒在构造口内完成）。
        assert person_scope_key("qq", "10001:telegram:2002") == "qq:10001telegram2002"
        key = person_scope_key("qq", "evil::id")
        assert PERSON_SCOPE_SEP not in key[len(PLATFORM_QQ) + 1 :]
        # 域段同样消毒：带冒号的伪造域前缀拆不回两段。
        assert person_scope_key("qq:telegram", "10001") == "qqtelegram:10001"

    def test_separator_constant_matches_roster_qualifier(self) -> None:
        # 键形与管理员名单限定条目（telegram:2002）逐字同构：同一把冒号。
        from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
            ENTRY_SEPARATOR,
        )

        assert PERSON_SCOPE_SEP == ENTRY_SEPARATOR


class TestRosterToBoardKey:
    def test_bare_roster_id_is_qq_native(self) -> None:
        assert _board_owner_from_roster_id("u_super") == person_scope_key("qq", "u_super")

    def test_qualified_entry_same_domain(self) -> None:
        assert _board_owner_from_roster_id("telegram:2002") == "telegram:2002"

    def test_alias_prefix_normalizes_like_roster(self) -> None:
        # roles._qualify_entries 把前缀过 platform_domain_of：别名不造孤儿桶。
        assert _board_owner_from_roster_id("tg:2002") == person_scope_key(
            platform_domain_of("tg"), "2002"
        )
        assert _board_owner_from_roster_id("onebot11:9") == person_scope_key("qq", "9")

    def test_qq_qualified_and_bare_collapse_to_same_key(self) -> None:
        assert _board_owner_from_roster_id("qq:u_super") == _board_owner_from_roster_id(
            "u_super"
        )

    def test_sanitize_key_segment_fixpoint_no_separator(self) -> None:
        # 删后拼接再生成的分隔符也要删净（不动点循环）。
        assert sanitize_key_segment("a::b", forbidden=":") == "ab"
        assert sanitize_key_segment("a:b:c", forbidden=":") == "abc"
