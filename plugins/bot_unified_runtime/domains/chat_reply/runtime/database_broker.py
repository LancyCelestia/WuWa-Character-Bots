"""V2.1 S8 数据库安全查询代理（V21-DB-001）。

合同来源：docs/design/backend-v2-implementation-guide.md §9「Database仅
query_id+schema参数绑定，行数默认200，执行2s；列名/排序只能注册枚举，
禁止任意SQL」+ 验收矩阵行 V21-DB-001（注入、超时/200行限额、无任意表/
排序/SQL）。

安全模型（纵深四层）：
1. **白名单**：只有注册过的 query_id 可执行；query_id 未注册直接拒绝。
   SQL 模板注册期静态校验：仅 SELECT 单语句、禁注释、禁写操作/DDL/
   ATTACH 关键字——注册面即拒绝任意 SQL。
2. **参数化**：全部动态值走 sqlite3 命名绑定参数（``:name``，值永不拼接
   进 SQL）；模板中的命名占位必须都在声明 schema 内、参数名必须在
   schema 内（schema 外一律拒绝）、类型必须匹配（bool≠int）；排序类
   参数只能取注册枚举内的列名，枚举命中后再过标识符白名单正则才允许
   替换进 ORDER BY。
3. **只读连接**：一律以 SQLite URI ``mode=ro`` 打开（复用 llm/ledger.py
   aggregate_channel_usage 的既有先例），即使模板校验被绕过也写不进库。
4. **有界执行**：progress handler 实现 wall-clock 语句超时（默认 2s，
   超时抛 QueryTimeoutError）；fetchmany(limit+1) 实现行限（默认 200，
   截断时如实置 truncated=true，绝不静默丢弃或多取）。

复用边界：不建连接池、不改任何存量库的写入路径；五个预注册查询全部
指向 docs/db-owners.md 在册的现有库（发送队列/好感度/账本/审计/订阅）。
"""

from __future__ import annotations

import math
import pathlib
import re
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DEFAULT_ROW_LIMIT",
    "DEFAULT_TIMEOUT_SECONDS",
    "BrokerQueryError",
    "BrokerResult",
    "DatabaseBroker",
    "QueryParamError",
    "QuerySortError",
    "QuerySpec",
    "QueryTemplateError",
    "QueryTimeoutError",
    "UnknownQueryError",
    "build_database_broker",
    "build_default_registry",
]

DEFAULT_ROW_LIMIT = 200
DEFAULT_TIMEOUT_SECONDS = 2.0

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_NAMED_PARAM_RE = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")

# 模板静态黑名单（词边界）：任何写操作/DDL/实例级命令在注册期即拒绝。
# created_at 这类标识符不会被 \bcreate\b 误伤（后随词字符不构成边界）。
_FORBIDDEN_SQL_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|"
    r"vacuum|reindex|replace|grant|revoke)\b",
    re.IGNORECASE,
)
_COMMENT_MARKERS = ("--", "/*", "*/")


class BrokerQueryError(RuntimeError):
    """代理查询失败基类；code 供调用方/控制面稳定判定。"""

    code = "query_failed"

    def __init__(self, message: str, *, query_id: str = "") -> None:
        super().__init__(message)
        self.query_id = query_id


class UnknownQueryError(BrokerQueryError):
    code = "query_unknown"


class QueryParamError(BrokerQueryError):
    code = "query_param_invalid"


class QuerySortError(BrokerQueryError):
    code = "query_sort_not_allowed"


class QueryTemplateError(BrokerQueryError):
    code = "query_template_invalid"


class QueryTimeoutError(BrokerQueryError):
    code = "query_timeout"


_PARAM_TYPES: dict[str, type] = {"int": int, "float": float, "str": str}


@dataclass(frozen=True)
class QuerySpec:
    """一条白名单查询：SQL 模板 + 参数 schema + 超时 + 行限。

    params: 参数名 -> 声明类型（"int"/"float"/"str"）；bool 一律拒绝
    （bool 是 int 子类，放行会让真值语义混入）。模板中值占位写
    ``:参数名``；排序占位写 ``{参数名}``（必须登记进 order_enum）。
    """

    query_id: str
    sql: str
    db: str
    params: Mapping[str, str] = field(default_factory=dict)
    required_params: frozenset[str] = frozenset()
    order_enum: Mapping[str, frozenset[str]] | None = None
    max_rows: int = DEFAULT_ROW_LIMIT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    description: str = ""


def validate_template(spec: QuerySpec) -> None:
    """注册期模板静态校验：非 SELECT 单语句/注释/黑名单词/未声明占位即拒绝。"""
    sql = spec.sql.strip()
    if not sql:
        raise QueryTemplateError("SQL 模板为空", query_id=spec.query_id)
    if "\x00" in sql:
        raise QueryTemplateError("SQL 模板含 NUL", query_id=spec.query_id)
    if any(marker in sql for marker in _COMMENT_MARKERS):
        raise QueryTemplateError(
            "SQL 模板禁止注释（-- 与块注释）", query_id=spec.query_id
        )
    body = sql[:-1].rstrip() if sql.endswith(";") else sql
    if ";" in body:
        raise QueryTemplateError(
            "SQL 模板必须是单条语句（禁止分号串接）", query_id=spec.query_id
        )
    # SELECT/WITH 前缀（CTE 属只读查询族；WITH ... INSERT/UPDATE/DELETE
    # 的写形态会被下方黑名单词边界捕获，这里只放行查询首词）。
    if not re.match(r"^\s*(?:SELECT|WITH)\b", body, re.IGNORECASE):
        raise QueryTemplateError(
            "SQL 模板只允许 SELECT/WITH 只读查询", query_id=spec.query_id
        )
    if _FORBIDDEN_SQL_RE.search(body):
        raise QueryTemplateError(
            "SQL 模板命中黑名单关键字（写/DDL/ATTACH/PRAGMA 等）",
            query_id=spec.query_id,
        )
    declared = dict(spec.params or {})
    for name in _NAMED_PARAM_RE.findall(body):
        if name not in declared:
            raise QueryTemplateError(
                f"SQL 模板命名占位 :{name} 未在参数 schema 声明",
                query_id=spec.query_id,
            )
    for name in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", body):
        if spec.order_enum is None or name not in spec.order_enum:
            raise QueryTemplateError(
                f"占位符 {{{name}}} 未登记为排序枚举", query_id=spec.query_id
            )
    for name in spec.required_params:
        if name not in declared:
            raise QueryTemplateError(
                f"必填参数 {name} 未在参数 schema 声明",
                query_id=spec.query_id,
            )


@dataclass(frozen=True)
class BrokerResult:
    query_id: str
    db: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    row_count: int
    truncated: bool
    elapsed_ms: float


class DatabaseBroker:
    """只执行注册白名单内参数化只读查询的数据库代理。"""

    def __init__(
        self,
        registry: Mapping[str, QuerySpec],
        database_paths: Mapping[str, str | pathlib.Path],
    ) -> None:
        self._database_paths = {
            str(key): str(value) for key, value in dict(database_paths).items()
        }
        self._specs: dict[str, QuerySpec] = {}
        for query_id, spec in dict(registry).items():
            if spec.query_id != query_id:
                raise QueryTemplateError(
                    f"registry 键 {query_id!r} 与 spec.query_id 不一致",
                    query_id=str(query_id),
                )
            if spec.db not in self._database_paths:
                raise QueryTemplateError(
                    f"query {query_id} 绑定了未注册的库 {spec.db!r}",
                    query_id=str(query_id),
                )
            for name, kind in dict(spec.params or {}).items():
                if kind not in _PARAM_TYPES:
                    raise QueryTemplateError(
                        f"query {query_id} 参数 {name} 类型 {kind!r} 不支持",
                        query_id=str(query_id),
                    )
            for name, columns in (spec.order_enum or {}).items():
                if name not in (spec.params or {}):
                    raise QueryTemplateError(
                        f"query {query_id} 排序参数 {name} 未在 params 声明",
                        query_id=str(query_id),
                    )
                if not columns:
                    raise QueryTemplateError(
                        f"query {query_id} 排序枚举 {name} 为空",
                        query_id=str(query_id),
                    )
            validate_template(spec)
            self._specs[query_id] = spec

    def query_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def spec(self, query_id: str) -> QuerySpec:
        spec = self._specs.get(query_id)
        if spec is None:
            raise UnknownQueryError(
                f"query_id {query_id!r} 未注册（白名单外一律拒绝）",
                query_id=query_id,
            )
        return spec

    def execute(
        self,
        query_id: str,
        params: Mapping[str, Any] | None = None,
    ) -> BrokerResult:
        """执行白名单查询；任何形态的越权/注入样本都在此处被拒绝。"""
        spec = self.spec(query_id)
        supplied = dict(params or {})
        declared = dict(spec.params or {})
        unknown = sorted(set(supplied) - set(declared))
        if unknown:
            raise QueryParamError(
                f"未知参数 {unknown}（schema 外参数一律拒绝）",
                query_id=query_id,
            )
        missing = sorted(name for name in spec.required_params if name not in supplied)
        if missing:
            raise QueryParamError(f"缺少必填参数 {missing}", query_id=query_id)
        bindings: dict[str, Any] = {}
        order_values: dict[str, str] = {}
        for name, kind in declared.items():
            if name not in supplied:
                continue
            value = supplied[name]
            if name in (spec.order_enum or {}):
                if not isinstance(value, str):
                    raise QuerySortError(
                        f"排序参数 {name} 必须是列名字符串", query_id=query_id
                    )
                allowed = (spec.order_enum or {})[name]
                if value not in allowed or not _IDENTIFIER_RE.match(value):
                    raise QuerySortError(
                        f"排序列 {value!r} 不在注册枚举内", query_id=query_id
                    )
                order_values[name] = value
                continue
            if isinstance(value, bool) or not isinstance(value, _PARAM_TYPES[kind]):
                raise QueryParamError(
                    f"参数 {name} 类型必须是 {kind}，收到 {type(value).__name__}",
                    query_id=query_id,
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise QueryParamError(
                    f"参数 {name} 拒绝 NaN/Infinity", query_id=query_id
                )
            bindings[name] = value
        sql = spec.sql
        for name, column in order_values.items():
            sql = sql.replace("{" + name + "}", column)
        # 只绑定最终 SQL 里实际出现的命名占位（模板漏用声明参数不算错）。
        used = _NAMED_PARAM_RE.findall(sql)
        final_bindings = {name: bindings[name] for name in used}
        limit = max(0, int(spec.max_rows))
        started = time.monotonic()
        connection = self._open_readonly(spec.db)
        try:
            connection.execute(
                f"PRAGMA busy_timeout={int(spec.timeout_seconds * 1000)}"
            )
            deadline = started + max(0.05, float(spec.timeout_seconds))

            def _check_progress() -> int:
                # 返回非零 → sqlite3 中断当前语句（wall-clock 超时实现）。
                return 1 if time.monotonic() > deadline else 0

            connection.set_progress_handler(_check_progress, 200)
            cursor = connection.execute(sql, final_bindings)
            columns = tuple(str(item[0]) for item in cursor.description or ())
            rows_raw = cursor.fetchmany(limit + 1)
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "interrupt" in message:
                raise QueryTimeoutError(
                    f"查询超过 {spec.timeout_seconds}s 执行上限，已中止",
                    query_id=query_id,
                ) from exc
            raise BrokerQueryError(
                f"查询执行失败: {exc}", query_id=query_id
            ) from exc
        finally:
            connection.close()
        truncated = len(rows_raw) > limit
        rows_raw = rows_raw[:limit]
        rows = tuple(
            {column: row[index] for index, column in enumerate(columns)}
            for row in rows_raw
        )
        return BrokerResult(
            query_id=query_id,
            db=spec.db,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            elapsed_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _open_readonly(self, db_key: str) -> sqlite3.Connection:
        path = self._database_paths[db_key]
        if not path or path == ":memory:":
            connection = sqlite3.connect(":memory:")
        else:
            uri = f"file:{pathlib.Path(path).as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = None
        return connection


def build_default_registry(
    max_rows: int = DEFAULT_ROW_LIMIT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, QuerySpec]:
    """五个预注册查询：全部指向 docs/db-owners.md 在册现有库。

    - queue.depth            发送队列按状态深度（sender/queue.py send_requests）
    - affinity.distribution  好感度分档分布（character/affinity.py user_affinity）
    - ledger.daily           账本按日聚合（llm/ledger.py llm_usage_daily）
    - audit.recent           审计最近 N 条（audit/logger.py audit_records；
                             order_by 走注册枚举——「排序只能枚举」的示范位）
    - subscriptions.status   订阅按平台状态（sources/subscription_store_v2.py
                             subscription_targets）
    """

    def _spec(
        query_id: str, sql: str, db: str, description: str, **kw: Any
    ) -> QuerySpec:
        return QuerySpec(
            query_id=query_id,
            sql=sql,
            db=db,
            description=description,
            max_rows=kw.pop("max_rows", max_rows),
            timeout_seconds=kw.pop("timeout_seconds", timeout_seconds),
            **kw,
        )

    return {
        "queue.depth": _spec(
            "queue.depth",
            (
                "SELECT state, COUNT(*) AS requests, "
                "COALESCE(SUM(retry_count), 0) AS total_retries "
                "FROM send_requests GROUP BY state ORDER BY state"
            ),
            "send_queue",
            "发送队列按状态深度（requests/total_retries）",
        ),
        "affinity.distribution": _spec(
            "affinity.distribution",
            (
                "SELECT CASE "
                "WHEN affinity >= 60 THEN 'devoted' "
                "WHEN affinity >= 25 THEN 'close' "
                "WHEN affinity >= 10 THEN 'friendly' "
                "WHEN affinity >= 0 THEN 'neutral' "
                "WHEN affinity >= -30 THEN 'wary' "
                "ELSE 'hostile' END AS bucket, "
                "COUNT(*) AS senders, "
                "COALESCE(AVG(affinity), 0.0) AS avg_affinity "
                "FROM user_affinity GROUP BY bucket ORDER BY bucket"
            ),
            "affinity",
            "好感度分档分布（bucket/senders/avg_affinity）",
        ),
        "ledger.daily": _spec(
            "ledger.daily",
            (
                "SELECT day, SUM(calls) AS calls, "
                "SUM(failed_calls) AS failed_calls, "
                "SUM(total_tokens) AS total_tokens, "
                "SUM(total_cost_milli) AS total_cost_milli, "
                "SUM(unpriced_calls) AS unpriced_calls "
                "FROM llm_usage_daily WHERE day >= :min_day "
                "GROUP BY day ORDER BY day DESC"
            ),
            "ledger",
            "账本按日聚合（day>=min_day，费用毫立单位）",
            params={"min_day": "str"},
            required_params=frozenset({"min_day"}),
        ),
        "audit.recent": _spec(
            "audit.recent",
            (
                "SELECT audit_id, request_id, session_id, capability_id, "
                "stage, event, severity, created_at "
                "FROM audit_records ORDER BY {order_by} DESC LIMIT :limit"
            ),
            "audit",
            "审计最近 N 条（order_by 只能取注册枚举列）",
            params={"limit": "int", "order_by": "str"},
            order_enum={
                "order_by": frozenset(
                    {"created_at", "severity", "capability_id"}
                ),
            },
        ),
        "subscriptions.status": _spec(
            "subscriptions.status",
            (
                "SELECT platform, COUNT(*) AS targets, "
                "COALESCE(SUM(enabled), 0) AS enabled_targets, "
                "COALESCE(SUM(failure_count), 0) AS failures, "
                "COALESCE(SUM(CASE WHEN health_state <> 'healthy' "
                "THEN 1 ELSE 0 END), 0) AS unhealthy "
                "FROM subscription_targets GROUP BY platform ORDER BY platform"
            ),
            "subscriptions",
            "订阅按平台状态（targets/enabled/failures/unhealthy）",
        ),
    }


def build_database_broker(
    config: object,
    *,
    database_paths: Mapping[str, str | pathlib.Path] | None = None,
) -> DatabaseBroker:
    """从 config 装配：db 路径复用既有各库 config 键（runtime_paths 已重映射）。

    不触碰任何库文件（懒打开，执行期才连接）；生产接线由装配席位裁决。
    """
    if database_paths is None:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.ledger import (
            resolve_default_db_path as _ledger_db,
        )

        database_paths = {
            "send_queue": str(
                getattr(config, "bot_send_queue_db_path", "")
                or "data/wuwa_send_queue.sqlite3"
            ),
            "affinity": str(
                getattr(config, "bot_affinity_db_path", "")
                or "data/user_affinity.sqlite3"
            ),
            "ledger": _ledger_db(),
            "audit": str(getattr(config, "bot_audit_db_path", "") or ""),
            "subscriptions": str(
                getattr(config, "bot_subscribe_db_path", "")
                or "data/subscriptions.sqlite3"
            ),
        }
    return DatabaseBroker(
        build_default_registry(),
        database_paths,  # type: ignore[arg-type]
    )
