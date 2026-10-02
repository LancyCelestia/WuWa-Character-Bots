"""S33 波锁：Telegram 视频 / 动图(sendAnimation) / 贴纸替代三族出站腿。

三条判据（缺一即本文件红）：
① 段能构造出**正确 payload**（api 名 + 字节参数名 + 本地转 (名, 字节) 元组、直链原样）。
② 本地件**必经** check_sendable 判定门与 2MiB 限额（摘掉判定门 ⇒ ③ 组里那枚当场红）。
③ 贴纸段走替代路径出口，**绝不静默丢**（旧行为＝只带贴纸的请求落 SKIPPED）。

真发/回执面属真机验收，不在本文件（离线 mock，零外网）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender import nonebot as sender_mod
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    TELEGRAM_MAX_DOCUMENT_BYTES,
    FileTicket,
    get_default_file_gateway,
)
from plugins.bot_unified_runtime.domains.transport.sender.nonebot import (
    plan_telegram_rich_media,
    send_nonebot_message,
    send_telegram_rich_media,
)

_TG_TARGET_ID = "6393538508"


class RecordingTgBot:
    """记录 TG 富媒体调用的假 bot。

    真实适配器上 ``send_video`` / ``send_animation`` / ``send_sticker`` 这三个名字
    由 ``Bot.__getattribute__`` 动态转成 ``call_api``（nonebot/adapters/telegram/
    bot.py:107 + api.py 的 API 类），**不是** Bot 上写死的 def——所以接线只借适配器
    已有的 API 面，绝不自己拼 HTTP（禁第二通路）。
    """

    def __init__(self, *, with_animation: bool = True) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.self_id = "telegram-bot"
        self.adapter = SimpleNamespace(get_name=lambda: "Telegram")
        if not with_animation:
            # 真实场景＝适配器/API 面没有这个出口名（getattr 取不到可调用对象）。
            self.send_animation = None  # type: ignore[assignment]

    async def send_video(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("send_video", kwargs))
        return {"message_id": "video-1"}

    async def send_animation(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("send_animation", kwargs))
        return {"message_id": "anim-1"}

    async def send_photo(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("send_photo", kwargs))
        return {"message_id": "photo-1"}

    async def send_to(self, chat_id: Any, message: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("send_to", {"chat_id": chat_id, "message": message}))
        return {"message_id": "text-1"}


def _mixed_request(parts: list[dict[str, Any]], text: str = "") -> SendRequest:
    return SendRequest(
        request_id="probe2-lock",
        session_id="private:6393538508",
        target_scope=SessionType.PRIVATE,
        target_id=_TG_TARGET_ID,
        origin_message_id="probe2-lock-message",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id="probe2-lock",
            content_type="mixed",
            content_ref={"parts": parts},
            text_fallback=text,
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=f"probe2:{len(parts)}:{text[:8]}",
        cooldown_key="private:6393538508",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_split=True,
        allow_forward=False,
        persona_profile_id="default",
        adapter="telegram",
        bot_id="telegram-bot",
    )


class _StubGateway:
    """stage 返回可控票据：把「限额」这一条判据与「路径域」解耦单测。"""

    def __init__(self, *, size: int, local_path: Path) -> None:
        self._size = size
        self._path = local_path
        self.staged: list[str] = []

    def stage(self, src: Any, *, request_id: str = "") -> FileTicket:
        self.staged.append(str(src.path))
        return FileTicket(
            ticket_id="ft_stub",
            local_path=self._path,
            name=src.name or self._path.name,
            size=self._size,
            sha256="0" * 64,
            source="path",
        )


# ---------------------------------------------------------------- ① payload 形状

@pytest.mark.parametrize(
    ("part", "expected_api", "expected_source"),
    [
        ({"type": "video", "file": "/x/a.mp4"}, "send_video", "local"),
        ({"type": "video", "file": "/x/a.gif"}, "send_animation", "local"),
        ({"type": "animation", "file": "/x/a.mp4"}, "send_animation", "local"),
        ({"type": "gif", "url": "https://cdn.example.com/t/a.gif"}, "send_animation", "remote"),
        (
            {"type": "video", "url": "https://cdn.example.com/path/movie.mp4?sig=1"},
            "send_video",
            "remote",
        ),
        # 贴纸：Telegram 硬约束＝必须属于已建 sticker set，任意图片不可直发 ⇒
        # 本腿给替代出口（动图→animation，静图→photo），且**必须有出口**。
        ({"type": "sticker", "file": "/x/poke.gif"}, "send_animation", "local"),
        ({"type": "sticker", "file": "/x/poke.png"}, "send_photo", "local"),
        ({"type": "sticker", "url": "https://cdn.example.com/s/a.webp"}, "send_photo", "remote"),
    ],
)
def test_plan_picks_the_right_telegram_api(
    part: dict[str, Any], expected_api: str, expected_source: str
) -> None:
    api, reference, source = plan_telegram_rich_media(part)
    assert (api, source) == (expected_api, expected_source)
    assert reference == (part.get("file") or part.get("url"))


def test_plan_rejects_unknown_and_empty_parts() -> None:
    assert plan_telegram_rich_media({"type": "image", "file": "/x/a.png"}) == ("", "", "")
    assert plan_telegram_rich_media({"type": "video", "file": ""}) == ("", "", "")
    assert plan_telegram_rich_media({"type": "voice", "file": "/x/a.ogg"}) == ("", "", "")


@pytest.mark.asyncio
async def test_local_video_send_payload_is_name_and_bytes(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake-mp4-bytes")
    bot = RecordingTgBot()
    gateway = _StubGateway(size=clip.stat().st_size, local_path=clip)

    result = await send_telegram_rich_media(
        bot,
        {"type": "video", "file": str(clip), "name": "clip.mp4"},
        request_id="probe2-lock",
        chat_id=_TG_TARGET_ID,
        caption="随件一句话",
        gateway=gateway,  # type: ignore[arg-type]
    )

    assert result == {"message_id": "video-1"}
    api, kwargs = bot.calls[0]
    assert api == "send_video"
    assert kwargs["chat_id"] == _TG_TARGET_ID
    assert kwargs["caption"] == "随件一句话"
    name, data = kwargs["video"]
    assert (name, data) == ("clip.mp4", b"fake-mp4-bytes")
    assert gateway.staged == [str(clip)]


@pytest.mark.asyncio
async def test_remote_animation_passes_url_unchanged() -> None:
    bot = RecordingTgBot()
    await send_telegram_rich_media(
        bot,
        {"type": "animation", "url": "https://cdn.example.com/a.gif"},
        request_id="probe2-lock",
        chat_id=_TG_TARGET_ID,
        caption="",
        gateway=_StubGateway(size=1, local_path=Path(__file__)),  # type: ignore[arg-type]
    )
    api, kwargs = bot.calls[0]
    assert api == "send_animation"
    assert kwargs["animation"] == "https://cdn.example.com/a.gif"
    assert kwargs["caption"] is None


# ---------------------------------------------------------------- ② 判定门与限额

@pytest.mark.asyncio
async def test_over_two_mebibit_is_denied_before_any_byte_is_sent(tmp_path: Path) -> None:
    clip = tmp_path / "big.mp4"
    clip.write_bytes(b"x")
    bot = RecordingTgBot()
    gateway = _StubGateway(size=TELEGRAM_MAX_DOCUMENT_BYTES + 1, local_path=clip)

    with pytest.raises(sender_mod._FinalSendError) as raised:
        await send_telegram_rich_media(
            bot,
            {"type": "video", "file": str(clip)},
            request_id="probe2-lock",
            chat_id=_TG_TARGET_ID,
            caption="",
            gateway=gateway,  # type: ignore[arg-type]
        )
    assert str(raised.value) == "telegram_media_too_large"
    assert bot.calls == []


@pytest.mark.asyncio
async def test_executable_is_denied(tmp_path: Path) -> None:
    """可执行/脚本形态永不出站（名册真身＝restricted_runner.DENIED_EXTENSIONS）。"""
    fake = tmp_path / "payload.exe"
    fake.write_bytes(b"MZ")
    bot = RecordingTgBot()
    gateway = _StubGateway(size=fake.stat().st_size, local_path=fake)

    with pytest.raises(sender_mod._FinalSendError) as raised:
        await send_telegram_rich_media(
            bot,
            {"type": "video", "file": str(fake)},
            request_id="probe2-lock",
            chat_id=_TG_TARGET_ID,
            caption="",
            gateway=gateway,  # type: ignore[arg-type]
        )
    assert "executable" in str(raised.value)
    assert bot.calls == []


@pytest.mark.asyncio
async def test_local_media_must_pass_the_check_sendable_gate(tmp_path: Path) -> None:
    """钉死「新通路必经中央判定门」：真网关 + 允许根之外的落点 ⇒ 终态拒绝、零出网。

    注毒靶：把 ``send_telegram_rich_media`` 里的 ``gateway.stage(...)`` 摘掉
    （改为直接按 Part 路径读字节）⇒ 本枚当场红（不再点名 path_domain_denied）。
    """
    outside = tmp_path / "not-in-allowed-roots.mp4"
    outside.write_bytes(b"nope")
    bot = RecordingTgBot()

    receipt = await send_nonebot_message(
        bot, None, _mixed_request([{"type": "video", "file": str(outside)}], "")
    )

    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "path_domain_denied"
    assert bot.calls == []


@pytest.mark.asyncio
async def test_telegram_api_absent_is_named_not_silently_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """适配器缺该出口 ⇒ 点名 send_animation_unavailable，绝不把「没发」记成「发了」。"""
    monkeypatch.setattr(sender_mod, "plan_telegram_rich_media", _allow_all_plan)
    bot = RecordingTgBot(with_animation=False)

    with pytest.raises(sender_mod._FinalSendError) as raised:
        await send_telegram_rich_media(
            bot,
            {"type": "animation", "url": "https://cdn.example.com/a.gif"},
            request_id="probe2-lock",
            chat_id=_TG_TARGET_ID,
            caption="",
            gateway=_StubGateway(size=1, local_path=Path(__file__)),  # type: ignore[arg-type]
        )
    assert "send_animation" in str(raised.value)


def _allow_all_plan(part: dict[str, Any]) -> tuple[str, str, str]:
    return ("send_animation", str(part.get("url") or part.get("file") or ""), "remote")


# ---------------------------------------------------------------- ③ 端到端不静默丢

@pytest.mark.asyncio
async def test_sticker_only_request_is_sent_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """旧行为＝只带贴纸、无正文 ⇒ SKIPPED（她什么都没收到、日志也无声）。"""
    sticker = tmp_path / "sticker.gif"
    sticker.write_bytes(b"GIF89a")
    monkeypatch.setattr(
        sender_mod,
        "get_default_file_gateway",
        lambda: _StubGateway(size=sticker.stat().st_size, local_path=sticker),
    )
    bot = RecordingTgBot()

    receipt = await send_nonebot_message(
        bot, None, _mixed_request([{"type": "sticker", "file": str(sticker)}], "")
    )

    assert receipt.state is ReceiptState.SENT
    assert [name for name, _ in bot.calls] == ["send_animation"]
    assert receipt.provider_message_id == "anim-1"


@pytest.mark.asyncio
async def test_video_part_with_text_sends_animation_and_no_duplicate_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = tmp_path / "a.gif"
    clip.write_bytes(b"GIF89a")
    monkeypatch.setattr(
        sender_mod,
        "get_default_file_gateway",
        lambda: _StubGateway(size=clip.stat().st_size, local_path=clip),
    )
    bot = RecordingTgBot()

    receipt = await send_nonebot_message(
        bot, None, _mixed_request([{"type": "video", "file": str(clip)}], "就这一句")
    )

    assert receipt.state is ReceiptState.SENT
    assert [name for name, _ in bot.calls] == ["send_animation"]
    assert bot.calls[0][1]["caption"] == "就这一句"
    # 正文已随件发出 ⇒ 不得再单发一轮（重投/重复骚扰面为零）。
    assert "send_to" not in [name for name, _ in bot.calls]


def test_default_gateway_is_the_shared_throat() -> None:
    """新通路复用进程级默认网关（不建第二条通道、不建第二本账）。"""
    assert get_default_file_gateway() is get_default_file_gateway()
