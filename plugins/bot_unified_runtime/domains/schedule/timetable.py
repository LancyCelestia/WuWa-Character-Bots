"""S11 余量交付②——课表截图→结构草稿（recognize_timetable，V2.1 §4.2）。

合同口径：
- 课表截图保留行列/合并区域/周次/置信度；**缺学期起点和节次表不能发布**
  （``needs_clarification`` + 澄清问题，绝不硬猜学期/时刻）。
- 单双周（odd/even）、节次→时间映射；重复导入按课程指纹去重（幂等）。
- 视觉调用面走依赖注入（provider 协议对齐 ``DynamicVisionProvider.generate``：
  ``(messages, *, temperature, max_tokens) -> 有 .text 屔回复``）——识图 registry
  的生产装配助手 ``build_timetable_provider(config)`` 惰性 import 既有
  ``domains.media.ingest.vision_describe.build_vision_provider``（只读消费，
  media 域零改动；本模块 import 期零硬依赖，离线测试全 mock）。
- 出站提示词守岸人口径：中文、只要结构化 JSON、没有的信息填 null 不许编，
  不含任何内部术语（泄露词自检与 llm_draft 同表，测试锁定）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.prompt_template import (
    PromptPartsTemplate,
    PromptSlot,
    register_prompt_template,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "CourseEntry",
    "TimetableDraft",
    "TimetableImportReport",
    "build_timetable_provider",
    "fingerprint_image_bytes",
    "merge_timetable_drafts",
    "recognize_timetable",
    "timetable_draft_to_plan_payload",
]

# 泄露词自检（与 llm_draft 同口径；出站提示词逐词扫描，测试锁定）。
_LEAK_MARKERS = (
    "route",
    "registry",
    "model_router",
    "system prompt",
    "注入",
    "工具调用",
    "function call",
)

# W1（2026-10-02）收编进模板层：课表识别的 user 侧是「静态引导 + 图像 parts」，
# 图像不是文本 ⇒ 反注入包裹无对象，本腿收编前后零字节差（骨架由模板持有、`prompt_text()`
# 读模板的 system，泄露词自检面不变）。
_TIMETABLE_TEMPLATE = register_prompt_template(
    PromptPartsTemplate(
        key="timetable.vlm",
        system=(
            "你帮用户把课程表截图整理成清单。只输出 JSON，不要解释。字段："
            "semester_start（学期第一天 YYYY-MM-DD，图里没有就 null）、"
            "period_table（节次数字→[开始 HH:MM, 结束 HH:MM]，图里没有就 null）、"
            "courses（每门课：course_name、weekday 0=周一…6=周日、periods 节次数组、"
            "start_time/end_time HH:MM（图里直接标了时间才填，否则 null）、"
            "week_parity odd|even|both（单双周，没标就是 both）、"
            "week_start/week_end（第几周到第几周，没有 null）、location、teacher、"
            "confidence 0 到 1、source_row/source_col（在截图里的行列位置，看不出 null）、"
            "merged（是否跨行跨列合并单元格 true/false））。"
            "看不清的字段一律 null，绝不猜；整页都不是课程表就给空 courses。"
        ),
        lead=PromptSlot("lead"),
    )
)


def prompt_text() -> str:
    """出站提示词文本（供接线席复用与泄露词自检）。"""
    return _TIMETABLE_TEMPLATE.system

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _valid_hhmm(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if re.fullmatch(r"\d{1,2}:\d{2}", text) else None


class CourseEntry(_Strict):
    """单门课（保留 OCR 出处与置信度；时间可空=待节次表映射）。"""

    course_name: str
    weekday: int = Field(ge=0, le=6)
    periods: list[int] = Field(default_factory=list)
    start_time: str | None = None  # HH:MM（OCR 直接给或节次表映射后）
    end_time: str | None = None
    week_parity: str = "both"  # odd|even|both
    week_start: int | None = Field(default=None, ge=1)
    week_end: int | None = Field(default=None, ge=1)
    location: str = ""
    teacher: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_row: int | None = None  # 截图行列出处（合同：保留行列/合并区域）
    source_col: int | None = None
    merged: bool = False

    @field_validator("course_name")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("course_name must be non-blank")
        return str(value).strip()

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _hhmm_or_none(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if re.fullmatch(r"\d{1,2}:\d{2}", text) else None

    @field_validator("week_parity")
    @classmethod
    def _parity(cls, value: str) -> str:
        return value if value in ("odd", "even", "both") else "both"

    @property
    def fingerprint(self) -> str:
        """课程指纹：同名同位同时刻同周次 = 同一门课（重复导入去重键）。"""
        payload = "|".join(
            (
                self.course_name,
                str(self.weekday),
                self.start_time or "-",
                self.end_time or "-",
                self.week_parity,
                str(self.week_start or ""),
                str(self.week_end or ""),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]

    def has_time(self) -> bool:
        return bool(self.start_time and self.end_time)


class TimetableDraft(_Strict):
    """课表结构草稿：确认+补齐学期/节次后才可发布成 plan。"""

    courses: list[CourseEntry] = Field(default_factory=list)
    semester_start: str | None = None  # ISO；缺=待澄清（校历锚不许猜）
    period_table: dict[int, list[str]] = Field(default_factory=dict)
    image_fingerprint: str = ""
    source: str = "vision"

    @field_validator("semester_start", mode="before")
    @classmethod
    def _iso_or_none(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None

    @property
    def has_parity_courses(self) -> bool:
        return any(c.week_parity in ("odd", "even") for c in self.courses)

    def missing_clarifications(self) -> list[str]:
        """缺什么就问什么；返回非空 = 不能发布。"""
        issues: list[str] = []
        if not self.courses:
            issues.append("这张图里没有认出课程。")
            return issues
        if self.semester_start is None and self.has_parity_courses:
            issues.append("学期第一天是哪天？单双周要按它数第几周。")
        unmapped = [c for c in self.courses if not c.has_time()]
        if unmapped and not self.period_table:
            issues.append(
                f"有 {len(unmapped)} 门课只写了节次没写时间，第 1 到第 "
                f"{max((p for c in unmapped for p in c.periods), default=1)} 节分别是几点到几点？"
            )
        unmapped_periods = sorted(
            {p for c in self.courses if not c.has_time() for p in c.periods}
            - set(self.period_table)
        )
        if unmapped_periods and self.period_table:
            issues.append(f"节次表里缺第 {unmapped_periods} 节的时间。")
        return issues

    @property
    def needs_clarification(self) -> bool:
        return bool(self.missing_clarifications())


class TimetableImportReport(_Strict):
    """重复导入对账：added=新增、skipped=指纹相同幂等跳过、kept=同名不同时刻并存。"""

    added: int = 0
    skipped: int = 0
    total_incoming: int = 0


def fingerprint_image_bytes(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()[:20]


def _image_to_data_url(ref: str) -> str:
    """图片引用 → provider 侧图像形态：**只走识图腿在册判定口，禁第二取字节通路**。

    病根（ATK-SCHED 票5 / S-FIX-ATK-SCHED2）：旧实现把本地路径自己
    ``Path.read_bytes()`` → base64 ——任意本机可读文件（段字段 ``data.file`` 可指
    ``.env`` 一类秘密）整块进外部 VLM 载荷，无大小上限、无格式白名单、不经任何
    判定，正是 AGENTS「文件出站」行在册裁定「取字节前统一判定（禁第二通路）」点名的
    第二通路。现收编到媒体域识图腿的既有咽喉（chat 视觉面同一构造，零新机制）：

    - ``http(s)``：``prepare_vision_image_urls``——入口中央咽喉
      ``domains/files/sources/downloader.check_download_url`` + 逐跳 SSRF 复查，
      bot 侧限额下载再编码（QQ 签名 URL 对服务商不可达的同族老坑一并治掉）；
      咽喉明确拒绝＝丢图不回透（F-2 口径），瞬时失败保留原 URL 兜底（原语义）。
    - 本地路径/``file:``：``_image_file_to_data_url``——大小上限 + 格式白名单 +
      像素预算（解压炸弹锁），读不实按无图降级返回空串，调用方丢该条。
    - ``data:``：原样透传（字节由消息本身带来，不触本地读）。
    - 空引用：返回空串。
    """
    text = str(ref or "").strip()
    if not text:
        return ""
    from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
        _image_file_to_data_url,
        prepare_vision_image_urls,
    )

    if text.startswith("data:"):
        return text
    if text.startswith(("http://", "https://")):
        prepared = prepare_vision_image_urls([text])
        return prepared[0] if prepared else ""
    return _image_file_to_data_url(text) or ""


def _extract_json(raw: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", raw or "")
    if match is None:
        raise ValueError("no json object in vision reply")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise TypeError("vision json is not an object")
    return payload


def _normalize_period_table(raw: Any) -> dict[int, list[str]]:
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


def _coerce_courses(raw: Any) -> list[CourseEntry]:
    if not isinstance(raw, list):
        return []
    courses: list[CourseEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        # 丢置信度过低条目（低置信=看不清，宁可问也不收）
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.3:
            continue
        periods_raw = item.get("periods") or []
        periods: list[int] = []
        if isinstance(periods_raw, list):
            for p in periods_raw:
                try:
                    periods.append(int(p))
                except (TypeError, ValueError):
                    continue
        try:
            courses.append(
                CourseEntry(
                    course_name=str(item.get("course_name") or "").strip(),
                    weekday=int(item.get("weekday") or 0),
                    periods=periods,
                    start_time=item.get("start_time"),
                    end_time=item.get("end_time"),
                    week_parity=str(item.get("week_parity") or "both"),
                    week_start=item.get("week_start"),
                    week_end=item.get("week_end"),
                    location=str(item.get("location") or ""),
                    teacher=str(item.get("teacher") or ""),
                    confidence=max(0.0, min(1.0, confidence)),
                    source_row=item.get("source_row"),
                    source_col=item.get("source_col"),
                    merged=bool(item.get("merged") or False),
                )
            )
        except Exception as exc:  # noqa: BLE001 - 单条坏数据丢弃，不猜不补
            _logger.debug("timetable course dropped: %s", exc)
            continue
    return courses


def _apply_period_table(draft: TimetableDraft) -> None:
    """节次→时间映射：只映射表里有的节次；映射后仍缺时间的留给澄清。"""
    if not draft.period_table:
        return
    for course in draft.courses:
        if course.has_time() or not course.periods:
            continue
        spans = [draft.period_table[p] for p in course.periods if p in draft.period_table]
        if not spans:
            continue
        course.start_time = min(s[0] for s in spans)
        course.end_time = max(s[1] for s in spans)


def recognize_timetable(
    provider: Any,
    images: list[str] | str,
    *,
    semester_start: str | None = None,
    period_table: dict[int, list[str]] | None = None,
    image_bytes: bytes | None = None,
) -> TimetableDraft:
    """课表截图→结构草稿。provider 不可用/回复坏 → 空课程草稿（诚实，不猜）。

    images：data URL / 本地路径 / http(s) URL；调用方持有 provider 生命周期。
    semester_start / period_table：调用方已知的先验（用户提供后不再发问）。
    """
    refs = [images] if isinstance(images, str) else list(images or [])
    if provider is None or not refs:
        return TimetableDraft()
    converted = [_image_to_data_url(ref) for ref in refs[:2]]
    usable = [url for url in converted if url]
    if not usable:
        # 票5 收严后的诚实面：所有图都过不了在册判定口（本地非图/咽喉拒绝/读不实）
        # =「这张图没读成」，**绝不空手敲 provider**——没有图像的纯文字请求只会让
        # 模型凭提示词编课程（识别失败=空草稿+澄清，不猜）。
        draft = TimetableDraft()
        if image_bytes:
            draft.image_fingerprint = fingerprint_image_bytes(image_bytes)
        return draft
    parts: list[dict[str, Any]] = []
    for url in usable:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    messages = _TIMETABLE_TEMPLATE.render_messages(
        {"lead": "帮我把这张课程表整理成清单。", "parts": parts}
    )
    try:
        reply = provider.generate(messages, temperature=0.1, max_tokens=2000)
        payload = _extract_json(str(getattr(reply, "text", "") or ""))
    except Exception:  # noqa: BLE001 - 识别失败=空草稿+澄清，绝不编课程
        draft = TimetableDraft()
        if image_bytes:
            draft.image_fingerprint = fingerprint_image_bytes(image_bytes)
        return draft

    draft = TimetableDraft(
        courses=_coerce_courses(payload.get("courses")),
        semester_start=str(payload.get("semester_start") or "").strip() or None,
        period_table=_normalize_period_table(payload.get("period_table")),
        image_fingerprint=fingerprint_image_bytes(image_bytes) if image_bytes else "",
    )
    # 先验（调用方显式给出）优先于 OCR；OCR 结果只作补位，不覆盖先验。
    if semester_start:
        draft.semester_start = semester_start
    if period_table:
        draft.period_table = dict(period_table)
    _apply_period_table(draft)
    return draft


def merge_timetable_drafts(
    incoming: TimetableDraft, existing: TimetableDraft | None
) -> tuple[TimetableDraft, TimetableImportReport]:
    """重复导入去重：指纹相同跳过；同名不同时刻各自保留（不合并不覆盖）。"""
    report = TimetableImportReport(total_incoming=len(incoming.courses))
    if existing is None:
        report.added = len(incoming.courses)
        return incoming.model_copy(), report
    known = {c.fingerprint for c in existing.courses}
    merged = existing.model_copy(deep=True)
    for course in incoming.courses:
        if course.fingerprint in known:
            report.skipped += 1
            continue
        merged.courses.append(course)
        known.add(course.fingerprint)
        report.added += 1
    if not merged.semester_start:
        merged.semester_start = incoming.semester_start
    if not merged.period_table:
        merged.period_table = dict(incoming.period_table)
    if not merged.image_fingerprint:
        merged.image_fingerprint = incoming.image_fingerprint
    return merged, report


def timetable_draft_to_plan_payload(
    draft: TimetableDraft,
    *,
    plan_id: str,
    owner: str,
) -> dict[str, Any]:
    """完整草稿→``parse_plan`` 可消费 dict；缺学期/节次映射 → ValueError 拒发布。"""
    issues = draft.missing_clarifications()
    if issues:
        raise ValueError("timetable draft not publishable: " + "; ".join(issues))
    tasks: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    for index, course in enumerate(draft.courses):
        task_id = f"course{index + 1}"
        tasks.append(
            {
                "task_id": task_id,
                "title": course.course_name,
                "kind": "fixed_time",
                "duration_minutes": _span_minutes(course),
                "fixed_local_time": course.start_time,
                "soft_window_minutes": 0,  # 上课是硬预约（不许静默顺延）
                "tags": ["course"] + ([f"location:{course.location}"] if course.location else []),
            }
        )
        rule: dict[str, Any] = {
            "rule_id": f"rule_{task_id}",
            "task_id": task_id,
            "start_date": draft.semester_start or "",
            "local_time": course.start_time or "",
        }
        if course.week_parity in ("odd", "even"):
            rule["kind"] = "teaching_week"
            rule["weekdays"] = [course.weekday]
            rule["week_parity"] = course.week_parity
            rule["parity_anchor_date"] = draft.semester_start
        else:
            rule["kind"] = "weekly_by_day"
            rule["weekdays"] = [course.weekday]
        rules.append(rule)
    return {
        "plan_id": plan_id,
        "owner": owner,
        "timezone": "Asia/Shanghai",
        "state": "draft",  # 发布前仍需用户确认（confirm 是显式动作）
        "tasks": tasks,
        "edges": [],
        "rules": rules,
    }


def _span_minutes(course: CourseEntry) -> int:
    def _minutes(hhmm: str) -> int:
        hh, mm = hhmm.split(":")
        return int(hh) * 60 + int(mm)

    if not (course.start_time and course.end_time):
        return 45
    return max(0, _minutes(course.end_time) - _minutes(course.start_time))


def build_timetable_provider(config: Any) -> Any:
    """惰性组装既有识图 provider（只读消费 media 域装配助手）；不可用返回 None。

    识图 registry（bot_vision_model_registry）为空或 BOT_VISION_ENABLED 关时
    返回 None（vision_describe 自身语义）；调用方按「识别不了→发问澄清」降级。
    """
    from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
        build_vision_provider,
    )

    return build_vision_provider(config)
