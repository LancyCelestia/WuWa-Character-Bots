"""TG document 段的入站补齐（需求 16①，席位 S-FILESAFE 锁，2026-09-28）。

旧口径把 ``document`` 明确排除在 ``TELEGRAM_FILE_ID_SEGMENT_TYPES`` 之外，
于是 QQ 侧吃得着的文件、TG 侧只留下一个标签——本件锁四格：

① document 现在会被取字节；
② 取到的段落点是**根入站归一唯一认得的 file 段形状**（``type="file"`` +
  ``data.file`` + ``data.name``），读取仍走 ``read_supported_file`` 那一颗咽喉，
  本席不在 TG 侧另开第二条读文件通路；
③ 文档段**不过**图像/视频那道 magic-bytes QC（那是拿错尺子：docx 是 zip、
  ``.txt`` 无签名，一律会被误杀）；
④ 名字来自 get_file 回的 ``file_path``（TG 入站段本身不带文件名），
  并过与出站/落盘同一条消毒（Bidi/零宽伪装剥掉）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.media.ingest import telegram_media
from plugins.bot_unified_runtime.domains.media.ingest.telegram_media import (
    TELEGRAM_FILE_ID_SEGMENT_TYPES,
    enrich_telegram_file_segments,
)

_RLO = chr(0x202E)
_ZWSP = chr(0x200B)


class _TelegramEvent:
    """只在 __module__ 上带 .telegram 标记的假事件。"""


_TelegramEvent.__module__ = "nonebot.adapters.telegram.event"


class _FakeBot:
    def __init__(self, file_path: str, *, api_server: str = "https://93.184.216.34/") -> None:
        self.bot_config = SimpleNamespace(token="123456:secret", api_server=api_server)
        self.file_path = file_path
        self.self_id = "123456"
        self.adapter = SimpleNamespace(adapter_config=SimpleNamespace(telegram_bots=[]))

    async def call_api(self, action: str, **params: Any) -> Any:
        assert action == "get_file"
        return SimpleNamespace(file_path=self.file_path)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telegram_media, "_FILE_PATH_CACHE", {})
    monkeypatch.setattr(telegram_media, "_FILE_PATH_CACHE_ORDER", [])
    monkeypatch.delenv("TELEGRAM_PROXY", raising=False)
    monkeypatch.delenv("BOT_DOWNLOAD_PROXY", raising=False)


def _serve(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    """把下载腿换成"直接回字节"，不碰真网络（与既有夹具同法）。"""

    async def _fake_download(url: str, **kwargs: Any) -> bytes:
        return payload

    monkeypatch.setattr(telegram_media, "_download_bytes", _fake_download)


def test_document_is_now_in_the_file_id_types() -> None:
    assert "document" in TELEGRAM_FILE_ID_SEGMENT_TYPES


def test_document_becomes_a_file_segment_with_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, b"%PDF-1.4\nhello\n%%EOF\n")
    segments = [{"type": "document", "data": {"file": "DOCID1"}}]

    asyncio.run(
        enrich_telegram_file_segments(
            _FakeBot("files/季度报告 2026.pdf"), _TelegramEvent(), segments
        )
    )

    segment = segments[0]
    assert segment["type"] == "file", "没改成根入站认得的形状＝TG 文件仍是全盲"
    data = segment["data"]
    assert data["name"] == "季度报告 2026.pdf"
    assert data["file_id"] == "DOCID1"
    assert Path(data["file"]).is_file(), "落点必须是真实暂存件"


def test_document_skips_the_image_magic_bytes_qc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """纯文本附件没有 magic bytes：图像那道 QC 若照_apply，合法文件会被误杀。"""
    _serve(monkeypatch, "一段普通文本附件".encode())
    assert telegram_media.sniff_extension("一段普通文本附件".encode()) is None
    segments = [{"type": "document", "data": {"file": "DOCID2"}}]

    asyncio.run(
        enrich_telegram_file_segments(_FakeBot("files/note.txt"), _TelegramEvent(), segments)
    )

    assert segments[0]["type"] == "file"


def test_document_name_visual_spoof_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, b"x")
    segments = [{"type": "document", "data": {"file": "DOCID3"}}]

    asyncio.run(
        enrich_telegram_file_segments(
            _FakeBot(f"files/报告{_RLO}{_ZWSP}txt.exe"), _TelegramEvent(), segments
        )
    )

    name = segments[0]["data"]["name"]
    assert _RLO not in name and _ZWSP not in name
    assert name == "报告txt.exe"


def test_image_segments_keep_their_old_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """反向锁：照片段不许被顺手改成 file 段（vision 链路吃的是 photo 段形状）。"""
    _serve(monkeypatch, b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    segments = [{"type": "photo", "data": {"file": "PHOTO1"}}]

    asyncio.run(
        enrich_telegram_file_segments(_FakeBot("photos/img.png"), _TelegramEvent(), segments)
    )

    assert segments[0]["type"] == "photo"
    assert Path(segments[0]["data"]["file"]).is_file()


def test_failed_document_download_leaves_segment_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取不到字节就保持段原样（既有"标签降级"行为不变），不抛、不改型。"""

    async def _fail(url: str, **kwargs: Any) -> bytes | None:
        return None

    monkeypatch.setattr(telegram_media, "_download_bytes", _fail)
    segments = [{"type": "document", "data": {"file": "DOCID4"}}]

    asyncio.run(
        enrich_telegram_file_segments(_FakeBot("files/a.pdf"), _TelegramEvent(), segments)
    )

    assert segments[0]["type"] == "document"
    assert segments[0]["data"]["file"] == "DOCID4"


def test_no_second_read_throat_in_the_telegram_leg() -> None:
    """防回潮：TG 文件腿只准落字节＋改写段形状，不许自己开第二条读文件通路。"""
    import ast

    source = Path(
        "plugins/bot_unified_runtime/domains/media/ingest/telegram_media.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(f"{node.module or ''}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    assert not any("file_reader" in name for name in names), (
        "TG 腿自己 import 了文件读取件＝第二通路，读取一律交根入站那一颗咽喉"
    )
