"""自我历法报：把「此刻 + 四历法 + 更新历史」组装成给模型看的一段话。

需求 10 的读出口。**本件不产生任何新事实**，只做三件已登记件的装配：
``moments.resolve_moments``（四把钟对照）、``calendar_leg.build_calendar_snapshot``
（四历法，全部转调 ``divination/data/multi_calendar`` 真身）、
``facts_leg.update_history_lines``（在册叙述文档的更新历史）。

口径：
- 时刻必须是 aware；日界按**东八区**取历法那一天，并在两把钟不同日时显式点出来；
- 「未探测 / 未接入 / 无源」这三类字样是本件的**契约**，不是兜底装饰：
  缺哪块就说缺哪块，绝不用公历日期顶替藏历月日、也不编一段「最近更新了什么」；
- 输出是**行列表**，交给装配层决定进哪个分区、占多少预算——本件不碰 providers.py。
失败：任一子块抛异常 ⇒ 只丢那一块并留一行诚实说明，其余照出（fail-open，
但绝不 fail 成「看起来完整」）。
配置：``timezone_name`` 由调用方传 ``config.bot_timezone``；本件零新键。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from plugins.bot_unified_runtime.domains.ops.self_calendar.calendar_leg import (
    UNCOMPUTABLE,
    build_calendar_snapshot,
    calendar_compact_lines,
)
from plugins.bot_unified_runtime.domains.ops.self_calendar.facts_leg import (
    update_history_lines,
)
from plugins.bot_unified_runtime.domains.ops.self_calendar.moments import (
    MomentSnapshot,
    resolve_moments,
)


def _utc_line(snapshot: MomentSnapshot) -> str:
    """UTC 那一面钟的绝对时刻（【当前时间】首行报的是配置时区墙钟，不含这一面）。"""
    return (
        f"UTC 时刻：{snapshot.utc.instant.strftime('%Y-%m-%d %H:%M:%S')}"
        f"（{snapshot.utc.offset_label}，日期 {snapshot.utc.day.isoformat()}）"
    )


def _config_zone_line(snapshot: MomentSnapshot) -> str:
    """配置时区（``bot_timezone``）那一面；认不出来时写「未探测」，不硬凑 UTC 日期。"""
    if snapshot.local.recognized:
        return (
            f"配置时区 {snapshot.local.name}："
            f"{snapshot.local.instant.strftime('%H:%M:%S')}"
            f"（{snapshot.local.offset_label}，日期 {snapshot.local.day.isoformat()}）"
        )
    return f"配置时区：未探测（{snapshot.local.note}），日期按 UTC {snapshot.local.day.isoformat()}"


def _calendar_day_line(snapshot: MomentSnapshot) -> str:
    """历法面**按哪一把钟取日**这一件事本身——旧版只在四把钟跨日时才被动露出。"""
    beijing = snapshot.beijing
    return (
        f"历法日界（东八区）：{beijing.day.isoformat()}"
        f" {beijing.instant.strftime('%H:%M:%S')}"
    )


def _system_zone_line(snapshot: MomentSnapshot) -> str:
    """系统本地钟（台账 #6：它与 ``bot_timezone`` 是两把钟）；未注入就说未探测。

    标签只印一次：``system.name`` 的真身已经是「系统本地时区（…标准时间）」
    （``moments.resolve_moments`` 造的这一面自带标签），前面再冠一枚「系统本地时区」
    就出成「系统本地时区 系统本地时区（马来西亚半岛标准时间）：…」。
    这一面的读数**永远是原始系统钟**——它的身份就是「机器自己的钟」，把它也接到
    校时器上，这行标签当场变成谎话（锁在
    ``tests/test_runtime_context_readout_partitions.py`` 第 ⑥ 族）。
    """
    if snapshot.system is None:
        return "系统本地时区：未探测（装配层未注入 system_now）"
    system = snapshot.system
    return (
        f"{system.name}："
        f"{system.instant.strftime('%Y-%m-%d %H:%M:%S')}"
        f"（{system.offset_label}）"
    )


def moment_lines(snapshot: MomentSnapshot) -> list[str]:
    """四把钟对照行（每面一行；拿不到的面写「未探测」）。

    口径：四面各自的措辞**只有一处生产者**（上面四个 ``_*_line``），
    所以命令面（本函数）与对话分区（:func:`clock_comparison_lines`）
    不可能对同一把钟各说一套。
    """
    lines = [_utc_line(snapshot), _config_zone_line(snapshot)]
    lines.append(_calendar_day_line(snapshot))
    lines.append(_system_zone_line(snapshot))
    if snapshot.day_divergence_note:
        lines.append(snapshot.day_divergence_note)
    return lines


def clock_comparison_lines(snapshot: MomentSnapshot) -> list[str]:
    """四把钟里**对话分区尚未覆盖**的那三面：UTC 绝对时刻 / 历法取日 / 系统本地钟。

    为什么是这三面而不是整段 :func:`moment_lines`：【当前时间】分区首行已经报了
    配置时区的日期与墙钟，``character/temporal.time_partition_extras`` 又已经报了
    时区名 + UTC 偏移 + 跨日点名，整段灌进去就是同一个事实在一个分区里说两遍
    （两种措辞并存的 prompt 会教模型挑错的那一套——见
    ``tests/test_time_partition_day_divergence.py::test_prompt_calendar_lines_have_exactly_one_producer``
    在 temporal 那一侧立的同型锁）。
    历法行一个都不在这里出：历法措辞的唯一生产者仍是 temporal 的紧凑四行。
    失败：本函数不吞异常也不读钟——快照由调用方给，拿不到快照就少这几行。
    """
    return [_utc_line(snapshot), _calendar_day_line(snapshot), _system_zone_line(snapshot)]


def self_calendar_report(
    now: datetime | None = None,
    *,
    timezone_name: str = "",
    system_now: datetime | None = None,
    root: Path | None = None,
    include_update_history: bool = True,
    limit_per_source: int = 5,
    include_detail: bool = False,
) -> list[str]:
    """一段自包含的「我现在是什么时候」读出，供装配层进人格上下文。

    参数：``now`` 可注入（测试钉时刻）；缺省取系统钟的 UTC。
    ``timezone_name`` 传 ``config.bot_timezone``；``root`` 只在测试里给 tmp_path。
    ``include_detail=True`` 时追加真身 ``rich_calendar_lines`` 全量明细（更长，
    缺省不出——分区预算的账在装配层，别默认把两千字灌进去）。
    """
    moments = resolve_moments(now, timezone_name=timezone_name, system_now=system_now)
    snapshot = build_calendar_snapshot(moments.calendar_day)
    lines: list[str] = ["【自我历法】", *moment_lines(moments)]
    lines.append(
        f"今天（按东八区日界 {snapshot.day.isoformat()}）的历法面："
        if snapshot.supported
        else f"历法面：{UNCOMPUTABLE}（请求的日子是 {snapshot.day.isoformat()}）"
    )
    lines.extend(calendar_compact_lines(snapshot))
    if include_detail and snapshot.detail_lines:
        lines.append("历法明细（真身 rich_calendar_lines 原句）：")
        lines.extend(f"- {line}" for line in snapshot.detail_lines)
    if include_update_history:
        lines.append("更新历史（读自在册叙述文档，非代码内摘要）：")
        try:
            history = update_history_lines(root, limit_per_source=limit_per_source)
        except Exception as error:  # noqa: BLE001 - 读盘炸了只丢这一节，历法面不受影响
            history = [f"- 更新历史：未接入（读取异常 {type(error).__name__}）"]
        lines.extend(_safe(history))
    return lines


def self_calendar_text(
    now: datetime | None = None,
    *,
    timezone_name: str = "",
    system_now: datetime | None = None,
    root: Path | None = None,
    include_update_history: bool = True,
    limit_per_source: int = 5,
    include_detail: bool = False,
) -> str:
    """``self_calendar_report`` 的整段文本形（装配层要一个 str 时用）。"""
    return "\n".join(
        self_calendar_report(
            now,
            timezone_name=timezone_name,
            system_now=system_now,
            root=root,
            include_update_history=include_update_history,
            limit_per_source=limit_per_source,
            include_detail=include_detail,
        )
    )


def _safe(lines: Sequence[str]) -> list[str]:
    """过滤空行/空串，保证至少有一行诚实说明。"""
    cleaned = [line for line in lines if str(line).strip()]
    return cleaned or ["- 更新历史：未接入（叙述文档没给出行）"]
