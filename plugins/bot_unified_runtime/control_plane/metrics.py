"""只读账本统计适配器；不初始化 ledger、不解析 attempts、不触碰运行配置。

公开结果：{status: ok, source: llm_call_records, data: ...}；失败仅返回
{status: source_unavailable|invalid_request, reason: 固定代码, data: None}。
overview.data 是总计；其余 data 含总计及 models/providers、sessions 或 items。
limit（默认 100，整数 1..100）仅限制各排名/桶的输出，不截断总计或组内样本。

每项 token 的 value 是已知记录之和（无已知记录为 None），并携带
known_rows/unknown_rows/quality（complete/partial/unknown）。一行仅代表一次
已记账 generate 调用，不代表网络 attempt；attempt_total/failover_calls 恒为未知。
模型按 actual_model 分组，不用渠道 model_id 冒充真实模型；空标识返回 None。
providers 仅按旧 provider_id 字段分组，不代表已验证的外部供应商。schema1 的
model_router 将 registry 路由 ID（spec.model_id/winner_id）写入该字段；所有总计
及分组均标记 provider_identity_quality=legacy_unverified，来源固定 code 为
schema1_provider_id_from_registry_route_id，不从路由名或 actual_model 推断 vendor。
会话使用进程内随机密钥 HMAC，不输出原文；跨实例稳定、进程重启后不可关联。
趋势使用 started_at 的显式时区转 UTC；无时区/无效时间记 unknown_timestamp_calls，
并保留 bucket_start=None 的未知桶（可能被 limit 截去）。时桶按时间倒序。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

__all__ = ["LedgerMetricsService"]

_BUSY_TIMEOUT_SECONDS = 0.2
_QUERY_TIMEOUT_SECONDS = 1.0
_PROGRESS_STEPS = 1000
_MAX_PROGRESS_CALLBACKS = 20_000
_HASH_KEY = os.urandom(32)
_SAFE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_TOKEN_COLUMNS = {
    "prompt": "prompt_tokens",
    "completion": "completion_tokens",
    "cache_read": "cache_read_tokens",
    "cache_creation": "cache_creation_tokens",
}
_REQUIRED_COLUMNS = frozenset(_TOKEN_COLUMNS.values()) | {
    "status",
    "started_at",
    "actual_model",
    "provider_id",
    "session_id",
}
# SQL 仅由本文件常量组成；调用参数绝不进入 SQL/列名。limit 使用绑定参数。
_AGGREGATES = """
COUNT(*) AS recorded_calls,
SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successful_calls,
SUM(CASE WHEN status IN ('deadline', 'provider_failed') THEN 1 ELSE 0 END) AS failed_calls,
COUNT(*) - COUNT(ledger_utc_day(started_at)) AS unknown_timestamp_calls
""" + "".join(
    f", SUM(CASE WHEN typeof({column}) = 'integer' AND {column} >= 0 "
    f"THEN {column} END) AS {name}_value, "
    f"COUNT(CASE WHEN typeof({column}) = 'integer' AND {column} >= 0 "
    f"THEN {column} END) AS {name}_known"
    for name, column in _TOKEN_COLUMNS.items()
)
_OVERVIEW_SQL = "SELECT " + _AGGREGATES + " FROM llm_call_records"
_GROUP_EXPRESSIONS = {
    "models": "NULLIF(actual_model, '')",
    "providers": "NULLIF(provider_id, '')",
    "sessions": "NULLIF(session_id, '')",
    "hour": "ledger_utc_hour(started_at)",
    "day": "ledger_utc_day(started_at)",
}
_GROUP_SQL = {
    name: f"SELECT {expression} AS group_key, {_AGGREGATES} "
    "FROM llm_call_records GROUP BY group_key ORDER BY "
    + (
        "group_key DESC"
        if name in ("hour", "day")
        else "recorded_calls DESC, group_key ASC"
    )
    + " LIMIT ?"
    for name, expression in _GROUP_EXPRESSIONS.items()
}

# ---- WebUI stats/tokens：模型族×时间窗（closed-set 常量，仅绑定参数） ----
_WINDOW_SECONDS = {"24h": 86_400, "7d": 7 * 86_400, "30d": 30 * 86_400}
# 只取已知非负整数 token（与 _AGGREGATES 同口径）；value 全未知时保持 None。
_FAMILY_TOKEN_SQL = ", ".join(
    f"SUM(CASE WHEN typeof({column}) = 'integer' AND {column} >= 0 "
    f"THEN {column} END) AS {name}_value, "
    f"COUNT(CASE WHEN typeof({column}) = 'integer' AND {column} >= 0 "
    f"THEN {column} END) AS {name}_known"
    for name, column in _TOKEN_COLUMNS.items()
)
# P3-9 同款取舍：completed_at 由同进程单一时区偏移写入，ISO 文本字典序即时序，
# 走 idx_llm_call_completed；参数上下界由调用侧绑定，绝不拼接。
_TOKEN_FAMILY_GROUPED_SQL = (
    "SELECT NULLIF(actual_model, '') AS model_key, COUNT(*) AS calls, "
    + _FAMILY_TOKEN_SQL
    + " FROM llm_call_records WHERE completed_at >= ? AND completed_at < ?"
    " GROUP BY model_key"
)
_TOKEN_FAMILY_TOTAL_SQL = (
    "SELECT COUNT(*) AS calls, "
    + _FAMILY_TOKEN_SQL
    + " FROM llm_call_records WHERE completed_at >= ? AND completed_at < ?"
)
_TOKEN_FAMILY_REQUIRED_COLUMNS = frozenset(_TOKEN_COLUMNS.values()) | {
    "status",
    "completed_at",
    "actual_model",
}


def _utc_bucket(value: object, *, hour: bool) -> str | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            return None
        stamp = stamp.astimezone(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        if not hour:
            stamp = stamp.replace(hour=0)
        return stamp.isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def _stored_offset_zone(connection: Any) -> tzinfo | None:
    """取账本 completed_at 实际使用的 UTC 偏移，供窗口边界与写入口径对齐。

    写入侧按本地时区渲染 ISO 文本（model_router 的 datetime.now(self._zone)），而窗口过滤
    走 ISO 文本字典序比较。边界若固定按 UTC 渲染，两侧偏移不同会把整个窗平移
    |本地偏移| 小时——+08:00 部署下「近 24 小时」丢掉最近 8 小时、反而纳入 26~31 小时前的
    旧行（2026-09-19 F13 首报、F21 敌对复算证真）。单一偏移是账本既有前提，见
    _TOKEN_FAMILY_GROUPED_SQL 上方注释。取不到可用时间戳时返回 None，调用侧回落 UTC。
    """
    row = connection.execute(
        "SELECT completed_at FROM llm_call_records ORDER BY completed_at DESC LIMIT 1"
    ).fetchone()
    value = row[0] if row is not None else None
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.tzinfo


def _identifier(value: object, kind: str) -> str | None:
    if value is None or value == "":
        return None
    if (
        kind != "session"
        and isinstance(value, str)
        and _SAFE_LABEL.fullmatch(value)
        and not value.lower().startswith(("sk-", "bot_"))
    ):
        return value
    payload = value if isinstance(value, bytes) else str(value).encode("utf-8")
    digest = hmac.new(_HASH_KEY, kind.encode("ascii") + b"\0" + payload, hashlib.sha256)
    return f"{kind}_{digest.hexdigest()}"


def _aggregate(row: sqlite3.Row) -> dict[str, Any]:
    count = int(row["recorded_calls"])
    successful = int(row["successful_calls"] or 0)
    failed = int(row["failed_calls"] or 0)
    tokens = {}
    for name in _TOKEN_COLUMNS:
        known = int(row[f"{name}_known"])
        quality = "unknown"
        if known:
            quality = "complete" if known == count else "partial"
        tokens[name] = {
            "value": row[f"{name}_value"],
            "known_rows": known,
            "unknown_rows": count - known,
            "quality": quality,
        }
    return {
        "provider_identity_quality": "legacy_unverified",
        "provider_identity_source_code": "schema1_provider_id_from_registry_route_id",
        "recorded_calls": count,
        "successful_calls": successful,
        "failed_calls": failed,
        "unknown_status_calls": count - successful - failed,
        "unknown_timestamp_calls": int(row["unknown_timestamp_calls"]),
        "tokens": tokens,
        "attempt_total": {
            "value": None,
            "quality": "unknown",
            "reason": "not_recorded_reliably",
        },
        "failover_calls": {
            "value": None,
            "quality": "unknown",
            "reason": "not_recorded_reliably",
        },
    }


def _failure(status: str, reason: str) -> dict[str, Any]:
    return {"status": status, "reason": reason, "data": None}


# WebUI stats/tokens 对外命名：输入/输出/缓存读/缓存建（账本列名 → 协议名）。
_WEBUI_TOKEN_NAMES = {
    "prompt": "input",
    "completion": "output",
    "cache_read": "cache_read",
    "cache_creation": "cache_creation",
}


def _token_block(calls: int, known: int, total: int) -> dict[str, Any]:
    if known == 0:
        quality = "unknown"
    elif known == calls:
        quality = "complete"
    else:
        quality = "partial"
    return {
        "value": total if known else None,
        "known_rows": known,
        "unknown_rows": calls - known,
        "quality": quality,
    }


def _family_row(row: sqlite3.Row, *, family: str | None) -> dict[str, Any]:
    calls = int(row["calls"])
    tokens = {
        target: _token_block(
            calls, int(row[f"{source}_known"] or 0), int(row[f"{source}_value"] or 0)
        )
        for source, target in _WEBUI_TOKEN_NAMES.items()
    }
    return {"family": family, "calls": calls, "tokens": tokens}


def _merge_family_row(bucket: dict[str, Any], row: sqlite3.Row) -> None:
    calls = bucket["calls"] + int(row["calls"])
    bucket["calls"] = calls
    for source, target in _WEBUI_TOKEN_NAMES.items():
        block = bucket["tokens"][target]
        bucket["tokens"][target] = _token_block(
            calls,
            block["known_rows"] + int(row[f"{source}_known"] or 0),
            (block["value"] or 0) + int(row[f"{source}_value"] or 0),
        )


class LedgerMetricsService:
    """每次调用独立只读连接和读事务；预算覆盖 schema、总计与所有排名查询。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = db_path

    def overview(self, limit: int = 100) -> dict[str, Any]:
        return self._read("overview", limit)

    def models(self, limit: int = 100) -> dict[str, Any]:
        """按调用数返回 actual_model 排名与未验证的旧 provider_id 路由分组。"""
        return self._read("models", limit)

    def sessions(self, limit: int = 100) -> dict[str, Any]:
        return self._read("sessions", limit)

    def trends(self, bucket: str = "hour", limit: int = 100) -> dict[str, Any]:
        if not isinstance(bucket, str) or bucket not in ("hour", "day"):
            return _failure("invalid_request", "invalid_bucket")
        return self._read(bucket, limit)

    def token_families(self, window: str = "24h", limit: int = 100) -> dict[str, Any]:
        """时间窗内按模型族聚合四项 token（输入/缓存读/缓存建/输出）。

        模型族归一复用 ``pricing.model_family_key``（casefold + 剥推理档后缀，
        Gemini-3.8-Flash-HIGH 与 gemini-3.8-flash 同族）。窗口过滤走
        completed_at 文本界（P3-9 同一取舍，见 _TOKEN_FAMILY_GROUPED_SQL 注）。
        """
        if not isinstance(window, str) or window not in _WINDOW_SECONDS:
            return _failure("invalid_request", "invalid_window")
        if type(limit) is not int or not 1 <= limit <= 100:
            return _failure("invalid_request", "invalid_limit")
        try:
            path = Path(self._db_path).resolve()
            if not path.is_file():
                return _failure("source_unavailable", "missing_source")
            with closing(
                sqlite3.connect(
                    path.as_uri() + "?mode=ro", uri=True, timeout=_BUSY_TIMEOUT_SECONDS
                )
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only = ON")
                connection.execute("PRAGMA trusted_schema = OFF")
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'llm_call_records'"
                    " AND type = 'table'"
                ).fetchone()
                if table is None:
                    return _failure("source_unavailable", "missing_table")
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(llm_call_records)")
                }
                if not _TOKEN_FAMILY_REQUIRED_COLUMNS <= columns:
                    return _failure("source_unavailable", "incomplete_schema")
                connection.execute("BEGIN")
                now = datetime.now(timezone.utc)
                span = timedelta(seconds=_WINDOW_SECONDS[window])
                # 边界与数据同偏移渲染，文本序才等价于时序（见 _stored_offset_zone）。
                zone = _stored_offset_zone(connection) or timezone.utc
                bounds = (
                    (now - span).astimezone(zone).isoformat(timespec="milliseconds"),
                    now.astimezone(zone).isoformat(timespec="milliseconds"),
                )
                totals = _family_row(connection.execute(
                    _TOKEN_FAMILY_TOTAL_SQL, bounds
                ).fetchone(), family=None)
                merged: dict[str, dict[str, Any]] = {}
                for row in connection.execute(_TOKEN_FAMILY_GROUPED_SQL, bounds):
                    key = row["model_key"]
                    if key is None:
                        continue  # 无模型名的行只入总量，不冒充一个族。
                    from ..domains.chat_reply.llm_engine.pricing import model_family_key

                    family = model_family_key(key) or key
                    bucket_row = merged.get(family)
                    if bucket_row is None:
                        bucket_row = merged[family] = _family_row(row, family=family)
                    else:
                        _merge_family_row(bucket_row, row)
                items = sorted(
                    merged.values(),
                    key=lambda item: (-item["calls"], str(item["family"])),
                )[:limit]
                return {
                    "status": "ok",
                    "source": "llm_call_records",
                    "data": {"window": window, "totals": totals, "families": items},
                }
        except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
            return _failure("source_unavailable", "read_failed")

    def _read(self, view: str, limit: int) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            return _failure("invalid_request", "invalid_limit")
        deadline = time.monotonic() + _QUERY_TIMEOUT_SECONDS
        callbacks = 0
        budget_exceeded = False

        def progress() -> int:
            nonlocal callbacks, budget_exceeded
            callbacks += 1
            budget_exceeded = (
                time.monotonic() >= deadline or callbacks >= _MAX_PROGRESS_CALLBACKS
            )
            return int(budget_exceeded)

        try:
            path = Path(self._db_path).resolve()
            if not path.is_file():
                return _failure("source_unavailable", "missing_source")
            # 不使用 immutable：正在写入的 WAL 账本必须保持 SQLite 正常快照语义。
            with closing(
                sqlite3.connect(
                    path.as_uri() + "?mode=ro", uri=True, timeout=_BUSY_TIMEOUT_SECONDS
                )
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only = ON")
                connection.execute("PRAGMA trusted_schema = OFF")
                connection.set_progress_handler(progress, _PROGRESS_STEPS)
                connection.create_function(
                    "ledger_utc_hour",
                    1,
                    lambda value: _utc_bucket(value, hour=True),
                    deterministic=True,
                )
                connection.create_function(
                    "ledger_utc_day",
                    1,
                    lambda value: _utc_bucket(value, hour=False),
                    deterministic=True,
                )
                connection.execute("BEGIN")
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'llm_call_records' AND type = 'table'"
                ).fetchone()
                if table is None:
                    return _failure("source_unavailable", "missing_table")
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(llm_call_records)")
                }
                if not _REQUIRED_COLUMNS <= columns:
                    return _failure("source_unavailable", "incomplete_schema")
                data = _aggregate(connection.execute(_OVERVIEW_SQL).fetchone())
                if view == "models":
                    data["models"] = self._groups(connection, "models", "model", limit)
                    data["providers"] = self._groups(
                        connection, "providers", "provider", limit
                    )
                elif view == "sessions":
                    data["sessions"] = self._groups(
                        connection, "sessions", "session", limit
                    )
                elif view in ("hour", "day"):
                    data.update(
                        bucket=view,
                        timezone="UTC",
                        items=self._groups(connection, view, "bucket_start", limit),
                    )
                # 小查询可能未执行满 progress 步长；返回前仍检查整次操作的墙钟预算。
                if time.monotonic() >= deadline:
                    return _failure("source_unavailable", "query_budget_exceeded")
                return {"status": "ok", "source": "llm_call_records", "data": data}
        except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
            # 不返回底层异常、SQL、绝对路径或任何账本原文；不记录包含它们的日志。
            reason = "query_budget_exceeded" if budget_exceeded else "read_failed"
            return _failure("source_unavailable", reason)

    @staticmethod
    def _groups(
        connection: sqlite3.Connection, name: str, label: str, limit: int
    ) -> list[dict[str, Any]]:
        items = []
        for row in connection.execute(_GROUP_SQL[name], (limit,)):
            key = row["group_key"]
            if label != "bucket_start":
                key = _identifier(key, label)
            items.append({label: key, **_aggregate(row)})
        return items
