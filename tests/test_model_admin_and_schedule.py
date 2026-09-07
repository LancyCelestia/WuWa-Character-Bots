from __future__ import annotations

import tempfile
from datetime import time as dt_time
from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.runtime_admin import (
    _handle_model_command,
)
from plugins.bot_unified_runtime.llm import LLMProviderError
from plugins.bot_unified_runtime.llm.model_router import ModelRouter
from plugins.bot_unified_runtime.runtime.model_schedule import (
    parse_model_schedule,
    resolve_scheduled_model,
)
from plugins.bot_unified_runtime.runtime.settings import (
    SETTABLE_KEYS,
    RuntimeSettingsStore,
)


def _temp_dir() -> Path:
    """pytest tmp_path 依赖目录枚举，沙箱环境下不可用；改用 mkdtemp 精确路径。"""
    return Path(tempfile.mkdtemp(prefix="dsh-settings-"))


def test_resolve_scheduled_model_windows() -> None:
    schedule = parse_model_schedule({"07:00-23:00": "terra", "23:00-07:00": "luna"})
    assert resolve_scheduled_model(schedule, dt_time(12, 0)) == "terra"
    assert resolve_scheduled_model(schedule, dt_time(23, 30)) == "luna"
    assert resolve_scheduled_model(schedule, dt_time(3, 0)) == "luna"
    assert resolve_scheduled_model(schedule, dt_time(7, 0)) == "terra"


def test_resolve_scheduled_model_ignores_invalid_entries() -> None:
    schedule = parse_model_schedule({"bad-window": "x", "08:00-09:00": "y"})
    assert set(schedule) == {"08:00-09:00"}
    assert resolve_scheduled_model(schedule, dt_time(10, 0)) == ""
    assert parse_model_schedule("not-json") == {}


class _RecordingFactory:
    def __init__(self) -> None:
        self.specs: list[object] = []

    def __call__(self, spec: object) -> object:
        self.specs.append(spec)
        return SimpleNamespace(
            generate=lambda messages, **kwargs: SimpleNamespace(
                text="ok", provider="fake", model="fake", confidence=1.0
            )
        )


def test_router_dynamic_registry_merge_update_and_remove() -> None:
    factory = _RecordingFactory()
    registry: dict[str, dict[str, object]] = {
        "my-model": {
            "model": "m1",
            "base_url": "https://dynamic.example/v1",
            "api_key": "dk",
            "tags": ["fast"],
            "priority": 1,
        }
    }
    router = ModelRouter(
        {},
        provider_factory=factory,
        dynamic_registry=lambda: registry,
    )

    reply = router.generate([{"role": "user", "content": "hi"}], override="my-model")
    assert reply.text == "ok"
    assert factory.specs[-1].base_url == "https://dynamic.example/v1"

    # 更新条目：provider 缓存失效，用新 base_url 重建。
    registry["my-model"] = {
        "model": "m2",
        "base_url": "https://changed.example/v1",
        "api_key": "dk",
        "priority": 1,
    }
    router.generate([{"role": "user", "content": "hi"}], override="my-model")
    assert factory.specs[-1].model == "m2"
    assert factory.specs[-1].base_url == "https://changed.example/v1"

    # 删除条目：无法解析 override，也没有任何候选 → 明确报错。
    del registry["my-model"]
    try:
        router.generate([{"role": "user", "content": "hi"}], override="my-model")
    except LLMProviderError:
        pass
    else:  # pragma: no cover - 断言失败路径
        raise AssertionError("expected LLMProviderError after registry removal")


def _fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        bot_model_registry={},
        bot_model_presets={"terra": "gpt-5.6-terra"},
        bot_chat_model="main-model",
        bot_model_auto_route=True,
    )


def test_model_command_add_update_remove_roundtrip() -> None:
    store = RuntimeSettingsStore(_temp_dir() / "settings.json")
    config = _fake_config()

    added = _handle_model_command(
        store,
        config,
        ["add", "my", "model=m1", "base_url=https://d.example/v1", "key=sk-secret"],
    )
    assert "已新增自定义模型 my" in added
    entry = store.list_model_registry()["my"]
    assert entry["model"] == "m1"
    assert entry["api_key"] == "sk-secret"

    listed = _handle_model_command(store, config, ["list"])
    assert "故障转移顺序" in listed
    assert "https://d.example/v1" in listed
    assert "sk-secret" not in listed  # 密钥绝不回显

    prioritized = _handle_model_command(store, config, ["priority", "my", "5"])
    # Slot semantics: one registered model can only occupy slot 1.
    assert "槽位 1" in prioritized
    assert store.list_model_registry()["my"]["priority"] == 1

    removed = _handle_model_command(store, config, ["remove", "my"])
    assert "已删除" in removed
    assert store.list_model_registry() == {}


def test_model_command_set_accepts_runtime_ids() -> None:
    store = RuntimeSettingsStore(_temp_dir() / "settings.json")
    config = _fake_config()
    _handle_model_command(
        store,
        config,
        ["add", "my", "model=m1", "base_url=https://d.example/v1"],
    )
    switched = _handle_model_command(store, config, ["set", "my"])
    assert "已手动指定模型：my" in switched
    assert store.get_or("BOT_CHAT_MODEL", "") == "my"


def test_model_commands_control_reasoning_effort_and_web_search() -> None:
    store = RuntimeSettingsStore(_temp_dir() / "settings.json")
    config = _fake_config()

    assert "reasoning" in _handle_model_command(store, config, ["think", "high"]).lower()
    assert store.get_or("BOT_CHAT_REASONING_EFFORT", "") == "high"
    assert "search" in _handle_model_command(store, config, ["search", "on"]).lower()
    assert store.get_or("BOT_WEB_SEARCH_ENABLED", False) is True
    assert "BOT_CHAT_REASONING_EFFORT" in SETTABLE_KEYS
    assert "BOT_WEB_SEARCH_ENABLED" in SETTABLE_KEYS


def test_model_reasoning_effort_rejects_unknown_value() -> None:
    store = RuntimeSettingsStore(_temp_dir() / "settings.json")
    config = _fake_config()
    result = _handle_model_command(store, config, ["think", "turbo"])
    assert "off/low/medium/high" in result


def test_model_usage_aggregates_safe_diagnostics() -> None:
    store = RuntimeSettingsStore()
    config = _fake_config()
    diagnostics = SimpleNamespace(
        list_recent=lambda limit: [
            SimpleNamespace(
                llm_model="terra",
                llm_usage_prompt_tokens=10,
                llm_usage_completion_tokens=4,
                llm_usage_total_tokens=14,
            ),
            SimpleNamespace(
                llm_model="terra",
                llm_usage_prompt_tokens=3,
                llm_usage_completion_tokens=2,
                llm_usage_total_tokens=5,
            ),
        ]
    )
    result = _handle_model_command(store, config, ["usage"], diagnostics_store=diagnostics)
    assert "输入 13" in result
    assert "输出 6" in result
    assert "总计 19" in result
    assert "terra" in result


def test_command_module_aliases_preserve_model_parameters() -> None:
    from plugins.bot_unified_runtime.runtime.aliases import normalize_command_text

    assert normalize_command_text("Model SET Terra") == "model set Terra"
    assert normalize_command_text("模型 添加 MyAPI model=Foo") == "model add MyAPI model=Foo"
    assert normalize_command_text("设置 模型 set MyModel") == "runtime model set MyModel"
    assert normalize_command_text("HELP 模型") == "help 模型"


def test_model_help_is_unique_and_covers_runtime_controls() -> None:
    from plugins.bot_unified_runtime.capabilities.echo import (
        _HELP_CATEGORIES,
        _HELP_ENTRIES,
        build_help_result,
    )

    assert [entry["topic"] for entry in _HELP_ENTRIES].count("模型") == 1
    assert [category for category, _topics in _HELP_CATEGORIES] == [
        "管理员专属",
        "大模型相关",
        "子功能",
    ]
    result = build_help_result(request_id="help-test", query="模型", is_admin=True)
    assert "/bot model think" in result.body
    assert "/bot model search" in result.body
    assert "/bot model usage" in result.body
    assert "/bot model vision mode" in result.body
