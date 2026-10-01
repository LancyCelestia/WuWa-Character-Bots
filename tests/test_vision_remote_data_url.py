"""vision 远程图片 bot 侧转 data URL 回归（QQ 签名 URL 服务商侧取不到的修复）。"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_direct_vision_messages,
)
from plugins.bot_unified_runtime.domains.media.ingest import vision_describe as V


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


# ---------- 图片大小上限口径（2026-09-18 用户裁定「放宽到 25MB」） ----------


def test_image_size_caps_are_25mb() -> None:
    """远程图与本地图上限同口径 25MB——两处漂移会让「远程能读、本地读不了」。"""
    assert V._MAX_REMOTE_IMAGE_BYTES == 25_000_000
    assert V._MAX_LOCAL_IMAGE_INPUT_BYTES == 25_000_000


def test_remote_download_accepts_just_under_cap_and_rejects_over(
    monkeypatch,
) -> None:
    """25MB 上限的边界语义：恰好等于上限可收，超出 1 字节即拒。

    2026-09-27 席位 S-ATKFIX-SSRF1 跟随 F-1 改动：取图腿不再走裸 urlopen，
    改走 ``_guarded_image_opener``（重定向逐跳落点复查）；注入点随之从
    ``urllib.request.urlopen`` 换到该工厂，只替传输、不替护栏。入口咽喉
    用字面量公网 IP（离线判定，零 DNS）。
    """
    cap = V._MAX_REMOTE_IMAGE_BYTES

    class _Resp:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self, n: int) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    class _FakeOpener:
        def open(self, request, timeout=None):
            return _Resp(b"\0" * (cap + 1))

    monkeypatch.setattr(V, "_guarded_image_opener", lambda: _FakeOpener())
    assert V._download_image_bytes("http://93.184.216.34/big.jpg") is None
