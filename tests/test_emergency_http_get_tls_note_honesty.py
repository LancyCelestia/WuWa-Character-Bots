"""S-FIX-ATK-WXEMG T4锁 | http_get.py 头注不得再引用 verify_ssl=False 假先例。

对应审计票 SEAT-ATK-WEATHER T4（欠账）：`domains/emergency_info/sources/http_get.py`
头注曾把「`verify_ssl=False` 的用法同 nmc_weather.py:119（nmc.cn 证书链不完整，
既有做法）」写成样板——而 S-FIX-WXSSL M1 已实测证伪并撤销该说法，
两域 TLS 验证各有锁件在案。文档与代码双真值且方向是**安全降级侧**，
本席已把该段注释改为撤销声明（T4 即修），本件钉死它不回退：

- 「证书链不完整，既有做法」式先例句不得再出现在头注；
- 撤销/证伪字样必须在场；
- 取数签名缺省 verify_ssl=True 两腿在场（防有人连签名一起改）。
"""

from __future__ import annotations

from pathlib import Path

HTTP_GET = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "emergency_info"
    / "sources"
    / "http_get.py"
)


def test_http_get_header_no_longer_cites_false_tls_precedent() -> None:
    src = HTTP_GET.read_text(encoding="utf-8")
    # 假先例句式（票面原文的关键搭配）必须绝迹。
    assert "证书链不完整，既有做法" not in src
    assert "verify_ssl=False`\n  的用法同" not in src
    # 撤销声明必须在场（与 nmc_weather.py:117-121 现文同一事实源口径）。
    assert "证伪" in src and "verify_ssl=False" in src


def test_http_get_signature_defaults_to_verification() -> None:
    src = HTTP_GET.read_text(encoding="utf-8")
    assert src.count("verify_ssl: bool = True") >= 2, (
        "两条取数腿的 verify_ssl 缺省必须都是 True（对齐锁件 "
        "test_weather_tls_verification.py / test_emergency_nmc_tls_verification.py）"
    )
