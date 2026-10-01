"""NMCFIX · NMC 主通道瞬时失败重试回归（离线 fixture，不外呼）。

背景（2026-09-12 复测）：NMC rest/weather 主接口本身存活（curl 与项目链路
均拿到全量数据，无 cookie 墙；`data:""` 是无/无效 stationid 的固定响应），
真实缺陷是单次尝试——瞬时超时/空 data（实测约 1/8）即静默降级 Open-Meteo、
预警支路随之跳过。本文件锁定：

1. 码表命中的城市：首次失败 → 重试一次成功；
2. 码表未命中（海外/乡镇）：零外呼零重试，立即走全球兜底；
3. 重试耗尽 → None（上层照旧降级，不抛出）；
4. capability 级：主通道重试恢复后，NMC 预警支路随之恢复。
"""

from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.weather.capabilities import (
    weather as weather_mod,
)
from plugins.bot_unified_runtime.domains.weather.capabilities.weather import (
    _nmc_query_with_retry,
    build_weather_capability,
)

_ALARM_FIXTURE: dict[str, Any] = {
    "data": {
        "page": {
            "list": [
                {
                    "alertid": "a1",
                    "issuetime": "2026/09/12 03:05",
                    "title": "黑龙江省大兴安岭地区呼玛县气象台发布大雾黄色预警信号",
                    "url": "/publish/alarm/a1.html",
                    "pic": "https://image.nmc.cn/assets/img/alarm/p0005003.png",
                }
            ]
        }
    }
}


# 桩形参显式具名 `timeout=None`（S-FIX-WX-T6 的 `timeout=` 下传腿）：这里不用
# `**kwargs` 兜底——生产再加一条下传腿时必须继续炸在测试里，而不是被兜底吞成
# 一次静默降级（与 test_wx_t6_timeout_plumbing.py 同口径）。
def _no_backoff(monkeypatch) -> None:
    monkeypatch.setattr(
        weather_mod, "_NMC_RETRY_BACKOFF_SECONDS", 0
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


def test_retry_succeeds_on_second_attempt(monkeypatch) -> None:
    """码表命中 + 首次瞬时失败 → 第二次成功，共外呼 2 次。"""
    _no_backoff(monkeypatch)
    calls: list[tuple[str, str]] = []

    def _flaky(query: str, proxy: str = "", timeout: float | None = None) -> str | None:
        calls.append((query, proxy))
        if len(calls) == 1:
            return None  # 模拟瞬时超时/空 data（fetch 层吞错后返回 None）
        return "【北京市北京天气】晴 25℃"

    monkeypatch.setattr(weather_mod, "nmc_weather_query", _flaky)
    report = _nmc_query_with_retry("北京", proxy="")
    assert report == "【北京市北京天气】晴 25℃"
    assert len(calls) == 2
    assert calls[0] == calls[1] == ("北京", "")


def test_unknown_city_skips_retry_and_network(monkeypatch) -> None:
    """码表未命中（海外/乡镇）→ 不重试不外呼，立即 None 走全球兜底。"""
    _no_backoff(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        weather_mod,
        "nmc_weather_query",
        lambda q, proxy="", timeout=None: calls.append(q),
    )
    assert _nmc_query_with_retry("Tokyo", proxy="") is None
    assert calls == []


def test_retry_exhausted_returns_none(monkeypatch) -> None:
    """重试耗尽仍失败 → 返回 None（上层照旧降级，不抛出）。"""
    _no_backoff(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        weather_mod,
        "nmc_weather_query",
        lambda q, proxy="", timeout=None: calls.append(q) or None,
    )
    assert _nmc_query_with_retry("黑龙江-呼玛", proxy="") is None
    assert len(calls) == 2  # 默认 _NMC_RETRY_ATTEMPTS = 2


def test_proxy_forwarded_on_every_attempt(monkeypatch) -> None:
    """proxy 参数逐次透传给底层查询。"""
    _no_backoff(monkeypatch)
    seen: list[str] = []
    monkeypatch.setattr(
        weather_mod,
        "nmc_weather_query",
        lambda q, proxy="", timeout=None: seen.append(proxy) or None,
    )
    _nmc_query_with_retry("北京", proxy="http://127.0.0.1:7890")
    assert seen == ["http://127.0.0.1:7890", "http://127.0.0.1:7890"]


def test_capability_recovers_nmc_and_alerts_after_transient_failure(
    monkeypatch,
) -> None:
    """capability 级：主通道重试恢复后，NMC 预警支路随之恢复。"""
    _no_backoff(monkeypatch)
    attempts: list[str] = []

    def _flaky(query: str, proxy: str = "", timeout: float | None = None) -> str | None:
        attempts.append(query)
        if len(attempts) == 1:
            return None  # 首次瞬时失败
        return "【黑龙江省大兴安岭地区呼玛县天气】雾 12℃"

    monkeypatch.setattr(weather_mod, "nmc_weather_query", _flaky)
    monkeypatch.setattr(
        weather_mod, "http_get_json", lambda *a, **k: _ALARM_FIXTURE
    )
    capability = build_weather_capability(config=None, render_backend=None)
    result = capability(_private_message("天气 黑龙江-呼玛"), None)
    assert len(attempts) == 2
    assert "呼玛县天气" in result.body
    assert "气象预警" in result.body
    assert "weather_source:nmc" in result.audit_tags
    assert "weather_alerts:1" in result.audit_tags


def test_capability_unknown_city_falls_back_without_nmc_calls(monkeypatch) -> None:
    """capability 级：海外城市不触发 NMC 外呼，直接 Open-Meteo 兜底。"""
    _no_backoff(monkeypatch)
    nmc_calls: list[str] = []
    monkeypatch.setattr(
        weather_mod,
        "nmc_weather_query",
        lambda q, proxy="", timeout=None: nmc_calls.append(q),
    )
    monkeypatch.setattr(
        weather_mod,
        "open_meteo_query",
        lambda query, proxy="", timeout=None: {"latitude": 35.7, "current": {}},
    )
    monkeypatch.setattr(
        weather_mod, "format_open_meteo", lambda payload: "【海外】Sunny"
    )
    capability = build_weather_capability(config=None, render_backend=None)
    result = capability(_private_message("天气 Tokyo"), None)
    assert nmc_calls == []
    assert "【海外】Sunny" in result.body
    assert "weather_source:open-meteo" in result.audit_tags
    assert not any(tag.startswith("weather_alerts") for tag in result.audit_tags)
