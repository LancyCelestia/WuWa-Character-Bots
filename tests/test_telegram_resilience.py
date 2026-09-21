"""Telegram 轮询网络故障隔离：不启动 NoneBot，不连接外网。"""
from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


class NetworkError(Exception):
    pass


@pytest.fixture
def builder():
    return importlib.import_module("scripts.telegram_resilience").build_resilient_telegram_adapter


@pytest.mark.parametrize("api", ["get_updates", "getUpdates"])
def test_inner_poll_network_failure_retries_before_upstream_catches(builder, api):
    request = AsyncMock(side_effect=[NetworkError("Bearer secret C:/private"), NetworkError("secret"), ["update"]])
    escapes = []
    class Adapter:
        async def _call_api(self, bot, method, **data):
            return await request(bot, method, **data)
        async def poll(self, bot):
            try:
                return await self._call_api(bot, api, offset=17, timeout=30)
            except Exception as exc:
                escapes.append(exc)
                raise
    logger = SimpleNamespace(warning=Mock(), info=Mock())
    sleep = AsyncMock()
    cls = builder(Adapter, network_error=NetworkError, logger=logger, sleep=sleep)
    bot = object()
    assert asyncio.run(cls().poll(bot)) == ["update"]
    assert escapes == []
    assert [call.args[0] for call in sleep.call_args_list] == [3, 6]
    assert request.await_count == 3
    assert all(call.args == (bot, api) and call.kwargs == {"offset": 17, "timeout": 30} for call in request.call_args_list)
    assert logger.info.call_count == 1
    assert "secret" not in repr(logger.warning.call_args_list)


def test_startup_network_failure_retries_without_retrying_other_adapters(builder):
    poll = AsyncMock(side_effect=[NetworkError("secret"), "ready"])
    class Adapter:
        async def poll(self, bot):
            return await poll(bot)
    sleep = AsyncMock()
    logger = SimpleNamespace(warning=Mock(), info=Mock())
    cls = builder(Adapter, network_error=NetworkError, logger=logger, sleep=sleep)
    assert asyncio.run(cls().poll(object())) == "ready"
    assert sleep.await_count == 1
    assert Adapter.poll is not cls.poll  # 不 monkeypatch 上游类或其他进程适配器


@pytest.mark.parametrize("api", ["get_updates", "send_message", "delete_webhook"])
def test_non_network_api_errors_never_retried(builder, api):
    call = AsyncMock(side_effect=ValueError("invalid token or API request"))
    class Adapter:
        async def _call_api(self, bot, method, **data):
            return await call()
    sleep = AsyncMock()
    logger = SimpleNamespace(warning=Mock(), info=Mock())
    cls = builder(Adapter, network_error=NetworkError, logger=logger, sleep=sleep)
    with pytest.raises(ValueError):
        asyncio.run(cls()._call_api(object(), api))
    sleep.assert_not_awaited()
    logger.warning.assert_not_called()


def test_outbound_network_error_is_not_replayed(builder):
    call = AsyncMock(side_effect=NetworkError("unknown delivery result"))
    class Adapter:
        async def _call_api(self, bot, method, **data):
            return await call()
    sleep = AsyncMock()
    cls = builder(Adapter, network_error=NetworkError, logger=SimpleNamespace(warning=Mock(), info=Mock()), sleep=sleep)
    with pytest.raises(NetworkError):
        asyncio.run(cls()._call_api(object(), "send_message", text="fixture"))
    assert call.await_count == 1
    sleep.assert_not_awaited()


def test_cancellation_escapes_retry_and_never_restarts(builder):
    request = AsyncMock(side_effect=NetworkError("offline"))
    class Adapter:
        async def _call_api(self, bot, method, **data):
            return await request()
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    cls = builder(Adapter, network_error=NetworkError, logger=SimpleNamespace(warning=Mock(), info=Mock()), sleep=sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cls()._call_api(object(), "get_updates"))
    assert request.await_count == 1


def test_retry_delay_caps_and_logs_only_state_changes(builder):
    request = AsyncMock(side_effect=[*[NetworkError("offline") for _ in range(9)], []])
    class Adapter:
        async def _call_api(self, bot, method, **data):
            return await request()
    sleep = AsyncMock()
    logger = SimpleNamespace(warning=Mock(), info=Mock())
    cls = builder(Adapter, network_error=NetworkError, logger=logger, sleep=sleep)
    assert asyncio.run(cls()._call_api(object(), "get_updates")) == []
    assert [call.args[0] for call in sleep.call_args_list] == [3, 6, 12, 24, 48, 60, 60, 60, 60]
    assert logger.warning.call_count <= 6
    assert logger.info.call_count == 1


def test_production_registers_subclass_not_global_patch(builder):
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "build_resilient_telegram_adapter" for n in ast.walk(tree))
    assert not any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "TelegramAdapter" and t.attr == "poll" for t in n.targets) for n in ast.walk(tree))


def test_installed_adapter_retries_transport_but_preserves_offset_and_http_errors(builder):
    import httpx
    from nonebot.adapters.telegram import Adapter
    from nonebot.adapters.telegram.exception import NetworkError as ActualNetworkError

    from scripts.telegram_resilience import is_transient_telegram_error

    logger = SimpleNamespace(warning=Mock(), info=Mock())
    sleep = AsyncMock()
    cls = builder(Adapter, network_error=ActualNetworkError, logger=logger, sleep=sleep, retryable=is_transient_telegram_error)
    adapter = object.__new__(cls)  # 不运行 Adapter.setup / NoneBot 初始化
    adapter.adapter_config = SimpleNamespace(proxy=None)
    adapter.request = AsyncMock(side_effect=[httpx.ConnectError("fixture TLS failure"), SimpleNamespace(status_code=200, content=b'{"result": []}')])
    bot = SimpleNamespace(bot_config=SimpleNamespace(api_server="https://api.telegram.org/", token="123:fixture"))
    assert asyncio.run(adapter._call_api(bot, "get_updates", offset=17, timeout=30)) == []
    assert adapter.request.await_count == 2
    for call in adapter.request.call_args_list:
        assert call.args[0].json == {"offset": "17", "timeout": "30"}
    assert logger.info.call_count == 1
    adapter.request = AsyncMock(return_value=SimpleNamespace(status_code=409, content=b'{"description": "conflict"}'))
    with pytest.raises(ActualNetworkError):
        asyncio.run(adapter._call_api(bot, "get_updates"))
    assert adapter.request.await_count == 1  # 409 多实例冲突不是可恢复 TLS 故障


def test_retry_classification_does_not_hide_configuration_or_authorization_errors():
    from scripts.telegram_resilience import is_transient_telegram_error
    for status in (401, 403, 404, 409):
        assert not is_transient_telegram_error(SimpleNamespace(msg=f"Received unexpected {status} private"))
    for status in (429, 500, 502, 503, 504):
        assert is_transient_telegram_error(SimpleNamespace(msg=f"Received unexpected {status} private"))
    assert not is_transient_telegram_error(ValueError("invalid proxy config"))
