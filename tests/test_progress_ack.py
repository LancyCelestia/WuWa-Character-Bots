"""慢回复先回执（ack-first）：文案池、名单门、每会话冷却、投递请求形状。

设计口径（2026-09-23 用户裁定）：
- 只有真的超过阈值仍未出结果才发；15 秒内出结果不发。
- 真回复回来后回执不撤回也不补句（QQ 也收不回），所以回执必须自身可读。
- 群聊默认不开，白名单群才开；黑名单永远赢（沿用 bot_content_route_* 四名单语义）。
- 文案只用守护人白名单意象，禁"我在这等你/接住你"等直白抒情与客服腔。

需求项 6 收尾（2026-09-26，S-T-ACK-1）追加的三条行为锁口径：
- 「超过阈值才发」⇒ 阈值内出结果**一句都不发**；超阈值**恰发一句**（不双发）。
- 「发出后真回复回来什么都不做」⇒ 回执发出后，真回复不论成功还是失败到达，
  都不撤回、不道歉、不补第二句（总投递数恒 ≤1 句回执）。
- 「群聊默认不开 + 黑名单永远赢」⇒ 未入白名单的群、黑白同在册的群、以及一切
  未知/非私聊会话类型都不得发出回执（fail-closed）；黑名单与白名单同在册时黑名单赢。
  三条锁各测**开闸 / 关闸两态**（出站闸缺省关，只测关态=测「这个功能不存在」）。
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.progress_ack import (
    ACK_DEDUPE_NAMESPACE,
    ACK_DEFAULT_TEXT,
    ACK_POOL,
    ACK_TEXT_BANNED,
    ProgressAckSettings,
    ProgressAckThrottle,
    ack_key_segment,
    build_progress_ack_request,
    normalize_session_type,
    pick_progress_ack_text,
    progress_ack_allowed,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue

GROUP_ON = ProgressAckSettings(
    enabled=True,
    delay_seconds=15.0,
    cooldown_seconds=60.0,
    group_whitelist=frozenset({"662948429", "631785829"}),
    group_blacklist=frozenset(),
    private_whitelist=frozenset(),
    private_blacklist=frozenset(),
)


def _message(
    *,
    group_id: str = "",
    sender_id: str = "3865067623",
    session_id: str | None = None,
    message_id: str = "msg_1",
    session_type: SessionType | None = None,
) -> SimpleNamespace:
    resolved = session_id
    if resolved is None:
        resolved = f"group_1_x:{group_id}" if group_id else f"private_{sender_id}"
    if session_type is None:
        # 真契约里 session_type 是必填（contracts/runtime.py:127），夹具漏填会让
        # "判据 fail-closed 到群侧"这类改动被假红掩盖——按 group_id 补齐成生产形态。
        session_type = SessionType.GROUP if group_id else SessionType.PRIVATE
    return SimpleNamespace(
        request_id="req_test1",
        session_id=resolved,
        session_type=session_type,
        group_id=group_id,
        sender_id=sender_id,
        message_id=message_id,
        adapter="onebot.v11",
        bot_id="3958874605",
        debug_id="dbg_test1",
    )


# ---------------------------------------------------------------- 文案池


def test_pool_has_twenty_five_short_persona_lines() -> None:
    assert len(ACK_POOL) == 25
    assert len(set(ACK_POOL)) == 25, "池内不得重复，否则轮换等于没轮换"
    for text in ACK_POOL:
        assert 12 <= len(text) <= 40, f"句长越界：{text}"


@pytest.mark.parametrize("text", ACK_POOL)
def test_pool_lines_avoid_banned_ai_register(text: str) -> None:
    for banned in ACK_TEXT_BANNED:
        assert banned not in text, f"命中禁用口径 {banned!r}：{text}"


def test_rotation_does_not_repeat_adjacent_lines() -> None:
    picks = [pick_progress_ack_text("private_1") for _ in range(6)]
    assert len(set(picks)) > 1, "轮换必须给出不同句"
    assert all(a != b for a, b in pairwise(picks))


# ---------------------------------------------------------------- 名单门


def test_group_needs_whitelist_entry_and_blacklist_always_wins() -> None:
    assert progress_ack_allowed(GROUP_ON, session_type="group", group_id="662948429")
    assert not progress_ack_allowed(GROUP_ON, session_type="group", group_id="999999999")

    both = ProgressAckSettings(
        **{
            **GROUP_ON.__dict__,
            "group_blacklist": frozenset({"662948429"}),
        }
    )
    # 同一个群同时出现在黑白名单：黑名单赢。
    assert not progress_ack_allowed(both, session_type="group", group_id="662948429")


def test_empty_group_whitelist_means_no_group_gets_ack() -> None:
    off = ProgressAckSettings(
        **{**GROUP_ON.__dict__, "group_whitelist": frozenset()}
    )
    assert not progress_ack_allowed(off, session_type="group", group_id="662948429")


def test_empty_private_whitelist_means_private_still_allowed() -> None:
    # 与 bot_content_route 私聊面同口径：私聊白名单为空＝放开（刻意不对称）。
    assert progress_ack_allowed(GROUP_ON, session_type="private", sender_id="3865067623")

    blocked = ProgressAckSettings(
        **{**GROUP_ON.__dict__, "private_blacklist": frozenset({"3865067623"})}
    )
    assert not progress_ack_allowed(
        blocked, session_type="private", sender_id="3865067623"
    )


def test_master_switch_shuts_everything() -> None:
    off = ProgressAckSettings(**{**GROUP_ON.__dict__, "enabled": False})
    assert not progress_ack_allowed(off, session_type="private", sender_id="x")
    assert not progress_ack_allowed(off, session_type="group", group_id="662948429")


# ---------------------------------------------------------------- 装配期读键


def test_from_config_maps_all_seven_keys() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.progress_ack import (
        ProgressAckSettings as Settings,
    )

    config = SimpleNamespace(
        bot_chat_progress_ack_enabled=True,
        bot_chat_progress_ack_delay_seconds=15,
        bot_chat_progress_ack_cooldown_seconds=90,
        bot_chat_progress_ack_group_whitelist=["662948429", "631785829"],
        bot_chat_progress_ack_group_blacklist=[],
        bot_chat_progress_ack_private_whitelist=[],
        bot_chat_progress_ack_private_blacklist=["999"],
    )

    settings = Settings.from_config(config)

    assert settings.enabled is True
    assert settings.delay_seconds == 15.0
    assert settings.cooldown_seconds == 90.0
    assert settings.group_whitelist == frozenset({"662948429", "631785829"})
    assert settings.private_blacklist == frozenset({"999"})


def test_from_config_failsclosed_when_config_lacks_keys() -> None:
    # Config 上不存在该字段时（填错键名/未登记）必须落回关，而不是"读不到就发"。
    settings = ProgressAckSettings.from_config(SimpleNamespace())
    assert settings.enabled is False
    assert settings.delay_seconds == 15.0
    assert not progress_ack_allowed(settings, session_type="private", sender_id="x")


def test_from_config_accepts_comma_string_id_lists() -> None:
    config = SimpleNamespace(
        bot_chat_progress_ack_enabled=True,
        bot_chat_progress_ack_group_whitelist="662948429, 631785829",
    )
    settings = ProgressAckSettings.from_config(config)
    assert settings.group_whitelist == frozenset({"662948429", "631785829"})


# ---------------------------------------------------------------- 冷却


def test_throttle_emits_once_per_window_then_again_after() -> None:
    throttle = ProgressAckThrottle(cooldown_seconds=60.0)
    assert throttle.try_claim("private_1", now=1000.0) == 1000.0
    assert throttle.try_claim("private_1", now=1030.0) is None
    assert throttle.try_claim("private_1", now=1061.0) == 1061.0
    # 另一会话不受影响。
    assert throttle.try_claim("private_2", now=1030.0) == 1030.0


def test_concurrent_claims_in_one_window_get_one_slot() -> None:
    """冷却的**查与占之间不许有缝隙**（2026-09-23 评审席实锤的反例形态）。

    旧实现 `should_emit()` 后 `record()`：两条并发消息可以都查到"没在冷却"，
    再各发一句 ⇒ 同一次等待收到两句回执。注毒判据＝把 `try_claim` 拆回
    "先查（不占）后写"，本用例当场红。
    """
    throttle = ProgressAckThrottle(cooldown_seconds=60.0)
    stamps = [throttle.try_claim("private_1", now=1000.0) for _ in range(3)]
    assert [s for s in stamps if s is not None] == [1000.0], stamps


def test_failed_send_returns_the_slot_so_the_next_ask_can_try() -> None:
    """占坑后发送失败 ⇒ 退还；失败的回执不该惩罚用户下一次追问。"""
    throttle = ProgressAckThrottle(cooldown_seconds=60.0)
    claimed = throttle.try_claim("private_1", now=1000.0)
    assert claimed == 1000.0
    throttle.release("private_1", claimed)
    assert throttle.try_claim("private_1", now=1001.0) == 1001.0


def test_release_never_eroses_a_newer_claim() -> None:
    """退还只认自己那次：投递期间同会话若有更新的占坑，不许被旧戳抹掉。"""
    throttle = ProgressAckThrottle(cooldown_seconds=60.0)
    first = throttle.try_claim("private_1", now=1000.0)
    throttle.release("private_1", first or 0.0)  # 1000 已不是当前值前先占一次
    second = throttle.try_claim("private_1", now=1010.0)
    assert second == 1010.0
    throttle.release("private_1", 1000.0)  # 拿一个过期的戳来退
    assert throttle.try_claim("private_1", now=1020.0) is None, "别人的冷却被抹掉了"


def test_throttle_is_bounded() -> None:
    throttle = ProgressAckThrottle(cooldown_seconds=60.0, max_sessions=4)
    for index in range(20):
        throttle.try_claim(f"s{index}", now=1000.0 + index)
    assert len(throttle) <= 4


# ---------------------------------------------------------------- 投递形状


def test_build_request_targets_group_and_carries_namespace_key() -> None:
    request = build_progress_ack_request(_message(group_id="662948429"), "潮线画到一半就断了。")

    assert request.capability_id == "bot.chat"
    assert str(request.target_scope).endswith("GROUP")
    assert request.target_id == "662948429"
    assert request.max_messages == 1
    assert request.content.text_fallback == "潮线画到一半就断了。"
    # 键首段必须是自报命名空间：漏报会回落紧急域 emg 口径⇒开闸态整族静默丢消息。
    assert request.dedupe_key.startswith("ack:")
    assert request.audit_tags == ["chat_progress_ack:v1"]


def test_build_request_targets_sender_when_private() -> None:
    request = build_progress_ack_request(_message(), "这句话我掂了一下。")

    assert str(request.target_scope).endswith("PRIVATE")
    assert request.target_id == "3865067623"


# -------------------------------------------------- 管线级：慢才发、快不发


class _NullAudit:
    def append(self, record: object) -> None:
        return


def _incoming(*, group_id: str = "", sender_id: str = "u1") -> IncomingMessage:
    if group_id:
        return IncomingMessage(
            platform="qq",
            adapter="onebot",
            bot_id="10000",
            session_id=f"group_{group_id}_{sender_id}",
            session_type=SessionType.GROUP,
            sender_id=sender_id,
            group_id=group_id,
            plain_text="你好",
            message_id="m-1",
        )
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=f"private:{sender_id}",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text="你好",
        message_id="m-1",
    )


def _result(message: IncomingMessage) -> CapabilityResult:
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.chat",
        kind="ok",
        title="",
        summary="",
        body="海潮回来了。",
    )


# ---------------------------------------------------------------------------
# 管线级夹具件：确定性的「慢 / 快」回复（需求项 6 收尾，2026-09-26 S-T-ACK-1）
#
# 为什么不许拿墙钟对赛跑：能力 `asyncio.sleep(0.15)` 与阈值 0.02 秒虽然同挂在一枚
# loop 钟上、正常调度不可能翻转，但本仓实测过 140–395 秒的事件循环停顿（台账 #50
# 根因②），任何"余量"在停顿面前都是零——偶发红还极难复现。现在顺序挂在**事件**上：
# - 慢回复：等 `release`，替身投递口在**送出的那一刻** set() ⇒ 回执结构上不可能输给
#   真回复；若这一轮本就不该发（名单外/关闸/闸拦下），由 `_ACK_FUSE_SECONDS` 引信
#   兜底放行（同钟、为阈值的 25 倍，只有整体停顿越出 25 倍才可能咬到用例）。
# - 快回复：纯让出即刻返回，同时把阈值放到 `_ACK_FUSE_SECONDS`（≥ 引信）⇒ 真回复
#   先到期，结构上不可能触发回执。
# ---------------------------------------------------------------------------

_ACK_THRESHOLD_SECONDS = 0.02
# 引信：负例（慢但这一轮不发）唯一的时间上界；正例里它只是防挂死的保险。
_ACK_FUSE_SECONDS = 0.5

_GATE_STATES: tuple[str, ...] = ("closed", "open_allow", "open_block")


def _fast_capability(
    message: IncomingMessage,
) -> Callable[[IncomingMessage, object], Awaitable[CapabilityResult]]:
    async def capability(cap_msg: IncomingMessage, decision: object) -> CapabilityResult:
        for _ in range(3):  # 真让出三次事件循环，再立刻交卷
            await asyncio.sleep(0)
        return _result(cap_msg)

    return capability


def _slow_capability(
    release: asyncio.Event,
    *,
    fail: bool = False,
    fuse_seconds: float = _ACK_FUSE_SECONDS,
) -> Callable[[IncomingMessage, object], Awaitable[CapabilityResult]]:
    """慢回复：只许在回执已落投递口之后放行（顺序挂在事件上，不赌墙钟）。

    ``fail=True`` 造「回执已发出、真回复以异常到达」那一格——口径②的失败面。
    """

    async def capability(cap_msg: IncomingMessage, decision: object) -> CapabilityResult:
        try:
            await asyncio.wait_for(release.wait(), timeout=fuse_seconds)
        except TimeoutError:
            pass  # 引信：这一轮没人 set（名单外/闸拦下），回复照样到，只是晚
        if fail:
            raise RuntimeError("上游在第 3 跳断了（真回复失败到达）")
        return _result(cap_msg)

    return capability


def _gate_submitter(
    state: str,
    delivered: list,
    release: asyncio.Event,
) -> Callable[[object], None]:
    """出站闸两态的替身（复刻根 `_submit_progress_ack` 与闸交互的形状）。

    - ``closed``：今日生产缺省——闸整体放行，入列 + 就地送成功。
    - ``open_allow``：开闸放行。先过**中央谓词** ``active_push_key_shape_ok``
      （真身，不复制第二套正则）；键形非法在生产是开闸态 `skip`＝静默丢，
      这里让这种丢**可见**：不计入送达，外层"该发一句"的断言当场红
      （紧急域 `nmc:A1` 那枚 Critical 的教训：本地全绿 ≠ 线上发得出）。
    - ``open_block``：闸拦下/判顺延 ⇒ 交回队列、本轮不就地投递（0 送达）。
    """
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        active_push_key_shape_ok,
    )

    def _submit(request: SendRequest) -> None:
        if state == "open_block":
            return
        if state == "open_allow":
            assert active_push_key_shape_ok(
                request.dedupe_key or "", namespace=ACK_DEDUPE_NAMESPACE
            ), f"回执幂等键过不了中央闸，开闸态会被静默丢：{request.dedupe_key!r}"
        delivered.append(request)
        release.set()  # 回执已送出 → 真回复此刻才许交卷

    return _submit


def _delivered_reply_text(pipeline: RuntimePipeline) -> str:
    """真回复投进发送队列的全文（回执替身不过这条通道，串里只有正文）。

    `InMemorySendQueue.sent_requests` 收的是管线自己提交的**渲染正文**；替身投递口
    只把回执记进它自己的 delivered 表。于是「真回复到底送没送出」在这里可机检——
    旧写法 `assert receipt is not None` 测不到这一点（回执被掐死时 receipt 照样在场，
    只是终态不同）。
    """
    queue = pipeline.send_queue
    requests: list[SendRequest] = getattr(queue, "sent_requests", [])
    return "".join(
        str(request.content.text_fallback or "")
        for request in requests
        if request.capability_id == "bot.chat"
    )


def _pipeline(
    *,
    delay: float,
    submits: list,
    raise_on_submit: bool = False,
    adaptive_enabled: bool = False,
    release: asyncio.Event | None = None,
):
    """本文件管线用例的统一构造。

    ``adaptive_enabled`` 缺省**关**（DEFECT-5，本席现算）：这里测的是「固定阈值」
    旧口径（与 `tests/test_progress_ack_thresholds.py` 的双态断言同口径）。设置
    字段缺省是 True，而 `effective_ack_delay_seconds()` 在 EMA>0 时把阈值抬到
    `max(delay_seconds, delay_floor_seconds)`（下限 30 秒，2026-09-26 用户裁定 D2 由
    15 抬来）——若夹具日后给管线
    注了探针，0.02 秒测试阈值会被静默抬成 15 秒，全部「慢该发 / 快不该发」格子
    一起翻。写死 False 让口径显式在场。
    """
    settings = ProgressAckSettings(
        enabled=True,
        delay_seconds=delay,
        cooldown_seconds=60.0,
        adaptive_enabled=adaptive_enabled,
        group_whitelist=frozenset({"662948429"}),
        private_whitelist=frozenset(),
    )

    def _submit(request: object) -> None:
        if raise_on_submit:
            raise RuntimeError("queue down")
        submits.append(request)
        if release is not None:
            release.set()

    return RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAudit()),
        audit_logger=_NullAudit(),
        progress_ack_settings=settings,
        progress_ack_submit=_submit,
    )


@pytest.mark.asyncio
async def test_slow_reply_emits_one_ack_and_real_reply_survives() -> None:
    """活性判据②：超阈值 → 恰一条，且真回复照到（`asyncio.shield` 摘掉必红）。"""
    message = _incoming()
    submitted: list = []
    release = asyncio.Event()
    pipeline = _pipeline(
        delay=_ACK_THRESHOLD_SECONDS, submits=submitted, release=release
    )

    receipt = await pipeline.handle_async(
        message, _slow_capability(release), "bot.chat"
    )

    assert len(submitted) == 1, "慢回复必须发且只发一句回执"
    assert receipt is not None
    assert str(receipt.state).endswith("SENT"), receipt
    assert _delivered_reply_text(pipeline) == "海潮回来了。", (
        "真回复被超时掐死了（`asyncio.shield` 不在场时这一发必红）"
    )


@pytest.mark.asyncio
async def test_fast_reply_emits_no_ack() -> None:
    """活性判据①：阈值内出结果 → 一句都不发、事后也不补句。"""
    message = _incoming()
    submitted: list = []
    pipeline = _pipeline(delay=_ACK_FUSE_SECONDS, submits=submitted)

    receipt = await pipeline.handle_async(
        message, _fast_capability(message), "bot.chat"
    )

    assert submitted == [], "阈值内出结果不得多发一句"
    assert str(receipt.state).endswith("SENT"), "快轮次真回复要照到"
    assert _delivered_reply_text(pipeline) == "海潮回来了。"


@pytest.mark.asyncio
async def test_group_outside_whitelist_emits_no_ack() -> None:
    message = _incoming(group_id="999999999")
    submitted: list = []
    pipeline = _pipeline(delay=_ACK_THRESHOLD_SECONDS, submits=submitted)

    await pipeline.handle_async(
        message, _slow_capability(asyncio.Event()), "bot.chat"
    )

    assert submitted == []


@pytest.mark.asyncio
async def test_submit_failure_does_not_break_real_reply_or_waste_cooldown() -> None:
    message = _incoming(sender_id="u9")
    submitted: list = []
    pipeline = _pipeline(
        delay=_ACK_THRESHOLD_SECONDS, submits=submitted, raise_on_submit=True
    )

    receipt = await pipeline.handle_async(
        message, _slow_capability(asyncio.Event()), "bot.chat"
    )

    assert submitted == []
    assert receipt is not None, "回执投递口炸了也不能影响真实回复送达"
    assert str(receipt.state).endswith("SENT"), receipt
    assert _delivered_reply_text(pipeline) == "海潮回来了。"
    # 没发成功就该退还冷却坑，否则后续追问永远收不到回执。
    assert pipeline._progress_ack_throttle.try_claim(message.session_id) is not None


@pytest.mark.asyncio
async def test_cooldown_suppresses_second_ack() -> None:
    message = _incoming(sender_id="u5")
    submitted: list = []
    # 投递口按「已送达条数」放行对应的回复：第一轮有回执→第一轮回复即刻交卷；
    # 第二轮被冷却挡下→没有 set 的人→由引信兜底（这一轮耗时 ≤ _ACK_FUSE_SECONDS）。
    releases = [asyncio.Event(), asyncio.Event()]

    def _submit(request: object) -> None:
        submitted.append(request)
        releases[min(len(submitted) - 1, 1)].set()

    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAudit()),
        audit_logger=_NullAudit(),
        progress_ack_settings=ProgressAckSettings(
            enabled=True,
            delay_seconds=_ACK_THRESHOLD_SECONDS,
            cooldown_seconds=60.0,
            adaptive_enabled=False,
            group_whitelist=frozenset({"662948429"}),
            private_whitelist=frozenset(),
        ),
        progress_ack_submit=_submit,
    )

    turn = -1

    async def slow(cap_msg: IncomingMessage, decision: object) -> CapabilityResult:
        nonlocal turn
        turn += 1
        ev = releases[min(turn, 1)]
        try:
            await asyncio.wait_for(ev.wait(), timeout=_ACK_FUSE_SECONDS)
        except TimeoutError:
            pass
        return _result(cap_msg)

    await pipeline.handle_async(message, slow, "bot.chat")
    await pipeline.handle_async(_incoming(sender_id="u5"), slow, "bot.chat")

    assert len(submitted) == 1


def test_pipeline_defaults_to_no_ack_when_not_injected() -> None:
    # 未注入（现网键关/根装配未接）必须零行为变更：不建 throttle 也不发。
    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAudit()),
        audit_logger=_NullAudit(),
    )
    assert pipeline.progress_ack_settings is None
    assert pipeline._progress_ack_candidate(_incoming(), "bot.chat") is False


# ---------------------------------------------------------------------------
# 幂等键段：开闸态脏键 = 整条静默丢，关闸态却照发 —— 所以必须在构造侧就洗合法。
# 判据一律走闸侧中央谓词（同一实现），测试里不自写第二套正则。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        "group_1108838060_3865067623",  # OneBot 群键（权威下划线形）
        "3865067623",  # OneBot 私聊键（纯号）
        "private_123456789",  # TG 私聊
        "friend_oX.9-3_A",  # 官方适配器 openid（含 . 与 -）
        "group:1108838060",  # 历史冒号形：':' 是段分隔符，必洗
        "",  # 缺字段
        "中文群",  # 非 ASCII
        "x" * 400,  # 超长
    ],
)
def test_ack_dedupe_key_passes_central_gate_shape_in_every_input(
    raw: str,
) -> None:
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        active_push_key_shape_ok,
    )

    request = build_progress_ack_request(
        _message(session_id=raw, sender_id=raw or "s"), ACK_POOL[0]
    )
    assert active_push_key_shape_ok(
        request.dedupe_key or "", namespace=ACK_DEDUPE_NAMESPACE
    ), f"脏输入 {raw!r} 造出的键过不了闸＝开闸态静默丢回执：{request.dedupe_key!r}"


def test_ack_dedupe_key_is_unique_per_message_and_session() -> None:
    a = build_progress_ack_request(
        _message(session_id="group_1_a", message_id="1"), "文本一"
    )
    b = build_progress_ack_request(
        _message(session_id="group_1_a", message_id="2"), "文本一"
    )
    c = build_progress_ack_request(
        _message(session_id="group_1_b", message_id="1"), "文本一"
    )
    keys = {a.dedupe_key, b.dedupe_key, c.dedupe_key}
    assert len(keys) == 3, "换消息/换会话必须换键，否则回执会被幂等吞掉"


def test_degenerate_washed_segments_do_not_collide() -> None:
    assert ack_key_segment("中文群") != ack_key_segment("：：：")
    # `group:1` 的 `:` 是段分隔符、必被洗成 `_`；洗完仍含字母数字 ⇒ 走「真被洗过」分支，
    # 带原串 blake2b 摘要后缀（S184 §3-① 修的「洗段非单射」：`11 08838060` 曾与
    # `11_08838060` 塌成同段）。期望用标准库独立复算，不 import 被测件（同源自比＝空转）。
    digest = hashlib.blake2b(b"group:1", digest_size=8).hexdigest()
    assert ack_key_segment("group:1") == "group_1" + "_h" + digest


# ---------------------------------------------------------------------------
# 装配可达性锁（D-8(a) 教训：机制存在但装配落空 = 线上零生效而测试全绿）。
# 根 __init__.py 不在 import 面可跑（要 NoneBot 宿主），故用 AST 静态读。
# ---------------------------------------------------------------------------

_ROOT_INIT = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "__init__.py"
)


def _pipeline_call_kwargs() -> dict[str, ast.expr]:
    tree = ast.parse(_ROOT_INIT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "RuntimePipeline"
        ):
            return {kw.arg: kw.value for kw in node.keywords if kw.arg}
    raise AssertionError("根 __init__.py 找不到 RuntimePipeline(...) 构造")


def test_root_injects_both_ack_kwargs_into_pipeline() -> None:
    kwargs = _pipeline_call_kwargs()
    assert "progress_ack_settings" in kwargs, "回执设置未注入 = 生产零生效"
    assert "progress_ack_submit" in kwargs, "回执投递口未注入 = 有设置也发不出去"
    # 值形态与真身咬合的判据在 test_root_injects_both_ack_kwargs_with_values_that_resolve
    # （同一把锁的两半合在那一处，避免两把互证不出新东西）。


def test_root_ack_injection_is_gated_on_the_config_key() -> None:
    """键关必须走 None 分支（惰性导入 + 双 None ⇒ pipeline 与旧代码同形）。"""
    source = _ROOT_INIT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    guarded: list[ast.If] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if "bot_chat_progress_ack_enabled" in test:
            guarded.append(node)
    assert len(guarded) == 1, f"回执装配门应恰一处，实={len(guarded)}"
    body = ast.unparse(guarded[0])
    assert "ProgressAckSettings.from_config" in body
    assert "import" in body, "键关部署不得触新符号 ⇒ 导入须在门内（配音 hook 先例）"
    # else 分支不存在 = 键关时两个变量保持 None（而不是被赋成别的形状）。
    assert guarded[0].orelse == []


def test_root_ack_submit_declares_its_dedupe_namespace() -> None:
    """漏报命名空间会回落 `emg` 口径 = 开闸态整族静默丢消息（R-CENTRAL C-1）。

    注：注入的是闭包（`_submit_progress_ack`），kwargs 处只到名字，故对函数体断言。
    """
    source = _ROOT_INIT.read_text(encoding="utf-8")
    submit_src = "\n".join(
        ast.unparse(node)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_submit_progress_ack"
    )
    assert submit_src, "根 __init__.py 找不到 _submit_progress_ack 投递口"
    assert re.search(r"dedupe_namespace\s*=\s*ACK_DEDUPE_NAMESPACE", submit_src), (
        "中央出口未申报 ack 命名空间"
    )
    assert "submit_active_push" in submit_src, "回执未走唯一主动投递出口"
    assert "to_thread" in submit_src, "回执投递在事件循环上做阻塞写，须下线程"


def test_ack_namespace_is_not_the_emergency_default() -> None:
    assert ACK_DEDUPE_NAMESPACE == "ack"
    assert ACK_DEDUPE_NAMESPACE != "emg"


# ------------------------------------------------ 会话类型归一（跨平台 fail-closed）


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (SessionType.PRIVATE, "private"),
        ("private", "private"),
        (SessionType.GROUP, "group"),
        # 这三档是 2026-09-23 跨平台审计实锤的漏口：旧写法 "group" in raw 判假 ⇒
        # 落进私聊侧，白名单空=放开，于是 TG 频道/邮件/控制台绕过"群聊默认不开"。
        (SessionType.CHANNEL, "group"),
        (SessionType.EMAIL, "group"),
        (SessionType.CONSOLE, "group"),
        ("", "group"),
        ("something-new", "group"),
    ],
)
def test_normalize_session_type_fails_closed_to_group_side(raw, expected) -> None:
    assert normalize_session_type(raw) == expected


def test_channel_and_email_sessions_are_not_emitted_by_default() -> None:
    """频道/邮件/控制台在"私聊白名单为空=放开"下也必须静默（跨平台审计实锤）。"""
    for stype in (SessionType.CHANNEL, SessionType.EMAIL, SessionType.CONSOLE):
        assert (
            progress_ack_allowed(
                GROUP_ON, session_type=stype, group_id="", sender_id="99887766"
            )
            is False
        ), f"{stype} 从私聊侧绕过了群聊默认不开"
    assert (
        progress_ack_allowed(GROUP_ON, session_type=SessionType.PRIVATE, sender_id="1")
        is True
    )


def test_target_scope_of_ack_request_matches_gate_for_channels() -> None:
    """门禁与落点同一判据：频道会话若被显式放行，投递目标必须是那个频道本身。"""
    request = build_progress_ack_request(
        SimpleNamespace(
            request_id="r1",
            session_id="channel_555",
            session_type=SessionType.CHANNEL,
            group_id="",
            sender_id="99887766",
            message_id="m1",
            adapter="telegram",
            bot_id="b",
        ),
        ACK_POOL[0],
    )
    assert request.target_scope is SessionType.GROUP
    assert request.target_id == "99887766"  # 无群号时退到发送者，绝不猜频道


def test_root_ack_submitter_delivers_inline_not_just_enqueues() -> None:
    """生产投递口必须**入列 + 就地投递**两步齐全（S1 评审实锤的 Critical）。

    病根不是代码写错，是"submit 成功"被当成"消息已送达"：
    `queue.submit` 只把 `next_retry_at` 写成内联宽限期
    （= max(60s, 3×传输超时)）并登记"本行有内联首投"的认领台账，
    真正送出由调用方负责——而这条台账还会在本次 chat 任务存活期间挡住 worker。
    于是"只入队"的回执必然晚于正文到达，功能语义直接反转成
    "答完一分钟追一句我在想"。
    这条锁断言的是**结构位置**（投递口函数体里真的 await 了传输投递并校验终态），
    不是"字符串出现过"；注毒：删掉就地投递那段 ⇒ 本用例红。
    """
    source = _ROOT_INIT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    submitter = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_submit_progress_ack"
        ),
        None,
    )
    assert submitter is not None, "根 __init__.py 找不到回执投递口"

    def _named_calls(name: str) -> list[ast.Call]:
        return [
            node
            for node in ast.walk(submitter)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        ]

    # 判定走真 AST 节点，不走 `ast.unparse` 子串：unparse 保留文档串，
    # "字符串出现过"能被一句注释单独满足（席位 S11 探针 4 实测三条断言皆如此，
    # 顺序断言当时也形同虚设）。
    submit_calls = _named_calls("submit_active_push")
    deliver_awaits = [
        node
        for node in ast.walk(submitter)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_deliver_transport_send_request"
    ]
    assert submit_calls, "未走唯一主动投递出口"
    assert deliver_awaits, "只入队未就地投递＝回执必然晚于正文，或根本没投"
    attrs = {
        f"{node.value.id}.{node.attr}"
        for node in ast.walk(submitter)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    }
    assert "ReceiptState.SENT" in attrs, "未校验投递终态就宣称送出"
    assert any(isinstance(node, ast.Raise) for node in ast.walk(submitter)), (
        "投递失败必须抛，好让 pipeline 退还冷却坑"
    )
    # 顺序也要钉：先入列拿放行结论，才谈就地投递（反了就是绕过中央闸）。按 lineno 比，
    # 文档串里的字样不会再冒充"调用 occurred"。
    assert min(call.lineno for call in submit_calls) < min(
        node.lineno for node in deliver_awaits
    )


def test_root_ack_submitter_does_not_submit_off_the_event_loop() -> None:
    """入列必须留在事件循环里，否则 A-22 认领台账静默不登记。

    `_register_inline_claim` 自述"线程提交（无运行中事件循环）不登记：退回纯时间宽限"。
    把 submit 包进 `asyncio.to_thread` ⇒ 线程内 `current_task()` 抛 RuntimeError ⇒
    该行唯一的防双发盾退化成 60s 时间差，而本仓实测过 140–395s 的事件循环停顿
    （台账 #50 根因②），宽限期外被 worker 接管就与就地投递叠成**同一句回执双发**。
    两席独立实跑坐实（S17 复刻双发=True、S20 复算台账不登记），且提醒族四处的
    中央出口全在循环内直调 ⇒ 本波实犯过一次，此锁就是那次的墓碑。
    """
    tree = ast.parse(_ROOT_INIT.read_text(encoding="utf-8"))
    submitter = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_submit_progress_ack"
        ),
        None,
    )
    assert submitter is not None, "根 __init__.py 找不到回执投递口"
    offenders = [
        node.lineno
        for node in ast.walk(submitter)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"to_thread", "run_in_executor", "run_coroutine_threadsafe"}
    ]
    assert not offenders, (
        f"回执投递口把中央出口搬出事件循环（A-22 台账会静默失效）：行 {offenders}"
    )


def test_root_select_queue_bot_receives_the_provider_not_its_result() -> None:
    """`_select_queue_bot(bot_provider, …)` 自己会调 `bot_provider()`。

    首参传成 `_all_online_bots()`（dict）时，`dict` 不可调用 → 该函数把异常
    `except Exception: return None` 吞掉 → 调用方只看到"没有在线 bot"。
    回执因此在生产**一次都发不出去**而全线无告警（本波实犯），故按全根扫。
    """
    tree = ast.parse(_ROOT_INIT.read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_select_queue_bot"
        and node.args
        and isinstance(node.args[0], ast.Call)
    ]
    assert not offenders, (
        f"_select_queue_bot 首参传成了调用结果，应为可调用对象：行 {offenders}"
    )


def test_root_injects_both_ack_kwargs_with_values_that_resolve() -> None:
    """两枚 kwarg 都要锁**值形态**，且名字必须能在同文件解析到真身。

    反面教材（席位 S11 注毒实证）：旧锁只断"键在场"，于是
    `progress_ack_submit=None` 时 72 条全绿，而生产语义是"回执永不发出、
    且无任何告警"——正是它 docstring 点名要防的 D-8(a) 同型病。
    两枚一严一松说明漏的是半边，不是巧合。
    """
    kwargs = _pipeline_call_kwargs()
    settings_value = kwargs.get("progress_ack_settings")
    submit_value = kwargs.get("progress_ack_submit")
    assert isinstance(settings_value, ast.Name), (
        "回执设置未以变量值注入（字面量=键关态不再同形）"
    )
    assert settings_value.id == "progress_ack_settings"
    assert isinstance(submit_value, ast.Name), (
        "回执投递口未以变量值注入：写成 None 就永远发不出去且无人知晓"
    )
    assert submit_value.id == "progress_ack_submit"

    tree = ast.parse(_ROOT_INIT.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    # 键关时局部量必须为 None（装配块外初始化的那行），所以不能要求"注入名=闭包名"；
    # 真正要锁的是：这个局部量在文件里**存在一条从已定义函数取值的赋值**——
    # 名与体互相咬合，在场 ≠ 接得上。注毒 `progress_ack_submit=None`（抹掉那行赋值）
    # 之后此断言当场红。
    bound_to_callable = {
        node.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "progress_ack_submit"
            for target in node.targets
        )
        and isinstance(node.value, ast.Name)
    }
    assert bound_to_callable & defined, (
        "progress_ack_submit 从未被赋成任何已定义的函数 = 回执永不发出"
    )


@pytest.mark.asyncio
async def test_non_chat_capability_is_never_acked() -> None:
    """让路腿：回执只服务 `bot.chat`（S11 注毒：该腿此前全仓无锁，改永真 72 条照绿）。

    命令类回复本就毫秒级，给它追一句"我在想"是用户口径里的"变笨了"。
    """
    other: list = []
    pipeline = _pipeline(delay=_ACK_THRESHOLD_SECONDS, submits=other)
    await pipeline.handle_async(
        _incoming(sender_id="u-leg"),
        _slow_capability(asyncio.Event()),
        "bot.status",
    )
    assert other == [], "非 bot.chat 能力也被回执 = 让路腿失效"

    # 反向格：同夹具只换 capability_id，必须真发出一条
    # （否则"永假"型改判也能蒙过上一条）。
    chat: list = []
    chat_release = asyncio.Event()
    chat_pipeline = _pipeline(
        delay=_ACK_THRESHOLD_SECONDS, submits=chat, release=chat_release
    )
    await chat_pipeline.handle_async(
        _incoming(sender_id="u-leg2"), _slow_capability(chat_release), "bot.chat"
    )
    assert len(chat) == 1


# ---------------------------------------------------------------------------
# 三态名单门 · **管线候选级**（需求项 6 收尾，2026-09-25）
#
# 为什么函数级断言不够：`progress_ack_allowed` 自己绿，不代表会话类型能**原样走到**
# 它面前——`RuntimePipeline._progress_ack_candidate` 在它之前还有一道
# `normalize_session_type(getattr(message, "session_type", ""))` 归一，而 2026-09-23
# 那个跨平台漏口正是"归一腿把五档压成两档"。所以每一态都要从**消息**打进去一次。
#
# 核心不变量（逐格显式断言，不许靠"整族参数化"含糊带过）：
#   群聊默认不开 · 白名单群才开 · 黑名单永远赢 · 私聊白名单空=放开 ·
#   未知会话档位 fail-closed 到群侧（不发）
# ---------------------------------------------------------------------------


def _typed_message(
    session_type: object,
    *,
    sender_id: str = "99887766",
    group_id: str = "",
    platform: str = "qq",
) -> IncomingMessage:
    """按会话类型造一条消息（TG 频道在生产里**也带 group_id**＝chat.id，
    见根 `__init__.py:1340-1341`；夹具不许把它抹成空，否则测的是想象中的世界）。

    群聊这一格必须 `mentions_bot=True`：本席第一版没点名，结果白名单群那一格实跑
    拿到 0 句——不是名单门失灵，而是**群内未点名的闲聊在 `_prepare` 就被拦掉**
    （passive_group_message，台账 #50 的设计语义），候选函数压根没被调用。
    点名之后测的才是"名单门"，不是一道更前面的门禁替它答了案。
    """
    flavour = str(session_type).rsplit(".", 1)[-1].lower()
    if flavour == "group" and group_id:
        key = f"group_{group_id}_{sender_id}"
    elif flavour == "channel":
        key = f"channel_{group_id or sender_id}"
    elif flavour == "email":
        key = f"email:{sender_id}"
    elif flavour == "console":
        key = f"console:{sender_id}"
    else:
        key = f"private:{sender_id}"
    return IncomingMessage(
        platform=platform,
        adapter="telegram" if platform == "telegram" else "onebot",
        bot_id="10000",
        session_id=key,
        session_type=session_type,  # type: ignore[arg-type]
        sender_id=sender_id,
        group_id=group_id or None,
        plain_text="你好",
        mentions_bot=bool(group_id),
        message_id="m-typed",
    )


async def _emit_once(message: IncomingMessage, settings: ProgressAckSettings) -> int:
    """跑一轮真管线，返回这一轮发出去的回执条数。

    「慢」的判定不赌墙钟（与 `_slow_capability` 同一理由，需求项 6 收尾）：回复挂在
    release 事件上，投递口落地那一刻才放行；这一轮不该发的格子由 `_ACK_FUSE_SECONDS`
    引信兜底放行（同钟、阈值的 25 倍——本仓实测过 140–395 秒的循环停顿，
    台账 #50，任何小余量的赛跑在那种停顿面前都是零）。
    """
    submitted: list = []
    release = asyncio.Event()
    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAudit()),
        audit_logger=_NullAudit(),
        progress_ack_settings=settings,
        progress_ack_submit=_gate_submitter("closed", submitted, release),
    )
    await pipeline.handle_async(message, _slow_capability(release), "bot.chat")
    return len(submitted)


_GATE_ON = ProgressAckSettings(
    enabled=True,
    delay_seconds=0.02,
    cooldown_seconds=60.0,
    # 口径①测的是**固定阈值**旧判据；不钉死这枚，日后夹具给管线注了探针，
    # `effective_ack_delay_seconds()` 会把 0.02 秒抬到 floor(15 秒)，整张矩阵
    # 「该发」格全翻红（DEFECT-5 的坑，与 `_pipeline` 里同一条现算）。
    adaptive_enabled=False,
    group_whitelist=frozenset({"662948429", "631785829"}),
    group_blacklist=frozenset({"631785829"}),
    private_whitelist=frozenset(),
    private_blacklist=frozenset({"777777777"}),
)

# 总闸关＝整个功能逐字节不存在（活性判据「两态都要测」的关态一侧）。
_GATE_OFF = ProgressAckSettings(enabled=False, delay_seconds=0.02)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected", "why"),
    [
        (
            _typed_message(SessionType.GROUP, group_id="662948429"),
            1,
            "白名单群：该发",
        ),
        (
            _typed_message(SessionType.GROUP, group_id="999999999"),
            0,
            "群聊默认不开：没进白名单就一句都不发",
        ),
        (
            _typed_message(SessionType.GROUP, group_id="631785829"),
            0,
            "黑名单永远赢（它同时也在白名单里）",
        ),
        (
            _typed_message(SessionType.PRIVATE, sender_id="3865067623"),
            1,
            "私聊白名单为空＝放开（与 bot_content_route 私聊面同口径）",
        ),
        (
            _typed_message(SessionType.PRIVATE, sender_id="777777777"),
            0,
            "私聊黑名单永远赢",
        ),
        (
            # TG 频道：session_type=CHANNEL 且**带 group_id**（生产形态），
            # 白名单是 QQ 群号那一本账 ⇒ 归一到群侧后要求它出现在群白名单里，
            # 不出现就不发。这条就是"非 group 即 private"漏口的反案复查。
            _typed_message(
                SessionType.CHANNEL, group_id="-1001234567890", platform="telegram"
            ),
            0,
            "TG 频道不得从私聊侧绕过「群聊默认不开」",
        ),
        (
            _typed_message(SessionType.EMAIL, sender_id="reader@example.com"),
            0,
            "邮件会话同样静默",
        ),
        (
            _typed_message(SessionType.CONSOLE, sender_id="local"),
            0,
            "控制台会话同样静默（它是本机调试面，不该被主动插话）",
        ),
    ],
)
async def test_name_gate_matrix_through_the_pipeline(
    message: IncomingMessage, expected: int, why: str
) -> None:
    assert await _emit_once(message, _GATE_ON) == expected, why


def test_unknown_session_flavours_are_judged_before_the_contract_can_help() -> None:
    """未知会话档位的兜底（需求项 6 的 fail-closed 半条）。

    先报一条现算事实：`IncomingMessage.session_type` 是 **pydantic 枚举字段**，
    契约层就把"第五档之外的新档位"挡在外面（本波写这条时实测
    `carrier-pigeon` 直接 ValidationError）——所以未知形态不会从生产消息面进来，
    它来自**没带这个属性的对象**：`_progress_ack_candidate` 用的是
    `getattr(message, "session_type", "")`，属性缺失/为 None 都要落群侧。
    这一发直接打候选函数，不经契约（打契约只能测到 pydantic，测不到判据）。
    """
    pipeline = RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAudit()),
        audit_logger=_NullAudit(),
        progress_ack_settings=_GATE_ON,
        progress_ack_submit=lambda request: None,
    )
    cases: list[tuple[object, str, bool, str]] = [
        (
            SimpleNamespace(session_type=None),
            "group",
            False,
            "session_type 为 None ⇒ 归成群侧且静默（`str(None or \"\")`＝空串）",
        ),
        (
            SimpleNamespace(),
            "group",
            False,
            "属性缺失 ⇒ 缺省值空串，归成群侧并静默",
        ),
        (
            SimpleNamespace(session_type="something-new"),
            "group",
            False,
            "字符串形态的新档位 ⇒ 群侧静默",
        ),
        (
            SimpleNamespace(session_type="channel_555"),
            "group",
            False,
            "把会话键误填进 session_type ⇒ 不以 private 结尾，落群侧静默",
        ),
        (
            SimpleNamespace(session_type=SessionType.CHANNEL),
            "group",
            False,
            "枚举 CHANNEL ⇒ 群侧静默",
        ),
        (
            SimpleNamespace(
                session_type="private", sender_id="99887766", group_id=""
            ),
            "private",
            True,
            (
                "字符串 private（枚举之外的宽容形态）仍可发——放开的是真私聊，"
                "不是一切不认识的东西"
            ),
        ),
        (
            SimpleNamespace(
                session_type="SessionType.private", sender_id="99887766", group_id=""
            ),
            "private",
            True,
            "str(Enum) 的完整形态也认得（pydantic 枚举的 __str__ 不是裸值）",
        ),
        (
            # 本席 DEFECT-3 收紧腿自己咬到的那一格：没有 sender_id 就没有身份可判，
            # 私聊侧也一律不发（旧写法在这里会放行，然后投一条 target 为空串的死信、
            # 顺手烧掉本会话 60 秒冷却坑）。
            SimpleNamespace(session_type="private", group_id=""),
            "private",
            False,
            "真私聊但没有 sender_id ⇒ 无身份可判 = 不发",
        ),
    ]
    for holder, expected_norm, expected, why in cases:
        raw = getattr(holder, "session_type", "")
        assert normalize_session_type(raw) == expected_norm, f"归一判据：{why}"
        got = pipeline._progress_ack_candidate(holder, "bot.chat")  # type: ignore[arg-type]
        assert got is expected, f"{why}：holder={holder!r} got={got}"


@pytest.mark.asyncio
async def test_private_whitelist_non_empty_narrows_the_private_side() -> None:
    """私聊"空=放开"的另一半：一旦有人填了白名单，没进去的人就必须收声。

    只断"空=放开"的话，判据写成"永远放开"也能绿（两半各钉一发才咬得住）。
    """
    narrowed = ProgressAckSettings(
        **{**_GATE_ON.__dict__, "private_whitelist": frozenset({"3865067623"})}
    )
    assert (
        await _emit_once(
            _typed_message(SessionType.PRIVATE, sender_id="3865067623"), narrowed
        )
        == 1
    )
    assert (
        await _emit_once(
            _typed_message(SessionType.PRIVATE, sender_id="1234567890"), narrowed
        )
        == 0
    )


@pytest.mark.asyncio
async def test_an_unidentifiable_private_sender_is_not_acked() -> None:
    """收紧腿（本波 DEFECT-3）：私聊腿也要求"有身份可判"。

    旧写法在 `private_whitelist` 为空时连 sender_id 都不看就放行 ⇒
    ① 黑名单挡不住号缺失的会话；② 投递目标 `group_id or sender_id` 退成空串，
    这一句注定发不出去，却已占掉本会话 60 秒冷却坑——一次必败的发送把下一次
    能成功的追问挡在门外。群侧一直是 `bool(group_id) and …` 同形判据。
    """
    assert (
        await _emit_once(
            _typed_message(SessionType.PRIVATE, sender_id=""), _GATE_ON
        )
        == 0
    )
    assert progress_ack_allowed(_GATE_ON, session_type="private", sender_id="") is False


@pytest.mark.asyncio
async def test_group_side_gate_is_still_bare_id_matching_across_platforms() -> None:
    """现状锁（DEFECT-2，登记不修）：群侧白名单只按裸号匹配、**不分平台**。

    生产里 TG 频道消息带 `group_id`＝chat.id（根 `__init__.py:1340-1341`），于是
    同号的 QQ 群被白名单放行时，TG 那一路也一并放行 = 同号不同平台误投。紧急域为
    同类问题已立平台门（`capabilities/emergency_info.py` 非 QQ 拒收，台账 #46），
    回执面缺这一腿。
    本发**故意锁现状**：哪天补上平台腿，这里必红一次，逼接手的人改判据而不是忘。
    修法坐标（两处皆本席禁写面）：`pipeline.py:1443` 的 `progress_ack_allowed(...)`
    多传一腿 `platform=str(getattr(message, "platform", ""))`，
    `progress_ack.progress_ack_allowed` 群侧加 `platform in {"qq", ""}` 门。
    """
    leaky = ProgressAckSettings(
        **{
            **_GATE_ON.__dict__,
            "group_whitelist": frozenset({"662948429"}),
            "group_blacklist": frozenset(),
        }
    )
    same_id_channel = _typed_message(
        SessionType.CHANNEL, group_id="662948429", platform="telegram"
    )
    assert normalize_session_type(same_id_channel.session_type) == "group"
    assert await _emit_once(same_id_channel, leaky) == 1, (
        "现状变了＝平台腿已补：把本发改成断 0 并在 DEFECT-2 台账摘牌"
    )


# ---------------------------------------------------------------------------
# 三条裁定口径的行为锁 · 各测**开闸 / 关闸两态**（需求项 6 收尾第二件，2026-09-26）
#
# 为什么两态是硬要求：出站闸 `bot_outbound_gate_enabled` 今天缺省**关**
# （`config.py` 缺省 False、生产 `.env` 无此行 ⇒ 键形/顺延/限流在线上暂不生效）。
# 只测关态＝测「这道闸不存在」，只测开态＝测「这条现网没人走的路」——所以每条
# 口径都要 closed 与 open_allow 各到一次，闸会改结果的那条再加 open_block 格。
# 闸的交互形状复刻根 `_submit_progress_ack`：拦下/判顺延⇒交回队列不就地投；
# 放行⇒入列+即送；键形核验走**中央谓词真身**，不复制第二套正则
# （规则唯一住 `domains/emergency_info/service/dedupe.py`，AGENTS 铁律）。
# ---------------------------------------------------------------------------


def _ruling_settings(**overrides: object) -> ProgressAckSettings:
    base: dict[str, object] = {
        "enabled": True,
        "delay_seconds": _ACK_THRESHOLD_SECONDS,
        "cooldown_seconds": 60.0,
        "adaptive_enabled": False,
        "group_whitelist": frozenset({"662948429", "631785829"}),
        "group_blacklist": frozenset({"631785829"}),
        "private_whitelist": frozenset(),
        "private_blacklist": frozenset({"777777777"}),
    }
    base.update(overrides)
    return ProgressAckSettings(**base)  # type: ignore[arg-type]


def _ruling_pipeline(
    settings: ProgressAckSettings,
    delivered: list,
    release: asyncio.Event,
    state: str,
) -> RuntimePipeline:
    return RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAudit()),
        audit_logger=_NullAudit(),
        progress_ack_settings=settings,
        progress_ack_submit=_gate_submitter(state, delivered, release),
    )


# 口径①：超过阈值才发——阈值内 0 句、超阈值恰 1 句；事后不补句由 `_slow_capability`
# 的事件顺序结构性保证（回复只有在回执送出之后才交卷，回执之后管线里再无 submit）。
@pytest.mark.asyncio
@pytest.mark.parametrize("state", _GATE_STATES)
async def test_ruling_1_emits_only_over_threshold_both_gate_states(state: str) -> None:
    # ── 阈值内出结果 ⇒ 一句都不发（fast 腿，两态同判）。
    fast_submitted: list = []
    fast_pipeline = _ruling_pipeline(
        _ruling_settings(delay_seconds=_ACK_FUSE_SECONDS),
        fast_submitted,
        asyncio.Event(),
        state,
    )
    fast_msg = _incoming(sender_id=f"r1-fast-{state}")
    receipt_fast = await fast_pipeline.handle_async(
        fast_msg, _fast_capability(fast_msg), "bot.chat"
    )
    assert fast_submitted == [], "①阈值内出结果：一句回执都不该发、事后也不补句"
    assert str(receipt_fast.state).endswith("SENT"), "快轮次自己的真回复要照到"

    # ── 超阈值 ⇒ closed / open_allow 恰发一句；open_block 一句不发（闸拦下）。
    submitted: list = []
    release = asyncio.Event()
    pipeline = _ruling_pipeline(_ruling_settings(), submitted, release, state)
    msg = _incoming(sender_id=f"r1-slow-{state}")
    receipt = await pipeline.handle_async(
        msg, _slow_capability(release), "bot.chat"
    )
    expected = 0 if state == "open_block" else 1
    assert len(submitted) == expected, (
        f"①超阈值在 {state} 态该发 {expected} 句，实发 {len(submitted)}"
    )
    assert str(receipt.state).endswith("SENT"), "①真回复无论闸态都要照到"


# 口径②：发出后真回复回来什么都不做——不撤回、不道歉、不补第二句（成功与失败两面）。
@pytest.mark.asyncio
@pytest.mark.parametrize("state", ("closed", "open_allow"))
@pytest.mark.parametrize("reply_fails", (False, True))
async def test_ruling_2_nothing_happens_when_reply_arrives(
    state: str, reply_fails: bool
) -> None:
    submitted: list = []
    release = asyncio.Event()
    pipeline = _ruling_pipeline(_ruling_settings(), submitted, release, state)
    msg = _incoming(sender_id=f"r2-{state}-{int(reply_fails)}")
    receipt = await pipeline.handle_async(
        msg, _slow_capability(release, fail=reply_fails), "bot.chat"
    )
    assert len(submitted) == 1, "②回执已发出：真回复到达后不得再补第二句"
    text = submitted[0].content.text_fallback
    assert text in ACK_POOL or text == ACK_DEFAULT_TEXT, "②发出的必须还是那句回执本体"
    for apology in ("抱歉", "回复慢", "久等", "对不起"):
        assert apology not in text, f"②不得出现道歉式补句：{apology}"
    state_name = "FAILED_FINAL" if reply_fails else "SENT"
    assert str(receipt.state).endswith(state_name), (
        f"②真回复{'失败' if reply_fails else '成功'}到达，终态应为 {state_name}"
    )
    # 「不撤回」在离线的可机检形态＝回执发出后没有任何后续投递动作再发生：
    # 上面 `len(submitted) == 1` 到管线返回之后仍然成立即是。


# 口径③：群聊默认不开 + 黑名单永远赢 + 未知会话类型 fail-closed（两态各到一次）。
@pytest.mark.asyncio
@pytest.mark.parametrize("state", ("closed", "open_allow"))
@pytest.mark.parametrize(
    ("message", "expected", "why"),
    [
        (
            _typed_message(SessionType.GROUP, group_id="662948429"),
            1,
            "白名单群：两态都该发（只测关态=测闸不存在）",
        ),
        (
            _typed_message(SessionType.GROUP, group_id="999999999"),
            0,
            "③群聊默认不开：未入白名单的群一句都不发",
        ),
        (
            _typed_message(SessionType.GROUP, group_id="631785829"),
            0,
            "③黑名单永远赢：黑白同在册取黑",
        ),
        (
            _typed_message(SessionType.CHANNEL, group_id="631785829", platform="telegram"),
            0,
            "③黑名单对同号的其它平台会话同样生效",
        ),
        (
            _typed_message(SessionType.EMAIL, sender_id="reader@example.com"),
            0,
            "③未知/非私聊会话类型 fail-closed：邮件静默",
        ),
    ],
)
async def test_ruling_3_group_default_off_blacklist_wins_fail_closed(
    message: IncomingMessage, expected: int, why: str, state: str
) -> None:
    submitted: list = []
    release = asyncio.Event()
    pipeline = _ruling_pipeline(_ruling_settings(), submitted, release, state)
    await pipeline.handle_async(message, _slow_capability(release), "bot.chat")
    assert len(submitted) == expected, f"③{state} 态：{why}"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", _GATE_STATES)
async def test_ruling_3_master_switch_off_never_emits(state: str) -> None:
    """③的总闸面：`enabled=False` ⇒ 一切名单/阈值/闸态都不发（现网键关同形）。"""
    submitted: list = []
    release = asyncio.Event()
    pipeline = _ruling_pipeline(
        _ruling_settings(enabled=False), submitted, release, state
    )
    await pipeline.handle_async(
        _typed_message(SessionType.GROUP, group_id="662948429"),
        _slow_capability(release),
        "bot.chat",
    )
    assert submitted == [], "③总闸关⇒任何闸态一句都不发"


# ---------------------------------------------------------------------------
# DEFECT-6（登记不修，本席禁写面；与前窗口台账 DEFECT-4 同一判据，合并挂账）：
# 开闸态「闸拦下(skip)」会烧掉本会话冷却坑
#
# 根 `_submit_progress_ack` docstring 承诺「闸拦下或判了顺延：交回队列，**不占
# 冷却坑**」，但现算不成立：
#   ① pipeline `_emit_progress_ack`（runtime/pipeline.py:1513）在调 submit **之前**
#      就 `try_claim()` 占坑；
#   ② submit 只在**抛异常**时 `release`（pipeline.py:1532-1534）；
#   ③ 而根投递口对闸拦下/顺延走的是 **`return outcome`（不抛）**——__init__.py:3991-3992
#      `if verdict.action != "allow" or verdict.deliver_after is not None: return outcome`。
# ⇒ 开闸态下每一次「拦下」都白烧一枚冷却坑（60 秒），与注释相反。关闸态（今日生产）
#   恒 allow，不触发。
# ⚠ 语义细分（前窗口 §交卷-D3 的更准确版本，本席并入）：中央闸动作三档里
#   `defer`（判顺延）其实**该**继续占坑——那句话稍后会由 worker 真送出去，
#   「已承诺」成立；真正白烧的只有 `skip`（拦死永不送）。根投递口现在把两档
#   混在同一个 `return outcome` 里，修法应拆开：skip ⇒ 抛（退坑），defer ⇒ 占。
# 修法坐标（禁写面）：根投递口按 verdict.action 分叉，或 pipeline 检查 submit
#   返回值的 verdict 再决定 release。修好后本用例自然转绿（非 strict xfail），
#   摘掉标记即可。
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT-6：开闸态闸拦下（submit 正常返回而非抛）⇒ pipeline 的 try_claim "
        "不被 release，本会话冷却坑白烧 60 秒；与根 docstring「不占冷却坑」相反。"
        "修法坐标见上方注释块。"
    ),
)
@pytest.mark.asyncio
async def test_gate_block_should_not_burn_the_cooldown_slot() -> None:
    submitted: list = []
    pipeline = _ruling_pipeline(
        _ruling_settings(), submitted, asyncio.Event(), "open_block"
    )
    msg = _incoming(sender_id="r-slot")
    await pipeline.handle_async(msg, _slow_capability(asyncio.Event()), "bot.chat")
    assert submitted == [], "前提：闸拦下，本句没送出去"

    # 没送出去 ⇒ 坑该退还：同一会话下一轮慢问（闸此刻放行）还能拿到一句。
    again: list = []
    release = asyncio.Event()
    pipeline.progress_ack_submit = _gate_submitter("closed", again, release)
    await pipeline.handle_async(
        _incoming(sender_id="r-slot"), _slow_capability(release), "bot.chat"
    )
    assert len(again) == 1, "闸拦下没退坑：同会话 60 秒内的下一次慢问被白挡"
