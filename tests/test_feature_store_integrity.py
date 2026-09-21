"""Regression contracts for JSON feature-store integrity."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.control_plane import features
from plugins.bot_unified_runtime.control_plane.features import (
    FeatureDescriptor,
    FeatureRegistry,
    FeatureStateStore,
)


def node(
    name: str,
    parent: str | None = None,
    dependencies: tuple[str, ...] = (),
    *,
    default_enabled: bool = True,
) -> FeatureDescriptor:
    return FeatureDescriptor(
        name, parent, "feature", name,
        dependencies=dependencies, default_enabled=default_enabled,
    )


@pytest.mark.parametrize("missing", ["parent", "dependency"])
def test_registry_rejects_missing_references(missing: str) -> None:
    descriptor = node("a", "missing") if missing == "parent" else node("a", dependencies=("missing",))
    with pytest.raises(ValueError, match="missing"):
        FeatureRegistry((descriptor,))


@pytest.mark.parametrize("descriptors", [
    (node("a", "a"),),
    (node("a", dependencies=("a",)),),
    (node("a", "b"), node("b", "a")),
    (node("a", dependencies=("b",)), node("b", dependencies=("a",))),
    (node("a", "b"), node("b", dependencies=("a",))),
    (node("a", dependencies=("b",)), node("b", "c"), node("c", dependencies=("a",))),
])
def test_registry_rejects_parent_dependency_union_cycles(descriptors: tuple[FeatureDescriptor, ...]) -> None:
    with pytest.raises(ValueError, match="cycle"):
        FeatureRegistry(descriptors)


def test_shared_prerequisites_are_not_cycles(tmp_path: Path) -> None:
    descriptors = (
        node("leaf", "left", ("right",)),
        node("left", "root"), node("right", dependencies=("root",)), node("root"),
    )
    store = FeatureStateStore(tmp_path / "features.json", descriptors=descriptors)
    assert store.get("leaf").effective_enabled
    store.set_enabled("root", False, actor="admin")
    assert not store.get("leaf").effective_enabled


@pytest.mark.parametrize("target", [
    "bot", "bot.plugin.control_plane", "bot.control_plane", "bot.audit",
    "bot.error_handling", "bot.persona.safety",
])
def test_default_protected_nodes_and_ancestors_cannot_be_disabled(tmp_path: Path, target: str) -> None:
    store = FeatureStateStore(tmp_path / "features.json")
    before = store.list_states()
    with pytest.raises(PermissionError, match="protected"):
        store.set_enabled(target, False, actor="admin")
    assert store.list_states() == before
    assert store.audit() == ()
    assert not store.path.exists()


def protected_graph(*, default_enabled: bool = True) -> tuple[FeatureDescriptor, ...]:
    return (
        node("root", default_enabled=default_enabled),
        node("dependency", "root", default_enabled=default_enabled),
        node("parent", dependencies=("dependency",), default_enabled=default_enabled),
        node("bot.audit", "parent", default_enabled=default_enabled),
        node("unrelated"),
    )


@pytest.mark.parametrize("target", ["root", "dependency", "parent", "bot.audit"])
def test_transitive_protected_prerequisites_cannot_be_disabled(tmp_path: Path, target: str) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=protected_graph())
    with pytest.raises(PermissionError, match="protected"):
        store.set_enabled(target, False, actor="admin")
    assert store.get("bot.audit").effective_enabled
    assert store.audit() == ()
    store.set_enabled("unrelated", False, actor="admin")
    assert not store.get("unrelated").effective_enabled


@pytest.mark.parametrize("target", ["root", "dependency", "parent", "bot.audit"])
def test_reset_cannot_disable_protected_prerequisites(tmp_path: Path, target: str) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=protected_graph(default_enabled=False))
    for feature_id in ("root", "dependency", "parent", "bot.audit"):
        store.set_enabled(feature_id, True, actor="admin")
    before, audit, disk = store.list_states(), store.audit(), store.path.read_bytes()
    with pytest.raises(PermissionError, match="protected"):
        store.reset(target, actor="admin", expected_version=1)
    assert store.list_states() == before
    assert store.audit() == audit
    assert store.path.read_bytes() == disk


def test_reset_retains_monotonic_versions_and_metadata_after_reload(tmp_path: Path) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=(node("a"),))
    store.set_enabled("a", False, actor="first", expected_version=0)
    result = store.reset("a", actor="resetter", expected_version=1)
    assert set(result) == {"state", "audit_id"}
    assert result["state"]["version"] == 2
    assert result["state"]["explicit_enabled"] is None
    assert result["state"]["effective_enabled"] is True
    assert result["state"]["updated_by"] == "resetter"
    assert result["state"]["updated_at"]
    store = FeatureStateStore(store.path, descriptors=(node("a"),))
    assert store.get("a").version == 2
    with pytest.raises(RuntimeError, match="version conflict"):
        store.set_enabled("a", False, actor="stale", expected_version=0)
    assert store.reset("a", actor="again", expected_version=2)["state"]["version"] == 3
    assert store.set_enabled("a", False, actor="last", expected_version=3)["state"]["version"] == 4


@pytest.mark.parametrize("operation", ["set", "reset"])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["save", "replace"])
def test_save_failure_rolls_back_state_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, existing: bool, failure: str,
) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=(node("a"), node("other")))
    store.set_enabled("other", False, actor="seed")
    if existing:
        store.set_enabled("a", False, actor="seed")
    before, audit, disk = store.list_states(), store.audit(), store.path.read_bytes()
    raw_before = json.loads(json.dumps(store._states))
    version = store.get("a").version

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("injected persistence failure")

    with monkeypatch.context() as patch:
        patch.setattr(store if failure == "save" else features.os, "_save" if failure == "save" else "replace", fail)
        with pytest.raises(OSError, match="injected"):
            if operation == "set":
                store.set_enabled("a", True, actor="failed", expected_version=version)
            else:
                store.reset("a", actor="failed", expected_version=version)
    assert store.list_states() == before
    assert store._states == raw_before
    assert store.audit() == audit
    assert store.path.read_bytes() == disk
    reloaded = FeatureStateStore(store.path, descriptors=(node("a"), node("other")))
    assert reloaded.list_states() == before
    assert store.set_enabled("a", True, actor="retry", expected_version=version)["state"]["version"] == version + 1


@pytest.mark.parametrize("operation", ["set", "reset"])
@pytest.mark.parametrize("request_id", [None, "request-123"])
def test_audit_has_before_after_and_optional_request_id(
    tmp_path: Path, operation: str, request_id: str | None,
) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=(node("a"),))
    before = asdict(store.get("a"))
    kwargs = {} if request_id is None else {"request_id": request_id}
    if operation == "set":
        result = store.set_enabled("a", False, actor="admin", **kwargs)
        assert set(result) == {"state", "audit_id", "affected"}
    else:
        result = store.reset("a", actor="admin", **kwargs)
    row = store.audit()[0]
    assert row["before"] == before
    assert row["after"] == result["state"]
    assert row["request_id"] == request_id
    assert row["audit_id"] == result["audit_id"]
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(payload) == {"states", "audit"}
    assert payload["audit"][0]["request_id"] == request_id
    assert payload["audit"][0]["after"]["version"] == result["state"]["version"]
    row["after"]["version"] = -1
    assert store.audit()[0]["after"]["version"] == result["state"]["version"]


def test_legacy_json_and_audit_remain_readable(tmp_path: Path) -> None:
    path = tmp_path / "features.json"
    legacy = {
        "states": {"a": {"explicit_enabled": False, "version": 7, "updated_by": "old"}},
        "audit": [{"feature_id": "a", "enabled": False, "version": 7, "actor": "old"}],
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    store = FeatureStateStore(path, descriptors=(node("a"),))
    assert not store.get("a").effective_enabled
    assert store.audit()[0] == legacy["audit"][0]
    store.reset("a", actor="new", expected_version=7)
    reloaded = FeatureStateStore(path, descriptors=(node("a"),))
    assert reloaded.get("a").version == 8
    assert reloaded.audit()[0] == legacy["audit"][0]


@pytest.mark.parametrize("operation", ["set", "reset"])
def test_version_conflict_does_not_write_or_audit(tmp_path: Path, operation: str) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=(node("a"),))
    with pytest.raises(RuntimeError, match="version conflict"):
        if operation == "set":
            store.set_enabled("a", False, actor="stale", expected_version=10)
        else:
            store.reset("a", actor="stale", expected_version=10)
    assert store.get("a").version == 0
    assert store.audit() == ()
    assert not store.path.exists()


def dependency_graph() -> tuple[FeatureDescriptor, ...]:
    return (
        node("source"), node("child", "source"),
        node("consumer", dependencies=("source",)),
        node("nested", "consumer"),
        node("diamond", "child", ("nested",)), node("unrelated"),
    )


@pytest.mark.parametrize("enabled", [True, False, None])
def test_preview_includes_transitive_dependents_without_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool | None,
) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=dependency_graph())
    store.set_enabled("source", False, actor="seed")
    before, audit, disk = store.list_states(), store.audit(), store.path.read_bytes()

    def unexpected_save() -> None:
        pytest.fail("preview must not persist")

    monkeypatch.setattr(store, "_save", unexpected_save)
    result = store.preview("source", enabled, expected_version=1)
    expected_ids = {"source", "child", "consumer", "nested", "diamond"}
    assert set(result) == {"state", "affected", "affected_ids"}
    assert set(result["affected_ids"]) == expected_ids
    assert len(result["affected_ids"]) == len(expected_ids)
    assert result["affected_ids"] == [item["feature_id"] for item in result["affected"]]
    assert result["state"]["explicit_enabled"] is enabled
    assert result["state"]["version"] == 2
    assert all(item["effective_enabled"] == (enabled is not False) for item in result["affected"])
    assert store.list_states() == before
    assert store.audit() == audit
    assert store.path.read_bytes() == disk


@pytest.mark.parametrize("enabled", [False, None])
def test_preview_uses_mutation_protection_rules(tmp_path: Path, enabled: bool | None) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=protected_graph(default_enabled=False))
    for feature_id in ("root", "dependency", "parent", "bot.audit"):
        store.set_enabled(feature_id, True, actor="admin")
    before, audit, disk = store.list_states(), store.audit(), store.path.read_bytes()
    with pytest.raises(PermissionError, match="protected"):
        store.preview("dependency", enabled, expected_version=1)
    assert store.list_states() == before
    assert store.audit() == audit
    assert store.path.read_bytes() == disk


def test_preview_rejects_stale_version_and_unknown_feature(tmp_path: Path) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=(node("a"),))
    with pytest.raises(RuntimeError, match="version conflict"):
        store.preview("a", False, expected_version=1)
    with pytest.raises(KeyError):
        store.preview("missing", False, expected_version=0)
    assert store.get("a").version == 0
    assert store.audit() == ()
    assert not store.path.exists()


def test_mutation_and_preview_share_dependency_impact_set(tmp_path: Path) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=dependency_graph())
    preview = store.preview("source", False, 0)
    changed = store.set_enabled("source", False, actor="admin", expected_version=0)
    assert [row["feature_id"] for row in changed["affected"]] == preview["affected_ids"]
    assert store.audit()[0]["affected"] == preview["affected_ids"]


def test_preview_restores_state_when_projection_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=dependency_graph())
    before = store.list_states()
    original_get = store.get

    def fail_on_consumer(feature_id: str):
        if feature_id == "consumer" and store._explicit("source") is False:
            raise RuntimeError("injected projection failure")
        return original_get(feature_id)

    with monkeypatch.context() as patch:
        patch.setattr(store, "get", fail_on_consumer)
        with pytest.raises(RuntimeError, match="injected projection"):
            store.preview("source", False, 0)
    assert store.list_states() == before
    assert store.audit() == ()
    assert not store.path.exists()


@pytest.mark.parametrize("operation", ["set", "reset"])
def test_persistence_permission_error_is_not_a_protection_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    store = FeatureStateStore(tmp_path / "features.json", descriptors=(node("a"),))
    before = store.list_states()

    def denied() -> None:
        raise PermissionError("disk permission denied")

    monkeypatch.setattr(store, "_save", denied)
    with pytest.raises(OSError) as caught:
        if operation == "set":
            store.set_enabled("a", False, actor="admin")
        else:
            store.reset("a", actor="admin")
    assert not isinstance(caught.value, PermissionError)
    assert isinstance(caught.value.__cause__, PermissionError)
    assert store.list_states() == before
    assert store.audit() == ()


def test_preview_holds_lock_until_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    store = FeatureStateStore(tmp_path / "features.json", descriptors=(node("a"),))
    projected, release, reader_started = Event(), Event(), Event()
    original_asdict = features.asdict

    def pause_projection(value):
        if value.feature_id == "a" and value.explicit_enabled is False:
            projected.set()
            assert release.wait(5), "preview was not released"
        return original_asdict(value)

    def read_state():
        reader_started.set()
        return store.get("a")

    monkeypatch.setattr(features, "asdict", pause_projection)
    with ThreadPoolExecutor(max_workers=2) as executor:
        preview = executor.submit(store.preview, "a", False, 0)
        try:
            assert projected.wait(5), "preview never reached staged projection"
            reader = executor.submit(read_state)
            assert reader_started.wait(5)
            assert not reader.done(), "reader observed uncommitted preview state"
        finally:
            release.set()
        assert preview.result(timeout=5)["state"]["effective_enabled"] is False
        assert reader.result(timeout=5).effective_enabled is True
    assert store.get("a").version == 0
    assert store.audit() == ()
    assert not store.path.exists()


def test_concurrent_mutations_have_one_version_winner(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store = FeatureStateStore(tmp_path / "features.json", descriptors=(node("a"),))
    barrier = Barrier(2)

    def mutate():
        barrier.wait(timeout=5)
        try:
            store.set_enabled("a", False, actor="writer", expected_version=0)
        except RuntimeError as exc:
            assert "version conflict" in str(exc)
            return "conflict"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(mutate) for _ in range(2)]
        assert sorted(result.result(timeout=5) for result in results) == ["conflict", "saved"]
    assert store.get("a").version == 1
    assert len(store.audit()) == 1


def test_large_registry_validates_and_traverses_without_recursive_stack_growth() -> None:
    # Bounded structural stress test: depth exceeds Python's normal recursion
    # limit; shared parent/dependency edges must not duplicate the impact set.
    descriptors = (node("0"),) + tuple(
        node(str(index), str(index - 1), (str(index - 1),))
        for index in range(1, 2000)
    )
    registry = FeatureRegistry(descriptors)
    affected = registry.affected("0")
    assert len(affected) == len(descriptors)
    assert affected[-1].id == "1999"

@pytest.mark.parametrize("contents", ["{", "[]", "{}", '{"states": [], "audit": []}', '{"states":{"bot":{"explicit_enabled":"false","version":0}},"audit":[]}', '{"states":{"bot":{"explicit_enabled":true,"version":-1}},"audit":[]}'])
def test_corrupt_state_file_does_not_silently_enable_everything(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "features.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid feature state"):
        FeatureStateStore(path)
    assert path.read_text(encoding="utf-8") == contents

def test_audit_memory_is_bounded_and_failed_append_restores_tail(tmp_path: Path, monkeypatch) -> None:
    store = FeatureStateStore(tmp_path / "features.json")
    monkeypatch.setattr(store, "_save", lambda: None)
    for i in range(205):
        store.set_enabled("bot.plugin.weather", bool(i % 2), actor="root")
    assert len(store._audit) == 200
    before = list(store._audit)
    def fail():
        raise OSError("disk full")
    monkeypatch.setattr(store, "_save", fail)
    with pytest.raises(OSError):
        store.set_enabled("bot.plugin.weather", True, actor="root")
    assert store._audit == before
