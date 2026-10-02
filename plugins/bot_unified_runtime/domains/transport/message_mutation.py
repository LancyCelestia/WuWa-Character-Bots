"""消息编辑与撤回：把 outbound_registry 的 EDIT/DELETE 坐标变成有人调用的能力。

席位 S34（2026-10-04）。此前事实：``domains/core/decision/outbound_registry.py`` 登记了
QQ ``delete_msg``/``edit_msg`` 与 TG ``editMessageText``/``deleteMessage`` 的**坐标**，
但全树零 live 调用点（唯一那条 ``delete_msg`` 是脏话守门里 ``bot.call_api`` 直连旁路，
审计记为 B3/P2，本席不代它收编）。

链路（全部复用，零新建通路、零新表）
------------------------------------
``MutationRequest`` → ``authorize_mutation``（门禁，缺省关）→ ``build_mutation_payload``
→ ``OutboundIntent``（严格 DTO）→ ``OutboundSideEffectExecutor``（统一出站副作用执行器：
准入复验 → 许可租约线性化 → ``TransportRegistry`` 固定映射取平台方法名，**绝不拼 API 名**
→ ``bot.call_api`` 通道本体，与 SendQueue worker 同一条腿）→ ``MutationOutcome``。
「这条消息是不是 bot 自己发的」不另立账：现读 ``sender/receipts.py`` 的投递回执
（``provider_message_id``），拿不到台账就整门拒（fail closed）。

能力边界（如实，别读成「能改对方消息」）
----------------------------------------
* **Telegram**：``editMessageText`` / ``deleteMessage`` 只能作用于 **bot 自己发出**的
  消息，且 ``chat_id`` + ``message_id`` 必须齐 —— 缺 chat_id 时本席**诚实失败**，
  绝不「先猜一个发出去看看」。
* **QQ（OneBot V11 / SnowLuma）**：``delete_msg`` 撤回本 bot 发出去的消息（平台侧另有
  时限）；``edit_msg`` 是 **NapCat 扩展方法**，OneBot v11 标准无编辑面，登记册原注
  「bind 前必须对生产 NapCat 实测」至今仍然成立 —— 本席只离线构造与单测，
  **未对生产实测**，所以 QQ 编辑面在盘上是「已接线、未验证」。
* 因此本能力的真实作用域＝「bot 自己发出去、且在投递回执账里对得上号的那条消息」。
  别人的消息、对端消息，一律碰不到。

开关与三面（2026-10-04 用户点头开面，席 S34b 落键）
------------------------------------------------
``bot_message_mutation_enabled`` / ``bot_message_mutation_window_seconds`` 现为
``config.py`` 的**在册字段**（缺省 ``False`` / ``120``），本模块属性式直读，不再
``getattr`` 容缺省（字段在册后容缺省＝第二套口径）。缺省 ``False`` 仍是门关＝能力整体
不生效（``authorize_mutation`` 首条即 ``feature_disabled``，零平台调用）；开面要用户把
``.env`` 的 ``BOT_MESSAGE_MUTATION_ENABLED`` 置 true 并**重启**。
三面（幽灵字段锁，台账 #68）＝config 字段 + ``runtime/settings.py::RESTART_REQUIRED_KEYS``
（config 经 ``install_message_mutation`` 的闭包在装配期快照，未进
``_RUNTIME_HOT_OVERRIDE_FIELDS`` ⇒ 热 set 零生效，诚实登记需重启）+ ``.env.example`` 声明。

注毒与执法见 ``tests/test_message_mutation_wiring.py``。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nonebot.adapters import Bot, Event

from plugins.bot_unified_runtime.control_plane.dispatcher import (
    OutboundSideEffectExecutor,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    PLATFORM_QQ,
    PLATFORM_TELEGRAM,
    is_admin_message,
)
from plugins.bot_unified_runtime.domains.core.decision.outbound_contracts import (
    OutboundIntent,
    OutboundOperation,
    OutboundPart,
    OutboundTarget,
    derive_dedupe_key,
)

OPERATION_EDIT = "edit"
OPERATION_DELETE = "delete"

#: 撤回/编辑时限缺省值（秒）：QQ 平台自身时限更短，这里只做「不许翻旧账」的上界。
DEFAULT_MUTATION_WINDOW_SECONDS = 120
#: 编辑文本长度上界（QQ/TG 均对单条文本有硬限，超限诚实拒，不静默截断）。
EDIT_TEXT_MAX_CHARS = 500

FEATURE_ID = "bot.plugin.transport.message_mutation"
POLICY_REVISION = "s34-message-mutation-1"

_SESSION_TYPES = frozenset({"private", "group", "channel"})

_LOGGER = logging.getLogger("bot.message_mutation")

#: 统一出站副作用执行器：与 reactions engine 同一枚类、同一条通道本体
#: （非第二出站通路 —— 出站方法名仍由 TransportRegistry 固定映射给出）。
_MUTATION_OUTBOUND_EXECUTOR = OutboundSideEffectExecutor()


class MutationRefused(Exception):
    """载荷形状不合法（缺 id / 文本空 / 超长）。``reason`` 即回执里的原因码。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class MutationActor:
    """请求人事实。``platform``/``sender_id`` 两字段与 ``is_admin_message`` 的
    鸭子类型口径逐字对齐（该平台域名单才生效，缺平台事实 fail closed）。

    ``own_private_chat`` 仅用于「私聊本人」这条腿：私聊会话里 bot 发出的消息，
    对面那位本就是唯一收件人，允许其撤回/编辑自己会话内的 bot 消息。
    """

    platform: str
    sender_id: str
    chat_id: str = ""
    is_admin: bool = False
    own_private_chat: bool = False


@dataclass(frozen=True)
class MutationTarget:
    """被作用消息的平台坐标。``chat_id`` 即便平台方法不吃（QQ delete_msg）也
    **必填** —— 它是会话绑定与回执对账的键，不是可选项。"""

    platform: str
    session_type: str
    chat_id: str
    message_id: str
    sent_at: datetime | None = None


@dataclass(frozen=True)
class MutationRequest:
    operation: str
    actor: MutationActor
    target: MutationTarget
    text: str = ""


@dataclass(frozen=True)
class MutationOutcome:
    """一次变动的诚实回执。``ok`` 只在平台确实吃了这条调用时为真。"""

    ok: bool
    status: str
    reason: str = ""
    method: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        if self.ok:
            return f"已{('编辑' if self.status == 'delivered' else '')}{self.method}（{self.status}）"
        return f"未执行（{self.status}:{self.reason}）"


# ---------------------------------------------------------------------------
# 配置读取（门关缺省；见模块 docstring「开关与需裁定」）
# ---------------------------------------------------------------------------


def mutation_feature_enabled(config: Any) -> bool:
    """总闸：在册字段直读（席 S34b 三面落键后，getattr 容缺省＝第二套口径，已撤）。"""
    return bool(config.bot_message_mutation_enabled)


def mutation_window_seconds(config: Any) -> int:
    """时限秒数：在册字段直读；只守「必须为正」这条形状判据（非正＝回退在册缺省上界）。"""
    window = int(config.bot_message_mutation_window_seconds)
    return window if window > 0 else DEFAULT_MUTATION_WINDOW_SECONDS


def _normalize_platform(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {PLATFORM_QQ, "onebot", "onebot_v11", "snowluma"}:
        return PLATFORM_QQ
    if text in {PLATFORM_TELEGRAM, "tg"}:
        return PLATFORM_TELEGRAM
    return text


# ---------------------------------------------------------------------------
# 载荷构造（锁①：chat_id/message_id 在场才发；锁②：缺 id 诚实失败）
# ---------------------------------------------------------------------------


def build_mutation_payload(request: MutationRequest) -> dict[str, Any]:
    """平台 API 参数。缺 ``message_id`` / 缺 ``chat_id`` / 文本不合法 ⇒ 抛
    ``MutationRefused``，**绝不**退化成「少一个参数也发发看」。"""
    target = request.target
    operation = str(request.operation or "").strip().lower()
    if operation not in {OPERATION_EDIT, OPERATION_DELETE}:
        raise MutationRefused("unknown_operation")

    platform = _normalize_platform(target.platform)
    if platform not in {PLATFORM_QQ, PLATFORM_TELEGRAM}:
        raise MutationRefused("unsupported_platform")

    session_type = str(target.session_type or "").strip().lower()
    if session_type not in _SESSION_TYPES:
        raise MutationRefused("unsupported_session_type")

    message_id = str(target.message_id or "").strip()
    if not message_id:
        raise MutationRefused("missing_message_id")
    if not message_id.isdigit():
        raise MutationRefused("non_numeric_message_id")

    chat_id = str(target.chat_id or "").strip()
    if not chat_id:
        raise MutationRefused("missing_chat_id")

    params: dict[str, Any] = {"message_id": int(message_id)}
    if platform == PLATFORM_TELEGRAM:
        # TG Bot API 两枚方法都吃 chat_id（QQ 侧 delete_msg 不吃，故不塞）。
        params["chat_id"] = chat_id
    if operation == OPERATION_EDIT:
        text = str(request.text or "")
        if not text.strip():
            raise MutationRefused("empty_edit_text")
        if len(text) > EDIT_TEXT_MAX_CHARS:
            raise MutationRefused("edit_text_too_long")
        if any(ch in text for ch in ("\x00", "\r")):
            raise MutationRefused("edit_text_control_chars")
        params["text"] = text
    return params


def build_mutation_intent(request: MutationRequest, params: dict[str, Any]) -> OutboundIntent:
    """变动意图 → §10 严格 DTO（幂等键段禁 ``:``，故走 ``derive_dedupe_key``）。"""
    target = request.target
    platform = _normalize_platform(target.platform)
    session_type = str(target.session_type or "").strip().lower()
    operation = str(request.operation or "").strip().lower()
    event_id = f"{operation}.{platform}.{session_type}.{str(target.chat_id).strip()}"
    event_id = event_id + f".{str(target.message_id).strip()}"
    dedupe_key = derive_dedupe_key(platform, event_id, "mutation")
    adapter = "onebot" if platform == PLATFORM_QQ else "telegram"
    return OutboundIntent(
        operation=OutboundOperation.EDIT if operation == OPERATION_EDIT else OutboundOperation.DELETE,
        target=OutboundTarget(
            platform=platform,
            session_type=session_type,
            target_id=str(target.chat_id).strip(),
            adapter=adapter,
        ),
        parts=[
            OutboundPart(
                part_id=f"mutation:{dedupe_key}",
                kind="text",
                content_ref={"api_params": dict(params)},
            )
        ],
        feature_id=FEATURE_ID,
        policy_revision=POLICY_REVISION,
        dedupe_key=dedupe_key,
        trace_id=f"mutation-{platform}-{str(target.message_id).strip()}",
    )


# ---------------------------------------------------------------------------
# 「这条消息是 bot 自己发的吗」—— 复用投递回执账（不新立账）
# ---------------------------------------------------------------------------


def _receipt_rows(ledger: Any) -> Iterable[Any]:
    lister = getattr(ledger, "list_receipts", None)
    if callable(lister):
        return list(lister())
    return []


def _matches_message(receipt: Any, message_id: str) -> bool:
    return str(getattr(receipt, "provider_message_id", "") or "").strip() == message_id


def find_send_receipt(ledger: Any, message_id: str) -> Any | None:
    """在既有投递回执里找这条消息（bot 自己发出去的凭据）。找不到 ⇒ None。"""
    for receipt in _receipt_rows(ledger):
        if _matches_message(receipt, message_id):
            return receipt
    return None


def _receipt_created_at(receipt: Any) -> datetime | None:
    raw = getattr(receipt, "created_at", None)
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = datetime.fromisoformat(raw.strip())
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


# ---------------------------------------------------------------------------
# 门禁（谁能改/撤回哪条）
# ---------------------------------------------------------------------------


def authorize_mutation(
    config: Any,
    request: MutationRequest,
    *,
    ledger: Any = None,
    now: datetime | None = None,
) -> str:
    """返回 ``""``＝放行，否则原因码。逐条 fail closed，顺序＝便宜判据在前。"""
    if not mutation_feature_enabled(config):
        return "feature_disabled"
    operation = str(request.operation or "").strip().lower()
    if operation not in {OPERATION_EDIT, OPERATION_DELETE}:
        return "unknown_operation"

    actor_platform = _normalize_platform(request.actor.platform)
    target_platform = _normalize_platform(request.target.platform)
    if target_platform != actor_platform:
        return "cross_platform_target"
    actor_chat = str(request.actor.chat_id or "").strip()
    target_chat = str(request.target.chat_id or "").strip()
    if not actor_chat or not target_chat or actor_chat != target_chat:
        return "out_of_session"

    # 权限腿：管理员/超管（中央名单，同 ``is_admin_message`` 口径）或私聊本人。
    privileged = bool(request.actor.is_admin) or is_admin_message(config, request.actor)
    private_chat = str(request.target.session_type or "").strip().lower() == "private"
    if not privileged and not (private_chat and request.actor.own_private_chat):
        return "not_authorized"

    # 归属腿：只作用于 bot 自己发出去、且回执对得上号的消息。
    message_id = str(request.target.message_id or "").strip()
    if ledger is None:
        return "no_send_ledger"
    receipt = find_send_receipt(ledger, message_id)
    if receipt is None:
        return "not_bot_message"

    # 时限腿：回执时刻优先，退回调用方给的 sent_at。
    moment = _receipt_created_at(receipt) or request.target.sent_at
    if moment is not None:
        reference = now or datetime.now(timezone.utc)
        reference = reference if reference.tzinfo else reference.replace(tzinfo=timezone.utc)
        if (reference - moment).total_seconds() > mutation_window_seconds(config):
            return "mutation_window_expired"
    return ""


# ---------------------------------------------------------------------------
# 执行（唯一 live 出口；门就在这里被调用）
# ---------------------------------------------------------------------------


async def execute_mutation(
    request: MutationRequest,
    *,
    config: Any,
    bot: Any = None,
    executor: Any = None,
    ledger: Any = None,
    now: datetime | None = None,
) -> MutationOutcome:
    """走统一出站副作用执行器执行一次编辑/撤回，返回诚实回执。

    本函数**不吞**任何失败：门拒不放行、载荷不合法、平台报错、无通道，
    全部落到 ``MutationOutcome.status/reason``，由调用方（命令面/日志）处置。
    """
    runner = executor if executor is not None else _MUTATION_OUTBOUND_EXECUTOR
    verdict = authorize_mutation(config, request, ledger=ledger, now=now)
    if verdict:
        return MutationOutcome(False, "refused", verdict)
    try:
        params = build_mutation_payload(request)
    except MutationRefused as exc:
        return MutationOutcome(False, "invalid_target", exc.reason)
    intent = build_mutation_intent(request, params)
    receipt = await runner.execute(intent, bot=bot)
    status = str(receipt.status or "unknown")
    return MutationOutcome(
        ok=bool(receipt.delivered),
        status=status,
        reason=str(receipt.reason or ""),
        method=str(receipt.method or ""),
        params=params,
    )


# ---------------------------------------------------------------------------
# 接线入口（根装配文件调用；门缺省关 ⇒ 未开面时命令只会拿到一句 refusal）
# ---------------------------------------------------------------------------


def _platform_of(bot: Any) -> str:
    impl = str(getattr(getattr(bot, "adapter", None), "impl_name", "") or "").strip().lower()
    if "telegram" in impl:
        return PLATFORM_TELEGRAM
    if "onebot" in impl or "snowluma" in impl:
        return PLATFORM_QQ
    return ""


def install_message_mutation(config: Any, bot: Any = None) -> Any:
    """注册 ``/msg_mutation`` 管理面（NoneBot matcher）。

    用法：``/msg_mutation recall <message_id>``、
    ``/msg_mutation edit <message_id> <新文本>``。
    行为：先过 ``authorize_mutation``（**缺省关**），门关时只回一句原因码，
    不发任何平台调用；结果一律写日志（``bot.message_mutation``）。
    """
    from nonebot import on_command

    from plugins.bot_unified_runtime.domains.transport.sender.receipts import (
        build_receipt_repository,
    )

    ledger = build_receipt_repository(config)
    matcher = on_command("msg_mutation", priority=3, block=False)
    fallback_platform = _platform_of(bot)

    @matcher.handle()
    async def _handle_msg_mutation(bot: Bot, event: Event) -> None:
        text = str(event.get_plaintext() or "").strip()
        parts = text.split(maxsplit=2)
        action = parts[1].strip().lower() if len(parts) > 1 else ""
        operation = OPERATION_DELETE if action in {"recall", "delete", "撤回"} else (
            OPERATION_EDIT if action in {"edit", "改"} else action
        )
        message_id = parts[2].split(maxsplit=1)[0].strip() if len(parts) > 2 else ""
        new_text = ""
        if len(parts) > 2:
            tail = parts[2].split(maxsplit=1)
            new_text = tail[1] if len(tail) > 1 else ""
        group_id = str(getattr(event, "group_id", "") or "").strip()
        chat_id = group_id or str(getattr(event, "user_id", "") or "").strip()
        platform = _platform_of(bot) or fallback_platform
        actor = MutationActor(
            platform=platform,
            sender_id=str(getattr(event, "sender_id", "") or getattr(event, "user_id", "") or ""),
            chat_id=chat_id,
            own_private_chat=not bool(group_id),
        )
        request = MutationRequest(
            operation=operation,
            actor=actor,
            target=MutationTarget(
                platform=platform,
                session_type="group" if group_id else "private",
                chat_id=chat_id,
                message_id=message_id,
            ),
            text=new_text,
        )
        outcome = await execute_mutation(request, config=config, bot=bot, ledger=ledger)
        _LOGGER.info(
            "message_mutation %s %s -> %s",
            operation,
            message_id,
            outcome.describe(),
        )

    return matcher


__all__ = [
    "EDIT_TEXT_MAX_CHARS",
    "MutationActor",
    "MutationOutcome",
    "MutationRefused",
    "MutationRequest",
    "MutationTarget",
    "authorize_mutation",
    "build_mutation_intent",
    "build_mutation_payload",
    "execute_mutation",
    "find_send_receipt",
    "install_message_mutation",
    "mutation_feature_enabled",
    "mutation_window_seconds",
]
