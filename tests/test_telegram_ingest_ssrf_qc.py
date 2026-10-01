"""TG 取字节腿：SSRF 逐跳咽喉 + 归档 magic-bytes 真身 QC 的回归锁。

出处（先读的席报）：
- .superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-ADAPTERS.md（F-B：TG 取字节腿
  绕过 SSRF 咽喉，`telegram_media._download_bytes` follow_redirects 且不过咽喉）；
- 同目录 SEAT-ATK-INGEST.md（A-ING-2：TG file_id→字节无 magic-bytes 质检，
  与归档面不对称；修法=复用归档真身 sniff_extension，禁第二真身）。

修复口径（席位 S-FIX-TGMEDIA）：
1. 每一跳（入口 + 30x 落点）发出前过中央咽喉 ``check_download_url``——httpx
   ``request`` 事件钩子逐跳复查，与同域 ``transcribe._download_audio`` 同形
   （语义照 ``_GuardedShortLinkRedirectHandler``：解析失败=拒绝、建连前拦下），
   不造第二套 URL 判据；
2. 图像/视频段字节在 enrich 落盘前过归档真身 ``sniff_extension``
   （``domains/media/archive/media_archive.py``，单一真身）——识别不出的
   容器点名降级（段原样保留=标签降级），不落盘、不喂 vision，无假成功。

全离线纪律（照 tests/test_vision_image_ssrf_hop.py 与 tests/test_audio_ingest_
ssrf_hop.py 的假传输形态）：下载经生产缝 ``_build_download_client`` 注入
``httpx.MockTransport``——**真实 httpx 客户端语义保留**（逐跳 event hook、
follow_redirects 均在），只把 transport 换成记账假件；入口/落点全用字面量
IP（93.x 公网放行、127.0.0.1/169.254.169.254 拒绝），零 DNS、零真网络。
护栏被摘掉（注毒）时：内网那一跳会真的流进 MockTransport 记账 →
"requested 只有入口一跳"断言必红；QC 闸被摘 → 非法字节落盘断言必红。
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from plugins.bot_unified_runtime.domains.media.ingest import telegram_media
from plugins.bot_unified_runtime.domains.media.ingest.telegram_media import (
    enrich_telegram_file_segments,
    resolve_telegram_file_bytes,
)

# 字面量公网 IP（咽喉按字面量离线判定放行，零 DNS）；内网/链路本地元数据落点。
_ENTRY = "https://93.184.216.34/"
_PUBLIC_LANDING = "http://93.184.216.35/final.jpg"
_LOOPBACK_LANDING = "http://127.0.0.1:3001/status"
_METADATA_LANDING = "http://169.254.169.254/latest/meta-data/"
_FORGED_LOOPBACK_PATH = "http://127.0.0.1:3001/photos/img.jpg"
_FORGED_METADATA_PATH = "http://169.254.169.254/latest/meta-data/iam"
# 302 后落点为非法协议（判据层必拒的三形态；零示范面见 SEAT-ATK-SSRF-LOCKS.md
# 追加三问 #3）。实证（httpx 0.28 ``_send_handling_redirects``）：httpx **不**自带
# 重定向协议门——非 http scheme 的 Location 照样造下一跳请求并回调 request 钩子，
# 所以拦住它的只能是中央咽喉。公网主机两枚只被协议白名单拦住；``file://`` 另有
# 「缺少主机名」兜底，注毒归因在席报里分开记账。
_ILLEGAL_SCHEME_LANDINGS = [
    "file:///etc/passwd",
    "gopher://8.8.8.8:11211/_probe",
    "dict://8.8.8.8:11211/x",
]

# 合法/非法容器字节（JPEG/PNG/MP4/OGG 起始签名照归档真身；伪造容器=无签名流）。
_JPEG = b"\xff\xd8\xff\xe0jpeg-bytes"
_MP4 = b"\x00\x00\x00\x18ftypmp42-quiet-bits"
_OGG = b"OggS\x00\x02audio-bytes"
_GARBAGE = b"MZ\x90\x00this-is-not-a-media-container"


class _TelegramEvent:
    """仅在 __module__ 上带 .telegram 标记的假事件（模块据此判适配器）。"""


_TelegramEvent.__module__ = "nonebot.adapters.telegram.event"


class _FakeBot:
    """call_api(get_file) 假适配器；file_path 由"恶意 TG 服务器"任意可控。

    file_path 可为字符串（所有 file_id 同应答）或 dict（按 file_id 应答）。
    """

    def __init__(self, file_path: Any, *, token: str = "123456:secret") -> None:
        self.file_path = file_path
        self.bot_config = SimpleNamespace(token=token, api_server=_ENTRY)

    async def call_api(self, action: str, **params: Any) -> Any:
        if isinstance(self.file_path, dict):
            return SimpleNamespace(file_path=self.file_path[params["file_id"]])
        return SimpleNamespace(file_path=self.file_path)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(telegram_media, "_FILE_PATH_CACHE", {})
    monkeypatch.setattr(telegram_media, "_FILE_PATH_CACHE_ORDER", [])
    monkeypatch.delenv("TELEGRAM_PROXY", raising=False)
    monkeypatch.delenv("BOT_DOWNLOAD_PROXY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    yield


def _install_transport(
    monkeypatch: pytest.MonkeyPatch, routes: dict[str, httpx.Response]
) -> list[str]:
    """把记账 MockTransport 装进生产缝；返回记账表（每个到 transport 的请求）。

    路由表里**没有**的 URL 命中即抛——内网落点故意不建路由：护栏被摘、那一跳
    真发出来时，这里先炸，本身就是红线。
    """
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return routes[str(request.url)]

    real_build = telegram_media._build_download_client

    def fake_build(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_build(**kwargs)

    monkeypatch.setattr(telegram_media, "_build_download_client", fake_build)
    return requested


def _redirect(location: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": location})


def _telegram_records(caplog: pytest.LogCaptureFixture) -> str:
    """只取本模块日志（httpx 自带 INFO 会记请求 URL，不属本席承诺面）。"""
    return "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "plugins.bot_unified_runtime.domains.media.ingest.telegram_media"
    )


# ---------- (a) 伪造 file_path 直指回环/链路本地元数据：入口拒绝、零连接 ----------


@pytest.mark.parametrize("forged", [_FORGED_LOOPBACK_PATH, _FORGED_METADATA_PATH])
def test_forged_file_path_intranet_entry_rejected_without_request(
    monkeypatch: pytest.MonkeyPatch, forged: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A-ING-2/F-B 主锁①：get_file 回伪造绝对 URL 指内网——咽喉入口即拒，
    transport 零记账（请求根本没发出），降级为 None 且 token 不进日志。"""
    requested = _install_transport(monkeypatch, {})
    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(resolve_telegram_file_bytes(_FakeBot(forged), "fid")) is None
    assert requested == []
    assert "secret" not in _telegram_records(caplog)


@pytest.mark.parametrize("forged", [_FORGED_LOOPBACK_PATH, _FORGED_METADATA_PATH])
def test_enrich_forged_intranet_entry_keeps_segment(
    monkeypatch: pytest.MonkeyPatch, forged: str
) -> None:
    """咽喉拒绝后 enrich 段原样保留（标签降级），无假成功、整链不炸。"""
    requested = _install_transport(monkeypatch, {})
    segments = [{"type": "photo", "data": {"file": "fid"}}]
    asyncio.run(enrich_telegram_file_segments(_FakeBot(forged), _TelegramEvent(), segments))
    assert segments[0]["data"] == {"file": "fid"}
    assert requested == []


# ---------- (b) 30x 逐跳落点复查：公网入口 → 内网落点，那一跳绝不发出 ----------


def test_redirect_landing_intranet_aborts_before_hop(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """F-B 主锁②（逐跳有牙）：TG 服务器回公网 URL、302 落点指回环——
    记账只允许入口一跳；内网那一跳连 transport 都没进（钩子在建连前抛）。"""
    requested = _install_transport(monkeypatch, {f"{_ENTRY}file/bot123456:secret/photos/img.jpg": _redirect(_LOOPBACK_LANDING)})
    with caplog.at_level(logging.DEBUG):
        payload = asyncio.run(resolve_telegram_file_bytes(_FakeBot("photos/img.jpg"), "fid"))
    assert payload is None
    assert requested == [f"{_ENTRY}file/bot123456:secret/photos/img.jpg"]
    assert "RejectedUrlError" in _telegram_records(caplog)  # 点名：咽喉拒绝非静默
    assert "secret" not in _telegram_records(caplog)


def test_redirect_landing_metadata_aborts_before_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """落点指链路本地元数据面（169.254.169.254）同样拦在建连前。"""
    entry = f"{_ENTRY}file/bot123456:secret/x"
    requested = _install_transport(monkeypatch, {entry: _redirect(_METADATA_LANDING)})
    assert asyncio.run(resolve_telegram_file_bytes(_FakeBot("x"), "fid")) is None
    assert requested == [entry]


@pytest.mark.parametrize("landing", _ILLEGAL_SCHEME_LANDINGS)
def test_redirect_landing_illegal_scheme_aborts_before_hop(
    monkeypatch: pytest.MonkeyPatch, landing: str, caplog: pytest.LogCaptureFixture
) -> None:
    """F-B 逐跳锁（非法协议落点版）：302→file/gopher/dict——那一跳绝不发出。

    与 ``test_redirect_landing_intranet_aborts_before_hop`` 同一份 transport 记账、
    同一条咽喉（httpx request 钩子 ``_guard_hop``）。护栏被摘（或协议判定被放宽）时
    该跳会真的流进 MockTransport 记账 → ``requested`` 多一跳 → 本锁当场红。
    """
    entry = f"{_ENTRY}file/bot123456:secret/y"
    requested = _install_transport(monkeypatch, {entry: _redirect(landing)})
    with caplog.at_level(logging.DEBUG):
        payload = asyncio.run(resolve_telegram_file_bytes(_FakeBot("y"), "fid"))
    assert payload is None
    assert requested == [entry], f"非法协议落点那一跳竟被发出：{landing}"
    assert "RejectedUrlError" in _telegram_records(caplog)  # 点名：咽喉拒绝非静默


def test_redirect_to_public_landing_still_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """零回归：公网落点照旧跟随、字节照旧返回（正常链路契约不变）。"""
    entry = f"{_ENTRY}file/bot123456:secret/photos/img.jpg"
    requested = _install_transport(
        monkeypatch, {entry: _redirect(_PUBLIC_LANDING), _PUBLIC_LANDING: httpx.Response(200, content=_JPEG)}
    )
    assert asyncio.run(resolve_telegram_file_bytes(_FakeBot("photos/img.jpg"), "fid")) == _JPEG
    assert requested == [entry, _PUBLIC_LANDING]


# ---------- (c) QC：非法容器字节被归档真身拦下、点名降级、不落盘 ----------


def test_enrich_illegal_container_blocked_by_qc(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A-ING-2 主锁③：photo 段回无签名伪容器——sniff_extension（归档真身）
    识别不出 → 点名降级：不落临时文件、段原样（标签降级）、无假成功。"""
    entry = f"{_ENTRY}file/bot123456:secret/photos/img.jpg"
    _install_transport(monkeypatch, {entry: httpx.Response(200, content=_GARBAGE)})
    tmp_dir = Path(tempfile.gettempdir())
    before = set(tmp_dir.glob("bot_tg_media_*"))
    segments = [{"type": "photo", "data": {"file": "fid"}}]
    with caplog.at_level(logging.DEBUG):
        asyncio.run(enrich_telegram_file_segments(_FakeBot("photos/img.jpg"), _TelegramEvent(), segments))
    assert segments[0]["data"] == {"file": "fid"}
    assert set(tmp_dir.glob("bot_tg_media_*")) == before  # 一个临时文件都没多
    logs = _telegram_records(caplog)
    assert "telegram media qc rejected" in logs
    assert "unsupported_media_type" in logs


def test_enrich_legal_image_video_zero_regression(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A-ING-2 零回归锁：合法 JPEG（photo）与 ftyp MP4（video_note）字节
    照旧落盘写回 data.file——QC 不挡真媒体（归档真身说了算）。"""
    entry_jpg = f"{_ENTRY}file/bot123456:secret/a.jpg"
    entry_mp4 = f"{_ENTRY}file/bot123456:secret/b"
    _install_transport(
        monkeypatch,
        {
            entry_jpg: httpx.Response(200, content=_JPEG),
            entry_mp4: httpx.Response(200, content=_MP4),
        },
    )
    segments = [
        {"type": "photo", "data": {"file": "fid-jpg"}},
        {"type": "video_note", "data": {"file": "fid-mp4"}},
    ]
    asyncio.run(
        enrich_telegram_file_segments(
            _FakeBot({"fid-jpg": "a.jpg", "fid-mp4": "b"}), _TelegramEvent(), segments
        )
    )

    photo, video = segments
    jpg_file = Path(photo["data"]["file"])
    mp4_file = Path(video["data"]["file"])
    assert jpg_file.read_bytes() == _JPEG
    assert mp4_file.read_bytes() == _MP4
    jpg_file.unlink()
    mp4_file.unlink()


def test_enrich_voice_audio_passes_documented_residual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """登记残余的形状锁：归档真身无音频容器签名（ogg/mp3），为其自造签名表
    即禁碰的第二真身——voice 段合法 OggS 字节照旧落盘喂 ASR。将来归档真身
    扩覆音频面时，本用例连同 _QC_SEGMENT_TYPES 一起升级（此断言逼那次
    跟随显式发生，不静默漏）。"""
    entry = f"{_ENTRY}file/bot123456:secret/v"
    _install_transport(monkeypatch, {entry: httpx.Response(200, content=_OGG)})
    segments = [{"type": "voice", "data": {"file": "fid-v"}}]
    asyncio.run(enrich_telegram_file_segments(_FakeBot("v"), _TelegramEvent(), segments))
    written = Path(segments[0]["data"]["file"])
    assert written.read_bytes() == _OGG
    written.unlink()
