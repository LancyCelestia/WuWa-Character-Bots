"""世界观术语表层：游戏世界观、专有名词、专有地名、科研词汇。

这些是角色说话时"必须知道的世界常识"，从本地术语文件读取后按预算
注入 prompt（优先于大段知识 chunk）。格式支持两种：

- ``**词条**：解释``（Markdown 加粗）
- ``词条：解释`` 或 ``词条|解释``（每行一条）

数据流：``GlossaryProvider.load -> GlossaryContext -> ContextBundle
-> build_chat_prompt 的"世界观与专有名词"分区``。术语表是可信的
运营知识，但解释文本仍按 untrusted 事实处理，防止注入。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from plugins.wuwa_unified_runtime.contracts.character import (
    GlossaryContext,
    GlossaryEntry,
)

_BOLD_ENTRY = re.compile(r"^\*{1,2}(.+?)\*{1,2}\s*[:：|]\s*(.+)$")
_PLAIN_ENTRY = re.compile(r"^([^\s:：|][^:：|\n]{0,60})\s*[:：|]\s*(.+)$")

DEFAULT_CATEGORIES: dict[str, str] = {}


class GlossaryProvider(Protocol):
    def load(self, request_id: str) -> GlossaryContext:
        """读取当前术语条目。"""


class NullGlossaryProvider:
    def load(self, request_id: str) -> GlossaryContext:
        return GlossaryContext(request_id=request_id, entries=[])


class FileGlossaryProvider:
    """从本地 Markdown/TXT 术语文件读取条目。"""

    def __init__(
        self,
        glossary_files: list[str | Path],
        *,
        max_entries: int = 30,
        max_chars: int = 1500,
    ) -> None:
        self.glossary_files = [Path(path).expanduser() for path in glossary_files]
        self.max_entries = max(0, int(max_entries))
        self.max_chars = max(0, int(max_chars))

    def load(self, request_id: str) -> GlossaryContext:
        entries: list[GlossaryEntry] = []
        total_chars = 0
        for path in self.glossary_files:
            if len(entries) >= self.max_entries:
                break
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            for raw_line in text.splitlines():
                if len(entries) >= self.max_entries:
                    break
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parsed = _parse_entry_line(line)
                if parsed is None:
                    continue
                term, explanation = parsed
                if not term or not explanation:
                    continue
                remaining = self.max_chars - total_chars
                if remaining <= 0:
                    break
                if len(explanation) > remaining:
                    explanation = f"{explanation[: max(1, remaining - 1)]}…"
                entries.append(
                    GlossaryEntry(
                        term=term,
                        explanation=explanation,
                        category="general",
                        source=path.stem,
                    )
                )
                total_chars += len(explanation)
        return GlossaryContext(request_id=request_id, entries=entries)


def _parse_entry_line(line: str) -> tuple[str, str] | None:
    bold = _BOLD_ENTRY.match(line)
    if bold:
        return bold.group(1).strip(), bold.group(2).strip()
    plain = _PLAIN_ENTRY.match(line)
    if plain:
        return plain.group(1).strip(), plain.group(2).strip()
    return None


def build_glossary_provider(config: object) -> GlossaryProvider:
    files = list(getattr(config, "wuwa_glossary_files", []) or [])
    if not files:
        return NullGlossaryProvider()
    return FileGlossaryProvider(
        glossary_files=files,
        max_entries=int(getattr(config, "wuwa_glossary_max_entries", 30)),
        max_chars=int(getattr(config, "wuwa_glossary_max_chars", 1500)),
    )
