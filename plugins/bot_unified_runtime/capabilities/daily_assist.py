"""收件箱速记能力（bot.daily_assist）：把随手想到的事丢进收件箱文件。

触发：`收件箱 <内容>`（带内容=记一条；不带=看一眼待处理清单），
别名 `inbox`/`shoujianxiang`。存储面在 character/daily_assist.py——
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
from plugins.bot_unified_runtime.contracts.runtime import IncomingMessage

# 前缀锚定 + 右边界防胶合（chishenmeqq 同款手法）。
_DAILY_ASSIST_RE = re.compile(
    r"^[/!！]?(?:收件箱|inbox|shoujianxiang)(?![A-Za-z0-9])[？?]?\s*(.*)$",
    re.DOTALL,
)
_QUERY_BODIES = {"", "?", "？", "看看", "列表", "清单", "有什么", "list"}

_HELP_TEXT = (
    "收件箱用法：发「收件箱 内容」把事情记进来（早报我会整理）；"
    "发「收件箱」看我目前攒着的。"
)


def is_daily_assist_command(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and bool(_DAILY_ASSIST_RE.match(stripped))


def build_daily_assist_capability(config: Any | None = None) -> Any:
    """构建收件箱速记能力：与 notes 等能力一致，(message, decision) → 结果。"""

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        from plugins.bot_unified_runtime.character.daily_assist import (
            append_inbox_line,
            inbox_path,
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
                return _result("收件箱现在是空的。攒着的事随时丢进来。", "query")
            listing = "\n".join(f"{index}. {item}" for index, item in enumerate(pending, 1))
            return _result(f"收件箱里攒着 {len(pending)} 件：\n{listing}", "query")
        if not body:
            return _result(_HELP_TEXT, "help")
        if len(body) > 2000:
            body = body[:2000]
        line = append_inbox_line(inbox_path(config), body)
        return _result(f"收进了：{line}\n早报的时候我一并理给你。", "capture")

    return capability
