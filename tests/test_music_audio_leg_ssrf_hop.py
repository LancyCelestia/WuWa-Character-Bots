"""W7 回归锁：点歌「试听音频下载腿」的逐跳咽喉复查 + 音频族文件头 + 限额。

审计实证（修复前**零锁**、可直接利用）：``domains/music/capabilities/music.py``
的 ``_default_audio_downloader`` 入口过了咽喉，却把跳转整段交给 httpx
（``follow_redirects=True``），而逐跳钩子 ``_scrub_hop`` 只剥凭证、**不判内网**，
全文对 ``response.url`` 零复查 ⇒ 一条公网直链回 302→``127.0.0.1:3001``
（OneBot 端点）或 ``169.254.169.254``（云元数据）即盲连，响应字节落盘成
``song_<sha1>.<ext>`` 再发进群＝内网读原语；该腿同时**没有** magic bytes 判定。

本文件钉五件事（缺一不可）：
1. **逐跳零连接**：公网入口 302→内网落点时，落点那一跳绝不发出（``sent`` 只含入口）。
2. **正向不误伤**：公网入口→公网落点的真音频仍能取回落盘（后缀按字节判定）。
3. **文件头验真**：伪装 ``audio/mpeg`` 的 JSON/HTML 字节一律不落盘。
4. **限额生效**：逐块限读（不是整读进内存才检查）；缓存配额在 config 缺席时
   也**绝不**回落成 ``0＝不限``。
5. **拒绝不回落**（审查 F-2 类比）：咽喉明确拒绝 ⇒ ``RejectedUrlError`` 上抛，
   ``_media_parts_for_mode`` 据此把媒体段整条撤下——绝不把已判危险的 URL 交给
   协议端自取（那是同一个洞换个执行者）。

全离线纪律：``httpx.Client`` 打桩成忠实逐跳假件（``follow_redirects`` 开/关两种
语义都按 httpx 真实行为模拟：自动跟随时每一跳照样跑 request 钩子）；入口与落点
一律用**字面量 IP**，使咽喉走字面量判定分支、零 DNS、零真网络请求。
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import httpx
import pytest

import plugins.bot_unified_runtime.domains.files.sources.downloader as downloader_mod
import plugins.bot_unified_runtime.domains.music.capabilities.music as music_mod
from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    RejectedUrlError,
)

# 字面量公网地址（咽喉直接放行、零 DNS）与三类必拦落点。
ENTRY = "http://93.184.216.34/song.mp3"
PUBLIC_LANDING = "http://93.184.216.35/cdn/song.mp3"
ONEBOT_LANDING = "http://127.0.0.1:3001/get_group_msg_report"
METADATA_LANDING = "http://169.254.169.254/latest/meta-data/iam/security-credentials"
PRIVATE_LAN = "http://192.168.1.7/x.mp3"

BLOCKED_URLS = [
    "http://127.0.0.1:3001/seg",
    METADATA_LANDING,
    PRIVATE_LAN,
    "http://localhost:8080/x.mp3",
    "file:///C:/Windows/win.ini",
]

# 各族音频字节的**最小可判定头**（≥12 字节，与 _audio_suffix_from_header 同尺）。
MP3_ID3 = b"ID3\x04\x00\x00\x00\x00\x00\x09TIT2\x00\x00\x00\x05" + b"song!"
MP3_SYNC = b"\xff\xfb\x90\x00" + b"\x00" * 24
FLAC = b"fLaC\x00\x00\x00\x22" + b"\x00" * 20
OGG = b"OggS\x00\x02\x00\x00" + b"\x00" * 20
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 8
M4A = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00M4A mp42isom"
# 伪装形态：content-type 自称 audio/mpeg，字节其实是元数据响应。
FAKE_JSON = b'{"region":"us-east-1","iam":{"Code":"Success"}}'
FAKE_HTML = b"<html><body>internal dashboard</body></html>"


# --------------------------------------------------------------------------- #
# 假 httpx：忠实模拟「自动跟随 / 手动逐跳」两种语义
# --------------------------------------------------------------------------- #
class _Req:
    """httpx ``Request`` 替身：钩子只用到 ``str(request.url)`` 与可变的 ``headers``。"""

    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self.url = url
        self.headers = headers


class _Resp:
    def __init__(self, status_code: int, body: bytes, headers: dict[str, str]) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers)
        self._body = body

    def iter_bytes(self, chunk_size: int | None = None):
        step = int(chunk_size or 0) or 64
        for offset in range(0, len(self._body), step):
            yield self._body[offset : offset + step]

    @property
    def content(self) -> bytes:  # 旧形 ``client.get`` 的读法（回归时照样能用）
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("stub", request=None, response=self)  # type: ignore[arg-type]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _install_fake_httpx(monkeypatch, script: dict[str, dict]):
    """把 ``httpx.Client`` 替身装好，返回 ``(sent, built, headers_log)``。

    - ``sent``：真正「发出」的每一跳 URL（钩子放行后才记账）；
    - ``built``：Client 构造参数（钉 ``follow_redirects`` 必须为 False、代理键缺省形态）；
    - ``headers_log``：每跳实际带出去的请求头键名（钉跨 host 剥凭证）。
    """
    sent: list[str] = []
    built: list[dict] = []
    headers_log: list[tuple[str, tuple[str, ...]]] = []

    def _issue(url: str, base_headers: dict, hooks, follow: bool) -> _Resp:
        current = url
        seen: set[str] = set()
        while True:
            request = _Req(current, dict(base_headers or {}))
            for hook in hooks:
                hook(request)
            sent.append(current)
            headers_log.append((current, tuple(sorted(k.lower() for k in request.headers))))
            spec = script.get(current) or {}
            status = int(spec.get("status", 404))
            location = str(spec.get("location") or "")
            headers = {str(k).lower(): str(v) for k, v in (spec.get("headers") or {}).items()}
            if location:
                headers["location"] = location
            if follow and location and status in {301, 302, 303, 307, 308} and current not in seen:
                seen.add(current)
                current = str(httpx.URL(current).join(location))
                continue
            return _Resp(status, bytes(spec.get("body", b"")), headers)

    class _StreamCtx:
        def __init__(self, client, url: str) -> None:
            self._resp = _issue(
                str(url), client._headers, client._hooks, client._follow
            )

        def __enter__(self) -> _Resp:
            return self._resp

        def __exit__(self, *exc: object) -> bool:
            return False

    class _FakeClient:
        def __init__(self, **kwargs) -> None:
            built.append(dict(kwargs))
            self._hooks = (kwargs.get("event_hooks") or {}).get("request", [])
            self._follow = kwargs.get("follow_redirects") is True
            self._headers = dict(kwargs.get("headers") or {})

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def stream(self, method: str, url: str, **kwargs) -> _StreamCtx:
            return _StreamCtx(self, url)

        def get(self, url: str, **kwargs) -> _Resp:  # 旧形通路（回归即被 sent 抓）
            return _issue(str(url), self._headers, self._hooks, self._follow)

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    return sent, built, headers_log


def _config(tmp_path: Path, **overrides):
    values: dict[str, object] = {
        "bot_music_dir": str(tmp_path / "music"),
        "bot_download_max_bytes": 1 << 20,
        "bot_download_timeout_seconds": 5,
        "bot_download_proxy": "",
        "bot_music_cache_max_bytes": 1 << 20,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _files_in(tmp_path: Path) -> list[str]:
    root = tmp_path / "music"
    return sorted(p.name for p in root.glob("*")) if root.exists() else []


# --------------------------------------------------------------------------- #
# 1) 逐跳咽喉：入口 + 落点
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_url", BLOCKED_URLS)
def test_blocked_entry_never_issues_a_request(bad_url: str, tmp_path, monkeypatch) -> None:
    """入口即被咽喉拒：一跳都不发出，且明确拒绝上抛（不静默降级成 None）。"""
    sent, _built, _log = _install_fake_httpx(monkeypatch, {})

    with pytest.raises(RejectedUrlError):
        music_mod._default_audio_downloader(_config(tmp_path))(bad_url)

    assert sent == [], f"被拦地址不得发出请求：{bad_url}"
    assert _files_in(tmp_path) == []


@pytest.mark.parametrize("landing", [ONEBOT_LANDING, METADATA_LANDING, PRIVATE_LAN])
def test_public_redirect_to_internal_landing_never_sent(
    landing: str, tmp_path, monkeypatch
) -> None:
    """主锁（RED 形＝修复前）：公网直链 302→内网/元数据落点，落点那一跳绝不发出。

    摘掉逐跳咽喉（或改回 ``follow_redirects=True`` 交给客户端自动跟随）时，假件会
    忠实把落点记进 ``sent`` 并把内网响应字节交给落盘 ⇒ 本锁当场红。
    """
    script = {ENTRY: {"status": 302, "location": landing}, landing: {"status": 200, "body": FAKE_JSON}}
    sent, built, _log = _install_fake_httpx(monkeypatch, script)

    with pytest.raises(RejectedUrlError):
        music_mod._default_audio_downloader(_config(tmp_path))(ENTRY)

    assert sent == [ENTRY], f"落点那一跳被记账为已发出：{sent!r}"
    assert _files_in(tmp_path) == []
    assert built and all(
        item.get("follow_redirects") is False for item in built
    ), "跳转不许再交给 httpx 自动完成"


def test_relative_location_landing_is_rechecked_too(tmp_path, monkeypatch) -> None:
    """相对 Location 也要按当前跳解析后再复查——落点回环同样拒。"""
    script = {
        ENTRY: {"status": 302, "location": "/redirect"},
        "http://93.184.216.34/redirect": {
            "status": 302,
            "location": "http://127.0.0.1:3001/report",
        },
        ONEBOT_LANDING: {"status": 200, "body": FAKE_JSON},
    }
    sent, _built, _log = _install_fake_httpx(monkeypatch, script)

    with pytest.raises(RejectedUrlError):
        music_mod._default_audio_downloader(_config(tmp_path))(ENTRY)

    assert sent == [ENTRY, "http://93.184.216.34/redirect"], f"逐跳复查没盖住第二跳：{sent!r}"
    assert _files_in(tmp_path) == []


# --------------------------------------------------------------------------- #
# 2) 正向：公网链仍能取到音频（咽喉不过度拦）
# --------------------------------------------------------------------------- #
def test_public_redirect_chain_downloads_audio(tmp_path, monkeypatch) -> None:
    script = {
        ENTRY: {"status": 302, "location": PUBLIC_LANDING},
        PUBLIC_LANDING: {
            "status": 200,
            "body": MP3_ID3,
            "headers": {"content-type": "audio/mpeg"},
        },
    }
    sent, _built, _log = _install_fake_httpx(monkeypatch, script)

    path = music_mod._default_audio_downloader(_config(tmp_path))(ENTRY)

    assert sent == [ENTRY, PUBLIC_LANDING]
    assert path is not None and Path(path).read_bytes() == MP3_ID3
    assert Path(path).name.startswith("song_") and Path(path).suffix == ".mp3"


@pytest.mark.parametrize(
    ("body", "expected"),
    [(MP3_ID3, ".mp3"), (MP3_SYNC, ".mp3"), (FLAC, ".flac"), (OGG, ".ogg"), (WAV, ".wav"), (M4A, ".m4a")],
)
def test_suffix_comes_from_bytes_not_from_content_type(
    body: bytes, expected: str, tmp_path, monkeypatch
) -> None:
    """后缀真身＝字节头：content-type 一律自称 audio/mpeg 也休想改变落盘后缀。"""
    script = {ENTRY: {"status": 200, "body": body, "headers": {"content-type": "audio/mpeg"}}}
    _install_fake_httpx(monkeypatch, script)

    path = music_mod._default_audio_downloader(_config(tmp_path))(ENTRY)

    assert path is not None and Path(path).suffix == expected


# --------------------------------------------------------------------------- #
# 3) magic bytes：非音频字节不落盘
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("body", [FAKE_JSON, FAKE_HTML, b"\x89PNG\r\n\x1a\n" + b"\x00" * 16])
def test_non_audio_payload_is_never_written(body: bytes, tmp_path, monkeypatch) -> None:
    """伪装音频的文本/JSON/图片字节一律弃掉（这条腿曾经的落盘面＝读原语的最后一公里）。"""
    script = {ENTRY: {"status": 200, "body": body, "headers": {"content-type": "audio/mpeg"}}}
    _install_fake_httpx(monkeypatch, script)

    assert music_mod._default_audio_downloader(_config(tmp_path))(ENTRY) is None
    assert _files_in(tmp_path) == []


# --------------------------------------------------------------------------- #
# 4) 限额
# --------------------------------------------------------------------------- #
def test_size_cap_aborts_mid_stream(tmp_path, monkeypatch) -> None:
    """逐块限读：超限即弃，既不落盘也不把整包读进内存。"""
    script = {ENTRY: {"status": 200, "body": MP3_SYNC + b"\x00" * 4096}}
    sent, _built, _log = _install_fake_httpx(monkeypatch, script)

    path = music_mod._default_audio_downloader(
        _config(tmp_path, bot_download_max_bytes=64)
    )(ENTRY)

    assert path is None and sent == [ENTRY]
    assert _files_in(tmp_path) == []


def test_cache_quota_is_enforced_even_without_config(tmp_path, monkeypatch) -> None:
    """核限额度（W7 结论）：旧形 ``getattr(config, ..., 0) or 0`` 在 config 缺席时
    静默回落成 0＝**不限总量**；现在回落成 Config 字段缺省，配额这一腿不再哑。"""
    script = {ENTRY: {"status": 200, "body": MP3_ID3}}
    _install_fake_httpx(monkeypatch, script)
    seen: dict[str, object] = {}

    from plugins.bot_unified_runtime.domains.chat_reply.runtime import cache_policy

    def spy(directory, *, max_bytes: int = 0, max_age_days: int = 0):
        seen["max_bytes"] = max_bytes
        return {"files_removed": 0, "bytes_removed": 0}

    monkeypatch.setattr(cache_policy, "enforce_quota", spy)

    config = _config(tmp_path, bot_music_dir=str(tmp_path / "music"))
    delattr(config, "bot_music_cache_max_bytes")  # 模拟「读不出这一键」的独立入口
    assert music_mod._default_audio_downloader(config)(ENTRY) is not None
    assert isinstance(seen.get("max_bytes"), int) and int(seen["max_bytes"]) > 0, (
        "配额读不出时必须回落在册缺省，绝不回落到 0＝不限"
    )
    # 管理员**显式**设 0＝「别清我的缓存」仍受尊重。
    assert music_mod._music_cache_quota_bytes(
        SimpleNamespace(bot_music_cache_max_bytes=0)
    ) == 0


# --------------------------------------------------------------------------- #
# 5) 单源 + 活性 + 拒绝不回落 + 凭证剥离
# --------------------------------------------------------------------------- #
def test_throat_is_live_on_every_hop_and_is_the_central_one(
    tmp_path, monkeypatch
) -> None:
    """活性锁：咽喉**每一跳都被真调**，且用的是 downloader 那一个函数对象（禁第二套）。"""
    script = {
        ENTRY: {"status": 302, "location": PUBLIC_LANDING},
        PUBLIC_LANDING: {"status": 200, "body": MP3_ID3},
    }
    _install_fake_httpx(monkeypatch, script)
    calls: list[str] = []
    original = downloader_mod.check_download_url

    def spy(url: str) -> None:
        calls.append(str(url))
        original(url)

    monkeypatch.setattr(downloader_mod, "check_download_url", spy)
    assert music_mod._default_audio_downloader(_config(tmp_path))(ENTRY) is not None
    assert calls == [ENTRY, PUBLIC_LANDING], "入口与落点必须共用同一处咽喉、逐跳各一次"


def test_guard_blocked_url_never_falls_back_to_raw_url(tmp_path, monkeypatch) -> None:
    """F-2 类比：咽喉明确拒绝 ⇒ 媒体段整条撤下；瞬时失败（None）仍照旧发原链接。"""
    item = SimpleNamespace(
        music=SimpleNamespace(audio_url=METADATA_LANDING),
        media=[],
        identity=None,
        content=None,
        creator=None,
    )
    parts = music_mod._media_parts_for_mode(
        item, "card+voice+file", audio_downloader=music_mod._default_audio_downloader(_config(tmp_path))
    )
    assert parts == [], f"被拒 URL 仍被交给协议端自取：{parts!r}"

    # 正向对照：注入「瞬时失败」的下载器（返回 None）时行为逐字节不变。
    transient = SimpleNamespace(
        music=SimpleNamespace(audio_url=ENTRY),
        media=[],
        identity=None,
        content=None,
        creator=None,
    )
    fallback_parts = music_mod._media_parts_for_mode(
        transient, "voice+file", audio_downloader=lambda _url: None
    )
    assert [p["file"] for p in fallback_parts] == [ENTRY, ENTRY]


def test_cookie_stripped_when_redirect_changes_host(tmp_path, monkeypatch) -> None:
    """WP1 凭证语义不许被本次改写弄丢：入口那跳带票，跨 host 那一跳绝不带。"""

    class _Cookie(str):
        cookie_domains: tuple[str, ...] = ("93.184.216.34",)

    monkeypatch.setattr(
        music_mod,
        "build_cookie_provider",
        lambda _config: SimpleNamespace(
            cookie_header=lambda _platform: _Cookie("MUSIC_U=secret")
        ),
    )
    script = {
        ENTRY: {"status": 302, "location": PUBLIC_LANDING},
        PUBLIC_LANDING: {"status": 200, "body": MP3_ID3},
    }
    _sent, _built, headers_log = _install_fake_httpx(monkeypatch, script)

    assert music_mod._default_audio_downloader(_config(tmp_path))(ENTRY) is not None
    by_url = {url: keys for url, keys in headers_log}
    assert "cookie" in by_url[ENTRY], "入口那跳该带平台票（票据绑定语义没被改坏）"
    assert "cookie" not in by_url[PUBLIC_LANDING], "跨 host 落点仍带 Cookie＝凭证泄露面回来了"


def test_proxy_key_shape_follows_ledger_71(tmp_path, monkeypatch) -> None:
    """台账 #71★红线：空代理键**绝不**写成显式 ``proxy=None``。

    显式传 proxy 会让 NO_PROXY/环境变量全部失效；而 ``proxy=None`` 也≠直连（httpx
    仍按 trust_env 回落到环境/注册表里的系统代理）。正确形态只有两种：配了才传那把键、
    没配一个键都不传——缺省 ``Client()`` 的 trust_env 回落语义原样保留。
    """
    script = {ENTRY: {"status": 200, "body": MP3_ID3}}
    _sent, built, _log = _install_fake_httpx(monkeypatch, script)

    assert music_mod._default_audio_downloader(_config(tmp_path))(ENTRY) is not None
    assert "proxy" not in built[-1], "空代理键被显式下发＝trust_env 回落被顺手关掉"

    proxied = _config(tmp_path, bot_download_proxy="http://127.0.0.1:7890")
    assert music_mod._default_audio_downloader(proxied)(ENTRY) is not None
    assert built[-1]["proxy"] == "http://127.0.0.1:7890"


def test_leg_has_no_auto_redirect_following() -> None:
    """棘轮锁：本腿不得再出现「把跳转交给客户端自动完成」的形态。"""
    source = Path(music_mod.__file__).read_text(encoding="utf-8")
    assert not re.search(r"follow_redirects\s*[=:]\s*True", source), (
        "follow_redirects=True 必须伴随逐跳咽喉复查；本腿已改手动逐跳"
    )
    assert '"follow_redirects": False' in source and "check_download_url" in source
