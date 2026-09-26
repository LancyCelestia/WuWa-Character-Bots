"""中文时效查询检索质量回归锁（席 S-T-SEARCHQ-1，2026-09-26）。

锁的是**判据**，不是某一次实跑：本文件全部用例离线、夹具手写、零网络（末尾有
一条自证）。真实联网测量在席报告
`.superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-SEARCHQ-1.md` §3（探针与抓包件
留在 %TEMP%，不是交付物）；夹具的标题/摘要/域名形态照抓包实样手抄。

四种实测形态各有一组锁：

* **F1 召回**——实体嵌在不带空格的中文整串里，旧判据要 8-13 字原样出现在标题中，
  于是又新又对的议息报道被整批判空；
* **F2 精度**——年份与「最新/消息/官方」这类由 `chat.py` 追加的装饰被当实体证据，
  「中国地图」因此进了「个人所得税起征点」的结果块；
* **F3 诚实判空**——上游真给垃圾（翻译农场答收入、黄历站答金价）时必须整批为空；
* **F4 在册限制**——词形不对齐（综指 vs 指数）今天仍判空，本文件把**现状**钉住，
  放宽的落点在查询构造侧（冻结件 `chat.py`），不在本席面上动地板。

外加本波新长的两条判据自身：时效信号 `search_intent.detect_query_recency`，
以及「带日期的先给模型看、但时效永不越过权威档、权威永不越过地板」这条排序不变量。
"""

from __future__ import annotations

import logging
import socket

import pytest

from plugins.bot_unified_runtime.domains.core.search import web_search as ws
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    detect_query_recency,
)
from plugins.bot_unified_runtime.domains.core.search.source_authority import (
    TIER_FIRST_PARTY,
    TIER_UNKNOWN,
)

# --------------------------------------------------------------------------- #
# 夹具（离线：形态抄自实弹抓包，内容手写）
# --------------------------------------------------------------------------- #


def _hit(title: str, snippet: str, url: str, domain: str) -> ws.WebSearchHit:
    return ws.WebSearchHit(title=title, snippet=snippet, url=url, source_domain=domain)


# F1：问句「美联储最新利率决议」不带空格，这三条都是**正解**（旧闸门 0 保留）。
_CLS_FED = _hit(
    "美联储动态 - CLS.CN",
    "1 天前 · 【花旗：预计美联储将于10月、12月维持利率不变 2027年6月恢复降息】财联社9月24日电",
    "https://www.cls.cn/subject/1350",
    "www.cls.cn",
)
_CCTV_FED = _hit(
    "财经老王 | 美联储加息影响多国，对我们有何影响？一文讲清",
    "2026年9月17日 · 美联储三年多来首次加息，为什么？对我们又有哪些影响？",
    "https://news.cctv.com/2026/09/17/fed",
    "news.cctv.com",
)
_XINHUA_FED = _hit(
    "美联储三年多来首次加息-新华网",
    "2026年9月18日 · 美联储货币政策转向的观察与解读。",
    "https://www3.xinhuanet.com/20260918/fed",
    "www3.xinhuanet.com",
)
# F2：实测**确实进过块**的垃圾（问句本是「个人所得税起征点」）。
_MAP_JUNK = _hit(
    "中国地图 - 卫星地图、实景全图 - 八九网",
    "这是中国地图网页，提供中国卫星地图2026高清版大图，包括可以看到城市、村庄的房子。",
    "https://www.bajiu.cn/ditu/zhongguo",
    "bajiu.cn",
)
_PRC_JUNK = _hit(
    "中华人民共和国_百度百科",
    "中华人民共和国（the People's Republic of China），简称“中国”，成立于1949年10月1日。",
    "https://baike.baidu.com/item/中华人民共和国",
    "baike.baidu.com",
)
# 正解两条（同题、实体齐备）
_TAX_GOOD = _hit(
    "个人所得税减除费用标准维持每月5000元",
    "国家税务总局公告：居民综合所得基本减除费用（起征点）为每月 5000 元。",
    "https://www.chinatax.gov.cn/chengbenkouchu",
    "chinatax.gov.cn",
)
_TAX_GOOD2 = _hit(
    "个人所得税专项附加扣除细则",
    "起征点（基本减除费用）每月 5000 元，子女教育等专项附加扣除另计。",
    "https://www.gov.cn/zhengce/202609/geshui.htm",
    "www.gov.cn",
)
# F3：真垃圾批次（翻译农场答「人均可支配收入」、黄历站答「黄金价格多少钱一克」）。
_TRANS_JUNK = _hit(
    "百度翻译_领先的AI大模型翻译_支持文本/文档/图片翻译",
    "全球最大的中文搜索引擎、致力于让网民更便捷地获取信息。",
    "https://fanyi.baidu.com/",
    "fanyi.baidu.com",
)
_ALMANAC_JUNK = _hit(
    "今日黄历宜忌查询,今日老黄历,今天是什么日子老黄历_天天黄历",
    "17 小时之前 · 今天是什么日子 今天黄历值神是勾陈，是黑道日 今天是2026年的 267 天。",
    "https://m.tthuangli.com/jinrihuangli/",
    "m.tthuangli.com",
)


def _domains(hits: list[ws.WebSearchHit]) -> list[str]:
    return [hit.source_domain for hit in hits]


# 别名那一组用的夹具：形态抄自 88 条真实抓包（席 S-T-SEARCHQ-2 §4 手工标注为正解/次解）
_INDEX_QUOTE = _hit(
    "上证指数 (000001)_股票行情_走势图—东方财富网",
    "提供上证指数(000001)的行情走势、资金流向、行业概念板块排行。",
    "https://quote.eastmoney.com/ZS000001.html",
    "quote.eastmoney.com",
)
_SSE_HOME = _hit(
    "首页 | 上海证券交易所",
    "2026年9月17日 · 上证系列指数 中证系列指数 中华系列指数 产品 股票与存托凭证。",
    "https://www.sse.com.cn/",
    "www.sse.com.cn",
)
_GOV_RRR = _hit(
    "中国人民银行决定下调金融机构存款准备金率",
    "2026年9月20日 · 为保持流动性合理充裕，中国人民银行下调存款准备金率 0.5 个百分点。",
    "https://www.gov.cn/zhengce/202609/rrr.htm",
    "www.gov.cn",
)
_BLOG_RRR = _hit(
    "降准落地解读",
    "某个人博客：本次降准已于当日落地，银行体系流动性趋于宽裕。",
    "https://blog.example.com/chaozhun",
    "blog.example.com",
)
_DICTIONARY_OFF_TOPIC = _hit(
    "起的解释",
    "汉语汉字字典：起的拼音、笔顺、部首。",
    "https://zdic.net/hans/起",
    "zdic.net",
)


# --------------------------------------------------------------------------- #
# ① F1 召回：中文连串里的实体必须算证据
# --------------------------------------------------------------------------- #


def test_entity_inside_an_undivided_chinese_run_is_recalled() -> None:
    """整串问句不出现在任何真实标题里，三条议息报道仍必须留下。"""
    kept = ws.gate_chain_hits([_CLS_FED, _CCTV_FED, _XINHUA_FED], "美联储最新利率决议")
    assert _domains(kept) == ["news.cctv.com", "www3.xinhuanet.com", "www.cls.cn"]
    # 顺序由权威档决定、与抓取顺序无关（同档再按域名稳定排）。
    assert ws.gate_chain_hits(
        [_CLS_FED, _XINHUA_FED, _CCTV_FED], "美联储最新利率决议"
    ) == kept


def test_run_is_segmented_on_scaffolding_before_grams() -> None:
    """三元组是**召回手段**不是放宽：先看段是怎么剥出来的。"""
    strong, weak = ws._token_evidence_forms("中国个人所得税起征点是多少")
    assert "中国个人所得税起征点" in strong  # 剥掉「是多少」之后的整段
    assert {"个人所", "人所得", "所得税", "起征点"} <= set(strong)
    assert "多少" not in strong and "多少" not in weak
    assert weak == ()  # 「中国」这类 2 字串埋在长段里，不单独成为弱形态


def test_year_and_recency_decoration_never_count_as_entities() -> None:
    """F2 的根：装饰与年份由 chat.py 追加、几乎每页都含，不得充当证据。"""
    forms = ws._query_entity_forms("中国个人所得税起征点是多少 2026 最新 消息 官方 发布")
    assert [token for token, _ in forms] == ["中国个人所得税起征点是多少"]
    assert ws.gate_chain_hits(
        [_MAP_JUNK], "中国个人所得税起征点是多少 2026 最新 消息"
    ) == []
    assert ws.gate_chain_hits([_PRC_JUNK], "中国个人所得税起征点是多少 2026") == []


def test_two_char_geopolitical_token_alone_still_fails_the_floor() -> None:
    """反向锁：只靠「中国」两字对上的页面，问句拆得再细也不算相关。"""
    query = "中国 个人所得税 起征点 每月多少"
    assert ws.gate_chain_hits([_MAP_JUNK, _PRC_JUNK], query) == []
    assert ws.gate_chain_hits([_MAP_JUNK, _PRC_JUNK, _TAX_GOOD], query) == [_TAX_GOOD]


# --------------------------------------------------------------------------- #
# ② 地板：该全留的一条不丢；该空的整批空；且**计数看得见**
# --------------------------------------------------------------------------- #


def test_floor_keeps_every_hit_of_a_clean_query() -> None:
    """两条都实体齐备 ⇒ 一条不丢（地板量的是相关性，不是数量）。"""
    kept = ws.gate_chain_hits([_TAX_GOOD, _TAX_GOOD2], "个人所得税 起征点 每月")
    assert len(kept) == 2


def test_floor_drops_junk_and_logs_the_count(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=ws.__name__):
        kept = ws.gate_chain_hits(
            [_TAX_GOOD, _MAP_JUNK, _PRC_JUNK, _TRANS_JUNK],
            "个人所得税 起征点 每月 多少",
        )
    assert kept == [_TAX_GOOD]
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "relevance gate" in joined
    assert "entities=3" in joined and "floor=3" in joined
    assert "kept=1" in joined and "dropped_by_floor=3" in joined


def test_whole_batch_drop_is_also_counted(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=ws.__name__):
        assert (
            ws.gate_chain_hits([_MAP_JUNK, _PRC_JUNK], "个人所得税 起征点 每月 多少") == []
        )
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "kept=0" in joined and "dropped_by_floor=2" in joined


def test_junk_domain_drop_is_counted_separately(caplog) -> None:
    """字典站那一层（`_is_junk`）与地板那一层分开计数，别互相顶包。"""
    dictionary = _hit(
        "起的解释",
        "汉语汉字字典：起的拼音、笔顺、部首。",
        "https://zdic.net/hans/起",
        "zdic.net",
    )
    with caplog.at_level(logging.INFO, logger=ws.__name__):
        assert ws.gate_chain_hits([dictionary, _TAX_GOOD], "个人所得税 起征点 每月 多少") == [
            _TAX_GOOD
        ]
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "dropped_as_junk=1" in joined and "dropped_by_floor=1" in joined


def test_gate_is_idempotent_under_the_new_evidence_rule() -> None:
    """链与各家自备过滤叠加不能吃件：二次过闸结果必须逐条相同。"""
    batch = [_CLS_FED, _CCTV_FED, _MAP_JUNK, _PRC_JUNK]
    once = ws.gate_chain_hits(batch, "美联储最新利率决议")
    assert once == [_CCTV_FED, _CLS_FED]
    assert ws.gate_chain_hits(once, "美联储最新利率决议") == once


# --------------------------------------------------------------------------- #
# ③ 时效档：带日期的先给模型看，但永不越过权威档、永不越过地板
# --------------------------------------------------------------------------- #


def test_dated_source_outranks_undated_within_the_same_tier() -> None:
    """时政意图（问句自带「最新」）+ 同为一手源 ⇒ 带日期那条先给模型看。"""
    dated = _hit(
        "中国人民银行 决定 下调 存款准备金率",
        "2026年9月20日 · 降准于当日落地生效。",
        "https://www.gov.cn/zhengce/202609/jz.htm",
        "www.gov.cn",
    )
    undated = _hit(
        "中国人民银行 决定 下调 存款准备金率",
        "央行通知：降准于当日落地生效。",
        "https://www.gov.cn/zhengce/jz.htm",
        "www.gov.cn",
    )
    assert ws.gate_chain_hits([undated, dated], "央行 降准 落地 最新") == [dated, undated]
    # 问句不要求新鲜度 ⇒ 时效加权不介入，退回原抓取顺序（缺省形态逐字节不变）。
    assert ws.gate_chain_hits([undated, dated], "央行 降准 落地 时间") == [undated, dated]


def test_freshness_never_outranks_authority_tier() -> None:
    """无日期的一手源仍排在有日期的无名站之前：时效只许在同档内说话。"""
    first_party_undated = _hit(
        "美联储 维持 利率 不变",
        "议息会议决定维持利率不变，后续视通胀数据调整。",
        "https://www.federalreserve.gov/newsevents",
        "www.federalreserve.gov",
    )
    unknown_dated = _hit(
        "美联储 维持 利率 不变 解读",
        "2026年9月24日 · 某个人博客的转述。",
        "https://blog.example.com/2026/09/fed",
        "blog.example.com",
    )
    assert ws.gate_chain_hits(
        [unknown_dated, first_party_undated], "美联储 利率 决议 最新"
    ) == [first_party_undated, unknown_dated]


@pytest.mark.parametrize(
    ("url", "snippet", "expected"),
    [
        ("https://www.gov.cn/zhengce/202609/x.htm", "国务院印发通知", True),
        ("https://news.cctv.com/a", "2026年9月17日 · 正文", True),
        ("https://www.cls.cn/subject/1350", "1 天前 · 摘句", True),
        ("https://www.eastmoney.com/a/2026-03-15/x.html", "无日期摘要", True),
        ("https://www.gov.cn/zhengce/2026/x.htm", "只出现年份，不构成日期", False),
        ("https://www.gov.cn/zhengce/x.htm", "什么日期都没有", False),
        ("https://www.gov.cn/zhengce/x.htm", "2026高清版大图", False),
    ],
)
def test_datedness_is_a_shape_test_not_a_clock_read(
    url: str, snippet: str, expected: bool
) -> None:
    """只判形态、不解析成时刻 ⇒ 不读时钟、跨日不变、离线可复跑。"""
    assert ws._hit_is_dated(_hit("标题", snippet, url, "")) is expected


# --------------------------------------------------------------------------- #
# ④ 时效信号真身（search_intent.detect_query_recency）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "wants_latest"),
    [
        ("美联储最新利率决议", True),
        ("央行降准消息", True),
        ("2026年最低工资标准", True),
        ("黄金价格今天多少钱一克", True),
        ("股价查询", True),
        ("什么是量化宽松", False),
        ("三国演义的作者", False),
        ("", False),
    ],
)
def test_query_recency_marker(text: str, wants_latest: bool) -> None:
    assert detect_query_recency(text).wants_latest is wants_latest


def test_query_recency_years_are_purely_lexical() -> None:
    """年份只按字面取、绝不与「今年」比较 ⇒ 纯函数、无时钟依赖。"""
    recency = detect_query_recency("央行降准 2026 与 2024 对比 最新消息")
    assert recency.years == (2024, 2026)
    assert recency.names_year("2026") and recency.names_year("2024")
    assert not recency.names_year("央行")
    assert not recency.names_year("2026年")  # 只有纯数字 token 才算年份
    assert detect_query_recency("").years == ()
    assert detect_query_recency("").wants_latest is False


# --------------------------------------------------------------------------- #
# ⑤ F3 反向锁：上游真给垃圾时必须判空，不许为凑数放宽
# --------------------------------------------------------------------------- #


def test_translation_farm_batch_returns_empty_for_an_income_query() -> None:
    assert ws.gate_chain_hits([_TRANS_JUNK], "居民人均可支配收入数据") == []


def test_almanac_batch_returns_empty_for_a_gold_price_query() -> None:
    """2026-09-11 旧注释防的是逗号切；本波防的是三元组派生出「今天黄」。"""
    strong, _ = ws._token_evidence_forms("今天黄金价格多少钱一克")
    assert "今天黄" not in strong
    assert "黄金价" in strong
    assert ws.gate_chain_hits([_ALMANAC_JUNK], "今天黄金价格多少钱一克") == []


def test_alias_leg_rescues_the_abbreviated_index_query() -> None:
    """F4 在册限制**已于本波解除**（席 S-T-SEARCHQ-2，2026-09-26）。

    旧锁钉的是「问句写『综指』、页面写『指数』⇒ 形态对不上，整批判空」这一现状，
    并要求日后改动先推翻它、留下新证据。证据 = `%TEMP%\\sq1_bing_capture.json`
    那 88 条真实命中的手工标注（席报告 §4）：`上证 综指 收盘 点位` 一题上游**确实**
    把正解给回来了（东方财富/新浪/雪球/百度财经的上证指数行情页共 5 条），
    旧判据按整批 2 分未达地板把 5 条全丢——召回率因此只有 6/11 = 54.5%。
    修法不是放宽地板，而是补上「简称⇒全称」这条**有向**词形通道
    （`_QUERY_ALIAS_FORMS`），见同组三条负向锁：放宽的方向被逐条钉死。
    量化前后：留下 20→28 条、确实相关 6→11 条、精确率 30.0%→39.3%、召回率 54.5%→100%。
    """
    quote = _hit(
        "上证指数 (000001)_股票行情_走势图—东方财富网",
        "提供上证指数(000001)的行情走势、资金流向、行业概念板块排行。",
        "https://quote.eastmoney.com/ZS000001.html",
        "quote.eastmoney.com",
    )
    assert ws.gate_chain_hits([quote], "上证 综指 收盘 点位") == [quote]
    # 词形本来就对得上的问句不受影响（别名只在缺通道时起作用）。
    assert ws.gate_chain_hits([quote], "上证 指数 行情 走势") == [quote]


def test_alias_use_is_named_in_the_audit_trail(caplog) -> None:
    """别名不是静默放宽：审计行必须写出「综指~指数」这一跳。"""
    quote = _hit(
        "上证指数 (000001)_股票行情_走势图—东方财富网",
        "提供上证指数(000001)的行情走势、资金流向。",
        "https://quote.eastmoney.com/ZS000001.html",
        "quote.eastmoney.com",
    )
    with caplog.at_level(logging.INFO, logger=ws.__name__):
        ws.gate_chain_hits([quote, _ALMANAC_JUNK], "上证 综指 收盘 点位")
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "综指~指数" in joined          # 走了哪条别名，账上看得见
    assert "quote.eastmoney.com|" in joined  # 留下/丢掉的每条都点名


# --- 别名表三条自律（负向锁：放宽的方向必须逐条钉死）--------------------------- #


def test_alias_never_decomposes_into_a_substring_match() -> None:
    """「央行→中央银行」绝不等于「含『银行』就算命中」——工商银行那页必须仍被丢。"""
    icbc = _hit(
        "中国工商银行",
        "银行贷款利率与存款业务说明，个人住房贷款。",
        "https://www.icbc.com.cn/loans",
        "www.icbc.com.cn",
    )
    assert ws.gate_chain_hits([icbc], "央行 降准 落地 最新") == []


def test_alias_is_directed_never_bidirectional() -> None:
    """反向不放：问句写「指数」绝不靠「综指」凑证据（消费者价格指数 ≠ 综合指数）。"""
    cpi = _hit(
        "消费者价格指数上涨",
        "居民消费价格指数同比上涨 0.6%，通胀压力总体可控。",
        "https://www.gov.cn/cpi/202609",
        "www.gov.cn",
    )
    assert ws.gate_chain_hits([cpi], "上证 指数 收盘 点位") == []
    assert ws.gate_chain_hits([cpi], "上证 综指 收盘 点位") == []


def test_alias_table_is_a_narrow_directed_graph() -> None:
    """表本身的纪律：有向无 2-环、目标不做停用词、不做通用词、键≠目标。"""
    for source, targets in ws._QUERY_ALIAS_FORMS.items():
        assert targets, source
        for target in targets:
            assert source != target, source
            assert len(target) >= ws._MIN_ALIAS_CHARS, target
            assert target not in ws._QUERY_STOP_TOKENS, target
            # 无 2-环：别名目标反向指回来源＝把有向表写成双向表
            assert source not in ws._QUERY_ALIAS_FORMS.get(target, ()), (source, target)
    # 通用词一律不许当别名目标（那会把任何财经页放回来）。「指数」是**唯一例外**：
    # 它只做 2 字弱证据，且实测要求同批还有「上证」这一枚独立证据才过地板
    # （CPI 那页因此仍被拒，见上两条），所以它抬不了孤证。
    for forbidden in ("银行", "公司", "价格", "新闻", "网站", "数据"):
        assert all(
            forbidden not in targets for targets in ws._QUERY_ALIAS_FORMS.values()
        ), forbidden


# --------------------------------------------------------------------------- #
# ⑥ 链头反爬墙：看得见，且不改行为
# --------------------------------------------------------------------------- #

_CHALLENGE_HTML = (
    "<html><body>DuckDuckGo Unfortunately, bots use DuckDuckGo too. "
    "Please complete the following challenge to confirm this search was made by a human. "
    "Select all squares containing a duck: <input></body></html>"
)
_RESULTS_HTML = (
    '<html><body><div class="result"><h2><a class="result__a" '
    'href="https://www.gov.cn/zhengce/202609/jz.htm">中国人民银行 降准</a></h2>'
    '<a class="result__snippet" href="https://www.gov.cn/x">2026年9月20日 降准落地</a>'
    "</div></body></html>"
)


def test_challenge_page_is_reported_once_per_cooldown(monkeypatch, caplog) -> None:
    monkeypatch.setattr(ws, "_ddg_block_last_warned", 0.0)
    with caplog.at_level(logging.WARNING, logger=ws.__name__):
        ws._note_ddg_challenge(_CHALLENGE_HTML)
        ws._note_ddg_challenge(_CHALLENGE_HTML)
    warnings = [
        record for record in caplog.records if "anti-bot challenge" in record.getMessage()
    ]
    assert len(warnings) == 1  # 抑制窗口内只报一次，但第一次必须点名


def test_challenge_detection_does_not_change_search_behaviour(monkeypatch) -> None:
    """观测归观测：命中验证页时返回形态与改前一致（空表，交链回退下一家）。"""
    seen: list[str] = []
    monkeypatch.setattr(ws, "_fetch", lambda *a, **k: _CHALLENGE_HTML)
    monkeypatch.setattr(ws, "_note_ddg_challenge", seen.append)
    provider = ws.DuckDuckGoWebSearchProvider(timeout_seconds=3.0, proxy="")
    try:
        assert provider.search("美联储最新利率决议") == []
    finally:
        provider.close()
    assert seen == [_CHALLENGE_HTML]  # 钩子确实挂在检索出口上，不是写了不调


def test_normal_result_page_still_searches_and_warns_nothing(monkeypatch, caplog) -> None:
    monkeypatch.setattr(ws, "_fetch", lambda *a, **k: _RESULTS_HTML)
    monkeypatch.setattr(ws, "_ddg_block_last_warned", 0.0)
    provider = ws.DuckDuckGoWebSearchProvider(timeout_seconds=3.0, proxy="")
    try:
        with caplog.at_level(logging.WARNING, logger=ws.__name__):
            kept = provider.search("央行 降准 落地")
    finally:
        provider.close()
    assert _domains(kept) == ["www.gov.cn"]
    assert [r for r in caplog.records if "anti-bot" in r.getMessage()] == []


# --------------------------------------------------------------------------- #
# ⑦ fail-open：坏提供器 / 坏输入只能降级，绝不炸掉这一轮
# --------------------------------------------------------------------------- #


class _BoomProvider:
    name = "boom"

    def search(self, query: str, *, max_results: int = 3) -> list[ws.WebSearchHit]:
        raise RuntimeError("provider exploded")


class _RawProvider:
    """自身不过滤的提供器（Tavily 型）：链必须替它执法。"""

    name = "raw"

    def __init__(self, hits: list[ws.WebSearchHit]) -> None:
        self._hits = hits

    def search(self, query: str, *, max_results: int = 3) -> list[ws.WebSearchHit]:
        return list(self._hits)


def test_broken_provider_degrades_and_the_chain_moves_on() -> None:
    chain = ws.ChainedWebSearchProvider([_BoomProvider(), _RawProvider([_CCTV_FED])])
    assert chain.search("美联储最新利率决议", max_results=3) == [_CCTV_FED]
    assert ws.ChainedWebSearchProvider([_BoomProvider()]).search("美联储最新利率决议") == []


@pytest.mark.parametrize("query", ["", "   ", "2026", "最新 消息", "的", "！"])
def test_no_entity_extractable_means_no_floor_applied(query: str) -> None:
    """拿不到实体就不抬门槛（fail-open）：此时只走低质剔除，与旧实现同形。"""
    assert ws._query_entity_forms(query) == []
    assert _domains(ws.gate_chain_hits([_MAP_JUNK, _TAX_GOOD], query)) == [
        "chinatax.gov.cn",  # 无实体可判 ⇒ 仍按权威档排序，但不丢件
        "bajiu.cn",
    ]


def test_query_side_guards_never_raise_on_hostile_input() -> None:
    """判据全在字符串上做，坏输入只能判成「没实体」，不许抛。"""
    for hostile in ("(" * 200, "中" * 4000, "\x00\x01", "??" * 50, "2099年"):
        assert isinstance(ws._query_entity_forms(hostile), list)
        assert isinstance(ws.gate_chain_hits([_TAX_GOOD], hostile), list)
    assert ws._token_evidence_forms("2026") == ((), ())
    assert ws._token_evidence_forms("") == ((), ())


# --------------------------------------------------------------------------- #
# ⑧ 零网络自证（本文件全部用例必须在断网下同样成立）
# --------------------------------------------------------------------------- #


def _no_socket(*_args, **_kwargs):
    raise AssertionError("本文件的任何一条用例都不该碰网络")


def test_nothing_in_this_file_touches_the_network(monkeypatch) -> None:
    monkeypatch.setattr(socket, "socket", _no_socket)
    monkeypatch.setattr(socket, "getaddrinfo", _no_socket)
    assert ws.gate_chain_hits([_CLS_FED, _MAP_JUNK], "美联储最新利率决议") == [_CLS_FED]
    assert detect_query_recency("央行降准最新消息").wants_latest is True
    assert ws._hit_is_dated(_CCTV_FED) is True


# --------------------------------------------------------------------------- #
# ⑨ 形态约束：不建第二真身
# --------------------------------------------------------------------------- #


def test_authority_registry_is_still_the_only_host_table() -> None:
    """域名档唯一住 source_authority；本波新增的都是**问句侧**表，不是主机表。"""
    for forbidden in ("_POLITICAL_HOSTS", "_FINANCE_HOSTS", "_ENCYCLOPEDIA_DOMAIN_FRAGMENTS"):
        assert not hasattr(ws, forbidden), forbidden
    assert ws._domain_priority(_TAX_GOOD)[0] == TIER_FIRST_PARTY
    assert ws._domain_priority(_MAP_JUNK)[0] == TIER_UNKNOWN


def test_datedness_and_tier_are_two_legs_of_one_sort_key() -> None:
    """排序键两半各归一位：档级来自 `order_key`，日期来自本件形态判定。"""
    tier, domain = ws._domain_priority(_CLS_FED, "美联储最新利率决议")
    assert (tier, domain) == ws.order_key(_CLS_FED.source_domain, "美联储最新利率决议")


def test_gate_constants_are_defined_exactly_once() -> None:
    """防回潮：本波两次栽在「同名模块级赋值静默覆盖」上（台账 #53 一次、本件一次）。

    判据分值表被定义两遍时，后一份赢、前一份变注释，测试仍可能全绿而线上走另一套值。
    这里用 AST 数模块级赋值次数，每枚只准一次。
    """
    import ast
    from pathlib import Path

    source = Path(ws.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    watched = {
        "_STRONG_EVIDENCE", "_WEAK_EVIDENCE", "_FLOOR_SHORT", "_FLOOR_RICH",
        "_RICH_TOKEN_COUNT", "_GRAM_MIN_SEGMENT", "_JUNK_DOMAINS", "_QUERY_STOP_TOKENS",
    }
    counts: dict[str, int] = {}
    for node in tree.body:  # 只看模块级，函数内同名赋值不算
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in watched:
                    counts[target.id] = counts.get(target.id, 0) + 1
        elif isinstance(node, ast.AnnAssign) and isinstance(
            node.target, ast.Name
        ) and node.target.id in watched:
            counts[node.target.id] = counts.get(node.target.id, 0) + 1
    duplicated = {name: n for name, n in counts.items() if n != 1}
    assert not duplicated, f"模块级重复定义（后者静默覆盖前者）：{duplicated}"
    assert set(counts) == watched, f"缺定义：{watched - set(counts)}"


# --------------------------------------------------------------------------- #
# ⑩ 反过度过滤：新判据只准丢「对不上实体」的，正常结果一条不许误杀
# --------------------------------------------------------------------------- #

_LORE_BATCH = [
    _hit(
        "守岸人_萌娘百科",
        "守岸人是《鸣潮》中的角色，泰缇斯系统的第二实例。",
        "https://zh.moegirl.org.cn/守岸人",
        "zh.moegirl.org.cn",
    ),
    _hit(
        "守岸人（《鸣潮》角色）_百度百科",
        "守岸人，游戏《鸣潮》登场角色，负责管理守岸的职务。",
        "https://baike.baidu.com/item/守岸人",
        "baike.baidu.com",
    ),
    _hit(
        "《鸣潮》守岸人角色介绍 - 哔哩哔哩",
        "鸣潮官方角色「守岸人」立绘、技能与背景介绍。",
        "https://www.bilibili.com/read/shorekeeper",
        "www.bilibili.com",
    ),
    _hit(
        "守岸人讨论 - 库街区",
        "玩家对守岸人剧情定位与强度培养的讨论。",
        "https://www.kurobbs.com/post/shorekeeper",
        "www.kurobbs.com",
    ),
]


def test_clean_encyclopedia_batch_loses_nothing() -> None:
    """百科式正常结果：每条都实打实写着「守岸人」⇒ 一条都不许被新判据杀掉。"""
    kept = ws.gate_chain_hits(list(_LORE_BATCH), "守岸人 是谁")
    assert {hit.title for hit in kept} == {hit.title for hit in _LORE_BATCH}


def test_ranking_reorders_but_never_drops_a_relevant_hit() -> None:
    """权威档 + 时效两把排序键只重排顺序；过闸集合本身不许因排序变小。"""
    kept = ws.gate_chain_hits(list(_LORE_BATCH), "守岸人 最新消息")
    assert len(kept) == len(_LORE_BATCH)
    assert [hit.source_domain for hit in kept] == [
        "www.bilibili.com",  # 垂类 2（同档内按域名字典序稳定排）
        "www.kurobbs.com",   # 垂类 2
        "baike.baidu.com",   # 通用百科 3
        "zh.moegirl.org.cn",  # 通用百科 3
    ]
    # 同一批换一个输入顺序，产出必须是同一个序（确定性，不看字典序以外的东西）。
    assert ws.gate_chain_hits(list(reversed(_LORE_BATCH)), "守岸人 最新消息") == kept


def test_single_good_hit_survives_a_multi_entity_query() -> None:
    """地板量的是相关性、不是条数：一条真对得上的，哪怕整批只有它，也必须留下。"""
    assert ws.gate_chain_hits([_TAX_GOOD2], "个人所得税 起征点 每月") == [_TAX_GOOD2]


@pytest.mark.parametrize(
    ("query", "batch"),
    [
        ("美联储最新利率决议", [_CLS_FED, _CCTV_FED, _XINHUA_FED]),
        ("上证 综指 收盘 点位", [_INDEX_QUOTE, _SSE_HOME, _ALMANAC_JUNK]),
        ("央行 降准 落地 最新", [_GOV_RRR, _BLOG_RRR]),
        ("个人所得税 起征点 每月", [_TAX_GOOD, _TAX_GOOD2, _MAP_JUNK]),
    ],
)
def test_alias_leg_is_monotone_never_narrows_the_kept_set(
    query: str, batch: list[ws.WebSearchHit], monkeypatch
) -> None:
    """别名只**追加**形态 ⇒ 去掉别名表后留下的集合必须是现集合的子集。

    这条是「不许顺手放宽成误杀/误放的开关」的结构锁：若哪天有人把别名做成筛选条件
    （而不是形态补充），这一发的包含关系当场断。
    """
    with_alias = {hit.title for hit in ws.gate_chain_hits(list(batch), query)}
    monkeypatch.setattr(ws, "_QUERY_ALIAS_FORMS", {})
    without_alias = {hit.title for hit in ws.gate_chain_hits(list(batch), query)}
    assert without_alias <= with_alias
    if query == "上证 综指 收盘 点位":
        # 别名在该题上确实救回了东西，且**只**救回写了实体名的两条：东方财富行情页
        # 与上交所官网首页。后者我手工标注里判「次解」（摘要只有指数系列目录、没有收盘
        # 点位），闸门无从分辨——它只能看字面证据。这是别名通道的已知代价，如实钉在账上：
        # 救回的是「点名了同一实体」的页，不是靠通用词凑数的页（对照下面三条负向锁）。
        assert with_alias - without_alias == {_INDEX_QUOTE.title, _SSE_HOME.title}


def test_whole_batch_drop_names_every_hit_in_the_audit(caplog) -> None:
    """整批判空时不许只留一个数字：每条被丢的都要有名字、分数与理由。"""
    with caplog.at_level(logging.INFO, logger=ws.__name__):
        assert ws.gate_chain_hits([_MAP_JUNK, _PRC_JUNK, _TRANS_JUNK], "上证 综指 收盘 点位") == []
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "kept=0" in joined and "dropped_by_floor=3" in joined
    for domain in ("bajiu.cn", "baike.baidu.com", "fanyi.baidu.com"):
        assert f"{domain}|" in joined, domain
    assert "0f" in joined  # 每条都记了「2 分未达地板」这类分数，而不是一句"不相关"


def test_floor_and_junk_counters_are_two_lenses_not_a_partition(caplog) -> None:
    """同一条既能是低质域、又能不达地板——两个计数**故意**重叠，别有人去"修成互斥"。"""
    with caplog.at_level(logging.INFO, logger=ws.__name__):
        ws.gate_chain_hits([_DICTIONARY_OFF_TOPIC], "上证 综指 收盘 点位")
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "dropped_as_junk=1" in joined and "dropped_by_floor=1" in joined
    assert "kept=0" in joined and "|0fx|" in joined  # 裁决字母 fx 就是那一格重叠
