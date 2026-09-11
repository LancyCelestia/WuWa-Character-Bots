"""B10 杂项批 · 气象预警支路回归（离线 fixture，不外呼）。

交付点：
1. NMC findAlarm 预警支路（fetch_city_alerts/format_city_alerts）解析与过滤；
2. 接口不可达 / 无命中 → 静默空列表；
3. 城市命中时天气回复附带预警段 + audit tag；海外源（open-meteo）不带预警。

fixture 条目取自 2026-09-12 curl 实测 findAlarm 响应（第三条为覆盖
蓝色等级排序的合成变体，结构一致）。
"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.capabilities.weather import (
    build_weather_capability,
    fetch_city_alerts,
    format_city_alerts,
    parse_alert_title,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError

_FIND_ALARM_FIXTURE: dict[str, Any] = {
    "msg": "success",
    "code": 0,
    "data": {
        "page": {
            "pageNo": 1,
            "pageSize": 300,
            "count": 3,
            "list": [
                {
                    "alertid": "a1",
                    "issuetime": "2026/09/12 03:05",
                    "title": "黑龙江省大兴安岭地区呼玛县气象台发布大雾黄色预警信号",
                    "url": "/publish/alarm/a1.html",
                    "pic": "https://image.nmc.cn/assets/img/alarm/p0005003.png",
                },
                {
                    "alertid": "a2",
                    "issuetime": "2026/09/12 02:09",
                    "title": "贵州省黔西南布依族苗族自治州安龙县气象台发布大雾橙色预警信号",
                    "url": "/publish/alarm/a2.html",
                    "pic": "https://image.nmc.cn/assets/img/alarm/p0005002.png",
                },
                {
                    "alertid": "a3",
                    "issuetime": "2026/09/12 03:39",
                    "title": "辽宁省锦州市黑山县气象台发布大风蓝色预警信号",
                    "url": "/publish/alarm/a3.html",
                    "pic": "https://image.nmc.cn/assets/img/alarm/p0001001.png",
                },
            ],
        }
    },
}


def _patch_alarm_http(monkeypatch, payload: Any) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.http_get_json",
        lambda *args, **kwargs: payload,
    )


def _private_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:user1",
        session_type=SessionType.PRIVATE,
        sender_id="user1",
        plain_text=text,
    )


def test_parse_alert_title_extracts_kind_and_color() -> None:
    assert parse_alert_title("黑龙江省…呼玛县气象台发布大雾黄色预警信号") == ("大雾", "黄色")
    assert parse_alert_title("辽宁省锦州市黑山县气象台发布大风蓝色预警信号") == ("大风", "蓝色")
    assert parse_alert_title("某地发布寒潮预警") == ("寒潮", "")
    assert parse_alert_title("") == ("", "")


def test_fetch_city_alerts_filters_by_all_tokens(monkeypatch) -> None:
    _patch_alarm_http(monkeypatch, _FIND_ALARM_FIXTURE)
    hits = fetch_city_alerts("黑龙江-呼玛")
    assert len(hits) == 1
    assert hits[0]["kind"] == "大雾"
    assert hits[0]["color"] == "黄色"
    assert hits[0]["issued"] == "2026/09/12 03:05"
    assert hits[0]["url"] == "https://www.nmc.cn/publish/alarm/a1.html"
    # 单 token 也能命中（呼玛 全库唯一语境）。
    assert len(fetch_city_alerts("安龙")) == 1
    # 无命中 → 空。
    assert fetch_city_alerts("nowhereland") == []
    assert fetch_city_alerts("") == []


def test_fetch_city_alerts_sorts_higher_level_first(monkeypatch) -> None:
    payload = {
        "data": {
            "page": {
                "list": [
                    _FIND_ALARM_FIXTURE["data"]["page"]["list"][2],
                    _FIND_ALARM_FIXTURE["data"]["page"]["list"][1],
                ]
            }
        }
    }
    _patch_alarm_http(monkeypatch, payload)
    hits = fetch_city_alerts("县")
    assert [item["color"] for item in hits] == ["橙色", "蓝色"]


def test_fetch_city_alerts_unreachable_returns_empty(monkeypatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise ParseHttpError("GET failed: HTTP 503", status_code=503)

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.http_get_json", _boom
    )
    assert fetch_city_alerts("呼玛") == []


def test_format_city_alerts_renders_entry_lines(monkeypatch) -> None:
    _patch_alarm_http(monkeypatch, _FIND_ALARM_FIXTURE)
    alerts = fetch_city_alerts("黑龙江-呼玛")
    body = format_city_alerts(alerts)
    assert "气象预警" in body
    assert "黄色大雾预警" in body
    assert "2026/09/12 03:05" in body
    assert format_city_alerts([]) == ""


def test_capability_appends_alerts_on_nmc_hit_only(monkeypatch) -> None:
    _patch_alarm_http(monkeypatch, _FIND_ALARM_FIXTURE)
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.nmc_weather_query",
        lambda query, proxy="": "【测试天气】晴 25℃",
    )
    capability = build_weather_capability(config=None, render_backend=None)
    result = capability(_private_message("天气 黑龙江-呼玛"), None)
    assert "【测试天气】晴 25℃" in result.body
    assert "气象预警" in result.body
    assert "weather_alerts:1" in result.audit_tags

    # 海外源（open-meteo）：NMC 预警语义不适用，不附带预警段。
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.nmc_weather_query",
        lambda query, proxy="": None,
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.open_meteo_query",
        lambda query, proxy="": {"latitude": 35.0, "current": {}},
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.format_open_meteo",
        lambda payload: "【海外】Sunny",
    )
    overseas = capability(_private_message("天气 Tokyo"), None)
    assert "气象预警" not in overseas.body
    assert "【海外】Sunny" in overseas.body
    assert not any(tag.startswith("weather_alerts") for tag in overseas.audit_tags)
