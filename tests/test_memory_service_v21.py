"""V2.1 S8 记忆库管理服务回归（V21-MEM-001，合同 §9 Memory/Teaching 段）。

全部离线：tmp_path 隔离 SQLite、注入 fake clock、线程并发直驱；
零网络、零 NoneBot 运行时、零源码树写入。

覆盖面（对应任务书八项）：
- 生命周期：propose→pending→approve/reject 全流程；拒绝留痕（墓碑）
- 遗忘三处不复活：查询/注入/重建投影；遗忘顺序（墓碑先行，后续步骤
  失败仍不复活）
- 备份恢复重放墓碑；恢复后再重建仍不复活
- 跨用户隔离（A 的记忆 B 查不到）；无绑定跨平台不合并；显式绑定后合并
- TTL：过期不注入可审计（sweep 前排除 reason=ttl，sweep 后 forgotten）
- 注入预览与真实注入同源一致；预算裁剪 reason=budget
- 并发 propose 同 source_event_id 幂等（多线程单行合流）
- 类型红线：kind 枚举封闭，教导改人格/权限/路由在类型层不可表达
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.character.memory_service import (
    DEFAULT_INJECTION_BUDGET_CHARS,
    ExclusionReason,
    InjectionItem,
    MemoryConflictError,
    MemoryDraft,
    MemoryKind,
    MemoryNotFoundError,
    MemoryPermissionError,
    MemoryPrincipal,
    MemoryServiceV21,
    OwnerScope,
)
from plugins.bot_unified_runtime.character.memory_store_v21 import (
    MemoryStoreUnavailable,
    MemoryStoreV21,
)

# ---------------------------------------------------------------- 夹具


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)

    def advance(self, **kwargs: float) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now

    def __call__(self) -> datetime:
        return self.now


def make_service(tmp_path: Path, clock: FakeClock | None = None) -> tuple[MemoryServiceV21, FakeClock]:
    store = MemoryStoreV21(tmp_path / "memory_v21.sqlite3")
    fake = clock or FakeClock()
    return MemoryServiceV21(store, clock=fake), fake


ALICE_QQ = MemoryPrincipal(platform="qq", identity_key="10001")
ALICE_TG = MemoryPrincipal(platform="telegram", identity_key="10001")
BOB_QQ = MemoryPrincipal(platform="qq", identity_key="20002")
ADMIN = {"actor": "admin-1", "actor_role": "admin"}


def draft(
    principal: MemoryPrincipal = ALICE_QQ,
    *,
    text: str = "喜欢甜豆浆",
    kind: MemoryKind = MemoryKind.PREFERENCE,
    session_id: str = "session-1",
    confidence: float = 0.9,
    source: str = "teaching",
    **overrides: object,
) -> MemoryDraft:
    payload: dict[str, object] = {
        "principal": principal,
        "session_id": session_id,
        "kind": kind,
        "text": text,
        "confidence": confidence,
        "source": source,
    }
    payload.update(overrides)
    return MemoryDraft(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------- 生命周期


class TestLifecycle:
    def test_propose_private_rule_auto_approves_active(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft())
        assert record.status == "active"
        assert record.version == 1
        assert record.owner_id == "qq:10001"
        assert record.source == "teaching"

    def test_propose_low_confidence_goes_pending_then_admin_approve_bumps_version(
        self, tmp_path: Path
    ) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft(confidence=0.3))
        assert record.status == "pending_review"
        assert record.reviewed_by is None
        approved = service.approve(record.memory_id, **ADMIN)
        assert approved.status == "active"
        assert approved.version == 2
        assert approved.reviewed_by == "admin-1"
        assert approved.reviewed_at is not None

    def test_shared_knowledge_requires_admin_review(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft(owner_scope=OwnerScope.SHARED, confidence=0.99))
        assert record.owner_id == "shared"
        assert record.status == "pending_review"
        with pytest.raises(MemoryPermissionError):
            service.approve(record.memory_id, actor="alice", actor_role="user")
        approved = service.approve(record.memory_id, **ADMIN)
        assert approved.status == "active"

    def test_reject_leaves_tombstone_trace_and_never_injects(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft(confidence=0.3, text="不该记住的话"))
        tombstone = service.reject(record.memory_id, **ADMIN, reason="测试拒绝")
        assert tombstone.reason == "reject:测试拒绝"
        assert tombstone.original_version == 1
        # 拒绝后：行已 retired，普通查询面消失，审计面留痕
        assert service.query_records(ALICE_QQ, session_id="session-1") == []
        audit = service.audit_records(ALICE_QQ)
        assert [r.status for r in audit] == ["forgotten"]
        assert [t.memory_id for t in service.audit_tombstones(ALICE_QQ)] == [
            record.memory_id
        ]
        plan = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        assert plan.selected == []
        assert [e.reason for e in plan.excluded] == [ExclusionReason.TOMBSTONE]

    def test_reject_non_pending_conflict(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft())  # active
        with pytest.raises(MemoryConflictError):
            service.reject(record.memory_id, **ADMIN)

    def test_forget_unknown_id_raises(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        with pytest.raises(MemoryNotFoundError):
            service.forget("mem_missing", forgotten_by="admin-1")

    def test_double_forget_conflict(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft())
        service.forget(record.memory_id, forgotten_by="admin-1", actor_role="admin")
        with pytest.raises(MemoryConflictError):
            service.forget(record.memory_id, forgotten_by="admin-1", actor_role="admin")

    def test_touch_used_refreshes(self, tmp_path: Path) -> None:
        service, clock = make_service(tmp_path)
        record = service.propose(draft())
        assert record.used_at is None
        clock.advance(hours=2)
        assert service.touch_used(record.memory_id) is True
        refreshed = service.audit_records(ALICE_QQ)[0]
        assert refreshed.used_at is not None
        assert refreshed.used_at > refreshed.created_at


# ---------------------------------------------------------------- 遗忘三处不复活


class TestForgetNeverRevives:
    def test_forget_excludes_query_injection_and_rebuild(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft(text="要被遗忘的秘密"))
        tombstone = service.forget(
            record.memory_id, forgotten_by="admin-1", actor_role="admin"
        )
        assert tombstone.reason == "forget"
        assert service.query_records(ALICE_QQ, session_id="session-1") == []
        plan = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        assert plan.selected == []
        assert plan.rendered_text == ""
        service.rebuild_projection()
        assert service.query_records(ALICE_QQ, session_id="session-1") == []
        plan2 = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        assert plan2.selected == []
        assert service.audit_records(ALICE_QQ)[0].status == "forgotten"

    def test_forget_order_tombstone_first_survives_partial_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """墓碑提交后，即使清索引步骤崩溃，查询/注入仍排除（顺序保证）。"""
        service, _ = make_service(tmp_path)
        record = service.propose(draft())
        original_remove = service._store.remove_index_row

        def broken_remove(memory_id: str) -> None:
            raise MemoryStoreUnavailable("注入的清索引故障")

        monkeypatch.setattr(service._store, "remove_index_row", broken_remove)
        with pytest.raises(MemoryStoreUnavailable):
            service.forget(
                record.memory_id, forgotten_by="admin-1", actor_role="admin"
            )
        monkeypatch.setattr(service._store, "remove_index_row", original_remove)
        # 墓碑已提交 → SQL 查询层已排除；索引残留由 rebuild 收敛
        assert service._store.index_contains(record.memory_id) is True
        assert service.query_records(ALICE_QQ, session_id="session-1") == []
        plan = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        assert plan.selected == []
        assert {e.reason for e in plan.excluded} == {ExclusionReason.TOMBSTONE}

    def test_stale_cache_cannot_resurrect_tombstoned_memory(
        self, tmp_path: Path
    ) -> None:
        """行被翻回 active（模拟恢复/重导入复活）也抵不过墓碑：读路径排除。"""
        service, _ = make_service(tmp_path)
        record = service.propose(draft())
        service.build_injection_plan(ALICE_QQ, session_id="session-1")  # 热缓存
        service.forget(record.memory_id, forgotten_by="admin-1", actor_role="admin")
        # 绕过服务直接把活动行复活（模拟备份恢复/重导入带来的同 id active 行）
        flipped = service._store.update_entry(
            record.memory_id, fields={"status": "active"}
        )
        assert flipped is True
        assert service._store.has_tombstone(record.memory_id) is True
        # 查询面（SQL 墓碑排除）与注入面（读路径墓碑复核）都不复活
        assert service.query_records(ALICE_QQ, session_id="session-1") == []
        plan = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        assert all(item.memory_id != record.memory_id for item in plan.selected)
        assert {e.reason for e in plan.excluded} == {ExclusionReason.TOMBSTONE}
        # 重建投影后依然不复活
        service.rebuild_projection()
        assert service.query_records(ALICE_QQ, session_id="session-1") == []


# ---------------------------------------------------------------- 备份恢复


class TestBackupRestore:
    def test_restore_replays_tombstones_no_resurrection(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        service.propose(draft(text="幸存记忆"))
        doomed = service.propose(draft(text="被遗忘记忆", confidence=0.95))
        backup = tmp_path / "backup.sqlite3"
        service.backup_to(str(backup))
        service.forget(doomed.memory_id, forgotten_by="admin-1", actor_role="admin")
        # 恢复旧备份（其中 doomed 仍 active）
        replayed = service.restore_from(str(backup))
        assert replayed >= 1
        records = {r.text: r for r in service.query_records(ALICE_QQ, session_id="session-1")}
        assert "幸存记忆" in records
        assert "被遗忘记忆" not in records
        plan = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        assert [i.text for i in plan.selected] == ["幸存记忆"]
        # 恢复后再重建：依然不复活
        service.rebuild_projection()
        assert "被遗忘记忆" not in {
            r.text for r in service.query_records(ALICE_QQ, session_id="session-1")
        }
        audit = {r.text: r.status for r in service.audit_records(ALICE_QQ)}
        assert audit["被遗忘记忆"] == "forgotten"

    def test_restore_missing_backup_raises(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        with pytest.raises(FileNotFoundError):
            service.restore_from(str(tmp_path / "nope.sqlite3"))


# ---------------------------------------------------------------- 隔离与合并


class TestIsolationAndBinding:
    def test_cross_user_isolation(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        service.propose(draft(principal=ALICE_QQ, text="A 的私有偏好"))
        assert service.query_records(BOB_QQ, session_id="session-1") == []
        plan = service.build_injection_plan(BOB_QQ, session_id="session-1")
        assert plan.selected == []
        assert plan.owner_id == "qq:20002"
        # B 也无法按 ID 遗忘 A 的记忆：非本人且非管理员 → MemoryPermissionError
        # （遗忘是本人权利或管理员动作；管理员路径见生命周期组 actor_role=admin）。
        alice_record = service.query_records(ALICE_QQ, session_id="session-1")[0]
        with pytest.raises(MemoryPermissionError):
            service.forget(alice_record.memory_id, forgotten_by="bob")

    def test_forget_requires_owner_or_admin(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft(principal=ALICE_QQ))
        # 本人可遗忘自己的记忆
        tomb = service.forget(record.memory_id, forgotten_by="qq:10001")
        assert tomb.forgotten_by == "qq:10001"
        # 管理员可遗忘他人记忆
        second = service.propose(draft(principal=BOB_QQ, text="B 的记忆"))
        tomb2 = service.forget(
            second.memory_id, forgotten_by="admin-1", actor_role="admin"
        )
        assert tomb2.owner_id == "qq:20002"
        # 非管理员普通用户不能指定他人身份遗忘
        third = service.propose(draft(principal=ALICE_QQ, text="C 的记忆"))
        with pytest.raises(MemoryPermissionError):
            service.forget(third.memory_id, forgotten_by="qq:20002")

    def test_no_binding_means_no_cross_platform_merge(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        service.propose(draft(principal=ALICE_QQ, text="QQ 侧记忆"))
        assert service.query_records(ALICE_TG, session_id="session-1") == []
        assert service.resolve_owner(ALICE_TG) == "telegram:10001"

    def test_explicit_binding_merges_identities(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        service.propose(draft(principal=ALICE_QQ, text="QQ 侧记忆"))
        binding = service.bind_identities(ALICE_QQ, ALICE_TG, created_by="admin-1")
        assert binding.owner_id == "qq:10001"
        assert service.resolve_owner(ALICE_TG) == "qq:10001"
        merged = service.query_records(ALICE_TG, session_id="session-1")
        assert [r.text for r in merged] == ["QQ 侧记忆"]
        plan = service.build_injection_plan(ALICE_TG, session_id="session-1")
        assert [i.text for i in plan.selected] == ["QQ 侧记忆"]

    def test_binding_survives_restore(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        service.bind_identities(ALICE_QQ, ALICE_TG, created_by="admin-1")
        backup = tmp_path / "b.sqlite3"
        service.backup_to(str(backup))
        # 备份之后新建的绑定：恢复（整库替换）后不得丢失
        service.bind_identities(ALICE_TG, BOB_QQ, created_by="admin-1")
        service.restore_from(str(backup))
        assert service.resolve_owner(ALICE_TG) == "qq:10001"
        assert service.resolve_owner(BOB_QQ) == "qq:10001"

    def test_session_scope_forced(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        service.propose(draft(session_id="s1", text="会话私有"))
        assert service.query_records(ALICE_QQ, session_id="s2") == []
        service.propose(draft(session_id="global", text="全局记忆"))
        assert [r.text for r in service.query_records(ALICE_QQ, session_id="s2")] == [
            "全局记忆"
        ]


# ---------------------------------------------------------------- TTL


class TestTtl:
    def test_expired_excluded_from_injection_but_auditable(self, tmp_path: Path) -> None:
        service, clock = make_service(tmp_path)
        record = service.propose(draft(text="短命记忆", ttl_seconds=3600))
        assert record.expires_at is not None
        clock.advance(hours=2)
        plan = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        assert plan.selected == []
        reasons = {e.memory_id: e.reason for e in plan.excluded}
        assert reasons[record.memory_id] == ExclusionReason.TTL
        # sweep → forgotten-with-ttl（可审计，不注入）
        swept = service.sweep_expired()
        assert [t.reason for t in swept] == ["ttl"]
        assert service.audit_records(ALICE_QQ)[0].status == "forgotten"
        assert service.query_records(ALICE_QQ, session_id="session-1") == []

    def test_non_expired_still_injected(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft(text="仍在保质期", ttl_seconds=3600))
        plan = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        assert [i.memory_id for i in plan.selected] == [record.memory_id]

    def test_used_at_refresh_lifts_recency(self, tmp_path: Path) -> None:
        service, clock = make_service(tmp_path)
        old = service.propose(draft(text="老记忆", confidence=0.9))
        clock.advance(days=60)
        fresh = service.propose(draft(text="新记忆", confidence=0.9, source="manual"))
        plan = service.build_injection_plan(
            ALICE_QQ, session_id="session-1", refresh_used_at=False
        )
        scores = {i.memory_id: i.score for i in plan.selected}
        assert scores[fresh.memory_id] > scores[old.memory_id]
        # 触碰后 used_at 刷新 → recency 回升
        service.touch_used(old.memory_id)
        plan2 = service.build_injection_plan(
            ALICE_QQ, session_id="session-1", refresh_used_at=False
        )
        scores2 = {i.memory_id: i.score for i in plan2.selected}
        assert scores2[old.memory_id] > scores[old.memory_id]


# ---------------------------------------------------------------- 注入预览同源


class TestInjectionSameSource:
    def test_preview_equals_real_plan_except_used_at(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft(text="预览同源记忆"))
        assert service.audit_records(ALICE_QQ)[0].used_at is None
        preview = service.build_injection_preview(ALICE_QQ, session_id="session-1")
        # 预览不刷新 used_at（观察不改被观察物）
        assert service.audit_records(ALICE_QQ)[0].used_at is None
        real = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        # 同一函数产出：选中项/渲染文本/排除归因完全一致
        assert preview.selected == real.selected
        assert preview.rendered_text == real.rendered_text
        assert [e.reason for e in preview.excluded] == [
            e.reason for e in real.excluded
        ]
        assert isinstance(preview.selected[0], InjectionItem)
        assert preview.owner_id == real.owner_id == "qq:10001"
        assert preview.session_id == real.session_id
        # 真实注入刷新 used_at
        assert service.audit_records(ALICE_QQ)[0].memory_id == record.memory_id
        assert service.audit_records(ALICE_QQ)[0].used_at is not None

    def test_budget_clips_with_reason(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        # 首条 300 字（"高置信长记忆"×50），预算 302：装得下首条、装不下
        # 第二条（300 已用 + 1 分隔符 + 6 字 > 302）。
        first = service.propose(draft(text="高置信长记忆" * 50, confidence=0.99))
        second = service.propose(draft(text="低置信记忆", confidence=0.61))
        plan = service.build_injection_plan(
            ALICE_QQ, session_id="session-1", budget_chars=302
        )
        assert [i.memory_id for i in plan.selected] == [first.memory_id]
        clipped = {e.memory_id: e.reason for e in plan.excluded}
        assert clipped[second.memory_id] == ExclusionReason.BUDGET
        total = sum(len(i.text) for i in plan.selected)
        assert total <= 302 + len(plan.selected) - 1  # 分隔符容差

    def test_pending_and_proposal_kind_excluded(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        pending = service.propose(draft(confidence=0.2))
        # proposal 类记忆用抽取来源（draft() 默认 source=teaching 会撞教导红线）
        proposal = service.propose(
            draft(
                kind=MemoryKind.PROPOSAL,
                text="结构化提议",
                confidence=0.9,
                source="extraction",
            )
        )
        plan = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        reasons = {e.memory_id: e.reason for e in plan.excluded}
        assert reasons[pending.memory_id] == ExclusionReason.PENDING_REVIEW
        assert reasons[proposal.memory_id] == ExclusionReason.KIND_NOT_INJECTABLE

    def test_rendered_block_is_plain_lines(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        service.propose(draft(text="第一条"))
        service.propose(draft(text="第二条", confidence=0.95))
        plan = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        assert plan.rendered_text.splitlines()[0] == "【长期记忆】"
        assert all(line.startswith("- ") for line in plan.rendered_text.splitlines()[1:])
        assert DEFAULT_INJECTION_BUDGET_CHARS > 0

    def test_default_budget_constant_used(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        plan = service.build_injection_preview(ALICE_QQ, session_id="session-1")
        assert plan.budget_chars == DEFAULT_INJECTION_BUDGET_CHARS


# ---------------------------------------------------------------- 并发幂等


class TestConcurrentPropose:
    def test_same_source_event_id_converges_to_one_row(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        results: list[str] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                record = service.propose(
                    draft(
                        text="并发同源提议",
                        source="extraction",
                        source_event_id="evt-20260917-1",
                    )
                )
                with lock:
                    results.append(record.memory_id)
            except Exception as exc:  # noqa: BLE001 - 线程 worker 错误收集器，须全捕后集中断言
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert len(set(results)) == 1
        records = service.audit_records(ALICE_QQ)
        assert len(records) == 1

    def test_different_source_event_ids_are_distinct(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        first = service.propose(
            draft(source="extraction", source_event_id="evt-1")
        )
        second = service.propose(
            draft(source="extraction", source_event_id="evt-2")
        )
        assert first.memory_id != second.memory_id

    def test_blank_source_event_id_never_dedupes(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        first = service.propose(draft())
        again = service.propose(draft())
        assert again.memory_id != first.memory_id
        assert len(service.audit_records(ALICE_QQ)) == 2


# ---------------------------------------------------------------- 教导与类型红线


class TestTeachingGuard:
    def test_teaching_only_preference_fact(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        with pytest.raises(MemoryPermissionError):
            service.propose_teaching(
                ALICE_QQ,
                session_id="session-1",
                kind=MemoryKind.REFLECTION,
                text="试图教导反思",
                confidence=0.9,
            )
        record = service.propose_teaching(
            ALICE_QQ,
            session_id="session-1",
            kind=MemoryKind.FACT,
            text="用户在杭州工作",
            confidence=0.9,
            correction_of="mem_old",
            source_event_id="teach-1",
        )
        assert record.source == "teaching"
        assert record.correction_of == "mem_old"

    def test_kind_enum_closed_no_persona_permission_route(self) -> None:
        for forbidden in ("persona", "permission", "route", "admin", "system_prompt"):
            with pytest.raises(ValueError):
                MemoryKind(forbidden)
        assert {kind.value for kind in MemoryKind} == {
            "preference",
            "fact",
            "event",
            "reflection",
            "proposal",
        }

    def test_teaching_via_draft_also_guarded(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        with pytest.raises(MemoryPermissionError):
            service.propose(
                draft(kind=MemoryKind.EVENT, source="teaching", text="教导事件")
            )


# ---------------------------------------------------------------- DTO 严格性


class TestStrictDtos:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            MemoryDraft(
                principal=ALICE_QQ,
                session_id="s",
                kind=MemoryKind.FACT,
                text="x",
                confidence=0.5,
                system_prompt_override="注入企图",
            )

    def test_rejects_confidence_out_of_range_and_blank_text(self) -> None:
        with pytest.raises(ValidationError):
            draft(confidence=1.5)
        with pytest.raises(ValidationError):
            draft(text="  ")

    def test_rejects_blank_principal_and_bad_ttl(self) -> None:
        with pytest.raises(ValidationError):
            MemoryPrincipal(platform=" ", identity_key="u")
        with pytest.raises(ValidationError):
            draft(ttl_seconds=0)

    def test_plan_rejects_unknown_fields(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        plan = service.build_injection_preview(ALICE_QQ, session_id="session-1")
        with pytest.raises(ValidationError):
            plan.model_copy(update={"rogue_field": 1}).model_validate(
                    plan.model_dump() | {"rogue_field": 1}
                )


# ---------------------------------------------------------------- 重建等价


class TestRebuildEquivalence:
    def test_rebuild_preserves_query_surface(self, tmp_path: Path) -> None:
        """重建后查询面等价：同 id/文本/kind/状态/条数/顺序（V21-MEM-001）。"""
        service, clock = make_service(tmp_path)
        first = service.propose(draft(text="偏好一", source="manual"))
        clock.advance(minutes=1)
        second = service.propose(
            draft(kind=MemoryKind.FACT, text="事实二", confidence=0.95, source="manual")
        )
        clock.advance(minutes=1)
        third = service.propose(
            draft(
                kind=MemoryKind.REFLECTION,
                text="反思三",
                confidence=0.7,
                source="reflection",
                session_id="global",
            )
        )
        service.forget(second.memory_id, forgotten_by="qq:10001")

        def snapshot() -> list[tuple[str, str, str, str]]:
            return [
                (r.memory_id, r.text, r.kind, r.status)
                for r in service.query_records(ALICE_QQ, session_id="session-1")
            ] + [
                (r.memory_id, r.text, r.kind, r.status)
                for r in service.query_records(ALICE_QQ, session_id="other")
            ]

        before = snapshot()
        replayed = service.rebuild_projection()
        assert replayed == 1  # 一条墓碑被重放（second）
        assert snapshot() == before
        # 注入面同样等价
        plan_before = service.build_injection_preview(
            ALICE_QQ, session_id="session-1"
        )
        service.rebuild_projection()
        plan_after = service.build_injection_preview(
            ALICE_QQ, session_id="session-1"
        )
        assert plan_after.selected == plan_before.selected
        # session-1 视图 = 本会话行 + global 行（反思三），被遗忘的 second 不在
        assert [i.text for i in plan_after.selected] == ["偏好一", "反思三"]
        # 被遗忘的 second 在重建后审计面仍是 forgotten
        audit = {r.memory_id: r.status for r in service.audit_records(ALICE_QQ)}
        assert audit[second.memory_id] == "forgotten"
        assert audit[first.memory_id] == "active"
        assert audit[third.memory_id] == "active"

    def test_rebuild_idempotent(self, tmp_path: Path) -> None:
        service, _ = make_service(tmp_path)
        record = service.propose(draft(text="幂等重建"))
        service.rebuild_projection()
        service.rebuild_projection()
        assert [r.text for r in service.query_records(ALICE_QQ, session_id="session-1")] == [
            "幂等重建"
        ]
        assert service.query_records(ALICE_QQ, session_id="session-1")[0].memory_id == (
            record.memory_id
        )


# ---------------------------------------------------------------- 来源与字段


class TestSourceAndFields:
    def test_reflection_source_fields_complete_and_injectable(self, tmp_path: Path) -> None:
        """反思来源记忆：字段齐备（来源/置信度/时间/TTL）且可注入。"""
        service, _ = make_service(tmp_path)
        record = service.propose(
            draft(
                kind=MemoryKind.REFLECTION,
                text="夜间反思：用户偏好清晨工作",
                confidence=0.75,
                source="reflection",
                source_event_id="refl-20260917",
                ttl_seconds=90 * 24 * 3600,
            )
        )
        assert record.source == "reflection"
        assert record.confidence == 0.75
        assert record.created_at is not None
        assert record.expires_at is not None
        assert record.version == 1
        assert record.status == "active"
        plan = service.build_injection_plan(ALICE_QQ, session_id="session-1")
        assert [i.memory_id for i in plan.selected] == [record.memory_id]
        # 幂等：同 source_event_id 重放反思不产生第二行
        again = service.propose(
            draft(
                kind=MemoryKind.REFLECTION,
                text="夜间反思：用户偏好清晨工作",
                confidence=0.75,
                source="reflection",
                source_event_id="refl-20260917",
            )
        )
        assert again.memory_id == record.memory_id

    def test_sensitivity_reuses_legacy_vocabulary(self, tmp_path: Path) -> None:
        """sensitivity 口径沿用存量 memory.py 四值（真引用非 docstring 声明）。"""
        service, _ = make_service(tmp_path)
        for value in ("public", "group", "personal", "credentialed"):
            record = service.propose(draft(sensitivity=value))
            assert record.sensitivity == value
        assert len(service.audit_records(ALICE_QQ)) == 4
        with pytest.raises(ValidationError):
            draft(sensitivity="top_secret")
