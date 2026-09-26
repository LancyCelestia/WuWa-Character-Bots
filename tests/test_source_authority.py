"""来源权威分级（domains/core/search/source_authority.py）的回归锁。

第 3 项「科技/时政/新闻/金融要最新最权威来源、二游已有内容要准确反馈」的
机器可执行形态。三条不变量各有一发负样本：
① 权威档只**排序**，绝不放宽相关性地板；② 末段后缀匹配（防抢注伪造一手源）；
③ 未登记域名不丢弃（判据不认识 ≠ 结果不相关）。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.core.search import web_search as ws
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    detect_acg_intent,
)
from plugins.bot_unified_runtime.domains.core.search.source_authority import (
    TIER_AGGREGATOR,
    TIER_FIRST_PARTY,
    TIER_UNKNOWN,
    authority_tier,
    normalize_domain,
)


def _hit(title: str, snippet: str, domain: str) -> ws.WebSearchHit:
    return ws.WebSearchHit(
        title=title, snippet=snippet, url=f"https://{domain}/x", source_domain=domain
    )


def _order(hits: list[ws.WebSearchHit], query: str) -> list[str]:
    return [hit.source_domain for hit in ws.gate_chain_hits(hits, query)]


# ---------------------------------------------------------------------------
# ① 时效四域：一手源排在转载聚合之前
# ---------------------------------------------------------------------------


def test_first_party_outranks_aggregator_for_finance_query() -> None:
    query = "央行 降准 落地 时间"
    farm = _hit(
        "央行 宣布 降准 释放 长期 流动性",
        "央行 决定 于 近日 落地 本次 降准。",
        "baijiahao.baidu.com",
    )
    pbc = _hit(
        "中国人民银行 决定 下调 存款准备金率",
        "央行 公告：降准 于 当日 落地 生效。",
        "pbc.gov.cn",
    )
    assert _order([farm, pbc], query) == ["pbc.gov.cn", "baijiahao.baidu.com"]


def test_exchange_and_regulator_are_first_party_in_any_topic() -> None:
    for domain in ("sse.com.cn", "szse.cn", "csrc.gov.cn", "sec.gov", "federalreserve.gov"):
        assert authority_tier(domain) == TIER_FIRST_PARTY, domain


def test_tech_and_news_first_party_and_major_media_are_distinguished() -> None:
    assert authority_tier("openai.com") == TIER_FIRST_PARTY
    assert authority_tier("arstechnica.com") > TIER_FIRST_PARTY
    assert authority_tier("reuters.com") == TIER_FIRST_PARTY
    assert authority_tier("ithome.com") == TIER_FIRST_PARTY + 1
    assert authority_tier("baijiahao.baidu.com") == TIER_AGGREGATOR


def test_political_query_prefers_government_and_xinhua_over_portal() -> None:
    query = "国务院 政策 发布会 最新 通知"
    portal = _hit(
        "国务院 发布 新 政策 通知 全文",
        "关于 国务院 新 政策 通知 的 转载 说明。",
        "sohu.com",
    )
    gov = _hit(
        "国务院 印发 政策 通知",
        "通知 全文 见 中国政府网。",
        "www.gov.cn",
    )
    assert _order([portal, gov], query) == ["www.gov.cn", "sohu.com"]


# ---------------------------------------------------------------------------
# ② 相关性地板高于权威（权威不许把无关结果抬进块里）
# ---------------------------------------------------------------------------


def test_authority_never_rescues_an_irrelevant_hit() -> None:
    """权威域名 + 对不上问题实体 ⇒ 整块为空，走上层「本轮未检索到」披露。"""
    irrelevant = _hit(
        "某地方台 财经 搬运 节目",
        "内容 与 中国 天气 有关。",
        "sse.com.cn",
    )
    assert _order([irrelevant], "个人所得税 起征点 每月 多少") == []


def test_unknown_domain_is_kept_and_never_dropped() -> None:
    assert authority_tier("some-obscure-forum.example") == TIER_UNKNOWN
    odd = _hit("美联储 维持 利率 不变", "议息 会议 决定 维持 利率。", "odd.example")
    assert _order([odd], "美联储 利率 决议") == ["odd.example"]


def test_suffix_matching_blocks_spoofed_first_party_domains() -> None:
    """"reuters.com 在串里" 不算命中：抢注 fake-reuters.com 不得拿到一手源档。"""
    for spoofed in (
        "fake-reuters.com",
        "reuters.com.evil.cn",
        "notgov.cn.evil.com",
        "xinhuachuanmei.com",
        "openai.com.co",
    ):
        assert authority_tier(spoofed) == TIER_UNKNOWN, spoofed


def test_subdomain_of_first_party_still_counts_as_first_party() -> None:
    assert authority_tier("www.pbc.gov.cn") == TIER_FIRST_PARTY
    assert authority_tier("news.nc.xinhuanet.com") == TIER_FIRST_PARTY


# ---------------------------------------------------------------------------
# ③ 二游/百科话题的抬档，且抬不过一手源
# ---------------------------------------------------------------------------


def test_acg_topic_promotes_encyclopedia_above_vertical() -> None:
    assert authority_tier("moegirl.org.cn", acg_topic=False) > authority_tier(
        "fandom.com", acg_topic=False
    )
    assert authority_tier("moegirl.org.cn", acg_topic=True) < authority_tier(
        "fandom.com", acg_topic=True
    )


def test_promotion_never_outranks_official_game_site() -> None:
    assert authority_tier("moegirl.org.cn", acg_topic=True) > authority_tier(
        "mc.kurogames.com", acg_topic=True
    )


def test_acg_query_is_routed_by_the_existing_predicate() -> None:
    """抬档依据必须是既有 ``detect_acg_intent``，不是本件自带的第二份词表。"""
    assert detect_acg_intent("鸣潮 守岸人 卡池 复刻 时间").is_acg
    assert not detect_acg_intent("美联储 利率 决议").is_acg
    assert (
        authority_tier("moegirl.org.cn", acg_topic=True)
        == authority_tier("caixin.com", acg_topic=True)
    )


# ---------------------------------------------------------------------------
# 形态与确定性
# ---------------------------------------------------------------------------


def test_normalize_domain_accepts_url_shapes_and_case() -> None:
    assert normalize_domain("HTTPS://WWW.Gov.CN:8080/zhengce?x=1") == "www.gov.cn"
    assert normalize_domain("example.com.") == "example.com"
    assert normalize_domain("") == ""
    assert normalize_domain("   ") == ""
    assert authority_tier("") == TIER_UNKNOWN


def test_ordering_is_independent_of_fetch_order() -> None:
    query = "上交所 公告 停牌 复核"
    hits = [
        _hit("上交所 发布 停牌 复核 公告", "交易所 公告：停牌 复核 完成。", "sse.com.cn"),
        _hit("散户 讨论 停牌 复核", "上交所 停牌 复核 的 转载 讨论。", "guba.example"),
    ]
    assert _order(hits, query) == _order(list(reversed(hits)), query) == ["sse.com.cn", "guba.example"]


def test_no_second_encyclopedia_table_survives_in_web_search() -> None:
    """权威档唯一住 source_authority；web_search 里再留一份词表＝第二真身。"""
    assert not hasattr(ws, "_ENCYCLOPEDIA_DOMAIN_FRAGMENTS")
    assert "order_key" in vars(ws)
