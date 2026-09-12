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
    DISHES,
    Dish,
    random_dish,
    search_dishes,
)

_EAT_RE = re.compile(
    r"^[/!！]?(?:今天)?吃(?:点|什|啥|么什么)?[什么啥]*(?:呢|好|啊|呀|嘛)?[？?]?\s*"
    r"(?P<extra>三选一|来三道|再来一道|再来|辣的|不辣|.*)?$"
)
_RECIPE_RE = re.compile(r"^[/!！]?(?:菜谱|菜譜|怎么做|怎麼做|如何做)\s*[:：]?\s*(?P<name>.+)$")

# 实弹反馈③轮修复（2026-09-12 群 662948429 现场）：
# a) 触发过灵：「怎么做到的」被 _RECIPE_RE 捕成菜名「到的」——菜名合法性守卫，
#    粒子/代词开头或过短的一律不算菜名（回落静默，不回骚扰文案）。
# b) 特定词打不中：「西红柿炒鸡蛋」查不到（库内叫「番茄炒蛋」）——同义词归一 +
#    反向包含兜底（菜名含于问句，如「西红柿炒蛋怎么做才嫩」→ 番茄炒蛋）。
# c) 带前缀消息误入随机推荐：@提及/昵称前缀未剥时 ^ 锚定正则全失配 → 掉进
#    随机推荐路径当众推错菜——入口剥前导 @提及；两类正则都不匹配时静默跳过
#    （随机推荐只服务真正「吃什么」类指令，绝不当兜底话术）。
_MENTION_TOKEN_RE = re.compile(r"^(?:@\S+[\s,，]*)+")
_RECIPE_NAME_INVALID_RE = re.compile(
    r"^(?:到|了|的|得|这样|那样|这么|那么|什么|怎么样|怎样|咋|难道|难道说|"
    r"吗|呢|吧|啊|呀|哦|嘛|嗯|就|才|都|也|又|再|还|被|把|将|会让|能|会|要|想)"
)
_DISH_SYNONYM_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"西红柿"), "番茄"),
    (re.compile(r"马铃薯|洋芋"), "土豆"),
    (re.compile(r"卷心菜|圆白菜|高丽菜"), "包菜"),
    (re.compile(r"花椰菜|花菜"), "菜花"),
    (re.compile(r"凤梨"), "菠萝"),
    (re.compile(r"奇异果"), "猕猴桃"),
    (re.compile(r"蛋炒饭"), "炒饭"),
    (re.compile(r"番薯|地瓜"), "红薯"),
    (re.compile(r"四季豆|芸豆"), "豆角"),
    (re.compile(r"青椒|菜椒|甜椒"), "辣椒"),
)


def strip_mentions(text: str) -> str:
    """剥掉消息开头的全部 @提及 token（多连 @ 场景，实弹 17:01:33 案例）。"""
    value = (text or "").strip()
    while True:
        stripped = _MENTION_TOKEN_RE.sub("", value).strip()
        if stripped == value or not stripped:
            return stripped
        value = stripped


def is_valid_recipe_name(name: str) -> bool:
    """菜名合法性：≥2 字且不以粒子/代词/助动词开头（「到的」「了」拒绝）。"""
    value = (name or "").strip()
    return len(value) >= 2 and not _RECIPE_NAME_INVALID_RE.match(value)


def normalize_dish_query(name: str) -> str:
    """食材同义词归一（西红柿→番茄等），命中同义词库的查询用它重试一次。"""
    value = name or ""
    for pattern, replacement in _DISH_SYNONYM_RULES:
        if pattern.search(value):
            return pattern.sub(replacement, value)
    return value


def _bigrams(value: str) -> set[str]:
    return {value[index : index + 2] for index in range(len(value) - 1)}


def fuzzy_dish_hits(name: str) -> list[Dish]:
    """bigram 重叠模糊匹配：问句与库内菜名不必互为子串。

    「西红柿炒鸡蛋」→同义词归一→「番茄炒鸡蛋」与库内「番茄炒蛋」重叠
    {番茄,茄炒} ≥ 半数菜名 bigram 即命中，按覆盖率降序；无噪声脆弱性
    （纯子串方案在 鸡蛋/蛋 断点处失配）。
    """
    query = _bigrams(normalize_dish_query(name))
    if not query:
        return []
    scored: list[tuple[float, str, Dish]] = []
    for dish in DISHES:
        dish_bigrams = _bigrams(dish.name)
        if not dish_bigrams:
            continue
        overlap = len(dish_bigrams & query)
        if overlap >= 2 and overlap / len(dish_bigrams) >= 0.5:
            scored.append((overlap / len(dish_bigrams), dish.name, dish))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [dish for _coverage, _name, dish in scored]

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
        # 入口剥前导 @提及（多连 @ 场景由 strip_mentions 循环处理），
        # 保证 ^ 锚定的菜谱/吃什么正则能命中（实弹 17:01:33 案例）。
        text = strip_mentions((message.plain_text or "").strip())
        session = f"{message.session_type.value}:{message.session_id}"
        with _RECENT_LOCK:
            recent = _RECENT.setdefault(session, {})

        # 菜谱查询：菜谱 <菜名> / 怎么做 <菜名>；菜名必须像菜名（守卫拒绝
        # 「怎么做到的」→「到的」这类误捕，回落到下方静默跳过）。
        recipe_match = _RECIPE_RE.match(text)
        recipe_name = recipe_match.group("name").strip() if recipe_match else ""
        if recipe_match and is_valid_recipe_name(recipe_name):
            hits = search_dishes(recipe_name)
            if not hits:
                normalized = normalize_dish_query(recipe_name)
                if normalized != recipe_name:
                    hits = search_dishes(normalized)
            if not hits:
                # bigram 模糊兜底：「西红柿炒鸡蛋」归一后与库内「番茄炒蛋」
                # 重叠过半即命中（纯子串在 鸡蛋/蛋 断点处失配）。
                hits = fuzzy_dish_hits(recipe_name)
            if not hits:
                # 本地没有 → LLM 生成菜谱，失败才告知未收录。
                llm_text = _llm_constrained(config, f"教我做「{recipe_name}」这道菜") if config else ""
                if llm_text:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.eat",
                        kind="text",
                        title=f"菜谱：{recipe_name}",
                        body=llm_text,
                        risk_level=RiskLevel.LOW,
                        privacy_level=PrivacyLevel.PUBLIC,
                        audit_tags=["eat", "recipe_llm"],
                    )
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.eat",
                    kind="text",
                    body=f"菜谱库里还没有「{recipe_name}」，换个常见家常菜试试？",
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
        if not eat_match:
            # 路由误捕/前缀污染文本（如「怎么做到的」剥不出合法菜名）：
            # 静默跳过——随机推荐只服务真正的「吃什么」类指令，绝不当兜底
            # 话术（实弹 17:01:22/17:01:33 当众推错菜事故的根修）。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.eat",
                kind="text",
                body="",
                audit_tags=["eat", "missing_query_silent"],
            )
        extra = (eat_match.group("extra") or "").strip()
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
