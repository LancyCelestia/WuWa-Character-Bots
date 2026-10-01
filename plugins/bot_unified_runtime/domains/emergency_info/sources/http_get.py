"""紧急信息采集源的共享取数件（B2 席）：SSRF 护栏 + 退避重试 + **显式状态**。

本文件只做一件事：把「常量白名单 URL」取回来变成一份带显式结论的文档，
并给全部采集源共用一个**三态**结果对象 `SourceOutcome`。

为什么必须有 `SourceOutcome`（本席唯一的产品级约束）：
现役天气预警支路 `domains/weather/capabilities/weather.py:155-190`
（`fetch_city_alerts`）把「接口不可达」「响应结构不对」「确实没有在报预警」
三种情况**全部返回同一个 `[]`**（源码原文：「接口不可达、响应异常或无命中
一律返回 []（调用方静默）」）。E11 §1.5 已实锤 findAlarm 冷页 24.9s、
现码 timeout=8s 且该支路无重试 ⇒ 生产上会**间歇性把「取数失败」说成
「无预警」**。本席新源不得复制这个病灶：`OK` / `NO_DATA` / `FAILED` 三态
分离，`NO_DATA` 只在「响应结构成立且源端自报零条目」时给出，其余一律
`FAILED` 并带机器可读 `reason`。

样板坐标（九个统一：本席写法抄的是哪个既有正例）：

- HTTP 客户端 = `domains/link_parse/parsers/http_util.py:255`（`http_get_json`，
  真身；`sources/parsers/http_util.py:1-3` 是 v21r2 兼容 shim）。统一 UA /
  超时 / 8MB 响应上限 / 429 有界重试（`http_util.py:169-221`），
  **本席不自建第二套 HTTP 客户端配置**。
- SSRF 护栏 = `domains/link_parse/parsers/ssrf_guard.py:159`（`guard_user_url`），
  其真身收编 `domains/files/sources/downloader.py:363`（`check_download_url`）；
  安全语义 F-04「解析失败=拒绝，绝不放行」。紧急源 URL 虽是常量白名单，
  **仍一律过闸、不豁免**（对齐 `capabilities/media_archive.py`、`capabilities/notes.py`
  的「入口 + 落点」既有口径）。
- 退避重试形态 = `domains/finance/data/stock_data.py:90`（`_network_retry`：
  只重试 `ParseHttpError/ConnectionError/TimeoutError`，其他异常原样抛）；
  次数与退避基数缺省对齐 `domains/weather/capabilities/weather.py:82-83`
  （`_NMC_RETRY_ATTEMPTS = 2`、`_NMC_RETRY_BACKOFF_SECONDS = 0.5`）。
- 超时参数命名 = `domains/weather/data/nmc_weather.py:113`
  （`timeout: float` 关键字参数，`proxy: str = ""`）。TLS 一律缺省验证：
  S-FIX-WXSSL M1（2026-09-27）已实测证伪并撤销「nmc.cn 证书链不完整、
  verify_ssl=False 是既有做法」的旧说法（见 `nmc_weather.py:117-121` 现文），
  两域的 `test_weather_tls_verification.py` / `test_emergency_nmc_tls_verification.py`
  已上锁——勿再传 `verify_ssl=False`，也不得引用它作先例。
- sleep 注入点 = `http_util.py:133-134`（模块级 `_sleep`，测试 monkeypatch
  免真等）；本文件同形态提供 `_backoff_sleep`。

本席零耦合声明：本文件与同席四个源件只依赖 stdlib + link_parse 取数/护栏，
**不 import `domains/emergency_info/contracts.py`**（B1R3 席域模型），解析产物
一律是本席文件内的普通 `@dataclass`；「源解析结果 → 域模型」收口见
report §4 落地请求。
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
    http_get_json,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.ssrf_guard import (
    guard_user_url,
)

T = TypeVar("T")

# --------------------------------------------------------------- 超时/重试缺省

# 通用缺省 10s（与 nmc_weather.py:113 同值）。NMC 预警清单单独放宽到 15s：
# E11 §1.5 实测 pageSize=300 冷页 24.9s / 暖页 0.39s、pageSize=50 冷页 10.3s，
# 现码 8s 必然间歇性掐断（report §3 记这条为「取数失败」而非「无预警」）。
DEFAULT_TIMEOUT_SECONDS = 10.0
NMC_ALARM_TIMEOUT_SECONDS = 15.0

# 缺省 = 现状天气支路的「一次调用」等价（天气侧 attempts=2 含首试），
# 命名与取值抄 weather.py:82-83。
DEFAULT_RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 0.5

# 测试注入点：monkeypatch 本符号避免真实 sleep（同 http_util.py:134 `_sleep` 口径）。
def _backoff_sleep(attempt: int) -> None:
    """重试前的退避（线性，基数抄 weather.py:83）。测试 monkeypatch 本符号。"""
    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))


# --------------------------------------------------------------- 显式三态

class FetchState(str, Enum):
    """一次采集的结论。三态语义互斥，绝不用空列表同时表达两种意思。"""

    OK = "ok"  # 取数成功 **且** 源端确实有条目
    NO_DATA = "no_data"  # 取数成功、结构成立，源端自报「零条目 / 无哨兵值」
    FAILED = "failed"  # 取数失败 / 结构不合预期 / 必需字段缺失（不可信）


@dataclass(frozen=True)
class SourceOutcome(Generic[T]):
    """一条采集链的结论（条目 + 状态 + 机器可读原因）。

    - `reason`：FAILED/NO_DATA 时的原因，形如 `ssrf_rejected:...`、
      `http_error:ParseHttpError`、`missing_field:data.page.list`，
      **调用方必须原样带着它记日志**，不得只凭 `items` 是否为空下结论。
    - `total_hint`：源端自报的总量（如 NMC `data.page.count`、USGS
      `metadata.count`）；与 `len(items)` 不等即说明被分页/上限截断，
      诚实标注用，不做补全。
    - `dropped`：结构成立但个别条目缺必需字段而被丢弃的条数（D-1：
      缺字段就丢，绝不填假值），`reason` 里同步记账。
    """

    state: FetchState
    source_id: str
    items: tuple[T, ...] = ()
    reason: str = ""
    total_hint: int | None = None
    dropped: int = 0
    attempts: int = 1
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def transport_ok(self) -> bool:
        """取数与响应结构是否成立（`FAILED` 之外都为 True）。"""
        return self.state is not FetchState.FAILED

    @property
    def has_items(self) -> bool:
        return bool(self.items)

    @property
    def truncated(self) -> bool:
        """源端总量 > 实收条目数 ⇒ 本次结果不完整（只标注不补全）。"""
        return self.total_hint is not None and self.total_hint > len(self.items)

    def describe(self) -> str:
        """一行人类可读结论（日志/告警用；不含 URL 查询串里的用户输入）。"""
        parts = [f"source={self.source_id}", f"state={self.state.value}"]
        if self.state is FetchState.OK:
            parts.append(f"items={len(self.items)}")
        if self.total_hint is not None:
            parts.append(f"total={self.total_hint}")
        if self.dropped:
            parts.append(f"dropped={self.dropped}")
        if self.reason:
            parts.append(f"reason={self.reason}")
        if self.truncated:
            parts.append("truncated=yes")
        return " ".join(parts)


# --------------------------------------------------------------- URL 白名单闸

# 常量白名单主机（E11 §2 矩阵实测 200 的四个 host）。任何经本件发出的 URL
# 都必须落在这里，再叠加 SSRF 护栏——两道闸任一不过即 FAILED。
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "www.nmc.cn",
        "mobile-new.chinaeew.cn",
        "earthquake.usgs.gov",
        "www.gdacs.org",
    }
)

# 插入 URL 的标识符（stationid / alertid）消毒：只接受字母数字与 _ . -。
# NMC 的 alertid 形如 `51178141600000_20260920002955`、stationid 形如 `Wqsps`
# （E11 §5.2 实测样例）。二者一个来自本地码表、一个来自**上游响应体**，
# 后者属不可信输入：不过消毒就不拼 URL（防路径/查询串注入）。
_SAFE_ID_RE = re.compile(r"^[0-9A-Za-z_.\-]{1,64}$")


class UnsafeIdentifier(ValueError):
    """标识符形态不合白名单形态 ⇒ 不拼 URL、不发请求。"""


class SsrfRejectedError(Exception):
    """URL 未过既有 SSRF 护栏（含 F-04「解析失败=拒绝」）。"""


def require_safe_id(value: str, *, field_name: str = "id") -> str:
    """标识符消毒：形态非法即抛 `UnsafeIdentifier`（D-1：不猜、不修）。"""
    text = str(value or "").strip()
    if not _SAFE_ID_RE.match(text):
        raise UnsafeIdentifier(f"{field_name} 形态非法，已拒绝拼入 URL")
    return text


def check_whitelisted_url(url: str) -> None:
    """常量白名单主机校验（第一道闸）；失败抛 `SsrfRejectedError`。"""
    from urllib.parse import urlsplit

    host = (urlsplit(str(url or "")).hostname or "").strip().lower()
    if host not in ALLOWED_HOSTS:
        raise SsrfRejectedError(f"主机 {host or '空'} 不在紧急源常量白名单内")


def guard_outbound_url(url: str) -> None:
    """两道闸一次走完：常量白名单 → 既有 SSRF 护栏（`guard_user_url`）。

    护栏返回原因即拒绝；返回 None 才算放行（F-04 语义见 ssrf_guard.py:117-156）。
    """
    check_whitelisted_url(url)
    reason = guard_user_url(url)
    if reason is not None:
        raise SsrfRejectedError(str(reason))


# --------------------------------------------------------------- 取数

FetchJson = Callable[[str], Any]
"""取数替身契约：`url -> 已解码 JSON 文档`；失败一律抛异常。"""


@dataclass(frozen=True)
class RawDoc:
    """一次取数的原始结果：要么有 payload，要么有失败原因（互斥）。"""

    payload: Any = None
    failure: str = ""
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return not self.failure


def fetch_json_document(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    proxy: str = "",
    verify_ssl: bool = True,
    retry: int = DEFAULT_RETRY_ATTEMPTS,
) -> Any:
    """真实取数：过闸 → `http_get_json` → 瞬时故障退避重试；失败一律抛。

    - 每一跳（含重试）之前都重新过 `guard_outbound_url`，重试不豁免护栏。
    - 只重试 `ParseHttpError/ConnectionError/TimeoutError`（抄
      `stock_data.py:90` 的判据）；`SsrfRejectedError` 是确定性拒绝，
      立即上抛不空耗预算。
    """
    attempts = max(1, int(retry))
    last_exc: Exception | None = None
    for attempt in range(attempts):
        guard_outbound_url(url)
        try:
            return http_get_json(
                url, proxy=proxy, timeout=timeout, verify_ssl=verify_ssl
            )
        except (ParseHttpError, ConnectionError, TimeoutError) as exc:
            last_exc = exc
            if attempt + 1 >= attempts:
                raise
            _backoff_sleep(attempt)
    if last_exc is not None:  # pragma: no cover - 循环必经 return/raise
        raise last_exc
    raise ParseHttpError("取数循环异常退出")  # pragma: no cover


def resolve_document(
    url: str,
    *,
    fetch: FetchJson | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    proxy: str = "",
    verify_ssl: bool = True,
    retry: int = DEFAULT_RETRY_ATTEMPTS,
) -> RawDoc:
    """执行取数并把异常收敛成 `RawDoc.failure`（**不**收敛成空列表）。

    `fetch` 非 None 时即测试注入的替身（全离线）：替身自己承担重试语义，
    本函数只把它的异常翻译成显式失败原因。`fetch` 为 None 走真实取数。
    """
    if fetch is not None:
        try:
            return RawDoc(payload=fetch(url), attempts=1)
        except SsrfRejectedError as exc:
            return RawDoc(failure=f"ssrf_rejected:{exc}")
        except Exception as exc:  # noqa: BLE001 - 替身抛什么都要变显式失败态
            return RawDoc(failure=f"http_error:{type(exc).__name__}")
    try:
        payload = fetch_json_document(
            url,
            timeout=timeout,
            proxy=proxy,
            verify_ssl=verify_ssl,
            retry=retry,
        )
    except SsrfRejectedError as exc:
        return RawDoc(failure=f"ssrf_rejected:{exc}", attempts=1)
    except Exception as exc:  # noqa: BLE001 - 同上：异常必须是状态，不是空值
        return RawDoc(failure=f"http_error:{type(exc).__name__}", attempts=max(1, retry))
    return RawDoc(payload=payload, attempts=1)


def failed_outcome(source_id: str, reason: str, *, attempts: int = 1) -> SourceOutcome[Any]:
    """构造 `FAILED` 结论（零条目 + 原因），供各源件复用。"""
    return SourceOutcome(state=FetchState.FAILED, source_id=source_id, reason=reason, attempts=attempts)


__all__ = [
    "ALLOWED_HOSTS",
    "DEFAULT_RETRY_ATTEMPTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "NMC_ALARM_TIMEOUT_SECONDS",
    "RETRY_BACKOFF_SECONDS",
    "FetchJson",
    "FetchState",
    "ParseHttpError",
    "RawDoc",
    "SourceOutcome",
    "SsrfRejectedError",
    "UnsafeIdentifier",
    "check_whitelisted_url",
    "failed_outcome",
    "fetch_json_document",
    "guard_outbound_url",
    "require_safe_id",
    "resolve_document",
]
