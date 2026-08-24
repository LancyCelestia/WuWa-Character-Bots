"""群聊回复策略（black1/black2/white1/white2）测试。

语义约定（黑名单是硬否决，优先级从高到低）：
- 黑名单1：所有消息只接收不发送；
- 黑名单2：只有 @它且带指令 才回复（不艾特的斜杠指令也不回）；
- 白名单2：只回 @它 的指令与自然语言；
- 白名单1：开放普通指令、@+指令、自然语言提问与呼出点名；
- 未列出的群：沿用默认策略（指令/@/自动接话抽签）。
同一群同时命中多档时：black1 > black2 > white2 > white1。
"""

from datetime import datetime, timezone

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.policy.gate import PolicySettings, evaluate_policy
from plugins.bot_unified_runtime.runtime.settings import (
    normalize_group_policy_mode,
)


def _group(text, *, mention=False, gid="100"):
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id=f"group:{gid}",
        session_type=SessionType.GROUP,
        sender_id="42",
        group_id=gid,
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=mention,
        message_id="m1",
        timestamp=datetime.now(timezone.utc),
    )


def _settings(**kwargs):
    defaults = dict(
        extra_command_check=lambda text: text.startswith("/") or "帮我" in text,
        natural_chat_check=lambda text: "？" in text or "?" in text or text.endswith("吗"),
    )
    defaults.update(kwargs)
    return PolicySettings(**defaults)


def test_black1_never_replies():
    settings = _settings(group_black1=frozenset({"100"}))
    for text, mention in [("你好", False), ("/bot status", False), ("/天气 杭州", True)]:
        result = evaluate_policy(_group(text, mention=mention), "bot.chat", settings=settings)
        assert result.allowed is False
        assert result.reason == "group_black1"


def test_black2_requires_mention_and_command():
    settings = _settings(group_black2=frozenset({"100"}))
    # 艾特 + 指令 → 放行
    ok = evaluate_policy(_group("/天气 杭州", mention=True), "bot.weather", settings=settings)
    assert ok.allowed is True
    # 不艾特的斜杠指令 → 不回
    plain = evaluate_policy(_group("/天气 杭州", mention=False), "bot.weather", settings=settings)
    assert plain.allowed is False and plain.reason == "group_black2"
    # 艾特但纯聊天（非指令） → 不回
    chat = evaluate_policy(_group("你好", mention=True), "bot.chat", settings=settings)
    assert chat.allowed is False and chat.reason == "group_black2"


def test_white1_allows_commands_mentions_and_natural_questions():
    settings = _settings(group_white1=frozenset({"100"}))
    # 普通指令（不带@）
    assert evaluate_policy(_group("/天气 杭州", mention=False), "bot.weather", settings=settings).allowed is True
    # @ + 聊天
    assert evaluate_policy(_group("你好", mention=True), "bot.chat", settings=settings).allowed is True
    # 自然语言命令（帮我查天气）
    assert evaluate_policy(_group("帮我查天气", mention=False), "bot.weather", settings=settings).allowed is True
    # 自然语言提问（不带@）→ 白名单1放行
    question = evaluate_policy(_group("鸣潮是什么？", mention=False), "bot.chat", settings=settings)
    assert question.allowed is True
    # 呼出点名（名字也算 mentions_bot）
    callout = evaluate_policy(_group("守岸人 在吗", mention=True), "bot.chat", settings=settings)
    assert callout.allowed is True
    # 无信号闲聊仍静默观察
    passive = evaluate_policy(_group("哈哈哈哈", mention=False), "bot.chat", settings=settings)
    assert passive.allowed is False and passive.reason == "passive_group_message"


def test_white2_requires_mention():
    settings = _settings(group_white2=frozenset({"100"}))
    # 不艾特的斜杠指令 → 不回
    plain = evaluate_policy(_group("/天气 杭州", mention=False), "bot.weather", settings=settings)
    assert plain.allowed is False and plain.reason == "group_white2_need_mention"
    # 不艾特的自然语言提问 → 不回
    question = evaluate_policy(_group("鸣潮是什么？", mention=False), "bot.chat", settings=settings)
    assert question.allowed is False and question.reason == "group_white2_need_mention"
    # 艾特 + 指令 / 自然语言 → 放行
    assert evaluate_policy(_group("/天气 杭州", mention=True), "bot.weather", settings=settings).allowed is True
    assert evaluate_policy(_group("守岸人是谁", mention=True), "bot.chat", settings=settings).allowed is True


def test_unlisted_group_uses_default():
    settings = _settings()
    assert evaluate_policy(_group("/天气 杭州", mention=False), "bot.weather", settings=settings).allowed is True
    assert evaluate_policy(_group("你好", mention=True), "bot.chat", settings=settings).allowed is True
    # 未列出的群：自然语言提问默认不主动回复
    passive = evaluate_policy(_group("鸣潮是什么？", mention=False), "bot.chat", settings=settings)
    assert passive.allowed is False
    assert passive.reason == "passive_group_message"


def test_black_overrides_white():
    # black1 与 white1 同群 → black1 静默
    settings = _settings(
        group_black1=frozenset({"100"}), group_white1=frozenset({"100"})
    )
    result = evaluate_policy(_group("/天气 杭州"), "bot.weather", settings=settings)
    assert result.allowed is False and result.reason == "group_black1"

    # black2 与 white1 同群 → 按 black2 规则（不@的指令也不回）
    settings = _settings(
        group_black2=frozenset({"100"}), group_white1=frozenset({"100"})
    )
    plain = evaluate_policy(_group("/天气 杭州"), "bot.weather", settings=settings)
    assert plain.allowed is False and plain.reason == "group_black2"
    ok = evaluate_policy(_group("/天气 杭州", mention=True), "bot.weather", settings=settings)
    assert ok.allowed is True


def test_white2_overrides_white1():
    settings = _settings(
        group_white1=frozenset({"100"}), group_white2=frozenset({"100"})
    )
    plain = evaluate_policy(_group("/天气 杭州"), "bot.weather", settings=settings)
    assert plain.allowed is False and plain.reason == "group_white2_need_mention"


def test_runtime_provider_overrides_static_sets():
    settings = PolicySettings(
        group_black1=frozenset({"100"}),
        group_white1=frozenset({"300"}),
        extra_command_check=lambda text: text.startswith("/"),
        natural_chat_check=lambda text: "？" in text,
        group_lists_provider=lambda: {
            "black1": {"200"},
            "black2": frozenset(),
            "white1": frozenset(),
            "white2": frozenset(),
        },
    )
    # 100 不再属于黑名单1（被运行时覆盖），指令照常放行
    ok = evaluate_policy(_group("/天气 杭州", gid="100"), "bot.weather", settings=settings)
    assert ok.allowed is True
    # 200 被运行时加入黑名单1 → 静默
    denied = evaluate_policy(_group("你好", gid="200"), "bot.chat", settings=settings)
    assert denied.allowed is False and denied.reason == "group_black1"
    # 300 的白名单1被运行时清空 → 自然提问不再放行
    passive = evaluate_policy(_group("鸣潮是什么？", gid="300"), "bot.chat", settings=settings)
    assert passive.allowed is False and passive.reason == "passive_group_message"


def test_provider_missing_key_keeps_static_and_failure_is_safe():
    # 只返回部分键：其余键保持静态配置。
    settings = PolicySettings(
        group_black1=frozenset({"100"}),
        group_lists_provider=lambda: {"black2": {"999"}},
    )
    denied = evaluate_policy(_group("你好"), "bot.chat", settings=settings)
    assert denied.allowed is False and denied.reason == "group_black1"

    # provider 抛异常 → 回退静态集合，不允许异常冒泡。
    def _boom() -> dict[str, frozenset[str]]:
        raise RuntimeError("provider broken")

    broken = PolicySettings(group_black1=frozenset({"100"}), group_lists_provider=_boom)
    result = evaluate_policy(_group("你好"), "bot.chat", settings=broken)
    assert result.allowed is False and result.reason == "group_black1"


def test_config_parses_group_lists():
    config = Config(
        bot_group_black1="100;200",
        bot_group_black2=["300", "400"],
        bot_group_white1="500,600",
        bot_group_white2='["700","800"]',
    )
    assert config.bot_group_black1 == ["100", "200"]
    assert config.bot_group_black2 == ["300", "400"]
    assert config.bot_group_white1 == ["500", "600"]
    assert config.bot_group_white2 == ["700", "800"]
    assert Config().bot_group_black1 == []


def test_normalize_group_policy_mode_aliases():
    # 英文大小写、简体/繁体、编号形式都要命中同一档。
    assert normalize_group_policy_mode("black1") == "BOT_GROUP_BLACK1"
    assert normalize_group_policy_mode("BLACK_1") == "BOT_GROUP_BLACK1"
    assert normalize_group_policy_mode("黑名单1") == "BOT_GROUP_BLACK1"
    assert normalize_group_policy_mode("黑名單2") == "BOT_GROUP_BLACK2"
    assert normalize_group_policy_mode("WHITE2") == "BOT_GROUP_WHITE2"
    assert normalize_group_policy_mode("白名单一") == "BOT_GROUP_WHITE1"
    assert normalize_group_policy_mode("") is None

