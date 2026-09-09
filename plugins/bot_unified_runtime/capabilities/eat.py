"""吃什么能力（bot.eat）：随机推荐 + 菜谱查询 + LLM 约束推荐。

触发：`吃什么`/`吃啥`/`今天吃什么`（可带 `三选一`/`再来一道`/辣/不辣）、
`菜谱 <菜名>`、`怎么做 <菜名>`。带忌口/食材/人数等自然语言约束时走
主路由 LLM 生成（参考 astrbot_plugin_eat_what 的交互思路，原生实现）；
纯随机推荐走内置库。渲染复用 Mica 信息卡管线，本地图包
（Runtime data/food_images/<菜名>.jpg）存在时作封面。
"""

from __future__ import annotations

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
from plugins.bot_unified_runtime.sources.food_data import (
    Dish,
    random_dish,
    search_dishes,
)

_EAT_RE = re.compile(
    r"^[/!！]?(?:今天)?吃(?:点|什|啥|么什么)?[什么啥]*(?:呢|好)?[？?]?\s*"
    r"(?P<extra>三选一|来三道|再来一道|再来|辣的|不辣|.*)?$"
)
_RECIPE_RE = re.compile(r"^[/!！]?(?:菜谱|菜譜|怎么做|怎麼做|如何做)\s*[:：]?\s*(?P<name>.+)$")


def is_eat_command(text: str) -> bool:
    return bool(_EAT_RE.match((text or "").strip()))


def is_recipe_command(text: str) -> bool:
    return bool(_RECIPE_RE.match((text or "").strip()))


def _format_dish_body(dish: Dish, *, with_steps: bool = True) -> str:
    lines = [f"🍽 {dish.name}（{dish.taste}）"]
    if dish.intro:
        lines.append(dish.intro)
    if with_steps:
        lines.append(f"食材：{dish.materials}")
        lines.append(f"做法：{dish.steps}")
    return "\n".join(lines)


def _dish_image(dish: Dish, config: Any) -> str:
    """本地图包：Runtime data/food_images/<菜名>.jpg|.png 存在则用作封面。"""
    base = str(getattr(config, "bot_food_image_dir", "") or "data/food_images")
    try:
        from plugins.bot_unified_runtime.character.providers import (
            build_runtime_data_path,
        )

        root = build_runtime_data_path(config, base)
    except Exception:  # noqa: BLE001 - 路径解析失败退回相对路径。
        root = Path(base)
    for suffix in (".jpg", ".png", ".webp"):
        candidate = root / f"{dish.name}{suffix}"
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return ""


def _eat_card(config: Any, render_backend: Any, dish: Dish, body: str) -> str:
    """推荐/菜谱渲染成 Mica 卡图；后端不可用或失败返回空串。"""
    if render_backend is None or not getattr(render_backend, "available", False):
        return ""
    try:
        from plugins.bot_unified_runtime.capabilities.content_parser import (
            render_card_png,
        )
        from plugins.bot_unified_runtime.contracts import build_parsed_content

        cover = _dish_image(dish, config)
        item = build_parsed_content(
            platform="eat",
            item_id=dish.name,
            item_kind="article",
            title=f"今天吃：{dish.name}",
            author_name="守岸人美食推荐",
            summary=body[:1200],
            cover_url=cover,
            parse_depth="deep",
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


def _llm_constrained(config: Any, raw_extra: str) -> str:
    """自然语言约束（忌口/食材/人数）→ 主路由生成菜谱；失败返回空串。"""
    try:
        from plugins.bot_unified_runtime.capabilities.content_parser import (
            _summarize_subtitle,  # 复用同一主路由调用范式
        )

        prompt = (
            "你是家常菜推荐助手。根据用户约束推荐 1 道菜，"
            "格式：菜名、简介一句、食材列表、编号做法步骤（3-6 步）。"
            f"用户约束：{raw_extra}"
        )
        return _summarize_subtitle(config, prompt, max_chars=1200)
    except Exception:  # noqa: BLE001 - LLM 失败兜底本地随机。
        return ""


# 近期推荐（换菜不重复）：会话 -> 菜名集合
_RECENT: dict[str, set[str]] = {}
_RECENT_MAX_SESSIONS = 256


def clear_recent_dishes() -> None:
    """清空近期推荐（测试与运维用）。"""
    _RECENT.clear()


def build_eat_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any:
    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        text = (message.plain_text or "").strip()
        session = f"{message.session_type.value}:{message.session_id}"
        recent = _RECENT.setdefault(session, set())

        # 菜谱查询：菜谱 <菜名> / 怎么做 <菜名>
        recipe_match = _RECIPE_RE.match(text)
        if recipe_match:
            name = recipe_match.group("name").strip()
            hits = search_dishes(name)
            if not hits:
                # 本地没有 → LLM 生成菜谱，失败才告知未收录。
                llm_text = _llm_constrained(config, f"教我做「{name}」这道菜") if config else ""
                if llm_text:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.eat",
                        kind="text",
                        title=f"菜谱：{name}",
                        body=llm_text,
                        risk_level=RiskLevel.LOW,
                        privacy_level=PrivacyLevel.PUBLIC,
                        audit_tags=["eat", "recipe_llm"],
                    )
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.eat",
                    kind="text",
                    body=f"菜谱库里还没有「{name}」，换个常见家常菜试试？",
                    audit_tags=["eat", "recipe_not_found"],
                )
            dish = hits[0]
            body = _format_dish_body(dish)
            card = _eat_card(config, render_backend, dish, body)
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.eat",
                kind="mixed" if card else "text",
                title=f"菜谱：{dish.name}",
                body=body,
                images=[{"file": card}] if card else [],
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["eat", "recipe", "card_rendered" if card else "text_only"],
            )

        # 推荐路径
        eat_match = _EAT_RE.match(text)
        extra = (eat_match.group("extra") or "").strip() if eat_match else ""
        count = 3 if ("三" in extra or "3" in extra) else 1
        again = "再来" in extra
        spicy: bool | None = (
            True if "辣" in extra and "不辣" not in extra else (False if "不辣" in extra else None)
        )
        # 带实义约束（忌口/食材/人数/口味关键词）→ LLM 推荐；
        # 纯修饰语（"朴实无华的"）不浪费一次模型调用，走本地随机。
        _CONSTRAINT_RE = re.compile(
            r"不吃|不要|别放|忌口|过敏|有|加|放|人多|\d人|两[人个]|三[人个]|四[人个]|"
            "清淡|开胃|下饭|暖和|热乎|快手|省事|便宜|丰盛|减脂|健身"
        )
        meaningful = bool(extra) and not again and count == 1 and not spicy and bool(
            _CONSTRAINT_RE.search(extra)
        )
        if meaningful and config is not None:
            llm_text = _llm_constrained(config, extra)
            if llm_text:
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.eat",
                    kind="text",
                    title="吃什么",
                    body=llm_text,
                    risk_level=RiskLevel.LOW,
                    privacy_level=PrivacyLevel.PUBLIC,
                    audit_tags=["eat", "recommend_llm"],
                )
        picks: list[Dish] = []
        for _ in range(count):
            picked = random_dish(exclude=recent if not again else set(), spicy=spicy)
            if picked is None:
                continue
            picks.append(picked)
            if len(recent) > 24:
                recent.clear()
            recent.add(picked.name)
        if not picks:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.eat",
                kind="text",
                body="菜品库暂时抽不出菜了，稍后再试。",
                audit_tags=["eat", "empty"],
            )
        while len(_RECENT) > _RECENT_MAX_SESSIONS:
            _RECENT.pop(next(iter(_RECENT)))
        bodies = [_format_dish_body(dish, with_steps=(len(picks) == 1)) for dish in picks]
        body = "\n\n".join(bodies)
        if len(picks) > 1:
            body = "三选一，纠结就掷骰子：\n\n" + body
        card = _eat_card(config, render_backend, picks[0], bodies[0])
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.eat",
            kind="mixed" if card else "text",
            title="今天吃什么",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "eat",
                f"eat_count:{len(picks)}",
                "card_rendered" if card else "text_only",
            ],
        )

    return capability
