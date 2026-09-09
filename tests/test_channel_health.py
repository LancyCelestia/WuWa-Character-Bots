"""模型渠道健康巡检回归：状态机、故障转移过滤、按模型名聚合渠道、延迟择优。"""

from __future__ import annotations

from types import SimpleNamespace

import plugins.bot_unified_runtime.llm.channel_health as channel_health_module
from plugins.bot_unified_runtime.llm.channel_health import (
    ChannelHealthStore,
    filter_healthy_candidates,
    prefer_fastest_channels,
)
from plugins.bot_unified_runtime.llm.model_router import ModelRouter, _price_rank


def _store(tmp_path) -> ChannelHealthStore:
    return ChannelHealthStore(tmp_path / "health.sqlite3")


def test_record_failure_marks_unavailable_after_threshold(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.is_available("ch-a") is True
    assert store.record_failure("ch-a", "HTTP 404: model not found") is False
    assert store.is_available("ch-a") is True  # 单次失败不踢出
    assert store.record_failure("ch-a", "HTTP 404: model not found") is True
    assert store.snapshot("ch-a")["state"] == "temporarily_unavailable"
    assert store.is_available("ch-a") is False


def test_record_success_recovers(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_failure("ch-a", "err")
    store.record_failure("ch-a", "err")
    assert store.is_available("ch-a") is False
    store.record_success("ch-a", 350)
    snap = store.snapshot("ch-a")
    assert snap["state"] == "ok"
    assert snap["latency_ms"] == 350
    assert store.is_available("ch-a") is True


def test_filter_keeps_all_when_everything_unavailable(tmp_path) -> None:
    store = _store(tmp_path)
    for model_id in ("a", "b"):
        store.record_failure(model_id, "err")
        store.record_failure(model_id, "err")
    # 全军覆没时放行原列表，避免整bot瘫痪。
    assert filter_healthy_candidates(["a", "b"], store) == ["a", "b"]


def test_filter_drops_only_unavailable(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_failure("bad", "err")
    store.record_failure("bad", "err")
    assert filter_healthy_candidates(["good", "bad", "good2"], store) == [
        "good",
        "good2",
    ]


def test_unavailable_ids_and_clear(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_failure("x", "err")
    store.record_failure("x", "err")
    assert store.unavailable_ids() == {"x"}
    store.clear("x")
    assert store.unavailable_ids() == set()


# ---- B-1 延迟择优 ----

def test_latencies_only_ok_rows_with_latency(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_success("fast", 120)
    store.record_failure("ok-no-latency", "err")  # 单次失败：state 仍 ok，latency 为 NULL
    store.record_failure("down", "err")
    store.record_failure("down", "err")  # 两次：temporarily_unavailable
    assert store.latencies() == {"fast": 120}


def test_prefer_fastest_orders_measured_first(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_success("a", 300)
    store.record_success("b", 100)
    store.record_success("c", 200)
    # 已实测按延迟升序在前，未实测保序垫底。
    assert prefer_fastest_channels(["a", "b", "c", "d", "e"], store) == [
        "b",
        "c",
        "a",
        "d",
        "e",
    ]


def test_prefer_fastest_unmeasured_keep_original_order(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_success("mid", 500)
    assert prefer_fastest_channels(["z", "mid", "a", "y"], store) == [
        "mid",
        "z",
        "a",
        "y",
    ]


def test_prefer_fastest_stable_for_equal_latency(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_success("x", 100)
    store.record_success("y", 100)
    # 同延迟：保持原相对序（稳定排序）。
    assert prefer_fastest_channels(["y", "x"], store) == ["y", "x"]


def test_prefer_fastest_passthrough_without_data(tmp_path) -> None:
    store = _store(tmp_path)
    assert prefer_fastest_channels(["b", "a"], None) == ["b", "a"]
    assert prefer_fastest_channels(["b", "a"], store, enabled=False) == ["b", "a"]
    assert prefer_fastest_channels(["solo"], store) == ["solo"]
    # 健康库无任何实测数据 → 原样返回。
    assert prefer_fastest_channels(["b", "a"], store) == ["b", "a"]


# ---- 按模型名聚合渠道（价格 → 优先级排序） ----

def _router_with(specs: dict[str, dict]) -> ModelRouter:
    built = {
        model_id: SimpleNamespace(
            model_id=model_id,
            model=item["model"],
            base_url=item.get("base_url", ""),
            api_key="k",
            api_keys=("k",),
            tags=("fast",),
            aliases=item.get("aliases", ()),
            priority=item.get("priority", 100),
            routing_group="",
            effort="",
            price_in=item.get("price_in"),
            price_out=item.get("price_out"),
        )
        for model_id, item in specs.items()
    }
    router = ModelRouter.__new__(ModelRouter)
    router.specs = built
    router._fallback_spec = None
    router._priority_groups_cb = None
    return router


def test_price_rank_missing_price_is_last() -> None:
    priced = SimpleNamespace(price_in=1.0, price_out=3.0)
    unpriced = SimpleNamespace(price_in=None, price_out=None)
    assert _price_rank(priced) < _price_rank(unpriced)


def test_channels_for_model_orders_by_price_then_priority(monkeypatch) -> None:
    # 回归基线：健康层关闭（默认）时维持价格 → 优先级排序。
    monkeypatch.delenv("BOT_CHANNEL_HEALTH_ENABLED", raising=False)
    router = _router_with(
        {
            "expensive": {"model": "gemini-x", "priority": 1, "price_in": 3.0, "price_out": 15.0},
            "cheap-late": {"model": "gemini-x", "priority": 5, "price_in": 0.3, "price_out": 1.5},
            "other": {"model": "glm-9", "priority": 2},
        }
    )
    assert router.channels_for_model("Gemini-X") == ["cheap-late", "expensive"]
    assert router.channels_for_model("glm-9") == ["other"]
    assert router.channels_for_model("不存在") == []


def test_channels_for_model_prefers_measured_latency(tmp_path, monkeypatch) -> None:
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    store.record_success("cheap-slow", 900)
    store.record_success("pricey-fast", 150)
    router = _router_with(
        {
            "cheap-slow": {"model": "gemini-x", "priority": 1, "price_in": 0.3, "price_out": 1.5},
            "pricey-fast": {"model": "gemini-x", "priority": 5, "price_in": 3.0, "price_out": 15.0},
            "unmeasured": {"model": "gemini-x", "priority": 2, "price_in": 0.1, "price_out": 0.5},
        }
    )
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "1")
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "1")
    monkeypatch.setattr(channel_health_module, "_GLOBAL_STORE", store)
    # 实测快者优先（价格只作同延迟并列裁决）；未实测渠道（即使最便宜）垫底。
    assert router.channels_for_model("gemini-x") == [
        "pricey-fast",
        "cheap-slow",
        "unmeasured",
    ]


def test_channels_for_model_latency_disabled_falls_back_to_price(tmp_path, monkeypatch) -> None:
    store = ChannelHealthStore(tmp_path / "h.sqlite3")
    store.record_success("cheap-slow", 900)
    store.record_success("pricey-fast", 150)
    router = _router_with(
        {
            "cheap-slow": {"model": "gemini-x", "priority": 1, "price_in": 0.3, "price_out": 1.5},
            "pricey-fast": {"model": "gemini-x", "priority": 5, "price_in": 3.0, "price_out": 15.0},
        }
    )
    monkeypatch.setattr(channel_health_module, "_GLOBAL_STORE", store)
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_ENABLED", "1")
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "0")
    # 延迟择优开关关闭 → 回落价格序。
    assert router.channels_for_model("gemini-x") == ["cheap-slow", "pricey-fast"]
    # 健康层总开关关闭 → 即使延迟择优开也不生效。
    monkeypatch.setenv("BOT_CHANNEL_HEALTH_LATENCY_FIRST", "1")
    monkeypatch.delenv("BOT_CHANNEL_HEALTH_ENABLED")
    assert router.channels_for_model("gemini-x") == ["cheap-slow", "pricey-fast"]


def test_route_ids_aggregates_channels_for_model_name() -> None:
    router = _router_with(
        {
            "ch-a": {"model": "grok-4.6", "priority": 2, "price_in": 0.6, "price_out": 1.8},
            "ch-b": {"model": "grok-4.6", "priority": 1, "price_in": 0.32, "price_out": 0.96},
            "fallback": {"model": "glm-9", "priority": 9},
        }
    )
    ids = router.route_ids(message_text="", override="grok-4.6")
    assert ids[0] == "ch-b"  # 便宜者优先
    assert ids[1] == "ch-a"
    assert "fallback" in ids  # 聚合后仍接自动路由兜底
