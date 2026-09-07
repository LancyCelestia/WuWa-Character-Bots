"""Safe cutover from the pre-V2 subscription database."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def _has_table(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def prepare_subscription_database(primary_path: str) -> str:
    primary = Path(primary_path).expanduser()
    primary.parent.mkdir(parents=True, exist_ok=True)
    backup = primary.with_name("subscriptions_old.sqlite3")
    lock = primary.with_name("subscriptions.sqlite3.v2.lock")

    with open(lock, "a+b"):
        if primary.exists():
            connection = sqlite3.connect(str(primary))
            try:
                has_v2 = _has_table(connection, "schema_meta") and bool(
                    connection.execute(
                        "SELECT 1 FROM schema_meta WHERE key='version' AND value='2'"
                    ).fetchone()
                )
                old_shape = _has_table(connection, "subscriptions")
            finally:
                connection.close()
            if has_v2:
                return str(primary)
            if old_shape:
                if backup.exists() or Path(f"{backup}-wal").exists() or Path(
                    f"{backup}-shm"
                ).exists():
                    raise RuntimeError(
                        "subscriptions_old.sqlite3 already exists; refusing overwrite"
                    )
                for suffix in ("", "-wal", "-shm"):
                    source = Path(f"{primary}{suffix}")
                    if source.exists():
                        os.rename(source, Path(f"{backup}{suffix}"))

        temporary = primary.with_name(f".{primary.name}.v2.tmp")
        if temporary.exists():
            temporary.unlink()
        try:
            connection = sqlite3.connect(str(temporary))
            connection.executescript(
                """
                CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO schema_meta(key, value) VALUES ('version', '2');
                """
            )
            connection.commit()
            connection.close()
            os.replace(temporary, primary)
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
    return str(primary)
