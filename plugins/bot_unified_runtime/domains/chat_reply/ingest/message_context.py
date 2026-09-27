"""Platform-neutral message segment normalization for chat context."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NormalizedMessage:
    plain_text: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    quoted_text: str = ""
    forwarded_text: str = ""

def _data(segment: dict[str, Any]) -> dict[str, Any]:
    value = segment.get("data")
    return value if isinstance(value, dict) else {}

def _flatten(items: Any, *, depth: int = 0) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    if depth > 5 or not isinstance(items, list):
        return [], [], [], []
    normalized: list[dict[str, Any]] = []
    texts: list[str] = []
    quotes: list[str] = []
    forwards: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type", "")).strip().lower()
        data = _data(raw)
        if kind == "text":
            value = str(data.get("text", ""))
            if value:
                texts.append(value)
            normalized.append({"type": "text", "data": {"text": value}})
        elif kind == "quote":
            value = str(data.get("text") or data.get("content") or "").strip()
            if value:
                quotes.append(value)
                texts.append(f"\n[引用内容]\n{_neutralize_markers(value)}\n[/引用内容]")
            normalized.append({"type": "quote", "data": {**data, "text": value}})
        elif kind in {"forward", "chat_history", "messages"}:
            children = data.get("messages") or data.get("content") or data.get("nodes")
            child_segments, child_texts, child_quotes, child_forwards = _flatten(children, depth=depth + 1)
            joined = "\n".join(child_texts).strip()
            if joined:
                forwards.append(joined)
                texts.append(f"\n[转发/聊天记录]\n{_neutralize_markers(joined)}\n[/转发/聊天记录]")
            normalized.append({"type": "forward", "data": {"messages": child_segments, **data}})
            normalized.extend(child_segments)
            quotes.extend(child_quotes); forwards.extend(child_forwards)
        elif kind in {"face", "mface", "marketface", "emoji"}:
            label = str(data.get("raw") or data.get("text") or data.get("name") or "表情")
            texts.append(f"[Emoji:{label}]")
            normalized.append({"type": "emoji", "data": data})
        elif kind in {
            "image",
            "photo",
            "sticker",
            "animation",
            "video_note",
            "file",
            "record",
            "voice",
            "audio",
            "video",
        }:
            # 跨适配器归一：OneBot 的 image/record/video vs Telegram 的
            # photo/sticker/animation/video_note/voice/audio 都要有可读标签，
            # 否则纯媒体消息在提示词里连"有张图/有段语音"都体现不出来。
            label = {
                "image": "图片",
                "photo": "图片",
                "sticker": "表情包",
                "animation": "动图",
                "video_note": "圆形视频",
                "file": "文件",
                "record": "语音",
                "voice": "语音",
                "audio": "音频",
                "video": "视频",
            }[kind]
            texts.append(f"[{label}]")
            normalized.append({"type": kind, "data": data})
        elif kind:
            normalized.append({"type": kind, "data": data})
    return normalized, texts, quotes, forwards

def normalize_message_segments(raw_segments: list[dict[str, Any]] | None) -> NormalizedMessage:
    segments, texts, quotes, forwards = _flatten(raw_segments or [])
    return NormalizedMessage(" ".join(part for part in texts if part).strip(), segments, "\n".join(quotes), "\n".join(forwards))


# --------------------------------------------------------------------------
# 引用链（评审：需求「综合解析回复消息 / 递归解析嵌套引用」）
#
# 背景：QQ 侧引用此前**完全读不到**——旧代码对 `event.reply` 取
# `get_plaintext()`/`.text`，而 OneBot V11 的 `Reply` 模型只有
# time/message_type/message_id/real_id/sender/message，两个属性都不存在，
# 于是 `reply_to_text` 恒为空、`[引用回复]` 块永不拼接（实测复现）。
# Telegram 侧只读第一层，而适配器其实递归解析了 `reply_to_message`。
#
# 这里把引用链做成一等结构：逐层采集 → 逐层预算 → 统一消毒 → 单点渲染。
# --------------------------------------------------------------------------

# 层数上限：QQ/Telegram 客户端实际展示深度约 2-3 层。用户指示放宽到 5 层，
# 以便较长的引用链也能被完整读取。
REPLY_CHAIN_MAX_DEPTH = 5
# 单层字符预算：**放宽后的上限**，不是目标值。正常引用（一两句话）只会用到
# 几十字；该值只用于拦住"被引用一条公告/小说"这类极端长文，避免撑大 prompt。
REPLY_CHAIN_PER_LEVEL_CHARS = 500
# 整链字符预算：同样是上限。实际注入量取决于引用链的真实内容，
# 由 format_reply_chain 的"有多少写多少"语义决定，不会为了凑预算而填充。
REPLY_CHAIN_TOTAL_CHARS = 2000
# 链条在"真实需要时"才展开：层数上限虽为 5，但只有确实存在更深引用时才会去取，
# 避免为了凑层数而做多余的反查请求或注入空层。
_ELLIPSIS = "…"
# 内部标记统一正则（审查 F-13 同族收口：全项目唯一一份）。
# security/injection.py 与 capabilities/chat.py 的同用途正则一律从本模块导入，
# 禁止再复制第二份——三处各自维护曾导致 chat 侧漏收引用族标记。
# 覆盖运行时真实产出/易被伪造的全部包裹标记：
#   [引用回复 层级N(+发送者名)] / [引用内容] / [转发/聊天记录]
#   [UNTRUSTED_USER_TEXT] / [TRUSTED_SYSTEM]
# 及同族变体（引用消息/转发消息/转发的消息）。标记名到闭括号之间的任意尾巴
# （如 `` 层级1 澜汐``）一并命中：format_reply_chain 产出的开标记就带发送者名，
# 旧正则 ``(?: 层级\d+)?\]`` 漏掉该形态，被引用正文可伪造真实开标记提前闭合。
# 刻意不收录裸「引用」「转发」（无后缀复合词）：正常文本含「引用」二字不误剥。
INTERNAL_MARKER_PATTERN = re.compile(
    r"\[(/?)(引用回复|引用内容|引用消息|转发消息|转发的消息|转发/聊天记录"
    r"|UNTRUSTED_USER_TEXT|TRUSTED_SYSTEM)[^\]]*\]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReplyChainItem:
    """引用链的一层（自近及远：layer=1 是直接回复的那条）。"""

    layer: int
    message_id: str = ""
    sender_id: str = ""
    sender_name: str = ""
    text: str = ""
    media_labels: tuple[str, ...] = ()


def _neutralize_markers(value: str) -> str:
    """把内部标记全角化，令被引用正文无法伪造块闭合（同 injection 层策略）。

    必须同时覆盖**带层级后缀**的形态：渲染出来的是
    ``[引用回复 层级1] … [/引用回复 层级1]``，被引用正文里只要出现
    ``[/引用回复 层级1]`` 就能提前闭合。只替换无后缀的裸标记会漏（实测）。

    只命中内部关键字，不碰用户正常书写的方括号（早期版本整段全角化 `[`/`]`，
    会篡改被引用正文里的代码、数组、`[图片]` 之类正常文本）。
    """
    return INTERNAL_MARKER_PATTERN.sub(
        lambda match: match.group(0).replace("[", "［").replace("]", "］"),
        value,
    )


def _clip(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + _ELLIPSIS


def _as_segment_dict(item: Any) -> dict[str, Any] | None:
    """把适配器的 MessageSegment / dict 统一成 ``{"type":…, "data":…}``。

    OneBot 的 ``Reply.message`` 是 ``Message``（元素为 pydantic ``MessageSegment``
    对象，不是 dict）——直接丢给按 dict 写的 `_flatten` 会**静默产出空文本**，
    这正是第一版补丁的 bug（实测 `_segments_to_text(rep.message) == ('', ())`）。
    """
    if isinstance(item, dict):
        return item
    seg_type = getattr(item, "type", None)
    if seg_type is None:
        return None
    data = getattr(item, "data", None)
    return {"type": str(seg_type), "data": data if isinstance(data, dict) else {}}


def _segments_to_text(segments: Any) -> tuple[str, tuple[str, ...]]:
    """段列表 → (文本, 媒体标签)。

    OneBot 侧的 `Reply.message` 是完整段列表（实测含 image/record/video 段），
    媒体此前被 `extract_plain_text()` 整段丢弃；这里显式产出 `[图片]` 之类标签，
    让模型至少知道"被引用的那条里有张图/有段语音"。
    """
    items = [_as_segment_dict(item) for item in (segments or [])]
    _normalized, texts, _quotes, _forwards = _flatten(
        [item for item in items if item is not None]
    )
    media = tuple(
        part
        for part in texts
        if part.startswith("[") and part.endswith("]") and len(part) <= 8
    )
    joined = " ".join(part for part in texts if part and not part.startswith("[")).strip()
    if not joined:
        joined = " ".join(part for part in texts if part).strip()
    return joined, media


def _plain_of(node: Any) -> str:
    """尽最大努力取一个节点的纯文本（适配器差异全部收敛在这里）。

    先试适配器自己的 ``get_plaintext()``；失败或为空时再退回 ``message`` 段列表
    （OneBot 的 ``Reply`` 就是这种形态），最后才看 ``text`` 属性。
    注意顺序：Telegram 事件即使没解析出内容也带一个**空的** ``message`` 字段，
    若先看 message 会得到空串并掩盖真正的 text，故必须先试 get_plaintext。
    """
    if node is None:
        return ""
    getter = getattr(node, "get_plaintext", None)
    if callable(getter):
        try:
            value = str(getter() or "").strip()
        except Exception:  # noqa: BLE001 - 适配器实现差异，读不到按空处理。
            value = ""
        if value:
            return value
    message = getattr(node, "message", None)
    if message is not None:
        extract = getattr(message, "extract_plain_text", None)
        if callable(extract):
            try:
                value = str(extract() or "").strip()
            except Exception:  # noqa: BLE001 - 同上。
                value = ""
            if value:
                return value
    text = getattr(node, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    # Telegram 的 caption 承载媒体消息的说明文字。
    caption = getattr(node, "caption", None)
    return caption.strip() if isinstance(caption, str) else ""


def _sender_of(node: Any) -> tuple[str, str]:
    sender = getattr(node, "sender", None)
    if sender is None:
        return "", ""
    user_id = str(getattr(sender, "user_id", "") or "")
    name = str(
        getattr(sender, "card", "")
        or getattr(sender, "nickname", "")
        or getattr(sender, "first_name", "")
        or ""
    )
    return user_id, name


def _replied_id_in_segments(segments: Any) -> str:
    """从段列表里取 ``reply`` 段指向的 message_id（QQ 的第二层线索）。

    QQ 的引用链是"逐段内嵌"的：本条消息的 reply 段给出被引用的 id，被引用消息
    自己的段列表里又可能带一个 reply 段指向更早的一条——这是继续下钻的唯一线索。
    """
    for item in segments or ():
        seg = _as_segment_dict(item)
        if seg is None:
            continue
        if str(seg.get("type", "")).lower() != "reply":
            continue
        data = seg.get("data") or {}
        value = data.get("id") or data.get("message_id")
        if value:
            return str(value)
    return ""


async def collect_reply_chain_async(
    event: Any,
    *,
    lookup: Any = None,
    max_depth: int = REPLY_CHAIN_MAX_DEPTH,
    per_level_chars: int = REPLY_CHAIN_PER_LEVEL_CHARS,
) -> list[ReplyChainItem]:
    """``collect_reply_chain`` 的异步版：能用 ``lookup`` 按 id 反查更深层引用。

    QQ 的 ``reply`` 段只带 id，"引用的引用"不随事件下发；``lookup(message_id)``
    由调用方注入（通常接 OneBot ``get_msg``），返回形如
    ``{"message_id":…, "message":[段…], "sender":{…}}`` 的映射。
    **只在确实存在更深 reply 段时才反查**——没有更深引用就不产生额外网络调用。
    反查失败/超时一律按链条结束处理，绝不阻断消息处理。
    """
    chain = collect_reply_chain(
        event, max_depth=max_depth, per_level_chars=per_level_chars
    )
    if not chain:
        return chain
    # 同步版在没有反查能力时会补一层 "[引用层级未展开]" 占位；这里既然能反查，
    # 就把该占位摘掉后用真实内容替换（否则会重复一层）。
    # 2026-09-18：去掉多余的 `chain[-1] and`——chain 非空已在上方保证，而
    # ReplyChainItem 是 dataclass 实例恒为真值，该判断永不起作用。
    if chain[-1].text == "[引用层级未展开]":
        chain.pop()
    if not callable(lookup):
        return chain
    seen = {item.message_id for item in chain if item.message_id}
    node: Any = getattr(event, "reply", None) or getattr(event, "reply_to_message", None)
    # 沿链条往下走：第一层来自事件，更深层靠反查。
    while node is not None and len(chain) < max_depth:
        segments = node.get("message") if isinstance(node, dict) else getattr(node, "message", None)
        nested_id = _replied_id_in_segments(segments)
        if not nested_id or nested_id in seen:
            break
        seen.add(nested_id)
        fetched = await _maybe_await(lookup(nested_id))
        if not isinstance(fetched, dict):
            break
        text, media = _segments_to_text(fetched.get("message"))
        sender_raw = fetched.get("sender")
        sender = sender_raw if isinstance(sender_raw, dict) else {}
        chain.append(
            ReplyChainItem(
                layer=len(chain) + 1,
                message_id=str(fetched.get("message_id") or nested_id),
                sender_id=str(sender.get("user_id") or ""),
                sender_name=str(sender.get("nickname") or sender.get("card") or ""),
                text=_clip(_neutralize_markers(text), per_level_chars),
                media_labels=media,
            )
        )
        node = fetched
    return chain


async def _maybe_await(value: Any) -> Any:
    """lookup 允许同步或异步实现。"""
    if hasattr(value, "__await__"):
        return await value
    return value


def collect_reply_chain(
    event: Any,
    *,
    max_depth: int = REPLY_CHAIN_MAX_DEPTH,
    per_level_chars: int = REPLY_CHAIN_PER_LEVEL_CHARS,
    nested_lookup: Any = None,
) -> list[ReplyChainItem]:
    """采集引用链（自近及远），跨 OneBot V11 与 Telegram。

    实现要点：
    - OneBot V11：``event.reply`` 是 ``Reply`` 模型，正文在 ``reply.message``
      （段列表），**必须读段列表而不是 get_plaintext()**——后者在 Reply 上根本
      不存在（这也是修复前引用恒为空的根因）。更深一层优先取非标的
      ``reply.reply``（``Reply`` 的 model_config 是 extra=allow，网关给出即保留）；
      否则读该层 ``message`` 里的 ``reply`` 段 id，并用 ``nested_lookup``
      （注入式，通常接 SnowLuma ``get_msg``）继续下钻。
    - Telegram：``event.reply_to_message`` 本身就是递归的 ``MessageEvent``，沿
      ``reply_to_message`` 逐层下行。
    - 每层记 message_id 并去重，防 A↔B 互引形成死循环。
    """
    if event is None or max_depth <= 0:
        return []
    chain: list[ReplyChainItem] = []
    seen: set[str] = set()
    node: Any = getattr(event, "reply", None) or getattr(event, "reply_to_message", None)
    layer = 1
    while node is not None and layer <= max_depth:
        # OneBot 的非标 `Reply.reply`（extra=allow）是**原始 dict**，而
        # `event.reply` / Telegram 的 `reply_to_message` 是模型对象；
        # 两种形态统一在这里取值。
        if isinstance(node, dict):
            message_id = str(node.get("message_id") or node.get("real_id") or "")
            sender_raw = node.get("sender")
            if isinstance(sender_raw, dict):
                sender_id = str(sender_raw.get("user_id") or "")
                sender_name = str(
                    sender_raw.get("card") or sender_raw.get("nickname") or ""
                )
            else:
                sender_id, sender_name = "", ""
            segments = node.get("message")
        else:
            message_id = str(
                getattr(node, "message_id", "") or getattr(node, "real_id", "") or ""
            )
            sender_id, sender_name = _sender_of(node)
            segments = getattr(node, "message", None)
        if message_id and message_id in seen:
            break
        if message_id:
            seen.add(message_id)
        text, media = _segments_to_text(segments) if segments is not None else ("", ())
        if not text:
            text = _plain_of(node)
        chain.append(
            ReplyChainItem(
                layer=layer,
                message_id=message_id,
                sender_id=sender_id,
                sender_name=sender_name,
                text=_clip(_neutralize_markers(text), per_level_chars),
                media_labels=media,
            )
        )
        # 下一层：OneBot 走非标 reply.reply；Telegram 走递归的 reply_to_message。
        if isinstance(node, dict):
            next_node = node.get("reply") or node.get("reply_to_message")
        else:
            next_node = getattr(node, "reply", None) or getattr(
                node, "reply_to_message", None
            )
        if next_node is None:
            # QQ 常态：本层 message 里带 reply 段（只有 id），需要反查才能下钻。
            nested_id = _replied_id_in_segments(segments)
            if nested_id and nested_id not in seen and callable(nested_lookup):
                try:
                    next_node = nested_lookup(nested_id)
                except Exception:  # noqa: BLE001 - 反查失败按链条结束处理。
                    next_node = None
            if next_node is None and nested_id and nested_id not in seen:
                # 无反查能力时至少记录一层占位，明确告知模型"还有更深一层"。
                chain.append(
                    ReplyChainItem(
                        layer=layer + 1,
                        message_id=nested_id,
                        text="[引用层级未展开]",
                    )
                )
                break
        node = next_node
        layer += 1
    return chain


def format_reply_chain(
    chain: list[ReplyChainItem] | None,
    *,
    total_chars: int = REPLY_CHAIN_TOTAL_CHARS,
) -> str:
    """把引用链渲染成逐层闭合的提示词块（已消毒、已预算）。

    单层：``[引用回复 层级1] …[/引用回复 层级1]``；多层逐层输出，便于模型区分
    "当前这话"与"被引用的旧话"，并在信息不足时显式给出层级达上限的提示。
    """
    items = list(chain or [])
    if not items:
        return ""
    blocks: list[str] = []
    for item in items:
        body = item.text.strip()
        extra = (" " + " ".join(item.media_labels)) if item.media_labels else ""
        who = f" {item.sender_name}" if item.sender_name else ""
        if not body and not extra:
            continue
        blocks.append(
            f"[引用回复 层级{item.layer}{who}] {body}{extra} [/引用回复 层级{item.layer}]"
        )
    if not blocks:
        return ""
    joined = "\n".join(blocks)
    if len(joined) > total_chars:
        joined = joined[: max(0, total_chars - 1)].rstrip() + _ELLIPSIS
    elif len(items) >= REPLY_CHAIN_MAX_DEPTH:
        joined = f"{joined}\n[引用层级已达上限]"
    return joined

