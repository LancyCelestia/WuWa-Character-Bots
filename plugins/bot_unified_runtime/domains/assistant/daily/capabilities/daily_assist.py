"""收件箱速记能力（bot.daily_assist）：把随手想到的事丢进收件箱文件。

触发：`收件箱 <内容>`（带内容=记一条；不带=看一眼待处理清单），
别名 `inbox`/`shoujianxiang`。存储面在 domains/assistant/daily/store/daily_assist.py——
收件箱是纯文本文件（``bot_daily_assist_dir``/inbox.md），早报定时任务
读它做晨间简报，ZCode/手机端也能直接编辑同一份文件。
"""

from __future__ import annotations

import re
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    SendPolicy,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import IncomingMessage

# 前缀锚定 + 右边界防胶合（chishenmeqq 同款手法）。
_DAILY_ASSIST_RE = re.compile(
    r"^[/!！]?(?:收件箱|inbox|shoujianxiang)(?![A-Za-z0-9])[？?]?\s*(.*)$",
    re.DOTALL,
)
_QUERY_BODIES = {"", "?", "？", "看看", "列表", "清单", "有什么", "list"}

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

_CAPTURE_VARIANTS: tuple[str, ...] = (
    "守岸人收好了：{line}\n早报的时候一并理给你。",
    "记下了：{line}\n放进收件箱，早报再细看。",
    "好，收进去了：{line}\n明早守岸人把它排进早报。",
    "收到了：{line}\n先攒着，不急。",
    "这件事守岸人替你记着：{line}\n丢不了。",
    "收好了：{line}\n等早报一起看。",
)


def is_daily_assist_command(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and bool(_DAILY_ASSIST_RE.match(stripped))


def build_daily_assist_capability(config: Any | None = None) -> Any:
    """构建收件箱速记能力：与 notes 等能力一致，(message, decision) → 结果。"""

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
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
        if len(body) > 2000:
            body = body[:2000]
        line = append_inbox_line(inbox_path(config), body)
        return _result(pick_variant("inbox_capture", _CAPTURE_VARIANTS, line=line), "capture")

    return capability
