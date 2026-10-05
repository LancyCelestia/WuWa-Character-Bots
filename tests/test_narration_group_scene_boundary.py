"""裁定 I-3＝丙（2026-10-04 深夜）：**群聊那一侧的 `scene` 不落笔身形／衣着**。

用户裁定的原话口径（丙）：群是公共空间、旁人也在看 ⇒ 群内那一轮 `scene` 不写「身形／衣着」
这两类**落在身体与穿戴上**的细部；私聊（本人那一路）照旧写。其余四维（语言／动作／神态／
心理）与环境段**群内照写**，长度档一字不动（600–1200 的铺写照样生效）。边界**只**收这两类，
不许顺手把动作／神态收掉，也不许动 R-18 六硬线与 09-17 内容政策（那是另一本账）。

本件判的三件事：

① **选择面**——群侧那一张表与私聊那一张表键形键集完全相同；只有两格 `scene` 随会话面变，
   两格 `speech` 在两种会话面下**同一个对象**（＝一字未动）。
② **文案面**——群侧那两段的成对锁：许可半句里一枚身形/衣着词都不许有，禁令半句必须**点名**
   这两类且每枚恰好出现一次（口径同 `test_reply_policy_permanent.py::_corporal_axis_violations`
   的逐块自洽，绝不跨块比对——见该件里那四枚注毒锚点）。反向也判：许可半句仍要点名四维与环境句
   （证明本席只收了裁定点名的那两类，没有顺手收窄）。
③ **注入面**——真跑 `build_chat_result`：白名单群里钉了 `scene` 的那一轮吃到的是群侧段、
   同一个人的私聊轮吃到的仍是原段；群内亲密授予轮吃到群侧亲密段；长度行与私聊 scene 轮
   **同档**（升格腿没被本波碰过）。

词表全部从真身 import／派生，本件不抄第二份（规则 10）：
身形细部 ← `chat.SCENE_CORPORAL_TERMS`｜衣着 ← `chat.NORMAL_SCENE_CLOTHING_TERMS`｜
环境句 ← `chat.SCENE_ENVIRONMENT_MARKER`｜描写四维 ← `test_reply_policy_permanent.py::_SCENE_DIMENSIONS`｜
红线尺 ← `security/content_safety.py` 两把尺 + `test_copy_redline_gate.py::R18_TERMS`｜
群聊出站尺 ← `domains/render/reviewer.py::_PUBLIC_OUTPUT_UNSAFE`。

生产库隔离（台账 #66★／#76★）：所有轮次都走 `build_chat_result`，`.env` 的 Runtime 根指向
生产 ⇒ autouse 夹具把 `shared_reply_policy_store` 收成 None；一枚 `_config()` 一本临时库，
钉不落生产（路径走 `tempfile`，仓库外、Runtime 根外）。
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

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

# 红线尺与词表＝真身 import（绝不在测试里抄第二份；抄了就不叫锁，叫另一份会漂移的散文）
from plugins.bot_unified_runtime.domains.chat_reply.security.content_safety import (
    _BODY_TYPE_PATTERN,
    _SEXUAL_CONTEXT_RE,
)
from plugins.bot_unified_runtime.domains.render.reviewer import _PUBLIC_OUTPUT_UNSAFE

_REPO = Path(__file__).resolve().parents[1]
_TMP_DATA_DIR = tempfile.mkdtemp(prefix="thyg-grp-scene-")
_GROUP_UID = "user-grp"
_GROUP_ID = "977001"
_GROUP_SESSION = f"group:{_GROUP_ID}"


def _load_sibling(relative: str):
    """按路径加载同树那件真身（只取词表，不复制第二份——口径同 test_narration_axis_styles.py）。"""
    path = _REPO / "tests" / relative
    spec = importlib.util.spec_from_file_location(f"_grp_scene_src_{path.stem}", path)
    assert spec is not None and spec.loader is not None, f"同树真身加载失败：{path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_SCENE_DIMENSIONS: tuple[str, ...] = _load_sibling(
    "test_reply_policy_permanent.py"
)._SCENE_DIMENSIONS
_R18_TERMS: tuple[str, ...] = _load_sibling("test_copy_redline_gate.py").R18_TERMS


@pytest.fixture(autouse=True)
def _no_production_reply_policy_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """聊天主链懒建的进程级策略 store 一律收成 None ⇒ 本文件零生产库读写。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character import reply_policy

    monkeypatch.setattr(reply_policy, "shared_reply_policy_store", lambda config: None)


# ---------------------------------------------------------------- 构造器（离线 mock）


def _config(**overrides: object) -> SimpleNamespace:
    """一次调用一本**自己的**临时库（描写钉按 (平台域, 用户号) 归属＝按人全局）。"""
    isolated = tempfile.mkdtemp(prefix="grp-scene-db-", dir=_TMP_DATA_DIR)
    base: dict[str, object] = {
        "bot_addressing_preferences_db_path": os.path.join(
            isolated, "addressing_preferences.sqlite3"
        ),
        "bot_content_route_enabled": True,
        "bot_content_route_model": "grok-4.6",
        "bot_content_route_order": "grok-4.6,gemini-3.5-flash",
        "bot_content_route_words": "",
        "bot_content_route_intimate_threshold": 60.0,
        "bot_content_route_normal_threshold": 25.0,
        "bot_content_route_context_turns": 4,
        "bot_content_route_max_ttl_minutes": 120.0,
        "bot_content_route_idle_reset_minutes": 10.0,
        # 群侧会话准入门（2026-09-17 裁定）：黑名单优先、白名单空＝群聊面整体关闭
        "bot_content_route_group_whitelist": [_GROUP_ID],
        "bot_content_route_group_blacklist": [],
        "bot_content_route_group_per_user_enabled": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _message(
    session_id: str,
    text: str = "那你会怎么陪我。",
    *,
    group: bool = False,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=session_id,
        session_type=SessionType.GROUP if group else SessionType.PRIVATE,
        sender_id=_GROUP_UID,
        group_id=_GROUP_ID if group else "",
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
        sender_id=_GROUP_UID,
        session_id=message.session_id,
    )


class _CapturingProvider:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def generate(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> LLMReply:
        self.messages = messages
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="m")


def _system_join(provider: _CapturingProvider) -> str:
    return "\n".join(
        str(item.get("content") or "")
        for item in provider.messages
        if item.get("role") == "system"
    )


def _section_header(instruction: str) -> str:
    head, marker, _rest = instruction.partition("】")
    assert marker and head.startswith("【"), f"样式段缺【…】段落头：{instruction[:20]!r}"
    return f"{head}{marker}"


def _turn(session: str, cfg: object, *, group: bool = False) -> tuple[str, object]:
    provider = _CapturingProvider()
    message = _message(session, group=group)
    result = chat.build_chat_result(
        message,
        _decision(message),
        _context(message),
        llm_provider=provider,
        content_route_config=cfg,
    )
    return _system_join(provider), result


def _pin_scene(session: str, cfg: object) -> None:
    """真实链路：把本人的描写档钉成 `scene`（读写同口，键由轴心算，不猜键形）。"""
    assert cr.write_narration_pin(
        session,
        mode=cr.NARRATION_MODE_SCENE,
        sender_id=_GROUP_UID,
        config=cfg,
        platform="qq",
    ) is True, "描写钉没写进去＝下面的断言全在空跑"


def _open_intimate(session: str, cfg: object) -> None:
    assert SHARED_CONTENT_ROUTE_ENGINE.apply_manual(session, "intimate", cfg) is True


def _permission_and_ban(block: str) -> tuple[str, str]:
    marker = chat.GROUP_SCENE_BAN_CLAUSE_MARKER
    assert marker in block, f"分界枚 {marker!r} 不在群侧段里 ⇒ 两截分不开，本腿会空跑"
    permission, _, ban = block.partition(marker)
    return permission, marker + ban


def _body_terms() -> tuple[str, ...]:
    """本裁定点名的两类＝身形细部词表 ∪ 衣着词表（两张真身表，本件一枚都不抄）。"""
    return tuple(chat.SCENE_CORPORAL_TERMS) + tuple(chat.NORMAL_SCENE_CLOTHING_TERMS)


def _injected_surface() -> dict[tuple[str, bool, bool], str]:
    """注入面全表＝选择表键集 × {私聊, 群}，全部**现算自 `resolve_rp_style_block`**。

    刻意不手写常量名册（失效形态 244＝靠硬抄名册的锁对新常量天生隐形）：表里加一格、
    或群侧那张表多一格，本件的枚举面自动跟上。
    """
    surface: dict[tuple[str, bool, bool], str] = {}
    for mode, intimate in chat.RP_STYLE_BLOCKS:
        for group in (False, True):
            surface[(str(mode), bool(intimate), group)] = chat.resolve_rp_style_block(
                mode, intimate=intimate, group=group
            )
    return surface


# ================================================================ ① 选择面：只有 scene 两格随会话面变


def test_group_scope_table_covers_exactly_the_same_cells() -> None:
    """群侧那张表的键形与键集必须与私聊那张**完全相同**（缺格＝KeyError，不许静默回落）。"""
    group_table = chat.RP_STYLE_GROUP_BLOCKS
    assert set(group_table) == set(chat.RP_STYLE_BLOCKS), (
        "两表键集不等 ⇒ 某一格在群侧没有写法，群聊那一轮会拿到私聊段（＝裁定要收的那一侧）"
    )
    for key, block in group_table.items():
        assert isinstance(block, str) and block.startswith("【"), f"群侧格 {key} 不是带头的散文段"


def test_only_the_scene_cells_move_with_the_session_scope() -> None:
    """两格 `scene` 随会话面变；两格 `speech` 在两种会话面下是**同一个对象**（一字未动）。"""
    surface = _injected_surface()
    scene = str(cr.NARRATION_MODE_SCENE)
    moved = [
        (mode, intimate)
        for (mode, intimate, group), block in surface.items()
        if group and block is not surface[(mode, intimate, False)]
    ]
    assert sorted(moved) == sorted(
        (str(mode), intimate)
        for (mode, intimate) in chat.RP_STYLE_BLOCKS
        if str(mode) == scene
    ), f"随会话面变的格子不是那两格 scene：{sorted(moved)}"
    for (mode, intimate, _group), block in surface.items():
        if str(mode) != scene:
            assert block is chat.RP_STYLE_BLOCKS[(mode, intimate)], (
                f"speech 格 {(mode, intimate)} 在群侧被换文了＝动了裁定范围之外的那两格"
            )


def test_scene_blocks_move_toward_narrowing_never_widening() -> None:
    """方向锁：群侧段必须**更短或等长**且不许长出私聊段没有的描写承诺——

    放宽只能由裁定带来。这里量的是"群侧段里身形/衣着的**许可**一枚都不剩"（下面文案面判），
    本腿只钉方向：群侧段与私聊段互不相同、且群侧段自己带分界枚（＝真的在关那一类）。
    """
    for intimate in (True, False):
        private = chat.RP_STYLE_BLOCKS[(str(cr.NARRATION_MODE_SCENE), intimate)]
        public = chat.RP_STYLE_GROUP_BLOCKS[(str(cr.NARRATION_MODE_SCENE), intimate)]
        assert private != public
        assert chat.GROUP_SCENE_BAN_CLAUSE_MARKER in public
        assert chat.GROUP_SCENE_BAN_CLAUSE_MARKER not in private, (
            "分界枚长进了私聊段＝把群侧判据写成了恒真，私聊那一侧也被收了"
        )


def test_unknown_axis_value_fails_closed_under_both_scopes() -> None:
    """认不出的轴值在两种会话面下都收回「只说话」那一格（笔误不得放大描写面）。"""
    speech = str(cr.NARRATION_MODE_SPEECH)
    for group in (False, True):
        junk = chat.resolve_rp_style_block("werewolf", intimate=True, group=group)
        assert junk == chat.RP_STYLE_BLOCKS[(speech, True)]
        assert _section_header(chat.INTIMATE_RP_STYLE_INSTRUCTION) not in junk
        assert _section_header(chat.NORMAL_SCENE_STYLE_INSTRUCTION) not in junk


# ================================================================ ② 文案面：群侧段的成对锁


def test_group_scene_blocks_permit_nothing_of_the_two_named_classes() -> None:
    """许可半句里身形细部与衣着**一枚都不许有**（裁定只收这两类，且收在许可侧才算收到）。"""
    terms = _body_terms()
    for intimate in (True, False):
        block = chat.RP_STYLE_GROUP_BLOCKS[(str(cr.NARRATION_MODE_SCENE), intimate)]
        permission, _ban = _permission_and_ban(block)
        smuggled = [term for term in terms if term in permission]
        assert not smuggled, f"群侧段 (intimate={intimate}) 的许可半句仍有 {smuggled}"
    # 注毒自证：把一枚真身词塞进许可半句，判据必须当场咬得住
    block = chat.RP_STYLE_GROUP_BLOCKS[(str(cr.NARRATION_MODE_SCENE), False)]
    permission, ban = _permission_and_ban(block)
    poisoned = permission + f"这一身的{chat.NORMAL_SCENE_CLOTHING_TERMS[0]}也照当下写。" + ban
    assert any(term in poisoned.split(ban, 1)[0] for term in terms), (
        "注毒后仍判得出「许可侧无词」＝词表是空表，本锁在空跑"
    )


def test_group_scene_ban_half_names_both_classes_exactly_once() -> None:
    """禁令半句必须点名这两类（不点名＝空话），且每枚被点名的词**恰好一次**（两次＝抹掉一枚
    还剩一枚，注毒永远打不红＝假绿）。口径同 `_corporal_axis_violations` ③。"""
    for intimate in (True, False):
        block = chat.RP_STYLE_GROUP_BLOCKS[(str(cr.NARRATION_MODE_SCENE), intimate)]
        _permission, ban = _permission_and_ban(block)
        corporal = [term for term in chat.SCENE_CORPORAL_TERMS if term in ban]
        clothing = [term for term in chat.NORMAL_SCENE_CLOTHING_TERMS if term in ban]
        assert corporal, f"群侧段 (intimate={intimate}) 禁令半句没点身形这一类 ⇒ 边界是句空话"
        assert clothing, f"群侧段 (intimate={intimate}) 禁令半句没点衣着这一类 ⇒ I-3 没落地"
        for term in set(corporal) | set(clothing):
            assert ban.count(term) == 1, (
                f"「{term}」在群侧禁令半句里出现 {ban.count(term)} 次（要恰好一次）"
            )


def test_group_scene_blocks_still_promise_the_rest_of_the_axis() -> None:
    """反收窄锁：四维＋环境句在群侧两段里**照旧在场**（裁定只收身形衣着，别的没让收）。"""
    for intimate in (True, False):
        block = chat.RP_STYLE_GROUP_BLOCKS[(str(cr.NARRATION_MODE_SCENE), intimate)]
        permission, _ban = _permission_and_ban(block)
        for dimension in _SCENE_DIMENSIONS:
            assert dimension in permission, (
                f"群侧段 (intimate={intimate}) 许可半句把「{dimension}」也收了＝越出裁定"
            )
        assert "语言" in permission, f"群侧段 (intimate={intimate}) 连语言都不写＝越出裁定"
        assert (
            chat.SCENE_ENVIRONMENT_MARKER in block
        ), f"群侧段 (intimate={intimate}) 把环境段也删了＝I-1 那条被本波吃掉"


def test_private_scene_blocks_still_promise_body_and_clothing() -> None:
    """**反向腿**（证明群侧判据不是恒真）：私聊那一路照旧——日常场景段的许可半句仍点名衣着，
    五维段仍写着彼此的形貌。"""
    private_normal = chat.NORMAL_SCENE_STYLE_INSTRUCTION
    normal_permission = private_normal.partition(chat.NORMAL_SCENE_BAN_CLAUSE_MARKER)[0]
    assert any(
        term in normal_permission for term in chat.NORMAL_SCENE_CLOTHING_TERMS
    ), "私聊侧日常场景段不再许可衣着＝群侧判据被写成恒真，把本人那一路也收了"
    assert any(
        term in chat.INTIMATE_RP_STYLE_INSTRUCTION for term in chat.SCENE_CORPORAL_TERMS
    ), "私聊侧五维段不再许可形貌那一路＝本波越过了裁定"
    assert (
        chat.resolve_rp_style_block(
            cr.NARRATION_MODE_SCENE, intimate=False, group=False
        )
        is chat.NORMAL_SCENE_STYLE_INSTRUCTION
    ), "私聊 scene 格换文了＝在册锁（test_narration_axis_styles）之外又多一份日常段"


# ================================================================ ③ 注入面：真跑 build_chat_result


def test_group_scene_turn_injects_the_group_block_only() -> None:
    """白名单群里钉了 `scene` 的那一轮：吃到群侧段，私聊日常段的段落头**不在**场。"""
    cfg = _config()
    _pin_scene(_GROUP_SESSION, cfg)
    joined, _result = _turn(_GROUP_SESSION, cfg, group=True)
    group_block = chat.RP_STYLE_GROUP_BLOCKS[(str(cr.NARRATION_MODE_SCENE), False)]
    assert _section_header(group_block) in joined
    assert _section_header(chat.NORMAL_SCENE_STYLE_INSTRUCTION) not in joined
    assert _section_header(chat.INTIMATE_RP_STYLE_INSTRUCTION) not in joined


def test_private_scene_turn_still_injects_the_private_block() -> None:
    """同一个人的私聊轮（同一枚钉、同一把尺）⇒ 仍吃原段：反向腿，证明群侧判据不是恒真。"""
    cfg = _config()
    private_session = f"private:{_GROUP_UID}-grp-scene"
    _pin_scene(private_session, cfg)
    joined, _result = _turn(private_session, cfg)
    assert _section_header(chat.NORMAL_SCENE_STYLE_INSTRUCTION) in joined
    assert (
        _section_header(chat.RP_STYLE_GROUP_BLOCKS[(str(cr.NARRATION_MODE_SCENE), False)])
        not in joined
    )


def test_group_intimate_scene_turn_injects_the_group_intimate_block() -> None:
    """群内亲密授予（真实链路：本人在白名单群说「亲密模式 开」）⇒ 群侧亲密段，不是五维段。"""
    cfg = _config()
    route_key = cr.member_session_key(_GROUP_SESSION, _GROUP_UID)
    _open_intimate(route_key, cfg)
    joined, _result = _turn(_GROUP_SESSION, cfg, group=True)
    intimate_block = chat.RP_STYLE_GROUP_BLOCKS[(str(cr.NARRATION_MODE_SCENE), True)]
    assert _section_header(intimate_block) in joined
    assert _section_header(chat.INTIMATE_RP_STYLE_INSTRUCTION) not in joined
    assert _section_header(chat.NORMAL_SCENE_STYLE_INSTRUCTION) not in joined


def test_group_scene_turn_keeps_the_same_length_tier_as_private_scene() -> None:
    """长度档不许动：群内 scene 轮与私聊 scene 轮读到**同一档**那一行（铺写照旧）。"""
    top = chat.REPLY_LENGTH_TIERS[chat._REPLY_TIER_TOP_ID]

    def _tier_line(joined: str) -> str:
        lines = [
            line for line in joined.splitlines() if line.startswith(chat.TIER_LINE_PREFIX)
        ]
        assert len(lines) == 1, f"长度指令必须恰好一条，实得 {len(lines)}"
        return lines[0]

    cfg_group = _config()
    _pin_scene(_GROUP_SESSION, cfg_group)
    group_joined, _ = _turn(_GROUP_SESSION, cfg_group, group=True)

    cfg_private = _config()
    private_session = f"private:{_GROUP_UID}-grp-scene-tier"
    _pin_scene(private_session, cfg_private)
    private_joined, _ = _turn(private_session, cfg_private)

    assert f"当前档＝{top.label_cn}" in _tier_line(group_joined), _tier_line(group_joined)
    assert _tier_line(group_joined) == _tier_line(private_joined), (
        "群侧 scene 轮的长度行与私聊不等＝本波顺手动了长度档"
    )


# ================================================================ ④ 词界与红线（新段也一并扫）


def _screen_hit_terms(text: str) -> list[str]:
    return [label for label, pattern in _PUBLIC_OUTPUT_UNSAFE if pattern.search(text)]


def test_every_injected_style_text_is_screen_clean_and_red_line_clean() -> None:
    """注入面**每一格**（含群侧两段）对群聊出站尺与三把红线尺零命中。

    群聊出站那把尺命中即整条丢 ⇒ 她在群里"什么都收不到"（台账 #76）。枚举面派生自
    `_injected_surface()`（＝选择表 × 会话面现算），所以群侧新段自动进锁面，不需要名册多一行。
    """
    surface = _injected_surface()
    assert len(surface) >= 8, f"注入面枚举只剩 {len(surface)} 格＝选择表或会话面被改窄"
    for key, block in surface.items():
        assert _screen_hit_terms(block) == [], f"样式段 {key} 会被群聊尺整条丢"
        assert not _SEXUAL_CONTEXT_RE.search(block), f"样式段 {key} 带性语境词面 ⇒ 撞六硬线"
        assert not _BODY_TYPE_PATTERN.search(block), f"样式段 {key} 带体态词面 ⇒ 撞幼态尺"
        hit = [term for term in _R18_TERMS if term in block]
        assert not hit, f"样式段 {key} 带 R-18 精确词表 {hit}"


def test_screen_lock_bites_on_every_injected_cell() -> None:
    """注毒自证：逐格粘上命中文样后尺必须变红；任何一格粘不动＝那一格在锁上是空跑的。"""
    token = None
    for _label, pattern in _PUBLIC_OUTPUT_UNSAFE:
        for alt in pattern.pattern.split("|"):
            alt = alt.strip("()").strip()
            if not alt or any(ch in alt for ch in "[](){}*+?\\^$"):
                continue
            if pattern.search(alt):
                token = alt
                break
        if token:
            break
    assert token, "取不出字面命中文样＝尺已漂移或只剩字符类，本锁无从注毒"
    for key, block in _injected_surface().items():
        assert token not in block, f"{key} 本来就带着 token＝注毒腿量不到尺"
        assert _screen_hit_terms(block + token), f"注毒后尺对 {key} 不命中＝本锁对该格空跑"


def test_injected_headers_are_pairwise_distinct() -> None:
    """**不同文本之间**段落头互不相同（`X not in joined` 那些负锁的前提；同头＝负锁全成空判）。

    两格 `speech` 在两种会话面下是同一枚对象（＝同一头），那是裁定要的形状、不是撞车，
    所以这里按**去重后的文本**判头，口径同 `test_narration_axis_styles.py::test_four_headers_are_pairwise_distinct`。
    """
    distinct = list(dict.fromkeys(_injected_surface().values()))
    headers = [_section_header(block) for block in distinct]
    assert len(headers) == len(set(headers)), f"样式段段落头撞车：{sorted(set(headers))}"
    assert all(re.match(r"^【.+】$", head) for head in headers), headers
    private_texts = {str(block) for block in chat.RP_STYLE_BLOCKS.values()}
    assert private_texts < set(distinct), "群侧那两段没让注入面变宽＝它们压根没挂进选择口"


def test_group_blocks_are_registered_as_module_level_literals() -> None:
    """群侧两段必须是 `chat.py` 顶层的**静态字面量**（AST 名册只认这个形状）。

    `test_reply_policy_permanent.py::_module_level_string_constants` 按形状从源文枚风格常量；
    写成 f-string／函数内赋值＝篇幅黑名单与成对锁从此扫不到它（失效形态 244 那一型）。
    """
    source = (
        _REPO
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "chat_reply"
        / "capabilities"
        / "chat.py"
    ).read_text(encoding="utf-8")
    sibling = _load_sibling("test_reply_policy_permanent.py")
    roster = sibling._style_roster_from_source(source)
    for name in ("GROUP_NORMAL_SCENE_STYLE_INSTRUCTION", "GROUP_INTIMATE_SCENE_STYLE_INSTRUCTION"):
        assert name in roster, f"{name} 不是顶层静态字面量（或不含叙述标记词）⇒ 名册看不见它"
        assert getattr(chat, name) == roster[name], f"{name}：AST 名册读数与运行时活值不同文"


def test_ban_marker_is_short_and_appears_once_per_group_scene_block() -> None:
    """分界枚要短（<40 字，否则被名册当独立段扫）且**群侧 scene 两段**里恰好一枚。

    两格 `speech` 复用私聊那两枚对象 ⇒ 它们本来就不该带这枚枚（带上了才是把群侧判据
    写进只说话那一格），所以这里只枚 scene 两格，口径同 `test_both_scene_cells_instruct_...`。
    """
    marker = chat.GROUP_SCENE_BAN_CLAUSE_MARKER
    assert 0 < len(marker) < 40, f"分界枚长度 {len(marker)}"
    scene_cells = {
        key: block
        for key, block in chat.RP_STYLE_GROUP_BLOCKS.items()
        if str(key[0]) == str(cr.NARRATION_MODE_SCENE)
    }
    assert len(scene_cells) == 2, f"群侧 scene 格数＝{len(scene_cells)}（应为两格）"
    for key, block in scene_cells.items():
        assert block.count(marker) == 1, f"群侧格 {key} 里分界枚出现 {block.count(marker)} 次"
    for key, block in chat.RP_STYLE_BLOCKS.items():
        if str(key[0]) != str(cr.NARRATION_MODE_SCENE):
            assert marker not in block, f"分界枚长进了 speech 格 {key}＝群侧判据越界"


def test_corporal_terms_are_still_the_real_boundary_in_both_scopes() -> None:
    """词表在两种会话面下都**真的**画在分界上：私聊五维段许可它、群侧两段都关它。

    （`test_corporal_axis_is_the_real_difference_between_the_two_scene_blocks` 判的是私聊两格；
    本腿把它扩到会话面这一轴，仍从真身词表取数，不抄第二份名单。）
    """
    for key, block in _injected_surface().items():
        mode, _intimate, group = key
        if not group or mode != str(cr.NARRATION_MODE_SCENE):
            continue
        hits = [term for term in chat.SCENE_CORPORAL_TERMS if term in block]
        assert hits, f"群侧 scene 格 {key} 里找不到身体细部词表 ⇒ 那张表与实际许可脱钩"
