"""help 搜索结构修复 + tra49 剩余 topic 繁體别名收口回归（fix-trae2 波）。

背景（fix-trae 报告 §一 + T-Spec T5 联动深化）：
- `_HELP_ALIAS_MAP` 此前只从 `entry["aliases"]` 构建，`_HELP_ENTRY_META` 的
  triggers_nickname/triggers_rl 触发词「深度页元数据看得见、help 查询搜不到」
  ——aliases 漏登即搜不到的复发模式由此而来；
- tra49 波落路由的其余 topic（Epic/fx/占卜/提醒/订阅/草稿/萌百/凭据/表情/搜图/
  状态/暂停/设置，按 tra49 报告实词 + 路由层源码逐词复核）繁體词未入 echo aliases。

口径：
- 结构：META 触发词全部纳入可搜索集合；aliases 永远优先（setdefault 不覆盖），
  既有命中与管理员隔离零变化；
- 繁體：逐 topic「路由层已有触发词 vs aliases——缺失即补」，含对向简体孪生
  （点唱/偷图 先例）；帮助/昵称按任务指令跳过（runtime MODULE_ALIASES 已收口）。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.capabilities.echo import (
    _HELP_ALIAS_MAP,
    _HELP_ENTRY_META,
    HELP_ENTRIES,
    normalize_help_topic,
)

# ---------------------------------------------------------------------------
# 一、结构修复：META 触发词可被 help 搜索命中
# ---------------------------------------------------------------------------

# (查询词, 期望 topic)：全部是 META 已登记、且此前不在任何 aliases 的词形。
META_ONLY_SEARCHABLE: tuple[tuple[str, str], ...] = (
    ("查询", "状态"),
    ("查询日志", "日志"),
    ("查询订阅", "订阅"),
    ("点歌模式", "点歌"),
    ("对话验收", "对话"),
    ("提醒列表", "提醒"),
    ("表情帮助", "表情"),
    ("随机来张表情", "偷表情"),
    ("清理历史", "历史"),
)

# tianqi 类拼音触发词（aliases 侧既有）与 META 繁體词形（本批结构修复后可达），
# 同属「天气」topic 可搜索集合——防「看得见搜不到」的代表性样例。
WEATHER_SEARCH_SAMPLES: tuple[str, ...] = ("tianqi", "tq", "天氣", "查天氣", "天氣預報", "weather")


def test_meta_only_trigger_words_resolve_to_topic() -> None:
    """META 触发词（未入 aliases 的）必须能经 help 搜索落到对应 topic。"""
    for word, topic in META_ONLY_SEARCHABLE:
        assert normalize_help_topic(word) == topic, word


def test_weather_trigger_samples_all_searchable() -> None:
    """「tianqi」类触发词能找到天气 topic：拼音/简体/繁體/META 词形同集合。"""
    for word in WEATHER_SEARCH_SAMPLES:
        assert normalize_help_topic(word) == "天气", word


def test_every_meta_trigger_word_is_searchable() -> None:
    """全量不变式：每个 topic 的 META 触发词都必须能解析到某个 topic。

    - 未被任何 aliases 认领的 META 词必须解析回本 topic；
    - 被 aliases（或先处理的 META）认领的词保持既有认领结果（aliases 优先）。
    """
    alias_claims: dict[str, str] = {}
    for entry in HELP_ENTRIES:
        for alias in entry["aliases"]:
            alias_claims[str(alias).lower()] = entry["topic"]
    meta_claims: dict[str, str] = {}
    for entry in HELP_ENTRIES:
        meta = _HELP_ENTRY_META.get(entry["topic"], {})
        for field in ("triggers_nickname", "triggers_nl"):
            for word in meta.get(field) or ():
                key = str(word).strip().lower()
                got = normalize_help_topic(word)
                assert got is not None, (entry["topic"], field, word)
                if key in alias_claims:
                    assert got == alias_claims[key], (entry["topic"], field, word, got)
                else:
                    assert got == meta_claims.get(key, entry["topic"]), (
                        entry["topic"],
                        field,
                        word,
                        got,
                    )
                meta_claims.setdefault(key, got)


def test_alias_map_equals_aliases_union_meta_triggers() -> None:
    """运行时映射 = aliases ∪ META 触发词（键集等势，aliases 优先不覆盖）。"""
    expected: set[str] = set()
    for entry in HELP_ENTRIES:
        for alias in entry["aliases"]:
            expected.add(str(alias).lower())
        for field in ("triggers_nickname", "triggers_nl"):
            for word in _HELP_ENTRY_META.get(entry["topic"], {}).get(field) or ():
                expected.add(str(word).strip().lower())
    assert set(_HELP_ALIAS_MAP) == expected
    # aliases 认领逐键不变（防静默覆盖）。
    for entry in HELP_ENTRIES:
        for alias in entry["aliases"]:
            assert _HELP_ALIAS_MAP[str(alias).lower()] == entry["topic"], alias


# ---------------------------------------------------------------------------
# 二、tra49 剩余 topic 繁體别名收口（逐词路由层源码取证，见各分组注释）
# ---------------------------------------------------------------------------

# (触发词, 期望 topic)。繁體=tra49 波（或既有）路由层词形；对向简体孪生同列。
TRA49_HELP_ALIASES: tuple[tuple[str, str], ...] = (
    # Epic（epic.py _COMMAND_RE：免費遊戲/遊戲免費/steam免費=tra49；简体孪生）
    ("免費遊戲", "Epic"),
    ("遊戲免費", "Epic"),
    ("steam免費", "Epic"),
    ("游戏免费", "Epic"),
    ("steam免费", "Epic"),
    ("steam 免费", "Epic"),
    # fx（fx.py _FX_CONVERT_RE：换算|換算；币名语境门在路由层，help 只管可搜）
    ("换算", "汇率"),
    ("換算", "汇率"),
    # 占卜（divination.py：塔羅/排盤/命盤/搖卦/今日塔羅/今天塔羅/塔羅三張=tra49；简体孪生）
    ("塔羅", "占卜"),
    ("排盤", "占卜"),
    ("排盘", "占卜"),
    ("命盤", "占卜"),
    ("命盘", "占卜"),
    ("搖卦", "占卜"),
    ("摇卦", "占卜"),
    ("今日塔羅", "占卜"),
    ("今日塔罗", "占卜"),
    ("今天塔羅", "占卜"),
    ("今天塔罗", "占卜"),
    ("塔羅三張", "占卜"),
    ("塔罗三张", "占卜"),
    # 提醒（reminder.py/_REMIND_SIGNAL_RE/_CLEAN_RE：記得叫=tra49；简体孪生）
    ("记得叫", "提醒"),
    ("記得叫", "提醒"),
    # 订阅（subscribe.py _SUBSCRIBE_ZH_RE：訂閱=tra49 前缀）
    ("訂閱", "订阅"),
    # 草稿（auto_send/parser.py _COMMAND_RE：報存=tra49 整链；简体孪生）
    ("报存", "草稿"),
    ("報存", "草稿"),
    # 萌娘百科（moegirl.py _QUESTION_STRIP_PREFIXES/SUFFIXES：是誰/是什麼/介紹一下=tra49）
    ("是誰", "萌娘百科"),
    ("是什麼", "萌娘百科"),
    ("介紹一下", "萌娘百科"),
    ("是谁", "萌娘百科"),
    ("是什么", "萌娘百科"),
    ("介绍一下", "萌娘百科"),
    # 凭据（platform_credentials.py _COMMAND_ALIASES：憑據/登錄憑證=tra49、憑證/凭证/登录凭证 同表）
    ("凭证", "凭据"),
    ("憑證", "凭据"),
    ("憑據", "凭据"),
    ("登录凭证", "凭据"),
    ("登錄憑證", "凭据"),
    # 表情（meme.py _COMMAND_RE：表情製作/表情包製作/表情產生/表情包產生；简体孪生）
    ("表情製作", "表情"),
    ("表情包製作", "表情"),
    ("表情產生", "表情"),
    ("表情包產生", "表情"),
    ("表情制作", "表情"),
    ("表情包制作", "表情"),
    ("表情产生", "表情"),
    ("表情包产生", "表情"),
    # 搜图（__init__.py 旁路 matcher：搜圖=tra49，与简体同口径）
    ("搜圖", "搜图"),
    # 状态/暂停/设置（runtime/aliases.py MODULE_ALIASES 設置/參數 + DEFAULT_VERB_MAP 狀態/暫停/繼續=tra49）
    ("狀態", "状态"),
    ("暫停", "暂停"),
    ("繼續", "暂停"),
    ("继续", "暂停"),
    ("設置", "设置"),
    ("參數", "设置"),
)

# META triggers 字段镜像（fix-trae 口径延续：每个新别名词在 META 同步登记）。
META_TRA49_MIRRORS: tuple[tuple[str, str, str], ...] = (
    ("Epic", "triggers_nickname", "免費遊戲"),
    ("Epic", "triggers_nickname", "遊戲免費"),
    ("Epic", "triggers_nickname", "steam免費"),
    ("Epic", "triggers_nickname", "steam 免费"),
    ("Epic", "triggers_nl", "免費遊戲"),
    ("汇率", "triggers_nl", "换算"),
    ("汇率", "triggers_nl", "換算"),
    ("占卜", "triggers_nl", "塔羅"),
    ("占卜", "triggers_nl", "排盘"),
    ("占卜", "triggers_nl", "排盤"),
    ("占卜", "triggers_nl", "命盘"),
    ("占卜", "triggers_nl", "命盤"),
    ("占卜", "triggers_nl", "摇卦"),
    ("占卜", "triggers_nl", "搖卦"),
    ("占卜", "triggers_nl", "今日塔罗"),
    ("占卜", "triggers_nl", "今日塔羅"),
    ("占卜", "triggers_nl", "今天塔罗"),
    ("占卜", "triggers_nl", "今天塔羅"),
    ("占卜", "triggers_nl", "塔罗三张"),
    ("占卜", "triggers_nl", "塔羅三張"),
    ("提醒", "triggers_nl", "记得叫"),
    ("提醒", "triggers_nl", "記得叫"),
    ("订阅", "triggers_nickname", "訂閱"),
    ("草稿", "triggers_nl", "报存"),
    ("草稿", "triggers_nl", "報存"),
    ("萌娘百科", "triggers_nl", "是谁"),
    ("萌娘百科", "triggers_nl", "是誰"),
    ("萌娘百科", "triggers_nl", "是什么"),
    ("萌娘百科", "triggers_nl", "是什麼"),
    ("萌娘百科", "triggers_nl", "介绍一下"),
    ("萌娘百科", "triggers_nl", "介紹一下"),
    ("凭据", "triggers_nickname", "凭证"),
    ("凭据", "triggers_nickname", "憑證"),
    ("凭据", "triggers_nickname", "憑據"),
    ("凭据", "triggers_nickname", "登录凭证"),
    ("凭据", "triggers_nickname", "登錄憑證"),
    ("表情", "triggers_nickname", "表情製作"),
    ("表情", "triggers_nickname", "表情包製作"),
    ("表情", "triggers_nickname", "表情產生"),
    ("表情", "triggers_nickname", "表情包產生"),
    ("表情", "triggers_nickname", "表情制作"),
    ("表情", "triggers_nickname", "表情包制作"),
    ("表情", "triggers_nickname", "表情产生"),
    ("表情", "triggers_nickname", "表情包产生"),
    ("搜图", "triggers_nickname", "搜圖"),
    ("状态", "triggers_nickname", "狀態"),
    ("暂停", "triggers_nickname", "暫停"),
    ("暂停", "triggers_nickname", "繼續"),
    ("设置", "triggers_nickname", "設置"),
    ("设置", "triggers_nickname", "參數"),
)

_ENTRIES_BY_TOPIC = {entry["topic"]: entry for entry in HELP_ENTRIES}


def test_tra49_trigger_resolves_to_help_topic() -> None:
    """/bot help <繁體触发词> 必须能落到对应 topic（_HELP_ALIAS_MAP 主口径）。"""
    for word, topic in TRA49_HELP_ALIASES:
        assert normalize_help_topic(word) == topic, word


@pytest.mark.parametrize("word,topic", TRA49_HELP_ALIASES, ids=lambda x: str(x))
def test_tra49_word_registered_in_entry_aliases(word: str, topic: str) -> None:
    """繁體词必须写入 aliases 元组本体（入册，非仅 META）。"""
    entry = _ENTRIES_BY_TOPIC[topic]
    assert word in (entry.get("aliases") or ()), (topic, word)


@pytest.mark.parametrize("topic,field,word", META_TRA49_MIRRORS, ids=lambda x: str(x))
def test_meta_trigger_fields_mirror_tra49_words(topic: str, field: str, word: str) -> None:
    """META triggers 类字段与 aliases 同步（fix-trae 口径延续）。"""
    meta = _HELP_ENTRY_META.get(topic) or {}
    assert word in (meta.get(field) or ()), (topic, field, word)


def test_qiuqian_registered_and_searchable() -> None:
    """求籤/求签 另立收口：aliases 入册，help 搜索可命中占卜 topic。"""
    assert _HELP_ALIAS_MAP["求籤"] == "占卜"
    assert _HELP_ALIAS_MAP["求签"] == "占卜"
