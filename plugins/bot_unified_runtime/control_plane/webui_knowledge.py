"""WebUI 知识目录只读服务（knowledge/collections、knowledge/terms）。

数据源与口径（全部只读，URI mode=ro + PRAGMA query_only，绝不写生产库）：

- ``community_terms`` ← 世界观术语表文件（``bot_glossary_files``，空配置回退
  personas 种子 ``worldview_glossary.md``）。解析与
  ``FileGlossaryProvider`` 同规（同一 ``_parse_entry_line`` /
  别名切分常量），但不做注入预算截断——目录面必须给全量词条。
  词条=term/aliases/definition/scope/source，q 按 term/alias 归一子串过滤。
- ``kb_docs`` ← 向量知识库 SQLite（``bot_knowledge_db_path`` 人格库 +
  ``bot_kb_wiki_db_path`` Crawl Wiki 库，两处台账并集）：
  ``knowledge_chunks`` 按 source_id 聚合 chunk 数，并集 ``knowledge_docs``
  外部文档台账；文档级时间取台账 ``source_updated_at``（上游编辑时间）→
  缺失退 ``crawl_at``（本地抓取落盘时间）→ 两者皆无才 null（不造时间戳）。
  另透出 kb-sync 最近一轮摘要（``knowledge_meta['kb_sync_last_summary']``：
  上次同步时间/成败/新增条数/耗时），无记录=如实 ``sync: null``。
  检索面不在此重复造——复用既有 platform API
  ``/api/v1/knowledge-bases/{id}/search``。
- ``meme_tags`` ← 表情库 SQLite（``bot_meme_library_db_path``）：
  ``memes.emotion_tags``/``scene_tags`` JSON 标签聚合 counts；坏 JSON 行
  跳过不炸（聚合可得部分即报部分）。
- ``acg_sources`` ← 配置态（``bot_search_acg_*`` 开关），未启用=如实
  ``enabled:false``；读外部检索源本身超出本服务职责。
- 用户点名但项目内无独立库的集合（B站网络热门梗/战双词条库）：
  collections 里如实 not_available（enabled:false + 固定 reason），
  terms 对其返回 source_unavailable/collection_not_available，绝不假造。

失败面沿用 webui_stats 先例：``{status, reason, data: None}``，固定
reason 代码，绝不回显路径/SQL/原文；无效参数先于任何 IO 校验。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .factory import _path

__all__ = [
    "KnowledgeCatalogService",
    "build_default_knowledge_service",
]

_BUSY_TIMEOUT_SECONDS = 0.2
_QUERY_TIMEOUT_SECONDS = 1.0
_MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 20
_MAX_QUERY_CHARS = 200

_KB_REQUIRED_TABLES = frozenset({"knowledge_chunks", "knowledge_docs"})
_KB_CHUNK_COLUMNS = frozenset({"chunk_id", "source_id", "title"})
_KB_DOC_COLUMNS = frozenset({"doc_id", "topic", "title"})
# 文档级时间元数据列（kb-sync 侧 schema 迁移产物；存量库未迁移时缺列 → 该文档
# 如实报 null，本服务是只读面，绝不 ALTER 生产库）。
_KB_DOC_TIME_COLUMNS = frozenset({"source_updated_at", "crawl_at"})
# kb-sync 每轮摘要落库键（真相源=domains/location/knowledge/kb_wiki.SYNC_SUMMARY_META_KEY）。
# 这里重复字面量而不是 import 那个模块：控制面只读一个字符串键，不该在读取路径上
# 把 vector_knowledge（faiss/httpx）整条依赖拉进进程；两处常量的同一性由
# tests/test_kb_wiki_metadata_sync.py 的一致性锁兜住，改一处必红。
_KB_SYNC_SUMMARY_KEY = "kb_sync_last_summary"
# 摘要透出白名单：只报观测数值与状态码，public_message 一类自由文本不外泄
# （其中可能含导出目录路径，出站打码在控制面 JSON 这条路上并不经过）。
_KB_SYNC_PUBLIC_FIELDS = (
    "started_at",
    "finished_at",
    "mode",
    "ok",
    "error_kind",
    "duration_ms",
    "added",
    "changed",
    "removed",
    "skipped",
    "embedded",
    "ann_rebuilt",
    "documents_after",
    "chunks_after",
    "embedded_after",
    "reconcile_status",
    "reconcile_missing",
    "reconcile_extra",
    "reconcile_held",
    "metadata_status",
    # 同步判据依据（S2 有界窗口探针产出，2026-09-20 精确移交补登）：本轮探针
    # 扫描行数与其中带时间字段行数——「刷不刷元数据」的机器证据，纯观测数值。
    "metadata_probed",
    "metadata_with_time",
    "metadata_refreshed",
    "generated_at",
    "documents_total",
)
_MEME_REQUIRED_COLUMNS = frozenset({"md5", "emotion_tags", "scene_tags"})

_REAL_COLLECTIONS = ("community_terms", "kb_docs", "meme_tags", "acg_sources")

# 用户点名但项目内无独立库的集合：如实 not_available（绝不假造条目）。
_NOT_AVAILABLE_COLLECTIONS: tuple[dict[str, str], ...] = (
    {
        "id": "bili_hot_memes",
        "name": "B站网络热门梗",
        "description": "B站热门梗词条库（项目内暂无独立存储）",
    },
    {
        "id": "pgr",
        "name": "战双帕弥什词条库",
        "description": "战双帕弥什世界观词条库（项目内暂无独立存储）",
    },
)
_NOT_AVAILABLE_REASON = "no_dedicated_store"
_NOT_AVAILABLE_IDS = frozenset(entry["id"] for entry in _NOT_AVAILABLE_COLLECTIONS)

_ACG_SOURCE_NAMES: dict[str, str] = {
    "bangumi": "Bangumi 条目检索",
    "moegirl": "萌娘百科检索",
    "bilibili": "B站检索",
}


def _failure(status: str, reason: str) -> dict[str, Any]:
    return {"status": status, "reason": reason, "data": None}


def _normalize(text: object) -> str:
    """q/term 匹配归一：NFKC + casefold（与 glossary 召回同规）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.glossary import (
        normalize_glossary_text,
    )

    return normalize_glossary_text(str(text or ""))


def _read_only_connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path.as_uri() + "?mode=ro", uri=True, timeout=_BUSY_TIMEOUT_SECONDS
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    return connection


def _text_or_none(value: object) -> str | None:
    """时间/文本列 → 字符串或 null：NULL 与空串都归为 null（诚实空缺）。

    台账的 ``source_updated_at`` 空串是「上游确无可信编辑时间」（非 MediaWiki 系
    源），不是「有时间但看不见」——对外一律 null，绝不渲染成空时间戳。
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class KnowledgeCatalogService:
    """知识目录聚合（术语表文件 + 向量库 + 表情标签 + ACG 配置态）。"""

    def __init__(
        self,
        *,
        glossary_files: list[str | Path],
        knowledge_db_path: str | Path,
        meme_db_path: str | Path,
        acg_sources: dict[str, bool],
        kb_wiki_db_path: str | Path = "",
    ) -> None:
        self._glossary_files = [Path(item) for item in glossary_files]
        self._knowledge_db_path = str(knowledge_db_path or "")
        self._kb_wiki_db_path = str(kb_wiki_db_path or "")
        self._meme_db_path = str(meme_db_path or "")
        self._acg_sources = dict(acg_sources)

    # -- 集合目录 -----------------------------------------------------------

    def collections(self) -> dict[str, Any]:
        glossary_entries = self._load_glossary_entries()
        kb_status, kb_docs = self._kb_document_index()
        kb_sync = self._kb_sync_summary()
        meme_status, meme_tags = self._meme_tag_counts()
        acg_any = any(bool(value) for value in self._acg_sources.values())
        items: list[dict[str, Any]] = [
            {
                "id": "community_terms",
                "name": "社区词条（世界观术语表）",
                "description": "词汇回忆/世界观 glossary 全量词条",
                "enabled": bool(glossary_entries),
                "source": "glossary_files",
                "count": len(glossary_entries),
                "reason": None if glossary_entries else "glossary_source_unavailable",
            },
            {
                "id": "kb_docs",
                "name": "向量知识库文档",
                "description": "知识库文档级清单（chunk 数聚合；检索走 platform API）",
                "enabled": kb_status == "ok",
                "source": "knowledge_embeddings",
                "count": len(kb_docs) if kb_docs is not None else 0,
                "reason": None if kb_status == "ok" else kb_status,
                # kb-sync 最近一轮摘要（上次同步时间/成败/新增条数/耗时）；
                # 从未跑过或库缺失 → 如实 null，不拿文件 mtime 冒充同步时间。
                "sync": kb_sync,
            },
            {
                "id": "meme_tags",
                "name": "表情库标签目录",
                "description": "表情库 VLM 标签聚合 counts",
                "enabled": meme_status == "ok",
                "source": "meme_library",
                "count": len(meme_tags) if meme_tags is not None else 0,
                "reason": None if meme_status == "ok" else meme_status,
            },
            {
                "id": "acg_sources",
                "name": "ACG 检索增强源",
                "description": "Bangumi/萌娘百科/B站 检索源配置态",
                "enabled": acg_any,
                "source": "static_config",
                "count": sum(1 for value in self._acg_sources.values() if value),
                "reason": None if acg_any else "disabled_by_config",
            },
        ]
        for entry in _NOT_AVAILABLE_COLLECTIONS:
            items.append(
                {
                    "id": entry["id"],
                    "name": entry["name"],
                    "description": entry["description"],
                    "enabled": False,
                    "source": "none",
                    "count": None,
                    "reason": _NOT_AVAILABLE_REASON,
                }
            )
        return {"status": "ok", "source": "knowledge_collections", "data": {"items": items}}

    # -- 词条查询 -----------------------------------------------------------

    def terms(
        self,
        collection: object,
        q: str = "",
        page: int = 1,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        known_ids = frozenset(_REAL_COLLECTIONS) | {
            entry["id"] for entry in _NOT_AVAILABLE_COLLECTIONS
        }
        if not isinstance(collection, str) or collection not in known_ids:
            return _failure("invalid_request", "invalid_collection")
        if type(page) is not int or page < 1:
            return _failure("invalid_request", "invalid_page")
        if type(page_size) is not int or not 1 <= page_size <= _MAX_PAGE_SIZE:
            return _failure("invalid_request", "invalid_page_size")
        if not isinstance(q, str) or len(q) > _MAX_QUERY_CHARS:
            return _failure("invalid_request", "invalid_query")
        if collection in _NOT_AVAILABLE_IDS:
            # 用户点名但无独立库：如实 unavailable，绝不假造词条。
            return _failure("source_unavailable", "collection_not_available")
        if collection == "community_terms":
            rows = self._community_term_rows()
            needle = _normalize(q)
            if needle:
                rows = [
                    row
                    for row in rows
                    if needle in _normalize(row["term"])
                    or any(needle in _normalize(alias) for alias in row["aliases"])
                ]
        elif collection == "kb_docs":
            status, docs = self._kb_document_index()
            if status != "ok" or docs is None:
                return _failure("source_unavailable", status)
            rows = self._kb_doc_rows(docs, q)
        elif collection == "meme_tags":
            status, tags = self._meme_tag_counts()
            if status != "ok" or tags is None:
                return _failure("source_unavailable", status)
            rows = self._meme_tag_rows(tags, q)
        else:
            rows = self._acg_rows(q)
        start = (page - 1) * page_size
        return {
            "status": "ok",
            "source": f"knowledge_terms:{collection}",
            "data": {
                "collection": collection,
                "page": page,
                "page_size": page_size,
                "total": len(rows),
                "items": rows[start : start + page_size],
            },
        }

    # -- community_terms ----------------------------------------------------

    def _community_term_rows(self) -> list[dict[str, Any]]:
        rows = [
            {
                "term": entry["term"],
                "aliases": entry["aliases"],
                "definition": entry["definition"],
                "scope": "general",
                "source": entry["source"],
            }
            for entry in self._load_glossary_entries()
        ]
        return rows

    def _load_glossary_entries(self) -> list[dict[str, Any]]:
        """全量解析术语表文件（同规 FileGlossaryProvider，但不截断不设上限）。"""
        from plugins.bot_unified_runtime.domains.chat_reply.character.glossary import (
            _TERM_ALIAS_SPLIT_RE,
            _parse_entry_line,
        )

        if not self._glossary_files:
            return []
        entries: list[dict[str, Any]] = []
        for path in self._glossary_files:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            stem = path.stem
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parsed = _parse_entry_line(line)
                if parsed is None:
                    continue
                term, definition = parsed
                if not term or not definition:
                    continue
                aliases: list[str] = []
                for part in _TERM_ALIAS_SPLIT_RE.split(term):
                    part = part.strip()
                    if part and part != term and part not in aliases:
                        aliases.append(part)
                entries.append(
                    {
                        "term": term,
                        "aliases": aliases,
                        "definition": definition,
                        "source": stem,
                    }
                )
        return entries

    # -- kb_docs ------------------------------------------------------------

    def _kb_document_index(self) -> tuple[str, list[dict[str, Any]] | None]:
        """文档级索引：人格库与 Crawl Wiki 库两处台账并集（同 id 以人格库那份为准）。

        返回 ``(status, docs)``；status ∈ ok/missing_source/incomplete_schema。
        任一侧可读即 ok——wiki 库还没启用/还没灌过时人格库照旧出全量，口径不缩；
        两侧都不可读时上报更具体的失败码（incomplete_schema 优先于 missing_source，
        别让建了半张表的库被说成「找不到源」）。
        """
        merged: dict[str, dict[str, Any]] = {}
        status = "missing_source"
        for raw_path in (self._knowledge_db_path, self._kb_wiki_db_path):
            one_status, docs = self._document_index_from(raw_path)
            if one_status == "ok" and docs is not None:
                status = "ok"
                for doc in docs:
                    merged.setdefault(doc["doc_id"], doc)
            elif status != "ok" and one_status == "incomplete_schema":
                status = "incomplete_schema"
        if status != "ok":
            return status, None
        return "ok", list(merged.values())

    def _document_index_from(self, raw_path: str) -> tuple[str, list[dict[str, Any]] | None]:
        """单个向量库的文档级索引：knowledge_chunks 聚合 ∪ knowledge_docs 台账。"""
        if not raw_path:
            return "missing_source", None
        try:
            path = Path(raw_path).resolve()
            if not path.is_file():
                return "missing_source", None
            with closing(_read_only_connect(path)) as connection:
                connection.execute("BEGIN")
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not _KB_REQUIRED_TABLES <= tables:
                    return "incomplete_schema", None
                chunk_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(knowledge_chunks)")
                }
                if not _KB_CHUNK_COLUMNS <= chunk_columns:
                    return "incomplete_schema", None
                counts: dict[str, int] = {}
                titles: dict[str, str] = {}
                for row in connection.execute(
                    "SELECT source_id, title, COUNT(*) AS n FROM knowledge_chunks"
                    " GROUP BY source_id"
                ):
                    source_id = str(row["source_id"] or "")
                    if not source_id:
                        continue
                    counts[source_id] = int(row["n"])
                    titles.setdefault(source_id, str(row["title"] or ""))
                docs: dict[str, dict[str, Any]] = {}
                doc_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(knowledge_docs)")
                }
                if _KB_DOC_COLUMNS <= doc_columns:
                    # 时间元数据两列是 kb-sync 侧的幂等迁移产物：存量库可能还没
                    # 迁移（缺列）。本服务是只读面、绝不 ALTER，因此缺列的文档
                    # 如实报 null，而不是报一个编出来的时间。
                    time_columns = sorted(_KB_DOC_TIME_COLUMNS & doc_columns)
                    for row in connection.execute(
                        "SELECT doc_id, topic, title"
                        + "".join(f", {column}" for column in time_columns)
                        + " FROM knowledge_docs"
                    ):
                        doc_id = str(row["doc_id"] or "")
                        if not doc_id:
                            continue
                        docs[doc_id] = {
                            "topic": str(row["topic"] or ""),
                            "title": str(row["title"] or ""),
                            **{
                                column: _text_or_none(row[column])
                                for column in time_columns
                            },
                        }
        except (sqlite3.Error, OSError, ValueError, TypeError, IndexError):
            return "missing_source", None
        index: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source_id in sorted(counts):
            seen.add(source_id)
            ledger = docs.get(source_id, {})
            index.append(
                {
                    "doc_id": source_id,
                    "title": titles.get(source_id) or ledger.get("title", ""),
                    "topic": ledger.get("topic", ""),
                    "chunk_count": counts[source_id],
                    "source_updated_at": ledger.get("source_updated_at"),
                    "crawl_at": ledger.get("crawl_at"),
                }
            )
        for doc_id in sorted(docs):
            if doc_id in seen:
                continue
            entry = docs[doc_id]
            index.append(
                {
                    "doc_id": doc_id,
                    "title": entry["title"],
                    "topic": entry["topic"],
                    "chunk_count": 0,
                    "source_updated_at": entry.get("source_updated_at"),
                    "crawl_at": entry.get("crawl_at"),
                }
            )
        return "ok", index

    def _kb_sync_summary(self) -> dict[str, Any] | None:
        """kb-sync 最近一轮摘要（wiki 库 knowledge_meta 单行 JSON，只读）。

        这是「全程静默但不无痕」的可见面：上次同步时间 / 成败 / 新增条数 / 耗时 /
        对账与回填状态。无记录（从未跑过、库缺失、JSON 损坏）一律 null，
        绝不拿 manifest.generated_at 或文件 mtime 冒充「同步时间」。
        """
        if not self._kb_wiki_db_path:
            return None
        try:
            path = Path(self._kb_wiki_db_path).resolve()
            if not path.is_file():
                return None
            with closing(_read_only_connect(path)) as connection:
                connection.execute("BEGIN")
                row = connection.execute(
                    "SELECT value FROM knowledge_meta WHERE key = ?",
                    (_KB_SYNC_SUMMARY_KEY,),
                ).fetchone()
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return None
        if row is None or not str(row["value"] or ""):
            return None
        try:
            payload = json.loads(str(row["value"]))
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        summary = {key: payload[key] for key in _KB_SYNC_PUBLIC_FIELDS if key in payload}
        return summary or None

    def _kb_doc_rows(self, docs: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
        needle = _normalize(q)
        rows: list[dict[str, Any]] = []
        for doc in sorted(docs, key=lambda item: item["doc_id"]):
            haystack = _normalize(
                " ".join([doc["doc_id"], doc["title"], doc["topic"]])
            )
            if needle and needle not in haystack:
                continue
            source_updated_at = _text_or_none(doc.get("source_updated_at"))
            crawl_at = _text_or_none(doc.get("crawl_at"))
            rows.append(
                {
                    "term": doc["doc_id"],
                    "aliases": [],
                    "definition": doc["title"] or doc["topic"] or None,
                    "scope": "kb_doc",
                    "source": "knowledge_embeddings",
                    "chunk_count": doc["chunk_count"],
                    # 文档级时间真值：上游编辑时间优先，缺失退本地抓取落盘时间；
                    # 两列各自同时透出，谁是谁一目了然（无值一律 null，不造时间）。
                    "updated_at": source_updated_at or crawl_at,
                    "source_updated_at": source_updated_at,
                    "crawl_at": crawl_at,
                }
            )
        return rows

    # -- meme_tags ----------------------------------------------------------

    def _meme_tag_counts(self) -> tuple[str, list[dict[str, Any]] | None]:
        if not self._meme_db_path:
            return "missing_source", None
        try:
            path = Path(self._meme_db_path).resolve()
            if not path.is_file():
                return "missing_source", None
            with closing(_read_only_connect(path)) as connection:
                connection.execute("BEGIN")
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if "memes" not in tables:
                    return "incomplete_schema", None
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(memes)")
                }
                if not _MEME_REQUIRED_COLUMNS <= columns:
                    return "incomplete_schema", None
                counts: dict[str, dict[str, Any]] = {}
                for row in connection.execute(
                    "SELECT emotion_tags, scene_tags FROM memes"
                ):
                    for column, scope in (
                        ("emotion_tags", "emotion_tags"),
                        ("scene_tags", "scene_tags"),
                    ):
                        raw = row[column]
                        try:
                            tags = json.loads(raw) if raw else []
                        except (json.JSONDecodeError, TypeError):
                            continue  # 坏 JSON 行：跳过，不炸聚合。
                        if not isinstance(tags, list):
                            continue
                        for tag in tags:
                            text = str(tag).strip()
                            if not text:
                                continue
                            bucket = counts.setdefault(
                                text, {"count": 0, "scopes": set()}
                            )
                            bucket["count"] += 1
                            bucket["scopes"].add(scope)
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return "missing_source", None
        return (
            "ok",
            [
                {"tag": tag, "count": bucket["count"], "scopes": bucket["scopes"]}
                for tag, bucket in counts.items()
            ],
        )

    def _meme_tag_rows(self, tags: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
        needle = _normalize(q)
        rows: list[dict[str, Any]] = []
        for bucket in tags:
            if needle and needle not in _normalize(bucket["tag"]):
                continue
            rows.append(
                {
                    "term": bucket["tag"],
                    "aliases": [],
                    "definition": None,
                    "scope": sorted(bucket["scopes"]),
                    "source": "meme_library",
                    "count": bucket["count"],
                }
            )
        rows.sort(key=lambda row: (-row["count"], row["term"]))
        return rows

    # -- acg_sources --------------------------------------------------------

    def _acg_rows(self, q: str) -> list[dict[str, Any]]:
        needle = _normalize(q)
        rows: list[dict[str, Any]] = []
        for key in sorted(_ACG_SOURCE_NAMES):
            enabled = bool(self._acg_sources.get(key, False))
            if needle and needle not in _normalize(key):
                continue
            rows.append(
                {
                    "term": key,
                    "aliases": [],
                    "definition": _ACG_SOURCE_NAMES[key],
                    "scope": "acg_source",
                    "source": "static_config",
                    "enabled": enabled,
                }
            )
        return rows


def build_default_knowledge_service(config: object | None) -> KnowledgeCatalogService:
    """按 config 解析默认数据源（与 _app 默认装配同一套 runtime 重映射）。"""
    glossary_raw = list(getattr(config, "bot_glossary_files", []) or [])
    glossary_files: list[str | Path] = [_path(str(item)) for item in glossary_raw if str(item).strip()]
    if not glossary_files:
        # 与 chat 装配同规：空配置回退随包种子（缺失时 load 静默为空，不炸）。
        from plugins.bot_unified_runtime.domains.chat_reply.character.glossary import (
            SEED_GLOSSARY_PATH,
        )

        glossary_files = [SEED_GLOSSARY_PATH]
    knowledge_raw = str(getattr(config, "bot_knowledge_db_path", "") or "").strip()
    # Crawl Wiki 向量库：文档台账与 kb-sync 摘要的真身所在地。不加
    # bot_kb_wiki_enabled 门——本服务只读投影，库文件在不在、同步跑没跑过都由
    # 数据自己说话（关着但留过库 → 仍能如实看到上次同步记录）。
    kb_wiki_raw = str(getattr(config, "bot_kb_wiki_db_path", "") or "").strip()
    meme_raw = str(getattr(config, "bot_meme_library_db_path", "") or "").strip()
    acg_enabled = bool(getattr(config, "bot_search_acg_enabled", False))
    acg_sources = {
        key: acg_enabled
        and bool(getattr(config, f"bot_search_acg_{key}_enabled", False))
        for key in _ACG_SOURCE_NAMES
    }
    return KnowledgeCatalogService(
        glossary_files=glossary_files,
        knowledge_db_path=_path(knowledge_raw) if knowledge_raw else "",
        meme_db_path=_path(meme_raw) if meme_raw else "",
        acg_sources=acg_sources,
        kb_wiki_db_path=_path(kb_wiki_raw) if kb_wiki_raw else "",
    )
