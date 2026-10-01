"""今日快报能力（bot.news）：`快报/早报/晚报/今日热点/科技新闻/AI新闻` 触发。

数据来自 ``sources.news_feeds``（国内可达 RSS 聚合，进程内 10 分钟 TTL
缓存，单源失败静默跳过）。触发面刻意收窄：

- 只认显式触发词：快报 / 早报 / 晚报 / 今日热点 / 类目词×新闻|快报
  （科技新闻、AI新闻、AI快报、财经新闻、财经快报、国际新闻）；
  繁體同族（快報/早報/晚報/今日熱點/科技新聞/AI新聞/AI快報/財經新聞/財經快報/國際新聞）同表生效；
- 裸「新闻」**不**触发——那是联网搜索链路的地盘（question_intent 的
  ``_CURRENT_REQUEST_RE`` 含裸 `新闻`，剥走会互相打架）；
- 短文本（≤32 字）、无链接（带链接是链接解析的活）；「搜索/搜一下/
  查一下/找新闻/联网/上网」等明确搜索意图时让路。

类目从同一句话提取：财经→finance、国际→world、科技/AI/人工智能→tech、
其余→mix（跨类目轮转）。

条目列表在**渲染后端可用**时另合成一张新闻摘要卡（``news_digest_card.html``，
B05 快讯域呈现面），与纯文本**同发**（``kind="mixed"``——她要求「一次性讲清
楚」，卡是加法不是替换）；后端缺失、渲染异常或超时一律回今天这份纯文本，
契约零破坏（``kind="text"``，与未接卡时逐字段同形）。渲染后端由**装配层注入**
（与 epic/weather/market/today_history 同一口径），能力侧不自建、不自取——
缺省 ``render_backend=None`` 即逐字节维持旧的纯文本行为。

定时推送（21:30 群摘要、早晚简报）不经本能力出卡：那是既有的「推送保持
纯文本」裁定，本文件的卡只服务会话里的显式提问。
"""

from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
    card_text_value,
)
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets
from plugins.bot_unified_runtime.domains.subscribe.feeds.news_feeds import (
    CATEGORY_LABELS,
    NewsItem,
    fetch_headlines,
    format_news_brief,
)

# 显式触发词：复合词在前仅便于阅读；「新闻」单独出现不算触发。
# 繁體同族与简体逐词对齐（快報/財經新聞/國際新聞…），边界守卫/搜索让路共用。
_NEWS_TRIGGER_RE = re.compile(
    r"(今日热点|科技新闻|AI新闻|AI快报|财经新闻|财经快报|国际新闻|快报|早报|晚报"
    r"|今日熱點|科技新聞|AI新聞|AI快報|財經新聞|財經快報|國際新聞|快報|早報|晚報"
    # 全拼/缩写（T-Spec T1.5/T1.6）：全拼同覆盖繁体同音；双侧 [a-z0-9] 边界
    # 防 kuaibaoqq 类胶合、jinrikuaibao 内嵌 kuaibao 误配。缩写查重仅 zb
    # （早报×占卜）冲突不上，其余 kb/wb/jrkb/jrrd/kjxw/cjxw/cjkb/gjxw/axw/akb
    # 无冲突入表（fix-py1-report.md）。
    r"|(?<![a-z0-9])(?:jinriredian|jinrikuaibao|kejixinwen|aixinwen|aikuaibao"
    r"|caijingxinwen|caijingkuaibao|guojixinwen|kuaibao|zaobao|wanbao"
    r"|jrkb|jrrd|kjxw|cjxw|cjkb|gjxw|axw|akb|kb|wb)(?![a-z0-9])"
    r"|(?<![a-z0-9])news(?![a-z0-9]))",
    re.IGNORECASE,
)
# 明确联网搜索意图 → 让路（与 question_intent._EXPLICIT_SEARCH_RE 同向）；
# 英文 search news / news search 同向让路（T-Spec T1.2 配套）。
_SEARCH_INTENT_RE = re.compile(r"(搜索|搜一下|查一下|检索|找新闻|联网|上网|search news|news search)")
_URL_HINT_RE = re.compile(r"https?://", re.IGNORECASE)
_MAX_TRIGGER_LEN = 32

# 类目提示词 → 类目键（AI 用「紧邻 新闻/快报」匹配，避免英文单词误伤）；
# ai news 为 T1.2 英文触发配套类目映射（归 tech，与 AI新闻 同语义）；
# AI拼音 aixinwen/aikuaibao 同归 tech（T-Spec T1.5/T1.6 配套类目）。
_AI_HINT_RE = re.compile(
    r"((?:ai|人工智能)\s*(?:新闻|快报|news)|人工智能|aixinwen|aikuaibao)", re.IGNORECASE
)

# 审查 Q-01：数据源失败文案统一入 user_copy 池（守岸人语气轮换），不再硬编码。
def _empty_degraded_text() -> str:
    return random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(reason="快报暂时拉不到")


def extract_news_category(text: str) -> str:
    """从触发文本提取类目；无类目提示词时回退 mix（跨类目轮转）。"""
    stripped = (text or "").strip()
    if "财经" in stripped:
        return "finance"
    if "国际" in stripped:
        return "world"
    if "科技" in stripped or _AI_HINT_RE.search(stripped):
        return "tech"
    return "mix"


def is_news_command(text: str) -> bool:
    """快报触发判定：短文本、无链接、显式触发词、不撞搜索意图。"""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _MAX_TRIGGER_LEN:
        return False
    if _URL_HINT_RE.search(stripped):
        return False
    if not _NEWS_TRIGGER_RE.search(stripped):
        return False
    return not _SEARCH_INTENT_RE.search(stripped)


# ==================== 卡面呈现（S-T-NEWS-2，2026-09-26）====================
# 出图/落盘/配额**不在本文件重写一份**：一律走诊断卡与宿主机卡共用的那条中央
# 落盘口 ``domains/ops/monitor/error_report.render_html_card``（后端取图 →
# runtime_paths 落盘 → 按前缀 prune_prefixed，见其 docstring「再抄一份就是第二
# 真身」）。本文件只负责「把条目装成载荷」与「失败就说没出卡」。

#: 落盘文件名前缀（同前缀配额彼此隔离，不碰别的能力的卡）。
_CARD_STEM = "news"
#: 同前缀保留张数，与 today_history/divination/market 同口径（keep=120）。
_CARD_KEEP = 120
#: 视口：壳宽 1080px（模板 .panel），两侧留阴影溢出位；20 条两栏约 1400px 高，
#: 给到 2200 留足余量（截图按 ``.card`` 元素包围盒裁，多余视口不入画）。
_CARD_VIEWPORT = (1160, 2200)
#: 卡面功能名（页脚胶囊左侧那枚标签）。⚠ 字面量不住本文件：卡片静态中文文案
#: 唯一落点 = `bridge._CARD_TEXT`（渲染契约 §二 S79/S95），此处经公共读口取数。
_CARD_FEATURE_LABEL = card_text_value("static_news_72")

#: 页脚口径说明。⚠ **只允许常量**：模板的 ``{{ foot | safe }}`` 不转义，把条目
#: 标题/来源/摘要拼进来等于把外部内容送进可执行 HTML 区（跨站脚本的形态，哪怕
#: 产物只是一张图）。锁＝tests/test_news_card_outbound.py 的 foot 常量锁。
#: 「常量」约束与「文案入册」不冲突：值仍是模块级常量，只是字面量真身住在
#: bridge._CARD_TEXT（S-T-VISUAL-1 收口，值逐字符未动）。
_CARD_FOOT = card_text_value("static_news_71")


def _display_text(value: Any) -> str:
    """卡面文本：转字符串 + 走同一把打码尺（本地盘符路径/密钥形态）。

    出站纯文本由 ``output/plain_text`` 统一打码，图片不过那道闸，所以卡面
    字段必须在进渲染器之前就打过（铁律 3：不绕过 ``redact_local_secrets``）。
    """
    text = str(value or "")
    return redact_local_secrets(text) if text else ""


def _published_label(item: NewsItem) -> str:
    """条目发布时间（本地时区 ``月-日 时:分``）。

    只有**时区已知**（aware）的时间才上卡：naive 值不知道是哪台的钟，标出去
    就是编数；缺位时返回空串，模板整块隐藏该字段（宁缺不假）。
    """
    when = getattr(item, "published_at", None)
    if not isinstance(when, datetime) or when.tzinfo is None:
        return ""
    return when.astimezone().strftime("%m-%d %H:%M")


def _brief_date_text(body: str) -> str:
    """纯文本首行的日期段（``今日快报 · YYYY-MM-DD · 类目``）。

    卡与文共用**同一时间口径**（today_history 同法：日期取自正文首行，不在卡
    上另起一次时钟）。行形不符时回空串，卡上该段整块省略。
    """
    first = (body or "").split("\n", 1)[0]
    parts = [segment.strip() for segment in first.split("·")]
    return parts[1] if len(parts) >= 3 and parts[1] else ""


def build_news_card_content(
    items: Any,
    *,
    label: str,
    date_text: str = "",
    config: Any | None = None,
) -> dict[str, Any]:
    """条目列表 → 新闻摘要卡 payload（纯构造、零 IO；能力层与测试共用）。

    载荷键的**唯一真相源**是 ``bridge.render_news_digest_card_html`` 的取数面
    （``domains/render/card_render/bridge.py:1879`` 起）与其模板
    ``news_digest_card.html``：``title/sub/foot`` + ``items=[{source,time,name,
    snip}]`` + ``bot_name/bot_avatar_url/feature_label``；``platform_color`` 故意
    不填——无平台语境的快讯卡按 bridge 缺省落守岸人本命蓝，不随内容漂移。
    条目 URL 一律**不上卡**（``NewsItem.url`` 被有意丢弃）：二十条链接刷在一张
    图上既不可点也是刷屏面，要读原文她把链接发回来即可。
    """
    card_items: list[dict[str, str]] = []
    for item in items or ():
        name = _display_text(getattr(item, "title", ""))
        if not name:
            # 无标题的条目连文本快报都不会出现（parse_feed 已跳过），这里同样不留空行。
            continue
        card_items.append(
            {
                "source": _display_text(getattr(item, "source", "")),
                "time": _published_label(item),
                "name": name,
                "snip": _display_text(getattr(item, "summary", "")),
            }
        )
    sources = sorted({str(row.get("source") or "").strip() for row in card_items} - {""})
    sub = " · ".join([segment for segment in (date_text, "、".join(sources)) if segment])
    # 署名唯一读法（P-G3 第二波）：人格册按当前生效人格现读 → 兼容显示名 → 空串交
    # 品牌胶囊统一回落；不再自取配置名并手抄「守岸人」。禁 get_login_info（#60★）。
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        active_persona_id,
        current_bot_nickname,
    )

    bot_name = current_bot_nickname(active_persona_id(config), config=config)
    from plugins.bot_unified_runtime.domains.render.bot_avatar import bot_avatar_uri

    return {
        "title": f"{_CARD_FEATURE_LABEL} · {label}",
        "sub": sub,
        "foot": _CARD_FOOT,
        "items": card_items,
        "bot_name": bot_name,
        "bot_avatar_url": str(bot_avatar_uri(config) or ""),
        "feature_label": _CARD_FEATURE_LABEL,
    }


def news_card_digest(payload: dict[str, Any]) -> str:
    """稳定文件名摘要：同一批条目重复出图覆盖同一文件，不喂爆卡片目录。"""
    material = "|".join(
        f"{row.get('source')}={row.get('time')}={row.get('name')}={row.get('snip')}"
        for row in (payload.get("items") or ())
    )
    material = f"{payload.get('title')}||{payload.get('sub')}||{material}"
    return hashlib.sha1(material.encode("utf-8", "ignore")).hexdigest()[:12]


def _render_card(
    payload: dict[str, Any],
    *,
    render_backend: Any | None,
    card_dir: str,
) -> str:
    """出图：成功返回 PNG 路径，任何一步不行都回空串（调用方降级纯文本）。

    兜底覆盖「后端不可用 / render_card 抛异常 / 落盘失败 / 超时」四类，一律
    不整条不回——本能力拿到的永远是那份完整纯文本，卡只是加在上面。
    """
    if render_backend is None or not getattr(render_backend, "available", False):
        return ""
    try:
        from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
            render_html_card,
        )
        from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
            render_news_digest_card_html,
        )

        return str(
            render_html_card(
                render_news_digest_card_html(payload),
                stem=_CARD_STEM,
                digest=news_card_digest(payload),
                backend=render_backend,
                card_dir=card_dir,
                keep=_CARD_KEEP,
                viewport=_CARD_VIEWPORT,
            )
            or ""
        )
    except Exception:  # noqa: BLE001 - 渲染失败回退纯文本快报，契约零破坏。
        return ""


def build_news_capability(
    config: Any | None = None,
    *,
    render_backend: Any | None = None,
    card_dir: str = "",
) -> Any:
    """构建快报能力闭包；超时/缓存时长/条数可由配置覆盖。

    ``bot_news_enabled`` 开关由基层路由（base_router news_match）检查，
    这里只负责把抓取结果装进 CapabilityResult；抓取为空时给降级文案，
    绝不阻塞会话。

    ``render_backend``：**由装配层注入**的卡片渲染后端（root ``__init__.py`` 的
    ``_build_news_with_backend``）。缺省 ``None`` = 不出卡、输出与接卡前逐字段
    同形——这也是定时推送侧的正确形态（推送保持纯文本是既有裁定，别往这里塞后端）。
    ``card_dir`` 空串 = 读配置 ``bot_card_render_dir``（缺省 ``data/cards``，
    经 ``runtime_paths`` 重映射到 Runtime，不落源码树）。
    """

    resolved_card_dir = card_dir or str(
        getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
    )

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        del decision
        category = extract_news_category(message.plain_text)
        label = CATEGORY_LABELS.get(category, CATEGORY_LABELS["mix"])
        items = fetch_headlines(
            category,
            timeout_seconds=float(
                getattr(config, "bot_news_timeout_seconds", 6.0) or 6.0
            ),
            cache_seconds=float(
                getattr(config, "bot_news_cache_seconds", 600.0) or 600.0
            ),
            max_items=int(getattr(config, "bot_news_max_items", 20) or 20),
        )
        if not items:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.news",
                kind="text",
                body=_empty_degraded_text(),
                audit_tags=["capability:news", "news:fetch_failed"],
            )
        body = format_news_brief(items, label)
        card = _render_card(
            build_news_card_content(
                items, label=label, date_text=_brief_date_text(body), config=config
            ),
            render_backend=render_backend,
            card_dir=resolved_card_dir,
        )
        # 三种出卡结果分开记账，别把「没注入后端」读成「渲染失败」：
        # rendered=卡已同发；failed=后端在场却没出图（要看日志）；disabled=压根没给后端。
        if card:
            card_tag = "news_card_rendered"
        elif render_backend is None:
            card_tag = "news_card_disabled"
        else:
            card_tag = "news_card_failed"
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.news",
            kind="mixed" if card else "text",
            title=f"今日快报 · {label}",
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "capability:news",
                f"news_items:{len(items)}",
                f"news_category:{category}",
                card_tag,
            ],
        )

    return capability
