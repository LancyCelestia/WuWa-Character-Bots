"""搜图能力（bot.image_search）：『搜图 [图片]』或引用/含图消息触发 SauceNAO 反搜。"""

from __future__ import annotations

import random
import re
from typing import Any

from plugins.bot_unified_runtime.capabilities import user_copy
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
)

_TRIGGER_RE = re.compile(r"^[/!！]?搜图\s*$|^[/!！]?搜图\s+\S+", re.IGNORECASE)


def _reverse_search_via_invoker(
    image_url: str, config: Any | None, *, principal: str, roles: tuple[str, ...]
) -> tuple[list[dict[str, Any]], str]:
    """反搜执行经**中央调度层**（Wave 1 接入 · 规格 §1 D-b「换调用点」）。

    返回 ``(hits, status)``；``status`` 是 ``InvocationStatus`` 的 value。
    真身 ``search_saucenao_ex`` 不在这里直呼——唯一直呼点收在壳的受控适配器
    ``_handle_media_anime_ip``（descriptor ``media.vision.anime_ip``），于是这次执行
    额外拿到中央面的载荷限额 / SSRF 入口复核 / 健康与降级链 / 审计记账。

    诚实约束：非 ``ok`` 终态**一律返回空命中**，由调用方落到既有的失败文案分支，
    绝不用空 data 拼一张"看起来成功"的结果卡。
    """
    # 函数体内 import：与仓内既有惯例一致（避免域件与 runtime 壳的装配期环依赖）。
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
        default_invoker,
    )

    invocation = default_invoker().invoke(
        CapabilityRequest(
            capability_id="media.vision.anime_ip",
            payload={"image_url": image_url},
            principal=principal,
            roles=roles,
        ),
        config=config,
    )
    status = str(invocation.status.value)
    if invocation.status is not InvocationStatus.OK:
        return [], status
    raw = invocation.data.get("hits") or []
    return [dict(hit) for hit in raw if isinstance(hit, dict)], status


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
        hits, status = _reverse_search_via_invoker(
            image_url,
            config,
            principal=str(message.sender_id or "anonymous"),
            roles=tuple(message.sender_roles) or ("user",),
        )
        if status == "not_configured":
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.image_search",
                kind="text",
                body="反搜服务还没配置 API key（SAUCENAO_API_KEY），暂时搜不了。",
                audit_tags=["image_search", "no_key", "orchestration:not_configured"],
            )
        if status in ("degraded", "failed"):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.image_search",
                kind="text",
                # 审查 Q-01：入 user_copy 数据源失败池（原「……稍后再试一次。」）。
                # 中央 degraded/failed 就是旧 error_kind=="http_error" 的落点：
                # 真身返回的 error_kind 经壳逐态映射回来，文案一字未改。
                body=random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(
                    reason="反搜服务暂时连不上（SauceNAO 超时/拒绝）"
                ),
                audit_tags=["image_search", "service_error", f"orchestration:{status}"],
            )
        if status != "ok":
            # 接入后才可能出现的中央终态（denied/unavailable/timeout/…）：
            # 旧直呼不存在这些条件，故是新文案；仍走同一失败池，且**绝不带命中**。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.image_search",
                kind="text",
                body=random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(
                    reason=f"反搜服务当前不可用（中央调度层判据：{status}）"
                ),
                audit_tags=["image_search", "service_error", f"orchestration:{status}"],
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
                audit_tags=["image_search", "not_found", "orchestration:ok"],
            )
        lines = ["反搜结果（按相似度）："]
        for index, hit in enumerate(hits, start=1):
            line = f"{index}. {float(hit.get('similarity') or 0):.1f}%"
            title = str(hit.get("title") or "")
            member = str(hit.get("member") or "")
            url = str(hit.get("url") or "")
            if title:
                line += f" {title[:40]}"
            if member:
                line += f"｜作者：{member[:24]}"
            if url:
                line += f"\n   {url}"
            lines.append(line)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.image_search",
            kind="text",
            body="\n".join(lines),
            url=hits[0].get("url") or None,
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["image_search", "saucenao", "orchestration:ok"],
        )

    return capability
