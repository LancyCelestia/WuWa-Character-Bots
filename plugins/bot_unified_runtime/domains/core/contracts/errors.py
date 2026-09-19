"""V2.1 错误注册表：全系统错误码单一注册源（S2 协议席）。

合同来源：
- docs/design/backend-v2-implementation-guide.md §6 错误表（「错误目录为单一注册源」）
- docs/design/backend-v2-product-extensions.md 补充错误集中注册段

设计约束（V21-CORE-001）：
- 本模块只依赖标准库（dataclasses/datetime/uuid），连 pydantic 都不碰；
  error_envelope 产出的 dict 由 contracts/envelope.py 的严格模型负责校验，
  两侧契约漂移会被 tests/test_contracts_v21.py 的往返断言拦下。
- 每条注册：code / http 状态（delivery_unknown 按规范以任务/part 状态暴露，
  不映射顶层 HTTP，故为 None）/ retryable 默认 / 人话 message 模板
  （守岸人语气、不泄露内部细节、可操作）。
- 旧码兼容映射留接口：LEGACY_CODE_ALIASES + resolve_code；别名目标在导入期
  自检必须存在于注册表，防漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class UnknownErrorCodeError(KeyError):
    """请求了注册表中不存在的错误码。"""


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    # None = 不映射顶层 HTTP（如 delivery_unknown：按任务/part 状态暴露）。
    http_status: int | None
    retryable: bool
    # 人话模板；{占位符} 由调用方字段插值，缺失占位符保持字面量不抛错。
    message_template: str


_ERROR_SPECS: tuple[ErrorSpec, ...] = (
    # ---- 主规范 §6 错误表 ----
    ErrorSpec("unauthenticated", 401, False, "我还认不出你是谁，请先完成登录再来找我吧。"),
    ErrorSpec("permission_denied", 403, False, "这件事超出了你现在的权限，先到这里为止了。"),
    ErrorSpec("resource_not_found", 404, False, "要找的东西不存在，或者不属于你能看到的范围。"),
    ErrorSpec("validation_error", 422, False, "有些内容没有通过检查，请按提示修正后再试一次。"),
    ErrorSpec("unsupported_parameter", 422, False, "这个选项这里用不上，请核对可用的参数。"),
    ErrorSpec("content_rejected", 422, False, "这份内容我没有办法受理，请调整后再发给我。"),
    ErrorSpec("unsupported_format", 415, False, "这种格式我还读不了，请换成支持的格式。"),
    ErrorSpec("version_conflict", 409, False, "内容刚被更新过了（当前版本 {expected_version}），请刷新最新状态再操作。"),
    ErrorSpec("idempotency_conflict", 409, False, "这个请求键已经绑定过别的内容，请换一个键或核对原文。"),
    ErrorSpec("confirmation_required", 409, False, "这一步需要你先确认才能继续，请先完成确认。"),
    ErrorSpec("confirmation_expired", 409, False, "确认已经过期了，请重新确认一次。"),
    ErrorSpec("feature_disabled", 409, False, "这个功能现在处于关闭状态，请先启用后再使用。"),
    ErrorSpec("cancel_not_supported", 409, False, "这件事不支持取消，我只能如实告诉你，不会假装取消成功。"),
    ErrorSpec("rate_limited", 429, True, "节奏有点太快了，稍等片刻再来找我就好。"),
    ErrorSpec("capacity_exceeded", 429, True, "现在有点忙不过来，请稍后再试。"),
    ErrorSpec("dependency_unavailable", 503, True, "上游服务暂时不在，我先停在这里，等恢复了再继续。"),
    ErrorSpec("sandbox_unavailable", 503, True, "隔离沙盒暂时不可用，相关操作先停下来了。"),
    ErrorSpec("provider_auth_failed", 503, False, "上游的凭据没有通过验证，需要管理员检查后再继续。"),
    ErrorSpec("storage_unavailable", 503, True, "存储暂时不可用，相关写入先停下了，稍后会恢复。"),
    ErrorSpec("provider_rate_limited", 503, True, "上游在限流，我会按它的节奏等待，稍后再继续。"),
    ErrorSpec("resource_limit_exceeded", 503, True, "资源额度用完了，等回收释放之后再继续。"),
    ErrorSpec("integrity_mismatch", 503, False, "数据校验对不上，相关内容已隔离保存，请先排查来源。"),
    ErrorSpec("reload_failed", 503, True, "这次重载没有完成，旧版本仍在正常服务，可以再试一次。"),
    ErrorSpec("rollback_failed", 503, False, "回退没有成功，系统已停在安全状态，请尽快人工处理。"),
    ErrorSpec("deadline_exceeded", 504, True, "等得太久了，这次先停在这里，需要的话可以重新发起。"),
    ErrorSpec("output_contract_violation", 502, False, "这次输出没有通过格式检查，已按约定做了兜底处理。"),
    ErrorSpec("delivery_unknown", None, False, "发送结果还不确定，需要先对账确认，而不是盲目重发。"),
    # ---- 扩展补充码（backend-v2-product-extensions.md）----
    ErrorSpec("usage_inconsistent", 502, False, "用量账目对不上，先挂起核对，不会把异常掩盖成零。"),
    ErrorSpec("price_unavailable", 503, False, "这个模型暂时没有可靠价格，付费任务先不受理。"),
    ErrorSpec("budget_exceeded", 429, False, "预算已经用完了，需要新的授权才能继续。"),
    ErrorSpec("affinity_unit_mismatch", 422, False, "好感度数据的计量单位对不上，先停在这里，不做折算猜测。"),
    ErrorSpec("affinity_evidence_missing", 409, False, "这次好感度变化缺少依据，先按中性处理，不凭空加减。"),
    ErrorSpec("invalid_spread", 422, False, "这次的牌面组合不成立，请重新抽取一次。"),
    ErrorSpec("deck_integrity_mismatch", 503, False, "牌库校验对不上，先停用整理，不拿坏牌占卜。"),
    ErrorSpec("schedule_cycle", 422, False, "安排里存在循环依赖，请先解开这个环。"),
    ErrorSpec("missing_calendar", 409, False, "缺少对应的日历，请先补齐再来安排。"),
    ErrorSpec("ambiguous_local_time", 422, False, "这个时间点有歧义，请指定得更明确一些。"),
    ErrorSpec("schedule_conflict", 409, False, "这个安排和已有日程冲突，请调整一下时间。"),
    ErrorSpec("occurrence_expired", 409, False, "这一项已经过期了，请重新创建新的安排。"),
    ErrorSpec("unsupported_platform_capability", 422, False, "这个平台暂时做不到这件事，我不会假装发送成功。"),
    ErrorSpec("acceptance_authorization_expired", 403, False, "验收授权已经过期，请重新授权后再继续。"),
)

ERROR_REGISTRY: dict[str, ErrorSpec] = {spec.code: spec for spec in _ERROR_SPECS}

# 旧码兼容映射：{旧码: 现行码}。目标必须在 ERROR_REGISTRY 中（下方导入期自检）。
LEGACY_CODE_ALIASES: dict[str, str] = {}

for _alias, _target in LEGACY_CODE_ALIASES.items():
    if _target not in ERROR_REGISTRY:
        raise RuntimeError(f"旧码别名 {_alias!r} 指向未注册的错误码 {_target!r}")


def iter_error_codes() -> tuple[str, ...]:
    return tuple(ERROR_REGISTRY)


def get_error_spec(code: str) -> ErrorSpec:
    spec = ERROR_REGISTRY.get(resolve_code(code))
    if spec is None:  # pragma: no cover - resolve_code 已保证
        raise UnknownErrorCodeError(code)
    return spec


def resolve_code(code: str) -> str:
    """旧码 -> 现行码；未注册码抛 UnknownErrorCodeError。"""
    canonical = LEGACY_CODE_ALIASES.get(code, code)
    if canonical not in ERROR_REGISTRY:
        raise UnknownErrorCodeError(code)
    return canonical


class _SafeDict(dict):
    """模板插值安全兜底：缺失占位符保持 {字面量}，不抛 KeyError。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def new_request_id() -> str:
    return f"req_{uuid4().hex[:12]}"


def new_trace_id() -> str:
    return f"trace_{uuid4().hex[:12]}"


def new_debug_id() -> str:
    return f"dbg_{uuid4().hex[:12]}"


def _render_message(spec: ErrorSpec, override: str | None, fields: dict[str, Any]) -> str:
    if override is not None:
        normalized = override.strip()
        if not normalized:
            raise ValueError("message 覆盖不能为空白")
        return normalized
    if fields:
        return spec.message_template.format_map(_SafeDict(fields))
    return spec.message_template


def error_body(
    code: str,
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    debug_id: str | None = None,
    message: str | None = None,
    retryable: bool | None = None,
    field_errors: list[dict[str, str]] | None = None,
    **template_fields: Any,
) -> dict[str, Any]:
    """构造 §6 七键错误体（dict 形态，由 envelope.ErrorBody 校验契约）。"""
    spec = get_error_spec(code)
    return {
        "code": spec.code,
        "message": _render_message(spec, message, template_fields),
        "request_id": request_id or new_request_id(),
        "trace_id": trace_id or new_trace_id(),
        "debug_id": debug_id or new_debug_id(),
        "retryable": spec.retryable if retryable is None else bool(retryable),
        "field_errors": list(field_errors) if field_errors else [],
    }


def error_envelope(
    code: str,
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    debug_id: str | None = None,
    message: str | None = None,
    retryable: bool | None = None,
    field_errors: list[dict[str, str]] | None = None,
    **template_fields: Any,
) -> dict[str, Any]:
    """构造完整错误 envelope（data=None；meta 与 error 的 ID 保持一致传播）。"""
    body = error_body(
        code,
        request_id=request_id,
        trace_id=trace_id,
        debug_id=debug_id,
        message=message,
        retryable=retryable,
        field_errors=field_errors,
        **template_fields,
    )
    generated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return {
        "data": None,
        "error": body,
        "meta": {
            "request_id": body["request_id"],
            "trace_id": body["trace_id"],
            "schema_version": "v1",
            "generated_at": generated_at,
        },
    }
