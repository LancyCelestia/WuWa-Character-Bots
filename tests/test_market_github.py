"""全球股指行情 + GitHub 仓库解析回归测试（全部离线，HTTP 均打桩）。

夹具取自 2026-09-11 真实探针：
- 东方财富 push2 ``ulist.np/get``（15 个有效指数，``100.BSESN``/``100.IMOEX``
  实测无数据已从宇宙剔除）；
- api.github.com ``/repos/psf/requests`` 与 ``/readme``（字段按真实响应保留）。
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.market import (
    build_market_capability,
    is_market_command,
    market_filter_secids,
)
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.sources import market_data
from plugins.bot_unified_runtime.sources.market_data import (
    IndexQuote,
    fetch_index_quotes,
    format_market_brief,
    format_quote_line,
    reset_market_cache,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
from plugins.bot_unified_runtime.sources.parsers.platforms_github import (
    GITHUB_URL_PATTERNS,
    _decode_readme,
    _markdown_excerpt,
    match_github_repo,
    parse_github,
)

# ---------------------------------------------------------------------------
# 真实探针夹具
# ---------------------------------------------------------------------------

# 真实响应（push2 ulist.np/get，fltt=2）：字段仅保留 f2/f3/f4/f12/f14。
EM_FIXTURE: dict = {
    "rc": 0,
    "data": {
        "total": 15,
        "diff": [
            {"f2": 3934.4, "f3": -0.43, "f4": -17.11, "f12": "000001", "f14": "上证指数"},
            {"f2": 13617.67, "f3": -0.77, "f4": -105.65, "f12": "399001", "f14": "深证成指"},
            {"f2": 3338.42, "f3": -0.49, "f4": -16.55, "f12": "399006", "f14": "创业板指"},
            {"f2": 24954.47, "f3": -1.27, "f4": -320.49, "f12": "HSI", "f14": "恒生指数"},
            {"f2": 65270.95, "f3": 0.2, "f4": 128.17, "f12": "N225", "f14": "日经225"},
            {"f2": 7033.92, "f3": -0.25, "f4": -17.72, "f12": "KS11", "f14": "韩国KOSPI"},
            {"f2": 5689.75, "f3": -0.7, "f4": -39.88, "f12": "STI", "f14": "富时新加坡海峡时报"},
            {"f2": 74902.59, "f3": 0.19, "f4": 138.36, "f12": "SENSEX", "f14": "印度孟买SENSEX"},
            {"f2": 10608.92, "f3": -0.57, "f4": -61.14, "f12": "FTSE", "f14": "英国富时100"},
            {"f2": 8116.76, "f3": -0.49, "f4": -39.91, "f12": "FCHI", "f14": "法国CAC40"},
            {"f2": 25361.15, "f3": -0.84, "f4": -215.3, "f12": "GDAXI", "f14": "德国DAX30"},
            {"f2": 52018.17, "f3": -0.69, "f4": -362.49, "f12": "DJIA", "f14": "道琼斯"},
            {"f2": 7590.68, "f3": -0.6, "f4": -45.68, "f12": "SPX", "f14": "标普500"},
            {"f2": 26079.55, "f3": -0.66, "f4": -173.79, "f12": "NDX", "f14": "纳斯达克"},
            {"f2": 46940.49, "f3": -0.51, "f4": -242.87, "f12": "TWII", "f14": "台湾加权"},
        ],
    },
}

# 真实响应（api.github.com/repos/psf/requests，字段裁剪到解析器消费的键）。
GH_REPO_FIXTURE: dict = {
    "full_name": "psf/requests",
    "description": "A simple, yet elegant, HTTP library.",
    "html_url": "https://github.com/psf/requests",
    "stargazers_count": 54293,
    "forks_count": 10132,
    "open_issues_count": 237,
    "language": "Python",
    "topics": ["client", "cookies", "http", "python", "requests"],
    "license": {
        "key": "apache-2.0",
        "name": "Apache License 2.0",
        "spdx_id": "Apache-2.0",
    },
    "updated_at": "2026-09-10T14:42:19Z",
    "pushed_at": "2026-09-07T16:54:39Z",
    "default_branch": "main",
    "homepage": "https://requests.readthedocs.io/en/latest/",
    "owner": {"login": "psf", "type": "Organization"},
}

# 真实 README 的开头（Requests 官方 README 正文节选，供 base64 编码成夹具）。
GH_README_MARKDOWN = """# Requests

[![Version](https://img.shields.io/pypi/v/requests.svg)](https://pypi.org/project/requests/)

**Requests** is a simple, yet elegant, HTTP library.

```python
>>> import requests
>>> r = requests.get('https://api.github.com')
```

Requests allows you to send HTTP/1.1 requests extremely easily.
There's no need to manually add query strings to your URLs.
"""

GH_README_FIXTURE: dict = {
    "encoding": "base64",
    "content": base64.b64encode(GH_README_MARKDOWN.encode("utf-8")).decode("ascii"),
}


class _Clock:
    """可控单调时钟：fetch TTL 测试用，避免依赖真实睡眠。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def _clean_market_cache() -> Iterator[None]:
    reset_market_cache()
    yield
    reset_market_cache()


# ---------------------------------------------------------------------------
# market_data：解析 / 缓存 / 降级
# ---------------------------------------------------------------------------


def test_parse_quotes_from_real_fixture(_clean_market_cache, monkeypatch) -> None:
    monkeypatch.setattr(market_data, "_fetch_payload", lambda secids, timeout: EM_FIXTURE)
    quotes = fetch_index_quotes()
    assert len(quotes) == 15
    assert quotes[0].name == "上证指数"
    assert quotes[0].code == "1.000001"
    assert quotes[0].price == 3934.4
    assert quotes[0].change_pct == -0.43
    assert quotes[0].change_abs == -17.11
    by_code = {quote.code: quote for quote in quotes}
    assert by_code["100.DJIA"].name == "道琼斯"
    assert by_code["100.TWII"].name == "台湾加权"
    # 实测无效的 secid 不应出现在宇宙里。
    all_codes = {quote.code for quote in quotes}
    assert "100.BSESN" not in all_codes
    assert "100.IMOEX" not in all_codes
    universe_codes = {secid for secid, _n, _g in market_data._INDEX_UNIVERSE}
    assert "100.BSESN" not in universe_codes
    assert "100.IMOEX" not in universe_codes


def test_quote_rows_with_missing_values_skipped(_clean_market_cache, monkeypatch) -> None:
    broken = {
        "data": {
            "diff": [
                {"f2": "-", "f3": -0.43, "f4": -17.11, "f12": "000001", "f14": "上证指数"},
                {"f3": -0.77, "f4": -105.65, "f12": "399001", "f14": "深证成指"},
                {"f2": 24954.47, "f3": -1.27, "f4": None, "f12": "HSI", "f14": "恒生指数"},
            ]
        }
    }
    monkeypatch.setattr(market_data, "_fetch_payload", lambda secids, timeout: broken)
    quotes = fetch_index_quotes()
    # f2="-" 和整行缺 f2 的被丢弃；f4 缺失只影响涨跌额（None 可容忍）。
    assert [quote.code for quote in quotes] == ["100.HSI"]
    assert quotes[0].change_abs is None


def test_fetch_failure_returns_empty_never_raises(
    _clean_market_cache, monkeypatch
) -> None:
    def _boom(secids: str, timeout: float) -> dict:
        raise OSError("network down")

    monkeypatch.setattr(market_data, "_fetch_payload", _boom)
    assert fetch_index_quotes() == []
    # 非法载荷（非 dict / 缺 data）同样安全降级。
    monkeypatch.setattr(market_data, "_fetch_payload", lambda secids, timeout: None)
    assert fetch_index_quotes() == []
    monkeypatch.setattr(market_data, "_fetch_payload", lambda secids, timeout: {"data": None})
    assert fetch_index_quotes() == []


def test_cache_ttl_hit_expiry_and_failure_not_cached(monkeypatch) -> None:
    reset_market_cache()
    clock = _Clock()
    calls: list[int] = []

    def _fake(secids: str, timeout: float) -> dict:
        calls.append(1)
        if len(calls) == 3:
            raise OSError("transient blip")
        return EM_FIXTURE

    monkeypatch.setattr(market_data.time, "monotonic", clock)
    monkeypatch.setattr(market_data, "_fetch_payload", _fake)

    assert len(fetch_index_quotes(cache_seconds=60)) == 15
    clock.now = 1030.0  # TTL 内
    assert len(fetch_index_quotes(cache_seconds=60)) == 15
    assert len(calls) == 1
    clock.now = 1061.0  # TTL 过期 → 重新拉取
    assert len(fetch_index_quotes(cache_seconds=60)) == 15
    assert len(calls) == 2
    clock.now = 1122.0  # 再次过期 → 这次外呼失败 → 返回空且不缓存。
    assert fetch_index_quotes(cache_seconds=60) == []
    assert len(calls) == 3
    # 失败未污染缓存：立即重试成功并重建缓存。
    assert len(fetch_index_quotes(cache_seconds=60)) == 15
    assert len(calls) == 4
    clock.now = 1183.0  # 缓存过期 → 再拉取（夹具正常）。
    assert len(fetch_index_quotes(cache_seconds=60)) == 15
    assert len(calls) == 5
    clock.now = 1213.0  # TTL 内 → 命中缓存，不再外呼。
    assert len(fetch_index_quotes(cache_seconds=60)) == 15
    assert len(calls) == 5
    reset_market_cache()


# ---------------------------------------------------------------------------
# format_market_brief：分组 / 涨跌标记 / 空结果
# ---------------------------------------------------------------------------


def _sample_quotes() -> list[IndexQuote]:
    return [
        IndexQuote("上证指数", "1.000001", 3934.4, -0.43, -17.11),
        IndexQuote("道琼斯", "100.DJIA", 42114.4, 0.58, 242.11),
        IndexQuote("恒生指数", "100.HSI", 24954.47, 0.0, 0.0),
    ]


def test_format_market_brief_grouping_and_markers() -> None:
    text = format_market_brief(_sample_quotes())
    assert text.startswith("全球股指速览")
    assert "—— 中国区 ——" in text
    assert "—— 亚太 ——" in text
    assert "—— 欧美 ——" in text
    # 分组顺序：中国区在亚太之前，亚太在欧美之前。
    assert text.index("中国区") < text.index("亚太") < text.index("欧美")
    assert "🔴 道琼斯 42114.40 +0.58%（+242.11）" in text
    assert "🟢 上证指数 3934.40 -0.43%（-17.11）" in text
    assert "⚪ 恒生指数 24954.47 0.00%" in text


def test_format_quote_line_without_abs() -> None:
    line = format_quote_line(IndexQuote("纳斯达克", "100.NDX", 26079.55, -0.66))
    assert line == "🟢 纳斯达克 26079.55 -0.66%"


def test_format_market_brief_empty_degrades() -> None:
    assert format_market_brief([]) == "行情数据暂时拉不到，晚点再试试？"


# ---------------------------------------------------------------------------
# capabilities/market：触发判定 / 市场过滤 / 降级
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("行情", True),
        ("大盘", True),
        ("股指", True),
        ("全球股市", True),
        ("A股行情", True),
        ("美股行情怎么样", True),
        ("看看日经行情", True),
        ("今天天气如何", False),
        ("房价行情", False),  # 非股市语境让路
        ("基金行情", False),
        ("股市大盘行情", True),  # 非股词 + 股票词 → 放行
        ("顺手看看 https://example.com 行情", False),  # 带链接不抢
        ("行情" * 20, False),  # 超长文本不抢（那是聊天的活）
        ("", False),
    ],
)
def test_is_market_command_matrix(text: str, expected: bool) -> None:
    assert is_market_command(text) is expected


def test_market_filter_secids() -> None:
    assert market_filter_secids("美股行情") == frozenset({"100.DJIA", "100.SPX", "100.NDX"})
    assert market_filter_secids("日经行情") == frozenset({"100.N225"})
    assert "1.000001" in market_filter_secids("A股行情")
    assert market_filter_secids("行情") == frozenset()


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        request_id="req-market-test",
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        plain_text=text,
    )


def _make_decision() -> BotDecision:
    return BotDecision(
        request_id="req-market-test",
        should_respond=True,
        mode="command",
        trigger="行情",
        capability_id="bot.market",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )


def test_market_capability_full_and_filtered(monkeypatch) -> None:
    quotes = [
        IndexQuote("上证指数", "1.000001", 3934.4, -0.43, None),
        IndexQuote("道琼斯", "100.DJIA", 42114.4, 0.58, None),
        IndexQuote("纳斯达克", "100.NDX", 26079.55, -0.66, None),
    ]
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.market.fetch_index_quotes",
        lambda timeout_seconds, cache_seconds: list(quotes),
    )
    capability = build_market_capability(config=None)

    result = capability(_make_message("行情"), _make_decision())
    assert result.kind == "text"
    assert result.capability_id == "bot.market"
    assert "上证指数" in result.body
    assert "道琼斯" in result.body
    assert "capability:market" in result.audit_tags

    us_result = capability(_make_message("美股行情"), _make_decision())
    assert "道琼斯" in us_result.body
    assert "纳斯达克" in us_result.body
    assert "上证指数" not in us_result.body


def test_market_capability_fetch_failure_degrades(monkeypatch) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.market.fetch_index_quotes",
        lambda timeout_seconds, cache_seconds: [],
    )
    capability = build_market_capability(config=None)
    result = capability(_make_message("行情"), _make_decision())
    assert result.body == "行情数据暂时拉不到，晚点再试试？"
    assert "market:fetch_failed" in result.audit_tags


def test_market_capability_unknown_filter_falls_back_to_all(monkeypatch) -> None:
    quotes = [IndexQuote("上证指数", "1.000001", 3934.4, -0.43, None)]
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.market.fetch_index_quotes",
        lambda timeout_seconds, cache_seconds: list(quotes),
    )
    capability = build_market_capability(config=None)
    # 「韩股行情」的「韩」命中过滤词，但夹具只有上证 → 回退全部而非空回复。
    result = capability(_make_message("韩股行情"), _make_decision())
    assert "上证指数" in result.body


# ---------------------------------------------------------------------------
# platforms_github：URL 匹配 / README 剥离 / 解析 / 失败降级
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/psf/requests", ("psf", "requests")),
        ("https://github.com/psf/requests/", ("psf", "requests")),
        ("https://github.com/psf/requests/tree/main/src", ("psf", "requests")),
        ("https://github.com/psf/requests/blob/main/README.md", ("psf", "requests")),
        ("https://github.com/psf/requests/releases/tag/v2.32.0", ("psf", "requests")),
        ("https://github.com/psf/requests/issues/6777", ("psf", "requests")),
        ("https://github.com/psf/requests/pull/6800", ("psf", "requests")),
        ("https://github.com/psf/requests.git", ("psf", "requests")),
        ("github.com/microsoft/vscode", ("microsoft", "vscode")),
    ],
)
def test_match_github_repo_accepts_repo_links(url: str, expected: tuple[str, str]) -> None:
    assert match_github_repo(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/features",
        "https://github.com/features/actions",
        "https://github.com/topics/python",
        "https://github.com/trending",
        "https://github.com/marketplace",
        "https://github.com/explore",
        "https://github.com/sponsors",
        "https://github.com/settings/profile",
        "https://github.com/",
        "https://gitlab.com/psf/requests",
        "随便聊聊 github 是什么",
    ],
)
def test_match_github_repo_rejects_non_repo(url: str) -> None:
    assert match_github_repo(url) is None


def test_registry_url_pattern_matrix() -> None:
    # 注册层建议模式：仓库/子路径命中宽匹配（非仓库自有页由 parse_github
    # 内部再校验后抛错走通用兜底）；features 单段页不命中。
    pattern = re.compile(GITHUB_URL_PATTERNS[0])
    assert pattern.search("https://github.com/psf/requests")
    assert pattern.search("https://github.com/psf/requests/blob/main/README.md")
    assert not pattern.search("https://github.com/features")


def test_markdown_excerpt_strips_noise() -> None:
    excerpt = _markdown_excerpt(GH_README_MARKDOWN, limit=200)
    assert "Requests" in excerpt
    assert "simple, yet elegant, HTTP library" in excerpt
    assert "requests extremely easily" in excerpt
    # 代码块/图片/裸链接不进摘要。
    assert "import requests" not in excerpt
    assert "img.shields.io" not in excerpt
    assert "https://" not in excerpt
    assert "```" not in excerpt
    assert "[" not in excerpt and "]" not in excerpt


def test_markdown_excerpt_bounded_at_500_chars() -> None:
    long_md = "这是一段很长的中文说明。" * 100
    excerpt = _markdown_excerpt(long_md)
    assert len(excerpt) <= 501  # 500 + 省略号
    assert excerpt.endswith("…")


def test_decode_readme_base64_and_fallback() -> None:
    assert "Requests" in _decode_readme(GH_README_FIXTURE)
    assert _decode_readme({"encoding": "base64", "content": "not!!valid"}) == ""
    assert _decode_readme({"encoding": "plain", "content": "# hi"}) == "# hi"
    assert _decode_readme(None) == ""
    assert _decode_readme({}) == ""


def test_parse_github_happy_path(monkeypatch) -> None:
    calls: list[str] = []

    def _fake_get(url: str) -> dict:
        calls.append(url)
        if url.endswith("/readme"):
            return dict(GH_README_FIXTURE)
        return dict(GH_REPO_FIXTURE)

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_github._github_get_json",
        _fake_get,
    )
    result = parse_github("https://github.com/psf/requests/blob/main/README.md")
    assert result.identity is not None
    assert result.identity.platform == "github"
    assert result.identity.item_id == "psf/requests"
    assert result.identity.item_kind == "repo"
    assert result.identity.canonical_url == "https://github.com/psf/requests"
    assert result.content is not None
    assert result.content.title == "psf/requests"
    assert result.content.summary == "A simple, yet elegant, HTTP library."
    assert "Requests" in result.content.body
    assert "client" in result.content.tags
    assert result.creator is not None
    assert result.creator.name == "psf"
    extras = result.engagement.platform_extra
    assert extras["星标"] == 54293
    assert extras["Fork"] == 10132
    assert extras["主语言"] == "Python"
    assert extras["许可证"] == "Apache License 2.0"
    assert extras["最近更新"] == "2026-09-10"
    # 子路径 URL 归一后只调仓库 + readme 两个接口。
    assert sorted(url.rsplit("/", 1)[-1] for url in calls) == ["readme", "requests"]


def test_parse_github_readme_failure_still_builds_card(monkeypatch) -> None:
    def _fake_get(url: str) -> dict:
        if url.endswith("/readme"):
            raise ParseHttpError("GET readme failed: HTTP 404")
        return dict(GH_REPO_FIXTURE)

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_github._github_get_json",
        _fake_get,
    )
    result = parse_github("https://github.com/psf/requests")
    assert result.content is not None
    assert result.content.title == "psf/requests"
    assert result.content.summary == "A simple, yet elegant, HTTP library."
    # README 可选：失败只少摘要。body 按契约回退为 summary，
    # 但绝不能混入 README 内容。
    assert result.content.body == "A simple, yet elegant, HTTP library."
    assert "Requests allows" not in result.content.body


def test_parse_github_api_failure_raises(monkeypatch) -> None:
    def _boom(url: str) -> dict:
        raise ParseHttpError("GET repo failed: HTTP 403")

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_github._github_get_json",
        _boom,
    )
    with pytest.raises(ParseHttpError):
        parse_github("https://github.com/psf/requests")


def test_parse_github_non_repo_skips_without_network(monkeypatch) -> None:
    calls: list[str] = []

    def _fake_get(url: str) -> dict:
        calls.append(url)
        return dict(GH_REPO_FIXTURE)

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.platforms_github._github_get_json",
        _fake_get,
    )
    with pytest.raises(ParseHttpError):
        parse_github("https://github.com/features/actions")
    assert calls == []  # 非仓库链接不产生任何外呼。


def test_config_field_defaults_documented() -> None:
    # 配置字段名约定（wiring 由编排层完成，这里锁字段拼写）。
    config = SimpleNamespace(
        bot_market_enabled=True,
        bot_market_timeout_seconds=6.0,
        bot_market_cache_seconds=60.0,
    )
    assert config.bot_market_enabled is True
    assert config.bot_market_timeout_seconds == 6.0
    assert config.bot_market_cache_seconds == 60.0
