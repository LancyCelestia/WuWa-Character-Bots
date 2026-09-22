"""S187 static-hygiene snapshot lock (2026-09-22 unify/taxonomy wave).

Turns two one-off measured truths into a *live* gate, per S187 brief:

    full-tree ruff I001 == 0  AND  source-tree cache-class products == 0

Design rules honoured:
* Only locks, never loosens: no skip/xfail, no narrowing of the scan face, no
  baseline ceiling. The assertions are absolute.
* Data sources are the project's own tooling -- ruff CLI (``--select I001``) for
  import-sort and an ``os.walk`` of the repository tree for cache products --
  so the gate cannot be satisfied by a hand-maintained number.
* The ruff subprocess writes its cache OUTSIDE the tree (``--cache-dir``), so
  running this gate never itself creates ``.ruff_cache`` -- otherwise it would
  break its own "cache == 0" assertion.

The gate deliberately does NOT assert on other ruff rules (e.g. UP036): S187
owns only the import-sort block; non-import findings belong to their file owners.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}

# I001 line in ruff concise output looks like: ``path:1:1: I001 [*] Import block ...``
_I001_LINE = re.compile(r":\s*I001\b")


def _run_ruff_select_i001() -> list[str]:
    """Return concise-output lines that carry an I001 code, across the whole tree."""
    # Keep ruff's own cache out of the source tree (rule: source tree stays cache-free).
    scratch_cache = os.path.join(
        os.environ.get("TEMP") or tempfile.gettempdir(),
        "qoder-s187-hygiene-ruff-cache",
    )
    os.makedirs(scratch_cache, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--cache-dir",
            scratch_cache,
            "--select",
            "I001",
            "--output-format",
            "concise",
            ".",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return [ln for ln in out.splitlines() if _I001_LINE.search(ln)]


def _scan_tree_cache_products() -> list[str]:
    """Return repo-relative paths of cache-class products found in the source tree."""
    offenders: list[str] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT, onerror=lambda _e: None):
        # Never descend into the VCS database.
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in list(dirnames):
            if name in CACHE_DIR_NAMES:
                offenders.append(os.path.relpath(Path(dirpath) / name, REPO_ROOT) + "/")
                dirnames.remove(name)  # prune: a flagged cache dir needs no deeper walk
        for fname in filenames:
            if fname.endswith(".pyc"):
                offenders.append(os.path.relpath(Path(dirpath) / fname, REPO_ROOT))
    # A source-tree ``data/`` residue is the classic leak (issue-ledger #1); it is
    # cache/write-class and must not live inside the repo.
    if (REPO_ROOT / "data").is_dir():
        offenders.append("data/")
    return offenders


def test_full_tree_import_sort_is_clean():
    violations = _run_ruff_select_i001()
    assert violations == [], (
        "S187 snapshot lock: source tree has un-sorted import blocks (ruff I001). "
        "Run `ruff check --select I001 --fix <file>` on each. Offenders:\n"
        + "\n".join(violations)
    )


def test_source_tree_has_no_cache_products():
    offenders = _scan_tree_cache_products()
    assert offenders == [], (
        "S187 snapshot lock: cache-class products present in the source tree. "
        "Delete __pycache__/*.pyc/.pytest_cache/.ruff_cache/.mypy_cache/data (back up "
        "any non-cache data first). Offenders:\n" + "\n".join(sorted(set(offenders)))
    )
