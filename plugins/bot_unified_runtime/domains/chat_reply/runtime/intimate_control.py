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
  🔴 判据一枚 ≠ 问法一枚：`chat.py` 交出两枚**取量口** `narration_ruler_source`
  （叙述轴，答"这一轮能不能铺开写"）与 `intimate_axis_source`（亲密轴，答"这档是谁
  推上去的"），本模块**凡是「细节描写」那一格只准问前者**（席 na-showalign，独立复查 B-4）。

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
    intimate_axis_source,
    intimate_reply_length_tier,
    narration_ruler_source,
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
    INTIMATE_SOURCE_NARRATION_PIN,
    INTIMATE_SOURCE_NONE,
    INTIMATE_TIER_L1,
    INTIMATE_TIER_L2,
    INTIMATE_TIER_NONE,
    MODE_INTIMATE,
    MODE_NORMAL,
    NARRATION_MODE_SCENE,
    NARRATION_MODE_SPEECH,
    SHARED_CONTENT_ROUTE_ENGINE,
    clear_narration_pin,
    grants_intimate_narration,
    match_intimate_subcommand,
    match_narration_subcommand,
    narration_write_allowed,
    read_narration_pin,
    resolve_intimate_context,
    write_narration_pin,
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
    # 描写档那一格的"依据"也走这张表（键是同一族 `INTIMATE_SOURCE_*`，另立一本＝
    # 长第二处映射；这一支永远只出现在 `narration_source` 上，亲密档的来源取不到它，
    # 所以不会互相糊）。
    INTIMATE_SOURCE_NARRATION_PIN: "你自己钉过描写",
}

#: 描写档两格的人话（2026-10-04 裁定 G-1）。键引 `NARRATION_MODE_*` 常量，不重抄码串。
#: 说法刻意**不承诺身形衣着**——普通档 `scene` 写哪几维归样式常量那一席（G-4），
#: 这里只说"说出口之外的部分写不写"，一个字都不替她裁定。
_NARRATION_LABELS: dict[str, str] = {
    NARRATION_MODE_SPEECH: "只说出口的话",
    NARRATION_MODE_SCENE: "连动作神色一起铺开",
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

    ① 本轮明示（这一句刚写进库的说法）→ ② 该人永久策略 → ③ 全局档
    `BOT_REPLY_DETAIL`（**覆盖册里那枚常驻值就在这一层**）→ ④ auto。
    裁定原文（2026-09-28）＝「当轮明示 > 永久策略 > 全局 BOT_REPLY_DETAIL > 缺省」。
    2026-10-04 根修：本函数（与 `chat.py` 同形）曾把「覆盖册里有这枚键」当第①层，
    于是某次 `/bot runtime set` 留下的跨重启常驻值把每一个人的永久策略整段静音——
    报出来的档位与她实际拿到的档位相反，对钉过「短一点」的人就是谎报。
    本轮真说过什么，由 ①② 那条写腿（`resolve_turn_reply_policy`）负责，不在这里判。
    """
    detail_mode = normalize_reply_detail_mode(getattr(config, "bot_reply_detail", "auto"))
    get_or = getattr(runtime_settings, "get_or", None)
    if callable(get_or):
        detail_mode = normalize_reply_detail_mode(get_or("BOT_REPLY_DETAIL", detail_mode))
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


def _narration_grant_line(ctx: dict[str, Any]) -> str:
    """「细节描写」这一格的**唯一渲染口**（两处 `show` 面共用一句，不留第二处字面）。

    读数＝拿**叙述轴**那枚取量口去问唯一那把尺（调用形态只准落在下面那一行）⇒
    `/bot intimate show` 与 `/bot 描写 show` 在同一轮里必然同值（独立复查 B-4 的用户
    可见面：旧写法两句互斥）。字面只落这一处也顺带过了「同源单句」那道门。
    """
    granted = grants_intimate_narration(narration_ruler_source(ctx))
    return f"细节描写：{'已开' if granted else '没开'}"


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
        # 🔴 席 na-showalign（独立复查 B-4／Q4）：这一格从此只按**叙述轴**回答——与
        # `/bot 描写 show` 那一句**同名同问、同一段字面**（旧写法拿亲密轴的 `source` 答
        # "细节描写开没开"，于是同一轮里两句互斥；形状锁
        # `tests/test_narration_axis_show_consistency.py` 钉的就是这一句）。
        _narration_grant_line(ctx),
        # 亲密轴那一问（"这档是谁推上去的"）答的是**另一件事**：样式段第二枚键、
        # 亲密轮的出站动作括号豁免读它（`chat.py` 装配段），它不决定描写档钉没钉。
        # 留在这一格是因为它是真读数、不是那把尺的答案——名字换了，值一个字没动。
        f"亲密档带来的描写：{'已开' if grants_intimate_narration(intimate_axis_source(ctx)) else '没开'}",
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
    platform: str = "",
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
        # 席 na-land 补的第五处（2026-10-05）：亲密面也读描写钉（那一句「细节描写」），
        # 不交平台事实时 `_narration_person_key` 走 fail-closed 支⇒**群里读不到本人的钉**，
        # 于是 `/bot intimate show` 与 `/bot 描写 show` 在群里可以各说各话（同值锁只在
        # 内存钉那一格成立）。值只出自契约字段 `IncomingMessage.platform`。
        platform=platform,
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


# ================================================================ 描写档命令面（G-0～G-3）
#
# `/bot 描写 speech|scene|reset|show`（2026-10-04 裁定 G-0 取「乙」）。本节的身份与
# 上面 `/bot intimate` 那一族**完全一样**：只做分诊与行文，生效链一条都不重造——
#
# - 参数解析＝`content_route.match_narration_subcommand`（词表真身在那边，这里不抄成员）；
# - 写腿的作用域门＝`content_route.narration_write_allowed`（唯一判据处，群里非管理员拒写；
#   这一枚与 `_manual_command_scope_key` 的管理员分支同一个角色面，`chat.py` 不改一行）；
# - 落盘＝`content_route.write_narration_pin` / `clear_narration_pin`（键口、库口都在那边，
#   本模块不建 store、不解析路径、不自拼键形）；
# - 读数＝`content_route.resolve_intimate_context` 新增的 `narration_mode` / `narration_source`
#   两格；**能不能铺开写只准问 `grants_intimate_narration(narration_source)` 那一处**；
# - `show` 的词面沿用本文件已有的 `SHOW_SUBCOMMAND`（与开关面同一枚，不重列）。
#
# 三条腿互不吞：①认下子命令走写腿（`reset` 的返回值是空串＝收回钉，与"认不出"的 None
# 分家）；②None 之后自己认一次 `show` 走只读腿；③两条都不中才回"不认得"＋用法。
# 全程 fail-open：落库失败**不改变本轮判定**（那句明示照样生效，只是留不到下一轮，
# 回执据实说一句"没钉上"），绝不因为写失败就把命令升级成报错。

#: 描写档用法表（裸命令与"不认得"共用；四枚子命令一名不遗漏，词面只指回真身那张表）。
_NARRATION_USAGE_LINES: Final[tuple[str, ...]] = (
    "描写档（/bot 描写）的子命令：",
    "  speech  只说出口的话（这就是缺省）",
    "  scene   动作、神色、心里那一层也写出来",
    "  reset   把这格交回缺省，连钉一起收回",
    "  show    只看现在是什么档，什么都不改",
    "  不带子命令＝看这份用法加当前读数。",
)

#: 群侧被门挡下那一格（G-3：描写档只在她自己开过的那一格生效，普通成员恒只说话）。
#: 这句与 `REFUSED_REPLY` 同为**命令面独有**——整句面那三格能落回普通聊天，这里没有正文可落。
#: 🔴 席 na-showalign 改文（独立复查 W-2）：旧句「要它，得她自己或管理员说一句」**指了一条
#: 走不通的路**——`narration_write_allowed` 群侧只放 admin/super_admin，群里那位"她自己"
#: 再说一次仍被拒；而描写钉**按人不按群**（`_narration_person_key` 在群作用域键上读不出
#: 本人段），管理员在群里这一句也只钉得住**管理员自己**那一格 ⇒ 群里让管理员替她说
#: 从来就不是通路。唯一真能落下的动作＝她本人在**非群会话**里说一句。按规则 8（不谎报）
#: 只报那条真的。被这一支拒到的永远是「群里的非管理员」本人（管理员不被拒、私聊不吃门），
#: 所以一句就够，不必再按角色分叉。
NARRATION_REFUSED_REPLY: Final[str] = (
    "描写这一格我只按在「这个人、这一路会话」身上，不替旁人按下——"
    "想要它，私聊里跟我说一句 /bot 描写 scene 就好；钉下就一直留着，"
    "但换一个群还得再说一次（I-2：换会话要重开）。"
)

#: 三态确认话（守岸人语气，不提键名/库/来源码；空串键＝`reset`）。
_NARRATION_ACKS: dict[str, str] = {
    NARRATION_MODE_SCENE: "好，到你这里我不只说出口的话——动作、神色、心里那一层都写给你。",
    NARRATION_MODE_SPEECH: "嗯，那我只说口上的话，旁的都收着。",
    "": "这一格我放回原处了——往后照旧只说口上的话，除非你再钉一次。",
}

#: 落库那一腿没成时补的一句（本轮照样生效，但留不到下一轮——不说就是谎报）。
_NARRATION_UNSAVED_SUFFIX: Final[str] = "库里那一格这会儿没写进去，下次再说一次才留得住。"


def _narrated_scope_tag(session_type: str, source: str) -> str:
    """描写档回执的 scope 标签：这一轴**恒按人**（钉按人不按群，G-3 的实现面）。

    群作用域键读不出本人段 ⇒ 群里普通成员永远走"没钉"那一侧；这里打的标签只用于
    审计可分辨，不参与任何判定，与 `apply_intimate_switch` 那枚 scope 标签同族。
    """
    if str(session_type or "") == "group":
        return "scope:user" if str(source or "") else "scope:none"
    return "scope:self" if str(source or "") else "scope:none"


def _narration_state_lines(
    ctx: dict[str, Any],
    config: Any,
    *,
    route_key: str,
    sender_id: str,
    platform: str = "",
) -> list[str]:
    """当前描写档读数（写腿与 `show` 共用同一份行文，不留两套说法）。

    四格各有分工：`描写档`＝本轮生效的那一格（优先级三格的**结果**）、`依据`＝交给
    唯一那把尺的来源（人话映射表转过的，绝不外端码串）、`细节描写`＝**尺本身的读数**
    （只准 `grants_intimate_narration(narration_source)` 这一处调用）、`库里的钉`＝
    持久面（`reset` 过就是"没钉过"，与"钉了 speech"分得开）。
    """
    mode = str(ctx.get("narration_mode") or "")
    source = str(ctx.get("narration_source") or INTIMATE_SOURCE_NONE)
    pinned = read_narration_pin(
        route_key, sender_id=sender_id, config=config, platform=platform
    )
    return [
        f"描写档：{_label(_NARRATION_LABELS, mode)}",
        f"依据：{_label(_SOURCE_LABELS, source)}",
        _narration_grant_line(ctx),  # 与 `/bot intimate show` 同一渲染口 ⇒ 两句必然同值
        f"库里的钉：{_label(_NARRATION_LABELS, pinned) if pinned else '没钉过'}",
    ]


def build_narration_control_result(
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
    platform: str = "",
) -> CapabilityResult:
    """/bot 描写 的三腿分诊口：写腿 → 只读查询 → 用法（都不中才回"不认得"）。

    `subcommand` **必须是已剥掉 `/bot 描写` 前缀**后剩下的参数串（前缀归命令面，
    与 `match_narration_subcommand` 同一口径）。`privacy_level` 交**会话自己的隐私档**，
    缺席时按会话类型回落一次（与开关面那一支逐字同形，本模块不另立第三套判据）。
    `platform` 交 **`message.platform`**（qq/telegram/…）：描写档的钉按 (平台域, 用户号)
    归属（`content_route._narration_person_key`），平台缺席即 fail-closed＝群侧读不出钉。
    🔴 接线面（根 `__init__.py`）与注入缝（`capabilities/chat.py` 那三个 `resolve_intimate_context`
    调用点）**必须同一批**各交同一个平台事实，只接一侧＝"写在 `qq:<uid>`、读在 `<uid>`"
    两形不相交（#33★ 那族；方向上是少写、绝不误串到别人的桶）。
    返回值永远是 `CapabilityResult`——命令面没有"落回普通聊天"这条路。

    与开关面**不同**的一格：这一族**不吃** `bot_content_route_enabled` 总闸与
    `eligible` 名单门。描写档是文风偏好（G-1 明写"普通模式也能用"），把总闸当它的门
    等于让一次路由开关静默改掉文风面；总闸真正管的是路由/放行那两件事。
    """
    resolved_privacy = privacy_level or (
        PrivacyLevel.GROUP if str(session_type or "") == "group" else PrivacyLevel.PERSONAL
    )
    raw = str(subcommand or "").strip()
    parsed = match_narration_subcommand(raw)
    ctx = resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type=session_type,
        group_id=group_id,
        sender_id=sender_id,
        session_key=session_key,
        config=config,
        platform=platform,
    )
    route_key = str(ctx.get("route_key") or session_key or "")
    if parsed is not None:
        verb = "reset" if parsed == "" else parsed
        tags = ["content_route", "slash_narration", f"slash_narration:{verb}"]
        if not narration_write_allowed(session_type=session_type, sender_roles=sender_roles):
            return _text_result(
                request_id,
                f"{NARRATION_REFUSED_REPLY}\n{INTIMATE_HELP_POINTER}",
                [*tags, "scope:none", "slash_narration_refused"],
                resolved_privacy,
            )
        if parsed == "":
            saved = clear_narration_pin(
                route_key, sender_id=sender_id, config=config, platform=platform
            )
        else:
            saved = write_narration_pin(
                route_key,
                mode=parsed,
                sender_id=sender_id,
                config=config,
                platform=platform,
            )
        # 本轮读数**带着本轮那一格**再合成一次：落库失败时这一句照样算数（写失败不许
        # 升级成"这一轮白说"），成功时读数与库里那份自然同形。
        shown = resolve_intimate_context(
            SHARED_CONTENT_ROUTE_ENGINE,
            session_type=session_type,
            group_id=group_id,
            sender_id=sender_id,
            session_key=session_key,
            config=config,
            turn_narration_mode=parsed,
            platform=platform,
        )
        lines = [_NARRATION_ACKS[parsed]]
        if not saved:
            lines.append(_NARRATION_UNSAVED_SUFFIX)
        lines.extend(
            _narration_state_lines(
                shown, config, route_key=route_key, sender_id=sender_id, platform=platform
            )
        )
        if not saved:
            tags.append("narration_unsaved")
        tags.append(_narrated_scope_tag(session_type, str(shown.get("narration_source") or "")))
        return _text_result(
            request_id, "\n".join(lines), tags, resolved_privacy
        )
    if raw.lower() == SHOW_SUBCOMMAND:
        lines = _narration_state_lines(
            ctx, config, route_key=route_key, sender_id=sender_id, platform=platform
        )
        return _text_result(
            request_id,
            "\n".join(lines),
            [
                "content_route",
                "slash_narration",
                "slash_narration:show",
                _narrated_scope_tag(session_type, str(ctx.get("narration_source") or "")),
            ],
            resolved_privacy,
        )
    head = [] if not raw else [f"没认出这个子命令：{raw}"]
    body = "\n".join([*head, *_narration_state_lines(
        ctx, config, route_key=route_key, sender_id=sender_id, platform=platform
    ), *_NARRATION_USAGE_LINES, INTIMATE_HELP_POINTER])
    verb = "usage" if not raw else "unknown"
    return _text_result(
        request_id,
        body,
        ["content_route", "slash_narration", f"slash_narration:{verb}"],
        resolved_privacy,
    )
