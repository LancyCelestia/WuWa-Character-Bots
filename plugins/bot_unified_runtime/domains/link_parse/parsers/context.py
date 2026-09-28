from __future__ import annotations

from dataclasses import dataclass, field

from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    DEFAULT_USER_AGENT,
)


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


# F-5（SEAT-ATK-LINKPARSE × 残票收口 S-FIX-ATK-OVERHEAD 2026-09-27）：此处曾有一份
# 同名 `build_request_headers` 直写 Cookie、绕开 WP1 凭证咽喉（credentials_allowed_for_target
# /_apply_cookie_guard/跨 host 剥除），且全树零生产调用方——属「双重真身陷阱」：误
# `from .context import build_request_headers` 会静默复活 F-CRED 类外流。真身唯一出处＝
# `http_util.build_request_headers`（本模块只留 FetchContext/ParseFailure 数据结构）。
