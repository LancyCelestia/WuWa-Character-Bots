"""好感度查询能力（bot.affinity）：`好感度` / `好感查看` / `查询好感`。

私聊返回双向分值卡（守岸人对你 / 你对守岸人），群聊返回本群好感榜
（有印象成员网格，自己一行高亮）；`好感度 算法` 返回八档规则说明。
Mica 卡走独立模板 affinity_card.html，渲染失败回退纯文本。
数值口径见 docs/affinity-design.md（v4 线性版）：展示 -100~+100、
基准 10、线性步长（各档位全额）、闲置回归与印象淡出、8 档态度表。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.character.affinity import (
    tier_name_for_affinity,
)
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)

_COMMAND_RE = re.compile(
    r"^[/!！]?\s*(?:好感度|好感查看|查询好感|好感值|亲密度|affinity"
    r"|好感(?=\s|$|算法|说明|规则|榜|我))\s*(?P<arg>.*)$",
    re.IGNORECASE,
)
# v5 展示口径（用户裁定 2026-09-12 实弹反馈④）：-100~+100 八档不变；
# 算法说明一律定性描述，不再展示「一次加几减几」的具体数值口径。
_LEADERBOARD_LIMIT = 60
_LEADERBOARD_PREVIEW = 12


def is_affinity_command(text: str) -> bool:
    return _COMMAND_RE.match(text.strip()) is not None


def parse_affinity_query(text: str) -> str:
    match = _COMMAND_RE.match(text.strip())
    return (match.group("arg").strip() if match else "")


ALGORITHM_TEXT = (
    "好感度算法（-100~+100，初始 10）：\n"
    "好感不是记次数的账本，而是一段连续流动的印象。每次相处，好感都会综合这些"
    "因素平滑地变化：\n"
    "① 说话的温度——真诚的感谢、问候与陪伴让好感自然升温；抱怨与恶言会让它"
    "降温，说得越难听降温越多。\n"
    "② 相处的时间——认识越久、相处越多，信任的积累越稳；刚认识时会更谨慎一些。\n"
    "③ 第一印象——最初几次互动的善恶会定下一个「起点偏差」：第一印象好，好话"
    "来得更明显；第一印象不佳，则需要更多温柔与耐心来弥补。\n"
    "④ 我当天的状态——我也会累也会开心，状态不同，感受的敏锐度也不同。\n"
    "⑤ 每个人的相处节奏略有差异，但态度与心意对所有人完全一致，绝无厚此薄彼。\n"
    "动态规则：好感没有固定加几减几；同一天内重复同类的言行影响会递减；"
    "好久不联系，好感会慢慢回到平静的基准；难听的记忆也会随时间淡去。\n"
    "档位态度：初识/生疏/微凉/稍淡/友善/亲近/挚友/独一份 共八档，连续过渡、"
    "绝不在门槛上生硬跳变。\n"
    "红线摘要：任何档位都不强硬、不辱骂、不贬低，负向档位只是距离感，"
    "最高档也不越界，不冷暴力弃聊。"
)

# 档位 → 回应方式对照（docs/affinity-design.md §4，v4 八档；左闭右开、最高档含 +100）
_TIER_TABLE: list[dict[str, str]] = [
    {"label": "初识", "range": "[-100, -75)", "attitude": "初见不久的人：礼貌、克制、有问必答但不寒暄"},
    {"label": "生疏", "range": "[-75, -50)", "attitude": "生疏的人：话少一截，依旧体面温和"},
    {"label": "微凉", "range": "[-50, -25)", "attitude": "语气稍淡，不冷不热，就事论事"},
    {"label": "稍淡", "range": "[-25, 0)", "attitude": "略淡于平时，但保持基本温柔"},
    {"label": "友善（基准）", "range": "[0, +25)", "attitude": "温和、有陪伴感，记得对方的偏好（初始 10 在此档）"},
    {"label": "亲近", "range": "[+25, +50)", "attitude": "更主动的关心，记得对方说过的事"},
    {"label": "挚友", "range": "[+50, +75)", "attitude": "直接而温暖，可以用给对方起的小名"},
    {"label": "独一份", "range": "[+75, +100]", "attitude": "最珍视的人：全然温柔的陪伴——依旧守全部安全边界"},
]

_STEP_LABELS: tuple[tuple[str, str], ...] = (
    ("first_impression", "第一印象"),
    ("known_days", "相处时长"),
)


def _factor_steps(profile: dict[str, Any]) -> list[dict[str, str]]:
    """请求者此刻的因子画像（定性方向词，不展示具体步长数值——F4）。"""
    steps: list[dict[str, str]] = []
    first = profile.get("first_impression")
    if first is None:
        steps.append({"label": "第一印象", "value": "还在积累中（最初几次相处定下起点）", "cls": "flat"})
    elif float(first) >= 0.25:
        steps.append({"label": "第一印象", "value": "起点不错，好话来得更明显", "cls": "up"})
    elif float(first) <= -0.25:
        steps.append({"label": "第一印象", "value": "起点偏冷，需要更多温柔来弥补", "cls": "down"})
    else:
        steps.append({"label": "第一印象", "value": "平静的起点，不快不慢", "cls": "flat"})
    days = float(profile.get("known_days") or 0.0)
    if days < 1.0:
        steps.append({"label": "相处时长", "value": "刚认识不久，还在慢慢熟悉", "cls": "flat"})
    elif days < 30.0:
        steps.append({"label": "相处时长", "value": "认识些日子了，信任在稳步积累", "cls": "up"})
    elif days < 365.0:
        steps.append({"label": "相处时长", "value": "相处了好几个月，已经很熟了", "cls": "up"})
    else:
        steps.append({"label": "相处时长", "value": "陪伴了一年以上的老朋友", "cls": "up"})
    return steps


def _accent_color(config: Any | None) -> str:
    color = str(getattr(config, "bot_help_card_color", "") or "").strip()
    return color or "#607080"


def _bot_name(config: Any | None) -> str:
    return (
        str(getattr(config, "bot_persona_display_name", "") or "").strip()
        or "守岸人"
    )


def _rules_chips() -> list[dict[str, str]]:
    """规则速览（v5：定性描述，不展示具体加减数值口径）。"""
    return [
        {
            "cls": "up",
            "label": "升温",
            "text": "真诚的感谢 / 夸奖 / 问候 / 陪伴——说得越暖，升温越明显",
        },
        {
            "cls": "flat",
            "label": "平稳",
            "text": "普通聊天 · 相处越久信任越稳 · 久不联系会慢慢回到基准",
        },
        {
            "cls": "down",
            "label": "降温",
            "text": "玩笑轻微 / 抱怨更多 / 辱骂最重——越难听降温越多",
        },
    ]


def build_private_payload(
    *,
    bot_to_user: float,
    user_to_bot: float,
    bot_name: str,
    accent_color: str,
    subtitle: str,
    bot_avatar_url: str = "",
) -> dict[str, Any]:
    """私聊双向卡 payload（纯函数，便于测试）。"""
    return {
        "pc": accent_color,
        "title": "好感度",
        "subtitle": subtitle,
        "mode": "private",
        "bot_name": bot_name,
        "bot_avatar_url": bot_avatar_url,
        "feature_label": "好感度",
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
    bot_avatar_url: str = "",
) -> dict[str, Any]:
    """算法说明卡 payload：规则速览 + 请求者的因子画像（定性）+ 档位态度对照。"""
    return {
        "pc": accent_color,
        "title": "好感度算法",
        "subtitle": subtitle,
        "mode": "algorithm",
        "bot_name": "守岸人",
        "bot_avatar_url": bot_avatar_url,
        "feature_label": "好感度",
        "bot_score": f"{bot_score:.1f}",
        "steps": steps,
        "tiers": [dict(tier) for tier in _TIER_TABLE],
        "rules": _rules_chips(),
    }


def _tier_text(score: float) -> str:
    """展示分（-100~+100）→ §4 档位名称（与 attitude 注入层同一档表）。"""
    return tier_name_for_affinity(score / 100.0)


def _format_private_text(bot_name: str, bot_score: float, user_score: float) -> str:
    return (
        f"{bot_name}对你：{bot_score:.1f}（{_tier_text(bot_score)}）\n"
        f"你对{bot_name}：{user_score:.1f}\n"
        f"{_algorithm_one_liner()}"
    )


def _algorithm_one_liner() -> str:
    return (
        "算法：好感随言行连续累积——说话的温度、相处的时间、第一印象、我当天的"
        "状态都会平滑地影响变化，没有固定的加几减几。发「好感度 算法」看完整说明。"
    )


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
        try:
            from plugins.bot_unified_runtime.runtime.cache_policy import prune_prefixed

            prune_prefixed(target, "affinity", keep=200)
        except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响本次出图。
            pass
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

        if arg in {"算法", "说明", "规则", "help", "算法说明", "怎么算", "如何算", "如何计算"}:
            steps: list[dict[str, str]] = []
            bot_score = 10.0
            if affinity_store is not None and message.sender_id:
                snap = affinity_store.snapshot(message.sender_id)
                current = float(snap.get("affinity", 0.1))
                bot_score = round(current * 100.0, 1)
                try:
                    steps = _factor_steps(affinity_store.factor_profile(message.sender_id))
                except Exception:  # noqa: BLE001 - 画像缺失时只展示通用说明。
                    steps = []
            body = ALGORITHM_TEXT
            payload = build_algorithm_payload(
                bot_score=bot_score,
                steps=steps,
                accent_color=accent,
                bot_avatar_url=str(getattr(config, "bot_persona_avatar_url", "") or ""),
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
        # 初始值口径（docs §1）：无记录默认基准 0.1，展示 10 分。
        bot_score = round(float(snapshot.get("affinity", 0.1)) * 100.0, 1)
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
                subtitle=f"有印象 {len(rows)} 人 · 分数=守岸人的印象好感（-100~+100）",
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
                bot_avatar_url=str(getattr(config, "bot_persona_avatar_url", "") or ""),
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
