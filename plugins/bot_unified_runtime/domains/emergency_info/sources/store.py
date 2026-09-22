"""紧急信息 SQLite 存储（本地持久层：幂等落库 + 状态裁决 + 订阅规则 + 保留期裁剪）。

样板出处（九个统一自证）：
- 库文件形态=「每操作独立连接的轻量 SQLite 库」，抄
  `domains/assistant/campus/campus_store.py:30-42`（`CampusStore`）；
- 采集侧幂等键 = `(source_id, external_id)` UNIQUE，抄 E5 §4.3 的口径
  （campus 用 `message_id TEXT PRIMARY KEY` 同族思路，`campus_store.py:17`）；
- 状态 CHECK 约束与「只从 pending 转正」的 SQL 守卫，抄
  `domains/chat_reply/character/quirks.py:157-176`（建表 CHECK）与
  `:292-300`（`UPDATE ... WHERE quirk_id=? AND status='pending_review'`）；
- `date_key` 列 + 保留期裁剪防无界增长，抄 `campus_store.py:23-26/:101-109`；
- 缺省库路径经 `scripts/runtime_paths.py` 重映射到 Runtime 数据根，抄
  `domains/chat_reply/character/persona_service.py:738-752`
  （`build_persona_service`：`db_path is None → runtime_path(DEFAULT_DB_PATH)`），
  对应铁律 6 与 `bot_campus_db_path` 先例（config.py:424 + path_fields :1161）。

本模块绝不发送任何对外消息，也绝不 import LLM/网络面。
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
    as_utc,
    build_emergency_item,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    date_key_of,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.subscriptions import (
    DEFAULT_RADIUS_KM,
    VALID_SCOPES,
    SubscriptionRule,
)

#: 缺省库路径（相对 `data/`，装配时必须经 `runtime_path` 重映射，不得落源码树）。
DEFAULT_DB_PATH = "data/emergency_info.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS emergency_items (
    item_id     TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    color_label TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    expires_at  TEXT,
    date_key    TEXT NOT NULL,
    level       TEXT,
    credibility REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewed_by TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    latitude  REAL,
    longitude REAL,
    category_id TEXT NOT NULL DEFAULT '',
    magnitude REAL,
    depth_km  REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_emergency_items_source
    ON emergency_items(source_id, external_id);
CREATE INDEX IF NOT EXISTS idx_emergency_items_status
    ON emergency_items(status, occurred_at);
CREATE INDEX IF NOT EXISTS idx_emergency_items_date
    ON emergency_items(date_key);
-- 订阅规则（WIRE-SUB）：一个目标一条规则，群/私聊同表不同 scope，主键即 `scope:id`。
-- 目标是「谁显式设过」而不是「谁在 .env 名单里」⇒ 设立动作本身就是显式授权，
-- 绝不猜群/猜人这条不变（群内命令带自身群号，私聊带自身 QQ 号）。
-- `last_matched_at`/`match_count` 是观测面：本项目烧过两次"配了但不生效、没人知道"
-- （死配置键 `auto_approve_sources`、`nmc_alarm` 写成模块名），所以"从没命中过"
-- 必须能在 `紧急信息 订阅 看` 里被看见，而不是靠用户猜。
CREATE TABLE IF NOT EXISTS emergency_subscriptions (
    target_key      TEXT PRIMARY KEY,
    target_scope    TEXT NOT NULL
        CHECK (target_scope IN ('group', 'private')),
    target_id       TEXT NOT NULL,
    created_by      TEXT NOT NULL DEFAULT '',
    levels          TEXT NOT NULL DEFAULT '',
    kinds           TEXT NOT NULL DEFAULT '',
    categories      TEXT NOT NULL DEFAULT '',
    area_name       TEXT NOT NULL DEFAULT '',
    latitude        REAL,
    longitude       REAL,
    radius_km       REAL NOT NULL DEFAULT 200,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_matched_at TEXT,
    match_count     INTEGER NOT NULL DEFAULT 0
);
"""

#: 存量库补列用（家规=「ALTER-if-missing 自动迁移」，先例 character/affinity 三列）。
#: WP3（2026-09-21 全谱重做）新增三列，全部**只加列不改语义**：
#: - `category_id`：注册表稳定类别 id（空=没认出来，与"没有类别"是两件事）；
#: - `magnitude`/`depth_km`：源侧震级/深度数值，地震族定级唯一输入（缺数＝不出档）。
_ITEM_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("latitude", "REAL"),
    ("longitude", "REAL"),
    ("category_id", "TEXT NOT NULL DEFAULT ''"),
    ("magnitude", "REAL"),
    ("depth_km", "REAL"),
)

#: 订阅表 WP3 新增列：注册表派生的类别 id 集合（逗号拼，与 levels/kinds 同族形态）。
_SUBSCRIPTION_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("categories", "TEXT NOT NULL DEFAULT ''"),
)

_SELECT_COLUMNS = (
    "item_id, source_id, source_kind, external_id, title, body, url, "
    "color_label, occurred_at, fetched_at, expires_at, level, credibility, "
    "status, reviewed_by, reviewed_at, latitude, longitude, "
    "category_id, magnitude, depth_km"
)


def _format_utc(moment: datetime) -> str:
    """统一落库格式（UTC ISO，字典序即时间序）；naive 视作 UTC。

    逐字同构 `quirks.py:57-62 _format_utc`。
    """
    return as_utc(moment).isoformat()


def _row_to_item(row: sqlite3.Row) -> EmergencyItem | None:
    """行 → 条目；库里存量行不合契约时返回 None（D-1：不硬凑）。

    `date_key` 是本表的裁剪辅助列，不属于契约，故不塞进 payload。
    """
    payload = {key: value for key, value in dict(row).items() if key != "date_key"}
    if payload.get("level") in (None, ""):
        payload["level"] = None
    if payload.get("status") in (None, ""):
        payload["status"] = EmergencyStatus.PENDING.value
    return build_emergency_item(payload)


def _ensure_columns(
    connection: sqlite3.Connection, table: str, columns: tuple[tuple[str, str], ...]
) -> None:
    """缺哪列补哪列（幂等）——本仓「ALTER-if-missing 自动迁移」家规的唯一执行口。

    为什么必须有：`_SCHEMA` 用 `CREATE TABLE IF NOT EXISTS`，对已存在的旧库
    不会加列，而 `_SELECT_COLUMNS` 一旦点名新列就会让**每次读**都抛
    `no such column`——库一旦在生产里建过就永久不可用。家规先例=affinity 三列自动迁移。
    """
    existing = {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
    }
    for name, sql_type in columns:
        if existing and name not in existing:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"
            )


def _ensure_item_coordinate_columns(connection: sqlite3.Connection) -> None:
    """存量库补 WP3 三列（`category_id`/`magnitude`/`depth_km`）+ 既有两枚坐标列。"""
    _ensure_columns(connection, "emergency_items", _ITEM_EXTRA_COLUMNS)


def _ensure_subscription_fact_columns(connection: sqlite3.Connection) -> None:
    """存量订阅表补 `categories` 列（注册表派生的类别 id，见 `_SUBSCRIPTION_EXTRA_COLUMNS`）。"""
    _ensure_columns(connection, "emergency_subscriptions", _SUBSCRIPTION_EXTRA_COLUMNS)


def _split_terms(raw: object) -> frozenset[str]:
    return frozenset(token for token in str(raw or "").split(",") if token)


def _parse_utc(raw: object) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _row_to_rule(row: sqlite3.Row) -> SubscriptionRule | None:
    """行 → 规则；库里存量行不合形态 ⇒ None（D-1 同型：不硬凑一条假规则去投递）。

    半个坐标（只有纬度或只有经度）同样判 None：半径匹配拿残缺坐标算出来的距离
    是假的，比不投更糟。
    """
    payload = dict(row)
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    if (latitude is None) != (longitude is None):
        return None
    scope = str(payload.get("target_scope") or "")
    target = str(payload.get("target_id") or "")
    if scope not in VALID_SCOPES or not target:
        return None
    try:
        return SubscriptionRule(
            target_scope=scope,
            target_id=target,
            levels=_split_terms(payload.get("levels")),
            kinds=_split_terms(payload.get("kinds")),
            categories=_split_terms(payload.get("categories")),
            area_name=str(payload.get("area_name") or ""),
            latitude=None if latitude is None else float(latitude),
            longitude=None if longitude is None else float(longitude),
            radius_km=float(payload.get("radius_km") or DEFAULT_RADIUS_KM),
            created_by=str(payload.get("created_by") or ""),
            last_matched_at=_parse_utc(payload.get("last_matched_at")),
            match_count=int(payload.get("match_count") or 0),
        )
    except (TypeError, ValueError):
        return None


class EmergencyStore:
    """紧急信息库：条目幂等落库 + 审核裁决写入 + 按状态读回 + 订阅规则读写 + 保留期裁剪。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            _ensure_item_coordinate_columns(connection)
            _ensure_subscription_fact_columns(connection)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """一次操作一条连接，**出口必关**。

        `sqlite3` 的 `with conn` 只 commit 不 close——采集轮询 + 每分钟投递现读订阅
        会把句柄按调用次数累积，Windows 上直接表现为临时库删不掉、库文件被占。
        """
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    # ------------------------------------------------------------ 写入

    def upsert_item(self, item: EmergencyItem) -> bool:
        """幂等插入：同 item_id 或同 (source_id, external_id) 重复 ⇒ False 不覆盖。

        采集器重跑、SnowLuma 重连重发同一事件都只会落一次（同 campus 的
        message_id 幂等语义）；本函数**不做**「重复即更新」，因为紧急条目的
        状态一旦被重复导入覆盖回 pending，等于把已过审条目悄悄撤回，风险更大。
        """
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO emergency_items (
                        item_id, source_id, source_kind, external_id,
                        title, body, url, color_label,
                        occurred_at, fetched_at, expires_at, date_key,
                        level, credibility, status, reviewed_by, reviewed_at,
                        latitude, longitude,
                        category_id, magnitude, depth_km
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.item_id,
                        item.source_id,
                        item.source_kind,
                        item.external_id,
                        item.title,
                        item.body,
                        item.url,
                        item.color_label,
                        _format_utc(item.occurred_at),
                        _format_utc(item.fetched_at),
                        _format_utc(item.expires_at) if item.expires_at else None,
                        date_key_of(item.occurred_at),
                        item.level.value if item.level is not None else None,
                        float(item.credibility),
                        item.status.value,
                        item.reviewed_by,
                        _format_utc(item.reviewed_at) if item.reviewed_at else None,
                        item.latitude,
                        item.longitude,
                        item.category_id,
                        item.magnitude,
                        item.depth_km,
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return cursor.rowcount > 0

    def apply_review(
        self,
        item_id: str,
        *,
        target: EmergencyStatus,
        reviewer_id: str,
        at: datetime,
    ) -> bool:
        """状态裁决：只改 pending 行（守卫与 quirks.approve 同型）。"""
        if target is EmergencyStatus.PENDING:
            return False
        reviewer = str(reviewer_id or "").strip()
        if not reviewer:
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE emergency_items SET status = ?, reviewed_by = ?, reviewed_at = ?"
                " WHERE item_id = ? AND status = 'pending'",
                (target.value, reviewer, _format_utc(at), str(item_id or "").strip()),
            )
        return cursor.rowcount > 0

    def set_level(
        self,
        item_id: str,
        *,
        level: EmergencyLevel,
        category_id: str | None = None,
    ) -> bool:
        """把定级结果（与注册表类别）写回库：仅过审条目可写（D-8 的存储侧守卫）。

        WP3（审计 E6-N3）：这一函数此前**生产零调用**，库里 `level` 恒 NULL，于是
        同一条目两副面孔——投递出去「【红色预警】…」、`紧急信息 <id>` 查到「未定级」。
        回写口现已由 `EmergencyInfoService.approved_items` 每轮调用（幂等：值没变不写），
        查询侧与投递侧因此同源同值。`category_id=None`＝不改这一列（与"改成空串"分别）。
        """
        wanted = str(category_id or "").strip() if category_id is not None else None
        params: list[object] = [level.value]
        clauses = ["level = ?"]
        if wanted is not None:
            clauses.insert(0, "category_id = ?")
            params.insert(0, wanted)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE emergency_items SET " + ", ".join(clauses) +
                " WHERE item_id = ? AND status = 'approved'",
                (*params, str(item_id or "").strip()),
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------ 读回

    def get(self, item_id: str) -> EmergencyItem | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM emergency_items WHERE item_id = ?",
                (str(item_id or "").strip(),),
            ).fetchone()
        return None if row is None else _row_to_item(row)

    def list_by_status(
        self, status: EmergencyStatus, *, limit: int = 50
    ) -> list[EmergencyItem]:
        """按状态读回（新→旧）；limit 非正即空表，不放开成全表扫描。"""
        cap = int(limit)
        if cap <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM emergency_items"
                " WHERE status = ? ORDER BY occurred_at DESC, rowid DESC LIMIT ?",
                (status.value, cap),
            ).fetchall()
        items = [_row_to_item(row) for row in rows]
        return [item for item in items if item is not None]

    # ------------------------------------------------ 订阅规则（WIRE-SUB）

    def save_subscription(self, rule: SubscriptionRule, *, at: datetime) -> bool:
        """落一条订阅：同目标已有即**整体覆盖**，返回 True=新建 / False=覆盖更新。

        与 `upsert_item` 的「重复即拒」刻意相反：投递规则被再次设立就是用户的改口，
        留着旧的才是不正常；而「一个目标一条」由主键 `target_key` 结构性保证，
        不存在两条规则同时生效、更难解释谁赢的问题。
        """
        moment = _format_utc(at)
        values = (
            rule.target_key,
            rule.target_scope,
            rule.target_id,
            rule.created_by,
            ",".join(sorted(rule.levels)),
            ",".join(sorted(rule.kinds)),
            ",".join(sorted(rule.categories)),
            rule.area_name,
            rule.latitude,
            rule.longitude,
            float(rule.radius_km),
            moment,
            moment,
        )
        with self._connect() as connection:
            existed = (
                connection.execute(
                    "SELECT 1 FROM emergency_subscriptions WHERE target_key = ?",
                    (rule.target_key,),
                ).fetchone()
                is not None
            )
            connection.execute(
                """
                INSERT INTO emergency_subscriptions (
                    target_key, target_scope, target_id, created_by,
                    levels, kinds, categories, area_name, latitude, longitude,
                    radius_km, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(target_key) DO UPDATE SET
                    levels = excluded.levels,
                    kinds = excluded.kinds,
                    categories = excluded.categories,
                    area_name = excluded.area_name,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    radius_km = excluded.radius_km,
                    created_by = excluded.created_by,
                    updated_at = excluded.updated_at
                """,
                values,
            )
        return not existed

    def get_subscription(self, target_key: str) -> SubscriptionRule | None:
        key = str(target_key or "").strip()
        if not key:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM emergency_subscriptions WHERE target_key = ?", (key,)
            ).fetchone()
        return None if row is None else _row_to_rule(row)

    def list_subscriptions(self) -> list[SubscriptionRule]:
        """全部生效规则（投递侧每轮现读 ⇒ 群里设完当轮即生效，不等重启）。"""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM emergency_subscriptions ORDER BY updated_at DESC"
            ).fetchall()
        rules = [_row_to_rule(row) for row in rows]
        return [rule for rule in rules if rule is not None]

    def delete_subscription(self, target_key: str) -> bool:
        """退订：删行（裁定 5.A「永久直到退订」的对偶——没有"暂停"这个态）。"""
        key = str(target_key or "").strip()
        if not key:
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM emergency_subscriptions WHERE target_key = ?", (key,)
            )
        return cursor.rowcount > 0

    def note_subscription_match(self, target_key: str, *, at: datetime) -> None:
        """记一次命中（观测面）：投递侧唯一写入点，**失败不影响投递本身**。

        头注此前是空话（函数体无 try，一次 sqlite 生病会被 job 的兜底 except 放大成
        「本轮剩余条目与目标全部不发」＝漏报）。现在记账失败只降级为一行日志：
        「没记上账」和「没投出去」是两件事，前者绝不许变成后者（审计 E6-N4 同族面）。
        """
        key = str(target_key or "").strip()
        if not key:
            return
        try:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE emergency_subscriptions"
                    " SET last_matched_at = ?, match_count = match_count + 1"
                    " WHERE target_key = ?",
                    (_format_utc(at), key),
                )
        except Exception:
            logging.getLogger(__name__).warning(
                "emergency subscription match accounting failed: target=%s",
                key[:64],
                exc_info=True,
            )

    # ------------------------------------------------------------ 卫生

    def prune(self, *, keep_days: int = 90, now: datetime | None = None) -> int:
        """删除保留期外的旧**条目**，返回删除条数（防库无界增长，抄 campus 同族）。

        只裁 `emergency_items`：订阅是用户显式设的活规则，裁掉等于悄悄让一个群
        停止接收紧急播报（裁定 5.A「永久直到退订」），故本函数结构性不碰它。
        """
        current = (now or datetime.now().astimezone()).astimezone()
        cutoff = (current - timedelta(days=max(1, int(keep_days)))).date().isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM emergency_items WHERE date_key < ?", (cutoff,)
            )
        return cursor.rowcount


def build_emergency_store(db_path: str | Path | None = None) -> EmergencyStore:
    """装配入口：缺省路径经 `runtime_path` 重映射到 Runtime 数据根（不入源码树）。

    逐字同构 `persona_service.py:738-752`。配置键 `bot_emergency_info_db_path`
    属 B8/B9 合流席的 config.py 落地请求（且必须进 `path_fields` 重映射表）。
    """
    if db_path is None:
        from scripts.runtime_paths import runtime_path

        db_path = runtime_path(DEFAULT_DB_PATH)
    return EmergencyStore(db_path)


__all__ = [
    "DEFAULT_DB_PATH",
    "EmergencyStore",
    "build_emergency_store",
]
