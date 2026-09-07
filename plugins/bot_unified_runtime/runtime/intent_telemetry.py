"""联网分类遥测：只保存哈希、决策和结果统计，不保存完整用户原文。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .question_intent import IntentDecision


class IntentTelemetry(Protocol):
    def record(
        self,
        *,
        request_id: str,
        text: str,
        decision: IntentDecision,
        knowledge_answerable: bool,
        knowledge_confidence: float,
        knowledge_chunk_count: int,
        web_search_attempted: bool,
        web_search_used: bool,
        web_hit_count: int,
        web_latency_ms: float,
        web_error_kind: str = "",
        legacy_category: str = "",
    ) -> None:
        raise NotImplementedError

    def summary(self) -> dict[str, Any]:
        raise NotImplementedError


class NullIntentTelemetry:
    def record(self, **kwargs: object) -> None:
        return None

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "total": 0,
            "by_category": {},
            "by_decision": {},
            "web_search_attempted": 0,
            "web_search_used": 0,
            "web_empty_results": 0,
            "average_web_latency_ms": 0.0,
        }


def _query_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


class SQLiteIntentTelemetry:
    def __init__(self, db_path: str | Path, max_items: int = 10000) -> None:
        self.db_path = Path(db_path)
        self.max_items = max(1, int(max_items))
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS intent_telemetry (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    query_hash TEXT NOT NULL,
                    category TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reason TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    score_breakdown TEXT NOT NULL,
                    allow_model_tool INTEGER NOT NULL,
                    knowledge_answerable INTEGER NOT NULL,
                    knowledge_confidence REAL NOT NULL,
                    knowledge_chunk_count INTEGER NOT NULL,
                    web_search_attempted INTEGER NOT NULL,
                    web_search_used INTEGER NOT NULL,
                    web_hit_count INTEGER NOT NULL,
                    web_latency_ms REAL NOT NULL,
                    web_error_kind TEXT NOT NULL,
                    legacy_category TEXT NOT NULL,
                    algorithm_version TEXT NOT NULL
                )
                """
            )

    def record(
        self,
        *,
        request_id: str,
        text: str,
        decision: IntentDecision,
        knowledge_answerable: bool,
        knowledge_confidence: float,
        knowledge_chunk_count: int,
        web_search_attempted: bool,
        web_search_used: bool,
        web_hit_count: int,
        web_latency_ms: float,
        web_error_kind: str = "",
        legacy_category: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO intent_telemetry (
                    request_id, created_at, query_hash, category, intent, decision,
                    confidence, reason, reason_codes, score_breakdown, allow_model_tool,
                    knowledge_answerable, knowledge_confidence, knowledge_chunk_count,
                    web_search_attempted, web_search_used, web_hit_count, web_latency_ms,
                    web_error_kind, legacy_category, algorithm_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(request_id),
                    datetime.now(timezone.utc).isoformat(),
                    _query_hash(text),
                    decision.category,
                    decision.intent.value,
                    decision.decision.value,
                    float(decision.confidence),
                    decision.reason,
                    json.dumps(list(decision.reason_codes), ensure_ascii=False),
                    json.dumps(decision.score_breakdown, ensure_ascii=False, sort_keys=True),
                    int(decision.allow_model_tool),
                    int(bool(knowledge_answerable)),
                    max(0.0, min(1.0, float(knowledge_confidence))),
                    max(0, int(knowledge_chunk_count)),
                    int(bool(web_search_attempted)),
                    int(bool(web_search_used)),
                    max(0, int(web_hit_count)),
                    max(0.0, float(web_latency_ms)),
                    str(web_error_kind or "")[:80],
                    str(legacy_category or "")[:80],
                    decision.algorithm_version,
                ),
            )
            connection.execute(
                """
                DELETE FROM intent_telemetry
                WHERE event_id NOT IN (
                    SELECT event_id FROM intent_telemetry
                    ORDER BY event_id DESC LIMIT ?
                )
                """,
                (self.max_items,),
            )

    def list_records(self, limit: int | None = None) -> list[dict[str, Any]]:
        take = max(1, int(limit or self.max_items))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM intent_telemetry ORDER BY event_id ASC LIMIT ?",
                (take,),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            total = int(
                connection.execute("SELECT COUNT(*) FROM intent_telemetry").fetchone()[0]
            )
            by_category = {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT category, COUNT(*) FROM intent_telemetry GROUP BY category"
                ).fetchall()
            }
            by_decision = {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT decision, COUNT(*) FROM intent_telemetry GROUP BY decision"
                ).fetchall()
            }
            attempted = int(
                connection.execute(
                    "SELECT COALESCE(SUM(web_search_attempted), 0) FROM intent_telemetry"
                ).fetchone()[0]
            )
            used = int(
                connection.execute(
                    "SELECT COALESCE(SUM(web_search_used), 0) FROM intent_telemetry"
                ).fetchone()[0]
            )
            empty = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM intent_telemetry
                    WHERE web_search_attempted = 1 AND web_hit_count = 0
                    """
                ).fetchone()[0]
            )
            average_latency = float(
                connection.execute(
                    """
                    SELECT COALESCE(AVG(web_latency_ms), 0)
                    FROM intent_telemetry
                    WHERE web_search_attempted = 1
                    """
                ).fetchone()[0]
            )
        return {
            "enabled": True,
            "total": total,
            "by_category": by_category,
            "by_decision": by_decision,
            "web_search_attempted": attempted,
            "web_search_used": used,
            "web_empty_results": empty,
            "average_web_latency_ms": round(average_latency, 3),
            # 没有人工标注时不伪造 precision/recall；这些字段需后续反馈补齐。
            "label_metrics_available": False,
        }


def build_intent_telemetry(
    *,
    enabled: bool,
    db_path: str | Path,
    max_items: int = 10000,
) -> IntentTelemetry:
    if not enabled:
        return NullIntentTelemetry()
    try:
        return SQLiteIntentTelemetry(db_path, max_items=max_items)
    except (OSError, sqlite3.Error):
        return NullIntentTelemetry()
