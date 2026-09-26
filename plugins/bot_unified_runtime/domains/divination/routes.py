"""占卜/运势 REST 路由段（V2.1 S12）；薄 HTTP 投影，业务逻辑全在域内。

合同来源：backend-v2-product-extensions.md §3（GET /divination/capabilities、
POST /divination/draws、GET /divination/draws/{id}）+ implementation-guide §6
（统一 envelope / Idempotency-Key 头 / 错误协议）。

- 形态对齐既有 ``api/actions.py`` / ``api/platform.py``：独立 ``build_*_router``，
  由 ``_app.py`` 挂载（platform 前例），不改 v1.py 签名。
- RBAC：读面（capabilities/draws/fortune/tarot/bazi/interpretation）= user+；
  管理面（config 政策投影）= admin+（``policy.roles`` 六级序内检）。
- 审计钩子：每请求一条 ``control_plane_audit``（fail-open，审计故障不影响
  响应）；detail 只记 kind/draw_id/码，不记 question 正文（隐私最小化）。
- 频控：塔罗/运势=draw_store 额度语义（服务层事务内判定）；bazi/preview=
  域内每主体固定窗限速。
"""

# ruff: noqa: B008
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, Request

from plugins.bot_unified_runtime.control_plane.api import ControlPlaneError
from plugins.bot_unified_runtime.control_plane.api.protocol import (
    ERROR_RESPONSES,
    envelope,
)
from plugins.bot_unified_runtime.control_plane.audit import redact_query
from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.domains.divination.api.dto import (
    BaziPreviewPayload,
    DivinationDrawPayload,
    FortuneDailyPayload,
    TarotDrawPayload,
    validate_idempotency_key,
)
from plugins.bot_unified_runtime.domains.divination.api.errors import (
    InterpretationNotWiredError,
    project_draw_error,
)
from plugins.bot_unified_runtime.domains.divination.api.facet import (
    DivinationHttpFacade,
    principal_has_role,
)
from plugins.bot_unified_runtime.domains.divination.projection import (
    pick_pending_line,
)
from plugins.bot_unified_runtime.domains.divination.service.divination_service import (
    DISCLAIMER_TEXT,
    DrawResult,
)
from plugins.bot_unified_runtime.domains.divination.store.draw_store import DrawError

_ADMIN_ROLE = "admin"
_USER_ROLE = "user"

logger = logging.getLogger(__name__)


def build_divination_router(
    *,
    facade: DivinationHttpFacade | None,
    read_dependency: Any,
    audit_store: Any | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/divination", responses=ERROR_RESPONSES)

    def require_facade() -> DivinationHttpFacade:
        if facade is None:
            raise ControlPlaneError(
                503,
                "divination_unavailable",
                "占卜服务尚未装配（未配置持久化路径），先不假装能抽牌。",
            )
        return facade

    def ensure_role(principal: Principal, minimum: str) -> None:
        if not principal_has_role(principal.roles, minimum):
            raise ControlPlaneError(
                403,
                "permission_denied",
                "这件事超出了你现在的权限，先到这里为止了。",
            )

    def audit(
        request: Request, principal: Principal, status_code: int, detail: str = ""
    ) -> None:
        if audit_store is None:
            return
        try:
            audit_store.record(
                subject=principal.subject,
                source="control_plane",
                method=request.method,
                path=request.url.path,
                query=redact_query(str(request.url.query or "")),
                status_code=int(status_code),
                detail=str(detail or "")[:500],
            )
        except Exception:  # 审计故障绝不影响响应（record 已吞，此处双保险）。
            logger.debug("divination audit hook failed", exc_info=True)

    def raise_draw_error(exc: DrawError) -> ControlPlaneError:
        projection = project_draw_error(exc)
        return ControlPlaneError(
            projection.status_code, projection.code, projection.message
        )

    def draw_response(result: DrawResult) -> dict[str, Any]:
        data = result.to_dict()
        data["disclaimer_text"] = DISCLAIMER_TEXT
        return data

    # ── 能力目录（user+）────────────────────────────────────────────────

    @router.get("/capabilities")
    def capabilities(
        request: Request, principal: Principal = Depends(read_dependency)
    ) -> dict[str, Any]:
        service = require_facade()
        audit(request, principal, 200, "capabilities")
        return envelope(service.capabilities_projection())

    # ── 管理面：政策投影（admin+）──────────────────────────────────────

    @router.get("/config")
    def policy_config(
        request: Request, principal: Principal = Depends(read_dependency)
    ) -> dict[str, Any]:
        service = require_facade()
        try:
            ensure_role(principal, _ADMIN_ROLE)
        except ControlPlaneError as exc:
            audit(request, principal, exc.status_code, "config denied")
            raise
        audit(request, principal, 200, "config")
        return envelope(service.policy_projection())

    # ── 通用抽取（user+；Idempotency-Key 头必填）────────────────────────

    @router.post("/draws")
    def create_draw(
        payload: DivinationDrawPayload,
        request: Request,
        principal: Principal = Depends(read_dependency),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return _draw_once(payload.kind, payload, request, principal, idempotency_key)

    # ── 别名字形（user+；kind 预置）────────────────────────────────────

    @router.post("/fortune/daily")
    def fortune_daily(
        payload: FortuneDailyPayload,
        request: Request,
        principal: Principal = Depends(read_dependency),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return _draw_once("fortune", payload, request, principal, idempotency_key)

    @router.post("/tarot/draw")
    def tarot_draw(
        payload: TarotDrawPayload,
        request: Request,
        principal: Principal = Depends(read_dependency),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return _draw_once("tarot", payload, request, principal, idempotency_key)

    # ── 读取与解读席位（user+）──────────────────────────────────────────

    @router.get("/draws/{draw_id}")
    def get_draw(
        draw_id: str,
        request: Request,
        principal: Principal = Depends(read_dependency),
    ) -> dict[str, Any]:
        service = require_facade()
        try:
            result = service.get_draw(draw_id)
        except DrawError as exc:
            projection = project_draw_error(exc)
            audit(request, principal, projection.status_code, f"get code={projection.code}")
            raise raise_draw_error(exc) from exc
        audit(request, principal, 200, f"get draw_id={result.draw_id}")
        return envelope(draw_response(result))

    @router.post("/draws/{draw_id}/interpretation")
    def interpret_draw(
        draw_id: str,
        request: Request,
        principal: Principal = Depends(read_dependency),
    ) -> dict[str, Any]:
        service = require_facade()
        try:
            service.get_draw(draw_id)  # 先证 draw 存在（404 优先于 not_wired）
        except DrawError as exc:
            projection = project_draw_error(exc)
            audit(request, principal, projection.status_code, "interpret miss")
            raise raise_draw_error(exc) from exc
        pending = pick_pending_line(draw_id)
        audit(request, principal, 503, "interpret not_wired")
        not_wired = InterpretationNotWiredError(
            f"{pending}（娱乐参考口径见牌面本地解读；本端点当前固定返回 503。）"
        )
        raise ControlPlaneError(
            not_wired.status_code, not_wired.code, not_wired.message
        ) from not_wired

    # ── bazi 只读投影（user+）──────────────────────────────────────────

    @router.post("/bazi/preview")
    def bazi_preview(
        payload: BaziPreviewPayload,
        request: Request,
        principal: Principal = Depends(read_dependency),
    ) -> dict[str, Any]:
        service = require_facade()
        try:
            data = service.bazi_preview(payload, principal.subject)
        except DrawError as exc:
            projection = project_draw_error(exc)
            audit(request, principal, projection.status_code, f"bazi code={projection.code}")
            raise raise_draw_error(exc) from exc
        audit(request, principal, 200, "bazi preview")
        return envelope(data)

    # ── 内部：统一抽取路径 ─────────────────────────────────────────────

    def _draw_once(
        kind: str,
        payload: Any,
        request: Request,
        principal: Principal,
        idempotency_key: str,
    ) -> dict[str, Any]:
        service = require_facade()
        try:
            key = validate_idempotency_key(idempotency_key)
        except ValueError as exc:
            audit(request, principal, 422, "draw bad idempotency key")
            raise ControlPlaneError(422, "validation_error", str(exc)) from exc
        try:
            result = service.draw(kind, payload, principal.subject, key)
        except DrawError as exc:
            projection = project_draw_error(exc)
            audit(
                request,
                principal,
                projection.status_code,
                f"draw kind={kind} code={projection.code}",
            )
            raise raise_draw_error(exc) from exc
        audit(
            request,
            principal,
            200,
            f"draw kind={result.kind} draw_id={result.draw_id}",
        )
        return envelope(draw_response(result))

    return router
