from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime import _register_send_queue_scheduler
from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.sender.nonebot import send_nonebot_message
from plugins.bot_unified_runtime.sender.onebot import send_onebot_v11
from plugins.bot_unified_runtime.sender.queue import QueuedSendRequest


def test_non_onebot_handlers_use_transport_dispatcher() -> None:
    source_path = Path(__file__).parents[1] / "plugins" / "bot_unified_runtime" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    handler_names = {
        "_handle_content",
        "_handle_music",
        "_handle_today_history",
        "_run_simple_capability",
        "_handle_meme_library",
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in handler_names:
            continue
        forbidden = [
            call
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_deliver_onebot_send_request"
        ]
        assert not forbidden, f"{node.name} must dispatch through adapter-aware transport"
class FakeAdapter:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


class FakeBot:
    def __init__(self, adapter_name: str, self_id: str) -> None:
        self.adapter = FakeAdapter(adapter_name)
        self.self_id = self_id
        self.send_calls: list[tuple[object, str, dict[str, object]]] = []
        self.send_to_calls: list[tuple[str, str]] = []
        self.send_mail_calls: list[object] = []
        self.bot_info = SimpleNamespace(
            id=self_id,
            name="守岸人 QQ邮箱",
        )

    async def send(self, event: object, message: str, **kwargs: object) -> dict[str, str]:
        self.send_calls.append((event, message, kwargs))
        return {"message_id": "event-message-1"}

    async def send_to(self, target_id: str, message: str) -> dict[str, str]:
        self.send_to_calls.append((str(target_id), message))
        return {"id": "direct-message-1"}

    async def send_mail(self, message: object) -> dict[str, str]:
        self.send_mail_calls.append(message)
        return {"message_id": "mail-message-1"}


class FailingBot(FakeBot):
    async def send(self, event: object, message: str, **kwargs: object) -> dict[str, str]:
        raise RuntimeError("secret transport detail")


def _send_request(*, adapter: str = "telegram", bot_id: str = "telegram-bot") -> SendRequest:
    return SendRequest(
        request_id="req-1",
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        origin_message_id="message-1",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id="req-1",
            content_type="text",
            content_ref={},
            text_fallback="你好",
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="bot.chat:private:user-1:message-1",
        cooldown_key="private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_split=False,
        allow_forward=False,
        persona_profile_id="default",
        adapter=adapter,
        bot_id=bot_id,
    )


@pytest.mark.asyncio
async def test_telegram_immediate_send_uses_event_send() -> None:
    bot = FakeBot("Telegram", "telegram-bot")
    event = object()

    receipt = await send_nonebot_message(bot, event, _send_request())

    assert receipt.state is ReceiptState.SENT
    assert bot.send_calls == [(event, "你好", {})]
    assert bot.send_to_calls == []
    assert receipt.provider_message_id == "event-message-1"


@pytest.mark.asyncio
async def test_mail_immediate_send_builds_rfc5322_reply() -> None:
    bot = FakeBot("Mail", "qq@example.com")
    event = SimpleNamespace(
        id="<incoming@example.com>",
        subject="测试主题",
        sender=SimpleNamespace(id="sender@example.com"),
    )

    receipt = await send_nonebot_message(
        bot,
        event,
        _send_request(adapter="mail", bot_id="qq@example.com"),
    )

    assert receipt.state is ReceiptState.SENT
    assert bot.send_calls == []
    assert receipt.provider_message_id == "mail-message-1"
    message = bot.send_mail_calls[0]
    assert message["From"] == "守岸人 QQ邮箱 <qq@example.com>"
    assert message["To"] == "sender@example.com"
    assert message["In-Reply-To"] == "<incoming@example.com>"
    assert message["References"] == "<incoming@example.com>"


@pytest.mark.asyncio
async def test_nonebot_queue_send_uses_adapter_send_to_without_event() -> None:
    bot = FakeBot("Telegram", "telegram-bot")

    receipt = await send_nonebot_message(bot, None, _send_request())

    assert receipt.state is ReceiptState.SENT
    assert bot.send_calls == []
    assert bot.send_to_calls == [("user-1", "你好")]
    assert receipt.provider_message_id == "direct-message-1"


@pytest.mark.asyncio
async def test_nonebot_send_failure_hides_exception_type_from_public_message() -> None:
    bot = FailingBot("Telegram", "telegram-bot")

    receipt = await send_nonebot_message(bot, object(), _send_request())

    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.stage == "telegram"
    assert "RuntimeError" not in receipt.public_message
    assert "secret transport detail" not in receipt.public_message


class HangingBot(FakeBot):
    async def send(self, event: object, message: str, **kwargs: object) -> dict[str, str]:
        await asyncio.sleep(10)
        return {"message_id": "late"}


class HangingOneBot:
    async def send_private_msg(self, **kwargs: object) -> object:
        await asyncio.sleep(10)
        return {"message_id": "late"}

    async def send_group_msg(self, **kwargs: object) -> object:
        await asyncio.sleep(10)
        return {"message_id": "late"}


@pytest.mark.asyncio
async def test_onebot_send_timeout_returns_result_unknown_without_retry() -> None:
    receipt = await send_onebot_v11(
        HangingOneBot(),
        _send_request(adapter="onebot", bot_id="qq"),
        timeout_seconds=0.01,
    )

    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "result_unknown"


@pytest.mark.asyncio
async def test_nonebot_send_timeout_returns_silent_operational_receipt() -> None:
    receipt = await send_nonebot_message(
        HangingBot("Telegram", "telegram-bot"),
        object(),
        _send_request(),
        timeout_seconds=0.01,
    )

    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "result_unknown"


class FakeScheduler:
    def __init__(self) -> None:
        self.job = None

    def add_job(self, job, *args, **kwargs) -> None:
        self.job = job


class FakeQueue:
    def __init__(self, send_request: SendRequest) -> None:
        now = datetime.now(timezone.utc)
        self.entries = [
            QueuedSendRequest(
                send_request=send_request,
                state=ReceiptState.QUEUED,
                retry_count=0,
                next_retry_at=None,
                created_at=now,
                updated_at=now,
            )
        ]
        self.sent: list[str] = []

    def list_due(self, *, now=None, limit=20):
        return self.entries[:limit]

    def mark_sent(self, request_id: str, public_message: str = "sent", *, now=None):
        self.sent.append(request_id)
        return DeliveryReceipt(
            request_id=request_id,
            state=ReceiptState.SENT,
            transport="sqlite_queue",
            public_message=public_message,
        )

    def mark_retryable_failure(self, request_id: str, public_message: str, *, now=None):
        return DeliveryReceipt(
            request_id=request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport="sqlite_queue",
            public_message=public_message,
        )

    def mark_final_failure(self, request_id: str, public_message: str, *, now=None):
        return DeliveryReceipt(
            request_id=request_id,
            state=ReceiptState.FAILED_FINAL,
            transport="sqlite_queue",
            public_message=public_message,
        )


@pytest.mark.asyncio
async def test_queue_worker_routes_telegram_request_to_matching_bot_and_send_to() -> None:
    send_request = _send_request(adapter="telegram", bot_id="telegram-bot")
    queue = FakeQueue(send_request)
    scheduler = FakeScheduler()
    telegram_bot = FakeBot("Telegram", "telegram-bot")
    mail_bot = FakeBot("Mail", "qq@example.com")
    config = SimpleNamespace(
        bot_send_queue_worker_enabled=True,
        bot_send_queue_worker_interval_seconds=1,
        bot_send_queue_worker_batch_size=10,
    )

    result = _register_send_queue_scheduler(
        scheduler=scheduler,
        config=config,
        send_queue=queue,
        audit_logger=InMemoryAuditLogger(),
        receipt_repository=None,
        bot_provider=lambda: {
            "telegram": telegram_bot,
            "mail": mail_bot,
        },
    )

    assert result["registered"] is True
    assert scheduler.job is not None
    await scheduler.job()

    assert queue.sent == ["req-1"]
    assert telegram_bot.send_to_calls == [("user-1", "你好")]
    assert telegram_bot.send_calls == []
    assert mail_bot.send_to_calls == []


@pytest.mark.asyncio
async def test_queue_worker_routes_mail_request_to_matching_bot_and_send_to() -> None:
    send_request = _send_request(adapter="mail", bot_id="qq@example.com")
    queue = FakeQueue(send_request)
    scheduler = FakeScheduler()
    telegram_bot = FakeBot("Telegram", "telegram-bot")
    mail_bot = FakeBot("Mail", "qq@example.com")
    config = SimpleNamespace(
        bot_send_queue_worker_enabled=True,
        bot_send_queue_worker_interval_seconds=1,
        bot_send_queue_worker_batch_size=10,
    )

    _register_send_queue_scheduler(
        scheduler=scheduler,
        config=config,
        send_queue=queue,
        audit_logger=InMemoryAuditLogger(),
        receipt_repository=None,
        bot_provider=lambda: {
            "telegram": telegram_bot,
            "mail": mail_bot,
        },
    )

    await scheduler.job()

    assert queue.sent == ["req-1"]
    assert mail_bot.send_to_calls == [("user-1", "你好")]
    assert mail_bot.send_calls == []
    assert telegram_bot.send_to_calls == []


class FakeTelegramMediaBot(FakeBot):
    """记录 TG 媒体调用的假 bot；send_photo/voice/audio 在真实适配器上动态转发。"""

    def __init__(self, adapter_name: str = "Telegram", self_id: str = "telegram-bot") -> None:
        super().__init__(adapter_name, self_id)
        self.media_calls: list[tuple[str, dict[str, object]]] = []

    async def send_photo(self, chat_id=None, photo=None, caption=None, **kwargs: object):
        self.media_calls.append(
            ("send_photo", {"chat_id": chat_id, "photo": photo, "caption": caption})
        )
        return {"message_id": "photo-1"}

    async def send_voice(self, chat_id=None, voice=None, **kwargs: object):
        self.media_calls.append(("send_voice", {"chat_id": chat_id, "voice": voice}))
        return {"message_id": "voice-1"}

    async def send_audio(self, chat_id=None, audio=None, **kwargs: object):
        self.media_calls.append(("send_audio", {"chat_id": chat_id, "audio": audio}))
        return {"message_id": "audio-1"}


def _media_send_request(parts: list[dict[str, object]], text: str) -> SendRequest:
    base = _send_request()
    return base.model_copy(
        update={
            "content": RenderedOutput(
                request_id="req-1",
                content_type="mixed",
                content_ref={"parts": parts},
                text_fallback=text,
                privacy_level=PrivacyLevel.PERSONAL,
            )
        }
    )


@pytest.mark.asyncio
async def test_telegram_local_card_image_sends_photo_without_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = tmp_path / "help.png"
    card.write_bytes(b"png-bytes")
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sender.nonebot._TG_VOICE_CACHE_DIR",
        tmp_path / "vcache",
    )
    bot = FakeTelegramMediaBot()

    receipt = await send_nonebot_message(
        bot, None, _media_send_request([{"type": "image", "file": str(card)}], "")
    )

    assert receipt.state is ReceiptState.SENT
    assert bot.media_calls == [
        ("send_photo", {"chat_id": "user-1", "photo": str(card), "caption": None})
    ]


@pytest.mark.asyncio
async def test_telegram_music_sends_cover_then_voice_degrades_to_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = tmp_path / "clip.mp3"
    clip.write_bytes(b"mp3-bytes")
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sender.nonebot._TG_VOICE_CACHE_DIR",
        tmp_path / "vcache",
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sender.nonebot.shutil.which", lambda name: None
    )
    bot = FakeTelegramMediaBot()

    receipt = await send_nonebot_message(
        bot,
        None,
        _media_send_request(
            [
                {"type": "record", "file": str(clip)},
                {"type": "image", "url": "https://example.com/cover.jpg"},
            ],
            "♪ 我与你\n歌手：auburn",
        ),
    )

    assert receipt.state is ReceiptState.SENT
    assert [name for name, _ in bot.media_calls] == ["send_photo", "send_audio"]
    assert bot.media_calls[0][1]["caption"] == "♪ 我与你\n歌手：auburn"
    assert bot.media_calls[1][1]["audio"] == str(clip)


@pytest.mark.asyncio
async def test_telegram_voice_converts_to_ogg_for_sendvoice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = tmp_path / "clip.mp3"
    clip.write_bytes(b"mp3-bytes")
    cache = tmp_path / "vcache"
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sender.nonebot._TG_VOICE_CACHE_DIR", cache
    )

    def fake_convert(source: Path, target: Path) -> bool:
        cache.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"ogg-bytes")
        return True

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sender.nonebot._convert_audio_to_ogg", fake_convert
    )
    bot = FakeTelegramMediaBot()

    receipt = await send_nonebot_message(
        bot, None, _media_send_request([{"type": "record", "file": str(clip)}], "")
    )

    assert receipt.state is ReceiptState.SENT
    assert bot.media_calls[0][0] == "send_voice"
    voice_ref = str(bot.media_calls[0][1]["voice"])
    assert voice_ref.endswith(".ogg")
    assert Path(voice_ref).is_file()


@pytest.mark.asyncio
async def test_telegram_photo_failure_falls_back_to_text_send() -> None:
    class NoPhotoBot(FakeBot):
        async def send_photo(self, **kwargs: object):
            raise RuntimeError("telegram rejected photo")

    bot = NoPhotoBot("Telegram", "telegram-bot")

    receipt = await send_nonebot_message(
        bot,
        None,
        _media_send_request(
            [{"type": "image", "url": "https://example.com/cover.jpg"}], "纯文本兜底"
        ),
    )

    assert receipt.state is ReceiptState.SENT
    assert bot.send_to_calls == [("user-1", "纯文本兜底")]


@pytest.mark.asyncio
async def test_telegram_unsendable_media_without_text_is_failure_not_silence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sender.nonebot._TG_VOICE_CACHE_DIR",
        tmp_path / "vcache",
    )
    missing = tmp_path / "missing.mp3"
    bot = FakeTelegramMediaBot()

    receipt = await send_nonebot_message(
        bot, None, _media_send_request([{"type": "record", "file": str(missing)}], "")
    )

    assert receipt.state is ReceiptState.FAILED_RETRYABLE
    assert receipt.operational_issue is not None
