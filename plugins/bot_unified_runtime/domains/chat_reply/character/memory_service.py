"""V2.1 记忆库管理服务（MemoryServiceV21，V21-MEM-001）。

重建说明（2026-09-18）：原文件在板块归类事故中被垫片覆写，本文件依据
tests/test_memory_service_v21.py（41 例契约）+ docs/design/v21r2-v2-memory-log.md
设计要点重建。语义红线：
- 遗忘/拒绝=墓碑先行，行翻 forgotten，读路径 SQL+复核双排除，永不复活
- 注入预览与真实注入同源（同一构建函数，仅 used_at 刷新行为不同）
- 教导来源只允许 FACT 类（人格/权限/路由在类型层不可表达）
- DTO 封闭（extra=forbid），sensitivity 沿用存量四值词表
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
    MemoryStoreUnavailable,
    MemoryStoreV21,
)

DEFAULT_INJECTION_BUDGET_CHARS = 1200
AUTO_APPROVE_CONFIDENCE = 0.5
_RECENCY_HALF_LIFE_DAYS = 30.0


class MemoryKind(str, Enum):
    """封闭枚举：人格/权限/路由类记忆在类型层不可表达（教导红线）。"""

    PREFERENCE = "preference"
    FACT = "fact"
    EVENT = "event"
    REFLECTION = "reflection"
    PROPOSAL = "proposal"


class OwnerScope(str, Enum):
    PERSONAL = "personal"
    SHARED = "shared"


class ExclusionReason(str, Enum):
    TOMBSTONE = "tombstone"
    TTL = "ttl"
    BUDGET = "budget"
    PENDING_REVIEW = "pending_review"
    KIND_NOT_INJECTABLE = "kind_not_injectable"


_SENSITIVITY_VALUES = ("public", "group", "personal", "credentialed")


class MemoryNotFoundError(LookupError):
    pass


class MemoryPermissionError(PermissionError):
    pass


class MemoryConflictError(RuntimeError):
    pass


class MemoryPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)

    @field_validator("platform", "identity_key")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("platform/identity_key 不能为空白")
        return value

    @property
    def owner_id(self) -> str:
        return f"{self.platform}:{self.identity_key}"

    @property
    def binding_key(self) -> str:
        return self.owner_id


class MemoryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal: MemoryPrincipal
    session_id: str = Field(min_length=1)
    kind: MemoryKind
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1)
    owner_scope: OwnerScope = OwnerScope.PERSONAL
    sensitivity: str = "personal"
    ttl_seconds: int | None = Field(default=None, gt=0)
    source_event_id: str = ""
    correction_of: str | None = None

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text 不能为空白")
        return value

    @field_validator("sensitivity")
    @classmethod
    def _sensitivity_known(cls, value: str) -> str:
        if value not in _SENSITIVITY_VALUES:
            raise ValueError(f"未知 sensitivity: {value}")
        return value


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: str
    owner_id: str
    session_id: str
    kind: MemoryKind
    status: str
    version: int
    text: str
    confidence: float
    sensitivity: str
    source: str
    source_event_id: str = ""
    correction_of: str | None = None
    ttl_seconds: int | None = None
    expires_at: str | None = None
    created_at: str
    updated_at: str
    used_at: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    # ---- v2 总线列（WP6）：全部带缺省，旧行/旧写入路径读出来即缺省值 ----
    # 这里必须同步扩字段：_record_from 走 `SELECT *`，表加列而 DTO 不加=老服务
    # 直接 ValidationError（extra="forbid"）。加列不加语义，缺省=「一条都没见过」。
    provenance: str = "explicit"
    confirm_count: int = 1
    contradict_count: int = 0
    first_seen_at: str = ""
    last_confirmed_at: str = ""
    scope_kind: str = "global"
    scope_key: str = ""
    supersedes: str = ""
    decay_class: str = "slow"
    slot_key: str = ""
    polarity: str = ""


class MemoryTombstone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: str
    owner_id: str
    reason: str
    original_version: int
    forgotten_by: str
    created_at: str


class IdentityBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: str
    created_by: str
    created_at: str


class InjectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: str
    text: str
    score: float


class InjectionExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: str
    reason: ExclusionReason


class InjectionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: str
    session_id: str
    budget_chars: int
    selected: list[InjectionItem]
    excluded: list[InjectionExclusion]
    rendered_text: str


def _utc_now() -> datetime:
    """默认时钟：UTC aware（与测试 FakeClock 同口径）；测试可注入固定时钟。"""
    return datetime.now(timezone.utc)


def _iso_now(clock: Callable[[], datetime]) -> str:
    return clock().isoformat(timespec="microseconds")


def _recency_score(moment: str | None, now: datetime) -> float:
    """used_at（缺省 created_at）起算的半衰衰减：30 天半衰。"""
    if not moment:
        return 0.25
    try:
        then = datetime.fromisoformat(str(moment))
    except ValueError:
        return 0.25
    age_days = max(0.0, (now - then).total_seconds()) / 86400.0
    return math.pow(0.5, age_days / _RECENCY_HALF_LIFE_DAYS)


class MemoryServiceV21:
    """记忆生命周期 + 注入计划 + 备份恢复 + 重建投影（同源同库）。"""

    def __init__(
        self,
        store: MemoryStoreV21,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or _utc_now

    # ---------------------------------------------------------------- 内部

    def _record_from(self, entry: dict[str, Any]) -> MemoryRecord:
        return MemoryRecord(**entry)

    def _now_iso(self) -> str:
        return _iso_now(self._clock)

    def _resolve_owner(self, principal: MemoryPrincipal) -> str:
        return self._store.resolve_binding(principal.binding_key) or principal.owner_id

    def _entry_or_raise(self, memory_id: str) -> dict[str, Any]:
        entry = self._store.get_entry(memory_id)
        if entry is None:
            raise MemoryNotFoundError(f"记忆不存在: {memory_id}")
        return entry

    # ---------------------------------------------------------------- 提交

    def propose(self, draft_obj: MemoryDraft) -> MemoryRecord:
        if draft_obj.source == "teaching" and draft_obj.kind not in (
            MemoryKind.PREFERENCE,
            MemoryKind.FACT,
        ):
            raise MemoryPermissionError(
                "教导来源只允许偏好/事实类记忆（人格/权限/路由/反思不可教导）"
            )
        owner_id = (
            "shared"
            if draft_obj.owner_scope == OwnerScope.SHARED
            else self._resolve_owner(draft_obj.principal)
        )
        now_iso = self._now_iso()
        expires_at = (
            (self._clock() + timedelta(seconds=draft_obj.ttl_seconds)).isoformat(
                timespec="microseconds"
            )
            if draft_obj.ttl_seconds is not None
            else None
        )
        auto_active = (
            draft_obj.confidence >= AUTO_APPROVE_CONFIDENCE
            and draft_obj.owner_scope != OwnerScope.SHARED
        )
        status = "active" if auto_active else "pending_review"
        entry: dict[str, Any] = {
            "memory_id": f"mem_{_entity_token()}",
            "owner_id": owner_id,
            "session_id": draft_obj.session_id,
            "kind": draft_obj.kind.value,
            "status": status,
            "version": 1,
            "text": draft_obj.text,
            "confidence": draft_obj.confidence,
            "sensitivity": draft_obj.sensitivity,
            "source": draft_obj.source,
            "source_event_id": draft_obj.source_event_id or "",
            "correction_of": draft_obj.correction_of,
            "ttl_seconds": draft_obj.ttl_seconds,
            "expires_at": expires_at,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        existing_id = self._store.insert_entry(entry)
        if existing_id is not None:
            stored = self._store.get_entry(existing_id)
            assert stored is not None
            return self._record_from(stored)
        return self._record_from(entry)

    def propose_teaching(
        self,
        principal: MemoryPrincipal,
        *,
        session_id: str,
        kind: MemoryKind,
        text: str,
        confidence: float,
        correction_of: str | None = None,
        source_event_id: str = "",
        sensitivity: str = "personal",
    ) -> MemoryRecord:
        return self.propose(
            MemoryDraft(
                principal=principal,
                session_id=session_id,
                kind=kind,
                text=text,
                confidence=confidence,
                source="teaching",
                sensitivity=sensitivity,
                correction_of=correction_of,
                source_event_id=source_event_id,
            )
        )

    def approve(self, memory_id: str, *, actor: str, actor_role: str) -> MemoryRecord:
        if actor_role != "admin":
            raise MemoryPermissionError("批准需要管理员角色")
        entry = self._entry_or_raise(memory_id)
        if entry["status"] != "pending_review":
            raise MemoryConflictError(f"记忆当前状态 {entry['status']} 不可批准")
        reviewed_at = self._now_iso()
        self._store.update_entry(
            memory_id,
            {
                "status": "active",
                "version": int(entry["version"]) + 1,
                "reviewed_by": actor,
                "reviewed_at": reviewed_at,
                "updated_at": reviewed_at,
            },
        )
        stored = self._store.get_entry(memory_id)
        assert stored is not None
        return self._record_from(stored)

    def reject(
        self, memory_id: str, *, actor: str, actor_role: str, reason: str = ""
    ) -> MemoryTombstone:
        if actor_role != "admin":
            raise MemoryPermissionError("拒绝需要管理员角色")
        entry = self._entry_or_raise(memory_id)
        if entry["status"] != "pending_review":
            raise MemoryConflictError(f"记忆当前状态 {entry['status']} 不可拒绝")
        return self._bury(
            entry,
            reason=f"reject:{reason}",
            forgotten_by=actor,
        )

    def forget(
        self,
        memory_id: str,
        *,
        forgotten_by: str,
        actor_role: str = "user",
    ) -> MemoryTombstone:
        entry = self._store.get_entry(memory_id)
        if entry is None:
            raise MemoryNotFoundError(f"记忆不存在: {memory_id}")
        if entry["status"] == "forgotten" or self._store.has_tombstone(memory_id):
            raise MemoryConflictError("该记忆已被遗忘")
        if forgotten_by != entry["owner_id"] and actor_role != "admin":
            raise MemoryPermissionError("只能遗忘本人记忆（管理员可代为遗忘）")
        return self._bury(entry, reason="forget", forgotten_by=forgotten_by)

    def _bury(
        self, entry: dict[str, Any], *, reason: str, forgotten_by: str
    ) -> MemoryTombstone:
        # 顺序红线：墓碑先提交（读路径 SQL 层即排除），后续清索引失败只留
        # 投影残渣由 rebuild 收敛——任何一步失败都不复活。
        now_iso = self._now_iso()
        tombstone = MemoryTombstone(
            memory_id=entry["memory_id"],
            owner_id=entry["owner_id"],
            reason=reason,
            original_version=int(entry["version"]),
            forgotten_by=forgotten_by,
            created_at=now_iso,
        )
        self._store.insert_tombstone(tombstone.model_dump())
        try:
            self._store.remove_index_row(entry["memory_id"])
        except Exception as exc:
            if isinstance(exc, MemoryStoreUnavailable):
                raise
            raise MemoryStoreUnavailable(f"清索引失败（墓碑已提交）: {exc}") from exc
        self._store.update_entry(
            entry["memory_id"],
            {"status": "forgotten", "updated_at": now_iso},
        )
        return tombstone

    def touch_used(self, memory_id: str) -> bool:
        entry = self._store.get_entry(memory_id)
        if entry is None:
            return False
        return self._store.update_entry(
            memory_id, {"used_at": self._now_iso(), "updated_at": self._now_iso()}
        )

    def sweep_expired(self) -> list[MemoryTombstone]:
        now = self._clock()
        swept: list[MemoryTombstone] = []
        for entry in self._store.list_all_entries():
            if entry["status"] != "active" or not entry["expires_at"]:
                continue
            try:
                expires = datetime.fromisoformat(str(entry["expires_at"]))
            except ValueError:
                continue
            if expires <= now:
                swept.append(
                    self._bury(entry, reason="ttl", forgotten_by="system:ttl")
                )
        return swept

    # ---------------------------------------------------------------- 查询/审计

    def query_records(
        self, principal: MemoryPrincipal, *, session_id: str
    ) -> list[MemoryRecord]:
        owner_id = self._resolve_owner(principal)
        entries = self._store.list_entries(
            owner_id=owner_id, session_ids=(session_id, "global")
        )
        return [self._record_from(entry) for entry in entries]

    def audit_records(self, principal: MemoryPrincipal) -> list[MemoryRecord]:
        owner_id = self._resolve_owner(principal)
        return [
            self._record_from(entry)
            for entry in self._store.list_entries_by_owner(owner_id)
        ]

    def audit_tombstones(self, principal: MemoryPrincipal) -> list[MemoryTombstone]:
        return [
            MemoryTombstone(**row)
            for row in self._store.list_tombstones(self._resolve_owner(principal))
        ]

    def bind_identities(
        self, first: MemoryPrincipal, second: MemoryPrincipal, *, created_by: str
    ) -> IdentityBinding:
        owner_id = self._resolve_owner(first)
        now_iso = self._now_iso()
        self._store.upsert_binding(second.binding_key, owner_id, created_by, now_iso)
        self._store.upsert_binding(first.binding_key, owner_id, created_by, now_iso)
        return IdentityBinding(owner_id=owner_id, created_by=created_by, created_at=now_iso)

    def resolve_owner(self, principal: MemoryPrincipal) -> str:
        return self._resolve_owner(principal)

    # ---------------------------------------------------------------- 注入

    def build_injection_preview(
        self,
        principal: MemoryPrincipal,
        *,
        session_id: str,
        budget_chars: int = DEFAULT_INJECTION_BUDGET_CHARS,
    ) -> InjectionPlan:
        return self._build_injection(
            principal,
            session_id=session_id,
            budget_chars=budget_chars,
            refresh_used_at=False,
        )

    def build_injection_plan(
        self,
        principal: MemoryPrincipal,
        *,
        session_id: str,
        budget_chars: int = DEFAULT_INJECTION_BUDGET_CHARS,
        refresh_used_at: bool = True,
    ) -> InjectionPlan:
        return self._build_injection(
            principal,
            session_id=session_id,
            budget_chars=budget_chars,
            refresh_used_at=refresh_used_at,
        )

    def _build_injection(
        self,
        principal: MemoryPrincipal,
        *,
        session_id: str,
        budget_chars: int,
        refresh_used_at: bool,
    ) -> InjectionPlan:
        owner_id = self._resolve_owner(principal)
        now = self._clock()
        entries = self._store.list_entries(
            owner_id=owner_id, session_ids=(session_id, "global")
        )
        # 墓碑归因需要把被墓碑排除的行也纳入候选（test_stale_cache：翻状态的
        # 行即便 SQL 排除，也要以 TOMBSTONE 原因出现在 excluded 里）。
        candidate_rows = list(entries)
        seen_ids = {row["memory_id"] for row in candidate_rows}
        for row in self._store.list_entries_by_owner(owner_id):
            if row["memory_id"] not in seen_ids and row["session_id"] in (
                session_id,
                "global",
            ):
                candidate_rows.append(row)
                seen_ids.add(row["memory_id"])

        selected: list[tuple[dict[str, Any], float]] = []
        excluded: list[InjectionExclusion] = []
        for row in candidate_rows:
            memory_id = row["memory_id"]
            if self._store.has_tombstone(memory_id) or row["status"] == "forgotten":
                excluded.append(
                    InjectionExclusion(memory_id=memory_id, reason=ExclusionReason.TOMBSTONE)
                )
                continue
            if row["status"] != "active":
                excluded.append(
                    InjectionExclusion(
                        memory_id=memory_id, reason=ExclusionReason.PENDING_REVIEW
                    )
                )
                continue
            if row["kind"] == MemoryKind.PROPOSAL.value:
                excluded.append(
                    InjectionExclusion(
                        memory_id=memory_id, reason=ExclusionReason.KIND_NOT_INJECTABLE
                    )
                )
                continue
            if row["expires_at"]:
                try:
                    expires = datetime.fromisoformat(str(row["expires_at"]))
                except ValueError:
                    expires = None
                if expires is not None and expires <= now:
                    excluded.append(
                        InjectionExclusion(memory_id=memory_id, reason=ExclusionReason.TTL)
                    )
                    continue
            base_moment = row["used_at"] or row["created_at"]
            score = float(row["confidence"]) * _recency_score(base_moment, now)
            selected.append((row, score))

        selected.sort(key=lambda pair: (-pair[1], pair[0]["created_at"], pair[0]["memory_id"]))
        picked: list[tuple[dict[str, Any], float]] = []
        used_chars = 0
        for row, score in selected:
            cost = len(row["text"]) + (1 if picked else 0)
            if used_chars + cost > budget_chars:
                excluded.append(
                    InjectionExclusion(memory_id=row["memory_id"], reason=ExclusionReason.BUDGET)
                )
                continue
            picked.append((row, score))
            used_chars += cost

        picked.sort(key=lambda pair: (pair[0]["created_at"], pair[0]["memory_id"]))
        items = [
            InjectionItem(memory_id=row["memory_id"], text=row["text"], score=round(score, 6))
            for row, score in picked
        ]
        rendered = ""
        if items:
            rendered = "【长期记忆】\n" + "\n".join(f"- {item.text}" for item in items)
        if refresh_used_at and picked:
            now_iso = self._now_iso()
            for row, _score in picked:
                self._store.update_entry(
                    row["memory_id"], {"used_at": now_iso, "updated_at": now_iso}
                )
        return InjectionPlan(
            owner_id=owner_id,
            session_id=session_id,
            budget_chars=budget_chars,
            selected=items,
            excluded=excluded,
            rendered_text=rendered,
        )

    # ---------------------------------------------------------------- 备份恢复/重建

    def backup_to(self, target_path: str) -> None:
        import sqlite3

        target = sqlite3.connect(target_path)
        try:
            self._store.connection.backup(target)
            target.commit()
        finally:
            target.close()

    def restore_from(self, source_path: str) -> int:
        """从备份恢复（整库替换）后重放当前墓碑——恢复不复活。

        返回重放的墓碑数（≥0）。绑定表合并（恢复后重放当前绑定，先到先得）。
        """
        import os
        import sqlite3

        if not os.path.isfile(source_path):
            raise FileNotFoundError(f"备份文件不存在: {source_path}")
        live_bindings = self._store.list_bindings()
        live_tombstones = self._store.list_all_tombstones()
        source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        tables: dict[str, list[dict[str, Any]]] = {}
        for table in (
            "memory_entries_v21",
            "memory_tombstones_v21",
            "memory_identity_bindings_v21",
            "memory_index_v21",
        ):
            tables[table] = [
                dict(row) for row in source.execute(f"SELECT * FROM {table}")
            ]
        source.close()
        self._store.restore_tables(tables)
        replayed = 0
        now_iso = self._now_iso()
        for tombstone in live_tombstones:
            if self._store.insert_tombstone(tombstone):
                replayed += 1
            # 墓碑重放必须同时把行翻回 forgotten：备份里的 active 行不得复活，
            # 审计面（不过滤墓碑）也要如实呈现遗忘态。
            self._store.update_entry(
                str(tombstone["memory_id"]),
                {"status": "forgotten", "updated_at": now_iso},
            )
        for binding in live_bindings:
            self._store.upsert_binding(
                binding["identity_key"],
                binding["owner_id"],
                binding["created_by"],
                binding["created_at"],
            )
        self.rebuild_projection()
        return replayed

    def rebuild_projection(self) -> int:
        """从条目+墓碑重建投影索引（幂等）：返回重放的墓碑数。"""
        tombstones = self._store.list_all_tombstones()
        self._store.clear_index()
        for row in self._store.backup_tables()["memory_entries_v21"]:
            if self._store.has_tombstone(row["memory_id"]):
                continue
            if row["status"] != "active":
                continue
            self._store.upsert_index_row(
                row["memory_id"], row["owner_id"], row["session_id"], row["status"]
            )
        return len(tombstones)


def _entity_token(length: int = 12) -> str:
    import secrets

    return secrets.token_hex(length // 2)
