"""需求 5 数据腿 · 「在册项 ⇔ 采集器」覆盖率机器锁（S-T-HOST2）。

已有 ``tests/test_host_metrics.py`` 与 ``tests/test_host_metrics_single_source.py``
都拦不住这个缺口，而且各有明确盲区，所以必须另立结构锁：

- 单源 AST 门（single_source）执法的是「取数落点唯一」——它扫读法形态，
  对「``METRIC_SPECS`` 里登了名但 ``_COLLECTORS`` 里没接采集器」**全盲**；
  2026-09-26 五枚采集器缺位正是这个形态：22 枚在册、17 枚采集器，
  ``_collect_spec`` 对缺位项抛 ``KeyError``，卡上端出五行「采集失败：KeyError」。
- 回归件（test_host_metrics.py）的两枚红是**间接**撞上这个缺口的（隔离锁与
  整卡未探测锁不许有任何采集失败项陪葬）；它修好后若再有人加一枚 spec 忘了
  接采集器，只有本文件的结构锁会当场点名。

锁自带注毒自证：纯谓词 ``coverage_violations`` 在「多一枚未注册采集器的在册项 /
少一枚在册项的采集器」两个方向都必须报出名字——注毒不红的锁是摆设。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.ops import host_metrics as hm


def coverage_violations(
    spec_ids: tuple[str, ...] | list[str],
    collector_ids: tuple[str, ...] | list[str] | set[str],
) -> list[str]:
    """纯谓词：在册项与采集器的一一对应差集（排序后逐名点名）。

    非空 = 有在册项没采集器（KeyError 形态）或有采集器没在册项（死代码形态）。
    拆成纯函数是为了注毒可以不经真模块、不碰 monkeypatch 就验锁真会红。
    """
    specs = set(spec_ids)
    collectors = set(collector_ids)
    missing = [f"未注册采集器：{metric_id}" for metric_id in sorted(specs - collectors)]
    orphan = [f"未在册的采集器：{metric_id}" for metric_id in sorted(collectors - specs)]
    return missing + orphan


# ---------------------------------------------------------------------------
# 结构锁：现算比对，一一对应，一个不许少
# ---------------------------------------------------------------------------


def test_collectors_cover_every_registered_spec() -> None:
    assert (
        coverage_violations(hm.METRIC_SPEC_IDS, set(hm._COLLECTORS)) == []
    ), "在册项与采集器失配——缺位项上卡就是「采集失败：KeyError」"
    assert set(hm._COLLECTORS) == set(hm.METRIC_SPEC_IDS)


def test_spec_ids_declared_exactly_once_each() -> None:
    ids = list(hm.METRIC_SPEC_IDS)
    assert len(ids) == len(set(ids)), "同一 metric_id 注册两次＝一行事实两处漂移"
    assert set(ids) == {spec.metric_id for spec in hm.METRIC_SPECS}
    assert set(hm._SPEC_BY_ID) == set(ids), "映射表与在册清单必须同源同集"


def test_registered_collectors_are_callable() -> None:
    for metric_id, fn in hm._COLLECTORS.items():
        assert callable(fn), f"{metric_id} 的采集器不是可调用对象"


# ---------------------------------------------------------------------------
# 注毒自证：谓词在两个方向都必须报红，否则上面的锁是摆设
# ---------------------------------------------------------------------------


def test_poison_unregistered_spec_turns_lock_red() -> None:
    poisoned = [*hm.METRIC_SPEC_IDS, "seat_poison_unregistered"]
    violations = coverage_violations(poisoned, set(hm._COLLECTORS))
    assert violations == ["未注册采集器：seat_poison_unregistered"], violations


def test_poison_orphan_collector_turns_lock_red() -> None:
    collectors = set(hm._COLLECTORS) | {"seat_poison_orphan"}
    violations = coverage_violations(hm.METRIC_SPEC_IDS, collectors)
    assert violations == ["未在册的采集器：seat_poison_orphan"], violations


def test_clean_pairing_is_silence() -> None:
    ids = list(hm.METRIC_SPEC_IDS)
    assert coverage_violations(ids, ids) == []


# ---------------------------------------------------------------------------
# 功能锁：真走一趟采集，任何在册项都不许以 KeyError 形态缺席
# （结构锁防的是注册表失配；这条防的是「注册了但采集器本体炸在查找之前」
# 的同族回归——缝全部掐假，只验收口形态）
# ---------------------------------------------------------------------------


def _stub_every_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hm, "_psutil_module", lambda: None)
    monkeypatch.setattr(hm, "_logical_core_count", lambda: None)
    monkeypatch.setattr(hm, "_version_rows_map", dict)
    monkeypatch.setattr(hm, "_cpu_model_text", lambda: "")
    monkeypatch.setattr(hm, "_gpu_model_rows", list)
    monkeypatch.setattr(hm, "_query_nvidia_smi", lambda timeout: ("", "mock"))
    monkeypatch.setattr(hm, "_stdlib_disk_usage_rows", list)
    monkeypatch.setattr(hm, "_adapter_version_rows", list)
    monkeypatch.setattr(hm, "_dependency_plugin_rows", list)
    monkeypatch.setattr(hm, "_core_dependency_rows", list)
    monkeypatch.setattr(hm, "_protocol_endpoint_rows", list)
    monkeypatch.setattr(hm, "_query_cuda_vram", lambda: ([], "mock"))


def test_full_collection_has_no_keyerror_shaped_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_every_seam(monkeypatch)
    report = hm.collect_host_metrics_sync()
    by_id = report.by_id()
    assert set(by_id) == set(hm.METRIC_SPEC_IDS), "每个在册项都必须端出行"
    for item in report.items:
        assert item.state in {hm.STATE_OK, hm.STATE_NOT_PROBED}, item
        assert not item.value.startswith("采集失败："), (
            f"{item.label} 以采集失败形态缺席＝大概率是没接采集器的 KeyError"
        )
