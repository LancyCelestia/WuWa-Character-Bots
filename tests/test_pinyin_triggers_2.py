"""T-Spec T1.5/T1.6 第二批：music/affinity/weather/meme/meme_library 拼音触发词回归。

第一批（test_pinyin_triggers.py）四层断言照抄，词表来源
``.superpowers/sdd/2026-09-12-shorekeeper-global-audit/pinyin-mapping-draft.json``
终审子集，入表/放弃依据见同目录 ``fix-py2-report.md``：

1. 命中：每能力拼音词（全拼+查重无冲突缩写）命中自身 ``is_*`` 检测器；
2. 唯一性：拼音词探针跑全部 ``is_*`` 检测器零跨能力冲突（真冲突缩写不启用）；
3. 词边界：双侧 ASCII 胶合与字母延续零命中；
4. 守卫parity + 零回归：weather 陈述句/口语守卫对拼音同口径、affinity
   独立成词约束对拼音同口径、简繁原词行为不变。

echo.py/divination.py 的拼音别名与 help aliases 顺延（文件被并行波占用），
本批不出现在任何断言里。
"""

from __future__ import annotations

import importlib

import pytest

from scripts.extract_trigger_words import build_inventory

# ---------------------------------------------------------------------------
# 被测词表：(能力 id, 拼音词, 行为探针)。探针口径与第一批一致：
# query 必填的命令（天气）带城市后缀，整句触发词（好感度/表情族/偷表情族）裸发。
# ---------------------------------------------------------------------------

PINYIN_HITS: list[tuple[str, str, str]] = [
    # 好感度（affinity：独立成词约束对拼音镜像，见 test_affinity_guard_parity）
    ("bot.affinity", "haogandu", "haogandu"),
    ("bot.affinity", "hgd", "hgd"),
    ("bot.affinity", "haoganzhi", "haoganzhi"),
    ("bot.affinity", "hgz", "hgz"),
    ("bot.affinity", "haoganchakan", "haoganchakan"),
    ("bot.affinity", "hgck", "hgck"),
    ("bot.affinity", "chaxunhaogan", "chaxunhaogan"),
    ("bot.affinity", "cxhg", "cxhg"),
    ("bot.affinity", "qinmidu", "qinmidu"),  # 親密度 同音覆盖
    ("bot.affinity", "qmd", "qmd"),
    ("bot.affinity", "haogan", "haogan"),
    # 天气（weather：query 必填，裸拼音词由既有 plausibility 守卫拒绝）
    ("bot.weather", "tianqi", "tianqi 北京"),
    ("bot.weather", "tq", "tq 北京"),
    ("bot.weather", "chatianqi", "chatianqi 北京"),
    ("bot.weather", "ctq", "ctq 北京"),
    # 表情包生成（meme：带头词族；帮助/用法/菜单/列表 tail 词族不拼音化）
    ("bot.meme", "biaoqing", "biaoqing"),
    ("bot.meme", "biaoqingbao", "biaoqingbao"),
    ("bot.meme", "bqb", "bqb"),
    ("bot.meme", "biaoqingshengcheng", "biaoqingshengcheng"),
    ("bot.meme", "bqsc", "bqsc"),
    ("bot.meme", "biaoqingbaoshengcheng", "biaoqingbaoshengcheng"),
    ("bot.meme", "bqbs", "bqbs"),
    ("bot.meme", "biaoqingzhizuo", "biaoqingzhizuo"),  # 表情製作 同音覆盖
    ("bot.meme", "bqzz", "bqzz"),
    ("bot.meme", "biaoqingbaozhizuo", "biaoqingbaozhizuo"),  # 表情包製作 同音
    ("bot.meme", "bqbz", "bqbz"),
    ("bot.meme", "biaoqingchansheng", "biaoqingchansheng"),
    ("bot.meme", "bqcs", "bqcs"),
    ("bot.meme", "biaoqingbaochansheng", "biaoqingbaochansheng"),  # 表情包產生 同音
    ("bot.meme", "bqbc", "bqbc"),
    # 表情库（meme_library：偷图/偷表情族 + 随机/统计/抽签/库）
    ("bot.meme_library", "toutu", "toutu"),  # 偷圖/偷图 同音覆盖
    ("bot.meme_library", "tt", "tt"),
    ("bot.meme_library", "toubiaoqing", "toubiaoqing"),
    ("bot.meme_library", "tbq", "tbq"),
    ("bot.meme_library", "toubiaoqingbao", "toubiaoqingbao"),
    ("bot.meme_library", "tbqb", "tbqb"),
    ("bot.meme_library", "biaoqingsuiji", "biaoqingsuiji"),
    ("bot.meme_library", "bqsj", "bqsj"),
    ("bot.meme_library", "suijibiaoqing", "suijibiaoqing"),
    ("bot.meme_library", "suijibiaoqingbao", "suijibiaoqingbao"),
    ("bot.meme_library", "sjbq", "sjbq"),  # 随机表情/随机表情包 同能力共享缩写
    ("bot.meme_library", "biaoqingchouqian", "biaoqingchouqian"),
    ("bot.meme_library", "bqcq", "bqcq"),
    ("bot.meme_library", "biaoqingku", "biaoqingku"),
    ("bot.meme_library", "bqk", "bqk"),
    ("bot.meme_library", "biaoqingtongji", "biaoqingtongji"),
    ("bot.meme_library", "bqtj", "bqtj"),
]

# music mode 词族（_MODE_COMMAND_RE；主命令 diange/dg 右边界让渡语义锁定）。
# inventory 只收 base_router 直连检测器，mode 检测器单独 import 断言。
MODE_HITS: list[tuple[str, str]] = [
    ("diangemoshi", "diangemoshi"),
    ("dgms", "dgms 卡片"),
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


@pytest.mark.parametrize("word,probe", MODE_HITS, ids=lambda x: str(x))
def test_music_mode_pinyin_hits_mode_command(word: str, probe: str) -> None:
    from plugins.bot_unified_runtime.domains.music.capabilities import music

    assert music.is_music_mode_command(probe), f"mode 拼音词未命中：{word!r}（探针 {probe!r}）"
    # 让渡语义：mode 拼音短语不得被点歌主命令当歌名抢走。
    assert not music.is_music_command("diangemoshi"), "主命令抢匹配 mode 裸词 diangemoshi"
    assert not music.is_music_command("dgms 卡片"), "主命令抢匹配 dgms 短语"
    # bot.music_mode 即 mode 词族属主能力（与 bot.music 同族），
    # 其余能力零命中。
    foreign = [cap for cap in _probe_hits(probe) if cap not in {"bot.music", "bot.music_mode"}]
    assert foreign == [], f"mode 拼音词跨能力冲突：{probe!r} 命中 {foreign}"


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


def test_letter_extensions_do_not_hit() -> None:
    """防子串胶合样例（T-Spec 指定）：字母延续不得触发任一能力。"""
    for probe in (
        "diangemoshiq",
        "dgmss",
        "haogandux",
        "haogansuanfa",  # affinity 独立成词约束：拼音 arg 词族未启用
        "tqbeijing",
        "ctqxx",
        "biaoqingbaox",
        "bqbcs",
        "toutuq",
        "tbqq",
        "sjbqs",
        "biaoqingkuq",
    ):
        assert _probe_hits(probe) == [], f"字母延续误触发：{probe!r} 命中 {_probe_hits(probe)}"


# ---------------------------------------------------------------------------
# 4) 守卫 parity + 零回归：简繁原词行为不变
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "probe",
    [
        "tianqi",  # 裸拼音无城市 → 既有 plausibility 守卫拒绝（与裸「天气」同口径）
        "tq",
        "chatianqi",
        "ctq",
        "tq 今天",  # 口语守卫 parity（「天气 今天」同拒）
        "tq 预报说下雨",  # 陈述句守卫 parity（「天气 预报说下雨」同拒）
    ],
)
def test_weather_pinyin_guard_parity(probe: str) -> None:
    assert _probe_hits(probe) == [], f"weather 守卫未拦拼音探针：{probe!r} 命中 {_probe_hits(probe)}"


def test_traditional_mode_word_still_hits() -> None:
    """簡繁零回归：點歌模式 走 mode 检测器（inventory 只收主命令检测器）。"""
    from plugins.bot_unified_runtime.domains.music.capabilities import music

    assert music.is_music_mode_command("點歌模式")


@pytest.mark.parametrize(
    "cap,probe",
    [
        ("bot.music", "點歌 周杰倫"),
        ("bot.affinity", "好感度"),
        ("bot.affinity", "好感 算法"),
        ("bot.affinity", "親密度"),
        ("bot.affinity", "好感查看"),
        ("bot.affinity", "查询好感"),
        ("bot.affinity", "好感值"),
        ("bot.weather", "天氣 北京"),
        ("bot.weather", "查天氣 北京"),
        ("bot.meme", "表情"),
        ("bot.meme", "表情包"),
        ("bot.meme", "表情生成"),
        ("bot.meme", "表情包生成"),
        ("bot.meme", "表情製作"),
        ("bot.meme", "表情包製作"),
        ("bot.meme", "表情产生"),
        ("bot.meme", "表情包產生"),
        ("bot.meme_library", "偷圖"),
        ("bot.meme_library", "偷表情"),
        ("bot.meme_library", "偷表情包"),
        ("bot.meme_library", "表情随机"),
        ("bot.meme_library", "随机表情"),
        ("bot.meme_library", "随机表情包"),
        ("bot.meme_library", "表情抽签"),
        ("bot.meme_library", "表情库"),
        ("bot.meme_library", "表情统计"),
    ],
    ids=lambda x: str(x),
)
def test_simplified_traditional_originals_still_hit(cap: str, probe: str) -> None:
    assert _detector_of(cap)(probe), f"简繁原词回归：{cap} 不再命中 {probe!r}"
