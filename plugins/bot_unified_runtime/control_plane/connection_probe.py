"""连接监测探针腿：**只测端口有人在听**，不冒充进程健康度。

病史（W12 2026-10-19）：控制台此前只测 OneBot WS 连接
（``runtime_state_probe`` 一个 bool），SnowLuma 进程健康度完全没测 ⇒ 学校号
（3014）掉线时整条连接被报"异常"，而主号 3011 其实好好的。

本模块只做件能被证明的事：对配置里的每个 SnowLuma 节点端口做一次 TCP
connect。端口不硬编码——默认取自 ``.env`` 已记在册的节点（3011 主号 /
3014 学校号），可经 ``BOT_SNOWLUMA_PROBE_PORTS`` 或 Config 同名键覆盖。

ponytail: 只探"有人在听"（SYN/ACK 成立），不探进程名/内存/QQ 登录态——
进程活着但掉线它答不出来。要那一层得走 SnowLuma 自己的 API，届时另立一条腿，
不要把这里改成猜。
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterable, Mapping

__all__ = [
    "DEFAULT_SNOWLUMA_PORTS",
    "probe_ports",
    "resolve_snowluma_ports",
]

# 生产在册节点：3011 主号 3865067623/3958874605 同节点、3014 学校号 2300230562。
# 只放"该有"的节点；3012/3013 是备用号，探它们会让"进程在跑"判成 False。
DEFAULT_SNOWLUMA_PORTS: tuple[int, ...] = (3011, 3014)

_CONNECT_TIMEOUT_SECONDS = 0.3

_ENV_KEY = "BOT_SNOWLUMA_PROBE_PORTS"
_CONFIG_KEY = "bot_snowluma_probe_ports"


def _coerce_ports(raw: object) -> tuple[int, ...] | None:
    """把 list / 逗号串归一成去重有序 tuple；一个合法端口都没有则 None。

    空值返回 None（＝没有覆盖），而不是空 tuple——空 tuple 会让
    ``snowluma_process`` 恒 True（all([]) 为真），是"装样子"。
    """
    if raw is None:
        return None
    items: Iterable[object]
    if isinstance(raw, (list, tuple, set, frozenset)):
        items = raw
    else:
        items = str(raw).replace(";", ",").split(",")
    ports: list[int] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        try:
            port = int(text)
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535 and port not in ports:
            ports.append(port)
    return tuple(ports) or None


def resolve_snowluma_ports(
    config: object | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[int, ...]:
    """端口来源优先级：Config 键 → 环境变量 → :data:`DEFAULT_SNOWLUMA_PORTS`。"""
    env = os.environ if environ is None else environ
    from_config = _coerce_ports(getattr(config, _CONFIG_KEY, None))
    if from_config:
        return from_config
    from_env = _coerce_ports(env.get(_ENV_KEY))
    if from_env:
        return from_env
    return DEFAULT_SNOWLUMA_PORTS


def probe_ports(
    ports: Iterable[int],
    *,
    host: str = "127.0.0.1",
    timeout: float = _CONNECT_TIMEOUT_SECONDS,
) -> dict[int, bool]:
    """逐口 TCP connect 探活。任何失败（含参数畸形）诚实降级 False，不抛。"""
    result: dict[int, bool] = {}
    for port in ports:
        result[port] = _is_listening(host, port, timeout)
    return result


def _is_listening(host: str, port: object, timeout: float) -> bool:
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
    except (OSError, TypeError, ValueError):
        return False
    else:
        sock.close()
        return True
