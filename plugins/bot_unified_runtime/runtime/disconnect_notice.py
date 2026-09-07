"""机器人掉线管理员通知。

思路来自 nonebot_plugin_disconnect_notice：掉线瞬间 QQ 通道本身不可用，
因此通知改走仍然在线的其他适配器（Telegram 管理员私聊、邮件桥），
并按 bot 维度做冷却，避免连接抖动刷屏。任何渠道失败都不抛出。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from plugins.bot_unified_runtime.mail_bridge import (
    notify_telegram_admins,
    send_mail_from_account,
)


@dataclass(frozen=True)
class DisconnectNoticeOptions:
    enabled: bool = False
    cooldown_seconds: float = 600.0
    mail_account: str = ""
    mail_recipients: tuple[str, ...] = ()
    telegram_chat_ids: tuple[str, ...] = ()


def disconnect_notice_options_from(config: Any) -> DisconnectNoticeOptions:
    return DisconnectNoticeOptions(
        enabled=bool(getattr(config, "bot_disconnect_notice_enabled", False)),
        cooldown_seconds=max(
            0.0,
            float(getattr(config, "bot_disconnect_notice_cooldown_seconds", 600.0) or 0.0),
        ),
        mail_account=str(getattr(config, "bot_disconnect_notice_mail_account", "") or "").strip(),
        mail_recipients=tuple(
            str(item).strip()
            for item in getattr(config, "bot_disconnect_notice_mail_recipients", ()) or ()
            if str(item).strip()
        ),
        telegram_chat_ids=tuple(
            str(item).strip()
            for item in getattr(config, "bot_disconnect_notice_telegram_chat_ids", ()) or ()
            if str(item).strip()
        ),
    )


def adapter_display_name(bot: Any) -> str:
    adapter = getattr(bot, "adapter", None)
    get_name = getattr(adapter, "get_name", None)
    try:
        name = str(get_name() if callable(get_name) else "") or str(
            getattr(bot, "adapter_name", "") or ""
        )
    except Exception:  # noqa: BLE001 - 适配器命名失败不阻塞通知。
        name = ""
    return name or "未知适配器"


def build_disconnect_notice_text(bot_id: str, adapter_name: str, reason: str = "") -> str:
    label = adapter_name or "未知适配器"
    suffix = f"\n原因：{reason.strip()}" if (reason or "").strip() else ""
    return (
        "🔌 机器人掉线通知\n"
        f"适配器：{label}\n"
        f"账号：{bot_id}{suffix}\n"
        "请尽快检查 NapCat 与网络状态。"
    )


class DisconnectNotifier:
    """带冷却的多渠道掉线通知器；冷却判定在发送前记账，渠道失败只跳过。"""

    def __init__(
        self,
        options: DisconnectNoticeOptions,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._options = options
        self._clock = clock
        self._last_sent_at: dict[str, float] = {}

    def _cooldown_allows(self, key: str) -> bool:
        now = self._clock()
        last = self._last_sent_at.get(key)
        if last is not None and now - last < self._options.cooldown_seconds:
            return False
        self._last_sent_at[key] = now
        return True

    async def notify(
        self,
        bots: Mapping[str, Any],
        *,
        bot_id: str,
        adapter_name: str = "",
        reason: str = "",
    ) -> list[str]:
        """投递掉线通知，返回已成功投递的渠道列表。"""
        if not self._options.enabled:
            return []
        key = f"{adapter_name or 'bot'}:{bot_id}"
        if not self._cooldown_allows(key):
            return []
        text = build_disconnect_notice_text(bot_id, adapter_name, reason)
        delivered: list[str] = []
        if self._options.telegram_chat_ids:
            try:
                sent = await notify_telegram_admins(
                    bots, self._options.telegram_chat_ids, text
                )
                if sent:
                    delivered.append("telegram")
            except Exception:  # noqa: S110, BLE001 - Telegram 通知失败时静默回退邮件渠道。
                pass
        if self._options.mail_account and self._options.mail_recipients:
            for recipient in self._options.mail_recipients:
                try:
                    await send_mail_from_account(
                        bots,
                        account=self._options.mail_account,
                        recipient=recipient,
                        subject="【机器人掉线通知】",
                        body=text,
                    )
                    delivered.append(f"mail:{recipient}")
                except Exception:  # noqa: S112, BLE001 - 单个收件人失败跳过，继续其他渠道。
                    continue
        return delivered
