"""Real autosync integration in TEMP; source WIP must never be rewritten.

Keep all three generators, their --check gates, hash warnings and the actual
conftest session-start/terminal-summary hooks. Only the test repository moves.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import conftest
import pytest
from _autosync_fixture import GENERATORS, copy_autosync_repo
from conftest import REPO_ROOT, run_autosync

AUTO_FACTS = REPO_ROOT / "docs" / "auto-facts.md"
_CHILD_TIMEOUT = 300
_EXPECTED_ENV = "AUTOSYNC_TEST_EXPECTED"


@pytest.fixture(autouse=True)
def _assert_source_outputs_untouched() -> Iterator[None]:
    """Never restore WIP: fail even on same-byte rewrites of source outputs."""
    paths = [REPO_ROOT / output for _, output in GENERATORS]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    yield
    changed = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in paths
        if not path.is_file()
        or (path.read_bytes(), path.stat().st_mtime_ns) != before[path]
    ]
    assert not changed, f"autosync tests wrote source-repository outputs: {changed}"


def _run_generator(root: Path, script: str, flag: str) -> subprocess.CompletedProcess[str]:
    # 子进程被 PYTHONUTF8=1 钉成 UTF-8 输出，父进程就必须按 UTF-8 解码：
    # 不写 encoding 时 subprocess 用 locale(GBK) 解码中文报告 ⇒ reader 线程抛
    # UnicodeDecodeError ⇒ stdout/stderr 变 None ⇒ 本门假红（跑法要求
    # export PYTHONIOENCODING=utf-8，故每次真跑必现）。两端都钉死才与环境无关。
    return subprocess.run(
        [sys.executable, "-B", str(root / script), flag],
        cwd=root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "BOT_AUTOSYNC": "0"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def _check_generators(root: Path, *, drift: bool = False) -> None:
    for script, _ in GENERATORS:
        result = _run_generator(root, script, "--check")
        assert result.returncode == (1 if drift else 0), result.stdout + result.stderr


def _outputs(root: Path) -> dict[str, bytes]:
    return {output: (root / output).read_bytes() for _, output in GENERATORS}


@pytest.fixture
def autosync_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _assert_source_outputs_untouched: None,
) -> Path:
    root = copy_autosync_repo(REPO_ROOT, tmp_path / "repo")
    # Keep the real hook's warning/summary state local to the test as well.
    monkeypatch.setattr(conftest, "_hash_baseline_changed", [])
    monkeypatch.setattr(conftest, "_autosync_changed", [])
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setenv("PYTHONUTF8", "1")
    # Establish the mirror's own canonical bytes, never bless source WIP.
    for script, _ in GENERATORS:
        result = _run_generator(root, script, "--write")
        assert result.returncode == 0, result.stdout + result.stderr
    _check_generators(root)
    return root


def _flip_last_byte(data: bytes) -> bytes:
    assert data, "auto-facts.md 不应为空"
    return data[:-1] + bytes([data[-1] ^ 0x20])


def _tamper_outputs(root: Path) -> None:
    for name in ("docs/auto-facts.md", "docs/command-catalog.md"):
        path = root / name
        path.write_bytes(_flip_last_byte(path.read_bytes()))
    manifest = root / "tests/render_hashes.json"
    hashes = json.loads(manifest.read_text(encoding="utf-8"))
    hashes[next(iter(hashes))] = "0" * 64
    manifest.write_text(json.dumps(hashes), encoding="utf-8")


def test_autosync_enabled_repairs_tampered_auto_facts(
    autosync_repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _outputs(autosync_repo)
    _tamper_outputs(autosync_repo)
    _check_generators(autosync_repo, drift=True)
    monkeypatch.setenv("BOT_AUTOSYNC", "1")
    with pytest.warns(UserWarning, match="哈希基线被自动重录"):
        changed = run_autosync(root=autosync_repo)
    assert changed == [output for _, output in GENERATORS]
    assert _outputs(autosync_repo) == original
    _check_generators(autosync_repo)
    # Idempotence is measured on bytes/change reporting, not skipped execution.
    # The hook retains its warning list until session end, including no-op reruns.
    with pytest.warns(UserWarning, match="哈希基线被自动重录"):
        assert run_autosync(root=autosync_repo) == []
    assert _outputs(autosync_repo) == original


@pytest.mark.parametrize("setting", [None, "0"])
def test_autosync_disabled_leaves_drift_for_resident_gate(
    autosync_repo: Path, monkeypatch: pytest.MonkeyPatch, setting: str | None,
) -> None:
    if setting is None:
        monkeypatch.delenv("BOT_AUTOSYNC", raising=False)
    else:
        monkeypatch.setenv("BOT_AUTOSYNC", setting)
    _tamper_outputs(autosync_repo)
    tampered = _outputs(autosync_repo)
    mtimes = [(autosync_repo / name).stat().st_mtime_ns for name in tampered]
    assert run_autosync(root=autosync_repo) == []
    assert _outputs(autosync_repo) == tampered
    assert [(autosync_repo / name).stat().st_mtime_ns for name in tampered] == mtimes
    _check_generators(autosync_repo, drift=True)


def test_autosync_smoke() -> None:
    """Child test body proves all repairs precede tests, not session finish."""
    assert AUTO_FACTS.is_file() and AUTO_FACTS.stat().st_size > 0
    assert AUTO_FACTS.read_bytes().endswith(b"\n"), "session 开始时 autosync 未完成"
    if expected_path := os.environ.get(_EXPECTED_ENV):
        expected = json.loads(Path(expected_path).read_text(encoding="utf-8"))
        assert {
            name: hashlib.sha256(data).hexdigest() for name, data in _outputs(REPO_ROOT).items()
        } == expected, "三种生成器的修复必须先于测试体运行"
        _check_generators(REPO_ROOT)


def test_autosync_end_to_end_mini_session(autosync_repo: Path, tmp_path: Path) -> None:
    original = _outputs(autosync_repo)
    expected = tmp_path / "expected.json"
    expected.write_text(
        json.dumps({name: hashlib.sha256(data).hexdigest() for name, data in original.items()}),
        encoding="utf-8",
    )
    _tamper_outputs(autosync_repo)
    _check_generators(autosync_repo, drift=True)
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "tests/test_autosync_hook.py::test_autosync_smoke",
            "tests/test_cross_validation_gates.py",
            f"--basetemp={tmp_path / 'child'}",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        cwd=autosync_repo,
        env={
            **os.environ,
            "BOT_AUTOSYNC": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            _EXPECTED_ENV: str(expected),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_CHILD_TIMEOUT,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _outputs(autosync_repo) == original, "子会话 fixture 未把三种漂移修回"
    assert "[autosync] 自动同步：" in proc.stdout
    assert "[autosync] 哈希基线已自动重录" in proc.stdout
    for _, output in GENERATORS:
        assert output in proc.stdout, proc.stdout
    _check_generators(autosync_repo)
