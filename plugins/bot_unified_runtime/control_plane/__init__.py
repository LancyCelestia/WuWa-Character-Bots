"""B4 控制面（M1 骨架）：独立 uvicorn 挂载、总开关默认关。

设计规格：``docs/design/control-plane-api.md``（仅 M1 阶段）。

- 独立监听，默认 ``127.0.0.1:8742``，不复用 NoneBot webhook 端口；
- **总开关 ``BOT_CONTROL_PLANE_ENABLED`` 默认关**：开关解析走 getattr
  防御式（Config 字段 ``bot_control_plane_enabled`` → os.environ → 默认
  False），字段缺失 = 关；关闭时不启动服务、无任何导入副作用（本包顶层
  不导入 fastapi/uvicorn，app 工厂惰性加载）。
- M1 面：``/healthz`` + ``/admin/api/v1/health`` + 只读
  ``/status/bot``、``/status/models``；Bearer token（SHA-256 恒定时间
  比较，见 auth.py）；未配置 token 时 API 面一律 503。
- M2+（状态面其余端点、配置读写、运维动作、隧道计量）一律不做。

配置键（getattr 防御式读取，config.py 未加字段时全部取默认值）：

.. code-block:: text

    BOT_CONTROL_PLANE_ENABLED=false          # 总开关，默认关
    BOT_CONTROL_PLANE_HOST=127.0.0.1         # 非 loopback 需确认文件（§9.7）
    BOT_CONTROL_PLANE_PORT=8742
    BOT_CONTROL_PLANE_TOKEN_SHA256=          # 空 = API 面一律 503
    BOT_CONTROL_PLANE_HOST_ALLOWLIST=        # 额外 Host 白名单（逗号分隔），
                                             # 防DNS rebinding（审查 P-01，§8.2）
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ControlPlaneSettings",
    "control_plane_enabled",
    "control_plane_settings",
    "create_control_plane_app",
    "serve",
]

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8742
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _flag_value(raw: object) -> bool | None:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in {"1", "true", "on", "yes"}:
        return True
    if text in {"0", "false", "off", "no"}:
        return False
    return None


@dataclass(frozen=True)
class ControlPlaneSettings:
    """控制面运行设置（全部默认关闭/环回，B4 §3.2）。"""

    enabled: bool = False
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    token_sha256: str = ""
    # 额外 Host 白名单条目（host 或 host:port，省端口继承控制面端口）；
    # 默认白名单（127.0.0.1/localhost + 端口）在 _app 侧始终叠加，不可关。
    host_allowlist: tuple[str, ...] = ()


def _allowlist_value(raw: object) -> tuple[str, ...]:
    """归一白名单配置：str 按逗号拆分，list/tuple 逐项收；空项剔除。"""
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        pieces = [str(item) for item in raw]
    else:
        pieces = str(raw).split(",")
    return tuple(piece.strip() for piece in pieces if piece.strip())


def control_plane_settings(config: object | None = None) -> ControlPlaneSettings:
    """解析控制面设置：Config 字段（getattr 防御式）→ os.environ → 默认。

    NoneBot 会把 .env 的 ``BOT_*`` 小写映射进 Config，getattr 主路径覆盖
    生产；os.environ 兜底服务于裸脚本与测试（monkeypatch.setenv）。
    """
    enabled = False
    for raw in (
        getattr(config, "bot_control_plane_enabled", None),
        os.environ.get("BOT_CONTROL_PLANE_ENABLED"),
    ):
        value = _flag_value(raw)
        if value is not None:
            enabled = value
            break
    host = str(
        getattr(config, "bot_control_plane_host", None)
        or os.environ.get("BOT_CONTROL_PLANE_HOST")
        or _DEFAULT_HOST
    ).strip()
    port = _DEFAULT_PORT
    for raw in (
        getattr(config, "bot_control_plane_port", None),
        os.environ.get("BOT_CONTROL_PLANE_PORT"),
    ):
        if raw is None:
            continue
        try:
            port_value = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= port_value <= 65535:
            port = port_value
            break
    token_sha256 = str(
        getattr(config, "bot_control_plane_token_sha256", None)
        or os.environ.get("BOT_CONTROL_PLANE_TOKEN_SHA256")
        or ""
    ).strip()
    host_allowlist: tuple[str, ...] = ()
    for raw in (
        getattr(config, "bot_control_plane_host_allowlist", None),
        os.environ.get("BOT_CONTROL_PLANE_HOST_ALLOWLIST"),
    ):
        entries = _allowlist_value(raw)
        if entries:
            host_allowlist = entries
            break
    return ControlPlaneSettings(
        enabled=enabled,
        host=host or _DEFAULT_HOST,
        port=port,
        token_sha256=token_sha256,
        host_allowlist=host_allowlist,
    )


def control_plane_enabled(config: object | None = None) -> bool:
    """总开关（唯一解析源）：字段缺失 = 关（铁律：默认关）。"""
    return control_plane_settings(config).enabled


def is_loopback_host(host: str) -> bool:
    return str(host or "").strip().lower() in _LOOPBACK_HOSTS


_LAZY_EXPORTS = ("create_control_plane_app", "serve")


def __getattr__(name: str) -> Any:
    """惰性导出：不触发 fastapi/uvicorn 导入（关闭态零导入副作用）。"""
    if name in _LAZY_EXPORTS:
        from . import _app

        return getattr(_app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
