"""bot.meme 图片入参回归：info 参数 → 图片采集/上传 → 缺图引导。"""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.meme import (
    _collect_image_sources,
    build_meme_capability,
)
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)

_DECISION = BotDecision(
    request_id="r-img",
    should_respond=True,
    mode="command",
    trigger="test",
    capability_id="bot.meme",
    target_scope=SessionType.GROUP,
    decision_reason="unit-test",
)


def _message(
    text: str,
    *,
    segments: list[dict] | None = None,
    platform: str = "onebot",
    sender_id: str = "10001",
) -> IncomingMessage:
    return IncomingMessage(
        platform=platform,
        adapter="onebot.v11" if platform == "onebot" else platform,
        bot_id="bot",
        session_id="group:1",
        session_type=SessionType.GROUP,
        group_id="1",
        sender_id=sender_id,
        plain_text=text,
        raw_segments=segments or [],
    )


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_meme_api_enabled=True,
        bot_meme_api_base_url="http://127.0.0.1:2233",
        bot_meme_api_timeout_seconds=5,
        bot_meme_api_output_dir=str(tmp_path / "memes"),
        bot_meme_cache_max_bytes=0,
    )


def _recording_request_fn(routes: dict):
    calls: list[tuple[str, str, dict | None]] = []

    def request(method: str, path: str, json: dict | None = None):
        key = (method.upper(), path)
        calls.append((method.upper(), path, json))
        return routes[key]

    return request, calls


def _happy_routes() -> dict:
    return {
        ("GET", "/memes/petpet/info"): (
            200,
            {"params": {"min_images": 1, "max_images": 1, "min_texts": 0, "max_texts": 2}},
        ),
        ("POST", "/image/upload"): (200, {"image_id": "abc123"}),
        ("POST", "/memes/petpet"): (200, {"image_id": "gen"}),
        ("GET", "/image/gen"): (200, b"\x89PNG\r\n\x1a\nfake"),
    }


def test_image_meme_via_at_avatar(tmp_path) -> None:
    request, calls = _recording_request_fn(_happy_routes())
    capability = build_meme_capability(
        _config(tmp_path),
        request_fn=request,
        image_fetch_fn=lambda url: b"PNGDATA" if url.startswith("http") else None,
    )
    message = _message(
        "/表情 petpet 可爱",
        segments=[{"type": "at", "data": {"qq": "12345"}}],
    )
    result = capability(message, _DECISION)

    assert result.kind == "mixed", "带图生成应成功"
    uploads = [call for call in calls if call[1] == "/image/upload"]
    assert len(uploads) == 1
    assert base64.b64decode(uploads[0][2]["data"]) == b"PNGDATA", "图片应 bot 侧下载后转 data 上传"
    generate = next(call for call in calls if call[1] == "/memes/petpet")
    assert generate[2]["images"] == [{"name": "img0.png", "id": "abc123"}]
    assert generate[2]["texts"] == ["可爱"]


def test_image_meme_sender_avatar_fallback(tmp_path) -> None:
    request, calls = _recording_request_fn(_happy_routes())
    fetched: list[str] = []

    def fetch(url: str):
        fetched.append(url)
        return b"PNGDATA" if "qlogo" in url else None

    capability = build_meme_capability(_config(tmp_path), request_fn=request, image_fetch_fn=fetch)
    result = capability(_message("/表情 petpet 可爱"), _DECISION)

    assert result.kind == "mixed", "无图无@时应回退发送者头像"
    assert fetched == ["https://q1.qlogo.cn/g?b=qq&nk=10001&s=640"]
    assert any(call[1] == "/image/upload" for call in calls)


def test_missing_image_guidance_when_fetch_fails(tmp_path) -> None:
    routes = _happy_routes()
    del routes[("POST", "/memes/petpet")]
    request, calls = _recording_request_fn(routes)
    capability = build_meme_capability(
        _config(tmp_path),
        request_fn=request,
        image_fetch_fn=lambda url: None,
    )
    message = _message(
        "/表情 petpet 可爱",
        segments=[{"type": "image", "data": {"url": "https://example.com/a.png"}}],
    )
    result = capability(message, _DECISION)

    assert result.kind == "text" and "需要 1 张图片" in result.body
    assert "meme_need_images" in result.audit_tags
    assert not any(call[1] == "/memes/petpet" for call in calls), "缺图不得发生成请求"


def test_text_meme_ignores_attached_image(tmp_path) -> None:
    routes = {
        ("GET", "/memes/5000choyen/info"): (
            200,
            {"params": {"min_images": 0, "max_images": 0, "min_texts": 2, "max_texts": 2}},
        ),
        ("POST", "/memes/5000choyen"): (200, {"image_id": "gen"}),
        ("GET", "/image/gen"): (200, b"\x89PNG\r\n\x1a\nfake"),
    }
    request, calls = _recording_request_fn(routes)
    capability = build_meme_capability(
        _config(tmp_path),
        request_fn=request,
        image_fetch_fn=lambda url: b"PNGDATA",
    )
    message = _message(
        "/表情 5000choyen 你好｜世界",
        segments=[{"type": "image", "data": {"url": "https://example.com/a.png"}}],
    )
    result = capability(message, _DECISION)

    assert result.kind == "mixed"
    assert not any(call[1] == "/image/upload" for call in calls), "纯文字表情不上传图片"
    generate = next(call for call in calls if call[1] == "/memes/5000choyen")
    assert generate[2]["images"] == []


def test_info_unavailable_falls_back_to_plain_render(tmp_path) -> None:
    request, calls = _recording_request_fn(
        {
            ("GET", "/memes/petpet/info"): (404, {"code": 404, "message": "no such meme"}),
            ("POST", "/memes/petpet"): (200, {"image_id": "gen"}),
            ("GET", "/image/gen"): (200, b"\x89PNG\r\n\x1a\nfake"),
        }
    )
    capability = build_meme_capability(_config(tmp_path), request_fn=request)
    result = capability(_message("/表情 petpet 可爱"), _DECISION)

    assert result.kind == "mixed", "info 缺失时按纯文字直发（兼容旧行为）"
    generate = next(call for call in calls if call[1] == "/memes/petpet")
    assert generate[2]["images"] == []


def test_zero_text_image_meme_renders_bare_key(tmp_path) -> None:
    """petpet 类零文字表情：『/表情 petpet』不带文字也应直接渲染。"""
    routes = {
        ("GET", "/memes/petpet/info"): (
            200,
            {"params": {"min_images": 1, "max_images": 1, "min_texts": 0, "max_texts": 0}},
        ),
        ("POST", "/image/upload"): (200, {"image_id": "abc123"}),
        ("POST", "/memes/petpet"): (200, {"image_id": "gen"}),
        ("GET", "/image/gen"): (200, b"\x89PNG\r\n\x1a\nfake"),
    }
    request, calls = _recording_request_fn(routes)
    capability = build_meme_capability(
        _config(tmp_path),
        request_fn=request,
        image_fetch_fn=lambda url: b"PNGDATA" if "qlogo" in url else None,
    )
    result = capability(_message("/表情 petpet"), _DECISION)

    assert result.kind == "mixed", "零文字图片表情应渲染而非回帮助"
    generate = next(call for call in calls if call[1] == "/memes/petpet")
    assert generate[2]["texts"] == []


def test_bare_nonzero_text_key_falls_back_to_help(tmp_path) -> None:
    """需要文字的表情只敲了 key：当打错 key 处理，回帮助。"""
    request, calls = _recording_request_fn(
        {
            ("GET", "/memes/5000choyen/info"): (
                200,
                {"params": {"min_images": 0, "max_images": 0, "min_texts": 2, "max_texts": 2}},
            ),
        }
    )
    capability = build_meme_capability(_config(tmp_path), request_fn=request)
    result = capability(_message("/表情 5000choyen"), _DECISION)

    assert result.kind == "text" and "用法" in result.body
    assert not any(call[1].startswith("/memes/") and call[1].endswith("5000choyen") for call in calls)


def test_collect_image_sources_priority_and_dedup() -> None:
    message = _message(
        "/表情 petpet",
        segments=[
            {"type": "at", "data": {"qq": "10001"}},
            {"type": "image", "data": {"url": "https://example.com/a.png"}},
            {"type": "image", "data": {"url": "https://example.com/a.png"}},
            {"type": "at", "data": {"qq": "all"}},
            {"type": "text", "data": {"text": "xx"}},
        ],
        sender_id="99999",
    )
    sources = _collect_image_sources(message)
    assert sources == [
        "https://q1.qlogo.cn/g?b=qq&nk=10001&s=640",
        "https://example.com/a.png",
    ], "消息图片优先于 @ 头像，去重且忽略 @全体"

    bare = _message("/表情 petpet", sender_id="99999")
    assert _collect_image_sources(bare) == ["https://q1.qlogo.cn/g?b=qq&nk=99999&s=640"]

    non_onebot = _message("/表情 petpet", platform="telegram", sender_id="99999")
    assert _collect_image_sources(non_onebot) == [], "非 OneBot 平台不做头像回退"
