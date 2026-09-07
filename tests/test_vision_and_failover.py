from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.runtime_admin import (
    _handle_runtime_command,
)
from plugins.bot_unified_runtime.llm import LLMProviderError
from plugins.bot_unified_runtime.llm.model_router import ModelRouter
from plugins.bot_unified_runtime.runtime.settings import InstanceSettingsManager
from plugins.bot_unified_runtime.sources.vision_describe import (
    build_vision_provider,
    describe_images,
    extract_image_urls,
)


def test_extract_image_urls_from_segments() -> None:
    segments = [
        {"type": "text", "data": {"text": "看这个"}},
        {"type": "image", "data": {"url": "https://img.example/a.jpg"}},
        {"type": "mface", "data": {"url": "https://img.example/sticker.png"}},
        {"type": "image", "data": {"url": "https://img.example/a.jpg"}},
        {"type": "image", "data": {"file": "local_only.png"}},
        {"type": "image", "data": {"url": "not-a-url"}},
    ]
    assert extract_image_urls(segments) == [
        "https://img.example/a.jpg",
        "https://img.example/sticker.png",
    ]


def test_build_vision_provider_none_when_registry_empty() -> None:
    config = SimpleNamespace(
        bot_vision_enabled=True,
        bot_vision_model_registry={},
    )
    assert build_vision_provider(config) is None


def test_build_vision_provider_accepts_list_groups() -> None:
    config = SimpleNamespace(
        bot_vision_enabled=True,
        bot_vision_model_registry={
            "myvlm": [
                {"model": "vlm-1", "base_url": "https://v/v1", "api_key": "sk", "priority": 1},
                {"model": "vlm-2", "base_url": "https://v/v1", "api_key": "sk", "priority": 2},
            ]
        },
    )
    provider = build_vision_provider(config)
    assert provider is not None
    assert provider.is_enabled() is True
    merged = provider._merged_entries()
    assert set(merged) == {"myvlm#1", "myvlm#2"}
    assert merged["myvlm#1"]["model"] == "vlm-1"


def test_vision_enabled_hot_toggle_via_store() -> None:
    import tempfile
    from pathlib import Path

    from plugins.bot_unified_runtime.runtime.settings import RuntimeSettingsStore

    store = RuntimeSettingsStore(
        Path(tempfile.mkdtemp(prefix="dsh-vision-")) / "settings.json"
    )
    config = SimpleNamespace(
        bot_vision_enabled=False,
        bot_vision_model_registry={
            "v": {"model": "vlm", "base_url": "https://v/v1", "api_key": "sk"}
        },
    )
    provider = build_vision_provider(
        config, dynamic_registry=store.list_vision_registry, settings_store=store
    )
    assert provider is not None
    assert provider.is_enabled() is False
    store.set_override("BOT_VISION_ENABLED", "true")
    assert provider.is_enabled() is True


def test_dynamic_vision_provider_failover(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.bot_unified_runtime.sources import vision_describe

    calls: list[str] = []

    class _FakeInner:
        def __init__(self, *, api_key: str, model: str, base_url: str, proxy: str, timeout_seconds: float):
            self.model = model

        def generate(self, messages, **kwargs):
            calls.append(self.model)
            if self.model == "glm-53":
                raise LLMProviderError("rate limited", error_kind="rate_limited")
            return SimpleNamespace(text="ok", provider="x", model="x", confidence=1.0)

    monkeypatch.setattr(vision_describe, "OpenAICompatibleLLMProvider", _FakeInner)
    config = SimpleNamespace(
        bot_vision_enabled=True,
        bot_download_proxy="",
        bot_vision_timeout_seconds=5.0,
        bot_vision_model_registry={
            "myvlm": [
                {"model": "glm-53", "base_url": "https://a/v1", "api_key": "k", "priority": 1},
                {"model": "glm-46v", "base_url": "https://a/v1", "api_key": "k", "priority": 2},
            ]
        },
    )
    wrapper = build_vision_provider(config)
    assert wrapper is not None
    result = describe_images(wrapper, image_urls=["https://img.example/1.jpg"])
    assert result == "ok"
    assert calls == ["glm-53", "glm-46v"]
    assert "myvlm#2:success" in wrapper.last_attempts


class _CaptureProvider:
    def __init__(self, *, text: str = "角色：守岸人（鸣潮）\n文字：无\n画面：一只蓝蝴蝶停在指尖。", fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls: list[list[dict]] = []

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        if self.fail:
            raise LLMProviderError("boom", error_kind="server")
        return SimpleNamespace(text=self.text, provider="fake", model="fake", confidence=1.0)


def test_describe_images_builds_multimodal_message_and_caps_images() -> None:
    provider = _CaptureProvider()
    urls = ["https://img.example/1.jpg", "https://img.example/2.jpg"]
    result = describe_images(provider, image_urls=urls, query_text="看这个", max_images=1)

    assert result.startswith("角色：守岸人")
    user_message = provider.calls[0][1]
    content = user_message["content"]
    assert isinstance(content, list)
    image_parts = [part for part in content if part["type"] == "image_url"]
    assert [part["image_url"]["url"] for part in image_parts] == urls[:1]
    assert "看这个" in content[0]["text"]


def test_describe_images_failure_returns_empty() -> None:
    provider = _CaptureProvider(fail=True)
    assert describe_images(provider, image_urls=["https://img.example/1.jpg"]) == ""


def test_describe_images_long_text_clipped() -> None:
    provider = _CaptureProvider(text="角" * 900)
    result = describe_images(
        provider, image_urls=["https://img.example/1.jpg"], max_chars=500
    )
    assert len(result) == 500
    assert result.endswith("…")


def _failing_provider_factory(delays: float = 0.0):
    def factory(spec: object) -> object:
        def generate(messages, **kwargs):
            if delays:
                time.sleep(delays)
            raise LLMProviderError("timed out", error_kind="timeout")

        return SimpleNamespace(generate=generate)

    return factory


def _spec(model_id: str, priority: int):
    from plugins.bot_unified_runtime.llm.model_router import ModelSpec

    return ModelSpec(
        model_id=model_id,
        model=f"m-{model_id}",
        base_url="https://x/v1",
        api_key="sk",
        tags=("fast",),
        priority=priority,
    )


def test_router_failover_deadline_stops_retry_chain() -> None:
    router = ModelRouter(
        {
            "c1": _spec("c1", 1),
            "c2": _spec("c2", 2),
            "c3": _spec("c3", 3),
        },
        provider_factory=_failing_provider_factory(delays=0.05),
        max_failover_seconds=0.06,
    )
    with pytest.raises(LLMProviderError):
        router.generate([{"role": "user", "content": "hi"}])
    assert "failover:deadline" in router.last_attempts
    assert len(router.last_attempts) < 4  # 没有把 3 个候选全部试完


def test_router_without_deadline_tries_all_candidates() -> None:
    router = ModelRouter(
        {
            "c1": _spec("c1", 1),
            "c2": _spec("c2", 2),
        },
        provider_factory=_failing_provider_factory(delays=0.0),
        max_failover_seconds=0.0,
    )
    with pytest.raises(LLMProviderError):
        router.generate([{"role": "user", "content": "hi"}])
    assert router.last_attempts == ["c1:timeout", "c2:timeout"]


def test_model_top_level_command_via_runtime_handler() -> None:
    import tempfile
    from pathlib import Path

    manager = InstanceSettingsManager(
        Path(tempfile.mkdtemp(prefix="dsh-inst-")) / "settings"
    )
    config = SimpleNamespace(
        bot_model_registry={},
        bot_model_presets={"terra": "gpt-5.6-terra"},
        bot_chat_model="main-model",
        bot_model_auto_route=True,
    )
    output = _handle_runtime_command(manager, "default", config, "model list")
    assert "当前模型：" in output
    assert "/bot model" in output

    added = _handle_runtime_command(
        manager,
        "default",
        config,
        "model add my model=m1 base_url=https://d.example/v1 key=sk-1 priority=2",
    )
    assert "已新增自定义模型 my" in added
    listed = _handle_runtime_command(manager, "default", config, "model list")
    assert "https://d.example/v1" in listed
    assert "sk-1" not in listed


def test_direct_vision_message_builder_attaches_images_only_once() -> None:
    from plugins.bot_unified_runtime.capabilities.chat import (
        build_direct_vision_messages,
    )

    messages = build_direct_vision_messages(
        [{"role": "system", "content": "system"}],
        query_text="看图",
        image_urls=["https://img.example/a.jpg", "https://img.example/a.jpg"],
        max_images=2,
    )
    assert messages[-1]["role"] == "user"
    content = messages[-1]["content"]
    assert isinstance(content, list)
    assert [item["type"] for item in content] == ["text", "image_url"]
    assert content[1]["image_url"]["url"] == "https://img.example/a.jpg"


def test_vision_command_roundtrip() -> None:
    import tempfile
    from pathlib import Path

    from plugins.bot_unified_runtime.capabilities.runtime_admin import (
        _handle_model_command,
    )
    from plugins.bot_unified_runtime.runtime.settings import RuntimeSettingsStore

    store = RuntimeSettingsStore(
        Path(tempfile.mkdtemp(prefix="dsh-vision-")) / "s.json"
    )
    config = SimpleNamespace(
        bot_vision_enabled=True,
        bot_vision_model_registry={
            "myvlm": [
                {"model": "vlm-1", "base_url": "https://v/v1", "api_key": "sk", "priority": 1}
            ]
        },
    )
    listed = _handle_model_command(store, config, ["vision", "list"])
    assert "myvlm#1" in listed
    assert "vlm-1" in listed
    assert "sk" not in listed

    added = _handle_model_command(
        store, config, ["vision", "add", "alt", "model=v2", "base_url=https://b/v1", "key=sk-b"]
    )
    assert "已新增视觉模型 alt" in added
    assert store.list_vision_registry()["alt"]["model"] == "v2"

    prioritized = _handle_model_command(store, config, ["vision", "priority", "alt", "0"])
    assert "1" in prioritized
    assert store.list_vision_registry()["alt"]["priority"] == 1
    assert store.list_vision_registry()["myvlm#1"]["priority"] == 2

    mode = _handle_model_command(store, config, ["vision", "mode", "direct"])
    assert "direct" in mode
    assert store.get_or("BOT_VISION_MODE", "relay") == "direct"

    removed = _handle_model_command(store, config, ["vision", "remove", "alt"])
    assert "已删除" in removed
    assert "alt" not in store.list_vision_registry()
