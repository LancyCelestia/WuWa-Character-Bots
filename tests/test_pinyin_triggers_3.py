"""T-Spec T1.5/T1.6 第三批：fx/reminder/divination 拼音触发词回归 + 二批 echo 顺延。

第一批/第二批四层断言照抄（词表来源
``.superpowers/sdd/2026-09-12-shorekeeper-global-audit/pinyin-mapping-draft.json``
终审子集，入表/放弃依据见同目录 ``fix-py3-report.md``）：

1. 命中：每能力拼音词（全拼+查重无冲突缩写）命中自身 ``is_*`` 检测器；
2. 唯一性：拼音词探针跑全部 ``is_*`` 检测器零跨能力冲突（真冲突缩写不启用）；
3. 词边界：双侧 ASCII 胶合与字母延续零命中（yaoguai/qiguai 类真实近形词必测）；
4. 守卫 parity + 零回归：divination 三守卫（独立成词锚定/长度 URL/惯用语排除）
   对拼音同口径——拼音词走 ASCII 双边界＝锚定模拟，长度/URL/惯用语守卫在
   ``is_divination_command`` 判定层天然继承；简体原词行为不变。

批内结构性边界（记录为锁定断言）：
- reminder 信号词面（提醒/叫我/记得叫 → tixing/jiaowo/jidejiao）依赖
  ``character/reminders.py`` 的 ``_REMIND_SIGNAL_RE``（白名单外）同步才能
  端到端承接，本批只入表列表查询面（提醒列表/我的提醒/看看提醒/有哪些提醒
  及其缩写）；信号词面拼音必须保持零命中（防半吊子上线）。
- echo aliases 含第二批五能力顺延别名（第二批因 echo 占用顺延到本批）。
"""

from __future__ import annotations

import importlib

import pytest

from plugins.bot_unified_runtime.capabilities.divination import (
    is_divination_command,
    parse_divination_intent,
)
from scripts.extract_trigger_words import build_inventory

# ---------------------------------------------------------------------------
# 被测词表：(能力 id, 拼音词, 行为探针)。探针口径与前两批一致：
# fx/divination/reminder 列表面均整句裸发（fx 面板词、divination 裸短词、
# reminder 列表查询词都是无门槛整句触发）。
# ---------------------------------------------------------------------------

PINYIN_HITS: list[tuple[str, str, str]] = [
    # 汇率（fx._FX_HINT_RE：整句短文本；hl/dh 真冲突缩写不启用）
    ("bot.fx", "huilv", "huilv"),
    ("bot.fx", "duihuan", "duihuan"),
    ("bot.fx", "huanhui", "huanhui"),
    ("bot.fx", "hh", "hh"),
    # 提醒（reminder._LIST_RE 列表查询面；信号词面依赖白名单外解析器，不入表）
    ("bot.reminder", "tixingliebiao", "tixingliebiao"),
    ("bot.reminder", "txlb", "txlb"),
    ("bot.reminder", "wodetixing", "wodetixing"),
    ("bot.reminder", "wdtx", "wdtx"),
    ("bot.reminder", "kankantixing", "kankantixing"),
    ("bot.reminder", "kktx", "kktx"),
    ("bot.reminder", "younaxietixing", "younaxietixing"),
    ("bot.reminder", "ynxt", "ynxt"),
    # 占卜（divination：拼音过三守卫，bz/zb/sz/sm 真冲突缩写不启用）
    ("bot.divination", "zhanbu", "zhanbu"),
    ("bot.divination", "taluo", "taluo"),
    ("bot.divination", "tl", "tl"),
    ("bot.divination", "paipan", "paipan"),
    ("bot.divination", "pp", "pp"),
    ("bot.divination", "sizhu", "sizhu"),
    ("bot.divination", "mingpan", "mingpan"),
    ("bot.divination", "mp", "mp"),
    ("bot.divination", "suanming", "suanming"),
    ("bot.divination", "qigua", "qigua"),
    ("bot.divination", "qg", "qg"),
    ("bot.divination", "suangua", "suangua"),
    ("bot.divination", "sg", "sg"),
    ("bot.divination", "yaogua", "yaogua"),
    ("bot.divination", "yg", "yg"),
    ("bot.divination", "liushisigua", "liushisigua"),
    ("bot.divination", "lssg", "lssg"),
    ("bot.divination", "jinqiangua", "jinqiangua"),
]

# divination 路由⇒意图承接不变式：每个拼音词必须被 parse_divination_intent
# 解析出正确子意图（复用 test_divination_hijack_guard 的 ⊆ 不变式口径）。
DIVINATION_INTENT_KINDS: list[tuple[str, str]] = [
    ("zhanbu", "iching"),
    ("qigua", "iching"),
    ("qg", "iching"),
    ("suangua", "iching"),
    ("sg", "iching"),
    ("yaogua", "iching"),
    ("yg", "iching"),
    ("liushisigua", "iching"),
    ("lssg", "iching"),
    ("jinqiangua", "iching"),
    ("taluo", "tarot"),
    ("tl", "tarot"),
    ("paipan", "bazi"),
    ("pp", "bazi"),
    ("sizhu", "bazi"),
    ("mingpan", "bazi"),
    ("mp", "bazi"),
    ("suanming", "bazi"),
]

# 劫持守卫样例抽 3 条（复用 test_divination_hijack_guard HIJACK_SAMPLES）：
# 惯用语排除 / CJK 独立成词锚定 / 混英文 APP 句——拼音入表后一条不能漏。
DIVINATION_HIJACK_SAMPLES: list[str] = [
    "这事八字还没一撇呢",
    "塔罗牌在哪买",
    "推荐个八字APP",
]

# 全部 is_* 行为检测器（capability_id -> [callable]），复用 T-Spec 提取器。
_INV = build_inventory()
_ALL_DETECTORS: dict[str, list] = {}
for _cap in sorted(_INV["capabilities"]):
    for _report in _INV["capabilities"][_cap]["detectors"]:
        if not _report.get("callable") or not _report["name"].startswith("is_"):
            continue
        _func = getattr(importlib.import_module(_report["module"]), _report["name"])
        _ALL_DETECTORS.setdefault(_cap, []).append(_func)


def _probe_hits(probe: str) -> list[str]:
    return sorted(
        cap for cap in sorted(_ALL_DETECTORS) if any(func(probe) for func in _ALL_DETECTORS[cap])
    )


def _detector_of(capability_id: str):
    def _hits(probe: str) -> bool:
        return any(func(probe) for func in _ALL_DETECTORS[capability_id])

    return _hits


# ---------------------------------------------------------------------------
# 1) 命中：拼音词命中自身能力
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cap,word,probe", PINYIN_HITS, ids=lambda x: str(x))
def test_pinyin_word_hits_owner_capability(cap: str, word: str, probe: str) -> None:
    assert _detector_of(cap)(probe), f"拼音词未命中自身能力：{cap} <- {word!r}（探针 {probe!r}）"


# ---------------------------------------------------------------------------
# 2) 唯一性：探针跑全部 is_* 零跨能力冲突
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cap,word,probe", PINYIN_HITS, ids=lambda x: str(x))
def test_pinyin_probe_unique_across_detectors(cap: str, word: str, probe: str) -> None:
    hits = _probe_hits(probe)
    assert hits == [cap], f"拼音词跨能力冲突：{word!r} 探针 {probe!r} 命中 {hits}"


# ---------------------------------------------------------------------------
# 3) 词边界：双侧胶合 / 字母延续零命中（_alias_hit 纪律）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cap,word,probe",
    [(cap, word, probe) for cap, word, probe in PINYIN_HITS if len(word) >= 2],
    ids=lambda x: str(x),
)
def test_pinyin_word_glued_probes_do_not_hit(cap: str, word: str, probe: str) -> None:
    hit = _detector_of(cap)
    for glued in (f"qq{word}", f"{word}qq"):
        assert not hit(glued), f"拼音词左/右胶合命中：{cap} 命中 {glued!r}"
        assert not _probe_hits(glued), f"拼音词胶合误伤他能力：{glued!r} 命中 {_probe_hits(glued)}"


def test_letter_extensions_and_nearform_words_do_not_hit() -> None:
    """防子串胶合样例（T-Spec 指定）：字母延续与真实近形词零命中。

    yaoguai（妖怪）/qiguai（奇怪）是拼音右侧胶合的高频真实误伤源，
    双侧词边界必须拦住；hhs/duihuans 类字母延续同理。
    """
    for probe in (
        "zhanbuzhe",
        "taluopai",
        "paipanq",
        "sizhux",
        "mingpans",
        "suanminger",
        "qiguai",  # 奇怪
        "yaoguai",  # 妖怪
        "liushisiguaq",
        "jinqianguas",
        "hhs",
        "huilvs",
        "duihuans",
        "tixingliebiaoq",
        "wodetixings",
        "kankantixingq",
        "younaxietixings",
        "txlbs",
        "wdtxx",
        "kktxx",
        "ynxts",
    ):
        assert _probe_hits(probe) == [], f"字母延续/近形词误触发：{probe!r} 命中 {_probe_hits(probe)}"


# ---------------------------------------------------------------------------
# 3.5) divination 三守卫对拼音同口径（劫持守卫不破坏）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sample", DIVINATION_HIJACK_SAMPLES)
def test_divination_hijack_samples_still_fall_to_chat(sample: str) -> None:
    assert not is_divination_command(sample), f"劫持样例被拼音入表波误改：{sample!r}"


@pytest.mark.parametrize(
    "sample",
    [
        "zhanbu https://example.com/tarot",
        "taluo http://x.test/a",
        "paipan https://example.com/bazi",
    ],
)
def test_divination_pinyin_url_guard(sample: str) -> None:
    """守卫②：拼音词同样受 URL 守卫（链接让位内容解析）。"""
    assert not is_divination_command(sample), f"URL 守卫对拼音失效：{sample!r}"


def test_divination_pinyin_length_guard() -> None:
    """守卫②：>32 字不触发；32 字（含）以内独立成词照常（对齐既有口径）。"""
    assert not is_divination_command("taluo " + "a" * 27)  # 33 字
    assert is_divination_command("taluo " + "a" * 26)  # 32 字
    assert not is_divination_command("zhanbu " + "1998年3月2日早上7点" * 3)


def test_divination_idiom_exclusion_unaffected_by_pinyin() -> None:
    """守卫③：惯用语排除表在拼音入表后仍一票否决（含压缩形态）。"""
    for sample in ("这事八字还没一撇呢", "八字还没一撇", "八字没一撇", "别急，八字还没一撇呢"):
        assert not is_divination_command(sample), f"惯用语误触发：{sample!r}"


@pytest.mark.parametrize("word,kind", DIVINATION_INTENT_KINDS, ids=lambda x: str(x))
def test_divination_pinyin_route_implies_intent(word: str, kind: str) -> None:
    """路由⇒意图承接不变式：拼音词命中后 parse 必产出正确子意图。"""
    intent = parse_divination_intent(word)
    assert intent is not None, f"路由命中但意图解析不承接：{word!r}"
    assert intent.kind == kind, f"{word!r} 子意图错位：期望 {kind}，实得 {intent.kind}"


# ---------------------------------------------------------------------------
# 3.6) reminder 信号词面拼音锁定为零命中（白名单外解析器未同步，防半吊子）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "probe",
    [
        "tixing",
        "jiaowo",
        "jidejiao",
        "12点tixing写作业",
        "明天早上8点jiaowo起床",
        "半小时后jidejiao我去看汤",
    ],
)
def test_reminder_signal_face_pinyin_stays_dead(probe: str) -> None:
    """信号词面拼音依赖 character/reminders._REMIND_SIGNAL_RE（白名单外）同步，
    本批只入表列表查询面——信号面拼音必须零命中，防止路由判定半承接。"""
    assert _probe_hits(probe) == [], f"信号词面拼音提前生效：{probe!r} 命中 {_probe_hits(probe)}"


# ---------------------------------------------------------------------------
# 4) 零回归：简体原词 + echo help aliases 拼音可见（本批 + 二批顺延）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cap,probe",
    [
        ("bot.fx", "汇率"),
        ("bot.fx", "美元兑人民币"),
        ("bot.reminder", "提醒列表"),
        ("bot.reminder", "我的提醒"),
        ("bot.reminder", "12点提醒我写作业"),
        ("bot.divination", "占卜"),
        ("bot.divination", "塔罗"),
        ("bot.divination", "排盘"),
        ("bot.divination", "金钱卦"),
        ("bot.divination", "八字 1998年3月2日早上7点"),
    ],
    ids=lambda x: str(x),
)
def test_simplified_originals_still_hit(cap: str, probe: str) -> None:
    assert _detector_of(cap)(probe), f"简体原词回归：{cap} 不再命中 {probe!r}"


def _help_aliases() -> dict[str, tuple[str, ...]]:
    from plugins.bot_unified_runtime.capabilities import echo

    return {str(entry["topic"]): tuple(entry.get("aliases", ())) for entry in echo._HELP_ENTRIES}


@pytest.mark.parametrize(
    "topic,pinyin_aliases",
    [
        # 本批三能力（只收已入表词；hl/dh/bz/zb/sz/sm 真冲突缩写不进 help）
        ("汇率", ("huilv",)),
        ("提醒", ("tixingliebiao", "txlb", "wodetixing", "wdtx", "kankantixing", "kktx", "younaxietixing", "ynxt")),
        ("占卜", ("zhanbu", "taluo", "tl", "suanming", "suangua", "sg", "qigua", "qg")),
        # 第二批五能力顺延（第二批因 echo 占用顺延到本批）
        ("点歌", ("diangemoshi", "dgms")),
        ("天气", ("tianqi", "tq", "chatianqi", "ctq")),
        ("好感度", ("haogandu", "hgd", "haoganchakan", "hgck", "chaxunhaogan", "cxhg")),
        ("表情", ("biaoqing", "biaoqingbao", "bqb", "biaoqingshengcheng", "bqsc")),
        ("偷表情", ("toubiaoqing", "tbq", "toubiaoqingbao", "tbqb")),
        ("表情收库", ("biaoqingku", "bqk")),
    ],
    ids=lambda x: str(x),
)
def test_help_aliases_announce_pinyin(topic: str, pinyin_aliases: tuple[str, ...]) -> None:
    aliases = _help_aliases()[topic]
    missing = [alias for alias in pinyin_aliases if alias not in aliases]
    assert missing == [], f"help topic {topic!r} aliases 缺拼音别名：{missing}"
