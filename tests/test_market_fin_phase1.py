"""金融 Phase-1 能力层回归（2026-09-13，全离线）。

锁定 capabilities/market.py 三条新能力（商品/国债/北向）与
capabilities/stocks.py 的 logo 本地缓存：
1. is_*_command 纯谓词：命中/词边界/长度/URL 守卫；
2. 能力闭包：fetch 降级文本、卡 payload sections/rows 契约、诚实脚注；
3. 卡面渲染走 render_finance_card_html（Jinja 离线渲染），
   模板零改动、既有 token 复用（契约门由 test_rendering_contract 锁）；
4. logo 缓存：sha256(域名) 文件名、命中不再下载、非 PNG/失败回退远程。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.finance.capabilities import (
    market as market_cap,
)
from plugins.bot_unified_runtime.domains.finance.capabilities import (
    stocks as stocks_cap,
)
from plugins.bot_unified_runtime.domains.finance.data import (
    bond_data,
    commodities_data,
    market_data,
)
from plugins.bot_unified_runtime.domains.finance.data.bond_data import (
    BondYieldPoint,
    BondYieldSnapshot,
)
from plugins.bot_unified_runtime.domains.finance.data.commodities_data import (
    CommodityQuote,
)
from plugins.bot_unified_runtime.domains.finance.data.market_data import NorthboundFlow

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture()
def _sleeps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    recorded: list[float] = []

    def _record(seconds: float) -> None:
        recorded.append(float(seconds))

    monkeypatch.setattr("time.sleep", _record)
    yield recorded


@pytest.fixture(autouse=True)
def _clean_caches():
    market_data.reset_northbound_cache()
    commodities_data.reset_commodities_cache()
    commodities_data.reset_commodities_trend_cache()
    bond_data.reset_bond_cache()
    yield
    market_data.reset_northbound_cache()
    commodities_data.reset_commodities_cache()
    commodities_data.reset_commodities_trend_cache()
    bond_data.reset_bond_cache()


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        request_id="req-fin-1",
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        plain_text=text,
    )


class _FakeBackend:
    """捕获 HTML 的假渲染后端；available 可控。"""

    available = True

    def __init__(self) -> None:
        self.specs: list[dict] = []

    def render_card(self, spec: dict) -> bytes:
        self.specs.append(spec)
        return b"\x89PNG-fake"


# ---------------------------------------------------------------------------
# 1. 纯谓词
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("黄金", True),
        ("黄金行情", True),
        ("原油多少钱", True),
        ("铜价", True),
        ("大宗商品", True),
        ("gold", True),
        ("crude oil", True),
        ("白银", True),
        ("golden", False),  # 词边界：golden 不命中 gold
        ("看黄金https://x.com", False),  # 带链接是链接解析的活
        ("x" * 40, False),  # 超长文本不触发
    ],
)
def test_is_commodity_command(text: str, expected: bool) -> None:
    assert market_cap.is_commodity_command(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("国债收益率", True),
        ("国债", True),
        ("10年期国债", True),
        ("期限利差", True),
        ("中美国债", True),
        ("收益率曲线", True),
        ("國債", True),
        ("债券基金", False),  # 债券≠国债收益率
        ("看国债https://x.com", False),
    ],
)
def test_is_bond_command(text: str, expected: bool) -> None:
    assert market_cap.is_bond_command(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("北向资金", True),
        ("北上资金", True),
        ("沪股通", True),
        ("深股通", True),
        ("北向資金", True),
        ("南向资金", False),
        ("看北向https://x.com", False),
    ],
)
def test_is_northbound_command(text: str, expected: bool) -> None:
    assert market_cap.is_northbound_command(text) is expected


# ---------------------------------------------------------------------------
# 2. 商品能力：降级文本 + 卡 payload（离线渲染）
# ---------------------------------------------------------------------------


_COMMODITY_QUOTES = [
    CommodityQuote(
        name="COMEX黄金",
        code="101.GC00Y",
        price=4390.0,
        change_pct=-0.39,
        change_abs=-17.3,
        unit="美元/金衡盎司",
        group="贵金属",
    ),
    CommodityQuote(
        name="COMEX铜",
        code="101.HG00Y",
        price=6.557,
        change_pct=0.15,
        change_abs=0.0095,
        unit="美元/磅",
        group="基本金属",
    ),
]


def test_commodities_capability_fetch_failed_text() -> None:
    monkey_quotes = []  # 空 → 降级文本

    def _build():
        orig = commodities_data.fetch_commodity_quotes
        commodities_data.fetch_commodity_quotes = lambda **kw: monkey_quotes  # type: ignore[assignment]
        try:
            return market_cap.build_commodities_capability(config=None, render_backend=None)
        finally:
            commodities_data.fetch_commodity_quotes = orig  # type: ignore[assignment]

    capability = _build()
    result = capability(_message("黄金"), None)
    assert result.kind == "text"
    assert "暂时拉不到" in result.body
    assert "commodities:fetch_failed" in result.audit_tags


def test_commodities_capability_renders_sections_card(tmp_path: Path) -> None:
    def _fake_quotes(**kwargs):
        return list(_COMMODITY_QUOTES)

    def _fake_trend(secid: str, **kwargs):
        return (4400.0, 4390.0) if secid == "101.GC00Y" else ()

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(commodities_data, "fetch_commodity_quotes", _fake_quotes)
        monkeypatch.setattr(commodities_data, "fetch_commodity_trend", _fake_trend)
        config = SimpleNamespace(bot_card_render_dir=str(tmp_path / "cards"))
        backend = _FakeBackend()
        capability = market_cap.build_commodities_capability(
            config, render_backend=backend
        )
        result = capability(_message("黄金"), None)
    finally:
        monkeypatch.undo()
    assert result.kind == "mixed"
    assert result.images and result.images[0]["file"].endswith(".png")
    assert Path(result.images[0]["file"]).read_bytes() == b"\x89PNG-fake"
    html = backend.specs[0]["html"]
    assert "COMEX黄金" in html and "4390.00" in html
    assert "暂无历史走势数据" in html  # 铜无走势 → 文案不伪造折线
    assert "COMEX 主力连续" in html  # LME 替代口径说明


# ---------------------------------------------------------------------------
# 3. 国债能力
# ---------------------------------------------------------------------------


_BOND_SNAPSHOT = BondYieldSnapshot(
    as_of_date="2026-09-11",
    cn=(
        BondYieldPoint("中国国债 2年", 1.2466),
        BondYieldPoint("中国国债 5年", 1.4226),
        BondYieldPoint("中国国债 10年", 1.6899),
        BondYieldPoint("中国国债 30年", 2.146),
    ),
    cn_spread_10y2y=0.4433,
    us=(
        BondYieldPoint("美国国债 2年", 4.63),
        BondYieldPoint("美国国债 5年", 4.78),
        BondYieldPoint("美国国债 10年", 4.96),
        BondYieldPoint("美国国债 30年", 5.35),
    ),
    us_spread_10y2y=0.33,
)


def test_bond_capability_renders_card_and_text(tmp_path: Path) -> None:
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(bond_data, "fetch_bond_yields", lambda **kw: _BOND_SNAPSHOT)
        config = SimpleNamespace(bot_card_render_dir=str(tmp_path / "cards"))
        backend = _FakeBackend()
        capability = market_cap.build_bond_capability(config, render_backend=backend)
        result = capability(_message("国债收益率"), None)
    finally:
        monkeypatch.undo()
    assert result.kind == "mixed"
    assert "1.690%" in result.body and "10Y−2Y" in result.body
    html = backend.specs[0]["html"]
    assert "中国国债（收益率 · 收盘口径）" in html
    assert "1.6899" not in html  # 卡面数值统一三位小数百分比
    assert "10Y−2Y 期限利差" in html and "0.443%" in html
    assert "1 年期暂无稳定免费源" in html  # 1Y 缺口诚实标注


def test_bond_capability_fetch_failed_text() -> None:
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            bond_data,
            "fetch_bond_yields",
            lambda **kw: BondYieldSnapshot(status="unavailable", note="上游失败"),
        )
        capability = market_cap.build_bond_capability(config=None, render_backend=None)
        result = capability(_message("国债"), None)
    finally:
        monkeypatch.undo()
    assert result.kind == "text"
    assert "暂时拉不到" in result.body
    assert "bonds:fetch_failed" in result.audit_tags


# ---------------------------------------------------------------------------
# 4. 北向能力
# ---------------------------------------------------------------------------


_FLOWS = [
    NorthboundFlow(
        name="沪股通",
        mutual_type="001",
        trade_date="2026-09-11",
        deal_amt_yi=1422.5609,
        deal_num=7114374,
        lead_stock="凯盛新能",
        lead_stock_pct=9.99,
        index_name="上证指数",
        index_close=3888.11,
        index_change_pct=-1.18,
    ),
    NorthboundFlow(
        name="深股通",
        mutual_type="003",
        trade_date="2026-09-11",
        deal_amt_yi=1490.6355,
        deal_num=7523378,
        lead_stock="远望谷",
        lead_stock_pct=9.99,
        index_name="深证成指",
        index_close=13471.26,
        index_change_pct=-1.08,
    ),
]


def test_northbound_capability_renders_card_and_text(tmp_path: Path) -> None:
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(market_data, "fetch_northbound_flows", lambda **kw: list(_FLOWS))
        config = SimpleNamespace(bot_card_render_dir=str(tmp_path / "cards"))
        backend = _FakeBackend()
        capability = market_cap.build_northbound_capability(
            config, render_backend=backend
        )
        result = capability(_message("北向资金"), None)
    finally:
        monkeypatch.undo()
    assert result.kind == "mixed"
    assert "1,422.56 亿元" in result.body
    assert "不再披露北向当日净买入" in result.body
    html = backend.specs[0]["html"]
    assert "沪深股通（当日成交）" in html
    assert "1,490.64 亿元" in html
    assert "不含净买入口径" in html  # 卡面诚实脚注


def test_northbound_capability_fetch_failed_text() -> None:
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(market_data, "fetch_northbound_flows", lambda **kw: [])
        capability = market_cap.build_northbound_capability(
            config=None, render_backend=None
        )
        result = capability(_message("北向"), None)
    finally:
        monkeypatch.undo()
    assert result.kind == "text"
    assert "暂时拉不到" in result.body


# ---------------------------------------------------------------------------
# 5. logo 本地缓存（sha256 域名；命中不再下载；失败回退远程）
# ---------------------------------------------------------------------------


@pytest.fixture()
def _logo_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cache_dir = tmp_path / "stock_logos"
    calls: list[str] = []

    def _fake_http_get(url: str, **kwargs: object):
        calls.append(url)
        return url, b"\x89PNG-fake-logo-bytes"

    monkeypatch.setattr(stocks_cap, "_logo_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.link_parse.parsers.http_util.http_get",
        _fake_http_get,
    )
    return SimpleNamespace(cache_dir=cache_dir, calls=calls)


def test_logo_download_then_cache_hit_no_second_download(_logo_env) -> None:
    uri = stocks_cap.local_logo_uri("nvidia.com")
    assert uri.startswith("file://")
    digest = hashlib.sha256(b"nvidia.com").hexdigest()
    path = _logo_env.cache_dir / f"{digest}.png"
    assert path.read_bytes() == b"\x89PNG-fake-logo-bytes"  # 文件名=sha256(域名)
    assert len(_logo_env.calls) == 1
    # 命中缓存：不再下载（calls 不增长）。
    assert stocks_cap.local_logo_uri("nvidia.com") == uri
    assert len(_logo_env.calls) == 1


def test_logo_cache_only_lookup_never_downloads(_logo_env) -> None:
    assert stocks_cap.local_logo_uri("nvidia.com", download=False) == ""
    assert _logo_env.calls == []
    stocks_cap.local_logo_uri("nvidia.com")
    assert stocks_cap.local_logo_uri("nvidia.com", download=False) != ""


def test_logo_non_png_payload_not_cached(_logo_env) -> None:
    from plugins.bot_unified_runtime.domains.link_parse.parsers import http_util

    original = http_util.http_get
    http_util.http_get = lambda url, **kw: (url, b"<html>404</html>")  # type: ignore[assignment]
    try:
        assert stocks_cap.local_logo_uri("bad.example") == ""
    finally:
        http_util.http_get = original  # type: ignore[assignment]
    assert not _logo_env.cache_dir.exists() or not list(_logo_env.cache_dir.iterdir())


def test_logo_download_failure_returns_empty(_logo_env) -> None:
    from plugins.bot_unified_runtime.domains.link_parse.parsers import http_util

    def _boom(url: str, **kwargs: object):
        raise http_util.ParseHttpError("GET failed: RemoteDisconnected")

    original = http_util.http_get
    http_util.http_get = _boom  # type: ignore[assignment]
    try:
        assert stocks_cap.local_logo_uri("down.example") == ""
    finally:
        http_util.http_get = original  # type: ignore[assignment]


def test_apply_cached_logo_swaps_and_falls_back(_logo_env, monkeypatch) -> None:
    payload = {"logo_url": "https://logo.clearbit.com/nvidia.com"}
    stocks_cap._apply_cached_logo(payload)
    assert payload["logo_url"].startswith("file://")  # 已换本地

    monkeypatch.setattr(stocks_cap, "local_logo_uri", lambda domain, **kw: "")
    payload2 = {"logo_url": "https://logo.clearbit.com/nvidia.com"}
    stocks_cap._apply_cached_logo(payload2)
    assert payload2["logo_url"] == "https://logo.clearbit.com/nvidia.com"  # 回退远程

    payload3 = {"logo_url": "https://other.example/logo.png"}
    stocks_cap._apply_cached_logo(payload3)
    assert payload3["logo_url"] == "https://other.example/logo.png"  # 非 clearbit 不动


def test_render_card_applies_cached_logo(tmp_path: Path) -> None:
    """个股能力渲染前把 clearbit 远程 URL 换成本地缓存 URI（行为面验证）。

    说明：finance_card 模板当前没有 logo 槽位（payload["logo_url"] 是既有
    休眠契约），本测试锁定的是缓存替换发生在渲染前、缓存命中不再下载。
    """
    from plugins.bot_unified_runtime.domains.core.contracts.finance import (
        EquityQuote,
        FinanceDataStatus,
    )

    seen: dict = {}
    download_calls: list[str] = []
    orig_apply = stocks_cap._apply_cached_logo

    def _spy(payload: dict) -> None:
        orig_apply(payload)
        seen["logo_url"] = payload.get("logo_url")

    quote = EquityQuote(
        ticker="NVDA",
        name="英伟达",
        exchange="NASDAQ",
        currency="USD",
        price=218.29,
        change_pct=-0.03,
        source="eastmoney",
        as_of=None,
        status=FinanceDataStatus.OK,
        delayed=True,
    )
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(stocks_cap, "fetch_stock_quote", lambda ticker, **kw: quote)
        monkeypatch.setattr(
            stocks_cap, "fetch_stock_ohlcv", lambda ticker, **kw: None
        )
        monkeypatch.setattr(
            stocks_cap, "fetch_market_cap", lambda ticker, **kw: None
        )
        monkeypatch.setattr(
            stocks_cap, "_logo_cache_dir", lambda: tmp_path / "logos"
        )
        monkeypatch.setattr(stocks_cap, "_apply_cached_logo", _spy)
        from plugins.bot_unified_runtime.domains.link_parse.parsers import http_util

        original = http_util.http_get

        def _fake_get(url: str, **kwargs: object):
            download_calls.append(url)
            return url, b"\x89PNG-cached"

        http_util.http_get = _fake_get  # type: ignore[assignment]
        try:
            capability = stocks_cap.build_stocks_capability(
                SimpleNamespace(bot_card_render_dir=str(tmp_path / "cards")),
                render_backend=_FakeBackend(),  # 出图路径才经过 _render_card
            )
            result = capability(_message("英伟达股价"), None)
        finally:
            http_util.http_get = original  # type: ignore[assignment]
    finally:
        monkeypatch.undo()
    assert result.kind == "mixed"  # 走完整渲染路径
    assert seen["logo_url"].startswith("file://")  # 渲染前已换本地缓存 URI
    assert "https://logo.clearbit.com/nvidia.com" in download_calls  # 首次出网下载
    assert seen["logo_url"] == (tmp_path / "logos").joinpath(
        hashlib.sha256(b"nvidia.com").hexdigest()
    ).with_suffix(".png").as_uri()  # 文件名 = sha256(域名)
    # 二次调用命中缓存：不再下载。
    stocks_cap.local_logo_uri("nvidia.com")
    assert len(download_calls) == 1


# ---------------------------------------------------------------------------
# 6. F2 logo 三级解析（2026-09-14 素材本地化）：payload 组装侧只落本地
#    file URI——缓存命中零网络；clearbit 失败落 Google s2 并入缓存；
#    两源全败诚实省略 logo 字段；预热入口幂等、失败列清单不阻塞。
# ---------------------------------------------------------------------------


def _nvda_quote():
    from plugins.bot_unified_runtime.domains.core.contracts.finance import (
        EquityQuote,
        FinanceDataStatus,
    )

    return EquityQuote(
        ticker="NVDA",
        name="英伟达",
        exchange="NASDAQ",
        currency="USD",
        price=184.95,
        change_pct=-0.38,
        change_abs=-0.71,
        source="eastmoney",
        as_of=None,
        status=FinanceDataStatus.OK,
        delayed=True,
    )


_NVDA_REF = SimpleNamespace(logo_domain="nvidia.com", brand_color="")


def test_payload_logo_cache_hit_zero_network(monkeypatch, tmp_path: Path) -> None:
    """缓存命中：payload 直接拿本地 file URI，组装期零网络。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers import http_util

    cache_dir = tmp_path / "logos"
    cache_dir.mkdir()
    digest = hashlib.sha256(b"nvidia.com").hexdigest()
    (cache_dir / f"{digest}.png").write_bytes(b"\x89PNG-cached")

    calls: list[str] = []

    def _must_not_download(url: str, **kwargs: object):
        calls.append(url)
        return url, b"\x89PNG-x"

    monkeypatch.setattr(stocks_cap, "_logo_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(http_util, "http_get", _must_not_download)

    payload = stocks_cap.build_stocks_card_payload(
        _nvda_quote(), None, None, None, ref=_NVDA_REF
    )
    assert payload["logo_url"] == (cache_dir / f"{digest}.png").as_uri()
    assert calls == []  # 缓存命中零网络


def test_payload_logo_clearbit_fail_falls_to_s2_and_caches(
    monkeypatch, tmp_path: Path
) -> None:
    """clearbit 死源（URLError）→ Google s2 补缓存 → 卡片拿本地 file URI。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers import http_util

    cache_dir = tmp_path / "logos"
    calls: list[str] = []

    def _clearbit_dead_s2_alive(url: str, **kwargs: object):
        calls.append(url)
        if "logo.clearbit.com" in url:
            raise http_util.ParseHttpError("clearbit unreachable (URLError)")
        return url, b"\x89PNG-from-s2"

    monkeypatch.setattr(stocks_cap, "_logo_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(http_util, "http_get", _clearbit_dead_s2_alive)

    payload = stocks_cap.build_stocks_card_payload(
        _nvda_quote(), None, None, None, ref=_NVDA_REF
    )
    digest = hashlib.sha256(b"nvidia.com").hexdigest()
    assert calls[0].startswith("https://logo.clearbit.com/")  # 先试 clearbit
    assert "s2/favicons" in calls[1]  # 失败落 Google s2
    assert (cache_dir / f"{digest}.png").read_bytes() == b"\x89PNG-from-s2"
    assert payload["logo_url"] == (cache_dir / f"{digest}.png").as_uri()
    assert payload["logo_url"].startswith("file://")  # 死源 URL 绝不进 payload


def test_payload_logo_all_sources_fail_omits_logo_field(
    monkeypatch, tmp_path: Path
) -> None:
    """两源全败：诚实降级不设 logo 字段（卡片不出死链），主链路不受影响。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers import http_util

    def _all_dead(url: str, **kwargs: object):
        raise http_util.ParseHttpError("all logo sources unreachable")

    monkeypatch.setattr(stocks_cap, "_logo_cache_dir", lambda: tmp_path / "logos")
    monkeypatch.setattr(http_util, "http_get", _all_dead)

    payload = stocks_cap.build_stocks_card_payload(
        _nvda_quote(), None, None, None, ref=_NVDA_REF
    )
    assert "logo_url" not in payload  # 无 logo 字段，绝无 clearbit 死链
    assert payload["title"].startswith("英伟达")  # 行情主链路照常
    cache_dir = tmp_path / "logos"
    assert not cache_dir.exists() or not list(cache_dir.iterdir())  # 不缓存坏字节


def test_warm_logo_cache_idempotent_and_reports_failures(
    monkeypatch, tmp_path: Path
) -> None:
    """预热幂等：命中跳过零网络；失败域名列清单不阻塞，下轮只补失败者。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers import http_util

    cache_dir = tmp_path / "logos"
    calls: list[str] = []

    def _fake_get(url: str, **kwargs: object):
        calls.append(url)
        if "bad.example" in url:
            raise http_util.ParseHttpError("dead domain")
        return url, b"\x89PNG-ok"

    monkeypatch.setattr(stocks_cap, "_logo_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(http_util, "http_get", _fake_get)

    assert stocks_cap.warm_logo_cache(["good.example", "bad.example"]) == [
        "bad.example"
    ]
    assert len(calls) == 3  # good 走 clearbit 即中；bad 两源全试
    # 幂等二轮：good 命中缓存零网络，只补 bad。
    assert stocks_cap.warm_logo_cache(["good.example", "bad.example"]) == [
        "bad.example"
    ]
    assert len(calls) == 5


def test_warm_logo_cache_default_domains_from_registry(
    monkeypatch, tmp_path: Path
) -> None:
    """缺省域名集=上市公司注册表全量（去重排序，空域名跳过）。"""
    from plugins.bot_unified_runtime.domains.finance.data import stock_data

    monkeypatch.setattr(stocks_cap, "_logo_cache_dir", lambda: tmp_path / "logos")
    monkeypatch.setattr(
        stock_data,
        "list_listed_companies",
        lambda: (
            SimpleNamespace(logo_domain="b.example"),
            SimpleNamespace(logo_domain="a.example"),
            SimpleNamespace(logo_domain=""),  # 空域名跳过
        ),
    )
    seen: list[str] = []

    def _fake_get(url: str, **kwargs: object):
        seen.append(url)
        return url, b"\x89PNG-ok"

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.link_parse.parsers.http_util.http_get", _fake_get
    )
    assert stocks_cap.warm_logo_cache() == []
    assert sorted(
        url.rsplit("/", 1)[-1] for url in seen if "logo.clearbit.com" in url
    ) == ["a.example", "b.example"]
