"""``domains/ops/host_snapshot.py``（文件链路波供件）的回归锁。

锁四件事：

① 文本形态与缓存口径：窗内复用同一份采样（采样缝只被叫一次）、过期重采、
   ``max_age_seconds<=0`` 每次现采（用受控时钟钉死 TTL 边界——Windows
   monotonic 粒度会让 ``age==0.0``，``<=`` 写法会在 ttl=0 上退化成缓存命中）；
② fail-open：采样缝抛异常/返回空串 → 空串且**不占缓存**（下次还能重试）；
   ``max_age_seconds`` 传不可解析的值也回空串不外抛；
③ 测试失效口在岗（用例间互不串读数）；
④ AST 自门：本模块体内**永远不准**长出自己的机器读数点（psutil/注册表/
   磁盘直调、或在册读数属性名）——采样只准复用 ``host_metrics`` 真身。
   这条是给 ``tests/test_single_entry_gates.py`` 门②归属账的前置防线：
   账门拦「账外新增」，本门拦「这个文件根本不该出现读数」。

采样源一律 mock（``_sample_usage_text`` 是唯一缝）——测试不读真机器。
消费契约：返回文本带自题头 ``SECTION_HEADER``（providers.py 的裸渲染分区
槽不加盖头，头并进缓存文本）；断言按「前缀 + 正文」拆开锁。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.ops import host_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "ops"
    / "host_snapshot.py"
)


class _FakeClock:
    """受控 monotonic 时钟（只换 host_snapshot 名字空间里的绑定，不碰全局 time）。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def strftime(self, fmt: str) -> str:
        return "12:03:05"


@pytest.fixture(autouse=True)
def _clean_cache():
    host_snapshot.invalidate_host_snapshot_for_tests()
    yield
    host_snapshot.invalidate_host_snapshot_for_tests()


def test_text_format_and_cached_within_window(monkeypatch):
    """窗内第二次调用零采样，文本原样复用；自题头在正文之前。"""
    calls = {"n": 0}

    def fake_sample():
        calls["n"] += 1
        return "CPU 12% · 内存 46%（采样 12:03:05）"

    monkeypatch.setattr(host_snapshot, "_sample_usage_text", fake_sample)
    first = host_snapshot.host_snapshot_section_text(max_age_seconds=30)
    second = host_snapshot.host_snapshot_section_text(max_age_seconds=30)
    assert first == f"{host_snapshot.SECTION_HEADER}CPU 12% · 内存 46%（采样 12:03:05）"
    assert second == first
    assert calls["n"] == 1, "缓存窗内不该重采（每条消息一份注记会放大采样成本）"


def test_expired_window_resamples(monkeypatch):
    """过期后重采并拿到新文本（受控时钟走到窗界之外）。"""
    texts = iter(["CPU 1% · 内存 2%（采样 10:00:00）", "CPU 9% · 内存 8%（采样 10:00:31）"])
    clock = _FakeClock()
    monkeypatch.setattr(host_snapshot, "_sample_usage_text", lambda: next(texts))
    monkeypatch.setattr(host_snapshot, "time", clock)

    host_snapshot.host_snapshot_section_text(max_age_seconds=30)
    clock.now += 30.1  # 越过窗界
    second = host_snapshot.host_snapshot_section_text(max_age_seconds=30)
    assert second == f"{host_snapshot.SECTION_HEADER}CPU 9% · 内存 8%（采样 10:00:31）"


def test_ttl_zero_always_resamples_even_on_monotonic_tie(monkeypatch):
    """TTL=0（每次现采）在 ``age==0.0`` 的时钟粒度上也不得退化成缓存命中。"""
    texts = iter(["CPU 1%（采样 10:00:00）", "CPU 2%（采样 10:00:00）"])
    clock = _FakeClock()  # 两次调用之间时钟原地不动：age 恒为 0.0
    monkeypatch.setattr(host_snapshot, "_sample_usage_text", lambda: next(texts))
    monkeypatch.setattr(host_snapshot, "time", clock)
    host_snapshot.host_snapshot_section_text(max_age_seconds=0)
    second = host_snapshot.host_snapshot_section_text(max_age_seconds=0)
    assert second.endswith("CPU 2%（采样 10:00:00）")


def test_sample_failure_returns_empty_and_is_not_cached(monkeypatch):
    """失败=空串，且失败**不占缓存**——下一窗还能重试出真数。"""
    texts: list[str | Any] = ["", "CPU 3% · 内存 4%（采样 11:00:00）"]
    monkeypatch.setattr(host_snapshot, "_sample_usage_text", lambda: texts.pop(0))
    assert host_snapshot.host_snapshot_section_text(max_age_seconds=60) == ""
    assert host_snapshot.host_snapshot_section_text(max_age_seconds=60) == (
        f"{host_snapshot.SECTION_HEADER}CPU 3% · 内存 4%（采样 11:00:00）"
    )


def test_sample_exception_never_raises(monkeypatch):
    """采样缝炸了 → 空串，绝不打断调用链（fail-open 承诺）。"""

    def boom():
        raise RuntimeError("psutil exploded")

    monkeypatch.setattr(host_snapshot, "_sample_usage_text", boom)
    assert host_snapshot.host_snapshot_section_text() == ""


def test_unparseable_max_age_fails_open(monkeypatch):
    """max_age_seconds 传不可解析值（None/字符串）→ 空串，不外抛。"""
    monkeypatch.setattr(
        host_snapshot, "_sample_usage_text", lambda: "CPU 5%（采样 12:00:00）"
    )
    assert host_snapshot.host_snapshot_section_text(max_age_seconds=None) == ""  # type: ignore[arg-type]
    assert host_snapshot.host_snapshot_section_text(max_age_seconds="soon") == ""  # type: ignore[arg-type]


def test_invalidate_helper_resets_cache(monkeypatch):
    calls = {"n": 0}

    def fake_sample():
        calls["n"] += 1
        return f"CPU {calls['n']}%（采样 12:00:00）"

    monkeypatch.setattr(host_snapshot, "_sample_usage_text", fake_sample)
    host_snapshot.host_snapshot_section_text(max_age_seconds=60)
    host_snapshot.invalidate_host_snapshot_for_tests()
    host_snapshot.host_snapshot_section_text(max_age_seconds=60)
    assert calls["n"] == 2, "失效口没清缓存：第二窗复用了旧读数"


def test_module_never_grows_its_own_machine_reads():
    """AST 自门：本模块体内零直调读数点（采样只准住在 host_metrics 真身）。

    属性名集合抄 ``tests/test_single_entry_gates.py::HOST_METRIC_READS`` 的
    token 全集；import 面另禁 psutil/winreg/shutil/platform 整门。锁的是
    **本文件**，不改门②的账——账门管全树归属，本门管这个新文件不破戒。
    """
    forbidden_attrs = {
        "cpu_count",
        "cpu_percent",
        "getloadavg",
        "processor",
        "virtual_memory",
        "swap_memory",
        "disk_usage",
        "disk_partitions",
        "boot_time",
        "memory_info",
        "cpu_times",
    }
    forbidden_modules = {"psutil", "winreg", "shutil", "platform"}
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
            pytest.fail(f"host_snapshot.py 长出自己的读数点：属性 .{node.attr}（行 {node.lineno}）")
    overlap = sorted(imported & forbidden_modules)
    assert not overlap, f"host_snapshot.py 禁止直读机器：import 了 {overlap}"
