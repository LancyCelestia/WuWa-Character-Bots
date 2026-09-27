"""LINKPARSE F-3（S-ATK-LINKPARSE，2026-09-27）：weibo 访客腿两处 `response.read()` 无上限。

`_weibo_visitor_cookie()` 自建 `build_opener`（只挂 CookieProcessor），genvisitor 与
incarnate 两条响应都直接 `response.read()` 整只进内存——目标 host 虽是固定常量
`passport.weibo.com`（SSRF/凭证外流被大幅收敛，故原判「低」），超大响应的 DoS 面
与 kurobbs 同型。修法与 F-1(a) 同一真身：改走中央 `_read_capped`，禁第二把尺。

锁的分工：
- 行为腿：假响应记录每次 read 的 size 参数——无界读必带 `-1`/`None`，限幅读必 ≤
  `DEFAULT_MAX_BYTES+1`；
- 结构腿：AST 现算函数体内每个 `.read` 调用都必须是 `_read_capped(...)` 的实参，
  禁「读了但没限幅」的第三种形态；
- 契约腿：正常小响应 + 访客 cookie 在位 ⇒ 仍返回非空 cookie 并写缓存（限幅不许
  把成功路径改坏）。
"""

from __future__ import annotations

import ast
import http.cookiejar
import inspect
import json
import urllib.request
from typing import Any, Self

import pytest

from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    http_util,
    platforms_weibo as W,
)

_GEN_OK = json.dumps({"ok": 1, "data": {"tid": "TID-42"}}).encode()
_PAD = b" " * (http_util.DEFAULT_MAX_BYTES + 64)
_VISITOR_SRC = ast.parse(inspect.getsource(W)).body


class _FakeRawResp:
    """urllib 响应替身：记录每次 read 的 size 参数。"""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers: dict[str, str] = {}  # 真 urllib 响应必有 .headers（gzip 判定读它）
        self.read_sizes: list[Any] = []

    def read(self, size: Any = -1) -> bytes:
        self.read_sizes.append(size)
        if size is None or int(size) < 0:
            return self._body
        return self._body[: int(size)]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeOpener:
    def __init__(
        self,
        handlers: tuple[Any, ...],
        responses: list[_FakeRawResp],
        seed_cookies: bool = False,
    ) -> None:
        self.handlers = handlers
        self._responses = responses
        self._seed = seed_cookies
        self.calls = 0

    def open(self, request: Any, timeout: Any = None) -> _FakeRawResp:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        if self._seed:
            self._seed = False
            _seed_visitor_cookies(self.handlers)
        return resp


def _install(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[_FakeRawResp],
    *,
    seed_cookies: bool = False,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _fake_build_opener(*handlers: Any, **_kw: Any) -> _FakeOpener:
        opener = _FakeOpener(handlers, responses, seed_cookies=seed_cookies)
        captured["opener"] = opener
        captured["handlers"] = list(handlers)
        return opener

    monkeypatch.setattr(urllib.request, "build_opener", _fake_build_opener)
    return captured


def _reset_cache() -> None:
    W._visitor_cache["cookie"] = ""
    W._visitor_cache["at"] = 0.0


def _seed_visitor_cookies(handlers: tuple[Any, ...]) -> None:
    """把访客 cookie 塞进真 CookieJar（假 opener 只替传输，不改记账）。"""
    jar: http.cookiejar.CookieJar = next(
        h.cookiejar
        for h in handlers
        if isinstance(h, urllib.request.HTTPCookieProcessor)
    )
    for name, value in (("SUB", "s-1"), ("SUBP", "p-1"), ("tid", "42")):
        jar.set_cookie(
            http.cookiejar.Cookie(
                version=0, name=name, value=value, port=None, port_specified=False,
                domain=".weibo.com", domain_specified=True, domain_initial_dot=True,
                path="/", path_specified=True, secure=False, expires=None,
                discard=True, comment=None, comment_url=None, rest={},
            )
        )


# --------------------------------------------------------------------------- 行为腿


def test_visitor_gen_read_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """genvisitor 响应必须限幅读：无界 read() 记到 -1/None 即红。"""
    _reset_cache()
    gen = _FakeRawResp(_GEN_OK + _PAD)
    captured = _install(monkeypatch, [gen, _FakeRawResp(b"")])
    W._weibo_visitor_cookie()
    assert captured["opener"].calls >= 1, "genvisitor 腿根本没被走到＝锁空跑"
    assert gen.read_sizes and all(
        s is not None and int(s) >= 0 and int(s) <= http_util.DEFAULT_MAX_BYTES + 1
        for s in gen.read_sizes
    ), f"genvisitor 读必须带限幅参数，实况 {gen.read_sizes}"


def test_visitor_incarnate_read_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """incarnate 响应同样限幅（这一处此前是裸 `response.read()`，只为落 cookie）。"""
    _reset_cache()
    incarnate = _FakeRawResp(b"<html>cross_domain(0);</html>" + _PAD)
    captured = _install(monkeypatch, [_FakeRawResp(_GEN_OK), incarnate])
    W._weibo_visitor_cookie()
    assert incarnate.read_sizes, "incarnate 腿没读到任何字节＝锁空跑"
    assert all(
        s is not None and int(s) >= 0 and int(s) <= http_util.DEFAULT_MAX_BYTES + 1
        for s in incarnate.read_sizes
    ), f"incarnate 读必须带限幅参数，实况 {incarnate.read_sizes}"


def test_over_limit_gen_body_degrades_without_leaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超限响应：诚实回退空 cookie，异常绝不外抛（访客腿不致命）。"""
    _reset_cache()
    _install(monkeypatch, [_FakeRawResp(_GEN_OK + _PAD), _FakeRawResp(b"")])
    assert W._weibo_visitor_cookie() == ""


# ---------------------------------------------------------------------------- 结构腿


def test_no_bare_read_left_in_visitor_leg() -> None:
    """函数体内每个 `.read(...)` 都必须是 `_read_capped(resp, …)` 的实参。"""
    fn = next(
        node
        for node in _VISITOR_SRC
        if isinstance(node, ast.FunctionDef) and node.name == "_weibo_visitor_cookie"
    )
    capped_targets: set[int] = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_read_capped"
            and node.args
        ):
            first = node.args[0]
            if isinstance(first, ast.Name):
                capped_targets.add(id(first))
    bare: list[int] = []
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read"
            and isinstance(node.func.value, ast.Name)
            and id(node.func.value) not in capped_targets
        ):
            bare.append(node.lineno)
    assert not bare, f"_weibo_visitor_cookie 仍有裸读（行 {bare}）＝F-3 复发"
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_read_capped"
        for node in ast.walk(fn)
    ), "两腿都没接中央限幅尺"


# ---------------------------------------------------------------------------- 契约腿


def test_small_response_contract_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常小响应 + 访客 cookie 在位 ⇒ 仍返回非空 cookie 并写缓存。"""
    _reset_cache()
    _install(
        monkeypatch, [_FakeRawResp(_GEN_OK), _FakeRawResp(b"ok")], seed_cookies=True
    )
    cookie = W._weibo_visitor_cookie()
    assert "SUB=s-1" in cookie and "tid=42" in cookie, f"成功路径被改坏：{cookie!r}"
    assert W._visitor_cache["cookie"] == cookie, "缓存未写入（下次又要整趟握手）"
    _reset_cache()
