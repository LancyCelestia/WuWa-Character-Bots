"""S11 余量交付①——自然语言→日程结构草稿（LLM 半边，V2.1 §4.1）。

职责边界（合同原文口径）：
- LLM 从自然语言提取**草稿**：动作/时间/依赖/重复规则；**不替用户确认**日期、
  出发地、目的地、交通或校历——缺关键信息一律落 ``needs_clarification`` 并列出
  澄清问题，绝不猜（合同 §4.1："LLM从自然语言/图片提取草稿，不替用户确认"）。
- 确定性半边（dict→SchedulePlan 校验/落库）在 ``schedule_service.parse_plan``，
  本模块只产出可被其消费的 payload（``draft_to_plan_payload``）。
- 模型调用面走依赖注入（``generate`` 可调用，签名对齐 ModelRouter.generate：
  ``(messages, *, ...) -> 有 .text 屔回复``）；生产装配助手
  ``build_schedule_llm(config)`` 惰性 import 既有路由（PEP 562 垫片只读消费，
  路由本体零改动、模块 import 期零硬依赖——离线测试不需要挂载 llm 包）。
- 出站提示词守岸人口径：中文、说人话、只要求结构化 JSON、不含任何内部术语
  （无 route/model/registry/prompt 等泄露词；``_LEAK_MARKERS`` 自检有测试锁定）。

七模板链（合同 §4.1 表）：课表/上班/出门办事/出行游玩/抢票抢课/购物/吃饭日常。
模板只提供**默认链条步骤种子**（tasks+finish_to_start 边）；购票/付款/下单等
涉及花钱的动作**结构性只落提醒步**，本模块不产出任何可执行购买语义。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.prompt_template import (
    PromptGuard,
    PromptSlot,
    PromptTemplate,
    register_prompt_template,
)
from plugins.bot_unified_runtime.domains.schedule.service.schedule_dag import (
    DEFAULT_MAX_EDGES,
    DEFAULT_MAX_TASKS,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_TIMEZONE",
    "TEMPLATE_CHAINS",
    "TEMPLATE_FAMILIES",
    "LLMDraftError",
    "ScheduleDraft",
    "build_schedule_llm",
    "classify_template",
    "draft_to_plan_payload",
    "parse_schedule_draft",
]

DEFAULT_TIMEZONE = "Asia/Shanghai"

# 模板族（合同 §4.1 七行；custom=未命中任何族的自由日程）。
TEMPLATE_FAMILIES = (
    "timetable",  # 课表
    "workday",  # 上班
    "errand",  # 出门/办事
    "trip",  # 出行/游玩
    "ticket",  # 抢票/抢课
    "shopping",  # 购物
    "meal",  # 吃饭/日常
    "custom",
)

# 每族默认链条步骤（合同 §4.1「默认链条」列；步骤名即 task_id 种子）。
# 抢票族的「开售」步落 rush 标签（引擎 reconcile 语义：过期即 expired 绝不
# 当"即将开售"）；购物族的「下单」是**用户自己下单**的记录提醒步，不是执行步。
TEMPLATE_CHAINS: dict[str, tuple[str, ...]] = {
    "timetable": ("起床准备", "课前", "上课", "课后事项"),
    "workday": ("起床", "早餐", "通勤", "到岗", "午餐", "下班"),
    "errand": ("材料清单", "出发", "到达", "办理", "返程"),
    "trip": ("证件检查", "打包", "出发", "安检候车", "行程", "返程"),
    "ticket": ("资格账号检查", "资料准备", "开售前提醒", "开售提醒", "结果登记"),
    "shopping": ("清单", "比价", "预算检查", "活动提醒", "下单记录", "收货退换截止"),
    "meal": ("食材准备", "用餐", "后续事务"),
}

# 模板链步骤→标签（决定引擎侧语义；无标签步骤不落）。
_TEMPLATE_TAGS: dict[str, tuple[str, ...]] = {
    "开售前提醒": ("rush",),
    "开售提醒": ("rush",),
}

# 每族必澄清字段（缺任一 → needs_clarification；宁可多问绝不编造）。
_FAMILY_REQUIRED: dict[str, tuple[str, ...]] = {
    "timetable": ("semester_start", "period_table"),
    "workday": ("start_date",),
    "errand": ("date",),
    "trip": ("date",),
    "ticket": ("datetime",),
    "shopping": ("date",),
    "meal": ("date",),
    "custom": ("date",),
}

_LOW_CONFIDENCE = 0.5


class LLMDraftError(Exception):
    """草稿解析结构性失败（JSON 坏/字段越界）；语义性缺失走 needs_clarification。"""


class _GenerateProtocol(Protocol):
    def __call__(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = ...,
        max_tokens: int = ...,
    ) -> Any: ...


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftAction(_Strict):
    """单个动作步（对应 plan 的 task+rule 种子）。"""

    step_id: str
    title: str
    local_time: str | None = None  # "HH:MM"；缺=相对步或待澄清
    date: str | None = None  # ISO 日期；缺=待澄清（绝不猜）
    duration_minutes: int | None = Field(default=None, ge=0)
    after_step: str | None = None  # 依赖前序步（finish_to_start）
    weekdays: list[int] = Field(default_factory=list)  # 0=周一…6=周日
    week_parity: str | None = None  # odd/even（单双周）
    tags: list[str] = Field(default_factory=list)

    @field_validator("step_id", "title")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("step_id/title must be non-blank")
        return str(value).strip()


class ScheduleDraft(_Strict):
    """结构草稿：LLM 半边产物，确认后才进引擎（confirm 前永不物化提醒）。"""

    template: str  # TEMPLATE_FAMILIES 之一
    title: str
    timezone: str = DEFAULT_TIMEZONE
    actions: list[DraftAction] = Field(default_factory=list)
    semester_start: str | None = None  # ISO；课表族必填（校历锚）
    period_table: dict[int, list[str]] = Field(default_factory=dict)  # 节次→[起,止]
    notes: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = "llm"

    @field_validator("template")
    @classmethod
    def _known_template(cls, value: str) -> str:
        if value not in TEMPLATE_FAMILIES:
            raise ValueError(f"unknown template family: {value}")
        return value

    @property
    def missing_fields(self) -> list[str]:
        """按模板族点名的缺失必填项（澄清问题的事实来源）。"""
        required = _FAMILY_REQUIRED.get(self.template, ("date",))
        missing: list[str] = []
        for field_name in required:
            gap = (
                (field_name == "semester_start" and not self.semester_start)
                or (field_name == "period_table" and not self.period_table)
                or (
                    field_name in ("date", "datetime", "start_date")
                    and not any(a.date for a in self.actions)
                )
            )
            if gap:
                missing.append(field_name)
        return missing

    @property
    def needs_clarification(self) -> bool:
        return bool(self.missing_fields) or self.confidence < _LOW_CONFIDENCE

    def clarification_questions(self) -> list[str]:
        questions: list[str] = []
        if "semester_start" in self.missing_fields:
            questions.append("学期从哪一天开始呀？单双周要按它来数第几周。")
        if "period_table" in self.missing_fields:
            questions.append("课表里只有节次没有时间呢，第 1 节到第 N 节分别是几点到几点？")
        for field_name in ("date", "datetime", "start_date"):
            if field_name in self.missing_fields:
                questions.append("这件事是哪一天（几点）？我不替你猜日子。")
                break
        if self.confidence < _LOW_CONFIDENCE:
            questions.append("这条安排我看得不太有把握，能再说清楚一点吗？")
        return questions


# ---------------------------------------------------------------- 提示词（守岸人口径）
# 自检锚：不含 route/model/registry/system/prompt/工具 等内部词；只要求 JSON。
# W1（2026-10-02）收编进模板层：骨架文本逐字节照旧（`prompt_texts()` 读模板 system），
# 增量只在**用户原话按二手材料包裹**——本腿是把那句话「转述」给抽取器，模型这轮并不在
# 和用户对话，那句原话里任何祈使句都只该是被分析的数据。
_DRAFT_TEMPLATE = register_prompt_template(
    PromptTemplate(
        key="llm_draft.schedule",
        system=(
            "你帮用户把一句话安排整理成结构化清单。只输出 JSON，不要解释。"
            "字段：template（timetable/workday/errand/trip/ticket/shopping/meal/custom 之一）、"
            "title、timezone、actions（step_id/title/local_time HH:MM/date YYYY-MM-DD/"
            "duration_minutes/after_step/weekdays 0=周一…6=周日/week_parity odd|even/tags）、"
            "semester_start、period_table（节次数字→[开始 HH:MM, 结束 HH:MM]）、notes、"
            "confidence（0 到 1，是你真的看懂了的把握）。"
            "用户没说清的时间、地点、日期就留空，绝不编造；一件事都没说清就给空 actions。"
        ),
        slots=(
            PromptSlot(
                "plan_text",
                guard=PromptGuard.WRAP,
                source_label="用户原话摘录",
            ),
        ),
    )
)

# 泄露词自检表（出站提示词不得出现；测试逐词扫描锁定）。
_LEAK_MARKERS = (
    "route",
    "registry",
    "model_router",
    "system prompt",
    "注入",
    "工具调用",
    "function call",
)


def prompt_texts() -> tuple[str, str]:
    """返回 (system, 说明) 文本；供接线席与泄露词自检使用。"""
    return _DRAFT_TEMPLATE.system, "把这段话整理成清单 JSON"


def classify_template(text: str) -> str:
    """关键词命中模板族（确定性半边；LLM 给不出 template 时的兜底）。

    只做词面归类，不推断任何时间/地点（禁猜边界不受此函数影响）。
    """
    lowered = text.lower()
    rules: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("timetable", ("课表", "课程表", "上课时间", "单双周", "第几节")),
        ("ticket", ("抢票", "抢课", "开售", "放票", "选课")),
        ("workday", ("上班", "打卡", "到岗", "通勤", "轮班")),
        ("trip", ("出差", "旅行", "出行", "游玩", "景点", "机票", "车票", "酒店")),
        ("shopping", ("购物", "买", "下单", "比价", "收货")),
        ("meal", ("吃饭", "做饭", "买菜", "聚餐", "用餐")),
        ("errand", ("办事", "办证", "取件", "缴费", "排队", "办理")),
    )
    for family, words in rules:
        if any(w in lowered for w in words):
            return family
    return "custom"


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _extract_json(raw: str) -> dict[str, Any]:
    """从回复中取首个 JSON 对象；取不到/类型不对 → LLMDraftError（禁猜）。"""
    match = _JSON_BLOCK.search(raw or "")
    if match is None:
        raise LLMDraftError("no json object in reply")
    try:
        payload = json.loads(match.group(0))
    except ValueError as exc:
        raise LLMDraftError(f"bad json: {exc}") from exc
    if not isinstance(payload, dict):
        raise LLMDraftError("json is not an object")
    return payload


def _build_actions(payload: dict[str, Any]) -> list[DraftAction]:
    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list):
        return []
    actions: list[DraftAction] = []
    for index, item in enumerate(raw_actions):
        if not isinstance(item, dict):
            continue
        item = dict(item)
        item.setdefault("step_id", f"step{index + 1}")
        item.setdefault("title", f"步骤{index + 1}")
        try:
            actions.append(DraftAction.model_validate(item))
        except Exception as exc:  # noqa: BLE001 - 单步坏数据丢弃记 notes，绝不猜补
            _logger.debug("draft action %s dropped: %s", index, exc)
            continue
    return actions


def parse_schedule_draft(
    text: str,
    generate: _GenerateProtocol,
    *,
    now_utc: datetime | None = None,
) -> ScheduleDraft:
    """自然语言→结构草稿。失败/残缺→needs_clarification 的诚实草稿，禁猜。

    generate：DI 注入的可调用（签名对齐 ModelRouter.generate）；本函数只读
    消费 ``reply.text``，任何异常向上抛由调用方决定降级（本模块不做网络重试）。
    """
    _ = now_utc  # 保留参数：接线席可传统一时钟；本模块不做相对日期推断
    messages = _DRAFT_TEMPLATE.render_messages(
        {"plan_text": str(text or "").strip()}
    )
    reply = generate(messages, temperature=0.1, max_tokens=800)
    raw = str(getattr(reply, "text", "") or "")
    payload = _extract_json(raw)

    template = str(payload.get("template") or "").strip()
    if template not in TEMPLATE_FAMILIES:
        template = classify_template(str(text or ""))
    title = str(payload.get("title") or "").strip() or "日程草稿"
    period_table = _normalize_period_table(payload.get("period_table"))
    confidence = _clamp_confidence(payload.get("confidence"))
    actions = _build_actions(payload)
    if not actions and template in TEMPLATE_CHAINS:
        # 模型没给步骤时按模板默认链条铺种子（纯确定性，不涉时间猜测）。
        actions = _seed_chain_actions(template)
    semester_start = str(payload.get("semester_start") or "").strip() or None
    notes = [str(n) for n in (payload.get("notes") or []) if str(n).strip()]
    if not actions:
        notes.append("没有可识别的具体安排，等你补充。")
    return ScheduleDraft(
        template=template,
        title=title,
        timezone=str(payload.get("timezone") or DEFAULT_TIMEZONE),
        actions=actions,
        semester_start=semester_start,
        period_table=period_table,
        notes=notes,
        confidence=confidence,
    )


def _seed_chain_actions(template: str) -> list[DraftAction]:
    steps = TEMPLATE_CHAINS.get(template)
    if not steps:
        return []
    actions: list[DraftAction] = []
    prev: str | None = None
    for step in steps:
        actions.append(
            DraftAction(
                step_id=step,
                title=step,
                after_step=prev,
                tags=list(_TEMPLATE_TAGS.get(step, ())),
            )
        )
        prev = step
    return actions


def _normalize_period_table(raw: Any) -> dict[int, list[str]]:
    """节次表：键 1..N、值 [HH:MM, HH:MM]；坏条目丢弃不猜。"""
    if not isinstance(raw, dict):
        return {}
    table: dict[int, list[str]] = {}
    for key, value in raw.items():
        try:
            period = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, (list, tuple)) and len(value) == 2:
            start, end = (str(v).strip() for v in value)
            if re.fullmatch(r"\d{1,2}:\d{2}", start) and re.fullmatch(r"\d{1,2}:\d{2}", end):
                table[period] = [start, end]
    return table


def _clamp_confidence(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


# ---------------------------------------------------------------- 草稿→plan payload
def draft_to_plan_payload(
    draft: ScheduleDraft,
    *,
    plan_id: str,
    owner: str,
) -> dict[str, Any]:
    """草稿→``parse_plan`` 可消费 dict（日期/时间缺失时拒绝，禁猜）。

    抛 ``LLMDraftError``：needs_clarification 的草稿没有可发布的日期事实。
    抢票/购物等模板的花钱步骤只落提醒任务（本函数不产生任何执行语义）。
    """
    if draft.needs_clarification:
        raise LLMDraftError(
            "draft needs clarification: " + "; ".join(draft.clarification_questions())
        )
    untyped = [a.step_id for a in draft.actions if a.local_time and not a.date]
    if untyped:
        # 有时刻没日期 → 日期事实缺口，澄清后再来（绝不给规则猜日期）。
        raise LLMDraftError(f"steps missing date fact: {untyped}")
    tasks: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    known_dates = {a.date for a in draft.actions if a.date}
    _ = sorted(known_dates)  # 日期口径以每步显式 date 为准；无显式日期的相对步挂锚步规则

    for action in draft.actions:
        tasks.append(
            {
                "task_id": action.step_id,
                "title": action.title,
                "kind": "fixed_time" if action.local_time else "duration",
                "duration_minutes": action.duration_minutes
                or (0 if action.local_time else 15),
                "fixed_local_time": action.local_time,
                "soft_window_minutes": 5,
                "tags": list(action.tags),
            }
        )
        if action.after_step:
            edges.append(
                {
                    "edge_id": f"e_{action.after_step}__{action.step_id}",
                    "predecessor": action.after_step,
                    "successor": action.step_id,
                }
            )
        # 规则只在有显式时刻时落（缺时刻=不提醒待澄清，绝不猜一个默认时刻）。
        if not action.local_time:
            continue
        anchor = action.after_step or action.step_id
        rule: dict[str, Any] = {
            "rule_id": f"r_{action.step_id}",
            "task_id": anchor,
            "kind": "once",
            "start_date": action.date or draft.semester_start or "",
            "local_time": action.local_time,
        }
        if action.weekdays:
            rule["kind"] = "weekly_by_day"
            rule["weekdays"] = list(action.weekdays)
        if action.week_parity:
            rule["kind"] = "teaching_week"
            rule["week_parity"] = action.week_parity
            rule["parity_anchor_date"] = draft.semester_start or rule["start_date"]
        if rule["kind"] == "once" and action.after_step:
            # 相对步没有自己的日期事实时不落 once 规则（由 DAG 最早窗口承载）。
            continue
        rules.append(rule)

    if len(tasks) > DEFAULT_MAX_TASKS or len(edges) > DEFAULT_MAX_EDGES:
        raise LLMDraftError("draft exceeds plan size limits")
    return {
        "plan_id": plan_id,
        "owner": owner,
        "timezone": draft.timezone,
        "state": "draft",  # 永远以 draft 落库，confirm 是用户的显式动作
        "tasks": tasks,
        "edges": edges,
        "rules": rules,
    }


# ---------------------------------------------------------------- 生产装配助手
def build_schedule_llm(config: Any) -> Any:
    """惰性组装既有主路由的 ``generate`` 可调用（只读消费真身路由，不走旧布局垫片）。

    返回值直接可作为 ``parse_schedule_draft`` 的 ``generate`` 参数；开关
    ``bot_schedule_llm_draft_enabled=False`` 或路由不可用 → None（调用方降级为
    纯澄清话术）。路由本体（chat_reply.llm_engine 域）零改动。
    """
    if not bool(getattr(config, "bot_schedule_llm_draft_enabled", False)):
        return None
    # 2026-09-29 席 S-FIX-SHIM-REFS：原走旧布局垫片 `llm/model_router`（`board_shim_ledger`
    # 在册待退役枚，上限 9）⇒ 改指真身，符号同名（真身 `build_model_router` :2681）。
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
        build_model_router,
    )

    return build_model_router(config).generate


def draft_date_floor(draft: ScheduleDraft) -> date | None:
    """草稿中最早显式日期（展示用；缺=None 不推断）。"""
    dates = sorted(date.fromisoformat(a.date) for a in draft.actions if a.date)
    return dates[0] if dates else None


def utc_now_iso() -> str:
    """测试与日志辅助：当前 UTC ISO（datetime.now 的唯一点，便于 monkeypatch）。"""
    return datetime.now(timezone.utc).isoformat()
