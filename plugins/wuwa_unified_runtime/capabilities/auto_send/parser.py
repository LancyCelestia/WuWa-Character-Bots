from __future__ import annotations

import re

from plugins.wuwa_unified_runtime.contracts import SessionType
from plugins.wuwa_unified_runtime.contracts.auto_send import AutoSendIntent, RecipientDescriptor

_COMMAND_RE = re.compile(
    r"^报存\s*给\s*(?P<recipients>.+?)\s*发(?P<channel>邮件|消息)"
    r"(?:[，,:：]\s*(?P<rest>.*))?$"
)


def is_auto_send_command_text(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("报存 ") and _COMMAND_RE.match(stripped) is not None


def _split_recipients(raw: str) -> list[RecipientDescriptor]:
    parts = [part.strip() for part in re.split(r"[、,，]", raw) if part.strip()]
    return [RecipientDescriptor(raw_text=part, kind="alias", display_name=part) for part in parts]


def _extract_instruction(rest: str | None) -> tuple[str, str | None]:
    if not rest:
        return "", None

    subject: str | None = None
    content = rest.strip()
    subject_match = re.search(r"主题[:：]\s*(?P<subject>[^，,]+)", content)
    if subject_match:
        subject = subject_match.group("subject").strip()
    content_match = re.search(r"内容(?P<content>.+)$", content)
    if content_match:
        content = content_match.group("content").lstrip(":：，, ").strip()
    return content, subject


def parse_auto_send_command(
    text: str,
    actor_sender_id: str,
    actor_session_id: str,
    actor_session_type: SessionType,
) -> AutoSendIntent:
    match = _COMMAND_RE.match(text.strip())
    if not match:
        raise ValueError("unsupported auto-send command")

    channel = "email" if match.group("channel") == "邮件" else "chat_message"
    content_instruction, subject_instruction = _extract_instruction(match.group("rest"))
    return AutoSendIntent(
        actor_sender_id=actor_sender_id,
        actor_session_id=actor_session_id,
        actor_session_type=actor_session_type,
        channel=channel,
        action="draft",
        raw_command_text=text,
        recipient_descriptors=_split_recipients(match.group("recipients")),
        content_instruction=content_instruction,
        subject_instruction=subject_instruction,
        personalization_mode="light",
        batch_mode="batch",
        requested_send_policy="confirm_required",
        priority="user_waiting",
        risk_level="medium" if channel == "email" else "low",
        privacy_level="personal",
    )


def build_auto_send_preview_text(
    text: str,
    actor_sender_id: str,
    actor_session_id: str,
    actor_session_type: SessionType = SessionType.PRIVATE,
) -> str:
    intent = parse_auto_send_command(
        text,
        actor_sender_id=actor_sender_id,
        actor_session_id=actor_session_id,
        actor_session_type=actor_session_type,
    )
    recipients = "、".join(descriptor.raw_text for descriptor in intent.recipient_descriptors)
    channel_name = "邮件" if intent.channel == "email" else "消息"
    subject = f"\n主题：{intent.subject_instruction}" if intent.subject_instruction else ""
    content = intent.content_instruction or "未填写正文要求"
    return (
        "草稿预览（仅预览，M0 不会真实发送）\n"
        f"通道：{channel_name}\n"
        f"收件人：{recipients}"
        f"{subject}\n"
        f"内容要求：{content}\n"
        "下一步：后续版本会生成 draft_id，再进行确认流程。"
    )
