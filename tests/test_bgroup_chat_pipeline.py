"""B组 chat 域回归（管线检视 #1/#5/#8/#11 + B-11 记忆抽取有界化）。

离线运行（无网络、无 SnowLuma、无 Playwright）：

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

from plugins.bot_unified_runtime.contracts import WebSearchHit
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
    chat as chat_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMReply,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline import (
    DeadlineBudget,
)

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
    tmp_path,
) -> None:
    # 运行数据根隔离：BOT_RUNTIME_DATA_DIR 缺省会回退到源码树 data/
    # （AGENTS.md 规则 2/6 明令源码树不得出现 data/），显式指到 tmp。
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    captured: dict[str, object] = {}

    def fake_build_video_brief(_config: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(text="brief", signals={})

    from plugins.bot_unified_runtime.domains.media.ingest import video_understanding

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


# ==================== S134·A：语音段最小预算预留（CM-P-40 R1） ====================


def _budget_with_remaining(remaining: float) -> DeadlineBudget:
    """造一枚"剩余恰好 ≈remaining 秒"的预算（用 started_at 偏移，确定性好复算）。"""
    total = remaining + 40.0
    return DeadlineBudget(total, started_at=time.monotonic() - (total - remaining))


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        (20.0, 20.0),      # 缺省：预留＝语音自己那一次调用的超时
        (5.0, 5.0),        # 小于夹顶：照单收下
        (600.0, 30.0),     # 夹顶：调大配置也不许把视觉相位饿死（反向互压）
        (0.0, 0.0),        # 关掉预留＝退回改动前形态
        ("abc", 0.0),      # 非数
        (float("nan"), 0.0),
        (-1.0, 0.0),
    ],
)
def test_asr_reserve_value_tracks_config_with_a_cap(raw: object, want: float) -> None:
    assert chat_module._asr_reserve_seconds(raw) == want


def test_asr_stage_timeout_is_clamped_by_remaining_budget() -> None:
    """剩余不足时语音**不再吃掉主回复的份额**：这是 R1 的第一半（此前完全无闸）。"""
    # 剩余 ≈25s、LLM 保留 60s ⇒ 可用为负 ⇒ 钳到 1s 且判"被饿"。
    timeout, starved = chat_module._asr_deadline_seconds(
        _budget_with_remaining(25.0), asr_timeout_seconds=20.0
    )
    assert timeout == 1.0 and starved is True
    # 剩余 ≈75s ⇒ 可用 ≈15s < 预留 20s ⇒ 仍判被饿，但不再吃满 20s。
    timeout, starved = chat_module._asr_deadline_seconds(
        _budget_with_remaining(75.0), asr_timeout_seconds=20.0
    )
    assert 13.0 < timeout <= 15.0 and starved is True
    # 充裕预算 ⇒ 拿满自己的超时、不算被饿。
    timeout, starved = chat_module._asr_deadline_seconds(
        _budget_with_remaining(250.0), asr_timeout_seconds=20.0
    )
    assert timeout == 20.0 and starved is False


@pytest.mark.parametrize("budget", [None, DeadlineBudget(0)])
def test_asr_stage_timeout_defaults_when_budget_inactive(budget: object) -> None:
    """预算未启用 ⇒ 逐字节退回旧行为（默认 20s、不算饿）。"""
    assert chat_module._asr_deadline_seconds(
        budget, asr_timeout_seconds=20.0  # type: ignore[arg-type]
    ) == (20.0, False)


def test_video_deadline_now_also_subtracts_the_asr_reserve() -> None:
    """视频相位那侧的同一规则：多扣一枚语音预留，且**缺省参数不改旧值**。"""
    plain = chat_module._video_deadline_seconds(_budget_with_remaining(200.0))
    reserved = chat_module._video_deadline_seconds(
        _budget_with_remaining(200.0), asr_reserve_seconds=20.0
    )
    assert plain is not None and reserved is not None
    assert 138.0 < plain <= 140.0, "缺省（0.0）必须等于改动前的 B-1 语义"
    assert 118.0 < reserved <= 120.0, f"预留没进扣减：plain={plain} reserved={reserved}"
    assert plain - reserved == pytest.approx(20.0, abs=1e-6)
    # 下限仍在：预算极小时钳到 30s 不下探（旧 B-1 语义优先于预留）。
    floored = chat_module._video_deadline_seconds(
        _budget_with_remaining(100.0), asr_reserve_seconds=20.0
    )
    assert floored == 30.0


def test_vision_stage_timeout_reserves_for_pending_voice() -> None:
    """旧抽帧分支（`describe_video`）同一条规则；预留 0 时＝旧值 30s。"""
    assert chat_module._vision_stage_timeout_seconds(
        _budget_with_remaining(250.0), default_seconds=30.0, asr_reserve_seconds=0.0
    ) == 30.0
    tight = chat_module._vision_stage_timeout_seconds(
        _budget_with_remaining(100.0), default_seconds=30.0, asr_reserve_seconds=20.0
    )
    assert 18.0 < tight <= 20.0, tight
    assert chat_module._vision_stage_timeout_seconds(
        _budget_with_remaining(30.0), default_seconds=30.0, asr_reserve_seconds=20.0
    ) == 5.0


def test_reservation_only_exists_when_a_voice_is_actually_pending(tmp_path) -> None:
    """没带语音却切走 20s＝把一条互压换成反向那一条（本席自查后补的门）。"""
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    clip = tmp_path / "voice.mp3"
    clip.write_bytes(b"ID3\x04" + b"\x00" * 128)

    def message(segments: list[dict]) -> IncomingMessage:
        return IncomingMessage(
            platform="qq",
            adapter="onebot",
            bot_id="10000",
            session_id="private:u1",
            session_type=SessionType.PRIVATE,
            sender_id="u1",
            plain_text="在吗",
            raw_segments=segments,
        )

    provider = SimpleNamespace(_config=SimpleNamespace(bot_asr_timeout_seconds=20.0))
    assert chat_module._asr_pending_on_message(message([]), provider) is False
    assert chat_module._asr_pending_on_message(
        message([{"type": "record", "data": {"file": str(clip)}}]), provider
    ) is True
    # provider 没装配 ⇒ 语音侧根本没活，预留必须为 0。
    assert chat_module._asr_pending_on_message(
        message([{"type": "record", "data": {"file": str(clip)}}]), None
    ) is False


class _RecordingAsrConfig:
    """ASR 替身：记下单次调用真正拿到的超时（牙齿在 kwargs，不在返回值）。"""

    def __init__(self, timeout: float = 20.0) -> None:
        self._config = SimpleNamespace(bot_asr_timeout_seconds=timeout)
        self.timeouts: list[object] = []

    def generate(self, audio_bytes: bytes, filename: str, **kwargs: object) -> str:
        self.timeouts.append(kwargs.get("timeout_seconds"))
        return "帮我看看明天的天气"


def _voice_message(tmp_path, text: str = "听听这个"):
    from plugins.bot_unified_runtime.contracts import (
        BotDecision,
        IncomingMessage,
        SessionType,
    )

    clip = tmp_path / "voice.mp3"
    clip.write_bytes(b"ID3\x04" + b"\x00" * 128)
    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
        raw_segments=[{"type": "record", "data": {"file": str(clip)}}],
    )
    decision = BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )
    return message, decision


def _run_voice_turn(tmp_path, budget_seconds: float):
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_capability,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        NullCharacterContextProvider,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
        StaticLLMProvider,
    )

    asr = _RecordingAsrConfig()
    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="好的，我看看"),
        asr_provider=asr,
        asr_enabled=True,
        request_budget_seconds=budget_seconds,
    )
    message, decision = _voice_message(tmp_path)
    result = capability(message, decision)
    return asr, result


def test_tight_budget_clamps_the_real_asr_call_and_leaves_a_trace(tmp_path) -> None:
    """**端到端主锁**（真能力层 → 真 transcribe_audio → 真 provider 记账）：
    预算只剩刚够 LLM 时，语音段拿到的超时被夹住，且审计面出现饿死留痕。"""
    asr, result = _run_voice_turn(tmp_path, 61.0)
    assert asr.timeouts, "一次转写都没发起：本用例退化成空跑"
    received = asr.timeouts[0]
    assert isinstance(received, float) and received <= 2.0, (
        f"紧预算下语音仍按裸 config 拿 20s ⇒ 预留/夹顶没接上：{received}"
    )
    assert "asr_budget_starved" in result.audit_tags, result.audit_tags


def test_generous_budget_keeps_the_old_timeout_and_stays_silent(tmp_path) -> None:
    """反向格（防"永远夹到最小"的过修）：预算充裕 ⇒ 超时照旧 20s、不留饿死痕。"""
    asr, result = _run_voice_turn(tmp_path, 300.0)
    assert asr.timeouts == [20.0], asr.timeouts
    assert "asr_budget_starved" not in result.audit_tags


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
    """Barrier 确定性并发断言：4 查询必须同时在飞（串行退化即 BrokenBarrier）。"""
    barrier = threading.Barrier(4, timeout=5.0)

    class _BarrierProvider:
        def search(self, query: str, *, max_results: int) -> list[WebSearchHit]:
            barrier.wait()  # 4 线程到齐才放行；串行实现此处超时破裂
            return [
                WebSearchHit(
                    title=f"t-{query}",
                    snippet="s",
                    url=f"http://u/{query}",
                    source_domain="d",
                )
            ]

    errors: set[str] = set()
    merged = chat_module._search_queries_concurrently(
        _BarrierProvider(),
        ["a", "b", "c", "d"],
        per_query=3,
        hard_total_cap=40,
        error_kinds=errors,
    )

    # 顺序确定性：合并结果按查询顺序排列。
    assert [hit.title for hit in merged] == ["t-a", "t-b", "t-c", "t-d"]
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
