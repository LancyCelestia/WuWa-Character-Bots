from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MailCommand:
    action: str
    account: str = ""
    recipient: str = ""
    subject: str = ""
    body: str = ""


def _email_address(value: str, *, field: str) -> str:
    cleaned = value.strip()
    _, parsed = parseaddr(cleaned)
    if not parsed or "@" not in parsed or parsed != cleaned:
        raise ValueError(f"{field}必须是完整邮箱地址。")
    return parsed


def parse_mail_command(text: str) -> MailCommand:
    normalized = text.strip()
    if normalized.startswith("/mail"):
        normalized = normalized[5:].strip()
    if not normalized:
        return MailCommand(action="help")

    action, _, remainder = normalized.partition(" ")
    action = action.lower()
    remainder = remainder.strip()
    if action in {"help", "status", "accounts", "pause", "resume"}:
        if remainder:
            raise ValueError(f"mail {action} 不接受额外参数。")
        return MailCommand(action=action)
    if action == "use":
        return MailCommand(
            action="use",
            account=_email_address(remainder, field="发件账户"),
        )
    if action != "send":
        raise ValueError("未知 mail 子命令。")

    parts = [part.strip() for part in remainder.split("|")]
    account = ""
    if parts and parts[0].lower().startswith("--from "):
        if len(parts) != 4:
            raise ValueError(
                "格式：/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>"
            )
        account = _email_address(parts[0][7:].strip(), field="发件账户")
        recipient, subject, body = parts[1:]
    else:
        if len(parts) != 3:
            raise ValueError("格式：/mail send <收件邮箱> | <主题> | <正文>")
        recipient, subject, body = parts
    recipient = _email_address(recipient, field="收件邮箱")
    if not subject:
        raise ValueError("邮件主题不能为空。")
    if not body:
        raise ValueError("邮件正文不能为空。")
    return MailCommand(
        action="send",
        account=account,
        recipient=recipient,
        subject=subject,
        body=body,
    )


class MailBridgeState:
    _MAIL_ID_LIMIT = 512

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._paused = False
        self._selected_accounts: dict[str, str] = {}
        self._notified_mail_ids: list[str] = []
        self._replied_mail_ids: list[str] = []
        self._reply_claims: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError):
            return
        if not isinstance(data, dict):
            return
        self._paused = bool(data.get("paused", False))
        selected = data.get("selected_accounts", {})
        if isinstance(selected, dict):
            self._selected_accounts = {
                str(actor): str(account)
                for actor, account in selected.items()
                if str(actor).strip() and str(account).strip()
            }
        self._notified_mail_ids = self._load_mail_ids(data.get("notified_mail_ids"))
        self._replied_mail_ids = self._load_mail_ids(data.get("replied_mail_ids"))

    @classmethod
    def _load_mail_ids(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return list(dict.fromkeys(cleaned[-cls._MAIL_ID_LIMIT :]))

    @staticmethod
    def _mail_key(mail_id: str, account: str) -> str:
        normalized_id = str(mail_id).strip()
        normalized_account = str(account).strip().lower()
        if not normalized_id or not normalized_account:
            return ""
        return f"{normalized_account}:{normalized_id}"

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "paused": self._paused,
                    "selected_accounts": self._selected_accounts,
                    "notified_mail_ids": self._notified_mail_ids,
                    "replied_mail_ids": self._replied_mail_ids,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        # Windows 文件扫描器/索引器可能瞬时锁住刚写入的临时文件，
        # 短暂重试原子替换，避免丢失去重状态后重复通知。
        for attempt in range(5):
            try:
                temporary.replace(self.path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            self._save()

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._save()

    def select_account(self, actor_id: str, account: str) -> None:
        actor = str(actor_id).strip()
        if not actor:
            raise ValueError("管理员用户 ID 不能为空。")
        validated = _email_address(account, field="发件账户")
        with self._lock:
            self._selected_accounts[actor] = validated
            self._save()

    def selected_account(self, actor_id: str) -> str:
        with self._lock:
            return self._selected_accounts.get(str(actor_id).strip(), "")

    def claim_notification(self, mail_id: str, account: str) -> bool:
        key = self._mail_key(mail_id, account)
        if not key:
            return False
        with self._lock:
            if key in self._notified_mail_ids:
                return False
            self._notified_mail_ids.append(key)
            self._notified_mail_ids = self._notified_mail_ids[-self._MAIL_ID_LIMIT :]
            self._save()
            return True

    def claim_reply(self, mail_id: str, account: str) -> bool:
        key = self._mail_key(mail_id, account)
        if not key:
            return False
        with self._lock:
            if key in self._replied_mail_ids or key in self._reply_claims:
                return False
            self._reply_claims.add(key)
            return True

    def release_reply(self, mail_id: str, account: str) -> None:
        key = self._mail_key(mail_id, account)
        if not key:
            return
        with self._lock:
            self._reply_claims.discard(key)

    def mark_reply_sent(self, mail_id: str, account: str) -> None:
        key = self._mail_key(mail_id, account)
        if not key:
            return
        with self._lock:
            self._reply_claims.discard(key)
            if key not in self._replied_mail_ids:
                self._replied_mail_ids.append(key)
                self._replied_mail_ids = self._replied_mail_ids[-self._MAIL_ID_LIMIT :]
                self._save()


def mail_event_id(event: Any) -> str:
    """Return the adapter-provided Message-ID for a mail event.

    ``nonebot-adapter-mail`` stores the RFC ``Message-ID`` in ``id``.  A
    separate ``message_id`` attribute is accepted for adapter/test doubles
    that use that conventional name.  Do not use a generated request ID here:
    it changes on every delivery and defeats duplicate suppression.
    """
    for name in ("id", "message_id"):
        value = str(getattr(event, name, "") or "").strip()
        if value:
            return value
    return ""


def mail_event_fingerprint(event: Any) -> str:
    """Return a deterministic fallback key when an adapter omits Message-ID."""
    get_plaintext = getattr(event, "get_plaintext", None)
    if callable(get_plaintext):
        try:
            body = get_plaintext()
        except Exception:  # noqa: BLE001 - a missing body must not break deduplication.
            body = ""
    else:
        body = getattr(event, "body", "")
    stable_fields = (
        str(getattr(getattr(event, "sender", None), "id", "") or "").strip().lower(),
        str(getattr(event, "subject", "") or "").strip(),
        str(getattr(event, "date", "") or "").strip(),
        str(getattr(event, "in_reply_to", "") or "").strip(),
        str(body or "").strip(),
    )
    if not any(stable_fields):
        return ""
    digest = hashlib.sha256("\x1f".join(stable_fields).encode("utf-8")).hexdigest()
    return f"fingerprint:{digest}"


def mail_event_dedupe_id(event: Any) -> tuple[str, bool]:
    """Return ``(key, is_fallback)`` for notification/reply deduplication."""
    event_id = mail_event_id(event)
    if event_id:
        return event_id, False
    return mail_event_fingerprint(event), True


def _adapter_name(bot: Any) -> str:
    adapter = getattr(bot, "adapter", None)
    get_name = getattr(adapter, "get_name", None)
    return str(get_name() if callable(get_name) else "").strip().lower()


def connected_mail_accounts(
    bots: Mapping[str, Any],
    aliases: Mapping[str, str] | None = None,
) -> list[str]:
    connected = {
        str(getattr(bot, "self_id", "")).strip()
        for bot in bots.values()
        if _adapter_name(bot) == "mail" and str(getattr(bot, "self_id", "")).strip()
    }
    connected_lower = {account.lower() for account in connected}
    for alias, auth_account in (aliases or {}).items():
        if str(auth_account).strip().lower() in connected_lower:
            connected.add(str(alias).strip())
    return sorted(account for account in connected if account)


def unresolved_mail_aliases(
    bots: Mapping[str, Any],
    aliases: Mapping[str, str] | None = None,
) -> list[str]:
    """Return aliases whose authentication target has no connected Mail Bot."""
    connected = {
        str(getattr(bot, "self_id", "")).strip().lower()
        for bot in bots.values()
        if _adapter_name(bot) == "mail" and str(getattr(bot, "self_id", "")).strip()
    }
    errors: list[str] = []
    for alias, auth_account in (aliases or {}).items():
        alias_text = str(alias).strip()
        auth_text = str(auth_account).strip()
        if alias_text and auth_text and auth_text.lower() not in connected:
            errors.append(f"{alias_text}->{auth_text}")
    return sorted(errors)


async def send_mail_from_account(
    bots: Mapping[str, Any],
    *,
    account: str,
    recipient: str,
    subject: str,
    body: str,
    aliases: Mapping[str, str] | None = None,
) -> None:
    sender = _email_address(account, field="发件账户")
    alias_map = {
        str(alias).strip().lower(): str(auth).strip()
        for alias, auth in (aliases or {}).items()
    }
    auth_account = alias_map.get(sender.lower(), sender)
    wanted = _email_address(auth_account, field="认证账户").lower()
    target = next(
        (
            bot
            for bot in bots.values()
            if _adapter_name(bot) == "mail"
            and str(getattr(bot, "self_id", "")).strip().lower() == wanted
        ),
        None,
    )
    if target is None:
        raise ValueError(f"发件账户未连接：{account}")
    recipient = _email_address(recipient, field="收件邮箱")
    if sender.lower() != wanted:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        await target.send_mail(message)
        return
    await target.send_to(recipient, body, subject=subject)


async def notify_telegram_admins(
    bots: Mapping[str, Any],
    chat_ids: Sequence[str],
    message: str,
) -> int:
    telegram_bot = next(
        (bot for bot in bots.values() if _adapter_name(bot) == "telegram"),
        None,
    )
    if telegram_bot is None:
        return 0
    sent = 0
    for chat_id in dict.fromkeys(str(item).strip() for item in chat_ids if str(item).strip()):
        await telegram_bot.send_to(chat_id, message)
        sent += 1
    return sent


def build_mail_notification(
    event: Any,
    *,
    account: str,
    max_preview_chars: int = 280,
) -> str:
    sender = getattr(event, "sender", None)
    sender_id = str(getattr(sender, "id", "unknown") or "unknown")
    sender_name = str(getattr(sender, "name", "") or "").strip()
    sender_label = f"{sender_name} <{sender_id}>" if sender_name else sender_id
    subject = str(getattr(event, "subject", "(无主题)") or "(无主题)").strip()
    get_plaintext = getattr(event, "get_plaintext", None)
    body = str(get_plaintext() if callable(get_plaintext) else "")
    preview = " ".join(body.split())
    limit = max(20, int(max_preview_chars))
    if len(preview) > limit:
        preview = preview[: limit - 1].rstrip() + "…"
    return (
        "📧 收到新邮件\n"
        f"收件账户：{account}\n"
        f"发件人：{sender_label}\n"
        f"主题：{subject}\n"
        f"摘要：{preview or '(无纯文本正文)'}"
    )


def is_telegram_admin(event: Any, admin_ids: Sequence[str]) -> bool:
    allowed = {str(item).strip() for item in admin_ids if str(item).strip()}
    if not allowed:
        return False
    get_user_id = getattr(event, "get_user_id", None)
    user_id = str(get_user_id() if callable(get_user_id) else "")
    chat_id = str(getattr(getattr(event, "chat", None), "id", ""))
    return bool({user_id, chat_id} & allowed)

async def execute_mail_command(
    command: MailCommand,
    *,
    actor_id: str,
    bots: Mapping[str, Any],
    state: MailBridgeState,
    aliases: Mapping[str, str] | None = None,
) -> str:
    accounts = connected_mail_accounts(bots, aliases)
    if command.action == "help":
        return (
            "邮件控制命令：\n"
            "/mail status\n"
            "/mail accounts\n"
            "/mail use <发件邮箱>\n"
            "/mail send <收件邮箱> | <主题> | <正文>\n"
            "/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>\n"
            "/mail pause\n"
            "/mail resume"
        )
    if command.action == "status":
        state_text = "已暂停" if state.paused else "运行中"
        selected = state.selected_account(actor_id) or "未选择"
        account_text = "、".join(accounts) if accounts else "无"
        return (
            f"邮件桥状态：{state_text}\n"
            f"已连接账户：{account_text}\n"
            f"当前发件账户：{selected}"
        )
    if command.action == "accounts":
        return "已连接邮箱：" + ("、".join(accounts) if accounts else "无")
    if command.action == "pause":
        state.pause()
        return "邮件自动回复已暂停；收信提醒仍可继续。"
    if command.action == "resume":
        state.resume()
        return "邮件自动回复已恢复。"
    if command.action == "use":
        if command.account not in accounts:
            raise ValueError(f"发件账户未连接：{command.account}")
        state.select_account(actor_id, command.account)
        return f"当前发件账户已切换为：{command.account}"
    if command.action == "send":
        account = command.account or state.selected_account(actor_id)
        if not account:
            raise ValueError("尚未选择发件账户，请先使用 /mail use <发件邮箱>。")
        await send_mail_from_account(
            bots,
            account=account,
            recipient=command.recipient,
            subject=command.subject,
            body=command.body,
            aliases=aliases,
        )
        if command.account:
            state.select_account(actor_id, command.account)
        return f"邮件发送成功：{account} → {command.recipient}"
    raise ValueError("未知 mail 子命令。")
