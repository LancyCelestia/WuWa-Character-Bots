"""I-2 回归：腾讯 GBK 快照解析器字段序固化（评审前零测试覆盖）。

``market_crosscheck._fetch_tencent_snapshot`` 硬编码字段序——短格式
``[3]=价格`` / ``[5]=涨跌幅``、长格式 ``[3]=价格`` / ``[32]=涨跌幅``——
此前全部测试都把该函数整体 monkeypatch 掉，没有任何 GBK fixture 锁定
字段序；上游改字段序时行解析静默失败 → snapshot 空 → checked=0 →
交叉核验整条哑火且无测试报警。

本文件用真实 ``body.decode("gbk")`` 全路径（仅 ``http_get`` 出口替换为
fixture 字节）锁死两种格式：字段序一旦漂移，这里立刻红。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.finance.data import market_crosscheck


def _short_record(price: str, delta: str, pct: str) -> str:
    """短格式实测结构：1~名称~代码~价格~涨跌额~涨跌幅~成交量~成交额~…"""
    fields = [
        "1",
        "上证指数",
        "000001",
        price,
        delta,
        pct,
        "352000000",
        "48810000",
        "",
        "20260912150000",
    ]
    return "~".join(fields)


def _long_record(price: str, delta: str, pct: str, *, truncate_before: int | None = None) -> str:
    """长格式（HK/US）实测结构：[3]=价格，[30]=时间戳，[31]=涨跌额，[32]=涨跌幅。"""
    fields: list[str] = ["100", "道琼斯", "DJI", price]
    fields += [f"f{i}" for i in range(4, 30)]
    fields += ["20260912160000", delta, pct]
    if truncate_before is not None:
        fields = fields[:truncate_before]
    return "~".join(fields)


def _body_bytes(lines: list[str]) -> bytes:
    return ("\n".join(f'{line};' for line in lines) + "\n").encode("gbk")


@pytest.fixture
def install_http(monkeypatch: pytest.MonkeyPatch):
    """把模块级 ``http_get`` 出口替换为 fixture 字节（走真实 GBK 解码全路径）。"""

    def _install(lines: list[str]) -> list[tuple[str, float]]:
        calls: list[tuple[str, float]] = []

        def fake_http_get(url: str, *, timeout: float = 10.0, **_kw: Any) -> tuple[str, bytes]:
            calls.append((url, timeout))
            return url, _body_bytes(lines)

        monkeypatch.setattr(market_crosscheck, "http_get", fake_http_get)
        return calls

    return _install


def test_short_format_field_order_locked(install_http) -> None:
    """短格式字段序：fields[3]=价格、fields[5]=涨跌幅（GBK 解码真实路径）。"""
    install_http([f'v_s_sh000001="{_short_record("3893.29", "19.85", "0.51")}"'])
    snapshot = market_crosscheck._fetch_tencent_snapshot(("s_sh000001",), 4.0)
    # 字段序漂移（如 [4]/[5] 错位、[2] 当价格）会在此精确断言上立刻红。
    assert snapshot == {"1.000001": (3893.29, 0.51)}


def test_long_format_field_order_locked(install_http) -> None:
    """长格式字段序：fields[3]=价格、fields[32]=涨跌幅（33+ 字段，GBK 全路径）。"""
    install_http(
        [
            f'v_usDJI="{_long_record("45000.12", "-120.50", "-0.27")}"',
            f'v_r_hkHSI="{_long_record("25890.44", "345.10", "1.35")}"',
        ]
    )
    snapshot = market_crosscheck._fetch_tencent_snapshot(("usDJI", "r_hkHSI"), 4.0)
    assert snapshot == {
        "100.DJIA": (45000.12, -0.27),
        "100.HSI": (25890.44, 1.35),
    }


def test_malformed_rows_skipped_silently(install_http) -> None:
    """截断行（不足 33 字段）与非数值行静默跳过，不影响其余行解析。"""
    install_http(
        [
            f'v_usDJI="{_long_record("45000.12", "-120.50", "-0.27", truncate_before=20)}"',
            f'v_r_hkHSI="{_long_record("N/A", "0.00", "0.00")}"',
            f'v_s_sh000001="{_short_record("3893.29", "19.85", "0.51")}"',
        ]
    )
    snapshot = market_crosscheck._fetch_tencent_snapshot(("usDJI", "r_hkHSI", "s_sh000001"), 4.0)
    assert snapshot == {"1.000001": (3893.29, 0.51)}


def test_missing_rows_yield_empty_snapshot_silence(install_http) -> None:
    """全部缺行 → 空 snapshot（上游语义：checked=0，交叉核验保持沉默）。"""
    install_http(['v_sz399306="1~别的指数~399306~1000.00~1.00~0.10"'])
    assert (
        market_crosscheck._fetch_tencent_snapshot(("s_sh000001",), 4.0) == {}
    )


def test_crosscheck_quotes_end_to_end_with_gbk_fixture(
    install_http, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fixture → 真实解析 → 两源核验全链路：一致时声明 n/n。"""
    market_crosscheck.reset_crosscheck_cache()
    calls = install_http(
        [
            f'v_s_sh000001="{_short_record("3893.29", "19.85", "0.51")}"',
            f'v_usDJI="{_long_record("45000.12", "-120.50", "-0.27")}"',
        ]
    )

    @dataclass(frozen=True)
    class _Quote:
        code: str
        name: str
        price: float
        change_pct: float

    quotes = [
        _Quote("1.000001", "上证指数", 3890.00, 0.50),
        _Quote("100.DJIA", "道琼斯", 45100.00, -0.30),
    ]
    result = market_crosscheck.crosscheck_quotes(quotes, timeout_seconds=2.0)
    assert result.checked == 2
    assert result.matched == 2
    assert result.ok
    assert "已与腾讯行情交叉核验 ✓ 2/2" in market_crosscheck.format_crosscheck_note(result)
    assert calls and calls[0][0].startswith("https://qt.gtimg.cn/q=")
    market_crosscheck.reset_crosscheck_cache()
