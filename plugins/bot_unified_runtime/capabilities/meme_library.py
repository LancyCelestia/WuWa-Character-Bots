"""群聊表情包能力（bot.meme_library）：/偷表情 按权重随机发送入库表情。

权重策略（来源 meme_library.py）：
- VLM 判定非表情/普通图片降权；NSFW≥0.2 再降权，≥0.8 永不发送；
- 守岸人/岸宝 最优先，其次 鸣潮/战双帕弥什/库洛，再次 ACG，最后普通；
- 支持关键词/情绪标签过滤；带冷却时间防刷屏风控。
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)

_COMMAND_RE = re.compile(
    r"^[/!！]?(?:偷表情|偷表情包|表情随机|随机表情|随机表情包|"
    r"表情抽签|meme random|steal meme|偷圖|偷表情包)\s*(?P<arg>.*)$",
    re.IGNORECASE,
)
_STATS_RE = re.compile(
    r"^[/!！]?(?:表情库统计|表情统计|表情库|meme stats)\s*$", re.IGNORECASE
)

# 冷却登记 LRU 上限：会话数极大时防止 dict 无界慢泄漏（审计 #30）。
_COOLDOWN_CAP = 4096


def is_meme_library_command(text: str) -> bool:
    stripped = (text or "").strip()
    return _COMMAND_RE.match(stripped) is not None or _STATS_RE.match(stripped) is not None


def parse_meme_library_command(text: str) -> tuple[str, str]:
    """返回 (动作, 参数)。动作：pick / stats。"""
    stripped = (text or "").strip()
    match = _STATS_RE.match(stripped)
    if match:
        return "stats", ""
    match = _COMMAND_RE.match(stripped)
    if not match:
        raise ValueError("not a meme library command")
    return "pick", (match.group("arg") or "").strip()


def build_meme_library_capability(store: Any, config: Any | None = None) -> Any:
    cooldown: OrderedDict[str, float] = OrderedDict()
    cooldown_seconds = int(getattr(config, "bot_meme_library_cooldown_seconds", 20) or 20)
    nsfw_max = float(getattr(config, "bot_meme_library_nsfw_max", 0.2) or 0.2)

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        try:
            action, arg = parse_meme_library_command(message.plain_text)
        except ValueError:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme_library",
                kind="text",
                body="用法：偷表情 [关键词|情绪标签|私聊]；表情库统计 查看数量。",
                audit_tags=["meme_library", "usage"],
            )
        if action == "stats":
            stats = store.stats()
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme_library",
                kind="text",
                title="表情库",
                body=(
                    f"已收藏 {stats['total']} 张，累计发送 {stats['used_total']} 次，"
                    f"高危拦截 {stats['nsfw_blocked']} 张。"
                ),
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["meme_library", "stats"],
            )

        # 冷却：同一会话防刷屏，避免 QQ 风控。
        key = f"{message.session_id}:{message.sender_id}"
        now = time.monotonic()
        # 有界化（审计重发现）：会话键无界增长，超阈值先清过期再裁最旧。
        if len(cooldown) > 512:
            for stale in [k for k, ts in cooldown.items() if now - ts >= cooldown_seconds]:
                cooldown.pop(stale, None)
            while len(cooldown) > 512:
                cooldown.popitem(last=False)
        if key in cooldown:
            cooldown.move_to_end(key)
            if now - cooldown[key] < cooldown_seconds:
                remaining = int(cooldown_seconds - (now - cooldown[key])) + 1
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.meme_library",
                    kind="text",
                    body=f"表情包还在冷却中，请 {remaining} 秒后再来偷～",
                    risk_level=RiskLevel.LOW,
                    privacy_level=PrivacyLevel.PERSONAL,
                    audit_tags=["meme_library", "cooldown"],
                )

        keyword = "" if arg.lower() in {"私聊", "私聊我", "private", "私"} else arg
        picked = store.weighted_pick(keyword=keyword, nsfw_max=nsfw_max)
        if picked is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme_library",
                kind="text",
                body="表情库还是空的（或没有匹配的表情）。多发点图让我收藏吧～",
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["meme_library", "empty"],
            )
        cooldown[key] = now
        cooldown.move_to_end(key)
        while len(cooldown) > _COOLDOWN_CAP:
            cooldown.popitem(last=False)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.meme_library",
            kind="mixed",
            title="表情包",
            body="给你偷来一张表情～",
            images=[{"file": str(picked["path"])}],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["meme_library", "pick", f"weight:{picked.get('weight')}"],
        )

    return capability
