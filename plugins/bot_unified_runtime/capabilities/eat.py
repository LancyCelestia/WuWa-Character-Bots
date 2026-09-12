"""吃什么能力（bot.eat）：随机推荐 + 菜谱查询 + LLM 约束推荐。

触发：`吃什么`/`吃啥`/`今天吃什么`（可带 `三选一`/`再来一道`/辣/不辣）、
`菜谱 <菜名>`、`怎么做 <菜名>`。带忌口/食材/人数等自然语言约束时走
主路由 LLM 生成（参考社区开源吃什么插件的交互思路，原生实现）；
纯随机推荐走内置库。渲染复用 Mica 信息卡管线，本地图包
（Runtime data/food_images/<菜名>.jpg）存在时作封面。
"""

from __future__ import annotations

import re
import threading
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
    r"^[/!！]?(?:今天)?吃(?:点|什|啥|么什么)?[什么啥]*(?:呢|好|啊|呀|嘛)?[？?]?\s*"
    r"(?P<extra>三选一|来三道|再来一道|再来|辣的|不辣|.*)?$"
)
_RECIPE_RE = re.compile(r"^[/!！]?(?:菜谱|菜譜|怎么做|怎麼做|如何做)\s*[:：]?\s*(?P<name>.+)$")

# F10 真实封面：本地图包未命中时经 Bing 图搜抓一张真实菜品图，
# 落盘 food_images/<菜名>.jpg 作常驻缓存（下次直接本地命中）。
# 全程 best-effort：任何网络/解析失败都返回空串（封面区折叠，不阻断出卡）。
_IMAGE_MAX_BYTES = 8 * 1024 * 1024
_FETCH_TIMEOUT = 6.0
_IMAGE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_BING_RESULT_RE = re.compile(r'murl&quot;:&quot;(https?://[^&"]+)&quot;')
_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8", ".jpg"),
    (b"\x89PNG", ".png"),
    (b"GIF8", ".gif"),
    (b"RIFF", ".webp"),
)
_ILLEGAL_FILENAME_RE = re.compile(r'[\\/:*?"<>|\s]+')

# 审计 E2-8：extra 非空时必须命中已知修饰/约束词表，否则不路由（落入闲聊）。
# 此前 `.*` 兜底让任何「吃」开头的句子（吃了吗/吃火锅）都被判成点菜指令。
_EAT_MODIFIER_RE = re.compile(r"三选一|来三道|再来一道|再来|辣的|不辣|微辣|中辣|特辣")
_CONSTRAINT_RE = re.compile(
    r"不吃|不要|别放|忌口|过敏|有|加|放|人多|\d人|两[人个]|三[人个]|四[人个]|"
    "清淡|开胃|下饭|暖和|热乎|快手|省事|便宜|丰盛|减脂|健身"
)


def is_eat_command(text: str) -> bool:
    match = _EAT_RE.match((text or "").strip())
    if match is None:
        return False
    extra = (match.group("extra") or "").strip()
    if not extra:
        return True
    return bool(
        _EAT_MODIFIER_RE.search(extra) or _CONSTRAINT_RE.search(extra)
    )


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


def _food_image_root(config: Any) -> Path:
    """food_images 目录解析（Runtime 重映射），失败退回相对路径。"""
    base = str(getattr(config, "bot_food_image_dir", "") or "data/food_images")
    try:
        from plugins.bot_unified_runtime.character.providers import (
            build_runtime_data_path,
        )

        return build_runtime_data_path(config, base)
    except Exception:  # noqa: BLE001 - 路径解析失败退回相对路径。
        return Path(base)


def _dish_image(dish: Dish, config: Any) -> str:
    """封面图三级来源：本地图包 → 抓取缓存 → 空串（卡面折叠封面区）。"""
    root = _food_image_root(config)
    for suffix in (".jpg", ".png", ".webp"):
        candidate = root / f"{dish.name}{suffix}"
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return _fetch_dish_image(root, dish.name)


def _fetch_dish_image(root: Path, name: str) -> str:
    """Bing 图搜抓一张真实菜品图并缓存；best-effort，失败返回空串。"""
    import urllib.parse
    import urllib.request

    query = urllib.parse.quote_plus(f"{name} 菜品 实拍")
    search_url = f"https://cn.bing.com/images/search?q={query}&first=1&count=8"
    try:
        req = urllib.request.Request(
            search_url,
            headers={
                "User-Agent": _IMAGE_UA,
                "Referer": "https://cn.bing.com/",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            page = resp.read(_IMAGE_MAX_BYTES).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001 - 搜索失败静默降级。
        return ""
    from plugins.bot_unified_runtime.sources.downloader import (
        RejectedUrlError,
        check_download_url,
    )

    for match in _BING_RESULT_RE.finditer(page):
        image_url = match.group(1)
        try:
            check_download_url(image_url)  # SSRF 护栏：内网/保留网段拒绝
        except RejectedUrlError:
            continue
        try:
            req = urllib.request.Request(
                image_url,
                headers={"User-Agent": _IMAGE_UA, "Referer": "https://cn.bing.com/"},
            )
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                data = resp.read(_IMAGE_MAX_BYTES + 1)
        except Exception:  # noqa: BLE001, S112 - 单个候选失败静默试下一个。
            continue
        if not (1024 <= len(data) <= _IMAGE_MAX_BYTES):
            continue
        suffix = next(
            (ext for magic, ext in _IMAGE_MAGIC if data.startswith(magic)), ""
        )
        if not suffix:
            continue  # 不是图片字节（多为错误页 HTML），换下一个候选
        try:
            root.mkdir(parents=True, exist_ok=True)
            safe_name = _ILLEGAL_FILENAME_RE.sub("_", name).strip("_") or "dish"
            target = root / f"{safe_name}{suffix}"
            target.write_bytes(data)
            return str(target)
        except OSError:
            return ""
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
            feature_label="美食推荐",
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


# 近期推荐（换菜不重复）：会话 -> 菜名集合。
# bot.eat 已进 offload 名单，多线程并发是常态：全部读写走锁；
# 值用 dict[str, None]（保插入序的集合），超限逐出最旧一半而不是清空，
# 保住"最近吃过的不再推"的语义（审计#31）。
_RECENT: dict[str, dict[str, None]] = {}
_RECENT_LOCK = threading.Lock()
_RECENT_MAX_SESSIONS = 256


def clear_recent_dishes() -> None:
    """清空近期推荐（测试与运维用）。"""
    with _RECENT_LOCK:
        _RECENT.clear()


def build_eat_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any:
    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        text = (message.plain_text or "").strip()
        session = f"{message.session_type.value}:{message.session_id}"
        with _RECENT_LOCK:
            recent = _RECENT.setdefault(session, {})

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
        # _CONSTRAINT_RE 提升到模块级，与 is_eat_command 的路由校验共用。
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
            with _RECENT_LOCK:
                exclude: set[str] | None = set(recent) if not again else None
            picked = random_dish(exclude=exclude, spicy=spicy)
            if picked is None:
                continue
            picks.append(picked)
            with _RECENT_LOCK:
                if len(recent) > 24:
                    # 审计#31：全清会让"换菜不重复"失忆；逐出最旧一半。
                    for stale in list(recent)[: len(recent) // 2]:
                        recent.pop(stale, None)
                recent[picked.name] = None
        if not picks:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.eat",
                kind="text",
                body="菜品库暂时抽不出菜了，稍后再试。",
                audit_tags=["eat", "empty"],
            )
        with _RECENT_LOCK:
            while len(_RECENT) > _RECENT_MAX_SESSIONS:
                _RECENT.pop(next(iter(_RECENT)), None)
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
