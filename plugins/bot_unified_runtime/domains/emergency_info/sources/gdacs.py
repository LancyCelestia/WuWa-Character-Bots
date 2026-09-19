"""GDACS（联合国全球灾害预警与协调体系）采集件（B2 席，限背景聚合）。

对应 E11 §2 矩阵 #14：旧 `gdacsapi/api/events/geteventlist/MAP|ALL|EQ` 已
400/404（`MAP` 原文 `"Eventtype is required."`），**可用匿名端点是
`www.gdacs.org/gdacsapi/api/Events/geteventlist/allpaging`**（200 / 2.7s /
63,829B，E11 §5.5）。判定=「只做背景聚合，不做推送」，本文件因此：

- 不产出任何投递字段，只出条目 + 状态；
- **不猜等级**：GDACS 的 `alertlevel` 是 Red/Orange/Green 三档，与本项目
  红/橙/黄/蓝（D-3）不同集。Red→红色、Orange→橙色；**Green 故意不映射**
  （Green 语义是「未发布警报」，映射成黄色会凭空造出一个档位）⇒
  `color_label=""`，由上层按「无等级」处理。未知等级同此处理。

真样例事实（`probes/samples/gdacs_eventlist.sample.json` 63,829B）：
`features` 共 101 条，**首条只有 `properties.meta.maxelement`**（GDACS 自己塞的
元信息条目，不是事件）⇒ 解析按「缺 eventid 即丢弃」处理并计入 `dropped=1`，
其余 100 条有效；实测种类分布 WF84/EQ9/FL5/TC2，`alertlevel` 全为 Green、
`alertscore` 全为 1。时间字段（`fromdate`/`todate`/`datemodified`）是**无时区
后缀的 ISO 串**，GDACS 文档未在本席实测范围内（E11 §6 自认「全量语义未逐字段
核完」）⇒ 本件按 UTC 读取并在 `notes` 里显式留 `gdacs_time_tz_assumed_utc`
标记，卡面显示前必须由上层把它当「未核实口径」而不是既成事实。

样板坐标：三态与 URL 双闸见 `http_get.py` 头注；`dropped`/`total_hint` 语义同
`nmc_alarm.py`。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .http_get import (
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_TIMEOUT_SECONDS,
    FetchJson,
    FetchState,
    SourceOutcome,
    failed_outcome,
    resolve_document,
)

SOURCE_ID = "gdacs"
SOURCE_LABEL = "GDACS（联合国灾害预警与协调体系）"

GDACS_ORIGIN = "https://www.gdacs.org"
GDACS_EVENT_LIST_URL = f"{GDACS_ORIGIN}/gdacsapi/api/Events/geteventlist/allpaging"

UTC_TZ = timezone.utc
# 上层显示口径（避免各消费方自己手写 timedelta(hours=8)）。
BEIJING_TZ = timezone(timedelta(hours=8), "UTC+8")

# 已见等级 → 本项目颜色词。Green 故意缺席（见模块头注）。
ALERT_LEVEL_COLOR: dict[str, str] = {"Red": "红色", "Orange": "橙色"}

# 种类码 → 中文：只收录真样例实测出现的四种（WF/EQ/FL/TC）。
# 其余种类码原样透出，不猜中文（D-1 无源诚实不接）。
EVENT_TYPE_LABEL: dict[str, str] = {
    "WF": "野火",
    "EQ": "地震",
    "FL": "洪水",
    "TC": "热带气旋",
}


@dataclass(frozen=True)
class GdacsEvent:
    """一条 GDACS 事件（背景聚合用；缺 eventid/eventtype/name 即丢弃）。"""

    event_id: str
    event_type: str
    event_type_label: str
    name: str
    description: str
    alert_level: str
    color_label: str
    alert_score: int | None
    country: str
    iso3: str
    from_at: datetime | None
    to_at: datetime | None
    modified_at: datetime | None
    latitude: float | None
    longitude: float | None
    icon_url: str


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _opt_float(value: Any) -> float | None:
    try:
        text = _text(value)
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    try:
        text = _text(value)
        return int(float(text)) if text else None
    except (TypeError, ValueError):
        return None


def _parse_naive_iso_utc(value: Any) -> datetime | None:
    """`2026-09-19T12:19:55`（无时区后缀）→ UTC aware；形态非法即 None。

    显式不猜本地时区；口径未核实的诚实标注写在模块头注与 `notes`。
    """
    raw = _text(value)
    if not raw:
        return None
    text = raw.replace("Z", "")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC_TZ)
    return parsed.replace(tzinfo=UTC_TZ)


def parse_gdacs_events(payload: Any) -> SourceOutcome[GdacsEvent]:
    """GDACS allpaging 响应 → 事件清单（纯函数，吃真样例字节）。"""
    if not isinstance(payload, dict):
        return failed_outcome(SOURCE_ID, f"bad_envelope:{type(payload).__name__}")
    features = payload.get("features")
    if features is None or not isinstance(features, list):
        return failed_outcome(SOURCE_ID, "missing_field:features")

    items: list[GdacsEvent] = []
    dropped = 0
    unmapped_level = 0
    tz_assumed = False
    for feature in features:
        if not isinstance(feature, dict):
            dropped += 1
            continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            dropped += 1
            continue
        event_id = _text(props.get("eventid"))
        event_type = _text(props.get("eventtype"))
        name = _text(props.get("name"))
        if not event_id or not event_type or not name:
            # GDACS 的元信息条目（只带 properties.meta）从这里被丢掉。
            dropped += 1
            continue
        alert_level = _text(props.get("alertlevel"))
        color = ALERT_LEVEL_COLOR.get(alert_level, "")
        if alert_level and not color:
            unmapped_level += 1
        geometry = feature.get("geometry")
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        longitude = latitude = None
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            longitude, latitude = _opt_float(coords[0]), _opt_float(coords[1])
        from_at = _parse_naive_iso_utc(props.get("fromdate"))
        if props.get("fromdate") and from_at is not None:
            tz_assumed = True
        items.append(
            GdacsEvent(
                event_id=event_id,
                event_type=event_type,
                event_type_label=EVENT_TYPE_LABEL.get(event_type, event_type),
                name=name,
                description=_text(props.get("description")),
                alert_level=alert_level,
                color_label=color,
                alert_score=_opt_int(props.get("alertscore")),
                country=_text(props.get("country")),
                iso3=_text(props.get("iso3")),
                from_at=from_at,
                to_at=_parse_naive_iso_utc(props.get("todate")),
                modified_at=_parse_naive_iso_utc(props.get("datemodified")),
                latitude=latitude,
                longitude=longitude,
                icon_url=_text(props.get("iconmap")),
            )
        )

    notes: list[str] = []
    if tz_assumed:
        notes.append("gdacs_time_tz_assumed_utc")
    if unmapped_level:
        notes.append(f"unmapped_alert_level={unmapped_level}")

    if items:
        return SourceOutcome(
            state=FetchState.OK,
            source_id=SOURCE_ID,
            items=tuple(items),
            total_hint=len(features),
            dropped=dropped,
            notes=tuple(notes),
        )
    if features:
        return SourceOutcome(
            state=FetchState.FAILED,
            source_id=SOURCE_ID,
            reason="all_entries_invalid",
            total_hint=len(features),
            dropped=dropped,
            notes=tuple(notes),
        )
    return SourceOutcome(
        state=FetchState.NO_DATA,
        source_id=SOURCE_ID,
        reason="no_active_event",
        total_hint=0,
        notes=tuple(notes),
    )


def fetch_gdacs_events(
    *,
    fetch: FetchJson | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    proxy: str = "",
    retry: int = DEFAULT_RETRY_ATTEMPTS,
) -> SourceOutcome[GdacsEvent]:
    """拉 GDACS 全量事件表（背景聚合；URL 是常量，仍过双闸）。"""
    doc = resolve_document(
        GDACS_EVENT_LIST_URL, fetch=fetch, timeout=timeout, proxy=proxy, retry=retry
    )
    if not doc.ok:
        return failed_outcome(SOURCE_ID, doc.failure, attempts=doc.attempts)
    return parse_gdacs_events(doc.payload)


__all__ = [
    "ALERT_LEVEL_COLOR",
    "EVENT_TYPE_LABEL",
    "GDACS_EVENT_LIST_URL",
    "GDACS_ORIGIN",
    "SOURCE_ID",
    "SOURCE_LABEL",
    "GdacsEvent",
    "fetch_gdacs_events",
    "parse_gdacs_events",
]

# 时间口径常备（上层换算北京时间用；避免各自手写 timedelta(hours=8)）
BEIJING_TZ = timezone(timedelta(hours=8), "UTC+8")
