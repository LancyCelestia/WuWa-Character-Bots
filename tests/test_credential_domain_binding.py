"""WP1 凭证跨域外泄统一咽喉回归（审计 D5-01 / E2-N14 / E1-2 / P0-9）。

全离线：不发任何真实第三方请求。四条缺陷各锁一层——

- ① 附凭证前的目标域校验（http_util 单一咽喉）：Cookie 只有当请求目标 host
  属于该凭证所属平台域集时才允许带出；不归属→剥 Cookie 后继续（降级未登录）。
  域集唯一真身 = cookies.PLATFORM_COOKIE_DOMAINS（扩它，不另建表）。
- ② 跨 host 重定向剥凭证：urllib 默认 redirect_request 只剥 content-*，跨 host
  原样保留 Cookie；新 handler 在 host 变化时剥 Cookie/Authorization。
- ③ 无锚定匹配收口：registry 命中后校验候选 URL 真实 host 归属规则平台域；
  content_parser 候选选择加同样归属判定；不认不归属的候选（含 steam 自读兜底）。
- 回归护栏：短链（b23.tv / xhslink）与内网字面量不误伤、不砍合法链路。

RED→GREEN 判据以实跑输出为准，见 impl-WP1-log.md §3。
"""

from __future__ import annotations

from types import SimpleNamespace
from urllib import request as urlrequest

import pytest

from plugins.bot_unified_runtime.domains.core.contracts.media import (
    ParserRule,
    SourceInput,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    build_content_parser_registry,
    extract_http_urls,
    http_util,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.cookies import (
    PLATFORM_COOKIE_DOMAINS,
)


class _CapturingOpener:
    """记录 .open() 收到的 Request（初始请求头即 ① 的判定点）。"""

    def __init__(self, sink: list) -> None:
        self._sink = sink

    def open(self, request, timeout=None):
        self._sink.append(request)

        class _Resp:
            def __init__(self) -> None:
                self.headers: dict[str, str] = {}

            def read(self, *_a):
                return b"{}"

            def geturl(self):
                return request.full_url

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        return _Resp()


def _capture_open_headers(monkeypatch, fn, *args, **kwargs):
    import contextlib

    sink: list = []
    monkeypatch.setattr(
        http_util, "_build_opener", lambda *a, **k: _CapturingOpener(sink)
    )
    # http_get/http_post 拿到桩响应后可能因非 JSON 体抛错——只关心初始请求头，
    # 吞掉后续解析异常不影响判定点。
    with contextlib.suppress(Exception):
        fn(*args, **kwargs)
    assert sink, "咽喉必须经过 _build_opener().open(request)"
    return sink[0]


def _has_header(request, name: str) -> bool:
    lowered = {k.lower() for k in request.headers} | {
        k.lower() for k in request.unredirected_hdrs
    }
    return name.lower() in lowered


# -------------------------- ① 目标域校验 --------------------------

def test_cookie_stripped_for_foreign_host(monkeypatch) -> None:
    """B 站登录态发往 evil.com：初始请求绝不带 Cookie（降级未登录，不抛错）。"""
    request = _capture_open_headers(
        monkeypatch,
        http_util.http_get,
        "https://evil.example.com/?r=bilibili.com",
        cookie="SESSDATA=leak; bili_jct=leak",
    )
    assert not _has_header(request, "Cookie")


def test_cookie_kept_for_platform_host(monkeypatch) -> None:
    """B 站登录态发往 www.bilibili.com（子域）：正常带 Cookie，合法链路不砍。"""
    request = _capture_open_headers(
        monkeypatch,
        http_util.http_get,
        "https://www.bilibili.com/video/BV1xx411c7mD",
        cookie="SESSDATA=ok",
    )
    assert _has_header(request, "Cookie")


def test_cookie_kept_for_exact_domain(monkeypatch) -> None:
    request = _capture_open_headers(
        monkeypatch,
        http_util.http_get,
        "https://bilibili.com/x",
        cookie="SESSDATA=ok",
    )
    assert _has_header(request, "Cookie")


def test_post_json_strips_cookie_for_foreign_host(monkeypatch) -> None:
    request = _capture_open_headers(
        monkeypatch,
        http_util.http_post_json,
        "https://evil.example.com/api",
        {"a": 1},
        cookie="SUB=leak",
    )
    assert not _has_header(request, "Cookie")


def test_post_form_keeps_cookie_for_own_domain(monkeypatch) -> None:
    request = _capture_open_headers(
        monkeypatch,
        http_util.http_post_form,
        "https://weibo.com/ajax/x",
        {"a": 1},
        cookie="SUB=ok",
    )
    assert _has_header(request, "Cookie")


def test_steam_cookie_domain_added_to_single_source_of_truth() -> None:
    """steam 自读兜底的 Cookie host 必须进 PLATFORM_COOKIE_DOMAINS（唯一真身）。"""
    all_domains = {
        dom for domains, _keys in PLATFORM_COOKIE_DOMAINS.values() for dom in domains
    }
    joined = " ".join(all_domains)
    assert "steamcommunity.com" in joined
    assert "steampowered.com" in joined


def test_steam_cookie_stripped_for_foreign_host_kept_for_steam(monkeypatch) -> None:
    """steam 兜底 Cookie（普通 str，走联合域回退）：evil 剥、steam 留。"""
    foreign = _capture_open_headers(
        monkeypatch,
        http_util.http_get,
        "https://evil.example.com/?x=steamcommunity.com/app/123",
        cookie="steamLoginSecure=leak",
    )
    assert not _has_header(foreign, "Cookie")
    steam = _capture_open_headers(
        monkeypatch,
        http_util.http_get,
        "https://steamcommunity.com/app/123",
        cookie="steamLoginSecure=ok",
    )
    assert _has_header(steam, "Cookie")


def test_provider_cookie_carries_narrow_domains(monkeypatch, tmp_path) -> None:
    """provider 产出的 Cookie 头携带本平台域集；跨平台（B站票发给微博）被剥离。"""
    from pathlib import Path

    from plugins.bot_unified_runtime.domains.link_parse.parsers.cookies import (
        build_platform_cookie_provider,
    )

    netscape = (
        "# Netscape HTTP Cookie File\n"
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tsecretB\n"
    )
    path = Path(tmp_path) / "cookies.txt"
    path.write_text(netscape, encoding="utf-8")
    provider = build_platform_cookie_provider(path)
    bili_cookie = provider.cookie_header("bilibili")
    assert bili_cookie, "B 站 cookie 应加载"
    # 同一份 B 站票：发微博（在联合域内、但非 B 站窄域）→ 窄域校验剥离。
    foreign = _capture_open_headers(
        monkeypatch,
        http_util.http_get,
        "https://weibo.com/x",
        cookie=bili_cookie,
    )
    assert not _has_header(foreign, "Cookie"), "跨平台票必须按窄域剥离"
    home = _capture_open_headers(
        monkeypatch,
        http_util.http_get,
        "https://www.bilibili.com/x",
        cookie=bili_cookie,
    )
    assert _has_header(home, "Cookie")


# -------------------------- ② 跨 host 重定向剥凭证 --------------------------

def test_redirect_strips_cookie_on_host_change() -> None:
    """跨 host 30x：重定向后的请求不得带 Cookie/Authorization。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        _CredentialScrubbingRedirectHandler,
    )

    handler = _CredentialScrubbingRedirectHandler()
    req = urlrequest.Request(
        "https://www.bilibili.com/video/BV1",
        headers={"Cookie": "SESSDATA=x", "Authorization": "Bearer y"},
    )
    new = handler.redirect_request(
        req, None, 302, "Found", {}, "https://other.example.com/next"
    )
    assert new is not None
    assert not _has_header(new, "Cookie")
    assert not _has_header(new, "Authorization")


def test_redirect_keeps_cookie_on_same_host() -> None:
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        _CredentialScrubbingRedirectHandler,
    )

    handler = _CredentialScrubbingRedirectHandler()
    req = urlrequest.Request(
        "https://www.bilibili.com/a", headers={"Cookie": "SESSDATA=x"}
    )
    new = handler.redirect_request(
        req, None, 302, "Found", {}, "https://www.bilibili.com/b"
    )
    assert new is not None
    assert _has_header(new, "Cookie"), "同 host 重定向不得误剥登录态"


def test_default_opener_has_credential_strip_handler() -> None:
    """默认 opener 必须装配剥凭证 handler（覆盖所有走 http_get 的解析器）。"""
    opener = http_util._build_opener()
    classes = [type(h) for h in opener.handlers]
    assert any(
        getattr(c, "__name__", "") == "_CredentialScrubbingRedirectHandler"
        for c in classes
    )


def test_resolve_short_link_handler_also_strips() -> None:
    """短链逐跳复查 handler 必须继承剥凭证能力（形态一致，两跳同堵）。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        _CredentialScrubbingRedirectHandler,
        _GuardedShortLinkRedirectHandler,
    )

    assert issubclass(
        _GuardedShortLinkRedirectHandler, _CredentialScrubbingRedirectHandler
    )


# -------------------------- ③ 无锚定匹配收口 --------------------------

def _real_registry():
    return build_content_parser_registry(cookie_provider=None)["registry"]


def test_registry_rejects_platform_substring_in_query() -> None:
    """evil.com 的 query 里塞 steam 路径：steam 规则不得命中（归属校验）。"""
    evil = "https://evil.example.com/?r=https://steamcommunity.com/app/123"
    si = SourceInput(
        request_id="t",
        session_id="",
        capability_id="bot.content",
        raw_text=evil,
        urls=extract_http_urls(evil),
    )
    matches = _real_registry().match(si)
    assert all(m.parser_id != "steam" for m in matches), "无锚定子串不得冒充平台"


def test_registry_allows_real_steam_url() -> None:
    url = "https://steamcommunity.com/app/123"
    si = SourceInput(
        request_id="t",
        session_id="",
        capability_id="bot.content",
        raw_text=url,
        urls=extract_http_urls(url),
    )
    matches = _real_registry().match(si)
    assert any(m.parser_id == "steam" for m in matches)


@pytest.mark.parametrize(
    "short_url,expected",
    [
        ("https://b23.tv/abc123", "bilibili"),
        ("https://xhslink.com/xyz789", "xiaohongshu"),
        ("https://v.douyin.com/iAbCdEf/", "douyin"),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
    ],
)
def test_registry_keeps_legit_short_links(short_url: str, expected: str) -> None:
    """短链 host 合法归属：收口不得把 b23.tv/youtu.be 等砍掉（B 站 412 教训）。"""
    si = SourceInput(
        request_id="t",
        session_id="",
        capability_id="bot.content",
        raw_text=short_url,
        urls=extract_http_urls(short_url),
    )
    matches = _real_registry().match(si)
    assert any(m.parser_id == expected for m in matches), f"{short_url} 必须仍被识别"


def test_match_carries_allowed_hosts_for_candidate_filter() -> None:
    """ParserMatch 必须把规则平台域带到候选选择层（②的候选归属判据来源）。"""
    url = "https://steamcommunity.com/app/123"
    si = SourceInput(
        request_id="t",
        session_id="",
        capability_id="bot.content",
        raw_text=url,
        urls=extract_http_urls(url),
    )
    match = _real_registry().match(si)[0]
    assert match.allowed_hosts, "命中必须携带平台域集"


def test_candidate_selection_rejects_unattributed_url() -> None:
    """候选选择：只认 host 归属规则域的 URL；evil 候选必须被排除。"""
    from plugins.bot_unified_runtime.domains.link_parse.capabilities.content_parser import (
        select_candidate_url,
    )

    allowed = ("steamcommunity.com", "steampowered.com")
    # evil 在前、真 steam 在后：必须选真 steam，而非含子串的 evil。
    picked = select_candidate_url(
        [
            "https://evil.example.com/?r=steamcommunity.com/app/123",
            "https://steamcommunity.com/app/123",
        ],
        matched_keyword="steamcommunity.com/app/123",
        allowed_hosts=list(allowed),
    )
    assert picked == "https://steamcommunity.com/app/123"

    # 只有 evil：无合法候选 → 返回空串（走既有解析失败降级），绝不回退 evil。
    alone = select_candidate_url(
        ["https://evil.example.com/?r=steamcommunity.com/app/123"],
        matched_keyword="steamcommunity.com/app/123",
        allowed_hosts=list(allowed),
    )
    assert alone == ""


def test_synthetic_rule_without_allowed_hosts_keeps_old_behavior() -> None:
    """未声明 allowed_hosts 的合成规则（既有 SSRF 门夹具形态）不受收口影响。"""
    from plugins.bot_unified_runtime.domains.link_parse.support.registry import (
        ParserRegistry,
    )

    reg = ParserRegistry()
    reg.register(
        ParserRule(
            parser_id="generic",
            source_id="通用",
            url_patterns=[r"bilibili\.com/video"],
            priority=1,
        )
    )
    evil = "http://public.example.com/?v=bilibili.com/video/BV1xx411c7mD"
    si = SourceInput(
        request_id="t",
        session_id="",
        capability_id="bot.content",
        raw_text=evil,
        urls=extract_http_urls(evil),
    )
    matches = reg.match(si)
    assert any(m.parser_id == "generic" for m in matches)


def test_parser_ssrf_guard_entry_guard_still_blocks_intranet() -> None:
    """入口 SSRF 护栏（既有）与归属收口正交：内网字面量仍被 content_parser 拦下。"""
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
    from plugins.bot_unified_runtime.domains.link_parse.capabilities.content_parser import (
        build_content_capability,
    )

    calls: list[str] = []

    def _parse(url_arg: str):
        calls.append(url_arg)
        raise AssertionError("内网 URL 绝不该到达解析器")

    reg_obj = SimpleNamespace(
        match=lambda si: [
            SimpleNamespace(
                parser_id="generic",
                source_id="通用",
                matched_keyword="xiaohongshu.com/explore/abc",
                priority=1,
                keyword_length=25,
                allowed_hosts=[],
            )
        ]
    )
    capability = build_content_capability(
        SimpleNamespace(bot_media_analyze_enabled=False),
        registry={"registry": reg_obj, "parsers": {"generic": _parse}},
    )
    msg = IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text="http://127.0.0.1:8742/?u=xiaohongshu.com/explore/abc",
    )
    result = capability(msg, None)
    assert calls == []
    assert "ssrf_guard_rejected" in result.audit_tags
