"""紧急信息域契约层：单一等级枚举 + 条目模型 + 审核状态机（纯数据，零 IO）。

本文件只做数据建模，绝不发网络请求、绝不 import llm/model_router、绝不读配置。

四条已裁定规则在这里落地（裁定原文
`.superpowers/sdd/2026-09-19-emergency-info-unify/briefs/b-wave-addendum.md` §1）：

- **D-3 等级=单一枚举**：`EmergencyLevel` 只有 P0/P1/P2/P3 四枚；对外文案唯一
  映射 `LEVEL_COLOR_LABEL`（红/橙/黄/蓝）。颜色词与序位**直接收编**气象预警既有
  词表 `domains/weather/capabilities/weather.py:112`
  （`_ALARM_COLOR_RANK = {"蓝色":1,"黄色":2,"橙色":3,"红色":4}`），不另造 severity
  同义枚举；`EmergencyItem` 的等级字段名为 `level`（`severity` 一名已被
  `OperationalIssue.severity: RiskLevel` 占用，真身
  `domains/core/contracts/runtime.py:43-46`，再造即两套）。跨到公共告警面时只经
  `to_risk_level()` 单点映射（建议出处 E5 §4.2）。
- **D-2 紧急面用词**：只有 P0/P1 为 urgent（`is_urgent_level`）。用词收编日程 v2
  `ReminderPolicy.urgent`（真身 `domains/schedule/service/schedule_dag.py:213-226`，
  穿静默判定 `domains/schedule/service/schedule_service.py:506`）。
- **D-1 无源诚实不接**：`build_emergency_item` 缺必需字段或字段非法 ⇒ 返回 None，
  绝不填假值凑数；`level=None` 的语义是「尚未定级」，不用最低档冒充「已判为低」。
- **D-8 人工报料**：`EmergencyStatus.PENDING` 是入库唯一缺省态；三态 +
  `CHECK (status IN ...)` + 「只能从 pending 转正」的形态抄 persona_quirks
  （`domains/chat_reply/character/quirks.py:39-41` 状态常量、
  `:157-176` 建表 CHECK、`:292-300` approve 只认 pending）。

样板坐标（九个统一自证）：`StrictBaseModel`（extra=forbid）与
`field_validator` 去空白、置信度区间校验全部抄
`domains/core/contracts/runtime.py:32-33`（StrictBaseModel）、
`:53-59`（require_non_blank）、`:264-269`（validate_confidence）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import ValidationError, field_validator, model_validator

from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    RiskLevel,
    StrictBaseModel,
)

# ---------------------------------------------------------------- 等级枚举（D-3）


class EmergencyLevel(str, Enum):
    """紧急等级：唯一等级枚举，P0 最高、P3 最低。

    `rank` 刻意与气象预警颜色序位同尺度（红=4 … 蓝=1，见本文件
    `LEVEL_COLOR_LABEL` 注），这样「按颜色判等」与「按等级判等」在两个域之间
    可以直接比大小，不需要第二张换算表。
    """

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

    @property
    def rank(self) -> int:
        """序位（4=最高 … 1=最低）；与 `_ALARM_COLOR_RANK` 数值口径一致。"""
        return _LEVEL_RANK[self]

    @property
    def color_label(self) -> str:
        """对外文案颜色词（红/橙/黄/蓝全称）；卡片色不在此处（属 render 域）。"""
        return LEVEL_COLOR_LABEL[self]


_LEVEL_RANK: dict[EmergencyLevel, int] = {
    EmergencyLevel.P0: 4,
    EmergencyLevel.P1: 3,
    EmergencyLevel.P2: 2,
    EmergencyLevel.P3: 1,
}

# 唯一对外颜色映射。键集合与数值序位必须与
# domains/weather/capabilities/weather.py:112 `_ALARM_COLOR_RANK` 保持一致，
# 漂移由 tests/test_emergency_info_core.py 的 AST 收编锁报红（不 import weather
# 能力模块：那会把 http 取数面拖进纯数据层）。
LEVEL_COLOR_LABEL: dict[EmergencyLevel, str] = {
    EmergencyLevel.P0: "红色",
    EmergencyLevel.P1: "橙色",
    EmergencyLevel.P2: "黄色",
    EmergencyLevel.P3: "蓝色",
}

_COLOR_LABEL_LEVEL: dict[str, EmergencyLevel] = {
    label: level for level, label in LEVEL_COLOR_LABEL.items()
}

# D-2：仅这两档穿安静时间，其余顺延（顺延执行归 transport 闸，本席只给判定）。
URGENT_LEVELS: frozenset[EmergencyLevel] = frozenset(
    {EmergencyLevel.P0, EmergencyLevel.P1}
)

_LEVEL_RISK_LEVEL: dict[EmergencyLevel, RiskLevel] = {
    EmergencyLevel.P0: RiskLevel.CRITICAL,
    EmergencyLevel.P1: RiskLevel.HIGH,
    EmergencyLevel.P2: RiskLevel.MEDIUM,
    EmergencyLevel.P3: RiskLevel.LOW,
}


def is_urgent_level(level: EmergencyLevel) -> bool:
    """该等级是否属于紧急面（仅 P0/P1，D-2 裁定的唯一事实源）。"""
    return level in URGENT_LEVELS


def level_from_color_label(color_label: str) -> EmergencyLevel | None:
    """源侧颜色词 → 等级；不认识的颜色一律 None（D-1：不猜、不上抬）。"""
    return _COLOR_LABEL_LEVEL.get(str(color_label or "").strip())


def to_risk_level(level: EmergencyLevel) -> RiskLevel:
    """紧急等级 → 公共告警等级：唯一映射点，消费方不得自建第二张表。"""
    return _LEVEL_RISK_LEVEL[level]


def highest_level(levels: Iterable[EmergencyLevel]) -> EmergencyLevel:
    """取最高档（rank 最大）；空集合抛 ValueError（不用缺省值假装判过）。"""
    collected = list(levels)
    if not collected:
        raise ValueError("highest_level() requires at least one level")
    return max(collected, key=lambda level: level.rank)


# ---------------------------------------------------------------- 审核状态机（D-8）


class EmergencyStatus(str, Enum):
    """人工报料状态：入库即 pending，过审 approved，驳回 rejected。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# 合法迁移表：只允许从 pending 出发的两种裁决。
# 「撤回过审」「驳回后重开」本席不做（诚实缺口，见 report §6）。
_ALLOWED_TRANSITIONS: dict[EmergencyStatus, frozenset[EmergencyStatus]] = {
    EmergencyStatus.PENDING: frozenset(
        {EmergencyStatus.APPROVED, EmergencyStatus.REJECTED}
    ),
    EmergencyStatus.APPROVED: frozenset(),
    EmergencyStatus.REJECTED: frozenset(),
}


def can_transition(current: EmergencyStatus, target: EmergencyStatus) -> bool:
    """状态机唯一判定口（存储侧的 SQL WHERE 守卫与本表同源）。"""
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------- 条目模型


def as_utc(moment: datetime) -> datetime:
    """naive 一律按 UTC 解释后归一（口径写死，不猜本地时区）。

    本域所有时间判定（时效窗/定级/日期键）都先经此归一，避免提醒族那种
    「UTC 混用 + 离线补投无检查」的老坑（AGENTS.md 台账 #29 ⑤）；日期键取用
    本地日历日的既有口径见 `__init__.py:3010/:3177`（本域 `date_key_of` 同型）。
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


class EmergencyItem(StrictBaseModel):
    """一条外部紧急信息（采集/报料共用模型）。

    字段基线抄 E5 §4.2 的 DTO 草案（item_id/source_id/source_kind/external_id/
    occurred_at/fetched_at/expires_at/title/body/credibility），差异只有两处，
    均为裁定要求：等级字段名 `level`（D-3，不叫 severity）、审核三字段
    （D-8）。`level=None` = 尚未定级，不是「等级为空字符串」。
    """

    item_id: str
    source_id: str
    source_kind: str = ""
    external_id: str
    title: str
    body: str = ""
    url: str = ""
    color_label: str = ""
    occurred_at: datetime
    fetched_at: datetime
    expires_at: datetime | None = None
    level: EmergencyLevel | None = None
    credibility: float = 0.0
    status: EmergencyStatus = EmergencyStatus.PENDING
    reviewed_by: str = ""
    reviewed_at: datetime | None = None

    @field_validator("item_id", "source_id", "external_id", "title")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        """必需字段去空白后不得为空（抄 OperationalIssue.require_non_blank）。"""
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("emergency item required field must be non-blank")
        return normalized

    @field_validator("source_kind", "body", "url", "color_label", "reviewed_by")
    @classmethod
    def strip_optional(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("occurred_at", "fetched_at", "expires_at", "reviewed_at")
    @classmethod
    def normalize_moment(cls, value: datetime | None) -> datetime | None:
        return None if value is None else as_utc(value)

    @field_validator("credibility")
    @classmethod
    def validate_credibility(cls, value: float) -> float:
        """可信度 0..1（校验形态抄 CapabilityResult.validate_confidence）。"""
        if not 0 <= value <= 1:
            raise ValueError("credibility must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def check_validity_window(self) -> EmergencyItem:
        """有效期不得早于发生时间（源侧给了矛盾时间 ⇒ 整条不成立，D-1）。"""
        if self.expires_at is not None and self.expires_at < self.occurred_at:
            raise ValueError("expires_at must not precede occurred_at")
        return self

    @property
    def is_urgent(self) -> bool:
        """已定级且属紧急面（P0/P1）；未定级恒 False——没判过就不自称紧急。"""
        return self.level is not None and is_urgent_level(self.level)

    @property
    def color_text(self) -> str:
        """对外颜色文案；尚未定级时为空串（不拿缺省档凑一个颜色）。"""
        return "" if self.level is None else self.level.color_label


def build_emergency_item(payload: Mapping[str, Any]) -> EmergencyItem | None:
    """安全构造口：解析不出必需字段 ⇒ None（D-1「无源诚实不接」唯一入口）。

    采集器一律经本函数把源侧 payload 转成条目；返回 None 时调用方必须
    **不入库、不投递**，也绝不退化成「填个假 id / 假时间」继续往下走。
    """
    if not isinstance(payload, Mapping):
        return None
    try:
        return EmergencyItem.model_validate(dict(payload))
    except ValidationError:
        # 契约层只回答「这条能不能成立」：不成立即 None，细节由调用方记日志。
        return None


__all__ = [
    "LEVEL_COLOR_LABEL",
    "URGENT_LEVELS",
    "EmergencyItem",
    "EmergencyLevel",
    "EmergencyStatus",
    "as_utc",
    "build_emergency_item",
    "can_transition",
    "highest_level",
    "is_urgent_level",
    "level_from_color_label",
    "to_risk_level",
]
