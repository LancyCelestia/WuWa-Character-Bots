"""QG9①：根装配现场必须把中央告警口接进出站闸的 `issue_sink`。

来源＝`logs/SEAT-ATK-QUEUE.md` Q-G9① ＋ `logs/SEAT-FIX-QG9.md` §6 遗留 1。
`4151c4f` 已让闸在 skip 分支 `note_issue`，但根 `build_outbound_gate(...)` 的实参只有
config / audit_logger / settings_provider / quiet_settings_provider 四枚——
`issue_sink` 从没被传过（根全文 `issue_sink` 今天只在 :3897 那条**自供状注释**里出现）。
⇒ 开闸后的 `KIND_SETTINGS_UNREADABLE / DEGRADED / STORM`、TTL 到期、skip
全部只剩审计与日志，**管理员通道永远哑**：这正是台账 #49★「未执法＝出站闸」的同族。

结构锁（装配面行为腿禁 import 根件，故只能锁形状）三腿：
 ① `build_outbound_gate(...)` 调用必带 `issue_sink=`，且值不是 `None` 字面量；
 ② 该值必须是**中央告警口**（根内唯一的共用推送函数 `_push_probe_issue`），
    不许手搓第二条直发腿（#49★ 教训）；
 ③ 摘掉 keyword 的内存副本必判红（证明锁会咬）。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"
CENTRAL_ALARM_PORT = "_push_probe_issue"


def _root_text() -> str:
    return ROOT_INIT.read_text(encoding="utf-8-sig")


def _gate_call(text: str) -> ast.Call | None:
    for node in ast.walk(ast.parse(text)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_outbound_gate"
        ):
            return node
    return None


def _issue_sink_keyword(text: str) -> ast.keyword | None:
    call = _gate_call(text)
    assert call is not None, "根文件里找不到 build_outbound_gate 调用＝坐标已漂"
    for kw in call.keywords:
        if kw.arg == "issue_sink":
            return kw
    return None


def test_gate_is_wired_to_an_issue_sink() -> None:
    kw = _issue_sink_keyword(_root_text())
    assert kw is not None, (
        "build_outbound_gate 没接 issue_sink＝闸的告警腿哑（QG9①）"
    )
    assert not (isinstance(kw.value, ast.Constant) and kw.value.value is None), (
        "issue_sink 显式给了 None＝等于没接"
    )


def test_issue_sink_reuses_the_central_alarm_port() -> None:
    """禁手搓第二条直发腿：sink 必须落在根内共用的那一个告警口上。"""
    kw = _issue_sink_keyword(_root_text())
    assert kw is not None, "sink 根本没接，谈不上复用中央口"
    names = {
        node.id for node in ast.walk(kw.value) if isinstance(node, ast.Name)
    }
    attrs = {
        node.attr for node in ast.walk(kw.value) if isinstance(node, ast.Attribute)
    }
    assert CENTRAL_ALARM_PORT in names or CENTRAL_ALARM_PORT in attrs, (
        f"issue_sink 没复用中央告警口 {CENTRAL_ALARM_PORT}＝另开直发腿（#49★ 同族教训）"
    )


def test_lock_bites_when_keyword_removed(tmp_path: Path) -> None:
    text = _root_text()
    call = _gate_call(text)
    assert call is not None
    if _issue_sink_keyword(text) is None:
        # 门还没落：此刻锁本就红，注毒腿退化为"缺失可被认出"的自证。
        assert _issue_sink_keyword(text) is None
        return
    body = ast.get_source_segment(text, call) or ""
    poisoned = text.replace(body, body.replace("issue_sink=", "issue_sink_REMOVED="), 1)
    assert poisoned != text, "注毒未落到真身文本＝空跑"
    copy = tmp_path / "root_poisoned.py"
    copy.write_text(poisoned, encoding="utf-8")
    assert _issue_sink_keyword(copy.read_text(encoding="utf-8-sig")) is None, (
        "摘掉 keyword 后锁仍认得出＝量具在空跑"
    )
