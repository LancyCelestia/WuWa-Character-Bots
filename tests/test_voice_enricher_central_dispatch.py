"""S-VOICE · 自动配音第二出站腿 vs 中央能力调度器（mandate：所有内容走中央调度层，TTS 也不例外）。

事实基线（VOICE-V12 翻面后，2026-09-22）：
- 命令腿 ``bot.tts`` 早已通电中央（capability_registry 路由行 execution.adapter="command"，
  经 runtime/capability_protocols.py::orchestrated_command → default_invoker().invoke）。
- 自动配音腿 ``domains/media/voice_enricher.py``：G-3 起在 pipeline review 批准后（pipeline.py:810-811）
  被调用，历史形态于 ``:175`` **直连 ``synthesize(...)``**（旁路，层 2 不执法），由
  tests/test_orchestration_callsite_wave_media.py 钉为在册直呼。VOICE-V12 已把该直呼段
  换成 ``default_invoker().invoke(CapabilityRequest(capability_id="media.tts.autodub", …))``：
  合成这一步成为 media 族内容契约能力（descriptor + 中央 handler），层 2（权限/健康/90s 超时/
  降级/中央审计）对它执法；门链（该不该配）与取文/政策/硬顶仍留层 1 hook（每条「不配」零合成、零审计行）。

本文件是**常态化正向锁**（不再是旁路判据、不再挂 xfail；判据方向由「合成未走中央」翻成「合成必经
中央、且层 1 不再直呼 synthesize」，强度不降——反而更硬：既测行为、又测结构）：

- ``test_auto_voice_leg_reaches_central_invoker_exactly_once`` —— 行为判据：门链放行的一次配音，
  合成恰经 ``default_invoker().invoke("media.tts.autodub")`` **恰一行**，产物音频挂回呈现结果。
- ``test_auto_voice_leg_no_longer_calls_synthesize_directly`` —— 结构判据：voice_enricher 源码里
  已**无** ``synthesize(...)`` 直呼（AST），且 ``invoke(capability_id="media.tts.autodub")`` **恰一处**；
  真正的 synthesize 落点只剩中央 handler 一处（经 tts 域内 ``synthesize_autodub`` 真身）。

全离线零网络：``synthesize``/``resolve_speech_text``/``should_voice_reply`` 一律 monkeypatch，
落盘只写 tmp_path（合成原语经 context 注入到产出步 seam，与生产同一真身、逐字节等价）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_orchestration_callsite_single as v1gate  # 复用直呼/invoker 判据真身（不留第二支扫描器）

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    IncomingMessage,
)
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

_VE_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "media"
    / "voice_enricher.py"
)

_AUTODUB_CID = "media.tts.autodub"


# ---------------------------------------------------------------------------
# 离线夹具（与 tests/test_voice_hook_assembly.py::_hook_config 同构，只保留必要键）
# ---------------------------------------------------------------------------


def _message() -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        group_id="",
        plain_text="今天天气不错",
        message_id="m-1",
        debug_id="dbg-1",
    )


def _decision() -> BotDecision:
    return BotDecision(
        request_id="req-1",
        should_respond=True,
        mode="command",
        trigger="你好",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )


def _result() -> CapabilityResult:
    return CapabilityResult(
        request_id="req-1",
        capability_id="bot.chat",
        kind="text",
        body="潮汐今天很安静。",
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["chat"],
    )


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_tts_voice_hook_enabled=True,
        bot_tts_enabled=True,
        bot_tts_api_url="http://127.0.0.1:9880",
        bot_tts_gptsovits_dir="",
        bot_tts_ref_audios=[f"{tmp_path / 'ref.wav'}|参考文本|zh"],
        bot_tts_trigger_words=[],
        bot_tts_output_dir=str(tmp_path / "tts_out"),
        bot_tts_preset="shorekeeper",
        bot_tts_max_chars=200,
        bot_tts_hard_max_chars=2000,
        bot_tts_max_audio_bytes=0,
        bot_tts_cache_enabled=False,
        bot_tts_cache_max_bytes=0,
        bot_tts_cache_max_age_days=0,
        bot_tts_timeout_seconds=60.0,
        bot_tts_speed_factor=0.85,
        bot_tts_temperature=0.9,
        bot_tts_top_k=15,
        bot_tts_top_p=1.0,
        bot_tts_text_lang="zh",
        bot_tts_text_split_method="cut5",
        bot_tts_auto_reply_enabled=True,
        bot_tts_auto_reply_scope="private",
        bot_tts_auto_reply_max_chars=120,
        bot_tts_auto_reply_probability=1.0,
        bot_tts_auto_reply_always=True,
    )


@pytest.fixture()
def armed_enricher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """构建「门链全通、合成经中央 seam、invoker 被监视」的 enricher。

    返回 (enricher, synth_calls, invoker_calls)。合成经 default_invoker().invoke →
    media.tts.autodub handler → tts.synthesize_autodub(synth=ve.synthesize 注入替身) 落回 seam，
    故 synth_calls 记录被执行的文本、invoker_calls 记录中央被调 capability_id。
    """
    import plugins.bot_unified_runtime.domains.media.voice_enricher as ve

    (tmp_path / "ref.wav").write_bytes(b"RIFFref")
    wav = tmp_path / "fake.wav"
    wav.write_bytes(b"RIFFfake")

    synth_calls: list[str] = []

    def fake_synthesize(**kwargs: object):
        synth_calls.append(str(kwargs.get("text")))
        return wav, ""

    # 隔离门链谓词（本件只测「是否经中央 invoker」，不重测 T75 在飞改造的门链）。
    monkeypatch.setattr(ve, "should_voice_reply", lambda *a, **k: True)
    monkeypatch.setattr(
        ve, "resolve_speech_text", lambda *a, **k: ("潮汐今天很安静。", "")
    )
    # 合成原语在产出步 seam 注入确定性替身（生产传的是同一 tts.synthesize 本体，逐字节等价）。
    monkeypatch.setattr(ve, "synthesize", fake_synthesize)

    invoker_calls: list[str] = []
    real_invoke = cp.CapabilityInvoker.invoke

    def spy_invoke(self: object, request: object, *a: object, **k: object):
        invoker_calls.append(getattr(request, "capability_id", "<unknown>"))
        return real_invoke(self, request, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(cp.CapabilityInvoker, "invoke", spy_invoke)

    config = _config(tmp_path)
    return ve.build_voice_enricher(config), synth_calls, invoker_calls


# ---------------------------------------------------------------------------
# 行为正向锁：合成恰经中央 invoker 恰一行、产物挂回
# ---------------------------------------------------------------------------


def test_auto_voice_leg_reaches_central_invoker_exactly_once(
    armed_enricher: tuple,
) -> None:
    enricher, synth_calls, invoker_calls = armed_enricher

    enriched = enricher(_message(), _decision(), _result())

    # 前置自证：门链放行、合成确已发生（否则「invoker 恰一行」是空断言）。
    assert synth_calls == ["潮汐今天很安静。"], synth_calls
    assert enriched.audio, "合成产物应已挂回呈现结果"

    # 承重判据：合成这一步恰经一次中央 CapabilityInvoker，且落在 media.tts.autodub 上。
    assert invoker_calls == [_AUTODUB_CID], (
        "自动配音合成须经中央 invoker 恰一行（实得 "
        f"{invoker_calls}）——旁路回潮或双调用都会打红本锁"
    )


# ---------------------------------------------------------------------------
# 结构正向锁：层 1 不再直呼 synthesize；中央 invoke 站点恰一处
# ---------------------------------------------------------------------------


def test_auto_voice_leg_no_longer_calls_synthesize_directly() -> None:
    src = _VE_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # ①直呼旁路已闭合：voice_enricher 内不存在 ``synthesize(...)`` 执行直呼
    #   （synthesize 只作为可注入原语随请求 context 交中央，不再在本模块被调用）。
    assert not v1gate._execution_calls(tree, "synthesize"), (
        "voice_enricher 重新直呼 synthesize ⇒ 自动配音腿回退为旁路，本锁必红"
    )

    # ②中央 invoke 站点恰一处，且打在 media.tts.autodub 上（真 synthesize 只剩中央 handler
    #   一处经 tts 域内 synthesize_autodub 真身消费）。计数走 AST（文档字符串里的同名字面量
    #   不算调用点——literal 计数会被 docstring 骗，这是本仓踩过的「存在性糊过活性」变体）。
    invoke_sites = _autodub_invoke_sites(tree)
    assert invoke_sites == 1, (
        f"media.tts.autodub 的 invoke 调用点须恰一处（实得 AST 计数={invoke_sites}）"
    )


def _autodub_invoke_sites(tree: ast.AST) -> int:
    """``….invoke(CapabilityRequest(capability_id="media.tts.autodub", …))`` 的调用点个数。"""
    total = 0
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "invoke"
        ):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.keyword)
                and sub.arg == "capability_id"
                and isinstance(sub.value, ast.Constant)
                and sub.value.value == _AUTODUB_CID
            ):
                total += 1
                break
    return total
