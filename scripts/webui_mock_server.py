#!/usr/bin/env python3
"""webui_mock_server.py — WebUI 离线确定性夹具后端（MOCKUI 席，2026-09-18）。

仅供前端开发 / 验收目验 / 截图对比使用的纯夹具服务：

- **绝不接入生产链路**：不读任何真实 SQLite/日志/cookie/人格文件，不写任何
  文件、不进任何数据库；与 ChatBot_Runtime、control_plane 生产进程零关联。
- **确定性**：全部夹具由固定假时刻（2026-09-18T12:00:00Z）与固定内容生成，
  request_id/trace_id/debug_id 亦由请求指纹派生（真实端为随机 UUID）——
  两次启动对同一请求的响应体逐字节一致，可做截图对比基线。
- **形状保真**：端点一一对照真实实现（control_plane/webui_stats.py、
  webui_knowledge.py、webui_plugins.py、webui_memory_graph.py、api/webui.py、
  api/webui_ext.py、api/events.py、api/health.py）与 tests/test_webui_*.py 的契约断言；
  统一信封 {data, error, meta{request_id, trace_id, schema_version, generated_at}}。
- **与真实端的诚实差异**（真实契约如此，mock 不造假）：
  * stats/latency 无历史曲线（真实 history=unavailable/not_persisted）；
  * stats/tokens 为族聚合快照（真实契约无 trend 字段；趋势序列只在 stats/calls）；
  * 认证只做 ``--bearer any`` 的存在性校验（无失败限速/429）；
  * 503 control_plane_not_provisioned（未配令牌）语义不模拟；
  * /admin/api/v1/health|status/bot|status/models 为 legacy 裸体（无 envelope）；
    mock 恒回组件全 ok / 渠道健康（health.py 的 store_unavailable 503 不模拟）。
- 零第三方依赖（stdlib http.server），离线可跑。

用法：
    python scripts/webui_mock_server.py                 # 127.0.0.1:8743
    python scripts/webui_mock_server.py --port 8744
    python scripts/webui_mock_server.py --delay-ms 300  # 模拟网络延迟
    python scripts/webui_mock_server.py --bearer any    # 校验 Authorization 头存在
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import typing
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlparse

# ---------------------------------------------------------------------------
# 确定性锚点
# ---------------------------------------------------------------------------

FIXED_NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
FIXED_NOW_ISO = FIXED_NOW.isoformat(timespec="milliseconds")  # 2026-09-18T12:00:00.000+00:00
FIXED_HTTP_DATE = "Fri, 18 Sep 2026 12:00:00 GMT"
SCHEMA_VERSION = "v1"

# logs 保留窗口：cursor ≤ RETENTION_FLOOR 视为已修剪 → 410 cursor_expired。
RETENTION_FLOOR = 100
HIGH_CURSOR = 112

_SSE_SUMMARY_INTERVAL_SECONDS = 2.0
_DEFAULT_HEARTBEAT_SECONDS = 15.0

_EVENT_SOURCES = (
    "bot", "nonebot", "napcat", "telegram", "mail", "control_plane",
    "decision_engine", "pipeline", "sender", "llm", "database", "scheduler",
    "capability", "renderer",
)
_EVENT_CATEGORIES = (
    "debug", "info", "warning", "error", "success", "critical", "detail",
)
# 真实 RuntimeLogEvent 会把 message 统一替换为分类文案（细节全在 details）。
_EVENT_MESSAGES = dict(zip(
    _EVENT_CATEGORIES,
    ("调试事件", "运行信息", "运行警告", "操作失败", "操作成功", "严重异常", "运行详情"),
    strict=True,
))

_TIER_NAMES = {
    -4: "初识", -3: "生疏", -2: "微凉", -1: "稍淡",
    0: "友善（基准）", 1: "亲近", 2: "挚友", 3: "独一份",
}

_IDENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,128}\Z")

# ---------------------------------------------------------------------------
# 确定性 id 工具（真实端为随机；mock 用请求指纹派生保证逐字节一致）
# ---------------------------------------------------------------------------


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _request_ids(method: str, path: str, query: str) -> tuple[str, str, str]:
    seed = f"{method}|{path}|{query}"
    return (
        "req_" + _digest("req|" + seed)[:32],
        "trace_" + _digest("trace|" + seed)[:32],
        "cp-20260918-" + _digest("dbg|" + seed)[:8],
    )


def _session_label(session: str) -> str:
    """真实端 session 标签=进程内 HMAC 假名（``session_<64hex>``）；mock 用固定 key 同形。"""
    return "session_" + hmac_hex(session)


def hmac_hex(payload: str) -> str:
    return hashlib.sha256(b"mock-key\0session\0" + payload.encode("utf-8")).hexdigest()


def _event_uuid(cursor: int) -> str:
    """事件 id：真实端为 uuid4 hex；mock 用 uuid5 定点派生（同为 32 hex）。"""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"mock-log-{cursor}").hex


def _normalize(text: str) -> str:
    """q/term 匹配归一：NFKC + casefold（glossary 召回同规）。"""
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


# ---------------------------------------------------------------------------
# 统一信封 / 错误体（api/protocol.py envelope + _error_payload 同形）
# ---------------------------------------------------------------------------


def envelope(data, *, request_id: str) -> dict:
    return {
        "data": data,
        "error": None,
        "meta": {
            "request_id": request_id,
            "trace_id": "trace_" + _digest("trace-base|" + request_id)[:32],
            "schema_version": SCHEMA_VERSION,
            "generated_at": FIXED_NOW_ISO,
        },
    }


def error_payload(*, status: int, code: str, message: str, request_id: str, debug_id: str) -> dict:
    return {
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "debug_id": debug_id,
            "retryable": status in (429, 503),
            "field_errors": [],
        },
        "meta": {
            "request_id": request_id,
            "trace_id": "trace_" + _digest("trace-err|" + request_id)[:32],
            "schema_version": SCHEMA_VERSION,
            "generated_at": FIXED_NOW_ISO,
        },
    }


# ---------------------------------------------------------------------------
# 夹具：stats/calls（审计聚合，按真实服务口径聚合）
# ---------------------------------------------------------------------------

# (距固定时刻的小时偏移, session_id, capability_id)；负偏移=更早。
_AUDIT_ROWS: list[tuple[int, str, str]] = [
    (0, "private_777", "bot.chat"),
    (0, "private_777", "bot.chat"),
    (0, "private_777", "bot.chat"),
    (0, "group_1108838060_3865067623", "bot.chat"),
    (0, "group_1108838060_3865067623", "bot.chat"),
    (1, "private_777", "bot.weather"),
    (2, "group_1108838060_3865067623", "bot.music"),
    (2, "group_1108838060_3865067623", "bot.music"),
    (3, "private_10001", "bot.market"),
    (3, "private_10001", "bot.market"),
    (4, "group_662948429_1722380002", "bot.chat"),
    (4, "group_662948429_1722380002", "bot.chat"),
    (4, "group_662948429_1722380002", "bot.chat"),
    (4, "group_662948429_1722380002", "bot.chat"),
    (5, "runtime_digest_scheduler", "bot.digest"),
    (6, "private_777", "bot.affinity"),
    (7, "group_662948429_1722380002", "bot.knowledge"),
    (7, "group_662948429_1722380002", "bot.knowledge"),
    (9, "private_10001", "bot.chat"),
    (9, "private_10001", "bot.chat"),
    (11, "private_777", "bot.chat"),
]
_AUDIT_UNKNOWN_TIMESTAMP_ROWS = 1  # created_at 畸形的行：只进 unknown_timestamp_calls


def _user_from_session(value: str) -> str | None:
    """OneBot v11 session 约定 → 用户 id；约定外 None（webui_stats 同款）。"""
    if value.isdigit():
        return value
    if value.startswith("private_"):
        rest = value[len("private_"):]
        return rest if rest.isdigit() else None
    if value.startswith("group_"):
        parts = value.split("_")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            return parts[2]
    return None


def _iso_at(hours_before: int) -> str:
    return (FIXED_NOW - timedelta(hours=hours_before)).isoformat(timespec="seconds")


def stats_calls(window: str, bucket: str, limit: int) -> dict:
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        return {"failure": "invalid_request"}
    if window not in ("24h", "7d", "30d"):
        return {"failure": "invalid_request"}
    if bucket not in ("hour", "day"):
        return {"failure": "invalid_request"}

    sessions: dict = {}
    users: dict = {}
    capabilities: dict = {}
    trend: dict = {}
    total = 0
    unattributed = 0
    cutoff = FIXED_NOW - timedelta(seconds={"24h": 86_400, "7d": 604_800, "30d": 2_592_000}[window])
    for hours, session, capability in _AUDIT_ROWS:
        stamp = FIXED_NOW - timedelta(hours=hours)
        if stamp < cutoff:
            continue
        total += 1
        if session:
            label = _session_label(session)
            sessions[label] = sessions.get(label, 0) + 1
            user = _user_from_session(session)
            if user is None:
                unattributed += 1
            else:
                users[user] = users.get(user, 0) + 1
        capabilities[capability] = capabilities.get(capability, 0) + 1
        bucket_dt = stamp.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        if bucket == "day":
            bucket_dt = bucket_dt.replace(hour=0)
        key = bucket_dt.isoformat().replace("+00:00", "Z")
        trend[key] = trend.get(key, 0) + 1

    def top(counts: dict, label: str) -> list[dict]:
        ranked = sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
        return [{label: key, "calls": count} for key, count in ranked[:limit]]

    return {
        "status": "ok",
        "source": "audit_records",
        "data": {
            "window": window,
            "total_calls": total,
            "unknown_timestamp_calls": _AUDIT_UNKNOWN_TIMESTAMP_ROWS,
            "unattributed_calls": unattributed,
            "user_attribution": "derived_from_session_id_onebot_convention",
            "by_session": top(sessions, "session"),
            "by_user": top(users, "user"),
            "by_capability": top(capabilities, "capability"),
            "trend": {
                "bucket": bucket,
                "timezone": "UTC",
                "items": [
                    {"bucket_start": key, "calls": trend[key]}
                    for key in sorted(trend, reverse=True)[:limit]
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# 夹具：stats/tokens（账本族聚合，metrics.token_families 同形）
# ---------------------------------------------------------------------------


def _token_block(calls: int, known: int, total: int) -> dict:
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


def _family(calls, i, o, cr_known, cr, cc_known, cc) -> dict:
    return {
        "family": None,
        "calls": calls,
        "tokens": {
            "input": _token_block(calls, calls, i),
            "output": _token_block(calls, calls, o),
            "cache_read": _token_block(calls, cr_known, cr),
            "cache_creation": _token_block(calls, cc_known, cc),
        },
    }


_TOKEN_FAMILIES_RAW = [
    ("gemini-3.8-flash", _family(34, 48200, 22150, 30, 12100, 34, 4300)),
    ("grok-4.6", _family(12, 15900, 9800, 0, 0, 0, 0)),
    ("gpt-5.6-terra", _family(7, 9100, 5300, 7, 2100, 0, 0)),
    ("deepseek-v4.1-flash", _family(3, 2400, 1500, 0, 0, 0, 0)),
]


def _merge(a: dict, b: dict) -> dict:
    calls = a["calls"] + b["calls"]
    tokens = {}
    for name in ("input", "output", "cache_read", "cache_creation"):
        blk = a["tokens"][name]
        other = b["tokens"][name]
        known = blk["known_rows"] + other["known_rows"]
        value = (blk["value"] or 0) + (other["value"] or 0)
        tokens[name] = _token_block(calls, known, value if known else 0)
    return {"family": a["family"], "calls": calls, "tokens": tokens}


def stats_tokens(window: str, limit: int) -> dict:
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        return {"failure": "invalid_request"}
    if window not in ("24h", "7d", "30d"):
        return {"failure": "invalid_request"}
    totals: dict | None = None
    for _, row in _TOKEN_FAMILIES_RAW:
        row = dict(row, family=None)
        totals = row if totals is None else _merge(totals, row)
    families = []
    for name, row in _TOKEN_FAMILIES_RAW:
        families.append(dict(row, family=name))
    families.sort(key=lambda item: (-item["calls"], str(item["family"])))
    return {
        "status": "ok",
        "source": "llm_call_records",
        "data": {"window": window, "totals": totals, "families": families[:limit]},
    }


# ---------------------------------------------------------------------------
# 夹具：stats/latency（渠道健康当前值投影；history=真实契约 unavailable）
# ---------------------------------------------------------------------------

_LATENCY_ITEMS = [
    {
        "channel": "aiprc-gemini-3.8-flash",
        "state": "healthy",
        "consecutive_fails": 0,
        "latency_ms": 14350,
        "ema_ms": 15120,
        "samples": 41,
        "last_ok_at": "2026-09-18T11:52:03.000+00:00",
        "last_error": None,
    },
    {
        "channel": "axon-deepseek-v41-flash",
        "state": "degraded",
        "consecutive_fails": 2,
        "latency_ms": None,
        "ema_ms": 28900,
        "samples": 12,
        "last_ok_at": "2026-09-18T09:14:57.000+00:00",
        "last_error": "ConnectTimeout: connect timeout after 5s (kind=network)",
    },
    {
        "channel": "axon-gemini-3.8-flash",
        "state": "healthy",
        "consecutive_fails": 0,
        "latency_ms": 11210,
        "ema_ms": 11640,
        "samples": 88,
        "last_ok_at": "2026-09-18T11:58:41.000+00:00",
        "last_error": None,
    },
    {
        "channel": "axon-grok-4.6",
        "state": "healthy",
        "consecutive_fails": 0,
        "latency_ms": 10980,
        "ema_ms": 11530,
        "samples": 52,
        "last_ok_at": "2026-09-18T11:47:19.000+00:00",
        "last_error": None,
    },
    {
        "channel": "axon-gpt-5.6-terra",
        "state": "healthy",
        "consecutive_fails": 0,
        "latency_ms": 12870,
        "ema_ms": 13105,
        "samples": 33,
        "last_ok_at": "2026-09-18T11:31:26.000+00:00",
        "last_error": None,
    },
    {
        "channel": "qian-gemini-3.8-flash-high",
        "state": "healthy",
        "consecutive_fails": 0,
        "latency_ms": 16890,
        "ema_ms": 17110,
        "samples": 27,
        "last_ok_at": "2026-09-18T10:05:44.000+00:00",
        "last_error": None,
    },
]


def stats_latency() -> dict:
    return {
        "status": "ok",
        "source": "channel_health",
        "data": {
            "items": sorted(_LATENCY_ITEMS, key=lambda item: item["channel"]),
            "history": {"status": "unavailable", "reason": "not_persisted"},
        },
    }


# ---------------------------------------------------------------------------
# 夹具：/admin/api/v1 health 与 status（api/health.py，legacy 裸体非 envelope）
# ---------------------------------------------------------------------------

# health checks：注入单例逐一 ping 的结果键（health.py 同款：control_plane 恒在，
# channel_health_store/audit_store 按注入在场）；mock 恒全 ok。
_HEALTH_CHECKS: dict[str, str] = {
    "control_plane": "ok",
    "channel_health_store": "ok",
    "audit_store": "ok",
}

# status/bot：进程概览——固定启动时刻与固定运行时长（真实端=now 派生，确定性纪律取固定值）。
_BOT_STARTED_AT = "2026-09-18T11:00:00.000+00:00"
_BOT_UPTIME_SECONDS = 3600.0
_BOT_TIMEZONE = "UTC"

# status/models：渠道健康快照投影（health.py DTO 白名单：model_id/state/consecutive_fails/
# latency_ms/last_error(脱敏)/last_ok_at；latency_ms=渠道 EWMA 快照值）。3 条固定，
# 数值与 _LATENCY_ITEMS 夹具同源（真实端 model_id 字段承载渠道 id，webui_stats 投影为 channel）。
_MODEL_STATUS_ITEMS = [
    {
        "model_id": "aiprc-gemini-3.8-flash",
        "state": "healthy",
        "consecutive_fails": 0,
        "latency_ms": 15120,
        "last_error": "",
        "last_ok_at": "2026-09-18T11:52:03.000+00:00",
    },
    {
        "model_id": "axon-deepseek-v41-flash",
        "state": "degraded",
        "consecutive_fails": 2,
        "latency_ms": 28900,
        "last_error": "ConnectTimeout: connect timeout after 5s (kind=network)",
        "last_ok_at": "2026-09-18T09:14:57.000+00:00",
    },
    {
        "model_id": "axon-gemini-3.8-flash",
        "state": "healthy",
        "consecutive_fails": 0,
        "latency_ms": 11640,
        "last_error": "",
        "last_ok_at": "2026-09-18T11:58:41.000+00:00",
    },
]


def health_report() -> dict:
    return {"ok": True, "checks": dict(_HEALTH_CHECKS), "generated_at": FIXED_NOW_ISO}


def status_bot() -> dict:
    return {
        "started_at": _BOT_STARTED_AT,
        "uptime_seconds": _BOT_UPTIME_SECONDS,
        "timezone": _BOT_TIMEZONE,
    }


def status_models() -> dict:
    return {
        "items": sorted(
            (dict(row) for row in _MODEL_STATUS_ITEMS), key=lambda row: row["model_id"]
        ),
        "generated_at": FIXED_NOW_ISO,
    }


# ---------------------------------------------------------------------------
# 夹具：affinity/board（≥10 人含负分；tier 口径=affinity.py 同款）
# ---------------------------------------------------------------------------

# (sender_id, 内部值, 昵称, 互动次数, updated_at)
_AFFINITY_ROWS = [
    ("3865067623", 0.92, "岸宝", 312, "2026-09-18T11:58:02+00:00"),
    ("1722380002", 0.84, "霞月", 268, "2026-09-18T11:41:37+00:00"),
    ("777", 0.71, "澜汐", 190, "2026-09-18T11:30:15+00:00"),
    ("20003", 0.63, "洛清崖", 155, "2026-09-18T10:52:48+00:00"),
    ("10001", 0.55, "星野", 132, "2026-09-18T10:21:33+00:00"),
    ("20004", 0.41, "白栖", 96, "2026-09-18T09:47:10+00:00"),
    ("20005", 0.33, "云汐", 77, "2026-09-18T09:02:56+00:00"),
    ("20006", 0.25, "泠鸢", 64, "2026-09-18T08:38:21+00:00"),
    ("20007", 0.18, "汀兰", 41, "2026-09-18T07:55:09+00:00"),
    ("20008", 0.09, "浮玉", 23, "2026-09-18T06:40:47+00:00"),
    ("30001", -0.12, "苍羽", 18, "2026-09-17T23:12:30+00:00"),
    ("30002", -0.47, "玄夜", 9, "2026-09-17T18:05:12+00:00"),
    ("30003", -0.68, "霜淮", 4, "2026-09-17T12:44:03+00:00"),
]


def _tier_for(affinity: float) -> int:
    display = float(affinity) * 100.0
    return max(-4, min(3, int(display // 25)))


def affinity_board(limit: int, order: str) -> dict:
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        return {"failure": "invalid_request"}
    if order not in ("desc", "asc"):
        return {"failure": "invalid_request"}
    rows = sorted(
        _AFFINITY_ROWS,
        key=lambda row: (row[1], row[0]) if order == "asc" else (-row[1], row[0]),
    )
    items = []
    for sender, value, nickname, interactions, updated_at in rows[:limit]:
        display = max(-100.0, min(100.0, value * 100.0))
        items.append({
            "sender_id": sender,
            "nickname": nickname,
            "affinity": value,
            "score": round(display, 1),
            "tier": _tier_for(value),
            "tier_name": _TIER_NAMES[_tier_for(value)],
            "interaction_count": interactions,
            "updated_at": updated_at,
        })
    return {
        "status": "ok",
        "source": "user_affinity",
        "data": {"order": order, "total": len(_AFFINITY_ROWS), "items": items},
    }


# ---------------------------------------------------------------------------
# 夹具：knowledge（46 词条 + 8 文档 + 12 标签 + 3 ACG 源 + 2 not_available）
# ---------------------------------------------------------------------------

# (term, aliases, definition, source_stem)
_COMMUNITY_TERMS = [
    ("守岸人", ["ShoreKeeper", "守守"], "本项目的看板娘人格：泰缇斯系统第二实例，鸣潮角色「守岸人」衍生的聊天机器人。", "worldview_glossary"),
    ("漂泊者", ["Rover", "旅人"], "鸣潮主角的称呼；在本 bot 私聊语境中指与守岸人对话的用户。", "worldview_glossary"),
    ("鸣潮", ["Wuthering Waves", "WW"], "库洛游戏开发的开放世界动作游戏，本项目人格设定的世界观来源。", "worldview_glossary"),
    ("今州", ["今州城"], "鸣潮中瑝璟地区的主要城市，守岸人曾长期守望之地。", "worldview_glossary"),
    ("瑝璟", [], "鸣潮世界的国度之一。", "worldview_glossary"),
    ("黑海沿岸", [], "鸣潮世界的重要区域。", "worldview_glossary"),
    ("无音区", ["TD区"], "鸣潮中被残象侵蚀的危险区域。", "worldview_glossary"),
    ("残象", ["Tacet Discord", "TD"], "鸣潮中的异质威胁存在。", "worldview_glossary"),
    ("声骸", ["Echo"], "残象留存的结晶，鸣潮核心养成系统。", "worldview_glossary"),
    ("凝素", [], "鸣潮中的能量物质概念。", "worldview_glossary"),
    ("泰缇斯", ["Tethys"], "守岸人所隶属的 AI 系统名，本项目人格「第二实例」的出处。", "worldview_glossary"),
    ("今汐", ["Jinhsi"], "鸣潮角色，今州令尹。", "worldview_glossary"),
    ("长离", ["Changli"], "鸣潮角色。", "worldview_glossary"),
    ("折枝", ["Zhezhi"], "鸣潮角色。", "worldview_glossary"),
    ("相里要", [], "鸣潮角色。", "worldview_glossary"),
    ("散华", ["Sanhua"], "鸣潮角色。", "worldview_glossary"),
    ("安可", ["Encore"], "鸣潮角色。", "worldview_glossary"),
    ("维里奈", ["Verina"], "鸣潮角色。", "worldview_glossary"),
    ("卡卡罗", ["Calcharo"], "鸣潮角色。", "worldview_glossary"),
    ("凌阳", ["Lingyang"], "鸣潮角色。", "worldview_glossary"),
    ("鉴心", ["Jianxin"], "鸣潮角色。", "worldview_glossary"),
    ("吟霖", ["Yinlin"], "鸣潮角色。", "worldview_glossary"),
    ("渊武", ["Yuanwu"], "鸣潮角色。", "worldview_glossary"),
    ("丹瑾", ["Danjin"], "鸣潮角色。", "worldview_glossary"),
    ("桃祈", ["Taoqi"], "鸣潮角色。", "worldview_glossary"),
    ("莫特斐", ["Mortefi"], "鸣潮角色。", "worldview_glossary"),
    ("秋水", ["Aalto"], "鸣潮角色。", "worldview_glossary"),
    ("炽霞", ["Chixia"], "鸣潮角色。", "worldview_glossary"),
    ("白芷", ["Baizhi"], "鸣潮角色。", "worldview_glossary"),
    ("秧秧", ["Yangyang"], "鸣潮角色。", "worldview_glossary"),
    ("灯灯", ["Lumi"], "鸣潮角色。", "worldview_glossary"),
    ("忌炎", ["Jiyan"], "鸣潮角色，璃月？不——是瑝璟的将军。", "worldview_glossary"),
    ("卡提希娅", ["Cartethyia"], "鸣潮角色。", "worldview_glossary"),
    ("守岸人好感度", ["好感度"], "本 bot 的关系数值系统：-100~+100，聊天内侧只做定性描述。", "community_terms_extra"),
    ("群摘要", ["日报"], "每日 21:30 向白名单群推送的通讯总结。", "community_terms_extra"),
    ("收件箱", ["inbox"], "日常助理速记入口，落纯文本收件箱文件。", "community_terms_extra"),
    ("早报", [], "日常助理 09:00 推送的收件箱划重点。", "community_terms_extra"),
    ("晚报", ["对账"], "日常助理 21:00 的当日对账与琐事建议。", "community_terms_extra"),
    ("校园转发", ["campus"], "学校群消息被动监听并私聊转发主人的功能。", "community_terms_extra"),
    ("媒体归档", ["收藏", "归档"], "用 VLM 判类别×IP 归档媒体文件的功能。", "community_terms_extra"),
    ("表情收库", ["meme"], "群图自动收库并打 VLM 标签的功能。", "community_terms_extra"),
    ("云母卡片", ["云母", "mica"], "本 bot 卡片渲染的视觉体系：云母底+釉瑚渐变漂移。", "community_terms_extra"),
    ("釉瑚", ["Youhu"], "鸣潮角色；渲染管线的渐变漂移配色以此命名。", "community_terms_extra"),
    ("控制面", ["control plane"], "独立于 bot 宿主的管理面进程（生产 8742 端口）。", "community_terms_extra"),
    ("计费账本", ["账本", "ledger"], "LLM 调用记账的三表存储，默认关。", "community_terms_extra"),
    ("渠道健康", ["channel health"], "LLM 渠道延迟与失败状态的跟踪视图。", "community_terms_extra"),
    ("失败转移", ["failover"], "主路由失败后按优先级链换渠道重试。", "community_terms_extra"),
    ("影子对照", ["shadow"], "决策引擎新旧路由并行的对照机制。", "community_terms_extra"),
    ("发送队列", ["SendQueue"], "带幂等与断点续发的 SQLite 出站队列。", "community_terms_extra"),
    ("安静时间", ["quiet hours"], "群聊免打扰时段门禁。", "community_terms_extra"),
    ("白名单", ["whitelist"], "显式放行列表；空=整链路关闭绝不猜群。", "community_terms_extra"),
    ("反注入", ["提示注入防护"], "对话层的注入攻击防护包裹。", "community_terms_extra"),
    ("人格怪癖", ["quirk"], "审核制演化的小习惯系统：propose→approve→渲染。", "community_terms_extra"),
    ("称谓偏好", ["addressing"], "用户自助设置的称呼与性别偏好。", "community_terms_extra"),
    ("鸣潮百科", ["wiki"], "社区维护的鸣潮知识百科（夹具中作向量库文档来源示例）。", "community_terms_extra"),
    ("社区词条", ["glossary"], "世界观术语表文件，词汇回忆功能的来源。", "community_terms_extra"),
    ("词汇回忆", [], "对话中遇到专有名词时注入术语解释的机制。", "community_terms_extra"),
    ("天气码表", ["qx.json"], "NMC 天气 2527 区县码表内置资产。", "community_terms_extra"),
    ("授时", ["NTP"], "时间同步服务，驱动提醒/笔记时序。", "community_terms_extra"),
    ("点歌", ["来首"], "五供应商候选卡点歌功能。", "community_terms_extra"),
    ("行情", ["股指"], "全球股指面板功能。", "community_terms_extra"),
    ("快报", ["今日快报"], "多源科技/财经新闻聚合。", "community_terms_extra"),
    ("订阅", ["subscribe"], "B站/YT/微博等平台的更新订阅推送。", "community_terms_extra"),
    ("占卜", ["塔罗", "八字"], "每日运势类小功能合集。", "community_terms_extra"),
    ("随机图", ["randpic"], "从自定义文件夹随机发图的功能。", "community_terms_extra"),
]

# (doc_id, title, topic, chunk_count) —— 按 doc_id 排序给出
_KB_DOCS = [
    ("digest-2026-09-17", "群摘要归档 2026-09-17", "digest", 2),
    ("faq-commands", "命令 FAQ 合集", "faq", 5),
    ("manual-notes", "本地运维手册摘录", "manual", 3),
    ("wiki-cartethyia", "鸣潮百科：卡提希娅", "wiki", 9),
    ("wiki-jinhsi", "鸣潮百科：今汐", "wiki", 12),
    ("wiki-shorekeeper", "鸣潮百科：守岸人", "wiki", 18),
    ("wiki-tethys", "鸣潮百科：泰缇斯系统", "wiki", 7),
    ("wiki-wuwa-combat", "鸣潮百科：战斗系统入门", "wiki", 14),
]

# (tag, count, scopes)
_MEME_TAGS = [
    ("开心", 14, ["emotion_tags"]),
    ("好耶", 9, ["emotion_tags"]),
    ("惊讶", 7, ["emotion_tags"]),
    ("鸣潮", 6, ["scene_tags"]),
    ("委屈", 6, ["emotion_tags"]),
    ("摸鱼", 5, ["emotion_tags"]),
    ("加班", 4, ["emotion_tags"]),
    ("沙雕", 4, ["emotion_tags"]),
    ("群聊", 3, ["scene_tags"]),
    ("星星眼", 3, ["emotion_tags"]),
    ("早安", 2, ["emotion_tags"]),
    ("晚安", 2, ["emotion_tags"]),
]

_ACG_SOURCES = [
    ("bangumi", "Bangumi 条目检索", True),
    ("bilibili", "B站检索", True),
    ("moegirl", "萌娘百科检索", False),
]

_NOT_AVAILABLE_COLLECTIONS = [
    {"id": "bili_hot_memes", "name": "B站网络热门梗", "description": "B站热门梗词条库（项目内暂无独立存储）"},
    {"id": "pgr", "name": "战双帕弥什词条库", "description": "战双帕弥什世界观词条库（项目内暂无独立存储）"},
]

_KNOWN_COLLECTION_IDS = ("community_terms", "kb_docs", "meme_tags", "acg_sources", "bili_hot_memes", "pgr")


def knowledge_collections() -> dict:
    items = [
        {
            "id": "community_terms",
            "name": "社区词条（世界观术语表）",
            "description": "词汇回忆/世界观 glossary 全量词条",
            "enabled": True,
            "source": "glossary_files",
            "count": len(_COMMUNITY_TERMS),
            "reason": None,
        },
        {
            "id": "kb_docs",
            "name": "向量知识库文档",
            "description": "知识库文档级清单（chunk 数聚合；检索走 platform API）",
            "enabled": True,
            "source": "knowledge_embeddings",
            "count": len(_KB_DOCS),
            "reason": None,
        },
        {
            "id": "meme_tags",
            "name": "表情库标签目录",
            "description": "表情库 VLM 标签聚合 counts",
            "enabled": True,
            "source": "meme_library",
            "count": len(_MEME_TAGS),
            "reason": None,
        },
        {
            "id": "acg_sources",
            "name": "ACG 检索增强源",
            "description": "Bangumi/萌娘百科/B站 检索源配置态",
            "enabled": True,
            "source": "static_config",
            "count": sum(1 for _, _, enabled in _ACG_SOURCES if enabled),
            "reason": None,
        },
    ]
    for entry in _NOT_AVAILABLE_COLLECTIONS:
        items.append({
            "id": entry["id"],
            "name": entry["name"],
            "description": entry["description"],
            "enabled": False,
            "source": "none",
            "count": None,
            "reason": "no_dedicated_store",
        })
    return {"status": "ok", "source": "knowledge_collections", "data": {"items": items}}


def _community_term_rows() -> list[dict]:
    return [
        {
            "term": term,
            "aliases": list(aliases),
            "definition": definition,
            "scope": "general",
            "source": source,
        }
        for term, aliases, definition, source in _COMMUNITY_TERMS
    ]


def _kb_doc_rows(q: str) -> list[dict]:
    needle = _normalize(q)
    rows = []
    for doc_id, title, topic, chunks in sorted(_KB_DOCS):
        if needle and needle not in _normalize(f"{doc_id} {title} {topic}"):
            continue
        rows.append({
            "term": doc_id,
            "aliases": [],
            "definition": title or topic or None,
            "scope": "kb_doc",
            "source": "knowledge_embeddings",
            "chunk_count": chunks,
            "updated_at": None,
        })
    return rows


def _meme_tag_rows(q: str) -> list[dict]:
    needle = _normalize(q)
    rows = []
    for tag, count, scopes in _MEME_TAGS:
        if needle and needle not in _normalize(tag):
            continue
        rows.append({
            "term": tag,
            "aliases": [],
            "definition": None,
            "scope": sorted(scopes),
            "source": "meme_library",
            "count": count,
        })
    rows.sort(key=lambda row: (-row["count"], row["term"]))
    return rows


def _acg_rows(q: str) -> list[dict]:
    needle = _normalize(q)
    rows = []
    for key, name, enabled in sorted(_ACG_SOURCES):
        if needle and needle not in _normalize(key):
            continue
        rows.append({
            "term": key,
            "aliases": [],
            "definition": name,
            "scope": "acg_source",
            "source": "static_config",
            "enabled": enabled,
        })
    return rows


def knowledge_terms(collection: str, q: str, page: int, page_size: int) -> dict:
    if not isinstance(collection, str) or collection not in _KNOWN_COLLECTION_IDS:
        return {"failure": "invalid_request"}
    if not isinstance(page, int) or page < 1:
        return {"failure": "invalid_request"}
    if not isinstance(page_size, int) or not 1 <= page_size <= 100:
        return {"failure": "invalid_request"}
    if not isinstance(q, str) or len(q) > 200:
        return {"failure": "invalid_request"}
    if collection in ("bili_hot_memes", "pgr"):
        return {"status": "source_unavailable", "reason": "collection_not_available", "data": None}
    if collection == "community_terms":
        rows = _community_term_rows()
        needle = _normalize(q)
        if needle:
            rows = [
                row for row in rows
                if needle in _normalize(row["term"])
                or any(needle in _normalize(alias) for alias in row["aliases"])
            ]
    elif collection == "kb_docs":
        rows = _kb_doc_rows(q)
    elif collection == "meme_tags":
        rows = _meme_tag_rows(q)
    else:
        rows = _acg_rows(q)
    start = (page - 1) * page_size
    return {
        "status": "ok",
        "source": f"knowledge_terms:{collection}",
        "data": {
            "collection": collection,
            "page": page,
            "page_size": page_size,
            "total": len(rows),
            "items": rows[start:start + page_size],
        },
    }


# ---------------------------------------------------------------------------
# 夹具：plugins（四组；event_matchers=诚实空态组）
# ---------------------------------------------------------------------------

_BUILTIN_FEATURES = [
    ("bot.chat", "人格对话", "CHAT", True, False),
    ("bot.affinity", "好感度", "AFFINITY", True, False),
    ("bot.weather", "天气查询", "WEATHER", True, False),
    ("bot.music", "点歌", "MUSIC", True, False),
    ("bot.market", "全球股指", "MARKET", True, False),
    ("bot.media_archive", "媒体归档", "MEDIA_ARCHIVE", True, False),
    ("bot.daily_assist", "日常助理", "DAILY_ASSIST", True, False),
    ("bot.campus", "校园转发", "CAMPUS", False, False),
]

_ADAPTERS = [
    ("OneBot V11", "nonebot-adapter-onebot (nonebot.adapters.onebot.v11)"),
    ("Telegram", "nonebot-adapter-telegram (nonebot.adapters.telegram)"),
]

_MIGRATED_DOMAINS = [
    ("assistant", 9), ("chat_reply", 83), ("core", 40), ("creation", 8),
    ("divination", 21), ("files", 9), ("finance", 13), ("food", 5),
    ("link_parse", 47), ("location", 11), ("media", 18), ("meme", 12),
    ("music", 7), ("notes", 5), ("ops", 40), ("render", 14),
    ("schedule", 19), ("subscribe", 25), ("transport", 14), ("weather", 6),
]


def plugins_catalog() -> dict:
    builtins = {
        "id": "builtins",
        "name": "内置功能",
        "description": "能力树/features store 聚合视图",
        "source": "features_store",
        "enabled": True,
        "reason": None,
        "items": [
            {
                "id": feature_id,
                "name": name,
                "description": kind,
                "kind": "capability",
                "enabled": enabled,
                "hot_reload": hot,
                "source": "features_store",
            }
            for feature_id, name, kind, enabled, hot in _BUILTIN_FEATURES
        ],
    }
    adapters = {
        "id": "adapters",
        "name": "协议适配器",
        "description": "pyproject [tool.nonebot.adapters] 静态声明",
        "source": "static_config",
        "enabled": True,
        "reason": None,
        "items": [
            {
                "name": name,
                "description": desc,
                "enabled": True,
                "hot_reload": False,
                "source": "static_config",
            }
            for name, desc in _ADAPTERS
        ],
    }
    event_matchers = {
        "id": "event_matchers",
        "name": "事件 matcher",
        "description": "bot 宿主进程内的事件 matcher 注册表",
        "source": "none",
        "enabled": False,
        "reason": "cross_process_introspection_unavailable",
        "items": [],
    }
    migrated = {
        "id": "migrated_modules",
        "name": "板块重组域清单",
        "description": "domains/ 目录清单（v21r2 板块重组）",
        "source": "filesystem",
        "enabled": True,
        "reason": None,
        "items": [
            {
                "name": name,
                "description": f"{count} 个模块",
                "source": "filesystem",
                "hot_reload": False,
                "enabled": None,
                "module_count": count,
                "entry_file_exists": True,
            }
            for name, count in _MIGRATED_DOMAINS
        ],
    }
    return {
        "status": "ok",
        "source": "plugins_catalog",
        "data": {"groups": [builtins, adapters, event_matchers, migrated]},
    }


# ---------------------------------------------------------------------------
# 夹具：memory/graph（五类型节点齐全 + 六统计；装配口径=webui_memory_graph 同款）
# ---------------------------------------------------------------------------

# (session_id, sender_id, turns)
_GRAPH_TURNS = [
    ("private_777", "777", 6),
    ("private_10001", "10001", 3),
    ("group_1108838060_3865067623", "3865067623", 12),
    ("group_1108838060_777", "777", 4),
    ("group_662948429_1722380002", "1722380002", 5),
    ("group_662948429_20002", "20002", 2),
]
# (fact_id, subject, text)
_GRAPH_FACTS = [
    ("f-001", "3865067623", "是群白名单第一批群的管理员，常在深夜整点来对账"),
    ("f-002", "777", "偏好在晚间进行长对话，喜欢被叫「澜汐」"),
    ("f-003", "1722380002", "负责维护校园号采集侧的脚本与扫码"),
    ("f-004", "10001", "喜欢点歌和天气预报，偶尔问行情"),
]
# (quirk_id, text, scope_kind, scope_key)
_GRAPH_QUIRKS = [
    ("q-001", "习惯用「在吗」开头", "user", "3865067623"),
    ("q-002", "深夜对话偏好更轻的语气", "global", ""),
]
_GRAPH_AFFINITY = {  # sender -> (值, 昵称)
    "3865067623": (0.92, "岸宝"),
    "1722380002": (0.84, "霞月"),
    "777": (0.71, "澜汐"),
    "10001": (0.55, ""),
    "20002": (0.63, "浮玉"),
}
_LABEL_MAX_CHARS = 80


def memory_graph(window: str, max_nodes: int) -> dict:
    if not isinstance(window, str) or window not in ("24h", "7d", "30d", "all"):
        return {"failure": "invalid_request"}
    if not isinstance(max_nodes, int) or not 1 <= max_nodes <= 200:
        return {"failure": "invalid_request"}

    persons: dict = {}
    conversations: dict = {}
    groups: dict = {}
    for session, sender, turns in _GRAPH_TURNS:
        person = persons.setdefault(sender, {"turns": 0, "affinity": None, "nickname": ""})
        person["turns"] += turns
        conversations[session] = conversations.get(session, 0) + turns
        parts = session.split("_")
        if len(parts) == 3 and parts[0] == "group" and parts[1].isdigit():
            groups[parts[1]] = groups.get(parts[1], 0) + turns
    host_weights: dict = {}
    for session, count in conversations.items():
        parts = session.split("_")
        if len(parts) == 3 and parts[0] == "group" and parts[1].isdigit():
            host_weights[(parts[1], session)] = count
    group_hosts = [(gid, session, n) for (gid, session), n in sorted(host_weights.items())]

    for sender, (value, nickname) in _GRAPH_AFFINITY.items():
        person = persons.setdefault(sender, {"turns": 0, "affinity": None, "nickname": ""})
        person["affinity"] = value
        person["nickname"] = nickname

    speaker_count = sum(1 for person in persons.values() if person["turns"] > 0)
    learned_rules = len(_GRAPH_QUIRKS) + sum(1 for _, nick in _GRAPH_AFFINITY.values() if nick.strip())

    nodes: list[dict] = []
    edges: list[dict] = []

    def add_edge(source: str, target: str, kind: str, weight: int) -> None:
        edges.append({"source": source, "target": target, "kind": kind, "weight": weight})

    for sender in sorted(persons):
        person = persons[sender]
        weight = person["affinity"]
        nodes.append({
            "id": f"person:{sender}",
            "type": "person",
            "label": person["nickname"] or sender,
            "weight": round(weight, 4) if weight is not None else None,
        })
    for gid in sorted(groups):
        nodes.append({"id": f"group:{gid}", "type": "group", "label": f"群 {gid}", "weight": groups[gid]})
    for session in sorted(conversations):
        nodes.append({"id": f"conv:{session}", "type": "conversation", "label": session, "weight": conversations[session]})
    for fact_id, subject, text in sorted(_GRAPH_FACTS):
        nodes.append({
            "id": f"memory:{fact_id}",
            "type": "memory",
            "label": text.strip()[:_LABEL_MAX_CHARS],
            "weight": 1,
        })
    for quirk_id, text, _kind, _key in sorted(_GRAPH_QUIRKS):
        nodes.append({
            "id": f"rule:quirk:{quirk_id}",
            "type": "rule",
            "label": text.strip()[:_LABEL_MAX_CHARS],
            "weight": 1,
        })
    for sender in sorted(_GRAPH_AFFINITY):
        nickname = _GRAPH_AFFINITY[sender][1].strip()
        if nickname:
            nodes.append({
                "id": f"rule:nick:{sender}",
                "type": "rule",
                "label": f"已学昵称：{nickname}",
                "weight": 1,
            })

    person_turns: dict = {}
    for session, sender, turns in _GRAPH_TURNS:
        bucket = person_turns.setdefault(sender, {})
        bucket[session] = bucket.get(session, 0) + turns
    for sender in sorted(person_turns):
        for session in sorted(person_turns[sender]):
            add_edge(f"person:{sender}", f"conv:{session}", "speaks_in", person_turns[sender][session])
    for gid, session, weight in group_hosts:
        add_edge(f"group:{gid}", f"conv:{session}", "hosts", weight)
    for fact_id, subject, _text in sorted(_GRAPH_FACTS):
        add_edge(f"person:{subject}", f"memory:{fact_id}", "about", 1)
    for quirk_id, _text, kind, key in sorted(_GRAPH_QUIRKS):
        if kind == "user" and key in persons:
            add_edge(f"person:{key}", f"rule:quirk:{quirk_id}", "learned_rule", 1)
    for sender in sorted(_GRAPH_AFFINITY):
        if _GRAPH_AFFINITY[sender][1].strip():
            add_edge(f"person:{sender}", f"rule:nick:{sender}", "nickname", 1)

    degrees: dict = {}
    for edge in edges:
        degrees[edge["source"]] = degrees.get(edge["source"], 0) + 1
        degrees[edge["target"]] = degrees.get(edge["target"], 0) + 1
    nodes.sort(key=lambda node: (-degrees.get(node["id"], 0), node["id"]))
    edges.sort(key=lambda edge: (edge["source"], edge["target"], edge["kind"]))

    nodes_total = len(nodes)
    truncated = nodes_total > max_nodes
    if truncated:
        kept = {node["id"] for node in nodes[:max_nodes]}
        nodes = nodes[:max_nodes]
        edges = [edge for edge in edges if edge["source"] in kept and edge["target"] in kept]

    return {
        "status": "ok",
        "source": "memory_graph",
        "data": {
            "window": window,
            "max_nodes": max_nodes,
            "truncated": truncated,
            "nodes_total": nodes_total,
            "stats": {
                "persons": len(persons),
                "groups": len(groups),
                "conversations": len(conversations),
                "long_term_memories": len(_GRAPH_FACTS),
                "learned_rules": learned_rules,
                "speaker_count": speaker_count,
            },
            "nodes": nodes,
            "edges": edges,
            "sources": {"history": "ok", "memory": "ok", "quirks": "ok", "affinity": "ok"},
        },
    }


# ---------------------------------------------------------------------------
# 夹具：logs（12 条固定事件 + 流式轮换摘要）
# ---------------------------------------------------------------------------

# (cursor, created_at, source, category, details)
_LOG_EVENTS_RAW = [
    (101, "2026-09-18T11:30:02.000+00:00", "bot", "info", {"summary": "bot 在线，WS 反向连接已建立", "gateway": "127.0.0.1:3001"}),
    (102, "2026-09-18T11:33:41.000+00:00", "llm", "info", {"summary": "主路由 gemini-3.8-flash 命中", "ema_ms": 11640}),
    (103, "2026-09-18T11:36:18.000+00:00", "capability", "success", {"summary": "能力完成", "capability_id": "bot.weather"}),
    (104, "2026-09-18T11:39:55.000+00:00", "scheduler", "warning", {"summary": "群摘要白名单为空，今夜推送跳过"}),
    (105, "2026-09-18T11:42:11.000+00:00", "database", "info", {"summary": "发送队列 pending=0，断点续发无残留"}),
    (106, "2026-09-18T11:45:29.000+00:00", "renderer", "debug", {"summary": "卡片渲染 warm 2222ms", "budget_ms": 1500}),
    (107, "2026-09-18T11:48:03.000+00:00", "sender", "warning", {"summary": "QQ 发送回执 UNKNOWN，等待确认对账", "part_id": "p-2077"}),
    (108, "2026-09-18T11:50:47.000+00:00", "napcat", "error", {"summary": "NapCat 心跳超时 45s，触发重连"}),
    (109, "2026-09-18T11:53:12.000+00:00", "telegram", "success", {"summary": "TG getUpdates 韧性退避恢复"}),
    (110, "2026-09-18T11:55:38.000+00:00", "pipeline", "info", {"summary": "摄取段归一完成", "quote_depth": 3}),
    (111, "2026-09-18T11:57:24.000+00:00", "control_plane", "critical", {"summary": "审计库写入失败，已降级内存实现"}),
    (112, "2026-09-18T11:59:58.000+00:00", "llm", "detail", {"summary": "计费账本窗口汇总", "families": 4, "unpriced": 0}),
]

_LOG_EVENTS: dict[int, dict] = {}
_LOG_BY_EVENT_ID: dict[str, dict] = {}
for _cursor, _created, _source, _category, _details in _LOG_EVENTS_RAW:
    _item = {
        "cursor": _cursor,
        "event_id": _event_uuid(_cursor),
        "created_at": _created,
        "source": _source,
        "category": _category,
        "message": _EVENT_MESSAGES[_category],
        "details": _details,
    }
    _LOG_EVENTS[_cursor] = _item
    _LOG_BY_EVENT_ID[_item["event_id"]] = _item

# 流式轮换摘要（每 2s 一条，循环使用）
_LIVE_SUMMARIES = [
    ("bot", "info", {"summary": "【mock 实时】发送队列心跳 pending=0"}),
    ("llm", "info", {"summary": "【mock 实时】渠道 axon-gemini-3.8-flash EMA 11.6s"}),
    ("renderer", "debug", {"summary": "【mock 实时】渲染预算余量充足"}),
    ("sender", "success", {"summary": "【mock 实时】出站回执确认 OK"}),
]

_EVENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}\Z")
_CURSOR_RE = re.compile(r"[0-9]{1,19}\Z")


def _parse_cursor(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and _CURSOR_RE.fullmatch(value) and int(value) <= 2**63 - 1:
        return int(value)
    return None


def logs_query(after, limit, source, category) -> dict:
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        return {"failure": "invalid_query"}
    if after is not None and (not isinstance(after, int) or not 0 <= after <= 2**63 - 1):
        return {"failure": "invalid_query"}
    if after is not None and after < RETENTION_FLOOR:
        return {"failure": "cursor_expired"}
    if after is not None and after > HIGH_CURSOR:
        return {"failure": "invalid_query"}
    if (source is not None and source not in _EVENT_SOURCES) or (
        category is not None and category not in _EVENT_CATEGORIES
    ):
        return {"failure": "invalid_query"}
    start = RETENTION_FLOOR if after is None else after
    matched = [
        item for cursor, item in sorted(_LOG_EVENTS.items())
        if cursor > start
        and (source is None or item["source"] == source)
        and (category is None or item["category"] == category)
    ]
    items = matched[:limit]
    more = len(matched) > limit
    return {
        "data": {
            "items": items,
            "next_cursor": items[-1]["cursor"] if more else HIGH_CURSOR,
            "has_more": more,
            "high_cursor": HIGH_CURSOR,
        }
    }


def logs_sources() -> dict:
    return {
        "items": list(_EVENT_SOURCES),
        "categories": list(_EVENT_CATEGORIES),
        "collector_status": "not_connected",
        "collectors": {
            "stdlib": "not_connected",
            "nonebot": "not_connected",
            "napcat": "not_connected",
            "raw_content": False,
            "publish_failures": 0,
        },
    }


def logs_detail(event_id: str):
    if not isinstance(event_id, str) or not _EVENT_ID_RE.fullmatch(event_id):
        return {"failure": "invalid_event_id"}
    item = _LOG_BY_EVENT_ID.get(event_id)
    if item is None:
        return {"failure": "event_not_found"}
    return {"data": item}


def live_event(cursor: int) -> dict:
    """流式轮换摘要事件（确定性：cursor → 固定内容）。"""
    index = (cursor - HIGH_CURSOR - 1) % len(_LIVE_SUMMARIES)
    source, category, details = _LIVE_SUMMARIES[index]
    minute = 0 + (cursor % 60)
    return {
        "cursor": cursor,
        "event_id": _event_uuid(cursor),
        "created_at": f"2026-09-18T12:{minute:02d}:00.000+00:00",
        "source": source,
        "category": category,
        "message": _EVENT_MESSAGES[category],
        "details": details,
    }


# ---------------------------------------------------------------------------
# /ui 夹具壳（固定字节；真实端=webui/dist/index.html 单文件产物）
# ---------------------------------------------------------------------------

_UI_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>守岸人 WebUI — Mock 壳</title></head>
<body>
<h1>守岸人 WebUI Mock 壳（夹具）</h1>
<p>本页面是 scripts/webui_mock_server.py 的内置夹具壳，仅供目验，不是真实 WebUI 产物。</p>
<ul>
<li>GET /api/v1/stats/calls?window=24h&amp;bucket=hour&amp;limit=10</li>
<li>GET /api/v1/stats/tokens?window=24h&amp;limit=20</li>
<li>GET /api/v1/stats/latency</li>
<li>GET /api/v1/affinity/board?limit=50&amp;order=desc</li>
<li>GET /api/v1/knowledge/collections</li>
<li>GET /api/v1/knowledge/terms?collection=community_terms&amp;q=&amp;page=1&amp;page_size=20</li>
<li>GET /api/v1/plugins</li>
<li>GET /api/v1/memory/graph?window=24h&amp;max_nodes=120</li>
<li>GET /api/v1/logs?limit=50</li>
<li>GET /api/v1/logs/sources</li>
<li>GET /api/v1/logs/stream（text/event-stream）</li>
<li>GET /admin/api/v1/health</li>
<li>GET /admin/api/v1/status/bot</li>
<li>GET /admin/api/v1/status/models</li>
</ul>
</body></html>
"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class MockControlPlaneServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, bearer_mode: bool, delay_ms: int) -> None:
        super().__init__(address, handler)
        self.bearer_mode = bearer_mode
        self.delay_ms = delay_ms


class MockHandler(BaseHTTPRequestHandler):
    server_version = "MockUI/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # 确定性：连 HTTP Date 头也固定（真实端为当前时刻）。
    def date_time_string(self, timestamp=None):
        return FIXED_HTTP_DATE

    # ---- 基础输出 ----

    def _cors_headers(self) -> dict[str, str]:
        # 【安全边界，SECWEB Minor-3】以下 CORS 头只属于本地开发联调夹具（vite dev 5174 → 本 mock 8743）：
        # 本服务器仅绑 127.0.0.1、仅 GET/OPTIONS 只读、数据全为合成假数据，ACAO:* 风险≈0。
        # 禁止把这套 CORS 头复制进真实控制面——否则任意网页可携 Authorization 头打 loopback API。
        return {
            # 仅 mock 假数据联调用；禁止复制进真实控制面（见上方安全边界注释）。
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, Last-Event-ID",
            "Access-Control-Expose-Headers": "X-Request-ID",
            "Access-Control-Max-Age": "600",
        }

    def _send_bytes(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        try:
            self.send_response(status)
            for key, value in self._cors_headers().items():
                self.send_header(key, value)
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True

    def _send_json(self, status: int, payload: dict, request_id: str) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(
            status,
            body,
            "application/json",
            {"X-Request-ID": request_id, "Cache-Control": "no-store"},
        )

    def _send_error_cp(self, status: int, code: str, message: str) -> None:
        request_id, _trace, debug_id = _request_ids(self.command, self.path, "")
        self._send_json(
            status,
            error_payload(status=status, code=code, message=message, request_id=request_id, debug_id=debug_id),
            request_id,
        )

    def _envelope_ok(self, service_result: dict, invalid_code: str) -> None:
        """服务层结果投影：invalid_request → 422，其余 200 信封内如实降级。"""
        request_id, _trace, _dbg = _request_ids("GET", self.path, self._raw_query)
        if service_result.get("failure") == "invalid_request":
            self._send_invalid(invalid_code, request_id)
            return
        self._send_json(200, envelope(service_result, request_id=request_id), request_id)

    # ---- 校验辅助 ----

    _INVALID_MESSAGES: typing.ClassVar[dict[str, str]] = {
        "stats_invalid_query": "统计查询参数无效。",
        "knowledge_invalid_query": "查询参数无效。",
        "plugins_invalid_query": "查询参数无效。",
        "memory_graph_invalid_query": "查询参数无效。",
        "invalid_query": "事件筛选或分页参数无效。",
    }

    def _send_invalid(self, code: str, request_id: str) -> None:
        self._send_error_payload(
            422, code, self._INVALID_MESSAGES.get(code, "查询参数无效。"), request_id
        )

    def _send_error_payload(self, status: int, code: str, message: str, request_id: str) -> None:
        _r, _t, debug_id = _request_ids("ERR|" + code, self.path, self._raw_query)
        self._send_json(
            status,
            error_payload(status=status, code=code, message=message, request_id=request_id, debug_id=debug_id),
            request_id,
        )

    def _auth_ok(self) -> bool:
        if not getattr(self.server, "bearer_mode", False):
            return True
        header = self.headers.get("Authorization") or ""
        return header.lower().startswith("bearer ") and bool(header[7:].strip())

    # ---- HTTP 方法 ----

    def do_OPTIONS(self):
        self._send_bytes(204, b"", "text/plain")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        self._raw_query = parsed.query
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        path = unquote(parsed.path)

        if getattr(self.server, "delay_ms", 0) > 0:
            time.sleep(self.server.delay_ms / 1000.0)

        if path == "/healthz":
            request_id, _t, _d = _request_ids("GET", path, self._raw_query)
            self._send_json(200, {"status": "ok", "service": "webui-mock"}, request_id)
            return
        if path == "/ui":
            self._send_bytes(200, _UI_HTML.encode("utf-8"), "text/html; charset=utf-8", {"Cache-Control": "no-store"})
            return
        if path == "/favicon.ico":
            self._send_bytes(404, b"", "text/plain")
            return

        if not path.startswith(("/api/", "/admin/api/v1/")):
            self._send_error_cp(404, "not_found", "请求的资源或操作不可用。")
            return
        if not self._auth_ok():
            self._send_error_cp(401, "unauthorized", "缺少或无效的 Bearer 凭据。")
            return

        try:
            self._route_api(path, params)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True

    # ---- API 路由 ----

    def _route_api(self, path: str, params: dict) -> None:
        request_id, _trace, _dbg = _request_ids("GET", self.path, self._raw_query)

        # /admin/api/v1/*（api/health.py）：legacy 裸体直出，不过 envelope。
        if path == "/admin/api/v1/health":
            self._send_json(200, health_report(), request_id)
            return

        if path == "/admin/api/v1/status/bot":
            self._send_json(200, status_bot(), request_id)
            return

        if path == "/admin/api/v1/status/models":
            self._send_json(200, status_models(), request_id)
            return

        if path == "/api/v1/stats/calls":
            limit = self._int_param(params.get("limit"), default=10)
            if limit is None:
                self._send_error_payload(422, "validation_error", "请求参数未通过校验。", request_id)
                return
            self._envelope_ok(
                stats_calls(
                    params.get("window", "24h"), params.get("bucket", "hour"), limit,
                ),
                "stats_invalid_query",
            )
            return

        if path == "/api/v1/stats/tokens":
            limit = self._int_param(params.get("limit"), default=20)
            if limit is None:
                self._send_error_payload(422, "validation_error", "请求参数未通过校验。", request_id)
                return
            self._envelope_ok(stats_tokens(params.get("window", "24h"), limit), "stats_invalid_query")
            return

        if path == "/api/v1/stats/latency":
            self._envelope_ok(stats_latency(), "stats_invalid_query")
            return

        if path == "/api/v1/affinity/board":
            limit = self._int_param(params.get("limit"), default=50)
            if limit is None:
                self._send_error_payload(422, "validation_error", "请求参数未通过校验。", request_id)
                return
            self._envelope_ok(affinity_board(limit, params.get("order", "desc")), "stats_invalid_query")
            return

        if path == "/api/v1/knowledge/collections":
            self._envelope_ok(knowledge_collections(), "knowledge_invalid_query")
            return

        if path == "/api/v1/knowledge/terms":
            page = self._int_param(params.get("page"), default=1)
            page_size = self._int_param(params.get("page_size"), default=20)
            if page is None or page_size is None:
                self._send_error_payload(422, "validation_error", "请求参数未通过校验。", request_id)
                return
            result = knowledge_terms(
                params.get("collection", ""), params.get("q", ""), page, page_size,
            )
            if result.get("failure") == "invalid_request":
                self._send_error_payload(422, "knowledge_invalid_query", "查询参数无效。", request_id)
                return
            self._send_json(200, envelope(result, request_id=request_id), request_id)
            return

        if path == "/api/v1/plugins":
            self._envelope_ok(plugins_catalog(), "plugins_invalid_query")
            return

        if path == "/api/v1/memory/graph":
            max_nodes = self._int_param(params.get("max_nodes"), default=120)
            if max_nodes is None:
                self._send_error_payload(422, "validation_error", "请求参数未通过校验。", request_id)
                return
            result = memory_graph(params.get("window", "24h"), max_nodes)
            if result.get("failure") == "invalid_request":
                self._send_error_payload(422, "memory_graph_invalid_query", "查询参数无效。", request_id)
                return
            self._send_json(200, envelope(result, request_id=request_id), request_id)
            return

        if path == "/api/v1/logs":
            limit = _parse_cursor(params.get("limit", "50"))
            after = _parse_cursor(params.get("after"))
            limit_raw, after_raw = params.get("limit", "50"), params.get("after")
            if (limit_raw is not None and limit is None) or (after_raw is not None and after is None):
                self._send_error_payload(422, "invalid_query", "事件筛选或分页参数无效。", request_id)
                return
            result = logs_query(
                after, 50 if limit is None else limit,
                params.get("source"), params.get("category"),
            )
            if result.get("failure") == "invalid_query":
                self._send_error_payload(422, "invalid_query", "事件筛选或分页参数无效。", request_id)
            elif result.get("failure") == "cursor_expired":
                self._send_error_payload(410, "cursor_expired", "游标已超出保留窗口，请明确选择重新订阅。", request_id)
            else:
                self._send_json(200, envelope(result["data"], request_id=request_id), request_id)
            return

        if path == "/api/v1/logs/sources":
            self._envelope_ok(logs_sources(), "invalid_query")
            return

        if path == "/api/v1/logs/stream":
            self._handle_stream(params)
            return

        if path.startswith("/api/v1/logs/"):
            result = logs_detail(path[len("/api/v1/logs/"):])
            if result.get("failure") == "invalid_event_id":
                self._send_error_payload(422, "invalid_event_id", "事件标识无效。", request_id)
            elif result.get("failure") == "event_not_found":
                self._send_error_payload(404, "event_not_found", "事件不存在或已超出保留窗口。", request_id)
            else:
                self._send_json(200, envelope(result["data"], request_id=request_id), request_id)
            return

        self._send_error_cp(404, "not_found", "请求的资源或操作不可用。")

    @staticmethod
    def _int_param(raw, default: int | None = None) -> int | None:
        """缺省 → default；非整数 → None（调用方判为 validation_error）。"""
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    # ---- SSE 流 ----

    def _handle_stream(self, params: dict) -> None:
        request_id, _trace, debug_id = _request_ids("GET", self.path, self._raw_query)

        def stream_error(status: int, code: str, message: str) -> None:
            self._send_json(
                status,
                error_payload(status=status, code=code, message=message, request_id=request_id, debug_id=debug_id),
                request_id,
            )

        heartbeat_raw = params.get("heartbeat", "15")
        try:
            if len(str(heartbeat_raw)) > 16:
                raise ValueError
            heartbeat_seconds = float(heartbeat_raw)
            if not 0.01 <= heartbeat_seconds <= 60:
                raise ValueError
        except ValueError:
            stream_error(422, "invalid_cursor", "游标或事件筛选参数无效。")
            return

        raw_cursor = self.headers.get("last-event-id")
        cursor_source = raw_cursor if raw_cursor is not None else params.get("after")
        cursor = _parse_cursor(cursor_source)
        if cursor_source is not None and cursor is None:
            stream_error(422, "invalid_cursor", "游标或事件筛选参数无效。")
            return
        if cursor is not None and cursor < RETENTION_FLOOR:
            stream_error(410, "cursor_expired", "游标已超出保留窗口，请明确选择重新订阅。")
            return
        if cursor is not None and cursor > 2**40:
            # 真实端 after > high_watermark 直接 422；mock 放行常规重连游标
            # （含流式 live cursor），只拒绝明显荒谬的值。
            stream_error(422, "invalid_cursor", "游标或事件筛选参数无效。")
            return
        source = params.get("source")
        category = params.get("category")
        if (source is not None and source not in _EVENT_SOURCES) or (
            category is not None and category not in _EVENT_CATEGORIES
        ):
            stream_error(422, "invalid_cursor", "游标或事件筛选参数无效。")
            return

        # 初始重放页：cursor 之后的固定事件（≤100 条，真实端同款有界单页）。
        start = cursor if cursor is not None else None
        replay = [
            item for item_cursor, item in sorted(_LOG_EVENTS.items())
            if (start is None or item_cursor > start)
            and (source is None or item["source"] == source)
            and (category is None or item["category"] == category)
        ][:100]

        self.send_response(200)
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("X-Request-ID", request_id)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        self.close_connection = True

        def chunk(payload: bytes) -> bool:
            try:
                self.wfile.write(f"{len(payload):x}\r\n".encode("ascii") + payload + b"\r\n")
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        def frame(item: dict) -> bytes:
            body = envelope(item, request_id=request_id)
            data = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            return f"id: {item['cursor']}\nevent: log\ndata: {data}\n\n".encode()

        for item in replay:
            if not chunk(frame(item)):
                return

        # 实时段：每 2s 一条轮换摘要；心跳按 heartbeat 参数。
        live_cursor = max(cursor if cursor is not None else HIGH_CURSOR, HIGH_CURSOR)
        next_summary = time.monotonic() + _SSE_SUMMARY_INTERVAL_SECONDS
        next_heartbeat = time.monotonic() + heartbeat_seconds
        while True:
            now = time.monotonic()
            if now >= next_summary:
                live_cursor += 1
                if not chunk(frame(live_event(live_cursor))):
                    return
                next_summary += _SSE_SUMMARY_INTERVAL_SECONDS
                continue
            if now >= next_heartbeat:
                if not chunk(b": heartbeat\n\n"):
                    return
                next_heartbeat += heartbeat_seconds
                continue
            time.sleep(max(0.0, min(next_summary, next_heartbeat) - time.monotonic()))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="webui_mock_server.py",
        description="守岸人 WebUI 离线确定性夹具后端（仅供前端开发/目验，绝不接入生产链路）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1，仅回环）")
    parser.add_argument("--port", type=int, default=8743, help="监听端口（默认 8743，避开真实控制面 8742）")
    parser.add_argument("--delay-ms", type=int, default=0, help="每个非流式响应前的模拟延迟（毫秒，默认 0）")
    parser.add_argument(
        "--bearer",
        metavar="MODE",
        default=None,
        help="'any' = 开启认证存在性校验：/api/* 请求必须带 Authorization: Bearer 头（任意值），否则 401",
    )
    args = parser.parse_args(argv)

    bearer_mode = args.bearer is not None
    if bearer_mode and args.bearer != "any":
        parser.error("--bearer 目前仅支持 'any'")

    server = MockControlPlaneServer(
        (args.host, args.port), MockHandler,
        bearer_mode=bearer_mode, delay_ms=max(0, args.delay_ms),
    )
    print(
        f"webui_mock_server: http://{args.host}:{args.port}/ui"
        f"  (bearer={'any' if bearer_mode else 'off'}, delay_ms={args.delay_ms})",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
