"""紧急信息「最近一轮快照」缓存（COLLECT-1 席：供查询路径读，绝不直打外呼）。

为什么需要这一层（本席唯一的产品级理由）：现役天气预警支路
`domains/weather/capabilities/weather.py:155-190` 把取数直接内联进用户热路径，
E11 实锤 NMC `findAlarm` 冷页 10–25s 且失败静默返 `[]` ⇒ 间歇性「无预警」假象。
主会话裁定：**不做超时化妆修复**，正解＝定时轮询写快照 + 用户路径只读快照。
本文件就是那份「只读快照」的载体——它不 import 任何取数/HTTP/告警实现，
纯粹是内存里的最近一轮结果 + 新鲜度判定。

四态语义（硬约束 #1，绝不含糊）：
- `NEVER_FETCHED` 一轮都没跑过；
- `FRESH` 最近一轮拿到了可信结果（含 NO_DATA＝「确认此刻无预警」）且在时效窗内；
- `STALE` 最近一轮成功、但距今超过注入的 `max_age`（数据旧，仍回传）；
- `FETCH_FAILED` **最近一轮所有源都取数失败**（冷页超时 / 结构塌陷）——
  此时快照仍**保留上一轮的条目**回传给查询路径，并显式标注本轮失败，
  这样上层可以说「取数失败，先显示上次结果」而**绝不是**「没有预警」。

`NO_DATA` 与 `FAILED` 的分野在这里是结构性的：前者是「源可达、自报零条」＝
合法当前答案（`SourceRecordState.NO_DATA`，计入可信轮、可判 FRESH）；后者是
「取不到」＝不可信（`SourceRecordState.FAILED`，不计入可信轮、保留旧数据）。
把两者都收敛成「空列表」正是现役支路的病灶，本模块不许重演。

样板坐标（九个统一自证）：
- 纯内存 + `threading.Lock` 的进程内缓存形态抄 `character/history.py` 的
  线程安全环形缓冲；本席零 SQLite（持久层在 `sources/store.py`，已交付）。
- 时间归一统一走 `contracts.as_utc`（naive 一律当 UTC，不猜本地时区），
  新鲜度阈值为**注入参数**（台账 #3 装配期快照 config 老坑 ⇒ 不读全局 config）。
- 状态枚举形态抄 `sources/http_get.py::FetchState`（str, Enum），但不 import 该模块
  （服务层不牵入取数面，见 `tests/test_emergency_info_core.py` 内核纯度 AST 锁）。
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    as_utc,
)

# 缺省新鲜度窗：仅当装配未注入阈值时的保守兜底（真实值由 config 注入，属 §落地请求）。
DEFAULT_MAX_SNAPSHOT_AGE = timedelta(minutes=30)


class SnapshotState(str, Enum):
    """查询路径读快照得到的四态结论（硬约束 #1 唯一事实源）。"""

    FRESH = "fresh"
    STALE = "stale"
    NEVER_FETCHED = "never_fetched"
    FETCH_FAILED = "fetch_failed"


class SourceRecordState(str, Enum):
    """单源在快照里的状态；语义逐字对齐 `http_get.FetchState`（此处不 import 以免牵入取数面）。"""

    OK = "ok"
    NO_DATA = "no_data"
    FAILED = "failed"


@dataclass(frozen=True)
class SourceSnapshot:
    """一个采集源在快照中的记录。

    `items` 在 `FAILED` 时是**上一轮保留的旧数据**（可能是空元组——从没成功过），
    绝非「本轮清空」；`fetched_at` 是本记录最后一次拿到可信结果的瞬间，
    `failed_at` 是最近一次失败的瞬间（两者一起支撑「上次好 / 这次坏」的诚实标注）。
    """

    source_id: str
    state: SourceRecordState
    items: tuple[EmergencyItem, ...] = ()
    reason: str = ""
    fetched_at: datetime | None = None
    failed_at: datetime | None = None

    @property
    def has_data(self) -> bool:
        return bool(self.items)


@dataclass(frozen=True)
class SourceResult:
    """采集器交给快照的单源本轮结论（对 `SourceOutcome` 的服务层投影，零取数依赖）。"""

    source_id: str
    state: SourceRecordState
    items: tuple[EmergencyItem, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class Snapshot:
    """一轮采集合并后的不可变快照。"""

    last_round_at: datetime
    last_good_round_at: datetime | None
    round_failed: bool
    sources: Mapping[str, SourceSnapshot]
    items: tuple[EmergencyItem, ...]

    def state_at(self, now: datetime, *, max_age: timedelta) -> SnapshotState:
        """按「本轮是否全败 → 距上次可信轮多久」算出四态（round_failed 优先于 STALE）。"""
        if self.round_failed:
            return SnapshotState.FETCH_FAILED
        good = self.last_good_round_at
        if good is None or (as_utc(now) - as_utc(good)) > max_age:
            return SnapshotState.STALE
        return SnapshotState.FRESH


@dataclass(frozen=True)
class SnapshotView:
    """查询路径拿到的读结果（含状态与保留条目；调用方据 `state` 决定文案，不得只看 items 空不空）。"""

    state: SnapshotState
    items: tuple[EmergencyItem, ...]
    sources: tuple[SourceSnapshot, ...]
    last_round_at: datetime | None

    @property
    def is_degraded(self) -> bool:
        """非 FRESH 一律视为降级（上层须显式区分处理，不得当「无预警」）。"""
        return self.state is not SnapshotState.FRESH

    @property
    def has_visible_data(self) -> bool:
        return bool(self.items)


def _merge_sources(
    previous: Mapping[str, SourceSnapshot],
    results: Sequence[SourceResult],
    now: datetime,
) -> tuple[dict[str, SourceSnapshot], bool]:
    """把本轮结论并进旧快照：OK/NO_DATA 覆盖，FAILED 保留旧条目并打失败标。

    返回 (合并后的源表, 本轮是否产出可信结果)。「本轮无数据产出」＝所有参与源都 FAILED，
    这是判 `FETCH_FAILED` 的唯一依据；未在本轮出现的旧源原样保留（不因某轮只查子集而丢数据）。
    """
    combined: dict[str, SourceSnapshot] = dict(previous)
    round_produced_data = False
    for result in results:
        old = combined.get(result.source_id)
        if result.state is SourceRecordState.OK:
            combined[result.source_id] = SourceSnapshot(
                source_id=result.source_id,
                state=SourceRecordState.OK,
                items=result.items,
                reason=result.reason,
                fetched_at=now,
            )
            round_produced_data = True
        elif result.state is SourceRecordState.NO_DATA:
            combined[result.source_id] = SourceSnapshot(
                source_id=result.source_id,
                state=SourceRecordState.NO_DATA,
                items=(),
                reason=result.reason,
                fetched_at=now,
            )
            round_produced_data = True
        else:  # FAILED：保留上一份条目，绝不清空
            combined[result.source_id] = SourceSnapshot(
                source_id=result.source_id,
                state=SourceRecordState.FAILED,
                items=old.items if old is not None else (),
                reason=result.reason,
                fetched_at=old.fetched_at if old is not None else None,
                failed_at=now,
            )
    return combined, round_produced_data


class SnapshotStore:
    """进程内最近一轮快照：采集器写、查询路径读；线程安全，零外呼、零网络、零 SQLite。"""

    def __init__(self, *, max_age: timedelta = DEFAULT_MAX_SNAPSHOT_AGE) -> None:
        self._max_age = max_age
        self._snapshot: Snapshot | None = None
        self._lock = threading.Lock()

    @property
    def max_age(self) -> timedelta:
        return self._max_age

    def record(self, results: Sequence[SourceResult], *, now: datetime) -> Snapshot:
        """并入一轮采集结论并替换快照（原子）。返回新快照，便于调用方断言。"""
        moment = as_utc(now)
        with self._lock:
            previous = self._snapshot
            previous_sources = previous.sources if previous is not None else {}
            previous_good = previous.last_good_round_at if previous is not None else None
            merged, produced_data = _merge_sources(previous_sources, results, moment)
            items = tuple(item for snap in merged.values() for item in snap.items)
            snapshot = Snapshot(
                last_round_at=moment,
                last_good_round_at=moment if produced_data else previous_good,
                round_failed=not produced_data,
                sources=merged,
                items=items,
            )
            self._snapshot = snapshot
            return snapshot

    def snapshot(self) -> Snapshot | None:
        with self._lock:
            return self._snapshot

    def latest(
        self, now: datetime, *, max_age: timedelta | None = None
    ) -> SnapshotView:
        """查询路径唯一读取口：只读快照、绝不内联外呼；四态在此算出。"""
        window = max_age if max_age is not None else self._max_age
        with self._lock:
            current = self._snapshot
        if current is None:
            return SnapshotView(
                state=SnapshotState.NEVER_FETCHED,
                items=(),
                sources=(),
                last_round_at=None,
            )
        return SnapshotView(
            state=current.state_at(now, max_age=window),
            items=current.items,
            sources=tuple(current.sources.values()),
            last_round_at=current.last_round_at,
        )


__all__ = [
    "DEFAULT_MAX_SNAPSHOT_AGE",
    "Snapshot",
    "SnapshotState",
    "SnapshotStore",
    "SnapshotView",
    "SourceRecordState",
    "SourceResult",
    "SourceSnapshot",
]
