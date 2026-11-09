"""连接监测三腿回归：OneBot 连接 / SnowLuma 进程端口 / bot 自身各自独立真值。

病史（W12 2026-10-19）：``runtime_state_probe`` 只返回一个 bool，语义是
「NoneBot 里有没有 online 的 bot」＝只测了 OneBot WS 连接，**SnowLuma 进程
健康度完全没测**。用户「SnowLuma 开着却显示异常」即由此而起——学校号那条腿
（3014）SYN_SENT 时整条连接被报成"异常"，而主号 3011 其实好好的。

本文件锁三件事：
1. 端口探测腿能对「真开着的端口」返 True、「真关着的端口」返 False；
2. ``snowluma.status`` 的 details 三条腿分开报，且保留老 ``connected`` 字段；
3. ``runtime_state_probe`` **老 bool 签名仍然可用**（向后兼容），
   新 dict 签名一并识别。
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token
from plugins.bot_unified_runtime.control_plane.connection_probe import (
    probe_ports,
    resolve_snowluma_ports,
)

# ---------------------------------------------------------------------------
# 夹具：真开一个口 / 找一个真关着的口
# ---------------------------------------------------------------------------


@pytest.fixture()
def listening_port() -> int:
    """真起一个 loopback 监听口，返回其端口号（比赌 3011 在不在更可靠）。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        yield srv.getsockname()[1]
    finally:
        srv.close()


@pytest.fixture()
def closed_port() -> int:
    """拿一个当前**确实没人监听**的 loopback 端口号。"""
    for _ in range(50):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.15)
        try:
            probe.connect(("127.0.0.1", port))
        except OSError:
            return port
        finally:
            probe.close()
    pytest.skip("找不到空闲端口")


# ---------------------------------------------------------------------------
# 1. 端口探测腿
# ---------------------------------------------------------------------------


def test_probe_ports_true_for_listening_false_for_closed(
    listening_port: int, closed_port: int
) -> None:
    result = probe_ports([listening_port, closed_port])
    assert result[listening_port] is True
    assert result[closed_port] is False


def test_probe_ports_never_raises_on_bad_port() -> None:
    """探测失败诚实降级成 False，不抛异常拖垮控制面。"""
    assert probe_ports([0]) == {0: False}


def test_probe_ports_empty_list_is_empty() -> None:
    assert probe_ports([]) == {}


def test_resolve_snowluma_ports_defaults_to_documented_nodes() -> None:
    ports = resolve_snowluma_ports(config=None, environ={})
    # 主号节点 3011 必在其中；学校号 3014 是独立故障点，必须分开可观测。
    assert 3011 in ports
    assert 3014 in ports


def test_resolve_snowluma_ports_honours_env_override() -> None:
    ports = resolve_snowluma_ports(config=None, environ={"BOT_SNOWLUMA_PROBE_PORTS": "3011, 9999"})
    assert ports == (3011, 9999)


def test_resolve_snowluma_ports_honours_config_attr() -> None:
    cfg = SimpleNamespace(bot_snowluma_probe_ports=[3011, 3012])
    assert resolve_snowluma_ports(config=cfg, environ={}) == (3011, 3012)


# ---------------------------------------------------------------------------
# 2. snowluma.status 三腿
# ---------------------------------------------------------------------------


def _config(tmp_path: Path, **extra: object) -> SimpleNamespace:
    return SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("read-test-token"),
        bot_control_plane_super_admin_token_sha256=hash_token("root-test-token"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
        **extra,
    )


def _app_with(tmp_path: Path, config: object, **factory: object) -> object:
    return create_control_plane_app(
        config,
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(),
        **factory,
    )


def _status_result(app: object) -> dict:
    """走默认装配的动作 handler（与 test_v21_risk_red_cp_app 同姿态）。

    不绕 HTTP：Host 白名单与限速是独立安全面，本文件只钉连接语义。
    """
    handler = app.state.action_service._registry["snowluma.status"][1]
    return asyncio.run(handler({}))


def _status_details(app: object) -> dict:
    result = _status_result(app)
    assert result["status"] == "ok", result
    return result["details"]


def test_status_reports_three_legs_separately(
    tmp_path: Path, listening_port: int, closed_port: int
) -> None:
    """探针给 dict 时：三条腿各自有值，connected 保留不动。"""
    app = _app_with(
        tmp_path,
        _config(tmp_path),
        runtime_attached=True,
        runtime_state_probe=lambda: {
            "onebot_connected": True,
            "snowluma_ports": {listening_port: True, closed_port: False},
        },
    )
    details = _status_details(app)
    assert details["connected"] is True
    assert details["onebot_connected"] is True
    assert details["snowluma_ports"] == {str(listening_port): True, str(closed_port): False}
    assert details["snowluma_process"] is True
    assert details["source"] == "runtime_probe"
    assert details["probed_at"]


def test_status_snowluma_process_false_when_all_ports_dead(
    tmp_path: Path, closed_port: int
) -> None:
    """OneBot 通但 SnowLuma 端口全死 = 两条腿一真一假，不得合并成一个 bool。"""
    app = _app_with(
        tmp_path,
        _config(tmp_path),
        runtime_state_probe=lambda: {
            "onebot_connected": True,
            "snowluma_ports": {closed_port: False},
        },
    )
    details = _status_details(app)
    assert details["onebot_connected"] is True
    assert details["snowluma_process"] is False
    # 老字段语义不变：仍看 OneBot 连接
    assert details["connected"] is True


def test_status_legacy_bool_probe_still_works(tmp_path: Path) -> None:
    """🔴 向后兼容：老签名返回 bool 的探针不得炸，且 connected 仍如实。"""
    app = _app_with(tmp_path, _config(tmp_path), runtime_state_probe=lambda: True)
    details = _status_details(app)
    assert details["connected"] is True
    assert details["onebot_connected"] is True

    app2 = _app_with(tmp_path, _config(tmp_path), runtime_state_probe=lambda: False)
    details2 = _status_details(app2)
    assert details2["connected"] is False
    assert details2["onebot_connected"] is False


def test_status_probe_error_still_fails_open(tmp_path: Path) -> None:
    def _boom() -> bool:
        raise RuntimeError("probe exploded")

    app = _app_with(tmp_path, _config(tmp_path), runtime_state_probe=_boom)
    result = _status_result(app)
    assert result["status"] == "degraded"
    assert result["details"]["connected"] is False
    assert result["details"]["source"] == "probe_error"
