"""等值锁：`apply_intimate_switch(...)` 与「亲密模式 开/深开/关」整句路径逐字节全等。

背景：`build_chat_result` 里那句整句命令命中后是一段就地流程（算作用域键 → 定
source → 上钉 → 选确认话 → 打 scope 标签并组装 `CapabilityResult`）。本波把它抽成
模块级 `apply_intimate_switch`，供将来的斜杠面（on/deep/off）复用同一生效出口。
纯重构 ⇒ **回执文本 / `privacy_level` / `audit_tags` 三者必须与改前逐字节一致**，
本件就是那把尺。

期望值来源（不是凭印象写的）：重构**前**用同一套夹具（形状照
`tests/test_intimate_group_switch_delivery.py` 的 `_config`/`_group_message`/
`_private_message`/`_turn`）对整句路径实跑抓取，11 组输入（会话形态 × 角色 ×
per_user × mode × tier）的 `body`/`privacy_level`/`audit_tags` 原样录在下面
`_CASES` 里。抓取脚本＝一次性、仓库外（`%TEMP%`），产物＝本文件这些字面量。

每枚用例量两条腿：
① 整句路径（`build_chat_result`）今天仍然给出录下来的那一份 ⇒ 证明搬家没改动行为；
② 同一组输入直接喂 `apply_intimate_switch` ⇒ 证明抽出来的出口给的是同一份读数。
两腿还互相比对（同一次运行内），任一侧漂了都红。

「不受理」那一格（群聊 + 普通成员 + `per_user` 关）两腿都量：抽出的函数必须返回
None，整句路径必须落回普通聊天（走了大模型、没有 `content_route` 标签）。

夹具卫生（规则 6 + 现网事故教训）：
- 称谓偏好 store 的缺省路径会落到生产运行数据根 ⇒ 每枚用例自带 tmp 绝对路径；
- `/bot reply` 面（`shared_reply_policy_store`）**结构性**指到 tmp：生产 reply_policy
  库今天已被别的测试写过、Runtime 里没有任何备份，绝不允许第二次写入。
"""

from __future__ import annotations

import inspect
import os
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
    apply_intimate_switch,
    build_chat_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    reply_policy as rp_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    ReplyPolicyStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import LLMReply
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_TIER_L1,
    INTIMATE_TIER_L2,
    INTIMATE_TIER_NONE,
    MODE_INTIMATE,
    MODE_NORMAL,
    SHARED_CONTENT_ROUTE_ENGINE,
    match_intimate_command,
    resolve_intimate_context,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    build_session_key,
    private_session_key,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CHAT_SOURCE = (
    _REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "capabilities"
    / "chat.py"
)

# DATAFIX：所有涉库键一律显式给仓库外 tmp 绝对路径（缺省值指向现网运行数据根）。
_TMP_DATA_DIR = tempfile.mkdtemp(prefix="thyg-intsw-")

_ADMIN = "3865067623"
_MEMBER_A = "2950687868"

# 一用例一枚群号：共享引擎是进程级单例，管理员的全群钉会染后面用例的读数。
_GROUP_IDS = {
    "group-admin-on": "700200001",
    "group-admin-deep": "700200002",
    "group-admin-off": "700200003",
    "group-member-on": "700200004",
    "group-member-deep": "700200005",
    "group-member-off": "700200006",
    "group-member-peruseroff-on": "700200007",
    "group-admin-peruseroff-deep": "700200008",
    "private-on": "700200009",
    "private-deep": "700200010",
    "private-off": "700200011",
}

# 期望值＝重构前整句路径的实跑抓取（见模块 docstring），一字未改。
_CASES: list[dict[str, Any]] = [
    {
        "id": "group-admin-on",
        "session_type": "group",
        "roles": ["admin", "super_admin"],
        "per_user": True,
        "text": "亲密模式 开",
        "accepted": True,
        "body": "好，这一段对话我会换一种更贴近你的方式来聊。",
        "privacy": PrivacyLevel.GROUP,
        "tags": ["content_route", "manual:intimate", "tier:l1", "scope:group"],
    },
    {
        "id": "group-admin-deep",
        "session_type": "group",
        "roles": ["admin", "super_admin"],
        "per_user": True,
        "text": "亲密模式 深开",
        "accepted": True,
        "body": "嗯，这一段我不收着了，你说什么我都接着。",
        "privacy": PrivacyLevel.GROUP,
        "tags": ["content_route", "manual:intimate", "tier:l2", "scope:group"],
    },
    {
        "id": "group-admin-off",
        "session_type": "group",
        "roles": ["admin", "super_admin"],
        "per_user": True,
        "text": "亲密模式 关",
        "accepted": True,
        "body": "嗯，回到平时这样聊就好。",
        "privacy": PrivacyLevel.GROUP,
        "tags": ["content_route", "manual:normal", "tier:none", "scope:group"],
    },
    {
        "id": "group-member-on",
        "session_type": "group",
        "roles": ["user"],
        "per_user": True,
        "text": "亲密模式 开",
        "accepted": True,
        "body": "好，这一段对话我会换一种更贴近你的方式来聊。",
        "privacy": PrivacyLevel.GROUP,
        "tags": ["content_route", "manual:intimate", "tier:l1", "scope:user"],
    },
    {
        "id": "group-member-deep",
        "session_type": "group",
        "roles": ["user"],
        "per_user": True,
        "text": "亲密模式 深开",
        "accepted": True,
        "body": "嗯，这一段我不收着了，你说什么我都接着。",
        "privacy": PrivacyLevel.GROUP,
        "tags": ["content_route", "manual:intimate", "tier:l2", "scope:user"],
    },
    {
        "id": "group-member-off",
        "session_type": "group",
        "roles": ["user"],
        "per_user": True,
        "text": "亲密模式 关",
        "accepted": True,
        "body": "嗯，回到平时这样聊就好。",
        "privacy": PrivacyLevel.GROUP,
        "tags": ["content_route", "manual:normal", "tier:none", "scope:user"],
    },
    {
        # 群聊 + 普通成员 + per_user 关 ⇒ 作用域键 None ⇒ 不受理，落回普通聊天。
        "id": "group-member-peruseroff-on",
        "session_type": "group",
        "roles": ["user"],
        "per_user": False,
        "text": "亲密模式 开",
        "accepted": False,
        "body": "好，这一段对话我会换一种更贴近你的方式来聊。",
        "privacy": PrivacyLevel.GROUP,
        "tags": ["content_route", "manual:intimate", "tier:l1", "scope:user"],
    },
    {
        # 管理员腿不看 per_user：per_user 关时依然拨群键。
        "id": "group-admin-peruseroff-deep",
        "session_type": "group",
        "roles": ["admin"],
        "per_user": False,
        "text": "亲密模式 深开",
        "accepted": True,
        "body": "嗯，这一段我不收着了，你说什么我都接着。",
        "privacy": PrivacyLevel.GROUP,
        "tags": ["content_route", "manual:intimate", "tier:l2", "scope:group"],
    },
    {
        "id": "private-on",
        "session_type": "private",
        "roles": ["user"],
        "per_user": True,
        "text": "亲密模式 开",
        "accepted": True,
        "body": "好，这一段对话我会换一种更贴近你的方式来聊。",
        "privacy": PrivacyLevel.PERSONAL,
        "tags": ["content_route", "manual:intimate", "tier:l1", "scope:self"],
    },
    {
        "id": "private-deep",
        "session_type": "private",
        "roles": ["user"],
        "per_user": True,
        "text": "亲密模式 深开",
        "accepted": True,
        "body": "嗯，这一段我不收着了，你说什么我都接着。",
        "privacy": PrivacyLevel.PERSONAL,
        "tags": ["content_route", "manual:intimate", "tier:l2", "scope:self"],
    },
    {
        "id": "private-off",
        "session_type": "private",
        "roles": ["admin", "super_admin"],
        "per_user": False,
        "text": "亲密模式 关",
        "accepted": True,
        "body": "嗯，回到平时这样聊就好。",
        "privacy": PrivacyLevel.PERSONAL,
        "tags": ["content_route", "manual:normal", "tier:none", "scope:self"],
    },
]


def _config(group: str, **overrides: object) -> SimpleNamespace:
    """会话门配置替身（形状照 `test_intimate_group_switch_delivery._config`）。"""
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
        # 两条自动腿关掉：本件只测「人说了一句开关」，自动档会污染读数。
        "bot_content_route_l1_auto_enabled": False,
        "bot_content_route_l1_auto_min_tier": 1,
        "bot_master_love_enabled": False,
        "bot_master_love_admins": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _CapturingProvider:
    """离线 LLM 替身：留下「这一轮到底有没有走到大模型」。"""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list[dict[str, Any]], **kwargs: object) -> LLMReply:
        self.calls += 1
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="fake")


def _message(case: dict[str, Any], group: str) -> IncomingMessage:
    sender = _ADMIN if "admin" in [str(r) for r in case["roles"]] else _MEMBER_A
    text = str(case["text"])
    if case["session_type"] == "group":
        return IncomingMessage(
            platform="qq",
            adapter="onebot",
            bot_id="3958874605",
            session_id=build_session_key(group, sender),
            session_type=SessionType.GROUP,
            sender_id=sender,
            group_id=group,
            sender_roles=list(case["roles"]),
            plain_text=text,
            command_text=text,
            mentions_bot=True,
            raw_segments=[{"type": "text", "data": {"text": text}}],
        )
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
    """复刻能力入口的隐私夹取（群腿=GROUP）：D1 事故的那一格只有这样才能量到。"""
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


def _route_args(
    message: IncomingMessage, cfg: SimpleNamespace
) -> dict[str, Any]:
    """`build_chat_result` 交给抽出口的那一组入参（键形照中央件派生，不另立判据）。"""
    session_type = str(getattr(message.session_type, "value", ""))
    parsed = match_intimate_command(message.command_text or message.plain_text)
    assert parsed is not None, "夹具文本没被整句口认出来 ⇒ 本件的期望值失去可比性"
    mode, tier = parsed
    ctx = resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type=session_type,
        group_id=str(message.group_id or ""),
        sender_id=message.sender_id,
        session_key=message.session_id,
        config=cfg,
    )
    return {
        "mode": mode,
        "tier": tier,
        "session_type": session_type,
        "session_key": str(message.session_id or ""),
        "route_key": str(ctx.get("route_key") or message.session_id),
        "sender_roles": message.sender_roles,
        "per_user_enabled": bool(
            getattr(cfg, "bot_content_route_group_per_user_enabled", True)
        ),
        "config": cfg,
        "request_id": message.request_id,
        "context": _context(message),
    }


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """进程级单例账本每枚用例换新的 + reply_policy 共享 store 结构性指 tmp。"""
    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "_sessions", OrderedDict())
    tmp_store = ReplyPolicyStore(Path(tmp_path) / "reply_policy.sqlite3")
    monkeypatch.setattr(rp_module, "shared_reply_policy_store", lambda _cfg: tmp_store)


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_extracted_function_matches_full_sentence_path(case: dict[str, Any]) -> None:
    group = _GROUP_IDS[case["id"]]
    cfg = _config(group, bot_content_route_group_per_user_enabled=case["per_user"])
    message = _message(case, group)
    provider = _CapturingProvider()

    # ① 整句路径（改前真身的读数，今天必须仍是这一份）
    full = build_chat_result(
        message,
        _decision(message),
        _context(message),
        llm_provider=provider,
        content_route_config=cfg,
    )
    # ② 抽出来的出口，同一组输入
    extracted = apply_intimate_switch(**_route_args(message, cfg))

    if not case["accepted"]:
        assert extracted is None, "不受理那一格抽出口自己上了钉（放宽了门）"
        assert full.body != case["body"], "不受理那一格却给出了确认话 ⇒ 门被绕过"
        assert "content_route" not in (full.audit_tags or []), full.audit_tags
        assert provider.calls >= 1, "不受理的开关句没落回普通聊天"
        return

    assert provider.calls == 0, "整句路径走进了大模型 ⇒ 短路支被搬坏了"
    assert full.body == case["body"], (full.body, case["body"])
    assert full.privacy_level is case["privacy"], full.privacy_level
    assert list(full.audit_tags or []) == case["tags"], full.audit_tags
    assert set(full.audit_tags or []) == set(case["tags"])

    assert extracted is not None, "受理那一格抽出口返回了 None（开关失效）"
    assert extracted.body == full.body
    assert extracted.privacy_level is full.privacy_level
    assert list(extracted.audit_tags or []) == list(full.audit_tags or [])
    # 契约其余格也是逐字搬过去的（`debug_id` 每次不同 ⇒ 不参与比对）
    assert extracted.kind == full.kind
    assert extracted.capability_id == full.capability_id
    assert extracted.risk_level is full.risk_level
    assert extracted.request_id == full.request_id


def test_extracted_function_does_not_parse_message_text() -> None:
    """设计合同：抽出口只吃已解析好的 mode/tier/上下文，函数内不读消息原文。

    将来的斜杠面（on/deep/off）自己解析、复用同一个生效出口 ⇒ 这里绝不能藏第二套
    解析，否则两个命令面会各自漂。
    """
    source = inspect.getsource(apply_intimate_switch)
    for token in ("plain_text", "command_text", "match_intimate_command", "message"):
        assert token not in source, f"抽出口里出现了 {token} ⇒ 在重做解析"


def test_extracted_function_still_defers_privacy_to_context() -> None:
    """D1 教训的搬家版：抽出口里的 `privacy_level` 仍须引 `context.privacy_level`。"""
    import ast

    tree = ast.parse(_CHAT_SOURCE.read_text(encoding="utf-8"))
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "apply_intimate_switch"
    )
    calls = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "CapabilityResult"
    ]
    assert len(calls) == 1, f"回执构造点应只有一处，实得 {len(calls)}"
    privacy = next(
        (kw.value for kw in calls[0].keywords if kw.arg == "privacy_level"), None
    )
    assert isinstance(privacy, ast.Attribute) and privacy.attr == "privacy_level"
    assert isinstance(privacy.value, ast.Name) and privacy.value.id == "context", (
        f"隐私档又变成硬写值了：{ast.dump(privacy) if privacy else None}"
    )


def test_manual_modes_and_tiers_are_the_ones_parsed() -> None:
    """夹具自检：三句命令解析出的 (mode, tier) 与期望标签里的档位一致。

    不检这一格，上面那些字面量可能在命令面改动后悄悄失去可比性。
    """
    assert match_intimate_command("亲密模式 开") == (MODE_INTIMATE, INTIMATE_TIER_L1)
    assert match_intimate_command("亲密模式 深开") == (MODE_INTIMATE, INTIMATE_TIER_L2)
    assert match_intimate_command("亲密模式 关") == (MODE_NORMAL, INTIMATE_TIER_NONE)
    for case in _CASES:
        parsed = match_intimate_command(str(case["text"]))
        assert parsed is not None
        tier_tag = case["tags"][2]
        assert tier_tag == f"tier:{parsed[1] or 'none'}", (case["id"], tier_tag, parsed)
        assert case["tags"][1] == f"manual:{parsed[0]}"
