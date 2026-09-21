"""P1 静态热点卫生修（q2-hotspot-triage P1-1..P1-4）行为锁定测试。

两类断言：
- 行为等价：同输入同输出，修复前后都必须通过；
- 编译次数：修复后模式编译只发生一次/零次（monkeypatch 计数，修复前应红）。

计数口径：re 内部 _compile 有 512 条缓存且不走公开 re.compile，故 P1-4 的
re.fullmatch 需单独挂计数器才能在修复前变红。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.render import plain_text
from plugins.bot_unified_runtime.runtime import base_router, mentions
from plugins.bot_unified_runtime.sources.registry import (
    ParserRegistry,
    ParserRule,
    SourceInput,
)


def _count_re_compile(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    counter = {"n": 0}
    real_compile: Callable[..., re.Pattern[str]] = re.compile

    def counting_compile(pattern: Any, flags: int = 0) -> re.Pattern[str]:
        counter["n"] += 1
        return real_compile(pattern, flags)

    monkeypatch.setattr(re, "compile", counting_compile)
    return counter


def _count_re_fullmatch(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    counter = {"n": 0}
    real_fullmatch: Callable[..., re.Match[str] | None] = re.fullmatch

    def counting_fullmatch(pattern: Any, string: Any, flags: int = 0) -> Any:
        counter["n"] += 1
        return real_fullmatch(pattern, string, flags)

    monkeypatch.setattr(re, "fullmatch", counting_fullmatch)
    return counter


# --- P1-1 runtime/base_router.extract_http_urls -----------------------------


def test_extract_http_urls_trailing_punctuation_and_dedupe() -> None:
    # 注：现行 URL 正则只排除空白/括号类字符，全角逗号会连进 URL（既有行为，
    # 本次零行为变化不改）；测试用空白分隔以保证断言只锁定「去尾点+去重」。
    text = (
        "看 https://example.com/a?b=1 还有 http://foo.bar/baz. "
        "重复 https://example.com/a?b=1"
    )
    assert base_router.extract_http_urls(text) == [
        "https://example.com/a?b=1",
        "http://foo.bar/baz",
    ]


def test_extract_http_urls_no_url_safe() -> None:
    assert base_router.extract_http_urls("") == []
    assert base_router.extract_http_urls("没有链接") == []


def test_extract_http_urls_compiles_zero_after_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_router.extract_http_urls("预热 https://warm.up/x")
    counter = _count_re_compile(monkeypatch)
    for _ in range(3):
        base_router.extract_http_urls(
            "a https://one.example/x b https://two.example/y"
        )
    assert counter["n"] == 0


# --- P1-2 runtime/mentions.detect_name_mention ------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("岸宝，帮我查天气", True),
        ("守岸人 今天天气怎么样", True),
        ("大家晚上好，守岸人，在吗？", True),
        ("@守岸人", True),
        ("岸宝贝真可爱", False),
        ("今天天气真不错", False),
        ("", False),
    ],
)
def test_detect_name_mention_behavior(text: str, expected: bool) -> None:
    assert mentions.detect_name_mention(text, ["守岸人", "岸宝"]) is expected


def test_detect_name_mention_compiles_zero_after_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terms = ["守岸人", "岸宝"]
    assert mentions.detect_name_mention("大家晚上好，守岸人，在吗？", terms) is True
    counter = _count_re_compile(monkeypatch)
    for _ in range(2):
        assert mentions.detect_name_mention("大家晚上好，守岸人，在吗？", terms) is True
    assert counter["n"] == 0


# --- P1-3 sources/registry.ParserRegistry -----------------------------------


def _make_source(urls: list[str], raw_text: str = "") -> SourceInput:
    return SourceInput(
        request_id="req-1",
        session_id="sess-1",
        capability_id="content_parse",
        urls=urls,
        raw_text=raw_text,
    )


def test_registry_match_url_and_keyword() -> None:
    registry = ParserRegistry()
    registry.register(
        ParserRule(
            parser_id="video",
            source_id="示例视频",
            url_patterns=[r"https?://video\.example/watch/\d+"],
        )
    )
    registry.register(
        ParserRule(parser_id="kw", source_id="关键词", keyword_patterns=["视频"])
    )
    matches = registry.match(
        _make_source(["https://video.example/watch/42"], raw_text="发个视频")
    )
    by_id = {match.parser_id: match for match in matches}
    assert by_id["video"].matched_keyword == "https://video.example/watch/42"
    assert by_id["kw"].matched_keyword == "视频"


def test_registry_match_compiles_zero_after_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ParserRegistry()
    registry.register(
        ParserRule(
            parser_id="p",
            source_id="s",
            url_patterns=[
                r"https?://a\.example/x",
                r"https?://b\.example/y",
            ],
        )
    )
    source = _make_source(["https://a.example/x"])
    assert registry.match(source)  # 预热
    counter = _count_re_compile(monkeypatch)
    for _ in range(2):
        assert registry.match(source)
    assert counter["n"] == 0


# --- P1-4 output/plain_text._table_text -------------------------------------


def test_table_text_converts_pipe_table() -> None:
    md = "列A|列B\n---|---\n1|2\n3|4"
    assert plain_text._table_text(md) == "列A：1；列B：2\n列A：3；列B：4"


def test_table_text_keeps_non_table_lines() -> None:
    md = "a|b\n不是分隔线\n尾部"
    assert plain_text._table_text(md) == md


def test_table_text_ragged_row_flattens() -> None:
    md = "列A|列B\n---|---\n只有一列"
    assert plain_text._table_text(md) == "只有一列"


def test_table_text_fullmatch_zero_after_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain_text._table_text("列A|列B\n---|---\n1|2")
    counter = _count_re_fullmatch(monkeypatch)
    plain_text._table_text("X|Y\n---|---\n1|2")
    plain_text._table_text("无表格文本")
    assert counter["n"] == 0
