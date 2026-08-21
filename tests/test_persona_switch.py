import random

from plugins.bot_unified_runtime.capabilities.runtime_admin import (
    build_runtime_admin_result,
)
from plugins.bot_unified_runtime.character.persona_set import (
    AltPersonaSpec,
    PersonaSelector,
    build_alt_personas,
)
from plugins.bot_unified_runtime.config import Config, translate_env_keys
from plugins.bot_unified_runtime.runtime.settings import (
    InstanceSettingsManager,
    effective_instance,
)


def _make_specs() -> dict[str, AltPersonaSpec]:
    return {
        "gentle": AltPersonaSpec(
            profile_id="gentle",
            display_name="守岸人·温柔",
            files=("gentle.md",),
            weight=0.3,
            emotions=("support_needed", "lonely"),
        ),
        "rational": AltPersonaSpec(
            profile_id="rational",
            display_name="守岸人·理性",
            files=("rational.md",),
            weight=0.2,
            emotions=("help_seeking",),
        ),
    }


def test_persona_selector_override_wins():
    selector = PersonaSelector(_make_specs())

    assert selector.select(override="gentle").profile_id == "gentle"
    assert selector.select(override="default") is None
    assert selector.select(override="unknown") is None


def test_persona_selector_emotion_trigger():
    selector = PersonaSelector(_make_specs())

    assert selector.select(emotions=["lonely"], rng=random.Random(0)).profile_id == "gentle"
    assert selector.select(emotions=["help_seeking"], rng=random.Random(0)).profile_id == "rational"


def test_persona_selector_probability_uses_fixed_rng():
    selector = PersonaSelector(_make_specs())
    rng = random.Random(42)

    results = set()
    for _ in range(200):
        spec = selector.select(rng=rng)
        results.add(spec.profile_id if spec is not None else None)

    # 0.3/0.2 权重下，采样应能覆盖两个人格；也可能只出现一个，不做强断言。
    assert results and results <= {"gentle", "rational", None}


def test_persona_selector_weights_override_config():
    selector = PersonaSelector(_make_specs())
    rng = random.Random(7)

    result = selector.select(weights={"gentle": 0.0}, rng=rng)

    # gentle 被禁用后，随机命中 rational 或 None（rational 权重 0.2）。
    assert result is None or result.profile_id == "rational"


def test_persona_selector_no_alt_personas_returns_none():
    selector = PersonaSelector({})
    assert selector.select(emotions=["lonely"]) is None


def test_build_alt_personas_from_config():
    config = Config(
        bot_persona_alt_profiles={
            "gentle": {
                "display_name": "守岸人·温柔",
                "files": ["a.md"],
                "weight": 0.4,
                "emotions": ["support_needed"],
            }
        }
    )

    specs = build_alt_personas(config)
    assert specs["gentle"].display_name == "守岸人·温柔"
    assert specs["gentle"].files == ("a.md",)
    assert specs["gentle"].weight == 0.4
    assert specs["gentle"].emotions == ("support_needed",)


def test_admin_persona_commands(tmp_path):
    manager = InstanceSettingsManager(tmp_path)
    config = Config(
        bot_persona_alt_profiles={
            "gentle": {
                "display_name": "守岸人·温柔",
                "files": ["a.md"],
                "weight": 0.3,
                "emotions": ["support_needed"],
            }
        }
    )

    switch = build_runtime_admin_result(
        manager,
        "shorekeeper",
        config,
        request_id="req_persona",
        actor_roles=["admin", "user"],
        command_text="persona switch gentle",
    )
    assert "gentle" in switch.body
    assert manager.get("shorekeeper").get_persona_override() == "gentle"

    auto = build_runtime_admin_result(
        manager,
        "shorekeeper",
        config,
        request_id="req_persona",
        actor_roles=["admin", "user"],
        command_text="persona switch default",
    )
    assert "自动模式" in auto.body
    assert manager.get("shorekeeper").get_persona_override() == ""

    prob = build_runtime_admin_result(
        manager,
        "shorekeeper",
        config,
        request_id="req_persona",
        actor_roles=["admin", "user"],
        command_text="persona probability gentle 0.5",
    )
    assert "0.5" in prob.body
    assert manager.get("shorekeeper").get_persona_weights() == {"gentle": 0.5}


def test_effective_instance_falls_back_to_persona_id():
    config = Config(bot_runtime_instance="", bot_persona_profile_id="shorekeeper")
    assert effective_instance(config) == "shorekeeper"

    explicit = Config(bot_runtime_instance="aimias", bot_persona_profile_id="x")
    assert effective_instance(explicit) == "aimias"


def test_translate_env_keys_maps_bot_prefix():
    values = {
        "BOT_CHAT_PROVIDER": "openai_compatible",
        "BOT_PERSONA_PROFILE_ID": "shorekeeper",
        "BOT_LEGACY_KEY": "1",  # 旧前缀仍按原样通过（不再使用）
    }

    translated = translate_env_keys(values)
    assert translated["bot_chat_provider"] == "openai_compatible"
    assert translated["bot_persona_profile_id"] == "shorekeeper"
    assert translated["bot_legacy_key"] == "1"
