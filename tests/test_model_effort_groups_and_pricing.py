from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from plugins.bot_unified_runtime.capabilities.runtime_admin import (
    _handle_model_command,
)
from plugins.bot_unified_runtime.llm.model_router import (
    ModelRouter,
    ModelSpec,
    build_model_router,
    default_effort,
    model_family,
    parse_priority_groups,
    resolve_active_priority_group,
)
from plugins.bot_unified_runtime.runtime.pricing import (
    format_milli_yuan,
    model_call_cost_milli,
    parse_model_prices,
)
from plugins.bot_unified_runtime.runtime.settings import (
    SETTABLE_KEYS,
    RuntimeSettingsStore,
)


class _CaptureProvider:
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self.calls = calls

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            text="ok", provider="fake", model="m", confidence=1.0
        )


def _spec(model_id: str, model: str, priority: int, *, effort: str = "") -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model,
        base_url="https://example.test/v1",
        api_key="key",
        tags=("low", "high", "max"),
        priority=priority,
        effort=effort,
    )


def test_model_family_and_default_effort() -> None:
    assert model_family("deepseek-v4-pro") == "deepseek"
    assert model_family("DeepSeek-V4-Flash") == "deepseek"
    assert model_family("glm-5.3-flash") == "glm"
    assert model_family("kimi-k3") == "kimi"
    assert model_family("gpt-5.6-terra") == "gpt"
    assert model_family("grok-4.6") == "grok"
    assert model_family("gemini-3.7-flash-high") == "gemini"
    assert model_family("c-gemini-3.7-flash-high") == "gemini"
    assert default_effort("deepseek-v4-pro") == "max"
    assert default_effort("gpt-5.6-terra") == "xhigh"
    assert default_effort("gemini-3.7-flash-high") == "high"
    assert default_effort("unknown-model") == ""


def test_router_sends_family_default_effort_and_respects_overrides() -> None:
    calls: list[dict[str, object]] = []
    router = ModelRouter(
        {"ds": _spec("ds", "deepseek-v4-pro", 1)},
        provider_factory=lambda _spec: _CaptureProvider(calls),
    )
    router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert calls[-1]["reasoning_effort"] == "max"  # 家族默认最高档

    # 全局覆盖（/bot model think low）
    router.generate(
        [{"role": "user", "content": "hi"}], message_text="hi", reasoning_effort="low"
    )
    assert calls[-1]["reasoning_effort"] == "low"

    # 条目 effort=off：明确不发送
    router_off = ModelRouter(
        {"ds": _spec("ds", "deepseek-v4-pro", 1, effort="off")},
        provider_factory=lambda _spec: _CaptureProvider(calls),
    )
    router_off.generate(
        [{"role": "user", "content": "hi"}], message_text="hi", reasoning_effort="high"
    )
    assert "reasoning_effort" not in calls[-1]


def test_router_complex_task_escalates_global_or_default_effort() -> None:
    calls: list[dict[str, object]] = []
    router = ModelRouter(
        {"ds": _spec("ds", "deepseek-v4-pro", 1)},
        provider_factory=lambda _spec: _CaptureProvider(calls),
    )
    complex_text = "请" * 300
    router.generate(
        [{"role": "user", "content": complex_text}],
        message_text=complex_text,
        reasoning_effort="low",
    )
    assert calls[-1]["reasoning_effort"] == "max"  # 复杂任务升到家族最高档
    # 无全局设置时家族默认本来就是 max
    router.generate([{"role": "user", "content": "hi"}], message_text="hi")
    assert calls[-1]["reasoning_effort"] == "max"


def test_priority_group_order_wins_over_registry_priority() -> None:
    calls: list[dict[str, object]] = []
    groups = [
        {
            "name": "工作日高峰",
            "days": [1, 2, 3, 4, 5],
            "windows": [["09:00", "12:00"]],
            "order": ["second", "first", "ghost"],
        },
        {"name": "兜底", "order": ["second", "first"]},
    ]
    router = ModelRouter(
        {
            "first": _spec("first", "deepseek-v4-pro", 1),
            "second": _spec("second", "gpt-5.6-terra", 2),
        },
        provider_factory=lambda spec: _CaptureProvider(calls),
        priority_groups=lambda: groups,
    )
    # 无论实时时钟落在哪个组，组内 order 都压过 registry priority。
    assert router.route_ids(message_text="hi", override="")[:2] == ["second", "first"]
    # 周三 10:00 命中高峰组（ghost 不存在会在路由时被忽略）
    wednesday = datetime(2026, 9, 2, 10, 0, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    assert router._active_group_order(now=wednesday) == (
        "工作日高峰",
        ["second", "first", "ghost"],
    )
    # 周六 10:00 → 兜底组
    saturday = datetime(2026, 9, 5, 10, 0, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    assert router._active_group_order(now=saturday) == ("兜底", ["second", "first"])


def test_parse_priority_groups_and_window_resolution() -> None:
    raw = (
        '[{"name":"工作日高峰","days":[1,2,3,4,5],'
        '"windows":[["09:00","12:00"],["14:00","18:00"]],"order":["a","b"]},'
        '{"name":"兜底","order":["b"]}]'
    )
    groups = parse_priority_groups(raw)
    assert len(groups) == 2
    zone = ZoneInfo("Asia/Hong_Kong")
    # 周一 10:00 → 高峰组
    hit = resolve_active_priority_group(
        groups, datetime(2026, 8, 31, 10, 0, tzinfo=zone)
    )
    assert hit is not None and hit["name"] == "工作日高峰"
    # 周一 13:00 → 高峰组第一个窗口外、第二个窗口未到 → 兜底组
    lunch = resolve_active_priority_group(
        groups, datetime(2026, 8, 31, 13, 0, tzinfo=zone)
    )
    assert lunch is not None and lunch["name"] == "兜底"
    # 周日 10:00 → 兜底组
    sunday = resolve_active_priority_group(
        groups, datetime(2026, 9, 6, 10, 0, tzinfo=zone)
    )
    assert sunday is not None and sunday["name"] == "兜底"
    assert parse_priority_groups("not-json") == []
    assert parse_priority_groups("") == []


def test_build_model_router_reads_timezone_and_groups() -> None:
    config = SimpleNamespace(
        bot_model_registry={
            "a": {"model": "deepseek-v4-flash", "base_url": "https://x/v1", "api_key": "k", "tags": ["low", "high", "max"], "priority": 1}
        },
        bot_model_presets={},
        bot_chat_model="",
        bot_chat_fast_mode=False,
        bot_chat_timeout_seconds=30.0,
        bot_chat_fast_timeout_seconds=12.0,
        bot_download_proxy="",
        bot_chat_failover_max_seconds=0.0,
        bot_timezone="Asia/Hong_Kong",
        bot_model_priority_groups=[{"name": "兜底", "order": ["a"]}],
    )
    router = build_model_router(config, priority_groups=lambda: config.bot_model_priority_groups)
    assert router._active_group_order() == ("兜底", ["a"])


def test_pricing_parse_and_cost_milli() -> None:
    prices = parse_model_prices(
        '{"deepseek-v4-pro":{"input":4,"output":16},"bad":{"input":"x"}}'
    )
    assert prices["deepseek-v4-pro"] == {"input": 4.0, "output": 16.0}
    cost_milli, priced = model_call_cost_milli(
        "deepseek-v4-pro", 1_000_000, 500_000, prices
    )
    assert priced and cost_milli == 12_000  # 4 + 8 = 12 元 = 12000 毫厘
    assert format_milli_yuan(12_000) == "12.00"
    _, unpriced = model_call_cost_milli("unknown", 100, 100, prices)
    assert not unpriced
    assert parse_model_prices("") == {}
    assert parse_model_prices("not-json") == {}


def _fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        bot_model_registry={
            "ds": {
                "model": "deepseek-v4-pro",
                "base_url": "https://x/v1",
                "api_key": "env:BOT_API_KEY_X",
                "tags": ["low", "high", "max"],
                "priority": 1,
            }
        },
        bot_model_presets={},
        bot_chat_model="main",
        bot_model_auto_route=True,
        bot_model_priority_groups=[],
        bot_model_prices={},
    )


def _temp_dir() -> Path:
    """沙箱禁目录枚举，pytest tmp_path 不可用；改用 mkdtemp 精确路径。"""
    return Path(tempfile.mkdtemp(prefix="dsh-model-"))


def test_model_command_effort_and_price_roundtrip() -> None:
    store = RuntimeSettingsStore(_temp_dir() / "settings.json")
    config = _fake_config()

    set_result = _handle_model_command(store, config, ["effort", "ds", "high"])
    assert "思考强度已设为 high" in set_result
    assert store.list_model_registry()["ds"]["effort"] == "high"

    default_result = _handle_model_command(store, config, ["effort", "ds", "default"])
    assert "家族默认" in default_result
    assert "effort" not in store.list_model_registry()["ds"]

    assert "effort 必须是" in _handle_model_command(store, config, ["effort", "ds", "turbo"])
    assert "不存在的模型 id" in _handle_model_command(store, config, ["effort", "nope", "high"])

    priced = _handle_model_command(
        store, config, ["price", "deepseek-v4-pro", "input=4", "output=16"]
    )
    assert "已设置 deepseek-v4-pro 价格" in priced
    raw_prices = store.get_or("BOT_MODEL_PRICES", "")
    assert isinstance(raw_prices, str) and "deepseek-v4-pro" in raw_prices
    assert "BOT_MODEL_PRICES" in SETTABLE_KEYS

    cleared = _handle_model_command(store, config, ["price", "deepseek-v4-pro"])
    assert "回到未计价" in cleared


def test_model_usage_renders_cost_from_event_aggregate() -> None:
    store = RuntimeSettingsStore(_temp_dir() / "settings.json")
    config = _fake_config()
    usage_store = SimpleNamespace(
        aggregate_llm_usage_range=lambda start, end: {
            "prompt_tokens": 2_000_000,
            "completion_tokens": 500_000,
            "total_tokens": 2_500_000,
            "cache_read_tokens": 800_000,
            "cache_write_tokens": 100_000,
            "cost_milli": 12_000,
            "calls": 7,
            "by_model": {"deepseek-v4-pro": 2_500_000},
            "by_model_prompt": {"deepseek-v4-pro": 2_000_000},
            "by_model_completion": {"deepseek-v4-pro": 500_000},
            "by_model_cache_read": {"deepseek-v4-pro": 800_000},
            "by_model_cache_write": {"deepseek-v4-pro": 100_000},
            "by_model_cost_milli": {"deepseek-v4-pro": 12_000},
            "unpriced_calls": 2,
        }
    )
    result = _handle_model_command(
        store, config, ["usage"], usage_store=usage_store
    )
    assert "输入 2,000,000" in result
    assert "命中 800,000" in result
    assert "创建 100,000" in result
    assert "账单：12.00 元" in result
    assert "deepseek-v4-pro" in result
    assert "未配置价格" in result


def test_usage_monitor_thresholds_and_state() -> None:
    from plugins.bot_unified_runtime.runtime.usage_monitor import (
        build_report_text,
        build_threshold_alert,
        threshold_alert_items,
    )

    aggregate = {
        "prompt_tokens": 60_000_000,
        "completion_tokens": 6_000_000,
        "total_tokens": 66_000_000,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_milli": 15_000,
        "calls": 10,
        "by_model": {"big": 66_000_000},
        "by_model_prompt": {"big": 60_000_000},
        "by_model_completion": {"big": 6_000_000},
        "by_model_cost_milli": {"big": 15_000},
        "unpriced_calls": 0,
    }
    items = threshold_alert_items(aggregate)
    keys = {item["key"] for item in items}
    assert keys == {"out:big", "in:big", "cost"}
    below = threshold_alert_items(
        {
            "by_model_prompt": {"m": 1},
            "by_model_completion": {"m": 1},
            "cost_milli": 1,
        }
    )
    assert below == []
    alert = build_threshold_alert({"kind": "cost", "model": "", "value": 15_000, "limit": 10_000})
    assert "账单" in alert.what_happened
    report = build_report_text(aggregate, window_label="测试窗口")
    assert "15.00 元" in report
    assert "big" in report


def test_priority_groups_converter_accepts_json_array() -> None:
    converter = SETTABLE_KEYS["BOT_MODEL_PRIORITY_GROUPS"]
    raw = converter('[{"name":"高峰","order":["a"]}]')
    assert isinstance(raw, str) and "高峰" in raw
    try:
        converter("not-json")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for invalid JSON")
