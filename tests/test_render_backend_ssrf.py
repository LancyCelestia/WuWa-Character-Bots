"""渲染器外链图 SSRF 闸「注册面」行为锁（SEAT-ATK-RENDER M-1 收口锁）。

背景：``_orb_route`` 携带 F-3 闸（非 ORB 名单的 http(s) 图在建连前先过
中央咽喉 ``check_download_url``），但其注册条件历史上只判「HTML 是否含
ORB 名单（sinaimg/weibocdn）图」——不含新浪图的卡（多数）根本不注册
拦截器，判据与拦截器同生同死，外链图由本机 Chromium 盲连。
修法（S-FIX-RENDER-SSRF 2026-09-28）：注册判据改为「HTML 含任何
http(s) 资源引用」（复用 ``_HTML_URL_RE`` 单一形态真身）；无外链则仍
不注册，保留零处理器快路径。本文件锁五件事：

①含非 sinaimg 外链图的 HTML 也挂闸（闸真生效＝内网图在建连前被拒）；
②闸拦 loopback/私网/链路本地/元数据地址（假 page 下 aborted 即
  「请求不发出」，且绝不改走 python 代捞——opener 零调用）；
③无任何 http(s) 外链的 HTML 注册数＝0（零开销快路径不回归）；
④W4 扩形态：只有 ``href=`` 外链 CSS/JS 的 HTML 同样挂闸（旧尺只认 ``src=``/
  ``url(``，外链 CSS 是漏网的一形）；
⑤W4 扩面：闸本体不再免检非 image 请求（``_orb_route`` 的口径见
  ``test_render_orb_route_ssrf``，那里改的锁与生产件同批）。

全离线纪律：假 page/route/opener（复用 ``test_render_image_cache``
替身），公网/内网全用字面量 IP 或黑名单主机名——``check_download_url``
对字面量 IP 与 ``localhost`` 系均不做 DNS，零真实网络。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.render import render_backends as rb

# 复用既有渲染测试替身（假 page 记账 route 注册；假 opener 记账回源），杜绝真网络。
from tests.test_render_image_cache import (
    _IMG_URL,
    _CountingOpener,
    _FakeOrbBrowser,
    _make_backend,
)

# 非 ORB 名单的公网字面量 IP（真咽喉离线放行，不触发 DNS）。
_PUBLIC = "http://93.184.216.34/cover.png"
_LOOPBACK = "http://127.0.0.1:9/probe.png"
_PRIVATE = "http://10.0.0.1/x.png"
_LINKLOCAL_METADATA = "http://169.254.169.254/latest"
_LOCALHOST = "http://localhost:8080/x.png"
_IPV6_LOOPBACK = "http://[::1]/x.png"


class _FakeRoute:
    """Playwright ``Route`` 替身：记录 abort/continue_/fulfill 三态。"""

    def __init__(self, url: str, *, resource_type: str = "image") -> None:
        from types import SimpleNamespace

        self.request = SimpleNamespace(resource_type=resource_type, url=url)
        self.aborted = False
        self.continued = False
        self.fulfilled: dict | None = None

    def continue_(self) -> None:
        self.continued = True

    def abort(self, *_args: object) -> None:
        self.aborted = True

    def fulfill(self, **kwargs: object) -> None:
        self.fulfilled = kwargs


def _render_and_get_handlers(
    monkeypatch: pytest.MonkeyPatch, html: str
) -> tuple[list, _CountingOpener, _FakeOrbBrowser]:
    """走一次 ``render_card``（假浏览器），回传该页注册的全部路由处理器。"""
    rb._image_bytes_cache_clear()
    opener = _CountingOpener({_IMG_URL: b"cover"})
    monkeypatch.setattr(rb, "_ORB_FETCH_OPENER", opener)
    browser = _FakeOrbBrowser()
    backend = _make_backend(browser)
    payload = {
        "html": html,
        "viewport": {"width": 10, "height": 10},
        "wait_ms": 0,
    }
    assert backend.render_card(dict(payload)) == b"png-bytes"
    handlers = [h for page in browser.pages for h in page.route_handlers]
    return handlers, opener, browser


def test_non_orb_remote_image_html_still_registers_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """锁①（M-1 主锁）：HTML 只含非 sinaimg 外链图也必须挂闸。

    RED（修复前）：注册判据 ``_html_mentions_orb_prone_image`` 对纯公网
    外链卡返回 False → handlers 为空 → 本锁红。挂闸证明＝向内网图请求
    喂处理器，必须 abort（判据在场且生效），不是无人接管。
    """
    handlers, opener, _ = _render_and_get_handlers(
        monkeypatch, f"<div class='card'><img src='{_PUBLIC}'></div>"
    )
    assert handlers, "含非 sinaimg 外链图的卡必须注册 _orb_route（M-1 缺口）"
    route = _FakeRoute(_LOOPBACK)
    handlers[0](route)
    assert route.aborted is True
    assert route.continued is False
    assert opener.calls == []  # 被拒的内网图绝不改走 python 代捞


@pytest.mark.parametrize(
    "bad_url",
    [_LOOPBACK, _PRIVATE, _LINKLOCAL_METADATA, _LOCALHOST, _IPV6_LOOPBACK],
    ids=["loopback-ip", "private-10", "linklocal-metadata", "localhost", "ipv6-loopback"],
)
def test_gate_rejects_intranet_addresses_without_connection(
    monkeypatch: pytest.MonkeyPatch, bad_url: str
) -> None:
    """锁②：loopback/私网/链路本地/元数据/localhost 一律 abort，请求不发出。

    判据真身＝中央咽喉 ``check_download_url``（字面量 IP 离线判定、
    localhost 系走主机名黑名单，均零 DNS）；「不发请求」在假 page 形态
    下即 aborted 且非 continued，且 opener 计数恒空（也不代捞）。
    """
    handlers, opener, _ = _render_and_get_handlers(
        monkeypatch, f"<div class='card'><img src='{_PUBLIC}'></div>"
    )
    assert handlers
    route = _FakeRoute(bad_url)
    handlers[0](route)
    assert route.aborted is True
    assert route.continued is False
    assert opener.calls == []


def test_gate_continues_public_non_orb_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正向锁：公网非名单图咽喉放行→continue_()，不扩面过度拦截。"""
    handlers, opener, _ = _render_and_get_handlers(
        monkeypatch, f"<div class='card'><img src='{_PUBLIC}'></div>"
    )
    assert handlers
    route = _FakeRoute(_PUBLIC)
    handlers[0](route)
    assert route.continued is True and route.aborted is False
    assert opener.calls == []  # 非 ORB 名单图仍由浏览器自取，不代捞


def test_no_remote_resource_html_registers_no_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """锁③（零开销快路径）：无任何 http(s) 外链的 HTML 注册数＝0。

    含 data: URI 与相对路径资源——两者都不构成「远程资源引用」
    （``_HTML_URL_RE`` 只认 https?:// 形态），挂闸只会给纯本地图加
    每请求 Python 处理器开销，属渲染延迟契约回归面。
    """
    html = (
        "<div class='card'>"
        "<img src='data:image/png;base64,AAAA'>"
        "<img src='assets/local.png'>"
        "<style>.x{background:url('img/bg.png')}</style>"
        "纯文本，无外链"
        "</div>"
    )
    handlers, opener, _ = _render_and_get_handlers(monkeypatch, html)
    assert handlers == []
    assert opener.calls == []


def test_href_only_external_stylesheet_registers_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """锁④（W4 扩形态）：只有 ``href=`` 外链（CSS/JS）的卡也必须挂闸。

    RED（修复前）：``_HTML_URL_RE`` 只认 ``src=`` / ``url(`` 两形 ⇒ 一枚
    ``<link href="http://127.0.0.1:9/x.css">`` 让注册判据返回 False、拦截器根本
    不在场，Chromium 直连内网端口（探测面从「图」这一形漏出去）。挂闸证明＝
    喂 stylesheet 形态的内网请求，处理器必须当场 abort。
    """
    handlers, opener, _ = _render_and_get_handlers(
        monkeypatch,
        "<div class='card'><link rel='stylesheet' href='http://93.184.216.34/a.css'></div>",
    )
    assert handlers, "href= 外链同样是远程资源引用，注册判据不许只认 src="
    route = _FakeRoute(_LOOPBACK, resource_type="stylesheet")
    handlers[0](route)
    assert route.aborted is True and route.continued is False
    assert opener.calls == []


def test_orb_prone_html_still_registers_superset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回归锁：旧判据命中的 ORB 卡在新判据下仍挂闸（新集合 ⊇ 旧集合）。

    ORB 名单图走既有 python 代捞支（不引入咽喉调用），行为逐字节不变。
    """
    handlers, opener, _ = _render_and_get_handlers(
        monkeypatch, f"<div class='card'><img src='{_IMG_URL}'></div>"
    )
    assert handlers
    route = _FakeRoute(_IMG_URL)
    handlers[0](route)
    assert route.fulfilled is not None
    assert route.fulfilled["body"] == b"cover"
    assert opener.calls == [_IMG_URL]


def test_rejection_verdicts_come_from_central_throat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单源锁：闸的拒绝判据必须现取中央咽喉，不得复制第二套 SSRF 正则。

    手法：把 ``downloader.check_download_url`` 换成记账替身（放行/拒绝
    各一发）。①替身抛 ``RejectedUrlError`` → 处理器必 abort，且替身
    被以该 URL 点名调用（证明判据外置）；②替身放行 → continue_。
    若未来有人在 render_backends 里自拼内网网段表，咽喉将不再被咨询，
    本锁的「替身被调用」断言当场红。
    """
    from plugins.bot_unified_runtime.domains.files.sources import downloader

    consulted: list[str] = []

    class _Reject(RuntimeError):
        pass

    def fake_check(url: str) -> None:
        consulted.append(url)
        if "denied" in url:
            raise downloader.RejectedUrlError("替身拒绝")

    monkeypatch.setattr(downloader, "check_download_url", fake_check)
    handlers, opener, _ = _render_and_get_handlers(
        monkeypatch, f"<div class='card'><img src='{_PUBLIC}'></div>"
    )
    assert handlers

    denied = _FakeRoute("http://denied.example.invalid/x.png")
    handlers[0](denied)
    assert denied.aborted is True and denied.continued is False
    assert consulted == ["http://denied.example.invalid/x.png"]

    allowed = _FakeRoute(_PUBLIC)
    handlers[0](allowed)
    assert allowed.continued is True and allowed.aborted is False
    assert consulted == ["http://denied.example.invalid/x.png", _PUBLIC]
    assert opener.calls == []  # 全程无真实回源
