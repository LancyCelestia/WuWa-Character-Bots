"""bot.why 执行面角色门活性回归锁（统一接入波 · 席位 S-WHY，2026-09-22）。

缺陷（实跑证实，见 .superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-WHY.md）：
帮助条目 admin_only=True，而 `build_why_result` 无角色形参、根分发亦不传 roles
⇒ 任何主体可拿到受保护的运行时诊断。修复=补中央 `roles_satisfy` 层级门
（admin 最低门槛，超管叠 admin，缺省/未知角色 fail-closed）。

全离线：喂 `RecentDiagnosticsStore` + 合成 `RuntimeDiagnostic`，零网络零生产 .env。
判据双向 + 注毒自证（门永真 ⇒ user 拒绝锁必红且点名；门永假 ⇒ admin 放行锁必红且点名）。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import plugins.bot_unified_runtime.runtime.capability_protocols as cp
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.ops.smoke.diagnostics import (
    RecentDiagnosticsStore,
    RuntimeDiagnostic,
    build_why_result,
)

SESSION = "group_10001_20002"
# 受保护内容探针：全部落在 why 正文真实渲染的字段上（_format_why_body 逐行消费）。
PROTECTED_MARKERS = (
    "req-PROTECTED-42",
    "dbg-PROTECTED-42",
    "PROTECTED_POLICY_MARKER",
    "PROTECTED_SUMMARY_MARKER",
)


def _store_with_diagnostic() -> RecentDiagnosticsStore:
    store = RecentDiagnosticsStore()
    store.record(
        RuntimeDiagnostic(
            request_id="req-PROTECTED-42",
            debug_id="dbg-PROTECTED-42",
            session_id=SESSION,
            capability_id="bot.chat",
            session_type="group",
            policy_allowed=True,
            policy_reason="PROTECTED_POLICY_MARKER",
            risk_level="low",
            privacy_level="personal",
            receipt_state="sent",
            receipt_message="ok",
            why_summary="PROTECTED_SUMMARY_MARKER",
        )
    )
    return store


def _call(store: RecentDiagnosticsStore, actor_roles: list[str] | None):
    kwargs = {"request_id": "probe", "session_id": SESSION, "query": ""}
    if actor_roles is not None:
        kwargs["actor_roles"] = actor_roles
    return build_why_result(store, **kwargs)


def _expect_user_denied(store: RecentDiagnosticsStore, actor_roles=None) -> None:
    """被拒锁：audit_tags 含 why_denied 且返回体不含任何受保护内容。"""
    result = _call(store, actor_roles)
    assert "why_denied" in (result.audit_tags or []), (
        f"why_denied 缺失：非管理员/无角色主体未被执行面拒绝（tags={result.audit_tags}）"
    )
    assert result.capability_id == "bot.why"
    for marker in PROTECTED_MARKERS:
        assert marker not in result.body, f"拒绝体泄露受保护内容探针 {marker!r}"


def _expect_admin_allowed(store: RecentDiagnosticsStore, actor_roles) -> None:
    """放行锁：admin 秩及以上拿到诊断正文。"""
    result = _call(store, actor_roles)
    assert "why_denied" not in (result.audit_tags or []), (
        f"admin_allowed 被误拒（tags={result.audit_tags}）"
    )
    assert "最近一次运行时诊断" in result.body, "admin_allowed 未拿到诊断正文"


def test_signature_declares_role_param():
    """结构锁：修复的判据入口本身在签名上可见（防只改文案不改门）。"""
    params = inspect.signature(build_why_result).parameters
    assert "actor_roles" in params, "build_why_result 角色形参消失"


def test_user_subject_denied_and_body_leaks_nothing():
    _expect_user_denied(_store_with_diagnostic(), ["user"])


def test_missing_roles_fail_closed():
    """根分发尚未补传 actor_roles 的现存形态 ⇒ 缺省必须拒（fail-closed，不猜身份）。"""
    _expect_user_denied(_store_with_diagnostic(), None)


def test_trusted_and_enterprise_denied_below_admin_floor():
    store = _store_with_diagnostic()
    _expect_user_denied(store, ["trusted"])
    _expect_user_denied(store, ["trusted", "enterprise"])


def test_unknown_role_string_fail_closed():
    """经中央 roles_satisfy：不在 ROLE_ORDER 的串一律不满足（永真注毒测不到这层）。"""
    store = _store_with_diagnostic()
    _expect_user_denied(store, ["root"])
    _expect_user_denied(store, ["ADMIN"])


def test_admin_allowed():
    _expect_admin_allowed(_store_with_diagnostic(), ["admin"])


def test_super_admin_allowed_without_literal_admin_role():
    """超管不写字面 admin 也放行=层级最低门槛语义（roles_satisfy，非 == 比较）。"""
    _expect_admin_allowed(_store_with_diagnostic(), ["super_admin"])


def test_denied_body_is_admin_gate_pool_copy():
    """被拒文案=同族管理门池（U11/Q-02 单源），守岸人语气温和不指责。"""
    result = _call(_store_with_diagnostic(), ["user"])
    expected = {
        template.format(action="看最近一次运行诊断")
        for template in user_copy.ADMIN_GATE_TEMPLATES
    }
    assert result.body in expected, f"拒绝文案脱离管理门池: {result.body!r}"


def test_poison_gate_always_true_kills_user_denial_lock(monkeypatch):
    """注毒①：门改永真 ⇒ 必红在「user 被拒」这条锁上（点名 why_denied 断言）。"""
    monkeypatch.setattr(cp, "roles_satisfy", lambda held, required: True)
    with pytest.raises(AssertionError, match="why_denied 缺失"):
        _expect_user_denied(_store_with_diagnostic(), ["user"])


def test_poison_gate_always_false_kills_admin_allowed_lock(monkeypatch):
    """注毒②：门改永假 ⇒ 必红在「admin 放行」这条锁上（点名 admin_allowed 断言）。"""
    monkeypatch.setattr(cp, "roles_satisfy", lambda held, required: False)
    with pytest.raises(AssertionError, match="admin_allowed 被误拒"):
        _expect_admin_allowed(_store_with_diagnostic(), ["admin"])


def test_root_dispatch_actually_passes_actor_roles() -> None:
    """接线半边（R-ROLE/I-1）：门在 builder 里，角色得真从根分发传进来。

    缺它的后果不是崩溃而是"全员温和拒答"——builder 侧 fail-closed 会拒一切主体（含超管），
    正是本次要消灭的反模式的镜像版本，所以必须由门钉住，不靠人肉记得。
    """
    root = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime" / "__init__.py"
    tree = ast.parse(root.read_text(encoding="utf-8"))
    sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "build_why_result"
    ]
    assert sites, "根文件里找不到 build_why_result 调用——分发点被搬走了，本锁需随迁重写"
    for site in sites:
        assert "actor_roles" in {kw.arg for kw in site.keywords}, f"根:{site.lineno} 未把角色传进能力"
