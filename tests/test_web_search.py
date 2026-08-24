"""问题意图分层判定（v2，不斩断联网权限）+ 联网检索提供器测试。"""

import asyncio
import io
import json

import httpx
import pytest

from plugins.bot_unified_runtime.runtime.question_intent import (
    QuestionIntent,
    classify_question_intent,
)
from plugins.bot_unified_runtime.sources import mcp_web_search_server as mcp
from plugins.bot_unified_runtime.sources import web_search as ws
from plugins.bot_unified_runtime.sources.web_search import (
    DuckDuckGoWebSearchProvider,
    WebSearchHit,
    _extract_bing_hits,
    _extract_ddg_hits,
)


def test_domain_entity_questions_use_knowledge_first_with_web_fallback():
    # 领域实体问句：知识库优先，但保留联网回退（不斩断权限）。
    for text in [
        "鸣潮是什么",
        "今州是什么",
        "拉古那是什么",
        "七丘是什么",
        "漂泊者是谁",
        "艾弥斯是谁",
        "洛斯拉是谁",
    ]:
        decision = classify_question_intent(text)
        assert decision.intent is QuestionIntent.KNOWLEDGE_FIRST, (text, decision)
        assert decision.allow_web_fallback is True, text


def test_real_world_entity_questions_search():
    # 同一语法但实体不是领域词：百科联网。
    for text in [
        "习近平是谁",
        "普京是谁",
        "陈睿是谁",
        "库洛游戏是个什么样的公司",
    ]:
        decision = classify_question_intent(text)
        assert decision.intent is QuestionIntent.WEB_SEARCH, (text, decision)


def test_temporal_questions_search_even_with_domain_terms():
    for text in [
        "鸣潮今天更新了什么",
        "鸣潮2.0什么时候上线",
        "守岸人卡池什么时候复刻",
        "你知道鸣潮演唱会吗",
        "你知道库洛所在地吗",
    ]:
        decision = classify_question_intent(text)
        assert decision.intent is QuestionIntent.WEB_SEARCH, (text, decision)


def test_real_world_signals_never_blocked():
    for text in [
        "今州房价多少",
        "守岸人手办多少钱",
        "库洛游戏在哪里",
    ]:
        assert classify_question_intent(text).intent is QuestionIntent.WEB_SEARCH, text


def test_self_chat_does_not_search():
    for text in ["你最近怎么样", "守岸人今天心情怎么样", "岸宝在吗", "今天有点累，陪我说说话"]:
        decision = classify_question_intent(text)
        assert decision.intent is not QuestionIntent.WEB_SEARCH, text


def test_general_knowledge_questions_now_search():
    # 用户要求大部分消息联网：科普/科学/方法类问句默认联网。
    for text in [
        "为什么天空是蓝的",
        "Python 怎么安装",
        "什么是光合作用",
        "量子力学是什么",
    ]:
        assert classify_question_intent(text).intent is QuestionIntent.WEB_SEARCH, text


def test_plain_chat_still_neutral():
    for text in ["今天天气不错", "播放量好高", "今天有点累，陪我说说话"]:
        assert classify_question_intent(text).intent is QuestionIntent.NEUTRAL, text


def test_real_world_categories_always_search():
    for text in ["当前国际局势怎么样", "中美贸易战是怎么回事", "芯片制造原理是什么"]:
        assert classify_question_intent(text).intent is QuestionIntent.WEB_SEARCH, text


def test_ddg_extract_hits_from_html():
    html = (
        '<div class="result"><a class="result__a" href="https://example.com/a">'
        "标题A</a><a class=\"result__snippet\">摘要A</a></div>"
    )
    hits = _extract_ddg_hits(html, max_results=2)
    assert hits and hits[0].title == "标题A"
    assert hits[0].source_domain == "example.com"


def test_bing_extract_hits_from_html():
    html = (
        '<li class="b_algo"><h2><a href="https://example.org/b">标题B</a></h2>'
        "<p>摘要B</p></li>"
    )
    hits = _extract_bing_hits(html, max_results=2)
    assert hits and hits[0].title == "标题B"
    assert hits[0].snippet == "摘要B"


def test_provider_search_returns_empty_on_network_error(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(ws, "_build_sync_client", boom)
    provider = DuckDuckGoWebSearchProvider(timeout_seconds=1.0)
    assert provider.search("今天的新闻", max_results=3) == []


def test_filter_drops_dictionary_junk_and_keeps_relevant():
    from plugins.bot_unified_runtime.sources.web_search import _filter_relevant

    junk = WebSearchHit(
        title="库（汉语汉字）_百度百科",
        snippet="本义为收藏兵车及其他武器的处所。",
        url="https://baike.baidu.com/item/库",
        source_domain="baike.baidu.com",
    )
    relevant = WebSearchHit(
        title="库街区 - 库洛游戏官方社区",
        snippet="《库街区》是库洛游戏官方社区APP。",
        url="https://www.kurobbs.com",
        source_domain="www.kurobbs.com",
    )
    hits = _filter_relevant([junk, relevant], "库洛游戏 公司 百科")
    assert len(hits) == 1
    assert hits[0].url == relevant.url


def test_fetch_page_text_returns_empty_for_bad_url(monkeypatch):
    from plugins.bot_unified_runtime.sources.web_search import fetch_page_text

    def boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(ws, "_build_sync_client", boom)
    assert fetch_page_text("https://example.com/x", timeout_seconds=1.0) == ""


def test_web_hits_sorted_by_preferred_encyclopedia():
    from plugins.bot_unified_runtime.capabilities.chat import _sort_web_hits
    from plugins.bot_unified_runtime.sources.web_search import WebSearchHit

    hits = [
        WebSearchHit(title="百度", snippet="", url="https://baike.baidu.com/x", source_domain="baike.baidu.com"),
        WebSearchHit(title="维基", snippet="", url="https://zh.wikipedia.org/y", source_domain="zh.wikipedia.org"),
        WebSearchHit(title="萌娘", snippet="", url="https://zh.moegirl.org.cn/z", source_domain="zh.moegirl.org.cn"),
    ]
    ordered = _sort_web_hits(hits)
    assert ordered[0].source_domain == "zh.moegirl.org.cn"
    assert ordered[1].source_domain == "zh.wikipedia.org"
    assert ordered[2].source_domain == "baike.baidu.com"


# ---------- httpx 化：同步 / 异步 / 多查询 ----------


def test_sync_provider_uses_injected_httpx_client(monkeypatch):
    """同步路径走 httpx.Client：注入 MockTransport 返回正确命中。"""

    def handler(request):
        assert request.url.host == "html.duckduckgo.com"
        html = (
            '<div class="result"><a class="result__a" '
            'href="https://baike.baidu.com/item/%E5%AE%88%E5%B2%B8%E4%BA%BA">'
            "守岸人 - 百度百科</a>"
            '<a class="result__snippet">《鸣潮》中的角色。</a></div>'
        )
        return httpx.Response(200, text=html)

    monkeypatch.setattr(
        ws,
        "_build_sync_client",
        lambda proxy, timeout: httpx.Client(
            transport=httpx.MockTransport(handler)
        ),
    )
    provider = DuckDuckGoWebSearchProvider(timeout_seconds=1.0)
    hits = provider.search("守岸人", max_results=2)
    assert len(hits) == 1
    assert hits[0].title == "守岸人 - 百度百科"
    assert hits[0].source_domain == "baike.baidu.com"


def test_httpx_clients_accept_single_proxy_value():
    """httpx 0.28 使用单值 proxy 参数：带代理构建客户端必须成功。"""
    client = ws._build_sync_client("http://127.0.0.1:7890", 3.0)
    try:
        assert isinstance(client, httpx.Client)
        assert any(getattr(key, "pattern", "") == "all://" for key in client._mounts)
    finally:
        client.close()
    assert ws._proxy_value("") is None
    assert ws._proxy_value("  http://127.0.0.1:7890  ") == "http://127.0.0.1:7890"


@pytest.mark.asyncio
async def test_async_client_accepts_single_proxy_value():
    client = ws._build_async_client("http://127.0.0.1:7890", 3.0)
    try:
        assert isinstance(client, httpx.AsyncClient)
        assert any(getattr(key, "pattern", "") == "all://" for key in client._mounts)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_async_provider_uses_injected_transport(monkeypatch):
    """异步 provider 走 httpx.AsyncClient：注入假 transport 返回正确命中。"""

    def handler(request):
        assert request.url.host == "html.duckduckgo.com"
        html = (
            '<div class="result"><a class="result__a" '
            'href="https://zh.moegirl.org.cn/%E5%AE%88%E5%B2%B8%E4%BA%BA">'
            "守岸人 &amp; 鸣潮 &nbsp; 角色</a>"
            '<a class="result__snippet">《鸣潮》中的角色\n\n简介。</a></div>'
        )
        return httpx.Response(200, text=html)

    monkeypatch.setattr(
        ws,
        "_build_async_client",
        lambda proxy, timeout: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ),
    )
    provider = DuckDuckGoWebSearchProvider(timeout_seconds=1.0)
    hits = await provider.search_async("守岸人", max_results=2)
    assert len(hits) == 1
    assert hits[0].title == "守岸人 & 鸣潮 角色"
    assert hits[0].snippet == "《鸣潮》中的角色 简介。"
    assert hits[0].source_domain == "zh.moegirl.org.cn"


@pytest.mark.asyncio
async def test_search_multi_async_runs_concurrently_merges_and_dedupes(monkeypatch):
    """多查询并发执行；DDG 优先、Bing 兜底；按 URL 去重合并且顺序确定。"""
    active = 0
    peak = 0
    request_log: list[str] = []

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        request_log.append(request.url.host)
        try:
            if request.url.host == "html.duckduckgo.com":
                await asyncio.sleep(0.05)
                query = request.url.params["q"]
                if query == "查询A":
                    return httpx.Response(
                        200,
                        text=(
                            '<div class="result"><a class="result__a" '
                            'href="https://a.example/one">A1</a>'
                            '<a class="result__snippet">sA1</a></div>'
                            '<div class="result"><a class="result__a" '
                            'href="https://a.example/two">A2</a>'
                            '<a class="result__snippet">sA2</a></div>'
                        ),
                    )
                return httpx.Response(200, text="<html></html>")
            if request.url.host == "www.bing.com":
                await asyncio.sleep(0.01)
                return httpx.Response(
                    200,
                    text=(
                        '<li class="b_algo"><h2><a href="https://b.example/x">B1'
                        "</a></h2><p>sB1</p></li>"
                        '<li class="b_algo"><h2><a href="https://a.example/one/">'
                        "A1 重复</a></h2><p>dup</p></li>"
                    ),
                )
            return httpx.Response(200, text="")
        finally:
            active -= 1

    monkeypatch.setattr(
        ws,
        "_build_async_client",
        lambda proxy, timeout: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ),
    )
    hits = await ws.search_multi_async(["查询A", "查询B"], max_results=3)
    # 两个查询同时在途，说明确实并发而非串行等待。
    assert peak >= 2
    assert [hit.url for hit in hits] == [
        "https://a.example/one",
        "https://a.example/two",
        "https://b.example/x",
    ]
    # 查询A命中 DDG 不再请求 Bing；查询B的 DDG 为空后由 Bing 兜底。
    assert request_log.count("html.duckduckgo.com") == 2
    assert request_log.count("www.bing.com") == 1


# ---------- 搜索质量微调 ----------


def test_extractors_normalize_entities_and_whitespace():
    ddg_html = (
        '<div class="result"><a class="result__a" href="https://example.com/x">'
        "  鸣潮 &nbsp; 守岸人 &#38; 角色</a>"
        '<a class="result__snippet">\n\n 摘要 &amp; 内容\t </a></div>'
    )
    ddg_hit = _extract_ddg_hits(ddg_html, max_results=1)[0]
    assert ddg_hit.title == "鸣潮 守岸人 & 角色"
    assert ddg_hit.snippet == "摘要 & 内容"

    bing_html = (
        '<li class="b_algo"><h2><a href="https://example.org/y"> 维基&nbsp;百科 </a></h2>'
        "<p> 介绍 &gt; 历史 </p></li>"
    )
    bing_hit = _extract_bing_hits(bing_html, max_results=1)[0]
    assert bing_hit.title == "维基 百科"
    assert bing_hit.snippet == "介绍 > 历史"


def test_filter_relevant_prefers_encyclopedia_domains():
    from plugins.bot_unified_runtime.sources.web_search import _filter_relevant

    hits = [
        WebSearchHit(
            title="普通博客",
            snippet="x",
            url="https://blog.example.com/1",
            source_domain="blog.example.com",
        ),
        WebSearchHit(
            title="百度百科",
            snippet="x",
            url="https://baike.baidu.com/1",
            source_domain="baike.baidu.com",
        ),
        WebSearchHit(
            title="维基",
            snippet="x",
            url="https://zh.wikipedia.org/1",
            source_domain="zh.wikipedia.org",
        ),
        WebSearchHit(
            title="萌娘",
            snippet="x",
            url="https://zh.moegirl.org.cn/1",
            source_domain="zh.moegirl.org.cn",
        ),
    ]
    ordered = _filter_relevant(hits, "守岸人 百科")
    assert [hit.source_domain for hit in ordered] == [
        "zh.moegirl.org.cn",
        "zh.wikipedia.org",
        "baike.baidu.com",
        "blog.example.com",
    ]


# ---------- stdio MCP JSON-RPC 2.0 ----------


@pytest.mark.asyncio
async def test_mcp_initialize_and_notification_roundtrip():
    out = io.StringIO()
    await mcp.handle_request(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            },
            ensure_ascii=False,
        ),
        out,
    )
    # notifications/initialized 是通知：不写任何响应。
    await mcp.handle_request(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), out
    )
    lines = out.getvalue().splitlines()
    assert len(lines) == 1
    response = json.loads(lines[0])
    assert response["id"] == 1
    assert response["result"]["protocolVersion"] == "2024-11-05"
    assert response["result"]["capabilities"] == {}
    assert response["result"]["serverInfo"]["name"] == "shorekeeper-web-search"


@pytest.mark.asyncio
async def test_mcp_tools_list_roundtrip():
    out = io.StringIO()
    await mcp.handle_request(
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}), out
    )
    response = json.loads(out.getvalue())
    assert response["id"] == 2
    tools = response["result"]["tools"]
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "web_search"
    assert tool["inputSchema"] == {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "要检索的查询词"},
            "max_results": {"type": "integer", "default": 6},
        },
        "required": ["query"],
    }


@pytest.mark.asyncio
async def test_mcp_outputs_utf8_bytes_when_stdout_has_buffer():
    """真实进程 stdout 需显式写 UTF-8 字节，不受 Windows 控制台代码页影响。"""

    class BufferedStdout:
        def __init__(self):
            self.buffer = io.BytesIO()

    stdout = BufferedStdout()
    await mcp.handle_request(
        json.dumps(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
            ensure_ascii=False,
        ),
        stdout,  # type: ignore[arg-type]
    )
    raw = stdout.buffer.getvalue()
    decoded = raw.decode("utf-8")
    assert decoded.startswith('{"jsonrpc": "2.0", "id": 4')
    assert "要检索的查询词" in decoded


@pytest.mark.asyncio
async def test_mcp_tools_call_roundtrip(monkeypatch):
    async def fake_search(query, *, max_results=3, **kwargs):
        assert query == "鸣潮 守岸人"
        assert max_results == 2
        return [
            WebSearchHit(
                title="守岸人 - 萌娘百科",
                snippet="《鸣潮》中的共鸣者。",
                url="https://zh.moegirl.org.cn/守岸人",
                source_domain="zh.moegirl.org.cn",
            )
        ]

    monkeypatch.setattr(mcp, "search_async", fake_search)
    out = io.StringIO()
    await mcp.handle_request(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "web_search",
                    "arguments": {"query": "鸣潮 守岸人", "max_results": 2},
                },
            },
            ensure_ascii=False,
        ),
        out,
    )
    response = json.loads(out.getvalue())
    assert response["id"] == 3
    result = response["result"]
    assert result["isError"] is False
    content = result["content"][0]
    assert content["type"] == "text"
    payload = json.loads(content["text"])
    assert payload["hits"][0]["url"] == "https://zh.moegirl.org.cn/守岸人"
    assert payload["hits"][0]["source_domain"] == "zh.moegirl.org.cn"


@pytest.mark.asyncio
async def test_mcp_parse_error_and_unknown_method():
    out = io.StringIO()
    await mcp.handle_request("这不是 JSON", out)
    await mcp.handle_request(
        json.dumps({"jsonrpc": "2.0", "id": 9, "method": "no/such"}), out
    )
    lines = out.getvalue().splitlines()
    parse_error = json.loads(lines[0])
    assert parse_error["id"] is None
    assert parse_error["error"]["code"] == -32700
    unknown = json.loads(lines[1])
    assert unknown["id"] == 9
    assert unknown["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_mcp_accepts_content_length_framing():
    """run_stdio 兼容 Content-Length 帧格式，并可注入 stdin/stdout 往返。"""
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}, ensure_ascii=False
    ).encode("utf-8")
    frame = b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload
    stdin = io.BytesIO(frame)
    out = io.StringIO()
    await mcp.run_stdio(stdin, out)
    response = json.loads(out.getvalue())
    assert response["id"] == 7
    assert response["result"]["tools"][0]["name"] == "web_search"