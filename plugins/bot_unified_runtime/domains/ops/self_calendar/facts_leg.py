"""更新历史取数口：只读在册叙述文档，代码里不写一份摘要副本。

需求 10 要 bot 知道「自己的更新历史」。本件的口径是**读**，不是**写**：

- 唯一来源 = 仓内在册叙述文档两份：``docs/HANDBOOK.md`` 的 ``## §NN`` 波次标题
  （单一活文档，按 § 编号取最新几段）与 ``AGENTS.md`` 第六部分台账行
  （``| N | **标题**——…``）。
- **禁止**在本文件里手写「最近做了 X」这类摘要文本——那是第二真身，而且几天就过期
  （AGENTS 第一部分规则 10 立的就是这件事）。本件只做「定位 + 取标题 + 截断 + 脱敏」。
- 取不到（文件不在/读不动/一条都没匹配上）⇒ 明说**未接入**，不编一条「暂无更新」。

与既有件的关系（如实报备，避免两条并行的「更新历史」）：
``character/temporal.recent_update_lines`` 读的是 ``git log`` 短哈希 + 提交标题，
面向「代码最近动了什么」；本件读的是叙述文档台账，面向「项目自己怎么记账」。
两者同源不同面，装配时**只该接一条**进 prompt，由主代理裁定。

口径：文本进 prompt 前逐行过 ``render/plain_text.redact_local_secrets``
（台账标题里出现过 ``%TEMP%`` 与盘符路径，铁律 3）。
失败：任何读盘异常 ⇒ 该源回一条「未接入」，不抛、不半截。
配置：零配置键；仓库根由 ``project_root()`` 现走目录上溯，测试可注入 ``root``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_LEDGER_HEADING = re.compile(r"^##\s+§(\d+)([A-Za-z]*)\s+(.+)$")
_AGENTS_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.*)$")
_BOLD_SPAN = re.compile(r"\*\*(.+?)\*\*")

#: 一条台账标题进 prompt 的显示上限。超了**明说另有 N 字未显示**，不静默截断
#: （2026-09-25 真卡评审口径：静默截断＝谎报）。
DEFAULT_MAX_CHARS = 160

NOT_WIRED = "未接入"


def project_root(start: Path | None = None) -> Path | None:
    """上溯找工程根（同时含 ``plugins`` 与 ``docs`` 的那一层）；找不到回 None。

    口径：不数 ``parents[N]`` 的层数——按固定层数数错过一次（层数一变就恒回 None
    ⇒ 整块静默缺席而测试照样绿），锚点法比数层稳。
    """
    here = (start or Path(__file__).resolve()).parent
    for candidate in (here, *here.parents):
        if (candidate / "plugins").is_dir() and (candidate / "docs").is_dir():
            return candidate
    return None


@dataclass(frozen=True)
class LedgerSource:
    """一份叙述文档台账的读取结果（``available=False`` 时``lines`` 是那句「未接入」）。"""

    name: str
    path: str
    available: bool
    lines: tuple[str, ...]


def _clamp(text: str, max_chars: int) -> str:
    """截断并把差额说出来：``……（另有 N 字未显示，全文见该文档）``。"""
    cleaned = " ".join(text.split())
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned
    tail = len(cleaned) - max_chars
    return f"{cleaned[:max_chars].rstrip()}……（另有 {tail} 字未显示，全文见该文档）"


def _redact(text: str) -> str:
    """一行过一遍 ``redact_local_secrets``；真身拿不到就回空串**丢行**。

    口径：台账标题进的是 system prompt（模型可见面），宁可少一行历史，
    也不放行一条没脱敏的盘符路径（铁律 3）。空串由调用方过滤。
    """
    try:
        from plugins.bot_unified_runtime.domains.render.plain_text import (
            redact_local_secrets,
        )
    except Exception:  # noqa: BLE001 - 渲染域不可用：这一行宁可不给
        return ""
    return redact_local_secrets(text)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def handbook_wave_lines(
    root: Path | None = None, *, limit: int = 5, max_chars: int = DEFAULT_MAX_CHARS
) -> LedgerSource:
    """``docs/HANDBOOK.md`` 的 ``## §NN`` 波次标题，按 § 编号取最新 ``limit`` 段。

    口径：编号序而非文件序——文件里 §46 排在 §45 之前，按行序取会拿错「最新」。
    """
    base = root if root is not None else project_root()
    path = (base / "docs" / "HANDBOOK.md") if base is not None else None
    name = "docs/HANDBOOK.md"
    if path is None or not path.is_file():
        return LedgerSource(name, str(path or "(未定位)"), False, (f"更新历史（{name}）：{NOT_WIRED}",))
    text = _read(path)
    if text is None:
        return LedgerSource(name, str(path), False, (f"更新历史（{name}）：{NOT_WIRED}（读不到文件）",))
    entries: list[tuple[tuple[int, str], str]] = []
    for raw in text.splitlines():
        match = _LEDGER_HEADING.match(raw.strip())
        if not match:
            continue
        number, suffix, title = match.group(1), match.group(2), match.group(3)
        entries.append(((int(number), suffix), f"§{number}{suffix} {title}"))
    if not entries:
        return LedgerSource(name, str(path), False, (f"更新历史（{name}）：{NOT_WIRED}（没匹配到账目段）",))
    entries.sort(key=lambda item: item[0])
    newest = entries[-max(1, limit) :][::-1]  # 新的在前：读的人第一眼要看到最近一波
    picked = [f"- 更新历史 {_clamp(title, max_chars)}" for _key, title in newest]
    lines = [line for line in (_redact(item) for item in picked) if line]
    return LedgerSource(name, str(path), bool(lines), tuple(lines) or (f"更新历史（{name}）：{NOT_WIRED}",))


def agents_ledger_lines(
    root: Path | None = None, *, limit: int = 5, max_chars: int = DEFAULT_MAX_CHARS
) -> LedgerSource:
    """``AGENTS.md`` 第六部分台账行的编号 + 标题（取编号最大的 ``limit`` 条）。"""
    base = root if root is not None else project_root()
    path = (base / "AGENTS.md") if base is not None else None
    name = "AGENTS.md 台账"
    if path is None or not path.is_file():
        return LedgerSource(name, str(path or "(未定位)"), False, (f"更新历史（{name}）：{NOT_WIRED}",))
    text = _read(path)
    if text is None:
        return LedgerSource(name, str(path), False, (f"更新历史（{name}）：{NOT_WIRED}（读不到文件）",))
    rows: list[tuple[int, str]] = []
    for raw in text.splitlines():
        match = _AGENTS_ROW.match(raw)
        if not match:
            continue
        number = int(match.group(1))
        rest = match.group(2)
        bold = _BOLD_SPAN.search(rest)
        title = bold.group(1) if bold else rest.split("|")[0]
        rows.append((number, _clamp(title, max_chars)))
    if not rows:
        return LedgerSource(name, str(path), False, (f"更新历史（{name}）：{NOT_WIRED}（没匹配到台账行）",))
    rows.sort(key=lambda item: item[0])
    picked = [
        f"- 台账 #{number} {title}" for number, title in rows[-max(1, limit) :][::-1]
    ]  # 与 HANDBOOK 侧同口径：新的在前
    lines = [line for line in (_redact(item) for item in picked) if line]
    return LedgerSource(name, str(path), bool(lines), tuple(lines) or (f"更新历史（{name}）：{NOT_WIRED}",))


def update_history_lines(
    root: Path | None = None,
    *,
    limit_per_source: int = 5,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[str]:
    """两份在册叙述文档的更新历史合流；任一取不到就在该行写「未接入」。

    口径：本函数**不缓存**——读盘发生在调用方（装配层）选择的时机；
    要 TTL 请在装配层做，别在这里藏一把全局状态。
    """
    lines: list[str] = []
    for source in (
        handbook_wave_lines(root, limit=limit_per_source, max_chars=max_chars),
        agents_ledger_lines(root, limit=limit_per_source, max_chars=max_chars),
    ):
        lines.extend(source.lines)
    return lines
