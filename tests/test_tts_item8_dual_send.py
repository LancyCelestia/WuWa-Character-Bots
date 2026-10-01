"""用户第 8 项（TTS）的三面补充锁（席 TTS，2026-09-29）。

先说清「本席补的是哪一面」——第 8 项的两半在仓里已有地基，本件不重复造锁：

* **10% 概率**：数值源 ``config.py`` 的 ``bot_tts_auto_reply_probability``（缺省 0.10）
  已由 ``tests/test_tts_probability_lock.py`` 钉死（单一读点 / 派生梯子 / 5σ 带 /
  四处口径一致 / 现网实况），本件只补「概率判据是纯函数且同消息不重掷」的一条
  独立复算（下方 E 组），不复述那套判据。
* **「原文本 + 语音音频」双发**：命令路与自动腿各自有零散锁
  （``test_tts.py::test_capability_success_emits_audio_only`` 断 body==念出文本、
  ``test_tts_result_transform.py`` 断正文未被吃、``test_tts_outbound_chain.py``
  断 mixed 部件）。**缺口是这三条腿从未被同一个「双发」判据一起验过**，也从未
  验过「发出去的是**一条消息里的两个部件**」这一形态（双发最容易退化成两条消息
  ⇒ part 级幂等账翻倍 ⇒ 刷屏）。⇒ A 组 + D 组。
* **孤立语音**：需求原话是「不能只发语音、也不能只发文本」。自动配音两腿的取文
  口从正文派生，正文为空时**结构性**应当无语音可发，但这条不变量在全树没有
  任何锁（B 组）。
* **时长/大小超限的诚实降级**：产物字节顶（≈语音条时长顶）超限与文字硬顶超限，
  用户侧此前拿到的是一句不带数值的通用话（「这次没能发出声音……」），既不
  说明「为什么」也不说明「下一步怎么办」⇒ 违简报第 4 项与本仓「讲清事实」铁律。
  C 组把这两类超限钉成**带关键数值**的守岸人文案。

全离线：零网络、零引擎（127.0.0.1:9880 一次都不碰）、零进程、不碰生产库。
"""

from __future__ import annotations

import io
import wave
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any

import pytest
from helpers.voice_queue_sim import SimulatedOneBotBot, build_mixed_request

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    ReceiptState,
    ReviewResult,
    SessionType,
)
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    build_tts_capability,
    maybe_attach_voice,
    should_voice_reply,
)
from plugins.bot_unified_runtime.domains.media.tts import result_transform as rt

# 2026-09-29 席 S-FIX-SHIM-REFS：原写 `from plugins.bot_unified_runtime.output.renderer import`
# （旧布局垫片路径＝`board_shim_ledger` 在册待退役枚，上限 6 被本枚顶到 7；该壳只有一句
# `from ...domains.render.renderer import *`），同批改指真身，符号同名。
from plugins.bot_unified_runtime.domains.render.renderer import render_reviewed_output

_SPEECH = "今天的潮汐很安静"
#: Q-01 旧句式（与 tests/test_user_copy_unification_gate.py 同一把尺，此处只作
#: 本组文案的自我约束，不构成第二判据真身）。
_BANNED_COPY = ("晚点再试试？", "稍后再试试？", "稍后再试一次。", "，稍后再试。")


def _config(**overrides: Any) -> SimpleNamespace:
    """能力层只走 getattr ⇒ 最小配置对象足够（与 test_tts.py 同形）。"""
    base: dict[str, Any] = {
        "bot_tts_enabled": True,
        "bot_tts_api_url": "http://127.0.0.1:9880",
        "bot_tts_gptsovits_dir": "",
        "bot_tts_ref_audios": [],
        "bot_tts_trigger_words": [],
        "bot_tts_max_chars": 200,
        "bot_tts_timeout_seconds": 60.0,
        "bot_tts_auto_reply_enabled": True,
        "bot_tts_auto_reply_scope": "private",
        "bot_tts_auto_reply_max_chars": 120,
        "bot_tts_auto_reply_split_max_chars": 0,
        "bot_tts_auto_reply_probability": 0.1,
        "bot_tts_auto_reply_always": False,
        "bot_tts_voice_hook_enabled": True,
        "bot_tts_cache_enabled": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _msg(text: str = "在吗") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id="private:20000",
        session_type=SessionType.PRIVATE,
        sender_id="20000",
        message_id="m-item8",
        plain_text=text,
    )


def _chat_result(body: str = _SPEECH) -> CapabilityResult:
    return CapabilityResult(
        request_id="req-item8", capability_id="bot.chat", kind="text", body=body
    )


def _wav(tmp_path: Any, name: str = "synth.wav") -> Any:
    """真 PCM16 单声道 wav（假魔数会被体检闸判不可播，夹具必须能过 wave 解析）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(32000)
        handle.writeframes(b"\x00\x01" * 3200)
    path = tmp_path / name
    path.write_bytes(buf.getvalue())
    return path


def _ref(tmp_path: Any) -> str:
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF....WAVEfmt ")
    return f"{path}|你好|zh"


def _parts(result: CapabilityResult) -> list[dict[str, Any]]:
    rendered = render_reviewed_output(result, ReviewResult(request_id=result.request_id, approved=True))
    assert rendered.content_type == "mixed", f"双发形态必须是 mixed，实得 {rendered.content_type}"
    return rendered.content_ref["parts"]


def _assert_dual_send(parts: list[dict[str, Any]], *, expected_text: str | None = None) -> None:
    """第 8 项判据本体：文字腿与音频腿**同时在场**，且文字腿只有一条。"""
    types = [str(part.get("type")) for part in parts]
    assert types.count("record") >= 1, f"缺语音部件：{types}"
    assert types.count("text") == 1, f"文字腿必须恰有一条（多了就是重复刷屏）：{types}"
    text_part = next(part for part in parts if part.get("type") == "text")
    body = str(text_part.get("text") or "").strip()
    assert body, f"文字腿为空 ⇒ 退化成「只发语音」：{parts}"
    if expected_text is not None:
        assert body == expected_text, "文字腿必须与实际念出的那串字同值"


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod, "_CACHE", OrderedDict())
    monkeypatch.setattr(tts_mod, "_last_failure_at", 0.0)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "")


# ---------------------------------------------------------------------------
# A｜三条出站腿都要「原文本 + 语音音频」同时在场
# ---------------------------------------------------------------------------


def test_command_leg_sends_text_and_audio(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = _wav(tmp_path)
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kw: (wav, ""))
    capability = build_tts_capability(
        _config(bot_tts_ref_audios=[_ref(tmp_path)], bot_tts_output_dir=str(tmp_path / "out"))
    )
    result = capability(_msg(f"说 {_SPEECH}"), None)
    assert result.audio, "命令路必须带音频"
    _assert_dual_send(_parts(result), expected_text=_SPEECH)


def test_legacy_wrapper_leg_sends_text_and_audio(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = _wav(tmp_path)
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kw: (wav, ""))
    config = _config(bot_tts_ref_audios=[_ref(tmp_path)], bot_tts_auto_reply_always=True)
    patched = maybe_attach_voice(_msg(), _chat_result(), config=config)
    assert patched.audio, "旧包装腿必须挂上语音"
    _assert_dual_send(_parts(patched), expected_text=_SPEECH)


def test_hook_leg_sends_text_and_audio(tmp_path: Any) -> None:
    """现网实况腿（``BOT_TTS_VOICE_HOOK_ENABLED=true``）：中央变换后仍是双发。"""
    wav = _wav(tmp_path)
    config = _config(bot_tts_ref_audios=[_ref(tmp_path)], bot_tts_auto_reply_always=True)

    def _dub(chunk: str) -> rt.DubOutcome:
        return rt.DubOutcome(
            rt.OUTCOME_DUBBED,
            {"audio_parts": [{"file": str(wav), "review_text": chunk}], "audit_tags_delta": ["tts"]},
        )

    enriched, code = rt.transform_presentation(config, _msg(), _chat_result(), dub=_dub)
    assert code == rt.OUTCOME_DUBBED
    assert enriched.audio, "hook 腿必须挂上语音"
    _assert_dual_send(_parts(enriched), expected_text=_SPEECH)


# ---------------------------------------------------------------------------
# B｜绝不发「孤立语音」（正文为空 ⇒ 一条都不发语音）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body", ["", "   ", "```python\nx = 1\n```"])
def test_voice_never_outbound_alone_legacy_leg(tmp_path: Any, body: str) -> None:
    config = _config(
        bot_tts_ref_audios=[_ref(tmp_path)],
        bot_tts_auto_reply_always=True,
        bot_tts_output_dir=str(tmp_path / "out"),
    )
    patched = maybe_attach_voice(_msg(), _chat_result(body=body), config=config)
    assert not patched.audio, "没有可印证的正文就不许只发语音（第 8 项反面）"
    assert patched.body == body, "文字面不得被改写"


def test_voice_never_outbound_alone_hook_leg(tmp_path: Any) -> None:
    config = _config(
        bot_tts_ref_audios=[_ref(tmp_path)],
        bot_tts_auto_reply_always=True,
        bot_tts_output_dir=str(tmp_path / "out"),
    )
    called: list[str] = []

    def _dub(chunk: str) -> rt.DubOutcome:
        called.append(chunk)
        return rt.DubOutcome(rt.OUTCOME_DUBBED, {"audio_parts": [{"file": str(_wav(tmp_path))}]})

    enriched, _code = rt.transform_presentation(
        config, _msg(), _chat_result(body=""), dub=_dub
    )
    assert enriched.audio == [], "空正文绝不产语音"
    assert called == [], "空正文连产出步都不该派出去"


# ---------------------------------------------------------------------------
# C｜时长/大小超限的诚实降级（讲清事实与下一步，不带空话）
# ---------------------------------------------------------------------------


def test_byte_cap_degrade_names_both_durations() -> None:
    """字节顶=语音条时长顶的代理量（32000Hz/16bit/单声道=64000 B/s）。

    8 MiB≈131 秒这个数字在仓里只有 config 注释与 tts_presets 文档说过话术，
    文案面此前完全看不见 ⇒ 本条把它钉成用户能读到的事实。
    """
    copy = tts_mod._degrade("音频体检失败：产物 10485760 字节超字节顶 8388608（10485760 字节）")
    assert "163" in copy and "131" in copy, f"超限文案必须报出「念了多久/上限多久」：{copy}"
    assert "秒" in copy
    assert "字节" not in copy, "内部单位不进用户侧"
    for banned in _BANNED_COPY:
        assert banned not in copy
    assert not copy.endswith(("～", "〜"))


def test_engine_reject_code_is_surfaced_honestly() -> None:
    copy = tts_mod._degrade("服务返回 500：Internal Server Error")
    assert "500" in copy, f"引擎返回码要如实报出：{copy}"
    assert "服务返回" not in copy, "内部原因串不原样出门（既有锁 test_tts.py:733）"


def test_last_resort_copy_still_tells_next_step() -> None:
    copy = tts_mod._degrade("音频落盘失败：OSError")
    assert copy and "落盘" not in copy
    assert "字" in copy or "文字" in copy, f"降级必须交代文字腿仍在：{copy}"


def test_over_hard_cap_body_quotes_both_numbers(tmp_path: Any) -> None:
    """文字硬顶超限：文案要点名「这句多长 / 上限多长」，audit_tags 不是用户侧。"""
    long_text = "今天的潮汐很安静，" * 6  # 144 字，远超 10 字硬顶
    capability = build_tts_capability(
        _config(bot_tts_ref_audios=[_ref(tmp_path)], bot_tts_hard_max_chars=10)
    )
    result = capability(_msg(f"说 {long_text}"), None)
    assert not result.audio
    assert "over_hard_cap" in result.audit_tags
    speech_len = len(tts_mod.clean_for_speech(long_text, max_chars=0))
    assert "10" in result.body, f"硬顶值要出现在文案里：{result.body}"
    assert str(speech_len) in result.body, f"实际字数要出现在文案里：{result.body}"
    for banned in _BANNED_COPY:
        assert banned not in result.body


# ---------------------------------------------------------------------------
# D｜双发=同一条消息的两个部件，不是两条消息（part 级幂等账不翻倍）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dual_send_is_one_dispatch_with_two_parts(tmp_path: Any) -> None:
    from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
        send_onebot_v11,
    )

    bot = SimulatedOneBotBot(behavior="ok")
    request = build_mixed_request(
        "item8-dual", text=_SPEECH, record_file=str(_wav(tmp_path))
    )
    receipt = await send_onebot_v11(bot, request, timeout_seconds=1.0)
    assert receipt.state is ReceiptState.SENT
    assert len(bot.calls) == 1, "双发必须是同一条消息，拆两次派发=翻倍刷屏面"
    types = [str(segment["type"]) for segment in bot.calls[0].segments]
    assert sorted(types) == ["record", "text"], f"两个部件一条消息：{types}"
    assert types.count("text") == 1


# ---------------------------------------------------------------------------
# E｜概率门是纯函数：同消息恒同结论、长期命中率跟配置值（10% 面独立复算）
# ---------------------------------------------------------------------------


def test_probability_is_pure_and_hits_the_configured_band() -> None:
    """``should_voice_reply`` 无副作用可复算：10000 条固定语料按配置值落带。

    与 tests/test_tts_probability_lock.py 的分工：那件钉「数值源与四处口径」，
    本条只钉「抽签本身」——同一条消息两次判定同结论（不重掷骰）、且长期命中率
    与配置值同增同减（简报第 1 项要求的性质测试）。
    """
    probability = 0.1
    config = _config(
        bot_tts_auto_reply_probability=probability,
        bot_tts_auto_reply_always=False,
        bot_tts_ref_audios=[],
    )
    chat = _chat_result()
    messages = [
        _msg().model_copy(update={"session_id": f"private:{1000 + (index % 7)}", "message_id": f"p{index}"})
        for index in range(10000)
    ]
    verdicts = [should_voice_reply(config, message, chat) for message in messages]
    hits = sum(verdicts)
    assert abs(hits - len(messages) * probability) <= 150, f"10% 档命中 {hits}/10000 偏离带外"
    assert all(
        should_voice_reply(config, message, chat) is verdicts[index]
        for index, message in enumerate(messages[:500])
    ), "同一条消息重掷骰 ⇒ 双发面会出现「同一条一会儿有语音一会儿没有」"
