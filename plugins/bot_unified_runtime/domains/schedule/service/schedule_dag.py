"""S11 日程链确定性核心——模型层与 DAG 校验（V2.1 §4）。

职责边界：
- 只做确定性计算（模型/拓扑/最早可行窗口）；LLM 草稿解析、课表截图识别、
  真实投递均不在本层（见 docs/design/v21-s11-schedule-log.md 遗留项）。
- 时间一律 UTC 存储、IANA 时区展示；本模块只存 IANA 名（zoneinfo 解析在
  schedule_rrule.py）。
- 错误码对齐 contracts/errors.py 已注册码：schedule_cycle / schedule_conflict /
  version_conflict / occurrence_expired / missing_calendar / ambiguous_local_time。
  本模块额外定义两个本地确定性码 plan_limit_exceeded / unknown_edge_endpoint
  （尚未入全局注册表，投递层映射前先原样暴露，见日志遗留项）。

模型（pydantic StrictBaseModel，风格对齐 contracts/runtime.py）：
    SchedulePlan(owner, timezone, revision, state)
      ├─ TaskTemplate(kind=fixed_time|duration|relative_to_start|relative_to_finish)
      ├─ DependencyEdge(predecessor, relation, offset_seconds, failure_policy)
      ├─ RecurrenceRule(once|daily|weekly|weekly_by_day|teaching_week)
      ├─ ReminderPolicy(默认前 10 分钟+准点；单实例 ≤4 条 offset)
      └─ Occurrence（物化产物，occurrence_id=hash(rule_id, rule_revision, at)）
"""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_MAX_TASKS = 100
DEFAULT_MAX_EDGES = 300
MAX_REMINDER_OFFSETS = 4
DEFAULT_REMINDER_OFFSETS_MINUTES = (-10, 0)

# DAG 校验通过的附加产出上限（防呆，与 store/expand 的 ≤1000 实例相互独立）。
TOPOLOGY_ORDER_MAX = DEFAULT_MAX_TASKS


class StrictModel(BaseModel):
    """模型基类：禁未知字段（风格对齐 contracts/runtime.StrictBaseModel）。"""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class ScheduleErrorCode:
    """本席产生的错误码常量（注册态见 contracts/errors.py）。"""

    SCHEDULE_CYCLE = "schedule_cycle"
    SCHEDULE_CONFLICT = "schedule_conflict"
    VERSION_CONFLICT = "version_conflict"
    OCCURRENCE_EXPIRED = "occurrence_expired"
    MISSING_CALENDAR = "missing_calendar"
    AMBIGUOUS_LOCAL_TIME = "ambiguous_local_time"
    # 本地确定性码（未入全局注册表，见模块 docstring）。
    PLAN_LIMIT_EXCEEDED = "plan_limit_exceeded"
    UNKNOWN_EDGE_ENDPOINT = "unknown_edge_endpoint"


class ScheduleError(Exception):
    """带错误码的日程异常；code 对齐 contracts/errors.py 命名。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class TaskKind(str, Enum):
    FIXED_TIME = "fixed_time"
    DURATION = "duration"
    RELATIVE_TO_START = "relative_to_start"
    RELATIVE_TO_FINISH = "relative_to_finish"


class EdgeRelation(str, Enum):
    FINISH_TO_START = "finish_to_start"
    START_TO_START = "start_to_start"
    FINISH_TO_FINISH = "finish_to_finish"
    START_TO_FINISH = "start_to_finish"


class FailurePolicy(str, Enum):
    """前置失败时后继怎么办：block=阻断；warn=照排但提醒风险。"""

    BLOCK = "block"
    WARN = "warn"


class TaskTemplate(StrictModel):
    task_id: str
    title: str
    kind: TaskKind = TaskKind.DURATION
    # duration / relative 任务的时长（分钟，>0）。
    duration_minutes: int | None = Field(default=None, ge=0)
    # relative_to_* 任务的锚任务。
    anchor_task_id: str | None = None
    # relative_to_* 相对锚点的偏移（分钟，可为负）。
    offset_minutes: int = 0
    # fixed_time 任务的本地时刻 "HH:MM"（日期由所属规则给出）。
    fixed_local_time: str | None = None
    # >0 = 软时间窗（分钟）：允许重算并给差异预览；0 = 硬预约不许静默顺延。
    soft_window_minutes: int = Field(default=0, ge=0)
    # 语义标签（如 "rush" 抢票/抢课类 → 过期即 occurrence_expired）。
    tags: list[str] = Field(default_factory=list)

    @field_validator("task_id", "title")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task_id/title must be non-blank")
        return value.strip()

    @model_validator(mode="after")
    def _validate_shape(self) -> TaskTemplate:
        if self.kind in (
            TaskKind.DURATION,
            TaskKind.RELATIVE_TO_START,
            TaskKind.RELATIVE_TO_FINISH,
        ) and self.duration_minutes is None:
            raise ValueError(f"task {self.task_id}: duration_minutes is required for kind={self.kind.value}")
        if self.kind in (TaskKind.RELATIVE_TO_START, TaskKind.RELATIVE_TO_FINISH):
            if not self.anchor_task_id:
                raise ValueError(f"task {self.task_id}: anchor_task_id is required for kind={self.kind.value}")
            if self.anchor_task_id == self.task_id:
                raise ValueError(f"task {self.task_id}: cannot anchor to itself")
        if self.kind is TaskKind.FIXED_TIME and not self.fixed_local_time:
            raise ValueError(f"task {self.task_id}: fixed_local_time is required for kind=fixed_time")
        if self.fixed_local_time is not None:
            _parse_hhmm(self.fixed_local_time, field="fixed_local_time")
        return self

    @property
    def is_hard(self) -> bool:
        return self.soft_window_minutes == 0

    @property
    def is_rush(self) -> bool:
        return "rush" in self.tags


class DependencyEdge(StrictModel):
    edge_id: str
    predecessor: str
    successor: str
    relation: EdgeRelation = EdgeRelation.FINISH_TO_START
    offset_seconds: int = 0
    failure_policy: FailurePolicy = FailurePolicy.BLOCK

    @field_validator("edge_id", "predecessor", "successor")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("edge fields must be non-blank")
        return value.strip()


class RuleKind(str, Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"  # 每周同一天（锚定 start_date 的星期）
    WEEKLY_BY_DAY = "weekly_by_day"  # 指定周几（可多选）
    TEACHING_WEEK = "teaching_week"  # 单双教学周（weekdays + parity 相对学期起点）


class WeekParity(str, Enum):
    ODD = "odd"  # 单周
    EVEN = "even"  # 双周


class RecurrenceRule(StrictModel):
    rule_id: str
    task_id: str
    kind: RuleKind = RuleKind.ONCE
    rule_revision: int = Field(default=1, ge=1)
    # 起始日期（计划时区下的本地日）。teaching_week 的单双以它（或
    # parity_anchor_date）所在周为第 1 周。
    start_date: str  # ISO "YYYY-MM-DD"（pydantic date 在 SQLite 侧来回不便，统一 str）
    end_date: str | None = None
    local_time: str  # "HH:MM"
    weekdays: list[int] = Field(default_factory=list)  # 0=周一 … 6=周日
    week_parity: WeekParity | None = None  # teaching_week 必填
    # 学期起点（教学周锚）；缺省用 start_date。
    parity_anchor_date: str | None = None

    @field_validator("rule_id", "task_id")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rule fields must be non-blank")
        return value.strip()

    @model_validator(mode="after")
    def _validate_shape(self) -> RecurrenceRule:
        _parse_hhmm(self.local_time, field="local_time")
        _parse_iso_date(self.start_date, field="start_date")
        if self.end_date is not None:
            _parse_iso_date(self.end_date, field="end_date")
            if self.end_date < self.start_date:
                raise ValueError(f"rule {self.rule_id}: end_date before start_date")
        if self.kind in (RuleKind.WEEKLY_BY_DAY, RuleKind.TEACHING_WEEK):
            if not self.weekdays:
                raise ValueError(f"rule {self.rule_id}: weekdays required for kind={self.kind.value}")
            if any(w < 0 or w > 6 for w in self.weekdays):
                raise ValueError(f"rule {self.rule_id}: weekdays must be 0..6 (Mon..Sun)")
        if self.kind is RuleKind.TEACHING_WEEK and self.week_parity is None:
            raise ValueError(f"rule {self.rule_id}: week_parity required for teaching_week")
        if self.kind is not RuleKind.TEACHING_WEEK and self.week_parity is not None:
            raise ValueError(f"rule {self.rule_id}: week_parity only valid for teaching_week")
        return self


class ReminderPolicy(StrictModel):
    """提醒策略：默认开始前 10 分钟 + 准点；单实例 ≤4 条 offset。

    offsets_minutes 负值 = 提前。urgent=True 的事件可穿 QuietHours（硬时点
    例外须显式批准并可查询，查询面在 schedule_service）。
    """

    offsets_minutes: tuple[int, ...] = DEFAULT_REMINDER_OFFSETS_MINUTES
    urgent: bool = False
    # 安静时间行为：defer=延后到安静结束；send=显式批准的硬时点例外。
    quiet_hours_behavior: str = "defer"
    # 错过策略：skip / send_once / digest / ask。grace_minutes 内按
    # send_once 补发；超出按 digest（service.reconcile_missed 实现细则）。
    missed_policy: str = "send_once"
    grace_minutes: int = Field(default=15, ge=0)

    @field_validator("offsets_minutes")
    @classmethod
    def _cap_offsets(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(value) > MAX_REMINDER_OFFSETS:
            raise ValueError(f"at most {MAX_REMINDER_OFFSETS} reminder offsets per occurrence")
        return value

    @field_validator("quiet_hours_behavior")
    @classmethod
    def _quiet_behavior(cls, value: str) -> str:
        if value not in ("defer", "send"):
            raise ValueError("quiet_hours_behavior must be defer|send")
        return value

    @field_validator("missed_policy")
    @classmethod
    def _missed_policy(cls, value: str) -> str:
        if value not in ("skip", "send_once", "digest", "ask"):
            raise ValueError("missed_policy must be skip|send_once|digest|ask")
        return value


class QuietHours(StrictModel):
    """安静时间窗（本地时刻 "HH:MM"，支持跨午夜）。"""

    start: str = "23:00"
    end: str = "07:00"

    @model_validator(mode="after")
    def _validate(self) -> QuietHours:
        _parse_hhmm(self.start, field="start")
        _parse_hhmm(self.end, field="end")
        return self


class Occurrence(StrictModel):
    """物化实例。occurrence_id=hash(rule_id, rule_revision, scheduled_at_utc)
    → 同一规则版本同一时刻重复导入天然幂等。"""

    occurrence_id: str
    plan_id: str
    rule_id: str
    rule_revision: int
    task_id: str
    title: str
    scheduled_at_utc: str  # ISO UTC（pydantic datetime 与 SQLite 往返易丢 tz，统一 str）
    duration_minutes: int = 0
    tags: list[str] = Field(default_factory=list)

    @property
    def is_rush(self) -> bool:
        return "rush" in self.tags


class SchedulePlan(StrictModel):

    plan_id: str
    owner: str
    timezone: str  # IANA 名；解析合法性在 model_validator 校验
    revision: int = Field(default=1, ge=1)
    state: str = "draft"  # draft|active|paused|archived
    tasks: list[TaskTemplate] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    rules: list[RecurrenceRule] = Field(default_factory=list)
    reminder_policy: ReminderPolicy = Field(default_factory=ReminderPolicy)
    quiet_hours: QuietHours = Field(default_factory=QuietHours)

    @field_validator("plan_id", "owner")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("plan_id/owner must be non-blank")
        return value.strip()

    @field_validator("state")
    @classmethod
    def _valid_state(cls, value: str) -> str:
        if value not in ("draft", "active", "paused", "archived"):
            raise ValueError("state must be draft|active|paused|archived")
        return value

    @model_validator(mode="after")
    def _validate_timezone(self) -> SchedulePlan:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone: {self.timezone}") from exc
        return self

    def task_by_id(self, task_id: str) -> TaskTemplate | None:
        return self._task_index().get(task_id)

    def _task_index(self) -> dict[str, TaskTemplate]:
        return {t.task_id: t for t in self.tasks}


class PlanIssue(StrictModel):
    """DAG/限额问题。code 见 ScheduleErrorCode。"""

    code: str
    message: str
    task_ids: list[str] = Field(default_factory=list)


class DagValidationResult(StrictModel):
    ok: bool
    issues: list[PlanIssue] = Field(default_factory=list)
    order: list[str] = Field(default_factory=list)  # 拓扑序（ok 时全量）

    def first_code(self) -> str | None:
        return self.issues[0].code if self.issues else None


def _parse_hhmm(value: str, *, field: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"{field} must be HH:MM, got {value!r}")
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"{field} must be HH:MM, got {value!r}") from exc
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"{field} out of range: {value!r}")
    return hh, mm


def _parse_iso_date(value: str, *, field: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}") from exc


def validate_plan_dag(
    plan: SchedulePlan,
    *,
    max_tasks: int = DEFAULT_MAX_TASKS,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> DagValidationResult:
    """拓扑排序 O(V+E)（Kahn）。拒绝循环（schedule_cycle）与超限。

    返回结构化结果（不抛异常）：cycle → issues[0].code == schedule_cycle；
    ok=True 时 order 为全量任务拓扑序。
    """
    issues: list[PlanIssue] = []
    task_ids = [t.task_id for t in plan.tasks]

    if len(task_ids) > max_tasks:
        issues.append(
            PlanIssue(
                code=ScheduleErrorCode.PLAN_LIMIT_EXCEEDED,
                message=f"plan has {len(task_ids)} tasks, max is {max_tasks}",
                task_ids=[],
            )
        )
    if len(plan.edges) > max_edges:
        issues.append(
            PlanIssue(
                code=ScheduleErrorCode.PLAN_LIMIT_EXCEEDED,
                message=f"plan has {len(plan.edges)} edges, max is {max_edges}",
                task_ids=[],
            )
        )
    if len(set(task_ids)) != len(task_ids):
        dupes = sorted({tid for tid in task_ids if task_ids.count(tid) > 1})
        issues.append(
            PlanIssue(
                code=ScheduleErrorCode.UNKNOWN_EDGE_ENDPOINT,
                message=f"duplicate task_id: {dupes}",
                task_ids=dupes,
            )
        )

    known = set(task_ids)
    for edge in plan.edges:
        missing = [tid for tid in (edge.predecessor, edge.successor) if tid not in known]
        if missing:
            issues.append(
                PlanIssue(
                    code=ScheduleErrorCode.UNKNOWN_EDGE_ENDPOINT,
                    message=f"edge {edge.edge_id} references unknown task(s): {missing}",
                    task_ids=missing,
                )
            )

    # 相对任务锚必须在计划内。
    for task in plan.tasks:
        if task.anchor_task_id and task.anchor_task_id not in known:
            issues.append(
                PlanIssue(
                    code=ScheduleErrorCode.UNKNOWN_EDGE_ENDPOINT,
                    message=f"task {task.task_id} anchors unknown task {task.anchor_task_id}",
                    task_ids=[task.task_id],
                )
            )

    # Kahn 拓扑排序 O(V+E)。
    indegree = {tid: 0 for tid in task_ids}
    adjacency: dict[str, list[str]] = {tid: [] for tid in task_ids}
    for edge in plan.edges:
        if edge.predecessor in indegree and edge.successor in indegree:
            adjacency[edge.predecessor].append(edge.successor)
            indegree[edge.successor] += 1

    queue = deque(tid for tid in task_ids if indegree[tid] == 0)
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for nxt in adjacency[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(task_ids):
        cyclic = sorted(tid for tid in task_ids if tid not in set(order))
        issues.append(
            PlanIssue(
                code=ScheduleErrorCode.SCHEDULE_CYCLE,
                message=f"dependency cycle detected among {cyclic}",
                task_ids=cyclic,
            )
        )

    return DagValidationResult(ok=not issues, issues=issues, order=order if not issues else [])


def compute_earliest(
    plan: SchedulePlan,
    anchors: dict[str, tuple[datetime, datetime]],
) -> dict[str, tuple[datetime, datetime]]:
    """按拓扑序计算最早可行开始/结束窗口（UTC datetime）。

    anchors：已有确定时刻的任务（如 fixed_time 经规则展开后）的 (start, end)。
    相对任务 = 锚窗口的 start/finish + offset_minutes；duration 任务若不在
    anchors 且无锚 → missing_calendar（缺日历锚点，无法发布）。
    复杂度 O(V+E)（拓扑序一遍传播）。
    """
    validation = validate_plan_dag(plan)
    if not validation.ok:
        code = validation.first_code() or ScheduleErrorCode.SCHEDULE_CYCLE
        raise ScheduleError(code, validation.issues[0].message)

    result: dict[str, tuple[datetime, datetime]] = {}
    for task_id in validation.order:
        task = plan.task_by_id(task_id)
        if task is None:  # pragma: no cover - validate 已保证
            continue
        if task_id in anchors:
            result[task_id] = anchors[task_id]
            continue
        if task.kind is TaskKind.FIXED_TIME:
            # fixed_time 但未提供锚 → 缺日历（规则未展开/学期起点缺失）。
            raise ScheduleError(
                ScheduleErrorCode.MISSING_CALENDAR,
                f"task {task_id} is fixed_time but no calendar anchor provided",
            )
        if task.anchor_task_id is None:
            raise ScheduleError(
                ScheduleErrorCode.MISSING_CALENDAR,
                f"task {task_id} has no anchor and no fixed time; cannot compute window",
            )
        anchor_window = result.get(task.anchor_task_id)
        if anchor_window is None:
            raise ScheduleError(
                ScheduleErrorCode.MISSING_CALENDAR,
                f"anchor {task.anchor_task_id} of task {task_id} has no computed window",
            )
        offset = timedelta(minutes=task.offset_minutes)
        duration = timedelta(minutes=task.duration_minutes or 0)
        if task.kind is TaskKind.RELATIVE_TO_START:
            start = anchor_window[0] + offset
        else:  # RELATIVE_TO_FINISH
            start = anchor_window[1] + offset
        result[task_id] = (start, start + duration)
    return result
