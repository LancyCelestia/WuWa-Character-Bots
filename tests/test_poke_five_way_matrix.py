"""戳一戳「五腿 × 两场景」可达性矩阵 + 分发器读点真值锁（S-T-POKE，ITEM 14）。

三块判据，都不发网络、不发消息、写只写 ``tmp_path``：

① **分发器十枚读点的兜底值必须等于 ``config.py`` 的字段缺省**（AST 现读两处真身，
   测试里一个数字都不抄）。这是本仓最高频的失效形态之一：兜底值写歪一枚，
   配置面开着、这里读成关，而 ``getattr`` 的默认值永远不会报错。
② **用户点名的五腿（反戳 / 自然语言回复 / 语音+文本 / 表情包 / 随机图）在群聊与
   私聊两个场景里都能被选到**，且「被戳贴表情」这一条在两个场景里都**结构性**选不
   到（它不在池里、不可点名）——私聊那条硬约束不许靠"跑到一半抛异常"实现。
③ **管理员把臂名写错时不留暗坑**：判据本身不改判（那是替她决定另一件事），
   但必须在 ``audit_tags`` 里点名，且点名的串不能变成任意形态的标签。

根装配文件（生产根文件，本席禁写）只被**读**：AST 现算「voice 那条腿的文本腿今天
到底填没填 LLM 文本」，缺的那一发以 ``xfail(strict=True)`` 钉成摘牌钩子。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    POKE_MIX_KEYWORD,
    PokeDispatcher,
    PokeEvent,
    poke_mode_is_recognized,
    poke_mode_label_for_audit,
    poke_reaction_cell,
    proactive_action_allowed,
    resolve_poke_reply_mode,
)
from plugins.bot_unified_runtime.domains.meme.reactions.engine import ProactiveGate

REPO_ROOT = Path(__file__).resolve().parents[1]
POKE_SRC = REPO_ROOT / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/poke.py"
CONFIG_SRC = REPO_ROOT / "plugins/bot_unified_runtime/config.py"
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"

#: 用户 ITEM 14 点名的五条腿（"任意一个"）。
REQUIRED_ARMS: tuple[str, ...] = ("poke", "llm", "voice", "meme", "randpic")


# --------------------------------------------------------------- 共用小工具


def _literal(node: ast.AST) -> Any:
    """取字面量；``Field(default=…)`` 形态退到它的 ``default``。"""
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Field":
        for kw in node.keywords:
            if kw.arg == "default":
                return ast.literal_eval(kw.value)
        raise AssertionError("Field() 没有 default")
    return ast.literal_eval(node)


def _config_field_defaults(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    klass = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Config"
    )
    out: dict[str, Any] = {}
    for stmt in klass.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.value is None:
                continue
            try:
                out[stmt.target.id] = _literal(stmt.value)
            except (ValueError, TypeError, SyntaxError):
                continue  # 非字面量缺省（Factory/计算式）不参与对账。
    return out


def _knob_fallbacks(source: str) -> dict[str, Any]:
    """``PokeDispatcher._knobs`` 里 ``getattr(config, "<键>", <兜底>)`` 的读点表。"""
    tree = ast.parse(source)
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_knobs"
    )
    out: dict[str, Any] = {}
    for call in ast.walk(fn):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "getattr"
            and len(call.args) >= 3
        ):
            continue
        key = call.args[1]
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            continue  # 动态键名不在对账范围内（也不许出现在 _knobs 里）。
        out[str(key.value)] = _literal(call.args[2])
    return out


def _knob_violations(poke_source: str, config_source: str) -> tuple[str, ...]:
    """逐枚比对；返回违规说明（空=两处置信一致）。"""
    defaults = _config_field_defaults(config_source)
    problems: list[str] = []
    for key, fallback in _knob_fallbacks(poke_source).items():
        if key not in defaults:
            problems.append(f"{key}: 分发器读了 Config 上不存在的字段（幽灵读点）")
            continue
        expected = defaults[key]
        # 同形要求：True 与 1 数值相等但语义不同（bool 字段被读成 int 就是漂移）。
        if isinstance(expected, bool) is not isinstance(fallback, bool):
            problems.append(
                f"{key}: 兜底 {fallback!r} 与真身缺省 {expected!r} 布尔形态不一致"
            )
        elif type(expected) is not type(fallback):
            problems.append(
                f"{key}: 兜底 {fallback!r} 与真身缺省 {expected!r} 类型不同形"
            )
        elif expected != fallback:
            problems.append(f"{key}: 兜底 {fallback!r} ≠ config.py 缺省 {expected!r}")
    return tuple(problems)


def _poke_config(**overrides: Any) -> Any:
    """真 ``Config()`` + 覆写：不在测试里重建第二份缺省表。"""
    cfg = Config()
    return cfg.model_copy(update=dict(overrides))


def _poke_event(*, group: bool) -> PokeEvent:
    return PokeEvent(
        target_id="bot-1", user_id="u-42", group_id="g-200" if group else "", sub_type="poke"
    )


def _decide(*, mode: str, group: bool, poke_back_available: bool = True, **over: Any):
    cfg = _poke_config(bot_poke_reply_mode=mode, **over)
    dispatcher = PokeDispatcher(clock=lambda: 1_000.0)
    return dispatcher.build_poke_reaction(
        _poke_event(group=group),
        bot_id="bot-1",
        config=cfg,
        poke_back_available=poke_back_available,
    )


# -------------------------------------------------- ① 读点兜底值 == config 真身


def test_dispatcher_knob_fallbacks_match_config_defaults() -> None:
    """十枚读点的兜底值与 ``config.py`` 逐枚等值（零手抄数字，两处都 AST 现读）。"""
    violations = _knob_violations(
        POKE_SRC.read_text(encoding="utf-8-sig"),
        CONFIG_SRC.read_text(encoding="utf-8-sig"),
    )
    assert not violations, "分发器兜底值与真身缺省不一致：" + "；".join(violations)


def test_knob_fallback_lock_is_not_an_empty_scan() -> None:
    """自证①：读点表非空且覆盖全部十枚 poke 键（否则上一条在空跑）。"""
    knobs = _knob_fallbacks(POKE_SRC.read_text(encoding="utf-8-sig"))
    assert len(knobs) >= 10, f"_knobs 现算只数到 {len(knobs)} 枚字面读点 ⇒ 锁在空跑"
    assert all(key.startswith("bot_poke_") for key in knobs)
    for key in ("bot_poke_enabled", "bot_poke_poke_back", "bot_poke_extra_arms_enabled"):
        assert key in knobs, f"{key} 没被读点表认出＝锁看不见它"


def test_knob_fallback_lock_has_teeth_on_a_poisoned_copy(tmp_path: Path) -> None:
    """自证②：往内存副本注一枚「兜底改 False」的毒，锁必须点名那一枚。

    注毒打在 ``tmp_path`` 的副本上，生产文件零接触（磁盘 sha 不变）。
    """
    src = POKE_SRC.read_text(encoding="utf-8-sig")
    assert '"poke_back": bool(getattr(config, "bot_poke_poke_back", True))' in src
    poisoned = src.replace(
        '"poke_back": bool(getattr(config, "bot_poke_poke_back", True))',
        '"poke_back": bool(getattr(config, "bot_poke_poke_back", False))',
        1,
    )
    assert poisoned != src
    problems = _knob_violations(
        poisoned, CONFIG_SRC.read_text(encoding="utf-8-sig")
    )
    assert len(problems) == 1 and "bot_poke_poke_back" in problems[0], problems
    # 反向：还原形态零违规（证明只杀这一枚毒，不是常量红）。
    assert _knob_violations(src, CONFIG_SRC.read_text(encoding="utf-8-sig")) == ()


# -------------------------------------------------- ② 五腿 × 两场景可达矩阵


@pytest.mark.parametrize("mode", REQUIRED_ARMS + ("fixed",))
@pytest.mark.parametrize("group", [True, False], ids=["group", "private"])
def test_every_required_arm_is_selectable_in_both_scenarios(
    mode: str, group: bool
) -> None:
    """显式点名任一腿，群/私两个场景都真被选中（决策层不按场景悄悄丢腿）。"""
    reaction = _decide(mode=mode, group=group)
    assert reaction is not None and reaction.active, f"{mode} 臂在分发层被判否"
    assert reaction.mode == mode
    assert f"poke_mode:{mode}" in reaction.audit_tags
    assert reaction.group is group
    if mode == "poke":
        assert reaction.poke_back is True  # 恰一臂：只有这一臂带反戳意图
    else:
        assert reaction.poke_back is False, f"{mode} 臂叠上了反戳 ⇒ 一次两臂"


@pytest.mark.parametrize("group", [True, False], ids=["group", "private"])
def test_poke_arm_never_silently_empty_hands(group: bool) -> None:
    """反戳不可用时「只回戳」当场改判固定话术——两个场景都不许静默空回。"""
    reaction = _decide(mode="poke", group=group, poke_back_available=False)
    assert reaction is not None
    assert reaction.mode == "fixed"
    assert reaction.reply
    assert "poke_arm_fallback_no_poke_back" in reaction.audit_tags


@pytest.mark.parametrize("group", [True, False], ids=["group", "private"])
def test_sticker_reaction_leg_is_structurally_absent_in_both_scenarios(
    group: bool,
) -> None:
    """被戳贴表情：两场景都选不到（排除方式是「不在池里且不可点名」，不是抛异常）。

    私聊那条硬约束的真身在 ``domains/meme/reactions/engine.py::_is_group_session``
    （QQ 侧无私聊表情回应通道，协议端对非群消息直接抛 ``not supported on private
    messages``）——本锁保证 poke 侧连"跑到那一步"都不会发生。
    """
    cell = poke_reaction_cell("sticker_reaction")
    assert cell is not None
    assert cell.mix_pools == () and not cell.explicit_nameable
    assert not cell.wired_in_poke_path and cell.not_wired_reason.strip()
    assert "private" in cell.not_wired_reason  # 理由里点名了私聊硬约束
    # 拿它当臂名去点名：既不会被认下，也进不了任何池 ⇒ 判否后按 mix 轮换（不是崩）。
    assert not poke_mode_is_recognized("sticker_reaction")
    for pool in ("legacy", "extended"):
        reaction = _decide(
            mode=POKE_MIX_KEYWORD,
            group=group,
            bot_poke_extra_arms_enabled=(pool == "extended"),
        )
        assert reaction is not None
        assert reaction.mode != "sticker_reaction"


def test_sticker_arm_is_not_a_nameable_mode_anywhere() -> None:
    """不可点名集合里必须有它（否则「未接线却被列为可点名臂」= 表说谎）。"""
    nameable = {
        resolve_poke_reply_mode(configured=arm, group="g", sender="u", bucket=0)
        for arm in REQUIRED_ARMS + ("fixed",)
    }
    assert "sticker_reaction" not in nameable


# --------------------------------- ③ 拼错的臂名：不改判，但必须在审计里留名


def test_unrecognized_reply_mode_is_tagged_but_does_not_change_the_arm() -> None:
    """``BOT_POKE_REPLY_MODE=語音`` 这类错名：今天实际按 mix 轮换 ⇒ 必须留名。"""
    wrong = "語音"
    reaction = _decide(mode=wrong, group=True)
    assert reaction is not None
    assert reaction.mode in {"fixed", "llm", "meme"}  # 未擅自改判成某一臂
    assert any(
        tag.startswith("poke_mode_unrecognized:") for tag in reaction.audit_tags
    ), reaction.audit_tags
    assert not poke_mode_is_recognized(wrong)


@pytest.mark.parametrize("mode", REQUIRED_ARMS + ("fixed", POKE_MIX_KEYWORD, ""))
def test_recognized_modes_never_carry_the_unrecognized_tag(mode: str) -> None:
    reaction = _decide(mode=mode, group=True)
    assert poke_mode_is_recognized(mode)
    assert reaction is not None
    assert not any(
        tag.startswith("poke_mode_unrecognized:") for tag in reaction.audit_tags
    )


def test_audit_label_washes_admin_text_to_a_tag_shape() -> None:
    """标签消毒：只留 ASCII 字母数字与 ``_-``、超长截断、全空给诚实占位。"""
    assert poke_mode_label_for_audit("Voice") == "voice"
    assert poke_mode_label_for_audit("rand pic!") == "randpic"
    assert poke_mode_label_for_audit("語音") == ""
    assert poke_mode_label_for_audit("a" * 200) == "a" * 32
    # 注入形态进标签也只是一串字母数字，成不了第二枚标签/换行。
    washed = poke_mode_label_for_audit('x"; drop=tok\nsk-abcdef123456')
    assert "\n" not in washed and ";" not in washed and ":" not in washed
    reaction = _decide(mode="語音", group=True)
    assert reaction is not None
    assert "poke_mode_unrecognized:unprintable" in reaction.audit_tags


# ------------------------------- 两条概率腿：只差开关、不是缺腿（真缺省现读）


def _one_flip_reachable(prefix: str, *, flip: str) -> bool:
    """群聊场景下只翻 ``{prefix}enabled`` 一枚键，五层门链是否真能放行。

    答案必须是「是」——否则那条腿缺的不只是开关，而是门链里还藏着别人（那才是
    本仓最难查的那种洞）。「私聊不放行」这一半不在这里验：那是装配层传进来的
    ``require_group=True``，已由 ``tests/test_poke_matrix_v4.py::
    test_root_proactive_pokes_pass_require_group`` 从根文件 AST 执法；在这里再
    传一次 ``require_group=True`` 断言私聊为否，只是把同一个参数抄两遍的空跑锁。

    安静时间窗必须显式关掉再测：真 ``Config()`` 的窗是 00:00–06:00（HK），
    不关它测到的是钟表而不是门（同一条腿在 arms_v3 里已有按时刻注入的专测）。
    """
    cfg = _poke_config(**{flip: True, "bot_quiet_hours_enabled": False})
    gate = ProactiveGate(clock=lambda: 5_000.0)
    for index in range(40):  # 确定性哈希 ⇒ 40 个消息键足以覆盖概率骰
        if proactive_action_allowed(
            cfg,
            prefix=prefix,
            gate=gate,
            session_key="group_g-200_u-42",
            message_key=f"{prefix}probe-{index}",
            group_id="g-200",
            user_id="u-42",
            salt=prefix,
            require_group=True,
        ):
            return True
    return False


def test_minimal_config_still_allows_the_poke_back_arm() -> None:
    """只给 ``reply_mode`` 的最小配置：其余读点全走兜底 ⇒ 兜底值就是行为真值。

    这枚是「``bot_poke_poke_back`` 兜底从 ``False`` 改回 ``True``」那一改的靶子：
    改之前本用例当场红（mode 被分发器判成 ``fixed``、审计里带
    ``poke_arm_fallback_no_poke_back``），也就是「配置面上回戳明晃晃开着，
    读点却把它当成关」——本波抓到的第一条真缺陷。
    """
    from types import SimpleNamespace

    reaction = PokeDispatcher(clock=lambda: 1_000.0).build_poke_reaction(
        _poke_event(group=True),
        bot_id="bot-1",
        config=SimpleNamespace(bot_poke_reply_mode="poke"),
    )
    assert reaction is not None
    assert reaction.mode == "poke", reaction.audit_tags
    assert reaction.poke_back is True
    assert "poke_arm_fallback_no_poke_back" not in reaction.audit_tags


def test_production_defaults_leave_the_two_probability_legs_closed() -> None:
    cfg = Config()
    assert cfg.bot_poke_extra_arms_enabled is False
    assert cfg.bot_poke_follow_enabled is False
    assert cfg.bot_poke_after_reply_enabled is False


def test_follow_poke_leg_is_one_flip_away() -> None:
    assert _one_flip_reachable("bot_poke_follow_", flip="bot_poke_follow_enabled"), (
        "跟戳缺的不止开关：门链里还藏着一道没人知道的闸"
    )


def test_poke_after_bot_spoke_leg_is_one_flip_away() -> None:
    assert _one_flip_reachable(
        "bot_poke_after_reply_", flip="bot_poke_after_reply_enabled"
    ), "回复后/主动发言后戳人缺的不止开关：门链里还藏着一道没人知道的闸"


# ------------------------ 根装配现算：voice 那条腿的文本腿今天填的是哪一路

def _modes_guarding_llm_text_fetch(source: str) -> set[str] | None:
    """根 handler 里给 ``llm_text`` 赋值的那些分支所判的臂名集合。

    返回 ``None`` = 该赋值不在任何按 mode 分支里（无条件取数 ⇒ 缺陷不存在）。
    收源串而不收路径：注毒/补丁形态可以在内存里喂进来，磁盘零接触。
    """
    tree = ast.parse(source)
    handler = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_handle_poke_notice"
        ),
        None,
    )
    assert handler is not None, "根文件里找不到 _handle_poke_notice ⇒ 锚点已失效"
    found_guarded = False
    found_fetch = False
    modes: set[str] = set()
    for node in ast.walk(handler):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "llm_text" for t in node.targets
        ):
            continue
        if not any(isinstance(c, ast.Await) for c in ast.walk(node)):
            continue  # 只认「await _poke_llm_reply(...)」那一处
        found_fetch = True
        parent_guard = None
        for outer in ast.walk(handler):
            if not isinstance(outer, ast.If):
                continue
            if any(sub is node for sub in outer.body):
                parent_guard = outer
                break
        if parent_guard is None:
            return None  # 无条件赋值 ⇒ 两臂都拿得到
        found_guarded = True
        for sub in ast.walk(parent_guard.test):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                modes.add(sub.value)
    # 「取数点整个不存在」不是「已修好」——那意味着有人把腿删了，或锚点漂了。
    assert found_fetch and found_guarded, "llm_text 取数点没被认出 ⇒ 锁在空跑"
    return modes


def test_voice_arm_text_leg_is_filled_by_the_llm_like_the_matrix_declares() -> None:
    """voice 臂的文本腿由 LLM 填（第 14 项「语音+自然语言文本」）。

    本用例原本是 ``xfail(strict=True)`` 的摘牌钩：盘上现值一度是 ``{'llm'}``，
    即根装配只在 ``mode=='llm'`` 那一支取 ``llm_text``（``poke.py`` 矩阵的 voice 行
    却声明 ``resource_key='llm_text'``）⇒ 语音臂今天只做到「语音+固定话术」。
    2026-09-26 分支条件改成一视同仁后 XPASS ⇒ 按该标记自带的指示摘牌，
    **没有放宽任何断言**（保留断言原样才能真正防回潮）。
    """
    cell = poke_reaction_cell("voice")
    assert cell is not None and cell.resource_key == "llm_text"
    modes = _modes_guarding_llm_text_fetch(
        ROOT_INIT.read_text(encoding="utf-8-sig")
    )
    assert modes is None or "voice" in modes, f"取 llm_text 的分支只认这些臂：{modes}"


def test_voice_leg_lock_recognises_the_two_possible_fixes() -> None:
    """自证：本锁认得两种修法，也认得「分支被整个删掉」这种假修。

    盘上现值是 ``{'llm', 'voice'}``（两臂同权）。上一条用例只断言「voice 在场」，
    所以本锁另补一发**回潮杀伤力**：把分支条件改回只认 ``llm`` 必须被量出来——
    否则「认得修法」只是句空话，探测器对回潮同样是瞎的。
    """
    source = ROOT_INIT.read_text(encoding="utf-8-sig")
    assert _modes_guarding_llm_text_fetch(source) == {"llm", "voice"}
    # 回潮（= 修法①被撤销）：分支条件退回只认 llm ⇒ 必须量出 {"llm"}。
    regressed = source.replace(
        'if reaction.mode in ("llm", "voice"):',
        'if reaction.mode == "llm":',
        1,
    )
    assert regressed != source, "锚点串没命中：根文件形态变了，本锁需随之更新"
    assert _modes_guarding_llm_text_fetch(regressed) == {"llm"}
    # 修法②：无条件先取一次 llm_text（赋值不在任何按 mode 的分支里）。
    # 用合成片段而不是在真文件上做文本手术——真文件那一段挪出来后残留的 ``elif``
    # 会直接不成法，ast.parse 抛的SyntaxError 证明不了判据认得这种修法。
    unconditional = (
        "async def _handle_poke_notice(bot, event):\n"
        "    llm_text = await _poke_llm_reply(cfg, is_group=g, attitude_hint=h)\n"
        "    return llm_text\n"
    )
    assert _modes_guarding_llm_text_fetch(unconditional) is None
    # 反向：把取数点整段删掉不是「修好了」，锚点必须自己炸。
    with pytest.raises(AssertionError, match="空跑"):
        _modes_guarding_llm_text_fetch(
            "async def _handle_poke_notice(bot, event):\n    return None\n"
        )


# ------------- 根装配现算②：语音臂的触发词前缀今天是一串配置dump（⇒ 永不出声）


def _voice_pair_trigger_arg_source() -> str:
    """AST 取根件 ``_poke_voice_pair`` 里 ``effective_trigger_words(...)`` 的首实参。"""
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_poke_voice_pair"
        ),
        None,
    )
    assert fn is not None, "根件里找不到 _poke_voice_pair ⇒ 锚点已失效"
    for call in ast.walk(fn):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "effective_trigger_words"
            and call.args
        ):
            return ast.unparse(call.args[0])
    raise AssertionError("没找到 effective_trigger_words 调用点 ⇒ 锁在空跑")


def test_trigger_words_helper_takes_a_word_list_not_a_config() -> None:
    """为什么「把 Config 整个交出去」是错的：pydantic 模型可迭代 ⇒ 拿到一堆键值对。

    这条**现在就绿**，因为它是判据的地基：``effective_trigger_words`` 收的是词表，
    喂 ``Config()`` 不会报错、只会静默产出 ``"('bot_runtime_data_dir', 'data')"``
    这种串，并且 ``extract_tts_text`` 对它的求值结果是**空正文**（= 整条语音腿不发）。
    将来若有人把这枚缺陷「修」成让 helper 自己去兼容 Config，本用例照红——
    兼容不是修法，调用点传对才是。
    """
    from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
        DEFAULT_TRIGGER_WORDS,
        effective_trigger_words,
        extract_tts_text,
    )

    misshaped: Any = Config()  # 以 Any 走「调用点传错形参」那一步：静态面会拦，
    # 而根装配**曾经**就是这么调的（2026-09-26 摘牌）—— 本用例要跑的是它拦不住
    # 之后发生的事，所以哪怕调用点已修对，这发缺陷演示仍必须留：它同时是
    # 「兼容不是修法，调用点传对才是」那条判据的地基。
    first = effective_trigger_words(misshaped)[0]
    assert first not in DEFAULT_TRIGGER_WORDS, "helper 已能兼容 Config ⇒ 判据需重估"
    assert first.startswith("(") and "'" in first, first
    # 空正文 = 语音能力走 missing_text 分支、audio 恒空 ⇒ 语音腿结构性发不出声。
    assert extract_tts_text(f"{first} 我收到你的轻轻一碰了。", None) == ""
    # 对照：词表传对时正文取得出来（证明上面那发不是取文器坏了）。
    assert extract_tts_text("说 我收到你的轻轻一碰了。", None) == "我收到你的轻轻一碰了。"


def test_voice_arm_trigger_prefix_comes_from_the_trigger_word_list() -> None:
    """语音臂的前缀必须来自触发词表，而不是整枚 Config。

    本用例原本是 ``xfail(strict=True)`` 的摘牌钩：``__init__.py`` 一度把
    ``merged_config`` 整枚交给 ``effective_trigger_words``（形参是词表）⇒ 首元素是
    ``('键名', 值)`` 的 repr 串 ⇒ ``extract_tts_text`` 恒得空正文 ⇒ 语音腿即使
    ``BOT_TTS_ENABLED=true`` 也永远拿不到 audio（本仓最典型那种「开关都开了、
    路还是走不到」）。2026-09-26 调用点传对后 XPASS ⇒ 摘牌，断言原样保留。
    """
    arg = _voice_pair_trigger_arg_source()
    assert "bot_tts_trigger_words" in arg, f"首实参是 {arg}＝把配置整枚交了出去"
