"""控制面认证（B4 §5，阶段 1 形态）：Bearer token + 失败限速。

- 管理员只配置 token 的 SHA-256（``BOT_CONTROL_PLANE_TOKEN_SHA256``），
  明文只在生成时展示一次；比较用 ``hmac.compare_digest``（恒定时间）。
- Token 只允许出现在 ``Authorization: Bearer`` 头，不接受 URL/query 传递。
- ``TOKEN_SHA256`` 为空 = 未配置：除 ``/healthz`` 外一律 503
  ``control_plane_not_provisioned``（防"忘了配 token 就裸奔"）。
- 失败限速：同一来源 60 秒内 5 次失败 → 后续请求 429；来源按掩码粒度
  记录（IPv4 /32、IPv6 /128，即主机粒度——阶段 1 只绑环回，来源恒为本机）。
- 未来可插拔（只留接口，不实现）：:class:`Authenticator` Protocol，Bearer
  为第一个实现；角色固定 ``admin``。
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque
from typing import Any, Protocol

# 失败限速参数（B4 §5.1：60 秒窗口内 5 次失败）。
FAILURE_WINDOW_SECONDS = 60.0
FAILURE_MAX_COUNT = 5


class Principal:
    """认证主体（阶段 1：token subject + 固定 admin 角色）。"""

    __slots__ = ("roles", "subject")

    def __init__(self, subject: str, roles: tuple[str, ...] = ("admin",)) -> None:
        self.subject = subject
        self.roles = roles


class Authenticator(Protocol):
    """可插拔认证协议（B4 §5.2）：未来可接密码/TOTP/OIDC 等。"""

    async def authenticate(self, request: Any) -> Principal | None:
        """校验请求凭据；通过返回 Principal，失败返回 None。"""
        ...  # pragma: no cover


def hash_token(token: str) -> str:
    """token 明文 → SHA-256 十六进制（管理员配置只存该摘要）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mask_source(client_host: str) -> str:
    """来源掩码（B4 §5.1）：IPv4 取 /32、IPv6 取 /128 粒度，即主机本身。

    阶段 1 控制面只绑环回，来源恒为本机；保留函数便于未来公网部署时
    在此收窄掩码粒度（如 /24），不影响调用方。
    """
    text = str(client_host or "").strip()
    return text or "unknown"


class BearerAuthenticator:
    """Bearer token 校验 + 同源失败限速（线程安全）。"""

    def __init__(
        self,
        token_sha256: str,
        *,
        failure_window_seconds: float = FAILURE_WINDOW_SECONDS,
        failure_max_count: int = FAILURE_MAX_COUNT,
    ) -> None:
        self.expected_digest = str(token_sha256 or "").strip().lower()
        self._window = max(1.0, float(failure_window_seconds))
        self._max_failures = max(1, int(failure_max_count))
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    @property
    def provisioned(self) -> bool:
        """是否已配置 token 摘要（空 = 整个 API 面降级 503）。"""
        return bool(self.expected_digest)

    # ---- 限速 ----

    def failure_blocked(self, source: str) -> float:
        """该来源是否处于失败限速冷却中；返回剩余秒数（0 = 未拦截）。"""
        with self._lock:
            marks = self._failures.get(source)
            if not marks:
                return 0.0
            now = time.monotonic()
            while marks and now - marks[0] > self._window:
                marks.popleft()
            if len(marks) >= self._max_failures:
                return max(1.0, self._window - (now - marks[0]))
            return 0.0

    def register_failure(self, source: str) -> None:
        with self._lock:
            now = time.monotonic()
            marks = self._failures[source]
            marks.append(now)
            while marks and now - marks[0] > self._window:
                marks.popleft()
            while len(marks) > self._max_failures:
                marks.popleft()

    @staticmethod
    def source_key_of(request: Any) -> str:
        """从请求提取掩码后的来源键（失败限速的分桶键）。"""
        return mask_source(getattr(getattr(request, "client", None), "host", ""))

    # ---- 认证 ----

    async def authenticate(self, request: Any) -> Principal | None:
        """校验 ``Authorization: Bearer <token>``；SHA-256 恒定时间比较。"""
        header = str(request.headers.get("authorization", "") or "")
        if not header.lower().startswith("bearer "):
            return None
        token = header[7:].strip()
        if not token:
            return None
        digest = hash_token(token)
        if not self.expected_digest or not hmac.compare_digest(
            digest, self.expected_digest
        ):
            return None
        return Principal("bearer-admin")
