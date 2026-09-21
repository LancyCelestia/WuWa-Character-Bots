"""紧急信息采集调度器：轮询编排 + 快照缓存 + 幂等落库（COLLECT-1 席）。

本席治的根因（简报「已核实前提」）：现役天气预警支路把 NMC `findAlarm`
（E11 实测冷页 10–25s）内联进用户热路径且失败静默返 `[]` ⇒ 间歇性「无预警」假象。
主会话裁定不做超时化妆修复，正解＝**定时轮询写快照 + 查询路径只读快照**。
本文件是「轮询编排」那一半：`run_collection_once(deps, now=...)` 是纯函数式编排，
真实调度器注册属根装配面（见 report §落地请求）；本模块**绝不 import APScheduler、
绝不 import 取数实现去主动发网络请求于编排体内**（源调用一律经 `SourceTask.fetch` 注入）。

五条硬约束的落点（对应简报「设计硬约束」1–6）：
1. 查询路径只读快照：`get_latest(snapshot, now)` 委托 `snapshot_store.SnapshotStore.latest`，
   四态由快照算出，绝不内联外呼；FAILED 保留上一份条目 ⇒ 冷页超时仍回传上次结果（治好的那条病）。
2. 调度器本体不进域内：只暴露 `run_collection_once` 纯编排 + `build_emergency_collector_deps` 工厂。
3. 失败可见：每源 FAILED 既进快照、又产 **一次** `OperationalIssue`，经注入的
   `AlertSuppression`（正身 `domains/ops/monitor/alerts.py::AdminAlertSuppression`，300s 折叠）
   放行后交 `issue_sink`；`NO_DATA` 不算失败、不告警。**不新建第二套告警体系**——本模块只造
   OperationalIssue + 调注入的抑制器，不 import 任何告警发送实现（服务层纯度 AST 锁）。
4. 落库唯一收口：条目一律 `contracts.build_emergency_item`（缺字段即丢，D-1 不填假值）；
   定级走纯规则 `grading.grade`；本席**绝不直接调 `store.upsert_item`**——B1R3 的结构护栏
   （`tests/test_emergency_info_core.py::test_only_the_review_gate_can_write_items_into_the_store`）
   钉死「唯一写入点是 ReviewGate」。采集器改经注入的 `persist` 回调上交条目，装配期把它接到
   `service/review.py::ReviewGate.submit`（入库即 pending，过审才定级投递，D-8）。投递幂等由
   下游 transport 队列的 dedupe_key 保证，本席不建第二套账（简报「不建第二套账」）。
5. 并发与限额：单轮每源一次调用（重试在 `sources/http_get` 内）；整轮墙钟预算 `budget_seconds`
   注入，超预算放弃**剩余**源并记 FAILED（不调其 fetch），不拖垮调度线程。
6. 幂等：同一时刻重复 `run_collection_once` 不产生重复条目——靠 `store.upsert_item` 的
   `(source_id, external_id)` UNIQUE（`sources/store.py:61-62`）+ 快照整体替换，不建第二套账。

样板坐标（九个统一自证）：编排 = 注入依赖跑一遍、时钟注入、阈值注入的形态抄
`domains/assistant/daily_assist` 与调度族；三态透传与 `SourceOutcome` 消费抄 B2 席
`sources/http_get.py::FetchState`；条目收口抄 B1R3 `contracts.build_emergency_item`；
OperationalIssue 折叠复用抄 `domains/ops/monitor/alerts.py`（R1 v21r2 告警去噪族）。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    OperationalIssue,
    RiskLevel,
)
from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyStatus,
    build_emergency_item,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import (
    alert_taxonomy as taxonomy,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.grading import grade
from plugins.bot_unified_runtime.domains.emergency_info.service.snapshot_store import (
    DEFAULT_MAX_SNAPSHOT_AGE,
    Snapshot,
    SnapshotStore,
    SnapshotView,
    SourceRecordState,
    SourceResult,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources import gdacs, nmc_alarm
from plugins.bot_unified_runtime.domains.emergency_info.sources import (
    open_data_quakes as quakes,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.http_get import (
    FetchState,
    SourceOutcome,
    failed_outcome,
)

#: 告警 stage 常量（唯一，供折叠键与运维识别；不新建第二套 stage 词）。
ISSUE_STAGE = "emergency_info"
#: 采集失败的告警 kind（每源折叠键含 source_id ⇒ 同源 300s 内只发一条）。
ISSUE_KIND = "collect_failed"

#: 整轮墙钟预算保守缺省（秒）：真实值由 config 注入（属 §落地请求），此处仅兜底。
DEFAULT_WALL_CLOCK_BUDGET_SECONDS = 60.0
#: 超预算放弃剩余源时的显式失败原因（诚实标 FAILED，绝不当「无数据」）。
BUDGET_EXCEEDED_REASON = "budget_exceeded"

#: USGS 采集腿的震级门槛（E11 §4 用户裁定的 `min_magnitude=4.0`）。
#:
#: 审计 E6-N1 的直接根修点：装配腿此前绑的是 `fetch_usgs_recent_feed()`
#: ——`all_hour` 全球通道、**零震级门槛**，配上「标题含『地震』即判红」的旧定级，
#: 等于「南极 M0.6 也能在凌晨三点给全群推红色预警」。裁定的
#: `fetch_usgs_quakes(min_magnitude=4.0)`（fdsnws + 中国矩形 + 滚动 24h）在生产零调用。
#: 现在装配腿回到裁定通道；门槛写成模块常量而非 config 键，是因为根装配侧
#: `build_emergency_collector_deps(...)` 的调用形态不传该参数（改根装配文件属另一工作包），
#: 想按环境改数请由工厂形参 `usgs_min_magnitude` 注入——该形参与主会话待落键
#: `bot_emergency_info_usgs_min_magnitude` 的接线写法见 WP3 交接段。
USGS_PUSH_MIN_MAGNITUDE = 4.0


# ---------------------------------------------------------------- 注入协议（依赖倒置，离线可测）


class AlertSuppression(Protocol):
    """300s 折叠抑制最小面：`AdminAlertSuppression.allow` 天然满足（此处只调，不 import 实现）。"""

    def allow(self, key: tuple[object, ...]) -> tuple[bool, int]: ...


Payloads = list[dict[str, Any]]
FetchFn = Callable[[], SourceOutcome[Any]]
PayloadMapper = Callable[[SourceOutcome[Any], datetime], Payloads]


def _noop_issue_sink(issue: OperationalIssue) -> None:
    """未注入告警管道时的静默口：缺省行为=不改变既有（装配前不落任何外发）。"""


def _noop_persist(item: EmergencyItem) -> None:
    """未注入持久门时的静默口：装配期由 `build_*` 之外接到 `ReviewGate.submit`（D-8 唯一写入点）。"""


# ---------------------------------------------------------------- 采集任务与依赖


@dataclass(frozen=True)
class SourceTask:
    """一路采集：注入的取数闭包 + 源侧条目→契约 payload 的纯映射。

    `fetch` 缺省真实实现走 `build_*` 工厂绑定的 `sources/*`（含 SSRF 双闸与退避重试）；
    离线测试注入返回 `SourceOutcome` 的假闭包，`run_collection_once` 全程零真实网络/线程。
    """

    source_id: str
    source_kind: str
    fetch: FetchFn
    to_payloads: PayloadMapper


@dataclass
class CollectorDeps:
    """编排运行所需的全部注入依赖（时钟/阈值/持久门/快照/告警面一律注入，不读全局）。"""

    sources: Sequence[SourceTask]
    snapshot: SnapshotStore
    persist: Callable[[EmergencyItem], None] = _noop_persist
    elapsed: Callable[[], float] = time.monotonic
    budget_seconds: float | None = DEFAULT_WALL_CLOCK_BUDGET_SECONDS
    issue_sink: Callable[[OperationalIssue], None] = _noop_issue_sink
    suppression: AlertSuppression | None = None


@dataclass(frozen=True)
class CollectionReport:
    """一轮采集的确定性产出（供上层记日志/断言，不含任何外发副作用）。"""

    results: tuple[SourceResult, ...]
    snapshot: Snapshot
    stored: int
    dropped: int
    emitted_issues: int


# ---------------------------------------------------------------- 三态映射与告警


def _to_record_state(state: FetchState) -> SourceRecordState:
    if state is FetchState.OK:
        return SourceRecordState.OK
    if state is FetchState.NO_DATA:
        return SourceRecordState.NO_DATA
    return SourceRecordState.FAILED


def _build_issue(outcome: SourceOutcome[Any]) -> OperationalIssue:
    reason = str(outcome.reason or "unknown_failure")
    return OperationalIssue(
        stage=ISSUE_STAGE,
        kind=ISSUE_KIND,
        retryable=True,
        severity=RiskLevel.MEDIUM,
        safe_summary=f"{outcome.source_id}:{reason}"[:200],
        attempts=max(1, int(outcome.attempts)),
    )


def _maybe_alert(
    deps: CollectorDeps, outcome: SourceOutcome[Any]
) -> int:
    """FAILED → 构造 OperationalIssue 经折叠放行后交 issue_sink；返回本次放行条数（0/1）。"""
    if _to_record_state(outcome.state) is not SourceRecordState.FAILED:
        return 0
    issue = _build_issue(outcome)
    if deps.suppression is not None:
        allowed, _count = deps.suppression.allow((ISSUE_STAGE, outcome.source_id, ISSUE_KIND))
        if not allowed:
            return 0
    deps.issue_sink(issue)
    return 1


# ---------------------------------------------------------------- 条目落库（唯一收口）


def _collect_ok_items(
    deps: CollectorDeps, task: SourceTask, outcome: SourceOutcome[Any], now: datetime
) -> tuple[tuple[EmergencyItem, ...], int, int]:
    """把 OK 条目过 `build_emergency_item` 收口 + 纯规则定级 + 幂等落库。

    返回 (入库成功条目元组, upsert 计数含被幂等拒的重跑, 丢弃计数)。「丢弃」＝缺必需字段
    （如无有效发生时间）⇒ 不入库不造假（D-1）。幂等重跑（upsert 返 False）不算丢弃。
    """
    stored = 0
    dropped = 0
    collected: list[EmergencyItem] = []
    for payload in task.to_payloads(outcome, now):
        external_id = str(payload.get("external_id") or "").strip()
        source_id = str(payload.get("source_id") or task.source_id).strip()
        # 连接符用 `-` 不用 `:`：`item_id` 会原样进投递幂等键的一段，而键段字符集
        # （`dedupe._SEGMENT_RE`）显式排除 `:`——`:` 是段的分隔符。此前写 `:` 使
        # **每一条真实条目**在 `deliver_emergency` 抛 ValueError，被 job 的兜底 except
        # 吞成一行日志，紧急信息一条都投不出去（2026-09-20 端到端用例抓到）。
        item_id = f"{source_id}-{external_id}" if external_id else ""
        enriched = dict(payload)
        enriched["item_id"] = item_id
        enriched["fetched_at"] = now
        item = build_emergency_item(enriched)
        if item is None:
            dropped += 1
            continue
        level = grade(item, now=now)
        graded = item.model_copy(
            update={"level": level, "status": EmergencyStatus.APPROVED}
        )
        deps.persist(graded)  # 经注入的持久门上交（装配期接 ReviewGate.submit，D-8 唯一写入点）
        stored += 1
        collected.append(graded)
    return tuple(collected), stored, dropped


# ---------------------------------------------------------------- 主编排


def run_collection_once(
    deps: CollectorDeps, *, now: datetime
) -> CollectionReport:
    """跑一轮：逐源一次调用（超预算弃剩余）→ 收口入库 → 并入快照 → FAILED 折叠告警。

    `now` 为注入时钟（采集时刻与定级/时效一律以此为准，不读全局 config，避开台账 #3/#6 坑）。
    返回 `CollectionReport`；本函数不发任何对外消息，落库/快照/告警均经注入依赖。
    """
    start = deps.elapsed()
    results: list[SourceResult] = []
    stored_total = 0
    dropped_total = 0
    issues_total = 0
    budget_spent = False

    for task in deps.sources:
        if budget_spent or (
            deps.budget_seconds is not None
            and (deps.elapsed() - start) >= float(deps.budget_seconds)
        ):
            budget_spent = True
            outcome = failed_outcome(task.source_id, BUDGET_EXCEEDED_REASON)
        else:
            try:
                outcome = task.fetch()
            except Exception as exc:  # noqa: BLE001 - 取数异常必须变显式 FAILED，绝不冒泡拖垮调度
                outcome = failed_outcome(task.source_id, f"fetch_exception:{type(exc).__name__}")

        record_state = _to_record_state(outcome.state)
        items: tuple[EmergencyItem, ...] = ()
        if record_state is SourceRecordState.OK:
            items, stored, dropped = _collect_ok_items(deps, task, outcome, now)
            stored_total += stored
            dropped_total += dropped
        # NO_DATA：源可达且自报零条＝合法空答案，不入库、不告警（快照记 NO_DATA，
        # 判 FRESH + 空 items＝诚实的「此刻确无预警」，与 FAILED 的「取不到」严格分离）。
        results.append(
            SourceResult(
                source_id=task.source_id,
                state=record_state,
                items=items,
                reason=str(outcome.reason or ""),
            )
        )
        issues_total += _maybe_alert(deps, outcome)

    snapshot = deps.snapshot.record(results, now=now)
    return CollectionReport(
        results=tuple(results),
        snapshot=snapshot,
        stored=stored_total,
        dropped=dropped_total,
        emitted_issues=issues_total,
    )


def get_latest(
    snapshot: SnapshotStore, now: datetime, *, max_age: timedelta | None = None
) -> SnapshotView:
    """查询路径唯一读取口：只读快照、绝不内联外呼（硬约束 #1 的门面）。"""
    return snapshot.latest(now, max_age=max_age)


# ---------------------------------------------------------------- 源侧 payload 映射（纯函数）


def _nmc_pic_signal_code(pic: object) -> str:
    """NMC 图标文件名 → 四位类型码（`p0002003.png` → `0002`）；形态不符返回空串。

    实测形态（真样例 `nmc_findAlarm.sample.json` 300 条逐条核过）：文件名恒为
    `p` + 4 位类型码 + 3 位等级码 + `.png`。等级码刻意**不**在此解析——颜色词已从
    标题解析（`nmc_alarm.split_alarm_title`），两条路各出一个色就会打架。
    """
    name = str(pic or "").rsplit("/", 1)[-1].strip()
    if not name.lower().startswith("p"):
        return ""
    digits = "".join(char for char in name[1:] if char.isdigit())
    return digits[:4] if len(digits) >= 5 else ""


def _nmc_category(alert: object) -> str:
    """一条 NMC 告警 → 注册表类别 id（图码优先，标题别名兜底，认不出留空）。"""
    code = _nmc_pic_signal_code(getattr(alert, "pic", ""))
    by_code = taxonomy.NMC_SIGNAL_TYPE_TO_CATEGORY.get(code, "")
    if by_code:
        return by_code
    return taxonomy.resolve_category(
        f"{getattr(alert, 'kind', '') or ''} {getattr(alert, 'title', '') or ''}",
        source_id=nmc_alarm.SOURCE_ID,
        source_kind="weather_alarm",
    )


def _nmc_payloads(outcome: SourceOutcome[Any], now: datetime) -> Payloads:
    """全国在报预警 → 契约 payload。发生时间缺失**不在此丢**：照原样交给
    `build_emergency_item`（唯一收口）判 None，由采集器计入 dropped（D-1 不造假时间）。"""
    payloads: Payloads = []
    for alert in outcome.items:
        payloads.append(
            {
                # 无 latitude/longitude：NMC 预警接口不给坐标、`qx.json` 码表也没有
                # （2026-09-20 实测 keys=code/province/city/url），订阅的地点判定对
                # 这一源只走标题地名文字匹配——留 None 是"没这个事实"，不是漏填。
                "source_id": nmc_alarm.SOURCE_ID,
                "source_kind": "weather_alarm",
                "external_id": getattr(alert, "alertid", ""),
                "title": getattr(alert, "title", ""),
                "body": "",
                "url": getattr(alert, "detail_url", "") or getattr(alert, "url", ""),
                "color_label": getattr(alert, "color_label", ""),
                "occurred_at": getattr(alert, "issued_at", None),
                "credibility": 0.90,
                "category_id": _nmc_category(alert),
            }
        )
    return payloads


_QUAKE_CREDIBILITY: dict[str, float] = {
    quakes.ICL_SOURCE_ID: 0.70,  # ICL 是 CENC 降级代理源（E11 §6 红线），可信度低于官方直连
    quakes.USGS_SOURCE_ID: 0.85,
}


def _quake_payloads(outcome: SourceOutcome[Any], now: datetime) -> Payloads:
    """地震速报（ICL / USGS 共用形态）→ 契约 payload。

    **没有 `color_label` 这一项**：ICL/USGS 都不给预警色，硬造一个色就是编数。
    定级因此只吃 `magnitude`/`depth_km`/坐标三枚**源侧数值**（`grading.earthquake_level`），
    再也不看标题里有没有「地震」二字——审计 E6-N1「M0.6 南极震判红穿静默窗」的根修点。
    """
    payloads: Payloads = []
    for event in outcome.items:
        source_id = getattr(event, "source_id", "") or ""
        magnitude = getattr(event, "magnitude_display", "") or ""
        epicenter = getattr(event, "epicenter_text", "") or ""
        title = f"{magnitude}级地震" + (f"｜{epicenter}" if epicenter else "")
        depth = getattr(event, "depth_km", None)
        label = getattr(event, "label", "") or source_id
        body = f"来源：{label}；震源深度 {depth if depth is not None else '未知'} km"
        payloads.append(
            {
                "source_id": source_id,
                "source_kind": "earthquake",
                "category_id": taxonomy.EARTHQUAKE_CATEGORY_ID,
                "external_id": getattr(event, "event_id", ""),
                "title": title,
                "body": body,
                "url": getattr(event, "url", "") or "",
                "color_label": "",
                "occurred_at": getattr(event, "origin_at", None),
                "credibility": _QUAKE_CREDIBILITY.get(source_id, 0.60),
                # 订阅侧的半径匹配唯一坐标来源（WIRE-SUB）；半个坐标会被契约层
                # `check_coordinate_pair` 判不成立⇒整条 dropped，不留半个点去算距离。
                "latitude": getattr(event, "latitude", None),
                "longitude": getattr(event, "longitude", None),
                # WP3 定级输入：震级/深度是源侧事实，拿不到就留 None（不猜）。
                "magnitude": getattr(event, "magnitude", None),
                "depth_km": depth,
            }
        )
    return payloads


def _gdacs_payloads(outcome: SourceOutcome[Any], now: datetime) -> Payloads:
    """GDACS 事件 → 契约 payload（背景聚合）；Green/未知等级不映射颜色（D-1）。
    发生时间缺失交 `build_emergency_item` 判 None（唯一收口），不在此丢。

    类别按**事件中文名 + 事件名**在注册表里认（`WF`→野火、`EQ`→地震、`FL`→洪水、
    `TC`→热带气旋都已实测）；认不出留空，不硬套一个"看起来像"的类别。
    """
    payloads: Payloads = []
    for event in outcome.items:
        country = getattr(event, "country", "") or ""
        payloads.append(
            {
                "source_id": gdacs.SOURCE_ID,
                "source_kind": "global_disaster",
                "external_id": getattr(event, "event_id", ""),
                "title": getattr(event, "name", ""),
                "body": f"来源：{gdacs.SOURCE_LABEL}" + (f"；{country}" if country else ""),
                "url": "",
                "color_label": getattr(event, "color_label", "") or "",
                "occurred_at": getattr(event, "from_at", None),
                "credibility": 0.60,
                "latitude": getattr(event, "latitude", None),
                "longitude": getattr(event, "longitude", None),
                "category_id": taxonomy.resolve_category(
                    " ".join(
                        str(value or "")
                        for value in (
                            getattr(event, "event_type_label", ""),
                            getattr(event, "name", ""),
                        )
                    ),
                    source_id=gdacs.SOURCE_ID,
                    source_kind="global_disaster",
                ),
            }
        )
    return payloads


# ---------------------------------------------------------------- 装配工厂（不主动发网络）


def build_emergency_collector_deps(
    *,
    persist: Callable[[EmergencyItem], None] = _noop_persist,
    snapshot: SnapshotStore | None = None,
    max_age: timedelta = DEFAULT_MAX_SNAPSHOT_AGE,
    issue_sink: Callable[[OperationalIssue], None] = _noop_issue_sink,
    suppression: AlertSuppression | None = None,
    elapsed: Callable[[], float] = time.monotonic,
    budget_seconds: float | None = DEFAULT_WALL_CLOCK_BUDGET_SECONDS,
    fetch_nmc: FetchFn | None = None,
    fetch_icl: FetchFn | None = None,
    fetch_usgs: FetchFn | None = None,
    fetch_gdacs: FetchFn | None = None,
    usgs_min_magnitude: float = USGS_PUSH_MIN_MAGNITUDE,
) -> CollectorDeps:
    """装配一轮四源（全国预警清单 / ICL / USGS / GDACS）的依赖。

    工厂本身**不发任何网络请求**：只把 `sources/*` 的真实取数函数绑成注入闭包。
    `fetch_*` 形参允许注入替身（离线冒烟），缺省走真实常量 URL（先过常量白名单再过 SSRF 闸）。
    USGS 腿缺省绑 E11 §4 裁定的 `fetch_usgs_quakes(min_magnitude=4.0)`——门槛理由写在
    `USGS_PUSH_MIN_MAGNITUDE` 上方注释（审计 E6-N1），不再用无门槛的全球 `all_hour` feed。
    `persist` 应由装配期接 `service/review.py::ReviewGate.submit`（D-8 唯一写入点，本席不直调 store）。
    """
    tasks: tuple[SourceTask, ...] = (
        SourceTask(
            source_id=nmc_alarm.SOURCE_ID,
            source_kind="weather_alarm",
            fetch=fetch_nmc or (lambda: nmc_alarm.fetch_nmc_alarms()),
            to_payloads=_nmc_payloads,
        ),
        SourceTask(
            source_id=quakes.ICL_SOURCE_ID,
            source_kind="earthquake",
            fetch=fetch_icl or (lambda: quakes.fetch_icl_earthquakes()),
            to_payloads=_quake_payloads,
        ),
        SourceTask(
            source_id=quakes.USGS_SOURCE_ID,
            source_kind="earthquake",
            fetch=(
                fetch_usgs
                or (lambda: quakes.fetch_usgs_quakes(min_magnitude=usgs_min_magnitude))
            ),
            to_payloads=_quake_payloads,
        ),
        SourceTask(
            source_id=gdacs.SOURCE_ID,
            source_kind="global_disaster",
            fetch=fetch_gdacs or (lambda: gdacs.fetch_gdacs_events()),
            to_payloads=_gdacs_payloads,
        ),
    )
    return CollectorDeps(
        sources=tasks,
        snapshot=snapshot if snapshot is not None else SnapshotStore(max_age=max_age),
        persist=persist,
        elapsed=elapsed,
        budget_seconds=budget_seconds,
        issue_sink=issue_sink,
        suppression=suppression,
    )


__all__ = [
    "BUDGET_EXCEEDED_REASON",
    "DEFAULT_WALL_CLOCK_BUDGET_SECONDS",
    "ISSUE_KIND",
    "ISSUE_STAGE",
    "USGS_PUSH_MIN_MAGNITUDE",
    "AlertSuppression",
    "CollectionReport",
    "CollectorDeps",
    "SourceTask",
    "build_emergency_collector_deps",
    "get_latest",
    "run_collection_once",
]
