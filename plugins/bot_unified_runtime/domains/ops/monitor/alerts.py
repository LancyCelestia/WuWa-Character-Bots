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
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts import (
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
from plugins.bot_unified_runtime.output.plain_text import redact_local_secrets


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
    def __init__(
        self,
        *,
        window_seconds: float = 300.0,
        clock: Callable[[], Any] | None = None,
        fold_kind_stages: frozenset[str] = frozenset({"llm"}),
    ) -> None:
        self.window_seconds = max(0.0, float(window_seconds))
        self.clock = clock or time.monotonic
        # v21r2 R1 告警去噪：这些 stage 的告警在抑制窗口内按 stage 折叠——
        # 不同 kind（llm 的 network/timeout/deadline…）不再各占一个抑制槽，
        # 窗口内最多一条/目标；累积的 kinds 随下一条放行告警带出（信息不丢）。
        self._fold_kind_stages = frozenset(fold_kind_stages or set())
        self._entries: dict[tuple[object, ...], tuple[float, int]] = {}
        self._seen_kinds: dict[tuple[object, ...], list[str]] = {}
        self._last_report_kinds: dict[tuple[object, ...], list[str]] = {}
        self._lock = threading.Lock()

    def _issue_key(
        self,
        issue: OperationalIssue,
        *,
        source_adapter: str,
        source_bot: str,
        target: AdminTarget,
    ) -> tuple[object, ...]:
        kind_slot: object = issue.kind
        if str(issue.stage).strip() in self._fold_kind_stages:
            kind_slot = "*folded*"
        return (
            issue.stage,
            kind_slot,
            str(source_adapter).strip().lower(),
            str(source_bot).strip(),
            target.adapter,
            target.bot_id,
            target.target_scope.value,
            target.target_id,
        )

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
        key = self._issue_key(
            issue,
            source_adapter=source_adapter,
            source_bot=source_bot,
            target=target,
        )
        kind = str(issue.kind).strip()
        with self._lock:
            kinds = self._seen_kinds.setdefault(key, [])
            if kind and kind not in kinds:
                kinds.append(kind)
                del kinds[8:]
            previous_kinds = list(kinds)
        allowed, suppressed_count = self.allow(key)
        with self._lock:
            if allowed:
                # 新窗口开启：上一窗口累积的 kinds（>1 才有意义）冻结为待播报
                # 清单，随本次告警文本带出；窗口内清单重置为当前 kind 重新累积。
                self._last_report_kinds[key] = (
                    previous_kinds
                    if str(issue.stage).strip() in self._fold_kind_stages
                    and len(previous_kinds) > 1
                    else []
                )
                self._seen_kinds[key] = [kind] if kind else []
            else:
                self._last_report_kinds.pop(key, None)
        return allowed, suppressed_count

    def last_report_kinds_for_issue(
        self,
        issue: OperationalIssue,
        *,
        source_adapter: str,
        source_bot: str,
        target: AdminTarget,
    ) -> list[str]:
        """上一抑制窗口累积（随本次放行待播报）的 kind 清单；fail-open 空表。"""
        try:
            key = self._issue_key(
                issue,
                source_adapter=source_adapter,
                source_bot=source_bot,
                target=target,
            )
            with self._lock:
                return list(self._last_report_kinds.get(key, []))
        except Exception:  # noqa: BLE001 - 聚合元数据失败不影响告警主链。
            return []


def build_admin_alert_send_request(
    target: AdminTarget,
    text: str,
    *,
    request_id: str | None = None,
) -> SendRequest:
    # 审查 F-03（收窄口径）：此处是所有管理员告警出站内容的唯一收口（调用方
    # 传入的 text 可能内插原始异常串，夹带内网 URL/键值形态），系统生成的
    # 通知文本出站前统一打码；聊天回复链不经此函数，零改动。
    text = redact_local_secrets(str(text))
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


# v21r2 R1：llm 路由轨迹摘要里的链宽记号（chat.py _llm_error_result 产出的
# safe_summary 形如 "network chain=17 last=umi-claude-sonnet-5"）。
_LLM_CHAIN_RE = re.compile(r"\bchain=(\d+)\b")


def _compress_llm_chain_detail(issue: OperationalIssue) -> str:
    """llm 告警 detail 压缩（防刷屏但可诊断）：`X chain=N …` → `chain=N跳全败 X …`。

    告警只在整条链失败后触发，`chain=N跳全败` 语义诚实（N=N 跳全失败）；
    非 llm stage 或无 chain 记号原样返回。
    """
    summary = str(issue.safe_summary).strip()
    if str(issue.stage).strip() != "llm":
        return summary
    match = _LLM_CHAIN_RE.search(summary)
    if match is None:
        return summary
    hops = max(1, int(match.group(1)))
    # kind 词头（match 前缀）丢弃：kind 已在 kind= 字段呈现，不重复占宽。
    tail = summary[match.end() :].strip()
    parts = [f"chain={hops}跳全败"]
    if tail:
        parts.append(tail)
    return " ".join(parts)[:72]


def build_operational_alert_text(
    issue: OperationalIssue,
    *,
    source_adapter: str,
    source_bot: str,
    session_type: SessionType,
    suppressed_count: int = 0,
    folded_kinds: list[str] | None = None,
) -> str:
    elapsed = "" if issue.elapsed_ms is None else f" elapsed_ms={issue.elapsed_ms:.1f}"
    # vis3（2026-09-13）：detail=安全摘要（能力名:异常类型），让告警自解释。
    # v21r2 R1：llm 链式失败 detail 压缩成「chain=N跳全败 …」防刷屏但可诊断。
    safe_detail = _compress_llm_chain_detail(issue)
    detail = (
        f" detail={safe_detail[:60]}"
        if safe_detail
        else ""
    )
    # v21r2 R1：折叠窗口内出现过的多 kind 清单随放行告警带出（信息不丢）。
    kinds = [str(k).strip() for k in (folded_kinds or []) if str(k).strip()]
    kinds_part = f" llm_kinds=[{'|'.join(kinds[:8])}]" if len(kinds) > 1 else ""
    # 审查 F-03（收窄口径）：告警 public 文本内插 issue.kind/safe_summary 等
    # 摘要字段（源自 str(exc) 截断，可能夹带内网 URL/键值形态），出站前统一
    # 过脱敏；告警是系统生成的通知文本，脱敏零误伤，聊天回复链不经此函数。
    return redact_local_secrets(
        f"[运行时告警] stage={issue.stage} kind={issue.kind}{detail} "
        f"retryable={str(issue.retryable).lower()} attempts={issue.attempts}{elapsed} "
        f"debug_id={issue.debug_id} source_adapter={str(source_adapter).strip()[:40]} "
        f"source_bot={str(source_bot).strip()[:80]} session_type={session_type.value} "
        f"suppressed_count={max(0, int(suppressed_count))}{kinds_part}"
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
        # v21r2 R1：折叠窗口内累积的 kind 清单随放行告警带出（信息不丢）。
        folded_kinds = suppression.last_report_kinds_for_issue(
            issue,
            source_adapter=source_adapter,
            source_bot=source_bot,
            target=target,
        )
        text = build_operational_alert_text(
            issue,
            source_adapter=source_adapter,
            source_bot=source_bot,
            session_type=session_type,
            suppressed_count=suppressed_count,
            folded_kinds=folded_kinds,
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


def build_alert_content_sink(
    pipeline: Any,
    admin_ids: list[str],
    *,
    qq_bot_id: str = "queued-onebot",
    window_seconds: float = 300.0,
    log: Any = None,
) -> Callable[[AlertContent], None]:
    """后台任务告警接入口：``AlertContent -> 管理员预警投递``（同步、fail-open）。

    存在的理由：定时/线程池任务（kb-sync、夜间作业等）跑不到事件循环里，也不该
    各自复制一份「拼文本 + 逐个管理员投递 + 抑制」的样板。这里把 ``send_admin_alert_requests``
    包成一个回调，任务侧只需 ``sink(AlertContent(...))``；装配点在 root
    ``__init__.py``（把 sink 注入对应模块的 setter）。

    抑制复用 ``AdminAlertSuppression``（缺省 300s 窗口，键 = location+level+管理员），
    与队列告警同口径：同一故障每晚一轮也只打扰一次。任何异常只记日志、绝不回传——
    告警链路坏了不能把同步任务一起拖下水（与 ``dispatch_admin_alert`` 的
    「failure must not recurse」同纪律）。
    """
    suppression = AdminAlertSuppression(window_seconds=window_seconds)

    def _sink(alert: AlertContent) -> None:
        try:
            for admin_id in (str(item).strip() for item in admin_ids):
                if not admin_id:
                    continue
                allowed, _count = suppression.allow(
                    (str(alert.location), str(alert.level), "onebot", admin_id)
                )
                if not allowed:
                    continue
                send_admin_alert_requests(
                    pipeline, [admin_id], alert, qq_bot_id=qq_bot_id
                )
        except Exception:  # noqa: BLE001 - 告警投递失败只记日志，不影响调用方主链路。
            if log is not None:
                try:
                    log.warning("alert sink dispatch failed", exc_info=True)
                except Exception:  # noqa: S110, BLE001 - 日志器本身异常时静默。
                    pass

    return _sink

