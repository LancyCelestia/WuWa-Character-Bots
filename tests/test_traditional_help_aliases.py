"""繁體触发词 help 入册回归（fix-trae 波）。

背景：tra2/tra3/tra49 波把繁體触发词落进了路由层词表，但 echo 的
_HELP_ENTRIES aliases（/bot help <词> 解析唯一事实源，META triggers_*
不入 _HELP_ALIAS_MAP）未同步——help 页搜不到这些繁體触发方式。

口径（fix-trae 报告 §一）：
- 范围=任务点名的 6 个 topic（news/randpic/affinity/music/weather/meme_library）；
- 逐 topic 以路由层现词表为准「缺失即补」，含同波对向简体孪生词（点唱/偷图）；
- 断言三件事：①normalize_help_topic 可解析；②词在 aliases 元组（入册）；
  ③topic 归属正确且与其他 topic 别名零冲突（冲突由文档一致性门禁兜底）。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    _HELP_ENTRY_META,
    HELP_ENTRIES,
    normalize_help_topic,
)

# (触发词, 期望 topic)。简繁同列：繁體=路由层新增词形；点唱/偷图=同波对向简体。
TRADITIONAL_HELP_ALIASES: tuple[tuple[str, str], ...] = (
    # news 快報族 10 词（news.py _NEWS_TRIGGER_RE）
    ("快報", "快报"),
    ("早報", "快报"),
    ("晚報", "快报"),
    ("今日熱點", "快报"),
    ("科技新聞", "快报"),
    ("AI新聞", "快报"),
    ("AI快報", "快报"),
    ("財經新聞", "快报"),
    ("財經快報", "快报"),
    ("國際新聞", "快报"),
    # randpic（randpic.py DEFAULT_TRIGGER_WORDS）
    ("隨機圖", "随机图"),
    ("來張圖", "随机图"),
    # affinity（affinity.py _COMMAND_RE：親密度=tra3、查詢好感=tra49）
    ("親密度", "好感度"),
    ("查詢好感", "好感度"),
    # music（music.py _COMMAND_RE：點唱=tra3；点唱=同波对向简体）
    ("點唱", "点歌"),
    ("点唱", "点歌"),
    # weather（weather.py _WEATHER_RE：天氣預報=tra3；天氣/查天氣=既有繁體形）
    ("天氣預報", "天气"),
    ("天氣", "天气"),
    ("查天氣", "天气"),
    # meme_library（meme_library.py _COMMAND_RE：偷圖/偷图=双向补齐；
    # 表情隨機族=tra49）
    ("偷圖", "偷表情"),
    ("偷图", "偷表情"),
    ("表情隨機", "偷表情"),
    ("隨機表情", "偷表情"),
    ("隨機表情包", "偷表情"),
    ("表情抽籤", "偷表情"),
)

# META triggers 字段镜像孪生词（fix-trae 口径：简体孪生已在该字段的，繁體成对补）。
META_TRIGGER_MIRRORS: tuple[tuple[str, str, str], ...] = (
    # (topic, 字段, 词)
    ("快报", "triggers_nickname", "早報"),
    ("快报", "triggers_nickname", "晚報"),
    ("快报", "triggers_nickname", "今日熱點"),
    ("快报", "triggers_nickname", "科技新聞"),
    ("快报", "triggers_nickname", "AI新聞"),
    ("快报", "triggers_nickname", "AI快報"),
    ("快报", "triggers_nickname", "財經快報"),
    ("快报", "triggers_nl", "快報"),
    ("快报", "triggers_nl", "今日熱點"),
    ("快报", "triggers_nl", "科技新聞"),
    ("快报", "triggers_nl", "AI新聞"),
    ("快报", "triggers_nl", "財經快報"),
    ("快报", "triggers_nl", "國際新聞"),
    ("随机图", "triggers_nl", "隨機圖"),
    ("随机图", "triggers_nl", "來張圖"),
    ("好感度", "triggers_nickname", "查詢好感"),
    ("好感度", "triggers_nl", "親密度"),
    ("好感度", "triggers_nl", "查詢好感"),
    ("点歌", "triggers_nickname", "点唱"),
    ("偷表情", "triggers_nickname", "偷圖"),
    ("偷表情", "triggers_nickname", "偷图"),
    ("偷表情", "triggers_nickname", "表情隨機"),
    ("偷表情", "triggers_nickname", "隨機表情"),
    ("偷表情", "triggers_nickname", "隨機表情包"),
    ("偷表情", "triggers_nickname", "表情抽籤"),
)

_ENTRIES_BY_TOPIC = {entry["topic"]: entry for entry in HELP_ENTRIES}


def test_traditional_trigger_resolves_to_help_topic() -> None:
    """/bot help <繁體触发词> 必须能落到对应 topic（_HELP_ALIAS_MAP 主口径）。"""
    for word, topic in TRADITIONAL_HELP_ALIASES:
        assert normalize_help_topic(word) == topic, word


@pytest.mark.parametrize("word,topic", TRADITIONAL_HELP_ALIASES, ids=lambda x: str(x))
def test_traditional_word_registered_in_entry_aliases(word: str, topic: str) -> None:
    """繁體词必须写入 aliases 元组本体（仅进 META 不入 _HELP_ALIAS_MAP，不算入册）。"""
    entry = _ENTRIES_BY_TOPIC[topic]
    assert word in (entry.get("aliases") or ()), (topic, word)


@pytest.mark.parametrize("topic,field,word", META_TRIGGER_MIRRORS, ids=lambda x: str(x))
def test_meta_trigger_fields_mirror_traditional_words(topic: str, field: str, word: str) -> None:
    """META triggers 类字段与 aliases 同步（任务口径：若含词表也同步）。"""
    meta = _HELP_ENTRY_META.get(topic) or {}
    assert word in (meta.get(field) or ()), (topic, field, word)
