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

写入面（审查 O-05 补缺）：历史上本层只读（词条来源只有手写文件，
运行期无法积累）。现提供**显式**写入 API ``add_trend_entry``：落盘
沿用同一 Markdown 形态，同名词条覆盖解释（keep-newest），条目总数
有上限防膨胀。注意两点纪律：

- **默认关语义保留**：``build_trend_provider`` 仍按 ``bot_trend_enabled``
  决定注入；写入口不自动触发、不影响任何读取/注入逻辑。
- **调用方接线待批**：本函数当前仅供后续管理员命令/反思链路调用
  （自动学习需 propose→approve 设计评审，本模块不做自动学习）。
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from plugins.bot_unified_runtime.domains.core.contracts.character import (
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
                if not line or line.startswith(("```", "#")):
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


# 单文件条目上限：防手写文件之外运行期积累导致无限膨胀（审查 O-05）。
# 超限时按文件顺序淘汰最旧（最前）小节，语义是"最新梗优先"的 FIFO。
MAX_TREND_ENTRIES = 200


def _split_markdown_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """按 `_TOPIC_LINE` 标题把 Markdown 切成 (前导内容, [(规范化主题, 小节原文)])。

    与 ``FileTrendProvider.load`` 同一标题语义：任何 ``#{1,3}`` 标题都
    开启一个主题小节（``(YYYY-MM-DD)`` 日期后缀不参与主题名归一）。
    归一用 ``strip().casefold()``，供同名去重比较。
    """
    preamble_lines: list[str] = []
    sections: list[tuple[str, str]] = []
    current_topic: str | None = None
    current_lines: list[str] = []
    for raw_line in text.splitlines():
        heading = _TOPIC_LINE.match(raw_line)
        if heading:
            if current_topic is not None:
                sections.append((current_topic, "\n".join(current_lines)))
            topic, _ = _parse_observed_on(heading.group(1))
            current_topic = topic.strip().casefold()
            current_lines = [raw_line]
        elif current_topic is None:
            preamble_lines.append(raw_line)
        else:
            current_lines.append(raw_line)
    if current_topic is not None:
        sections.append((current_topic, "\n".join(current_lines)))
    return "\n".join(preamble_lines), sections


def _render_trend_section(
    term: str, explanation: str, observed_on: str, source: str
) -> str:
    """渲染一个小节；写出的形态必须能被 ``load`` 原样解析（注入面零变化）。

    source 行用 ``####`` 前缀：``load`` 对 ``#`` 开头行直接跳过、且
    ``_TOPIC_LINE`` 只认 1-3 级标题，因此该行不会进入注入面，仅作
    人工审计留痕。
    """
    heading = f"## {term} ({observed_on})" if observed_on else f"## {term}"
    lines = [heading, f"- {explanation}"]
    if source and source != "manual":
        lines.append(f"#### source: {source}")
    return "\n".join(lines)


def add_trend_entry(
    notes_file: str | Path,
    term: str,
    explanation: str,
    *,
    observed_on: str | None = None,
    source: str = "manual",
    max_entries: int = MAX_TREND_ENTRIES,
) -> bool:
    """向时梗备注文件显式写入一条词条（审查 O-05 补写入路径）。

    纪律（详见模块 docstring）：

    - **调用方接线待批**：不自动触发，仅供后续管理员命令/反思链路
      调用；自动学习需另行走 propose→approve 设计评审。
    - 同名词条（strip+casefold 归一后同名）覆盖解释，keep-newest：
      新小节追加到文件尾部，旧小节删除。
    - 新词条使条目数超过 ``max_entries``（默认常量
      ``MAX_TREND_ENTRIES``）时，按文件顺序淘汰最旧（最前）小节。
    - 原子写：先写同目录 ``.tmp``（唯一后缀）再 ``os.replace``；失败
      时清理 tmp 不留残留，原文件不受影响。
    - ``observed_on`` 缺省自动补今天（UTC，``YYYY-MM-DD``）；显式传入
      则必须匹配该格式，否则抛 ``ValueError``（不落半截文件）。

    返回 ``True`` 表示覆盖了已有词条，``False`` 表示新增。
    """
    clean_term = term.strip()
    clean_explanation = explanation.strip()
    if not clean_term or not clean_explanation:
        raise ValueError("trend 词条的 term/explanation 不能为空")
    if observed_on is None:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    else:
        try:
            datetime.strptime(observed_on, "%Y-%m-%d")  # noqa: DTZ007 - 仅校验格式，不取时刻。
        except ValueError as exc:
            raise ValueError(
                f"observed_on 需为 YYYY-MM-DD，收到：{observed_on!r}"
            ) from exc
        date_str = observed_on

    path = Path(notes_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        # 文件不存在/不可读：按空文件起账（与 load 对缺失文件的容忍一致）。
        text = ""

    preamble, sections = _split_markdown_sections(text)
    key = clean_term.casefold()
    kept = [section for name, section in sections if name != key]
    replaced = len(kept) < len(sections)
    if not replaced:
        # 仅新增时受上限约束；覆盖不增条目，无需淘汰。
        # `kept and` 守卫 max_entries<=0 的退化情形（淘汰至空即止，不崩）。
        while kept and len(kept) >= max(0, max_entries):
            kept.pop(0)
    kept.append(
        _render_trend_section(clean_term, clean_explanation, date_str, source)
    )

    parts: list[str] = []
    if preamble.strip():
        parts.append(preamble.strip("\n"))
    parts.extend(section.strip("\n") for section in kept)
    final_text = "\n\n".join(parts) + "\n"

    tmp_path = path.with_name(f"{path.name}.{uuid4().hex[:8]}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(final_text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # 原子写中断/失败：不留 .tmp 残留（源码树与数据目录零垃圾）。
        tmp_path.unlink(missing_ok=True)
        raise
    return replaced

