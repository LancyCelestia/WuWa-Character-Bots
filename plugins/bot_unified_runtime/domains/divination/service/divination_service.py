"""V2.1 S12 占卜统一服务：DrawRequest 契约 + DivinationService（持久化优先）。

合同来源：docs/design/backend-v2-product-extensions.md §3（V21-DIVINATION-001/002）。

- 契约：``DrawRequest(kind, spread_id, question≤500字, timezone_id,
  workspace_id, idempotency_key)``；身份/日期/密钥来自可信
  ``TrustedDrawContext``（认证注入），绝不信任客户端自述。结果形态
  ``DrawResult``（draw_id/cards[]/fortune_grade/interpretation_lines/
  algorithm_revision/deck_revision/asset_ids/trace_id/disclaimer_id）。
- 语义：
  - 每日运势：day_key 唯一（同日跨会话/跨幂等键/重启/密钥轮换不重抽），
    重读不限；等级抽取见 runtime/fortune.py。
  - 塔罗：阵型白名单（invalid_spread）→ 随机抽取（生产 SystemPrng）→
    **先持久化后解读**——解读唯一入口是 ``build_interpretation_context``，
    只消费持久行并通过牌库完整性校验（deck_integrity_mismatch），
    函数上不可能换牌/换朝向/伪造第 79 张。
  - draw_id / idempotency_key 重试恒返回既有抽取（不重抽、不换牌）；
    同幂等键跨日/跨类别复用 → idempotency_conflict（已注册码）。
- 配额：每主体塔罗冷却 60s、每天 20 次（workspace 独立配额），在存储
  写锁事务内判定；运势不入配额。关闭态 → feature_disabled。
- 娱乐边界：结果附 disclaimer_id；解读为定性娱乐指引，不伪装确定预言；
  本服务不改好感度、不建日程、不触发任何交易动作（结构上无此出口）。
- LLM 解释席位（后续）：只消费 ``build_interpretation_context`` 输出；
  模型失败回落 ``local_interpretation_lines``（既有牌面的本地解释，非重抽）。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from plugins.bot_unified_runtime.domains.core.contracts.errors import new_trace_id
from plugins.bot_unified_runtime.domains.core.contracts.request import (
    IDEMPOTENCY_KEY_PATTERN,
)
from plugins.bot_unified_runtime.domains.divination.data.deck_math import (
    DECK_REVISION,
    FORTUNE_ALGORITHM_REVISION,
    FORTUNE_GRADES_V1,
    FORTUNE_RULE_VERSION,
    POSITION_LABELS,
    TAROT_ALGORITHM_REVISION,
    AuditPrng,
    SystemPrng,
    build_card_index,
    derive_fortune_seed,
    draw_fortune_grade,
    draw_tarot_cards,
    fortune_day_key,
    local_date_for,
    validate_spread,
    validated_tarot_cards,
)
from plugins.bot_unified_runtime.domains.divination.store.draw_store import (
    DEFAULT_TAROT_COOLDOWN_SECONDS,
    DEFAULT_TAROT_DAILY_LIMIT,
    DrawError,
    DrawRecord,
    DrawStore,
    QuotaPolicy,
)

__all__ = [
    "ASSET_IDS_EMPTY",
    "DISCLAIMER_ID",
    "DISCLAIMER_TEXT",
    "DivinationService",
    "DrawRequest",
    "DrawResult",
    "InterpretationContext",
    "TrustedDrawContext",
]

# 娱乐声明（合同 §3.1：解释不得伪装确定预言或专业决策）。
DISCLAIMER_ID = "divination-entertainment-v1"
DISCLAIMER_TEXT = "占卜与运势是娱乐向指引，不是确定预言，也不替代专业建议。"

# 素材面：本席未登记任何牌图资产——缺图就文本，不临时抓来源不明图片。
ASSET_IDS_EMPTY: tuple[str, ...] = ()

_GRADE_LINES: dict[str, str] = {
    "大吉": "今天整体顺风，适合把搁置的事推进一把。",
    "中吉": "今天整体平稳偏暖，稳稳推进就会有收获。",
    "小吉": "今天有点小小的亮光，留意身边顺手的好机会。",
    "平": "今天是平常的一天，不急不躁刚刚好。",
    "小凶": "今天多留意细节，节奏放慢一点会更稳。",
    "凶": "今天适合保守行事，把重要的决定留给状态更好的时候。",
}

_KNOWN_GRADES = frozenset(grade for grade, _ in FORTUNE_GRADES_V1)


class DrawRequest(BaseModel):
    """§3.2 抽签请求（严格 DTO；extra=forbid）。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    kind: Literal["tarot", "fortune"]
    spread_id: str | None = Field(default=None, max_length=64)
    question: str = Field(default="", max_length=500)
    timezone_id: str = Field(min_length=1, max_length=64)
    workspace_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_KEY_PATTERN)

    @field_validator("timezone_id")
    @classmethod
    def require_loadable_zone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"未知时区：{value!r}") from exc
        return value

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        return value.strip()


@dataclass(frozen=True)
class TrustedDrawContext:
    """可信上下文：身份/时刻只由认证与核心注入，不来自客户端载荷。

    HMAC 密钥由核心直接注入服务（``DivinationService(secret=...)``），
    不经请求、不经上下文、不暴露给插件与客户端。
    """

    principal_id: str
    bot_id: str
    now: datetime

    def __post_init__(self) -> None:
        if self.now.tzinfo is None or self.now.utcoffset() is None:
            raise ValueError("TrustedDrawContext.now 必须带时区")


@dataclass(frozen=True)
class InterpretationContext:
    """LLM 解释席位唯一合法输入：从持久行校验重建的牌面/等级。"""

    draw_id: str
    kind: str
    spread_id: str
    cards: tuple[dict[str, str], ...]
    fortune_grade: str


@dataclass(frozen=True)
class DrawResult:
    """§3.2 抽签结果（契约投影）。"""

    draw_id: str
    kind: str
    cards: tuple[dict[str, str], ...]
    fortune_grade: str
    interpretation_lines: tuple[str, ...]
    algorithm_revision: str
    deck_revision: str
    asset_ids: tuple[str, ...]
    trace_id: str
    disclaimer_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "draw_id": self.draw_id,
            "kind": self.kind,
            "cards": [dict(card) for card in self.cards],
            "fortune_grade": self.fortune_grade,
            "interpretation_lines": list(self.interpretation_lines),
            "algorithm_revision": self.algorithm_revision,
            "deck_revision": self.deck_revision,
            "asset_ids": list(self.asset_ids),
            "trace_id": self.trace_id,
            "disclaimer_id": self.disclaimer_id,
        }


class DivinationService:
    """占卜统一入口：运势 day_key 幂等 + 塔罗持久化优先 + 事务内配额。"""

    def __init__(
        self,
        store: DrawStore,
        *,
        secret: bytes,
        enabled: bool = True,
        prng_factory: Callable[[], AuditPrng] | None = None,
        tarot_cooldown_seconds: int = DEFAULT_TAROT_COOLDOWN_SECONDS,
        tarot_daily_limit: int = DEFAULT_TAROT_DAILY_LIMIT,
        trace_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._secret = bytes(secret)
        self._enabled = bool(enabled)
        self._prng_factory = prng_factory or (lambda: SystemPrng())
        self._quota = QuotaPolicy(
            cooldown_seconds=int(tarot_cooldown_seconds),
            daily_limit=int(tarot_daily_limit),
        )
        self._trace_factory = trace_factory or new_trace_id

    # ── 创建面 ──────────────────────────────────────────────────────────

    def create_draw(self, request: DrawRequest, context: TrustedDrawContext) -> DrawResult:
        """创建一次抽取（幂等）；解读发生在持久化成功之后。"""
        if not self._enabled:
            raise DrawError("feature_disabled", "占卜功能当前处于关闭状态")
        local_date = local_date_for(context.now, request.timezone_id)
        if request.kind == "fortune":
            return self._create_fortune(request, context, local_date)
        return self._create_tarot(request, context, local_date)

    # ── 读面（重读不限）────────────────────────────────────────────────

    def get_draw(self, draw_id: str) -> DrawResult:
        """按 draw_id 读取既有抽取（运势/塔罗重读均不限次）。"""
        record = self._store.get_draw(draw_id)
        if record is None:
            raise DrawError("resource_not_found", f"找不到这次抽取：{draw_id}")
        return self._project(record)

    # ── 解读面（持久化优先；LLM 席位只消费这里）────────────────────────

    def build_interpretation_context(self, draw_id: str) -> InterpretationContext:
        """持久行 → 校验后的解读上下文；篡改/伪造 → deck_integrity_mismatch。"""
        record = self._store.get_draw(draw_id)
        if record is None:
            raise DrawError("resource_not_found", f"找不到这次抽取：{draw_id}")
        return build_interpretation_context(record)

    def interpret_draw(self, draw_id: str) -> DrawResult:
        """读取既有抽取并给出来自持久牌面的本地解读（模型失败回落面）。"""
        record = self._store.get_draw(draw_id)
        if record is None:
            raise DrawError("resource_not_found", f"找不到这次抽取：{draw_id}")
        return self._project(record)

    # ── 内部：运势 ─────────────────────────────────────────────────────

    def _create_fortune(
        self, request: DrawRequest, context: TrustedDrawContext, local_date: str
    ) -> DrawResult:
        day_key = fortune_day_key(
            context.principal_id, context.bot_id, local_date, FORTUNE_RULE_VERSION
        )
        # 幂等键命中：类别/日期不符属键复用（idempotency_conflict）。
        by_key = self._store.find_by_idempotency_key(request.idempotency_key)
        if by_key is not None:
            if by_key.kind != "fortune" or by_key.dedupe_key != day_key:
                raise DrawError(
                    "idempotency_conflict",
                    "这个幂等键已经绑定过别的抽取，请换一个键",
                )
            return self._project(by_key)
        # day_key 命中：同日跨会话/跨幂等键/重启/密钥轮换 → 既有结果不重抽。
        by_day = self._store.find_by_dedupe("fortune", day_key)
        if by_day is not None:
            return self._project(by_day)

        seed = derive_fortune_seed(
            self._secret, context.principal_id, context.bot_id, local_date
        )
        grade = draw_fortune_grade(seed.prng)
        record = DrawRecord(
            draw_id=_new_draw_id(),
            kind="fortune",
            principal_id=context.principal_id,
            bot_id=context.bot_id,
            workspace_id=request.workspace_id,
            idempotency_key=request.idempotency_key,
            dedupe_key=day_key,
            question=request.question,
            timezone_id=request.timezone_id,
            fortune_grade=grade,
            algorithm_revision=FORTUNE_ALGORITHM_REVISION,
            key_id=seed.key_id,
            seed_digest=seed.seed_digest,
            trace_id=self._trace_factory(),
            local_day=local_date,
            occurred_at=context.now.isoformat(),
            occurred_epoch=context.now.timestamp(),
        )
        stored, _created = self._store.persist_draw_once(record, quota=None)
        return self._project(stored)

    # ── 内部：塔罗 ─────────────────────────────────────────────────────

    def _create_tarot(
        self, request: DrawRequest, context: TrustedDrawContext, local_date: str
    ) -> DrawResult:
        spread_id = request.spread_id or ""
        validate_spread(spread_id)  # 非法阵型 → DrawError("invalid_spread")
        by_key = self._store.find_by_idempotency_key(request.idempotency_key)
        if by_key is not None:
            if by_key.kind != "tarot":
                raise DrawError(
                    "idempotency_conflict",
                    "这个幂等键已经绑定过别的抽取，请换一个键",
                )
            return self._project(by_key)  # 重试不变：不重抽、不换牌
        cards = draw_tarot_cards(spread_id, self._prng_factory())
        record = DrawRecord(
            draw_id=_new_draw_id(),
            kind="tarot",
            principal_id=context.principal_id,
            bot_id=context.bot_id,
            workspace_id=request.workspace_id,
            idempotency_key=request.idempotency_key,
            spread_id=spread_id,
            question=request.question,
            timezone_id=request.timezone_id,
            cards=cards,
            algorithm_revision=TAROT_ALGORITHM_REVISION,
            deck_revision=DECK_REVISION,
            trace_id=self._trace_factory(),
            local_day=local_date,
            occurred_at=context.now.isoformat(),
            occurred_epoch=context.now.timestamp(),
        )
        stored, _created = self._store.persist_draw_once(record, quota=self._quota)
        return self._project(stored)

    # ── 内部：持久行 → 契约结果 ────────────────────────────────────────

    def _project(self, record: DrawRecord) -> DrawResult:
        interpretation = build_interpretation_context(record)
        lines = local_interpretation_lines(interpretation)
        return DrawResult(
            draw_id=record.draw_id,
            kind=record.kind,
            cards=tuple(dict(card) for card in interpretation.cards),
            fortune_grade=record.fortune_grade,
            interpretation_lines=lines,
            algorithm_revision=record.algorithm_revision,
            deck_revision=record.deck_revision,
            asset_ids=ASSET_IDS_EMPTY,
            trace_id=record.trace_id,
            disclaimer_id=DISCLAIMER_ID,
        )


def _new_draw_id() -> str:
    return f"draw_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# 持久行 → 解读上下文（完整性门：篡改/伪造 → deck_integrity_mismatch）。
# ---------------------------------------------------------------------------


def build_interpretation_context(record: DrawRecord) -> InterpretationContext:
    """校验持久行并重建解读上下文（LLM 解释的唯一合法输入）。

    - tarot：牌面完整性走全域唯一的一道门 ``data.deck_math.validated_tarot_cards``
      （阵型/张数/位置序列/牌库存在性/朝向/牌库版本全部吻合才放行；任何不符，
      含伪造第 79 张、牌库外 card_id、spread_id 被篡改、cards_json 损坏 →
      ``deck_integrity_mismatch``）。聊天渲染与控制面解读共用这一颗门。
    - fortune：等级必须在登记表内且 cards 为空，否则同码报错。
    """
    if record.kind == "fortune":
        if record.cards:
            raise DrawError("deck_integrity_mismatch", "运势不应携带牌面")
        if record.fortune_grade not in _KNOWN_GRADES:
            raise DrawError(
                "deck_integrity_mismatch", f"未登记的运势等级：{record.fortune_grade!r}"
            )
        return InterpretationContext(
            draw_id=record.draw_id,
            kind=record.kind,
            spread_id="",
            cards=(),
            fortune_grade=record.fortune_grade,
        )
    if record.kind != "tarot":  # pragma: no cover - 存储层写入面已约束
        raise DrawError("deck_integrity_mismatch", f"未知抽取类别：{record.kind!r}")
    spread_id, cards = validated_tarot_cards(record)
    return InterpretationContext(
        draw_id=record.draw_id,
        kind=record.kind,
        spread_id=spread_id,
        cards=tuple(dict(card) for card in cards),
        fortune_grade="",
    )


def local_interpretation_lines(context: InterpretationContext) -> tuple[str, ...]:
    """本地确定性解读（娱乐向、定性；不伪装确定预言）。

    LLM 解释席位可用同上下文生成人格化解读；模型失败时回落本函数输出。
    """
    lines: list[str] = []
    if context.kind == "fortune":
        grade_line = _GRADE_LINES.get(context.fortune_grade)
        if grade_line is None:  # pragma: no cover - 完整性门已拦截未知等级
            raise DrawError("deck_integrity_mismatch", "未登记的运势等级")
        lines.append(f"今日运势：{context.fortune_grade}。{grade_line}")
    else:
        index = build_card_index()
        labels = POSITION_LABELS.get(context.spread_id, {})
        for item in context.cards:
            card = index[item["card_id"]]
            orientation = "正位" if item["orientation"] == "upright" else "逆位"
            hint = card.reversed_hint if orientation == "逆位" else card.upright_hint
            label = labels.get(item["position_id"], item["position_id"])
            prefix = f"【{label}】" if label else ""
            lines.append(f"{prefix}{card.name}（{orientation}）——{hint}")
    lines.append(DISCLAIMER_TEXT)
    return tuple(lines)
