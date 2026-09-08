"""萌娘百科查询能力回归：问句归一化、可信主词条判定、降级决策、路由不误触。

全部离线：网络层用假 fetch 注入；路由用 SimpleNamespace 配置直跑注册表。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.moegirl import (
    build_moegirl_capability,
    extract_moegirl_query,
    is_moegirl_command,
    normalize_entity_question,
    question_lookup,
)
from plugins.bot_unified_runtime.runtime.base_router import RouteKind
from plugins.bot_unified_runtime.sources.moegirl import (
    MoegirlHit,
    parse_search_payload,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError

# ---------------------------------------------------------------- 问句归一化


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("初音未来是谁？", "初音未来"),
        ("守岸人是谁", "守岸人"),
        ("洛天依是谁呀", "洛天依"),
        ("初音未来是什么", "初音未来"),
        ("『洛天依』是谁？", "洛天依"),
        ("介绍一下洛天依", "洛天依"),
        ("洛天依的资料", "洛天依"),
        ("请问初音未来是谁", "初音未来"),
        ("VOCALOID 是什么？", "VOCALOID"),
    ],
)
def test_normalize_entity_question_extracts_entity(raw, expected):
    assert normalize_entity_question(raw) == expected


# ---------------------------------------------------------------- 镜像语义


def test_search_empty_on_primary_skips_mirror(monkeypatch):
    """主站可达但查无结果 = 权威回答：不追打镜像，未命中快速降级。"""
    import plugins.bot_unified_runtime.sources.moegirl as src

    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return {"query": {"pages": {}}}

    monkeypatch.setattr(src, "_cached_get_json", fake_get)
    assert src.moegirl_search("冷门词条qqx9z") == []
    assert len(calls) == 2  # generator=search + opensearch，仅主站
    assert all("zh.moegirl" in url for url in calls)


def test_search_mirror_used_on_primary_failure(monkeypatch):
    """主站网络失败才回退镜像域名。"""
    import plugins.bot_unified_runtime.sources.moegirl as src

    mirror_payload = {
        "query": {
            "pageids": ["1"],
            "pages": [
                {
                    "pageid": 1,
                    "title": "洛天依",
                    "extract": "虚拟歌手。",
                    "fullurl": "https://mzh.moegirl.org.cn/洛天依",
                }
            ],
        }
    }

    def fake_get(url, **kwargs):
        # 注意 mzh.moegirl 同样包含子串 zh.moegirl，必须按域名起点匹配。
        if "://zh.moegirl" in url:
            raise ParseHttpError("primary unreachable")
        return mirror_payload

    monkeypatch.setattr(src, "_cached_get_json", fake_get)
    hits = src.moegirl_search("洛天依")
    assert len(hits) == 1
    assert hits[0].title == "洛天依"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "？？？",
        "你是谁",
        "你是什么东西",
        "我是谁",
        "他是谁？",
        "谁",
        "来首歌",
        "维基 鸣潮",
        "/bot status",
        "看一下这个 https://example.com",
        "今天天气不错",
        "a" * 31,
    ],
)
def test_normalize_entity_question_rejects_non_entity(raw):
    assert normalize_entity_question(raw) is None


# ---------------------------------------------------------------- 显式指令


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("萌娘百科 洛天依", "洛天依"),
        ("萌娘百科洛天依", "洛天依"),
        ("萌百 洛天依", "洛天依"),
        ("MOEGIRL miku", "miku"),
        ("/萌娘百科 初音未来", "初音未来"),
    ],
)
def test_extract_moegirl_query(raw, expected):
    assert is_moegirl_command(raw)
    assert extract_moegirl_query(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["萌娘百科", "萌百", "维基 洛天依", "洛天依是谁", ""],
)
def test_is_moegirl_command_negative(raw):
    assert not is_moegirl_command(raw)


# ---------------------------------------------------------------- API 载荷解析


def _generator_payload():
    return {
        "query": {
            "pageids": ["42", "7"],
            "pages": [
                {
                    "pageid": 7,
                    "title": "VOCALOID",
                    "extract": "语音合成引擎。",
                    "fullurl": "https://zh.moegirl.org.cn/VOCALOID",
                },
                {
                    "pageid": 42,
                    "title": "洛天依",
                    "extract": "基于VOCALOID的虚拟歌手。",
                    "fullurl": "https://zh.moegirl.org.cn/洛天依",
                },
            ],
        }
    }


def test_parse_search_payload_preserves_relevance_order():
    hits = parse_search_payload(_generator_payload())
    assert [hit.title for hit in hits] == ["洛天依", "VOCALOID"]
    assert hits[0].url.endswith("洛天依")
    assert "虚拟歌手" in hits[0].snippet


def test_parse_search_payload_opensearch_fallback():
    payload = [
        "miku",
        ["初音未来"],
        ["虚拟歌姬"],
        ["https://zh.moegirl.org.cn/初音未来"],
    ]
    hits = parse_search_payload(payload)
    assert len(hits) == 1
    assert hits[0].title == "初音未来"
    assert hits[0].snippet == "虚拟歌姬"


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"query": {}}, {"error": {"code": "readonly"}}, [1, 2], []],
)
def test_parse_search_payload_garbage_returns_empty(payload):
    assert parse_search_payload(payload) == []


# ---------------------------------------------------------------- 可信主词条判定


def _hit(title: str, snippet: str = "简介", url: str = "https://zh.moegirl.org.cn/x"):
    return MoegirlHit(title=title, snippet=snippet, url=url)


def test_question_lookup_exact_hit_fetches_summary():
    calls: list[str] = []

    def fake_search(query, **kwargs):
        calls.append(f"search:{query}")
        return [_hit("洛天依"), _hit("VOCALOID")]

    def fake_page(title, **kwargs):
        calls.append(f"page:{title}")
        return _hit("洛天依", "洛天依是基于VOCALOID引擎的虚拟歌手。", "https://zh.moegirl.org.cn/洛天依")

    outcome = question_lookup(
        "洛天依是谁", search_fn=fake_search, page_fn=fake_page
    )
    assert outcome.status == "hit"
    assert "洛天依" in outcome.body
    assert "虚拟歌手" in outcome.body
    assert "https://zh.moegirl.org.cn/洛天依" in outcome.body
    assert calls == ["search:洛天依", "page:洛天依"]


def test_question_lookup_unique_candidate_hits_without_page():
    def fake_search(query, **kwargs):
        return [_hit("初音未来", "虚拟歌姬。")]

    outcome = question_lookup("初音未来是谁", search_fn=fake_search, page_fn=None)
    assert outcome.status == "hit"
    assert "初音未来" in outcome.body


def test_question_lookup_ambiguous_lists_candidates():
    def fake_search(query, **kwargs):
        return [_hit("东方Project", "同人企划。"), _hit("东方Project/音乐", "音乐条目。")]

    outcome = question_lookup("东方是谁", search_fn=fake_search, page_fn=None)
    assert outcome.status == "hit"
    assert "东方Project" in outcome.body
    assert "同人企划" in outcome.body


@pytest.mark.parametrize(
    ("hits", "exc"),
    [
        ([], None),
        (None, ParseHttpError("boom")),
    ],
)
def test_question_lookup_miss_or_error_degrades(hits, exc):
    def fake_search(query, **kwargs):
        if exc is not None:
            raise exc
        return hits

    outcome = question_lookup("冷门角色是谁", search_fn=fake_search, page_fn=None)
    assert outcome.status == "degrade"
    assert outcome.body == ""


def test_question_lookup_page_miss_falls_back_to_search_snippet():
    """主词条页摘要拉取失败（网络/缺失）→ 回退搜索自带摘要，不降级。"""

    def fake_search(query, **kwargs):
        return [_hit("洛天依", "搜索摘要：虚拟歌手。"), _hit("VOCALOID")]

    def fake_page(title, **kwargs):
        raise ParseHttpError("timeout")

    outcome = question_lookup("洛天依是谁", search_fn=fake_search, page_fn=fake_page)
    assert outcome.status == "hit"
    assert "洛天依" in outcome.body
    assert "虚拟歌手" in outcome.body


# ---------------------------------------------------------------- 路由


def _router_config(**overrides):
    base = {
        "bot_moegirl_enabled": True,
        "bot_moegirl_question_enabled": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_router_question_routes_to_moegirl_question():
    from plugins.bot_unified_runtime.runtime.base_router import (
        RouteKind,
        classify_message_route,
    )

    decision = classify_message_route("初音未来是谁", config=_router_config())
    assert decision.kind is RouteKind.MOEGIRL_QUESTION
    assert decision.capability_id == "bot.moegirl"


def test_router_explicit_command_routes_to_moegirl():
    from plugins.bot_unified_runtime.runtime.base_router import (
        RouteKind,
        classify_message_route,
    )

    decision = classify_message_route("萌娘百科 洛天依", config=_router_config())
    assert decision.kind is RouteKind.MOEGIRL
    assert decision.priority == 41


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("你是谁", RouteKind.CHAT),
        # 「来首歌」由自然语言命令层归一化成点歌意图（既有行为）。
        ("来首歌 周杰伦的歌", RouteKind.NATURAL_COMMAND),
        ("维基 鸣潮", RouteKind.WIKI),
        ("今天天气怎么样", RouteKind.CHAT),
        ("介绍一下你自己", RouteKind.CHAT),
    ],
)
def test_router_no_hijack(raw, expected):
    from plugins.bot_unified_runtime.runtime.base_router import (
        classify_message_route,
    )

    assert classify_message_route(raw, config=_router_config()).kind is expected


def test_router_disabled_flags():
    from plugins.bot_unified_runtime.runtime.base_router import (
        RouteKind,
        classify_message_route,
    )

    off_question = _router_config(bot_moegirl_question_enabled=False)
    assert (
        classify_message_route("初音未来是谁", config=off_question).kind
        is RouteKind.CHAT
    )
    off_all = _router_config(bot_moegirl_enabled=False)
    assert (
        classify_message_route("萌娘百科 洛天依", config=off_all).kind
        is RouteKind.CHAT
    )


# ---------------------------------------------------------------- 显式指令能力


class _FakeIncoming(SimpleNamespace):
    pass


def _message(text: str):
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    return IncomingMessage(
        request_id="req-1",
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id="private:100",
        session_type=SessionType.PRIVATE,
        sender_id="100",
        plain_text=text,
    )


def _decision():
    from plugins.bot_unified_runtime.contracts import BotDecision, SessionType

    return BotDecision(
        request_id="req-1",
        should_respond=True,
        mode="command",
        trigger="command",
        capability_id="bot.moegirl",
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )


def test_capability_explicit_found(monkeypatch):
    import plugins.bot_unified_runtime.capabilities.moegirl as cap

    monkeypatch.setattr(
        cap,
        "moegirl_page_summary",
        lambda title, **kw: _hit(title, "虚拟歌手介绍。", "https://zh.moegirl.org.cn/洛天依"),
    )
    monkeypatch.setattr(
        cap,
        "moegirl_search",
        lambda query, **kw: [_hit("洛天依")],
    )
    config = SimpleNamespace(bot_moegirl_enabled=True)
    capability = build_moegirl_capability(config)
    result = capability(_message("萌娘百科 洛天依"), _decision())
    assert result.kind == "text"
    assert "洛天依" in result.body
    assert "虚拟歌手介绍" in result.body


def test_capability_explicit_not_found(monkeypatch):
    import plugins.bot_unified_runtime.capabilities.moegirl as cap

    monkeypatch.setattr(cap, "moegirl_page_summary", lambda title, **kw: None)
    monkeypatch.setattr(cap, "moegirl_search", lambda query, **kw: [])
    config = SimpleNamespace(bot_moegirl_enabled=True)
    capability = build_moegirl_capability(config)
    result = capability(_message("萌娘百科 不存在的词条"), _decision())
    assert "没有找到" in result.body
    assert "不存在的词条" in result.body


def test_capability_usage_hint(monkeypatch):
    import plugins.bot_unified_runtime.capabilities.moegirl as cap

    monkeypatch.setattr(cap, "moegirl_page_summary", lambda title, **kw: None)
    monkeypatch.setattr(cap, "moegirl_search", lambda query, **kw: [])
    config = SimpleNamespace(bot_moegirl_enabled=True)
    capability = build_moegirl_capability(config)
    result = capability(_message("萌娘百科"), _decision())
    assert "用法" in result.body
