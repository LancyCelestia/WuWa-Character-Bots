"""好感度查询能力（bot.affinity）：`好感度` / `好感查看` / `查询好感`。

私聊返回双向分值卡（守岸人对你 / 你对守岸人），群聊返回本群好感榜
（有印象成员网格，自己一行高亮）；`好感度 算法` 返回八档规则说明。
Mica 卡走独立模板 affinity_card.html，渲染失败回退纯文本。
数值口径权威：docs/design/affinity-v7-design.md（v7 潜变量重写，2026-09-21 用户
裁定「算法全部重写」）；v4/v5/v6 历史章节在 docs/affinity-design.md（灰度关闭态）。
展示 -100~+100、基准 10、8 档温和态度不变；v7 内部改由无界潜变量映射，结构上
永不触顶；计分单元从关键词次数升级为互动质量（主动/延展/情绪/尊重/回应五子
信号），同类信号新鲜度跨日累积（不再隔日重置），增速按本人活跃度归一，道歉与
和解走独立修复通道。算法说明全定性、不展示固定加减数值（F4 裁定不变）。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    attitude_tiers,
    tier_display_range,
    tier_name_for_affinity,
)
from plugins.bot_unified_runtime.domains.render.bot_avatar import bot_avatar_uri
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BRAND_THEME,
)

_COMMAND_RE = re.compile(
    # affinity(?![a-z0-9])：ASCII 别名右侧词边界（wiki _alias_hit 先例），
    # affinityqq 类字母延续不触发（边界体检清账）；中文胶合不受影响。
    # 全拼/缩写（T-Spec T1.5/T1.6 第二批）：haogandu 等同音覆盖 親密度/好感值
    # 等简繁词；haogan 镜像中文「好感」的独立成词约束（后随仅限
    # 空白/串尾/算法/说明/规则/榜/我），haogandu 类长词先匹配、
    # haogansuanfa 类拼音 arg 延续不触发（arg 词族不拼音化，同批一 eat 先例）。
    r"^[/!！]?\s*(?:好感度|好感查看|查询好感|查詢好感|好感值|亲密度|親密度|affinity(?![a-z0-9])"
    r"|haoganchakan(?![a-z0-9])|hgck(?![a-z0-9])"
    r"|chaxunhaogan(?![a-z0-9])|cxhg(?![a-z0-9])"
    r"|haogandu(?![a-z0-9])|hgd(?![a-z0-9])"
    r"|haoganzhi(?![a-z0-9])|hgz(?![a-z0-9])"
    r"|qinmidu(?![a-z0-9])|qmd(?![a-z0-9])"
    r"|好感(?=\s|$|算法|说明|规则|榜|我)"
    r"|haogan(?=\s|$|算法|说明|规则|榜|我))\s*(?P<arg>.*)$",
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
    "好感度算法（展示口径 -100~+100，初始 10 · v7 重写版）：\n"
    "好感不是记次数的账本，而是一段连续流动的印象。这一版把量尺从「有限线性」"
    "重写为「连续生长」：相处越久，分数始终还能再涨，却永远涨不到头——高处只会"
    "平滑地放缓、渐渐钝住，不再一下子冲到顶挤成一团，顶端留给了真正的长久相处。\n"
    "每次互动，好感都会综合这些真实信号平滑地变化：\n"
    "① 说话的温度——真诚的感谢、问候与陪伴让好感升温；抱怨与恶言会让它降温，"
    "说得越难听降温越多。但关键词不再是全部。\n"
    "② 互动的质量——你是不是主动来找我、有没有说新的内容、是否追问与回应我的话、"
    "是否礼貌地守住边界。敷衍的套话复读几乎没有分量——这是「不按次数计分」的核心。\n"
    "③ 相处的时间——认识越久、相处越多，信任的积累越稳；刚认识时会更谨慎一些。\n"
    "④ 第一印象——最初几次互动的善恶会定下一个「起点偏差」，长期相处会把它慢慢"
    "抹平，任何人都有等价的机会。\n"
    "⑤ 每个人的相处节奏略有差异（因人而异），但聊得多不等于涨得快——增速会按你"
    "自己的活跃水位归一，安静的人不吃亏，话痨也不占便宜。\n"
    "动态规则：好感没有固定加几减几；同类言行的影响边际递减，且这份递减不再隔天"
    "重置——反复刷同一句话会跨日越来越没意思，冷一冷再来，它又会有分量；单次互动"
    "的影响有上限，每一天累积的变化也有限额，绝不允许一夜暴涨暴跌。道歉与和解有"
    "独立的修复通道，不会被「重复」的折扣挡住——回血永远不嫌晚，但也在同样的护栏"
    "之内。好久不联系，好感一分不扣；难听的记忆则会随时间淡去。\n"
    "档位态度：初识/生疏/微凉/稍淡/友善/亲近/挚友/独一份 共八档，连续过渡、"
    "绝不在门槛上生硬跳变。\n"
    "红线摘要：任何档位都不强硬、不辱骂、不贬低，负向档位只是距离感，"
    "最高档也不越界，不冷暴力弃聊。"
)

# 档位 → 回应方式对照（docs/affinity-design.md §4/§7，v4 八档）。
# **本表不抄文案**：档位名、态度句、区间边界全部由注入真身 attitude_tiers()/
# tier_display_range() 投影（真身 = character/affinity.py:_ATTITUDE_TIERS）；
# 本层只允许追加「只给用户看」的注脚 _TIER_DISPLAY_NOTES。
# 曾各抄一份导致友善/独一份两档改词分叉，常驻锁见 tests/test_affinity_tier_single_source.py。
_TIER_DISPLAY_NOTES: dict[int, str] = {
    0: "（初始 10 在此档）",  # 展示口径注脚：分数不进注入面（内心数值保密 §7）
}


def _tier_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for tier_id, name, instruction in attitude_tiers():
        rows.append(
            {
                "label": name,
                "range": tier_display_range(tier_id),
                "attitude": instruction + _TIER_DISPLAY_NOTES.get(tier_id, ""),
            }
        )
    return rows


_TIER_TABLE: list[dict[str, str]] = _tier_rows()

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
    """卡面/正文署名的中文自称——走唯一读法（P-G3 第二波换腿，2026-09-29）。

    此前直读 ``config.bot_persona_display_name`` 再手抄「守岸人」兜底：切人格时该
    配置项不动 ⇒ 好感度卡继续显旧名，与人格自称分家。现经
    ``persona_profile.current_bot_nickname``（先查人格册、按**当前生效**人格 id
    现读，再回落兼容显示名）；两者都取不到 ⇒ 空串，由品牌胶囊统一回落品牌名，
    本层不留第二处字面量（契约锁＝``bridge.RenderPayload().bot_name == ""``）。
    绝不读 ``get_login_info``（台账 #60★）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        active_persona_id,
        current_bot_nickname,
    )

    return current_bot_nickname(active_persona_id(config), config=config)


def _rules_chips() -> list[dict[str, str]]:
    """规则速览（v7 口径：定性描述，不展示具体加减数值）。"""
    return [
        {
            "cls": "up",
            "label": "升温",
            "text": "真诚的感谢 / 夸奖 / 问候 / 陪伴——说得越暖，升温越明显",
        },
        {
            "cls": "flat",
            "label": "平稳",
            "text": "普通聊天缓温 · 增速按本人节奏归一 · 久不联系不扣分也不强制回归",
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
    bot_name: str = "",
) -> dict[str, Any]:
    """算法说明卡 payload：规则速览 + 请求者的因子画像（定性）+ 档位态度对照。

    ``bot_name``＝调用方经 ``_bot_name(config)``（唯一读法）取到的自称；缺省空串＝
    不表态，署名回落品牌胶囊单一源。此处**不许**再写死「守岸人」——那正是 P-G3
    「自称与页面名分家」的形态（切人格后这张卡仍显旧名）。
    """
    return {
        "pc": accent_color,
        "title": "好感度算法",
        "subtitle": subtitle,
        "mode": "algorithm",
        "bot_name": bot_name,
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
        from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
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
            from plugins.bot_unified_runtime.domains.chat_reply.runtime.cache_policy import (
                prune_prefixed,
            )

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
                bot_avatar_url=bot_avatar_uri(config),
                bot_name=bot_name,
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
                subtitle=(
                    f"有印象 {len(rows)} 人 · 分数="
                    f"{bot_name or BRAND_THEME.display_name}的印象好感（-100~+100）"
                ),
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
                bot_avatar_url=bot_avatar_uri(config),
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
