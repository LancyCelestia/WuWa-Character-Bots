"""路由优先级「同优先级抢占同一句话」机器门（WP5，2026-09-21，全离线）。

审计 E4-2：base_router 的 commodities/bond/northbound/market/fx 全挤在优先级 41，
「同一句话被 ≥2 条规则命中且这两条同优先级」时谁赢只取决于书写序——真跑谓词证实
「美元兑人民币行情」被 is_market_command 与 is_fx_command 同时命中、而 fx 写在
market 之后 ⇒ 问汇率拿到一张全球股指面板；「国债行情」则「碰巧排对」才对，任何人
改表序就翻车。

本门把这条不变量钉死为**可重跑枚举**：

- 语料从代码派生（禁硬编码快照）：每条能力的行为验证触发词全集
  （``scripts.extract_trigger_words.build_inventory`` 的 ``verified_triggers``，
  含繁体/拼音/英文）作单子探针，叠加金融/天气/个股触发词 × 现实连接词
  （「行情/价格/走势」后缀、「天气 /点歌 」前缀）的组合，外加施工图点名的跨域
  组合句。规则表 = 运行时 ``ROUTE_RULES``（``build_route_rules`` 真身），不抄快照。
- 判据：语料上不存在「同优先级多命中」（≥2 条规则命中同一句且优先级相等）。

四把牙（照 tests/test_trigger_bidirectional_gate.py / test_db_owners_coverage.py
的变异锁风格）：
1. ``test_no_same_priority_multi_hit_on_enum_corpus``：主门——枚举语料零冲突；
2. ``test_corpus_really_covers_the_finance_collision_space``：前提自证——语料里
   确有跨 market/fx/commodities/bond/northbound/weather 的多命中句子（否则门可能
   被「让谓词永不相交」糊过去，主门失去杀伤力）；
3. ``test_gate_flags_injected_same_priority_collision``：负样本注入——构造两条同
   优先级且同时命中一句的规则，门必须报冲突（防主门退化成永真摆设）；
4. ``test_named_e42_defect_fixed``：真机口径回归锁——点名句子路由到正确能力。

另锁 ``test_finance_family_priorities_distinct_and_ordered``：金融族五档优先级两两
不同且按「越专用越靠前」排序（拆优先级本身的语义锁，防随手 +1）。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
    ROUTE_RULES,
    RouteDecision,
    RouteKind,
    RouteRule,
    classify_message_route,
    clear_route_decision_cache,
)
from scripts.extract_trigger_words import build_inventory


class _DefaultConfig:
    """全部路由开关走 base_router 的 getattr 默认值（默认启用语义）。"""


@pytest.fixture(autouse=True)
def _clean_route_cache() -> object:
    clear_route_decision_cache()
    yield
    clear_route_decision_cache()


# 能力 id → 展示名（点名的跨域组合句用）；连接词是现实问法探针，非优先级快照。
_MARKET_SUFFIXES = ("行情", "价格", "走势")
_LEADING_COMMAND_PREFIXES = ("天气 ", "点歌 ")
# 施工图点名的跨域组合句（E4-2 现场证据）。
_NAMED_COMBOS = (
    "美元兑人民币行情",
    "黄金价格行情",
    "比特币行情",
    "英伟达股价走势",
    "天气 黄金",
    "国债行情",
    "原油行情",
    "北向资金行情",
    "日元兑换人民币行情",
)
# 已知让路面（在册裁定：商品遇股词让位 market；股指遇前导命令让位）。
_YIELD_PROBES = ("黄金股行情", "huangjin股行情", "股市股价", "天气 大盘", "点歌 原油")

# 组合探针只围绕金融/天气/个股域触发词生成（缺陷域），不把「点歌 塔罗」这类
# 无厘头并置拉进门——那类由触发规范化门（test_trigger_bidirectional_gate 等）
# 按前导动词管，不属优先级劫持。
_COMPOSITION_SCOPE = frozenset(
    {
        "bot.market",
        "bot.fx",
        "bot.commodities",
        "bot.bond",
        "bot.northbound",
        "bot.weather",
        "bot.stocks",
    }
)


def _enum_corpus() -> list[str]:
    """从当前源码派生的枚举语料（行为验证触发词 ∪ 现实组合 ∪ 点名/让路探针）。"""
    inventory = build_inventory()
    singles: list[str] = [
        info["probe"]
        for entry in inventory["capabilities"].values()
        for info in entry["verified_triggers"].values()
    ]
    scope_triggers: list[str] = [
        info["probe"]
        for capability_id, entry in inventory["capabilities"].items()
        if capability_id in _COMPOSITION_SCOPE
        for info in entry["verified_triggers"].values()
    ]
    combos: list[str] = []
    for word in scope_triggers:
        for suffix in _MARKET_SUFFIXES:
            combos.extend((word + suffix, word + " " + suffix))
        for prefix in _LEADING_COMMAND_PREFIXES:
            combos.append(prefix + word)
    return [*singles, *combos, *_NAMED_COMBOS, *_YIELD_PROBES]


def _matching_rules(text: str, rules: list[RouteRule]) -> list[RouteRule]:
    out: list[RouteRule] = []
    for rule in rules:
        if rule.matcher is None:
            continue
        try:
            if rule.matcher(text, _DefaultConfig(), None) is not None:
                out.append(rule)
        except Exception:  # noqa: S112, BLE001 - 谓词异常按未命中记账（同体检口径）。
            continue
    return out


def _same_priority_multi_hits(
    corpus: list[str], rules: list[RouteRule]
) -> dict[tuple[int, tuple[str, ...]], list[str]]:
    """返回 {(优先级, (命中 kind 序)): [触发该冲突的语料句子]}。"""
    conflicts: dict[tuple[int, tuple[str, ...]], list[str]] = {}
    for raw in corpus:
        text = raw.strip()
        if not text:
            continue
        by_priority: dict[int, list[str]] = {}
        for rule in _matching_rules(text, rules):
            by_priority.setdefault(rule.priority, []).append(rule.kind.value)
        for priority, kinds in by_priority.items():
            if len(kinds) >= 2:
                conflicts.setdefault((priority, tuple(sorted(kinds))), []).append(text)
    return conflicts


# ---------------------------------------------------------------------------
# ① 主门：枚举语料上不存在同优先级多命中
# ---------------------------------------------------------------------------


def test_no_same_priority_multi_hit_on_enum_corpus() -> None:
    conflicts = _same_priority_multi_hits(_enum_corpus(), list(ROUTE_RULES))
    report = "\n".join(
        f"  优先级={prio} 命中={list(kinds)} 例={sorted(ex)[:5]}"
        for (prio, kinds), ex in sorted(conflicts.items())
    )
    assert not conflicts, (
        "检测到「同优先级抢占同一句话」的路由冲突（谁赢只取决于书写序=脆弱）：\n"
        f"{report}\n"
        "修法：给冲突族分配互不相同的优先级（越专用越靠前），或收紧过宽的谓词。"
    )


# ---------------------------------------------------------------------------
# ② 前提自证：语料确实覆盖金融族多命中空间（防门被「永不相交」糊过去）
# ---------------------------------------------------------------------------


def test_corpus_really_covers_the_finance_collision_space() -> None:
    """语料里确有跨金融族的多命中句——否则主门可能空转（无杀伤力）。

    判据取「命中集合大小≥2」而非优先级相等：这些句子在修复前是同优先级冲突，
    修复后仍多条命中（只是优先级已拆开），故本断言证明语料真的把候选规则凑到
    了一起碰，不是靠删语料凑绿。
    """
    covered: set[frozenset[str]] = set()
    for text in _enum_corpus():
        kinds = frozenset(rule.kind.value for rule in _matching_rules(text, list(ROUTE_RULES)))
        if len(kinds) >= 2:
            covered.add(kinds)
    finance = {"market", "fx", "commodities", "bond", "northbound", "weather"}
    assert any(
        kinds >= {"market", "fx"} for kinds in covered
    ), "语料未覆盖 market+fx 多命中（美元兑人民币行情类），主门失去对 E4-2 的杀伤力"
    assert any(kinds >= {"market", "bond"} for kinds in covered), "语料未覆盖 market+bond 多命中"
    assert any(kinds >= {"market", "commodities"} for kinds in covered), "语料未覆盖 market+commodities 多命中"
    assert any(kinds & finance and "weather" in kinds for kinds in covered), "语料未覆盖 weather×金融 多命中"


# ---------------------------------------------------------------------------
# ③ 负样本注入：门必须抓到同优先级冲突（变异锁，防永真摆设）
# ---------------------------------------------------------------------------


def test_gate_flags_injected_same_priority_collision() -> None:
    """注入两条同优先级、同时命中一句的规则 ⇒ 判据函数必须报冲突。

    若有人把主门改成永远返回空/或让 _same_priority_multi_hits 失明，本用例先红。
    """

    def always_match(_text, _config, _alias) -> RouteDecision:
        return RouteDecision(RouteKind.MARKET, "bot.injected", 41, "注入", ())

    colliding = [
        RouteRule(RouteKind.MARKET, "bot.a", 41, "A", "注入样本", matcher=always_match),
        RouteRule(RouteKind.FX, "bot.b", 41, "B", "注入样本", matcher=always_match),
    ]
    conflicts = _same_priority_multi_hits(["随便什么句子"], colliding)
    assert conflicts, "注入的同优先级双命中未被抓到——门没有牙"
    assert (41, ("fx", "market")) in conflicts or any(p == 41 for (p, _k) in conflicts)

    # 对照组：同样两条规则但优先级拆开 ⇒ 不再报冲突（证明门判的是「同优先级」）。
    disambiguated = [
        RouteRule(RouteKind.MARKET, "bot.a", 40, "A", "对照", matcher=always_match),
        RouteRule(RouteKind.FX, "bot.b", 41, "B", "对照", matcher=always_match),
    ]
    assert not _same_priority_multi_hits(["随便什么句子"], disambiguated)


# ---------------------------------------------------------------------------
# ④ 真机口径回归锁：点名句子路由到正确能力（E4-2 现场）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("美元兑人民币行情", RouteKind.FX),  # 修前被 market(41,书写在前) 抢走
        ("日元兑换人民币行情", RouteKind.FX),
        ("国债行情", RouteKind.BOND),  # 修前「碰巧排对」，改表序即翻车
        ("原油行情", RouteKind.COMMODITIES),
        ("北向资金行情", RouteKind.NORTHBOUND),
        ("黄金价格行情", RouteKind.COMMODITIES),
        ("比特币行情", RouteKind.MARKET),  # 无特异金融词 → 仍归泛股指
        ("行情", RouteKind.MARKET),
        ("美股行情", RouteKind.MARKET),
        ("天气 黄金", RouteKind.WEATHER),  # 前导命令让路（金融特异卡不抢天气句）
        ("点歌 原油", RouteKind.MUSIC),  # 前导命令让路（金融特异卡不抢点歌句）
    ],
)
def test_named_e42_defect_fixed(text: str, expected: RouteKind) -> None:
    clear_route_decision_cache()
    assert classify_message_route(text, config=_DefaultConfig(), alias_resolver=None).kind is expected


# ---------------------------------------------------------------------------
# ⑤ 拆优先级本身的语义锁：金融族五档两两不同、越专用越靠前
# ---------------------------------------------------------------------------


def test_finance_family_priorities_distinct_and_ordered() -> None:
    prio = {rule.kind: rule.priority for rule in ROUTE_RULES}
    family = [RouteKind.FX, RouteKind.COMMODITIES, RouteKind.BOND, RouteKind.NORTHBOUND, RouteKind.MARKET]
    numbers = [prio[k] for k in family]
    assert len(set(numbers)) == len(numbers), f"金融族优先级未全部拆开：{dict(zip([k.value for k in family], numbers))}"
    # 越专用越靠前：四个具体品种名都排在最泛的「行情」catch-all(market) 之前。
    assert all(prio[k] < prio[RouteKind.MARKET] for k in family if k is not RouteKind.MARKET)
    # market 仍是全表里带「行情/大盘/股市」触发、优先级落在原 40 段之上的通用档；
    # 「天气 X」/「点歌 X」由前导命令让路锁覆盖（见 ④），本处不重复。

