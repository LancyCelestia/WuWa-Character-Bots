"""每实例配置覆盖的 SQLite 事务存储；仅操作调用方显式指定的路径。

revision 为实例全局 CAS 版本；覆盖、reset tombstone、审计同事务提交。
legacy 导入只执行一次（空导入也封口）；显式 SQL 写入同样封口，避免旧
JSON 复活。审计仅保留敏感值状态与摘要，不保留密钥明文。无资源 reload。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigVersionConflict(ValueError):
    """调用方必须重新读取当前实例版本，不自动重放过期的写操作。"""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"配置版本冲突：expected={expected}, actual={actual}")
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class ConfigSnapshot:
    version: int
    overrides: dict[str, Any]
    tombstones: frozenset[str]


def validate_version(version: int) -> None:
    if type(version) is not int or version < 0:
        raise ValueError("必须提供非负整数 expected_version")


def normalize_key(key: str, *, writable: bool = False) -> str:
    # 延迟导入：settings 真身（domains.chat_reply.runtime.settings）仅在选择 backend 时依赖本模块。
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        RESTART_REQUIRED_KEYS,
        SETTABLE_KEYS,
    )

    normalized = key.strip().upper()
    if normalized not in SETTABLE_KEYS and normalized not in RESTART_REQUIRED_KEYS:
        raise KeyError("未登记的配置键")
    if writable and normalized in RESTART_REQUIRED_KEYS:
        raise ValueError("该配置尚无安全热更新路径，请修改 .env 并重启")
    return normalized


# 按凭证字段后缀登记，不用 token 子串；MAX_TOKENS/预算/统计应可读。
_CREDENTIAL_SUFFIXES = (
    "_KEY", "_API_KEYS", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSPHRASE",
    "_COOKIE", "_COOKIES", "_CREDENTIAL", "_CREDENTIALS", "_AUTHORIZATION",
)


def is_sensitive(key: str) -> bool:
    normalized = key.strip().upper()
    for suffix in ("_SHA256", "_HASH", "_DIGEST"):
        if normalized.endswith(suffix):
            normalized = normalized.removesuffix(suffix)
            break
    return normalized.endswith(_CREDENTIAL_SUFFIXES)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


# 路径仅用于判断，命中后隐藏整个字符串，避免空格/引号后的路径尾部泄漏。
# 单斜线排除相邻斜线，因此正常 https:// 与相对路径/时区不被误判。
_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])[a-z]:[\\/]|\\\\|(?<![\w:/])//|(?<![\w/])/(?!/)|\bfile://")
_ASSIGNMENT_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_-]*)[\"']?\s*[:=：]")


def redact_public_data(value: Any, *, _depth: int = 0) -> Any:
    """DTO/审计出口专用：递归保留数值类型，不改变内部消费者拿到的原值。"""
    if value is None or type(value) in (bool, int, float):
        return value
    if _depth >= 20:
        return "[redacted]"
    try:
        if isinstance(value, str):
            from ..domains.ops.audit.logger import redact_private_debug

            redacted = redact_private_debug(value)
            # 复用现有凭证识别；整段隐藏也覆盖多 Cookie、带空格密钥的残尾。
            if not isinstance(redacted, str) or redacted != value:
                return "[redacted]"
            if _ABSOLUTE_PATH_RE.search(value) or any(
                is_sensitive("FIELD_" + match[1].replace("-", "_"))
                for match in _ASSIGNMENT_RE.finditer(value)
            ):
                return "[redacted]"
            return redacted
        if isinstance(value, (list, tuple)):
            return [redact_public_data(item, _depth=_depth + 1) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                name = str(key)
                safe_key = redact_public_data(name, _depth=_depth + 1)
                if is_sensitive("FIELD_" + name.replace("-", "_")):
                    result[safe_key] = "[redacted]" if item is not None and item != "" else None
                else:
                    result[safe_key] = redact_public_data(item, _depth=_depth + 1)
            return result
    except Exception:  # noqa: BLE001 - 隐私出口失败关闭，绝不回传原值或异常文本。
        return "[redacted]"
    return "[redacted]"  # Path/任意对象不通过 str() 意外泄漏。


def _public_audit_values(values: dict[str, Any]) -> dict[str, Any]:
    # 老审计也过出口，但不改写历史记录。逐项处理以保留凭证行的 fingerprint。
    result = {}
    for key, entry in values.items():
        safe = redact_public_data(entry)
        if is_sensitive(key) and isinstance(safe, dict):
            safe["value"] = "[redacted]" if safe.get("value") not in (None, "") else None
        result[redact_public_data(key)] = safe
    return result


def public_value(key: str, value: Any) -> dict[str, Any]:
    sensitive = is_sensitive(key)
    configured = value is not None and value != ""
    fingerprint = hashlib.sha256(_json(value).encode("utf-8")).hexdigest() if sensitive and configured else None
    return {"value": ("[redacted]" if configured else None) if sensitive else redact_public_data(value),
            "sensitive": sensitive, "configured": configured, "fingerprint": fingerprint}


# 审计动作标签（F-1）：值与 CFG12 锁件断言逐字相等（"import"/"import_refused"），
# 一字未改。此处是**审计动作字符串**、不是触发词的第二处声明位——「import」的
# 触发词真身在 platform_credentials._IMPORT_VERBS（/bot cookie 动词族），本常量
# 命名刻意不命中词表形态（棘轮判据），事件消费方（changes() 与锁件）拿到的值不变。
_IMPORT_ACTION = "import"
_IMPORT_REFUSED_ACTION = "import_refused"


class SQLiteConfigStateStore:
    """短连接、无覆盖缓存；独立对象/进程在每次读取时看到已提交的 SQL 状态。"""

    def __init__(self, path: str | Path, instance: str = "default") -> None:
        if not str(path).strip() or str(path) == ":memory:":
            raise ValueError("配置 backend 需要显式文件路径")
        if not isinstance(instance, str) or not instance.strip():
            raise ValueError("实例名不能为空")
        self.path = Path(path).expanduser().resolve()
        self.instance = instance
        self._listeners: list[Callable[[], None]] = []
        self._listener_lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(write=True) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS config_instances (
                instance TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0,
                legacy_imported INTEGER NOT NULL DEFAULT 0)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS config_overrides (
                instance TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT,
                is_reset INTEGER NOT NULL CHECK(is_reset IN (0, 1)),
                PRIMARY KEY(instance, key))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS config_audit (
                instance TEXT NOT NULL, version INTEGER NOT NULL, action TEXT NOT NULL,
                key TEXT, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
                actor TEXT NOT NULL, request_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY(instance, version))""")
            conn.execute("INSERT OR IGNORE INTO config_instances(instance) VALUES (?)", (self.instance,))

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

    def _snapshot(self, conn: sqlite3.Connection) -> ConfigSnapshot:
        version = conn.execute("SELECT revision FROM config_instances WHERE instance=?", (self.instance,)).fetchone()[0]
        rows = conn.execute("SELECT key, value_json, is_reset FROM config_overrides WHERE instance=?", (self.instance,)).fetchall()
        return ConfigSnapshot(version, {row["key"]: json.loads(row["value_json"]) for row in rows if not row["is_reset"]},
                              frozenset(row["key"] for row in rows if row["is_reset"]))

    def snapshot(self) -> ConfigSnapshot:
        with self._transaction() as conn:
            return self._snapshot(conn)

    def register_change_listener(self, callback: Callable[[], None]) -> None:
        """仅本对象成功写入后通知；跨进程读取无缓存，不承诺跨进程推送。"""
        with self._listener_lock:
            self._listeners.append(callback)

    def _notify(self) -> None:
        with self._listener_lock:
            listeners = tuple(self._listeners)
        for callback in listeners:
            try:
                callback()
            except Exception:  # noqa: BLE001, S110 - 已提交的写入不可因监听失败变成失败。
                pass

    def _audit(self, conn: sqlite3.Connection, *, before: ConfigSnapshot, after: ConfigSnapshot,
               action: str, key: str | None, keys: list[str], actor: str, request_id: str) -> None:
        def values(snapshot: ConfigSnapshot) -> dict[str, Any]:
            return {name: {"state": "override" if name in snapshot.overrides else "default",
                           **public_value(name, snapshot.overrides.get(name))} for name in keys}
        conn.execute("""INSERT INTO config_audit
            (instance, version, action, key, before_json, after_json, actor, request_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (self.instance, after.version, action, key, _json(values(before)), _json(values(after)),
             redact_public_data(actor), redact_public_data(request_id)))

    def _change(self, key: str | None, value: Any, *, reset: bool, expected_version: int,
                actor: str, request_id: str) -> ConfigSnapshot:
        validate_version(expected_version)
        if not isinstance(actor, str) or not actor.strip() or not isinstance(request_id, str):
            raise ValueError("actor 必须非空且 request_id 必须为字符串")
        if key is not None:
            key = normalize_key(key, writable=True)
        encoded = None if reset else _json(value)
        with self._transaction(write=True) as conn:
            before = self._snapshot(conn)
            if before.version != expected_version:
                raise ConfigVersionConflict(expected_version, before.version)
            keys = sorted(before.overrides) if key is None else [key]
            for name in keys:
                normalize_key(name, writable=True)
                conn.execute("""INSERT INTO config_overrides(instance, key, value_json, is_reset)
                    VALUES (?, ?, ?, ?) ON CONFLICT(instance, key) DO UPDATE SET
                    value_json=excluded.value_json, is_reset=excluded.is_reset""",
                    (self.instance, name, encoded, int(reset)))
            conn.execute("UPDATE config_instances SET revision=revision+1, legacy_imported=1 WHERE instance=?", (self.instance,))
            after = self._snapshot(conn)
            self._audit(conn, before=before, after=after, action="reset" if reset else "set",
                        key=key, keys=keys, actor=actor, request_id=request_id)
        self._notify()  # COMMIT 已成功且连接已关闭，监听可通过独立连接验证审计。
        return after

    def set_override(self, key: str, value: Any, *, expected_version: int,
                     actor: str, request_id: str = "") -> ConfigSnapshot:
        return self._change(key, value, reset=False, expected_version=expected_version, actor=actor, request_id=request_id)

    def reset_override(self, key: str | None = None, *, expected_version: int,
                       actor: str, request_id: str = "") -> ConfigSnapshot:
        return self._change(key, None, reset=True, expected_version=expected_version, actor=actor, request_id=request_id)

    def import_legacy(self, overrides: Mapping[str, Any]) -> bool:
        """只消费已加载的 legacy 覆盖；不读写 JSON，也不回填已封口的实例。

        F-1（SEAT-ATKFIX-CFG12，2026-09-28）：导入也是「改参数」——不经咽喉的
        非 R0 档一律拒入库。档位真身只认
        ``domains/core/safety_exec/config_risk.py`` 这一张表（禁第二套判据）；
        被拒的键留在 JSON 不迁不认，之后要落库必须正常过咽喉四档裁决，
        并在审计里留一条 ``import_refused``（不留被拒值的明文，只留键名与形态）。
        """
        from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
            RESTART_REQUIRED_KEYS,
            SETTABLE_KEYS,
        )

        # 延迟导入：control_plane 对 safety_exec 只做软依赖（家规同上方 settings 延迟 import）。
        # 装载失败不静默放行：判不出档 ⇒ 一枚都不带（fail-closed，与咽喉同口径）。
        tier_risk: Any = None
        try:
            from plugins.bot_unified_runtime.domains.core.safety_exec import config_risk
            tier_risk = config_risk
        except Exception:  # noqa: BLE001 - 分级表读不进来时没有任何键可被证明是 R0
            tier_risk = None

        with self._transaction(write=True) as conn:
            imported = conn.execute("SELECT legacy_imported FROM config_instances WHERE instance=?", (self.instance,)).fetchone()[0]
            if imported:
                return False
            before = self._snapshot(conn)
            keys = []
            refused: list[str] = []
            for key, value in overrides.items():
                if key not in SETTABLE_KEYS or key in RESTART_REQUIRED_KEYS:
                    continue
                if tier_risk is None or not tier_risk.allows_unattended_change(
                    tier_risk.risk_tier_for_target(key)
                ):
                    refused.append(key)
                    continue
                conn.execute("INSERT INTO config_overrides(instance, key, value_json, is_reset) VALUES (?, ?, ?, 0)",
                             (self.instance, key, _json(value)))
                keys.append(key)
            # 审计主键是 (instance, version)：迁入、拒入各占一枚版本戳（只算发生的腿）。
            events: list[tuple[str, list[str]]] = []
            if keys:
                events.append((_IMPORT_ACTION, sorted(keys)))
            if refused:
                events.append((_IMPORT_REFUSED_ACTION, sorted(refused)))
            conn.execute("UPDATE config_instances SET legacy_imported=1, revision=revision+? WHERE instance=?",
                         (len(events), self.instance))
            after = self._snapshot(conn)
            for offset, (action, event_keys) in enumerate(events, start=1):
                slot = ConfigSnapshot(before.version + offset, after.overrides, after.tombstones)
                self._audit(conn, before=before, after=slot, action=action, key=None,
                            keys=event_keys, actor="legacy_import", request_id="")
        return True

    def changes(self, *, since_version: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        validate_version(since_version)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit 必须为 1..1000 的整数")
        with self._transaction() as conn:
            rows = conn.execute("""SELECT * FROM config_audit WHERE instance=? AND version>?
                ORDER BY version LIMIT ?""", (self.instance, since_version, limit)).fetchall()
        return [{"instance": redact_public_data(row["instance"]), "version": row["version"], "action": row["action"],
                 "key": redact_public_data(row["key"]), "before": _public_audit_values(json.loads(row["before_json"])),
                 "after": _public_audit_values(json.loads(row["after_json"])),
                 "actor": redact_public_data(row["actor"]), "request_id": redact_public_data(row["request_id"]),
                 "created_at": row["created_at"]} for row in rows]
