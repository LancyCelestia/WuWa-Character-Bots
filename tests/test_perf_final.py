"""路由分类 TTL-LRU 缓存与设置变更监听回归：缓存命中/失效、resolver 区分、TTL 过期、持久化监听触发。

全部离线；被测实现在
``plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router``（TTL 10s，键为 (有无 resolver, 文本)）
与 ``plugins.bot_unified_runtime.domains.chat_reply.runtime.settings.RuntimeSettingsStore``（_save 先通知监听再写盘）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime import base_router
from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
    RouteDecision,
    RouteKind,
    RouteRule,
    classify_message_route,
    clear_route_decision_cache,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RuntimeSettingsStore,
)

_TEXT = "今天天气不错"


@pytest.fixture()
def _clean_route_cache():
    clear_route_decision_cache()
    yield
    clear_route_decision_cache()


def _install_counting_rule(monkeypatch) -> list[RouteDecision]:
    """把 ROUTE_RULES 换成单条计数假规则，返回记录命中 decision 的列表。"""
    calls: list[RouteDecision] = []

    def counting_matcher(_text, _config, _alias):
        decision = RouteDecision(RouteKind.CHAT, "bot.chat", 50, "reason", ("tag",))
        calls.append(decision)
        return decision

    monkeypatch.setattr(
        base_router,
        "ROUTE_RULES",
        [RouteRule(RouteKind.CHAT, "bot.chat", 50, "假规则", "计数用", matcher=counting_matcher)],
    )
    return calls


def test_route_classification_cached(monkeypatch, _clean_route_cache):
    calls = _install_counting_rule(monkeypatch)
    config = object()  # 生产中 config 是进程级单例；缓存按 config 同一性校验

    first = classify_message_route(_TEXT, config=config)
    second = classify_message_route(_TEXT, config=config)

    assert len(calls) == 1, "TTL 内同文本第二次分类必须命中缓存，不得再跑 matcher"
    assert second is first, "命中缓存必须返回同一 decision 对象"


def test_route_cache_clear_invalidates(monkeypatch, _clean_route_cache):
    calls = _install_counting_rule(monkeypatch)
    config = object()

    classify_message_route(_TEXT, config=config)
    clear_route_decision_cache()
    classify_message_route(_TEXT, config=config)

    assert len(calls) == 2, "clear_route_decision_cache 后必须重新分类"


def test_route_cache_distinguishes_alias_presence(monkeypatch, _clean_route_cache):
    calls = _install_counting_rule(monkeypatch)
    config = object()

    classify_message_route(_TEXT, config=config, alias_resolver=None)
    classify_message_route(_TEXT, config=config, alias_resolver=object())

    assert len(calls) == 2, "有无 alias_resolver 是两个缓存键，不得互相命中"


def test_route_cache_rejects_foreign_config(monkeypatch, _clean_route_cache):
    """不同 config 对象互不串结果（命中时校验 config 同一性）。"""
    calls = _install_counting_rule(monkeypatch)

    classify_message_route(_TEXT, config=object())
    classify_message_route(_TEXT, config=object())

    assert len(calls) == 2, "config 不同即便文本相同也必须重新分类"


def test_route_cache_ttl_expires(monkeypatch, _clean_route_cache):
    calls = _install_counting_rule(monkeypatch)
    config = object()
    fake_clock = [1000.0]
    monkeypatch.setattr(
        base_router, "time", SimpleNamespace(monotonic=lambda: fake_clock[0])
    )

    classify_message_route(_TEXT, config=config)
    fake_clock[0] = 1011.0
    classify_message_route(_TEXT, config=config)
    assert len(calls) == 2, "超过 10s TTL 后必须重新分类"

    fake_clock[0] = 1015.0
    classify_message_route(_TEXT, config=config)
    assert len(calls) == 2, "1011s 写入后 4s 内仍在 TTL 内，必须命中缓存"


def test_settings_change_listener_fires(tmp_path):
    store = RuntimeSettingsStore(tmp_path / "s.json", instance="t1")
    fired: list[int] = []
    store.register_change_listener(lambda: fired.append(1))

    store._overrides["BOT_X"] = 1
    store._save()
    assert fired == [1], "持久化开始时必须触发监听"

    store._save()
    assert fired == [1, 1], "再次保存监听应累计触发"
