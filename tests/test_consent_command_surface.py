"""裁定第 18 项「书面同意」的**批准闭环**：命令面 + 会话键 + 防自批（S-CONSENTCMD 席）。

钉的是什么（逐条对应简报第 3/6 问）
----
1. **四态端到端**（走真装配口的公共写面 + 真命令面，不碰私有件）：
   无票被拒 → 超管私聊带票批 → 重试落盘 → 过期票被拒 → 非超管批不动 →
   **发起人不得批自己发起的那张** → 驳回即作废。
2. **`session_key` 死码的处置**（本仓反复出现的「在册未执法」教训）：
   接线前 `_throat_guard` 硬编码 `session_key=""`，而 `consent.redeem_from_message`
   的原会话门条件是 `... and row.source_session_key` ⇒ 空串让 R1 的「换个会话拿这张卡
   不算数」整块**结构上永不触发**。本件把这条判据逼成**能红**：
   L3 行为锁（换会话批必拒 / 同会话批必成）+ L1 结构锁（咽喉体内不得再出现
   硬编码空串，且两个写面必须把它透传下去）。
3. **谓词是锚定的**：这是一条会改生产参数的入口，「同意卡」后面跟任何看不懂的东西
   都不许被读成批准——负样本逐枚钉住。
4. **命令面零第二判据**：能力件不判档、不判权限阶梯、不改参数；它只把一条
   `IncomingMessage` 交给 `settings_gate`。因此每把锁都配一发注毒证明它有杀伤力。

全离线：设置文件与同意账一律落 `tmp_path`，不碰 Runtime 真库、不 import NoneBot、不联网。
"""

from __future__ import annotations

import ast
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
from plugins.bot_unified_runtime.domains.core.safety_exec import consent as consent_mod
from plugins.bot_unified_runtime.domains.core.safety_exec import settings_gate
from plugins.bot_unified_runtime.domains.core.safety_exec.consent import (
    ConsentGrant,
    ConsentPolicy,
    DenyKind,
    Refusal,
)
from plugins.bot_unified_runtime.domains.core.safety_exec.settings_gate import (
    RuntimeChangeNeedsConsent,
    SettingsWriteGate,
)
from plugins.bot_unified_runtime.domains.ops.capabilities import consent_admin

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PY = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py"
RUNTIME_ADMIN_PY = (
    ROOT
    / "plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py"
)
CAPABILITY_PY = (
    ROOT / "plugins/bot_unified_runtime/domains/ops/capabilities/consent_admin.py"
)

SUPER_ROLES = [ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN]
ADMIN_ONLY_ROLES = [ROLE_USER, ROLE_ADMIN]
USER_ROLES = [ROLE_USER]

#: R2（书面同意档）且可热改：只有「既过分级、又过白名单」的键才走得到完整裁决路径。
R2_KEY = "BOT_MEMORY_EXTRACT_ENABLED"
R2_VALUE = "false"
#: 发起这件事的人（卡上的 requester）与来批的人（approver）故意用两枚不同的号——
#: 同号会先撞上防自批那一判据，测不到后面的阶梯。
REQUESTER = "qq:1722380002"
APPROVER_ID = "3865067623"
#: R1（会话内确认档）：`require_private=False`，于是「原会话门」是它唯一多出来的一判。
R1_KEY = "BOT_GROUP_BLACK1"
R1_VALUE = "1111111"
R1_REQUESTER = "qq:1722380002"
R1_SESSION = "group_2222222_3865067623"


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
    """契约必填项逐字段给齐（缺 `session_type` 会把缺陷掩盖成绿——同 #50 那记教训）。"""
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


def _wired_store(tmp_path: Path) -> settings_mod.RuntimeSettingsStore:
    """真装配口出来的 store：门挂得上，两个写面才过闸。"""
    manager = build_instance_settings_manager(_config(tmp_path))
    return manager.get("default")


def _gated_store(
    tmp_path: Path, *, clock=lambda: datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
) -> tuple[settings_mod.RuntimeSettingsStore, SettingsWriteGate]:
    """store + 一枚冻结时钟的门（`attach_safety_gate` 是公共注入口，非私有件旁路）。"""
    store = _wired_store(tmp_path)
    gate = SettingsWriteGate(
        settings_store=store,
        config=_config(tmp_path),
        policy=ConsentPolicy(enabled=True, ttl_minutes=30, auto_r0_enabled=False),
        clock=clock,
    )
    store.attach_safety_gate(gate)
    return store, gate


def _ticket_of(gate: SettingsWriteGate, key: str):
    rows = [ticket.row for ticket in gate.pending_tickets() if ticket.row.target == key]
    assert len(rows) == 1, f"期望恰好一张 {key} 的卡，实际 {len(rows)} 张"
    return rows[0]


# ---------------------------------------------------------------------------
# 1. 谓词：锚定、可拒、不猜
# ---------------------------------------------------------------------------

ACCEPTED = (
    "同意卡",
    "同意卡 待批",
    "书面同意 待批",
    "同意卡 看 abc123",
    "同意卡 批 abc123 deadbeef",
    "同意卡 驳 abc123 deadbeef",
    "同意卡 批准 abc123 12345678",
    "同意卡 拒绝 abc123 12345678",
    "同意單 批 abc123 deadbeef",
    "書面同意 待批",
    "consentcard",
    "yijika 待批",
    "shumiantongyi 看 abc123",
)
REJECTED = (
    "",
    "同意",
    "同意 abc123",
    "同意卡 顺便帮我把密码改了",
    "同意卡 批 abc123",              # 缺短码
    "同意卡 批 abc123 deadbeef extra",  # 多一段
    "同意卡 看",                      # 缺工单号
    "我同意卡的设置",                  # 触发词没在句首
    "同意卡批 abc123 deadbeef",         # 触发词后无空白边界
    "随机图",
    "同意卡 待批 现在几点",
)


@pytest.mark.parametrize("text", ACCEPTED)
def test_predicate_accepts_only_anchored_command_shapes(text: str) -> None:
    assert consent_admin.is_consent_command(text), text


@pytest.mark.parametrize("text", REJECTED)
def test_predicate_rejects_loose_or_unanchored_text(text: str) -> None:
    assert not consent_admin.is_consent_command(text), text


def test_help_word_list_equals_route_predicate_word_list() -> None:
    """双向门的席位自检：帮助册词表与谓词词表同一枚真身，不靠台账放行。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        HELP_ENTRIES,
    )

    entry = next(item for item in HELP_ENTRIES if item["topic"] == "书面同意")
    assert set(entry["aliases"]) == set(consent_admin.DEFAULT_TRIGGER_WORDS)
    for word in consent_admin.DEFAULT_TRIGGER_WORDS:
        assert consent_admin.is_consent_command(word), word


# ---------------------------------------------------------------------------
# 2. 四态端到端（真装配口 + 真命令面）
# ---------------------------------------------------------------------------


def test_state_1_write_without_ticket_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    store, gate = _gated_store(tmp_path)
    with pytest.raises(RuntimeChangeNeedsConsent) as caught:
        store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    assert caught.value.target == R2_KEY and caught.value.tier == "R2"
    assert store.list_overrides() == {}, "被拒的写把值落下去了——拒绝路径泄了"
    row = _ticket_of(gate, R2_KEY)
    assert row.state == "pending"
    # 卡面话术必须点名「怎么批」，且那句话说的是**真存在**的命令面（散文不许点名
    # 不存在的东西——统一波立过的规矩）。
    assert "同意卡 批" in str(caught.value)
    assert "/bot consent" not in str(caught.value)


def test_state_2_super_admin_approves_then_retry_lands(tmp_path: Path) -> None:
    store, gate = _gated_store(tmp_path)
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    row = _ticket_of(gate, R2_KEY)
    sentence = f"同意卡 批 {row.consent_id} {settings_gate.short_code_of(row)}"
    verdict = consent_admin.build_consent_admin_result(
        gate, _message(sentence),
        consent_admin.parse_consent_command(sentence) or {},
        request_id="req-approve",
    )
    assert "按你批的记下了" in verdict.body
    assert store.list_overrides() == {}, "批语本身不许顺手改参数"
    applied = store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    assert applied is False, "R2 值没落地（重试路径断了）"
    assert [t.row.state for t in gate.pending_tickets() if t.row.target == R2_KEY] == []


def test_state_2b_wrong_short_code_is_not_a_verdict_but_is_audited(tmp_path: Path) -> None:
    store, gate = _gated_store(tmp_path)
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    row = _ticket_of(gate, R2_KEY)
    before = len(gate.change_history(limit=50))
    verdict = gate.approve(row.consent_id, code="00000000", message=_message("同意卡 批 x 0"))
    assert isinstance(verdict, Refusal) and verdict.kind is DenyKind.APPROVAL_CODE_MISMATCH
    assert _ticket_of(gate, R2_KEY).state == "pending", "误码不该消费工单"
    after = gate.change_history(limit=50)
    assert len(after) == before + 1, "误码不留痕＝一条可以无限试的公开猜号面"
    assert "没对上" in after[0].reason or "APPROVAL_CODE_MISMATCH" in after[0].reason


def test_state_3_expired_ticket_is_refused_and_write_still_lands_nothing(
    tmp_path: Path,
) -> None:
    now = {"t": datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)}
    store, gate = _gated_store(tmp_path, clock=lambda: now["t"])
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    row = _ticket_of(gate, R2_KEY)
    now["t"] = row.expires_at + timedelta(seconds=1)  # 过期之后拿原句再批
    verdict = gate.approve(row.consent_id, code=settings_gate.short_code_of(row),
                           message=_message("同意卡 批 x y"))
    assert isinstance(verdict, Refusal) and verdict.kind is DenyKind.EXPIRED
    assert store.list_overrides() == {}
    # 过期卡不可续：重试那次写只会签出**新的一张**，不会把旧的救活。
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    fresh = _ticket_of(gate, R2_KEY)
    assert fresh.consent_id != row.consent_id and fresh.state == "pending"


def test_state_4_non_super_admin_cannot_approve_written_consent(tmp_path: Path) -> None:
    store, gate = _gated_store(tmp_path)
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    row = _ticket_of(gate, R2_KEY)
    verdict = gate.approve(row.consent_id, code=settings_gate.short_code_of(row),
                           message=_message("同意卡 批 x y", roles=ADMIN_ONLY_ROLES))
    assert isinstance(verdict, Refusal)
    assert verdict.kind is DenyKind.APPROVER_NOT_AUTHORISED
    assert store.list_overrides() == {}
    # 群里那句同样不算（R2 要私聊）：先过权限、再过场景，顺序不可换。
    verdict2 = gate.approve(row.consent_id, code=settings_gate.short_code_of(row),
                            message=_message("同意卡 批 x y",
                                             session_type=SessionType.GROUP,
                                             session_id="group_9_9"))
    assert isinstance(verdict2, Refusal) and verdict2.kind is DenyKind.NOT_PRIVATE_CHAT


def test_state_5_requester_cannot_approve_own_ticket(tmp_path: Path) -> None:
    """防自批（本轮补上的一判）：以谁的名义发起，那个人就不能再亲手批掉它。"""
    store, gate = _gated_store(tmp_path)
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=f"qq:{APPROVER_ID}")
    row = _ticket_of(gate, R2_KEY)
    verdict = gate.approve(row.consent_id, code=settings_gate.short_code_of(row),
                           message=_message("同意卡 批 x y"))
    assert isinstance(verdict, Refusal)
    assert verdict.kind is DenyKind.SELF_CONSENT, f"自批没被拦：{verdict}"
    assert store.list_overrides() == {}
    # 反向锁：内部无名写点（`runtime_internal`）不构成「申请人」，
    # 否则定时排程签出的卡将永无被人批的一天。
    store2, gate2 = _gated_store(tmp_path / "internal")
    with pytest.raises(RuntimeChangeNeedsConsent):
        store2.set_override(R2_KEY, R2_VALUE, actor="runtime_internal")
    row2 = _ticket_of(gate2, R2_KEY)
    granted = gate2.approve(row2.consent_id, code=settings_gate.short_code_of(row2),
                            message=_message("同意卡 批 x y"))
    assert isinstance(granted, ConsentGrant)


@pytest.mark.parametrize(
    ("requester", "approver", "same"),
    [
        ("qq:123", "qq:123", True),
        ("qq:123", "tg:123", False),          # 跨平台同号不是同一个人
        ("123", "qq:123", True),              # 一侧没带平台：按同人算（宁可多拒）
        ("runtime_internal", "qq:123", False),
        ("bot:self_iteration", "qq:123", False),
        ("", "qq:123", False),
        ("qq:123", "qq:1234", False),
        ("QQ:123", "qq:123", True),           # 平台与号都大小写不敏感
    ],
)
def test_self_consent_identity_rule_is_exact(requester: str, approver: str, same: bool) -> None:
    assert consent_mod.is_same_principal(requester, approver) is same


def test_state_6_deny_revokes_the_ticket_and_the_write_never_happens(
    tmp_path: Path,
) -> None:
    store, gate = _gated_store(tmp_path)
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    row = _ticket_of(gate, R2_KEY)
    sentence = f"同意卡 驳 {row.consent_id} {settings_gate.short_code_of(row)}"
    result = consent_admin.build_consent_admin_result(
        gate, _message(sentence),
        consent_admin.parse_consent_command(sentence) or {},
        request_id="req-deny",
    )
    assert "被驳回" in result.body or "作废" in result.body
    assert store.list_overrides() == {}
    # 驳回把卡置成终态：既不在待批面上，也再批不动（一次性与终态同一条判据）。
    assert [t for t in gate.pending_tickets() if t.row.consent_id == row.consent_id] == []
    assert gate.ticket(row.consent_id).row.state == "revoked"
    # 作废的卡不能再被拿去批（一次性与终态同一条判据）。
    again = gate.approve(row.consent_id, code=settings_gate.short_code_of(row),
                         message=_message("同意卡 批 x y"))
    assert isinstance(again, Refusal) and again.kind is DenyKind.ALREADY_USED


# ---------------------------------------------------------------------------
# 3. `session_key` 不再是死码：R1 的原会话门今天真能红
# ---------------------------------------------------------------------------


def test_r1_card_issued_with_real_session_is_refused_from_another_session(
    tmp_path: Path,
) -> None:
    """接线前这一判**结构上跑不到**（咽喉递的是硬编码空串）；现在必须能红。"""
    store, gate = _gated_store(tmp_path)
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R1_KEY, R1_VALUE, actor=R1_REQUESTER, session_key=R1_SESSION)
    row = _ticket_of(gate, R1_KEY)
    assert row.source_session_key == R1_SESSION, "咽喉没把真实会话键交给账"
    assert not row.require_private, "R1 不该要求私聊"
    wrong = gate.approve(row.consent_id, code=settings_gate.short_code_of(row),
                         message=_message("同意卡 批 x y", roles=ADMIN_ONLY_ROLES,
                                          session_type=SessionType.GROUP,
                                          session_id="group_9999_9999"))
    assert isinstance(wrong, Refusal) and wrong.kind is DenyKind.APPROVER_NOT_AUTHORISED
    assert "原会话" in wrong.detail
    right = gate.approve(row.consent_id, code=settings_gate.short_code_of(row),
                         message=_message("同意卡 批 x y", roles=ADMIN_ONLY_ROLES,
                                          session_type=SessionType.GROUP,
                                          session_id=R1_SESSION))
    assert isinstance(right, ConsentGrant), f"同会话批不动：{right}"
    assert store.set_override(R1_KEY, R1_VALUE, actor=R1_REQUESTER,
                              session_key=R1_SESSION) is not None


def test_empty_session_key_keeps_the_old_shape_and_says_so(tmp_path: Path) -> None:
    """拿不到会话的写点（内部调度器）仍可用：空串＝这张卡不声明来源会话，
    原会话判据不启用——这不是漏判，是不假装执法的登记形态。"""
    store, gate = _gated_store(tmp_path / "nosession")
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R1_KEY, R1_VALUE, actor=R1_REQUESTER)
    row = _ticket_of(gate, R1_KEY)
    assert row.source_session_key == ""
    granted = gate.approve(row.consent_id, code=settings_gate.short_code_of(row),
                           message=_message("同意卡 批 x y", roles=ADMIN_ONLY_ROLES,
                                            session_type=SessionType.GROUP,
                                            session_id="group_7_7"))
    assert isinstance(granted, ConsentGrant)


def _func(tree: ast.Module, dotted: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    parts = dotted.split(".")
    node: Any = tree
    for part in parts:
        node = next(
            child
            for child in ast.walk(node)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and child.name == part
        )
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    return node


def _kwarg_names(call: ast.Call) -> set[str]:
    return {keyword.arg for keyword in call.keywords if keyword.arg}


def test_throat_no_longer_hardcodes_an_empty_session_key() -> None:
    """结构锁：咽喉体内不得再出现 `session_key=""`，且必须把它透传给门。

    反向锁同批立：两个写面各自都必须把 `session_key` 交下去——只补一半
    （`set_override` 传、`reset_override` 不传）就是留一个看着在执法的空壳。
    """
    tree = ast.parse(SETTINGS_PY.read_text(encoding="utf-8"))
    store_cls = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeSettingsStore"
    )
    guard = _func(store_cls, "_throat_guard")
    guard_src = ast.unparse(guard)
    assert 'session_key=""' not in guard_src, "硬编码空串又回来了：R1 的原会话门会重新变成死码"
    guarded = next(
        call for call in ast.walk(guard)
        if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "guarded_write"
    )
    assert "session_key" in _kwarg_names(guarded)
    for method in ("set_override", "reset_override"):
        body = _func(store_cls, method)
        assert "session_key" in {
            arg.arg for arg in [*body.args.args, *body.args.kwonlyargs]
        }, f"{method} 没有 session_key 形参"
        calls = [
            call for call in ast.walk(body)
            if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "_throat_guard"
        ]
        assert calls, f"{method} 不再过咽喉"
        for call in calls:
            assert "session_key" in _kwarg_names(call), f"{method} 没把会话键交给咽喉"
    # 会话键清洗只在咽喉一处真身，写面不各自洗一遍（禁第二判据）。
    assert guard_src.count("_as_text_key(") == 1


def test_settings_admin_writes_carry_actor_and_session() -> None:
    """`/bot runtime` 这条面的每一枚咽喉写点都必须带 actor + session_key。

    反向锁：把 runtime_admin 里任一写点的 `actor=` 摘掉 ⇒ 本锁红。这条锁的意义是
    「防自批与 R1 原会话门在生产有没有可触发的输入」——不带身份，两判据都只是形式。
    """
    tree = ast.parse(RUNTIME_ADMIN_PY.read_text(encoding="utf-8"))
    calls = [
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr in {"set_override", "reset_override"}
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "store"
    ]
    assert len(calls) >= 10, f"只数到 {len(calls)} 枚写点，谓词可能失效（不许假零）"
    for call in calls:
        kwargs = _kwarg_names(call)
        assert {"actor", "session_key"} <= kwargs, ast.unparse(call)[:80]


# ---------------------------------------------------------------------------
# 4. 命令面的权限与回显
# ---------------------------------------------------------------------------


def test_capability_lists_and_shows_without_leaking_to_non_admin(tmp_path: Path) -> None:
    store, gate = _gated_store(tmp_path)
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    row = _ticket_of(gate, R2_KEY)
    capability = consent_admin.build_consent_admin_capability(lambda: store.safety_gate)
    listed = capability(_message("同意卡 待批"), SimpleNamespace(actor_roles=SUPER_ROLES))
    assert row.consent_id in listed.body
    assert settings_gate.short_code_of(row) in listed.body
    assert R2_KEY in listed.body
    shown = capability(_message(f"同意卡 看 {row.consent_id}"),
                       SimpleNamespace(actor_roles=SUPER_ROLES))
    assert row.consent_id in shown.body
    silent = capability(_message("今天天气不错"), SimpleNamespace(actor_roles=SUPER_ROLES))
    assert "skip_no_trigger" in silent.audit_tags, "不是命令的句子该静默，不该回一句闲话"
    outsider = capability(_message("同意卡 待批"), SimpleNamespace(actor_roles=USER_ROLES))
    assert row.consent_id not in outsider.body, "非管理员拿到了卡面内容"
    assert outsider.audit_tags.count("gate_not_admin") == 1


def test_capability_provider_is_read_every_call_not_snapshotted(tmp_path: Path) -> None:
    """装配侧交来的必须是**每次现读**的门句柄：建门是惰性的，快照会把命令面钉成死的。"""
    store = _wired_store(tmp_path)
    holder: dict[str, Any] = {"gate": None}
    capability = consent_admin.build_consent_admin_capability(lambda: holder["gate"])
    closed = capability(_message("同意卡 待批"), SimpleNamespace(actor_roles=SUPER_ROLES))
    assert "没装载" in closed.body
    holder["gate"] = SettingsWriteGate(
        settings_store=store,
        config=_config(tmp_path),
        policy=ConsentPolicy(enabled=True, ttl_minutes=30, auto_r0_enabled=False),
    )
    store.attach_safety_gate(holder["gate"])
    opened = capability(_message("同意卡 待批"), SimpleNamespace(actor_roles=SUPER_ROLES))
    assert "没装载" not in opened.body


def test_capability_never_writes_parameters_itself(tmp_path: Path) -> None:
    """能力件零写腿：整件不许出现 set_override/reset_override 直呼（判据在咽喉）。"""
    tree = ast.parse(CAPABILITY_PY.read_text(encoding="utf-8"))
    forbidden = {"set_override", "reset_override", "guarded_write", "claim_consent",
                 "revoke_consent", "append_consent"}
    hits = {
        call.func.attr
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }
    assert not (hits & forbidden), f"命令面自己动笔了：{sorted(hits & forbidden)}"


def test_applicant_hint_carries_ticket_code_expiry_and_next_step(
    tmp_path: Path,
) -> None:
    """被拦下时申请人看到的那一句必须自带「票号 + 短码 + 批准入口 + 有效期 + 下一步」。

    判据是**结构**上的（模板里必须含四枚占位符 + 一句真在跑的批准形），
    不是内容文案——文案归文案，改字改语序不许悄悄把这四件事弄没。
    这条锁的红→绿路径来自 S-CONSENT-APPROVE 席位（第 18 项出票侧闭环）；
    上一版模板缺「工单 X」抬头（票号只出现在批准指令正文里、申请人易被卡面话术
    绕过），此锁逼这一枚抬头常驻。
    """
    template = settings_gate._APPROVE_HINT_TEMPLATE
    # 四枚占位符（模板格式化后必须真填进去，缺一枚即"发票没写号"这种病）
    for placeholder in ("{consent_id}", "{code}", "{expires_at}"):
        assert placeholder in template, f"模板丢了占位符 {placeholder}（申请人看不到那一环）"
    assert template.count("{consent_id}") >= 2, (
        "工单抬头与批准指令两处都要点票号——只在指令里出现一次＝申请人只看到一串命令，"
        "对不上是哪张卡。"
    )
    # 一句真在跑的批准形（与 parse_consent_command 的谓词同源，禁点名不存在的入口）
    assert "同意卡 批 {consent_id} {code}" in template, (
        "批准入口不是谓词真认得的形；散文点了不存在的东西"
    )
    # 「下一步」这一问必须显式落到"用同一参数再说一次"——不是"等一等"、不是"联系谁"
    assert "用同一参数再说一次" in template, "下一步丢了：批完之后要谁做什么没写"
    # 严禁把球踢回去却没有对象（她是管理员，不需要"请联系管理员"这种空话）
    for banned in ("请联系管理员", "请咨询管理员", "请找管理员", "请稍等"):
        assert banned not in template, f"模板回潮了空转话术：{banned}"


def test_applicant_hint_survives_poison_on_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒：把模板换成"请联系管理员"式空话 ⇒ 上一发锁必红（证明那条锁不是摆设）。

    中毒版刻意保留 `{consent_id}` 一枚占位符（否则格式化就崩、红在别处），
    但把批准指令 / 短码 / 有效期 / 下一步全丢了——**上一发结构锁的四问全红**
    才叫毒发，光看 `key==key` 那类空跑不算。
    """
    original = settings_gate._APPROVE_HINT_TEMPLATE
    monkeypatch.setattr(
        settings_gate,
        "_APPROVE_HINT_TEMPLATE",
        "这次没能改，请联系管理员处理：同意号 {consent_id}",
    )
    try:
        store, _gate = _gated_store(tmp_path)
        with pytest.raises(RuntimeChangeNeedsConsent) as caught:
            store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
        text = str(caught.value)
        assert "请联系管理员" in text, "毒没生效＝这条锁不测模板本体，是空跑"
        expected_command = (
            f"同意卡 批 {caught.value.consent_id} {caught.value.short_code}"
        )
        assert expected_command not in text, (
            "中毒版仍带批准指令 ⇒ 上一发结构锁不测的是模板本体"
        )
        assert caught.value.short_code not in text, "中毒版仍带短码"
        assert "用同一参数再说一次" not in text, "中毒版仍带下一步"
    finally:
        monkeypatch.undo()
    assert settings_gate._APPROVE_HINT_TEMPLATE is original, "还原失败"
    # 还原后：结构锁的判据必须能重新成立（同一段文本再走一次判据）
    restored = settings_gate._APPROVE_HINT_TEMPLATE
    assert "同意卡 批 {consent_id} {code}" in restored
    assert "请联系管理员" not in restored


# ---------------------------------------------------------------------------
# 5. 注毒自证：每把锁都要能被打红
# ---------------------------------------------------------------------------


def test_poison_disabling_self_consent_check_flips_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """把 `is_same_principal` 打成恒假 ⇒ 第 5 态必红（证明红来自这条判据、不是噪声）。"""
    store, gate = _gated_store(tmp_path)
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=f"qq:{APPROVER_ID}")
    row = _ticket_of(gate, R2_KEY)
    original = consent_mod.is_same_principal
    monkeypatch.setattr(consent_mod, "is_same_principal", lambda *_a, **_k: False)
    try:
        poisoned = gate.approve(row.consent_id, code=settings_gate.short_code_of(row),
                                message=_message("同意卡 批 x y"))
        assert isinstance(poisoned, ConsentGrant), "毒发了却没变绿＝这条锁是空跑"
    finally:
        monkeypatch.undo()
    assert consent_mod.is_same_principal is original, "还原失败＝后面那发断言测的是毒不是代码"
    restored = gate.approve(row.consent_id, code=settings_gate.short_code_of(row),
                            message=_message("同意卡 批 x y"))
    assert isinstance(restored, Refusal), "还原后仍不拦＝测的是夹具不是代码"


def test_poison_predicate_boundary_cannot_be_loosened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """把「触发词后必须跟空白」这一边界洗掉 ⇒ 负样本必红（谓词不是摆设）。"""
    original = consent_admin._head_and_rest

    def loosened(text: str):
        raw = str(text or "").strip()
        for word in consent_admin.DEFAULT_TRIGGER_WORDS:
            if raw.casefold().startswith(word.casefold()):
                return word, raw[len(word):].strip()
        return None

    assert not consent_admin.is_consent_command("同意卡批 abc123 deadbeef")
    monkeypatch.setattr(consent_admin, "_head_and_rest", loosened)
    try:
        assert consent_admin.is_consent_command("同意卡批 abc123 deadbeef"), (
            "毒发了却没放宽＝这条锁压根没在判边界（空跑）"
        )
    finally:
        monkeypatch.undo()
    assert consent_admin._head_and_rest is original, "还原失败＝这发断言测的是毒不是代码"
    assert not consent_admin.is_consent_command("同意卡批 abc123 deadbeef"), "还原后仍放宽"


# ---------------------------------------------------------------------------
# 5. 装配活性（S-CONSDISP 席，2026-09-26）：命令面今天真被根 dispatch 承载
# ---------------------------------------------------------------------------

ROOT_INIT_PY = ROOT / "plugins/bot_unified_runtime/__init__.py"


def _consent_matcher_nodes(tree: ast.AST) -> tuple[ast.Assign, ast.AsyncFunctionDef]:
    """从根装配文件里取 consent 的「注册赋值 + handler」两节点，缺一个当场 AssertionError。

    判据只认结构形态（与登记册同一哲学：按符号名锚定，不数行号）：
    ① `<x> = on_message(rule=<谓词>, priority=41, block=True)`，且谓词体内
      比对 `RouteKind.CONSENT`；② 被 `@x.handle()` 装饰的 async handler。
    """
    matcher_assign: ast.Assign | None = None
    matcher_name = ""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and getattr(node.value.func, "id", "") == "on_message"
            and any(
                isinstance(target, ast.Name) and target.id.endswith("consent_matcher")
                for target in node.targets
            )
        ):
            matcher_name = node.targets[0].id  # type: ignore[union-attr]
            matcher_assign = node
            break
    assert matcher_assign is not None, (
        "根装配文件里没有 consent 的 on_message 注册——命令面在册而生产无人 dispatch"
        "（这正是 §⑨-A 装之前『代码全在、真机走不到』的形态）"
    )
    rule = next(
        (kw.value for kw in matcher_assign.value.keywords if kw.arg == "rule"), None
    )
    assert isinstance(rule, ast.Name), "consent matcher 的 rule 必须是具名谓词"
    predicate = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == rule.id
        ),
        None,
    )
    assert predicate is not None, f"谓词 {rule.id} 不存在"
    assert "RouteKind.CONSENT" in ast.unparse(predicate), (
        "谓词不比对 RouteKind.CONSENT ⇒ dispatch 与该路由族没有接线"
    )
    handler: ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "handle"
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == matcher_name
            ):
                handler = node
    assert handler is not None, f"@{matcher_name}.handle() 的 handler 不存在"
    return matcher_assign, handler


def test_consent_matcher_is_wired_in_root() -> None:
    """装配活性锁（§⑨-A 必带件）：根的 consent handler 必须
    ① 在函数体内 import build_consent_admin_capability（置顶 import 会顶漂登记坐标，
       5a/host_state/campus 三处先例同法）；
    ② 把**每次现读**的门句柄（lambda 里读 runtime_settings.safety_gate）交给工厂——
       构造期快照会把命令面钉成「门没装载」；
    ③ 以 capability_id="bot.consent" 投递进中央管线。

    本锁不 import 根文件（会拉起整个 NoneBot 装配），按仓内先例走 AST 现算。
    它与 test_consent_command_through_handler_reaches_approve 合起来才构成
    「命令进 handler → 批票路径被调用」的证据：那条锁判『handler 装配对了』，
    这条锁判『经 handler 造出的能力真批得动卡』。单有构造器直调不算装配——
    本仓台账记过这种假绿。
    """
    _tree = ast.parse(ROOT_INIT_PY.read_text(encoding="utf-8"))
    _matcher_assign, handler = _consent_matcher_nodes(_tree)

    # ① 函数体内 import：ImportFrom 出现在 handler 体内而非模块顶层。
    imports = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.ImportFrom)
        and any(a.name == "build_consent_admin_capability" for a in node.names)
    ]
    assert imports, "handler 没在函数体内 import build_consent_admin_capability"
    top_level = [
        node
        for node in _tree.body
        if isinstance(node, ast.ImportFrom)
        and any(a.name == "build_consent_admin_capability" for a in node.names)
    ]
    assert not top_level, (
        "build_consent_admin_capability 被挪到了模块顶层 import——"
        "会把 campus_record_matcher 等登记坐标整体顶漂（先例口径：只准函数体内）"
    )

    # ② 工厂拿到的 gate_provider 必须是 lambda 且每跑一次读一次 safety_gate。
    factory_calls = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "build_consent_admin_capability"
    ]
    assert len(factory_calls) == 1, "handler 里工厂调用不恰好一枚"
    provider = factory_calls[0].args[0] if factory_calls[0].args else None
    assert isinstance(provider, ast.Lambda), (
        "gate_provider 不是 lambda——构造期快照把门钉成 None 的旧坑回来了"
    )
    provider_src = ast.unparse(provider)
    assert "runtime_settings" in provider_src and "safety_gate" in provider_src, (
        f"gate_provider 没现读装配 store 的门句柄：{provider_src}"
    )

    # ③ 以 capability_id="bot.consent" 经 pipeline.handle_async 投递（中央管线，非直发）。
    pipeline_calls = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "handle_async"
    ]
    assert pipeline_calls, "handler 不经 pipeline.handle_async（中央管线被旁路）"
    ids = {
        kw.value.value
        for call in pipeline_calls
        for kw in call.keywords
        if kw.arg == "capability_id" and isinstance(kw.value, ast.Constant)
    }
    assert "bot.consent" in ids, f"投递的 capability_id 不是 bot.consent：{ids}"


def test_consent_command_through_handler_reaches_approve(tmp_path: Path) -> None:
    """活性腿之二：用与 handler **同一构造式**造出的能力，喂一句真批准命令，
    批票路径必须被调用（卡被消费、凭证成立、原发起人同参重试才落库）。

    这不与 test_state_2 重复：state_2 直调 gate.approve（门本体），本例走的是
    命令面 → build_consent_admin_capability → build_consent_admin_result →
    gate.approve 这条 dispatch 真实执行的那段。装配锁（上一条）证明根上有人
    这样调，本条证明这样调**批得动**。两腿都绿才配说「真机能批票」。
    """
    store, gate = _gated_store(tmp_path)
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER)
    row = _ticket_of(gate, R2_KEY)

    capability = consent_admin.build_consent_admin_capability(
        lambda: store.safety_gate  # 与根 handler 同一形：每次现读
    )
    granted = capability(
        _message(f"同意卡 批 {row.consent_id} {settings_gate.short_code_of(row)}"),
        SimpleNamespace(actor_roles=SUPER_ROLES),
    )
    assert "approve_granted" in granted.audit_tags, (
        f"批准命令进了命令面却没批动：audit={granted.audit_tags}"
    )
    assert "按你批的记下了" in granted.body
    # 凭证入暂存、卡离开 pending：批票路径真被走到，不是文案回显。
    assert gate.pending_tickets() == []
    # 原发起人同参重试 ⇒ 这才落库（批准本身从不改参数）。
    assert store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER) is False
    assert store.list_overrides()[R2_KEY] is False
