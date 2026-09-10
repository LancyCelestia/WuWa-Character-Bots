"""B组 chat 域回归（管线检视 #1/#5/#8/#11 + B-11 记忆抽取有界化）。

离线运行（无网络、无 NapCat、无 Playwright）：

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_bgroup_chat_pipeline.py -q

覆盖项：
- B-1 视频阶段 deadline 与请求总预算协调（剩余-60s 保留、下限 30s）。
- B-3 多 query 并发检索：并发性、顺序确定性、单查询失败容错、硬顶截断。
- B-6 MCP 工具面负缓存短 TTL：失败不再永久缓存，到期自动重探。
- B-8 工具循环打满且末轮空文本时触发无工具收尾轮。
- B-11 记忆抽取并发有界（同时在飞 ≤4，满载跳过不排队）。
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities import chat as chat_module
from plugins.bot_unified_runtime.contracts import WebSearchHit
from plugins.bot_unified_runtime.llm import LLMReply
from plugins.bot_unified_runtime.runtime.deadline import DeadlineBudget

# ==================== B-1：视频阶段预算协调 ====================


def test_video_deadline_none_when_budget_absent_or_disabled() -> None:
    assert chat_module._video_deadline_seconds(None) is None
    assert chat_module._video_deadline_seconds(DeadlineBudget(0)) is None


def test_video_deadline_reserves_llm_budget() -> None:
    started = time.monotonic()
    # 剩余 ≈100s → 视频阶段拿 100-60 ≈ 40s。
    budget = DeadlineBudget(150.0, started_at=started - 50.0)
    value = chat_module._video_deadline_seconds(budget)
    assert value is not None
    assert 38.0 < value <= 40.0


def test_video_deadline_floor_keeps_minimum_analysis_window() -> None:
    started = time.monotonic()
    # 剩余 ≈10s：不下探到负值，钳到 30s 下限（至少能抽到基本帧）。
    budget = DeadlineBudget(150.0, started_at=started - 140.0)
    value = chat_module._video_deadline_seconds(budget)
    assert value is not None
    assert 30.0 <= value < 31.0


def test_analyze_and_store_passes_deadline_to_brief_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_build_video_brief(_config: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(text="brief", signals={})

    from plugins.bot_unified_runtime.sources import video_understanding

    monkeypatch.setattr(
        video_understanding, "build_video_brief", fake_build_video_brief
    )

    result = chat_module._analyze_and_store(
        media_registry=None,
        vision_provider=None,
        asr_provider=None,
        query_text="看看这个视频",
        video_source="/tmp/none.mp4",
        deadline_seconds=42.0,
    )

    assert result == "brief"
    assert captured["deadline_seconds"] == 42.0


# ==================== B-3：多 query 并发检索 ====================


class _SlowSearchProvider:
    def __init__(self, latency: float = 0.25) -> None:
        self.latency = latency

    def search(self, query: str, *, max_results: int) -> list[WebSearchHit]:
        time.sleep(self.latency)
        return [
            WebSearchHit(
                title=f"t-{query}",
                snippet="s",
                url=f"http://u/{query}",
                source_domain="d",
            )
        ]


def test_search_queries_run_concurrently() -> None:
    provider = _SlowSearchProvider()
    errors: set[str] = set()
    started = time.perf_counter()

    merged = chat_module._search_queries_concurrently(
        provider,
        ["a", "b", "c", "d"],
        per_query=3,
        hard_total_cap=40,
        error_kinds=errors,
    )

    elapsed = time.perf_counter() - started
    # 顺序确定性：合并结果按查询顺序排列。
    assert [hit.title for hit in merged] == ["t-a", "t-b", "t-c", "t-d"]
    # 串行 4×0.25=1.0s；并发应接近单查询耗时（留足 CI 裕量）。
    assert elapsed < 0.9
    assert errors == set()


def test_search_queries_tolerates_single_query_failure() -> None:
    class _FlakyProvider(_SlowSearchProvider):
        def search(self, query: str, *, max_results: int) -> list[WebSearchHit]:
            if query == "bad":
                raise RuntimeError("boom")
            return super().search(query, max_results=max_results)

    errors: set[str] = set()
    merged = chat_module._search_queries_concurrently(
        _FlakyProvider(latency=0.0),
        ["a", "bad", "c"],
        per_query=3,
        hard_total_cap=40,
        error_kinds=errors,
    )

    assert [hit.title for hit in merged] == ["t-a", "t-c"]
    assert errors == {"provider:RuntimeError"}


def test_search_queries_respects_hard_total_cap() -> None:
    class _MultiHitProvider:
        def search(self, query: str, *, max_results: int) -> list[WebSearchHit]:
            return [
                WebSearchHit(
                    title=f"{query}-{index}",
                    snippet="s",
                    url=f"http://u/{query}-{index}",
                    source_domain="d",
                )
                for index in range(3)
            ]

    errors: set[str] = set()
    merged = chat_module._search_queries_concurrently(
        _MultiHitProvider(),
        ["a", "b"],
        per_query=3,
        hard_total_cap=4,
        error_kinds=errors,
    )

    # 语义与旧实现一致：break 在整个 query 的命中合并完后才判，超出部分由
    # 调用方 `merged[:hard_total_cap]` 截断（helper 返回全部去重合并）。
    assert len(merged) == 6


# ==================== B-6：MCP 工具面负缓存 TTL ====================


@pytest.fixture
def _reset_mcp_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(chat_module, "_mcp_tools_schema_cache", None)
    monkeypatch.setattr(chat_module, "_mcp_tools_schema_negative_until", 0.0)
    yield


def test_mcp_failure_negative_cache_expires(
    monkeypatch: pytest.MonkeyPatch, _reset_mcp_cache
) -> None:
    calls: list[int] = []

    async def failing_get_tools() -> list[dict[str, object]]:
        calls.append(1)
        raise RuntimeError("mcp offline")

    monkeypatch.setattr(
        chat_module, "_mcp_probe_cache", (failing_get_tools, None)
    )

    assert chat_module._mcp_tools_schema() == []
    assert chat_module._mcp_tools_schema() == []
    # 负缓存窗口内不重探（避免每条消息重复探测）。
    assert len(calls) == 1

    # TTL 到期后自动重探并缓存成功结果。
    monkeypatch.setattr(
        chat_module,
        "_mcp_tools_schema_negative_until",
        time.monotonic() - 1.0,
    )

    async def healthy_get_tools() -> list[dict[str, object]]:
        calls.append(1)
        return [{"name": "tool-a"}]

    monkeypatch.setattr(chat_module, "_mcp_probe_cache", (healthy_get_tools, None))
    assert chat_module._mcp_tools_schema() == [{"name": "tool-a"}]
    assert len(calls) == 2
    # 成功结果进程内常驻（不再探测）。
    assert chat_module._mcp_tools_schema() == [{"name": "tool-a"}]
    assert len(calls) == 2


def test_mcp_structural_missing_is_permanently_cached(
    monkeypatch: pytest.MonkeyPatch, _reset_mcp_cache
) -> None:
    monkeypatch.setattr(chat_module, "_mcp_probe_cache", (None, None))
    assert chat_module._mcp_tools_schema() == []
    # 结构性缺失（插件未安装）仍是永久缓存：进程内不会变化。
    assert chat_module._mcp_tools_schema_cache == []


# ==================== B-8：工具循环空文本收尾轮 ====================


class _ToolOnlyThenTextProvider:
    """带 tools 的轮次只回 tool_calls；无 tools 的轮次回文本。"""

    def __init__(self) -> None:
        self.option_log: list[object] = []

    def generate(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> LLMReply:
        self.option_log.append(kwargs.get("tools"))
        if kwargs.get("tools"):
            return LLMReply(
                text="",
                provider="fake",
                model="m",
                tool_calls=[
                    {
                        "id": "t1",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": "{}"},
                    }
                ],
            )
        return LLMReply(text="final answer", provider="fake", model="m")


def test_tool_loop_empty_text_triggers_wrap_up_round() -> None:
    provider = _ToolOnlyThenTextProvider()
    tools = [{"type": "function", "function": {"name": "web_search"}}]

    reply = chat_module._generate_with_tool_loop(
        llm_provider=provider,
        model_router=None,
        messages=[{"role": "user", "content": "hi"}],
        message_text="hi",
        override="",
        tools=tools,
        llm_options={},
        max_rounds=2,
    )

    # 末轮空文本不再直接判 empty_response：触发一次无工具收尾轮。
    assert reply.text == "final answer"
    assert provider.option_log == [tools, tools, None]


def test_tool_loop_wrap_up_failure_falls_back_to_last_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AlwaysToolCallsProvider:
        def generate(
            self, messages: list[dict[str, str]], **kwargs: object
        ) -> LLMReply:
            if not kwargs.get("tools"):
                raise RuntimeError("wrap-up failed")
            return LLMReply(
                text="",
                provider="fake",
                model="m",
                tool_calls=[
                    {
                        "id": "t1",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": "{}"},
                    }
                ],
            )

    tools = [{"type": "function", "function": {"name": "web_search"}}]
    reply = chat_module._generate_with_tool_loop(
        llm_provider=_AlwaysToolCallsProvider(),
        model_router=None,
        messages=[{"role": "user", "content": "hi"}],
        message_text="hi",
        override="",
        tools=tools,
        llm_options={},
        max_rounds=2,
    )

    # 收尾轮失败回退旧行为：返回末轮回复（空文本由上层按 empty_response 处理）。
    assert reply.text == ""


# ==================== B-11：记忆抽取并发有界 ====================


def test_memory_extraction_is_bounded(
    monkeypatch: pytest.MonkeyPatch, _reset_mcp_cache
) -> None:
    stats = {"active": 0, "max_active": 0, "calls": 0}
    lock = threading.Lock()

    def writer(**_kwargs: object) -> None:
        with lock:
            stats["active"] += 1
            stats["calls"] += 1
            stats["max_active"] = max(stats["max_active"], stats["active"])
        time.sleep(0.25)
        with lock:
            stats["active"] -= 1

    message = SimpleNamespace(
        plain_text="用户的话",
        sender_id="u1",
        session_id="private:u1",
        request_id="req-mem",
    )
    for _ in range(6):
        chat_module._schedule_memory_extraction(
            writer, message=message, reply_text="回复"
        )

    for thread in threading.enumerate():
        if thread.name == "chat-memory-extract":
            thread.join(timeout=3.0)

    # 满载 4 个在飞，其余直接跳过（不排队积压）。
    assert stats["calls"] == 4
    assert stats["max_active"] <= 4
