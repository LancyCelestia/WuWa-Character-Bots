from __future__ import annotations

import functools
import re
from urllib.parse import urlsplit

from plugins.bot_unified_runtime.domains.core.contracts.media import (
    ParserMatch,
    ParserRule,
    SourceInput,
)


def _host_matches_domain(host: str, domain: str) -> bool:
    """后缀语义匹配（与 http_util 咽喉同源口径）：www.bilibili.com ∈ .bilibili.com。"""
    host = (host or "").strip().lower().rstrip(".")
    dom = (domain or "").strip().lower().lstrip(".").rstrip(".")
    if not host or not dom:
        return False
    return host == dom or host.endswith("." + dom)


def _candidate_host(candidate: str) -> str:
    try:
        return (urlsplit(candidate or "").hostname or "").strip().lower()
    except ValueError:
        return ""


def _host_belongs(host: str, allowed_hosts: list[str]) -> bool:
    if not allowed_hosts:
        return True  # 合成/无域集规则：不做归属收口（保持既有形态）
    if not host:
        return False
    return any(_host_matches_domain(host, dom) for dom in allowed_hosts)


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
            matched_url = _match_url(source_input, rule.url_patterns, rule.allowed_hosts)
            if matched_keyword is None and matched_url is None:
                continue
            matches.append(
                ParserMatch(
                    parser_id=rule.parser_id,
                    source_id=rule.source_id,
                    matched_keyword=matched_keyword or matched_url,
                    priority=rule.priority,
                    keyword_length=len(matched_keyword or matched_url or ""),
                    allowed_hosts=list(rule.allowed_hosts),
                )
            )
        return sorted(matches, key=lambda match: (-match.keyword_length, match.priority))


def _match_keyword(text: str, keywords: list[str]) -> str | None:
    matched = [keyword for keyword in keywords if keyword and keyword in text]
    if not matched:
        return None
    return max(matched, key=len)


@functools.cache
def _compiled_pattern(pattern: str) -> re.Pattern[str]:
    """注册表 pattern 只编译一次（P1-3：消除解析循环内重复 compile）。"""
    return re.compile(pattern)


def _match_url(
    source_input: SourceInput, patterns: list[str], allowed_hosts: list[str]
) -> str | None:
    """URL 命中并做候选 host 归属收口（WP1 ③）。

    旧缺陷：``compiled.search(candidate)`` 无锚定子串匹配——把平台标识（如
    ``steamcommunity.com/app/123``）塞进任意 evil URL 的 query 里也会命中，
    且返回 matched 子串后被 content_parser 当候选、附该票 Cookie 发往 evil host。
    修法：命中后必须校验**候选 URL 自身**的真实 host 归属规则平台域；不归属
    就不认这条规则的这一次命中。合成规则（allowed_hosts 空）保持旧行为不误伤。
    """
    if not patterns:
        return None
    candidates = list(source_input.urls)
    if source_input.raw_text:
        candidates.append(source_input.raw_text)
    for pattern in patterns:
        compiled = _compiled_pattern(pattern)
        for candidate in candidates:
            match = compiled.search(candidate)
            if not match:
                continue
            if not _host_belongs(_candidate_host(candidate), allowed_hosts):
                continue
            return match.group(0)
    return None
