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

趋势口径（2026-10 修三处缺陷，见 tests/test_webui_stats.py 同名回归锁）：

1. **连续时间轴**：窗口内每个桶一行，没调用就是 ``calls: 0``。原实现
   ``sorted(trend, reverse=True)[:limit]`` 只切最新 N 个**有数据的**桶，中间空桶被
   整段抽掉 → 时间轴压缩 → 相隔数小时的相邻点被连成直线（看着像单调斜线）。
   由此 ``limit`` 不再兼作趋势点数（它只管 TopN 列表），趋势长度只受
   ``_MAX_TREND_POINTS`` 与窗口约束；被裁时 ``truncated_buckets`` 如实报数。
   窗口内一次调用都没有 → 不给轴（``items`` 为空，空表=没有横轴，不画 24 个假零）。
2. **业务时区**：桶按 ``timezone_name``（装配期传 ``config.bot_timezone``）取整，
   ``bucket_start`` 带该时区的真实偏移，``timezone`` 回填实际用的时区名；认不出的
   时区名退回 UTC 并如实回填 ``UTC``（不照抄配置撒谎）。同一屏不再两套时区。
3. **人 × 时段 × 次数**：``trend_by_user`` 是 userId×bucket 交叉表（TopN 用户各自
   成列，其余并成「其他」；派生不出用户的系统行只计入 ``unattributed_calls``）。
   它与 ``trend`` 在同一遍行扫描里累计，不新增查询，因此不额外吃预算。
   可归属率低于 ``_TREND_BY_USER_MIN_ATTRIBUTION`` 时整块返回 ``null`` +
   ``trend_by_user_reason``（生产实测仅 6.3% 可归属：不给表，也不给一张以偏概全的表）。
4. **数据可用性**：``coverage`` 如实回传 ``first_bucket``/``last_bucket``/
   ``available_buckets``/``requested_buckets``/``truncated_by_source`` 与真实数据
   跨度 ``first_data_at``/``last_data_at``。轴被源截短（审计库只留几十行/几十分钟）时，
   前端必须据此显式说明「历史数据不足」，不许把两个点画成一条像样的趋势线。

失败面沿用账本 metrics 先例：``{status, reason, data: None}``，固定 reason
代码，绝不回显路径/SQL/原文；无效参数先于任何 IO 校验。
"""

from __future__ import annotations

import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .metrics import _identifier

__all__ = [
    "DEFAULT_WEBUI_DIST_DIR",
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
#: 趋势点数上限：30d×hour＝721 桶会把响应撑大，超上限按窗口右侧对齐裁并在响应里报数。
#: 168(=24×7) 差一格兜不住 7d×hour(169)，故取 200。
_MAX_TREND_POINTS = 200
#: 交叉表只画 TopN 用户，其余并成一列（否则 N 人＝N 条线，图不可读）。
_TREND_USER_TOPN = 5
_TREND_OTHER_USER = "其他"
#: 人×时段交叉表的最低可归属率。低于此值交叉表整个不给（``null`` + 原因码）：
#: 生产实测 1000 行里只有 63 行派生得出用户（6.3%，其余是 ``email:*``/``runtime``
#: 等系统行），拿这 6% 画「按人趋势」＝以偏概全。宁缺毋滥。
_TREND_BY_USER_MIN_ATTRIBUTION = 0.5
#: 轴生成硬护栏（窗口是封闭枚举，真实最大 721；此处只防病态时钟成环）。
_AXIS_HARD_CAP = 5000

_AUDIT_REQUIRED_COLUMNS = frozenset({"created_at", "session_id", "capability_id"})
#: 身份四件套列（平台/群ID/群名/昵称）。**可选列**：存量库是 10 列版本，
#: 由写入侧 ``SQLiteAuditRepository._ensure_schema`` 在 bot 重启后幂等补齐；
#: 本服务是只读消费方，**绝不 ALTER**，缺列就如实报 ``available=false``。
_AUDIT_IDENTITY_COLUMNS: tuple[str, ...] = (
    "platform",
    "group_id",
    "group_title",
    "sender_nickname",
)
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


def _resolve_zone(name: object) -> tuple[Any, str]:
    """业务时区 → (tzinfo, 名字)。认不出/为空退回 UTC，并**如实回填** UTC。"""
    text = str(name or "").strip()
    if text:
        try:
            return ZoneInfo(text), text
        except (ZoneInfoNotFoundError, ValueError):
            pass  # ZoneInfoNotFoundError 是 KeyError 子类，不是 ValueError——两个都要接。
    return timezone.utc, "UTC"


def _bucket_start(stamp: datetime, *, hour: bool, zone: Any) -> datetime:
    """aware 瞬时 → 业务时区的桶起点（hour=整点 / day=当地零点）。

    按墙钟取整再交给 ``zone`` 重算偏移（ZoneInfo 的 utcoffset 由墙钟现算），
    因此 +08:00 部署下桶点就是本地整点，而不是 UTC 整点。
    """
    local = stamp.astimezone(zone)
    if hour:
        return local.replace(minute=0, second=0, microsecond=0)
    return datetime(local.year, local.month, local.day, tzinfo=zone)


def _next_bucket(stamp: datetime, *, hour: bool, zone: Any) -> datetime:
    """下一个桶起点。日桶按**日历日**推进（跨月跨年自动进位）。

    ponytail: 小时桶按 +1h 墙钟推进；目标时区（Asia/Hong_Kong、Asia/Shanghai、
    UTC）均无夏令时，故不会跳桶/重桶。真要支持有 DST 的时区，改法是把轴按
    绝对时刻生成再逐点取整（天花板已写明，不在本波范围）。
    """
    if hour:
        return stamp + timedelta(hours=1)
    following = date(stamp.year, stamp.month, stamp.day) + timedelta(days=1)
    return datetime(following.year, following.month, following.day, tzinfo=zone)


def _bucket_text(stamp: datetime) -> str:
    """UTC 用 ``Z`` 后缀（与 metrics._utc_bucket 同款口径），其余带真实偏移。"""
    return stamp.isoformat().replace("+00:00", "Z")


def _trend_axis(
    *, first: datetime, last: datetime, hour: bool, zone: Any
) -> list[str]:
    """[first, last] 的连续桶序列（升序，空桶靠调用方补 0）。"""
    out: list[str] = []
    cursor = first
    while cursor <= last and len(out) < _AXIS_HARD_CAP:
        out.append(_bucket_text(cursor))
        cursor = _next_bucket(cursor, hour=hour, zone=zone)
    return out


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


def _session_kind(session: str) -> str:
    """session_id → 会话种类。只读派生，不猜平台（平台另有列）。"""
    text = str(session or "")
    if text.startswith("group_"):
        return "group"
    if text.startswith("private_") or _DIGITS.fullmatch(text):
        return "private"
    if text.startswith("email:"):
        return "email"
    return "system"


def _group_id_from_session(session: str) -> str | None:
    """`group_<gid>_<uid>` → gid（OneBot v11 稳定约定，`_user_from_session` 同源）。

    存量审计行（迁移前写入的）列里没有群号，但**键里写着**——这是派生，不是编造。
    调用方必须同时把来源标出来（``group_id_source``），别让"库里记的"与"键里推的"
    在报表上长得一样。
    """
    parts = str(session or "").split("_")
    if len(parts) == 3 and parts[0] == "group" and _DIGITS.fullmatch(parts[1]):
        return parts[1]
    return None


def _optional_cell(row: sqlite3.Row | None, column: str) -> str | None:
    """容缺读可选列：行里没这列 / NULL / 空串 → None（未采集，不是空串）。"""
    if row is None or column not in row.keys():  # noqa: SIM118 - sqlite3.Row 的 in 查的是值不是列名
        return None
    value = row[column]
    if value is None:
        return None
    return str(value).strip() or None


def _accumulate_identity(
    bucket: dict[tuple[Any, ...], dict[str, Any]],
    *,
    session: str,
    user: str | None,
    row: sqlite3.Row | None,
) -> None:
    """把一行审计并进"会话身份"聚合（群合一行、私聊/系统按用户各自一行）。"""
    kind = _session_kind(session)
    platform = _optional_cell(row, "platform")
    column_group_id = _optional_cell(row, "group_id") if kind == "group" else None
    derived_group_id = _group_id_from_session(session) if kind == "group" else None
    group_id = column_group_id or derived_group_id
    group_id_source = (
        "audit_column" if column_group_id else ("session_id" if derived_group_id else None)
    )
    group_title = _optional_cell(row, "group_title")
    nickname = _optional_cell(row, "sender_nickname")
    key = (kind, platform, group_id, None if kind == "group" else user)
    entry = bucket.get(key)
    if entry is None:
        entry = {
            "kind": kind,
            "platform": platform,
            "group_id": group_id,
            "group_id_source": group_id_source,
            "group_title": group_title,
            "user_id": None if kind == "group" else user,
            "calls": 0,
            "users": {},
        }
        bucket[key] = entry
    entry["calls"] += 1
    if group_title is not None and entry["group_title"] is None:
        # 后到的行带来群名就补上（同名同群，覆盖无害）。
        entry["group_title"] = group_title
    if user is None:
        return
    user_entry = entry["users"].get(user)
    if user_entry is None:
        user_entry = {"user_id": user, "sender_nickname": nickname, "calls": 0}
        entry["users"][user] = user_entry
    user_entry["calls"] += 1
    if user_entry["sender_nickname"] is None and nickname is not None:
        user_entry["sender_nickname"] = nickname


def _identity_sessions_view(
    bucket: dict[tuple[Any, ...], dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {
            "kind": entry["kind"],
            "platform": entry["platform"],
            "group_id": entry["group_id"],
            "group_id_source": entry["group_id_source"],
            "group_title": entry["group_title"],
            "user_id": entry["user_id"],
            "calls": entry["calls"],
            "users": sorted(
                entry["users"].values(),
                key=lambda item: (-item["calls"], item["user_id"]),
            ),
        }
        for entry in bucket.values()
    ]
    out.sort(
        key=lambda row: (
            -row["calls"],
            row["kind"],
            str(row["group_id"] or row["user_id"] or ""),
        )
    )
    return out


def _top(counts: dict[Any, int], limit: int, *, label: str) -> list[dict[str, Any]]:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
    return [{label: key, "calls": count} for key, count in ranked[:limit]]


class AuditCallStatsService:
    """审计库只读聚合（``audit_records``；默认 1000 行 prune 上限，全量可扫）。"""

    def __init__(self, db_path: str | Path, timezone_name: str = "UTC") -> None:
        self._db_path = db_path
        #: 业务时区名（装配期传 ``config.bot_timezone``）：桶按它取整、响应回填它。
        #: 认不出时响应回填 ``UTC``（见 ``_resolve_zone``），但这里保留原始配置值。
        self.timezone_name = str(timezone_name or "UTC")

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
        zone, zone_name = _resolve_zone(self.timezone_name)
        hour_bucket = bucket == "hour"
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
                identity_available = set(_AUDIT_IDENTITY_COLUMNS) <= columns
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
                # 身份链聚合（平台/群/用户/昵称）。键按"会话身份"归并：
                # 群=同一群合一行（群里多个人挂在 users 下），私聊/系统按用户各自成行。
                identity_sessions: dict[tuple[Any, ...], dict[str, Any]] = {}
                # userId × bucket 交叉（与 trend 同一遍扫描累计，不额外查库）。
                user_trend: dict[str, dict[str, int]] = {}
                earliest_bucket: datetime | None = None
                latest_bucket: datetime | None = None
                first_stamp: datetime | None = None
                last_stamp: datetime | None = None
                # 列名只来自本文件常量元组（不接受外部输入），故可拼进 SELECT。
                identity_select = "".join(
                    f", {column}" for column in _AUDIT_IDENTITY_COLUMNS
                )
                rows = connection.execute(
                    "SELECT created_at, session_id, capability_id"
                    f"{identity_select if identity_available else ''}"
                    " FROM audit_records"
                ).fetchall()
                for row in rows:
                    stamp = _parse_utc(row["created_at"])
                    if stamp is None:
                        unknown_timestamp += 1
                        continue
                    if stamp < cutoff:
                        continue
                    total += 1
                    if first_stamp is None or stamp < first_stamp:
                        first_stamp = stamp
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
                    _accumulate_identity(
                        identity_sessions,
                        session=session,
                        user=user,
                        row=row if identity_available else None,
                    )
                    capability = str(row["capability_id"] or "")
                    cap_label = _identifier(capability, "capability") if capability else None
                    capabilities[cap_label] = capabilities.get(cap_label, 0) + 1
                    bucket_stamp = _bucket_start(stamp, hour=hour_bucket, zone=zone)
                    bucket_key = _bucket_text(bucket_stamp)
                    trend[bucket_key] = trend.get(bucket_key, 0) + 1
                    if earliest_bucket is None or bucket_stamp < earliest_bucket:
                        earliest_bucket = bucket_stamp
                    if latest_bucket is None or bucket_stamp > latest_bucket:
                        latest_bucket = bucket_stamp
                    if user is not None:
                        per_user = user_trend.setdefault(user, {})
                        per_user[bucket_key] = per_user.get(bucket_key, 0) + 1
                if time.monotonic() >= deadline:
                    return _failure("source_unavailable", "query_budget_exceeded")
                # 窗口内一次调用都没有 → 不给横轴（空表=没有横轴，不画一串假零）。
                axis: list[str] = []
                truncated_buckets = 0
                if earliest_bucket is not None and latest_bucket is not None:
                    axis = _trend_axis(
                        # 轴覆盖窗口起点，也覆盖早于窗口落桶的极端行（时钟回拨）。
                        first=min(
                            _bucket_start(cutoff, hour=hour_bucket, zone=zone),
                            earliest_bucket,
                        ),
                        last=max(
                            _bucket_start(
                                datetime.now(timezone.utc),
                                hour=hour_bucket,
                                zone=zone,
                            ),
                            latest_bucket,
                        ),
                        hour=hour_bucket,
                        zone=zone,
                    )
                    truncated_buckets = max(0, len(axis) - _MAX_TREND_POINTS)
                    axis = axis[truncated_buckets:]
                trend_by_user: dict[str, Any] | None
                trend_by_user_reason: str | None
                if total > 0 and (total - unattributed) / total < _TREND_BY_USER_MIN_ATTRIBUTION:
                    # 归因率过低：整块不给（null + 原因码），不拿少数可归属行冒充全貌。
                    trend_by_user = None
                    trend_by_user_reason = "insufficient_attribution"
                else:
                    cross = _cross_trend(axis, user_trend)
                    trend_by_user = {
                        "bucket": bucket,
                        "timezone": zone_name,
                        "top_users": cross["top_users"],
                        "other_label": _TREND_OTHER_USER,
                        "items": cross["items"],
                    }
                    trend_by_user_reason = None
                # 数据可用性：轴多长 / 几个桶真有调用 / 真实数据跨度 / 被源截短没有。
                covered_buckets = sum(1 for key in axis if trend.get(key))
                coverage = {
                    "first_bucket": axis[0] if axis else None,
                    "last_bucket": axis[-1] if axis else None,
                    "available_buckets": covered_buckets,
                    "requested_buckets": len(axis),
                    "truncated_by_source": covered_buckets < len(axis),
                    "first_data_at": (
                        first_stamp.isoformat() if first_stamp is not None else None
                    ),
                    "last_data_at": (
                        last_stamp.isoformat() if last_stamp is not None else None
                    ),
                }
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
                            "timezone": zone_name,
                            # 升序 + 窗口内每个桶都在（空桶补 0）：前端不用再 reverse。
                            "items": [
                                {"bucket_start": key, "calls": trend.get(key, 0)}
                                for key in axis
                            ],
                            # 轴超上限被右侧对齐裁掉多少桶；0=没裁。
                            "truncated_buckets": truncated_buckets,
                        },
                        "coverage": coverage,
                        # 身份链（平台/群或频道/用户ID/昵称）。缺列 = 未采集，
                        # 不填空串、不造值；缺列的旧库如实报 available=false。
                        "identity": {
                            "available": identity_available,
                            "fields": {
                                "collected": (
                                    list(_AUDIT_IDENTITY_COLUMNS)
                                    if identity_available
                                    else []
                                ),
                                "uncollected": (
                                    []
                                    if identity_available
                                    else list(_AUDIT_IDENTITY_COLUMNS)
                                ),
                            },
                            "sessions": _identity_sessions_view(identity_sessions),
                        },
                        "trend_by_user": trend_by_user,
                        "trend_by_user_reason": trend_by_user_reason,
                    },
                }
        except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
            return _failure("source_unavailable", "read_failed")


def _cross_trend(
    axis: list[str], user_trend: dict[str, dict[str, int]]
) -> dict[str, list[dict[str, Any]]]:
    """userId×bucket 交叉表 → TopN 用户各成一列，其余并成一列「其他」。

    只吐**有调用**的格子（稀疏）：横轴由 ``trend.items`` 给全，缺格即 0，
    不必再把 200×6 个空格子塞进响应。按 ``axis`` 顺序输出，不做字符串排序
    （跨夏令时后偏移不同，字符串序会错位）。
    """
    totals = {user: sum(per.values()) for user, per in user_trend.items()}
    top_users = _top(totals, _TREND_USER_TOPN, label="user")
    top_ids = {row["user"] for row in top_users}
    in_axis = set(axis)
    merged: dict[str, dict[str, int]] = {}
    for user, per in user_trend.items():
        target = user if user in top_ids else _TREND_OTHER_USER
        cells = merged.setdefault(target, {})
        for key, calls in per.items():
            if key in in_axis:
                cells[key] = cells.get(key, 0) + calls
    order = [row["user"] for row in top_users]
    if _TREND_OTHER_USER in merged:
        order.append(_TREND_OTHER_USER)
    items = [
        {"bucket_start": key, "user": user, "calls": merged[user][key]}
        for key in axis
        for user in order
        if merged.get(user, {}).get(key)
    ]
    return {"top_users": top_users, "items": items}


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


#: WebUI 产物默认根＝locator 单一真身（与 ``resolve_webui_index`` 同一基准）。
#: api 层（``api/webui.py``）只**消费**本符号，不再自存第二份基准推导——见
#: ``tests/test_control_plane_files_read_scope.py`` 的 F-3 活性锁（locator 不落 HTTP 层）。
DEFAULT_WEBUI_DIST_DIR: Path = Path(__file__).resolve().parents[3] / "webui" / "dist"


def resolve_webui_index(dist_dir: str | Path | None = None) -> Path | None:
    """WebUI 单文件产物定位；不存在返回 None（调用方回 404 诚实体）。"""
    if dist_dir:
        base = Path(dist_dir)
    else:
        base = DEFAULT_WEBUI_DIST_DIR
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
    # 趋势轴与 Bot 进程同一把钟：桶按 bot_timezone 取整、响应回填同一个时区名。
    zone_name = str(getattr(config, "bot_timezone", "") or "").strip() or "UTC"
    calls = AuditCallStatsService(
        _path(audit_raw) if audit_raw else "", timezone_name=zone_name
    )
    affinity_raw = str(
        getattr(config, "bot_affinity_db_path", "") or "data/user_affinity.sqlite3"
    )
    return WebUIStatsBundle(
        calls=calls,
        affinity=AffinityBoardService(_path(affinity_raw)),
    )
