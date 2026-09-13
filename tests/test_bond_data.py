"""国债收益率数据源回归（金融 Phase-1 扩容 2026-09-13，全离线）。

锁定 sources/bond_data.py：
1. 列名→期限映射（akshare 1.18.94 锚定 + 利差自洽交叉验证）；
2. 上游利差列缺失时纯算术推导并显式标注「计算值」（算术不是造数）；
3. 缺期限诚实列 missing，绝不造 0；无行 → unavailable；
4. G2 纪律：空→退避重试 1 次、真异常不重试、成功才缓存、URL 载荷锁定。
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from plugins.bot_unified_runtime.sources import bond_data
from plugins.bot_unified_runtime.sources.bond_data import (
    fetch_bond_yields,
    format_bond_brief,
    parse_bond_snapshot,
    reset_bond_cache,
)

# 2026-09-11 实测行（探针逐字段抄录）：利差与期限差自洽
# 1.6899-1.2466=0.4433（✓EMM01276014）、4.96-4.63=0.33（✓EMG01339436）。
_ROW_0911: dict = {
    "SOLAR_DATE": "2026-09-11 00:00:00",
    "EMM00588704": 1.2466,
    "EMM00166462": 1.4226,
    "EMM00166466": 1.6899,
    "EMM00166469": 2.146,
    "EMM01276014": 0.4433,
    "EMM00000024": None,
    "EMG00001306": 4.63,
    "EMG00001308": 4.78,
    "EMG00001310": 4.96,
    "EMG00001312": 5.35,
    "EMG01339436": 0.33,
    "EMG00159635": None,
}
_PAYLOAD: dict = {"result": {"pages": 19, "data": [dict(_ROW_0911)]}}
_EMPTY: dict = {}


@pytest.fixture()
def _clean_cache() -> Iterator[None]:
    reset_bond_cache()
    yield
    reset_bond_cache()


@pytest.fixture()
def _sleeps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    recorded: list[float] = []

    def _record(seconds: float) -> None:
        recorded.append(float(seconds))

    monkeypatch.setattr(time, "sleep", _record)
    yield recorded


# ---------------------------------------------------------------------------
# 解析（纯离线）：映射 / 推导 / 诚实缺项
# ---------------------------------------------------------------------------


def test_parse_full_row_maps_tenors_and_spreads(_clean_cache) -> None:
    snapshot = parse_bond_snapshot(_PAYLOAD, fetched_at=1000.0)
    assert snapshot.status == "ok"
    assert snapshot.as_of_date == "2026-09-11"
    assert [(p.label, p.value) for p in snapshot.cn] == [
        ("中国国债 2年", 1.2466),
        ("中国国债 5年", 1.4226),
        ("中国国债 10年", 1.6899),
        ("中国国债 30年", 2.146),
    ]
    assert snapshot.cn_spread_10y2y == 0.4433  # 上游直供列
    assert [(p.label, p.value) for p in snapshot.us] == [
        ("美国国债 2年", 4.63),
        ("美国国债 5年", 4.78),
        ("美国国债 10年", 4.96),
        ("美国国债 30年", 5.35),
    ]
    assert snapshot.us_spread_10y2y == 0.33
    assert snapshot.missing == () and snapshot.derived_notes == ()
    assert snapshot.delayed is True


def test_parse_derives_spread_when_column_missing_but_tenors_present(
    _clean_cache,
) -> None:
    row = dict(_ROW_0911)
    row["EMM01276014"] = None  # 上游利差列缺失
    row["EMG01339436"] = None
    payload = {"result": {"data": [row]}}
    snapshot = parse_bond_snapshot(payload, fetched_at=1000.0)
    assert snapshot.cn_spread_10y2y == round(1.6899 - 1.2466, 4)  # 纯算术推导
    assert snapshot.us_spread_10y2y == round(4.96 - 4.63, 4)
    assert any("计算" in note for note in snapshot.derived_notes)  # 显式标注
    assert snapshot.missing == ()  # 推导不算缺项


def test_parse_missing_tenor_lists_honestly_and_never_zero(_clean_cache) -> None:
    row = dict(_ROW_0911)
    row["EMM00166466"] = None  # 中国 10 年缺失
    row["EMM01276014"] = None  # 利差列也缺（10Y 没了 → 无法推导）
    payload = {"result": {"data": [row]}}
    snapshot = parse_bond_snapshot(payload, fetched_at=1000.0)
    cn_10y = snapshot.cn[2]
    assert cn_10y.value is None  # 绝不造 0
    assert "中国国债 10年" in snapshot.missing
    assert snapshot.cn_spread_10y2y is None
    assert "中国 10Y−2Y 利差" in snapshot.missing


def test_parse_empty_payload_unavailable(_clean_cache) -> None:
    snapshot = parse_bond_snapshot(_EMPTY, fetched_at=1000.0)
    assert snapshot.status == "unavailable"
    assert snapshot.note  # 有说明
    assert "暂时拉不到" in format_bond_brief(snapshot)


def test_format_brief_ok_contains_blocks(_clean_cache) -> None:
    brief = format_bond_brief(parse_bond_snapshot(_PAYLOAD, fetched_at=1000.0))
    assert "中美国债收益率速览" in brief
    assert "中国国债 10年 1.690%" in brief
    assert "10Y−2Y 期限利差 0.443%" in brief
    assert "美国国债 30年 5.350%" in brief
    assert "10Y−2Y 期限利差 0.330%" in brief


# ---------------------------------------------------------------------------
# fetch：G2 重试 + 零缓存 + URL 载荷
# ---------------------------------------------------------------------------


def test_fetch_empty_then_data_two_calls(_clean_cache, _sleeps, monkeypatch) -> None:
    from plugins.bot_unified_runtime.sources.market_data import _RETRY_BACKOFF_SECONDS

    payloads: list[dict] = [dict(_EMPTY), dict(_PAYLOAD)]
    calls: list[str] = []

    def _fake(timeout: float) -> dict:
        calls.append("call")
        return payloads.pop(0)

    monkeypatch.setattr(bond_data, "_fetch_payload", _fake)
    snapshot = fetch_bond_yields()
    assert len(calls) == 2
    assert snapshot.status == "ok" and snapshot.as_of_date == "2026-09-11"
    assert _sleeps == [_RETRY_BACKOFF_SECONDS]


def test_fetch_exception_unavailable_no_retry(_clean_cache, _sleeps, monkeypatch) -> None:
    calls: list[str] = []

    def _boom(timeout: float) -> dict:
        calls.append("call")
        raise OSError("network down")

    monkeypatch.setattr(bond_data, "_fetch_payload", _boom)
    snapshot = fetch_bond_yields()
    assert len(calls) == 1  # 真异常不重试
    assert snapshot.status == "unavailable"
    assert "OSError" in snapshot.note
    assert _sleeps == []


def test_fetch_double_empty_no_cache_and_url_payload(
    _clean_cache, _sleeps, monkeypatch
) -> None:
    real_fetch = bond_data._fetch_payload
    calls: list[str] = []

    def _fake(timeout: float) -> dict:
        calls.append("call")
        return dict(_EMPTY)

    monkeypatch.setattr(bond_data, "_fetch_payload", _fake)
    assert fetch_bond_yields().status == "unavailable"
    assert len(calls) == 2
    assert fetch_bond_yields().status == "unavailable"  # 失败不缓存
    assert len(calls) == 4

    # URL 载荷锁定：恢复真 _fetch_payload、在 http_get_json 层拦 URL。
    monkeypatch.setattr(bond_data, "_fetch_payload", real_fetch)
    captured: list[str] = []

    def _fake_json(url: str, **kwargs: object):
        captured.append(url)
        return dict(_PAYLOAD)

    monkeypatch.setattr(bond_data, "http_get_json", _fake_json)
    reset_bond_cache()
    snapshot = fetch_bond_yields()
    assert snapshot.status == "ok"
    url = captured[0]
    assert "reportName=RPTA_WEB_TREASURYYIELD" in url
    assert "sortColumns=SOLAR_DATE" in url  # TRADE_DATE 列不存在（实测 9501）
    assert "sortTypes=-1" in url
