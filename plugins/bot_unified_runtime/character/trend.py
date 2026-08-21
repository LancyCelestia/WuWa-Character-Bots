"""时梗 / 时效备注层。

解决"回复贴合人设但又不脱离当下互联网"的张力：人格文件保持稳定
（人设不该天天改），而"最近的梗、热词、时事"放进独立、可随手更新
的备注文件里，作为**不可信背景事实**注入 prompt。这样：

- 人设（人格文件）不需要为了跟热点而频繁改动，降低人设漂移风险。
- 备注过期的会被 ``max_age_days`` 自动过滤，避免机器人说陈年旧梗。
- 所有备注在 prompt 中明确标注"可能过时、不能假装亲眼见过"。

备注文件是 Markdown：``## <主题> (YYYY-MM-DD)`` 或 ``## <主题>``
作为小节，小节内的每一行是一个备注。日期只写在小节标题里。

数据流：``TrendProvider.load -> TrendContext -> ContextBundle
-> build_chat_prompt 的"近期时效信息"分区``。该层不决定发送、不写
长期记忆、不能覆盖权限与审计。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from plugins.bot_unified_runtime.contracts.character import (
    TrendContext,
    TrendNote,
)

_DATE_IN_HEADING = re.compile(r"\((\d{4}-\d{2}-\d{2})\)\s*$")
_TOPIC_LINE = re.compile(r"^#{1,3}\s+(.+)$")


class TrendProvider(Protocol):
    def load(self, request_id: str) -> TrendContext:
        """读取当前可用的时梗备注。"""


class NullTrendProvider:
    def load(self, request_id: str) -> TrendContext:
        return TrendContext(request_id=request_id, notes=[])


@dataclass(frozen=True)
class TrendSettings:
    max_notes: int = 5
    max_chars: int = 500
    max_age_days: int = 14


def _parse_observed_on(heading: str) -> tuple[str, str]:
    match = _DATE_IN_HEADING.search(heading.strip())
    if match:
        return heading[: match.start()].strip(), match.group(1)
    return heading.strip(), ""


def _date_is_fresh(observed_on: str, max_age_days: int) -> bool:
    if not observed_on or max_age_days <= 0:
        return True
    try:
        observed = datetime.strptime(observed_on, "%Y-%m-%d").replace(
            tzinfo=UTC
        )
    except ValueError:
        return True
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    return observed >= cutoff


class FileTrendProvider:
    """从本地 Markdown 备注文件读取时梗。"""

    def __init__(
        self,
        notes_files: list[str | Path],
        *,
        max_notes: int = 5,
        max_chars: int = 500,
        max_age_days: int = 14,
    ) -> None:
        self.notes_files = [Path(path).expanduser() for path in notes_files]
        self.max_notes = max(0, max_notes)
        self.max_chars = max(0, max_chars)
        self.max_age_days = max(0, max_age_days)

    def load(self, request_id: str) -> TrendContext:
        notes: list[TrendNote] = []
        total_chars = 0
        for path in self.notes_files:
            if len(notes) >= self.max_notes:
                break
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            topic = path.stem
            observed_on = ""
            for raw_line in text.splitlines():
                if len(notes) >= self.max_notes:
                    break
                heading = _TOPIC_LINE.match(raw_line)
                if heading:
                    topic, observed_on = _parse_observed_on(heading.group(1))
                    continue
                line = raw_line.strip().lstrip("-*").strip()
                if not line or line.startswith("```") or line.startswith("#"):
                    continue
                if not _date_is_fresh(observed_on, self.max_age_days):
                    continue
                remaining = self.max_chars - total_chars
                if remaining <= 0:
                    break
                if len(line) > remaining:
                    line = f"{line[: max(1, remaining - 1)]}…"
                if not line:
                    continue
                notes.append(
                    TrendNote(
                        topic=topic,
                        note=line,
                        observed_on=observed_on,
                        source="local_notes",
                    )
                )
                total_chars += len(line)
        return TrendContext(request_id=request_id, notes=notes)


def build_trend_provider(config: object) -> TrendProvider:
    """按配置构造时梗 provider；未启用或无文件时返回空实现。"""
    enabled = bool(getattr(config, "bot_trend_enabled", False))
    files = list(getattr(config, "bot_trend_files", []) or [])
    if not enabled or not files:
        return NullTrendProvider()
    return FileTrendProvider(
        notes_files=files,
        max_notes=int(getattr(config, "bot_trend_max_notes", 5)),
        max_chars=int(getattr(config, "bot_trend_max_chars", 500)),
        max_age_days=int(getattr(config, "bot_trend_max_age_days", 14)),
    )
