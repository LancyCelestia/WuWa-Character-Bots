"""2026-09-11 出域 findings 认领修复的回归测试。

覆盖：DDG 重定向解码（web_search/meme_search）、梗搜索缓存有界化、
「总之」剥离吞实质内容、订阅同步客户端阻塞事件循环（P1）、
bilibili V2 live_room 恒空、调度器最小间隔持全局锁串行、
LLM 流式总预算 deadline、剥参重试成功漏记健康样本。
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionFetchResult,
    SubscriptionSpec,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.llm import model_router as router_module
from plugins.bot_unified_runtime.llm.model_router import ModelRouter, ModelSpec
from plugins.bot_unified_runtime.llm.providers import LLMProviderError, LLMReply
from plugins.bot_unified_runtime.output.plain_text import humanize_reply
from plugins.bot_unified_runtime.sources import meme_search, web_search
from plugins.bot_unified_runtime.sources.subscription_scheduler import PlatformThrottle
from plugins.bot_unified_runtime.sources.subscriptions import (
    bilibili_adapter,
    social_v2,
)

# ---------- DDG 重定向解码 ----------

def test_websearch_resolve_ddg_redirect_decodes_shell() -> None:
    encoded = "https%3A%2F%2Fzh.moegirl.org.cn%2F%E5%AE%88%E5%B2%B8%E4%BA%BA"
    assert (
        web_search._resolve_ddg_redirect(f"//duckduckgo.com/l/?uddg={encoded}")
        == "https://zh.moegirl.org.cn/守岸人"
    )
    assert (
        web_search._resolve_ddg_redirect(f"/l/?uddg={encoded}")
        == "https://zh.moegirl.org.cn/守岸人"
    )


def test_websearch_resolve_ddg_redirect_keeps_plain_urls() -> None:
    assert web_search._resolve_ddg_redirect("https://example.com/a") == "https://example.com/a"
    # 非 DDG 域名即便自带 uddg 参数也不动，避免误伤第三方链接。
    assert (
        web_search._resolve_ddg_redirect("https://example.com/l/?uddg=x")
        == "https://example.com/l/?uddg=x"
    )


def test_websearch_ddg_hits_extract_real_target_links() -> None:
    html = (
        '<div class="result results_links results_links_deep web-result ">'
        '<h2 class="result__title"><a rel="nofollow" class="result__a" '
        'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fzh.moegirl.org.cn%2Fxyz">'
        "守岸人_萌娘百科</a></h2>"
        '<a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">守岸人简介</a>'
        "</div>"
    )
    hits = web_search._extract_ddg_hits(html)
    assert len(hits) == 1
    assert hits[0].url == "https://zh.moegirl.org.cn/xyz"
    assert hits[0].source_domain == "zh.moegirl.org.cn"


def test_memesearch_ddg_items_resolve_redirect_and_pass_whitelist() -> None:
    encoded = "https%3A%2F%2Fzh.moegirl.org.cn%2F%E5%AE%88%E5%B2%B8%E4%BA%BA"
    html = (
        '<div class="result results_links results_links_deep web-result ">'
        '<a class="result__a" href="//duckduckgo.com/l/?uddg='
        + encoded
        + '">守岸人是什么梗_萌娘百科</a>'
        '<a class="result__snippet" href="#">守岸人是鸣潮中的角色</a>'
        "</div>"
    )
    items = meme_search._extract_ddg_items(html)
    assert items and items[0][2] == "https://zh.moegirl.org.cn/守岸人"
    results = meme_search.filter_meme_results("守岸人 是什么梗", items)
    assert results and results[0].source_domain == "zh.moegirl.org.cn"


def test_memesearch_cache_is_bounded() -> None:
    provider = meme_search.DuckDuckGoMemeSearchProvider()
    now = time.monotonic()
    for i in range(meme_search._CACHE_MAX_ENTRIES + 20):
        provider._cache[f"stale-{i}"] = (now - 10_000.0, [])
    provider._cache["fresh"] = (now, [])
    provider._evict_cache()
    assert len(provider._cache) <= meme_search._CACHE_MAX_ENTRIES
    assert "fresh" in provider._cache
    assert not any(k.startswith("stale-") for k in provider._cache)


# ---------- 去 AI 味：「总之」剥离边界 ----------

def test_humanize_keeps_substantive_summary_tail() -> None:
    text = "方案 A 更省事。总之先跑通主流程再说。"
    assert humanize_reply(text) == text


def test_humanize_strips_coda_only_with_boilerplate_cue() -> None:
    assert humanize_reply("今天先到这里。总之，希望你喜欢！") == "今天先到这里。"
    assert humanize_reply("内容如上。总之以上就是全部内容。") == "内容如上。"


# ---------- 订阅调度器：最小间隔不得持全局锁 ----------

def test_platform_throttle_does_not_serialize_platforms() -> None:
    async def main() -> list[str]:
        throttle = PlatformThrottle(
            per_platform_limit=4, global_limit=8, min_interval_seconds=0.3
        )
        order: list[str] = []

        async def noop() -> None:
            return None

        async def op_a() -> None:
            order.append("a")

        async def op_b() -> None:
            order.append("b")

        await throttle.run("p1", noop)  # 占住 p1 的最小间隔窗口

        async def run_a() -> None:
            await throttle.run("p1", op_a)

        async def run_b() -> None:
            await throttle.run("p2", op_b)

        await asyncio.gather(run_a(), run_b())
        return order

    # 修复前：p1 睡最小间隔时持全局锁，p2 被迫等锁 → 先 a 后 b。
    # 修复后：p2 不受 p1 的间隔窗口影响 → 先 b 后 a。
    assert asyncio.run(main()) == ["b", "a"]


# ---------- 订阅同步客户端卸载线程（P1） ----------

def _subscription_target(platform: str = "twitter") -> SubscriptionTarget:
    now = datetime.now(timezone.utc)
    return SubscriptionTarget(
        id="t42",
        platform=platform,
        target_kind="creator",
        target_key="42",
        display_name="42",
        target_payload={"raw": "https://example.com/42"},
        created_at=now,
        updated_at=now,
    )


def test_sync_subscription_client_runs_off_event_loop() -> None:
    class SyncClient:
        def __init__(self) -> None:
            self.thread_id: int | None = None

        def fetch_incremental(
            self, target: object, cursors: object, context: object
        ) -> SubscriptionFetchResult:
            self.thread_id = threading.get_ident()
            return SubscriptionFetchResult(health_state="healthy")

    client = SyncClient()
    adapter = social_v2._BaseAdapter(client=client)
    result = asyncio.run(
        adapter._fetch_or_unsupported(_subscription_target(), {}, {})
    )
    assert result.health_state == "healthy"
    assert client.thread_id is not None
    assert client.thread_id != threading.get_ident()


def test_async_subscription_client_stays_on_loop() -> None:
    class AsyncClient:
        def __init__(self) -> None:
            self.thread_id: int | None = None

        async def fetch_incremental(
            self, target: object, cursors: object, context: object
        ) -> SubscriptionFetchResult:
            self.thread_id = threading.get_ident()
            return SubscriptionFetchResult(health_state="healthy")

    client = AsyncClient()
    adapter = social_v2._BaseAdapter(client=client)
    result = asyncio.run(
        adapter._fetch_or_unsupported(_subscription_target(), {}, {})
    )
    assert result.health_state == "healthy"
    assert client.thread_id == threading.get_ident()


# ---------- bilibili V2 live_room 恒空 ----------

def _live_spec() -> SubscriptionSpec:
    return SubscriptionSpec(
        id="s1",
        platform="bilibili",
        target_kind="live_room",
        target_id="123",
        target_name="测试UP",
        created_by="t",
    )


def test_bilibili_live_room_fetch_emits_item(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_json(url: str, **_kwargs: object) -> dict[str, object]:
        assert "room_id=123" in url
        return {
            "code": 0,
            "data": {
                "room_info": {
                    "live_status": 1,
                    "title": "测试直播",
                    "live_start_time": "1700000000",
                }
            },
        }

    monkeypatch.setattr(bilibili_adapter, "http_get_json", fake_get_json)
    adapter = bilibili_adapter.BilibiliAdapter()
    result = asyncio.run(adapter.fetch_latest(_live_spec(), None, {}))
    assert result.health_state == "healthy"
    assert result.items is not None and len(result.items) == 1
    item = result.items[0]
    assert item.kind == "live"
    assert item.item_id == "live:123:1700000000"
    assert item.url == "https://live.bilibili.com/123"


def test_bilibili_live_room_offline_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bilibili_adapter,
        "http_get_json",
        lambda _url, **_kw: {"code": 0, "data": {"room_info": {"live_status": 0}}},
    )
    adapter = bilibili_adapter.BilibiliAdapter()
    result = asyncio.run(adapter.fetch_latest(_live_spec(), None, {}))
    assert result.health_state == "healthy"
    assert result.items == []


# ---------- 内心状态数值保密（拟人化整合报告红线） ----------

def test_humanize_redacts_inner_state_numbers() -> None:
    redacted = humanize_reply("其实你的好感度已经是0.78了哦")
    assert "0.78" not in redacted
    assert "好感度" in redacted
    assert "0.45" not in humanize_reply("顺便一提 affinity=0.45。")
    assert humanize_reply("好感度排行榜前3名已经更新") == "好感度排行榜前3名已经更新"


# ---------- LLM 流式总预算 deadline ----------

class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def iter_bytes(self) -> object:
        return iter(self._chunks)


def test_read_stream_deadline_raises_timeout() -> None:
    from plugins.bot_unified_runtime.llm import providers as llm_providers

    with pytest.raises(LLMProviderError) as raised:
        llm_providers._read_stream_limited(
            _FakeStreamResponse([b"abc"]),  # type: ignore[arg-type]
            100,
            deadline=time.monotonic() - 1.0,
        )
    assert raised.value.error_kind == "timeout"


def test_read_stream_without_deadline_returns_bytes() -> None:
    from plugins.bot_unified_runtime.llm import providers as llm_providers

    out = llm_providers._read_stream_limited(
        _FakeStreamResponse([b"ab", b"cd"]),  # type: ignore[arg-type]
        100,
    )
    assert out == b"abcd"


# ---------- 剥参重试成功漏记健康样本（EWMA 饿死） ----------

def test_strip_retry_success_records_health_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[str] = []
    monkeypatch.setattr(
        router_module,
        "_health_record_success",
        lambda model_id, _latency_ms, _config=None: recorded.append(model_id),
    )
    calls: list[dict[str, object]] = []

    class Provider:
        def generate(self, messages: object, **kwargs: object) -> LLMReply:
            calls.append(dict(kwargs))
            if "reasoning_effort" in kwargs:
                raise LLMProviderError(
                    "unsupported reasoning",
                    error_kind="unsupported_parameter",
                )
            return LLMReply(text="ok", provider="fake", model="first")

    router = ModelRouter(
        {"first": ModelSpec(
            model_id="first",
            model="first",
            base_url="https://example.test/v1",
            api_key="key",
            tags=("fast",),
            priority=1,
        )},
        provider_factory=lambda _spec: Provider(),
    )
    reply = router.generate(
        [{"role": "user", "content": "hello"}],
        reasoning_effort="high",
    )

    assert reply.text == "ok"
    assert len(calls) == 2
    assert recorded == ["first"]
