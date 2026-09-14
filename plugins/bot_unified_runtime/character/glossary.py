"""世界观术语表层：游戏世界观、专有名词、专有地名、科研词汇。

这些是角色说话时"必须知道的世界常识"，从本地术语文件读取后按预算
注入 prompt（优先于大段知识 chunk）。格式支持两种：

- ``**词条**：解释``（Markdown 加粗）
- ``词条：解释`` 或 ``词条|解释``（每行一条）

数据流：``GlossaryProvider.load -> GlossaryContext -> ContextBundle
-> build_chat_prompt 的"世界观与专有名词"分区``。术语表是可信的
运营知识，但解释文本仍按 untrusted 事实处理，防止注入。

审查 O-02/O-03（2026-09-14）：术语表机制在但默认空转——config 默认
``bot_glossary_files=[]`` 且生产 .env 显式置空（env 覆盖使 config 默认值
改法无效），鸣潮名词在术语层零命中。故装配层增加**随包种子回退**：
空配置时加载 personas/shorekeeper/knowledge/worldview_glossary.md；
种子文件缺失/不可读时 load 逐文件静默跳过，等价 NullGlossaryProvider
空转路径保留。注入纪律（项目红线）：术语=背景知识，只作理解辅助、
禁止复读——包裹文案由 chat 侧运行时上下文总说明统一负责；每轮注入
条数由 SEED_MAX_ENTRIES 硬上限（≤8 条）防 prompt 膨胀。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.contracts.character import (
    GlossaryContext,
    GlossaryEntry,
)

_BOLD_ENTRY = re.compile(r"^\*{1,2}(.+?)\*{1,2}\s*[:：|]\s*(.+)$")
_PLAIN_ENTRY = re.compile(r"^([^\s:：|][^:：|\n]{0,60})\s*[:：|]\s*(.+)$")

DEFAULT_CATEGORIES: dict[str, str] = {}

# 随包种子术语表（审查 O-02/O-03 激活数据）：仓库根 personas/ 下，与
# 守岸人_核心知识.md 同目录。glossary.py 位于仓库根下第 3 层
# （plugins/bot_unified_runtime/character/），向上三级即仓库根；
# 若插件被装到别处导致种子不存在，load 会优雅回退为空上下文。
SEED_GLOSSARY_PATH = (
    Path(__file__).resolve().parents[3]
    / "personas"
    / "shorekeeper"
    / "knowledge"
    / "worldview_glossary.md"
)
# 每轮注入条数硬上限（注入纪律：术语=背景知识，防 prompt 膨胀）。
# 字符级预算另由 bot_glossary_max_chars 与提示词分区预算双层兜底。
SEED_MAX_ENTRIES = 8


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
    files = list(getattr(config, "bot_glossary_files", []) or [])
    if not files:
        # 审查 O-02/O-03：默认空配置回退随包种子，让默认部署不再空转；
        # 种子缺失/不可读时 FileGlossaryProvider.load 逐文件静默跳过，
        # 返回空 GlossaryContext，等价 NullGlossaryProvider（不抛异常）。
        return FileGlossaryProvider(
            glossary_files=[SEED_GLOSSARY_PATH],
            max_entries=SEED_MAX_ENTRIES,
            max_chars=int(getattr(config, "bot_glossary_max_chars", 1500)),
        )
    return FileGlossaryProvider(
        glossary_files=files,
        max_entries=int(getattr(config, "bot_glossary_max_entries", 30)),
        max_chars=int(getattr(config, "bot_glossary_max_chars", 1500)),
    )
