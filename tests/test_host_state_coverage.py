"""需求 5 · 覆盖面补齐（S-T-HOST-2 三段）——对照用户点名清单的缺口各立一条锁。

前两席把「取数口唯一」「出卡/能力入口」立成了；本席按用户原话点名清单补余下
覆盖面，每条测试拦一件会真发生的缺口：

- **适配器全景**：卡上只有 onebot 一行，telegram/console/mail/qq 全被闭集映射
  丢掉（用户点名「适配器（onebot、telegram、github、gitee、satori）版本」）；
- **本 bot 进程运行时长**：中央版本口的「运行时长」行原样被映射层丢弃；
- **依赖插件全家 / 核心依赖全家**：用户点名「插件版本号（本插件与依赖插件）」
  「pydantic/nonebot 依赖全家」——中央采集口没有这两路，另开固定口径缝；
- **进程瞬时 CPU%**：旧值只有 RSS + 累计 CPU 时间；且采样必须走间隔窗
  （psutil 首采 interval=None 无意义——本机已知坑 ②）；
- **显存第二腿**：nvidia-smi/NVML 挂死时试 torch.cuda 直读；两腿皆死 →
  「未探测」且 note 并列两腿原因，**绝不编数**（本机已知坑 ①）；
- **协议端在线与端口**：运行期 nonebot 驱动派生；离线/无驱动环境诚实「未探测」
  且绝不抛异常；
- **呈现适配器不复读**：「运行时长」已有中央透传行，映射腿再端一份
  「本 bot 运行时长」就是同一事实两处出现（迟早漂成两个值）。

测试全离线：新增取数缝全部 monkeypatch；只有「全景现算比对」组故意现算
（读本机发行版元数据 / 未初始化驱动的 nonebot），零网络、零 GPU、零渲染。
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.ops import host_metrics as hm
from plugins.bot_unified_runtime.domains.ops.capabilities import host_state
from plugins.bot_unified_runtime.domains.ops.monitor import error_report, host_status

NEW_METRIC_IDS = {
    "adapter_versions",
    "process_uptime",
    "dependency_plugins",
    "dependency_versions",
    "protocol_endpoints",
}


class _FakeProcess:
    """进程缝假件：记录 cpu_percent 的采样间隔（首采无意义坑的执法点）。"""

    def __init__(self, *, with_cpu_percent: bool = True) -> None:
        self.intervals: list[Any] = []
        self._with = with_cpu_percent

    def memory_info(self) -> SimpleNamespace:
        return SimpleNamespace(rss=int(1.5 * 1024**3))

    def cpu_times(self) -> SimpleNamespace:
        return SimpleNamespace(user=120.0, system=30.0)

    def cpu_percent(self, interval: Any = None) -> float:
        self.intervals.append(interval)
        if not self._with:
            raise AttributeError("cpu_percent")
        return 12.5


def _fake_ps(process: _FakeProcess | None = None) -> Any:
    proc = process or _FakeProcess()
    return SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(
            total=32 * 1024**3, available=8 * 1024**3, percent=75.0
        ),
        cpu_count=lambda logical=True: 16 if logical else 8,
        cpu_percent=lambda interval=0.0: 42.5,
        disk_partitions=lambda all=False: [],
        swap_memory=lambda: SimpleNamespace(total=0, used=0, percent=0.0),
        boot_time=lambda: 0.0,
        Process=lambda *a, **k: proc,
    )


def _stub_all_seams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    adapters: list[tuple[str, str]] | None = None,
    plugins: list[tuple[str, str]] | None = None,
    deps: list[tuple[str, str]] | None = None,
    endpoints: list[tuple[str, str]] | None = None,
    version_map: dict[str, str] | None = None,
    cuda: tuple[list[tuple[str, float, float]], str] | None = None,
    process: _FakeProcess | None = None,
) -> None:
    """把一切外部世界按到假数据上；各参数即「该缝给什么读数」。"""
    monkeypatch.setattr(hm, "_psutil_module", lambda: _fake_ps(process))
    monkeypatch.setattr(hm, "_logical_core_count", lambda: 16)
    monkeypatch.setattr(hm, "_cpu_model_text", lambda: "Fake CPU")
    monkeypatch.setattr(hm, "_gpu_model_rows", lambda: ["Fake GPU"])
    monkeypatch.setattr(
        hm, "_query_nvidia_smi", lambda timeout: ("", "mock：不真调外部命令")
    )
    monkeypatch.setattr(hm, "_adapter_version_rows", lambda: list(adapters or []))
    monkeypatch.setattr(hm, "_dependency_plugin_rows", lambda: list(plugins or []))
    monkeypatch.setattr(hm, "_core_dependency_rows", lambda: list(deps or []))
    monkeypatch.setattr(hm, "_protocol_endpoint_rows", lambda: list(endpoints or []))
    monkeypatch.setattr(
        hm, "_query_cuda_vram", lambda: cuda or ([], "mock：不真读 CUDA")
    )
    monkeypatch.setattr(hm, "_version_rows_map", lambda: dict(version_map or {}))


# ---------------------------------------------------------------------------
# 在册性：新指标必须「在册且可采」，不许成只有名字的空壳
# ---------------------------------------------------------------------------


def test_new_metrics_are_registered_with_collectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert NEW_METRIC_IDS <= set(hm.METRIC_SPEC_IDS), hm.METRIC_SPEC_IDS
    assert set(hm._COLLECTORS) == set(hm.METRIC_SPEC_IDS), "在册项与采集器必须一一对应"
    _stub_all_seams(monkeypatch)
    report = hm.collect_host_metrics_sync()
    assert set(report.by_id()) == set(hm.METRIC_SPEC_IDS)


# ---------------------------------------------------------------------------
# 适配器全景：闭集映射不再丢行
# ---------------------------------------------------------------------------


def test_adapter_family_lists_every_installed_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_all_seams(
        monkeypatch,
        adapters=[("onebot", "1.1.1"), ("telegram", "2.2.2"), ("satori", "3.3.3")],
    )
    item = hm.collect_host_metrics_sync().first("adapter_versions")
    assert item is not None and item.state == hm.STATE_OK
    assert item.value == "onebot 1.1.1 · telegram 2.2.2 · satori 3.3.3"
    assert item.source == hm.VERSION_PAIRS_SOURCE, "适配器行仍走中央版本口"


def test_adapter_family_absent_is_honest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_all_seams(monkeypatch, adapters=[])
    item = hm.collect_host_metrics_sync().first("adapter_versions")
    assert item is not None and item.state == hm.STATE_NOT_PROBED
    assert item.value == hm.NOT_PROBED and item.note


def test_adapter_family_live_matches_central_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """现算比对：卡上全景与 error_report._adapter_dist_pairs() 逐名一致。"""
    pairs = error_report._adapter_dist_pairs()
    if not pairs:
        pytest.skip("本环境没有任何 nonebot-adapter* 发行版，全景比对不适用")
    monkeypatch.setattr(
        hm, "_query_nvidia_smi", lambda timeout: ("", "mock：不真调外部命令")
    )
    item = hm.collect_host_metrics_sync().first("adapter_versions")
    assert item is not None and item.state == hm.STATE_OK, item
    for name, version in pairs:
        short = name.replace("nonebot-adapter-", "")
        assert f"{short} {version}" in item.value, item.value


# ---------------------------------------------------------------------------
# 本 bot 运行时长：中央版本口「运行时长」行不再被丢
# ---------------------------------------------------------------------------


def test_process_uptime_maps_central_runtime_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert hm._VERSION_LABEL_TO_ID.get("运行时长") == "process_uptime"
    _stub_all_seams(monkeypatch, version_map={"process_uptime": "2 小时 3 分"})
    item = hm.collect_host_metrics_sync().first("process_uptime")
    assert item is not None and item.state == hm.STATE_OK
    assert item.value == "2 小时 3 分"
    assert item.label == "本 bot 运行时长"


# ---------------------------------------------------------------------------
# 依赖插件全家 / 核心依赖全家
# ---------------------------------------------------------------------------


def test_dependency_plugin_and_core_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_all_seams(
        monkeypatch,
        plugins=[("alconna", "0.62.1"), ("waiter", "0.8.1")],
        deps=[("pydantic", "9.9.9"), ("httpx", "8.8.8")],
    )
    report = hm.collect_host_metrics_sync()
    plugs = report.first("dependency_plugins")
    deps = report.first("dependency_versions")
    assert plugs is not None and plugs.value == "alconna 0.62.1 · waiter 0.8.1"
    assert deps is not None and deps.value == "pydantic 9.9.9 · httpx 8.8.8"
    assert plugs.source != hm.VERSION_PAIRS_SOURCE, "这两路不在中央口里，来源必须各点名"
    assert "importlib.metadata" in plugs.source and "importlib.metadata" in deps.source


def test_dependency_legs_absent_are_honest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_all_seams(monkeypatch, plugins=[], deps=[])
    report = hm.collect_host_metrics_sync()
    for metric_id in ("dependency_plugins", "dependency_versions"):
        item = report.first(metric_id)
        assert item is not None and item.state == hm.STATE_NOT_PROBED
        assert item.value == hm.NOT_PROBED and item.note


def test_live_dependency_legs_read_real_distributions() -> None:
    """现算腿：本机真装了 pydantic 与 nonebot-plugin*，两行必须是真数。"""
    import importlib.metadata as md

    expected_pydantic = md.version("pydantic")
    rows = hm._core_dependency_rows()
    assert ("pydantic", expected_pydantic) in rows, rows
    plugin_rows = hm._dependency_plugin_rows()
    assert any(short == "alconna" for short, _v in plugin_rows), plugin_rows
    for short, _v in plugin_rows:
        assert not short.lower().startswith("nonebot-plugin"), (
            "短名清洗没做＝整行前缀噪声"
        )


# ---------------------------------------------------------------------------
# 进程瞬时 CPU%：值上卡 + 采样必须走间隔窗（首采无意义坑）
# ---------------------------------------------------------------------------


def test_process_usage_carries_instant_cpu_percent_with_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProcess()
    _stub_all_seams(monkeypatch, process=proc)
    item = hm.collect_host_metrics_sync().first("process_usage")
    assert item is not None and item.state == hm.STATE_OK
    assert "CPU 12.5%" in item.value, item.value
    assert "常驻内存" in item.value
    assert proc.intervals and all(
        i is not None and float(i) >= 0.05 for i in proc.intervals
    ), f"进程 CPU 采样必须带间隔窗（首采 interval=None 无意义）：{proc.intervals}"


def test_process_usage_survives_missing_cpu_percent_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """老 psutil/平台不提供进程 cpu_percent：该项降级为两段值，不整行采集失败。"""
    _stub_all_seams(monkeypatch, process=_FakeProcess(with_cpu_percent=False))
    item = hm.collect_host_metrics_sync().first("process_usage")
    assert item is not None and item.state == hm.STATE_OK, item
    assert "常驻内存" in item.value and "累计 CPU" in item.value


# ---------------------------------------------------------------------------
# 显存第二腿：NVML 挂死 → torch/CUDA 直读；两腿皆死才「未探测」
# ---------------------------------------------------------------------------


def test_gpu_memory_falls_back_to_cuda_leg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_all_seams(
        monkeypatch,
        cuda=([("Fake CUDA GPU", 3 * 1024**3, 8 * 1024**3)], ""),
    )
    item = hm.collect_host_metrics_sync().first("gpu_memory")
    assert item is not None and item.state == hm.STATE_OK, item
    assert "Fake CUDA GPU" in item.value and "已用 3.0 / 8.0 GB" in item.value
    assert "占用 37.5%" in item.value
    assert hm.NOT_PROBED not in item.value, "OK 行值里不许出现占位词"
    assert "CUDA" in item.source


def test_gpu_memory_both_legs_dead_lists_both_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hm,
        "_query_nvidia_smi",
        lambda timeout: ("", "nvidia-smi 退出码 9：Failed to initialize NVML: Unknown Error"),
    )
    monkeypatch.setattr(
        hm, "_query_cuda_vram", lambda: ([], "本机未装 torch（CUDA 直读腿不可用）")
    )
    monkeypatch.setattr(hm, "_adapter_version_rows", list)
    monkeypatch.setattr(hm, "_dependency_plugin_rows", list)
    monkeypatch.setattr(hm, "_core_dependency_rows", list)
    monkeypatch.setattr(hm, "_protocol_endpoint_rows", list)
    monkeypatch.setattr(hm, "_version_rows_map", dict)
    item = hm.collect_host_metrics_sync().first("gpu_memory")
    assert item is not None and item.state == hm.STATE_NOT_PROBED
    assert item.value == hm.NOT_PROBED
    assert "NVML" in item.note and "torch" in item.note, item.note


def test_cuda_leg_default_never_raises_without_torch() -> None:
    """默认腿在「没装 torch」的本机必须安静回空+原因，绝不带崩整卡。"""
    import importlib.util

    rows, note = hm._query_cuda_vram()
    assert isinstance(rows, list)
    if importlib.util.find_spec("torch") is None:
        assert rows == [] and "torch" in note.lower(), (rows, note)


# ---------------------------------------------------------------------------
# 协议端在线与端口
# ---------------------------------------------------------------------------


def test_protocol_endpoint_rows_land_as_own_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_all_seams(
        monkeypatch,
        endpoints=[("协议端连接", "QQ 在线 1（123456）"), ("监听端点", "127.0.0.1:8080")],
    )
    items = hm.collect_host_metrics_sync().by_id()["protocol_endpoints"]
    assert [(i.label, i.value) for i in items] == [
        ("协议端连接", "QQ 在线 1（123456）"),
        ("监听端点", "127.0.0.1:8080"),
    ]
    assert all(i.state == hm.STATE_OK for i in items)


def test_protocol_endpoints_absent_is_honest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_all_seams(monkeypatch, endpoints=[])
    item = hm.collect_host_metrics_sync().first("protocol_endpoints")
    assert item is not None and item.state == hm.STATE_NOT_PROBED
    assert item.value == hm.NOT_PROBED and item.note


def test_default_protocol_seam_never_raises_outside_bot_process() -> None:
    """测试环境没有初始化过的 nonebot 驱动：默认腿必须回 list、绝不外抛。"""
    rows = hm._protocol_endpoint_rows()
    assert isinstance(rows, list)
    for label, value in rows:
        assert label.strip() and value.strip()


# ---------------------------------------------------------------------------
# 呈现适配器：同一事实不许两处出现
# ---------------------------------------------------------------------------


def test_legacy_adapter_does_not_duplicate_runtime_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = hm.HostMetricsReport(
        items=(
            hm.HostMetric(
                "adapter_versions", "适配器全家", hm.GROUP_VERSIONS,
                "onebot 1.1.1", hm.STATE_OK, "s",
            ),
            hm.HostMetric(
                "dependency_plugins", "NoneBot 插件全家", hm.GROUP_VERSIONS,
                "alconna 0.1.0", hm.STATE_OK, "s",
            ),
            hm.HostMetric(
                "process_uptime", "本 bot 运行时长", hm.GROUP_USAGE,
                "2 小时 3 分", hm.STATE_OK, "s",
            ),
            hm.HostMetric(
                "protocol_endpoints", "协议端连接", hm.GROUP_USAGE,
                "QQ 在线 1（123）", hm.STATE_OK, "s",
            ),
        ),
        taken_at="21:30",
    )
    monkeypatch.setattr(hm, "collect_host_metrics_sync", lambda: report)
    host_status.invalidate_cached_snapshot_for_tests()
    groups = host_status.collect_host_snapshot()
    labels = [label for rows in groups.values() for label, _ in rows]
    assert "适配器全家" not in labels and "NoneBot 插件全家" not in labels
    assert "本 bot 运行时长" not in labels, "中央透传行已含「运行时长」，映射腿不许复读"
    assert "协议端连接" in labels, "新行照常上旧卡面（端点状态是点名要给的）"
    assert sum(1 for label in labels if label == "运行时长") <= 1
    host_status.invalidate_cached_snapshot_for_tests()


# ---------------------------------------------------------------------------
# 能力面整串：新行以人话进 body（render=False，零渲染）
# ---------------------------------------------------------------------------


def test_capability_body_lists_every_new_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_all_seams(
        monkeypatch,
        adapters=[("onebot", "1.1.1"), ("telegram", "2.2.2")],
        plugins=[("alconna", "0.62.1")],
        deps=[("pydantic", "9.9.9")],
        endpoints=[("监听端点", "127.0.0.1:8080")],
        version_map={"process_uptime": "3 小时 4 分"},
    )
    report = hm.collect_host_metrics_sync()
    result = host_state.build_host_state_result(report, render=False)
    for probe in (
        "适配器全家：onebot 1.1.1 · telegram 2.2.2",
        "NoneBot 插件全家：alconna 0.62.1",
        "核心依赖版本：pydantic 9.9.9",
        "本 bot 运行时长：3 小时 4 分",
        "监听端点：127.0.0.1:8080",
    ):
        assert probe in result.body, probe


# ---------------------------------------------------------------------------
# 形态锁：真身文件本体也不许手抄版本号
# ---------------------------------------------------------------------------


def test_true_source_file_has_no_version_literals() -> None:
    src = Path(hm.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\d+\.\d+\.\d+", src), "取数真身里出现 x.y.z 手抄版本号"
