"""「第 9 项」三规格（用户 2026-09-27 04:3x 睡前定稿）的行为锁 + 装配活性锁。

覆盖三条硬规格各自「真会咬人」的那一半：

规格 1（3 秒等待窗口）——窗口值以 ``message_merge.MERGE_WINDOW_SECONDS``
为权威；``apply_merge_window_seconds`` 只换 quiet_seconds、其余护栏逐字节
保留（frozen dataclass ⇒ 必须是 ``dataclasses.replace`` 语义，本席位首稿
误用 pydantic ``model_copy`` 会在线上炸，这条锁就是它的教训固化）；
再验 3 秒确实抵达折句器的放行计算与「折进同一轮、只回一次」行为。

规格 2（表情静默）——``is_lone_emoji_or_sticker`` /
``should_silence_emoji_reaction`` 是判据不是白名单：正例反例矩阵 +
「bot 未回复不静默」「群聊点名不静默」「私聊豁免不放大」逐条锁。

规格 3（命令+自然语言双触发）——``command_natural_remainder`` 只认
「无参数命令头 + 自然语言尾巴」；纯命令、带参命令、参数样余文一律
None ⇒ 既有行为不变（「宁可维持旧行为，不多头回复」）。

装配活性锁走 ``ast`` 静态解析（不 import 根件——根近万行、import 面会
被并发席半写污染，同 test_coalescing_wiring_lock 的既有裁定）。
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    message_merge as mm,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.message_coalescing import (
    CoalescingSettings,
    MessageCoalescer,
)

# --------------------------------------------------------------------------
# 消息工厂（离线，无网络无真 bot）
# --------------------------------------------------------------------------


def _message(
    text: str,
    *,
    sender_id: str = "u1",
    session_id: str = "group_10_u1",
    session_type: SessionType = SessionType.GROUP,
    message_id: str | None = None,
    **kwargs: object,
) -> IncomingMessage:
    platform = str(kwargs.pop("platform", "qq"))
    return IncomingMessage(
        platform=platform,
        adapter="onebot_v11",
        bot_id="3958874605",
        session_id=session_id,
        session_type=session_type,
        sender_id=sender_id,
        plain_text=text,
        message_id=message_id or f"m-{abs(hash((text, sender_id))) % 10**8}",
        **kwargs,  # type: ignore[arg-type]
    )


def _seg(seg_type: str, **data: Any) -> dict[str, Any]:
    return {"type": seg_type, "data": data}


def _emoji_message(
    segments: list[dict[str, Any]],
    *,
    text: str = "",
    **kwargs: object,
) -> IncomingMessage:
    # 透传 dict[str,object] kwargs，同折句测试族口径（工厂本身带 ignore）。
    extra = dict(kwargs)
    return _message(text, raw_segments=segments, **extra)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# 规格 1：3 秒等待窗口
# --------------------------------------------------------------------------


def test_merge_window_constant_is_user_ruling() -> None:
    """用户 2026-09-27 裁定 3s——常数是本波唯一权威，勿改回 1.8。"""
    assert mm.MERGE_WINDOW_SECONDS == 3.0


def test_apply_merge_window_only_touches_quiet_seconds() -> None:
    """只换 quiet_seconds；enabled/封顶/条数字数护栏逐字节保留。

    这条同时锁住实现语义：CoalescingSettings 是 frozen dataclass，
    apply 必须产出**新对象**且原对象不动（首稿误用 model_copy 的固化）。
    """
    base = CoalescingSettings(
        enabled=True,
        quiet_seconds=1.8,
        max_hold_seconds=8.0,
        max_messages=6,
        max_chars=1500,
    )
    applied = mm.apply_merge_window_seconds(base)
    assert applied.quiet_seconds == mm.MERGE_WINDOW_SECONDS
    assert applied.enabled is base.enabled
    assert applied.max_hold_seconds == base.max_hold_seconds
    assert applied.max_messages == base.max_messages
    assert applied.max_chars == base.max_chars
    # 原对象不被就地修改（frozen dataclass ⇒ 就地改会直接 raise）。
    assert base.quiet_seconds == 1.8
    assert applied is not base


@pytest.mark.asyncio
async def test_three_second_window_reaches_coalescer_flush_math() -> None:
    """折句器的放行截止 = last_at + 3.0（封顶更晚时以 3 秒停口为准）。"""
    applied = mm.apply_merge_window_seconds(CoalescingSettings())
    now = [0.0]
    batcher = MessageCoalescer(applied, clock=lambda: now[0])
    message = _message("守岸人，", message_id="m-9-math-1")
    key = "group_10_u1:u1"

    owner = asyncio.create_task(batcher.offer(key, message))
    await asyncio.sleep(0)
    window = batcher._windows[key]
    assert window.last_at == 0.0
    assert batcher._flush_deadline(window) - window.last_at == pytest.approx(3.0)
    owner.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await owner
    assert batcher.pending_keys == ()  # 取消不留悬窗（不吞下一轮的保险）


@pytest.mark.asyncio
async def test_same_sender_fragments_fold_into_one_replyable_turn() -> None:
    """同人连发在窗口内到齐 ⇒ 折成一轮、只有开门者拿到回复权。

    真实 3 秒不进单测：用「3s quiet + 短 max_hold」让封顶提前收口——
    收口时机由护栏决定，本条锁的是「3s 生效设置下折句语义不变、
    一条消息都不吞」；护栏与 3s 各自单独锁。
    """
    applied = mm.apply_merge_window_seconds(
        CoalescingSettings(max_hold_seconds=0.15)
    )
    batcher = MessageCoalescer(applied)
    first, second = (
        _message("守岸人，", message_id="m-9-fold-1"),
        _message("今天的潮汐怎么样", message_id="m-9-fold-2"),
    )
    key = "group_10_u1:u1"

    owner = asyncio.create_task(batcher.offer(key, first))
    await asyncio.sleep(0.005)
    follower = await batcher.offer(key, second)
    assert follower.owned is False  # 折进别人那一轮：不再多回一句

    turn = await asyncio.wait_for(owner, timeout=2.0)
    assert turn.owned is True
    assert turn.folded_count == 2
    assert turn.message.plain_text == "守岸人，今天的潮汐怎么样"

    # 绝不吞消息：下一句必须自己拿到回复权。
    later = await batcher.offer(key, _message("还有吗", message_id="m-9-fold-3"))
    assert later.owned is True


def test_complete_sentence_under_applied_window_returns_immediately() -> None:
    """完整句子不为 3 秒窗多等一刻（零额外延迟的既有硬要求不破）。"""
    applied = mm.apply_merge_window_seconds(CoalescingSettings(quiet_seconds=30.0))
    batcher = MessageCoalescer(applied)
    message = _message("今天天气不错。", message_id="m-9-fast-1")
    turn = asyncio.run(batcher.offer("group_10_u1:u1", message))
    assert turn.owned is True and turn.folded_count == 1
    assert turn.message is message


# --------------------------------------------------------------------------
# 规格 2：裸表情/贴纸 → 静默（可判定规则，非白名单）
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("segments", "text"),
    [
        ([_seg("face", file="f1")], ""),
        ([_seg("face", file="f1"), _seg("text", text="[表情]")], "[表情]"),
        ([_seg("text", text="😄😄")], "😄😄"),
        ([_seg("sticker", id="1"), _seg("reply", id="9")], ""),
        ([_seg("mface", file="m1"), _seg("at", qq="12345")], ""),
        (
            [
                _seg("face", file="f1"),
                _seg("text", text="（用户发送了图片/表情包/视频，未附文字。）"),
            ],
            "（用户发送了图片/表情包/视频，未附文字。）",
        ),
    ],
)
def test_lone_emoji_positives(segments: list[dict[str, Any]], text: str) -> None:
    assert mm.is_lone_emoji_or_sticker(_emoji_message(segments, text=text)) is True


@pytest.mark.parametrize(
    ("segments", "text"),
    [
        # 图片/视频/语音段一律不算裸表情（护视觉理解与语音链路）。
        ([_seg("image", file="photo.jpg")], ""),
        ([_seg("face", file="f1"), _seg("image", file="photo.jpg")], ""),
        ([_seg("face", file="f1"), _seg("record", file="voice.amr")], ""),
        # 有真正文 ⇒ 不是「裸」。
        ([_seg("face", file="f1"), _seg("text", text="今天真开心")], "今天真开心"),
        ([_seg("text", text="哈哈")], "哈哈"),
        # 只有摄取占位、没有表情段 ⇒ fail-open（宁多回一句）。
        (
            [_seg("text", text="（用户发送了图片/表情包/视频，未附文字。）")],
            "（用户发送了图片/表情包/视频，未附文字。）",
        ),
        ([], ""),
    ],
)
def test_lone_emoji_negatives(segments: list[dict[str, Any]], text: str) -> None:
    assert mm.is_lone_emoji_or_sticker(_emoji_message(segments, text=text)) is False


def test_mail_surface_never_counts_as_lone_emoji() -> None:
    """邮件一封一线程：表情当新线程处理，静默会错接回信 ⇒ 一律不算。"""
    message = _emoji_message(
        [_seg("face", file="f1")],
        platform="mail",
        session_id="email:box1",
    )
    assert mm.is_lone_emoji_or_sticker(message) is False
    assert mm.should_silence_emoji_reaction(message, last_turn_role="assistant") is False


def test_silence_requires_bot_already_replied() -> None:
    """「bot 已回复过」是静默的前提：最近一轮 role 必须是 assistant。

    未回复（None/空/异常回退）或上一轮还是用户自己 ⇒ 表情可能是开场
    提问，绝不静默（用户口径「得看情况」的落地判据②）。
    """
    face = _emoji_message([_seg("face", file="f1")])
    assert mm.should_silence_emoji_reaction(face, last_turn_role="assistant") is True
    assert mm.should_silence_emoji_reaction(face, last_turn_role="user") is False
    assert mm.should_silence_emoji_reaction(face, last_turn_role=None) is False


def test_reply_to_bot_message_with_emoji_is_silenced() -> None:
    """回复 bot 那条再发裸表情（谢谢表情场景）⇒ 正是定稿点名的静默例。"""
    message = _emoji_message([_seg("face", file="f1"), _seg("reply", id="9")])
    assert mm.should_silence_emoji_reaction(message, last_turn_role="assistant") is True


def test_group_mention_exemptions() -> None:
    """群聊里 @/人格名/软点名过 bot 的表情是**在叫它**，不静默。"""
    face_seg = [_seg("face", file="f1")]
    for flag in ("mentions_bot", "name_mention_only", "soft_persona_mention"):
        message = _emoji_message(face_seg, **{flag: True})  # type: ignore[arg-type]
        assert message.session_type is SessionType.GROUP
        assert (
            mm.should_silence_emoji_reaction(message, last_turn_role="assistant")
            is False
        ), flag


def test_private_never_waived_by_always_true_mention_flag() -> None:
    """私聊 mentions_bot 恒真（摄取现算）——豁免不套私聊，否则私聊表情
    永不再理。这条锁住「豁免只裁群聊」的口径边界。"""
    message = _emoji_message(
        [_seg("face", file="f1")],
        mentions_bot=True,
        session_id="private_u1",
        session_type=SessionType.PRIVATE,
    )
    assert mm.should_silence_emoji_reaction(message, last_turn_role="assistant") is True


def test_non_emoji_message_is_not_silenced_even_after_reply() -> None:
    """照片+谢谢表情混排不算裸表情 ⇒ bot 已回复也照回（护多模态正文）。"""
    message = _emoji_message(
        [_seg("image", file="cat.jpg"), _seg("face", file="f1")]
    )
    assert mm.should_silence_emoji_reaction(message, last_turn_role="assistant") is False


# --------------------------------------------------------------------------
# 规格 3：命令 + 自然语言双触发（覆盖旧「命中命令不走人格」口径）
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command_text", "expected"),
    [
        # 用户定稿例与同型：无参数命令头 + 自然语言尾巴。
        ("status 顺便说两句", "顺便说两句"),
        ("queue 看看排到哪了", "看看排到哪了"),
        ("llm 状态怎么样", "状态怎么样"),
        ("resume 继续吧", "继续吧"),
        ("history clear 今天聊聊", "今天聊聊"),  # 最长头优先，不误拆 history
        ("config 都想说点什么", "都想说点什么"),
        # 纯命令 ⇒ None ⇒ 既有行为逐字节不变（纯命令不多回一句）。
        ("status", None),
        ("queue", None),
        ("history clear", None),
        ("", None),
        # 带真参数的命令头不在双触发集 ⇒ 尾随文本仍是命令参数。
        ("context list", None),
        ("setup llm 慢慢说", None),
        ("restart 随便聊聊", None),  # 头不在集内
        # 判据不过的余文一律 None：宁可维持旧行为，不多头回复。
        ("status /help", None),  # 命令形态起手
        ("status help", None),  # 参数样词
        ("status status", None),  # 参数样词
        ("status a", None),  # 太短
        ("status 123", None),  # 纯数字
        ("llm temperature=0.7", None),  # 赋值样式
        ("history clearx 随便聊聊", None),  # 头必须词边界（空格）分隔
    ],
)
def test_command_natural_remainder(command_text: str, expected: str | None) -> None:
    assert mm.command_natural_remainder(command_text) == expected


def test_dual_trigger_head_set_covers_only_argless_command_branches() -> None:
    """头集合只收「整条命令本就无参数、尾随文字今天坠进 help 兜底」的
    命令 ⇒ 双触发只在既有 dead-text 上增加行为，不劫持任何既有参数语义。"""
    assert "status" in mm.DUAL_TRIGGER_COMMAND_HEADS
    assert "history clear" in mm.DUAL_TRIGGER_COMMAND_HEADS
    for argful in ("context", "why", "receipt", "dialogue", "setup llm", "model"):
        assert argful not in mm.DUAL_TRIGGER_COMMAND_HEADS, argful


# --------------------------------------------------------------------------
# 装配活性锁（ast 静态解析根件；零 import 零执行，同 wiring lock 先例）
# --------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = _ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
ROOT_COALESCING = (
    _ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "message_coalescing.py"
)
_SOURCE = ROOT_INIT.read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)
_COALESCING_TREE = ast.parse(ROOT_COALESCING.read_text(encoding="utf-8"))


def _find_func_in(tree: ast.AST, name: str):
    """在任意一棵树里按名字取函数（折句接缝 2026-09-29 收进
    `message_coalescing.fold_inbound_turn`，活性锁必须跟着锚点走）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"找不到 {name}——活性锁的锚没了")


def _find_async_func(name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(_TREE):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"根装配段找不到 {name}——活性锁的锚没了")


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _calls(func: ast.AsyncFunctionDef) -> list[ast.Call]:
    return [node for node in ast.walk(func) if isinstance(node, ast.Call)]


def _first_call(func: ast.AsyncFunctionDef, name: str) -> ast.Call:
    hits = [call for call in _calls(func) if _call_name(call) == name]
    assert hits, f"{func.name} 里找不到对 {name} 的调用——装配落空（机制在、线上零生效）"
    return min(hits, key=lambda call: call.lineno)


def _first_log_with_tag(func: ast.AsyncFunctionDef, tag: str) -> ast.Call:
    """定位 _log_runtime_event(..., tag, ...)：事件名是常量实参不是调用名。"""
    hits = [
        call
        for call in _calls(func)
        if _call_name(call) == "_log_runtime_event"
        and any(
            isinstance(arg, ast.Constant) and arg.value == tag for arg in call.args
        )
    ]
    assert hits, f"{func.name} 里没有 {tag} 事件——静默/折句无痕吞消息？"
    return min(hits, key=lambda call: call.lineno)


def test_chat_handler_applies_three_second_window_after_coalescer() -> None:
    """规格 1 活性：`shared_coalescer` 之后、`offer` 之前，settings 被
    `apply_merge_window_seconds` 就地换窗——顺序错一步，要么 3s 不生效
    （先 offer 后换），要么被 `shared_coalescer` 的 settings 重置覆盖（先换后取）。

    锚点搬家（2026-09-29 需求 1「实现暂缓、接缝留干净」）：这三步从根
    `_handle_chat` 收进唯一入口 `message_coalescing.fold_inbound_turn`，
    所以**判据跟着搬进那一件**；同时把新形态的核心承诺也钉上——
    ① 根装配段只准调 `fold_inbound_turn` 一次（第二处＝第二通路，红线）；
    ② 根装配段不得再自己碰 `shared_coalescer`/`apply_merge_window_seconds`/`offer`
      （否则「只动一处即启用」的承诺就假了）。
    """
    seam = _find_func_in(_COALESCING_TREE, "fold_inbound_turn")
    shared = _first_call(seam, "shared_coalescer")
    applied = _first_call(seam, "apply_merge_window_seconds")
    assert applied.lineno > shared.lineno
    # 且应用在 offer(...) 之前。
    offers = [call for call in _calls(seam) if _call_name(call) == "offer"]
    assert offers, "fold_inbound_turn 不再调用 offer ⇒ 折句整体下线？活性锁报错"
    assert applied.lineno < min(call.lineno for call in offers)
    # 应用形如 `coalescer.settings = apply_merge_window_seconds(...)`：
    # 赋值目标必须是那枚折句器的 `.settings`（换错对象=3s 不生效）。
    assign_found = False
    for node in ast.walk(seam):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and _call_name(node.value) == "apply_merge_window_seconds"
            and any(
                isinstance(target, ast.Attribute)
                and target.attr == "settings"
                and isinstance(target.value, ast.Name)
                for target in node.targets
            )
        ):
            assign_found = True
    assert assign_found, "3s 应用没有落在折句器的 .settings 上"

    # ①② 根装配段这一侧的两条承诺。
    chat = _find_async_func("_handle_chat")
    entries = [call for call in _calls(chat) if _call_name(call) == "fold_inbound_turn"]
    assert len(entries) == 1, (
        f"_handle_chat 里 fold_inbound_turn 出现 {len(entries)} 次"
        "（要求恰 1 次）⇒ 折句有了第二处调用点＝第二通路"
    )
    for stray in ("shared_coalescer", "apply_merge_window_seconds", "offer"):
        assert not [c for c in _calls(chat) if _call_name(c) == stray], (
            f"_handle_chat 里还直接调用 {stray} ⇒ 接缝没收口，"
            "「将来启用只动三处」的承诺不成立"
        )


def test_chat_handler_silence_gate_is_wired_before_pipeline() -> None:
    """规格 2 活性：折句之后、进管道之前有 is_lone_emoji_or_sticker 门；
    命中静默必记 chat_emoji_reaction_silenced 事件并 return——
    「静默无痕吞消息」是本仓红线，事件名与 return 一起锁。"""
    chat = _find_async_func("_handle_chat")
    lone = _first_call(chat, "is_lone_emoji_or_sticker")
    gate_if = next(
        node
        for node in ast.walk(chat)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Call)
        and _call_name(node.test) == "is_lone_emoji_or_sticker"
    )
    body_src = ast.dump(gate_if)
    assert "should_silence_emoji_reaction" in body_src
    assert "chat_emoji_reaction_silenced" in body_src
    assert any(
        isinstance(node, ast.Return) and node.value is None
        for node in ast.walk(gate_if)
    ), "静默分支没有 return ⇒ 表情照进管道，静默规格落空"
    # 位置锁：在折句之后（被折进文字轮的贴纸随整轮回复，不单独判）、
    # 进**主聊天管道调用**之前。主调用以第二实参 chat_capability 认定
    # （复读 parrot 等提前支也走 handle_async("bot.chat")，但闭包能力
    # 不是 chat_capability——那些在折句之前就 return，与本门无先后义务）。
    pipeline_calls = [
        call
        for call in _calls(chat)
        if _call_name(call) == "handle_async"
        and any(
            kw.arg == "capability_id"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == "bot.chat"
            for kw in call.keywords
        )
        and len(call.args) >= 2
        and isinstance(call.args[1], ast.Name)
        and call.args[1].id == "chat_capability"
    ]
    assert pipeline_calls, "_handle_chat 不再经 pipeline.handle_async 进管道？"
    first_pipeline = min(call.lineno for call in pipeline_calls)
    folded = _first_log_with_tag(chat, "chat_turn_folded")
    assert lone.lineno > folded.lineno
    assert gate_if.lineno < first_pipeline


def test_status_handler_dual_trigger_is_wired() -> None:
    """规格 3 活性：_handle_status 尾部按 command_natural_remainder 判
    双触发，人格回复走 bot.chat 进**同一** pipeline（不另起通路），
    并留 command_dual_trigger_persona 事件痕。"""
    status = _find_async_func("_handle_status")
    remainder = _first_call(status, "command_natural_remainder")
    pipeline_calls = [
        call
        for call in _calls(status)
        if _call_name(call) == "handle_async"
        and any(
            kw.arg == "capability_id"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == "bot.chat"
            for kw in call.keywords
        )
    ]
    assert pipeline_calls, "双触发的人格回复没有走 bot.chat 主链"
    assert remainder.lineno < min(call.lineno for call in pipeline_calls)
    dumped = ast.dump(status)
    assert "command_dual_trigger_persona" in dumped
    # 尾巴进管道前必须把派生消息的 command_text 清空（否则二次命中命令链）。
    copies = [
        call
        for call in _calls(status)
        if _call_name(call) == "model_copy"
        and any(
            kw.arg == "update"
            and isinstance(kw.value, ast.Dict)
            and any(
                isinstance(key, ast.Constant) and key.value == "command_text"
                for key in kw.value.keys
            )
            for kw in call.keywords
        )
    ]
    assert copies, "派生人格消息没有 model_copy 清 command_text"


def test_merge_module_free_of_pydantic_copy_on_dataclass() -> None:
    """message_merge 对 frozen dataclass 的 CoalescingSettings 不得使用
    model_copy（首稿实炸固化）；必须走 dataclasses.replace。
    锁的是**调用节点**而非文本——注释里讲这个坑本身不算犯。"""
    source = (
        _ROOT
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "chat_reply"
        / "runtime"
        / "message_merge.py"
    ).read_text(encoding="utf-8")
    module = ast.parse(source)
    model_copy_calls = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "model_copy"
    ]
    assert not model_copy_calls, "对 frozen dataclass 用 model_copy 会 AttributeError"
    replace_calls = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and _call_name(node) == "replace"
    ]
    assert any(
        call.args
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "settings"
        for call in replace_calls
    ), "apply_merge_window_seconds 没走 dataclasses.replace"


def test_message_merge_rule_functions_do_not_import_nonebot() -> None:
    """判据件零运行期框架依赖：不 import nonebot/pipeline，纯函数可单测
    （「有入参、有判据、可单测」是用户对规格 2 的原话要求）。"""
    module = ast.parse(
        (
            _ROOT
            / "plugins"
            / "bot_unified_runtime"
            / "domains"
            / "chat_reply"
            / "runtime"
            / "message_merge.py"
        ).read_text(encoding="utf-8")
    )
    imported: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not [
        name for name in imported if name.startswith(("nonebot", "plugins."))
    ], imported
