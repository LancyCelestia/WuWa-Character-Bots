"""NMC（中国气象局 / 国家预警信息发布中心）政务预警采集源（B2 席）。

覆盖 E11 §2 矩阵里判「接」的三条 NMC 端点：

1. **全国在报预警清单** `www.nmc.cn/rest/findAlarm?pageNo=&pageSize=`（矩阵 #1，
   主源）→ `fetch_nmc_alarms` / `parse_nmc_alarm_page`。
2. **站点级当前预警** `www.nmc.cn/rest/weather?stationid=`（矩阵 #2，白捡位）
   → `fetch_nmc_station_alarm` / `parse_nmc_station_alarm`。真身字段
   `data.real.warn`（现役 `domains/weather/data/nmc_weather.py:113-153`
   只读 `real.*` 的温湿度风，**从未读 `real.warn`**，E11 §2「消费缺口」行）。
3. **预警详情页** `www.nmc.cn/publish/alarm/{alertid}.html`（矩阵 #3）
   → 本席只提供 `build_nmc_alarm_detail_url`（主键消毒 + 绝对化），
   **不提供 HTML 正文解析器**：probes/samples 无该端点样例字节，
   E11 §6 亦自证「结构化抽取点只验了可达性，未做解析器设计」⇒
   按 D-1「无源诚实不接」不做，登记在 report §6。

样板坐标：标题里的 (类型, 颜色) 拆法抄
`domains/weather/capabilities/weather.py:126-146`（`parse_alert_title`）与
`:112` 的颜色序位表 `_ALARM_COLOR_RANK`；本席**不 import weather 能力模块**
（那会把整层能力契约与 http 取数面拖进纯采集件，且 `domains/weather/**` 是
本席禁写面），改为在本文件内实现同语义的 `split_alarm_title`，并把
「上提为单一事实源、weather 支路反向复用」写进 report §4 落地请求。

时间口径：NMC `issuetime` 是**北京时间分钟精度**（样例 300/300 条均为
`YYYY-MM-DD HH:MM`），一律解析成带 `UTC+8` tzinfo 的 aware datetime；
naive 一律显式打标，绝不当本地时区也不当 UTC（老坑见 AGENTS.md 台账 #29 ⑤）。

「无数据 vs 取数失败」在本文件的落地（详见 report §3）：
- `NO_DATA`：`code==0` 且 `data.page` 结构成立、`page.count==0` 且 `list==[]`；
  站点预警侧 = `warn.alert` 为 NMC 的「无值」哨兵 `9999`/空串（哨兵口径同
  `nmc_weather.py:86,130` 的 `known()` 判定）。
- `FAILED`：信封不是 dict、`code!=0`、`data.page` 缺失、`list` 不是列表、
  条目全部缺 `alertid`/`title`、取数抛异常、stationid 形态非法、URL 不过闸。
- 两者**不共用空列表**：调用方拿到 `items==()` 时若不看 `state` 就必然重演
  现役天气支路「间歇性无预警」的假象。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .http_get import (
    DEFAULT_RETRY_ATTEMPTS,
    NMC_ALARM_TIMEOUT_SECONDS,
    FetchJson,
    FetchState,
    SourceOutcome,
    UnsafeIdentifier,
    failed_outcome,
    require_safe_id,
    resolve_document,
)

SOURCE_ID = "nmc"

NMC_ORIGIN = "https://www.nmc.cn"
BEIJING_TZ = timezone(timedelta(hours=8), "UTC+8")

# NMC 的「无值」哨兵：接口拿不到值时用 9999/空串占位（既有做法
# nmc_weather.py:86 `if str(value).strip() in {"9999", "9999.0", ""}`）。
_NMC_SENTINELS = frozenset({"", "9999", "9999.0", "none", "null"})

# 颜色序位：数值口径与 weather.py:112 `_ALARM_COLOR_RANK` 逐字一致（蓝1黄2橙3红4）。
ALARM_COLOR_RANK: dict[str, int] = {"蓝色": 1, "黄色": 2, "橙色": 3, "红色": 4}

# 两种分隔符都得收：真样例实测 findAlarm 的 `issuetime` 用**斜杠**
# （`nmc_findAlarm.sample.json` 首条字节 = `2026/09/20 00:43`，0x2f；E11 §5
# 转写成短横是笔误，本席以磁盘字节为准），而 `rest/weather` 的
# `real.publish_time` 用**短横**（`nmc_restWeather.sample.json` 字节 0x2d）。
# 现役 `weather.py:190` 只把原文塞进 `issued` 字段从不解析，所以这个差异从没暴露过。
_ISSUE_TIME_FORMATS = (
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------- 条目模型（本席自持）

@dataclass(frozen=True)
class AlarmAlert:
    """一条 NMC 全国在报预警（findAlarm 条目，字段全部来自响应体）。

    `kind`/`color_label` 由标题解析：标题无比方颜色词时 `color_label=""`
    （E11 §3 口径「不猜等级」），**不**给缺省档。
    """

    alertid: str
    title: str
    kind: str
    color_label: str
    issued_at: datetime | None
    issued_text: str
    url: str
    detail_url: str
    pic: str
    province_level: bool = False


@dataclass(frozen=True)
class StationAlarm:
    """一个站点的当前预警（`rest/weather` 的 `data.real.warn`）。"""

    station_code: str
    station_text: str
    alert_text: str
    signal_type: str
    signal_level: str
    issued_at: datetime | None
    issued_text: str
    url: str
    pic: str
    issue_content: str


# ---------------------------------------------------------------- 纯解析（零 IO）

def _clean(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in _NMC_SENTINELS else text


def split_alarm_title(title: str) -> tuple[str, str]:
    """预警标题 → (类型, 颜色词)；语义逐字对齐 weather.py:126-146。

    例：「湖南省湘西土家族苗族自治州保靖县气象台发布大雾黄色预警信号」
    → ("大雾", "黄色")（真样例 `nmc_findAlarm.sample.json` 首条）。
    """
    text = str(title or "").strip()
    color = ""
    for name in ALARM_COLOR_RANK:
        if name in text:
            color = name
            break
    kind = ""
    if "发布" in text:
        segment = text.split("发布", 1)[1]
        for suffix in ("预警信号", "预警"):
            if suffix in segment:
                kind = segment.split(suffix, 1)[0]
                for name in ALARM_COLOR_RANK:
                    kind = kind.replace(name, "")
                kind = kind.strip("（）() 　")
                break
    return kind, color


def parse_beijing_time(text: Any) -> datetime | None:
    """`YYYY-MM-DD HH:MM[:SS]`（北京时间）→ aware datetime；不可解析→ None。"""
    raw = str(text or "").strip()
    if not raw or raw.lower() in _NMC_SENTINELS:
        return None
    for fmt in _ISSUE_TIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=BEIJING_TZ)
        except ValueError:
            continue
    return None


def absolutize_nmc_url(path: Any) -> str:
    """把响应里的相对路径绝对化；已是绝对 URL 原样返回；空→空串。"""
    raw = str(path or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    if raw.startswith("//"):
        return f"https:{raw}"
    return f"{NMC_ORIGIN}/{raw.lstrip('/')}"


def build_nmc_alarm_detail_url(alertid: str) -> str:
    """alertid → 详情页绝对 URL（矩阵 #3；主键先消毒再拼，防路径注入）。

    实证：`51178141600000_20260920002955` →
    `https://www.nmc.cn/publish/alarm/51178141600000_20260920002955.html`
    （E11 §5.2 实测 200 / 51,921B；该 alertid 亦在真样例 list 内）。
    """
    return f"{NMC_ORIGIN}/publish/alarm/{require_safe_id(alertid, field_name='alertid')}.html"


def build_nmc_find_alarm_url(page_no: int = 1, page_size: int = 300) -> str:
    """清单端点 URL（pageSize=300 即当日全量在报，E11 §5.2 实测 count=328/300 条一页）。"""
    no = max(1, int(page_no))
    size = min(max(1, int(page_size)), 500)
    return f"{NMC_ORIGIN}/rest/findAlarm?pageNo={no}&pageSize={size}"


def build_nmc_rest_weather_url(stationid: str, *, timestamp_ms: int | None = None) -> str:
    """站点实况端点 URL（含 `_` 防缓存参数，形态抄 nmc_weather.py:115）。"""
    code = require_safe_id(stationid, field_name="stationid")
    stamp = int(timestamp_ms) if timestamp_ms is not None else 0
    return f"{NMC_ORIGIN}/rest/weather?stationid={code}&_={stamp}"


def _entry_to_alert(entry: Any, *, province_level: bool) -> tuple[AlarmAlert | None, str]:
    """单条目 → (告警, 丢弃原因标签)。缺必需字段即 None（D-1 不填假值）。"""
    if not isinstance(entry, dict):
        return None, "not_object"
    alertid = _clean(entry.get("alertid"))
    title = _clean(entry.get("title"))
    if not alertid or not title:
        return None, "missing_alertid_or_title"
    kind, color = split_alarm_title(title)
    issued_text = _clean(entry.get("issuetime"))
    url_field = absolutize_nmc_url(entry.get("url"))
    return (
        AlarmAlert(
            alertid=alertid,
            title=title,
            kind=kind,
            color_label=color,
            issued_at=parse_beijing_time(issued_text),
            issued_text=issued_text,
            url=url_field,
            detail_url=url_field or _safe_detail_url_or_empty(alertid),
            pic=absolutize_nmc_url(entry.get("pic")),
            province_level=province_level,
        ),
        "",
    )


def _safe_detail_url_or_empty(alertid: str) -> str:
    try:
        return build_nmc_alarm_detail_url(alertid)
    except UnsafeIdentifier:
        return ""


def parse_nmc_alarm_page(payload: Any) -> SourceOutcome[AlarmAlert]:
    """findAlarm 响应 → 告警清单（纯函数，直接吃真样例字节）。

    真样例：`probes/samples/nmc_findAlarm.sample.json`（83,370B，
    `code=0`、`data.page.count=328`、`list` 300 条、`provinceAlarms` 4 条且
    **4 条 alertid 全部已在 list 内**——故按 alertid 去重合并，不重复计数）。
    """
    if not isinstance(payload, dict):
        return failed_outcome(SOURCE_ID, f"bad_envelope:{type(payload).__name__}")
    code = payload.get("code")
    if str(code).strip() != "0":
        return failed_outcome(SOURCE_ID, f"source_error:code={code!r}")
    data = payload.get("data")
    if not isinstance(data, dict):
        return failed_outcome(SOURCE_ID, "missing_field:data")
    page = data.get("page")
    if not isinstance(page, dict):
        return failed_outcome(SOURCE_ID, "missing_field:data.page")
    entries = page.get("list")
    if entries is None or not isinstance(entries, list):
        return failed_outcome(SOURCE_ID, "missing_field:data.page.list")

    total_hint = _as_int(page.get("count"))
    collected: dict[str, AlarmAlert] = {}
    dropped = 0
    for entry in entries:
        alert, _reason = _entry_to_alert(entry, province_level=False)
        if alert is None:
            dropped += 1
            continue
        collected[alert.alertid] = alert

    province_entries = data.get("provinceAlarms")
    province_only = 0
    dropped_province = 0
    if isinstance(province_entries, list):
        for entry in province_entries:
            alert, _reason = _entry_to_alert(entry, province_level=True)
            if alert is None:
                dropped_province += 1
                continue
            if alert.alertid in collected:
                # 同一条：只在既有条目上打省级标，不新增条目。
                collected[alert.alertid] = _mark_province(collected[alert.alertid])
                continue
            collected[alert.alertid] = alert
            province_only += 1
    elif province_entries is not None:
        dropped_province += 1

    if not collected:
        if entries or province_entries:
            # 源端给了条目但一条都解析不出来 ⇒ 结构/字段问题，不是「无预警」。
            return SourceOutcome(
                state=FetchState.FAILED,
                source_id=SOURCE_ID,
                reason="all_entries_invalid",
                total_hint=total_hint,
                dropped=dropped + dropped_province,
            )
        if total_hint in (None, 0):
            return SourceOutcome(
                state=FetchState.NO_DATA,
                source_id=SOURCE_ID,
                reason="no_alarm_in_report",
                total_hint=total_hint,
            )
        return SourceOutcome(
            state=FetchState.FAILED,
            source_id=SOURCE_ID,
            reason=f"count_mismatch:total={total_hint}_but_empty_page",
            total_hint=total_hint,
        )

    items = tuple(collected.values())
    notes: list[str] = []
    if total_hint is not None and total_hint > len(items):
        notes.append(f"page_truncated:{len(items)}/{total_hint}")
    if province_only:
        notes.append(f"province_only_added={province_only}")
    return SourceOutcome(
        state=FetchState.OK,
        source_id=SOURCE_ID,
        items=items,
        total_hint=total_hint,
        dropped=dropped + dropped_province,
        notes=tuple(notes),
    )


def _mark_province(alert: AlarmAlert) -> AlarmAlert:
    return replace(alert, province_level=True)


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_nmc_station_alarm(payload: Any, *, stationid: str = "") -> SourceOutcome[StationAlarm]:
    """`rest/weather` 响应 → 站点当前预警（纯函数，吃 nmc_restWeather.sample.json）。

    真样例（10,473B，stationid=Wqsps/北京）的 `data.real.warn` 全字段为哨兵
    `9999`、`issuetime=""` ⇒ 判 `NO_DATA`（**「确实无预警」而非「取数失败」**）。
    `data.real` 或 `real.warn` 缺失则判 `FAILED`——那是结构塌了，不能报「无预警」。
    """
    if not isinstance(payload, dict):
        return failed_outcome(SOURCE_ID, f"bad_envelope:{type(payload).__name__}")
    code = payload.get("code")
    if str(code).strip() != "0":
        return failed_outcome(SOURCE_ID, f"source_error:code={code!r}")
    data = payload.get("data")
    if not isinstance(data, dict):
        return failed_outcome(SOURCE_ID, "missing_field:data")
    real = data.get("real")
    if not isinstance(real, dict):
        return failed_outcome(SOURCE_ID, "missing_field:data.real")
    warn = real.get("warn")
    if not isinstance(warn, dict):
        return failed_outcome(SOURCE_ID, "missing_field:data.real.warn")

    raw_station: Any = real.get("station")
    station: dict[str, Any] = raw_station if isinstance(raw_station, dict) else {}
    station_text = " ".join(
        part for part in (_clean(station.get("province")), _clean(station.get("city"))) if part
    )
    alert_text = _clean(warn.get("alert"))
    issued_text = _clean(warn.get("issuetime"))
    if not alert_text:
        return SourceOutcome(
            state=FetchState.NO_DATA,
            source_id=SOURCE_ID,
            reason="station_has_no_active_alarm",
            notes=(f"station={_clean(station.get('city')) or stationid}",),
        )
    _kind, color = split_alarm_title(alert_text)
    return SourceOutcome(
        state=FetchState.OK,
        source_id=SOURCE_ID,
        items=(
            StationAlarm(
                station_code=_clean(station.get("code")) or str(stationid or ""),
                station_text=station_text,
                alert_text=alert_text,
                signal_type=_clean(warn.get("signaltype")),
                signal_level=color or _clean(warn.get("signallevel")),
                issued_at=parse_beijing_time(issued_text),
                issued_text=issued_text,
                url=absolutize_nmc_url(warn.get("url")),
                pic=absolutize_nmc_url(warn.get("pic")),
                issue_content=_clean(warn.get("issuecontent")),
            ),
        ),
    )


# ---------------------------------------------------------------- 取数门面

def fetch_nmc_alarms(
    *,
    page_no: int = 1,
    page_size: int = 300,
    fetch: FetchJson | None = None,
    timeout: float = NMC_ALARM_TIMEOUT_SECONDS,
    proxy: str = "",
    retry: int = DEFAULT_RETRY_ATTEMPTS,
) -> SourceOutcome[AlarmAlert]:
    """拉全国在报预警清单（E11 §4 签名裁定：timeout 必 ≥15s + 重试）。

    `fetch` 为测试注入的取数替身（全离线）；缺省走真实常量 URL（先过
    常量白名单再过 SSRF 护栏）。失败**永远**是 `FetchState.FAILED` +
    `reason`，绝不返回空的 `OK`。
    """
    url = build_nmc_find_alarm_url(page_no, page_size)
    doc = resolve_document(url, fetch=fetch, timeout=timeout, proxy=proxy, retry=retry)
    if not doc.ok:
        return failed_outcome(SOURCE_ID, doc.failure, attempts=doc.attempts)
    outcome = parse_nmc_alarm_page(doc.payload)
    return outcome


def fetch_nmc_station_alarm(
    stationid: str,
    *,
    fetch: FetchJson | None = None,
    timeout: float = 10.0,
    proxy: str = "",
    retry: int = DEFAULT_RETRY_ATTEMPTS,
    timestamp_ms: int | None = None,
) -> SourceOutcome[StationAlarm]:
    """拉一个站点的当前预警（矩阵 #2；`real.warn` 现成位，现役天气码未消费）。"""
    try:
        url = build_nmc_rest_weather_url(stationid, timestamp_ms=timestamp_ms)
    except UnsafeIdentifier as exc:
        return failed_outcome(SOURCE_ID, f"unsafe_stationid:{exc}")
    doc = resolve_document(url, fetch=fetch, timeout=timeout, proxy=proxy, verify_ssl=False, retry=retry)
    if not doc.ok:
        return failed_outcome(SOURCE_ID, doc.failure, attempts=doc.attempts)
    return parse_nmc_station_alarm(doc.payload, stationid=stationid)


__all__ = [
    "ALARM_COLOR_RANK",
    "BEIJING_TZ",
    "NMC_ORIGIN",
    "SOURCE_ID",
    "AlarmAlert",
    "StationAlarm",
    "absolutize_nmc_url",
    "build_nmc_alarm_detail_url",
    "build_nmc_find_alarm_url",
    "build_nmc_rest_weather_url",
    "fetch_nmc_alarms",
    "fetch_nmc_station_alarm",
    "parse_beijing_time",
    "parse_nmc_alarm_page",
    "parse_nmc_station_alarm",
    "split_alarm_title",
]
