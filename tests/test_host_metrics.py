"""宿主机状态取数（``domains/ops/host_metrics.py``）回归——第 5 项数据腿。

四条活性判据各锁一件会真发生的事（简报点名的四条）：

① 五项版本信息（nonebot / 适配器 / 协议端 / 插件 / Python）各一条断言，且断言
   的是**取自真身**——与 ``importlib.metadata.version("nonebot2")`` 这类现算值
   比对，卡上永远不出现第二个手写版本号；
② 单项采集抛异常只脏该项（注毒式），整卡仍成立且该项标「采集失败：<类型>」；
③ 全项「未探测」时不出现空值、也不出现任何编造的数字；
④ 采集走工作线程：spy 替换 ``_to_thread`` 断言每项都被 offload 一次，且用线程
   id 实证没有任何采集活落在事件循环线程上。

测试全离线：外部世界（psutil / nvidia-smi / 版本采集口）全部走 monkeypatch 的
「取数缝」；只有 ① 组与两个 live 用例故意不 mock，因为「现算值比对」本身就是
该组判据——被调用的也都是本机文件与包元数据，零网络。
"""

from __future__ import annotations

import ast
import asyncio
import importlib.metadata
import importlib.util
import platform
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.ops import host_metrics as hm
from plugins.bot_unified_runtime.domains.ops.monitor import error_report

ALL_STATES = {hm.STATE_OK, hm.STATE_NOT_PROBED, hm.STATE_FAILED}


def _fake_ps(*, memory_error: bool = False, memory_delay: float = 0.0) -> Any:
    """假 psutil：形状照真身，行为按用例注入（炸/慢/正常三态）。"""

    def virtual_memory() -> SimpleNamespace:
        if memory_delay:
            time.sleep(memory_delay)
        if memory_error:
            raise RuntimeError("内存采集炸了（测试注毒）")
        return SimpleNamespace(
            total=(32 * 1024**3),
            available=(8 * 1024**3),
            percent=75.0,
        )

    return SimpleNamespace(
        virtual_memory=virtual_memory,
        cpu_count=lambda logical=True: 16 if logical else 8,
        cpu_percent=lambda interval=0.0: 42.5,
        disk_partitions=lambda all=False: [SimpleNamespace(mountpoint="Q:\\")],
        disk_usage=lambda path: SimpleNamespace(
            total=(512 * 1024**3), free=(128 * 1024**3), percent=75.0
        ),
        Process=lambda *a, **k: SimpleNamespace(
            memory_info=lambda: SimpleNamespace(rss=int(1.5 * 1024**3)),
            cpu_times=lambda: SimpleNamespace(user=3661.0, system=30.0),
        ),
    )


def _isolated(
    monkeypatch: pytest.MonkeyPatch, *, ps: Any = None, **ps_kwargs: Any
) -> None:
    """把全部取数缝按到假数据上：只验形状/隔离性的用例不碰真机器。"""

    monkeypatch.setattr(hm, "_psutil_module", lambda: ps or _fake_ps(**ps_kwargs))
    monkeypatch.setattr(hm, "_version_rows_map", dict)
    monkeypatch.setattr(hm, "_cpu_model_text", lambda: "Fake Test CPU")
    monkeypatch.setattr(hm, "_gpu_model_rows", lambda: ["Fake GPU A", "Fake GPU B"])
    monkeypatch.setattr(
        hm, "_query_nvidia_smi", lambda timeout: ("", "测试环境不真调外部命令")
    )
    # 三段新增的五枚缝同样按到假数据上：形状/隔离用例不碰真包元数据与真驱动。
    monkeypatch.setattr(hm, "_adapter_version_rows", list)
    monkeypatch.setattr(hm, "_dependency_plugin_rows", list)
    monkeypatch.setattr(hm, "_core_dependency_rows", list)
    monkeypatch.setattr(hm, "_protocol_endpoint_rows", list)
    monkeypatch.setattr(
        hm, "_query_cuda_vram", lambda: ([], "测试环境不真读 CUDA")
    )


def _live_report(monkeypatch: pytest.MonkeyPatch) -> hm.HostMetricsReport:
    """真机采集，唯独掐掉 nvidia-smi（外部命令不许真调，值断言也不吃它）。"""
    monkeypatch.setattr(
        hm, "_query_nvidia_smi", lambda timeout: ("", "测试环境不真调外部命令")
    )
    return hm.collect_host_metrics_sync()


# ---------------------------------------------------------------------------
# ① 五项版本信息：各与真身现算值比对（不硬编码任何版本字符串）
# ---------------------------------------------------------------------------


def _expect_from_central(raw: str) -> str:
    """中央件诚实值到本卡值轨词汇的归一（与 _VERSION_MISSING_VALUES 同口径）。"""
    return hm.NOT_PROBED if raw in hm._VERSION_MISSING_VALUES or not raw else raw


def test_nonebot_version_comes_from_dist_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _live_report(monkeypatch).first("nonebot_version")
    assert item is not None
    assert item.value == _expect_from_central(importlib.metadata.version("nonebot2"))
    assert item.value and item.state == hm.STATE_OK
    assert item.source == hm.VERSION_PAIRS_SOURCE, "版本腿只准走中央采集口"


def test_onebot_adapter_version_comes_from_dist_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _live_report(monkeypatch).first("adapter_onebot_version")
    assert item is not None
    assert item.value == _expect_from_central(
        importlib.metadata.version("nonebot-adapter-onebot")
    )
    assert item.state == hm.STATE_OK


def test_protocol_client_version_matches_error_report_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = error_report._protocol_client_version_label(
        error_report._default_config_getter
    )
    item = _live_report(monkeypatch).first("protocol_client_version")
    assert item is not None
    assert item.value == _expect_from_central(expected)
    # 本机协议端 package.json 在册（AGENTS #55 实证 1.14.19 一系）：
    # 读到的是「名字 版本」形态，而不是拿适配器版本顶替。
    if expected != "未取到":
        assert " " in item.value or item.state == hm.STATE_NOT_PROBED


def test_plugin_version_matches_error_report_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = error_report._plugin_version()
    item = _live_report(monkeypatch).first("plugin_version")
    assert item is not None
    assert item.value == _expect_from_central(expected)


def test_python_version_matches_running_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _live_report(monkeypatch).first("python_version")
    assert item is not None
    assert item.value == _expect_from_central(platform.python_version())
    assert item.state == hm.STATE_OK


def test_os_version_matches_error_report_os_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _live_report(monkeypatch).first("os_version")
    assert item is not None
    assert item.value == _expect_from_central(error_report._os_label())


# ---------------------------------------------------------------------------
# ② 单项失败隔离（注毒式）
# ---------------------------------------------------------------------------


def test_single_collector_exception_only_dirties_that_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolated(monkeypatch, memory_error=True)
    report = hm.collect_host_metrics_sync()
    by_id = report.by_id()
    memory = by_id["memory"][0]
    assert memory.value == "采集失败：RuntimeError"
    assert memory.state == hm.STATE_FAILED
    # 整卡仍成立：每个在册项都在，其余项不陪葬。
    assert set(by_id) == set(hm.METRIC_SPEC_IDS)
    assert by_id["cpu_percent"][0].value == "42.5%"
    assert by_id["cpu_percent"][0].state == hm.STATE_OK
    assert by_id["disk"][0].state == hm.STATE_OK
    others = [m for m in report.items if m.metric_id != "memory"]
    assert all(m.state != hm.STATE_FAILED for m in others), others


def test_timeout_kills_one_item_not_the_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolated(monkeypatch, memory_delay=0.3)
    report = asyncio.run(hm.collect_host_metrics(item_timeout_seconds=0.05))
    by_id = report.by_id()
    assert by_id["memory"][0].value == "采集失败：TimeoutError"
    assert by_id["memory"][0].state == hm.STATE_FAILED
    assert by_id["cpu_percent"][0].state == hm.STATE_OK
    assert set(by_id) == set(hm.METRIC_SPEC_IDS), "超时腿不许让任何一项消失"


# ---------------------------------------------------------------------------
# ③ 全项未探测：无空值、无编造数字
# ---------------------------------------------------------------------------


def test_all_sources_absent_is_honest_without_fabricated_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hm, "_psutil_module", lambda: None)
    monkeypatch.setattr(hm, "_version_rows_map", dict)
    monkeypatch.setattr(hm, "_cpu_model_text", lambda: "")
    monkeypatch.setattr(hm, "_gpu_model_rows", list)
    monkeypatch.setattr(hm, "_query_nvidia_smi", lambda timeout: ("", "mock"))
    monkeypatch.setattr(hm, "_stdlib_disk_usage_rows", list)
    monkeypatch.setattr(hm, "_logical_core_count", lambda: None)
    # 三段新增的五枚缝一并掐掉：这一条是「全部来源缺席＝整卡未探测」的锁，
    # 任何一枚缝还在真读包元数据/真驱动，整卡就不干净。
    monkeypatch.setattr(hm, "_adapter_version_rows", list)
    monkeypatch.setattr(hm, "_dependency_plugin_rows", list)
    monkeypatch.setattr(hm, "_core_dependency_rows", list)
    monkeypatch.setattr(hm, "_protocol_endpoint_rows", list)
    monkeypatch.setattr(hm, "_query_cuda_vram", lambda: ([], "mock"))
    report = hm.collect_host_metrics_sync()
    assert len(report.items) == len(hm.METRIC_SPECS)
    for item in report.items:
        assert item.value == hm.NOT_PROBED, item
        assert item.state == hm.STATE_NOT_PROBED, item
        assert not re.search(r"\d", item.value), f"{item.label} 掺了数字：{item.value}"
    payload = hm.build_host_metrics_card_payload(report)
    assert all(str(v).strip() for v in payload["stats"].values())
    assert hm.NOT_PROBED in payload["stats"].values(), "整卡未探测也要有行可看"


def test_psutil_absent_uses_stdlib_fallback_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hm, "_psutil_module", lambda: None)
    monkeypatch.setattr(hm, "_version_rows_map", dict)
    monkeypatch.setattr(hm, "_cpu_model_text", lambda: "Fake CPU")
    monkeypatch.setattr(hm, "_gpu_model_rows", list)
    monkeypatch.setattr(hm, "_query_nvidia_smi", lambda timeout: ("", "mock"))
    monkeypatch.setattr(
        hm,
        "_stdlib_disk_usage_rows",
        lambda: [("Q:\\", "总 512.0 GB · 可用 128.0 GB · 占用 75.0%")],
    )
    monkeypatch.setattr(hm, "_logical_core_count", lambda: 12)
    report = hm.collect_host_metrics_sync()
    by_id = report.by_id()
    disk = by_id["disk"][0]
    assert disk.state == hm.STATE_OK
    assert "shutil" in disk.source, "兜底腿必须点名数据来源"
    assert disk.label == "磁盘 Q:\\"
    assert "12" in by_id["cpu_cores"][0].value
    assert "os.cpu_count" in by_id["cpu_cores"][0].source
    for metric_id in ("memory", "cpu_percent", "process_usage"):
        item = by_id[metric_id][0]
        assert item.value == hm.NOT_PROBED
        assert "本机未装 psutil" in item.note, item


# ---------------------------------------------------------------------------
# GPU 显存腿：解析靠罐头输出，NVML 失败按设计降级
# ---------------------------------------------------------------------------


def test_gpu_memory_parses_canned_nvidia_smi_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolated(monkeypatch)
    monkeypatch.setattr(
        hm,
        "_query_nvidia_smi",
        lambda timeout: ("Fake GPU One, 1024, 8192, 45\n", ""),
    )
    item = hm.collect_host_metrics_sync().first("gpu_memory")
    assert item is not None and item.state == hm.STATE_OK
    assert "已用 1.0 / 8.0 GB" in item.value
    assert "12.5%" in item.value and "45%" in item.value
    assert "nvidia-smi" in item.source


def test_gpu_memory_degrades_honestly_when_nvml_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本机实况：nvidia-smi 会 Failed to initialize NVML——必须降级不编数。"""
    _isolated(monkeypatch)
    monkeypatch.setattr(
        hm,
        "_query_nvidia_smi",
        lambda timeout: (
            "",
            "nvidia-smi 退出码 9：Failed to initialize NVML: Unknown Error",
        ),
    )
    item = hm.collect_host_metrics_sync().first("gpu_memory")
    assert item is not None
    assert item.value == hm.NOT_PROBED
    assert item.state == hm.STATE_NOT_PROBED
    assert "NVML" in item.note


# ---------------------------------------------------------------------------
# 呈现腿：payload 形状 / 同名去重 / 文本版
# ---------------------------------------------------------------------------


def _synthetic_report() -> hm.HostMetricsReport:
    """合成报告只取子集；「在册项全覆盖」由真采集用例负责，这里只验呈现腿。"""
    items = [
        hm.HostMetric("nonebot_version", "NoneBot2", hm.GROUP_VERSIONS, "2.5.0", "ok"),
        hm.HostMetric("gpu_model", "显卡", hm.GROUP_HARDWARE, "GPU A", "ok"),
        hm.HostMetric("gpu_model", "显卡", hm.GROUP_HARDWARE, "GPU B", "ok"),
        hm.HostMetric("gpu_memory", "显卡显存", hm.GROUP_HARDWARE, hm.NOT_PROBED, "not_probed"),
        hm.HostMetric("memory", "内存", hm.GROUP_HARDWARE, "采集失败：RuntimeError", "failed"),
    ]
    return hm.HostMetricsReport(items=tuple(items), taken_at="21:30")


def test_card_payload_shape_and_duplicate_labels_survive() -> None:
    report = _synthetic_report()
    payload = hm.build_host_metrics_card_payload(report)
    assert payload["page_type"] == "universal"
    assert payload["title"] == hm.CARD_TITLE
    assert payload["badge"] == hm.CARD_BADGE
    assert payload["feature_label"] == hm.CARD_FEATURE_LABEL
    stats = payload["stats"]
    assert len(stats) == len(report.items), "同名属性吃掉一行=少一份读数"
    assert stats["显卡"] == "GPU A" and stats["显卡 2"] == "GPU B"
    assert stats["内存"] == "采集失败：RuntimeError"
    assert all(str(v).strip() for v in stats.values())
    assert "取样时刻 21:30" in payload["summary"]


def test_metrics_text_is_label_colon_value_lines() -> None:
    text = hm.metrics_text(_synthetic_report())
    lines = text.splitlines()
    assert lines[0] == "NoneBot2：2.5.0"
    assert len(lines) == 5


def test_live_report_covers_every_spec_id_with_closed_state_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真机一趟：15 个在册项一个不少，状态全在闭集里，值永不为空。"""
    report = _live_report(monkeypatch)
    by_id = report.by_id()
    assert set(by_id) == set(hm.METRIC_SPEC_IDS)
    for item in report.items:
        assert item.state in ALL_STATES, item
        assert item.value.strip(), item
        if item.state == hm.STATE_OK:
            assert hm.NOT_PROBED not in item.value
            assert not item.value.startswith("采集失败：")


@pytest.mark.skipif(
    importlib.util.find_spec("psutil") is None, reason="本机未装 psutil，实数腿不适用"
)
def test_live_hardware_legs_return_real_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _live_report(monkeypatch)
    by_id = report.by_id()
    for metric_id in ("cpu_model", "cpu_cores", "memory", "cpu_percent", "process_usage"):
        item = by_id[metric_id][0]
        assert item.state == hm.STATE_OK, item
        assert re.search(r"\d", item.value), f"{item.label} 没拿到真数：{item.value}"
    assert "可用" in by_id["memory"][0].value, "简报点名要有内存可用量"
    assert "常驻内存" in by_id["process_usage"][0].value
    assert any(m.label.startswith("磁盘") for m in by_id["disk"])


# ---------------------------------------------------------------------------
# ④ 事件循环不阻塞：每项采集都经 _to_thread 落到工作线程
# ---------------------------------------------------------------------------


def test_async_collect_offloads_every_item_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolated(monkeypatch)
    real_to_thread = hm._to_thread
    dispatched: list[str] = []
    worker_ids: list[int] = []
    main_ident = threading.get_ident()

    async def _spy(fn: Any, *args: Any, **kwargs: Any) -> Any:
        dispatched.append(str(args[0]) if args else getattr(fn, "__name__", "?"))

        def _traced() -> Any:
            worker_ids.append(threading.get_ident())
            return fn(*args, **kwargs)

        return await real_to_thread(_traced)

    monkeypatch.setattr(hm, "_to_thread", _spy)
    report = asyncio.run(hm.collect_host_metrics())
    assert sorted(dispatched) == sorted(hm.METRIC_SPEC_IDS), (
        "每个在册项都必须被 offload 一次（少一项=有一项在环上现取）"
    )
    assert worker_ids and all(tid != main_ident for tid in worker_ids), (
        "采集活落在了事件循环线程上"
    )
    assert set(report.by_id()) == set(hm.METRIC_SPEC_IDS)


def test_psutil_is_imported_lazily_not_at_module_level() -> None:
    """模块级不许 import psutil——精简环境要连「诚实说拿不到」这条路都留着。"""
    tree = ast.parse(Path(hm.__file__).read_text(encoding="utf-8"))
    module_level = {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    assert "psutil" not in module_level, module_level
