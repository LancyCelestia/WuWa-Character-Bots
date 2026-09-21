"""Control-plane feature registry and versioned tree state.

The WebUI and ``/bot feature`` command are intentionally backed by this
small service boundary.  Runtime consumers can later replace the descriptor
source without changing the API DTOs or the state semantics.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

FeatureKind = Literal[
    "group",
    "plugin",
    "feature",
    "command",
    "help",
    "document",
    "scheduled_job",
    "control_action",
    "metric",
    "data_resource",
    "sub_feature", "auto_reply", "config", "trace_stage",
    "model_provider", "model_channel", "model",
]


@dataclass(frozen=True)
class FeatureDescriptor:
    """Stable product node metadata consumed by control-plane clients."""

    id: str
    parent_id: str | None
    kind: FeatureKind
    label: str
    aliases: tuple[str, ...] = ()
    capability_id: str | None = None
    route_kind: str | None = None
    default_enabled: bool = True
    hot_toggle: bool = True
    dependencies: tuple[str, ...] = ()
    required_roles: tuple[str, ...] = ("super_admin",)
    config_keys: tuple[str, ...] = ()
    documentation_refs: tuple[str, ...] = ()
    webui_visibility: str = "visible"
    protected: bool = False
    implementation_ref: str | None = None
    reload_strategy: str = "gate"
    privacy_level: str = "internal"


@dataclass(frozen=True)
class FeatureState:
    feature_id: str
    explicit_enabled: bool | None
    effective_enabled: bool
    inherited_from: str | None
    blocked_by: tuple[str, ...] = ()
    updated_by: str | None = None
    updated_at: str | None = None
    version: int = 0
    graph_revision: int = 0


_PROTECTED_IDS = frozenset({
    "bot.control_plane",
    "bot.audit",
    "bot.error_handling",
    "bot.persona.safety",
})


def default_feature_descriptors() -> tuple[FeatureDescriptor, ...]:
    """Return the initial registry projection without importing NoneBot."""
    return (
        FeatureDescriptor("bot", None, "group", "Bot", aliases=("根",)),
        FeatureDescriptor(
            "bot.plugin.weather",
            "bot",
            "plugin",
            "天气",
            aliases=("weather", "天气插件"),
            capability_id="bot.weather",
        ),
        FeatureDescriptor(
            "bot.plugin.weather.command.forecast",
            "bot.plugin.weather",
            "command",
            "天气命令",
            aliases=("天气", "forecast"),
            capability_id="bot.weather",
        ),
        FeatureDescriptor(
            "bot.plugin.chat",
            "bot",
            "plugin",
            "人格对话",
            aliases=("chat", "聊天"),
            capability_id="bot.chat",
        ),
        FeatureDescriptor(
            "bot.plugin.control_plane",
            "bot",
            "plugin",
            "控制面",
            aliases=("control_plane", "webui"),
            capability_id="bot.control_plane",
            default_enabled=True,
            hot_toggle=False,
        ),
        FeatureDescriptor(
            "bot.control_plane",
            "bot.plugin.control_plane",
            "feature",
            "控制面服务",
            capability_id="bot.control_plane",
            hot_toggle=False,
        ),
        FeatureDescriptor(
            "bot.audit",
            "bot",
            "feature",
            "审计",
            default_enabled=True,
            hot_toggle=False,
        ),
        FeatureDescriptor(
            "bot.error_handling",
            "bot",
            "feature",
            "统一错误处理",
            default_enabled=True,
            hot_toggle=False,
        ),
        FeatureDescriptor(
            "bot.persona.safety",
            "bot",
            "feature",
            "人格安全边界",
            default_enabled=True,
            hot_toggle=False,
        ),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class FeatureRegistry:
    """Immutable descriptor index with alias and hierarchy validation."""

    def __init__(self, descriptors: tuple[FeatureDescriptor, ...] | None = None) -> None:
        self.descriptors = tuple(descriptors or default_feature_descriptors())
        self._by_id = {item.id: item for item in self.descriptors}
        if len(self._by_id) != len(self.descriptors):
            raise ValueError("duplicate feature id")
        aliases: dict[str, str] = {}
        self._dependents: dict[str, list[str]] = {item.id: [] for item in self.descriptors}
        for item in self.descriptors:
            if item.parent_id is not None and item.parent_id not in self._by_id:
                raise ValueError(f"missing feature parent: {item.id}")
            for dependency in item.dependencies:
                if dependency not in self._by_id:
                    raise ValueError(f"missing feature dependency: {item.id} -> {dependency}")
            prerequisites = (*item.dependencies, *((item.parent_id,) if item.parent_id is not None else ()))
            for prerequisite in dict.fromkeys(prerequisites):
                self._dependents[prerequisite].append(item.id)
            for alias in (item.id, *item.aliases):
                key = alias.strip().lower()
                if key in aliases and aliases[key] != item.id:
                    raise ValueError(f"duplicate feature alias: {alias}")
                aliases[key] = item.id
        self._aliases = aliases
        self._validate_acyclic()

    def _validate_acyclic(self) -> None:
        # Parent and dependency edges gate the same effective state, so they
        # must form one DAG, not merely two independently acyclic graphs.
        active: set[str] = set()
        done: set[str] = set()
        for item in self.descriptors:
            pending = [(item.id, False)]
            while pending:
                current, exiting = pending.pop()
                if exiting:
                    active.remove(current)
                    done.add(current)
                elif current not in done:
                    if current in active:
                        raise ValueError(f"feature hierarchy/dependency cycle: {current}")
                    active.add(current)
                    pending.append((current, True))
                    pending.extend((child, False) for child in self._dependents[current])

    def affected(self, feature_id: str) -> tuple[FeatureDescriptor, ...]:
        """Target plus transitive parent/dependency consumers, once each."""
        self.get(feature_id)
        pending = [feature_id]
        seen = {feature_id}
        for current in pending:
            for dependent in self._dependents[current]:
                if dependent not in seen:
                    seen.add(dependent)
                    pending.append(dependent)
        return tuple(self._by_id[current] for current in pending)

    def get(self, feature_id: str) -> FeatureDescriptor:
        try:
            return self._by_id[feature_id]
        except KeyError as exc:
            raise KeyError(feature_id) from exc

    def resolve(self, value: str) -> str | None:
        return self._aliases.get(str(value or "").strip().lower())

    def children(self, parent_id: str | None) -> tuple[FeatureDescriptor, ...]:
        return tuple(item for item in self.descriptors if item.parent_id == parent_id)

    def descendants(self, feature_id: str) -> tuple[FeatureDescriptor, ...]:
        result: list[FeatureDescriptor] = []
        pending = [feature_id]
        while pending:
            parent = pending.pop(0)
            children = self.children(parent)
            result.extend(children)
            pending.extend(item.id for item in children)
        return tuple(result)


class InvalidFeatureStateError(ValueError):
    """持久化文件不符合状态协议；拒绝静默恢复默认开关。"""


class FeatureStateStore:
    """Atomic, versioned state store for the feature tree."""

    def __init__(
        self,
        path: str | Path,
        *,
        descriptors: tuple[FeatureDescriptor, ...] | None = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.registry = FeatureRegistry(descriptors)
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, Any]] = {}
        self._audit: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return  # 首次初始化；其他 IO 故障不能默认为全启用。
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise InvalidFeatureStateError("invalid feature state file") from exc
        if not isinstance(payload, dict):
            raise InvalidFeatureStateError("invalid feature state file")
        states, audits = payload.get("states"), payload.get("audit")
        if not isinstance(states, dict) or not isinstance(audits, list):
            raise InvalidFeatureStateError("invalid feature state schema")
        for raw in states.values():
            if not isinstance(raw, dict):
                raise InvalidFeatureStateError("invalid feature state record")
            explicit, version = raw.get("explicit_enabled"), raw.get("version", 0)
            if explicit is not None and type(explicit) is not bool:
                raise InvalidFeatureStateError("invalid feature state boolean")
            if type(version) is not int or version < 0:
                raise InvalidFeatureStateError("invalid feature state version")
        if any(not isinstance(row, dict) for row in audits):
            raise InvalidFeatureStateError("invalid feature state audit")
        self._states = states
        self._audit = audits[-200:]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temp.write_text(
            json.dumps({"states": self._states, "audit": self._audit[-200:]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, self.path)

    def _explicit(self, feature_id: str) -> bool | None:
        raw = self._states.get(feature_id, {}).get("explicit_enabled")
        return raw if isinstance(raw, bool) else None

    def get(self, feature_id: str) -> FeatureState:
        with self._lock:
            descriptor = self.registry.get(feature_id)
            explicit = self._explicit(feature_id)
            blocked: list[str] = []
            inherited_from: str | None = None
            effective = descriptor.default_enabled if explicit is None else explicit
            if descriptor.parent_id is not None:
                parent = self.get(descriptor.parent_id)
                if not parent.effective_enabled:
                    effective = False
                    blocked.append(parent.feature_id)
                    inherited_from = parent.feature_id
            for dependency in descriptor.dependencies:
                dependency_state = self.get(dependency)
                if not dependency_state.effective_enabled:
                    effective = False
                    blocked.append(dependency)
            raw = self._states.get(feature_id, {})
            return FeatureState(
                feature_id=feature_id,
                explicit_enabled=explicit,
                effective_enabled=bool(effective),
                inherited_from=inherited_from,
                blocked_by=tuple(dict.fromkeys(blocked)),
                updated_by=str(raw.get("updated_by")) if raw.get("updated_by") else None,
                updated_at=str(raw.get("updated_at")) if raw.get("updated_at") else None,
                version=int(raw.get("version", 0) or 0),
            )

    def list_states(self) -> tuple[FeatureState, ...]:
        with self._lock:
            return tuple(self.get(item.id) for item in self.registry.descriptors)

    def _change(
        self,
        feature_id: str,
        enabled: bool | None,
        *,
        actor: str | None,
        expected_version: int | None,
        request_id: str | None = None,
        preview: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            descriptor = self.registry.get(feature_id)
            current = self.get(feature_id)
            if expected_version is not None and expected_version != current.version:
                raise RuntimeError(f"feature version conflict: expected {expected_version}, actual {current.version}")
            affected = self.registry.affected(feature_id)
            own_enabled = descriptor.default_enabled if enabled is None else enabled
            if not own_enabled and any(item.id in _PROTECTED_IDS or item.protected for item in affected):
                raise PermissionError(f"protected feature or prerequisite cannot be disabled: {feature_id}")

            previous_states, previous_audit = self._states, self._audit
            staged = dict(self._states.get(feature_id, {}))
            staged.update(explicit_enabled=enabled, version=current.version + 1)
            if not preview:
                staged.update(updated_by=str(actor)[:120], updated_at=_now_iso())
            self._states = {**self._states, feature_id: staged}
            committed = False
            try:
                state = asdict(self.get(feature_id))
                affected_ids = [item.id for item in affected]
                result = {
                    "state": state,
                    "affected": [asdict(self.get(item.id)) for item in affected],
                    "affected_ids": affected_ids,
                }
                if preview:
                    return result
                audit_id = f"feature-{uuid.uuid4().hex[:16]}"
                self._audit = [*previous_audit[-199:], {
                    "audit_id": audit_id,
                    "feature_id": feature_id,
                    "enabled": enabled,
                    "actor": staged["updated_by"],
                    "affected": affected_ids,
                    "occurred_at": staged["updated_at"],
                    "version": staged["version"],
                    "before": asdict(current),
                    "after": deepcopy(state),
                    "request_id": request_id,
                }]
                try:
                    self._save()
                except PermissionError as exc:
                    # Service maps PermissionError to protected/403, whereas
                    # a filesystem denial must remain persistence/503.
                    raise OSError("feature state persistence failed") from exc
                committed = True
                result["audit_id"] = audit_id
                return result
            finally:
                if not committed:
                    self._states, self._audit = previous_states, previous_audit

    def preview(
        self, feature_id: str, enabled: bool | None, expected_version: int,
    ) -> dict[str, Any]:
        """Project the next state under lock without saving or auditing it.

        None resets the explicit override. Versions remain node-local: a
        prerequisite change does not increment a consumer's version. A future
        service should use a graph revision for effective-state concurrency.
        """
        return self._change(
            feature_id, None if enabled is None else bool(enabled), actor=None,
            expected_version=expected_version, preview=True,
        )

    def set_enabled(
        self,
        feature_id: str,
        enabled: bool,
        *,
        actor: str,
        expected_version: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        result = self._change(
            feature_id, bool(enabled), actor=actor,
            expected_version=expected_version, request_id=request_id,
        )
        return {key: result[key] for key in ("audit_id", "state", "affected")}

    def reset(
        self, feature_id: str, *, actor: str,
        expected_version: int | None = None, request_id: str | None = None,
    ) -> dict[str, Any]:
        result = self._change(
            feature_id, None, actor=actor,
            expected_version=expected_version, request_id=request_id,
        )
        return {key: result[key] for key in ("state", "audit_id")}

    def audit(self, feature_id: str | None = None) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._audit
            if feature_id:
                rows = [row for row in rows if row.get("feature_id") == feature_id]
            return tuple(deepcopy(row) for row in rows[-100:])
