"""AI 绘图 job 的中央缝 HTTP 入口（中央调度收编波 S262，2026-09-25）。

一句话：本路由**只是门面**——受理契约请求、把它交给**唯一**中央 invoker、把执行
信封投影成 HTTP。真身全在别处：字段校验＝`domains/creation/image/contracts.py`
（`ImageJobRequest`，本件不抄第二份判据），执行＝`runtime/capability_protocols`
的 `default_invoker()`（其回调体在 `domains/creation/image/engine_provider.handle`）。

本件兑现 SEAT-S252 `PROPOSAL-creation-visibility.md` §5 的面③ A 案：让「没接
provider」从 HTTP 503 就看得见（此前该缺席只有面① status 行 + 面② 巡检告警两条腿，
面③的 `INVOKER_ERROR_DATA_KEY`→诊断卡那条 raise 腿对绘画永不成立——它非路由命令形、
且全仓零生产 `invoke` 直呼点）。**照语音 `domains/creation/tts/routes.py` 同构落地**。

三条硬约束（逐条有测试执法，见 `tests/test_control_plane_image_api.py`）：

1. **唯一入口**——处理体内只准
   `default_invoker().invoke(CapabilityRequest(capability_id="creation.image.generate", …))`。
   禁 import / 直调 `domains.creation.image.engine_provider` 或
   `domains.creation.provider_factory` / `select_image_provider`：那就是第二条路
   （AGENTS 铁律 6「禁第二真身」在本面的形态）。结构锁用 AST 执法，行为锁用「给
   `engine_provider.handle` 挂哨兵、断言它不被本路由碰到」执法——两种形态各拦一类绕法，
   缺一即假锁。
   ⚠ 直呼点必须写**字面量串**，不能提成变量：普查与直呼门
   （`orchestration_wired_census` / `central_seam_census` 的 `_invoker_cids`）认的是
   AST 里的 `capability_id=` 常量，换成变量引用就「码照跑、账上不认」＝一笔假账。
   该形态由 `tests/test_control_plane_image_api.py` 的 AST 尺钉死（同 tts/routes.py:52-57
   已踩过的坑）。
2. **绝不 200+空成功**——非成功终态一律 4xx/5xx + 稳定错误码 + 诚实说明
   （honest_degrade 口径：detail 必给，缺 provider 就说缺 provider，点名待配键）。
3. **零泄漏**——不回显 env 值、密钥、本机绝对路径（v1 模块家规：控制面「不暴露
   Runtime SQLite 文件、环境值或内部 Python 对象」）；成功态只投影身份/观测字段
   白名单，自由文本一律过 `redact_local_secrets`。

在册路由表（`contracts.py IMAGE_REST_ROUTES`）本件**只挂两枚有真身的**：
`POST /image-generation/jobs`（经中央缝出图/诚实 503）与 `GET /image-generation/jobs/{id}`
（**诚实 503**——creation 域没有对外可读的任务态存储真身，不自建第二份、不拿
「内存里刚跑完」猜状态）。`providers`/`models`/`capabilities`/`preview`/`cancel` 五枚要
的是 provider 能力目录与取消语义，其数据源尚未落地 ⇒ 本件**不**挂空壳路由充数
（挂了就是假面，同 tts/routes.py:22-27 家规；SEAT-S252 §5.3 已显式登记这五枚零挂载）。

⚠ 通电口径（不得叙述过头）：路由经中央 invoker ⇒ 普查账上 `creation.image.generate`
自此有生产字面调用点（wired）；但 **控制面缺省关**（`bot_control_plane_enabled=False`）
⇒ 现网零流量。"执行面入口已通电"与"入口默认关"必须同行读。且**这不等于 chat 诊断卡**：
诊断卡只在 chat pipeline `_step` 的 `_internal_error`；本件给的是 **HTTP 面**可见性
（与语音 `POST /tts/jobs` 同级）。要在聊天里真出诊断卡，须另给绘画一枚 RouteKind 命令宿主
（`bot.draw`，`execution.adapter="command"`）——那会真改生产根路由表 + 真身册，超出本件范围，
清单见 `PROPOSAL-draw-command-host.md`（B 案，本席零落根代码）。
"""
# ruff: noqa: B008
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from plugins.bot_unified_runtime.control_plane.api import ControlPlaneError
from plugins.bot_unified_runtime.control_plane.api.protocol import envelope
from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.domains.creation.image.contracts import ImageJobRequest
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    PRESENTATION_DATA_KEY,
    CapabilityRequest,
    InvocationResult,
    InvocationStatus,
    default_invoker,
)

#: 本路由唯一允许调用的能力 id。**只作断言/文档用**——真正的调用点必须写**字面量串**：
#: 普查与直呼门认的是 AST 里的 `capability_id=` 常量，换成变量引用就"码照跑、账上不认"
#: ＝一笔假账。该形态由 tests/test_control_plane_image_api.py 的 AST 尺钉死。
IMAGE_GENERATION_CAPABILITY_ID = "creation.image.generate"

#: 成功态 HTTP 投影白名单——**只留身份/观测字段**（从中央呈现信封里挑）。
#: 刻意排除：`assets`（AssetRef 列表——不外泄结构，只投影**件数**）、`usage`
#: （计费明细，属内部对账面）、`cancel_requested(_at)`（控制面不驱动取消）。
#: 这些字段本身不含密钥/路径（AssetRef pattern 已拒路径/URL/穿越），但 HTTP 面无
#: 必要把整包结果结构原样吐回去——与语音侧「存在性而非路径」同一克制。
_RESULT_FIELDS: tuple[str, ...] = ("job_id", "provider_operation", "error_code")

#: 成功终态族（与中央 `_SUCCESS_STATUSES` 同一集合语义，此处只作 HTTP 状态分流）。
_OK_STATUSES: frozenset[InvocationStatus] = frozenset(
    {InvocationStatus.OK, InvocationStatus.FALLBACK_OK}
)

#: 终态 → (HTTP 状态码, 稳定错误码)。逐态分派，**没有一态折叠成 200**。
#: 表本身即"绝不空成功"的结构证据：只要某态落在这张表里就必然带上错误码。
#: UNAVAILABLE→503 `image_not_wired` 是本件存在的理由：缺 provider 在 HTTP 面显式可见。
_FAILURE_HTTP: dict[InvocationStatus, tuple[int, str]] = {
    InvocationStatus.DENIED: (403, "image_denied"),
    InvocationStatus.LIMIT_EXCEEDED: (413, "image_limit_exceeded"),
    InvocationStatus.NOT_CONFIGURED: (503, "image_not_configured"),
    InvocationStatus.UNAVAILABLE: (503, "image_not_wired"),
    InvocationStatus.TIMEOUT: (504, "image_timeout"),
    InvocationStatus.DEGRADED: (502, "image_degraded"),
    InvocationStatus.FAILED: (502, "image_failed"),
}


def _detail_of(invocation: InvocationResult) -> str:
    """诚实说明的唯一出口：过打码口后截断，绝不回原文异常/路径/密钥形态。

    未接 provider 时，中央信封的 detail 已由 `reserved_provider.not_wired_detail`
    造好（原因＋待配**键名**、零值），本件只过 `redact_local_secrets` 再截断——
    **不在这里重拼"待配键"**，否则又是一处第二真身（两通道文案会漂）。
    """
    text = str(invocation.detail or "").strip()
    if not text:
        # 中央信封构造期已拦「非成功态无 detail」；走到这里说明上游漏给——宁可说一句
        # 「没做成、原因没给」，也绝不静默、绝不留空串让调用方以为「成功但没内容」。
        text = f"终态 {invocation.status.value}，未给出原因（不应发生）"
    return redact_local_secrets(text)[:400]


def _presentation(invocation: InvocationResult) -> dict[str, Any]:
    """取中央呈现信封里的 job 快照（`PRESENTATION_DATA_KEY`），非 dict 一律当空。"""
    data = invocation.data if isinstance(invocation.data, dict) else {}
    pres = data.get(PRESENTATION_DATA_KEY)
    return pres if isinstance(pres, dict) else {}


def _projection(invocation: InvocationResult) -> dict[str, Any]:
    """成功态投影：信封归因 + 白名单身份字段 + 产物**件数**（不吐结构）。"""
    pres = _presentation(invocation)
    assets = pres.get("assets")
    body: dict[str, Any] = {
        "capability_id": invocation.capability_id,
        "state": invocation.status.value,
        "via": invocation.via,
        "elapsed_ms": int(invocation.elapsed_ms),
        "attempts": int(invocation.attempts),
        # 件数而非结构：调用方需要知道"真出了几件货"，不需要知道 asset 列表本身。
        "asset_count": len(assets) if isinstance(assets, (list, tuple)) else 0,
        "detail": _detail_of(invocation),
    }
    for field in _RESULT_FIELDS:
        if field in pres:
            body[field] = pres[field]
    return body


def build_image_router(
    *,
    config: Any | None,
    read_dependency: Any,
    write_dependency: Any,
) -> APIRouter:
    """构造 `/api/v1/image-generation/*` 路由；由 `api/v1.py` 挂在 `/api/v1` 前缀之下。

    ``config`` 与根装配同源（生产为 `Config` 实例，测试可为任何对象）：只经
    ``CapabilityRequest.context`` 交给执行体，本件**不**读它的字段——provider 判定
    的唯一家在其真身（`domains/creation/reserved_provider.py`），此处再判一次就是
    第二把尺子。
    """
    router = APIRouter()

    @router.post("/image-generation/jobs")
    def create_image_job(
        job: ImageJobRequest, principal: Principal = Depends(write_dependency)
    ) -> dict[str, Any]:
        """提交一段绘图任务：受理即同步过中央缝，成功才 200，缺 provider 诚实 503。

        `roles=()` 是刻意的：空角色＝**系统/内部主体**（中央权限门在册语义，
        不受人门约束、principal 原样入审计）。伪造 `("user",)` 去凑人门会让审计
        记上一个不存在的真人，比 DENIED 更坏。
        """
        invocation = default_invoker().invoke(
            CapabilityRequest(
                capability_id="creation.image.generate",
                payload={"job": job},
                principal=f"control_plane:{getattr(principal, 'subject', '')}"[:128],
                roles=(),
                context={"config": config},
            )
        )
        if invocation.status in _OK_STATUSES:
            return envelope(_projection(invocation))
        status_code, code = _FAILURE_HTTP.get(invocation.status, (502, "image_failed"))
        raise ControlPlaneError(
            status_code,
            # 未知终态不折叠成既有码：码面本身要能归因（兜底 code 带上游状态）。
            code if invocation.status in _FAILURE_HTTP else f"{code}:{invocation.status.value}",
            _detail_of(invocation),
        )

    @router.get("/image-generation/jobs/{job_id}")
    def read_image_job(job_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        """任务态轮询：**诚实 503**，不自建第二份状态。

        在册路由表要它（`IMAGE_REST_ROUTES` 第 6 枚），但 creation 域今天没有任何
        **对外可读**的任务态存储真身（`_common/job_store` 是执行侧账、不对外经 HTTP），
        而 `POST /image-generation/jobs` 同步产出终态、不在 HTTP 面维护 job store。此处
        若写一个内存字典，就是**第二份状态**——重启即失忆、多进程各记一套，比明说"没有"
        坏得多。因此本路由只证明"入口在册且可达"，绝不返回猜测出来的 job 状态。
        """
        del principal
        raise ControlPlaneError(
            503,
            "image_job_state_unavailable",
            f"绘图任务态 HTTP 存储真身未落地（同步产出，无对外 job store）：不给 {job_id} 编一个状态。",
        )

    return router
