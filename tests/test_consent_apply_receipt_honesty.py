"""同意卡「批下即落地」回执的**诚实锁**（S-CONSENT-RECEIPT 席，2026-10-04）。

钉的是什么
----
台账 #63 现算过一次谎账：`consent_admin` 的回执照 `getattr(gate, "consume_apply_result", None)`
读门的结果话术，而门**从未定义**这个件 ⇒ 恒走 `_APPLY_RESULT_FALLBACK`，那句写的是
「没再听到别的话，就是已经按卡上批的落到位了」——而那一刻**一个参数都没被改动**。
本件不实现「批下回灌执行」（那是主人的裁定，不在本席范围），只把**回执**钉成事实：

1. **无证据即不声称落地**（A/B/E）：批准入账与「参数被改了」是两件事，回执只准说前者。
   判据不只看文案字符串，还与 `store.list_overrides()` 的**实况**对同一件事——
   文案说没落、盘面真没落，才算诚实。
2. **有证据必须报落地**（C/D）：门交出落地话术时，回执原文转述（禁第二真身）；
   门按变更流水现算时，流水里有 applied 行 ⇒ 报出键名与变更号。
3. **兜底句永不得回潮「已落到位」**（F）：源码级扫两枚件里所有**字符串面量**
   （排除 docstring），出现无条件落地口径即红——改常量、改语序、换文件都躲不过。
4. **回执腿零执行**（G）：`consume_apply_result` 结构上不许调
   `guarded_write/_apply_with_audit/apply/set_override/claim_consent/...`——
   否则「读结果」这条路会变成第二条偷偷写参数的门（台账 #56 K-1 绕咽喉同族）。
5. **每把锁都有牙**（H/I）：注毒只在内存里发生（源码字符串切片 / monkeypatch），
   零碰真树，还原后 sha256 必须与注毒前一致。

全离线：设置文件与同意账落 `tmp_path`，不碰 Runtime 真库、不碰运行时覆盖册、不 import NoneBot。
"""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    settings as settings_mod,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    build_instance_settings_manager,
)
from plugins.bot_unified_runtime.domains.core.safety_exec import settings_gate
from plugins.bot_unified_runtime.domains.core.safety_exec.consent import (
    CHANGE_APPLIED,
    CHANGE_FAILED,
    ChangeRecord,
    ConsentGrant,
    ConsentPolicy,
    Refusal,
    aware_now,
)
from plugins.bot_unified_runtime.domains.core.safety_exec.settings_gate import (
    RuntimeChangeNeedsConsent,
    SettingsWriteGate,
)
from plugins.bot_unified_runtime.domains.ops.capabilities import consent_admin

ROOT = Path(__file__).resolve().parents[1]
CONSENT_ADMIN_PY = (
    ROOT / "plugins/bot_unified_runtime/domains/ops/capabilities/consent_admin.py"
)
SETTINGS_GATE_PY = (
    ROOT / "plugins/bot_unified_runtime/domains/core/safety_exec/settings_gate.py"
)

SUPER_ROLES = [ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN]
ADMIN_ONLY_ROLES = [ROLE_USER, ROLE_ADMIN]

#: R2（书面同意档）且可热改——只有「既过分级、又过白名单」的键走得到完整裁决路径。
R2_KEY = "BOT_MEMORY_EXTRACT_ENABLED"
R2_VALUE = "false"
#: 卡上的申请人与来批的人故意两枚不同的号（同号先撞防自批，测不到后面的阶梯）。
REQUESTER = "qq:1722380002"
APPROVER_ID = "3865067623"

#: 谎账原文（2026-10-04 之前的 `_APPLY_RESULT_FALLBACK`）。只准出现在注毒切片里，
#: 准不准出现在产品话术里由 F 锁判——**这条锁判的就是它不许出现**。
OLD_LIE = (
    "这张卡按你批的记下了。落地结果以门回的那句为准——"
    "没再听到别的话，就是已经按卡上批的落到位了。"
)

#: 回执里一旦出现在册＝「声称已执行落地」。本波裁定：**没有落地证据就不许说**。
LANDING_CLAIM_MARKERS: tuple[str, ...] = (
    "落到位",
    "已落地",
    "已经落地",
    "落了地",
    "按卡上批的落",
    "批完我直接",
)
#: 无证据回执必须明说的两件事：没改参数 + 真落地要走哪一步。
MUST_SAY_NOT_APPLIED = "没有改动任何参数"
MUST_SAY_NEXT_STEP = "同一参数再说一次"
#: 兜底那条腿（连门的证据都读不到）的最低要求：不报喜，也不把「读不到」当结论。
NO_CLAIM_MARKER = "我不声称"
#: 批准确实入账了这一事实的口径（`test_consent_command_surface.py` 两枚锁按此子串判，
#: 改动本常量族时必须保住它，否则咬的是别人家的锁）。
BOOKED_MARKER = "按你批的记下了"

EXECUTION_FORBIDDEN_ATTRS = frozenset(
    {
        "guarded_write",
        "_apply_with_audit",
        "apply",
        "set_override",
        "reset_override",
        "claim_consent",
        "revoke_consent",
        "append_change",
        "update_change",
        "append_consent",
        "redeem_from_message",
        "apply_with_consent",
        "apply_approved",
        "_execute",
    }
)


# ---------------------------------------------------------------------------
# 夹具：真装配口 + 真门 + 真命令面（判据一律在门与账本体里，本件不重实现谓词）
# ---------------------------------------------------------------------------


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_runtime_settings_dir=str(tmp_path),
        bot_control_plane_config_db="",
        bot_safetyexec_enabled=True,
    )


def _message(
    text: str,
    *,
    sender_id: str = APPROVER_ID,
    roles: list[str] | None = None,
    session_type: SessionType = SessionType.PRIVATE,
    session_id: str = "private_3865067623",
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        sender_roles=list(roles if roles is not None else SUPER_ROLES),
        plain_text=text,
    )


def _gated_store(
    tmp_path: Path,
    *,
    clock: Any = lambda: datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc),
) -> tuple[settings_mod.RuntimeSettingsStore, SettingsWriteGate]:
    store = build_instance_settings_manager(_config(tmp_path)).get("default")
    gate = SettingsWriteGate(
        settings_store=store,
        config=_config(tmp_path),
        policy=ConsentPolicy(enabled=True, ttl_minutes=30, auto_r0_enabled=False),
        clock=clock,
    )
    store.attach_safety_gate(gate)
    return store, gate


def _issue_ticket(
    store: settings_mod.RuntimeSettingsStore, gate: SettingsWriteGate
):
    """签一张待批卡（走真咽喉，不手搓工单行）。"""
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    rows = [t.row for t in gate.pending_tickets() if t.row.target == R2_KEY]
    assert len(rows) == 1, f"期望恰好一张 {R2_KEY} 的卡，实际 {len(rows)} 张"
    return rows[0]


def _approve(store, gate, row) -> str:
    """真命令面跑一句批准，交回用户看到的那段正文（回执本体）。"""
    sentence = f"同意卡 批 {row.consent_id} {settings_gate.short_code_of(row)}"
    verdict = consent_admin.build_consent_admin_result(
        gate,
        _message(sentence),
        consent_admin.parse_consent_command(sentence) or {},
        request_id="req-receipt",
    )
    return verdict.body


class _GateWithoutGetter:
    """旧门形：**没有** `consume_apply_result`（`getattr` 交 None）⇒ 走兜底句那条腿。"""

    consume_apply_result = None  # 显式遮蔽委托，让 getattr 读到不可调用

    def __init__(self, inner: SettingsWriteGate) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _GateThatLanded:
    """合成门：模拟「门按卡回灌执行过、并交出结果话术」的形态（真门今天不执行）。"""

    def __init__(self, inner: SettingsWriteGate, note: str) -> None:
        self._inner = inner
        self._note = note

    def consume_apply_result(self, consent_id: object) -> str:
        return self._note

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _landing_claims(text: str) -> list[str]:
    return [marker for marker in LANDING_CLAIM_MARKERS if marker in text]


def _assert_receipt_is_honest(body: str, *, applied: bool) -> None:
    """回执的诚实判据（唯一一处，锁与注毒共用同一把尺）。"""
    claims = _landing_claims(body)
    assert BOOKED_MARKER in body, f"批准入账这件事没在回执里说清：{body[:120]}"
    if applied:
        assert claims, "门报了落地，回执却把落地吞了（用户会以为还要再催一遍）"
        return
    assert not claims, f"没有落地证据却声称落了地：{claims}｜回执={body[:160]}"
    assert MUST_SAY_NOT_APPLIED in body, f"没说出「参数未被改动」这个事实：{body[:160]}"
    assert MUST_SAY_NEXT_STEP in body, f"没交代真落地要走哪一步：{body[:160]}"


def _assert_receipt_claims_nothing(body: str) -> None:
    """兜底那条腿的判据：批准入账可以说，落没落**一个字都不许声称**。"""
    assert BOOKED_MARKER in body, f"批准入账这件事没在回执里说清：{body[:120]}"
    claims = _landing_claims(body)
    assert not claims, f"门什么都没回，回执却替它声称落了地：{claims}｜{body[:160]}"
    assert NO_CLAIM_MARKER in body, f"没把「我手里没有凭据」说出口：{body[:160]}"


def _module_string_literals(path: Path) -> list[str]:
    """一个 py 件里所有**产品话术**用的字符串面量（排除 module/class/function docstring）。

    排除 docstring 是刻意的：docstring 里可以引用旧谎话作为「这里曾经是谎」的登记，
    那是登记面；产品话术是出口面。两者不许混为一谈，也只有出口面受本锁约束。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                skipped.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skipped
    ]


# ---------------------------------------------------------------------------
# A/B/C/D/E：四种用户可见形态（(a) 批而未落 / (b) 批且落 / (c) 驳 / (d) 过期票）
# ---------------------------------------------------------------------------


def test_a_real_gate_approve_receipt_says_nothing_was_applied(tmp_path: Path) -> None:
    """(a) 批准入账、什么都没落 ⇒ 回执必须说「没有改动任何参数」，不许说落了。"""
    store, gate = _gated_store(tmp_path)
    row = _issue_ticket(store, gate)
    body = _approve(store, gate, row)
    _assert_receipt_is_honest(body, applied=False)
    # 文案与实况对同一件事：回执说没落，盘面必须真没落。
    assert store.list_overrides() == {}, "回执说不落地，咽喉却把值写下去了"


def test_b_receipt_falls_back_to_honest_wording_when_gate_has_no_getter(
    tmp_path: Path,
) -> None:
    """兜底那条腿（门没交出结果话术）同样不许承诺落地——谎账正是从这条腿出生的。"""
    store, gate = _gated_store(tmp_path)
    row = _issue_ticket(store, gate)
    body = _approve(store, _GateWithoutGetter(gate), row)
    _assert_receipt_claims_nothing(body)
    assert store.list_overrides() == {}


def test_c_receipt_reports_landing_when_the_gate_reports_it(tmp_path: Path) -> None:
    """(b) 门交出落地话术 ⇒ 命令面原文转述，且不得再挂「没有改动任何参数」。

    本例的门是合成件，只证明**转述腿**：门说落了就说落了，判据在门里（禁第二真身）。
    """
    store, gate = _gated_store(tmp_path)
    row = _issue_ticket(store, gate)
    note = (
        f"这张卡按你批的记下了：{R2_KEY} 已经按卡上批的落到位了，"
        "凭证一次有效、已核销。"
    )
    body = _approve(store, _GateThatLanded(gate, note), row)
    assert note in body, f"门给的落地话术被吃了：{body[:160]}"
    _assert_receipt_is_honest(body, applied=True)
    assert MUST_SAY_NOT_APPLIED not in body, "门报了落地，回执却又说没改参数（自相矛盾）"
    # 转述腿本身绝不动笔：合成门没执行任何东西 ⇒ 参数仍然没变。
    assert store.list_overrides() == {}


def test_d_gate_reports_landing_only_when_the_flow_records_it(tmp_path: Path) -> None:
    """真门的回执是**现算**的：流水里没有 applied 行 ⇒ 报未落；发起人同参重试落地后 ⇒ 报落。"""
    store, gate = _gated_store(tmp_path)
    row = _issue_ticket(store, gate)

    before = gate.consume_apply_result(row.consent_id)
    _assert_receipt_is_honest(before, applied=False)

    granted = gate.approve(
        row.consent_id,
        code=settings_gate.short_code_of(row),
        message=_message("同意卡 批 x y"),
    )
    assert isinstance(granted, ConsentGrant), granted
    pending_note = gate.consume_apply_result(row.consent_id)
    _assert_receipt_is_honest(pending_note, applied=False)
    assert store.list_overrides() == {}, "批准这一步把参数改了（行为翻转，未经裁定）"

    assert store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER) is False
    landed = gate.consume_apply_result(row.consent_id)
    assert R2_KEY in landed, f"落地回执没点名是哪枚键：{landed[:160]}"
    assert CHANGE_APPLIED in landed, f"流水里已有 applied 行却不报终态：{landed[:160]}"
    assert MUST_SAY_NOT_APPLIED not in landed, f"已经落了地仍报「没有改动任何参数」：{landed[:160]}"


def test_e_deny_and_expired_receipts_never_claim_landing(tmp_path: Path) -> None:
    """(c) 驳回 与 (d) 过期票：拒绝面也不许被读成「批过并落了」。"""
    store, gate = _gated_store(tmp_path)
    row = _issue_ticket(store, gate)
    denied = consent_admin.build_consent_admin_result(
        gate,
        _message(f"同意卡 驳 {row.consent_id} {settings_gate.short_code_of(row)}"),
        consent_admin.parse_consent_command(
            f"同意卡 驳 {row.consent_id} {settings_gate.short_code_of(row)}"
        )
        or {},
        request_id="req-deny",
    )
    assert _landing_claims(denied.body) == [], denied.body[:160]
    assert "按你批的记下了" not in denied.body, "驳回的回执却说批准记下了"
    assert store.list_overrides() == {}

    # (d) 过期：拿原句再批 ⇒ Refusal(EXPIRED)，同样一个字都不许沾落地。
    now = {"t": datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)}
    store2, gate2 = _gated_store(tmp_path / "expired", clock=lambda: now["t"])
    row2 = _issue_ticket(store2, gate2)
    now["t"] = row2.expires_at + timedelta(seconds=1)
    verdict = gate2.approve(
        row2.consent_id, code=settings_gate.short_code_of(row2), message=_message("同意卡 批 x y")
    )
    assert isinstance(verdict, Refusal) and verdict.kind.value == "expired", verdict
    assert _landing_claims(verdict.line()) == [], verdict.line()[:160]
    assert store2.list_overrides() == {}


# ---------------------------------------------------------------------------
# F/G：源码级与结构级锁（防回潮 / 防「读结果」变成第二道写门）
# ---------------------------------------------------------------------------


def test_f_no_receipt_wording_claims_landing_without_evidence() -> None:
    """兜底句与门的话术常量族里，**一枚无条件落地口径都不许存在**（台账 #63 的那句谎账）。"""
    offenders: list[str] = []
    for path in (CONSENT_ADMIN_PY, SETTINGS_GATE_PY):
        for literal in _module_string_literals(path):
            hits = _landing_claims(literal)
            if hits:
                offenders.append(f"{path.name}:{hits} ← {literal[:80]}")
    assert offenders == [], "回潮了「已落到位」式无条件落地口径：\n" + "\n".join(offenders)


def test_g_consume_apply_result_performs_no_execution() -> None:
    """回执腿零执行：方法体内不许出现任何写腿/消费腿调用（只读流水、只翻人话）。"""
    tree = ast.parse(SETTINGS_GATE_PY.read_text(encoding="utf-8"))
    cls = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "SettingsWriteGate"
    )
    method = next(
        (
            node
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "consume_apply_result"
        ),
        None,
    )
    assert method is not None, (
        "门没有 consume_apply_result —— 命令面就会退回兜底句；"
        "本波立过的锁不许这条腿再次变成空头支票"
    )
    hits = {
        call.func.attr
        for call in ast.walk(method)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }
    assert not (hits & EXECUTION_FORBIDDEN_ATTRS), (
        f"回执腿里出现了执行面：{sorted(hits & EXECUTION_FORBIDDEN_ATTRS)}——"
        "「读落地结果」不许变成第二条偷偷写参数的门"
    )


def test_h_settings_gate_exposes_the_receipt_hook_so_the_fallback_is_dead_code_in_production() -> None:
    """接线锁：真门必须交出结果话术 ⇒ 生产路径不再靠兜底句说话。"""
    assert callable(getattr(SettingsWriteGate, "consume_apply_result", None)), (
        "门没有 consume_apply_result：生产回显将恒走兜底句（台账 #63 谎账的成因形态）"
    )


# ---------------------------------------------------------------------------
# I/J：注毒自证（只在内存里发生，零碰真树）
# ---------------------------------------------------------------------------


def _assign_slice(path: Path, name: str) -> tuple[str, str]:
    """取模块级常量**在源码里 contiguous 的那一段**（隐式拼接的常量在 AST 里会被折成
    一枚 Constant，运行时字符串不是源文件的连续子串 ⇒ 注毒必须按赋值段来做，不能按值）。
    """
    src = path.read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            segment = ast.get_source_segment(src, node)
            assert segment, f"取不到 {name} 的源码切片"
            return src, segment
    raise AssertionError(f"{path.name} 里没有模块级常量 {name}")


def test_i_f_source_lock_bites_on_poisoned_source() -> None:
    """把谎账原文塞回话术常量（内存切片）⇒ F 锁的判据必须当场看见。"""
    src, segment = _assign_slice(CONSENT_ADMIN_PY, "_APPLY_RESULT_FALLBACK")
    digest_before = hashlib.sha256(src.encode("utf-8")).hexdigest()
    assert "落到位" not in segment, "现状常量里已经有无条件落地口径，先现算再动锁"
    poisoned_src = src.replace(segment, f'_APPLY_RESULT_FALLBACK = "{OLD_LIE}"', 1)
    assert poisoned_src != src, "毒打不进去＝赋值段形态变了，先现算再动锁"
    literals = [
        node.value
        for node in ast.walk(ast.parse(poisoned_src))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert any(_landing_claims(item) for item in literals), (
        "谎账原文进了源码字符串面量却判不出来＝F 锁是空跑"
    )
    assert digest_before == hashlib.sha256(
        CONSENT_ADMIN_PY.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest(), "注毒污染了真树"


def test_j_behavioral_lock_bites_when_the_lie_is_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """把兜底句换回谎账原文并摘掉门的钩子 ⇒ 行为锁必红（证明红来自这条判据）。"""
    store, gate = _gated_store(tmp_path)
    row = _issue_ticket(store, gate)
    original = consent_admin._APPLY_RESULT_FALLBACK
    monkeypatch.setattr(consent_admin, "_APPLY_RESULT_FALLBACK", OLD_LIE)
    try:
        body = _approve(store, _GateWithoutGetter(gate), row)
        with pytest.raises(AssertionError):
            _assert_receipt_claims_nothing(body)
        assert _landing_claims(body), "谎账没进回执＝这发锁不测回执本体，是空跑"
    finally:
        monkeypatch.undo()
    assert consent_admin._APPLY_RESULT_FALLBACK is original, "还原失败＝后面测的是毒不是代码"
    store2, gate2 = _gated_store(tmp_path / "restored")
    row2 = _issue_ticket(store2, gate2)
    _assert_receipt_claims_nothing(_approve(store2, _GateWithoutGetter(gate2), row2))


def test_k_failed_and_pending_flow_rows_are_reported_as_such(tmp_path: Path) -> None:
    """证据不齐时两头都不许声称：流水里只有 failed/pending 行的那张卡，回执不能报成功。"""
    store, gate = _gated_store(tmp_path)
    row = _issue_ticket(store, gate)
    granted = gate.approve(
        row.consent_id,
        code=settings_gate.short_code_of(row),
        message=_message("同意卡 批 x y"),
    )
    assert isinstance(granted, ConsentGrant), granted
    assert gate._ledger_store is not None
    stuck = ChangeRecord(
        change_id="deadbeefdeadbeef",
        target=R2_KEY,
        action_id="config.write",
        tier=row.tier,
        requester=REQUESTER,
        actor="test-fixture",
        state=CHANGE_FAILED,
        before_fingerprint="",
        after_fingerprint="",
        created_at=aware_now(None),
        consent_id=row.consent_id,
        reason="夹具：落地失败的一行",
    )
    gate._ledger_store.append_change(stuck)

    note = gate.consume_apply_result(row.consent_id)
    assert MUST_SAY_NOT_APPLIED in note or CHANGE_FAILED in note, (
        f"流水只有 failed 行，回执却没交代失败终态：{note[:200]}"
    )
    assert MUST_SAY_NEXT_STEP in note or CHANGE_FAILED in note
    assert _landing_claims(note) == [], f"failed 流水被报成了成功：{note[:200]}"
    assert store.list_overrides() == {}, "夹具流水把值写下去了（append_change 不该有副作用）"
