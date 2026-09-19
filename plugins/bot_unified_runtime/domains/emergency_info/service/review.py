"""人工报料审核门（产品裁定 D-8）：入库即 pending，过审才参与定级与投递。

形态复用 `domains/chat_reply/character/quirks.py` 的 propose→approve 评审区：
- `propose`（quirks.py:202-290）只把候选送进 pending 队列、对渲染零影响
  → 本席 `ReviewGate.submit` 强制 `status=pending` 并清空审核痕迹；
- `approve`（quirks.py:292-300）用 `WHERE ... AND status='pending_review'` 守卫，
  非 pending 直接返回 False → 本席把同样的守卫下推到
  `sources/store.py::apply_review` 的 SQL `WHERE status='pending'`；
- 「管理员过审后才允许注入 prompt」→ 本席「过审后才允许定级与投递」，
  唯一出口是 `publishable_level()`。

权限判定不在本席硬编码：`authorizer` 由装配期注入（真身在
`domains/chat_reply/policy/roles.py` 的六级角色面，注册属 B8/B9 合流席）。
**未注入 authorizer ⇒ 一律拒绝**（缺省=功能关闭，与「白名单空绝不猜群」同向）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

from plugins.bot_unified_runtime.domains.core.contracts.runtime import StrictBaseModel
from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
    as_utc,
    can_transition,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.grading import (
    DEFAULT_GRADING_RULES,
    GradingRule,
    grade,
)


class ReviewStore(Protocol):
    """审核门依赖的最小存储面（结构型协议，正例见 transport 的 `SendQueue`，
    `domains/transport/sender/queue.py:167-176`）。`EmergencyStore` 天然满足。"""

    def upsert_item(self, item: EmergencyItem) -> bool: ...

    def get(self, item_id: str) -> EmergencyItem | None: ...

    def list_by_status(
        self, status: EmergencyStatus, *, limit: int = 50
    ) -> list[EmergencyItem]: ...

    def apply_review(
        self,
        item_id: str,
        *,
        target: EmergencyStatus,
        reviewer_id: str,
        at: datetime,
    ) -> bool: ...


class ReviewOutcome(StrictBaseModel):
    """一次审核动作的确定性结果（outcome 形态抄 B4 规格 §1.2 的 ActivePushOutcome）。"""

    item_id: str
    action: str
    ok: bool
    reason: str
    status: EmergencyStatus = EmergencyStatus.PENDING


class ReviewGate:
    """pending → approve/reject 审核门；纯判定 + 委托存储，零网络零 LLM。"""

    def __init__(
        self, store: ReviewStore, *, authorizer: Callable[[str], bool] | None = None
    ) -> None:
        self._store = store
        self._authorizer = authorizer

    # ------------------------------------------------------------ 入库（propose）

    def submit(self, item: EmergencyItem) -> EmergencyItem:
        """报料入库：无论调用方传什么状态，一律钉回 pending 并清空审核痕迹。

        等级也在入库时清空——「approve 后才参与定级」（D-8）在这里是结构性
        保证：pending 条目身上不带 level，投递侧就没有可绕过的现成等级可用。
        """
        forced = item.model_copy(
            update={
                "status": EmergencyStatus.PENDING,
                "reviewed_by": "",
                "reviewed_at": None,
                "level": None,
            }
        )
        self._store.upsert_item(forced)
        return forced

    # ------------------------------------------------------------ 裁决（approve/reject）

    def approve(
        self, item_id: str, *, reviewer_id: str, at: datetime
    ) -> ReviewOutcome:
        """pending → approved。任何前置校验不过即 ok=False，绝不静默改状态。"""
        return self._decide(
            item_id,
            target=EmergencyStatus.APPROVED,
            reviewer_id=reviewer_id,
            at=as_utc(at),
        )

    def reject(
        self,
        item_id: str,
        *,
        reviewer_id: str,
        at: datetime,
        reason: str = "",
    ) -> ReviewOutcome:
        """pending → rejected（终态，本席不做「驳回后重开」）。"""
        return self._decide(
            item_id,
            target=EmergencyStatus.REJECTED,
            reviewer_id=reviewer_id,
            at=as_utc(at),
            reason=str(reason or "").strip(),
        )

    def _decide(
        self,
        item_id: str,
        *,
        target: EmergencyStatus,
        reviewer_id: str,
        at: datetime,
        reason: str = "",
    ) -> ReviewOutcome:
        action = "approve" if target is EmergencyStatus.APPROVED else "reject"
        safe_id = str(item_id or "").strip()
        reviewer = str(reviewer_id or "").strip()
        if not safe_id:
            return self._failure("", action, "blank_item_id")
        if not reviewer:
            return self._failure(safe_id, action, "blank_reviewer")
        if self._authorizer is None:
            return self._failure(safe_id, action, "authorizer_not_configured")
        if not self._authorizer(reviewer):
            return self._failure(safe_id, action, "reviewer_not_authorized")
        item = self._store.get(safe_id)
        if item is None:
            return self._failure(safe_id, action, "unknown_item")
        if not can_transition(item.status, target):
            return self._failure(
                safe_id, action, "illegal_transition", status=item.status
            )
        changed = self._store.apply_review(
            safe_id, target=target, reviewer_id=reviewer, at=at
        )
        if not changed:
            # 存储侧守卫（WHERE status='pending'）没命中：并发下已被别人裁决过。
            return self._failure(safe_id, action, "not_pending_anymore")
        updated = self._store.get(safe_id) or item.model_copy(
            update={"status": target, "reviewed_by": reviewer, "reviewed_at": at}
        )
        return ReviewOutcome(
            item_id=safe_id,
            action=action,
            ok=True,
            reason=reason or "ok",
            status=updated.status,
        )

    @staticmethod
    def _failure(
        item_id: str,
        action: str,
        reason: str,
        *,
        status: EmergencyStatus = EmergencyStatus.PENDING,
    ) -> ReviewOutcome:
        return ReviewOutcome(
            item_id=item_id, action=action, ok=False, reason=reason, status=status
        )

    # ------------------------------------------------------------ 消费侧闸门

    @staticmethod
    def publishable(item: EmergencyItem) -> bool:
        """只有过审条目可以进入投递面（D-8 唯一判据；pending/rejected 全否）。"""
        return item.status is EmergencyStatus.APPROVED

    @staticmethod
    def publishable_level(
        item: EmergencyItem,
        *,
        now: datetime,
        rules: Sequence[GradingRule] = DEFAULT_GRADING_RULES,
    ) -> EmergencyLevel | None:
        """过审条目的定级结果；未过审 ⇒ None（不参与定级，也不参与投递）。

        这是「审核门 × 定级」的唯一串联点：投递侧只认本函数，
        不得自行 `grade(pending_item)` 绕门。
        """
        if not ReviewGate.publishable(item):
            return None
        return grade(item, now=now, rules=rules)

    def pending_items(self, *, limit: int = 50) -> list[EmergencyItem]:
        """待审列表（管理员过审入口的数据面）。"""
        return self._store.list_by_status(EmergencyStatus.PENDING, limit=limit)


__all__ = ["ReviewGate", "ReviewOutcome", "ReviewStore"]
