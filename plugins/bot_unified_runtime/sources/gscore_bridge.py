"""GsCore / gsuid-core 适配桥（参考 astrbot_plugin_gscore_adapter 实现）。

目标：把 GsCore 当作相邻的 AI/游戏服务接进统一运行时。桥接层只做
协议转换与连接维护，不决定权限、不绕过审查与审计：

- 入站：GsCore 下发的消息 → ``on_message`` 回调（转成 IncomingMessage
  再走统一流水线）。
- 出站：``SendRequest`` → GsCore ``MessageSend``（含 echo 回执关联）。
- 断线重连（5 秒间隔）、上报队列串行化、优雅关闭。

协议模型沿用 GsCore adapter 的 ``MessageReceive/MessageSend`` 字段
（msg_id/bot_self_id/user_type/group_id/user_id/content/echo）。

默认 ``DisabledGsCoreBridge``：未配置时所有操作安全降级，不影响
主链路；``websockets`` 未安装时同样降级（不需要时零依赖）。
"""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol


class GsCoreBridge(Protocol):
    def is_connected(self) -> bool:
        """是否已建立连接。"""

    def report_message(self, payload: dict[str, Any]) -> bool:
        """上报一条消息给 GsCore；断连时暂存，重连后补发。"""

    def send_message(self, payload: dict[str, Any]) -> bool:
        """向 GsCore 下发一条消息（MessageSend 结构）。"""

    def start(self) -> None:
        """启动连接（幂等）。"""

    def stop(self) -> None:
        """停止连接。"""


class DisabledGsCoreBridge:
    def __init__(self, reason: str = "disabled") -> None:
        self.reason = reason

    def is_connected(self) -> bool:
        return False

    def report_message(self, payload: dict[str, Any]) -> bool:
        return False

    def send_message(self, payload: dict[str, Any]) -> bool:
        return False

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


@dataclass(frozen=True)
class GsCoreConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    ws_token: str = ""
    max_retry: int = 5
    bot_id: str = "NoneBot2"
    bot_self_id: str = ""


def build_message_receive(
    *,
    bot_id: str = "NoneBot2",
    bot_self_id: str = "",
    msg_id: str = "",
    user_type: str = "group",
    group_id: str = "",
    user_id: str = "",
    user_pm: int = 6,
    content: list[dict[str, Any]] | None = None,
    sender: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 GsCore MessageReceive 上报包（协议字段见早柚协议文档）。"""
    payload: dict[str, Any] = {
        "bot_id": bot_id,
        "bot_self_id": bot_self_id,
        "msg_id": msg_id,
        "user_type": user_type,
        "user_id": user_id,
        "user_pm": user_pm,
        "content": content or [],
    }
    if group_id:
        payload["group_id"] = group_id
    if sender:
        payload["sender"] = sender
    return payload


def build_message_send(
    *,
    bot_id: str = "NoneBot2",
    bot_self_id: str = "",
    msg_id: str = "",
    target_type: str = "direct",
    target_id: str = "",
    content: list[dict[str, Any]] | None = None,
    echo: str = "",
) -> dict[str, Any]:
    """构造 GsCore MessageSend 下发包。"""
    payload: dict[str, Any] = {
        "bot_id": bot_id,
        "bot_self_id": bot_self_id,
        "msg_id": msg_id,
        "target_type": target_type,
        "target_id": target_id,
        "content": content or [],
    }
    if echo:
        payload["echo"] = echo
    return payload


def roles_to_user_pm(roles: list[str], user_type: str = "direct") -> int:
    """本项目角色 → GsCore user_pm（0 主人 / 1 超管 / 2 群主 / 3 群管 / 6 普通）。"""
    if "admin" in roles:
        return 1
    if user_type == "group":
        if "trusted" in roles or "enterprise" in roles:
            return 3
        return 6
    return 6


class WsGsCoreBridge:
    """基于 websockets 的 GsCore 连接桥（协议侧，不依赖任何平台库）。"""

    def __init__(
        self,
        config: GsCoreConfig,
        *,
        on_message: Any | None = None,
    ) -> None:
        self.config = config
        self.on_message = on_message
        self._ws: Any | None = None
        self._queue: list[dict[str, Any]] = []
        self._running = False
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    # ---- 连接状态 ----

    def is_connected(self) -> bool:
        try:
            from websockets.protocol import State
        except Exception:  # noqa: BLE001 - websockets 未安装按未连接处理。
            return False
        return self._ws is not None and getattr(self._ws, "state", None) is State.OPEN

    # ---- 入队（线程安全）----

    def report_message(self, payload: dict[str, Any]) -> bool:
        with self._lock:
            if not self._running:
                return False
            self._queue.append(payload)
            if len(self._queue) > 500:
                self._queue = self._queue[-500:]
        return True

    def send_message(self, payload: dict[str, Any]) -> bool:
        return self.report_message(payload)

    # ---- 生命周期 ----

    def start(self) -> None:
        if self._running:
            return
        try:
            import websockets  # noqa: F401
        except Exception:  # noqa: BLE001 - websockets 导入失败则静默停用桥接。
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._thread_main,
            name="gscore-bridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._close_ws(), self._loop)

    async def _close_ws(self) -> None:
        if self._ws is not None:
            with suppress(Exception):
                await self._ws.close()
            self._ws = None

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run())
        finally:
            self._loop.close()
            self._loop = None

    async def _run(self) -> None:
        retry = 0
        while self._running:
            try:
                await self._connect_and_serve()
                retry = 0
            except Exception:  # noqa: BLE001 - 连接异常按重试策略处理。
                retry += 1
                if self.config.max_retry > 0 and retry >= self.config.max_retry:
                    self._running = False
                    return
            await asyncio.sleep(5)

    async def _connect_and_serve(self) -> None:
        from websockets.asyncio.client import connect as ws_connect

        # 早柚协议：ws://{HOST}:{PORT}/{BOT_ID}?token={WS_TOKEN}
        # token 在 URL 查询参数中（本机部署可留空）；注意路由 bot_id
        # 是平台名（NoneBot2），与包内 bot_id（聊天平台 id）区分。
        route_bot_id = self.config.bot_id or "NoneBot2"
        uri = f"ws://{self.config.host}:{self.config.port}/{route_bot_id}"
        if self.config.ws_token:
            from urllib.parse import quote

            uri = f"{uri}?token={quote(self.config.ws_token)}"
        async with ws_connect(
            uri,
            open_timeout=10,
        ) as ws:
            self._ws = ws
            await self._flush_queue(ws)
            await self._receive_loop(ws)

    async def _flush_queue(self, ws: Any) -> None:
        with self._lock:
            pending = list(self._queue)
            self._queue = []
        for payload in pending:
            with suppress(Exception):
                await ws.send(json.dumps(payload, ensure_ascii=False))

    async def _receive_loop(self, ws: Any) -> None:
        async for raw in ws:
            try:
                payload = json.loads(raw)
            except ValueError:
                continue
            if callable(self.on_message):
                with suppress(Exception):
                    result = self.on_message(payload)
                    if asyncio.iscoroutine(result):
                        await result


def build_gscore_bridge(
    config: object,
    *,
    on_message: Any | None = None,
) -> GsCoreBridge:
    enabled = bool(getattr(config, "bot_gscore_enabled", False))
    if not enabled:
        return DisabledGsCoreBridge(reason="disabled")
    try:
        import websockets  # noqa: F401
    except Exception:  # noqa: BLE001 - websockets 不可用时返回禁用桥。
        return DisabledGsCoreBridge(reason="websockets_not_installed")
    host = str(getattr(config, "bot_gscore_host", "127.0.0.1")).strip()
    port = int(getattr(config, "bot_gscore_port", 8765))
    token = str(getattr(config, "bot_gscore_ws_token", "")).strip()
    if not host or port <= 0:
        return DisabledGsCoreBridge(reason="invalid_endpoint")
    return WsGsCoreBridge(
        GsCoreConfig(
            enabled=True,
            host=host,
            port=port,
            ws_token=token,
            max_retry=int(getattr(config, "bot_gscore_max_retry", 5)),
            bot_id=str(getattr(config, "bot_gscore_bot_id", "Bot")),
            bot_self_id=str(getattr(config, "bot_gscore_bot_self_id", "")),
        ),
        on_message=on_message,
    )


def gscore_readiness(config: object) -> dict[str, Any]:
    """只读就绪检查：不建立真实连接，输出安全字段。"""
    enabled = bool(getattr(config, "bot_gscore_enabled", False))
    websockets_ok = True
    try:
        import websockets  # noqa: F401
    except Exception:  # noqa: BLE001 - 导入失败仅标记不可用。
        websockets_ok = False
    host = str(getattr(config, "bot_gscore_host", "127.0.0.1")).strip()
    port = int(getattr(config, "bot_gscore_port", 8765))
    token_set = bool(str(getattr(config, "bot_gscore_ws_token", "")).strip())
    return {
        "enabled": enabled,
        "websockets_available": websockets_ok,
        "host": host if enabled else "",
        "port": port if enabled else 0,
        "ws_token_set": token_set,
        "status": (
            "ready"
            if enabled and websockets_ok and host and port > 0
            else "disabled"
        ),
    }


if __name__ == "__main__":
    # 本地 smoke：python -m plugins.bot_unified_runtime.sources.gscore_bridge
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined, union-attr]
        except (AttributeError, OSError):
            pass
    import argparse

    from plugins.bot_unified_runtime.smoke import load_smoke_config

    parser = argparse.ArgumentParser(description="GsCore 适配桥就绪检查（只读，不联网连接）")
    parser.add_argument("--env", default=None)
    args = parser.parse_args()
    try:
        config = load_smoke_config(args.env)
    except Exception as exc:  # noqa: BLE001 - 配置加载失败统一报错退出。
        print(f"config_error={exc}")
        raise SystemExit(2)
    readiness = gscore_readiness(config)
    for key, value in readiness.items():
        print(f"gscore_{key}={value}")
    raise SystemExit(0 if readiness["status"] in {"ready", "disabled"} else 1)
