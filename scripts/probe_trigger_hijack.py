"""触发劫持探针（TRG-AUDIT 实证，只读不改源码）。

实证 trg-inventory §7 推断的三条劫持风险：

1. divination：``_DIVINATION_COMMAND_RE`` 无锚子串（八字/塔罗/算命/占卜…），
   疑似可劫持任意含这些词的聊天句（DIVINATION 先于 moegirl_question/chat）。
2. stocks：openai/anthropic 等非上市公司豁免词 ``key in lowered`` 子串即触发
   （≤32 字），且 STOCKS（规则序 16）先于 MOEGIRL_QUESTION(44)/CHAT(50)。
3. market：触发词「行情」的排除表 ``_NON_STOCK_RE`` 未含油价/金价等
   商品价格语境词，「油价行情/金价行情」疑似落股指面板。

方法：直接调用 ``classify_message_route``（base_router 真实判定顺序，全部
路由开关取默认值），逐条对比实际落点与预期落点；对被劫持条目再用「关闭
劫持方开关」复测一次，得到让路后的真实落点（证明劫持次序而非误判）。

用法：``python scripts/probe_trigger_hijack.py [--markdown]``
纯离线：不联网、不发消息、不写任何运行数据。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.bot_unified_runtime.runtime.base_router import (
    RouteKind,
    classify_message_route,
)

__all__ = ["SAMPLES", "main", "run_probe"]


class _DefaultConfig:
    """全部路由开关走 base_router 的 getattr 默认值（默认启用语义）。"""


class _ToggleOffConfig:
    """除指定开关强制 False 外，其余属性全部走 getattr 默认值。"""

    def __init__(self, toggle: str) -> None:
        self._toggle = toggle

    def __getattr__(self, name: str) -> object:
        if name == self._toggle:
            return False
        raise AttributeError(name)


# 劫持方 RouteKind → 其路由开关（让路复测用；与 base_router matcher 一致）。
_ROUTE_TOGGLES: dict[RouteKind, str] = {
    RouteKind.DIVINATION: "bot_divination_enabled",
    RouteKind.STOCKS: "bot_stocks_enabled",
    RouteKind.MARKET: "bot_market_enabled",
    RouteKind.WEATHER: "bot_weather_query_enabled",
    RouteKind.NEWS: "bot_news_enabled",
    RouteKind.EAT: "bot_eat_enabled",
    RouteKind.FX: "bot_fx_enabled",
    RouteKind.REMINDER: "bot_reminder_enabled",
}

# 劫持风险归类：①divination ②stocks ③market；control=真命令对照；other=范围外。
_RISK_1 = "①divination"
_RISK_2 = "②stocks"
_RISK_3 = "③market"

# (样例文本, 预期落点, 风险归类)。预期=按 T-Spec T17（裸短词不触发、
# 长度/边界守卫）人工判定的「这句自然语义应该去哪」。
SAMPLES: list[tuple[str, RouteKind, str]] = [
    # ── 风险①：divination 无锚子串 ──
    ("我说算命都是骗人的", RouteKind.CHAT, _RISK_1),
    ("塔罗牌在哪买", RouteKind.CHAT, _RISK_1),
    ("推荐个八字APP", RouteKind.CHAT, _RISK_1),
    ("我朋友会算命，据说特别准", RouteKind.CHAT, _RISK_1),
    ("楼下新开了家占卜小店", RouteKind.CHAT, _RISK_1),
    ("这事八字还没一撇呢", RouteKind.CHAT, _RISK_1),
    ("别给我算命，我不信这个", RouteKind.CHAT, _RISK_1),
    ("朋友送了我一副塔罗牌，还没拆", RouteKind.CHAT, _RISK_1),
    # ── 风险① 对照：真命令应正常触发 ──
    ("塔罗", RouteKind.DIVINATION, "control"),
    ("占卜", RouteKind.DIVINATION, "control"),
    ("八字 1998年3月2日早上7点", RouteKind.DIVINATION, "control"),
    # ── 风险① 前贴口语恢复（良性前缀白名单）：新正例必须直达 divination，
    #    否定语境仍落 chat（fix-hj1-report「前贴口语恢复」节）──
    ("帮我占卜", RouteKind.DIVINATION, "control"),
    ("帮我算个塔罗", RouteKind.DIVINATION, "control"),
    ("来一卦", RouteKind.DIVINATION, "control"),
    ("别占卜了", RouteKind.CHAT, _RISK_1),
    # ── 风险① 繁體前缀波：繁體口语正例必须直达 divination
    #    （fix-hj1-report「繁體前缀」节）──
    ("幫我占卜", RouteKind.DIVINATION, "control"),
    ("幫我搖一卦", RouteKind.DIVINATION, "control"),
    # ── 风险②：stocks openai/anthropic 豁免子串（先于 moegirl_question/chat）──
    ("openai是什么", RouteKind.MOEGIRL_QUESTION, _RISK_2),
    ("openai 的 gpt 咋用", RouteKind.CHAT, _RISK_2),
    ("anthropic和openai哪家强", RouteKind.CHAT, _RISK_2),
    # 风险② 同族变体：股价/股票 hint 词本身也是无锚子串
    ("股票被套了怎么办，难受", RouteKind.CHAT, _RISK_2),
    # ── 风险② 对照 ──
    ("openai 估值多少", RouteKind.STOCKS, "control"),
    ("英伟达股价", RouteKind.STOCKS, "control"),
    # ── 风险③：market「行情」排除表缺油价/金价语境词 ──
    ("今天油价行情怎么样", RouteKind.CHAT, _RISK_3),
    ("金价行情如何", RouteKind.CHAT, _RISK_3),
    ("看看油价行情", RouteKind.CHAT, _RISK_3),
    ("今天金价多少", RouteKind.CHAT, _RISK_3),
    ("金价行情 https://example.com/gold", RouteKind.CONTENT, _RISK_3),
    # ── 风险③ 对照 ──
    ("美股行情", RouteKind.MARKET, "control"),
    ("大盘行情", RouteKind.MARKET, "control"),
    # ── moegirl_question 让路修复对照（invest-moegirl-hijack §四）：
    #    「帮我查 + 天气」问句族应落 natural_command(45) 归一化 weather，
    #    不再被 moegirl_question 剥前缀判成萌百实体抢路。──
    ("帮我查天气 杭州", RouteKind.NATURAL_COMMAND, "control"),
    ("帮我查一下杭州天气", RouteKind.NATURAL_COMMAND, "control"),
    # ── 日常寒暄与既有能力对照（范围外，验证探针本身不误报）──
    ("今天心情不错，摸鱼去了", RouteKind.CHAT, "other"),
    ("在吗", RouteKind.CHAT, "other"),
    ("晚安，守岸人", RouteKind.CHAT, "other"),
    ("哈哈哈笑死我了", RouteKind.CHAT, "other"),
    ("有人周末一起打游戏吗", RouteKind.CHAT, "other"),
    ("天气预报说明天下雨", RouteKind.CHAT, "other"),
    ("初音未来是谁", RouteKind.MOEGIRL_QUESTION, "other"),
    ("查天气 杭州", RouteKind.WEATHER, "other"),
    ("12点提醒我写作业", RouteKind.REMINDER, "other"),
    ("今天吃什么", RouteKind.EAT, "other"),
    ("点歌 晴天", RouteKind.MUSIC, "other"),
    ("好感度", RouteKind.AFFINITY, "other"),
    ("今晚欧元汇率涨了没", RouteKind.FX, "other"),
]


def run_probe() -> list[dict[str, str]]:
    """跑全部样例，返回逐条判定记录（纯内存，无副作用）。"""

    default_config = _DefaultConfig()
    off_configs: dict[str, _ToggleOffConfig] = {}
    records: list[dict[str, str]] = []
    for text, expected, risk in SAMPLES:
        actual = classify_message_route(text, config=default_config, alias_resolver=None)
        verdict = "OK" if actual.kind == expected else "HIJACKED"
        fallback = ""
        if verdict == "HIJACKED":
            toggle = _ROUTE_TOGGLES.get(actual.kind)
            if toggle is not None:
                off_config = off_configs.setdefault(toggle, _ToggleOffConfig(toggle))
                rerun = classify_message_route(
                    text, config=off_config, alias_resolver=None
                )
                fallback = rerun.kind.value
            records.append(
                {
                    "text": text,
                    "risk": risk,
                    "expected": expected.value,
                    "actual": actual.kind.value,
                    "fallback": fallback,
                    "verdict": verdict,
                }
            )
        else:
            records.append(
                {
                    "text": text,
                    "risk": risk,
                    "expected": expected.value,
                    "actual": actual.kind.value,
                    "fallback": "",
                    "verdict": verdict,
                }
            )
    return records


def _tally(records: list[dict[str, str]]) -> dict[str, int]:
    """按风险归类统计 HIJACKED 数。"""
    tally: dict[str, int] = {}
    for record in records:
        if record["verdict"] == "HIJACKED":
            tally[record["risk"]] = tally.get(record["risk"], 0) + 1
    return tally


def _print_table(records: list[dict[str, str]], markdown: bool) -> None:
    if markdown:
        print("| 样例 | 归类 | 预期 | 实际 | 关闭劫持方后 | 判定 |")
        print("|---|---|---|---|---|---|")
        for record in records:
            values = {**record, "fallback": record["fallback"] or "—"}
            print(
                "| {text} | {risk} | {expected} | {actual} | {fallback} | {verdict} |".format(
                    **values
                )
            )
    else:
        width = max(len(record["text"]) for record in records) + 2
        header = f"{'样例':<{width}} {'归类':<14} {'预期':<18} {'实际':<10} {'让路后':<10} 判定"
        print(header)
        print("-" * len(header))
        for record in records:
            print(
                f"{record['text']:<{width}} {record['risk']:<14} "
                f"{record['expected']:<18} {record['actual']:<10} "
                f"{record['fallback'] or '—':<10} {record['verdict']}"
            )
    tally = _tally(records)
    total_hijacked = sum(tally.values())
    print()
    print(f"样例数：{len(records)}；HIJACKED 合计：{total_hijacked}")
    for risk in (_RISK_1, _RISK_2, _RISK_3):
        print(f"  {risk}：{tally.get(risk, 0)}")
    others = {k: v for k, v in tally.items() if k not in (_RISK_1, _RISK_2, _RISK_3)}
    if others:
        print(f"  范围外误配：{others}")


def main(argv: list[str] | None = None) -> int:
    markdown = "--markdown" in (argv if argv is not None else sys.argv[1:])
    records = run_probe()
    _print_table(records, markdown=markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
