"""收件箱速记能力（bot.daily_assist）：把随手想到的事丢进收件箱文件。

触发：`收件箱 <内容>`（带内容=记一条；不带=看一眼待处理清单），
别名 `inbox`/`shoujianxiang`。存储面在 domains/assistant/daily/store/daily_assist.py——
收件箱是纯文本文件（``bot_daily_assist_dir``/inbox.md），早报定时任务
读它做晨间简报，ZCode/手机端也能直接编辑同一份文件。

权限口径（S-FIX-ATK-NOTES 2026-09-27，实锤 3 读侧降档）：收件箱是**全局一份**
共享文件（设计如此，含主人私事），**写/追加**维持全员可用，**裸查询列清单**
只对推送名单（owner 侧）与超管开放——判点收在本能力面，不动路由/板块文案。

群语境 fail-closed（S-FIX-SCHED20-H4 2026-09-27，第 20 项隐私修法）：收件箱
条目没有「公/密」分级列，任何一行都无法证明是「公」⇒ 与 schedule_board G2
自视图「群语境不出私密行」同源同尺——裸查询只在**私聊**语境出内容，
群聊（及一切非私聊/语境缺失）即便问话人是名单主或超管也走降档拒答。

A3a（S-FIX-GOAL18-REST2 2026-09-28）：写/追加腿加**按发送者滑窗限频**——
此前无任何速率门，刷屏可把待处理段灌成海量行，拖垮早报整条投递
（A3b 只帽消息体量，不解存储灌满）。门槛常量在本文件（先例：
reminders.MAX_PENDING_PER_SENDER，不新增 config 键）；拒答文案不透
窗口/上限数字。查询与帮助腿不限频（只读，无存储增长面）。
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import IncomingMessage

# 前缀锚定 + 右边界防胶合（chishenmeqq 同款手法）。
_DAILY_ASSIST_RE = re.compile(
    r"^[/!！]?(?:收件箱|inbox|shoujianxiang)(?![A-Za-z0-9])[？?]?\s*(.*)$",
    re.DOTALL,
)
_QUERY_BODIES = {"", "?", "？", "看看", "列表", "清单", "有什么", "list"}

# A3a：写/追加腿按发送者滑窗限频。刻意不新增 config 键（先例见 reminders.
# MAX_PENDING_PER_SENDER）；要可调走提案。sender 缺失（空串/None）归并到
# 同一个 fail-closed 桶 ""，不给匿名者留无限速旁路。
_INBOX_RATE_WINDOW_SECONDS = 3600.0
_INBOX_RATE_MAX_PER_WINDOW = 20
_INBOX_RATE_LOCK = threading.Lock()
_INBOX_RATE_HITS: dict[str, deque[float]] = {}


def _inbox_rate_allowed(sender_id: str, now: float | None = None) -> bool:
    """滑窗计数：窗口内已满则拒（且不记账），否则记一次命中并放行。"""
    moment = time.time() if now is None else float(now)
    bucket = str(sender_id or "").strip()
    with _INBOX_RATE_LOCK:
        hits = _INBOX_RATE_HITS.setdefault(bucket, deque())
        while hits and moment - hits[0] >= _INBOX_RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= _INBOX_RATE_MAX_PER_WINDOW:
            return False
        hits.append(moment)
        return True


def reset_inbox_rate_state() -> None:
    """清空限频台账（测试/重启语义用；生产路径不需要显式调）。"""
    with _INBOX_RATE_LOCK:
        _INBOX_RATE_HITS.clear()

# 命令面文案池（守岸人语气）：轮换机制用 domains/assistant/daily/store/daily_assist.pick_variant，
# 同池按调用序循环，连发不重复；语义各变体等价，只换说法。
_HELP_VARIANTS: tuple[str, ...] = (
    "收件箱的用法：发「收件箱 内容」就把事情记下了，早报守岸人会一并整理；发「收件箱」能看现在攒着的。",
    "想记事，发「收件箱 内容」，守岸人替你收着；发「收件箱」不带内容，看的就是目前攒下的。",
    "「收件箱 内容」是记一笔，早报时守岸人会理给你；只发「收件箱」，就把攒着的翻出来看看。",
    "把想到的交给收件箱：发「收件箱 内容」记下；发「收件箱」，看守岸人目前替你攒着的。",
    "用法很简单：「收件箱 内容」记事，「收件箱」看清单。记下的事，早报会一并整理。",
    "随手记用「收件箱 内容」，守岸人会收好，早报再理给你；发「收件箱」不带字，就能翻看攒下的。",
)

_QUERY_EMPTY_VARIANTS: tuple[str, ...] = (
    "收件箱空着呢。想到什么，随时丢进来。",
    "现在什么都没攒着。守岸人守着收件箱，随时等你。",
    "收件箱干干净净，一件待办都没有。",
    "空空的，还没攒下事情。有想记的就说。",
    "守岸人看过了，收件箱现在是空的。想到随时说。",
    "这里很安静，还没有事情进来。你开口，守岸人就记。",
)

_QUERY_LISTING_VARIANTS: tuple[str, ...] = (
    "收件箱里攒着 {n} 件：\n{listing}",
    "现在攒了 {n} 件事：\n{listing}",
    "守岸人替你记着 {n} 件：\n{listing}",
    "攒下的有 {n} 件，都在这儿：\n{listing}",
    "收件箱里躺着 {n} 件事，逐条给你：\n{listing}",
    "记着的共 {n} 件，守岸人列给你：\n{listing}",
)

# 读侧降档文案（实锤 3）：名单外者拿到的拒答不透明细、也不透条数；
# 「记一条」仍全员可用，所以话术留出口。
_QUERY_DENIED_VARIANTS: tuple[str, ...] = (
    "收件箱是主人自己攒事的地方，守岸人就不替你翻啦。想记事的话，「收件箱 内容」照样能丢。",
    "守岸人看管的是主人的小本子，本子上的事只对主人开口。记事的话随时可以丢一条进来。",
    "这份清单守岸人只念给主人听，旁人来问也是这个口风。要记一笔的话，「收件箱 内容」就好。",
    "抱歉，收件箱里攒了什么，守岸人只对主人说。你想记事，丢「收件箱 内容」一条就行。",
    "守岸人替主人收着这些小事，也对旁人保密——攒着的东西不外翻，记事门倒是常开。",
    "想让守岸人记事，随时丢「收件箱 内容」；至于翻看攒下的，那是主人和守岸人之间的事。",
)

_CAPTURE_VARIANTS: tuple[str, ...] = (
    "守岸人收好了：{line}\n早报的时候一并理给你。",
    "记下了：{line}\n放进收件箱，早报再细看。",
    "好，收进去了：{line}\n明早守岸人把它排进早报。",
    "收到了：{line}\n先攒着，不急。",
    "这件事守岸人替你记着：{line}\n丢不了。",
    "收好了：{line}\n等早报一起看。",
)

# A3a 限频拒答池：守岸人语气、不透窗口/上限数字（口径同 _QUERY_DENIED_VARIANTS
# 「不透细」），留「缓一缓再来」的出口。
_CAPTURE_DENIED_VARIANTS: tuple[str, ...] = (
    "这条守岸人先不收——你记事的频率太密了，缓一缓再来丢一条吧。",
    "守岸人手头的本子这会儿合上了，太快丢进来会接不住。稍后再说一次。",
    "攒得太急了，守岸人替你理不过来。歇一会儿，再丢一条进来就好。",
    "先按一下——这么密的记事守岸人收不住，待会儿再来丢吧。",
    "这条先婉拒：频率太高了。守岸人还在，缓一缓再说。",
    "记事门常开，但一阵急雨守岸人也接不住。等一会，再丢一条来。",
)


def is_daily_assist_command(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and bool(_DAILY_ASSIST_RE.match(stripped))


def _may_read_inbox(message: Any, config: Any, decision: Any) -> bool:
    """收件箱列面读取权：私聊语境 +（推送名单 owner 侧 或 超管）；fail-closed。

    名单与早报推送目标同源（``bot_daily_assist_push_user_ids``）——能收到
    简报的人才配主动翻简报内容；写/追加面不走此门（设计=全员速记）。
    语境门（S-FIX-SCHED20-H4）：非私聊一律拒——收件箱行无「公/密」分级，
    群语境拿不出任何一行可证明为「公」（与 schedule_board G2 同源口径）。
    """
    # 语境缺失按非私聊判（str Enum 等值判据，兼容契约对象与夹具字面量）。
    if getattr(message, "session_type", None) != SessionType.PRIVATE:
        return False
    # 延迟导入：policy 包与 root 装配存在启动期环（capabilities 先于 runtime
    # 被根 import），本行在查询命令触发时才走。
    from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
        ROLE_SUPER_ADMIN,
    )

    roles = {str(role) for role in (getattr(decision, "actor_roles", None) or [])}
    if ROLE_SUPER_ADMIN in roles:
        return True
    sender = str(getattr(message, "sender_id", "") or "").strip()
    if not sender:
        return False
    roster = {
        str(user).strip()
        for user in (getattr(config, "bot_daily_assist_push_user_ids", None) or [])
    }
    return bool(roster) and sender in roster


def build_daily_assist_capability(config: Any | None = None) -> Any:
    """构建收件箱速记能力：与 notes 等能力一致，(message, decision) → 结果。"""

    def capability(message: IncomingMessage, decision: Any) -> CapabilityResult:
        from plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist import (
            append_inbox_line,
            inbox_path,
            pick_variant,
            read_pending_inbox,
        )

        text = (message.plain_text or "").strip()
        match = _DAILY_ASSIST_RE.match(text)
        body = (match.group(1) if match else "").strip()

        def _result(body_text: str, *tags: str) -> CapabilityResult:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.daily_assist",
                kind="text",
                title="",
                body=body_text,
                send_policy=SendPolicy.SILENT_AUDIT,
                privacy_level=PrivacyLevel.PERSONAL,
                audit_tags=["daily_assist", *tags],
            )

        if body.lower() in _QUERY_BODIES:
            if not _may_read_inbox(message, config, decision):
                # 读侧降档：不透条目、不透条数（实锤 3）。
                return _result(
                    pick_variant("inbox_query_denied", _QUERY_DENIED_VARIANTS),
                    "query_denied",
                )
            pending = read_pending_inbox(inbox_path(config))
            if not pending:
                return _result(
                    pick_variant("inbox_query_empty", _QUERY_EMPTY_VARIANTS), "query"
                )
            listing = "\n".join(f"{index}. {item}" for index, item in enumerate(pending, 1))
            return _result(
                pick_variant(
                    "inbox_query_list", _QUERY_LISTING_VARIANTS, n=len(pending), listing=listing
                ),
                "query",
            )
        if not body:
            return _result(pick_variant("inbox_help", _HELP_VARIANTS), "help")
        # A3a：截断之前先过限频门——被拒的条目连存储都不该摸到。
        if not _inbox_rate_allowed(str(getattr(message, "sender_id", "") or "")):
            return _result(
                pick_variant("inbox_capture_denied", _CAPTURE_DENIED_VARIANTS),
                "capture_rate_limited",
            )
        if len(body) > 2000:
            body = body[:2000]
        line = append_inbox_line(inbox_path(config), body)
        return _result(pick_variant("inbox_capture", _CAPTURE_VARIANTS, line=line), "capture")

    return capability
