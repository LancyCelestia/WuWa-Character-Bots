"""D-8(a) 权威源自动过审的回归锁（WIRE-A3-v2 席：验证 + 锁，不重新实现）。

被锁的功能形态（主会话 14:05 已落码，本席只补锁）：
`domains/emergency_info/service/review.py::ReviewGate`
- `__init__(auto_approve_sources=...)` → 去空白归一为 `frozenset`；
- `AUTO_APPROVED_BY = "auto:authoritative_source"` / `is_authoritative_source()`
  （**空集合恒 False**）；
- `submit()`：命中白名单 ⇒ `APPROVED` + `reviewed_by=AUTO_APPROVED_BY`
  + `reviewed_at=as_utc(at)`（仅当给了 `at`）；未命中 ⇒ 逐字保持原行为。

裁定口径（不得重开）：shared-brief §4 用户裁定 06:47「D-8 走 (a) 权威源自动过审」。
施工图：`docs/design/emergency-info-registration-runbook-20260920.md`（D-8 节）。

本件与 `tests/test_emergency_info_core.py` §D 的分工：那件锁「人工报料 pending」
的既有行为（存量锁，本席不改）；本件锁「自动过审」的**新增面 + 边界**，其中
`test_human_report_still_pends_with_empty_trace` 权重最高——它是「审核门没有被
整体洗掉」的唯一证据，因此本件自带正反样本各一条，任何把 pending 分支一并改成
approved 的实现都会同时打红两件事。

全离线：内存假存储，零 SQLite / 零网络 / 零 LLM（conftest 源码树 `data/` 守卫）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
    as_utc,
    build_emergency_item,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.grading import grade
from plugins.bot_unified_runtime.domains.emergency_info.service.review import (
    ReviewGate,
)

_NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

#: 白名单来源（NMC 预警＝源侧已发布的权威告警，D-8(a) 的放行对象）。
#: **WP3 纠偏（审计 E6-N2）**：这里以前写的是 `"nmc_alarm"`——那是**模块名**，
#: 真身 `sources/nmc_alarm.py:SOURCE_ID` 是 `"nmc"`。旧夹具把「填错形态」当成了
#: 命中正例固化下来，等于给"静默不命中"这个事故背书；现在夹具用真身值，
#: 模块名形态改由 `test_module_name_style_value_is_named_and_dropped` 反向锁住。
_SOURCE_AUTO = "nmc"
#: 非白名单来源（人工报料通道，必须继续走 pending）
_SOURCE_HUMAN = "user_report"


def _item(**overrides: Any) -> EmergencyItem:
    """最小合法条目：标题自带「暴雨」+「橙色」两信号，定级必得 P1。"""
    payload: dict[str, Any] = {
        "item_id": "emg-gate-1",
        "source_id": _SOURCE_HUMAN,
        "source_kind": "manual",
        "external_id": "ext-001",
        "title": "某市气象台发布暴雨橙色预警信号",
        "body": "预计 6 小时内降雨量达 100 毫米以上。",
        "color_label": "橙色",
        "occurred_at": _NOW,
        "fetched_at": _NOW,
        "expires_at": _NOW + timedelta(hours=6),
        "credibility": 0.9,
    }
    payload.update(overrides)
    built = build_emergency_item(payload)
    assert built is not None, "测试夹具自身不合法，用例结论无意义"
    return built


class _FakeStore:
    """只实现 `ReviewStore` 最小面的内存假存储（同 core 件 §D 形态）。"""

    def __init__(self) -> None:
        self.rows: dict[str, EmergencyItem] = {}
        self.upserts: list[EmergencyItem] = []

    def upsert_item(self, item: EmergencyItem) -> bool:
        self.upserts.append(item)
        if item.item_id in self.rows:
            return False
        self.rows[item.item_id] = item
        return True

    def get(self, item_id: str) -> EmergencyItem | None:
        return self.rows.get(str(item_id or "").strip())

    def list_by_status(
        self, status: EmergencyStatus, *, limit: int = 50
    ) -> list[EmergencyItem]:
        rows = [row for row in self.rows.values() if row.status is status]
        return rows[: int(limit)]

    def apply_review(
        self,
        item_id: str,
        *,
        target: EmergencyStatus,
        reviewer_id: str,
        at: datetime,
    ) -> bool:
        row = self.rows.get(item_id)
        if row is None or row.status is not EmergencyStatus.PENDING:
            return False
        self.rows[item_id] = row.model_copy(
            update={"status": target, "reviewed_by": reviewer_id, "reviewed_at": at}
        )
        return True


def _gate(**kwargs: Any) -> tuple[ReviewGate, _FakeStore]:
    store = _FakeStore()
    return ReviewGate(store, **kwargs), store


def _auto_gate(**kwargs: Any) -> tuple[ReviewGate, _FakeStore]:
    kwargs.setdefault("auto_approve_sources", [_SOURCE_AUTO])
    return _gate(**kwargs)


# ------------------------------------------------- 锁 1｜白名单条目入库即过审


def test_authoritative_source_item_is_approved_on_submit() -> None:
    """D-8(a) 正面：白名单来源 `submit` 后即 `APPROVED`，痕迹是自动过审字面。"""
    gate, store = _auto_gate()
    approved = gate.submit(_item(source_id=_SOURCE_AUTO))
    assert approved.status is EmergencyStatus.APPROVED
    assert approved.reviewed_by == ReviewGate.AUTO_APPROVED_BY
    # 落库的必须是同一份（不是「返回体漂亮、库里另一份」）
    assert store.get(approved.item_id) == approved
    assert store.upserts == [approved]


def test_auto_approved_trace_is_a_literal_auditable_marker() -> None:
    """审核痕迹字面钉死：自动 ≠ 人工，审计时一眼可分，改名须过本锁。"""
    assert ReviewGate.AUTO_APPROVED_BY == "auto:authoritative_source"
    gate, _store = _auto_gate()
    auto = gate.submit(_item(item_id="a", source_id=_SOURCE_AUTO))
    human = gate.submit(_item(item_id="h", source_id=_SOURCE_HUMAN))
    assert auto.reviewed_by == ReviewGate.AUTO_APPROVED_BY
    assert human.reviewed_by == ""  # submit 当时不留任何人工痕迹
    assert auto.reviewed_by != human.reviewed_by
    # 人工裁决写入的是审核人 id，绝不会被自动痕迹冒充
    admin_gate, admin_store = _gate(authorizer=lambda reviewer: reviewer == "admin-1")
    pending = admin_gate.submit(_item(item_id="p", source_id=_SOURCE_HUMAN))
    outcome = admin_gate.approve(pending.item_id, reviewer_id="admin-1", at=_NOW)
    assert outcome.ok
    stored = admin_store.get("p")
    assert stored is not None
    assert stored.reviewed_by == "admin-1"
    assert stored.reviewed_by != ReviewGate.AUTO_APPROVED_BY
    assert stored.status is EmergencyStatus.APPROVED


def test_submit_stamps_reviewed_at_only_when_clock_given() -> None:
    """`reviewed_at` 口径：给了 `at` 才写（且经 `as_utc` 归一），没给就 None。"""
    gate, _store = _auto_gate()
    naive = datetime(2026, 9, 19, 4, 0)  # noqa: DTZ001 - 专造 naive 输入验 UTC 归一
    stamped = gate.submit(_item(source_id=_SOURCE_AUTO), at=naive)
    assert stamped.reviewed_at == as_utc(naive)
    assert stamped.reviewed_at is not None
    assert stamped.reviewed_at.tzinfo is not None
    unstamped = gate.submit(_item(item_id="emg-gate-2", source_id=_SOURCE_AUTO))
    assert unstamped.status is EmergencyStatus.APPROVED
    assert unstamped.reviewed_at is None


# ------------------------------------- 锁 2｜人工报料负样本（权重最高：门没被洗掉）


def test_human_report_still_pends_with_empty_trace() -> None:
    """非白名单来源：仍 `PENDING` + `reviewed_by == ""` + `reviewed_at is None`。

    「审核门没有被整体洗掉」的唯一证据。任何把 pending 分支改成自动过审的实现
    都会在此打红，并同时使 `test_authoritative_source_item_is_approved_on_submit`
    失去判别力（正反样本同件共存）。
    """
    gate, store = _auto_gate()
    human = gate.submit(_item(source_id=_SOURCE_HUMAN))
    assert human.status is EmergencyStatus.PENDING
    assert human.reviewed_by == ""
    assert human.reviewed_at is None
    assert human.level is None
    assert store.get(human.item_id) == human
    # 投递面判据同样未松动：未过审 ⇒ 不可投递、不可定级
    assert ReviewGate.publishable(human) is False
    assert ReviewGate.publishable_level(human, now=_NOW) is None


def test_whitelist_only_affects_listed_sources_and_keeps_queue_hygiene() -> None:
    """同批混投：白名单条目出 pending 队列，人工条目留在队列（审核面一寸未松）。"""
    gate, _store = _auto_gate()
    auto = gate.submit(_item(item_id="auto-1", source_id=_SOURCE_AUTO))
    human = gate.submit(_item(item_id="human-1", source_id=_SOURCE_HUMAN))
    pending_ids = {row.item_id for row in gate.pending_items()}
    assert pending_ids == {human.item_id}
    assert auto.status is EmergencyStatus.APPROVED
    assert human.status is EmergencyStatus.PENDING
    # 近似名不等于命中（白名单是精确集合，不做前缀/子串匹配）
    near = gate.submit(_item(item_id="near-1", source_id="nmc_alarm_v2"))
    assert near.status is EmergencyStatus.PENDING


# ----------------------------------------------------------- 锁 3｜缺省关闭


@pytest.mark.parametrize(
    "sources",
    [None, frozenset(), [], ["", "  ", "\t"]],
    ids=["unset", "empty-frozenset", "empty-list", "blanks-only"],
)
def test_auto_approval_is_off_by_default(sources: Any) -> None:
    """不传 / 传空 / 只含空白 ⇒ 一切照旧 pending（缺省=功能关闭，与「白名单空
    绝不猜群」同向）。"""
    kwargs: dict[str, Any] = {}
    if sources is not None:
        kwargs["auto_approve_sources"] = sources
    gate, _store = _gate(**kwargs)
    assert gate.is_authoritative_source(_SOURCE_AUTO) is False
    assert gate.is_authoritative_source("") is False
    submitted = gate.submit(_item(source_id=_SOURCE_AUTO))
    assert submitted.status is EmergencyStatus.PENDING
    assert submitted.reviewed_by == ""
    assert submitted.reviewed_at is None


def test_blank_source_never_auto_approves_even_with_blank_only_list() -> None:
    """空白归一化必须**过滤**空串：否则 `""` 会进集合、让无来源条目白拿过审。"""
    gate, _store = _gate(auto_approve_sources=["   ", "", "\t"])
    assert gate.is_authoritative_source("") is False
    assert gate.is_authoritative_source("   ") is False
    assert gate.is_authoritative_source("nmc_alarm") is False


# ------------------------------- 锁 4｜自动过审 ≠ 提前定级（投递面仍只一条路）


def test_auto_approval_does_not_pregrade_but_still_grades_through_the_only_gate() -> None:
    """过审条目身上 `level is None`，但 `publishable_level()` 照常给出等级。

    D-8 的结构性保证：自动过审只解开「状态」这道门，**不**把现成等级塞进
    投递面；定级唯一出口仍是 `publishable_level()`，没有第二条路。
    """
    gate, _store = _auto_gate()
    seeded = gate.submit(
        _item(
            item_id="emg-gate-seed", source_id=_SOURCE_AUTO, level=EmergencyLevel.P0
        ),
        at=_NOW,
    )
    assert seeded.level is None  # 采集侧预置的 P0 也带不进投递面
    auto = gate.submit(_item(source_id=_SOURCE_AUTO), at=_NOW)
    assert auto.level is None
    assert auto.is_urgent is False  # 未定级就不自称紧急
    assert auto.color_text == ""
    # 唯一串联点照常工作：过审 ⇒ 有等级
    level = ReviewGate.publishable_level(auto, now=_NOW)
    assert level is EmergencyLevel.P1
    assert level == grade(auto, now=_NOW)
    # 同一条目若没过审（人工报料同标题同色），这个出口必须给 None
    human = gate.submit(_item(item_id="emg-gate-9", source_id=_SOURCE_HUMAN))
    assert ReviewGate.publishable_level(human, now=_NOW) is None


# --------------------------- 锁 5｜调用方传什么都不算（伪造 status/level 被钉回）


def test_caller_supplied_status_and_level_are_pinned_away() -> None:
    """白名单条目伪造 `status=REJECTED` + `level=P0` 进 `submit`：
    产出仍是 `APPROVED` + `level=None` + 痕迹 `AUTO_APPROVED_BY`。"""
    gate, store = _auto_gate()
    forged = _item(
        source_id=_SOURCE_AUTO,
        status=EmergencyStatus.REJECTED,
        level=EmergencyLevel.P0,
        reviewed_by="somebody",
        reviewed_at=_NOW - timedelta(days=1),
    )
    out = gate.submit(forged, at=_NOW)
    assert out.status is EmergencyStatus.APPROVED
    assert out.level is None
    assert out.reviewed_by == ReviewGate.AUTO_APPROVED_BY
    assert out.reviewed_at == as_utc(_NOW)
    assert store.get(out.item_id) == out
    stored = store.get(out.item_id)
    assert stored is not None
    assert stored.status is EmergencyStatus.APPROVED


def test_forged_fields_are_pinned_away_for_human_reports_too() -> None:
    """反面同构：人工报料伪造 `APPROVED` + `P0` 也照样被钉回 pending。

    这条与上一条成对——证明「钉回」不是「白名单特权」，调用方永远说了不算。
    """
    gate, _store = _auto_gate()
    forged = _item(
        source_id=_SOURCE_HUMAN,
        status=EmergencyStatus.APPROVED,
        level=EmergencyLevel.P0,
        reviewed_by="self-appointed",
        reviewed_at=_NOW,
    )
    out = gate.submit(forged, at=_NOW)
    assert out.status is EmergencyStatus.PENDING
    assert out.level is None
    assert out.reviewed_by == ""
    assert out.reviewed_at is None
    assert ReviewGate.publishable(out) is False


# ------------------------------------------------- 锁 6｜名单空白归一化（不静默失效）


def test_whitespace_in_whitelist_still_matches_clean_source_id() -> None:
    """名单写 `" nmc "`、条目 `source_id="nmc"` ⇒ 命中。

    配管里手打的空白不得让白名单静默失效（缺省关闭是对的，但「配了却不生效」
    是另一种故障：运维会以为已经开了）。
    WP3 纠偏：正例从旧夹具的模块名 `nmc_alarm` 改回真身 SOURCE_ID（见文件头注）。
    """
    gate, _store = _gate(auto_approve_sources=["  nmc  ", "\tgdacs\t"])
    assert gate.is_authoritative_source(_SOURCE_AUTO) is True
    assert gate.is_authoritative_source("gdacs") is True
    assert gate.is_authoritative_source("icl") is False
    out = gate.submit(_item(source_id=_SOURCE_AUTO), at=_NOW)
    assert out.status is EmergencyStatus.APPROVED
    assert out.reviewed_by == ReviewGate.AUTO_APPROVED_BY


def test_frozenset_and_list_inputs_behave_identically() -> None:
    """`frozenset` 与 `list` 两种入参形态语义一致（装配期从 config 的 list 直灌）。"""
    by_list, _ = _gate(auto_approve_sources=[_SOURCE_AUTO])
    by_frozenset, _ = _gate(auto_approve_sources=frozenset({_SOURCE_AUTO}))
    assert by_list.is_authoritative_source(_SOURCE_AUTO) is True
    assert by_frozenset.is_authoritative_source(_SOURCE_AUTO) is True
    assert by_list.is_authoritative_source("usgs") is False
    assert by_frozenset.is_authoritative_source("usgs") is False
    a = by_list.submit(_item(source_id=_SOURCE_AUTO))
    b = by_frozenset.submit(_item(source_id=_SOURCE_AUTO))
    assert a.status is b.status is EmergencyStatus.APPROVED
    assert a.reviewed_by == b.reviewed_by == ReviewGate.AUTO_APPROVED_BY


# ---------------------- 锁 7（现状记录，非裁定）｜自动过审后人工撤回仍无路可走


def test_auto_approved_item_cannot_be_revoked_by_a_human_yet() -> None:
    """诚实记录现状：approved 是终态，自动过审的错放条目**没有**人工撤回通道。

    这不是本席引入的缺陷（`contracts._ALLOWED_TRANSITIONS` 里 APPROVED/REJECTED
    的出边本就是空集，见 contracts.py:142-150），但 D-8(a) 之后它从「人工才会踩」
    变成「机器批量可能踩」，风险面被放大 ⇒ 本锁钉死现状，撤销通道另案裁定。
    """
    gate, _store = _gate(
        authorizer=lambda reviewer: reviewer == "admin-1",
        auto_approve_sources=[_SOURCE_AUTO],
    )
    auto = gate.submit(_item(source_id=_SOURCE_AUTO), at=_NOW)
    refused = gate.reject(
        auto.item_id, reviewer_id="admin-1", at=_NOW, reason="误放"
    )
    assert refused.ok is False
    assert refused.reason == "illegal_transition"
    assert refused.status is EmergencyStatus.APPROVED
    # 同一条存储面：人工报料被驳回后也没有「重开」通道（状态机同源，未松动）
    human = gate.submit(_item(item_id="emg-gate-3", source_id=_SOURCE_HUMAN))
    assert gate.reject(human.item_id, reviewer_id="admin-1", at=_NOW).ok is True
    reopened = gate.approve(human.item_id, reviewer_id="admin-1", at=_NOW)
    assert reopened.ok is False
    assert reopened.reason == "illegal_transition"


def test_auto_approval_leaves_authorizer_requirement_untouched() -> None:
    """自动过审不吞 authorizer 门：未注入 authorizer 时人工裁决仍一律拒绝。

    （本席对「是否绕过不可绕过的守卫」的取证结论：submit 的自动过审以
    「装配期注入名单」为权限来源，`_decide` 的人工授权链一寸未改。）
    """
    gate, _store = _auto_gate()  # 故意不传 authorizer
    outcome = gate.approve("whatever", reviewer_id="admin-1", at=_NOW)
    assert outcome.ok is False
    assert outcome.reason == "authorizer_not_configured"
    assert gate.submit(_item(item_id="emg-gate-4")).status is (
        EmergencyStatus.PENDING
    )


# ---- 锁 8｜装配注入同源（WIRE-L2）：快照搬运名单 + build_review_gate 双门 +
#      服务内联缺省闸不再是第二套裸缺省（D-8(a) 生产真生效的行为面锁；
#      「根装配确实调了它」的可达性面锁在 tests/test_emergency_info_reachability.py）


_CAP_MODULE = (
    "plugins.bot_unified_runtime.domains.emergency_info.capabilities.emergency_info"
)


def _cap_source(**overrides: Any) -> Any:
    """装配期快照真身：喂假 config，走 `build_emergency_info_source` 的按名读取。"""
    import importlib
    from types import SimpleNamespace

    module = importlib.import_module(_CAP_MODULE)
    data: dict[str, Any] = {
        "bot_emergency_info_enabled": True,
        "bot_emergency_info_sources": [_SOURCE_AUTO, _SOURCE_HUMAN],
        "bot_emergency_info_auto_approve_sources": [_SOURCE_AUTO],
        "bot_emergency_info_push_group_whitelist": ["g-1"],
        "bot_emergency_info_push_user_ids": [],
        "bot_emergency_info_reviewer_ids": ["admin-1"],
        "bot_emergency_info_min_level": "P2",
        "bot_emergency_info_poll_interval_seconds": 300,
        "bot_emergency_info_keep_days": 90,
        "bot_emergency_info_db_path": "",
        "bot_persona_profile_id": "default",
    }
    data.update(overrides)
    return module.build_emergency_info_source(SimpleNamespace(**data))


def test_snapshot_carries_auto_approve_list_into_frozen_fields() -> None:
    """快照搬运权威源名单（缺省语义不许变：空名单 ⇒ frozenset() ⇒ 一切照旧）。"""
    source = _cap_source()
    assert source.auto_approve_sources == frozenset({_SOURCE_AUTO})
    empty = _cap_source(bot_emergency_info_auto_approve_sources=[])
    assert empty.auto_approve_sources == frozenset()


def test_build_review_gate_carries_both_knobs_from_the_snapshot() -> None:
    """双门同源：白名单源入库即 APPROVED；authorizer 认 reviewer_ids 名单。"""
    import importlib

    module = importlib.import_module(_CAP_MODULE)
    store = _FakeStore()
    gate = module.build_review_gate(store, _cap_source())
    auto = gate.submit(_item(item_id="w-1", source_id=_SOURCE_AUTO), at=_NOW)
    assert auto.status is EmergencyStatus.APPROVED
    assert auto.reviewed_by == ReviewGate.AUTO_APPROVED_BY
    human = gate.submit(_item(item_id="w-2", source_id=_SOURCE_HUMAN), at=_NOW)
    assert human.status is EmergencyStatus.PENDING
    assert human.reviewed_by == ""
    ok = gate.approve(human.item_id, reviewer_id="admin-1", at=_NOW)
    assert ok.ok is True
    refused = gate.approve(human.item_id, reviewer_id="stranger", at=_NOW)
    assert (refused.ok, refused.reason) == (False, "reviewer_not_authorized")


def test_build_review_gate_with_empty_reviewer_list_rejects_everyone() -> None:
    """reviewer_ids 空 ⇒ authorizer 对任何人一律 False（人工门一寸不松）。"""
    import importlib

    module = importlib.import_module(_CAP_MODULE)
    source = _cap_source(bot_emergency_info_reviewer_ids=[])
    gate = module.build_review_gate(_FakeStore(), source)
    human = gate.submit(_item(item_id="w-3", source_id=_SOURCE_HUMAN), at=_NOW)
    assert human.status is EmergencyStatus.PENDING
    outcome = gate.approve(human.item_id, reviewer_id="admin-1", at=_NOW)
    assert outcome.ok is False
    assert outcome.reason in {"reviewer_not_authorized", "authorizer_not_configured"}


def test_service_inline_default_is_same_origin_as_snapshot() -> None:
    """高危「第二套缺省」根修：服务未显式注入 review_gate 时，缺省闸同样来自快照
    双门（名单命中即 APPROVED），而不是无名单的裸 `ReviewGate(store)`。"""
    import importlib

    module = importlib.import_module(_CAP_MODULE)
    store = _FakeStore()
    service = module.EmergencyInfoService(
        store=store, source=_cap_source(), gate=object()
    )
    auto = service.review_gate.submit(
        _item(item_id="w-4", source_id=_SOURCE_AUTO), at=_NOW
    )
    assert auto.status is EmergencyStatus.APPROVED
    assert store.get("w-4").reviewed_by == ReviewGate.AUTO_APPROVED_BY
    human = service.review_gate.submit(
        _item(item_id="w-5", source_id=_SOURCE_HUMAN), at=_NOW
    )
    assert human.status is EmergencyStatus.PENDING
