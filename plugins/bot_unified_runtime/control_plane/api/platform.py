# ruff: noqa: B008
"""WebUI platform protocol: versioned resources, traces, usage and media contracts."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..api import ControlPlaneError
from ..auth import Principal
from ..platform import PlatformService, PlatformStore
from .protocol import envelope

RESOURCE_KINDS = (
    "persona_profiles",
    "worlds",
    "worldbooks",
    "references",
    "knowledge_bases",
    "memories",
    "databases",
    "media_capabilities",
    "file_capabilities",
    "search_providers",
)

LIFECYCLE_KINDS = ("persona_profiles", "worlds", "worldbooks", "references")
LIFECYCLE_ACTIONS = ("draft", "publish", "rollback", "activate", "versions")


def build_platform_router(
    *,
    store: PlatformStore,
    read_dependency: Any,
    write_dependency: Any,
    prefix: str = "",
    config: object | None = None,
    log_level_setter: Any | None = None,
) -> APIRouter:
    service = PlatformService(store)
    r = APIRouter(prefix=prefix)

    # V21-risk-1：处理器一律经工厂闭包捕获 kind/action 等内部判别值，
    # principal 只以 Depends 出现（或由路由级 dependencies 承担鉴权），
    # _kind/_action 不再以可被 ?query 覆盖的默认参数进入签名。

    def _make_list(kind: str) -> Callable[[], dict[str, Any]]:
        def list_handler() -> dict[str, Any]:
            return envelope(service.list_resources(kind))

        return list_handler

    def _make_get(kind: str) -> Callable[[str], dict[str, Any]]:
        def get_handler(resource_id: str) -> dict[str, Any]:
            current = service.get_resource(kind, resource_id)
            if current is None:
                raise ControlPlaneError(404, "resource_not_found", "资源不存在。")
            return envelope(current)

        return get_handler

    def _make_upsert(kind: str) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
        async def upsert(
            payload: dict[str, Any], resource_id: str
        ) -> dict[str, Any]:
            expected = payload.pop("expected_version", None)
            try:
                return envelope(
                    service.put_resource(kind, resource_id, payload, expected)
                )
            except ValueError as exc:
                raise ControlPlaneError(
                    409, "version_conflict", "资源版本冲突。"
                ) from exc

        return upsert

    for kind in RESOURCE_KINDS:
        path = kind.replace("_", "-")
        r.add_api_route(
            f"/{path}",
            _make_list(kind),
            methods=["GET"],
            dependencies=[Depends(read_dependency)],
        )
        r.add_api_route(
            f"/{path}/{{resource_id}}",
            _make_get(kind),
            methods=["GET"],
            dependencies=[Depends(read_dependency)],
        )
        r.add_api_route(
            f"/{path}/{{resource_id}}",
            _make_upsert(kind),
            methods=["PUT"],
            dependencies=[Depends(write_dependency)],
        )

    @r.get("/traces")
    def traces(
        limit: int = Query(100, ge=1, le=1000),
        principal: Principal = Depends(read_dependency),
    ):
        return envelope({"items": service.rows("traces", limit)})

    @r.get("/traces/{trace_id}")
    def trace(trace_id: str, principal: Principal = Depends(read_dependency)):
        items = [
            x
            for x in service.rows("traces", 1000)
            if x.get("trace_id") == trace_id or x.get("id") == trace_id
        ]
        if not items:
            raise ControlPlaneError(404, "trace_not_found", "轨迹不存在。")
        return envelope(items[0])

    for suffix in ("timeline", "context", "model-calls", "deliveries"):

        @r.get(f"/traces/{{trace_id}}/{suffix}")
        def trace_part(
            trace_id: str,
            suffix=suffix,
            principal: Principal = Depends(read_dependency),
        ):
            return envelope({"trace_id": trace_id, "stage": suffix, "items": []})

    @r.get("/usage")
    def usage(
        limit: int = Query(100, ge=1, le=1000),
        principal: Principal = Depends(read_dependency),
    ):
        return envelope({"items": service.rows("usage", limit)})

    @r.get("/model-calls")
    def model_calls(
        limit: int = Query(100, ge=1, le=1000),
        principal: Principal = Depends(read_dependency),
    ):
        return envelope({"items": service.rows("model_calls", limit)})

    @r.post("/logs/level")
    def log_level(
        payload: dict[str, Any], principal: Principal = Depends(write_dependency)
    ):
        level = payload.get("level")
        allowed = {"debug", "info", "warning", "error", "success", "critical", "detail"}
        if level not in allowed:
            raise ControlPlaneError(422, "validation_error", "日志级别无效。")
        if log_level_setter is not None:
            try:
                outcome = log_level_setter(str(level))
            except (TypeError, ValueError) as exc:
                raise ControlPlaneError(
                    422, "logging_level_rejected", "日志级别无法应用。"
                ) from exc
            # V21-risk-3 补口：setter 显式自报失败（返回 False）必须如实上报，
            # 不得在未验证生效的情况下假称 applied。
            if outcome is False:
                return envelope(
                    {"level": level, "applied": False, "reason": "setter_reported_failure"}
                )
            return envelope({"level": level, "applied": True})
        # V21-risk-3：setter 未装配必须如实上报，不得假称已应用。
        return envelope(
            {"level": level, "applied": False, "reason": "setter_not_configured"}
        )

    @r.post("/traces")
    def create_trace(
        payload: dict[str, Any], principal: Principal = Depends(write_dependency)
    ):
        return envelope(service.append("traces", payload))

    @r.post("/usage")
    def create_usage(
        payload: dict[str, Any], principal: Principal = Depends(write_dependency)
    ):
        return envelope(service.append("usage", payload))

    @r.post("/model-calls")
    def create_model_call(
        payload: dict[str, Any], principal: Principal = Depends(write_dependency)
    ):
        return envelope(service.append("model_calls", payload))

    # Versioned authoring lifecycle for persona/world/worldbook/reference resources.
    def _make_lifecycle(
        kind: str, action: str
    ) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
        async def lifecycle(
            resource_id: str,
            payload: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            current = service.get_resource(kind, resource_id)
            if current is None:
                raise ControlPlaneError(404, "resource_not_found", "资源不存在。")
            if action == "versions":
                return envelope(
                    {
                        "resource_id": resource_id,
                        "versions": service.versions(kind, resource_id),
                    }
                )
            if action == "rollback":
                version = (payload or {}).get("version")
                if version is None:
                    raise ControlPlaneError(
                        422, "validation_error", "回滚版本无效。"
                    )
                try:
                    version = int(version)
                except (TypeError, ValueError) as exc:
                    raise ControlPlaneError(
                        422, "validation_error", "回滚版本无效。"
                    ) from exc
                candidate = next(
                    (
                        item
                        for item in service.versions(kind, resource_id)
                        if item["version"] == version
                    ),
                    None,
                )
                if candidate is None:
                    raise ControlPlaneError(
                        404, "version_not_found", "目标版本不存在。"
                    )
                data = {
                    k: v
                    for k, v in candidate.items()
                    if k not in {"id", "version", "updated_at"}
                }
                data["lifecycle"] = "rollback"
                try:
                    return envelope(
                        service.put_resource(
                            kind, resource_id, data, current["version"]
                        )
                    )
                except ValueError as exc:
                    raise ControlPlaneError(
                        409, "version_conflict", "资源版本冲突。"
                    ) from exc
            try:
                return envelope(
                    service.apply_lifecycle(kind, resource_id, action, payload, current)
                )
            except ValueError as exc:
                raise ControlPlaneError(
                    409, "version_conflict", "资源版本冲突。"
                ) from exc

        return lifecycle

    for kind in LIFECYCLE_KINDS:
        path = kind.replace("_", "-")
        for action in LIFECYCLE_ACTIONS:
            method = "GET" if action == "versions" else "POST"
            r.add_api_route(
                f"/{path}/{{resource_id}}/{action}",
                _make_lifecycle(kind, action),
                methods=[method],
                dependencies=[Depends(write_dependency)],
            )

    @r.get("/knowledge-bases/{resource_id}/search")
    def knowledge_search(
        resource_id: str,
        q: str = Query(..., min_length=1, max_length=500),
        principal: Principal = Depends(read_dependency),
    ):
        kb = service.get_resource("knowledge_bases", resource_id)
        if kb is None:
            raise ControlPlaneError(404, "knowledge_base_not_found", "知识库不存在。")
        documents = (
            kb.get("documents", []) if isinstance(kb.get("documents", []), list) else []
        )
        needle = q.casefold()
        hits = [doc for doc in documents if needle in str(doc).casefold()]
        return envelope({"query": q, "items": hits, "total": len(hits)})

    @r.post("/knowledge-bases/{resource_id}/reindex")
    def knowledge_reindex(
        resource_id: str, principal: Principal = Depends(write_dependency)
    ):
        if service.get_resource("knowledge_bases", resource_id) is None:
            raise ControlPlaneError(404, "knowledge_base_not_found", "知识库不存在。")
        # V21-risk-3：作业必须落可查登记，且不得假称已排队执行。
        job = service.register_job("knowledge_reindex", resource_id)
        return envelope({**job, "job_id": job["id"]})

    def _make_memory_action(action: str) -> Callable[[str], dict[str, Any]]:
        def memory_action(resource_id: str) -> dict[str, Any]:
            result = service.review_memory(resource_id, action)
            if result is None:
                raise ControlPlaneError(404, "memory_not_found", "记忆不存在。")
            return envelope(result)

        return memory_action

    for action in ("approve", "reject", "forget"):
        r.add_api_route(
            f"/memories/{{resource_id}}/{action}",
            _make_memory_action(action),
            methods=["POST"],
            dependencies=[Depends(write_dependency)],
        )

    @r.post("/memories/rebuild")
    def memory_rebuild(principal: Principal = Depends(write_dependency)):
        # V21-risk-3：作业必须落可查登记，且不得假称已排队执行。
        job = service.register_job("memory_rebuild")
        return envelope({**job, "job_id": job["id"]})

    @r.get("/jobs/{job_id}")
    def get_job(job_id: str, principal: Principal = Depends(read_dependency)):
        job = service.get_job(job_id)
        if job is None:
            raise ControlPlaneError(404, "job_not_found", "作业不存在或已过期。")
        return envelope(job)

    @r.get("/databases/{resource_id}/schema")
    def database_schema(
        resource_id: str, principal: Principal = Depends(read_dependency)
    ):
        item = service.get_resource("databases", resource_id)
        if item is None:
            raise ControlPlaneError(404, "database_not_found", "数据库资源不存在。")
        return envelope({"id": resource_id, "schema": item.get("schema", [])})

    @r.get("/databases/{resource_id}/health")
    def database_health(
        resource_id: str, principal: Principal = Depends(read_dependency)
    ):
        if service.get_resource("databases", resource_id) is None:
            raise ControlPlaneError(404, "database_not_found", "数据库资源不存在。")
        return envelope(
            {"id": resource_id, "status": "unknown", "reason": "source_unavailable"}
        )

    @r.get("/databases/{resource_id}/stats")
    def database_stats(
        resource_id: str, principal: Principal = Depends(read_dependency)
    ):
        if service.get_resource("databases", resource_id) is None:
            raise ControlPlaneError(404, "database_not_found", "数据库资源不存在。")
        return envelope(
            {"id": resource_id, "rows": None, "bytes": None, "status": "unknown"}
        )

    @r.post("/files/read")
    def read_file(
        payload: dict[str, Any], principal: Principal = Depends(read_dependency)
    ):
        # F-1（SEAT-ATK-CP，2026-09-28 根修）：读取根＝显式配置的白名单
        # （bot_control_plane_files_roots，装配期快照键），**不再**以进程 cwd 为根；
        # 无配置 ⇒ 503 诚实拒绝（与 config 服务/media 未装配同一形态），绝不回落 cwd。
        # 全部守卫（resolve+按段判成员、敏感子树/后缀 denylist、绝对路径拒）由
        # ..file_access.FileReadGateway 一次执法（F-3 收编：网关＝本端点唯一读取实现体，
        # 守卫排在任何 stat/解析之前）；HTTP 层不另存第二套路径判据。
        from ...domains.files.sources.file_reader import read_supported_file
        from ..file_access import FileGatewayError, FileReadGateway, parse_roots

        roots = parse_roots(
            getattr(config, "bot_control_plane_files_roots", None)
            if config is not None
            else None
        )
        if not roots:
            raise ControlPlaneError(
                503,
                "files_config_unavailable",
                "未配置文件读取根（BOT_CONTROL_PLANE_FILES_ROOTS 为空），端点拒绝读取。",
            )
        gateway = FileReadGateway(roots)
        relative = str(payload.get("path") or "")
        try:
            candidate, matched_root = gateway.authorize(relative)
        except FileGatewayError as exc:
            reason = str(exc)
            if reason == "absolute_path_forbidden":
                raise ControlPlaneError(
                    422, "file_read_rejected", "只允许登记根内的相对路径。"
                ) from exc
            if reason == "path_not_allowed":
                raise ControlPlaneError(
                    403, "file_read_rejected", "路径不在登记读取根范围内。"
                ) from exc
            if reason == "denied_location":
                raise ControlPlaneError(
                    403, "file_read_denied", "路径命中敏感读取禁区。"
                ) from exc
            raise ControlPlaneError(
                404, "file_not_supported", "文件不存在或格式不支持。"
            ) from exc
        result = read_supported_file(candidate)
        if result.kind in {"missing", "unknown"}:
            raise ControlPlaneError(
                404, "file_not_supported", "文件不存在或格式不支持。"
            )
        return envelope(
            {
                "path": str(candidate.relative_to(matched_root)),
                "kind": result.kind,
                "text": result.text,
                "title": result.title,
                "metadata": result.metadata or {},
            }
        )

    @r.post("/media/analyze")
    def analyze_media(
        payload: dict[str, Any], principal: Principal = Depends(read_dependency)
    ):
        kind = str(payload.get("kind") or "unknown")
        if kind not in {"image", "audio", "video", "gif"}:
            raise ControlPlaneError(422, "media_kind_invalid", "媒体类型无效。")
        if config is None:
            raise ControlPlaneError(503, "media_config_unavailable", "媒体配置未装配。")
        # F-01（SEAT-ATK-WEBUI，SEAT-FIX-WEBUIMA 2026-09-27 根修）：三源的本地形态
        # 不再直连 ingest 真身——与 /files/read 走同一登记根/禁区守卫中央件
        # （唯一真身 = ..file_access.FileReadGateway.admit_media_source，HTTP 层
        # 不自存第二套路径判据）。远程/数据形态原样放行（远程取物咽喉在 ingest
        # 下游，另票处理）；未知 scheme 与越界本地路径 fail-closed。全部本地拒因
        # 折叠成单一回执码——"存在但越界"与"不存在"同形，杜绝存在性探测。
        # 守卫排在任何 ingest 调用（其内含 stat/open/ffmpeg 触盘）之前。
        from ..file_access import FileGatewayError, FileReadGateway, parse_roots

        gateway = FileReadGateway(
            parse_roots(getattr(config, "bot_control_plane_files_roots", None))
        )

        def _admit(raw: str) -> str:
            try:
                return str(gateway.admit_media_source(raw))
            except FileGatewayError as exc:
                raise ControlPlaneError(
                    422, "media_source_rejected", "媒体来源未通过读取校验。"
                ) from exc

        try:
            if kind in {"image", "gif"}:
                from ...domains.media.ingest.vision_describe import (
                    build_vision_provider,
                    describe_images,
                )

                guarded_images = [
                    _admit(str(item)) for item in payload.get("image_urls", [])
                ]
                provider = build_vision_provider(config)
                text = describe_images(
                    provider,
                    image_urls=guarded_images,
                    query_text=str(payload.get("query") or ""),
                )
                result = {
                    "text": text,
                    "ocr": bool(text),
                    "status": "ok" if text else "unknown",
                }
            elif kind == "audio":
                from ...domains.media.ingest.transcribe import (
                    build_asr_provider,
                    transcribe_audio,
                )

                guarded_audio = _admit(str(payload.get("audio_source") or ""))
                asr_provider = build_asr_provider(config)
                text = transcribe_audio(asr_provider, audio_source=guarded_audio)
                result = {
                    "text": text,
                    "asr": bool(text),
                    "status": "ok" if text else "unknown",
                }
            else:
                from ...domains.media.ingest.vision_describe import (
                    build_vision_provider,
                    describe_video,
                )

                guarded_video = _admit(str(payload.get("video_source") or ""))
                provider = build_vision_provider(config)
                frames = max(1, min(16, int(payload.get("frames") or 4)))
                text = describe_video(
                    provider,
                    video_source=guarded_video,
                    query_text=str(payload.get("query") or ""),
                    frames=frames,
                )
                result = {
                    "text": text,
                    "frames": frames,
                    "subtitle_text": str(payload.get("subtitle_text") or ""),
                    "status": "ok" if text else "unknown",
                }
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            raise ControlPlaneError(
                422, "media_analysis_rejected", "媒体分析参数或适配器不可用。"
            ) from exc
        return envelope({"kind": kind, **result})

    def _hit_payload(hit: Any) -> Any:
        dumper = getattr(hit, "model_dump", None)
        return dumper() if callable(dumper) else getattr(hit, "__dict__", hit)

    @r.get("/search")
    async def search(
        q: str = Query(..., min_length=1, max_length=500),
        max_results: int = Query(5, ge=1, le=20),
        principal: Principal = Depends(read_dependency),
    ):
        from ...domains.core.search.web_search import search_async

        hits = await search_async(q, max_results=max_results)
        return envelope(
            {
                "query": q,
                "items": [_hit_payload(hit) for hit in hits],
            }
        )

    @r.get("/capabilities")
    def capabilities(principal: Principal = Depends(read_dependency)):
        return envelope(
            {"items": [{"id": x, "status": "registered"} for x in RESOURCE_KINDS]}
        )

    return r
