"""bot 运行日志自持文件 sink（W1-② 证据链落盘）。

背景（09-29 代理链故障排查）：逐跳日志（``llm route hop failed`` 等 std
logging 经 nonebot 桥接到控制台 sink）只在控制台存在——日常
``scripts/dev.ps1 -Task run`` 裸跑不重定向，``bot_stdout/stderr.log`` 停在
09-27，故障窗口的证据随控制台蒸发。本模块给同一份日志并排装一枚**轮转
文件 sink**：与启动方式无关，控制台怎么起都能落盘。

fail-open 约束：目录不可判定 / sink 安装失败一律返回 None，绝不影响控制台
日志与 bot 启动本身。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

_SINK_ROTATION = "10 MB"
_SINK_RETENTION = 5


def resolve_runtime_logs_dir(data_dir_raw: str | Path | None) -> Path | None:
    """由运行数据目录推日志目录（``<runtime>/logs``），不可判定返回 None。

    只信绝对路径：相对值（源码树缺省 ``data`` 一类）会写进仓库/源码树，
    违反工作区零缓存零写入规矩——宁可不装 sink（fail-open），绝不落错地方。
    """
    raw = str(data_dir_raw or "").strip()
    if not raw:
        return None
    data_dir = Path(raw).expanduser()
    if not data_dir.is_absolute():
        return None
    return data_dir.parent / "logs"


def install_runtime_file_sink(
    sink_path: Path,
    *,
    log_filter: Callable[[Any], bool],
    log_format: str,
) -> int | None:
    """向 loguru 注册轮转文件 sink，返回 sink id（测试/卸载用）；失败 None。

    filter/format 与控制台 sink 同源（bot.py 传入 ``_rate_limited_log_filter``
    与 ``default_format``），保证文件与控制台看到同一份经过降噪的日志；
    enqueue=True 让 offload 线程写日志不阻塞事件循环。
    """
    try:
        from loguru import logger as _loguru

        return _loguru.add(
            str(sink_path),
            level=0,
            diagnose=False,
            filter=log_filter,
            format=log_format,
            rotation=_SINK_ROTATION,
            retention=_SINK_RETENTION,
            encoding="utf-8",
            enqueue=True,
        )
    except Exception:  # noqa: BLE001 - 证据链是加值件，绝不反噬启动。
        return None
