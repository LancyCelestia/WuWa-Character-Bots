"""免费游戏能力（bot.epic）：`epic` / `epicfree` / `Epic 免费`。

Epic 每周限免 + Steam 100% 折扣限免合并展示；渲染后端可用时产出
Mica 信息卡图（复用解析卡的 render_card_png 管线），文本作 caption/兜底。
"""

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
)
from plugins.bot_unified_runtime.sources.steamfree import (
    fetch_steam_free_games,
)

_COMMAND_RE = re.compile(r"^[/!！]?(?:epic|epicfree|epic free|epic 免费|epic免费|免费游戏|游戏免费|steam免费|steam 免费|steamfree)\s*$", re.IGNORECASE)


def is_epic_command(text: str) -> bool:
    return _COMMAND_RE.match(text.strip()) is not None


def _format_games(games: list[dict[str, Any]]) -> str:
    if not games:
        return "这周没有正在进行的免费游戏活动。"
    lines = ["本周免费游戏："]
    for game in games:
        source = str(game.get("source") or "").strip()
        line = f"- {game['title']}"
        if source:
            line = f"- [{source}] {game['title']}"
        if game.get("end"):
            line += f"（截止 {game['end']}）"
        if game.get("url"):
            line += f"\n  {game['url']}"
        lines.append(line)
    return "\n".join(lines)


def build_epic_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any:
    proxy = str(getattr(config, "bot_download_proxy", "") or "") if config else ""

    def _render_games_card(games: list[dict[str, Any]], summary: str) -> str:
        """合成免费游戏 Mica 卡图；后端不可用或失败返回空串。"""
        if render_backend is None or not getattr(render_backend, "available", False):
            return ""
        try:
            from plugins.bot_unified_runtime.capabilities.content_parser import (
                render_card_png,
            )
            from plugins.bot_unified_runtime.contracts import build_parsed_content

            covers = [str(g.get("image") or "") for g in games if g.get("image")]
            item = build_parsed_content(
                platform="epic",
                item_id="free-games",
                item_kind="article",
                title="本周免费游戏",
                author_name="Epic Games Store · Steam",
                summary=summary,
                cover_url=covers[0] if covers else "",
                canonical_url=str(games[0].get("url") or "") if games else "",
                parse_depth="deep",
                detail={"images": covers[:4]} if covers else {},
            )
            payload = render_card_png(
                render_backend,
                item,
                config=config,
                card_dir=str(getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"),
            )
        except Exception:  # noqa: BLE001 - 渲染失败回退纯文本。
            return ""
        return str(payload.get("file") or "") if isinstance(payload, dict) else ""

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        games: list[dict[str, Any]] = []
        failed: list[str] = []
        try:
            games.extend(fetch_epic_free_games(proxy=proxy))
        except Exception:  # noqa: BLE001 - 单源失败不影响另一源。
            failed.append("Epic")
        try:
            games.extend(fetch_steam_free_games(proxy=proxy))
        except Exception:  # noqa: BLE001
            failed.append("Steam")
        if not games:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.epic",
                kind="text",
                body="免费游戏信息拉取失败，稍后再试。",
                audit_tags=["epic", "fetch_failed"],
            )
        body = _format_games(games)
        if failed:
            body += f"\n（{'、'.join(failed)} 源暂时拉取失败）"
        card = _render_games_card(games, body)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.epic",
            kind="mixed" if card else "text",
            title="本周免费游戏",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["epic", f"epic_games:{len(games)}", "card_rendered" if card else "text_only"],
        )

    return capability
