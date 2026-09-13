"""搜图能力（bot.image_search）：『搜图 [图片]』或引用/含图消息触发 SauceNAO 反搜。"""

from __future__ import annotations

import re
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
)
from plugins.bot_unified_runtime.sources.sauce_search import search_saucenao_ex

_TRIGGER_RE = re.compile(r"^[/!！]?搜图\s*$|^[/!！]?搜图\s+\S+", re.IGNORECASE)


def _extract_image_url(message: IncomingMessage) -> str:
    for segment in message.raw_segments or []:
        if str(segment.get("type", "")).strip().lower() == "image":
            data = segment.get("data") or {}
            value = str(data.get("url") or data.get("file") or "")
            if value.startswith("http"):
                return value
    return ""


def build_image_search_capability(config: Any | None = None):
    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        text = message.plain_text.strip()
        if not _TRIGGER_RE.match(text):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.image_search",
                kind="text",
                body="",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["image_search", "skip_no_trigger"],
            )
        image_url = _extract_image_url(message)
        if not image_url and message.reply_to_text:
            # 审计#35：引用消息拿不到原图 URL；旧实现此处赋空串是死分支，静默落通用提示。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.image_search",
                kind="text",
                body="引用消息里的原图链接拿不到，把图片和『搜图』发在同一条消息里再试一次。",
                audit_tags=["image_search", "image_search_reply_hint"],
            )
        if not image_url:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.image_search",
                kind="text",
                body="把要搜的图片和『搜图』发在同一条消息里，或直接发图后跟上搜图指令。",
                audit_tags=["image_search", "missing_image"],
            )
        hits, error_kind = search_saucenao_ex(image_url, config=config)
        if error_kind == "no_key":
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.image_search",
                kind="text",
                body="反搜服务还没配置 API key（SAUCENAO_API_KEY），暂时搜不了。",
                audit_tags=["image_search", "no_key"],
            )
        if error_kind == "http_error":
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.image_search",
                kind="text",
                body="反搜服务暂时连不上（SauceNAO 超时/拒绝），稍后再试一次。",
                audit_tags=["image_search", "service_error"],
            )
        if not hits:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.image_search",
                kind="text",
                body=(
                    "没有找到相似图源（图源站点未收录，或 QQ 图床链接被图源拒绝抓取；"
                    "可以试试直接发原图文件再搜）。"
                ),
                audit_tags=["image_search", "not_found"],
            )
        lines = ["反搜结果（按相似度）："]
        for index, hit in enumerate(hits, start=1):
            line = f"{index}. {hit.similarity:.1f}%"
            if hit.title:
                line += f" {hit.title[:40]}"
            if hit.member:
                line += f"｜作者：{hit.member[:24]}"
            if hit.url:
                line += f"\n   {hit.url}"
            lines.append(line)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.image_search",
            kind="text",
            body="\n".join(lines),
            url=hits[0].url or None,
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["image_search", "saucenao"],
        )

    return capability
