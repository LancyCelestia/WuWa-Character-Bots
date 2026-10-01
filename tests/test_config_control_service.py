"""配置事务层：仅使用 tmp_path 的 SQLite/JSON，不读取生产设置。"""
from __future__ import annotations

import importlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.control_plane.services import ControlServiceError
from plugins.bot_unified_runtime.domains.chat_reply.runtime import settings

KEY = "BOT_CHAT_TEMPERATURE"
#: F-1（SEAT-ATKFIX-CFG12）后 legacy 导入只带 R0 档：迁移/导入腿改用超时族真字段。
R0_KEY = "BOT_TRANSPORT_TIMEOUT_SECONDS"
ADMIN = Principal("test-admin", ("super_admin",))


@pytest.fixture
def api():
    store = importlib.import_module("plugins.bot_unified_runtime.control_plane.config_store")
    service = importlib.import_module("plugins.bot_unified_runtime.control_plane.config_service")
    return SimpleNamespace(Store=store.SQLiteConfigStateStore,
                           Conflict=store.ConfigVersionConflict,
                           Service=service.ConfigControlService)


@pytest.fixture
def setup(api, tmp_path):
    backend = api.Store(tmp_path / "config.sqlite3")
    config = SimpleNamespace(bot_chat_temperature=0.5, bot_chat_model="default-model")
    # allow_no_gate：本件测的是事务/CAS/审计语义，不是档位执法（咽喉测试在
    # test_safety_exec_session_throat / test_control_plane_consent_throat）。
    runtime = settings.RuntimeSettingsStore(tmp_path / "legacy.json", backend=backend, allow_no_gate=True)
    service = api.Service(config, backend, runtime_settings=runtime)
    return backend, runtime, service


def test_schema_and_legacy_shape(setup):
    backend, _, service = setup
    rows = service.schema()
    assert {row["key"] for row in rows} == set(settings.SETTABLE_KEYS) | set(settings.RESTART_REQUIRED_KEYS)
    assert rows == service.list()
    row = service.get(KEY.lower())
    assert row.items() >= {"key": KEY, "value": 0.5, "source": "config", "sensitive": False,
                           "hot_reload": True, "restart_required": False, "version": 0,
                           "state": "default", "fingerprint": None}.items()
    assert "description" in row
    assert backend.snapshot().version == 0


def test_preview_is_validated_and_does_not_write(setup):
    backend, runtime, service = setup
    notices = []
    runtime.register_change_listener(lambda: notices.append(True))
    row = service.preview(KEY, "0.7", principal=ADMIN, expected_version=0)
    assert row["value"] == 0.7 and row["preview"] is True and row["version"] == 0
    assert backend.snapshot().version == 0
    assert backend.changes() == [] and notices == []
    with pytest.raises(ControlServiceError) as exc:
        service.preview(KEY, "not-a-number", principal=ADMIN, expected_version=0)
    assert exc.value.status_code == 422


def test_same_instance_visibility_and_other_instance_isolation(api, setup, tmp_path):
    backend, runtime, service = setup
    peer = api.Store(backend.path)
    other = api.Store(backend.path, instance="another")
    peer_runtime = settings.RuntimeSettingsStore(tmp_path / "peer.json", backend=peer)
    changed = service.set(KEY, 0.8, principal=ADMIN, expected_version=0, request_id="req-1")
    assert changed["value"] == 0.8 and changed["version"] == 1
    assert runtime.get_or(KEY, 0) == peer_runtime.get_or(KEY, 0) == 0.8
    assert other.snapshot().version == 0 and other.snapshot().overrides == {}
    event = service.changes()[0]
    assert event["actor"] == ADMIN.subject and event["request_id"] == "req-1"
    assert event["version"] == 1 and event["action"] == "set"


def test_cas_rejects_stale_write_and_preview(setup):
    backend, _, service = setup
    service.set(KEY, "0.7", principal=ADMIN, expected_version=0)
    for method in (service.set, service.preview):
        with pytest.raises(ControlServiceError) as exc:
            method(KEY, "0.9", principal=ADMIN, expected_version=0)
        assert exc.value.code == "version_conflict" and exc.value.status_code == 409
    with pytest.raises(ControlServiceError):
        service.reset(KEY, principal=ADMIN, expected_version=0)
    assert backend.snapshot().version == 1
    assert len(service.changes()) == 1


@pytest.mark.parametrize("version", [None, True, -1, "0", 0.0])
def test_version_must_be_integer(setup, version):
    _, _, service = setup
    with pytest.raises(ControlServiceError) as exc:
        service.set(KEY, "0.8", principal=ADMIN, expected_version=version)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("method", ["set", "reset", "preview"])
def test_only_super_admin_and_registered_keys(setup, method):
    _, _, service = setup
    args = (KEY,) if method == "reset" else (KEY, "0.8")
    with pytest.raises(ControlServiceError) as exc:
        getattr(service, method)(*args, principal=Principal("admin"), expected_version=0)
    assert exc.value.status_code == 403
    args = ("BOT_UNKNOWN",) if method == "reset" else ("BOT_UNKNOWN", "0.8")
    with pytest.raises(ControlServiceError) as exc:
        getattr(service, method)(*args, principal=ADMIN, expected_version=0)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("key", sorted(settings.RESTART_REQUIRED_KEYS))
def test_restart_keys_are_readable_but_never_writable(setup, key):
    backend, _, service = setup
    row = service.get(key)
    assert row["restart_required"] and not row["hot_reload"]
    for method in ("set", "reset", "preview"):
        args = (key,) if method == "reset" else (key, "true")
        with pytest.raises(ControlServiceError) as exc:
            getattr(service, method)(*args, principal=ADMIN, expected_version=0)
        assert exc.value.code == "config_not_hot_reloadable"
    assert backend.snapshot().version == 0


def test_secret_never_leaks_in_any_dto_audit_or_errors(setup, monkeypatch):
    backend, _, service = setup
    key, secret = "BOT_TEST_API_KEY", "test-secret-unique-123"
    monkeypatch.setitem(settings.SETTABLE_KEYS, key, str)
    row = service.preview(key, secret, principal=ADMIN, expected_version=0)
    result = service.set(key, secret, principal=ADMIN, expected_version=0)
    assert result["value"] == "[redacted]" and result["fingerprint"]
    assert row["fingerprint"] == result["fingerprint"]
    assert backend.snapshot().overrides[key] == secret  # 内部消费允许取原值。
    payloads = [row, result, service.get(key), service.list(), service.schema(), service.changes(), backend.changes()]
    assert secret not in json.dumps(payloads)
    cleared = service.reset(key, principal=ADMIN, expected_version=1)
    assert cleared["value"] is None and cleared["state"] == "default"
    assert secret not in json.dumps(service.changes())
    def reject(value):
        raise ValueError(value)
    monkeypatch.setitem(settings.SETTABLE_KEYS, key, reject)
    with pytest.raises(ControlServiceError) as exc:
        service.set(key, secret, principal=ADMIN, expected_version=2)
    assert secret not in str(exc.value)


def test_audit_failure_rolls_back_value_revision_and_listener(setup):
    backend, runtime, service = setup
    notices = []
    runtime.register_change_listener(lambda: notices.append(True))
    with sqlite3.connect(backend.path) as conn:
        conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON config_audit BEGIN SELECT RAISE(ABORT, 'disk failed'); END")
    with pytest.raises(ControlServiceError) as exc:
        service.set(KEY, "0.8", principal=ADMIN, expected_version=0)
    assert exc.value.status_code == 503
    assert backend.snapshot().version == 0 and backend.snapshot().overrides == {}
    assert service.get(KEY)["value"] == 0.5 and notices == []
    assert service.changes() == []
    with pytest.raises(sqlite3.DatabaseError):
        runtime.set_override(KEY, "0.9")
    assert runtime.get_or(KEY, 0.5) == 0.5 and notices == []


def test_listener_observes_committed_state_and_audit(api, setup):
    backend, runtime, service = setup
    peer = api.Store(backend.path)
    notices = []
    runtime.register_change_listener(lambda: notices.append((peer.snapshot().version, peer.changes()[-1]["action"])))
    runtime.register_change_listener(lambda: (_ for _ in ()).throw(RuntimeError("listener failure")))
    service.set(KEY, "0.8", principal=ADMIN, expected_version=0)
    runtime.set_override(KEY, "0.9")
    assert backend.changes()[-1]["actor"] == "runtime_internal"
    runtime.reset_override(KEY)
    assert notices == [(1, "set"), (2, "set"), (3, "reset")]


def test_legacy_import_once_reset_never_resurrects(api, tmp_path):
    path = tmp_path / "legacy.json"
    # 迁移腿必须用 R0 键：F-1 后非 R0 档不经咽喉绝不入库（拒入留痕由
    # tests/test_atkfix_cfg12_throat_import_locks.py 的行为锁钉死）。
    original = json.dumps({"overrides": {R0_KEY: 5.0}, "nicknames": ["keeper"], "model_registry": {"x": {"model": "x"}}})
    path.write_text(original, encoding="utf-8")
    backend = api.Store(tmp_path / "config.sqlite3")
    runtime = settings.RuntimeSettingsStore(path, allow_no_gate=True)
    runtime.attach_config_backend(backend)
    assert runtime.get_or(R0_KEY, 0.5) == 5.0 and backend.snapshot().version == 1
    assert path.read_text(encoding="utf-8") == original
    runtime.reset_override(R0_KEY)
    assert R0_KEY in backend.snapshot().tombstones and runtime.get_or(R0_KEY, 0.5) == 0.5
    assert path.read_text(encoding="utf-8") == original
    reopened = settings.RuntimeSettingsStore(path, backend=api.Store(backend.path))
    assert reopened.get(R0_KEY, SimpleNamespace(bot_transport_timeout_seconds=0.4)) == 0.4
    assert reopened.list_overrides() == {} and len(backend.changes()) == 2
    assert reopened.list_nicknames() == ["keeper"] and reopened.list_model_registry() == {"x": {"model": "x"}}
    reopened.add_nickname("shore")
    assert json.loads(path.read_text(encoding="utf-8"))["overrides"] == {R0_KEY: 5.0}
    assert reopened.list_overrides() == {}


def test_empty_import_is_also_one_time(api, tmp_path):
    path = tmp_path / "legacy.json"
    backend = api.Store(tmp_path / "state.sqlite3")
    settings.RuntimeSettingsStore(path, backend=backend)
    path.write_text(json.dumps({"overrides": {KEY: 0.9}}), encoding="utf-8")
    runtime = settings.RuntimeSettingsStore(path, backend=api.Store(backend.path))
    assert runtime.list_overrides() == {}


def test_reset_before_import_does_not_revive_legacy(api, tmp_path):
    backend = api.Store(tmp_path / "state.sqlite3")
    backend.reset_override(KEY, expected_version=0, actor="internal")
    assert backend.import_legacy({KEY: 0.9}) is False
    assert backend.snapshot().overrides == {} and KEY in backend.snapshot().tombstones


def test_reset_all_is_one_atomic_audited_revision(setup):
    backend, runtime, _ = setup
    runtime.set_override(KEY, "0.8")
    runtime.set_override("BOT_CHAT_MODEL", "another-model")
    assert runtime.reset_override() == 2
    assert backend.snapshot().version == 3 and runtime.list_overrides() == {}
    assert len(backend.changes()) == 3 and backend.changes()[-1]["action"] == "reset"


def test_two_concurrent_cas_writers_only_one_wins(api, tmp_path):
    path = tmp_path / "state.sqlite3"
    stores = [api.Store(path), api.Store(path)]
    barrier = Barrier(2)
    def write(index):
        barrier.wait(timeout=5)
        try:
            stores[index].set_override(KEY, 0.7 + index / 10, expected_version=0, actor=str(index))
            return "ok"
        except api.Conflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, range(2))) == ["conflict", "ok"]
    assert stores[0].snapshot().version == 1 and len(stores[0].changes()) == 1


def test_attach_failure_does_not_switch_source(api, tmp_path, monkeypatch):
    runtime = settings.RuntimeSettingsStore(allow_no_gate=True)
    runtime.set_override(KEY, "0.7")
    backend = api.Store(tmp_path / "state.sqlite3")
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("failed")
    monkeypatch.setattr(backend, "import_legacy", fail)
    with pytest.raises(sqlite3.OperationalError):
        runtime.attach_config_backend(backend)
    assert runtime.config_backend is None and runtime.get_or(KEY, 0) == 0.7


def test_manager_binds_all_instances_and_cache_includes_database(api, tmp_path):
    config = SimpleNamespace(bot_runtime_settings_dir=str(tmp_path / "settings"),
                             bot_control_plane_config_db=str(tmp_path / "a.sqlite3"))
    manager = settings.build_instance_settings_manager(config)
    default = manager.get("default")
    other = manager.get("other")
    default.set_override(KEY, "0.8")
    assert other.list_overrides() == {} and other.config_backend.instance == "other"
    peer = settings.InstanceSettingsManager(config.bot_runtime_settings_dir, backend_db=config.bot_control_plane_config_db)
    assert peer.get("default").get_or(KEY, 0) == 0.8
    assert settings.build_instance_settings_manager(config) is manager
    config.bot_control_plane_config_db = str(tmp_path / "b.sqlite3")
    assert settings.build_instance_settings_manager(config) is not manager
    config.bot_control_plane_config_db = ""
    assert settings.build_instance_settings_manager(config).get("default").config_backend is None
    assert manager.get("a/b") is manager.get("a b")


def test_no_backend_json_compatibility(tmp_path):
    path = tmp_path / "settings.json"
    runtime = settings.RuntimeSettingsStore(path, allow_no_gate=True)
    assert runtime.set_override(KEY, "0.8") == 0.8
    assert settings.RuntimeSettingsStore(path).get_or(KEY, 0) == 0.8
    assert runtime.reset_override(KEY) == 1
    assert settings.RuntimeSettingsStore(path).list_overrides() == {}

@pytest.mark.parametrize(("key", "value", "expected"), [
    ("BOT_CHAT_FAST_MODE", True, True),
    ("BOT_GROUP_WHITE1", [123, "456"], ["123", "456"]),
    ("BOT_QUIET_HOURS_SESSION_TYPES", ["group", "private"], ["group", "private"]),
    ("BOT_QUIET_HOURS_BYPASS_ROLES", ["admin", "super_admin"], ["admin", "super_admin"]),
    ("BOT_MODEL_PRIORITY_GROUPS", [{"name": "a", "order": ["model"]}], '[{"name": "a", "order": ["model"]}]'),
])
def test_api_native_values_use_existing_converters(setup, key, value, expected):
    _, runtime, service = setup
    assert service.set(key, value, principal=ADMIN, expected_version=0)["value"] == expected
    assert runtime.get_or(key, None) == expected


def test_null_is_not_a_silent_model_name(setup):
    _, _, service = setup
    with pytest.raises(ControlServiceError) as exc:
        service.set("BOT_CHAT_MODEL", None, principal=ADMIN, expected_version=0)
    assert exc.value.status_code == 422


def test_commit_failure_does_not_notify_or_apply(setup, monkeypatch):
    backend, runtime, service = setup
    connect = sqlite3.connect
    class FailCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("simulated commit failure")
    notices = []
    runtime.register_change_listener(lambda: notices.append(True))
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=FailCommit))
        with pytest.raises(ControlServiceError) as exc:
            service.set(KEY, "0.8", principal=ADMIN, expected_version=0)
        assert exc.value.status_code == 503
    assert backend.snapshot().version == 0 and runtime.get_or(KEY, 0.5) == 0.5
    assert backend.changes() == [] and notices == []


def test_reset_failure_preserves_override_and_audit(setup):
    backend, runtime, service = setup
    runtime.set_override(KEY, "0.8")
    notices = []
    runtime.register_change_listener(lambda: notices.append(True))
    with sqlite3.connect(backend.path) as conn:
        conn.execute("CREATE TRIGGER fail_reset BEFORE INSERT ON config_audit BEGIN SELECT RAISE(ABORT, 'failure'); END")
    with pytest.raises(ControlServiceError):
        service.reset(KEY, principal=ADMIN, expected_version=1)
    assert backend.snapshot().version == 1 and runtime.get_or(KEY, 0) == 0.8
    assert KEY not in backend.snapshot().tombstones and notices == []


def test_import_failure_is_retryable_and_audited(api, tmp_path):
    backend = api.Store(tmp_path / "state.sqlite3")
    with sqlite3.connect(backend.path) as conn:
        conn.execute("CREATE TRIGGER fail_import BEFORE INSERT ON config_audit BEGIN SELECT RAISE(ABORT, 'failure'); END")
    with pytest.raises(sqlite3.DatabaseError):
        backend.import_legacy({R0_KEY: 5.0})
    assert backend.snapshot().version == 0 and backend.snapshot().overrides == {}
    with sqlite3.connect(backend.path) as conn:
        conn.execute("DROP TRIGGER fail_import")
    assert backend.import_legacy({R0_KEY: 5.0}) is True
    assert backend.import_legacy({R0_KEY: 0.9}) is False
    assert backend.snapshot().overrides == {R0_KEY: 5.0}
    assert backend.changes()[0]["actor"] == "legacy_import"


def test_internal_writer_uses_cas_without_retrying_over_newer_write(api, setup, monkeypatch):
    backend, runtime, _ = setup
    peer = api.Store(backend.path)
    original = backend.set_override
    def competing_write(*args, **kwargs):
        peer.set_override(KEY, 0.9, expected_version=0, actor="peer")
        return original(*args, **kwargs)
    monkeypatch.setattr(backend, "set_override", competing_write)
    with pytest.raises(api.Conflict):
        runtime.set_override(KEY, "0.8")
    assert runtime.get_or(KEY, 0) == 0.9 and len(backend.changes()) == 1


def test_attach_same_backend_idempotent_but_different_target_rejected(api, setup, tmp_path):
    backend, runtime, service = setup
    peer = api.Store(backend.path)
    notices = []
    runtime.register_change_listener(lambda: notices.append(True))
    runtime.attach_config_backend(peer)
    api.Service(service.config, peer, runtime_settings=runtime).set(KEY, "0.8", principal=ADMIN, expected_version=0)
    assert notices == [True] and runtime.config_backend is backend
    for target in (api.Store(tmp_path / "other.sqlite3"), api.Store(backend.path, instance="other")):
        with pytest.raises(ValueError):
            runtime.attach_config_backend(target)


def test_changes_paging_and_sql_parameters(api, tmp_path):
    backend = api.Store(tmp_path / "state.sqlite3", instance="x'; DROP TABLE config_audit;--")
    for version in range(4):
        backend.set_override(KEY, 0.5, expected_version=version, actor="';--", request_id="';--")
    assert [row["version"] for row in backend.changes(since_version=1, limit=2)] == [2, 3]
    assert backend.snapshot().version == 4
    assert api.Store(backend.path).changes() == []


def test_reset_preview_has_default_value_and_no_side_effect(setup):
    backend, _, service = setup
    service.set(KEY, "0.8", principal=ADMIN, expected_version=0)
    row = service.preview(KEY, principal=ADMIN, expected_version=1, reset=True)
    assert row["value"] == 0.5 and row["state"] == "default"
    assert backend.snapshot().overrides == {KEY: 0.8}


def test_sql_reads_ignore_later_json_edits(api, setup, tmp_path):
    backend, runtime, _ = setup
    runtime.set_override(KEY, "0.8")
    runtime.path.write_text(json.dumps({"overrides": {KEY: 1.5}, "nicknames": ["new"]}), encoding="utf-8")
    assert runtime.get_or(KEY, 0) == 0.8 and runtime.list_nicknames() == ["new"]
    assert backend.snapshot().overrides == {KEY: 0.8}


def test_no_backend_failed_json_write_retains_legacy_notification(tmp_path, monkeypatch):
    runtime = settings.RuntimeSettingsStore(tmp_path / "legacy.json", allow_no_gate=True)
    notices = []
    runtime.register_change_listener(lambda: notices.append(runtime.get_or(KEY, 0)))
    def fail(*args):
        raise OSError("failed")
    monkeypatch.setattr(settings.os, "replace", fail)
    assert runtime.set_override(KEY, "0.8") == 0.8
    assert notices == [0.8]  # 不将 SQL 的新事务语义偷偷施加到 legacy 路径。


def test_sql_enabled_json_listener_only_after_success(setup, monkeypatch):
    _, runtime, _ = setup
    notices = []
    runtime.register_change_listener(lambda: notices.append(json.loads(runtime.path.read_text(encoding="utf-8"))["nicknames"]))
    runtime.add_nickname("saved")
    assert notices == [["saved"]]
    def fail(*args):
        raise OSError("failed")
    monkeypatch.setattr(settings.os, "replace", fail)
    runtime.add_nickname("unsaved")
    assert notices == [["saved"]]

@pytest.mark.parametrize("value", ["NaN", "Infinity", float("inf")])
def test_nonfinite_converter_result_is_rejected_before_preview_or_write(setup, value):
    backend, _, service = setup
    for method in (service.preview, service.set):
        with pytest.raises(ControlServiceError) as exc:
            method("BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS", value, principal=ADMIN, expected_version=0)
        assert exc.value.status_code == 422
    assert backend.snapshot().version == 0

@pytest.mark.parametrize("key", ["BOT_CHAT_MAX_TOKENS", "BOT_CHAT_FAST_MAX_TOKENS", "BOT_MEMORY_EXTRACT_MAX_TOKENS"])
def test_token_budgets_are_visible_not_misclassified_as_credentials(setup, key):
    _, _, service = setup
    row = service.set(key, 512, principal=ADMIN, expected_version=0)
    assert row["value"] == 512 and not row["sensitive"] and row["fingerprint"] is None
    assert service.get(key)["value"] == 512
    assert service.changes()[0]["after"][key]["value"] == 512


@pytest.mark.parametrize("key", ["BOT_TEST_API_KEY", "BOT_TEST_ACCESS_TOKEN", "BOT_TEST_SECRET", "BOT_TEST_PASSWORD", "BOT_TEST_COOKIE", "BOT_CONTROL_PLANE_TOKEN_SHA256"])
def test_credential_suffixes_are_redacted(setup, monkeypatch, key):
    _, _, service = setup
    monkeypatch.setitem(settings.SETTABLE_KEYS, key, str)
    row = service.set(key, "private-test-value", principal=ADMIN, expected_version=0)
    assert row["sensitive"] and row["fingerprint"] and row["value"] == "[redacted]"
    assert "private-test-value" not in json.dumps([row, service.changes()])


def test_cross_process_writer_is_seen_by_existing_runtime(setup):
    import subprocess
    import sys

    backend, runtime, _ = setup
    code = """
import sys
from plugins.bot_unified_runtime.control_plane.config_store import SQLiteConfigStateStore
store = SQLiteConfigStateStore(sys.argv[1])
store.set_override('BOT_CHAT_TEMPERATURE', 0.85, expected_version=0, actor='child', request_id='cross-process')
"""
    proc = subprocess.run([sys.executable, "-B", "-c", code, str(backend.path)],
                          capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
    assert proc.returncode == 0, proc.stderr
    assert runtime.get_or(KEY, 0.5) == 0.85
    assert backend.changes()[0]["request_id"] == "cross-process"


def test_revision_is_instance_wide_not_per_key(setup):
    _, _, service = setup
    service.set(KEY, 0.9, principal=ADMIN, expected_version=0)
    with pytest.raises(ControlServiceError) as exc:
        service.set("BOT_CHAT_MODEL", "next-model", principal=ADMIN, expected_version=0)
    assert exc.value.code == "version_conflict"
    assert {row["version"] for row in service.list()} == {1}


def test_sql_runtime_read_write_latency_sample(setup):
    from statistics import median
    from time import perf_counter

    _, runtime, _ = setup
    writes, reads = [], []
    for _ in range(20):
        start = perf_counter()
        runtime.set_override(KEY, "0.8")
        writes.append((perf_counter() - start) * 1000)
    for _ in range(100):
        start = perf_counter()
        assert runtime.get_or(KEY, 0) == 0.8
        reads.append((perf_counter() - start) * 1000)
    print(f"SQL config read: P50={median(reads):.3f}ms P95={sorted(reads)[94]:.3f}ms; "
          f"CAS+audit write: P50={median(writes):.3f}ms P95={sorted(writes)[18]:.3f}ms")


def test_shared_backend_concurrent_runtime_writers_do_not_deadlock(api, setup, tmp_path, monkeypatch):
    from threading import Event, Thread

    backend, first, _ = setup
    second = settings.RuntimeSettingsStore(tmp_path / "second.json", backend=backend, allow_no_gate=True)
    committed = Event()
    barrier = Barrier(2)
    notify = backend._notify
    errors = []
    def after_commit():
        committed.set()
        barrier.wait(timeout=5)
        notify()
    monkeypatch.setattr(backend, "_notify", after_commit)
    def write(runtime, value):
        try:
            runtime.set_override(KEY, value)
        except (ValueError, sqlite3.Error, RuntimeError) as exc:
            errors.append(exc)
    threads = [Thread(target=write, args=(first, "0.7"), daemon=True),
               Thread(target=write, args=(second, "0.8"), daemon=True)]
    threads[0].start()
    assert committed.wait(timeout=5)
    threads[1].start()
    for thread in threads:
        thread.join(timeout=3)
    assert not any(thread.is_alive() for thread in threads), "listener lock inversion"
    assert not errors and backend.snapshot().version == 2


def test_service_reset_all_is_single_cas_transaction(setup):
    backend, runtime, service = setup
    runtime.set_override(KEY, "0.8")
    runtime.set_override("BOT_CHAT_MODEL", "another-model")
    notices = []
    runtime.register_change_listener(lambda: notices.append(backend.snapshot().version))
    result = service.reset_all(principal=ADMIN, expected_version=2, request_id="reset-all")
    assert result == {"version": 3, "reset_count": 2}
    assert runtime.list_overrides() == {} and backend.snapshot().tombstones == {KEY, "BOT_CHAT_MODEL"}
    assert notices == [3] and len(service.changes()) == 3
    event = service.changes()[-1]
    assert event["action"] == "reset" and event["key"] is None
    assert event["actor"] == ADMIN.subject and event["request_id"] == "reset-all"
    assert set(event["before"]) == {KEY, "BOT_CHAT_MODEL"}
    assert service.reset_all(principal=ADMIN, expected_version=3) == {"version": 4, "reset_count": 0}


def test_service_reset_all_enforces_role_version_and_no_partial_failure(setup):
    backend, runtime, service = setup
    runtime.set_override(KEY, "0.8")
    runtime.set_override("BOT_CHAT_MODEL", "another-model")
    for principal, version, code in [(Principal("admin"), 2, "forbidden"),
                                     (ADMIN, None, "invalid_version"),
                                     (ADMIN, 1, "version_conflict")]:
        with pytest.raises(ControlServiceError) as exc:
            service.reset_all(principal=principal, expected_version=version)
        assert exc.value.code == code
    notices = []
    runtime.register_change_listener(lambda: notices.append(True))
    with sqlite3.connect(backend.path) as conn:
        conn.execute("CREATE TRIGGER fail_all BEFORE INSERT ON config_audit BEGIN SELECT RAISE(ABORT, 'failure'); END")
    with pytest.raises(ControlServiceError) as exc:
        service.reset_all(principal=ADMIN, expected_version=2)
    assert exc.value.status_code == 503
    assert runtime.list_overrides() == {KEY: 0.8, "BOT_CHAT_MODEL": "another-model"}
    assert backend.snapshot().version == 2 and not backend.snapshot().tombstones
    assert len(service.changes()) == 2 and notices == []


def test_service_reset_all_count_cannot_race_with_another_writer(api, setup, monkeypatch):
    backend, runtime, service = setup
    runtime.set_override(KEY, "0.8")
    peer = api.Store(backend.path)
    original = backend.reset_override
    def racing_reset(*args, **kwargs):
        peer.set_override("BOT_CHAT_MODEL", "new-model", expected_version=1, actor="peer")
        return original(*args, **kwargs)
    monkeypatch.setattr(backend, "reset_override", racing_reset)
    with pytest.raises(ControlServiceError) as exc:
        service.reset_all(principal=ADMIN, expected_version=1)
    assert exc.value.code == "version_conflict"
    assert runtime.list_overrides() == {KEY: 0.8, "BOT_CHAT_MODEL": "new-model"}


@pytest.mark.parametrize("value", [
    r"C:\Private\settings.sqlite3",
    "C:/Private/settings.sqlite3",
    r"\\server\private\settings.sqlite3",
    r"failure at C:\Users\Test User\private.json",
    "/var/lib/private/settings.sqlite3",
    "failed path=/home/test/private.json",
    "path:/tmp/private.json",
    "//server/private/settings.sqlite3",
    "file:///etc/private.json",
    "Authorization: Bearer bearer-test-secret",
    "Cookie: sid=cookie-test-secret; other=second-secret",
    "api_key=key-test-secret",
    'config={"api_key": "key-test-secret"}',
    "key=short-secret",
    "provider sk-testsecret123456",
])
def test_public_noncredential_text_is_redacted(value):
    from plugins.bot_unified_runtime.control_plane.config_store import public_value

    row = public_value("BOT_CHAT_MODEL", value)
    assert row["value"] == "[redacted]"
    assert row["sensitive"] is False and row["fingerprint"] is None


def test_restart_default_path_never_enters_config_dto(setup, monkeypatch):
    _, _, service = setup
    key = "BOT_RATE_LIMIT_DB_PATH"
    monkeypatch.setitem(settings.RESTART_REQUIRED_KEYS, key, "初始化时绑定")
    setattr(service.config, key.lower(), "/var/lib/private/limits.sqlite3")
    assert service.get(key)["value"] == "[redacted]"
    assert "/var/lib/private" not in json.dumps([service.get(key), service.list(), service.schema()])


def test_nested_public_values_and_audit_are_safe_but_backend_unchanged(setup, monkeypatch):
    backend, runtime, service = setup
    key = "BOT_TEST_OPTIONS"
    raw = {"count": 512, "enabled": True, "ratio": 0.5, "missing": None,
           "paths": [r"C:\Private\first.db", "/srv/private/second.db"],
           "nested": {"api_key": "opaque-nested-secret", "text": "Bearer inner-secret"},
           "/etc/private/key-as-path": "safe"}
    monkeypatch.setitem(settings.SETTABLE_KEYS, key, json.loads)
    preview = service.preview(key, raw, principal=ADMIN, expected_version=0)
    result = service.set(key, raw, principal=ADMIN, expected_version=0)
    assert result["value"]["count"] == 512 and type(result["value"]["count"]) is int
    assert result["value"]["enabled"] is True and result["value"]["ratio"] == 0.5
    assert result["value"]["missing"] is None
    assert backend.snapshot().overrides[key] == raw and runtime.get_or(key, None) == raw
    service.reset(key, principal=ADMIN, expected_version=1)
    payload = json.dumps([preview, result, service.changes(), backend.changes()])
    with sqlite3.connect(backend.path) as conn:
        stored = str(conn.execute("SELECT before_json, after_json FROM config_audit").fetchall())
    for forbidden in ("Private", "/srv/private", "opaque-nested-secret", "inner-secret", "/etc/private"):
        assert forbidden not in payload and forbidden not in stored


@pytest.mark.parametrize("failure", ["raise", "bad-return"])
def test_public_redaction_helper_failure_is_closed(setup, monkeypatch, failure):
    from plugins.bot_unified_runtime.control_plane.config_store import public_value
    from plugins.bot_unified_runtime.domains.ops.audit import logger

    def fail(value):
        if failure == "raise":
            raise RuntimeError("redactor failed with private input")
    monkeypatch.setattr(logger, "redact_private_debug", fail)
    assert public_value("BOT_CHAT_MODEL", "raw-private-value")["value"] == "[redacted]"
    assert public_value("BOT_CHAT_MAX_TOKENS", 512)["value"] == 512
    assert public_value("BOT_CHAT_FAST_MODE", False)["value"] is False
    backend, _, service = setup
    row = service.set("BOT_CHAT_MODEL", "raw-private-value", principal=ADMIN, expected_version=0)
    assert row["value"] == "[redacted]"
    assert backend.snapshot().overrides["BOT_CHAT_MODEL"] == "raw-private-value"
    assert "raw-private-value" not in json.dumps(service.changes())


def test_public_ordinary_values_preserve_types_and_relative_text():
    from plugins.bot_unified_runtime.control_plane.config_store import public_value

    raw = {"max_tokens": 1024, "enabled": False, "temperature": 0.6,
           "timezone": "Asia/Hong_Kong", "relative": "data/settings.json",
           "url": "https://example.test/models", "model": "ordinary-model"}
    assert public_value("BOT_TEST_OPTIONS", raw)["value"] == raw
    assert public_value("BOT_CHAT_MAX_TOKENS", 1024)["value"] == 1024


def test_older_unsafe_audit_values_are_redacted_on_read(setup):
    backend, _, service = setup
    before = {"BOT_CHAT_MODEL": {"state": "override", "value": "/tmp/old-private.json", "fingerprint": None}}
    after = {"BOT_CHAT_MODEL": {"state": "override", "value": "key=old-secret", "fingerprint": None}}
    with sqlite3.connect(backend.path) as conn:
        conn.execute("INSERT INTO config_audit(instance, version, action, key, before_json, after_json, actor, request_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     ("default", 1, "set", "BOT_CHAT_MODEL", json.dumps(before), json.dumps(after), "admin", "history"))
    payload = json.dumps([backend.changes(), service.changes()])
    assert "old-private" not in payload and "old-secret" not in payload
