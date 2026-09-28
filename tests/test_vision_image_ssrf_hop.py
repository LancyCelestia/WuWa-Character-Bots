"""vision 取图重定向落点复查 + 拒绝 fail-closed 回归（攻击者复查 F-1/F-2 修复锁）。

出处：.superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-SSRF.md（F-1 高危 / F-2 中危），
修复席 S-ATKFIX-SSRF1（2026-09-27）。

背景（审查 F-1，高危）：``_download_image_bytes`` 入口过 SSRF 咽喉，但 urlopen
默认 opener 自动跟随 30x、逐跳落点零复查——图片 URL 一跳指进内网/云元数据时，
内网字节经 PIL → data URL → VLM 描述回显给任意群成员。修复后重定向走
``_guarded_image_opener``（复用既有 ``_GuardedShortLinkRedirectHandler``：每跳
落点先过 ssrf_guard.check_fetch_landing，判据仍是中央 check_download_url，
不造第二套咽喉）。

背景（审查 F-2，中危）：咽喉拒绝后原内网 URL 仍被 prepare_vision_image_urls
当「下载失败」保留兜底、透传给 VLM provider——本机构架的 provider 会自己连
内网。修复后：明确拒绝（入口 ``RejectedUrlError`` / 落点 ``ParseHttpError``）
丢图不回透（fail-closed）；仅「公网判定成立但瞬时下载失败」保留原 URL 兜底。

全离线纪律：传输层用假 HTTPHandler 记账每个「真实会发出」的请求（继承
HTTPHandler 才会顶掉默认真实处理器）；入口/落点用字面量 IP 走咽喉离线判定
（零 DNS）；测试只把 ``urllib.request.build_opener`` 包一层注入假传输件——
生产 ``_guarded_image_opener`` 的护栏 handler 装配本身不被 mock（摘掉护栏
handler，逐跳拒绝锁必红）。禁真实网络。
"""

from __future__ import annotations

import email.message
import io
import urllib.request as urlrequest
from urllib.response import addinfourl

import pytest
from PIL import Image

from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    RejectedUrlError,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
    _GuardedShortLinkRedirectHandler,
)
from plugins.bot_unified_runtime.domains.media.ingest import vision_describe as V

# 字面量公网 IP（93.184.216.34）：咽喉按字面量离线判定放行，零 DNS。
_ENTRY = "http://93.184.216.34/pic.jpg"
_PUBLIC_LANDING = "http://93.184.216.34/final.jpg"
# 字面量内网入口：咽喉入口即拒（F-2 语义下原样上抛，绝不进兜底）。
_PRIVATE_ENTRY = "http://127.0.0.1:3001/pic.jpg"


def _jpeg_bytes(w: int = 48, h: int = 32) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (w, h), (30, 120, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _clear_cache():
    V._REMOTE_DATA_URL_CACHE.clear()
    V._REMOTE_DATA_URL_CACHE_ORDER.clear()


class _FakeTransport(urlrequest.HTTPHandler):
    """假 HTTP 传输层：按路由表应答 30x/200，并记账每个将真实发出的请求。

    内网落点故意不建路由——护栏被摘、请求真会发到此处时 http_open 抛
    URLError（KeyError 记账即断言失败），本身就是一层红线。
    """

    def __init__(self, routes: dict[str, tuple[int, str, bytes]]):
        # routes: url -> (status, location, body)
        self.routes = routes
        self.requested: list[str] = []

    def http_open(self, req):
        url = req.full_url
        self.requested.append(url)
        status, location, body = self.routes[url]
        headers = email.message.Message()
        if location:
            headers["Location"] = location
        response = addinfourl(io.BytesIO(body), headers, url, status)
        response.msg = "fake"
        return response


def _install_guarded_transport(
    monkeypatch: pytest.MonkeyPatch, transport: _FakeTransport
) -> None:
    """包装 build_opener：生产工厂装配的真实 handler 原样流进 opener，只追加假传输层。

    护栏 handler（_GuardedShortLinkRedirectHandler）逐跳校验逻辑本身不被 mock；
    若生产侧把 handler 摘掉，落点拒绝锁立即变红。
    """
    real_build_opener = urlrequest.build_opener

    def wrapper(*handlers):
        return real_build_opener(*handlers, transport)

    monkeypatch.setattr(urlrequest, "build_opener", wrapper)


# ---------- F-1：取图重定向逐跳落点复查 ----------


def test_public_landing_bytes_still_downloaded(monkeypatch) -> None:
    """公网落点：30x 照旧跟随、字节照旧返回（正常链路契约零变化）。"""
    jpeg = _jpeg_bytes()
    transport = _FakeTransport(
        {
            _ENTRY: (302, _PUBLIC_LANDING, b"moved"),
            _PUBLIC_LANDING: (200, "", jpeg),
        }
    )
    _install_guarded_transport(monkeypatch, transport)
    data = V._download_image_bytes(_ENTRY)
    assert data == jpeg
    assert transport.requested == [_ENTRY, _PUBLIC_LANDING]


@pytest.mark.parametrize(
    "landing",
    [
        "http://127.0.0.1:3001/status",  # 本机回环（SnowLuma 端口场景）
        "http://169.254.169.254/latest/meta-data/",  # 云元数据凭据面
        "http://10.1.2.3/internal.png",  # 私网段
        "http://192.168.1.1/gateway.png",  # 局域网网关
    ],
)
def test_intranet_redirect_landing_aborts_before_request(monkeypatch, landing) -> None:
    """F-1 主锁：30x 落点指内网——请求发出前即抛 ParseHttpError，内网零连接。"""
    transport = _FakeTransport({_ENTRY: (302, landing, b"moved")})
    _install_guarded_transport(monkeypatch, transport)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        V._download_image_bytes(_ENTRY)
    # 记账断言：只有入口这一跳「发出」，内网落点零请求、零字节回显。
    assert transport.requested == [_ENTRY]


def test_integer_ip_redirect_landing_rejected(monkeypatch) -> None:
    """十进制整型 IP 落点（2130706433=127.0.0.1）：F-04 归一化判定拦在建连前。"""
    transport = _FakeTransport({_ENTRY: (302, "http://2130706433/pic.png", b"moved")})
    _install_guarded_transport(monkeypatch, transport)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        V._download_image_bytes(_ENTRY)
    assert transport.requested == [_ENTRY]


def test_ftp_redirect_landing_rejected_by_guard(monkeypatch) -> None:
    """302→非法协议落点（链上可表达形态）：``ftp://`` 过得了 urllib 的协议门，
    过不了中央白名单——由本腿护栏在建连前抛 ``ParseHttpError``。

    为什么只有 ftp 一枚立在整链上（加固 SEAT-ATK-SSRF-LOCKS.md 追加三问 #3）：
    CPython ``HTTPRedirectHandler.http_error_302`` 自带协议门（scheme 不在
    ``http/https/ftp/''`` 即 ``HTTPError``，**先于**任何 handler 调用），故
    ``file://``/``gopher://``/``dict://`` 在本腿走不到中央咽喉——整链形态摘掉护栏
    也不会红（假绿），不立；三形态改在下方护栏 handler 单元上立。
    """
    landing = "ftp://127.0.0.1:1/pic.png"  # 字面量回环+端口 1：护栏被摘也只撞本机拒绝
    transport = _FakeTransport({_ENTRY: (302, landing, b"moved")})
    _install_guarded_transport(monkeypatch, transport)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        V._download_image_bytes(_ENTRY)
    assert transport.requested == [_ENTRY]


def test_prepare_drops_ftp_redirect_rejected_url(monkeypatch) -> None:
    """F-1×F-2 组合（非法协议落点版）：明确拒绝=丢图不回透，绝不滑进瞬时失败兜底。"""
    transport = _FakeTransport({_ENTRY: (302, "ftp://127.0.0.1:1/pic.png", b"moved")})
    _install_guarded_transport(monkeypatch, transport)
    assert V.prepare_vision_image_urls([_ENTRY]) == []
    assert transport.requested == [_ENTRY]


# ---------- 护栏 handler 本体：落点协议判定（整链表达不出的三形态在此立） ----------

_ILLEGAL_SCHEME_LANDINGS = [
    "file:///C:/Windows/win.ini",
    "gopher://8.8.8.8:11211/_probe",
    "dict://8.8.8.8:11211/x",
    "ftp://8.8.8.8:21/pic.png",
]


@pytest.mark.parametrize("landing", _ILLEGAL_SCHEME_LANDINGS)
def test_guard_handler_rejects_illegal_scheme_landing(landing: str) -> None:
    """逐跳护栏真身：落点协议不在中央白名单即拦——判据不只认内网地址。

    吃的是生产 handler ``_GuardedShortLinkRedirectHandler.redirect_request``（本腿
    opener 装的就是它），非自造判据。公网主机两枚（gopher/dict）只有协议白名单拦得住，
    ``file://`` 另有「缺少主机名」兜底；因此额外点名拒绝理由出自协议分支，免得靠内网
    判定蒙对。摘掉中央咽喉的协议判定（或整条咽喉）→ 本枚当场红。
    """
    request = urlrequest.Request(_ENTRY)
    handler = _GuardedShortLinkRedirectHandler()
    with pytest.raises(ParseHttpError, match="SSRF guard") as failure:
        handler.redirect_request(
            request, None, 302, "Found", email.message.Message(), landing
        )
    assert "只支持 http/https" in str(failure.value), (
        "必须出自协议白名单分支，不得靠内网判定蒙对"
    )


# ---------- F-2：咽喉拒绝 fail-closed 丢图，不回透原 URL ----------


def test_entry_rejection_raises_rejected_url_error() -> None:
    """入口咽喉明确拒绝：上抛 RejectedUrlError（不再吞成 None 混进兜底通道）。"""
    with pytest.raises(RejectedUrlError):
        V._download_image_bytes(_PRIVATE_ENTRY)


def test_prepare_drops_entry_rejected_url() -> None:
    """F-2 主锁：入口被拒的图直接丢弃——绝不进 prepared，provider 收不到原 URL。"""
    assert V.prepare_vision_image_urls([_PRIVATE_ENTRY]) == []


def test_prepare_drops_redirect_rejected_url(monkeypatch) -> None:
    """F-1×F-2 组合锁：入口公网、落点内网 → 丢图不回透，且内网零请求。"""
    transport = _FakeTransport({_ENTRY: (302, "http://127.0.0.1:3001/x.png", b"moved")})
    _install_guarded_transport(monkeypatch, transport)
    assert V.prepare_vision_image_urls([_ENTRY]) == []
    assert transport.requested == [_ENTRY]


def test_prepare_keeps_url_on_transient_failure(monkeypatch) -> None:
    """公网判定成立、瞬时下载失败（URLError）→ 保留原 URL 兜底（旧语义不变）。"""

    class _FlakyTransport(_FakeTransport):
        def http_open(self, req):
            self.requested.append(req.full_url)
            raise urlrequest.URLError("connection reset")

    transport = _FlakyTransport({})
    _install_guarded_transport(monkeypatch, transport)
    assert V.prepare_vision_image_urls([_ENTRY]) == [_ENTRY]
    assert transport.requested == [_ENTRY]


def test_prepare_converts_public_success_to_data_url(monkeypatch) -> None:
    """公网下载成功：bot 侧转 data URL（QQ 签名 URL 兜底主链路，契约零变化）。"""
    transport = _FakeTransport({_ENTRY: (200, "", _jpeg_bytes())})
    _install_guarded_transport(monkeypatch, transport)
    prepared = V.prepare_vision_image_urls([_ENTRY])
    assert prepared and prepared[0].startswith("data:image/jpeg;base64,")


def test_prepare_mixed_rejected_and_transient_only_drops_rejected(monkeypatch) -> None:
    """混排清单：被拒者丢弃、瞬时失败者保留——两分支互不串道。"""

    class _EntryFailTransport(_FakeTransport):
        def http_open(self, req):
            self.requested.append(req.full_url)
            raise urlrequest.URLError("connection reset")

    transport = _EntryFailTransport({})
    _install_guarded_transport(monkeypatch, transport)
    result = V.prepare_vision_image_urls([_PRIVATE_ENTRY, _ENTRY])
    assert result == [_ENTRY]


def test_describe_images_returns_empty_when_all_images_dropped() -> None:
    """F-2 连锁锁：全部图被护栏丢弃 → describe_images 返回空，provider 零调用。

    provider 用计数件而非「调用即抛」件：describe_images 的兜底 except 会把
    抛出的 AssertionError 吞成空串，令弱断言在注毒态下假绿（注毒自证发现的
    锁自身缺口，2026-09-27 本席 shot-2 实录）。
    """
    from types import SimpleNamespace

    class _RecordingProvider:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, messages, **kwargs):
            self.calls += 1
            return SimpleNamespace(text="绝不该被生成", provider="fake", model="fake", confidence=1.0)

    provider = _RecordingProvider()
    assert V.describe_images(provider, image_urls=[_PRIVATE_ENTRY]) == ""
    assert provider.calls == 0, "被拒图不得空跑 provider（哪怕只带文字）"
