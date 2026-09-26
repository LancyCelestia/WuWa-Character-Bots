"""S200 锁：非能力署名标签显式桶（用户裁定 2.A）——把「纯落款 id」从「在册表外」差集里摘出，
但不许把它写成新的免检抽屉。

被检对象
--------
``scripts/central_seam_census.py`` 的 ``SIGNATURE_LABEL_IDS`` 登记处 +
派生判据 ``Census._derived_signature_ids`` + ``_build_output`` 里的署名桶分档。

本锁件钉死五件事（各拦一种造假手法，互不替代）
--------------------------------------------
① **成员冻结 + 方向 ceiling（只准缩、不许涨）**：登记处成员 == 裁定 2.A 点名的 5 枚；
   枚数受一枚**手写整数字面量**上限 ``SIGNATURE_LABEL_COUNT_CEILING`` 约束。新增成员
   （哪怕它也是纯落款）会同时撞成员锁与 ceiling，除非 owner 带证据改这两处。
② **反向锁（本席命门）**：真被调度过的 id 一旦被申报进桶 ⇒ 派生判据不认 ⇒
   ``signature_claimed_not_derived`` 点名它、且它**不会**从 ``unknown_ids`` 消失。
   注毒一发（把一枚 routed id 塞进桶）证明它有牙。⇒ 桶不能用来藏"其实在跑的第二条路"。
③ **不隐身**：5 枚署名 id 仍逐枚留在 ``roster`` + ``signature_label_sites``（有坐标可查），
   只是不计入 headline 差集。隐身＝再也查不到＝一票否决面。
④ **桶不是抽屉（保守侧自证）**：派生其实认 12 枚纯落款，但只有 authoring 明确认领的 5 枚
   被摘；另 7 枚 record_only（``bot.decision`` 一类）**照旧留在差集**里。这条锁死
   "顺手把所有 record_only 一键抹掉"那形。反向注毒（摘一枚真 record_only）证明
   *一致性锁抓不到它*——正因如此 ①的 ceiling 才不可省。
⑤ **分档不变量仍在**：``routed ∪ record_only`` 恰好划分**去掉桶后**的差集，
   ``unknown_id_sites`` 键集 == ``unknown_ids``，且 ``reported == raw - len(bucket)``。

全离线：只 shell 出/载入普查尺做 AST 静态解析，零 import 生产模块、零网络、零运行数据触点。
起点==实测：本件只记"此刻现算 raw=48 / reported=43"这类读数进 SEAT-S200 报告，绝不写"达标"，
也绝不把桶叙述成"这些能力已处理"——它们只是**被诚实地重新分类为非能力落款**。

复跑
----
.. code-block:: bash

    cd ChatBot/ChatBot && export PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \\
      PYTHONIOENCODING=utf-8 PYTHONPYCACHEPREFIX=<私有目录>
    ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_signature_label_bucket.py -p no:cacheprovider --basetemp=<私有目录> -q
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_CENSUS = ROOT / "scripts" / "central_seam_census.py"
_ME = Path(__file__)

#: 用户裁定 2.A 点名的 5 枚「只在根上作署名/记录字段」的非能力标签。
#: 成员改动 = 必须同步改本清单（＝带证据的显式动作），且不得越过下面的 ceiling。
EXPECTED_SIGNATURE_LABELS: frozenset[str] = frozenset(
    {
        "bot.cookie_expiry_notice",
        "bot.credential_check",
        "bot.group_digest_push",
        "bot.mail.notify",
        "bot.send_queue_worker",
    }
)

#: 方向棘轮上限：登记处枚数只准降、不许涨。手写整数字面量，绝不允许写成派生式
#: （由 ``test_ceiling_is_a_handwritten_int_literal`` AST 锁死——照 ``test_offseam_..._gate`` 家规）。
SIGNATURE_LABEL_COUNT_CEILING = 5


# ------------------------------------------------------------------ 取数口
def _load_census_module() -> Any:
    prev = sys.getrecursionlimit()
    spec = importlib.util.spec_from_file_location("s200_census_under_test", _CENSUS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # 记录：exec_module 会抬递归上限，交回调用方决定何时复原（poison 用例只读不改树，无泄漏风险）。
    module._s200_prev_recursionlimit = prev  # type: ignore[attr-defined]
    return module


def _run_census_json() -> dict[str, Any]:
    """跑尺子 CLI 出口（与 S81/S95 门同一条路）。``encoding`` 必钉——本仓铁律。"""
    out = subprocess.run(
        [sys.executable, str(_CENSUS), "--json"],
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
    global _REAL
    if _REAL is None:
        _REAL = _run_census_json()
    return _REAL


# ------------------------------------------------------------------ ① 成员冻结 + 方向 ceiling
def test_module_registry_equals_adjudicated_five() -> None:
    """登记处成员 == 裁定 2.A 点名的 5 枚（多一枚少一枚都要显式改本锁＝带证据）。"""
    module = _load_census_module()
    assert frozenset(module.SIGNATURE_LABEL_IDS) == EXPECTED_SIGNATURE_LABELS, (
        f"登记处成员与裁定 2.A 不符：多={sorted(set(module.SIGNATURE_LABEL_IDS) - EXPECTED_SIGNATURE_LABELS)} "
        f"少={sorted(EXPECTED_SIGNATURE_LABELS - set(module.SIGNATURE_LABEL_IDS))}"
    )


def test_registry_size_within_direction_ceiling() -> None:
    """方向锁（只准缩不许涨）：现算枚数不得超过手写上限。涨＝有人往桶里塞新豁免。"""
    module = _load_census_module()
    assert len(module.SIGNATURE_LABEL_IDS) <= SIGNATURE_LABEL_COUNT_CEILING, (
        f"登记处枚数 {len(module.SIGNATURE_LABEL_IDS)} > 上限 "
        f"{SIGNATURE_LABEL_COUNT_CEILING}＝桶在膨胀（新成员必须带证据、由 owner 复算后同批抬上限）"
    )


def test_ceiling_is_a_handwritten_int_literal() -> None:
    """ceiling 必须是顶层**整数字面量**，不得写成 ``= len(EXPECTED...)`` 等派生式
    （派生式＝上限跟着被检对象动＝棘轮对真树结构性不红，S95/S65 同型定罪形态）。"""
    tree = ast.parse(_ME.read_text(encoding="utf-8"))
    found: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    found[tgt.id] = node.value
    value = found.get("SIGNATURE_LABEL_COUNT_CEILING")
    assert value is not None, "本件顶层找不到 SIGNATURE_LABEL_COUNT_CEILING 赋值"
    assert (
        isinstance(value, ast.Constant)
        and isinstance(value.value, int)
        and not isinstance(value.value, bool)
    ), "ceiling 不是手写整数字面量＝方向棘轮被改成派生式（自指=对真树恒不执法）"


# ------------------------------------------------------------------ ② 反向锁（真调度 id 不许落桶）
def test_every_claimed_label_is_actually_derived_on_real_tree() -> None:
    """真树活账：5 枚必须逐枚被派生判据认成纯落款（claimed ⊆ derived），反向信号必空。"""
    out = _real()
    assert out["signature_claimed_not_derived"] == [], (
        f"以下 id 被申报为署名却被派生判据否掉（有执行点/无落款证据）："
        f"{out['signature_claimed_not_derived']}"
    )
    assert frozenset(out["signature_labels"]) == EXPECTED_SIGNATURE_LABELS


def test_poison_claiming_a_routed_id_is_rejected_and_stays_visible() -> None:
    """反向锁注毒（本席命门）：把一枚**有执行点**的在册表外 id 塞进桶——
    派生判据必须否掉它（记进 claimed_not_derived），且它**绝不从 unknown_ids 消失**。
    证「桶不是藏第二条路的抽屉」：真被调度过的东西，申报也藏不住。"""
    module = _load_census_module()
    routed = _real()["unknown_id_partition"]["routed"]
    assert routed, "真树无 routed 在册表外 id＝注毒失去落点（先查普查是否失明）"
    victim = routed[0]
    original = module.SIGNATURE_LABEL_IDS
    try:
        module.SIGNATURE_LABEL_IDS = frozenset(set(original) | {victim})
        out = module.Census([]).collect()
    finally:
        module.SIGNATURE_LABEL_IDS = original
    assert victim in out["signature_claimed_not_derived"], (
        f"申报一枚有执行点的 id（{victim}）竟未被反向锁点名＝派生判据空转")
    assert victim in out["unknown_ids"], f"{victim} 被『申报即摘除』＝桶成了免检抽屉"
    assert victim not in out["signature_labels"], f"{victim} 落进署名桶＝把在跑的能力当落款抹掉"


# ------------------------------------------------------------------ ③ 不隐身
def test_signature_labels_remain_visible_in_detail() -> None:
    """5 枚仍逐枚留在 roster + signature_label_sites（有坐标可查），只是不计入 headline 差集。"""
    out = _real()
    for cid in EXPECTED_SIGNATURE_LABELS:
        assert cid in out["roster"], f"{cid} 从 roster 消失＝隐身（再也查不到）"
        assert out["roster"][cid]["unknown_sites"], f"{cid} 在 roster 里连一处落款坐标都没有"
        assert cid in out["signature_label_sites"], f"{cid} 不在 signature_label_sites＝明细里被抹平"
        assert out["signature_label_sites"][cid], f"{cid} 署名桶明细为空"
        assert cid not in out["unknown_ids"], f"{cid} 仍被算进在册表外差集＝桶没生效"


# ------------------------------------------------------------------ ④ 桶不是抽屉（保守侧）
def test_bucket_only_sweeps_claimed_not_all_record_only() -> None:
    """派生其实认更多纯落款，但只有 authoring 认领的 5 枚被摘；
    其余 record_only 照旧留在差集里（未认领者不得被一键抹掉）。"""
    out = _real()
    record_only = set(out["unknown_id_partition"]["record_only"])
    assert record_only, "真树 record_only 为空＝无法自证保守侧（先查普查）"
    assert record_only & EXPECTED_SIGNATURE_LABELS == set(), (
        f"被摘的署名 id 不应还出现在 record_only 里：{record_only & EXPECTED_SIGNATURE_LABELS}")
    # 那 7 枚未被认领的纯落款 id 必须仍在差集，且不在桶里。
    for cid in record_only:
        assert cid in out["unknown_ids"] and cid not in out["signature_labels"]


def test_poison_sweeping_a_genuine_record_only_escapes_consistency_lock() -> None:
    """④ 牙口自证：把一枚**真·未认领 record_only** 塞进桶——派生会接受它（它确实纯落款），
    ⇒ 反向锁（②）抓不到、它会静默离开差集。这条用例证明 *一致性锁不足以自守*，
    正因如此 ①的 ceiling 才不可省（真树枚数已顶满 5，再多一枚即撞上限）。"""
    module = _load_census_module()
    record_only = _real()["unknown_id_partition"]["record_only"]
    assert record_only, "无 record_only 样本＝注毒失去落点"
    victim = min(record_only)
    original = module.SIGNATURE_LABEL_IDS
    try:
        module.SIGNATURE_LABEL_IDS = frozenset(set(original) | {victim})
        out = module.Census([]).collect()
    finally:
        module.SIGNATURE_LABEL_IDS = original
    # 一致性锁放行了它（派生认纯落款）：
    assert victim not in out["signature_claimed_not_derived"], "这枚本就纯落款，反向锁不该误报"
    # 它确实静默离开了差集：
    assert victim in out["signature_labels"] and victim not in out["unknown_ids"]
    # ⇒ 唯一拦得住它的是 ceiling：真树 5 枚 + 这枚 = 6 > 上限。
    assert len(original) + 1 > SIGNATURE_LABEL_COUNT_CEILING, (
        "ceiling 留了余量＝静默扩容拦不住，收紧上限或改回等值")


# ------------------------------------------------------------------ ⑤ 分档不变量
def test_partition_invariants_hold_on_reduced_diff() -> None:
    """去掉桶后：routed ∪ record_only 恰好划分差集、明细与账同集、且 reported==raw-桶。"""
    out = _real()
    part = out["unknown_id_partition"]
    unknown = set(out["unknown_ids"])
    routed, record = set(part["routed"]), set(part["record_only"])
    assert routed | record == unknown, f"丢账：{sorted(unknown - (routed | record))}"
    assert not (routed & record), f"重叠：{sorted(routed & record)}"
    assert part["covers_exactly"] is True
    assert set(out["unknown_id_sites"]) == unknown, "unknown_id_sites 与 unknown_ids 不同集"
    counts = out["counts"]
    assert counts["unknown_ids_routed"] + counts["unknown_ids_record_only"] == counts["unknown_ids"]
    assert counts["unknown_ids"] == counts["unknown_ids_offmanifest_raw"] - counts["unknown_ids_signature"]
    assert counts["unknown_ids_signature"] == len(EXPECTED_SIGNATURE_LABELS)


def test_derived_predicate_is_not_a_name_whitelist() -> None:
    """派生判据可复算：独立地在 Census 证据上重跑一遍纯落款判据，
    必须覆盖 authoring 的 5 枚（claimed ⊆ derived），而非读清单名字。"""
    module = _load_census_module()
    census = module.Census([])
    out = census.collect()
    derived = census._derived_signature_ids()  # 采集后 self 已含全部证据
    assert EXPECTED_SIGNATURE_LABELS <= set(derived), (
        f"authoring 5 枚里有派生不认的（清单与实况脱钩）："
        f"{sorted(EXPECTED_SIGNATURE_LABELS - set(derived))}")
    # 派生集合是纯落款超集（含未认领的 record_only），故它 >= 桶成员；桶只摘认领部分。
    assert set(out["signature_labels"]) == EXPECTED_SIGNATURE_LABELS & derived
