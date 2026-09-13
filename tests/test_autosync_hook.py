"""BOT_AUTOSYNC 常驻自动同步钩子的回归（钩子本体在 tests/conftest.py 顶部段）。

四个断言面：
1. 钩子开启（BOT_AUTOSYNC=1）：篡改 docs/auto-facts.md 一个字符后
   run_autosync 把它修回原字节，且 doc_sync --check 恢复绿；
2. 钩子关闭（未设 BOT_AUTOSYNC）：run_autosync 零动作，漂移保留——
   交由常驻门 tests/test_cross_validation_gates.py 报红；
3. 端到端：子进程 mini pytest 会话里 session 级 fixture 真实触发，
   篡改被自动修复，且 session 结束打印 [autosync] 汇总行；
4. 每个用例篡改的字节均在 finally 恢复，绝不污染工作区。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT, run_autosync

AUTO_FACTS = REPO_ROOT / "docs" / "auto-facts.md"
_CHILD_TIMEOUT = 300


def _flip_last_byte(data: bytes) -> bytes:
    """翻最后一字节（auto-facts.md 恒以 LF 结尾，0x0A^0x20=0x2A，保持 ASCII 合法）。"""
    assert data, "auto-facts.md 不应为空"
    return data[:-1] + bytes([data[-1] ^ 0x20])


def test_autosync_enabled_repairs_tampered_auto_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_AUTOSYNC", "1")
    original = AUTO_FACTS.read_bytes()
    try:
        AUTO_FACTS.write_bytes(_flip_last_byte(original))
        changed = run_autosync()
        assert "docs/auto-facts.md" in changed
        assert AUTO_FACTS.read_bytes() == original
        check = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "doc_sync.py"), "--check"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert check.returncode == 0, check.stdout + check.stderr
    finally:
        AUTO_FACTS.write_bytes(original)


def test_autosync_disabled_leaves_drift_for_resident_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_AUTOSYNC", raising=False)
    original = AUTO_FACTS.read_bytes()
    try:
        tampered = _flip_last_byte(original)
        AUTO_FACTS.write_bytes(tampered)
        assert run_autosync() == []
        assert AUTO_FACTS.read_bytes() == tampered
    finally:
        AUTO_FACTS.write_bytes(original)


def test_autosync_smoke() -> None:
    """端到端用例的子进程落点：本体恒真，钩子行为由 mini 会话的 fixture 完成。"""


def test_autosync_end_to_end_mini_session(tmp_path: Path) -> None:
    original = AUTO_FACTS.read_bytes()
    try:
        AUTO_FACTS.write_bytes(_flip_last_byte(original))
        env = dict(os.environ)
        env["BOT_AUTOSYNC"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_autosync_hook.py::test_autosync_smoke",
                f"--basetemp={tmp_path / 'child'}",
                "-p",
                "no:cacheprovider",
                "-q",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=_CHILD_TIMEOUT,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert AUTO_FACTS.read_bytes() == original, "子会话 fixture 未把篡改修回"
        assert "[autosync]" in proc.stdout, "session 结束未打印 [autosync] 汇总行"
    finally:
        AUTO_FACTS.write_bytes(original)
