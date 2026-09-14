"""短链 30x 逐跳 SSRF 校验回归（安全审查 F-05 修复，2026-09-14）。

背景（审查 F-05，Critical）：``resolve_short_link`` 旧版用 urllib 默认
opener 自动跟随 30x，逐跳落点无任何校验——短链 30x 指向内网/云元数据
地址时，请求已发进内网才返回。修复后每跳落点先过 ssrf_guard
``check_fetch_landing``（F-04 新语义「解析失败=拒绝」），命中即抛
ParseHttpError（消息带「SSRF guard」可判别标记）中止，请求绝不发向
内网；跳数上限显式收紧到 5（urllib 默认 10）。

全离线：传输层用假 HTTPHandler 记账每个「真实会发出」的请求，
字面量 IP 落点走护栏离线判定（零 DNS）；禁真实网络。
"""

from __future__ import annotations

import email.message
import io
from urllib import request as urlrequest
from urllib.response import addinfourl

import pytest

from plugins.bot_unified_runtime.sources.parsers import http_util
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError

_SHORT_LINK = "http://s.example.com/abc123"
# 字面量公网 IP（93.184.216.34）：护栏按字面量离线判定放行，零 DNS。
_PUBLIC_IP_LANDING = "http://93.184.216.34/final?video=1"


class _FakeTransport(urlrequest.HTTPHandler):
    """假 HTTP 传输层：按路由表应答 30x/200，并记账每个将真实发出的请求。

    必须继承 HTTPHandler（而非 BaseHandler）：build_opener 看到传入实例
    属于 HTTPHandler 族才会跳过默认真实 HTTPHandler，否则默认处理器
    仍会抢先发起真实网络请求。内网落点故意不建路由——真发出去会
    KeyError，本身就是一层断言。
    """

    def __init__(self, routes: dict[str, tuple[int, str, str]]):
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
        response = addinfourl(io.BytesIO(body.encode("utf-8")), headers, url, status)
        response.msg = "fake"
        return response


def _install_opener(monkeypatch: pytest.MonkeyPatch, transport: _FakeTransport) -> None:
    """替换 _build_opener：保留 resolve_short_link 真实传入的守卫 handler，
    只把传输层换成假件——逐跳校验逻辑本身不被 mock。"""

    def fake_build_opener(proxy="", *, verify_ssl=True, extra_handlers=None):
        return urlrequest.build_opener(*(extra_handlers or []), transport)

    monkeypatch.setattr(http_util, "_build_opener", fake_build_opener)


# ---------- ① 短链 → 公网落点：正常解析（契约零变化） ----------


def test_short_link_to_public_landing_resolves(monkeypatch):
    transport = _FakeTransport(
        {
            _SHORT_LINK: (302, _PUBLIC_IP_LANDING, "moved"),
            _PUBLIC_IP_LANDING: (200, "", "final-body"),
        }
    )
    _install_opener(monkeypatch, transport)
    final = http_util.resolve_short_link(_SHORT_LINK)
    assert final == _PUBLIC_IP_LANDING, "公网落点照旧返回最终 URL（契约不变）"
    # 30x 被真实跟随：短链一跳 + 公网落点一跳。
    assert transport.requested == [_SHORT_LINK, _PUBLIC_IP_LANDING]


def test_short_link_chain_of_two_public_hops_resolves(monkeypatch):
    hop1 = "http://93.184.216.34/hop1"
    transport = _FakeTransport(
        {
            _SHORT_LINK: (302, hop1, "moved"),
            hop1: (302, _PUBLIC_IP_LANDING, "moved"),
            _PUBLIC_IP_LANDING: (200, "", "final-body"),
        }
    )
    _install_opener(monkeypatch, transport)
    assert http_util.resolve_short_link(_SHORT_LINK) == _PUBLIC_IP_LANDING
    assert transport.requested == [_SHORT_LINK, hop1, _PUBLIC_IP_LANDING]


# ---------- ② 短链 → 内网/元数据落点：中止且不发内网请求 ----------


@pytest.mark.parametrize(
    "landing",
    [
        "http://127.0.0.1:3001/status",  # 本机回环（NapCat 端口场景）
        "http://169.254.169.254/latest/meta-data/",  # 云元数据凭据面
        "http://10.1.2.3/router",  # 私网段
        "http://192.168.1.1/admin",  # 局域网网关
    ],
)
def test_short_link_to_intranet_landing_aborts_before_request(monkeypatch, landing):
    transport = _FakeTransport({_SHORT_LINK: (302, landing, "moved")})
    _install_opener(monkeypatch, transport)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        http_util.resolve_short_link(_SHORT_LINK)
    # fake 计数器断言：只有短链本体这一跳「发出」，内网落点零请求。
    assert transport.requested == [_SHORT_LINK]


# ---------- ③ 跳数超限：按既有错误路径抛 ----------


def test_short_link_hop_limit_raises_via_error_path(monkeypatch):
    # 12 跳无限 30x 链（全公网字面量 IP，护栏逐跳放行、零 DNS）：
    # 超限必须走既有 HTTPError→ParseHttpError 错误路径，且请求数被
    # 显式上限（F-05：≤5 跳，urllib 默认 10）钳住。
    routes: dict[str, tuple[int, str, str]] = {}
    current = _SHORT_LINK
    for i in range(12):
        nxt = f"http://93.184.216.34/hop{i}"
        routes[current] = (302, nxt, "moved")
        current = nxt
    transport = _FakeTransport(routes)
    _install_opener(monkeypatch, transport)
    with pytest.raises(ParseHttpError):
        http_util.resolve_short_link(_SHORT_LINK)
    assert len(transport.requested) < 12, "跳数超限必须中止，不允许跟完整条链"
    # 1 次入口 + 至多 5 次跳转，第 6 跳响应处理时 urllib 抛 HTTPError。
    assert len(transport.requested) <= 7


# ---------- ④ 十进制整型 IP 落点：拒绝（F-05 × F-04 组合） ----------


def test_short_link_to_decimal_integer_ip_landing_rejected(monkeypatch):
    # 2130706433 = 127.0.0.1（inet_aton 语义）：常见客户端会直接按回环
    # 连接。逐跳校验必须经 F-04 归一化判定拦在请求发出之前。
    transport = _FakeTransport({_SHORT_LINK: (302, "http://2130706433/admin", "moved")})
    _install_opener(monkeypatch, transport)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        http_util.resolve_short_link(_SHORT_LINK)
    assert transport.requested == [_SHORT_LINK]
