"""Lock the source-tree ``data/`` guard (tests/conftest.py) — AGENTS.md #1.

Two layers:
1. Repo tripwire: the source tree must not contain ``data/``.  The per-test
   guard in conftest.py attributes *which* test created it; this test fails
   fast even when the residue predates the guarded phases.
2. Unit tests for the guard's snapshot/enforce/log logic (no nested pytest).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "g1_data_guard", Path(__file__).with_name("conftest.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_tree_has_no_data_dir() -> None:
    assert not (_REPO_ROOT / "data").exists(), (
        "source-tree data/ exists; find the writer with the conftest guard "
        "(see %TEMP%/g1-data-writes.log) and port it to tmp_path"
    )


def test_snapshot_empty_when_dir_missing(tmp_path: Path) -> None:
    guard = _load_guard()
    guard._REPO_DATA = tmp_path / "absent"  # type: ignore[attr-defined]
    assert guard._snapshot() == set()


def test_enforce_raises_on_new_file(tmp_path: Path) -> None:
    guard = _load_guard()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    guard._REPO_DATA = data_dir  # type: ignore[attr-defined]
    before = guard._snapshot()
    (data_dir / "stray.sqlite").write_bytes(b"x")
    with pytest.raises(AssertionError, match=r"stray\.sqlite"):
        guard._enforce("node::id", "call", before, None)


def test_enforce_noop_without_new_files(tmp_path: Path) -> None:
    guard = _load_guard()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    guard._REPO_DATA = data_dir  # type: ignore[attr-defined]
    (data_dir / "preexisting.sqlite").write_bytes(b"x")  # 既有残留不属新增
    log = tmp_path / "guard.log"
    guard._LOG = log  # type: ignore[attr-defined]
    before = guard._snapshot()
    assert before == {"preexisting.sqlite"}, "_snapshot 应把目录内既有文件全量入集"
    # Must not raise when nothing new appeared (pre-existing files don't count).
    guard._enforce("node::id", "call", before, None)
    assert not log.exists(), "无违规时不得写守卫日志——_enforce noop 须零副作用"


def test_enforce_does_not_mask_existing_failure(tmp_path: Path) -> None:
    guard = _load_guard()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    guard._REPO_DATA = data_dir  # type: ignore[attr-defined]
    log = tmp_path / "guard.log"
    guard._LOG = log  # type: ignore[attr-defined]
    before = guard._snapshot()
    (data_dir / "late.sqlite").write_bytes(b"x")
    fake_excinfo = (ValueError, ValueError("boom"), None)
    # No raise: the phase already failed for its own reason.
    guard._enforce("node::id", "teardown", before, fake_excinfo)
    body = log.read_text(encoding="utf-8")
    assert "late.sqlite" in body
    assert "teardown" in body
    assert "node::id" in body
