from __future__ import annotations

import re

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    PrivacyLevel,
    ReviewAction,
    ReviewResult,
    RiskLevel,
    SessionType,
)

_INTERNAL_OUTPUT_MARKERS = (
    "[UNTRUSTED_USER_TEXT]",
    "[/UNTRUSTED_USER_TEXT]",
    "[TRUSTED_SYSTEM]",
    "[/TRUSTED_SYSTEM]",
)

_SECRET_OUTPUT_PATTERNS = (
    re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*\S+"),
    re.compile(r"(?i)\btoken\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bcookie\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bauthkey\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bauthorization\s*[:=]\s*bearer\s+\S+"),
    re.compile(r"(?i)\bbearer\s+sk-[A-Za-z0-9._-]+"),
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]{8,}"),
)

_PERSONA_DRIFT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "self_identified_as_generic_ai",
        re.compile(
            r"(?i)(作为|我是|我只是|我仅是)\s*(一个|一名)?\s*"
            r"(chatgpt|openai|ai\s*语言模型|ai\s*助手|人工智能|大语言模型|语言模型)"
        ),
    ),
    (
        "english_generic_ai_identity",
        re.compile(
            r"(?i)\b(as\s+an?\s+|i\s*(am|'m)\s+)"
            r"(ai|chatgpt|large language model|language model|openai)\b"
        ),
    ),
    (
        "refused_configured_persona",
        re.compile(r"(不能|无法).{0,8}(真正)?(成为|扮演|作为).{0,12}(守岸人|角色|人格)"),
    ),
    (
        "denied_persona",
        re.compile(r"(我没有|不具备).{0,8}(人格|角色|人设)"),
    ),
)


def _redact_output_match(value: str) -> str:
    redacted = value
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|token|cookie|authkey)\s*[:=]\s*\S+",
        lambda match: f"{match.group(1)}=[redacted]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\bauthorization\s*[:=]\s*bearer\s+\S+",
        "authorization=Bearer [redacted]",
        redacted,
    )
    redacted = re.sub(r"(?i)\bbearer\s+sk-[A-Za-z0-9._-]+", "Bearer [redacted]", redacted)
    redacted = re.sub(r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]{8,}", "sk-[redacted]", redacted)
    return redacted


def _unsafe_output_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    if any(marker in text for marker in _INTERNAL_OUTPUT_MARKERS):
        reasons.append("unsafe output leakage")

    matched_fragments = [
        _redact_output_match(match.group(0))
        for pattern in _SECRET_OUTPUT_PATTERNS
        for match in pattern.finditer(text)
    ]
    if matched_fragments:
        reasons.append("unsafe output leakage")
        reasons.append(f"redacted fragments: {', '.join(matched_fragments)}")

    deduped: list[str] = []
    for reason in reasons:
        if reason in deduped:
            continue
        deduped.append(reason)
    return deduped


def _persona_drift_reasons(result: CapabilityResult, text: str) -> list[str]:
    if result.capability_id != "bot.chat":
        return []
    return [
        f"persona drift: {name}"
        for name, pattern in _PERSONA_DRIFT_PATTERNS
        if pattern.search(text)
    ]


def review_capability_result(
    result: CapabilityResult,
    decision: BotDecision,
) -> ReviewResult:
    reasons: list[str] = []
    action = ReviewAction.ALLOW
    approved = True
    output_text = result.body or result.summary or result.title

    if result.risk_level is RiskLevel.CRITICAL:
        approved = False
        action = ReviewAction.BLOCK
        reasons.append("critical risk is blocked")

    unsafe_reasons = _unsafe_output_reasons(output_text)
    if unsafe_reasons:
        approved = False
        action = ReviewAction.BLOCK
        reasons.extend(unsafe_reasons)

    persona_drift_reasons = _persona_drift_reasons(result, output_text)
    if persona_drift_reasons:
        approved = False
        action = ReviewAction.BLOCK
        reasons.extend(persona_drift_reasons)

    if (
        result.privacy_level in {PrivacyLevel.PERSONAL, PrivacyLevel.CREDENTIALED}
        and decision.target_scope is SessionType.GROUP
    ):
        approved = False
        if action is not ReviewAction.BLOCK:
            action = ReviewAction.MOVE_PRIVATE
        reasons.append("personal output cannot be sent to group")

    return ReviewResult(
        request_id=result.request_id,
        approved=approved,
        action=action,
        risk_level=result.risk_level,
        privacy_level=result.privacy_level,
        reasons=reasons,
        safe_text=output_text,
        debug_id=result.debug_id,
    )
