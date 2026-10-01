"""bot_log_sink 单元回归（W1-② 证据链落盘）。

- 目录解析：只信绝对路径（相对值会落源码树，拒绝并返回 None）；
- 文件 sink：写入、过滤与控制台同源、enqueue 异步落盘；
- 失败面：非法路径安装返回 None（fail-open，绝不反噬启动）。
全部离线（tmp_path），sink 用毕即卸，不污染其他用例的 loguru 全局状态。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from loguru import logger as _loguru

from scripts.bot_log_sink import install_runtime_file_sink, resolve_runtime_logs_dir


@pytest.mark.parametrize(
    ("raw", "expected_name"),
    [
        ("C:/rt/data", "logs"),
        (Path("C:/rt/data"), "logs"),
        (None, None),
        ("", None),
        ("   ", None),
        ("relative/data", None),
    ],
)
def test_resolve_runtime_logs_dir(raw: Any, expected_name: str | None) -> None:
    got = resolve_runtime_logs_dir(raw)
    if expected_name is None:
        assert got is None
    else:
        assert got == Path("C:/rt") / expected_name
        assert got.is_absolute()


def test_install_runtime_file_sink_writes_and_filters(tmp_path: Path) -> None:
    """写入落盘 + 过滤与控制台同源（noise 行不进文件）。"""
    sink_file = tmp_path / "bot_runtime.log"

    def _filter(record: dict[str, Any]) -> bool:
        return "noise-line" not in str(record.get("message", ""))

    sink_id = install_runtime_file_sink(
        sink_file, log_filter=_filter, log_format="{message}\n"
    )
    try:
        assert sink_id is not None
        _loguru.info("chain-evidence-line")
        _loguru.info("noise-line")
        _loguru.complete()
        content = sink_file.read_text(encoding="utf-8")
        assert "chain-evidence-line" in content
        assert "noise-line" not in content
    finally:
        if sink_id is not None:
            _loguru.remove(sink_id)


def test_install_runtime_file_sink_fail_open(tmp_path: Path) -> None:
    """非法 sink 路径（目录冲突）安装失败返回 None，绝不抛异常。"""
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("occupy", encoding="utf-8")
    # 把「文件」当目录用：loguru add 必失败，函数须吞掉并返回 None。
    assert (
        install_runtime_file_sink(
            blocked / "bot_runtime.log",
            log_filter=lambda _: True,
            log_format="{message}\n",
        )
        is None
    )
