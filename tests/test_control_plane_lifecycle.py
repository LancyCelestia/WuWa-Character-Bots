"""§3.2 生命周期离线契约：不导入 Bot，不绑定端口，不接触运行数据。"""

from __future__ import annotations

import asyncio
import builtins
import errno
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

PACKAGE = (
    Path(__file__).resolve().parents[1] / "plugins/bot_unified_runtime/control_plane"
)
_ORIGINAL_IMPORT = builtins.__import__
SECRET = "sk-private-token C:/private/.env BOT_SECRET=private"


def test_lifecycle_module_exists():
    assert (PACKAGE / "lifecycle.py").is_file(), "Lifecycle implementation is missing"


@pytest.fixture
def lifecycle_module(monkeypatch):
    # 独立加载真实控制面包，避开 Bot 父包的适配器与生产装配副作用。
    for key in tuple(os.environ):
        if key.startswith("BOT_CONTROL_PLANE_"):
            monkeypatch.delenv(key)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"uvicorn", "fastapi"}:
            pytest.fail(f"Unexpected eager import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    name = "_cp_lifecycle_test"
    for suffix, path in (
        ("", PACKAGE / "__init__.py"),
        (".lifecycle", PACKAGE / "lifecycle.py"),
    ):
        assert path.exists(), f"Missing lifecycle implementation: {path.name}"
        spec = importlib.util.spec_from_file_location(name + suffix, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name + suffix, module)
        spec.loader.exec_module(module)
    return module


class Driver:
    def __init__(self):
        self.startups = []
        self.shutdowns = []

    def on_startup(self, hook):
        self.startups.append(hook)
        return hook

    def on_shutdown(self, hook):
        self.shutdowns.append(hook)
        return hook


class Server:
    def __init__(self, *, error=None, ready=True, stubborn=False):
        self.started = False
        self.should_exit = False
        self.error = error
        self.ready = ready
        self.stubborn = stubborn
        self.calls = 0
        self.cancelled = False
        self.finished = False

    async def serve(self):
        self.calls += 1
        try:
            if self.error:
                raise self.error
            self.started = self.ready
            while self.stubborn or not self.should_exit:
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.finished = True


async def settle():
    for _ in range(8):
        await asyncio.sleep(0)


def register(module, *, config=None, server=None, app_factory=None, **kwargs):
    driver = Driver()
    server = Server() if server is None else server
    factory = Mock(return_value=server)
    app_factory = Mock(return_value=object()) if app_factory is None else app_factory
    config = (
        SimpleNamespace(bot_control_plane_enabled=True) if config is None else config
    )
    lifecycle = module.register_control_plane_lifecycle(
        driver, config, app_factory, server_factory=factory, **kwargs
    )
    return lifecycle, driver, server, factory, app_factory


def test_disabled_has_no_import_factory_hook_or_task_side_effects(
    lifecycle_module, monkeypatch
):
    monkeypatch.setattr(
        asyncio, "create_task", Mock(side_effect=AssertionError("task created"))
    )
    lifecycle, driver, _, factory, app = register(
        lifecycle_module, config=SimpleNamespace(bot_control_plane_enabled=False)
    )
    assert lifecycle.state == "off"
    assert lifecycle.failure_code is None
    assert lifecycle.task is None
    assert driver.startups == driver.shutdowns == []
    asyncio.run(lifecycle.start())
    asyncio.run(lifecycle.shutdown())
    assert lifecycle.state == "off"
    factory.assert_not_called()
    app.assert_not_called()


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "::", "192.168.1.2", "example.org", SECRET]
)
def test_non_loopback_fails_before_hooks_and_factories(lifecycle_module, host, caplog):
    lifecycle, driver, _, factory, app = register(
        lifecycle_module,
        config=SimpleNamespace(
            bot_control_plane_enabled=True, bot_control_plane_host=host
        ),
    )
    assert lifecycle.state == "failed"
    assert lifecycle.failure_code == "host_not_allowed"
    assert driver.startups == driver.shutdowns == []
    factory.assert_not_called()
    app.assert_not_called()
    assert SECRET not in caplog.text


@pytest.mark.parametrize("port,webhook", [(8080, None), (9000, 9000)])
def test_webhook_port_is_rejected(lifecycle_module, port, webhook):
    lifecycle, driver, _, factory, app = register(
        lifecycle_module,
        config=SimpleNamespace(
            bot_control_plane_enabled=True, bot_control_plane_port=port, port=webhook
        ),
    )
    assert lifecycle.state == "failed"
    assert lifecycle.failure_code == "port_not_allowed"
    assert not driver.startups
    factory.assert_not_called()
    app.assert_not_called()


@pytest.mark.parametrize(
    "host,expected",
    [("127.0.0.1", "127.0.0.1"), ("::1", "::1"), ("LOCALHOST", "127.0.0.1")],
)
def test_start_stop_and_real_readiness(lifecycle_module, host, expected):
    async def scenario():
        lifecycle, driver, server, factory, app = register(
            lifecycle_module,
            config=SimpleNamespace(
                bot_control_plane_enabled=True, bot_control_plane_host=host
            ),
        )
        assert lifecycle.state == "stopped"
        app.assert_not_called()
        assert len(driver.startups) == len(driver.shutdowns) == 1
        await driver.startups[0]()
        assert lifecycle.state == "starting"
        assert isinstance(lifecycle.task, asyncio.Task)
        await settle()
        assert lifecycle.state == "running"
        assert lifecycle.failure_code is None
        factory.assert_called_once_with(app.return_value, host=expected, port=8742)
        await driver.shutdowns[0]()
        assert server.should_exit and server.finished
        assert not server.cancelled
        assert lifecycle.task.done()
        assert lifecycle.state == "stopped"
        await driver.shutdowns[0]()
        assert lifecycle.state == "stopped"

    asyncio.run(scenario())


def test_settings_parser_is_used_and_environment_port_respected(
    lifecycle_module, monkeypatch
):
    monkeypatch.setenv("BOT_CONTROL_PLANE_ENABLED", "true")
    monkeypatch.setenv("BOT_CONTROL_PLANE_PORT", "9876")

    async def scenario():
        lifecycle, driver, _, factory, app = register(
            lifecycle_module, config=SimpleNamespace()
        )
        await driver.startups[0]()
        await settle()
        factory.assert_called_once_with(app.return_value, host="127.0.0.1", port=9876)
        await lifecycle.shutdown()

    asyncio.run(scenario())


def test_registration_and_concurrent_start_are_idempotent(lifecycle_module):
    async def scenario():
        lifecycle, driver, server, factory, app = register(lifecycle_module)
        again = lifecycle_module.register_control_plane_lifecycle(
            driver,
            SimpleNamespace(bot_control_plane_enabled=True),
            app,
            server_factory=factory,
        )
        assert again is lifecycle
        assert len(driver.startups) == len(driver.shutdowns) == 1
        await asyncio.gather(*(driver.startups[0]() for _ in range(10)))
        await settle()
        task = lifecycle.task
        await lifecycle.start()
        assert lifecycle.task is task
        assert server.calls == 1
        app.assert_called_once()
        factory.assert_called_once()
        await asyncio.gather(lifecycle.shutdown(), lifecycle.shutdown())
        assert lifecycle.state == "stopped"

    asyncio.run(scenario())


def test_not_ready_remains_starting(lifecycle_module):
    async def scenario():
        lifecycle, _, _, _, _ = register(lifecycle_module, server=Server(ready=False))
        await lifecycle.start()
        await settle()
        assert lifecycle.state == "starting"
        await lifecycle.shutdown()
        assert lifecycle.state == "stopped"

    asyncio.run(scenario())


@pytest.mark.parametrize("error", [RuntimeError(SECRET), SystemExit(SECRET)])
def test_app_factory_failure_does_not_abort_bot_startup(
    lifecycle_module, error, caplog
):
    async def scenario():
        lifecycle, driver, _, factory, _ = register(
            lifecycle_module, app_factory=Mock(side_effect=error)
        )
        continued = []

        async def bot_startup():
            continued.append(True)

        driver.on_startup(bot_startup)
        for hook in driver.startups:
            await hook()
        assert continued == [True]
        assert lifecycle.state == "failed"
        assert lifecycle.failure_code == "app_factory_failed"
        assert lifecycle.task is None
        factory.assert_not_called()
        await lifecycle.shutdown()
        assert lifecycle.state == "failed"

    asyncio.run(scenario())
    assert SECRET not in caplog.text
    assert "app_factory_failed" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize(
    "error,code",
    [
        (OSError(errno.EADDRINUSE, SECRET), "bind_failed"),
        (SystemExit(SECRET), "server_start_failed"),
        (RuntimeError(SECRET), "server_failed"),
    ],
)
def test_serve_failure_is_consumed_inside_task(lifecycle_module, error, code, caplog):
    async def scenario():
        lifecycle, _, _, _, _ = register(lifecycle_module, server=Server(error=error))
        await lifecycle.start()
        await settle()
        assert lifecycle.state == "failed"
        assert lifecycle.failure_code == code
        assert lifecycle.task.done()
        assert lifecycle.task.exception() is None
        await lifecycle.shutdown()
        await lifecycle.shutdown()
        assert lifecycle.state == "failed"

    asyncio.run(scenario())
    assert SECRET not in caplog.text
    assert code in caplog.text


def test_uvicorn_style_bind_system_exit_preserves_failure_code(lifecycle_module):
    class BindFailure(Server):
        async def serve(self):
            try:
                raise OSError(errno.EADDRINUSE, SECRET)
            except OSError:
                await asyncio.sleep(0)
                raise SystemExit(1)

    async def scenario():
        lifecycle, _, _, _, _ = register(lifecycle_module, server=BindFailure())
        await lifecycle.start()
        await settle()
        assert lifecycle.state == "failed"
        assert lifecycle.failure_code == "bind_failed"
        assert lifecycle.task.exception() is None
        await lifecycle.shutdown()

    asyncio.run(scenario())


def test_shutdown_timeout_cancels_and_consumes_task(lifecycle_module):
    async def scenario():
        lifecycle, _, server, _, _ = register(
            lifecycle_module,
            server=Server(stubborn=True),
            shutdown_timeout=0.01,
            cancel_timeout=0.01,
        )
        await lifecycle.start()
        await settle()
        await asyncio.wait_for(lifecycle.shutdown(), timeout=0.5)
        assert server.should_exit and server.cancelled and server.finished
        assert lifecycle.task.done()
        assert lifecycle.state == "failed"
        assert lifecycle.failure_code == "shutdown_timeout"
        await lifecycle.shutdown()

    asyncio.run(scenario())


def test_immediate_shutdown_never_starts_listener(lifecycle_module):
    async def scenario():
        lifecycle, _, server, _, _ = register(lifecycle_module)
        await lifecycle.start()
        await lifecycle.shutdown()
        assert server.calls == 0
        assert lifecycle.task.done()
        assert lifecycle.state == "stopped"

    asyncio.run(scenario())


def test_unexpected_normal_serve_return_is_failure(lifecycle_module):
    class EarlyExit(Server):
        async def serve(self):
            return

    async def scenario():
        lifecycle, _, _, _, _ = register(lifecycle_module, server=EarlyExit())
        await lifecycle.start()
        await settle()
        assert lifecycle.state == "failed"
        assert lifecycle.failure_code == "server_exited"
        await lifecycle.shutdown()

    asyncio.run(scenario())


def test_default_uvicorn_factory_is_lazy_and_does_not_own_bot_signals(
    lifecycle_module, monkeypatch
):
    config_calls = []

    class FakeConfig:
        def __init__(self, app, **kwargs):
            config_calls.append((app, kwargs))

    class UvicornServer(Server):
        def __init__(self, config):
            super().__init__()
            self.config = config

        def capture_signals(self):
            pytest.fail("Control plane must not take over Bot signal handlers")

        def install_signal_handlers(self):
            pytest.fail("Control plane must not take over Bot signal handlers")

        async def serve(self):
            with self.capture_signals():
                self.install_signal_handlers()
                await super().serve()

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "uvicorn":
            return SimpleNamespace(Config=FakeConfig, Server=UvicornServer)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    async def scenario():
        driver, app = Driver(), object()
        lifecycle = lifecycle_module.register_control_plane_lifecycle(
            driver, SimpleNamespace(bot_control_plane_enabled=True), lambda: app
        )
        assert config_calls == []
        await lifecycle.start()
        await settle()
        assert lifecycle.state == "running"
        assert config_calls == [
            (
                app,
                {
                    "host": "127.0.0.1",
                    "port": 8742,
                    "log_config": None,
                    "access_log": False,
                },
            )
        ]
        await lifecycle.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("error", [RuntimeError(SECRET), SystemExit(SECRET)])
def test_server_factory_failure_is_safe(lifecycle_module, error, caplog):
    async def scenario():
        lifecycle, _, _, factory, _ = register(lifecycle_module)
        factory.side_effect = error
        await lifecycle.start()
        await lifecycle.start()
        assert lifecycle.state == "failed"
        assert lifecycle.failure_code == "server_factory_failed"
        assert lifecycle.task is None
        factory.assert_called_once()
        await lifecycle.shutdown()

    asyncio.run(scenario())
    assert SECRET not in caplog.text


@pytest.mark.parametrize("timeout", [-1, float("inf"), float("nan")])
def test_invalid_wait_budget_fails_closed(lifecycle_module, timeout):
    lifecycle, driver, _, factory, app = register(
        lifecycle_module, shutdown_timeout=timeout
    )
    assert lifecycle.state == "failed"
    assert lifecycle.failure_code == "invalid_timeout"
    assert not driver.startups
    factory.assert_not_called()
    app.assert_not_called()


def test_cancellation_resistant_task_has_bounded_shutdown_and_sticky_failure(
    lifecycle_module,
):
    async def scenario():
        release = asyncio.Event()

        class Resistant(Server):
            async def serve(self):
                self.started = True
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    await release.wait()

        lifecycle, _, server, _, _ = register(
            lifecycle_module,
            server=Resistant(),
            shutdown_timeout=0.01,
            cancel_timeout=0.01,
        )
        await lifecycle.start()
        await settle()
        try:
            await asyncio.wait_for(lifecycle.shutdown(), timeout=0.5)
            assert server.cancelled
            assert not lifecycle.task.done()
            assert lifecycle.state == "failed"
            assert lifecycle.failure_code == "cancel_timeout"
        finally:
            release.set()
            await asyncio.wait_for(lifecycle.task, timeout=0.5)
        assert lifecycle.state == "failed"
        assert lifecycle.failure_code == "cancel_timeout"

    asyncio.run(scenario())


def test_clean_shutdown_allows_a_fresh_start_without_overlapping_tasks(
    lifecycle_module,
):
    async def scenario():
        lifecycle, _, _, factory, app = register(lifecycle_module)
        factory.side_effect = [Server(), Server()]
        for _ in range(2):
            await lifecycle.start()
            await settle()
            assert lifecycle.state == "running"
            await lifecycle.shutdown()
            assert lifecycle.task.done()
            assert lifecycle.state == "stopped"
        assert app.call_count == 2

    asyncio.run(scenario())


def test_real_uvicorn_bind_conflict_without_opening_a_socket(
    lifecycle_module, monkeypatch
):
    # 只在此用例解除 Web 栈导入门；替换事件循环绑定入口，不创建真实 socket。
    monkeypatch.setattr(builtins, "__import__", _ORIGINAL_IMPORT)

    async def scenario():
        lifespan_events = []
        binds = []

        async def app(scope, receive, send):
            assert scope["type"] == "lifespan"
            while True:
                event = await receive()
                lifespan_events.append(event["type"])
                await send({"type": event["type"] + ".complete"})
                if event["type"] == "lifespan.shutdown":
                    return

        async def reject_bind(*args, **kwargs):
            binds.append((kwargs["host"], kwargs["port"]))
            raise OSError(errno.EADDRINUSE, "Address already in use")

        monkeypatch.setattr(asyncio.get_running_loop(), "create_server", reject_bind)
        lifecycle = lifecycle_module.register_control_plane_lifecycle(
            Driver(), SimpleNamespace(bot_control_plane_enabled=True), lambda: app
        )
        await lifecycle.start()
        await asyncio.wait_for(lifecycle.task, timeout=2)
        assert binds == [("127.0.0.1", 8742)]
        assert lifespan_events == ["lifespan.startup", "lifespan.shutdown"]
        assert lifecycle.state == "failed"
        assert lifecycle.failure_code == "bind_failed"
        assert lifecycle.task.exception() is None
        await lifecycle.shutdown()

    asyncio.run(scenario())
