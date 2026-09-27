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

2026-09-25（澜汐裁定「任何报错出来都需要给我完整的诊断卡」）：文本告警之后
给同一批管理员**追加一张诊断卡**——载荷组装与渲染/入队口径全在
``error_report``（``build_issue_report`` / ``schedule_issue_card``），本模块只管
「发给谁、何时发、出图失败怎么办」；开关与冷却闸沿用异常卡那一本，不另立。
"""

from __future__ import annotations

import inspect
import logging
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
from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
    ErrorCardGate,
    ErrorCardSettings,
    _module_gate,
    _resolve_settings,
    build_issue_report,
    build_text_fallback,
    format_clock_label,
    schedule_issue_card,
)
from plugins.bot_unified_runtime.output.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)


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


def admin_alert_session_id(target: AdminTarget) -> str:
    """管理员告警的会话标识（文本与诊断卡共用同一个键）。

    这枚串同时是诊断卡冷却闸的记账键（见 `_maybe_dispatch_issue_card`），所以
    必须与出站请求上的 session_id 逐字相等——两处各拼一遍迟早会漂。
    """
    return f"admin:{target.adapter}:{target.target_id}"


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
        session_id=admin_alert_session_id(target),
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


# ---------------------------------------------------------------- 人话主句（2026-09-25）
#
# 为什么要这一层：告警今天长这样——
#   [运行时告警] stage=onebot kind=retcode_failure detail=retcode_failure retryable=false
#   attempts=1 debug_id=dbg_a390… source_adapter=nonebot source_bot=3958874605 …
# 一行英文键值串，澜汐的原话是「现在的报错实在是无法让人看懂」。
#
# 两条口径写死在这里：
# 1. **人话在前、技术行在后**：原来那行逐字保留（有测试按 `detail=` / `chain=N跳全败` /
#    `kind=` 取子串，也有运维脚本按这行 grep），只是在它前面加中文主句。
# 2. **认不出的 stage/kind 绝不编解释**：落到 `（错误代号 stage/kind）` 的通用中文句式。
#    把没核过的原因写成断言，比不给解释更糟——这条与「无检索结果不得断言未发生」同源。

_STAGE_PLAIN: dict[str, str] = {
    "llm": "我在想怎么回你这句话（模型那一跳）",
    "onebot": "我把话交给 QQ 协议端往外发",
    "transport": "我把消息往外投递",
    "sender": "我把消息往外投递",
    "queue": "这条消息排在发送队列里",
    "receipt": "我在确认消息到底送出去了没有",
    "tts": "我把这段文字转成语音",
    "mail_bridge": "我在发/收邮件",
    "capability_invoke": "我在跑一个功能",
    "context": "我在拼这次对话的上下文",
    "context_diagnostic": "我在自检上下文",
    "router": "我在挑用哪个模型",
    "policy": "我在过发送策略",
    "review": "我在过内容审核",
    "audience_gate": "我在判断这条该不该发给对方",
    "mute_gate": "我在看这个会话是不是被静音了",
    "quiet_hours": "我在核对安静时间",
    "idempotency_gate": "我在查这条是不是重复发",
    "notice_gate": "我在看过不过通知门",
    "action_resolver": "我在解析要执行哪个动作",
    "scheduler": "定时器在派一件该做的事",
    "startup": "我在启动装配",
    "runtime": "我在做运行时杂务",
    "nonebot_handlers": "NoneBot 的事件处理",
    "tools": "我在调一个工具",
    "creation": "我在生成创作类内容",
    "generation": "我在生成内容",
    "history": "我在读历史消息",
    "campus": "我在处理校园转发",
}

_KIND_PLAIN: dict[str, str] = {
    "timeout": "等回话等超时了",
    "deadline_exceeded": "整条链路的时限用完了",
    "network": "连不上对方服务",
    "retcode_failure": "协议端拒收（它回了失败码）",
    "send_exception": "投递时抛了异常",
    "transport_exception": "传输层抛了异常",
    "bot_unavailable": "此刻没有在线的发送账号",
    "result_unknown": "发出去了，但不确定对方收到没有",
    "config_missing": "少了一项配置，功能没能起来",
    "provider_error": "模型服务自己报错了",
    "provider_not_configured": "这个模型没配好上游",
    "schema": "对方回的内容格式不对，我读不出来",
    "empty_response": "对方回了，但内容是空的",
    "internal_error": "我内部抛异常了",
    "pipeline_busy": "队列排满了，这条暂时挤不进去",
    "registry_unavailable": "模型注册表这会儿读不到",
    "tts_service_unreachable": "语音引擎连不上",
    "tts_service_rejected": "语音引擎拒了这个请求",
    "tts_synthesize_failed": "语音合成失败",
    "tts_no_ref_audio": "没有可用的参考音频",
}

#: 键由 ``SessionType`` 枚举派生，不手抄字符串——旧表写的是 `"mail"`，而枚举值
#: 是 `"email"`，邮件会话因此查不到、把英文代号 `email` 直接打进中文主句
#: （违反「报错提示不得纯英文」，2026-09-25 澜汐硬约束）。加一档忘了填人话，
#: 由 `test_session_plain_covers_every_session_type` 当场红。
_SESSION_PLAIN: dict[str, str] = {
    member.value: label
    for member, label in (
        (SessionType.PRIVATE, "私聊"),
        (SessionType.GROUP, "群聊"),
        (SessionType.CHANNEL, "频道"),
        (SessionType.EMAIL, "邮件"),
        (SessionType.CONSOLE, "控制台"),
    )
}


def _alert_when_label() -> str:
    """告警时刻：委托 `error_report.format_clock_label`（全卡/全告警一个格式）。

    偏移必须写出来——本仓 cron 用系统本地时区（台账 #6），异区机器上光有
    「03:52:11」对不上日志里的 UTC 行。两处各写一份 strftime 时，卡上漂成了
    ISO 的 ``T``/``+08:00``，同一张卡两种写法（2026-09-25 真卡评审）。
    """
    return format_clock_label()


# 代号字符集：stage/kind 是代码里给的标识符，进人话句前按白名单洗一遍。
# 为什么不等 redact_local_secrets 兜——它按形态识别（`sk-` 独立成词之类），
# 嵌在词里的密钥它不认；而这里恰恰是把外部字符串拼进句子。白名单外的字符
# 一律不认，宁可让代号显示成被裁过的样子，也不给它带东西出去。
_ALERT_TOKEN_RE = re.compile(r"[^A-Za-z0-9_.:\-]")
# 密钥形态（`sk-` / `ah-` 后跟一长串）：白名单允许这些字符，所以光靠白名单挡不住
# "代号里混进密钥"。全仓脱敏 `redact_local_secrets` 按独立词形识别，嵌在词里的不认，
# 这里就地把这类片段摘掉——只在告警代号面上生效，不去改全局尺（那会牵连聊天出站）。
_ALERT_SECRETISH_RE = re.compile(r"[A-Za-z]{1,6}-[A-Za-z0-9]{20,}")


def _alert_token(raw: str, *, limit: int = 48) -> str:
    cleaned = _ALERT_TOKEN_RE.sub("", str(raw or "").strip())
    cleaned = _ALERT_SECRETISH_RE.sub("‹已隐藏密钥形态›", cleaned)
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "…"
    return cleaned or "未记名"


#: 认不出代号时主句里必带的那半句（2026-09-28 用户裁定「兜底句别只报我没词」）。
#: 测试两面都吃这个常量——「已登记的不许出现它」「未登记的必须出现它」共用一把尺，
#: 措辞再改也不会把反向腿测成空转（旧写法两边各抄一遍字面量，改一处即静默失效）。
ALERT_UNREGISTERED_MARK = "还没登记中文说明"


def _alert_plain_headline(issue: OperationalIssue) -> str:
    """把一条 issue 翻成一句中文主句（不含技术字段行）。"""
    stage = _alert_token(issue.stage)
    kind = _alert_token(issue.kind)
    doing = _STAGE_PLAIN.get(str(issue.stage).strip())
    reason = _KIND_PLAIN.get(str(issue.kind).strip())
    if doing is None or reason is None:
        # 认不出来的那半边一律点名代号，不猜原因。
        token = f"{stage}/{kind}" if doing is None and reason is None else (
            kind if doing is not None else stage
        )
        doing = doing or "有一件事没做成"
        # 兜底句自带出路：不编原因＋该谁动（照代号补 `_KIND_PLAIN`）＋现场依据在哪
        # （本条 detail 与排查编号）。运维拿到这一句就知道下一步，不用再翻代码猜。
        reason = (
            f"碰到一件{ALERT_UNREGISTERED_MARK}的异常（代号 {token}）；"
            "原因我不猜，请按代号往 alerts._KIND_PLAIN 补一句中文说明，"
            "现场依据看本条 detail 与排查编号"
        )
    # 主句只留"发生了什么"：时间/会话/账号/试了几次/要不要再试交给下面的逐行字段，
    # 同一件事不在一条消息里说两遍（2026-09-25 澜汐：一行一个值、别复读）。
    return f"[守岸人告警] {doing}：{reason}。"


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
    # 人话主句同样在脱敏之内（代号里可能带出上游原文）。
    headline = _alert_plain_headline(issue)
    plain_fields = _alert_plain_fields(
        issue,
        source_adapter=source_adapter,
        source_bot=source_bot,
        session_type=session_type,
        safe_detail=safe_detail,
        suppressed_count=suppressed_count,
    )
    technical = redact_local_secrets(
        f"[运行时告警] stage={issue.stage} kind={issue.kind}{detail} "
        f"retryable={str(issue.retryable).lower()} attempts={issue.attempts}{elapsed} "
        f"debug_id={issue.debug_id} source_adapter={str(source_adapter).strip()[:40]} "
        f"source_bot={str(source_bot).strip()[:80]} session_type={session_type.value} "
        f"suppressed_count={max(0, int(suppressed_count))}{kinds_part}"
    )
    return "\n".join([redact_local_secrets(headline), *plain_fields, technical])


def _alert_plain_fields(
    issue: OperationalIssue,
    *,
    source_adapter: str,
    source_bot: str,
    session_type: SessionType,
    safe_detail: str,
    suppressed_count: int,
) -> list[str]:
    """告警正文的逐行字段（2026-09-25 澜汐：一行一个值，要看得懂）。

    旧版把时间、会话、发出账号、原因全挤进一句，读起来像绕口令；技术行又是
    一整串键值。这里改成**每个事实单独一行、行首中文标签**，值原样保留——
    代号、排查编号、详情串都是要抄去查的东西，不翻译也不改写。
    技术行照旧逐字留在最后，既有 grep 与回归锁不吃亏。

    「走哪一步 / 出的什么错」两行**不在这里**：它们就是主句那句话，同一条消息里
    说三遍（2026-09-25 澜汐：别复读）。代号单列一行留给抄查，中文解释只在主句出现。
    """
    rows: list[tuple[str, str]] = [
        ("时间", _alert_when_label()),
        ("会话", _SESSION_PLAIN.get(str(session_type.value), str(session_type.value))),
        ("发出账号", _alert_token(source_bot, limit=80)),
        ("代号", f"{_alert_token(issue.stage)}/{_alert_token(issue.kind)}"),
        ("具体情况", safe_detail[:120] if safe_detail else "上游没给细节"),
        (
            "要不要再试",
            "还能重试，你不用管" if issue.retryable else "重试也没用，得有人看一眼",
        ),
        ("试了几次", str(max(1, int(issue.attempts)))),
        ("排查编号", str(issue.debug_id or "没有")),
    ]
    if issue.elapsed_ms is not None:
        # 30211.4 毫秒这种写法要人用心算；毫秒级保留小数，秒级以上说秒。
        ms = float(issue.elapsed_ms)
        spent = f"{ms:.1f} 毫秒" if ms < 1000 else f"{ms / 1000:.1f} 秒"
        rows.append(("这一步花了", spent))
    if source_adapter:
        rows.append(("来源通道", _alert_token(source_adapter, limit=40)))
    if suppressed_count:
        rows.append(
            ("同时压着", f"{int(suppressed_count)} 条同类没重复发（300 秒内只发一条）")
        )
    # 逐行也要过脱敏：详情串来自 str(exc) 截断，实测能把 `sk-…` 与盘符路径带进来
    # （本仓铁律 3：出站前统一 redact_local_secrets，不因"只是行标签"而豁免）。
    return [
        redact_local_secrets(f"{label}：{value}")
        for label, value in rows
        if str(value).strip() and value != "未记名"
    ]


# ---------------------------------------------------------------- 告警诊断卡（2026-09-25）
#
# 澜汐裁定：「任何报错出来都需要给我完整的诊断卡」。此前运行时告警只有
# `build_operational_alert_text` 那一行文本（本文件改前对 error_report 零引用，
# 判据已核实成立），LLM 超时与协议端拒收这类故障她只看得见一行键值串。
# 这一段把卡接在**同一条链路**上，三条口径写死在这里：
# 1. **文本先行**：文本告警照旧立刻发；卡是追加件，渲染排在专用渲染线程、入队
#    带 deliver_after 下限（= 卡必排在文本之后），任何一步失败只 logger.warning，
#    绝不把已经发出去的文本带下水。
# 2. **不另立闸本**：开关沿用 ``bot_error_card_enabled``（``_resolve_settings()``），
#    冷却沿用异常卡那个进程级共享闸 ``ErrorCardGate``（``_module_gate``），
#    记账键用管理员会话 id——与异常卡同一本账，不建第二本。
# 3. **不手搓载荷**：卡 payload 的唯一组装口是 ``error_report.build_issue_report``，
#    本文件只负责「发给谁 / 什么时候发 / 出图失败怎么办」。

#: 测试注入缝：非 None 时**整段**替代真渲染+入队（生产恒 None＝走真渲染）。
#: 闸（开关/冷却）与载荷组装都在调用它之前完成，所以「开关关＝一次渲染都不调」
#: 这类判据测的是真判据，不是测替身。
alert_card_sink: Callable[[AdminTarget, dict[str, Any]], Any] | None = None


def build_admin_alert_card_send_request(
    target: AdminTarget,
    report: dict[str, Any],
    *,
    png_path: str = "",
    request_id: str | None = None,
) -> SendRequest:
    """告警诊断卡的出站请求（与文本告警同一个管理员目标、同一 session 口径）。

    ``png_path`` 为空＝渲染失败那一态：此时不发明第二份文本，直接用诊断卡的
    纯文本兜底 ``build_text_fallback(report)``（全量要素，同样已脱敏）。
    ``audit_tags`` 必须带 ``admin_alert``：根装配层的队列回执通知按这个标签
    短路（"alert send failure must not recurse"），漏了它，一条发不出去的告警
    卡会再生一条告警——自我放大。
    """
    request_id = request_id or new_request_id("admin_alert")
    fallback_text = build_text_fallback(report)
    if png_path:
        content = RenderedOutput(
            request_id=request_id,
            content_type="mixed",
            content_ref={
                "parts": [
                    {"type": "image", "file": png_path},
                    {"type": "text", "text": str(report.get("human_text") or "")},
                ]
            },
            text_fallback=fallback_text,
            privacy_level=PrivacyLevel.PERSONAL,
        )
    else:
        content = RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={"text": fallback_text[:4000]},
            text_fallback=fallback_text[:4000],
            privacy_level=PrivacyLevel.PERSONAL,
        )
    return SendRequest(
        request_id=request_id,
        session_id=admin_alert_session_id(target),
        target_scope=target.target_scope,
        target_id=target.target_id,
        capability_id="bot.error_report",
        content=content,
        send_policy=SendPolicy.IMMEDIATE,
        priority="high",
        max_messages=1,
        dedupe_key=(
            f"admin_alert_card:{target.adapter}:{target.bot_id}:"
            f"{target.target_id}:{request_id}"
        ),
        cooldown_key=f"admin_alert_card:{target.adapter}:{target.target_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_split=False,
        allow_forward=False,
        persona_profile_id="runtime",
        adapter=target.adapter,
        bot_id=target.bot_id,
        audit_tags=["admin_alert", "origin:admin_alert", "admin_alert_card"],
    )


def _maybe_dispatch_issue_card(
    issue: OperationalIssue,
    target: AdminTarget,
    *,
    source_adapter: str,
    source_bot: str,
    session_type: SessionType,
    pipeline: Any = None,
    capability_id: str = "",
    session_id: str = "",
    group_id: str = "",
    request_id: str = "",
    settings: ErrorCardSettings | None = None,
    gate: ErrorCardGate | None = None,
    backend: Any = None,
    card_dir: str | None = None,
    render_pool: Any = None,
) -> bool:
    """已发出的那条文本告警 → 给同一个管理员追加一张诊断卡；返回是否已排卡。

    顺序（先文本后卡）由调用方保证；本函数自身**不抛异常**——卡是追加件，
    渲染/入队任何失败只留痕，把已送达的文本告警带下水是比"没看到卡"更糟的失效。
    """
    try:
        sink = alert_card_sink
        if sink is None and pipeline is None:
            # 没有可投递的队列：今天这条链只可能出文本。诚实不假装出卡，
            # 也**先于占闸**返回——不为一件发不出去的事烧掉冷却窗口。
            return False
        resolved = settings or _resolve_settings()
        if not resolved.enabled:
            return False
        session_gate = gate or _module_gate(resolved.cooldown_seconds)
        if not session_gate.allow(admin_alert_session_id(target)):
            return False
        report = build_issue_report(
            issue,
            source_adapter=source_adapter,
            source_bot=source_bot,
            session_type=session_type,
            headline=_alert_plain_headline(issue),
            capability_id=capability_id,
            session_id=session_id,
            group_id=group_id,
            request_id=request_id,
        )
        if sink is not None:
            sink(target, report)
            return True
        return schedule_issue_card(
            report,
            pipeline=pipeline,
            build_request=lambda png, payload: build_admin_alert_card_send_request(
                target, payload, png_path=png
            ),
            backend=backend,
            card_dir=card_dir,
            render_pool=render_pool,
        )
    except Exception:  # 卡失败绝不反噬文本告警（处理器已记日志=BLE001 不触发）。
        logger.warning("admin alert card dispatch failed", exc_info=True)
        return False


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
    pipeline: Any = None,
    capability_id: str = "",
    session_id: str = "",
    group_id: str = "",
    request_id: str = "",
) -> list[AdminAlertDispatchResult]:
    """运行时告警投递：每个目标**先发文本、再补一张诊断卡**（2026-09-25）。

    ``pipeline`` 是卡的投递依赖（诊断卡经 send_queue 补发）。调用方（根装配层
    的四个告警口）手上有 pipeline，不传就等于今天仍然只发文本——闸与载荷照旧
    走同一条函数，不留第二条实现。
    """
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
        for result in dispatched:
            results.append(
                result.__class__(
                    target=result.target,
                    success=result.success,
                    request_id=result.request_id,
                    error_kind=result.error_kind,
                    suppressed=False,
                    suppressed_count=suppressed_count,
                )
            )
            # 文本已在路上 → 才谈卡。文本都没发出去（例如没有在线账号）时不追卡，
            # 免得把一个投不出去的告警冷却窗口顺手烧掉。
            if result.success:
                _maybe_dispatch_issue_card(
                    issue,
                    result.target,
                    source_adapter=source_adapter,
                    source_bot=source_bot,
                    session_type=session_type,
                    pipeline=pipeline,
                    capability_id=capability_id,
                    session_id=session_id,
                    group_id=group_id,
                    request_id=request_id,
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

