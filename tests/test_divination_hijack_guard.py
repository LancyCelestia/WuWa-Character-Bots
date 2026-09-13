"""divination 无锚子串劫持修复回归锁（probe-hijack-report §①，8/8 实证）。

修法三守卫（只动 ``is_divination_command`` 判定函数，能力逻辑零改动）：
1. 独立成词锚定：中文触发词前后不贴 CJK 字符（``塔罗牌在哪买`` 的 塔罗贴着
   牌 → 不触发）；复合命令（今日塔罗/塔罗三张/生辰八字/金钱卦/每日一抽…）
   作为整词显式收录，保住既有真命令。
2. 长度 + URL 守卫：>32 字或含 http(s) 链接不触发（对齐 stocks/market 的
   ``_MAX_TRIGGER_LEN``/``_URL_HINT_RE`` 既有模式；链接让位内容解析）。
3. 惯用语排除表：``八字还没一撇`` 等俗语即使在边界意外放行时也一票否决。

前贴口语恢复波（良性前缀白名单）：
4. 白名单引导（帮我/求/来/想…）+ 触发词 ⇒ 视为独立触发（只豁免「前贴」
   否决，中贴/后贴锚定与三守卫照旧）；否定/负面语境（别/不/少/骗子…）
   不进白名单，维持落 chat；惯用语排除表优先级高于白名单。

探针 8 条劫持样例一条不能漏；真命令对照（含生产接线钉死的
``八字 1998年3月2日早上7点`` 与 test_trigger_english 钉死的英文触发）零回归。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.divination import (
    is_divination_command,
    parse_divination_intent,
)
from plugins.bot_unified_runtime.runtime.base_router import (
    RouteKind,
    classify_message_route,
    clear_route_decision_cache,
)

# 探针 §① 八条劫持样例（probe-hijack-report 实测 8/8 HIJACKED → 应落 chat）。
HIJACK_SAMPLES: list[str] = [
    "我说算命都是骗人的",
    "塔罗牌在哪买",
    "推荐个八字APP",
    "我朋友会算命，据说特别准",
    "楼下新开了家占卜小店",
    "这事八字还没一撇呢",
    "别给我算命，我不信这个",
    "朋友送了我一副塔罗牌，还没拆",
]

# 真命令对照：裸短词 + 复合命令 + 带参 + 英文（test_trigger_english 已钉子集）。
CONTROL_SAMPLES: list[str] = [
    "占卜",
    "塔罗",
    "八字",
    "排盘",
    "四柱",
    "命盘",
    "算命",
    "起卦",
    "算卦",
    "摇卦",
    "六十四卦",
    "金钱卦",
    "每日一抽",
    "每日一签",
    "每日一簽",
    "今日塔罗",
    "今天塔罗",
    "塔罗三张",
    "生辰八字",
    "八字 1998年3月2日早上7点",
    "排盘 1998年3月2日",
    "tarot",
    "tarots",
    "bazi",
    "iching",
    "hexagram",
    "divination",
    "daily tarot",
    "tarot three cards",
]


@pytest.mark.parametrize("sample", HIJACK_SAMPLES)
def test_hijack_sample_does_not_trigger(sample: str) -> None:
    assert not is_divination_command(sample), f"劫持样例仍被占卜抢走：{sample!r}"


@pytest.mark.parametrize("sample", CONTROL_SAMPLES)
def test_true_command_still_triggers(sample: str) -> None:
    assert is_divination_command(sample), f"真命令回归：{sample!r} 不再触发"


@pytest.mark.parametrize("sample", HIJACK_SAMPLES)
def test_hijack_sample_routes_to_chat(sample: str) -> None:
    """路由级：劫持样例应落 chat（探针 §① 预期落点）。"""
    clear_route_decision_cache()
    try:
        decision = classify_message_route(
            sample, config=SimpleNamespace(), alias_resolver=None
        )
    finally:
        clear_route_decision_cache()
    assert decision.kind is RouteKind.CHAT, (
        f"{sample!r} 预期落 chat，实得 {decision.kind.value}"
    )


@pytest.mark.parametrize(
    "sample", ["占卜", "塔罗", "八字 1998年3月2日早上7点", "金钱卦", "每日一抽"]
)
def test_true_command_routes_to_divination(sample: str) -> None:
    clear_route_decision_cache()
    try:
        decision = classify_message_route(
            sample, config=SimpleNamespace(), alias_resolver=None
        )
    finally:
        clear_route_decision_cache()
    assert decision.kind is RouteKind.DIVINATION, (
        f"{sample!r} 预期落 divination，实得 {decision.kind.value}"
    )


@pytest.mark.parametrize(
    "sample", ["帮我占卜", "来一卦", "帮我算个塔罗", "幫我占卜", "幫我搖一卦"]
)
def test_prefixed_command_routes_to_divination(sample: str) -> None:
    """路由级：白名单前贴口语命令应落 divination。"""
    clear_route_decision_cache()
    try:
        decision = classify_message_route(
            sample, config=SimpleNamespace(), alias_resolver=None
        )
    finally:
        clear_route_decision_cache()
    assert decision.kind is RouteKind.DIVINATION, (
        f"{sample!r} 预期落 divination，实得 {decision.kind.value}"
    )


@pytest.mark.parametrize(
    "sample",
    [
        "占卜 https://example.com/tarot",
        "塔罗 https://x.test/a",
        "八字排盘看这个链接 http://example.com/bazi",
    ],
)
def test_url_guard_blocks_trigger(sample: str) -> None:
    """含链接不触发（让位内容解析）。"""
    assert not is_divination_command(sample), f"URL 守卫失效：{sample!r}"


def test_url_sample_routes_away_from_divination() -> None:
    clear_route_decision_cache()
    try:
        decision = classify_message_route(
            "占卜 https://example.com/tarot",
            config=SimpleNamespace(),
            alias_resolver=None,
        )
    finally:
        clear_route_decision_cache()
    assert decision.kind is not RouteKind.DIVINATION


def test_length_guard_boundary() -> None:
    """>32 字不触发；32 字（含）以内且独立成词仍触发（对齐 stocks/market）。"""
    assert not is_divination_command("塔罗 " + "a" * 30)  # 33 字
    assert is_divination_command("塔罗 " + "a" * 29)  # 32 字
    assert not is_divination_command("八字 " + "1998年3月2日早上7点" * 3)  # 42 字


@pytest.mark.parametrize(
    "sample",
    [
        "这事八字还没一撇呢",
        "八字还没一撇",
        "八字没一撇",
        "别急，八字还没一撇呢",
    ],
)
def test_idiom_exclusion_table(sample: str) -> None:
    """惯用语排除表：俗语一票否决（边界守卫的兜底保险）。"""
    assert not is_divination_command(sample), f"惯用语误触发：{sample!r}"


# ── 前贴口语恢复波：良性前缀白名单 ──
# 白名单引导（帮我/求/来/想…）+ 触发词 ⇒ 独立触发（只豁免前贴，锚定照旧）。
PREFIXED_POSITIVE_SAMPLES: list[str] = [
    "帮我占卜",
    "帮我算个塔罗",
    "帮我抽个塔罗",
    "帮我测个八字",
    "帮我占卜一下",
    "求占卜",
    "想算命",
    "想要塔罗",
    "来个塔罗",
    "来一卦",
    "算一卦",
    "起一卦",
    "摇一卦",
    "给我来一卦",
    "麻烦占卜一下",
    "请帮我算命",
]

# 否定/负面语境不进白名单：否定词领头（含「白名单词被否定包裹」变体）
# 与含触发词的贬义句维持落 chat。
NEGATED_SAMPLES: list[str] = [
    "别给我算命，我不信这个",
    "少来这套迷信",
    "别占卜了",
    "不想算命",
    "我拒绝占卜",
    "别帮我塔罗",
    "骗子才会算命",
    "帮我骂占卜小店",
]


# 繁體前缀波：与简体表同款语义的繁體口语引导（幫我/幫忙/來/求/搖個/擲個/
# 問個/測個/想/我想要…）。求/抽/想/我想要 等简繁同形词不入本表（已被简体
# 表覆盖）；「求籤」不作正例——裸 籤/签 不在触发词表，简体「求签」同样落 chat。
TRADITIONAL_PREFIXED_POSITIVE_SAMPLES: list[str] = [
    "幫我占卜",
    "幫我搖一卦",
    "幫忙占卜一下",
    "請幫我算命",
    "麻煩測個八字",
    "來個塔羅",
    "來一卦",
    "問個塔羅",
    "測個八字",
    "搖個塔羅",
    "給我來一卦",
]

# 繁體否定/负面语境：否定词领头不进白名单，与简体同款维持落 chat；
# 繁體俗语「八字還沒一撇」由惯用语表（含繁体变体）一票否决。
TRADITIONAL_NEGATED_SAMPLES: list[str] = [
    "別幫我占卜",
    "別給我算命",
    "別想占卜",
    "少來這套迷信",
    "我拒絕占卜",
]


@pytest.mark.parametrize("sample", PREFIXED_POSITIVE_SAMPLES)
def test_benign_prefix_command_triggers(sample: str) -> None:
    """白名单前缀 + 触发词：前贴口语命令恢复触发。"""
    assert is_divination_command(sample), f"前贴口语仍被拦：{sample!r}"


@pytest.mark.parametrize("sample", TRADITIONAL_PREFIXED_POSITIVE_SAMPLES)
def test_traditional_prefix_command_triggers(sample: str) -> None:
    """繁體白名单前缀 + 触发词：繁體前贴口语命令恢复触发。"""
    assert is_divination_command(sample), f"繁體前贴口语仍被拦：{sample!r}"


@pytest.mark.parametrize("sample", TRADITIONAL_PREFIXED_POSITIVE_SAMPLES)
def test_traditional_prefixed_gate_subset_of_intent_parser(sample: str) -> None:
    """繁體前贴口语命中路由后意图解析必承接（命中必承接不变式）。"""
    intent = parse_divination_intent(sample)
    assert intent is not None, f"路由命中但意图解析不承接：{sample!r}"


@pytest.mark.parametrize("sample", TRADITIONAL_NEGATED_SAMPLES)
def test_traditional_negated_context_stays_chat(sample: str) -> None:
    """繁體否定/负面语境不进白名单：维持落 chat（劫持不许重开）。"""
    assert not is_divination_command(sample), f"繁體否定语境误触发：{sample!r}"


@pytest.mark.parametrize("sample", NEGATED_SAMPLES)
def test_negated_context_stays_chat(sample: str) -> None:
    """否定/负面语境不进白名单：维持落 chat（劫持不许重开）。"""
    assert not is_divination_command(sample), f"否定语境误触发：{sample!r}"


@pytest.mark.parametrize(
    "sample",
    ["帮我看看八字还没一撇", "来个八字还没一撇", "幫我看看八字還沒一撇"],
)
def test_idiom_exclusion_beats_prefix_whitelist(sample: str) -> None:
    """惯用语排除表优先级高于白名单：白名单前缀不豁免俗语。"""
    assert not is_divination_command(sample), f"俗语经白名单漏触发：{sample!r}"


@pytest.mark.parametrize("sample", PREFIXED_POSITIVE_SAMPLES)
def test_prefixed_gate_subset_of_intent_parser(sample: str) -> None:
    """前贴口语命中路由后意图解析必承接（头注释不变式对白名单同样成立）。"""
    intent = parse_divination_intent(sample)
    assert intent is not None, f"路由命中但意图解析不承接：{sample!r}"


@pytest.mark.parametrize("sample", CONTROL_SAMPLES)
def test_gate_subset_of_intent_parser(sample: str) -> None:
    """路由门 ⊆ 意图解析（divination.py 头注释不变式：命中必承接）。

    已知既有例外：英文 ``divination`` 仅路由词表收录、意图解析不认
    （命中后走能力层 noop 引导文案），非本批引入，不在断言内。
    """
    if sample == "divination":
        pytest.skip("既有路由词表单侧收录，noop 引导分支承接")
    intent = parse_divination_intent(sample)
    assert intent is not None, f"路由命中但意图解析不承接：{sample!r}"


# ---------------------------------------------------------------------------
# parked 收口（2026-09-13 实战审计）：求籤/求签 另立 + 真冲突缩写禁用锁
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["求籤", "求签"])
def test_qiuqian_standalone_triggers(text: str) -> None:
    """求籤/求签 独立触发词（另立收口）：命中即必承接（金钱卦意图）。"""
    assert is_divination_command(text) is True
    assert parse_divination_intent(text) is not None


@pytest.mark.parametrize("text", ["bz", "zb", "sz", "sm"])
def test_conflict_initials_stay_disabled(text: str) -> None:
    """bz/zb/sz/sm 真冲突缩写不启用——divination.py 词表注释钉死的设计裁定。"""
    assert is_divination_command(text) is False
