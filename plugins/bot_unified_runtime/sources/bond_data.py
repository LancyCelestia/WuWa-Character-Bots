"""中美国债收益率数据源（金融 Phase-1 扩容，2026-09-13）。

**源**：东财 datacenter ``RPTA_WEB_TREASURYYIELD``（免 key，2026-09-13 本机
实测可达）：

    GET https://datacenter-web.eastmoney.com/api/data/v1/get
        ?reportName=RPTA_WEB_TREASURYYIELD&columns=ALL
        &sortColumns=SOLAR_DATE&sortTypes=-1&pageNumber=1&pageSize=2
        &source=WEB&client=WEB

列名→期限映射来源：akshare 1.18.94（2026-09-13 从 PyPI sdist 实取源码，
``akshare/bond/bond_em.py`` 的 ``bond_zh_us_rate``）——

- ``EMM00588704`` 中国国债收益率2年　``EMM00166462`` 中国国债收益率5年
- ``EMM00166466`` 中国国债收益率10年　``EMM00166469`` 中国国债收益率30年
- ``EMM01276014`` 中国国债收益率10年-2年（期限利差，上游直接给）
- ``EMG00001306/8/10/2`` 美国国债收益率 2/5/10/30 年
- ``EMG01339436`` 美国国债收益率10年-2年
- ``EMM00000024``/``EMG00159635`` 中国/美国GDP年增率（近期实测恒 null，不接）

映射交叉验证（2026-09-13 实测行 2026-09-11）：EMM01276014=0.4433 与
EMM00166466−EMM00588704=1.6899−1.2466=0.4433 逐位一致；EMG01339436=0.33 与
4.96−4.63=0.33 一致——利差列与期限列自洽，映射可信。

**1 年期诚实边界**：该报表无 1 年期列（中债官网/其他免费源本机实测不可达
或映射不可证），1Y 不接入；期限利差采用上游直供的 10Y−2Y 口径，不自行
拼凑其他期限组合。10Y−2Y 上游字段缺失而两期限都在时，做纯算术推导并
显式标注「计算值」（算术不是造数）。

G2 空响应重试纪律与 market_data 同款：``result`` 为空/缺行 → 退避重试
1 次；真异常不重试；仍空走诚实降级且不缓存。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from plugins.bot_unified_runtime.sources.market_data import (
    _MAX_PAYLOAD_BYTES,
    empty_backoff_sleep,
    retry_on_empty_enabled,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import http_get_json

_BOND_URL = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get"
    "?reportName=RPTA_WEB_TREASURYYIELD&columns=ALL"
    "&sortColumns=SOLAR_DATE&sortTypes=-1&pageNumber=1&pageSize={page_size}"
    "&source=WEB&client=WEB"
)
_SOURCE = "eastmoney_datacenter"
_PAGE_SIZE = 2

# 列名 → (展示标签, 板块)。上游口径单位=%（小数形式，1.6899 = 1.6899%）。
_CN_TENORS: tuple[tuple[str, str], ...] = (
    ("EMM00588704", "中国国债 2年"),
    ("EMM00166462", "中国国债 5年"),
    ("EMM00166466", "中国国债 10年"),
    ("EMM00166469", "中国国债 30年"),
)
_US_TENORS: tuple[tuple[str, str], ...] = (
    ("EMG00001306", "美国国债 2年"),
    ("EMG00001308", "美国国债 5年"),
    ("EMG00001310", "美国国债 10年"),
    ("EMG00001312", "美国国债 30年"),
)
_CN_SPREAD_10Y2Y = "EMM01276014"
_US_SPREAD_10Y2Y = "EMG01339436"
_DATE_COLUMN = "SOLAR_DATE"

_CACHE_TTL_DEFAULT_SECONDS = 300.0
_CACHE: tuple[float, BondYieldSnapshot] | None = None

# 审查 Q-01：原 _EMPTY_DEGRADED_TEXT（「国债收益率数据暂时拉不到，晚点再试试？」）
# 为无引用死常量，随文案统一批删除；bond 降级文案若将来需要，走 user_copy
# 数据源失败池（DATASOURCE_FAILURE_TEMPLATES），不得回退硬编码。


@dataclass(frozen=True)
class BondYieldPoint:
    """单个期限的收益率点位；value 单位 %，缺数 None（绝不造 0）。"""

    label: str
    value: float | None = None


@dataclass(frozen=True)
class BondYieldSnapshot:
    """中美国债收益率快照（利差=10Y−2Y 口径，见模块 docstring）。"""

    as_of_date: str | None = None  # 交易日 YYYY-MM-DD
    cn: tuple[BondYieldPoint, ...] = ()
    cn_spread_10y2y: float | None = None
    us: tuple[BondYieldPoint, ...] = ()
    us_spread_10y2y: float | None = None
    derived_notes: tuple[str, ...] = field(default_factory=tuple)
    missing: tuple[str, ...] = field(default_factory=tuple)
    source: str = _SOURCE
    as_of: float | None = None
    delayed: bool = True
    status: str = "ok"
    note: str = ""


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fetch_payload(timeout_seconds: float) -> Any:
    """收益率单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    return http_get_json(
        _BOND_URL.format(page_size=_PAGE_SIZE),
        timeout=max(1.0, float(timeout_seconds)),
        max_bytes=_MAX_PAYLOAD_BYTES,
    )


def _first_row(payload: Any) -> dict[str, Any] | None:
    """datacenter v1 包络取最新一行（sortTypes=-1 首行）。"""
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _spread_with_fallback(
    row: dict[str, Any],
    spread_column: str,
    long_point: BondYieldPoint,
    short_point: BondYieldPoint,
    label: str,
    notes: list[str],
) -> float | None:
    """利差优先取上游直供列；缺失且两期限都在 → 纯算术推导并记「计算值」。"""
    direct = _as_float(row.get(spread_column))
    if direct is not None:
        return direct
    if long_point.value is not None and short_point.value is not None:
        notes.append(f"{label}（由 {long_point.label}−{short_point.label} 计算）")
        return round(long_point.value - short_point.value, 4)
    return None


def parse_bond_snapshot(payload: Any, fetched_at: float | None = None) -> BondYieldSnapshot:
    """解析最新一行；缺字段/非数一律 None 并进 missing，绝不造 0。"""
    row = _first_row(payload)
    if row is None:
        return BondYieldSnapshot(
            status="unavailable",
            as_of=fetched_at,
            note="上游未返回可用收益率行（网络失败或包络异常）",
        )
    raw_date = str(row.get(_DATE_COLUMN) or "").strip()
    as_of_date = raw_date[:10] or None
    notes: list[str] = []
    missing: list[str] = []

    cn_points: list[BondYieldPoint] = []
    cn_values: dict[str, float | None] = {}
    for column, label in _CN_TENORS:
        value = _as_float(row.get(column))
        if value is None:
            missing.append(label)
        cn_points.append(BondYieldPoint(label=label, value=value))
        cn_values[column] = value
    cn_spread = _spread_with_fallback(
        row, _CN_SPREAD_10Y2Y, cn_points[2], cn_points[0], "中国 10Y−2Y 利差", notes
    )

    us_points: list[BondYieldPoint] = []
    for column, label in _US_TENORS:
        value = _as_float(row.get(column))
        if value is None:
            missing.append(label)
        us_points.append(BondYieldPoint(label=label, value=value))
    us_spread = _spread_with_fallback(
        row, _US_SPREAD_10Y2Y, us_points[2], us_points[0], "美国 10Y−2Y 利差", notes
    )

    if cn_spread is None:
        missing.append("中国 10Y−2Y 利差")
    if us_spread is None:
        missing.append("美国 10Y−2Y 利差")
    return BondYieldSnapshot(
        as_of_date=as_of_date,
        cn=tuple(cn_points),
        cn_spread_10y2y=cn_spread,
        us=tuple(us_points),
        us_spread_10y2y=us_spread,
        derived_notes=tuple(notes),
        missing=tuple(missing),
        source=_SOURCE,
        as_of=fetched_at if fetched_at is not None else time.time(),
        delayed=True,
        status="ok",
        note="",
    )


def reset_bond_cache() -> None:
    """清空收益率进程内缓存（测试与运维手动刷新用）。"""
    global _CACHE
    _CACHE = None


def fetch_bond_yields(
    timeout_seconds: float = 6.0,
    cache_seconds: float = _CACHE_TTL_DEFAULT_SECONDS,
) -> BondYieldSnapshot:
    """拉取中美国债收益率快照；失败走 unavailable 状态，绝不抛异常。

    G2：空响应（result 空/缺行）退避后至多重试 1 次；真异常不重试；
    仍空走 unavailable 且不缓存。数据源按交易日更新（非实时），
    缓存默认 5 分钟即可。
    """
    global _CACHE
    now = time.monotonic()
    cached = _CACHE
    if cached is not None and now - cached[0] <= max(0.0, float(cache_seconds)):
        return cached[1]
    fetched_at = time.time()
    attempts = 2 if retry_on_empty_enabled() else 1
    snapshot: BondYieldSnapshot | None = None
    for attempt in range(attempts):
        try:
            payload = _fetch_payload(timeout_seconds)
            snapshot = parse_bond_snapshot(payload, fetched_at)
        except Exception as exc:  # noqa: BLE001 - 收益率失败静默降级。
            return BondYieldSnapshot(
                status="unavailable",
                as_of=fetched_at,
                note=f"收益率拉取失败：{type(exc).__name__}",
            )
        if snapshot.status == "ok" or attempt + 1 >= attempts:
            break
        empty_backoff_sleep()
    assert snapshot is not None  # pragma: no cover - 循环末次必有值
    if snapshot.status == "ok":
        _CACHE = (now, snapshot)
    return snapshot


def _fmt_yield(value: float | None) -> str:
    if value is None:
        return "暂无"
    return f"{value:.3f}%"


def format_bond_brief(snapshot: BondYieldSnapshot) -> str:
    """国债收益率纯文本快报；空结果给降级文案，缺项显式列出。"""
    if snapshot.status != "ok" or (
        all(p.value is None for p in snapshot.cn)
        and all(p.value is None for p in snapshot.us)
    ):
        reason = snapshot.note or "上游失败"
        return f"国债收益率数据暂时拉不到（{reason}），先不瞎猜数字。"
    lines = ["中美国债收益率速览"]
    if snapshot.as_of_date:
        lines.append(f"交易日 {snapshot.as_of_date} · 收盘口径 · 延迟数据")
    lines.append("—— 中国国债 ——")
    for point in snapshot.cn:
        lines.append(f"{point.label} {_fmt_yield(point.value)}")
    lines.append(f"10Y−2Y 期限利差 {_fmt_yield(snapshot.cn_spread_10y2y)}")
    lines.append("—— 美国国债 ——")
    for point in snapshot.us:
        lines.append(f"{point.label} {_fmt_yield(point.value)}")
    lines.append(f"10Y−2Y 期限利差 {_fmt_yield(snapshot.us_spread_10y2y)}")
    if snapshot.missing:
        lines.append("暂无数据：" + "、".join(snapshot.missing))
    for note in snapshot.derived_notes:
        lines.append(f"注：{note}")
    return "\n".join(lines)
