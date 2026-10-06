from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy import gate as gate_module
from plugins.bot_unified_runtime.domains.chat_reply.policy.gate import (
    GROUP_POLICY_SLOTS,
    PolicySettings,
    _flag_from_text,
    configure_proactive_affinity_gate,
    evaluate_policy,
    group_is_listed,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
    QuietHoursSettings,
    build_quiet_hours_settings,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
    RateLimitSettings,
    build_rate_limit_settings,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RESTART_REQUIRED_KEYS,
    SETTABLE_KEYS,
)


def _message(text: str, *, mentions_bot: bool = False, group_id: str = "group-1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id=f"group:{group_id}",
        session_type=SessionType.GROUP,
        sender_id="user-1",
        group_id=group_id,
        plain_text=text,
        mentions_bot=mentions_bot,
        message_id="message-1",
    )


def test_white2_allows_explicit_command_without_mention() -> None:
    decision = evaluate_policy(
        _message("/bot status"),
        "bot.chat",
        PolicySettings(group_white2=frozenset({"group-1"})),
    )

    assert decision.allowed is True


def test_white2_allows_mentioned_message_but_rejects_passive_message() -> None:
    settings = PolicySettings(group_white2=frozenset({"group-1"}))

    assert evaluate_policy(_message("你好", mentions_bot=True), "bot.chat", settings).allowed
    denied = evaluate_policy(_message("你好"), "bot.chat", settings)
    assert denied.allowed is False
    assert denied.reason == "group_white2_need_trigger"


def test_white2_does_not_proactively_reply() -> None:
    decision = evaluate_policy(
        _message("普通闲聊"),
        "bot.chat",
        PolicySettings(
            group_white2=frozenset({"group-1"}),
            group_auto_reply_enabled=True,
            group_auto_reply_probability=1.0,
        ),
    )

    assert decision.allowed is False


def test_white1_is_the_only_group_allowed_to_proactively_reply() -> None:
    settings = PolicySettings(
        group_white1=frozenset({"group-1"}),
        group_auto_reply_enabled=True,
        group_auto_reply_probability=1.0,
    )

    selected = evaluate_policy(_message("普通闲聊"), "bot.chat", settings)
    assert selected.allowed is True
    assert selected.reason == "proactive_reply_selected"

    other = evaluate_policy(
        _message("普通闲聊", group_id="group-2"),
        "bot.chat",
        settings,
    )
    assert other.allowed is False
    assert other.reason == "passive_group_message"


# ---------------------------------------------------------------------------
# 视觉回复腿 × 两枚中央门（group_auto_reply_enabled 总闸 / N4 好感门）真值表。
# 缺陷底账＝M2-31：视觉腿 `vision_reply_selected` 此前两门都不查，且全仓零测试锁。
# 配对锁与代码同笔（只准变严：删掉任一枚门的接线本段必红）。
# ---------------------------------------------------------------------------


def _visual_message(*, group_id: str = "group-1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id=f"group:{group_id}",
        session_type=SessionType.GROUP,
        sender_id="user-1",
        group_id=group_id,
        plain_text="",
        message_id="message-1",
        raw_segments=[{"type": "image", "data": {"url": "https://visual.test/x.png"}}],
    )


def _white1_always_drawn(*, enabled: bool = True) -> PolicySettings:
    return PolicySettings(
        group_white1=frozenset({"group-1"}),
        group_auto_reply_enabled=enabled,
        group_auto_reply_probability=1.0,  # 抽签必中，聚焦测门本身。
    )


@pytest.fixture()
def _reset_affinity_gate():
    yield
    configure_proactive_affinity_gate(None)


def test_vision_leg_respects_auto_reply_switch() -> None:
    decision = evaluate_policy(
        _visual_message(), "bot.chat", _white1_always_drawn(enabled=False)
    )
    assert decision.allowed is False
    assert decision.reason == "passive_group_message"


def test_vision_leg_selected_with_switch_on_and_close_sender(_reset_affinity_gate) -> None:
    configure_proactive_affinity_gate(lambda sender: True)
    decision = evaluate_policy(_visual_message(), "bot.chat", _white1_always_drawn())
    assert decision.allowed is True
    assert decision.reason == "vision_reply_selected"


def test_vision_leg_blocked_by_affinity_gate(_reset_affinity_gate) -> None:
    configure_proactive_affinity_gate(lambda sender: False)
    decision = evaluate_policy(_visual_message(), "bot.chat", _white1_always_drawn())
    assert decision.allowed is False
    assert decision.reason == "proactive_affinity_gate"


def test_vision_and_text_legs_share_both_gates(_reset_affinity_gate) -> None:
    """两腿同闸：同 settings 下两腿读数一致（防第 N 条抽签腿再漏接）。"""
    settings_on = _white1_always_drawn()
    configure_proactive_affinity_gate(lambda sender: False)
    assert evaluate_policy(_visual_message(), "bot.chat", settings_on).reason == (
        evaluate_policy(_message("普通闲聊"), "bot.chat", settings_on).reason
    )

    settings_off = _white1_always_drawn(enabled=False)
    configure_proactive_affinity_gate(None)
    vision = evaluate_policy(_visual_message(), "bot.chat", settings_off)
    assert vision.allowed is False
    assert vision.reason == evaluate_policy(
        _message("普通闲聊"), "bot.chat", settings_off
    ).reason


# ---------------------------------------------------------------------------
# E05 缺口一 · 未在册群的命令腿必须关门。
# 缺陷底账：群分支末尾 fall-through `allowed=True`——群不在 black1/black2/
# white1/white2 任何一册时，任意成员敲 /bot 全通（.env 从未填过群名单）。
# 红线（同段配对锁）：黑白名单既有语义**一字未动**——硬否决仍在最前、
# 空名单被动回复仍 fail-close、搭话好感门双腿仍同检。本段只收紧命令态。
# ---------------------------------------------------------------------------


def _private(text: str, *, roles: tuple[str, ...] = ("user",)) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot-1",
        session_id="private:user-1",
        session_type=SessionType.PRIVATE,
        sender_id="user-1",
        sender_roles=list(roles),
        plain_text=text,
        message_id="message-1",
    )


def _group(text, *, roles=("user",), mentions_bot=False, group_id="group-1"):
    message = _message(text, mentions_bot=mentions_bot, group_id=group_id)
    return message.model_copy(update={"sender_roles": list(roles)})


def test_command_in_unlisted_group_is_denied() -> None:
    """四册皆不含的群 + 命令态 ⇒ 拒（这就是缺口本身，改前恒放行）。"""
    decision = evaluate_policy(_group("/bot status"), "bot.status", PolicySettings())
    assert decision.allowed is False
    assert decision.reason == "command_group_unlisted"
    assert "policy" in decision.audit_tags


def test_alias_command_in_unlisted_group_is_denied() -> None:
    """别名命令（extra_command_check）同受此门——攻击面同形，不留第二道缝。"""
    settings = PolicySettings(extra_command_check=lambda text: text.startswith("/岸宝"))
    decision = evaluate_policy(_group("/岸宝帮助"), "bot.help", settings)
    assert decision.allowed is False
    assert decision.reason == "command_group_unlisted"


@pytest.mark.parametrize(
    "settings",
    [
        PolicySettings(group_white1=frozenset({"group-1"})),
        PolicySettings(group_white2=frozenset({"group-1"})),
        PolicySettings(group_black2=frozenset({"group-1"})),
    ],
    ids=["white1", "white2", "black2-mentioned"],
)
def test_listed_group_command_still_allowed(settings: PolicySettings) -> None:
    """合法形：在册群的命令一律照旧能过（black2 需带 @，夹具已带）。"""
    decision = evaluate_policy(
        _group("/bot help", mentions_bot=True), "bot.chat", settings
    )
    assert decision.allowed is True


def test_dynamic_provider_listing_opens_the_command_leg() -> None:
    """在册面含动态 provider（管理员热改）：provider 给了群就算在册。"""
    settings = PolicySettings(
        group_lists_provider=lambda: {"white1": frozenset({"group-1"})}
    )
    assert evaluate_policy(_group("/bot help"), "bot.chat", settings).allowed is True


def test_flag_off_restores_legacy_open_behaviour() -> None:
    """止血开关：置 False 回退旧行为（事故时可关，不作缺省）。"""
    settings = PolicySettings(command_requires_listed_group=False)
    decision = evaluate_policy(_group("/bot status"), "bot.status", settings)
    assert decision.allowed is True


def test_unlisted_group_passive_message_keeps_old_reason() -> None:
    """被动腿零变更：未触发群消息仍 fail-close 到 passive_group_message。"""
    decision = evaluate_policy(_message("普通闲聊"), "bot.chat", PolicySettings())
    assert decision.allowed is False
    assert decision.reason == "passive_group_message"


def test_unlisted_group_mentioned_chat_unchanged() -> None:
    """红线锁（不是新门的战利品）：@bot 说人话在 HEAD 就是「主动触发」，未在册群
    也照旧放行——本席**只收紧命令态**，不顺手改 @ 腿语义（要治那一层属白名单面，
    归用户裁定）。此断言若哪天变 False，说明有人把命令门扩到了 @ 腿上。
    """
    decision = evaluate_policy(
        _message("你好", mentions_bot=True), "bot.chat", PolicySettings()
    )
    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_prefix_without_word_boundary_is_not_command_state() -> None:
    """`/botxxx` 不算命令态（is_command_text 语义守住）⇒ 不落到新 reason。"""
    decision = evaluate_policy(_message("/botxxx"), "bot.chat", PolicySettings())
    assert decision.allowed is False
    assert decision.reason == "passive_group_message"


def test_private_session_commands_are_untouched() -> None:
    """私聊路径不受影响：整段门只在 GROUP 分支内。"""
    assert evaluate_policy(_private("/bot status"), "bot.status", PolicySettings()).allowed
    assert evaluate_policy(_private("/bot 帮助"), "bot.help", PolicySettings()).allowed


def test_hard_vetoes_precede_the_unlisted_command_gate() -> None:
    """硬否决优先：blocked 角色 / CRITICAL 风险 / black1 群都仍是原 reason。"""
    blocked = evaluate_policy(
        _group("/bot status", roles=("blocked",)), "bot.status", PolicySettings()
    )
    assert blocked.reason == "sender_blocked"

    black1 = evaluate_policy(
        _group("/bot status"),
        "bot.status",
        PolicySettings(group_black1=frozenset({"group-1"})),
    )
    assert black1.reason == "group_black1"

    critical = evaluate_policy(
        _group("/bot status").model_copy(update={"risk_level": RiskLevel.CRITICAL}),
        "bot.status",
        PolicySettings(),
    )
    assert critical.reason == "critical_input_risk"


def test_listen_only_account_still_wins_over_the_new_gate() -> None:
    """监听专用号：命令/点名全否决的旧语义在前，reason 不许被新门顶掉。"""
    settings = PolicySettings(listen_only_bot_ids=frozenset({"bot-1"}))
    decision = evaluate_policy(_group("/bot status"), "bot.status", settings)
    assert decision.reason == "listen_only_account"


def test_group_is_listed_uses_the_four_slots_single_truth() -> None:
    """谓词只吃 GROUP_POLICY_SLOTS（禁第二份名单名），缺键按缺席处理。"""
    assert group_is_listed({"black2": frozenset({"g"})}, "g")
    assert not group_is_listed({"black2": frozenset({"g"})}, "other")
    assert not group_is_listed({}, "")
    # 槽名真身＝四档；多给无关键不算在册。
    assert not group_is_listed({"grey": frozenset({"g"})}, "g")
    assert set(GROUP_POLICY_SLOTS) == {"black1", "black2", "white1", "white2"}


# ---------------------------------------------------------------------------
# W2 · 门禁准入键的三面登记账（台账 #68★：幽灵字段补齐＝config 字段 + settings.py
# 热改态登记 + `.env.example` **三面齐**，只补一面必红另一面）。
# 本段是「三面齐」这件事的常驻锁：任一面被摘掉、或新补同类键却只补一面，当场点名。
# 登记账本文＝patches/E05-CONFIG-REQUEST.md。
# ---------------------------------------------------------------------------

#: (Config 字段名, env 键名)——八枚逐枚点名，缺一枚就是漏登记。
#: 安静时间两枚的真身读点＝`quiet_hours.py::build_quiet_hours_settings` 的
#: `bot_quiet_hours_direct_bypass_{mentions,commands}`（2026-10-01 用户裁定把早前
#: 单枚 `..._requires_both` 拆成两腿各一枚；本席按**落盘读点**定名，不自创键名）。
ADMISSION_KEYS_ON_THREE_FACES: tuple[tuple[str, str], ...] = (
    ("bot_gate_command_requires_listed_group", "BOT_GATE_COMMAND_REQUIRES_LISTED_GROUP"),
    (
        "bot_quiet_hours_direct_bypass_mentions",
        "BOT_QUIET_HOURS_DIRECT_BYPASS_MENTIONS",
    ),
    (
        "bot_quiet_hours_direct_bypass_commands",
        "BOT_QUIET_HOURS_DIRECT_BYPASS_COMMANDS",
    ),
    ("bot_rate_limit_command_enabled", "BOT_RATE_LIMIT_COMMAND_ENABLED"),
    ("bot_rate_limit_command_window_seconds", "BOT_RATE_LIMIT_COMMAND_WINDOW_SECONDS"),
    ("bot_rate_limit_command_sender_max_requests", "BOT_RATE_LIMIT_COMMAND_SENDER_MAX_REQUESTS"),
    ("bot_rate_limit_command_group_max_requests", "BOT_RATE_LIMIT_COMMAND_GROUP_MAX_REQUESTS"),
    ("bot_rate_limit_command_bypass_roles", "BOT_RATE_LIMIT_COMMAND_BYPASS_ROLES"),
)

_ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"
_ACTIVE_ENV_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


@pytest.mark.parametrize(
    ("field_name", "env_key"),
    ADMISSION_KEYS_ON_THREE_FACES,
    ids=[env for _, env in ADMISSION_KEYS_ON_THREE_FACES],
)
def test_admission_key_is_registered_on_all_three_faces(field_name: str, env_key: str) -> None:
    """①Config 有字段 ②热改面有唯一表态 ③`.env.example` 有**激活**键行（注释形态不算）。"""
    assert field_name in Config.model_fields, f"{field_name} 缺 config.py 字段（写了不生效）"

    listed = set(SETTABLE_KEYS) | set(RESTART_REQUIRED_KEYS)
    assert env_key in listed, (
        f"{env_key} 对热改面没表态：既不在 SETTABLE_KEYS 也不在 RESTART_REQUIRED_KEYS"
        "（管理员看不出它能不能热改）"
    )
    assert not (env_key in SETTABLE_KEYS and env_key in RESTART_REQUIRED_KEYS), (
        f"{env_key} 两表同现 ⇒ 热改档位无唯一真值"
    )

    active_keys = {
        m.group(1) for m in _ACTIVE_ENV_KEY_RE.finditer(_ENV_EXAMPLE.read_text(encoding="utf-8"))
    }
    assert env_key in active_keys, (
        f"{env_key} 不在 `.env.example` 的激活键行里 ⇒ 运维照旧不知道有这枚开关"
        "（本断言刻意不认 `# KEY=` 注释形态，与 test_env_example_gate 同口径）"
    )


def test_command_gate_config_default_is_the_safe_side() -> None:
    """缺省取向核对（补台账 #69★ 那条「补键的门只判在场不校验缺省值」的牙）：
    配置面缺省必须＝收紧侧 True，且 PolicySettings 侧留 None＝「交配置面判」。"""
    info = Config.model_fields["bot_gate_command_requires_listed_group"]
    assert info.default is True, "命令态在册门的配置面缺省漂了（安全侧必须=True）"
    assert PolicySettings().command_requires_listed_group is None, (
        "PolicySettings 侧不许把缺省写回硬编码 True——None 才是「按配置面判定」那一档，"
        "装配方显式传值时仍优先"
    )


@pytest.mark.parametrize("raw", ["false", "0", "no", "off"])
def test_env_switch_actually_closes_the_command_gate(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """止血面必须**实测能关**（简报硬话：想关掉不能只能改码 + 重启）。

    `"false"` 折成假值这一腿是承重结构：driver config / os.environ 存的是原文字符串，
    `bool("false")` 恒真＝「写了没用」的静默失效形态。
    """
    monkeypatch.setenv("BOT_GATE_COMMAND_REQUIRES_LISTED_GROUP", raw)
    decision = evaluate_policy(_group("/bot status"), "bot.status", PolicySettings())
    assert decision.allowed is True, f"配置面写 {raw!r} 没关掉这道门＝止血面是假的"


def test_env_garbage_keeps_the_gate_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """认不出的形态宁按缺省收紧，绝不猜用户的意思（fail-close）。"""
    monkeypatch.setenv("BOT_GATE_COMMAND_REQUIRES_LISTED_GROUP", "maybe")
    decision = evaluate_policy(_group("/bot status"), "bot.status", PolicySettings())
    assert decision.reason == "command_group_unlisted"


def test_explicit_flag_beats_the_config_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    """装配方/单测显式传值优先于配置面：环境写 false 也压不住显式 True 的判定。"""
    monkeypatch.setenv("BOT_GATE_COMMAND_REQUIRES_LISTED_GROUP", "false")
    decision = evaluate_policy(
        _group("/bot status"),
        "bot.status",
        PolicySettings(command_requires_listed_group=True),
    )
    assert decision.reason == "command_group_unlisted"


# ---------------------------------------------------------------------------
# F-13 乙案 · 配置面布尔词表的两把尺（词表搬家批 2026-10-06）。
# 真身今天住 `domains/core/config/` 里一枚**已存在**的件（本批把词表从一枚新建件
# 搬进 `config_readiness.py`——同一条事实只准有一处真身，为此多开一个生产文件不算修）。
# 搬家前后下面三枚读数必须逐格相同：①三态语义（None＝读不出、交下一级，这一格的
# 落点就是「硬合并判定逻辑」会改掉的东西，故只折字集不折逻辑）；②字集成员本身；
# ③全仓只准一处定义。判定逻辑的三份同型实现今天仍各住各家（control_plane 与
# llm_engine/channel_health 在 `test_trigger_word_single_source` 的名册逐枚署名在册）。
# ---------------------------------------------------------------------------

#: (配置面原始值, `_flag_from_text` 应有读数)——期望列取自搬家**前**的实跑对拍基线。
#: 覆盖：空串／纯空白／认不出／纯数字／大小写混排／首尾带空白／真值词／假值词／
#: 原生 bool／原生 int／None。21 格，任一格的读数变了都算行为变了。
FLAG_TRISTATE_CASES: tuple[tuple[object, bool | None], ...] = (
    ("", None),
    ("   ", None),
    ("maybe", None),
    ("1", True),
    ("true", True),
    ("TRUE", True),
    ("  Yes  ", True),
    ("on", True),
    ("0", False),
    ("false", False),
    ("FALSE", False),
    ("off", False),
    ("no", False),
    ("2", None),
    ("y", None),
    ("on1", None),
    ("10", None),
    (None, None),
    (True, True),
    (False, False),
    (1, True),
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGINS_ROOT = _REPO_ROOT / "plugins"
_FLAG_TABLE_NAMES = frozenset({"ENV_TRUE_WORDS", "ENV_FALSE_WORDS"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    FLAG_TRISTATE_CASES,
    ids=[f"{index}_{value!r}" for index, (value, _e) in enumerate(FLAG_TRISTATE_CASES)],
)
def test_flag_from_text_tristate_table(raw: object, expected: bool | None) -> None:
    """三态逐格对拍：`is` 而非 `==`——不许把 `""`／`0` 这类"读不出"折成 False 档。"""
    assert _flag_from_text(raw) is expected, (
        f"输入 {raw!r} 的读数从 {expected!r} 变成 {_flag_from_text(raw)!r}＝搬家动了语义"
        "（None 那一格＝读不出交下一级，是 fail-close 的落点，不是可以顺手抹平的死格）"
    )


def test_flag_word_tables_membership_is_the_blessed_one() -> None:
    """字集成员本身也是账：真值集/假值集逐格点名且两集互斥——搬家只准换家、不准换词。"""
    assert gate_module.ENV_TRUE_WORDS == frozenset({"1", "true", "on", "yes"})
    assert gate_module.ENV_FALSE_WORDS == frozenset({"0", "false", "off", "no"})
    assert not (gate_module.ENV_TRUE_WORDS & gate_module.ENV_FALSE_WORDS), (
        "同一枚字面既真又假＝词表被并成了一坨，三态读数会随书写顺序变"
    )


def test_flag_word_tables_have_exactly_one_home_in_the_source_tree() -> None:
    """单一真身结构锁：全树**模块级定义**这两枚词表的文件只准一枚，且 gate 引用的就是它。

    这条锁管的是"再抄一份"和"为这件事再开一个生产文件"两种跑偏：搬家（换文件）与
    复制（多文件）在这里都是可现算的——改家数＝当场红。
    """
    definers: dict[str, set[str]] = {}
    for path in sorted(_PLUGINS_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                targets: list[ast.expr] = list(stmt.targets)
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
            else:
                continue
            names = {t.id for t in targets if isinstance(t, ast.Name)} & set(_FLAG_TABLE_NAMES)
            if names:
                definers.setdefault(path.relative_to(_REPO_ROOT).as_posix(), set()).update(names)
    assert len(definers) == 1, (
        f"配置面布尔词表被 {len(definers)} 枚文件定义：{sorted(definers)}"
    )
    home_rel, home_names = next(iter(definers.items()))
    assert home_names == set(_FLAG_TABLE_NAMES), (
        f"真值集与假值集被拆散到别处（第二处定义）：{sorted(home_names)}"
    )
    assert home_rel.startswith("plugins/bot_unified_runtime/domains/core/config/"), (
        f"词表真身跑出配置域：{home_rel}"
    )
    home_module = importlib.import_module(
        home_rel[: -len(".py")].replace("/", "."),
    )
    assert gate_module.ENV_TRUE_WORDS is home_module.ENV_TRUE_WORDS
    assert gate_module.ENV_FALSE_WORDS is home_module.ENV_FALSE_WORDS


def test_new_config_fields_drive_the_consumer_settings() -> None:
    """七枚消费侧键（rate_limit 五枚 + quiet_hours 两枚）缺省**逐枚等于**消费侧模型的
    缺省，且改了 Config 就改了消费侧读数 ⇒ 证明键不是「登记在册却没人读」的镜像。"""
    rate = build_rate_limit_settings(Config())
    baseline = RateLimitSettings()
    for field in (
        "command_enabled",
        "command_window_seconds",
        "command_sender_max_requests",
        "command_group_max_requests",
        "command_bypass_roles",
    ):
        assert getattr(rate, field) == getattr(baseline, field), (
            f"Config 缺省与 RateLimitSettings.{field} 缺省分叉＝两本账"
        )
    assert build_quiet_hours_settings(Config()).direct_bypass_covers_mentions is (
        QuietHoursSettings().direct_bypass_covers_mentions
    )
    assert build_quiet_hours_settings(Config()).direct_bypass_covers_commands is (
        QuietHoursSettings().direct_bypass_covers_commands
    )

    moved = build_rate_limit_settings(
        Config.model_validate(
            {
                "bot_rate_limit_command_enabled": False,
                "bot_rate_limit_command_window_seconds": 30,
                "bot_rate_limit_command_sender_max_requests": 3,
                "bot_rate_limit_command_group_max_requests": 5,
                "bot_rate_limit_command_bypass_roles": ["admin", "trusted"],
            }
        )
    )
    assert moved.command_enabled is False
    assert moved.command_window_seconds == 30
    assert moved.command_sender_max_requests == 3
    assert moved.command_group_max_requests == 5
    assert moved.command_bypass_roles == ["admin", "trusted"]

    tightened = build_quiet_hours_settings(
        Config.model_validate(
            {
                "bot_quiet_hours_direct_bypass_mentions": False,
                "bot_quiet_hours_direct_bypass_commands": False,
            }
        )
    )
    assert tightened.direct_bypass_covers_mentions is False
    assert tightened.direct_bypass_covers_commands is False


def test_command_bypass_roles_accepts_delimiter_string() -> None:
    """`.env` 里写 `admin;trusted` 这类分隔串必须能装载（与同族 bypass_roles 共用
    `_parse_role_list` 那条腿；漏挂 validator 会当场 ValidationError＝「写了就炸」）。"""
    parsed = Config.model_validate({"bot_rate_limit_command_bypass_roles": "admin;trusted"})
    assert parsed.bot_rate_limit_command_bypass_roles == ["admin", "trusted"]
