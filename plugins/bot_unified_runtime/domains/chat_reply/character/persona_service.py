"""V2.1 S7 人格版本管理服务（V21-PERSONA-001 地基）。

合同来源：docs/design/backend-v2-implementation-guide.md §9 人格段——

    Persona/World/Worldbook/Reference：draft→validated→published→active 指针；
    正式版本不可变；rollback 创建新版本；请求开始固定 persona_revision。
    仅超管发布人格。hash 损坏隔离并回到已验证版本，不能抹证据。

+ 验收矩阵行 V21-PERSONA-001（人格草稿/发布/激活/回滚不被插件改写；CAS、
正式快照 hash、损坏回退）。

红线（与既有人格资产的关系）：
1. **personas/ 目录零接触**：本服务是版本管理外壳，人格话术的唯一修改途径
   仍是既有 persona 工作流（RP 域所有）；本服务只管理「发布进版本库之后的
   生命周期」。装配席把 personas/ 同步产物灌入 draft→publish 链时，本模块
   不反向写任何人格文件。
2. **注入防护（结构性）**：人格核心内容只有一条出站路径
   ``build_core_injection``——只从 ``persona_versions``（已发布 + 哈希复核
   通过的版本）读出，带 (resource_id, version, sha256) 溯源；服务不存在
   「直接写 active 内容」「从任意路径读人格」的 API，插件拿不到 system
   prompt 写入面。
3. **正式版本不可变**：SQL 触发器在 UPDATE/DELETE 时 RAISE(ABORT)，任何
   代码（含本模块）都无法改写已发布版本；rollback = 按目标版本内容新增
   一版并激活，历史完整保留。
4. **损坏隔离不抹证据**：load 时哈希不符 → 拒载该版本 + quarantine 表
   留证（expected/actual sha256 + 时间戳，永不删除）+ 告警日志 + 自动回退
   到最近一个哈希完好的已发布版本；全部好版本皆损时 PersonaStoreUnavailable，
   绝不带病注入。
5. **权限门**：draft=admin+；publish/activate/rollback=super_admin 专属
   （guide §9「仅超管发布人格」；角色常量只读引用 policy/roles）。

存储：SQLite ``data/persona_versions.sqlite3``（无独立配置键，经
scripts/runtime_paths 解析——memory_v21.sqlite3 先例）；表前缀 persona_*：
versions（不可变）/ drafts（可变工作稿）/ state（active 指针+persona_revision）
/ quarantine（损坏证据，只增）。WAL + busy_timeout=1000ms + 每操作独立
连接（§7 契约，与 memory_store_v21 同构）。

CAS 语义：``expected_version`` = 调用方读到的最新已发布版本号；draft 与
publish 均在事务内比对，不匹配抛 PersonaVersionConflict（防并发发布丢更新）。
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
)

logger = logging.getLogger(__name__)

__all__ = [
    "PersonaLoad",
    "PersonaNotFoundError",
    "PersonaPermissionError",
    "PersonaService",
    "PersonaStoreUnavailable",
    "PersonaValidationError",
    "PersonaVersionConflict",
    "VersionedResourceStore",
    "build_persona_service",
]

DEFAULT_CONTENT_MAX_CHARS = 200_000
DEFAULT_DB_PATH = "data/persona_versions.sqlite3"
FALLBACK_ACTOR = "system:corruption-fallback"


class PersonaStoreUnavailable(RuntimeError):
    """SQLite/OSError 故障或全部版本损坏的归一出口（拒绝注入，绝不带病）。"""


class PersonaPermissionError(PermissionError):
    """角色不足（draft 需 admin+；publish/activate/rollback 需 super_admin）。"""


class PersonaVersionConflict(ValueError):
    """CAS expected_version 与库内最新已发布版本不一致（或版本号竞态落空）。"""


class PersonaNotFoundError(LookupError):
    """资源/版本不存在。"""


class PersonaValidationError(ValueError):
    """发布校验失败（内容非法/哈希不符），不产生版本。"""


@dataclass(frozen=True)
class PersonaLoad:
    """load_active / build_core_injection 的出站载体（注入防护唯一出口）。"""

    resource_id: str
    content: str
    version: int
    content_sha256: str
    persona_revision: int
    degraded: bool = False
    quarantine: tuple[dict[str, Any], ...] = field(default=())


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def sha256_text(text: str) -> str:
    """内容哈希（对落库 TEXT 的精确 utf-8 字节计算，可独立复算）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class VersionedResourceStore:
    """前缀参数化的版本库存储层：不可变版本 + 草稿 + active 指针 + 隔离证据。

    persona_* 与 worldbook_* 两个服务共用本类（各自独立库文件、独立表前缀），
    业务规则（校验/权限/引用图）全部在服务层，存储层不含业务语义。
    """

    def __init__(self, db_path: str | Path, *, prefix: str = "persona") -> None:
        self.db_path = Path(db_path)
        self.prefix = prefix
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.tables = {
            "versions": f"{prefix}_versions",
            "drafts": f"{prefix}_drafts",
            "state": f"{prefix}_state",
            "quarantine": f"{prefix}_quarantine",
        }

    # ------------------------------------------------------------------ 基础

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=1000")
        return connection

    def _scoped(self) -> _ScopedConnection:
        return _ScopedConnection(self)

    def ensure_schema(self) -> None:
        versions = self.tables["versions"]
        statements = (
            f"""
            CREATE TABLE IF NOT EXISTS {versions} (
                resource_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                published_by TEXT NOT NULL,
                published_at TEXT NOT NULL,
                PRIMARY KEY (resource_id, version)
            )
            """,
            # 正式版本不可变：任何 UPDATE/DELETE 一律 ABORT（结构性红线 3）。
            f"""
            CREATE TRIGGER IF NOT EXISTS {versions}_no_update
            BEFORE UPDATE ON {versions}
            BEGIN
                SELECT RAISE(ABORT, '{versions}_immutable');
            END
            """,
            f"""
            CREATE TRIGGER IF NOT EXISTS {versions}_no_delete
            BEFORE DELETE ON {versions}
            BEGIN
                SELECT RAISE(ABORT, '{versions}_immutable');
            END
            """,
            f"""
            CREATE TABLE IF NOT EXISTS {self.tables["drafts"]} (
                resource_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                base_version INTEGER NOT NULL DEFAULT 0
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS {self.tables["state"]} (
                resource_id TEXT PRIMARY KEY,
                active_version INTEGER NOT NULL,
                persona_revision INTEGER NOT NULL DEFAULT 1,
                activated_by TEXT NOT NULL DEFAULT '',
                activated_at TEXT NOT NULL,
                quarantined INTEGER NOT NULL DEFAULT 0,
                quarantine_reason TEXT NOT NULL DEFAULT ''
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS {self.tables["quarantine"]} (
                quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
                resource_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                expected_sha256 TEXT NOT NULL,
                actual_sha256 TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT ''
            )
            """,
        )
        with self._scoped() as conn:
            for statement in statements:
                conn.execute(statement)

    # ------------------------------------------------------------------ 版本行

    def latest_version(self, resource_id: str) -> int:
        with self._scoped() as conn:
            row = conn.execute(
                f"SELECT MAX(version) AS v FROM {self.tables['versions']} "
                "WHERE resource_id=?",
                (resource_id,),
            ).fetchone()
            return int(row["v"] or 0)

    def insert_published(
        self,
        resource_id: str,
        version: int,
        content: str,
        content_sha256: str,
        published_by: str,
        published_at: str,
    ) -> None:
        with self._scoped() as conn:
            conn.execute(
                f"INSERT INTO {self.tables['versions']}"
                "(resource_id, version, content, content_sha256, published_by,"
                " published_at) VALUES(?,?,?,?,?,?)",
                (resource_id, int(version), content, content_sha256, published_by,
                 published_at),
            )

    def get_version(self, resource_id: str, version: int) -> dict[str, Any] | None:
        with self._scoped() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.tables['versions']} "
                "WHERE resource_id=? AND version=?",
                (resource_id, int(version)),
            ).fetchone()
            return dict(row) if row is not None else None

    def versions_desc(self, resource_id: str) -> list[dict[str, Any]]:
        with self._scoped() as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.tables['versions']} "
                "WHERE resource_id=? ORDER BY version DESC",
                (resource_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def published_ids(self) -> list[str]:
        with self._scoped() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT resource_id FROM {self.tables['versions']}"
            ).fetchall()
            return sorted(str(row["resource_id"]) for row in rows)

    # ------------------------------------------------------------------ 草稿

    def upsert_draft(
        self,
        resource_id: str,
        content: str,
        updated_by: str,
        updated_at: str,
        base_version: int,
    ) -> None:
        with self._scoped() as conn:
            conn.execute(
                f"INSERT INTO {self.tables['drafts']}"
                "(resource_id, content, updated_by, updated_at, base_version)"
                " VALUES(?,?,?,?,?) ON CONFLICT(resource_id) DO UPDATE SET"
                " content=excluded.content, updated_by=excluded.updated_by,"
                " updated_at=excluded.updated_at,"
                " base_version=excluded.base_version",
                (resource_id, content, updated_by, updated_at, int(base_version)),
            )

    def get_draft(self, resource_id: str) -> dict[str, Any] | None:
        with self._scoped() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.tables['drafts']} WHERE resource_id=?",
                (resource_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def delete_draft(self, resource_id: str) -> None:
        with self._scoped() as conn:
            conn.execute(
                f"DELETE FROM {self.tables['drafts']} WHERE resource_id=?",
                (resource_id,),
            )

    # ------------------------------------------------------------------ 指针

    def get_state(self, resource_id: str) -> dict[str, Any] | None:
        with self._scoped() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.tables['state']} WHERE resource_id=?",
                (resource_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def set_active(
        self,
        resource_id: str,
        version: int,
        activated_by: str,
        activated_at: str,
    ) -> int:
        """激活指针：persona_revision 单调递增（请求开始固定修订的依据）。

        正常激活会清除 quarantined 标记（新指针已指向哈希复核通过的版本）；
        损坏证据在 quarantine 表，永不删除。
        """
        with self._scoped() as conn:
            row = conn.execute(
                f"SELECT persona_revision FROM {self.tables['state']} "
                "WHERE resource_id=?",
                (resource_id,),
            ).fetchone()
            revision = int(row["persona_revision"]) + 1 if row is not None else 1
            conn.execute(
                f"INSERT INTO {self.tables['state']}"
                "(resource_id, active_version, persona_revision, activated_by,"
                " activated_at, quarantined, quarantine_reason)"
                " VALUES(?,?,?,?,?,0,'') ON CONFLICT(resource_id) DO UPDATE SET"
                " active_version=excluded.active_version,"
                " persona_revision=excluded.persona_revision,"
                " activated_by=excluded.activated_by,"
                " activated_at=excluded.activated_at,"
                " quarantined=0, quarantine_reason=''",
                (resource_id, int(version), revision, activated_by, activated_at),
            )
            return revision

    def mark_quarantined(self, resource_id: str, reason: str) -> None:
        with self._scoped() as conn:
            conn.execute(
                f"UPDATE {self.tables['state']} SET quarantined=1,"
                " quarantine_reason=? WHERE resource_id=?",
                (reason, resource_id),
            )

    # ------------------------------------------------------------------ 隔离证据

    def insert_quarantine(
        self,
        resource_id: str,
        version: int,
        expected_sha256: str,
        actual_sha256: str,
        detected_at: str,
        detail: str = "",
    ) -> int:
        with self._scoped() as conn:
            cur = conn.execute(
                f"INSERT INTO {self.tables['quarantine']}"
                "(resource_id, version, expected_sha256, actual_sha256,"
                " detected_at, detail) VALUES(?,?,?,?,?,?)",
                (resource_id, int(version), expected_sha256, actual_sha256,
                 detected_at, detail),
            )
            return int(cur.lastrowid or 0)

    def quarantine_records(self, resource_id: str) -> list[dict[str, Any]]:
        with self._scoped() as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.tables['quarantine']} "
                "WHERE resource_id=? ORDER BY quarantine_id DESC",
                (resource_id,),
            ).fetchall()
            return [dict(row) for row in rows]


class _ScopedConnection:
    """连接生命周期 + 提交/回滚 + 异常归一（与 memory_store_v21 同构）。"""

    def __init__(self, store: VersionedResourceStore) -> None:
        self._store = store
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        try:
            self._connection = self._store._connect()
        except (sqlite3.Error, OSError) as exc:
            raise PersonaStoreUnavailable() from exc
        return self._connection

    def __exit__(self, exc_type, exc, tb) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            if exc_type is None:
                connection.commit()
            else:
                connection.rollback()
        except sqlite3.Error:
            pass
        finally:
            connection.close()


class PersonaService:
    """人格版本生命周期：draft→publish→activate→rollback（CAS+哈希+权限门）。

    通用版本化内核：``publish_role``/``publish_validator``/错误类三个扩展点
    供同构资源（worldbook 等）复用同一套 CAS/不可变/损坏隔离机制——
    persona 缺省 super_admin 发布；worldbook 等由子类覆写（见 worldbook_service）。
    """

    permission_error: type[Exception] = PersonaPermissionError
    validation_error: type[Exception] = PersonaValidationError

    def __init__(
        self,
        store: VersionedResourceStore,
        *,
        clock: Callable[[], str] = _utc_now,
        content_max_chars: int = DEFAULT_CONTENT_MAX_CHARS,
        publish_role: str = ROLE_SUPER_ADMIN,
        publish_validator: Callable[[str, str], None] | None = None,
    ) -> None:
        self.store = store
        self._clock = clock
        self._content_max_chars = int(content_max_chars)
        self._publish_role = str(publish_role)
        self._publish_validator = publish_validator
        store.ensure_schema()

    # ------------------------------------------------------------------ 权限

    def _require(self, roles: list[str] | tuple[str, ...], needed: str,
                 action: str) -> None:
        roleset = {str(r) for r in roles}
        if needed == ROLE_ADMIN and not (roleset & {ROLE_ADMIN, ROLE_SUPER_ADMIN}):
            raise self.permission_error(f"{action} 需要 admin 及以上角色")
        if needed == ROLE_SUPER_ADMIN and ROLE_SUPER_ADMIN not in roleset:
            # guide §9：仅超管发布人格——普通管理员不可发布/激活/回滚核心人格。
            raise self.permission_error(f"{action} 仅 super_admin 可执行")

    # ------------------------------------------------------------------ 生命周期

    def draft(
        self,
        resource_id: str,
        content: str,
        *,
        actor: str,
        roles: list[str],
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """写/覆写工作稿（admin+）。expected_version=CAS 基准（最新已发布版本）。"""
        self._require(roles, ROLE_ADMIN, "draft")
        content = self._validate_content(content)
        latest = self.store.latest_version(resource_id)
        if expected_version is not None and int(expected_version) != latest:
            raise PersonaVersionConflict(
                f"expected_version={expected_version} != 最新已发布版本 {latest}"
            )
        now = self._clock()
        self.store.upsert_draft(resource_id, content, actor, now, latest)
        return {
            "resource_id": resource_id,
            "status": "draft",
            "base_version": latest,
            "updated_by": actor,
            "updated_at": now,
        }

    def publish(
        self,
        resource_id: str,
        *,
        actor: str,
        roles: list[str],
        expected_version: int,
    ) -> dict[str, Any]:
        """校验草稿→落不可变版本+sha256 快照（权限=CAS 保护下的发布角色）。"""
        self._require(roles, self._publish_role, "publish")
        draft = self.store.get_draft(resource_id)
        if draft is None:
            raise PersonaNotFoundError(f"{resource_id} 无待发布草稿")
        content = self._validate_content(str(draft["content"]))
        if self._publish_validator is not None:
            # 资源专属校验（worldbook 引用图/预算等）——失败不产生版本。
            self._publish_validator(resource_id, content)
        digest = sha256_text(content)
        now = self._clock()
        store = self.store
        try:
            # 单事务内比对+插入：CAS 与版本落库原子完成（并发发布只成功一个）。
            with store._scoped() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    f"SELECT MAX(version) AS v FROM {store.tables['versions']} "
                    "WHERE resource_id=?",
                    (resource_id,),
                ).fetchone()
                latest = int(row["v"] or 0)
                if int(expected_version) != latest:
                    raise PersonaVersionConflict(
                        f"expected_version={expected_version} != "
                        f"最新已发布版本 {latest}"
                    )
                conn.execute(
                    f"INSERT INTO {store.tables['versions']}"
                    "(resource_id, version, content, content_sha256, published_by,"
                    " published_at) VALUES(?,?,?,?,?,?)",
                    (resource_id, latest + 1, content, digest, actor, now),
                )
        except sqlite3.IntegrityError as exc:
            # 版本号竞态落空（并发发布已占号）→ 显式冲突，绝不静默覆盖。
            raise PersonaVersionConflict(
                f"{resource_id} v{latest + 1} 已被并发发布占用"
            ) from exc
        self.store.delete_draft(resource_id)
        return {
            "resource_id": resource_id,
            "status": "published",
            "version": latest + 1,
            "content_sha256": digest,
            "published_by": actor,
            "published_at": now,
        }

    def activate(
        self,
        resource_id: str,
        version: int,
        *,
        actor: str,
        roles: list[str],
    ) -> dict[str, Any]:
        """把 active 指针拨到已发布版本（权限=生命周期特权角色）。"""
        self._require(roles, self._publish_role, "activate")
        row = self.store.get_version(resource_id, version)
        if row is None:
            raise PersonaNotFoundError(f"{resource_id} v{version} 不存在")
        # 激活前复核哈希：损坏版本不允许成为 active（证据已留、显式报错）。
        if sha256_text(str(row["content"])) != str(row["content_sha256"]):
            self._quarantine(resource_id, int(version), row)
            raise self.validation_error(
                f"{resource_id} v{version} 哈希不符，已隔离并拒绝激活"
                "（证据见 quarantine 表）"
            )
        revision = self.store.set_active(resource_id, int(version), actor,
                                         self._clock())
        return {
            "resource_id": resource_id,
            "active_version": int(version),
            "persona_revision": revision,
            "activated_by": actor,
        }

    def rollback(
        self,
        resource_id: str,
        to_version: int,
        *,
        actor: str,
        roles: list[str],
    ) -> dict[str, Any]:
        """回滚=按目标版本内容新增一版并激活（正式版本不可变，历史保留）。"""
        self._require(roles, self._publish_role, "rollback")
        target = self.store.get_version(resource_id, to_version)
        if target is None:
            raise PersonaNotFoundError(f"{resource_id} v{to_version} 不存在")
        content = str(target["content"])
        digest = sha256_text(content)
        if digest != str(target["content_sha256"]):
            self._quarantine(resource_id, int(to_version), target)
            raise self.validation_error(
                f"{resource_id} v{to_version} 哈希不符，拒绝作为回滚源（证据已留）"
            )
        new_version = self.store.latest_version(resource_id) + 1
        now = self._clock()
        self.store.insert_published(
            resource_id, new_version, content, digest, actor, now
        )
        revision = self.store.set_active(resource_id, new_version, actor, now)
        return {
            "resource_id": resource_id,
            "status": "rollback",
            "rolled_back_from": int(to_version),
            "version": new_version,
            "persona_revision": revision,
            "content_sha256": digest,
        }

    # ------------------------------------------------------------------ 读出/注入出口

    def load_active(self, resource_id: str) -> PersonaLoad:
        """加载 active 版本；哈希不符→拒载+隔离留证+回退上一好版本。"""
        state = self.store.get_state(resource_id)
        if state is None:
            raise PersonaNotFoundError(f"{resource_id} 未激活任何版本")
        quarantines: list[dict[str, Any]] = []
        active_version = int(state["active_version"])
        current = self.store.get_version(resource_id, active_version)
        if current is not None:
            if sha256_text(str(current["content"])) == str(current["content_sha256"]):
                return self._to_load(resource_id, state, current, quarantines)
            quarantines.append(
                self._quarantine(resource_id, active_version, current)
            )
            logger.error(
                "persona hash mismatch: resource=%s version=%s expected=%s "
                "actual=%s — 已隔离并回退最近完好版本",
                resource_id,
                active_version,
                current["content_sha256"],
                quarantines[-1]["actual_sha256"],
            )
        # 回退扫描：从新到旧找第一个哈希完好的已发布版本（不能抹证据）。
        for row in self.store.versions_desc(resource_id):
            if sha256_text(str(row["content"])) == str(row["content_sha256"]):
                revision = self.store.set_active(
                    resource_id, int(row["version"]), FALLBACK_ACTOR, self._clock()
                )
                fallback_state = dict(state)
                fallback_state["active_version"] = int(row["version"])
                fallback_state["persona_revision"] = revision
                # degraded=True（_to_load 按 quarantines 非空判定）。
                return self._to_load(resource_id, fallback_state, row, quarantines)
        self.store.mark_quarantined(resource_id, "all_versions_corrupted")
        raise PersonaStoreUnavailable(
            f"{resource_id} 全部已发布版本哈希不符，拒绝注入（证据见 quarantine 表）"
        )

    def build_core_injection(self, resource_id: str) -> dict[str, Any]:
        """人格核心唯一出站路径：只供已发布+哈希复核内容，带溯源。"""
        load = self.load_active(resource_id)
        return {
            "channel": "persona_core",
            "source": "version_store",
            "resource_id": load.resource_id,
            "version": load.version,
            "persona_revision": load.persona_revision,
            "content_sha256": load.content_sha256,
            "degraded": load.degraded,
            "content": load.content,
        }

    # ------------------------------------------------------------------ 查询面

    def get_state(self, resource_id: str) -> dict[str, Any]:
        state = self.store.get_state(resource_id)
        if state is None:
            raise PersonaNotFoundError(resource_id)
        return state

    def list_versions(self, resource_id: str) -> list[dict[str, Any]]:
        return [
            {
                "version": int(row["version"]),
                "content_sha256": row["content_sha256"],
                "published_by": row["published_by"],
                "published_at": row["published_at"],
            }
            for row in self.store.versions_desc(resource_id)
        ]

    def published_ids(self) -> list[str]:
        return self.store.published_ids()

    def quarantine_records(self, resource_id: str) -> list[dict[str, Any]]:
        return self.store.quarantine_records(resource_id)

    # ------------------------------------------------------------------ 内部

    def _validate_content(self, content: str) -> str:
        if not isinstance(content, str):
            raise self.validation_error("人格核心内容必须是文本")
        if not content.strip():
            raise self.validation_error("人格核心内容为空，拒绝入库")
        if len(content) > self._content_max_chars:
            raise self.validation_error(
                f"人格核心内容超长（{len(content)} > {self._content_max_chars}）"
            )
        if "\x00" in content:
            raise self.validation_error("人格核心内容含 NUL 字节，拒绝入库")
        return content

    def _quarantine(
        self, resource_id: str, version: int, row: dict[str, Any]
    ) -> dict[str, Any]:
        actual = sha256_text(str(row["content"]))
        detected_at = self._clock()
        self.store.insert_quarantine(
            resource_id,
            int(version),
            str(row["content_sha256"]),
            actual,
            detected_at,
            "hash_mismatch",
        )
        self.store.mark_quarantined(resource_id, f"hash_mismatch@v{version}")
        return {
            "resource_id": resource_id,
            "version": int(version),
            "expected_sha256": str(row["content_sha256"]),
            "actual_sha256": actual,
            "detected_at": detected_at,
            "detail": "hash_mismatch",
        }

    @staticmethod
    def _to_load(
        resource_id: str,
        state: dict[str, Any],
        row: dict[str, Any],
        quarantines: list[dict[str, Any]],
    ) -> PersonaLoad:
        return PersonaLoad(
            resource_id=resource_id,
            content=str(row["content"]),
            version=int(row["version"]),
            content_sha256=str(row["content_sha256"]),
            persona_revision=int(state["persona_revision"]),
            degraded=bool(quarantines),
            quarantine=tuple(quarantines),
        )


def build_persona_service(
    db_path: str | Path | None = None,
    *,
    clock: Callable[[], str] | None = None,
) -> PersonaService:
    """装配入口：缺省路径经 runtime_path 重映射到 Runtime data/（不入源码树）。"""
    if db_path is None:
        from scripts.runtime_paths import runtime_path

        db_path = runtime_path(DEFAULT_DB_PATH)
    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    return PersonaService(VersionedResourceStore(db_path, prefix="persona"), **kwargs)
