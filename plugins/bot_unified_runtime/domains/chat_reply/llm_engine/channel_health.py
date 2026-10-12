"""模型渠道健康巡检（暂不可用标注与故障转移隔离）。

需求背景：同一模型常有多个渠道（供应商）；渠道可能临时停用某模型。
定时探针（默认每小时）对每个注册渠道做一次最小真实调用：

- 成功 → 记录延迟，清除不可用标记；
- 失败（连接/401/404/模型不存在）→ 标记 ``temporarily_unavailable``，
  ModelRouter 在故障转移队列中跳过它们；**永不自动删除**，只有管理员
  手动 remove 才删除（临时停用可能恢复）。

状态存 SQLite（Runtime data），跨重启保留。全部不可用时放行全部候选
（避免整bot瘫痪），由真实调用自身的故障转移兜底。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_UNAVAILABLE = "temporarily_unavailable"
_OK = "ok"
# 连续失败达到该次数才判暂不可用（单次抖动不踢出队列）。
_UNAVAILABLE_AFTER_FAILS = 2
# 暂不可用后每隔多久重探（秒）；重探成功即自动恢复。
_RETRY_INTERVAL_SECONDS = 1800.0
# EWMA 平滑系数（v2 动态测量）：ema = round(0.3*最近一次 + 0.7*上次平滑)。
_EWMA_ALPHA = 0.3
# 慢渠道识别阈值（毫秒，v2 动态检测）：平滑延迟超过它，巡检报告评级标「偏慢」。
# config bot_channel_slow_ema_ms / env BOT_CHANNEL_SLOW_EMA_MS 可覆盖。
_SLOW_EMA_MS = 15000
# 近期失败冷却缺省（秒，v21r2 R1）：真实调用失败后该渠道在候选队列里降级到
# 队尾的时长（不剔除——与 unavailable 的「30 分钟重探」互补的两档熔断）。
# config bot_chat_channel_cooldown_seconds / env BOT_CHAT_CHANNEL_COOLDOWN_SECONDS 可覆盖。
_DEFAULT_COOLDOWN_SECONDS = 90.0

# 每跳超时地板（秒）——**唯一真身**，三处消费：① 自适应钳制
# `model_router._tighten_timeout` 里的 `max(地板, ema×3)`；② 侧腿交给路由的单跳预算
# （`question_intent.llm_timely_domain_hint`、`sentiment_selector.classify_sticker_sentiment`）；
# ③ 锁 `tests/test_chat_timeout_floor.py`（该锁不再自带数字——改一处漏一处的老病由这枚常量治）。
# 2026-09-27 实弹定档：低于这档不是「响应慢」而是**必然失败**（两跳各 20s 同死、弹失败模板）。
# 2026-10-06 再证 8s 一档同死：本地渠道 ema 被 12-token 截断的微调用喂成 903ms ⇒ 每跳钳到
# 8.0s ⇒ 真回复连首字都等不到，且侧腿用 4s/8s 打满整条链＝系统性制造假超时。账见台账 #80。
PER_HOP_TIMEOUT_FLOOR_SECONDS = 30.0

# 巡检并发/错峰参数（B-2）：config 字段 → os.environ 兜底 → 最终默认。
# 默认值即历史硬编码值（background 3 线程 + 0.4s 抖动；manual 8 线程），
# 行为回归约束：默认参数下现网行为不变。
_PROBE_THREADS_DEFAULT = 3
_PROBE_MANUAL_THREADS_DEFAULT = 8
_PROBE_JITTER_DEFAULT = 0.4
_PROBE_THREADS_MIN = 1
_PROBE_THREADS_MAX = 16
_PROBE_JITTER_MAX = 5.0

# ---- 可用性判据：SQL 两条 + 判定一枚（唯一真身，两条腿共用） ----
# 单候选腿：PK 直查，一趟取回判定要的三列（旧形状是 8 列 _row 之后再补一条
# SELECT last_probe_at ＋每次现开连接，实测 498µs/候选，其中开连 142µs）。
_AVAILABILITY_ONE_SQL = (
    "SELECT model_id, state, last_probe_at FROM channel_health WHERE model_id = ?"
)
# 批查询腿：一枚参数都不绑（候选数不进气泡串 ⇒ 无 SQLITE_MAX_VARIABLE_NUMBER 风险，
# 也不用给 state 另建索引；现库 83 行一趟扫，实测低于 40 候选参数的 IN 串一档）。
_UNAVAILABLE_ROWS_SQL = (
    "SELECT model_id, last_probe_at FROM channel_health WHERE state = ?"
)


def _decide_available(now: datetime, state: Any, last_probe_at: Any) -> bool:
    """「这一路现在能不能走」的**唯一判据真身**（单候选腿与批查询腿同读）。

    逐字段照抄改前 ``is_available`` 的判定顺序，一个字节都没改语义：
    ① 行缺席（state=None）或 state 不是 temporarily_unavailable ⇒ 放行；
    ② last_probe_at 为 NULL/空 ⇒ 放行；
    ③ ``fromisoformat`` 抛 ``ValueError`` ⇒ 放行；
    ④ 否则 age ≥ ``_RETRY_INTERVAL_SECONDS`` 才放行（到点重探放一次）。
    ⚠ 时间戳是 naive 形态时 ``now - last`` 抛的是 ``TypeError``，改前同样不接
    （只 ``except ValueError``）⇒ 这里**故意不补兜底**：它由路由侧
    ``_health_filter_candidates`` 的 ``except Exception`` 收敛成「原列表放行」，
    接住它会改开一条第二判据。锁＝
    ``tests/test_channel_health_v2.py::test_naive_probe_timestamp_raises_on_both_legs``。
    """
    if state != _UNAVAILABLE:
        return True
    if not last_probe_at:
        return True
    try:
        last = datetime.fromisoformat(str(last_probe_at))
        age = (now - last).total_seconds()
    except ValueError:
        return True
    return age >= _RETRY_INTERVAL_SECONDS


class ChannelHealthStore:
    """按 model_id（注册条目 id）记录渠道健康状态。

    连接形状（延迟无用功删除波 2026-10-12，账见台账 #80 同族）：进程内**一条常驻
    连接** + 一把锁串行化，照 ``domains/transport/sender/queue.py::
    SQLiteSendQueue._shared_connection`` 的既有形状做（🔴 本仓不得有第二套连接
    管理真身）。旧形状是「每个方法每次调用现开一条连接、用完 close」——实测单候选
    ``is_available`` 498µs 里 142µs 是开连、40 枚候选 22.3ms、全库 83 枚 40.5ms，
    全是本机往返、与网络无关。
    ``_connect()`` 保留为**唯一**建连原语（只被 ``_shared_connection`` 调），
    ``timeout=10`` 一字未动——那是天花板不是无用功。
    """

    def __init__(self, db_path: str | Any) -> None:
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        # v21r5 config_missing 重复冷却：进程生命周期内每渠道 config_missing
        # 累计计数（内存态、不落库——重启清零即「进程生命周期」语义；SQLite
        # 侧只存冷却截止时刻，由路由侧达到阈值后经 record_failure 落地）。
        self._config_missing_counts: dict[str, int] = {}
        # 常驻连接（queue 同形状）：check_same_thread=False ＋ 独立 RLock，
        # 与 self._lock 分工——_lock 串行化业务操作（语义不变），_connection_lock
        # 只管连接句柄的取用与丢弃，两者不成环（_discard 只在持 _lock 的体内调）。
        self._connection: sqlite3.Connection | None = None
        self._connection_lock = threading.RLock()
        # 建表 DDL 每实例只跑一次（旧形状里每次现连都要重跑一遍 PRAGMA 对照）。
        self._schema_ready = False
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """本模块**唯一**的建连原语（只被 ``_shared_connection`` 调，形状锁钉这条）。

        ``timeout=10`` 一字未动——那是天花板、不是无用功（天花板锁＝
        ``tests/test_chat_timeout_floor.py::
        test_channel_health_refactor_kept_every_timeout_ceiling``）。
        ``check_same_thread=False``：连接跨线程复用（路由跑在线程池上），
        与 ``SQLiteSendQueue._shared_connection`` 同形状；串行化仍由 self._lock 负责。
        """
        return sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)

    def _shared_connection(self) -> sqlite3.Connection:
        """惰性取用进程内长连接（queue 同形状；调用方须已持 self._lock）。"""
        with self._connection_lock:
            if self._connection is None:
                self._connection = self._connect()
            return self._connection

    def _discard_connection(self) -> None:
        """库级损坏/断连时句柄不可复用（queue 同形状）：丢掉，下次调用再惰性重建。"""
        with self._connection_lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
                self._connection = None

    def close(self) -> None:
        """显式收尾口（queue 同形状）：释放常驻连接句柄。

        Windows 上打开的 sqlite 文件不可 unlink——供「实例随临时目录销毁」的调用方
        在清理前收尾。生产走进程级单例，无人调用＝语义零改动。
        """
        self._discard_connection()

    def _fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        """读侧唯一通路：常驻连接 + 业务锁；sqlite3.Error 丢句柄后**原样上抛**。

        上抛而不是吞：旧形状里读失败会一路冒到调用方（路由侧有
        ``except Exception`` 兜底放行），吞掉就改判据了。
        """
        with self._lock:
            try:
                return self._shared_connection().execute(sql, params).fetchall()
            except sqlite3.Error:
                self._discard_connection()
                raise

    def _init_schema(self) -> None:
        with self._lock:
            if self._schema_ready:
                return
            con = self._shared_connection()
            try:
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS channel_health (
                        model_id TEXT PRIMARY KEY,
                        state TEXT NOT NULL,
                        consecutive_fails INTEGER NOT NULL DEFAULT 0,
                        latency_ms INTEGER,
                        ema_ms INTEGER,
                        samples INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT DEFAULT '',
                        last_probe_at TEXT DEFAULT '',
                        last_ok_at TEXT DEFAULT '',
                        updated_at TEXT DEFAULT ''
                    )
                    """
                )
                # 老库无损升级（v2）：PRAGMA table_info 判断后补列，旧数据不动。
                existing = {
                    str(row[1]) for row in con.execute("PRAGMA table_info(channel_health)")
                }
                if "ema_ms" not in existing:
                    con.execute("ALTER TABLE channel_health ADD COLUMN ema_ms INTEGER")
                if "samples" not in existing:
                    con.execute(
                        "ALTER TABLE channel_health ADD COLUMN samples INTEGER NOT NULL DEFAULT 0"
                    )
                # v21r2 R1：近期失败冷却截止时刻（ISO 文本，空=不在冷却）。
                # 落 SQLite 与库同生命周期——重启不丢冷却（比内存方案优）。
                if "cooldown_until" not in existing:
                    con.execute(
                        "ALTER TABLE channel_health ADD COLUMN cooldown_until TEXT DEFAULT ''"
                    )
                con.commit()
                self._schema_ready = True
            except sqlite3.Error:
                self._discard_connection()
                raise

    def _row(self, cur: sqlite3.Cursor, model_id: str) -> dict[str, Any] | None:
        row = cur.execute(
            "SELECT state, consecutive_fails, latency_ms, last_error, last_ok_at,"
            " ema_ms, samples, cooldown_until"
            " FROM channel_health WHERE model_id = ?",
            (model_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "state": row[0],
            "consecutive_fails": int(row[1]),
            "latency_ms": row[2],
            "last_error": row[3] or "",
            "last_ok_at": row[4] or "",
            "ema_ms": row[5],
            "samples": int(row[6] or 0),
            "cooldown_until": row[7] or "",
        }

    def snapshot(self, model_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                return self._row(self._shared_connection().cursor(), model_id)
            except sqlite3.Error:
                self._discard_connection()
                raise

    def is_available(self, model_id: str) -> bool:
        """故障转移队列判据的**单候选腿**：unavailable 且未到重探时间 → False。

        到达重探间隔（30 分钟）放行一次：下一次真实调用/巡检若成功会自动
        恢复 ok 状态；仍失败则继续不可用并刷新探针时间。

        无用功删除波（2026-10-12）：
        ① 旧形状是「一条 8 列 ``_row`` SELECT ＋ 再补一条 ``SELECT last_probe_at``」
        ＋每次现开连接——本腿收敂成**一条窄 SELECT**（model_id/state/last_probe_at）
        打常驻连接，判据逐字段不变（判据真身只剩 ``_decide_available`` 一处）。
        ② 候选队列不再逐枚调本函数——``filter_healthy_candidates`` 走
        ``availability_map`` 的一条批查询；本函数保留给单渠道查询面
        （控制面/管理员侧按枚问「这一路能不能走」）。
        """
        rows = self._fetch_all(_AVAILABILITY_ONE_SQL, (model_id,))
        row = rows[0] if rows else None
        # 缺席行 ⇒ state=None ⇒ _decide_available 放行（与旧形状 row is None 同值）。
        return _decide_available(
            datetime.now(timezone.utc),
            row[1] if row else None,
            row[2] if row else None,
        )

    def availability_map(self, model_ids: list[str]) -> dict[str, bool]:
        """批查询腿（无用功删除波主修项）：一条查询定全部候选的可用性。

        判据与 ``is_available`` **逐字段同值**——两条腿共用 ``_decide_available``
        这一枚真身、读同一组列（state / last_probe_at）；差别只在取行方式
        （一条 vs 每候选一条）。实测：40 候选现连形状 P50 22.3ms → 本腿一条查询
        P50 数十微秒。表里查不到的 model_id 一律判可用（与旧形状
        ``row is None → True`` 同值）。
        """
        # 只捞 unavailable 行：不在结果里 ⇒ 要么缺席、要么 state!='unavailable'
        # ⇒ 两条腿都判放行，无需第二趟查询。
        blocked = {r[0]: r[1] for r in self._fetch_all(_UNAVAILABLE_ROWS_SQL, (_UNAVAILABLE,))}
        now = datetime.now(timezone.utc)
        result: dict[str, bool] = {}
        for model_id in dict.fromkeys(model_ids):  # 去重保序：同 id 只判一次
            if model_id not in blocked:
                result[model_id] = True
            else:
                result[model_id] = _decide_available(now, _UNAVAILABLE, blocked[model_id])
        return result

    def record_success(self, model_id: str, latency_ms: int) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            try:
                con = self._shared_connection()
                cur = con.cursor()
                # EWMA 平滑（v2 动态测量）：无历史平滑值时首测直取，之后
                # ema = 0.3*最近一次 + 0.7*上次平滑；samples 只增不减。
                row = self._row(cur, model_id)
                prev_ema = (row or {}).get("ema_ms")
                samples = int((row or {}).get("samples") or 0)
                if prev_ema is None:
                    ema = latency_ms  # 首测直取
                else:
                    ema = round(_EWMA_ALPHA * latency_ms + (1 - _EWMA_ALPHA) * int(prev_ema))
                con.execute(
                    """
                    INSERT INTO channel_health
                        (model_id, state, consecutive_fails, latency_ms,
                         ema_ms, samples, cooldown_until,
                         last_error, last_probe_at, last_ok_at, updated_at)
                    VALUES (?, ?, 0, ?, ?, ?, '', '', ?, ?, ?)
                    ON CONFLICT(model_id) DO UPDATE SET
                        state='ok', consecutive_fails=0, latency_ms=excluded.latency_ms,
                        ema_ms=excluded.ema_ms, samples=excluded.samples,
                        cooldown_until='',
                        last_error='', last_probe_at=excluded.last_probe_at,
                        last_ok_at=excluded.last_ok_at, updated_at=excluded.updated_at
                    """,
                    (model_id, _OK, latency_ms, ema, samples + 1, now, now, now),
                )
                con.commit()
            except sqlite3.Error:
                self._discard_connection()
                raise

    def record_failure(
        self, model_id: str, error_summary: str, cooldown_seconds: float = 0.0
    ) -> bool:
        """记录一次失败；达到阈值标记暂不可用。返回是否发生了状态翻转。

        v21r2 R1：``cooldown_seconds`` > 0 时同时写入近期失败冷却截止时刻
        （now + cooldown_seconds，UTC ISO）——路由侧把冷却中的渠道降级到候选
        队尾（不剔除）。重复失败会顺延冷却（每次失败重推截止时刻）。
        """
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat(timespec="seconds")
        # ATKLLM-4（P4）：上游 4xx 回显体可能带密钥形态，原样进 SQLite `last_error`
        # 就是**静止存留**——出站总闸覆盖不到 at-rest（备份 / 导库 / 直读 data 根即成
        # 暴露面）。顺序要紧：先过中央打码件、再截断；反过来把 key 切成半截，
        # `_API_KEY_RE` 就不认得了。打码层自身出问题不得挡住健康度落库（fail-open
        # 于「存」），但那时收紧成占位、绝不回落原文（与 persona_profile /
        # safety_exec.paths 的「中央件缺失走保守分支」同调）。延迟导入避开模块级环。
        try:
            from plugins.bot_unified_runtime.domains.render.plain_text import (
                redact_local_secrets,
            )

            safe_summary = redact_local_secrets(str(error_summary or ""))
        except Exception:
            logger.warning("channel_health: 打码层不可用，last_error 落占位", exc_info=True)
            safe_summary = "unavailable (redaction layer failed)"
        cooldown_until = ""
        if cooldown_seconds and cooldown_seconds > 0:
            # 微秒精度：短冷却（测试/小值）在秒级截断下会退化成「已过期」。
            cooldown_until = (now_dt + timedelta(seconds=float(cooldown_seconds))).isoformat()
        flipped = False
        with self._lock:
            try:
                con = self._shared_connection()
                cur = con.cursor()
                row = self._row(cur, model_id)
                fails = (row or {}).get("consecutive_fails", 0) + 1
                state = _UNAVAILABLE if fails >= _UNAVAILABLE_AFTER_FAILS else _OK
                if row is not None and row["state"] != _UNAVAILABLE and state == _UNAVAILABLE:
                    flipped = True
                con.execute(
                    """
                    INSERT INTO channel_health
                        (model_id, state, consecutive_fails, latency_ms,
                         cooldown_until,
                         last_error, last_probe_at, last_ok_at, updated_at)
                    VALUES (?, ?, ?, NULL, ?, ?, ?, COALESCE(?, ''), ?)
                    ON CONFLICT(model_id) DO UPDATE SET
                        state=excluded.state,
                        consecutive_fails=excluded.consecutive_fails,
                        cooldown_until=excluded.cooldown_until,
                        last_error=excluded.last_error,
                        last_probe_at=excluded.last_probe_at,
                        updated_at=excluded.updated_at
                    """,
                    (
                        model_id,
                        state,
                        fails,
                        cooldown_until,
                        safe_summary[:300],
                        now,
                        (row or {}).get("last_ok_at", ""),
                        now,
                    ),
                )
                con.commit()
            except sqlite3.Error:
                self._discard_connection()
                raise
        return flipped

    def cooling_ids(self) -> set[str]:
        """近期失败冷却中的渠道 id 集（cooldown_until > now）；解析失败按不在冷却。

        无用功删除波（2026-10-12）：判据一字未动，只把「每次现开连接」换成常驻
        连接上的一条查询（实测 427µs → 49µs）。
        """
        now_dt = datetime.now(timezone.utc)
        cooling: set[str] = set()
        rows = self._fetch_all(
            "SELECT model_id, cooldown_until FROM channel_health"
            " WHERE cooldown_until IS NOT NULL AND cooldown_until != ''"
        )
        for model_id, raw in rows:
            try:
                until = datetime.fromisoformat(str(raw))
            except (TypeError, ValueError):
                continue
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if until > now_dt:
                cooling.add(str(model_id))
        return cooling

    def record_config_missing(self, model_id: str) -> int:
        """进程生命周期内 config_missing 累计计数（v21r5）；返回累计次数。

        语义（v21r5 设计）：config_missing = 渠道配置洞（key 缺失/未解析），
        沿用既有注释「配置问题≠渠道不可用」——前两次绝不冷却；但同一渠道
        反复缺配置通常意味着注册表条目已废（如 env 槽位没灌、渠道被裁），
        累计 ≥ 阈值（路由侧 _CONFIG_MISSING_COOLDOWN_THRESHOLD）后由路由侧
        调 record_failure 按加长冷却（10× 常规）降速，避免每个候选链都把它
        排在前面白跳一次。计数只增不清零（进程生命周期累计）；重启即清零。
        线程安全：与 SQLite 操作共用 self._lock；纯内存 O(1)。
        """
        with self._lock:
            count = self._config_missing_counts.get(model_id, 0) + 1
            self._config_missing_counts[model_id] = count
            return count

    def unavailable_ids(self) -> set[str]:
        """state=temporarily_unavailable 的 id 集（巡检摘要用；不看重探时间）。

        与批查询腿同一条 SQL 真身（``_UNAVAILABLE_ROWS_SQL``）：改前取
        ``(model_id, state)``、改后取 ``(model_id, last_probe_at)``，WHERE 逐字未动
        ⇒ 返回集合同一（第二列不再被本函数消费）。
        """
        rows = self._fetch_all(_UNAVAILABLE_ROWS_SQL, (_UNAVAILABLE,))
        return {r[0] for r in rows}

    def latencies(self) -> dict[str, int]:
        """实测延迟表：state='ok' 且 latency_ms 非空的 {model_id: latency_ms}。

        供同名模型渠道聚合时的延迟择优（prefer_fastest_channels / ModelRouter）。
        """
        rows = self._fetch_all(
            "SELECT model_id, latency_ms FROM channel_health"
            " WHERE state = ? AND latency_ms IS NOT NULL",
            (_OK,),
        )
        return {r[0]: int(r[1]) for r in rows}

    def ema_latencies(self) -> dict[str, int]:
        """平滑延迟表（v2 动态切换）：state='ok' 且 ema_ms 非空的 {model_id: ema_ms}。

        供同名模型渠道聚合的延迟择优（ModelRouter.channels_for_model）；
        比最近一次实测更抗抖动，探针与真实调用都在持续更新它。
        """
        rows = self._fetch_all(
            "SELECT model_id, ema_ms FROM channel_health"
            " WHERE state = ? AND ema_ms IS NOT NULL",
            (_OK,),
        )
        return {r[0]: int(r[1]) for r in rows}

    def report(self) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            "SELECT model_id, state, consecutive_fails, latency_ms,"
            " ema_ms, samples, last_error, last_ok_at FROM channel_health"
            " ORDER BY state DESC, model_id"
        )
        return [
            {
                "model_id": r[0],
                "state": r[1],
                "consecutive_fails": r[2],
                "latency_ms": r[3],
                "ema_ms": r[4],
                "samples": int(r[5] or 0),
                "last_error": r[6],
                "last_ok_at": r[7],
            }
            for r in rows
        ]

    def clear(self, model_id: str) -> None:
        with self._lock:
            try:
                con = self._shared_connection()
                con.execute("DELETE FROM channel_health WHERE model_id = ?", (model_id,))
                con.commit()
            except sqlite3.Error:
                self._discard_connection()
                raise


_GLOBAL_STORE: ChannelHealthStore | None = None
_GLOBAL_LOCK = threading.Lock()


def _flag_value(raw: object) -> bool | None:
    """布尔开关文本解析：命中真/假词表返回对应布尔，未识别返回 None。"""
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in {"1", "true", "on", "yes"}:
        return True
    if text in {"0", "false", "off", "no"}:
        return False
    return None


def channel_health_enabled(config: Any | None = None) -> bool:
    """健康层总开关（唯一解析源，路由侧与巡检侧共用）。

    解析链：Config 字段（bot_channel_health_enabled）→ os.environ
    （BOT_CHANNEL_HEALTH_ENABLED）→ 默认关。生产 .env 的值只进 NoneBot
    Config 不进 os.environ，因此 Config 字段必须是主路径；os.environ
    兜底服务于裸脚本与测试（monkeypatch.setenv）。config 缺字段且未设
    环境变量时视为关（保守默认，不写库不过滤）。
    """
    for raw in (
        getattr(config, "bot_channel_health_enabled", None),
        os.environ.get("BOT_CHANNEL_HEALTH_ENABLED"),
    ):
        value = _flag_value(raw)
        if value is not None:
            return value
    return False


def channel_health_latency_first(config: Any | None = None) -> bool:
    """延迟择优开关（与巡检侧同源）：Config 字段 → os.environ → 默认关。

    2026-09-16 用户裁定「永远按故障路由转移优先级来处理」：EWMA 延迟重排
    会把低优先级但响应快的渠道顶到前面（浅夜の梦抢恒星纪元事故），故缺省
    改为优先级序；确需延迟择优时 BOT_CHANNEL_HEALTH_LATENCY_FIRST=true。"""
    for raw in (
        getattr(config, "bot_channel_health_latency_first", None),
        os.environ.get("BOT_CHANNEL_HEALTH_LATENCY_FIRST"),
    ):
        value = _flag_value(raw)
        if value is not None:
            return value
    return False


def resolve_default_db_path() -> str:
    """默认库路径：data/ 前缀按 runtime_paths 重映射到 Runtime 数据根。"""
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        from scripts.runtime_paths import runtime_path

        return str(runtime_path("data/channel_health.sqlite3"))
    except Exception:  # noqa: BLE001 - 解析失败退回相对路径。
        return "data/channel_health.sqlite3"


def get_channel_health_store(db_path: str = "") -> ChannelHealthStore:
    """进程级单例（修 D4：库位置只按一种规则解析）。

    路径一律先经 ``resolve_default_db_path()``（runtime_paths 重映射），
    不再允许 model_router 系自带 os.environ 相对路径默认——旧实现里库
    位置取决于进程内谁先调用，跨重启巡检历史「凭空丢失」。首次调用固定
    库位置；此后若传入不同 db_path 只打 warning 并继续用现有库。
    """
    global _GLOBAL_STORE
    with _GLOBAL_LOCK:
        store = _GLOBAL_STORE
        if store is None:
            _GLOBAL_STORE = ChannelHealthStore(
                str(db_path) if db_path else resolve_default_db_path()
            )
            return _GLOBAL_STORE
        if db_path:
            if store.db_path != str(db_path):
                logger.warning(
                    "channel health store already opened at %s; "
                    "ignoring different db path %s",
                    store.db_path,
                    str(db_path),
                )
            return store
        # 空参 ＋ 单例已在 ⇒ 不再重算路径（无用功删除波 2026-10-12）。
        # 依据是本函数自己的既有契约「首次调用固定库位置」：默认库位置在第一次
        # 调用时就已钉死，此后 resolve_default_db_path() 的返回值要么被丢弃、
        # 要么只用来打一行 warning——而 warning 的在册触发条件是「**传入**不同
        # db_path」（见上一段 docstring 与锁
        # tests/test_auditfix_llm_route.py::test_get_store_singleton_ignores_mismatched_path），
        # 空参从来不在契约里。旧实现每消息 ≥4 次走进这一支、每次全重算一遍
        # runtime_paths 落点（实测 P50 1.58ms/次、成分 runtime_data_dir() 0.91ms
        # + Path.resolve() 0.16ms），换来的是一句永远不会打的 warning。
        return store


def filter_healthy_candidates(model_ids: list[str], store: ChannelHealthStore | None) -> list[str]:
    """从故障转移候选中剔除暂不可用渠道；全被剔除时放行原列表（防全瘫）。

    无用功删除波（2026-10-12）：改前形状是「每候选调一次 ``store.is_available``
    ⇒ 每候选现开一条 sqlite 连接」——实测 40 候选 P50 22.3ms、全库 83 候选 40.5ms，
    全是本机往返、与网络无关。现收成 ``availability_map`` 的**一条批查询**；
    判据真身仍只有一枚（``_decide_available``），返回列表逐元素同值
    （锁＝``tests/test_channel_health_v2.py::test_batch_leg_equals_per_candidate_leg_field_by_field``
    ＋同件里的连接计数形状锁）。
    """
    if store is None or not model_ids:
        return model_ids
    avail = store.availability_map(model_ids)
    # 查不到的 id 按放行（与旧形状 row is None → True 同值，也与本模块
    # 「健康层自己出问题绝不阻塞路由」的 fail-open 哲学同调）。
    healthy = [mid for mid in model_ids if avail.get(mid, True)]
    return healthy or model_ids


def resolve_channel_cooldown_seconds(config: Any | None = None) -> float:
    """近期失败冷却时长解析：config 属性 → os.environ 兜底 → 缺省 90s；负值按 0。

    2026-09-17 用户裁定（故障转移链完善）：真实调用失败的渠道短期冷却——
    冷却期内不排候选前排（降级不剔除），治「同一坏渠道每轮都当首发烧 20s」。
    """
    for raw in (
        getattr(config, "bot_chat_channel_cooldown_seconds", None),
        os.environ.get("BOT_CHAT_CHANNEL_COOLDOWN_SECONDS"),
    ):
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        return max(0.0, value)
    return _DEFAULT_COOLDOWN_SECONDS


def demote_cooling_candidates(
    model_ids: list[str], store: ChannelHealthStore | None
) -> tuple[list[str], list[str]]:
    """近期失败冷却降级：冷却中的渠道稳定移到队尾，其余保持原相对顺序。

    返回 (降级后队列, 被降级的渠道 id 列表)。降级不剔除：全部候选都在冷却
    时等价原序放行（防全瘫，与 filter_healthy_candidates 同一哲学）；
    store 为 None / 列表短于 2 → 原样。
    """
    if store is None or len(model_ids) < 2:
        return model_ids, []
    try:
        cooling = store.cooling_ids()
    except Exception:  # noqa: BLE001 - 冷却层故障不阻塞路由。
        return model_ids, []
    if not cooling:
        return model_ids, []
    front = [mid for mid in model_ids if mid not in cooling]
    back = [mid for mid in model_ids if mid in cooling]
    if not front or not back:
        return model_ids, []
    return [*front, *back], back


def prefer_fastest_channels(
    model_ids: list[str],
    store: ChannelHealthStore | None,
    *,
    enabled: bool = True,
) -> list[str]:
    """延迟择优（B-1）：已实测渠道按 latency 升序排前，未实测保序垫底。

    稳定重排：同延迟/未实测渠道保持原有相对顺序；纯排序，不做额外健康
    判定（不可用渠道由 filter_healthy_candidates 在上游过滤）。
    store 为 None / enabled=False / 列表短于 2 → 原样返回。
    """
    if store is None or not enabled or len(model_ids) < 2:
        return model_ids
    latencies = store.latencies()
    measured = [(mid, latencies[mid]) for mid in model_ids if mid in latencies]
    if not measured:
        return model_ids
    ordered = [mid for mid, _ in sorted(measured, key=lambda item: item[1])]
    return ordered + [mid for mid in model_ids if mid not in latencies]


def probe_entry(
    spec: Any,
    *,
    proxy: str = "",
    timeout_seconds: float = 25.0,
    api_key_override: str = "",
) -> tuple[bool, int, str]:
    """对单个渠道做最小真实调用；返回 (ok, latency_ms, error_summary)。

    用 OpenAI 兼容 /chat/completions，max_tokens=1，最小化费用。

    密钥解析链（修 D8：删除恒空死表达式与 ``object.__setattr__`` 注入）：
    ``api_key_override``（probe_all 经 os.environ→Config 预解析的结果）
    → spec.api_key 为 ``env:`` 引用时直接查 os.environ → 都为空报
    no_api_key。明文密钥直接可用。
    """
    import httpx

    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
        _loopback_endpoint,
    )

    api_key = str(api_key_override or "").strip()
    if not api_key:
        raw_key = str(getattr(spec, "api_key", "") or "")
        if raw_key.startswith("env:"):
            env_name = raw_key[4:].strip()
            api_key = os.environ.get(env_name, "").strip()
        else:
            api_key = raw_key.strip()
    if not api_key:
        return False, 0, "no_api_key(需在系统环境变量或Config字段提供)"
    url = spec.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": spec.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    started = time.monotonic()
    try:
        # 回环网关探针硬直连：本机渠道健康度不得被代理进程存活绑架
        # （2026-09-29 22:09 Clash 7890 拒连窗实证）。
        loopback = _loopback_endpoint(url)
        with httpx.Client(
            timeout=timeout_seconds,
            proxy=None if loopback else (proxy or None),
            trust_env=not loopback,
        ) as client:
            response = client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        latency = int((time.monotonic() - started) * 1000)
        if response.status_code == 200:
            return True, latency, ""
        body = ""
        try:
            body = str(response.json().get("error", {}).get("message", ""))[:200]
        except Exception:  # noqa: BLE001
            body = response.text[:200]
        return False, latency, f"HTTP {response.status_code}: {body}"
    except Exception as exc:  # noqa: BLE001 - 探针吞一切异常转状态。
        latency = int((time.monotonic() - started) * 1000)
        return False, latency, f"{type(exc).__name__}: {str(exc)[:180]}"


def _probe_setting(config: Any, attr: str, env_name: str, default: float) -> float:
    """巡检参数解析：config 属性 → os.environ 兜底 → 默认值。

    NoneBot 会把 .env 的 ``BOT_*`` 小写映射进 Config，getattr 主路径即覆盖
    生产；os.environ 兜底服务于裸脚本调用（config 是 stub 时）。仅当值
    缺失/无法解析为数字才回退；越界交给调用方钳位，不在此回退。
    """
    for raw in (getattr(config, attr, None), os.environ.get(env_name)):
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return default


def _probe_threads(config: Any, *, mode: str) -> int:
    attr = "bot_channel_probe_manual_threads" if mode == "manual" else "bot_channel_probe_threads"
    env = "BOT_CHANNEL_PROBE_MANUAL_THREADS" if mode == "manual" else "BOT_CHANNEL_PROBE_THREADS"
    default = _PROBE_MANUAL_THREADS_DEFAULT if mode == "manual" else _PROBE_THREADS_DEFAULT
    value = int(_probe_setting(config, attr, env, float(default)))
    return max(_PROBE_THREADS_MIN, min(_PROBE_THREADS_MAX, value))


def _probe_jitter(config: Any) -> float:
    value = _probe_setting(
        config,
        "bot_channel_probe_jitter_seconds",
        "BOT_CHANNEL_PROBE_JITTER_SECONDS",
        _PROBE_JITTER_DEFAULT,
    )
    # jitter<=0 → 不 sleep（提交零错峰）；上限 5s 防止误配拖垮巡检。
    return max(0.0, min(_PROBE_JITTER_MAX, value))


# 巡检在飞互斥（修 D5）：手动 /bot model probe 与后台定时巡检共享一把
# 非阻塞锁，任一在飞时其他全量巡检直接被拒，防止叠加多路全量真实调用
# 打爆共享 key 的限流窗口。
_PROBE_ALL_LOCK = threading.Lock()


def probe_in_flight() -> bool:
    """是否有渠道巡检（手动或后台）正在进行。"""
    return _PROBE_ALL_LOCK.locked()


def probe_all(
    config: Any,
    specs: dict[str, Any],
    store: ChannelHealthStore,
    *,
    mode: str = "background",
) -> dict[str, Any]:
    """全量巡检；返回摘要。

    mode="manual"：手动 /bot model probe——高并发（默认 8 线程，
    bot_channel_probe_manual_threads）尽快出结果；
    mode="background"：定时巡检——默认 3 线程（bot_channel_probe_threads）
    + 默认 0.4s 错峰抖动（bot_channel_probe_jitter_seconds），避免突发
    打爆共享 key 的限流窗口、殃及紧随其后的真实聊天。

    在飞互斥：入口以非阻塞方式获取共享锁，拿不到（手动/后台任一巡检
    正在跑）立即返回 ``busy=True`` 摘要，不做任何真实调用。
    """
    if not _PROBE_ALL_LOCK.acquire(blocking=False):
        return {
            "probed": 0,
            "ok": 0,
            "unavailable": [],
            "detail": {},
            "busy": True,
        }
    try:
        return _probe_all_locked(config, specs, store, mode=mode)
    finally:
        _PROBE_ALL_LOCK.release()


def _probe_all_locked(
    config: Any,
    specs: dict[str, Any],
    store: ChannelHealthStore,
    *,
    mode: str,
) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor

    proxy = str(getattr(config, "bot_download_proxy", "") or "")
    timeout = min(30.0, float(getattr(config, "bot_chat_timeout_seconds", 30.0) or 30.0))
    threads = _probe_threads(config, mode=mode)
    jitter = _probe_jitter(config)
    results: dict[str, Any] = {}

    # env: 引用预解析（修 D8：结果经显式参数传入 probe_entry，不再用
    # object.__setattr__ 污染 spec）。解析链与 model_router._resolve_api_key
    # 同语义：os.environ 优先，Config 字段回退。
    resolved_keys: dict[int, str] = {}
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
            _resolve_api_key,
        )

        for spec_index, spec in enumerate(specs.values()):
            resolved = _resolve_api_key(str(getattr(spec, "api_key", "") or ""), config)
            if resolved:
                resolved_keys[id(spec)] = resolved
    except Exception:  # 预解析失败退回 probe 内部解析，不影响巡检主流程。
        logger.debug("channel probe pre-resolve api keys failed", exc_info=True)

    def _one(item: tuple[str, Any]) -> tuple[str, bool, int, str]:
        model_id, spec = item
        ok, latency, err = probe_entry(
            spec,
            proxy=proxy,
            timeout_seconds=timeout,
            api_key_override=resolved_keys.get(id(spec), ""),
        )
        return model_id, ok, latency, err

    pending = list(specs.items())
    if mode == "manual":
        with ThreadPoolExecutor(max_workers=threads) as pool:
            for model_id, ok, latency, err in pool.map(_one, pending):
                if ok:
                    store.record_success(model_id, latency)
                else:
                    store.record_failure(model_id, err)
                results[model_id] = {"ok": ok, "latency_ms": latency, "error": err}
        unavailable = store.unavailable_ids()
        return {
            "probed": len(results),
            "ok": sum(1 for r in results.values() if r["ok"]),
            "unavailable": sorted(unavailable),
            "detail": results,
        }
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = []
        for index, item in enumerate(pending):
            if index and jitter > 0:
                time.sleep(jitter)
            futures.append(pool.submit(_one, item))
        for future in futures:
            model_id, ok, latency, err = future.result()
            if ok:
                store.record_success(model_id, latency)
            else:
                store.record_failure(model_id, err)
            results[model_id] = {"ok": ok, "latency_ms": latency, "error": err}
    unavailable = store.unavailable_ids()
    return {
        "probed": len(results),
        "ok": sum(1 for r in results.values() if r["ok"]),
        "unavailable": sorted(unavailable),
        "detail": results,
    }


def resolve_slow_ema_ms(config: Any) -> int:
    """慢渠道阈值解析：config 属性 → os.environ 兜底 → 默认（毫秒，>=1）。"""
    for raw in (
        getattr(config, "bot_channel_slow_ema_ms", None),
        os.environ.get("BOT_CHANNEL_SLOW_EMA_MS"),
    ):
        if raw is None:
            continue
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            continue
        if value >= 1:
            return value
    return _SLOW_EMA_MS