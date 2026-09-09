"""好感度查询能力（bot.affinity）：`好感度` / `好感查看` / `查询好感`。

私聊返回双向分值卡（守岸人对你 / 你对守岸人），群聊返回本群好感榜
（有印象成员网格，自己一行高亮）；`好感度 算法` 返回三档规则说明。
Mica 卡走独立模板 affinity_card.html，渲染失败回退纯文本。
数值口径见 docs/affinity-design.md §9。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.character.affinity import effective_delta
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)

_COMMAND_RE = re.compile(r"^[/!！]?\s*(?:好感度|好感查看|查询好感)\s*(?P<arg>.*)$")
# 与样本卡一致的展示口径：≥75 亲近强调、<25 疏离警示，单位 0-100。
_HOT_SCORE = 75.0
_COLD_SCORE = 25.0
_LEADERBOARD_LIMIT = 60
_LEADERBOARD_PREVIEW = 12


def is_affinity_command(text: str) -> bool:
    return _COMMAND_RE.match(text.strip()) is not None


def parse_affinity_query(text: str) -> str:
    match = _COMMAND_RE.match(text.strip())
    return (match.group("arg").strip() if match else "")


ALGORITHM_TEXT = (
    "好感度算法（0-100，初始 10；步长动态变化、因人而异）：\n"
    "① 加分：感谢/夸奖/问候/陪伴 每次 +2 起（同一天前 10 次有效）。\n"
    "② 轻微波动：玩笑与越界亲昵 每次 -1 起（每日前 5 次）；普通聊天不变；闲置 7 天起每天向 10 回归 1 分。\n"
    "③ 扣分：抱怨/贬低 每次 -5 起、辱骂/骚扰 每次 -10 起（每日各前 8 次）。\n"
    "动态规则：当前分越靠近 0 或 100，单步越小（10~90 区间全额，两侧按幂律衰减）；"
    "每人另有由 QQ 号确定性派生的 ±15% 个人系数——同一句话，不同人的实际增减不同。\n"
    "档位态度：亲近 ≥75｜友善 45~74｜客气 25~44｜疏离 <25（任何档位都不辱骂、不弃聊）。"
)

# 档位 → 回应方式对照（docs/affinity-design.md §9.1b）
_TIER_TABLE: list[dict[str, str]] = [
    {"label": "亲近", "range": "≥75", "attitude": "更直接的关心与陪伴，可以用小名称呼，答应得干脆"},
    {"label": "友善", "range": "45~74", "attitude": "温和有陪伴感，记得对方偏好，征询式回应"},
    {"label": "客气", "range": "25~44", "attitude": "礼貌但有距离，就事论事，不假装熟识"},
    {"label": "疏离", "range": "<25", "attitude": "简短、有分寸的疏离；保持体面，绝不辱骂"},
]

_STEP_LABELS: tuple[tuple[str, str], ...] = (
    ("positive", "感谢/夸奖"),
    ("tease", "玩笑/亲昵"),
    ("negative", "抱怨/贬低"),
    ("insult", "辱骂/骚扰"),
)


def _score_color_class(score: float) -> str:
    if score >= _HOT_SCORE:
        return " hot"
    if score < _COLD_SCORE:
        return " cold"
    return ""


def _accent_color(config: Any | None) -> str:
    color = str(getattr(config, "bot_help_card_color", "") or "").strip()
    return color or "#607080"


def _bot_name(config: Any | None) -> str:
    return (
        str(getattr(config, "bot_persona_display_name", "") or "").strip()
        or "守岸人"
    )


def _rules_chips() -> list[dict[str, str]]:
    return [
        {
            "cls": "up",
            "label": "加分",
            "text": "感谢 / 夸奖 / 问候 / 陪伴　+2/次（每日前 10 次）",
        },
        {
            "cls": "flat",
            "label": "波动",
            "text": "玩笑亲昵 -1 · 普通聊天不变 · 闲置 7 天起每天向 50 回归",
        },
        {
            "cls": "down",
            "label": "扣分",
            "text": "抱怨 -5 / 次 · 辱骂骚扰 -10 / 次（每日前 8 次）",
        },
    ]


def build_private_payload(
    *,
    bot_to_user: float,
    user_to_bot: float,
    bot_name: str,
    accent_color: str,
    subtitle: str,
) -> dict[str, Any]:
    """私聊双向卡 payload（纯函数，便于测试）。"""
    return {
        "pc": accent_color,
        "title": "好感度",
        "subtitle": subtitle,
        "mode": "private",
        "bot_name": bot_name,
        "bot_to_user": {
            "score": bot_to_user,
            "tier": _tier_text(bot_to_user),
            "bar": max(0.0, min(100.0, bot_to_user)),
        },
        "user_to_bot": {
            "score": user_to_bot,
            "tier": _tier_text(user_to_bot),
            "bar": max(0.0, min(100.0, user_to_bot)),
        },
        "rules": _rules_chips(),
    }


def build_group_payload(
    rows: list[dict[str, Any]], *, me_id: str, subtitle: str, accent_color: str
) -> dict[str, Any]:
    """群排行榜卡 payload（纯函数，便于测试）。"""
    return {
        "pc": accent_color,
        "title": "好感度",
        "subtitle": subtitle,
        "mode": "group",
        "me_id": me_id,
        "rows": rows,
    }


def build_algorithm_payload(
    *,
    bot_score: float,
    steps: list[dict[str, str]],
    accent_color: str,
    subtitle: str = "算法 · 因人而异 · 档位回应方式",
) -> dict[str, Any]:
    """算法说明卡 payload：规则速览 + 请求者此刻的精确步长 + 档位态度对照。"""
    return {
        "pc": accent_color,
        "title": "好感度算法",
        "subtitle": subtitle,
        "mode": "algorithm",
        "bot_score": f"{bot_score:.1f}",
        "steps": steps,
        "tiers": [dict(tier) for tier in _TIER_TABLE],
        "rules": _rules_chips(),
    }


def _tier_text(score: float) -> str:
    if score >= _HOT_SCORE:
        return "亲近"
    if score >= 45.0:
        return "友善"
    if score >= _COLD_SCORE:
        return "客气"
    return "疏离"


def _format_private_text(bot_name: str, bot_score: float, user_score: float) -> str:
    return (
        f"{bot_name}对你：{bot_score:.1f}（{_tier_text(bot_score)}）\n"
        f"你对{bot_name}：{user_score:.1f}\n"
        f"{_algorithm_one_liner()}"
    )


def _algorithm_one_liner() -> str:
    return "算法：感谢夸奖问候 +2/次；玩笑 -1、闲置回归；抱怨 -5、辱骂 -10；区间 0-100。发「好感度 算法」看完整说明。"


def _format_group_text(
    bot_name: str,
    rows: list[dict[str, Any]],
    me_id: str,
    me_bot_score: float,
    me_user_score: float,
) -> str:
    lines = [f"好感榜（有印象 {len(rows)} 人，展示前 {_LEADERBOARD_LIMIT}）："]
    for index, row in enumerate(rows[:_LEADERBOARD_PREVIEW], start=1):
        name = str(row.get("display_name") or row.get("sender_id") or "")
        mark = "（你）" if str(row.get("sender_id")) == me_id else ""
        lines.append(f"{index}. {name}{mark}　{float(row.get('score') or 0.0):.1f}")
    if me_id and not any(str(row.get("sender_id")) == me_id for row in rows):
        lines.append(f"……你还没在本群留下印象，先聊聊天吧（当前 {me_bot_score:.1f}）")
    lines.append(
        f"{bot_name}对你 {me_bot_score:.1f}｜你对{bot_name} {me_user_score:.1f}｜{_algorithm_one_liner()}"
    )
    return "\n".join(lines)


def _render_card(payload: dict[str, Any], render_backend: Any | None, card_dir: str, request_id: str) -> str:
    """渲染好感度卡 PNG；文件名按内容摘要（同内容复用，防卡片目录无界增长）。"""
    if render_backend is None or not getattr(render_backend, "available", False):
        return ""
    try:
        from plugins.bot_unified_runtime.output.card_render.bridge import (
            render_affinity_card_html,
        )

        png = render_backend.render_card(
            {
                "html": render_affinity_card_html(payload),
                "viewport": {"width": 1240, "height": 1400},
                "device_scale_factor": 2,
                "wait_ms": 0,
            }
        )
        if not isinstance(png, bytes) or not png:
            return ""
        digest = hashlib.sha1(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:12]
        target = Path(card_dir or "data/cards")
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"affinity_{digest}.png"
        path.write_bytes(png)
        return str(path)
    except Exception:  # noqa: BLE001 - 渲染失败回退纯文本。
        return ""


def build_affinity_capability(
    config: Any | None = None,
    *,
    affinity_store: Any | None = None,
    render_backend: Any | None = None,
    card_dir: str | None = None,
) -> Any:
    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        del decision
        request_id = message.request_id
        accent = _accent_color(config)
        bot_name = _bot_name(config)
        resolved_card_dir = card_dir or str(
            getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
        )
        arg = parse_affinity_query(message.plain_text)

        if arg in {"算法", "说明", "规则", "help"}:
            steps: list[dict[str, str]] = []
            bot_score = 10.0
            if affinity_store is not None and message.sender_id:
                snap = affinity_store.snapshot(message.sender_id)
                current = float(snap.get("affinity", 0.1))
                bot_score = round(current * 100.0, 1)
                for behavior, label in _STEP_LABELS:
                    value = round(
                        effective_delta(message.sender_id, behavior, current) * 100.0, 2
                    )
                    steps.append(
                        {"label": label, "value": f"{value:+.2f}", "cls": "up" if value >= 0 else "down"}
                    )
            body = ALGORITHM_TEXT
            if steps:
                body += (
                    f"\n你此刻的精确步长（印象好感 {bot_score:.1f}）："
                    + "｜".join(f"{s['label']} {s['value']}" for s in steps)
                )
            payload = build_algorithm_payload(
                bot_score=bot_score, steps=steps, accent_color=accent
            )
            card = _render_card(payload, render_backend, resolved_card_dir, request_id)
            return CapabilityResult(
                request_id=request_id,
                capability_id="bot.affinity",
                kind="mixed" if card else "text",
                title="好感度算法",
                body=body,
                images=[{"file": card}] if card else [],
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["affinity", "algorithm"],
            )
        if affinity_store is None:
            return CapabilityResult(
                request_id=request_id,
                capability_id="bot.affinity",
                kind="text",
                body="好感度功能未开启。",
                audit_tags=["affinity", "disabled"],
            )

        me_id = message.sender_id
        snapshot = affinity_store.snapshot(me_id) if me_id else {}
        bot_score = round(float(snapshot.get("affinity", 0.5)) * 100.0, 1)
        user_score = round(float(affinity_store.sentiment_for(me_id)) * 100.0, 1)

        show_group_board = bool(message.group_id) and arg not in {"我", "自己", "me"}
        if show_group_board:
            rows = list(affinity_store.leaderboard(message.group_id, limit=_LEADERBOARD_LIMIT))
        else:
            rows = []

        if rows:
            body = _format_group_text(bot_name, rows, me_id, bot_score, user_score)
            payload = build_group_payload(
                rows,
                me_id=me_id,
                subtitle=f"有印象 {len(rows)} 人 · 分数=守岸人的印象好感（0-100）",
                accent_color=accent,
            )
        else:
            body = _format_private_text(bot_name, bot_score, user_score)
            where = "私聊" if not message.group_id else f"群 {message.group_id}"
            payload = build_private_payload(
                bot_to_user=bot_score,
                user_to_bot=user_score,
                bot_name=bot_name,
                accent_color=accent,
                subtitle=where,
            )

        card = _render_card(payload, render_backend, resolved_card_dir, request_id)
        return CapabilityResult(
            request_id=request_id,
            capability_id="bot.affinity",
            kind="mixed" if card else "text",
            title="好感度",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["affinity", "group_board" if rows else "private"],
        )

    return capability


__all__ = [
    "ALGORITHM_TEXT",
    "build_affinity_capability",
    "build_algorithm_payload",
    "build_group_payload",
    "build_private_payload",
    "is_affinity_command",
    "parse_affinity_query",
]
