"""V2.1 S12 REST 服务薄壳（框架无关；控制面路由的唯一域入口）。

- 只读消费 W5 域半边：``DivinationService``（幂等/配额/解读）与
  ``data/ganzhi``（八字既有算法）——本模块零算法、零存储改动。
- 频控语义（合同：复用 draw_store 额度语义）：
  - 塔罗：60s 冷却 / 每日 20 次（workspace 独立）——服务层在存储写锁事务
    内判定（并发不超卖），本层不重复计数；
  - 运势：day_key 每日一次幂等 + 重读不限（同日跨会话/跨幂等键/重启/
    密钥轮换恒命中既有行）；
  - bazi/preview 是**非持久**的只读投影，不入 draw_store 配额——防刷用
    本进程内每主体固定窗限速（缺省 10 次/60s，测试可注入 clock/参数）。
- 角色判定复用 ``policy.roles`` 的六级序（user < trusted < enterprise <
  admin < super_admin；blocked 显式拒绝），不另造角色表。
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_BLOCKED,
    ROLE_ORDER,
)
from plugins.bot_unified_runtime.domains.divination.api.dto import (
    BaziPreviewPayload,
    DivinationDrawPayload,
)
from plugins.bot_unified_runtime.domains.divination.data.deck_math import (
    DECK_REVISION,
    FORTUNE_ALGORITHM_REVISION,
    FORTUNE_GRADES_V1,
    FORTUNE_RULE_VERSION,
    POSITION_LABELS,
    SPREADS,
    TAROT_ALGORITHM_REVISION,
    build_card_index,
)
from plugins.bot_unified_runtime.domains.divination.service.divination_service import (
    DISCLAIMER_ID,
    DISCLAIMER_TEXT,
    DivinationService,
    DrawResult,
    TrustedDrawContext,
)
from plugins.bot_unified_runtime.domains.divination.store.draw_store import (
    DEFAULT_TAROT_COOLDOWN_SECONDS,
    DEFAULT_TAROT_DAILY_LIMIT,
    DrawError,
)

__all__ = [
    "BAZI_PROJECTION_REVISION",
    "DEFAULT_BAZI_PREVIEW_LIMIT",
    "DEFAULT_BAZI_PREVIEW_WINDOW_SECONDS",
    "REST_BOT_ID",
    "BaziRateLimiter",
    "DivinationHttpFacade",
    "build_divination_facade_from_config",
    "principal_has_role",
]

# 控制面 REST 面的 bot 侧身份（运势 day_key 的 bot 分量；与聊天面 bot_id
# 天然隔离——控制面运势与聊天运势各自独立成行，互不挤占）。
REST_BOT_ID = "control_plane"

# 投影版本只描述投影形状（字段集），不冒充八字算法版本——算法语义以
# data/ganzhi.py 既有实现为准，本席零改动。
BAZI_PROJECTION_REVISION = "bazi-projection-v1"
BAZI_ALGORITHM_SOURCE = "domains/divination/data/ganzhi.py"

DEFAULT_BAZI_PREVIEW_LIMIT = 10
DEFAULT_BAZI_PREVIEW_WINDOW_SECONDS = 60.0

_ROLE_LEVELS: dict[str, int] = {
    role: level for level, role in enumerate(ROLE_ORDER) if role != ROLE_BLOCKED
}


def principal_has_role(roles: tuple[str, ...] | list[str], minimum: str) -> bool:
    """主体角色是否达到最低档（``blocked`` 一票否决，不参与比较）。"""
    minimum_level = _ROLE_LEVELS.get(str(minimum))
    if minimum_level is None:
        return False
    return any(
        role != ROLE_BLOCKED and _ROLE_LEVELS.get(role, -1) >= minimum_level
        for role in roles
    )


class BaziRateLimiter:
    """每主体固定窗限速（bazi/preview 专用防刷；线程安全）。"""

    def __init__(
        self,
        *,
        max_per_window: int = DEFAULT_BAZI_PREVIEW_LIMIT,
        window_seconds: float = DEFAULT_BAZI_PREVIEW_WINDOW_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max = max(1, int(max_per_window))
        self._window = max(0.001, float(window_seconds))
        self._clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def wait_seconds(self, principal_id: str) -> float:
        """登记一次命中；返回 0=放行，>0=需等待的秒数（未登记）。"""
        key = str(principal_id or "anonymous")
        now = float(self._clock())
        with self._lock:
            marks = self._hits.setdefault(key, deque())
            while marks and now - marks[0] >= self._window:
                marks.popleft()
            if len(marks) >= self._max:
                return max(0.001, self._window - (now - marks[0]))
            marks.append(now)
            return 0.0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class DivinationHttpFacade:
    """DivinationService 的 REST 薄壳：身份/时刻注入 + bazi 投影 + 政策投影。"""

    def __init__(
        self,
        service: DivinationService,
        *,
        bot_id: str = REST_BOT_ID,
        clock: Callable[[], datetime] | None = None,
        fortune_ready: bool = True,
        bazi_limiter: BaziRateLimiter | None = None,
        tarot_cooldown_seconds: int = DEFAULT_TAROT_COOLDOWN_SECONDS,
        tarot_daily_limit: int = DEFAULT_TAROT_DAILY_LIMIT,
    ) -> None:
        self.service = service
        self.bot_id = str(bot_id or REST_BOT_ID)
        self._clock = clock or _now_utc
        self.fortune_ready = bool(fortune_ready)
        self.bazi_limiter = bazi_limiter or BaziRateLimiter()
        self.tarot_cooldown_seconds = int(tarot_cooldown_seconds)
        self.tarot_daily_limit = int(tarot_daily_limit)

    # ── 抽取面 ─────────────────────────────────────────────────────────

    def draw(
        self,
        kind: str,
        payload: DivinationDrawPayload | Any,
        principal_id: str,
        idempotency_key: str,
    ) -> DrawResult:
        """通用抽取入口（别名端点在路由层预置 kind 后也走这里）。"""
        from plugins.bot_unified_runtime.domains.divination.service.divination_service import (
            DrawRequest,
        )

        if kind == "fortune" and not self.fortune_ready:
            # 密钥未配置：诚实拒绝，绝不退化为无密钥 HMAC（可被第三方离线复算）。
            raise DrawError("feature_disabled", "运势密钥尚未配置，先从塔罗开始吧")
        request = DrawRequest(
            kind="fortune" if kind == "fortune" else "tarot",
            spread_id=getattr(payload, "spread_id", None),
            question=getattr(payload, "question", "") or "",
            timezone_id=getattr(payload, "timezone_id", ""),
            workspace_id=getattr(payload, "workspace_id", "")
            or "default",
            idempotency_key=idempotency_key,
        )
        return self.service.create_draw(
            request, self._context_for(principal_id)
        )

    def get_draw(self, draw_id: str) -> DrawResult:
        return self.service.get_draw(draw_id)

    # ── bazi 只读投影 ─────────────────────────────────────────────────

    def bazi_preview(self, payload: BaziPreviewPayload, principal_id: str) -> dict[str, Any]:
        """既有八字算法只读投影：确定性、零持久化、零好感/日程副作用。"""
        wait = self.bazi_limiter.wait_seconds(principal_id)
        if wait > 0:
            raise DrawError("rate_limited", "排盘请求有点密，稍等片刻再来")
        from zoneinfo import ZoneInfo

        from plugins.bot_unified_runtime.domains.divination.data.ganzhi import (
            bazi_chart,
            format_bazi_text,
        )

        moment = datetime(
            payload.year,
            payload.month,
            payload.day,
            payload.hour,
            payload.minute,
            tzinfo=ZoneInfo(payload.timezone_id),
        )
        try:
            chart = bazi_chart(moment)
        except ValueError as exc:
            # 年份范围/节气范围等算法面拒绝 → validation_error（422）。
            raise DrawError("validation_error", str(exc)) from exc
        pillars = [
            {
                "pillar": pillar.name,
                "stem": pillar.stem,
                "branch": pillar.branch,
                "stem_element": pillar.stem_element,
                "zodiac": pillar.zodiac,
                "nayin": nayin,
            }
            for pillar, nayin in zip(
                chart.pillars,
                chart.nayin,
                strict=True,
            )
        ]
        return {
            "moment_cst": chart.moment.isoformat(),
            "requested_timezone": payload.timezone_id,
            "pillars": pillars,
            "element_counts": dict(chart.element_counts),
            "day_master": chart.day_master,
            "day_master_element": chart.day_master_element,
            "body_text": format_bazi_text(chart),
            "algorithm_source": BAZI_ALGORITHM_SOURCE,
            "projection_revision": BAZI_PROJECTION_REVISION,
            "disclaimer_id": DISCLAIMER_ID,
            "disclaimer_text": DISCLAIMER_TEXT,
        }

    # ── 投影面（capabilities/config 端点数据源）────────────────────────

    def policy_projection(self) -> dict[str, Any]:
        """管理面政策投影：版本/配额/边界口径（装配值为准）。"""
        return {
            "fortune_rule_version": FORTUNE_RULE_VERSION,
            "fortune_algorithm_revision": FORTUNE_ALGORITHM_REVISION,
            "tarot_algorithm_revision": TAROT_ALGORITHM_REVISION,
            "deck_revision": DECK_REVISION,
            "tarot_cooldown_seconds": self.tarot_cooldown_seconds,
            "tarot_daily_limit": self.tarot_daily_limit,
            "fortune_quota": "每日一次幂等，重读不限",
            "bazi_preview_limit_per_minute": self.bazi_limiter._max,
            "fortune_ready": self.fortune_ready,
            "disclaimer_id": DISCLAIMER_ID,
            "llm_interpretation": "not_wired",
            "side_effects": "不自动改好感度、不建日程、不触发交易动作",
        }

    def capabilities_projection(self) -> dict[str, Any]:
        """能力目录投影：端点/阵型白名单/牌库/配额/密钥轮换行为。"""
        deck_size = len(build_card_index())
        return {
            "kinds": {
                "fortune": {
                    "spread": "daily",
                    "grades": [
                        {"grade": grade, "weight": weight}
                        for grade, weight in FORTUNE_GRADES_V1
                    ],
                    "idempotency": "day_key（主体+bot+本地日期+规则版本）唯一：同日跨会话/跨幂等键/重启/密钥轮换恒返回既有结果，不重抽",
                    "key_rotation": "轮换 HMAC 密钥不更换 day_key：当天已抽取结果原样返回，新密钥自下一个本地日起生效",
                    "ready": self.fortune_ready,
                },
                "tarot": {
                    "spreads": {
                        spread_id: {
                            "count": count,
                            "positions": [
                                position for position in positions if position
                            ],
                        }
                        for spread_id, (count, positions) in SPREADS.items()
                    },
                    "orientation": "正逆位独立 Bernoulli(0.5)，拒绝采样实现",
                    "sampling": "Fisher-Yates 无放回",
                },
                "bazi": {
                    "mode": "preview_only",
                    "persistence": False,
                    "algorithm_source": BAZI_ALGORITHM_SOURCE,
                },
            },
            "deck": {"size": deck_size, "revision": DECK_REVISION},
            "position_labels": {
                spread_id: dict(labels)
                for spread_id, labels in POSITION_LABELS.items()
            },
            "quota": {
                "tarot_cooldown_seconds": self.tarot_cooldown_seconds,
                "tarot_daily_limit": self.tarot_daily_limit,
                "fortune": "每日一次幂等，重读不限",
                "bazi_preview_per_minute": self.bazi_limiter._max,
            },
            "interpretation": {
                "llm": "not_wired",
                "fallback": "local_interpretation_lines（持久牌面本地解读）",
            },
            "disclaimer_id": DISCLAIMER_ID,
            "disclaimer_text": DISCLAIMER_TEXT,
        }

    # ── 内部 ───────────────────────────────────────────────────────────

    def _context_for(self, principal_id: str) -> TrustedDrawContext:
        return TrustedDrawContext(
            principal_id=str(principal_id),
            bot_id=self.bot_id,
            now=self._clock(),
        )


def build_divination_facade_from_config(config: Any) -> DivinationHttpFacade | None:
    """装配期工厂：未配置持久化路径 → None（端点诚实 503，不落默认路径）。

    生产启用 = 配 ``bot_control_plane_divination_db``（经 runtime_paths 重映射，
    与 notes/media 同惯例）+ 可选 ``bot_divination_fortune_secret``（不配置则
    运势 409 feature_disabled、塔罗/bazi 照常）。缺键即缺功能，不猜路径、
    不写源码树。
    """
    db_path = getattr(config, "bot_control_plane_divination_db", None)
    if not db_path:
        return None
    from plugins.bot_unified_runtime.domains.divination.store.draw_store import (
        DrawStore,
    )

    store = DrawStore(db_path)
    secret = str(getattr(config, "bot_divination_fortune_secret", "") or "")
    return DivinationHttpFacade(
        DivinationService(store, secret=secret.encode("utf-8")),
        fortune_ready=bool(secret),
    )
