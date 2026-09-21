"""Real, copy-only inputs for autosync integration tests (no Git/Runtime/.env)."""

from __future__ import annotations

import shutil
from pathlib import Path

from conftest import _AUTOSYNC_STEPS as GENERATORS
from verify_hashes import TRACKED_FILES


def copy_autosync_repo(source: Path, destination: Path) -> Path:
    """Copy real scripts, guards and generator inputs, preserving test-file counts."""
    source = source.resolve()
    destination = destination.resolve()
    assert destination != source and not destination.is_relative_to(source)
    paths = {
        "tests/conftest.py",
        "tests/_autosync_fixture.py",
        "plugins/bot_unified_runtime/config.py",
        "plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py",
        "plugins/bot_unified_runtime/domains/chat_reply/runtime/aliases.py",
        *TRACKED_FILES,
        *(script for script, _ in GENERATORS),
        *(output for _, output in GENERATORS),
    }
    # doc_sync counts all test_*.py and template names, not just collected tests.
    for pattern in (
        "tests/test_*.py",
        "plugins/bot_unified_runtime/domains/render/card_render/templates/*.html",
    ):
        paths.update(path.relative_to(source).as_posix() for path in source.glob(pattern))
    for name in sorted(paths):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    return destination
