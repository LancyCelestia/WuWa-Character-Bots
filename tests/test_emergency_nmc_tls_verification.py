"""S-FIX-EMG-TLS 回归锁：紧急信息域 NMC 通道 TLS 证书验证在场（离线，不外呼）。

背景（S-FIX-WXSSL 天气席同型缺陷移交）：`nmc_alarm.py` 的两条 NMC 通道
（rest/findAlarm 全国在报清单、rest/weather 站点当前预警）曾无条件传
`verify_ssl=False`，等于裸 TLS：MITM 可伪造预警正文原样进群聊与推送链。
天气席已在 runtime venv 实测证伪「nmc.cn 证书链不完整」历史注释
（默认上下文 TLSv1.3 握手通过 + JSON 拉取 200），本席同口径：
缺省路径一律走证书验证，**不设降级重试腿**，握手失败按既有异常面
（`resolve_document` → `RawDoc.failure` → `FetchState.FAILED`）诚实出留痕。

本文件锁定三件事：

1. AST 锁：`nmc_alarm.py` 生产源码不得出现任何 `verify_ssl=False`
   字面量传参（无条件关校验的回潮即红）。
2. 行为锁：两条通道对公共口 `http_get_json` 的每一次真实缺省链路调用
   都不得带 `verify_ssl=False`——「验证在场」是运行时事实，不止文本形态。
3. 反降级锁：全部尝试失败时，每一次重试也必须在场验证；失败绝不换来
   一条「关校验再试一次」的降级腿。

全测试离线：`http_get_json` 与 SSRF 护栏均为替身，零出网。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.emergency_info.sources import http_get
from plugins.bot_unified_runtime.domains.emergency_info.sources import (
    nmc_alarm as nmc_module,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.nmc_alarm import (
    FetchState,
    fetch_nmc_alarms,
    fetch_nmc_station_alarm,
)

# nmc_alarm 真身源码路径（由已导入模块的 __file__ 反推，不依赖 cwd）。
_NMC_ALARM_SOURCE = Path(nmc_module.__file__).resolve()

_ALARM_PAGE_FIXTURE: dict[str, Any] = {
    "msg": "success",
    "code": 0,
    "data": {
        "page": {
            "count": 1,
            "list": [
                {
                    "alertid": "51178141600000_20260927000000",
                    "issuetime": "2026/09/27 08:00",
                    "title": "北京市气象台发布大风蓝色预警信号",
                    "url": "/publish/alarm/51178141600000_20260927000000.html",
                }
            ],
        },
        "provinceAlarms": [],
    },
}

_STATION_WARN_FIXTURE: dict[str, Any] = {
    "code": 0,
    "data": {
        "real": {
            "station": {"province": "北京市", "city": "北京", "code": "Wqsps"},
            "warn": {
                "alert": "北京市气象台发布大风蓝色预警信号",
                "issuetime": "2026-09-27 08:00",
                "signaltype": "大风",
                "signallevel": "蓝色",
                "url": "/publish/alarm/x.html",
                "pic": "",
                "issuecontent": "测试正文",
            },
        }
    },
}


class _PassGuard:
    """SSRF 护栏替身：一律放行（返回 None），同时留呼痕（测试不出网）。"""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> str | None:
        self.urls.append(url)
        return None


def _verify_ssl_false_sites(path: Path) -> list[int]:
    """收集该源码文件里 `...(..., verify_ssl=False, ...)` 字面量传参行号。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "verify_ssl":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and value.value is False:
                lines.append(node.lineno)
    return lines


def test_nmc_alarm_source_has_no_verify_ssl_false() -> None:
    """AST 锁：nmc_alarm.py 生产路径不得无条件传 verify_ssl=False。"""
    sites = _verify_ssl_false_sites(_NMC_ALARM_SOURCE)
    assert sites == [], (
        f"{_NMC_ALARM_SOURCE.name} 出现关闭证书校验的调用（行 {sites}）"
    )


def _assert_verified(kwargs: dict[str, Any], where: str) -> None:
    """每次外呼都必须落在「缺省验证」上：不带 verify_ssl 键，或显式为 True。"""
    assert kwargs.get("verify_ssl", True) is True, f"{where} 调用未走证书验证：{kwargs!r}"


def test_fetch_nmc_alarms_default_transport_is_verified(
    monkeypatch,
) -> None:
    """行为锁：全国清单通道缺省链路（fetch=None）的每次外呼都在场验证。"""
    calls: list[dict[str, Any]] = []

    def capture(url: str, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return _ALARM_PAGE_FIXTURE

    guard = _PassGuard()
    monkeypatch.setattr(http_get, "guard_user_url", guard)
    monkeypatch.setattr(http_get, "http_get_json", capture)

    outcome = fetch_nmc_alarms()
    assert outcome.state is FetchState.OK and outcome.items
    assert len(calls) == 1
    for index, kwargs in enumerate(calls):
        _assert_verified(kwargs, f"fetch_nmc_alarms 第 {index + 1} 次调用")


def test_fetch_nmc_station_alarm_default_transport_is_verified(
    monkeypatch,
) -> None:
    """行为锁：站点预警通道缺省链路的每次外呼都在场验证。"""
    calls: list[dict[str, Any]] = []

    def capture(url: str, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return _STATION_WARN_FIXTURE

    guard = _PassGuard()
    monkeypatch.setattr(http_get, "guard_user_url", guard)
    monkeypatch.setattr(http_get, "http_get_json", capture)

    outcome = fetch_nmc_station_alarm("Wqsps")
    assert outcome.state is FetchState.OK and outcome.items
    assert len(calls) == 1
    for index, kwargs in enumerate(calls):
        _assert_verified(kwargs, f"fetch_nmc_station_alarm 第 {index + 1} 次调用")


def test_failure_path_never_degrades_to_unverified(
    monkeypatch,
) -> None:
    """反降级锁：整条重试链全部失败时，每一次尝试也必须在场验证。

    天气席先例：握手/传输失败按既有异常面收敛成 FAILED 留痕，
    绝不追加一条「关校验再试」的降级腿。
    """
    calls: list[dict[str, Any]] = []

    def boom(url: str, **kwargs: Any) -> Any:
        calls.append(kwargs)
        raise http_get.ParseHttpError("simulated TLS handshake failure")

    guard = _PassGuard()
    monkeypatch.setattr(http_get, "guard_user_url", guard)
    monkeypatch.setattr(http_get, "http_get_json", boom)
    monkeypatch.setattr(http_get, "_backoff_sleep", lambda attempt: None)

    outcome = fetch_nmc_alarms(retry=3)
    assert outcome.state is FetchState.FAILED
    assert outcome.reason == "http_error:ParseHttpError"
    assert len(calls) == 3  # 首试 + 2 次重试，一次都不能关校验
    for index, kwargs in enumerate(calls):
        _assert_verified(kwargs, f"失败态第 {index + 1} 次调用")
