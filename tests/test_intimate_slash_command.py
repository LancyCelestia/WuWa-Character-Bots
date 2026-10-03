"""席 S6（2026-10-08）：`/bot intimate` 斜杠命令面的判据锁。

真入口＝`build_intimate_control_result`（`domains/chat_reply/runtime/intimate_control.py`）。
本件**不**重测参数解析（那是 `test_intimate_subcommand_parse.py`），只测四件事：

1. **开关腿只准复用唯一生效出口**——回执逐字等于 `MANUAL_ON_REPLY`/`MANUAL_DEEP_ON_REPLY`/
   `MANUAL_OFF_REPLY`，档位/来源/作用域键全由既有中央口给出。斜杠面不许自己上钉、
   不许自己写第二套确认话（那正是本波要防的第二真身；末段有枚 AST 锁盯着这件事）。
2. **斜杠面与整句面在同一个会话上产出同一个 verdict**（`mode`/`tier`/`source` 三字段全等）。
   两路口词面不同（英文子命令 vs 中文整句），生效后必须无差别。
3. **`show` 是只读查询**：既不动钉，也只准说人话。三条红线——
   ① 内部码串（模型名/来源串/档位码）绝不外端，来源必须过本模块的人话映射表；
   ② 长度**只报档名、不报字数区间**（正文里连数字都不该出现）；
   ③ 生效长度档必须走 `chat.py` 那条**四层优先级链**（运行时覆盖→该人永久策略→
      `BOT_REPLY_DETAIL`→auto）——只读 `config.bot_reply_detail` 就是谎报。
4. **裸命令必须自己交出「用法 + 当前档 + 指路一行」**。今天裸 `/bot intimate` 是靠
   `_handle_status` 落空后经 `bot.help` → `_HELP_ALIAS_MAP["intimate"]` 出帮助页的；
   新加一支 elif 就把那条旧行为顶掉了 ⇒ 不补就是静默回归，所以这条进锁。

夹具铁律（AGENTS 规则 6 + 台账 #66★ + 「孤儿 pytest 会写她生产库」那条教训）：
- `shared_reply_policy_store` 一律 monkeypatch 到 tmp（先例 `test_reply_policy_preset_command.py`）
  ——她生产 reply_policy 库今天已被别的测试写过、且 Runtime 里没有任何备份，再写就是事故；
- `bot_addressing_preferences_db_path` 给仓库外的 tmp 绝对路径；
- 每枚用例各占一枚群号/会话键：`SHARED_CONTENT_ROUTE_ENGINE` 是进程级单例，
  管理员的全群钉会染后面所有用例（`test_intimate_group_switch_delivery` 自己踩过两次）。

全离线：零网络、零真模型调用（LLM 替身只记「这一轮有没有被叫过」）。
"""
from __future__ import annotations

import ast
import os
import re
import tempfile
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    ContextBundle,
    ConversationHistoryResult,
    IncomingMessage,
    MemoryRetrievalResult,
    PersonaProfile,
    PrivacyLevel,
    RetrievalResult,
    RiskLevel,
    SendPolicy,
    SessionType,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    reply_policy as rp_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    ReplyPolicy,
    ReplyPolicyStore,
    person_reply_policy_key,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import LLMReply
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_SOURCE_ADMIN_PIN,
    INTIMATE_SOURCE_MANUAL,
    INTIMATE_SOURCE_NONE,
    INTIMATE_TIER_L1,
    INTIMATE_TIER_L2,
    INTIMATE_TIER_NONE,
    MANUAL_DEEP_ON_REPLY,
    MANUAL_OFF_REPLY,
    MANUAL_ON_REPLY,
    MODE_INTIMATE,
    MODE_NORMAL,
    SHARED_CONTENT_ROUTE_ENGINE,
    resolve_intimate_context,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.intimate_control import (
    INTIMATE_HELP_POINTER,
    build_intimate_control_result,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    build_session_key,
    group_scope_key,
    private_session_key,
)

_TMP_DATA_DIR = tempfile.mkdtemp(prefix="thyg-intslash-")
_CONTROL_SRC = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "intimate_control.py"
)

_ADMIN = "3865067623"
_MEMBER = "2950687868"
_OTHER = "9000000001"


# ---------------------------------------------------------------- 夹具


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> ReplyPolicyStore:
    """引擎账本每枚用例换新 + 共享策略 store 结构性指 tmp（绝不碰生产库）。"""
    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "_sessions", OrderedDict())
    store = ReplyPolicyStore(Path(tmp_path) / "reply_policy.sqlite3")
    monkeypatch.setattr(rp_module, "shared_reply_policy_store", lambda _config: store)
    return store


def _config(group: str, **overrides: object) -> SimpleNamespace:
    """会话门配置替身（形状照 `test_intimate_switch_equivalence._config`）。

    `group` **无默认值**：漏传必须 TypeError，不许静默回落到别人用过的键。
    """
    base: dict[str, object] = {
        "bot_addressing_preferences_db_path": os.path.join(
            _TMP_DATA_DIR, f"addr-{group}.sqlite3"
        ),
        "bot_content_route_enabled": True,
        "bot_content_route_model": "grok-4.6",
        "bot_content_route_order": "grok-4.6,gemini-3.8-flash",
        "bot_content_route_words": "",
        "bot_content_route_intimate_threshold": 60.0,
        "bot_content_route_normal_threshold": 25.0,
        "bot_content_route_context_turns": 4,
        "bot_content_route_max_ttl_minutes": 120.0,
        "bot_content_route_idle_reset_minutes": 10.0,
        "bot_content_route_intimate_ttl_minutes": 60.0,
        "bot_content_route_group_per_user_enabled": True,
        "bot_content_route_group_whitelist": [group],
        "bot_content_route_group_blacklist": [],
        "bot_content_route_private_whitelist": [],
        "bot_content_route_private_blacklist": [],
        # 两条自动腿关掉：本件只测「人亲手拨了一下开关」，自动档会污染读数。
        "bot_content_route_l1_auto_enabled": False,
        "bot_content_route_l1_auto_min_tier": 1,
        "bot_master_love_enabled": False,
        "bot_master_love_admins": [],
        "bot_reply_policy_enabled": True,
        "bot_reply_policy_db_path": str(Path(_TMP_DATA_DIR) / f"rp-{group}.sqlite3"),
        "bot_reply_detail": "detail",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _SilentProvider:
    """离线 LLM 替身：留下「这一轮到底有没有走到大模型」。"""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list[dict[str, Any]], **kwargs: object) -> LLMReply:
        self.calls += 1
        return LLMReply(text="嗯，我在听。", provider="fake", model="fake")


class _RuntimeOverrides:
    """`runtime_settings` 替身：只交 `get_or` 这一张口（与真身同名同形）。"""

    def __init__(self, overrides: dict[str, Any] | None = None) -> None:
        self._overrides = dict(overrides or {})

    def get_or(self, key: str, default: Any) -> Any:
        return self._overrides.get(str(key).strip().upper(), default)


def _private_message(text: str, sender: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="3958874605",
        session_id=private_session_key(sender),
        session_type=SessionType.PRIVATE,
        sender_id=sender,
        plain_text=text,
        command_text=text,
        mentions_bot=True,
        raw_segments=[{"type": "text", "data": {"text": text}}],
    )


def _decision(message: IncomingMessage) -> BotDecision:
    is_group = message.session_type is SessionType.GROUP
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=message.session_type,
        privacy_level=PrivacyLevel.GROUP if is_group else PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _context(message: IncomingMessage) -> ContextBundle:
    """复刻能力入口的隐私夹取（群腿=GROUP）——D1 那一格只有这样才能量到。"""
    return ContextBundle(
        request_id=message.request_id,
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id=message.request_id),
        conversation_history=ConversationHistoryResult(request_id=message.request_id),
        knowledge_results=RetrievalResult(request_id=message.request_id),
        current_message=message.plain_text,
        sender_id=message.sender_id,
        session_id=message.session_id,
        privacy_level=(
            PrivacyLevel.GROUP
            if message.session_type is SessionType.GROUP
            else PrivacyLevel.PERSONAL
        ),
    )


def _slash(
    sub: str,
    *,
    config: SimpleNamespace,
    sender: str = _ADMIN,
    group: str = "",
    roles: list[str] | None = None,
    runtime_settings: Any = None,
) -> Any:
    """斜杠命令面真入口：给了 ``group`` 就走群会话，否则私聊。"""
    if group:
        session_type = "group"
        session_key = build_session_key(group, sender)
        privacy = PrivacyLevel.GROUP
    else:
        session_type = "private"
        session_key = private_session_key(sender)
        privacy = PrivacyLevel.PERSONAL
    return build_intimate_control_result(
        config=config,
        request_id=f"req-intslash-{sub or 'bare'}-{group or sender}",
        subcommand=sub,
        session_type=session_type,
        session_key=session_key,
        group_id=group,
        sender_id=sender,
        sender_roles=list(roles if roles is not None else ["user", "admin", "super_admin"]),
        privacy_level=privacy,
        runtime_settings=runtime_settings,
    )


def _group_scope(group: str) -> str:
    """整群作用域键——**只经中央件构造**（会话键先按生产下划线形拼出来再收拢）。"""
    return group_scope_key(build_session_key(group, _ADMIN))


def _verdict(config: SimpleNamespace, *, sender: str, group: str = "") -> dict[str, Any]:
    """只读判定读数（键形与主链同源：群=成员派生键，私聊=本人键）。"""
    return resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type="group" if group else "private",
        group_id=group,
        sender_id=sender,
        session_key=(
            build_session_key(group, sender) if group else private_session_key(sender)
        ),
        config=config,
    )


# ---------------------------------------------------------------- ① 开关腿：唯一生效出口


def test_on_returns_shallow_ack_and_l1_verdict() -> None:
    cfg = _config("1000000101")
    result = _slash("on", config=cfg, sender=_ADMIN)
    assert result.body == MANUAL_ON_REPLY, result.body
    assert result.capability_id == "bot.chat", "斜杠面另铸了第二枚能力 id"
    verdict = _verdict(cfg, sender=_ADMIN)
    assert verdict["mode"] == MODE_INTIMATE
    assert verdict["tier"] == INTIMATE_TIER_L1, "浅档词被上成了深档"
    assert verdict["source"] == INTIMATE_SOURCE_MANUAL
    tags = list(result.audit_tags or [])
    assert "slash_intimate:on" in tags, tags
    assert "scope:self" in tags, tags


def test_deep_returns_deep_ack_and_l2_verdict() -> None:
    cfg = _config("1000000102")
    result = _slash("deep", config=cfg, sender=_ADMIN)
    assert result.body == MANUAL_DEEP_ON_REPLY, result.body
    verdict = _verdict(cfg, sender=_ADMIN)
    assert verdict["mode"] == MODE_INTIMATE
    assert verdict["tier"] == INTIMATE_TIER_L2
    assert "slash_intimate:deep" in list(result.audit_tags or [])


def test_off_clears_both_tiers() -> None:
    cfg = _config("1000000103")
    assert _slash("deep", config=cfg, sender=_ADMIN).body == MANUAL_DEEP_ON_REPLY
    assert _verdict(cfg, sender=_ADMIN)["tier"] == INTIMATE_TIER_L2
    result = _slash("off", config=cfg, sender=_ADMIN)
    assert result.body == MANUAL_OFF_REPLY, result.body
    verdict = _verdict(cfg, sender=_ADMIN)
    assert verdict["mode"] == MODE_NORMAL
    assert verdict["tier"] == INTIMATE_TIER_NONE, "深档没被一起解下来"
    assert verdict["source"] == INTIMATE_SOURCE_NONE, "解除后还留着来源＝下一轮会被认成在档"
    assert "slash_intimate:off" in list(result.audit_tags or [])


def test_switch_privacy_follows_the_session_not_a_hardcoded_value() -> None:
    """D1 事故那一格：群内回执必须声明 GROUP，否则审核判 move_private＝"开关不可用"。"""
    group = "1000000104"
    cfg = _config(group)
    in_group = _slash("on", config=cfg, sender=_ADMIN, group=group)
    assert in_group.privacy_level is PrivacyLevel.GROUP, in_group.privacy_level
    alone = _slash("on", config=_config("1000000105"), sender=_ADMIN)
    assert alone.privacy_level is PrivacyLevel.PERSONAL, alone.privacy_level


# ---------------------------------------------------------------- ② 群内两级作用域


def test_group_admin_pins_group_scope_key_with_admin_source() -> None:
    group = "1000000106"
    cfg = _config(group)
    result = _slash("on", config=cfg, sender=_ADMIN, group=group, roles=["user", "admin"])
    assert result.body == MANUAL_ON_REPLY
    assert "scope:group" in list(result.audit_tags or []), result.audit_tags
    # 钉必须挂在**整群那把键**上（不是管理员自己的成员键）——T-1 那一族缺陷的判据。
    pinned = SHARED_CONTENT_ROUTE_ENGINE.pinned_mode(_group_scope(group), cfg)
    assert pinned == MODE_INTIMATE, f"群作用域键上没吃到钉：{pinned!r}"
    assert _verdict(cfg, sender=_ADMIN, group=group)["source"] == INTIMATE_SOURCE_ADMIN_PIN
    # 全群生效：同群里没自己拨过的成员也该读到亲密档。
    assert _verdict(cfg, sender=_OTHER, group=group)["mode"] == MODE_INTIMATE


def test_group_member_pins_only_self_with_scope_user_tag() -> None:
    group = "1000000107"
    cfg = _config(group)
    result = _slash("on", config=cfg, sender=_MEMBER, group=group, roles=["user"])
    assert result.body == MANUAL_ON_REPLY
    assert "scope:user" in list(result.audit_tags or []), result.audit_tags
    # 本人读得到、同群别人读不到（B-Important-1 那格泄漏的历史缺陷）。
    assert _verdict(cfg, sender=_MEMBER, group=group)["mode"] == MODE_INTIMATE
    assert _verdict(cfg, sender=_OTHER, group=group)["mode"] == MODE_NORMAL
    assert SHARED_CONTENT_ROUTE_ENGINE.pinned_mode(_group_scope(group), cfg) is None


# ---------------------------------------------------------------- ③ 斜杠面 ≡ 整句面


@pytest.mark.parametrize(
    ("slash_sub", "sentence", "want_tier"),
    [
        ("on", "亲密模式 开", INTIMATE_TIER_L1),
        ("deep", "亲密模式 深开", INTIMATE_TIER_L2),
        ("off", "亲密模式 关", INTIMATE_TIER_NONE),
    ],
    ids=["on", "deep", "off"],
)
def test_slash_and_full_sentence_produce_the_same_verdict(
    slash_sub: str, sentence: str, want_tier: str
) -> None:
    """两路口词面不同，生效后必须无差别：同一会话上 mode/tier/source 三字段全等。"""
    sender = f"7100{len(sentence)}0{len(slash_sub)}"
    cfg = _config("1000000108")

    # ① 整句面（今天已在生产的那条路）
    message = _private_message(sentence, sender)
    provider = _SilentProvider()
    ack = build_chat_result(
        message,
        _decision(message),
        _context(message),
        llm_provider=provider,
        content_route_config=cfg,
    )
    assert provider.calls == 0, "整句开关句走进了大模型 ⇒ 短路腿被搬坏"
    sentence_verdict = _verdict(cfg, sender=sender)
    assert sentence_verdict["tier"] == want_tier, sentence_verdict

    # ② 同一个会话键上走斜杠面；先归零，免得"两遍都没动"被当成"两遍相同"。
    _slash("off", config=cfg, sender=sender)
    assert _verdict(cfg, sender=sender)["mode"] == MODE_NORMAL
    _slash(slash_sub, config=cfg, sender=sender)
    slash_verdict = _verdict(cfg, sender=sender)

    for field in ("mode", "tier", "source"):
        assert slash_verdict[field] == sentence_verdict[field], (
            f"{field} 两路口分叉：斜杠={slash_verdict[field]!r} "
            f"整句={sentence_verdict[field]!r}"
        )
    # 回执文本同源（斜杠面不许自己另写一句）
    assert _slash(slash_sub, config=cfg, sender=sender).body == ack.body


# ---------------------------------------------------------------- ④ show：只读 + 只说人话


def test_show_reads_back_the_current_tier_without_moving_the_pin() -> None:
    cfg = _config("1000000109")
    _slash("deep", config=cfg, sender=_ADMIN)
    before = dict(_verdict(cfg, sender=_ADMIN))
    result = _slash("show", config=cfg, sender=_ADMIN)
    assert "深" in result.body, result.body
    assert "slash_intimate:show" in list(result.audit_tags or [])
    after = dict(_verdict(cfg, sender=_ADMIN))
    assert after == before, f"看一眼就把档位改了：{before} -> {after}"


def test_show_reports_narration_grant_and_admission() -> None:
    """五维叙述那一格＝`grants_intimate_narration(source)`；准入门读数照实说。"""
    cfg = _config("1000000110")
    cold = _slash("show", config=cfg, sender=_ADMIN).body
    assert "描写：没开" in cold, cold
    _slash("on", config=cfg, sender=_ADMIN)
    warm = _slash("show", config=cfg, sender=_ADMIN).body
    assert "描写：已开" in warm, warm
    assert "这一处准进：是" in warm, warm


@pytest.mark.parametrize(
    ("sub", "strict"),
    [("show", True), ("", False)],
    ids=["show", "bare"],
)
def test_outbound_text_carries_no_internals_and_no_char_counts(
    sub: str, strict: bool
) -> None:
    """两条红线一起量：内部码串绝不外端；长度只报档名、不报字数区间。

    裸命令（``sub=""``）同样过一遍——它的行文也出自本模块。唯一豁免是用法表里
    那行 `/bot intimate`：那是**用户自己敲的命令名**，不是内部码串；
    `show` 那一腿没有这层借口，所以连档位码都不许外端（``strict``）。
    """
    cfg = _config("1000000111")
    _slash("on", config=cfg, sender=_ADMIN)
    body = _slash(sub, config=cfg, sender=_ADMIN).body
    lowered = body.lower()
    forbidden = [
        "grok",
        "gemini",
        "model",
        "manual_command",
        "admin_pin",
        "master_love",
        "content_signal",
        "affinity_tier",
    ]
    if strict:
        forbidden += ["intimate", "normal", "l1", "l2", "threshold"]
    for token in forbidden:
        assert token not in lowered, f"内部码串外端：{token} ∈ {body!r}"
    assert not re.search(r"\d+\s*字", body), f"报了字数区间＝把长度尺抄进人话：{body!r}"
    for wording in ("阈值", "路由", "模型", "优先级", "默认链"):
        assert wording not in body, wording


def test_show_speaks_unknown_source_code_in_its_own_words() -> None:
    """人话映射表的反直觉那一腿：认不出的码要**带着原码**说话，不硬套标签。"""
    cfg = _config("1000000112")
    assert SHARED_CONTENT_ROUTE_ENGINE.apply_manual(
        private_session_key(_ADMIN),
        MODE_INTIMATE,
        cfg,
        source="brand_new_source",
        tier=INTIMATE_TIER_L1,
    )
    body = _slash("show", config=cfg, sender=_ADMIN).body
    assert "brand_new_source" in body, body
    assert "没给中文名" in body, body


# ---------------------------------------------------------------- ⑤ 生效长度档：四层链


def test_show_length_tier_follows_per_user_policy_over_config() -> None:
    """层②（该人永久策略）必须压过层③（`BOT_REPLY_DETAIL`）。

    现网钉 `detail`，若只读 `config.bot_reply_detail` 就永远报「详尽」——而她钉过
    「短一点」的人拿到的其实是简洁档 ⇒ 那一格成了谎报。
    """
    cfg = _config("1000000113", bot_reply_detail="detail")
    store = rp_module.shared_reply_policy_store(cfg)
    assert store is not None
    assert store.put(
        ReplyPolicy(
            person_key=person_reply_policy_key(sender_id=_ADMIN),
            length_mode="concise",
        )
    )
    body = _slash("show", config=cfg, sender=_ADMIN).body
    assert "详略：简洁" in body, body


def test_show_length_tier_runtime_override_beats_person_policy() -> None:
    """层①（运行时覆盖）压过层②——次序与 `chat.py` 那条链逐字同形。"""
    cfg = _config("1000000114", bot_reply_detail="detail")
    store = rp_module.shared_reply_policy_store(cfg)
    assert store is not None
    store.put(
        ReplyPolicy(
            person_key=person_reply_policy_key(sender_id=_ADMIN),
            length_mode="concise",
        )
    )
    body = _slash(
        "show",
        config=cfg,
        sender=_ADMIN,
        runtime_settings=_RuntimeOverrides({"BOT_REPLY_DETAIL": "auto"}),
    ).body
    assert "详略：适中" in body, body


def test_show_length_tier_reports_tier_name_only() -> None:
    """层③：没有上两层时读 `BOT_REPLY_DETAIL`，且只报档名。"""
    cfg = _config("1000000115", bot_reply_detail="detail")
    assert "详略：详尽" in _slash("show", config=cfg, sender=_ADMIN).body


# ---------------------------------------------------------------- ⑥ 裸命令与不认得的子命令


def test_bare_command_returns_usage_plus_current_tier_plus_pointer() -> None:
    """静默回归锁：新 elif 顶掉了旧的 help 兜底 ⇒ 用法/当前档/指路三件必须本模块自己交。"""
    cfg = _config("1000000116")
    _slash("deep", config=cfg, sender=_ADMIN)
    body = _slash("", config=cfg, sender=_ADMIN).body
    for verb in ("on", "deep", "off", "show"):
        assert verb in body, f"用法里缺子命令 {verb}：{body!r}"
    assert "深" in body, f"裸命令没交当前档读数：{body!r}"
    assert body.rstrip().endswith(INTIMATE_HELP_POINTER), body


def test_unrecognized_subcommand_says_so_and_moves_nothing() -> None:
    cfg = _config("1000000117")
    before = dict(_verdict(cfg, sender=_ADMIN))
    result = _slash("banana", config=cfg, sender=_ADMIN)
    assert "banana" in result.body, "没把用户原话回给他＝猜错了也无从发现"
    assert dict(_verdict(cfg, sender=_ADMIN)) == before, "不认得的子命令动了档位"
    assert INTIMATE_HELP_POINTER in result.body, result.body


# ---------------------------------------------------------------- ⑦ 结构锁：不许长第二真身


def test_control_module_reuses_the_single_effective_exit() -> None:
    """AST 锁：本模块只准调 `apply_intimate_switch`，不许自己上钉/自己选确认话。

    「开关的唯一生效出口」一旦被绕开，深浅档、作用域键、来源标签、隐私档四条判据
    就会各长出一份副本——那才是本波真正的事故面。
    """
    tree = ast.parse(_CONTROL_SRC.read_text(encoding="utf-8"))
    called: set[str] = set()
    assigned: set[str] = set()
    string_consts: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called.add(
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else "")
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assigned.add(target.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_consts.add(node.value)
    assert "apply_intimate_switch" in called, "开关腿没走唯一生效出口"
    for banned in ("apply_manual", "_manual_command_ack_text", "_manual_pin_source"):
        assert banned not in called, f"绕开出口自己上钉/自己选话：{banned}"
    for banned in (MANUAL_ON_REPLY, MANUAL_DEEP_ON_REPLY, MANUAL_OFF_REPLY):
        assert banned not in string_consts, f"确认话术被抄成第二真身：{banned!r}"
