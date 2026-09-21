"""统一控制面资源、Trace、Usage、ModelCall 与安全资源服务。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Self


class PlatformStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # V21-risk-2：旧版 traces 建表主键为 trace_id，与 append 的 (id,data) 列名
        # 不一致且历史写入必然全部失败（表必为空）→ 检测到旧结构即重建统一列名。
        legacy_traces = self._conn.execute("PRAGMA table_info(traces)").fetchall()
        if legacy_traces and not any(str(row["name"]) == "id" for row in legacy_traces):
            self._conn.execute("DROP TABLE traces")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS resources(
                kind TEXT,id TEXT,version INTEGER NOT NULL,data TEXT NOT NULL,
                updated_at TEXT NOT NULL,PRIMARY KEY(kind,id)
            );
            CREATE TABLE IF NOT EXISTS resource_versions(
                kind TEXT,id TEXT,version INTEGER NOT NULL,data TEXT NOT NULL,
                updated_at TEXT NOT NULL,PRIMARY KEY(kind,id,version)
            );
            CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS model_calls(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS logs(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            """
        )
        self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def list_resources(self, kind: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                json.loads(row["data"])
                | {
                    "id": row["id"],
                    "version": row["version"],
                    "updated_at": row["updated_at"],
                }
                for row in self._conn.execute(
                    "SELECT * FROM resources WHERE kind=? ORDER BY id", (kind,)
                )
            ]

    def get(self, kind: str, ident: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM resources WHERE kind=? AND id=?", (kind, ident)
            ).fetchone()
            return (
                None
                if row is None
                else json.loads(row["data"])
                | {
                    "id": row["id"],
                    "version": row["version"],
                    "updated_at": row["updated_at"],
                }
            )

    def put(
        self, kind: str, ident: str, data: dict[str, Any], expected: int | None = None
    ) -> dict[str, Any]:
        with self._lock:
            now = self._now()
            clean = dict(data)
            clean.pop("id", None)
            clean.pop("version", None)
            clean.pop("updated_at", None)
            blob = json.dumps(clean, ensure_ascii=False)
            if expected is not None:
                # V21-risk-2：单语句原子 CAS——比较与写回在同一 UPDATE 内完成，
                # 消除读-写间隙（跨实例另一写者在间隙提交 → WHERE version=expected
                # 落空 → 拒绝，不再丢更新）。
                cur = self._conn.execute(
                    "UPDATE resources SET version=version+1,data=?,updated_at=? "
                    "WHERE kind=? AND id=? AND version=?",
                    (blob, now, kind, ident, int(expected)),
                )
                if cur.rowcount == 0:
                    existing = self._conn.execute(
                        "SELECT version FROM resources WHERE kind=? AND id=?",
                        (kind, ident),
                    ).fetchone()
                    if existing is None and int(expected) == 0:
                        # expected=0 语义=新建（保持既有约定）。
                        self._conn.execute(
                            "INSERT INTO resources(kind,id,version,data,updated_at)"
                            " VALUES(?,?,1,?,?)",
                            (kind, ident, blob, now),
                        )
                        version = 1
                    else:
                        self._conn.rollback()
                        raise ValueError("version_conflict")
                else:
                    version = int(expected) + 1
            else:
                old = self.get(kind, ident)
                version = 1 if old is None else int(old["version"]) + 1
                self._conn.execute(
                    "INSERT INTO resources(kind,id,version,data,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET version=excluded.version,data=excluded.data,updated_at=excluded.updated_at",
                    (kind, ident, version, blob, now),
                )
            self._conn.execute(
                "INSERT INTO resource_versions(kind,id,version,data,updated_at) VALUES(?,?,?,?,?)",
                (kind, ident, version, blob, now),
            )
            self._conn.commit()
            return clean | {"id": ident, "version": version, "updated_at": now}

    def versions(self, kind: str, ident: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM resource_versions WHERE kind=? AND id=? ORDER BY version DESC",
                (kind, ident),
            )
            return [
                json.loads(row["data"])
                | {
                    "id": row["id"],
                    "version": row["version"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]

    def delete(self, kind: str, ident: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM resources WHERE kind=? AND id=?", (kind, ident)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def append(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        ident = str(data.get("id") or data.get("trace_id") or uuid.uuid4().hex)
        payload = dict(data)
        payload.setdefault("id", ident)
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO {table}(id,data) VALUES(?,?)",
                (ident, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()
        return payload

    def rows(self, table: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return [
                json.loads(r["data"])
                for r in self._conn.execute(
                    f"SELECT data FROM {table} ORDER BY rowid DESC LIMIT ?",
                    (min(max(limit, 1), 1000),),
                )
            ]

    def close(self) -> None:
        """提交未决事务并关闭连接（V21-risk-2 生命周期收口）。"""
        with self._lock:
            try:
                self._conn.commit()
            except sqlite3.Error:
                pass
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class PlatformService:
    """HTTP 无关的 platform 资源业务层（V21-risk-1 收口）。

    路由层不再直操 PlatformStore：资源读写、生命周期产物、作业登记一律经由本服务。
    「无真实执行路径必须显式失败、不得假成功」（V21-risk-3）在 publish/activate
    与 register_job 处落地。
    """

    def __init__(self, store: PlatformStore) -> None:
        self.store = store

    # ---- 资源 CRUD ----

    def list_resources(self, kind: str) -> dict[str, Any]:
        return {"items": self.store.list_resources(kind)}

    def get_resource(self, kind: str, resource_id: str) -> dict[str, Any] | None:
        return self.store.get(kind, resource_id)

    def put_resource(
        self,
        kind: str,
        resource_id: str,
        payload: dict[str, Any],
        expected: int | None = None,
    ) -> dict[str, Any]:
        return self.store.put(kind, resource_id, payload, expected)

    def versions(self, kind: str, resource_id: str) -> list[dict[str, Any]]:
        return self.store.versions(kind, resource_id)

    # ---- 追加型记录（traces/usage/model_calls）----

    def append(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.store.append(table, payload)

    def rows(self, table: str, limit: int) -> list[dict[str, Any]]:
        return self.store.rows(table, limit)

    # ---- 生命周期：产出真实激活标记，不做纯标记假成功 ----

    # 参与内容摘要的字段（ bookkeeping 元数据除外，且摘要自身不参与——可复算）。
    _DIGEST_EXCLUDED = frozenset(
        {"id", "version", "updated_at", "content_sha256"}
    )

    @staticmethod
    def content_digest(data: dict[str, Any]) -> str:
        """资源内容 sha256 快照（V21-risk-3 补口：publish 必须落哈希快照）。

        可复算：剔除 bookkeeping 字段与摘要自身后按 sort_keys 序列化；
        读回方可对同字段集重算比对，检测落库内容被旁路篡改。
        """
        core = {
            k: v for k, v in data.items() if k not in PlatformService._DIGEST_EXCLUDED
        }
        blob = json.dumps(core, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def verify_resource(self, kind: str, resource_id: str) -> dict[str, Any]:
        """复核当前资源数据与其发布期 content_sha256 快照。

        快照取自版本史（resource_versions 内最新携带哈希的版本行）而非当前
        数据——旁路篡改若连当前数据里的哈希一并改写，版本史里的原始快照
        仍可对照检出（哈希快照的取证意义正在于此）。无任何快照=如实报 absent。
        """
        current = self.store.get(kind, resource_id)
        if current is None:
            return {"resource_id": resource_id, "has_snapshot": False, "intact": None}
        stored = next(
            (
                item.get("content_sha256")
                for item in self.store.versions(kind, resource_id)  # version DESC
                if item.get("content_sha256")
            ),
            None,
        )
        if not stored:
            return {
                "resource_id": resource_id,
                "has_snapshot": False,
                "intact": None,
                "version": current["version"],
            }
        actual = self.content_digest(current)
        return {
            "resource_id": resource_id,
            "has_snapshot": True,
            "intact": actual == stored,
            "version": current["version"],
            "content_sha256": stored,
        }

    def apply_lifecycle(
        self,
        kind: str,
        resource_id: str,
        action: str,
        payload: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> dict[str, Any]:
        data = dict(current)
        data["lifecycle"] = action
        if action == "draft":
            data["draft"] = True
            data["active"] = False
        elif action in ("publish", "activate"):
            # publish/activate 必须留下真实激活产物（active + published_at）。
            data["draft"] = False
            data["active"] = True
            data["published_at"] = self.store._now()
        if payload:
            data.update({k: v for k, v in payload.items() if k != "expected_version"})
        # V21-risk-3 补口：publish/activate 必须同时落内容哈希快照
        # （放在全部业务字段定值之后计算；随版本行一并入 resource_versions）。
        if action in ("publish", "activate"):
            data["content_sha256"] = self.content_digest(data)
        return self.store.put(kind, resource_id, data, current["version"])

    # ---- 作业登记：无真实执行路径 → 显式不可用且可查，绝不假称 queued ----

    def register_job(
        self, job_kind: str, resource_id: str | None = None
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "kind": job_kind,
            "resource_id": resource_id,
            "status": "unavailable",
            "reason": "executor_not_wired",
            "created_at": self.store._now(),
        }
        self.store.append("jobs", record)
        return record

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        for row in self.store.rows("jobs", 1000):
            if row.get("id") == job_id:
                return row
        return None

    # ---- 记忆审核 ----

    def review_memory(self, resource_id: str, action: str) -> dict[str, Any] | None:
        memory = self.store.get("memories", resource_id)
        if memory is None:
            return None
        memory["review_state"] = "forgotten" if action == "forget" else action + "d"
        return self.store.put("memories", resource_id, memory, memory["version"])
