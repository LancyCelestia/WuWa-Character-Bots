"""crash_trap 离线回归（v21r2 R8）。

覆盖：幂等安装、心跳落盘与覆写、标记追加、优雅停止、僵尸心跳清理、
faulthandler 兜底启用。全离线，只写 tmp_path。
"""

from __future__ import annotations

import faulthandler
import os
import re
import time
from pathlib import Path

import pytest

from scripts.crash_trap import _HEARTBEAT_PREFIX, install


@pytest.fixture(autouse=True)
def _cleanup_singleton():
    yield
    from scripts import crash_trap

    if crash_trap._ACTIVE is not None:
        crash_trap._ACTIVE.stop()


def test_install_creates_heartbeat_and_marker(tmp_path: Path) -> None:
    trap = install(tmp_path, beat_seconds=0.05, source="test")
    assert trap.heartbeat_path.exists()
    assert trap.markers_path.exists()
    hb = trap.heartbeat_path.read_text(encoding="utf-8")
    assert f"pid={os.getpid()}" in hb
    assert "src=test" in hb
    assert any("stage=install" in line for line in trap.markers_path.read_text(encoding="utf-8").splitlines())


def test_install_idempotent_returns_singleton(tmp_path: Path) -> None:
    first = install(tmp_path, beat_seconds=0.05)
    second = install(tmp_path, beat_seconds=99)
    assert first is second


def test_heartbeat_rewrites_in_place(tmp_path: Path) -> None:
    trap = install(tmp_path, beat_seconds=0.05, source="beat")
    first = trap.heartbeat_path.read_text(encoding="utf-8")
    time.sleep(0.25)
    second = trap.heartbeat_path.read_text(encoding="utf-8")
    mono_first = float(re.search(r"mono=([0-9.]+)", first).group(1))  # type: ignore[union-attr]
    mono_second = float(re.search(r"mono=([0-9.]+)", second).group(1))  # type: ignore[union-attr]
    assert mono_second > mono_first
    # 覆写语义：单行、不增长。
    assert len(second.strip().splitlines()) == 1


def test_mark_appends_stage_lines(tmp_path: Path) -> None:
    trap = install(tmp_path, beat_seconds=0.05)
    trap.mark("before_risky_step")
    trap.mark("after_risky_step")
    lines = trap.markers_path.read_text(encoding="utf-8").splitlines()
    stages = [line for line in lines if "stage=" in line]
    assert any("stage=before_risky_step" in line for line in stages)
    assert any("stage=after_risky_step" in line for line in stages)


def test_stop_stops_thread_and_marks(tmp_path: Path) -> None:
    trap = install(tmp_path, beat_seconds=0.05)
    thread = trap._thread
    assert thread is not None and thread.is_alive()
    trap.stop()
    assert not thread.is_alive()
    assert any("stage=trap_stop" in line for line in trap.markers_path.read_text(encoding="utf-8").splitlines())


def test_stale_heartbeat_swept_on_install(tmp_path: Path) -> None:
    stale = tmp_path / f"{_HEARTBEAT_PREFIX}999999.log"
    stale.write_text("hb ts=dead\n", encoding="utf-8")
    ancient = time.time() - 25 * 3600
    os.utime(stale, (ancient, ancient))
    fresh = tmp_path / f"{_HEARTBEAT_PREFIX}{os.getpid() + 7777}.log"
    fresh.write_text("hb ts=alive\n", encoding="utf-8")
    install(tmp_path, beat_seconds=0.05)
    assert not stale.exists()
    assert fresh.exists()  # 新鲜的他者心跳（可能还活着）不误删。


def test_faulthandler_briefly_enabled(tmp_path: Path) -> None:
    was_enabled = faulthandler.is_enabled()
    install(tmp_path, beat_seconds=0.05)
    if not was_enabled:
        assert faulthandler.is_enabled()
    # 已启用环境（dev.ps1 -X faulthandler）下不重复启用也不报错。
