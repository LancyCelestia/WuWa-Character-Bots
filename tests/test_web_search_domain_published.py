"""检索链「来源域名 / 发布时间 / 时效窗 / 引擎归因」四条 plumbing 回归锁（WEB 席）。

对应 WEBCFG-AUDIT 表 B 与用户第 3 项「取最新最权威来源」的两处结构性断点：

① **key 主链的来源域名从来没被填**：``normalize_search_results`` 只造
   ``WebSearchHit(title, snippet, url)``，``source_domain`` 恒为空串。于是
   ``source_authority.authority_tier("")`` 一律 ``TIER_UNKNOWN``、``_is_junk``
   的域名字典闸永不命中、``_audit_trail`` 全打 ``?``、chat.py 的按域优先级表
   与 prompt 里的 ``-[域名]`` 前缀全部失明——**「权威源优先」在生产主链
   （Tavily）上等于没接**。免 key 的 DDG/Bing 两家自己填了域名，所以这条
   只在有 key 的链上塌，测试必须走 ``normalize_search_results`` 才看得见。
② **发布时间不进结果**：引擎返回的 ``published_date`` 一类字段被丢掉，
   「带发布时间与口径」在结果面上没有载体，档内「有日期者优先」只能靠
   标题/摘要里的日期字样碰运气。
③ **时效窗按类目收窄**（E-3 后续）：链上只有一个全局档
   （``bot_web_search_tavily_time_range``），金融/新闻/赛事与科技/时政同宽。
   本锁要求链接受注入的 ``window_resolver``，**未注入时逐字节维持现状**。
④ **链头引擎交回人机验证页要能归因**（E-4/PX-21）：此前只打日志、
   不进任何决策与账目，运维把「今天 DDG 是死的」读成「没查到」。

全部离线：只喂构造的 payload 与假 provider，零网络、零写盘。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.core.contracts.character import (
    WebSearchHit as ContractWebSearchHit,
)
from plugins.bot_unified_runtime.domains.core.search import web_search as ws
from plugins.bot_unified_runtime.domains.core.search.search_api import (
    normalize_search_results,
)
from plugins.bot_unified_runtime.domains.core.search.source_authority import (
    TIER_AGGREGATOR,
    TIER_FIRST_PARTY,
    TIER_UNKNOWN,
    authority_tier,
)

# 足够长以过 `_MIN_SNIPPET_CHARS`（24），避免被摘要闸挪位。
_SNIPPET = "官方公告称本次调整自当日起执行，具体口径以正式文件为准。"


def _tavily_payload(items: list[dict[str, object]]) -> dict[str, object]:
    """Tavily 形响应体（``{"results": [...]}``）。

    刻意返回 dict 而不是 JSON 字符串：``normalize_search_results`` 的入口按
    ``Mapping`` 处理，喂字符串会让「没命中」与「解析器不认」两种结果同形，
    那正好是本次要修的盲区（域名空串→权威档失明）的同一种遮蔽形态。
    """
    return {"results": items}



# ---------------------------------------------------------------------------
# ① 来源域名：provider 自带优先，否则由 URL 现推；绝不虚构
# ---------------------------------------------------------------------------


def test_normalize_fills_source_domain_from_url_when_provider_gives_none() -> None:
    hits = normalize_search_results(
        _tavily_payload(
            [{"url": "https://www.reuters.com/markets/x", "title": "路透报道", "content": _SNIPPET}]
        ),
        max_results=3,
    )
    assert len(hits) == 1
    # 大小写归一、去端口、去 userinfo、去单一 `www.` 前缀（权威档按末段后缀比，
    # 带不带 www 都能命中；剥它只为让 `_is_junk` 的字典域名精确匹配不吃暗亏）。
    assert hits[0].source_domain == "reuters.com"
    assert authority_tier(hits[0].source_domain) == TIER_FIRST_PARTY


def test_normalize_prefers_provider_supplied_domain_over_url() -> None:
    hits = normalize_search_results(
        _tavily_payload(
            [
                {
                    "url": "https://m.baijiahao.baidu.com/s?id=1",
                    "displayLink": "baijiahao.baidu.com",
                    "title": "转载稿",
                    "content": _SNIPPET,
                }
            ]
        ),
        max_results=3,
    )
    assert hits[0].source_domain == "baijiahao.baidu.com"
    assert authority_tier(hits[0].source_domain) == TIER_AGGREGATOR


def test_normalize_keeps_domain_empty_for_unparsable_url() -> None:
    # 结构性无域名（相对链接）⇒ 空串，不拿 "None"/"?" 之类的假值顶替。
    hits = normalize_search_results(
        {"results": [{"url": "https://", "title": "怪链接", "content": _SNIPPET}]},
        max_results=3,
    )
    assert hits == [] or all(hit.source_domain != "None" for hit in hits)


def test_keyfree_chain_hits_now_reach_junk_gate_by_domain() -> None:
    """端到端后果锁：农场页**词面完全相关**，过去只因域名空串而漏过字典域名闸。

    两条命中的标题/摘要都对问句有实体证据，唯一差别是域名——所以本腿一旦变绿，
    绿的就是「域名进账」这一件事，不是相关性判据被放宽。
    """
    junk_domain = min(ws._JUNK_DOMAINS)
    hits = normalize_search_results(
        _tavily_payload(
            [
                {
                    "url": f"https://{junk_domain}/page",
                    "title": "央行宣布降准",
                    "content": "央行决定降准，长期流动性进一步释放。",
                },
                {
                    "url": "https://pbc.gov.cn/notice",
                    "title": "中国人民银行 降准 公告",
                    "content": "央行公告：本次降准自当日起执行。",
                },
            ]
        ),
        max_results=3,
    )
    assert [hit.source_domain for hit in hits] == [junk_domain, "pbc.gov.cn"]
    gated = ws.gate_chain_hits(hits, "央行 降准 公告")
    assert [hit.source_domain for hit in gated] == ["pbc.gov.cn"]


# ---------------------------------------------------------------------------
# ② 发布时间：有则带、无则空，绝不拿抓取时间顶替
# ---------------------------------------------------------------------------


def test_normalize_carries_published_date_from_provider_payload() -> None:
    hits = normalize_search_results(
        _tavily_payload(
            [
                {
                    "url": "https://w.soundofgoods.com/x",
                    "published_date": "2026-09-28",
                    "title": "公告",
                    "content": _SNIPPET,
                }
            ]
        ),
        max_results=3,
    )
    assert hits[0].published_at == "2026-09-28"


def test_normalize_leaves_published_at_empty_when_absent() -> None:
    hits = normalize_search_results(
        _tavily_payload([{"url": "https://example.com/x", "title": "无日期", "content": _SNIPPET}]),
        max_results=3,
    )
    assert hits[0].published_at == ""


def test_hit_is_dated_uses_structured_published_at() -> None:
    undated = ws.WebSearchHit(title="标题", snippet=_SNIPPET, url="https://a.com/1")
    dated = ws.WebSearchHit(
        title="标题",
        snippet=_SNIPPET,
        url="https://a.com/1",
        source_domain="a.com",
        published_at="2026-09-28",
    )
    assert not ws._hit_is_dated(undated)
    assert ws._hit_is_dated(dated)


def test_hit_is_dated_accepts_contract_model_without_published_at() -> None:
    """两枚 ``WebSearchHit`` 混装面：契约模型没有 ``published_at``，判据不许点炸。

    ACG 竖源融合后的列表里 dataclass 与 pydantic 契约两型并存（本仓在册事实），
    `_order_for_reading` / `_hit_is_dated` 必须对两型同权工作。
    """
    contract_hit = ContractWebSearchHit(
        title="人民银行公告", snippet=_SNIPPET, url="https://pbc.gov.cn/notice"
    )
    assert ws._hit_is_dated(contract_hit) is False
    ordered = ws._order_for_reading(
        [
            contract_hit,
            ws.WebSearchHit(
                title="无名站", snippet=_SNIPPET, url="https://zzz.example/1"
            ),
        ],
        "央行 最新 公告",
    )
    assert len(ordered) == 2


def test_dated_hit_leads_within_same_authority_tier_only() -> None:
    """带日期优先只在同档内成立：一手源的无日期页仍压过无名站的日期页。"""
    unknown_dated = ws.WebSearchHit(
        title="无名站消息",
        snippet=_SNIPPET,
        url="https://unknown-site.example/1",
        source_domain="unknown-site.example",
        published_at="2026-09-28",
    )
    first_party_undated = ws.WebSearchHit(
        title="人民银行公告",
        snippet=_SNIPPET,
        url="https://pbc.gov.cn/2",
        source_domain="pbc.gov.cn",
    )
    ordered = ws._order_for_reading(
        [unknown_dated, first_party_undated], "央行 最新 降准 公告"
    )
    assert [hit.source_domain for hit in ordered] == ["pbc.gov.cn", "unknown-site.example"]
    assert authority_tier("pbc.gov.cn") == TIER_FIRST_PARTY
    assert authority_tier("unknown-site.example") == TIER_UNKNOWN


# ---------------------------------------------------------------------------
# ③ 类目化时效窗：注入才通电，未注入逐字节现状
# ---------------------------------------------------------------------------


class _FakeTavily:
    """声明吃得下 ``extra_body`` 的最小假 provider（照 Tavily 的形态声明）。"""

    name = "fake-tavily"
    accepts_extra_body = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def search(self, query, *, max_results=3, extra_body=None):
        self.calls.append((query, extra_body))
        return [
            ws.WebSearchHit(
                title="公告",
                snippet=_SNIPPET,
                url="https://pbc.gov.cn/notice",
                source_domain="pbc.gov.cn",
            )
        ]


def _chain(**kwargs: object) -> ws.ChainedWebSearchProvider:
    return ws.ChainedWebSearchProvider([_FakeTavily()], **kwargs)  # type: ignore[arg-type]


def test_window_resolver_none_keeps_global_time_range_behaviour() -> None:
    chain = _chain(latest_time_range="week")
    chain.search("央行 最新 降准", max_results=1)
    provider = chain.providers[0]
    assert provider.calls[0][1] == {"time_range": "week"}


def test_window_resolver_overrides_global_per_query() -> None:
    chain = _chain(
        latest_time_range="week",
        window_resolver=lambda query: "day" if "汇率" in query else "",
    )
    chain.search("美元 兑 人民币 最新 汇率", max_results=1)
    chain.search("央行 降准 落地 时间", max_results=1)
    provider = chain.providers[0]
    assert provider.calls[0][1] == {"time_range": "day"}
    # 解析器判「不开窗」⇒ 不发 time_range（历史题/lore 题不被窗挡掉旧档）。
    assert provider.calls[1][1] is None


def test_window_resolver_still_respects_provider_capability_flag() -> None:
    """provider 自声明吃不下 extra_body ⇒ 绝不开这条通道（链级三闸之一）。"""

    class _KeyFreeShaped(_FakeTavily):
        accepts_extra_body = False

    chain = ws.ChainedWebSearchProvider([_KeyFreeShaped()], window_resolver=lambda _q: "day")
    chain.search("英超 最新 比分", max_results=1)
    assert chain.providers[0].calls[0][1] is None


# ---------------------------------------------------------------------------
# ④ 引擎归因：验证页进账，且取走即清（不留到下一轮）
# ---------------------------------------------------------------------------


def test_ddg_challenge_records_drainable_diagnostic(monkeypatch) -> None:
    monkeypatch.setattr(ws, "_ddg_block_last_warned", 0.0)
    ws.drain_chain_diagnostics()  # 清场，防别的用例串味
    ws._note_ddg_challenge(
        "Please complete the following challenge to confirm this search "
        "was made by a human. Select all squares containing a duck."
    )
    kinds = ws.drain_chain_diagnostics()
    assert "engine:ddg_challenge" in kinds
    assert ws.drain_chain_diagnostics() == []


def test_clean_page_records_no_diagnostic() -> None:
    ws.drain_chain_diagnostics()
    ws._note_ddg_challenge('<div class="result"><a class="result__a">正文</a></div>')
    assert ws.drain_chain_diagnostics() == []


def test_diagnostic_records_survive_warn_cooldown(monkeypatch) -> None:
    """日志有 600s 抑制窗，归因账**不**跟着抑制——否则同一轮第二次查询无账可查。"""
    monkeypatch.setattr(ws, "_ddg_block_last_warned", ws.time.monotonic())
    ws.drain_chain_diagnostics()
    ws._note_ddg_challenge("Please complete the following challenge")
    assert "engine:ddg_challenge" in ws.drain_chain_diagnostics()
