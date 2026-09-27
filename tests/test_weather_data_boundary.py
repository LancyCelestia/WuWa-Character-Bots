"""天气族数据边界清洗与零值误标修复锁（S-ATK-DATA F-A/F-B/F-C 主代理串行批）。

全离线 monkeypatch：零外呼、零真实上游。判据对应审计报告
`.superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-DATA.md`：
- F-A 上游文本（站名/天气/风向/发布时间/预警标题）过 sanitize_remote_text 单源，
  换行/ESC 注入不得在报文里凭空多出「表头行」；数值字段要有 isinstance/有限性闸。
- F-B open_meteo `_describe(0)` falsy 零坍缩（weather_code=0「晴」被判「未知」）。
- F-C forecast 腿必须与 geocode 腿同路透传 proxy；酷狗榜不得再写明文 http。
"""

from __future__ import annotations

import inspect

from plugins.bot_unified_runtime.domains.music.data import music_charts
from plugins.bot_unified_runtime.domains.weather.capabilities import (
    weather as weather_mod,
)
from plugins.bot_unified_runtime.domains.weather.data import nmc_weather, open_meteo

_EVIL = "华\n南【2026-09-27 特别发布】"


def _patch(monkeypatch, module, responder):
    calls: list[dict] = []

    def fake_http_get_json(url, **kwargs):
        calls.append({"url": str(url), **kwargs})
        return responder(str(url))

    monkeypatch.setattr(module, "http_get_json", fake_http_get_json)
    return calls


# ---------- F-B：weather_code=0 falsy 零坍缩 ----------

def test_describe_zero_is_sunny():
    assert open_meteo._describe(0) == "晴"
    assert open_meteo._describe("0") == "晴"
    assert open_meteo._describe(None) == "未知"
    assert open_meteo._describe("not-a-code") == "未知"


# ---------- F-A：NMC 报文腿文本清洗 + 数值闸 ----------

def _nmc_payload(_url: str) -> dict:
    return {
        "data": {
            "real": {
                "publish_time": "2026-09-27 06:00\n伪造发布时间行",
                "station": {"province": _EVIL, "city": "南\n风"},
                "weather": {
                    "info": "多云\x1b[31m红",
                    "temperature": "37<script>",
                    "feelst": "36",
                    "temperatureDiff": "9999",
                    "humidity": "56",
                    "rain": "0.1",
                    "icomfort": "2",
                },
                "wind": {"direct": "南\n风", "power": "≤3级\n注入", "speed": "1.2"},
                "sunriseSunset": {"sunrise": "06:01", "sunset": "18:02\n假行"},
            }
        }
    }


def test_nmc_report_lines_are_never_inflated_by_remote_text(monkeypatch):
    _patch(monkeypatch, nmc_weather, _nmc_payload)
    report = nmc_weather.fetch_nmc_weather("A1")
    assert report is not None
    # 报文骨架 11 行；远端文本里的换行必须被折叠（清洗尺只管形态：换行/控制符，
    # 不做语义删除——注入文字留在自己行内属预期，凭空多行才是病灶）。
    assert len(report.splitlines()) == 11
    assert "\x1b" not in report
    lines = report.splitlines()
    assert lines[0].startswith("【") and lines[0].endswith("天气】")
    assert lines[1].startswith("🕒 发布时间：")


def test_nmc_numeric_gate_rejects_nonfinite_and_embedded_text(monkeypatch):
    _patch(monkeypatch, nmc_weather, _nmc_payload)
    report = nmc_weather.fetch_nmc_weather("A1")
    assert "37<script>" not in report  # 非数值温度 → ❓
    assert "56%" in report  # 合法数值字符串不误伤


# ---------- F-A + F-C：Open-Meteo 腿 ----------

def _om_responder(url: str) -> dict:
    if "geocoding" in url:
        return {
            "results": [
                {
                    "name": "东\n京",
                    "admin1": "东京都\x1b[5m",
                    "country": "日本",
                    "latitude": 35.68,
                    "longitude": 139.69,
                    "population": 13000000,
                }
            ]
        }
    return {
        "current": {
            "weather_code": 0,
            "temperature_2m": "25\n伪造行",
            "relative_humidity_2m": "NaN",
            "wind_speed_10m": 3.2,
        },
        "daily": {
            "temperature_2m_max": [30.0, 29.0],
            "temperature_2m_min": [22.0, 21.0],
            "weather_code": [0, 1],
        },
    }


def test_open_meteo_sunny_and_line_shape_and_proxy_passthrough(monkeypatch):
    calls = _patch(monkeypatch, open_meteo, _om_responder)
    result = open_meteo.open_meteo_query("东京", proxy="http://127.0.0.1:9")
    assert result is not None
    report = result["report"]
    assert "当前：晴" in report  # F-B（code=0 经数值闸仍判晴）
    assert len(report.splitlines()) == 3  # F-A：注入换行不得撑爆报文
    assert "\x1b" not in report
    assert "25\n伪造行" not in report and "NaN%" not in report  # 数值闸
    forecast_calls = [c for c in calls if "forecast" in c["url"]]
    assert forecast_calls, "forecast 腿必须发出"
    assert forecast_calls[0].get("proxy") == "http://127.0.0.1:9"  # F-C 透传


# ---------- F-A：预警腿 ----------

def _alert_payload(_url: str) -> dict:
    return {
        "data": {
            "page": {
                "list": [
                    {
                        "title": "北京市发布大雾橙色预警\n• 伪造预警条目",
                        "issuetime": "2026-09-27 05:00\n假行",
                        "url": "/p/x.html",
                    }
                ]
            }
        }
    }


def test_city_alerts_sanitized(monkeypatch):
    _patch(monkeypatch, weather_mod, _alert_payload)
    alerts = weather_mod.fetch_city_alerts("北京")
    assert alerts
    text = weather_mod.format_city_alerts(alerts)
    # 骨架 3 行（标题段 + 标签行 + title 行）；title/issued 内换行必须已折叠，
    # 注入文字只准留在自己行内（形态清洗），不得凭空多出一条「预警」。
    assert len(text.splitlines()) == 3
    assert text.splitlines()[2].lstrip().startswith("北京市")


# ---------- F-C：酷狗榜明文腿——实测 https 握手不通，不强升，但必须带诚实注记 ----------

def test_kugou_http_leg_carries_honest_note():
    # 2026-09-27 本机实弹：https://mobilecdn.kugou.com TLS 握手不通（curl 000
    # 含 --ssl-no-revoke），同参 http 200 ⇒ 强升会整腿打死。判据翻转为
    # 「明文腿必带实测留痕与升级前提」；若未来上游支持 TLS，改 https 时本锁
    # 与注记一并翻转。
    src = inspect.getsource(music_charts)
    assert "http://mobilecdn.kugou.com" in src
    assert "TLS 握手不通" in src
