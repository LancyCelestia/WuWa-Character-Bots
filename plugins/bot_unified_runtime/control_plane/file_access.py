"""受控文件读取与代码文件网关。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ALLOWED = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".tex",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cxx",
    ".cs",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
}


class FileGatewayError(Exception):
    pass


class FileReadGateway:
    def __init__(
        self, roots: tuple[str | Path, ...], max_bytes: int = 20 * 1024 * 1024
    ) -> None:
        self.roots = tuple(Path(x).resolve() for x in roots)
        self.max_bytes = max_bytes

    def resolve(self, relative: str) -> Path:
        if not relative or Path(relative).is_absolute():
            raise FileGatewayError("absolute_path_forbidden")
        candidate = Path(relative).resolve()
        if not any(
            candidate == root or root in candidate.parents for root in self.roots
        ):
            raise FileGatewayError("path_not_allowed")
        if candidate.suffix.lower() not in ALLOWED:
            raise FileGatewayError("format_not_supported")
        if not candidate.is_file() or candidate.stat().st_size > self.max_bytes:
            raise FileGatewayError("file_unavailable")
        return candidate

    def read(self, relative: str) -> dict[str, Any]:
        path = self.resolve(relative)
        suffix = path.suffix.lower()
        if suffix in {
            ".txt",
            ".md",
            ".markdown",
            ".rst",
            ".tex",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".cc",
            ".cxx",
            ".cs",
            ".py",
            ".js",
            ".ts",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".csv",
        }:
            return {
                "name": path.name,
                "format": suffix[1:],
                "text": path.read_text(encoding="utf-8", errors="replace"),
                "size": path.stat().st_size,
            }
        return {
            "name": path.name,
            "format": suffix[1:],
            "text": None,
            "status": "parser_required",
            "size": path.stat().st_size,
        }
