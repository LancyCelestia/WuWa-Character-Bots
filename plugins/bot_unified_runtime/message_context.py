"""Platform-neutral message segment normalization for chat context."""
from __future__ import annotations

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
                texts.append(f"\n[引用内容]\n{value}\n[/引用内容]")
            normalized.append({"type": "quote", "data": {**data, "text": value}})
        elif kind in {"forward", "chat_history", "messages"}:
            children = data.get("messages") or data.get("content") or data.get("nodes")
            child_segments, child_texts, child_quotes, child_forwards = _flatten(children, depth=depth + 1)
            joined = "\n".join(child_texts).strip()
            if joined:
                forwards.append(joined)
                texts.append(f"\n[转发/聊天记录]\n{joined}\n[/转发/聊天记录]")
            normalized.append({"type": "forward", "data": {"messages": child_segments, **data}})
            normalized.extend(child_segments)
            quotes.extend(child_quotes); forwards.extend(child_forwards)
        elif kind in {"face", "mface", "marketface", "emoji"}:
            label = str(data.get("raw") or data.get("text") or data.get("name") or "表情")
            texts.append(f"[Emoji:{label}]")
            normalized.append({"type": "emoji", "data": data})
        elif kind in {"image", "sticker", "file", "record", "video"}:
            label = {"image": "图片", "sticker": "表情包", "file": "文件", "record": "语音", "video": "视频"}[kind]
            texts.append(f"[{label}]")
            normalized.append({"type": kind, "data": data})
        elif kind:
            normalized.append({"type": kind, "data": data})
    return normalized, texts, quotes, forwards

def normalize_message_segments(raw_segments: list[dict[str, Any]] | None) -> NormalizedMessage:
    segments, texts, quotes, forwards = _flatten(raw_segments or [])
    return NormalizedMessage(" ".join(part for part in texts if part).strip(), segments, "\n".join(quotes), "\n".join(forwards))
