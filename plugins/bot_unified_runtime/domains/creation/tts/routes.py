"""语音合成 job 的中央缝 HTTP 入口（中央调度收编波 P4-C4，2026-09-23）。

一句话：本路由**只是门面**——受理契约请求、把它交给**唯一**中央 invoker、把执行
信封投影成 HTTP。真身全在别处：字段校验＝`domains/creation/tts/contracts.py`
（`TTSJobRequest`，本件不抄第二份判据），执行＝`runtime/capability_protocols`
的 `default_invoker()`。

三条硬约束（逐条有测试执法，见 `tests/test_control_plane_tts_api.py`）：

1. **唯一入口**——处理体内只准
   `default_invoker().invoke(CapabilityRequest(capability_id="creation.tts.synthesize", …))`。
   禁 import / 直调 `domains.creation.tts.engine_provider` 或
   `domains.media.capabilities.tts`：那就是第二条路（AGENTS 铁律 6「禁第二真身」
   在本面的形态）。结构锁用 AST 执法，行为锁用「给 engine_provider.handle 挂哨兵、
   断言它不被本路由碰到」执法——两种形态各拦一类绕法，缺一即假锁。
2. **绝不 200+空成功**——非成功终态一律 4xx/5xx + 稳定错误码 + 诚实说明
   （honest_degrade 口径：detail 必给，缺 provider 就说缺 provider）。
3. **零泄漏**——不回显 env 值、密钥、本机绝对路径（v1 模块家规：控制面「不暴露
   Runtime SQLite 文件、环境值或内部 Python 对象」）；成功态只投影身份/观测字段
   白名单，自由文本一律过 `redact_local_secrets`。

在册路由表（`contracts.py TTS_REST_ROUTES`）本件只挂两枚有真身的：
`POST /tts/jobs`（经中央缝合成）与 `GET /tts/jobs/{id}`（**诚实 503**——
creation 域没有任务态存储真身，不自建第二份、不拿「内存里刚跑完」猜状态）。
`providers`/`voices`/`capabilities`/`preview`/`cancel` 五枚要的是 provider 能力目录
与取消语义，其数据源尚未落地 ⇒ 本件**不**挂空壳路由充数（挂了就是假面），
交卷报告如实登记为残项。

⚠ 通电口径（不得叙述过头）：路由经中央 invoker ⇒ 普查账上 `creation.tts.synthesize`
自此有生产字面调用点（wired）；但 **控制面缺省关**（`bot_control_plane_enabled=False`）
⇒ 现网零流量。"执行面已通电"与"入口默认关"必须同行读。
"""
# ruff: noqa: B008
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from plugins.bot_unified_runtime.control_plane.api import ControlPlaneError
from plugins.bot_unified_runtime.control_plane.api.protocol import envelope
from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.domains.creation.tts.contracts import TTSJobRequest
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    CapabilityRequest,
    InvocationResult,
    InvocationStatus,
    default_invoker,
)

#: 本路由唯一允许调用的能力 id。**只作断言/文档用**——真正的调用点必须写**字面量串**：
#: 普查与直呼门（`orchestration_wired_census` / `central_seam_census` 的 `_invoker_cids`）
#: 认的是 AST 里的 `capability_id=` 常量，换成变量引用就"码照跑、账上不认"＝一笔假账。
#: 该形态由 tests/test_control_plane_tts_api.py 的 AST 尺钉死（本席实跑踩过：先写成
#: `capability_id=TTS_SYNTHESIS_CAPABILITY_ID` 时尺与普查同时看不见这个调用点）。
TTS_SYNTHESIS_CAPABILITY_ID = "creation.tts.synthesize"

#: 成功态 HTTP 投影白名单——**只留身份与观测字段**。
#: 刻意排除：``audio_file``（本机绝对路径，v1 家规不外泄）、``review_text``
#: （把用户内容再送回 HTTP 面无必要）、``audit_tags_delta``（内部审计面）。
#: ``audio_ready`` 由 ``audio_file`` 的**存在性**派生，绝不回显路径本身。
_RESULT_FIELDS: tuple[str, ...] = ("preset_id", "seed", "content_sha256", "audio_parts")

#: 成功终态族（与中央 `_SUCCESS_STATUSES` 同一集合语义，此处只作 HTTP 状态分流）。
_OK_STATUSES: frozenset[InvocationStatus] = frozenset(
    {InvocationStatus.OK, InvocationStatus.FALLBACK_OK}
)

#: 终态 → (HTTP 状态码, 稳定错误码)。逐态分派，**没有一态折叠成 200**。
#: 表本身即"绝不空成功"的结构证据：只要某态落在这张表里就必然带上错误码。
_FAILURE_HTTP: dict[InvocationStatus, tuple[int, str]] = {
    InvocationStatus.DENIED: (403, "tts_denied"),
    InvocationStatus.LIMIT_EXCEEDED: (413, "tts_limit_exceeded"),
    InvocationStatus.NOT_CONFIGURED: (503, "tts_not_configured"),
    InvocationStatus.UNAVAILABLE: (503, "tts_unavailable"),
    InvocationStatus.TIMEOUT: (504, "tts_timeout"),
    InvocationStatus.DEGRADED: (502, "tts_degraded"),
    InvocationStatus.FAILED: (502, "tts_failed"),
}


def _detail_of(invocation: InvocationResult) -> str:
    """诚实说明的唯一出口：过打码口后截断，绝不回原文异常/路径/密钥形态。"""
    text = str(invocation.detail or "").strip()
    if not text:
        # 中央信封构造期已拦「非成功态无 detail」；走到这里说明上游漏给——宁可说一句
        # 「没做成、原因没给」，也绝不静默、绝不留空串让调用方以为「成功但没内容」。
        text = f"终态 {invocation.status.value}，未给出原因（不应发生）"
    return redact_local_secrets(text)[:400]


def _projection(invocation: InvocationResult) -> dict[str, Any]:
    """成功态投影：信封归因 + 白名单身份字段 + 产物存在性布尔。"""
    data = invocation.data if isinstance(invocation.data, dict) else {}
    body: dict[str, Any] = {
        "capability_id": invocation.capability_id,
        "state": invocation.status.value,
        "via": invocation.via,
        "elapsed_ms": int(invocation.elapsed_ms),
        "attempts": int(invocation.attempts),
        # 存在性而非路径：调用方需要知道"真出了货"，不需要知道货在本机哪里。
        "audio_ready": bool(data.get("audio_file")),
        "detail": _detail_of(invocation),
    }
    for field in _RESULT_FIELDS:
        if field in data:
            body[field] = data[field]
    return body


def build_tts_router(
    *,
    config: Any | None,
    read_dependency: Any,
    write_dependency: Any,
) -> APIRouter:
    """构造 `/api/v1/tts/*` 路由；由 `api/v1.py` 挂在 `/api/v1` 前缀之下。

    ``config`` 与根装配同源（生产为 `Config` 实例，测试可为任何对象）：只经
    ``CapabilityRequest.context`` 交给执行体，本件**不**读它的字段——provider 判定
    的唯一家在其真身（`domains/creation/reserved_provider.py`），此处再判一次就是
    第二把尺子。
    """
    router = APIRouter()

    @router.post("/tts/jobs")
    def create_tts_job(
        job: TTSJobRequest, principal: Principal = Depends(write_dependency)
    ) -> dict[str, Any]:
        """提交一段合成任务：受理即同步过中央缝，成功才 200。

        `roles=()` 是刻意的：空角色＝**系统/内部主体**（中央权限门在册语义，
        不受人门约束、principal 原样入审计）。伪造 `("user",)` 去凑人门会让审计
        记上一个不存在的真人，比 DENIED 更坏。
        """
        invocation = default_invoker().invoke(
            CapabilityRequest(
                capability_id="creation.tts.synthesize",
                payload={"job": job},
                principal=f"control_plane:{getattr(principal, 'subject', '')}"[:128],
                roles=(),
                context={"config": config},
            )
        )
        if invocation.status in _OK_STATUSES:
            return envelope(_projection(invocation))
        status_code, code = _FAILURE_HTTP.get(invocation.status, (502, "tts_failed"))
        raise ControlPlaneError(
            status_code,
            # 未知终态不折叠成既有码：码面本身要能归因（兜底 code 带上游状态）。
            code if invocation.status in _FAILURE_HTTP else f"{code}:{invocation.status.value}",
            _detail_of(invocation),
        )

    @router.get("/tts/jobs/{job_id}")
    def read_tts_job(job_id: str, principal: Principal = Depends(read_dependency)) -> dict[str, Any]:
        """任务态轮询：**诚实 503**，不自建第二份状态。

        在册路由表要它，但 creation 域今天没有任何任务态存储真身（无 job store、
        无持久化状态机），而 `POST /tts/jobs` 是同步产出终态、不落库。此处若写一个
        内存字典，就是**第二份状态**——重启即失忆、多进程各记一套，比明说"没有"坏得多。
        因此本路由只证明"入口在册且可达"，绝不返回猜测出来的 job 状态。
        """
        del principal
        raise ControlPlaneError(
            503,
            "tts_job_state_unavailable",
            f"语音任务态存储真身未落地（同步产出，无 job store）：不给 {job_id} 编一个状态。",
        )

    return router
