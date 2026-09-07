"""预警推送闭环。

预警内容固定包含五要素：
1. 出了什么错（what_happened）
2. 影响（impact，哪里会出问题）
3. 怎么解决（fix_suggestion）
4. 时间（occurred_at，精确到秒）
5. 位置（location，模块/阶段/会话）

预警通过统一流水线发给管理员（``BOT_ADMIN_USER_IDS``），走
``SendRequest -> DeliveryReceipt -> AuditRecord``，不绕过审计。
控制台模式下直接打印。
"""

from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    DeliveryReceipt,
    IncomingMessage,
    OperationalIssue,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    RiskLevel,
    SendPolicy,
    SendRequest,
    SessionType,
    new_request_id,
)


@dataclass(frozen=True)
class AlertContent:
    title: str
    what_happened: str
    impact: str
    fix_suggestion: str
    location: str
    level: str = "warning"  # info | warning | critical
    occurred_at: str = ""

    def __post_init__(self) -> None:
        if not self.occurred_at:
            object.__setattr__(
                self,
                "occurred_at",
                datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
            )

    def format_message(self) -> str:
        lines = [
            f"[预警] {self.title}",
            f"时间：{self.occurred_at}",
            f"位置：{self.location}",
            f"发生了什么：{self.what_happened}",
            f"影响：{self.impact}",
            f"建议处理：{self.fix_suggestion}",
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class AdminTarget:
    adapter: str
    bot_id: str
    target_id: str
    target_scope: SessionType = SessionType.PRIVATE

    def __post_init__(self) -> None:
        adapter = str(self.adapter).strip().lower()
        bot_id = str(self.bot_id).strip()
        target_id = str(self.target_id).strip()
        if not adapter or not bot_id or not target_id:
            raise ValueError("admin target adapter, bot_id, and target_id are required")
        if self.target_scope not in {SessionType.PRIVATE, SessionType.GROUP, SessionType.CHANNEL}:
            raise ValueError("admin target scope must be private, group, or channel")
        object.__setattr__(self, "adapter", adapter)
        object.__setattr__(self, "bot_id", bot_id)
        object.__setattr__(self, "target_id", target_id)

    @property
    def platform(self) -> str:
        return self.adapter

    @property
    def target_type(self) -> str:
        if self.adapter == "onebot":
            return "qq_private:user" if self.target_scope is SessionType.PRIVATE else "qq_group"
        if self.adapter == "telegram":
            return "telegram_user" if self.target_scope is SessionType.PRIVATE else "telegram_chat"
        return f"{self.adapter}:{self.target_scope.value}"

    @property
    def identity(self) -> str:
        return f"{self.adapter}:{self.bot_id}:{self.target_scope.value}:{self.target_id}"


@dataclass(frozen=True)
class AdminAlertDispatchResult:
    target: AdminTarget
    success: bool
    request_id: str
    error_kind: str = ""
    suppressed: bool = False
    suppressed_count: int = 0


def build_typed_admin_targets(
    *,
    qq_admin_ids: list[str] | tuple[str, ...] = (),
    telegram_user_ids: list[str] | tuple[str, ...] = (),
    telegram_chat_ids: list[str] | tuple[str, ...] = (),
    qq_bot_id: str = "configured-qq",
    telegram_bot_id: str = "configured-telegram",
) -> list[AdminTarget]:
    targets: list[AdminTarget] = []
    for target_id in qq_admin_ids:
        if str(target_id).strip() and str(qq_bot_id).strip():
            targets.append(
                AdminTarget(
                    adapter="onebot", bot_id=qq_bot_id, target_id=str(target_id)
                )
            )
    for target_id in telegram_user_ids:
        if str(target_id).strip() and str(telegram_bot_id).strip():
            targets.append(
                AdminTarget(
                    adapter="telegram", bot_id=telegram_bot_id, target_id=str(target_id)
                )
            )
    for target_id in telegram_chat_ids:
        if str(target_id).strip() and str(telegram_bot_id).strip():
            targets.append(
                AdminTarget(
                    adapter="telegram",
                    bot_id=telegram_bot_id,
                    target_id=str(target_id),
                    target_scope=SessionType.GROUP,
                )
            )
    return targets


class AdminAlertSuppression:
    def __init__(self, *, window_seconds: float = 300.0, clock: Callable[[], Any] | None = None) -> None:
        self.window_seconds = max(0.0, float(window_seconds))
        self.clock = clock or time.monotonic
        self._entries: dict[tuple[object, ...], tuple[float, int]] = {}
        self._lock = threading.Lock()

    def allow(self, key: tuple[object, ...]) -> tuple[bool, int]:
        now = self.clock()
        timestamp_method = getattr(now, "timestamp", None)
        timestamp = float(timestamp_method() if callable(timestamp_method) else now)
        normalized_key = tuple(key)
        with self._lock:
            existing = self._entries.get(normalized_key)
            if existing is None or timestamp - existing[0] >= self.window_seconds:
                suppressed = existing[1] if existing is not None else 0
                self._entries[normalized_key] = (timestamp, 0)
                return True, suppressed
            self._entries[normalized_key] = (existing[0], existing[1] + 1)
            return False, existing[1] + 1

    def allow_issue(
        self,
        issue: OperationalIssue,
        *,
        source_adapter: str,
        source_bot: str,
        target: AdminTarget,
    ) -> tuple[bool, int]:
        return self.allow(
            (
                issue.stage,
                issue.kind,
                str(source_adapter).strip().lower(),
                str(source_bot).strip(),
                target.adapter,
                target.bot_id,
                target.target_scope.value,
                target.target_id,
            )
        )


def build_admin_alert_send_request(
    target: AdminTarget,
    text: str,
    *,
    request_id: str | None = None,
) -> SendRequest:
    request_id = request_id or new_request_id("admin_alert")
    return SendRequest(
        request_id=request_id,
        session_id=f"admin:{target.adapter}:{target.target_id}",
        target_scope=target.target_scope,
        target_id=target.target_id,
        capability_id="bot.admin_alert",
        content=RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={"text": str(text)[:4000]},
            text_fallback=str(text)[:4000],
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="high",
        max_messages=1,
        dedupe_key=f"admin_alert:{target.adapter}:{target.bot_id}:{target.target_id}:{request_id}",
        cooldown_key=f"admin_alert:{target.adapter}:{target.target_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="runtime",
        adapter=target.adapter,
        bot_id=target.bot_id,
        audit_tags=["admin_alert", "origin:admin_alert"],
    )


def build_operational_alert_text(
    issue: OperationalIssue,
    *,
    source_adapter: str,
    source_bot: str,
    session_type: SessionType,
    suppressed_count: int = 0,
) -> str:
    elapsed = "" if issue.elapsed_ms is None else f" elapsed_ms={issue.elapsed_ms:.1f}"
    return (
        f"[运行时告警] stage={issue.stage} kind={issue.kind} "
        f"retryable={str(issue.retryable).lower()} attempts={issue.attempts}{elapsed} "
        f"debug_id={issue.debug_id} source_adapter={str(source_adapter).strip()[:40]} "
        f"source_bot={str(source_bot).strip()[:80]} session_type={session_type.value} "
        f"suppressed_count={max(0, int(suppressed_count))}"
    )


async def notify_operational_issue(
    issue: OperationalIssue,
    *,
    source_adapter: str,
    source_bot: str,
    session_type: SessionType,
    targets: list[AdminTarget],
    online_bots: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
    delivery: Callable[[AdminTarget, Any, SendRequest], Any],
    suppression: AdminAlertSuppression | None = None,
) -> list[AdminAlertDispatchResult]:
    suppression = suppression or AdminAlertSuppression()
    results: list[AdminAlertDispatchResult] = []
    for target in targets:
        allowed, suppressed_count = suppression.allow_issue(
            issue,
            source_adapter=source_adapter,
            source_bot=source_bot,
            target=target,
        )
        if not allowed:
            results.append(
                AdminAlertDispatchResult(
                    target=target,
                    success=False,
                    request_id="",
                    suppressed=True,
                    suppressed_count=suppressed_count,
                )
            )
            continue
        text = build_operational_alert_text(
            issue,
            source_adapter=source_adapter,
            source_bot=source_bot,
            session_type=session_type,
            suppressed_count=suppressed_count,
        )
        dispatched = await dispatch_admin_alert(
            [target],
            online_bots=online_bots,
            delivery=delivery,
            text=text,
        )
        results.extend(
            result.__class__(
                target=result.target,
                success=result.success,
                request_id=result.request_id,
                error_kind=result.error_kind,
                suppressed=False,
                suppressed_count=suppressed_count,
            )
            for result in dispatched
        )
    return results


async def dispatch_admin_alert(
    targets: list[AdminTarget],
    *,
    online_bots: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
    delivery: Callable[[AdminTarget, Any, SendRequest], Any],
    text: str,
) -> list[AdminAlertDispatchResult]:
    try:
        bots = online_bots() if callable(online_bots) else online_bots
    except Exception:  # noqa: BLE001 - registry failure must not affect origin.
        return [
            AdminAlertDispatchResult(
                target=target,
                success=False,
                request_id="",
                error_kind="registry_unavailable",
            )
            for target in targets
        ]
    results: list[AdminAlertDispatchResult] = []
    for target in targets:
        bot = bots.get(target.bot_id) if target.bot_id else None
        if bot is None and not target.bot_id and len(bots) == 1:
            bot = next(iter(bots.values()))
        request_id = new_request_id("admin_alert")
        request = build_admin_alert_send_request(target, text, request_id=request_id)
        if bot is None:
            results.append(
                AdminAlertDispatchResult(target, False, request_id, "bot_unavailable")
            )
            continue
        try:
            value = delivery(target, bot, request)
            if inspect.isawaitable(value):
                value = await value
        except Exception:  # noqa: BLE001 - alert delivery failures must not recurse.
            results.append(AdminAlertDispatchResult(target, False, request_id, "send_exception"))
        else:
            success = not isinstance(value, DeliveryReceipt) or value.state is ReceiptState.SENT
            results.append(
                AdminAlertDispatchResult(
                    target,
                    success,
                    request_id,
                    "" if success else "send_exception",
                )
            )
    return results


def build_alert_capability_result(
    request_id: str,
    alert: AlertContent,
    *,
    image_path: str = "",
) -> CapabilityResult:
    result = CapabilityResult(
        request_id=request_id,
        capability_id="bot.alert",
        kind="text",
        title=alert.title,
        body=alert.format_message(),
        confidence=1.0,
        risk_level=(
            RiskLevel.HIGH if alert.level == "critical" else RiskLevel.MEDIUM
        ),
        privacy_level=PrivacyLevel.PERSONAL,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=[
            "admin_alert",
            "origin:admin_alert",
            f"alert_level:{alert.level}",
            "alert",
        ],
    )
    if image_path:
        result = result.model_copy(
            update={
                "kind": "image",
                "images": [{"type": "image", "file": image_path}],
            }
        )
    return result


def send_admin_alert_requests(
    pipeline: Any,
    admin_ids: list[str],
    alert: AlertContent,
    *,
    qq_bot_id: str = "queued-onebot",
    image_path: str = "",
) -> list[tuple[str, str]]:
    """Queue compatible QQ credential alerts and return explicit request IDs.

    The compatibility surface is intentionally QQ-only. The adapter and bot ID
    are typed on the request, so a later queue worker can match a recovered
    OneBot account instead of guessing from the last request.
    """
    created: list[tuple[str, str]] = []
    normalized_bot_id = str(qq_bot_id).strip() or "queued-onebot"
    for admin_id in admin_ids:
        admin_id = str(admin_id).strip()
        if not admin_id:
            continue
        message = IncomingMessage(
            platform="runtime",
            adapter="onebot",
            bot_id=normalized_bot_id,
            session_id=f"private:{admin_id}",
            session_type=SessionType.PRIVATE,
            sender_id=admin_id,
            sender_display_name="运行时预警",
            plain_text=alert.title,
            mentions_bot=False,
        )

        def capability(
            _message: IncomingMessage,
            _decision: object,
        ) -> CapabilityResult:
            return build_alert_capability_result(
                _message.request_id, alert, image_path=image_path
            )

        try:
            receipt = pipeline.handle(
                message,
                capability,
                capability_id="bot.alert",
            )
        except Exception:  # noqa: S112, BLE001 - 单个管理员告警投递失败跳过，继续处理其余管理员。
            continue
        if receipt.state.value in {"sent", "accepted", "queued", "rendered"}:
            created.append((admin_id, message.request_id))
    return created


def send_admin_alert(
    pipeline: Any,
    admin_ids: list[str],
    alert: AlertContent,
) -> list[str]:
    """Compatibility wrapper for existing QQ credential alert callers."""
    return [
        admin_id
        for admin_id, _request_id in send_admin_alert_requests(
            pipeline,
            admin_ids,
            alert,
        )
    ]

