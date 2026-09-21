"""与 HTTP 无关的能力控制服务，供 API 与后续命令适配器复用。"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, Protocol

from .auth import Principal
from .features import FeatureRegistry, FeatureState


class FeatureStore(Protocol):
    """持久化无关的控制协议；SQLite可接受额外的图修订参数。"""
    registry: FeatureRegistry

    def get(self, feature_id: str) -> FeatureState: ...
    def list_states(self) -> tuple[FeatureState, ...]: ...
    def audit(self, feature_id: str | None = None) -> tuple[dict[str, Any], ...]: ...
    def preview(self, feature_id: str, enabled: bool | None, expected_version: int) -> dict[str, Any]: ...
    def set_enabled(self, feature_id: str, enabled: bool, *, actor: str, expected_version: int | None = None, request_id: str | None = None) -> dict[str, Any]: ...
    def reset(self, feature_id: str, *, actor: str, expected_version: int | None = None, request_id: str | None = None) -> dict[str, Any]: ...


class ControlServiceError(Exception):
    """业务错误：传输层负责状态码与 envelope，禁止回传底层异常。"""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@contextmanager
def _read_guard() -> Iterator[None]:
    try:
        yield
    except (OSError, ValueError) as exc:
        raise ControlServiceError("feature_state_unavailable", "功能状态存储暂不可用。", 503) from exc


class FeatureControlService:
    """唯一能力查询/变更入口；store 只负责状态与持久化。"""

    def __init__(self, store: FeatureStore) -> None:
        self._store = store

    @property
    def graph_cas_enabled(self) -> bool:
        return bool(getattr(self._store, "supports_graph_revision", False))

    def resolve(self, value: str) -> str:
        resolved = self._store.registry.resolve(value)
        if resolved is None:
            raise ControlServiceError("feature_not_found", "未找到对应的功能节点。", 404)
        return resolved

    def detail(self, value: str) -> dict[str, Any]:
        feature_id = self.resolve(value)
        with _read_guard():
            return {
                "descriptor": asdict(self._store.registry.get(feature_id)),
                "state": asdict(self._store.get(feature_id)),
            }

    def state_snapshot(self) -> tuple[FeatureState, ...]:
        """供执行端一次读取整图；不组装菜单 DTO、不跨线程重复读每个子节点。"""
        with _read_guard():
            return self._store.list_states()

    def _snapshot(self) -> dict[str, dict[str, Any]]:
        with _read_guard():
            states = self._store.list_states()  # 锁内取得一次图快照，避免父子混读。
        return {
            state.feature_id: {
                "descriptor": asdict(self._store.registry.get(state.feature_id)),
                "state": asdict(state),
            }
            for state in states
        }

    def list_features(self, *, kind: str | None = None, enabled: bool | None = None, search: str = "") -> list[dict[str, Any]]:
        needle = search.strip().lower()
        rows = []
        snapshot = self._snapshot()
        for descriptor in self._store.registry.descriptors:
            if kind is not None and descriptor.kind != kind:
                continue
            haystack = f"{descriptor.id} {descriptor.label} {' '.join(descriptor.aliases)}".lower()
            if needle and needle not in haystack:
                continue
            row = snapshot[descriptor.id]
            if enabled is None or row["state"]["effective_enabled"] == enabled:
                rows.append(row)
        return rows

    def children(self, value: str) -> list[dict[str, Any]]:
        feature_id = self.resolve(value)
        snapshot = self._snapshot()
        return [snapshot[item.id] for item in self._store.registry.children(feature_id)]

    def tree(self) -> list[dict[str, Any]]:
        snapshot = self._snapshot()

        def build(parent_id: str | None) -> list[dict[str, Any]]:
            return [
                {**snapshot[item.id], "children": build(item.id)}
                for item in self._store.registry.children(parent_id)
            ]
        return build(None)

    def audit(self, value: str) -> tuple[dict[str, Any], ...]:
        with _read_guard():
            return self._store.audit(self.resolve(value))

    def change(
        self, value: str, enabled: bool | None, *, principal: Principal,
        expected_version: int, request_id: str = "", preview: bool = False,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        # 角色在服务层再次校验；命令适配器不能绕过 HTTP 权限检查。
        if "super_admin" not in principal.roles:
            raise ControlServiceError("forbidden", "此操作需要 super_admin 权限。", 403)
        if type(expected_version) is not int or expected_version < 0:
            raise ControlServiceError("invalid_version", "必须提供非负整数 expected_version。", 422)
        if enabled is not None and type(enabled) is not bool:
            raise ControlServiceError("invalid_feature_state", "启用状态必须为布尔值或 null。", 422)
        feature_id = self.resolve(value)
        revision_args: dict[str, Any] = {}
        if getattr(self._store, "supports_graph_revision", False):
            if type(expected_revision) is not int or expected_revision < 0:
                raise ControlServiceError("invalid_revision", "必须提供非负整数 expected_revision。", 422)
            revision_args["expected_revision"] = expected_revision
        try:
            if preview:
                return self._store.preview(feature_id, enabled, expected_version=expected_version, **revision_args)
            if enabled is None:
                return self._store.reset(feature_id, actor=principal.subject, expected_version=expected_version, request_id=request_id, **revision_args)
            return self._store.set_enabled(feature_id, enabled, actor=principal.subject, expected_version=expected_version, request_id=request_id, **revision_args)
        except PermissionError as exc:
            raise ControlServiceError("feature_protected", "该变更会关闭受保护的核心能力。", 403) from exc
        except RuntimeError as exc:
            raise ControlServiceError("version_conflict", "功能状态已变化，请刷新后重试。", 409) from exc
        except ValueError as exc:
            raise ControlServiceError("feature_state_unavailable", "功能状态存储暂不可用。", 503) from exc
        except OSError as exc:
            raise ControlServiceError("feature_persistence_failed", "功能状态保存失败，变更未生效。", 503) from exc
