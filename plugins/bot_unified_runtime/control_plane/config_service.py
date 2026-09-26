"""HTTP 无关的配置控制服务；CAS 持久化不等同于资源已安全 reload。

公开读项保留 legacy value/source 等字段。只有 SETTABLE_KEYS 可变更；
RESTART_REQUIRED_KEYS 仅可读。本层拒绝越权/过期写，底层审计失败则整笔回滚。
"""
from __future__ import annotations

import builtins
import json
import sqlite3
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RESTART_REQUIRED_KEYS,
    SETTABLE_KEYS,
    RuntimeSettingsStore,
)

from .auth import Principal
from .config_store import (
    ConfigSnapshot,
    ConfigVersionConflict,
    SQLiteConfigStateStore,
    normalize_key,
    public_value,
    redact_public_data,
    validate_version,
)
from .services import ControlServiceError


class ConfigControlService:
    def __init__(self, config: object, backend: SQLiteConfigStateStore, *,
                 runtime_settings: RuntimeSettingsStore | None = None) -> None:
        self.config = config
        if runtime_settings is not None:
            runtime_settings.attach_config_backend(backend)
            attached = runtime_settings.config_backend
            assert attached is not None
            backend = attached  # 同文件的另一个对象也统一到运行时监听绑定的对象。
        self.backend = backend

    def _key(self, key: str, *, writable: bool = False) -> str:
        try:
            return normalize_key(key, writable=writable)
        except KeyError:
            raise ControlServiceError("config_not_found", "未找到对应配置键。", 404) from None
        except (ValueError, AttributeError, TypeError):
            raise ControlServiceError("config_not_hot_reloadable", "该配置尚无安全热更新路径，请修改 .env 并重启。", 409) from None

    def _snapshot(self) -> ConfigSnapshot:
        try:
            return self.backend.snapshot()
        except (sqlite3.Error, OSError):
            raise ControlServiceError("config_store_unavailable", "配置存储暂不可用。", 503) from None

    def _row(self, key: str, snapshot: ConfigSnapshot) -> dict[str, Any]:
        # 冻结键即便留有历史覆盖，也不能假称它已作用于当前资源。
        overridden = key in snapshot.overrides and key not in RESTART_REQUIRED_KEYS
        value = snapshot.overrides[key] if overridden else getattr(self.config, key.lower(), None)
        return {"key": key, **public_value(key, value),
                "source": "runtime_override" if overridden else "config",
                "state": "override" if overridden else "default", "version": snapshot.version,
                "hot_reload": key in SETTABLE_KEYS and key not in RESTART_REQUIRED_KEYS,
                "restart_required": key in RESTART_REQUIRED_KEYS,
                "description": redact_public_data(RESTART_REQUIRED_KEYS.get(key, "运行时白名单参数"))}

    def schema(self) -> builtins.list[dict[str, Any]]:
        return self.list()

    def list(self) -> builtins.list[dict[str, Any]]:
        snapshot = self._snapshot()
        return [self._row(key, snapshot) for key in sorted(set(SETTABLE_KEYS) | set(RESTART_REQUIRED_KEYS))]

    def get(self, key: str) -> dict[str, Any]:
        return self._row(self._key(key), self._snapshot())

    def _authorize(self, principal: Principal, expected_version: int, request_id: str) -> None:
        if "super_admin" not in principal.roles:
            raise ControlServiceError("forbidden", "此操作需要 super_admin 权限。", 403)
        try:
            validate_version(expected_version)
        except ValueError:
            raise ControlServiceError("invalid_version", "必须提供非负整数 expected_version。", 422) from None
        if not isinstance(request_id, str) or not isinstance(principal.subject, str) or not principal.subject.strip():
            raise ControlServiceError("config_invalid", "审计主体及请求标识无效。", 422)

    def _convert(self, key: str, value: Any) -> Any:
        try:
            if value is None:
                raise ValueError("清除覆盖请使用 reset")
            if isinstance(value, str):
                raw = value.strip()
            elif isinstance(value, list) and key in {
                "BOT_QUIET_HOURS_SESSION_TYPES", "BOT_QUIET_HOURS_BYPASS_ROLES",
            }:
                # 两个 legacy converter 接收分隔文本，而非 JSON 数组字符串。
                if not all(isinstance(item, str) for item in value):
                    raise ValueError("列表项必须为字符串")
                raw = ",".join(value)
            else:
                raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
            converted = SETTABLE_KEYS[key](raw)
            json.dumps(converted, allow_nan=False)
            return converted
        except (ValueError, TypeError, OverflowError):
            # converter 的异常可能包含原始 secret，不把 cause 暴露到 DTO。
            raise ControlServiceError("config_invalid", "配置值未通过校验。", 422) from None

    def preview(self, key: str, value: Any = None, *, principal: Principal,
                expected_version: int, reset: bool = False, request_id: str = "") -> dict[str, Any]:
        self._authorize(principal, expected_version, request_id)
        key = self._key(key, writable=True)
        if type(reset) is not bool:
            raise ControlServiceError("config_invalid", "reset 必须为布尔值。", 422)
        snapshot = self._snapshot()
        if snapshot.version != expected_version:
            raise ControlServiceError("version_conflict", "配置版本已变更，请重新读取。", 409)
        overrides = dict(snapshot.overrides)
        if reset:
            overrides.pop(key, None)
        else:
            overrides[key] = self._convert(key, value)
        return {**self._row(key, ConfigSnapshot(snapshot.version, overrides, snapshot.tombstones)), "preview": True}

    def _write(self, key: str, value: Any, *, reset: bool, principal: Principal,
               expected_version: int, request_id: str) -> dict[str, Any]:
        self._authorize(principal, expected_version, request_id)
        key = self._key(key, writable=True)
        converted = None if reset else self._convert(key, value)
        try:
            if reset:
                snapshot = self.backend.reset_override(key, expected_version=expected_version,
                                                       actor=principal.subject, request_id=request_id)
            else:
                snapshot = self.backend.set_override(key, converted, expected_version=expected_version,
                                                     actor=principal.subject, request_id=request_id)
        except ConfigVersionConflict:
            raise ControlServiceError("version_conflict", "配置版本已变更，请重新读取。", 409) from None
        except (sqlite3.Error, OSError):
            raise ControlServiceError("config_store_unavailable", "配置未保存，存储暂不可用。", 503) from None
        return self._row(key, snapshot)

    def set(self, key: str, value: Any, *, principal: Principal, expected_version: int,
            request_id: str = "") -> dict[str, Any]:
        return self._write(key, value, reset=False, principal=principal,
                           expected_version=expected_version, request_id=request_id)

    def reset(self, key: str, *, principal: Principal, expected_version: int,
              request_id: str = "") -> dict[str, Any]:
        return self._write(key, None, reset=True, principal=principal,
                           expected_version=expected_version, request_id=request_id)

    def reset_all(self, *, principal: Principal, expected_version: int,
                  request_id: str = "") -> dict[str, int]:
        """一次 CAS 清空覆盖；count 来自同一版本快照，不逐键提交。"""
        self._authorize(principal, expected_version, request_id)
        before = self._snapshot()
        if before.version != expected_version:
            raise ControlServiceError("version_conflict", "配置版本已变更，请重新读取。", 409)
        for key in before.overrides:
            self._key(key, writable=True)  # 仅预校验；历史冻结键也不假称热改。
        try:
            after = self.backend.reset_override(
                None, expected_version=expected_version,
                actor=principal.subject, request_id=request_id,
            )
        except ConfigVersionConflict:
            raise ControlServiceError("version_conflict", "配置版本已变更，请重新读取。", 409) from None
        except (sqlite3.Error, OSError):
            raise ControlServiceError("config_store_unavailable", "配置未保存，存储暂不可用。", 503) from None
        return {"version": after.version, "reset_count": len(before.overrides)}

    def changes(self, *, since_version: int = 0, limit: int = 100) -> builtins.list[dict[str, Any]]:
        try:
            return self.backend.changes(since_version=since_version, limit=limit)
        except ValueError:
            raise ControlServiceError("config_invalid", "历史分页参数无效。", 422) from None
        except (sqlite3.Error, OSError):
            raise ControlServiceError("config_store_unavailable", "配置历史暂不可用。", 503) from None
