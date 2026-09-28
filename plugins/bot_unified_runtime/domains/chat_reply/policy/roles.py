from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import IncomingMessage

ROLE_USER = "user"
ROLE_TRUSTED = "trusted"
ROLE_ENTERPRISE = "enterprise"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"
ROLE_BLOCKED = "blocked"
ROLE_ORDER = (ROLE_USER, ROLE_TRUSTED, ROLE_ENTERPRISE, ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_BLOCKED)

# --- 平台域（F-A 2026-09-28：管理/超管名单按平台域匹配）--------------------
# 病根：admin 集此前把 QQ 与 Telegram 两份名单并成一集、判定只看 sender_id，
# 于是「TG 用户的数字 user_id 恰等于某枚 QQ 管理员号」（或反向）就跨平台拿到
# 管理员脸（/bot 配置写、邮件控制、群文件与媒体上传）。平台事实本身在契约里就
# 有（``IncomingMessage.platform``，真身填充于根 ``__init__.py`` 摄取层：
# qq / telegram / email），此前判定处没吃这条腿。
PLATFORM_QQ = "qq"
PLATFORM_TELEGRAM = "telegram"
# 名单条目的平台限定分隔符（沿用仓内既有的冒号限定形态，如会话键 email:<id>）。
ENTRY_SEPARATOR = ":"
# 平台写法 → 名单平台域（**唯一声明位**，S-FIX-TRIG-B 2026-09-27 真洗）：本表是
# 以平台写法为键、平台域为值的结构数据（平台域定权的权威表），不是触发词表——
# 词集跨 QQ/Telegram 两域、不是盘上任何一枚触发词真身词集的子集，全仓没有第二处
# 抄它；读侧 ``platform_domain_of`` 整表查值，不再逐域摆第二份字面量词表。
# OneBot/NoneBot 各写法同属 QQ 协议域（真身：入站 platform∈{qq,telegram,email}，
# 合成推送/校园转发用 onebot/nonebot），收进同一域以免既有 QQ 侧行为被字面写法
# 误伤。email/console 等无原生管理名单的域一律落空串＝取不到平台域，管理/超管
# 不放行。
_PLATFORM_ALIASES: Final[dict[str, str]] = {
    "qq": PLATFORM_QQ,
    "onebot": PLATFORM_QQ,
    "onebot v11": PLATFORM_QQ,
    "onebot-v11": PLATFORM_QQ,
    "onebot.v11": PLATFORM_QQ,
    "onebot_v11": PLATFORM_QQ,
    "onebot11": PLATFORM_QQ,
    "nonebot": PLATFORM_QQ,
    "telegram": PLATFORM_TELEGRAM,
    "tg": PLATFORM_TELEGRAM,
}


def platform_domain_of(platform: object) -> str:
    """平台事实 → 名单平台域；取不到或不认识返回 ``""``（fail-closed 的触发值）。"""
    text = str(platform if platform is not None else "").strip().casefold()
    return _PLATFORM_ALIASES.get(text, "")


def _qualify_entries(values: Iterable[object] | None, native_domain: str) -> frozenset[str]:
    """一份配置名单 → 带平台域的条目集（装配口唯一）。

    - 条目自带平台前缀（``telegram:2002``）→ 归一为该形态，只在同域生效；
    - 裸号条目 → 归属**该名单的原生平台**：QQ 名单保持裸号（既有语义显式化，
      只有 QQ 域能吃），Telegram 名单写成 ``telegram:`` 前缀条目；
    - 空条目丢弃。不新建第二张名单：条目仍来自同一批 config 字段。
    """
    entries: set[str] = set()
    for value in values or ():
        entry = str(value).strip()
        if not entry:
            continue
        head, separator, tail = entry.partition(ENTRY_SEPARATOR)
        explicit_domain = platform_domain_of(head) if separator else ""
        if explicit_domain and tail.strip():
            entries.add(f"{explicit_domain}{ENTRY_SEPARATOR}{tail.strip()}")
            continue
        if native_domain == PLATFORM_QQ:
            entries.add(entry)
        else:
            entries.add(f"{native_domain}{ENTRY_SEPARATOR}{entry}")
    return frozenset(entries)


def _roster_hit(roster: frozenset[str], domain: str, sender_id: str) -> bool:
    """平台域内的名单命中判据（管理/超管唯一入口）。

    ``domain`` 为空（缺平台事实 / 平台不认识）或 ``sender_id`` 为空 → 一律
    不命中：取不到就不放行，落回普通用户。裸号条目只在 QQ 域命中；带平台
    前缀的条目只在同域命中。跨平台的同号数字因此无从借另一侧名单提权。
    """
    if not domain or not sender_id:
        return False
    if f"{domain}{ENTRY_SEPARATOR}{sender_id}" in roster:
        return True
    return domain == PLATFORM_QQ and sender_id in roster


@dataclass(frozen=True)
class RoleSettings:
    admin_user_ids: frozenset[str]
    enterprise_user_ids: frozenset[str]
    trusted_user_ids: frozenset[str]
    blocked_user_ids: frozenset[str]
    super_admin_user_ids: frozenset[str] = frozenset()

    def resolve_roles(self, message: IncomingMessage) -> list[str]:
        sender_id = message.sender_id.strip()
        # 平台腿：管理/超管按平台域匹配（F-A）。trusted/enterprise/blocked
        # 维持既有纯 sender_id 语义——本席只修管理面跨平台提权，不扩判据面；
        # blocked 域盲区是收权方向（fail-safe），不在缺陷面上。
        domain = platform_domain_of(getattr(message, "platform", ""))
        roles = {ROLE_USER}
        if sender_id in self.trusted_user_ids:
            roles.add(ROLE_TRUSTED)
        if sender_id in self.enterprise_user_ids:
            roles.add(ROLE_ENTERPRISE)
        # 超管自动叠加 admin 角色：既有 admin 判定点（runtime_admin/pipeline
        # 私聊管理门等）无需逐一感知超管的存在。
        if _roster_hit(self.super_admin_user_ids, domain, sender_id):
            roles.add(ROLE_SUPER_ADMIN)
            roles.add(ROLE_ADMIN)
        if _roster_hit(self.admin_user_ids, domain, sender_id):
            roles.add(ROLE_ADMIN)
        if sender_id in self.blocked_user_ids:
            roles.add(ROLE_BLOCKED)
        return [role for role in ROLE_ORDER if role in roles]

    def counts(self) -> dict[str, int]:
        return {
            ROLE_ADMIN: len(self.admin_user_ids),
            ROLE_SUPER_ADMIN: len(self.super_admin_user_ids),
            ROLE_ENTERPRISE: len(self.enterprise_user_ids),
            ROLE_TRUSTED: len(self.trusted_user_ids),
            ROLE_BLOCKED: len(self.blocked_user_ids),
        }


def build_role_settings(config: Config) -> RoleSettings:
    # 两份管理名单**不再并成一集**（F-A 真身）：QQ 名单按 QQ 域装配、Telegram
    # 名单按 telegram 域装配，条目形态仍来自同一批 config 字段（未新建名单、
    # 未加键）。counts() 的 admin 计数与改动前逐枚等值（每枚号仍是一条目）。
    return RoleSettings(
        admin_user_ids=(
            _qualify_entries(config.bot_admin_user_ids, PLATFORM_QQ)
            | _qualify_entries(config.bot_telegram_admin_user_ids, PLATFORM_TELEGRAM)
        ),
        super_admin_user_ids=_qualify_entries(config.bot_super_admin_user_ids, PLATFORM_QQ),
        enterprise_user_ids=frozenset(config.bot_enterprise_user_ids),
        trusted_user_ids=frozenset(config.bot_trusted_user_ids),
        blocked_user_ids=frozenset(config.bot_blocked_user_ids),
    )


def is_admin_message(config: object, message: IncomingMessage) -> bool:
    """管理面旁路复用口（F-A 残留 2026-09-28）：按 (平台域, sender_id) 判管理名单。

    旁路点（subscribe v1/v2 的 ``_is_admin`` 第二腿）手里只有鸭子类型的 config
    （字段可缺、可为 ``None``），吃不下 ``build_role_settings`` 的全字段面——本口
    用**同一批中央原语**（``platform_domain_of`` + ``_qualify_entries`` +
    ``_roster_hit``）装配并判定，不重建第二套名单逻辑。语义与
    ``build_role_settings(config).resolve_roles(message)`` 的 admin 腿对齐：
    QQ 裸号只在 QQ 域生效、Telegram 条目只在 telegram 域生效、缺平台事实/
    平台不认识一律不放行（fail-closed）。不含超管自动叠加 admin——那是中央
    ``resolve_roles`` 的角色面，旁路点既有语义本就不吃超管名单。
    """
    domain = platform_domain_of(getattr(message, "platform", ""))
    sender_id = str(getattr(message, "sender_id", "") or "").strip()
    admin_entries = (
        _qualify_entries(getattr(config, "bot_admin_user_ids", None), PLATFORM_QQ)
        | _qualify_entries(
            getattr(config, "bot_telegram_admin_user_ids", None), PLATFORM_TELEGRAM
        )
    )
    return _roster_hit(admin_entries, domain, sender_id)


def role_audit_tags(roles: list[str]) -> list[str]:
    return [f"role:{role}" for role in roles if role != ROLE_USER]
