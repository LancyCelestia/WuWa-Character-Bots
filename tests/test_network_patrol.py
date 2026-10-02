"""network_patrol 单元回归（W1-③ + Clash 探针）。

- TCP 探活：真监听 socket=活、死端口=down；
- HTTPS 探活：任何 HTTP 应答=可达（含 4xx）、异常=down、直连腿硬直连语义；
- 巡检编排：双腿矩阵 + Clash 死时代理腿免测直接 down；
- 差分与告警行：变坏/恢复边界、首轮建基线不告警；
- 连续失败去抖（2026-10-02 裁定）：连败达阈值才报 down、中途成功清零、
  恢复只对报过 down 的目标发、根装配接线锁；
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


# ==================== 连续失败去抖（2026-10-02 裁定：连续 5 次炸了才报） ====================


def _alert_rounds(
    debounce: patrol.DownDebounce, observed: list[dict[str, bool]]
) -> list[list[tuple[str, bool]]]:
    """把多轮原始观测喂进「去抖 + state_delta」的接线同款链，逐轮返回告警差分。"""
    previous: dict[str, bool] | None = None
    deltas: list[list[tuple[str, bool]]] = []
    for current in observed:
        alerted = debounce.debounced_state(current)
        deltas.append(patrol.state_delta(previous, alerted))
        previous = alerted
    return deltas


def test_debounce_default_threshold_is_five() -> None:
    assert patrol.DEFAULT_DOWN_THRESHOLD == 5
    from plugins.bot_unified_runtime.config import Config

    assert Config.model_fields["bot_network_patrol_down_threshold"].default == 5


def test_debounce_1_to_4_consecutive_failures_do_not_alert() -> None:
    debounce = patrol.DownDebounce()
    failing = {"a.test:direct": False, "a.test:proxy": True}
    for delta in _alert_rounds(debounce, [failing] * 4):
        assert delta == [], f"未达阈值竟出告警差分：{delta}"


def test_debounce_fifth_consecutive_failure_alerts_down() -> None:
    debounce = patrol.DownDebounce()
    failing = {"a.test:direct": False, "a.test:proxy": True}
    deltas = _alert_rounds(debounce, [failing] * 5)
    assert deltas[:4] == [[]] * 4
    assert deltas[4] == [("a.test:direct", False)], f"第 5 次连续失败必须报 down：{deltas[4]}"


def test_debounce_midway_success_resets_streak() -> None:
    debounce = patrol.DownDebounce()
    fail: dict[str, bool] = {"a.test:direct": False}
    ok: dict[str, bool] = {"a.test:direct": True}
    # 连败 4 → 成功 1（清零）→ 再连败 4：全程不出告警；第 5 枚连败才报。
    deltas = _alert_rounds(debounce, [fail] * 4 + [ok] + [fail] * 4 + [fail])
    assert deltas[:9] == [[]] * 9, f"中途成功应清零连败计数，未达 5 连败不得出告警：{deltas}"
    assert deltas[9] == [("a.test:direct", False)]


def test_debounce_recovery_line_only_for_reported_down() -> None:
    debounce = patrol.DownDebounce()
    fail: dict[str, bool] = {"a.test:direct": False}
    ok: dict[str, bool] = {"a.test:direct": True}
    # 未达阈值的 blip（炸一轮立刻恢复）：变坏与恢复两侧都不出声。
    blip = _alert_rounds(patrol.DownDebounce(), [fail, ok])
    assert blip == [[], []], f"未报过 down 的目标不得进恢复侧：{blip}"
    # 报过 down 之后恢复 ⇒ 恰发一条恢复行，且文案与既有告警行兼容；其后不再发声。
    deltas = _alert_rounds(debounce, [fail] * 5 + [ok] + [ok])
    assert deltas[5] == [("a.test:direct", True)]
    lines = patrol.format_alert_lines(deltas[5])
    assert any("a.test:direct 已恢复" in line for line in lines)
    assert deltas[6] == [], "恢复一次即止，不得重复发恢复行"


def test_debounce_threshold_one_degrades_to_undebounced_delta() -> None:
    """阈值=1 退化为旧的「原始观测单轮差分」：首轮基线静默（含首轮就在失败的关键腿，
    与去抖前老行为同形）；此后「好基线 → 坏」边界照常报 down，连续失败不重复刷屏。"""
    debounce = patrol.DownDebounce(threshold=1)
    fail: dict[str, bool] = {"a.test:direct": False}
    assert _alert_rounds(debounce, [fail, fail, fail]) == [[], [], []]
    ok: dict[str, bool] = {"a.test:direct": True}
    deltas = _alert_rounds(patrol.DownDebounce(threshold=1), [ok, fail, fail])
    assert deltas[1] == [("a.test:direct", False)], "阈值=1 时基线后首个失败边界必须出声"
    assert deltas[2] == [], "已报 down 的目标不重复刷屏"


def test_debounce_threshold_below_one_clamps_to_one() -> None:
    assert patrol.DownDebounce(threshold=0).threshold == 1


def test_patrol_wiring_uses_debounced_state_as_delta_baseline() -> None:
    """接线锁（文本形态，同仓 AST/字面锁先例）：根装配的差分基线必须是去抖稳态，
    不许退回裸观测（摘掉去抖这枚锁必须当场红——防「改回去测试全绿」）。"""
    from pathlib import Path

    src = (
        Path(patrol.__file__).resolve().parents[2] / "__init__.py"
    ).read_text(encoding="utf-8")
    assert "DownDebounce(threshold=down_threshold)" in src
    assert "debounce.debounced_state(current)" in src
    assert 'state_delta(state_holder.get("last"), alerted)' in src
    assert 'getattr(config, "bot_network_patrol_down_threshold"' in src


# ==================== 失败分型（2026-10-02 澜汐裁定 b） ====================


def test_classify_local_proxy_family_is_blamed_on_clash() -> None:
    """refused / proxyconnect / clash port down（代理腿）⇒ 归因「本机 Clash 不在家」；
    clash 腿本身 ⇒ 端口未监听。这是 10-02 事故里被当成"渠道掉了"报的那一族。"""
    assert "不在家" in patrol.classify_leg_failure(
        "aiprc.top:proxy", "ConnectError: proxyconnect tcp 127.0.0.1:7890: connectex: refused"
    )
    assert "不在家" in patrol.classify_leg_failure("aiprc.top:proxy", "clash port down")
    assert "7890" in patrol.classify_leg_failure("127.0.0.1:7890:clash", "")


def test_classify_eof_ssl_on_proxy_leg_is_node_side() -> None:
    """经代理的 SSL/EOF/TLS ⇒ 归因节点抖动（一元机场腿），不是本机也不是上游域。"""
    kind = patrol.classify_leg_failure(
        "www.starapi.cc:proxy", "SSLError: UNEXPECTED_EOF_WHILE_READING"
    )
    assert "节点" in kind, kind


def test_classify_direct_leg_failure_is_upstream_side() -> None:
    """直连腿炸 ⇒ 「上游本身不可达，与本机代理无关」；超时另说。"""
    assert "上游" in patrol.classify_leg_failure(
        "toolcode.cc:direct", "ConnectError: [WinError 1225] 拒绝连接"
    )
    assert "线路" in patrol.classify_leg_failure(
        "api.deepseek.com:direct", "ConnectTimeout: timed out"
    )


def test_format_alert_lines_down_carries_kind_and_detail() -> None:
    """变坏行自带分型与探针细节（截断），恢复行口径不变；details 缺省 None 兼容旧调用。"""
    lines = patrol.format_alert_lines(
        [("x.test:proxy", False), ("y.test:direct", True)],
        {"x.test:proxy": "ConnectError: target machine actively refused it"},
    )
    assert "不可达" in lines[0] and "不在家" in lines[0] and "refused" in lines[0]
    assert "已恢复" in lines[1]
    legacy = patrol.format_alert_lines([("a:direct", False)])
    assert "a:direct 不可达" in legacy[0]


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
