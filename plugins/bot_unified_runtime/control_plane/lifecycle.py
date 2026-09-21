"""独立控制面生命周期（设计 §3.2），不参与 Bot/webhook 的装配或信号处理。

注册入口默认不导入 Web 栈。状态服务可读取 ``state`` / ``failure_code``；
错误状态与生命周期日志只包含稳定代码，不包含异常文本、配置或应用对象。
"""

from __future__ import annotations

import asyncio
import errno
import logging
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal

from . import control_plane_settings, is_loopback_host

LifecycleState = Literal["off", "stopped", "starting", "running", "failed"]
ServerFactory = Callable[..., Any]
_LOGGER = logging.getLogger(__name__)
_DRIVER_ATTRIBUTE = "_bot_control_plane_lifecycle"


def _uvicorn_server(app: Any, *, host: str, port: int) -> Any:
    import uvicorn

    class EmbeddedServer(uvicorn.Server):
        # Bot 拥有进程信号；兼容新旧 uvicorn 的两种信号安装入口。
        @contextmanager
        def capture_signals(self) -> Iterator[None]:
            yield

        def install_signal_handlers(self) -> None:
            pass

    return EmbeddedServer(
        uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False)
    )


class ControlPlaneLifecycle:
    """仅在 driver 所属事件循环内使用；首次注册的配置固定到该对象。

    ``starting`` 不代表监听成功：必须看到 server.started 才报告 running。
    failed 保留到对象销毁；不会在重复 startup/shutdown 时静默重试或抹去。
    ``task`` 仅供诊断，不应由调用方直接取消。
    """

    def __init__(
        self,
        *,
        enabled: bool,
        host: str,
        port: int,
        app_factory: Callable[[], Any],
        server_factory: ServerFactory,
        shutdown_timeout: float,
        cancel_timeout: float,
    ) -> None:
        self._state: LifecycleState = "stopped" if enabled else "off"
        self.failure_code: str | None = None
        self.task: asyncio.Task[None] | None = None
        self._host = host
        self._port = port
        self._app_factory = app_factory
        self._server_factory = server_factory
        self._server: Any = None
        self._shutdown_timeout = shutdown_timeout
        self._cancel_timeout = cancel_timeout
        self._stopping = False
        self._shutdown_lock = asyncio.Lock()

    @property
    def state(self) -> LifecycleState:
        if (
            self._state == "starting"
            and self._server is not None
            and self._server.started
        ):
            return "running"
        return self._state

    def _fail(self, code: str) -> str:
        self._state = "failed"
        self.failure_code = code
        return f"Control plane lifecycle failed ({code})"

    async def start(self) -> None:
        """非阻塞调度 serve；同一轮重复启动不会重复创建应用/监听器。"""
        if self._state in {"off", "failed"} or self._stopping:
            return
        if self.task is not None and not self.task.done():
            return
        self._state = "starting"
        try:
            app = self._app_factory()
        except (Exception, SystemExit):
            _LOGGER.exception(self._fail("app_factory_failed"), exc_info=None)
            return
        try:
            self._server = self._server_factory(app, host=self._host, port=self._port)
        except (Exception, SystemExit):
            _LOGGER.exception(self._fail("server_factory_failed"), exc_info=None)
            return
        self.task = asyncio.create_task(self._serve(), name="control-plane-serve")

    async def _serve(self) -> None:
        # startup 后同一 tick 就 shutdown 时，不能再启动监听。
        if self._stopping:
            return
        try:
            await self._server.serve()
        except asyncio.CancelledError:
            if not self._stopping and self._state != "failed":
                _LOGGER.error(self._fail("server_cancelled"))
            raise
        except (Exception, SystemExit) as exc:
            # uvicorn 把 create_server 的 OSError 包装为 SystemExit；必须在
            # 任务内部截住，否则 Task 的 SystemExit 可直接终止 Bot 事件循环。
            cause = exc.__context__ if isinstance(exc, SystemExit) else exc
            if isinstance(cause, OSError) and (
                cause.errno in {errno.EADDRINUSE, errno.EADDRNOTAVAIL, errno.EACCES}
                or getattr(cause, "winerror", None) in {10048, 10049, 10013}
            ):
                code = "bind_failed"
            elif isinstance(exc, SystemExit):
                code = "server_start_failed"
            else:
                code = "server_failed"
            if self._state != "failed":
                _LOGGER.exception(self._fail(code), exc_info=None)
        else:
            if not self._stopping and self._state != "failed":
                _LOGGER.error(self._fail("server_exited"))

    async def shutdown(self) -> None:
        """should_exit → 有界等待 → cancel → 有界回收；重复关闭安全。

        不使用 wait_for(task)：协程吞掉 CancelledError 时它可能无界等待。
        若取消后仍不退出，保留任务引用和 failed 状态，绝不假报 stopped。
        """
        if self._state == "off":
            return
        async with self._shutdown_lock:
            task = self.task
            if task is None:
                return
            self._stopping = True
            try:
                self._server.should_exit = True
                if not task.done():
                    _, pending = await asyncio.wait(
                        {task}, timeout=self._shutdown_timeout
                    )
                    if pending:
                        _LOGGER.error(self._fail("shutdown_timeout"))
                        task.cancel()
                        _, pending = await asyncio.wait(
                            {task}, timeout=self._cancel_timeout
                        )
                        if pending:
                            _LOGGER.error(self._fail("cancel_timeout"))
                if task.done() and self._state != "failed":
                    self._state = "stopped"
            finally:
                self._stopping = False


def register_control_plane_lifecycle(
    driver: Any,
    config: object | None,
    app_factory: Callable[[], Any],
    *,
    server_factory: ServerFactory | None = None,
    shutdown_timeout: float = 5.0,
    cancel_timeout: float = 1.0,
) -> ControlPlaneLifecycle:
    """挂载 §3.2 的独立服务，返回可查询对象；不修改 webhook/生产配置。

    注入工厂契约：``server_factory(app, *, host, port)``，返回具有
    ``started``、``should_exit`` 和异步 ``serve()`` 的对象；注入时不导入
    uvicorn。默认 8742，仅允许现有 loopback 白名单；localhost 固定转为
    127.0.0.1 避免 DNS 歧义。公网确认文件不在此入口受理。
    同一 driver 重复注册返回首次对象，不动态重载配置。
    """
    existing = getattr(driver, _DRIVER_ATTRIBUTE, None)
    if isinstance(existing, ControlPlaneLifecycle):
        return existing
    settings = control_plane_settings(config)
    lifecycle = ControlPlaneLifecycle(
        enabled=settings.enabled,
        host="127.0.0.1" if settings.host.lower() == "localhost" else settings.host,
        port=settings.port,
        app_factory=app_factory,
        server_factory=server_factory
        if server_factory is not None
        else _uvicorn_server,
        shutdown_timeout=shutdown_timeout,
        cancel_timeout=cancel_timeout,
    )
    if not settings.enabled:
        return lifecycle
    setattr(driver, _DRIVER_ATTRIBUTE, lifecycle)
    if not is_loopback_host(settings.host):
        _LOGGER.error(lifecycle._fail("host_not_allowed"))
    elif settings.port == 8080 or settings.port == getattr(config, "port", None):
        _LOGGER.error(lifecycle._fail("port_not_allowed"))
    elif any(
        not math.isfinite(value) or value < 0
        for value in (shutdown_timeout, cancel_timeout)
    ):
        _LOGGER.error(lifecycle._fail("invalid_timeout"))
    else:
        driver.on_startup(lifecycle.start)
        driver.on_shutdown(lifecycle.shutdown)
    return lifecycle
