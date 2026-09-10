"""管线检视第二轮 chat 域回归（B-1 / B-3 / B-6 / B-8 / B-9）。

覆盖：
- B-1：视频阶段 deadline 与请求总预算协调（剩余预算 − LLM 保留 60s，
  下限 30s，预算未启用返回 None）；
- B-3：多 query 并发检索——真实并发（Barrier 证明）、结果顺序确定、
  单查询失败不阻断、硬顶截断；
- B-6：MCP 工具 schema 探测失败的负缓存短 TTL（60s 到期重探），结构性
  缺失仍永久缓存，clear 重置；
- B-8：工具循环打满且末轮空文本时追加一次无工具收尾轮；
- B-9：引号审计标签的语义（strip 前后文本比较）。
全部离线：provider 为假实现，不发真实网络请求。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.capabilities.chat as chat_module
from plugins.bot_unified_runtime.capabilities.chat import (
    _MCP_NEGATIVE_CACHE_TTL_SECONDS,
    _generate_with_tool_loop,
    _search_queries_concurrently,
    _video_deadline_seconds,
    clear_mcp_tools_schema_cache,
    strip_outer_speech_quotes,
)
from plugins.bot_unified_runtime.contracts import WebSearchHit
from plugins.bot_unified_runtime.llm.providers import LLMReply

# ==================== B-1：视频 deadline 与请求预算协调 ====================


class _FakeBudget:
    def __init__(self, *, enabled: bool, remaining: float) -> None:
        self.enabled = enabled
        self._remaining = remaining

    def remaining_seconds(self) -> float:
        return self._remaining


def test_video_deadline_none_when_budget_disabled() -> None:
    assert _video_deadline_seconds(None) is None
    assert _video_deadline_seconds(_FakeBudget(enabled=False, remaining=100.0)) is None


def test_video_deadline_reserves_llm_window_with_floor() -> None:
    # 剩余 200s → 视频 140s（给 LLM 留 60s）。
    assert _video_deadline_seconds(_FakeBudget(enabled=True, remaining=200.0)) == 140.0
    # 剩余不足时钳到 30s 下限（至少能抽基本帧）。
    assert _video_deadline_seconds(_FakeBudget(enabled=True, remaining=50.0)) == 30.0


def test_video_deadline_none_when_budget_exhausted() -> None:
    assert _video_deadline_seconds(_FakeBudget(enabled=True, remaining=0.0)) is None


# ==================== B-3：多 query 并发检索 ====================


class _BarrierSearchProvider:
    """所有 query 必须同时在 search 内部汇聚（Barrier），否则超时抛错——
    串行实现下该 provider 必然失败，从行为上锁定「真并发」。"""

    def __init__(self, barrier: threading.Barrier, calls: list[str]) -> None:
        self._barrier = barrier
        self.calls = calls

    def search(self, query: str, max_results: int = 3) -> list[WebSearchHit]:
        self.calls.append(query)
        self._barrier.wait(timeout=5)
        return [
            WebSearchHit(
                title=f"{query} 的结果",
                snippet="s",
                url=f"https://example.test/{query}",
                source_domain="example.test",
            )
        ]


def test_search_queries_run_concurrently_and_keep_order() -> None:
    barrier = threading.Barrier(3)
    calls: list[str] = []
    provider = _BarrierSearchProvider(barrier, calls)
    error_kinds: set[str] = set()

    hits = _search_queries_concurrently(
        provider,
        ["q1", "q2", "q3"],
        per_query=3,
        hard_total_cap=10,
        error_kinds=error_kinds,
    )

    assert [hit.title for hit in hits] == ["q1 的结果", "q2 的结果", "q3 的结果"]
    assert error_kinds == set()


class _MixedSearchProvider:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def search(self, query: str, max_results: int = 3) -> list[WebSearchHit]:
        self.calls.append(query)
        if query == "bad":
            raise RuntimeError("search exploded")
        # 同 URL 同标题：命中去重键 (url, title[:24])，只保留首个查询的结果。
        return [
            WebSearchHit(
                title="shared 结果",
                snippet="s",
                url="https://example.test/shared",
                source_domain="example.test",
            )
        ]


def test_search_query_failure_skipped_and_results_deduped() -> None:
    calls: list[str] = []
    provider = _MixedSearchProvider(calls)
    error_kinds: set[str] = set()

    hits = _search_queries_concurrently(
        provider,
        ["ok1", "bad", "ok2"],
        per_query=3,
        hard_total_cap=10,
        error_kinds=error_kinds,
    )

    # 失败查询跳过不阻断；两个成功查询命中同一去重键，只保留按序首个。
    assert [hit.title for hit in hits] == ["shared 结果"]
    assert any(kind.startswith("provider:RuntimeError") for kind in error_kinds)


def test_search_hard_total_cap_stops_merge() -> None:
    calls: list[str] = []
    provider = _MixedSearchProvider(calls)
    error_kinds: set[str] = set()

    hits = _search_queries_concurrently(
        provider,
        ["ok1", "ok2"],
        per_query=3,
        hard_total_cap=1,
        error_kinds=error_kinds,
    )

    assert len(hits) == 1


# ==================== B-6：MCP schema 负缓存短 TTL ====================


@pytest.fixture(autouse=True)
def _reset_mcp_cache():
    clear_mcp_tools_schema_cache()
    yield
    clear_mcp_tools_schema_cache()


def test_mcp_schema_failure_negative_cache_expires(monkeypatch) -> None:
    calls = {"n": 0}
    clock = {"now": 1000.0}

    def fake_get_tools() -> object:
        calls["n"] += 1
        raise RuntimeError("mcp server offline")

    monkeypatch.setattr(
        chat_module, "_mcp_client_modules", lambda: (fake_get_tools, None)
    )
    monkeypatch.setattr(chat_module, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    assert chat_module._mcp_tools_schema() == []
    assert chat_module._mcp_tools_schema() == []
    assert calls["n"] == 1, "TTL 内不应重复探测"

    clock["now"] += _MCP_NEGATIVE_CACHE_TTL_SECONDS + 1.0
    assert chat_module._mcp_tools_schema() == []
    assert calls["n"] == 2, "负缓存到期后应重新探测"


def test_mcp_schema_success_cached_without_expiry(monkeypatch) -> None:
    calls = {"n": 0}
    clock = {"now": 1000.0}

    async def fake_get_tools() -> object:
        calls["n"] += 1
        return [{"type": "function", "function": {"name": "web_search"}}]

    monkeypatch.setattr(
        chat_module, "_mcp_client_modules", lambda: (fake_get_tools, None)
    )
    monkeypatch.setattr(chat_module, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    schema = chat_module._mcp_tools_schema()
    assert schema and schema[0]["function"]["name"] == "web_search"
    clock["now"] += 10_000.0
    chat_module._mcp_tools_schema()
    assert calls["n"] == 1, "成功结果长期缓存"


def test_mcp_modules_structurally_missing_cached_permanently(monkeypatch) -> None:
    probe_calls = {"n": 0}

    def fake_probe() -> tuple[object, object]:
        probe_calls["n"] += 1
        return (None, None)

    monkeypatch.setattr(chat_module, "_mcp_client_modules", fake_probe)
    assert chat_module._mcp_tools_schema() == []
    assert chat_module._mcp_tools_schema() == []
    assert probe_calls["n"] == 1, "插件未安装属结构性缺失，进程内不会变化"


# ==================== B-8：工具循环空文本收尾轮 ====================


class _ExhaustedThenWrapProvider:
    """前两轮只有 tool_calls 没有文本（打满 max_rounds），第三轮（收尾轮，
    不带 tools）返回最终回答。"""

    def __init__(self) -> None:
        self.calls = 0
        self.wrap_call_had_tools: bool | None = None

    def generate(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= 2:
            return LLMReply(
                text="",
                provider="fake",
                model="m",
                tool_calls=[
                    {
                        "id": f"c{self.calls}",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": "{}"},
                    }
                ],
            )
        self.wrap_call_had_tools = "tools" in kwargs
        return LLMReply(text="最终回答", provider="fake", model="m")


def test_tool_loop_appends_single_wrap_up_round_when_text_empty() -> None:
    provider = _ExhaustedThenWrapProvider()

    reply = _generate_with_tool_loop(
        llm_provider=provider,
        model_router=None,
        messages=[{"role": "user", "content": "hi"}],
        message_text="hi",
        override="",
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        llm_options={},
    )

    assert reply.text == "最终回答"
    assert provider.calls == 3, "收尾轮恰好追加一次"
    assert provider.wrap_call_had_tools is False, "收尾轮不应再携带 tools"


class _NeverTextProvider:
    def generate(self, messages, **kwargs):
        self.calls = getattr(self, "calls", 0) + 1
        return LLMReply(
            text="",
            provider="fake",
            model="m",
            tool_calls=[
                {
                    "id": f"c{self.calls}",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{}"},
                }
            ],
        )


def test_tool_loop_wrap_failure_falls_back_to_last_reply() -> None:
    provider = _NeverTextProvider()

    reply = _generate_with_tool_loop(
        llm_provider=provider,
        model_router=None,
        messages=[{"role": "user", "content": "hi"}],
        message_text="hi",
        override="",
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        llm_options={},
    )

    # 收尾轮仍空文本 → 回退旧行为（不抛异常，返回末轮空文本回复）。
    assert reply.text == ""


# ==================== B-9：引号审计标签语义 ====================


def test_speech_quotes_tag_condition_matches_strip_transform_only() -> None:
    quoted = "“我就在这里。”"
    stripped = strip_outer_speech_quotes(quoted)
    assert stripped != quoted.strip(), "外层引号被剥离时标签应置位"

    plain = "我就在这里。"
    assert strip_outer_speech_quotes(plain) == plain.strip(), "无外层引号时不应置位"
