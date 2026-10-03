"""v21r2 RP 席：R-18 文风多样化与复读三连治理（离线单测）。

覆盖（设计稿 docs/design/v21r2-rp-style-log.md §五.3）：
- 文风指令按 content_route 会话态二选一注入（互斥）：INTIMATE=动作/环境/
  体感详细描写+篇幅放开；normal=全年龄禁动作描写；
- 路由整体关闭时仍得 normal 禁令（全年龄全局口径）；
- 复读三连（「我不会躲。」「我在。」「我在这里。」）不再以固定形态出现在
  提示词常量与人格源改写节；
- 危险安抚示例池规模 ≥8 + 游标轮换确定性（整轮无重复、重放一致）。

minors 硬红线回归由 tests/test_content_safety_v2.py、tests/test_content_route.py
承担（本文件不重复）。
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

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
    _DANGER_COMFORT_EXAMPLES,
    INTIMATE_RP_STYLE_INSTRUCTION,
    NORMAL_NO_ACTION_INSTRUCTION,
    _danger_style_line,
    build_chat_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import LLMReply
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    MASTER_LOVE_INSTRUCTION,
    SHARED_CONTENT_ROUTE_ENGINE,
    grants_intimate_narration,
)

_REPO = Path(__file__).resolve().parents[1]


class _CapturingProvider:
    """记录收到的 messages 并原样成功返回（触发 prompt 组装全链）。"""

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def generate(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> LLMReply:
        self.messages = messages
        return LLMReply(text="嗯，我在听。你慢慢说。", provider="fake", model="m")


# DATAFIX：称谓偏好 store 无键时走生产 getattr 缺省 "data/addressing_preferences.sqlite3"，
# 会把测试读写的 sqlite 落到运行数据根或源码树 data/。显式注入本件独有临时绝对路径，
# 只改测试构造参数、不动生产缺省逻辑。
_TMP_DATA_DIR = tempfile.mkdtemp(prefix="thyg-rpsd-")


def _config(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_addressing_preferences_db_path": os.path.join(
            _TMP_DATA_DIR, "addressing_preferences.sqlite3"
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
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _message(session_id: str, text: str = "今天有点累，想和你说说话。") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id="user-rp",
        plain_text=text,
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _context(
    session_id: str, *, action_brackets: bool = True
) -> ContextBundle:
    return ContextBundle(
        request_id="req-rp-style",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
        ),
        # `action_brackets` 是**出站**那一道括号动作处置开关的契约字段：
        # 生产 `.env:26 BOT_PERSONA_ACTION_BRACKETS=false` ⇒ 走 `strip_action_brackets`
        # （含汉字括号动作整段删除）。本件默认 True 以保持既有用例原义。
        tone=ToneProfile(
            profile_id="shorekeeper", mode="default", action_brackets=action_brackets
        ),
        memory_results=MemoryRetrievalResult(request_id="req-rp-style"),
        conversation_history=ConversationHistoryResult(request_id="req-rp-style"),
        knowledge_results=RetrievalResult(request_id="req-rp-style"),
        current_message="今天有点累，想和你说说话。",
        sender_id="user-rp",
        session_id=session_id,
    )


class _ActionProvider:
    """产回**带括号动作**的正文——模拟模型确实照五维令写了动作/神态。

    她 2026-10-03 的线上缺陷就是这一类输出被出站删掉了：叙述授予令在 prompt 里
    （已由 :func:`test_master_love_session_keeps_tone_but_drops_narration` 等证实在场），
    但 `action_brackets=false` 让 `strip_action_brackets` 把动作段整段抹掉 ⇒
    「开了亲密模式还是不描写动作」。
    """

    TEXT = "（轻轻靠近你）今天累了吧。\n（把手放在你背上）我在。"

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def generate(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> LLMReply:
        self.messages = messages
        return LLMReply(text=self.TEXT, provider="fake", model="m")


def _run_action_turn(
    *, session: str, cfg: object, command: str, action_brackets: bool
) -> str:
    """跑两轮：先 `command`（开档/或 ML 自动），再普通话一句，返回第二轮出站正文。"""
    if command:
        first = _message(session, text=command)
        build_chat_result(
            first, _decision(first), _context(session, action_brackets=action_brackets),
            llm_provider=_ActionProvider(), content_route_config=cfg,
        )
    second = _message(session, text="那你会怎么陪我。")
    result = build_chat_result(
        second, _decision(second), _context(session, action_brackets=action_brackets),
        llm_provider=_ActionProvider(), content_route_config=cfg,
    )
    return str(getattr(result, "body", "") or "")


def test_ungranted_turn_still_stripped_when_brackets_suppressed() -> None:
    """**回归保护**：没拿到叙述授予（ML 自动档）且生产关着括号动作 ⇒ 照旧被剥掉。

    她 2026-09-28 的裁定「日常沟通不写动作神态」这条硬保证不能被本波放宽。
    """
    cfg = _config(bot_master_love_enabled=True, bot_master_love_admins=["user-rp"])
    body = _run_action_turn(
        session="private:rp-style-strip-ungranted", cfg=cfg,
        command="", action_brackets=False,
    )
    assert "轻轻靠近你" not in body, "未授予的轮次不该带括号动作（日常硬保证被削）"


def test_granted_intimate_turn_keeps_actions_despite_global_suppression() -> None:
    """拿到叙述授予的那轮，出站**不得**再把括号动作整段删掉（线上缺陷根修）。

    判据复用同一个门（`_rp_intimate_now`）：授予了叙述却仍被 `strip_action_brackets`
    抹掉，等于"令在 prompt 里、货在出口被没收"——她看到的就是这个。
    反向保护：本波**不动** `BOT_PERSONA_ACTION_BRACKETS` 的全局语义，未授予轮次照旧剥
    （见上一枚测试）。
    """
    cfg = _config()
    body = _run_action_turn(
        session="private:rp-style-strip-granted", cfg=cfg,
        command="亲密模式 开", action_brackets=False,
    )
    assert "轻轻靠近你" in body, f"开档后仍被剥掉动作段 ⇒ 缺陷未修：{body!r}"
    assert "我在" in body


def _system_join(provider: _CapturingProvider) -> str:
    return "\n".join(
        str(item.get("content") or "")
        for item in provider.messages
        if item.get("role") == "system"
    )


# ---------------------------------------------------------------- 会话态互斥注入


def _section_header(instruction: str) -> str:
    """段落头从常量**真身**派生（字面量收单源，家规同 chat 的 TIER_LINE_PREFIX）。

    他席改标题措辞（2026-09-28 实跑：「亲密场景」→「亲密与成人向场景」）时，硬编码
    的第二份字面量会当场失配、把这条互斥锁变成假红。派生之后仍然咬得住：本文件
    正反两面都判（亲密态判「日常头不在」＋日常态判「亲密头不在」），注入腿一旦断，
    presence 那侧必红。
    """
    head, marker, _ = instruction.partition("】")
    assert marker, "场景散文常量丢了【…】段落头，注入面无法辨识"
    assert head.startswith("【"), "段落头必须以【开头"
    return f"{head}{marker}"


_INTIMATE_HEADER = _section_header(INTIMATE_RP_STYLE_INSTRUCTION)
_NORMAL_HEADER = _section_header(NORMAL_NO_ACTION_INSTRUCTION)


def test_two_scene_sections_have_distinct_headers() -> None:
    """互斥判据的前提：两段各有自己的头。同头 ⇒ 上面那三条 not in 全是空判。"""
    assert _INTIMATE_HEADER != _NORMAL_HEADER


def test_intimate_session_gets_action_directive() -> None:
    session = "private:rp-style-intimate-1"
    cfg = _config()
    assert SHARED_CONTENT_ROUTE_ENGINE.apply_manual(session, "intimate", cfg) is True
    provider = _CapturingProvider()
    message = _message(session)
    build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=cfg,
    )
    joined = _system_join(provider)
    assert _INTIMATE_HEADER in joined
    # T8（2026-09-28 用户裁定「档位风格统一」）：亲密段不再自带篇幅口径（旧断言的
    # 「能详则详」已从常量里摘掉，篇幅唯一真身＝那一行长度分档指令）。这一段现在
    # 只准管**描写维度**，所以断言改判它承诺过的那一维。
    assert "动作、神态、呼吸、触感、心理" in joined
    assert "能详则详" not in joined and "放宽篇幅" not in joined
    assert "动作" in joined
    assert _NORMAL_HEADER not in joined  # 互斥：不并存
    assert "不加括号" not in joined


def test_master_love_session_keeps_tone_but_drops_narration() -> None:
    """Master Love 自动档只给语气，**不给展开描写**（2026-10-04 用户裁定）。

    她要的是「superadmin 的默认 master love 模式仍然只描述说话内容，输入显式指令
    打开 L1/L2 才变成这样」。判据不看 mode 布尔，看**这枚钉是谁上的**：
    `master_love` 属自动派生来源，不在授予面上。

    防过修保护：恋人语气（关系指令那一格）**必须仍在场**——本裁定收的是叙述维度，
    不是把 ML 的档与语气一起摘掉。
    """
    session = "private:rp-style-ml-1"
    cfg = _config(bot_master_love_enabled=True, bot_master_love_admins=["user-rp"])
    provider = _CapturingProvider()
    message = _message(session)
    build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=cfg,
    )
    joined = _system_join(provider)
    # ① ML 确实进了亲密档（否则这条测试什么都没测）：语气那一格必须在场。
    assert MASTER_LOVE_INSTRUCTION in joined, "ML 根本没进档＝本测试没测到要测的东西"
    # ② 但叙述维度必须收回去：拿的是日常禁令，不是亲密展开段。
    assert _NORMAL_HEADER in joined
    assert _INTIMATE_HEADER not in joined
    assert "动作、神态、呼吸、触感、心理" not in joined


def test_narration_grant_is_its_own_axis_not_a_borrowed_one() -> None:
    """五维授予面**必须是独立一轴**，不许是哪张既有来源集的顺带读数。

    来历：`_MODEL_SWITCH_SOURCES` 与 `_MAX_TTL_EXEMPT_SOURCES` 今天与授予面成员高度
    重叠，"顺手复用一张集"看起来零成本——但一枚答"要不要换真实首跳"、一枚答"这钉该
    不该被 TTL 上限悄悄截掉"、一枚答"要不要展开叙述"。复用之后，任何一侧独立放宽
    （给 ML 免 TTL、给浅档换模型）都会**静默把五维授予面一起放大**，正是她 09-28
    立过的那句「换了个档，结果文风全部都变了，那肯定不对」。
    本锁用 `content_signal` 当探针：它在"换模型"面上、**不在**"TTL 豁免"面上
    ⇒ 三张集结构上不可能同一枚。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        content_route as cr,
    )

    # 授予面逐枚点名（白名单形：未知来源一律不授予＝fail-closed）
    assert grants_intimate_narration(cr.INTIMATE_SOURCE_MANUAL) is True
    assert grants_intimate_narration(cr.INTIMATE_SOURCE_ADMIN_PIN) is True
    assert grants_intimate_narration(cr.INTIMATE_SOURCE_CONTENT_SIGNAL) is True
    assert grants_intimate_narration(cr.INTIMATE_SOURCE_MASTER_LOVE) is False
    assert grants_intimate_narration(cr.INTIMATE_SOURCE_AFFINITY) is False
    assert grants_intimate_narration(cr.INTIMATE_SOURCE_NONE) is False
    assert grants_intimate_narration("whoever") is False
    # 三轴各自独立：证明授予面≠TTL 豁免面（content_signal 一枚就能区分开）
    assert (cr.INTIMATE_SOURCE_CONTENT_SIGNAL in cr._MAX_TTL_EXEMPT_SOURCES) is False
    assert (cr.INTIMATE_SOURCE_CONTENT_SIGNAL in cr._MODEL_SWITCH_SOURCES) is True
    assert grants_intimate_narration(cr.INTIMATE_SOURCE_CONTENT_SIGNAL) is not (
        cr.INTIMATE_SOURCE_CONTENT_SIGNAL in cr._MAX_TTL_EXEMPT_SOURCES
    ), "授予面与 TTL 豁免面同形＝其中一枚已被复用，两轴已并成一条"
    # 注毒自证：若有人把 ML 塞进授予面，本门必红
    assert cr.INTIMATE_SOURCE_MASTER_LOVE not in cr._INTIMATE_NARRATION_SOURCES


def test_intimate_route_forbids_labelling_its_own_content() -> None:
    """亲密段自带「别替这段文字贴类别标签」——群聊出站闸的防自陈护栏（2026-10-03）。

    来历：`domains/render/reviewer.py` 的 `_PUBLIC_OUTPUT_UNSAFE` 只在
    `target_scope is SessionType.GROUP` 那一支跑，性相关词面含 `r[- ]?18`、「色情描写」、
    「裸体细节」等，命中即 **整条 BLOCK** ⇒ 群里"什么都收不到"，比降级更糟。而亲密段
    原文带「（含 R-18 向）」，模型很容易把这枚标签词复述进正文＝自己把自己拦掉。
    修法只在**判据侧**加一句"别贴标签"，**不动那道闸**（本仓家规：门只准变严）。
    """
    clause = "别替这段文字贴类别标签"
    assert clause in INTIMATE_RP_STYLE_INSTRUCTION
    # 日常段不该有这句：它本就不写叙述，没有可贴的标签
    assert clause not in NORMAL_NO_ACTION_INSTRUCTION
    # 注毒自证：摘掉这句，本门必须看得见（摘不掉＝源串写法漂移，门已空跑）
    stripped = INTIMATE_RP_STYLE_INSTRUCTION.replace(clause, "", 1)
    assert clause not in stripped
    # 篇幅口径不在这条断言里判：`test_reply_policy_permanent.py` 的
    # `test_route_style_instructions_carry_no_length_truth` 已把**整段常量**扫过
    # 黑名单与 `\d+字`，这里再判一遍只会长出第二把尺（本席曾误写
    # `"字" not in clause`，被「文**字**」当场打红——冗余断言自己就是缺陷）。


def test_persona_prose_does_not_smuggle_length_doctrine() -> None:
    """篇幅黑名单必须**也扫人格散文**——否则门绿、生产却在端"篇幅放开"。

    来历（2026-10-03 现算）：`test_reply_policy_permanent.py` 的
    `test_route_style_instructions_carry_no_length_truth` 只把 `_ROUTE_LENGTH_PHRASES`
    喂给 `chat.py` 那两段常量，**人格侧一个字都不扫**。而
    `personas/shorekeeper/knowledge/守岸人_人格与表达规范.md` 的"节奏"那一格长期写着
    「篇幅放开、能详则详、绝不一句话打发」，经 `.env` 的 `BOT_KNOWLEDGE_FILES`
    **直读源码树**进生产 prompt ⇒ 09-28 那次 T8 收口只收了代码侧、没收人格侧，
    长度于是长出第二真身（她后来抱怨"开了却不长/忽长忽短"的机理之一）。
    黑名单只借同源那一份，绝不在这儿抄第二遍。
    """
    import importlib.util

    sibling = _REPO / "tests" / "test_reply_policy_permanent.py"
    spec = importlib.util.spec_from_file_location("_rp_len_src", sibling)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    banned = tuple(module._ROUTE_LENGTH_PHRASES)

    targets = [
        _REPO / "personas" / "shorekeeper" / "knowledge" / "守岸人_人格与表达规范.md",
        _REPO / "personas" / "shorekeeper" / "identity.md",
        _REPO.parent / "ChatBot_Runtime" / "data" / "persona" / "守岸人_核心人格.md",
    ]
    scanned = 0
    for path in targets:
        if not path.exists():  # 运行副本缺失时优雅跳过（与文案红线门同口径）
            continue
        text = path.read_text(encoding="utf-8")
        smuggled = [phrase for phrase in banned if phrase in text]
        assert not smuggled, f"{path.name} 自带篇幅口径 {smuggled} ⇒ 长度长出第二真身"
        assert not re.search(r"\d+\s*字", text), f"{path.name} 手抄了字数下限"
        scanned += 1
    assert scanned >= 2, f"只扫到 {scanned} 件 ⇒ 判据面塌了，本门在空跑"


def test_normal_session_gets_no_action_directive() -> None:
    session = "private:rp-style-normal-1"
    cfg = _config()
    provider = _CapturingProvider()
    message = _message(session, text="今天天气怎么样？")
    build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=cfg,
    )
    joined = _system_join(provider)
    assert _NORMAL_HEADER in joined
    assert "不加括号" in joined
    assert _INTIMATE_HEADER not in joined  # 互斥：不并存


def test_route_disabled_still_gets_normal_directive() -> None:
    session = "private:rp-style-route-off-1"
    provider = _CapturingProvider()
    message = _message(session, text="晚饭吃什么好")
    build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=None,
    )
    joined = _system_join(provider)
    assert _NORMAL_HEADER in joined
    assert _INTIMATE_HEADER not in joined


# ---------------------------------------------------------------- 复读三连治理

def test_repeat_trio_absent_from_prompt_constants() -> None:
    assert "我不会躲" not in INTIMATE_RP_STYLE_INSTRUCTION
    assert "我不会躲" not in NORMAL_NO_ACTION_INSTRUCTION
    for variant in _DANGER_COMFORT_EXAMPLES:
        assert "我不会躲" not in variant
        assert "我在这里。" not in variant
        assert "我在。" not in variant


def test_repeat_trio_absent_from_persona_source_fixed_forms() -> None:
    persona_path = (
        _REPO / "personas" / "shorekeeper" / "knowledge" / "守岸人_人格与表达规范.md"
    )
    persona_text = persona_path.read_text(encoding="utf-8")
    # 旧 MaiBot 合并节的极简三连示例（固定形态）必须已被多样化改写替换。
    assert '"我在这里。"、"你回来了。"、"我等你。"' not in persona_text
    assert "“我在这里”“我会一直听着”" not in persona_text
    assert "我不会躲" not in persona_text
    assert "我在这里......一直都在" not in persona_text
    # 多样化指引与变体池在位。
    assert "在场与安抚，从来不是同一句话" in persona_text
    assert "不重复固定短句" in persona_text


def test_runtime_answer_rules_no_longer_carry_fixed_example() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        _RUNTIME_ANSWER_RULES,
    )

    assert "我在这里" not in _RUNTIME_ANSWER_RULES
    assert "不用怕。" not in _RUNTIME_ANSWER_RULES
    # 危险与战斗引导改为动态轮换行（含池示例）。
    line = _danger_style_line()
    assert line.startswith("危险与战斗：")
    assert any(example in line for example in _DANGER_COMFORT_EXAMPLES)


# ---------------------------------------------------------------- 池化轮换

def test_danger_pool_size_and_deterministic_rotation() -> None:
    from plugins.bot_unified_runtime.domains.assistant.daily.store import daily_assist

    pool = _DANGER_COMFORT_EXAMPLES
    assert len(pool) >= 8
    daily_assist._VARIANT_CURSORS.pop("chat_danger_comfort", None)
    first_cycle = [_danger_style_line() for _ in range(len(pool))]
    daily_assist._VARIANT_CURSORS["chat_danger_comfort"] = 0
    second_cycle = [_danger_style_line() for _ in range(len(pool))]
    assert first_cycle == second_cycle  # 同起点重放一致（确定性）
    assert len(set(first_cycle)) == len(pool)  # 整轮无重复


# ==================== S17（2026-10-04）：授予轮的篇幅走「铺写」档 ====================
#
# 篇幅数值只住 `REPLY_LENGTH_TIERS`（本文件一个数字都不抄，全部从登记表取），
# 这里只验**端到端行为**：真进模型的那一行长度指令，授予与否各落在哪一档。


def _chat_module():
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat

    return chat


def _length_line_of(joined: str) -> str:
    """本轮真进模型的那一行长度指令（恰好一条；两行＝模型读到两句拆台话）。"""
    prefix = _chat_module().TIER_LINE_PREFIX
    lines = [line for line in joined.splitlines() if prefix in line]
    assert len(lines) == 1, f"长度指令行数＝{len(lines)}（必须恰好一条）"
    return lines[0]


def test_granted_turn_carries_the_scene_length_line() -> None:
    """显式开档那一轮：长度指令＝铺写档（她 10-04 裁定「六百到一千字为佳」）。

    现网实测 261 / 201 字的机理＝那一行最远只到「详尽：不少于 300 字」，
    且后半句是知识题口径；本件钉的是**改完之后真发出去的那一行**。
    """
    chat = _chat_module()
    session = "private:rp-style-scene-granted"
    cfg = _config()
    assert SHARED_CONTENT_ROUTE_ENGINE.apply_manual(session, "intimate", cfg) is True
    provider = _CapturingProvider()
    message = _message(session)
    build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=cfg,
    )
    joined = _system_join(provider)
    scene = chat.REPLY_LENGTH_TIERS[chat.REPLY_TIER_SCENE_ID]
    line = _length_line_of(joined)
    assert f"当前档＝{scene.label_cn}" in line, line
    assert f"不少于 {scene.min_chars} 字" in line, line
    assert f"不超过 {scene.max_chars} 字" in line, line
    # 同一个授予判据 ⇒ 长度升格与五维展开段必须同轮在场（不许一半一半）
    assert _INTIMATE_HEADER in joined


def test_ungranted_master_love_turn_keeps_normal_prose_and_short_tier() -> None:
    """防过修：ML 自动档那一轮**既**拿日常禁令段、**也**拿不到铺写档。

    未授予路径必须逐字等于 `resolve_reply_length_tier` 的读数（升格只挂在授予腿上），
    档名与那句指令都从真身派生，本件不抄任何数值。
    """
    chat = _chat_module()
    session = "private:rp-style-scene-ml"
    cfg = _config(bot_master_love_enabled=True, bot_master_love_admins=["user-rp"])
    provider = _CapturingProvider()
    message = _message(session)
    build_chat_result(
        message,
        _decision(message),
        _context(session),
        llm_provider=provider,
        content_route_config=cfg,
    )
    joined = _system_join(provider)
    assert MASTER_LOVE_INSTRUCTION in joined, "ML 根本没进档＝本测试没测到要测的东西"
    assert _NORMAL_HEADER in joined and _INTIMATE_HEADER not in joined
    line = _length_line_of(joined)
    scene_label = chat.REPLY_LENGTH_TIERS[chat.REPLY_TIER_SCENE_ID].label_cn
    assert scene_label not in line, f"未授予的轮次被抬进了铺写档：{line}"
    ungranted = chat.resolve_reply_length_tier("", message.plain_text)
    assert line == chat.reply_length_guidance_text(ungranted), (
        f"未授予轮的长度指令不再是那条单一真身：{line!r} vs {ungranted!r}"
    )
