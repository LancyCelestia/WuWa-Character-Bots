"""校园自动转发（campus v1）：学校 QQ 账号群消息 → 主人私聊实时转发。

设计约束：

- **纯监听**：对学校群只读不写，本模块绝不向任何群发送消息；
- **三重来源门**：总开关 ∧ 学校账号（self_ids）∧ 群白名单，任一为空整链路
  关闭——绝不猜账号、绝不猜群；白名单支持 ``*`` 显式放行学校号全部群；
- **幂等**：message_id 去重，NapCat 断线重连重发不会双推；
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
    PrivacyLevel,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.assistant.campus.campus_store import (
    CampusStore,
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


class CampusForwardService:
    """录制 + 转发决策：来源门内首条消息返回私聊 SendRequest，其余返回 None。"""

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
    ) -> SendRequest | None:
        """落库并决策：门内首条 → 转发请求；门外/空文本/重复 → None。"""
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
        return self._build_forward_request(
            group_id=str(group_id or "").strip(),
            sender_name=str(sender_name or "").strip(),
            text=clean_text,
            message_id=safe_id,
        )

    def _build_forward_request(
        self,
        *,
        group_id: str,
        sender_name: str,
        text: str,
        message_id: str,
    ) -> SendRequest:
        who = f"{sender_name}：" if sender_name else ""
        prefix = f"{_CAMPUS_FORWARD_INTRO}群{group_id} {who}"
        budget = max(0, _CAMPUS_FORWARD_MAX_CHARS - len(prefix))
        body = prefix + text[:budget] + ("…" if len(text) > budget else "")
        request_id = f"campus-fwd-{message_id}"
        return SendRequest(
            request_id=request_id,
            session_id=f"private:{self.source.notify_qq}",
            target_scope=SessionType.PRIVATE,
            target_id=self.source.notify_qq,
            capability_id="bot.campus_forward",
            content=RenderedOutput(
                request_id=request_id,
                content_type="text",
                content_ref={},
                text_fallback=body,
                privacy_level=PrivacyLevel.PERSONAL,
            ),
            send_policy=SendPolicy.QUEUED,
            priority="normal",
            max_messages=1,
            dedupe_key=f"campus_fwd:{message_id}",
            cooldown_key=f"campus_fwd:{self.source.notify_qq}",
            privacy_level=PrivacyLevel.PERSONAL,
            persona_profile_id=self.source.persona_profile_id,
            bot_id=self.source.push_bot_id,
            audit_tags=["campus", "forward"],
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
