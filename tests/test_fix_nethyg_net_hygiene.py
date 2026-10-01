"""S-FIX-NETHYG 网络卫生族回归锁（F-V-2 出站语音咽喉 / F-1 kurobbs 裸 opener 三件套）。

出处：
- SEAT-ATK-VISION.md F-V-2：``sender/nonebot.py::_download_voice_source`` 是全仓出站
  取字节腿里唯一不过中央 SSRF 咽喉的一条（入站 vision/transcribe/downloader 全闸）。
- SEAT-ATK-LINKPARSE.md F-1：``link_parse/parsers/platforms_kurobbs.py::_kuro_post_detail``
  裸 opener 三件套——(a) ``response.read()`` 无界、(b) ``gzip.decompress`` 无解压限幅
  （膨胀炸弹）、(c) 自定义 ``token`` 头跨 host 302 不在中央三桶剥除名单内。

全离线纪律（对齐 tests/test_audio_ingest_ssrf_hop.py 假件惯例）：
- 语音腿：monkeypatch ``httpx.AsyncClient`` 为忠实逐跳假件——每一跳「发出」前先跑生产
  注册的 request 事件钩，钩内 ``check_download_url`` 抛 ``RejectedUrlError`` 即中止、
  绝不记账为已发出；入口/落点全用字面量 IP（93.x 公网、127.0.0.1/169.254.169.254
  内网）走咽喉离线判定，零 DNS、零真网络。
- kurobbs 腿：monkeypatch ``urllib.request.build_opener`` 捕获 handler 与 Request，
  响应为可控假件；不真发任何请求。
"""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from typing import Any, Self

import httpx
import pytest

from plugins.bot_unified_runtime.domains.link_parse.parsers import http_util
from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    platforms_kurobbs as K,
)
from plugins.bot_unified_runtime.domains.transport.sender import nonebot as N

# ---------------------------------------------------------------------------
# 共用：SSRF 判定用字面量 URL（咽喉对字面量 IP 直接判定，零 DNS）
# ---------------------------------------------------------------------------
_PUBLIC_ENTRY = "http://93.184.216.34/voice.bin"
_PUBLIC_LANDING = "http://93.184.216.35/real.bin"
_INTERNAL_LANDING = "http://127.0.0.1:9/secret"
_METADATA_LANDING = "http://169.254.169.254/latest"
_PRIVATE_ENTRY = "http://169.254.169.254/loop"


# ===========================================================================
# F-V-2：出站语音取字节腿接中央咽喉（入口闸 + 逐跳事件钩）
# ===========================================================================
class _Req:
    """httpx ``Request`` 替身：钩子只用到 ``str(request.url)``。"""

    def __init__(self, url: str) -> None:
        self.url = url


class _Resp:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = {"content-length": str(len(body))}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPError(f"stub status {self.status_code}")

    async def aiter_bytes(self) -> Any:
        if self._body:
            yield self._body


def _install_fake_async_httpx(monkeypatch: pytest.MonkeyPatch, script: dict[str, tuple]):
    """把 ``httpx.AsyncClient`` 替身为忠实逐跳假件（镜像 test_audio_ingest_ssrf_hop.py）。

    ``script``: url -> ("redirect", location) | ("body", bytes)。返回 ``(sent, built)``：
    sent=真正「发出」的 URL 序（钩子放行后才记账），built=AsyncClient 构造 kwargs 列表。
    """
    sent: list[str] = []
    built: list[dict] = []

    class _StreamCtx:
        def __init__(self, client: _FakeAsyncClient, url: str) -> None:
            self._c = client
            self._url = url

        async def __aenter__(self) -> _Resp:
            url = self._url
            seen: set[str] = set()
            while True:
                for hook in self._c._hooks:  # 发请求前跑逐跳咽喉（钩子抛错即中止）
                    res = hook(_Req(url))
                    if hasattr(res, "__await__"):
                        await res
                sent.append(url)  # 钩子放行 = 这一跳真会发出
                spec = self._c._script.get(url)
                if spec is None:
                    return _Resp(404, b"")
                kind = spec[0]
                if kind == "redirect":
                    location = str(spec[1])
                    if self._c._follow and location and location not in seen:
                        seen.add(url)
                        url = location
                        continue
                    return _Resp(302, b"")
                if kind == "body":
                    return _Resp(200, bytes(spec[1]))
                return _Resp(404, b"")

        async def __aexit__(self, *exc: object) -> bool:
            return False

    class _FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            built.append(dict(kwargs))
            self._hooks = (kwargs.get("event_hooks") or {}).get("request", [])
            self._follow = kwargs.get("follow_redirects") is True
            self._script = script

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        def stream(self, method: str, url: str, **kwargs: object) -> _StreamCtx:
            return _StreamCtx(self, str(url))

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return sent, built


@pytest.mark.asyncio
async def test_voice_entry_rejected_before_any_client(tmp_path: Path, monkeypatch) -> None:
    """F-V-2 入口闸：内网/元数据入口直接返回 None——连 AsyncClient 都不建、零出站。"""
    dest = tmp_path / "a.src"
    sent, built = _install_fake_async_httpx(monkeypatch, {})
    assert await N._download_voice_source(_PRIVATE_ENTRY, dest) is None
    assert built == [], "内网入口不得建客户端（咽喉必须在建连之前）"
    assert sent == [] and not dest.exists()


@pytest.mark.asyncio
async def test_voice_illegal_scheme_rejected(tmp_path: Path, monkeypatch) -> None:
    """F-V-2 入口闸：非 http(s) 协议（file://）同样在建连前拒掉，绝不交给 httpx。"""
    dest = tmp_path / "b.src"
    sent, built = _install_fake_async_httpx(monkeypatch, {})
    assert await N._download_voice_source("file:///C:/Windows/win.ini", dest) is None
    assert built == [] and sent == [] and not dest.exists()


@pytest.mark.asyncio
async def test_voice_redirect_to_internal_landing_never_sent(
    tmp_path: Path, monkeypatch
) -> None:
    """F-V-2 逐跳主锁：公网入口 302→内网落点——内网那一跳发出前即被钩拒，绝不发出。

    RED 反证（钩子被摘的回归）：若 ``event_hooks`` 未注册 ``_guard_hop``，假件会把
    内网落点记账为已发出 → 本锁当场红。
    """
    dest = tmp_path / "c.src"
    script = {_PUBLIC_ENTRY: ("redirect", _INTERNAL_LANDING)}
    sent, _built = _install_fake_async_httpx(monkeypatch, script)
    assert await N._download_voice_source(_PUBLIC_ENTRY, dest) is None
    assert sent == [_PUBLIC_ENTRY], "只有入口这一跳发出，内网落点零连接"
    assert _INTERNAL_LANDING not in sent
    assert not dest.exists()


@pytest.mark.asyncio
async def test_voice_redirect_to_metadata_landing_never_sent(
    tmp_path: Path, monkeypatch
) -> None:
    """F-V-2 落点=云元数据面：与回环同级，逐跳复查在建连前拒掉。"""
    dest = tmp_path / "d.src"
    script = {_PUBLIC_ENTRY: ("redirect", _METADATA_LANDING)}
    sent, _built = _install_fake_async_httpx(monkeypatch, script)
    assert await N._download_voice_source(_PUBLIC_ENTRY, dest) is None
    assert sent == [_PUBLIC_ENTRY] and _METADATA_LANDING not in sent


@pytest.mark.asyncio
async def test_voice_public_path_still_fetches_bytes(tmp_path: Path, monkeypatch) -> None:
    """F-V-2 正向锁：公网入口→公网落点照旧取回字节写盘（咽喉不过度拦、契约不变）。"""
    dest = tmp_path / "e.src"
    script = {
        _PUBLIC_ENTRY: ("redirect", _PUBLIC_LANDING),
        _PUBLIC_LANDING: ("body", b"OPUS-BYTES"),
    }
    sent, _built = _install_fake_async_httpx(monkeypatch, script)
    got = await N._download_voice_source(_PUBLIC_ENTRY, dest)
    assert got is dest
    assert sent == [_PUBLIC_ENTRY, _PUBLIC_LANDING]
    assert dest.read_bytes() == b"OPUS-BYTES"


# ===========================================================================
# F-1：kurobbs _kuro_post_detail —— (a) 无界读 (b) gzip 无界解压 (c) token 跨 host
# ===========================================================================
_OK_JSON = b'{"code": 200, "data": {"post": {"title": "hello"}}}'
# 合法 JSON + 尾部填充空白：json.loads 容忍尾随空白 ⇒ 「旧实现全量读回能成功解析、
# 返回 data」，新实现限幅读必超限抛 ParseHttpError。RED/GREEN 分野干净。
_OVER_LIMIT_PADDING = b" " * (http_util.DEFAULT_MAX_BYTES + 64)


class _FakeRawResp:
    """urllib 响应替身：记录每次 read 的 size 参数，headers 可控。"""

    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}
        self.read_sizes: list[Any] = []

    def read(self, size: Any = -1) -> bytes:
        self.read_sizes.append(size)
        if size is None or size < 0:
            return self._body
        return self._body[: int(size)]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeOpener:
    def __init__(self, handlers: tuple[Any, ...], response: _FakeRawResp) -> None:
        self.handlers = handlers
        self._response = response
        self.captured_request: Any = None

    def open(self, request: Any, timeout: Any = None) -> _FakeRawResp:
        self.captured_request = request
        return self._response


def _install_fake_opener(monkeypatch: pytest.MonkeyPatch, response: _FakeRawResp):
    """替身 ``urllib.request.build_opener``：捕获 handlers 与 Request，返回假响应。"""
    captured: dict[str, Any] = {}

    def _fake_build_opener(*handlers: Any, **_kw: Any) -> _FakeOpener:
        opener = _FakeOpener(handlers, response)
        captured["opener"] = opener
        captured["handlers"] = list(handlers)
        return opener

    monkeypatch.setattr(K.urlrequest, "build_opener", _fake_build_opener)
    return captured


def _run_detail() -> dict:
    # 假凭据显式命名（尺的 F2「夹具显式假值」面认 FAKE/EXAMPLE；旧写 SECRET-TOKEN
    # 落进 F1 欠账形、而点名册棘轮 32/32 满额无位可登记——S-BASE 基线席 2026-09-29 现算）。
    return K._kuro_post_detail("123", cookie_header="user_token=FAKE-TOKEN-EXAMPLE")


def test_kurobbs_read_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-1(a)：响应体读取必须限幅——超限体（合法 JSON+填充）不再被整读解析成功。

    RED 前态：``response.read()`` 无界全量读回 → json.loads 成功 → 返回 data，
    pytest.raises 落空即红。GREEN：``_read_capped`` 以 ``max_bytes+1`` 限幅读、
    超限抛 ParseHttpError（经既有失败面包裹），且假响应只可能被「有界 size」调用。
    """
    resp = _FakeRawResp(_OK_JSON + _OVER_LIMIT_PADDING)
    _install_fake_opener(monkeypatch, resp)
    with pytest.raises(http_util.ParseHttpError):
        _run_detail()
    assert resp.read_sizes and all(
        size is not None and 0 < int(size) <= http_util.DEFAULT_MAX_BYTES + 1
        for size in resp.read_sizes
    ), f"读必须带限幅参数（≤DEFAULT_MAX_BYTES+1），实况 {resp.read_sizes}"


def test_kurobbs_gzip_bomb_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-1(b)：gzip 膨胀炸弹（几 KB 压缩→ >上限 明文）必被解压限幅拒掉。

    RED 前态：``gzip.decompress`` 全量解压 20MB 合法 JSON → 解析成功 → 无异常即红。
    GREEN：``_read_capped`` 的 zlib 限幅解压（max_bytes+1 + unconsumed_tail 检查）
    在解压输出超限时抛 ParseHttpError，明文绝不整只进内存。
    """
    bomb_plain = _OK_JSON + b" " * (20 * 1024 * 1024)
    resp = _FakeRawResp(
        gzip.compress(bomb_plain), headers={"Content-Encoding": "gzip"}
    )
    _install_fake_opener(monkeypatch, resp)
    with pytest.raises(http_util.ParseHttpError):
        _run_detail()


def test_kurobbs_token_never_follows_crosshost_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-1(c)：token 凭证在跨 host 302 上必须「带不出去」，且剥除逻辑用中央单源。

    两道断言：
    1) 结构：opener 必须挂 ``_CredentialScrubbingRedirectHandler``（中央件，禁第二判据）；
       token 只准进 ``unredirected_hdrs``（urllib 原生：redirect_request 只复制
       req.headers），不得进 ``headers``。
    2) 行为：用捕获的真 handler 实例驱动一次跨 host redirect_request，落点请求头
       （含 header_items() 合并视图）里不得出现 token。

    RED 前态：build_opener() 裸挂（无 handler）且 token 在 headers 桶 ⇒ 两道皆红。
    """
    resp = _FakeRawResp(_OK_JSON)
    captured = _install_fake_opener(monkeypatch, resp)
    data = _run_detail()
    assert data.get("post", {}).get("title") == "hello"  # 正向契约不破

    handlers = captured["handlers"]
    scrub = [
        h for h in handlers
        if isinstance(h, http_util._CredentialScrubbingRedirectHandler)
    ]
    assert scrub, "kurobbs 腿必须挂中央凭证剥除 handler（单源，禁自造判据）"

    req = captured["opener"].captured_request
    hdr_keys = {str(k).lower() for k in req.headers}
    unred_keys = {str(k).lower() for k in req.unredirected_hdrs}
    assert "token" not in hdr_keys, "token 不得进可随重定向复制的 headers 桶"
    assert "token" in unred_keys, "token 必须经 add_unredirected_header 挂载"

    new_req = scrub[0].redirect_request(
        req, io.BytesIO(), 302, "Found", {"Location": "https://evil.example.com/x"},
        "https://evil.example.com/x",
    )
    assert new_req is not None
    carried = {str(k).lower() for k, _v in new_req.header_items()}
    assert "token" not in carried, "跨 host 重定向请求绝不携带 token"
    assert json.loads  # 引住 json 防 lint 误报（本文件确实用到 json 常量构造）


def test_kurobbs_small_response_contract_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-1 正向锁：正常小响应解析路径逐字不变（限幅改造不误伤主流程）。"""
    resp = _FakeRawResp(
        json.dumps({"code": 200, "data": {"post": {"title": "ok"}}}).encode("utf-8")
    )
    _install_fake_opener(monkeypatch, resp)
    data = _run_detail()
    assert data["post"]["title"] == "ok"
