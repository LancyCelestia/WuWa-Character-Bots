from __future__ import annotations

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RenderedOutput,
    ReviewResult,
    RiskLevel,
)


def render_reviewed_output(
    result: CapabilityResult,
    review: ReviewResult,
) -> RenderedOutput:
    text = review.safe_text or result.body or result.summary or result.title
    # 能力层声明的图片/语音直链在审核通过后原样透传（内容来自平台
    # 官方接口，不是用户输入）；transport 不支持时按 text_fallback 降级。
    media_parts: list[dict] = []
    for image in result.images or []:
        if isinstance(image, dict) and (image.get("file") or image.get("url")):
            media_parts.append({"type": "image", **image})
    for audio in result.audio or []:
        if isinstance(audio, dict) and (
            audio.get("file") or (audio.get("music_type") and audio.get("music_id"))
        ):
            part_type = str(audio.get("type") or "record")
            media_parts.append({"type": part_type, **audio})
    for video in result.video or []:
        if isinstance(video, dict) and (video.get("file") or video.get("url")):
            media_parts.append({"type": "video", **video})
    if not media_parts and result.text_parts and len(result.text_parts) > 1:
        chunks = [str(part).strip() for part in result.text_parts if str(part).strip()]
        if chunks:
            return RenderedOutput(
                request_id=result.request_id,
                content_type="chunks",
                content_ref={"chunks": chunks},
                text_fallback="\n\n".join(chunks),
                size_estimate=sum(len(chunk) for chunk in chunks),
                risk_level=review.risk_level,
                privacy_level=review.privacy_level,
            )
    if media_parts:
        return RenderedOutput(
            request_id=result.request_id,
            content_type="mixed",
            content_ref={"parts": [*media_parts, {"type": "text", "text": text}]},
            text_fallback=text,
            size_estimate=len(text),
            risk_level=review.risk_level,
            privacy_level=review.privacy_level,
        )
    return RenderedOutput(
        request_id=result.request_id,
        content_type="text",
        content_ref={"text": text},
        text_fallback=text,
        size_estimate=len(text),
        risk_level=review.risk_level,
        privacy_level=review.privacy_level,
    )


def _safe_break_index(paragraph: str, limit: int) -> int:
    """优先在句末标点/空白处断行，避免把颜文字从中间切开。"""
    if limit <= 0:
        return 0
    break_chars = "。！？…~!?；;，, 　	"
    for index in range(limit - 1, max(0, limit - 40), -1):
        if paragraph[index] in break_chars:
            return index + 1
    return limit


def split_text_chunks(
    text: str,
    *,
    node_chars: int = 900,
    max_nodes: int = 6,
) -> list[str]:
    """按段落把长文本切成合并转发节点，超长段落优先在标点处断开。"""
    normalized = (text or "").strip()
    if not normalized:
        return []
    chunks: list[str] = []
    current = ""
    for paragraph in normalized.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            if current:
                chunks.append(current)
                current = ""
            continue
        while len(paragraph) > node_chars:
            if current:
                chunks.append(current)
                current = ""
            break_at = _safe_break_index(paragraph, node_chars)
            chunks.append(paragraph[:break_at])
            paragraph = paragraph[break_at:]
        if current and len(current) + len(paragraph) + 1 > node_chars:
            chunks.append(current)
            current = paragraph
            continue
        current = paragraph if not current else f"{current}\n{paragraph}"
    if current:
        chunks.append(current)
    while len(chunks) > max_nodes:
        overflow = chunks.pop()
        chunks[-1] = f"{chunks[-1]}\n{overflow}"
    return chunks


def build_forward_output(
    request_id: str,
    text: str,
    *,
    node_chars: int = 900,
    max_nodes: int = 6,
    sender_name: str = "",
    risk_level: RiskLevel = RiskLevel.LOW,
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC,
) -> RenderedOutput:
    """把超长文本渲染成合并转发消息（OneBot node 格式），带文本兜底。

    如果 transport 不支持 forward，会按 ``text_fallback`` 降级。
    """
    chunks = split_text_chunks(text, node_chars=node_chars, max_nodes=max_nodes)
    nodes = [
        {
            "type": "node",
            "data": {
                "name": sender_name or "消息",
                "uin": "0",
                "content": [{"type": "text", "data": {"text": chunk}}],
            },
        }
        for chunk in chunks
    ]
    return RenderedOutput(
        request_id=request_id,
        content_type="forward",
        content_ref={"messages": nodes},
        text_fallback=text,
        size_estimate=len(text),
        risk_level=risk_level,
        privacy_level=privacy_level,
    )


def should_forward_long_text(
    text: str,
    *,
    min_chars: int = 1500,
) -> bool:
    """min_chars<=0 表示不拆转发，长文本直接单条发送。"""
    if min_chars <= 0:
        return False
    return bool(text) and len(text.strip()) >= max(1, min_chars)
