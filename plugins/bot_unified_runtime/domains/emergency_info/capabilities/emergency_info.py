"""紧急信息聚合域能力层（查询 + 待审列表 + 审核裁决的读侧 + 订阅命令面）。

WIRE-SUB（2026-09-20 用户裁定）：投递条件**不落 `.env`**（"太僵硬"），改由群内/私聊
一条命令设立（`紧急信息 订阅 …` / `退订` / `订阅 看`），落 `emergency_subscriptions`
表、投递侧每轮现读 ⇒ 说完当轮生效。这一改动把「显式授权」的载体从配置名单换成了
设立动作本身，`绝不猜群/绝不猜人` 一寸没松：没有目标行就没有投递，目标行只可能由
群主/管理员（或超管在私聊）亲手写下。

命名与仓内多数派对齐（施工图 §4-面0，用户裁 U-4/R-S1 一次定死、禁两名并存）：
谓词 `is_emergency_info_command`、工厂 `build_emergency_info_capability(config, *,
render_backend)`、装配期快照门 `build_emergency_info_source(config)`、能力闭包
`def capability(message, decision) -> CapabilityResult`（真身
`domains/core/contracts/runtime.py`）。能力 id 字面 = `bot.emergency_info`（B11 §7.1）。

**投递面不在本文件**（施工图 §4-面11 / R-S5）：本文件只应答查询；主动投递的唯一
触点在域内 `service/push.py`。因此本文件内既不得出现中央投递触点的字样，也不得
直接构造发送请求——装配期服务 `EmergencyInfoService` 只持有闸句柄并据此判定
「投递面是否可用」（闸缺失 ⇒ 不可用，绝不退化成裸投递，见 §4-面5 高危③）。

三重来源门（§5-钉死②，抄 campus 正例 `domains/assistant/campus/campus.py:58-71`）：
`enabled ∧ sources ∧ (push_group_whitelist ∨ push_user_ids)`，任一不满足 ⇒
快照 `enabled=False` ⇒ 上层整链不注册。**绝不猜群、绝不猜人**：两个投递名单全空
= 关闭，不是全开。审核名单 `reviewer_ids` 不参与装配门（它空 ⇒ 审核面关闭＝安全的
缺省态：链可跑、料可入库，但永远投不出去），单独以 `review_surface_enabled` 暴露。

> **WIRE-SUB 修订（2026-09-20 裁定 3.B，覆盖上段第三腿）**：投递目标改由库里的
> `emergency_subscriptions` 每轮现读派生，装配门缩为 `enabled ∧ sources`。上面那句
> 「名单全空=关闭」因此只适用于**硬推腿**；主路的显式授权载体换成了群内设立动作。

本文件零网络、零 LLM、零 NoneBot：配置一律按名 `getattr` 读取（不 import config
模块，与 `test_domain_kernel_touches_no_config_module` 的 rglob 口径同源）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    SendPolicy,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyStatus,
    build_emergency_item,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import (
    alert_taxonomy as taxonomy,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.review import (
    ReviewGate,
    validate_auto_approve_sources,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.subscriptions import (
    DEFAULT_RADIUS_KM,
    RuleError,
    SubscriptionRule,
    parse_subscription,
    subscription_key,
)

#: 能力 id 字面（B11 §7.1 定名；根面 5c 的 `_run_simple_capability` 同值双钉）。
CAPABILITY_ID = "bot.emergency_info"

# 触发正则=施工图 §4-面0 的**可编译形态**：右边界必须有（G23 的 `emergencyxxx`
# 胶合探针若在裸匹配下会命中，那条门就会红）。文档原文里的 `\b?` 在 Python 3.12
# 是不可编译的（`re.error: nothing to repeat`，实测见 A1 report §诚实缺口），
# 语义上它也只是「可选的词边界」——右边界这件事已由 `(?![A-Za-z0-9])` 承担，
# 故落地形态去掉 `\b?`，判定结果与文档意图逐例一致。
_EMERGENCY_RE = re.compile(
    r"^(紧急信息|緊急信息|预警|預警|地震|震情|待审|emergency)(?![A-Za-z0-9])"
)

# 待审队列的意图词（触发词本身就是 `待审`，这里只补显式后缀形态）。
_PENDING_WORDS = frozenset({"待审", "待審核", "待审列表", "審核", "pending", "review"})
# 余下文本为空/这些词 ⇒ 列表语义；否则按条目 id 走详情。
_LIST_WORDS = frozenset(
    {"", "列表", "清單", "list", "all", "latest", "recent", "最近", "最新", "全部"}
)
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,}")

_MAX_LIST_ROWS = 10

#: 缺省「可击穿静默窗」等级集合＝`contracts.URGENT_LEVELS` 的字面形态（P0/P1）。
#: 缺省值刻意与今天逐字相同：WP3 的族级规则只会**比今天更安静**，不会更吵。
DEFAULT_QUIET_BREACH_LEVELS: frozenset[str] = frozenset({"P0", "P1"})


# ------------------------------------------------------------------ 装配期快照门


@dataclass(frozen=True)
class EmergencyInfoSource:
    """装配门快照：两腿（总闸 ∧ 有源），装配期从 Config 构建、运行期只读（同 campus `:42-51`）。

    投递目标不在此快照里（WIRE-SUB）：那些活在 `emergency_subscriptions` 表里，
    调度每轮现读，所以群里改条件不需要重启。`push_*` 两字段是可选硬推腿的名单。
    """

    enabled: bool
    sources: frozenset[str]
    push_group_whitelist: frozenset[str]
    push_user_ids: frozenset[str]
    reviewer_ids: frozenset[str]
    review_surface_enabled: bool
    min_level: str
    poll_interval_seconds: int
    keep_days: int
    db_path: str
    persona_profile_id: str
    #: D-8(a) 权威源自动过审白名单快照：命中来源的条目入库即 approved。
    #: **空集合＝整机制关闭**（缺省语义不变，人工报料继续 pending，门一寸不松）。
    auto_approve_sources: frozenset[str] = frozenset()
    #: WP3 交付④：白名单里**不是真身 SOURCE_ID** 的取值（已忽略，不静默）。
    #: 只搬不吞——名单在这里看得见，`build_review_gate` 装配期点名告警就靠这一格。
    unknown_auto_approve_sources: tuple[str, ...] = ()
    #: WP3 交付②：允许击穿 00:00–06:00 静默窗的等级（缺省 `P0,P1`＝与今天一致）。
    #: 族级地板（`alert_taxonomy.AlertFamily.wake_levels`）在此之上**再收窄**，
    #: 配成 `P0,P1,P2,P3` 等于关掉本域这层抑制、把窗判定整个交回中央闸。
    quiet_breach_levels: frozenset[str] = DEFAULT_QUIET_BREACH_LEVELS


def _id_list(value: Any) -> list[str]:
    """名单宽容装载：None/数字/空串一律洗成干净字符串列表（campus `:54-55` 同形）。"""
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _level_tokens(value: Any) -> frozenset[str]:
    """`"P0,P1"` / `["p0", "P1"]` → 归一大写字面集合。非法值**原样保留**由消费侧判否。"""
    if isinstance(value, str):
        tokens = re.split(r"[,，;；\s]+", value)
    else:
        tokens = [str(item or "") for item in (value or [])]
    return frozenset(token.strip().upper() for token in tokens if token.strip())


def build_emergency_info_source(config: Any) -> EmergencyInfoSource:
    """从 Config 构建来源门快照；空值安全，任一腿为空即整链关闭。"""
    sources = frozenset(_id_list(getattr(config, "bot_emergency_info_sources", None)))
    groups = frozenset(
        _id_list(getattr(config, "bot_emergency_info_push_group_whitelist", None))
    )
    users = frozenset(
        _id_list(getattr(config, "bot_emergency_info_push_user_ids", None))
    )
    reviewers = frozenset(
        _id_list(getattr(config, "bot_emergency_info_reviewer_ids", None))
    )
    # WP3 交付④（审计 E6-N2）：填成模块名（`nmc_alarm`）而不是真身 SOURCE_ID（`nmc`）
    # 的取值一律**忽略并点名**，与姊妹键 `sources` 的 2.A 先例同口径。合法值唯一来自
    # 注册表镜像 `taxonomy.SOURCE_IDS`（与四个源件 `SOURCE_ID` 常量的逐字相等由 AST 锁钉）。
    requested_auto_approve = frozenset(
        _id_list(getattr(config, "bot_emergency_info_auto_approve_sources", None))
    )
    auto_approve, unknown_auto_approve = validate_auto_approve_sources(
        requested_auto_approve, taxonomy.SOURCE_IDS
    )
    flag = bool(getattr(config, "bot_emergency_info_enabled", False))
    return EmergencyInfoSource(
        # 装配门两腿（WIRE-SUB 修订 2026-09-20 裁定 3.B，覆盖施工图 §5-钉死②第三腿）：
        # 总闸 ∧ 有源 = 链可跑。投递目标由 `emergency_subscriptions` 表**每轮现读**
        # 派生，不再要求 .env 里预填群/人名单——条件写在群里，说完当轮生效。
        # 「绝不猜群/绝不猜人」一寸没松：表里没有行＝一个目标都没有＝一条都不投，
        # 而行只能由群主/管理员（或管理员在私聊）亲手写下。
        # .env 两名单降级为**可选硬推腿**（缺省空=该腿不存在），保留是因为它们已在
        # 生产 .env 里写着，删掉属破坏性变更；要走订阅这条主路不必碰它们。
        enabled=flag and bool(sources),
        sources=sources,
        push_group_whitelist=groups,
        push_user_ids=users,
        reviewer_ids=reviewers,
        review_surface_enabled=bool(reviewers),
        # 值域=EmergencyLevel 字面，但此处**不校验、不建第二套枚举**（D-3）：
        # 非法值由消费侧按缺省处理，装配期只如实搬运。
        min_level=str(getattr(config, "bot_emergency_info_min_level", "") or "").strip(),
        poll_interval_seconds=_positive_int(
            getattr(config, "bot_emergency_info_poll_interval_seconds", None), 300
        ),
        keep_days=_positive_int(getattr(config, "bot_emergency_info_keep_days", None), 90),
        db_path=str(getattr(config, "bot_emergency_info_db_path", "") or "").strip(),
        persona_profile_id=str(
            getattr(config, "bot_persona_profile_id", "default") or "default"
        ),
        auto_approve_sources=auto_approve,
        unknown_auto_approve_sources=unknown_auto_approve,
        quiet_breach_levels=_level_tokens(
            getattr(config, "bot_emergency_info_quiet_breach_levels", "")
        )
        or DEFAULT_QUIET_BREACH_LEVELS,
    )


def matches_emergency_push_group(source: EmergencyInfoSource, group_id: str) -> bool:
    """群投递腿判定；白名单含 `*` 显式放行全部群（campus `:74-82` 同形）。"""
    if not source.enabled or not source.push_group_whitelist:
        return False
    if "*" in source.push_group_whitelist:
        return True
    return str(group_id or "").strip() in source.push_group_whitelist


def matches_emergency_push_user(source: EmergencyInfoSource, user_id: str) -> bool:
    """私聊投递腿判定：名单空 ⇒ 一律不投（绝不猜人）。"""
    if not source.enabled or not source.push_user_ids:
        return False
    return str(user_id or "").strip() in source.push_user_ids


def allows_emergency_review(
    source: EmergencyInfoSource,
    sender_id: str,
    roles: Any = (),
) -> bool:
    """审核面判定：名单空＝整面关闭；管理员/超管角色是额外放行腿。"""
    if not source.review_surface_enabled:
        return False
    identity = str(sender_id or "").strip()
    if identity and identity in source.reviewer_ids:
        return True
    return any(str(role) in {"admin", "super_admin"} for role in (roles or ()))


def build_review_gate(store: Any, source: EmergencyInfoSource) -> ReviewGate:
    """装配期 ReviewGate 的唯一构造口（WIRE-L2：两枚旋钮一律从快照同源搬运）。

    R2 评审席实测教训：`ReviewGate(store)` 裸构造 = `authorizer` 与
    `auto_approve_sources` 双双落空——权威源自动过审（D-8(a)）整体不生效、
    人工过审也因 `authorizer_not_configured` 而全拒。故本域内一切 ReviewGate
    实例（根装配注入、服务内联缺省、能力层待审读侧）都必须经本函数出闸。

    - `authorizer`：`reviewer_ids` 名单成员制（名单空 ⇒ 对任何人一律 False，
      即根装配注释「无授权人 ⇒ 过审一律拒」的刻意的安全缺省态）。
      authorizer 签名只有 reviewer_id 一个字符串，拿不到角色面，因此管理
      admin/super_admin 的额外放行腿只存在于读侧（本文件
      `allows_emergency_review` 的 roles 参数），裁决面以显式名单为真相源。
    - `auto_approve_sources`：D-8(a) 白名单快照。**缺省空 = 整机制关闭**
      （一切照旧 pending），与「白名单空绝不猜群」同向。
    - WP3 交付④：名单里被 `build_emergency_info_source` 判为**非真身 SOURCE_ID** 的
      取值已在这里点名后忽略（不再静默不命中）。告警落 `logging`——装配期一次，
      与根装配对 `sources` 键的 2.A 先例同形态。
    """
    if source.unknown_auto_approve_sources:
        logging.getLogger(__name__).warning(
            "紧急信息 auto_approve_sources 含未注册的 SOURCE_ID（已忽略，不会自动过审）：%s；"
            "合法值只有：%s",
            ",".join(source.unknown_auto_approve_sources),
            ",".join(sorted(taxonomy.SOURCE_IDS)),
        )
    return ReviewGate(
        store,
        authorizer=lambda reviewer_id: allows_emergency_review(source, reviewer_id),
        auto_approve_sources=source.auto_approve_sources,
    )


# ------------------------------------------------------------------ 查询与展示


def is_emergency_info_command(text: str) -> bool:
    """本域触发谓词（路由侧与能力侧共用同一份正则，禁第二份表）。"""
    return _EMERGENCY_RE.match(str(text or "").strip()) is not None


def _moment(item: EmergencyItem) -> str:
    try:
        return item.occurred_at.strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):  # pragma: no cover - 极端平台时钟
        return ""


def _category_tag(item: EmergencyItem) -> str:
    """条目所属种类的人话标签（注册表唯一出处）；没认出来＝空串，不写"未知类别"凑数。"""
    category_id = taxonomy.category_of_item(item)
    return taxonomy.label_of(category_id) if category_id else ""


def format_emergency_line(item: EmergencyItem) -> str:
    """列表行：条目号 + 标题 + 颜色文案 + 发生时间（未定级不冒充等级，D-1）。"""
    color = item.color_text
    level = color or "未定级"
    kind = _category_tag(item)
    stamp = _moment(item)
    tail = f"｜{stamp}" if stamp else ""
    middle = f"｜{kind}" if kind else ""
    return f"- [{item.item_id}] {item.title}｜{level}{middle}{tail}"


def format_emergency_detail(item: EmergencyItem) -> str:
    """详情块：只展示契约里确实存在的字段，空值一律不凑数。"""
    kind = _category_tag(item)
    lines = [
        f"条目：{item.item_id}",
        f"标题：{item.title}",
        f"来源：{item.source_id}（{item.source_kind or '未知类型'}）",
        f"状态：{item.status.value}",
        (
            f"等级：{item.level.value if item.level is not None else '未定级'}"
            f"｜颜色：{item.color_text or '无'}"
        ),
    ]
    if kind:
        availability = taxonomy.availability_text(taxonomy.category_of_item(item))
        lines.append(f"种类：{kind}（{availability}）")
    stamp = _moment(item)
    if stamp:
        lines.append(f"发生：{stamp}")
    if item.expires_at is not None:
        lines.append(f"有效至：{item.expires_at.strftime('%Y-%m-%d %H:%M')}")
    if item.body:
        lines.append(item.body)
    if item.url:
        lines.append(f"链接：{item.url}")
    return "\n".join(lines)


# ------------------------------------------------------------------ 订阅命令面（WIRE-SUB）


_SUBSCRIBE_WORDS = frozenset({"订阅", "訂閱", "subscribe"})
_UNSUBSCRIBE_WORDS = frozenset({"退订", "退訂", "unsubscribe"})
_VIEW_WORDS = frozenset(
    {"看", "看看", "查看", "当前", "详情", "詳情", "状态", "狀態", "view", "current", "status"}
)
_GROUP_SESSION_RE = re.compile(r"^group_(\d+)_\d+$")

#: 地名→坐标的注入缝（跨域取数只在装配层做，能力层零 IO）。
CoordinateResolver = Callable[[str], "tuple[float, float] | None"]

_USAGE_HINT = (
    "用法示例：「紧急信息 订阅 area=湘潭 kinds=暴雨 橙色以上」，"
    "参数式也可：「area=湘潭 levels=P0,P1 radius=150」；只看某类警情就只写 kinds。"
)


def subscription_target(message: Any) -> tuple[str, str]:
    """这条消息该订给谁：群内=本群号，私聊=发送者本人号。

    目标**只认事件自带的事实**，绝不从文本里读群号/QQ 号——那正是「猜群猜人」
    的老路（钉死②在本域的延续，只是名单从 .env 搬进了库里）。
    """
    group_id = str(getattr(message, "group_id", "") or "").strip()
    if group_id:
        return ("group", group_id)
    session = str(getattr(message, "session_id", "") or "").strip()
    hit = _GROUP_SESSION_RE.match(session)
    if hit:
        return ("group", hit.group(1))
    return ("private", str(getattr(message, "sender_id", "") or "").strip())


#: 现役投递通道的唯一在仓事实：紧急域（及 campus/摘要/日常助理各推送族）的目标构造
#: 只认 QQ 号，`EmergencyTarget.channel` 缺省 `"qq"`。别的平台上收下的号若一并存进
#: 订阅表，投递时会拿 TG 用户号去查 QQ 群/号——同号不同平台是**误投**，不是失败。
SUPPORTED_SUBSCRIPTION_PLATFORMS = frozenset({"qq"})


def subscription_platform_supported(message: Any) -> bool:
    return (
        str(getattr(message, "platform", "") or "").strip().lower()
        in SUPPORTED_SUBSCRIPTION_PLATFORMS
    )


def allows_emergency_subscription(message: Any, scope: str) -> bool:
    """裁定 2（2026-09-20）：能设/退订阅的＝超级管理员 ∨ 管理员 ∨ **本群群主**。

    群主这条腿走 `sender_platform_role`（OneBot `sender.role`，填充真身
    `__init__.py:1462`）。契约注释写着「平台角色只作上下文、权限由 RoleSettings
    定」，那是针对*聊天人格*的口径；而「什么东西允许往这个群里推」的正当授权人
    本来就是群主，故本席刻意开这一条腿，并且**只在 scope=group 时生效**
    （私聊没有群主可言，不能让一个群里当过家主的人在私聊里自封权限）。
    """
    roles = [str(role) for role in (getattr(message, "sender_roles", ()) or ())]
    if any(role in {"admin", "super_admin"} for role in roles):
        return True
    if scope != "group":
        return False
    return str(getattr(message, "sender_platform_role", "") or "").strip().lower() == "owner"


def subscription_subcommand(remainder: str) -> tuple[str, str] | None:
    """`订阅 暴雨 橙色以上` / `退订` → (动作, 参数)；不是订阅动作返回 None。

    「订阅」后面不接条件＝**查看**而不是订全部：裸一个动词就订下无过滤的全量推送，
    是用户手滑能造成的最大噪声，宁可让他再说一句。
    """
    head, _, rest = str(remainder or "").strip().partition(" ")
    rest = rest.strip()
    if head in _UNSUBSCRIBE_WORDS:
        return ("cancel", rest)
    if head not in _SUBSCRIBE_WORDS:
        return None
    if not rest or rest in _VIEW_WORDS:
        return ("view", "")
    return ("set", rest)


def _rule_summary(rule: SubscriptionRule | None, *, aged: bool = True) -> str:
    """`aged=True`（查看旧规则）才提"从没命中过"：刚设完就说这话是责备用户。"""
    if rule is None:
        return ""
    line = rule.describe()
    if rule.created_by:
        line += f"（由 {rule.created_by} 设立）"
    if aged and rule.match_count == 0:
        # 「配了但从没生效」是本项目烧过两轮的坑，命中数必须自己开口。
        line += "\n这条至今一次都没命中过——多半是地名不对或警情词拼错了。"
    return line


def run_subscription_command(
    store: Any,
    *,
    scope: str,
    target_id: str,
    sender_id: str = "",
    action: str,
    argument: str = "",
    at: datetime | None = None,
    default_radius_km: float = DEFAULT_RADIUS_KM,
    resolver: CoordinateResolver | None = None,
) -> str:
    """订阅/退订/查看三条动作的落地口，返回给用户看的那句话。

    与投递侧同源的一件事：这里写完**当轮就生效**（投递每轮现读本表），
    不需要重启——否则「群里说一声」这件事就没有意义了。
    """
    key = subscription_key(scope, target_id)
    where = "本群" if scope == "group" else "你"
    if action == "cancel":
        if store.delete_subscription(key):
            return f"已经退掉了，{where}不再收紧急信息推送。"
        return f"{where}本来也没设过紧急信息订阅，没什么可退的。"
    if action == "view":
        summary = _rule_summary(store.get_subscription(key))
        if summary:
            return f"{where}当前的紧急信息订阅：\n{summary}"
        return f"{where}还没有紧急信息订阅。{_USAGE_HINT}"
    try:
        rule = parse_subscription(
            argument,
            target_scope=scope,
            target_id=target_id,
            created_by=sender_id,
            default_radius_km=default_radius_km,
            resolver=resolver,
        )
    except RuleError as exc:
        return f"这条订阅我没收下：{exc}。{_USAGE_HINT}"
    created = store.save_subscription(rule, at=at or datetime.now(timezone.utc))
    verb = "已经记下了" if created else "已经按你说的改好了"
    unsourced = rule.unsourced_terms()
    warning = ""
    if unsourced:
        # WP3 交付①：无源类别不拦用户设立（那是她的判断），但绝不让她以为生效了。
        warning = (
            "\n这几类现在无源（本域四个采集源都供不了："
            + "、".join(unsourced)
            + "）——订阅先记着，源接上之前不会有推送。"
        )
    return f"{verb}，{where}的紧急信息订阅：\n{_rule_summary(rule, aged=False)}{warning}"


# ------------------------------------------------------------------ 装配期服务


class EmergencyInfoService:
    """根面 5b 的装配句柄：持存储/来源快照/中央闸，提供入库与读侧，投递在 push.py。

    `gate` 缺失（None）＝投递面**不可用**（§4-面5 高危③：宁可整链不装配，也不
    退化成不经闸的投递）。本类自身不做投递，只把「能不能投」这件事如实回答出去。
    """

    def __init__(
        self,
        *,
        store: Any,
        source: EmergencyInfoSource,
        gate: Any = None,
        review_gate: ReviewGate | None = None,
    ) -> None:
        self._store = store
        self._source = source
        self._delivery_gate = gate
        # WIRE-L2：内联缺省不再是裸 `ReviewGate(store)`（第二套无名单缺省），
        # 与根装配注入同走 `build_review_gate`——即便注入腿被拆，快照双门仍在。
        self._review_gate = review_gate or build_review_gate(store, source)

    # ---- 只读面 -------------------------------------------------------------

    @property
    def store(self) -> Any:
        return self._store

    @property
    def source(self) -> EmergencyInfoSource:
        return self._source

    @property
    def review_gate(self) -> ReviewGate:
        return self._review_gate

    @property
    def can_deliver(self) -> bool:
        """投递面可用性：闸在位 ∧ 来源门成立，二者缺一律不投。"""
        return self._delivery_gate is not None and self._source.enabled

    def approved_items(
        self, *, limit: int = _MAX_LIST_ROWS, now: datetime | None = None
    ) -> list[EmergencyItem]:
        """读回已过审条目，并**顺手把定级结果回写进库**（WP3 交付③，审计 E6-N3）。

        为什么回写点在这里：根装配 job 每轮只经 `service.approved_items(limit=50)`
        取条目（`__init__.py` 的投递循环），这是「读侧」与「投递侧」唯一同处一时的
        位置——在这里回写，两侧拿到的就是同一个 `grade()` 结果，不再出现
        「库里未定级 / 投出去红色预警」的两副面孔。

        三条不变式：
        - 定级唯一出口仍是 `ReviewGate.publishable_level`（本函数不自建第二套判定），
          所以回写值与 job 随后 `publishable_level(item, now=now)` 的重算值**必然相等**
          （纯函数 + 同一 now）；锁 `test_read_side_writeback_is_the_delivery_side_value`。
        - 幂等：库里已是这个值就不再 UPDATE（每轮 50 条 × 5 分钟一次，不做无谓写盘）。
        - 只回写 `approved` 行（`store.set_level` 的 SQL 守卫）；pending 行永远 NULL，
          D-8「过审才参与定级」一寸不松。
        - `now=None` 才取墙钟，与 `store.prune`/`run_subscription_command` 的
          「时钟可注入、缺省兜底」既有口径同形；job 传自己的 `now`。
        """
        moment = now or datetime.now().astimezone()
        rows = self._store.list_by_status(EmergencyStatus.APPROVED, limit=limit)
        graded: list[EmergencyItem] = []
        for item in rows:
            level = ReviewGate.publishable_level(item, now=moment)
            if level is None:
                graded.append(item)
                continue
            category_id = taxonomy.category_of_item(item)
            if item.level is not level or (item.category_id or "") != category_id:
                self._store.set_level(item.item_id, level=level, category_id=category_id)
            graded.append(item.model_copy(update={"level": level, "category_id": category_id}))
        return graded

    def pending_items(self, *, limit: int = _MAX_LIST_ROWS) -> list[EmergencyItem]:
        return self._review_gate.pending_items(limit=limit)

    # ---- 唯一写路径（经审核门；D-8）----------------------------------------

    def ingest_payloads(
        self,
        payloads: Any,
        *,
        at: datetime | None = None,
    ) -> list[EmergencyItem]:
        """源侧 payload → `build_emergency_item` → `ReviewGate.submit`。

        解析不出必需字段的条目**直接丢弃**（D-1「无源诚实不接」），绝不填假 id
        继续往下走；入库一律 pending（权威源自动过审由 `ReviewGate` 的名单决定）。
        """
        built = [
            item
            for item in (
                build_emergency_item(payload) for payload in (payloads or ())
            )
            if item is not None
        ]
        return [self._review_gate.submit(item, at=at) for item in built]


# ------------------------------------------------------------------ 能力工厂


class _CapabilityWiring:
    """能力闭包的依赖缝：生产由 config 装配，离线测试可直投 `store`。

    工厂签名被施工图钉死（只有 config/render_backend 两个位置），故测试侧的替身
    存储经本对象注入：`build_..._capability(cfg).wiring.store = tmp_store`。
    """

    def __init__(self, config: Any, render_backend: Any) -> None:
        self.config = config
        self.render_backend = render_backend
        self.store: Any | None = None
        #: 地名→坐标解析器：由根装配注入（跨域取数不在本层），None＝只走地名文字。
        self.resolver: CoordinateResolver | None = None
        self._built_store: Any | None = None
        self._store_attempted = False

    def resolve_store(self) -> Any | None:
        """存储解析：只有配置显式给了路径才建库（否则一律「未启用」，零落盘）。"""
        if self.store is not None:
            return self.store
        if self._store_attempted:
            return self._built_store
        self._store_attempted = True
        db_path = str(
            getattr(self.config, "bot_emergency_info_db_path", "") or ""
        ).strip()
        if db_path:
            from plugins.bot_unified_runtime.domains.emergency_info.sources.store import (
                build_emergency_store,
            )

            self._built_store = build_emergency_store(db_path)
        return self._built_store


def build_emergency_info_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any:
    """构建紧急信息查询能力：与 weather/notes 一致，(message, decision) → 结果。"""
    wiring = _CapabilityWiring(config, render_backend)

    def capability(message: IncomingMessage, _decision: Any = None) -> CapabilityResult:
        text = (getattr(message, "plain_text", "") or "").strip()

        def _answer(body: str, *tags: str) -> CapabilityResult:
            return CapabilityResult(
                request_id=str(getattr(message, "request_id", "") or ""),
                capability_id=CAPABILITY_ID,
                kind="text",
                title="",
                body=body,
                send_policy=SendPolicy.IMMEDIATE,
                privacy_level=PrivacyLevel.PERSONAL,
                audit_tags=["emergency_info", *tags],
            )

        match = _EMERGENCY_RE.match(text)
        if match is None:
            return _answer(
                "要看紧急信息的话，直接说「紧急信息」「预警」或「待审」就好。",
                "no_trigger",
            )

        store = wiring.resolve_store()
        if store is None:
            return _answer(
                "紧急信息能力当前未启用（未配置存储，或总开关未打开）。",
                "not_configured",
            )

        remainder = text[match.end() :].strip()
        lowered = remainder.lower()

        # 订阅面（WIRE-SUB）：条件写在群里而不是 .env 里，写完当轮生效。
        subcommand = subscription_subcommand(remainder)
        if subcommand is not None:
            action, argument = subcommand
            if not subscription_platform_supported(message):
                return _answer(
                    "订阅目前只能在 QQ 这边设——紧急信息的投递通道只有这一条，"
                    "别处记下的号码我送不到。",
                    "subscription_unsupported_platform",
                )
            scope, target_id = subscription_target(message)
            if not target_id:
                return _answer(
                    "认不出这条要订给谁，所以没有记下来。", "subscription_no_target"
                )
            if not allows_emergency_subscription(message, scope):
                return _answer(
                    "订阅条件要由群主或管理员来设，我这边不能替谁做主。"
                    "需要的话请让群里管事的人说一句。",
                    "subscription_denied",
                )
            body = run_subscription_command(
                store,
                scope=scope,
                target_id=target_id,
                sender_id=str(getattr(message, "sender_id", "") or ""),
                action=action,
                argument=argument,
                resolver=wiring.resolver,
            )
            return _answer(body, "subscription", action)

        # 待审队列＝审核读侧：非审核人（含审核名单空的缺省态）一律读不到内容。
        if (
            match.group(1) == "待审"
            or lowered in _PENDING_WORDS
            or lowered.split(" ")[0] in _PENDING_WORDS
        ):
            source = build_emergency_info_source(config)
            if not allows_emergency_review(
                source,
                str(getattr(message, "sender_id", "") or ""),
                getattr(message, "sender_roles", ()) or (),
            ):
                return _answer(
                    "待审队列只对紧急信息审核人开放——需要的话请让管理员把你加进审核名单。",
                    "pending_denied",
                )
            rows = build_review_gate(store, source).pending_items(
                limit=_MAX_LIST_ROWS
            )
            if not rows:
                return _answer("待审队列是空的，目前没有等裁决的报料。", "pending_empty")
            listing = "\n".join(
                f"- [{item.item_id}] {item.title}｜{item.source_id}｜{_moment(item) or '时间未知'}"
                for item in rows
            )
            return _answer(
                f"待审 {len(rows)} 条（新→旧）：\n{listing}", "pending_list"
            )

        # 详情：余下文本里找得到一个像 id 的 token 就走单条读侧（管理员裁决入口的读侧）。
        wanted = "" if lowered in _LIST_WORDS else next(
            (token.group(0) for token in _ID_RE.finditer(remainder)), ""
        )
        if wanted:
            item = store.get(wanted)
            if item is None:
                return _answer(f"未找到条目 {wanted}（可能已过期清理，或编号有误）。", "detail_miss")
            return _answer(format_emergency_detail(item), "detail", item.item_id)

        rows = store.list_by_status(EmergencyStatus.APPROVED, limit=_MAX_LIST_ROWS)
        if not rows:
            return _answer(
                "暂无已核准的紧急信息。未过审的报料不会出现在这里。", "list_empty"
            )
        listing = "\n".join(format_emergency_line(item) for item in rows)
        return _answer(
            f"已核准 {len(rows)} 条紧急信息（新→旧）：\n{listing}", "list"
        )

    capability.wiring = wiring  # type: ignore[attr-defined]
    return capability


__all__ = [
    "CAPABILITY_ID",
    "DEFAULT_QUIET_BREACH_LEVELS",
    "EmergencyInfoService",
    "EmergencyInfoSource",
    "allows_emergency_review",
    "allows_emergency_subscription",
    "build_emergency_info_capability",
    "build_emergency_info_source",
    "build_review_gate",
    "format_emergency_detail",
    "format_emergency_line",
    "is_emergency_info_command",
    "matches_emergency_push_group",
    "matches_emergency_push_user",
    "run_subscription_command",
    "subscription_subcommand",
    "subscription_target",
]
