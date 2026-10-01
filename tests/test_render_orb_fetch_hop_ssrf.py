"""渲染 ORB 代捞腿逐跳 SSRF 复查锁（INCIDENT-20260930 第五节 · 缺口①）。

背景：``render_backends._ORB_FETCH_OPENER`` 是 ``build_opener(ProxyHandler({}))``
——Python 侧替 Chromium 代捞 sinaimg/weibocdn 图的通道，**零咽喉**且 urllib
默认自动跟随 30x。``_orb_route`` 的 F-3 闸只罩住「非 ORB 名单」那一支
（名单内直接交给代捞腿），于是图床回一个 30x 就能把 bot 的出站请求送进
内网/云元数据：卡面上看不见字节，但「连得上」本身就是探测面，且字节还会
经 ``route.fulfill`` 变成像素回显在群卡上。

修法：给这条腿装**链上唯一**的逐跳护栏形态
``link_parse.parsers.http_util._GuardedShortLinkRedirectHandler``（每一跳落点在
建连前先过 ``ssrf_guard.check_fetch_landing``，判据仍是中央
``downloader.check_download_url``——本件不造第二套 URL 判据）。缺省直连
（``ProxyHandler({})``，新浪图床对代理出口 IP 回 403 的实测结论）与
「入口域名不触 DNS」两条既有口径一律不动。

全离线纪律：``urllib.request.build_opener`` 包一层注入假传输件（http/https
各一枚，按路由表应答 30x/200 并记账每跳是否真的发出）；生产 opener 装配
本体（护栏 handler）不被 mock——摘掉护栏，落点拒绝锁必红。入口用名单域名
（护栏只看落点、不碰入口 ⇒ 不触 DNS），落点全用字面量 IP ⇒ 零真实网络。
"""

from __future__ import annotations

import email.message
import io
import urllib.request as urlrequest
from urllib.response import addinfourl

import pytest

from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    _GuardedShortLinkRedirectHandler,
)
from plugins.bot_unified_runtime.domains.render import render_backends as rb

# 入口用 ORB 名单域名（护栏只看落点、不碰入口 ⇒ 永不触 DNS）；
# 落点全用字面量 IP（中央咽喉离线可判，零 DNS）。
_ORB_ENTRY = "https://wx1.sinaimg.cn/large/cover.jpg"
_PUBLIC_LANDING = "http://93.184.216.34/final.jpg"
_LOOPBACK_LANDING = "http://127.0.0.1:3001/status"
_METADATA_LANDING = "http://169.254.169.254/latest/meta-data/"
_PRIVATE_LANDING = "http://10.1.2.3/x.png"


def _respond(url: str):
    """按路由表应答，并记账「这一跳真的发出去了」（http/https 两腿共用同一本账）。"""
    _FakeTransportHTTP.requested.append(url)
    status, location, body = _FakeTransportHTTP.routes[url]
    headers = email.message.Message()
    if location:
        headers["Location"] = location
    response = addinfourl(io.BytesIO(body), headers, url, status)
    response.msg = "fake"
    return response


class _FakeTransportHTTP(urlrequest.HTTPHandler):
    """假传输层（继承 HTTPHandler 才会顶掉默认真实处理器；内网落点故意不建路由）。"""

    routes: dict[str, tuple[int, str, bytes]] = {}
    requested: list[str] = []

    def http_open(self, req):
        return _respond(req.full_url)


class _FakeTransportHTTPS(urlrequest.HTTPSHandler):
    def https_open(self, req):
        return _respond(req.full_url)


def _install_transport(
    monkeypatch: pytest.MonkeyPatch, routes: dict[str, tuple[int, str, bytes]]
) -> list[str]:
    """包装 ``build_opener``：生产 handler 原样流进 opener，只追加假传输层。"""
    _FakeTransportHTTP.routes = routes
    _FakeTransportHTTPS.routes = routes
    _FakeTransportHTTP.requested = []
    _FakeTransportHTTPS.requested = []
    real_build_opener = urlrequest.build_opener

    def wrapper(*handlers):
        return real_build_opener(*handlers, _FakeTransportHTTP(), _FakeTransportHTTPS())

    monkeypatch.setattr(urlrequest, "build_opener", wrapper)
    # 用生产工厂重建代捞 opener（护栏 handler 的装配本体因此被真实执行）。
    monkeypatch.setattr(rb, "_ORB_FETCH_OPENER", rb._build_orb_fetch_opener())
    rb._image_bytes_cache_clear()
    return _FakeTransportHTTP.requested


# --------------------------------------------------------------------------- #
# 装配真身：护栏 handler 必须在场，且缺省直连不许被顺手改掉
# --------------------------------------------------------------------------- #
def test_orb_opener_carries_the_central_hop_guard() -> None:
    """主锁：生产 ``_ORB_FETCH_OPENER`` 装有逐跳护栏 handler。

    RED（修复前）：``build_opener(ProxyHandler({}))`` 里只有代理件，重定向由
    urllib 默认 handler 盲跟 ⇒ 本锁红。
    """
    handlers = rb._ORB_FETCH_OPENER.handlers
    assert any(
        isinstance(h, _GuardedShortLinkRedirectHandler) for h in handlers
    ), "ORB 代捞腿必须复用链上唯一的逐跳护栏（禁第二套判据）"


def test_orb_opener_stays_forced_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归锁：环境里有代理（本机全链拴 Clash）时，代捞腿仍旧**不经代理**。

    口径要认清：空 proxies 的 ``ProxyHandler({})`` 本身不会进 chain（它没有任何
    ``*_open`` 方法可注册），它的作用是把 ``build_opener`` 的缺省代理件**顶掉**
    ⇒ chain 里不存在带有效 proxies 的代理件＝强制直连。新浪 WAF 对代理出口 IP
    回 403 的实测结论就靠这一点成立；装进逐跳护栏时不许顺手把它换成缺省代理件。
    """
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    assert urlrequest.getproxies(), "前置条件：环境里确实有代理，否则本锁无意义"

    for opener in (rb._ORB_FETCH_OPENER, rb._build_orb_fetch_opener()):
        assert not any(
            isinstance(h, urlrequest.ProxyHandler) and h.proxies
            for h in opener.handlers
        ), "代捞腿被装了有效代理件＝直连口径被破"


# --------------------------------------------------------------------------- #
# 行为：内网落点拦在建连前，公网落点照旧跟随
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "landing",
    [_LOOPBACK_LANDING, _METADATA_LANDING, _PRIVATE_LANDING],
    ids=["loopback-snowluma", "cloud-metadata", "private-10"],
)
def test_intranet_redirect_landing_never_reaches_the_socket(
    landing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """30x 落点指内网 ⇒ 第二跳请求绝不发出，取字节失败交给 route.abort。"""
    requested = _install_transport(monkeypatch, {_ORB_ENTRY: (302, landing, b"moved")})

    assert rb._fetch_image_bytes(_ORB_ENTRY) is None
    assert requested == [_ORB_ENTRY], f"内网落点被真的连了：{requested}"


def test_integer_ip_redirect_landing_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """整型 IP 落点（2130706433=127.0.0.1）：F-04 归一化判定同样拦在建连前。"""
    requested = _install_transport(
        monkeypatch, {_ORB_ENTRY: (302, "http://2130706433/x.png", b"moved")}
    )

    assert rb._fetch_image_bytes(_ORB_ENTRY) is None
    assert requested == [_ORB_ENTRY]


def test_too_many_hops_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """跳数上限（护栏 ``max_redirections=5``）：不许无限跟下去把渲染线程挂死。"""
    hop_urls = [f"http://93.184.216.3{index}/h{index}.jpg" for index in range(9)]
    routes = {
        _ORB_ENTRY: (302, hop_urls[0], b"moved"),
        **{
            hop_urls[i]: (302, hop_urls[i + 1], b"moved")
            for i in range(len(hop_urls) - 1)
        },
    }
    requested = _install_transport(monkeypatch, routes)

    assert rb._fetch_image_bytes(_ORB_ENTRY) is None
    # 入口 1 跳 + 跟随至上限即停：远小于「无限跟」，且全程都是公网落点。
    assert len(requested) <= 6, requested


def test_public_redirect_landing_still_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """正向锁：公网落点照旧跟随、字节照旧返回（正常链路契约零变化）。"""
    requested = _install_transport(
        monkeypatch,
        {_ORB_ENTRY: (302, _PUBLIC_LANDING, b"moved"), _PUBLIC_LANDING: (200, "", b"cover")},
    )

    assert rb._fetch_image_bytes(_ORB_ENTRY) == (b"cover", "image/jpeg")
    assert requested == [_ORB_ENTRY, _PUBLIC_LANDING]


def test_direct_200_still_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """无重定向（绝大多数真实图床命中）：行为与修复前逐字节一致。"""
    requested = _install_transport(monkeypatch, {_ORB_ENTRY: (200, "", b"cover")})

    assert rb._fetch_image_bytes(_ORB_ENTRY) == (b"cover", "image/jpeg")
    assert requested == [_ORB_ENTRY]


def test_failure_contract_unchanged_when_guard_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    """契约锁：护栏拒绝仍旧走「返回 None → route.abort → 模板 onerror 灰图」旧降级，
    不新增异常通路（渲染失败绝不让卡片整体抛错）。"""
    _install_transport(monkeypatch, {_ORB_ENTRY: (302, _LOOPBACK_LANDING, b"moved")})
    try:
        assert rb._fetch_image_bytes(_ORB_ENTRY) is None
    except Exception as exc:  # pragma: no cover - 修复若改抛错，这里当场红
        pytest.fail(f"护栏拒绝不得外抛（渲染降级契约破坏）：{exc!r}")


def test_cached_bytes_skip_the_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """LRU 契约零变化（审查 L-07）：命中缓存不建连，护栏也无需再看第二眼。"""
    requested = _install_transport(monkeypatch, {_ORB_ENTRY: (200, "", b"cover")})

    assert rb._fetch_image_bytes(_ORB_ENTRY) == (b"cover", "image/jpeg")
    assert rb._fetch_image_bytes(_ORB_ENTRY) == (b"cover", "image/jpeg")
    assert requested == [_ORB_ENTRY]
