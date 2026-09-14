from __future__ import annotations

import atexit
import base64
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RenderedOutput,
    ReviewResult,
    RiskLevel,
)

from .plain_text import naturalize_chat_text

# ==================== Mermaid 流程图（G-MERMAID） ====================
# bot 回复文本里的 ```mermaid 围栏块 → PNG 随消息发出。检测必须在
# naturalize_chat_text 之前：自然化会剥掉围栏行，之后就无法识别块了。
_MERMAID_FENCE_RE = re.compile(
    r"```[ \t]*mermaid\b[^\n]*\n(.*?)\n?[ \t]*```",
    re.IGNORECASE | re.DOTALL,
)
# 护栏：单块源码超长不渲染、单条消息最多渲染张数、整体时间预算。
MERMAID_MAX_SOURCE_CHARS = 8000
MERMAID_MAX_BLOCKS = 3
_MERMAID_PLACEHOLDER = "【流程图见下图】"
_MERMAID_CALL_TIMEOUT_S = 20.0
_MERMAID_TOTAL_BUDGET_S = 22.0

_mermaid_executor: ThreadPoolExecutor | None = None
_mermaid_executor_lock = threading.Lock()
# 审查 L-12：atexit 注册只许一次（模块级布尔防 shutdown 后重建池导致的重复
# 注册堆积；钩子读全局，一次注册覆盖此后所有池实例）。
_mermaid_shutdown_hook_registered = False


def _shutdown_mermaid_executor() -> None:
    """模块级关闭钩子（审查 L-12，与 pipeline._shutdown_chat_pool /
    error_report._shutdown_render_pool 同模式）：wait=True 且不取消排队任务
    （cancel_futures=False）——已提交的 mermaid 渲染在进程退出前跑完再收
    线程（worker 非守护态本就会被解释器隐式 join，显式回收把时序摆上台面；
    渲染自带超时预算，不会无限挂住）。"""
    global _mermaid_executor
    with _mermaid_executor_lock:
        pool, _mermaid_executor = _mermaid_executor, None
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=False)


def _get_mermaid_executor() -> ThreadPoolExecutor:
    """mermaid 渲染专用单线程池：playwright sync API 与事件循环互斥，
    且其浏览器实例线程绑定，固定 worker 才能跨渲染复用常驻浏览器。"""
    global _mermaid_executor, _mermaid_shutdown_hook_registered
    with _mermaid_executor_lock:
        if _mermaid_executor is None:
            _mermaid_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="mermaid-render",
            )
            if not _mermaid_shutdown_hook_registered:
                atexit.register(_shutdown_mermaid_executor)
                _mermaid_shutdown_hook_registered = True
        return _mermaid_executor


def _render_mermaid_png(code: str) -> bytes | None:
    """渲染一块 mermaid 源码为 PNG 字节；失败/超时返回 None，绝不抛异常。

    实际渲染在专用线程执行（render_reviewed_output 可能被 handle_async
    直接调在事件循环线程上，playwright sync API 在那里会拒绝启动）。
    """
    try:
        from .card_render.bridge import render_mermaid_png
    except Exception:  # noqa: BLE001 - 桥接不可用按渲染失败降级。
        return None
    try:
        future = _get_mermaid_executor().submit(render_mermaid_png, code)
        return future.result(timeout=_MERMAID_CALL_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - 超时/线程异常一律按渲染失败降级。
        return None


def find_mermaid_blocks(text: str) -> list[re.Match[str]]:
    """找出文本里所有 ```mermaid 围栏块（含开闭围栏整段）。"""
    if not text:
        return []
    try:
        return list(_MERMAID_FENCE_RE.finditer(text))
    except Exception:  # noqa: BLE001 - 正则异常时按无块处理。
        return []


def _naturalize_keeping_edges(segment: str) -> str:
    """自然化分段但保留两端换行，保证占位/围栏始终独立成行。"""
    if not segment.strip():
        return segment
    stripped = segment.strip("\n")
    if not stripped:
        return segment
    lead = segment[: len(segment) - len(segment.lstrip("\n"))]
    trail = segment[len(segment.rstrip("\n")) :]
    return lead + naturalize_chat_text(stripped) + trail


def apply_mermaid_blocks(
    text: str,
    *,
    is_chat: bool,
) -> tuple[str, list[dict]]:
    """把 ```mermaid 围栏块替换为一行占位并产出 PNG 图片部件（G-MERMAID）。

    返回 (新文本, 阅读顺序交错的 text/image 部件)。护栏：单块源码
    >8000 字符不渲染；单条消息最多渲染前 3 块；渲染总耗时超预算后
    其余块保留文本。渲染失败/无网的块原样保留代码文本——绝不丢内容、
    绝不抛异常；一张都没渲染成功时返回原文本与空列表（调用方继续走
    既有纯文本管线，行为与未挂钩完全一致）。
    """
    try:
        return _apply_mermaid_blocks_inner(text, is_chat=is_chat)
    except Exception:  # noqa: BLE001 - mermaid 挂钩绝不阻断出站管线。
        return text, []


def _apply_mermaid_blocks_inner(
    text: str,
    *,
    is_chat: bool,
) -> tuple[str, list[dict]]:
    matches = find_mermaid_blocks(text)
    if not matches:
        return text, []
    # 先渲染再动文本：全部失败时对文本零改动，保持既有管线逐字节一致。
    deadline = time.monotonic() + _MERMAID_TOTAL_BUDGET_S
    rendered: list[bytes | None] = []
    success_count = 0
    for match in matches:
        source = match.group(1).replace("\r\n", "\n").strip("\n")
        if (
            success_count >= MERMAID_MAX_BLOCKS
            or len(source) > MERMAID_MAX_SOURCE_CHARS
            or time.monotonic() >= deadline
        ):
            rendered.append(None)
            continue
        png = _render_mermaid_png(source)
        rendered.append(png)
        if png:
            success_count += 1
    if not any(rendered):
        return text, []
    ordered: list[dict] = []
    new_text_chunks: list[str] = []
    cursor = 0
    for match, png in zip(matches, rendered):
        before = text[cursor : match.start()]
        if is_chat:
            before = _naturalize_keeping_edges(before)
        chunk = before + (
            _MERMAID_PLACEHOLDER if png else text[match.start() : match.end()]
        )
        new_text_chunks.append(chunk)
        if chunk:
            ordered.append({"type": "text", "text": chunk})
        if png:
            ordered.append(
                {
                    "type": "image",
                    "file": "base64://" + base64.b64encode(png).decode("ascii"),
                }
            )
        cursor = match.end()
    tail = text[cursor:]
    if is_chat:
        tail = _naturalize_keeping_edges(tail)
    if tail:
        new_text_chunks.append(tail)
        ordered.append({"type": "text", "text": tail})
    return "".join(new_text_chunks), ordered


def render_reviewed_output(
    result: CapabilityResult,
    review: ReviewResult,
) -> RenderedOutput:
    text = review.safe_text or result.body or result.summary or result.title
    is_chat = result.capability_id == "bot.chat"
    # G-MERMAID：检测/渲染先于自然化（naturalize 会剥掉围栏行导致无法
    # 识别块）；没有任何块渲染成功时返回原文本，行为与未挂钩完全一致。
    mermaid_text, mermaid_parts = apply_mermaid_blocks(text, is_chat=is_chat)
    if mermaid_parts:
        text = mermaid_text
    elif is_chat:
        text = naturalize_chat_text(text)
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
    for file_item in result.files or []:
        if isinstance(file_item, dict) and (file_item.get("file") or file_item.get("url")):
            media_parts.append({"type": "file", **file_item})
    if not media_parts and not mermaid_parts and result.text_parts and len(result.text_parts) > 1:
        chunks = [str(part).strip() for part in result.text_parts if str(part).strip()]
        if is_chat:
            chunks = [clean for part in chunks if (clean := naturalize_chat_text(part))]
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
    if mermaid_parts:
        # 流程图已渲染：mermaid_parts 是阅读顺序交错的 text/image 部件
        # （占位行与配图相邻）；能力层自带媒体仍排在最前（与既有 mixed
        # 形态一致，聊天回复通常没有 media_parts）。text_fallback 保留
        # 占位后的全文，transport 不支持图片时按文本降级不丢内容。
        parts = [*media_parts, *mermaid_parts]
        return RenderedOutput(
            request_id=result.request_id,
            content_type="mixed",
            content_ref={"parts": parts},
            text_fallback=text,
            size_estimate=len(text),
            risk_level=review.risk_level,
            privacy_level=review.privacy_level,
        )
    if media_parts:
        parts = [*media_parts]
        if text.strip():
            parts.append({"type": "text", "text": text})
        return RenderedOutput(
            request_id=result.request_id,
            content_type="mixed",
            content_ref={"parts": parts},
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
    max_nodes: int = 0,
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
    # 0/负数表示不人为限制转发节点数；只有 node_chars 作为传输硬长度边界。
    if max_nodes > 0:
        while len(chunks) > max_nodes:
            overflow = chunks.pop()
            merged = f"{chunks[-1]}\n{overflow}" if chunks else overflow
            if chunks:
                chunks[-1] = merged
            else:
                chunks.append(merged)
        # 溢出反复合并会突破 node_chars 硬边界：对尾块按边界二次切分，
        # 代价是块数可能临时超过 max_nodes（硬长度边界优先于节点数上限）。
        tail = chunks[-1]
        if len(tail) > node_chars:
            chunks[-1:] = [
                tail[index : index + node_chars]
                for index in range(0, len(tail), node_chars)
            ]
    return chunks


def build_forward_output(
    request_id: str,
    text: str,
    *,
    node_chars: int = 900,
    max_nodes: int = 0,
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
    """min_chars<=0 表示不按字数拆转发。"""
    if min_chars <= 0:
        return False
    return bool(text) and len(text.strip()) >= max(1, min_chars)


def should_forward_by_node_count(
    text: str,
    *,
    node_chars: int = 900,
    min_nodes: int = 4,
    max_nodes: int = 0,
) -> bool:
    """按**条数**判断是否合并转发：切分后条数达到 min_nodes 即合并。

    用户口径："需要发送的消息 > 3 条（不含 3 条）就合并转发"，即切分后
    **≥4 条**才合并。min_nodes<=0 表示该规则关闭。
    比按字数判断更贴近真实体验：4 条以上刷屏时收进一条合并转发，3 条以内照常直发。
    """
    if min_nodes <= 0 or not text:
        return False
    chunks = split_text_chunks(text, node_chars=node_chars, max_nodes=max_nodes)
    return len(chunks) >= min_nodes
