"""S-VSPLIT · 自动配音长文拆条（2026-09-23 批）离线回归。

覆盖两层：

- **纯函数层** ``tts.split_speech_chunks``：空文本/不拆语义（cap<=0 或未超限=
  单块、与拆条引入前逐字节同构）/句末贪心装填/超限长句退切逗号/无标点硬切/
  拉丁词边不粘连/内容守恒（拼接不吞字）。
- **enricher 层**（``domains/media/voice_enricher.py``）：多块全成=音频部件
  逐块并入同一条回复 + ``split=a/b`` 标签；**首块即败**=既有整幅失败面逐字保留
  （FAILED→issue、NOT_CONFIGURED→无参考 issue）；**半程败**=已合成块照发、
  不挂 issue、``split=a/b`` 如实记缺角；拆键=0 单块路径与拆条引入前同构
  （恰一次中央 invoke、无 split 标签）。

全离线零网络：``should_voice_reply``/``resolve_speech_text``/``synthesize``
一律 monkeypatch（与 tests/test_voice_enricher_central_dispatch.py 同构夹具，
合成经 media.tts.autodub 中央 handler 真路落回 seam）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plugins.bot_unified_runtime.contracts import SendPolicy, SessionType
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
)
from plugins.bot_unified_runtime.domains.media import voice_enricher as ve
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    split_speech_chunks,
)
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

# ---------------------------------------------------------------------------
# 纯函数：split_speech_chunks
# ---------------------------------------------------------------------------


def test_split_empty_returns_no_chunks() -> None:
    assert split_speech_chunks("", 10) == []
    assert split_speech_chunks("   \t ", 10) == []


def test_split_cap_nonpositive_or_under_limit_is_single_stripped_chunk() -> None:
    # cap<=0（缺省 0=不拆）或未超限 ⇒ 原样单块（仅 strip），逐字节同构语义。
    assert split_speech_chunks("  潮汐很安静。  ", 0) == ["潮汐很安静。"]
    assert split_speech_chunks("潮汐很安静。", -5) == ["潮汐很安静。"]
    assert split_speech_chunks("潮汐很安静。", 6) == ["潮汐很安静。"]


def test_split_greedy_sentence_packing() -> None:
    s1 = "一" * 30 + "。"  # 31
    s2 = "二" * 40 + "。"  # 41
    s3 = "三" * 25 + "。"  # 26
    text = s1 + s2 + s3
    assert split_speech_chunks(text, 80) == [s1 + s2, s3]
    # 每块都不超限，且拼接守恒（CJK 直连不补空格、不吞字）。
    chunks = split_speech_chunks(text, 80)
    assert all(len(c) <= 80 for c in chunks)
    assert "".join(chunks) == text


def test_split_overlong_sentence_falls_back_to_clause_break() -> None:
    # 「、」是逗号类次切点：从 cap 往回**先命中的那个**顿号落刀（切点在标点之后，
    # 块尾保留标点、不粘下一块）；剩余纯假名长串无切点则按 cap 硬切兜底。
    piece = "あ" * 10 + "、" + "い" * 30
    chunks = split_speech_chunks(piece, 25)
    assert all(len(c) <= 25 for c in chunks)
    assert chunks == ["あ" * 10 + "、", "い" * 25, "い" * 5]


def test_split_no_punctuation_hard_cut() -> None:
    text = "字" * 55
    assert split_speech_chunks(text, 20) == ["字" * 20, "字" * 20, "字" * 15]


def test_split_sentence_end_splits_and_hard_cut_atoms_keep_word_space() -> None:
    # 句末集是 _SENTENCE_END（ASCII「.」不在内，「!」在）：「!」后为切点，
    # 块尾「!」非 alnum ⇒ 两块不粘连、直接分块。
    assert split_speech_chunks("Hello world!Foo bar!", 15) == ["Hello world!", "Foo bar!"]
    # 次切点落在空白处：两原子两端都是字母 ⇒ _join_speech_atom 补一个空格拼回
    # 一块（原连续空白被压缩成单空格；纯硬切串的首原子恒等 cap 长、永不回拼）。
    assert split_speech_chunks("abcd   efgh", 9) == ["abcd efgh"]


# ---------------------------------------------------------------------------
# enricher 层夹具（同 test_voice_enricher_central_dispatch 形状）
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
        body="占位正文",
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["chat"],
    )


def _config(tmp_path: Path, *, split_cap: int) -> SimpleNamespace:
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
        bot_tts_auto_reply_max_chars=0,
        bot_tts_auto_reply_split_max_chars=split_cap,
        bot_tts_auto_reply_probability=1.0,
        bot_tts_auto_reply_always=True,
    )


_LONG_SPEECH = "第一句话的内容。" + "第二句话的内容。" + "第三句话的内容。"  # 8×3=24 字
_CHUNKS_3 = ["第一句话的内容。", "第二句话的内容。", "第三句话的内容。"]  # split_cap=9


@pytest.fixture()
def armed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """门链全通、合成分块落 seam、可编排失败块的 enricher 工厂。

    返回 ``make(split_cap, fail_at=...)``：``fail_at`` 为 1-based 块序集合，
    命中块令合成原语返回 ``(None, "engine unreachable: refused")``（→ 中央
    FAILED→``_failure_issue`` 路）。
    """
    (tmp_path / "ref.wav").write_bytes(b"RIFFref")
    wav = tmp_path / "fake.wav"
    wav.write_bytes(b"RIFFfake")

    def make(split_cap: int, *, fail_at: frozenset[int] = frozenset()):
        synth_calls: list[str] = []
        counter = {"n": 0}

        def fake_synthesize(**kwargs: object):
            counter["n"] += 1
            synth_calls.append(str(kwargs.get("text")))
            if counter["n"] in fail_at:
                return None, "engine unreachable: refused"
            return wav, ""

        monkeypatch.setattr(ve, "should_voice_reply", lambda *a, **k: True)
        # S91 收编：取文口在中央第三形真身 result_transform 里跑（不再是 hook 内联），
        # 故替身钉 rt；合成原语 dub 闭包仍从 ve 命名空间取 synthesize（逐字节等价注入）。
        import plugins.bot_unified_runtime.domains.media.tts.result_transform as rt

        monkeypatch.setattr(
            rt, "resolve_speech_text", lambda *a, **k: (_LONG_SPEECH, "")
        )
        monkeypatch.setattr(ve, "synthesize", fake_synthesize)

        invoker_calls: list[str] = []
        real_invoke = cp.CapabilityInvoker.invoke

        def spy_invoke(self: object, request: object, *a: object, **k: object):
            invoker_calls.append(getattr(request, "capability_id", "<unknown>"))
            return real_invoke(self, request, *a, **k)  # type: ignore[arg-type]

        monkeypatch.setattr(cp.CapabilityInvoker, "invoke", spy_invoke)

        enricher = ve.build_voice_enricher(_config(tmp_path, split_cap=split_cap))
        return enricher, synth_calls, invoker_calls

    return make


def test_multi_chunk_all_ok_merges_parts_with_split_tag(armed) -> None:
    enricher, synth_calls, invoker_calls = armed(9)

    enriched = enricher(_message(), _decision(), _result())

    assert synth_calls == _CHUNKS_3, "三块应逐块过中央、文本与切分一致"
    # S91 收编：hook 先派一次中央第三形（变换），其内产出步 dub 再逐块派 autodub ⇒
    # 恰 [transform] + [autodub]×块数；任一腿旁路或换序都会打红本锁。
    assert invoker_calls == ["media.tts.autodub_transform"] + ["media.tts.autodub"] * 3, (
        invoker_calls
    )
    assert enriched.audio is not None and len(enriched.audio) == 3
    assert [part["review_text"] for part in enriched.audio] == _CHUNKS_3
    # 真身 result_transform 只在有缺角时记 split=a/b（全成不留缺角标），与旧内联
    # "多块必标 split=N/N" 是一处刻意语义差（缺角才是异常信号，全成不刷标签）。
    assert not any(tag.startswith("split=") for tag in enriched.audit_tags)
    assert "tts" in enriched.audit_tags and "auto_reply" in enriched.audit_tags
    assert enriched.operational_issue is None


def test_first_chunk_failure_keeps_whole_failure_surface(armed) -> None:
    enricher, synth_calls, _ = armed(9, fail_at=frozenset({1}))

    enriched = enricher(_message(), _decision(), _result())

    assert synth_calls == [_CHUNKS_3[0]], "首块即败：不再合成后续块"
    assert not enriched.audio
    issue = enriched.operational_issue
    assert issue is not None, "首块失败=整幅失败面，issue 语义逐字保留"


def test_partial_failure_ships_done_chunks_without_issue(armed) -> None:
    enricher, synth_calls, _ = armed(9, fail_at=frozenset({2}))

    enriched = enricher(_message(), _decision(), _result())

    assert synth_calls == _CHUNKS_3[:2], "第 2 块败即停手，第 3 块不再合成"
    assert enriched.audio is not None and len(enriched.audio) == 1
    assert enriched.audio[0]["review_text"] == _CHUNKS_3[0]
    assert "split=1/3" in enriched.audit_tags
    assert enriched.operational_issue is None, "半程故障不挂 issue（防刷屏，增益语义）"


def test_split_cap_zero_is_single_invoke_without_split_tag(armed) -> None:
    enricher, synth_calls, invoker_calls = armed(0)

    enriched = enricher(_message(), _decision(), _result())

    # 拆键 0（缺省）：单块路径——hook 派一次中央第三形、其内 dub 派一次 autodub ⇒
    # [transform, autodub]；音频一段、全成无 split 缺角标（真身语义）。
    assert synth_calls == [_LONG_SPEECH]
    assert invoker_calls == ["media.tts.autodub_transform", "media.tts.autodub"]
    assert enriched.audio is not None and len(enriched.audio) == 1
    assert not any(tag.startswith("split=") for tag in enriched.audit_tags)
    assert enriched.operational_issue is None
