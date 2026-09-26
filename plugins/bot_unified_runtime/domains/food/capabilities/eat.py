"""吃什么能力（bot.eat）：随机推荐 + 菜谱查询 + LLM 约束推荐。

触发：`吃什么`/`吃啥`/`今天吃什么`（可带 `三选一`/`再来一道`/辣/不辣）、
`菜谱 <菜名>`、`怎么做 <菜名>`。带忌口/食材/人数等自然语言约束时走
主路由 LLM 生成（参考社区开源吃什么插件的交互思路，原生实现）；
纯随机推荐走内置库。渲染复用 Mica 信息卡管线，本地图包
（Runtime data/food_images/<菜名>.jpg）存在时作封面。
"""

from __future__ import annotations

import random
import re
import threading
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.food.data.food_data import (
    DISHES,
    Dish,
    random_dish,
    search_dishes,
)

_EAT_RE = re.compile(
    r"^[/!！]?(?:(?:今天)?吃(?:点|什|啥|么什么)?[什么啥]*(?:呢|好|啊|呀|嘛)?"
    r"|eat|food"
    # 拼音全拼/缩写（T-Spec T1.5/T1.6）：吃什么→chishenme/csm（查重无冲突）；
    # 前缀锚定天然防左胶合，(?![A-Za-z0-9]) 防右胶合（chishenmeqq）。
    r"|chishenme(?![A-Za-z0-9])|csm(?![A-Za-z0-9]))[？?]?\s*"
    r"(?P<extra>三选一|来三道|再来一道|再来|辣的|不辣"
    r"|spicy|mild|random|anything|something|.*)?$"
)
# 英文 eat/food（前缀锚定）与 recipes? 为 T-Spec T1.2 英文触发；
# 带尾巴的英文句子（eating/foodie/fast food）由 extra 守卫拦回聊天。
# ASCII 别名右侧词边界（stocks _alias_hit 先例）：recipesxx / recipexx 等
# 字母延续不触发；本正则无 IGNORECASE，故用显式大小写区间。全角标点后缀
# （recipes？）不受影响。
_RECIPE_RE = re.compile(
    r"^[/!！]?(?:菜谱|菜譜|怎么做|怎麼做|如何做"
    # 拼音全拼/缩写（T-Spec T1.5/T1.6）：caipu/zenmezuo 同覆盖繁体同音
    # （菜譜/怎麼做）；cp/zmz 查重仅同源变体对不算冲突。前缀锚定防左胶合，
    # (?![A-Za-z0-9]) 防右胶合（cpqq/caipuqq）。
    r"|caipu(?![A-Za-z0-9])|zenmezuo(?![A-Za-z0-9])|cp(?![A-Za-z0-9])|zmz(?![A-Za-z0-9])"
    r"|recipes?(?![A-Za-z0-9]))\s*[:：]?\s*(?P<name>.+)$"
)

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

# 像素级封面质检阈值：min 边 < 300 多为图标/占位缩略图；宽高比超出
# [1/3, 3] 多为横幅广告条/雪碧图——都不适合当菜品封面，按候选拒绝。
_IMG_MIN_SIDE = 300
_IMG_ASPECT_MIN = 1 / 3
_IMG_ASPECT_MAX = 3.0

# 轻量防污染域黑名单（2026-09-13 图库污染清理隔离区实测来源注册域）：
# boredpanda=娱乐段子站（动漫剧照）、moyubuluo=动漫图床、sinaimg=新浪防盗链
# 广告位、699pic=摄图网水印 stock、duitang=堆糖杂图——这些域的「菜品图」
# 实测多为剧照/广告/风景。整域拒绝零成本（先于下载），不逐张 VLM。
_IMAGE_DOMAIN_BLOCKLIST: tuple[str, ...] = (
    "boredpanda.com",
    "moyubuluo.com",
    "sinaimg.cn",
    "699pic.com",
    "duitang.com",
)


def _url_domain_blocked(url: str) -> bool:
    """来源域命中黑名单（注册域后缀匹配，覆盖全部子域）→ True。"""
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return any(
        host == domain or host.endswith("." + domain)
        for domain in _IMAGE_DOMAIN_BLOCKLIST
    )

# 审计 E2-8：extra 非空时必须命中已知修饰/约束词表，否则不路由（落入闲聊）。
# 此前 `.*` 兜底让任何「吃」开头的句子（吃了吗/吃火锅）都被判成点菜指令。
_EAT_MODIFIER_RE = re.compile(r"三选一|来三道|再来一道|再来|辣的|不辣|微辣|中辣|特辣|spicy|mild|random|anything|something")
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
        from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
            build_runtime_data_path,
        )

        return build_runtime_data_path(config, base)
    except Exception:  # noqa: BLE001 - 路径解析失败退回相对路径。
        return Path(base)


def _dish_image(dish: Dish, config: Any) -> str:
    """封面图四级来源：本地图包 → SQLite 图库索引 → 抓取缓存 → 空串。"""
    root = _food_image_root(config)
    for suffix in (".jpg", ".png", ".webp"):
        candidate = root / f"{dish.name}{suffix}"
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    library = _library_lookup(root, dish.name)
    if library:
        return library
    return _fetch_dish_image(root, dish.name, config)


def _pixels_ok(data: bytes) -> bool:
    """PIL 像素级质检：解码成功且 min 边/宽高比达标才放行。

    PIL 不可用（未安装）时跳过本检查不阻断；Image.open/verify 异常按拒绝
    处理（字节头伪装成图片的坏文件在这里拦下）。
    """
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - PIL 缺席 → 跳过该检查。
        return True
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            image.verify()
    except Exception:  # noqa: BLE001 - 解码失败按拒绝处理。
        return False
    if width <= 0 or height <= 0:
        return False
    if min(width, height) < _IMG_MIN_SIDE:
        return False
    aspect = width / height
    return _IMG_ASPECT_MIN <= aspect <= _IMG_ASPECT_MAX


def _tavily_image_candidates(name: str, config: Any | None = None) -> list[str]:
    """Tavily 图搜直链候选（Bing 空手时的兜底通道）；未配 key/失败返回空表。

    key 解析复用 web_search 链同一套：config 字段（支持 env: 间接引用）；
    CLI 预热态（config=None，nonebot 未加载配置）从 .env 直取真实 key。
    """
    import os

    from plugins.bot_unified_runtime.domains.core.search.search_api import (
        resolve_search_secret,
    )

    api_key = resolve_search_secret(
        str(getattr(config, "bot_search_tavily_api_key", "") or ""), config
    )
    if not api_key and config is None:
        # CLI 预热态（config=None，nonebot 未加载配置）：直读进程环境变量。
        # 注意：库代码不做 load_dotenv()——运行时读 .env 会把生产开关泄进
        # 测试进程（A43 全量预跑 20 红根因）；.env 装载是 CLI 入口的职责。
        api_key = os.environ.get("BOT_SEARCH_TAVILY_API_KEY", "")
    if not api_key:
        return []
    try:
        from plugins.bot_unified_runtime.domains.core.search.search_api import (
            TavilyWebSearchProvider,
        )

        endpoint = (
            str(getattr(config, "bot_web_search_tavily_endpoint", "") or "").strip()
            or "https://api.tavily.com/search"
        )
        provider = TavilyWebSearchProvider(api_key=api_key, endpoint=endpoint)
        try:
            return provider.image_urls(f"{name} 菜品 实拍", max_results=8)
        finally:
            provider.close()
    except Exception:  # noqa: BLE001 - 兜底通道任何失败都静默降级。
        return []


def _fetch_dish_image(root: Path, name: str, config: Any | None = None) -> str:
    """图搜按序抓第一张通过全部质检的菜品图并缓存；失败返回空串。

    候选通道两跳：Bing 图搜 HTML → Tavily 图搜 API（用户 2026-09-14 裁定：
    Bing 缺图时用已配的 Tavily key 兜底，不自造离线假图）。所有候选过同一
    校验链：来源域黑名单 → SSRF 护栏 → 字节数(1KB~8MB) → magic bytes
    → 像素质检（PIL，可跳过）；任一环不过即换下一个候选。落盘时同目录写
    <菜名>.source.txt（首行图片 URL，次行 ISO 时间戳）作来源记录。
    """
    import urllib.parse
    import urllib.request

    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        RejectedUrlError,
        check_download_url,
    )

    safe_name = _ILLEGAL_FILENAME_RE.sub("_", name).strip("_") or "dish"

    def _accepts(image_url: str) -> str:
        """单候选质检+落盘：通过返回落盘路径，不过返回空串（闸序固定）。"""

        if _url_domain_blocked(image_url):
            return ""  # 已知污染源域（剧照/防盗链/wallpaper），零成本先拒
        try:
            check_download_url(image_url)  # SSRF 护栏：内网/保留网段拒绝
        except RejectedUrlError:
            return ""
        try:
            req = urllib.request.Request(
                image_url,
                headers={"User-Agent": _IMAGE_UA, "Referer": "https://cn.bing.com/"},
            )
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                final_url = str(resp.geturl() or image_url)
                check_download_url(final_url)  # 重定向落点复查（安全审计 I-1：公网候选 302→内网拒绝）
                data = resp.read(_IMAGE_MAX_BYTES + 1)
        except Exception:  # noqa: BLE001 - 单个候选失败静默试下一个。
            return ""
        if not (1024 <= len(data) <= _IMAGE_MAX_BYTES):
            return ""
        suffix = next(
            (ext for magic, ext in _IMAGE_MAGIC if data.startswith(magic)), ""
        )
        if not suffix:
            return ""  # 不是图片字节（多为错误页 HTML），换下一个候选
        if not _pixels_ok(data):
            return ""  # 像素质检不过（图标/占位图/横竖条），换下一个候选
        try:
            root.mkdir(parents=True, exist_ok=True)
            target = root / f"{safe_name}{suffix}"
            target.write_bytes(data)
            try:
                (root / f"{safe_name}.source.txt").write_text(
                    f"{image_url}\n"
                    f"{datetime.now().astimezone().isoformat(timespec='seconds')}\n",
                    encoding="utf-8",
                )
            except OSError:
                pass  # 来源记录 best-effort，不影响封面返回
            return str(target)
        except OSError:
            return ""

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
    except Exception:  # noqa: BLE001 - Bing 搜索失败不放弃，继续走 Tavily 兜底。
        page = ""
    for match in _BING_RESULT_RE.finditer(page):
        fetched = _accepts(match.group(1))
        if fetched:
            return fetched
    for image_url in _tavily_image_candidates(name, config):
        fetched = _accepts(image_url)
        if fetched:
            return fetched
    return ""


# ==================== 图库 SQLite 索引 + 预热（用户裁定 2026-09-13） ====================
# 「按菜谱全量预先把合格实拍图下载进图库，按需调用」：文件仍是事实来源
# （food_images/<菜名>.<ext> + .source.txt），SQLite 只做 name→path 的
# 可查询索引；索引任何失败都不影响主链路（退回常规三级缓存链）。


def _library_db_path(root: Path) -> Path:
    return root / "library.sqlite"


def _library_record(root: Path, name: str, path: str) -> None:
    """写入/更新索引行（name → 图片路径 + 来源 URL + 时间）；best-effort。"""
    try:
        import sqlite3

        source_url = ""
        try:
            source_file = Path(path).with_suffix(".source.txt")
            if source_file.is_file():
                source_url = (
                    source_file.read_text(encoding="utf-8").splitlines()[0].strip()
                )
        except (OSError, IndexError):
            source_url = ""
        conn = sqlite3.connect(_library_db_path(root))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS food_images ("
                "name TEXT PRIMARY KEY, path TEXT NOT NULL, "
                "source_url TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL DEFAULT '')"
            )
            conn.execute(
                "INSERT INTO food_images(name, path, source_url, fetched_at) "
                "VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                "path=excluded.path, source_url=excluded.source_url, "
                "fetched_at=excluded.fetched_at",
                (
                    name,
                    path,
                    source_url,
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001, S110 - 索引失败不影响主链路。
        pass


def _library_lookup(root: Path, name: str) -> str:
    """按索引查封面路径；索引缺失或文件已被清理返回空串。"""
    try:
        import sqlite3

        db = _library_db_path(root)
        if not db.is_file():
            return ""
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT path FROM food_images WHERE name = ?", (name,)
            ).fetchone()
        finally:
            conn.close()
        if row and Path(row[0]).is_file():
            return str(row[0])
    except Exception:  # noqa: BLE001 - 索引失败退回常规缓存链。
        return ""
    return ""


def prewarm_food_images(
    config: Any | None = None,
    *,
    dishes: list[str] | None = None,
    limit: int = 0,
) -> dict[str, str]:
    """图库预热：把菜品库封面按需预下载进本地图包（幂等，可反复跑）。

    - dishes 缺省 = domains.food.data.food_data.DISHES 全量菜名；
    - 已有本地缓存的菜直接登记索引并跳过下载；
    - limit>0 只处理前 N 个缺失项（控速用）；
    - 返回 {菜名: 路径或空串}（空 = 该菜本轮没有拿到合格图，下次重试）。
    """
    if dishes is None:
        dishes = [dish.name for dish in DISHES]
    root = _food_image_root(config)
    results: dict[str, str] = {}
    pending = 0
    for name in dishes:
        existing = ""
        for suffix in (".jpg", ".png", ".webp"):
            candidate = root / f"{name}{suffix}"
            try:
                if candidate.is_file():
                    existing = str(candidate)
                    break
            except OSError:
                continue
        if existing:
            results[name] = existing
            _library_record(root, name, existing)
            continue
        if limit and pending >= limit:
            results[name] = ""
            continue
        pending += 1
        fetched = _fetch_dish_image(root, name, config)
        results[name] = fetched
        if fetched:
            _library_record(root, name, fetched)
    return results


def _eat_card(config: Any, render_backend: Any, dish: Dish, body: str) -> str:
    """推荐/菜谱渲染成 Mica 卡图；后端不可用或失败返回空串。"""
    if render_backend is None or not getattr(render_backend, "available", False):
        return ""
    try:
        from plugins.bot_unified_runtime.contracts import build_parsed_content
        from plugins.bot_unified_runtime.domains.link_parse.capabilities.content_parser import (
            render_card_png,
        )

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
        from plugins.bot_unified_runtime.domains.link_parse.capabilities.content_parser import (
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
                # 审查 Q-01：入 user_copy 数据源失败池（原「……稍后再试。」）。
                body=random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(
                    reason="菜品库暂时抽不出菜了"
                ),
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


if __name__ == "__main__":  # pragma: no cover - 运维预热入口（裸跑=全量幂等预热；--dishes 指定菜名）
    import argparse

    try:  # CLI 预热需要 Tavily 兜底 key：入口处装 .env（库代码保持纯净）。
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # noqa: BLE001, S110 - 无 dotenv 环境直读进程环境变量。
        pass
    _parser = argparse.ArgumentParser(
        description="菜谱封面图库预热（Bing 实拍图 + 像素质检 + SQLite 索引）"
    )
    _parser.add_argument("--limit", type=int, default=0, help="只预热前 N 个缺失项（0=全部）")
    _parser.add_argument("--dishes", nargs="*", default=None, help="指定菜名（缺省=全量菜品库）")
    _args = _parser.parse_args()
    _results = prewarm_food_images(dishes=_args.dishes, limit=_args.limit)
    _ok = sum(1 for _v in _results.values() if _v)
    print(f"预热完成：{_ok}/{len(_results)} 有图")
    for _name, _path in _results.items():
        print(("  OK  " if _path else "  MISS ") + _name + ("" if _path else "（下次重试）"))
