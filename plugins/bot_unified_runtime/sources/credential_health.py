"""凭据健康检查：cookie 过期预警 + 可选在线探测。

需求：开机时以及固定时间检查 cookie 是否过期、能否正常使用；
不能用时发出"重新登录获取 cookie"预警。

- ``expires_at`` 解析：过期 / 临近过期（``warn_days`` 内）/ 正常 / 未知。
- 在线探测（可选）：对配置的 ``probe_url`` 带上 cookie 发 GET，
  HTTP 200/302 视为可用，401/403 视为需要重新登录，其余为网络错误。
- 输出只含状态和脱敏说明，绝不包含 cookie 值。

配合 APScheduler 的定时任务在 NoneBot 入口注册（配置
``BOT_CREDENTIAL_CHECK_ENABLED=true`` 与检查间隔）。
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from plugins.bot_unified_runtime.sources.credentials import (
    CredentialStore,
    build_credential_store,
)

STATE_OK = "ok"
STATE_EXPIRED = "expired"
STATE_EXPIRING_SOON = "expiring_soon"
STATE_UNKNOWN = "unknown"
STATE_AUTH_REQUIRED = "auth_required"
STATE_NETWORK_ERROR = "network_error"
STATE_NOT_PROBED = "not_probed"


@dataclass(frozen=True)
class CredentialHealthReport:
    ref_id: str
    kind: str
    state: str
    detail: str
    needs_reauth: bool = False


class CredentialHealthChecker:
    def __init__(
        self,
        store: CredentialStore,
        *,
        warn_days: int = 7,
        probe_urls: dict[str, str] | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.store = store
        self.warn_days = max(1, int(warn_days))
        self.probe_urls = dict(probe_urls or {})
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    def check(self, *, probe: bool = False) -> list[CredentialHealthReport]:
        reports: list[CredentialHealthReport] = []
        for ref in self.store.refs():
            reports.append(self._check_ref(ref.ref_id, probe=probe))
        return reports

    def _check_ref(self, ref_id: str, *, probe: bool) -> CredentialHealthReport:
        value = self.store.resolve(ref_id)
        if value is None:
            return CredentialHealthReport(
                ref_id=ref_id,
                kind="unknown",
                state=STATE_UNKNOWN,
                detail="凭据引用存在但无法解析",
                needs_reauth=True,
            )
        expiry_state, detail = self._expiry_state(value.expires_at)
        report = CredentialHealthReport(
            ref_id=value.ref_id,
            kind=value.kind,
            state=expiry_state,
            detail=detail,
            needs_reauth=expiry_state == STATE_EXPIRED,
        )
        if probe and expiry_state in {STATE_OK, STATE_EXPIRING_SOON, STATE_UNKNOWN}:
            report = self._apply_probe(report, value.ref_id, value.value)
        return report

    def _expiry_state(self, expires_at: str) -> tuple[str, str]:
        if not expires_at:
            return STATE_UNKNOWN, "未填写 expires_at，建议补全或做在线探测"
        try:
            expiry = datetime.fromisoformat(expires_at)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
        except ValueError:
            return STATE_UNKNOWN, f"expires_at 无法解析：{expires_at}"
        now = datetime.now(UTC)
        if expiry <= now:
            return STATE_EXPIRED, f"凭据已于 {expires_at} 过期，请重新登录获取"
        if expiry - now <= timedelta(days=self.warn_days):
            return (
                STATE_EXPIRING_SOON,
                f"凭据将在 {expires_at} 过期（{self.warn_days} 天内），建议提前重新登录",
            )
        return STATE_OK, f"凭据有效至 {expires_at}"

    def _apply_probe(
        self,
        report: CredentialHealthReport,
        ref_id: str,
        credential_value: str,
    ) -> CredentialHealthReport:
        url = self.probe_urls.get(ref_id) or self.probe_urls.get("*")
        if not url:
            return CredentialHealthReport(
                ref_id=report.ref_id,
                kind=report.kind,
                state=STATE_NOT_PROBED,
                detail=f"{report.detail}；未配置 probe_url，未做在线探测",
                needs_reauth=report.needs_reauth,
            )
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0"
                    ),
                    "Cookie": credential_value,
                },
            )
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status = int(getattr(response, "status", 200) or 200)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
        except Exception:
            return CredentialHealthReport(
                ref_id=report.ref_id,
                kind=report.kind,
                state=STATE_NETWORK_ERROR,
                detail=f"{report.detail}；在线探测网络失败",
                needs_reauth=False,
            )
        if status in {401, 403}:
            return CredentialHealthReport(
                ref_id=report.ref_id,
                kind=report.kind,
                state=STATE_AUTH_REQUIRED,
                detail=f"在线探测返回 {status}：cookie 已失效，请重新登录获取",
                needs_reauth=True,
            )
        if 200 <= status < 400:
            return CredentialHealthReport(
                ref_id=report.ref_id,
                kind=report.kind,
                state=STATE_OK,
                detail=f"在线探测正常（HTTP {status}）；{report.detail}",
            )
        return CredentialHealthReport(
            ref_id=report.ref_id,
            kind=report.kind,
            state=STATE_NETWORK_ERROR,
            detail=f"在线探测返回 {status}，请稍后重试",
        )


def build_credential_health_checker(config: object) -> CredentialHealthChecker:
    store = build_credential_store(config)
    probe_urls_value = getattr(config, "bot_credential_probe_urls", {})
    if isinstance(probe_urls_value, str) and probe_urls_value.strip():
        try:
            parsed = json.loads(probe_urls_value)
        except ValueError:
            parsed = {}
        probe_urls = (
            {str(k): str(v) for k, v in parsed.items()}
            if isinstance(parsed, dict)
            else {}
        )
    elif isinstance(probe_urls_value, dict):
        probe_urls = {str(k): str(v) for k, v in probe_urls_value.items()}
    else:
        probe_urls = {}
    return CredentialHealthChecker(
        store,
        warn_days=int(getattr(config, "bot_credential_warn_days", 7)),
        probe_urls=probe_urls,
        timeout_seconds=float(getattr(config, "bot_credential_probe_timeout_seconds", 8.0)),
    )


def check_credentials_and_report(
    config: object,
    *,
    probe: bool = False,
) -> list[CredentialHealthReport]:
    """统一入口：供 smoke、NoneBot 定时任务和预警复用。"""
    checker = build_credential_health_checker(config)
    return checker.check(probe=probe)


if __name__ == "__main__":
    # 本地 smoke：python -m plugins.bot_unified_runtime.sources.credential_health
    import argparse
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    from plugins.bot_unified_runtime.smoke import load_smoke_config

    parser = argparse.ArgumentParser(description="凭据健康检查（只读，安全字段）")
    parser.add_argument("--env", default=None)
    parser.add_argument("--probe", action="store_true", help="是否做在线探测（联网）")
    args = parser.parse_args()
    try:
        config = load_smoke_config(args.env)
    except Exception as exc:
        print(f"config_error={exc}")
        raise SystemExit(2)
    reports = check_credentials_and_report(config, probe=args.probe)
    if not reports:
        print("credential_refs=0")
        print("credential_health=ok")
        print("public_message=未配置任何凭据引用，无需检查。")
        raise SystemExit(0)
    problems = [report for report in reports if report.needs_reauth]
    for report in reports:
        print(
            f"ref={report.ref_id} kind={report.kind} state={report.state} "
            f"needs_reauth={str(report.needs_reauth).lower()}"
        )
        print(f"detail={report.detail}")
    if problems:
        print("credential_health=action_required")
        print(
            "public_message=存在需要重新登录的凭据："
            + ",".join(report.ref_id for report in problems)
        )
        raise SystemExit(1)
    print("credential_health=ok")
    raise SystemExit(0)
