"""TG file_id → 媒体字节解析回归（全部离线：mock get_file + MockTransport）。

锁定 telegram_media 的四条硬承诺：任何失败返回 None 绝不抛、超 20MB 上限
返回 None、token 绝不进日志、enrich 成功把字节落临时文件写回 data.file 而
失败保持段原样（标签降级行为不变）。

fixture 纪律（席位 S-FIX-TGMEDIA，WP1 §7 迁移计划落地）：下载腿已接中央
SSRF 咽喉逐跳复查（check_download_url，解析失败=拒绝）+图像/视频段落盘前
归档 magic-bytes 真身 QC——本文件的下载目标一律用**字面量公网 IP**
（93.184.216.3x，咽喉离线判定放行，零 DNS 零真网络），载荷一律用**合法
magic bytes**（JPEG/PNG 起始签名），旧 .example.org 字面域名夹具按计划在
本波迁走。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from plugins.bot_unified_runtime.domains.media.ingest import telegram_media
from plugins.bot_unified_runtime.domains.media.ingest.telegram_media import (
    DEFAULT_MAX_FILE_BYTES,
    enrich_telegram_file_segments,
    resolve_telegram_file_bytes,
)


class _TelegramEvent:
    """仅在 __module__ 上带 .telegram 标记的假事件（模块据此判适配器）。"""


_TelegramEvent.__module__ = "nonebot.adapters.telegram.event"


class _OtherEvent:
    """非 TG 事件。"""


_OtherEvent.__module__ = "nonebot.adapters.onebot.v11.event"


class _FakeBot:
    """call_api(get_file) 假适配器；file_path 可为相对路径或完整 URL。

    api_server 默认字面量公网 IP（离线咽喉判定放行、零 DNS），不再走
    api.telegram.org 真域解析。
    """

    def __init__(
        self,
        file_path: str = "photos/img.jpg",
        *,
        token: str = "123456:secret",
        api_server: str = "https://93.184.216.34/",
        fail: bool = False,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.file_path = file_path
        self.bot_config = SimpleNamespace(token=token, api_server=api_server)
        self.fail = fail

    async def call_api(self, action: str, **params: Any) -> Any:
        self.calls.append((action, params))
        if self.fail:
            raise RuntimeError("get_file boom")
        return SimpleNamespace(file_path=self.file_path)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    # TTL 缓存与代理环境变量跨用例隔离，防 mock 断言被污染。
    monkeypatch.setattr(telegram_media, "_FILE_PATH_CACHE", {})
    monkeypatch.setattr(telegram_media, "_FILE_PATH_CACHE_ORDER", [])
    monkeypatch.delenv("TELEGRAM_PROXY", raising=False)
    monkeypatch.delenv("BOT_DOWNLOAD_PROXY", raising=False)
    yield


def _install_download(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    seen_urls: list[str],
    *,
    status: int = 200,
) -> None:
    """用 MockTransport 替换下载客户端构造缝，绝不发真实请求。"""

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(status, content=payload)

    real_build = telegram_media._build_download_client

    def fake_build(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_build(**kwargs)

    monkeypatch.setattr(telegram_media, "_build_download_client", fake_build)


def test_resolve_success_downloads_bytes_and_enrich_writes_temp_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen_urls: list[str] = []
    _install_download(monkeypatch, b"\xff\xd8\xff\xe0jpeg-bytes", seen_urls)
    bot = _FakeBot(file_path="photos/img.jpg", api_server="https://93.184.216.34/")

    payload = asyncio.run(resolve_telegram_file_bytes(bot, "fid-1"))
    assert payload == b"\xff\xd8\xff\xe0jpeg-bytes"
    assert bot.calls == [("get_file", {"file_id": "fid-1"})]
    # 相对 file_path → {api_server}/file/bot<token>/<path>；api_server 尾斜杠被规整。
    assert seen_urls == ["https://93.184.216.34/file/bot123456:secret/photos/img.jpg"]

    # enrich：成功后字节落临时文件，data.file 指向本机路径，原 file_id 保留。
    segments = [{"type": "photo", "data": {"file": "fid-1"}}]
    asyncio.run(enrich_telegram_file_segments(bot, _TelegramEvent(), segments))
    data = segments[0]["data"]
    written = Path(data["file"])
    assert data["file_id"] == "fid-1"
    assert written.suffix == ".jpg"
    assert written.read_bytes() == b"\xff\xd8\xff\xe0jpeg-bytes"
    written.unlink()


def test_full_url_file_path_downloads_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_urls: list[str] = []
    _install_download(monkeypatch, b"\x89PNG\r\n\x1a\nurl-bytes", seen_urls)
    # 自定义 api server 的 get_file 可能直接回完整 URL → 原样下载，不拼 token。
    bot = _FakeBot(file_path="https://93.184.216.35/photos/img.png")

    assert asyncio.run(resolve_telegram_file_bytes(bot, "fid-url")) == b"\x89PNG\r\n\x1a\nurl-bytes"
    assert seen_urls == ["https://93.184.216.35/photos/img.png"]


def test_oversized_download_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_urls: list[str] = []
    _install_download(monkeypatch, b"x" * 64, seen_urls)
    bot = _FakeBot()

    # 超 20MB 走同一条限读分支；用小 max_bytes 等价触发（默认值即 20MB 硬上限）。
    assert DEFAULT_MAX_FILE_BYTES == 20 * 1024 * 1024
    assert (
        asyncio.run(resolve_telegram_file_bytes(bot, "fid-big", max_bytes=32)) is None
    )


def test_get_file_exception_returns_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _install_download(monkeypatch, b"never", [])
    bot = _FakeBot(fail=True)
    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(resolve_telegram_file_bytes(bot, "fid-boom")) is None
    # 绝不抛 + token 绝不进日志（异常消息含 URL 也不落）。
    assert "secret" not in caplog.text
    assert "get_file boom" not in caplog.text


def test_enrich_failure_keeps_segment_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_download(monkeypatch, b"never", [])
    bot = _FakeBot(fail=True)
    segments = [{"type": "voice", "data": {"file": "fid-boom"}}]
    asyncio.run(enrich_telegram_file_segments(bot, _TelegramEvent(), segments))
    assert segments[0]["data"] == {"file": "fid-boom"}


def test_enrich_ignores_non_telegram_and_resolvable_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_download(monkeypatch, b"unused", [])
    bot = _FakeBot()

    # 非 TG 事件零成本直通，不发任何 API。
    segments = [{"type": "photo", "data": {"file": "fid-1"}}]
    asyncio.run(enrich_telegram_file_segments(bot, _OtherEvent(), segments))
    assert bot.calls == []

    # 已有可用 URL/path 来源的 TG 段不碰。
    already = [{"type": "photo", "data": {"file": "https://cdn.example/a.jpg"}}]
    asyncio.run(enrich_telegram_file_segments(bot, _TelegramEvent(), already))
    assert bot.calls == []
    assert already[0]["data"]["file"] == "https://cdn.example/a.jpg"


def test_missing_token_skips_download(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_urls: list[str] = []
    _install_download(monkeypatch, b"never", seen_urls)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    bot = _FakeBot(token="")
    assert asyncio.run(resolve_telegram_file_bytes(bot, "fid-1")) is None
    assert seen_urls == []
