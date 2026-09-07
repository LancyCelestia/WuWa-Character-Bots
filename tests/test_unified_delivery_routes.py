from __future__ import annotations

from pathlib import Path

PLUGIN = Path("plugins/bot_unified_runtime/__init__.py")


def test_file_handlers_use_pipeline_instead_of_direct_bot_send():
    source = PLUGIN.read_text(encoding="utf-8")
    start = source.index("    async def _handle_admin_file_notice")
    end = source.index("    async def _handle_mail_notice", start)
    block = source[start:end]

    assert "await bot.send(" not in block
    assert "_send_text_through_unified_pipeline(" in block


def test_main_transport_delivery_uses_unified_gateway():
    source = PLUGIN.read_text(encoding="utf-8")
    start = source.index("async def _deliver_transport_send_request")
    end = source.index("async def _notify_operational_callback", start)
    block = source[start:end]

    assert "UnifiedDeliveryGateway" in block