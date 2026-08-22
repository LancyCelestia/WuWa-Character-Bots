"""Epic 每周免费游戏能力（bot.epic）：`epic` / `epicfree` / `Epic 免费`。"""

from __future__ import annotations

import re
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.sources.epicfree import (
    fetch_epic_free_games,
    format_epic_free_games,
)

_COMMAND_RE = re.compile(r"^(?:epic|epicfree|epic 免费|epic免费)\s*$", re.IGNORECASE)


def is_epic_command(text: str) -> bool:
    return _COMMAND_RE.match(text.strip()) is not None


def build_epic_capability(config: Any | None = None) -> Any:
    proxy = str(getattr(config, "bot_download_proxy", "") or "") if config else ""

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        try:
            games = fetch_epic_free_games(proxy=proxy)
        except Exception:  # noqa: BLE001 - 接口失败降级提示。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.epic",
                kind="text",
                body="Epic 免费游戏信息拉取失败，稍后再试。",
                audit_tags=["epic", "fetch_failed"],
            )
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.epic",
            kind="text",
            title="Epic 免费游戏",
            body=format_epic_free_games(games),
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["epic", f"epic_games:{len(games)}"],
        )

    return capability
