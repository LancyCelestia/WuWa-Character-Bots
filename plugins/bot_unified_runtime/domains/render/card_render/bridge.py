"""通用卡片渲染桥接。

移植并适配自一个 MIT 许可的开源卡片渲染上游项目 core/render_html/bridge.py
（完整出处与许可声明见 docs/THIRD_PARTY_NOTICES.md，
Copyright (c) 2024 Les Freire）。

职责：
- parse_to_render_payload(item)：把 PlatformParse（含可选 page_type/badge/
  detail）转换为字段完整的 RenderPayload；
- render_universal_card_html(payload_dict)：合并默认值并用 Jinja2 渲染模板，
  所有顶层变量都有默认值，字段缺失时对应区块整体隐藏；
- QR 码由项目依赖 qrcode[pil] 生成；异常时隐藏二维码区块，不阻断卡片渲染。
"""

from __future__ import annotations

import base64
import functools
import hashlib
import html
import io
import json
import os
import re
import threading
import time
import urllib.parse
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any

import jinja2

from plugins.bot_unified_runtime.domains.render.card_render.mica_shell import (
    BRAND_CAPSULE_CSS,
    brand_capsule_html,
    drift_blobs_html,
    mica_decor_css,
    render_root_tokens,
)
from plugins.bot_unified_runtime.domains.render.card_render.models import (
    ForwardPayload,
    RenderPayload,
)
from plugins.bot_unified_runtime.domains.render.render_backends import (
    build_render_backend,
    get_shared_render_backend,
)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR), encoding="utf-8"),
    autoescape=True,
)

# S79 CARD-TEXT-RESIDUAL：卡片模板内「其余形态」硬编码中文文案的唯一中央落点。
# 模板侧只留参数引用（card_text.<键>），字面量本体只住这一张表；
# 由 _ENV.globals 单点注册，故全仓只有这一处注入点（禁第二真身）。
_CARD_TEXT: dict[str, str] = {
    # song_candidates.html：候选行 artist/album 全空时的元信息占位。
    "song_meta_fallback": "未知歌手",
    # error_card.html：help_text 为空串/未定义时的求助指引回落（default(..., true) 语义）。
    "error_help_fallback": "把这张卡截图发给创造者即可，信息已齐备且脱敏。",
    # universal_card.html：直播封面/截图 img alt 文本（无障碍面）。
    "live_cover_alt": "直播封面",
    "live_screenshot_alt": "直播截图",
    # S95 CARD-STATIC-TEXT-65：模板静态中文文本节点唯一参数源（同串只此一处，
    # 模板侧只留 {{ card_text.<键> }} 参数引用；键名 static_<模板缩写>_<全局序>。
    # 键名→值可复跑现算：python /tmp/s95_tool.py verify
    "static_aff_01": '好感查看',
    "static_aff_02": '你与我之间的氛围（印象好感',
    "static_aff_03": '好感随言行连续累积：说话温度',
    "static_aff_04": '相处时长',
    "static_aff_05": '第一印象',
    "static_aff_06": '我当天的状态，平滑变化、没有固定加几减几；久不联系慢慢回归基准，难听的记忆会随时间淡去',
    "static_aff_07": '档位',
    "static_aff_08": '回应方式（同一句话）',
    "static_aff_09": '对你',
    "static_aff_10": '印象好感度：由你的言行长期累积，只影响语气，不外显为标签',
    "static_aff_11": '你对',
    "static_aff_12": '表达倾向：你说出口的话里友好成分的加权比例（估算值）',
    "static_aff_13": '好感区间',
    "static_aff_14": '档0',
    "static_aff_15": '友善（基准',
    "static_aff_16": '任何档位都保持人格与体面',
    "static_err_17": '守',
    "static_err_18": '泰缇斯系统',
    "static_err_19": '触发回显',
    "static_err_20": '栈摘录（末',
    "static_err_21": '帧，路径已脱敏）',
    "static_err_22": '定位与原因',
    "static_err_23": '配置快照（白名单',
    "static_err_24": '值已脱敏）',
    "static_err_25": '版本与构建',
    "static_err_26": '平台与协议',
    # static_err_27（旧「与时间」，与模板侧 'IDs ' 拼接成机读节题）已由
    # static_err_32「标识与时间」整词取代，零消费点后从表退役（不留死键）。
    # 2026-09-25 诊断卡补要素：⑪自我审查＋⑫debug 建议、⑬超管联系方式两段落。
    # 标题明写「推测」是刻意的——这格不是确诊，不许把没核过的归因摆成结论。
    "static_err_28": '我自查的大概原因（推测）与建议',
    "static_err_29": '可以找谁',
    # 无栈那一支（运行时告警卡结构上没有 traceback）的节标题：详情行照样要出，
    # 但标题不能写「栈摘录（末 0 帧）」。
    "static_err_30": '报错详情',
    # goal-7 说人话波（2026-09-25）：卡头英文机读标签与「IDs」节题中文化
    #（模板侧只留参数引用，见 error_card.html 头注）。
    "static_err_31": '运行诊断',
    "static_err_32": '标识与时间',
    # 渲染统一波（2026-10-03）error 卡人话化：head 徽章异常类名 → 人话标签。
    # 映射「类名 → 键」住 _EXC_TYPE_LABEL_KEYS，未登记类名回落 static_err_37；
    # 原类名保留在栈摘录次要行（.stack-head），机器证据不丢。
    "static_err_33": '等待超时',
    "static_err_34": '能力执行超时',
    "static_err_35": '模型服务异常',
    "static_err_36": '网络连接异常',
    "static_err_37": '程序异常',
    "static_fin_28": '数据时间',
    "static_mkt_29": '全球股指速览',
    "static_song_30": '找到',
    "static_song_31": '首「',
    "static_song_32": '」相关歌曲',
    "static_song_33": '内有效',
    "static_song_34": '想听哪首就',
    "static_song_35": '直接回复它的序号数字',
    "static_song_36": '（如',
    "static_song_37": '），也可以说「点歌',
    "static_song_38": '内有效，超时不回复则不播放，可重新点歌。',
    "static_uni_39": '亿',
    "static_uni_40": '万',
    "static_uni_41": '动态',
    "static_uni_42": '帖子',
    "static_uni_43": '视频',
    "static_uni_44": '番剧',
    "static_uni_45": '内容摘要',
    "static_uni_46": '热评',
    "static_uni_47": '参展嘉宾',
    "static_uni_48": '预约',
    "static_uni_49": '直播',
    "static_uni_50": '空间',
    "static_uni_51": '收藏夹',
    "static_uni_52": '编辑于',
    "static_uni_53": '直播中',
    "static_uni_54": '等级',
    "static_uni_55": '高能榜:',
    "static_uni_56": '分P列表',
    "static_uni_57": '(共',
    "static_uni_58": '置顶',
    "static_uni_59": '评论区',
    "static_uni_60": '已直播',
    "static_uni_61": '人气',
    "static_uni_62": '直播间',
    "static_uni_63": '生日:',
    "static_uni_64": '加入:',
    "static_uni_65": '页面内容',
    "static_uni_66": '最近动态',
    # news_digest_card.html（B05 快讯域新闻摘要卡）静态中文文案，键名沿用
    # static_<模板缩写>_<全局序>，续上表全局序 67 起。
    "static_news_67": '科技快讯摘要',
    "static_news_68": '条',
    "static_news_69": '每日快报',
    "static_news_70": '暂无可展示的条目',
    # S-T-VISUAL-1（2026-09-26 第 7 项收尾波）：快报卡此前有两枚卡面静态文案
    # 住在**能力域**（domains/subscribe/capabilities/news.py 的 _CARD_FOOT /
    # _CARD_FEATURE_LABEL 字面量）——不在本表＝契约 §二「字面量唯一落点
    # = bridge._CARD_TEXT」对该面失守。值逐字符迁入本表，能力侧改经
    # card_text_value() 取数（foot 的「只允许常量」安全性质不变：仍是
    # 模块级常量，只是真身住这里；tests/test_news_card_outbound.py 的
    # foot 常量锁按值等值断言，迁移两侧同文即绿）。
    "static_news_71": '条目取自各来源的公开订阅源，标题与摘要按原文收录，未作核实。',
    "static_news_72": '今日快报',
}

_ENV.globals["card_text"] = _CARD_TEXT


def card_text_value(key: str) -> str:
    """卡片静态文案登记表公共读口（S-T-VISUAL-1，2026-09-26）。

    卡面静态中文文案的唯一落点是 `_CARD_TEXT`（契约 §二 S79/S95）；能力侧
    需要把某枚文案带进 payload（如快报卡的页脚口径句与功能名）时，经此口
    取数，**不许在自己模块里再抄一份字面量**——抄了就是第二真身，改表不跟随。
    键写错 = 当场 KeyError 并点名可用键（fail-loud）：静默回退会把「没登记」
    伪装成「登记了但为空」，正是模板侧 card_text 空渲染那类病的模块级复现。
    """
    try:
        return _CARD_TEXT[key]
    except KeyError:
        raise KeyError(
            f"卡片文案键未登记: {key!r}（唯一落点 bridge._CARD_TEXT，"
            f"请先入册再引用；已登记 {len(_CARD_TEXT)} 键）"
        ) from None


def card_template_names() -> tuple[str, ...]:
    """卡面模板清单**单一派生取数口**（S-T-VISUAL-1，第 7 项统一波收口）。

    判据与 `scripts/doc_sync.py::_tpl_list` 完全同构：同一 `templates/` 目录、
    同一 `*.html` glob、同一排序——机器册与契约门从此共用一份账。
    背景：此前模板清单在 tests 里存过多本手抄副本（各契约门一本、E03 一本、
    视觉审计一本、供给链与九门各一本 sid→文件名表），后增的 news_digest 面
    没被任一清单数到，脱族数值在门外通行数个波次（「清单没数到它」型假绿，
    见 test_news_digest_card_contract.py 头注）。归一后管辖面恒等于目录现走；
    「模板名 → 面 id / 渲染入口 / 宽度键 / 数字选择器」这类**元数据**仍逐面
    显式登记（不可派生），由各门完备锁执法：新模板入目录即触发登记要求。
    """
    return tuple(sorted(p.name for p in _TEMPLATES_DIR.glob("*.html")))


_TEMPLATE = _ENV.get_template("universal_card.html")

# ==================== 平台配色 / 官方名映射 ====================
# 主题 token 单一来源在 theme_tokens.py（C 方向 UI 统一 2026-09-12）：
# bridge 只保留渲染投影所需的查找表与再导出（含历史别名 `_derive_wash_tokens`，
# echo/debug/usage_cards/templates 直接从本模块导入该私有名，勿删）。
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BRAND_THEME,
    BRAND_WASH_TOKENS,
    CARD_WASH_ALERT,
    CARD_WASH_BLOBS,
    DEFAULT_THEME,
    DIVIDER,
    ERROR_THEME,
    GLASS_EDGE,
    GLASS_FOOT,
    GLASS_MAIN,
    GLOW_ACCENT,
    MONO_FONT_STACK,
    OVERLAY_SCRIMS,
    PLATFORM_FOOTER_LABELS,
    PLATFORM_THEMES,
    RADIUS_CIRCLE,
    RADIUS_INNER_CSS_VARS,
    RADIUS_PILL,
    SCORE_COLD,
    SCORE_HOT,
    SEMANTIC_DANGER,
    SEMANTIC_SUCCESS,
    SEMANTIC_WARNING,
    SHADOW_LEVELS,
    SURFACE_TINTS,
    THEME_ALIASES,
    UNKNOWN_PLATFORM_COLOR,
    ThemeTokens,
    derive_wash_tokens,
    get_platform_theme,
    theme_to_css_vars,
)

PLATFORM_COLORS: dict[str, str] = {
    key: theme.accent for key, theme in PLATFORM_THEMES.items()
}
PLATFORM_COLORS.update(
    {alias: PLATFORM_THEMES[target].accent for alias, target in THEME_ALIASES.items()}
)

PLATFORM_OFFICIAL_NAMES: dict[str, str] = {
    key: theme.display_name for key, theme in PLATFORM_THEMES.items()
}
for _alias, _key in THEME_ALIASES.items():
    PLATFORM_OFFICIAL_NAMES.setdefault(_alias, PLATFORM_THEMES[_key].display_name)
PLATFORM_OFFICIAL_NAMES.setdefault("generic", "Web")

# 兼容别名：跨模块历史导入面（templates.py/usage_cards.py/echo.py/debug.py）。
_derive_wash_tokens = derive_wash_tokens

# 模板“已知键”特殊标签已覆盖的统计键（其余走通用遍历）。
_KNOWN_STAT_KEYS = frozenset({
    "views", "danmaku", "likes", "favorites", "coins", "comments", "reposts", "shares",
    "following", "followers", "user_likes", "total_views", "quotes", "bookmarks",
    "attention", "fansclub", "high_energy_users", "fleet_total", "captain",
    "admiral", "governor", "is_living", "live_level", "top3_rank", "live_viewers",
    "live_rank", "live_watched", "live_popularity", "official_title",
    # 中文键已由 bridge 提炼到直播间字段，避免重复展示。
    "观看", "在线", "人气",
    "粉丝", "关注", "视频数", "专栏数",
    "时长", "发布时间", "pubdate", "duration", "duration_seconds",
    "AV", "av", "avid", "AV号",
})

_DEFAULT_CONTEXT = RenderPayload().to_dict()

# S61 文案单源（2026-09-22，CARD-TEXT-UNIVERSAL-1）：universal 卡统计行「尾随单位串」
# 与标签兜底措辞从模板硬编码上收到本桥接 context 构造段为唯一真身；模板只留
# {{ stat_units.<键> }} 形状引用，渲染字节与迁移前逐字一致（样张 before/after 对拍实证）。
_UNIVERSAL_STAT_UNITS: dict[str, str] = {
    "views": "播放",
    "total_views": "总播放",
    "danmaku": "弹幕",
    "likes": "赞",
    "replies": "回复",
    "favorites": "收藏",
    "coins": "硬币",
    "comments": "评论",
    "reposts": "转发",
    "quotes": "引用",
    "bookmarks": "书签",
    "followers": "粉丝",
    "following": "关注",
    "user_likes": "获赞",
    "videos": "视频",
    "attention": "关注度",
    "fansclub": "粉丝团",
    "high_energy_users": "高能用户",
    "fleet": "舰队",
    "captain": "舰长",
    "admiral": "提督",
    "governor": "总督",
    "live_viewers": "观众",
    "live_rank": "排名",
    "live_watched": "看过",
    "live_popularity": "人气",
    "seen": "人看过",
}
# 标签 falsy 兜底（模板原 default("帖子"/"会员", true) 语义上收，同值同规则）。
_LABEL_POST_FALLBACK = "帖子"
_LABEL_MEMBERS_FALLBACK = "会员"

# vis4 层次化阴影/辉光/表面/分隔线（theme_tokens 单一源，2026-09-13）：非 universal
# 渲染函数与 universal 的 context 段同键同值注入六键——改 theme_tokens 一处，
# 全部模板自动生效。
_VIS4_KEYS: dict[str, str] = {
    "shadow_elev_panel": SHADOW_LEVELS["elev_panel"],
    "glow_accent": GLOW_ACCENT,
    "divider_line": DIVIDER,
    "surface_a": SURFACE_TINTS["tint_a"],
    "surface_b": SURFACE_TINTS["tint_b"],
    "surface_neutral": SURFACE_TINTS["tint_neutral"],
}

# CORE 值册（2026-09-18 统一收尾波 C1/C3/C4/C5/C9）：玻璃两档+描边/遮罩四员/
# 语义五色/等宽字体/内径刻度——与 vis4 六键同一注入管道（_vis4_context 合并
# 返回，各 render_* 上下文同键同值），模板 Jinja 键 + :root CSS 变量（经
# render_root_tokens）双通道可消费；改 theme_tokens 一处=全部卡自动生效。
_CORE_TOKEN_KEYS: dict[str, str] = {
    "glass_main": GLASS_MAIN,
    "glass_foot": GLASS_FOOT,
    "glass_edge": GLASS_EDGE,
    "scrim_badge": OVERLAY_SCRIMS["scrim_badge"],
    "scrim_banner": OVERLAY_SCRIMS["scrim_banner"],
    "scrim_code": OVERLAY_SCRIMS["scrim_code"],
    "scrim_media": OVERLAY_SCRIMS["scrim_media"],
    "semantic_danger": SEMANTIC_DANGER,
    "semantic_success": SEMANTIC_SUCCESS,
    "semantic_warning": SEMANTIC_WARNING,
    "score_hot": SCORE_HOT,
    "score_cold": SCORE_COLD,
    "mono_font_family": MONO_FONT_STACK,
    # 内径刻度投影：--r-inner-xs → radius_inner_xs（与 vis4 键同 snake_case 风格），
    # 键名显式、取值全部出自 RADIUS_INNER_CSS_VARS/RADIUS_PILL/RADIUS_CIRCLE
    # 登记（单一来源，不手抄第二份值）。
    "radius_inner_xs": RADIUS_INNER_CSS_VARS["--r-inner-xs"],
    "radius_inner_sm": RADIUS_INNER_CSS_VARS["--r-inner-sm"],
    "radius_inner_md": RADIUS_INNER_CSS_VARS["--r-inner-md"],
    "radius_inner_lg": RADIUS_INNER_CSS_VARS["--r-inner-lg"],
    "radius_inner_xl": RADIUS_INNER_CSS_VARS["--r-inner-xl"],
    "radius_pill": RADIUS_PILL,
    "radius_circle": RADIUS_CIRCLE,
}


# 通水切换键（v21r3 统一收尾波 C2）：漂移装饰层 CSS/DOM 缺省实例（mica_shell
# 单一来源；与历史手抄 CSS/DOM 逐字节等价，FINMKT 席已实证 finance/market 面
# 字面==生成器输出、DOM==DRIFT_BLOBS_HTML）。经 _vis4_context 注入全部 Jinja
# 渲染上下文，模板整块换 {{ decor_css | safe }} / {{ blobs_html | safe }}。
_DECOR_CSS = mica_decor_css()
_BLOBS_HTML = drift_blobs_html()


def _vis4_context() -> dict[str, str]:
    """全部 Jinja 渲染函数共用的注入段（vis4 + CORE 值册 + 漂移装饰层）。

    返回副本，防调用方误改模块级常量。``decor_css`` / ``blobs_html`` 为通水
    切换键（v21r3 统一收尾波 C2）：漂移色斑层 CSS/DOM 由 ``mica_shell`` 生成器
    单一产出（缺省实例=三斑 46/58/52s 交错，与历史手抄 CSS 逐字节等价），模板
    以 ``{{ decor_css | safe }}`` / ``{{ blobs_html | safe }}`` 消费，手抄副本
    退役。``error_card`` 的 ``wash_blob_mix=24`` 是 ``:root`` token 面参数
    （``_card_root_tokens`` 保留通道），与本键无关。
    """
    context = dict(_VIS4_KEYS)
    context.update(_CORE_TOKEN_KEYS)
    context["decor_css"] = _DECOR_CSS
    context["blobs_html"] = _BLOBS_HTML
    return context


def _capsule_context(
    bot_name: str,
    bot_avatar_url: str,
    feature_label: str,
    bot_name_en: str = "",
) -> dict[str, str]:
    """品牌胶囊上下文（CAP1 2026-09-20，用户裁定「所有图片加胶囊」）。

    组件 CSS/DOM 由 ``mica_shell.brand_capsule_*`` 单一产出，模板以
    ``{{ capsule_css | safe }}``（放进 ``<style>``）与
    ``{{ capsule_html | safe }}``（页脚摆位）消费；摆位 margin 留在各模板
    本地（只属布局，组件样式零手抄）。纯字符串组装，任何输入都不抛
    （铁律 7：渲染面永不因署名件炸整卡）。

    ``bot_name`` 空回落 ``BRAND_THEME.display_name``（中文名单一来源）；
    ``bot_name_en``（2026-09-28 补形参）空回落 ``BRAND_NAME_EN``——**卡面身份要跟着
    生效人格走**，署名由调用侧按人格派生后传入，缺省形态与历史逐字节一致。
    """
    return {
        "capsule_css": BRAND_CAPSULE_CSS,
        "capsule_html": brand_capsule_html(
            bot_name=(bot_name or BRAND_THEME.display_name),
            bot_name_en=bot_name_en,
            avatar_url=bot_avatar_url,
            feature_label=feature_label,
        ),
    }


def _card_root_tokens(
    color: str,
    *,
    phase: float | str = 0.2,
    extras: dict[str, str] | None = None,
    wash_blob_mix: int = 18,
    include_phase: bool = True,
    include_wash: bool = True,
    face: str = "",
) -> str:
    """7 张模板共用的 ``:root`` token 块（转调 ``mica_shell.render_root_tokens``）。

    v21r3 渲染统一步 5 的注入入口：模板里的 ``:root`` 此前是**硬编码字面量**，
    值虽与 ``theme_tokens`` 一致（``test_rendering_contract.py`` 逐条锁定），
    但改 ``theme_tokens`` 不会自动同步——这是真实的分叉风险。接入本函数后，
    公共 token 子集、声明顺序、书写风格由 ``mica_shell`` 单一产出。

    ``accent_dark`` 取「深一档主色」：与模板既有的 ``platform_color_dark``
    （渲染为 ``--accent-dark``）**同源同算法**（``_rgb_to_hex(_darken(rgb))``），
    也与四张 f-string 直拼卡同语义——2026-09-18 用户裁定「统一成 dark」后，
    直拼卡侧原先的 ``--accent-ink`` 已退役，两边同名。

    ``wash_blob_mix`` 默认 18（2026-09-25 起全卡一致，见 render_root_tokens）。

    ``--wash-1..3`` / ``--wash-mist`` 一律按 ``theme_tokens.BRAND_WASH_TOKENS``
    （本命蓝派生）注入，**不跟随各卡 ``--accent``**（2026-09-25 澜汐：背景要在
    守岸人的蓝色标志色上做釉瑚飘逸渐变）。此前按 accent 派生，红系平台卡整张
    壳底被推成粉灰。平台身份仍留在 ``--accent`` 强调线与 ≤35% 的漂移色斑里。

    ``include_phase`` / ``include_wash`` 供 ``universal_card`` 的**基础块**使用：
    该模板有两个 ``:root``，而 ``test_phase_determinism*.py`` 断言全页恰好一处
    ``--phase`` 声明——基础块必须关掉 phase 与 wash（wash 由视频卡块提供，同值）。
    """
    return render_root_tokens(
        accent=color,
        accent_dark=_rgb_to_hex(_darken(_hex_to_rgb(color))),
        phase=phase,
        wash=BRAND_WASH_TOKENS if include_wash else None,
        extras=extras,
        wash_blob_mix=wash_blob_mix,
        include_phase=include_phase,
        include_wash=include_wash,
        face=face,
    )


def _resolve_icon_asset_root() -> Path:
    """Resolve card SVG assets outside the AI workspace when available."""
    configured = os.getenv("BOT_CARD_ASSET_DIR", "").strip()
    if configured:
        return Path(configured).expanduser() / "iconfont"

    # Search ancestors instead of depending on a fixed directory depth.
    # This supports both MyWorkspace\ChatBot and Archive\ChatBot\ChatBot layouts.
    for ancestor in Path(__file__).resolve().parents:
        external = ancestor / "ChatBot_Runtime" / "card_render_assets" / "iconfont"
        if external.is_dir():
            return external

    # Development fallback: preserve the old checked-in layout for restoration.
    return Path(__file__).resolve().parent / "assets" / "iconfont"


_ICON_ASSET_ROOT = _resolve_icon_asset_root()
_METRIC_ICON_FILES = {
    "views": "5375/播放数_32.svg",
    "danmaku": "5375/弹幕数_32.svg",
    "comments": "5375/16_ico_reply.svg",
    "likes": "5375/32_ic_赞.svg",
    "coins": "5375/B币_32.svg",
    "favorites": "5375/收藏_32.svg",
    "shares": "5375/分享_32.svg",
}
_PLATFORM_LOGO_FILES = {
    "bilibili": "../platforms/bilibili.svg",
    "douyin": "../platforms/douyin_user.svg",
    "xiaohongshu": "../platforms/xiaohongshu_user.svg",
    "xhs": "../platforms/xiaohongshu_user.svg",
    "weibo": "../platforms/weibo.svg",
    "youtube": "../platforms/youtube_user.svg",
    "twitter": "../platforms/twitter_x_user.svg",
    "x": "../platforms/twitter_x_user.svg",
    "spotify": "../platforms/spotify_user.svg",
    "apple_music": "../platforms/apple_music_user.svg",
    "facebook": "../platforms/facebook_user.svg",
    "instagram": "../platforms/instagram_user.svg",
}
# 平台页脚标签：单一来源 theme_tokens.PLATFORM_FOOTER_LABELS（契约测试锁定）；
# 未登记平台回退 platform_official_name。
_PLATFORM_FOOTER_LABELS = PLATFORM_FOOTER_LABELS


# ==================== 基础工具 ====================
def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip() if isinstance(value, str) else str(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ==================== 本地图片内联 ====================
# playwright 以 about:blank 起页，file:// 子资源被 Chromium 拒载
# （实测白块）；本地图片（如竖切横图拼接结果）必须内联成 data URL 才能进卡。

_INLINE_MAX_BYTES = 12 * 1024 * 1024


def _inline_local_image(url: Any) -> str:
    """本地图片文件 → data URL；远程/ data:/缺失文件原样返回。"""
    raw = str(url or "").strip()
    if not raw or raw.startswith(("http://", "https://", "data:")):
        return raw
    candidate = Path(raw)
    if not candidate.is_file():
        return raw
    try:
        if candidate.stat().st_size > _INLINE_MAX_BYTES:
            return raw
        suffix = candidate.suffix.lower().lstrip(".") or "jpeg"
        mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
        encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
        return f"data:image/{mime};base64,{encoded}"
    except OSError:
        return raw


def _first_stat_value(stats: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = stats.get(key)
        if value is not None and value != "":
            return value
    return None


def _first_stat_int(stats: dict[str, Any], keys: tuple[str, ...]) -> int:
    return _as_int(_first_stat_value(stats, keys))


def _normalize_av_id(value: Any) -> str:
    """Normalize Bilibili AV variants to digits for the header only."""
    text = _as_str(value).strip()
    if not text:
        return ""
    match = re.search(r"(?i)\bav\s*(\d+)\b", text) or re.search(r"\b(\d{5,})\b", text)
    return match.group(1) if match else text.removeprefix("av").removeprefix("AV")


def _format_timestamp(value: Any) -> str:
    text = _as_str(value)
    if not text:
        return ""
    if text.isdigit() and len(text) >= 10:
        try:
            return datetime.fromtimestamp(int(text)).strftime("%Y-%m-%d %H:%M:%S")  # noqa: DTZ006 - 本地时间有意 naive
        except (OverflowError, OSError, ValueError):
            return text
    return text


def _format_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# ==================== 清晰度角标（vis1r H1 2026-09-12） ====================
# 行业口径按「短边」取档（竖屏 1080×1920 仍是 1080P 而非 2K）；非整档高度
# 向下取档（B 站常见 1088 扫描线 → 1080P）。宽高缺任一边时单边档位有歧义
# （1920×? 可能是 1080P 也可能是 2K），宁可不出角标也不猜：返回空串由模板
# {% if video_quality %} 钩子整块隐藏。
_QUALITY_TIERS: tuple[tuple[int, str], ...] = (
    (4320, "8K"),
    (2160, "4K"),
    (1440, "2K"),
    (1080, "1080P"),
    (720, "720P"),
    (540, "540P"),
    (480, "480P"),
    (360, "360P"),
    (240, "240P"),
)


def _format_video_quality(width: int, height: int) -> str:
    """视频宽高 → 清晰度文案（如 1920×1080 → "1080P"）；宽高不全/无档位返回空串。"""
    if width <= 0 or height <= 0:
        return ""
    tier_side = min(width, height)
    for floor, label in _QUALITY_TIERS:
        if tier_side >= floor:
            return label
    return ""


# ==================== 釉瑚云母洗派生（mica-glass v2 2026-09-12） ====================
# 派生算法与色相锚点已上收 theme_tokens.derive_wash_tokens（单一事实来源，
# 工艺出处=用户裁定两轮收敛：v1 邻近色 pastel；v2 守岸人本命为唯一基底，
# 平台个性只留 --accent accent 与 ≤35% 主色斑透色两层）。本模块经文件头部的
# `_derive_wash_tokens` 别名再导出，历史调用面零变化。


# ==================== 颜色派生 ====================
def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = (color or "").lstrip("#")
    if len(color) != 6:
        return (96, 112, 128)
    try:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (96, 112, 128)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _darken(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(channel * 0.8))) for channel in rgb)  # type: ignore[return-value]


def _lighten(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(
        int(channel + (255 - channel) * 0.12) for channel in rgb
    )  # type: ignore[return-value]


# ==================== 字段映射 ====================
def _map_comment(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        "author": _as_str(raw.get("user") or raw.get("author") or raw.get("name")),
        "avatar": _as_str(raw.get("avatar")),
        "level": _as_str(raw.get("level")),
        "time": _as_str(raw.get("time")),
        "content": _as_str(raw.get("content") or raw.get("text")),
        "likes": _as_str(raw.get("likes")),
        "handle": _as_str(raw.get("handle")),
        "title_badge": _as_str(raw.get("title_badge")),
        "dress": _as_str(raw.get("dress")),
        "replies_count": _as_str(raw.get("replies_count")),
        "is_hot": bool(raw.get("is_hot")),
    }


def _clean_card_summary(summary: str) -> str:
    """卡片简介只留博主原文：去时长/发布时间行与“简介：”前缀；
    保留解析器插入的空行分段（AI 总结/热评分隔），连续空行折叠。"""
    kept: list[str] = []
    for raw_line in (summary or "").splitlines():
        line = raw_line.strip()
        if not line:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        head = line.split("：", 1)[0].split(":", 1)[0].strip()
        if head == "简介":
            content = ""
            if "：" in line:
                content = line.split("：", 1)[1]
            elif ":" in line:
                content = line.split(":", 1)[1]
            if content.strip():
                kept.append(content.strip())
            continue
        if head in {"时长", "视频时长", "发布时间", "时间", "上传时间", "分区"}:
            continue
        kept.append(line)
    while kept and kept[0] == "":
        kept.pop(0)
    while kept and kept[-1] == "":
        kept.pop()
    return "\n".join(kept)




# 审查 L-09：SVG 指标图标×7（_METRIC_ICON_FILES）与平台 logo×12 键
# （_PLATFORM_LOGO_FILES）每次渲染都经 _load_icon_asset 走 read_text 读盘
# +strip——内容进程内不变，重复读盘纯浪费 → 进程内 lru 缓存（容量 64，
# 覆盖 19 个注册键仍有余量）。契约零变化：
# - 返回值与未加缓存前逐位一致；
# - 失败路径不变：lru_cache 不缓存异常，文件缺失/解码失败时每次调用照旧
#   重试读盘再回退 ""（不做负缓存，文件随后出现的场景语义不变）。
# 取舍：键=相对路径，不做 mtime 失效——_ICON_ASSET_ROOT 在 import 期解析
# 后进程内恒定，图标属随包资产（换图=发版行为）；若需热更图标需重启进程。
@functools.lru_cache(maxsize=64)
def _read_icon_asset_cached(relative_path: str) -> str:
    """读盘+去首尾空白；仅成功读取进缓存，异常上抛交调用方回退。"""
    return (_ICON_ASSET_ROOT / relative_path).read_text(encoding="utf-8").strip()


def _load_icon_asset(relative_path: str) -> str:
    """Load an Iconfont SVG for inline rendering（L-09：读盘结果进程内缓存）。"""
    if not relative_path:
        return ""
    try:
        return _read_icon_asset_cached(relative_path)
    except (OSError, UnicodeError):
        return ""


def _first_nonempty_stat(stats: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        value = stats.get(key)
        if value is not None and value != "":
            return value
    return None


_METRIC_DEFINITIONS: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "video": (
        ("views", "播放", ("views", "播放", "播放量", "观看", "浏览量")),
        ("danmaku", "弹幕", ("danmaku", "弹幕", "弹幕数")),
        ("comments", "评论", ("comments", "评论", "评论数")),
        ("likes", "点赞", ("likes", "点赞", "赞", "爱心")),
        ("coins", "投币", ("coins", "投币", "硬币")),
        ("favorites", "收藏", ("favorites", "收藏", "收藏数")),
        ("shares", "转发", ("shares", "转发", "转发数", "分享", "reposts")),
    ),
    "dynamic": (
        ("likes", "点赞", ("likes", "点赞", "赞", "爱心")),
        ("shares", "转发", ("shares", "转发", "转发数", "分享", "reposts")),
        ("comments", "评论", ("comments", "评论", "评论数")),
    ),
    "article": (
        ("views", "浏览量", ("views", "浏览量", "浏览", "阅读", "阅读量")),
        ("likes", "点赞", ("likes", "点赞", "赞", "爱心")),
        ("coins", "投币", ("coins", "投币", "硬币")),
        ("favorites", "收藏", ("favorites", "收藏", "收藏数")),
        ("shares", "转发", ("shares", "转发", "转发数", "分享", "reposts")),
        ("comments", "评论", ("comments", "评论", "评论数")),
    ),
    "note": (
        ("likes", "爱心", ("likes", "爱心", "点赞", "赞")),
        ("favorites", "收藏", ("favorites", "收藏", "收藏数")),
        ("comments", "评论", ("comments", "评论", "评论数")),
        ("shares", "转发", ("shares", "转发", "转发数", "分享", "reposts")),
    ),
    "tweet": (
        ("views", "浏览量", ("views", "浏览量", "浏览", "观看")),
        ("likes", "点赞", ("likes", "点赞", "赞", "喜欢")),
        ("comments", "评论", ("comments", "评论", "回复", "评论数")),
        ("shares", "转发", ("shares", "转发", "转发数", "转推", "分享", "reposts", "retweets")),
    ),
}

# 平台级标签覆盖（VIS-FIX）：只改瓦片标签，不动数据抽取与瓦片结构。
# 抖音语义 shares 应为「分享」（其余平台保持通用「转发」）。
_METRIC_LABEL_OVERRIDES: dict[str, dict[str, str]] = {
    "douyin": {"shares": "分享"},
}


# 新平台页面类型 → 走 raw 指标策略（stats 原键直接进指标栏，无图标）。
_RAW_METRIC_PAGE_TYPES = frozenset(
    {
        "game", "store_page", "market_listing", "community_hub", "ticket",
        "cheese", "charity", "search", "project", "goods", "share_post",
        "share_video", "public_page", "works",
    }
)
_RAW_METRIC_PLATFORMS = frozenset({"steam", "epic", "mihuashi", "huajia", "facebook"})


def _metric_kind(platform: str, kind: str, page_type: str) -> str:
    if platform in {"xiaohongshu", "xhs"}:
        return "note"
    if kind in {"article", "column", "opus"} or page_type in {"article", "column"}:
        return "article"
    if kind == "tweet" or page_type == "tweet":
        # X 专属指标桶：浏览量/点赞/评论/转发（不含弹幕/投币等视频指标）。
        return "tweet"
    if kind in {"dynamic", "post"} or page_type in {"dynamic", "post"}:
        return "dynamic"
    if kind == "video" or page_type == "video":
        return "video"
    if page_type in _RAW_METRIC_PAGE_TYPES or platform in _RAW_METRIC_PLATFORMS:
        # 新平台（Steam/Epic/米画师/画加/Facebook/会员购等）：stats 原键直接上卡。
        return "raw"
    return "generic"


def _build_metric_items(
    platform: str,
    kind: str,
    page_type: str,
    stats: dict[str, Any],
) -> list[dict[str, Any]]:
    metric_kind = _metric_kind(platform, kind, page_type)
    if metric_kind == "raw":
        # raw：无图标指标卡，stats 原键原标签直接展示（最多 7 项）。
        raw_items: list[dict[str, Any]] = []
        for key, value in stats.items():
            if isinstance(value, (dict, list)) or value in (None, ""):
                continue
            raw_items.append(
                {
                    "key": "raw",
                    "label": str(key),
                    "value": value,
                    "icon_svg": "",
                    "source": "none",
                }
            )
            if len(raw_items) >= 7:
                break
        return raw_items
    definitions = _METRIC_DEFINITIONS.get(metric_kind)
    if definitions is None:
        definitions = (
            ("views", "浏览", ("views", "播放", "播放量", "观看", "浏览", "浏览量")),
            ("likes", "点赞", ("likes", "点赞", "赞", "爱心")),
            ("comments", "评论", ("comments", "评论", "评论数")),
            ("shares", "转发", ("shares", "转发", "转发数", "分享", "reposts")),
        )
    label_overrides = _METRIC_LABEL_OVERRIDES.get(platform) or {}
    items: list[dict[str, Any]] = []
    for key, label, aliases in definitions:
        value = _first_nonempty_stat(stats, aliases)
        if value is None:
            continue
        items.append(
            {
                "key": key,
                "label": label_overrides.get(key, label),
                "value": value,
                "icon_svg": _load_icon_asset(_METRIC_ICON_FILES.get(key, "")),
                "source": "iconfont" if key in _METRIC_ICON_FILES else "none",
            }
        )
    return items


def _format_join_date(value: Any) -> str:
    """博主注册日期归一成 YYYY-MM-DD；支持推特/ISO/中文格式，失败返回空。"""
    raw = _as_str(value).strip()
    if not raw:
        return ""
    import datetime

    for fmt in (
        "%a %b %d %H:%M:%S %z %Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y年%m月%d日",
        "%Y/%m/%d",
    ):
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")  # noqa: DTZ007 - 仅取日期。
        except ValueError:
            continue
    match = re.match(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", raw)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return ""


# ==================== 嵌套模型 → 渲染投影 ====================
def flat_projection(item: Any) -> Any:
    """把纯嵌套 ParsedContent 还原成渲染投影字典（渲染边界专用）。

    模型层不再有扁平字段；渲染层统一经本函数把嵌套数据 + 各平台
    ``platform_extra`` 还原为卡片需要的扁平形状（stats/detail 等），
    卡片区块与迁移前保持等价（个别标量会经统一格式化，如发布时间补秒）。
    非 ParsedContent 输入原样返回。
    """
    from plugins.bot_unified_runtime.domains.core.contracts.media import ParsedContent

    if not isinstance(item, ParsedContent):
        return item
    identity = item.identity
    content = item.content
    creator = item.creator
    engagement = item.engagement
    media = list(item.media or [])
    provenance = item.provenance
    content_extras = dict(content.platform_extra or {}) if content else {}
    engagement_extras = dict(engagement.platform_extra or {}) if engagement else {}
    creator_extras = dict(creator.platform_extra or {}) if creator else {}

    platform = identity.platform if identity else ""
    item_id = identity.item_id if identity else ""
    kind = identity.item_kind if identity else ""
    canonical = identity.canonical_url if identity else ""
    title = content.title if content else ""
    summary = content.summary if content else ""
    page_type = str(content_extras.get("page_type") or "")
    badge = str(content_extras.get("badge") or "")
    published_at = content.published_at if content else None

    video_asset = next(
        (asset for asset in media if asset.asset_type == "video"), None
    )

    # 统计栏：统一互动字段 → 卡片已知键（全部在 _KNOWN_STAT_KEYS 内），
    # 平台特有键经 platform_extra 原样透传。
    stats: dict[str, Any] = {}
    if engagement is not None:
        for key, value in (
            ("views", engagement.view_count),
            ("播放次数", engagement.play_count),
            ("likes", engagement.like_count),
            ("comments", engagement.comment_count),
            ("favorites", engagement.favorite_count),
            ("bookmarks", engagement.bookmark_count),
            ("shares", engagement.share_count),
            ("reposts", engagement.repost_count),
            ("quotes", engagement.quote_count),
            ("danmaku", engagement.danmaku_count),
            ("coins", engagement.coin_count),
        ):
            if value is not None:
                stats[key] = value
        if engagement.like_count is None and engagement.heart_count is not None:
            stats["likes"] = engagement.heart_count
    if creator is not None:
        for key, value in (
            ("followers", creator.follower_count),
            ("following", creator.following_count),
            ("posts", creator.post_count),
            ("videos", creator.video_count),
            ("user_likes", creator.received_like_count),
        ):
            if value is not None:
                stats[key] = value
    for key, extra_value in engagement_extras.items():
        if not isinstance(extra_value, (dict, list)):
            stats[key] = extra_value
    if published_at is not None:
        try:
            stats["发布时间"] = published_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            stats["发布时间"] = published_at.strftime("%Y-%m-%d %H:%M:%S")
    if video_asset is not None and video_asset.duration_ms is not None:
        stats["时长"] = video_asset.duration_ms // 1000
    if platform == "bilibili" and item_id.lower().startswith("av"):
        stats["AV号"] = item_id

    # detail：作者/视频/图集/分P/直播/评论/商品/相关等平台扩展原样透传。
    detail: dict[str, Any] = {}
    if creator is not None:
        author: dict[str, Any] = {}
        if creator.name:
            author["name"] = creator.name
        if creator.avatar_url:
            author["avatar"] = creator.avatar_url
        if creator.signature or creator.bio:
            author["signature"] = creator.signature or creator.bio
        if creator.handle:
            author["handle"] = creator.handle
        if creator.platform_creator_id:
            author["uuid"] = creator.platform_creator_id
        verification = creator.verification
        if verification is not None:
            if verification.label:
                author["official_title"] = verification.label
            if verification.type:
                author["official_badge"] = verification.type
            if verification.verified is not None:
                author["verified"] = verification.verified
        if creator.follower_count is not None:
            author["fans"] = creator.follower_count
        if creator.joined_at is not None:
            author["created_at"] = creator.joined_at.isoformat()
        author.update(creator_extras)
        detail["author"] = author
    video: dict[str, Any] = {}
    if video_asset is not None:
        if video_asset.url:
            video["url"] = video_asset.url
        if video_asset.preview_url:
            video["thumbnail_url"] = video_asset.preview_url
        if video_asset.width is not None:
            video["width"] = video_asset.width
        if video_asset.height is not None:
            video["height"] = video_asset.height
        if video_asset.duration_ms is not None:
            video["duration"] = video_asset.duration_ms // 1000
    video_extras = content_extras.get("video")
    if isinstance(video_extras, dict):
        for key, value in video_extras.items():
            video.setdefault(key, value)
    if published_at is not None and "pubdate" not in video:
        video["pubdate"] = int(published_at.timestamp())
    if video:
        detail["video"] = video
    # vis1r H2：音乐署名（MusicTrack 契约字段已由音乐解析器灌入，此前未投影）。
    music = item.music
    if music is not None and music.title:
        detail["music"] = {
            "name": str(music.title),
            "author": "、".join(
                contributor.name
                for contributor in music.contributors
                if getattr(contributor, "name", "")
            ),
        }
    # vis1r H3：话题标签（ContentMetadata.tags 契约字段，github 等解析器已灌）。
    if content is not None:
        tags = [str(tag).strip() for tag in content.tags if str(tag).strip()]
        if tags:
            detail["tags"] = tags
    images = content_extras.get("images")
    if isinstance(images, list):
        detail["images"] = [_inline_local_image(url) for url in images if str(url)]
    for key in (
        "episodes", "live", "comments", "goods", "related", "show",
        "pinned_comment", "hot_comment", "hot_comments",
    ):
        if key in content_extras:
            detail[key] = content_extras[key]

    cover = _inline_local_image(content_extras.get("cover_url"))
    return {
        "platform": platform,
        "item_id": item_id,
        "item_kind": kind,
        "page_type": page_type,
        "badge": badge,
        "title": title,
        "summary": summary,
        "cover_url": cover,
        "canonical_url": canonical,
        "author_name": creator.name if creator else "",
        "stats": stats,
        "detail": detail,
        "parse_depth": provenance.parse_depth if provenance else "deep",
    }


def parse_to_render_payload(item: Any) -> RenderPayload:
    """把 PlatformParse（或等价字典）映射为字段完整的 RenderPayload。

    契约中的 page_type/badge/detail 全部可选；缺省时返回一张空但可渲染的
    卡片（各区块隐藏）。纯嵌套 ParsedContent 先经 ``flat_projection``
    还原成渲染投影字典，再走既有映射逻辑。
    """
    item = flat_projection(item)
    platform = _as_str(_get(item, "platform")).strip().lower()
    kind = _as_str(_get(item, "item_kind")).strip().lower()
    page_type = _as_str(_get(item, "page_type")).strip().lower() or kind
    badge = _as_str(_get(item, "badge")).strip()
    item_id = _as_str(_get(item, "item_id")).strip()
    title = _as_str(_get(item, "title")).strip()
    summary = _as_str(_get(item, "summary"))
    cover = _inline_local_image(_get(item, "cover_url"))
    canonical = _as_str(_get(item, "canonical_url"))

    stats_raw = _as_dict(_get(item, "stats"))
    detail = _as_dict(_get(item, "detail"))
    author = _as_dict(detail.get("author"))
    video = _as_dict(detail.get("video"))
    episodes = _as_list(detail.get("episodes"))
    images = _as_list(detail.get("images"))
    live = _as_dict(detail.get("live"))
    comments_raw = _as_list(detail.get("comments"))
    goods = _as_dict(detail.get("goods"))
    related = _as_list(detail.get("related"))

    payload = RenderPayload()
    payload.platform = platform
    payload.type = kind
    payload.page_type = page_type
    payload.title = title
    payload.summary = summary
    payload.text = summary
    payload.url = canonical
    payload.cover_url = cover
    payload.timestamp = (
        _as_str(_get(item, "timestamp"))
        or _as_str(_get(item, "published_at"))
        or _as_str(video.get("pubdate"))
        or _as_str(_first_stat_value(stats_raw, ("发布时间", "时间", "上传时间", "pubdate")))
    )

    # 作者
    payload.name = _as_str(author.get("name")) or _as_str(_get(item, "author_name"))
    payload.avatar = _as_str(author.get("avatar"))
    payload.signature = _as_str(author.get("signature"))
    payload.handle = _as_str(author.get("handle"))
    payload.author_uuid = _as_str(
        author.get("uuid") or author.get("author_uuid") or author.get("unique_id") or author.get("mid")
    )
    join_date = _format_join_date(
        author.get("created_at") or author.get("joined") or author.get("created_date")
    )
    if join_date:
        payload.profile_join_date = join_date
    payload.follower_count = _as_str(author.get("fans"))
    payload.official_title = _as_str(author.get("official_title"))
    payload.official_badge = (
        badge
        or _as_str(author.get("official_badge"))
        or _as_str(author.get("verified"))
        or _as_str(detail.get("badge"))
    )

    # 各类 ID 标签（UID/Handle/BVID/AV/动态/直播/空间/收藏夹/番剧/帖子）
    payload.uid = item_id
    if kind == "dynamic":
        payload.extra_dynamic_id, payload.uid = item_id, ""
    elif kind == "live":
        payload.extra_live_id, payload.uid = item_id, ""
    elif kind in {"user", "space", "painter"}:
        payload.extra_space_id, payload.uid = item_id, ""
    elif kind == "collection":
        payload.extra_favlist_id, payload.uid = item_id, ""
    elif kind == "bangumi":
        payload.extra_bangumi_id, payload.uid = item_id, ""
    elif kind in {"tweet", "note", "post", "article", "opus"}:
        payload.extra_status_id, payload.uid = item_id, ""
    elif platform == "bilibili" and item_id.upper().startswith("BV"):
        payload.bvid, payload.uid = item_id, ""
    elif platform == "bilibili" and item_id.lower().startswith("av"):
        payload.av_id, payload.uid = item_id, ""
    if platform == "bilibili" and not payload.av_id:
        raw_av = video.get("aid") or _first_nonempty_stat(
            stats_raw, ("AV", "av", "avid", "AV号")
        )
        if raw_av not in (None, ""):
            payload.av_id = _normalize_av_id(raw_av)

    # 正文 / 图片 / 横幅
    payload.banner = (
        _as_str(live.get("keyframe"))
        or _as_str(live.get("cover"))
        or cover
    )
    payload.image_urls = [_inline_local_image(url) for url in images if _as_str(url)]

    # 分 P / 剧集
    pages: list[dict[str, Any]] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        duration = _as_int(
            episode.get("duration_seconds", episode.get("duration", 0))
        )
        page_title = _as_str(episode.get("title")) or (
            f"P{_as_str(episode.get('index'))}" if _as_str(episode.get("index")) else ""
        )
        pages.append(
            {
                "title": page_title,
                "duration": duration,
                "cover": _as_str(episode.get("cover")),
            }
        )
    payload.video_pages = pages

    # 作者指标与内容互动分开：渲染投影产出的 stats 里，只把已知作者键
    # 分进 author_stats，其余按视频/通用键分进 video_stats（未知键保留）。
    explicit_author_stats = _as_dict(_get(item, "author_stats"))
    explicit_video_stats = _as_dict(_get(item, "video_stats"))
    author_keys = (
        "followers", "following", "user_likes", "total_views", "videos", "columns",
        "video_count", "column_count", "粉丝", "关注", "获赞", "总播放", "视频数", "专栏数",
        "帖子数", "media_count",
    )
    video_keys = ("views", "danmaku", "comments", "likes", "coins", "favorites", "shares", "reposts", "播放", "播放量", "观看", "浏览", "浏览量", "弹幕", "弹幕数", "评论", "评论数", "点赞", "赞", "投币", "硬币", "收藏", "收藏数", "转发", "转发数")
    payload.author_stats = explicit_author_stats or {
        key: value for key, value in stats_raw.items() if key in author_keys
    }
    payload.video_stats = explicit_video_stats or {
        key: value for key, value in stats_raw.items() if key in video_keys
    }
    if "reposts" in payload.video_stats and "shares" not in payload.video_stats:
        payload.video_stats["shares"] = payload.video_stats["reposts"]
    if _metric_kind(platform, kind, page_type) != "generic":
        metric_source = {
            key: value
            for key, value in (explicit_video_stats or stats_raw).items()
            if key not in author_keys
        }
        payload.stats_bar_items = _build_metric_items(
            platform,
            kind,
            page_type,
            metric_source,
        )

    # 博主结构化数据（视频/空间解析带上的 粉丝/关注/视频数/专栏数）。
    author_metric_specs = (
        ("followers", "粉丝", ("followers", "粉丝", "fans")),
        ("following", "关注", ("following", "关注")),
        ("videos", "视频", ("videos", "video_count", "视频数")),
        ("columns", "专栏", ("columns", "column_count", "专栏数")),
        ("posts", "帖子", ("posts", "media_count", "帖子数")),
        ("user_likes", "获赞", ("user_likes", "获赞", "获赞与收藏")),
    )
    merged_author_stats = {**author, **payload.author_stats}
    for key, label, aliases in author_metric_specs:
        value = _first_nonempty_stat(merged_author_stats, aliases)
        if value is None:
            value = _first_nonempty_stat(stats_raw, aliases)
        if value in (None, ""):
            continue
        # B 站 post_count 语义是专栏数，作者栏标签跟随平台语义。
        if platform == "bilibili" and key == "posts":
            label = "专栏"
        payload.author_stats.setdefault(key, value)
        payload.author_stat_items.append({"key": key, "label": label, "value": value})
        payload.header_l4_items.append({"label": label, "value": value})

    # 第二行：视频ID / 动态ID / 番剧ID / 商品ID
    if kind == "dynamic":
        payload.header_l2_items.append({"label": "动态ID", "value": item_id})
    elif kind == "bangumi":
        payload.header_l2_items.append({"label": "番剧ID", "value": item_id})
    elif kind in {"goods", "ticket", "mall"}:
        payload.header_l2_items.append({"label": "商品ID", "value": item_id})
    elif platform == "bilibili" and item_id.upper().startswith("BV") or platform == "bilibili" and item_id.lower().startswith("av"):
        payload.header_l2_items.append({"label": "视频ID", "value": item_id})

    # 发布时间：精确到年月日时分秒
    pub_raw = video.get("pubdate") or _first_stat_value(
        stats_raw, ("pubdate", "发布时间", "pub_time")
    )
    if pub_raw is not None:
        payload.timestamp = _format_timestamp(pub_raw)

    # 视频时长 / 简介（从 stats 的常见键提炼）
    duration_raw = video.get("duration") or _first_stat_value(
        stats_raw, ("duration", "duration_seconds", "时长")
    )
    if duration_raw is not None:
        payload.video_duration = _format_duration(_as_int(duration_raw))
    desc_raw = _first_stat_value(stats_raw, ("简介", "desc", "description"))
    if desc_raw is not None:
        payload.video_desc = _as_str(desc_raw)

    # 直播间
    payload.live_title = _as_str(live.get("title"))
    payload.live_cover = _as_str(live.get("cover"))
    payload.live_screenshot = _as_str(live.get("keyframe"))
    area_parts = [
        part
        for part in (_as_str(live.get("parent_area")), _as_str(live.get("area")))
        if part
    ]
    payload.live_area = "/".join(area_parts)
    payload.live_tags = " ".join(
        _as_str(tag) for tag in _as_list(live.get("tags")) if _as_str(tag)
    )
    payload.live_desc = _as_str(live.get("intro"))
    live_start = live.get("start_time")
    if live_start not in (None, ""):
        payload.timestamp = _format_timestamp(live_start)
    payload.live_viewers = _first_stat_int(
        stats_raw, ("live_viewers", "观看", "在线")
    )
    payload.live_popularity = _first_stat_int(
        stats_raw, ("live_popularity", "人气")
    )

    # 评论
    payload.comments = [
        _map_comment(comment)
        for comment in comments_raw
        if isinstance(comment, dict)
    ]
    pinned = _as_dict(detail.get("pinned_comment"))
    hot = _as_dict(detail.get("hot_comment"))
    payload.pinned_comment = _map_comment(pinned) if pinned else None
    payload.hot_comment = _map_comment(hot) if hot else None
    # 热评列表（B 站等解析器存 hot_comments 数组）：映射后取前 3 条进模板。
    hot_list = [
        _map_comment(comment)
        for comment in _as_list(detail.get("hot_comments"))
        if isinstance(comment, dict)
    ]
    if not hot_list and payload.hot_comment is not None:
        hot_list = [payload.hot_comment]
    payload.hot_comments = hot_list[:3]

    # 会员购参展嘉宾（detail.show.guests → 独立卡区）。
    show_data = _as_dict(detail.get("show"))
    payload.show_guests = [
        {
            "name": _as_str(guest.get("name")),
            "description": _as_str(guest.get("description")),
            "avatar": _inline_local_image(guest.get("avatar")),
            "book_num": _as_str(guest.get("book_num") or ""),
        }
        for guest in _as_list(show_data.get("guests"))
        if isinstance(guest, dict) and _as_str(guest.get("name"))
    ][:12]
    # 作者栏"帖子/专栏"计数标签：B 站 post_count 语义是专栏数。
    payload.stats_post_label = "专栏" if platform == "bilibili" else "帖子"

    # 商品信息并入正文（模板无独立 goods 块，先以文本行消费契约字段）
    goods_lines: list[str] = []
    if goods:
        goods_title = _as_str(goods.get("title"))
        if goods_title:
            goods_lines.append(f"商品：{goods_title}")
        brand = _as_str(goods.get("brand"))
        category = _as_str(goods.get("category"))
        if brand or category:
            goods_lines.append(" · ".join(part for part in (brand, category) if part))
        price = _as_str(goods.get("price"))
        origin_price = _as_str(goods.get("origin_price"))
        if price or origin_price:
            prices = " / ".join(part for part in (price, origin_price) if part)
            goods_lines.append(f"价格：{prices}")
        intro = _as_str(goods.get("intro"))
        if intro:
            goods_lines.append(intro)
    if goods_lines:
        payload.text = "\n\n".join(
            part for part in (payload.text, "\n".join(goods_lines)) if part
        )

    # 相关链接 → 转发块（纯文本，渲染前统一转义，避免 XSS）
    forward: ForwardPayload | None = None
    if related:
        related_lines: list[str] = []
        for related_item in related:
            if not isinstance(related_item, dict):
                continue
            related_title = _as_str(related_item.get("title"))
            related_url = _as_str(related_item.get("url"))
            if related_title and related_url:
                related_lines.append(f"{related_title} · {related_url}")
            elif related_title or related_url:
                related_lines.append(related_title or related_url)
        if related_lines:
            forward = ForwardPayload(name="相关链接", text="\n".join(related_lines))
    payload.forward = forward

    # 统计栏：标量统计 + 未知键通用条目
    payload.stats = {
        key: value
        for key, value in stats_raw.items()
        if not isinstance(value, (dict, list))
    }
    payload.stats_extra_items = [
        {"label": _as_str(key), "value": value}
        for key, value in payload.stats.items()
        if key not in _KNOWN_STAT_KEYS
    ]

    # 平台主题色 / 页脚
    color = PLATFORM_COLORS.get(platform, UNKNOWN_PLATFORM_COLOR)
    rgb = _hex_to_rgb(color)
    payload.platform_color = color
    payload.platform_color_rgb = f"{rgb[0]},{rgb[1]},{rgb[2]}"
    payload.platform_color_dark = _rgb_to_hex(_darken(rgb))
    payload.platform_color_light = _rgb_to_hex(_lighten(rgb))
    payload.platform_official_name = PLATFORM_OFFICIAL_NAMES.get(platform) or (
        platform.capitalize() if platform else ""
    )
    payload.platform_footer_label = _PLATFORM_FOOTER_LABELS.get(
        platform,
        payload.platform_official_name,
    )
    payload.platform_logo_svg = _load_icon_asset(_PLATFORM_LOGO_FILES.get(platform, ""))
    return payload


# ==================== E01 漂移相位策展（D2→D1 确定性定格） ====================
# 相位单一事实来源：payload 稳定序列化 sha1 → [0,1) 四位小数，经模板 :root
# 直注 --phase，页面零 JS（原 Math.random 内联脚本已删）。同一 payload 永远
# 定格同一帧（视觉回归可逐像素比对），不同 payload 仍各有姿态；与渲染缓存
# 键同源思路（docs/design/visual-effects-catalog.md §E01 / 管线规格 §4.2.2）。
# digest 剥离易变字段（updated_at 等）：内容相同仅刷新时间不同的两次渲染
# 定格同一帧，避免「缓存内外两种构图」。
_PHASE_VOLATILE_KEYS = frozenset({"updated_at", "fetched_at", "generated_at"})


def _stable_digest_text(payload: Any) -> str:
    """payload → 稳定序列化文本；不可 JSON 化对象退 repr（进程内仍稳定）。"""
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 - 序列化失败不阻断渲染，退 repr 保稳定。
        return repr(payload)


def stable_payload_digest(payload: Any) -> str:
    """payload → sha1 hexdigest（E01 相位来源；bridge/templates 共用单点）。"""
    if isinstance(payload, dict):
        payload = {
            key: value
            for key, value in payload.items()
            if key not in _PHASE_VOLATILE_KEYS
        }
    return hashlib.sha1(_stable_digest_text(payload).encode("utf-8")).hexdigest()


def digest_phase(digest: str) -> str:
    """digest hexdigest → [0,1) 相位串（4 位小数，CSS --phase 直用）。"""
    spread = int(hashlib.sha1(digest.encode("utf-8")).hexdigest(), 16) % 10000
    return f"{spread / 10000:.4f}"


def payload_phase(payload: Any, *, face: str = "") -> str:
    """payload（+卡面身份 ``face``）→ 确定性相位串（各 render_* 的统一注入入口）。

    goal-7 统一波（2026-09-25）：相位原先只由 payload 决定，**同一 payload
    投给两张不同卡面会得到逐字节同构的色斑构图**——「每张卡的颜色布局不得
    雷同」缺一条腿。``face`` 是以卡面稳定标识（如 ``"market"``）做盐：同一面
    同一 payload 仍恒定定格（双渲逐字节一致、样张基线不碎），跨面则保证
    ``--phase`` 互异 → 钉帧下色斑的 animation-delay 互异 → 构图互异。
    缺省 ``face=""`` 与旧行为逐字节一致（既有单参调用零改动零漂移）。
    """
    digest = stable_payload_digest(payload)
    if face:
        digest = digest + "\x1f" + face
    return digest_phase(digest)


# ==================== 渲染 ====================
def _build_qr_data_url(url: str) -> str:
    """生成链接 QR 码；生成失败时返回空串（区块整体隐藏）。"""
    if not url:
        return ""
    try:
        import qrcode
    except Exception:  # noqa: BLE001 - qrcode 不可用时隐藏 QR 区块，不阻断卡片渲染。
        return ""
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=3,
        )
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:  # noqa: BLE001 - QR 生成失败时隐藏 QR 区块，不阻断卡片渲染。
        return ""


def _coerce_field(field_name: str, value: Any, current: Any) -> Any:
    if field_name == "forward":
        if isinstance(value, (ForwardPayload, dict)):
            return value
        return current
    if isinstance(current, str):
        return _as_str(value)
    if isinstance(current, int):
        return _as_int(value, current)
    if isinstance(current, float):
        return _as_float(value, current)
    if isinstance(current, list):
        return list(value) if isinstance(value, (list, tuple)) else current
    if isinstance(current, dict):
        return _as_dict(value)
    return value if value is not None else current


def _render_payload_from_data(data: dict[str, Any]) -> RenderPayload:
    """任意部分字典 → 完整 RenderPayload。

    先按 PlatformParse 字段映射（page_type/badge/detail 等），再允许
    RenderPayload 风格的显式字段覆盖，二者幂等。
    """
    payload = parse_to_render_payload(data)
    render_fields = {field.name for field in fields(RenderPayload)}
    for key, value in data.items():
        if key in render_fields and value is not None:
            setattr(
                payload,
                key,
                _coerce_field(key, value, getattr(payload, key)),
            )
    return payload


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_RGB_TRIPLET_RE = re.compile(r"^\d{1,3},\s*\d{1,3},\s*\d{1,3}$")


def _safe_css_color(value: Any, fallback: str) -> str:
    """CSS 变量语境只接受 #RRGGBB；非法值（含 CSS 注入载荷）回退中性色。"""
    text = _as_str(value).strip()
    return text if _HEX_COLOR_RE.match(text) else fallback


def _safe_css_rgb(value: Any, fallback: str) -> str:
    text = _as_str(value).strip()
    return text if _RGB_TRIPLET_RE.match(text) else fallback


# data: URL 白名单（评审 M25）：只放行「base64 图片」这一种形态。旧实现在
# data: 分支**原样返回**，而 base64 字符集之外的内容（引号、括号、分号）可以
# 从 `style="background-image:url('{{ banner }}')"` 逃逸出新 CSS 声明——Jinja
# 的 autoescape 只把 `'` 变成 `&#39;`，浏览器解码后照样交给 CSS 解析器。
# 非白名单形态一律返回空串（模板侧表现为无图，安全侧倾斜）。
_CSS_DATA_URL_RE = re.compile(
    r"^data:image/(?:png|jpe?g|gif|webp|bmp|avif);base64,[A-Za-z0-9+/]+={0,2}$",
    re.IGNORECASE,
)


def _css_url_token(url: Any) -> str:
    """CSS url('...') 语境安全化：仅放行 base64 图片 data URL，其余 URL 百分号
    编码，阻断 `') 形式的样式注入。"""
    text = _as_str(url).strip()
    if not text:
        return text
    if text.startswith("data:"):
        return text if _CSS_DATA_URL_RE.match(text) else ""
    return urllib.parse.quote(text, safe=":/?&=%")


def render_universal_card_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染通用卡片 HTML。

    payload_dict 可为：
    - card_payload_from_parse 的输出（page_type/badge/detail 等）；
    - 部分 RenderPayload 风格字典；
    - 空字典 / None（渲染一张空卡片）。

    所有顶层变量都有默认值，因此缺字段只会隐藏区块，不会抛异常。
    """
    data = dict(payload_dict or {})
    payload = _render_payload_from_data(data)

    # 显式覆盖后重新归一化统计字段，保证只渲染标量且通用条目同步。
    payload.stats = {
        key: value
        for key, value in payload.stats.items()
        if not isinstance(value, (dict, list))
    }
    payload.stats_extra_items = [
        {"label": _as_str(key), "value": value}
        for key, value in payload.stats.items()
        if key not in _KNOWN_STAT_KEYS
    ]

    # 模板对 text/summary/forward.text 使用 | safe，这里先统一转义防注入；
    # 同时去掉 时长/发布时间 行与“简介：”前缀，简介只留博主原文。
    payload.text = html.escape(_clean_card_summary(_as_str(payload.text)))
    payload.summary = html.escape(_clean_card_summary(_as_str(payload.summary)))
    if isinstance(payload.forward, ForwardPayload):
        payload.forward.text = html.escape(_as_str(payload.forward.text))
    elif isinstance(payload.forward, dict):
        payload.forward = dict(payload.forward)
        payload.forward["text"] = html.escape(_as_str(payload.forward.get("text")))
    # repost.text 走模板 |safe，逐字段预转义（对纯文本内容渲染产物零变化）。
    repost = payload.repost
    if isinstance(repost, dict):
        escaped_repost = dict(repost)
        escaped_repost["text"] = html.escape(_as_str(escaped_repost.get("text")))
        payload.repost = escaped_repost
    elif repost is not None and isinstance(getattr(repost, "text", None), str):
        try:
            repost.text = html.escape(repost.text)
        except AttributeError:
            pass

    # 平台色与横幅图进入 CSS 语境前做格式校验/编码，阻断样式注入。
    payload.platform_color = _safe_css_color(
        payload.platform_color, UNKNOWN_PLATFORM_COLOR
    )
    payload.platform_color_dark = _safe_css_color(
        payload.platform_color_dark, UNKNOWN_PLATFORM_COLOR
    )
    payload.platform_color_light = _safe_css_color(
        payload.platform_color_light, UNKNOWN_PLATFORM_COLOR
    )
    payload.platform_color_rgb = _safe_css_rgb(payload.platform_color_rgb, "96,112,128")
    payload.banner = _css_url_token(payload.banner)
    payload.cover_url = _css_url_token(payload.cover_url)

    # 可选 QR：优先调用方给的 qrcode，其次尝试生成；缺依赖则隐藏。
    if not _as_str(payload.qrcode) and _as_str(payload.url):
        payload.qrcode = _build_qr_data_url(_as_str(payload.url))

    context = dict(_DEFAULT_CONTEXT)
    context.update(payload.to_dict())
    # S61：统计行单位串单源注入；标签兜底与原 default(x, true) 的 falsy 规则对齐
    # （空/缺失回退、非空原样），渲染字节与迁移前一致。
    context["stat_units"] = _UNIVERSAL_STAT_UNITS
    for _label_key in ("extra_post_label", "stats_post_label"):
        context[_label_key] = _as_str(context.get(_label_key)) or _LABEL_POST_FALLBACK
    context["extra_members_label"] = (
        _as_str(context.get("extra_members_label")) or _LABEL_MEMBERS_FALLBACK
    )
    # 釉瑚云母洗：与 --accent 同点注入（mica-glass v1 2026-09-12，工艺出处=用户裁定）。
    context.update(_derive_wash_tokens(payload.platform_color))
    # vis1r 移交项投影增量（H1-H3，2026-09-12）：RenderPayload 未扩字段的
    # 轻量上下文注入，模板钩子缺数据整块隐藏；显式入参优先于投影推导。
    detail_data = _as_dict(data.get("detail"))
    video_data = _as_dict(detail_data.get("video"))
    context["video_quality"] = _as_str(data.get("video_quality")) or _format_video_quality(
        _as_int(video_data.get("width")), _as_int(video_data.get("height"))
    )
    music_data = _as_dict(detail_data.get("music"))
    context["music_name"] = _as_str(data.get("music_name")) or _as_str(music_data.get("name"))
    context["music_author"] = _as_str(data.get("music_author")) or _as_str(music_data.get("author"))
    topics_raw = data.get("topics") if isinstance(data.get("topics"), list) else detail_data.get("tags")
    context["topics"] = [str(tag) for tag in _as_list(topics_raw) if _as_str(tag)]
    # E01：漂移相位按 payload digest 确定注入（模板 :root --phase 直读）。
    context["phase"] = payload_phase(data, face="universal")
    # vis4 六键 + CORE 值册（玻璃/遮罩/语义色/等宽/内径）同一管道注入——
    # 值全部出自 theme_tokens 单一登记（改一处=全模板自动生效）。
    context.update(_vis4_context())
    # :root 公共段单一产出（v21r3 步 5）。本模板有**两个** :root，但都是全局
    # 选择器：公共段只在视频卡块声明一次（基础块只出 accent 家族与语义色），
    # 否则同一 token 会重复定义（渲染契约测试禁止族内重复）。
    context["root_tokens"] = _card_root_tokens(
        payload.platform_color, phase=context["phase"], face="universal"
    )
    # 品牌胶囊（CAP1）：单一产出经 mica_shell；功能名无能力语境时整段省略
    # （旧模板「feature 空则显 Shorekeeper」的占位语义作废——英文名常驻）。
    context.update(
        _capsule_context(
            _as_str(context.get("bot_name")),
            _as_str(context.get("bot_avatar_url")),
            _as_str(context.get("feature_label")),
        )
    )
    return _TEMPLATE.render(**context)


def _song_candidates_platform_color(platform: str) -> str:
    """候选卡平台色：先精确匹配，再包含关系回退（netease_music→netease）。"""
    color = PLATFORM_COLORS.get(platform)
    if color is not None:
        return color
    matches = [
        (key, value)
        for key, value in PLATFORM_COLORS.items()
        if key and key in platform
    ]
    if matches:
        return max(matches, key=lambda item: len(item[0]))[1]
    return UNKNOWN_PLATFORM_COLOR


# ==================== 全球股指卡（F19 2026-09-12） ====================
_MARKET_CARD_TEMPLATE = _ENV.get_template("market_card.html")


def _spark_points(closes: Any) -> tuple[str, str]:
    """收盘序列（旧→新）→ SVG polyline points + 涨跌描边色（红涨绿跌）。

    点位不足 2 个返回 ("", "")（模板隐藏折线）；任何输入异常同样静默。
    """
    try:
        values = [float(v) for v in (closes or [])]
    except (TypeError, ValueError):
        return "", ""
    if len(values) < 2:
        return "", ""
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    width, height = 128.0, 40.0
    step = width / (len(values) - 1)
    points = " ".join(
        f"{index * step:.1f},{height - (value - low) / span * (height - 4) - 2:.1f}"
        for index, value in enumerate(values)
    )
    # 涨跌描边色消费 theme_tokens 语义色常量（红涨=SEMANTIC_DANGER、
    # 绿跌=SEMANTIC_SUCCESS；直写第二份 hex 字面量已退役，v21r3 通水批）。
    color = SEMANTIC_DANGER if values[-1] >= values[0] else SEMANTIC_SUCCESS
    return points, color


def render_market_card_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染全球股指卡 HTML（mica-glass 规范，F19；C 方向统一扩展 2026-09-12）。

    payload_dict 字段：subtitle、groups=[{name, rows=[{name, price, pct,
    change(涨跌额,可选), cls, trend=[float,...], trend_note(无走势文案,可选)}]}]、
    platform_color、bot_name、bot_avatar_url、feature_label、source_note、
    updated_at、delayed_note。折线由 trend 收盘序列在此生成 polyline points；
    指数无历史走势时展示 trend_note（如 MOEX「暂无历史走势数据」），
    不伪造折线；缺数据区块静默隐藏，不抛异常。
    """
    data = dict(payload_dict or {})
    color = _safe_css_color(
        _as_str(data.get("platform_color")) or UNKNOWN_PLATFORM_COLOR,
        UNKNOWN_PLATFORM_COLOR,
    )
    rgb = _hex_to_rgb(color)
    groups_out: list[dict[str, Any]] = []
    for group in _as_list(data.get("groups")):
        if not isinstance(group, dict):
            continue
        rows_out: list[dict[str, Any]] = []
        for row in _as_list(group.get("rows")):
            if not isinstance(row, dict):
                continue
            points, spark_color = _spark_points(row.get("trend"))
            change = _as_float(row.get("change_pct"), 0.0)
            rows_out.append(
                {
                    "name": _as_str(row.get("name")) or "指数",
                    "price": _as_str(row.get("price")),
                    "pct": _as_str(row.get("pct")),
                    "change": _as_str(row.get("change")),
                    "cls": (
                        "up" if change > 0 else ("down" if change < 0 else "flat")
                    ),
                    "spark_points": points,
                    "spark_color": spark_color,
                    "trend_note": (
                        "" if points else _as_str(row.get("trend_note"))
                    ),
                }
            )
        if rows_out:
            groups_out.append({"name": _as_str(group.get("name")), "rows": rows_out})
    bot_name = _as_str(data.get("bot_name")) or BRAND_THEME.display_name
    bot_avatar_url = _as_str(data.get("bot_avatar_url"))
    # 功能名单一来源（CAPFIX-B 修 I-4）：只认调用方传入（能力侧自带语义），
    # 缺省整段省略——桥内「全球股指」回落字面量是第二处真相，退役。
    feature_label = _as_str(data.get("feature_label"))
    return _MARKET_CARD_TEMPLATE.render(
        platform_color=color,
        platform_color_dark=_rgb_to_hex(_darken(rgb)),
        subtitle=_as_str(data.get("subtitle")),
        groups=groups_out,
        source_note=_as_str(data.get("source_note")),
        updated_at=_as_str(data.get("updated_at")),
        delayed_note=_as_str(data.get("delayed_note")),
        # 多源交叉查验声明（腾讯；通道不可用为空串=区块隐藏）。
        crosscheck_note=_as_str(data.get("crosscheck_note")),
        bot_name=bot_name,
        bot_avatar_url=bot_avatar_url,
        feature_label=feature_label,
        # 品牌胶囊（CAP1）：CSS/DOM 单一产出经 mica_shell，模板摆位本地化。
        **_capsule_context(bot_name, bot_avatar_url, feature_label),
        # 漂移相位按 payload digest 确定注入（E01，D2→D1）。
        phase=payload_phase(data, face="market"),
        # 釉瑚云母洗：与 --accent 同点注入（mica-glass v2 本命基底）。
        **_derive_wash_tokens(color),
        # vis4 层次化阴影/辉光/表面/分隔线（theme_tokens 单一源，同 universal 段）。
        **_vis4_context(),
        # :root 公共段单一产出（v21r3 步 5）：模板里只留 {{ root_tokens }} 与卡特有 token。
        root_tokens=_card_root_tokens(color, phase=payload_phase(data, face="market"), face="market"),
    )


# ==================== 股票/汇率金融卡（C 方向 UI 统一 2026-09-12） ====================
_FINANCE_CARD_TEMPLATE = _ENV.get_template("finance_card.html")
# trend_svg 只放行内部 finance_chart 生成的整段 <svg>…</svg>（数值/转义后
# 文本构成，无属性注入面）；其余形态一律丢弃，模板侧回退趋势文案。
_FINANCE_TREND_SVG_RE = re.compile(r"^<svg[\s\S]*</svg>$")


def render_finance_card_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染股票/汇率金融卡 HTML（mica-glass 规范，stocks/fx 共用壳）。

    payload_dict 字段：title、subtitle、badge、sections=[{name, rows=[
    {label, value, delta, cls(up/down/flat), sub, trend_svg, trend_note}]}]、
    platform_color(可选,缺省守岸人品牌 accent)、source_note、updated_at、
    delayed_note、bot_name、bot_avatar_url、feature_label。
    主题取守岸人品牌基底（金融卡无平台语境，本命洗不随内容漂移）；
    无数据的行内区块静默隐藏，不抛异常。
    """
    data = dict(payload_dict or {})
    color = _safe_css_color(
        _as_str(data.get("platform_color")) or BRAND_THEME.accent,
        BRAND_THEME.accent,
    )
    rgb = _hex_to_rgb(color)
    sections_out: list[dict[str, Any]] = []
    for section in _as_list(data.get("sections")):
        if not isinstance(section, dict):
            continue
        rows_out: list[dict[str, Any]] = []
        for row in _as_list(section.get("rows")):
            if not isinstance(row, dict):
                continue
            raw_svg = _as_str(row.get("trend_svg")).strip()
            trend_svg = raw_svg if _FINANCE_TREND_SVG_RE.match(raw_svg) else ""
            delta = _as_str(row.get("delta"))
            cls = _as_str(row.get("cls")) or "flat"
            rows_out.append(
                {
                    "label": _as_str(row.get("label")) or "—",
                    "value": _as_str(row.get("value")),
                    "delta": delta,
                    "cls": cls if cls in {"up", "down", "flat"} else "flat",
                    "sub": _as_str(row.get("sub")),
                    "trend_svg": trend_svg,
                    "trend_note": (
                        "" if trend_svg else _as_str(row.get("trend_note"))
                    ),
                }
            )
        if rows_out:
            sections_out.append(
                {"name": _as_str(section.get("name")), "rows": rows_out}
            )
    bot_name = _as_str(data.get("bot_name")) or BRAND_THEME.display_name
    bot_avatar_url = _as_str(data.get("bot_avatar_url"))
    # 功能名单一来源（CAPFIX-B 修 I-4）：只认调用方传入（stocks/fx 能力侧
    # 各自给「个股行情/股价/汇率」），缺省整段省略，桥内「金融」退役。
    feature_label = _as_str(data.get("feature_label"))
    return _FINANCE_CARD_TEMPLATE.render(
        platform_color=color,
        platform_color_dark=_rgb_to_hex(_darken(rgb)),
        title=_as_str(data.get("title")) or "金融速览",
        subtitle=_as_str(data.get("subtitle")),
        badge=_as_str(data.get("badge")),
        sections=sections_out,
        source_note=_as_str(data.get("source_note")),
        updated_at=_as_str(data.get("updated_at")),
        delayed_note=_as_str(data.get("delayed_note")),
        bot_name=bot_name,
        bot_avatar_url=bot_avatar_url,
        feature_label=feature_label,
        # 品牌胶囊（CAP1）：单一产出经 mica_shell（见 render_market_card_html 注）。
        **_capsule_context(bot_name, bot_avatar_url, feature_label),
        # 漂移相位按 payload digest 确定注入（E01，D2→D1）。
        phase=payload_phase(data, face="finance"),
        # 釉瑚云母洗：与 --accent 同点注入（品牌 accent → 纯本命基底）。
        **_derive_wash_tokens(color),
        # vis4 层次化阴影/辉光/表面/分隔线（theme_tokens 单一源，同 universal 段）。
        **_vis4_context(),
        # :root 公共段单一产出（v21r3 步 5）。
        root_tokens=_card_root_tokens(color, phase=payload_phase(data, face="finance"), face="finance"),
    )


def render_song_candidates_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染点歌多候选选择卡 HTML（Mica 规范）。

    payload_dict 字段：query、platform、platform_name、ttl_seconds、
    candidates=[{index, name, artist, album}, ...]。
    颜色派生复用 PLATFORM_COLORS（精确匹配→包含回退→中性灰），
    artist/album 缺省段静默省略，任何字段缺失都不抛异常。
    """
    data = dict(payload_dict or {})
    platform = _as_str(data.get("platform")).lower()
    color = _song_candidates_platform_color(platform)
    rgb = _hex_to_rgb(color)

    candidates_raw = _as_list(data.get("candidates"))
    candidates: list[dict[str, Any]] = []
    for offset, cand in enumerate(candidates_raw, start=1):
        if not isinstance(cand, dict):
            continue
        index = _as_int(cand.get("index"), offset) or offset
        candidates.append(
            {
                "index": index,
                "index_label": f"{index:02d}",
                "name": _as_str(cand.get("name")) or "未知歌曲",
                "artist": _as_str(cand.get("artist")),
                "album": _as_str(cand.get("album")),
                "is_top": index <= 3,
            }
        )

    template = _ENV.get_template("song_candidates.html")
    bot_name = _as_str(data.get("bot_name")) or BRAND_THEME.display_name
    bot_avatar_url = _as_str(data.get("bot_avatar_url"))
    # 功能名单一来源（CAPFIX-B 修 I-4）：只认调用方传入（music 能力侧给
    # 「点歌」），缺省整段省略，桥内「点歌」回落退役。
    feature_label = _as_str(data.get("feature_label"))
    return template.render(
        query=_as_str(data.get("query")) or "未知关键词",
        platform=platform,
        platform_name=_as_str(data.get("platform_name"))
        or PLATFORM_OFFICIAL_NAMES.get(platform)
        or (platform.capitalize() if platform else ""),
        platform_color=color,
        platform_color_rgb=f"{rgb[0]},{rgb[1]},{rgb[2]}",
        platform_color_dark=_rgb_to_hex(_darken(rgb)),
        platform_color_light=_rgb_to_hex(_lighten(rgb)),
        ttl_seconds=_as_int(data.get("ttl_seconds"), 300),
        candidates=candidates,
        bot_name=bot_name,
        bot_avatar_url=bot_avatar_url,
        feature_label=feature_label,
        # 品牌胶囊（CAP1）：单一产出经 mica_shell（见 render_market_card_html 注）。
        **_capsule_context(bot_name, bot_avatar_url, feature_label),
        # 漂移相位按 payload digest 确定注入（E01，D2→D1）。
        phase=payload_phase(data, face="song"),
        # 釉瑚云母洗：与 --accent 同点注入（mica-glass v1 2026-09-12）。
        **_derive_wash_tokens(color),
        # vis4 层次化阴影/辉光/表面/分隔线（theme_tokens 单一源，同 universal 段）。
        **_vis4_context(),
        # :root 公共段单一产出（v21r3 步 5）。
        root_tokens=_card_root_tokens(color, phase=payload_phase(data, face="song"), face="song"),
    )


def render_news_digest_card_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染新闻摘要卡 HTML（mica-glass 规范，B05 快讯域紧凑摘要，2026-09-23）。

    payload_dict 字段：title（缺省回落 card_text.static_news_67）、sub（可空）、
    foot（可空，能力侧带口径说明时传入）、items=[{source,time,name(或 title),
    snip(或 summary)}]、platform_color（可空，缺省守岸人品牌 accent）、
    bot_name、bot_avatar_url、feature_label。
    质感与 song_candidates/market 同族（釉瑚云母底 + 液态玻璃浮层 + 漂移色斑 +
    品牌胶囊）；无平台的快讯卡默认落本命蓝，不随内容漂移。空 items 出「暂无」占位，
    任一字段缺失区块静默隐藏，任何输入都不抛异常（铁律 7：渲染失败→纯文本兜底）。
    """
    data = dict(payload_dict or {})
    color = _safe_css_color(
        _as_str(data.get("platform_color")) or BRAND_THEME.accent,
        BRAND_THEME.accent,
    )
    rgb = _hex_to_rgb(color)
    items_out: list[dict[str, Any]] = []
    for item in _as_list(data.get("items")):
        if not isinstance(item, dict):
            continue
        name = _as_str(item.get("name")) or _as_str(item.get("title"))
        if not name:
            continue
        items_out.append(
            {
                "source": _as_str(item.get("source")),
                "time": _as_str(item.get("time")),
                "name": name,
                "snip": _as_str(item.get("snip")) or _as_str(item.get("summary")),
            }
        )
    template = _ENV.get_template("news_digest_card.html")
    bot_name = _as_str(data.get("bot_name")) or BRAND_THEME.display_name
    bot_avatar_url = _as_str(data.get("bot_avatar_url"))
    # 功能名单一来源（CAPFIX-B 修 I-4 同口径）：只认调用方传入，缺省整段省略。
    feature_label = _as_str(data.get("feature_label"))
    return template.render(
        title=_as_str(data.get("title")),
        sub=_as_str(data.get("sub")),
        foot=_as_str(data.get("foot")),
        items=items_out,
        platform_color=color,
        platform_color_rgb=f"{rgb[0]},{rgb[1]},{rgb[2]}",
        platform_color_dark=_rgb_to_hex(_darken(rgb)),
        platform_color_light=_rgb_to_hex(_lighten(rgb)),
        bot_name=bot_name,
        bot_avatar_url=bot_avatar_url,
        feature_label=feature_label,
        # 品牌胶囊（CAP1）：单一产出经 mica_shell（见 render_market_card_html 注）。
        **_capsule_context(bot_name, bot_avatar_url, feature_label),
        # 漂移相位按 payload digest 确定注入（E01，D2→D1）。
        phase=payload_phase(data, face="news_digest"),
        # 釉瑚云母洗：与 --accent 同点注入（品牌 accent → 纯本命基底）。
        **_derive_wash_tokens(color),
        # vis4 层次化阴影/辉光/表面/分隔线（theme_tokens 单一源，同 universal 段）。
        **_vis4_context(),
        # :root 公共段单一产出（v21r3 步 5）。
        root_tokens=_card_root_tokens(color, phase=payload_phase(data, face="news_digest"), face="news_digest"),
    )


def render_affinity_card_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染好感度卡 HTML（Mica 规范，docs/affinity-design.md §9.5）。

    payload_dict 分支字段：mode="group"（rows=[{sender_id, display_name,
    score, tier}]、me_id）与 mode="private"（bot_to_user / user_to_bot =
    {score, tier, bar}、rules=[...]、bot_name）。主色 pc 无平台语境，取
    bot_help_card_color 同源配置，缺省回 UNKNOWN_PLATFORM_COLOR 中性灰。
    任何字段缺失都有默认值，不抛异常。
    vis5 加固（2026-09-13）：rows/steps/tiers/双向面板逐字段归一——score
    None/字符串/缺键不再让模板 `%.1f` 格式化抛 TypeError（契约铁律 7：
    渲染失败→纯文本兜底，桥层先保证可渲染），bar 钳 0-100，cls 白名单。
    """
    data = dict(payload_dict or {})
    template = _ENV.get_template("affinity_card.html")
    pc = _as_str(data.get("pc")) or UNKNOWN_PLATFORM_COLOR

    def _num(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _pair(raw: Any) -> dict[str, Any]:
        src = raw if isinstance(raw, dict) else {}
        score = _num(src.get("score"), 50.0)
        bar = max(0.0, min(100.0, _num(src.get("bar"), score)))
        return {"score": score, "tier": _as_str(src.get("tier")) or "友善", "bar": bar}

    rows_out: list[dict[str, Any]] = []
    for row in _as_list(data.get("rows")):
        if not isinstance(row, dict):
            continue
        rows_out.append(
            {
                "sender_id": _as_str(row.get("sender_id")),
                "display_name": _as_str(row.get("display_name")),
                "score": _num(row.get("score"), 0.0),
                "tier": _as_str(row.get("tier")),
            }
        )
    cls_allowed = {"up", "down", "flat", ""}
    steps_out: list[dict[str, Any]] = []
    for step in _as_list(data.get("steps")):
        if not isinstance(step, dict):
            continue
        value = step.get("value")
        cls_raw = _as_str(step.get("cls"))
        steps_out.append(
            {
                "label": _as_str(step.get("label")),
                "value": "—" if value is None else str(value),
                "cls": cls_raw if cls_raw in cls_allowed else "",
            }
        )
    tiers_out = [
        {
            "label": _as_str(t.get("label")),
            "range": _as_str(t.get("range")),
            "attitude": _as_str(t.get("attitude")),
        }
        for t in _as_list(data.get("tiers"))
        if isinstance(t, dict)
    ]
    bot_name = _as_str(data.get("bot_name")) or BRAND_THEME.display_name
    bot_avatar_url = _as_str(data.get("bot_avatar_url"))
    # 功能名单一来源（CAPFIX-B 修 I-4）：只认调用方传入（affinity 能力侧给
    # 「好感度」），缺省整段省略，桥内「好感度」回落退役。
    feature_label = _as_str(data.get("feature_label"))
    return template.render(
        pc=pc,
        # 釉瑚云母洗：与 --accent 同点注入（mica-glass v1 2026-09-12）。
        **_derive_wash_tokens(pc),
        title=_as_str(data.get("title")) or "好感度",
        subtitle=_as_str(data.get("subtitle")),
        mode=_as_str(data.get("mode")) or "private",
        me_id=_as_str(data.get("me_id")),
        bot_name=bot_name,
        bot_avatar_url=bot_avatar_url,
        feature_label=feature_label,
        # 品牌胶囊（CAP1）：单一产出经 mica_shell（见 render_market_card_html 注）。
        **_capsule_context(bot_name, bot_avatar_url, feature_label),
        bot_score=_as_str(data.get("bot_score")) or "10.0",
        rows=rows_out,
        steps=steps_out,
        tiers=tiers_out,
        bot_to_user=_pair(data.get("bot_to_user")),
        user_to_bot=_pair(data.get("user_to_bot")),
        rules=[rule for rule in (data.get("rules") or []) if isinstance(rule, dict)],
        # 漂移相位按 payload digest 确定注入（E01，D2→D1）。
        phase=payload_phase(data, face="affinity"),
        # vis4 层次化阴影/辉光/表面/分隔线（theme_tokens 单一源，同 universal 段）。
        **_vis4_context(),
        # :root 公共段单一产出（v21r3 步 5）。pc 走 _safe_css_color 归一——
        # 模板侧已改用 |safe 注入，此处必须先把非法值挡在 CSS 之外。
        root_tokens=_card_root_tokens(
            _safe_css_color(pc, UNKNOWN_PLATFORM_COLOR), phase=payload_phase(data, face="affinity"), face="affinity"
        ),
    )


# ==================== 运行异常诊断卡（统一错误报告卡 2026-09-13） ====================
_ERROR_CARD_TEMPLATE = _ENV.get_template("error_card.html")


def _error_kv_rows(raw: Any) -> list[dict[str, str]]:
    """label/value 键值对行归一：脏输入逐项丢弃，绝不抛异常。"""
    rows: list[dict[str, str]] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        label = _as_str(item.get("label"))
        value = item.get("value")
        if not label or value is None or str(value) == "":
            continue
        rows.append({"label": label, "value": _as_str(value)})
    return rows


# 渲染统一波（2026-10-03，error 卡人话化）：head 徽章此前直出裸异常类名
# （TimeoutError 一类机读英文）。人话标签文案住 _CARD_TEXT（S79/S95 单源），
# 本表只做「类名 → 键」映射；未登记类名回落默认键。原类名保留在栈摘录
# 次要行（error_card.html .stack-head），机器证据不丢。
_EXC_TYPE_LABEL_KEYS: dict[str, str] = {
    "TimeoutError": "static_err_33",
    "CapabilityTimeout": "static_err_34",
    "LLMProviderError": "static_err_35",
    "ConnectionError": "static_err_36",
}
_EXC_TYPE_LABEL_DEFAULT_KEY = "static_err_37"


def render_error_card_html(payload_dict: dict[str, Any] | None = None) -> str:
    """渲染运行异常诊断卡 HTML（mica 契约，runtime.error_report 供载荷）。

    payload_dict 字段：human_text（人话区）、exc_type/exc_message、trigger_echo
    （≤80 字符脱敏回显）、stack_lines（末 N 帧，路径已脱敏）、method_pairs/
    config_pairs/version_pairs/env_pairs/id_pairs（label/value 键值行）、
    help_text、bot_name、bot_avatar_url。强调色走 theme_tokens.ERROR_THEME
    （独立系统主题，不进平台注册表）；全字段缺省可渲染（空 payload 契约）。
    """
    data = dict(payload_dict or {})
    # 卡种决定洗色档：``alert``＝运行时告警（蓝→红），其余＝诊断卡（浅蓝→蓝）。
    card_variant = "alert" if str(data.get("card_variant") or "") == "alert" else "calm"
    rgb = _hex_to_rgb(ERROR_THEME.accent)
    bot_name = _as_str(data.get("bot_name")) or BRAND_THEME.display_name
    # 英文署名同口径：调用侧按生效人格派生后传入，空则回落品牌常量（mica_shell 内）。
    bot_name_en = _as_str(data.get("bot_name_en"))
    bot_avatar_url = _as_str(data.get("bot_avatar_url"))
    exc_type_raw = _as_str(data.get("exc_type")) or "EXCEPTION"
    return _ERROR_CARD_TEMPLATE.render(
        platform_color=ERROR_THEME.accent,
        platform_color_dark=_rgb_to_hex(_darken(rgb)),
        card_title=_as_str(data.get("card_title")) or "运行异常",
        exc_type=exc_type_raw,
        # 人话徽章（渲染统一波 2026-10-03）：类名 → 人话标签（文案唯一落点
        # _CARD_TEXT，映射见 _EXC_TYPE_LABEL_KEYS）；原类名仍在栈摘录次要行。
        exc_type_label=_CARD_TEXT[
            _EXC_TYPE_LABEL_KEYS.get(exc_type_raw, _EXC_TYPE_LABEL_DEFAULT_KEY)
        ],
        exc_message=_as_str(data.get("exc_message")),
        human_text=_as_str(data.get("human_text")),
        trigger_echo=_as_str(data.get("trigger_echo")),
        stack_lines=[
            line for line in (_as_str(item) for item in _as_list(data.get("stack_lines")))
            if line
        ],
        method_pairs=_error_kv_rows(data.get("method_pairs")),
        # ⑪⑫⑬ 三段（诊断卡补要素，2026-09-25）：走同一 _error_kv_rows 口径，
        # 不新造第二套行渲染，空载荷下与既有段一样整段缺席。
        self_review_pairs=_error_kv_rows(data.get("self_review_pairs")),
        contact_pairs=_error_kv_rows(data.get("contact_pairs")),
        config_pairs=_error_kv_rows(data.get("config_pairs")),
        version_pairs=_error_kv_rows(data.get("version_pairs")),
        env_pairs=_error_kv_rows(data.get("env_pairs")),
        id_pairs=_error_kv_rows(data.get("id_pairs")),
        help_text=_as_str(data.get("help_text")),
        bot_name=bot_name,
        bot_avatar_url=bot_avatar_url,
        # 品牌胶囊（CAP1）：功能名单一来源（CAPFIX-B 修 I-4）——「诊断」是
        # CAP1 新增、无调用方出处的卡面文案，回落退役；error_report 载荷未带
        # feature_label 时整段省略（卡面「运行异常」语义自有 card_title 承载）。
        # help_text 由模板摆在胶囊旁。
        **_capsule_context(
            bot_name, bot_avatar_url, _as_str(data.get("feature_label")), bot_name_en
        ),
        # 漂移相位按 payload digest 确定注入（E01 同源语义）。
        phase=payload_phase(data, face="error"),
        # 釉瑚云母洗：与 --accent 同点注入（红 accent 派生，mist 保持本命打底）。
        **_derive_wash_tokens(ERROR_THEME.accent),
        # vis4 层次化阴影/辉光/表面/分隔线（theme_tokens 单一源）。
        **_vis4_context(),
        # :root 公共段单一产出（v21r3 步 5）。
        root_tokens=_card_root_tokens(
            ERROR_THEME.accent,
            phase=payload_phase(data, face="error"),
            # 洗色分档（2026-09-25 两轮点名）：两档的 --wash-* 都按本命蓝派生
            # （见 _card_root_tokens），差别只在壳层——
            #   calm  = 不覆盖壳层，走按面派生的 --mica-shell-wash（error 面色标布局）。
            #           旧写法在此另抄一条四段蓝→蓝直线渐变，把"飘逸"做成了
            #           加深色块，已退役。
            #   alert = 蓝→红是这张卡的语义本身，extras 覆盖 --mica-shell-wash，保留登记字面量。
            face="error",
            extras={
                # 色斑两档都要覆盖：render_root_tokens 里 --wash-blob-1 恒与
                # var(--accent) 混（契约"平台色斑"的定义），诊断卡的 accent 是
                # 语义红——不覆盖就会在左上角顶出一块灰粉。
                **({"--mica-shell-wash": CARD_WASH_ALERT}
                   if card_variant == "alert" else {}),
                "--wash-blob-1": CARD_WASH_BLOBS[card_variant],
                "--brand-ink": BRAND_THEME.accent,
            },
        ),
    )


# ==================== Mermaid 流程图卡（G-MERMAID） ====================
_MERMAID_TEMPLATE = _ENV.get_template("mermaid_card.html")
# 等待条件：.card 里出现 SVG 且不是 mermaid 的语法错误弹窗（error bomb）。
# 脚本加载失败（无网）时条件永不成立，由 wait_js 超时兜底返回 None。
_MERMAID_READY_JS = (
    "() => {"
    " const svg = document.querySelector('.card svg');"
    " if (!svg) { return false; }"
    " return (svg.textContent || '').toLowerCase().indexOf('syntax error') === -1;"
    "}"
)
# 渲染后端单例：None=未初始化，False=已探测到不可用（不重复探测）。
_MERMAID_BACKEND: Any = None
_MERMAID_BACKEND_LOCK = threading.Lock()

# 重试预算门（评审 I-1）：单次渲染 attempt 最坏 ≈ 14.2s（set_content 上限
# 8s + wait_js 6s + 余量），外层 renderer._MERMAID_CALL_TIMEOUT_S=20s 钳的
# 只是调用方等待（future.result 超时不能取消在跑任务）。首败已耗时超过
# （20s − 单 attempt 最坏）≈ 5.5s 时放弃重试直接 None——否则最坏总工作量
# 顶到 ~28s，mermaid 专用单 worker 被弃渲染占住，断网期后续消息逐条排队
# 20s 超时；重试只留给「快速失败」（浏览器级故障自愈重建，秒级）场景。
_MERMAID_RETRY_MAX_FIRST_ATTEMPT_S = 5.5


def _resolve_mermaid_backend() -> Any:
    """mermaid 后端解析序（审查 L-04）：共享登记优先，自建兜底。

    优先取进程级共享 playwright 后端——__init__.py 装配的主渲染后端经
    build_render_backend 工厂按「先到先得」登记（见 render_backends 登记
    段），此处只借用引用、从不 close（生命周期归属主后端）。复用后
    thread-local 浏览器模型不变：mermaid 专用线程在共享实例上懒启动自己
    的常驻浏览器，与主卡渲染各线程互不越线程，语义与自持实例一致，只是
    进程内不再并存第二个常驻后端实例（审查 L-04 的内存翻倍来源）。
    登记为空（bot_card_render_enabled=False 未装配主后端 / 单测隔离环境）
    才回退自建，保持既有行为兜底。共享实例不打自愈钩子：不得改写他方
    持有对象的方法，且 render_backends 已于 2026-09-12/09-13 根治关闭
    路径，钩子在共享路径上本就冗余。
    """
    shared = get_shared_render_backend()
    if (
        shared is not None
        and getattr(shared, "available", False)
        and getattr(shared, "name", "") == "playwright"
    ):
        return shared
    backend = build_render_backend("auto")
    if (
        getattr(backend, "available", False)
        and getattr(backend, "name", "") == "playwright"
    ):
        _install_ctx_exit_on_self_heal(backend)
        return backend
    return None


def _get_mermaid_backend() -> Any:
    """懒初始化 mermaid 专用截图后端；仅接受 playwright（需要 wait_js）。

    解析序见 _resolve_mermaid_backend（审查 L-04：优先复用进程级共享的
    主渲染后端实例，不再自建第二个常驻实例）；已缓存结果优先于登记——
    缓存语义不变：None=未初始化，False=已探测到不可用（不重复探测），
    显式注入（单测桩）不被登记覆盖。

    自愈前置钩子（_install_ctx_exit_on_self_heal）的历史背景，仅施加于
    自建兜底实例：历史 bug 是 render_backends._close_thread_browser 对
    playwright ctx 调 .close()（该对象并无 close 方法，AttributeError 被
    静默吞掉），ctx 退出全靠 browser.close() 隐式掐断传输；浏览器「僵死
    但管道未断」时传输掐不断，线程常驻停车中的 asyncio loop，之后同线程
    每次 start() 都报 "Sync API inside the asyncio loop"（实弹复现）。
    render_backends 已于 2026-09-12 根治（_close_thread_browser 改走
    __exit__，launch 重试路径同步堵漏）；本钩子按幂等语义保留为双保险，
    待评审 M-4 清理时整体移除。
    """
    global _MERMAID_BACKEND
    with _MERMAID_BACKEND_LOCK:
        if _MERMAID_BACKEND is None:
            backend = _resolve_mermaid_backend()
            _MERMAID_BACKEND = backend if backend is not None else False
        return _MERMAID_BACKEND or None


def _install_ctx_exit_on_self_heal(backend: Any) -> None:
    """包装后端实例的自愈关闭：先正确退出 playwright ctx，再走原关闭路径。

    只包装 bridge 自持的单例实例（不改 render_backends 源）；ctx.__exit__
    是 playwright 上下文管理器的公开协议（with 语句即此入口），重复退出
    幂等（内部 _exit_was_called 守卫）。上游根治后本钩子可整体移除。
    """
    orig_close = backend._close_thread_browser

    def _close_with_ctx_exit() -> None:
        ctx = getattr(getattr(backend, "_local", None), "playwright_ctx", None)
        if ctx is not None:
            try:
                ctx.__exit__(None, None, None)
            except Exception:  # noqa: BLE001, S110 - 退出失败不阻断原关闭路径。
                pass
        orig_close()

    backend._close_thread_browser = _close_with_ctx_exit


def render_mermaid_html(
    code: str,
    *,
    config: object | None = None,
    feature_label: str = "",
) -> str:
    """渲染 mermaid 流程图卡 HTML（Mica 规范）。

    code 经 Jinja2 autoescape 转义后注入 <pre class="mermaid">，页面内
    从 jsDelivr CDN 加载 mermaid.min.js 并 startOnLoad 自动出图。
    纯字符串组装，不访问网络，不抛异常；釉瑚云母洗按中性灰派生注入
    （mica-glass v1 2026-09-12）。

    ``config``（CAPFIX-B 修 I-7 2026-09-21）：透传给 ``bot_avatar_uri(config)``
    ——本模块其余头像直调点（usage_cards 及能力侧共五处）都是带 config 的
    同一口径，此前裸调把优先级链最高级「显式配置 bot_persona_avatar_url」
    与「磁盘兜底发现」两级丢掉。调用方拿到 config 就传；缺省 None 行为与
    既有一致（进程内登记 > 空）。生产 renderer 侧 config 接线登记待合流
    （renderer.py 非本席可写面）。
    ``feature_label``（CAPFIX-B 修 I-4）：功能名由调用方传入，缺省整段
    省略——旧「流程图」为桥内硬编码第二处真相，退役。
    """
    # CAP1 胶囊头像 → CAPFIX-B：头像仍走 bot_avatar_uri 单一入口，但带
    # config（见 docstring），不在渲染层复制优先级逻辑。
    from plugins.bot_unified_runtime.domains.render.bot_avatar import bot_avatar_uri

    bot_name = BRAND_THEME.display_name
    bot_avatar_url = str(bot_avatar_uri(config))
    feature_label = _as_str(feature_label)
    return _MERMAID_TEMPLATE.render(
        code=code or "",
        bot_name=bot_name,
        bot_avatar_url=bot_avatar_url,
        feature_label=feature_label,
        # 品牌胶囊（CAP1）：单一产出经 mica_shell（见 render_market_card_html 注）。
        **_capsule_context(bot_name, bot_avatar_url, feature_label),
        # 漂移相位按 mermaid 源码 digest 确定注入（E01，D2→D1）。
        phase=payload_phase(code or "", face="mermaid"),
        **_derive_wash_tokens(UNKNOWN_PLATFORM_COLOR),
        # vis4 层次化阴影/辉光/表面/分隔线（theme_tokens 单一源，同 universal 段）。
        **_vis4_context(),
        # :root 公共段单一产出（v21r3 步 5）。本卡主色恒为中性灰（模板原硬编码
        # #607080 = UNKNOWN_PLATFORM_COLOR），与 wash 同源。
        root_tokens=_card_root_tokens(
            UNKNOWN_PLATFORM_COLOR, phase=payload_phase(code or "", face="mermaid"), face="mermaid"
        ),
    )


def render_mermaid_png(
    code: str,
    *,
    config: object | None = None,
    feature_label: str = "",
) -> bytes | None:
    """mermaid 源码 → PNG 字节；任何失败（无网/超时/后端缺失/异常）返回 None。

    走 render_backends 既有截图入口（PlaywrightRenderBackend.render_card），
    通过 wait_js 在截图前等 SVG 真正出现（上限 6s）。首败若为快速失败
    （浏览器级故障：render_card 内部自愈已重建浏览器，重试即用新实例出图
    ——把自愈收益从「下一次调用」提前到「本张卡」）则紧接重试一次、同
    payload；首败已耗时超过 _MERMAID_RETRY_MAX_FIRST_ATTEMPT_S 时放弃重试
    直接 None——否则最坏 ~28s 会越过外层 renderer._MERMAID_CALL_TIMEOUT_S=20s
    （该超时只钳调用方等待，不能取消 worker 上在跑的渲染，弃渲染仍占住
    mermaid 专用单 worker，断网期后续消息逐条排队超时；评审 I-1）。
    重试仍失败（如无网）保持 None 降级。

    ``config``/``feature_label``（CAPFIX-B I-7/I-4）：原样透传
    ``render_mermaid_html``（头像优先级链与功能名单一来源，见该函数）。
    """
    if not (code or "").strip():
        return None
    try:
        backend = _get_mermaid_backend()
        if backend is None:
            return None
        payload = {
            "html": render_mermaid_html(
                code, config=config, feature_label=feature_label
            ),
            "viewport": {"width": 840, "height": 640},
            "wait_ms": 120,
            "wait_js": _MERMAID_READY_JS,
            "wait_js_timeout_ms": 6000,
        }
        started = time.monotonic()
        png = backend.render_card(payload)
        if png is None and (
            time.monotonic() - started <= _MERMAID_RETRY_MAX_FIRST_ATTEMPT_S
        ):
            png = backend.render_card(payload)
        return png
    except Exception:  # noqa: BLE001 - mermaid 渲染绝不抛异常，失败降级文本。
        return None


__all__ = [
    "BRAND_THEME",
    "DEFAULT_THEME",
    "PLATFORM_COLORS",
    "PLATFORM_OFFICIAL_NAMES",
    "PLATFORM_THEMES",
    "ForwardPayload",
    "RenderPayload",
    "ThemeTokens",
    "card_template_names",
    "card_text_value",
    "derive_wash_tokens",
    "digest_phase",
    "flat_projection",
    "get_platform_theme",
    "parse_to_render_payload",
    "payload_phase",
    "render_affinity_card_html",
    "render_error_card_html",
    "render_finance_card_html",
    "render_market_card_html",
    "render_mermaid_html",
    "render_mermaid_png",
    "render_news_digest_card_html",
    "render_song_candidates_html",
    "render_universal_card_html",
    "stable_payload_digest",
    "theme_to_css_vars",
]
