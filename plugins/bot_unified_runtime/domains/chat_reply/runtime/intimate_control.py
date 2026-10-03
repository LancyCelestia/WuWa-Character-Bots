"""`/bot intimate` 命令面（席 S6，2026-10-08 波）：子命令 → 唯一生效出口 / 只读查询 / 用法。

本模块**只做分诊与行文**，生效链一条都不重造：

- 参数解析＝`content_route.match_intimate_subcommand`（`on/open/l1`→浅档、`deep/deeper/l2`→深档、
  `off/close/unset`→解除；认不出 None，`show` 也 None）；
- 上钉与回执＝`capabilities.chat.apply_intimate_switch`——亲密开关的**唯一生效出口**
  （作用域键→来源→上钉→选确认话→scope 审计标签→隐私档，五步一体）。本模块只调它，
  **绝不在旁边再写一套上钉逻辑**，确认话逐字由它给
  （`tests/test_intimate_slash_command.py` 末段一枚 AST 锁盯着这件事）；
- 档位/来源读数＝`content_route.resolve_intimate_context`（注入缝与路由双门同源）；
  五维叙述那一格＝`content_route.grants_intimate_narration`（判据只在那一处）。

分诊口径照 `match_intimate_subcommand` 的 docstring 执行，三条腿互不吞：
① 先取开关口，非 None 走开关腿；② 返回 None 后再自己认一次 `show` 走查询腿
（`show` 是只读——给它任何 `(mode, tier)` 都等于"看一眼顺手把档位改了"）；
③ 两条都不中才回"不认得"，并把用户原话回给他。

裸命令（无参数）必须自己交出「用法 + 当前档 + 指路一行」：今天裸 `/bot intimate` 是靠
`_handle_status` 那串 elif 全落空后经 `bot.help` → `_HELP_ALIAS_MAP["intimate"]` 出帮助页的；
接线新增的那支 elif 会把这条旧行为顶掉，不补就是一次**静默回归**。

两条行文红线（用户裁定）：
① `source` 那串内部码（`manual_command`/`admin_pin`/…）**绝不外端**——一律过本模块的人话
   映射表，全文不提模型名/路由/阈值；认不出的码**带着原码说话**，不硬套标签
   （先例 `capabilities/group_info.py` 的 `_QQ_STATUS_LABELS` 与 `_qq_status_label`）。
② 长度**只报档名（简洁/适中/详尽）、不报字数区间**；且生效档必须走 `chat.py` 那条
   **四层优先级链**（运行时覆盖→该人永久策略→`BOT_REPLY_DETAIL`→auto）——
   只读 `config.bot_reply_detail` 会对钉过「短一点」的人谎报「详尽」。

「还剩多久自动退出」这一格**本波不做**：要它就得给引擎加一枚公开只读方法，
牵动 `tests/test_content_route_threading.py` 的公开状态方法名册——那是另一波的账。

能力 id 复用 `bot.chat`（`bot.intimate` 有意不存在：铸新 id 要同改
`capability_protocols` 唯一在册表 + `CONTROLLED_INTERNAL_CAPABILITIES` +
`test_capability_manifest_gate` 那本"只准降缺口"的账）；可分辨性全部交给 `audit_tags`。

本模块不导入 NoneBot、不碰网络；全离线可单测。
"""
from __future__ import annotations

from typing import Any, Final

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    ContextBundle,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    REPLY_LENGTH_TIERS,
    apply_intimate_switch,
    intimate_reply_length_tier,
    normalize_reply_detail_mode,
    resolve_reply_length_tier,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    LENGTH_MODE_AUTO,
    person_reply_policy_key,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_SOURCE_ADMIN_PIN,
    INTIMATE_SOURCE_AFFINITY,
    INTIMATE_SOURCE_CONTENT_SIGNAL,
    INTIMATE_SOURCE_MANUAL,
    INTIMATE_SOURCE_MASTER_LOVE,
    INTIMATE_SOURCE_NONE,
    INTIMATE_TIER_L1,
    INTIMATE_TIER_L2,
    INTIMATE_TIER_NONE,
    MODE_INTIMATE,
    MODE_NORMAL,
    SHARED_CONTENT_ROUTE_ENGINE,
    grants_intimate_narration,
    match_intimate_subcommand,
    resolve_intimate_context,
)

#: 帮助页指路行：裸命令与"不认得"两支都附在末尾，替被新 elif 顶掉的那条旧 help 兜底。
#: 字面量只落这一处，调用方（含测试）一律引这个名字。
INTIMATE_HELP_POINTER: Final[str] = "/bot help 亲密模式"

#: 只读查询那枚子命令的词面。它**不在** `content_route` 的开关词表里（给了 (mode, tier)
#: 就等于顺手改档），所以它的真身只能住在命令面这一格——全仓第二处也不许再抄它。
SHOW_SUBCOMMAND: Final[str] = "show"

#: 开关腿没被受理（总闸关／会话没准入／群里普通成员但 per_user 关）时的回执。
#: 这一句是**命令面独有**的：整句面那三格是"落回普通聊天"，命令面没有正文可落回。
REFUSED_REPLY: Final[str] = "这一处我动不了那一档——不是你说错了，是这里还没放开。"

# ---------------------------------------------------------------- 人话映射表

#: 档位来源码 → 人话。键引 `INTIMATE_SOURCE_*` 常量（**不重抄码串**，那会被词面级
#: 独立声明账记成第二处声明位，也会与引擎的来源真身分叉）；值只谈"谁开的"，
#: 一个字都不碰模型名/路由/阈值。
_SOURCE_LABELS: dict[str, str] = {
    INTIMATE_SOURCE_NONE: "还没开过",
    INTIMATE_SOURCE_MANUAL: "你自己开过一句",
    INTIMATE_SOURCE_ADMIN_PIN: "管理员替这一群开的",
    INTIMATE_SOURCE_MASTER_LOVE: "在册名单自动给的",
    INTIMATE_SOURCE_CONTENT_SIGNAL: "这几句话自己带进来的",
    INTIMATE_SOURCE_AFFINITY: "处着处着自然到的",
}

_MODE_LABELS: dict[str, str] = {
    MODE_INTIMATE: "亲密档",
    MODE_NORMAL: "普通档",
}

_TIER_LABELS: dict[str, str] = {
    INTIMATE_TIER_NONE: "没进档",
    INTIMATE_TIER_L1: "浅档",
    INTIMATE_TIER_L2: "深档",
}

#: 用法表：裸命令与"不认得"两支共用，四枚子命令一名不遗漏。
_USAGE_LINES: Final[tuple[str, ...]] = (
    "亲密模式（/bot intimate）的子命令：",
    "  on    换一种更贴近你的方式聊（讲法不改）",
    "  deep  再放开一层，你说什么我都接着",
    "  off   回到平时这样聊（深浅一起放下）",
    "  show  只看现在是什么档，什么都不改",
    "  不带子命令＝看这份用法加当前档位。",
)


def _label(table: dict[str, str], code: str) -> str:
    """码 → 人话；**认不出就带着原码说话**，不硬套一个标签。

    照 `group_info._qq_status_label` 的先例：宁可少说，也不把没登记过的码糊成某个
    在册说法——那会让读的人以为那是权威口径。
    """
    key = str(code or "").strip()
    hit = table.get(key)
    if hit:
        return hit
    if not key:
        return "还没开过"
    return f"{key}（这本册子没给中文名，不替你猜）"


def _tier_phrase(mode: str, tier: str) -> str:
    """档位那一格：普通档只说普通档，亲密档才带深浅。"""
    if str(mode or "").strip() != MODE_INTIMATE:
        return _label(_MODE_LABELS, mode)
    return f"{_label(_MODE_LABELS, mode)}·{_label(_TIER_LABELS, tier)}"


def _switch_verb(mode: str, tier: str) -> str:
    """审计标签里那枚子命令类别（on/deep/off）——只用于记账，不参与任何判定。

    生效与确认话全在 `apply_intimate_switch` 里；深浅之外的形态一律归 off，
    因为解除腿本来就是"两档一起放下"。
    """
    if str(mode or "").strip() != MODE_INTIMATE:
        return "off"
    return "deep" if str(tier or "").strip() == INTIMATE_TIER_L2 else "on"


def _scope_reading(source: str, session_type: str) -> tuple[str, str]:
    """作用域那一格 + 同源的 scope 审计标签。

    读数**只引引擎已经交回的 `source`**（`resolve_intimate_context` 转述
    `_SessionState.pin_source` 那一格），本函数不再判一次"这一档挂在谁身上"——
    管理员钉＝全群，其余在册来源在群里＝只本人，私聊/控制台＝这段对话。
    标签串与 `apply_intimate_switch` 自己打的那枚逐字同形（scope:group / scope:user /
    scope:self），两条腿打出的 scope 因此可以并排对账。
    """
    code = str(source or "").strip()
    if code == INTIMATE_SOURCE_ADMIN_PIN:
        return ("全群共享那一档", "scope:group")
    if not code:
        return ("还没人拨过这一档", "scope:none")
    if str(session_type or "") == "group":
        return ("只你自己", "scope:user")
    return ("只这段对话", "scope:self")


def _person_length_mode(config: Any, sender_id: str, session_key: str) -> str:
    """四层链的层②：这个人钉过的永久长度档。

    没钉过／读不出／策略总闸关 ⇒ 交回空串＝**不表态**，绝不拿一份读失败的 None 去替
    这个人编一个档位出来（台账 #67★同族：读库失败≠没有既有行）。store 走
    `shared_reply_policy_store` 那张进程级单例口（与聊天主链同一个口，本模块不建库、
    不解析路径、不改写任何一行）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
        shared_reply_policy_store,
    )

    person_key = person_reply_policy_key(sender_id=sender_id, session_id=session_key)
    if not person_key:
        return ""
    try:
        store = shared_reply_policy_store(config)
        if store is None:
            return ""
        row, readable = store.read_policy(person_key)
        if not readable or row is None or row.length_mode == LENGTH_MODE_AUTO:
            return ""
        return str(row.length_mode)
    except Exception:  # noqa: BLE001 - 读不到就是不表态。
        return ""


def _length_label(detail_mode: str, *, in_intimate: bool) -> str:
    """生效长度档的**人话档名**（简洁/适中/详尽）——只报档名，区间一个数字都不抄。

    取档与升格全走既有单源助手：`resolve_reply_length_tier` / `intimate_reply_length_tier`
    （裁定两度：2026-09-28 立「亲密档字数比普通档多」，2026-10-04 改为「拿到叙述授予的
    那一轮直取顶格档」）/ `REPLY_LENGTH_TIERS` 登记表——数值与档名的唯一真身。
    登记表里查不到那一档时宁可说「没读到」，不猜一档。
    """
    tier_id = (
        intimate_reply_length_tier(detail_mode)
        if in_intimate
        else resolve_reply_length_tier(detail_mode)
    )
    tier = REPLY_LENGTH_TIERS.get(str(tier_id or ""))
    return tier.label_cn if tier is not None else "没读到"


def _effective_detail_mode(
    config: Any, runtime_settings: Any, sender_id: str, session_key: str
) -> str:
    """详略「模式」的四层优先级链——次序与 `chat.py` 装配段那条一字不差：

    ① 运行时覆盖（`/bot reply 精简` 那类热改）→ ② 该人永久策略 →
    ③ `BOT_REPLY_DETAIL` → ④ auto。层①在场时层②让路，这是原链的规矩，
    这里照抄、不自行放宽——少读一层就是对钉过「短一点」的人谎报「详尽」。
    """
    base_mode = normalize_reply_detail_mode(getattr(config, "bot_reply_detail", "auto"))
    detail_mode = base_mode
    layer_one_hit = False
    get_or = getattr(runtime_settings, "get_or", None)
    if callable(get_or):
        detail_mode = normalize_reply_detail_mode(get_or("BOT_REPLY_DETAIL", base_mode))
        layer_one_hit = get_or("BOT_REPLY_DETAIL", None) is not None
    if not layer_one_hit:
        person_mode = _person_length_mode(config, sender_id, session_key)
        if person_mode:
            detail_mode = normalize_reply_detail_mode(person_mode)
    return detail_mode


def _privacy_carrier(request_id: str, privacy: PrivacyLevel) -> ContextBundle:
    """只带隐私档那一格的 ContextBundle。

    命令面拿不到装配期上下文，而 `apply_intimate_switch` 对 context 的唯一取用就是
    `context.privacy_level`（D1 事故那一格：群作用域 + PERSONAL 正文被审核判
    move_private，群里看着就是"开关不可用"）。这里交的是**调用方递进来的会话隐私档**
    （`__init__.py` 那支 elif 从 `message.privacy_level` 递进来），本模块不另判一次；
    上下文其余分区一个都不伪造，所以走 pydantic 的部分构造而不是编一份假档案。
    """
    return ContextBundle.model_construct(request_id=request_id, privacy_level=privacy)


def _text_result(
    request_id: str, body: str, tags: list[str], privacy: PrivacyLevel
) -> CapabilityResult:
    """用法／不认得／不受理三支共用的回执装配（开关腿不走这里，走唯一生效出口）。"""
    return CapabilityResult(
        request_id=request_id,
        capability_id="bot.chat",
        kind="text",
        body=body,
        risk_level=RiskLevel.LOW,
        privacy_level=privacy,
        audit_tags=tags,
    )


def _state_body(
    ctx: dict[str, Any],
    config: Any,
    runtime_settings: Any,
    *,
    sender_id: str,
    session_key: str,
    session_type: str,
) -> list[str]:
    """当前档位读数（裸命令与 show 共用同一份行文，不留两套说法）。"""
    mode = str(ctx.get("mode") or MODE_NORMAL)
    tier = str(ctx.get("tier") or INTIMATE_TIER_NONE)
    source = str(ctx.get("source") or INTIMATE_SOURCE_NONE)
    scope_phrase, _scope_tag = _scope_reading(source, session_type)
    detail_mode = _effective_detail_mode(config, runtime_settings, sender_id, session_key)
    return [
        f"当前档位：{_tier_phrase(mode, tier)}",
        f"谁开的：{_label(_SOURCE_LABELS, source)}",
        f"细节描写：{'已开' if grants_intimate_narration(source) else '没开'}",
        f"详略：{_length_label(detail_mode, in_intimate=mode == MODE_INTIMATE)}",
        f"作用域：{scope_phrase}",
        f"这一处准进：{'是' if ctx.get('eligible') else '否'}",
    ]


def build_intimate_control_result(
    *,
    config: Any,
    request_id: str,
    subcommand: str,
    session_type: str,
    session_key: str,
    sender_id: str = "",
    group_id: str = "",
    sender_roles: list[str] | tuple[str, ...] | None = None,
    privacy_level: PrivacyLevel | None = None,
    runtime_settings: Any = None,
) -> CapabilityResult:
    """/bot intimate 的三腿分诊口：开关 → 只读查询 → 用法（都不中才回"不认得"）。

    `subcommand` **必须是已剥掉 `/bot intimate` 前缀**后剩下的参数串（前缀归命令面，
    与 `match_intimate_subcommand` 同一口径）。`privacy_level` 交**会话自己的隐私档**
    （接线侧取 `IncomingMessage.privacy_level`，那一格由中央件
    `default_privacy_by_session` 按会话类型夹好）；缺席时才按会话类型回落一次，
    与那条 validator 同形——本模块不另立第三套隐私判据。返回值永远是 `CapabilityResult`：
    命令面没有"落回普通聊天"这条路，所以不受理那一格也必须有话说。

    全程 fail-open：任何一步读不出来都收在"不表态"那一侧，绝不少数报一个档位、
    也绝不因为查询失败去动钉。
    """
    resolved_privacy = privacy_level or (
        PrivacyLevel.GROUP if str(session_type or "") == "group" else PrivacyLevel.PERSONAL
    )
    raw = str(subcommand or "").strip()
    parsed = match_intimate_subcommand(raw)
    ctx = resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type=session_type,
        group_id=group_id,
        sender_id=sender_id,
        session_key=session_key,
        config=config,
    )
    route_key = str(ctx.get("route_key") or session_key or "")
    per_user_enabled = bool(
        getattr(config, "bot_content_route_group_per_user_enabled", True)
    )
    if parsed is not None:
        mode, tier = parsed
        verb = _switch_verb(mode, tier)
        tags = ["content_route", "slash_intimate", f"slash_intimate:{verb}"]
        engine_on = bool(getattr(config, "bot_content_route_enabled", False))
        if not (engine_on and bool(ctx.get("eligible"))):
            # 与整句面同一格：总闸关或会话没准入时那一腿根本不上钉，这里同样不动钉。
            return _text_result(
                request_id,
                f"{REFUSED_REPLY}\n{INTIMATE_HELP_POINTER}",
                [*tags, "scope:none", "slash_intimate_refused"],
                resolved_privacy,
            )
        switched = apply_intimate_switch(
            mode=mode,
            tier=tier,
            session_type=session_type,
            session_key=session_key,
            route_key=route_key,
            sender_roles=sender_roles,
            per_user_enabled=per_user_enabled,
            config=config,
            request_id=request_id,
            context=_privacy_carrier(request_id, resolved_privacy),
        )
        if switched is None:
            fallback_scope = _scope_reading(
                str(ctx.get("source") or INTIMATE_SOURCE_NONE), session_type
            )[1]
            return _text_result(
                request_id,
                f"{REFUSED_REPLY}\n{INTIMATE_HELP_POINTER}",
                [*tags, fallback_scope, "slash_intimate_refused"],
                resolved_privacy,
            )
        return switched.model_copy(
            update={
                "audit_tags": [*(switched.audit_tags or []), f"slash_intimate:{verb}"]
            }
        )
    if raw.lower() == SHOW_SUBCOMMAND:
        lines = _state_body(
            ctx, config, runtime_settings,
            sender_id=sender_id, session_key=session_key, session_type=session_type,
        )
        show_scope_tag = _scope_reading(
            str(ctx.get("source") or INTIMATE_SOURCE_NONE), session_type
        )[1]
        return _text_result(
            request_id,
            "\n".join(lines),
            ["content_route", "slash_intimate", "slash_intimate:show", show_scope_tag],
            resolved_privacy,
        )
    # 裸命令与"不认得"两支：都交「用法 + 当前档 + 指路」，区别只在那一行回不回原话。
    lines = _state_body(
        ctx, config, runtime_settings,
        sender_id=sender_id, session_key=session_key, session_type=session_type,
    )
    head = [] if not raw else [f"没认出这个子命令：{raw}"]
    body = "\n".join([*head, *lines, *_USAGE_LINES, INTIMATE_HELP_POINTER])
    verb = "usage" if not raw else "unknown"
    return _text_result(
        request_id,
        body,
        ["content_route", "slash_intimate", f"slash_intimate:{verb}"],
        resolved_privacy,
    )
