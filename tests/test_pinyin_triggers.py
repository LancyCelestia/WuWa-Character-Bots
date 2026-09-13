"""T-Spec T1.5/T1.6 第一批：全拼与拼音缩写触发词回归（拼音入表波）。

四层断言（词表来源：pinyin-mapping-draft.json 终审子集，入表/放弃依据见
``.superpowers/sdd/2026-09-12-shorekeeper-global-audit/fix-py1-report.md``）：

1. 命中：每能力拼音词（全拼+查重无冲突缩写）命中自身 ``is_*`` 检测器；
2. 唯一性：拼音词探针跑全部 ``is_*`` 检测器唯一命中所属能力（冲突零新增）；
3. 词边界：双侧 ASCII 胶合探针（``qq<word>`` / ``<word>qq`` / ``dianger``
   类字母延续）零命中——拼音词与英文词同守 ``_alias_hit`` 纪律；
4. 零回归：简体原词行为不变 + echo help aliases 拼音别名可见。

禁碰域（weather/fx/reminder/affinity/divination/meme 族，文件被并行波占用）
本批不入表，对应拼音词不出现在任何断言里。
"""

from __future__ import annotations

import importlib

import pytest

from scripts.extract_trigger_words import build_inventory

# ---------------------------------------------------------------------------
# 被测词表：(能力 id, 拼音词, 行为探针)。
# 探针口径与 extract_trigger_words.verify_word 对齐：query 必填的命令
# （点歌/菜谱/维基/萌百）带后缀词，整句触发词（行情/快报/随机图…）裸发。
# ---------------------------------------------------------------------------

PINYIN_HITS: list[tuple[str, str, str]] = [
    # 点歌（music._COMMAND_RE：query 必填）
    ("bot.music", "diange", "diange 海阔天空"),
    ("bot.music", "dg", "dg 海阔天空"),
    # 行情（market._MARKET_TRIGGER_RE：整句短文本）
    ("bot.market", "hangqing", "hangqing"),
    ("bot.market", "hq", "hq"),
    ("bot.market", "gushi", "gushi"),
    ("bot.market", "gs", "gs"),
    ("bot.market", "dapan", "dapan"),
    ("bot.market", "dp", "dp"),
    ("bot.market", "guzhi", "guzhi"),
    ("bot.market", "quanqiugushi", "quanqiugushi"),
    # 个股（stocks._STOCK_HINT_RE：显式股票词直通）
    ("bot.stocks", "gujia", "gujia"),
    ("bot.stocks", "gj", "gj"),
    ("bot.stocks", "gupiao", "gupiao"),
    ("bot.stocks", "gupiaojiage", "gupiaojiage"),
    ("bot.stocks", "gegu", "gegu"),
    # 快报（news._NEWS_TRIGGER_RE：整句短文本）
    ("bot.news", "kuaibao", "kuaibao"),
    ("bot.news", "kb", "kb"),
    ("bot.news", "zaobao", "zaobao"),
    ("bot.news", "wanbao", "wanbao"),
    ("bot.news", "jinrikuaibao", "jinrikuaibao"),
    ("bot.news", "jrkb", "jrkb"),
    ("bot.news", "jinriredian", "jinriredian"),
    ("bot.news", "jrrd", "jrrd"),
    ("bot.news", "kejixinwen", "kejixinwen"),
    ("bot.news", "kjxw", "kjxw"),
    ("bot.news", "caijingxinwen", "caijingxinwen"),
    ("bot.news", "cjxw", "cjxw"),
    ("bot.news", "caijingkuaibao", "caijingkuaibao"),
    ("bot.news", "cjkb", "cjkb"),
    ("bot.news", "guojixinwen", "guojixinwen"),
    ("bot.news", "gjxw", "gjxw"),
    ("bot.news", "aixinwen", "aixinwen"),
    ("bot.news", "axw", "axw"),
    ("bot.news", "aikuaibao", "aikuaibao"),
    ("bot.news", "akb", "akb"),
    # 随机图（randpic.DEFAULT_TRIGGER_WORDS：整句或前缀+标点）
    ("bot.randpic", "suijitu", "suijitu"),
    ("bot.randpic", "sjt", "sjt"),
    ("bot.randpic", "laizhangtu", "laizhangtu"),
    ("bot.randpic", "lzt", "lzt"),
    # 吃什么（eat._EAT_RE：裸词即命中）
    ("bot.eat", "chishenme", "chishenme"),
    ("bot.eat", "csm", "csm"),
    # 菜谱（eat._RECIPE_RE：菜名必填）
    ("bot.eat", "caipu", "caipu 红烧肉"),
    ("bot.eat", "cp", "cp 红烧肉"),
    ("bot.eat", "zenmezuo", "zenmezuo 红烧肉"),
    ("bot.eat", "zmz", "zmz 红烧肉"),
    # 历史上的今天（today_history._QUERY_RE：无门槛 / _SHORT_RE：带斜杠）
    ("bot.today_history", "lishishangdejintian", "lishishangdejintian"),
    ("bot.today_history", "lssd", "lssd"),
    ("bot.today_history", "jinrilishi", "/jinrilishi"),
    ("bot.today_history", "jrls", "/jrls"),
    ("bot.today_history", "lishi", "/lishi"),
    ("bot.today_history", "ls", "/ls"),
    # 维基（wiki._COMMAND_RE：词条必填）
    ("bot.wiki", "weiji", "weiji 鸣潮"),
    ("bot.wiki", "wjbk", "wjbk 鸣潮"),
    # 萌娘百科（moegirl._COMMAND_RE：词条必填）
    ("bot.moegirl", "mengbai", "mengbai 初音未来"),
    ("bot.moegirl", "mb", "mb 初音未来"),
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
    """取该能力任一命中探针的检测器（词表按能力分置，命中者即所属）。"""

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


def test_dianger_style_extensions_do_not_hit() -> None:
    """防子串胶合样例（T-Spec 指定）：dianger 类字母延续不得触发点歌。"""
    for probe in ("dianger", "dgs", "hqs", "kuaibaoer", "suijitus"):
        assert _probe_hits(probe) == [], f"字母延续误触发：{probe!r} 命中 {_probe_hits(probe)}"


# ---------------------------------------------------------------------------
# 4) 零回归：简体原词 + echo help aliases 拼音可见
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cap,probe",
    [
        ("bot.music", "点歌 海阔天空"),
        ("bot.market", "行情"),
        ("bot.market", "美股行情"),
        ("bot.stocks", "股价 英伟达"),
        ("bot.news", "快报"),
        ("bot.randpic", "随机图"),
        ("bot.eat", "吃什么"),
        ("bot.eat", "菜谱 红烧肉"),
        ("bot.today_history", "历史上的今天"),
        ("bot.wiki", "维基 鸣潮"),
        ("bot.moegirl", "萌百 初音未来"),
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
        ("点歌", ("diange", "dg")),
        ("行情", ("hangqing", "hq")),
        ("个股行情", ("gujia", "gj")),
        ("快报", ("kuaibao", "kb")),
        ("随机图", ("suijitu", "sjt")),
        ("吃什么", ("chishenme", "csm")),
        ("历史上的今天", ("lssd",)),
        ("维基", ("weiji", "wjbk")),
        ("萌娘百科", ("mengbai", "mb")),
    ],
    ids=lambda x: str(x),
)
def test_help_aliases_announce_pinyin(topic: str, pinyin_aliases: tuple[str, ...]) -> None:
    aliases = _help_aliases()[topic]
    missing = [alias for alias in pinyin_aliases if alias not in aliases]
    assert missing == [], f"help topic {topic!r} aliases 缺拼音别名：{missing}"
