"""SSRF 收口锁：抓搜索结果正文的 ``web_search.fetch_page_text`` 必须过中央咽喉。

威胁模型：搜索结果里的 URL 由第三方响应决定（可被上游替换、可 302 跳内网），
属用户可控面。旧实现只做 ``startswith("http")``，``http://169.254.169.254`` /
``http://127.0.0.1`` / 整型混淆 IP 全穿，且 httpx ``follow_redirects=True`` 会把
302 到的内网地址也一并抓。修复=抓前过中央咽喉（复用 ``ssrf_guard.guard_user_url``
→ 内部即 ``check_download_url``，另含 inet_aton 整型 IP 归一与「解析失败=拒绝」）
+ 逐跳重定向事件钩子，不新建第二套 URL 判定。

全离线纪律：
- 内网/元数据/整型 IP 走字面量判定或 inet_aton 归一，不触 DNS；
- 域名路径一律 monkeypatch ``socket.getaddrinfo`` 喂假解析，绝不真发网络；
- 注毒只在进程内 ``monkeypatch``（本机另有席位在写别的文件，禁编辑磁盘注毒）。
"""

from __future__ import annotations

import inspect
import socket

import httpx
import pytest

from plugins.bot_unified_runtime.domains.core.search import web_search
from plugins.bot_unified_runtime.domains.files.sources import downloader as _downloader


# --------------------------------------------------------------------------- #
# 测试替身
# --------------------------------------------------------------------------- #
class _FetchSpy:
    """替换 ``web_search._fetch``：记录抓取是否真的被发起，并返回可控正文。"""

    def __init__(self, text: str | None = None) -> None:
        self.calls: list[dict] = []
        self._text = text

    def __call__(self, url, **kwargs):
        self.calls.append(dict(kwargs, url=url))
        return self._text

    @property
    def count(self) -> int:
        return len(self.calls)


class _StubResponse:
    text = ""

    def raise_for_status(self) -> None:
        return None


class _StubClient:
    def __init__(self) -> None:
        self.closed = False

    def get(self, url: str) -> _StubResponse:
        return _StubResponse()

    def close(self) -> None:
        self.closed = True


def _fake_dns(resolves_to: list[str]):
    def _getaddrinfo(host, port, *a, **k):
        return [(2, 1, 6, "", (ip, 0)) for ip in resolves_to]

    return _getaddrinfo


# --------------------------------------------------------------------------- #
# 锁 1：内网 / 元数据 / 私网 / IPv6 / 整型混淆 / 非法协议 —— 入口拦下且根本不发请求
# --------------------------------------------------------------------------- #
BLOCKED_URLS = [
    "http://127.0.0.1:8742/api/status",          # loopback
    "http://localhost:8080/",                     # 本机主机名
    "http://169.254.169.254/latest/meta-data/",   # 云元数据（AWS/GCP 链路口）
    "http://metadata.google.internal/x",          # 云元数据主机名（黑名单）
    "http://10.1.2.3/internal",                   # 私网 A 类
    "http://192.168.0.55/router",                 # 私网 C 类
    "http://172.16.5.4/admin",                    # 私网 B 类
    "http://[::1]/v1",                            # IPv6 回环
    "http://[fd00::1234]/x",                      # IPv6 唯一本地（ULA）
    "http://2130706433/",                         # 十进制混淆 = 127.0.0.1
    "http://0x7f000001/",                         # 十六进制混淆
    "http://017700000001/",                       # 八进制混淆（前导 0）
    "file:///etc/passwd",                         # 非法协议
    "gopher://127.0.0.1:11211/",                  # 非法协议
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_blocked_urls_return_empty_and_never_fetch(url: str, monkeypatch) -> None:
    spy = _FetchSpy()
    monkeypatch.setattr(web_search, "_fetch", spy)
    assert web_search.fetch_page_text(url) == ""
    assert spy.count == 0, f"护栏未拦下 {url}：仍发起了抓取（SSRF 缺口未闭合）"


def test_blocked_even_if_fetch_would_return_body(monkeypatch) -> None:
    # 反向确认「空串」不是靠 _fetch 恰好返回 None 蒙对的：让假 fetch 返回可读正文，
    # 内网地址仍必须在入口就被拦下、根本走不到 _fetch。
    spy = _FetchSpy(text="SECRET-INTERNAL-DATA")
    monkeypatch.setattr(web_search, "_fetch", spy)
    assert web_search.fetch_page_text("http://169.254.169.254/latest/meta-data") == ""
    assert spy.count == 0


# --------------------------------------------------------------------------- #
# 锁 2（注毒）：把中央咽喉打成「恒放行」，内网地址必穿到 _fetch —— 证明锁 1 有牙
# --------------------------------------------------------------------------- #
def test_poison_central_throat_always_allow_leaks_to_fetch(monkeypatch) -> None:
    # 注毒（中央咽喉本体）：把 check_download_url 打成恒放行，内网地址就会穿到 _fetch ——
    # 证明锁1 的「_fetch 调用数 0」真的有牙、且判定确实流经中央咽喉本体（非本地自判）。
    monkeypatch.setattr(_downloader, "check_download_url", lambda url: None)
    spy = _FetchSpy()
    monkeypatch.setattr(web_search, "_fetch", spy)
    web_search.fetch_page_text("http://169.254.169.254/latest/meta-data")
    assert spy.count == 1, "咽喉被短路后仍拦得住 = 这条锁是假的"


def test_poison_entry_seam_leaks_but_hook_still_strict(monkeypatch) -> None:
    # 注毒（入口腿）：只把入口咽喉打恒放行 → 直接抓取路径穿到 _fetch；
    # 但逐跳钩子走 guard_user_url（更严），内网跳仍抛。证明两腿独立、都非恒真。
    monkeypatch.setattr(web_search, "_ssrf_rejection_for_fetch", lambda url: None)
    spy = _FetchSpy()
    monkeypatch.setattr(web_search, "_fetch", spy)
    web_search.fetch_page_text("http://169.254.169.254/latest/meta-data")
    assert spy.count == 1
    import httpx as _httpx

    with pytest.raises(web_search._SSRFBlockedError):
        web_search._ssrf_request_guard(_httpx.Request("GET", "http://169.254.169.254/"))


# --------------------------------------------------------------------------- #
# 锁 3：抓取路径必须挂「逐跳重定向」SSRF 钩子（防 302 跳内网）
# --------------------------------------------------------------------------- #
def test_fetch_path_builds_client_with_ssrf_redirect_hook(monkeypatch) -> None:
    built: dict = {}

    def fake_build(proxy, timeout_seconds, *, ssrf_guard=False):
        built["ssrf_guard"] = ssrf_guard
        return _StubClient()

    monkeypatch.setattr(web_search, "_build_sync_client", fake_build)
    # 用公网字面量 URL 让入口护栏放行，才会真正建客户端、走抓取。
    web_search.fetch_page_text("https://93.184.216.34/page")
    assert built.get("ssrf_guard") is True, "抓取路径未请求逐跳护栏：302 跳内网无人拦"


# --------------------------------------------------------------------------- #
# 锁 4：钩子本体逐跳判定 —— 内网跳抛、公网跳放行（离线构造 httpx.Request）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest",
        "http://127.0.0.1:9/",
        "http://10.0.0.5/",
        "http://[::1]/",
        "file:///etc/passwd",
    ],
)
def test_redirect_hook_blocks_internal_hop(url: str) -> None:
    req = httpx.Request("GET", url)
    with pytest.raises(web_search._SSRFBlockedError):
        web_search._ssrf_request_guard(req)


def test_redirect_hook_allows_public_hop() -> None:
    # 不抛即放行（公网 IP 字面量，不触 DNS）。
    web_search._ssrf_request_guard(httpx.Request("GET", "https://93.184.216.34/page"))


# --------------------------------------------------------------------------- #
# 锁 5：反向锁 —— 公网搜索端点 / 正常公网 https 不得被误拦（假 DNS，离线）
# --------------------------------------------------------------------------- #
def test_public_https_hostname_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns(["140.82.113.3"]))
    spy = _FetchSpy()
    monkeypatch.setattr(web_search, "_fetch", spy)
    web_search.fetch_page_text("https://html.duckduckgo.com/html/?q=x")
    assert spy.count == 1, "公网搜索 host 被误拦：会打断正常联网检索"
    assert spy.calls[0].get("ssrf_guard") is True


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bing.com/search?q=x",
        "https://html.duckduckgo.com/html/?q=x",
        "https://api.tavily.com/search",
    ],
)
def test_public_search_endpoints_not_false_blocked(url: str, monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns(["150.171.27.10"]))
    spy = _FetchSpy()
    monkeypatch.setattr(web_search, "_fetch", spy)
    web_search.fetch_page_text(url)
    assert spy.count == 1, f"公网搜索端点被误拦: {url}"


def test_hostname_rebinding_to_loopback_is_blocked(monkeypatch) -> None:
    # DNS 把「正常-looking」域名解析到 127.0.0.1：入口必须拒。
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns(["127.0.0.1"]))
    spy = _FetchSpy()
    monkeypatch.setattr(web_search, "_fetch", spy)
    assert web_search.fetch_page_text("https://innocuous.example/x") == ""
    assert spy.count == 0


# --------------------------------------------------------------------------- #
# 锁 6：剥凭证护栏的安全意图 —— 抓取路径根本不携带任何凭据
# --------------------------------------------------------------------------- #
def test_fetch_request_carries_no_credentials() -> None:
    lowered = {key.lower() for key in web_search._DEFAULT_HEADERS}
    assert "cookie" not in lowered
    assert "authorization" not in lowered
    client = web_search._build_sync_client("", 5.0, ssrf_guard=True)
    try:
        client_h = {key.lower() for key in client.headers}
        assert "cookie" not in client_h and "authorization" not in client_h
    finally:
        client.close()


# --------------------------------------------------------------------------- #
# 锁 7：不新建第二套 URL 判定 —— 抓函数必须委托中央咽喉，不得回到弱 startswith
# --------------------------------------------------------------------------- #
def test_fetch_page_text_delegates_to_central_guardrail() -> None:
    src = inspect.getsource(web_search.fetch_page_text)
    assert "_ssrf_rejection_for_fetch" in src, "抓取入口未调用中央咽喉包装"
    assert 'startswith("http")' not in src, "回到旧的弱 scheme 前缀判定（第二套判据）"
