"""B 站商品（会员购 / 魔力赏市集）解析回归测试。

全部不访问网络：monkeypatch 商品模块内的 ``http_post_json`` 与 ``_og_scrape``，
用固定响应验证 字段映射 / 翻页匹配 / og 兜底 / 浅层降级 / 注册表规则。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.sources.parsers import (
    build_content_parser_registry,
    build_source_input,
)
from plugins.bot_unified_runtime.sources.parsers import (
    platforms_bilibili_goods as goods,
)
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError
from plugins.bot_unified_runtime.sources.parsers.types import PlatformParse

MARKET_URL = (
    "https://mall.bilibili.com/neul-next/index.html"
    "?page=magic-market_detail&noTitleBar=1&itemsId=5201314"
)
SHOW_URL = "https://show.bilibili.com/platform/detail.html?id=8888"
MALL_HOME_URL = "https://www.bilibili.com/h5/mall/home"


def _list_item(**overrides):
    item = {
        "c2cItemsId": 5201314,
        "c2cItemsName": "初音未来 手办 景品",
        "showPrice": 299.5,
        "showMarketPrice": 499.0,
        "price": 29950,
        "uid": 123,
        "uname": "卖家小明",
        "uface": "https://i0.hdslb.com/face.jpg",
        "detailDtoList": [
            {
                "name": "初音未来 手办 景品",
                "img": "https://i0.hdslb.com/goods.jpg",
                "marketPrice": 499.0,
                "itemsId": 5201314,
            }
        ],
    }
    item.update(overrides)
    return item


def test_extract_items_id_from_query():
    assert goods._extract_items_id(MARKET_URL) == "5201314"
    assert goods._extract_items_id(SHOW_URL) == "8888"
    assert goods._extract_items_id("https://mall.bilibili.com/x") == ""


def test_c2c_deep_parse_maps_fields(monkeypatch):
    captured: list = []

    def fake_post_json(url, payload, **kwargs):
        captured.append((url, payload, kwargs.get("cookie", "")))
        return {"code": 0, "data": {"data": [_list_item()], "nextId": None}}

    monkeypatch.setattr(goods, "http_post_json", fake_post_json)

    result = goods.parse_bilibili_goods(MARKET_URL, cookie_header="SESSDATA=x")

    assert isinstance(result, PlatformParse)
    assert result.platform == "bilibili"
    assert result.item_id == "5201314"
    assert result.item_kind == "goods"
    assert result.page_type == "goods"
    assert result.badge == "商品"
    assert result.parse_depth == "deep"
    assert result.title == "初音未来 手办 景品"
    assert result.author_name == "卖家小明"
    assert result.cover_url == "https://i0.hdslb.com/goods.jpg"
    assert result.stats["价格"] == "¥299.5"
    assert result.stats["原价"] == "¥499.0"
    assert result.stats["卖家"] == "卖家小明"
    assert result.detail["goods"]["price"] == 299.5
    assert result.detail["goods"]["cover"].startswith("https://i0.hdslb.com")

    url, payload, cookie = captured[0]
    assert url == goods._C2C_LIST_API
    assert payload["sortType"] == "TIME_DESC"
    assert payload["priceFilters"] == ["0-100000001"]
    assert payload["discountFilters"] == ["0-101"]
    assert payload["nextId"] is None
    assert cookie == "SESSDATA=x"


def test_c2c_paginates_until_match(monkeypatch):
    pages = [
        {"code": 0, "data": {"data": [_list_item(c2cItemsId=1)], "nextId": "page2"}},
        {
            "code": 0,
            "data": {
                "data": [_list_item(c2cItemsId=2), _list_item()],
                "nextId": None,
            },
        },
    ]
    calls: list = []
    state = {"index": 0}

    def fake_post_json(url, payload, **kwargs):
        calls.append(payload["nextId"])
        page = pages[state["index"]]
        state["index"] += 1
        return page

    monkeypatch.setattr(goods, "http_post_json", fake_post_json)

    result = goods.parse_bilibili_goods(MARKET_URL, cookie_header="SESSDATA=x")

    assert result.item_id == "5201314"
    assert calls == [None, "page2"]
    assert result.title == "初音未来 手办 景品"


def test_og_fallback_when_item_not_in_list(monkeypatch):
    monkeypatch.setattr(
        goods,
        "http_post_json",
        lambda url, payload, **kwargs: {
            "code": 0,
            "data": {"data": [_list_item(c2cItemsId=1)], "nextId": None},
        },
    )
    shallow = PlatformParse(
        platform="bilibili",
        item_id="",
        item_kind="goods",
        title="商品标题",
        cover_url="https://cover.jpg",
        parse_depth="shallow",
    )
    monkeypatch.setattr(goods, "_og_scrape", lambda *a, **k: shallow)

    result = goods.parse_bilibili_goods(MARKET_URL, cookie_header="SESSDATA=x")

    assert result.item_id == "5201314"
    assert result.page_type == "goods"
    assert result.badge == "商品"
    assert result.detail["goods"]["title"] == "商品标题"
    assert result.parse_depth == "shallow"


def test_degraded_result_when_all_fail(monkeypatch):
    def fail_post(*a, **k):
        raise ParseHttpError("blocked")

    def fail_og(*a, **k):
        raise ParseHttpError("no title")

    monkeypatch.setattr(goods, "http_post_json", fail_post)
    monkeypatch.setattr(goods, "_og_scrape", fail_og)

    result = goods.parse_bilibili_goods(MARKET_URL, cookie_header="SESSDATA=x")

    assert result.platform == "bilibili"
    assert result.item_kind == "goods"
    assert result.page_type == "goods"
    assert result.badge == "商品"
    assert result.parse_depth == "shallow"
    assert result.item_id == "5201314"
    assert "5201314" in result.title


def test_degraded_result_has_no_network_for_non_id_url(monkeypatch):
    monkeypatch.setattr(
        goods,
        "http_post_json",
        lambda *a, **k: (_ for _ in ()).throw(ParseHttpError("nope")),
    )
    monkeypatch.setattr(
        goods,
        "_og_scrape",
        lambda *a, **k: (_ for _ in ()).throw(ParseHttpError("nope")),
    )

    result = goods.parse_bilibili_goods(MALL_HOME_URL)

    assert result.title == "B站商品"
    assert result.item_id == ""
    assert result.parse_depth == "shallow"


def test_registry_matches_goods_urls():
    built = build_content_parser_registry(enabled_platforms=["bilibili_goods"])
    registry = built["registry"]

    for url in (MARKET_URL, SHOW_URL, MALL_HOME_URL):
        matches = registry.match(build_source_input(url))
        assert [match.parser_id for match in matches] == ["bilibili_goods"], url
