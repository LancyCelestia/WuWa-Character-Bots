"""无头浏览器 ``page.goto`` 前置 SSRF 闸锁（INCIDENT-20260930 第五节 · 缺口③）。

背景：``PlaywrightFetchBackend.fetch_html`` / ``capture_json`` 把 URL 直接喂给
``page.goto``，本机 Chromium 盲连——用户贴一条 ``http://127.0.0.1:3001/`` （SnowLuma
控制面）或 ``http://169.254.169.254/`` （云元数据）就能让 bot 用浏览器去连内网，
`capture_json` 还会把命中的响应 body 收进解析链回显进卡。这是解析链上唯一
没过中央咽喉的出站口（urllib 腿早已由 ``ssrf_guard`` 罩住）。

修法：
①两处 ``page.goto`` **之前**过入口护栏 ``ssrf_guard.guard_user_url``
  （判据＝中央 ``downloader.check_download_url``，F-04「解析失败=拒绝」）；
②导航落点（``page.url``）与截获到的 XHR 响应 URL，在**取 body / 交回内容之前**
  再过一次落点复查（对齐解析链「入口 + geturl 双查」范式）；
③拒绝一律抛 ``ParseHttpError``——调用方（platforms_generic / kurobbs / xhs 订阅）
  既有 ``except`` 分支就是降级通路（回落 og 浅解析 → 纯文本卡），不新增异常面。

已知边界（登记不硬做，见 playwright_backend 模块注释）：Chromium 内部的
**中间跳转**与页内子资源请求由浏览器网络栈自己完成，本层拿不到逐跳落点；
彻底收敛要挂 ``page.route`` 传输层拦截，代价是每条子资源一次 Python 回调
（渲染热路径同族问题）。本文件的锁只覆盖「入口不建连 + 落点不回显」。

全离线纪律：假 ``sync_playwright``/browser/context/page/response，绝不启动真
Chromium；URL 全用字面量 IP 与 ``localhost`` 系主机名（咽喉离线可判、不触 DNS）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.link_parse.fetchers import playwright_backend as pb
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import ParseHttpError

_PUBLIC = "http://93.184.216.34/page"
_INTERNALS = [
    "http://127.0.0.1:3001/status",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.1.2.3/console",
    "http://localhost:8080/x",
    "http://[::1]/x",
]
_JSON = b'{"code":200,"data":{"x":1}}'
_FILTER = "/api/sns/web/v1/user_posted"


class _FakePage:
    def __init__(self, *, final_url: str, responses: list[SimpleNamespace] | None = None) -> None:
        self.goto_calls: list[str] = []
        self.content_calls = 0
        self.url = final_url
        self._responses = responses or []
        self._handlers: list = []

    def on(self, event: str, callback) -> None:
        self._handlers.append((event, callback))

    def goto(self, url: str, **_kwargs: object) -> None:
        self.goto_calls.append(url)
        for event, callback in self._handlers:
            if event == "response":
                for response in self._responses:
                    callback(response)

    def content(self) -> str:
        self.content_calls += 1
        return "<html>INITIAL_STATE</html>"

    def close(self) -> None:
        pass


def _install_fake_playwright(
    monkeypatch: pytest.MonkeyPatch,
    page: _FakePage,
    *,
    launches: list[str] | None = None,
) -> list[str]:
    """装上假 sync_playwright，返回记账用的容器（close 次数等）。"""
    closed: list[str] = []
    launch_log = launches if launches is not None else []
    context = SimpleNamespace(
        new_page=lambda **_kw: page,
        add_cookies=lambda _cookies: None,
    )

    def _launch(**_kwargs: object):
        launch_log.append("launch")
        return browser

    browser = SimpleNamespace(
        new_context=lambda **_kw: context,
        close=lambda: closed.append("browser"),
    )
    playwright = SimpleNamespace(
        chromium=SimpleNamespace(launch=_launch),
        stop=lambda: closed.append("playwright"),
    )
    monkeypatch.setattr(pb, "sync_playwright", lambda: playwright, raising=False)
    return closed


def _response(url: str, *, content_type: str = "application/json", body: bytes = _JSON):
    """假 Playwright Response：``body()`` 计数，被拦时一次都不许调。"""
    calls: list[str] = []

    def _body() -> bytes:
        calls.append(url)
        return body

    response = SimpleNamespace(
        url=url,
        headers={"content-type": content_type},
        body=_body,
    )
    response._body_calls = calls  # type: ignore[attr-defined]
    return response


# --------------------------------------------------------------------------- #
# ①入口闸：内网地址 goto 之前就被拒
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_url", _INTERNALS)
def test_fetch_html_refuses_intranet_entry_before_goto(
    monkeypatch: pytest.MonkeyPatch, bad_url: str
) -> None:
    """主锁①：内网入口 ⇒ 抛 ParseHttpError 且 page.goto 一次都没调用。"""
    page = _FakePage(final_url=bad_url)
    _install_fake_playwright(monkeypatch, page)
    backend = pb.PlaywrightFetchBackend()

    with pytest.raises(ParseHttpError, match="SSRF guard"):
        backend.fetch_html(bad_url)

    assert page.goto_calls == []
    assert page.content_calls == 0


@pytest.mark.parametrize("bad_url", _INTERNALS)
def test_capture_json_refuses_intranet_entry_before_goto(
    monkeypatch: pytest.MonkeyPatch, bad_url: str
) -> None:
    page = _FakePage(final_url=bad_url)
    _install_fake_playwright(monkeypatch, page)
    backend = pb.PlaywrightFetchBackend()

    with pytest.raises(ParseHttpError, match="SSRF guard"):
        backend.capture_json(bad_url, json_filter=_FILTER)

    assert page.goto_calls == []


def test_fetch_html_still_opens_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """正向锁：咽喉放行的公网地址照旧导航、照旧回内容（不过度拦）。"""
    page = _FakePage(final_url=_PUBLIC)
    _install_fake_playwright(monkeypatch, page)
    backend = pb.PlaywrightFetchBackend()

    landing, html = backend.fetch_html(_PUBLIC)

    assert page.goto_calls == [_PUBLIC]
    assert (landing, html) == (_PUBLIC, "<html>INITIAL_STATE</html>")


# --------------------------------------------------------------------------- #
# ②落点复查：跳转后的 page.url 不许把内网内容交回解析链
# --------------------------------------------------------------------------- #
def test_fetch_html_rechecks_navigation_landing_before_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公网入口 → 浏览器落到内网：内容（page.content）一次都不许读。"""
    page = _FakePage(final_url="http://127.0.0.1:3001/secret")
    _install_fake_playwright(monkeypatch, page)
    backend = pb.PlaywrightFetchBackend()

    with pytest.raises(ParseHttpError, match="SSRF guard"):
        backend.fetch_html(_PUBLIC)

    assert page.content_calls == 0


def test_capture_json_rechecks_navigation_landing(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage(final_url="http://169.254.169.254/latest/meta-data/", responses=[])
    _install_fake_playwright(monkeypatch, page)
    backend = pb.PlaywrightFetchBackend()

    with pytest.raises(ParseHttpError, match="SSRF guard"):
        backend.capture_json(_PUBLIC, json_filter=_FILTER)


def test_capture_json_does_not_read_body_of_blocked_xhr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """截获的 XHR 落内网 ⇒ 连 ``response.body()`` 都不取（回显面为零）。"""
    blocked = _response(f"http://127.0.0.1:3001{_FILTER}")
    allowed = _response(f"{_PUBLIC}{_FILTER}")
    page = _FakePage(final_url=_PUBLIC, responses=[blocked, allowed])
    _install_fake_playwright(monkeypatch, page)
    backend = pb.PlaywrightFetchBackend()

    collected = backend.capture_json(_PUBLIC, json_filter=_FILTER)

    assert blocked._body_calls == [], "被拦响应不许取 body"
    assert allowed._body_calls == [allowed.url]
    assert collected == [{"code": 200, "data": {"x": 1}}]


def test_capture_json_public_chain_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """正向锁：公网导航 + 公网接口响应 ⇒ 载荷照旧收（契约零变化）。"""
    allowed = _response(f"{_PUBLIC}{_FILTER}")
    page = _FakePage(final_url=_PUBLIC, responses=[allowed])
    _install_fake_playwright(monkeypatch, page)
    backend = pb.PlaywrightFetchBackend()

    assert backend.capture_json(_PUBLIC, json_filter=_FILTER) == [
        {"code": 200, "data": {"x": 1}}
    ]


# --------------------------------------------------------------------------- #
# ③降级通路：护栏拒绝必须走调用方既有 except（不新造异常类型）
# --------------------------------------------------------------------------- #
def test_guard_rejection_is_parse_http_error_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """异常族 + 成本锁：只用 ``ParseHttpError``（解析链统一降级语），不外泄浏览器/OS
    异常；且入口被拒时**连 Chromium 都不启动**（launch 零次、close 零次）。"""
    launches: list[str] = []
    page = _FakePage(final_url=_PUBLIC)
    closed = _install_fake_playwright(monkeypatch, page, launches=launches)
    backend = pb.PlaywrightFetchBackend()

    with pytest.raises(ParseHttpError) as failure:
        backend.fetch_html("http://192.168.1.1/admin")

    assert isinstance(failure.value, ParseHttpError)
    assert launches == [], "被拦地址不许先付一次浏览器冷启动"
    assert closed == []
    assert page.goto_calls == []


def test_verdicts_come_from_the_central_throat(monkeypatch: pytest.MonkeyPatch) -> None:
    """单源锁：入口判据现取 ``ssrf_guard.guard_user_url``，本件不复制第二套网段表。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers import ssrf_guard

    consulted: list[str] = []
    monkeypatch.setattr(
        ssrf_guard,
        "guard_user_url",
        lambda url: (consulted.append(url) or "替身拒绝") if "denied" in url else None,
    )
    page = _FakePage(final_url="http://ok.example.invalid/page")
    _install_fake_playwright(monkeypatch, page)
    backend = pb.PlaywrightFetchBackend()

    with pytest.raises(ParseHttpError, match="替身拒绝"):
        backend.fetch_html("http://denied.example.invalid/page")
    assert consulted == ["http://denied.example.invalid/page"]
