"""审计身份链（台账 D1–D4）：平台 / 群或频道 / 用户ID / 昵称 的落库与只读透出。

背景（本文件锁的四条判据）：

1. 摄取层**本来就有** ``platform`` / ``group_id`` / ``group_title`` /
   ``sender_nickname``（``domains/core/contracts/runtime.py::IncomingMessage``），
   但它们此前只进 LLM 提示词（``capabilities/chat.py`` 的画像分区），**从不落库**
   ⇒ ``audit_records`` 只有 10 列，WebUI 无法回答"哪条消息来自哪个群、谁发的"。
2. 迁移必须**幂等可重跑**：生产库在 ``ChatBot_Runtime/data/wuwa_audit.sqlite3``，
   本席只改代码、不改生产库；真正执行 ``ALTER TABLE`` 的是 bot 重启后的首次写入。
   SQLite 没有 ``ADD COLUMN IF NOT EXISTS``，判据是 ``PRAGMA table_info`` 后按缺失补。
3. 旧行（迁移前写入的）四列必为 NULL ⇒ 读接口回 ``None``，**不得**回空串冒充"已采集"。
   前端据此显示「未采集」。
4. 纯函数/仓库层口径：``""`` 一律归 ``None``（群名片/昵称 strip 后为空 = 没采集到）。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from plugins.bot_unified_runtime.control_plane.webui_stats import AuditCallStatsService
from plugins.bot_unified_runtime.domains.chat_reply.runtime import pipeline as pipeline_module
from plugins.bot_unified_runtime.domains.core.contracts import (
    AuditRecord,
    IncomingMessage,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.audit.logger import SQLiteAuditRepository

_LEGACY_DDL = """
CREATE TABLE audit_records (
    audit_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    event TEXT NOT NULL,
    severity TEXT NOT NULL,
    public_message TEXT NOT NULL,
    private_debug TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

IDENTITY_COLUMNS = ("platform", "group_id", "group_title", "sender_nickname")


def _record(*, request_id: str = "req-1", session_id: str = "group_777_10001", created: datetime | None = None):
    return AuditRecord(
        request_id=request_id,
        session_id=session_id,
        capability_id="bot.chat",
        stage="runtime",
        event="capability_done",
        severity=RiskLevel.LOW,
        public_message="ok",
        private_debug="",
        created_at=created or datetime.now(timezone.utc),
    )


def _message(**overrides) -> IncomingMessage:
    base = dict(
        request_id="req-1",
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="group_777_10001",
        session_type=SessionType.GROUP,
        sender_id="10001",
        sender_nickname="阿岚",
        sender_display_name="阿岚",
        group_id="777",
        group_title="守岸人测试群",
    )
    base.update(overrides)
    return IncomingMessage(**base)


def _legacy_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(_LEGACY_DDL)


def _columns(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as connection:
        return [str(row[1]) for row in connection.execute("PRAGMA table_info(audit_records)")]


# ---------------------------------------------------------------------------
# 1. 契约层：字段存在且缺省 None（旧构造点一字不改也不炸）
# ---------------------------------------------------------------------------


def test_audit_record_identity_fields_default_to_none():
    record = _record()
    for name in IDENTITY_COLUMNS:
        assert getattr(record, name) is None


def test_audit_record_carries_identity_fields():
    """走真构造器（StrictBaseModel：多余/未知键会被拒，故这测的是真字段）。"""
    record = AuditRecord(
        request_id="req-1",
        session_id="group_777_10001",
        capability_id="bot.chat",
        stage="runtime",
        event="capability_done",
        severity=RiskLevel.LOW,
        public_message="ok",
        private_debug="",
        platform="qq",
        group_id="777",
        group_title="守岸人测试群",
        sender_nickname="阿岚",
    )
    assert (record.platform, record.group_id, record.group_title, record.sender_nickname) == (
        "qq",
        "777",
        "守岸人测试群",
        "阿岚",
    )


# ---------------------------------------------------------------------------
# 2. 迁移：旧 10 列库 → 首次写入补 4 列；重复执行不炸
# ---------------------------------------------------------------------------


def test_repository_migrates_legacy_table_on_first_write(tmp_path: Path):
    db = tmp_path / "audit.sqlite3"
    _legacy_db(db)
    assert "platform" not in _columns(db)

    SQLiteAuditRepository(db).append(_record())

    columns = _columns(db)
    for name in IDENTITY_COLUMNS:
        assert name in columns


def test_repository_migration_is_idempotent_across_instances(tmp_path: Path):
    db = tmp_path / "audit.sqlite3"
    _legacy_db(db)
    SQLiteAuditRepository(db).append(_record(request_id="req-a"))
    # 第二个实例 = 重启后的下一次进程；_ensure_schema 会再跑一遍 ALTER 腿。
    repo = SQLiteAuditRepository(db)
    repo.append(_record(request_id="req-b"))
    repo.append(_record(request_id="req-c"))

    columns = _columns(db)
    assert len(columns) == 14
    assert len([name for name in columns if name == "platform"]) == 1


def test_repository_roundtrips_identity_fields(tmp_path: Path):
    db = tmp_path / "audit.sqlite3"
    record = _record().model_copy(
        update={
            "platform": "qq",
            "group_id": "777",
            "group_title": "守岸人测试群",
            "sender_nickname": "阿岚",
        }
    )
    SQLiteAuditRepository(db).append(record)

    restored = SQLiteAuditRepository(db).list_records("req-1")[0]
    assert (
        restored.platform,
        restored.group_id,
        restored.group_title,
        restored.sender_nickname,
    ) == ("qq", "777", "守岸人测试群", "阿岚")


def test_legacy_rows_read_back_as_uncollected(tmp_path: Path):
    """迁移前写入的旧行：四列 NULL（读回 None，不是空串）。"""
    db = tmp_path / "audit.sqlite3"
    _legacy_db(db)
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute(
            "INSERT INTO audit_records VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "audit_old",
                "req-old",
                "group_777_10001",
                "bot.chat",
                "runtime",
                "capability_done",
                "low",
                "ok",
                "",
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    records = SQLiteAuditRepository(db).list_records("req-old")

    assert len(records) == 1
    for name in IDENTITY_COLUMNS:
        assert getattr(records[0], name) is None


# ---------------------------------------------------------------------------
# 3. 写入侧：从入站消息取身份（strip 后为空 → None）
# ---------------------------------------------------------------------------


def test_identity_from_message_uses_real_ingest_shape():
    identity = pipeline_module.audit_identity_from_message(_message())

    assert identity == {
        "platform": "qq",
        "group_id": "777",
        "group_title": "守岸人测试群",
        "sender_nickname": "阿岚",
    }


def test_identity_from_message_nullifies_blank_fields():
    identity = pipeline_module.audit_identity_from_message(
        _message(group_id=None, group_title="   ", sender_nickname="")
    )

    assert identity["group_id"] is None
    assert identity["group_title"] is None
    assert identity["sender_nickname"] is None


def test_append_audit_safely_merges_identity_for_matching_request():
    class _Logger:
        def __init__(self) -> None:
            self.records: list[AuditRecord] = []

        def append(self, record: AuditRecord) -> AuditRecord:
            self.records.append(record)
            return record

    stub = type("_Stub", (), {"audit_logger": _Logger()})()
    pipeline_module.remember_audit_identity(_message())

    pipeline_module.RuntimePipeline._append_audit_safely(stub, _record(request_id="req-1"))

    stored = stub.audit_logger.records[0]
    assert (stored.platform, stored.group_id, stored.group_title, stored.sender_nickname) == (
        "qq",
        "777",
        "守岸人测试群",
        "阿岚",
    )


def test_append_audit_safely_ignores_identity_of_another_request():
    """跨请求串味是不可接受的错误方向：宁可留 None，也不许贴错人。"""

    class _Logger:
        def __init__(self) -> None:
            self.records: list[AuditRecord] = []

        def append(self, record: AuditRecord) -> AuditRecord:
            self.records.append(record)
            return record

    stub = type("_Stub", (), {"audit_logger": _Logger()})()
    pipeline_module.remember_audit_identity(_message(request_id="req-other"))

    pipeline_module.RuntimePipeline._append_audit_safely(stub, _record(request_id="req-1"))

    stored = stub.audit_logger.records[0]
    assert stored.sender_nickname is None
    assert stored.group_id is None


# ---------------------------------------------------------------------------
# 4. 只读透出：stats/calls 的 identity 块
# ---------------------------------------------------------------------------


def _seed(path: Path, rows: list[AuditRecord]) -> None:
    repo = SQLiteAuditRepository(path)
    for row in rows:
        repo.append(row)


def _identity_seed(now: datetime) -> list[AuditRecord]:
    return [
        _record(session_id="group_777_10001", created=now).model_copy(
            update={
                "platform": "qq",
                "group_id": "777",
                "group_title": "守岸人测试群",
                "sender_nickname": "阿岚",
            }
        ),
        _record(session_id="group_777_10002", created=now).model_copy(
            update={
                "platform": "qq",
                "group_id": "777",
                "group_title": "守岸人测试群",
                "sender_nickname": "第二个人",
            }
        ),
        _record(session_id="private_10001", created=now).model_copy(
            update={"platform": "telegram", "sender_nickname": "私聊的人"}
        ),
    ]


def test_stats_calls_exposes_identity_block(tmp_path: Path):
    db = tmp_path / "audit.sqlite3"
    _seed(db, _identity_seed(datetime.now(timezone.utc)))

    result = AuditCallStatsService(db).calls(window="24h", limit=10)

    assert result["status"] == "ok"
    identity = result["data"]["identity"]
    assert identity["available"] is True
    assert set(identity["fields"]["collected"]) == set(IDENTITY_COLUMNS)
    assert identity["fields"]["uncollected"] == []

    group = next(row for row in identity["sessions"] if row["group_id"] == "777")
    assert group["platform"] == "qq"
    assert group["group_title"] == "守岸人测试群"
    assert group["kind"] == "group"
    assert group["calls"] == 2
    assert group["users"] == [
        {"user_id": "10001", "sender_nickname": "阿岚", "calls": 1},
        {"user_id": "10002", "sender_nickname": "第二个人", "calls": 1},
    ]

    private = next(row for row in identity["sessions"] if row["kind"] == "private")
    assert private["user_id"] == "10001"
    assert private["group_id"] is None
    assert private["users"] == [{"user_id": "10001", "sender_nickname": "私聊的人", "calls": 1}]


def test_stats_calls_marks_identity_unavailable_on_legacy_schema(tmp_path: Path):
    """迁移没跑到（旧库/旧进程）时：如实报 unavailable + 未采集清单，不填空串。"""
    db = tmp_path / "audit.sqlite3"
    _legacy_db(db)
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute(
            "INSERT INTO audit_records VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "audit_old",
                "req-old",
                "group_777_10001",
                "bot.chat",
                "runtime",
                "capability_done",
                "low",
                "ok",
                "",
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    result = AuditCallStatsService(db).calls(window="24h", limit=10)

    identity = result["data"]["identity"]
    assert identity["available"] is False
    assert identity["fields"]["collected"] == []
    assert set(identity["fields"]["uncollected"]) == set(IDENTITY_COLUMNS)
    # 旧行仍要能被看见（session/user 派生不变），身份四件套里**列**给 None；
    # 群号可由 session 约定派生（下面单独一条锁它），并标 source=session_id。
    session = identity["sessions"][0]
    assert session["platform"] is None
    assert session["group_id"] == "777"
    assert session["group_id_source"] == "session_id"
    assert session["group_title"] is None
    assert session["kind"] == "group"


def test_stats_calls_derives_group_id_from_session_when_column_missing(tmp_path: Path):
    """群号在 session 键里本来就写着（`group_<gid>_<uid>` 是 OneBot 稳定约定）。

    生产库 1000 行（迁移前）全是这种方式记的群：列里没有、键里有。这是**派生**不是编造，
    接口用 `group_id_source` 把来源标出来（`audit_column` vs `session_id`），
    前端与报表都能分辨"库里记的"和"从键推的"。
    """
    db = tmp_path / "audit.sqlite3"
    _seed(db, [_record(session_id="group_777_10001")])

    identity = AuditCallStatsService(db).calls(window="24h", limit=10)["data"]["identity"]
    session = identity["sessions"][0]

    assert session["group_id"] == "777"
    assert session["group_id_source"] == "session_id"


def test_stats_calls_prefers_audit_column_over_derivation(tmp_path: Path):
    db = tmp_path / "audit.sqlite3"
    _seed(
        db,
        [
            _record(session_id="group_777_10001").model_copy(
                update={"platform": "qq", "group_id": "999", "group_title": "库里的群名"}
            )
        ],
    )

    identity = AuditCallStatsService(db).calls(window="24h", limit=10)["data"]["identity"]
    session = identity["sessions"][0]

    assert session["group_id"] == "999"
    assert session["group_id_source"] == "audit_column"


def test_stats_calls_identity_not_polluted_by_window_outside_rows(tmp_path: Path):
    db = tmp_path / "audit.sqlite3"
    now = datetime.now(timezone.utc)
    _seed(
        db,
        [
            _record(session_id="group_777_10001", created=now - timedelta(days=10)).model_copy(
                update={"platform": "qq", "group_id": "777", "sender_nickname": "旧人"}
            ),
            _record(session_id="group_888_10003", created=now).model_copy(
                update={"platform": "qq", "group_id": "888", "sender_nickname": "新人"}
            ),
        ],
    )

    result = AuditCallStatsService(db).calls(window="24h", limit=10)

    identity = result["data"]["identity"]
    assert [row["group_id"] for row in identity["sessions"]] == ["888"]
