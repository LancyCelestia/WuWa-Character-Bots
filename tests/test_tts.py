"""守岸人语音合成能力（bot.tts）离线回归（2026-09-17 批）。

覆盖范围（全部离线，不打真实 GPT-SoVITS 服务）：

- 触发词边界判定：裸触发词不占路由、包含关系词不误触发；
- 参考音频解析：``路径|参考文本|语种`` 三段式与相对路径基准；
- 朗读前清洗：代码块/行内代码/链接/markdown 标记/列表前缀/句末截断；
- 结果缓存：键稳定性、命中复用、落盘文件消失即失效、LRU 封顶；
- 合成失败：降级文案映射，绝不抛异常；
- 能力层：总开关关闭 / 只发触发词 / 缺参考音频 / 成功四态；
- 对话自动配音：四道短路门与附加语音的成功路径；
- 路由层：``tts_match`` 关时返回 None，开时命中 TTS 路由。
"""

from __future__ import annotations

import asyncio
import random
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    DEFAULT_TRIGGER_WORDS,
    RefAudio,
    TtsParams,
    auto_reply_scope_allows,
    build_tts_capability,
    clean_for_speech,
    extract_tts_text,
    is_tts_command,
    maybe_attach_voice,
    parse_ref_audios,
    pick_ref_audio,
    should_voice_reply,
    synthesize,
)

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _params(**overrides: object) -> TtsParams:
    base = {
        "text_lang": "zh",
        "speed_factor": 0.85,
        "temperature": 0.9,
        "top_k": 15,
        "top_p": 1.0,
        "text_split_method": "cut5",
    }
    base.update(overrides)
    return TtsParams(**base)  # type: ignore[arg-type]


def _config(**overrides: object) -> SimpleNamespace:
    """最小配置对象：能力层只走 getattr，SimpleNamespace 足够。"""
    base = {
        "bot_tts_enabled": True,
        "bot_tts_api_url": "http://127.0.0.1:9880",
        "bot_tts_gptsovits_dir": "",
        "bot_tts_ref_audios": [],
        "bot_tts_trigger_words": [],
        "bot_tts_output_dir": "data/tts_output",
        "bot_tts_max_chars": 200,
        "bot_tts_timeout_seconds": 60.0,
        "bot_tts_speed_factor": 0.85,
        "bot_tts_temperature": 0.9,
        "bot_tts_top_k": 15,
        "bot_tts_top_p": 1.0,
        "bot_tts_text_lang": "zh",
        "bot_tts_text_split_method": "cut5",
        "bot_tts_cache_enabled": True,
        "bot_tts_auto_reply_enabled": False,
        "bot_tts_auto_reply_scope": "private",
        "bot_tts_auto_reply_max_chars": 120,
        "bot_tts_auto_reply_probability": 0.05,
        "bot_tts_auto_reply_always": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _msg(text: str, *, group_id: str | None = None) -> IncomingMessage:
    is_group = bool(group_id)
    return IncomingMessage(
        platform="qq",
        adapter="onebot11",
        bot_id="10000",
        session_id=f"group:{group_id}" if is_group else "private:20000",
        session_type=SessionType.GROUP if is_group else SessionType.PRIVATE,
        sender_id="20000",
        group_id=group_id,
        plain_text=text,
    )


def _ref_file(tmp_path: Path, name: str = "ref.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(b"RIFF....WAVEfmt ")
    return path


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """每条用例一份干净缓存，避免进程级 LRU 串味。"""
    monkeypatch.setattr(tts_mod, "_CACHE", OrderedDict())
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "")


# ---------------------------------------------------------------------------
# 触发词边界
# ---------------------------------------------------------------------------


def test_default_trigger_words_cover_chinese_english_pinyin() -> None:
    for word in (
        "语音合成", "说", "语音", "念", "朗读",
        "tts", "say", "shuo", "yuyin", "nian", "langdu",
    ):
        assert word in DEFAULT_TRIGGER_WORDS


def test_extract_tts_text_hits_and_strips_boundary() -> None:
    assert extract_tts_text("说 今天的潮汐很安静") == "今天的潮汐很安静"
    assert extract_tts_text("语音，你好") == "你好"
    assert extract_tts_text("tts:你好") == "你好"
    assert extract_tts_text("say hello") == "hello"
    assert extract_tts_text("念 一段话。") == "一段话。"


def test_help_alias_word_actually_routes() -> None:
    """help 主题别名里的词必须在路由面真能命中（双向门同源要求）。

    「语音合成」是帮助条目的别名，故它必须是一个真触发词——否则用户照着
    帮助去发，会坠回人格对话。
    """
    assert extract_tts_text("语音合成 你好") == "你好"
    assert extract_tts_text("语音合成：你好") == "你好"
    assert is_tts_command("语音合成 测试")


def test_bare_trigger_word_yields_empty_body() -> None:
    # 裸触发词不占路由，交回人格对话自然回应。
    for text in ("说", "语音", "念", "tts", "say", "语音合成", "  朗读  "):
        assert extract_tts_text(text) == ""
        assert not is_tts_command(text)


def test_containment_words_do_not_trigger() -> None:
    # 「说话」「念书」「语音消息」这类包含关系词不是命令。
    for text in ("说话", "念书", "语音消息", "说明一下", "sayonara"):
        assert not is_tts_command(text)


def test_custom_trigger_words_extend_defaults() -> None:
    assert is_tts_command("来段语音 你好", ("来段语音",))
    assert extract_tts_text("来段语音 你好", ("来段语音",)) == "你好"
    # 未命中的自定义词不误触发。
    assert not is_tts_command("讲个故事", ("来段语音",))


def test_longest_trigger_word_wins() -> None:
    # 「yuyin」与「语音」并存时，长词优先，避免短词截断。
    assert extract_tts_text("yuyin 你好") == "你好"


# ---------------------------------------------------------------------------
# 参考音频解析
# ---------------------------------------------------------------------------


def test_parse_ref_audios_three_segment_form(tmp_path: Path) -> None:
    audio = _ref_file(tmp_path)
    parsed = parse_ref_audios([f"{audio}|你好呀，我是守岸人。|zh"])
    assert len(parsed) == 1
    assert parsed[0].path == str(audio)
    assert parsed[0].text == "你好呀，我是守岸人。"
    assert parsed[0].lang == "zh"


def test_parse_ref_audios_defaults_text_and_lang(tmp_path: Path) -> None:
    audio = _ref_file(tmp_path)
    parsed = parse_ref_audios([str(audio)])
    assert parsed[0].text == ""
    assert parsed[0].lang == "zh"


def test_parse_ref_audios_relative_path_uses_base_dir(tmp_path: Path) -> None:
    base = tmp_path / "GPT-SoVITS"
    parsed = parse_ref_audios(["refs/a.wav|文本"], base_dir=str(base))
    assert Path(parsed[0].path) == base / "refs" / "a.wav"


def test_parse_ref_audios_skips_blank_and_pathless(tmp_path: Path) -> None:
    audio = _ref_file(tmp_path)
    parsed = parse_ref_audios(["", "   ", "|只有文本", str(audio)])
    assert len(parsed) == 1
    assert parsed[0].path == str(audio)


def test_parse_ref_audios_empty_input() -> None:
    assert parse_ref_audios([]) == []
    assert parse_ref_audios(None) == []


def test_pick_ref_audio_only_returns_existing_file(tmp_path: Path) -> None:
    good = _ref_file(tmp_path, "good.wav")
    missing = tmp_path / "missing.wav"
    picked = pick_ref_audio([f"{missing}|x", f"{good}|y"], rng=random.Random(0))
    assert picked is not None
    assert picked.path == str(good)


def test_pick_ref_audio_none_when_all_missing(tmp_path: Path) -> None:
    assert pick_ref_audio([str(tmp_path / "nope.wav")]) is None
    assert pick_ref_audio([]) is None


# ---------------------------------------------------------------------------
# 朗读前清洗
# ---------------------------------------------------------------------------


def test_clean_for_speech_strips_code_fence_and_inline_code() -> None:
    cleaned = clean_for_speech("看这段 ```print('hi')``` 和 `x = 1` 就行")
    assert "print" not in cleaned
    assert "x = 1" not in cleaned
    assert "看这段" in cleaned
    assert "就行" in cleaned


def test_clean_for_speech_strips_url() -> None:
    cleaned = clean_for_speech("详情见 https://example.com/a?b=1 这里")
    assert "http" not in cleaned
    assert "example.com" not in cleaned


def test_clean_for_speech_strips_markdown_marks_and_list_prefix() -> None:
    cleaned = clean_for_speech("# 标题\n- 第一条\n- 第二条")
    assert "#" not in cleaned
    assert "- " not in cleaned
    assert "标题" in cleaned
    assert "第一条" in cleaned


def test_clean_for_speech_collapses_blank_lines_to_single_line() -> None:
    assert clean_for_speech("第一行\n\n\n第二行") == "第一行 第二行"


def test_clean_for_speech_truncates_at_sentence_end() -> None:
    cleaned = clean_for_speech("第一句。第二句。第三句。", max_chars=6)
    assert cleaned == "第一句。"


def test_clean_for_speech_empty_and_whitespace() -> None:
    assert clean_for_speech("") == ""
    assert clean_for_speech("   \n  ") == ""


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------


def test_cache_key_is_stable_and_param_sensitive(tmp_path: Path) -> None:
    ref = RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    base = tts_mod._cache_key("正文", ref, _params())
    assert base == tts_mod._cache_key("正文", ref, _params())
    assert base != tts_mod._cache_key("正文", ref, _params(temperature=1.1))
    assert base != tts_mod._cache_key("正文", ref, _params(speed_factor=1.0))
    assert base != tts_mod._cache_key("换一句", ref, _params())


def test_cache_key_ref_text_participates(tmp_path: Path) -> None:
    audio = _ref_file(tmp_path)
    left = tts_mod._cache_key("正文", RefAudio(path=str(audio), text="甲"), _params())
    right = tts_mod._cache_key("正文", RefAudio(path=str(audio), text="乙"), _params())
    assert left != right


def test_cache_lookup_drops_entry_when_file_vanishes(tmp_path: Path) -> None:
    """索引里有记录、磁盘上文件已不在 → 必须自清并返回 None。"""
    target = _ref_file(tmp_path, "out.wav")
    tts_mod._store_cache("k1", target)
    assert tts_mod._lookup_cache("k1") == target
    # 模拟落盘文件被清理：把索引指向一个不存在的路径。
    # 这里不真删文件——宿主的批量删除守卫会在整轮删除数达阈值时中断进程，
    # 让用例假红；而本用例要验的是「文件不在就失效」这一分支本身。
    tts_mod._CACHE["k1"] = (tmp_path / "gone.wav", 0.0)
    assert tts_mod._lookup_cache("k1") is None
    assert "k1" not in tts_mod._CACHE


def test_cache_lru_cap_evicts_oldest(tmp_path: Path) -> None:
    target = _ref_file(tmp_path, "out.wav")
    for index in range(tts_mod._CACHE_LRU_CAP + 3):
        tts_mod._store_cache(f"k{index}", target)
    assert len(tts_mod._CACHE) == tts_mod._CACHE_LRU_CAP
    assert "k0" not in tts_mod._CACHE
    assert f"k{tts_mod._CACHE_LRU_CAP + 2}" in tts_mod._CACHE


# ---------------------------------------------------------------------------
# 合成
# ---------------------------------------------------------------------------


def test_synthesize_writes_file_then_hits_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def _fake_request(**_kwargs: object) -> bytes:
        calls.append("hit")
        return b"RIFFfake"

    monkeypatch.setattr(tts_mod, "_request_tts", _fake_request)
    ref = RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    out = tmp_path / "out"

    first, reason = synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=_params(),
        output_dir=out,
    )
    assert first is not None
    assert reason == ""
    assert first.is_file()
    assert first.read_bytes() == b"RIFFfake"

    second, reason2 = synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=_params(),
        output_dir=out,
    )
    assert second == first
    assert reason2 == ""
    assert calls == ["hit"], "第二次应命中缓存，不再打服务"


def test_synthesize_cache_disabled_always_calls_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def _fake_request(**_kwargs: object) -> bytes:
        calls.append("hit")
        return b"RIFFfake"

    monkeypatch.setattr(tts_mod, "_request_tts", _fake_request)
    ref = RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    for _ in range(2):
        path, _reason = synthesize(
            api_url="http://127.0.0.1:9880",
            text="正文",
            ref=ref,
            params=_params(),
            output_dir=tmp_path / "out",
            cache_enabled=False,
        )
        assert path is not None
    assert calls == ["hit", "hit"]


def test_synthesize_returns_reason_on_service_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tts_mod, "_request_tts", lambda **_kwargs: None)
    monkeypatch.setattr(tts_mod, "_last_failure_reason", "服务不可达：ConnectError")
    ref = RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    path, reason = synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=_params(),
        output_dir=tmp_path / "out",
    )
    assert path is None
    assert "不可达" in reason


def test_synthesize_reports_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tts_mod, "_request_tts", lambda **_kwargs: b"RIFFfake")
    ref = RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    blocked = tmp_path / "blocked"
    blocked.write_text("我是文件不是目录", encoding="utf-8")
    path, reason = synthesize(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=ref,
        params=_params(),
        output_dir=blocked / "child",
    )
    assert path is None
    assert "落盘失败" in reason


def test_request_payload_matches_api_v2_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """请求体键名必须与 api_v2.py 的 /tts 参数一致，否则服务端 422。"""
    captured: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200
        content = b"RIFFfake"

        @staticmethod
        def json() -> dict[str, object]:
            return {}

    class _FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, json: dict[str, object]) -> _FakeResponse:
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    fake_httpx = SimpleNamespace(Client=_FakeClient)
    monkeypatch.setitem(__import__("sys").modules, "httpx", fake_httpx)

    ref = RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")
    payload_bytes = tts_mod._request_tts(
        api_url="http://127.0.0.1:9880/",
        text="正文",
        ref=ref,
        params=_params(),
        timeout_seconds=5.0,
    )
    assert payload_bytes == b"RIFFfake"
    assert captured["url"] == "http://127.0.0.1:9880/tts"
    body = captured["json"]
    assert isinstance(body, dict)
    for key in (
        "text",
        "text_lang",
        "ref_audio_path",
        "prompt_text",
        "prompt_lang",
        "top_k",
        "top_p",
        "temperature",
        "text_split_method",
        "speed_factor",
        "media_type",
        "streaming_mode",
    ):
        assert key in body, f"请求体缺 api_v2.py 参数：{key}"
    assert body["ref_audio_path"] == ref.path
    assert body["prompt_text"] == "你好"
    assert body["media_type"] == "wav"


def _install_fake_httpx(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int,
    content: bytes,
    json_payload: object = None,
    json_raises: bool = False,
) -> None:
    """把 ``sys.modules["httpx"]`` 换成只回一个固定响应的假模块。"""

    class _FakeResponse:
        def __init__(self) -> None:
            self.status_code = status_code
            self.content = content
            self.text = content.decode("utf-8", errors="replace")

        def json(self) -> object:
            if json_raises:
                raise ValueError("not json")
            return json_payload

    class _FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, _url: str, json: dict[str, object]) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setitem(
        __import__("sys").modules, "httpx", SimpleNamespace(Client=_FakeClient)
    )


def test_request_tts_error_body_prefers_exception_over_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归锁：api_v2.py 把真原因放 ``Exception``、``message`` 只是固定摘要。

    此前实现优先读 ``message``，导致「参考音频 3~10 秒越界」这类可读原因被吞成
    "tts failed"，``_degrade`` 的「参考音频」分支永远命不中——用户只会看到
    最泛化的那句降级文案。本用例同时锁住「解析顺序」与「端到端降级映射」。
    """
    reason = "参考音频在3~10秒范围外，请更换！"
    _install_fake_httpx(
        monkeypatch,
        status_code=400,
        content=b'{"message": "tts failed", "Exception": "..."}',
        json_payload={"message": "tts failed", "Exception": reason},
    )
    out = tts_mod._request_tts(
        api_url="http://127.0.0.1:9880",
        text="正文",
        ref=RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh"),
        params=_params(),
        timeout_seconds=5.0,
    )
    assert out is None
    assert "3~10秒" in tts_mod._last_failure_reason
    assert "tts failed" not in tts_mod._last_failure_reason
    assert "参考音频" in tts_mod._degrade(tts_mod._last_failure_reason)


def test_request_tts_error_body_tolerates_non_json_and_bare_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """错误体非 JSON / 是裸 JSON 字符串时都不能炸，且要留下可读线索。"""
    ref = RefAudio(path=str(_ref_file(tmp_path)), text="你好", lang="zh")

    _install_fake_httpx(
        monkeypatch, status_code=502, content=b"<html>Bad Gateway</html>", json_raises=True
    )
    assert (
        tts_mod._request_tts(
            api_url="http://127.0.0.1:9880",
            text="正文",
            ref=ref,
            params=_params(),
            timeout_seconds=5.0,
        )
        is None
    )
    assert "502" in tts_mod._last_failure_reason
    assert "Bad Gateway" in tts_mod._last_failure_reason

    _install_fake_httpx(
        monkeypatch, status_code=500, content=b'"boom"', json_payload="boom"
    )
    assert (
        tts_mod._request_tts(
            api_url="http://127.0.0.1:9880",
            text="正文",
            ref=ref,
            params=_params(),
            timeout_seconds=5.0,
        )
        is None
    )
    assert "boom" in tts_mod._last_failure_reason


def test_degrade_copy_maps_reason_to_shorekeeper_voice() -> None:
    assert "语音服务" in tts_mod._degrade("服务不可达：ConnectError")
    assert "参考音频" in tts_mod._degrade("参考音频时长需 3~10秒")
    fallback = tts_mod._degrade("服务返回 500：internal")
    assert fallback and "服务返回" not in fallback


# ---------------------------------------------------------------------------
# 能力层四态
# ---------------------------------------------------------------------------


def test_capability_disabled_is_silent_audit(tmp_path: Path) -> None:
    capability = build_tts_capability(_config(bot_tts_enabled=False))
    result = capability(_msg("说 你好"), None)
    assert result.capability_id == "bot.tts"
    assert result.send_policy == SendPolicy.SILENT_AUDIT
    assert "skip_disabled" in result.audit_tags
    assert not result.audio


def test_capability_bare_trigger_gives_guidance() -> None:
    capability = build_tts_capability(_config())
    result = capability(_msg("语音"), None)
    assert "missing_text" in result.audit_tags
    assert "说" in result.body
    assert not result.audio


def test_capability_without_ref_audio_hints_config() -> None:
    capability = build_tts_capability(_config(bot_tts_ref_audios=[]))
    result = capability(_msg("说 你好"), None)
    assert "no_ref_audio" in result.audit_tags
    assert "BOT_TTS_REF_AUDIOS" in result.body
    assert not result.audio


def test_capability_missing_ref_file_hints_paths(tmp_path: Path) -> None:
    capability = build_tts_capability(
        _config(bot_tts_ref_audios=[str(tmp_path / "gone.wav")])
    )
    result = capability(_msg("说 你好"), None)
    assert "no_ref_audio" in result.audit_tags
    assert "找不到" in result.body


def test_capability_success_emits_audio_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = _ref_file(tmp_path, "synth.wav")
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kwargs: (wav, ""))
    capability = build_tts_capability(
        _config(
            bot_tts_ref_audios=[f"{_ref_file(tmp_path, 'ref.wav')}|你好|zh"],
            bot_tts_output_dir=str(tmp_path / "out"),
        )
    )
    result = capability(_msg("说 今天的潮汐很安静"), None)
    # `review_text` 是给中央审核看的（媒体能力 title/body 必须留空，否则 renderer
    # 的兜底链会把朗读文本再发成一条文字消息）；`record` 段只把 `file` 交给平台。
    assert result.audio == [{"file": str(wav), "review_text": "今天的潮汐很安静"}]
    # 与 randpic 同口径：只发媒体本体，避免 renderer 兜底链把标题当文案发出。
    assert result.title == ""
    assert result.body == ""
    assert "sent" in result.audit_tags


def test_capability_failure_degrades_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(**_kwargs: object) -> tuple[None, str]:
        return None, "服务不可达：ConnectError"

    monkeypatch.setattr(tts_mod, "synthesize", _boom)
    capability = build_tts_capability(
        _config(bot_tts_ref_audios=[f"{_ref_file(tmp_path)}|你好|zh"])
    )
    result = capability(_msg("说 你好"), None)
    assert "synthesize_failed" in result.audit_tags
    assert not result.audio
    assert result.body, "失败必须有可读降级文案"


# ---------------------------------------------------------------------------
# 对话自动配音
# ---------------------------------------------------------------------------


def _chat_result(body: str = "今天的潮汐很安静。") -> CapabilityResult:
    return CapabilityResult(
        request_id="req-1",
        capability_id="bot.chat",
        kind="text",
        body=body,
    )


def test_auto_reply_scope_allows_matrix() -> None:
    private_msg = _msg("在吗")
    group_msg = _msg("在吗", group_id="123456")
    assert auto_reply_scope_allows(_config(bot_tts_auto_reply_scope="private"), private_msg)
    assert not auto_reply_scope_allows(_config(bot_tts_auto_reply_scope="private"), group_msg)
    assert auto_reply_scope_allows(_config(bot_tts_auto_reply_scope="group"), group_msg)
    assert not auto_reply_scope_allows(_config(bot_tts_auto_reply_scope="group"), private_msg)
    assert auto_reply_scope_allows(_config(bot_tts_auto_reply_scope="all"), group_msg)
    assert auto_reply_scope_allows(_config(bot_tts_auto_reply_scope="all"), private_msg)


def test_maybe_attach_voice_short_circuits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tts_mod, "synthesize", lambda **_kwargs: pytest.fail("不该触发合成")
    )
    ref = [f"{_ref_file(tmp_path)}|你好|zh"]
    original = _chat_result()

    # 总开关关。
    assert maybe_attach_voice(
        _msg("在吗"), original, config=_config(bot_tts_enabled=False, bot_tts_ref_audios=ref)
    ) is original
    # 自动配音开关关。
    assert maybe_attach_voice(
        _msg("在吗"),
        original,
        config=_config(bot_tts_auto_reply_enabled=False, bot_tts_ref_audios=ref),
    ) is original
    # 已有音频。
    with_audio = original.model_copy(update={"audio": [{"file": "x.wav"}]})
    assert maybe_attach_voice(
        _msg("在吗"),
        with_audio,
        config=_config(bot_tts_auto_reply_enabled=True, bot_tts_ref_audios=ref),
    ) is with_audio
    # 非 chat 能力。
    other = CapabilityResult(request_id="req-2", capability_id="bot.market", kind="text")
    assert maybe_attach_voice(
        _msg("在吗"),
        other,
        config=_config(bot_tts_auto_reply_enabled=True, bot_tts_ref_audios=ref),
    ) is other
    # 群聊 + 仅私聊配音。
    assert maybe_attach_voice(
        _msg("在吗", group_id="123456"),
        original,
        config=_config(bot_tts_auto_reply_enabled=True, bot_tts_ref_audios=ref),
    ) is original


def test_maybe_attach_voice_attaches_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = _ref_file(tmp_path, "synth.wav")
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kwargs: (wav, ""))
    original = _chat_result()
    patched = maybe_attach_voice(
        _msg("在吗"),
        original,
        config=_config(
            bot_tts_auto_reply_enabled=True,
            bot_tts_auto_reply_always=True,
            bot_tts_ref_audios=[f"{_ref_file(tmp_path, 'ref.wav')}|你好|zh"],
            bot_tts_output_dir=str(tmp_path / "out"),
        ),
    )
    assert patched is not original
    assert patched.audio == [{"file": str(wav), "review_text": original.body}]
    assert "auto_reply" in patched.audit_tags
    assert not original.audio, "原结果不应被就地修改"


def test_maybe_attach_voice_survives_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kwargs: (None, "服务不可达：ConnectError"))
    original = _chat_result()
    assert maybe_attach_voice(
        _msg("在吗"),
        original,
        config=_config(
            bot_tts_auto_reply_enabled=True,
            bot_tts_auto_reply_always=True,
            bot_tts_ref_audios=[f"{_ref_file(tmp_path)}|你好|zh"],
        ),
    ) is original


def test_maybe_attach_voice_swallows_unexpected_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(**_kwargs: object) -> tuple[None, str]:
        raise RuntimeError("boom")

    monkeypatch.setattr(tts_mod, "synthesize", _boom)
    original = _chat_result()
    # 参考音频就位 + always 旁路概率门，保证真的走到 synthesize：
    # 该阶段的意外异常同样必须被吞掉（fail-open 的兜底分支）。
    config = _config(
        bot_tts_auto_reply_enabled=True,
        bot_tts_auto_reply_always=True,
        bot_tts_ref_audios=[f"{_ref_file(tmp_path)}|你好|zh"],
    )
    assert maybe_attach_voice(_msg("在吗"), original, config=config) is original


def test_maybe_attach_voice_skips_empty_speech() -> None:
    original = _chat_result(body="```code```")
    assert maybe_attach_voice(
        _msg("在吗"),
        original,
        config=_config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_always=True),
    ) is original


# ---------------------------------------------------------------------------
# 概率门（2026-09-19 批）：确定性哈希，同一条消息结果恒定
# ---------------------------------------------------------------------------


def test_should_voice_reply_gates_before_probability() -> None:
    """概率门之前的三道门仍必须短路——always 也不能绕过它们。"""
    always = _config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_always=True)
    chat = _chat_result()
    assert not should_voice_reply(
        _config(bot_tts_enabled=False, bot_tts_auto_reply_always=True), _msg("在吗"), chat
    )
    assert not should_voice_reply(
        _config(bot_tts_auto_reply_enabled=False, bot_tts_auto_reply_always=True),
        _msg("在吗"),
        chat,
    )
    assert not should_voice_reply(
        always, _msg("在吗"), chat.model_copy(update={"audio": [{"file": "x.wav"}]})
    )
    assert not should_voice_reply(
        always,
        _msg("在吗"),
        CapabilityResult(request_id="req-9", capability_id="bot.market", kind="text"),
    )
    assert not should_voice_reply(
        always, _msg("在吗", group_id="123456"), chat
    ), "群聊 + scope=private 必须不配音"


def test_should_voice_reply_probability_bounds() -> None:
    """概率边界：0=永不配音、1.0=全量、always=跳过概率门。"""
    chat = _chat_result()
    never = _config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_probability=0.0)
    always_by_prob = _config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_probability=1.0)
    for _ in range(50):
        msg = _msg("在吗")
        assert not should_voice_reply(never, msg, chat)
        assert should_voice_reply(always_by_prob, msg, chat)
    # always 旁路必须**压过**概率门：即便 probability=0.0 也要配音。
    # 这条断言由变异测试补出（2026-09-19）——此前 always 的旁路行为无人直接断言，
    # 把它改成失效后全套测试仍全绿（盲区）。
    bypass = _config(
        bot_tts_auto_reply_enabled=True,
        bot_tts_auto_reply_probability=0.0,
        bot_tts_auto_reply_always=True,
    )
    for _ in range(20):
        assert should_voice_reply(bypass, _msg("在吗"), chat), "always 必须跳过概率门"
    # 非法值（None / 非数字字符串）按 0 处理，绝不误配音。
    broken = _config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_probability=None)
    assert not should_voice_reply(broken, _msg("在吗"), chat)
    weird = _config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_probability="abc")
    assert not should_voice_reply(weird, _msg("在吗"), chat)


def test_should_voice_reply_is_deterministic_and_sparse_by_default() -> None:
    """默认 5%：同一消息结果恒定，且绝大多数消息不配音（防「默认全开」回归）。

    确定性是硬要求——若改用 ``random``，同一条消息两次调用会给出不同答案，
    下游测试与审计都不可复现。
    """
    config = _config(bot_tts_auto_reply_enabled=True)
    chat = _chat_result()
    voiced = 0
    total = 400
    for i in range(total):
        msg = _msg("在吗").model_copy(update={"message_id": f"m{i}"})
        first = should_voice_reply(config, msg, chat)
        assert should_voice_reply(config, msg, chat) is first, "同一消息必须结果恒定"
        voiced += int(first)
    # 400 条按 5% 期望 20 条；只锁「既非全开也非全关」这个粗边界。
    assert 0 < voiced < total * 0.25, f"概率门异常：{voiced}/{total} 被配音"


def test_maybe_attach_voice_probability_gate_skips_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """概率门未命中时绝不调 synthesize——这是省线程/省推理的关键路径。"""
    monkeypatch.setattr(
        tts_mod, "synthesize", lambda **_kwargs: pytest.fail("概率未命中却触发了合成")
    )
    original = _chat_result()
    config = _config(
        bot_tts_auto_reply_enabled=True,
        bot_tts_auto_reply_probability=0.0,
        bot_tts_ref_audios=[f"{_ref_file(tmp_path)}|你好|zh"],
    )
    assert maybe_attach_voice(_msg("在吗"), original, config=config) is original


# ---------------------------------------------------------------------------
# 根 __init__ 的谓词短路（2026-09-19 第二批：省线程调度，行为不变）
# ---------------------------------------------------------------------------


def _spy_to_thread(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """把根包的 ``asyncio.to_thread`` 换成记录调用的直通版本。

    ``_attach_voice_reply`` 用的是模块级 ``asyncio``，故直接替换该模块属性即可
    观测「是否真的投递了线程池」。
    """
    import plugins.bot_unified_runtime as root

    calls: list[str] = []

    async def _fake_to_thread(fn, *args, **kwargs):
        calls.append("dispatched")
        return fn(*args, **kwargs)

    monkeypatch.setattr(root.asyncio, "to_thread", _fake_to_thread)
    return calls


def _voice_wrapper(
    config: SimpleNamespace, result: CapabilityResult | None = None
):
    """包一层 ``_attach_voice_reply``；``result`` 给定时每次返回同一对象，
    便于与直调 ``maybe_attach_voice`` 做逐字段比对（否则 debug_id 会不同）。
    """
    import plugins.bot_unified_runtime as root

    async def _inner(_message, _decision):
        return result if result is not None else _chat_result()

    return root._attach_voice_reply(_inner, config=config)


def test_attach_voice_reply_skips_thread_when_predicate_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """谓词判否时**不得**投递线程池——第二批的全部收益就在这一次省掉的调度。

    概率门落空（默认 5%）是绝大多数消息的路径；此前只挡两个开关，意味着
    95% 的消息仍要白付一次 ``asyncio.to_thread`` 投递。
    """
    calls = _spy_to_thread(monkeypatch)
    wrapper = _voice_wrapper(
        _config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_probability=0.0)
    )
    result = asyncio.run(wrapper(_msg("在吗"), None))
    assert result.capability_id == "bot.chat"
    assert not result.audio
    assert calls == [], "概率门未命中却投递了线程池"


def test_attach_voice_reply_skips_thread_when_switch_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """总开关/自动配音开关关闭时同样不投递（原行为的等价保留）。"""
    calls = _spy_to_thread(monkeypatch)
    for config in (
        _config(bot_tts_enabled=False),
        _config(bot_tts_auto_reply_enabled=False),
    ):
        result = asyncio.run(_voice_wrapper(config)(_msg("在吗"), None))
        assert result.capability_id == "bot.chat"
    assert calls == [], "开关关闭却投递了线程池"


def test_attach_voice_reply_dispatches_thread_when_predicate_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """谓词判真时必须走线程池，且结果与直接调用 ``maybe_attach_voice`` 一致。"""
    calls = _spy_to_thread(monkeypatch)
    # always 跳过概率门 → 谓词为真；不给参考音频 → 内部 fail-open 返回原结果。
    wrapper = _voice_wrapper(
        _config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_always=True)
    )
    result = asyncio.run(wrapper(_msg("在吗"), None))
    assert calls == ["dispatched"], "谓词判真却没有投递线程池"
    assert result.capability_id == "bot.chat"
    assert not result.audio, "无参考音频时必须原样返回，不得抛异常"


def test_attach_voice_reply_matches_maybe_attach_voice_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """短路版与直调版出站结果必须逐字段一致（证明「只是省调度」）。"""
    monkeypatch.setattr(tts_mod, "synthesize", lambda **_kwargs: pytest.fail("不应合成"))
    message = _msg("在吗")
    config = _config(bot_tts_auto_reply_enabled=True, bot_tts_auto_reply_probability=0.0)
    shared = _chat_result()
    direct = maybe_attach_voice(message, shared, config=config)
    wrapped = asyncio.run(_voice_wrapper(config, shared)(message, None))
    assert wrapped.model_dump() == direct.model_dump()


# ---------------------------------------------------------------------------
# 路由层
# ---------------------------------------------------------------------------


def _tts_rule():
    """从路由规则表取出 bot.tts 规则（matcher 是 build_route_rules 内的闭包）。"""
    from plugins.bot_unified_runtime.runtime.base_router import build_route_rules

    for rule in build_route_rules():
        if rule.capability_id == "bot.tts":
            assert rule.matcher is not None, "bot.tts 规则缺 matcher"
            return rule
    raise AssertionError("路由规则表里没有 bot.tts")


def test_tts_rule_registered_with_expected_shape() -> None:
    rule = _tts_rule()
    assert rule.kind.value == "tts"
    assert rule.priority == 41
    assert "base_route:tts" in rule.tags


def test_tts_match_disabled_returns_none() -> None:
    rule = _tts_rule()
    assert rule.matcher("说 你好", _config(bot_tts_enabled=False), None) is None


def test_tts_match_hits_route_when_enabled() -> None:
    decision = _tts_rule().matcher("说 你好", _config(), None)
    assert decision is not None
    assert decision.capability_id == "bot.tts"
    assert decision.kind.value == "tts"
    assert decision.priority == 41


def test_tts_match_ignores_bare_trigger() -> None:
    assert _tts_rule().matcher("说", _config(), None) is None
