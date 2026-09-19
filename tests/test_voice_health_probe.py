"""语音引擎只读健康探针（bot.tts，U-17=C 案，Wave G T79）。

宪法边界（progress.md G2-R2 用户裁定 + T79 简报）：
- 引擎生命周期=人工脚本唯一入口，bot 侧**只读**探针：被调用才查（/bot status
  查询、退避窗进入两触发点），**零常驻线程、零后台轮询、绝不代启动引擎**；
- 不可达 → 构造 ``OperationalIssue(kind="tts_service_unreachable")``（复用既有
  kind），同一冷却窗（300s，对齐中央 ``AdminAlertSuppression`` 缺省窗）内
  **不重复构造**；可达且上次不可达=恢复态（状态行显示「已恢复」）；
- fail-open：探针自身任何异常不冒泡（debug 日志留痕），返回 unknown 态。

全离线零真实网络：TCP 连接一律桩掉（monkeypatch ``_tcp_connect``），
时钟经 ``_monotonic`` 注入。护栏与上游退避真闸（T57）同风格。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Self

import pytest

from plugins.bot_unified_runtime.domains.media import voice_health_probe as probe_mod
from plugins.bot_unified_runtime.domains.media.voice_health_probe import (
    VoiceEngineHealth,
    last_operational_issue,
    parse_engine_endpoint,
    probe_voice_engine,
    voice_status_line,
)

_URL = "http://127.0.0.1:9880"


@pytest.fixture(autouse=True)
def _isolate_probe_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """探针模块态逐例隔离（进程内全局，惯例同 test_tts_health_backoff）。"""
    probe_mod._reset_state()
    yield
    probe_mod._reset_state()


@pytest.fixture(autouse=True)
def _isolate_tts_backoff(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """上游 tts 退避态隔离（真实集成用例会写它，走完必须清零）。"""
    import plugins.bot_unified_runtime.domains.media.capabilities.tts as tts_mod

    monkeypatch.setattr(tts_mod, "_last_failure_at", 0.0)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "")
    yield


# ---------------------------------------------------------------------------
# 桩件
# ---------------------------------------------------------------------------


class _StubSocket:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _stub_connect_ok(host: str, port: int, timeout: float) -> _StubSocket:
    return _StubSocket()


def _patch_clock(monkeypatch: pytest.MonkeyPatch, *, start: float = 1000.0) -> list[float]:
    """可控单调钟：返回可推进的刻度列表（probe_mod._monotonic 替换点）。"""
    ticks = [start]

    def _fake_monotonic() -> float:
        return ticks[0]

    monkeypatch.setattr(probe_mod, "_monotonic", _fake_monotonic)
    return ticks


# ---------------------------------------------------------------------------
# 端点解析
# ---------------------------------------------------------------------------


def test_parse_engine_endpoint_variants() -> None:
    assert parse_engine_endpoint(_URL) == ("127.0.0.1", 9880)
    assert parse_engine_endpoint("http://127.0.0.1") == ("127.0.0.1", 80)
    assert parse_engine_endpoint("https://engine.example.com/tts") == (
        "engine.example.com",
        443,
    )
    assert parse_engine_endpoint("") is None
    assert parse_engine_endpoint("not a url") is None


def test_parse_engine_endpoint_invalid_port_is_none() -> None:
    assert parse_engine_endpoint("http://127.0.0.1:notaport/") is None


# ---------------------------------------------------------------------------
# 探针三态
# ---------------------------------------------------------------------------


def test_reachable_reports_structured_health(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_clock(monkeypatch)
    captured: dict[str, object] = {}

    def _connect(host: str, port: int, timeout: float) -> _StubSocket:
        captured["host"] = host
        captured["port"] = port
        captured["timeout"] = timeout
        return _StubSocket()

    monkeypatch.setattr(probe_mod, "_tcp_connect", _connect)
    health = probe_voice_engine(api_url=_URL)
    assert health.state == "reachable"
    assert health.reachable is True
    assert health.latency_ms is not None
    assert health.checked_at > 0
    assert health.endpoint == "127.0.0.1:9880"
    assert captured == {"host": "127.0.0.1", "port": 9880, "timeout": 2.0}


def test_connection_refused_maps_to_unreachable_and_builds_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_clock(monkeypatch)

    def _refuse(host: str, port: int, timeout: float) -> _StubSocket:
        raise ConnectionRefusedError("[WinError 10061]")

    monkeypatch.setattr(probe_mod, "_tcp_connect", _refuse)
    health = probe_voice_engine(api_url=_URL)
    assert health.state == "unreachable"
    assert health.reachable is False
    assert "连接被拒绝" in health.detail
    issue = last_operational_issue()
    assert issue is not None
    assert issue.kind == "tts_service_unreachable"
    assert issue.retryable is True
    assert issue.stage == "tts"
    assert issue.safe_summary  # 人话摘要非空（已过 redact）


def test_timeout_maps_to_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_clock(monkeypatch)

    def _hang(host: str, port: int, timeout: float) -> _StubSocket:
        raise TimeoutError("timed out")

    monkeypatch.setattr(probe_mod, "_tcp_connect", _hang)
    health = probe_voice_engine(api_url=_URL)
    assert health.state == "unreachable"
    assert "连接超时" in health.detail


def test_unreachable_other_os_error_reports_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_clock(monkeypatch)

    def _dns_fail(host: str, port: int, timeout: float) -> _StubSocket:
        raise OSError("getaddrinfo failed")

    monkeypatch.setattr(probe_mod, "_tcp_connect", _dns_fail)
    health = probe_voice_engine(api_url=_URL)
    assert health.state == "unreachable"
    assert "OSError" in health.detail


def test_unparseable_url_is_unknown_without_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_clock(monkeypatch)
    health = probe_voice_engine(api_url="")
    assert health.state == "unknown"
    assert health.reachable is None
    assert last_operational_issue() is None


def test_probe_internal_error_fails_open(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_clock(monkeypatch)

    def _explode(host: str, port: int, timeout: float) -> _StubSocket:
        raise RuntimeError("probe blew up")

    monkeypatch.setattr(probe_mod, "_tcp_connect", _explode)
    with caplog.at_level(logging.DEBUG):
        health = probe_voice_engine(api_url=_URL)  # 绝不冒泡
    assert health.state == "unknown"
    assert last_operational_issue() is None
    assert any("probe" in record.message.lower() for record in caplog.records)


def test_probe_timeout_is_clamped_to_two_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_clock(monkeypatch)
    seen: list[float] = []

    def _connect(host: str, port: int, timeout: float) -> _StubSocket:
        seen.append(timeout)
        return _StubSocket()

    monkeypatch.setattr(probe_mod, "_tcp_connect", _connect)
    probe_voice_engine(api_url=_URL, timeout_seconds=99.0)
    probe_voice_engine(api_url=_URL, timeout_seconds=0.0)
    assert seen[0] <= 2.0
    assert seen[1] >= 0.1


# ---------------------------------------------------------------------------
# 告警衔接：300s 冷却窗内不重复构造 + 恢复沿
# ---------------------------------------------------------------------------


def _stub_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(host: str, port: int, timeout: float) -> _StubSocket:
        raise ConnectionRefusedError("[WinError 10061]")

    monkeypatch.setattr(probe_mod, "_tcp_connect", _refuse)


def test_issue_not_reconstructed_within_cooldown_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = _patch_clock(monkeypatch)
    _stub_refused(monkeypatch)
    probe_voice_engine(api_url=_URL)
    first = last_operational_issue()
    probe_voice_engine(api_url=_URL)
    assert last_operational_issue() is first  # 同窗不重复构造（同一对象）
    ticks[0] += probe_mod._ISSUE_COOLDOWN_SECONDS + 1.0
    probe_voice_engine(api_url=_URL)
    second = last_operational_issue()
    if first is None or second is None:
        pytest.fail("不可达探测必须构造 issue")
    assert second is not first  # 窗满=新事件，新 issue
    assert second.debug_id != first.debug_id


def test_recovery_edge_sets_recovered_flag_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_clock(monkeypatch)
    _stub_refused(monkeypatch)
    down = probe_voice_engine(api_url=_URL)
    assert down.recovered is False

    monkeypatch.setattr(probe_mod, "_tcp_connect", _stub_connect_ok)
    up = probe_voice_engine(api_url=_URL)
    assert up.state == "reachable"
    assert up.recovered is True  # 上次不可达 → 本次恢复沿

    again = probe_voice_engine(api_url=_URL)
    assert again.recovered is False  # 恢复沿只报一次


def test_new_down_edge_after_recovery_builds_fresh_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = _patch_clock(monkeypatch)
    _stub_refused(monkeypatch)
    probe_voice_engine(api_url=_URL)
    first = last_operational_issue()
    monkeypatch.setattr(probe_mod, "_tcp_connect", _stub_connect_ok)
    probe_voice_engine(api_url=_URL)  # 恢复
    _stub_refused(monkeypatch)
    ticks[0] += 1.0
    probe_voice_engine(api_url=_URL)  # 再次不可达：新事件沿
    second = last_operational_issue()
    assert second is not None and first is not None
    assert second is not first


# ---------------------------------------------------------------------------
# /bot status 行数据接口
# ---------------------------------------------------------------------------


def _health(state: str, *, recovered: bool = False) -> VoiceEngineHealth:
    reachable = {"reachable": True, "unreachable": False, "unknown": None}[state]
    return VoiceEngineHealth(
        state=state,
        reachable=reachable,
        latency_ms=12.0 if state == "reachable" else None,
        checked_at=time.time(),
        endpoint="127.0.0.1:9880",
        detail="连接被拒绝" if state == "unreachable" else "",
        recovered=recovered,
    )


def test_status_line_disabled_skips_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    def _must_not_run(host: str, port: int, timeout: float) -> _StubSocket:
        raise AssertionError("开关关闭时绝不真探")

    monkeypatch.setattr(probe_mod, "_tcp_connect", _must_not_run)
    config = SimpleNamespace(bot_tts_enabled=False, bot_tts_api_url=_URL)
    line = voice_status_line(config)
    assert "disabled" in line


def test_status_line_running_down_and_recovered() -> None:
    config = SimpleNamespace(bot_tts_enabled=True, bot_tts_api_url=_URL)
    assert "reachable" in voice_status_line(config, health=_health("reachable"))
    assert "unreachable" in voice_status_line(config, health=_health("unreachable"))
    assert (
        "已恢复" in voice_status_line(config, health=_health("reachable", recovered=True))
    )
    assert "unknown" in voice_status_line(config, health=_health("unknown"))


def test_status_line_unreachable_includes_redacted_backoff_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(bot_tts_enabled=True, bot_tts_api_url=_URL)
    monkeypatch.setattr(
        probe_mod,
        "_tts_backoff_reason",
        lambda: "服务不可达：退避冷却中（剩 9 秒）｜上次失败：C:\\Users\\secret\\ref.wav",
    )
    line = voice_status_line(config, health=_health("unreachable"))
    assert "退避冷却中" in line
    assert "C:\\Users" not in line  # 脱敏红线：本机路径绝不进状态行


def test_status_line_reads_real_tts_backoff_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任务4状态来源集成：真实读 T57 退避公共态（``_backoff_reason``）。"""
    import plugins.bot_unified_runtime.domains.media.capabilities.tts as tts_mod

    monkeypatch.setattr(tts_mod, "_last_failure_at", time.monotonic())
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "服务不可达：ConnectError")
    config = SimpleNamespace(bot_tts_enabled=True, bot_tts_api_url=_URL)
    line = voice_status_line(config, health=_health("unreachable"))
    assert "退避冷却中" in line
    assert "ConnectError" in line


def test_status_line_probes_lazily_when_health_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_clock(monkeypatch)
    monkeypatch.setattr(probe_mod, "_tcp_connect", _stub_connect_ok)
    config = SimpleNamespace(bot_tts_enabled=True, bot_tts_api_url=_URL)
    line = voice_status_line(config)  # 未传 health → 探针惰性触发一次
    assert "reachable" in line
