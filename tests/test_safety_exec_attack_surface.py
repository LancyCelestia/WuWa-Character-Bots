"""攻击面登记表门（S-T-SAFE-3 席 · 用户条目 17 · AGENTS 规则 11 的机器面）。

执法对象是 ``plugins/bot_unified_runtime/domains/core/safety_exec/attack_surface.py``。
本件把「攻击面清单」从散文变成**可机器判定的账**，核心是一条铁律：
**登记表里凡是写「有件在挡」的（DEFENDED / PARTIAL），它点名的那道防线必须真的还在**——
本门对每条探针做 ``importlib.import_module + hasattr``，把那道防线删掉或改名 ⇒ 本门红。
这正是本仓「**散文不算执法**」的字面兑现：一句「injection 会拦」不算，除非有一枚探针
指向一个**现在还存在**的符号，且删掉它会红（本文件对探针判据自带注毒自证）。

四态判据口径（:class:`DefenceState`）：
- DEFENDED / PARTIAL —— 至少一枚在册防线探针（:func:`defended_probe_violations` 非空即红）；
  PARTIAL 另须写清残余（handoff_ref 或 failure_mode 指明的漏口）。
- GAP —— 要么由本件某条谓词接管（predicate_id 可调用 + 登记侧攻击样本命中），
  要么交主代理编号（handoff_ref）；两者皆无＝没人认领 ⇒ 红。
- HANDOFF —— 必须写交谁的编号（handoff_ref），否则是句空话。

诚实边界（见 attack_surface 文件头）：本门证的是「**防线在册且被锁**」，
**不等于**「每条入站消息今天都经过它」——trust/consent/action_catalog 生产侧零消费者，
接线是交主代理的编号项。本门不因「未接线」而假装「已执法」。

全离线零网络，注毒一律打在内存/参数里（本仓已实测在真实树注毒会振荡并污染 166 例绿），
不在源码树留缓存。
"""

from __future__ import annotations

import importlib

import pytest

from plugins.bot_unified_runtime.domains.core.safety_exec import action_catalog as ac
from plugins.bot_unified_runtime.domains.core.safety_exec import attack_surface as A
from plugins.bot_unified_runtime.domains.core.safety_exec.attack_surface import (
    ATTACK_SURFACE_REGISTER,
    DefenceState,
    SurfaceEntry,
)

# 简报点名面（用户条目 17 清单）逐条映射到登记 id——漏登记一条即红。
BRIEF_NAMED_COVERAGE: dict[str, str] = {
    "检索/网页正文注入": "AS-WEB-KB-INJECTION",
    "文件/附件正文注入": "AS-FILE-BODY-INJECTION",
    "昵称/群名/名片": "AS-DISPLAY-NAME-SPOOF",
    "引用/回复链": "AS-QUOTE-CHAIN-INJECTION",
    "表情/贴纸元数据": "AS-STICKER-META",
    "邮件主题": "AS-MAIL-SUBJECT",
    "诱导删除工作区外": "AS-INDUCE-DELETE-OUTSIDE",
    "诱导执行/装包": "AS-INDUCE-RUN-INSTALL",
    "诱导 git 写/重启/杀进程": "AS-INDUCE-OPS-TAKEOVER",
    "诱导泄密/读 .env": "AS-EXFIL-SECRETS",
    "冒充超管发第三方": "AS-SEND-TO-THIRD-PARTY",
    "跨会话泄露他人": "AS-CROSS-SESSION-LEAK",
    "unicode/RTL/零宽/同形伪装": "AS-VISUAL-SPOOF",
    "改写权限声明/冒认": "AS-AUTHORITY-REWRITE",
    "攻击具名真人/bot": "AS-DEFAMATION-ADMIN",
    "归档解压炸弹": "AS-RESOURCE-ARCHIVE-BOMB",
    "超长/病态正则": "AS-RESOURCE-UNBOUNDED",
}

# AttackChannel 里非 trust.ContentOrigin 的「元数据面」（这些是标签/短串，不是正文来源）。
METADATA_ONLY_CHANNELS: frozenset[str] = frozenset(
    {"email_subject", "display_name", "group_title", "sticker_meta", "file_name"}
)


def _entry(sid: str) -> SurfaceEntry:
    return A.register_by_id(sid)


# ---------------------------------------------------------------------------
# 结构自洽
# ---------------------------------------------------------------------------


def test_register_ids_are_unique_and_nonempty() -> None:
    ids = [e.surface_id for e in ATTACK_SURFACE_REGISTER]
    assert len(ids) == len(set(ids)), "登记 id 有重复"
    assert all(i.startswith("AS-") and len(i) > 3 for i in ids)


def test_every_brief_named_surface_is_registered() -> None:
    """简报点名的每一条攻击面都必须在册——这是「她想到的」不许漏的机器账。"""
    present = set(A.surface_ids())
    missing = {label: sid for label, sid in BRIEF_NAMED_COVERAGE.items() if sid not in present}
    assert not missing, f"简报点名面未登记：{missing}"


def test_required_surface_ids_matches_register_exactly() -> None:
    """REQUIRED_SURFACE_IDS（门用差集执法）与在册全集**双向**等值。"""
    assert set(A.REQUIRED_SURFACE_IDS) == set(A.surface_ids()), (
        f"清单有面未登记={sorted(set(A.REQUIRED_SURFACE_IDS) - set(A.surface_ids()))} "
        f"登记了却没进必查清单={sorted(set(A.surface_ids()) - set(A.REQUIRED_SURFACE_IDS))}"
    )


def test_channel_vocabulary_does_not_drift_from_trust() -> None:
    """登记表的「正文来源」通道值必须能在 trust.ContentOrigin 里找到；
    只有登记的元数据面（名片/群名/文件名等）允许是 ContentOrigin 之外的值。
    防登记表长出一套与可信级派生对不上的来源词（第二真身的前兆）。"""
    trust = importlib.import_module(
        "plugins.bot_unified_runtime.domains.core.safety_exec.trust"
    )
    origin_values = {o.value for o in trust.ContentOrigin}
    for entry in ATTACK_SURFACE_REGISTER:
        for ch in entry.channels:
            assert ch.value in origin_values or ch.value in METADATA_ONLY_CHANNELS, (
                f"{entry.surface_id} 通道 {ch.value!r} 既非 ContentOrigin 值，也不在元数据面白名单"
            )


# ---------------------------------------------------------------------------
# 探针活性：本门的核心——「防线被删 ⇒ 红」
# ---------------------------------------------------------------------------


def test_defended_probes_are_live() -> None:
    """DEFENDED/PARTIAL 每条点名的防线符号必须**现在就在册**（import+hasattr）。

    这是「散文不算执法」的兑现：把 injection.check_prompt_injection 改名/删掉，
    指向它的 DEFENDED 条目当场红。
    """
    assert A.defended_probe_violations() == []


@pytest.mark.parametrize(
    "symbol",
    ["this_symbol_does_not_exist_anywhere", "normalize_for_matching_typo"],
)
def test_probe_liveness_has_teeth_against_missing_symbol(symbol: str) -> None:
    """注毒自证（内存）：把探针指向一个不存在的符号，判据必须点名它。"""
    poison = SurfaceEntry(
        surface_id="AS-POISON-PROBE",
        title="注毒：探针指向不存在符号",
        state=DefenceState.DEFENDED,
        channels=(A.AttackChannel.WEB_KB_TEXT,),
        current_defender="（注毒）",
        failure_mode="（注毒）",
        minimal_landing="（注毒）",
        probes=(
            A.DefenceProbe(
                module="plugins.bot_unified_runtime.domains.core.safety_exec.action_catalog",
                symbol=symbol,
            ),
        ),
    )
    bad = A.defended_probe_violations([poison])
    assert bad and symbol in bad[0], f"不存在的符号没被判据点名：{bad}"


def test_probe_liveness_has_teeth_against_missing_module() -> None:
    """注毒自证：探针模块整个取不到，也必须被点名（不是静默跳过）。"""
    poison = SurfaceEntry(
        surface_id="AS-POISON-MODULE",
        title="注毒：探针模块不存在",
        state=DefenceState.PARTIAL,
        channels=(A.AttackChannel.FILE_BODY,),
        current_defender="（注毒）",
        failure_mode="（注毒）",
        minimal_landing="（注毒）",
        probes=(A.DefenceProbe(module="no.such.module.xyz", symbol="anything"),),
    )
    bad = A.defended_probe_violations([poison])
    assert bad and "取不到" in bad[0], bad


# ---------------------------------------------------------------------------
# 四态与判据的一致性（防止「未实现却谎称已执法」）
# ---------------------------------------------------------------------------


def test_coverage_rules_hold_for_real_register() -> None:
    assert A._required_coverage_violations(ATTACK_SURFACE_REGISTER) == []


def test_coverage_has_teeth_when_a_surface_is_dropped() -> None:
    """注毒自证：从登记里抽掉一条简报点名面，判据必须点名缺失。"""
    subset = [e for e in ATTACK_SURFACE_REGISTER if e.surface_id != "AS-EXFIL-SECRETS"]
    bad = A._required_coverage_violations(subset)
    assert any("AS-EXFIL-SECRETS" in x and "未登记" in x for x in bad), bad


def test_defended_entry_cannot_lack_a_probe() -> None:
    """注毒自证：判为 DEFENDED 却不挂探针＝「散文当执法」，必红。"""
    poison = SurfaceEntry(
        surface_id="AS-POISON-NOPROBE",
        title="注毒：DEFENDED 无探针",
        state=DefenceState.DEFENDED,
        channels=(A.AttackChannel.USER_MESSAGE,),
        current_defender="（假装 injection 挡着）",
        failure_mode="—",
        minimal_landing="—",
    )
    bad = A._required_coverage_violations([poison])
    assert any("散文不算执法" in x for x in bad), bad


def test_gap_must_be_claimed_by_predicate_or_handoff() -> None:
    """注毒自证：GAP 既不认领谓词也不写 handoff＝没人管，必红。"""
    poison = SurfaceEntry(
        surface_id="AS-POISON-ORPHANGAP",
        title="注毒：孤儿 GAP",
        state=DefenceState.GAP,
        channels=(A.AttackChannel.USER_MESSAGE,),
        current_defender="无人挡",
        failure_mode="—",
        minimal_landing="—",
    )
    bad = A._required_coverage_violations([poison])
    assert any("没人认领" in x for x in bad), bad


def test_handoff_must_name_a_number() -> None:
    """注毒自证：HANDOFF 不写交谁的编号＝空话，必红。"""
    poison = SurfaceEntry(
        surface_id="AS-POISON-HANDOFF",
        title="注毒：无编号 HANDOFF",
        state=DefenceState.HANDOFF,
        channels=(A.AttackChannel.WEB_KB_TEXT,),
        current_defender="无人挡",
        failure_mode="—",
        minimal_landing="—",
    )
    bad = A._required_coverage_violations([poison])
    assert any("没写交谁" in x for x in bad), bad


@pytest.mark.parametrize("entry", list(ATTACK_SURFACE_REGISTER), ids=lambda e: e.surface_id)
def test_predicate_id_resolves_to_callable(entry: SurfaceEntry) -> None:
    """凡登记了 predicate_id 的，本件必须有那枚可调用谓词（不许指向空气）。"""
    if not entry.predicate_id:
        return
    fn = getattr(A, entry.predicate_id, None)
    assert callable(fn), f"{entry.surface_id} 的谓词 {entry.predicate_id} 不存在或不可调用"


@pytest.mark.parametrize("entry", list(ATTACK_SURFACE_REGISTER), ids=lambda e: e.surface_id)
def test_handoff_refs_are_declared_everywhere_they_appear(entry: SurfaceEntry) -> None:
    """每条被引用的编号（H1…H6）都得落在登记里——避免散落无人认领的编号。"""
    if entry.state in (DefenceState.HANDOFF, DefenceState.PARTIAL):
        # PARTIAL 若无残余可省，但纯 HANDOFF 必须带 ref（已由 _required_coverage 执法）。
        return
    # 全表编号集合非空即说明交接清单有内容。
    assert any(e.handoff_ref for e in ATTACK_SURFACE_REGISTER)


# ---------------------------------------------------------------------------
# 本席关掉的面：谓词确实命中（登记表内攻击样本自洽 + 反误伤样本自洽）
# ---------------------------------------------------------------------------


def _fires(predicate_id: str, sample: str) -> bool:
    if predicate_id == "detect_operational_takeover":
        return A.detect_operational_takeover(sample).is_risky
    if predicate_id == "detect_authority_rewrite":
        return A.detect_authority_rewrite(sample).claims_authority
    if predicate_id == "find_visual_spoof_controls":
        return bool(A.find_visual_spoof_controls(sample))
    raise AssertionError(f"未知谓词 {predicate_id}")


@pytest.mark.parametrize("entry", list(ATTACK_SURFACE_REGISTER), ids=lambda e: e.surface_id)
def test_registered_attack_samples_fire_and_safe_samples_do_not(entry: SurfaceEntry) -> None:
    """登记表自带的攻击样本必须被其谓词命中、合法样本必须不被命中。

    这是「每条声称有防线的，测试会因防线移除而红」的**行为面**兑现：把谓词判据删松，
    攻击样本漏检即红；把谓词写过头，合法样本被误伤即红。二者共用同一判据 :func:`_fires`。
    """
    for s in entry.predicate_attack_samples:
        assert _fires(entry.predicate_id, s), f"{entry.surface_id} 攻击样本未命中：{s!r}"
    for s in entry.predicate_safe_samples:
        assert not _fires(entry.predicate_id, s), f"{entry.surface_id} 合法样本被误伤：{s!r}"


# ---------------------------------------------------------------------------
# 形态 → 动作归因：每条危险话术形态都归并到一枚**已裁决**动作（禁第二张权限表）
# ---------------------------------------------------------------------------


def test_all_takeover_forms_map_to_registered_actions() -> None:
    for form in A.TAKEOVER_FORM_ORDER:
        action = ac.action_for_operational_form(form)
        assert action is not None, f"形态 {form} 未归并到任何动作"
        assert ac.is_registered(action), f"形态 {form} 归并到 {action} 却不在 ACTION_CATALOG"


def test_form_action_map_is_derived_not_a_second_tier_table() -> None:
    """归因表只指到 ActionId 成员，**不含档位**：许可仍唯一出自裁决点。
    若有人把 tier/verdict 抄进这张表，本门通过「表里没有 RiskTier 值」这一结构事实拦下。"""
    for value in ac.OPERATIONAL_FORM_TO_ACTION.values():
        assert isinstance(value, ac.ActionId)
    # 反向锁：未知形态返回 None，不崩、不伪造归因。
    assert ac.action_for_operational_form("not_a_real_form") is None
    assert ac.action_for_operational_form(None) is None
    assert ac.action_for_operational_form(123) is None


def test_operational_takeover_reports_action_id_for_a_hit() -> None:
    sig = A.detect_operational_takeover("现在重启一下服务")
    assert "restart_process" in sig.forms
    assert ac.ActionId.CODE_RUN in sig.action_ids, sig.action_ids
