"""运行时设置咽喉的书面同意执法门（用户裁定第 18 项的执法腿，S-T-CONSENT1 席 2026-09-26）。

一句话
----
把 ``consent.py`` 的同意账与 ``config_risk.py`` 的风险档接进
``domains/chat_reply/runtime/settings.py::RuntimeSettingsStore`` 的**唯一写入咽喉**：
R0 不问就改、R1/R2 先建工单后落地、R3 永不自动改——本仓此前的形态是
「机制在册、生产零调用者」（闸建好了，一条消息都没过去），本件就是那根接线。

四档行为（真值表在 ``config_risk``，本件只消费不复制）
----
- **R0**（``UNATTENDED_CHANGE_TIERS``）：无条件放行，但每次落库照记一行
  ``safetyexec_change_audit``（source=unattended + 旧值指纹 + 回退号）。
- **R1**（``CONSENT_REQUIRED_TIERS`` 非书面半）：首次请求**不落库**，签一张
  管理员在本会话可批的工单；批准凭证被**下一次同值重试**消费后才写。
- **R2**（``WRITTEN_CONSENT_TIERS``，含未登记键的缺省档）：书面同意——工单绑死
  ``(key, 新值, actor)``（绑定指纹由 ``consent.binding_fingerprint`` 现算），
  只有超管从**私聊**亲批（``consent.redeem_from_message`` 的既有阶梯），换值/换键/
  重放一律不作数。
- **R3**（``NEVER_AUTO_TIERS``）：连批准都不给，只回「请主人手动改 .env 并重启」。

凭证的落地形态（为什么是「重试才生效」而不是「批完当场写」）
----
咽喉同步在调用栈上，拿不到入站消息；批准发生在另一条会话腿（``bot.consent`` 命令面，
见 ``domains/ops/capabilities/consent_admin.py``，说法是「同意卡 批 <工单号> <短码>」）。
所以批准把工单置为已消费（``claim_consent``，一次性判定仍全在 ``consent.py``），
本件把凭证按绑定指纹暂存在进程内 ``_grants``；发起方**用同一 (key, 新值, actor) 重试**
时命中凭证才真落库。凭证随工单 ``expires_at`` 一起过期——批完不重试、过了 TTL，
就得重新申请新工单。回退号已随每行审计落账，但**回退执行面本波不接**：
``consent.ConsentLedger._execute`` 的写腿走 ``RuntimeConfigBackend.set_override``，
接进来等于在咽喉上开第二道「自信任」写门，与本门的存在意义正面冲突（挂账见波日志）。

失败面（全部 fail-closed，照 ``consent.py`` 的审计哲学）
----
- 账落不下去 ⇒ 这次改动不做（``AUDIT_UNAVAILABLE``）；写了但终态丢账 ⇒ 记 ``failed``
  并把原异常喊出来（不自行补偿——补偿写腿正是上面那道会互咬的门）。
- 账本装载失败（无路径、无库文件）⇒ R1/R2/R3 一律拒；只有 R0 直写，
  且 `_logger.error` 点名（查无此事的改动只发生在「连账本都没有」这一形态，如实报）。
- 总闸 ``bot_safetyexec_enabled`` 关 ⇒ 本件整体旁路，行为与接线前逐字节一致
  （一键可关是「改现存运行中 bot」的准入条件）。

配置：``bot_safetyexec_enabled``（config.py 真字段，缺省 True＝执法开；
装配期快照进 ``RESTART_REQUIRED_KEYS``）。TTL 走 ``consent.DEFAULT_CONSENT_TTL_MINUTES``，
本波刻意不加第二枚键（席位简报「新配置键最多一枚」）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import IncomingMessage
from plugins.bot_unified_runtime.domains.core.safety_exec import config_risk
from plugins.bot_unified_runtime.domains.core.safety_exec.consent import (
    CHANGE_APPLIED,
    CHANGE_FAILED,
    CHANGE_PENDING,
    CHANGE_REFUSED,
    SOURCE_CONSENTED,
    SOURCE_UNATTENDED,
    ApprovalIntent,
    AuditWriteError,
    ChangeRecord,
    ChangeRequest,
    ConsentGrant,
    ConsentLedger,
    ConsentPolicy,
    ConsentRow,
    ConsentState,
    DenyKind,
    JsonSafetyLedger,
    NeedsConsent,
    Refusal,
    RuntimeConfigBackend,
    SafetyLedgerStore,
    SqliteSafetyLedger,
    aware_now,
    binding_fingerprint,
    new_consent_id,
    new_rollback_id,
    plain_text_for,
    value_pair_for_ledger,
)

__all__ = [
    "ALL_OVERRIDES_TARGET",
    "CODE_LENGTH",
    "RuntimeChangeNeedsConsent",
    "RuntimeChangeRefused",
    "SettingsWriteGate",
    "build_gate_for_store",
    "short_code_of",
]

#: 工单短码 = 绑定指纹前若干位。批语必须回显它，作为「读过卡面」的最小证明
#: （紧急域与回执键两次的教训：能少一位校验就少一位；盲批一长串 hex 不算批过内容）。
CODE_LENGTH = 8

#: 「一次清掉全部覆盖」没有单键可分级，用这个聚合目标名过同一套档（缺省 R2）。
#: 形如标识符是硬要求——``config_risk.normalize_target`` 对怪形直接抛，绝不静默。
ALL_OVERRIDES_TARGET = "ALL_RUNTIME_OVERRIDES"

#: 本门落账/建工单时登记的动作品名（``consent.ChangeRequest`` 的缺省同一枚）。
_ACTION_CONFIG_WRITE = "config.write"

# ---------------------------------------------------------------------------
# 中央句子表（拒绝/待批的人话一律从这里出，调用点禁复制字面量；
# DenyKind 已有的代号优先走 ``consent.plain_text_for``，这里只补它缺的档）
# ---------------------------------------------------------------------------

_APPROVE_HINT_TEMPLATE = (
    "工单 {consent_id}｜短码 {code}\n"
    "这条要主人亲自点头我才改，先把参数原样留着——批之前一个字节都不会动。\n"
    "批：同意卡 批 {consent_id} {code}　　驳：同意卡 驳 {consent_id} {code}\n"
    "工单到 {expires_at} 过期，过期不续；过期就要重新申请一张。\n"
    "批完之后，请原来发起这件事的人用同一参数再说一次——"
    "我照卡上批的那件事落地，凭证一次有效。"
)

_R3_HINT = "这条我不能自己动，请主人手动改 .env 并重启 bot（{target}｜R3）。"

_ENGINE_BROKEN_HINT = (
    "安全执行引擎的账本装不起来，危险档的参数我一个都不改"
    "（{target}｜{tier}）。这不是一句软话：账落不下去的改动比不改更糟。"
)


def short_code_of(row: ConsentRow) -> str:
    """工单短码的唯一派生口（绑定指纹前缀；换一处推导＝两处会漂移）。"""
    return row.binding[:CODE_LENGTH]


def _tier_of(row: ConsentRow) -> config_risk.RiskTier:
    """卡上档位代号 → 分级表枚举（拒绝流水也要按当时的档记账，不统一写缺省档）。"""
    try:
        return config_risk.RiskTier(str(row.tier))
    except ValueError:
        return config_risk.DEFAULT_TIER


def _redact(text: str) -> str:
    """出站前统一打码（盘符路径 / BOT_XXX= / sk- 形态）。懒导入避开装配链重量。"""
    try:
        from plugins.bot_unified_runtime.domains.render.plain_text import (
            redact_local_secrets,
        )

        return redact_local_secrets(text)
    except Exception:  # noqa: BLE001 - 打码件本身坏了不许把安全话术吞掉；回原文并保拒绝成立
        return text


class RuntimeChangeNeedsConsent(ValueError):
    """R1/R2：这次没写，附待批工单的事实。继承 ``ValueError`` 是刻意的——

    既有命令面（``runtime_admin`` / 群策略 handler）都按 ``except ValueError``
    把 ``str(exc)`` 当人话回执投给用户；不改签名、不改异常族，
    工单话术才能今天就走到人眼前。
    """

    def __init__(
        self,
        plain_text: str,
        *,
        consent_id: str,
        short_code: str,
        target: str,
        tier: str,
        expires_at: datetime,
    ) -> None:
        super().__init__(plain_text)
        self.plain_text = plain_text
        self.consent_id = consent_id
        self.short_code = short_code
        self.target = target
        self.tier = tier
        self.expires_at = expires_at


class RuntimeChangeRefused(ValueError):
    """R3 / 账本不可用 / 档位不允许：这次改动被拒，人话与代号一起带出去。"""

    def __init__(self, plain_text: str, *, kind: DenyKind, target: str, tier: str) -> None:
        super().__init__(plain_text)
        self.plain_text = plain_text
        self.kind = kind
        self.target = target
        self.tier = tier


class SettingsWriteGate:
    """咽喉写入的唯一裁决点：按 ``risk_tier_for_target`` 分四档，
    同意账与变更流水全部复用 ``consent.py``（本件零第二本账、零第二套判定表）。

    口径：只裁决「这一次 set/reset 能不能落」；「谁能批、批的是什么」由
    ``consent.ConsentLedger.redeem_from_message`` 判（可信级派生只吃结构化事实）。
    失败：账落不下即拒（``RuntimeChangeRefused``）；``enabled=False`` 时本件整体旁路。
    配置：``bot_safetyexec_enabled``（缺省 True＝执法开，装配期快照）。
    """

    def __init__(
        self,
        *,
        settings_store: Any,
        config: object = None,
        ledger_store: SafetyLedgerStore | None = None,
        policy: ConsentPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = settings_store
        self._config = config
        self._clock = clock
        self._policy = policy if policy is not None else ConsentPolicy.from_config(
            config if config is not None else {}
        )
        self._ledger_store = ledger_store
        self._backend = (
            RuntimeConfigBackend(settings_store, config)
            if self._policy.enabled and settings_store is not None
            else None
        )
        self._ledger: ConsentLedger | None = None
        self._ledger_failed = False
        self._grants: dict[str, ConsentGrant] = {}
        self._lock = threading.Lock()

    # ---- 状态面（consent_admin 命令面与测试用） ----

    @property
    def enabled(self) -> bool:
        return bool(self._policy.enabled)

    def _now(self) -> datetime:
        return aware_now(self._clock)

    def _ensure_ledger(self) -> ConsentLedger:
        if self._ledger is not None:
            return self._ledger
        if self._ledger_failed or not self._policy.enabled:
            raise AuditWriteError("安全执行引擎的账本没有装载成功（或总闸关着）")
        try:
            if self._ledger_store is None:
                self._ledger_store = self._build_ledger_store()
            self._ledger = ConsentLedger(
                self._ledger_store,
                backend=self._backend,
                policy=self._policy,
                clock=self._clock,
            )
        except (AuditWriteError, OSError, ValueError, TypeError) as exc:
            self._ledger_failed = True
            raise AuditWriteError(f"账本装载失败：{type(exc).__name__}: {exc}") from exc
        return self._ledger

    def _build_ledger_store(self) -> SafetyLedgerStore:
        """两态后端同 ``consent.build_store`` 口径：有控制面配置库就复用它**同一个库文件**，
        否则退到设置文件同目录的 append-only JSON 账。拿不到落点即抛（=账本不可用）。
        """
        config_backend = getattr(self._store, "config_backend", None)
        if config_backend is not None:
            return SqliteSafetyLedger.from_config_store(config_backend)
        path = getattr(self._store, "path", None)
        if isinstance(path, (str, Path)) and str(path).strip():
            return JsonSafetyLedger(Path(str(path)).expanduser().parent)
        raise ValueError("同意账需要设置文件目录或控制面配置库之一作为落点")

    # ---- 咽喉裁决 ----

    def guarded_write(
        self,
        *,
        key: str,
        value: Any,
        restore_default: bool,
        actor: str,
        request_id: str,
        session_key: str,
        apply: Callable[[], Any],
    ) -> Any:
        """一次覆盖写/撤的裁决：放行则返回 ``apply()`` 的结果，否则抛 ``ValueError`` 族。"""
        # actor 归一排在一切绑定计算**之前**：卡上的 requester 与重试时现算的
        # binding 必须吃同一个字符串，空 actor 若两侧各归一各的（binding 用 ""、
        # 卡用 "runtime_internal"），凭证永远对不上号 ⇒ R2 写陷入「批了也写不进」
        # 的死循环工单。缺省名只准在这一处定形。
        actor = actor or "runtime_internal"
        tier = config_risk.risk_tier_for_target(key)
        if config_risk.is_never_auto(tier):
            self._note_refusal(key, tier, actor=actor, request_id=request_id,
                               kind=DenyKind.NEVER_AUTO, detail="R3 永不自动改")
            raise RuntimeChangeRefused(
                _redact(f"{plain_text_for(DenyKind.NEVER_AUTO)}\n"
                        + _R3_HINT.format(target=key)),
                kind=DenyKind.NEVER_AUTO, target=key, tier=tier.value,
            )
        if config_risk.allows_unattended_change(tier):
            return self._apply_with_audit(
                key=key, tier=tier, value=value, restore_default=restore_default,
                actor=actor, request_id=request_id, consent=None,
                source=SOURCE_UNATTENDED, apply=apply,
            )
        # R1/R2：先找「批过的凭证」，没有就给一张待批工单。
        try:
            ledger = self._ensure_ledger()
        except AuditWriteError as exc:
            raise RuntimeChangeRefused(
                _redact(_ENGINE_BROKEN_HINT.format(target=key, tier=tier.value)
                        + f"\n{exc}"),
                kind=DenyKind.AUDIT_UNAVAILABLE, target=key, tier=tier.value,
            ) from exc
        current = self._backend.effective_value(key) if self._backend is not None else None
        before_fp, _sensitive, _kept = value_pair_for_ledger(key, current)
        after_fp = (
            config_risk.RESTORE_DEFAULT_FINGERPRINT
            if restore_default
            else _fingerprint(value)
        )
        binding = binding_fingerprint(
            action_id=_ACTION_CONFIG_WRITE,
            target=key,
            before_fingerprint=before_fp,
            after_fingerprint=after_fp,
            requester=actor,
        )
        grant = self._take_valid_grant(binding)
        if grant is not None:
            return self._apply_with_audit(
                key=key, tier=tier, value=value, restore_default=restore_default,
                actor=actor, request_id=request_id, consent=grant,
                source=SOURCE_CONSENTED, apply=apply,
            )
        need = self._issue_or_reuse_ticket(
            ledger=ledger, key=key, tier=tier, value=value,
            restore_default=restore_default, actor=actor,
            request_id=request_id, session_key=session_key, binding=binding,
        )
        if isinstance(need, Refusal):
            raise RuntimeChangeRefused(
                _redact(need.line()), kind=need.kind, target=key, tier=tier.value
            )
        row = need.ticket.row
        text = _redact(
            need.plain_text()
            + "\n"
            + _APPROVE_HINT_TEMPLATE.format(
                consent_id=row.consent_id,
                code=short_code_of(row),
                expires_at=row.expires_at.isoformat(),
            )
        )
        raise RuntimeChangeNeedsConsent(
            text,
            consent_id=row.consent_id,
            short_code=short_code_of(row),
            target=key,
            tier=tier.value,
            expires_at=row.expires_at,
        )

    # ---- 批准/驳回（唯一入口：``bot.consent`` 命令面；批语必须是一条入站消息） ----

    def approve(self, consent_id: object, *, code: object, message: IncomingMessage):
        return self._adjudicate(consent_id, code=code, message=message, approved=True)

    def deny(self, consent_id: object, *, code: object, message: IncomingMessage):
        return self._adjudicate(consent_id, code=code, message=message, approved=False)

    def ticket(self, consent_id: object):
        """按同意号查一张卡（命令面的「看 <工单号>」用；只读，不消费任何东西）。"""
        if not self.enabled:
            return None
        try:
            return self._ensure_ledger().ticket(str(consent_id or "").strip())
        except (AuditWriteError, OSError, ValueError):
            return None

    def _adjudicate(
        self, consent_id: object, *, code: object, message: IncomingMessage, approved: bool
    ):
        """短码先对卡面，再走 ``redeem_from_message`` 的既有阶梯（权限/私聊/原会话/
        防自批/一次性/TTL）。

        短码不符 ⇒ 连「批/驳」都不算（工单保持 pending）；这里**不消费**任何东西。
        但**必须留痕**：不记账的拒绝面是一条可以无限试的公开猜号路（一次误码什么
        都不落，试一千次也什么都不落——「查无此事的批准尝试」比查有此事更糟）。
        """
        wanted = str(consent_id or "").strip()
        if not self.enabled:
            return Refusal(DenyKind.ENGINE_DISABLED, wanted or "?", config_risk.DEFAULT_TIER.value)
        try:
            ledger = self._ensure_ledger()
        except (AuditWriteError, OSError, ValueError) as exc:
            return Refusal(
                DenyKind.AUDIT_UNAVAILABLE, wanted or "?",
                config_risk.DEFAULT_TIER.value, detail=f"账本装不起来：{exc}",
            )
        ticket = ledger.ticket(wanted)
        if ticket is None:
            return Refusal(DenyKind.UNKNOWN_CONSENT, wanted or "?", config_risk.DEFAULT_TIER.value)
        row = ticket.row
        presented = str(code or "").strip()
        if presented != short_code_of(row):
            self._note_refusal(
                row.target, _tier_of(row),
                actor=str(getattr(message, "sender_id", "") or "unknown_approver"),
                request_id=str(getattr(message, "request_id", "") or ""),
                kind=DenyKind.APPROVAL_CODE_MISMATCH,
                detail=f"同意号 {row.consent_id} 的卡面短码没对上（工单仍待批，未消费）",
            )
            return Refusal(
                DenyKind.APPROVAL_CODE_MISMATCH, row.target, row.tier,
                detail="卡面短码是 "
                       f"{short_code_of(row)}，来句里念的是另一串——这张卡不作数、也还在有效期内。",
            )
        verdict = ledger.redeem_from_message(
            wanted,
            message,
            intent=ApprovalIntent(consent_id=row.consent_id, approved=approved),
        )
        if isinstance(verdict, ConsentGrant) and approved:
            with self._lock:
                self._grants[row.binding] = verdict
        return verdict

    def pending_tickets(self) -> list:
        if not self.enabled:
            return []
        try:
            return self._ensure_ledger().pending_tickets()
        except (AuditWriteError, OSError, ValueError):
            return []

    def change_history(self, *, limit: int = 10) -> list[ChangeRecord]:
        if not self.enabled:
            return []
        try:
            return self._ensure_ledger().change_history(limit=limit)
        except (AuditWriteError, OSError, ValueError):
            return []

    # ---- 内部 ----

    def _take_valid_grant(self, binding: str) -> ConsentGrant | None:
        """一次性消费凭证：命中即摘除；随工单 ``expires_at`` 一起过期。"""
        with self._lock:
            grant = self._grants.pop(binding, None)
        if grant is None:
            return None
        if self._now() >= grant.row.expires_at:
            return None
        if grant.row.state != ConsentState.CONSUMED.value:
            return None
        return grant

    def _issue_or_reuse_ticket(
        self,
        *,
        ledger: ConsentLedger,
        key: str,
        tier: config_risk.RiskTier,
        value: Any,
        restore_default: bool,
        actor: str,
        request_id: str,
        session_key: str,
        binding: str,
    ):
        # 同 (key, 新值, actor) 的未过期 pending 卡直接复用：调度器每 30 秒撞一次门
        # 不该刷出第二张卡（append-only 账也会按调用数无限膨胀）。
        # `ConsentLedger.pending_tickets()` 交回的是 **ConsentTicket**（壳），
        # 绑定住在 `.row` 上——首版把壳当行用（`row.binding`）是 mypy :438/:439
        # 两枚报错的本体；这里直接复用现成的壳，不 `_ticket(row)` 再包一层。
        try:
            for ticket in ledger.pending_tickets():
                if ticket.row.binding == binding:
                    return NeedsConsent(ticket=ticket, target=key, tier=tier.value)
        except (AuditWriteError, OSError, ValueError):
            pass  # 读挂了就照常签新卡；签卡失败另有 AUDIT_UNAVAILABLE 分支兜住
        return ledger.request_consent(
            ChangeRequest(
                target=key,
                value=None if restore_default else value,
                requester=actor or "runtime_internal",
                action_id=_ACTION_CONFIG_WRITE,
                source_session_key=session_key,
                request_id=request_id,
                restore_default=restore_default,
                reason="settings throat",
            )
        )

    def _apply_with_audit(
        self,
        *,
        key: str,
        tier: config_risk.RiskTier,
        value: Any,
        restore_default: bool,
        actor: str,
        request_id: str,
        consent: ConsentGrant | None,
        source: str,
        apply: Callable[[], Any],
    ) -> Any:
        """账先落、再动手、终态回写——与 ``consent.ConsentLedger._execute`` 同一节拍
        （但走咽喉注入的 raw apply，绝不再进 ``set_override`` 开第二道自信任门）。
        """
        try:
            self._ensure_ledger()  # 只为「装得上」这件事；装不上即拒这次改动（下面 except）
        except AuditWriteError as exc:
            raise RuntimeChangeRefused(
                _redact(_ENGINE_BROKEN_HINT.format(target=key, tier=tier.value) + f"\n{exc}"),
                kind=DenyKind.AUDIT_UNAVAILABLE, target=key, tier=tier.value,
            ) from exc
        current = self._backend.effective_value(key) if self._backend is not None else None
        before_fp, sensitive, before_kept = value_pair_for_ledger(key, current)
        after_fp = (
            config_risk.RESTORE_DEFAULT_FINGERPRINT
            if restore_default
            else _fingerprint(value)
        )
        record = ChangeRecord(
            change_id=new_consent_id(),
            target=key,
            action_id=_ACTION_CONFIG_WRITE,
            tier=tier.value,
            requester=actor or "runtime_internal",
            actor=actor or "runtime_internal",
            state=CHANGE_PENDING,
            before_fingerprint=before_fp,
            after_fingerprint=after_fp,
            created_at=self._now(),
            consent_id=consent.consent_id if consent is not None else "",
            approved_by=consent.approved_by if consent is not None else "",
            approved_at=consent.approved_at if consent is not None else None,
            rollback_id=new_rollback_id(),
            before_value=None if sensitive else before_kept,
            applied_value=None if sensitive else (None if restore_default else value),
            value_is_sensitive=sensitive,
            restore_default=restore_default,
            request_id=request_id,
            reason=f"source={source}",
        )
        try:
            self._ledger_store_append(record)
        except (AuditWriteError, OSError, ValueError) as exc:
            raise RuntimeChangeRefused(
                _redact(f"{plain_text_for(DenyKind.AUDIT_UNAVAILABLE)}（{key}｜{tier.value}）\n{exc}"),
                kind=DenyKind.AUDIT_UNAVAILABLE, target=key, tier=tier.value,
            ) from exc
        try:
            applied = apply()
        except Exception as exc:  # 写失败要落 failed 终态并原样喊出去
            detail = f"{type(exc).__name__}: {exc}"
            try:
                self._ledger_store_update(record.change_id, state=CHANGE_FAILED, reason=detail)
            except (AuditWriteError, OSError, ValueError):
                pass  # pending 行已在账上，绝不叠第二层静默
            raise
        final_reason = record.reason
        applied_fp = _fingerprint(applied)
        if not restore_default and applied_fp != after_fp:
            final_reason = (
                f"{final_reason}\n注意：写进去再读回来是 {applied_fp}，与批的 {after_fp} "
                "不一致（转换器改了形），已如实记账，不谎称一致。"
            )
        try:
            self._ledger_store_update(
                record.change_id, state=CHANGE_APPLIED, reason=final_reason
            )
        except (AuditWriteError, OSError, ValueError) as exc:
            # 与 _execute 同判：已改却落不下终态 ⇒ 不许假称账全对；把两件事一起喊出来。
            raise RuntimeChangeRefused(
                _redact(
                    f"{plain_text_for(DenyKind.AUDIT_UNAVAILABLE)}（{key}｜{tier.value}）\n"
                    f"参数已经写成 {applied_fp}，但终态没落进账（{exc}）——请人工核对这一条。"
                ),
                kind=DenyKind.AUDIT_UNAVAILABLE, target=key, tier=tier.value,
            ) from exc
        return applied

    def _ledger_store_append(self, record: ChangeRecord) -> None:
        store = self._ledger_store
        if self._ledger is None or store is None:
            # fail-closed：账体缺席 ⇒ **拒绝这次变更**（不放行）——调用方
            # `_apply_with_audit` 把 AuditWriteError 翻成 RuntimeChangeRefused
            # (AUDIT_UNAVAILABLE)。与 consent.py「落不下去账就不改」同一节拍。
            raise AuditWriteError("账本未装载")
        store.append_change(record)

    def _ledger_store_update(self, change_id: str, *, state: str, reason: str) -> None:
        store = self._ledger_store
        if self._ledger is None or store is None:
            raise AuditWriteError("账本未装载")
        store.update_change(change_id, state=state, reason=reason)

    def _note_refusal(
        self, key: str, tier: config_risk.RiskTier, *, actor: str, request_id: str,
        kind: DenyKind, detail: str,
    ) -> None:
        """被拒的每一次也各落一条 `refused` 流水（best-effort，记账失败不反客为主）。"""
        try:
            self._ensure_ledger()  # 同 `_apply_with_audit`：判据是「装得上」，不是取值
        except AuditWriteError:
            return
        record = ChangeRecord(
            change_id=new_consent_id(),
            target=key,
            action_id=_ACTION_CONFIG_WRITE,
            tier=tier.value,
            requester=actor or "runtime_internal",
            actor=actor or "runtime_internal",
            state=CHANGE_REFUSED,
            before_fingerprint="",
            after_fingerprint="",
            created_at=self._now(),
            request_id=request_id,
            reason=f"{kind.value}: {detail}".strip(),
        )
        try:
            ledger_store = self._ledger_store
            if ledger_store is None:
                ledger_store = self._build_ledger_store()
                self._ledger_store = ledger_store
            ledger_store.append_change(record)
        except (AuditWriteError, OSError, ValueError):
            pass


def _fingerprint(value: Any) -> str:
    return config_risk.fingerprint_value(value)


def build_gate_for_store(store: Any, config: object, *, clock=None) -> SettingsWriteGate:
    """装配口：由设置仓与 Config 现造一道门（账本落点惰性决定，构造零落盘）。

    口径：``consent.ConsentPolicy.from_config`` 只在这条路上读一次（装配期快照），
    与「总闸看起来能热改」这种假象绝缘。
    失败：本函数不抛——抛点在第一次写（``guarded_write`` 的 AUDIT_UNAVAILABLE 分支）。
    配置：``bot_safetyexec_enabled``。
    """
    policy = ConsentPolicy.from_config(config if config is not None else {})
    return SettingsWriteGate(settings_store=store, config=config, policy=policy, clock=clock)
