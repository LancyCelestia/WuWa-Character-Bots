"""金融三能力路由接线回归（2026-09-13 六域批，全离线）：命中/让路/不误触。

A1 席落地的三能力闭包（bot.commodities/bot.bond/bot.northbound）在本席接线：
- base_router 三条 RouteRule（kind=COMMODITIES/BOND/NORTHBOUND，priority 41，
  声明在 market 之前——同优先级先到先得，商品语境由特异触发词先接住）；
- 商品规则带股语境让路（黄金股行情仍归 market，守卫先例）；
- echo 帮助注册表三 topic（商品行情/国债收益率/北向资金）与路由口径一致。
本文件锁 L2 判定语义；生产 NoneBot matcher 注册在 __init__.py（主会话联动）。
2026-09-14 A34 终审遗留③：三族全拼路由对齐（商品 huangjin/jinjia/baiyin/
youjia/yuanyou；国债 guozhai；北向 beixiang/hugutong/shengutong），双侧
ASCII 词边界 + 基金语境排除同款；弃用词（yinyuan/youtong/hj/by/yj 等）
与胶合边界负例同锁。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.capabilities.echo import HELP_ENTRIES
from plugins.bot_unified_runtime.runtime.base_router import (
    RouteKind,
    classify_message_route,
    clear_route_decision_cache,
)


class _DefaultConfig:
    """路由开关走 base_router 的 getattr 默认值（默认启用语义）。"""


def _route(text: str):
    clear_route_decision_cache()
    return classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)


# ---------- 商品行情：命中 ----------


@pytest.mark.parametrize(
    "text",
    [
        "黄金",
        "今天金价多少",
        "白银价格",
        "原油行情",
        "铜价",
        "大宗商品",
        "油價",
        "gold price",
    ],
)
def test_commodity_samples_hit_route(text: str) -> None:
    decision = _route(text)
    assert decision.kind is RouteKind.COMMODITIES, text
    assert decision.capability_id == "bot.commodities"


# ---------- 商品行情：让路与不误触 ----------


@pytest.mark.parametrize(
    "text",
    [
        "黄金股行情",  # 股语境让位 market（守卫先例，test_market_exclusion_guard）。
        "黄金指数怎么样",  # 指数词 = 股市语境，商品卡让路。
        "金饰价格",  # 无触发词。
        "golden retriever",  # 英文词边界外（gold+en 不闭合）。
    ],
)
def test_commodity_false_positives_stay_away(text: str) -> None:
    assert _route(text).kind is not RouteKind.COMMODITIES, text


def test_gold_stock_market_still_routes_to_market() -> None:
    assert _route("黄金股行情").kind is RouteKind.MARKET


# ---------- 国债收益率：命中 ----------


@pytest.mark.parametrize(
    "text",
    ["国债", "国债收益率", "期限利差", "收益率曲线", "中美国债", "國債"],
)
def test_bond_samples_hit_route(text: str) -> None:
    decision = _route(text)
    assert decision.kind is RouteKind.BOND, text
    assert decision.capability_id == "bot.bond"


@pytest.mark.parametrize("text", ["债券", "公司债收益率", "债市基金怎么买"])
def test_bond_false_positives_stay_away(text: str) -> None:
    assert _route(text).kind is not RouteKind.BOND, text


# ---------- 北向资金：命中 ----------


@pytest.mark.parametrize(
    "text",
    ["北向资金", "北上资金", "沪股通", "深股通", "滬股通"],
)
def test_northbound_samples_hit_route(text: str) -> None:
    decision = _route(text)
    assert decision.kind is RouteKind.NORTHBOUND, text
    assert decision.capability_id == "bot.northbound"


@pytest.mark.parametrize("text", ["港股通", "南向资金", "融资余额多少"])
def test_northbound_false_positives_stay_away(text: str) -> None:
    assert _route(text).kind is not RouteKind.NORTHBOUND, text


# ---------- 全拼路由对齐（2026-09-14 A34 终审遗留③）：命中 ----------


@pytest.mark.parametrize(
    "text",
    [
        "huangjin",  # 黄金
        "jinjia",  # 金价
        "baiyin",  # 白银
        "youjia",  # 油价
        "yuanyou",  # 原油
        "huangjin 多少钱",  # 句式拼音
    ],
)
def test_commodity_pinyin_hits_route(text: str) -> None:
    decision = _route(text)
    assert decision.kind is RouteKind.COMMODITIES, text
    assert decision.capability_id == "bot.commodities"


@pytest.mark.parametrize("text", ["guozhai", "guozhai收益率"])
def test_bond_pinyin_hits_route(text: str) -> None:
    decision = _route(text)
    assert decision.kind is RouteKind.BOND, text
    assert decision.capability_id == "bot.bond"


@pytest.mark.parametrize("text", ["beixiang", "hugutong", "shengutong"])
def test_northbound_pinyin_hits_route(text: str) -> None:
    decision = _route(text)
    assert decision.kind is RouteKind.NORTHBOUND, text
    assert decision.capability_id == "bot.northbound"


# ---------- 全拼路由对齐：边界守卫与弃用词负例 ----------


@pytest.mark.parametrize(
    "text",
    [
        "xhuangjin",  # 左胶合：边界拒。
        "jinjiaxing",  # 右胶合（金家兴类）：边界拒。
        "guozhai123",  # 右邻数字：边界拒。
        "huangjinjijin",  # 胶合「黄金基金」拼音：右边界 + (?!基金) 同拒。
        "yinyuan",  # 姻缘 高频同音：弃用不路由。
        "youtong",  # 幼童 同音：弃用不路由。
        "hj",  # 缩写弃用（滑稽类撞车）。
        "by",  # 缩写弃用（毕业类撞车）。
        "yj",  # 缩写弃用（意见类撞车）。
        "dagutong",  # 无对应触发词：弃用不路由。
    ],
)
def test_finance_pinyin_drop_and_boundary_words_stay_away(text: str) -> None:
    decision = _route(text)
    assert decision.kind not in (
        RouteKind.COMMODITIES,
        RouteKind.BOND,
        RouteKind.NORTHBOUND,
    ), text


@pytest.mark.parametrize(
    "text",
    [
        "金家人真多",  # 中文「金家」人名句：ASCII 拼音正则天然不涉。
        "人情过债真累",  # 中文「过债」：非 guozhai 拼音。
        "黄金基金怎么样",  # (?!基金) 中文排除既有语义。
        "huangjin基金",  # 拼音触发词 + 中文基金排除同款语义。
    ],
)
def test_finance_pinyin_chinese_homophone_stays_away(text: str) -> None:
    decision = _route(text)
    assert decision.kind is not RouteKind.COMMODITIES, text
    assert decision.kind is not RouteKind.BOND, text


def test_gold_pinyin_stock_context_yields_market() -> None:
    """拼音商品词撞股词让位 market（与「黄金股行情」守卫同源语义）。"""
    assert _route("huangjin股行情").kind is RouteKind.MARKET


# ---------- 既有金融路由零回归 ----------


@pytest.mark.parametrize("text", ["行情", "美股行情", "莫斯科股指", "大盘"])
def test_market_commands_unchanged(text: str) -> None:
    assert _route(text).kind is RouteKind.MARKET, text


@pytest.mark.parametrize("text", ["英伟达股价", "股价", "stocks"])
def test_stocks_commands_unchanged(text: str) -> None:
    assert _route(text).kind is RouteKind.STOCKS, text


@pytest.mark.parametrize("text", ["汇率", "美元兑人民币"])
def test_fx_commands_unchanged(text: str) -> None:
    assert _route(text).kind is RouteKind.FX, text


# ---------- 路由与帮助注册表口径一致 ----------


@pytest.mark.parametrize(
    ("topic", "capability_id"),
    [
        ("商品行情", "bot.commodities"),
        ("国债收益率", "bot.bond"),
        ("北向资金", "bot.northbound"),
    ],
)
def test_help_topics_exist_and_match_routes(topic: str, capability_id: str) -> None:
    matches = [entry for entry in HELP_ENTRIES if entry["topic"] == topic]
    assert len(matches) == 1, f"帮助 topic {topic} 出现 {len(matches)} 次"
    entry = matches[0]
    assert entry["admin_only"] is False
    # 逐参数四要素结构：lines 至少一条，detail 带板块/指令/权限/示例段。
    assert entry["lines"] and entry["index"] and entry["title_line"]
    for section in ("【板块介绍】", "【指令与参数】", "【权限与效果】", "【示例】"):
        assert section in str(entry["detail"]), f"{topic} 缺 {section}"
