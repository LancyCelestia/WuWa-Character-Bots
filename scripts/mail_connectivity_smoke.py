from __future__ import annotations

import argparse
import imaplib
import json
import re
import smtplib
import socket
import ssl
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MailAccount:
    account_id: str
    name: str
    password: str = field(repr=False)
    subject: str = "Bot reply"
    imap_host: str = ""
    imap_port: int = 993
    imap_tls: bool = True
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_tls: bool = True


@dataclass(frozen=True)
class MailProbeResult:
    account_id: str
    imap_ok: bool
    smtp_ok: bool
    latency_ms: int
    detail: str

    @property
    def ok(self) -> bool:
        return self.imap_ok and self.smtp_ok


def _host(item: dict[str, Any], field_name: str) -> tuple[str, int, bool]:
    value = item.get(field_name)
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    host = str(value.get("host", "")).strip()
    if not host:
        raise ValueError(f"{field_name}.host is required")
    return host, int(value.get("port", 0)), bool(value.get("tls", True))


def parse_mail_accounts(raw: str) -> list[MailAccount]:
    value = str(raw or "").strip()
    if not value:
        return []
    data = json.loads(value)
    if not isinstance(data, list):
        raise TypeError("MAIL_BOTS must be a JSON array")
    accounts: list[MailAccount] = []
    for item in data:
        if not isinstance(item, dict):
            raise TypeError("MAIL_BOTS entries must be objects")
        imap_host, imap_port, imap_tls = _host(item, "imap")
        smtp_host, smtp_port, smtp_tls = _host(item, "smtp")
        accounts.append(
            MailAccount(
                account_id=str(item.get("id", "")).strip(),
                name=str(item.get("name", "")).strip(),
                password=str(item.get("password", "")),
                subject=str(item.get("subject", "Bot reply")),
                imap_host=imap_host,
                imap_port=imap_port,
                imap_tls=imap_tls,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_tls=smtp_tls,
            )
        )
    return accounts


def _safe_detail(value: object, secret: str) -> str:
    text = str(value)
    if secret:
        text = text.replace(secret, "[redacted]")
    text = re.sub(
        r"(?i)(password|authorization[_ -]?code|token)(\s*[:=]\s*)\S+",
        r"\1\2[redacted]",
        text,
    )
    return text[:500]


def probe_mail_account(
    account: MailAccount,
    *,
    imap_ssl_factory: Callable[..., Any] = imaplib.IMAP4_SSL,
    imap_factory: Callable[..., Any] = imaplib.IMAP4,
    smtp_ssl_factory: Callable[..., Any] = smtplib.SMTP_SSL,
    smtp_factory: Callable[..., Any] = smtplib.SMTP,
    timeout: float = 15.0,
) -> MailProbeResult:
    started = time.perf_counter()
    imap_ok = False
    smtp_ok = False
    details: list[str] = []
    imap_client: Any | None = None
    try:
        if account.imap_tls:
            imap_client = imap_ssl_factory(
                account.imap_host,
                account.imap_port,
                ssl_context=ssl.create_default_context(),
                timeout=timeout,
            )
        else:
            imap_client = imap_factory(
                account.imap_host,
                account.imap_port,
                timeout=timeout,
            )
        imap_client.login(account.account_id, account.password)
        imap_ok = True
        details.append("imap_auth_ok")
    except Exception as exc:  # noqa: BLE001 - CLI must classify heterogeneous provider failures.
        details.append(f"imap_error:{_safe_detail(exc, account.password)}")
    finally:
        if imap_client is not None:
            try:
                imap_client.logout()
            except Exception:  # noqa: BLE001, S110 - logout cleanup is best effort.
                pass

    try:
        if account.smtp_tls:
            smtp_context = smtp_ssl_factory(
                account.smtp_host,
                account.smtp_port,
                context=ssl.create_default_context(),
                timeout=timeout,
            )
            with smtp_context as smtp_client:
                smtp_client.ehlo()
                smtp_client.login(account.account_id, account.password)
        else:
            smtp_context = smtp_factory(
                account.smtp_host,
                account.smtp_port,
                timeout=timeout,
            )
            with smtp_context as smtp_client:
                smtp_client.ehlo()
                smtp_client.starttls(context=ssl.create_default_context())
                smtp_client.ehlo()
                smtp_client.login(account.account_id, account.password)
        smtp_ok = True
        details.append("smtp_auth_ok")
    except Exception as exc:  # noqa: BLE001 - CLI must classify heterogeneous provider failures.
        details.append(f"smtp_error:{_safe_detail(exc, account.password)}")

    return MailProbeResult(
        account_id=account.account_id,
        imap_ok=imap_ok,
        smtp_ok=smtp_ok,
        latency_ms=int((time.perf_counter() - started) * 1000),
        detail="; ".join(details),
    )


def probe_tls_endpoint(host: str, port: int, *, timeout: float = 10.0) -> tuple[bool, str]:
    try:
        with (
            socket.create_connection((host, port), timeout=timeout) as raw,
            ssl.create_default_context().wrap_socket(
                raw, server_hostname=host
            ) as secure,
        ):
            protocol = secure.version() or "TLS"
        return True, protocol
    except Exception as exc:  # noqa: BLE001 - network diagnostic only.
        return False, type(exc).__name__


def _load_env_value(path: Path, key: str) -> str:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Test Gmail/QQ IMAP and SMTP settings without sending mail."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--network-only", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    if args.network_only:
        endpoints = [
            ("gmail-imap", "imap.gmail.com", 993),
            ("gmail-smtp", "smtp.gmail.com", 465),
            ("qq-imap", "imap.qq.com", 993),
            ("qq-smtp", "smtp.qq.com", 465),
        ]
        results = []
        for name, host, port in endpoints:
            ok, detail = probe_tls_endpoint(host, port, timeout=args.timeout)
            results.append({"name": name, "host": host, "port": port, "ok": ok, "detail": detail})
    else:
        raw = _load_env_value(Path(args.env_file), "MAIL_BOTS")
        accounts = parse_mail_accounts(raw)
        if not accounts:
            print("MAIL_BOTS is empty; no credentials were tested.", file=sys.stderr)
            return 2
        results = [asdict(probe_mail_account(account, timeout=args.timeout)) for account in accounts]
        for item in results:
            item["ok"] = bool(item["imap_ok"] and item["smtp_ok"])

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            mark = "PASS" if item["ok"] else "FAIL"
            print(f"{mark} {item}")
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
