"""可配置 transport timeout（handover 9.1）：config 校验、runtime 热更转换、发送层取最小值。"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.runtime.settings import (
    SETTABLE_KEYS,
    RuntimeSettingsStore,
)
from plugins.bot_unified_runtime.sender.timeout import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
    resolve_transport_timeout,
    set_transport_timeout_provider,
)


@pytest.fixture(autouse=True)
def _reset_provider() -> None:
    set_transport_timeout_provider(None)
    yield
    set_transport_timeout_provider(None)


def test_config_rejects_invalid_transport_timeout() -> None:
    from pydantic import ValidationError

    for bad in (-1, 0, -0.5, float("nan"), float("inf"), 601, "abc"):
        with pytest.raises(ValidationError):
            Config(bot_transport_timeout_seconds=bad)


def test_config_accepts_valid_transport_timeout() -> None:
    assert Config().bot_transport_timeout_seconds == 15.0
    assert Config(bot_transport_timeout_seconds=300).bot_transport_timeout_seconds == 300


def test_settings_converter_validates_range(tmp_path: object) -> None:
    converter = SETTABLE_KEYS["BOT_TRANSPORT_TIMEOUT_SECONDS"]
    assert converter("30") == 30.0
    for bad in ("-1", "0", "nan", "inf", "601", "", "abc"):
        with pytest.raises(ValueError):
            converter(bad)


def test_settings_override_hot_reloads(tmp_path: object) -> None:
    store = RuntimeSettingsStore(tmp_path / "settings.json")  # type: ignore[operator]
    config = Config()
    assert store.get("BOT_TRANSPORT_TIMEOUT_SECONDS", config) == 15.0
    store.set_override("BOT_TRANSPORT_TIMEOUT_SECONDS", "20")
    assert store.get("BOT_TRANSPORT_TIMEOUT_SECONDS", config) == 20.0
    with pytest.raises(ValueError):
        store.set_override("BOT_TRANSPORT_TIMEOUT_SECONDS", "-3")


def test_resolve_without_provider_uses_default_or_explicit() -> None:
    assert resolve_transport_timeout(None) == DEFAULT_TIMEOUT_SECONDS
    assert resolve_transport_timeout(5) == 5.0


def test_resolve_reads_provider_and_takes_minimum() -> None:
    set_transport_timeout_provider(lambda: 20.0)
    assert resolve_transport_timeout(None) == 20.0
    # 调用方显式更小值优先；显式更大值被配置钳制。
    assert resolve_transport_timeout(8) == 8.0
    assert resolve_transport_timeout(90) == 20.0


def test_resolve_provider_garbage_falls_back_to_default() -> None:
    for garbage in ("oops", 0, -4, float("nan")):
        set_transport_timeout_provider(lambda g=garbage: g)  # type: ignore[arg-type,return-value]
        assert resolve_transport_timeout(None) == DEFAULT_TIMEOUT_SECONDS
    set_transport_timeout_provider(lambda: 999.0)
    assert resolve_transport_timeout(None) == MAX_TIMEOUT_SECONDS


def test_onebot_sender_applies_configured_timeout() -> None:
    import asyncio
    import time

    from plugins.bot_unified_runtime.contracts import (
        PrivacyLevel,
        ReceiptState,
        RenderedOutput,
        SendPolicy,
        SendRequest,
        SessionType,
    )
    from plugins.bot_unified_runtime.sender.onebot import send_onebot_v11

    set_transport_timeout_provider(lambda: 0.05)

    class _SlowBot:
        async def send_group_msg(self, **kwargs: object) -> None:
            await asyncio.sleep(3)

    request = SendRequest(
        request_id="req-1",
        session_id="group:g-1",
        target_scope=SessionType.GROUP,
        target_id="g-1",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id="req-1",
            content_type="text",
            content_ref={},
            text_fallback="hi",
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="bot.chat:group:g-1",
        cooldown_key="group:g-1",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_split=False,
        allow_forward=False,
        persona_profile_id="default",
        adapter="onebot",
        bot_id="qq-bot",
    )

    async def _run() -> object:
        return await send_onebot_v11(_SlowBot(), request)  # type: ignore[arg-type]

    started = time.monotonic()
    receipt = asyncio.run(_run())
    elapsed = time.monotonic() - started

    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.public_message == ""
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "result_unknown"
    assert elapsed < 2.5
