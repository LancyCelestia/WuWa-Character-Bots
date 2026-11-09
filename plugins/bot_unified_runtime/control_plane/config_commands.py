"""结构化配置命令收件箱与回执（W1/W2/W3）：面板提交、Bot 消费、可核 CAS。

本模块只做三件事，别的一律不做：

- ``SQLiteConfigCommandStore``：与配置 backend **同一个库文件**里的新表
  ``config_commands``（不新建第二调度器、不打开第二本账）。一行 = 一笔待执行/
  已执行的 ``set``/``reset`` 命令，带幂等键、CAS 期望版本、可信主体
  （subject+roles）、scope、TTL、状态、租约与回执。
- ``ConfigCommandGateway``：面板侧唯一提交口。**只登记、不执行**；不持有
  ``ConfigControlService``，所以「提交即落库」这条路在结构上不存在。
- ``ConfigCommandConsumer``：Bot 侧唯一执行口。复用现成
  ``ConfigControlService``（其写腿自 S-G2-THROAT 起已裹 ``settings_gate`` 唯一裁决点）
  逐条消费，把 ``applied``/``needs_consent``/``conflict``/``failed``/``expired``/``unknown``
  回写。门缺席或总闸关 ⇒ 本消费者**拒绝落库**（fail-closed），绝不退回旧直写。

边界（与操作包逐条对应）
----
- 拒 secret 键（``is_sensitive``）、未登记/冻结键（``normalize_key(writable=True)``）、
  空 actor、空幂等键；值只存非 secret 的结构化原始值，DTO 出口再过
  ``redact_public_data``。
- 幂等：同 ``(instance, idempotency_key)`` 重复提交返回**同一笔**命令，不写第二行；
  已 applied 的命令被重放也只回同一条，不二次执行。
- 多消费者：租约 + owner CAS 抢单，``complete`` 也要 owner 匹配；并发消费者只有一个
  能拿到同一笔。
- 崩溃留下的过期租约**不自动盲重放**：``attempts >= 1`` 时落 ``unknown`` 并停手
  （本模块不声称 exactly-once——写与回执之间没有事务，宁可报 unknown 让人核对）。
- ``needs_consent`` 是**可重试**态：批准凭证住在 Bot 进程内同一枚门对象上，消费者
  用命令里存的同一 ``actor_subject``/值/版本重试才能命中绑定（不是「批就执行」）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .auth import Principal
from .config_store import (
    SQLiteConfigStateStore,
    is_sensitive,
    normalize_key,
    public_value,
    redact_public_data,
    validate_version,
)
from .services import ControlServiceError

__all__ = [
    "ACTION_REQUEST_TABLE",
    "COMMAND_TABLE",
    "ActionRequestConsumer",
    "CommandStatus",
    "ConfigCommandConsumer",
    "ConfigCommandConsumerRunner",
    "ConfigCommandGateway",
    "HostConfigCommandGateway",
    "SQLiteActionRequestStore",
    "SQLiteConfigCommandStore",
    "build_action_request_runner",
    "build_consumer_runner",
    "next_poll_delay",
    "public_command",
]

DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_POLL_MAX_INTERVAL_SECONDS = 5.0

#: 命令表名（与配置 backend 同库、不同表；不碰既有三张表）。
COMMAND_TABLE = "config_commands"

#: 动作申请表名：与 ``config_commands`` **同一个库文件**（不新开第二本账），
#: 只装「面板申请、Bot 侧只读」这类不可由面板直接执行的意图。
ACTION_REQUEST_TABLE = "action_requests"

DEFAULT_COMMAND_TTL_SECONDS = 3600
DEFAULT_LEASE_SECONDS = 30
#: 重启申请的默认时效：过窗即 ``expired``，不再提醒（旧申请不该在半小时后突然喊人）。
DEFAULT_REQUEST_TTL_SECONDS = 900

#: 幂等键形（与 ``api.protocol.ActionExecutePayload`` 同一族，避免面板两套校验）。
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")

_STATUS_PENDING = "pending"
_STATUS_LEASED = "leased"
_STATUS_APPLIED = "applied"
_STATUS_NEEDS_CONSENT = "needs_consent"
_STATUS_CONFLICT = "conflict"
_STATUS_FAILED = "failed"
_STATUS_EXPIRED = "expired"
_STATUS_UNKNOWN = "unknown"

#: 消费者可回写的终态/中间态全集（``leased`` 由 ``claim_next`` 独占，不由 ``complete`` 写）。
_COMMAND_STATUSES = frozenset(
    {
        _STATUS_PENDING,
        _STATUS_LEASED,
        _STATUS_APPLIED,
        _STATUS_NEEDS_CONSENT,
        _STATUS_CONFLICT,
        _STATUS_FAILED,
        _STATUS_EXPIRED,
        _STATUS_UNKNOWN,
    }
)
#: 可再次被消费者抢单的态（``needs_consent`` 批完同参重试就是靠这一格接上的）。
_RETRYABLE_STATUSES = (_STATUS_PENDING, _STATUS_NEEDS_CONSENT)


class CommandStatus:
    """状态代号唯一真身（禁在别处再抄字面量）。"""

    PENDING = _STATUS_PENDING
    LEASED = _STATUS_LEASED
    APPLIED = _STATUS_APPLIED
    NEEDS_CONSENT = _STATUS_NEEDS_CONSENT
    CONFLICT = _STATUS_CONFLICT
    FAILED = _STATUS_FAILED
    EXPIRED = _STATUS_EXPIRED
    UNKNOWN = _STATUS_UNKNOWN

    ALL = _COMMAND_STATUSES


def _utc_stamp(moment: datetime) -> str:
    """固定宽度 UTC 串：库内比较走字典序，等价于时间序（禁用本地时区裸 isoformat）。"""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()[:16]


def _request_fingerprint(
    *,
    action: str,
    key: str,
    value: Any,
    expected_version: int,
    actor_subject: str,
    actor_roles: Any,
    scope: str,
) -> str:
    """一次提交请求的**严格绑定**指纹（幂等键之外的全部请求内容）。

    幂等键只保证「同一件事重复提交返回同一行」；**不能**用它当「谁都能拿这行」的通行证。
    指纹覆盖 actor/roles/action/key/value/expected_version/scope ⇒ 换主体、换值、换版本、
    换 scope 都是**另一件事**，同键也必须拒（409），绝不返回他人 DTO。
    """
    payload = {
        "action": action,
        "key": key,
        "expected_version": expected_version,
        "actor": str(actor_subject or "").strip(),
        "roles": sorted(str(role) for role in (actor_roles or ())),
        "scope": scope,
        "value": None if action == "reset" else _fingerprint(value),
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()[:32]


class SQLiteConfigCommandStore:
    """命令收件箱/回执的事务存储；只操作调用方显式指定的库文件。

    与 ``SQLiteConfigStateStore`` 同库（同一路径、同一 instance 命名空间）但
    **独立一张表**：配置覆盖的 CAS 版本与命令的幂等键互不干涉，命令失败不会
    顶动配置版本戳。
    """

    def __init__(self, path: str | Path, instance: str = "default") -> None:
        if not str(path).strip() or str(path) == ":memory:":
            raise ValueError("命令收件箱需要显式文件路径")
        if not isinstance(instance, str) or not instance.strip():
            raise ValueError("实例名不能为空")
        self.path = Path(path).expanduser().resolve()
        self.instance = instance
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(write=True) as conn:
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {COMMAND_TABLE} (
                command_id TEXT PRIMARY KEY,
                instance TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('set', 'reset')),
                key TEXT NOT NULL,
                value_json TEXT,
                expected_version INTEGER NOT NULL,
                actor_subject TEXT NOT NULL,
                actor_roles TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                lease_owner TEXT NOT NULL DEFAULT '',
                lease_expires_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                result_json TEXT NOT NULL DEFAULT '{{}}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                UNIQUE(instance, idempotency_key))"""
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{COMMAND_TABLE}_queue "
                f"ON {COMMAND_TABLE}(instance, status, created_at)"
            )

    @classmethod
    def from_config_store(cls, backend: SQLiteConfigStateStore) -> SQLiteConfigCommandStore:
        """复用配置 backend 的库文件与实例名（同库新表，不新建第二本账）。"""
        return cls(backend.path, getattr(backend, "instance", "default"))

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _now(self, clock: Any = None) -> datetime:
        if clock is not None:
            return clock()
        return datetime.now(timezone.utc)

    # ---- 提交（面板侧唯一入口的持久化腿）--------------------------------

    def submit(
        self,
        *,
        action: str,
        key: str,
        value: Any = None,
        expected_version: int,
        actor_subject: str,
        actor_roles: tuple[str, ...],
        idempotency_key: str,
        scope: str = "",
        ttl_seconds: int = DEFAULT_COMMAND_TTL_SECONDS,
        clock: Any = None,
    ) -> tuple[dict[str, Any], bool]:
        """登记一笔命令；返回 ``(DTO, replay)``，``replay=True`` 表示命中既有幂等键。"""
        if action not in {"set", "reset"}:
            raise ControlServiceError("config_command_invalid", "只支持 set/reset 命令。", 422)
        validate_version(expected_version)
        if not isinstance(actor_subject, str) or not actor_subject.strip():
            raise ControlServiceError("config_command_actor_required", "命令必须带可信主体。", 422)
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.match(idempotency_key):
            raise ControlServiceError("config_command_idempotency_invalid", "幂等键形不正确。", 422)
        if not isinstance(scope, str) or len(scope) > 128:
            raise ControlServiceError("config_command_invalid", "scope 无效。", 422)
        if not isinstance(actor_roles, tuple) or any(not isinstance(r, str) for r in actor_roles):
            raise ControlServiceError("config_command_invalid", "角色集合无效。", 422)
        if type(ttl_seconds) is not int or ttl_seconds < 1:
            raise ControlServiceError("config_command_invalid", "TTL 必须为正整数秒。", 422)
        try:
            normalized_key = normalize_key(key, writable=True)
        except KeyError:
            raise ControlServiceError("config_not_found", "未找到对应配置键。", 404) from None
        except (ValueError, AttributeError, TypeError):
            raise ControlServiceError(
                "config_not_hot_reloadable", "该配置尚无安全热更新路径，请修改 .env 并重启。", 409
            ) from None
        if is_sensitive(normalized_key):
            # 秘密配置一律不登记：命令面是本仓唯一会把值落进「可被面板读到」的表，
            # 秘密值没有安全的回显口径，直接拒。
            raise ControlServiceError(
                "config_command_secret_refused", "秘密配置不允许经命令面提交。", 403
            )
        if action == "set":
            if value is None:
                raise ControlServiceError("config_invalid", "set 命令必须带值。", 422)
            try:
                value_json: str | None = _json(value)
            except (TypeError, ValueError):
                raise ControlServiceError("config_invalid", "命令值无法序列化。", 422) from None
        else:
            value_json = None
        now = self._now(clock)
        created = _utc_stamp(now)
        expires = _utc_stamp(now + timedelta(seconds=ttl_seconds))
        command_id = f"cmd_{uuid.uuid4().hex}"
        with self._lock, self._transaction(write=True) as conn:
            existing = conn.execute(
                f"SELECT * FROM {COMMAND_TABLE} WHERE instance=? AND idempotency_key=?",
                (self.instance, idempotency_key),
            ).fetchone()
            if existing is not None:
                # 幂等命中≠无条件复用：请求内容（actor/roles/action/key/value/version/scope）
                # 必须逐项一致，否则 409，绝不把别人那一行的 DTO 交出去。
                self._assert_idempotent_match(
                    existing, action=action, key=normalized_key, value=value,
                    expected_version=expected_version, actor_subject=actor_subject,
                    actor_roles=actor_roles, scope=scope,
                )
                return self._dto(existing), True
            try:
                conn.execute(
                    f"""INSERT INTO {COMMAND_TABLE}
                    (command_id, instance, idempotency_key, action, key, value_json,
                     expected_version, actor_subject, actor_roles, scope, status,
                     lease_owner, lease_expires_at, attempts, result_json,
                     created_at, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', NULL, 0, '{{}}', ?, ?, ?)""",
                    (
                        command_id, self.instance, idempotency_key, action, normalized_key,
                        value_json, expected_version, actor_subject.strip(),
                        _json(list(actor_roles)), scope, _STATUS_PENDING,
                        created, created, expires,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    f"SELECT * FROM {COMMAND_TABLE} WHERE instance=? AND idempotency_key=?",
                    (self.instance, idempotency_key),
                ).fetchone()
                if existing is None:  # pragma: no cover - 竞态窗口已由 BEGIN IMMEDIATE 关掉
                    raise
                self._assert_idempotent_match(
                    existing, action=action, key=normalized_key, value=value,
                    expected_version=expected_version, actor_subject=actor_subject,
                    actor_roles=actor_roles, scope=scope,
                )
                return self._dto(existing), True
            row = conn.execute(
                f"SELECT * FROM {COMMAND_TABLE} WHERE command_id=?", (command_id,)
            ).fetchone()
        return self._dto(row), False

    def _assert_idempotent_match(self, row: sqlite3.Row, *, action: str, key: str,
                                 value: Any, expected_version: int, actor_subject: str,
                                 actor_roles: Any, scope: str) -> None:
        stored_value = None if row["value_json"] is None else json.loads(row["value_json"])
        incoming = _request_fingerprint(
            action=action, key=key, value=value, expected_version=expected_version,
            actor_subject=actor_subject, actor_roles=actor_roles, scope=scope,
        )
        stored = _request_fingerprint(
            action=row["action"], key=row["key"], value=stored_value,
            expected_version=row["expected_version"], actor_subject=row["actor_subject"],
            actor_roles=json.loads(row["actor_roles"]), scope=row["scope"],
        )
        if incoming != stored:
            # 同一幂等键、不同请求内容＝另一件事：拒绝，且**不回显**既有行的任何字段
            # （防跨主体拿到别人的 DTO）。
            raise ControlServiceError(
                "config_command_idempotency_conflict",
                "同一幂等键的请求内容与已登记命令不一致。", 409,
            )

    # ---- 读面 -------------------------------------------------------------

    def get(self, command_id: str) -> dict[str, Any] | None:
        if not isinstance(command_id, str) or not command_id.strip():
            return None
        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT * FROM {COMMAND_TABLE} WHERE instance=? AND command_id=?",
                (self.instance, command_id.strip()),
            ).fetchone()
        return None if row is None else self._dto(row)

    def list_for_actor(self, actor_subject: str, *, limit: int = 50) -> list[dict[str, Any]]:
        if not isinstance(actor_subject, str) or not actor_subject.strip():
            return []
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ControlServiceError("config_command_invalid", "limit 必须为 1..500。", 422)
        with self._transaction() as conn:
            rows = conn.execute(
                f"""SELECT * FROM {COMMAND_TABLE} WHERE instance=? AND actor_subject=?
                ORDER BY created_at DESC LIMIT ?""",
                (self.instance, actor_subject.strip(), limit),
            ).fetchall()
        return [self._dto(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._transaction() as conn:
            rows = conn.execute(
                f"SELECT status, COUNT(*) AS n FROM {COMMAND_TABLE} WHERE instance=? GROUP BY status",
                (self.instance,),
            ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}

    # ---- 消费（Bot 侧唯一入口的持久化腿）--------------------------------

    def claim_next(
        self,
        *,
        owner: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        limit: int = 1,
        needs_consent_backoff_seconds: float = 5.0,
        clock: Any = None,
    ) -> list[dict[str, Any]]:
        """租约抢单：返回本次真正抢到的命令（含租约 owner/到期），别的消费者抢不到。

        公平性（防饿死）：候选按「``pending`` 优先 → ``needs_consent`` 按 ``updated_at``
        轮转」排序；``needs_consent`` 还要过一道**有界 backoff**（默认 5s）才可再抢，
        免得 10 张待批卡每轮把 claim 占满、把新 ``pending`` 永远饿在后面。TTL 不变。
        """
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("owner 不能为空")
        if type(lease_seconds) is not int or lease_seconds < 1:
            raise ValueError("lease_seconds 必须为正整数")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit 必须为 1..50")
        now = self._now(clock)
        now_stamp = _utc_stamp(now)
        lease_until = _utc_stamp(now + timedelta(seconds=lease_seconds))
        consent_cutoff = _utc_stamp(
            now - timedelta(seconds=max(0.0, float(needs_consent_backoff_seconds)))
        )
        claimed: list[dict[str, Any]] = []
        with self._lock, self._transaction(write=True) as conn:
            self._sweep(conn, now_stamp)
            for _ in range(limit):
                row = conn.execute(
                    f"""SELECT * FROM {COMMAND_TABLE} WHERE instance=?
                    AND expires_at > ?
                    AND (status = '{_STATUS_PENDING}'
                         OR (status = '{_STATUS_NEEDS_CONSENT}' AND updated_at <= ?))
                    ORDER BY CASE status WHEN '{_STATUS_PENDING}' THEN 0 ELSE 1 END,
                             updated_at
                    LIMIT 1""",
                    (self.instance, now_stamp, consent_cutoff),
                ).fetchone()
                if row is None:
                    break
                cursor = conn.execute(
                    f"""UPDATE {COMMAND_TABLE} SET status='{_STATUS_LEASED}', lease_owner=?,
                    lease_expires_at=?, attempts=attempts+1, updated_at=?
                    WHERE command_id=? AND instance=?
                    AND status IN ('{_STATUS_PENDING}', '{_STATUS_NEEDS_CONSENT}')""",
                    (owner.strip(), lease_until, now_stamp, row["command_id"], self.instance),
                )
                if cursor.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE 下不会发生
                    continue
                fresh = conn.execute(
                    f"SELECT * FROM {COMMAND_TABLE} WHERE command_id=?", (row["command_id"],)
                ).fetchone()
                claimed.append(self._dto(fresh))
        return claimed

    def complete(
        self,
        command_id: str,
        *,
        owner: str,
        status: str,
        result: dict[str, Any] | None = None,
        clock: Any = None,
    ) -> bool:
        """回写终态/中间态；owner CAS——不是自己抢到的单回写不了。"""
        if status not in _COMMAND_STATUSES or status == _STATUS_LEASED:
            raise ValueError(f"complete 不接受的状态：{status!r}")
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("owner 不能为空")
        try:
            result_json = _json(redact_public_data(result or {}))
        except (TypeError, ValueError):
            result_json = _json({"error": "result_not_serializable"})
        now_stamp = _utc_stamp(self._now(clock))
        with self._lock, self._transaction(write=True) as conn:
            cursor = conn.execute(
                f"""UPDATE {COMMAND_TABLE} SET status=?, result_json=?, lease_owner='',
                lease_expires_at=NULL, updated_at=?
                WHERE command_id=? AND instance=? AND status='{_STATUS_LEASED}'
                AND lease_owner=?""",
                (status, result_json, now_stamp, str(command_id).strip(), self.instance, owner.strip()),
            )
            return cursor.rowcount == 1

    def _sweep(self, conn: sqlite3.Connection, now_stamp: str) -> None:
        """抢单前清理：TTL 到期的落 ``expired``；过期租约按 attempts 分「回到队列」/``unknown``。

        ``attempts >= 1`` 的过期租约 = 有消费者动过手却没了回执。**不盲重放**：无法区分
        「还没写就崩」与「写完才崩」，宁可落 ``unknown`` 让人核对（不假 exactly-once）。
        """
        conn.execute(
            f"""UPDATE {COMMAND_TABLE} SET status='{_STATUS_EXPIRED}', lease_owner='',
            lease_expires_at=NULL, updated_at=?
            WHERE instance=? AND status IN ('{_STATUS_PENDING}', '{_STATUS_NEEDS_CONSENT}', '{_STATUS_LEASED}')
            AND expires_at <= ?""",
            (now_stamp, self.instance, now_stamp),
        )
        conn.execute(
            f"""UPDATE {COMMAND_TABLE} SET status='{_STATUS_UNKNOWN}', lease_owner='',
            lease_expires_at=NULL, updated_at=?
            WHERE instance=? AND status='{_STATUS_LEASED}' AND attempts >= 1
            AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?""",
            (now_stamp, self.instance, now_stamp),
        )
        conn.execute(
            f"""UPDATE {COMMAND_TABLE} SET status='{_STATUS_PENDING}', lease_owner='',
            lease_expires_at=NULL, updated_at=?
            WHERE instance=? AND status='{_STATUS_LEASED}' AND attempts = 0
            AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?""",
            (now_stamp, self.instance, now_stamp),
        )

    # ---- DTO --------------------------------------------------------------

    def _dto(self, row: sqlite3.Row) -> dict[str, Any]:
        """内部表示：**保留原始 value**（消费者要用它执行），不做字段名级脱敏。

        面板出口走 ``public_command``——本模块刻意不把 ``redact_public_data`` 套在整个
        DTO 上：它按**字段名**判凭证（``key``/``idempotency_key`` 命中 ``_KEY`` 后缀会被
        整格涂销），套上去会把配置键名本身涂掉、消费者拿到 ``[redacted]`` 当场执行失败。
        """
        value = None if row["value_json"] is None else json.loads(row["value_json"])
        return {
            "command_id": row["command_id"],
            "instance": row["instance"],
            "idempotency_key": row["idempotency_key"],
            "action": row["action"],
            "key": row["key"],
            "value": value,
            "value_fingerprint": None if value is None else _fingerprint(value),
            "expected_version": row["expected_version"],
            "actor_subject": row["actor_subject"],
            "actor_roles": list(json.loads(row["actor_roles"])),
            "scope": row["scope"],
            "status": row["status"],
            "attempts": row["attempts"],
            "result": json.loads(row["result_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
        }


def public_command(dto: dict[str, Any]) -> dict[str, Any]:
    """面板出口投影：值走 ``public_value`` 脱敏（路径/凭证形态涂销），键名保持可读。

    秘密配置在提交时已被拒，所以这里的值本就非秘密；仍过一遍 ``public_value`` 是
    纵深防御（防有人把 ``sk-``/盘符路径塞进普通键的值里）。
    """
    key = str(dto.get("key") or "")
    value = dto.get("value")
    projected = {**dto}
    if value is not None:
        projected["value"] = public_value(key, value)["value"]
    return projected


class ConfigCommandGateway:
    """面板侧唯一提交口：只登记与读状态，**不执行**、不持有 ConfigControlService。

    面板读自己的命令状态（``subject`` 匹配）或超管读全部；这里**没有**批准接口——
    批准永远走 bot 现成的 ``bot.consent`` 命令面。
    """

    def __init__(self, store: SQLiteConfigCommandStore) -> None:
        self.store = store

    def submit(
        self,
        *,
        principal: Principal,
        key: str,
        value: Any = None,
        reset: bool = False,
        expected_version: int,
        idempotency_key: str,
        scope: str = "",
        ttl_seconds: int = DEFAULT_COMMAND_TTL_SECONDS,
    ) -> dict[str, Any]:
        if type(reset) is not bool:
            raise ControlServiceError("config_command_invalid", "reset 必须为布尔值。", 422)
        dto, replay = self.store.submit(
            action="reset" if reset else "set",
            key=key,
            value=None if reset else value,
            expected_version=expected_version,
            actor_subject=getattr(principal, "subject", ""),
            actor_roles=tuple(getattr(principal, "roles", ()) or ()),
            idempotency_key=idempotency_key,
            scope=scope,
            ttl_seconds=ttl_seconds,
        )
        return {**public_command(dto), "idempotent_replay": replay}

    def status(self, *, principal: Principal, command_id: str) -> dict[str, Any]:
        dto = self.store.get(command_id)
        if dto is None:
            raise ControlServiceError("config_command_not_found", "未找到该命令。", 404)
        roles = tuple(getattr(principal, "roles", ()) or ())
        if dto["actor_subject"] != getattr(principal, "subject", "") and "super_admin" not in roles:
            raise ControlServiceError("forbidden", "只能读取本人提交的命令。", 403)
        return public_command(dto)

    def list_own(self, *, principal: Principal, limit: int = 50) -> list[dict[str, Any]]:
        return [
            public_command(dto)
            for dto in self.store.list_for_actor(getattr(principal, "subject", ""), limit=limit)
        ]


class HostConfigCommandGateway:
    """嵌入宿主的命令面：命令由**本进程当场执行**，不排队、不编造记录。

    为什么不能直接复用 ``ConfigCommandGateway``：那条路只登记、等 Bot 侧消费者
    （``ConfigCommandConsumerRunner``）来取；嵌入宿主里没有第二个消费者进程
    （Bot 自己就是执行方），登记后没人取 ＝「设置存不了」换一种形式复发。
    故本实现把写当场交给 ``ConfigControlService``——授权、CAS 版本、审计、同意门
    一条不少（与直写腿同一个咽喉），结果作为回执直接返回。

    读面诚实：宿主内不存在待执行队列 ⇒ ``list_own`` 恒空、``status`` 404
    （不往库里伪造「成功命令」行）。
    """

    def __init__(self, service: Any) -> None:
        self.service = service

    def submit(
        self,
        *,
        principal: Principal,
        key: str,
        value: Any = None,
        reset: bool = False,
        expected_version: int,
        idempotency_key: str,
        scope: str = "",
        ttl_seconds: int = DEFAULT_COMMAND_TTL_SECONDS,
    ) -> dict[str, Any]:
        if type(reset) is not bool:
            raise ControlServiceError("config_command_invalid", "reset 必须为布尔值。", 422)
        # 命令号走请求头那串幂等键的**独立命名空间**：宿主内不落命令表，但回执、审计
        # request_id 与前端「这一笔」必须能对上，且不与表里的 command_id 撞形。
        command_id = f"host-{uuid.uuid4().hex}"
        common = {
            "principal": principal,
            "expected_version": expected_version,
            "request_id": command_id,
            "session_key": str(scope or ""),
        }
        if reset:
            outcome = self.service.reset(key, **common)
        else:
            outcome = self.service.set(key, value, **common)
        return {
            "command_id": command_id,
            "status": "applied",
            "action": "reset" if reset else "set",
            "key": outcome.get("key", key) if isinstance(outcome, dict) else key,
            "value": outcome.get("value") if isinstance(outcome, dict) else None,
            "version": outcome.get("version") if isinstance(outcome, dict) else None,
            "expected_version": expected_version,
            "idempotent_replay": False,
        }

    def status(self, *, principal: Principal, command_id: str) -> dict[str, Any]:
        raise ControlServiceError(
            "config_command_not_found",
            "本宿主内配置写为直执行，不存在排队的命令记录。",
            404,
        )

    def list_own(self, *, principal: Principal, limit: int = 50) -> list[dict[str, Any]]:
        return []


class ConfigCommandConsumer:
    """Bot 侧唯一执行口：租约抢单 → 走现成 ConfigControlService（内含咽喉门）→ 回写回执。

    fail-closed：门缺席或总闸关 ⇒ **不落库**，落 ``failed``（code=``gate_unavailable``）。
    这与旧「同进程 runtime_attached 直写」是两条腿：那条腿的闸在 HTTP 装配侧由父 app
    显参决定；本消费者只认「门在且开」这一条。
    """

    def __init__(
        self,
        store: SQLiteConfigCommandStore,
        service: Any,
        *,
        owner: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self.store = store
        self.service = service
        self.owner = owner
        self.lease_seconds = lease_seconds

    def _gate_active(self) -> bool:
        getter = getattr(self.service, "_consent_gate", None)
        if not callable(getter):
            return False
        try:
            gate = getter()
        except Exception:  # noqa: BLE001 - 拿不到门＝不能证明能安全落库
            return False
        return bool(gate is not None and getattr(gate, "enabled", False))

    def drain(self, *, limit: int = 10, needs_consent_backoff_seconds: float = 5.0,
              clock: Any = None) -> list[dict[str, Any]]:
        """消费至多 ``limit`` 笔命令，逐条回执；返回本次处理过的命令 DTO。"""
        processed: list[dict[str, Any]] = []
        for command in self.store.claim_next(
            owner=self.owner, lease_seconds=self.lease_seconds, limit=limit,
            needs_consent_backoff_seconds=needs_consent_backoff_seconds, clock=clock,
        ):
            processed.append(self._execute(command))
        return processed

    def _current_version(self) -> int | None:
        backend = getattr(self.service, "backend", None)
        snapshot = getattr(backend, "snapshot", None)
        if not callable(snapshot):
            return None
        try:
            return int(snapshot().version)
        except Exception:  # noqa: BLE001 - 读不到版本＝不拦（交给门/CAS 兜底）
            return None

    def _execute(self, command: dict[str, Any]) -> dict[str, Any]:
        command_id = command["command_id"]
        if not self._gate_active():
            self.store.complete(
                command_id, owner=self.owner, status=_STATUS_FAILED,
                result={"code": "gate_unavailable",
                        "message": "安全执行门未装配或已关闭，命令不落库。"},
            )
            return self.store.get(command_id) or command
        # 版本**先**验证：stale 命令不许把批准凭证吃掉（CAS 冲突之前就拦下，凭证留给
        # 版本正确的同一笔命令）。
        current = self._current_version()
        if current is not None and current != command["expected_version"]:
            self.store.complete(
                command_id, owner=self.owner, status=_STATUS_CONFLICT,
                result={"code": "version_conflict",
                        "message": "命令的期望版本已过期，未消费批准凭证。"},
            )
            return self.store.get(command_id) or command
        principal = Principal(command["actor_subject"], tuple(command["actor_roles"]))
        scope = str(command["scope"] or "")
        approval_context = {
            "command_id": command_id,
            "expected_version": command["expected_version"],
            "scope": scope,
        }
        try:
            if command["action"] == "reset":
                outcome = self.service.reset(
                    command["key"], principal=principal,
                    expected_version=command["expected_version"], request_id=command_id,
                    session_key=scope, approval_context=approval_context,
                )
            else:
                outcome = self.service.set(
                    command["key"], command["value"], principal=principal,
                    expected_version=command["expected_version"], request_id=command_id,
                    session_key=scope, approval_context=approval_context,
                )
        except ControlServiceError as exc:
            status = {
                "consent_required": _STATUS_NEEDS_CONSENT,
                "version_conflict": _STATUS_CONFLICT,
            }.get(exc.code, _STATUS_FAILED)
            self.store.complete(
                command_id, owner=self.owner, status=status,
                result={"code": exc.code, "message": exc.message},
            )
            return self.store.get(command_id) or command
        except Exception as exc:  # noqa: BLE001 - 未知异常不许冒充成功
            self.store.complete(
                command_id, owner=self.owner, status=_STATUS_FAILED,
                result={"code": "command_execution_error", "message": type(exc).__name__},
            )
            return self.store.get(command_id) or command
        self.store.complete(
            command_id, owner=self.owner, status=_STATUS_APPLIED,
            result={"code": "applied", "version": outcome.get("version")},
        )
        return self.store.get(command_id) or command


def next_poll_delay(
    progressed: bool,
    current: float,
    *,
    interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_interval: float = DEFAULT_POLL_MAX_INTERVAL_SECONDS,
) -> float:
    """退避尺（纯函数，可复跑）：有进展回落到 ``interval``，否则指数退避到 ``max_interval``。

    要点：``needs_consent`` 不算进展 ⇒ 待批命令不会被每 200ms 撞门刷账，最小 1s、封顶 5s。
    """
    if progressed:
        return interval
    return min(max_interval, max(interval, current * 2))


class ConfigCommandConsumerRunner:
    """驱动侧消费者轮询：``on_startup`` 起 task、``on_shutdown`` 取消 await。

    契约（与操作包 A 段逐条对应）
    - 不阻塞主链：单次 drain 走 ``asyncio.to_thread``（sqlite 阻塞不许卡事件循环）。
    - 不双注册/重入：``register`` 对同一 driver 幂等；``start`` 见在飞 task 直接返回。
    - 退避：见 ``next_poll_delay``；``needs_consent``/无事可做 → 退避到 5s。
    - 故障：只记一条固定 warning，**不 dump 异常全文**（异常文本可能带值）。
    - 关停：``stop`` 取消并 ``gather`` 回收；重复调用安全。
    """

    def __init__(
        self,
        consumer: Any,
        *,
        interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_interval: float = DEFAULT_POLL_MAX_INTERVAL_SECONDS,
        limit: int = 10,
        needs_consent_backoff_seconds: float = 5.0,
        logger: Any | None = None,
    ) -> None:
        if interval <= 0 or max_interval < interval:
            raise ValueError("轮询间隔无效")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit 必须为 1..50")
        self._consumer = consumer
        self._interval = float(interval)
        self._max_interval = float(max_interval)
        self._limit = limit
        self._needs_consent_backoff = float(needs_consent_backoff_seconds)
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._driver: Any | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    def register(self, driver: Any) -> bool:
        """挂到 driver；同一 driver 重复注册幂等（不双注册）。"""
        if self._driver is not None:
            return self._driver is driver
        self._driver = driver
        driver.on_startup(self.start)
        driver.on_shutdown(self.stop)
        return True

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="config-command-consumer")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _loop(self) -> None:
        delay = self._interval
        while True:
            await asyncio.sleep(delay)
            try:
                processed = await asyncio.to_thread(
                    self._consumer.drain, limit=self._limit,
                    needs_consent_backoff_seconds=self._needs_consent_backoff,
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - 固定告警，异常全文不外泄
                self._log.warning("config command consumer drain failed")
                delay = next_poll_delay(
                    False, delay, interval=self._interval, max_interval=self._max_interval
                )
                continue
            # 🔴 W12-REVIEW 修（P0-2）：**在这里**（＝事件循环线程，await 已返回）
            # 投告警，而不是让 drain 在线程池里投。生产 sink 需要 running loop
            # （`_push_probe_issue` 首行就是 `get_running_loop()`），在工作线程里
            # 必抛 RuntimeError 并被吞 ⇒ 账落了、人永远不会被喊。
            # 消费者若有待喊文本面（`flush_pending_announcements`），在这里清空；
            # 其它消费者没有这个面，`getattr` 兜空即可，行为零变化。
            _flush = getattr(self._consumer, "flush_pending_announcements", None)
            if callable(_flush):
                try:
                    _flush()
                except Exception:  # noqa: BLE001 - 告警是旁路，不能反噬轮询
                    self._log.warning("config command consumer alert flush failed")
            progressed = any(
                row.get("status") not in (_STATUS_NEEDS_CONSENT, _STATUS_PENDING)
                for row in processed
            )
            delay = next_poll_delay(
                progressed, delay, interval=self._interval, max_interval=self._max_interval
            )


def build_consumer_runner(
    store_or_backend: Any,
    service: Any,
    *,
    owner: str | None = None,
    logger: Any | None = None,
    interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_interval: float = DEFAULT_POLL_MAX_INTERVAL_SECONDS,
    limit: int = 10,
    needs_consent_backoff_seconds: float = 5.0,
) -> ConfigCommandConsumerRunner:
    """生产装配口：造消费者并包成 runner。

    收 **store 或 backend** 二者皆可——传 store 时与命令网关**共用同一对象**（同库同实例、
    同一张表），不各造各的。⚠ 传 backend 时本函数会在其库文件上执行
    ``CREATE TABLE IF NOT EXISTS``（源码 DDL）；生产部署/迁移由后续批次负责，本批不执行。
    """
    store = (
        store_or_backend
        if isinstance(store_or_backend, SQLiteConfigCommandStore)
        else SQLiteConfigCommandStore.from_config_store(store_or_backend)
    )
    consumer = ConfigCommandConsumer(
        store, service, owner=owner or f"bot-{os.getpid()}"
    )
    return ConfigCommandConsumerRunner(
        consumer, interval=interval, max_interval=max_interval, limit=limit,
        needs_consent_backoff_seconds=needs_consent_backoff_seconds, logger=logger,
    )


# ---------------------------------------------------------------------------
# 动作申请收件箱（W12 用户裁定 A：面板只写申请，Bot 侧只读+喊人，绝不执行）
#
# 与 ``config_commands`` **同一个 SQLite 文件**（``from_config_store`` 复用路径与实例名），
# 新表而非新库。三点刻意设计：
#
# - 状态只三档：``pending``（面板已提交）→``awaiting_human``（Bot 侧已看到并喊人）/
#   ``expired``（过 TTL 未处理）。**没有** ``running``/``done``：一旦有这两种状态，
#   就会有人忍不住给它接执行器。
# - 本模块零进程控制：消费者只写告警和落状态。``tests/test_restart_request_flow.py``
#   用 AST 扫本文件与 ``_app.py`` 断言不含 ``os.execv``/``os.kill``/``os.system``/
#   ``subprocess``/``psutil``/``signal``/``multiprocessing``。
# - 幂等键 + 主体绑定：同键换主体/换动作＝另一件事，409 且不回显既有行。
# ---------------------------------------------------------------------------

_STATUS_AWAITING_HUMAN = "awaiting_human"

#: 允许经动作申请面落账的意图。只此一项——其它「想让它真的动」的诉求走人工。
SUPPORTED_REQUEST_ACTIONS = frozenset({"restart"})


class SQLiteActionRequestStore:
    """动作申请表：同一库文件、同一实例命名空间，独立一张表。

    ``version`` 是行级 CAS：每次状态迁移 +1，面板侧读到的版本与消费者落状态前
    读到的版本不一致就不写（防面板与 Bot 各改各的）。``result_json`` 只存
    ``{"code": ..., "message": ...}`` 级别的固定文案，永不回显自由文本。
    """

    def __init__(self, path: str | Path, instance: str = "default") -> None:
        if not str(path).strip() or str(path) == ":memory:":
            raise ValueError("动作申请表需要显式文件路径")
        if not isinstance(instance, str) or not instance.strip():
            raise ValueError("实例名不能为空")
        self.path = Path(path).expanduser().resolve()
        self.instance = instance
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(write=True) as conn:
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {ACTION_REQUEST_TABLE} (
                request_id TEXT PRIMARY KEY,
                instance TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                action TEXT NOT NULL,
                actor_subject TEXT NOT NULL,
                actor_roles TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0,
                result_json TEXT NOT NULL DEFAULT '{{}}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                UNIQUE(instance, idempotency_key))"""
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{ACTION_REQUEST_TABLE}_queue "
                f"ON {ACTION_REQUEST_TABLE}(instance, status, created_at)"
            )

    @classmethod
    def from_config_store(
        cls, source: Any
    ) -> SQLiteActionRequestStore:
        """复用配置命令库的**同一个文件**与实例名（禁第二本账）。"""
        path = getattr(source, "path", None)
        if path is None:
            raise ValueError("动作申请表需要带 path 的配置命令库或 backend")
        return cls(path, getattr(source, "instance", "default"))

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _now(self, clock: Any = None) -> datetime:
        return clock() if clock is not None else datetime.now(timezone.utc)

    # ---- 提交（面板侧动作 handler 的唯一落账腿）---------------------------

    def submit(
        self,
        *,
        action: str = "restart",
        actor_subject: str,
        actor_roles: tuple[str, ...],
        idempotency_key: str,
        ttl_seconds: int = DEFAULT_REQUEST_TTL_SECONDS,
        clock: Any = None,
    ) -> tuple[dict[str, Any], bool]:
        """登记一条申请；返回 ``(DTO, replay)``，``replay=True`` 表示命中既有幂等键。"""
        if action not in SUPPORTED_REQUEST_ACTIONS:
            raise ControlServiceError(
                "action_request_invalid", "不支持的动作申请。", 422
            )
        if not isinstance(actor_subject, str) or not actor_subject.strip():
            raise ControlServiceError(
                "action_request_actor_required", "申请必须带可信主体。", 422
            )
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.match(
            idempotency_key
        ):
            raise ControlServiceError(
                "action_request_idempotency_invalid", "幂等键形不正确。", 422
            )
        if not isinstance(actor_roles, tuple) or any(
            not isinstance(role, str) for role in actor_roles
        ):
            raise ControlServiceError("action_request_invalid", "角色集合无效。", 422)
        # 权限门不放宽：申请面仍只认超管。动作层（``ControlActionService._validate``）
        # 已经拦了一道；这里再拦一道，因为本类是公开的存储面，将来任何人绕过动作层
        # 直接调它都不该能伪造一条「超管申请」。
        if "super_admin" not in actor_roles:
            raise ControlServiceError(
                "action_request_forbidden", "仅超管可以提交动作申请。", 403
            )
        if type(ttl_seconds) is not int or ttl_seconds < 1:
            raise ControlServiceError(
                "action_request_invalid", "TTL 必须为正整数秒。", 422
            )
        now = self._now(clock)
        created = _utc_stamp(now)
        expires = _utc_stamp(now + timedelta(seconds=ttl_seconds))
        request_id = f"req_{uuid.uuid4().hex}"
        subject = actor_subject.strip()
        with self._lock, self._transaction(write=True) as conn:
            existing = conn.execute(
                f"SELECT * FROM {ACTION_REQUEST_TABLE} WHERE instance=? AND idempotency_key=?",
                (self.instance, idempotency_key),
            ).fetchone()
            if existing is not None:
                # 幂等命中≠无条件复用：主体或动作不同＝另一件事，拒且不回显既有行。
                if existing["action"] != action or existing["actor_subject"] != subject:
                    raise ControlServiceError(
                        "action_request_idempotency_conflict",
                        "同一幂等键的请求内容与已登记申请不一致。",
                        409,
                    )
                return self._dto(existing), True
            conn.execute(
                f"""INSERT INTO {ACTION_REQUEST_TABLE}
                (request_id, instance, idempotency_key, action, actor_subject,
                 actor_roles, status, version, result_json, created_at, updated_at,
                 expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, '{{}}', ?, ?, ?)""",
                (
                    request_id, self.instance, idempotency_key, action, subject,
                    _json(list(actor_roles)), _STATUS_PENDING, created, created,
                    expires,
                ),
            )
            row = conn.execute(
                f"SELECT * FROM {ACTION_REQUEST_TABLE} WHERE request_id=?",
                (request_id,),
            ).fetchone()
        return self._dto(row), False

    # ---- 读面 -------------------------------------------------------------

    def get(self, request_id: str) -> dict[str, Any] | None:
        if not isinstance(request_id, str) or not request_id.strip():
            return None
        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT * FROM {ACTION_REQUEST_TABLE} WHERE instance=? AND request_id=?",
                (self.instance, request_id.strip()),
            ).fetchone()
        return None if row is None else self._dto(row)

    def counts(self) -> dict[str, int]:
        with self._transaction() as conn:
            rows = conn.execute(
                f"SELECT status, COUNT(*) AS n FROM {ACTION_REQUEST_TABLE} WHERE instance=? GROUP BY status",
                (self.instance,),
            ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}

    # ---- 消费（Bot 侧唯一入口的持久化腿：只改状态，不执行）----------------

    def claim_pending(
        self, *, limit: int = 10, clock: Any = None
    ) -> list[dict[str, Any]]:
        """先把过窗的落 ``expired``，再把 ``pending`` 抢成 ``awaiting_human``。

        抢是行级 CAS（``status='pending' AND version=?``），多消费者也只有一个能拿到
        同一笔；拿到的行由调用方负责喊人。
        """
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit 必须为 1..50")
        now_stamp = _utc_stamp(self._now(clock))
        claimed: list[dict[str, Any]] = []
        with self._lock, self._transaction(write=True) as conn:
            conn.execute(
                f"""UPDATE {ACTION_REQUEST_TABLE}
                SET status='{_STATUS_EXPIRED}', version=version+1, updated_at=?,
                    result_json=?
                WHERE instance=? AND status='{_STATUS_PENDING}' AND expires_at <= ?""",
                (
                    now_stamp,
                    _json({"code": "expired", "message": "申请已过时效，未处理。"}),
                    self.instance,
                    now_stamp,
                ),
            )
            rows = conn.execute(
                f"""SELECT * FROM {ACTION_REQUEST_TABLE}
                WHERE instance=? AND status='{_STATUS_PENDING}' AND expires_at > ?
                ORDER BY created_at LIMIT ?""",
                (self.instance, now_stamp, limit),
            ).fetchall()
            for row in rows:
                cursor = conn.execute(
                    f"""UPDATE {ACTION_REQUEST_TABLE}
                    SET status='{_STATUS_AWAITING_HUMAN}', version=version+1,
                        updated_at=?, result_json=?
                    WHERE request_id=? AND instance=? AND status='{_STATUS_PENDING}'
                    AND version=?""",
                    (
                        now_stamp,
                        _json({"code": "awaiting_human",
                               "message": "已通知运维人工执行重启。"}),
                        row["request_id"], self.instance, row["version"],
                    ),
                )
                if cursor.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE 下不发生
                    continue
                claimed.append(
                    self._dto(
                        conn.execute(
                            f"SELECT * FROM {ACTION_REQUEST_TABLE} WHERE request_id=?",
                            (row["request_id"],),
                        ).fetchone()
                    )
                )
        return claimed

    # ---- DTO --------------------------------------------------------------

    def _dto(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "request_id": row["request_id"],
            "instance": row["instance"],
            "idempotency_key": row["idempotency_key"],
            "action": row["action"],
            "actor_subject": row["actor_subject"],
            "actor_roles": list(json.loads(row["actor_roles"])),
            "status": row["status"],
            "version": row["version"],
            "result": json.loads(row["result_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
        }


class ActionRequestConsumer:
    """Bot 侧唯一读口：读到有效申请**只喊人**，到 TTL **只落过期**。

    🔴 本类**不做**、也不许将来做：``os.execv``/``os.kill``/``os.system``/
    ``subprocess``/信号/supervisor 调用。理由三条：面板是独立进程，没有 supervisor
    与信号通道；生产 bot 以管理员权限常驻，杀它需提权；``AGENTS.md`` 写死「重启由
    用户执行或明示授权」。这里能做的只有「让它被看见」。

    告警失败只记固定 warning、不抛（告警链坏了不能拖垮消费循环），该行留在
    ``awaiting_human``——下次重启后运维仍能在面板上看到它。
    """

    def __init__(
        self,
        store: SQLiteActionRequestStore,
        *,
        alert_sink: Any,
        clock: Any = None,
        owner: str = "bot-action-requests",
    ) -> None:
        if not callable(alert_sink):
            raise TypeError("动作申请消费者必须注入告警 sink")
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("owner 不能为空")
        self.store = store
        self.alert_sink = alert_sink
        self.clock = clock
        self.owner = owner.strip()
        # 待喊文本队列：drain（可能在 to_thread 工作线程）只往里攒，
        # 由 runner 在 await 之后于**事件循环线程**调 flush_pending_announcements 投出。
        self._pending_announcements: list[str] = []

    def drain(
        self,
        *,
        limit: int = 10,
        needs_consent_backoff_seconds: float = 5.0,  # 与 runner 同形，本面不用
        clock: Any = None,
    ) -> list[dict[str, Any]]:
        """抢单并**只排队**待喊文本；返回本次处理过的申请 DTO（空＝无事可做）。

        🔴 W12-REVIEW 修（2026-10-19，P0-2）：**本方法绝不直接调 ``alert_sink``**。

        为什么（实测，不是推演）：``ConfigCommandConsumerRunner._loop`` 用
        ``await asyncio.to_thread(self._consumer.drain, ...)`` 把 drain 甩进线程池；
        生产 sink 最终走 root 的 ``_push_probe_issue``，它第一步
        ``asyncio.get_running_loop()``——工作线程里**必然 RuntimeError**，被
        ``except Exception`` 吞成一条 debug ⇒ **告警 0 条投出**，而申请行已经落
        ``awaiting_human``，账面上看起来"已处理"，再 drain 也不重投。

        所以这里只把文本攒进 ``_pending_announcements``，由 runner 在 ``await``
        返回之后（＝**事件循环线程**里）调 :meth:`flush_pending_announcements`。
        职责切分：drain 负责"抢单 + 生成文本"，flush 负责"真的喊人"。

        ``needs_consent_backoff_seconds`` 只为复用 ``ConfigCommandConsumerRunner``
        而接受，本面没有待批态，不参与判定。
        """
        del needs_consent_backoff_seconds
        rows = self.store.claim_pending(limit=limit, clock=clock or self.clock)
        for row in rows:
            self._pending_announcements.append(self._announcement_text(row))
        return rows

    def take_pending_announcements(self) -> list[str]:
        """取走待喊文本（取走即清空，防重复刷屏）。测试与显式驱动用。"""
        taken, self._pending_announcements = self._pending_announcements, []
        return taken

    def flush_pending_announcements(self) -> int:
        """**在事件循环线程里**把攒下的待喊文本逐条投出；返回成功投递条数。

        单独成败：一条失败不拖累其余，全部失败也只记一条固定 warning
        （告警是旁路，不能反噬消费循环）。
        """
        texts = self.take_pending_announcements()
        delivered = 0
        for text in texts:
            try:
                self.alert_sink(text)
            except Exception:  # noqa: BLE001 - 告警是旁路，固定日志不 dump 异常全文
                logging.getLogger(__name__).warning(
                    "action request alert sink failed"
                )
                continue
            delivered += 1
        return delivered

    def _announcement_text(self, row: dict[str, Any]) -> str:
        return (
            "【需要人工执行】有人从控制面板请求重启 Bot。"
            f"申请人={row['actor_subject']}，申请号={row['request_id']}，"
            f"过期时间={row['expires_at']}。"
            "面板只会落这条账，不会自动重启；确认后请你自己手动重启主进程。"
        )


def build_action_request_runner(
    store_or_source: Any,
    *,
    alert_sink: Any,
    owner: str | None = None,
    logger: Any | None = None,
    interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_interval: float = DEFAULT_POLL_MAX_INTERVAL_SECONDS,
    limit: int = 10,
) -> ConfigCommandConsumerRunner:
    """生产装配口：造申请消费者并包成**同一个** runner 形态（不新建第二套轮询）。"""
    store = (
        store_or_source
        if isinstance(store_or_source, SQLiteActionRequestStore)
        else SQLiteActionRequestStore.from_config_store(store_or_source)
    )
    consumer = ActionRequestConsumer(
        store, alert_sink=alert_sink, owner=owner or f"bot-{os.getpid()}"
    )
    return ConfigCommandConsumerRunner(
        consumer, interval=interval, max_interval=max_interval, limit=limit,
        logger=logger,
    )
