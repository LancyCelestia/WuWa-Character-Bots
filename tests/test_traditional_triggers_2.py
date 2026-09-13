"""繁體触发词路由层回归（TRA 第三批：40 缺失词条落地锁定）。

数据来源：.superpowers/sdd/2026-09-12-shorekeeper-global-audit/
traditional-mapping-draft.json（status=missing 全量）+ fix-tra49-report.md。
只锁触发层与解析层判定；echo aliases/help 文案（他人在飞）、
DEFAULT_VERB_MAP 的英文族、NL 天气/维基/历史繁體缺口（独立子波）不在本文件。
__init__.py 旁路闭包内联正则（搜圖/暱稱/刪）以源码行断言锁定（不可导入）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.bot_unified_runtime.capabilities.affinity import (
    is_affinity_command,
    parse_affinity_query,
)
from plugins.bot_unified_runtime.capabilities.auto_send.parser import (
    is_auto_send_command_text,
    parse_auto_send_command,
)
from plugins.bot_unified_runtime.capabilities.divination import (
    is_divination_command,
    parse_divination_intent,
)
from plugins.bot_unified_runtime.capabilities.epic import is_epic_command
from plugins.bot_unified_runtime.capabilities.fx import is_fx_command
from plugins.bot_unified_runtime.capabilities.meme import is_meme_command
from plugins.bot_unified_runtime.capabilities.meme_library import (
    is_meme_library_command,
)
from plugins.bot_unified_runtime.capabilities.moegirl import (
    normalize_entity_question,
)
from plugins.bot_unified_runtime.capabilities.platform_credentials import (
    is_cookie_command,
)
from plugins.bot_unified_runtime.capabilities.reminder import is_reminder_command
from plugins.bot_unified_runtime.capabilities.subscribe import (
    is_standalone_subscribe_command,
    is_subscribe_command,
    normalize_subscribe_text,
)
from plugins.bot_unified_runtime.capabilities.subscribe_v2 import _normalize
from plugins.bot_unified_runtime.character.reminders import parse_reminder_intent
from plugins.bot_unified_runtime.contracts import SessionType
from plugins.bot_unified_runtime.runtime.aliases import (
    DEFAULT_VERB_MAP,
    CommandAliasResolver,
    normalize_command_text,
)
from plugins.bot_unified_runtime.runtime.natural_language import (
    detect_natural_command,
)

# ---------------------------------------------------------------- meme：表情產生


def test_meme_traditional_generate_routes() -> None:
    assert is_meme_command("表情產生") is True
    assert is_meme_command("表情包產生") is True


def test_meme_simplified_control_unchanged() -> None:
    assert is_meme_command("表情产生") is True
    assert is_meme_command("表情包生成") is True


# ---------------------------------------------------- meme_library：隨機表情族


@pytest.mark.parametrize(
    "text",
    [
        "表情隨機",
        "隨機表情",
        "隨機表情包",
        "表情抽籤",
        "偷圖",  # 前波已修，防回退
    ],
)
def test_meme_library_traditional_triggers_route(text: str) -> None:
    assert is_meme_library_command(text) is True


def test_meme_library_simplified_controls_unchanged() -> None:
    assert is_meme_library_command("表情随机") is True
    assert is_meme_library_command("随机表情包") is True
    assert is_meme_library_command("表情抽签") is True
    assert is_meme_library_command("偷图") is True


# ---------------------------------------------------------------- epic：免費遊戲族


@pytest.mark.parametrize("text", ["免費遊戲", "遊戲免費", "steam免費"])
def test_epic_traditional_triggers_route(text: str) -> None:
    assert is_epic_command(text) is True


def test_epic_traditional_nl_question_reaches() -> None:
    resolution = detect_natural_command("今天有什麼免費遊戲")
    assert resolution is not None
    assert resolution.capability_id == "bot.epic"


def test_epic_simplified_controls_unchanged() -> None:
    assert is_epic_command("免费游戏") is True
    assert is_epic_command("游戏免费") is True
    assert is_epic_command("steam免费") is True
    # 尾部锚定与简体同口径：问句后缀走 NL 层而非路由层。
    assert is_epic_command("免費遊戲有哪些") is False


# ---------------------------------------------------------------- fx：換算 + 排除表


def test_fx_traditional_convert_with_currency_routes() -> None:
    assert is_fx_command("美元換算") is True
    # 与简体同口径：裸「換算」无币名不触发。
    assert is_fx_command("單位換算") is False


def test_fx_traditional_exclusion_words_suppress_misfire() -> None:
    assert is_fx_command("換匯話術") is False
    assert is_fx_command("美元信用卡積分換匯") is False


def test_fx_simplified_controls_unchanged() -> None:
    assert is_fx_command("美元换算") is True
    assert is_fx_command("换汇话术") is False


# ---------------------------------------------------------------- affinity：查詢好感


def test_affinity_traditional_query_routes() -> None:
    assert is_affinity_command("查詢好感") is True
    assert parse_affinity_query("查詢好感") == ""


def test_affinity_simplified_control_unchanged() -> None:
    assert is_affinity_command("查询好感") is True
    assert is_affinity_command("親密度") is True  # 前波已修，防回退


# ---------------------------------------------------- divination：排盤/命盤/塔羅/搖卦


@pytest.mark.parametrize(
    "text",
    ["排盤", "命盤", "塔羅", "搖卦", "今日塔羅", "塔羅三張"],
)
def test_divination_traditional_triggers_route(text: str) -> None:
    assert is_divination_command(text) is True
    # 命中必承接不变式：路由命中 ⇒ 意图解析必出意图。
    assert parse_divination_intent(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "塔羅牌在哪买",  # 独立成词锚定：贴 CJK 后缀不触发
        "排盤 https://example.com",  # URL 守卫
        "八字還沒一撇",  # 惯用语排除（繁體形与简体同口径）
    ],
)
def test_divination_traditional_three_guards_hold(text: str) -> None:
    assert is_divination_command(text) is False


def test_divination_simplified_controls_unchanged() -> None:
    assert is_divination_command("排盘") is True
    assert is_divination_command("命盘") is True
    assert is_divination_command("塔罗") is True
    assert is_divination_command("摇卦") is True
    assert is_divination_command("塔罗牌在哪买") is False


# ---------------------------------------------------------------- reminder：記得叫


def test_reminder_traditional_signal_reaches() -> None:
    assert parse_reminder_intent("明天8點記得叫我起床") is not None
    assert is_reminder_command("明天8點記得叫我起床") is True


def test_reminder_traditional_time_gate_still_required() -> None:
    # 与简体同口径：信号词 + 无时间表达不建提醒（§7.5 双门保持）。
    assert parse_reminder_intent("記得叫我起床") is None
    assert is_reminder_command("記得叫我起床") is False


def test_reminder_simplified_control_unchanged() -> None:
    assert parse_reminder_intent("明天8点记得叫我起床") is not None


# ---------------------------------------------------------------- subscribe：訂閱族


@pytest.mark.parametrize(
    "text,expected",
    [
        ("訂閱 list", "/bot subscribe list"),
        ("訂閱 刪除 123", "/bot subscribe remove 123"),
        ("訂閱 暫停 123", "/bot subscribe pause 123"),
        ("訂閱 恢復 123", "/bot subscribe resume 123"),
        ("訂閱 繼續 123", "/bot subscribe resume 123"),
        ("訂閱 檢查 123", "/bot subscribe check 123"),
        ("訂閱 狀態", "/bot subscribe status"),
    ],
)
def test_subscribe_traditional_normalizes(text: str, expected: str) -> None:
    assert is_subscribe_command(text) is True
    assert normalize_subscribe_text(text) == expected


def test_subscribe_traditional_guard_unchanged() -> None:
    # 普通句子以「訂閱」开头不吞（与简体「订阅人数」同门）。
    assert is_standalone_subscribe_command("訂閱人數很多") is False


def test_subscribe_v2_prefix_traditional() -> None:
    assert _normalize("訂閱 list") == "subscribe list"
    assert _normalize("/訂閱 list") == "subscribe list"


def test_subscribe_simplified_controls_unchanged() -> None:
    assert normalize_subscribe_text("订阅 删除 123") == "/bot subscribe remove 123"
    assert normalize_subscribe_text("订阅 状态") == "/bot subscribe status"


# ---------------------------------------------------------------- auto_send：報存鏈


def test_auto_send_traditional_chain_routes() -> None:
    assert is_auto_send_command_text("報存 給 A 發郵件，主題：問候") is True
    assert is_auto_send_command_text("報存 給 A 發訊息，內容：早") is True
    intent = parse_auto_send_command(
        "報存 給 阿貝 發郵件，主題：問候，內容：早安",
        actor_sender_id="u1",
        actor_session_id="private:u1",
        actor_session_type=SessionType.PRIVATE,
    )
    assert intent.channel == "email"
    assert intent.subject_instruction == "問候"
    assert intent.content_instruction == "早安"


def test_auto_send_simplified_control_unchanged() -> None:
    assert is_auto_send_command_text("报存 给 A 发邮件") is True
    assert is_auto_send_command_text("报存了三块钱") is False


# ---------------------------------------------------------------- normalize/aliases


@pytest.mark.parametrize(
    "text,expected",
    [
        ("幫助", "help"),
        ("設置", "runtime"),
        ("參數", "runtime"),
    ],
)
def test_normalize_command_text_traditional(text: str, expected: str) -> None:
    assert normalize_command_text(text) == expected


def test_default_verb_map_traditional_twins() -> None:
    resolver = CommandAliasResolver(nicknames=["守岸人"])
    assert resolver.resolve("守岸人幫助") is not None
    assert resolver.resolve("守岸人幫助").capability_id == "bot.help"
    assert resolver.resolve("守岸人查詢好感").capability_id == "bot.affinity"
    assert resolver.resolve("守岸人訂閱").capability_id == "bot.subscribe"
    for verb in ("狀態", "暫停", "繼續"):
        assert verb in DEFAULT_VERB_MAP


# ---------------------------------------------------------------- cookie 旁路


def test_cookie_traditional_aliases_route() -> None:
    assert is_cookie_command("/bot 憑據 status") is True
    assert is_cookie_command("/bot 登錄憑證 status") is True
    assert is_cookie_command("/bot 憑證 status") is True


def test_cookie_simplified_control_unchanged() -> None:
    assert is_cookie_command("/bot 凭证 status") is True
    assert is_cookie_command("/bot cookie status") is True


# ---------------------------------------------------------------- moegirl 問句


@pytest.mark.parametrize(
    "text,expected",
    [
        ("初音未來是誰", "初音未來"),
        ("初音未來是什麼", "初音未來"),
        ("介紹一下初音未來", "初音未來"),
    ],
)
def test_moegirl_traditional_question_strips(text: str, expected: str) -> None:
    assert normalize_entity_question(text) == expected


def test_moegirl_traditional_pronoun_guard_unchanged() -> None:
    assert normalize_entity_question("你是誰") is None


# ---------------------------------------------------------------- NL：幫我/點一首/來首


@pytest.mark.parametrize(
    "text",
    ["幫我來首晴天", "來首晴天", "點一首晴天", "麻煩點一首晴天"],
)
def test_nl_traditional_music_reaches(text: str) -> None:
    resolution = detect_natural_command(text)
    assert resolution is not None
    assert resolution.capability_id == "bot.music"
    assert resolution.normalized_text == "点歌 晴天"


def test_nl_traditional_polite_prefix_plain_question_still_none() -> None:
    # 幫我 入礼貌前缀后，普通闲聊不得被误归命令。
    assert detect_natural_command("幫我看看這個") is None


# ---------------------------------------- __init__ 旁路闭包（源码行锁定，不可导入）


def test_bypass_matcher_traditional_words_present_in_source() -> None:
    source = Path(
        "plugins/bot_unified_runtime/__init__.py"
    ).read_text(encoding="utf-8")
    # 搜圖 旁路 matcher（priority 46）。
    assert "搜图|搜圖" in source
    # 暱稱 admin matcher。
    assert "昵称|暱稱|nickname" in source
    # 群策略动作别名「刪」。
    assert '"刪": "del"' in source
