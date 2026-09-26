"""原生音频/视频进主聊天模型（仅被声明支持的模型走原生，其余保持转译）。

背景（2026-09-23 实测）：经 axonhub 向 gemini-3.8-flash 发 `input_audio`/`video_url`
内容部件可被真实理解（语音逐字转写正确、视频画面描述准确）；而 grok-4.6 对音频
返回 422、**对视频返回 200 却答"没有附带任何视频"**——即 HTTP 成功不代表模型真的
看见了内容。故能力门必须是声明式白名单（tags），缺省不放行。
"""

from __future__ import annotations

import ast
import base64
import copy
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_capability,
    build_direct_vision_messages,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    NullCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
    ModelRouter,
    ModelSpec,
    declared_native_media_kinds,
    native_media_kinds_in_payload,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
    StaticLLMProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_SOURCE_MANUAL,
    INTIMATE_SOURCE_MASTER_LOVE,
    SHARED_CONTENT_ROUTE_ENGINE,
    ContentRouteEngine,
    build_router_cb,
    member_session_key,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    FORM_BARE,
    FORM_UNDERSCORE,
    build_session_key,
    parse_session_key,
    private_session_key,
)
from plugins.bot_unified_runtime.domains.media.ingest import vision_describe
from plugins.bot_unified_runtime.domains.media.ingest.transcribe import (
    build_native_audio_part,
)
from plugins.bot_unified_runtime.domains.media.ingest.video_understanding import (
    build_native_video_part,
)
from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
    extract_image_urls,
)

_WAV_BYTES = b"RIFF" + b"\x00" * 40


def _spec(model_id: str, priority: int, *tags: str) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        model=model_id,
        base_url="https://example.test/v1",
        api_key="key",
        tags=tags,
        priority=priority,
    )


def _router(**specs: ModelSpec) -> ModelRouter:
    return ModelRouter(specs, provider_factory=lambda spec: None)


# ---------------------------------------------------------------- 能力门


def test_native_audio_gate_requires_tag_and_defaults_closed() -> None:
    tagged = _router(gemini=_spec("gemini", 1, "vision", "native-audio"))
    plain = _router(grok=_spec("grok", 1, "high"))

    assert tagged.supports_native_media("audio") is True
    # 缺省不放行：grok 对视频是"200 但没看见"，按标签放行会静默丢内容。
    assert plain.supports_native_media("audio") is False


def test_native_media_gate_only_looks_at_first_candidate() -> None:
    # 判别格必须是「首位没有、次位有」：两枚都带同一标签时"只看首位"与"扫全部"
    # 结论相同，名字里那半条规矩等于没锁（席位 S11 注毒实证：改判据后 119 条全绿）。
    behind = _router(
        head=_spec("head", 1, "vision"),
        tail=_spec("tail", 2, "native-video"),
    )
    assert behind.supports_native_media("video") is False
    # 反向格：首位有、次位没有 ⇒ True（防"只看首位"被悄悄改成"只看末位"）。
    ahead = _router(
        head=_spec("head", 1, "native-video"),
        tail=_spec("tail", 2, "vision"),
    )
    assert ahead.supports_native_media("video") is True
    assert ahead.supports_native_media("audio") is False


def test_animation_is_a_native_kind_of_its_own() -> None:
    """动图/表情包的原生面独立于音视频，且缺省不放行。

    生产声明打在 `axon-gemini-38-flash`（运行时注册表 tags，本仓测试不读 Runtime，
    故这里只锁判据形态）；grok 不给它原生 gif 的依据是实跑 400
    （`not a valid JPG, PNG, WebP, or ICO image`），不是推测。
    """
    gemini = _router(
        gemini=_spec("gemini", 1, "vision", "native-audio", "native-video", "native-animation")
    )
    grok = _router(grok=_spec("grok", 1, "high"))
    assert gemini.supports_native_media("animation") is True
    assert grok.supports_native_media("animation") is False

    only_animation = _router(head=_spec("head", 1, "native-animation"))
    assert only_animation.supports_native_media("animation") is True
    # 三种 kind 互不牵连：声明能吃动图不等于能吃音频/视频（转译让路判据各管各的）。
    assert only_animation.supports_native_media("audio") is False
    assert only_animation.supports_native_media("video") is False


def test_unknown_media_kind_is_not_supported() -> None:
    router = _router(head=_spec("head", 1, "native-audio", "native-video"))
    assert router.supports_native_media("hologram") is False


# ---------------------------------------------------------------- 部件构造


@pytest.mark.parametrize(
    ("suffix", "want_format"),
    [(".wav", "wav"), (".mp3", "mp3")],
)
def test_build_native_audio_part_emits_verified_wire_shape(
    tmp_path, suffix: str, want_format: str
) -> None:
    audio = tmp_path / f"voice{suffix}"
    audio.write_bytes(_WAV_BYTES)

    part = build_native_audio_part(str(audio), max_mb=20.0)

    assert part is not None
    assert part["type"] == "input_audio"
    assert part["input_audio"]["format"] == want_format
    assert base64.b64decode(part["input_audio"]["data"]) == _WAV_BYTES


def test_build_native_audio_part_rejects_oversized_and_remote(tmp_path) -> None:
    audio = tmp_path / "big.mp3"
    audio.write_bytes(b"x" * 4096)

    assert build_native_audio_part(str(audio), max_mb=0.0001) is None
    # http URL 不在本机，交给下载/转译路径，绝不当原生部件塞进去。
    assert build_native_audio_part("https://example.test/a.mp3", max_mb=20.0) is None


def test_build_native_video_part_carries_data_url(tmp_path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"y" * 64)

    part = build_native_video_part(str(clip), max_mb=20.0)

    assert part is not None
    assert part["type"] == "video_url"
    assert part["video_url"]["url"].startswith("data:video/mp4;base64,")


def test_build_native_video_part_rejects_unknown_container(tmp_path) -> None:
    """认不出的容器必须返回 None，而不是发一个 `application/octet-stream` 的部件。

    注毒判据：把 `mime is None` 那行改回 `.get(..., "application/octet-stream")`
    本用例必红。真机依据是 grok 收 `video_url` 时"200 却答没看见内容"——无类型部件
    最可能的结局就是被静默忽略，宁缺勿滥。
    """
    gifish = tmp_path / "loop.gif"
    gifish.write_bytes(b"GIF89a" + b"y" * 64)

    assert build_native_video_part(str(gifish), max_mb=20.0) is None
    noext = tmp_path / "mystery"
    noext.write_bytes(b"y" * 64)
    assert build_native_video_part(str(noext), max_mb=20.0) is None


# ---------------------------------------------------------------- 装配


def test_direct_vision_messages_append_media_parts_after_text() -> None:
    messages = [{"role": "system", "content": "人设"}, {"role": "user", "content": "听这段"}]
    audio_part = {"type": "input_audio", "input_audio": {"data": "AAA", "format": "mp3"}}
    video_part = {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,AAA"}}

    out = build_direct_vision_messages(
        messages,
        query_text="这段说了什么",
        image_urls=[],
        media_parts=[audio_part, video_part],
    )

    content = out[-1]["content"]
    assert content[0] == {"type": "text", "text": "这段说了什么"}
    assert content[1:] == [audio_part, video_part]
    # 系统消息必须原样保留，不被多模态改造波及。
    assert out[0] == {"role": "system", "content": "人设"}


def test_direct_vision_messages_unchanged_without_media_parts() -> None:
    messages = [{"role": "user", "content": "在吗"}]

    out = build_direct_vision_messages(messages, query_text="在吗", image_urls=[])

    assert out == messages


# ------------------------------------------------ 逐跳重放：声明必须逐候选执法
#
# 上面的能力门只问链首一次，而真实请求会被故障转移**逐跳重发同一份 messages**
# （生产链 = [gemini, grok]）。后果由评审席实跑坐实：第二跳 grok 收到
# `image/gif` + `input_audio`，正撞它自己的 400 / 422 ⇒ 两跳皆败 ⇒ 首跳本来能
# 答的媒体消息变成整体失败（用户只拿到安全失败话术）。本组用例因此不看"门答对
# 没有"，只看**每一跳真正收到了什么**。


_AUDIO_PART = {"type": "input_audio", "input_audio": {"data": "QUFB", "format": "mp3"}}
_VIDEO_PART = {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,QUFB"}}
_JPEG_URL = "data:image/jpeg;base64,QUFB"
_GIF_URL = "data:image/gif;base64,QUFB"


def _failing_factory(journal: list[tuple[str, list[dict]]]):
    """provider 替身工厂：把该跳**真正收到**的 messages 记账后一律以可转移错误失败。

    用 `error_kind="server"`（在册可转移类）而非网络类，既保证链路必然走到第二跳，
    又不触发链级 fail-fast 的连续网络失败中止（那会把"第二跳收到了什么"这一幕
    直接抹掉＝假绿）。
    """

    def factory(spec: ModelSpec):
        def generate(messages, **kwargs):
            journal.append((spec.model_id, copy.deepcopy(list(messages))))
            raise LLMProviderError("hop failed", error_kind="server")

        return SimpleNamespace(generate=generate)

    return factory


def _two_hop_router(head_tags: tuple[str, ...], tail_tags: tuple[str, ...]):
    journal: list[tuple[str, list[dict]]] = []
    router = ModelRouter(
        {
            "head": _spec("head", 1, *head_tags),
            "tail": _spec("tail", 2, *tail_tags),
        },
        provider_factory=_failing_factory(journal),
        max_failover_seconds=0.0,
    )
    return router, journal


def _parts_for(journal, model_id: str) -> list[dict]:
    """该渠道所有跳收到的内容部件摊平（列表型 content 才是多模态请求体）。"""
    parts: list[dict] = []
    for hop_id, messages in journal:
        if hop_id != model_id:
            continue
        for message in messages:
            content = message.get("content")
            if isinstance(content, list):
                parts.extend(content)
    return parts


def _texts_for(journal, model_id: str) -> list[str]:
    return [
        str(part.get("text", ""))
        for part in _parts_for(journal, model_id)
        if part.get("type") == "text"
    ]


def _image_urls_for(journal, model_id: str) -> list[str]:
    return [
        str(part.get("image_url", {}).get("url", ""))
        for part in _parts_for(journal, model_id)
        if part.get("type") == "image_url"
    ]


def test_native_audio_is_never_replayed_to_a_hop_that_did_not_declare_it() -> None:
    router, journal = _two_hop_router(("vision", "native-audio"), ("vision",))
    messages = build_direct_vision_messages(
        [{"role": "system", "content": "人设"}, {"role": "user", "content": "听这段"}],
        query_text="这段说了什么",
        image_urls=[],
        media_parts=[dict(_AUDIO_PART)],
    )

    with pytest.raises(LLMProviderError):
        router.generate(messages, message_text="这段说了什么")

    # 链不缩：首跳瞬时故障时第二跳仍须被尝试，否则"媒体消息"整体失败的面更宽。
    assert [hop for hop, _ in journal] == ["head", "tail"]
    # 声明了的这一跳照旧收到原生部件（不许把原生面一起误伤掉）。
    assert any(part["type"] == "input_audio" for part in _parts_for(journal, "head"))
    # 没声明的这一跳绝不能再收到它（实跑依据：grok 网关对 input_audio 直接 422）。
    assert not any(part["type"] == "input_audio" for part in _parts_for(journal, "tail"))
    # 转译面（文字上下文）必须原样留在非原生那一跳上。
    assert "这段说了什么" in _texts_for(journal, "tail")


def test_shaping_is_per_channel_not_per_chain() -> None:
    """判据按**该候选自己的声明**算，不按"链上有谁没声明"一刀切。

    与 `supports_native_media` 的"只看链首"是同一条病根的两个方向：整链一刀切会
    把声明过的那一跳也裁掉（＝原生面静默失效，且 `native_audio_used` 标签还在，
    验收判据当场失真），故两半都得锁。
    """
    router, journal = _two_hop_router(("vision",), ("vision", "native-audio"))
    messages = build_direct_vision_messages(
        [{"role": "user", "content": "听这段"}],
        query_text="这段说了什么",
        image_urls=[],
        media_parts=[dict(_AUDIO_PART)],
    )

    with pytest.raises(LLMProviderError):
        router.generate(messages, message_text="这段说了什么")

    assert not any(part["type"] == "input_audio" for part in _parts_for(journal, "head"))
    assert any(part["type"] == "input_audio" for part in _parts_for(journal, "tail"))


def test_per_hop_shaping_drops_undeclared_animation_and_video_but_keeps_photos() -> None:
    router, journal = _two_hop_router(
        ("vision", "native-video", "native-animation"), ("vision",)
    )
    messages = build_direct_vision_messages(
        [{"role": "user", "content": "看图和看片"}],
        query_text="图和片各是什么",
        image_urls=[_JPEG_URL, _GIF_URL],
        media_parts=[dict(_VIDEO_PART)],
    )

    with pytest.raises(LLMProviderError):
        router.generate(messages, message_text="图和片各是什么")

    head_parts = _parts_for(journal, "head")
    assert any(part["type"] == "video_url" for part in head_parts)
    assert _image_urls_for(journal, "head") == [_JPEG_URL, _GIF_URL]
    tail_parts = _parts_for(journal, "tail")
    assert not any(part["type"] == "video_url" for part in tail_parts)
    # 只裁"这一跳不该收的那一枚"：动图被裁而纯图片必须留下——
    # 「见 gif 就删掉整族 image_url」的变异在此当场红（grok 收 png/jpeg 是 200）。
    assert _image_urls_for(journal, "tail") == [_JPEG_URL]


def test_payload_without_native_parts_is_replayed_untouched() -> None:
    """没有原生部件的请求体一字不改：不裁、不加说明、不重建结构。

    这是"改动不得外溢到纯文本/纯图片链路"的锁——裁件逻辑一旦写成无条件重写
    messages（例如无条件补一句"附件未送达"），纯图片与纯文本轮次就会被污染。
    """
    router, journal = _two_hop_router(("vision", "native-audio"), ("vision",))
    messages = build_direct_vision_messages(
        [{"role": "user", "content": "看这张"}],
        query_text="这张图里是什么",
        image_urls=[_JPEG_URL],
    )
    snapshot = copy.deepcopy(messages)

    with pytest.raises(LLMProviderError):
        router.generate(messages, message_text="这张图里是什么")

    assert [hop for hop, _ in journal] == ["head", "tail"]
    for _, sent in journal:
        assert sent == snapshot


def test_stripping_an_undeclared_part_leaves_an_explicit_note_for_that_hop() -> None:
    """裁掉部件必须**留下痕迹**，否则第二跳会自信地臆答它没收到的附件。

    只锁形态不锁措辞：有一条说明该附件没送达的文字部件 + 原始问句仍在。
    """
    router, journal = _two_hop_router(("vision", "native-audio"), ("vision",))
    messages = build_direct_vision_messages(
        [{"role": "user", "content": "听这段"}],
        query_text="这段说了什么",
        image_urls=[],
        media_parts=[dict(_AUDIO_PART)],
    )

    with pytest.raises(LLMProviderError):
        router.generate(messages, message_text="这段说了什么")

    tail_texts = _texts_for(journal, "tail")
    assert "这段说了什么" in tail_texts
    assert any("未送达" in text for text in tail_texts), tail_texts
    # 声明过的那一跳不该看到这句提示（它真收到了附件）。
    assert not any("未送达" in text for text in _texts_for(journal, "head"))


def test_hedged_workers_shape_payload_per_declaration() -> None:
    """影子并发是同一次泄露的第二条腿：worker 逐候选发请求，判据必须同源。

    生产缺省关（`BOT_CHAT_HEDGED_REQUESTS_ENABLED=false`），但这条腿今天仍在代码
    里，开影子就会漏——故不得只修串行路。
    """
    journal: list[tuple[str, list[dict]]] = []
    config = SimpleNamespace(
        bot_chat_hedged_requests_enabled=True,
        bot_chat_hedge_max_candidates=2,
        bot_chat_hedge_delay_seconds=0.0,
        bot_channel_health_enabled=False,
        bot_chat_strict_priority=True,
    )
    router = ModelRouter(
        {
            "head": _spec("head", 1, "vision", "native-audio"),
            "tail": _spec("tail", 2, "vision"),
        },
        provider_factory=_failing_factory(journal),
        credential_config=config,
        max_failover_seconds=0.0,
    )
    messages = build_direct_vision_messages(
        [{"role": "user", "content": "听这段"}],
        query_text="这段说了什么",
        image_urls=[],
        media_parts=[dict(_AUDIO_PART)],
    )

    with pytest.raises(LLMProviderError):
        router.generate(messages, message_text="这段说了什么")

    hopped = {hop for hop, _ in journal}
    assert {"head", "tail"} <= hopped
    assert any(part["type"] == "input_audio" for part in _parts_for(journal, "head"))
    assert not any(part["type"] == "input_audio" for part in _parts_for(journal, "tail"))


# ---------------------------------------------------------------- 判据本体
#
# 裁件行为已由上面五组用例锁死；这里只补"哪些部件算哪种 kind"与"标签怎么读"两张
# 表的边角（HTTP 签名 gif、大小写、空格），免得逐跳判据在真实形态上留盲区。


@pytest.mark.parametrize(
    ("part", "want"),
    [
        ({"type": "input_audio", "input_audio": {"data": "A", "format": "mp3"}}, "audio"),
        ({"type": "video_url", "video_url": {"url": "data:video/mp4;base64,A"}}, "video"),
        ({"type": "image_url", "image_url": {"url": _GIF_URL}}, "animation"),
        # QQ/CDN 的 gif 常以带签名的 http URL 原样透传（`extract_image_urls` 不转换
        # http URL），只认 data URL 会漏掉这一整批——同一跳照样会撞 400。
        (
            {"type": "image_url", "image_url": {"url": "https://c.test/a.gif?sign=1"}},
            "animation",
        ),
        ({"type": "image_url", "image_url": {"url": "https://c.test/A.GIF"}}, "animation"),
        ({"type": "image_url", "image_url": {"url": _JPEG_URL}}, None),
        ({"type": "image_url", "image_url": {"url": "https://c.test/a.png"}}, None),
        # 查询串里出现 .gif 不算容器本身（路径才是事实）。
        ({"type": "image_url", "image_url": {"url": "https://c.test/a.png?f=.gif"}}, None),
        ({"type": "text", "text": "说话"}, None),
    ],
)
def test_native_kind_detected_from_part_shape(part: dict, want: str | None) -> None:
    kinds = native_media_kinds_in_payload([{"role": "user", "content": [part]}])
    assert (want in kinds) if want else (kinds == frozenset())


def test_string_content_and_malformed_parts_are_not_native() -> None:
    assert native_media_kinds_in_payload([{"role": "user", "content": "纯文本"}]) == frozenset()
    # 畸形部件（image_url 直接给字符串）不得抛异常——判据失败宁可放行也不炸链路。
    assert native_media_kinds_in_payload(
        [{"role": "user", "content": [{"type": "image_url", "image_url": _GIF_URL}]}]
    ) == frozenset({"animation"})
    assert native_media_kinds_in_payload([{"role": "user"}]) == frozenset()
    assert native_media_kinds_in_payload([None]) == frozenset()  # type: ignore[list-item]


def test_declared_native_kinds_reads_tags_case_and_space_tolerantly() -> None:
    assert declared_native_media_kinds(
        ("Native-Audio", " native-video ", "vision", "native-", "high")
    ) == frozenset({"audio", "video"})
    assert declared_native_media_kinds(()) == frozenset()
    # 标签解释与装配期那道门必须同源：同一张标签表两边结论一致。
    router = _router(gemini=_spec("gemini", 1, "NATIVE-AUDIO", "vision"))
    assert router.supports_native_media("audio") is True


# ================================================ S36 跟进三件（评审席 S32 贰-1/2/3）
#
# 裁件本身（上面两组用例）方向是对的，但评审席在同一份码上又确定性复现出三处：
#   贰-1 裁件是 `_hedge_attempt` 里**新增的无防护抛点** ⇒ 影子等待方永久挂死；
#   贰-2 "animation" 有两副判据（装配门看 sticker+animation 两组，裁件只认 gif）
#        ⇒ http `.mp4` 形态的动图段被直挂进请求体后不裁 = 同一类网关 400；
#   贰-3 转译口（`DynamicVisionProvider.generate`）是**第五条重发同一份 messages
#        的路**，且它的候选注册表根本没有 `native-*` 可问 ⇒ `keep_animation_raw`
#        产的原字节 gif 正从这条路进去。


# ------------------------------------------------------------------ 贰-1 挂死面
class _UrlThatRaisesOnStr(str):
    """一枚 `str()` 就抛异常的 URL 值——裁件对载荷做的事正是 `str()`。

    诚实标注：生产 `chat.py` 全程把 URL `str()` 化后才塞进部件，所以今天从
    装配口构造不出这种对象（评审席同判，其可达性三合取之一）。本用例锁的因此
    **不是**"这个形态会不会真发生"，而是"裁件一旦抛，影子 worker 怎么结算"——
    载荷仍由真装配口 `build_direct_vision_messages` 产出，不手写部件。
    """

    def __str__(self) -> str:
        raise RuntimeError("shaping cannot read this payload")


def _hedge_router(
    journal: list[tuple[str, list[dict]]],
) -> ModelRouter:
    """影子并发开着的两候选路由器（与既有影子用例同型配置）。"""
    config = SimpleNamespace(
        bot_chat_hedged_requests_enabled=True,
        bot_chat_hedge_max_candidates=2,
        bot_chat_hedge_delay_seconds=0.0,
        bot_channel_health_enabled=False,
        bot_chat_strict_priority=True,
    )
    return ModelRouter(
        {
            "head": _spec("head", 1, "vision", "native-audio"),
            "tail": _spec("tail", 2, "vision"),
        },
        provider_factory=_failing_factory(journal),
        credential_config=config,
        max_failover_seconds=0.0,  # 无链预算 ⇒ 等待方 `cond.wait(None)`，挂死只需一处抛
    )


def test_a_raising_shaping_settles_the_hedge_worker_instead_of_hanging_the_waiter() -> None:
    """裁件抛异常时，影子等待方必须**在有限时间内返回**（S32 贰-1）。

    复现依据：评审席 `p7_hang.py` 打印 `HANG-NO-RETURN-after-8s hops_called=[]`
    ——两个 worker 当场死在 `_hedge_attempt` 里那道 try **之外**的裁件调用上，
    等待方 `while True` + `race.cond.wait(None)` 永远等不到 settle。同一个函数
    自己的注释就写着"影子线程二次异常不得炸线程：炸了等待方永远等不到 settle"
    （`_hedge_attempt` 去参重试那一支），裁件却没被这句话罩住。

    三腿：① 等待方返回（不挂死）；② 这次调用以异常收场，绝不"静默当成功"；
    ③ **一跳都没发出去**——裁件算不出来时不得带着未裁的载荷出门（泄露面必须
    保持关闭，这也是本仓 fail-closed 的极性）。
    """
    journal: list[tuple[str, list[dict]]] = []
    router = _hedge_router(journal)
    messages = build_direct_vision_messages(
        [{"role": "user", "content": "听这段"}],
        query_text="这段说了什么",
        image_urls=[_UrlThatRaisesOnStr("data:image/gif;base64,QUFB")],
        media_parts=[dict(_AUDIO_PART)],
    )
    # 前提自证（走公共取数口，不碰私有件）：这份载荷确实让裁件抛。
    with pytest.raises(RuntimeError):
        native_media_kinds_in_payload(messages)

    outcome: dict[str, object] = {}

    def _call() -> None:
        try:
            outcome["reply"] = router.generate(messages, message_text="这段说了什么")
        except BaseException as exc:  # noqa: BLE001 - 死因由下面的断言判，不在这里改判。
            outcome["error"] = exc

    waiter = threading.Thread(target=_call, name="s36-hedge-waiter", daemon=True)
    waiter.start()
    waiter.join(timeout=8.0)
    assert not waiter.is_alive(), (
        "等待方 8 秒内没返回：裁件异常逃出了影子 worker 的错误路径（S32 贰-1 挂死）"
    )
    assert "error" in outcome, f"裁件失败却被当成一次正常返回：{outcome}"
    assert journal == [], f"裁件算不出来时一发都不该发出（泄露面不得被打开）：{journal}"


# ------------------------------------------------------------------ 贰-2 两副判据
@pytest.mark.parametrize(
    ("url", "want_animation"),
    [
        (_GIF_URL, True),
        # 视频容器：`animation` 段的 http URL 由 `extract_image_urls` **原样透传**
        # （http 分支根本不进 `_image_file_to_data_url`），而 Telegram 动图落盘
        # 后缀恒 `.mp4` ⇒ 只认 gif 的裁件对这一整批是瞎的，同一发必败请求换个形态。
        ("data:video/mp4;base64,QUFB", True),
        ("https://media.test/loop.mp4", True),
        ("https://media.test/loop.webm?sign=1", True),
        ("https://media.test/LOOP.MOV", True),
        # 反向格（防过裁）：静态图容器与非容器形态的签名 URL 必须照旧放行——
        # QQ 图片签名 URL 常无扩展名，判成动图会把纯照片一起从这一跳上裁掉。
        ("data:image/png;base64,QUFB", False),
        (_JPEG_URL, False),
        ("https://c.test/a.png", False),
        ("https://gchat.qpic.cn/gchatpic_new/1234/0", False),
        ("", False),
    ],
)
def test_non_gif_animation_containers_need_a_declaration_too(
    url: str, want_animation: bool
) -> None:
    kinds = native_media_kinds_in_payload(
        [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}]
    )
    assert ("animation" in kinds) is want_animation, url


def test_http_mp4_animation_is_not_replayed_to_a_hop_that_never_declared_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**组成缝活性锁**：真取数口 → 真装配口 → 真路由器两跳（评审席贰-2 + 贰-4）。

    与上一条表格用例的分工：表格用例判"哪些形态算动图"，本用例判"装配侧真能
    挂上来的形态，裁件侧真的裁不裁"。两副判据的差集就是新的一发必败请求，而
    这个差集在两侧各自绿的状态下看不见（本仓在册病形「helper 全绿、组合必坏」）。
    """
    mp4 = "https://media.test/loop.mp4"
    photo = "https://gchat.qpic.cn/gchatpic_new/1234/0"
    segments = [
        {"type": "animation", "data": {"url": mp4}},
        {"type": "image", "data": {"url": photo}},
    ]
    # 只替掉网络 IO 叶子：下载失败时 `prepare_vision_image_urls` 保留原 URL
    # （生产同一条降级路径），载荷形状因此与真机一致、且测试零出网。
    monkeypatch.setattr(
        vision_describe, "_download_image_bytes", lambda url, **kwargs: None
    )
    meme_urls = extract_image_urls(
        segments, groups=("sticker", "animation"), keep_animation_raw=True
    )
    photo_urls = extract_image_urls(
        segments, groups=("photo",), keep_animation_raw=True
    )
    assert meme_urls == [mp4] and photo_urls == [photo]  # 前提：两段都真挂得上来

    messages = build_direct_vision_messages(
        [{"role": "user", "content": "看这个动图"}],
        query_text="这个动图是什么",
        image_urls=photo_urls + meme_urls,
    )
    router, journal = _two_hop_router(("vision", "native-animation"), ("vision",))

    with pytest.raises(LLMProviderError):
        router.generate(messages, message_text="这个动图是什么")

    # 声明了 native-animation 的那一跳：两枚都收到（原生面不许被误伤）。
    assert _image_urls_for(journal, "head") == [photo, mp4]
    # 没声明的那一跳：只留静态图，mp4 形态的动图必须被裁掉。
    assert _image_urls_for(journal, "tail") == [photo]
    assert any("未送达" in text for text in _texts_for(journal, "tail"))


# ------------------------------------------------------------------ 贰-3 转译口
def _real_gif_bytes() -> bytes:
    """四帧真动图（随机字节会令 PIL 以"文件损坏"为由失败，测到的是夹具不是代码）。"""
    from io import BytesIO

    from PIL import Image, ImageDraw

    frames = []
    for digit in "1234":
        frame = Image.new("RGB", (120, 120), "white")
        ImageDraw.Draw(frame).text((60, 60), digit, fill=(200, 0, 0), anchor="mm")
        frames.append(frame)
    buffer = BytesIO()
    frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=300,
        loop=0,
    )
    return buffer.getvalue()


def test_the_transcription_port_is_never_handed_the_raw_animation_bytes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """转译口 ≤3 个视觉候选重发同一份 messages，而它的注册表没有 `native-*` 可问。

    入口与死因都按评审席贰-3 的复现口径：真能力层 `build_chat_capability`（非
    直传那一支，`vision_mode="relay"`）+ **真** `DynamicVisionProvider`（≤3 候选
    故障转移那段代码原样跑），只在 HTTP 叶子上记账。
    断言三腿：① 转译口确实被调用过（否则本用例是空跑）；② 收到的部件里没有
    `data:image/gif` 原字节；③ 动图**仍然**被送去转译（静态化后的帧条），
    即修法不是"干脆别发"——那会把格 5 的"读不到表情包"换成另一版本的读不到。
    """
    gif = tmp_path / "meme.gif"
    gif.write_bytes(_real_gif_bytes())
    segments = [{"type": "animation", "data": {"file": str(gif)}}]

    recorded: list[list[dict]] = []

    def _recording_generate(messages, **kwargs):
        recorded.append(copy.deepcopy(list(messages)))
        return SimpleNamespace(text="一只转圈的猫")

    vision = vision_describe.DynamicVisionProvider(
        SimpleNamespace(
            bot_vision_enabled=True,
            bot_vision_model_registry={
                "v1": {"model": "vision-a", "base_url": "https://v.test/v1", "api_key": "k"},
                "v2": {"model": "vision-b", "base_url": "https://v.test/v1", "api_key": "k"},
            },
            bot_download_proxy="",
            bot_vision_timeout_seconds=20.0,
        )
    )
    monkeypatch.setattr(
        vision, "_provider_for", lambda entry_id, entry: SimpleNamespace(generate=_recording_generate)
    )

    router = ModelRouter(
        {"head": _spec("head", 1, "vision", "native-animation")},
        provider_factory=lambda spec: StaticLLMProvider(text="这只猫在转圈"),
    )
    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="不该被用到"),
        model_router=router,
        vision_provider=vision,
        vision_enabled=True,
        vision_mode="relay",
    )
    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="private:u",
        session_type=SessionType.PRIVATE,
        sender_id="u",
        plain_text="这动图是什么",
        raw_segments=segments,
        mentions_bot=True,
    )
    decision = BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )

    capability(message, decision)

    image_urls = [
        str(part.get("image_url", {}).get("url", ""))
        for call in recorded
        for message_body in call
        for part in (message_body.get("content") or [])
        if isinstance(part, dict) and part.get("type") == "image_url"
    ]
    assert recorded, "转译口一次都没被调用：本用例退化成空跑"
    assert not any(url.startswith("data:image/gif") for url in image_urls), (
        f"原字节 gif 进了转译口（未声明却重放 = S26 格 5 反向泄漏）：{image_urls}"
    )
    assert any(url.startswith("data:image/jpeg") for url in image_urls), (
        f"动图被整个丢掉而不是静态化后转译：{image_urls}"
    )


# ================================================================ S40 缺陷 D1
#
# 内容路由（INTIMATE 头插）把**真实首跳**换成了没声明的那一家，而装配期那道能力门
# 问的仍是默认链首（`supports_native_media` 里 `route_ids(...)` 不传 `session_key`）：
# 门答"能原生吃" ⇒ ASR/抽帧让路 ⇒ 真首跳再按自己的声明把部件裁掉（S31 的逐跳裁件）
# ⇒ 没声明的一家 HTTP 200 抢跑、能答的那家永不被问 ⇒ 语音/视频/动图内容**静默丢失**，
# 用户侧零报错。这正是 S26 那条 P0 泄露被内容路由自己重新打开的口子（评审席 S39 §一.3
# 用生产注册表实跑：`hop_for_intimate_head_content_types=["text"]`）。
#
# 这里的锁一律"两侧都取函数返回值现算"：门的答复必须逐字等于**真首跳实际收到的**载荷
# 里还留着哪几种原生部件。只断 "tags 里含 native-audio" 属于常量断言，不算锁。
# 会话键一律由中央件产出（`build_session_key`/`member_session_key`）并自证形态——
# 手写 `group:900` 那类生产永不产出的键形，正是这条泄露带着 87+69 条绿测试零覆盖的原因。

_GEMINI_TAGS = ("vision", "native-audio", "native-video", "native-animation")
_GROK_TAGS = ("high",)  # 生产实况：grok 三种原生媒体一个都没声明（实测 422/400/"没看见"）


def _content_route_config(**overrides: object) -> SimpleNamespace:
    """内容路由配置面（键名与 `Config` 一致，值取生产缺省）。"""
    base: dict[str, object] = {
        "bot_content_route_enabled": True,
        "bot_content_route_model": "grok-4.6",
        "bot_content_route_order": "grok-4.6,gemini-3.8-flash",
        "bot_content_route_words": "",
        "bot_content_route_intimate_threshold": 60.0,
        "bot_content_route_normal_threshold": 25.0,
        "bot_content_route_context_turns": 4,
        "bot_content_route_max_ttl_minutes": 120.0,
        "bot_content_route_idle_reset_minutes": 10.0,
        "bot_content_route_intimate_ttl_minutes": 60.0,
        "bot_content_route_group_per_user_enabled": True,
        "bot_content_route_group_whitelist": [],
        "bot_content_route_group_blacklist": [],
        "bot_content_route_private_whitelist": [],
        "bot_content_route_private_blacklist": [],
        "bot_master_love_enabled": False,
        "bot_master_love_admins": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _media_chain_router(content_route_cb: object, journal: list) -> ModelRouter:
    """生产形状的两跳链：默认链首 gemini（声明三种原生）+ grok（什么都不声明）。"""
    return ModelRouter(
        {
            "gemini-3.8-flash": _spec("gemini-3.8-flash", 1, *_GEMINI_TAGS),
            "grok-4.6": _spec("grok-4.6", 2, *_GROK_TAGS),
        },
        provider_factory=_failing_factory(journal),
        content_route_cb=content_route_cb,  # type: ignore[arg-type]
        max_failover_seconds=0.0,
    )


def _member_route_key(group_id: str, sender_id: str) -> str:
    """路由/注入键只准由中央件产出，并自证摄取层形态（挡住 `group:900` 进夹具）。"""
    session_key = build_session_key(group_id, sender_id)
    parsed = parse_session_key(session_key)
    assert parsed.form == FORM_UNDERSCORE, parsed
    assert (parsed.group_id, parsed.user_id) == (group_id, sender_id), parsed
    return member_session_key(session_key, sender_id)


def _three_kind_payload(text: str) -> list:
    """一次挂上音/视/动图三种原生部件（载荷由真装配口产出，不手写部件）。"""
    return build_direct_vision_messages(
        [{"role": "user", "content": text}],
        query_text=text,
        image_urls=[_JPEG_URL, _GIF_URL],
        media_parts=[dict(_AUDIO_PART), dict(_VIDEO_PART)],
    )


def _hop_text(journal: list, index: int) -> str:
    """某一跳真正收到的全部文字（str 正文与部件里的 text 都算）。"""
    _, messages = journal[index]
    chunks: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            chunks.extend(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
    return "\n".join(chunks)


class _RecordingAsrProvider:
    """ASR 替身：只记账 + 给一段转写（被真入口 `transcribe_audio` 直呼）。"""

    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.calls: list[str] = []

    def generate(self, audio_bytes: bytes, filename: str, **kwargs: object) -> str:
        self.calls.append(f"{filename}:{len(audio_bytes)}")
        return self.transcript


def _group_incoming(
    session_key: str, group_id: str, sender_id: str, text: str, segments: list
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id=session_key,
        session_type=SessionType.GROUP,
        sender_id=sender_id,
        group_id=group_id,
        plain_text=text,
        raw_segments=segments,
        mentions_bot=True,
    )


def _group_decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )


def test_intimate_head_insertion_never_outranks_native_media_gate() -> None:
    """**D1 主锁**：门的答复 == 真首跳载荷里实际留下的原生 kind（两侧现算）。"""
    engine = ContentRouteEngine()
    cfg = _content_route_config()
    key = _member_route_key("700100001", "1000000001")
    assert engine.apply_manual(key, "intimate", cfg)
    journal: list = []
    router = _media_chain_router(build_router_cb(engine, lambda: cfg), journal)
    text = "听听这段，再看看这个动图"

    # 前提自证（公共入口现算）：这一会话的真实首跳已经被换成没声明的那一家。
    assert (
        router.route_ids(message_text=text, override="", session_key=key)[0]
        == "grok-4.6"
    )

    with pytest.raises(LLMProviderError):
        router.generate(_three_kind_payload(text), message_text=text, session_id=key)
    assert journal[0][0] == "grok-4.6", journal
    received_at_real_head = native_media_kinds_in_payload(journal[0][1])
    assert received_at_real_head == frozenset(), received_at_real_head

    for kind in ("audio", "video", "animation"):
        gate = router.supports_native_media(
            kind, message_text=text, override="", session_key=key
        )
        assert gate is (kind in received_at_real_head), (
            kind,
            gate,
            received_at_real_head,
        )
    # 反向格：静态照片与文字不属于原生面，必须照旧留在真首跳上（防"整族裁掉"的过修）。
    assert _image_urls_for(journal, "grok-4.6") == [_JPEG_URL]
    assert text in _hop_text(journal, 0)


def test_default_head_session_still_mounts_declared_native_media() -> None:
    """未亲密的会话逐字节不变：链首声明过 ⇒ 三种原生部件照挂（防"干脆别原生"的过修）。"""
    engine = ContentRouteEngine()
    cfg = _content_route_config()
    key = _member_route_key("700100002", "1000000002")  # 从未钉过 ⇒ verdict=normal
    journal: list = []
    router = _media_chain_router(build_router_cb(engine, lambda: cfg), journal)
    text = "听听这段"

    assert (
        router.route_ids(message_text=text, override="", session_key=key)[0]
        == "gemini-3.8-flash"
    )
    with pytest.raises(LLMProviderError):
        router.generate(_three_kind_payload(text), message_text=text, session_id=key)
    received = native_media_kinds_in_payload(journal[0][1])
    assert received == frozenset({"audio", "video", "animation"}), received
    for kind in ("audio", "video", "animation"):
        assert (
            router.supports_native_media(
                kind, message_text=text, override="", session_key=key
            )
            is True
        )


def test_intimate_voice_is_transcribed_not_mounted_on_the_swapped_head(
    tmp_path,
) -> None:
    """**D1 组成缝活性锁**：真能力层 + 真路由器 + 真 ASR 口，走生产摄取键形。

    亲密档由**真入口**自己产出（成员说一句「亲密模式 深开」——2026-09-24 R3 A 之后
    只有深档才换真实首跳，浅档「亲密模式 开」不换头，见 tests/test_intimate_tiers_v4.py），
    不手写钉、不手写键。
    """
    cfg = _content_route_config(bot_content_route_group_whitelist=["700100003"])
    group_key = build_session_key("700100003", "1000000003")
    member_key = member_session_key(group_key, "1000000003")
    journal: list = []
    router = _media_chain_router(
        build_router_cb(SHARED_CONTENT_ROUTE_ENGINE, lambda: cfg), journal
    )
    asr = _RecordingAsrProvider("帮我看看明天的天气")
    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="不该被用到"),
        model_router=router,
        asr_provider=asr,
        asr_enabled=True,
        content_route_config=cfg,
    )

    opener = _group_incoming(group_key, "700100003", "1000000003", "亲密模式 深开", [])
    capability(opener, _group_decision(opener))
    # 前提：这一档确实是真入口自己钉上去的（不是夹具手写）。
    assert SHARED_CONTENT_ROUTE_ENGINE.pinned_mode(member_key, cfg) == "intimate"

    clip = tmp_path / "voice.mp3"
    clip.write_bytes(b"ID3\x04" + b"\x00" * 128)
    segments = [{"type": "record", "data": {"file": str(clip)}}]
    message = _group_incoming(
        group_key, "700100003", "1000000003", "听听这个", segments
    )
    capability(message, _group_decision(message))

    assert journal, "一次请求都没发出：本用例退化成空跑"
    assert journal[0][0] == "grok-4.6"
    assert native_media_kinds_in_payload(journal[0][1]) == frozenset(), (
        "亲密首跳仍收到原生音频 ⇒ 能力门问错了那一跳"
    )
    assert asr.calls, "音频既没原生送达也没转写 ⇒ 语音内容彻底丢失"
    assert asr.transcript in _hop_text(journal, 0)


def test_non_intimate_voice_still_goes_native_and_skips_asr(tmp_path) -> None:
    """同群里未钉亲密的另一名成员：原生照挂、ASR 让路（09-23 裁定不变）。"""
    cfg = _content_route_config(bot_content_route_group_whitelist=["700100004"])
    group_key = build_session_key("700100004", "1000000004")
    member_key = member_session_key(group_key, "1000000004")
    journal: list = []
    router = _media_chain_router(
        build_router_cb(SHARED_CONTENT_ROUTE_ENGINE, lambda: cfg), journal
    )
    asr = _RecordingAsrProvider("这句话不该被转写")
    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="不该被用到"),
        model_router=router,
        asr_provider=asr,
        asr_enabled=True,
        content_route_config=cfg,
    )
    clip = tmp_path / "voice.mp3"
    clip.write_bytes(b"ID3\x04" + b"\x00" * 128)
    message = _group_incoming(
        group_key,
        "700100004",
        "1000000004",
        "听听这个",
        [{"type": "record", "data": {"file": str(clip)}}],
    )
    capability(message, _group_decision(message))

    assert SHARED_CONTENT_ROUTE_ENGINE.pinned_mode(member_key, cfg) is None
    assert journal, "一次请求都没发出：本用例退化成空跑"
    assert journal[0][0] == "gemini-3.8-flash"
    assert native_media_kinds_in_payload(journal[0][1]) == frozenset({"audio"})
    assert asr.calls == [], "未亲密会话被拖回落 ASR ⇒ 修过头了"


# ============================ S42 跟进 C：能力门调用点必须显式传 session_key =======
#
# `supports_native_media` 的 `session_key` 缺省 `""`（为兼容既有调用面而留），而
# 传空串 = 门退回问默认链首 = D1 那枚静默丢内容的 bug 类**整类复开**。今天没有任何
# 机器门拦得住"将来某个新调用点忘传这个 kwarg"（S39/S40 就是这一类bug 复发的先例，
# S41 §7 建议②点名补锁）。判据只走真 AST 节点（`ast.Call.func` + `keywords`），
# 不走 `ast.unparse` 子串——unparse 会把 docstring/注释里的散文点名也算成调用点
# （`domains/vision/capabilities/modality_preprocessing.py` 的模块 docstring 就
# 散文点名了本门，零调用；先例教训=tests/test_progress_ack.py 的"判定走真 AST"）。
# 范围=生产树（plugins/ 与 scripts/）；tests/ 里直调门是测门本身，不在此锁面。

_NATIVE_MEDIA_GATE = "supports_native_media"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PRODUCTION_TREES = (_REPO_ROOT / "plugins", _REPO_ROOT / "scripts")


def _native_media_gate_audit(source: str, filename: str) -> tuple[int, list[str]]:
    """现算一个源文件里的门真调用点：返回 (调用点数, 违例描述列表)。

    违例 = 未显式传 `session_key=`，或传了**字面空串**（与漏传同形，门答默认链首）。
    解析不了的源文件按"扫描器不许瞎"记账为违例，不静默跳过。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - 生产树不该出现，出现即违例
        return 0, [f"{filename}: 无法解析（{exc}）"]
    seen = 0
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = (
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else node.func.id
            if isinstance(node.func, ast.Name)
            else None
        )
        if called != _NATIVE_MEDIA_GATE:
            continue
        seen += 1
        kw = next((k for k in node.keywords if k.arg == "session_key"), None)
        if kw is None:
            violations.append(f"{filename}:{node.lineno} 调用未传 session_key=")
        elif isinstance(kw.value, ast.Constant) and kw.value.value == "":
            violations.append(f"{filename}:{node.lineno} session_key 传字面空串")
    return seen, violations


def test_every_production_native_media_gate_passes_session_key() -> None:
    """全生产树每个真调用点都必须显式传真实会话键；且自证扫描器确实看见了它们。"""
    total = 0
    violations: list[str] = []
    for root in _PRODUCTION_TREES:
        assert root.is_dir(), root
        for path in sorted(root.rglob("*.py")):
            calls, bad = _native_media_gate_audit(
                path.read_text(encoding="utf-8"), str(path.relative_to(_REPO_ROOT))
            )
            total += calls
            violations.extend(bad)
    # 地板只挡"扫描器瞎了/树没读到"这一种假绿形态（真值以现算为准，不写死条数）。
    assert total >= 3, f"生产树上一个门调用点都没扫到（total={total}）⇒ 判据失效"
    assert violations == [], "存在会把 D1 bug 类静默重开的调用点"


def test_session_key_gate_lock_has_teeth_on_poison_snippets() -> None:
    """注毒自证（S41 §7 建议②的杀伤力面）：违例形态必被抓、合规形态不误伤。

    合成源走同一真判据函数，不落任何仓库文件——与「全量套件不许被注毒」的在册纪律
    同形（先例=tests/test_documentation_consistency.py 的注毒必红/带指针放行两腿）。
    """
    missed = _native_media_gate_audit(
        'ok = model_router.supports_native_media("audio", message_text=t, override=o)\n',
        "poison_missing_kwarg.py",
    )
    assert missed[0] == 1 and len(missed[1]) == 1, missed  # 漏传 ⇒ 必红
    empty = _native_media_gate_audit(
        'ok = model_router.supports_native_media("audio", session_key="")\n',
        "poison_empty_key.py",
    )
    assert empty[0] == 1 and len(empty[1]) == 1, empty  # 传死空串 ⇒ 必红
    bare = _native_media_gate_audit(
        'ok = supports_native_media("audio", message_text=t)\n',
        "poison_bare_name.py",
    )
    assert bare[0] == 1 and len(bare[1]) == 1, bare  # 裸名直调漏传 ⇒ 必红
    good = _native_media_gate_audit(
        'ok = model_router.supports_native_media("audio", session_key=key)\n',
        "good.py",
    )
    assert good == (1, []), good  # 合规 ⇒ 不误伤
    prose = _native_media_gate_audit(
        '"""docstring 散文点名 supports_native_media 不是调用点"""\n'
        "router_probe = getattr(model_router, 'supports_native_media', None)\n",
        "prose.py",
    )
    assert prose == (0, []), prose  # docstring/getattr 取引用不是调用，不算违例


# ================================== T1 裁定（2026-09-24）：ML 不改默认模型 × 转译优先 ==
#
# 两枚裁定在同一处咬合：
#
# ① **Master Love 不得改变默认模型**——名单用户的默认模型仍是缺省链首 gemini，ML 只
#   授予亲密档（语气 + 内容放行）。于是 S39 §一.3 那格"最常亲密的那两个号"的媒体泄露
#   在源头就没了：门问的首跳与真实首跳是同一家。换模型只由**显式「亲密模式 深开」/管理员钉**
#   （以及内容信号自己越阈）触发。
# ② **非全模态的真实首跳不得把音/视/动图剥掉**——先转译（ASR / 抽帧），只有在**转译也
#   不可用**时才允许"剥掉"这一档（此时仍把部件挂上，由逐跳裁件 + 故障转移去兜，并留下
#   可见痕迹），绝不允许"既没原生送达、也没转译"的静默丢失。
#
# 纪律：会话键只由中央件产出（私聊=裸 QQ 号，自证 `FORM_BARE`）；亲密档只由**真入口**
# 产生（ML 分支 / 本人说一句「亲密模式 开」），测试不手写 `apply_manual` 伪造 ML。


def _private_ingest_key(uid: str) -> str:
    """私聊会话键（摄取层真形=裸 QQ 号），并自证形态。"""
    key = private_session_key(uid)
    parsed = parse_session_key(key)
    assert parsed.form == FORM_BARE, parsed
    assert parsed.user_id == uid, parsed
    return key


def _private_incoming(
    session_key: str, sender_id: str, text: str, segments: list
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id=session_key,
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
        raw_segments=segments,
    )


def _private_decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )


def _run_private_turn(
    cfg: SimpleNamespace,
    journal: list,
    uid: str,
    text: str,
    segments: list,
    **capability_kwargs: object,
) -> ModelRouter:
    """真能力层跑一条私聊消息（ML 自动钉与显式指令都发生在它里面），返回所用路由器。"""
    router = _media_chain_router(
        build_router_cb(SHARED_CONTENT_ROUTE_ENGINE, lambda: cfg), journal
    )
    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="不该被用到"),
        model_router=router,
        content_route_config=cfg,
        **capability_kwargs,  # type: ignore[arg-type]
    )
    key = _private_ingest_key(uid)
    message = _private_incoming(key, uid, text, segments)
    capability(message, _private_decision(message))
    return router


def _voice_file(tmp_path) -> str:
    clip = tmp_path / "voice.mp3"
    clip.write_bytes(b"ID3\x04" + b"\x00" * 128)
    return str(clip)


def _video_file(tmp_path) -> str:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"y" * 64)
    return str(clip)


def test_master_love_never_changes_the_default_model(tmp_path) -> None:
    """**裁定①主锁（Step 2b 第一格）**：ML 名单内私聊用户跑完一轮之后，
    `route_ids()` 首位仍是缺省链首 gemini——ML 只给档、不给换模型。"""
    uid = "940000001"
    key = _private_ingest_key(uid)
    cfg = _content_route_config(bot_master_love_enabled=True, bot_master_love_admins=[uid])
    journal: list = []

    router = _run_private_turn(cfg, journal, uid, "今天也想你", [])

    # 前提自证（公共入口现算）：档真的由真入口钉上了，且来源是 ML。
    assert SHARED_CONTENT_ROUTE_ENGINE.pinned_mode(key, cfg) == "intimate"
    verdict = SHARED_CONTENT_ROUTE_ENGINE.route_verdict(key, cfg)
    assert verdict.get("source") == INTIMATE_SOURCE_MASTER_LOVE, verdict
    # 判据本体：真实首跳仍是 gemini（声明过原生媒体），grok 没有被头插。
    assert router.route_ids(message_text="今天也想你", override="", session_key=key)[0] == (
        "gemini-3.8-flash"
    )
    assert journal and journal[0][0] == "gemini-3.8-flash", journal


def test_explicit_intimate_command_is_what_changes_the_default_model(tmp_path) -> None:
    """**裁定①反向格（Step 2b 第二格）**：同一会话被本人显式「亲密模式 深开」之后，
    首位才允许换成 grok——两格缺一格就是把 ML 与显式深开混成同一条路。
    （2026-09-24 R3 A：浅档「亲密模式 开」只给语气与放行，不换模型。）"""
    uid = "940000002"
    key = _private_ingest_key(uid)
    cfg = _content_route_config(bot_master_love_enabled=True, bot_master_love_admins=[uid])
    journal: list = []

    router = _run_private_turn(cfg, journal, uid, "亲密模式 深开", [])

    verdict = SHARED_CONTENT_ROUTE_ENGINE.route_verdict(key, cfg)
    assert verdict["mode"] == "intimate", verdict
    assert verdict.get("source") == INTIMATE_SOURCE_MANUAL, verdict
    assert router.route_ids(message_text="在吗", override="", session_key=key)[0] == "grok-4.6"


def test_master_love_pinned_session_does_not_strip_media_at_the_gate(tmp_path) -> None:
    """**裁定①×②合并格（Step 1）**：ML 名单内私聊 + 一段语音 ⇒ 语音必须**送达**。

    改码前的实跑形态（本格 RED 依据）：装配门先按"还没钉"的默认链首答"能原生吃"⇒
    部件挂上、ASR 让路 ⇒ `build_chat_result` 里 ML 才把档钉上 ⇒ 真实首跳被换成零声明
    的 grok ⇒ 逐跳裁件把音频裁掉（日志 `llm native media stripped`）⇒ 首跳 200 抢跑、
    能答的 gemini 永不被问 ⇒ **她没听见，用户侧零报错**。
    裁定①落地后 ML 不换首跳，门与真实首跳重新是同一家 ⇒ 音频原生送达、无需转译。
    """
    uid = "940000003"
    key = _private_ingest_key(uid)
    cfg = _content_route_config(bot_master_love_enabled=True, bot_master_love_admins=[uid])
    journal: list = []
    asr = _RecordingAsrProvider("这句话不必转写")

    _run_private_turn(
        cfg,
        journal,
        uid,
        "听听这个",
        [{"type": "record", "data": {"file": _voice_file(tmp_path)}}],
        asr_provider=asr,
        asr_enabled=True,
    )

    assert journal, "一次请求都没发出：本用例退化成空跑"
    assert SHARED_CONTENT_ROUTE_ENGINE.pinned_mode(key, cfg) == "intimate"
    head_id, head_messages = journal[0]
    assert head_id == "gemini-3.8-flash", f"ML 会话的首跳被换掉了：{head_id}"
    # 送达判据（两侧现算，不看日志）：音频**在**首跳载荷上，且这一跳没有被裁件的痕迹。
    assert "audio" in native_media_kinds_in_payload(head_messages), (
        "ML 会话的语音在真实首跳被剥掉了 ⇒ 门问的首跳与真实首跳又不同源了"
    )
    assert not any("未送达" in text for text in _texts_for(journal, head_id)), (
        "首跳收到了『附件未送达』说明 ⇒ 裁件仍在这条路上发生"
    )
    assert asr.calls == [], "原生可达时仍回落 ASR ⇒ 修过头（转译是兜底不是替代）"


@pytest.mark.parametrize("kind", ["audio", "video"])
def test_undeclared_media_is_mounted_for_the_chain_when_translation_is_unavailable(
    tmp_path, kind: str
) -> None:
    """**裁定②主锁**：真实首跳零声明 ⇒ 先转译；**转译也不可用**时唯一允许的"剥掉"档
    仍须把部件挂在请求体上，让逐跳裁件与故障转移去兜（声明过的那一跳真的收到它），
    而不是"既没原生、也没转译"地把内容变没。

    本格用显式「亲密模式 深开」把首跳换成零声明的 grok（裁定①之后 ML 不再换头；
    2026-09-24 R3 A 之后浅档「亲密模式 开」也不换头，只有深档换），
    并且**不给** ASR / 抽帧口（转译不可用）。改码前：门答 False ⇒ 不挂部件 ⇒ 两跳
    都收不到任何音频/视频 ⇒ 内容静默消失、日志零痕迹。
    """
    uid = "940000004" if kind == "audio" else "940000005"
    key = _private_ingest_key(uid)
    cfg = _content_route_config()
    journal: list = []
    # 第一轮：本人显式深开（指令轮不产生 LLM 请求，因此不需要转译口）。
    _run_private_turn(cfg, journal, uid, "亲密模式 深开", [])
    assert SHARED_CONTENT_ROUTE_ENGINE.route_verdict(key, cfg)["mode"] == "intimate"

    # 第二轮：同一个人发一段媒体，且转译口全程缺席（asr/vision/视频理解都没装配）。
    segments = (
        [{"type": "record", "data": {"file": _voice_file(tmp_path)}}]
        if kind == "audio"
        else [{"type": "video", "data": {"file": _video_file(tmp_path)}}]
    )
    _run_private_turn(cfg, journal, uid, "这个你看看", segments)

    hops = [hop for hop, _ in journal]
    assert hops == ["grok-4.6", "gemini-3.8-flash"], hops
    # 零声明的首跳：确实被裁掉，但**留下了痕迹**（模型被明确要求就"没收到"说实话）。
    assert kind not in native_media_kinds_in_payload(journal[0][1])
    assert any("未送达" in text for text in _texts_for(journal, "grok-4.6")), (
        "裁件没留痕迹 ⇒ 首跳会自信地臆答它没收到的附件"
    )
    # 声明过的那一跳必须真的收到它：这才是"剥掉是最后一档、不是默认档"的意思。
    assert kind in native_media_kinds_in_payload(journal[1][1]), (
        f"{kind} 既没原生送达、也没转译 ⇒ 内容静默丢失（裁定②禁止的形态）"
    )
