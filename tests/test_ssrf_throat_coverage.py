"""F2 席回归锁：SSRF 咽喉两处漏毒收编（群图收库下载 / ``downloader.probe``）。

取证坐标（审计 U1-15 / U1-10、U11b §1 D1-F1、U9 F-U9-01）：

- ``domains/meme/sources/meme_library_listener.py:_download_once``
  —— 全文件零咽喉调用，且 ``follow_redirects=True`` 不复查落点；URL 由任意群成员发消息诱发。
- ``domains/files/sources/downloader.py:probe``
  —— 同文件 ``download()`` 过 ``check_download_url``，``probe()`` 从未过；
  ``content_parser.py:739/759`` 把页面派生 URL（``audio_url``/``canonical_url``）直送 ``probe()``。

本文件的锁三件事（缺一不可）：
1. **咽喉被调**：被拦地址在发出任何请求/交给 yt-dlp 之前就被拒（``requested == []``）。
2. **逐跳复查**：公网入口 302 → 内网落点时，落点那一跳**绝不发出**。
3. **单源不加戏**：咽喉本体全树唯一定义，两处收编复用同一个函数对象
   （调用点各 1 处，``probe``/``download`` 共享同一个 helper）——严禁第二套校验。

离线约定：全部出口打桩（httpx / yt-dlp），URL 一律用**字面量 IP**，
使咽喉走「字面量私网/公网判定」分支而不触发 DNS；零真网络请求。
"""

from __future__ import annotations

import ast
import asyncio
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import httpx
import pytest

import plugins.bot_unified_runtime.domains.files.sources.downloader as downloader_mod
from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    MediaDownloader,
    RejectedUrlError,
)
from plugins.bot_unified_runtime.domains.meme.sources import (
    meme_library_listener as listener,
)

# 字面量公网地址（咽喉直接放行，不触 DNS）与三类必拦地址。
PUBLIC_ENTRY = "http://93.184.216.34/a.png"
PUBLIC_LANDING = "http://93.184.216.35/b.png"
LOOPBACK = "http://127.0.0.1:8742/card.png"
METADATA = "http://169.254.169.254/latest/meta-data/iam.png"
PRIVATE_LAN = "http://192.168.1.7/x.png"

MAX_BYTES = 1 << 20

# 咽喉必拦样本（协议白名单 + 主机黑名单 + 私网/保留段，全部零 DNS）。
BLOCKED_URLS = [
    LOOPBACK,
    METADATA,
    PRIVATE_LAN,
    "http://localhost:8080/x.png",
    "file:///C:/Windows/win.ini",
]


# --------------------------------------------------------------------------- #
# 探针：AST 级「咽喉调用点份数」计数（证明同源复用，不是复制两份校验逻辑）
# --------------------------------------------------------------------------- #
def _ast_call_count(module) -> int:
    """模块内对 ``check_download_url`` 的**调用**次数（不含 def 与 import）。"""
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name == "check_download_url":
            calls += 1
    return calls


def _shared_guard_call_count(module, helper: str) -> int:
    """``helper``（咽喉 helper）在模块内被调用的次数。"""
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) == helper
    )


# --------------------------------------------------------------------------- #
# 离线替身：httpx AsyncClient（忠实模拟 follow_redirects 开/关两种语义）
# --------------------------------------------------------------------------- #
class _FakeStreamResponse:
    def __init__(self, status_code: int, body: bytes, headers: dict[str, str]) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers)
        self._body = body

    async def aiter_bytes(self):
        if self._body:
            yield self._body

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class _ScriptedClient:
    """替身：``script`` 为「请求 URL → 该 URL 的响应规格」。

    ``follow_redirects=True`` 时忠实模拟 httpx 客户端**自行**一路跟到底
    （每一跳都记进 ``requested``）——这正是修复前那条「不复查落点」的形态。
    """

    def __init__(
        self, script: dict[str, dict], requested: list[str], **kwargs: object
    ) -> None:
        self._script = script
        self._requested = requested
        self._follows = kwargs.get("follow_redirects") is True

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    def stream(self, method: str, url: str) -> _FakeStreamResponse:
        hops = [str(url)]
        if self._follows:
            current = str(url)
            while True:
                nxt = str((self._script.get(current) or {}).get("location") or "")
                if not nxt or nxt in hops:
                    break
                current = nxt
                hops.append(current)
        self._requested.extend(hops)
        spec = self._script.get(hops[-1]) or {}
        headers = {str(k): str(v) for k, v in (spec.get("headers") or {}).items()}
        location = str(spec.get("location") or "")
        if location:
            headers["location"] = location
        return _FakeStreamResponse(
            int(spec.get("status", 404)), bytes(spec.get("body", b"")), headers
        )


def _install_fake_httpx(monkeypatch, script: dict[str, dict]):
    requested: list[str] = []
    kwargs_log: list[dict] = []

    def factory(**kwargs: object) -> _ScriptedClient:
        kwargs_log.append(dict(kwargs))
        return _ScriptedClient(script, requested, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return requested, kwargs_log


def _make_downloader(monkeypatch, tmp_path: Path, requested: list[str]) -> MediaDownloader:
    """yt-dlp 出口打桩：``extract_info`` 收到的 URL 记进 ``requested``。"""
    monkeypatch.setattr(downloader_mod, "yt_dlp", SimpleNamespace(YoutubeDL=object))

    @contextmanager
    def fake_youtube_dl(self, opts: dict):
        class _Ydl:
            def extract_info(self, url: str, download: bool = False):
                requested.append(str(url))
                return {"title": "stubbed"}

        yield _Ydl()

    monkeypatch.setattr(MediaDownloader, "_youtube_dl", fake_youtube_dl)
    return MediaDownloader(download_dir=str(tmp_path / "downloads"), aria2_enabled=False)


def _download(url: str) -> tuple[bytes, str] | None:
    return asyncio.run(
        listener._download_once(url, max_bytes=MAX_BYTES, proxy="")
    )


# --------------------------------------------------------------------------- #
# 1) downloader.probe()：入口咽喉（D1-F1）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_url", BLOCKED_URLS)
def test_probe_rejects_guard_blocked_url_without_touching_ytdlp(
    bad_url: str, monkeypatch, tmp_path
) -> None:
    """RED（修复前）：probe 从不查咽喉 → 地址原样交给 yt-dlp。"""
    requested: list[str] = []
    downloader = _make_downloader(monkeypatch, tmp_path, requested)

    with pytest.raises(RuntimeError) as failure:
        downloader.probe(bad_url)

    assert requested == [], f"被拦地址不得抵达 yt-dlp：{bad_url}"
    message = str(failure.value)
    assert "yt-dlp 未安装" not in message  # 拒绝原因必须是咽喉判定，不是环境缺失
    assert message.strip(), "调用方必须拿到可操作原因（不静默吞）"


def test_probe_allows_public_literal_ip(monkeypatch, tmp_path) -> None:
    """正向锁：咽喉放行时 probe 行为不变（不过度拦、契约不变）。"""
    requested: list[str] = []
    downloader = _make_downloader(monkeypatch, tmp_path, requested)

    analysis = downloader.probe(PUBLIC_ENTRY)

    assert requested == [PUBLIC_ENTRY]
    assert analysis.title == "stubbed"


def test_probe_and_download_share_one_guard_call_site(monkeypatch, tmp_path) -> None:
    """同源锁：probe 与 download 调用**同一个**咽喉一次，且失败原因同源。"""
    calls: list[str] = []

    def spy(url: str) -> None:
        calls.append(url)
        raise RejectedUrlError("演练拒绝：内网/保留网段")

    monkeypatch.setattr(downloader_mod, "check_download_url", spy)
    requested: list[str] = []
    downloader = _make_downloader(monkeypatch, tmp_path, requested)

    outcome = downloader.download(PUBLIC_ENTRY)
    with pytest.raises(RuntimeError) as probe_failure:
        downloader.probe(PUBLIC_ENTRY)

    assert calls == [PUBLIC_ENTRY, PUBLIC_ENTRY], "两处各且仅各过一次咽喉"
    assert "演练拒绝：内网/保留网段" in (outcome.error or "")
    assert "演练拒绝：内网/保留网段" in str(probe_failure.value)
    assert requested == []


def test_downloader_guard_lives_in_a_single_helper() -> None:
    """结构锁：咽喉调用点全文件唯一（``probe``/``download`` 共享同一 helper）。"""
    assert _ast_call_count(downloader_mod) == 1, "downloader 内 check_download_url 调用点必须只有一处"
    assert (
        _shared_guard_call_count(downloader_mod, "_url_rejection_reason") == 2
    ), "probe/download 各自只调一次共享 helper（不得复制两份校验逻辑）"


# --------------------------------------------------------------------------- #
# 2) 群图收库：入口咽喉（U1-15 / U1-10）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_url", BLOCKED_URLS)
def test_meme_listener_rejects_blocked_url_before_request(
    bad_url: str, monkeypatch
) -> None:
    """RED（修复前）：该文件零咽喉调用，地址直接 GET 出去。"""
    requested, _ = _install_fake_httpx(monkeypatch, {})

    assert _download(bad_url) is None
    assert requested == [], f"被拦地址不得发出请求：{bad_url}"


def test_meme_listener_rechecks_every_redirect_hop(monkeypatch) -> None:
    """RED（修复前）：``follow_redirects=True`` 一路跟到元数据地址且不复查。"""
    script = {
        PUBLIC_ENTRY: {"status": 302, "location": METADATA},
        METADATA: {"status": 200, "body": b"CRED-MATERIAL"},
    }
    requested, _ = _install_fake_httpx(monkeypatch, script)

    assert _download(PUBLIC_ENTRY) is None
    assert requested == [PUBLIC_ENTRY], (
        "落点那一跳必须先过咽喉再发请求，实测发出：" + repr(requested)
    )


def test_meme_listener_allows_public_redirect_chain(monkeypatch) -> None:
    """正向锁：公网入口 → 公网落点照旧取回字节（咽喉不过度拦）。"""
    script = {
        PUBLIC_ENTRY: {"status": 302, "location": PUBLIC_LANDING},
        PUBLIC_LANDING: {
            "status": 200,
            "body": b"image-bytes",
            "headers": {"content-type": "image/png"},
        },
    }
    requested, _ = _install_fake_httpx(monkeypatch, script)

    assert _download(PUBLIC_ENTRY) == (b"image-bytes", "image/png")
    assert requested == [PUBLIC_ENTRY, PUBLIC_LANDING]


def test_meme_listener_logs_rejection_reason(monkeypatch, caplog) -> None:
    """失败面锁：拒绝按咽喉文案在抛出点 WARNING 留痕（与 media_archive F-06 同构）。"""
    _install_fake_httpx(monkeypatch, {})

    with caplog.at_level(logging.WARNING, logger=listener.__name__):
        assert _download(PRIVATE_LAN) is None

    assert any(
        "ssrf" in record.getMessage().lower() for record in caplog.records
    ), "咽喉拒绝必须留痕，不得静默吞"
    assert any("内网" in record.getMessage() for record in caplog.records)


def test_meme_listener_stops_at_the_entry_hop(monkeypatch) -> None:
    """RED（修复前）：修复后逐跳复查由**同一处**咽喉调用完成，调用点唯一。"""
    assert _ast_call_count(listener) == 1, (
        "meme 收库的咽喉调用点必须唯一（入口与每一跳共用同一处调用）"
    )


def test_listener_no_unguarded_redirect_following() -> None:
    """棘轮锁（U9 建议口径）：收库侧不得再出现「自动跟随重定向」形态。"""
    source = Path(listener.__file__).read_text(encoding="utf-8")
    assert not re.search(r"follow_redirects\s*[=:]\s*True", source), (
        "follow_redirects=True 必须伴随逐跳咽喉复查；本文件改手动逐跳"
    )
    assert "check_download_url" in source


def test_guard_definition_is_unique_across_plugin_tree() -> None:
    """单源锁：咽喉本体全树唯一定义，两处收编 import 的是同一个函数对象。"""
    plugin_root = Path(downloader_mod.__file__).parent.parent.parent.parent
    definitions = [
        path
        for path in plugin_root.rglob("*.py")
        if re.search(r"^def check_download_url\(", path.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert definitions == [Path(downloader_mod.__file__)]
    assert getattr(listener, "check_download_url", None) is downloader_mod.check_download_url
    media_archive = __import__(
        "plugins.bot_unified_runtime.domains.media.capabilities.media_archive",
        fromlist=["check_download_url"],
    )
    assert media_archive.check_download_url is downloader_mod.check_download_url
