"""vision 远程图片 bot 侧转 data URL 回归（QQ 签名 URL 服务商侧取不到的修复）。"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from plugins.bot_unified_runtime.capabilities.chat import build_direct_vision_messages
from plugins.bot_unified_runtime.sources import vision_describe as V


def _jpeg_bytes(w: int = 60, h: int = 40) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _gif_bytes(frames: int = 4) -> bytes:
    buffer = io.BytesIO()
    pages = [Image.new("RGB", (60, 40), (i * 60, 30, 90)) for i in range(frames)]
    pages[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=pages[1:],
        duration=100,
        loop=0,
    )
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _clear_cache():
    V._REMOTE_DATA_URL_CACHE.clear()
    V._REMOTE_DATA_URL_CACHE_ORDER.clear()


def test_jpeg_http_url_converted_to_data_url(monkeypatch) -> None:
    monkeypatch.setattr(V, "_download_image_bytes", lambda url, **kw: _jpeg_bytes())
    prepared = V.prepare_vision_image_urls(["http://multimedia.nt.qq.com.cn/a?rkey=x"])
    assert prepared[0].startswith("data:image/jpeg;base64,")


def test_gif_converted_to_filmstrip_jpeg(monkeypatch) -> None:
    monkeypatch.setattr(V, "_download_image_bytes", lambda url, **kw: _gif_bytes())
    prepared = V.prepare_vision_image_urls(["http://gchat.qpic.cn/anim.gif"])
    assert prepared[0].startswith("data:image/jpeg;base64,")
    raw = base64.b64decode(prepared[0].split(",", 1)[1])
    image = Image.open(io.BytesIO(raw))
    assert image.format == "JPEG"
    # 拼条断言：多帧 GIF 必须产出宽于单帧的横向长条（防退化成单帧首帧）。
    assert image.width > 60, image.size


def test_download_failure_keeps_original_url(monkeypatch) -> None:
    monkeypatch.setattr(V, "_download_image_bytes", lambda url, **kw: None)
    original = "http://multimedia.nt.qq.com.cn/expired"
    assert V.prepare_vision_image_urls([original]) == [original]


def test_data_url_passthrough(monkeypatch) -> None:
    keep = "data:image/png;base64,AAA"
    monkeypatch.setattr(
        V,
        "_download_image_bytes",
        lambda url, **kw: (_ for _ in ()).throw(AssertionError("must not download")),
    )
    assert V.prepare_vision_image_urls([keep]) == [keep]


def test_cache_avoids_repeat_download(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_download(url: str, **kwargs: object) -> bytes:
        calls["n"] += 1
        return _jpeg_bytes()

    monkeypatch.setattr(V, "_download_image_bytes", fake_download)
    url = "http://cdn.example/one.jpg"
    V.prepare_vision_image_urls([url])
    V.prepare_vision_image_urls([url])
    assert calls["n"] == 1


def test_direct_vision_funnel_converts_qq_urls(monkeypatch) -> None:
    monkeypatch.setattr(V, "_download_image_bytes", lambda url, **kw: _jpeg_bytes())
    messages = [{"role": "user", "content": "看这张图"}]
    result = build_direct_vision_messages(
        messages,
        query_text="这是什么",
        image_urls=["http://multimedia.nt.qq.com.cn/fresh?rkey=y"],
        max_images=2,
    )
    content = result[0]["content"]
    image_parts = [part for part in content if part.get("type") == "image_url"]
    assert image_parts
    assert image_parts[0]["image_url"]["url"].startswith("data:")
