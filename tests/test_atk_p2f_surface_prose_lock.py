"""P2-f 攻击面登记册「人话滞后于真身」补丁预备席回归锁（S-PATCH-ATK-P2F-RERUN，2026-09-28）。

钉的是 ANTIATTACK-BRAIN 残票 **P2-f**：`attack_surface.py` 登记表**条目体散文**与
**真身行为**口径打架——头注指针早已改账，条目体 `current_defender` 还停在旧叙述：

- AS-INDUCE-OPS-TAKEOVER / AS-AUTHORITY-REWRITE（均 GAP）：`current_defender` 仍把
  本席两条**话术信号谓词**写成「无人挡」，可头注（2026-09-26 S-ATTACK-CONSUMERS）与
  `tests/test_attack_surface_consumers.py` 锁①-④ 实证它们已由
  `injection.check_prompt_injection`（每条真人消息真跑）消费为信号腿；
- AS-QUOTE-CHAIN-INJECTION（DEFENDED）：`current_defender` 仍指「injection 自带
  `_INTERNAL_MARKER_PATTERN` 窄版第二真身、两处并非同一份」，可 S-MARKER-UNIFY-b
  已把内部标记消毒正则单源化到 `message_context.INTERNAL_MARKER_PATTERN` 本体。

判据一律走**正向在场**（要求条目体点名真身符号），不吃「旧措辞缺席」这种反判——
因为收口后的散文会以引号复述旧说法，反判会把正确的改写也误报。这样：
- 干净 HEAD（未叠补丁）：三条真锁腿必 FAILED（旧散文没点名 check_prompt_injection /
  S-MARKER-UNIFY-b），即「补丁待审」的可复跑标志；
- 叠 `P2F-attack_surface.patch.md` 后：三条转绿。

另有两枚**代码接地锁**（HEAD 即绿）把「散文必须跟着真身走」钉死在事实上：
① 两条信号谓词确在 `check_prompt_injection` 真跑；② 内部标记正则真单源。
最后一枚注毒自证证明判据对旧散文真会报命中，不是永假条件。

本席只出补丁，未直写生产文件（`attack_surface.py` 在飞 240/27）。
"""

from __future__ import annotations

import ast
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.ingest.message_context import (
    INTERNAL_MARKER_PATTERN,
)
from plugins.bot_unified_runtime.domains.chat_reply.security import injection
from plugins.bot_unified_runtime.domains.core.safety_exec.attack_surface import (
    SurfaceEntry,
    register_by_id,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_INJECTION_PATH = (
    REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "security"
    / "injection.py"
)


def _injection_source() -> str:
    return _INJECTION_PATH.read_text(encoding="utf-8")


def _call_names_in(tree: ast.Module, func_name: str) -> set[str]:
    """某顶层函数体里的调用名（Attribute/Name 两形态，同消费锁口径）。"""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            names: set[str] = set()
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    fn = call.func
                    if isinstance(fn, ast.Attribute):
                        names.add(fn.attr)
                    elif isinstance(fn, ast.Name):
                        names.add(fn.id)
            return names
    return set()


# ---------------------------------------------------------------------------
# 代码接地锁（真身事实；散文必须与之一致；HEAD 即绿）
# ---------------------------------------------------------------------------


def test_both_signal_predicates_are_live_consumers_in_production_gate() -> None:
    """detect_operational_takeover / detect_authority_rewrite 确在门里真调——
    「信号腿已真跑」不是散文自述，是 AST 现算，故登记表不许再写「无人挡」。"""
    tree = ast.parse(_injection_source())
    scan_calls = _call_names_in(tree, "_attack_surface_signal_scan")
    assert {"detect_operational_takeover", "detect_authority_rewrite"} <= scan_calls, (
        f"信号腿不再真调谓词（实算 {sorted(scan_calls)}）：消费被拆，须同步把登记表改回「无人挡」"
    )
    gate_calls = _call_names_in(tree, "check_prompt_injection")
    assert "_attack_surface_signal_scan" in gate_calls, (
        "check_prompt_injection 不再消费信号扫描：门被旁路，登记表「已真跑」的改账前提不成立"
    )


def test_internal_marker_regex_is_single_sourced() -> None:
    """内部标记消毒正则真身唯一：injection 不再持有本地窄版 `_INTERNAL_MARKER_PATTERN`，
    与采集侧共用同一枚 `message_context.INTERNAL_MARKER_PATTERN` 本体。
    故 AS-QUOTE-CHAIN 条目体「两处并非同一份」的说法过期。"""
    assert not hasattr(injection, "_INTERNAL_MARKER_PATTERN"), (
        "injection 又长出本地窄版正则（S-MARKER-UNIFY-b 单源化回潮）：登记表改账前提不成立"
    )
    assert getattr(injection, "INTERNAL_MARKER_PATTERN", None) is INTERNAL_MARKER_PATTERN, (
        "injection 引用的不是 message_context 的标记正则本体：第二真身复活"
    )


# ---------------------------------------------------------------------------
# 条目体散文判据（正向在场；纯函数可喂注毒 entry）
# ---------------------------------------------------------------------------


def _ops_takeover_prose_violations(entry: SurfaceEntry) -> list[str]:
    cd = entry.current_defender
    bad: list[str] = []
    if "detect_operational_takeover" not in cd:
        bad.append("current_defender 未点名本席信号谓词 detect_operational_takeover")
    if "check_prompt_injection" not in cd:
        bad.append("current_defender 未点名真身消费者 check_prompt_injection（信号腿已真跑）")
    if "无人挡" in cd or "无机器防线" in cd:
        bad.append("current_defender 仍写「无人挡/无机器防线」，与消费锁①-④矛盾")
    return bad


def _authority_rewrite_prose_violations(entry: SurfaceEntry) -> list[str]:
    cd = entry.current_defender
    bad: list[str] = []
    if "detect_authority_rewrite" not in cd:
        bad.append("current_defender 未点名本席信号谓词 detect_authority_rewrite")
    if "check_prompt_injection" not in cd:
        bad.append("current_defender 未点名真身消费者 check_prompt_injection（信号腿已真跑）")
    return bad


def _quote_chain_prose_violations(entry: SurfaceEntry) -> list[str]:
    cd = entry.current_defender
    bad: list[str] = []
    if "S-MARKER-UNIFY-b" not in cd:
        bad.append("current_defender 未记 S-MARKER-UNIFY-b 单源化收口（仍停在旧「第二真身」账）")
    if "单源" not in cd:
        bad.append("current_defender 未点明标记正则已单源（旧「两处并非同一份/窄版」应作废）")
    return bad


# ---------------------------------------------------------------------------
# 真锁：登记册条目体现算应干净（HEAD 红 / 叠补丁绿）
# ---------------------------------------------------------------------------


def test_as_induce_ops_takeover_prose_matches_live_signal_leg() -> None:
    entry = register_by_id("AS-INDUCE-OPS-TAKEOVER")
    assert _ops_takeover_prose_violations(entry) == [], _ops_takeover_prose_violations(entry)


def test_as_authority_rewrite_prose_matches_live_signal_leg() -> None:
    entry = register_by_id("AS-AUTHORITY-REWRITE")
    assert _authority_rewrite_prose_violations(entry) == [], _authority_rewrite_prose_violations(entry)


def test_as_quote_chain_prose_no_stale_second_source_claim() -> None:
    entry = register_by_id("AS-QUOTE-CHAIN-INJECTION")
    assert _quote_chain_prose_violations(entry) == [], _quote_chain_prose_violations(entry)


# ---------------------------------------------------------------------------
# 注毒自证：判据对「旧散文形态」真会点名，不是永假条件（只在内存构造，不落盘）
# ---------------------------------------------------------------------------


def test_prose_locks_bite_on_the_stale_headword_form() -> None:
    """把 HEAD 旧 current_defender 逐字灌进来，三把判据必须各自当场报命中。"""
    stale_ops = SurfaceEntry(
        surface_id="AS-POISON-OPS",
        title="注毒：复刻旧「无人挡」",
        state=register_by_id("AS-INDUCE-OPS-TAKEOVER").state,
        channels=register_by_id("AS-INDUCE-OPS-TAKEOVER").channels,
        current_defender=(
            "无人挡（旧 injection 无 restart/kill/git 三类判据；仅靠 AGENTS 对 LLM 席位的纪律，"
            "对 bot 自身回复路径无机器防线）"
        ),
        failure_mode="—",
        minimal_landing="—",
        predicate_id="detect_operational_takeover",
    )
    assert _ops_takeover_prose_violations(stale_ops), "旧「无人挡」散文竟未被判据点名——锁空跑"

    stale_auth = SurfaceEntry(
        surface_id="AS-POISON-AUTH",
        title="注毒：复刻旧只述 role_escalation 缺口",
        state=register_by_id("AS-AUTHORITY-REWRITE").state,
        channels=register_by_id("AS-AUTHORITY-REWRITE").channels,
        current_defender=(
            "真角色只由 sender_id→roles 派生，但旧 injection 的 role_escalation 只认"
            "「你现在是管理员」，不认「改人的权限归属」"
        ),
        failure_mode="—",
        minimal_landing="—",
        predicate_id="detect_authority_rewrite",
    )
    assert _authority_rewrite_prose_violations(stale_auth), "旧冒认散文竟未被点名——锁空跑"

    stale_quote = SurfaceEntry(
        surface_id="AS-POISON-QUOTE",
        title="注毒：复刻旧「第二真身窄版」",
        state=register_by_id("AS-QUOTE-CHAIN-INJECTION").state,
        channels=register_by_id("AS-QUOTE-CHAIN-INJECTION").channels,
        current_defender=(
            "⚠ 两处正则并非同一份——injection 窄版不认「层级N+发送者名」尾巴（另案在册）"
        ),
        failure_mode="—",
        minimal_landing="—",
    )
    assert _quote_chain_prose_violations(stale_quote), "旧窄版第二真身散文竟未被点名——锁空跑"
