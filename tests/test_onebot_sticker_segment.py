"""S-MEME-MFACE（2026-09-29）：出站贴纸段构段的离线锁（需求 12 的发送腿）。

上一波的洞：``onebot.py`` 里 ``mface`` 零命中 ⇒ 表情贴纸只有「当普通图发」一条路。
本波把通道接上，同时钉死两条口径：

1. **绝不自己拼 ``emoji_id``**：QQ 表情 id 属于协议端表情包，凭空造一枚＝协议端整条
   拒发（「想发却发不出」是用户点名的禁形）。Task A 探测波（2026-09-29，读本机
   SnowLuma v1.14.19-node bundle 的发送侧校验）把这条硬门从初稿的「纯数字串」**改
   成协议端实际认的那把尺：恰好 32 位 hex**（``/^[0-9a-fA-F]{32}$/``）——数字短串
   在协议端同样吃 INVALID_FIELD 整条拒发，按旧尺放行反而是「本地放行、线上炸」；
2. **没有 id 就诚实回落 image 段**（现役贴纸通路逐字节不变），回落时记一条
   ``sticker_via_image_segment_fallback=true`` 观测行；两样都没有 ⇒ 丢段交观测面，
   绝不出空段、也绝不把死路径送上线（M-38 那道闸同尺）。

死引用判定面必须把贴纸一起管起来：贴纸部件带本地绝对路径时同样进
``_mixed_dead_local_file_types``，否则「构段跳过、回执仍报 SENT」的旧假成功会换个
类型名复活。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    _mixed_dead_local_file_types,
    _segment_from_mixed_part,
    _sticker_segment,
)

# 收侧 image 段上挂的真实 ``data.emoji_id`` 形态（MarketFace.faceId 的 hex GUID）。
NATIVE_EMOJI_ID = "04d9d0b1c22d4a54a21e45143f92bcac"


def test_emoji_id_from_payload_becomes_mface_segment() -> None:
    segment = _segment_from_mixed_part(
        {
            "type": "sticker",
            "emoji_id": NATIVE_EMOJI_ID,
            "emoji_package_id": "201",
            "summary": "开心",
        }
    )
    assert segment == {
        "type": "mface",
        "data": {
            "emoji_id": NATIVE_EMOJI_ID,
            "emoji_package_id": "201",
            "summary": "开心",
        },
    }


def test_mface_part_type_is_accepted_under_both_names() -> None:
    for name in ("mface", "sticker"):
        segment = _segment_from_mixed_part({"type": name, "emoji_id": NATIVE_EMOJI_ID})
        assert segment is not None and segment["type"] == "mface"


def test_no_id_never_fabricates_mface_and_falls_back_to_image(tmp_path: Path) -> None:
    """没给 emoji_id ⇒ 绝不拼一枚假的；有本地真图就按 image 段发（现役通路）。"""
    real = tmp_path / "sticker.png"
    real.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
    segment = _sticker_segment({"type": "sticker", "file": str(real)})
    assert segment is not None and segment["type"] == "image"
    assert segment["data"]["file"] == str(real.resolve())


def test_malformed_id_is_refused_not_guessed(tmp_path: Path) -> None:
    """``emoji_id`` 不是 32 位 hex＝载荷不可信：不退而求其次瞎发，走 image 面或丢段。

    短数字串（初稿误尺放行的形态）与注入串一样必须在本地就被拦下——SnowLuma 发送
    侧校验（assertValidMessageElements，方向 W）对不合形的 emojiId 抛 INVALID_FIELD、
    **整条消息拒发**，本地拦是唯一不连累同消息文字部件的位置。
    """
    assert _sticker_segment({"type": "sticker", "emoji_id": "abc; rm -rf"}) is None
    assert _sticker_segment({"type": "sticker", "emoji_id": "12345"}) is None, (
        "纯数字短串过了本地门＝旧『纯数字』尺复活，协议端会整条拒发"
    )
    assert _sticker_segment({"type": "sticker", "emoji_id": NATIVE_EMOJI_ID + "0"}) is None
    real = tmp_path / "s.png"
    real.write_bytes(b"\x89PNG\r\n\x1a\n" + b"y" * 32)
    downgraded = _sticker_segment({"type": "sticker", "emoji_id": "NaN", "file": str(real)})
    assert downgraded is not None and downgraded["type"] == "image"


def test_uppercase_hex_id_is_accepted() -> None:
    """bundle 校验是 ``[0-9a-fA-F]`` 大小写都收 ⇒ 本地尺不得偷偷只认小写。"""
    segment = _sticker_segment({"type": "sticker", "emoji_id": NATIVE_EMOJI_ID.upper()})
    assert segment is not None and segment["type"] == "mface"


def test_dead_or_missing_everything_yields_no_segment() -> None:
    assert _sticker_segment({"type": "sticker"}) is None
    assert _sticker_segment({"type": "sticker", "file": "C:/nope/ghost.png"}) is None, (
        "死绝对路径仍然构段 ⇒ M-38 那道闸在贴纸上漏了一格"
    )


def test_sticker_parts_join_the_dead_local_file_audit(tmp_path: Path) -> None:
    """贴纸部件的死路径必须进终败/留痕面（与 record/video/file/image 同一把尺）。"""
    request = _mixed_request([{"type": "sticker", "file": "C:/nope/ghost.png"}])
    assert _mixed_dead_local_file_types(request) == ["sticker"]
    live = tmp_path / "ok.png"
    live.write_bytes(b"\x89PNG\r\n\x1a\n" + b"z" * 32)
    assert _mixed_dead_local_file_types(_mixed_request([{"type": "sticker", "file": str(live)}])) == []


def _mixed_request(parts: list[dict[str, Any]]) -> SendRequest:
    """造一条 mixed 出站请求（只喂本件要的三面：content_type/content_ref/text_fallback）。"""
    rendered = RenderedOutput(
        request_id="req-sticker-1",
        content_type="mixed",
        content_ref={"parts": parts},
        text_fallback="",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id="req-sticker-1",
        session_id="group:g-1",
        target_scope=SessionType.GROUP,
        target_id="g-1",
        capability_id="bot.meme_library",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="dedupe-req-sticker-1",
        cooldown_key="bot.meme_library:group:g-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        allow_forward=False,
        adapter="onebot",
        bot_id="qq-bot",
    )
