"""书面同意命令面（用户裁定第 18 项的批准腿，capability_id ``bot.consent``）。

一句话
----
危险参数的改动被咽喉拦下时会签出一张同意卡；本文件是**把那张卡批掉或驳回的那句话**
——超管/管理员在会话里说一句，卡就当场落地或作废。此前本仓的形态是「拦截腿已在生产、
放行腿只有测试调用者」（工单签得出来、批不下去），本件补的就是放行这一段。

三件事，只做这三件
----
1. **认触发**：整句必须以 ``DEFAULT_TRIGGER_WORDS`` 之一开头，且后面只能跟本文件认得的
   子命令形（``待批`` / ``看 <id>`` / ``批 <id> <短码>`` / ``驳 <id> <短码>``）。
   判据是**锚定的**：``同意卡 顺便帮我改下密码`` 不算命令——这是一条会改生产参数的
   入口，宁可拒得难看，不许把用户的随口一句话读成批准。
2. **把权限门**：非管理员连「看」都不给（角色只吃 ``decision.actor_roles``，
   与 host_state 同口径，零第二份角色表）。**谁能批一张具体的卡**不在这里判——
   那一问的唯一真身是 ``consent.ConsentLedger.redeem_from_message`` 的阶梯
   （可信级 / 私聊门 / 原会话门 / 防自批 / 一次性 / TTL），本件一条都不复制。
3. **回人话**：把阶梯交回的 ``ConsentGrant`` / ``Refusal`` 翻成守岸人语气的一行，
   并点名是哪枚键、从什么值改成什么值、哪一档。

不做什么
----
- 不判档位、不签卡、不记账：全部复用 ``settings_gate.SettingsWriteGate``
  （咽喉唯一执法点）与 ``consent.ConsentLedger``（同意账唯一真身）。
- 不新建第二条入站通路：能力挂在既有分发上（``bot.consent`` 走与 ``bot.host_state``
  同一条 ``on_message`` → 中央管线），装配点在主代理手里（见根装配施工单）。
- 不接受「模型替人批」：批准只认一条真 ``IncomingMessage``，本件的形参就是它，
  凭证无法由 bot 侧构造（这是裁定第 18 项不变量①的形态，``consent.py`` 头注同源）。
"""

from __future__ import annotations

import random
import re
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    new_request_id,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.core.safety_exec import config_risk
from plugins.bot_unified_runtime.domains.core.safety_exec.consent import (
    ConsentGrant,
    Refusal,
    plain_text_for,
)

CAPABILITY_ID = "bot.consent"

#: 触发词表（简中/繁中/英文/拼音）。帮助侧词表必须与此**逐词一致**——
#: `tests/test_trigger_bidirectional_gate.py` 按词级双向 diff 执法，写一头必红。
DEFAULT_TRIGGER_WORDS: tuple[str, ...] = (
    "同意卡",
    "书面同意",
    "同意單",
    "書面同意",
    "consentcard",
    "yijika",
    "shumiantongyi",
)

#: 子命令动词（同一形位的别名并在这里，判据只在这一处）。
_LIST_VERBS = frozenset({"", "待批", "列表", "清单", "list", "pending"})
_SHOW_VERBS = frozenset({"看", "查", "详情", "show", "view"})
_APPROVE_VERBS = frozenset({"批", "批准", "同意", "approve", "yes"})
_DENY_VERBS = frozenset({"驳", "驳回", "拒绝", "deny", "reject", "no"})

_ID_CHARS = "A-Za-z0-9_.-"
_ID_RE = re.compile(rf"^[{_ID_CHARS}]{{1,64}}$")
_CODE_RE = re.compile(rf"^[{_ID_CHARS}]{{1,32}}$")

EMPTY_PENDING_LINE = "眼下没有待批的同意卡——没有任何参数在等谁点头。"
NO_GATE_LINE = (
    "安全执行引擎现在没装载（总闸关着，或门还没建起来）："
    "没有卡可批，也不会有参数被这一族命令改动。"
)
#: 批下来之后下一步做什么——卡面上写一遍、批复回显再写一遍，两处同一枚常量，
#: 禁在此处之外再抄一份（措辞改了必须两处一起改，因为它们是同一个真身）。
GRANT_NEXT_STEP_LINE = (
    "下一步：请原来发起这件事的人用同一参数再说一次，我照卡上批的那件事落地——"
    "凭证一次有效，批了不重试到点就作废，要改请重新申请。"
)

USAGE_LINE = (
    "用法：同意卡 待批｜同意卡 看 <工单号>｜同意卡 批 <工单号> <短码>｜"
    "同意卡 驳 <工单号> <短码>"
)


# ---------------------------------------------------------------------------
# 1. 认触发
# ---------------------------------------------------------------------------


def _head_and_rest(text: str) -> tuple[str, str] | None:
    """整句必须以某个触发词开头，且触发词后只能跟空白或句尾。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    lowered = raw.casefold()
    for head in DEFAULT_TRIGGER_WORDS:
        key = head.casefold()
        if lowered == key:
            return head, ""
        if lowered.startswith(key) and raw[len(key)] in " \t":
            return head, raw[len(key):].strip()
    return None


def parse_consent_command(text: str) -> dict[str, str] | None:
    """把一句话解析成 ``{"verb": ..., "consent_id": ..., "code": ...}``。

    解析不出来（含「触发词后面跟了我不认识的东西」）一律回 ``None``——
    这条判据不许放宽成「大概像就当命令」：放宽一次，就有一次把闲聊批成改参数。
    """
    parsed_head = _head_and_rest(text)
    if parsed_head is None:
        return None
    _head, rest = parsed_head
    parts = rest.split()
    verb_token = parts[0].casefold() if parts else ""
    if verb_token in _LIST_VERBS:
        if len(parts) > 1:
            return None
        return {"verb": "list", "consent_id": "", "code": ""}
    if verb_token in _SHOW_VERBS:
        if len(parts) != 2 or not _ID_RE.match(parts[1]):
            return None
        return {"verb": "show", "consent_id": parts[1], "code": ""}
    if verb_token in _APPROVE_VERBS or verb_token in _DENY_VERBS:
        if len(parts) != 3:
            return None
        if not _ID_RE.match(parts[1]) or not _CODE_RE.match(parts[2]):
            return None
        verb = "approve" if verb_token in _APPROVE_VERBS else "deny"
        return {"verb": verb, "consent_id": parts[1], "code": parts[2]}
    return None


def is_consent_command(text: str) -> bool:
    """路由谓词：这句话是不是一条同意卡命令（判定与解析同一处，零第二套词表）。"""
    return parse_consent_command(text) is not None


def is_admin_actor(actor_roles: list[str] | None) -> bool:
    """管理员或超管可看单；批某张具体卡够不够格由 ``consent`` 的阶梯判。"""
    roles = {str(role).strip().lower() for role in (actor_roles or [])}
    return bool(roles & {"admin", "super_admin"})


# ---------------------------------------------------------------------------
# 2. 把每一环的账面翻成人话（只读账面的投影，零第二本账）
# ---------------------------------------------------------------------------


def _safe(text: object) -> str:
    """出站前统一打码：走中央咽喉 ``redact_local_secrets``（不在这里复制第二套规则）。"""
    body = str(text or "")
    try:
        from plugins.bot_unified_runtime.domains.render.plain_text import (
            redact_local_secrets,
        )

        return redact_local_secrets(body)
    except Exception:  # noqa: BLE001 - 打码件坏了不许把回显吞掉；宁可原文并保拒绝成立
        return body


def _tier_label(row: Any) -> str:
    """档位代号 + 它到底要谁点头（真值表唯一住 `config_risk`，这里只翻译不判定）。"""
    tier = str(getattr(row, "tier", "") or config_risk.DEFAULT_TIER.value)
    needs_writing = tier in config_risk.WRITTEN_CONSENT_TIERS
    return f"{tier}｜{'超管私聊书面同意' if needs_writing else '会话内管理员确认'}"


def _value_pair_lines(row: Any) -> list[str]:
    """卡面上的「哪枚键、旧值→新值」两行（值缺失就明写，不编）。

    敏感值的真身在账上就不留明文（``value_is_sensitive``），这里必须照实说
    「不留明文」而不是回一个空串——空串会被读成「旧值是空的」。
    """
    target = str(getattr(row, "target", "") or "?")
    lines = [f"哪枚参数：{target}"]
    if getattr(row, "restore_default", False):
        old = _display(getattr(row, "before_value", None))
        return lines + [f"要做什么：撤掉覆盖、回到 .env 缺省（当前覆盖 {old}）"]
    if getattr(row, "value_is_sensitive", False):
        return lines + [
            "旧值 → 新值：凭证类参数，账上两边都不留明文（只留指纹对账）"
        ]
    old = _display(getattr(row, "before_value", None))
    new = _display(getattr(row, "after_value", None))
    return lines + [f"旧值 → 新值：{old} → {new}"]


def _display(value: Any) -> str:
    if value is None:
        return "（账上没留）"
    text = str(value)
    return text if len(text) <= 80 else text[:80] + "…"


def ticket_lines(row: Any, *, index: str = "") -> list[str]:
    """一张卡的完整人话（列表页与详情页共用同一份，禁两处各拼一遍）。"""
    from plugins.bot_unified_runtime.domains.core.safety_exec import settings_gate

    code = settings_gate.short_code_of(row)
    head = f"{index} " if index else ""
    return [
        f"{head}工单 {row.consent_id}｜短码 {code}",
        *_value_pair_lines(row),
        f"风险档：{_tier_label(row)}",
        f"申请人：{getattr(row, 'requester', '') or '（未记名）'}",
        f"签出：{getattr(row, 'created_at', '')}｜过期：{getattr(row, 'expires_at', '')}",
        f"状态：{getattr(row, 'state', '')}",
    ]


def pending_lines(rows: list[Any]) -> list[str]:
    lines = [f"待批的同意卡 {len(rows)} 张："]
    for position, row in enumerate(rows, start=1):
        lines.extend(ticket_lines(row, index=f"{position}."))
    return lines


# ---------------------------------------------------------------------------
# 3. 能力本体
# ---------------------------------------------------------------------------


def _result(
    request_id: str,
    body: str,
    *,
    audit: list[str],
    title: str = "书面同意",
) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id=CAPABILITY_ID,
        kind="text",
        title=title,
        body=_safe(body),
        risk_level=RiskLevel.LOW,
        privacy_level=PrivacyLevel.PUBLIC,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["consent", *audit],
    )


def _gate_result(request_id: str) -> CapabilityResult:
    """非管理员：话术走既有轮换池，且不透露任何一张卡的内容。"""
    return _result(
        request_id,
        random.choice(user_copy.ADMIN_GATE_TEMPLATES).format(action="看或批同意卡"),
        audit=["gate_not_admin"],
    )


def _verdict_result(
    request_id: str, verdict: Any, *, verb: str
) -> CapabilityResult:
    """把阶梯交回的 ConsentGrant / Refusal 翻成人话（判据不在这里，只有措辞）。"""
    if isinstance(verdict, ConsentGrant):
        row = verdict.row
        # 「批了」与「改了」是两件事，一句话都不替对方许诺：凭证要由**原发起人用同一
        # 参数再说一次**才落地（咽喉的写腿只在调用栈上跑，批准发生在另一条会话腿）。
        lines = ["这张卡按你批的记下了。", *ticket_lines(row), GRANT_NEXT_STEP_LINE]
        return _result(request_id, "\n".join(lines), audit=[f"{verb}_granted"])
    if isinstance(verdict, Refusal):
        detail = getattr(verdict, "detail", "")
        body = plain_text_for(verdict.kind)
        if detail:
            body = f"{body}\n{detail}"
        return _result(
            request_id,
            f"{body}\n（{verdict.target}｜{verdict.tier}｜{verdict.kind.value}）",
            audit=[f"{verb}_refused_{verdict.kind.value}"],
        )
    return _result(
        request_id,
        f"这一问的答复我读不懂（返回的是 {type(verdict).__name__}），"
        "所以什么都没当作批准记下来。",
        audit=[f"{verb}_unknown_verdict_shape"],
    )


def build_consent_admin_result(
    gate: Any,
    message: IncomingMessage,
    parsed: dict[str, str],
    *,
    request_id: str = "",
) -> CapabilityResult:
    """在已装好的执法门上执行一条同意卡命令（唯一动账入口仍是门与账本体）。"""
    rid = request_id or new_request_id("consent")
    verb = parsed["verb"]
    if gate is None or not getattr(gate, "enabled", False):
        return _result(rid, NO_GATE_LINE, audit=["no_gate"])
    if verb == "list":
        rows = [ticket.row for ticket in gate.pending_tickets()]
        body = EMPTY_PENDING_LINE if not rows else "\n".join(pending_lines(rows))
        return _result(rid, body, audit=["list"], title="待批同意卡")
    if verb == "show":
        ticket = gate.ticket(parsed["consent_id"])
        if ticket is None:
            return _result(
                rid,
                f"没有这张卡：{parsed['consent_id']}（也许已经过期，或从来不是签给这台的）。",
                audit=["show_unknown"],
            )
        return _result(
            rid, "\n".join(["这一张卡的全文：", *ticket_lines(ticket.row)]),
            audit=["show"],
        )
    if verb == "approve":
        verdict = gate.approve(
            parsed["consent_id"], code=parsed["code"], message=message
        )
        return _verdict_result(rid, verdict, verb="approve")
    verdict = gate.deny(parsed["consent_id"], code=parsed["code"], message=message)
    return _verdict_result(rid, verdict, verb="deny")


def build_consent_admin_capability(gate_provider: Any) -> Any:
    """构建能力：返回 ``(message, decision) -> CapabilityResult``（与 host_state 同形）。

    ``gate_provider`` 是一个**每次现读**的可调用（装配侧给
    ``lambda: runtime_settings.safety_gate``）——门是惰性建的，构造期快照会把它
    钉成 None，于是命令面永远回「门没装载」（本仓「开关在册而路走不到」的旧坑）。
    """

    def capability(message: IncomingMessage, decision: Any) -> CapabilityResult:
        request_id = str(getattr(message, "request_id", "") or "") or new_request_id(
            "consent"
        )
        parsed = parse_consent_command(str(getattr(message, "plain_text", "") or ""))
        if parsed is None:
            return CapabilityResult(
                request_id=request_id,
                capability_id=CAPABILITY_ID,
                kind="text",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["consent", "skip_no_trigger"],
            )
        actor_roles = list(getattr(decision, "actor_roles", []) or [])
        if not is_admin_actor(actor_roles):
            return _gate_result(request_id)
        gate = gate_provider() if callable(gate_provider) else gate_provider
        return build_consent_admin_result(
            gate, message, parsed, request_id=request_id
        )

    return capability


__all__ = [
    "CAPABILITY_ID",
    "DEFAULT_TRIGGER_WORDS",
    "EMPTY_PENDING_LINE",
    "NO_GATE_LINE",
    "USAGE_LINE",
    "build_consent_admin_capability",
    "build_consent_admin_result",
    "is_admin_actor",
    "is_consent_command",
    "parse_consent_command",
    "pending_lines",
    "ticket_lines",
]
