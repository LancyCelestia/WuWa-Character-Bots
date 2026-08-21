from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.llm import LLMProviderError, LLMReply
from plugins.bot_unified_runtime.llm.model_router import (
    ModelRouter,
    ModelSpec,
    build_model_registry,
    build_model_router,
)


def _make_router() -> ModelRouter:
    specs = {
        "flash": ModelSpec(
            model_id="flash",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com/v1",
            api_key="key-ds",
            tags=("fast",),
            priority=1,
        ),
        "pro": ModelSpec(
            model_id="pro",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com/v1",
            api_key="key-ds",
            tags=("strong",),
            priority=2,
        ),
        "gemini-flash": ModelSpec(
            model_id="gemini-flash",
            model="gemini-3.7-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key="key-gemini",
            tags=("fast",),
            priority=5,
        ),
    }
    return ModelRouter(specs)


def test_route_default_goes_to_fast_tier():
    router = _make_router()

    ids = router.route_ids(message_text="今天天气怎么样", override="")

    assert ids[0] in {"flash", "gemini-flash"}
    assert "pro" in ids


def test_route_complex_task_goes_to_strong_tier():
    router = _make_router()

    ids = router.route_ids(message_text="请你一步一步教我怎么配置 NoneBot", override="")

    assert ids[0] == "pro"


def test_route_long_text_goes_to_strong_tier():
    router = _make_router()
    long_text = "内容" * 200

    ids = router.route_ids(message_text=long_text, override="")

    assert ids[0] == "pro"


def test_route_override_puts_chosen_model_first():
    router = _make_router()

    ids = router.route_ids(message_text="你好", override="pro")

    assert ids[0] == "pro"


def test_route_unknown_override_falls_back_to_auto():
    router = _make_router()

    ids = router.route_ids(message_text="你好", override="nonexistent")

    assert ids[0] in {"flash", "gemini-flash"}


def test_generate_fails_over_to_next_candidate():
    class FakeProvider:
        def __init__(self, spec: ModelSpec, fail: bool = False) -> None:
            self.spec = spec
            self.fail = fail

        def generate(self, messages, **kwargs):
            if self.fail:
                raise LLMProviderError("boom", error_kind="server")
            return LLMReply(
                text=f"replied-by-{self.spec.model_id}",
                provider="fake",
                model=self.spec.model,
                confidence=1.0,
            )

    def factory(spec: ModelSpec):
        return FakeProvider(spec, fail=spec.model_id == "flash")

    router = ModelRouter(
        {
            "flash": ModelSpec(
                model_id="flash",
                model="deepseek-v4-flash",
                base_url="x",
                api_key="k",
                tags=("fast",),
                priority=1,
            ),
            "pro": ModelSpec(
                model_id="pro",
                model="deepseek-v4-pro",
                base_url="x",
                api_key="k",
                tags=("strong",),
                priority=2,
            ),
        },
        provider_factory=factory,
    )

    reply = router.generate(
        [{"role": "user", "content": "你好"}],
        message_text="你好",
    )

    assert reply.text == "replied-by-pro"


def test_generate_all_candidates_fail_raises_last_error():
    class AlwaysFail:
        def generate(self, messages, **kwargs):
            raise LLMProviderError("down", error_kind="network")

    router = ModelRouter(
        {
            "flash": ModelSpec(
                model_id="flash",
                model="m",
                base_url="x",
                api_key="k",
                tags=("fast",),
                priority=1,
            ),
        },
        provider_factory=lambda spec: AlwaysFail(),
    )

    try:
        router.generate([{"role": "user", "content": "你好"}], message_text="你好")
    except LLMProviderError as exc:
        assert exc.error_kind == "network"
    else:  # pragma: no cover
        raise AssertionError("expected LLMProviderError")


def test_build_model_registry_resolves_env_key_reference(monkeypatch):
    monkeypatch.setenv("BOT_API_KEY_DEEPSEEK", "sk-real-key")
    config = Config(
        bot_model_registry={
            "flash": {
                "model": "deepseek-v4-flash",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "env:BOT_API_KEY_DEEPSEEK",
                "tags": ["fast"],
                "priority": 1,
            }
        }
    )

    registry = build_model_registry(config)
    assert registry["flash"].api_key == "sk-real-key"
    assert registry["flash"].model == "deepseek-v4-flash"


def test_build_model_router_falls_back_to_main_config():
    config = Config(
        bot_chat_model="my-model",
        bot_chat_base_url="https://x/v1",
        bot_chat_api_key="sk-main",
    )

    router = build_model_router(config)
    assert router.model_ids() == ["default"]
    assert router.specs["default"].model == "my-model"


def test_build_model_router_empty_when_nothing_configured():
    router = build_model_router(Config(bot_chat_model=""))
    assert router.model_ids() == []


def test_preset_name_override_resolves_to_preset_model():
    config = Config(
        bot_chat_model="my-model",
        bot_chat_base_url="https://x/v1",
        bot_chat_api_key="sk-main",
        bot_model_presets={"flash": "deepseek-v4-flash"},
    )
    router = build_model_router(config)

    ids = router.route_ids(message_text="你好", override="flash")

    assert ids[0] == "flash"
    assert router.specs["flash"].model == "deepseek-v4-flash"
    # 预设失败后回落到主配置模型。
    assert ids[1] == "default"


def test_presets_do_not_win_auto_routing():
    config = Config(
        bot_chat_model="my-model",
        bot_chat_base_url="https://x/v1",
        bot_chat_api_key="sk-main",
        bot_model_presets={"flash": "deepseek-v4-flash"},
    )
    router = build_model_router(config)

    ids = router.route_ids(message_text="你好", override="")

    assert ids[0] == "default"


def test_literal_override_uses_main_connection_with_full_model_name():
    config = Config(
        bot_chat_model="my-model",
        bot_chat_base_url="https://x/v1",
        bot_chat_api_key="sk-main",
    )
    router = build_model_router(config)

    ids = router.route_ids(message_text="你好", override="some-literal-model")

    assert ids[0] == "some-literal-model"
    spec = router._spec_for("some-literal-model")
    assert spec is not None and spec.model == "some-literal-model"
    assert spec.base_url == "https://x/v1" and spec.api_key == "sk-main"


def test_registry_wins_over_preset_name():
    config = Config(
        bot_chat_model="my-model",
        bot_model_presets={"flash": "preset-model-name"},
        bot_model_registry={
            "flash": {
                "model": "deepseek-v4-flash",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "k",
                "tags": ["fast"],
                "priority": 1,
            }
        },
    )
    router = build_model_router(config)

    assert router.specs["flash"].model == "deepseek-v4-flash"
    # 自动选型时注册表模型优先于主配置兜底模型。
    ids = router.route_ids(message_text="你好", override="")
    assert ids[0] == "flash"
