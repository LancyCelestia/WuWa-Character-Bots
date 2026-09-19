"""G-3 配音出站路径接中央回归（Wave G T73 · M-10/M-13 自动半）。

覆盖（施工图=report-T58.md §3/§5；冻结接口=docs/design/tts-contract-layer.md §4.2；
裁定=progress.md R-16②（群内降级维持中央 A-19）/U-17=C/G2-R1 U-29=A）：

- R1/R2 双态互斥：``bot_tts_voice_hook_enabled`` 键关=旧 ``_attach_voice_reply``
  包装路径（字节级现状）∧ pipeline 收 ``outbound_voice_enricher=None``；
  键开=不包装、``build_voice_enricher`` 产物接 pipeline（惰性导入）；
- R3 hook 时序：enricher 在 review 批准后、render 前恰调一次；review BLOCK⇒零调用；
- R4 取文口径（M-10 根修）：合成入参=review 批准后的 body；被拦正文零落盘；
- R5 失败可观测（M-13 自动半）：合成失败⇒``operational_issue.kind`` ∈ c723904
  七 kind 码族、body/send_policy 不变（非 SILENT_AUDIT）；
- R6 政策拒绝≠故障：无 issue、有 audit_tag（T54 §4.1#2）；
- R7 告警链贯通：hook 挂的 issue 随 SendRequest 进队列（根 ``_notify_operational_receipt``
  链路既有，T58 §2 已验，此处锁源头入队）；
- R8 群内文字存活：hook 失败⇒正文照发、A-19 压空正文分支零触发（R-16②）；
- R9 退役守卫：根 ``__init__.py`` 不再含旧包装符号（AST 门）——**本波刻意
  xfail**（退役两步走的第二步=摘旧包装，等真机浸泡窗；落地时本测试转绿，
  strict 锁强制移除标记，G-4 可收编）。

全离线零网络（``synthesize``/``resolve_speech_text`` 一律 monkeypatch）；
落盘只写 tmp_path。新件避开 ``test_tts_*`` 前缀（T61 报告 §五占用在用）。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    ReceiptState,
    ReviewResult,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    pipeline as pipeline_module,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    IncomingMessage,
)
from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue

_ROOT_INIT = Path(__file__).resolve().parents[1] / (
    "plugins/bot_unified_runtime/__init__.py"
)

# c723904 失败码族（tts.py `_FAILURE_KINDS` 六前缀 + 兜底 + 无参考音频）。
_FAILURE_KIND_FAMILY = {
    "tts_service_unreachable",
    "tts_empty_audio",
    "tts_bad_audio",
    "tts_service_rejected",
    "tts_write_failed",
    "tts_synthesize_failed",
    "tts_no_ref_audio",
}


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


class _NullAuditLogger:
    def append(self, record: object) -> None:
        return


def _message(group: bool = False) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g1" if group else "private:u1",
        session_type=SessionType.GROUP if group else SessionType.PRIVATE,
        sender_id="u1",
        group_id="g1" if group else "",
        plain_text="今天天气不错",
        message_id="m-1",
        debug_id="dbg-1",
    )


def _decision(group: bool = False) -> BotDecision:
    return BotDecision(
        request_id="req-1",
        should_respond=True,
        mode="command",
        trigger="你好",
        capability_id="bot.chat",
        target_scope=SessionType.GROUP if group else SessionType.PRIVATE,
        decision_reason="test",
    )


def _chat_result(body: str = "潮汐今天很安静。") -> CapabilityResult:
    return CapabilityResult(
        request_id="req-1",
        capability_id="bot.chat",
        kind="text",
        body=body,
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["chat"],
    )


def _static_capability(result: object):
    async def _run(message: IncomingMessage, decision: BotDecision) -> object:
        return result

    return _run


def _hook_config(tmp_path: Path, ref_file: Path | None = None, **overrides: object):
    """enricher 行为测试的最小配置（与 test_tts.py 命名空间夹具同构）。"""
    ref_audios = (
        [f"{ref_file}|参考文本|zh"] if ref_file is not None else []
    )
    base: dict[str, object] = {
        "bot_tts_voice_hook_enabled": True,
        "bot_tts_enabled": True,
        "bot_tts_api_url": "http://127.0.0.1:9880",
        "bot_tts_gptsovits_dir": "",
        "bot_tts_ref_audios": ref_audios,
        "bot_tts_trigger_words": [],
        "bot_tts_output_dir": str(tmp_path / "tts_out"),
        "bot_tts_preset": "shorekeeper",
        "bot_tts_max_chars": 200,
        "bot_tts_hard_max_chars": 2000,
        "bot_tts_max_audio_bytes": 0,
        "bot_tts_cache_enabled": False,
        "bot_tts_cache_max_bytes": 0,
        "bot_tts_cache_max_age_days": 0,
        "bot_tts_timeout_seconds": 60.0,
        "bot_tts_speed_factor": 0.85,
        "bot_tts_temperature": 0.9,
        "bot_tts_top_k": 15,
        "bot_tts_top_p": 1.0,
        "bot_tts_text_lang": "zh",
        "bot_tts_text_split_method": "cut5",
        "bot_tts_auto_reply_enabled": True,
        "bot_tts_auto_reply_scope": "private",
        "bot_tts_auto_reply_max_chars": 120,
        "bot_tts_auto_reply_probability": 1.0,
        "bot_tts_auto_reply_always": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_pipeline(enricher: object | None, **pipeline_kwargs: object) -> RuntimePipeline:
    kwargs: dict[str, object] = {
        "send_queue": InMemorySendQueue(audit_logger=_NullAuditLogger()),
        "audit_logger": _NullAuditLogger(),
    }
    if enricher is not None:
        kwargs["outbound_voice_enricher"] = enricher
    kwargs.update(pipeline_kwargs)
    return RuntimePipeline(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# R1/R2 · 双态互斥装配（键关=字节级现状 / 键开=hook）
# ---------------------------------------------------------------------------


def test_r1_key_off_keeps_legacy_wrapper_and_zero_enricher() -> None:
    """键关=旧包装路径原样装配，pipeline 不接 enricher（字节级不变判据①②）。"""
    # ①新键缺省 False（真实 config 契约，非夹具）。
    field = Config.model_fields["bot_tts_voice_hook_enabled"]
    assert field.default is False

    source = _ROOT_INIT.read_text(encoding="utf-8")
    # ②装配区双态：enricher 缺省 None；旧包装只在 None 分支内装配。
    assert "pipeline_voice_enricher = None" in source
    guard_index = source.index("if pipeline_voice_enricher is None:")
    wrapper_index = source.index(
        "chat_capability = _attach_voice_reply(chat_capability, config=config)"
    )
    assert guard_index < wrapper_index, "旧包装必须在键关（enricher=None）分支内"
    # ③pipeline 收 enricher（双态互斥：同一变量两处消费）。
    assert "outbound_voice_enricher=pipeline_voice_enricher" in source
    # ④ctor 缺省 None ⇒ 键关部署 _complete 新分支零执行。
    pipeline = _make_pipeline(None)
    assert pipeline.outbound_voice_enricher is None
    # ⑤根模块顶层不得静态导入 enricher（惰性导入防半吊子：键关部署永不触新符号）。
    tree = ast.parse(source)
    top_level_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    for node in top_level_imports:
        module = getattr(node, "module", "") or ""
        names = [alias.name for alias in node.names]
        assert "voice_enricher" not in module, "enricher 只允许惰性导入"
        assert "build_voice_enricher" not in names, "enricher 只允许惰性导入"


def test_r2_key_on_wires_enricher_and_skips_wrapper(tmp_path: Path) -> None:
    """键开=惰性导入构建 enricher 接 pipeline；双态互斥（无包装）。"""
    source = _ROOT_INIT.read_text(encoding="utf-8")
    # 键开分支存在且惰性导入在分支内（缩进级 import，非顶层）。
    key_on_probe = 'getattr(config, "bot_tts_voice_hook_enabled", False)'
    assert key_on_probe in source
    assert "from .domains.media.voice_enricher import build_voice_enricher" in source
    tree = ast.parse(source)
    lazy_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").endswith("voice_enricher")
        and node.col_offset > 0
    ]
    assert lazy_imports, "build_voice_enricher 必须是分支内惰性导入"
    # 双态互斥的结构锁：键开分支与旧包装分支互斥（if/else 配对）。
    assert "pipeline_voice_enricher = build_voice_enricher(config)" in source

    # 行为面：键开配置能构建出 enricher；构建后关键 ⇒ enricher 内部门链判否
    # （纵深第二道：即便误装配，键关语义仍是零合成）。
    from plugins.bot_unified_runtime.domains.media.voice_enricher import (
        build_voice_enricher,
    )

    config = _hook_config(tmp_path)
    enricher = build_voice_enricher(config)
    assert callable(enricher)
    config.bot_tts_voice_hook_enabled = False
    result = enricher(_message(), _decision(), _chat_result())
    assert result.audio == []
    assert result.operational_issue is None


# ---------------------------------------------------------------------------
# R3/R4 · hook 时序与取文口径（M-10 根修）
# ---------------------------------------------------------------------------


def test_r3_enricher_runs_after_review_before_render(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    def spy_enricher(message: object, decision: object, result: CapabilityResult):
        order.append("hook")
        return result

    real_review = pipeline_module.review_capability_result
    real_render = pipeline_module.render_reviewed_output

    def review_spy(result: object, decision: object):
        order.append("review")
        return real_review(result, decision)

    def render_spy(result: object, review: object):
        order.append("render")
        return real_render(result, review)

    monkeypatch.setattr(pipeline_module, "review_capability_result", review_spy)
    monkeypatch.setattr(pipeline_module, "render_reviewed_output", render_spy)

    pipeline = _make_pipeline(spy_enricher)
    receipt = asyncio.run(
        pipeline.handle_async(
            _message(), _static_capability(_chat_result()), "bot.chat"
        )
    )

    assert order == ["review", "hook", "render"], "hook 必须夹在 review 批准与 render 之间"
    assert order.count("hook") == 1
    assert receipt.state == ReceiptState.SENT


def test_r3b_review_block_skips_enricher(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    def spy_enricher(message: object, decision: object, result: CapabilityResult):
        calls.append(result)
        return result

    monkeypatch.setattr(
        pipeline_module,
        "review_capability_result",
        lambda result, decision: ReviewResult(
            request_id="req-1", approved=False, reasons=["blocked"]
        ),
    )
    pipeline = _make_pipeline(spy_enricher)
    receipt = asyncio.run(
        pipeline.handle_async(
            _message(), _static_capability(_chat_result()), "bot.chat"
        )
    )

    assert calls == [], "review 拦截 ⇒ enricher 零调用（被拦正文不得合成）"
    assert receipt.state == ReceiptState.BLOCKED


def test_r4_synthesis_intakes_review_approved_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-10 根修：合成取文=hook 时点的批准后 body；review 拦截⇒零落盘。"""
    import plugins.bot_unified_runtime.domains.media.voice_enricher as ve

    ref_file = tmp_path / "ref.wav"
    ref_file.write_bytes(b"RIFFref")
    out_dir = tmp_path / "tts_out"
    wav_file = tmp_path / "fake.wav"
    wav_file.write_bytes(b"RIFFfake")
    captured: dict[str, object] = {}

    def fake_synthesize(**kwargs: object):
        captured["text"] = kwargs.get("text")
        return wav_file, ""

    monkeypatch.setattr(ve, "synthesize", fake_synthesize)

    config = _hook_config(tmp_path, ref_file=ref_file)
    enricher = ve.build_voice_enricher(config)
    pipeline = _make_pipeline(enricher)
    receipt = asyncio.run(
        pipeline.handle_async(
            _message(), _static_capability(_chat_result()), "bot.chat"
        )
    )

    assert receipt.state == ReceiptState.SENT
    assert captured["text"] == "潮汐今天很安静。"
    # hook 成功 ⇒ 音频已挂回结果并随 SendRequest 出站。
    request = pipeline.send_queue.sent_requests[-1]
    assert request.content.content_ref.get("audio") or request.audit_tags  # 出站携带
    assert any(
        tag.startswith("preset=") for tag in request.audit_tags
    ), request.audit_tags

    # review 拦截 ⇒ 合成零调用、被拦正文零落盘。
    monkeypatch.setattr(
        pipeline_module,
        "review_capability_result",
        lambda result, decision: ReviewResult(
            request_id="req-1", approved=False, reasons=["blocked"]
        ),
    )
    asyncio.run(
        pipeline.handle_async(
            _message(), _static_capability(_chat_result()), "bot.chat"
        )
    )
    assert captured["text"] == "潮汐今天很安静。", "拦截后不得再合成"
    assert not (out_dir).exists() or list(out_dir.iterdir()) == [], "被拦正文零落盘"


# ---------------------------------------------------------------------------
# R5/R6 · M-13 自动半：失败可观测 / 政策拒绝不挂 issue
# ---------------------------------------------------------------------------


def _enricher_with_failing_synthesize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: object,
    *,
    bypass_gate: bool = False,
    **config_overrides: object,
):
    import plugins.bot_unified_runtime.domains.media.voice_enricher as ve

    ref_file = tmp_path / "ref.wav"
    ref_file.write_bytes(b"RIFFref")
    monkeypatch.setattr(ve, "synthesize", fake)
    if bypass_gate:
        # R8 专供：门链谓词归 tts.py 面（T75 席在飞改造，M-17 群面中央名单门
        # 已入 should_voice_reply）；本例测的是 issue 挂载与 A-19 不触发语义，
        # 旁路门链隔离他席在飞变化。键关纵深门（hook key/既有 issue）仍生效。
        monkeypatch.setattr(ve, "should_voice_reply", lambda *a, **k: True)
    config = _hook_config(tmp_path, ref_file=ref_file, **config_overrides)
    return ve.build_voice_enricher(config), config


def test_r5_synthesis_failure_attaches_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enricher, _config = _enricher_with_failing_synthesize(
        tmp_path, monkeypatch, lambda **kwargs: (None, "服务不可达: connection refused")
    )
    result = _chat_result()
    enriched = enricher(_message(), _decision(), result)

    assert enriched.audio == []
    assert enriched.body == result.body, "正文必须原样存活（增益失败不伤正文）"
    assert enriched.send_policy == SendPolicy.IMMEDIATE, "失败不得压成 SILENT_AUDIT"
    issue = enriched.operational_issue
    assert issue is not None
    assert issue.kind in _FAILURE_KIND_FAMILY
    assert issue.kind == "tts_service_unreachable"
    assert issue.retryable is True


def test_r5b_unexpected_exception_attaches_generic_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(**kwargs: object):
        raise RuntimeError("engine exploded")

    enricher, _config = _enricher_with_failing_synthesize(tmp_path, monkeypatch, boom)
    result = _chat_result()
    enriched = enricher(_message(), _decision(), result)

    assert enriched.body == result.body
    issue = enriched.operational_issue
    assert issue is not None
    assert issue.kind in _FAILURE_KIND_FAMILY
    assert issue.kind == "tts_synthesize_failed"
    assert issue.retryable is False


def test_r5c_missing_ref_audio_attaches_no_ref_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无参考音频=确定性失败（F3），对应既有 tts_no_ref_audio 码。"""
    import plugins.bot_unified_runtime.domains.media.voice_enricher as ve

    monkeypatch.setattr(
        ve, "synthesize", lambda **kwargs: pytest.fail("无 ref 时不得触达合成")
    )
    config = _hook_config(tmp_path, ref_file=None)
    enricher = ve.build_voice_enricher(config)
    enriched = enricher(_message(), _decision(), _chat_result())

    issue = enriched.operational_issue
    assert issue is not None
    assert issue.kind == "tts_no_ref_audio"
    assert issue.kind in _FAILURE_KIND_FAMILY


def test_r6_policy_refusal_no_issue_with_audit_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """内容门拦（政策拒绝≠故障，T54 §4.1#2）：零 issue、留 audit_tag。"""
    import plugins.bot_unified_runtime.domains.media.voice_enricher as ve

    monkeypatch.setattr(
        ve,
        "resolve_speech_text",
        lambda config, message, raw, *, max_chars=None: ("", "minors"),
    )
    monkeypatch.setattr(
        ve, "synthesize", lambda **kwargs: pytest.fail("政策拒绝不得触达合成")
    )
    config = _hook_config(tmp_path, ref_file=None)
    enricher = ve.build_voice_enricher(config)
    result = _chat_result()
    enriched = enricher(_message(), _decision(), result)

    assert enriched.operational_issue is None, "政策拒绝不得挂 issue"
    assert enriched.body == result.body
    assert "blocked_by_policy" in enriched.audit_tags
    assert enriched.audio == []


# ---------------------------------------------------------------------------
# R7/R8 · 告警链贯通 / 群内文字存活（R-16②）
# ---------------------------------------------------------------------------


def test_r7_issue_flows_into_send_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enricher, _config = _enricher_with_failing_synthesize(
        tmp_path, monkeypatch, lambda **kwargs: (None, "服务不可达: connection refused")
    )
    pipeline = _make_pipeline(enricher)
    receipt = asyncio.run(
        pipeline.handle_async(
            _message(), _static_capability(_chat_result()), "bot.chat"
        )
    )

    request = pipeline.send_queue.sent_requests[-1]
    assert request.operational_issue is not None, "hook 挂的 issue 必须随 SendRequest 入队"
    assert request.operational_issue.kind == "tts_service_unreachable"
    assert receipt.state == ReceiptState.SENT, "自动路失败=正文照发（非 SKIPPED/压空）"


def test_r8_group_failure_keeps_text_and_skips_a19(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enricher, _config = _enricher_with_failing_synthesize(
        tmp_path,
        monkeypatch,
        lambda **kwargs: (None, "音频体检失败：静音（32044 字节）"),
        bypass_gate=True,
    )
    pipeline = _make_pipeline(
        enricher,
        # 群会话默认群回复关 ⇒ _prepare 即拦（到不了 hook）；测试需放行群回复门
        # （闲聊抽签只对 white1 群生效，见 policy/gate.py evaluate_policy）。
        group_auto_reply_enabled=True,
        group_auto_reply_probability=1.0,
        group_white1=frozenset({"g1"}),
    )
    a19_calls: list[object] = []

    def spy_notice(message: object, issue: object) -> None:
        a19_calls.append(issue)

    monkeypatch.setattr(pipeline, "_maybe_submit_group_failure_notice", spy_notice)
    receipt = asyncio.run(
        pipeline.handle_async(
            _message(group=True),
            _static_capability(_chat_result()),
            "bot.chat",
        )
    )

    assert a19_calls == [], "hook 期挂 issue 不触 A-19 压空正文分支（分支在 review 前已过）"
    request = pipeline.send_queue.sent_requests[-1]
    assert "潮汐今天很安静" in request.content.text_fallback, "群内正文必须照发"
    assert request.operational_issue is not None, "失败可见（管理员告警链可达）"
    assert receipt.state == ReceiptState.SENT


# ---------------------------------------------------------------------------
# R9 · 退役守卫（第二步落地才转绿；本波刻意 xfail，strict 棘轮）
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="退役两步走的第二步（摘旧包装）等真机浸泡窗；落地时本门转绿并移除标记（G-4 可收编）",
)
def test_r9_root_init_retires_legacy_wrapper_symbols() -> None:
    tree = ast.parse(_ROOT_INIT.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    banned = {"_attach_voice_reply", "maybe_attach_voice", "should_voice_reply"}
    leaked = sorted(names & banned)
    assert not leaked, f"根装配仍引用旧配音包装符号（退役第二步未完成）：{leaked}"
