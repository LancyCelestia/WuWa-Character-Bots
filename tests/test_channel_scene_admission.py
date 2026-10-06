"""频道那一轮：**叙述可达**与**露骨放行**是两道题（用户 2026-10-06 裁定「频道里可以写场景描写」）。

`content_route.explicit_allowed_for_session` 的 docstring 自己就写明它答的是
「露骨内容放行判定」：群走黑白名单、私聊默认放开、**其余会话类型（TG 频道/邮件等公开面）
不放行**。而注入缝 `_rp_scene_now`（`capabilities/chat.py`）今天把这同一枚准入门当成
「这一轮的描写轴可达吗」在用 ⇒ 后果：`channel` 轮的 `explicit_allowed` 恒 False，
她在频道里钉了 `scene` 也永远拿不到场景描写那一格。

她的裁定**只开第二问**，第一问照旧关着（频道是公开面，露骨内容仍不放行；六硬线与
09-17 内容政策一字不动）。本件因此判三件事：

① 腿一（今日必红）：频道轮、本人亲手钉了 `scene`（走真身写腿 `cr.write_narration_pin`），
   跑 `chat.build_chat_result` 真链路 ⇒ 必须吃到 `scene` 那一格样式段，而且是**公共面**
   那一格（`RP_STYLE_GROUP_BLOCKS[(scene, False)]`，不落笔身形／衣着），不是私聊那一格。
② 腿二：这次拆轴**不得**顺手给频道开出露骨放行——`explicit_allowed_for_session("channel", …)`
   仍 False（哪怕群在白名单、人在私聊白名单），亲密那一路（`_rp_intimate_now`／五维段／
   群侧亲密段）在频道仍然到不了，且内容政策那条腿的**读数不变**：同一句公开面必中的话，
   钉 scene 前后的 kind、边界出口正文、`public_safety*` 审计与吃到的样式格逐枚对拷
   （不是断言"没抛"；`prompt_*_chars` 那几枚带轮间方差，不当判据）。
③ 腿三：群／私聊／控制台／邮件四态**改前改后同值**——两把尺在那四型上逐格读数相等
   （名单矩阵全扫：群白／群非白／群黑／人腿／私聊黑白／console 不参与私聊名单／email），
   真链路的样式格也逐型对拷。

外加一枚**尺形锁**（禁在同一件事上留第二把尺）：注入缝两处谓词各读各的尺——
`_rp_scene_now` 只准读新的叙述可达尺、`_rp_intimate_now` 照旧只读 `content_route_session_eligible`；
露骨那把尺的函数体不许出现叙述集的名字；新尺内部**只转述**旧尺（零 `getattr(config…)` ⇒
本波不新建配置键、不新建第二张名单）。

会话类型一律取契约字段的规范值（`SessionType.CHANNEL.value == "channel"`），绝不靠会话键
前缀判（`guild_<g>_channel_<c>_<u>` 那形中央件 `session_keys` 明写"不判"）。

夹具纪律照 `tests/test_narration_group_scene_boundary.py`／`tests/test_narration_platform_wiring.py`
（规则 6／台账 #66★／#76★）：自建 `SimpleNamespace` 配置、库路径交 pytest `tmp_path`（仓库外、
Runtime 根外）、号全用合成值、聊天主链懒建的进程级策略 store 收成 None ⇒ 生产库零读写。
"""
from __future__ import annotations

import ast
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
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import LLMReply
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    content_route as cr,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    SHARED_CONTENT_ROUTE_ENGINE,
)

_ROOT = Path(__file__).resolve().parents[1]
_CHAT_SRC = (
    _ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "capabilities"
    / "chat.py"
)
_CR_SRC = (
    _ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "content_route.py"
)

_CHANNEL_UID = "7770004242"
_CHANNEL_KEY = "channel_-1001234567890"          # TG 频道/超级组的键形
_CHANNEL_PLATFORM = "telegram"
_GROUP_UID = "user-chan-scene"
_GROUP_ID = "977001"
_GROUP_SESSION = f"group:{_GROUP_ID}"
_PLAIN_TEXT = "那你会怎么陪我。"
#: 公开面规则（`content_safety._RULES` 里 scope="public" 的 `sexual` 那一枚）必中的句子，
#: 且不碰任何 scope="all" 硬线——这样"钉了 scene 之后出口有没有变"才量得到本波要防的那一格。
_EXPLICIT_TEXT = "把刚才那段露骨的继续写完。"


# ---------------------------------------------------------------- 夹具

_CONFIG_KEYS: dict[str, object] = {
    "bot_content_route_enabled": True,
    "bot_content_route_model": "grok-4.6",
    "bot_content_route_order": "grok-4.6,gemini-3.8-flash",
    "bot_content_route_words": "",
    "bot_content_route_intimate_threshold": 60.0,
    "bot_content_route_normal_threshold": 25.0,
    "bot_content_route_context_turns": 4,
    "bot_content_route_max_ttl_minutes": 120.0,
    "bot_content_route_idle_reset_minutes": 10.0,
    "bot_content_route_group_per_user_enabled": True,
    # 会话准入门的四张名单（2026-09-17／2026-10-02 裁定）——本波一枚都不新建，只复用。
    "bot_content_route_group_whitelist": [_GROUP_ID],
    "bot_content_route_group_blacklist": [],
    "bot_content_route_private_whitelist": [],
    "bot_content_route_private_blacklist": [],
}


def _config(db_path: str, **overrides: object) -> SimpleNamespace:
    base: dict[str, object] = dict(_CONFIG_KEYS)
    base["bot_addressing_preferences_db_path"] = db_path
    base.update(overrides)
    return SimpleNamespace(**base)


def _db_cfg(tmp_path: Path, tag: str, **overrides: object) -> SimpleNamespace:
    """每段判据各拿一本自己的临时库（`tmp_path` 仓库外、Runtime 根外，台账 #76★ 假红坑）。"""
    return _config(str(tmp_path / f"chan-scene-{tag}.sqlite3"), **overrides)


@pytest.fixture(autouse=True)
def _no_production_reply_policy_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """聊天主链懒建的进程级策略 store 收成 None ⇒ 本件零生产库读写（#66★／#76★）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character import reply_policy

    monkeypatch.setattr(reply_policy, "shared_reply_policy_store", lambda config: None)


@pytest.fixture(autouse=True)
def _clean_content_route_sessions() -> Any:
    """进程内档态逐用例换新（档态住 LRU，跨用例残留会把"这轮的 mode"读成上一轮的）。"""
    saved = SHARED_CONTENT_ROUTE_ENGINE._sessions
    SHARED_CONTENT_ROUTE_ENGINE._sessions = OrderedDict()
    yield SHARED_CONTENT_ROUTE_ENGINE
    SHARED_CONTENT_ROUTE_ENGINE._sessions = saved


# ---------------------------------------------------------------- 构造器（离线 mock）


class _CapturingProvider:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: object) -> LLMReply:
        self.messages = messages
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="m")


def _message(
    session_type: SessionType,
    session_id: str,
    uid: str,
    *,
    platform: str = "qq",
    group_id: str = "",
    text: str = _PLAIN_TEXT,
) -> IncomingMessage:
    return IncomingMessage(
        platform=platform,
        adapter="onebot" if platform == "qq" else platform,
        bot_id="bot-chan-scene",
        session_id=session_id,
        session_type=session_type,
        sender_id=uid,
        group_id=group_id,
        sender_roles=["user"],
        plain_text=text,
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=message.session_type,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _context(message: IncomingMessage) -> ContextBundle:
    return ContextBundle(
        request_id=message.request_id,
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default", action_brackets=True),
        memory_results=MemoryRetrievalResult(request_id=message.request_id),
        conversation_history=ConversationHistoryResult(request_id=message.request_id),
        knowledge_results=RetrievalResult(request_id=message.request_id),
        current_message=message.plain_text,
        sender_id=message.sender_id,
        session_id=message.session_id,
    )


def _turn(message: IncomingMessage, cfg: Any) -> tuple[str, Any]:
    """真链路一轮：返回 `(进模型的 system 段拼接, CapabilityResult)`。"""
    provider = _CapturingProvider()
    result = chat.build_chat_result(
        message,
        _decision(message),
        _context(message),
        llm_provider=provider,
        content_route_config=cfg,
    )
    joined = "\n".join(
        str(item.get("content") or "")
        for item in provider.messages
        if item.get("role") == "system"
    )
    return joined, result


def _channel_turn(cfg: Any, *, text: str = _PLAIN_TEXT) -> tuple[str, Any]:
    return _turn(
        _message(
            SessionType.CHANNEL, _CHANNEL_KEY, _CHANNEL_UID,
            platform=_CHANNEL_PLATFORM, text=text,
        ),
        cfg,
    )


def _pin(
    cfg: Any,
    session_id: str,
    uid: str,
    *,
    platform: str,
    conversation_type: str,
) -> None:
    """真身写腿钉一枚 `scene`（读写同口，键由轴心算，本件不猜第四形）。

    生产里这一腿由 `/bot 描写 scene` 命令面经 `narration_write_allowed` 的角色门调用；
    本件直接调写腿＝绕开别席正握着的 `intimate_control.py`，钉的形状与键完全一致。
    """
    assert cr.write_narration_pin(
        session_id,
        mode=cr.NARRATION_MODE_SCENE,
        sender_id=uid,
        config=cfg,
        platform=platform,
        conversation_type=conversation_type,
    ) is True, "描写钉没写进去＝下面的断言全在空跑"


def _pin_channel_scene(cfg: Any) -> None:
    _pin(cfg, _CHANNEL_KEY, _CHANNEL_UID, platform=_CHANNEL_PLATFORM,
         conversation_type=SessionType.CHANNEL.value)


# ---------------------------------------------------------------- 样式格读数（现算自真身表）


def _section_header(instruction: str) -> str:
    head, marker, _rest = instruction.partition("】")
    assert marker and head.startswith("【"), f"样式段缺【…】段落头：{instruction[:20]!r}"
    return f"{head}】"


def _cell(mode: str, intimate: bool, *, group: bool) -> str:
    """选择口现算的某一格（本件不抄第二段常量文本）。"""
    return chat.resolve_rp_style_block(mode, intimate=intimate, group=group)


def _all_cell_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    for group in (False, True):
        for mode in (cr.NARRATION_MODE_SPEECH, cr.NARRATION_MODE_SCENE):
            for intimate in (False, True):
                block = _cell(mode, intimate, group=group)
                headers.setdefault(_section_header(block), block)
    return headers


def _style_cell_of(joined: str) -> str:
    """这一轮实际吃到的是哪一格（**恰好一枚**命中；多枚＝段落头撞车，本件的负锁会空跑）。"""
    headers = _all_cell_headers()
    assert len(headers) >= 4, f"样式格枚举只剩 {len(headers)} 枚＝选择表被改窄"
    hits = [header for header in headers if header in joined]
    assert len(hits) == 1, f"注入的样式格必须恰好一枚，实得 {hits}"
    return hits[0]


# ================================================================ ① 腿一：频道拿得到 scene 那一格


def test_channel_scene_pin_reaches_the_scene_cell_in_the_real_chain(tmp_path: Path) -> None:
    """频道轮钉了 `scene` ⇒ 吃到**公共面**那一格（今日缺这一格＝本件的红）。"""
    cfg = _db_cfg(tmp_path, "leg1")
    before, _ = _channel_turn(cfg)
    assert _style_cell_of(before) == _section_header(_cell(
        cr.NARRATION_MODE_SPEECH, False, group=True
    )), "夹具没清干净：没钉之前就已经是 scene，后面的断言会在空跑"

    _pin_channel_scene(cfg)
    joined, result = _channel_turn(cfg)
    expected = chat.RP_STYLE_GROUP_BLOCKS[(cr.NARRATION_MODE_SCENE, False)]
    assert _style_cell_of(joined) == _section_header(expected), (
        "频道里本人亲手钉了 scene 却仍吃只说话那一格＝叙述可达被露骨放行那把尺替她答了"
    )
    assert result.kind == "text" and str(result.body).strip(), "真链路没跑到底"
    # 频道是公共面：拿到的必须是群侧那一格，不是私聊那一格（身形／衣着照旧不落笔）。
    assert _section_header(chat.NORMAL_SCENE_STYLE_INSTRUCTION) not in joined


def test_channel_scene_reading_is_what_the_axis_itself_reports(tmp_path: Path) -> None:
    """轴心读数与注入缝同判：频道轮的 `narration_mode` 早就是 scene、`eligible` 早就是 False。

    这一腿把"红"钉在**会话准入门**那一格上，而不是钉在轴心或授予尺上：拆轴只准动前者。
    """
    cfg = _db_cfg(tmp_path, "leg1-axis")
    _pin_channel_scene(cfg)
    ctx = cr.resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type=SessionType.CHANNEL.value,
        sender_id=_CHANNEL_UID,
        session_key=_CHANNEL_KEY,
        config=cfg,
        platform=_CHANNEL_PLATFORM,
    )
    assert ctx["narration_mode"] == cr.NARRATION_MODE_SCENE, ctx
    assert cr.grants_intimate_narration(str(ctx["narration_source"])) is True, ctx
    assert ctx["eligible"] is False, ctx


# ================================================================ ② 腿二：露骨面照旧关着


def test_channel_never_gets_explicit_content_admission(tmp_path: Path) -> None:
    """频道仍是公开面：白名单群号＋私聊白名单的人一起交进来也换不来露骨放行。"""
    cfg = _db_cfg(
        tmp_path,
        "leg2-lists",
        bot_content_route_private_whitelist=[_CHANNEL_UID],
    )
    for group_id in ("", _GROUP_ID):
        for sender in ("", _CHANNEL_UID, _GROUP_UID):
            assert cr.explicit_allowed_for_session(
                SessionType.CHANNEL.value, group_id, cfg, sender_id=sender
            ) is False, f"频道拿到了露骨放行（group_id={group_id!r} sender={sender!r}）"


def test_channel_scene_turn_still_denies_the_intimate_leg(tmp_path: Path) -> None:
    """钉了 scene 的频道轮：亲密那一路（档态／五维段／群侧亲密段）一格都不许变宽。"""
    cfg = _db_cfg(tmp_path, "leg2-intimate")
    _pin_channel_scene(cfg)
    ctx = cr.resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type=SessionType.CHANNEL.value,
        sender_id=_CHANNEL_UID,
        session_key=_CHANNEL_KEY,
        config=cfg,
        platform=_CHANNEL_PLATFORM,
    )
    assert ctx["eligible"] is False, ctx
    assert ctx["mode"] != cr.MODE_INTIMATE, ctx
    joined, _result = _channel_turn(cfg)
    assert _section_header(chat.INTIMATE_RP_STYLE_INSTRUCTION) not in joined
    assert (
        _section_header(chat.RP_STYLE_GROUP_BLOCKS[(cr.NARRATION_MODE_SCENE, True)])
        not in joined
    ), "频道拿到了私密相处那一格＝拆轴顺手把露骨面也放开了"


def test_channel_content_policy_outcome_is_byte_identical_with_and_without_the_pin(
    tmp_path: Path
) -> None:
    """内容政策那条腿**读数对拷**：同一句公开面必中的话，钉 scene 前后的出口与审计逐字相同。

    判的不是"没抛异常"，是两枚 `CapabilityResult` 的 kind/正文/审计标签全等 ⇒ 拆轴没有
    把 `assess_public_content(explicit_allowed=…)` 那一路换成叙述尺。
    """
    cfg = _db_cfg(tmp_path, "leg2-policy")
    _joined_before, before = _channel_turn(cfg, text=_EXPLICIT_TEXT)
    _pin_channel_scene(cfg)
    _joined_after, after = _channel_turn(cfg, text=_EXPLICIT_TEXT)

    assert "public_safety" in before.audit_tags, before.audit_tags
    assert any(str(tag).startswith("public_safety:") for tag in before.audit_tags)
    assert before.kind == after.kind
    assert str(before.body) == str(after.body), (
        "钉了 scene 之后频道轮的边界出口换了文＝叙述尺漏进了内容政策那条腿"
    )
    assert _safety_tags(before) == _safety_tags(after), (
        f"安全审计漂移：{_safety_tags(before)} vs {_safety_tags(after)}"
    )
    # 被拦的那一轮照样拿不到"展开描写"的鼓励（`safety.action == "allow"` 那一支没被拆轴绕过）。
    assert _style_cell_of(_joined_before) == _style_cell_of(_joined_after)
    assert _style_cell_of(_joined_after) == _section_header(
        _cell(cr.NARRATION_MODE_SPEECH, False, group=True)
    )


def _safety_tags(result: Any) -> list[str]:
    """审计里**与安全判定有关**的那几枚（`prompt_*_chars` 那几格带轮间方差，不是判据）。"""
    return [str(tag) for tag in result.audit_tags if str(tag).startswith("public_safety")]


# ================================================================ ③ 腿三：四态改前改后同值


#: (标签, 会话类型, 群号, 发送者, 配置覆盖) —— 覆盖 `explicit_allowed_for_session` 每条分支：
#: 群白命中／群白未命中／群黑永远赢／白名单空＝整群关闭／人腿（私聊白名单）／人腿被私聊黑关掉／
#: 私聊默认放开／私聊白名单内外／私聊黑名单／console 不参与私聊名单／email 与未知型。
_ADMISSION_CASES: tuple[tuple[str, str, str, str, dict[str, object]], ...] = (
    ("group-whitelisted", SessionType.GROUP.value, _GROUP_ID, _GROUP_UID, {}),
    ("group-not-whitelisted", SessionType.GROUP.value, "900002", _GROUP_UID, {}),
    ("group-blacklisted", SessionType.GROUP.value, _GROUP_ID, _GROUP_UID,
     {"bot_content_route_group_blacklist": [_GROUP_ID]}),
    ("group-empty-whitelist", SessionType.GROUP.value, _GROUP_ID, _GROUP_UID,
     {"bot_content_route_group_whitelist": []}),
    ("group-person-leg", SessionType.GROUP.value, "900002", _GROUP_UID,
     {"bot_content_route_private_whitelist": [_GROUP_UID]}),
    ("group-person-leg-blacklisted", SessionType.GROUP.value, "900002", _GROUP_UID,
     {"bot_content_route_private_whitelist": [_GROUP_UID],
      "bot_content_route_private_blacklist": [_GROUP_UID]}),
    ("group-person-leg-empty-private-whitelist", SessionType.GROUP.value, "900002", _GROUP_UID,
     {"bot_content_route_private_blacklist": [_GROUP_UID]}),
    ("group-no-sender", SessionType.GROUP.value, _GROUP_ID, "", {}),
    ("private-default-open", SessionType.PRIVATE.value, "", _GROUP_UID, {}),
    ("private-no-sender", SessionType.PRIVATE.value, "", "", {}),
    ("private-whitelist-hit", SessionType.PRIVATE.value, "", _GROUP_UID,
     {"bot_content_route_private_whitelist": [_GROUP_UID]}),
    ("private-whitelist-miss", SessionType.PRIVATE.value, "", "99999",
     {"bot_content_route_private_whitelist": [_GROUP_UID]}),
    ("private-blacklist-wins", SessionType.PRIVATE.value, "", _GROUP_UID,
     {"bot_content_route_private_blacklist": [_GROUP_UID]}),
    ("console", SessionType.CONSOLE.value, "", _GROUP_UID, {}),
    ("console-with-private-lists", SessionType.CONSOLE.value, "", "99999",
     {"bot_content_route_private_whitelist": [_GROUP_UID],
      "bot_content_route_private_blacklist": [_GROUP_UID]}),
    ("email", SessionType.EMAIL.value, "", _GROUP_UID, {}),
    ("email-with-person-leg", SessionType.EMAIL.value, _GROUP_ID, _GROUP_UID,
     {"bot_content_route_private_whitelist": [_GROUP_UID]}),
    ("unknown-type", "", "", _GROUP_UID, {}),
)


def test_the_narration_ruler_copies_the_explicit_ruler_for_every_type_but_channel(
    tmp_path: Path,
) -> None:
    """两把尺在**非频道**的每一型、每一种名单组合上读数逐格相等（对拷，不是断言"没抛"）。

    新尺在那四型上就是把入参原样转给旧尺 ⇒ 群／私聊／控制台／邮件的既有语义逐字不变；
    唯一的差别只准出现在 `channel` 那一格（下一枚测试点名它）。
    """
    mismatches: list[str] = []
    for label, stype, group_id, sender, overrides in _ADMISSION_CASES:
        case_cfg = _config(str(tmp_path / f"chan-scene-matrix-{label}.sqlite3"), **overrides)
        old = cr.explicit_allowed_for_session(stype, group_id, case_cfg, sender_id=sender)
        new = cr.narration_allowed_for_session(stype, group_id, case_cfg, sender_id=sender)
        if bool(new) != bool(old):
            mismatches.append(
                f"{label}: type={stype!r} group={group_id!r} sender={sender!r} "
                f"露骨放行={old} 叙述可达={new}"
            )
    assert not mismatches, "非频道型上两把尺分叉＝改写了裁定范围之外的语义：\n" + "\n".join(
        mismatches
    )


def test_channel_is_the_only_new_cell_narration_reachable_explicit_denied(
    tmp_path: Path,
) -> None:
    """十格对照表的那两格：频道 ⇒ 叙述可达 True、露骨放行 False（其余四型两把尺同值）。"""
    cfg = _db_cfg(tmp_path, "leg3-channel-cell")
    assert cr.narration_allowed_for_session(
        SessionType.CHANNEL.value, "", cfg, sender_id=_CHANNEL_UID
    ) is True
    assert cr.explicit_allowed_for_session(
        SessionType.CHANNEL.value, "", cfg, sender_id=_CHANNEL_UID
    ) is False


#: 真链路逐型读数：型 → (会话键, 本人号, 平台, 群号, 期望那一格)。期望一律**现算**自选择表。
_CHAIN_CASES: tuple[tuple[str, str, str, str, str, str, bool], ...] = (
    # (标签, 会话类型, 会话键, 本人号, 平台, 群号, 期望是否公共面那一侧)
    ("group-whitelisted", SessionType.GROUP.value, _GROUP_SESSION, _GROUP_UID, "qq", _GROUP_ID, True),
    ("private", SessionType.PRIVATE.value, "7770005151", "7770005151", "qq", "", False),
    ("console", SessionType.CONSOLE.value, "console_7770006060", "7770006060", "qq", "", False),
)


@pytest.mark.parametrize(
    "label,stype,session_id,uid,platform,group_id,expects_group_side",
    _CHAIN_CASES,
    ids=[case[0] for case in _CHAIN_CASES],
)
def test_scene_cell_for_non_channel_types_is_unchanged(
    label: str,
    stype: str,
    session_id: str,
    uid: str,
    platform: str,
    group_id: str,
    expects_group_side: bool,
    tmp_path: Path,
) -> None:
    """钉了 scene 的群／私聊/控制台轮：吃到的那一格与拆轴前**同值**（白名单群照旧开、其余照旧）。

    `label` 只用于报错可读；判据是"这一格恰好等于选择口在该型下应当给出的那一格"。
    """
    cfg = _db_cfg(tmp_path, f"leg3-chain-{label}")
    _pin(cfg, session_id, uid, platform=platform, conversation_type=stype)
    message = _message(
        SessionType(stype), session_id, uid, platform=platform, group_id=group_id
    )
    joined, _result = _turn(message, cfg)
    expected = chat.RP_STYLE_GROUP_BLOCKS if expects_group_side else chat.RP_STYLE_BLOCKS
    assert _style_cell_of(joined) == _section_header(
        expected[(cr.NARRATION_MODE_SCENE, False)]
    ), f"{label} 那一格被本波动过"


def test_email_and_unlisted_group_stay_on_the_speech_cell(tmp_path: Path) -> None:
    """邮件面（公开）与未获准的群：钉了 scene 也仍留在只说话那一格——旧语义逐字不变。"""
    cfg = _db_cfg(tmp_path, "leg3-denied")
    _pin(cfg, "email_7770007177", "7770007177", platform="qq",
         conversation_type=SessionType.EMAIL.value)
    joined, _result = _turn(
        _message(SessionType.EMAIL, "email_7770007177", "7770007177"), cfg
    )
    assert _style_cell_of(joined) == _section_header(
        _cell(cr.NARRATION_MODE_SPEECH, False, group=False)
    )

    other = _db_cfg(tmp_path, "leg3-denied-group", bot_content_route_group_whitelist=[])
    _pin(other, _GROUP_SESSION, _GROUP_UID, platform="qq",
         conversation_type=SessionType.GROUP.value)
    joined2, _r2 = _turn(
        _message(SessionType.GROUP, _GROUP_SESSION, _GROUP_UID, group_id=_GROUP_ID), other
    )
    assert _style_cell_of(joined2) == _section_header(
        _cell(cr.NARRATION_MODE_SPEECH, False, group=True)
    )


# ================================================================ ④ 尺形锁：两问两尺


def _assignment_source(src: str, target: str) -> str:
    """按名字取那一处赋值（`_rp_scene_now` 住在 `build_chat_result` **体内**，故全树 walk）。"""
    found = [
        node
        for node in ast.walk(ast.parse(src, filename="<src>"))
        if isinstance(node, ast.Assign)
        and any(isinstance(item, ast.Name) and item.id == target for item in node.targets)
    ]
    assert len(found) == 1, f"`{target}` 应恰好一处赋值，现算 {len(found)} 处（多处＝先同步本件）"
    segment = ast.get_source_segment(src, found[0])
    assert segment is not None, f"{target} 取不到源码段"
    return segment


def _function_source(src: str, name: str) -> str:
    tree = ast.parse(src, filename="<src>")
    found = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(found) == 1, f"真身里 `def {name}` 应恰好一处，现算 {len(found)} 处"
    segment = ast.get_source_segment(src, found[0])
    assert segment is not None, f"{name} 取不到源码段"
    return segment


def test_the_seam_reads_two_different_rulers_for_two_questions() -> None:
    """`_rp_scene_now` 改读叙述尺；`_rp_intimate_now` 照旧读露骨/准入尺——两问不许并成一枚。"""
    src = _CHAT_SRC.read_text(encoding="utf-8")
    scene = _assignment_source(src, "_rp_scene_now")
    assert "narration_allowed_for_session(" in scene, (
        "`_rp_scene_now` 没读新的叙述可达尺＝频道那一格还是由露骨放行那把尺替她答"
    )
    assert "content_route_session_eligible" not in scene, (
        "`_rp_scene_now` 仍在读会话准入门＝同一件事上留了两把尺"
    )
    intimate = _assignment_source(src, "_rp_intimate_now")
    assert "content_route_session_eligible" in intimate, "亲密/露骨那条腿被顺手改道了"
    assert "narration_allowed_for_session" not in intimate, (
        "露骨那条腿开始读叙述尺＝把②的放宽漏进了①"
    )


def test_the_new_ruler_delegates_and_creates_no_second_list() -> None:
    """新尺内部只转述旧尺：不读配置（零新键）、不抄第二张名单；旧尺不许引用叙述集。"""
    src = _CR_SRC.read_text(encoding="utf-8")
    new_ruler = _function_source(src, "narration_allowed_for_session")
    assert "explicit_allowed_for_session(" in new_ruler, (
        "新尺自己另算了一遍名单＝第二把尺（本波要求复用既有配置键、不新建）"
    )
    assert "getattr(" not in new_ruler, "新尺里读了配置字段＝本波不该新建配置键"
    old_ruler = _function_source(src, "explicit_allowed_for_session")
    assert "_NARRATION" not in old_ruler, (
        "露骨放行那把尺开始引用叙述集＝两轴并成一轴，频道会被它一起放开"
    )
