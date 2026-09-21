"""审查 F-03（收窄口径）：系统生成的通知/告警文本出站前统一脱敏。

原案「send_queue 提交前统一收口」因误伤风险（闲聊回复合法提及 token 形态会被
打码）改收窄：只治理系统生成的通知/告警文本——其特征是内插原始异常串
（str(exc) 可能带内网 URL/键值形态）且不含用户创作内容，脱敏零误伤。

覆盖面：
- runtime/alerts.py 告警文本构建与管理员告警 SendRequest 收口；
- sender/nonebot.py _FinalSendError 分支（kind/safe_summary 进系统通知）；
- capabilities/download.py 失败文案回显「原链接」。

硬边界：聊天回复链零改动（聊天回复的既有脱敏在 capabilities/chat.py 自有
链路，不经本批改动点）。
"""
from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.capabilities.download import build_download_capability
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    OperationalIssue,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
    AdminTarget,
    build_admin_alert_send_request,
    build_operational_alert_text,
)
from plugins.bot_unified_runtime.domains.transport.sender import (
    file_gateway as file_gateway_module,
)
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    FinalTransferError,
)
from plugins.bot_unified_runtime.sender.nonebot import send_nonebot_message
from plugins.bot_unified_runtime.sources.downloader import DownloadOutcome

# 长度钉在 48 字节内：nonebot 侧 kind/safe_summary 取 str(exc)[:48]，
# 两种敏感形态（URL userinfo + 裸键值对）都必须完整落在截断窗口内。
_LEAKY_SHORT = "https://u:p@internal.host/s sendkey=abcdefgh1234"
_LEAKY_FULL = "https://user:secret@internal.host/api sendkey=abcdefgh1234"


# ---------------- runtime/alerts.py ----------------


def test_operational_alert_text_redacts_interpolated_secrets() -> None:
    """safe_summary 内插的 URL userinfo/键值形态进告警文本前必须打码。"""
    issue = OperationalIssue(
        stage="send",
        kind="send_failed_final",
        retryable=False,
        safe_summary=f"auth failed {_LEAKY_SHORT}",
    )
    text = build_operational_alert_text(
        issue,
        source_adapter="onebot",
        source_bot="bot-1",
        session_type=SessionType.PRIVATE,
    )
    assert "u:p@" not in text
    assert "abcdefgh1234" not in text
    assert "<已隐藏>" in text
    # 非敏感骨架信息保持可读（host 保留，人仍能看出泄漏发生在哪）。
    assert "internal.host/s" in text


def test_operational_alert_text_keeps_plain_summary() -> None:
    """普通文本不误伤：既有告警字段逐字保留。"""
    issue = OperationalIssue(
        stage="llm",
        kind="timeout",
        retryable=True,
        attempts=2,
        safe_summary="upstream_timeout",
    )
    text = build_operational_alert_text(
        issue,
        source_adapter="onebot",
        source_bot="bot-1",
        session_type=SessionType.PRIVATE,
    )
    assert "kind=timeout" in text
    assert "detail=upstream_timeout" in text
    assert "attempts=2" in text


def test_admin_alert_send_request_redacts_outbound_text() -> None:
    """管理员告警出站收口：SendRequest 内容里的敏感形态必须打码。"""
    target = AdminTarget(adapter="onebot", bot_id="bot-1", target_id="10001")
    request = build_admin_alert_send_request(target, f"凭据失效 {_LEAKY_FULL}")
    fallback = str(request.content.text_fallback or "")
    assert "user:secret" not in fallback
    assert "abcdefgh1234" not in fallback
    assert "<已隐藏>" in fallback
    content_ref_text = str(request.content.content_ref.get("text", ""))
    assert "user:secret" not in content_ref_text


def test_admin_alert_send_request_keeps_plain_text() -> None:
    """普通文本不误伤：无敏感形态时出站内容逐字不变。"""
    target = AdminTarget(adapter="onebot", bot_id="bot-1", target_id="10001")
    plain = "队列积压 12 条，请检查 NapCat 连接"
    request = build_admin_alert_send_request(target, plain)
    assert request.content.text_fallback == plain


# ---------------- sender/nonebot.py ----------------


class _FakeAdapter:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


class _TelegramStubBot:
    """files 分支在 gateway.stage 就抛终态异常，bot API 不会被触达。"""

    def __init__(self) -> None:
        self.adapter = _FakeAdapter("telegram")
        self.self_id = "telegram-bot"


class _RaisingGateway:
    def __init__(self, message: str) -> None:
        self._message = message

    def stage(self, src: object, *, request_id: str = "") -> object:
        raise FinalTransferError(self._message)

    def deliver(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("deliver must not be reached when stage fails")


def _telegram_file_request() -> SendRequest:
    return SendRequest(
        request_id="req-f03",
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        origin_message_id="message-1",
        capability_id="bot.admin_alert",
        content=RenderedOutput(
            request_id="req-f03",
            content_type="text",
            content_ref={
                "parts": [
                    {"type": "file", "file": "Z:/missing/video.mp4", "name": "video.mp4"}
                ]
            },
            text_fallback="",
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="bot.admin_alert:private:user-1:message-1",
        cooldown_key="admin_alert:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        allow_split=False,
        allow_forward=False,
        persona_profile_id="default",
        adapter="telegram",
        bot_id="telegram-bot",
    )


@pytest.mark.asyncio
async def test_final_send_error_notice_fields_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """_FinalSendError 文本进 OperationalIssue(kind/safe_summary) 前必须打码。

    这两个字段随后内插进管理员告警等系统通知文本（alerts 告警行 + 私聊
    调试文本），是 F-03 收窄口径下的系统通知字段。
    """
    monkeypatch.setattr(
        file_gateway_module, "_default_gateway", _RaisingGateway(_LEAKY_SHORT)
    )
    receipt = await send_nonebot_message(
        _TelegramStubBot(), object(), _telegram_file_request()
    )
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.public_message == ""
    issue = receipt.operational_issue
    assert issue is not None
    assert "u:p@" not in issue.kind
    assert "abcdefgh1234" not in issue.kind
    assert "<已隐藏>" in issue.kind
    assert "u:p@" not in issue.safe_summary
    assert "abcdefgh1234" not in issue.safe_summary


@pytest.mark.asyncio
async def test_final_send_error_fixed_kind_is_not_mangled(monkeypatch: pytest.MonkeyPatch) -> None:
    """普通固定 kind 串不误伤：file_gateway 既有失败分类逐字保留。"""
    monkeypatch.setattr(
        file_gateway_module,
        "_default_gateway",
        _RaisingGateway("invalid generated attachment"),
    )
    receipt = await send_nonebot_message(
        _TelegramStubBot(), object(), _telegram_file_request()
    )
    issue = receipt.operational_issue
    assert issue is not None
    assert issue.kind == "invalid generated attachment"
    assert issue.safe_summary == "invalid generated attachment"


# ---------------- capabilities/download.py ----------------


class _FailingDownloader:
    def available(self) -> bool:
        return True

    def download(self, url: str) -> DownloadOutcome:
        return DownloadOutcome(error="HTTP 401 upstream", path="")


def _download_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id="private:10001",
        session_type=SessionType.PRIVATE,
        sender_id="10001",
        plain_text=text,
        mentions_bot=True,
    )


def test_download_failure_body_redacts_url_credentials() -> None:
    """失败文案回显「原链接」：URL userinfo 凭据形态出站前必须打码。"""
    capability = build_download_capability(downloader=_FailingDownloader())
    result = capability(
        _download_message("下载 https://user:secret@host/video.mp4"), None
    )
    assert "user:secret" not in result.body
    assert "<已隐藏>" in result.body
    # 分类后的中文原因与回显骨架保持不变。
    assert "这次没下载成功" in result.body
    assert "原链接：https://<已隐藏>@host/video.mp4" in result.body


def test_download_failure_body_keeps_plain_url() -> None:
    """普通 URL 不误伤：无凭据形态时回显逐字不变。"""
    capability = build_download_capability(downloader=_FailingDownloader())
    result = capability(
        _download_message("下载 https://example.com/video.mp4"), None
    )
    assert "原链接：https://example.com/video.mp4" in result.body
    assert "<已隐藏>" not in result.body
