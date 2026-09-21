"""WebUI Phase A 只读统计服务（stats/calls、stats/latency、affinity/board）。

数据源与口径（全部只读，URI mode=ro + PRAGMA query_only，绝不写生产库）：

- ``stats/calls``  ← 审计 SQLite（``audit_records`` 表，``bot_audit_db_path``；
  默认空=进程内内存实现，此处如实 ``audit_source_not_configured``）。
  总调用数/按会话 TopN/按用户 TopN/按能力 TopN/趋势桶（hour|day）。
  会话标签按账本 metrics 先例做进程内 HMAC 假名（不回显原始 session id）；
  用户不落库——按 OneBot v11 ``get_session_id()`` 稳定约定
  （``private_<uid>`` / ``group_<gid>_<uid>`` / 裸 ``<uid>``）显式派生，
  派生不出的系统行计入 ``unattributed_calls``，绝不造一个用户。
- ``stats/latency`` ← channel_health store（单例经装配注入）的当前值；
  历史曲线无存储 → ``history`` 为显式不可用字段（不造历史点）。
- ``affinity/board`` ← ``user_affinity`` SQLite（``bot_affinity_db_path``）。
  榜单=昵称/分数/档位，显数值（2026-09-15 用户裁定 WebUI 面板直显；
  聊天内侧定性口径不变，两处不同源不冲突）。

失败面沿用账本 metrics 先例：``{status, reason, data: None}``，固定 reason
代码，绝不回显路径/SQL/原文；无效参数先于任何 IO 校验。
"""

from __future__ import annotations

import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .metrics import _identifier, _utc_bucket

__all__ = [
    "AffinityBoardService",
    "AuditCallStatsService",
    "WebUIStatsBundle",
    "build_default_stats_service",
    "latency_view",
    "resolve_webui_index",
]

_BUSY_TIMEOUT_SECONDS = 0.2
_QUERY_TIMEOUT_SECONDS = 1.0
_WINDOW_SECONDS = {"24h": 86_400, "7d": 7 * 86_400, "30d": 30 * 86_400}
_BUCKETS = ("hour", "day")
_DIGITS = re.compile(r"[0-9]+\Z")
_USER_ATTRIBUTION_CODE = "derived_from_session_id_onebot_convention"

_AUDIT_REQUIRED_COLUMNS = frozenset({"created_at", "session_id", "capability_id"})
_AFFINITY_REQUIRED_COLUMNS = frozenset(
    {"sender_id", "affinity", "nickname", "interaction_count", "updated_at"}
)

# SQL 仅由本文件常量组成；排序方向来自封闭枚举的两个独立常量（不拼片）。
_BOARD_SQL = {
    "desc": (
        "SELECT sender_id, affinity, nickname, interaction_count, updated_at"
        " FROM user_affinity ORDER BY affinity DESC, sender_id ASC LIMIT ?"
    ),
    "asc": (
        "SELECT sender_id, affinity, nickname, interaction_count, updated_at"
        " FROM user_affinity ORDER BY affinity ASC, sender_id ASC LIMIT ?"
    ),
}
_BOARD_COUNT_SQL = "SELECT COUNT(*) FROM user_affinity"


def _failure(status: str, reason: str) -> dict[str, Any]:
    return {"status": status, "reason": reason, "data": None}


def _parse_utc(value: object) -> datetime | None:
    """ISO 文本 → aware UTC；无时区/畸形 = None（账本同款口径：未知，不猜）。"""
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def _user_from_session(value: object) -> str | None:
    """OneBot v11 session 约定 → 用户 id；约定外返回 None（不计入用户榜）。"""
    text = str(value or "")
    if _DIGITS.fullmatch(text):
        return text
    if text.startswith("private_"):
        rest = text[len("private_") :]
        return rest if _DIGITS.fullmatch(rest) else None
    if text.startswith("group_"):
        parts = text.split("_")
        if len(parts) == 3 and _DIGITS.fullmatch(parts[1]) and _DIGITS.fullmatch(parts[2]):
            return parts[2]
    return None


def _top(counts: dict[Any, int], limit: int, *, label: str) -> list[dict[str, Any]]:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
    return [{label: key, "calls": count} for key, count in ranked[:limit]]


class AuditCallStatsService:
    """审计库只读聚合（``audit_records``；默认 1000 行 prune 上限，全量可扫）。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = db_path

    def calls(
        self,
        window: str = "24h",
        bucket: str = "hour",
        limit: int = 10,
    ) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            return _failure("invalid_request", "invalid_limit")
        if not isinstance(window, str) or window not in _WINDOW_SECONDS:
            return _failure("invalid_request", "invalid_window")
        if bucket not in _BUCKETS:
            return _failure("invalid_request", "invalid_bucket")
        if not str(self._db_path).strip():
            return _failure("source_unavailable", "audit_source_not_configured")
        deadline = time.monotonic() + _QUERY_TIMEOUT_SECONDS
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
                connection.execute("BEGIN")
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'audit_records'"
                    " AND type = 'table'"
                ).fetchone()
                if table is None:
                    return _failure("source_unavailable", "missing_table")
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(audit_records)")
                }
                if not _AUDIT_REQUIRED_COLUMNS <= columns:
                    return _failure("source_unavailable", "incomplete_schema")
                cutoff = datetime.now(timezone.utc) - timedelta(
                    seconds=_WINDOW_SECONDS[window]
                )
                total = 0
                unknown_timestamp = 0
                unattributed = 0
                sessions: dict[str | None, int] = {}
                users: dict[str, int] = {}
                capabilities: dict[str | None, int] = {}
                trend: dict[str, int] = {}
                last_stamp: datetime | None = None
                rows = connection.execute(
                    "SELECT created_at, session_id, capability_id FROM audit_records"
                ).fetchall()
                for row in rows:
                    stamp = _parse_utc(row["created_at"])
                    if stamp is None:
                        unknown_timestamp += 1
                        continue
                    if stamp < cutoff:
                        continue
                    total += 1
                    if last_stamp is None or stamp > last_stamp:
                        last_stamp = stamp
                    session = str(row["session_id"] or "")
                    session_label = _identifier(session, "session") if session else None
                    sessions[session_label] = sessions.get(session_label, 0) + 1
                    user = _user_from_session(row["session_id"])
                    if user is None:
                        unattributed += 1
                    else:
                        users[user] = users.get(user, 0) + 1
                    capability = str(row["capability_id"] or "")
                    cap_label = _identifier(capability, "capability") if capability else None
                    capabilities[cap_label] = capabilities.get(cap_label, 0) + 1
                    bucket_key = _utc_bucket(
                        row["created_at"], hour=bucket == "hour"
                    )
                    if bucket_key is not None:
                        trend[bucket_key] = trend.get(bucket_key, 0) + 1
                if time.monotonic() >= deadline:
                    return _failure("source_unavailable", "query_budget_exceeded")
                return {
                    "status": "ok",
                    "source": "audit_records",
                    "data": {
                        "window": window,
                        "total_calls": total,
                        "unknown_timestamp_calls": unknown_timestamp,
                        "unattributed_calls": unattributed,
                        "user_attribution": _USER_ATTRIBUTION_CODE,
                        # 窗口内可归属用户去重数（unattributed 不计入，已单列）。
                        "active_users": len(users),
                        # 窗口内最新审计时间（归一 UTC ISO）；窗口内无记录=null。
                        "last_message_at": (
                            last_stamp.isoformat() if last_stamp is not None else None
                        ),
                        "by_session": _top(sessions, limit, label="session"),
                        "by_user": _top(users, limit, label="user"),
                        "by_capability": _top(capabilities, limit, label="capability"),
                        "trend": {
                            "bucket": bucket,
                            "timezone": "UTC",
                            # 时桶按时间倒序（账本 trends 同款口径），不受 TopN 排序影响。
                            "items": [
                                {"bucket_start": key, "calls": trend[key]}
                                for key in sorted(trend, reverse=True)[:limit]
                            ],
                        },
                    },
                }
        except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
            return _failure("source_unavailable", "read_failed")


class AffinityBoardService:
    """``user_affinity`` 只读榜单（显数值；内部值 -1..1 → 展示分 ×100）。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = db_path

    def board(self, limit: int = 50, order: str = "desc") -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 200:
            return _failure("invalid_request", "invalid_limit")
        if order not in _BOARD_SQL:
            return _failure("invalid_request", "invalid_order")
        if not str(self._db_path).strip():
            return _failure("source_unavailable", "affinity_source_not_configured")
        deadline = time.monotonic() + _QUERY_TIMEOUT_SECONDS
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
                connection.execute("BEGIN")
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'user_affinity'"
                    " AND type = 'table'"
                ).fetchone()
                if table is None:
                    return _failure("source_unavailable", "missing_table")
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(user_affinity)")
                }
                if not _AFFINITY_REQUIRED_COLUMNS <= columns:
                    return _failure("source_unavailable", "incomplete_schema")
                total = int(connection.execute(_BOARD_COUNT_SQL).fetchone()[0])
                from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
                    tier_for_affinity,
                    tier_name_for_affinity,
                )

                items: list[dict[str, Any]] = []
                for row in connection.execute(_BOARD_SQL[order], (limit,)):
                    try:
                        affinity = float(row["affinity"])
                    except (TypeError, ValueError):
                        affinity = 0.1  # 畸形值回退基准，不炸整个榜单。
                    display = max(-100.0, min(100.0, affinity * 100.0))
                    items.append(
                        {
                            "sender_id": str(row["sender_id"]),
                            "nickname": str(row["nickname"] or ""),
                            "affinity": affinity,
                            "score": round(display, 1),
                            "tier": tier_for_affinity(affinity),
                            "tier_name": tier_name_for_affinity(affinity),
                            "interaction_count": int(row["interaction_count"] or 0),
                            "updated_at": str(row["updated_at"] or ""),
                        }
                    )
                if time.monotonic() >= deadline:
                    return _failure("source_unavailable", "query_budget_exceeded")
                return {
                    "status": "ok",
                    "source": "user_affinity",
                    "data": {"order": order, "total": total, "items": items},
                }
        except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
            return _failure("source_unavailable", "read_failed")


def latency_view(store: Any | None) -> dict[str, Any]:
    """渠道健康当前值投影视；历史曲线无存储 → 显式不可用字段（不造数）。"""
    if store is None:
        return _failure("source_unavailable", "not_connected")
    try:
        rows = store.report()
    except Exception:  # noqa: BLE001 - 观测面故障不拖垮控制面（fail-open 先例）。
        return _failure("source_unavailable", "read_failed")
    from .audit import redact_error_for_dto

    items: list[dict[str, Any]] = []
    for row in rows:
        get = row.get if isinstance(row, dict) else (lambda key, _r=row: getattr(_r, key, None))
        latency = get("latency_ms")
        ema = get("ema_ms")
        items.append(
            {
                "channel": str(get("model_id") or ""),
                "state": str(get("state") or ""),
                "consecutive_fails": int(get("consecutive_fails") or 0),
                "latency_ms": int(latency) if latency is not None else None,
                "ema_ms": int(ema) if ema is not None else None,
                "samples": int(get("samples") or 0),
                "last_ok_at": str(get("last_ok_at") or ""),
                "last_error": redact_error_for_dto(get("last_error"), 200),
            }
        )
    items.sort(key=lambda item: item["channel"])
    return {
        "status": "ok",
        "source": "channel_health",
        "data": {
            "items": items,
            "history": {"status": "unavailable", "reason": "not_persisted"},
        },
    }


def resolve_webui_index(dist_dir: str | Path | None = None) -> Path | None:
    """WebUI 单文件产物定位；不存在返回 None（调用方回 404 诚实体）。"""
    if dist_dir:
        base = Path(dist_dir)
    else:
        base = Path(__file__).resolve().parents[3] / "webui" / "dist"
    index = base / "index.html"
    return index if index.is_file() else None


@dataclass(frozen=True)
class WebUIStatsBundle:
    """WebUI 统计面服务束（装配期经 ``create_control_plane_app`` 注入）。"""

    calls: AuditCallStatsService
    affinity: AffinityBoardService


def build_default_stats_service(config: object | None) -> WebUIStatsBundle:
    """按 config 解析默认库路径（与 _app 默认装配同一套 runtime 重映射）。"""
    from .factory import _path

    audit_raw = str(getattr(config, "bot_audit_db_path", "") or "").strip()
    calls = AuditCallStatsService(_path(audit_raw)) if audit_raw else AuditCallStatsService("")
    affinity_raw = str(
        getattr(config, "bot_affinity_db_path", "") or "data/user_affinity.sqlite3"
    )
    return WebUIStatsBundle(
        calls=calls,
        affinity=AffinityBoardService(_path(affinity_raw)),
    )
