"""Verify that mutable runtime data stays outside the AI source workspace.

This is an offline structural check. It never opens database contents, calls an
LLM, connects to a platform, or prints secrets from dotenv files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from runtime_paths import PROJECT_ROOT, _dotenv_value, runtime_data_dir

RUNTIME_ROOT = PROJECT_ROOT.parent / "ChatBot_Runtime"


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _configured_list(key: str) -> list[Path]:
    raw = _dotenv_value(key)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in raw.split(";") if item.strip()]
    if not isinstance(parsed, list):
        return []
    return [Path(str(item)).expanduser() for item in parsed]


def _external_path(key: str) -> Path | None:
    raw = _dotenv_value(key)
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def main() -> int:
    errors: list[str] = []
    data_root = runtime_data_dir()
    if not data_root.is_dir():
        errors.append(f"runtime data directory missing: {data_root}")
    if _inside(data_root, PROJECT_ROOT):
        errors.append("BOT_RUNTIME_DATA_DIR points inside the AI source workspace")
    if not RUNTIME_ROOT.is_dir():
        errors.append(f"runtime root missing: {RUNTIME_ROOT}")

    for relative in ("knowledge_embeddings.sqlite3", "knowledge_faiss.index"):
        path = data_root / relative
        if not path.is_file():
            errors.append(f"required runtime file missing: {path}")

    if not _configured_list("BOT_PERSONA_FILES"):
        errors.append("BOT_PERSONA_FILES is empty")
    if not _configured_list("BOT_KNOWLEDGE_FILES"):
        errors.append("BOT_KNOWLEDGE_FILES is empty")
    for key in ("BOT_PERSONA_FILES", "BOT_KNOWLEDGE_FILES"):
        for path in _configured_list(key):
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if not path.is_file():
                errors.append(f"configured {key} file missing: {path.resolve()}")

    card_assets = _external_path("BOT_CARD_ASSET_DIR")
    if card_assets is None:
        card_assets = RUNTIME_ROOT / "card_render_assets"
    if not card_assets.is_dir() or not any(card_assets.rglob("*.svg")):
        errors.append(f"card SVG asset directory is missing or empty: {card_assets}")
    elif _inside(card_assets, PROJECT_ROOT):
        errors.append("card SVG assets unexpectedly live inside the AI source workspace")

    localstore_use_cwd = _dotenv_value("LOCALSTORE_USE_CWD").lower()
    if localstore_use_cwd == "true":
        errors.append("LOCALSTORE_USE_CWD=true would write third-party state into CWD")
    elif localstore_use_cwd not in {"false", "0", "no"}:
        errors.append("LOCALSTORE_USE_CWD must be explicitly false")
    for key in ("LOCALSTORE_CACHE_DIR", "LOCALSTORE_CONFIG_DIR", "LOCALSTORE_DATA_DIR"):
        path = _external_path(key)
        if path is None:
            errors.append(f"{key} is not configured")
        elif _inside(path, PROJECT_ROOT):
            errors.append(f"{key} points inside the AI source workspace: {path}")

    for relative in ("data", "cache", "config"):
        local_dir = PROJECT_ROOT / relative
        if local_dir.is_dir() and any(local_dir.rglob("*")):
            errors.append(f"source workspace contains generated/runtime files in {local_dir}")

    bytecode = list(PROJECT_ROOT.rglob("*.pyc")) + list(PROJECT_ROOT.rglob("*.pyo"))
    bytecode += [path for path in PROJECT_ROOT.rglob("__pycache__") if path.is_dir()]
    if bytecode:
        errors.append(f"source workspace contains {len(bytecode)} Python cache path(s)")

    if errors:
        print("runtime-layout: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("runtime-layout: PASS")
    print(f"source_workspace={PROJECT_ROOT}")
    print(f"runtime_root={RUNTIME_ROOT}")
    print(f"runtime_data={data_root}")
    print("external_databases=knowledge_embeddings.sqlite3, knowledge_faiss.index")
    print("localstore=external cache/config/data")
    print("source_generated_dirs=empty")
    print("python_bytecode=absent")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
