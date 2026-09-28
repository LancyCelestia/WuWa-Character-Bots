"""S-FIX-ATK-WXEMG T1锁 | NMC 主腿对非 dict JSON 响应必须走失败面降级。

对应审计票 SEAT-ATK-WEATHER T1（会错）：`http_get_json`（http_util.py:402）返回
**任意** JSON 类型——顶层数组 / 字符串 / 整数都出得来；旧写法
`((payload or {}).get("data") or {}).get("real")` 对非 dict 直接抛
AttributeError，冲出 capability() 到 pipeline 兜底 catch，把设计承诺的降级链
（NMC 失败 → Open-Meteo 全球兜底 → 诚实播报查不到）整条烧掉，还白烧 2 次重试。

修法落点：`domains/weather/data/nmc_weather.py:fetch_nmc_weather` 在建报文之前
逐层 isinstance 防护，畸形响应一律 `return None`（既有失败面）。

注毒自证（%TEMP% 副本，见 SEAT-FIX-ATK-WXEMG.md 复跑证据段）：把守卫撤掉
（还原旧写法）后本件对 list 载荷必红；守卫恢复即绿。
全部离线：零网络，http_get_json 一律 monkeypatch。
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.weather.data import nmc_weather
from plugins.bot_unified_runtime.domains.weather.data.nmc_weather import (
    fetch_nmc_weather,
    nmc_weather_query,
)

# 畸形顶层：非 dict 的一切 JSON 形态（审计复跑证据 #1 的 list 形态在首）。
MALFORMED_TOP_LEVEL: list[Any] = [
    ["x"],
    [],
    "not-a-dict",
    42,
    0,
    None,
    {},
    {"data": []},
    {"data": "x"},
    {"data": 42},
    {"data": None},
    {"data": {}},
    {"data": {"real": "x"}},
    {"data": {"real": []}},
    {"data": {"real": 7}},
    {"data": {"real": None}},
    {"data": {"real": {}}},
    {"message": "success"},
]


def _patch_payload(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    monkeypatch.setattr(
        nmc_weather, "http_get_json", lambda *args, **kwargs: payload
    )


@pytest.mark.parametrize("payload", MALFORMED_TOP_LEVEL)
def test_malformed_json_degrades_to_none(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    """畸形/改版响应一律 return None（失败面），绝不抛 AttributeError 冲出。"""
    _patch_payload(monkeypatch, payload)
    assert fetch_nmc_weather("54511", proxy="") is None


@pytest.mark.parametrize("payload", MALFORMED_TOP_LEVEL)
def test_query_seam_also_degrades(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    """nmc_weather_query 是 weather.py 重试环的打桩缝：同样必须 None 不炸。"""
    _patch_payload(monkeypatch, payload)
    assert nmc_weather_query("北京") is None


def test_non_dict_subfields_degrade_to_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """real 成立但子字段是脏标量时：出报告、脏字段按未知（❓）处理，不炸。"""
    _patch_payload(
        monkeypatch,
        {
            "data": {
                "real": {
                    "publish_time": "2026-09-27 12:00",
                    "station": "STRING-NOT-DICT",
                    "weather": 42,
                    "wind": ["a", "b"],
                    "sunriseSunset": True,
                }
            }
        },
    )
    report = fetch_nmc_weather("54511", proxy="")
    assert isinstance(report, str) and report
    # 脏子字段被洗成空 dict：报文照常成文，省市/数值段落空——绝不炸、也不误杀整报。
    assert report.startswith("【天气】")
    assert "舒适度：未知" in report


def test_wellformed_payload_report_shape_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正向锁：合法载荷的报告输出与修复前逐字节一致（防过度防护改坏现网形态）。"""
    _patch_payload(
        monkeypatch,
        {
            "data": {
                "real": {
                    "publish_time": "2026-09-27 12:00",
                    "station": {"province": "北京", "city": "北京"},
                    "weather": {
                        "temperature": "21.3",
                        "temperatureDiff": "6.1",
                        "humidity": "50",
                        "rain": "0",
                        "info": "晴",
                        "feelst": "20.9",
                        "icomfort": "0",
                    },
                    "wind": {"direct": "东北", "power": "≤3", "speed": "3.2"},
                    "sunriseSunset": {"sunrise": "06:08", "sunset": "18:00"},
                }
            }
        },
    )
    report = fetch_nmc_weather("54511", proxy="")
    assert isinstance(report, str)
    assert report.startswith("【北京北京天气】")
    for expected in ("🌡 温度：21.3℃", "💧 湿度：50%", "🌇 日落：18:00"):
        assert expected in report


def test_parse_http_error_leg_still_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """既有失败面（ParseHttpError 吞错返回 None）语义不变。"""

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise nmc_weather.ParseHttpError("boom")

    monkeypatch.setattr(nmc_weather, "http_get_json", _raise)
    assert fetch_nmc_weather("54511", proxy="") is None
