from __future__ import annotations

import re

from plugins.wuwa_unified_runtime.contracts import SessionType
from plugins.wuwa_unified_runtime.contracts.auto_send import AutoSendIntent, RecipientDescriptor

_COMMAND_RE = re.compile(
    r"^报存\s*给\s*(?P<recipients>.+?)\s*发(?P<channel>邮件|消息)"
    r"(?:[，,:：]\s*(?P<rest>.*))?$"
)


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
