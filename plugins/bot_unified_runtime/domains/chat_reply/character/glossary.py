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

审查 O-06（2026-09-14）：注入从「每轮全量」改为「按关键词召回」——
recall_entries/recall_trend_notes 只返回术语名/别名命中本轮消息的条目
（≤RECALL_MAX_ENTRIES 条），零命中时分区整块不出现；召回为零但本轮
明确询问术语（is_term_question，question_intent 术语类）时由 chat 侧
回退全量防漏答。load 的加载上限语义不变。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.domains.chat_reply.runtime.question_intent import (
    classify_question_intent,
)
from plugins.bot_unified_runtime.domains.core.contracts.character import (
    GlossaryContext,
    GlossaryEntry,
    TrendNote,
)

_BOLD_ENTRY = re.compile(r"^\*{1,2}(.+?)\*{1,2}\s*[:：|]\s*(.+)$")
_PLAIN_ENTRY = re.compile(r"^([^\s:：|][^:：|\n]{0,60})\s*[:：|]\s*(.+)$")

DEFAULT_CATEGORIES: dict[str, str] = {}

# 随包种子术语表的**文件名**（S5 多人格隔离波 单元 1：路径不再带人格名）。
# 旧形态＝模块级常量把 ``personas/shorekeeper/`` 写死在代码里 ⇒ 切到备用人格后
# 装配层继续端**主人格**的世界观术语表（同一人格的语料跟着换、术语表不换，
# 台账 #66★「切人格要跟着换意象」的同型残留）。现在根由人格册现算。
SEED_GLOSSARY_FILENAME = "worldview_glossary.md"
_SEED_GLOSSARY_SUBDIR = ("knowledge",)


def seed_glossary_path(persona_id: str = "") -> Path | None:
    """按人格解析随包种子术语表落点；**没备料就申报缺席**（返回 None）。

    ``persona_id`` 空/``default`` ⇒ 归一到生效格（切换态 → 配置主人格档 →
    在册 is_main）。人格根取不到（册缺席、id 带穿越）同样返回 None，
    绝不拼出主人格的目录顶包。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        persona_asset_path,
    )

    return persona_asset_path(*_SEED_GLOSSARY_SUBDIR, SEED_GLOSSARY_FILENAME, persona_id=persona_id)


# 模块级缺省＝**主人格那格**的种子路径（派生值，非字面量路径）。
# 保留这个名字是两条既有通道的承重面：``control_plane/webui_knowledge.py`` 的
# 只读展示，以及 tests/test_glossary_seed.py 对"种子缺失优雅回退"的 monkeypatch
# 位（改这个名字会让那条离线锁红）。装配层请按 persona 现取（见
# :func:`build_glossary_provider`），本常量只当"没带人格信息时的缺省"。
SEED_GLOSSARY_PATH = seed_glossary_path() or (
    Path(__file__).resolve().parents[5] / "personas" / SEED_GLOSSARY_FILENAME
)
# 每轮注入条数硬上限（注入纪律：术语=背景知识，防 prompt 膨胀）。
# 字符级预算另由 bot_glossary_max_chars 与提示词分区预算双层兜底。
SEED_MAX_ENTRIES = 8

# ---------------------------------------------------------------------------
# 审查 O-06：按关键词召回——glossary/trend 每轮全量注入会随术语规模线性
# 膨胀 prompt，而大部分轮次根本用不上。召回口径：条目的术语名/别名
# （术语字段内的括号/分隔变体）归一后出现在本轮 current_message 中才注入；
# 每轮召回上限 RECALL_MAX_ENTRIES（≤8，对齐 SEED_MAX_ENTRIES 惯例）。
# 兜底：召回为零且本轮明确询问术语/概念（question_intent 术语类）时回退
# 全量防漏答——全量仍受 load 侧 SEED_MAX_ENTRIES / bot_glossary_max_entries
# 上限约束。召回只裁剪注入面，不改变 load 的加载语义。
# ---------------------------------------------------------------------------
RECALL_MAX_ENTRIES = 8


def normalize_glossary_text(text: str) -> str:
    """召回匹配归一：NFKC 折叠全角→半角 + casefold（对齐既有 normalize 口径）。

    中文主体不受 NFKC/casefold 影响；「ＵＰ池」与「up池」、「Rover」与
    「rover」归一后同键，避免大小写/全角书写差异漏召回。
    """
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


# 术语字段内的别名分隔：括号/方括号/各类斜杠、顿号、逗号、竖线、间隔号。
_TERM_ALIAS_SPLIT_RE = re.compile(r"[（）()\[\]【】「」『』/／、,，|｜·]+")


def _term_match_keys(term: str) -> tuple[str, ...]:
    """术语名 + 别名匹配键（去重保序）。

    例：「漂泊者（Rover）」→ ("漂泊者(rover)", "漂泊者", "rover")。
    纯 ASCII 单字符键太易误召回（任意句子都含某个字母），丢弃；
    单字 CJK 词条（如「椿」）字符本身足够特异，保留。
    """
    normalized = normalize_glossary_text(term).strip()
    if not normalized:
        return ()
    keys = [normalized]
    for part in _TERM_ALIAS_SPLIT_RE.split(normalized):
        part = part.strip()
        if not part:
            continue
        if len(part) < 2 and all(ord(ch) < 128 for ch in part):
            continue
        if part not in keys:
            keys.append(part)
    return tuple(keys)


def recall_entries(
    entries: list[GlossaryEntry],
    query_text: str,
    limit: int = RECALL_MAX_ENTRIES,
) -> list[GlossaryEntry]:
    """审查 O-06 核心接口：按关键词召回条目子集。

    命中条件=术语名/任一别名归一后是 query 归一文本的子串；
    保持原有条目顺序（=文件内注入优先级），最多返回 limit 条。
    """
    if limit <= 0:
        return []
    query = normalize_glossary_text(query_text)
    if not query:
        return []
    hits = [
        entry
        for entry in entries
        if any(key in query for key in _term_match_keys(entry.term))
    ]
    return hits[:limit]


def recall_trend_notes(
    notes: list[TrendNote],
    query_text: str,
    limit: int = RECALL_MAX_ENTRIES,
) -> list[TrendNote]:
    """审查 O-06 同型处理：时梗备注按 topic 关键词召回（口径与 recall_entries 一致）。

    topic 是时梗的"术语名"（note 是解释正文，不参与匹配，避免长句噪声）。
    """
    if limit <= 0:
        return []
    query = normalize_glossary_text(query_text)
    if not query:
        return []
    hits = [
        note
        for note in notes
        if any(key in query for key in _term_match_keys(note.topic))
    ]
    return hits[:limit]


# question_intent 术语类：世界观/本地知识域提问（LOCAL_KNOWLEDGE）与
# 静态概念释义提问（GENERAL_STATIC_KNOWLEDGE：什么是/含义/意思/定义…）。
# EXTERNAL_ENTITY 不入兜底——问域外实体时全量术语帮不上忙，只会白涨 prompt。
_TERM_QUESTION_CATEGORIES = frozenset({"LOCAL_KNOWLEDGE", "GENERAL_STATIC_KNOWLEDGE"})


def is_term_question(text: str) -> bool:
    """审查 O-06 兜底门：本轮是否明确在问术语/概念（question_intent 术语类）。

    召回为零但命中此门时，chat 注入侧回退全量（防漏答）。
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    decision = classify_question_intent(stripped)
    return decision.category in _TERM_QUESTION_CATEGORIES


class GlossaryProvider(Protocol):
    def load(self, request_id: str) -> GlossaryContext:
        """读取当前术语条目。"""

    def recall(self, query_text: str, limit: int = RECALL_MAX_ENTRIES) -> GlossaryContext:
        """审查 O-06：按关键词召回条目子集（query 命中术语名/别名才返回）。"""


class NullGlossaryProvider:
    def load(self, request_id: str) -> GlossaryContext:
        return GlossaryContext(request_id=request_id, entries=[])

    def recall(self, query_text: str, limit: int = RECALL_MAX_ENTRIES) -> GlossaryContext:
        return GlossaryContext(request_id="recall", entries=[])


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

    def recall(self, query_text: str, limit: int = RECALL_MAX_ENTRIES) -> GlossaryContext:
        """审查 O-06：load 后按关键词召回。

        chat 注入链路（capabilities/chat.py）直接对 ContextBundle 里的
        entries 用模块级 recall_entries（provider 不随 bundle 下发）；
        本方法供不经过 ContextBundle 的调用方使用。
        """
        loaded = self.load(request_id="recall")
        return loaded.model_copy(
            update={"entries": recall_entries(loaded.entries, query_text, limit=limit)}
        )


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
        # S5 单元 1：种子按**生效人格**现取——备用人格没备术语表时申报缺席
        # （空清单＝等价 NullGlossaryProvider），绝不端主人格的术语表给新人格。
        from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
            main_persona_id,
            resolve_persona_id,
        )

        persona_id = resolve_persona_id(config)
        if not persona_id or persona_id == main_persona_id():
            # 主人格档沿用模块缺省常量：那是 tests/test_glossary_seed.py
            # 「种子缺失优雅回退」的 monkeypatch 承重位，不许被派生值绕开。
            seed: Path | None = SEED_GLOSSARY_PATH
        else:
            seed = seed_glossary_path(persona_id)
        return FileGlossaryProvider(
            glossary_files=[seed] if seed else [],
            max_entries=SEED_MAX_ENTRIES,
            max_chars=int(getattr(config, "bot_glossary_max_chars", 1500)),
        )
    return FileGlossaryProvider(
        glossary_files=files,
        max_entries=int(getattr(config, "bot_glossary_max_entries", 30)),
        max_chars=int(getattr(config, "bot_glossary_max_chars", 1500)),
    )
