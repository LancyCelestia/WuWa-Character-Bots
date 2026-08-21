"""测试公共夹具。

把测试进程的工作目录固定到项目根，保证测试内部的相对路径
（scripts/dev.ps1、.env.example 等）无论从哪个目录启动 pytest
都能正确解析。测试内部再 monkeypatch.chdir() 会覆盖并在结束时
自动恢复。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _project_cwd():
    previous = Path.cwd()
    os.chdir(PROJECT_ROOT)
    try:
        yield
    finally:
        os.chdir(previous)
