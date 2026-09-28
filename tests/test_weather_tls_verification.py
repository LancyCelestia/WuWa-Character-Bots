"""S-FIX-WXSSL M1 回归锁：NMC 双通道 TLS 证书验证在场（离线，不外呼）。

背景（终局攻击者复查波 S-ATK-WXFIN M-1）：weather 域两条 NMC 通道
（rest/weather 主接口、rest/findAlarm 预警接口）曾无条件传
`verify_ssl=False`，等于裸 TLS：MITM 可伪造天气/预警文本进群聊并回灌
提示词。历史注释「nmc.cn 证书链不完整」经 2026-09-27 runtime venv 实测
证伪（默认上下文 TLS 握手 TLSv1.3 通过 + JSON 拉取 200），故缺省路径
一律走证书验证，不设降级重试腿。

本文件锁定两件事：

1. AST 锁：domains/weather 生产源码不得出现任何 `verify_ssl=False`
   字面量传参（无条件关校验的回潮即红）。
2. 行为锁：两条通道正常态与失败态对 http_get_json 的每一次调用都不得
   带 verify_ssl=False —— 「验证在场」是运行时事实，不止是文本形态。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
)
from plugins.bot_unified_runtime.domains.weather.capabilities import (
    weather as weather_mod,
)
from plugins.bot_unified_runtime.domains.weather.capabilities.weather import (
    fetch_city_alerts,
)
from plugins.bot_unified_runtime.domains.weather.data import nmc_weather as nmc_mod
from plugins.bot_unified_runtime.domains.weather.data.nmc_weather import (
    fetch_nmc_weather,
)

# domains/weather 包根（由已导入模块的 __file__ 反推，不依赖 cwd）。
_WEATHER_PKG_ROOT = Path(nmc_mod.__file__).resolve().parent.parent

_REAL_FIXTURE: dict[str, Any] = {
    "data": {"real": {"station": {"province": "北京市", "city": "北京"}}}
}
_ALARM_FIXTURE: dict[str, Any] = {
    "data": {
        "page": {
            "list": [
                {
                    "alertid": "a1",
                    "issuetime": "2026-09-27 08:00",
                    "title": "北京市气象台发布大风蓝色预警信号",
                    "url": "/publish/alarm/a1.html",
                }
            ]
        }
    }
}


def _iter_weather_source_files() -> list[Path]:
    files = sorted(_WEATHER_PKG_ROOT.rglob("*.py"))
    assert files, f"domains/weather 下未找到源码：{_WEATHER_PKG_ROOT}"
    return files


def _verify_ssl_false_sites(files: list[Path]) -> list[str]:
    """收集 `...(..., verify_ssl=False, ...)` 字面量传参坐标。"""
    sites: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "verify_ssl":
                    continue
                value = keyword.value
                if isinstance(value, ast.Constant) and value.value is False:
                    sites.append(f"{path.relative_to(_WEATHER_PKG_ROOT)}:{node.lineno}")
    return sites


def test_weather_domain_has_no_verify_ssl_false() -> None:
    """AST 锁：weather 域生产路径不得无条件传 verify_ssl=False。"""
    sites = _verify_ssl_false_sites(_iter_weather_source_files())
    assert sites == [], "weather 域出现关闭证书校验的调用：" + "、".join(sites)


def _assert_verified(kwargs: dict[str, Any], where: str) -> None:
    """每次外呼都必须落在「缺省验证」上：不带 verify_ssl 键，或显式为 True。"""
    assert kwargs.get("verify_ssl", True) is True, f"{where} 调用未走证书验证：{kwargs!r}"


def test_fetch_nmc_weather_calls_with_verification(monkeypatch) -> None:
    """行为锁：主通道对 http_get_json 的每次调用（含失败重试）都必须在场验证。"""
    calls: list[dict[str, Any]] = []

    def _capture(url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        if len(calls) == 1:
            raise ParseHttpError("simulated transient failure")  # 第二次才成功
        return _REAL_FIXTURE

    monkeypatch.setattr(nmc_mod, "http_get_json", _capture)
    assert fetch_nmc_weather("54511", proxy="") is None  # 吞错返回 None 语义不变
    report = fetch_nmc_weather("54511", proxy="")
    assert report is not None
    assert len(calls) == 2
    for index, kwargs in enumerate(calls):
        _assert_verified(kwargs, f"fetch_nmc_weather 第 {index + 1} 次调用")


def test_fetch_city_alerts_calls_with_verification(monkeypatch) -> None:
    """行为锁：预警通道同样缺省验证；异常回退路径也不得出现降级调用。"""
    calls: list[dict[str, Any]] = []

    def _capture(url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return _ALARM_FIXTURE

    monkeypatch.setattr(weather_mod, "http_get_json", _capture)
    hits = fetch_city_alerts("北京", proxy="")
    assert hits and "大风蓝色" in hits[0]["title"]
    assert len(calls) == 1
    for index, kwargs in enumerate(calls):
        _assert_verified(kwargs, f"fetch_city_alerts 第 {index + 1} 次调用")

    # 失败态：抛 ParseHttpError 时必须收敛为空，且不得追加一次「关校验重试」。
    def _boom(url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        raise ParseHttpError("simulated unreachable")

    monkeypatch.setattr(weather_mod, "http_get_json", _boom)
    assert fetch_city_alerts("北京", proxy="") == []
    assert len(calls) == 2
    _assert_verified(calls[1], "fetch_city_alerts 失败态调用")
