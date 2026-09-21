"""校园自动转发（campus v1）：学校 QQ 账号群消息 → 主人私聊实时转发。

设计约束：

- **纯监听**：对学校群只读不写，本模块绝不向任何群发送消息；
- **三重来源门**：总开关 ∧ 学校账号（self_ids）∧ 群白名单，任一为空整链路
  关闭——绝不猜账号、绝不猜群；白名单支持 ``*`` 显式放行学校号全部群；
- **幂等**：message_id 去重，SnowLuma 断线重连重发不会双推；
- **防无界增长**：跨天首条录制时机性裁剪保留期外旧行；
- v1 范围只做自动转发；LLM 行动项提取/每日摘要留待后续迭代。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.domains.assistant.campus.campus_store import (
    CampusStore,
)
from plugins.bot_unified_runtime.domains.render.plain_text import (
    redact_local_secrets,
)

_CAMPUS_FORWARD_INTRO = "【校园转发】"
# 单条转发正文预算（字符）；原文超预算截断，避免单条消息刷屏。
_CAMPUS_FORWARD_MAX_CHARS = 1500
_CAMPUS_KEEP_DAYS = 90


@dataclass(frozen=True)
class CampusSource:
    """来源门快照：装配期从 Config 构建，运行期只读。"""

    enabled: bool
    self_ids: frozenset[str]
    whitelist: frozenset[str]
    notify_qq: str
    push_bot_id: str
    persona_profile_id: str


def _id_list(value: Any) -> list[str]:
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def build_campus_source(config: Any) -> CampusSource:
    """从 Config 构建来源门快照；空值安全，账号/群号统一字符串化。"""
    return CampusSource(
        enabled=bool(getattr(config, "bot_campus_enabled", False)),
        self_ids=frozenset(_id_list(getattr(config, "bot_campus_self_ids", None))),
        whitelist=frozenset(
            _id_list(getattr(config, "bot_campus_group_whitelist", None))
        ),
        notify_qq=str(getattr(config, "bot_campus_notify_qq", "") or "").strip(),
        push_bot_id=str(getattr(config, "bot_campus_push_bot_id", "") or "").strip(),
        persona_profile_id=str(
            getattr(config, "bot_persona_profile_id", "default") or "default"
        ),
    )


def matches_campus_source(source: CampusSource, bot_id: str, group_id: str) -> bool:
    """三重来源门；白名单含 "*" 显式放行学校号全部群。"""
    if not source.enabled or not source.self_ids or not source.whitelist:
        return False
    if str(bot_id or "").strip() not in source.self_ids:
        return False
    if "*" in source.whitelist:
        return True
    return str(group_id or "").strip() in source.whitelist


def build_campus_forward_text(group_id: str, sender_name: str, text: str) -> str:
    """转发正文纯格式化——单一事实源（U17-CAMPUS-WIRE 规约指定形态）。

    自 ``_build_forward_request`` 内联四行原样提出：引导语+群号+发言人前缀，
    原文按前缀后剩余预算截断，超预算补省略号；输出与改前旁路逐字节相同。
    """
    who = f"{sender_name}：" if sender_name else ""
    prefix = f"{_CAMPUS_FORWARD_INTRO}群{group_id} {who}"
    budget = max(0, _CAMPUS_FORWARD_MAX_CHARS - len(prefix))
    return prefix + text[:budget] + ("…" if len(text) > budget else "")


@dataclass(frozen=True)
class CampusForwardPayload:
    """record() 载荷：域内纯数据，零出站语义。

    U17-CAMPUS-WIRE 收编后，出站请求（会话目标/去重/发送策略等）全部由
    中央管线 ``_complete`` 统一推导；本域只产出「正文 + 溯源五字段」，
    供根装配的两 builder 合成 IncomingMessage 与能力闭包。
    """

    group_id: str
    sender_name: str
    text: str
    message_id: str
    body: str


def build_campus_forward_message(
    source: CampusSource, payload: CampusForwardPayload
) -> IncomingMessage:
    """按目标会话（主人私聊）合成消息——异会话投递的既有表达。

    字段映射沿订阅推送/今天历史推送先例（root ``__init__.py``）：目标会话写进
    消息，由中央 ``_complete`` 推导出站目标；``group_id`` 恒为 ``None``——
    目标私聊绝不能带上学校群号（「绝不向学校群发消息」红线）。
    """
    return IncomingMessage(
        platform="nonebot",
        adapter="onebot.v11",
        bot_id=source.push_bot_id,
        session_id=f"private:{source.notify_qq}",
        session_type=SessionType.PRIVATE,
        sender_id=source.notify_qq,
        group_id=None,
        plain_text=payload.body,
        raw_segments=[{"type": "text", "data": {"text": payload.body}}],
        message_id=payload.message_id,
        privacy_level=PrivacyLevel.PERSONAL,
    )


def build_campus_forward_capability(
    source: CampusSource, payload: CampusForwardPayload
) -> Any:
    """构造校园转发能力闭包：body 原样上送，零平台发送面（先例同订阅推送）。"""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.campus_forward",
            kind="text",
            body=payload.body,
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PERSONAL,
            # persona:<id> 约定：中央 _resolve_persona_profile_id 据此保原值。
            audit_tags=["campus", "forward", f"persona:{source.persona_profile_id}"],
        )

    return capability


class CampusForwardService:
    """录制 + 转发决策：来源门内首条消息返回转发载荷，其余返回 None。"""

    def __init__(self, *, store: CampusStore, source: CampusSource) -> None:
        self.store = store
        self.source = source
        self._last_prune_date: str | None = None
        # record 经 asyncio.to_thread 调用，可能并发；裁剪日期游标需持锁。
        self._prune_lock = threading.Lock()

    def matches(self, bot_id: str, group_id: str) -> bool:
        return matches_campus_source(self.source, bot_id, group_id)

    def record(
        self,
        *,
        bot_id: str,
        group_id: str,
        sender_id: str = "",
        sender_name: str = "",
        text: str = "",
        message_id: str = "",
        now: datetime | None = None,
    ) -> CampusForwardPayload | None:
        """落库并决策：门内首条 → 转发载荷；门外/空文本/重复 → None。"""
        if not self.matches(bot_id, group_id):
            return None
        clean_text = str(text or "").strip()
        if not clean_text:
            # v1 只处理文本消息：纯图片/表情等空文本不落库不转发。
            return None
        current = now or datetime.now().astimezone()
        date_key = current.date().isoformat()
        self._maybe_prune(date_key, current)
        safe_id = str(message_id).strip() or (
            f"{bot_id}:{group_id}:{current.timestamp():.0f}"
        )
        inserted = self.store.record_message(
            message_id=safe_id,
            self_id=str(bot_id or "").strip(),
            group_id=str(group_id or "").strip(),
            sender_id=str(sender_id or "").strip(),
            sender_name=str(sender_name or "").strip(),
            text=clean_text,
            date_key=date_key,
            occurred_at=current.isoformat(timespec="seconds"),
        )
        if not inserted:
            return None
        return self._build_forward_payload(
            group_id=str(group_id or "").strip(),
            sender_name=str(sender_name or "").strip(),
            text=clean_text,
            message_id=safe_id,
        )

    def _build_forward_payload(
        self,
        *,
        group_id: str,
        sender_name: str,
        text: str,
        message_id: str,
    ) -> CampusForwardPayload:
        return CampusForwardPayload(
            group_id=group_id,
            sender_name=sender_name,
            text=text,
            message_id=message_id,
            # 单一事实源不变：正文逐字节契约由 build_campus_forward_text 承担。
            # U17-FIX：出站正文进 review 门之前过既有打码器（BOT_XXX=/盘符路径/
            # sk- 等形态），泄漏形态打码后再上送——主人收打码版而非原文裸奔，
            # 打码产物不再命中 review 泄漏形态（键值词干形态仍由 review 拦）。
            body=redact_local_secrets(
                build_campus_forward_text(group_id, sender_name, text)
            ),
        )

    def _maybe_prune(self, date_key: str, current: datetime) -> None:
        """跨天首条录制时机性裁剪；失败只记调试，不影响录制。"""
        with self._prune_lock:
            if self._last_prune_date == date_key:
                return
            self._last_prune_date = date_key
        try:
            self.store.prune(keep_days=_CAMPUS_KEEP_DAYS, now=current)
        except Exception:  # noqa: BLE001 - 裁剪失败不影响录制与转发。
            logging.getLogger(__name__).debug("校园记录清理失败，保留本轮录制与转发")
