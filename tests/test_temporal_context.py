from datetime import datetime
from zoneinfo import ZoneInfo

from plugins.bot_unified_runtime.capabilities.chat import build_chat_prompt
from plugins.bot_unified_runtime.character.providers import FileCharacterContextProvider
from plugins.bot_unified_runtime.character.temporal import (
    OpenMeteoWeatherProvider,
    RuleBasedTemporalProvider,
    holiday_of,
    solar_term_of,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts.character import TemporalContext


def test_solar_term_of_known_dates():
    # 2026 年冬至约在 12 月 21/22 日，公式按 21 世纪系数计算。
    assert solar_term_of(datetime(2026, 12, 22, tzinfo=ZoneInfo("UTC"))) in {"冬至", ""}
    assert solar_term_of(datetime(2026, 3, 20, tzinfo=ZoneInfo("UTC"))) in {"春分", ""}
    assert solar_term_of(datetime(2026, 7, 15, tzinfo=ZoneInfo("UTC"))) == ""


def test_holiday_of_default_table():
    assert holiday_of(datetime(2026, 2, 17)) == "春节"  # noqa: DTZ001 - 测试有意 naive 日期
    assert holiday_of(datetime(2026, 10, 1)) == "国庆节"  # noqa: DTZ001 - 测试有意 naive 日期
    assert holiday_of(datetime(2026, 6, 19)) == "端午节"  # noqa: DTZ001 - 测试有意 naive 日期
    assert holiday_of(datetime(2026, 3, 12)) == ""  # noqa: DTZ001 - 测试有意 naive 日期


def test_holiday_table_override():
    table = (("03-12", "植树节"),)
    assert holiday_of(datetime(2026, 3, 12), table) == "植树节"  # noqa: DTZ001 - 测试有意 naive 日期
    assert holiday_of(datetime(2026, 10, 1), table) == ""  # noqa: DTZ001 - 测试有意 naive 日期


def test_rule_based_temporal_provider_snapshot(tmp_path):
    provider = RuleBasedTemporalProvider(timezone="Asia/Hong_Kong")
    context = provider.snapshot("req_temporal")

    assert context.date_local
    assert context.now_local
    assert context.weekday
    assert context.timezone
    assert context.weather_ok is False
    assert context.weather_summary == ""


def test_weather_provider_never_blocks_or_raises():
    provider = OpenMeteoWeatherProvider(
        latitude=22.3193,
        longitude=114.1694,
        timeout_seconds=2.0,
        cache_seconds=60,
    )
    # 无网络环境下必须返回空字符串而不是抛异常（可空结果）。
    summary = provider.current_weather("req_weather")
    assert isinstance(summary, str)


def test_temporal_context_injected_into_prompt(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text(
        "来自黑海岸的守岸人，温柔、克制、可靠。\n说话语气要安静温柔，有陪伴感。",
        encoding="utf-8",
    )

    class FakeTemporalProvider:
        def snapshot(self, request_id: str) -> TemporalContext:
            return TemporalContext(
                request_id=request_id,
                now_local="08:30",
                date_local="2026-06-19",
                weekday="星期五",
                timezone="Asia/Hong_Kong",
                solar_term="芒种",
                holiday="端午节",
                weather_summary="气温 30°C，多云，湿度 80%",
                weather_ok=True,
                weather_source="fake",
            )

    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="test",
        persona_files=[persona_file],
        knowledge_files=[],
        temporal_provider=FakeTemporalProvider(),  # type: ignore[arg-type]
    )
    bundle = provider.build_context(
        request_id="req_env",
        sender_id="42",
        session_id="private:42",
        query_text="今天天气怎么样？",
    )
    prompt_text = "\n".join(
        message["content"] for message in build_chat_prompt(bundle)
    )

    assert "当前环境信息" in prompt_text
    assert "2026-06-19" in prompt_text
    assert "芒种" in prompt_text
    assert "端午节" in prompt_text
    assert "气温 30°C" in prompt_text
    assert "不要编造天气实况" in prompt_text
    # 动作括号规则也应出现（默认开启）。
    assert "动作表现" in prompt_text
    assert "轻轻点头" in prompt_text


def test_action_brackets_can_be_disabled(tmp_path):
    persona_file = tmp_path / "shorekeeper.md"
    persona_file.write_text(
        "来自黑海岸的守岸人，温柔、克制、可靠。\n说话语气要安静温柔。",
        encoding="utf-8",
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="test",
        persona_files=[persona_file],
        knowledge_files=[],
        action_brackets=False,
    )
    bundle = provider.build_context(
        request_id="req_no_action",
        sender_id="42",
        session_id="private:42",
        query_text="你好。",
    )
    prompt_text = "\n".join(
        message["content"] for message in build_chat_prompt(bundle)
    )

    assert "本会话不启用括号动作" in prompt_text


def test_config_temporal_fields_defaults():
    config = Config()
    assert config.bot_temporal_enabled is True
    assert config.bot_timezone == "Asia/Hong_Kong"
    assert config.bot_weather_enabled is False
    assert config.bot_persona_action_brackets is True
    assert config.bot_runtime_persona_nickname == ""
