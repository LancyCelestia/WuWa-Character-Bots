"""V21-AFFINITY-002 历史误扣重放与具名补偿（只读提案器，绝不写好感度库）。

合同（验收矩阵 V21-AFFINITY-002）：旧新 policy 差额证据；无证据不猜，
补偿不重复。用户原始诉求（2026-09-17）：测试 grok 路由时一晚掉 40+ 分，
历史因果未重放确认——本模块只产出证据与待审提案，**不得无证据恢复 40 分**。

## 证据模型（诚实边界，逐条对应合同）

1. **逐事件账** = ``affinity_delta_log``（V2.1 §2.3 滚动预算落地时随建）：
   ``(sender_id, bot_id, applied_at, delta, source, source_event_id)``，
   >48h 行写入时 prune（``_BUDGET_LOG_RETENTION_SECONDS``），且**不存行为
   分类/安全评估输入**（text/safety_category/safety_action/reason_code 均不落库）。
   因此逐事件旧新判定只有在 ``source`` 能唯一确定行为族时才可计算：
   - 当前唯一已验证族 = ``poke``（``__init__._record_poke_affinity`` 经
     ``observe_points`` 覆写路径，behavior 由调用方显式给定，策略变更不触及
     判定层）→ 旧新一致，**已证零差额**；
   - 其余（source='' 的被动感知族）→ **unknown**：不猜旧判、不猜新判、
     不猜差额，不计入补偿。
2. **预算前时代**（误扣 40+ 分事故窗口，≤2026-09-17）：``affinity_delta_log``
   尚不存在 → 逐事件记录物理缺失 → 只能以 ``user_affinity`` 聚合计数
   （insult_count/last_insult_at/口无遮拦打标时间等）作**审查指针**，
   明确标注「非逐事件证据、不构成补偿依据」。
3. **单位口径**：库内 delta 为内部值（1.0 内部值 = 100 展示分）；本模块
   政策层与提案一律用展示「分」，LedgerEvent 原样保留内部值并提供
   ``applied_points`` 换算——唯一换算口，禁止二次 ×100。
4. **只读保证**：引擎唯一入库方式是 ``open_readonly_connection``（SQLite
   ``mode=ro`` URI），全模块零 INSERT/UPDATE/DELETE/DDL；写报告/登记表是
   脚本层（scripts/affinity_replay_report.py）的文件 IO，与本模块无关。
5. **补偿只出提案**：``build_compensation_proposals`` 只聚合「已证旧比新
   扣得多」的事件；提案带事件集指纹（SHA-256），重复生成按指纹去重不重复
   计。落库属管理员手工操作（本模块与脚本都不存在 apply 路径）。

规格依据：docs/design/backend-v2-product-extensions.md §2.2/§2.3；
前席事实源：docs/design/v21-affinity-fix-log.md（refuse→insult 解耦与
滚动预算同批于 2026-09-17 落地；补偿重放列为遗留项 2）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .character.affinity import (
    _BEHAVIOR_DELTA,
    classify_behavior,
    score_relationship_signal,
)

# ---------------------------------------------------------------- 常量与口径

POLICY_OLD_REVISION = "pre-v21.1"  # refuse 一律归 insult；无滚动预算钳制
POLICY_NEW_REVISION = "v21.1"  # score_relationship_signal：拒答/非关系事件零计分

_INTERNAL_TO_POINTS = 100.0  # 内部值 → 展示分唯一换算口（spec §2.2 口径）


def behavior_delta_points(behavior: str) -> float:
    """行为 → 展示分（``_BEHAVIOR_DELTA`` ×100；未知行为（如 refusal）= 0）。

    单一事实源是 ``.character.affinity._BEHAVIOR_DELTA``（v21.1 未改数值，
    改的是判定层）；tests/test_v21_affinity_replay.py 有漂移锁。
    """
    return float(_BEHAVIOR_DELTA.get(behavior, 0.0)) * _INTERNAL_TO_POINTS


# ---------------------------------------------------------------- 政策差额层


@dataclass(frozen=True)
class PolicyDiff:
    """单事件「旧 policy vs 新 policy v21.1」判定差额（展示分口径）。

    ``diff_points = 新判分 − 旧判分``：**正数表示旧 policy 比新 policy 多扣了
    这么多分**（误扣证据，如 refuse：旧 -10 → 新 0，差 +10）；``== 0`` 表示
    两代判定一致；``None`` 只出现在逐事件无证据的 unknown 路径
    （见 :class:`ReplayVerdict`），本层不产生 None。
    """

    old_behavior: str
    new_behavior: str
    old_points: float
    new_points: float
    diff_points: float
    old_reason_code: str = ""
    new_reason_code: str = ""

    @property
    def over_deducted(self) -> bool:
        return self.diff_points > 0.0


def old_policy_behavior(
    text: str,
    *,
    safety_category: str = "",
    safety_action: str = "allow",
) -> str:
    """旧 policy（pre-v21.1）行为判定：历史重建，唯一差异=refuse 一律归 insult。

    与 v21.1 前的 ``classify_behavior`` 等价——其余分支（对人直接类别证据、
    excess_intimacy/persona_breaking→tease、正文四则正则启发式）逐支未变，
    直接委托现行实现；refuse 分支按旧语义返回 ``insult``（现行返回
    ``refusal``，delta=0）。类别证据在旧版同样先行于 refuse 分支，两支结论
    同为 insult，无需特判。
    """
    if (safety_action or "allow") == "refuse":
        return "insult"
    return classify_behavior(
        text, safety_category=safety_category, safety_action=safety_action
    )


def new_policy_signal(
    text: str,
    *,
    safety_category: str = "",
    safety_action: str = "allow",
    reason_code: str = "",
) -> tuple[str, str]:
    """新 policy（v21.1）判定：单一事实源直委托 ``score_relationship_signal``。"""
    return score_relationship_signal(
        text,
        safety_category=safety_category,
        safety_action=safety_action,
        reason_code=reason_code,
    )


def event_policy_diff(
    text: str,
    *,
    safety_category: str = "",
    safety_action: str = "allow",
    reason_code: str = "",
) -> PolicyDiff:
    """在**掌握事件原始输入**（正文/类别/动作/原因码）时计算旧新差额。

    这是差额证据的「满配」形态：逐条误扣机制可精确到分（如 refuse 事件旧
    -10 分 → 新 0 分，差额 = 新−旧 = +10 分）。注意：delta_log 不存这些输入，
    所以本函数只能用于有独立证据来源的事件（未来 V2.1 事件服务/管理员人工
    核对），不能凭空对 ledger 行调用——那是「无证据不猜」红线。
    """
    old_behavior = old_policy_behavior(
        text, safety_category=safety_category, safety_action=safety_action
    )
    # 旧 policy 没有 reason_code 通道（该参数是 v21.1 新增）：旧判定不消费它。
    new_behavior, new_reason_code = new_policy_signal(
        text,
        safety_category=safety_category,
        safety_action=safety_action,
        reason_code=reason_code,
    )
    old_points = behavior_delta_points(old_behavior)
    new_points = behavior_delta_points(new_behavior)
    return PolicyDiff(
        old_behavior=old_behavior,
        new_behavior=new_behavior,
        old_points=old_points,
        new_points=new_points,
        diff_points=round(new_points - old_points, 6),
        new_reason_code=new_reason_code,
    )


# ---------------------------------------------------------------- 只读接入


class LedgerSchemaError(RuntimeError):
    """只读库缺少重放所需表（旧于 V2.1 §2.3 的库没有 affinity_delta_log）。"""


def open_readonly_connection(db_path: str | Path) -> sqlite3.Connection:
    """以 SQLite ``mode=ro`` 打开好感度库——引擎唯一入库方式（写必被拒）。"""
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def _require_tables(connection: sqlite3.Connection, tables: Sequence[str]) -> None:
    present = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing = [name for name in tables if name not in present]
    if missing:
        raise LedgerSchemaError(
            f"只读库缺少重放所需表：{missing}（早于 V2.1 §2.3 的库没有逐事件账，"
            "该时代事件属『无证据』，不做逐事件重放）"
        )


# ---------------------------------------------------------------- 账本重放层


@dataclass(frozen=True)
class LedgerEvent:
    """affinity_delta_log 一行（内部值口径原样保留）。"""

    event_id: str
    sender_id: str
    bot_id: str
    applied_at: float
    applied_delta: float  # 内部值（库内原样，1.0 = 100 分）
    source: str
    source_event_id: str

    @property
    def applied_points(self) -> float:
        """落地差额的展示分口径（唯一换算口）。"""
        return self.applied_delta * _INTERNAL_TO_POINTS


@dataclass(frozen=True)
class SourceFamily:
    """已验证的 source→行为族映射（每条都必须有代码级出处，宁缺毋错）。"""

    old_behavior: str
    new_behavior: str
    note: str


#: 已验证族登记表（当前唯一成员：poke 覆写路径）。新族必须先在代码里核实
#: 旧新两代判定后再登记——本表是「无证据不猜」红线的白名单形态。
SOURCE_FAMILIES: Mapping[str, SourceFamily] = {
    "poke": SourceFamily(
        old_behavior="positive",
        new_behavior="positive",
        note=(
            "__init__._record_poke_affinity → observe_points(behavior='positive', "
            "source='poke', delta_override=…)：行为由调用方显式给定，不经过 "
            "classify_behavior/score_relationship_signal 判定层，refuse→refusal "
            "与 reason_code 族变更均不触及 → 旧新一致"
        ),
    ),
}


def load_ledger_events(
    connection: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[LedgerEvent]:
    """只读拉取 delta 账全行（时间升序，rowid 作稳定事件 id）。"""
    _require_tables(connection, ("affinity_delta_log",))
    sql = (
        "SELECT rowid, sender_id, bot_id, applied_at, delta, source, source_event_id"
        " FROM affinity_delta_log ORDER BY applied_at ASC, rowid ASC"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    events: list[LedgerEvent] = []
    for row in connection.execute(sql):
        events.append(
            LedgerEvent(
                event_id=f"rowid-{int(row['rowid'])}",
                sender_id=str(row["sender_id"]),
                bot_id=str(row["bot_id"] or ""),
                applied_at=float(row["applied_at"]),
                applied_delta=float(row["delta"]),
                source=str(row["source"] or ""),
                source_event_id=str(row["source_event_id"] or ""),
            )
        )
    return events


VERDICT_POLICY_INVARIANT = "policy_invariant"  # 旧新判定一致（已证，零差额）
VERDICT_OVER_DEDUCTED = "over_deducted"  # 旧比新扣得多（已证，补偿候选）
VERDICT_UNKNOWN = "unknown"  # 无分类证据：不猜旧判/新判/差额，不计补偿


@dataclass(frozen=True)
class ReplayVerdict:
    """单条历史计分事件的差额证据（事件 id/时间/旧判/新判/差额）。"""

    event: LedgerEvent
    verdict: str
    old_behavior: str | None = None  # None = 无证据，不猜
    new_behavior: str | None = None
    old_points: float | None = None
    new_points: float | None = None
    diff_points: float | None = None
    evidence_kind: str = ""
    note: str = ""


def replay_ledger(
    events: Sequence[LedgerEvent],
    *,
    source_families: Mapping[str, SourceFamily] = SOURCE_FAMILIES,
) -> list[ReplayVerdict]:
    """逐事件差额重放：有已验证行为族 → 算旧新差额；否则 unknown。

    族路径的差额用政策表值（判定层），不使用 applied_delta 反推——落地值
    含 v5 多因素调制与预算钳制，反推即臆造；applied 原样附在事件上供参照。
    """
    verdicts: list[ReplayVerdict] = []
    for event in events:
        family = source_families.get(event.source) if event.source else None
        if family is None:
            verdicts.append(
                ReplayVerdict(
                    event=event,
                    verdict=VERDICT_UNKNOWN,
                    evidence_kind="insufficient_classification_evidence",
                    note=(
                        "delta_log 不存行为分类/安全评估输入，source 为空无法确定"
                        "行为族——旧判/新判/差额均不猜（合同：无证据不猜）"
                    ),
                )
            )
            continue
        old_points = behavior_delta_points(family.old_behavior)
        new_points = behavior_delta_points(family.new_behavior)
        # 差额口径与 event_policy_diff 一致：新 − 旧，正数=旧判多扣（误扣量）。
        diff = round(new_points - old_points, 6)
        if diff > 0:
            verdict_kind = VERDICT_OVER_DEDUCTED
        else:
            verdict_kind = VERDICT_POLICY_INVARIANT
        verdicts.append(
            ReplayVerdict(
                event=event,
                verdict=verdict_kind,
                old_behavior=family.old_behavior,
                new_behavior=family.new_behavior,
                old_points=old_points,
                new_points=new_points,
                diff_points=diff,
                evidence_kind=f"source_family:{event.source}",
                note=family.note,
            )
        )
    return verdicts


# ---------------------------------------------------------------- 聚合证据指针


@dataclass(frozen=True)
class CounterEvidence:
    """user_affinity 聚合计数（**审查指针**，非逐事件证据，不构成补偿依据）。"""

    sender_id: str
    affinity_points: float
    interaction_count: int
    negative_count: int
    insult_count: int
    last_insult_at: str
    last_negative_at: str
    updated_at: str
    insult_tag_last_at: str  # 「口无遮拦」标签最近打标时间（G-11 时间戳）


_INSULT_TAG = "口无遮拦"  # _IMPRESSION_RULES insult 档标签名（单一事实源在 affinity.py）


def load_counter_evidence(connection: sqlite3.Connection) -> list[CounterEvidence]:
    """只读拉取有负向/辱骂计数的用户聚合行（insult 降序，具名不猜身份）。"""
    _require_tables(connection, ("user_affinity",))
    rows = connection.execute(
        "SELECT sender_id, affinity, interaction_count, negative_count, insult_count,"
        " last_insult_at, last_negative_at, updated_at, impression_tag_times"
        " FROM user_affinity WHERE insult_count > 0 OR negative_count > 0"
        " ORDER BY insult_count DESC, negative_count DESC, sender_id ASC"
    ).fetchall()
    evidence: list[CounterEvidence] = []
    for row in rows:
        try:
            tag_times = json.loads(str(row["impression_tag_times"] or "{}"))
        except (ValueError, TypeError):
            tag_times = {}
        insult_tag_last = ""
        if isinstance(tag_times, dict):
            value = tag_times.get(_INSULT_TAG)
            if isinstance(value, str):
                insult_tag_last = value
        evidence.append(
            CounterEvidence(
                sender_id=str(row["sender_id"]),
                affinity_points=float(row["affinity"]) * _INTERNAL_TO_POINTS,
                interaction_count=int(row["interaction_count"]),
                negative_count=int(row["negative_count"]),
                insult_count=int(row["insult_count"]),
                last_insult_at=str(row["last_insult_at"] or ""),
                last_negative_at=str(row["last_negative_at"] or ""),
                updated_at=str(row["updated_at"] or ""),
                insult_tag_last_at=insult_tag_last,
            )
        )
    return evidence


# ---------------------------------------------------------------- 补偿提案层


@dataclass(frozen=True)
class CompensationProposal:
    """具名补偿提案（待审，绝不自动落库）。"""

    sender_id: str
    bot_id: str
    total_points: float  # 建议恢复的展示分（= Σ 逐事件已证差额）
    event_count: int
    event_ids: tuple[str, ...]
    events: tuple[LedgerEvent, ...] = field(repr=False)
    fingerprint: str
    basis: str

    def to_registry_entry(self, *, generated_at: str) -> dict[str, object]:
        """登记表条目（脚本层持久化用；纯数据，无 IO）。"""
        return {
            "fingerprint": self.fingerprint,
            "sender_id": self.sender_id,
            "bot_id": self.bot_id,
            "total_points": self.total_points,
            "event_count": self.event_count,
            "event_ids": list(self.event_ids),
            "basis": self.basis,
            "generated_at": generated_at,
        }


def compensation_fingerprint(events: Sequence[LedgerEvent]) -> str:
    """事件集指纹（SHA-256）——同一事件集必得同一指纹（幂等去重锚点）。

    参与字段=账本行全字段（sender/bot/时间/落地值/source/事件 id），规范化
    JSON + 排序后摘要；任何一字段不同 → 指纹不同 → 不会错误去重。
    """
    canonical = sorted(
        [
            event.sender_id,
            event.bot_id,
            repr(event.applied_at),
            repr(event.applied_delta),
            event.source,
            event.source_event_id,
            event.event_id,
        ]
        for event in events
    )
    payload = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"affcomp-v1:{digest[:24]}"


def build_compensation_proposals(
    verdicts: Sequence[ReplayVerdict],
    *,
    known_fingerprints: frozenset[str] | set[str] = frozenset(),
    policy_basis: str = (
        f"{POLICY_OLD_REVISION}（refuse 归 insult，无预算钳制）vs "
        f"{POLICY_NEW_REVISION}（score_relationship_signal 拒答/非关系事件零计分）"
    ),
) -> tuple[list[CompensationProposal], list[CompensationProposal]]:
    """聚合「已证多扣」事件 → 具名提案；已知指纹进 duplicates 不重复计。

    返回 ``(new_proposals, duplicate_proposals)``：duplicates 只作展示
    （「已提案过，不重复计」），调用方合计补偿总量时**只数 new**。
    unknown / 零差额事件在此被结构性排除——不存在靠参数混入的路径。
    """
    grouped: dict[tuple[str, str], list[ReplayVerdict]] = defaultdict(list)
    totals: dict[tuple[str, str], float] = defaultdict(float)
    for verdict in verdicts:
        if verdict.verdict != VERDICT_OVER_DEDUCTED:
            continue
        diff = verdict.diff_points
        if diff is None or diff <= 0:
            continue
        key = (verdict.event.sender_id, verdict.event.bot_id)
        grouped[key].append(verdict)
        totals[key] += diff

    new_proposals: list[CompensationProposal] = []
    duplicate_proposals: list[CompensationProposal] = []
    for (sender_id, bot_id), members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda v: (v.event.applied_at, v.event.event_id))
        fingerprint = compensation_fingerprint([v.event for v in ordered])
        total = round(totals[(sender_id, bot_id)], 6)
        proposal = CompensationProposal(
            sender_id=sender_id,
            bot_id=bot_id,
            total_points=total,
            event_count=len(ordered),
            event_ids=tuple(v.event.event_id for v in ordered),
            events=tuple(v.event for v in ordered),
            fingerprint=fingerprint,
            basis=(
                f"逐事件已证差额合计（{policy_basis}）；"
                f"证据=delta_log 行 {[v.event.event_id for v in ordered]}"
            ),
        )
        if fingerprint in known_fingerprints:
            duplicate_proposals.append(proposal)
        else:
            new_proposals.append(proposal)
    return new_proposals, duplicate_proposals


def parse_known_fingerprints(entries: Iterable[object]) -> frozenset[str]:
    """从登记表条目（dict 形态）提取已知指纹（脏数据行跳过不炸）。"""
    known: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict):
            value = entry.get("fingerprint")
            if isinstance(value, str) and value:
                known.add(value)
    return frozenset(known)


# ---------------------------------------------------------------- 汇总与报告


@dataclass(frozen=True)
class ReplayResult:
    """一次只读重放的全部产物（纯数据，报告由脚本层渲染或本层 build_text_report）。"""

    events: tuple[LedgerEvent, ...]
    verdicts: tuple[ReplayVerdict, ...]
    counters: tuple[CounterEvidence, ...]

    def verdict_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for verdict in self.verdicts:
            counts[verdict.verdict] += 1
        return dict(counts)

    def proven_over_deduction_points(self) -> float:
        """已证多扣合计（分）——unknown 事件结构性不计入。"""
        return round(
            sum(
                float(v.diff_points)
                for v in self.verdicts
                if v.verdict == VERDICT_OVER_DEDUCTED and v.diff_points is not None
            ),
            6,
        )


def run_replay(
    connection: sqlite3.Connection,
    *,
    source_families: Mapping[str, SourceFamily] = SOURCE_FAMILIES,
    limit: int | None = None,
) -> ReplayResult:
    """只读全流程：拉账 → 逐事件差额 → 聚合证据指针。零写入路径。"""
    events = load_ledger_events(connection, limit=limit)
    verdicts = replay_ledger(events, source_families=source_families)
    counters = load_counter_evidence(connection)
    return ReplayResult(
        events=tuple(events), verdicts=tuple(verdicts), counters=tuple(counters)
    )


def _fmt_utc(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def build_text_report(
    result: ReplayResult,
    *,
    db_label: str,
    generated_at: float | None = None,
    proposals: Sequence[CompensationProposal] = (),
    duplicates: Sequence[CompensationProposal] = (),
    max_event_lines: int = 500,
) -> str:
    """渲染人读报告（Markdown）——诚实口径：unknown 不美化、提案不自动执行。"""
    moment = _fmt_utc(generated_at if generated_at is not None else time.time())
    counts = result.verdict_counts()
    unknown = counts.get(VERDICT_UNKNOWN, 0)
    invariant = counts.get(VERDICT_POLICY_INVARIANT, 0)
    over = counts.get(VERDICT_OVER_DEDUCTED, 0)
    lines: list[str] = []
    lines.append("# V21-AFFINITY-002 历史误扣重放与具名补偿（待审提案报告）")
    lines.append("")
    lines.append(f"- 生成时刻：{moment}（UTC）")
    lines.append(f"- 只读库：`{db_label}`（引擎全程 `mode=ro`，零写入路径）")
    lines.append(
        f"- 政策对照：{POLICY_OLD_REVISION}（refuse 一律归 insult，无滚动预算）"
        f" vs {POLICY_NEW_REVISION}"
        "（score_relationship_signal：拒答/七类非关系事件零计分）"
    )
    lines.append(
        f"- 逐事件账总行数：{len(result.events)}"
        f"（48h prune 滚动窗；早于账本存在的事件无逐事件记录）"
    )
    lines.append(
        f"- 判定分布：已证零差额 {invariant} / 已证多扣 {over} / "
        f"无证据 unknown {unknown}"
    )
    lines.append("")
    lines.append("## 一、逐事件差额证据清单")
    lines.append("")
    if not result.verdicts:
        lines.append("（账本为空：无逐事件记录可重放。）")
    else:
        lines.append(
            "| 事件 id | 时间(UTC) | 用户 | 落地分 | source | 旧判 | 新判 | 差额分 | 判定 |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for verdict in result.verdicts[:max_event_lines]:
            event = verdict.event
            old = verdict.old_behavior if verdict.old_behavior is not None else "unknown"
            new = verdict.new_behavior if verdict.new_behavior is not None else "unknown"
            diff = (
                f"{verdict.diff_points:+.1f}"
                if verdict.diff_points is not None
                else "unknown"
            )
            lines.append(
                f"| {event.event_id} | {_fmt_utc(event.applied_at)} | "
                f"{event.sender_id} | {event.applied_points:+.2f} | "
                f"{event.source or '(空)'} | {old} | {new} | {diff} | {verdict.verdict} |"
            )
        if len(result.verdicts) > max_event_lines:
            lines.append(
                f"（仅列前 {max_event_lines} 条，其余 {len(result.verdicts) - max_event_lines}"
                " 条判定分布已计入上文统计。）"
            )
    lines.append("")
    lines.append("## 二、聚合计数证据指针（**非逐事件证据，不构成补偿依据**）")
    lines.append("")
    lines.append(
        "预算前时代（≤2026-09-17，含 grok 路由测试夜）的逐事件记录在 "
        "`affinity_delta_log` 存在之前，物理缺失；下表只是 user_affinity 聚合计数"
        "（旧 policy 时代每次 refuse→insult 判定都会 +1 insult_count 并打"
        f"「{_INSULT_TAG}」标），用于管理员对照聊天记录人工核查，不得直接换算补偿。"
    )
    lines.append("")
    if not result.counters:
        lines.append("（无 insult_count/negative_count > 0 的用户。）")
    else:
        lines.append(
            "| 用户 | 当前好感(分) | 互动数 | insult 计数 | negative 计数"
            " | 末次 insult | 口无遮拦打标 | 最后互动 |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for counter in result.counters:
            lines.append(
                f"| {counter.sender_id} | {counter.affinity_points:+.1f}"
                f" | {counter.interaction_count} | {counter.insult_count}"
                f" | {counter.negative_count} | {counter.last_insult_at or '—'}"
                f" | {counter.insult_tag_last_at or '—'} | {counter.updated_at or '—'} |"
            )
    lines.append("")
    lines.append("## 三、具名补偿提案（待审；本引擎与脚本均无落库路径）")
    lines.append("")
    new_total = round(sum(p.total_points for p in proposals), 6)
    dup_total = round(sum(p.total_points for p in duplicates), 6)
    if not proposals and not duplicates:
        lines.append(
            "（零提案：当前账本内没有「已证旧比新扣得多」的事件。无证据事件"
            f" {unknown} 条一律 unknown，不猜、不计补偿——含一晚 40+ 分事故："
            "其逐事件记录物理缺失，只能按第二节指针人工核查后由管理员裁决。）"
        )
    else:
        if proposals:
            lines.append(
                f"### 新提案 {len(proposals)} 项，合计 {new_total:+.1f} 分（本次计入）"
            )
            lines.append("")
            for proposal in proposals:
                lines.append(f"- **用户 {proposal.sender_id}**（bot_id=`{proposal.bot_id}`）")
                lines.append(
                    f"  - 建议恢复：{proposal.total_points:+.1f} 分；"
                    f"依据事件数：{proposal.event_count}"
                )
                lines.append(f"  - 事件集指纹：`{proposal.fingerprint}`")
                lines.append(f"  - 事件 id：{', '.join(proposal.event_ids)}")
                lines.append(f"  - 依据：{proposal.basis}")
            lines.append("")
        if duplicates:
            lines.append(
                f"### 已提案过（指纹命中登记表）{len(duplicates)} 项，"
                f"合计 {dup_total:+.1f} 分——**不重复计**"
            )
            lines.append("")
            for proposal in duplicates:
                lines.append(
                    f"- 用户 {proposal.sender_id}：指纹 "
                    f"`{proposal.fingerprint}`（{proposal.event_count} 事件，"
                    f"{proposal.total_points:+.1f} 分）已登记，跳过。"
                )
            lines.append("")
    lines.append("## 四、手工补偿规程（管理员亲办；本报告不执行任何一步）")
    lines.append("")
    lines.append(
        "1. **逐事件独立确认**：对 unknown 事件，用聊天记录/时间窗人工核对"
        "（引擎不猜）；确认属 refuse 误判且当时无预算钳制，才可纳入补偿。"
    )
    lines.append(
        "2. **停机窗口操作**：改库须 bot 重启才生效（铁律），请在停机窗口以"
        " sqlite3 事务执行；内部值 = 展示分 ÷ 100（勿二次换算）。"
    )
    lines.append(
        "3. **两种写法二选一**（副作用见括号）："
        "`UPDATE user_affinity SET affinity = max(-1.0, min(1.0, affinity + X))`"
        "（不落日志行：滚动预算账 48h 内少记这段历史，日志本就 48h prune）；"
        "或同事务向 affinity_delta_log 追加一行"
        "（source='manual_compensation'，source_event_id='manual-<日期>-<用户>-<序号>'，"
        "delta=X/100：账实一致，但会占 24h 增益预算 ≤3 分额度）。"
    )
    lines.append(
        "4. **防重复补偿**：处置完成后把本报告第三节指纹登记进"
        " `docs/design/v21r2-aff-compensation-registry.json`（脚本自动登记"
        "新指纹；人工处置的 unknown 事件请追加人工条目）。"
    )
    lines.append("")
    lines.append(
        "> 口径声明：本报告全部数字来自只读库原样行；unknown 不美化、"
        "提案不落库、40+ 分事故在逐事件证据出现前不恢复（用户裁定）。"
    )
    return "\n".join(lines)
