"""WebUI 只读统计端点（Phase A）服务层契约：tmp 库、离线、只读打开。

- /api/v1/stats/calls   来源=审计 SQLite（audit_records，bot_audit_db_path）
- /api/v1/stats/tokens  来源=账本 llm_call_records（模型族×时间窗，四项 token）
- /api/v1/stats/latency 来源=channel_health（EWMA 当前值；历史无存储=诚实 null）
- /api/v1/affinity/board 来源=user_affinity（显数值榜单，2026-09-15 用户裁定）

全部只读（URI mode=ro + query_only），缺源/坏源返回固定 reason 的
source_unavailable，绝不创建文件、绝不回显路径或原文。
"""

from __future__ import annotations

import ast
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.control_plane.metrics import LedgerMetricsService
from plugins.bot_unified_runtime.control_plane.webui_stats import (
    AffinityBoardService,
    AuditCallStatsService,
    latency_view,
)
from plugins.bot_unified_runtime.domains.core.contracts import AuditRecord, RiskLevel
from plugins.bot_unified_runtime.domains.ops.audit.logger import SQLiteAuditRepository

ROOT = Path(__file__).resolve().parents[1]
LEDGER_MODULE = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/llm_engine/ledger.py"


def _seed_audit(path: Path, records: list[AuditRecord]) -> None:
    repo = SQLiteAuditRepository(path)
    for record in records:
        repo.append(record)


def _audit_record(
    *,
    session_id: str,
    capability_id: str,
    created: datetime | None = None,
) -> AuditRecord:
    return AuditRecord(
        request_id="req-seed",
        session_id=session_id,
        capability_id=capability_id,
        stage="invoke",
        event="capability_done",
        severity=RiskLevel.LOW,
        public_message="ok",
        private_debug="",
        created_at=created or datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# stats/calls —— 审计库聚合
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_db(tmp_path: Path) -> Path:
    path = tmp_path / "audit.sqlite3"
    now = datetime.now(timezone.utc)
    _seed_audit(
        path,
        [
            _audit_record(
                session_id="group_100_20001",
                capability_id="bot.chat",
                created=now - timedelta(hours=2),
            ),
            _audit_record(
                session_id="private_20001",
                capability_id="bot.chat",
                created=now - timedelta(hours=3),
            ),
            _audit_record(
                session_id="runtime",
                capability_id="bot.credential_check",
                created=now - timedelta(hours=5),
            ),
            # 窗口外（30 天前）：24h 不计入，30d 计入。
            _audit_record(
                session_id="private_30001",
                capability_id="bot.reminder",
                created=now - timedelta(days=10),
            ),
        ],
    )
    # 混合时区偏移的一行（22:35+08:00 == 14:35Z，须按 UTC 正确入桶/入窗）。
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO audit_records (audit_id, request_id, session_id,"
            " capability_id, stage, event, severity, public_message,"
            " private_debug, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "audit_mixed_tz",
                "req-seed",
                "private_20002",
                "bot.chat",
                "invoke",
                "capability_done",
                "low",
                "ok",
                "",
                (now - timedelta(hours=1)).astimezone(timezone(timedelta(hours=8))).isoformat(),
            ),
        )
    return path


def test_calls_window_totals_sessions_users_capabilities(audit_db: Path) -> None:
    result = AuditCallStatsService(audit_db).calls(window="24h", bucket="hour")
    assert result["status"] == "ok"
    assert result["source"] == "audit_records"
    data = result["data"]
    assert data["window"] == "24h"
    # 5 行里 4 行在 24h 内；1 行 10 天前出窗。
    assert data["total_calls"] == 4
    assert data["unknown_timestamp_calls"] == 0

    # 会话：HMAC 假名（不回显原始 session id），计数正确。
    session_counts = {row["session"]: row["calls"] for row in data["by_session"]}
    assert sum(session_counts.values()) == 4
    assert len(session_counts) == 4
    assert all(key.startswith("session_") for key in session_counts)
    dumped = json.dumps(data, ensure_ascii=False)
    assert "group_100_20001" not in dumped and "private_20001" not in dumped

    # 用户：按 OneBot 约定从 session id 派生（private_<uid>/group_<gid>_<uid>）；
    # 派生不出（runtime 等系统行）计入 unattributed_calls，绝不造一个用户。
    users = {row["user"]: row["calls"] for row in data["by_user"]}
    assert users == {"20001": 2, "20002": 1}
    assert data["unattributed_calls"] == 1
    assert data["user_attribution"] == "derived_from_session_id_onebot_convention"

    # 能力：原文能力码（bot.chat×3，credential_check×1）。
    caps = {row["capability"]: row["calls"] for row in data["by_capability"]}
    assert caps == {"bot.chat": 3, "bot.credential_check": 1}

    # 趋势桶：UTC 小时桶，4 行 4 个有调用的小时；窗口内空桶补 0、整体升序。
    assert data["trend"]["bucket"] == "hour"
    assert data["trend"]["timezone"] == "UTC"
    assert sum(item["calls"] for item in data["trend"]["items"]) == 4
    starts = [item["bucket_start"] for item in data["trend"]["items"]]
    assert starts == sorted(starts)
    assert all(stamp.endswith("Z") for stamp in starts)


def test_calls_day_bucket_and_wider_window_includes_old_rows(audit_db: Path) -> None:
    service = AuditCallStatsService(audit_db)
    wide = service.calls(window="30d", bucket="day")["data"]
    assert wide["total_calls"] == 5
    assert wide["trend"]["bucket"] == "day"
    assert sum(item["calls"] for item in wide["trend"]["items"]) == 5
    # 用户跨窗聚合同样成立。
    users = {row["user"]: row["calls"] for row in wide["by_user"]}
    assert users["30001"] == 1


def test_calls_unknown_timestamp_counted_but_excluded(audit_db: Path) -> None:
    with closing(sqlite3.connect(audit_db)) as connection, connection:
        connection.execute(
            "INSERT INTO audit_records (audit_id, request_id, session_id,"
            " capability_id, stage, event, severity, public_message,"
            " private_debug, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "audit_bad_ts",
                "req-seed",
                "private_40001",
                "bot.chat",
                "invoke",
                "capability_done",
                "low",
                "ok",
                "",
                "not-a-timestamp",
            ),
        )
    data = AuditCallStatsService(audit_db).calls(window="24h")["data"]
    assert data["total_calls"] == 4
    assert data["unknown_timestamp_calls"] == 1
    assert all(row["user"] != "40001" for row in data["by_user"])
    assert "not-a-timestamp" not in json.dumps(data)


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "10", None])
def test_calls_invalid_limit_rejected_without_opening_db(
    tmp_path: Path, monkeypatch, limit
) -> None:
    def no_connect(*args, **kwargs):
        pytest.fail("invalid request opened database")

    monkeypatch.setattr("plugins.bot_unified_runtime.control_plane.webui_stats.sqlite3.connect", no_connect)
    result = AuditCallStatsService(tmp_path / "x.sqlite3").calls(limit=limit)
    assert result == {"status": "invalid_request", "reason": "invalid_limit", "data": None}


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"window": "99w"}, "invalid_window"),
        ({"window": "24h; DROP TABLE audit_records"}, "invalid_window"),
        ({"bucket": "week"}, "invalid_bucket"),
        ({"bucket": "HOUR"}, "invalid_bucket"),
    ],
)
def test_calls_closed_enums(audit_db: Path, kwargs, reason: str) -> None:
    result = AuditCallStatsService(audit_db).calls(**kwargs)
    assert result == {"status": "invalid_request", "reason": reason, "data": None}


def test_calls_missing_source_never_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "audit.sqlite3"
    result = AuditCallStatsService(path).calls()
    assert result["status"] == "source_unavailable"
    assert result["data"] is None
    assert not path.parent.exists()
    assert str(path) not in json.dumps(result)


def test_calls_bad_sources_are_explicit_and_read_only(tmp_path: Path) -> None:
    path = tmp_path / "audit.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE something_else (id INTEGER)")
    assert AuditCallStatsService(path).calls()["reason"] == "missing_table"

    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DROP TABLE something_else")
        connection.execute("CREATE TABLE audit_records (created_at TEXT)")
    assert AuditCallStatsService(path).calls()["reason"] == "incomplete_schema"

    path.write_bytes(b"corrupt sk-secret")
    before = path.read_bytes()
    broken = AuditCallStatsService(path).calls()
    assert broken["status"] == "source_unavailable"
    assert broken["data"] is None
    assert path.read_bytes() == before
    assert "sk-secret" not in json.dumps(broken)


def test_calls_empty_but_valid_table_is_zero_not_failure(tmp_path: Path) -> None:
    path = tmp_path / "audit.sqlite3"
    repo = SQLiteAuditRepository(path)
    repo.append(
        _audit_record(session_id="private_1", capability_id="bot.chat")
    )
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DELETE FROM audit_records")
    data = AuditCallStatsService(path).calls()["data"]
    assert data["total_calls"] == 0
    assert data["by_session"] == [] and data["by_user"] == []
    assert data["by_capability"] == [] and data["trend"]["items"] == []


def test_calls_unconfigured_path_is_honest(tmp_path: Path) -> None:
    result = AuditCallStatsService("").calls()
    assert result == {
        "status": "source_unavailable",
        "reason": "audit_source_not_configured",
        "data": None,
    }


# ---------------------------------------------------------------------------
# stats/calls —— 活跃人数 / 最近一条（运行状态页 A7/A8 增补）
# ---------------------------------------------------------------------------


@pytest.fixture
def active_db(tmp_path: Path) -> tuple[Path, datetime]:
    """固定相对时刻的三名用户 + 一行窗口外 + 一行派生不出用户的系统行。"""
    path = tmp_path / "audit-active.sqlite3"
    now = datetime.now(timezone.utc)
    in_window = {
        "20001": now - timedelta(hours=2),
        "20002": now - timedelta(hours=1),
        "30001": now - timedelta(hours=20),
    }
    repo = SQLiteAuditRepository(path)
    for uid, stamp in in_window.items():
        session = f"group_900_{uid}" if uid == "20001" else f"private_{uid}"
        repo.append(
            _audit_record(session_id=session, capability_id="bot.chat", created=stamp)
        )
    repo.append(
        _audit_record(
            session_id="runtime",
            capability_id="bot.credential_check",
            created=now - timedelta(minutes=30),
        )
    )
    repo.append(
        _audit_record(
            session_id="private_30001",
            capability_id="bot.reminder",
            created=now - timedelta(days=10),
        )
    )
    # 最新一条以 +08:00 偏移文本直写：last_message_at 必须归一为 UTC ISO。
    latest_local = (now - timedelta(minutes=5)).astimezone(
        timezone(timedelta(hours=8))
    )
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO audit_records (audit_id, request_id, session_id,"
            " capability_id, stage, event, severity, public_message,"
            " private_debug, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "audit-active-latest",
                "req-active",
                "private_20002",
                "bot.chat",
                "invoke",
                "capability_done",
                "low",
                "ok",
                "",
                latest_local.isoformat(),
            ),
        )
    return path, now


def test_calls_active_users_dedup_excludes_unattributed(
    active_db: tuple[Path, datetime],
) -> None:
    path, _ = active_db
    data = AuditCallStatsService(path).calls(window="24h", bucket="hour")["data"]
    # 24h 内可归属用户=20001/20002/30001 去重 3 人；runtime 系统行不计入，
    # 只进 unattributed_calls（单列既有口径）。
    assert data["active_users"] == 3
    assert data["unattributed_calls"] == 1
    assert data["active_users"] <= sum(row["calls"] for row in data["by_user"]) + data[
        "unattributed_calls"
    ]


def test_calls_active_users_grows_with_window(
    active_db: tuple[Path, datetime],
) -> None:
    path, _ = active_db
    wide = AuditCallStatsService(path).calls(window="30d", bucket="day")["data"]
    # 30d 窗口追加 10 天前的 private_30001——与 24h 内同一用户，去重仍 3 人。
    assert wide["active_users"] == 3
    assert wide["unattributed_calls"] == 1


def test_calls_last_message_at_is_utc_iso_of_latest_in_window(
    active_db: tuple[Path, datetime],
) -> None:
    path, now = active_db
    data = AuditCallStatsService(path).calls(window="24h", bucket="hour")["data"]
    stamp = data["last_message_at"]
    assert isinstance(stamp, str) and stamp.endswith("+00:00")
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None
    # 最新一条=5 分钟前那行（+08:00 文本入、UTC ISO 出）。
    expected = (now - timedelta(minutes=5)).astimezone(timezone.utc)
    assert abs((parsed - expected).total_seconds()) < 5
    # 窗口过滤后的 max，不是全表 max：10 天前那行永不反超。
    assert parsed <= datetime.now(timezone.utc)


def test_calls_last_message_at_null_when_window_empty(tmp_path: Path) -> None:
    path = tmp_path / "audit-stale.sqlite3"
    repo = SQLiteAuditRepository(path)
    repo.append(
        _audit_record(
            session_id="private_1",
            capability_id="bot.chat",
            created=datetime.now(timezone.utc) - timedelta(days=90),
        )
    )
    data = AuditCallStatsService(path).calls(window="24h")["data"]
    assert data["last_message_at"] is None
    assert data["active_users"] == 0
    assert data["total_calls"] == 0


def test_calls_empty_table_null_fields_not_failure(tmp_path: Path) -> None:
    path = tmp_path / "audit-empty.sqlite3"
    repo = SQLiteAuditRepository(path)
    repo.append(
        _audit_record(session_id="private_1", capability_id="bot.chat")
    )
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DELETE FROM audit_records")
    data = AuditCallStatsService(path).calls()["data"]
    assert data["last_message_at"] is None
    assert data["active_users"] == 0
    assert data["total_calls"] == 0


# ---------------------------------------------------------------------------
# stats/calls —— 趋势时间轴（连续波形 / 业务时区 / 人×时段交叉）
#
# 三个缺陷回归锁：
#  ① `sorted(trend, reverse=True)[:limit]` 只取最新 N 个**有数据的**桶，中间空桶被
#     抽掉 → 时间轴压缩 → 相隔多小时的相邻点被连成直线（看着像单调斜线）。
#  ② `"timezone": "UTC"` 硬编码 → 同一屏两套时区（Bot 进程 Asia/Hong_Kong，轴却是 UTC）。
#  ③ 只有 by_user（按人总量）与 trend（按时段总量）两个独立维度，没有 userId×bucket。
# ---------------------------------------------------------------------------


def _seed_gap_audit(path: Path, now: datetime) -> None:
    """5 小时前与 1 小时前各一条（中间隔 3 个整点空桶）。"""
    repo = SQLiteAuditRepository(path)
    repo.append(
        _audit_record(
            session_id="private_20001",
            capability_id="bot.chat",
            created=now - timedelta(hours=5),
        )
    )
    repo.append(
        _audit_record(
            session_id="private_20001",
            capability_id="bot.chat",
            created=now - timedelta(hours=1),
        )
    )


def test_trend_fills_empty_buckets_instead_of_dropping_them(tmp_path: Path) -> None:
    """空桶必须补成 calls=0，而不是从序列里消失（时间轴不许被压缩）。"""
    path = tmp_path / "audit-gap.sqlite3"
    _seed_gap_audit(path, datetime.now(timezone.utc))
    data = AuditCallStatsService(path).calls(window="24h", bucket="hour")["data"]
    items = data["trend"]["items"]
    # 24h 窗口按小时铺满 → 24 或 25 个连续桶（滚窗起止可能跨一个边界）。
    assert 24 <= len(items) <= 25, f"空桶被抽掉：只给了 {len(items)} 个桶"
    non_zero = [i for i, item in enumerate(items) if item["calls"]]
    assert len(non_zero) == 2, "两个有调用的桶必须都在，且各 1 次"
    assert all(items[i]["calls"] == 1 for i in non_zero)
    # 两个采样相隔正好 4 个整点桶；中间三个必须是 0（不是被删掉）。
    assert non_zero[1] - non_zero[0] == 4, "相邻点的间隔必须等于真实小时差"
    gap = items[non_zero[0] + 1 : non_zero[1]]
    assert [item["calls"] for item in gap] == [0, 0, 0]


def test_trend_items_are_time_ascending(tmp_path: Path) -> None:
    """升序输出：前端不必再 reverse（倒序 + 前端 reverse 是最容易左右颠倒的组合）。"""
    path = tmp_path / "audit-order.sqlite3"
    _seed_gap_audit(path, datetime.now(timezone.utc))
    starts = [
        item["bucket_start"]
        for item in AuditCallStatsService(path).calls(window="24h")["data"]["trend"]["items"]
    ]
    assert starts == sorted(starts), "趋势必须按时间升序"
    assert len(starts) == len(set(starts)), "桶不许重复"


def test_trend_timezone_is_business_zone_and_bucket_carries_its_offset(
    tmp_path: Path,
) -> None:
    """时区取业务时区（bot_timezone），bucket_start 带该时区的真实偏移。"""
    from zoneinfo import ZoneInfo

    path = tmp_path / "audit-tz.sqlite3"
    now = datetime.now(timezone.utc)
    _seed_gap_audit(path, now)
    service = AuditCallStatsService(path, timezone_name="Asia/Hong_Kong")
    trend = service.calls(window="24h", bucket="hour")["data"]["trend"]
    assert trend["timezone"] == "Asia/Hong_Kong"
    assert trend["items"], "窗口内有调用就必须有桶"
    assert all(item["bucket_start"].endswith("+08:00") for item in trend["items"])
    # 1 小时前那条的桶 = 香港墙钟的整点，不是 UTC 整点。
    expected = (
        (now - timedelta(hours=1))
        .astimezone(ZoneInfo("Asia/Hong_Kong"))
        .replace(minute=0, second=0, microsecond=0)
        .isoformat()
    )
    hits = [item for item in trend["items"] if item["calls"]]
    assert len(hits) == 2
    assert hits[-1]["bucket_start"] == expected


def test_trend_unknown_timezone_falls_back_to_utc_honestly(tmp_path: Path) -> None:
    path = tmp_path / "audit-tz-bad.sqlite3"
    _seed_gap_audit(path, datetime.now(timezone.utc))
    trend = AuditCallStatsService(path, timezone_name="Not/AZone").calls(window="24h")[
        "data"
    ]["trend"]
    assert trend["timezone"] == "UTC", "认不出的时区必须如实回填 UTC，不许照抄配置"
    assert all(item["bucket_start"].endswith("Z") for item in trend["items"])


def test_trend_truncates_long_axis_and_reports_dropped_buckets(tmp_path: Path) -> None:
    """30d×hour＝721 桶撑爆响应：按窗口裁到上限，并把被裁数量如实报出。"""
    path = tmp_path / "audit-truncate.sqlite3"
    _seed_gap_audit(path, datetime.now(timezone.utc))
    trend = AuditCallStatsService(path).calls(window="30d", bucket="hour")["data"]["trend"]
    assert len(trend["items"]) <= 200, "小时桶上限必须兜住 30 天×24"
    assert trend["truncated_buckets"] > 0, "被裁了就必须说被裁了"
    # 保留的是最新那一批（右侧对齐），最新桶永远是最后一个。
    assert trend["items"][-1]["bucket_start"] == max(
        item["bucket_start"] for item in trend["items"]
    )
    # 最新桶=当前小时（窗口里没有当前小时的调用，如实 0）；1 小时前那条在倒数第二格。
    assert trend["items"][-1]["calls"] == 0
    assert trend["items"][-2]["calls"] == 1, "1 小时前的调用必须在保留区里"


def test_trend_by_user_crosses_user_and_bucket_with_other_bucket(
    tmp_path: Path,
) -> None:
    """人 × 时段 × 次数：TopN 用户各自成列，其余归「其他」。"""
    path = tmp_path / "audit-cross.sqlite3"
    now = datetime.now(timezone.utc)
    repo = SQLiteAuditRepository(path)
    # 20001..20007：调用次数依次 8..2（20001 最多）。
    for offset, uid in enumerate(range(20001, 20008)):
        for n in range(8 - offset):
            repo.append(
                _audit_record(
                    session_id=f"private_{uid}",
                    capability_id="bot.chat",
                    created=now - timedelta(hours=1, minutes=n),
                )
            )
    data = AuditCallStatsService(path).calls(window="24h", bucket="hour")["data"]
    cross = data["trend_by_user"]
    assert cross["bucket"] == "hour"
    assert cross["other_label"] == "其他"
    assert [row["user"] for row in cross["top_users"]] == [
        "20001",
        "20002",
        "20003",
        "20004",
        "20005",
    ]
    users_in_items = {row["user"] for row in cross["items"]}
    assert users_in_items == {"20001", "20002", "20003", "20004", "20005", "其他"}
    # TopN 各自的次数原样；「其他」＝20006(3)+20007(2)=5。
    per_user: dict[str, int] = {}
    for row in cross["items"]:
        per_user[row["user"]] = per_user.get(row["user"], 0) + row["calls"]
    assert per_user["20001"] == 8
    assert per_user["其他"] == 5
    # 交叉表不许改变既有语义。
    assert data["total_calls"] == 8 + 7 + 6 + 5 + 4 + 3 + 2
    assert sum(row["calls"] for row in cross["items"]) == data["total_calls"]


def test_trend_by_user_excludes_unattributed_rows(tmp_path: Path) -> None:
    """派生不出用户的系统行只进 unattributed_calls，绝不造一个用户。

    100% 归因失败 ⇒ 交叉表退化为 null + 原因码（不是「一张空表」——空表会被
    误读成「窗口内没有人调用」，而真相是「有调用但认不出是谁」）。
    """
    path = tmp_path / "audit-cross-sys.sqlite3"
    now = datetime.now(timezone.utc)
    repo = SQLiteAuditRepository(path)
    repo.append(
        _audit_record(
            session_id="runtime", capability_id="bot.chat", created=now - timedelta(hours=1)
        )
    )
    data = AuditCallStatsService(path).calls(window="24h")["data"]
    assert data["unattributed_calls"] == 1
    assert data["trend_by_user"] is None
    assert data["trend_by_user_reason"] == "insufficient_attribution"


def test_calls_budget_exceeded_returns_failure_not_exception(
    tmp_path: Path, monkeypatch
) -> None:
    """预算超时仍是结构化失败（端点不抛异常、不吐半截数据）。"""
    path = tmp_path / "audit-budget.sqlite3"
    _seed_gap_audit(path, datetime.now(timezone.utc))
    ticks = {"n": 0}

    def fake_monotonic() -> float:
        ticks["n"] += 1
        return 0.0 if ticks["n"] == 1 else 99.0

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.control_plane.webui_stats.time.monotonic",
        fake_monotonic,
    )
    assert AuditCallStatsService(path).calls() == {
        "status": "source_unavailable",
        "reason": "query_budget_exceeded",
        "data": None,
    }


def test_build_default_stats_service_passes_bot_timezone(tmp_path: Path) -> None:
    """装配期必须把 bot_timezone 传下去——否则趋势轴仍是第二套时区。"""

    class _Config:
        bot_audit_db_path = str(tmp_path / "audit.sqlite3")
        bot_affinity_db_path = str(tmp_path / "affinity.sqlite3")
        bot_timezone = "Asia/Hong_Kong"

    from plugins.bot_unified_runtime.control_plane.webui_stats import (
        build_default_stats_service,
    )

    bundle = build_default_stats_service(_Config())
    assert bundle.calls.timezone_name == "Asia/Hong_Kong"


def test_trend_coverage_reports_data_availability(tmp_path: Path) -> None:
    """数据可用性必须如实回传：轴多长、几个桶真有调用、真实数据跨度、被源截短没有。

    生产实测（2026-10-19，1000 行 prune 上限）：24h 窗口只有 2 个桶有数据、跨度 48 分钟。
    没有 coverage 块，前端只能把「25 个桶里 2 个非零」画成一条像样的趋势图——
    这正是「不许美化」要挡住的那种表达。
    """
    path = tmp_path / "audit-coverage.sqlite3"
    now = datetime.now(timezone.utc)
    _seed_gap_audit(path, now)
    data = AuditCallStatsService(path).calls(window="24h", bucket="hour")["data"]
    items = data["trend"]["items"]
    coverage = data["coverage"]
    assert coverage["requested_buckets"] == len(items) == 25
    assert coverage["first_bucket"] == items[0]["bucket_start"]
    assert coverage["last_bucket"] == items[-1]["bucket_start"]
    assert coverage["available_buckets"] == 2
    assert coverage["truncated_by_source"] is True
    # 两个真实数据点相隔 4 小时（夹具 5 小时前 / 1 小时前各一条）。
    first_data = datetime.fromisoformat(coverage["first_data_at"])
    last_data = datetime.fromisoformat(coverage["last_data_at"])
    assert (last_data - first_data) == timedelta(hours=4)


def test_trend_coverage_not_truncated_when_axis_is_full(tmp_path: Path) -> None:
    """每个桶都有调用时按事实说「没被截」——不能永远报 True。"""
    path = tmp_path / "audit-coverage-full.sqlite3"
    now = datetime.now(timezone.utc)
    repo = SQLiteAuditRepository(path)
    # 7d×day：轴 = 8 个日桶（含窗口起点那半天）。起点桶用「窗口起点 +1h」这一行盖住，
    # 其余 7 天各一行——不依赖「现在几点」，任何时刻都铺满。
    for days_ago in range(7):
        repo.append(
            _audit_record(
                session_id="private_20001",
                capability_id="bot.chat",
                created=now - timedelta(days=days_ago),
            )
        )
    repo.append(
        _audit_record(
            session_id="private_20001",
            capability_id="bot.chat",
            created=now - timedelta(days=7) + timedelta(hours=1),
        )
    )
    data = AuditCallStatsService(path).calls(window="7d", bucket="day")["data"]
    coverage = data["coverage"]
    assert coverage["requested_buckets"] == 8
    assert coverage["available_buckets"] == 8
    assert coverage["truncated_by_source"] is False
    # 桶和 == total_calls：轴覆盖整个窗口，不丢行也不重复计。
    assert sum(item["calls"] for item in data["trend"]["items"]) == data["total_calls"] == 8


def test_trend_by_user_withheld_when_attribution_is_unreliable(
    tmp_path: Path,
) -> None:
    """归因率低就不硬做交叉表：返回 null + 固定原因码，而不是给一张 6% 覆盖的表。

    生产实测：1000 行里 937 行派生不出用户（email:* / runtime 等系统行），
    此时交叉表只剩 63 行，任何「按人」结论都会以偏概全。
    """
    path = tmp_path / "audit-low-attribution.sqlite3"
    now = datetime.now(timezone.utc)
    repo = SQLiteAuditRepository(path)
    repo.append(
        _audit_record(
            session_id="private_20001",
            capability_id="bot.chat",
            created=now - timedelta(hours=1),
        )
    )
    for _ in range(9):
        repo.append(
            _audit_record(
                session_id="email:noreply@example.com",
                capability_id="bot.content",
                created=now - timedelta(hours=1),
            )
        )
    data = AuditCallStatsService(path).calls(window="24h", bucket="hour")["data"]
    assert data["total_calls"] == 10
    assert data["unattributed_calls"] == 9
    assert data["trend_by_user"] is None
    assert data["trend_by_user_reason"] == "insufficient_attribution"
    # 主趋势轴不受影响（人×时段只是附加维度，缺席不改主图）。
    assert data["trend"]["items"]


# ---------------------------------------------------------------------------
# stats/tokens —— 账本模型族×时间窗
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ledger_schema() -> str:
    tree = ast.parse(LEDGER_MODULE.read_text(encoding="utf-8"))
    return next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_SCHEMA_SQL"
            for target in node.targets
        )
    )


@pytest.fixture
def ledger_db(tmp_path: Path, ledger_schema: str) -> Path:
    path = tmp_path / "ledger.sqlite3"
    now = datetime.now(timezone.utc)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(ledger_schema)

    def insert(
        *,
        actual_model: str,
        hours_ago: float,
        prompt: int | None,
        completion: int | None = None,
        cache_read: int | None = None,
        cache_creation: int | None = None,
        status: str = "success",
    ) -> None:
        started = now - timedelta(hours=hours_ago)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                "INSERT INTO llm_call_records (request_id, started_at, completed_at,"
                " model_id, actual_model, status, prompt_tokens, completion_tokens,"
                " cache_read_tokens, cache_creation_tokens, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "req",
                    started.isoformat(),
                    started.isoformat(),
                    "channel-x",
                    actual_model,
                    status,
                    prompt,
                    completion,
                    cache_read,
                    cache_creation,
                    started.isoformat(),
                ),
            )

    # 同族三行（大小写/档位后缀归一）：gemini-3.8-flash。
    insert(actual_model="Gemini-3.8-Flash-HIGH", hours_ago=1, prompt=10, completion=4, cache_read=2)
    insert(actual_model="gemini-3.8-flash", hours_ago=2, prompt=30, completion=0, cache_creation=5)
    insert(actual_model="gemini-3.8-flash", hours_ago=3, prompt=None)
    # 另一族。
    insert(actual_model="gpt-5.6-terra-xhigh", hours_ago=4, prompt=100, completion=50)
    # 窗口外（40 小时前 > 24h）：24h 不计、30d 计。
    insert(actual_model="gpt-5.6-terra", hours_ago=40, prompt=7, completion=3)
    return path


def test_token_window_follows_stored_utc_offset(
    ledger_schema: str, tmp_path: Path
) -> None:
    """窗口边界必须按账本实际偏移渲染。

    回归锁（2026-09-19 F13 首报 / F21 敌对复算证真的 8 小时平移）：写入侧用本地时区
    （+08:00）渲染 completed_at，而过滤走 ISO 文本序——边界固定按 UTC 渲染时，
    「近 24 小时」会丢掉最近 8 小时的真实调用、并把 26 小时前的旧行纳进来。
    既有 ledger_db 夹具种子全为 UTC，故该缺陷在修前可长绿。
    """
    path = tmp_path / "ledger-plus8.sqlite3"
    zone_plus8 = timezone(timedelta(hours=8))
    now = datetime.now(timezone.utc)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(ledger_schema)
        for actual_model, hours_ago in (("gemini-3.8-flash", 0.1), ("gpt-5.6-terra", 26.0)):
            moment = (now - timedelta(hours=hours_ago)).astimezone(zone_plus8)
            stamp = moment.isoformat(timespec="milliseconds")
            connection.execute(
                "INSERT INTO llm_call_records (request_id, started_at, completed_at,"
                " model_id, actual_model, status, prompt_tokens, completion_tokens,"
                " cache_read_tokens, cache_creation_tokens, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "req",
                    stamp,
                    stamp,
                    "channel-x",
                    actual_model,
                    "success",
                    10,
                    4,
                    None,
                    None,
                    stamp,
                ),
            )
    result = LedgerMetricsService(path).token_families(window="24h")
    assert result["status"] == "ok"
    families = {row["family"]: row for row in result["data"]["families"]}
    # 6 分钟前的行必须在窗内；26 小时前的行必须在窗外。
    assert set(families) == {"gemini-3.8-flash"}, f"窗口按 UTC 平移了：{sorted(families)}"
    assert families["gemini-3.8-flash"]["calls"] == 1


def test_tokens_family_merge_window_and_quality(ledger_db: Path) -> None:
    result = LedgerMetricsService(ledger_db).token_families(window="24h")
    assert result["status"] == "ok"
    assert result["source"] == "llm_call_records"
    data = result["data"]
    assert data["window"] == "24h"

    families = {row["family"]: row for row in data["families"]}
    assert set(families) == {"gemini-3.8-flash", "gpt-5.6-terra"}
    gemini = families["gemini-3.8-flash"]
    assert gemini["calls"] == 3
    assert gemini["tokens"]["input"] == {
        "value": 40,
        "known_rows": 2,
        "unknown_rows": 1,
        "quality": "partial",
    }
    assert gemini["tokens"]["output"] == {
        "value": 4,
        "known_rows": 2,
        "unknown_rows": 1,
        "quality": "partial",
    }
    assert gemini["tokens"]["cache_read"] == {
        "value": 2,
        "known_rows": 1,
        "unknown_rows": 2,
        "quality": "partial",
    }
    assert gemini["tokens"]["cache_creation"] == {
        "value": 5,
        "known_rows": 1,
        "unknown_rows": 2,
        "quality": "partial",
    }
    terra = families["gpt-5.6-terra"]
    assert terra["calls"] == 1
    assert terra["tokens"]["input"]["value"] == 100
    assert terra["tokens"]["output"]["value"] == 50

    # 排序按调用数降序；总量含全部窗口内行。
    assert data["families"][0]["family"] == "gemini-3.8-flash"
    totals = data["totals"]
    assert totals["calls"] == 4
    assert totals["tokens"]["input"] == {
        "value": 140,
        "known_rows": 3,
        "unknown_rows": 1,
        "quality": "partial",
    }


def test_tokens_wider_window_pulls_in_older_rows(ledger_db: Path) -> None:
    data = LedgerMetricsService(ledger_db).token_families(window="30d")["data"]
    terra = {row["family"]: row for row in data["families"]}["gpt-5.6-terra"]
    assert terra["calls"] == 2
    assert terra["tokens"]["input"]["value"] == 107


@pytest.mark.parametrize("window", ["99w", "week", "", None, "24h; DROP TABLE llm_call_records"])
def test_tokens_invalid_window_is_closed_enum(ledger_db: Path, window) -> None:
    result = LedgerMetricsService(ledger_db).token_families(window=window)
    assert result == {"status": "invalid_request", "reason": "invalid_window", "data": None}


@pytest.mark.parametrize("limit", [0, -1, 101, True, 2.5, "10", None])
def test_tokens_invalid_limit_rejected_without_opening_db(
    tmp_path: Path, monkeypatch, limit
) -> None:
    def no_connect(*args, **kwargs):
        pytest.fail("invalid request opened database")

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.control_plane.metrics.sqlite3.connect", no_connect
    )
    result = LedgerMetricsService(tmp_path / "x.sqlite3").token_families(limit=limit)
    assert result == {"status": "invalid_request", "reason": "invalid_limit", "data": None}


@pytest.mark.parametrize("kind", ["missing_file", "missing_table", "incomplete", "corrupt"])
def test_tokens_bad_sources_honest_and_read_only(
    tmp_path: Path, ledger_schema: str, kind: str
) -> None:
    path = tmp_path / "ledger.sqlite3"
    if kind == "corrupt":
        path.write_bytes(b"not sqlite sk-secret")
    elif kind == "missing_table":
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE other (id INTEGER)")
    elif kind == "incomplete":
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE llm_call_records (status TEXT)")
    before = path.read_bytes() if path.exists() else None
    result = LedgerMetricsService(path).token_families()
    assert result["status"] == "source_unavailable"
    assert result["data"] is None
    if before is not None:
        assert path.read_bytes() == before
    assert "sk-secret" not in json.dumps(result)
    assert str(path) not in json.dumps(result)


# ---------------------------------------------------------------------------
# stats/latency —— 渠道 EWMA 当前值（历史无存储=诚实字段）
# ---------------------------------------------------------------------------


class _FakeHealthStore:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def report(self) -> list[dict[str, object]]:
        return self._rows


def test_latency_view_maps_rows_and_honest_history() -> None:
    store = _FakeHealthStore(
        [
            {
                "model_id": "axon-gemini",
                "state": "ok",
                "consecutive_fails": 0,
                "latency_ms": 2345,
                "ema_ms": 2501,
                "samples": 12,
                "last_error": "",
                "last_ok_at": "2026-09-18T01:00:00+00:00",
            },
            {
                "model_id": "qian-gemini",
                "state": "temporarily_unavailable",
                "consecutive_fails": 3,
                "latency_ms": None,
                "ema_ms": None,
                "samples": 4,
                "last_error": "HTTP 401: ws://127.0.0.1:3001/?access_token=SUPERSECRET bad",
                "last_ok_at": "",
            },
        ]
    )
    result = latency_view(store)
    assert result["status"] == "ok"
    assert result["source"] == "channel_health"
    data = result["data"]
    assert [item["channel"] for item in data["items"]] == ["axon-gemini", "qian-gemini"]
    assert data["items"][0]["ema_ms"] == 2501
    assert data["items"][0]["state"] == "ok"
    # 历史曲线无存储：显式不可用原因，绝不造历史点。
    assert data["history"] == {"status": "unavailable", "reason": "not_persisted"}
    text = json.dumps(data, ensure_ascii=False)
    assert "SUPERSECRET" not in text
    assert "access_token=[redacted]" in text


def test_latency_view_without_store_is_honest() -> None:
    assert latency_view(None) == {
        "status": "source_unavailable",
        "reason": "not_connected",
        "data": None,
    }


def test_latency_view_store_failure_is_contained() -> None:
    class Broken:
        def report(self):
            raise sqlite3.Error("boom")

    result = latency_view(Broken())
    assert result["status"] == "source_unavailable"
    assert result["reason"] == "read_failed"
    assert "boom" not in json.dumps(result)


# ---------------------------------------------------------------------------
# affinity/board —— 显数值好感榜
# ---------------------------------------------------------------------------


@pytest.fixture
def affinity_db(tmp_path: Path) -> Path:
    from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
        DynamicAffinityStore,
    )

    path = tmp_path / "user_affinity.sqlite3"
    store = DynamicAffinityStore(path)
    # 建表连接收口，WAL 落盘（测试种子专用）；惰性句柄可为 None，先断言。
    assert store._connection is not None
    store._connection.close()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executemany(
            "INSERT INTO user_affinity (sender_id, affinity, nickname,"
            " interaction_count, updated_at) VALUES (?, ?, ?, ?, ?)",
            [
                ("10001", 0.853, "澜汐", 42, "2026-09-18T00:00:00+00:00"),
                ("10002", -0.2, "", 3, "2026-09-17T00:00:00+00:00"),
                ("10003", 0.1, "小岸", 7, "2026-09-16T00:00:00+00:00"),
            ],
        )
    return path


def test_affinity_board_desc_displays_numeric_scores(affinity_db: Path) -> None:
    result = AffinityBoardService(affinity_db).board()
    assert result["status"] == "ok"
    assert result["source"] == "user_affinity"
    data = result["data"]
    assert data["order"] == "desc"
    assert data["total"] == 3
    top = data["items"][0]
    assert top["sender_id"] == "10001"
    assert top["nickname"] == "澜汐"
    assert top["score"] == 85.3
    assert top["affinity"] == pytest.approx(0.853)
    assert top["tier"] == 3
    assert top["tier_name"] == "独一份"
    assert top["interaction_count"] == 42
    scores = [row["score"] for row in data["items"]]
    assert scores == sorted(scores, reverse=True)


def test_affinity_board_asc_and_limit(affinity_db: Path) -> None:
    data = AffinityBoardService(affinity_db).board(order="asc", limit=2)["data"]
    assert data["order"] == "asc"
    assert len(data["items"]) == 2
    assert data["total"] == 3
    bottom = data["items"][0]
    assert bottom["sender_id"] == "10002"
    assert bottom["score"] == -20.0
    assert bottom["tier"] == -1
    assert bottom["tier_name"] == "稍淡"
    assert bottom["nickname"] == ""


def test_affinity_board_read_only_never_mutates(affinity_db: Path) -> None:
    before = affinity_db.read_bytes()
    AffinityBoardService(affinity_db).board()
    assert affinity_db.read_bytes() == before


@pytest.mark.parametrize("limit", [0, 201, True, 1.5, "5", None])
def test_affinity_board_invalid_limit(affinity_db: Path, limit) -> None:
    result = AffinityBoardService(affinity_db).board(limit=limit)
    assert result == {"status": "invalid_request", "reason": "invalid_limit", "data": None}


@pytest.mark.parametrize("order", ["sideways", "DESC", "", None])
def test_affinity_board_closed_order_enum(affinity_db: Path, order) -> None:
    result = AffinityBoardService(affinity_db).board(order=order)
    assert result == {"status": "invalid_request", "reason": "invalid_order", "data": None}


def test_affinity_board_missing_source_never_creates(tmp_path: Path) -> None:
    path = tmp_path / "nope" / "user_affinity.sqlite3"
    result = AffinityBoardService(path).board()
    assert result["status"] == "source_unavailable"
    assert result["data"] is None
    assert not path.parent.exists()
