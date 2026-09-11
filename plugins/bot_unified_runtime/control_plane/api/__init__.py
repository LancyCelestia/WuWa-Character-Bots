"""控制面 API 层（B4 §3.1）：参数校验、DTO 投影、错误码映射；无业务逻辑。

M1 只含健康与只读状态最小面（api/health.py）；config/ops/usage/tunnel 属
M2-M5，不在本轮。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any


def new_debug_id(now: datetime | None = None) -> str:
    """错误追踪 id（B4 §4 示例格式：``cp-20260912-ab12cd34``）。"""
    moment = now or datetime.now(timezone.utc).astimezone()
    return f"cp-{moment.strftime('%Y%m%d')}-{secrets.token_hex(4)}"


def error_body(code: str, debug_id: str, message: str) -> dict[str, Any]:
    """统一错误体（B4 §4）：永不回 ``str(exc)``。"""
    return {
        "error": {
            "code": str(code),
            "debug_id": str(debug_id),
            "message": str(message),
        }
    }


class ControlPlaneError(Exception):
    """携带稳定错误码的控制面异常；由 app 级 handler 转 §4 错误体。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code)
        self.message = str(message)
        self.headers = headers


__all__ = ["ControlPlaneError", "error_body", "new_debug_id"]
