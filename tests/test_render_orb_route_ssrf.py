"""卡片渲染回源 ``_orb_route`` 图片请求落点咽喉锁（攻击者复查 F-3 修复锁）。

出处：SEAT-ATK-SSRF.md F-3（中危）/ 调用点表 #25：卡 HTML 内任意 http(s)
``<img src>``（头像透传腿、第三方解析响应里的封面）此前由 bot 本机 **Chromium
直连**、零 SSRF 判定——盲 SSRF/端口探测面（响应变像素、回显难，但「连得上」
本身即探测）。ORB 代捞腿仅 sinaimg/weibocdn 后缀白名单内（内网字面不可能入名单），
故缺口在「非 ORB 名单的远程图直接 ``route.continue_()``」这一支。

修法（本席，写面严格限 ``_orb_route`` 一跳守卫）：对**任意 http(s)** 请求（W4
2026-10-01 起不再只挑 ``resource_type=="image"``），先过 ``scheme`` 门（非 http(s)
＝本地形态，交回浏览器 continue_），ORB 名单图走 python 侧代捞，其余一律先过
**中央唯一判据** ``check_download_url``——明确拒绝即 ``route.abort()``（模板
onerror 已有灰图兜底，行为兼容），放行才 ``continue_()``。ORB 名单支维持既有
「python 侧代捞」不变（不为它引入咽喉调用，避免测试里对 sinaimg 图床触发真 DNS）。

全离线纪律：沿用 ``test_render_image_cache`` 的假 page/route/opener（无真 Chromium、
无真网络）；内网/公网全用字面量 IP，``check_download_url`` 离线判定零 DNS。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.render import render_backends as rb

# 复用既有渲染测试替身（假 page 记账 route 注册；假 opener 记账回源），杜绝真网络。
from tests.test_render_image_cache import (
    _IMG_URL,
    _CountingOpener,
    _FakeOrbBrowser,
    _make_backend,
)

_INTERNAL = "http://127.0.0.1:9/probe.png"
_METADATA = "http://169.254.169.254/latest"
_PUBLIC = "http://93.184.216.34/cover.png"


class _FakeRoute:
    """Playwright ``Route`` 替身：记录 abort/continue_/fulfill 三态。"""

    def __init__(self, url: str, *, resource_type: str = "image") -> None:
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


def _install_orb_handler(monkeypatch: pytest.MonkeyPatch):
    """渲染一张含 ORB 名单图（触发 ``_orb_route`` 注册）的卡，取回该路由处理器。"""
    rb._image_bytes_cache_clear()
    opener = _CountingOpener({_IMG_URL: b"cover"})
    monkeypatch.setattr(rb, "_ORB_FETCH_OPENER", opener)
    browser = _FakeOrbBrowser()
    backend = _make_backend(browser)
    payload = {
        "html": f"<div class='card'><img src='{_IMG_URL}'></div>",
        "viewport": {"width": 10, "height": 10},
        "wait_ms": 0,
    }
    assert backend.render_card(dict(payload)) == b"png-bytes"
    handlers = [h for page in browser.pages for h in page.route_handlers]
    assert handlers, "ORB 名单卡应注册 _orb_route"
    return handlers[0], opener


@pytest.mark.parametrize("bad_url", [_INTERNAL, _METADATA])
def test_orb_route_aborts_intranet_image_before_chromium(
    monkeypatch: pytest.MonkeyPatch, bad_url: str
) -> None:
    """F-3 主锁：非名单内网图→发请求前即 route.abort()，Chromium 绝不直连内网。

    RED（修复前）：``_orb_route`` 对非 ORB 名单图无脑 ``continue_()`` →
    continued=True、aborted=False → 本锁红。
    """
    handler, opener = _install_orb_handler(monkeypatch)
    route = _FakeRoute(bad_url)
    handler(route)
    assert route.aborted is True
    assert route.continued is False
    # 内网图被咽喉拒后直接 abort：既不放行直连，也不改走 python 代捞（零回源）。
    assert opener.calls == []


def test_orb_route_continues_public_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """正向锁：公网非名单图咽喉放行→continue_()（行为与修复前一致，不过度拦）。"""
    handler, opener = _install_orb_handler(monkeypatch)
    route = _FakeRoute(_PUBLIC)
    handler(route)
    assert route.continued is True and route.aborted is False
    # 非名单公网图交回浏览器自取，不进 ORB 代捞（零回源）。
    assert opener.calls == []


def test_orb_route_orb_prone_still_fetched_via_proxy_leg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """契约锁：ORB 名单图仍走 python 代捞（本席未给该支加咽喉调用→无 sinaimg DNS）。"""
    handler, opener = _install_orb_handler(monkeypatch)
    route = _FakeRoute(_IMG_URL)
    handler(route)
    assert route.fulfilled is not None
    assert route.fulfilled["body"] == b"cover"
    assert opener.calls == [_IMG_URL]


def test_orb_route_non_image_public_still_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    """正向锁：非图片但公网可达的请求（外链 CSS/JS）仍 continue_()，不过度拦。"""
    handler, opener = _install_orb_handler(monkeypatch)
    route = _FakeRoute(_PUBLIC, resource_type="script")
    handler(route)
    assert route.continued is True and route.aborted is False
    assert opener.calls == []


def test_orb_route_non_image_intranet_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    """W4 扩面锁：``resource_type!="image"`` 不再是免检通道。

    旧实现首行「非 image 一律 continue_()」，而注册判据与 docstring 都自称罩住
    「任意远程资源」⇒ 卡里一枚 ``<script src='http://127.0.0.1:3001/x.js'>``
    （或外链 CSS/XHR）由本机 Chromium 盲连，F-3 判据根本不执行——端口探测面
    从「图」这一形收窄出来的口子，实际等于没关。RED（扩面前）：本锁红在
    ``continued is True``。口径既已改，锁与生产件同批改（台账 #68★）。
    """
    handler, opener = _install_orb_handler(monkeypatch)
    for resource_type in ("script", "stylesheet", "xhr", "document", "font"):
        route = _FakeRoute(_INTERNAL, resource_type=resource_type)
        handler(route)
        assert route.aborted is True, f"{resource_type} 腿内网请求必须发不出"
        assert route.continued is False
    assert opener.calls == []  # 内网请求既不放行也不代捞


@pytest.mark.parametrize(
    ("url", "resource_type"),
    [
        ("data:image/png;base64,AAAA", "image"),
        ("blob:https://example.test/6f2f1c", "image"),
        ("about:blank", "document"),
        ("file:///C:/Windows/win.ini", "image"),
    ],
)
def test_orb_route_local_schemes_never_aborted(
    monkeypatch: pytest.MonkeyPatch, url: str, resource_type: str
) -> None:
    """scheme 门前置锁：非 http(s) 形态交回浏览器，绝不被咽喉按「协议非法」误杀。

    没有这道显式判定，扩面后 ``data:``/``blob:`` 本地图会进 ``check_download_url``
    ⇒ 非 http/https ⇒ RejectedUrlError ⇒ abort ⇒ 卡面内联图全灰（渲染契约回归面）。
    """
    handler, opener = _install_orb_handler(monkeypatch)
    route = _FakeRoute(url, resource_type=resource_type)
    handler(route)
    assert route.continued is True and route.aborted is False
    assert opener.calls == []
