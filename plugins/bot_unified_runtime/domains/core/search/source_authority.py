"""检索结果的来源权威分级（「最新、最权威来源」这条要求的判据真身）。

为什么单开一件：``web_search._domain_priority`` 此前只认识百科域名，科技/时政/
新闻/金融四类题里一手源（监管机构、交易所、通讯社、厂商官方发布）与内容农场
同权，模型先读到的就是抓取顺序里碰巧靠前的那一条。本件只回答「哪个域名更该
先看」，**不参与相关性判定**——相关性地板仍唯一住在
``web_search._filter_relevant``，权威永远不许把不相关的结果抬进块里。

为什么不按话题各建一棵词表：话题判定的真身已在
``domains/chat_reply/runtime/question_intent.py``（时效四域）与本包
``search_intent.py``（二次元域）。在 core 层再抄一份正则＝第二真身，两份必然
漂移。所以这里只做**跨话题成立**的通用阶梯（一手源在任何话题下都是一手源），
二次元/百科话题额外把百科域抬到 tier 1——抬的依据直接调用既有谓词
``detect_acg_intent``，不新建词表。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    detect_acg_intent,
)

__all__ = [
    "TIER_AGGREGATOR",
    "TIER_FIRST_PARTY",
    "TIER_UNKNOWN",
    "authority_tier",
    "normalize_domain",
    "order_key",
]

# 数值越小越该先看。TIER_UNKNOWN 不是低质，只是「本件不认识」——绝不因不认识而丢弃。
TIER_FIRST_PARTY = 0  # 官方/监管/交易所/通讯社/厂商一手发布
TIER_MAJOR_MEDIA = 1  # 主流权威媒体（有采编与更正机制）
TIER_VERTICAL = 2  # 垂类可信（垂直数据站、官方社区、番剧资料站）
TIER_NEUTRAL = 3  # 通用百科（旧实现唯一认识的一档）
TIER_UNKNOWN = 4  # 未登记域名
TIER_AGGREGATOR = 5  # 明确的转载/聚合形态（不是垃圾，但不配占前排）

_FIRST_PARTY: tuple[str, ...] = (
    # 中国政务与监管
    "gov.cn",
    "xinhua.cn",
    "xinhuanet.com",
    "news.cn",
    "people.com.cn",
    "cctv.com",
    "chinacourt.org",
    # 金融基础设施与监管
    "sse.com.cn",
    "szse.cn",
    "cffex.com.cn",
    "shfe.com.cn",
    "dce.com.cn",
    "czce.com.cn",
    "chinabond.com.cn",
    "cninfo.com.cn",
    "sec.gov",
    "federalreserve.gov",
    "ecb.europa.eu",
    "imf.org",
    "worldbank.org",
    "opec.org",
    "eia.gov",
    # 国际通讯社
    "reuters.com",
    "apnews.com",
    "afp.com",
    # 科技一手发布
    "openai.com",
    "anthropic.com",
    "deepmind.google",
    "blog.google",
    "microsoft.com",
    "apple.com",
    "nvidia.com",
    "intel.com",
    "amd.com",
    "kernel.org",
    "arxiv.org",
    "github.blog",
    "huggingface.co",
    # 二游官方站（版本/卡池/公告的真相只在这里）
    "mihoyo.com",
    "hoyoverse.com",
    "hypgis.com",
    "kurogames.com",
    "biligame.com",
)

_MAJOR_MEDIA: tuple[str, ...] = (
    "thepaper.cn",
    "chinanews.com.cn",
    "chinanews.com",
    "caixin.com",
    "yicai.com",
    "stcn.com",
    "21jingji.com",
    "nbd.com.cn",
    "bloomberg.com",
    "ftchinese.com",
    "ft.com",
    "wsj.com",
    "nytimes.com",
    "bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "theverge.com",
    "arstechnica.com",
    "techcrunch.com",
    "engadget.com",
    "jiqizhixin.com",
    "qbitai.com",
    "infoq.cn",
    "ithome.com",
    "nature.com",
    "newscientist.com",
)

_VERTICAL: tuple[str, ...] = (
    "eastmoney.com",
    "wallstreetcn.com",
    "cls.cn",
    "globaltimes.cn",
    "36kr.com",
    "sspai.com",
    "v2ex.com",
    "oschina.net",
    "bgm.tv",
    "bangumi.tv",
    "fandom.com",
    "kurobbs.com",
    "bilibili.com",
)

_NEUTRAL: tuple[str, ...] = (
    "moegirl.org.cn",
    "moegirl.icu",
    "wikipedia.org",
    "baike.baidu.com",
    "britannica.com",
)

# 明确的转载/聚合形态。**故意只登记少数几枚**：误降权（把权威站打成聚合）比漏
# 降权坏得多——前者让模型看不到一手源，后者只是维持现状。
_AGGREGATOR: tuple[str, ...] = (
    "baijiahao.baidu.com",
    "mbd.baidu.com",
    "360kuai.com",
    "ixigua.com",
    "toutiao.com",
    "sohu.com",
)

_TIERS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (TIER_FIRST_PARTY, _FIRST_PARTY),
    (TIER_MAJOR_MEDIA, _MAJOR_MEDIA),
    (TIER_VERTICAL, _VERTICAL),
    (TIER_NEUTRAL, _NEUTRAL),
    (TIER_AGGREGATOR, _AGGREGATOR),
)


def normalize_domain(value: str) -> str:
    """把 ``https://X:8080/p``、``X.``、大小写混写统一成可比较的裸域名。"""
    domain = (value or "").strip().lower()
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    domain = domain.split("/", 1)[0].split("?", 1)[0]
    return domain.split(":", 1)[0].strip(".")


def _matches(domain: str, registered: str) -> bool:
    """整段相等或作为末段后缀命中。

    刻意不做任意子串匹配：一旦 ``fake-reuters.com`` 能被 ``reuters.com`` 命中，
    「抬升权威」就成了可抢注伪造的通道。
    """
    return domain == registered or domain.endswith("." + registered)


def authority_tier(source_domain: str, *, acg_topic: bool = False) -> int:
    """该来源域名的权威档（越小越该先看）；未登记一律 TIER_UNKNOWN，不丢弃。"""
    domain = normalize_domain(source_domain)
    if not domain:
        return TIER_UNKNOWN
    for tier, registered in _TIERS:
        if any(_matches(domain, item) for item in registered):
            # 百科域是 lore 题的正解来源，抬到与主流媒体同档；但不越过一手源。
            if acg_topic and tier == TIER_NEUTRAL:
                return TIER_MAJOR_MEDIA
            return tier
    return TIER_UNKNOWN


def order_key(source_domain: str, query: str = "") -> tuple[int, str]:
    """排序键，供 ``sorted`` 直接用；同档内按域名稳定排序，保证确定性可测。"""
    domain = normalize_domain(source_domain)
    return (
        authority_tier(domain, acg_topic=bool(detect_acg_intent(query or "").is_acg)),
        domain,
    )
