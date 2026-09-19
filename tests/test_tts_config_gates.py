"""bot_tts_api_url 装载期 SSRF 闸测试（审计 M-32 / 席 T94）。

语义（U-17=C 宪条：语音引擎必须本机）：fail-closed **白名单**——scheme 必须
http/https，且 host 必须可在装载期**无歧义证明**指向本机 loopback
（127.0.0.0/8 字面量、::1、localhost 字面量、IPv4-mapped 解包后 loopback）。
其余一律 ValidationError：公网/内网段/云元数据 169.254.169.254/整型 IP
（十进制/十六进制/八进制，F-04 口径）/任意域名（装载期不做 DNS）/userinfo
迷惑形态/畸形端口，全部装载期即拒。空值=未配置，回落缺省不触发闸。

生产零影响基线：缺省值与生产 .env 实值均为 ``http://127.0.0.1:9880``
（report-T53.md：引擎绑定 127.0.0.1:9880），必须原样通过、原值保留。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

PROD_URL = "http://127.0.0.1:9880"


def _config(**overrides: object) -> object:
    from plugins.bot_unified_runtime.config import Config

    return Config(**overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 生产零影响（基线：闸落上前就必须绿）
# ---------------------------------------------------------------------------


def test_default_api_url_is_production_loopback() -> None:
    """缺省值=生产实值=127.0.0.1:9880，闸落上后原样通过。"""
    cfg = _config()
    assert cfg.bot_tts_api_url == PROD_URL  # type: ignore[attr-defined]


def test_production_env_value_passes_unchanged() -> None:
    """生产 .env:652 实值（BOT_TTS_API_URL=http://127.0.0.1:9880）装载零影响。"""
    cfg = _config(bot_tts_api_url=PROD_URL)
    assert cfg.bot_tts_api_url == PROD_URL  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 白名单放行面：可无歧义证明为 loopback 的字面量
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:9880",
        "http://LOCALHOST:9880",  # 大小写归一
        "http://localhost.:9880",  # 结尾点归一
        "http://127.0.0.2:9880",  # 127.0.0.0/8 整段
        "http://127.0.0.1",  # 无端口
        "https://127.0.0.1:9880",
        "HTTP://127.0.0.1:9880",  # scheme 大小写
        "http://[::1]:9880",  # IPv6 loopback
        "http://[::ffff:127.0.0.1]:9880",  # IPv4-mapped loopback（解包后=127.0.0.1）
    ],
)
def test_loopback_forms_pass(url: str) -> None:
    cfg = _config(bot_tts_api_url=url)
    assert cfg.bot_tts_api_url == url  # type: ignore[attr-defined]


def test_empty_value_falls_back_to_default_without_gate() -> None:
    """空值=未配置，回落缺省，不触发闸。"""
    cfg = _config(bot_tts_api_url="")
    assert cfg.bot_tts_api_url == PROD_URL  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 拒绝面：scheme
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1:9880",
        "file:///etc/passwd",
        "javascript://127.0.0.1",
        "127.0.0.1:9880",  # 无 scheme（urlsplit 归入 path，host 为空）
    ],
)
def test_non_http_schemes_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        _config(bot_tts_api_url=url)


# ---------------------------------------------------------------------------
# 拒绝面：非 loopback 主机（对照 downloader._BLOCKED_NETWORKS 黑名单口径）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://0.0.0.0:9880",  # 未指定地址
        "http://169.254.169.254:9880/",  # 云元数据（黑名单口径）
        "http://10.1.2.3:9880",  # 内网段
        "http://172.16.0.5:9880",
        "http://192.168.1.5:9880",
        "http://100.64.0.1:9880",  # CGNAT 段
        "http://8.8.8.8:9880",  # 公网
        "http://224.0.0.1:9880",  # 组播
        "http://[fe80::1]:9880/",  # v6 链路本地
        "http://[fc00::1]:9880/",  # v6 ULA
        "http://[::ffff:10.0.0.5]:9880/",  # IPv4-mapped 内网（变体绕过）
        "http://[::ffff:169.254.169.254]:9880/",  # IPv4-mapped 元数据
        "http://evil.example.com:9880/",  # 任意域名：装载期不做 DNS，fail-closed
        "http://127.0.0.1@10.0.0.5:9880/",  # userinfo 迷惑：真 host=10.0.0.5
    ],
)
def test_non_loopback_hosts_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        _config(bot_tts_api_url=url)


# ---------------------------------------------------------------------------
# 拒绝面：整型/歧义 IP 形态（ssrf_guard F-04 口径：只认无歧义字面量）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433:9880/",  # 十进制 = 127.0.0.1，仍拒（inet_aton 歧义形态）
        "http://0x7f000001:9880/",  # 十六进制
        "http://017700000001:9880/",  # 八进制
        "http://134744072:9880/",  # 十进制 = 8.8.8.8
        "http://127.1:9880/",  # 缩写点分（ipaddress 不认，歧义即拒）
    ],
)
def test_integer_and_ambiguous_ip_forms_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        _config(bot_tts_api_url=url)


# ---------------------------------------------------------------------------
# 拒绝面：畸形（F-04「解析失败=拒绝」）
# ---------------------------------------------------------------------------


def test_malformed_port_rejected() -> None:
    with pytest.raises(ValidationError):
        _config(bot_tts_api_url="http://127.0.0.1:abc/")


def test_missing_host_rejected() -> None:
    with pytest.raises(ValidationError):
        _config(bot_tts_api_url="http://")
