"""Guard: fail any test that creates new files under the source-tree data/.

Repo rules (AGENTS.md #2/#6): the source tree must never contain ``data/`` --
runtime paths resolve through ``scripts/runtime_paths.py`` into
``ChatBot_Runtime/`` and tests must write to ``tmp_path``.  Before and after
each of a test's setup/call/teardown phases we snapshot the repo ``data/``
directory; any file appearing mid-phase fails exactly that phase with the
list of offending paths.  Diagnostics are also appended to
``%TEMP%/g1-data-writes.log`` (outside the source tree).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

_REPO_DATA = Path(__file__).resolve().parents[1] / "data"
_LOG = Path(os.environ.get("TEMP", ".")) / "g1-data-writes.log"


def _snapshot() -> set[str]:
    if not _REPO_DATA.is_dir():
        return set()
    return {str(p.relative_to(_REPO_DATA)) for p in _REPO_DATA.rglob("*")}


def _log(node: str, phase: str, fresh: list[str]) -> None:
    stamp = time.strftime("%H:%M:%S")
    try:
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.writelines(f"{stamp}\t{node}\t{phase}\tNEW\t{name}\n" for name in fresh)
    except OSError:  # pragma: no cover - diagnostics must never break the run
        pass


def _enforce(node: str, phase: str, before: set[str], excinfo: object) -> None:
    """Fail the phase when new files appeared under the source-tree data/.

    ``excinfo`` is the pluggy hookwrapper result's ``excinfo``: non-None means
    the phase already failed for its own reason and we must not mask it.
    """
    fresh = sorted(_snapshot() - before)
    if not fresh:
        return
    _log(node, phase, fresh)
    if excinfo is not None:
        return
    listing = "\n".join(f"  data/{name}" for name in fresh)
    raise AssertionError(
        f"{node} wrote new file(s) into the source tree data/ during {phase}:\n"
        f"{listing}\n"
        "Write to tmp_path (or resolve via scripts/runtime_paths.py) instead; "
        "see AGENTS.md rules 2/6."
    )


def _make_phase_guard(phase: str):
    @pytest.hookimpl(hookwrapper=True)
    def impl(item: pytest.Item):
        before = _snapshot()
        outcome = yield
        _enforce(item.nodeid, phase, before, outcome.excinfo)

    return impl


pytest_runtest_setup = _make_phase_guard("setup")
pytest_runtest_call = _make_phase_guard("call")
pytest_runtest_teardown = _make_phase_guard("teardown")
