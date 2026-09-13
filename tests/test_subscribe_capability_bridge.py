"""订阅能力 check 协程桥接回归（capabilities/subscribe.py × social_v2 桥接）。

A63 移交件（xhs-leak-fix-report §五.2）：check 动作原 ``asyncio.run(coro)``
形态是 16 条 XHS "never awaited" 的真实构造点——先构造入参协程、再做入口
running-loop 检查；线程若残留 running-loop 状态（playwright sync greenlet
中毒），检查先抛 RuntimeError，协程被弃 → GC 时告警。修复后走
``_run_legacy_coroutine`` 预检先行：中毒线程在协程构造**之前**上抛，由
能力层 broad except 收敛为结构化失败（不炸调度器）。

本文件在能力层验证：中毒线程（monkeypatch 模拟 / 真实线程两种）结构化
降级且协程零构造；干净线程正常抓取与内部错误照旧传播。全离线（假
adapter，无网络）。
"""

from __future__ import annotations

import asyncio
import gc
import threading
import warnings
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.capabilities.subscribe import (
    build_subscribe_capability,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.contracts.subscription import (
    NormalizedSubscriptionItem,
    SourceFetchResult,
    SubscriptionDestination,
    SubscriptionSpec,
)
from plugins.bot_unified_runtime.sources.subscription_store import SubscriptionStore

_SPEC_ID = "bilibili:user:1"


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:creator",
        session_type=SessionType.PRIVATE,
        sender_id="creator",
        group_id=None,
        sender_roles=["user"],
        plain_text=text,
    )


def _seed_spec(store: SubscriptionStore) -> None:
    store.upsert_spec(
        SubscriptionSpec(
            id=_SPEC_ID,
            platform="bilibili",
            target_kind="user",
            target_id="1",
            target_name="UP主",
            destinations=[SubscriptionDestination(scope="private", target_id="creator")],
            created_by="creator",
        )
    )


def _capability(tmp_path: Any, adapter: Any):
    registry = SimpleNamespace(
        resolve_target=lambda raw: {},
        find=lambda platform: adapter,
    )
    store = SubscriptionStore(str(tmp_path / "sub.sqlite3"))
    _seed_spec(store)
    return build_subscribe_capability(store=store, registry=registry, config=None)


class _FakeAdapter:
    """假 bilibili adapter：``fetch_latest`` 被调用即计一次（= 协程构造点）。"""

    platform = "bilibili"

    def __init__(
        self,
        *,
        error: str = "",
        items: list[NormalizedSubscriptionItem] | None = None,
        exc: BaseException | None = None,
    ) -> None:
        self.calls = 0
        self._error = error
        self._items = items or []
        self._exc = exc

    def fetch_latest(self, spec: Any, cursor: Any, context: Any) -> Any:
        # 能力层把本方法作为 factory 传入 _run_legacy_coroutine：
        # 本方法被调用 = 入参协程已构造（中毒线程应为 0 次）。
        self.calls += 1
        return self._fetch(spec, cursor, context)

    async def _fetch(self, spec: Any, cursor: Any, context: Any) -> SourceFetchResult:
        if self._exc is not None:
            raise self._exc
        return SourceFetchResult(items=self._items, error=self._error)


def _one_item() -> NormalizedSubscriptionItem:
    return NormalizedSubscriptionItem(
        item_id="i1",
        kind="video",
        title="新视频",
        url="https://example.com/v1",
    )


# ==================== 中毒线程：协程零构造 + 结构化降级 ====================


def test_check_poisoned_running_loop_degrades_without_constructing(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """monkeypatch 模拟残留 running-loop：构造前上抛 → 结构化失败、零构造。"""
    adapter = _FakeAdapter(items=[_one_item()])
    capability = _capability(tmp_path, adapter)
    monkeypatch.setattr(
        asyncio, "get_running_loop", lambda: object(), raising=True
    )  # 模拟 greenlet 中毒残留：get_running_loop 不再抛 RuntimeError。
    result = capability(_message(f"/bot subscribe check {_SPEC_ID}"), None)
    assert "检查失败" in result.body
    assert "subscribe_check_failed" in result.audit_tags
    assert adapter.calls == 0  # factory 未执行 → 协程从未构造，结构性零泄漏。


def test_check_poisoned_worker_thread_degrades_without_constructing(tmp_path: Any) -> None:
    """真实中毒工作线程（asyncio.events 私有 API 注入 running loop）：同语义降级。"""
    adapter = _FakeAdapter(items=[_one_item()])
    capability = _capability(tmp_path, adapter)
    sentinel = object()
    outcomes: dict[str, Any] = {}

    def _poisoned_worker() -> None:
        asyncio.events._set_running_loop(sentinel)
        try:
            result = capability(_message(f"/bot subscribe check {_SPEC_ID}"), None)
            outcomes["body"] = result.body
            outcomes["tags"] = list(result.audit_tags)
        except Exception as exc:  # noqa: BLE001 - 命中即回归失败：能力层必须结构化兜底。
            outcomes["unexpected"] = exc
        finally:
            asyncio.events._set_running_loop(None)

    thread = threading.Thread(target=_poisoned_worker, name="poisoned-worker")
    thread.start()
    thread.join(timeout=10)
    assert "unexpected" not in outcomes  # 结构化失败，不炸调用方。
    assert "检查失败" in outcomes["body"]
    assert "subscribe_check_failed" in outcomes["tags"]
    assert adapter.calls == 0


# ==================== 干净线程：正常抓取 + 内部错误照旧传播 ====================


def test_check_clean_thread_fetches_through_bridge(tmp_path: Any) -> None:
    """干净线程正常路径：协程被完整 await，新增条目照常预览。"""
    adapter = _FakeAdapter(items=[_one_item()])
    capability = _capability(tmp_path, adapter)
    result = capability(_message(f"/bot subscribe check {_SPEC_ID}"), None)
    assert adapter.calls == 1
    assert "检查完成：新增 1 条" in result.body
    assert "新视频" in result.body
    assert "subscribe_check_failed" not in result.audit_tags


def test_check_clean_thread_coroutine_error_structured_no_leak(tmp_path: Any) -> None:
    """干净线程协程内部抛 RuntimeError：结构化失败且零 "never awaited"。"""
    adapter = _FakeAdapter(exc=RuntimeError("bridge internal boom"))
    capability = _capability(tmp_path, adapter)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = capability(_message(f"/bot subscribe check {_SPEC_ID}"), None)
        gc.collect()
    never_awaited = [w for w in caught if "never awaited" in str(w.message)]
    assert never_awaited == []
    assert adapter.calls == 1  # 协程已构造且被 run_until_complete 消费。
    assert "检查失败" in result.body and "bridge internal boom" in result.body
    assert "subscribe_check_failed" in result.audit_tags
