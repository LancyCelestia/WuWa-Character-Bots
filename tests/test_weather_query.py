from plugins.bot_unified_runtime.capabilities.weather import (
    build_weather_capability,
    is_weather_command,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.sources.nmc_weather import (
    find_city_code,
    list_districts,
    nmc_weather_query,
    search_city_code,
)


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="test",
        adapter="test",
        bot_id="bot",
        session_id="s1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
    )


def test_city_code_search():
    assert search_city_code("北京") == "Wqsps"
    assert search_city_code("昌平")
    assert find_city_code("广东", "广州")
    assert find_city_code("河北省", "大城")
    assert search_city_code("不存在的城市") is None


def test_list_districts():
    result = list_districts("北京")
    assert result["province"] == "北京市"
    assert "北京" in result["districts"]


def test_weather_command_parsing():
    assert is_weather_command("天气 北京")
    assert is_weather_command("查天气 广东-广州")
    assert not is_weather_command("天气")


def test_weather_capability_result(monkeypatch):
    from plugins.bot_unified_runtime.capabilities import weather as weather_module

    monkeypatch.setattr(
        weather_module,
        "nmc_weather_query",
        lambda query, **kwargs: "【北京市北京天气】\n🌡 温度：27.1℃",
    )

    capability = build_weather_capability()
    result = capability(_message("天气 北京"), None)

    assert result.capability_id == "bot.weather"
    assert "27.1℃" in result.body
    assert "weather_source:nmc" in result.audit_tags


def test_weather_capability_not_found(monkeypatch):
    from plugins.bot_unified_runtime.capabilities import weather as weather_module

    monkeypatch.setattr(
        weather_module, "nmc_weather_query", lambda query, **kwargs: None
    )

    capability = build_weather_capability()
    result = capability(_message("天气 不存在的地方"), None)

    assert "weather_not_found" in result.audit_tags


def test_weather_district_command(monkeypatch):
    from plugins.bot_unified_runtime.capabilities import weather as weather_module

    monkeypatch.setattr(
        weather_module,
        "list_districts",
        lambda province: {"province": "北京市", "districts": ["北京", "昌平"]},
    )

    capability = build_weather_capability()
    result = capability(_message("支持区县 北京"), None)

    assert "昌平" in result.body
