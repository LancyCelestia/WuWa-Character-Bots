"""V2.1 S5 Usage/Billing Service：存储、预算 CAS、结算、去重、聚合与迁移。

合同：``docs/design/backend-v2-product-extensions.md`` §1.1–§1.3。
**复用既有 ``llm/ledger.py``（只读适配，不重写不改其文件）**：
- ``migrate_ledger_records`` 把 ``llm_call_records`` 存量行导入为
  UsageAttempt + Settlement：旧 ``cost_milli`` 保留**迁移来源与精度**
  （Decimal(milli)/1000，不凭空恢复被舍入的小数），**绝不用今价重算**
  （不查询 PriceBook）；
- :meth:`BillingService.attach_ledger_sink` 经 :class:
  ``CallRecordSink`` 协议把新结算**适配**回旧账本观测面（fail-open），
  精度差异（ledger 为毫厘 1e-3）在 draft 层显式量化。

正确性红线（§1.3）：
- 预算：SQLite 事务 CAS 扣占（``BEGIN IMMEDIATE``），**并发不能超卖**；
  未登记授权预算不猜充值额；
- 请求受理后 UNKNOWN 不立即释放预算或重发；按 provider 状态/账单对账，
  有据再结算或撤销；无查询能力则 unknown 挂账并告警；
- 取消只标 ``cancel_requested`` 语义（outcome=cancelled），保留可能已
  产生的费用（取消后仍可结算）；
- 价格缺失且无已授权保守上限 → ``price_unavailable``，不以 unknown 绕过
  预算；
- provider 重复 usage 回调以 ``attempt_id + source_event_key`` 去重；
- 重试费用属于原 operation（failover 多 attempt 同 operation 聚合），
  不能只统计最后成功模型；
- 历史结算不可覆盖：修正/退款一律追加新 revision（原始行不动）。

金额纪律：落库一律十进制普通记数字符串（TEXT，禁浮点 REAL）；预算 CAS
用微元（1e-6）整数算术。本层不做 REST/SSE/价格导入脚本（后续席位）。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.billing_entities import (
    ALL_METRICS,
    AggregatedUsage,
    BudgetExceededError,
    BudgetNotFoundError,
    ChargeLine,
    PriceRevision,
    Settlement,
    SettlementImmutableError,
    UsageAttempt,
    UsageBillingError,
    UsageQuantity,
    UsageSnapshot,
    amount_to_micros,
    money_str,
    parse_decimal,
    quantize_amount,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.billing_pricing import (
    PriceBook,
    quote_usage,
)

logger = logging.getLogger(__name__)

UTC = datetime.timezone.utc

# ledger 毫厘精度（1e-3 元）：draft 适配层显式量化目标。
_LEDGER_MILLI = Decimal("0.001")


def _now_iso() -> str:
    return datetime.datetime.now(UTC).isoformat(timespec="milliseconds")


def _iso(value: datetime.datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds")


def _parse_iso(value: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _payload_hash(quantities: Sequence[UsageQuantity], outcome: str) -> str:
    canonical = json.dumps(
        [
            [q.metric, money_str(q.value), q.status, q.cache_tier]
            for q in sorted(quantities, key=lambda q: (q.metric, q.cache_tier))
        ]
        + [outcome],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ==================== 过滤器与结果 DTO ====================


@dataclass(frozen=True)
class UsageFilter:
    """aggregate_usage 过滤（§1.3：管理员可按模型/渠道/会话/能力/测试 run）。"""

    owner: str | None = None
    operation_id: str | None = None
    provider: str | None = None
    channel: str | None = None
    model: str | None = None
    task_kind: str | None = None
    currency: str | None = None
    test_run_id: str | None = None
    from_at: datetime.datetime | None = None
    to_at: datetime.datetime | None = None


@dataclass
class RecordResult:
    attempt_id: str
    duplicated: bool
    event_key: str


@dataclass
class ReservationResult:
    reservation_id: str
    budget_id: str
    remaining_micros: int
    amount_micros: int


@dataclass
class ReconciliationResult:
    attempt_id: str
    status: str  # settled / released_no_charge / still_unknown
    alert: bool = False
    settlement_id: str | None = None


@dataclass
class MigrationReport:
    imported: int = 0
    skipped_duplicated: int = 0
    unpriced: int = 0
    errors: list[str] = field(default_factory=list)


# ==================== 服务 ====================


class BillingService:
    """Usage/Billing 服务（离线层）：SQLite 存储 + 事务 CAS + 结算编排。

    线程模型：每操作独立短连接（``timeout`` 忙等），预算路径显式
    ``BEGIN IMMEDIATE``——多实例并发安全，CAS 由 SQLite 写锁保证。
    """

    def __init__(self, db_path: str, *, price_book: PriceBook | None = None) -> None:
        self.db_path = str(db_path)
        self.book = price_book if price_book is not None else PriceBook()
        self._ledger_sink: Any = None  # CallRecordSink | None（惰性类型避免环导）
        self._ensure_schema()

    # ---- 连接与 schema ----

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(_SCHEMA_SQL)
        self._load_prices()

    def _load_prices(self) -> None:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT revision_json FROM billing_prices"
                ).fetchall()
        except sqlite3.Error:
            return
        for row in rows:
            try:
                revision = PriceRevision.model_validate_json(str(row["revision_json"]))
            except Exception:  # noqa: BLE001 - 坏行跳过不致命
                logger.warning("billing price row unparsable; skipped")
                continue
            if all(r.price_id != revision.price_id or r.version != revision.version
                   for r in self.book.revisions()):
                self.book.add(revision)

    def register_price(self, revision: PriceRevision) -> None:
        """登记价格版本：入 PriceBook + 落库审计（幂等按 price_id+version）。"""
        if all(r.price_id != revision.price_id or r.version != revision.version
               for r in self.book.revisions()):
            self.book.add(revision)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO billing_prices "
                "(price_id, version, revision_json, created_at) VALUES (?,?,?,?)",
                (revision.price_id, revision.version,
                 revision.model_dump_json(), _now_iso()),
            )

    def attach_ledger_sink(self, sink: Any) -> None:
        """把新结算适配回旧账本观测面（CallRecordSink 协议；fail-open）。"""
        self._ledger_sink = sink

    # ---- 记录与去重（§1.3：重复回调以 attempt+来源事件键去重）----

    def record_attempt(
        self, attempt: UsageAttempt, *, source_event_key: str | None = None
    ) -> RecordResult:
        """登记一次 attempt；同 (attempt_id, source_event_key) 重复回调去重。

        同 attempt 不同事件键（如补全 usage 的后续回调）允许更新最新事实
        （outcome/用量以后到为准），但不产生重复计费（结算幂等在 settle 侧）。
        """
        key = (source_event_key or attempt.source_event_key
               or f"inline:{_payload_hash(attempt.quantities, attempt.outcome)}")
        digest = _payload_hash(attempt.quantities, attempt.outcome)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO billing_usage_events "
                    "(attempt_id, source_event_key, payload_hash, first_seen_at) "
                    "VALUES (?,?,?,?)",
                    (attempt.attempt_id, key, digest, _now_iso()),
                )
                duplicated = cursor.rowcount == 0
                if not duplicated:
                    connection.execute(
                        "INSERT INTO billing_attempts ("
                        "attempt_id, operation_id, provider, channel, model,"
                        " task_kind, owner, scope, trace_id, test_run_id,"
                        " provider_request_id, started_at, finished_at, outcome,"
                        " usage_status, input_semantics,"
                        " cache_creation_includes_read, raw_usage_schema_version,"
                        " quantities_json, source_event_key, created_at"
                        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(attempt_id) DO UPDATE SET "
                        "outcome=excluded.outcome, usage_status=excluded.usage_status,"
                        " quantities_json=excluded.quantities_json,"
                        " finished_at=excluded.finished_at",
                        (
                            attempt.attempt_id, attempt.operation_id, attempt.provider,
                            attempt.channel, attempt.model, attempt.task_kind,
                            attempt.owner, attempt.scope, attempt.trace_id,
                            attempt.test_run_id, attempt.provider_request_id,
                            _iso(attempt.started_at),
                            _iso(attempt.finished_at) if attempt.finished_at else None,
                            attempt.outcome, attempt.usage_status,
                            attempt.input_semantics,
                            "" if attempt.cache_creation_includes_read is None
                            else ("true" if attempt.cache_creation_includes_read
                                  else "false"),
                            attempt.raw_usage_schema_version,
                            json.dumps(
                                [q.model_dump(mode="json") for q in attempt.quantities],
                                ensure_ascii=False,
                            ),
                            key, _now_iso(),
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return RecordResult(attempt.attempt_id, duplicated, key)

    # ---- 结算（幂等；费用归原 operation）----

    def settle_attempt(
        self,
        attempt_id: str | UsageAttempt,
        *,
        book: PriceBook | None = None,
        invoice_ref: str = "",
        reservation_id: str | None = None,
    ) -> Settlement:
        """结算一次 attempt（幂等：已有结算直接返回最新 revision）。

        语义门（usage_inconsistent / unsupported_usage_semantics）在
        quote_usage 内抛出——**拒绝自动结算**而非掩盖。partial 结算
        total_amount=None（不出假总价），known_amount 承载已知部分。
        """
        attempt = (attempt_id if isinstance(attempt_id, UsageAttempt)
                   else self.get_attempt(str(attempt_id)))
        if attempt is None:
            raise UsageBillingError(f"attempt 不存在: {attempt_id}", code="attempt_not_found")
        latest = self.latest_settlement(attempt.attempt_id)
        if latest is not None:
            return latest

        effective_book = book if book is not None else self.book
        quote = quote_usage(
            self._snapshot_of(attempt), effective_book.resolve(
                attempt.started_at,
                provider=attempt.provider, channel=attempt.channel,
                model=attempt.model,
            ),
            attempt_id=attempt.attempt_id,
        )
        status = "settled" if quote.status == "ok" else "partial"
        settlement = Settlement(
            settlement_id=_new_id("stl"),
            attempt_id=attempt.attempt_id,
            operation_id=attempt.operation_id,
            revision=1,
            status=status,  # type: ignore[arg-type]
            currency=quote.currency,
            total_amount=quote.total_amount,
            known_amount=quote.known_amount,
            unknown_metrics=list(quote.unknown_metrics),
            lines=list(quote.lines),
            invoice_ref=invoice_ref,
            reservation_id=reservation_id,
            created_at=datetime.datetime.now(UTC),
        )
        self._insert_settlement(settlement)
        if reservation_id is not None and quote.total_amount is not None:
            self.consume_reservation(reservation_id, quote.total_amount)
        self._emit_ledger_draft(attempt, settlement)
        return settlement

    def _snapshot_of(self, attempt: UsageAttempt) -> UsageSnapshot:
        quantities: dict[str, UsageQuantity] = {}
        for q in attempt.quantities:
            key = q.metric if not q.cache_tier else f"{q.metric}#{q.cache_tier}"
            quantities[key] = q
        return UsageSnapshot(
            task_kind=attempt.task_kind,
            input_semantics=attempt.input_semantics,
            cache_creation_includes_read=attempt.cache_creation_includes_read,
            quantities=quantities,
            raw_usage_schema_version=attempt.raw_usage_schema_version,
        )

    def _insert_settlement(self, settlement: Settlement) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO billing_settlements ("
                    "settlement_id, attempt_id, operation_id, revision, status,"
                    " currency, total_amount, known_amount, unknown_metrics_json,"
                    " lines_json, invoice_ref, prev_settlement_id, adjustment_id,"
                    " reservation_id, note, created_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        settlement.settlement_id, settlement.attempt_id,
                        settlement.operation_id, settlement.revision,
                        settlement.status, settlement.currency,
                        money_str(settlement.total_amount),
                        money_str(settlement.known_amount) or "0",
                        json.dumps(settlement.unknown_metrics, ensure_ascii=False),
                        json.dumps(
                            [ln.model_dump(mode="json") for ln in settlement.lines],
                            ensure_ascii=False,
                        ),
                        settlement.invoice_ref, settlement.prev_settlement_id,
                        settlement.adjustment_id, settlement.reservation_id,
                        settlement.note, _iso(settlement.created_at),
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise SettlementImmutableError(
                    f"结算 revision 冲突（不可覆盖历史）: {exc}"
                ) from exc
            except Exception:
                connection.rollback()
                raise

    def latest_settlement(self, attempt_id: str) -> Settlement | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM billing_settlements WHERE attempt_id=? "
                "ORDER BY revision DESC LIMIT 1",
                (attempt_id,),
            ).fetchone()
        return None if row is None else self._row_to_settlement(row)

    def get_settlement(self, settlement_id: str) -> Settlement | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM billing_settlements WHERE settlement_id=?",
                (settlement_id,),
            ).fetchone()
        return None if row is None else self._row_to_settlement(row)

    def get_attempt(self, attempt_id: str) -> UsageAttempt | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM billing_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
        return None if row is None else self._row_to_attempt(row)

    @staticmethod
    def _row_to_attempt(row: sqlite3.Row) -> UsageAttempt:
        return UsageAttempt(
            attempt_id=row["attempt_id"], operation_id=row["operation_id"],
            provider=row["provider"], channel=row["channel"], model=row["model"],
            task_kind=row["task_kind"], owner=row["owner"], scope=row["scope"],
            trace_id=row["trace_id"], test_run_id=row["test_run_id"],
            provider_request_id=row["provider_request_id"],
            started_at=_parse_iso(row["started_at"]),
            finished_at=(_parse_iso(row["finished_at"])
                         if row["finished_at"] else None),
            outcome=row["outcome"], usage_status=row["usage_status"],
            input_semantics=row["input_semantics"],
            cache_creation_includes_read=(
                None if not row["cache_creation_includes_read"]
                else row["cache_creation_includes_read"] == "true"
            ),
            raw_usage_schema_version=row["raw_usage_schema_version"],
            quantities=[
                UsageQuantity.model_validate(item)
                for item in json.loads(row["quantities_json"])
            ],
            source_event_key=row["source_event_key"],
        )

    @staticmethod
    def _row_to_settlement(row: sqlite3.Row) -> Settlement:
        return Settlement(
            settlement_id=row["settlement_id"], attempt_id=row["attempt_id"],
            operation_id=row["operation_id"], revision=int(row["revision"]),
            status=row["status"], currency=row["currency"],
            total_amount=(parse_decimal(row["total_amount"], what="total_amount")
                          if row["total_amount"] else None),
            known_amount=parse_decimal(row["known_amount"], what="known_amount"),
            unknown_metrics=list(json.loads(row["unknown_metrics_json"])),
            lines=[ChargeLine.model_validate(item)
                   for item in json.loads(row["lines_json"])],
            invoice_ref=row["invoice_ref"],
            prev_settlement_id=row["prev_settlement_id"],
            adjustment_id=row["adjustment_id"],
            reservation_id=row["reservation_id"],
            note=row["note"], created_at=_parse_iso(row["created_at"]),
        )

    # ---- 调整与退款（§1.1：不可覆盖历史结算，追加 revision）----

    def adjust_charge(
        self,
        settlement_id: str,
        *,
        deltas: dict[str, Decimal | str] | None = None,
        reason: str,
        actor: str,
        refund: bool = False,
    ) -> Settlement:
        """对已结算行追加调整/退款（新 revision）；原始行逐字节保留。

        ``refund=True`` 生成等额反向行（status=refunded）；净额钳制非负
        （调整不得把总额修成负数）。
        """
        base = self.get_settlement(settlement_id)
        if base is None:
            raise UsageBillingError(f"结算不存在: {settlement_id}",
                                    code="settlement_not_found")
        if base.status in ("reserved",):
            raise SettlementImmutableError("reserved 结算无已账金额可调整")
        deltas = deltas or {}
        adjustment_id = _new_id("adj")
        new_lines: list[ChargeLine] = list(base.lines)
        delta_total = Decimal(0)
        for metric, raw_delta in deltas.items():
            if metric not in ALL_METRICS:
                raise UsageBillingError(
                    f"调整计量不合法: {metric!r}（合法集合: {sorted(ALL_METRICS)}）",
                    code="adjustment_invalid",
                )
            delta = parse_decimal(raw_delta, what=f"delta[{metric}]")
            delta_total += delta
            new_lines.append(
                ChargeLine(
                    line_id=f"line-{adjustment_id}-{metric}",
                    attempt_id=base.attempt_id,
                    metric=metric,
                    unit="tokens" if metric.endswith("_tokens") else "requests",
                    amount=delta,
                    currency=base.currency,
                    status="adjustment",
                    billing_group="adjustment",
                )
            )
        if refund:
            reverse = quantize_amount(-(base.total_amount or Decimal(0)))
            new_lines.append(
                ChargeLine(
                    line_id=f"line-{adjustment_id}-refund",
                    attempt_id=base.attempt_id,
                    metric="requests",
                    unit="requests",
                    amount=reverse,
                    currency=base.currency,
                    status="refunded",
                    billing_group="refund",
                )
            )
            delta_total += reverse
        new_total = (base.total_amount or base.known_amount) + delta_total
        if new_total < 0:
            raise UsageBillingError("调整后净额为负（退款超过已账金额）",
                                    code="adjustment_invalid")
        new_status: str = "refunded" if new_total == 0 and refund else (
            "settled" if base.status == "settled" else "partial"
        )
        # 已知部分随调整同步（退款后 net 已反映在 total 中）
        known = (base.known_amount + delta_total
                 if base.total_amount is None else new_total)
        revision = Settlement(
            settlement_id=_new_id("stl"),
            attempt_id=base.attempt_id,
            operation_id=base.operation_id,
            revision=base.revision + 1,
            status=new_status,  # type: ignore[arg-type]
            currency=base.currency,
            total_amount=new_total,
            known_amount=known,
            unknown_metrics=list(base.unknown_metrics)
            if new_status == "partial" else [],
            lines=new_lines,
            prev_settlement_id=base.settlement_id,
            adjustment_id=adjustment_id,
            reservation_id=base.reservation_id,
            note=f"{reason}（by {actor}）",
            created_at=datetime.datetime.now(UTC),
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO billing_adjustments ("
                    "adjustment_id, settlement_id, actor, reason, deltas_json,"
                    " created_at) VALUES (?,?,?,?,?,?)",
                    (adjustment_id, settlement_id, actor, reason,
                     json.dumps({k: money_str(parse_decimal(v, what=k))
                                 for k, v in deltas.items()},
                                ensure_ascii=False),
                     _now_iso()),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        self._insert_settlement(revision)
        return revision

    # ---- 预算（§1.3：SQLite 事务 CAS，并发不超卖；不猜充值额）----

    def ensure_budget(
        self, *, scope_kind: str, scope_key: str, currency: str, limit: Decimal | str
    ) -> str:
        """登记授权预算包（初始金额由授权方提供；重复登记为幂等）。"""
        limit_micros = amount_to_micros(parse_decimal(limit, what="limit"),
                                        what="limit")
        budget_id = f"budget:{scope_kind}:{scope_key}:{currency}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT OR IGNORE INTO budget_envelopes ("
                    "budget_id, scope_kind, scope_key, currency, limit_micros,"
                    " reserved_micros, used_micros, created_at, updated_at"
                    ") VALUES (?,?,?,?,?,0,0,?,?)",
                    (budget_id, scope_kind, scope_key, currency, limit_micros,
                     _now_iso(), _now_iso()),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return budget_id

    def reserve_budget(
        self,
        *,
        scope_kind: str,
        scope_key: str,
        currency: str,
        amount: Decimal | str,
        reservation_id: str | None = None,
        attempt_id: str = "",
    ) -> ReservationResult:
        """事务 CAS 扣占：``BEGIN IMMEDIATE`` 下读余额→校验→写回。

        并发不超卖：可用 = limit − reserved − used；不足即
        ``budget_exceeded``（429）。未登记的预算抛 ``budget_not_found``
        （不猜充值额、不默认无限）。
        """
        amount_micros = amount_to_micros(parse_decimal(amount, what="amount"),
                                         what="amount")
        if amount_micros < 0:
            raise UsageBillingError("预留额必须非负", code="adjustment_invalid")
        budget_id = f"budget:{scope_kind}:{scope_key}:{currency}"
        rid = reservation_id or _new_id("rsv")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT limit_micros, reserved_micros, used_micros "
                    "FROM budget_envelopes WHERE budget_id=?",
                    (budget_id,),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    raise BudgetNotFoundError(f"预算未登记: {budget_id}")
                available = (int(row["limit_micros"]) - int(row["reserved_micros"])
                             - int(row["used_micros"]))
                if amount_micros > available:
                    connection.rollback()
                    raise BudgetExceededError(
                        f"预算不足: 需要 {amount_micros}μ 可用仅 {available}μ"
                        f"（{scope_kind}/{scope_key}/{currency}）"
                    )
                connection.execute(
                    "UPDATE budget_envelopes SET reserved_micros = "
                    "reserved_micros + ?, updated_at=? WHERE budget_id=? AND "
                    "reserved_micros=?",
                    (amount_micros, _now_iso(), budget_id,
                     int(row["reserved_micros"])),
                )
                connection.execute(
                    "INSERT INTO budget_reservations (reservation_id, budget_id,"
                    " attempt_id, amount_micros, state, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (rid, budget_id, attempt_id, amount_micros, "held",
                     _now_iso(), _now_iso()),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        remaining = self.budget_state(budget_id)["available_micros"]
        return ReservationResult(rid, budget_id, remaining, amount_micros)

    def budget_state(self, budget_id: str) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT limit_micros, reserved_micros, used_micros "
                "FROM budget_envelopes WHERE budget_id=?",
                (budget_id,),
            ).fetchone()
        if row is None:
            raise BudgetNotFoundError(f"预算未登记: {budget_id}")
        limit_micros = int(row["limit_micros"])
        reserved = int(row["reserved_micros"])
        used = int(row["used_micros"])
        return {
            "limit_micros": limit_micros,
            "reserved_micros": reserved,
            "used_micros": used,
            "available_micros": limit_micros - reserved - used,
        }

    def consume_reservation(
        self, reservation_id: str, actual: Decimal | str
    ) -> ReservationResult:
        """结算消耗：reserved 释放、used 记实际额（实际>预留允许，靠 used 显现）。"""
        actual_micros = amount_to_micros(parse_decimal(actual, what="actual"),
                                         what="actual")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT budget_id, amount_micros, state FROM "
                    "budget_reservations WHERE reservation_id=?",
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    raise BudgetNotFoundError(f"预留不存在: {reservation_id}")
                if row["state"] != "held":
                    connection.rollback()
                    raise UsageBillingError(
                        f"预留状态不可消耗: {row['state']}", code="reservation_state"
                    )
                held = int(row["amount_micros"])
                connection.execute(
                    "UPDATE budget_envelopes SET reserved_micros = "
                    "reserved_micros - ?, used_micros = used_micros + ?, "
                    "updated_at=? WHERE budget_id=?",
                    (held, actual_micros, _now_iso(), row["budget_id"]),
                )
                connection.execute(
                    "UPDATE budget_reservations SET state='consumed', updated_at=? "
                    "WHERE reservation_id=?",
                    (_now_iso(), reservation_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        state = self.budget_state(str(row["budget_id"]))
        return ReservationResult(reservation_id, str(row["budget_id"]),
                                 state["available_micros"], actual_micros)

    def release_reservation(self, reservation_id: str) -> ReservationResult:
        """撤销释放（未产生费用的预留）；幂等（已释放/已消耗直接返回）。"""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT budget_id, amount_micros, state FROM "
                    "budget_reservations WHERE reservation_id=?",
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    raise BudgetNotFoundError(f"预留不存在: {reservation_id}")
                if row["state"] == "held":
                    connection.execute(
                        "UPDATE budget_envelopes SET reserved_micros = "
                        "reserved_micros - ?, updated_at=? WHERE budget_id=?",
                        (int(row["amount_micros"]), _now_iso(), row["budget_id"]),
                    )
                    connection.execute(
                        "UPDATE budget_reservations SET state='released', "
                        "updated_at=? WHERE reservation_id=?",
                        (_now_iso(), reservation_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        state = self.budget_state(str(row["budget_id"]))
        return ReservationResult(reservation_id, str(row["budget_id"]),
                                 state["available_micros"], int(row["amount_micros"]))

    # ---- UNKNOWN 对账（§1.3：有据再结算或撤销；无据挂账告警）----

    def reconcile_unknown(
        self,
        attempt_id: str,
        *,
        evidence: dict[str, Any] | None = None,
        book: PriceBook | None = None,
    ) -> ReconciliationResult:
        """对 UNKNOWN attempt 对账：provider 账单证据→结算；未计费证据→
        撤销预留；无证据→继续挂账并告警（不立即释放预算、不重发）。"""
        attempt = self.get_attempt(attempt_id)
        if attempt is None:
            raise UsageBillingError(f"attempt 不存在: {attempt_id}",
                                    code="attempt_not_found")
        evidence = evidence or {}
        reservation_id = self._held_reservation_for(attempt_id)
        if evidence.get("billed") is False:
            if reservation_id:
                self.release_reservation(reservation_id)
            return ReconciliationResult(attempt_id, "released_no_charge")
        if evidence.get("invoice_ref") or evidence.get("usage"):
            settlement = self.settle_attempt(
                attempt, book=book,
                invoice_ref=str(evidence.get("invoice_ref") or ""),
                reservation_id=reservation_id,
            )
            return ReconciliationResult(attempt_id, "settled",
                                        settlement_id=settlement.settlement_id)
        return ReconciliationResult(attempt_id, "still_unknown", alert=True)

    def _held_reservation_for(self, attempt_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT reservation_id FROM budget_reservations WHERE "
                "attempt_id=? AND state='held' ORDER BY created_at DESC LIMIT 1",
                (attempt_id,),
            ).fetchone()
        return None if row is None else str(row["reservation_id"])

    # ---- 聚合（§1.3：分币分别汇总；排行榜与账本一致）----

    def aggregate_usage(
        self, filter_: UsageFilter | None = None, bucket: str | None = None
    ) -> list[AggregatedUsage]:
        """按过滤条件聚合用量/金额/次数；``bucket`` 分桶（day/operation/
        model/channel/provider/owner/task_kind）；None=总计单行。

        金额取每 attempt **最新 revision** 结算的 total（partial 取
        known_amount；unknown/unpriced 不计金额只计次）；退款后的净额
        自然反映（refunded revision 的 total 即净额）。
        """
        filter_ = filter_ or UsageFilter()
        attempts = self._iter_attempts(filter_)
        rows: dict[str, AggregatedUsage] = {}

        def _row_for(key: str, bucket_name: str) -> AggregatedUsage:
            if key not in rows:
                rows[key] = AggregatedUsage(bucket=bucket_name, key=key)
            return rows[key]

        default_key = "total"
        for attempt in attempts:
            key = default_key
            if bucket == "operation":
                key = attempt.operation_id
            elif bucket == "model":
                key = attempt.model
            elif bucket == "channel":
                key = attempt.channel
            elif bucket == "provider":
                key = attempt.provider
            elif bucket == "owner":
                key = attempt.owner
            elif bucket == "task_kind":
                key = attempt.task_kind
            elif bucket == "day":
                key = _iso(attempt.started_at)[:10]
            row = _row_for(key, bucket or "total")
            row.counts.requested += 1
            row.counts.submitted += 1
            if attempt.outcome == "succeeded":
                row.counts.succeeded += 1
            for q in attempt.quantities:
                if q.value is not None and q.status in ("measured", "estimated"):
                    row.metric_totals[q.metric] = (
                        row.metric_totals.get(q.metric, Decimal(0)) + q.value
                    )
            settlement = self.latest_settlement(attempt.attempt_id)
            if settlement is None:
                row.unpriced_attempts += 1
                continue
            if settlement.status == "unknown":
                row.unknown_attempts += 1
                continue
            amount = (settlement.total_amount if settlement.total_amount is not None
                      else settlement.known_amount)
            row.amounts[settlement.currency] = (
                row.amounts.get(settlement.currency, Decimal(0)) + amount
            )
            row.counts.billed_requests = (row.counts.billed_requests or 0) + 1
        # 账单未知（未知结局/未结算/未知结算）→ billed_requests=null
        # （不用成功数代替计费次数，§1.3）。
        for row in rows.values():
            if row.unknown_attempts > 0 or row.unpriced_attempts > 0:
                row.counts.billed_requests = None
        return [rows[k] for k in sorted(rows)]

    def _iter_attempts(self, filter_: UsageFilter) -> list[UsageAttempt]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("owner", filter_.owner), ("operation_id", filter_.operation_id),
            ("provider", filter_.provider), ("channel", filter_.channel),
            ("model", filter_.model), ("task_kind", filter_.task_kind),
            ("test_run_id", filter_.test_run_id),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if filter_.from_at is not None:
            clauses.append("started_at >= ?")
            params.append(_iso(filter_.from_at))
        if filter_.to_at is not None:
            clauses.append("started_at < ?")
            params.append(_iso(filter_.to_at))
        sql = "SELECT * FROM billing_attempts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY started_at, attempt_id"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._row_to_attempt(row) for row in rows]

    # ---- 旧账本迁移（只读 llm/ledger.py 数据；保留精度与来源；不重算）----

    def migrate_ledger_records(
        self, ledger_db_path: str, *, window_days: int | None = None
    ) -> MigrationReport:
        """llm_call_records → UsageAttempt + Settlement（幂等）。

        - attempt_id = ``legacy-{request_id}-{call_seq}``；source_event_key =
          ``ledger:{request_id}:{call_seq}`` → 重跑去重；
        - 旧 cost_milli：``Decimal(milli)/1000``（毫厘精度如实保留，不凭空
          恢复被舍入的小数），行 ``pricing_source`` 记入账单行 source；
        - **不查询 PriceBook、不用今价重算**（历史数据不得用今天价格重算
          后覆盖，§1.2）；未计价行（cost 全 NULL 但有 token）落 unknown
          结算（「未知不是 0」口径延续）。
        """
        report = MigrationReport()
        rows = self._read_ledger_rows(ledger_db_path)
        for row in rows:
            attempt_id = f"legacy-{row['request_id']}-{int(row['call_seq'])}"
            attempt = self._legacy_row_to_attempt(row, attempt_id)
            result = self.record_attempt(
                attempt,
                source_event_key=f"ledger:{row['request_id']}:{int(row['call_seq'])}",
            )
            if result.duplicated:
                report.skipped_duplicated += 1
                continue
            report.imported += 1
            if row["total_cost_milli"] is None:
                if (row["total_tokens"] or 0) > 0:
                    report.unpriced += 1
                    self._insert_settlement(self._legacy_unknown_settlement(attempt))
                continue
            self._insert_settlement(self._legacy_settlement(row, attempt))
        return report

    @staticmethod
    def _read_ledger_rows(ledger_db_path: str) -> list[sqlite3.Row]:
        import pathlib

        connection = sqlite3.connect(
            f"file:{pathlib.Path(ledger_db_path).as_posix()}?mode=ro",
            uri=True, timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(
                "SELECT * FROM llm_call_records ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

    @staticmethod
    def _legacy_row_to_attempt(row: sqlite3.Row, attempt_id: str) -> UsageAttempt:
        quantities: list[UsageQuantity] = []
        for metric, column in (
            ("input_tokens", "prompt_tokens"),
            ("cache_create_tokens", "cache_creation_tokens"),
            ("cache_read_tokens", "cache_read_tokens"),
            ("output_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            value = row[column]
            quantities.append(
                UsageQuantity(
                    metric=metric, unit="tokens",
                    value=None if value is None else Decimal(int(value)),
                    status="measured" if value is not None else "unknown",
                    source="legacy_ledger",
                )
            )
        started = str(row["started_at"] or "")
        finished = str(row["completed_at"] or "")
        return UsageAttempt(
            attempt_id=attempt_id,
            operation_id=str(row["request_id"] or attempt_id),
            provider=str(row["provider_id"] or "unknown"),
            channel=normalize_legacy_channel(row["provider_id"], row["model_id"]),
            model=str(row["actual_model"] or row["model_id"] or "unknown"),
            task_kind="chat",
            owner="legacy",
            scope=str(row["session_id"] or ""),
            trace_id="",
            provider_request_id=str(row["request_id"] or ""),
            started_at=_parse_legacy_time(started),
            finished_at=_parse_legacy_time(finished) if finished else None,
            outcome="succeeded" if row["status"] == "success" else "failed",
            usage_status="measured" if row["total_tokens"] is not None else "unknown",
            input_semantics="unknown",
            cache_creation_includes_read=None,
            raw_usage_schema_version=f"ledger_v{int(row['schema_ver'] or 1)}",
            quantities=quantities,
        )

    @staticmethod
    def _legacy_settlement(row: sqlite3.Row, attempt: UsageAttempt) -> Settlement:
        lines: list[ChargeLine] = []
        for metric, column in (
            ("input_tokens", "input_cost_milli"),
            ("cache_read_tokens", "cache_read_cost_milli"),
            ("output_tokens", "output_cost_milli"),
        ):
            milli = row[column]
            if milli is None:
                continue
            lines.append(
                ChargeLine(
                    line_id=f"line-{attempt.attempt_id}-legacy-{column}",
                    attempt_id=attempt.attempt_id,
                    metric=metric, unit="tokens",
                    amount=Decimal(int(milli)) / Decimal(1000),
                    currency=str(row["currency"] or "CNY"),
                    status="billed",
                    billing_group="legacy",
                )
            )
        return Settlement(
            settlement_id=_new_id("stl"),
            attempt_id=attempt.attempt_id,
            operation_id=attempt.operation_id,
            revision=1,
            status="settled",
            currency=str(row["currency"] or "CNY"),
            total_amount=Decimal(int(row["total_cost_milli"])) / Decimal(1000),
            known_amount=Decimal(int(row["total_cost_milli"])) / Decimal(1000),
            lines=lines,
            invoice_ref=f"legacy:llm_call_records:{row['request_id']}",
            note=f"legacy_cost_milli/{row['pricing_source']}（迁移保精度，未重算）",
            created_at=datetime.datetime.now(UTC),
        )

    @staticmethod
    def _legacy_unknown_settlement(attempt: UsageAttempt) -> Settlement:
        return Settlement(
            settlement_id=_new_id("stl"),
            attempt_id=attempt.attempt_id,
            operation_id=attempt.operation_id,
            revision=1,
            status="unknown",
            currency="CNY",
            total_amount=None,
            known_amount=Decimal(0),
            unknown_metrics=["price:legacy_unpriced"],
            lines=[],
            note="legacy 未计价行（unpriced=1）：未知不是 0",
            created_at=datetime.datetime.now(UTC),
        )

    # ---- 旧账本观测面适配（CallRecordSink 协议；精度差异显式量化）----

    def _emit_ledger_draft(self, attempt: UsageAttempt, settlement: Settlement) -> None:
        if self._ledger_sink is None:
            return
        try:
            from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
                LLMCallDraft,
            )

            def _token(metric: str) -> int | None:
                q = next((x for x in attempt.quantities if x.metric == metric), None)
                if q is None or q.value is None:
                    return None
                return int(q.value)

            total = settlement.total_amount
            draft = LLMCallDraft(
                request_id=attempt.provider_request_id or attempt.attempt_id,
                session_id=attempt.scope,
                capability=attempt.task_kind,
                started_at=_iso(attempt.started_at),
                completed_at=(_iso(attempt.finished_at) if attempt.finished_at
                              else _iso(attempt.started_at)),
                provider_id=attempt.provider, model_id=attempt.channel,
                actual_model=attempt.model,
                prompt_tokens=_token("input_tokens"),
                cache_creation_tokens=_token("cache_create_tokens"),
                cache_read_tokens=_token("cache_read_tokens"),
                completion_tokens=_token("output_tokens"),
                total_tokens=_token("total_tokens"),
                total_cost_milli=(
                    int((total / _LEDGER_MILLI).quantize(Decimal(1),
                                                         rounding=ROUND_HALF_UP))
                    if total is not None else None
                ),
                currency=settlement.currency,
                pricing_source="billing_v21",
                unpriced=0 if settlement.total_amount is not None else 1,
                status=attempt.outcome,
                source="billing_service",
            )
            self._ledger_sink.submit(draft)
        except Exception:
            logger.debug("billing ledger sink emit failed", exc_info=True)


def normalize_legacy_channel(provider_id: object, model_id: object) -> str:
    """旧账本行渠道归一：provider_id 即渠道注册 id；缺失记 unknown（不拿
    模型名冒充渠道）。"""
    text = str(provider_id or "").strip()
    return text if text else "unknown"


def _parse_legacy_time(value: str) -> datetime.datetime:
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return datetime.datetime(1970, 1, 1, tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS billing_attempts (
    attempt_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    channel TEXT NOT NULL,
    model TEXT NOT NULL,
    task_kind TEXT NOT NULL,
    owner TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    trace_id TEXT NOT NULL DEFAULT '',
    test_run_id TEXT NOT NULL DEFAULT '',
    provider_request_id TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL,
    usage_status TEXT NOT NULL,
    input_semantics TEXT NOT NULL,
    cache_creation_includes_read TEXT,
    raw_usage_schema_version TEXT NOT NULL,
    quantities_json TEXT NOT NULL,
    source_event_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_batt_op ON billing_attempts (operation_id);
CREATE INDEX IF NOT EXISTS idx_batt_started ON billing_attempts (started_at);
CREATE INDEX IF NOT EXISTS idx_batt_owner ON billing_attempts (owner, started_at);
CREATE INDEX IF NOT EXISTS idx_batt_model ON billing_attempts (model, started_at);

CREATE TABLE IF NOT EXISTS billing_usage_events (
    attempt_id TEXT NOT NULL,
    source_event_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (attempt_id, source_event_key)
);

CREATE TABLE IF NOT EXISTS billing_settlements (
    settlement_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    operation_id TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    currency TEXT NOT NULL,
    total_amount TEXT,
    known_amount TEXT NOT NULL,
    unknown_metrics_json TEXT NOT NULL DEFAULT '[]',
    lines_json TEXT NOT NULL DEFAULT '[]',
    invoice_ref TEXT NOT NULL DEFAULT '',
    prev_settlement_id TEXT,
    adjustment_id TEXT,
    reservation_id TEXT,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (attempt_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_bset_attempt ON billing_settlements (attempt_id, revision);
CREATE INDEX IF NOT EXISTS idx_bset_op ON billing_settlements (operation_id);

CREATE TABLE IF NOT EXISTS billing_adjustments (
    adjustment_id TEXT PRIMARY KEY,
    settlement_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    deltas_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS billing_prices (
    price_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    revision_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (price_id, version)
);

CREATE TABLE IF NOT EXISTS budget_envelopes (
    budget_id TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    currency TEXT NOT NULL,
    limit_micros INTEGER NOT NULL,
    reserved_micros INTEGER NOT NULL DEFAULT 0,
    used_micros INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (scope_kind, scope_key, currency)
);

CREATE TABLE IF NOT EXISTS budget_reservations (
    reservation_id TEXT PRIMARY KEY,
    budget_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL DEFAULT '',
    amount_micros INTEGER NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brsv_attempt ON budget_reservations (attempt_id, state);
"""


__all__ = [
    "BillingService",
    "MigrationReport",
    "PriceBook",
    "ReconciliationResult",
    "RecordResult",
    "ReservationResult",
    "UsageFilter",
    "normalize_legacy_channel",
]
