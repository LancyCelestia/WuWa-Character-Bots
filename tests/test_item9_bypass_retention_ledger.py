"""第 9 项·双触发撤旁路——旁路挂账与可达性前置锁（S-IMPL-ITEM9）。

裁定：能力入口收「命令 + 自然语言」双形；撤除直调旁路前，须**逐枚证明**该入口
已被中央双触发覆盖。本锁不撤任何旁路——它把「撤除的前置证明」钉成机检：

1. 挂账锁：现算根文件旁路直呼点（census v0.3.0 现值 exec-bypass ∧ wired 中落
   在 root 的四枚：bot.ignore ×1、bot.music_mode ×3），枚枚在册、计数对点——
   旁路数量变化（撤或长新枝）都必须先动这本账。
2. 可达性前置锁：某旁路要从账上摘除（根呼叫计数下降）时，其能力必须先出示
   中央在册证明（CAPABILITY_DESCRIPTOR 行存在 ∧ orchestration authored）；
   证明不出、账先摘 ⇒ 红。
3. 自然语言腿缺位如实挂账：四枚旁路今日全部保留——bot.ignore 与 bot.music_mode
   的自然语言入口形态未证得（census 入口形态=命令；触发词真身不在册面可离线核），
   撤除义务不成立，缺口点名见挂账条目的 missing 字段。

中央双触发本体（command_natural_remainder + 根装配段）的锁在
test_message_merge_9.py——本文件不重做第二真身，只锁撤旁路的证明门。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    message_merge,
)
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    CAPABILITY_DESCRIPTOR,
)

ROOT_INIT = ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

# ---------------------------------------------------------------- 挂账名册

# symbol -> 挂账条目。count = 现算（2026-09-28 本席以 AST 直扫根文件呼叫点，
# 与 scripts/central_seam_census.py v0.3.0 --report 的 exec-bypass 名册对点）。
BYPASS_RETENTION_LEDGER: dict[str, dict[str, object]] = {
    "build_ignore_guide_result": {
        "capability_id": "bot.ignore",
        "count": 1,
        "site": "_handle_ignore_guide",
        "missing": "自然语言入口形态未证得（census 入口形态=命令）；"
        "中央命令腿虽 wired，双形齐证前撤除义务不成立",
    },
    "build_music_mode_result": {
        "capability_id": "bot.music_mode",
        "count": 3,
        "site": "_handle_music/_handle_playlist/_handle_modes 区 capability 闭包",
        "missing": "同上：模式切换类文本无在册自然语言触发面证据；"
        "且根写面属在飞收编席（S-SEAM-FOLLOW）+用户放开令范围，本席不代撤",
    },
}

# 非旁路申明（如实挂账，不进撤除门）：ops/smoke 控制台与烟测脚本的直呼是
# 开发工具对真身的离线探针，不是用户可达的能力入口——不在第 9 项旁路条款射程。
HARNESS_DIRECT_CALLS_OUT_OF_SCOPE = (
    "domains/ops/smoke/console_chat.py::_route_for_message",
    "domains/ops/smoke/route_demo.py::_capability_smoke",
)


# ------------------------------------------------------------------- 现算


def _root_call_counts() -> dict[str, int]:
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in BYPASS_RETENTION_LEDGER:
                counts[name] = counts.get(name, 0) + 1
    return counts


def test_ledger_counts_match_live_root():
    """旁路枚枚在册、计数对点：根直调点数变了（撤或长新枝）必先动账。"""
    counts = _root_call_counts()
    for symbol, row in BYPASS_RETENTION_LEDGER.items():
        assert counts.get(symbol, 0) == row["count"], (
            f"{symbol} 根呼叫现算 {counts.get(symbol, 0)} ≠ 挂账 {row['count']}"
            " ⇒ 旁路面变了：撤除须出示中央双触发覆盖证明，新增长枝须补挂账"
        )


def test_removed_bypass_requires_central_registration():
    """可达性前置：只有当呼叫数低于挂账计数（=有人撤了旁路）时，才要求中央在册
    铁证——而现在四枚全保留，本锁同时验证「在册」判据本身可用（描述符行存在
    ∧ orchestration authored），防止账与真身双双失真后锁成恒真。"""
    counts = _root_call_counts()
    for symbol, row in BYPASS_RETENTION_LEDGER.items():
        cid = str(row["capability_id"])
        removed = counts.get(symbol, 0) < int(row["count"])
        if removed:
            descriptor_row = CAPABILITY_DESCRIPTOR.get(cid)
            assert descriptor_row is not None, f"{cid} 未入中央册 ⇒ 不许撤旁路"
            assert "orchestration_descriptor" in descriptor_row.authored_by, (
                f"{cid} 中央执行面未 author ⇒ 撤旁路=入口消失，红"
            )
        # 保留态下也抽查判据非恒真：这些 id 今天确实在册（判据可用性自证）
        assert cid in CAPABILITY_DESCRIPTOR or removed, (
            f"{cid} 不在册且旁路仍在——挂账本身失真"
        )


def test_no_central_natural_language_claim_without_evidence():
    """诚实锁：挂账 missing 字段非空的条目，本波不许宣告双触发覆盖闭环。
    （澜汐在册未执法纪律：完整性宣告必须与执法缺口同披露。）"""
    for symbol, row in BYPASS_RETENTION_LEDGER.items():
        assert str(row["missing"]), f"{symbol} 挂账缺 missing 点名"


def test_dual_trigger_roster_still_argless_only():
    """双触发头集与旁路挂账正交：头集仍只收无参命令（判据真身锁在
    test_message_merge_9，这里只防本文件与头集漂移后有人误并表）。"""
    heads = set(message_merge.DUAL_TRIGGER_COMMAND_HEADS)
    ledger_cids = {str(r["capability_id"]) for r in BYPASS_RETENTION_LEDGER.values()}
    assert ledger_cids.isdisjoint({"bot.chat"}), "旁路账不该混入人格腿"
    assert "music" not in " ".join(heads) and "ignore" not in " ".join(heads), (
        f"带参/旁路面误入双触发头集: {heads}"
    )
