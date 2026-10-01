"""F-CRED-1 回归锁：凭据健康探针的凭证出站必须并入中央咽喉（WP1 件）。

审计坐实（SEAT-ATK-SSRF F-CRED-1）：``credential_health._apply_probe`` 曾以裸
``urllib.request.urlopen`` 携带 Cookie 探测上游——urllib 跨 host 30x 重定向
**不剥 Cookie**（原生只剥 ``add_unredirected_header`` 桶），探测目标域上的开放
重定向即可把平台登录三件套整串送到落点域。本仓唯一咽喉 =
``link_parse/parsers/http_util``：``_build_opener()`` 默认装
``_CredentialScrubbingRedirectHandler``（跨 host 剥 Cookie/Authorization），
初始附凭证经 ``scrub_credentials_for_target``（目标域归属校验）。

全离线：只对本机随机端口上的两个 ``HTTPServer`` 监听器发请求
（127.0.0.1 与 localhost 是两个不同的 host 名，正合「跨 host」判据形态），
绝不触网。锁三层：

- ① 行为：跨 host 302 ⇒ 第二监听器不得收到 Cookie；同 host 302 ⇒ 必须仍收到
  （防过度剥，误剥会毁掉站内登录态续跳）。
- ② 结构：探针件不得再出现「带凭证的裸 urlopen」，且 ``_apply_probe`` 必须
  点名中央件（``_build_opener`` 与 ``scrub_credentials_for_target``）——禁止
  在探针件里新建第二套剥除逻辑，判据只认「吃中央件」。
- ③ 门有牙：注毒样本（手工挂 Cookie + 裸 urlopen）必须被同一扫描函数报红。
"""

from __future__ import annotations

import ast
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from plugins.bot_unified_runtime.domains.core.credentials import credential_health
from plugins.bot_unified_runtime.domains.core.credentials.credentials import (
    CredentialRef,
    CredentialValue,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.cookies import (
    PlatformCookie,
)

_PROBE_SOURCE_PATH = (
    Path(__file__).resolve().parent.parent
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "core"
    / "credentials"
    / "credential_health.py"
)

# 哨兵 Cookie 值：真值只在测试进程内存里，绝不外发。
COOKIE_SENTINEL = "SESSDATA=LEAK-CANARY-b64"
# 探针腿允许的首跳 host：用 PlatformCookie 窄域声明本机两监听器
# （provider 产出的真实票即此形态；普通 str 会走联合域校验、本机必然不归属）。
_LOCAL_DOMAINS = ("localhost", "127.0.0.1")


class _FakeStore:
    """最小 CredentialStore 桩：只有一个 ref、值即哨兵 Cookie。"""

    def __init__(self, value: CredentialValue) -> None:
        self._value = value

    def refs(self) -> list[CredentialRef]:
        return [
            CredentialRef(
                ref_id=self._value.ref_id,
                kind=self._value.kind,
                source="test",
            )
        ]

    def resolve(self, ref_id: str) -> CredentialValue | None:
        if ref_id == self._value.ref_id:
            return self._value
        return None


def _checker_for(probe_url: str) -> credential_health.CredentialHealthChecker:
    value = CredentialValue(
        ref_id="bili",
        kind="cookie",
        value=PlatformCookie(COOKIE_SENTINEL, cookie_domains=_LOCAL_DOMAINS),
    )
    return credential_health.CredentialHealthChecker(
        _FakeStore(value),
        probe_urls={"bili": probe_url},
        timeout_seconds=5.0,
    )


class _RecordingHandler(BaseHTTPRequestHandler):
    """记录每一跳收到的 Cookie 头；按 handler 类上的剧本回应。"""

    # 类级剧本（由 fixture 注入）：mode = "cross" | "same"
    mode: ClassVar[str] = "same"
    target_url: ClassVar[str] = ""
    seen_cookies: ClassVar[list[tuple[str, str]]] = []

    def do_GET(self) -> None:
        cookie = self.headers.get("Cookie", "")
        type(self).seen_cookies.append((self.path, cookie))
        if self.path == "/start" and type(self).mode == "cross":
            # 跨 host 剧本：本监听器 302 到「另一 host 名」的 /final。
            self.send_response(302)
            self.send_header("Location", f"{type(self).target_url}/final")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        body = b'{"ok": 1}'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args, **kwargs) -> None:  # 静音 http.server 默认 stderr 日志
        return


def _start_server(host: str) -> HTTPServer:
    server = HTTPServer((host, 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture()
def local_pair():
    """两台本机监听器（127.0.0.1 / localhost），每用例重置记录与剧本。"""
    _RecordingHandler.seen_cookies = []
    _RecordingHandler.mode = "same"
    _RecordingHandler.target_url = ""
    a = _start_server("127.0.0.1")
    b = _start_server("localhost")
    try:
        yield a, b
    finally:
        for server in (a, b):
            server.shutdown()
            server.server_close()


# -------------------------- ① 行为：跨 host 剥 / 同 host 保留 --------------------------

def test_cross_host_redirect_strips_cookie_from_probe(local_pair) -> None:
    """探针腿：目标 302 跨 host 时，落点监听器绝不能收到 Cookie（F-CRED-1 主锁）。"""
    _a, b = local_pair
    _RecordingHandler.mode = "cross"
    _RecordingHandler.target_url = f"http://127.0.0.1:{b.server_port}"
    # 首跳打在 localhost、落点是 127.0.0.1：两个不同 host 名，构成跨 host 一跳。
    checker = _checker_for(f"http://localhost:{_a.server_port}/start")
    reports = checker.check(probe=True)
    assert reports and reports[0].state == credential_health.STATE_OK
    landed = [cookie for path, cookie in _RecordingHandler.seen_cookies if path == "/final"]
    assert landed, "第二跳必须真的发生（否则本锁在测空气）"
    assert all(COOKIE_SENTINEL not in cookie for cookie in landed), (
        "跨 host 重定向后哨兵 Cookie 抵达了落点监听器 = 凭证外泄"
    )


def test_same_host_redirect_keeps_cookie_from_probe(local_pair) -> None:
    """同 host 站内 302 续跳必须仍带 Cookie（防过度剥，误剥会毁掉登录态续跳）。"""
    a, _b = local_pair
    # 复用「发 302」剧本，落点改回同 host 名：A(localhost) /start → localhost /final。
    _RecordingHandler.mode = "cross"
    _RecordingHandler.target_url = f"http://localhost:{a.server_port}"
    checker = _checker_for(f"http://localhost:{a.server_port}/start")
    reports = checker.check(probe=True)
    assert reports and reports[0].state == credential_health.STATE_OK
    landed = [cookie for path, cookie in _RecordingHandler.seen_cookies if path == "/final"]
    assert landed, "同 host 302 第二跳必须发生（否则本锁在测空气）"
    assert all(COOKIE_SENTINEL in cookie for cookie in landed), (
        "同 host 重定向被剥 Cookie = 过度剥，会毁掉站内登录态续跳"
    )


# -------------------------- ② 结构：探针件吃中央件、禁裸 urlopen --------------------------

def _scan_credential_health_source(source: str) -> list[str]:
    """扫描 credential_health 源码：带凭证的出站调用必须收进中央件。

    违规形态：
      - 任何 ``urlopen(...)`` 调用（中央咽喉之外一律不许出现）；
      - 携带 Cookie 的 ``Request(...)`` 构造，且其所在函数既未经
        ``scrub_credentials_for_target`` / ``credentials_allowed_for_target``
        过滤、也未用 ``_build_opener``（中央 opener 工厂）。
    """
    tree = ast.parse(source)
    parent: dict[int, ast.AST] = {}
    for cur in ast.walk(tree):
        for child in ast.iter_child_nodes(cur):
            parent[id(child)] = cur

    def enclosing(node: ast.AST) -> ast.AST | None:
        cur: ast.AST | None = node
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur
            cur = parent.get(id(cur))
        return None

    def call_name(call: ast.Call) -> str:
        func = call.func
        if isinstance(func, ast.Attribute):
            return func.attr
        if isinstance(func, ast.Name):
            return func.id
        return ""

    def carries_cookie(call: ast.Call) -> bool:
        for kw in call.keywords:
            value = kw.value
            if kw.arg == "headers" and isinstance(value, ast.Dict):
                for key in value.keys:
                    if (
                        isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                        and key.value.lower() == "cookie"
                    ):
                        return True
        return False

    scrubbed_funcs: set[int] = set()
    opener_funcs: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            name = call_name(sub)
            if name in {"scrub_credentials_for_target", "credentials_allowed_for_target"}:
                scrubbed_funcs.add(id(node))
            if name == "_build_opener":
                opener_funcs.add(id(node))

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        if name == "urlopen":
            violations.append(f"{node.lineno}: 裸 urlopen（中央咽喉之外的出站）")
            continue
        if name == "Request" and carries_cookie(node):
            fn = enclosing(node)
            fid = id(fn) if fn is not None else None
            if fid in scrubbed_funcs or fid in opener_funcs:
                continue
            violations.append(f"{node.lineno}: 带 Cookie 的 Request 未收进中央件")
    return violations


def test_probe_leg_uses_central_throat_no_bare_urlopen() -> None:
    source = _PROBE_SOURCE_PATH.read_text(encoding="utf-8")
    violations = _scan_credential_health_source(source)
    assert not violations, "credential_health 凭证出站未并入中央咽喉：\n" + "\n".join(violations)


def test_probe_leg_names_central_helpers() -> None:
    """活性方向：_apply_probe 函数体必须点名两枚中央件（禁第二真身）。"""
    tree = ast.parse(_PROBE_SOURCE_PATH.read_text(encoding="utf-8"))
    apply_probe = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_probe"
    )
    names = {
        (sub.func.attr if isinstance(sub.func, ast.Attribute) else sub.func.id)
        for sub in ast.walk(apply_probe)
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, (ast.Attribute, ast.Name))
    }
    assert "_build_opener" in names, "探针腿必须经 http_util._build_opener（剥凭证 handler 默认装配）"
    assert "scrub_credentials_for_target" in names, "附凭证前必须过目标域咽喉 scrub_credentials_for_target"


def test_negative_sample_is_detected() -> None:
    """门有牙：注毒旧形态（手工 Cookie + 裸 urlopen）必须报红。"""
    bad = '''
import urllib.request

def _apply_probe(url, credential_value):
    request = urllib.request.Request(
        url, headers={"User-Agent": "x", "Cookie": credential_value}
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status
'''
    assert _scan_credential_health_source(bad), "注毒的裸 urlopen+Cookie 必须被扫出"

    bad2 = '''
def _apply_probe(url, cookie):
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        scrub_credentials_for_target,
    )

    allowed = scrub_credentials_for_target(cookie, url)
    request = __import__("urllib.request", fromlist=["Request"]).Request(
        url, headers={"Cookie": allowed}
    )
    return request
'''
    # scrub 在场但没走中央 opener 且直接构造带 Cookie 的 Request：
    # scrub 腿放行 Request 构造，但任何 urlopen 仍必红——构造一个含 urlopen 的变体。
    bad3 = bad2 + '''

def _extra(req):
    import urllib.request as r

    return r.urlopen(req)
'''
    assert _scan_credential_health_source(bad3), "即便过了 scrub，裸 urlopen 仍须报红"
