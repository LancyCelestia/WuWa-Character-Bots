"""SAFE-EXEC 裁定第 18 项：咽喉接线的**活性**锁（S-CONSENT-WIRE 席，2026-09-26）。

钉的是什么
----
接线前实况（S-R-SAFETYEXEC-WIRING 现算）：`configure_safety_gate` 全仓零调用者、
`set_override`/`reset_override` 一次都不过门 ⇒ 书面同意门「机制在册、生产永不装载」。
本件不再测门类内部（那是 `test_safety_exec_consent.py` 的活），测的是**接线本身**：

- L1 绕过咽喉即红 AST 锁：两个写面必须经 `_throat_guard`，`_throat_guard` 必须
  真调 `_ensure_safety_gate` / `_refuse_without_gate` / `guarded_write`（她亲点的那枚）；
- L2 装配活性：走真装配口 `build_instance_settings_manager(config)` 建出的 store，
  第一次 R2 写就撞门（门装不上＝这条直接红）；
- L4 行为锁：一次高危参数写入，**没有票被拒、带票通过**，全程只经公共写面
  （set_override / gate.approve / set_override 重试），不碰任何私有件；
- L5 fail-closed：门本体装不起来 ⇒ 同意档一律拒、只有 R0 直写（`_refuse_without_gate`
  的档位判别今天真有读者）；
- 缺省态不骗人（F-2/SEAT-ATKFIX-CFG12 起改形）：总闸关 与 **显式声明** no-gate
  两个形态写入结果与落盘文件逐字节一致；而「从未装配且未声明」的裸 store 已
  fail-closed 翻转——写非 R0 当场拒（与门坏兜底同口径），不再无声放行；
- 工单不刷二张（`pending_tickets` 返回 ConsentTicket 壳、绑定在 `.row` 上——
  首版把壳当行用会在**第二次撞门**时抛 AttributeError，本锁顺带钉死这条回归）；
- 空 actor 重试必命中凭证：卡上 requester 与 binding 的 requester 必须同源归一。

全离线：设置文件与账本一律落 `tmp_path`，不碰 Runtime 真库、不 import NoneBot、不联网。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]

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
    InstanceSettingsManager,
    build_instance_settings_manager,
)
from plugins.bot_unified_runtime.domains.core.safety_exec import settings_gate
from plugins.bot_unified_runtime.domains.core.safety_exec.consent import ConsentGrant
from plugins.bot_unified_runtime.domains.core.safety_exec.settings_gate import (
    ALL_OVERRIDES_TARGET,
    RuntimeChangeNeedsConsent,
    SettingsWriteGate,
)

SETTINGS_PY = (
    ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "settings.py"
)
SUPER_ROLES = [ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN]

#: R2 真字段（`^BOT_(KB_WIKI|MEMORY)_(.*_)?(ENABLED|TOPICS)$`）且在 SETTABLE 白名单里：
#: 只有「既过分级、又过白名单」的键才能测到咽喉门的完整裁决路径。
R2_SETTABLE_KEY = "BOT_MEMORY_EXTRACT_ENABLED"
#: R0 真字段（超时族模式）且在白名单里：门开时也直写，只多一条审计流水。
R0_SETTABLE_KEY = "BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS"
R2_VALUE = "false"  # _bool_converter 的合法文本形
R0_VALUE = "45.0"


def _config(tmp_path: Path, *, enabled: bool | None) -> SimpleNamespace:
    """装配期 Config 的最小真实形状：三个读点各给一个（None=连总闸键都没有）。"""
    fields: dict[str, Any] = {
        "bot_runtime_settings_dir": str(tmp_path),
        "bot_control_plane_config_db": "",
    }
    if enabled is not None:
        fields["bot_safetyexec_enabled"] = enabled
    return SimpleNamespace(**fields)


def _wired_store(tmp_path: Path, *, enabled: bool) -> settings_mod.RuntimeSettingsStore:
    manager = build_instance_settings_manager(_config(tmp_path, enabled=enabled))
    return manager.get("default")


def _super_admin_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private_3865067623",
        session_type=SessionType.PRIVATE,
        sender_id="3865067623",
        sender_roles=list(SUPER_ROLES),
        plain_text=text,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ===========================================================================
# L2 + L4：装配后，一次高危写入「没票被拒、带票通过」——全程只走公共写面
# ===========================================================================


def test_r2_write_denied_without_ticket_and_passes_with_one(tmp_path: Path) -> None:
    store = _wired_store(tmp_path, enabled=True)
    # ① 没票：拒绝，且**什么都没写**。
    with pytest.raises(RuntimeChangeNeedsConsent) as first:
        store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="qq:3865067623")
    assert first.value.target == R2_SETTABLE_KEY
    assert first.value.tier == "R2"
    assert store.list_overrides() == {}, "被拒的写把值落下去了——拒绝路径泄了"
    # 装配活性：撞一次门之后，门对象必须真的挂在 store 上（门没装载就到此为止全红）。
    gate = store.safety_gate
    assert isinstance(gate, SettingsWriteGate) and gate.enabled

    # ② 超管私聊亲批（短码对卡面）——批的是这张卡，不是别的。
    verdict = gate.approve(
        first.value.consent_id,
        code=first.value.short_code,
        message=_super_admin_message(
            f"/bot consent approve {first.value.consent_id} {first.value.short_code}"
        ),
    )
    assert isinstance(verdict, ConsentGrant), f"批语没成立：{verdict}"

    # ③ 带票重试（同 key/值/actor）：这才真落库。
    applied = store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="qq:3865067623")
    assert applied is False
    assert store.list_overrides()[R2_SETTABLE_KEY] is False

    # ④ 两本账都在。同意账是 append-only：同一张卡「签发」与「消费」各写一行
    #    （后写覆盖前写的读取形），所以钉的是**去重后只有一张卡**，不是行数。
    consent_rows = _read_jsonl(tmp_path / "safetyexec_consent.jsonl")
    assert {r["consent_id"] for r in consent_rows} == {first.value.consent_id}, (
        "同意卡不止一张（复用路径没走到）"
    )
    assert [r["state"] for r in consent_rows if r["consent_id"] == first.value.consent_id] == [
        "pending", "consumed",
    ]
    changes = _read_jsonl(tmp_path / "safetyexec_change_audit.jsonl")
    final = [r for r in changes if r["state"] == "applied" and r["target"] == R2_SETTABLE_KEY]
    assert final and final[-1]["consent_id"] == first.value.consent_id


def test_same_request_reuses_the_one_pending_ticket(tmp_path: Path) -> None:
    """第二、三次撞门不许刷新卡（首版在这里把 ConsentTicket 壳当 ConsentRow 用，
    `row.binding` 抛 AttributeError 且不被兜底吃掉 ⇒ 本锁同时钉死那枚类型缺陷的运行时形态）。"""
    store = _wired_store(tmp_path, enabled=True)
    ids: list[str] = []
    for _ in range(3):
        with pytest.raises(RuntimeChangeNeedsConsent) as caught:
            store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="qq:3865067623")
        ids.append(caught.value.consent_id)
    assert len(set(ids)) == 1, f"同一件事刷出了多张卡：{ids}"
    assert store.list_overrides() == {}


def test_empty_actor_retry_still_consumes_the_grant(tmp_path: Path) -> None:
    """binding 的 requester 与卡上的 requester 必须同源归一：
    空 actor 若两侧各归一各的（binding 用 ""、卡用 "runtime_internal"），
    批完重试永远对不上凭证 ⇒ 「批了也写不进」的死循环工单。"""
    store = _wired_store(tmp_path, enabled=True)
    with pytest.raises(RuntimeChangeNeedsConsent) as first:
        store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="")
    gate = store.safety_gate
    verdict = gate.approve(
        first.value.consent_id, code=first.value.short_code,
        message=_super_admin_message("同意 0000000000000000"),
    )
    assert isinstance(verdict, ConsentGrant), verdict
    assert store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="") is False


def test_reset_single_key_r0_passes_but_reset_all_needs_ticket(tmp_path: Path) -> None:
    store = _wired_store(tmp_path, enabled=True)
    assert store.set_override(R0_SETTABLE_KEY, R0_VALUE, actor="qq:3865067623") == 45.0
    # R0 键单撤：按该键分级（R0）⇒ 直放，但审计必须有它的流水。
    assert store.reset_override(R0_SETTABLE_KEY, actor="qq:3865067623") == 1
    assert store.list_overrides() == {}
    # 先挂一条 R2 覆盖（批一次），再试「全撤」——聚合目标无单键可分级，落缺省 R2 ⇒ 要票。
    with pytest.raises(RuntimeChangeNeedsConsent):
        store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="qq:3865067623")
    gate = store.safety_gate
    need = gate.pending_tickets()[0]
    verdict = gate.approve(
        need.consent_id, code=settings_gate.short_code_of(need.row),
        message=_super_admin_message("x"),
    )
    assert isinstance(verdict, ConsentGrant)
    store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="qq:3865067623")
    with pytest.raises(RuntimeChangeNeedsConsent) as reset_all:
        store.reset_override(None, actor="qq:3865067623")
    assert reset_all.value.target == ALL_OVERRIDES_TARGET
    assert store.list_overrides()[R2_SETTABLE_KEY] is False, "全撤绕过了票"


def test_r0_write_lands_and_is_audited_gate_records_source(tmp_path: Path) -> None:
    store = _wired_store(tmp_path, enabled=True)
    assert store.set_override(R0_SETTABLE_KEY, R0_VALUE, actor="qq:3865067623") == 45.0
    changes = _read_jsonl(tmp_path / "safetyexec_change_audit.jsonl")
    row = [r for r in changes if r["target"] == R0_SETTABLE_KEY and r["state"] == "applied"]
    assert row and "source=unattended" in row[-1]["reason"]
    # R0 不配同意卡：账本里没有它。
    assert _read_jsonl(tmp_path / "safetyexec_consent.jsonl") == []


# ===========================================================================
# 缺省态不骗人（F-2 起三态分形）：关闸 ≡ 显式声明 no-gate（逐字节一致、零账本）；
# 「从未装配且未声明」不再等同无声放行——非 R0 写当场拒。
# ===========================================================================


def test_master_off_is_byte_identical_to_declared_no_gate(tmp_path: Path) -> None:
    off_dir = tmp_path / "off"
    legacy_dir = tmp_path / "legacy"
    off_store = _wired_store(off_dir, enabled=False)
    # 显式出口 = 测试/夹具声明的旧形态；裸构造（未声明）已改道 fail-closed（见下锁）。
    legacy_store = settings_mod.RuntimeSettingsStore(
        legacy_dir / "runtime_settings_default.json", allow_no_gate=True
    )
    off_result = off_store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="qq:1")
    legacy_result = legacy_store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="qq:1")
    assert off_result == legacy_result is False
    off_file = off_dir / "runtime_settings_default.json"
    legacy_file = legacy_dir / "runtime_settings_default.json"
    assert off_file.read_bytes() == legacy_file.read_bytes(), "落盘内容漂了字节"
    for directory in (off_dir, legacy_dir):
        assert not (directory / "safetyexec_consent.jsonl").exists()
        assert not (directory / "safetyexec_change_audit.jsonl").exists()
    # reset 两面同形：关闸与显式声明 no-gate 都不许被门挡。
    assert off_store.reset_override(R2_SETTABLE_KEY) == legacy_store.reset_override(R2_SETTABLE_KEY) == 1


def test_never_wired_store_is_fail_closed_not_silent(tmp_path: Path) -> None:
    """F-2 行为锁：从未装配、也未显式声明 no-gate 的裸 store——非 R0 写必须与
    「门本体坏了」的兜底拒**同口径**（同一句话），R0 仍按档直写，零账本文件。
    旧形态的「未装配=放行」是洞，不是特性：本锁钉住它已被关死。"""
    bare_dir = tmp_path / "bare"
    bare_store = InstanceSettingsManager(bare_dir).get("default")  # 真的从未装配
    with pytest.raises(ValueError) as refused:
        bare_store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="qq:1")
    assert "装载失败" in str(refused.value)
    assert bare_store.list_overrides() == {}, "被拒的写把值落下去了——拒绝路径泄了"
    assert bare_store.set_override(R0_SETTABLE_KEY, R0_VALUE, actor="qq:1") == 45.0
    assert not (bare_dir / "safetyexec_consent.jsonl").exists()
    assert not (bare_dir / "safetyexec_change_audit.jsonl").exists()


# ===========================================================================
# L5：门本体装不起来 ⇒ fail-closed（同意档拒、R0 直写）
# ===========================================================================


def test_gate_load_failure_refuses_consent_tiers_and_still_passes_r0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("注毒：门本体坏了")

    monkeypatch.setattr(settings_gate, "build_gate_for_store", explode)
    store = _wired_store(tmp_path, enabled=True)
    with pytest.raises(ValueError) as refused:
        store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="qq:3865067623")
    assert "装载失败" in str(refused.value)
    assert store.list_overrides() == {}
    # 同一颗坏门上 R0 仍直写：兜底判据是「按档放行」，不是「一坏全堵」也不是「一坏全放」。
    assert store.set_override(R0_SETTABLE_KEY, R0_VALUE, actor="qq:3865067623") == 45.0
    assert store.safety_gate is None  # 装载失败态如实可见


# ===========================================================================
# L1：绕过咽喉即红（AST 结构锁 + 注毒杀伤力自证）
# ===========================================================================


def _class_methods(tree: ast.Module, class_name: str) -> dict[str, ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.name: item
                for item in node.body
                if isinstance(item, ast.FunctionDef)
            }
    raise AssertionError(f"类 {class_name} 不在被审源码里")


def _calls_in(func: ast.FunctionDef) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(func)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def throat_wire_violations(source: str) -> list[str]:
    """纯判据：两个写面必须经 `_throat_guard`；`_throat_guard` 必须真调三件套。"""
    methods = _class_methods(ast.parse(source), "RuntimeSettingsStore")
    problems: list[str] = []
    for mutator in ("set_override", "reset_override"):
        if mutator not in methods:
            problems.append(f"{mutator} 不存在")
        elif "_throat_guard" not in _calls_in(methods[mutator]):
            problems.append(f"{mutator} 不再经过 _throat_guard（第二写通路出现）")
    guard = methods.get("_throat_guard")
    if guard is None:
        problems.append("_throat_guard 不存在")
    else:
        wanted = {"_ensure_safety_gate", "_refuse_without_gate", "guarded_write"}
        missing = wanted - _calls_in(guard)
        if missing:
            problems.append(f"_throat_guard 缺调用：{sorted(missing)}")
    return problems


def test_throat_wiring_ast_lock_is_clean_on_real_source() -> None:
    assert throat_wire_violations(SETTINGS_PY.read_text(encoding="utf-8")) == []


def test_throat_wiring_ast_lock_has_teeth() -> None:
    """注毒（纯内存，零落盘）：把两个写面对 `_throat_guard` 的调用改名绕过 —— 锁必须点名。"""
    real = SETTINGS_PY.read_text(encoding="utf-8")
    bypassed = real.replace("self._throat_guard(", "self._throat_bypassed_for_poison(")
    assert bypassed != real, "注毒替换未生效（源码形态已变）⇒ 本毒在空跑"
    violations = throat_wire_violations(bypassed)
    assert any("set_override" in problem for problem in violations), (
        f"绕过 set_override 的毒没被抓：{violations}"
    )
    assert any("reset_override" in problem for problem in violations), (
        f"绕过 reset_override 的毒没被抓：{violations}"
    )
    # 还原形态复绿：同一把尺量真源码仍然干净（证明红来自毒、不是阈值噪声）。
    assert throat_wire_violations(real) == []


# ===========================================================================
# 注毒自证（常驻在件，进程内 monkeypatch，零落盘）：把执法半边删掉 ⇒ 行为当场翻转；
# 还原 ⇒ 复绿。证明上面那些绿不是「断言恰好都落在旁路形态」上。
# ===========================================================================


def _r2_write_lands(store) -> bool:
    """一次 R2 写有没有**绕过同意直接落地**（True=绕过了，执法半边没了）。"""
    try:
        store.set_override(R2_SETTABLE_KEY, R2_VALUE, actor="qq:3865067623")
    except RuntimeChangeNeedsConsent:
        return False
    return store.list_overrides().get(R2_SETTABLE_KEY) is False


def test_poison_removing_enforcement_inverts_the_liveness_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 毒发 1：咽喉拦截器整体透明（等价于「接线被抹掉」）。
    monkeypatch.setattr(
        settings_mod.RuntimeSettingsStore, "_throat_guard",
        lambda self, **kw: kw["apply"](),
    )
    assert _r2_write_lands(_wired_store(tmp_path / "p1", enabled=True)), (
        "咽喉被抹平后 R2 写仍要票 ⇒ 上面的活性锁在测别的东西"
    )
    monkeypatch.undo()

    # 毒发 2：门体在（装配链照跑），但裁决函数透明（等价于「只装不执法」）。
    monkeypatch.setattr(
        SettingsWriteGate, "guarded_write", lambda self, **kw: kw["apply"]()
    )
    assert _r2_write_lands(_wired_store(tmp_path / "p2", enabled=True)), (
        "裁决被抹平后 R2 写仍要票 ⇒ 活性锁没测到 guarded_write 这一腿"
    )
    monkeypatch.undo()

    # 还原复绿：同一把尺、第三个 store、同一次写 ⇒ 又必须被拦（红来自毒，不是阈值噪声）。
    assert not _r2_write_lands(_wired_store(tmp_path / "p3", enabled=True)), (
        "还原后仍拦不住 ⇒ 本毒的归属不成立，前两条红另有原因"
    )
    monkeypatch.undo()

    # 还原复绿：同一判据在干净代码上必须回到「要票」形态（红来自毒，不是噪声）。
    assert not _r2_write_lands(_wired_store(tmp_path / "clean", enabled=True))


def test_master_switch_key_cannot_be_hot_set(tmp_path: Path) -> None:
    """总闸键自己在 RESTART_REQUIRED_KEYS：装配出的 store 对它的 `set` 当场拒绝——
    「用一条命令热关护栏」这条路今天不存在（护栏的本体不许被护栏要护的东西撬开）。"""
    assert "BOT_SAFETYEXEC_ENABLED" in settings_mod.RESTART_REQUIRED_KEYS
    store = _wired_store(tmp_path, enabled=True)
    with pytest.raises(ValueError) as refused:
        store.set_override("BOT_SAFETYEXEC_ENABLED", "false", actor="qq:3865067623")
    assert "不支持运行时热改" in str(refused.value)
    assert store.list_overrides() == {}
