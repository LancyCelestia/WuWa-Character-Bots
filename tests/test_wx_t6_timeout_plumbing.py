"""S-FIX-WX-T6 · 命令路径超时真身＝`bot_weather_timeout_seconds` 实传（全离线）。

背景（假账根修）：键在 config.py:486 声明（缺省 8.0），但此前命令链路
builder→`_nmc_query_with_retry`→`nmc_weather_query`→`fetch_nmc_weather` 三腿
全部吃硬编码缺省（NMC/Open-Meteo 腿 10.0、预警腿 8.0），配置在册不算数；
registry 旧注释「NMC 主通道 2 次重试（`bot_weather_timeout_seconds`=8s）…
最坏约 24s」是账面假账。本件三层判据：

1. 行为锁——假网络（各模块命名空间叶子 `http_get_json` 记录 kwargs）证明
   配置值经装配链逐腿抵达每条外呼腿；`config=None`/缺键走声明缺省 8.0；
   不传 timeout 的直调＝旧缺省逐字节不变（NMC 腿 10.0、预警腿 8.0）；
2. AST 锁——对盘上源文本断言调用点实传的是配置变量（Name 节点）而非
   字面量/漏传，重试环与 nmc_weather_query 确有 timeout 形参与下传腿；
3. 注释诚实锁——registry 假账句式绝迹、根修指认在场。

注毒自证（谓词对变异源必 False、%TEMP 私拷行为锁必红、cmp 还原）见
SEAT-FIX-WX-T6.md 复跑证据段；谓词以模块函数暴露，供脚本 import 复用。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.weather.capabilities import (
    weather as weather_mod,
)
from plugins.bot_unified_runtime.domains.weather.capabilities.weather import (
    _nmc_query_with_retry,
    build_weather_capability,
    fetch_city_alerts,
)
from plugins.bot_unified_runtime.domains.weather.data import (
    nmc_weather as nmc_weather_mod,
)
from plugins.bot_unified_runtime.domains.weather.data import (
    open_meteo as open_meteo_mod,
)
from plugins.bot_unified_runtime.domains.weather.data.nmc_weather import (
    nmc_weather_query,
)
from plugins.bot_unified_runtime.domains.weather.data.open_meteo import (
    open_meteo_query,
)

# ------------------------------------------------------------------ fixture 报文
# fetch_nmc_weather 正向形态（T1 守卫全过）：与
# tests/test_weather_nmc_malformed_json_degrade.py 正向锁同款。
VALID_NMC_PAYLOAD: dict[str, Any] = {
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
}
EMPTY_ALARM_PAGE: dict[str, Any] = {"data": {"page": {"list": []}}}
GEOCODE_HIT: dict[str, Any] = {
    "results": [
        {
            "name": "Tokyo",
            "admin1": "東京",
            "country": "日本",
            "latitude": 35.68,
            "longitude": 139.69,
            "population": 37000000,
        }
    ]
}
FORECAST_HIT: dict[str, Any] = {
    "current": {
        "temperature_2m": 20.5,
        "weather_code": 0,
        "wind_speed_10m": 4.0,
        "relative_humidity_2m": 50.0,
    },
    "daily": {
        "temperature_2m_max": [22.0, 23.0],
        "temperature_2m_min": [15.0, 16.0],
        "weather_code": [0, 1],
    },
}


class LeafRecorder:
    """假网络叶子：记录 (url, kwargs)，按 url 分派固定报文。"""

    def __init__(self, responder: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._responder = responder

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append((str(url), kwargs))
        if callable(self._responder) and not isinstance(self._responder, dict):
            return self._responder(url)
        return self._responder

    @property
    def timeouts(self) -> list[Any]:
        return [kwargs.get("timeout") for _, kwargs in self.calls]


def _private_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _fake_config(**extra: Any) -> SimpleNamespace:
    return SimpleNamespace(bot_download_proxy="", **extra)


# --------------------------------------------------------------------- AST 谓词
def _func(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def predicate_builder_plumbs_config_key(weather_src: str) -> bool:
    """builder 内有 `float(getattr(config, "bot_weather_timeout_seconds", …))`
    赋值，且三腿调用点 `timeout=` 实传的是该变量 Name（非字面量、非漏传）。"""
    tree = ast.parse(weather_src)
    builder = _func(tree, "build_weather_capability")
    if builder is None:
        return False
    timeout_var: str | None = None
    for node in ast.walk(builder):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "float"
            and len(node.value.args) == 1
            and isinstance(node.value.args[0], ast.Call)
            and isinstance(node.value.args[0].func, ast.Name)
            and node.value.args[0].func.id == "getattr"
            and len(node.value.args[0].args) >= 2
            and isinstance(node.value.args[0].args[0], ast.Name)
            and node.value.args[0].args[0].id == "config"
            and isinstance(node.value.args[0].args[1], ast.Constant)
            and node.value.args[0].args[1].value == "bot_weather_timeout_seconds"
        ):
            timeout_var = node.targets[0].id
    if timeout_var is None:
        return False
    wanted = {"_nmc_query_with_retry", "open_meteo_query", "fetch_city_alerts"}
    hit: set[str] = set()
    for node in ast.walk(builder):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id not in wanted:
            continue
        for kw in node.keywords:
            if (
                kw.arg == "timeout"
                and isinstance(kw.value, ast.Name)
                and kw.value.id == timeout_var
            ):
                hit.add(node.func.id)
    return hit == wanted


def predicate_retry_forwards_timeout(weather_src: str) -> bool:
    """`_nmc_query_with_retry` 有 timeout 形参（缺省 None 哨兵）且把
    `timeout=timeout` 下传给 `nmc_weather_query`。"""
    tree = ast.parse(weather_src)
    fn = _func(tree, "_nmc_query_with_retry")
    if fn is None:
        return False
    params = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    if "timeout" not in params:
        return False
    sentinels = [d for d in (*fn.args.defaults, *fn.args.kw_defaults) if d is not None]
    if not any(isinstance(d, ast.Constant) and d.value is None for d in sentinels):
        return False
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "nmc_weather_query"
            and any(
                kw.arg == "timeout" and isinstance(kw.value, ast.Name)
                and kw.value.id == "timeout"
                for kw in node.keywords
            )
        ):
            return True
    return False


def predicate_nmc_query_forwards_timeout(nmc_src: str) -> bool:
    """`nmc_weather_query` 有 timeout 形参（None 哨兵）；存在
    `fetch_nmc_weather(..., timeout=timeout)` 下传腿 **且** 存在不带 timeout
    关键字的旧缺省腿（不传＝旧行为逐字节不变的结构性前提）。"""
    tree = ast.parse(nmc_src)
    fn = _func(tree, "nmc_weather_query")
    if fn is None:
        return False
    params = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    if "timeout" not in params:
        return False
    sentinels = [d for d in (*fn.args.defaults, *fn.args.kw_defaults) if d is not None]
    if not any(isinstance(d, ast.Constant) and d.value is None for d in sentinels):
        return False
    forwarding = False
    legacy_leg = False
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "fetch_nmc_weather"
        ):
            has_timeout_kw = any(
                kw.arg == "timeout" and isinstance(kw.value, ast.Name)
                and kw.value.id == "timeout"
                for kw in node.keywords
            )
            forwarding = forwarding or has_timeout_kw
            legacy_leg = legacy_leg or not has_timeout_kw
    return forwarding and legacy_leg


def predicate_registry_honesty(registry_src: str) -> bool:
    """registry weather 申报面：假账句式绝迹 + 根修指认在场 + 键申报不变。"""
    if "`bot_weather_timeout_seconds`=8s" in registry_src:
        return False
    if "最坏约 24s" in registry_src:
        return False
    if "S-FIX-WX-T6" not in registry_src:
        return False
    config_keys_line = (
        'config_keys=("bot_weather_enabled", "bot_weather_cache_seconds", '
        '"bot_weather_timeout_seconds")'
    )
    return config_keys_line in registry_src


# ------------------------------------------------------------------ 行为锁（装配链）
def test_nmc_and_alert_legs_receive_config_timeout(monkeypatch) -> None:
    """NMC 命中：主腿与预警腿的叶子 timeout 都＝配置值（此前是硬编码缺省）。"""
    nmc_leaf = LeafRecorder(VALID_NMC_PAYLOAD)
    alarm_leaf = LeafRecorder(EMPTY_ALARM_PAGE)
    monkeypatch.setattr(nmc_weather_mod, "http_get_json", nmc_leaf)
    monkeypatch.setattr(weather_mod, "http_get_json", alarm_leaf)
    capability = build_weather_capability(
        _fake_config(bot_weather_timeout_seconds=3.25), render_backend=None
    )
    result = capability(_private_message("天气 北京"), None)
    assert "weather_source:nmc" in result.audit_tags
    assert nmc_leaf.calls and alarm_leaf.calls
    assert nmc_leaf.timeouts == [3.25], nmc_leaf.calls
    assert alarm_leaf.timeouts == [3.25], alarm_leaf.calls


def test_retry_legs_all_use_config_timeout(monkeypatch) -> None:
    """重试两试都实传：每次外呼叶子收到的 timeout 恒等于配置值。"""
    monkeypatch.setattr(weather_mod, "_NMC_RETRY_BACKOFF_SECONDS", 0)
    seen: list[dict[str, Any]] = []

    def _first_fail(url: str, **kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return {} if len(seen) == 1 else VALID_NMC_PAYLOAD

    nmc_leaf = LeafRecorder(_first_fail)
    monkeypatch.setattr(nmc_weather_mod, "http_get_json", nmc_leaf)
    monkeypatch.setattr(weather_mod, "http_get_json", LeafRecorder(EMPTY_ALARM_PAGE))
    capability = build_weather_capability(
        _fake_config(bot_weather_timeout_seconds=4.5), render_backend=None
    )
    result = capability(_private_message("天气 北京"), None)
    assert "weather_source:nmc" in result.audit_tags
    assert len(nmc_leaf.calls) == 2
    assert nmc_leaf.timeouts == [4.5, 4.5], nmc_leaf.calls


def test_openmeteo_fallback_legs_receive_config_timeout(monkeypatch) -> None:
    """海外兜底：geocode 与 forecast 两腿都吃配置值；NMC 腿零外呼照旧。"""
    om_leaf = LeafRecorder(
        lambda url: GEOCODE_HIT if "geocoding" in url else FORECAST_HIT
    )
    nmc_leaf = LeafRecorder(None)
    monkeypatch.setattr(open_meteo_mod, "http_get_json", om_leaf)
    monkeypatch.setattr(nmc_weather_mod, "http_get_json", nmc_leaf)
    capability = build_weather_capability(
        _fake_config(bot_weather_timeout_seconds=2.75), render_backend=None
    )
    result = capability(_private_message("天气 Tokyo"), None)
    assert "weather_source:open-meteo" in result.audit_tags
    assert len(om_leaf.calls) >= 2
    assert set(om_leaf.timeouts) == {2.75}, om_leaf.calls
    assert nmc_leaf.calls == []


def test_config_none_builds_with_declared_default(monkeypatch) -> None:
    """config=None：装配处 getattr 缺省腿走声明值 8.0，命令链路仍被实传。"""
    nmc_leaf = LeafRecorder(VALID_NMC_PAYLOAD)
    alarm_leaf = LeafRecorder(EMPTY_ALARM_PAGE)
    monkeypatch.setattr(nmc_weather_mod, "http_get_json", nmc_leaf)
    monkeypatch.setattr(weather_mod, "http_get_json", alarm_leaf)
    capability = build_weather_capability(config=None, render_backend=None)
    result = capability(_private_message("天气 北京"), None)
    assert "weather_source:nmc" in result.audit_tags
    assert set(nmc_leaf.timeouts) == {8.0}, nmc_leaf.calls
    assert set(alarm_leaf.timeouts) == {8.0}, alarm_leaf.calls


def test_key_absent_config_falls_back_to_eight(monkeypatch) -> None:
    """假 config 缺键：读取口带缺省（8.0），不因缺键裸奔回硬编码旧值。"""
    nmc_leaf = LeafRecorder(VALID_NMC_PAYLOAD)
    monkeypatch.setattr(nmc_weather_mod, "http_get_json", nmc_leaf)
    monkeypatch.setattr(
        weather_mod, "http_get_json", LeafRecorder(EMPTY_ALARM_PAGE)
    )
    capability = build_weather_capability(
        SimpleNamespace(bot_download_proxy=""), render_backend=None
    )
    capability(_private_message("天气 北京"), None)
    assert set(nmc_leaf.timeouts) == {8.0}, nmc_leaf.calls


# ------------------------------------------------------- 行为锁（不传＝旧行为）
def test_direct_calls_without_timeout_keep_legacy_defaults(monkeypatch) -> None:
    """绕开装配处的直调（旧调用方/测试缝）逐字节旧行为：
    `_nmc_query_with_retry`/`nmc_weather_query` 不传 → NMC 叶子吃 10.0；
    `fetch_city_alerts` 不传 → 吃自身缺省 8.0；
    `open_meteo_query` 不传 → 吃自身缺省 10.0。"""
    nmc_leaf = LeafRecorder(VALID_NMC_PAYLOAD)
    monkeypatch.setattr(nmc_weather_mod, "http_get_json", nmc_leaf)
    assert _nmc_query_with_retry("北京", proxy="")
    assert nmc_leaf.timeouts == [10.0], nmc_leaf.calls
    nmc_leaf.calls.clear()
    assert nmc_weather_query("北京", proxy="")
    assert nmc_leaf.timeouts == [10.0], nmc_leaf.calls

    alarm_leaf = LeafRecorder(EMPTY_ALARM_PAGE)
    monkeypatch.setattr(weather_mod, "http_get_json", alarm_leaf)
    assert fetch_city_alerts("北京", proxy="") == []
    assert alarm_leaf.timeouts == [8.0], alarm_leaf.calls

    om_leaf = LeafRecorder(
        lambda url: GEOCODE_HIT if "geocoding" in url else FORECAST_HIT
    )
    monkeypatch.setattr(open_meteo_mod, "http_get_json", om_leaf)
    assert open_meteo_query("Tokyo", proxy="") is not None
    assert set(om_leaf.timeouts) == {10.0}, om_leaf.calls


# ------------------------------------------------------------------- AST 结构锁
def test_ast_lock_builder_actually_plumbs_config_variable() -> None:
    src = Path(weather_mod.__file__).read_text(encoding="utf-8")
    assert predicate_builder_plumbs_config_key(src)


def test_ast_lock_retry_forward() -> None:
    src = Path(weather_mod.__file__).read_text(encoding="utf-8")
    assert predicate_retry_forwards_timeout(src)


def test_ast_lock_nmc_query_forward_with_legacy_leg() -> None:
    src = Path(nmc_weather_mod.__file__).read_text(encoding="utf-8")
    assert predicate_nmc_query_forwards_timeout(src)


# ------------------------------------------------------------------- 注释诚实锁
def test_registry_weather_comment_no_longer_falsely_accounted() -> None:
    registry_src = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/domains/chat_reply/runtime"
        / "capability_registry.py"
    ).read_text(encoding="utf-8")
    # 旧假账句式绝迹：宣称键值就是 NMC 重试超时、并钉死「最坏约 24s」；
    # 根修指认在场；键申报面不变。判据集中于 predicate_registry_honesty。
    assert predicate_registry_honesty(registry_src)
