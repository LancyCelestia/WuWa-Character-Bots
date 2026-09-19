"""紧急信息采集调度器回归（COLLECT-1 席：轮询编排 + 快照缓存，全离线）。

零网络、零真实线程、零 APScheduler：所有源调用都是注入的假闭包，返回 B2 席的
`SourceOutcome` 三态；时钟/预算/告警抑制/持久门一律注入。SQLite 只写 `tmp_path`
（台账 #1 卫生 + conftest 源码树 `data/` 守卫）。持久化经注入的 `persist` 回调上交
（装配期接 `ReviewGate.submit`——本席绝不直调 `store.upsert_item`，尊重 D-8 唯一写入点护栏）。

覆盖简报「TDD 与验收」点名的六条病，每条都带反证性：
1. 冷页超时 → `FETCH_FAILED` 且查询路径仍返回上一份快照（**这就是治好的那条病**）。
2. `NO_DATA` 与 `FAILED` 不混淆（同为空 items，语义与告警行为相反）。
3. 快照过期语义（`STALE` 保留条目、显式非 FRESH）。
4. 重复运行幂等（真 `EmergencyStore` 的 UNIQUE 不产生重复行，经审核门上交）。
5. 预算耗尽放弃剩余源（后续源不调 fetch、记 FAILED）。
6. 告警只发一次（复用 `AdminAlertSuppression` 300s 折叠）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.collector import (
    BUDGET_EXCEEDED_REASON,
    CollectorDeps,
    SourceTask,
    _nmc_payloads,
    _quake_payloads,
    build_emergency_collector_deps,
    get_latest,
    run_collection_once,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.review import ReviewGate
from plugins.bot_unified_runtime.domains.emergency_info.service.snapshot_store import (
    SnapshotState,
    SnapshotStore,
    SourceRecordState,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.http_get import (
    FetchState,
    SourceOutcome,
    failed_outcome,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.nmc_alarm import (
    SOURCE_ID as NMC_ID,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.nmc_alarm import (
    AlarmAlert,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.open_data_quakes import (
    ICL_SOURCE_ID,
    USGS_SOURCE_ID,
    QuakeEvent,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.store import (
    EmergencyStore,
)
from plugins.bot_unified_runtime.domains.ops.monitor.alerts import AdminAlertSuppression

_NOW = datetime(2026, 9, 20, 3, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    """可编排的单调时钟：测试里手动推 t，模拟冷页耗时/超时窗。"""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


class RecordingSink:
    def __init__(self) -> None:
        self.issues: list[object] = []

    def __call__(self, issue: object) -> None:
        self.issues.append(issue)


class CountingPersist:
    """记录上交条目数（持久门替身；真实装配接 ReviewGate.submit）。"""

    def __init__(self) -> None:
        self.items: list[EmergencyItem] = []

    def __call__(self, item: EmergencyItem) -> None:
        self.items.append(item)


def _alarm(external_id: str, title: str, color: str = "红色") -> AlarmAlert:
    return AlarmAlert(
        alertid=external_id,
        title=title,
        kind="暴雨",
        color_label=color,
        issued_at=_NOW - timedelta(minutes=5),
        issued_text="2026/09/20 02:55",
        url=f"https://www.nmc.cn/publish/alarm/{external_id}.html",
        detail_url=f"https://www.nmc.cn/publish/alarm/{external_id}.html",
        pic="",
    )


def _nmc_ok(*alarms: AlarmAlert) -> SourceOutcome[AlarmAlert]:
    return SourceOutcome(state=FetchState.OK, source_id=NMC_ID, items=tuple(alarms))


def _nmc_no_data() -> SourceOutcome[AlarmAlert]:
    return SourceOutcome(
        state=FetchState.NO_DATA, source_id=NMC_ID, reason="no_alarm_in_report"
    )


def _nmc_failed(reason: str = "http_error:TimeoutError") -> SourceOutcome[AlarmAlert]:
    return failed_outcome(NMC_ID, reason, attempts=2)


def _deps(
    snapshot: SnapshotStore,
    *,
    sources: list[SourceTask],
    sink: RecordingSink | None = None,
    persist: object | None = None,
    suppression: AdminAlertSuppression | None = None,
    clock: FakeClock | None = None,
    budget: float | None = None,
) -> CollectorDeps:
    return CollectorDeps(
        sources=sources,
        snapshot=snapshot,
        persist=persist or _noop,  # type: ignore[arg-type]
        elapsed=clock or FakeClock(0.0),
        budget_seconds=budget,
        issue_sink=sink or RecordingSink(),
        suppression=suppression,
    )


def _noop(item: EmergencyItem) -> None:
    return None


def _task(
    fetch, *, source_id: str = NMC_ID, source_kind: str = "weather_alarm"
) -> SourceTask:
    return SourceTask(
        source_id=source_id,
        source_kind=source_kind,
        fetch=fetch,
        to_payloads=_quake_payloads if source_kind == "earthquake" else _nmc_payloads,
    )


# ---------------------------------------------------------------- 1 冷页超时→FETCH_FAILED 仍回传旧快照


def test_cold_page_timeout_keeps_previous_snapshot() -> None:
    """治病实证：第一轮拿到数据 → 第二轮冷页超时 FAILED → 查询路径仍拿到上一份条目、
    且状态显式为 FETCH_FAILED（绝不是「无预警」）。"""
    snapshot = SnapshotStore(max_age=timedelta(minutes=30))
    holder: dict[str, SourceOutcome[AlarmAlert]] = {
        "outcome": _nmc_ok(_alarm("A1", "某某县发布暴雨红色预警信号"))
    }
    deps = _deps(snapshot, sources=[_task(lambda: holder["outcome"])])

    run_collection_once(deps, now=_NOW)
    first = get_latest(snapshot, _NOW)
    assert first.state is SnapshotState.FRESH and len(first.items) == 1

    holder["outcome"] = _nmc_failed("http_error:TimeoutError")
    run_collection_once(deps, now=_NOW + timedelta(minutes=10))
    second = get_latest(snapshot, _NOW + timedelta(minutes=10))

    assert second.state is SnapshotState.FETCH_FAILED
    assert second.has_visible_data, "取数失败不得清空上一份快照（否则重演「无预警」假象）"
    assert {item.external_id for item in second.items} == {"A1"}


# ---------------------------------------------------------------- 2 NO_DATA ≠ FAILED


def test_no_data_is_fresh_empty_but_failed_is_degraded() -> None:
    """同为空 items：NO_DATA＝合法「此刻确无预警」→ FRESH + 不告警；
    FAILED＝取不到 → FETCH_FAILED + 告警。两者绝不混为一谈。"""
    sink_no_data = RecordingSink()
    snapshot = SnapshotStore()
    deps = _deps(
        snapshot, sources=[_task(lambda: _nmc_no_data())], sink=sink_no_data
    )
    run_collection_once(deps, now=_NOW)
    view = get_latest(snapshot, _NOW)
    assert view.state is SnapshotState.FRESH
    assert view.items == ()
    assert view.sources[0].state is SourceRecordState.NO_DATA
    assert sink_no_data.issues == [], "NO_DATA 不算失败、不得告警"

    sink_failed = RecordingSink()
    snapshot2 = SnapshotStore()
    deps2 = _deps(
        snapshot2,
        sources=[_task(lambda: _nmc_failed("source_error:code=1"))],
        sink=sink_failed,
    )
    run_collection_once(deps2, now=_NOW)
    view2 = get_latest(snapshot2, _NOW)
    assert view2.state is SnapshotState.FETCH_FAILED
    assert view2.items == ()  # 从没成功过，无可保留——但仍不是「无预警」
    assert len(sink_failed.issues) == 1, "FAILED 必须挂一次 OperationalIssue"


# ---------------------------------------------------------------- 3 快照过期→STALE


def test_snapshot_expires_to_stale() -> None:
    snapshot = SnapshotStore(max_age=timedelta(minutes=30))
    deps = _deps(
        snapshot, sources=[_task(lambda: _nmc_ok(_alarm("A1", "大雾黄色预警信号")))]
    )
    run_collection_once(deps, now=_NOW)
    fresh = get_latest(snapshot, _NOW + timedelta(minutes=5))
    assert fresh.state is SnapshotState.FRESH
    stale = get_latest(snapshot, _NOW + timedelta(hours=2))
    assert stale.state is SnapshotState.STALE
    assert stale.has_visible_data, "过期仍回传上次条目，交上层显式标注数据已旧"


def test_never_fetched_is_explicit() -> None:
    view = get_latest(SnapshotStore(), _NOW)
    assert view.state is SnapshotState.NEVER_FETCHED
    assert view.items == ()


# ---------------------------------------------------------------- 4 重复运行幂等


def test_repeated_run_is_idempotent(tmp_path) -> None:
    """经审核门上交：重复轮询不得在库中产生重复行（store 的 UNIQUE 才是幂等唯一执行点）。"""
    store = EmergencyStore(tmp_path / "emg.sqlite3")
    gate = ReviewGate(store)
    snapshot = SnapshotStore()
    deps = _deps(
        snapshot,
        sources=[_task(lambda: _nmc_ok(_alarm("A1", "暴雨橙色预警信号")))],
        persist=gate.submit,
    )
    run_collection_once(deps, now=_NOW)
    run_collection_once(deps, now=_NOW)
    rows = store.list_by_status(EmergencyStatus.PENDING, limit=50)
    assert len(rows) == 1, "同一时刻重复轮询不得产生重复条目（审核门上交 + UNIQUE 幂等）"
    assert len(get_latest(snapshot, _NOW).items) == 1


# ---------------------------------------------------------------- 5 预算耗尽弃剩余源


def test_budget_exhausted_abandons_remaining_sources() -> None:
    snapshot = SnapshotStore()
    clock = FakeClock(0.0)
    b_calls = {"n": 0}

    def slow_ok() -> SourceOutcome[AlarmAlert]:
        clock.t += 100.0  # 模拟冷页 100s 才回
        return _nmc_ok(_alarm("A1", "台风红色预警信号"))

    def never_called() -> SourceOutcome[AlarmAlert]:
        b_calls["n"] += 1
        return _nmc_ok(_alarm("B1", "无关"))

    deps = _deps(
        snapshot,
        sources=[_task(slow_ok, source_id="a"), _task(never_called, source_id="b")],
        clock=clock,
        budget=10.0,
    )
    report = run_collection_once(deps, now=_NOW)
    by_source = {r.source_id: r for r in report.results}
    assert by_source["a"].state is SourceRecordState.OK
    assert by_source["b"].state is SourceRecordState.FAILED
    assert by_source["b"].reason == BUDGET_EXCEEDED_REASON
    assert b_calls["n"] == 0, "超预算后剩余源绝不再调 fetch（不拖垮调度线程）"
    assert by_source["b"].items == ()


# ---------------------------------------------------------------- 6 告警 300s 只发一次


def test_failed_alert_suppressed_within_window() -> None:
    snapshot = SnapshotStore()
    sink = RecordingSink()
    clock = FakeClock(1000.0)
    suppression = AdminAlertSuppression(window_seconds=300.0, clock=clock)
    deps = _deps(
        snapshot,
        sources=[_task(lambda: _nmc_failed("http_error:TimeoutError"))],
        sink=sink,
        suppression=suppression,
        clock=clock,
    )
    run_collection_once(deps, now=_NOW)
    run_collection_once(deps, now=_NOW + timedelta(seconds=60))
    assert len(sink.issues) == 1, "同源 300s 窗口内折叠，只打扰一次"
    clock.t += 301.0
    run_collection_once(deps, now=_NOW + timedelta(minutes=7))
    assert len(sink.issues) == 2, "窗口结束后新故障可再告警"


# ---------------------------------------------------------------- 收口/定级/装配


def test_ok_items_are_built_graded_and_handed_to_persist() -> None:
    snapshot = SnapshotStore()
    persist = CountingPersist()
    deps = _deps(
        snapshot,
        sources=[
            _task(lambda: _nmc_ok(_alarm("A1", "某某县气象台发布暴雨红色预警信号")))
        ],
        persist=persist,
    )
    report = run_collection_once(deps, now=_NOW)
    assert report.stored == 1
    assert len(persist.items) == 1
    handed = persist.items[0]
    assert handed.item_id == f"{NMC_ID}:A1"
    assert handed.level is EmergencyLevel.P0  # 红色 → P0（D-3 颜色序位）
    # 查询路径（快照）读到已定级条目
    view = get_latest(snapshot, _NOW)
    assert view.items[0].level is EmergencyLevel.P0


def test_missing_occurred_time_is_dropped_not_fabricated() -> None:
    """D-1：发生时间解析不出的告警条目直接丢，绝不造 1970 或假时间凑数。"""
    bad = _alarm("A9", "某某县发布大雾黄色预警信号")
    bad = AlarmAlert(**{**bad.__dict__, "issued_at": None})  # frozen: 用 dict 重建
    snapshot = SnapshotStore()
    persist = CountingPersist()
    deps = _deps(
        snapshot,
        sources=[_task(lambda: _nmc_ok(bad))],
        persist=persist,
    )
    report = run_collection_once(deps, now=_NOW)
    assert report.dropped == 1
    assert persist.items == []


def test_quake_item_graded_p0_via_keyword() -> None:
    snapshot = SnapshotStore()
    event = QuakeEvent(
        source_id=ICL_SOURCE_ID,
        event_id="98395394",
        origin_at=_NOW - timedelta(minutes=2),
        magnitude=3.9,
        mag_type="",
        depth_km=8.0,
        epicenter_text="四川宜宾长宁县",
        latitude=28.5,
        longitude=104.9,
        updates=5,
        station_count=6,
        url="",
        status="",
        label="ICL（中国地震预警网联盟）",
    )
    task = _task(
        lambda: SourceOutcome(
            state=FetchState.OK, source_id=ICL_SOURCE_ID, items=(event,)
        ),
        source_id=ICL_SOURCE_ID,
        source_kind="earthquake",
    )
    deps = _deps(snapshot, sources=[task])
    run_collection_once(deps, now=_NOW)
    item = get_latest(snapshot, _NOW).items[0]
    assert item.level is EmergencyLevel.P0  # 正文含「地震」→ P0
    assert item.source_kind == "earthquake"
    assert item.source_id == ICL_SOURCE_ID


def test_build_factory_wires_four_sources_without_network() -> None:
    deps = build_emergency_collector_deps()
    assert len(deps.sources) == 4
    assert {t.source_id for t in deps.sources} == {
        NMC_ID,
        ICL_SOURCE_ID,
        USGS_SOURCE_ID,
        "gdacs",
    }
    assert all(callable(t.fetch) for t in deps.sources)
    assert all(callable(t.to_payloads) for t in deps.sources)
