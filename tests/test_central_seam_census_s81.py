"""S81 量具锁：普查尺 ``unknown_ids`` 的分档必须**只加账、不销账**。

背景（2026-09-24 S81 取证）：``scripts/central_seam_census.py`` 的判据⑦把生产面一切
``capability_id=`` 字面量都记成 "unknown"，48 枚里既有 ``/bot`` 派发表那些**真的在被执行**
的在册表外 id，也有 ``CapabilityResult``/``SendRequest`` 这类**纯记录字段**——两者混在一
个词里，谁都可能把它读成"48 条债"或"0 条债"。本锁件钉三件事：

① 分档必须恰好划分 ``unknown_ids``（``routed ∪ record_only == unknown_ids`` 且不重叠）；
   任何让账变小的改法当场红。
② 注毒四形各归其位：在册表外的 ``invoke`` 直呼 / 同步 ``pipeline.handle`` / 变量携带进缝
   三形必须落进 ``routed``；只在契约对象字段里出现的必须落进 ``record_only``。
   （判据是**形状**推出来的，不是手写白名单——所以伪造一条野调用一定被抓。）
③ 形态判据集 ``SITE_EXEC_FUNCS`` 只喂分档，**绝不喂三态**：把该集人为收窄后重跑整树，
   ``states`` 与 ``unknown_ids`` 必须逐值不变，只有 ``routed`` 允许变小。
   外加一条崩溃回归：``execution`` 已申报 ∧ 无 seam/invoke 证据这条组合旧尺直接抛
   ``TypeError`` 把整把尺打死（S81 实炸一次），现在必须出 ``wired`` 而不是炸。

全离线：只读源码树做 AST 静态解析，零 import 生产模块、零网络、零运行数据触点。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
_CENSUS = ROOT / "scripts" / "central_seam_census.py"

#: 注毒四形的 id（都不在唯一真身册，命名空间独占 s81.，防与真能力撞名）。
_POISON_INVOKE = "s81.poison.direct-invoke"
_POISON_SYNC_GENERIC = "s81.poison.sync-generic"
_POISON_VAR_CARRIED = "s81.poison.var-carried"
_POISON_FIELD_ONLY = "s81.poison.field-only"

#: 一文件四形：三形该被认成"在跑"，一形该被认成"只是字段"。
_POISON_SRC = f'''\
"""S81 注毒件：四种 capability_id 落点形态同框。"""


async def _shapes(invoker: object, pipeline: object, message: object, capability: object) -> object:
    await invoker.invoke(capability_id="{_POISON_INVOKE}")  # 形1：直呼中央 invoker
    pipeline.handle(message, capability, capability_id="{_POISON_SYNC_GENERIC}")  # 形2：同步泛型执行器
    return CapabilityResult(request_id="r1", capability_id="{_POISON_FIELD_ONLY}", kind="text")  # 形3：契约字段


async def _handle_demo(pipeline: object, capability: object) -> object:
    capability_id = "{_POISON_VAR_CARRIED}"  # 形4：变量携带进汇合缝
    return await _run_capability_through_pipeline(
        pipeline=pipeline,
        capability=capability,
        capability_id=capability_id,
    )
'''


def _run_census(*extra: str) -> dict[str, Any]:
    """跑尺子本体（CLI 出口，与常驻门同一条路）。``encoding`` 必钉——本仓铁律。"""
    out = subprocess.run(
        [sys.executable, str(_CENSUS), "--json", *extra],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
        check=False,
    )
    assert out.returncode == 0, f"普查尺跑不起来（RC={out.returncode}）：{out.stderr[-500:]}"
    payload = json.loads(out.stdout)
    assert payload["integrity"]["ok"] is True, f"尺缺件/读不出/解析失败：{payload['integrity']}"
    return payload


_REAL: dict[str, Any] | None = None


def _real() -> dict[str, Any]:
    """整树只跑一次，多腿共用（与 S67 门同一缓存哲学）。"""
    global _REAL
    if _REAL is None:
        _REAL = _run_census()
    return _REAL


@pytest.fixture()
def census_module():
    """在进程内载入尺件（只为直戳 ``_state`` 与改判据集两用），并复原它抬过的递归上限。"""
    prev = sys.getrecursionlimit()
    spec = importlib.util.spec_from_file_location("s81_census_under_test", _CENSUS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.setrecursionlimit(prev)


# ---------------------------------------------------------------- ① 恰好划分


def test_partition_covers_unknown_ids_exactly_on_real_tree() -> None:
    """两桶必须**恰好**划分 unknown_ids：不重叠、更不丢账（丢账＝尺自证变窄）。"""
    payload = _real()
    part = payload["unknown_id_partition"]
    unknown = set(payload["unknown_ids"])
    routed, record = set(part["routed"]), set(part["record_only"])
    assert routed | record == unknown, f"丢账：{sorted(unknown - (routed | record))}"
    assert not (routed & record), f"重叠：{sorted(routed & record)}"
    assert part["covers_exactly"] is True
    # 每枚入账的 id 都必须留坐标：只报数不给点位＝尺在含糊（本席首版锁漏了这一腿，补上）。
    assert set(payload["unknown_id_sites"]) == unknown, (
        "unknown_id_sites 与 unknown_ids 不同集＝有账无坐标或有坐标无账"
    )
    # 账数自证：分档是加在 unknown 之上的，不是替换它。
    assert payload["counts"]["unknown_ids"] == len(unknown)
    assert payload["counts"]["unknown_ids_routed"] + payload["counts"]["unknown_ids_record_only"] == len(unknown)


def test_routed_ids_all_really_reach_an_execution_point() -> None:
    """``routed`` 的每枚都必须真有一处"交给执行点"的落点，且带坐标——防空口记账。"""
    payload = _real()
    roster = payload["roster"]
    for cid in payload["unknown_id_partition"]["routed"]:
        sites = roster[cid]["unknown_sites"]
        assert sites, f"{cid} 记为 routed 却零坐标"
        assert any(s["shape"] == "routed" for s in sites), f"{cid} 无 routed 形态落点"
        for s in sites:
            if s["shape"] == "routed":
                assert s["file"] and isinstance(s["line"], int) and s["fn"]
                assert s["via"] in ("literal", "variable")


def test_record_only_ids_never_reach_an_execution_point() -> None:
    """反向腿：``record_only`` 的每一处落点都不得是执行点（否则分档在替野调用遮掩）。"""
    payload = _real()
    roster = payload["roster"]
    for cid in payload["unknown_id_partition"]["record_only"]:
        sites = roster[cid]["unknown_sites"]
        assert sites, f"{cid} 在册表外却连一处落点都没有（尺漏扫，须查扫描面）"
        assert all(s["shape"] == "record" for s in sites), f"{cid} 有执行点落点却被记成 record"


# ---------------------------------------------------------------- ② 注毒四形


@pytest.fixture(scope="module")
def poisoned(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    path = tmp_path_factory.mktemp("s81-poison") / "s81_shapes.py"
    path.write_text(_POISON_SRC, encoding="utf-8")
    return _run_census("--poison", str(path))


def test_poison_offroster_invoke_lands_in_routed(poisoned: dict[str, Any]) -> None:
    """伪造一条不在册的 ``invoke(capability_id=…)`` ⇒ 必须出现在 routed（本席命门）。"""
    part = poisoned["unknown_id_partition"]
    assert _POISON_INVOKE in poisoned["unknown_ids"], "在册表外的中央直呼竟未入 unknown 账"
    assert _POISON_INVOKE in part["routed"], "在册表外的中央直呼被记成记录字段＝遮掩第二条路"


def test_poison_sync_generic_lands_in_routed(poisoned: dict[str, Any]) -> None:
    """``pipeline.handle`` 与 ``handle_async`` 是同型泛型执行器 ⇒ 也必须被抓进 routed。"""
    assert _POISON_SYNC_GENERIC in poisoned["unknown_id_partition"]["routed"]


def test_poison_variable_carried_id_lands_in_routed(poisoned: dict[str, Any]) -> None:
    """id 写在赋值里、变量交给汇合缝 ⇒ 判据⑧必须认下来（``/bot`` 派发表就藏在这儿）。"""
    assert _POISON_VAR_CARRIED in poisoned["unknown_ids"]
    assert _POISON_VAR_CARRIED in poisoned["unknown_id_partition"]["routed"]


def test_poison_contract_field_lands_in_record_only(poisoned: dict[str, Any]) -> None:
    """只在契约对象字段里出现的 id ⇒ record_only（排除是**形状**推出来的，不是名字白名单）。"""
    assert _POISON_FIELD_ONLY in poisoned["unknown_id_partition"]["record_only"]


def test_poison_does_not_shrink_the_real_account(poisoned: dict[str, Any]) -> None:
    """注毒只许加账：真树 48 枚必须全部仍在，且 routed 只增不减。"""
    real, part = _real(), poisoned["unknown_id_partition"]
    assert set(real["unknown_ids"]) <= set(poisoned["unknown_ids"])
    assert set(real["unknown_id_partition"]["routed"]) <= set(part["routed"])


# ---------------------------------------------------------------- ③ 判据隔离


def test_shape_set_never_feeds_the_three_state_buckets(census_module: Any) -> None:
    """把 ``SITE_EXEC_FUNCS`` 人为收窄后重跑整树：三态与 unknown 账必须逐值不变。

    这条锁的是"动形态判据＝动债"这条路：形态集只准搬分档，不准搬 ``states``。
    反向自证在同一条断言里——若哪天有人让 ``_state`` 读它，``states`` 就会在这里跳。
    """
    full = census_module.Census([]).collect()
    narrow_mod = census_module
    original = narrow_mod.SITE_EXEC_FUNCS
    try:
        narrow_mod.SITE_EXEC_FUNCS = frozenset({"orchestrated_command"})
        narrow = census_module.Census([]).collect()
    finally:
        narrow_mod.SITE_EXEC_FUNCS = original
    assert narrow["counts"]["states"] == full["counts"]["states"], "形态判据集渗进了三态账"
    assert narrow["counts"]["declared"] == full["counts"]["declared"]
    assert narrow["counts"]["universe"] == full["counts"]["universe"]
    assert narrow["unknown_ids"] == full["unknown_ids"], "收窄形态集竟让 unknown 账变小＝缩扫描面"
    routed_n = set(narrow["unknown_id_partition"]["routed"])
    assert routed_n <= set(full["unknown_id_partition"]["routed"]), "形态集只能少认，不能多吞真账"
    # 少认之后仍须恰好划分（分档与形态集解耦，不许留无归属的账）。
    assert narrow["unknown_id_partition"]["covers_exactly"] is True


def test_execution_declared_without_evidence_does_not_crash_ruler(census_module: Any) -> None:
    """崩溃回归：``execution`` 已申报 ∧ 无缝/invoke 证据 ⇒ 旧尺 ``list & set`` 当场 TypeError。

    收编波每加一行 ``execution=CapabilityExecution(...)`` 而汇合点还没落（或汇合点用变量
    携带 id）就正好踩这条组合，整把尺被打死；S67 门只会报"量具跑不起来"，不报根因。
    """
    cen = census_module.Census([])
    cen.adapter_default = "command"
    cen.decls["s81.crash.probe"] = [
        {
            "file": "runtime/capability_protocols.py",
            "line": 1,
            "adapter": None,
            "implementation_ref": None,
            "execution_declared": True,
            "in_func": "<module>",
        }
    ]
    assert cen._state("s81.crash.probe") == "wired"

    # 杀伤力自证：``adapters`` 的出口形状仍是 sorted list（roster 消费者按列表读），
    # 而旧写法那句 list & set 在这个形状上必炸——证明上面这条锁拦得住回归，不是空跑。
    adapters = cen._decl_execution("s81.crash.probe")["adapters"]
    assert isinstance(adapters, list)
    with pytest.raises(TypeError):
        adapters & {"command", "prepared"}  # type: ignore[attr-defined]
