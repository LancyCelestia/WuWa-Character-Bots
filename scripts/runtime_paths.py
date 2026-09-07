"""Stable paths for maintenance commands.

The source tree is the AI workspace; mutable databases, media and plugin state
live in the sibling ``ChatBot_Runtime`` directory.  This module deliberately
reads only path settings from dotenv files and never prints their contents.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _dotenv_value(key: str) -> str:
    """Read one non-secret setting using the same .env then .env.prod order."""
    value = ""
    for filename in (".env", ".env.prod"):
        path = PROJECT_ROOT / filename
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, raw_value = line.split("=", 1)
            if name.strip() != key:
                continue
            value = raw_value.strip().strip('"').strip("'")
    return os.environ.get(key, value).strip()


def runtime_data_dir() -> Path:
    raw = _dotenv_value("BOT_RUNTIME_DATA_DIR") or "data"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def runtime_path(value: str | Path) -> Path:
    """Resolve data/... into the configured external runtime data directory."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    normalized = str(path).replace("\\", "/")
    data_root = runtime_data_dir()
    if normalized == "data":
        return data_root
    if normalized.startswith("data/"):
        return (data_root / normalized[5:]).resolve()
    return (PROJECT_ROOT / path).resolve()
