"""S10 席：能力协议注册面 + 统一受控调用面离线回归（v21r2；V21-MEDIA/FILE/SEARCH/TTS/IMAGE）。

覆盖（合同=backend-v2-implementation-guide.md §11/§13 S10 + 验收矩阵
V21-MEDIA-001/002、V21-FILE-001/002、V21-SEARCH-001/002、V21-TTS-001、
V21-IMAGE-001）：
- 描述符完整性（每能力必备字段/实现引用在盘/健康探测已注册）；
- 权限门（blocked 无条件拒、角色交集门在 handler 之前）；
- 超时/载荷限额（handler 不执行）；
- 降级链（fallback 承接=honest fallback_ok / honest_degrade=degraded / 链尽=failed）；
- 未接线诚实（creation 对接点 invoke=unavailable not_wired，绝不假成功）；
- 九源逐源状态诚实性（配了=available、没配=not_configured、授权源不冒充）；
- 协议调用面 mock 实调（真实 file_reader/sauce/guard/search_service 链，全离线）。

零真实网络：SauceNAO/搜索引擎只测护栏拒绝与 not_configured 分支；搜索命中
走注入的 fake provider。
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.domains.core.search import search_service
from plugins.bot_unified_runtime.domains.files.sources import file_reader
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    HONEST_DEGRADE_PREFIX,
    NINE_SOURCE_IDS,
    CapabilityDescriptor,
    CapabilityFamily,
    CapabilityHealth,
    CapabilityInvoker,
    CapabilityRegistry,
    CapabilityRequest,
    FallbackRegistry,
    HandlerRegistry,
    HealthProbeRegistry,
    InvocationResult,
    InvocationStatus,
    default_invoker,
    search_source_status,
    validate_registry,
)

# ---------------------------------------------------------------------------
# 公共 fake
# ---------------------------------------------------------------------------


def _roles(*names: str) -> tuple[str, ...]:
    return names


def _make_request(
    capability_id: str, payload: dict[str, Any] | None = None, *, roles: tuple[str, ...] = ("user",),
    context: dict[str, Any] | None = None,
) -> CapabilityRequest:
    return CapabilityRequest(
        capability_id=capability_id,
        payload=payload or {},
        principal="tester",
        roles=roles,
        context=context or {},
    )


class _RecordingHook:
    def __init__(self) -> None:
        self.records: list[Any] = []

    def __call__(self, record: Any) -> None:
        self.records.append(record)


def _mini_invoker() -> CapabilityInvoker:
    """自定义注册面的空 invoker（测试专用注册，不污染默认单例）。"""
    return CapabilityInvoker(
        registry=CapabilityRegistry(),
        handlers=HandlerRegistry(),
        fallbacks=FallbackRegistry(),
        probes=HealthProbeRegistry(),
    )


def _register_custom(
    invoker: CapabilityInvoker,
    capability_id: str,
    handler: Any,
    *,
    roles: tuple[str, ...] = ("user",),
    timeout: float = 5.0,
    limits: dict[str, int] | None = None,
    limit_fields: tuple[tuple[str, str], ...] = (),
    fallback_chain: tuple[str, ...] = (HONEST_DEGRADE_PREFIX + "测试终态",),
) -> None:
    invoker.registry.register(
        CapabilityDescriptor(
            capability_id=capability_id,
            family=CapabilityFamily.MEDIA,
            title="测试能力",
            input_protocol="test.v1{in}",
            output_protocol="test.v1{out}",
            required_roles=roles,
            timeout_seconds=timeout,
            limits=limits or {},
            limit_fields=limit_fields,
            fallback_chain=fallback_chain,
            implementation_ref="plugins/bot_unified_runtime/runtime/capability_protocols.py#CapabilityInvoker",
            notes="测试专用描述符",
        )
    )
    if handler is not None:
        invoker.handlers.register(capability_id, handler)


# ---------------------------------------------------------------------------
# 描述符完整性与默认装配
# ---------------------------------------------------------------------------


class TestDescriptorCompleteness:
    def test_default_registry_counts_per_family(self) -> None:
        invoker = default_invoker()
        assert len(invoker.registry.iter(CapabilityFamily.MEDIA)) == 8
        assert len(invoker.registry.iter(CapabilityFamily.FILES)) == 8
        assert len(invoker.registry.iter(CapabilityFamily.SEARCH)) == 4
        assert len(invoker.registry.iter(CapabilityFamily.CREATION)) == 2

    def test_every_descriptor_has_required_fields_and_resolvable_refs(self) -> None:
        invoker = default_invoker()
        problems = validate_registry(
            invoker.registry,
            handlers=invoker.handlers,
            fallbacks=invoker.fallbacks,
            probes=invoker.probes,
        )
        assert problems == []

    def test_media_contract_capabilities_present(self) -> None:
        invoker = default_invoker()
        ids = {d.capability_id for d in invoker.registry.iter(CapabilityFamily.MEDIA)}
        assert {
            "media.vision.image",      # 图片识别
            "media.vision.ocr",        # OCR（VLM 代位，诚实 degraded）
            "media.vision.anime_ip",   # 动漫角色/IP 识别
            "media.asr.speech",        # 语音识别
            "media.asr.audio_file",    # 音频转文字
            "media.video.recognize",   # 视频识别
            "media.video.subtitle",    # 字幕
            "media.video.frame_extract",  # 抽帧
        } == ids

    def test_files_contract_capabilities_present(self) -> None:
        invoker = default_invoker()
        ids = {d.capability_id for d in invoker.registry.iter(CapabilityFamily.FILES)}
        assert {
            "files.read.word",
            "files.read.ppt",
            "files.read.excel",
            "files.read.pdf",
            "files.read.code",
            "files.read.markdown",
            "files.read.latex",
            "files.artifact.generate",
        } == ids

    def test_ocr_descriptor_is_honest_degraded_family(self) -> None:
        invoker = default_invoker()
        descriptor = invoker.registry.get("media.vision.ocr")
        assert descriptor is not None
        assert descriptor.health_probe == "vision_registry_degraded"
        assert any(
            name.startswith(HONEST_DEGRADE_PREFIX) for name in descriptor.fallback_chain
        )

    def test_duplicate_registration_rejected(self) -> None:
        invoker = default_invoker()
        descriptor = invoker.registry.get("media.vision.image")
        assert descriptor is not None
        with pytest.raises(ValueError, match="重复注册"):
            invoker.registry.register(descriptor)

    def test_request_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            CapabilityRequest(
                capability_id="media.vision.image",
                payload={},
                roles=("user",),
                not_a_field=1,  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# 健康态诚实性
# ---------------------------------------------------------------------------


class TestHealthProbes:
    def test_vision_unconfigured_vs_available_vs_disabled(self) -> None:
        invoker = default_invoker()
        empty = SimpleNamespace(bot_vision_model_registry={}, bot_vision_enabled=False)
        configured = SimpleNamespace(
            bot_vision_model_registry={"glm": {"api_key": "k", "model": "glm-4v-flash", "base_url": "https://vision.example/v1"}},
            bot_vision_enabled=True,
        )
        disabled = SimpleNamespace(
            bot_vision_model_registry={"glm": {"api_key": "k", "model": "glm-4v-flash", "base_url": "https://vision.example/v1"}},
            bot_vision_enabled=False,
        )
        assert invoker.health("media.vision.image", empty)[1] is CapabilityHealth.NOT_CONFIGURED
        assert invoker.health("media.vision.image", configured)[1] is CapabilityHealth.AVAILABLE
        assert invoker.health("media.vision.image", disabled)[1] is CapabilityHealth.DISABLED

    def test_ocr_is_degraded_when_vlm_present(self) -> None:
        invoker = default_invoker()
        configured = SimpleNamespace(
            bot_vision_model_registry={"glm": {"api_key": "k", "model": "glm-4v-flash", "base_url": "https://vision.example/v1"}},
            bot_vision_enabled=True,
        )
        assert invoker.health("media.vision.ocr", configured)[1] is CapabilityHealth.DEGRADED

    def test_saucenao_key_presence(self) -> None:
        invoker = default_invoker()
        with_key = SimpleNamespace(bot_saucenao_api_key="sk-test")
        without_key = SimpleNamespace(bot_saucenao_api_key="")
        assert invoker.health("media.vision.anime_ip", with_key)[1] is CapabilityHealth.AVAILABLE
        assert (
            invoker.health("media.vision.anime_ip", without_key)[1]
            is CapabilityHealth.NOT_CONFIGURED
        )

    def test_creation_dock_reports_not_configured(self) -> None:
        invoker = default_invoker()
        assert (
            invoker.health("creation.tts.synthesize", None)[1]
            is CapabilityHealth.NOT_CONFIGURED
        )
        assert (
            invoker.health("creation.image.generate", None)[1]
            is CapabilityHealth.NOT_CONFIGURED
        )

    def test_probe_exception_reports_unknown_not_fake_available(self) -> None:
        invoker = default_invoker()

        class _BombConfig:
            @property
            def bot_vision_model_registry(self) -> dict[str, Any]:
                raise RuntimeError("registry 读取出错")

        # 属性读取抛错 → 探测异常 → unknown（不冒充可用）
        assert invoker.health("media.vision.image", _BombConfig())[1] is CapabilityHealth.UNKNOWN


# ---------------------------------------------------------------------------
# 受控调用面：权限门 / 超时 / 限额 / 降级链 / 审计
# ---------------------------------------------------------------------------


class TestInvocationGates:
    def test_unknown_capability_fails_honestly(self) -> None:
        result = default_invoker().invoke(_make_request("no.such.capability"))
        assert result.status is InvocationStatus.FAILED

    def test_blocked_principal_denied_before_handler(self) -> None:
        invoker = default_invoker()
        result = invoker.invoke(
            _make_request(
                "files.artifact.generate",
                {"user_text": "生成代码", "reply_text": "```py\nprint(1)\n```", "output_dir": "x"},
                roles=_roles("blocked"),
            )
        )
        assert result.status is InvocationStatus.DENIED
        assert "blocked" in result.detail

    def test_role_gate_blocks_user_on_admin_capability(self, tmp_path: Any) -> None:
        invoker = default_invoker()
        result = invoker.invoke(
            _make_request(
                "files.artifact.generate",
                {
                    "user_text": "生成python代码文件",
                    "reply_text": "```python\nprint('hi')\n```",
                    "output_dir": str(tmp_path),
                },
                roles=_roles("user"),
            )
        )
        assert result.status is InvocationStatus.DENIED
        assert list(tmp_path.iterdir()) == []  # handler 未执行

    def test_admin_passes_gate_then_handler_runs(self, tmp_path: Any) -> None:
        invoker = default_invoker()
        result = invoker.invoke(
            _make_request(
                "files.artifact.generate",
                {
                    "user_text": "生成python代码文件",
                    "reply_text": "```python\nprint('hi')\n```",
                    "output_dir": str(tmp_path),
                },
                roles=_roles("admin", "user"),
            ),
        )
        assert result.status is InvocationStatus.OK
        produced = list(tmp_path.iterdir())
        assert len(produced) == 1 and produced[0].suffix == ".py"

    def test_payload_limit_exceeded_without_running_handler(self) -> None:
        invoker = default_invoker()
        calls: list[Any] = []

        def _spy(request: CapabilityRequest) -> InvocationResult:
            calls.append(request)
            return InvocationResult(
                capability_id=request.capability_id, status=InvocationStatus.OK
            )

        _register_custom(
            invoker,
            "media.test.limited",
            _spy,
            limits={"max_items": 2},
            limit_fields=(("items", "max_items"),),
        )
        result = invoker.invoke(
            _make_request("media.test.limited", {"items": ["a", "b", "c"]})
        )
        assert result.status is InvocationStatus.LIMIT_EXCEEDED
        assert calls == []

    def test_string_length_limit(self) -> None:
        invoker = default_invoker()
        result = invoker.invoke(
            _make_request("search.web", {"query": "x" * 501}, roles=("user",))
        )
        assert result.status is InvocationStatus.LIMIT_EXCEEDED

    def test_frame_count_limit_blocks_ffmpeg_path(self) -> None:
        result = default_invoker().invoke(
            _make_request("media.video.frame_extract", {"video_source": "x.mp4", "frames": 100})
        )
        assert result.status is InvocationStatus.LIMIT_EXCEEDED
        assert "max_frames" in result.detail

    def test_timeout_reported_honestly(self) -> None:
        invoker = _mini_invoker()

        def _slow(request: CapabilityRequest) -> InvocationResult:
            time.sleep(1.0)
            return InvocationResult(
                capability_id=request.capability_id, status=InvocationStatus.OK
            )

        _register_custom(invoker, "media.test.slow", _slow, timeout=0.2)
        result = invoker.invoke(_make_request("media.test.slow"))
        assert result.status is InvocationStatus.TIMEOUT
        assert result.via == "invoker"

    def test_not_wired_capability_is_unavailable_never_ok(self) -> None:
        invoker = default_invoker()
        for cid in ("creation.tts.synthesize", "creation.image.generate"):
            result = invoker.invoke(_make_request(cid))
            assert result.status is InvocationStatus.UNAVAILABLE
            assert "not_wired" in result.detail or "未接线" in result.detail

    def test_async_handler_bridged(self) -> None:
        invoker = _mini_invoker()

        async def _async_handler(request: CapabilityRequest) -> InvocationResult:
            await asyncio_sleep(0)
            return InvocationResult(
                capability_id=request.capability_id,
                status=InvocationStatus.OK,
                data={"via": "async"},
            )

        _register_custom(invoker, "media.test.async", _async_handler)
        result = invoker.invoke(_make_request("media.test.async"))
        assert result.status is InvocationStatus.OK
        assert result.data["via"] == "async"


async def asyncio_sleep(delay: float) -> None:
    import asyncio

    await asyncio.sleep(delay)


class TestFallbackChain:
    def test_fallback_takes_over_reports_fallback_ok(self) -> None:
        invoker = _mini_invoker()

        def _boom(request: CapabilityRequest) -> InvocationResult:
            raise RuntimeError("主链炸了")

        def _rescue(request: CapabilityRequest) -> InvocationResult:
            return InvocationResult(
                capability_id=request.capability_id,
                status=InvocationStatus.OK,
                data={"rescued": True},
            )

        _register_custom(
            invoker,
            "media.test.rescued",
            _boom,
            fallback_chain=("rescue_step", HONEST_DEGRADE_PREFIX + "兜底也挂"),
        )
        invoker.fallbacks.register("media.test.rescued", "rescue_step", _rescue)
        result = invoker.invoke(_make_request("media.test.rescued"))
        assert result.status is InvocationStatus.FALLBACK_OK
        assert result.via == "fallback[0]:rescue_step"
        assert result.data["rescued"] is True
        assert result.attempts == 2

    def test_honest_degrade_terminal_never_fakes_success(self) -> None:
        invoker = _mini_invoker()

        def _boom(request: CapabilityRequest) -> InvocationResult:
            raise RuntimeError("无解")

        _register_custom(invoker, "media.test.degraded", _boom)
        result = invoker.invoke(_make_request("media.test.degraded"))
        assert result.status is InvocationStatus.DEGRADED
        assert "诚实降级" in result.detail
        assert result.data == {}

    def test_all_chain_exhausted_fails_honestly(self) -> None:
        invoker = _mini_invoker()

        def _boom(request: CapabilityRequest) -> InvocationResult:
            raise RuntimeError("持续失败")

        _register_custom(
            invoker,
            "media.test.doomed",
            _boom,
            fallback_chain=("also_boom", HONEST_DEGRADE_PREFIX + "不会到这"),
        )
        invoker.fallbacks.register("media.test.doomed", "also_boom", _boom)
        result = invoker.invoke(_make_request("media.test.doomed"))
        assert result.status is InvocationStatus.FAILED
        assert "降级链 1 项失败" in result.detail

    def test_handler_returning_wrong_type_walks_fallback(self) -> None:
        invoker = _mini_invoker()

        def _bad(request: CapabilityRequest) -> Any:
            return {"fake": "result"}  # 非InvocationResult：不冒充协议结果

        def _rescue(request: CapabilityRequest) -> InvocationResult:
            return InvocationResult(
                capability_id=request.capability_id, status=InvocationStatus.OK
            )

        _register_custom(
            invoker,
            "media.test.badtype",
            _bad,
            fallback_chain=("rescue", HONEST_DEGRADE_PREFIX + "终态"),
        )
        invoker.fallbacks.register("media.test.badtype", "rescue", _rescue)
        result = invoker.invoke(_make_request("media.test.badtype"))
        assert result.status is InvocationStatus.FALLBACK_OK


class TestAuditHooks:
    def test_audit_record_emitted_for_every_terminal_state(self) -> None:
        hook = _RecordingHook()
        invoker = default_invoker()
        invoker.audit_hooks.register(hook)
        try:
            invoker.invoke(_make_request("media.vision.image", {}, roles=("user",)))
            invoker.invoke(_make_request("creation.tts.synthesize"))
            invoker.invoke(_make_request("no.such"))
        finally:
            pass
        statuses = [record.status for record in hook.records]
        assert InvocationStatus.NOT_CONFIGURED in statuses
        assert InvocationStatus.UNAVAILABLE in statuses
        assert InvocationStatus.FAILED in statuses
        assert all(record.principal == "tester" for record in hook.records)
        assert all(record.elapsed_ms >= 0 for record in hook.records)

    def test_raising_hook_does_not_break_invocation(self) -> None:
        def _bomb(record: Any) -> None:
            raise RuntimeError("审计钩子坏")

        invoker = default_invoker()
        invoker.audit_hooks.register(_bomb)
        result = invoker.invoke(_make_request("creation.tts.synthesize"))
        assert result.status is InvocationStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# 协议调用面 mock 实调（真实既有实现链，全离线）
# ---------------------------------------------------------------------------


class TestFilesFamilyRealChains:
    def test_read_code_file(self, tmp_path: Any) -> None:
        target = tmp_path / "hello.py"
        target.write_text("print('守岸人')\n", encoding="utf-8")
        result = default_invoker().invoke(
            _make_request("files.read.code", {"path": str(target)})
        )
        assert result.status is InvocationStatus.OK
        assert result.data["kind"] == "code"
        assert "守岸人" in result.data["text"]

    def test_read_markdown_file(self, tmp_path: Any) -> None:
        target = tmp_path / "note.md"
        target.write_text("# 标题\n\n正文\n", encoding="utf-8")
        result = default_invoker().invoke(
            _make_request("files.read.markdown", {"path": str(target)})
        )
        assert result.status is InvocationStatus.OK
        assert result.data["kind"] == "text"
        assert "# 标题" in result.data["text"]

    def test_read_latex_file_via_new_tex_support(self, tmp_path: Any) -> None:
        target = tmp_path / "paper.tex"
        target.write_text(
            "\\documentclass{article}\n\\begin{document}能量守恒\n\\end{document}\n",
            encoding="utf-8",
        )
        # 直接既有实现断言 .tex 已入文本集
        direct = file_reader.read_supported_file(target)
        assert direct.kind == "text"
        result = default_invoker().invoke(
            _make_request("files.read.latex", {"path": str(target)})
        )
        assert result.status is InvocationStatus.OK
        assert "能量守恒" in result.data["text"]

    def test_missing_file_fails_honestly(self, tmp_path: Any) -> None:
        result = default_invoker().invoke(
            _make_request("files.read.code", {"path": str(tmp_path / "nope.py")})
        )
        assert result.status is InvocationStatus.FAILED
        assert "不存在" in result.detail

    def test_legacy_ppt_honest_parser_unavailable(self, tmp_path: Any) -> None:
        target = tmp_path / "old.ppt"
        target.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
        result = default_invoker().invoke(
            _make_request("files.read.ppt", {"path": str(target)})
        )
        assert result.status is InvocationStatus.DEGRADED
        assert "parser_unavailable" in result.detail
        assert result.data["metadata"]["status"] == "parser_unavailable"

    def test_legacy_xls_honest_parser_unavailable(self, tmp_path: Any) -> None:
        target = tmp_path / "old.xls"
        target.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
        result = default_invoker().invoke(
            _make_request("files.read.excel", {"path": str(target)})
        )
        assert result.status is InvocationStatus.DEGRADED

    def test_real_xlsx_read(self, tmp_path: Any) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        target = tmp_path / "book.xlsx"
        book = openpyxl.Workbook()
        book.active["A1"] = "守岸人"
        book.save(target)
        result = default_invoker().invoke(
            _make_request("files.read.excel", {"path": str(target)})
        )
        assert result.status is InvocationStatus.OK
        assert result.data["kind"] == "spreadsheet"
        assert "守岸人" in result.data["text"]

    def test_real_docx_read(self, tmp_path: Any) -> None:
        docx_module = pytest.importorskip("docx")
        target = tmp_path / "doc.docx"
        document = docx_module.Document()
        document.add_paragraph("泰缇斯系统第二实例")
        document.save(str(target))
        result = default_invoker().invoke(
            _make_request("files.read.word", {"path": str(target)})
        )
        assert result.status is InvocationStatus.OK
        assert result.data["kind"] == "document"
        assert "泰缇斯" in result.data["text"]

    def test_pdf_parser_unavailable_degrades_honestly(self, tmp_path: Any) -> None:
        """pypdf 缺失或解析失败时，PDF 走诚实 parser_unavailable（本 venv 现状）。"""
        target = tmp_path / "minimal.pdf"
        target.write_bytes(b"%PDF-1.4\ntrailer\n%%EOF\n")
        result = default_invoker().invoke(
            _make_request("files.read.pdf", {"path": str(target)})
        )
        assert result.status is InvocationStatus.DEGRADED
        assert "parser_unavailable" in result.detail

    def test_textless_pdf_degrades_honestly(self, tmp_path: Any) -> None:
        pypdf = pytest.importorskip("pypdf")
        target = tmp_path / "scan.pdf"
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with target.open("wb") as stream:
            writer.write(stream)
        result = default_invoker().invoke(
            _make_request("files.read.pdf", {"path": str(target)})
        )
        assert result.status is InvocationStatus.DEGRADED
        assert "无可提取文本" in result.detail

    def test_artifact_generation_rejects_office_masquerade(self, tmp_path: Any) -> None:
        result = default_invoker().invoke(
            _make_request(
                "files.artifact.generate",
                {
                    "user_text": "帮我生成 word 文档",
                    "reply_text": "随便一段话",
                    "output_dir": str(tmp_path),
                },
                roles=("admin",),
            )
        )
        assert result.status is InvocationStatus.FAILED
        assert "冒充" in result.detail or "不能" in result.detail
        assert list(tmp_path.iterdir()) == []


class TestMediaFamilyHonestBranches:
    def test_vision_unconfigured(self) -> None:
        config = SimpleNamespace(bot_vision_model_registry={}, bot_vision_enabled=True)
        result = default_invoker().invoke(
            _make_request(
                "media.vision.image",
                {"image_urls": ["file:///tmp/a.jpg"]},
                context={"config": config},
            )
        )
        assert result.status is InvocationStatus.NOT_CONFIGURED

    def test_vision_url_rejected_by_existing_ssrf_guard(self) -> None:
        config = SimpleNamespace(
            bot_vision_model_registry={"glm": {"api_key": "k", "model": "glm-4v-flash", "base_url": "https://vision.example/v1"}},
            bot_vision_enabled=True,
            bot_vision_max_images=2,
            bot_vision_max_chars=500,
        )
        result = default_invoker().invoke(
            _make_request(
                "media.vision.image",
                {"image_urls": ["http://127.0.0.1:9222/secret.jpg"]},
                context={"config": config},
            )
        )
        assert result.status is InvocationStatus.FAILED
        assert "SSRF" in result.detail

    def test_asr_unconfigured(self) -> None:
        config = SimpleNamespace(bot_asr_model_registry={}, bot_asr_enabled=True)
        result = default_invoker().invoke(
            _make_request(
                "media.asr.speech",
                {"audio_source": "file:///tmp/a.mp3"},
                context={"config": config},
            )
        )
        assert result.status is InvocationStatus.NOT_CONFIGURED

    def test_anime_ip_requires_http_url(self) -> None:
        result = default_invoker().invoke(
            _make_request("media.vision.anime_ip", {"image_url": "file:///tmp/a.jpg"})
        )
        assert result.status is InvocationStatus.FAILED
        assert "URL" in result.detail

    def test_anime_ip_guard_rejects_loopback(self) -> None:
        result = default_invoker().invoke(
            _make_request(
                "media.vision.anime_ip",
                {"image_url": "http://localhost/x.jpg"},
            )
        )
        assert result.status is InvocationStatus.FAILED
        assert "SSRF" in result.detail

    def test_anime_ip_unconfigured_key(self) -> None:
        result = default_invoker().invoke(
            _make_request(
                "media.vision.anime_ip",
                {"image_url": "https://example.com/img.jpg"},
                context={"config": SimpleNamespace(bot_saucenao_api_key="")},
            )
        )
        assert result.status is InvocationStatus.NOT_CONFIGURED
        assert result.detail == "" or "key" in result.detail

    def test_video_recognize_disabled_switch(self) -> None:
        config = SimpleNamespace(bot_video_understanding_enabled=False)
        result = default_invoker().invoke(
            _make_request(
                "media.video.recognize",
                {"video_source": "file:///tmp/a.mp4"},
                context={"config": config},
            )
        )
        assert result.status is InvocationStatus.NOT_CONFIGURED

    def test_subtitle_present_and_absent(self) -> None:
        invoker = default_invoker()
        present = invoker.invoke(
            _make_request(
                "media.video.subtitle",
                {"subtitle_text": "00:01 大家好"},
                context={"config": SimpleNamespace()},
            )
        )
        assert present.status is InvocationStatus.OK
        assert present.data["present"] is True
        absent = invoker.invoke(
            _make_request(
                "media.video.subtitle", {}, context={"config": SimpleNamespace()}
            )
        )
        assert absent.status is InvocationStatus.DEGRADED
        assert absent.data["present"] is False


class TestSearchFamilyMockInvocations:
    def test_web_disabled_not_configured(self) -> None:
        config = SimpleNamespace(bot_web_search_enabled=False)
        result = default_invoker().invoke(
            _make_request("search.web", {"query": "test"}, context={"config": config})
        )
        assert result.status is InvocationStatus.NOT_CONFIGURED

    def test_acg_disabled_not_configured(self) -> None:
        config = SimpleNamespace(bot_search_acg_enabled=False)
        result = default_invoker().invoke(
            _make_request("search.acg", {"query": "test"}, context={"config": config})
        )
        assert result.status is InvocationStatus.NOT_CONFIGURED

    def test_unified_with_injected_fake_provider(self) -> None:
        class FakeProvider:
            def search(self, query: Any) -> list[Any]:
                return [
                    search_service.ProviderRawHit(
                        title="命中", url="https://example.com/a", snippet="摘要"
                    )
                ]

        config = SimpleNamespace(bot_web_search_enabled=False)
        result = default_invoker().invoke(
            _make_request(
                "search.unified",
                {"query": "守岸人", "source_ids": ["general"]},
                context={"config": config, "providers": {"general": FakeProvider()}},
            )
        )
        assert result.status is InvocationStatus.OK
        assert result.data["hits"][0]["title"] == "命中"
        assert result.data["per_source"][0]["status"] == "ok"

    def test_unified_without_providers_is_honest_not_configured(self) -> None:
        config = SimpleNamespace(bot_web_search_enabled=False)
        result = default_invoker().invoke(
            _make_request(
                "search.unified",
                {"query": "守岸人", "source_ids": ["general"]},
                context={"config": config},
            )
        )
        assert result.status is InvocationStatus.NOT_CONFIGURED
        assert "dependency_unavailable" in result.detail

    def test_reference_fetch_requires_authorized_citation(self) -> None:
        hit = search_service.SearchHit(
            id="h1",
            title="t",
            canonical_url="https://example.com/doc",
            source_id="general",
            retrieved_at=search_service.datetime.now(search_service.timezone.utc),
            citation_id="cite-1",
        )
        result = default_invoker().invoke(
            _make_request(
                "search.reference.fetch",
                {"citation_id": "cite-other"},
                context={
                    "hit_context": {"cite-1": hit},
                    "fetcher": lambda url: "正文",
                },
            )
        )
        assert result.status is InvocationStatus.DENIED
        assert "授权" in result.detail

    def test_reference_fetch_happy_path_with_fake_fetcher(self) -> None:
        hit = search_service.SearchHit(
            id="h1",
            title="t",
            canonical_url="https://example.com/doc",
            source_id="general",
            retrieved_at=search_service.datetime.now(search_service.timezone.utc),
            citation_id="cite-1",
        )
        result = default_invoker().invoke(
            _make_request(
                "search.reference.fetch",
                {"citation_id": "cite-1"},
                context={
                    "hit_context": {"cite-1": hit},
                    "fetcher": lambda url: f"正文@{url}",
                },
            )
        )
        assert result.status is InvocationStatus.OK
        assert "example.com" in result.data["reference"]["content"]

    def test_reference_fetch_guard_blocks_private_target(self) -> None:
        hit = search_service.SearchHit(
            id="h1",
            title="t",
            canonical_url="http://127.0.0.1:8742/internal",
            source_id="general",
            retrieved_at=search_service.datetime.now(search_service.timezone.utc),
            citation_id="cite-1",
        )
        result = default_invoker().invoke(
            _make_request(
                "search.reference.fetch",
                {"citation_id": "cite-1"},
                context={
                    "hit_context": {"cite-1": hit},
                    "fetcher": lambda url: "不该被取回",
                },
            )
        )
        assert result.status is InvocationStatus.FAILED
        assert "SSRF" in result.detail


# ---------------------------------------------------------------------------
# 九源逐源状态面（V21-SEARCH-001：诚实 not_configured）
# ---------------------------------------------------------------------------


class TestNineSourceStatus:
    def test_exactly_nine_sources(self) -> None:
        config = SimpleNamespace(bot_web_search_enabled=False)
        statuses = search_source_status(config)
        assert tuple(s.source_id for s in statuses) == NINE_SOURCE_IDS

    def test_all_not_configured_when_disabled(self) -> None:
        config = SimpleNamespace(bot_web_search_enabled=False)
        statuses = search_source_status(config)
        assert all(s.status is CapabilityHealth.NOT_CONFIGURED for s in statuses)
        assert all(s.reason for s in statuses)

    def test_general_chain_sources_available_when_enabled(self) -> None:
        config = SimpleNamespace(bot_web_search_enabled=True)
        statuses = {s.source_id: s for s in search_source_status(config)}
        for source_id in ("bilibili", "youtube", "x", "github", "linux_do", "csdn", "zhihu"):
            assert statuses[source_id].status is CapabilityHealth.AVAILABLE, source_id

    def test_authorized_provider_sources_never_fake_available(self) -> None:
        config = SimpleNamespace(bot_web_search_enabled=True)
        statuses = {s.source_id: s for s in search_source_status(config)}
        for source_id in ("xiaohongshu", "cnki"):
            assert statuses[source_id].status is CapabilityHealth.NOT_CONFIGURED, source_id
            assert statuses[source_id].requires_authorized_provider is True

    def test_registered_provider_unlocks_authorized_source(self) -> None:
        config = SimpleNamespace(bot_web_search_enabled=False)
        statuses = {
            s.source_id: s
            for s in search_source_status(config, registered_providers={"cnki": object()})
        }
        assert statuses["cnki"].status is CapabilityHealth.AVAILABLE
        assert statuses["xiaohongshu"].status is CapabilityHealth.NOT_CONFIGURED

    def test_metadata_passthrough_from_w7_registry(self) -> None:
        config = SimpleNamespace(bot_web_search_enabled=False)
        statuses = {s.source_id: s for s in search_source_status(config)}
        assert statuses["github"].private_scope_supported is True
        assert "site:" in statuses["bilibili"].fallback_and_limits
        assert statuses["cnki"].display_name == "知网（CNKI）"
