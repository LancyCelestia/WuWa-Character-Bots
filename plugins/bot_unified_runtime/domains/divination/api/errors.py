"""V2.1 S12 域错误 → REST 错误投影（只读消费 contracts 错误注册表）。

- DrawError 的码全部取自 ``domains/core/contracts/errors.py`` 注册表（W5 约束）；
  本模块只把 (码 → HTTP 状态/retryable/人话兜底) 投影出来，不注册新全局码。
- ``not_wired``（LLM 解释未接线）按控制面本码前例处理
  （config_store_unavailable / traces_unavailable 同类，不入全局注册表）——
  诚实位是交付的一部分：没接线就明说没接线，不冒充模型解读。
"""

from __future__ import annotations

from dataclasses import dataclass

from plugins.bot_unified_runtime.domains.core.contracts.errors import ERROR_REGISTRY
from plugins.bot_unified_runtime.domains.divination.store.draw_store import DrawError

__all__ = [
    "INTERPRETATION_NOT_WIRED_CODE",
    "INTERPRETATION_NOT_WIRED_STATUS",
    "HttpErrorProjection",
    "InterpretationNotWiredError",
    "project_draw_error",
]

INTERPRETATION_NOT_WIRED_CODE = "not_wired"
INTERPRETATION_NOT_WIRED_STATUS = 503


@dataclass(frozen=True)
class HttpErrorProjection:
    """一次域错误的 REST 投影（状态/码/人话/可重试）。"""

    status_code: int
    code: str
    message: str
    retryable: bool


class InterpretationNotWiredError(Exception):
    """LLM 人格化解释席位未接线（诚实 503，回落面=本地牌面解读）。"""

    def __init__(self, message: str = "") -> None:
        super().__init__(message or "人格化解读尚未接线")
        self.code = INTERPRETATION_NOT_WIRED_CODE
        self.status_code = INTERPRETATION_NOT_WIRED_STATUS
        self.message = message or "人格化解读尚未接线"

    @property
    def projection(self) -> HttpErrorProjection:
        return HttpErrorProjection(
            status_code=self.status_code,
            code=self.code,
            message=self.message,
            retryable=False,
        )


def project_draw_error(exc: DrawError) -> HttpErrorProjection:
    """DrawError → REST 投影；状态/可重试只信注册表，不临场发明。

    服务层的人话 message 优先（更具体），空/退化为码名时回落注册表模板。
    """
    spec = ERROR_REGISTRY.get(exc.code)
    if spec is None or spec.http_status is None:
        # 防御分支：divination 域不应产生未注册/无 HTTP 映射的码；
        # 即便发生也按 500 诚实暴露码名，不吞不换。
        return HttpErrorProjection(
            status_code=500,
            code=exc.code or "internal_error",
            message=exc.message or exc.code,
            retryable=False,
        )
    message = exc.message if exc.message and exc.message != exc.code else (
        spec.message_template
    )
    return HttpErrorProjection(
        status_code=spec.http_status,
        code=exc.code,
        message=message,
        retryable=spec.retryable,
    )
