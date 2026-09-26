"""请求级预算的相位记账（需求 6「报错在哪」的直接前置件）。

2026-09-26 从生产诊断库现算出的三条事实，件件都是本文件的用例：

1. 一轮 ``latency_ms=802560``（820 秒），全部已记相位加起来 3.3 秒
   （``phase_llm_ms:3284``），``phase_total_ms:0`` ——**800 秒花在哪一段，账面上
   结构性看不见**。根因：全仓只对 ``vision`` / ``vision_video`` / ``video_brief``
   / ``asr`` / ``llm`` 五段记账，而上下文/检索段与工具段只被预算"拦"、从不被
   "记"（``ensure_available(stage="tools")`` 存在，对应 ``record_phase`` 不存在）。
2. ``phase_total_ms`` 是派生量，早快照只加了当时已归账的相位；沿用固定相位那套
   "同名以已贴过为准"去重，会把合计**永久钉死在 0**，与后到的 ``phase_llm_ms``
   自相矛盾地挂在同一条回执上。
3. 记账补齐后，``deadline_exceeded:before_llm`` 这类回执必须能点名"到期那一刻
   哪一段正跑到一半"（``mark_in_flight``）而不是留空。

全部离线：不联网、不起进程、不读生产库。
"""

from __future__ import annotations

import ast
import inspect
import time
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.runtime import deadline as dl

CHAT_SOURCE = Path(inspect.getfile(chat))


# ---------------------------------------------------------------------------
# ① 相位记账本身
# ---------------------------------------------------------------------------


def test_record_phase_accumulates_and_phase_tags_reports_total() -> None:
    budget = dl.DeadlineBudget(300.0)
    started = time.monotonic() - 0.05
    budget.record_phase("context", started)
    tags = dl.phase_tags(budget)
    assert any(tag.startswith("phase_context_ms:") for tag in tags)
    total = [tag for tag in tags if tag.startswith("phase_total_ms:")]
    assert len(total) == 1
    # 合计必须等于各相位之和（±1ms 取整余量）——派生量不许自创口径。
    parts = sum(
        float(tag.split(":", 1)[1])
        for tag in tags
        if tag != total[0] and tag.startswith("phase_")
    )
    assert abs(float(total[0].split(":", 1)[1]) - parts) <= 1.0


def test_illegal_phase_names_never_reach_tags() -> None:
    """相位名是诊断标签的**唯一**用户内容防线：脏名（含冒号/换行/正文）必须
    在记账与落盘两处都被拒，否则一条回执能被污染成任意文本。"""
    budget = dl.DeadlineBudget(300.0)
    now = time.monotonic()
    budget.record_phase("恶意正文:含冒号\n第二行", now - 1.0)
    budget.record_phase("", now - 1.0)
    tags = dl.phase_tags(budget)
    assert tags == [], f"非法相位名漏进诊断标签：{tags}"


def test_mark_in_flight_is_cleared_when_the_phase_is_recorded() -> None:
    budget = dl.DeadlineBudget(300.0)
    budget.mark_in_flight("context")
    assert budget.in_flight_stage == "context"
    budget.record_phase("context", time.monotonic())
    assert budget.in_flight_stage == "", "归账后仍留在飞=下一段会被冒名顶替"


def test_illegal_in_flight_name_never_overwrites_a_valid_one() -> None:
    """卫生优先于记账：脏标注被丢弃时**不得**清掉已有的合法标注。"""
    budget = dl.DeadlineBudget(300.0)
    budget.mark_in_flight("tools")
    budget.mark_in_flight("正文;rm -rf")
    assert budget.in_flight_stage == "tools"


# ---------------------------------------------------------------------------
# ② 派生量的合并方向（本波真修的自相矛盾账）
# ---------------------------------------------------------------------------


def test_stale_total_is_superseded_by_the_late_snapshot() -> None:
    """生产形态复现：早快照贴了 ``phase_total_ms:0``，晚快照带来 ``phase_llm_ms``
    与真合计 ⇒ 合并后合计只能有一枚，且必须是晚到的那一枚。"""
    posted = ["prompt_messages:8", "phase_video_brief_ms:0", "phase_total_ms:0"]
    late = ["phase_llm_ms:3284", "phase_total_ms:3284"]
    kept, added = dl.merge_phase_tags(posted, late)
    totals = [t for t in [*kept, *added] if str(t).startswith("phase_total_ms:")]
    assert totals == ["phase_total_ms:3284"], totals
    assert kept.count("phase_video_brief_ms:0") == 1
    assert "prompt_messages:8" in kept


def test_fixed_phases_are_still_deduped_by_posted_wins() -> None:
    """反向：固定相位**不**许被晚快照覆盖成两枚（同名以已贴为准）。"""
    posted = ["phase_vision_ms:120"]
    late = ["phase_vision_ms:120", "phase_llm_ms:50"]
    kept, added = dl.merge_phase_tags(posted, late)
    assert kept == ["phase_vision_ms:120"]
    assert added == ["phase_llm_ms:50"]


def test_merge_is_a_no_op_when_the_late_snapshot_carries_no_total() -> None:
    posted = ["phase_total_ms:10", "phase_llm_ms:10"]
    kept, added = dl.merge_phase_tags(posted, ["phase_context_ms:3"])
    assert kept == posted  # 晚快照没有合计 ⇒ 一枚都不该被摘掉
    assert added == ["phase_context_ms:3"]


# ---------------------------------------------------------------------------
# ③ 装配活性：有"拦"就必须有"记"（不许再出现只 gate 不记账的段）
# ---------------------------------------------------------------------------


def _budget_call_stages(source: str, fname: str) -> set[str]:
    """抓 ``request_budget.<fname>(...)`` 的相位名字面量。

    位置参数与 ``stage=`` 关键字**都要收**：第一版写了 ``if not node.args: continue``，
    于是 ``ensure_available(stage="llm")`` 这种纯关键字调用全被跳过 ⇒ "有拦必须有记"
    那条锁拿到的是空集，恒绿、零执法（是注毒用例把它抓出来的）。
    """
    tree = ast.parse(source)
    stages: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != fname:
            continue
        candidates: list[ast.expr] = list(node.args[:1])
        candidates += [
            kw.value for kw in node.keywords if isinstance(kw, ast.keyword) and kw.arg == "stage"
        ]
        for candidate in candidates:
            if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
                stages.add(candidate.value)
    return stages


def test_every_gated_stage_is_also_recorded_in_chat() -> None:
    """``ensure_available(stage=X)`` 的每个 X 都必须有 ``record_phase(X, ...)``。

    这是本用例的全部意义：09-26 那轮 ``tools`` 段就是"会拦不会记"，于是
    预算因它耗尽、回执却答不出它跑了多久。判据从"我记得哪几段没记"
    升级为"两集合做差"，以后谁再加一道 gate 忘记记账，当场红。
    """
    source = CHAT_SOURCE.read_text(encoding="utf-8")
    gated = _budget_call_stages(source, "ensure_available")
    recorded = _budget_call_stages(source, "record_phase")
    # 自证判据不空转：gated 拿不到任何名字，这条锁就是恒绿的假锁（本用例第一版
    # 就是这个形态——纯关键字调用被提取器跳过了）。
    assert gated, "提取器没抓到任何被预算拦截的相位＝锁不执法"
    assert {"llm", "tools"} <= gated, f"已知会被拦截的相位从 gated 里消失了：{sorted(gated)}"
    missing = sorted(gated - recorded)
    assert not missing, f"这些段会被预算拦截却从不记账：{missing}"


def test_context_phase_is_recorded_on_both_exit_paths() -> None:
    """上下文段的异常出口（早 return）也必须归账，否则"检索挂了"这一类
    恰好是唯一不留账的那种。"""
    source = CHAT_SOURCE.read_text(encoding="utf-8")
    assert source.count('record_phase("context"') >= 2
    assert 'mark_in_flight("context")' in source


def test_tools_phase_is_instrumented_in_chat() -> None:
    source = CHAT_SOURCE.read_text(encoding="utf-8")
    assert 'record_phase("tools"' in source
    assert 'mark_in_flight("tools")' in source


def test_late_merge_is_wired_at_the_production_call_site() -> None:
    """记账规则住在 deadline.merge_phase_tags，调用点只许用它——
    第二处手写去重＝第二真身（本仓反复栽过的形态）。

    数调用点走 AST 而不是数子串：第一版写 ``count("merge_phase_tags(") == 2``
    把 import 行（``merge_phase_tags,`` 不带括号）算进去了，当场自己红。
    """
    source = CHAT_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "merge_phase_tags"
    ]
    assert len(calls) == 1, f"合并口径应在唯一调用点，实际 {len(calls)} 处"
    imported = any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "merge_phase_tags" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert imported, "调用点没走真身（本地重写或漏 import）"
    # 调用点不得再自己筛 phase_total_ms（判据归真身）。
    assert 'startswith("phase_total_ms:")' not in source


def test_gate_without_accounting_would_actually_be_caught() -> None:
    """杀伤力自证：把 ``tools`` 的归账抹掉，"有拦必须有记"那枚锁必须变红。

    不这么写的话，判据可以只是恰好绿（本仓反复栽过的"存在性当活性"）。
    在内存里做，不碰真文件。
    """
    source = CHAT_SOURCE.read_text(encoding="utf-8")
    assert 'record_phase("tools", tools_started)' in source
    # 抹法要仍可编译：直接换成 pass 会留下 `request_budget.pass` 这种语法残骸，
    # 判据会以 SyntaxError 而不是"抓到缺账"的形式失败——那是假杀伤力。
    mutated = source.replace(
        'record_phase("tools", tools_started)',
        'mark("tools", tools_started)',
    )
    gated = _budget_call_stages(mutated, "ensure_available")
    recorded = _budget_call_stages(mutated, "record_phase")
    assert "tools" in gated - recorded, "注毒没打中判据＝这枚锁本来就不执法"


@pytest.mark.parametrize("stage", ["context", "tools", "llm", "vision", "asr"])
def test_phase_tags_emits_each_expected_stage_tag(stage: str) -> None:
    budget = dl.DeadlineBudget(120.0)
    budget.record_phase(stage, time.monotonic() - 0.2)
    assert f"phase_{stage}_ms" in " ".join(dl.phase_tags(budget))
