from plugins.bot_unified_runtime import policy
from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.capabilities.echo import build_status_result
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    ReceiptState,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.runtime import RuntimePipeline
from plugins.bot_unified_runtime.sender import InMemorySendQueue


def make_role_message(sender_id: str = "42") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id=f"private:{sender_id}",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text="你好",
        raw_segments=[{"type": "text", "data": {"text": "你好"}}],
        mentions_bot=True,
    )


def test_config_accepts_json_comma_and_semicolon_role_lists():
    config = Config(
        bot_admin_user_ids='["10001","10002"]',
        bot_enterprise_user_ids="20001,20002",
        bot_trusted_user_ids="30001;30002",
        bot_blocked_user_ids="40001",
    )

    assert config.bot_admin_user_ids == ["10001", "10002"]
    assert config.bot_enterprise_user_ids == ["20001", "20002"]
    assert config.bot_trusted_user_ids == ["30001", "30002"]
    assert config.bot_blocked_user_ids == ["40001"]


def test_policy_blocks_configured_blocked_sender_before_capability():
    message = make_role_message("40001")
    role_settings = policy.build_role_settings(Config(bot_blocked_user_ids=["40001"]))
    message = message.model_copy(update={"sender_roles": role_settings.resolve_roles(message)})

    evaluation = policy.evaluate_policy(message, "bot.chat")

    assert evaluation.allowed is False
    assert evaluation.reason == "sender_blocked"
    assert evaluation.risk_level is RiskLevel.MEDIUM
    assert "role:blocked" in evaluation.audit_tags


def test_runtime_uses_configured_group_command_prefix_for_policy_gate():
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        group_command_prefix="!",
    )
    called = False

    def capability(message, decision):
        nonlocal called
        called = True
        return CapabilityResult(
            request_id=message.request_id,
            capability_id=decision.capability_id,
            kind="text",
            body="ok",
        )

    blocked = IncomingMessage(
        platform="qq",
        adapter="onebot.v11",
        bot_id="10000",
        session_id="group:100",
        session_type=SessionType.GROUP,
        sender_id="42",
        group_id="100",
        plain_text="/bot status",
        raw_segments=[{"type": "text", "data": {"text": "/bot status"}}],
        mentions_bot=False,
    )
    allowed = blocked.model_copy(
        update={
            "request_id": "req_allowed_prefix",
            "plain_text": "!status",
            "raw_segments": [{"type": "text", "data": {"text": "!status"}}],
        }
    )

    blocked_receipt = pipeline.handle(blocked, capability, capability_id="bot.status")
    allowed_receipt = pipeline.handle(allowed, capability, capability_id="bot.status")

    assert blocked_receipt.state is ReceiptState.BLOCKED
    assert allowed_receipt.state is ReceiptState.SENT
    assert called is True


def test_runtime_passes_actor_roles_into_decision_and_audit_tags():
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(
        send_queue=queue,
        audit_logger=audit,
        role_settings=policy.build_role_settings(
            Config(
                bot_admin_user_ids=["42"],
                bot_enterprise_user_ids=["42"],
                bot_trusted_user_ids=["42"],
            )
        ),
    )
    seen_roles: list[str] = []

    def capability(message, decision):
        seen_roles.extend(decision.actor_roles)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id=decision.capability_id,
            kind="text",
            body="统一运行时在线",
        )

    receipt = pipeline.handle(make_role_message("42"), capability, capability_id="bot.status")

    assert receipt.state is ReceiptState.SENT
    assert seen_roles == ["user", "trusted", "enterprise", "admin"]
    [send_request] = queue.sent_requests
    assert "role:admin" in send_request.audit_tags
    assert "role:enterprise" in send_request.audit_tags
    assert "role:trusted" in send_request.audit_tags


def test_status_reports_permission_role_counts_without_listing_ids():
    result = build_status_result(
        Config(
            bot_admin_user_ids=["10001"],
            bot_enterprise_user_ids=["20001", "20002"],
            bot_trusted_user_ids=["30001"],
            bot_blocked_user_ids=["40001"],
        )
    )

    assert "权限角色：admins=1，enterprise=2，trusted=1，blocked=1" in result.body
    assert "10001" not in result.body
    assert "40001" not in result.body
