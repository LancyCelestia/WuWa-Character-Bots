"""地震速报双源采集件：ICL（中国地震预警网联盟）+ USGS（B2 席）。

对应 E11 §2 矩阵判「接」的三行：

- #6 **ICL** `mobile-new.chinaeew.cn/v1/earlywarnings`（200 匿名 JSON，E11 §5.3
  实测 3.5s / 4,232B）——**CENC 官网匿名接口已死**（`www.ceic.ac.cn/ajax/speedsearch`
  302→OSS `NoSuchKey`，E11 §5.1），故 ICL 是**降级代理源**。E11 §6 的红线：
  卡面来源必须写「ICL（中国地震预警网联盟）」，**不得冒充 CENC 官网口径**；
  本席把这条固化成 `SOURCE_ID="icl"` + `source_label` 常量，不给「cenc」留入口。
- #10 **USGS** `earthquake.usgs.gov` 两条通道：summary feed
  （`/earthquakes/feed/v1.0/summary/all_hour.geojson`，真样例 3,163B / 4 条）
  与 fdsnws 查询（`/fdsnws/event/1/query`，E11 §5.6 用中国矩形命中德钦 M4.5）。
  **fdsnws 的矩形参数必须是 min/max 四参**——`bbox=` 实测 400
  `Unknown parameter "bbox"`（E11 §5.6），本文件用 `build_usgs_fdsnws_url`
  把它锁成唯一种 URL 形态，并有回归用例盯着不出现 `bbox`。
- 交叉核验 `crosscheck_quakes`（E11 §3 裁定：主源 ICL、核验源 USGS，
  匹配键=发震时刻 ±30min 且震中距 ≤200km，匹配不上「各报各的并标注
  未获第二源确认」，**绝不静默择一**）。

时间口径（E11 §3 钉死）：两侧 epoch 毫秒一律按 **UTC 瞬间**解析成 aware
datetime（`origin_at`），显示时用 `.origin_at_beijing` 转 UTC+8 并在卡面标
「UTC+8」；不做 naive 本地时区猜测。真样例自检：ICL 首条 eventId 98395394
`startAt=1787531181614` → 北京 2026-08-24 08:26:21，USGS `metadata.generated`
→ 北京 2026-09-20 00:47:00（与 E11 实测时点 00:15—01:00 UTC+8 吻合）。

安全与状态：URL 全为常量白名单，仍逐次过 `http_get.guard_outbound_url`
（常量白名单 → 既有 `ssrf_guard.guard_user_url`）；三态语义与「无数据≠取数失败」
见 `http_get.py` 头注与 report §3。

样板坐标：`min_magnitude` 之类的「过滤后零命中」判 `NO_DATA`（源端确有数据、
只是不满足条件），与「响应结构塌了」判 `FAILED` 分离；退避/超时命名同
`http_get.py` 头注所列正例。
"""

from __future__ import annotations

import math
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

ICL_SOURCE_ID = "icl"
USGS_SOURCE_ID = "usgs"

# 卡面来源口径（E11 §6 红线：ICL 是降级代理源，不得冒充 CENC）。
ICL_SOURCE_LABEL = "ICL（中国地震预警网联盟）"
USGS_SOURCE_LABEL = "USGS（美国地质调查局）"

ICL_ORIGIN = "https://mobile-new.chinaeew.cn"
USGS_ORIGIN = "https://earthquake.usgs.gov"

# 中国矩形四至（E11 §4 签名裁定：minlat, minlon, maxlat, maxlon）。
CHINA_RECT: tuple[float, float, float, float] = (18.0, 73.0, 54.0, 135.0)

UTC_TZ = timezone.utc
BEIJING_TZ = timezone(timedelta(hours=8), "UTC+8")


# ---------------------------------------------------------------- 条目模型（本席自持）

@dataclass(frozen=True)
class QuakeEvent:
    """一条地震速报（ICL / USGS 共用形态；缺字段即丢弃，不填假值）。

    `station_count` 来自 ICL 源端拼写为 `sations` 的字段（E11 §4 注记「源端字段
    拼写需容错」），USGS 侧为 None（无该概念，不硬造 0）。
    """

    source_id: str
    event_id: str
    origin_at: datetime
    magnitude: float
    mag_type: str
    depth_km: float | None
    epicenter_text: str
    latitude: float
    longitude: float
    updates: int | None
    station_count: int | None
    url: str
    status: str
    label: str = ""

    @property
    def origin_at_beijing(self) -> datetime:
        """显示口径：统一转北京时间（卡面须标 UTC+8）。"""
        return self.origin_at.astimezone(BEIJING_TZ)

    @property
    def magnitude_display(self) -> str:
        """震级显示串（源端浮点噪声如 3.900001 → 「3.9」）。"""
        return f"{self.magnitude:.1f}"


@dataclass(frozen=True)
class QuakeMatch:
    """交叉核验的一对结果（E11 §3：两源并列，绝不静默择一）。"""

    primary: QuakeEvent
    secondary: QuakeEvent | None
    confirmed: bool
    distance_km: float | None = None
    time_delta_minutes: float | None = None

    @property
    def footnote(self) -> str:
        """卡面脚注串（两源并列 / 未获第二源确认）。"""
        if self.secondary is None or not self.confirmed:
            return (
                f"{self.primary.label or self.primary.source_id} "
                f"{self.primary.magnitude_display} 级——未获第二源确认"
            )
        return (
            f"{self.primary.label} {self.primary.magnitude_display} 级"
            f"｜{self.secondary.label} {self.secondary.magnitude_display} 级"
            f"——两源测定基准/速报时相不同，相距 "
            f"{(self.distance_km or 0):.0f}km、时差 "
            f"{(self.time_delta_minutes or 0):.0f} 分钟"
        )


# ---------------------------------------------------------------- 公共小工具

def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _opt_float(value: Any) -> float | None:
    try:
        text = _text(value)
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    try:
        text = _text(value)
        if not text:
            return None
        return int(float(text))
    except (TypeError, ValueError):
        return None


def epoch_ms_to_utc(value: Any) -> datetime | None:
    """epoch 毫秒 → UTC aware datetime；形态非法即 None（不猜、不造 1970）。"""
    raw = _opt_float(value)
    if raw is None or raw <= 0:
        return None
    if raw > 1e14:  # 明显不是毫秒（微秒级形态），拒绝而非折算
        return None
    try:
        return datetime.fromtimestamp(raw / 1000.0, tz=UTC_TZ)
    except (OverflowError, OSError, ValueError):
        return None


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """两点大圆距离（km）；交叉核验的半径门用。"""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    chord = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(min(1.0, math.sqrt(chord)))


# ---------------------------------------------------------------- ICL

def build_icl_earlywarnings_url(
    *, start_at_ms: int | None = None, updates: int = 10
) -> str:
    """ICL 速报 URL（形态=E11 §5.3 实测 200 的那一条：`?start_at=&updates=10`）。"""
    start = _text(start_at_ms) if start_at_ms is not None else ""
    count = max(1, int(updates))
    return f"{ICL_ORIGIN}/v1/earlywarnings?start_at={start}&updates={count}"


def _icl_to_event(entry: Any) -> tuple[QuakeEvent | None, str]:
    if not isinstance(entry, dict):
        return None, "not_object"
    event_id = _text(entry.get("eventId"))
    origin = epoch_ms_to_utc(entry.get("startAt"))
    magnitude = _opt_float(entry.get("magnitude"))
    latitude = _opt_float(entry.get("latitude"))
    longitude = _opt_float(entry.get("longitude"))
    if not event_id or origin is None or magnitude is None:
        return None, "missing_eventid_time_or_magnitude"
    if latitude is None or longitude is None:
        return None, "missing_coordinates"  # 经纬度是交叉核验的必要条件
    return (
        QuakeEvent(
            source_id=ICL_SOURCE_ID,
            event_id=event_id,
            origin_at=origin,
            magnitude=magnitude,
            mag_type="",  # ICL 不披露震级类型（不硬造 mw）
            depth_km=_opt_float(entry.get("depth")),
            epicenter_text=_text(entry.get("epicenter")),
            latitude=latitude,
            longitude=longitude,
            updates=_opt_int(entry.get("updates")),
            station_count=_opt_int(entry.get("sations")),  # 源端拼写如此
            url="",
            status="",
            label=ICL_SOURCE_LABEL,
        ),
        "",
    )


def parse_icl_earlywarnings(payload: Any) -> SourceOutcome[QuakeEvent]:
    """ICL 响应 → 速报清单（纯函数，吃 `icl_earlywarnings.sample.json`）。

    真样例（4,232B）：`code=0`、`message=""`、`data` 20 条，首条
    「四川长宁 M3.9 updates=5 sations=6」；第 3 条起部分条目无 `sations`
    （可选字段，缺即 None）。
    """
    if not isinstance(payload, dict):
        return failed_outcome(ICL_SOURCE_ID, f"bad_envelope:{type(payload).__name__}")
    code = _text(payload.get("code"))
    if code != "0":
        return failed_outcome(ICL_SOURCE_ID, f"source_error:code={payload.get('code')!r}")
    data = payload.get("data")
    if data is None:
        return failed_outcome(ICL_SOURCE_ID, "missing_field:data")
    if not isinstance(data, list):
        return failed_outcome(ICL_SOURCE_ID, "bad_type:data")

    items: list[QuakeEvent] = []
    dropped = 0
    for entry in data:
        event, _reason = _icl_to_event(entry)
        if event is None:
            dropped += 1
            continue
        items.append(event)
    if items:
        return SourceOutcome(
            state=FetchState.OK,
            source_id=ICL_SOURCE_ID,
            items=tuple(items),
            total_hint=len(data),
            dropped=dropped,
        )
    if not data:
        return SourceOutcome(
            state=FetchState.NO_DATA,
            source_id=ICL_SOURCE_ID,
            reason="no_earlywarning_in_window",
            total_hint=0,
        )
    return SourceOutcome(
        state=FetchState.FAILED,
        source_id=ICL_SOURCE_ID,
        reason="all_entries_invalid",
        total_hint=len(data),
        dropped=dropped,
    )


def fetch_icl_earthquakes(
    *,
    start_at_ms: int | None = None,
    updates: int = 10,
    fetch: FetchJson | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    proxy: str = "",
    retry: int = DEFAULT_RETRY_ATTEMPTS,
) -> SourceOutcome[QuakeEvent]:
    """拉 ICL 速报（E11 §4 签名：`fetch_icl_earthquakes(start_at=None, timeout=10.0)`）。"""
    url = build_icl_earlywarnings_url(start_at_ms=start_at_ms, updates=updates)
    doc = resolve_document(url, fetch=fetch, timeout=timeout, proxy=proxy, retry=retry)
    if not doc.ok:
        return failed_outcome(ICL_SOURCE_ID, doc.failure, attempts=doc.attempts)
    return parse_icl_earlywarnings(doc.payload)


# ---------------------------------------------------------------- USGS

def build_usgs_feed_url(window: str = "all_hour") -> str:
    """summary feed URL（真样例即 `all_hour`）。窗口名白名单化，不拼任意串。"""
    allowed = {
        "all_minute",
        "all_hour",
        "all_day",
        "all_week",
        "significant_week",
        "significant_month",
    }
    name = _text(window)
    if name not in allowed:
        raise ValueError(f"未知的 USGS feed 窗口：{name!r}")
    return f"{USGS_ORIGIN}/earthquakes/feed/v1.0/summary/{name}.geojson"


def build_usgs_fdsnws_url(
    *,
    start: datetime,
    end: datetime,
    min_magnitude: float = 4.0,
    rect: tuple[float, float, float, float] = CHINA_RECT,
) -> str:
    """fdsnws 查询 URL：**矩形用 min/max 四参**（`bbox` 实测 400，E11 §5.6）。

    参数顺序与命名对齐 USGS 文档形态：
    `?format=geojson&starttime=&endtime=&minlatitude=&minlongitude=&maxlatitude=&maxlongitude=&minmagnitude=`
    """
    min_lat, min_lon, max_lat, max_lon = (float(v) for v in rect)

    def stamp(moment: datetime) -> str:
        aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC_TZ)
        return aware.astimezone(UTC_TZ).strftime("%Y-%m-%dT%H:%M:%S")

    return (
        f"{USGS_ORIGIN}/fdsnws/event/1/query?format=geojson"
        f"&starttime={stamp(start)}&endtime={stamp(end)}"
        f"&minlatitude={min_lat}&minlongitude={min_lon}"
        f"&maxlatitude={max_lat}&maxlongitude={max_lon}"
        f"&minmagnitude={float(min_magnitude)}"
    )


def _usgs_to_event(feature: Any) -> tuple[QuakeEvent | None, str]:
    if not isinstance(feature, dict):
        return None, "not_object"
    props = feature.get("properties")
    if not isinstance(props, dict):
        return None, "missing_properties"
    geometry = feature.get("geometry")
    coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if not isinstance(coords, (list, tuple)) or len(coords) < 3:
        return None, "missing_geometry_coordinates"
    event_id = _text(feature.get("id")) or _text(props.get("id"))
    origin = epoch_ms_to_utc(props.get("time"))
    magnitude = _opt_float(props.get("mag"))
    longitude = _opt_float(coords[0])
    latitude = _opt_float(coords[1])
    if not event_id or origin is None or magnitude is None:
        # mag 为 null（火山/非震事件常见）⇒ 丢弃，不用 0.0 冒充。
        return None, "missing_id_time_or_magnitude"
    if latitude is None or longitude is None:
        return None, "bad_coordinates"
    depth = _opt_float(coords[2])
    return (
        QuakeEvent(
            source_id=USGS_SOURCE_ID,
            event_id=event_id,
            origin_at=origin,
            magnitude=magnitude,
            mag_type=_text(props.get("magType")),
            depth_km=depth,
            epicenter_text=_text(props.get("place")),
            latitude=latitude,
            longitude=longitude,
            updates=None,  # USGS 无修订号概念
            station_count=_opt_int(props.get("nst")),  # 台数：USGS 的对应概念
            url=_text(props.get("url")),
            status=_text(props.get("status")),  # automatic / verified / reviewed
            label=USGS_SOURCE_LABEL,
        ),
        "",
    )


def parse_usgs_geojson(
    payload: Any, *, min_magnitude: float | None = None
) -> SourceOutcome[QuakeEvent]:
    """USGS GeoJSON → 速报清单（feed 与 fdsnws 两通道同构，共用本函数）。

    真样例（`usgs_all_hour.sample.geojson` 3,163B）：`metadata.count=4`、
    4 条 features（M0.6 / M0.7 / M1.03 / M2.6，全为 automatic）。
    传 `min_magnitude=4.0` 时 4 条全部被过滤 ⇒ `NO_DATA` +
    `reason="filtered_out=4"`（**源端有数据但不满足条件**，不是取数失败）。
    """
    if not isinstance(payload, dict):
        return failed_outcome(USGS_SOURCE_ID, f"bad_envelope:{type(payload).__name__}")
    metadata = payload.get("metadata")
    features = payload.get("features")
    if features is None or not isinstance(features, list):
        return failed_outcome(USGS_SOURCE_ID, "missing_field:features")
    total_hint = _opt_int(metadata.get("count")) if isinstance(metadata, dict) else None
    notes: list[str] = []
    if total_hint is None:
        notes.append("metadata_count_absent")
    elif isinstance(metadata, dict) and _text(metadata.get("status")) not in ("", "200"):
        return SourceOutcome(
            state=FetchState.FAILED,
            source_id=USGS_SOURCE_ID,
            reason=f"source_error:metadata.status={metadata.get('status')!r}",
            total_hint=total_hint,
        )

    kept: list[QuakeEvent] = []
    dropped = 0
    filtered = 0
    for feature in features:
        event, _reason = _usgs_to_event(feature)
        if event is None:
            dropped += 1
            continue
        if min_magnitude is not None and event.magnitude < float(min_magnitude):
            filtered += 1
            continue
        kept.append(event)
    if filtered:
        notes.append(f"filtered_out={filtered}")

    if kept:
        return SourceOutcome(
            state=FetchState.OK,
            source_id=USGS_SOURCE_ID,
            items=tuple(kept),
            total_hint=total_hint,
            dropped=dropped,
            notes=tuple(notes),
        )
    if dropped:
        # 条目结构不成立 ⇒ 不可信，绝不是「无地震」。
        return SourceOutcome(
            state=FetchState.FAILED,
            source_id=USGS_SOURCE_ID,
            reason="all_entries_invalid",
            total_hint=total_hint,
            dropped=dropped,
            notes=tuple(notes),
        )
    # 结构成立、条目也成立，只是被震级门滤空 / 源端本就零条 ⇒ NO_DATA
    return SourceOutcome(
        state=FetchState.NO_DATA,
        source_id=USGS_SOURCE_ID,
        reason=(
            f"no_event_above_m{min_magnitude:g}"
            if min_magnitude is not None
            else "no_event_in_window"
        ),
        total_hint=total_hint if total_hint is not None else len(features),
        dropped=dropped,
        notes=tuple(notes),
    )


def fetch_usgs_quakes(
    *,
    min_magnitude: float = 4.0,
    rect: tuple[float, float, float, float] = CHINA_RECT,
    hours: int = 24,
    now: datetime | None = None,
    fetch: FetchJson | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    proxy: str = "",
    retry: int = DEFAULT_RETRY_ATTEMPTS,
) -> SourceOutcome[QuakeEvent]:
    """fdsnws 查询（E11 §4 签名：min_mag 4.0 + 中国矩形 + 滚动 24h）。

    `now` 为时钟注入点（离线测试确定性）；缺省取 UTC 当前瞬间。
    """
    end = now or datetime.now(tz=UTC_TZ)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC_TZ)
    start = end - timedelta(hours=max(1, int(hours)))
    url = build_usgs_fdsnws_url(
        start=start, end=end, min_magnitude=min_magnitude, rect=rect
    )
    doc = resolve_document(url, fetch=fetch, timeout=timeout, proxy=proxy, retry=retry)
    if not doc.ok:
        return failed_outcome(USGS_SOURCE_ID, doc.failure, attempts=doc.attempts)
    return parse_usgs_geojson(doc.payload, min_magnitude=min_magnitude)


def fetch_usgs_recent_feed(
    *,
    window: str = "all_hour",
    min_magnitude: float | None = None,
    fetch: FetchJson | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    proxy: str = "",
    retry: int = DEFAULT_RETRY_ATTEMPTS,
) -> SourceOutcome[QuakeEvent]:
    """summary feed 通道（真样例即此；交叉核验的第二源常态入口）。"""
    try:
        url = build_usgs_feed_url(window)
    except ValueError as exc:
        return failed_outcome(USGS_SOURCE_ID, f"bad_window:{exc}")
    doc = resolve_document(url, fetch=fetch, timeout=timeout, proxy=proxy, retry=retry)
    if not doc.ok:
        return failed_outcome(USGS_SOURCE_ID, doc.failure, attempts=doc.attempts)
    return parse_usgs_geojson(doc.payload, min_magnitude=min_magnitude)


# ---------------------------------------------------------------- 交叉核验（纯规则）

def crosscheck_quakes(
    primary: tuple[QuakeEvent, ...] | list[QuakeEvent],
    secondary: tuple[QuakeEvent, ...] | list[QuakeEvent],
    *,
    window_minutes: int = 30,
    radius_km: float = 200.0,
) -> tuple[QuakeMatch, ...]:
    """主源逐条在核验源里找「±30min 且 ≤200km」的配对（E11 §3 口径）。

    一对一贪心（按时间差再按距离取最优，一条核验条目只配一次）；
    配不上就单独出一条 `confirmed=False`，由调用方按 `footnote` 显示
    「未获第二源确认」——**绝不静默择一、绝不改数**。
    """
    pool = list(secondary)
    consumed: set[str] = set()
    matches: list[QuakeMatch] = []
    for event in primary:
        best: tuple[float, float, int] | None = None
        best_index = -1
        for index, other in enumerate(pool):
            if other.event_id in consumed:
                continue
            delta_minutes = abs(
                (event.origin_at - other.origin_at).total_seconds()
            ) / 60.0
            if delta_minutes > window_minutes:
                continue
            distance = haversine_km(
                event.latitude, event.longitude, other.latitude, other.longitude
            )
            if distance > radius_km:
                continue
            score = (delta_minutes, distance, index)
            if best is None or score < best:
                best, best_index = score, index
        if best is None or best_index < 0:
            matches.append(QuakeMatch(primary=event, secondary=None, confirmed=False))
            continue
        partner = pool[best_index]
        consumed.add(partner.event_id)
        matches.append(
            QuakeMatch(
                primary=event,
                secondary=partner,
                confirmed=True,
                distance_km=best[1],
                time_delta_minutes=best[0],
            )
        )
    for other in pool:
        if other.event_id not in consumed and not any(
            match.secondary is other for match in matches
        ):
            # 核验源独有的事件同样出一条（不吞、不静默丢弃）
            matches.append(QuakeMatch(primary=other, secondary=None, confirmed=False))
    return tuple(matches)


__all__ = [
    "BEIJING_TZ",
    "CHINA_RECT",
    "ICL_ORIGIN",
    "ICL_SOURCE_ID",
    "ICL_SOURCE_LABEL",
    "USGS_ORIGIN",
    "USGS_SOURCE_ID",
    "USGS_SOURCE_LABEL",
    "QuakeEvent",
    "QuakeMatch",
    "build_icl_earlywarnings_url",
    "build_usgs_fdsnws_url",
    "build_usgs_feed_url",
    "crosscheck_quakes",
    "epoch_ms_to_utc",
    "fetch_icl_earthquakes",
    "fetch_usgs_quakes",
    "fetch_usgs_recent_feed",
    "haversine_km",
    "parse_icl_earlywarnings",
    "parse_usgs_geojson",
]
