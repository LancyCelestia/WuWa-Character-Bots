"""进程资源采样契约：仅当前进程、无生产读写、unknown 不冒充零。"""
from __future__ import annotations

import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest


@pytest.fixture
def resources():
    return importlib.import_module("plugins.bot_unified_runtime.control_plane.resources")


class Clock:
    now = 100.0
    cpu = 10.0

    def tick(self, seconds=1.0, cpu=0.5):
        self.now += seconds
        self.cpu += cpu


@pytest.fixture
def sampler(resources):
    clock = Clock()
    process = SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=4096),
                              num_threads=lambda: 7, create_time=lambda: 50.0)
    service = resources.ResourceMetricsService(
        monotonic=lambda: clock.now, wall_clock=lambda: clock.now,
        cpu_clock=lambda: clock.cpu, process_factory=lambda: process,
    )
    return service, clock, process


def test_first_cpu_sample_unknown_other_metrics_available(sampler):
    service, _, _ = sampler
    result = service.snapshot()
    assert result["cpu_percent"] is None
    assert result["measurements"]["cpu_percent"] == {
        "value": None, "status": "unknown", "reason": "warming_up", "unit": "percent_one_core"
    }
    assert result["memory_bytes"] == 4096
    assert result["measurements"]["thread_count"]["value"] == 7
    assert result["measurements"]["uptime_seconds"]["value"] == 50
    assert result["process_role"] == "control_plane_host"


def test_cpu_delta_and_cache_share_one_sampling_window(sampler):
    service, clock, _ = sampler
    first = service.snapshot()
    clock.tick(seconds=0.1, cpu=0.01)
    assert service.snapshot() == first
    clock.tick(seconds=0.9, cpu=0.49)
    row = service.snapshot()
    assert row["cpu_percent"] == 50.0
    assert row["measurements"]["cpu_percent"]["status"] == "ok"
    row["measurements"]["cpu_percent"]["value"] = 999
    assert service.snapshot()["cpu_percent"] == 50.0


def test_multicore_cpu_not_clamped_and_true_idle_is_zero(sampler):
    service, clock, _ = sampler
    service.snapshot()
    clock.tick(cpu=2.0)
    assert service.snapshot()["cpu_percent"] == 200.0
    clock.tick(cpu=0)
    assert service.snapshot()["cpu_percent"] == 0.0


def test_counter_reset_is_unknown_and_next_window_recovers(sampler):
    service, clock, _ = sampler
    service.snapshot()
    clock.tick(cpu=-9.0)
    assert service.snapshot()["measurements"]["cpu_percent"]["reason"] == "counter_reset"
    clock.tick()
    assert service.snapshot()["cpu_percent"] == 50.0


def test_collector_failure_isolated_and_exception_never_exposed(sampler):
    service, clock, process = sampler

    def fail():
        raise RuntimeError("Bearer secret C:/private/keys.env")

    process.memory_info = fail
    result = service.snapshot()
    assert result["memory_bytes"] is None
    assert result["measurements"]["memory_bytes"]["reason"] == "source_unavailable"
    assert result["measurements"]["thread_count"]["value"] == 7
    assert "secret" not in json.dumps(result)
    clock.tick()
    assert service.snapshot()["cpu_percent"] == 50.0


def test_missing_psutil_does_not_hide_cpu(resources):
    def missing():
        raise ImportError("not installed")

    clock = Clock()
    service = resources.ResourceMetricsService(monotonic=lambda: clock.now,
        cpu_clock=lambda: clock.cpu, process_factory=missing)
    service.snapshot()
    clock.tick()
    result = service.snapshot()
    assert result["cpu_percent"] == 50.0
    for key in ("memory_bytes", "thread_count", "uptime_seconds"):
        assert result["measurements"][key]["status"] == "unknown"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "42"])
def test_invalid_numeric_sample_is_not_published(sampler, value):
    service, _, process = sampler
    process.memory_info = lambda: SimpleNamespace(rss=value)
    assert service.snapshot()["measurements"]["memory_bytes"]["value"] is None


def test_unwired_resources_explicitly_unknown(sampler):
    result = sampler[0].snapshot()
    for key in ("task_count", "queue_depth", "llm_concurrency", "database_bytes"):
        assert result["measurements"][key]["value"] is None
        assert result["measurements"][key]["reason"] == "not_connected"


def test_concurrent_readers_do_not_reset_cpu_or_mutate_cache(sampler):
    service, clock, _ = sampler
    service.snapshot()
    clock.tick()
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: service.snapshot(), range(20)))
    assert {row["cpu_percent"] for row in rows} == {50.0}
    assert len({row["captured_at"] for row in rows}) == 1


def test_cpu_collection_failure_requires_new_warmup(resources):
    clock = Clock()
    broken = False

    def cpu():
        if broken:
            raise OSError("private")
        return clock.cpu

    service = resources.ResourceMetricsService(monotonic=lambda: clock.now, cpu_clock=cpu)
    service.snapshot()
    clock.tick()
    broken = True
    assert service.snapshot()["cpu_percent_reason"] == "source_unavailable"
    clock.tick()
    broken = False
    assert service.snapshot()["cpu_percent_reason"] == "warming_up"
    clock.tick()
    assert service.snapshot()["cpu_percent"] == 50.0


def test_api_uses_shared_resource_service_and_declares_protocol(sampler, tmp_path):
    from fastapi.testclient import TestClient

    from plugins.bot_unified_runtime.control_plane import create_control_plane_app
    from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
    from plugins.bot_unified_runtime.control_plane.auth import hash_token
    from plugins.bot_unified_runtime.control_plane.metrics import LedgerMetricsService

    service, clock, _ = sampler
    config = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("read-token"),
        bot_control_plane_super_admin_token_sha256=hash_token("write-token"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
    )
    app = create_control_plane_app(config, resource_service=service,
        audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        metrics_service=LedgerMetricsService(tmp_path / "absent-ledger.sqlite3"),
        channel_health_store=object())
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        assert client.get("/api/v1/metrics/resources").status_code == 401
        headers = {"Authorization": "Bearer read-token"}
        first = client.get("/api/v1/metrics/resources", headers=headers).json()
        assert first["data"]["cpu_percent"] is None
        assert first["meta"]["schema_version"] == "v1"
        clock.tick()
        overview = client.get("/api/v1/metrics/overview", headers=headers).json()
        resources = client.get("/api/v1/metrics/resources", headers=headers).json()
        assert overview["data"]["resources"] == resources["data"]
        assert resources["data"]["cpu_percent"] == 50.0
        manifest = client.get("/api/v1/protocol", headers=headers).json()["data"]
        assert manifest["services"]["resources"]["sampling"] == "on_demand"
        schema = client.get("/api/v1/openapi.json", headers=headers).json()["data"]
        assert "ResourceSnapshot" in schema["components"]["schemas"]
    assert not (tmp_path / "absent-ledger.sqlite3").exists()
