"""Stable paths for maintenance commands.

The source tree is the AI workspace; mutable databases, media and plugin state
live in the sibling ``ChatBot_Runtime`` directory.  This module deliberately
reads only path settings from dotenv files and never prints their contents.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _strip_inline_comment(raw_value: str) -> str:
    """去掉 dotenv 行内注释（引号感知）：仅在未闭合引号外、且 ``#`` 前有空白时截断。

    与 python-dotenv 行为对齐：``data # 注释`` → ``data``；
    ``"a # b"`` 引号内的 # 不算注释；``a#b`` 无空白不算注释。
    """
    quote = ""
    for index, char in enumerate(raw_value):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and index > 0 and raw_value[index - 1] in " \t":
            return raw_value[:index].rstrip()
    return raw_value


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
            value = _strip_inline_comment(raw_value).strip().strip('"').strip("'")
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
    # 与 config.py 的路径解析器对齐：统一剥 ./ 前缀并对 data/ 前缀
    # 大小写不敏感重映射，两侧对 "./DATA/x"、"data/x" 得到同一结果。
    normalized = str(path).replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    data_root = runtime_data_dir()
    if normalized.lower() == "data":
        return data_root
    if normalized.lower().startswith("data/"):
        return (data_root / normalized[5:]).resolve()
    return (PROJECT_ROOT / path).resolve()
