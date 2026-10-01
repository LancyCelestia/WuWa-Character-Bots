"""吃什么封面取图逐跳 SSRF 复查锁（INCIDENT-20260930 第五节 · 缺口②）。

背景（盲 SSRF）：``eat._accepts`` 先 ``urllib.request.urlopen(req)``、**之后**才
``resp.geturl()`` + ``check_download_url(final_url)``。urlopen 默认 opener 自动
跟随 30x，所以「公网候选 → 302 → 127.0.0.1:3001 / 169.254.169.254」这条链上
内网请求**早已发出**，事后复查只拦得住字节落盘，拦不住连接本身（SSRF +
端口探测面；两次解析之间还有 DNS rebinding 窗口）。

修法（同 ``vision_describe`` / ``notes`` 已验证的正确形）：取字节只走
``_guarded_image_opener()``——
①复用链上唯一的逐跳护栏 ``http_util._GuardedShortLinkRedirectHandler``
  （每一跳落点在**建连之前**过 ``ssrf_guard.check_fetch_landing``）；
②装 ``downloader.build_pinning_handlers()`` 的连接层钉定件（治 rebinding：
  判定与连接共用同一次解析，缺省 ``ProxyHandler`` 与 TLS 校验一律不动）；
③入口 ``check_download_url`` 与「落点 ``geturl()`` 复查」都保留：前者 fail-fast
  给 refusal 语义，后者是纵深（假传输件也照拦），绝不因为加了护栏就摘掉旧闸。

判据仍是中央咽喉，本件不复制第二套网段表。

全离线纪律：搜索腿（固定 ``cn.bing.com``，非用户可控）仍旧打桩
``urllib.request.urlopen``；候选腿用真生产 opener + ``build_opener`` 注入的假
传输件（``handler_order`` 调低到钉定件之前，保证测试不建真 socket），落点全用
字面量 IP ⇒ 零真实网络、零 DNS。
"""

from __future__ import annotations

import email.message
import io
import os
import urllib.request as urlrequest
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote_plus
from urllib.response import addinfourl

import pytest

from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    _PinningHTTPHandler,
)
from plugins.bot_unified_runtime.domains.food.capabilities import eat as E
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    _GuardedShortLinkRedirectHandler,
)

DISH = "宫保鸡丁"
_SEARCH = f"https://cn.bing.com/images/search?q={quote_plus(f'{DISH} 菜品 实拍')}&first=1&count=8"
_ENTRY = "http://93.184.216.34/candidate.png"
_PUBLIC_LANDING = "http://93.184.216.35/final.png"
_LOOPBACK_LANDING = "http://127.0.0.1:3001/status"
_METADATA_LANDING = "http://169.254.169.254/latest/meta-data/"


def _png_bytes(size: tuple[int, int] = (640, 480)) -> bytes:
    from PIL import Image

    noise = Image.frombytes("L", size, os.urandom(size[0] * size[1]))
    buffer = io.BytesIO()
    noise.save(buffer, format="PNG")
    return buffer.getvalue()


def _bing_page(urls: list[str]) -> bytes:
    return "".join(f'murl&quot;:&quot;{u}&quot;' for u in urls).encode("utf-8")


def _respond(url: str):
    """按路由表应答并记账「这一跳真的发出去了」。"""
    _FakeTransportHTTP.requested.append(url)
    status, location, body = _FakeTransportHTTP.routes[url]
    headers = email.message.Message()
    if location:
        headers["Location"] = location
    response = addinfourl(io.BytesIO(body), headers, url, status)
    response.msg = "fake"
    return response


class _FakeTransportHTTP(urlrequest.HTTPHandler):
    """假传输层：按路由表应答（handler_order 调低 ⇒ 抢先于钉定件，绝不建真 socket）。"""

    handler_order = 300
    routes: ClassVar[dict[str, tuple[int, str, bytes]]] = {}
    requested: ClassVar[list[str]] = []

    def http_open(self, req):
        return _respond(req.full_url)


class _FakeTransportHTTPS(urlrequest.HTTPSHandler):
    handler_order = 300

    def https_open(self, req):
        return _respond(req.full_url)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    routes: dict[str, tuple[int, str, bytes]],
) -> list[str]:
    """搜索腿打桩 urlopen、候选腿保留真生产 opener（只换传输件）。"""
    _FakeTransportHTTP.routes = routes
    _FakeTransportHTTPS.routes = routes
    _FakeTransportHTTP.requested = []
    _FakeTransportHTTPS.requested = []
    real_build_opener = urlrequest.build_opener

    def wrapper(*handlers):
        return real_build_opener(*handlers, _FakeTransportHTTP(), _FakeTransportHTTPS())

    monkeypatch.setattr(urlrequest, "build_opener", wrapper)
    monkeypatch.setattr(
        urlrequest,
        "urlopen",
        lambda req, *args, **kwargs: _respond(str(getattr(req, "full_url", req))),
    )
    return _FakeTransportHTTP.requested


# --------------------------------------------------------------------------- #
# 装配真身：护栏 + 钉定两件都得在场上
# --------------------------------------------------------------------------- #
def test_eat_opener_carries_hop_guard_and_connect_pin() -> None:
    opener = E._guarded_image_opener()
    assert any(
        isinstance(h, _GuardedShortLinkRedirectHandler) for h in opener.handlers
    ), "必须复用链上唯一的逐跳护栏（禁第二套判据）"
    assert any(isinstance(h, _PinningHTTPHandler) for h in opener.handlers), (
        "取图腿要装连接层钉定件（DNS rebinding 由同一次解析判定并连接）"
    )


# --------------------------------------------------------------------------- #
# 主行为：内网落点建连前即拒
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "landing",
    [_LOOPBACK_LANDING, _METADATA_LANDING],
    ids=["loopback-snowluma", "cloud-metadata"],
)
def test_intranet_redirect_landing_is_never_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, landing: str
) -> None:
    """RED（修复前）：urlopen 先把内网连了、事后才复查 ⇒ 本锁红（requested 含内网落点）。"""
    requested = _install(
        monkeypatch,
        {
            _SEARCH: (200, "", _bing_page([_ENTRY])),
            _ENTRY: (302, landing, b"moved"),
        },
    )

    assert E._fetch_dish_image(tmp_path, DISH) == ""
    assert requested == [_SEARCH, _ENTRY], f"内网落点被真的连了：{requested}"
    assert list(tmp_path.iterdir()) == []


def test_public_redirect_chain_still_saves_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正向锁：公网入口 → 公网落点照旧落盘（护栏不过度拦，契约零变化）。"""
    payload = _png_bytes()
    requested = _install(
        monkeypatch,
        {
            _SEARCH: (200, "", _bing_page([_ENTRY])),
            _ENTRY: (302, _PUBLIC_LANDING, b"moved"),
            _PUBLIC_LANDING: (200, "", payload),
        },
    )

    saved = E._fetch_dish_image(tmp_path, DISH)
    assert saved != "" and Path(saved).read_bytes() == payload
    assert requested == [_SEARCH, _ENTRY, _PUBLIC_LANDING]


def test_direct_candidate_still_saves_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无重定向（常态）：与修复前逐字节一致。"""
    payload = _png_bytes()
    requested = _install(
        monkeypatch,
        {_SEARCH: (200, "", _bing_page([_ENTRY])), _ENTRY: (200, "", payload)},
    )

    assert E._fetch_dish_image(tmp_path, DISH) != ""
    assert requested == [_SEARCH, _ENTRY]


def test_intranet_entry_candidate_is_never_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """入口咽喉仍旧 fail-fast：候选本身就是内网地址 ⇒ 一条请求都不发。"""
    requested = _install(
        monkeypatch,
        {_SEARCH: (200, "", _bing_page(["http://127.0.0.1:8080/x.png"]))},
    )

    assert E._fetch_dish_image(tmp_path, DISH) == ""
    assert requested == [_SEARCH]


def test_landing_recheck_is_kept_as_defense_in_depth() -> None:
    """纵深锁：加护栏不许把旧的两道判据拆掉——入口咽喉 + ``geturl()`` 落点复查
    仍在 ``_accepts`` 现场（同一中央咽喉被点两次，判据本体不复制第二套）。

    只看 ``_accepts`` 那一段：搜索腿（固定 ``cn.bing.com``，非用户可控）留在
    裸 ``urlopen`` 上是本席的有意取舍，不算「第二条无护栏通路」。
    """
    import inspect

    body = inspect.getsource(E._fetch_dish_image).split("def _accepts")[1]
    body = body.split("    query = ")[0]
    assert body.count("check_download_url(") == 2, "入口 + 落点两道复查都要在场"
    assert "_guarded_image_opener()" in body, "取字节必须走护栏 opener"
    assert "urlopen(" not in body, "_accepts 取字节不许留裸 urlopen 通路"


def test_central_throat_is_the_only_verdict_source() -> None:
    """单源锁：eat 里不许长出第二套判据——没有 ipaddress/网段表，判定只出自中央咽喉。

    （注释里的 ``169.254.169.254`` 是 prose 不是判据，故按 AST 的**代码**面查。）
    """
    import ast
    import inspect
    from pathlib import Path

    tree = ast.parse(Path(inspect.getsourcefile(E)).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "ipaddress" not in imported, "自造内网判定＝第二套判据，红线禁止"
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    } | {getattr(node.func, "attr", "") for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not {"ip_network", "ip_address", "_ip_is_blocked"} & names
