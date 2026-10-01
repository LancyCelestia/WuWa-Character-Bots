"""Task C（mface 探测波，2026-09-29）：贴纸出站的 mface 主路与 image 兜底腿。

与 ``test_onebot_sticker_segment.py``（构段尺本体）的分工：本件锁**三段接线**——

1. **支持 mface 的协议端**（Task A 实据：SnowLuma v1.14.19-node bundle 发送方向
   册 ``mface: {W: "yes"}``）：载荷带原生 ``emoji_id``（32 位 hex）即出
   ``{"type": "mface", ...}`` 段——「mock」在这里就是一枚真实形态的收侧 id，
   不依赖网络也不碰真机；
2. **不支持/没 id 的协议端**：回落 ``{"type": "image", ...}``，且必须留下
   ``sticker_via_image_segment_fallback=true`` 观测行（用户报「发成了图片」时
   第一现场就在日志里）；
3. **kind 标签全链传导**：消费方（sticker_packs 席）在 ``CapabilityResult.images``
   条目上打 ``kind="sticker"`` ⇒ renderer 打成 ``sticker`` 部件 ⇒ onebot 出站腿
   构 ``mface``/``image`` 段；没打 kind 的条目（/随机图 等照片面）逐字节走旧
   ``image`` 路，**不得**被贴纸接线波及。

全离线：tmp_path 真文件 + 纯函数调用，零网络、零真实协议端、零源码树写入。
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from plugins.bot_unified_runtime.contracts import CapabilityResult, SessionType
from plugins.bot_unified_runtime.domains.render.renderer import render_reviewed_output
from plugins.bot_unified_runtime.domains.render.reviewer import review_capability_result
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    _segment_from_mixed_part,
    _segments_from_rendered_output,
    _sticker_segment,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# SnowLuma 收侧把 mface 元素投影成 image 段时挂在 data.emoji_id 上的真实形态。
NATIVE_EMOJI_ID = "36e30075a7c87195418619ccf67c60dc"
FALLBACK_LOG_TOKEN = "sticker_via_image_segment_fallback=true"


def _real_png(tmp_path: Path, name: str = "sticker.png") -> Path:
    path = tmp_path / name
    path.write_bytes(PNG_MAGIC + b"\x00" * 48)
    return path


def _decision(request_id: str = "req-mface-1") -> SimpleNamespace:
    """``review_capability_result`` 只认 should_respond/target_scope/capability_id 三件。"""
    return SimpleNamespace(
        request_id=request_id,
        should_respond=True,
        capability_id="bot.sticker_packs",
        target_scope=SessionType.PRIVATE,
    )


def _chain(result: CapabilityResult) -> list[dict[str, Any]]:
    """能力结果 → 审核 → 渲染 → OneBot 段（与生产同一个入口链，全离线）。"""
    review = review_capability_result(result, _decision(result.request_id))
    assert review.approved is True
    rendered = render_reviewed_output(result, review)
    return _segments_from_rendered_output(
        content_type=rendered.content_type,
        content_ref=rendered.content_ref,
        text_fallback=rendered.text_fallback,
        request_id=result.request_id,
    )


def _capability_result(images: list[dict[str, Any]], request_id: str) -> CapabilityResult:
    return CapabilityResult(
        request_id=request_id,
        capability_id="bot.sticker_packs",
        kind="mixed",
        body="",
        images=images,
    )


# ============================================================================
# ① 支持 mface：原生 id ⇒ mface 段（不上传本地文件也成立）
# ============================================================================


def test_supported_native_id_yields_mface_segment_end_to_end() -> None:
    result = _capability_result(
        [{"kind": "sticker", "emoji_id": NATIVE_EMOJI_ID, "summary": "蹭蹭"}],
        "req-mface-1",
    )
    segments = _chain(result)
    assert segments == [
        {"type": "mface", "data": {"emoji_id": NATIVE_EMOJI_ID, "summary": "蹭蹭"}}
    ], "原生 id 的贴纸必须走 mface 段——发成 image 就是用户点名的旧症状"


def test_mface_segment_carries_package_and_key_when_present() -> None:
    segment = _segment_from_mixed_part(
        {
            "type": "sticker",
            "emoji_id": NATIVE_EMOJI_ID,
            "emoji_package_id": "187",
            "key": "k-1",
        }
    )
    assert segment is not None
    assert segment["data"]["emoji_package_id"] == "187"
    assert segment["data"]["key"] == "k-1"


# ============================================================================
# ② 不支持 / 没 id：image 兜底 + 观测行
# ============================================================================


def test_unsupported_falls_back_to_image_and_logs_token(tmp_path: Path, caplog) -> None:
    """载荷无可信 emoji_id（协议端没给/形态不合）⇒ image 段 + 点名观测行。"""
    real = _real_png(tmp_path)
    with caplog.at_level(logging.WARNING, logger="plugins.bot_unified_runtime.domains.transport.sender.onebot"):
        segment = _sticker_segment({"type": "sticker", "file": str(real)})
    assert segment is not None and segment["type"] == "image"
    assert segment["data"]["file"] == str(real.resolve())
    assert any(FALLBACK_LOG_TOKEN in row for row in caplog.messages), (
        "兜底不发观测行 ⇒ 用户报「发成图片」时日志里查不到是哪条腿退的"
    )


def test_no_id_and_no_file_drops_segment_without_empty_send() -> None:
    """两样都没有 ⇒ None 丢段（进 mixed 丢段观测），绝不构空段。"""
    assert _sticker_segment({"type": "sticker"}) is None
    assert _sticker_segment({"type": "sticker", "file": "C:/nope/ghost.png"}) is None


def test_dropped_sticker_part_falls_back_to_text_in_mixed_chain() -> None:
    """整条 mixed 只有死贴纸时按既有语义落 text_fallback，不出半张假图。"""
    result = _capability_result(
        [{"kind": "sticker", "file": "C:/nope/ghost.png"}], "req-mface-2"
    )
    result = result.model_copy(update={"body": "就一句话"})
    segments = _chain(result)
    types = [str(segment.get("type")) for segment in segments]
    assert "sticker" not in types and "mface" not in types
    assert types == ["text"]


# ============================================================================
# ③ kind 标签传导：sticker 走贴纸腿、image（含不打 kind）逐字节走旧路
# ============================================================================


def test_kind_image_and_bare_entries_keep_legacy_image_path(tmp_path: Path) -> None:
    """``kind="image"``、``"kind": "photo"`` 与不打 kind 的条目（/随机图 形态）
    全部必须仍出 ``image`` 段——贴纸接线一根手指都不许碰到照片通路。"""
    a = _real_png(tmp_path, "a.png")
    b = _real_png(tmp_path, "b.png")
    c = _real_png(tmp_path, "c.png")
    result = _capability_result(
        [
            {"file": str(a), "kind": "image"},
            {"file": str(b), "kind": "photo"},
            {"file": str(c)},
        ],
        "req-mface-3",
    )
    segments = _chain(result)
    assert [str(segment.get("type")) for segment in segments] == ["image", "image", "image"]


def test_kind_sticker_propagates_through_renderer_into_segment(tmp_path: Path) -> None:
    """同一批 images 里混打 kind：sticker 条目出 mface，photo 条目出 image，互不串门。"""
    photo = _real_png(tmp_path, "photo.png")
    sticker = _real_png(tmp_path, "sticker.png")
    result = _capability_result(
        [
            {"file": str(photo)},
            {"file": str(sticker), "kind": "sticker", "emoji_id": NATIVE_EMOJI_ID},
        ],
        "req-mface-4",
    )
    segments = _chain(result)
    types = [str(segment.get("type")) for segment in segments]
    assert types == ["image", "mface"]
    assert segments[1]["data"]["emoji_id"] == NATIVE_EMOJI_ID
