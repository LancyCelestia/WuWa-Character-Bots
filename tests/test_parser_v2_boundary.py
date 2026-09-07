from __future__ import annotations

from datetime import datetime, timezone

from plugins.bot_unified_runtime.contracts.media import (
    ContentIdentity,
    ContentMetadata,
    ParsedContent,
    SourceProvenance,
    build_parsed_content,
)
from plugins.bot_unified_runtime.sources.parsers.context import FetchContext
from plugins.bot_unified_runtime.sources.parsers.http_util import build_request_headers


def _item() -> ParsedContent:
    return build_parsed_content(
        identity=ContentIdentity(
            platform="example",
            item_id="1",
            item_kind="post",
            canonical_url="https://example.test/1",
        ),
        content=ContentMetadata(title="ok"),
        provenance=SourceProvenance(
            parse_depth="deep",
            auth_mode="anonymous",
            fetched_at=datetime.now(timezone.utc),
        ),
    )


def test_fetch_context_sanitizes_credentials_only_for_diagnostics() -> None:
    context = FetchContext(
        platform="twitter",
        timeout_seconds=8,
        cookie_header="auth_token=secret; ct0=secret2",
        extra_headers={"X-Trace": "trace-1"},
    )
    headers = build_request_headers(context)
    assert headers["Cookie"] == "auth_token=secret; ct0=secret2"
    assert context.sanitized_headers()["Cookie"] == "<redacted>"
    assert context.sanitized_headers()["X-Trace"] == "trace-1"


def test_parse_matched_url_invokes_parser_once() -> None:
    from plugins.bot_unified_runtime.capabilities.content_parser import (
        parse_matched_url,
    )

    calls: list[str] = []

    def parse_once(url: str, context: FetchContext) -> ParsedContent:
        calls.append(url)
        return _item()

    result = parse_matched_url(
        ["https://example.test/1"],
        parse_once,
        FetchContext.anonymous("example"),
    )
    assert result.identity is not None
    assert result.identity.item_id == "1"
    assert calls == ["https://example.test/1"]
