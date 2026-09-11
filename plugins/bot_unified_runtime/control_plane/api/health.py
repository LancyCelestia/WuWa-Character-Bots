"""控制面健康与只读状态端点（B4 §6.1 的 M1 最小面）。

- ``GET /healthz``：本地存活探针，无鉴权、无信息量（常量 ``{"ok": true}``）。
- ``GET /admin/api/v1/health``：进程内组件可达性（注入单例逐一 ping）。
- ``GET /admin/api/v1/status/bot``：进程概览（启动时间/运行时长/时区）。
- ``GET /admin/api/v1/status/models``：渠道健康快照投影——DTO 白名单制
  （B4 §8.1），只回 model_id/state/计数/延迟/脱敏 last_error/last_ok_at，
  绝不包含 api_key/base_url 等凭据段。

数据源全部经构造注入（B4 §3.1 规则 1），本模块不 import NoneBot。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter

from ..audit import redact_error_for_dto
from . import ControlPlaneError

# last_error 只保留短文本并脱敏（B4 §6.1：last_error(脱敏)）。
_LAST_ERROR_MAX_CHARS = 200


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_healthz_router() -> APIRouter:
    """无鉴权存活探针：只回常量，不回任何配置/版本细节（B4 §4）。"""
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True}

    return router


def build_health_router(
    *,
    channel_health_store: Any | None = None,
    audit_store: Any | None = None,
    started_at: datetime | str | None = None,
    timezone_name: str = "",
) -> APIRouter:
    """``/admin/api/v1`` 只读最小面；依赖注入由 create_control_plane_app 完成。"""
    router = APIRouter(prefix="/admin/api/v1")

    @router.get("/health")
    def health() -> dict[str, Any]:
        checks: dict[str, str] = {"control_plane": "ok"}
        ok = True
        if channel_health_store is not None:
            try:
                channel_health_store.report()
                checks["channel_health_store"] = "ok"
            except Exception:  # noqa: BLE001 - 健康检查只呈报，不外溢异常。
                checks["channel_health_store"] = "unavailable"
                ok = False
        if audit_store is not None:
            try:
                reachable = bool(audit_store.ping())
            except Exception:  # noqa: BLE001
                reachable = False
            checks["audit_store"] = "ok" if reachable else "unavailable"
            ok = ok and reachable
        return {"ok": ok, "checks": checks, "generated_at": _now_iso()}

    @router.get("/status/bot")
    def status_bot() -> dict[str, Any]:
        started_iso = ""
        uptime_seconds: float | None = None
        if started_at is not None:
            try:
                moment = (
                    started_at
                    if isinstance(started_at, datetime)
                    else datetime.fromisoformat(str(started_at))
                )
                started_iso = moment.astimezone().isoformat(timespec="seconds")
                uptime_seconds = round(
                    (datetime.now().astimezone() - moment).total_seconds(), 3
                )
            except (ValueError, TypeError, OSError):
                started_iso = ""
                uptime_seconds = None
        return {
            "started_at": started_iso,
            "uptime_seconds": uptime_seconds,
            "timezone": str(timezone_name or ""),
        }

    @router.get("/status/models")
    def status_models() -> dict[str, Any]:
        if channel_health_store is None:
            # 未接线（如独立冒烟启动）：如实回空集，不伪造状态。
            return {"items": [], "generated_at": _now_iso()}
        try:
            rows = channel_health_store.report()
        except Exception as exc:
            raise ControlPlaneError(
                503,
                "store_unavailable",
                "渠道健康库暂不可用。",
            ) from exc
        items = [
            {
                "model_id": str(row.get("model_id", "")),
                "state": str(row.get("state", "")),
                "consecutive_fails": int(row.get("consecutive_fails", 0) or 0),
                "latency_ms": row.get("latency_ms"),
                "last_error": redact_error_for_dto(
                    row.get("last_error", ""), _LAST_ERROR_MAX_CHARS
                ),
                "last_ok_at": str(row.get("last_ok_at", "") or ""),
            }
            for row in rows
        ]
        return {"items": items, "generated_at": _now_iso()}

    return router


__all__ = ["build_health_router", "build_healthz_router"]
