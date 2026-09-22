"""链接解析链 SSRF 护栏回归（安全审计 I-2 修复，2026-09-14）。

覆盖四件事：
1. 入口护栏（content_parser 分发前）：内网/保留网段/localhost/内网域名
   一律拒绝且走既有「解析失败」降级路径（群静默/私聊人话提示），
   解析函数绝不收到内网 URL；
2. 公网 URL 正常放行（mock DNS），不误伤字面量公网整型 IP；
3. og 兜底落点复查（platforms_generic._og_scrape）：重定向落到内网时
   在解析/回显内容之前抛 ParseHttpError（mock http_get_text 的 final url，
   等价于 geturl 落点）。全离线，无真实网络；
4. 审查 F-04（解析失败=拒绝）：整型 IP（十进制/十六进制/八进制，
   2130706433=127.0.0.1）归一化后拒绝、DNS 解析失败拒绝（旧版放行
   已改判）、无 host/畸形 URL 拒绝、护栏崩溃才允许 fail-open+WARNING；
5. P2-12（2026-09-15）：非 og 深解析二次抓取（xhs INITIAL_STATE /
   douyin _ROUTER_DATA / 用户主页 / 搜索页）同款落点复查——302 落
   内网保留段在解析/回显前拒绝，拒绝直通全链不 og 复抓。
"""

from __future__ import annotations

import logging
import socket
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.content_parser import (
    build_content_capability,
)
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.core.contracts.media import (
    ParserRule,
    build_parsed_content,
)
from plugins.bot_unified_runtime.domains.files.sources import (
    downloader as downloader_module,
)

# v21r2 W1a: platforms_generic 真身已迁 domains/link_parse/parsers/，monkeypatch 需打在真身上
# （上方 content_parser import 已先行触发 sources.parsers 聚合，垫片期顺序纪律满足）
from plugins.bot_unified_runtime.domains.link_parse.parsers import platforms_generic
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.ssrf_guard import (
    check_fetch_landing,
    guard_user_url,
)
from plugins.bot_unified_runtime.sources.registry import ParserRegistry

_PUBLIC_IP = "93.184.216.34"
_INTRANET_IP = "10.8.0.7"


def _item(title: str = "公开标题"):
    return build_parsed_content(
        platform="generic",
        item_id="1",
        item_kind="post",
        title=title,
        canonical_url="https://example.com/1",
    )


def _message(text: str, *, group: bool = False) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="group:g1" if group else "private:u1",
        session_type=SessionType.GROUP if group else SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _registry(pattern: str, parse_fn) -> dict:
    registry = ParserRegistry()
    registry.register(
        ParserRule(
            parser_id="generic",
            source_id="通用",
            url_patterns=[pattern],
            priority=1,
        )
    )
    return {"registry": registry, "parsers": {"generic": parse_fn}}


def _run(text: str, pattern: str, parse_fn, *, group: bool = False):
    capability = build_content_capability(
        SimpleNamespace(bot_media_analyze_enabled=False),
        registry=_registry(pattern, parse_fn),
    )
    return capability(_message(text, group=group), None)


def _patch_dns(monkeypatch, ip: str) -> None:
    """把 socket.getaddrinfo 钉到固定解析结果（离线确定性）。"""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, int(port or 0)))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def _patch_dns_failure(monkeypatch) -> None:
    def fail_getaddrinfo(host, port, *args, **kwargs):
        raise socket.gaierror(11001, "getaddrinfo failed")

    monkeypatch.setattr(socket, "getaddrinfo", fail_getaddrinfo)


# ---------- 1. 入口护栏：内网 URL 拒绝 + 降级路径 ----------


@pytest.mark.parametrize(
    ("url", "pattern"),
    [
        # 字面量内网 IP ×4：借平台关键词子串混过注册表匹配的真实向量。
        (
            "http://127.0.0.1:8742/health?u=xiaohongshu.com/explore/abc",
            r"xiaohongshu\.com/explore",
        ),
        (
            "http://10.1.2.3/?fallback=bilibili.com/video/BV1xx411c7mD",
            r"bilibili\.com/video",
        ),
        (
            "http://192.168.1.1/router?page=github.com/a/b",
            r"github\.com/a/b",
        ),
        (
            "http://169.254.169.254/latest/meta-data/",
            r"169\.254\.169\.254",
        ),
    ],
)
def test_entry_guard_rejects_intranet_literal_ip(url: str, pattern: str) -> None:
    calls: list[str] = []

    def parse_fn(url_arg: str):
        calls.append(url_arg)
        return _item()

    result = _run(url, pattern, parse_fn, group=True)
    assert calls == [], "解析函数绝不能收到内网 URL"
    assert "ssrf_guard_rejected" in result.audit_tags
    assert "parse_failed" not in result.audit_tags
    # 群聊走既有静默降级，绝不回显内网内容。
    assert result.body == ""
    assert result.send_policy == SendPolicy.SILENT_AUDIT
    assert "silent_group_parse_failure" in result.audit_tags


def test_entry_guard_rejects_intranet_domain_via_dns(monkeypatch) -> None:
    """内网域名：DNS 解析结果落内网 → 拒绝（不依赖 URL 形态）。"""
    _patch_dns(monkeypatch, _INTRANET_IP)
    calls: list[str] = []

    def parse_fn(url_arg: str):
        calls.append(url_arg)
        return _item()

    url = "http://nas.corp.internal/secret?ref=xiaohongshu.com/explore/abc"
    result = _run(url, r"xiaohongshu\.com/explore", parse_fn, group=True)
    assert calls == []
    assert "ssrf_guard_rejected" in result.audit_tags
    assert result.send_policy == SendPolicy.SILENT_AUDIT


def test_entry_guard_rejects_localhost() -> None:
    """localhost 黑名单主机名：不查 DNS 直接拒绝（SnowLuma 3001 场景）。"""
    calls: list[str] = []

    def parse_fn(url_arg: str):
        calls.append(url_arg)
        return _item()

    url = "http://localhost:3001/?x=xiaohongshu.com/explore/abc"
    result = _run(url, r"xiaohongshu\.com/explore", parse_fn)
    assert calls == []
    assert "ssrf_guard_rejected" in result.audit_tags


def test_entry_guard_private_chat_degrades_with_verbal_hint() -> None:
    """私聊降级：人话提示 + 原链接回放（用户自己的链接，非内网内容）。"""
    url = "http://127.0.0.1:8080/?u=xiaohongshu.com/explore/abc"

    def parse_fn(url_arg: str):
        raise AssertionError("不应到达解析函数")

    result = _run(url, r"xiaohongshu\.com/explore", parse_fn, group=False)
    assert "ssrf_guard_rejected" in result.audit_tags
    assert "内网或本机地址" in result.body
    assert url in result.body


# ---------- 2. 公网 URL 放行 + DNS 失败放行策略 ----------


def test_entry_guard_allows_public_url(monkeypatch) -> None:
    _patch_dns(monkeypatch, _PUBLIC_IP)
    calls: list[str] = []

    def parse_fn(url_arg: str):
        calls.append(url_arg)
        return _item()

    url = "https://www.xiaohongshu.com/explore/abc123"
    result = _run(url, r"xiaohongshu\.com", parse_fn)
    assert calls == [url]
    assert "ssrf_guard_rejected" not in result.audit_tags
    assert "【标题】公开标题" in result.body


def test_entry_guard_allows_public_host_with_platform_substring(monkeypatch) -> None:
    """公网攻击者域借平台关键词过匹配：公网落点放行（内容解析照旧）。"""
    _patch_dns(monkeypatch, _PUBLIC_IP)
    calls: list[str] = []

    def parse_fn(url_arg: str):
        calls.append(url_arg)
        return _item()

    url = "http://public.example.com/?v=bilibili.com/video/BV1xx411c7mD"
    result = _run(url, r"bilibili\.com/video", parse_fn)
    assert calls == [url]
    assert "ssrf_guard_rejected" not in result.audit_tags


def test_entry_guard_rejects_when_dns_unresolvable(monkeypatch) -> None:
    """DNS 解析失败=拒绝（审查 F-04 改判）。

    旧行为（已废，2026-09-14 前锁死过相反断言）：DNS 失败放行，给
    纯代理可达平台让路——但整型 IP、rebind 域名恰好借这条 OSError
    cause 路径穿透入口（Critical）。新语义：无法确证公网一律拒绝，
    走既有「解析失败」降级；代价是代理可达平台少解析一条链接，
    换取入口护栏零放行。
    """
    _patch_dns_failure(monkeypatch)
    calls: list[str] = []

    def parse_fn(url_arg: str):
        calls.append(url_arg)
        return _item()

    url = "https://proxy-only.example/video/1"
    result = _run(url, r"proxy-only\.example", parse_fn, group=True)
    assert calls == [], "解析函数绝不能收到无法确证公网的 URL"
    assert "ssrf_guard_rejected" in result.audit_tags
    assert result.send_policy == SendPolicy.SILENT_AUDIT


# ---------- 3. og 兜底落点复查（重定向 landing = mock geturl） ----------


def test_og_scrape_rejects_intranet_landing(monkeypatch) -> None:
    """http_get_text 的最终 URL 落内网 → 在解析内容之前抛 ParseHttpError。"""
    og_html = (
        '<html><meta property="og:title" content="内网服务标题">'
        '<meta property="og:description" content="不该回显的内容"></html>'
    )

    def fake_get_text(url, **kwargs):
        # 落点即模拟 response.geturl()：入口公网、重定向落内网。
        return "http://169.254.169.254/latest/meta-data/", og_html

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        platforms_generic._og_scrape(
            "http://public.example.com/redirect", platform="generic", item_kind="post"
        )


def test_og_scrape_allows_public_landing(monkeypatch) -> None:
    _patch_dns(monkeypatch, _PUBLIC_IP)
    og_html = (
        '<html><meta property="og:title" content="公开标题">'
        '<meta property="og:description" content="公开简介"></html>'
    )

    def fake_get_text(url, **kwargs):
        return "https://cdn.example.com/final", og_html

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    item = platforms_generic._og_scrape(
        "http://public.example.com/page", platform="generic", item_kind="post"
    )
    assert item.content is not None
    assert item.content.title == "公开标题"


def test_og_scrape_non_html_garbage_never_echoed(monkeypatch) -> None:
    """非 HTML 响应（内网服务二进制/纯文本）：无 title 即 ParseHttpError，
    乱码不进卡（结构性防线，此处锁行为）。
    （F-04 后须 mock 公网 DNS：旧版此用例隐性依赖「DNS 失败放行」才能
    走到 no title 断言，新语义下解析失败在落点复查即拒绝。）"""
    _patch_dns(monkeypatch, _PUBLIC_IP)

    def fake_get_text(url, **kwargs):
        return "https://public.example.com/bin", "\x00\x01binary garbage \xff\xfe"

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    with pytest.raises(ParseHttpError, match="no title"):
        platforms_generic._og_scrape(
            "https://public.example.com/bin",
            platform="generic",
            item_kind="post",
        )


# ---------- 4. 审查 F-04：解析失败=拒绝，整型 IP 归一化 ----------


@pytest.mark.parametrize(
    "url",
    [
        # 十进制整型：2130706433 = 127.0.0.1（F-04 原始向量）。
        "http://2130706433/?u=xiaohongshu.com/explore/abc",
        # 十六进制整型：0x7f000001 = 127.0.0.1。
        "http://0x7f000001/",
        # 八进制整型（inet_aton 前导 0 语义）：017700000001 = 127.0.0.1。
        "http://017700000001/",
        # 整型 IP + 端口/userinfo：归一化必须保留端口再判定。
        "https://user:pass@2130706433:8443/x",
    ],
)
def test_guard_rejects_integer_form_loopback(url: str) -> None:
    """整型 IP 归一化成点分十进制后必须命中既有私网段判定（F-04）。"""
    reason = guard_user_url(url)
    assert reason is not None, f"整型回环地址必须拒绝：{url}"
    assert "内网" in reason or "本机" in reason


def test_guard_allows_public_integer_form_ip() -> None:
    """整型公网 IP 不误伤：16843009 = 1.1.1.1，按字面量公网放行（离线、零 DNS）。"""
    assert guard_user_url("http://16843009/") is None


def test_guard_rejects_when_dns_unresolvable(monkeypatch) -> None:
    """护栏单元级：DNS 解析失败=拒绝（旧版放行，F-04 改判）。"""
    _patch_dns_failure(monkeypatch)
    assert guard_user_url("https://rebind.attacker.example/x") is not None


def test_landing_rejects_when_dns_unresolvable(monkeypatch) -> None:
    """落点复查同样适用「解析失败=拒绝」：og 兜底链拦住 rebind 回显。"""
    _patch_dns_failure(monkeypatch)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        check_fetch_landing(
            "https://rebind.attacker.example/final", "https://public.example/origin"
        )


def test_landing_rejects_integer_form_loopback() -> None:
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        check_fetch_landing("http://2130706433/final", "https://public.example/origin")


def test_landing_rejects_empty_target() -> None:
    """落点目标为空=无法确证公网 → 拒绝（旧版静默放行）。"""
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        check_fetch_landing("", "")


def test_guard_rejects_no_host_and_malformed() -> None:
    """无 host / 畸形 URL 一律拒绝（F-04：旧版畸形 URL 会炸出护栏外）。"""
    assert guard_user_url("http:///path") is not None  # 无 host
    assert guard_user_url("http://[::1") is not None  # urlsplit ValueError
    assert guard_user_url("http://host:port/") is not None  # 非法端口
    assert guard_user_url("") is not None  # 空地址


def test_guard_crash_fail_open_logs_warning(monkeypatch, caplog) -> None:
    """护栏自身意外崩溃是唯一允许的 fail-open，且必须记 WARNING（F-04 裁定）。"""

    def boom(url: str) -> None:
        raise RuntimeError("guard internal bug")

    monkeypatch.setattr(downloader_module, "check_download_url", boom)
    with caplog.at_level(
        logging.WARNING, logger="plugins.bot_unified_runtime.sources.parsers.ssrf_guard"
    ):
        reason = guard_user_url("https://example.com/")
    assert reason is None, "仅护栏崩溃才允许 fail-open"
    assert any("fail-open" in record.getMessage() for record in caplog.records)


def test_entry_guard_rejects_decimal_ip_chain() -> None:
    """链路级：十进制整型回环借平台关键词过匹配 → 入口护栏拒绝，解析函数零触达。"""
    calls: list[str] = []

    def parse_fn(url_arg: str):
        calls.append(url_arg)
        return _item()

    url = "http://2130706433/?u=xiaohongshu.com/explore/abc"
    result = _run(url, r"xiaohongshu\.com/explore", parse_fn, group=True)
    assert calls == []
    assert "ssrf_guard_rejected" in result.audit_tags
    assert result.send_policy == SendPolicy.SILENT_AUDIT


# ---------- 5. P2-12：非 og 深解析二次抓取的落点复查（xhs/douyin） ----------
#
# 台账实证：短链逐跳 SSRF 已修（_GuardedShortLinkRedirectHandler 每跳过
# 护栏），og 兜底抓取有落点复查；但 xhs INITIAL_STATE / douyin _ROUTER_DATA
# 的深解析二次抓取此前无落点复查——盲 SSRF 一跳侧信道（重定向落到内网后
# 页面内容会经深解析上卡回显）。以下用例 mock http_get_text / playwright
# 后端的「最终 URL」等价于 response.geturl() 落点，全离线、无真实网络。

# 深解析假响应内容本身「可回显」：若不拦，深解析会把它发上卡——用于证明
# 拒绝发生在解析/回显之前。
_XHS_STATE_HTML = (
    '<html><script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{"n1":'
    '{"note":{"noteId":"n1","title":"深解析标题","desc":"深解析正文",'
    '"user":{},"imageList":[]}}}}}</script></html>'
)
_DOUYIN_ROUTER_HTML = (
    '<html><script>window._ROUTER_DATA={"loaderData":{"video/(1)/page":'
    '{"videoInfoRes":{"item_list":[{"aweme_id":"1","desc":"深解析正文",'
    '"author":{"nickname":"深解析作者"},"video":{"cover":{"url_list":[]}},'
    '"statistics":{}}]}}}}</script></html>'
)
# 保留段落点各一：回环 / 内网 10.x / 链路本地 169.254.x / 内网 192.168.x。
_INTRANET_LANDINGS = [
    "http://127.0.0.1:3001/",
    "http://10.8.0.7/nas/admin",
    "http://169.254.169.254/latest/meta-data/",
    "http://192.168.1.1/router",
]


@pytest.mark.parametrize("landing_url", _INTRANET_LANDINGS)
def test_xhs_deep_parse_rejects_intranet_landing(monkeypatch, landing_url: str) -> None:
    """xhs INITIAL_STATE 深解析抓取：入口公网、302 落内网 → 解析前拒绝。"""

    def fake_get_text(url: str, **kwargs):
        return landing_url, _XHS_STATE_HTML

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        platforms_generic._xhs_note_deep_parse(
            "https://www.xiaohongshu.com/explore/n1", cookie_header="web_session=x"
        )


@pytest.mark.parametrize("landing_url", _INTRANET_LANDINGS)
def test_xhs_full_chain_rejects_and_never_refetches(
    monkeypatch, landing_url: str
) -> None:
    """链路级：深解析落点被拒 → ParseHttpError 直通全链，不 og 复抓、
    不走 playwright 通道（内网请求零追加）。"""
    calls: list[str] = []

    def fake_get_text(url: str, **kwargs):
        calls.append(url)
        return landing_url, _XHS_STATE_HTML

    class _ForbiddenPlaywright:
        def fetch_html(self, *args, **kwargs):
            raise AssertionError("落点被拒后不得再走 playwright 通道")

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        platforms_generic.parse_xiaohongshu(
            "https://www.xiaohongshu.com/explore/n1",
            cookie_header="web_session=x",
            playwright_backend=_ForbiddenPlaywright(),
        )
    assert calls == ["https://www.xiaohongshu.com/explore/n1"]


def test_xhs_deep_parse_playwright_channel_rejects_intranet_landing(monkeypatch) -> None:
    """直连无 INITIAL_STATE → playwright 通道 page.url 落内网 → 同样拒绝。"""

    def fake_get_text(url: str, **kwargs):
        return "https://www.xiaohongshu.com/explore/n1", "<html>no state</html>"

    class _Backend:
        def fetch_html(self, url: str, *, cookies=None):
            return "http://10.1.2.3/inner", _XHS_STATE_HTML

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        platforms_generic._xhs_note_deep_parse(
            "https://www.xiaohongshu.com/explore/n1",
            cookie_header="web_session=x",
            playwright_backend=_Backend(),
        )


def test_xhs_user_profile_fetch_html_rejects_intranet_landing(monkeypatch) -> None:
    """用户主页 INITIAL_STATE 二次抓取：落内网 → 拒绝直通，不回退 og。"""

    class _Backend:
        def capture_json(self, url: str, *, cookies=None, json_filter=None):
            return []

        def fetch_html(self, url: str, *, cookies=None):
            return "http://169.254.169.254/latest/meta-data/", "<html>内网页面</html>"

    def forbidden_get_text(url: str, **kwargs):
        raise AssertionError("落点被拒后不得回退 og 再抓取")

    monkeypatch.setattr(platforms_generic, "http_get_text", forbidden_get_text)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        platforms_generic._xhs_user_profile_card(
            "https://www.xiaohongshu.com/user/profile/u1",
            _Backend(),
            "web_session=x",
        )


def test_xhs_search_state_fetch_landing_reject_without_echo(monkeypatch) -> None:
    """搜索页状态抓取：落内网 → 拒绝后走既有入口卡兜底，内网内容零回显。"""

    def fake_get_text(url: str, **kwargs):
        return "http://127.0.0.1:9200/", _XHS_STATE_HTML

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    item = platforms_generic._xhs_search_result_card(
        "https://www.xiaohongshu.com/search_result/xyz", cookie_header="web_session=x"
    )
    assert item.content is not None
    assert "深解析" not in item.content.title
    assert "深解析" not in (item.content.summary or "")


def test_xhs_deep_parse_allows_public_landing(monkeypatch) -> None:
    """公网落点放行：深解析照常出卡（不误伤）。"""
    _patch_dns(monkeypatch, _PUBLIC_IP)

    def fake_get_text(url: str, **kwargs):
        return "https://www.xiaohongshu.com/explore/n1", _XHS_STATE_HTML

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    item = platforms_generic._xhs_note_deep_parse(
        "https://www.xiaohongshu.com/explore/n1", cookie_header="web_session=x"
    )
    assert item is not None and item.content is not None
    assert item.content.title == "深解析标题"


@pytest.mark.parametrize("landing_url", _INTRANET_LANDINGS)
def test_douyin_full_chain_rejects_and_never_refetches(
    monkeypatch, landing_url: str
) -> None:
    """douyin _ROUTER_DATA 深解析抓取：入口公网、302 落内网 → 拒绝直通，
    不回退 og 复抓同一落点（修前该内容会整卡回显）。"""
    calls: list[str] = []

    def fake_get_text(url: str, **kwargs):
        calls.append(url)
        return landing_url, _DOUYIN_ROUTER_HTML

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    with pytest.raises(ParseHttpError, match="SSRF guard"):
        platforms_generic.parse_douyin(
            "https://www.douyin.com/video/1", cookie_header="sessionid=x"
        )
    assert calls == ["https://www.douyin.com/video/1"]


def test_douyin_deep_parse_allows_public_landing(monkeypatch) -> None:
    """公网落点放行：_ROUTER_DATA 深解析照常出卡（不误伤）。"""
    _patch_dns(monkeypatch, _PUBLIC_IP)

    def fake_get_text(url: str, **kwargs):
        return "https://www.douyin.com/video/1", _DOUYIN_ROUTER_HTML

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    item = platforms_generic.parse_douyin(
        "https://www.douyin.com/video/1", cookie_header="sessionid=x"
    )
    assert item.content is not None
    assert item.content.title == "深解析正文"
