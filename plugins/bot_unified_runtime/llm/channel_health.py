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

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

_UNAVAILABLE = "temporarily_unavailable"
_OK = "ok"
# 连续失败达到该次数才判暂不可用（单次抖动不踢出队列）。
_UNAVAILABLE_AFTER_FAILS = 2
# 暂不可用后每隔多久重探（秒）；重探成功即自动恢复。
_RETRY_INTERVAL_SECONDS = 1800.0


class ChannelHealthStore:
    """按 model_id（注册条目 id）记录渠道健康状态。"""

    def __init__(self, db_path: str | Any) -> None:
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        return con

    def _init_schema(self) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS channel_health (
                        model_id TEXT PRIMARY KEY,
                        state TEXT NOT NULL,
                        consecutive_fails INTEGER NOT NULL DEFAULT 0,
                        latency_ms INTEGER,
                        last_error TEXT DEFAULT '',
                        last_probe_at TEXT DEFAULT '',
                        last_ok_at TEXT DEFAULT '',
                        updated_at TEXT DEFAULT ''
                    )
                    """
                )
                con.commit()
            finally:
                con.close()

    def _row(self, cur: sqlite3.Cursor, model_id: str) -> dict[str, Any] | None:
        row = cur.execute(
            "SELECT state, consecutive_fails, latency_ms, last_error, last_ok_at"
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
        }

    def snapshot(self, model_id: str) -> dict[str, Any] | None:
        with self._lock:
            con = self._connect()
            try:
                return self._row(con.cursor(), model_id)
            finally:
                con.close()

    def is_available(self, model_id: str) -> bool:
        """故障转移队列过滤：unavailable 且未到重探时间 → False。

        到达重探间隔（30 分钟）放行一次：下一次真实调用/巡检若成功会自动
        恢复 ok 状态；仍失败则继续不可用并刷新探针时间。
        """
        with self._lock:
            con = self._connect()
            try:
                cur = con.cursor()
                row = self._row(cur, model_id)
                raw = cur.execute(
                    "SELECT last_probe_at FROM channel_health WHERE model_id = ?",
                    (model_id,),
                ).fetchone()
            finally:
                con.close()
        if row is None or row["state"] != _UNAVAILABLE:
            return True
        if not raw or not raw[0]:
            return True
        try:
            last = datetime.fromisoformat(str(raw[0]))
            age = (datetime.now(timezone.utc) - last).total_seconds()
        except ValueError:
            return True
        return age >= _RETRY_INTERVAL_SECONDS

    def record_success(self, model_id: str, latency_ms: int) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    """
                    INSERT INTO channel_health
                        (model_id, state, consecutive_fails, latency_ms,
                         last_error, last_probe_at, last_ok_at, updated_at)
                    VALUES (?, ?, 0, ?, '', ?, ?, ?)
                    ON CONFLICT(model_id) DO UPDATE SET
                        state='ok', consecutive_fails=0, latency_ms=excluded.latency_ms,
                        last_error='', last_probe_at=excluded.last_probe_at,
                        last_ok_at=excluded.last_ok_at, updated_at=excluded.updated_at
                    """,
                    (model_id, _OK, latency_ms, now, now, now),
                )
                con.commit()
            finally:
                con.close()

    def record_failure(self, model_id: str, error_summary: str) -> bool:
        """记录一次失败；达到阈值标记暂不可用。返回是否发生了状态翻转。"""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        flipped = False
        with self._lock:
            con = self._connect()
            try:
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
                         last_error, last_probe_at, last_ok_at, updated_at)
                    VALUES (?, ?, ?, NULL, ?, ?, COALESCE(?, ''), ?)
                    ON CONFLICT(model_id) DO UPDATE SET
                        state=excluded.state,
                        consecutive_fails=excluded.consecutive_fails,
                        last_error=excluded.last_error,
                        last_probe_at=excluded.last_probe_at,
                        updated_at=excluded.updated_at
                    """,
                    (
                        model_id,
                        state,
                        fails,
                        error_summary[:300],
                        now,
                        (row or {}).get("last_ok_at", ""),
                        now,
                    ),
                )
                con.commit()
            finally:
                con.close()
        return flipped

    def unavailable_ids(self) -> set[str]:
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    "SELECT model_id, state FROM channel_health WHERE state = ?",
                    (_UNAVAILABLE,),
                ).fetchall()
            finally:
                con.close()
        return {r[0] for r in rows}

    def report(self) -> list[dict[str, Any]]:
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    "SELECT model_id, state, consecutive_fails, latency_ms,"
                    " last_error, last_ok_at FROM channel_health"
                    " ORDER BY state DESC, model_id"
                ).fetchall()
            finally:
                con.close()
        return [
            {
                "model_id": r[0],
                "state": r[1],
                "consecutive_fails": r[2],
                "latency_ms": r[3],
                "last_error": r[4],
                "last_ok_at": r[5],
            }
            for r in rows
        ]

    def clear(self, model_id: str) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute("DELETE FROM channel_health WHERE model_id = ?", (model_id,))
                con.commit()
            finally:
                con.close()


_GLOBAL_STORE: ChannelHealthStore | None = None
_GLOBAL_LOCK = threading.Lock()


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
    global _GLOBAL_STORE
    with _GLOBAL_LOCK:
        if _GLOBAL_STORE is None:
            _GLOBAL_STORE = ChannelHealthStore(db_path or resolve_default_db_path())
        return _GLOBAL_STORE


def filter_healthy_candidates(model_ids: list[str], store: ChannelHealthStore | None) -> list[str]:
    """从故障转移候选中剔除暂不可用渠道；全被剔除时放行原列表（防全瘫）。"""
    if store is None or not model_ids:
        return model_ids
    healthy = [mid for mid in model_ids if store.is_available(mid)]
    return healthy or model_ids


def probe_entry(spec: Any, *, proxy: str = "", timeout_seconds: float = 25.0) -> tuple[bool, int, str]:
    """对单个渠道做最小真实调用；返回 (ok, latency_ms, error_summary)。

    用 OpenAI 兼容 /chat/completions，max_tokens=1，最小化费用。
    """
    import httpx

    api_key = spec.api_key
    if str(api_key).startswith("env:"):
        import os

        api_key = os.environ.get(str(api_key)[4:], "")
    if not api_key:
        return False, 0, "no_api_key"
    url = spec.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": spec.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout_seconds, proxy=proxy or None) as client:
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


def probe_all(config: Any, specs: dict[str, Any], store: ChannelHealthStore) -> dict[str, Any]:
    """全量巡检（线程池并发）；返回摘要。"""
    from concurrent.futures import ThreadPoolExecutor

    proxy = str(getattr(config, "bot_download_proxy", "") or "")
    timeout = min(30.0, float(getattr(config, "bot_chat_timeout_seconds", 30.0) or 30.0))
    results: dict[str, Any] = {}

    def _one(item: tuple[str, Any]) -> tuple[str, bool, int, str]:
        model_id, spec = item
        ok, latency, err = probe_entry(spec, proxy=proxy, timeout_seconds=timeout)
        return model_id, ok, latency, err

    with ThreadPoolExecutor(max_workers=8) as pool:
        for model_id, ok, latency, err in pool.map(_one, list(specs.items())):
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


def build_health_summary_text(report: list[dict[str, Any]]) -> str:
    """/bot model health 展示文本。"""
    if not report:
        return "渠道健康：暂无巡检数据（等待首轮探测或手动 /bot model probe）。"
    ok_rows = [r for r in report if r["state"] == "ok"]
    bad_rows = [r for r in report if r["state"] != "ok"]
    lines = [f"渠道健康：{len(ok_rows)} 可用 / {len(bad_rows)} 暂不可用"]
    for row in ok_rows:
        latency = f"{row['latency_ms']}ms" if row["latency_ms"] else "-"
        lines.append(f"✅ {row['model_id']} {latency}")
    for row in bad_rows:
        err = (row["last_error"] or "unknown")[:80]
        lines.append(f"⛔ {row['model_id']} 暂时不可用（连续失败 {row['consecutive_fails']}）：{err}")
    lines.append("说明：暂不可用渠道已移出故障转移队列，每 30 分钟自动重探，恢复即自动回队；永不自动删除。")
    return "\n".join(lines)


def dumps_payload(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)
