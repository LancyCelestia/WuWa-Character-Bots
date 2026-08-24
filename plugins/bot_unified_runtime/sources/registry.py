from __future__ import annotations

import re

from plugins.bot_unified_runtime.contracts.media import (
    ParserMatch,
    ParserRule,
    SourceInput,
)


class ParserRegistry:
    def __init__(self) -> None:
        self._rules: list[ParserRule] = []

    def register(self, rule: ParserRule) -> None:
        self._rules.append(rule)

    def match(self, source_input: SourceInput) -> list[ParserMatch]:
        matches: list[ParserMatch] = []
        text = source_input.raw_text
        for rule in self._rules:
            if not rule.enabled:
                continue
            matched_keyword = _match_keyword(text, rule.keyword_patterns)
            matched_url = _match_url(source_input, rule.url_patterns)
            if matched_keyword is None and matched_url is None:
                continue
            matches.append(
                ParserMatch(
                    parser_id=rule.parser_id,
                    source_id=rule.source_id,
                    matched_keyword=matched_keyword or matched_url,
                    priority=rule.priority,
                    keyword_length=len(matched_keyword or matched_url or ""),
                )
            )
        return sorted(matches, key=lambda match: (-match.keyword_length, match.priority))


def _match_keyword(text: str, keywords: list[str]) -> str | None:
    matched = [keyword for keyword in keywords if keyword and keyword in text]
    if not matched:
        return None
    return max(matched, key=len)


def _match_url(source_input: SourceInput, patterns: list[str]) -> str | None:
    if not patterns:
        return None
    candidates = list(source_input.urls)
    if source_input.raw_text:
        candidates.append(source_input.raw_text)
    for pattern in patterns:
        compiled = re.compile(pattern)
        for candidate in candidates:
            match = compiled.search(candidate)
            if match:
                return match.group(0)
    return None
