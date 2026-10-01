"""network_patrol 单元回归（W1-③ + Clash 探针）。

- TCP 探活：真监听 socket=活、死端口=down；
- HTTPS 探活：任何 HTTP 应答=可达（含 4xx）、异常=down、直连腿硬直连语义；
- 巡检编排：双腿矩阵 + Clash 死时代理腿免测直接 down；
- 差分与告警行：变坏/恢复边界、首轮建基线不告警；
- JSONL 落盘与滚动。
全部离线：HTTP 腿用 MockTransport/捕获桩，TCP 腿用进程内临时 socket。
"""

from __future__ import annotations

import json
import socket

import httpx
import pytest

from plugins.bot_unified_runtime.domains.ops import network_patrol as patrol

# ==================== TCP 探活 ====================


def test_probe_tcp_alive_on_real_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    """活腿＝真监听 socket 真探活；死腿用 create_connection 桩——真实死端口
    有竞态（全量套件期间端口可能被其他用例的监听者抢走，09-30 实锤）。"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()
    try:
        assert patrol.probe_tcp(host, port) is True
    finally:
        server.close()

    def _refuse(address, timeout=0.0):
        raise ConnectionRefusedError(f"stub: {address}")

    monkeypatch.setattr(patrol.socket, "create_connection", _refuse)
    assert patrol.probe_tcp(host, port, timeout=0.5) is False


# ==================== HTTPS 探活 ====================


def test_probe_https_any_http_answer_counts_as_reachable() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, text="nope")
    )
    ok, detail = patrol.probe_https(
        "https://example.test/", proxy="", timeout=5, transport=transport
    )
    assert ok is True
    assert "HTTP 404" in detail


def test_probe_https_exception_becomes_down() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    ok, detail = patrol.probe_https(
        "https://example.test/", proxy="", timeout=5, transport=transport
    )
    assert ok is False
    assert "ConnectError" in detail


def test_probe_https_direct_leg_is_hard_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    """直连腿必须 trust_env=False（环境变量/系统代理不参与），代理腿显式传。"""
    captured: list[dict[str, object]] = []

    def spy(**kwargs: object) -> httpx.Client:
        captured.append(kwargs)
        raise httpx.ConnectError("stop before request")

    monkeypatch.setattr(httpx, "Client", spy)
    patrol.probe_https("https://example.test/", proxy="")
    patrol.probe_https("https://example.test/", proxy="http://127.0.0.1:7890")
    assert captured[0]["proxy"] is None
    assert captured[0]["trust_env"] is False
    assert captured[1]["proxy"] == "http://127.0.0.1:7890"
    assert captured[1]["trust_env"] is True


# ==================== 巡检编排 ====================


def test_run_patrol_builds_dual_path_matrix() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    report = patrol.run_patrol(
        targets=("alpha.test", "beta.test"),
        transport=transport,
        # 禁真端口：全量套件期间真实 Clash 状态会漂移（09-30 实锤竞态红）。
        tcp_probe=lambda host, port: True,
    )
    keys = [f"{leg.target}:{leg.path}" for leg in report.legs]
    assert keys == [
        "127.0.0.1:7890:clash",
        "alpha.test:direct",
        "alpha.test:proxy",
        "beta.test:direct",
        "beta.test:proxy",
    ]
    assert all(leg.ok for leg in report.legs)


def test_run_patrol_clash_down_skips_proxy_legs() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    report = patrol.run_patrol(
        targets=("alpha.test",),
        transport=transport,
        tcp_probe=lambda host, port: False,
    )
    by_path = {leg.path: leg for leg in report.legs}
    assert by_path["clash"].ok is False
    assert by_path["proxy"].ok is False
    assert "clash port down" in by_path["proxy"].detail
    # 直连腿照常实测（代理死不代表直连死）。
    assert by_path["direct"].ok is True


# ==================== 差分与告警行 ====================


def test_state_delta_first_round_is_silent() -> None:
    current = {"a:direct": True}
    assert patrol.state_delta(None, current) == []


def test_state_delta_reports_changes_both_ways() -> None:
    previous = {"a:direct": True, "b:proxy": False}
    current = {"a:direct": False, "b:proxy": True}
    delta = dict(patrol.state_delta(previous, current))
    assert delta == {"a:direct": False, "b:proxy": True}


def test_format_alert_lines_huma_tone() -> None:
    lines = patrol.format_alert_lines([("a:direct", False), ("b:proxy", True)])
    assert any("a:direct 不可达" in line for line in lines)
    assert any("b:proxy 已恢复" in line for line in lines)


# ==================== JSONL 落盘与滚动 ====================


def test_append_patrol_jsonl_roundtrip(tmp_path) -> None:
    target = tmp_path / "network_patrol.jsonl"
    report = patrol.PatrolReport(started_at=100.0)
    report.legs.append(patrol.PatrolLeg("127.0.0.1:7890", "clash", True, "ok"))
    patrol.append_patrol_jsonl(target, report)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ts"] == 100.0
    assert payload["legs"][0]["path"] == "clash"


def test_append_patrol_jsonl_rotates(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "network_patrol.jsonl"
    monkeypatch.setattr(patrol, "_PATROL_JSONL_MAX_BYTES", 16)
    report = patrol.PatrolReport(started_at=1.0)
    report.legs.append(patrol.PatrolLeg("t", "clash", True))
    patrol.append_patrol_jsonl(target, report)
    report2 = patrol.PatrolReport(started_at=2.0)
    report2.legs.append(patrol.PatrolLeg("t", "clash", True))
    patrol.append_patrol_jsonl(target, report2)
    assert target.with_name(target.name + ".1").exists()
    assert json.loads(target.read_text(encoding="utf-8"))["ts"] == 2.0
