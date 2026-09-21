"""Transactional SQLite persistence for the existing feature-state semantics.

Only the explicitly supplied database path is used (journals stay beside it;
SQLite temporary tables stay in memory). Legacy JSON migration is opt-in via
``import_legacy`` and never rewrites its source. Audit history is not pruned;
``audit`` retains the original API's latest-100 query limit, not a storage limit.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from .features import (
    FeatureDescriptor,
    FeatureRegistry,
    FeatureState,
    FeatureStateStore,
    InvalidFeatureStateError,
)


class _StateSnapshot(FeatureStateStore):
    """In-memory adapter: inherit all computation/protection, never JSON I/O."""

    def __init__(
        self, registry: FeatureRegistry, states: dict[str, dict[str, Any]], revision: int,
    ) -> None:
        self.registry = registry
        self._lock = threading.RLock()
        self._states = self._baseline = states
        self._audit: list[dict[str, Any]] = []
        self._revision = revision

    def get(self, feature_id: str) -> FeatureState:
        # The base _change stages a new dict before computing the projection,
        # restoring the original dict after preview/failure. Before/after audit
        # states therefore receive the appropriate graph revision as well.
        return replace(
            super().get(feature_id),
            graph_revision=self._revision + int(self._states is not self._baseline),
        )

    def _save(self) -> None:
        """The owning SQLite transaction persists the staged state and audit."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _decode(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (TypeError, ValueError) as exc:
        raise InvalidFeatureStateError("invalid feature state JSON") from exc
    if not isinstance(value, dict):
        raise InvalidFeatureStateError("invalid feature state record")
    return value


def _validate_states(states: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(states, dict):
        raise InvalidFeatureStateError("invalid feature state schema")
    for raw in states.values():
        if not isinstance(raw, dict):
            raise InvalidFeatureStateError("invalid feature state record")
        enabled, version = raw.get("explicit_enabled"), raw.get("version", 0)
        if enabled is not None and type(enabled) is not bool:
            raise InvalidFeatureStateError("invalid feature state boolean")
        if type(version) is not int or version < 0:
            raise InvalidFeatureStateError("invalid feature state version")
    return states


def _encode(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class SQLiteFeatureStateStore:
    """Fresh graph snapshots with graph-wide compare-and-swap transactions.

    ``version`` remains node-local. Mutations and previews require a nonnegative
    integer ``expected_revision``; None/omission is rejected, never a CAS bypass.
    Preview returns the projected next revision without writing anything.
    ``import_legacy`` returns True only when an unused empty database is imported;
    False means already imported or nonempty, with no state overwritten.
    """

    supports_graph_revision = True

    def __init__(
        self, path: str | Path, *, descriptors: tuple[FeatureDescriptor, ...] | None = None,
    ) -> None:
        self.path = Path(path).expanduser().absolute()
        self.registry = FeatureRegistry(descriptors)
        existing = self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(write=True, create=True) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tables:
                if existing:
                    raise InvalidFeatureStateError("empty or truncated feature database")
                db.execute("CREATE TABLE feature_meta (id INTEGER PRIMARY KEY CHECK(id=1), "
                           "graph_revision INTEGER NOT NULL CHECK(graph_revision>=0), "
                           "legacy_imported INTEGER NOT NULL CHECK(legacy_imported IN (0,1)))")
                db.execute("CREATE TABLE feature_states (feature_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                db.execute("CREATE TABLE feature_audit (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
                db.execute("INSERT INTO feature_meta VALUES (1, 0, 0)")
            elif not {"feature_meta", "feature_states", "feature_audit"} <= tables:
                raise InvalidFeatureStateError("incomplete feature database schema")
            if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise InvalidFeatureStateError("corrupt feature database")
            self._snapshot(db)

    @contextmanager
    def _transaction(self, *, write: bool = False, create: bool = False) -> Iterator[sqlite3.Connection]:
        mode = "rwc" if create else "rw" if write else "ro"
        db = None
        try:
            db = sqlite3.connect(f"{self.path.as_uri()}?mode={mode}", uri=True, isolation_level=None)
            db.execute("PRAGMA temp_store=MEMORY")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except sqlite3.Error as exc:
            raise OSError("feature state persistence failed") from exc
        finally:
            if db is not None:
                try:
                    if db.in_transaction:
                        db.rollback()
                finally:
                    db.close()

    @staticmethod
    def _meta(db: sqlite3.Connection) -> tuple[int, int]:
        rows = db.execute("SELECT id, graph_revision, legacy_imported FROM feature_meta").fetchall()
        if len(rows) != 1:
            raise InvalidFeatureStateError("invalid feature graph metadata")
        identity, revision, imported = rows[0]
        if identity != 1 or type(revision) is not int or revision < 0 or imported not in (0, 1):
            raise InvalidFeatureStateError("invalid feature graph revision")
        return revision, imported

    def _snapshot(self, db: sqlite3.Connection) -> _StateSnapshot:
        revision, _ = self._meta(db)
        states = {key: _decode(payload) for key, payload in db.execute("SELECT feature_id, payload FROM feature_states")}
        return _StateSnapshot(self.registry, _validate_states(states), revision)

    def get(self, feature_id: str) -> FeatureState:
        with self._transaction() as db:
            return self._snapshot(db).get(feature_id)

    def list_states(self) -> tuple[FeatureState, ...]:
        with self._transaction() as db:
            return self._snapshot(db).list_states()

    def audit(self, feature_id: str | None = None) -> tuple[dict[str, Any], ...]:
        """Latest 100 matching records, in chronological order; never prune disk."""
        with self._transaction() as db:
            self._meta(db)
            rows = []
            for (payload,) in db.execute("SELECT payload FROM feature_audit ORDER BY seq DESC"):
                row = _decode(payload)
                if not feature_id or row.get("feature_id") == feature_id:
                    rows.append(row)
                    if len(rows) == 100:
                        break
            return tuple(reversed(rows))

    def _change(
        self, feature_id: str, enabled: bool | None, *, actor: str | None,
        expected_version: int | None, expected_revision: int | None,
        request_id: str | None = None, preview: bool = False,
    ) -> dict[str, Any]:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a nonnegative integer")
        with self._transaction(write=not preview) as db:
            snapshot = self._snapshot(db)
            revision = snapshot._revision
            if expected_revision != revision:
                raise RuntimeError(f"feature graph revision conflict: expected {expected_revision}, actual {revision}")
            if preview:
                # The original API requires the node-local preview version too.
                if expected_version is None:
                    raise ValueError("expected_version is required for preview")
                return snapshot.preview(feature_id, enabled, expected_version)
            if enabled is None:
                result = snapshot.reset(
                    feature_id, actor=str(actor), expected_version=expected_version, request_id=request_id,
                )
            else:
                result = snapshot.set_enabled(
                    feature_id, enabled, actor=str(actor), expected_version=expected_version, request_id=request_id,
                )
            db.execute("INSERT INTO feature_states (feature_id, payload) VALUES (?, ?) "
                       "ON CONFLICT(feature_id) DO UPDATE SET payload=excluded.payload",
                       (feature_id, _encode(snapshot._states[feature_id])))
            db.execute("INSERT INTO feature_audit (payload) VALUES (?)", (_encode(snapshot._audit[-1]),))
            db.execute("UPDATE feature_meta SET graph_revision=? WHERE id=1", (revision + 1,))
            return result

    def set_enabled(
        self, feature_id: str, enabled: bool, *, actor: str,
        expected_version: int | None = None, request_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        return self._change(
            feature_id, bool(enabled), actor=actor, expected_version=expected_version,
            expected_revision=expected_revision, request_id=request_id,
        )

    def reset(
        self, feature_id: str, *, actor: str, expected_version: int | None = None,
        request_id: str | None = None, expected_revision: int | None = None,
    ) -> dict[str, Any]:
        return self._change(
            feature_id, None, actor=actor, expected_version=expected_version,
            expected_revision=expected_revision, request_id=request_id,
        )

    def preview(
        self, feature_id: str, enabled: bool | None, expected_version: int,
        *, expected_revision: int | None = None,
    ) -> dict[str, Any]:
        return self._change(
            feature_id, None if enabled is None else bool(enabled), actor=None,
            expected_version=expected_version, expected_revision=expected_revision, preview=True,
        )

    def import_legacy(self, path: str | Path) -> bool:
        """Explicit one-time import; no automatic discovery, overwrite or unlink."""
        with self._transaction(write=True) as db:
            revision, imported = self._meta(db)
            if (
                imported or revision
                or db.execute("SELECT 1 FROM feature_states LIMIT 1").fetchone()
                or db.execute("SELECT 1 FROM feature_audit LIMIT 1").fetchone()
            ):
                return False
            try:
                payload = _decode(Path(path).expanduser().read_text(encoding="utf-8"))
            except UnicodeError as exc:
                raise InvalidFeatureStateError("invalid legacy feature JSON encoding") from exc
            states = _validate_states(payload.get("states"))
            audits = payload.get("audit")
            if not isinstance(audits, list) or any(not isinstance(row, dict) for row in audits):
                raise InvalidFeatureStateError("invalid feature state audit")
            db.executemany("INSERT INTO feature_states (feature_id, payload) VALUES (?, ?)",
                           ((key, _encode(raw)) for key, raw in states.items()))
            db.executemany("INSERT INTO feature_audit (payload) VALUES (?)", ((_encode(row),) for row in audits))
            db.execute("UPDATE feature_meta SET graph_revision=1, legacy_imported=1 WHERE id=1")
            return True
