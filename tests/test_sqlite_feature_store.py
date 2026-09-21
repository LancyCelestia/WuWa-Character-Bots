"""SQLite feature-store contracts; all persistence is isolated in tmp_path."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from time import perf_counter

import pytest

from plugins.bot_unified_runtime.control_plane.features import (
    FeatureDescriptor,
    FeatureState,
    FeatureStateStore,
    InvalidFeatureStateError,
)

MODULE = "plugins.bot_unified_runtime.control_plane.sqlite_features"
GRAPH = (
    FeatureDescriptor("root", None, "group", "Root"),
    FeatureDescriptor("parent", "root", "plugin", "Parent"),
    FeatureDescriptor("child", "parent", "feature", "Child"),
    FeatureDescriptor("consumer", "root", "feature", "Consumer", dependencies=("child",)),
    FeatureDescriptor("other", "root", "feature", "Other"),
)


@pytest.fixture
def store_type():
    assert importlib.util.find_spec(MODULE) is not None, "SQLite feature store is not implemented"
    return importlib.import_module(MODULE).SQLiteFeatureStateStore


@pytest.fixture
def store(store_type, tmp_path):
    return store_type(tmp_path / "specified" / "features.sqlite3", descriptors=GRAPH)


def test_feature_state_exposes_default_graph_revision():
    state = FeatureState("node", None, True, None)
    assert getattr(state, "graph_revision", None) == 0


def test_empty_database_and_cross_instance_visibility(store, store_type):
    assert store.supports_graph_revision is True
    peer = store_type(store.path, descriptors=GRAPH)
    assert all(s.graph_revision == s.version == 0 for s in store.list_states())
    assert store.audit() == ()
    result = store.set_enabled("parent", False, actor="admin", expected_revision=0, request_id="r1")
    assert set(result) == {"audit_id", "state", "affected"}
    assert result["state"]["graph_revision"] == result["state"]["version"] == 1
    assert all(s["graph_revision"] == 1 for s in result["affected"])
    assert not peer.get("consumer").effective_enabled
    assert peer.get("consumer").version == 0
    assert peer.get("other").graph_revision == 1
    audit = peer.audit()[0]
    assert audit["request_id"] == "r1"
    assert audit["before"]["graph_revision"] == 0
    assert audit["after"]["graph_revision"] == 1
    reset = peer.reset("parent", actor="admin", expected_revision=1, expected_version=1)
    assert set(reset) == {"state", "audit_id"}
    assert reset["state"]["version"] == 2
    assert store.get("consumer").effective_enabled
    assert store.get("consumer").graph_revision == 2


@pytest.mark.parametrize("method", ["set_enabled", "reset", "preview"])
@pytest.mark.parametrize("revision", ["missing", None, True, -1, 1.0, "0"])
def test_mutation_and_preview_require_integer_revision(store, method, revision):
    args = ("parent",) if method == "reset" else ("parent", False)
    kwargs = {"expected_version": 0} if method == "preview" else {"actor": "admin"}
    if revision != "missing":
        kwargs["expected_revision"] = revision
    with pytest.raises(ValueError, match="expected_revision"):
        getattr(store, method)(*args, **kwargs)
    assert store.get("parent").version == 0
    assert store.audit() == ()


@pytest.mark.parametrize("method", ["set_enabled", "reset", "preview"])
def test_stale_graph_revision_rejects_unchanged_node(store, store_type, method):
    peer = store_type(store.path, descriptors=GRAPH)
    store.set_enabled("parent", False, actor="admin", expected_revision=0)
    args = ("child",) if method == "reset" else ("child", True)
    kwargs = {"expected_version": 0, "expected_revision": 0}
    if method != "preview":
        kwargs["actor"] = "admin"
    with pytest.raises(RuntimeError, match="revision conflict"):
        getattr(peer, method)(*args, **kwargs)
    assert len(store.audit()) == 1
    assert store.get("child").version == 0


def test_local_version_conflict_is_still_enforced(store):
    with pytest.raises(RuntimeError, match="version conflict"):
        store.set_enabled("child", False, actor="a", expected_version=9, expected_revision=0)
    assert store.get("root").graph_revision == 0


def test_preview_reuses_projection_without_persisting(store, monkeypatch):
    before = store.path.read_bytes()
    calls = []
    original = FeatureStateStore.preview

    def tracked(self, *args, **kwargs):
        calls.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FeatureStateStore, "preview", tracked)
    preview = store.preview("parent", False, 0, expected_revision=0)
    assert calls == [True]
    assert set(preview) == {"state", "affected", "affected_ids"}
    assert preview["state"]["graph_revision"] == 1
    assert {s["feature_id"] for s in preview["affected"]} == {"parent", "child", "consumer"}
    assert all(not s["effective_enabled"] for s in preview["affected"])
    assert store.path.read_bytes() == before
    assert store.get("parent").version == 0
    assert store.audit() == ()
    changed = store.set_enabled("parent", False, actor="a", expected_revision=0)
    for expected, actual in zip(preview["affected"], changed["affected"], strict=True):
        for key in ("version", "graph_revision", "effective_enabled", "blocked_by"):
            assert expected[key] == actual[key]
    assert store.preview("parent", None, 1, expected_revision=1)["state"]["explicit_enabled"] is None


@pytest.mark.parametrize("method", ["set_enabled", "reset", "preview"])
def test_reuses_protection_for_dependency_graph(store_type, tmp_path, method):
    graph = (
        FeatureDescriptor("source", None, "feature", "Source", default_enabled=False),
        FeatureDescriptor("bot.audit", None, "feature", "Audit", dependencies=("source",)),
    )
    store = store_type(tmp_path / "features.db", descriptors=graph)
    args = ("source",) if method == "reset" else ("source", False)
    kwargs = {"expected_revision": 0, "expected_version": 0}
    if method != "preview":
        kwargs["actor"] = "a"
    with pytest.raises(PermissionError, match="protected"):
        getattr(store, method)(*args, **kwargs)
    assert store.audit() == ()
    assert store.get("source").graph_revision == 0


def test_concurrent_instances_only_one_cas_wins(store, store_type):
    peer = store_type(store.path, descriptors=GRAPH)
    barrier = threading.Barrier(2)

    def change(instance, target):
        barrier.wait(timeout=10)
        try:
            instance.set_enabled(target, False, actor="a", expected_revision=0)
            return "commit"
        except RuntimeError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(change, store, "parent"), pool.submit(change, peer, "other")]
        assert sorted(f.result(timeout=15) for f in futures) == ["commit", "conflict"]
    assert len(store.audit()) == 1
    assert {s.graph_revision for s in store.list_states()} == {1}


def test_readonly_graph_snapshot_cannot_mix_commits(store, store_type, monkeypatch):
    peer = store_type(store.path, descriptors=GRAPH)
    entered = threading.Event()
    release = threading.Event()
    original = FeatureStateStore.get
    reader_thread = None
    paused = False

    def paused_get(self, feature_id):
        nonlocal paused
        if threading.get_ident() == reader_thread and not paused:
            paused = True
            entered.set()
            assert release.wait(timeout=10)
        return original(self, feature_id)

    def read():
        nonlocal reader_thread
        reader_thread = threading.get_ident()
        return store.list_states()

    monkeypatch.setattr(FeatureStateStore, "get", paused_get)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(read)
        assert entered.wait(timeout=10)
        writer = pool.submit(peer.set_enabled, "parent", False, actor="a", expected_revision=0)
        release.set()
        snapshot = reader.result(timeout=15)
        writer.result(timeout=15)
    assert {s.graph_revision for s in snapshot} == {0}
    assert all(s.effective_enabled for s in snapshot)
    assert not store.get("consumer").effective_enabled


@pytest.mark.parametrize("failed_table", ["feature_states", "feature_audit", "feature_meta"])
def test_database_failure_rolls_back_state_audit_and_revision(store, failed_table):
    before = store.list_states()
    event = "UPDATE" if failed_table == "feature_meta" else "INSERT"
    with sqlite3.connect(store.path) as db:
        db.execute(f"CREATE TRIGGER fail_write BEFORE {event} ON {failed_table} "
                   "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with pytest.raises((sqlite3.DatabaseError, OSError)):
        store.set_enabled("parent", False, actor="a", expected_revision=0)
    assert store.list_states() == before
    assert store.audit() == ()
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TRIGGER fail_write")
    assert store.set_enabled("parent", False, actor="a", expected_revision=0)["state"]["graph_revision"] == 1


def test_audit_is_retained_beyond_200_but_api_returns_latest_100(store, store_type):
    started = perf_counter()
    for revision in range(205):
        store.set_enabled("parent", bool(revision % 2), actor="a", expected_revision=revision)
    elapsed = perf_counter() - started
    peer = store_type(store.path, descriptors=GRAPH)
    assert len(peer.audit()) == len(peer.audit("parent")) == 100
    assert peer.audit()[0]["version"] == 106
    assert peer.audit()[0]["after"]["graph_revision"] == 106
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM feature_audit").fetchone()[0] == 205
    rows = peer.audit()
    rows[-1]["after"]["version"] = -1
    assert peer.audit()[-1]["after"]["version"] == 205
    print(f"205 durable SQLite commits: {elapsed:.3f}s")


def legacy_file(tmp_path, *, audit_count=1):
    path = tmp_path / "legacy.json"
    payload = {
        "states": {"parent": {"explicit_enabled": False, "version": 7, "updated_by": "legacy"}},
        "audit": [{"feature_id": "parent", "version": i} for i in range(audit_count)],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_legacy_import_is_explicit_atomic_and_preserves_entire_history(store, store_type, tmp_path):
    legacy = legacy_file(tmp_path, audit_count=250)
    original = legacy.read_bytes()
    assert store.get("parent").effective_enabled
    assert store.import_legacy(legacy) is True
    assert legacy.read_bytes() == original
    peer = store_type(store.path, descriptors=GRAPH)
    assert peer.get("parent").version == 7
    assert peer.get("consumer").graph_revision == 1
    assert not peer.get("consumer").effective_enabled
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM feature_audit").fetchone()[0] == 250
    assert peer.import_legacy(legacy) is False
    assert peer.get("root").graph_revision == 1
    assert legacy.read_bytes() == original


def test_import_cannot_overwrite_existing_state(store, tmp_path):
    legacy = legacy_file(tmp_path)
    store.set_enabled("other", False, actor="a", expected_revision=0)
    before = store.list_states(), store.audit()
    assert store.import_legacy(legacy) is False
    assert (store.list_states(), store.audit()) == before


def test_empty_import_is_marked_and_cannot_be_replayed(store, tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text('{"states": {}, "audit": []}', encoding="utf-8")
    assert store.import_legacy(legacy) is True
    assert store.get("root").graph_revision == 1
    legacy_file(tmp_path)
    assert store.import_legacy(legacy) is False
    assert store.get("parent").effective_enabled


def test_failed_import_rolls_back_and_can_retry(store, tmp_path):
    legacy = legacy_file(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER fail_import BEFORE INSERT ON feature_audit "
                   "BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises((sqlite3.DatabaseError, OSError)):
        store.import_legacy(legacy)
    assert store.get("root").graph_revision == 0
    assert store.get("parent").effective_enabled
    assert store.audit() == ()
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TRIGGER fail_import")
    assert store.import_legacy(legacy) is True


@pytest.mark.parametrize("payload", [
    "not json", "[]", "{}", '{"states": {}, "audit": [null]}',
    '{"states": {"parent": {"explicit_enabled": "false"}}, "audit": []}',
    '{"states": {"parent": {"version": true}}, "audit": []}',
    '{"states": {"parent": {"version": -1}}, "audit": []}',
])
def test_corrupt_json_fails_closed_without_marking_import(store, tmp_path, payload):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(payload, encoding="utf-8")
    with pytest.raises(InvalidFeatureStateError):
        store.import_legacy(legacy)
    assert store.get("root").graph_revision == 0
    assert legacy.read_text(encoding="utf-8") == payload
    assert store.import_legacy(legacy_file(tmp_path)) is True


def test_missing_legacy_file_is_not_empty_import(store, tmp_path):
    with pytest.raises(FileNotFoundError):
        store.import_legacy(tmp_path / "missing.json")
    assert store.get("root").graph_revision == 0


def test_corrupt_database_is_never_replaced(store_type, tmp_path):
    path = tmp_path / "bad.db"
    original = b"not a sqlite database"
    path.write_bytes(original)
    with pytest.raises((sqlite3.DatabaseError, OSError, InvalidFeatureStateError)):
        store_type(path, descriptors=GRAPH)
    assert path.read_bytes() == original


def test_missing_schema_fails_closed_without_reinitializing(store, store_type):
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TABLE feature_states")
    with pytest.raises((sqlite3.DatabaseError, OSError, InvalidFeatureStateError)):
        store_type(store.path, descriptors=GRAPH)
    with pytest.raises((sqlite3.DatabaseError, OSError, InvalidFeatureStateError)):
        store.get("parent")


def test_deleted_database_not_recreated_by_read_or_write(store):
    store.path.unlink()
    with pytest.raises((sqlite3.DatabaseError, OSError)):
        store.get("root")
    with pytest.raises((sqlite3.DatabaseError, OSError)):
        store.set_enabled("parent", False, actor="a", expected_revision=0)
    assert not store.path.exists()


def test_original_json_store_semantics_are_unchanged(tmp_path):
    store = FeatureStateStore(tmp_path / "legacy.json", descriptors=GRAPH)
    result = store.set_enabled("parent", False, actor="admin")
    assert result["state"]["version"] == 1
    assert result["state"]["graph_revision"] == 0
    assert asdict(store.get("child"))["graph_revision"] == 0


@pytest.mark.parametrize("method", ["set_enabled", "reset", "preview"])
def test_descriptor_protected_flag_is_inherited_from_original_logic(store_type, tmp_path, method):
    graph = (
        FeatureDescriptor("source", None, "feature", "Source", default_enabled=False),
        FeatureDescriptor("runtime.status", None, "feature", "Status", dependencies=("source",), protected=True),
    )
    store = store_type(tmp_path / "features.db", descriptors=graph)
    args = ("source",) if method == "reset" else ("source", False)
    kwargs = {"expected_revision": 0, "expected_version": 0}
    if method != "preview":
        kwargs["actor"] = "a"
    with pytest.raises(PermissionError, match="protected"):
        getattr(store, method)(*args, **kwargs)
    assert store.get("source").graph_revision == 0


@pytest.mark.parametrize("payload", [
    '{"states": {}, "states": {"parent": {}}, "audit": []}',
    '{"states": {}, "audit": [{"invalid": NaN}]}',
    '{"states": {}, "audit": [{"invalid": Infinity}]}',
])
def test_ambiguous_or_nonstandard_legacy_json_fails_closed(store, tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(InvalidFeatureStateError):
        store.import_legacy(path)
    assert store.get("root").graph_revision == 0


def test_existing_empty_file_is_not_silently_initialized(store_type, tmp_path):
    path = tmp_path / "truncated.db"
    path.write_bytes(b"")
    with pytest.raises(InvalidFeatureStateError):
        store_type(path, descriptors=GRAPH)
    assert path.read_bytes() == b""


def test_commit_failure_rolls_back_everything(store, monkeypatch):
    original = sqlite3.connect

    class FailCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("injected commit failure")

    def connect(*args, **kwargs):
        return original(*args, **kwargs, factory=FailCommit)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        with pytest.raises(OSError, match="persistence"):
            store.set_enabled("parent", False, actor="a", expected_revision=0)
    assert store.get("parent").version == store.get("parent").graph_revision == 0
    assert store.audit() == ()


@pytest.mark.parametrize("method", ["get", "list_states", "preview", "set_enabled"])
def test_malformed_state_in_database_fails_closed(store, method):
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO feature_states VALUES (?, ?)", ("parent", '{"explicit_enabled": "false"}'))
    kwargs = {}
    args = () if method == "list_states" else ("parent",)
    if method in ("preview", "set_enabled"):
        args = ("parent", False)
        kwargs = {"expected_version": 0, "expected_revision": 0}
        if method == "set_enabled":
            kwargs["actor"] = "a"
    with pytest.raises(InvalidFeatureStateError):
        getattr(store, method)(*args, **kwargs)


def test_concurrent_imports_are_idempotent(store, store_type, tmp_path):
    peer = store_type(store.path, descriptors=GRAPH)
    path = legacy_file(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(s.import_legacy, path) for s in (store, peer)]
        assert sorted(f.result(timeout=10) for f in futures) == [False, True]
    assert len(store.audit()) == 1
    assert store.get("root").graph_revision == 1


def test_database_artifacts_stay_at_explicit_path(store_type, tmp_path, monkeypatch):
    cwd = tmp_path / "unrelated"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    path = tmp_path / "指定 %# directory" / "features %#.db"
    store = store_type(path, descriptors=GRAPH)
    store.set_enabled("parent", False, actor="a", expected_revision=0)
    assert store.path == path
    assert list(cwd.iterdir()) == []
    assert {p.name for p in path.parent.iterdir()} == {path.name}


def test_read_transactions_do_not_write_and_write_locks_precede_load(store, monkeypatch):
    statements = []
    original = sqlite3.connect

    def connect(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(sqlite3, "connect", connect)
    store.get("root")
    store.list_states()
    store.audit()
    store.preview("parent", False, 0, expected_revision=0)
    assert not any(s.startswith(("UPDATE", "INSERT", "DELETE", "CREATE", "BEGIN IMMEDIATE")) for s in statements)
    statements.clear()
    store.set_enabled("parent", False, actor="a", expected_revision=0)
    assert statements.index("BEGIN IMMEDIATE") < next(i for i, s in enumerate(statements) if s.startswith("SELECT"))
    assert statements[-1] == "COMMIT"


def test_metadata_and_states_share_one_sqlite_read_snapshot(store, store_type, monkeypatch):
    # WAL lets a real writer commit between the reader's metadata and state SELECTs.
    with sqlite3.connect(store.path) as db:
        db.execute("PRAGMA journal_mode=WAL")
    peer = store_type(store.path, descriptors=GRAPH)
    entered, release = threading.Event(), threading.Event()
    reader_thread = None
    original = store_type._meta

    def pause_after_meta(db):
        result = original(db)
        if threading.get_ident() == reader_thread:
            entered.set()
            assert release.wait(timeout=10)
        return result

    def read():
        nonlocal reader_thread
        reader_thread = threading.get_ident()
        return store.list_states()

    monkeypatch.setattr(store_type, "_meta", staticmethod(pause_after_meta))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read)
        try:
            assert entered.wait(timeout=10)
            peer.set_enabled("parent", False, actor="a", expected_revision=0)
        finally:
            release.set()
        snapshot = future.result(timeout=10)
    assert {s.graph_revision for s in snapshot} == {0}
    assert all(s.effective_enabled for s in snapshot)
    assert not store.get("consumer").effective_enabled
