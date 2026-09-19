"""Wave G T75 席回归锁：M-14 截断可观测化 + M-17 语音门中央同源 + T62 反审三条。

审计锚点（``.superpowers/sdd/2026-09-19-unify-audit/report-T29.md``）：

- **M-14（P1）**：``resolve_speech_text``/``clean_for_speech`` 的有损变换
  （打码、markdown 剥除、截断、占位符替换、词典替换）此前零可观测事实——
  T26-表3 实证「语音只念 42% 字」无人能从机读面看出来。本席修法=**只加
  机读结论（audit_tags），零文本处理行为变更**。
- **M-17（P1）**：``should_voice_reply`` 只查自有三值 scope，零导入中央
  ``explicit_allowed_for_session``——scope=all 对非白名单群一视同仁。
  修法=礼仪维度（scope）与安全维度（四名单）分层：scope 照旧是礼仪开关，
  群面在 scope 放行后**必须**过中央名单谓词（黑名单永远赢、群白名单空=
  群亲密面关闭绝不猜群）。缺省行为变化（安全方向）记入披露表。
- **T62 反审 P1-1**：``_last_failure_at``/``_last_failure_reason`` 必须锁内
  成对读写；失败原因必须随请求返回（否则并发下读到别的请求的原因 →
  ``_FAILURE_KINDS`` 错挂 kind 干扰 M-13 告警分类）。
- **T62 反审 P2-1**：失败分类学——确定性请求类拒绝（4xx，如 ref 3~10s 越界）
  不进 30s 退避窗（坏 ref 不该让全员周期性吃「服务没在跑」失真文案）；
  部署类失败（不可达/5xx/空音频）照旧进窗；体检失败（tts_bad_audio）不入窗
  （存疑-1 同口径：retryable=False → 不设窗）。
- **T62 反审 P2-2**：sha256 内容指纹正向钉死——stat-only 变异全绿=指纹语义
  零正向断言；本文件锁「指纹格式=sha256[:16]」与「内容变→键变，即使
  size+mtime 被还原」。

全离线，零网络零落盘（落盘只写 tmp_path）。
"""

from __future__ import annotations

import ast
import hashlib
import io
import os
import threading
import wave
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.content_safety import (
    SafetyAssessment,
)
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    TtsPreset,
    clean_for_speech,
    maybe_attach_voice,
    resolve_speech_text,
    should_voice_reply,
)
from plugins.bot_unified_runtime.domains.media.tts_presets import PRESET_REGISTRY

# 形如密钥的**假值**（不含任何真实凭据），只用来验打码与占位符观测。
_SECRET_SHAPE = "BOT_SUPER_ADMIN_API_KEY=sk-TESTFAKE12345 记得看海"
_LONG_MARKDOWN = (
    "## 标题\n\n正文第一段，带 [链接](https://example.com/x) 与 `代码`。\n\n"
    "- 列表一\n- 列表二\n\n```\ncode fence block\n```\n\n结尾一句。"
)


@pytest.fixture(autouse=True)
def _isolate_process_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    """每条用例干净 LRU 索引与退避状态（进程级全局，不隔离会跨用例串味）。"""
    monkeypatch.setattr(tts_mod, "_CACHE", OrderedDict())
    monkeypatch.setattr(tts_mod, "_last_failure_at", 0.0)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "")


def _config(**overrides: object) -> SimpleNamespace:
    base: dict[str, Any] = {
        "bot_tts_enabled": True,
        "bot_tts_api_url": "http://127.0.0.1:9880",
        "bot_tts_gptsovits_dir": "",
        "bot_tts_ref_audios": [],
        "bot_tts_trigger_words": [],
        "bot_tts_output_dir": "data/tts_output",
        "bot_tts_max_chars": 200,
        "bot_tts_hard_max_chars": 2000,
        "bot_tts_max_audio_bytes": 0,
        "bot_tts_cache_enabled": True,
        "bot_tts_cache_max_bytes": 0,
        "bot_tts_cache_max_age_days": 0,
        "bot_tts_timeout_seconds": 60.0,
        "bot_tts_preset": "shorekeeper",
        "bot_tts_auto_reply_enabled": True,
        "bot_tts_auto_reply_scope": "all",
        "bot_tts_auto_reply_max_chars": 120,
        "bot_tts_auto_reply_probability": 0.05,
        "bot_tts_auto_reply_always": False,
        # v21r5 中央四名单（M-17 同源对象；缺省全空=群面关闭）。
        "bot_content_route_group_whitelist": [],
        "bot_content_route_group_blacklist": [],
        "bot_content_route_private_whitelist": [],
        "bot_content_route_private_blacklist": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _msg(text: str = "在吗", *, group_id: str = "") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id=f"group:{group_id}" if group_id else "private:20000",
        session_type=SessionType.GROUP if group_id else SessionType.PRIVATE,
        sender_id="20000",
        group_id=group_id,
        plain_text=text,
    )


def _ref_file(tmp_path: Path, name: str = "ref.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(b"RIFF-voice-reference-bytes")
    return path


def _wav_bytes(*, seconds: float = 0.2, rate: int = 32000) -> bytes:
    """真 PCM16 单声道 wav（能过音频体检闸的产物形态）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def _chat_result(body: str = "今天的潮汐很安静。") -> CapabilityResult:
    return CapabilityResult(
        request_id="req-t75",
        capability_id="bot.chat",
        kind="text",
        body=body,
    )


# ---------------------------------------------------------------------------
# M-17：语音门群面接入中央名单谓词（礼仪维度 scope 与安全维度四名单分层）
# ---------------------------------------------------------------------------


def test_voice_gate_group_face_requires_central_whitelist() -> None:
    """scope=all + 群白名单空（缺省）⇒ 群面不配音（绝不猜群）。

    缺省行为变化（安全方向，T29 M-17 修法本体）：旧代码 scope=all 对任何群
    一视同仁放行；现在必须过中央四名单。
    """
    config = _config(bot_tts_auto_reply_scope="all", bot_tts_auto_reply_always=True)
    assert not should_voice_reply(config, _msg(group_id="123456"), _chat_result())


def test_voice_gate_group_face_allows_whitelisted_group() -> None:
    """白名单命中且不在黑名单 ⇒ 群面放行（安全门过了，礼仪照旧）。"""
    config = _config(
        bot_tts_auto_reply_scope="all",
        bot_tts_auto_reply_always=True,
        bot_content_route_group_whitelist=["123456"],
    )
    assert should_voice_reply(config, _msg(group_id="123456"), _chat_result())


def test_voice_gate_blacklist_beats_whitelist() -> None:
    """黑名单永远赢：同群同时在黑白名单 ⇒ 拒绝。"""
    config = _config(
        bot_tts_auto_reply_scope="all",
        bot_tts_auto_reply_always=True,
        bot_content_route_group_whitelist=["123456"],
        bot_content_route_group_blacklist=["123456"],
    )
    assert not should_voice_reply(config, _msg(group_id="123456"), _chat_result())


def test_voice_gate_group_list_applies_to_scope_group_too() -> None:
    """scope=group 的群面同走中央名单（安全维度与 scope 取值无关）。"""
    config = _config(
        bot_tts_auto_reply_scope="group",
        bot_tts_auto_reply_always=True,
        bot_content_route_group_whitelist=["999"],
    )
    assert not should_voice_reply(config, _msg(group_id="123456"), _chat_result())
    assert should_voice_reply(config, _msg(group_id="999"), _chat_result())


def test_voice_gate_private_face_unaffected_by_group_lists() -> None:
    """私聊面不吃群名单：scope=all 私聊照旧放行（M-17 只收群面）。"""
    config = _config(bot_tts_auto_reply_scope="all", bot_tts_auto_reply_always=True)
    assert should_voice_reply(config, _msg(), _chat_result())


def test_voice_gate_scope_etiquette_still_gates_first() -> None:
    """分层：scope=private（礼仪）即使在白名单群里也不配音——scope 不降级为
    安全门，名单也不取代礼仪开关，两门串联。"""
    config = _config(
        bot_tts_auto_reply_scope="private",
        bot_tts_auto_reply_always=True,
        bot_content_route_group_whitelist=["123456"],
    )
    assert not should_voice_reply(config, _msg(group_id="123456"), _chat_result())


def test_maybe_attach_voice_group_skip_is_silent_gain_drop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端到端：非白名单群里 maybe_attach_voice 不合成、文字回复原样出站。"""
    calls: list[str] = []

    def _no_synth(**_kwargs: object) -> tuple[bytes, str]:
        calls.append("synth")
        return _wav_bytes(), ""

    monkeypatch.setattr(tts_mod, "synthesize", _no_synth)
    patched = maybe_attach_voice(
        _msg(group_id="123456"),
        _chat_result(),
        config=_config(
            bot_tts_auto_reply_scope="all",
            bot_tts_auto_reply_always=True,
            bot_tts_ref_audios=[f"{_ref_file(tmp_path)}|你好|zh"],
            bot_tts_output_dir=str(tmp_path / "out"),
        ),
    )
    assert calls == [], "非白名单群绝不得触发合成"
    assert patched.audio == [], "群面被名单拦下时不得带音频"


# ---------------------------------------------------------------------------
# M-14：有损变换可观测化（零行为变更，只加机读结论）
# ---------------------------------------------------------------------------


def test_resolve_speech_text_audit_reports_stripping() -> None:
    audit: dict[str, Any] = {}
    speech, reason = resolve_speech_text(
        _config(), _msg(), _LONG_MARKDOWN, max_chars=0, audit=audit
    )
    assert reason == "" and speech
    assert audit["stripped"] is True, "markdown 剥除是有损变换，必须留机读结论"
    assert 0.0 < audit["kept_ratio"] < 1.0
    assert audit["truncated"] is False
    assert audit["kept_len"] == len(speech)


def test_resolve_speech_text_audit_reports_truncation() -> None:
    audit: dict[str, Any] = {}
    body = "这是一段很长的话，" * 30
    speech, _reason = resolve_speech_text(
        _config(), _msg(), body, max_chars=40, audit=audit
    )
    assert len(speech) <= 40
    assert audit["truncated"] is True
    assert audit["kept_ratio"] < 1.0
    assert audit["kept_len"] == len(speech)
    assert audit["raw_len"] == len(body)


def test_resolve_speech_text_audit_reports_redaction_and_placeholder() -> None:
    audit: dict[str, Any] = {}
    speech, _reason = resolve_speech_text(
        _config(), _msg(), _SECRET_SHAPE, max_chars=0, audit=audit
    )
    assert audit["redacted"] is True, "打码发生必须留机读结论"
    assert audit["placeholders_replaced"] >= 1, "打码占位符替换必须计数"
    assert "已隐去" in speech
    assert "sk-TESTFAKE" not in speech


def test_resolve_speech_text_audit_reports_lexicon_hits() -> None:
    lex_preset = TtsPreset(
        preset_id="t75lex",
        params=dict(PRESET_REGISTRY["shorekeeper"].params),
        lexicon={"潮汐": "海浪"},
    )
    saved_registry = tts_mod.PRESET_REGISTRY
    tts_mod.PRESET_REGISTRY = {**saved_registry, "t75lex": lex_preset}
    try:
        audit: dict[str, Any] = {}
        speech, _reason = resolve_speech_text(
            _config(bot_tts_preset="t75lex"),
            _msg(),
            "今天的潮汐很安静",
            max_chars=0,
            audit=audit,
        )
    finally:
        tts_mod.PRESET_REGISTRY = saved_registry
    assert "海浪" in speech and "潮汐" not in speech
    assert audit["lexicon_replaced"] == 1


def test_resolve_speech_text_audit_clean_text_has_no_lossy_tags() -> None:
    """无害短句：有损事实全 false——稀疏-真值口径的负样本锁。"""
    audit: dict[str, Any] = {}
    speech, _reason = resolve_speech_text(
        _config(), _msg(), "今天的潮汐很安静", max_chars=0, audit=audit
    )
    assert speech == "今天的潮汐很安静"
    assert audit["redacted"] is False
    assert audit["stripped"] is False
    assert audit["truncated"] is False
    assert audit["kept_ratio"] == 1.0


def test_clean_for_speech_tracked_matches_public_function() -> None:
    """零行为变更锁：带审计的内部分析与公开 pure 函数逐字一致。"""
    tracked = tts_mod._clean_for_speech_tracked
    corpus = [
        "",
        "   ",
        _LONG_MARKDOWN,
        "说 普通一句话",
        "```\nfence\n```\n尾随文字",
        "[链接](https://example.com) 与 文本",
        "- 一\n- 二\n",
        "超长正文，" * 60,
    ]
    for text in corpus:
        for limit in (0, 10, 50, 200):
            assert tracked(text, max_chars=limit)[0] == clean_for_speech(
                text, max_chars=limit
            ), f"清洗行为变更！corpus={text[:20]!r} limit={limit}"


def test_capability_success_emits_lossy_audit_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """命令路：截断发生 ⇒ audit_tags 出现机读结论（truncated=true/kept_ratio=）。"""
    from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
        build_tts_capability,
    )

    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kw: (_wav_bytes(), ""))
    capability = build_tts_capability(
        _config(
            bot_tts_max_chars=20,
            bot_tts_ref_audios=[f"{_ref_file(tmp_path)}|你好|zh"],
            bot_tts_output_dir=str(tmp_path / "out"),
        )
    )
    result = capability(_msg("说 " + "这句话特别长，" * 30), None)
    assert result.audio, "正常合成不应被审计改造影响"
    assert "truncated=true" in result.audit_tags
    assert any(tag.startswith("kept_ratio=") for tag in result.audit_tags)


def test_auto_reply_skip_over_hard_cap_emits_audit_tags(tmp_path: Path) -> None:
    """自动路：超硬顶放弃增益 ⇒ 留机读痕迹（生产 logger.info 直接丢失）。"""
    original = _chat_result(body="超" * 2500)  # max_chars=0 不截断，2500>2000 硬顶
    patched = maybe_attach_voice(
        _msg(),
        original,
        config=_config(
            bot_tts_auto_reply_always=True,
            bot_tts_auto_reply_max_chars=0,
            bot_tts_ref_audios=[f"{_ref_file(tmp_path)}|你好|zh"],
            bot_tts_output_dir=str(tmp_path / "out"),
        ),
    )
    assert patched.audio == []
    assert "auto_reply_skipped" in patched.audit_tags
    assert "over_hard_cap" in patched.audit_tags
    assert original.audio == []


def test_auto_reply_skip_policy_blocked_emits_audit_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _refuse(*_a: object, **_k: object) -> SafetyAssessment:
        return SafetyAssessment("refuse", "minors", "stubbed", "stubbed")

    monkeypatch.setattr(tts_mod, "assess_public_content", _refuse)
    patched = maybe_attach_voice(
        _msg(), _chat_result(), config=_config(bot_tts_auto_reply_always=True)
    )
    assert patched.audio == []
    assert "auto_reply_skipped" in patched.audit_tags
    assert "blocked_by_policy" in patched.audit_tags


def test_auto_reply_skip_synthesize_failed_emits_kind_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tts_mod, "synthesize", lambda **_kw: (None, "服务不可达：ConnectError")
    )
    patched = maybe_attach_voice(
        _msg(),
        _chat_result(),
        config=_config(
            bot_tts_auto_reply_always=True,
            bot_tts_ref_audios=[f"{_ref_file(tmp_path)}|你好|zh"],
            bot_tts_output_dir=str(tmp_path / "out"),
        ),
    )
    assert patched.audio == []
    assert "auto_reply_skipped" in patched.audit_tags
    assert "tts_service_unreachable" in patched.audit_tags


def test_auto_reply_success_emits_lossy_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kw: (_wav_bytes(), ""))
    patched = maybe_attach_voice(
        _msg(),
        _chat_result(body="这句话同样很长，" * 30),
        config=_config(
            bot_tts_auto_reply_max_chars=15,
            bot_tts_auto_reply_always=True,
            bot_tts_ref_audios=[f"{_ref_file(tmp_path)}|你好|zh"],
            bot_tts_output_dir=str(tmp_path / "out"),
        ),
    )
    assert patched.audio
    assert "auto_reply" in patched.audit_tags
    assert "truncated=true" in patched.audit_tags


# ---------------------------------------------------------------------------
# T62 P1-1：退避状态锁纪律 + 失败原因随请求返回
# ---------------------------------------------------------------------------


def test_failure_reason_travels_with_the_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """并发错挂锁：synthesize 的失败原因必须是**本次请求**自己的。

    旧实现从模块全局 ``_last_failure_reason`` 读——并发下别的请求可能刚好
    覆盖全局，``_FAILURE_KINDS`` 就会错挂 kind（M-13 告警分类被污染）。
    本用例把「 foreign 写入恰好落在读之前」确定性复现：真实 ``_record_failure``
    记录本次失败后立刻模拟并发请求覆盖全局。
    """
    real_record = tts_mod._record_failure

    def _record_then_foreign_interleave(reason: str) -> None:
        real_record(reason)
        real_record("服务返回 400：来自并发请求的失败原因")

    monkeypatch.setattr(tts_mod, "_record_failure", _record_then_foreign_interleave)

    class _FakeResponse:
        status_code = 200
        content = b""

    class _FakeClient:
        def __init__(self, **_kw: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def post(self, *_a: object, **_k: object) -> _FakeResponse:
            raise OSError("connection refused")

    monkeypatch.setitem(
        __import__("sys").modules, "httpx", SimpleNamespace(Client=_FakeClient)
    )
    ref = tts_mod.RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    path, reason = tts_mod.synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=tts_mod.TtsParams(
            text_lang="zh",
            speed_factor=0.85,
            temperature=0.9,
            top_k=15,
            top_p=1.0,
            text_split_method="cut5",
        ),
        output_dir=tmp_path / "out",
    )
    assert path is None
    assert "400" not in reason, f"失败原因被并发请求错挂：{reason}"
    assert "并发请求" not in reason
    assert "不可达" in reason, f"必须携带本次请求自己的失败原因：{reason}"


def test_backoff_state_access_is_lock_confined() -> None:
    """AST 结构锁：``_last_failure_at/_last_failure_reason`` 的写只许出现在
    ``_record_failure``/``_clear_failure``，读只许出现在持锁三函数。"""
    source = Path(tts_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    write_ok = {"_record_failure", "_clear_failure"}
    read_ok = {"_record_failure", "_clear_failure", "_backoff_reason"}
    globals_named = {"_last_failure_at", "_last_failure_reason"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    for name in ast.walk(target):
                        if isinstance(name, ast.Name) and name.id in globals_named:
                            assert node.name in write_ok, (
                                f"{node.name} 锁外裸写 {name.id}（T62 P1-1）"
                            )
            if (
                isinstance(sub, ast.Name)
                and isinstance(sub.ctx, ast.Load)
                and sub.id in globals_named
            ):
                assert node.name in read_ok, (
                    f"{node.name} 锁外裸读 {sub.id}（T62 P1-1）"
                )


def test_backoff_pair_stays_consistent_under_concurrency() -> None:
    """并发锤：多线程写失败状态、读端拿到的 reason 必须属于已写入集合
    （成对读写，不撕裂）。"""
    reasons = [f"服务不可达：Worker{i}" for i in range(4)]
    errors: list[str] = []
    stop = threading.Event()

    def _writer(index: int) -> None:
        for _ in range(150):
            tts_mod._record_failure(reasons[index])
            if stop.is_set():
                return

    def _reader() -> None:
        for _ in range(600):
            text = tts_mod._backoff_reason()
            if text:
                marker = text.split("上次失败：", 1)[-1]
                if marker not in reasons:
                    errors.append(marker)
        stop.set()

    threads = [
        threading.Thread(target=_writer, args=(i,)) for i in range(len(reasons))
    ]
    reader = threading.Thread(target=_reader)
    for thread in threads:
        thread.start()
    reader.start()
    for thread in threads:
        thread.join()
    reader.join()
    tts_mod._clear_failure()
    assert not errors, f"退避状态读到了撕裂/外来原因：{errors[:5]}"
    assert tts_mod._backoff_reason() == ""


# ---------------------------------------------------------------------------
# T62 P2-1：失败分类学（确定性请求类拒绝不进退避窗）
# ---------------------------------------------------------------------------


def _install_rejecting_httpx(
    monkeypatch: pytest.MonkeyPatch, *, status_code: int
) -> list[int]:
    attempts: list[int] = []

    class _FakeResponse:
        def __init__(self) -> None:
            self.status_code = status_code
            self.content = b""
            self.text = ""

        def json(self) -> dict[str, object]:
            return {"message": "tts failed", "Exception": "参考音频在3~10秒范围外"}

    class _FakeClient:
        def __init__(self, **_kw: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def post(self, *_a: object, **_k: object) -> _FakeResponse:
            attempts.append(1)
            return _FakeResponse()

    monkeypatch.setitem(
        __import__("sys").modules, "httpx", SimpleNamespace(Client=_FakeClient)
    )
    return attempts


def test_deterministic_4xx_rejection_does_not_arm_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2-1 本体：400（ref 3~10s 越界等确定性拒绝）不设 30s 退避窗。"""
    attempts = _install_rejecting_httpx(monkeypatch, status_code=400)
    ref = tts_mod.RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    params = tts_mod.TtsParams(
        text_lang="zh",
        speed_factor=0.85,
        temperature=0.9,
        top_k=15,
        top_p=1.0,
        text_split_method="cut5",
    )
    out = tts_mod._request_tts(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=params,
        timeout_seconds=5.0,
        engine_params=dict(tts_mod.PRESET_REGISTRY["shorekeeper"].params),
        seed=1,
    )
    assert isinstance(out, tuple), "_request_tts 契约=(bytes|None, reason)"
    assert out[0] is None and "3~10秒" in out[1]
    assert tts_mod._last_failure_at == 0.0, "确定性请求类拒绝不得进退避窗"

    path2, reason2 = tts_mod.synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=params,
        output_dir=tmp_path / "out",
    )
    assert path2 is None and "3~10秒" in reason2
    assert len(attempts) == 2, "第二次合成必须仍真打服务（无退避窗）"
    assert "退避" not in reason2, "不得给确定性拒绝套「服务没在跑」失真文案"


def test_deployment_5xx_still_arms_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """部署类失败（5xx）照旧进窗：窗内快速失败不再打服务。"""
    attempts = _install_rejecting_httpx(monkeypatch, status_code=502)
    ref = tts_mod.RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    params = tts_mod.TtsParams(
        text_lang="zh",
        speed_factor=0.85,
        temperature=0.9,
        top_k=15,
        top_p=1.0,
        text_split_method="cut5",
    )
    first_path, first_reason = tts_mod.synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=params,
        output_dir=tmp_path / "out",
    )
    assert first_path is None and "502" in first_reason
    assert tts_mod._last_failure_at > 0.0, "部署类失败必须进退避窗"
    second_path, second_reason = tts_mod.synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=params,
        output_dir=tmp_path / "out",
    )
    assert second_path is None
    assert len(attempts) == 1, "窗内不得再打服务"
    assert "退避" in second_reason or "冷却" in second_reason


def test_bad_audio_inspection_failure_does_not_arm_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """存疑-1 裁定锁：体检失败（tts_bad_audio，retryable=False）不入退避窗。"""
    attempts: list[int] = []

    class _FakeResponse:
        status_code = 200
        content = b"not-a-wav-at-all"
        text = ""

        @staticmethod
        def json() -> dict[str, object]:
            return {}

    class _FakeClient:
        def __init__(self, **_kw: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def post(self, *_a: object, **_k: object) -> _FakeResponse:
            attempts.append(1)
            return _FakeResponse()

    monkeypatch.setitem(
        __import__("sys").modules, "httpx", SimpleNamespace(Client=_FakeClient)
    )
    ref = tts_mod.RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    params = tts_mod.TtsParams(
        text_lang="zh",
        speed_factor=0.85,
        temperature=0.9,
        top_k=15,
        top_p=1.0,
        text_split_method="cut5",
    )
    first_path, first_reason = tts_mod.synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=params,
        output_dir=tmp_path / "out",
    )
    assert first_path is None and "体检" in first_reason
    assert tts_mod._last_failure_at == 0.0, "体检失败不入退避窗（retryable=False）"
    second_path, _r = tts_mod.synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=params,
        output_dir=tmp_path / "out",
    )
    assert second_path is None
    assert len(attempts) == 2, "体检失败不得让下一次合成吃退避快速失败"


# ---------------------------------------------------------------------------
# T62 P2-2：sha256 内容指纹正向钉死
# ---------------------------------------------------------------------------


def test_ref_fingerprint_is_sha256_prefix_of_content(tmp_path: Path) -> None:
    """正向钉死（杀 stat-only 变异）：指纹必须是内容 sha256 的前 16 hex。"""
    content = b"RIFF-reference-audio-take-one"
    path = tmp_path / "ref.wav"
    path.write_bytes(content)
    fingerprint = tts_mod._ref_fingerprint(str(path))
    assert fingerprint == hashlib.sha256(content).hexdigest()[:16]
    assert len(fingerprint) == 16
    assert all(ch in "0123456789abcdef" for ch in fingerprint)


def test_ref_fingerprint_detects_content_change_with_restored_stat(
    tmp_path: Path,
) -> None:
    """内容变→键变，即使 size+mtime 被还原（T62 P2-2；备份还原/touch 场景）。"""
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF-take-one-aaaaaa")
    first = tts_mod._ref_fingerprint(str(path))
    stat_before = path.stat()
    path.write_bytes(b"RIFF-take-two-bbbbbb")  # 同长度换内容（只动内容不动 size）
    os.utime(path, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
    second = tts_mod._ref_fingerprint(str(path))
    assert second != first, "内容变了指纹没变 = 永久命中旧音色（stat-only 复辟）"
    assert second == hashlib.sha256(b"RIFF-take-two-bbbbbb").hexdigest()[:16]


def test_cache_key_changes_when_ref_content_changes_with_same_stat(
    tmp_path: Path,
) -> None:
    """键级端到端：同 stat 换内容 ⇒ 缓存键必须换代（旧键失配）。"""
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF-key-take-one")
    ref = tts_mod.RefAudio(path=str(path), text="你好", lang="zh")
    params = tts_mod.TtsParams(
        text_lang="zh",
        speed_factor=0.85,
        temperature=0.9,
        top_k=15,
        top_p=1.0,
        text_split_method="cut5",
    )
    first = tts_mod._cache_key("正文", ref, params, api_url="http://127.0.0.1:9880", preset_id="shorekeeper")
    stat_before = path.stat()
    path.write_bytes(b"RIFF-key-take-two")
    os.utime(path, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
    second = tts_mod._cache_key("正文", ref, params, api_url="http://127.0.0.1:9880", preset_id="shorekeeper")
    assert first != second
