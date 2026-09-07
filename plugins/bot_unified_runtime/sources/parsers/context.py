from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generic, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .http_util import DEFAULT_USER_AGENT

T = TypeVar("T")
_SENSITIVE_QUERY = re.compile(r"token|key|sign|auth|cookie|sid", re.IGNORECASE)


@dataclass(frozen=True)
class FetchContext:
    platform: str
    timeout_seconds: float = 10.0
    cookie_header: str = ""
    proxy: str = ""
    user_agent: str = DEFAULT_USER_AGENT
    trace_id: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def anonymous(cls, platform: str, *, timeout_seconds: float = 10.0) -> FetchContext:
        return cls(platform=platform, timeout_seconds=timeout_seconds)

    def sanitized_headers(self) -> dict[str, str]:
        headers = dict(self.extra_headers)
        headers["User-Agent"] = self.user_agent
        if self.cookie_header:
            headers["Cookie"] = "<redacted>"
        return headers


@dataclass(frozen=True)
class FetchEnvelope(Generic[T]):
    payload: T
    final_url: str
    status_code: int | None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_endpoint: str = ""
    warnings: list[str] = field(default_factory=list)


class ParseFailure(Exception):
    def __init__(
        self,
        code: str,
        platform: str,
        operation: str,
        *,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
        public_message: str = "",
    ) -> None:
        self.code = str(code)
        self.platform = str(platform)
        self.operation = str(operation)
        self.retryable = bool(retryable)
        self.retry_after_seconds = retry_after_seconds
        self.public_message = str(public_message)
        super().__init__(f"{self.code}: {self.platform}/{self.operation}")


def sanitize_url(url: str) -> str:
    parts = urlsplit(str(url))
    safe_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _SENSITIVE_QUERY.search(key)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))


def build_request_headers(context: FetchContext) -> dict[str, str]:
    headers = {
        "User-Agent": context.user_agent,
        "Accept-Encoding": "gzip",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if context.cookie_header:
        headers["Cookie"] = context.cookie_header
    headers.update(context.extra_headers)
    return headers


def classify_http_failure(status_code: int | None, *, platform: str, operation: str) -> ParseFailure:
    if status_code in {401, 403}:
        return ParseFailure("auth_required", platform, operation, retryable=False)
    if status_code == 429:
        return ParseFailure("rate_limited", platform, operation, retryable=True)
    if status_code is not None and status_code >= 500:
        return ParseFailure("network_error", platform, operation, retryable=True)
    return ParseFailure("invalid_payload", platform, operation, retryable=False)
