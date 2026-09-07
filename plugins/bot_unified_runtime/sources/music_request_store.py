"""音乐规范歌曲与机器人点歌行为的 SQLite 存储。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from plugins.bot_unified_runtime.contracts.music import (
    MusicRankingEntry,
    MusicRequestEvent,
    MusicTrack,
)
from plugins.bot_unified_runtime.sources.music_normalization import canonical_key


class MusicRequestStore:
    """保存规范歌曲、provider 映射和成功的 bot.music 请求事件。"""

    def __init__(
        self,
        db_path: str = "data/music_analytics.sqlite3",
        *,
        retention_days: int = 365,
    ) -> None:
        self._db_path = str(db_path or "data/music_analytics.sqlite3")
        self._retention_days = max(0, int(retention_days))
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            directory = os.path.dirname(os.path.abspath(self._db_path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            connection = sqlite3.connect(
                self._db_path,
                timeout=30.0,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            self._ensure_schema(connection)
            self._connection = connection
        return self._connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO schema_meta (key, value)
            VALUES ('version', '2');

            CREATE TABLE IF NOT EXISTS music_tracks (
                canonical_track_id TEXT PRIMARY KEY,
                canonical_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                metadata TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS music_provider_tracks (
                provider TEXT NOT NULL,
                provider_track_id TEXT NOT NULL,
                canonical_track_id TEXT NOT NULL,
                metadata TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (provider, provider_track_id),
                FOREIGN KEY (canonical_track_id)
                    REFERENCES music_tracks(canonical_track_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS music_track_aliases (
                canonical_track_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                PRIMARY KEY (canonical_track_id, alias),
                FOREIGN KEY (canonical_track_id)
                    REFERENCES music_tracks(canonical_track_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS music_request_events (
                request_id TEXT PRIMARY KEY,
                canonical_track_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_track_id TEXT NOT NULL,
                session_scope TEXT NOT NULL,
                requester_hash TEXT,
                requested_at TEXT NOT NULL,
                FOREIGN KEY (canonical_track_id)
                    REFERENCES music_tracks(canonical_track_id)
            );

            CREATE INDEX IF NOT EXISTS idx_music_request_events_requested_at
                ON music_request_events(requested_at);
            CREATE INDEX IF NOT EXISTS idx_music_request_events_track
                ON music_request_events(canonical_track_id);

            CREATE TABLE IF NOT EXISTS music_chart_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                category TEXT NOT NULL,
                region TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS music_chart_entries (
                snapshot_id TEXT NOT NULL,
                provider_track_id TEXT NOT NULL,
                rank INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                canonical_track_id TEXT,
                PRIMARY KEY (snapshot_id, provider_track_id),
                FOREIGN KEY (snapshot_id)
                    REFERENCES music_chart_snapshots(snapshot_id)
                    ON DELETE CASCADE
            );
            """
        )

    @staticmethod
    def _track_id_for_key(key: str) -> str:
        return f"track:{key}"

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def upsert_track(self, track: MusicTrack) -> str:
        key = canonical_key(track)
        canonical_id = track.canonical_track_id or self._track_id_for_key(key)
        now = datetime.now(timezone.utc).isoformat()
        metadata = track.model_dump(mode="json")
        metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        with self._lock:
            connection = self._get_connection()
            with connection:
                row = connection.execute(
                    "SELECT canonical_track_id, metadata FROM music_tracks "
                    "WHERE canonical_key = ?",
                    (key,),
                ).fetchone()
                if row is not None:
                    canonical_id = str(row["canonical_track_id"])
                connection.execute(
                    """
                    INSERT INTO music_tracks (
                        canonical_track_id, canonical_key, title, metadata, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_track_id) DO UPDATE SET
                        canonical_key = excluded.canonical_key,
                        title = excluded.title,
                        metadata = excluded.metadata,
                        updated_at = excluded.updated_at
                    """,
                    (canonical_id, key, track.title, metadata_json, now),
                )
                connection.execute(
                    """
                    INSERT INTO music_provider_tracks (
                        provider, provider_track_id, canonical_track_id,
                        metadata, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(provider, provider_track_id) DO UPDATE SET
                        canonical_track_id = excluded.canonical_track_id,
                        metadata = excluded.metadata,
                        updated_at = excluded.updated_at
                    """,
                    (
                        track.provider,
                        track.provider_track_id,
                        canonical_id,
                        metadata_json,
                        now,
                    ),
                )
                for alias in track.aliases:
                    normalized_alias = str(alias).strip()
                    if normalized_alias:
                        connection.execute(
                            "INSERT OR IGNORE INTO music_track_aliases "
                            "(canonical_track_id, alias) VALUES (?, ?)",
                            (canonical_id, normalized_alias),
                        )
        return canonical_id

    def record_successful_request(self, event: MusicRequestEvent) -> bool:
        requested_at = self._ensure_utc(event.requested_at).isoformat()
        with self._lock:
            connection = self._get_connection()
            with connection:
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO music_request_events (
                        request_id, canonical_track_id, provider,
                        provider_track_id, session_scope, requester_hash,
                        requested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.request_id,
                        event.canonical_track_id,
                        event.provider,
                        event.provider_track_id,
                        event.session_scope,
                        event.requester_hash,
                        requested_at,
                    ),
                ).rowcount
        return bool(inserted)

    @staticmethod
    def _period_start(period: str, now: datetime) -> datetime:
        normalized = str(period).strip().lower()
        days = {"day": 1, "week": 7, "year": 365}.get(normalized)
        if days is None:
            raise ValueError("period must be day, week, or year")
        return now - timedelta(days=days)

    def request_ranking(
        self,
        *,
        period: str,
        now: datetime,
    ) -> list[MusicRankingEntry]:
        end = self._ensure_utc(now)
        start = self._period_start(period, end)
        with self._lock:
            connection = self._get_connection()
            rows = connection.execute(
                """
                SELECT
                    e.canonical_track_id,
                    COUNT(*) AS request_count,
                    MAX(e.requested_at) AS last_requested_at,
                    t.title,
                    t.metadata
                FROM music_request_events AS e
                JOIN music_tracks AS t
                  ON t.canonical_track_id = e.canonical_track_id
                WHERE e.requested_at >= ? AND e.requested_at < ?
                GROUP BY e.canonical_track_id
                ORDER BY request_count DESC, last_requested_at DESC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            result: list[MusicRankingEntry] = []
            for row in rows:
                try:
                    metadata = json.loads(row["metadata"] or "{}")
                    contributors = metadata.get("contributors") or []
                except (TypeError, ValueError):
                    contributors = []
                from plugins.bot_unified_runtime.contracts.music import MusicContributor

                parsed_contributors = [
                    MusicContributor.model_validate(item)
                    for item in contributors
                    if isinstance(item, dict) and item.get("name")
                ]
                provider_rows = connection.execute(
                    """
                    SELECT provider, COUNT(*) AS count
                    FROM music_request_events
                    WHERE canonical_track_id = ?
                      AND requested_at >= ? AND requested_at < ?
                    GROUP BY provider
                    """,
                    (row["canonical_track_id"], start.isoformat(), end.isoformat()),
                ).fetchall()
                result.append(
                    MusicRankingEntry(
                        canonical_track_id=str(row["canonical_track_id"]),
                        title=str(row["title"]),
                        contributors=parsed_contributors,
                        request_count=int(row["request_count"]),
                        last_requested_at=self._ensure_utc(
                            datetime.fromisoformat(str(row["last_requested_at"]))
                        ),
                        provider_counts={
                            str(item["provider"]): int(item["count"])
                            for item in provider_rows
                        },
                    )
                )
            return result

    def count_events(self) -> int:
        with self._lock:
            row = self._get_connection().execute(
                "SELECT COUNT(*) AS count FROM music_request_events"
            ).fetchone()
            return int(row["count"] if row is not None else 0)

    def events(self) -> list[MusicRequestEvent]:
        with self._lock:
            rows = self._get_connection().execute(
                "SELECT * FROM music_request_events ORDER BY requested_at"
            ).fetchall()
            return [
                MusicRequestEvent(
                    request_id=str(row["request_id"]),
                    canonical_track_id=str(row["canonical_track_id"]),
                    provider=str(row["provider"]),
                    provider_track_id=str(row["provider_track_id"]),
                    session_scope=str(row["session_scope"]),
                    requester_hash=row["requester_hash"],
                    requested_at=self._ensure_utc(
                        datetime.fromisoformat(str(row["requested_at"]))
                    ),
                )
                for row in rows
            ]

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
