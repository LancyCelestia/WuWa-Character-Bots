"""链接解析链 SSRF 护栏回归（安全审计 I-2 修复，2026-09-14）。

覆盖三件事：
1. 入口护栏（content_parser 分发前）：内网/保留网段/localhost/内网域名
   一律拒绝且走既有「解析失败」降级路径（群静默/私聊人话提示），
   解析函数绝不收到内网 URL；
2. 公网 URL 正常放行（mock DNS），DNS 解析失败放行策略锁死
   （纯代理可达平台不被本机 DNS 误伤）；
3. og 兜底落点复查（platforms_generic._og_scrape）：重定向落到内网时
   在解析/回显内容之前抛 ParseHttpError（mock http_get_text 的 final url，
   等价于 geturl 落点）。全离线，无真实网络。
"""

from __future__ import annotations

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
from plugins.bot_unified_runtime.contracts.media import (
    ParserRule,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers import platforms_generic
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
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
    """localhost 黑名单主机名：不查 DNS 直接拒绝（NapCat 3001 场景）。"""
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


def test_entry_guard_allows_when_dns_unresolvable(monkeypatch) -> None:
    """DNS 解析失败放行（锁死策略）：纯代理可达平台不被本机 DNS 误伤。"""
    _patch_dns_failure(monkeypatch)
    calls: list[str] = []

    def parse_fn(url_arg: str):
        calls.append(url_arg)
        return _item()

    url = "https://proxy-only.example/video/1"
    result = _run(url, r"proxy-only\.example", parse_fn)
    assert calls == [url]
    assert "ssrf_guard_rejected" not in result.audit_tags


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
    乱码不进卡（结构性防线，此处锁行为）。"""

    def fake_get_text(url, **kwargs):
        return "https://public.example.com/bin", "\x00\x01binary garbage \xff\xfe"

    monkeypatch.setattr(platforms_generic, "http_get_text", fake_get_text)
    with pytest.raises(ParseHttpError, match="no title"):
        platforms_generic._og_scrape(
            "https://public.example.com/bin",
            platform="generic",
            item_kind="post",
        )
