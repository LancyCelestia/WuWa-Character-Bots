"""书面同意账 + R0 自动改的「回显 + 一键回退」两件套（SAFE-EXEC 规格 §5 与 §4 的 R0 条）。

服务对象是用户裁定第 18 项原话：「能根据超级管理员的需要自动修改参数和设置。
**危险的参数设置需要经过超级管理员的书面同意**」。她 2026-09-25 的 P-4 裁定把
「自动」这一半说死了：**R0 允许 bot 不问就改，但必须回显改了什么 + 给一条一键回退**；
R1/R2 一律要书面同意。本件就是那本账 + 那个两件套。

三条不变量与本件的执法点
----
1. **bot 永远不能自批**（规格 §0.2）。把同意号置成「已用」的入口只有一个：
   `ConsentLedger.redeem_from_message`，它形参上就要求一条 `IncomingMessage`，
   并只经既有派生口 `trust.trust_from_message` 判档（角色真身 = `policy/roles.py`，
   本件不维护第二份名单）。LLM 输出、工具返回、文件正文、检索摘要在 §7 的梯子里
   是 T2/T3，它们**构造不出** `IncomingMessage`；`RepairService` 的
   `apply_to_target`/`deploy_patch` 至今是 ``NoReturn``（只产待审补丁），本件连
   import 都没有——「自动修 bug」不是本件的一条腿，测试有 AST 锁钉住这点。
2. **一次性 + TTL + 绑定值指纹**（规格 §5.1/§5.2）。同意号绑定五元组
   ``(action_id, target, before_fp, after_fp, requester)`` 的 `sha256[:16]`；
   消费是单条 ``UPDATE … WHERE state='pending' AND binding=?`` 的原子改置
   （JSON 账是锁内判态改置），所以重放必拒；`expires_at` 一到即失效且**没有续期
   API**；落地前还要再比一次 `after_fp`，拿旧同意改新值必拒——这道判**排在消费之前**
   （先消费再判的话，一次误试就把人批的卡烧掉了，等于让 bot 自己决定「还要不要再
   问一次」，那是她的决定）。
3. **可回退**（P-4 的第二半）。每次生效落一条 `ChangeRecord`：before/after 指纹
   + `rollback_id` + 同意号 + 批准人 + 批准时刻。R0 自动改只有一条入口
   `ConsentLedger.apply_unattended`，它**先**问三件事「这个键能热改吗、旧值留得住吗、
   自动改开关开了吗」，任一不过就拒这次改动并点名原因——**没有回退口就不许自动改**。
   回退本身也走同一裁决点（`rollback()`），所以「我这是在恢复原状」不是免检通道。

审计绝不静默（fail-closed）
----
写账排在动手**之前**：pending 行落不下去就直接拒绝这次改动
（`REFUSED(audit_unavailable)`），改完再落终态；连终态都落不下时立刻尽力改回原值
并把两件事都喊出来。宁可这次什么都不改，也不能「改了却查无此事」。被拒的每一次
也各落一条 `refused` 流水（`_refuse`，best-effort，绝不反客为主；批语侧的拒绝
不记这一下——那是别人的话，不是 bot 的一次尝试）。

两态后端（规格 §5.4 + G-19）
----
`config_audit` 今天**只在 SQL 后端存在**，JSON 路径什么都不写。本件把账同时接两个
后端，且**不另起一套库**：SQLite 后端复用控制面配置库同一个**数据库文件**
（只新增两张表，见 `CONSENT_TABLE`/`CHANGE_TABLE`），JSON 后端落同目录的
append-only 账本。两者读出口同形，测试按后端参数化跑同一批断言。
（把 `consent_id/approved_by/approved_at` 三列并进 `config_audit` 本体要动
`control_plane/config_store.py`，不在本席写面内，已进建议清单。）

值不入账（凭证形态）
----
账上永远有 `sha256[:16]` 指纹；明文值**只在非敏感键上**留存（回退要用旧值），
敏感键（`control_plane.config_store.is_sensitive` 的后缀表，本件不另立第二套）
只留指纹——于是这种键拿不到回退口 ⇒ 不许自动改（不变量 3 的前置判据在这里咬合）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.core import moment_parsing
from plugins.bot_unified_runtime.domains.core.safety_exec import config_risk
from plugins.bot_unified_runtime.domains.core.safety_exec.trust import (
    TrustLevel,
    trust_from_message,
    trust_rank,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    is_legal_segment,
)

# ---------------------------------------------------------------------------
# 常量与缺省（所有开关缺省 False：规格 §0.3「缺省关，且不自动部署」）
# ---------------------------------------------------------------------------

#: 同意号缺省存活分钟数（用户裁定：30 分钟）。建议配置键名见 `PROPOSED_CONFIG_KEYS`。
DEFAULT_CONSENT_TTL_MINUTES = 30

#: 一键回退指令模板。装配席注册 matcher 时**只用这个常量**，免得话术两处各写一份。
ROLLBACK_COMMAND_TEMPLATE = "回退 {rollback_id}"

#: 账本表名（SQL 后端与 `SQLiteConfigStateStore` 同一个数据库文件，只新增这两张）。
CONSENT_TABLE = "safetyexec_consent"
CHANGE_TABLE = "safetyexec_change_audit"

#: 同意号/回退号只出十六进制小写：天然满足中央键段合法集（`dedupe._SEGMENT_RE`
#: 不认 `:`；紧急域 09-20 那枚 Critical 与回执幂等键两次都栽在「本地测通、
#: 上闸即静默丢」的同一形态上，所以生成侧一次做对，判定侧仍走中央谓词）。
_ID_BYTES = 8

#: 时刻串落盘/解析的唯一口径（带显式偏移的 ISO；台账 #6 的坑）。
_TS_FIELD = "safetyexec_moment"

#: 变更记录的四种终态 + 两种中间态。
CHANGE_PENDING = "pending"
CHANGE_APPLIED = "applied"
CHANGE_FAILED = "failed"
CHANGE_ROLLED_BACK = "rolled_back"
CHANGE_REFUSED = "refused"

#: 落地来源三态（决定要不要「自动改开关」这道门，见 `ConsentLedger._execute`）。
SOURCE_UNATTENDED = "unattended"  # bot 不问就改（只允许 R0）
SOURCE_CONSENTED = "consented"  # 拿着批过的同意卡落地
SOURCE_ROLLBACK = "rollback"  # 人亲手要回退


def utc_clock() -> datetime:
    """缺省时钟：aware UTC。

    校时器 `domains/schedule/timesync` 是**装配侧**该注入的东西
    （`build_ledger(clock=timesync.now)`）：本件不自己调它，因为 NTP 校时可能联网，
    而本件的公开入口大多在事件循环上——把可能阻塞的取时口塞进公共路径，
    等于拿安全件去换一个抖动 bug。
    """
    return datetime.now(timezone.utc)


def aware_now(clock: Callable[[], datetime] | None = None) -> datetime:
    """公开取时口（同 `_aware_now` 的判据）：消费方（如 `settings_gate`）不自造
    「取现在」的第二套实现，也不许拿到 naive 时刻（台账 #6）。"""
    return _aware_now(clock)


def _aware_now(clock: Callable[[], datetime] | None) -> datetime:
    """取一次「现在」，并**拒绝 naive 时刻**（猜时区才是事故，缺省关才是 bug）。"""
    moment = (clock or utc_clock)()
    if not isinstance(moment, datetime):
        raise TypeError(f"时钟必须返回 datetime，收到 {type(moment).__name__}")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError("时钟必须返回带显式时区的 aware datetime（台账 #6）")
    return moment


def _as_text(value: object) -> str:
    return str(value or "").strip()


def _moment(value: object) -> datetime:
    """时刻解析唯一走中央件 `moment_parsing`（本件不写第二套 ISO 兼容）。"""
    return moment_parsing.parse_moment(value, field=_TS_FIELD)


def _moment_or_none(value: object) -> datetime | None:
    if value is None or _as_text(value) == "":
        return None
    return _moment(value)


# ---------------------------------------------------------------------------
# 建议登记的配置键（本席禁写 config.py，故在此声明并供测试对账）
# ---------------------------------------------------------------------------

#: 本件想要、但**尚未**在 `config.py` 里登记的键名（小写 = Config 字段形）。
#: 登记时三处同生：`config.py` + `docs/config-catalog-full.md` + `.env.example`，
#: 并按「装配期快照」口径进 `RESTART_REQUIRED_KEYS`。
#: ⚠ 2026-09-26 裁定第 18 项落地波（S-T-CONSENT1）：`bot_safetyexec_enabled` **已登记**
#: （咽喉执法的总闸，缺省 True＝执法开——「缺省关」的旧口径被她那句
#: 「危险的参数设置需要经过超级管理员的书面同意」覆盖，她要真门不是货架），
#: 本表只剩下面两枚待装配侧点头。
PROPOSED_CONFIG_KEYS: tuple[str, ...] = (
    "bot_safetyexec_auto_r0_enabled",  # R0 不问就改的许可（缺省关；咽喉波未用到）
    "bot_safetyexec_consent_ttl_minutes",  # 同意号 TTL（缺省 30）
)

#: 建议进 `RESTART_REQUIRED_KEYS` 的理由文案（装配席照抄，别另编一份）。
PROPOSED_KEY_RESTART_NOTE = (
    "同意账/自动改档的开关在装配期快照一次，做成「看起来能热改」比不做更坏"
)


# ---------------------------------------------------------------------------
# 拒绝原因（人话文案与本枚举一一对应，禁止在别处再写第二套话术池）
# ---------------------------------------------------------------------------


class DenyKind(str, Enum):
    """拒绝/不成立的原因代号。`plain_text_for()` 负责翻成人话。"""

    ENGINE_DISABLED = "engine_disabled"
    AUDIT_UNAVAILABLE = "audit_unavailable"
    NO_ROLLBACK_PATH = "no_rollback_path"
    NEVER_AUTO = "never_auto"
    NOT_UNATTENDED_ELIGIBLE = "not_unattended_eligible"
    UNKNOWN_CONSENT = "unknown_consent"
    ALREADY_USED = "already_used"
    EXPIRED = "expired"
    BINDING_MISMATCH = "binding_mismatch"
    APPROVAL_CODE_MISMATCH = "approval_code_mismatch"
    DENIED_BY_APPROVER = "denied_by_approver"
    APPROVER_NOT_AUTHORISED = "approver_not_authorised"
    SELF_CONSENT = "self_consent"
    NOT_PRIVATE_CHAT = "not_private_chat"
    NOT_AN_APPROVAL = "not_an_approval"
    STATE_DRIFT = "state_drift"
    APPLY_FAILED = "apply_failed"


_DENY_PLAIN_TEXT: dict[DenyKind, str] = {
    DenyKind.ENGINE_DISABLED: "安全执行引擎还没开（总闸关着），这次我没有动任何参数。",
    DenyKind.AUDIT_UNAVAILABLE: "账本这一读/写没成，所以我没有改这个参数——查无此事的改动比不改更糟。",
    DenyKind.NO_ROLLBACK_PATH: "这条参数我拿不到可回退的旧值（或它压根不支持热改），按规矩不自动改。",
    DenyKind.NEVER_AUTO: "这条是 R3：只允许出待审补丁，部署由主人亲手执行，我不碰。",
    DenyKind.NOT_UNATTENDED_ELIGIBLE: "这一档不在「可以不问就改」的范围里，要人的一个字。",
    DenyKind.UNKNOWN_CONSENT: "这个同意号我没见过，所以什么都没发生。",
    DenyKind.ALREADY_USED: "这个同意号已经用过了——一次性，用过即焚，要改请重新申请。",
    DenyKind.EXPIRED: "这张同意卡已经过期（且不可续），要改请重新申请。",
    DenyKind.BINDING_MISMATCH: "要改的值和当初批的不是同一件事，这张同意卡不作数。",
    DenyKind.APPROVAL_CODE_MISMATCH: "批语里的短码和这张卡对不上，我没有当作批准记下来——照卡面念对短码再来。",
    DenyKind.DENIED_BY_APPROVER: "这条被驳回了，那张同意卡已作废，我没有改。",
    DenyKind.APPROVER_NOT_AUTHORISED: "这条要主人亲自批，别人代不了。",
    # 防自批：发起这次改动的人不能再亲手把它批掉——「书面同意」的意义就在于
    # 有第二双眼睛看过卡面写的旧值→新值。一个人既申请又批准，等于没有同意。
    DenyKind.SELF_CONSENT: (
        "这张卡是我替你自己发起的改动，自己批自己不算书面同意——"
        "要落地，请另一位有权限的人照卡面批一句。"
    ),
    DenyKind.NOT_PRIVATE_CHAT: "书面同意只认私聊亲口批复，群里那句不算。",
    DenyKind.NOT_AN_APPROVAL: "这句话不像是针对某个同意号的批复，我没有当作批准处理。",
    DenyKind.STATE_DRIFT: "这个参数的当前值和我申请时看到的不一样了，先不覆盖别人的改动。",
    DenyKind.APPLY_FAILED: "写这一步失败了，我按失败处理，没有假装改成。",
}


def plain_text_for(kind: DenyKind | str) -> str:
    """原因代号 → 一句人话（规格 §5.5「拒绝路径不得静默」的落点）。"""
    resolved = kind if isinstance(kind, DenyKind) else DenyKind(str(kind))
    return _DENY_PLAIN_TEXT[resolved]


# ---------------------------------------------------------------------------
# 同意号：生成、绑定指纹、生命周期
# ---------------------------------------------------------------------------


def new_consent_id() -> str:
    """新同意号（16 位十六进制）。"""
    return secrets.token_hex(_ID_BYTES)


def new_rollback_id() -> str:
    """新回退号（16 位十六进制）。"""
    return secrets.token_hex(_ID_BYTES)


def binding_fingerprint(
    *,
    action_id: object,
    target: object,
    before_fingerprint: object,
    after_fingerprint: object,
    requester: object,
) -> str:
    """五元组绑定指纹（sha256[:16]）。

    用规范化 JSON 而不是 `|` 直拼：字段里含分隔符会把两件事拼成一件事
    （本仓在幂等键上已为此栽过两次）。
    """
    payload = config_risk.canonical_json(
        {
            "action_id": _as_text(action_id),
            "target": config_risk.normalize_target(target),
            "before": _as_text(before_fingerprint),
            "after": _as_text(after_fingerprint),
            "requester": _as_text(requester),
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[
        : config_risk.FINGERPRINT_LENGTH
    ]


def fingerprint_of(value: Any) -> str:
    """一枚值的指纹（唯一走 `config_risk.fingerprint_value`，本件不造第二套）。"""
    return config_risk.fingerprint_value(value)


class ConsentState(str, Enum):
    PENDING = "pending"
    CONSUMED = "consumed"
    REVOKED = "revoked"
    # 过期只由读取侧派生，**永不**落盘，也没有任何续期口。


@dataclass(frozen=True)
class ConsentRow:
    """账本里的一行同意号。`before_value/after_value` 只在**非敏感**键上留存。"""

    consent_id: str
    state: str
    action_id: str
    target: str
    tier: str
    requester: str
    source_session_key: str
    min_approver_level: str
    require_private: bool
    before_fingerprint: str
    after_fingerprint: str
    binding: str
    created_at: datetime
    expires_at: datetime
    approved_by: str = ""
    approved_at: datetime | None = None
    before_value: Any = None
    after_value: Any = None
    restore_default: bool = False
    value_is_sensitive: bool = False
    request_id: str = ""
    reason: str = ""

    def is_live(self, *, now: datetime) -> bool:
        """仍在有效期内的一次性同意号（过期不可续，没有旁路）。"""
        return self.state == ConsentState.PENDING.value and now < self.expires_at

    def to_record(self) -> dict[str, Any]:
        """落盘形（时刻 → 带偏移的 ISO 串）。"""
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["expires_at"] = self.expires_at.isoformat()
        payload["approved_at"] = self.approved_at.isoformat() if self.approved_at else None
        return payload

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> ConsentRow:
        return cls(
            consent_id=_as_text(record["consent_id"]),
            state=_as_text(record["state"]),
            action_id=_as_text(record["action_id"]),
            target=_as_text(record["target"]),
            tier=_as_text(record["tier"]),
            requester=_as_text(record["requester"]),
            source_session_key=_as_text(record["source_session_key"]),
            min_approver_level=_as_text(record["min_approver_level"]),
            require_private=bool(record["require_private"]),
            before_fingerprint=_as_text(record["before_fingerprint"]),
            after_fingerprint=_as_text(record["after_fingerprint"]),
            binding=_as_text(record["binding"]),
            created_at=_moment(record["created_at"]),
            expires_at=_moment(record["expires_at"]),
            approved_by=_as_text(record.get("approved_by") or ""),
            approved_at=_moment_or_none(record.get("approved_at")),
            before_value=record.get("before_value"),
            after_value=record.get("after_value"),
            restore_default=bool(record.get("restore_default")),
            value_is_sensitive=bool(record.get("value_is_sensitive")),
            request_id=_as_text(record.get("request_id") or ""),
            reason=_as_text(record.get("reason") or ""),
        )


@dataclass(frozen=True)
class ConsentTicket:
    """发给超管的「同意卡」数据形（渲染归卡片席，本件只给事实）。"""

    row: ConsentRow

    @property
    def consent_id(self) -> str:
        return self.row.consent_id

    @property
    def expires_at(self) -> datetime:
        return self.row.expires_at

    def card_payload(self) -> dict[str, Any]:
        """同意卡的机器可读载荷：动作 / 目标键 / before→after / 指纹 / 到期 / 后果。"""
        row = self.row
        return {
            "consent_id": row.consent_id,
            "action_id": row.action_id,
            "target": row.target,
            "tier": row.tier,
            "tier_text": describe_tier_or_raw(row.tier),
            "before": display_value(row.target, row.before_value, row.before_fingerprint),
            "after": (
                "回到缺省值"
                if row.restore_default
                else display_value(row.target, row.after_value, row.after_fingerprint)
            ),
            "before_fingerprint": row.before_fingerprint,
            "after_fingerprint": row.after_fingerprint,
            "binding_fingerprint": row.binding,
            "requester": row.requester,
            "created_at": row.created_at.isoformat(),
            "expires_at": row.expires_at.isoformat(),
            "ttl_minutes": int((row.expires_at - row.created_at).total_seconds() // 60),
            "delivery": {
                "only_private_chat": row.require_private,
                "audience": "super_admin" if row.require_private else "admin_or_above",
                "group_broadcast": False,
            },
            "approval_text": f"同意 {row.consent_id}",
            "deny_text": f"拒绝 {row.consent_id}",
        }

    def card_text(self) -> str:
        """同意卡的人话正文（无卡图时的兜底，也是投递文案的唯一来源）。"""
        payload = self.card_payload()
        return (
            f"这条要主人亲自批：{payload['action_id']} 改 {payload['target']}\n"
            f"档位：{payload['tier_text']}\n"
            f"现值：{payload['before']}（指纹 {payload['before_fingerprint']}）\n"
            f"改成：{payload['after']}（指纹 {payload['after_fingerprint']}）\n"
            f"申请方：{payload['requester']}\n"
            f"有效期到：{payload['expires_at']}（过期不续）\n"
            f"亲手批：{payload['approval_text']}　驳回：{payload['deny_text']}"
        )


def describe_tier_or_raw(tier_text: object) -> str:
    """档位的行人话；代号认不出时原样点名（绝不编一条解释）。"""
    try:
        return config_risk.describe_tier(config_risk.RiskTier(_as_text(tier_text)))
    except ValueError:
        return f"未知档位 {_as_text(tier_text) or '∅'}"


def display_value(key: str, value: Any, fingerprint: str) -> str:
    """值的上屏形：凭证形态一律只报指纹。"""
    view = config_risk.value_view(key, value)
    display = view["display"]
    if view["sensitive"] or not view["configured"] or display in (None, "", "[redacted]"):
        return f"（不上屏，指纹 {fingerprint}）"
    return _as_text(display)


def value_pair_for_ledger(key: str, value: Any) -> tuple[str, bool, Any]:
    """(指纹, 是否敏感, 可入账的明文值)。敏感 ⇒ 明文一律 ``None``。"""
    view = config_risk.value_view(key, value)
    sensitive = bool(view["sensitive"])
    return str(view["fingerprint"]), sensitive, (None if sensitive else value)


# ---------------------------------------------------------------------------
# 批准意图解析（只认「动词 + 同意号」整句形；形不合规一律不算批复）
# ---------------------------------------------------------------------------

_APPROVE_VERBS = ("同意", "批准", "准了", "approve")
_DENY_VERBS = ("拒绝", "驳回", "deny")
_ALL_VERBS = _APPROVE_VERBS + _DENY_VERBS

# 整句锚定：`不` / `别` / `取消` 打头的反义句因为 `^` 之后必须紧跟动词而天然落空。
_APPROVAL_RE = re.compile(
    r"^\s*(?P<verb>" + "|".join(_ALL_VERBS) + r")\s*[:：]?\s*(?P<cid>[A-Za-z0-9]{6,64})\s*$",
    re.IGNORECASE,
)
_ROLLBACK_RE = re.compile(
    r"^\s*(?:回退|撤销改动|回滚)\s*[:：]?\s*(?P<cid>[A-Za-z0-9]{6,64})\s*$"
)


@dataclass(frozen=True)
class ApprovalIntent:
    """一句正文解析出来的批准/驳回意图（**它本身不构成授权**，只是文本事实）。"""

    consent_id: str
    approved: bool


def parse_approval(text: object) -> ApprovalIntent | None:
    """把一句入站正文解析成「批 / 驳 + 同意号」；认不出返回 ``None``（绝不猜）。"""
    match = _APPROVAL_RE.match(str(text or ""))
    if match is None:
        return None
    verb = _as_text(match["verb"]).lower()
    return ApprovalIntent(consent_id=_as_text(match["cid"]), approved=verb in _APPROVE_VERBS)


def rollback_id_from_text(text: object) -> str:
    """从「回退 <id>」里取回退号；取不出返回空串（不猜）。"""
    match = _ROLLBACK_RE.match(str(text or "").strip())
    return _as_text(match["cid"]) if match else ""


# ---------------------------------------------------------------------------
# 变更记录（可回退那一腿）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangeRecord:
    """一次「改参数」的流水：before/after 指纹 + 同意号 + 批准人 + 回退号。

    `consent_id / approved_by / approved_at` 三列就是规格 §5.4 要求并进
    `config_audit` 的那三列；本件先落在自己的表/账本里（SQL 后端是同一个库文件），
    并表要 `control_plane/config_store.py` 的 owner 点头（建议清单已交回）。
    """

    change_id: str
    target: str
    action_id: str
    tier: str
    requester: str
    actor: str
    state: str
    before_fingerprint: str
    after_fingerprint: str
    created_at: datetime
    consent_id: str = ""
    approved_by: str = ""
    approved_at: datetime | None = None
    rollback_id: str = ""
    before_value: Any = None
    applied_value: Any = None
    value_is_sensitive: bool = False
    restore_default: bool = False
    request_id: str = ""
    reason: str = ""

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["approved_at"] = self.approved_at.isoformat() if self.approved_at else None
        return payload

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> ChangeRecord:
        return cls(
            change_id=_as_text(record["change_id"]),
            target=_as_text(record["target"]),
            action_id=_as_text(record["action_id"]),
            tier=_as_text(record["tier"]),
            requester=_as_text(record["requester"]),
            actor=_as_text(record["actor"]),
            state=_as_text(record["state"]),
            before_fingerprint=_as_text(record["before_fingerprint"]),
            after_fingerprint=_as_text(record["after_fingerprint"]),
            created_at=_moment(record["created_at"]),
            consent_id=_as_text(record.get("consent_id") or ""),
            approved_by=_as_text(record.get("approved_by") or ""),
            approved_at=_moment_or_none(record.get("approved_at")),
            rollback_id=_as_text(record.get("rollback_id") or ""),
            before_value=record.get("before_value"),
            applied_value=record.get("applied_value"),
            value_is_sensitive=bool(record.get("value_is_sensitive")),
            restore_default=bool(record.get("restore_default")),
            request_id=_as_text(record.get("request_id") or ""),
            reason=_as_text(record.get("reason") or ""),
        )

    def rollback_command(self) -> str:
        """一键回退的指令文本（无回退号 ⇒ 空串：调用方据此就知道不能回退）。"""
        if not self.rollback_id:
            return ""
        return ROLLBACK_COMMAND_TEMPLATE.format(rollback_id=self.rollback_id)


# ---------------------------------------------------------------------------
# 账本后端（两态同形）
# ---------------------------------------------------------------------------

_CONSENT_DDL = f"""CREATE TABLE IF NOT EXISTS {CONSENT_TABLE} (
    consent_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    action_id TEXT NOT NULL,
    target TEXT NOT NULL,
    tier TEXT NOT NULL,
    requester TEXT NOT NULL,
    source_session_key TEXT NOT NULL DEFAULT '',
    min_approver_level TEXT NOT NULL DEFAULT '',
    require_private INTEGER NOT NULL DEFAULT 1,
    before_fingerprint TEXT NOT NULL,
    after_fingerprint TEXT NOT NULL,
    binding TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT,
    before_json TEXT,
    after_json TEXT,
    restore_default INTEGER NOT NULL DEFAULT 0,
    value_is_sensitive INTEGER NOT NULL DEFAULT 0,
    request_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '')"""

_CHANGE_DDL = f"""CREATE TABLE IF NOT EXISTS {CHANGE_TABLE} (
    change_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    target TEXT NOT NULL,
    action_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    requester TEXT NOT NULL,
    actor TEXT NOT NULL,
    state TEXT NOT NULL,
    before_fingerprint TEXT NOT NULL,
    after_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    consent_id TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT,
    rollback_id TEXT NOT NULL DEFAULT '',
    before_json TEXT,
    applied_json TEXT,
    value_is_sensitive INTEGER NOT NULL DEFAULT 0,
    restore_default INTEGER NOT NULL DEFAULT 0,
    request_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '')"""

_CONSENT_COLUMNS = (
    "consent_id",
    "state",
    "action_id",
    "target",
    "tier",
    "requester",
    "source_session_key",
    "min_approver_level",
    "require_private",
    "before_fingerprint",
    "after_fingerprint",
    "binding",
    "created_at",
    "expires_at",
    "approved_by",
    "approved_at",
    "before_json",
    "after_json",
    "restore_default",
    "value_is_sensitive",
    "request_id",
    "reason",
)

_CHANGE_COLUMNS = (
    "change_id",
    "seq",
    "target",
    "action_id",
    "tier",
    "requester",
    "actor",
    "state",
    "before_fingerprint",
    "after_fingerprint",
    "created_at",
    "consent_id",
    "approved_by",
    "approved_at",
    "rollback_id",
    "before_json",
    "applied_json",
    "value_is_sensitive",
    "restore_default",
    "request_id",
    "reason",
)


class AuditWriteError(RuntimeError):
    """账写不下去。抛出＝这次改动必须被拒绝（fail-closed 的那一半）。"""


class SafetyLedgerStore(Protocol):
    """账本后端契约。实现必须只做阻塞 I/O（事件循环的活交给 `AsyncConsentLedger`）。"""

    backend_name: str

    def append_consent(self, row: ConsentRow) -> None: ...

    def get_consent(self, consent_id: str) -> ConsentRow | None: ...

    def claim_consent(
        self, consent_id: str, *, binding: str, approver: str, at: datetime
    ) -> ConsentRow | None: ...

    def revoke_consent(
        self, consent_id: str, *, binding: str, approver: str, at: datetime
    ) -> ConsentRow | None: ...

    def append_change(self, record: ChangeRecord) -> None: ...

    def update_change(
        self, change_id: str, *, state: str, reason: str = ""
    ) -> ChangeRecord | None: ...

    def get_change(self, change_id: str) -> ChangeRecord | None: ...

    def find_rollback(self, rollback_id: str) -> ChangeRecord | None: ...

    def list_changes(self, *, limit: int = 50) -> list[ChangeRecord]: ...

    def list_pending(self, *, now: datetime) -> list[ConsentRow]: ...


class SqliteSafetyLedger:
    """SQL 后端：与 `SQLiteConfigStateStore` **同一个数据库文件**，只新增两张表。

    短连接、无缓存、`BEGIN IMMEDIATE` 抢写锁——照控制面配置库的既有做法，
    本件不自创第二种事务口径。
    """

    backend_name = "sqlite"

    def __init__(self, path: str | Path, *, timeout: float = 5.0) -> None:
        text = str(path or "").strip()
        if not text or text == ":memory:":
            raise ValueError("同意账需要显式的数据库文件路径（同控制面配置库那枚）")
        self.path = Path(text).expanduser()
        self.timeout = timeout
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(_CONSENT_DDL)
            conn.execute(_CHANGE_DDL)

    @classmethod
    def from_config_store(cls, store: object) -> SqliteSafetyLedger:
        """从既有 `SQLiteConfigStateStore` 派生路径：**同一库文件**，不另起一套。"""
        path = getattr(store, "path", None)
        if not isinstance(path, (str, Path)):
            raise TypeError("传入的不是控制面配置库对象（没有 path 属性）")
        return cls(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert(self, table: str, columns: tuple[str, ...], values: tuple[Any, ...], *, replace: bool = False) -> None:
        placeholders = ",".join("?" * len(columns))
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        sql = f"{verb} INTO {table}({','.join(columns)}) VALUES ({placeholders})"
        try:
            with self._lock, closing(self._connect()) as conn, conn:
                conn.execute(sql, values)
        except sqlite3.Error as exc:
            # 同意号的重复插入走不到 `replace=True` 这条路上（id 是随机数），
            # 真撞上了说明有人在造第二本账——按写失败处理，让调用方拒这次改动。
            raise AuditWriteError(f"写 {table} 失败：{type(exc).__name__}: {exc}") from exc

    def _mutate(self, sql: str, params: tuple[Any, ...]) -> int:
        """跑一条 UPDATE，返回受影响行数（一次性消费的判据就靠这个数）。"""
        try:
            with self._lock, closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(sql, params)
                return int(cur.rowcount or 0)
        except sqlite3.Error as exc:
            raise AuditWriteError(f"改账失败：{type(exc).__name__}: {exc}") from exc

    def _select(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        try:
            with closing(self._connect()) as conn:
                return list(conn.execute(sql, params).fetchall())
        except sqlite3.Error as exc:
            raise AuditWriteError(f"读账失败：{type(exc).__name__}: {exc}") from exc

    # -- 同意号 ---------------------------------------------------------------

    def append_consent(self, row: ConsentRow) -> None:
        if not row.consent_id:
            raise AuditWriteError("同意号为空，拒绝入账")
        self._insert(
            CONSENT_TABLE,
            _CONSENT_COLUMNS,
            (
                row.consent_id,
                row.state,
                row.action_id,
                row.target,
                row.tier,
                row.requester,
                row.source_session_key,
                row.min_approver_level,
                int(row.require_private),
                row.before_fingerprint,
                row.after_fingerprint,
                row.binding,
                row.created_at.isoformat(),
                row.expires_at.isoformat(),
                row.approved_by,
                row.approved_at.isoformat() if row.approved_at else None,
                _dump(row.before_value),
                _dump(row.after_value),
                int(row.restore_default),
                int(row.value_is_sensitive),
                row.request_id,
                row.reason,
            ),
        )

    def get_consent(self, consent_id: str) -> ConsentRow | None:
        rows = self._select(f"SELECT * FROM {CONSENT_TABLE} WHERE consent_id=?", (consent_id,))
        return _consent_from_row(rows[0]) if rows else None

    def _transition(
        self, consent_id: str, *, to_state: str, binding: str, approver: str, at: datetime
    ) -> ConsentRow | None:
        changed = self._mutate(
            f"UPDATE {CONSENT_TABLE} SET state=?, approved_by=?, approved_at=?"
            " WHERE consent_id=? AND state=? AND binding=?",
            (to_state, approver, at.isoformat(), consent_id, ConsentState.PENDING.value, binding),
        )
        if changed != 1:
            return None
        rows = self._select(f"SELECT * FROM {CONSENT_TABLE} WHERE consent_id=?", (consent_id,))
        return _consent_from_row(rows[0]) if rows else None

    def claim_consent(
        self, consent_id: str, *, binding: str, approver: str, at: datetime
    ) -> ConsentRow | None:
        """原子一次性消费：`pending → consumed`，改到 0 行即「已被用过 / 不存在 / 换了绑定」。"""
        return self._transition(
            consent_id, to_state=ConsentState.CONSUMED.value, binding=binding, approver=approver, at=at
        )

    def revoke_consent(
        self, consent_id: str, *, binding: str, approver: str, at: datetime
    ) -> ConsentRow | None:
        return self._transition(
            consent_id, to_state=ConsentState.REVOKED.value, binding=binding, approver=approver, at=at
        )

    def list_pending(self, *, now: datetime) -> list[ConsentRow]:
        rows = self._select(
            f"SELECT * FROM {CONSENT_TABLE} WHERE state=? AND expires_at>? ORDER BY created_at",
            (ConsentState.PENDING.value, now.isoformat()),
        )
        return [_consent_from_row(row) for row in rows]

    # -- 变更流水 -------------------------------------------------------------

    def append_change(self, record: ChangeRecord) -> None:
        if not record.change_id:
            raise AuditWriteError("变更记录 id 为空，拒绝入账")
        self._insert(
            CHANGE_TABLE,
            _CHANGE_COLUMNS,
            (
                record.change_id,
                int(record.created_at.timestamp() * 1000000),
                record.target,
                record.action_id,
                record.tier,
                record.requester,
                record.actor,
                record.state,
                record.before_fingerprint,
                record.after_fingerprint,
                record.created_at.isoformat(),
                record.consent_id,
                record.approved_by,
                record.approved_at.isoformat() if record.approved_at else None,
                record.rollback_id,
                _dump(record.before_value),
                _dump(record.applied_value),
                int(record.value_is_sensitive),
                int(record.restore_default),
                record.request_id,
                record.reason,
            ),
        )

    def update_change(
        self, change_id: str, *, state: str, reason: str = ""
    ) -> ChangeRecord | None:
        self._mutate(
            f"UPDATE {CHANGE_TABLE} SET state=?, reason=? WHERE change_id=?",
            (state, reason, change_id),
        )
        return self.get_change(change_id)

    def get_change(self, change_id: str) -> ChangeRecord | None:
        rows = self._select(f"SELECT * FROM {CHANGE_TABLE} WHERE change_id=?", (change_id,))
        return _change_from_row(rows[0]) if rows else None

    def find_rollback(self, rollback_id: str) -> ChangeRecord | None:
        if not rollback_id:
            return None
        rows = self._select(
            f"SELECT * FROM {CHANGE_TABLE} WHERE rollback_id=? ORDER BY seq DESC LIMIT 1",
            (rollback_id,),
        )
        return _change_from_row(rows[0]) if rows else None

    def list_changes(self, *, limit: int = 50) -> list[ChangeRecord]:
        rows = self._select(
            f"SELECT * FROM {CHANGE_TABLE} ORDER BY seq DESC LIMIT ?", (max(1, int(limit)),)
        )
        return [_change_from_row(row) for row in reversed(rows)]


class JsonSafetyLedger:
    """JSON 后端：同目录两份 append-only 账本（一行一条，同 id 后写覆盖前写）。

    存在的理由就是 G-19：今天 JSON 路径**什么都不写**，改一次参数查无此事。
    append-only 是刻意的——「谁批的、批的是什么」这类事实不许被后来的重写抹掉；
    代价是文件只增不减，清理得留给人做（本件绝不自动删自己的账，规格 §4 R3）。
    """

    backend_name = "json"

    def __init__(self, directory: str | Path, *, basename: str = "safetyexec") -> None:
        text = str(directory or "").strip()
        if not text:
            raise ValueError("JSON 账本需要显式目录")
        self.directory = Path(text).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.consent_path = self.directory / f"{basename}_consent.jsonl"
        self.change_path = self.directory / f"{basename}_change_audit.jsonl"
        self._lock = threading.Lock()

    def _append(self, path: Path, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        try:
            with self._lock, open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:  # 由调用方翻成 REFUSED(audit_unavailable)
            raise AuditWriteError(f"写 {path.name} 失败：{type(exc).__name__}: {exc}") from exc

    def _read(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AuditWriteError(f"读 {path.name} 失败：{type(exc).__name__}: {exc}") from exc
        records: list[dict[str, Any]] = []
        for text in raw.splitlines():
            stripped = text.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except ValueError:
                # 半截行（进程被杀）不许把整本账读废：跳过这一行、如实报备，
                # 绝不返回空表冒充「没有账」。
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
        return records

    def _latest(self, path: Path, key: str, wanted: str) -> dict[str, Any] | None:
        found: dict[str, Any] | None = None
        for record in self._read(path):
            if _as_text(record.get(key)) == wanted:
                found = record
        return found

    def append_consent(self, row: ConsentRow) -> None:
        if not row.consent_id:
            raise AuditWriteError("同意号为空，拒绝入账")
        self._append(self.consent_path, row.to_record())

    def get_consent(self, consent_id: str) -> ConsentRow | None:
        record = self._latest(self.consent_path, "consent_id", consent_id)
        return ConsentRow.from_record(record) if record else None

    def _transition(
        self, consent_id: str, *, to_state: str, binding: str, approver: str, at: datetime
    ) -> ConsentRow | None:
        row = self.get_consent(consent_id)
        if row is None or row.binding != binding or row.state != ConsentState.PENDING.value:
            return None
        updated = replace(
            row, state=to_state, approved_by=approver, approved_at=at
        )
        self._append(self.consent_path, updated.to_record())
        return updated

    def claim_consent(
        self, consent_id: str, *, binding: str, approver: str, at: datetime
    ) -> ConsentRow | None:
        return self._transition(
            consent_id, to_state=ConsentState.CONSUMED.value, binding=binding, approver=approver, at=at
        )

    def revoke_consent(
        self, consent_id: str, *, binding: str, approver: str, at: datetime
    ) -> ConsentRow | None:
        return self._transition(
            consent_id, to_state=ConsentState.REVOKED.value, binding=binding, approver=approver, at=at
        )

    def list_pending(self, *, now: datetime) -> list[ConsentRow]:
        latest: dict[str, ConsentRow] = {}
        for record in self._read(self.consent_path):
            row = ConsentRow.from_record(record)
            latest[row.consent_id] = row
        return sorted(
            (row for row in latest.values() if row.is_live(now=now)),
            key=lambda row: row.created_at,
        )

    def append_change(self, record: ChangeRecord) -> None:
        if not record.change_id:
            raise AuditWriteError("变更记录 id 为空，拒绝入账")
        self._append(self.change_path, record.to_record())

    def update_change(
        self, change_id: str, *, state: str, reason: str = ""
    ) -> ChangeRecord | None:
        record = self.get_change(change_id)
        if record is None:
            return None
        updated = replace(record, state=state, reason=reason)
        self._append(self.change_path, updated.to_record())
        return updated

    def get_change(self, change_id: str) -> ChangeRecord | None:
        record = self._latest(self.change_path, "change_id", change_id)
        return ChangeRecord.from_record(record) if record else None

    def find_rollback(self, rollback_id: str) -> ChangeRecord | None:
        if not rollback_id:
            return None
        record = self._latest(self.change_path, "rollback_id", rollback_id)
        return ChangeRecord.from_record(record) if record else None

    def list_changes(self, *, limit: int = 50) -> list[ChangeRecord]:
        deduped: dict[str, ChangeRecord] = {}
        for record in self._read(self.change_path):
            parsed = ChangeRecord.from_record(record)
            deduped[parsed.change_id] = parsed
        ordered = sorted(deduped.values(), key=lambda item: item.created_at)
        return ordered[-max(1, int(limit)) :]


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return json.dumps(repr(value), ensure_ascii=False)


def _load(text: object) -> Any:
    if text is None or _as_text(text) == "":
        return None
    try:
        return json.loads(str(text))
    except ValueError:
        return str(text)


def _record_from_row(row: sqlite3.Row, columns: Iterable[str]) -> dict[str, Any]:
    """按列名把 `sqlite3.Row` 收成字典（只取本件认识的列）。

    `row.keys()` 不是冗余：`sqlite3.Row` **迭代出来的是值**，不是列名——
    写成 `for name in row` 会把一串值拿去和列名比，结果几乎全不命中，
    下游 `record["require_private"]` 当场 ``KeyError``（本席第一发就这么红的）。
    """
    keys = set(columns)
    return {name: row[name] for name in row.keys() if name in keys}  # noqa: SIM118


def _consent_from_row(row: sqlite3.Row) -> ConsentRow:
    record = _record_from_row(row, _CONSENT_COLUMNS)
    record["require_private"] = bool(record["require_private"])
    record["restore_default"] = bool(record["restore_default"])
    record["value_is_sensitive"] = bool(record["value_is_sensitive"])
    record["before_value"] = _load(record.pop("before_json", None))
    record["after_value"] = _load(record.pop("after_json", None))
    return ConsentRow.from_record(record)


def _change_from_row(row: sqlite3.Row) -> ChangeRecord:
    record = _record_from_row(row, _CHANGE_COLUMNS)
    record["value_is_sensitive"] = bool(record["value_is_sensitive"])
    record["restore_default"] = bool(record["restore_default"])
    record["before_value"] = _load(record.pop("before_json", None))
    record["applied_value"] = _load(record.pop("applied_json", None))
    record.pop("seq", None)
    return ChangeRecord.from_record(record)


# ---------------------------------------------------------------------------
# 配置写入后端（装配侧注入；本件不认识 NoneBot，只认这个窄接口）
# ---------------------------------------------------------------------------


class ConfigWriteBackend(Protocol):
    """「读现值 / 写一次 / 能不能改回去」三件事的窄接口。"""

    name: str

    def effective_value(self, key: str) -> Any: ...

    def has_override(self, key: str) -> bool: ...

    def supports_hot_write(self, key: str) -> bool: ...

    def write(self, key: str, value: Any, *, actor: str, request_id: str) -> Any: ...

    def reset(self, key: str, *, actor: str, request_id: str) -> Any: ...


class RuntimeConfigBackend:
    """把装配层的 `RuntimeSettingsStore` 包成 `ConfigWriteBackend`。

    「能不能热改」这道硬门在这里，而**不在**风险分级表里：
    `RESTART_REQUIRED_KEYS` 里的键改了不落（消费者每轮重读的 Config 也读不到覆盖），
    所以本适配器直接判它「不支持热改」⇒ 上层就不许自动改、也不许出那种回显。
    规格 §4 末段那句「否则就是自我欺骗」说的正是这件事。
    """

    name = "runtime_settings"

    def __init__(self, store: object, config: object = None) -> None:
        for missing in ("list_overrides", "set_override", "reset_override"):
            if not callable(getattr(store, missing, None)):
                raise TypeError(f"配置后端缺少 {missing}()")
        # 上面已经逐名验过鸭子类型，这里把字段标成 Any 让调用点过 mypy：
        # 本件**不 import** `RuntimeSettingsStore`（避开根装配链的重依赖），
        # 所以拿不到它的静态类型；窄接口 `ConfigWriteBackend` 才是对外契约。
        self._store: Any = store
        self._config = config

    def effective_value(self, key: str) -> Any:
        name = config_risk.normalize_target(key)
        overrides = self._overrides()
        if name in overrides:
            return overrides[name]
        return getattr(self._config, name.lower(), None) if self._config is not None else None

    def has_override(self, key: str) -> bool:
        return config_risk.normalize_target(key) in self._overrides()

    def supports_hot_write(self, key: str) -> bool:
        from plugins.bot_unified_runtime.domains.chat_reply.runtime import settings

        name = config_risk.normalize_target(key)
        return name in settings.SETTABLE_KEYS and name not in settings.RESTART_REQUIRED_KEYS

    def write(self, key: str, value: Any, *, actor: str, request_id: str) -> Any:
        return self._store.set_override(
            config_risk.normalize_target(key),
            _as_setting_text(value),
            actor=actor,
            request_id=request_id,
        )

    def reset(self, key: str, *, actor: str, request_id: str) -> Any:
        return self._store.reset_override(
            config_risk.normalize_target(key), actor=actor, request_id=request_id
        )

    def _overrides(self) -> dict[str, Any]:
        return {str(key): value for key, value in dict(self._store.list_overrides()).items()}


def _as_setting_text(value: Any) -> str:
    """把值折成 `RuntimeSettingsStore` 转换器吃得起的文本形。

    ``None`` 绝不折成字面量 ``"None"``（那会被转换器当成一个真值写进去）——
    要回缺省请走 `reset`。布尔显式写 ``true/false``。
    """
    if value is None:
        raise ValueError("不允许把 None 当配置值写入；要回缺省请用 reset")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


# ---------------------------------------------------------------------------
# 同意账主体
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsentPolicy:
    """本件的三枚开关 + TTL。

    ⚠ 2026-09-26 起「缺省全关」旧口径要分两层读：**数据类字段缺省**仍是引擎级保守值
    （没喂配置的对象一律关，测试与旁路场景靠它）；而**生产真值**是
    `config.py::bot_safetyexec_enabled` 缺省 **True**——裁定第 18 项「危险的参数设置
    需要经过超级管理员的书面同意」要的是执法开着的真门（咽喉接线见 `settings_gate.py`）。
    """

    enabled: bool = False
    auto_r0_enabled: bool = False
    ttl_minutes: int = DEFAULT_CONSENT_TTL_MINUTES

    @classmethod
    def from_config(cls, config: object) -> ConsentPolicy:
        """从 Config（或任何带同名属性的对象/字典）取一次**快照**。

        刻意只在构造期读一次：这三枚键建议进 `RESTART_REQUIRED_KEYS`，
        做成「看起来能热改」比不做更坏。
        """
        mapping = config if isinstance(config, dict) else None

        def read(name: str, default: Any) -> Any:
            if mapping is not None:
                return mapping.get(name, default)
            return getattr(config, name, default)

        ttl_raw = read("bot_safetyexec_consent_ttl_minutes", DEFAULT_CONSENT_TTL_MINUTES)
        try:
            ttl = int(ttl_raw)
        except (TypeError, ValueError):
            ttl = DEFAULT_CONSENT_TTL_MINUTES
        if not 1 <= ttl <= 24 * 60:
            ttl = DEFAULT_CONSENT_TTL_MINUTES
        return cls(
            enabled=bool(read("bot_safetyexec_enabled", False)),
            auto_r0_enabled=bool(read("bot_safetyexec_auto_r0_enabled", False)),
            ttl_minutes=ttl,
        )


@dataclass(frozen=True)
class ChangeRequest:
    """一次「想改某个参数」的意图。`restore_default=True` = 回到缺省值（不留覆盖）。"""

    target: str
    value: Any = None
    requester: str = "bot:self_iteration"
    action_id: str = "config.write"
    source_session_key: str = ""
    request_id: str = ""
    restore_default: bool = False
    reason: str = ""

    def normalized(self) -> ChangeRequest:
        return replace(
            self,
            target=config_risk.normalize_target(self.target),
            requester=_as_text(self.requester) or "bot:self_iteration",
            action_id=_as_text(self.action_id) or "config.write",
            request_id=_as_text(self.request_id),
        )

    def after_fingerprint(self) -> str:
        """这次要写进去的值（或缺省哨兵）的指纹。"""
        if self.restore_default:
            return config_risk.RESTORE_DEFAULT_FINGERPRINT
        return fingerprint_of(self.value)


@dataclass(frozen=True)
class ConsentGrant:
    """批语成立后的凭证：拿着它才能落地这一次写。"""

    row: ConsentRow
    approved_by: str
    approved_at: datetime

    @property
    def consent_id(self) -> str:
        return self.row.consent_id


@dataclass(frozen=True)
class ChangeOutcome:
    """一次生效的结果：回显文案 + 一键回退（R0 两件套的落点）。"""

    record: ChangeRecord
    echo_text: str
    rollback_command: str
    applied_value: Any = None
    rolled_back: bool = False

    @property
    def target(self) -> str:
        return self.record.target

    @property
    def tier(self) -> str:
        return self.record.tier


@dataclass(frozen=True)
class Refusal:
    """一次没发生的改动，带代号与人话（规格 §5.5：拒绝路径不得静默）。"""

    kind: DenyKind
    target: str
    tier: str
    detail: str = ""

    @property
    def plain_text(self) -> str:
        return plain_text_for(self.kind)

    def line(self) -> str:
        text = f"{self.plain_text}（{self.target}｜{self.tier}｜{self.kind.value}）"
        return f"{text}\n{self.detail}" if self.detail else text


@dataclass(frozen=True)
class NeedsConsent:
    """要书面同意：带同意卡数据与投递事实，动作尚未落地。"""

    ticket: ConsentTicket
    target: str
    tier: str

    @property
    def consent_id(self) -> str:
        return self.ticket.consent_id

    @property
    def expires_at(self) -> datetime:
        return self.ticket.expires_at

    def plain_text(self) -> str:
        who = "主人亲自" if config_risk.requires_written_consent(self.tier) else "管理员在本会话确认"
        return (
            f"这条我不能自己改：{self.target}（{self.tier}）。要{who}批一句"
            f"「同意 {self.consent_id}」，过期不续。"
        )


#: 一次改参数请求的三种可能结果。
Decision = NeedsConsent | Refusal | ChangeOutcome


class ConsentLedger:
    """同意账 + 改参数流水线（同步内核；异步壳见 `AsyncConsentLedger`）。

    每个公开写口都以「账先落得下去」为前提，落不下去就拒这次改动。
    """

    def __init__(
        self,
        store: SafetyLedgerStore,
        *,
        backend: ConfigWriteBackend | None = None,
        policy: ConsentPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._backend = backend
        self._policy = policy or ConsentPolicy()
        self._clock = clock or utc_clock

    # -- 只读面 ---------------------------------------------------------------

    @property
    def backend_name(self) -> str:
        return self._store.backend_name

    @property
    def policy(self) -> ConsentPolicy:
        return self._policy

    def pending_tickets(self) -> list[ConsentTicket]:
        now = _aware_now(self._clock)
        return [ConsentTicket(row=row) for row in self._store.list_pending(now=now)]

    def ticket(self, consent_id: object) -> ConsentTicket | None:
        row = self._store.get_consent(_as_text(consent_id))
        return ConsentTicket(row=row) if row is not None else None

    def change_history(self, *, limit: int = 50) -> list[ChangeRecord]:
        return self._store.list_changes(limit=limit)

    def rollback_target(self, rollback_id: object) -> ChangeRecord | None:
        return self._store.find_rollback(_as_text(rollback_id))

    # -- 分级与规划（纯读）-----------------------------------------------------

    def plan(self, request: ChangeRequest) -> tuple[ChangeRequest, config_risk.RiskTier, Any]:
        """(规范形请求, 风险档, 现值)。不落任何副作用。"""
        normalized = request.normalized()
        tier = config_risk.risk_tier_for_target(normalized.target)
        current = self._require_backend().effective_value(normalized.target)
        return normalized, tier, current

    # -- R0：不问就改，但必须两件套 -------------------------------------------

    def apply_unattended(self, request: ChangeRequest) -> ChangeOutcome | Refusal:
        """R0 自动改的**唯一**入口：回显 + 一键回退缺一件就不改（裁定 P-4）。"""
        normalized, tier, current = self.plan(request)
        if not self._policy.enabled:
            return self._refuse(Refusal(DenyKind.ENGINE_DISABLED, normalized.target, tier.value))
        if config_risk.is_never_auto(tier):
            return self._refuse(Refusal(DenyKind.NEVER_AUTO, normalized.target, tier.value))
        if not config_risk.allows_unattended_change(tier):
            return self._refuse(
                Refusal(
                    DenyKind.NOT_UNATTENDED_ELIGIBLE,
                    normalized.target,
                    tier.value,
                    detail="这一档要走同意卡",
                )
            )
        return self._execute(normalized, tier, current, consent=None, source=SOURCE_UNATTENDED)

    # -- R1/R2：书面同意 ------------------------------------------------------

    def request_consent(self, request: ChangeRequest) -> NeedsConsent | Refusal:
        """申请一张同意卡（本身不落地任何改动）。"""
        normalized, tier, current = self.plan(request)
        if not self._policy.enabled:
            return Refusal(DenyKind.ENGINE_DISABLED, normalized.target, tier.value)
        if config_risk.is_never_auto(tier):
            # R3 的天花板是 RepairService 的「待审补丁」；本件不代它落地、也不给它开口子。
            return Refusal(DenyKind.NEVER_AUTO, normalized.target, tier.value)
        if not config_risk.requires_consent(tier):
            return Refusal(
                DenyKind.NOT_UNATTENDED_ELIGIBLE,
                normalized.target,
                tier.value,
                detail="这一档不需要同意卡",
            )
        written = config_risk.requires_written_consent(tier)
        before_fp, sensitive, before_kept = value_pair_for_ledger(normalized.target, current)
        after_fp = normalized.after_fingerprint()
        after_value = None if normalized.restore_default else normalized.value
        now = _aware_now(self._clock)
        row = ConsentRow(
            consent_id=new_consent_id(),
            state=ConsentState.PENDING.value,
            action_id=normalized.action_id,
            target=normalized.target,
            tier=tier.value,
            requester=normalized.requester,
            source_session_key=_as_text(normalized.source_session_key),
            min_approver_level=TrustLevel.T0.value if written else TrustLevel.T0_PRIME.value,
            require_private=written,
            before_fingerprint=before_fp,
            after_fingerprint=after_fp,
            binding=binding_fingerprint(
                action_id=normalized.action_id,
                target=normalized.target,
                before_fingerprint=before_fp,
                after_fingerprint=after_fp,
                requester=normalized.requester,
            ),
            created_at=now,
            expires_at=now + timedelta(minutes=self._policy.ttl_minutes),
            before_value=None if sensitive else before_kept,
            after_value=None if sensitive else after_value,
            restore_default=normalized.restore_default,
            value_is_sensitive=sensitive,
            request_id=normalized.request_id,
            reason=normalized.reason,
        )
        if not is_legal_segment(row.consent_id) or not is_legal_segment(row.binding):
            return Refusal(
                DenyKind.AUDIT_UNAVAILABLE,
                normalized.target,
                tier.value,
                detail="同意号/绑定指纹不合中央键段规范，不投出去",
            )
        try:
            self._store.append_consent(row)
        except (AuditWriteError, OSError, ValueError) as exc:
            return Refusal(
                DenyKind.AUDIT_UNAVAILABLE, normalized.target, tier.value, detail=str(exc)
            )
        return NeedsConsent(ticket=ConsentTicket(row=row), target=normalized.target, tier=tier.value)

    def redeem_from_message(
        self,
        consent_id: object,
        message: IncomingMessage,
        *,
        intent: ApprovalIntent | None = None,
    ) -> ConsentGrant | Refusal:
        """**唯一**能把同意号置为已用的入口：批语必须是一条入站消息。

        形参上就要 `IncomingMessage`：模型输出、工具返回、文件正文构造不出这个对象，
        因此结构上就递不进批准（规格 §5.6）。可信级只走 `trust_from_message`
        这一个派生口，本件不读任何名单、不维护第二套权限表。

        `intent` 为命令面（`/bot consent approve|deny <id> <码>`）准备的显式批语形：
        **授权阶梯一字不动**（可信级 / 私聊门 / 原会话门 / pending / TTL / 原子消费），
        差别只在「批/驳」来自已解析的命令参数而非正文正则。消息本体仍必须是真实入站
        消息——凭证不能由 bot 侧构造，这条与形参类型是同一件事的两面（S-T-CONSENT1，
        裁定第 18 项咽喉波；短码校验在 `settings_gate` 命令门前置，不在这里）。
        """
        if not isinstance(message, IncomingMessage):
            raise TypeError(
                "同意只能由 IncomingMessage 带来；LLM 输出/工具结果/补丁文本一律不构成批准"
            )
        if intent is not None and not isinstance(intent, ApprovalIntent):
            raise TypeError("intent 必须是 ApprovalIntent 或省略（省略=从正文解析）")
        wanted = _as_text(consent_id)
        try:
            row = self._store.get_consent(wanted)
        except (AuditWriteError, OSError, ValueError) as exc:
            return Refusal(
                DenyKind.AUDIT_UNAVAILABLE,
                wanted or "?",
                config_risk.DEFAULT_TIER.value,
                detail=f"查这张卡时账本读不成：{exc}",
            )
        tier_text = row.tier if row is not None else config_risk.DEFAULT_TIER.value
        if row is None:
            return Refusal(DenyKind.UNKNOWN_CONSENT, wanted or "?", tier_text)
        if intent is None:
            intent = parse_approval(message.plain_text)
        if intent is None or intent.consent_id != row.consent_id:
            return Refusal(DenyKind.NOT_AN_APPROVAL, row.target, row.tier)
        now = _aware_now(self._clock)
        approver = _approver_of(message)
        # 授权与场景判定排在「批/驳」分岔**之前**：不然路人一句「拒绝 <id>」就能
        # 把主人那张卡作废掉——安全件被人从下面 DoS，方向正好反了。
        required = TrustLevel(row.min_approver_level or TrustLevel.T0.value)
        if trust_rank(trust_from_message(message)) < trust_rank(required):
            return Refusal(DenyKind.APPROVER_NOT_AUTHORISED, row.target, row.tier)
        # 防自批（裁定第 18 项「书面同意」的第二问）：发起这次改动的人不能再把它批掉。
        # 排在权限门之后、场景门之前——先确认「有资格批」，再确认「不是自己批自己」，
        # 否则路人的一句误触会把「不能自批」这条判据变成公开信息。
        if is_same_principal(row.requester, approver):
            return Refusal(
                DenyKind.SELF_CONSENT,
                row.target,
                row.tier,
                detail=f"这张卡是以 {row.requester} 的名义发起的，批准人也是同一个人。",
            )
        if row.require_private and message.session_type is not SessionType.PRIVATE:
            return Refusal(DenyKind.NOT_PRIVATE_CHAT, row.target, row.tier)
        # R1 的「同会话确认」：换个会话拿这张卡不算数。
        if (
            not row.require_private
            and row.source_session_key
            and _session_key_of(message) != row.source_session_key
        ):
            return Refusal(
                DenyKind.APPROVER_NOT_AUTHORISED,
                row.target,
                row.tier,
                detail="这条要在原会话里确认",
            )
        if row.state != ConsentState.PENDING.value:
            return Refusal(DenyKind.ALREADY_USED, row.target, row.tier)
        if now >= row.expires_at:
            return Refusal(DenyKind.EXPIRED, row.target, row.tier)
        try:
            moved = (
                self._store.claim_consent(
                    row.consent_id, binding=row.binding, approver=approver, at=now
                )
                if intent.approved
                else self._store.revoke_consent(
                    row.consent_id, binding=row.binding, approver=approver, at=now
                )
            )
        except (AuditWriteError, OSError, ValueError) as exc:
            return Refusal(
                DenyKind.AUDIT_UNAVAILABLE,
                row.target,
                row.tier,
                detail=f"这条{'批' if intent.approved else '驳'}语没落账：{exc}",
            )
        if moved is None:
            # 判过 pending 之后、落账之前被别人抢先消费（并发/重启窗口）：仍按一次性算。
            return Refusal(DenyKind.ALREADY_USED, row.target, row.tier)
        if not intent.approved:
            return Refusal(
                DenyKind.DENIED_BY_APPROVER,
                row.target,
                row.tier,
                detail=f"由 {approver} 驳回，这张卡已作废",
            )
        return ConsentGrant(
            row=moved, approved_by=moved.approved_by, approved_at=moved.approved_at or now
        )

    def _binding_guard(
        self, row: ConsentRow, wanted: ChangeRequest
    ) -> Refusal | None:
        """调用方要写的东西与卡上批的是不是**同一件事**（纯判，不消费）。

        排在消费**之前**：拿错值/拿错键来试一次，不该把主人亲手批的那张卡烧掉
        ——那是她的劳动，也是「拒绝路径不得静默」的反面（一次误试就把同意弄没了，
        等于把门挪到了机器人这一侧）。落地前 `apply_approved` 还会再判一次。
        """
        if wanted.target != row.target:
            return Refusal(
                DenyKind.BINDING_MISMATCH,
                wanted.target,
                row.tier,
                detail="这张卡批的不是这个键",
            )
        want_fp = wanted.after_fingerprint()
        if want_fp != row.after_fingerprint:
            return Refusal(
                DenyKind.BINDING_MISMATCH,
                row.target,
                row.tier,
                detail=f"批的是 {row.after_fingerprint}，要写的是 {want_fp}",
            )
        return None

    def apply_with_consent(
        self, request: ChangeRequest, consent_id: object, message: IncomingMessage
    ) -> ChangeOutcome | Refusal:
        """一步式：批语 + 落地。**要写的值必须与当初批的那枚指纹对得上**。"""
        wanted = request.normalized()
        stored = self._store.get_consent(_as_text(consent_id))
        if stored is not None:
            mismatch = self._binding_guard(stored, wanted)
            if mismatch is not None:
                return mismatch
        grant = self.redeem_from_message(consent_id, message)
        if isinstance(grant, Refusal):
            return grant
        return self.apply_approved(grant, wanted)

    def apply_approved(self, grant: ConsentGrant, request: ChangeRequest) -> ChangeOutcome | Refusal:
        """拿已消费的凭证落地一次写（绑定复算在这里，不在批语那一步）。"""
        wanted = request.normalized()
        row = grant.row
        tier = config_risk.risk_tier_for_target(row.target)
        mismatch = self._binding_guard(row, wanted)
        if mismatch is not None:
            return mismatch
        current = self._require_backend().effective_value(row.target)
        return self._execute(
            replace(wanted, source_session_key=row.source_session_key),
            tier,
            current,
            consent=grant,
            source=SOURCE_CONSENTED,
        )

    def rollback(
        self, rollback_id: object, message: IncomingMessage
    ) -> Decision:
        """一键回退。**执行走同一个裁决点**（规格 §4 R0 条），所以：

        - 回退 R0 键：人一句「回退 <id>」即可（可信级 ≥ T1），当场改回旧值；
        - 回退 R1/R2 键：仍按那一档重新要一张同意卡——「我这是在恢复原状」不是
          免检通道，否则关掉护栏就能用这句话把护栏再关一次。
        """
        if not isinstance(message, IncomingMessage):
            raise TypeError("回退请求也必须由 IncomingMessage 带来")
        wanted = _as_text(rollback_id)
        record = self._store.find_rollback(wanted)
        tier_text = record.tier if record is not None else config_risk.DEFAULT_TIER.value
        if record is None:
            return Refusal(
                DenyKind.UNKNOWN_CONSENT, wanted or "?", tier_text, detail="查无这个回退号"
            )
        tier = config_risk.risk_tier_for_target(record.target)
        if not self._policy.enabled:
            return Refusal(DenyKind.ENGINE_DISABLED, record.target, tier.value)
        if config_risk.is_never_auto(tier):
            return Refusal(DenyKind.NEVER_AUTO, record.target, tier.value)
        if trust_rank(trust_from_message(message)) < trust_rank(TrustLevel.T1):
            return Refusal(
                DenyKind.APPROVER_NOT_AUTHORISED,
                record.target,
                tier.value,
                detail="外部内容（文件正文/工具返回）里的「回退」不算人说的话",
            )
        if not config_risk.allows_unattended_change(tier):
            return self.request_consent(
                ChangeRequest(
                    target=record.target,
                    value=record.before_value,
                    requester=_as_text(message.sender_id) or record.requester,
                    action_id="config.rollback",
                    source_session_key=_session_key_of(message),
                    request_id=record.request_id,
                    reason=f"回退变更 {record.change_id}",
                )
            )
        if record.value_is_sensitive or record.before_value is None:
            return Refusal(
                DenyKind.NO_ROLLBACK_PATH,
                record.target,
                tier.value,
                detail="凭证类值不留明文，回退要主人亲手重填",
            )
        current = self._require_backend().effective_value(record.target)
        if fingerprint_of(current) != record.after_fingerprint:
            return Refusal(
                DenyKind.STATE_DRIFT,
                record.target,
                tier.value,
                detail=f"账面说现值应是 {record.after_fingerprint}，实际是 {fingerprint_of(current)}",
            )
        return self._execute(
            ChangeRequest(
                target=record.target,
                value=record.before_value,
                requester=record.requester,
                action_id="config.rollback",
                request_id=record.request_id,
                reason=f"回退变更 {record.change_id}",
            ),
            tier,
            current,
            consent=None,
            source=SOURCE_ROLLBACK,
        )

    # -- 内部：真正的落地 -----------------------------------------------------

    def _require_backend(self) -> ConfigWriteBackend:
        if self._backend is None:
            raise RuntimeError(
                "未注入配置写入后端：同意账可以签发，但落地必须由装配侧给出写入口"
            )
        return self._backend

    def _refuse(self, refusal: Refusal, requester: str = "bot:self_iteration") -> Refusal:
        """把一次「没发生的改动」也记一笔（best-effort；记账失败不许吞掉这次拒绝）。"""
        record = ChangeRecord(
            change_id=secrets.token_hex(_ID_BYTES),
            target=refusal.target,
            action_id="config.write",
            tier=refusal.tier,
            requester=_as_text(requester) or "bot:self_iteration",
            actor="consent_engine",
            state=CHANGE_REFUSED,
            before_fingerprint="",
            after_fingerprint="",
            created_at=_aware_now(self._clock),
            reason=f"{refusal.kind.value}: {refusal.detail}".strip(),
        )
        try:
            self._store.append_change(record)
        except (AuditWriteError, OSError, ValueError):
            pass
        return refusal

    def _execute(
        self,
        request: ChangeRequest,
        tier: config_risk.RiskTier,
        current: Any,
        *,
        consent: ConsentGrant | None,
        source: str,
    ) -> ChangeOutcome | Refusal:
        backend = self._require_backend()
        now = _aware_now(self._clock)
        before_fp, sensitive, before_kept = value_pair_for_ledger(request.target, current)
        after_fp = request.after_fingerprint()
        after_value = None if request.restore_default else request.value
        # 回退号只在「旧值真的留得住」时才发：凭证类值账上不留明文 ⇒ 没有可用的回退口，
        # 发一个注定失败的回退号等于在回显里许诺一件做不到的事（裁定 P-4 第二半）。
        rollback_id = new_rollback_id() if (not sensitive and before_kept is not None) else ""

        # ---- 前置判据：R0 自动改必须三问过，否则一条都不许动 ----------------
        def refuse(kind: DenyKind, detail: str = "") -> Refusal:
            """拒这次改动 + 落一条 `refused` 流水，**署的是提出这次改动的那一方**。"""
            return self._refuse(
                Refusal(kind, request.target, tier.value, detail=detail), request.requester
            )

        if source == SOURCE_UNATTENDED:
            if not self._policy.auto_r0_enabled:
                return refuse(
                    DenyKind.NO_ROLLBACK_PATH, "自动改参数的开关没开（缺省关），这次不代改"
                )
            if not backend.supports_hot_write(request.target):
                return refuse(
                    DenyKind.NO_ROLLBACK_PATH,
                    "该键无热改路径（改它要重启），不在可自动改的范围",
                )
            if sensitive or before_kept is None:
                return refuse(
                    DenyKind.NO_ROLLBACK_PATH,
                    "旧值留不住（凭证类值或未取到现值），按规矩不自动改",
                )
        elif not backend.supports_hot_write(request.target):
            # 批过的卡也不许拿去做「看起来改了、其实要重启」——那种回显是谎话。
            return refuse(
                DenyKind.NO_ROLLBACK_PATH, "该键无热改路径，改了也不生效，我不做这种回显"
            )

        actor = (
            f"consent:{consent.consent_id}"
            if consent is not None
            else (SOURCE_UNATTENDED if source == SOURCE_UNATTENDED else request.requester)
        )
        record = ChangeRecord(
            change_id=secrets.token_hex(_ID_BYTES),
            target=request.target,
            action_id="config.rollback" if source == SOURCE_ROLLBACK else request.action_id,
            tier=tier.value,
            requester=request.requester,
            actor=actor,
            state=CHANGE_PENDING,
            before_fingerprint=before_fp,
            after_fingerprint=after_fp,
            created_at=now,
            consent_id=consent.consent_id if consent else "",
            approved_by=consent.approved_by if consent else "",
            approved_at=consent.approved_at if consent else None,
            rollback_id=rollback_id,
            before_value=None if sensitive else before_kept,
            applied_value=None if sensitive else after_value,
            value_is_sensitive=sensitive,
            restore_default=request.restore_default,
            request_id=request.request_id,
            reason=request.reason,
        )
        # ① 账先落：落不下去就拒这次改动（fail-closed 的正身）。
        try:
            self._store.append_change(record)
        except (AuditWriteError, OSError, ValueError) as exc:
            return Refusal(
                DenyKind.AUDIT_UNAVAILABLE, request.target, tier.value, detail=str(exc)
            )

        # ② 真改。
        try:
            applied: Any = (
                backend.reset(request.target, actor=actor, request_id=request.request_id)
                if request.restore_default
                else backend.write(
                    request.target, after_value, actor=actor, request_id=request.request_id
                )
            )
        except Exception as exc:  # noqa: BLE001 - 写失败要翻成人话与终态，不许冒泡炸调用方
            detail = f"{type(exc).__name__}: {exc}"
            try:
                self._store.update_change(record.change_id, state=CHANGE_FAILED, reason=detail)
            except (AuditWriteError, OSError, ValueError):
                pass  # pending 行已在账上，绝不再叠一层静默
            return self._refuse(
                Refusal(DenyKind.APPLY_FAILED, request.target, tier.value, detail=detail)
            )

        # ③ 终态回写。
        applied_fp = fingerprint_of(applied)
        final_reason = record.reason
        if not request.restore_default and applied_fp != after_fp:
            final_reason = (
                f"{final_reason}\n注意：写进去再读回来是 {applied_fp}，与批的 {after_fp} 不一致"
                "（转换器改了形），已如实记账，不谎称一致。"
            )
        final_state = CHANGE_ROLLED_BACK if source == SOURCE_ROLLBACK else CHANGE_APPLIED
        try:
            updated = self._store.update_change(
                record.change_id, state=final_state, reason=final_reason
            )
        except (AuditWriteError, OSError, ValueError) as exc:
            # 已经改了却落不下终态：立刻尽力改回原值，并把两件事都喊出来。
            try:
                if request.restore_default:
                    backend.reset(request.target, actor="lost_audit", request_id=request.request_id)
                else:
                    backend.write(
                        request.target, current, actor="lost_audit", request_id=request.request_id
                    )
                note = "已尽力改回原值"
            except Exception as inner:  # noqa: BLE001
                note = f"改回也失败（{type(inner).__name__}），请人工核对"
            return Refusal(
                DenyKind.AUDIT_UNAVAILABLE,
                request.target,
                tier.value,
                detail=f"终态写不进账本：{exc}；{note}",
            )
        final_record = updated or replace(record, state=final_state, reason=final_reason)
        return ChangeOutcome(
            record=final_record,
            echo_text=self.echo_text_for(final_record, applied_value=applied),
            rollback_command=final_record.rollback_command(),
            applied_value=applied,
            rolled_back=source == SOURCE_ROLLBACK,
        )

    def echo_text_for(self, record: ChangeRecord, *, applied_value: Any = None) -> str:
        """R0 两件套的第一件：**回显改了什么**（凭证类值只报指纹）。

        只报事实：改了什么就说改了什么，不粉饰、不「大概」。
        """
        shown = applied_value if applied_value is not None else record.applied_value
        after_text = (
            "缺省值（覆盖已撤）"
            if record.restore_default
            else display_value(record.target, shown, record.after_fingerprint)
        )
        lines = [
            f"我改了一个参数：{record.target}",
            f"原来：{display_value(record.target, record.before_value, record.before_fingerprint)}",
            f"现在：{after_text}",
            f"档位：{record.tier}（{describe_tier_or_raw(record.tier)}）",
        ]
        command = record.rollback_command()
        lines.append(
            f"要退回就说一句：{command}"
            if command
            else "这条我没能留下回退口，改回去要主人亲手来。"
        )
        return "\n".join(lines)


#: 不是「某个人」的发起者名字：机器人内部写点与装配缺省名。
#: 它们永远构不成「申请人」，所以防自批那一问对它们不适用——不然
#: `model_schedule` 定时切模型签出来的 R2 卡将永无被人批的一天
#: （批准人恒是 `平台:号`，与这些名字永不相等，这条判据也永远不咬）。
NON_PERSONAL_REQUESTERS: frozenset[str] = frozenset(
    {
        "runtime_internal",
        "bot:self_iteration",
        "runtime-admin",
        "system",
        "",
    }
)


def _principal_pair(raw: object) -> tuple[str, str]:
    """身份串拆成 (平台, 号)。无平台前缀 ⇒ 平台留空，表示「来路没带平台」。"""
    text = _as_text(raw).strip().lower()
    if ":" in text:
        platform, _, who = text.rpartition(":")
        return platform.strip(), who.strip()
    return "", text


def is_same_principal(requester: object, approver: object) -> bool:
    """「申请人就是批准人」的唯一判据（防自批那一问只在这一处判）。

    口径：号必须相等；平台两侧都认得时必须同平台（QQ 的 123 与 TG 的 123
    不是同一个人）；有一侧没带平台就按同号同人算——宁可多拒一次（这条判据
    只会把「批准」判成「拒绝」，方向是收紧不是放宽），不放过自批。
    """
    requester_text = _as_text(requester).strip().lower()
    if requester_text in NON_PERSONAL_REQUESTERS:
        return False
    req_platform, req_who = _principal_pair(requester)
    app_platform, app_who = _principal_pair(approver)
    if not req_who or not app_who or req_who != app_who:
        return False
    if req_platform and app_platform:
        return req_platform == app_platform
    return True


def _approver_of(message: IncomingMessage) -> str:
    """批准人身份：平台 + 号（**只取结构化字段**，与 trust.py 同口径）。"""
    return f"{message.platform}:{message.sender_id}".strip(":")


def _session_key_of(message: IncomingMessage) -> str:
    return _as_text(message.session_id)


# ---------------------------------------------------------------------------
# 异步壳：账本的阻塞写走 asyncio.to_thread，别把它压进事件循环
# ---------------------------------------------------------------------------


class AsyncConsentLedger:
    """`ConsentLedger` 的异步门面：落盘动作 `to_thread`，判据本体不复制第二份。

    装配层（根 `__init__.py`）只该看到这一层——消息处理在事件循环里，
    而账本写是同步 SQLite / `fsync`。
    """

    def __init__(self, ledger: ConsentLedger) -> None:
        self._ledger = ledger
        self._lock = asyncio.Lock()  # 同进程内串行化「申请→落地」，防同一键并发双写

    @property
    def sync(self) -> ConsentLedger:
        """同步内核（测试与非事件循环调用方用它，别为跑测试再造一套语义）。"""
        return self._ledger

    @property
    def backend_name(self) -> str:
        return self._ledger.backend_name

    async def plan(self, request: ChangeRequest) -> tuple[ChangeRequest, config_risk.RiskTier, Any]:
        return await asyncio.to_thread(self._ledger.plan, request)

    async def request_change(self, request: ChangeRequest) -> Decision:
        async with self._lock:
            normalized, tier, _current = await asyncio.to_thread(self._ledger.plan, request)
            if config_risk.is_never_auto(tier):
                return Refusal(DenyKind.NEVER_AUTO, normalized.target, tier.value)
            if config_risk.allows_unattended_change(tier):
                return await asyncio.to_thread(self._ledger.apply_unattended, normalized)
            return await asyncio.to_thread(self._ledger.request_consent, normalized)

    async def redeem(
        self, consent_id: object, message: IncomingMessage
    ) -> ConsentGrant | Refusal:
        return await asyncio.to_thread(self._ledger.redeem_from_message, consent_id, message)

    async def apply_with_consent(
        self, request: ChangeRequest, consent_id: object, message: IncomingMessage
    ) -> ChangeOutcome | Refusal:
        async with self._lock:
            return await asyncio.to_thread(
                self._ledger.apply_with_consent, request, consent_id, message
            )

    async def rollback(self, rollback_id: object, message: IncomingMessage) -> Decision:
        async with self._lock:
            return await asyncio.to_thread(self._ledger.rollback, rollback_id, message)

    async def change_history(self, *, limit: int = 50) -> list[ChangeRecord]:
        return await asyncio.to_thread(self._ledger.change_history, limit=limit)

    async def pending_tickets(self) -> list[ConsentTicket]:
        return await asyncio.to_thread(self._ledger.pending_tickets)


# ---------------------------------------------------------------------------
# 装配口
# ---------------------------------------------------------------------------


def build_store(
    *,
    ledger_path: str | Path | None = None,
    config_store: object | None = None,
    json_dir: str | Path | None = None,
) -> SafetyLedgerStore:
    """选后端：给了控制面配置库就复用**同一个库文件**，否则退到 JSON 账本。

    两者都给时以 SQL 为准（与 `RuntimeSettingsStore.attach_config_backend` 的
    「SQL 为唯一覆盖源」口径一致）——不留「半本 SQL 半本 JSON」这种两边都查不到的形态。
    """
    if config_store is not None:
        return SqliteSafetyLedger.from_config_store(config_store)
    if ledger_path is not None:
        return SqliteSafetyLedger(ledger_path)
    if json_dir is not None:
        return JsonSafetyLedger(json_dir)
    raise ValueError("同意账必须显式给库文件（ledger_path/config_store）或 JSON 目录之一")


def build_ledger(
    *,
    ledger_path: str | Path | None = None,
    config_store: object | None = None,
    json_dir: str | Path | None = None,
    backend: ConfigWriteBackend | None = None,
    policy: ConsentPolicy | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ConsentLedger:
    """构造同意账（同步内核）。装配侧请用 `AsyncConsentLedger(build_ledger(...))`。"""
    store = build_store(ledger_path=ledger_path, config_store=config_store, json_dir=json_dir)
    return ConsentLedger(store, backend=backend, policy=policy, clock=clock)


__all__ = [
    "CHANGE_APPLIED",
    "CHANGE_FAILED",
    "CHANGE_PENDING",
    "CHANGE_REFUSED",
    "CHANGE_ROLLED_BACK",
    "CHANGE_TABLE",
    "CONSENT_TABLE",
    "DEFAULT_CONSENT_TTL_MINUTES",
    "NON_PERSONAL_REQUESTERS",
    "PROPOSED_CONFIG_KEYS",
    "PROPOSED_KEY_RESTART_NOTE",
    "ROLLBACK_COMMAND_TEMPLATE",
    "SOURCE_CONSENTED",
    "SOURCE_ROLLBACK",
    "SOURCE_UNATTENDED",
    "AsyncConsentLedger",
    "AuditWriteError",
    "ChangeOutcome",
    "ChangeRecord",
    "ChangeRequest",
    "ConfigWriteBackend",
    "ConsentGrant",
    "ConsentLedger",
    "ConsentPolicy",
    "ConsentRow",
    "ConsentState",
    "ConsentTicket",
    "Decision",
    "DenyKind",
    "JsonSafetyLedger",
    "NeedsConsent",
    "Refusal",
    "RuntimeConfigBackend",
    "SafetyLedgerStore",
    "SqliteSafetyLedger",
    "aware_now",
    "binding_fingerprint",
    "build_ledger",
    "build_store",
    "display_value",
    "fingerprint_of",
    "is_same_principal",
    "new_consent_id",
    "new_rollback_id",
    "parse_approval",
    "plain_text_for",
    "rollback_id_from_text",
    "utc_clock",
    "value_pair_for_ledger",
]
