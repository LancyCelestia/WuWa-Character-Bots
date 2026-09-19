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
    re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*(?!(?:set|missing|\[redacted\])\b)\S+"),
    re.compile(r"(?i)\btoken\s*[:=]\s*(?!(?:set|missing|\[redacted\])\b)\S+"),
    re.compile(r"(?i)\bcookie\s*[:=]\s*(?!(?:set|missing|\[redacted\])\b)\S+"),
    re.compile(r"(?i)\bauthkey\s*[:=]\s*(?!(?:set|missing|\[redacted\])\b)\S+"),
    re.compile(r"(?i)\bauthorization\s*[:=]\s*bearer\s+\S+"),
    re.compile(r"(?i)\bbearer\s+sk-[A-Za-z0-9._-]+"),
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]{8,}"),
)


_PUBLIC_OUTPUT_UNSAFE = (
    ("sexual output", re.compile(r"(露骨性行为|性交|色情描写|裸体细节|r[- ]?18)", re.IGNORECASE)),
    ("graphic violence output", re.compile(r"(肢解|虐杀细节|血腥描写|酷刑细节)", re.IGNORECASE)),
    ("harassment output", re.compile(r"(你这个废物|你是个傻逼|公开羞辱|去死吧)", re.IGNORECASE)),
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


# 媒体/前置部件里可能承载「会出门的文本」的键。
# 分两档用：泄漏面（密钥、内部标记）扫全部键；内容面（露骨/暴力/辱骂）只扫
# **消息载荷**那几个键——卡片里的 `label`/`description` 常是上游原文（新闻标题、
# 公告摘录），拿内容面去裁它们会把正常卡片误杀。
_META_TEXT_KEYS: tuple[str, ...] = (
    "text", "content", "caption", "alt", "label", "name", "title", "description",
    "review_text",
)
_PAYLOAD_TEXT_KEYS: tuple[str, ...] = ("text", "content", "caption", "alt", "review_text")
_MEDIA_FIELDS: tuple[str, ...] = (
    "images", "audio", "video", "files", "prefix_parts", "actions",
)


def _iter_part_texts(item: object, keys: tuple[str, ...]) -> list[str]:
    if isinstance(item, str):
        return [item] if item.strip() else []
    if not isinstance(item, dict):
        return []
    found: list[str] = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value)
    return found


def _collect_scan_text(result: CapabilityResult, primary: str, keys: tuple[str, ...]) -> str:
    """把会出门的文本汇成一条待审串。

    ⚠️ 这只喂规则，**不参与 `safe_text`**：`renderer.py` 拿 `safe_text` 当外发正文，
    把媒体文本混进去会让一条音频额外发成一条文字消息。
    """
    chunks: list[str] = [primary] if primary.strip() else []
    for part in result.text_parts or []:
        chunks.extend(_iter_part_texts(part, ("text",)))
    for field in _MEDIA_FIELDS:
        for item in getattr(result, field, None) or []:
            chunks.extend(_iter_part_texts(item, keys))
    return "\n".join(dict.fromkeys(chunks))


def review_capability_result(
    result: CapabilityResult,
    decision: BotDecision,
) -> ReviewResult:
    reasons: list[str] = []
    action = ReviewAction.ALLOW
    approved = True
    output_text = result.body or result.summary or result.title
    # 泄漏面（密钥/内部标记）与内容面（露骨/暴力/辱骂）各扫各的文本集：
    # 过去两者都只看 body→summary→title，媒体能力把这三样留空 ⇒ 审核恒无输入。
    leak_text = _collect_scan_text(result, output_text, _META_TEXT_KEYS)
    payload_text = _collect_scan_text(result, output_text, _PAYLOAD_TEXT_KEYS)

    if result.risk_level is RiskLevel.CRITICAL:
        approved = False
        action = ReviewAction.BLOCK
        reasons.append("critical risk is blocked")

    unsafe_reasons = _unsafe_output_reasons(leak_text)
    if unsafe_reasons:
        approved = False
        action = ReviewAction.BLOCK
        reasons.extend(unsafe_reasons)

    if decision.target_scope is SessionType.GROUP:
        # 不再限定 `bot.chat`：任何能力把不安全内容发进群都该拦（媒体能力免检
        # 是 M-02 的中央半）。persona 审仍只看 chat 自己的话——语音命令的正文
        # 是用户原文，不该被当成「守岸人自述」。
        for label, pattern in _PUBLIC_OUTPUT_UNSAFE:
            if pattern.search(payload_text):
                approved = False
                action = ReviewAction.BLOCK
                reasons.append(label)

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
