"""席 D1（2026-10-02）：群内「亲密模式 开」的**可送达**锁（用户点名缺陷 ①）。

现网取证（生产审计库 `wuwa_audit`，一条 review 行把整件事说完了）：在册
亲密群（群号见生产白名单，本件不抄录——PRV 扫出后改为脱敏叙述）里超管真
@ 了机器人说「亲密模式 开」，链路三段全过
（门禁 allowed → 指令短路 apply_manual → 回执 CapabilityResult），但回执被
**审核**判 ``move_private``／``personal output cannot be sent to group``——
群内看到的是兜底文案「输出未通过安全或隐私检查。」，于是"开关不可用"。

病根只有一个字：`build_chat_result` 的指令短路回执把 `privacy_level` **硬写成
PERSONAL**，而同函数其余出口一律交 `context.privacy_level`（群聊腿在能力入口被夹成
GROUP）。审核门（`domains/render/reviewer.py`）对「群作用域 + PERSONAL 正文」一律
不放行 ⇒ 钉其实已经上上了，只是回执永远出不了门。既有单测全部只看 `result.body`，
从不把结果交给真消费者 `review_capability_result` ⇒ 这一格静默了一整个波次。

双向纪律（SEAT-RULES 判据纪律）：
- 注毒腿：② 组——回执一旦声明 PERSONAL（=改前形态）审核必须判不放行；③ 组——
  准入门被摘（白名单空／黑名单命中／总闸关）时必须表现为「关」，绝不猜开放。
- 反向不误伤腿：① 组——群内指令的回执必须能出门；④ 组——成员自己拨的钉
  **只钉他自己**，同群别人一律不因此进亲密档（B-Important-1 那格泄漏的历史缺陷）；
  ⑤ 组——私聊那侧的档位与隐私一个字都不许被顺手放宽。
- 键形一律由中央件产出（`build_session_key`/`group_scope_key`），且用**生产下划线
  形** `group_<群号>_<用户号>`——旧集成用例吃的是合成冒号形（`group:v3-it-1`），
  恰好绕过了 T-1 那一族「逐成员键 vs 整群键」的真实分叉，本文件把生产形钉住。
- 每个用例各占一枚群号：共享引擎是进程级单例，管理员的全群钉会把后面用例的
  成员读数一起染成 intimate（本件初稿就踩到过，靠分群号才测得出真东西）。
  ⚠ 这条规矩 D1（2026-10-02）自己破过一次：`_G_DEEP` 被「管理员深开回执」与
  「成员深开落档」两枚用例共用，于是 `test_member_deep_switch_...` 的
  `route_verdict` 走的是**群级钉短路**（引擎里 `_group_pin_state` 命中后直接转述
  整群那把键的 `source`/`tier`），tier 那一格是**替邻居用例背书**才绿的，而
  「群级键无钉」那一格红的是邻居、不是产品。D1b（同日）三件同批收：① 一用例一群号补全（含
  私聊那枚，见 `_G_PRIVATE`）；② `_config`/`_group_message` 的 `group` **默认值删掉**
  （漏传必须 TypeError，不许静默回落到 `_G_ACK` 这把别人用过的键）；③ 加 autouse
  隔离具（每枚用例进出各换一次 `_sessions`）+ 本例改读**来源**与**写侧档号**，
  让「读的是自己那把钉」这件事被断言本身证明，不再靠运气。
"""
from __future__ import annotations

import ast
import copy
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
    INTIMATE_RP_STYLE_INSTRUCTION,
    MANUAL_ON_REPLY,
    build_chat_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMReply,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_SOURCE_ADMIN_PIN,
    INTIMATE_SOURCE_MANUAL,
    INTIMATE_SOURCE_NONE,
    INTIMATE_TIER_L1,
    INTIMATE_TIER_L2,
    MANUAL_DEEP_ON_REPLY,
    MODE_INTIMATE,
    SHARED_CONTENT_ROUTE_ENGINE,
    explicit_allowed_for_session,
    member_session_key,
    resolve_intimate_context,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    build_session_key,
    group_scope_key,
    private_session_key,
)
from plugins.bot_unified_runtime.domains.render.reviewer import (
    review_capability_result,
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
_TTS_SOURCE = (
    _REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "media"
    / "capabilities"
    / "tts.py"
)

# DATAFIX：称谓偏好 store 的缺省路径会落到生产运行数据根（.env 的 Runtime 根直指现网），
# 本件每个用例都自带 tmp 目录，绝不读写现网库。
_TMP_DATA_DIR = tempfile.mkdtemp(prefix="thyg-d1grp-")

# 用例各自的群号（数字 QQ 群形态，与现网同形状；**一用例一枚**，防全群钉互染——
# 见模块 docstring 那条被破过又补全的规矩；私聊那枚也单独占一号，为的是让
# 「两个用例共用一把键」这件事在源码层面就不成立，而不是靠人记得住）。
_G_ACK = "700100030"        # 事故腿形状那一枚（原误用现网真实群号，PRV 扫出后换假号段——夹具自喂白名单，不依赖真值）
_G_DEEP = "700100031"       # 仅管理员深开回执那一枚（同上换假号段）
_G_DEEP_MEMBER = "700100017"  # 成员深开落档那一枚（曾与 `_G_DEEP` 共用＝本件那格红）
_G_MEMBER = "662948429"
_G_POISON = "700100011"
_G_UNLISTED = "700100012"
_G_BLACK = "700100013"
_G_MASTER_OFF = "700100014"
_G_LEAK = "700100015"
_G_ADMIN_SCOPE = "700100016"
_G_PRIVATE = "700100018"     # 私聊回执那一枚（群号只喂白名单，不进任何键）
_G_PERSON_LEG = "700100019"   # 人腿端到端正例（群不在群白名单）
_G_PERSON_NEG = "700100020"   # 人腿反例（人不在私聊白名单）
_G_PERSON_BLACK = "700100021"  # 人腿反例（群黑名单压人腿）

_ADMIN = "3865067623"
_MEMBER_A = "2950687868"
_MEMBER_B = "1250727173"


def _config(group: str, **overrides: object) -> SimpleNamespace:
    """会话门配置替身。`group` **无默认值**（D1b）：漏传必须 TypeError，
    绝不静默落到某枚别人用过的群号上——那正是本件那格红的成因。
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
        # 自动腿关掉：本件只测「人说了一句开关」这一条路，好感度自动档会污染读数。
        "bot_content_route_l1_auto_enabled": False,
        "bot_content_route_l1_auto_min_tier": 1,
        "bot_master_love_enabled": False,
        "bot_master_love_admins": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _CapturingProvider:
    """离线 LLM 替身：留下「这一轮到底有没有走到大模型」与真发出去的 messages。"""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.calls = 0

    def generate(self, messages: list[dict[str, Any]], **kwargs: object) -> LLMReply:
        self.calls += 1
        self.messages = copy.deepcopy(list(messages))
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="fake")


def _group_message(
    sender_id: str,
    text: str,
    roles: list[str],
    *,
    group_id: str,
) -> IncomingMessage:
    """生产形态群消息：会话键=OneBot 逐成员下划线形，@ 段不进 plain_text。

    `group_id` **无默认值**（D1b，与 `_config` 同一条纪律）：本文件的每一枚用例
    都必须自己说清占的是哪把群键。
    """
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="3958874605",
        session_id=build_session_key(group_id, sender_id),
        session_type=SessionType.GROUP,
        sender_id=sender_id,
        group_id=group_id,
        sender_roles=roles,
        plain_text=text,
        command_text=text,
        mentions_bot=True,
        raw_segments=[{"type": "text", "data": {"text": text}}],
    )


def _private_message(sender_id: str, text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="3958874605",
        session_id=private_session_key(sender_id),
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
        command_text=text,
        mentions_bot=True,
        raw_segments=[{"type": "text", "data": {"text": text}}],
    )


def _decision(message: IncomingMessage) -> BotDecision:
    """照生产口径建判定：群腿 target_scope=GROUP（真门禁给的就是这个）。"""
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
    """复刻能力入口对上下文的隐私夹取（`build_chat_capability` 里那一条 model_copy）。

    不复刻就测不出真相：现网群聊正文能出门，靠的正是这一步把 GROUP 写进 context；
    指令短路回执没走它、自己硬写了 PERSONAL，才在审核那一格被撞死。
    """
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


def _turn(
    message: IncomingMessage,
    cfg: SimpleNamespace,
    provider: _CapturingProvider | None = None,
):
    provider = provider or _CapturingProvider()
    result = build_chat_result(
        message,
        _decision(message),
        _context(message),
        llm_provider=provider,
        affinity_store=None,
        content_route_config=cfg,
    )
    return result, provider


def _system_join(provider: _CapturingProvider) -> str:
    return "\n".join(
        str(item.get("content") or "")
        for item in provider.messages
        if item.get("role") == "system"
    )


def _verdict_of(message: IncomingMessage, cfg: SimpleNamespace) -> dict[str, Any]:
    """下一轮读数：走注入缝的同一个合成口（禁第二套判据）。"""
    return resolve_intimate_context(
        SHARED_CONTENT_ROUTE_ENGINE,
        session_type="group",
        group_id=str(message.group_id or ""),
        sender_id=message.sender_id,
        session_key=message.session_id,
        config=cfg,
    )


def _pin_on_own_key(key: str) -> str | None:
    """只看**这把键自己**的钉（不查整群短路）——`pinned_mode` 会先转述群钉，
    用它判「个人键有没有被抄上一份」必然读出 intimate，那是判据用错地方。
    """
    state = SHARED_CONTENT_ROUTE_ENGINE._sessions.get(key)
    return None if state is None else state.pin


def _tier_on_own_key(key: str) -> str | None:
    """同上，但读**档号**：写侧到底把深浅落到哪把键上，只认这把键自己的账。

    为什么需要它（D1b 2026-10-02）：`route_verdict` 对成员派生键先查整群钉
    （`_group_pin_state` 命中即转述群键的 source/tier 后 return），所以「verdict
    里 tier=l2」在群钉在场时**证明不了成员键自己落没落档**——必须绕过短路直读
    `_SessionState.pin_tier` 才量得到写侧真身。
    """
    state = SHARED_CONTENT_ROUTE_ENGINE._sessions.get(key)
    return None if state is None else state.pin_tier


@pytest.fixture(autouse=True)
def _isolate_shared_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """用例间隔离（D1b）：`SHARED_CONTENT_ROUTE_ENGINE` 是进程级单例，本文件所有
    用例共用同一本 `_sessions` 账。上一枚用例的管理员全群钉会染黑后面用例的
    「群级键无钉」断言——现算实锤：整片跑 1 红、单跑同一枚绿，差值只有邻居。
    这里每枚用例换一只新账、用例结束由 monkeypatch 自动还原原对象，因此
    ① 本文件内部互不污染，② 对同批其他测试文件的既有累积状态一个字没动。
    """
    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "_sessions", OrderedDict())


# ========================================================= ① 群内回执出得了门（反向不误伤）


def test_group_ack_is_approved_by_review_so_the_switch_is_visible() -> None:
    """群内「亲密模式 开」：回执必须**能出门**（审核放行、正文就是那句确认话）。

    这是用户点名缺陷的本体：钉上了、回执被审核吃掉 ⇒ 用户只看见兜底文案，
    于是"开关不可用"。
    """
    cfg = _config(_G_ACK)
    msg = _group_message(_ADMIN, "亲密模式 开", ["admin", "super_admin"], group_id=_G_ACK)
    result, provider = _turn(msg, cfg)

    assert provider.calls == 0, "指令短路没接住这句话，跑去问模型了"
    assert result.body == MANUAL_ON_REPLY
    assert "scope:group" in (result.audit_tags or []), result.audit_tags

    review = review_capability_result(result, _decision(msg))
    assert review.approved is True, review.reasons
    assert "personal output cannot be sent to group" not in review.reasons
    assert result.privacy_level is PrivacyLevel.GROUP, (
        "群聊回执的隐私档不再是 GROUP：要么被改回裸 PERSONAL（回执会被审核吃掉），"
        "要么 context 的隐私夹取被摘掉了"
    )


def test_group_deep_ack_is_approved_too() -> None:
    """深档「亲密模式 深开」同一条路：回执同样要能出门（三句确认话共用这一支）。"""
    cfg = _config(_G_DEEP)
    msg = _group_message(
        _ADMIN, "亲密模式 深开", ["admin", "super_admin"], group_id=_G_DEEP
    )
    result, _provider = _turn(msg, cfg)

    assert result.body == MANUAL_DEEP_ON_REPLY
    assert review_capability_result(result, _decision(msg)).approved is True


def test_member_group_ack_is_approved_and_pins_only_the_member_key() -> None:
    """普通成员在群里拨开关：回执同样能出门，且钉落**成员派生键**（scope:user）。"""
    cfg = _config(_G_MEMBER)
    msg = _group_message(_MEMBER_A, "亲密模式 开", ["user"], group_id=_G_MEMBER)
    result, provider = _turn(msg, cfg)

    assert provider.calls == 0
    assert result.body == MANUAL_ON_REPLY
    assert "scope:user" in (result.audit_tags or []), result.audit_tags
    assert review_capability_result(result, _decision(msg)).approved is True
    own_key = member_session_key(msg.session_id, _MEMBER_A)
    assert SHARED_CONTENT_ROUTE_ENGINE.route_verdict(own_key, cfg)["mode"] == "intimate"
    assert SHARED_CONTENT_ROUTE_ENGINE.route_verdict(own_key, cfg)["source"] == (
        INTIMATE_SOURCE_MANUAL
    )


def test_member_deep_switch_in_group_reaches_the_router_head_on_the_same_key() -> None:
    """群内「亲密模式 深开」要真的能把首跳换掉：写侧键 == 交给路由的那把成员键。

    注册在案的键形教义（T-1）：群消息路由读的是成员派生键，注入缝与路由同源一把。
    这一格盯的是"回执出了门、档也上了，但路由读的是另一把键"——那种形态下用户
    会同时看见"已开"和"没换档"，比彻底不受理更难查。
    """
    cfg = _config(_G_DEEP)
    msg = _group_message(
        _MEMBER_A, "亲密模式 深开", ["user"], group_id=_G_DEEP
    )
    result, provider = _turn(msg, cfg)

    assert provider.calls == 0
    assert result.body == MANUAL_DEEP_ON_REPLY
    own_key = member_session_key(msg.session_id, _MEMBER_A)
    verdict = SHARED_CONTENT_ROUTE_ENGINE.route_verdict(own_key, cfg)
    assert verdict["mode"] == "intimate"
    assert verdict["tier"] == INTIMATE_TIER_L2
    assert verdict["head_models"][:1] == ["grok-4.6"], verdict["head_models"]
    # 群级键上不该有钉：个人深档不许顺手把全群点着。
    assert _pin_on_own_key(group_scope_key(msg.session_id)) != MODE_INTIMATE


# ============================================ ② 注毒腿：改回裸 PERSONAL 就必须被审核撞死


def test_personal_privacy_ack_would_be_blocked_in_group() -> None:
    """缺陷本体自证：同一条回执只要声明 PERSONAL，群腿必被判不放行。

    本例是 ① 的对照——它证明 ① 不是空话：审核那一格真的在管「群作用域 +
    PERSONAL 正文」，改前形态出去的正是这一枚不放行（现网事件名 ``move_private``）。
    """
    cfg = _config(_G_POISON)
    msg = _group_message(
        _ADMIN, "亲密模式 开", ["admin", "super_admin"], group_id=_G_POISON
    )
    result, _provider = _turn(msg, cfg)

    poisoned = result.model_copy(update={"privacy_level": PrivacyLevel.PERSONAL})
    review = review_capability_result(poisoned, _decision(msg))
    assert review.approved is False
    assert "personal output cannot be sent to group" in review.reasons


def test_manual_ack_does_not_hardcode_a_privacy_level() -> None:
    """静态锁：指令短路回执的隐私档必须引 `context.privacy_level`，不许再写枚举常量。

    同函数其余出口（正文/边界/产物失败/兜底）早就统一交 `context.privacy_level`，
    只有这一支当年漏了。AST 层把它钉住——写回 `PrivacyLevel.PERSONAL` 当场红，
    不必等下一次现网取证。
    """
    tree = ast.parse(_CHAT_SOURCE.read_text(encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", "") != "CapabilityResult":
            continue
        has_content_route_tag = any(
            kw.arg == "audit_tags"
            and isinstance(kw.value, ast.List)
            and any(
                isinstance(item, ast.Constant) and item.value == "content_route"
                for item in kw.value.elts
            )
            for kw in node.keywords
        )
        if not has_content_route_tag:
            continue
        privacy = next(
            (kw.value for kw in node.keywords if kw.arg == "privacy_level"), None
        )
        assert privacy is not None, "指令短路回执没有 privacy_level 参数"
        assert isinstance(privacy, ast.Attribute) and privacy.attr == "privacy_level", (
            "群内开关回执的隐私档又变成硬写的枚举常量了 ⇒ 审核会把回执吃掉"
        )
        assert isinstance(privacy.value, ast.Name) and privacy.value.id == "context", (
            f"privacy_level 取的不是 context：{ast.dump(privacy)}"
        )
        checked += 1
    assert checked >= 1, "找不到带 content_route 标签的回执构造点（短路支被搬走了？）"


# ================================= ③ 注毒腿：准入门被摘＝表现为「关」，绝不猜开放


def test_empty_group_whitelist_closes_the_switch_instead_of_guessing_open() -> None:
    """白名单被清空：群内那句开关**不受理**（无确认话、不上钉），落回普通聊天。

    判据只住 `explicit_allowed_for_session` 一处——这一格锁的是「清空名单不会反过来
    被当成放开」，那是 R-18 面的底线（白名单空=群聊亲密面整体关闭）。
    """
    cfg = _config(_G_UNLISTED, bot_content_route_group_whitelist=[])
    msg = _group_message(_MEMBER_A, "亲密模式 开", ["user"], group_id=_G_UNLISTED)
    provider = _CapturingProvider()
    result, _ = _turn(msg, cfg, provider)

    assert provider.calls >= 1, "准入门被摘后这句反而走了指令短路（=猜开放）"
    assert result.body != MANUAL_ON_REPLY
    assert "content_route" not in (result.audit_tags or []), result.audit_tags
    ctx = _verdict_of(msg, cfg)
    assert ctx["eligible"] is False
    verdict = SHARED_CONTENT_ROUTE_ENGINE.route_verdict(ctx["route_key"], cfg)
    assert verdict["mode"] == "normal"
    assert verdict["source"] == INTIMATE_SOURCE_NONE


def test_blacklisted_group_wins_over_whitelist() -> None:
    """黑名单优先：同一群既在白名单又在黑名单 ⇒ 开关照样不受理。"""
    cfg = _config(_G_BLACK, bot_content_route_group_blacklist=[_G_BLACK])
    msg = _group_message(_ADMIN, "亲密模式 深开", ["admin", "super_admin"], group_id=_G_BLACK)
    provider = _CapturingProvider()
    result, _ = _turn(msg, cfg, provider)

    assert result.body != MANUAL_DEEP_ON_REPLY
    assert provider.calls >= 1
    verdict = SHARED_CONTENT_ROUTE_ENGINE.route_verdict(
        group_scope_key(msg.session_id), cfg
    )
    assert verdict["mode"] == "normal"


def test_total_gate_off_leaves_the_switch_unanswered() -> None:
    """总闸关（`bot_content_route_enabled=False`）：整条亲密面熄火，回执不许自己活。"""
    cfg = _config(_G_MASTER_OFF, bot_content_route_enabled=False)
    msg = _group_message(
        _ADMIN, "亲密模式 开", ["admin", "super_admin"], group_id=_G_MASTER_OFF
    )
    provider = _CapturingProvider()
    result, _ = _turn(msg, cfg, provider)

    assert result.body != MANUAL_ON_REPLY
    assert provider.calls >= 1
    assert "content_route" not in (result.audit_tags or []), result.audit_tags


# ============================== ④ 反向不误伤：成员档不泄漏给同群其他人（历史缺陷不回潮）


def test_member_pin_does_not_leak_to_other_group_members() -> None:
    """A 自己拨开关 ⇒ A 进档、B 一步都不动（B-Important-1 那一格泄漏的历史缺陷）。

    两条腿都量：注入缝的裁决（`resolve_intimate_context`）+ 下一轮**真发出去的
    system 文本**里亲密段在不在——只看裁决表会放过「判据对、注入缝另读一把键」。
    """
    cfg = _config(_G_LEAK)
    msg_a = _group_message(_MEMBER_A, "亲密模式 开", ["user"], group_id=_G_LEAK)
    _turn(msg_a, cfg)

    ctx_a = _verdict_of(msg_a, cfg)
    assert ctx_a["eligible"] is True and ctx_a["mode"] == "intimate", ctx_a

    msg_b = _group_message(_MEMBER_B, "今天天气怎么样", ["user"], group_id=_G_LEAK)
    provider_b = _CapturingProvider()
    _turn(msg_b, cfg, provider_b)
    ctx_b = _verdict_of(msg_b, cfg)
    assert ctx_b["mode"] == "normal", ctx_b
    joined_b = _system_join(provider_b)
    assert INTIMATE_RP_STYLE_INSTRUCTION not in joined_b, (
        "A 的个人钉泄漏给了 B（亲密叙述档进了别人的请求体）"
    )

    provider_a = _CapturingProvider()
    _turn(
        _group_message(_MEMBER_A, "继续陪我聊会", ["user"], group_id=_G_LEAK),
        cfg,
        provider_a,
    )
    assert INTIMATE_RP_STYLE_INSTRUCTION in _system_join(provider_a)


def test_admin_group_pin_covers_the_group_but_writes_only_the_scope_key() -> None:
    """管理员开关二（全群）：别人确实进档，但**只**写在整群作用域键上。

    成员派生键必须仍然没有自己的钉——否则「全群生效」会退化成逐成员复制一份私档，
    关都关不掉（读写分叉的家谱形态）。
    """
    cfg = _config(_G_ADMIN_SCOPE)
    msg_admin = _group_message(
        _ADMIN, "亲密模式 开", ["admin", "super_admin"], group_id=_G_ADMIN_SCOPE
    )
    _turn(msg_admin, cfg)

    scope_key = group_scope_key(msg_admin.session_id)
    assert scope_key == "group:700100016", scope_key
    assert SHARED_CONTENT_ROUTE_ENGINE.pinned_mode(scope_key, cfg) == MODE_INTIMATE
    for other in (_MEMBER_A, _MEMBER_B):
        member_key = member_session_key(build_session_key(_G_ADMIN_SCOPE, other), other)
        assert _pin_on_own_key(member_key) != MODE_INTIMATE, (
            f"全群钉被抄进了 {other} 的个人键：关不掉的那一种"
        )
        ctx = _verdict_of(_group_message(other, "在吗", ["user"], group_id=_G_ADMIN_SCOPE), cfg)
        assert ctx["mode"] == "intimate", ctx
        assert ctx["source"] == INTIMATE_SOURCE_ADMIN_PIN
        assert ctx["tier"] == INTIMATE_TIER_L1


# ============================ ⑤ 私聊那一侧不许被顺手放宽（同一条代码支的邻居）


def test_private_ack_stays_personal_and_still_passes_review() -> None:
    """私聊回执仍是 PERSONAL（会话本身就是 1:1），且审核放行——改群腿不许动私腿。"""
    cfg = _config(_G_ACK)
    msg = _private_message(_ADMIN, "亲密模式 开")
    result, provider = _turn(msg, cfg)

    assert provider.calls == 0
    assert result.body == MANUAL_ON_REPLY
    assert "scope:self" in (result.audit_tags or []), result.audit_tags
    assert result.privacy_level is PrivacyLevel.PERSONAL
    assert review_capability_result(result, _decision(msg)).approved is True


# ========== ⑥ 2026-10-02 用户裁定：人在私聊白名单 ⇒ 任何群都能开（群分支人腿）


def test_person_in_private_whitelist_can_switch_in_group_outside_group_whitelist() -> None:
    """人腿正例·端到端：群不在群白名单、人在私聊白名单 ⇒ 开关句照常受理。

    主链取证：指令短路接住（不走模型）、回执出门（审核放行）、成员派生键真进
    intimate 档——证明人腿不是只活在判定函数里，而是整条**可送达**。
    """
    cfg = _config(
        _G_PERSON_LEG,
        bot_content_route_group_whitelist=[],
        bot_content_route_private_whitelist=[_MEMBER_A],
    )
    msg = _group_message(_MEMBER_A, "亲密模式 开", ["user"], group_id=_G_PERSON_LEG)
    result, provider = _turn(msg, cfg)

    assert provider.calls == 0, "人腿没接住这句，跑去问模型了"
    assert result.body == MANUAL_ON_REPLY
    assert "scope:user" in (result.audit_tags or []), result.audit_tags
    assert review_capability_result(result, _decision(msg)).approved is True
    own_key = member_session_key(msg.session_id, _MEMBER_A)
    verdict = SHARED_CONTENT_ROUTE_ENGINE.route_verdict(own_key, cfg)
    assert verdict["mode"] == "intimate"
    assert verdict["source"] == INTIMATE_SOURCE_MANUAL
    # 判定函数直读（同函数私聊分支的集合收集形态、四步顺序的真身）：
    assert explicit_allowed_for_session(
        "group", _G_PERSON_LEG, cfg, sender_id=_MEMBER_A
    ) is True


def test_person_outside_private_whitelist_stays_closed_in_unlisted_group() -> None:
    """人腿反例：同群、人不在私聊白名单 ⇒ False（判定函数直读 + 主链不受理）。

    随手两枚小护栏：空 ``sender_id``（缺省调用面）不匹配任何名单 ⇒ 旧行为
    逐字节一致；群白名单命中那条路对无 sender 调用面照旧放行（②既有路不被
    人腿改写）。
    """
    cfg = _config(
        _G_PERSON_NEG,
        bot_content_route_group_whitelist=[],
        bot_content_route_private_whitelist=[_MEMBER_A],
    )
    assert explicit_allowed_for_session(
        "group", _G_PERSON_NEG, cfg, sender_id=_MEMBER_B
    ) is False
    assert explicit_allowed_for_session("group", _G_PERSON_NEG, cfg) is False
    whitelisted_cfg = _config(_G_PERSON_NEG)
    assert explicit_allowed_for_session("group", _G_PERSON_NEG, whitelisted_cfg) is True

    # 端到端面：名单外的人说开关句不受理，落回普通聊天（绝不猜开放）。
    msg = _group_message(_MEMBER_B, "亲密模式 开", ["user"], group_id=_G_PERSON_NEG)
    provider = _CapturingProvider()
    result, _ = _turn(msg, cfg, provider)
    assert provider.calls >= 1, "名单外的人反而走了指令短路（=人腿猜开放）"
    assert result.body != MANUAL_ON_REPLY
    assert "content_route" not in (result.audit_tags or []), result.audit_tags


def test_group_blacklist_beats_the_person_leg() -> None:
    """人腿反例：群在群黑名单 ⇒ 人再白也 False（群黑名单压过人腿，顺序即裁定）。

    本例群同时挂在群白名单与黑名单上、人又在私聊白名单上：两白齐备只差一道黑
    ——正是「黑名单永远赢」最锋利的形态；顺带主链取证开关句不受理。
    """
    cfg = _config(
        _G_PERSON_BLACK,
        bot_content_route_group_whitelist=[_G_PERSON_BLACK],
        bot_content_route_group_blacklist=[_G_PERSON_BLACK],
        bot_content_route_private_whitelist=[_MEMBER_A],
    )
    assert explicit_allowed_for_session(
        "group", _G_PERSON_BLACK, cfg, sender_id=_MEMBER_A
    ) is False

    msg = _group_message(_MEMBER_A, "亲密模式 开", ["user"], group_id=_G_PERSON_BLACK)
    provider = _CapturingProvider()
    result, _ = _turn(msg, cfg, provider)
    assert provider.calls >= 1, "群黑名单在场上，人腿却把开关句送进了指令短路"
    assert result.body != MANUAL_ON_REPLY


def test_tts_m17_group_gate_passes_sender_to_the_admission_gate() -> None:
    """消费者 AST 腿：M-17 自动配音的群面门必须把 sender 带给名单门。

    ``should_voice_reply`` 是名单门的真消费者之一（tts.py）；不传 sender，
    content_route 的人腿对它永远关闭，「人在白名单 ⇒ 任何群可开」只剩半条腿。
    静态断言：group 形调用的第四参必须真实引用 ``message.sender_id``。
    """
    tree = ast.parse(_TTS_SOURCE.read_text(encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", "") != "explicit_allowed_for_session":
            continue
        args = node.args
        if (
            not args
            or not isinstance(args[0], ast.Constant)
            or args[0].value != "group"
        ):
            continue
        checked += 1
        sender_arg = None
        if len(args) >= 4:
            sender_arg = args[3]
        else:
            sender_arg = next(
                (kw.value for kw in node.keywords if kw.arg == "sender_id"), None
            )
        assert sender_arg is not None, (
            "M-17 群面调用没把 sender 带上 ⇒ 人腿对这条消费者永远关闭"
        )
        assert "sender_id" in ast.dump(sender_arg), (
            f"第四参没有引用 message.sender_id：{ast.dump(sender_arg)}"
        )
    assert checked >= 1, (
        "tts.py 找不到 group 形态的 explicit_allowed_for_session 调用（M-17 门被搬走了？）"
    )


# ========== ⑦ REV 对抗复核补腿（2026-10-02 下午窗）：人腿的两条未测边界
# 只 append；上方 16 腿为 INT 交付，判据一字未动。

_G_PERSON_PBL = "700100022"  # REV 腿：人同时挂私聊白/黑双名单（私聊黑压人腿）
_G_PERSON_WS = "700100023"   # REV 腿：sender 与名单条目的 strip 归一


def test_private_blacklist_beats_the_person_leg() -> None:
    """人腿反例：人同时在私聊白名单与私聊黑名单、群不在群白 ⇒ False。

    既有 `_G_PERSON_BLACK` 腿锁的是**群**黑名单压人腿；这一格锁**私聊**
    黑名单——群分支 ③ 的 `sid not in pbl` 是独立的第二把闸（裁定原文
    「私聊黑名单只关人腿」的另一面＝人腿自己必须被它压住）。两枚黑名单
    少锁任何一枚，「黑名单永远赢」就有半边裸奔。
    """
    cfg = _config(
        _G_PERSON_PBL,
        bot_content_route_group_whitelist=[],
        bot_content_route_private_whitelist=[_MEMBER_A],
        bot_content_route_private_blacklist=[_MEMBER_A],
    )
    assert explicit_allowed_for_session(
        "group", _G_PERSON_PBL, cfg, sender_id=_MEMBER_A
    ) is False

    msg = _group_message(_MEMBER_A, "亲密模式 开", ["user"], group_id=_G_PERSON_PBL)
    provider = _CapturingProvider()
    result, _ = _turn(msg, cfg, provider)
    assert provider.calls >= 1, "私聊黑名单在场上，人腿却把开关句送进了指令短路"
    assert result.body != MANUAL_ON_REPLY
    assert "content_route" not in (result.audit_tags or []), result.audit_tags


def test_person_leg_matches_after_stripping_sender_and_list_entries() -> None:
    """人腿边界：sender 与名单条目**两边都 strip** 后逐字匹配；纯空白 sender ⇒ 人腿关闭。

    名单条目带首尾空白（人工编辑 `.env` 时 ``a, b`` 切分的常见残留）或 sender
    带空白时，判定必须与干净形态同判——collect 与 sid 两侧任一侧丢了 strip
    当场红。纯空白/空 sender（消费者 getattr 缺省、脏消息）不启用人腿，群白
    又空 ⇒ False，绝不猜开放；名单里的纯空白条目被收集形态过滤、不产生幽灵键。
    """
    padded = f" {_MEMBER_A} "
    cfg = _config(
        _G_PERSON_WS,
        bot_content_route_group_whitelist=[],
        bot_content_route_private_whitelist=[padded, "   "],
    )
    # 群白空 ⇒ True 只可能来自人腿：条目带空白、sender 干净 ⇒ 同判。
    assert explicit_allowed_for_session(
        "group", _G_PERSON_WS, cfg, sender_id=_MEMBER_A
    ) is True
    # sender 带空白（strip 后命中）⇒ 同判。
    assert explicit_allowed_for_session(
        "group", _G_PERSON_WS, cfg, sender_id=padded
    ) is True
    # 纯空白 sender ⇒ sid 归空 ⇒ 人腿整体关闭 ⇒ False（不是放开）。
    assert explicit_allowed_for_session(
        "group", _G_PERSON_WS, cfg, sender_id="   "
    ) is False
    assert explicit_allowed_for_session("group", _G_PERSON_WS, cfg) is False
