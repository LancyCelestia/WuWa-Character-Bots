"""卡面样张一键渲染：离线出全套卡片 PNG，供重启后人工验收。

用途边界（审查 Q-05）：本脚本只产出离线样张图与基线素材（缺省
%TEMP%/shorekeeper-samples/baseline-20260918/），不写源码树与 Runtime——
不被 plugins/ 任何模块 import，其 payload（含错误卡 help_text 等示例文案）
一律不进生产链路、不进任何 LLM prompt。
覆盖 2026-09-18 渲染统一收口批 **11 面 19 张样张**（11 面 = 7 张 Jinja 模板
+ 4 张直拼卡；payload 结构抄自生产链路对应能力/契约测试）：
- universal：bilibili/netease/未知默认三主题 × 视频/BGV/搜图/音乐四形态；
- market：股指（market_card）+ 大宗商品/国债/北向（finance 卡三形态）；
- finance：个股行情卡（sections + 折线 SVG）；
- affinity：私聊/群聊正常卡 + 脏数据卡（vis5 归一路径实证）；
- song_candidates：点歌候选卡；
- mermaid：流程图卡（本地素材拦截在 render_backends 传输层自动生效，
  本地缺失时放行 jsDelivr CDN——与生产链路同一条路径）；
- help：帮助目录卡（/bot help 总览，echo 直拼卡，真实 72 topic payload）；
- debug：LLM 接入检查卡（管理员诊断直拼卡，domains/ops/admin/debug.py；
  config 面为内置 stub——真实 Config 会读 .env，样张禁触）；
- usage：模型用量账单卡（含渠道子行）；
- media_archive：媒体归档结果卡（通用媒体卡壳；生产归档回执为纯文本，
  本样张为卡面验收供参考形态）；
- error_card：运行异常诊断卡（红强调 + 分区齐全；payload 抄
  tests/test_error_card_contract.py 全量构造，视口同生产 render_error_card_png）。

全部 payload 零外网图片（封面/头像/图库均为脚本内 PIL 生成的 base64 PNG），
mermaid.min.js 走本地素材（ChatBot_Runtime/card_render_assets/mermaid/），
因此整个流程可完全离线渲染。

基线模式（2026-09-18 统一收口批，SAMPLES 席）：main() 走 render_baseline——
每面落 payload.json + card PNG + .sha256 旁车；同 payload 渲染两次比对字节
（双渲确定性自检）；汇总 manifest.json（面→html/png sha256→毫秒→确定性）。
wave-2 改后用 --out 指向 after 目录重跑即可逐面对比。
PNG 字节判据沿革：baseline-20260918 时生产 render_backends 截图路径不冻结
CSS 循环动画（无 animations="disabled"/reduced_motion），漂移色斑随墙钟采样
——相位 digest 只钉动画初相，不钉采样时刻——故当时双渲字节不稳、以
html_sha256 为主判据。2026-09-19 ANIM 钉帧席起 render_backends 截图前对
.card 子树动画 WAAPI 钉时（pause+currentTime=0，冻结在 --phase 负 delay
相位位，探针证与「加载即 paused」参照帧逐字节一致），双渲 PNG 逐字节确定
——**自 baseline-20260919-paused 起 PNG 字节等值为全部面的验收判据**。

用法：
    python scripts/render_card_samples.py                 # 缺省 %TEMP%/shorekeeper-samples/baseline-20260918/
    python scripts/render_card_samples.py --out <dir>     # 指定输出目录（after 对比同理）
    python scripts/render_card_samples.py --only market_index,affinity_group
    python scripts/render_card_samples.py --list          # 只列卡型不渲染（离线快）

退出码：0 = 全部成功；1 = 有卡失败（其余照常出图）；2 = 渲染后端不可用。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.domains.render.card_render import bridge

# mermaid 截图就绪条件与生产同源（bridge 私有常量，避免脚本侧字符串漂移）。
from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
    _MERMAID_READY_JS,
)
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BRAND_THEME,
    get_platform_theme,
)
from plugins.bot_unified_runtime.domains.render.card_render.usage_cards import (
    usage_report_mica_html,
)
from plugins.bot_unified_runtime.output.render_backends import (
    build_render_backend,
)

# ---------------------------------------------------------------------------
# 样张通用素材（PIL 生成 base64 PNG：零外网、零落盘依赖）
# ---------------------------------------------------------------------------

_BILIBILI_ACCENT = get_platform_theme("bilibili").accent
_NETEASE_ACCENT = get_platform_theme("netease").accent
_UNKNOWN_ACCENT = bridge.UNKNOWN_PLATFORM_COLOR


def _gradient_png_data_uri(
    width: int, height: int, top: str, bottom: str, label: str = ""
) -> str:
    """竖向渐变占位图 → base64 PNG data URI（可选角标文字）。"""
    from PIL import Image, ImageDraw

    def _hex_rgb(color: str) -> tuple[int, int, int]:
        return tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]

    image = Image.new("RGB", (width, height))
    top_rgb, bottom_rgb = _hex_rgb(top), _hex_rgb(bottom)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        row_color = tuple(
            round(top_rgb[i] + (bottom_rgb[i] - top_rgb[i]) * ratio)
            for i in range(3)
        )
        draw.line([(0, y), (width, y)], fill=row_color)
    if label:
        draw.text((12, height // 2 - 6), label, fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _avatar_data_uri(accent: str) -> str:
    """UP 主/机器人圆形感占位头像（方形底色 + 深色内芯）。"""
    return _gradient_png_data_uri(96, 96, accent, "#262e38")


_BILI_COVER = _gradient_png_data_uri(960, 540, _BILIBILI_ACCENT, "#1f2440", "SAMPLE COVER")
_BILI_AVATAR = _avatar_data_uri(_BILIBILI_ACCENT)
_SEARCH_IMAGES = [
    # 16:9 横图：画廊 .img-box 宽度撑满卡体，竖图会把样张拉得过长。
    _gradient_png_data_uri(960, 540, "#318ce7", "#101826", "IMG 1"),
    _gradient_png_data_uri(960, 540, "#8b5cf6", "#101826", "IMG 2"),
    _gradient_png_data_uri(960, 540, "#2e9e6b", "#101826", "IMG 3"),
]

_COMMON_FOOTER = {
    "bot_name": "守岸人",
    # 头像缺省即走「守」字圆点兜底（与生产未配头像时同形态）。
    "bot_avatar_url": "",
}


# ---------------------------------------------------------------------------
# universal（bilibili/netease/未知默认 三主题 × 视频/BGV/搜图/音乐 四形态）
# ---------------------------------------------------------------------------


def build_universal_bilibili_video() -> dict[str, Any]:
    """bilibili 主题 · 视频形态（全统计条+简介+QR）。"""
    html_text = bridge.render_universal_card_html(
        {
            "page_type": "video",
            "name": "混元编辑部",
            "title": "【4K】守岸人角色 PV：泰缇斯的全频段守护",
            "author": "混元编辑部",
            "author_avatar_url": _BILI_AVATAR,
            "official_badge": "哔哩哔哩知名科普UP主",
            "platform_color": _BILIBILI_ACCENT,
            "banner": _BILI_COVER,
            "duration_text": "08:21",
            "publish_time_text": "2026-09-12 20:00",
            "avatar_url": _BILI_AVATAR,
            "summary": "本期视频带你看泰缇斯系统的守护逻辑：从路由门禁到出站渲染，"
            "一条消息要过五道关才能落到你眼前。全片 8 分钟，无废话。",
            "stats_bar_items": [
                {"key": "views", "label": "播放", "value": 1520000, "icon_svg": "", "source": "none"},
                {"key": "likes", "label": "点赞", "value": 49000, "icon_svg": "", "source": "none"},
                {"key": "favorites", "label": "收藏", "value": 12000, "icon_svg": "", "source": "none"},
                {"key": "comments", "label": "评论", "value": 3300, "icon_svg": "", "source": "none"},
                {"key": "shares", "label": "转发", "value": 1200, "icon_svg": "", "source": "none"},
            ],
            "author_stat_items": [
                {"key": "followers", "label": "粉丝", "value": 1287401},
            ],
            "av_id": "112874701",
            "bvid": "BV1uvbL6iE8z",
            "url": "https://www.bilibili.com/video/BV1uvbL6iE8z",
            **_COMMON_FOOTER,
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1504, "height": 1000},
        "device_scale_factor": 2,
        "wait_ms": 600,
    }


def build_universal_bilibili_bgv() -> dict[str, Any]:
    """bilibili 主题 · BGV 形态（视频 + BGM 音乐署名行）。"""
    html_text = bridge.render_universal_card_html(
        {
            "page_type": "video",
            "name": "釉瑚日常",
            "title": "【混剪】Iris 燃向 BGV · 守岸人角色回",
            "author": "釉瑚日常",
            "platform_color": _BILIBILI_ACCENT,
            "banner": _gradient_png_data_uri(960, 540, "#1f2440", _BILIBILI_ACCENT, "BGV"),
            "summary": "卡点混剪，BGM 选用《Iris》，节奏对齐 0.75x 变速段。",
            "music_name": "Iris",
            "music_author": "混元 Goo Goo Dolls 乐队 / 翻调：星尘",
            "stats_bar_items": [
                {"key": "views", "label": "播放", "value": 86000, "icon_svg": "", "source": "none"},
                {"key": "likes", "label": "点赞", "value": 7400, "icon_svg": "", "source": "none"},
                {"key": "danmaku", "label": "弹幕", "value": 1820, "icon_svg": "", "source": "none"},
            ],
            "bvid": "BV1AbCdEfGhJ",
            **_COMMON_FOOTER,
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1504, "height": 1000},
        "device_scale_factor": 2,
        "wait_ms": 600,
    }


def build_universal_default_search() -> dict[str, Any]:
    """未知默认主题 · 搜图形态（generic 落模板兜底分支 + 图片画廊）。

    模板主分支（video/search/works 等标准 page_type）不渲染 image_urls
    画廊；搜图形态走 generic 兜底分支（与生产解析兜底同路径）。
    """
    html_text = bridge.render_universal_card_html(
        {
            "page_type": "generic",
            "name": "聚合搜索",
            "title": "「守岸人 高清立绘」的搜图结果",
            "author": "聚合搜索",
            "platform_color": _UNKNOWN_ACCENT,
            "summary": "共命中 3 张样本图（脚本内置占位图，离线渲染验证画廊布局）。",
            "image_urls": _SEARCH_IMAGES,
            **_COMMON_FOOTER,
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1504, "height": 1000},
        "device_scale_factor": 2,
        "wait_ms": 600,
    }


def build_universal_netease_music() -> dict[str, Any]:
    """netease 主题 · 音乐形态（works + 音乐署名行）。"""
    html_text = bridge.render_universal_card_html(
        {
            "page_type": "works",
            "name": "网易云音乐",
            "title": "守岸人（泰缇斯主题曲）",
            "author": "星尘 / 守岸人角色歌企划",
            "platform_color": _NETEASE_ACCENT,
            "music_name": "守岸人",
            "music_author": "星尘",
            "summary": "专辑《泰缇斯原声集》第 3 轨，时长 04:12，FLAC 母带音源。",
            "stats_bar_items": [
                {"key": "plays", "label": "播放", "value": 2860000, "icon_svg": "", "source": "none"},
                {"key": "comments", "label": "评论", "value": 12000, "icon_svg": "", "source": "none"},
            ],
            "publish_time_text": "2026-08-01 发行",
            **_COMMON_FOOTER,
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1504, "height": 1000},
        "device_scale_factor": 2,
        "wait_ms": 600,
    }


# ---------------------------------------------------------------------------
# market：股指 + 大宗商品 + 国债 + 北向
# ---------------------------------------------------------------------------


def _trend_series(base: float, drift: float) -> list[float]:
    """确定性 30 点收盘序列（无随机，样张可复现）。"""
    return [round(base * (1 + drift * index / 29), 2) for index in range(30)]


def _market_common() -> dict[str, Any]:
    return {
        "source_note": "数据源：东方财富 · MOEX ISS（俄罗斯）〔样张占位数据〕",
        "updated_at": "2026-09-14 12:00:00",
        "delayed_note": "部分海外指数行情可能有延迟",
        "crosscheck_note": "交叉核验：腾讯财经 6 指数一致〔样张占位〕",
        **_COMMON_FOOTER,
        "feature_label": "全球股指",
    }


def build_market_index() -> dict[str, Any]:
    """股指卡（market_card.html，分组网格 + 折线）。"""
    html_text = bridge.render_market_card_html(
        {
            "subtitle": "红涨绿跌 · 折线为近 30 个交易日收盘",
            "groups": [
                {
                    "name": "A股",
                    "rows": [
                        {
                            "name": "上证指数",
                            "price": "3286.41",
                            "pct": "+0.62%",
                            "change_pct": 0.62,
                            "change": "+20.31",
                            "trend": _trend_series(3200, 0.03),
                        },
                        {
                            "name": "深证成指",
                            "price": "10421.77",
                            "pct": "-0.35%",
                            "change_pct": -0.35,
                            "change": "-36.58",
                            "trend": _trend_series(10600, -0.02),
                        },
                    ],
                },
                {
                    "name": "美股",
                    "rows": [
                        {
                            "name": "道琼斯",
                            "price": "45230.15",
                            "pct": "+0.18%",
                            "change_pct": 0.18,
                            "change": "+81.42",
                            "trend": _trend_series(44800, 0.01),
                        },
                        {
                            "name": "纳斯达克",
                            "price": "17890.03",
                            "pct": "-0.52%",
                            "change_pct": -0.52,
                            "change": "-93.60",
                            "trend": _trend_series(18200, -0.02),
                        },
                    ],
                },
                {
                    "name": "其他",
                    "rows": [
                        {
                            "name": "莫斯科指数",
                            "price": "2861.44",
                            "pct": "+0.11%",
                            "change_pct": 0.11,
                            "trend_note": "暂无历史走势数据",
                        },
                    ],
                },
            ],
            **_market_common(),
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1160, "height": 1400},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


def _finance_common(feature_label: str) -> dict[str, Any]:
    return {
        "source_note": "数据源：东方财富〔样张占位数据〕",
        "updated_at": "2026-09-14 12:00:00",
        **_COMMON_FOOTER,
        "feature_label": feature_label,
    }


def build_market_commodities() -> dict[str, Any]:
    """大宗商品卡（finance 壳 · 商品形态）。"""
    html_text = bridge.render_finance_card_html(
        {
            "title": "大宗商品速览",
            "subtitle": "红涨绿跌 · 折线为近 30 个交易日收盘",
            "badge": "延迟行情",
            "sections": [
                {
                    "name": "贵金属",
                    "rows": [
                        {
                            "label": "COMEX 黄金",
                            "value": "2612.40",
                            "delta": "+0.86%",
                            "cls": "up",
                            "sub": "美元/盎司",
                            "trend_svg": bridge_trend_svg(_trend_series(2520, 0.04)),
                        },
                        {
                            "label": "COMEX 白银",
                            "value": "30.85",
                            "delta": "-0.42%",
                            "cls": "down",
                            "sub": "美元/盎司",
                        },
                    ],
                },
                {
                    "name": "能源/工业金属",
                    "rows": [
                        {
                            "label": "WTI 原油",
                            "value": "70.28",
                            "delta": "+1.24%",
                            "cls": "up",
                            "sub": "美元/桶",
                            "trend_svg": bridge_trend_svg(_trend_series(68.5, 0.03)),
                        },
                        {
                            "label": "LME 铜",
                            "value": "9186.00",
                            "delta": "0.00%",
                            "cls": "flat",
                            "sub": "美元/吨 · 无 LME 源用 COMEX 铜",
                        },
                    ],
                },
            ],
            "delayed_note": "外盘主力连续口径，LME 无免费源以 COMEX 铜近似",
            **_finance_common("商品行情"),
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1160, "height": 1400},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


def build_market_bond() -> dict[str, Any]:
    """国债收益率卡（finance 壳 · 国债形态）。"""
    html_text = bridge.render_finance_card_html(
        {
            "title": "中美国债收益率速览",
            "subtitle": "交易日 2026-09-12",
            "badge": "延迟数据",
            "sections": [
                {
                    "name": "中国国债（收益率 · 收盘口径）",
                    "rows": [
                        {"label": "2 年期", "value": "1.412%", "delta": "", "cls": "flat"},
                        {"label": "5 年期", "value": "1.618%", "delta": "", "cls": "flat"},
                        {"label": "10 年期", "value": "1.835%", "delta": "", "cls": "flat"},
                        {"label": "30 年期", "value": "2.104%", "delta": "", "cls": "flat"},
                        {"label": "10Y−2Y 期限利差", "value": "+0.423%", "delta": "", "cls": "flat"},
                    ],
                },
                {
                    "name": "美国国债（收益率 · 收盘口径）",
                    "rows": [
                        {"label": "2 年期", "value": "3.562%", "delta": "", "cls": "flat"},
                        {"label": "5 年期", "value": "3.589%", "delta": "", "cls": "flat"},
                        {"label": "10 年期", "value": "3.674%", "delta": "", "cls": "flat"},
                        {"label": "30 年期", "value": "3.988%", "delta": "", "cls": "flat"},
                        {"label": "10Y−2Y 期限利差", "value": "+0.112%", "delta": "", "cls": "flat"},
                    ],
                },
            ],
            "delayed_note": "1 年期暂无稳定免费源，不展示；利差为 10Y−2Y 口径",
            **_finance_common("国债收益率"),
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1160, "height": 1400},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


def build_market_northbound() -> dict[str, Any]:
    """北向资金卡（finance 壳 · 北向形态）。"""
    html_text = bridge.render_finance_card_html(
        {
            "title": "北向资金速览",
            "subtitle": "交易日 2026-09-12",
            "badge": "收盘披露",
            "sections": [
                {
                    "name": "沪深股通（当日成交）",
                    "rows": [
                        {
                            "label": "沪股通",
                            "value": "684.21 亿元",
                            "sub": "当日成交总额 · 8,412,366 笔",
                            "delta": "",
                            "cls": "flat",
                        },
                        {
                            "label": "深股通",
                            "value": "731.05 亿元",
                            "sub": "当日成交总额 · 9,015,204 笔",
                            "delta": "",
                            "cls": "flat",
                        },
                    ],
                },
                {
                    "name": "参考",
                    "rows": [
                        {
                            "label": "沪股通参考 · 上证指数",
                            "value": "3286.41",
                            "delta": "+0.62%",
                            "cls": "up",
                            "sub": "",
                        },
                        {
                            "label": "深股通参考 · 深证成指",
                            "value": "10421.77",
                            "delta": "-0.35%",
                            "cls": "down",
                            "sub": "",
                        },
                    ],
                },
            ],
            "delayed_note": "2024-08 起不再披露北向当日净买入，本卡不含净买入口径",
            **_finance_common("北向资金"),
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1160, "height": 1400},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


# ---------------------------------------------------------------------------
# finance：个股行情卡（sections + 内部折线 SVG）
# ---------------------------------------------------------------------------


def bridge_trend_svg(closes: list[float]) -> str:
    """收盘序列 → finance 卡 trend_svg（走生产 line_chart_svg，离线纯 SVG）。"""
    from plugins.bot_unified_runtime.sources.finance_chart import line_chart_svg

    return line_chart_svg([float(v) for v in closes]).svg


def build_finance_stocks() -> dict[str, Any]:
    """个股行情卡（finance 壳 · 股票形态，9 巨头样张取 2 家示意）。"""
    html_text = bridge.render_finance_card_html(
        {
            "title": "科技巨头行情速览",
            "subtitle": "美东时间 2026-09-12 收盘",
            "badge": "样张占位数据",
            "sections": [
                {
                    "name": "芯片",
                    "rows": [
                        {
                            "label": "英伟达 NVDA",
                            "value": "1,064.28 美元",
                            "delta": "+2.31%",
                            "cls": "up",
                            "sub": "市值 2.61 万亿美元 · 成交 3,214 万股",
                            "trend_svg": bridge_trend_svg(_trend_series(980, 0.08)),
                        },
                        {
                            "label": "AMD",
                            "value": "158.42 美元",
                            "delta": "-0.87%",
                            "cls": "down",
                            "sub": "市值 2,561 亿美元",
                            "trend_svg": bridge_trend_svg(_trend_series(164, -0.04)),
                        },
                    ],
                },
                {
                    "name": "平台",
                    "rows": [
                        {
                            "label": "微软 MSFT",
                            "value": "428.16 美元",
                            "delta": "+0.44%",
                            "cls": "up",
                            "sub": "市值 3.18 万亿美元",
                        },
                        {
                            "label": "字节跳动",
                            "value": "非上市",
                            "delta": "",
                            "cls": "flat",
                            "sub": "无公开市场价格，估值口径见官方公告",
                            "trend_note": "结构性无价格字段（红线）",
                        },
                    ],
                },
            ],
            **_finance_common("个股行情"),
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1160, "height": 1400},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


# ---------------------------------------------------------------------------
# affinity：私聊/群聊正常 + 脏数据
# ---------------------------------------------------------------------------


def build_affinity_private() -> dict[str, Any]:
    """好感度私聊卡（双向面板 + 规则区）。"""
    html_text = bridge.render_affinity_card_html(
        {
            "pc": BRAND_THEME.accent,
            "title": "好感度",
            "subtitle": "与 澜汐 的相处记录",
            "mode": "private",
            "bot_to_user": {"score": 62.4, "tier": "亲近", "bar": 81.2},
            "user_to_bot": {"score": 58.0, "tier": "亲近", "bar": 76.5},
            "rules": [
                {"label": "基准", "text": "基准 10 = 档 0 友善，多因素线性步长"},
                {"label": "边界", "text": "任何档位都不攻击、不强硬、不 R-18"},
            ],
            **_COMMON_FOOTER,
            "feature_label": "好感度",
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1240, "height": 1400},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


def build_affinity_group() -> dict[str, Any]:
    """好感度群聊卡（排行 + 算法说明步骤）。"""
    html_text = bridge.render_affinity_card_html(
        {
            "pc": BRAND_THEME.accent,
            "title": "好感度 · 群聊榜",
            "subtitle": "群 11451489361919810",
            "mode": "group",
            "me_id": "u_shorekeeper",
            "rows": [
                {"sender_id": "u_lancy", "display_name": "澜汐", "score": 78.6, "tier": "亲近"},
                {"sender_id": "u_xiayue", "display_name": "霞月", "score": 71.2, "tier": "亲近"},
                {"sender_id": "u_003", "display_name": "群友·阿波", "score": 34.5, "tier": "熟络"},
                {"sender_id": "u_004", "display_name": "群友·小柚", "score": 12.0, "tier": "友善"},
            ],
            "steps": [
                {"label": "基准因子", "value": "档 3 熟络", "cls": "up"},
                {"label": "说话温度", "value": "偏暖", "cls": "up"},
                {"label": "相处时长", "value": "拉长", "cls": "up"},
                {"label": "当日心情", "value": "平稳", "cls": "flat"},
            ],
            **_COMMON_FOOTER,
            "feature_label": "好感度",
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1240, "height": 1400},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


def build_affinity_dirty() -> dict[str, Any]:
    """好感度脏数据卡（score=None/字符串/bar 越界/非法 cls —— 桥层归一后渲染）。"""
    html_text = bridge.render_affinity_card_html(
        {
            "pc": "not-a-color",
            "mode": "group",
            "rows": [
                {"sender_id": "1", "display_name": "甲", "score": None},
                {"sender_id": "2", "display_name": "乙", "score": "80"},
                {"sender_id": "3"},
                "not-a-dict",
                None,
            ],
            "steps": [
                {"label": "基准", "value": None, "cls": "爆"},
                {"label": "温度", "value": "ok", "cls": ""},
            ],
            "tiers": [{"label": None, "range": None, "attitude": None}],
            **_COMMON_FOOTER,
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1240, "height": 1400},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


# ---------------------------------------------------------------------------
# song_candidates / mermaid / usage / media_archive
# ---------------------------------------------------------------------------


def build_song_candidates() -> dict[str, Any]:
    """点歌候选卡（netease 主题，Top3 高亮）。"""
    html_text = bridge.render_song_candidates_html(
        {
            "query": "晴天",
            "platform": "netease",
            "platform_name": "网易云音乐",
            "ttl_seconds": 300,
            "candidates": [
                {"index": 1, "name": "晴天", "artist": "周杰伦", "album": "叶惠美"},
                {"index": 2, "name": "晴天 (Live)", "artist": "周杰伦", "album": "魔天伦世界巡回演唱会"},
                {"index": 3, "name": "晴天", "artist": "音阙诗听 / 昆玉", "album": "晴天"},
                {"index": 4, "name": "晴天下", "artist": "Keys.io", "album": "雨停了"},
            ],
            **_COMMON_FOOTER,
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 1040, "height": 900},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


_MERMAID_SAMPLE_CODE = """graph TD
    A[用户消息] --> B{路由判定}
    B -->|能力命令| C[能力执行]
    B -->|人格对话| D[LLM 生成]
    C --> E[Review 审核]
    D --> E
    E --> F[渲染出站]
    F --> G[(SendQueue)]"""


def build_mermaid() -> dict[str, Any]:
    """mermaid 流程图卡（本地素材拦截生效；缺失时放行 CDN——同生产路径）。

    payload 结构复刻 bridge.render_mermaid_png（wait_js 等 SVG 真出图），
    但走本脚本共享后端，避免额外起一个浏览器实例。
    """
    return {
        "html": bridge.render_mermaid_html(_MERMAID_SAMPLE_CODE),
        "viewport": {"width": 840, "height": 640},
        "device_scale_factor": 2,
        "wait_ms": 120,
        "wait_js": _MERMAID_READY_JS,
        "wait_js_timeout_ms": 6000,
    }


class _SampleUsageConfig:
    """usage 卡配置面：只消费 bot_help_card_color。"""

    bot_help_card_color = BRAND_THEME.accent


def build_usage_report() -> dict[str, Any]:
    """模型用量账单卡（含渠道子行 .crow）。"""
    html_text = usage_report_mica_html(
        _SampleUsageConfig(),
        kicker="定时报告 · 模型用量",
        title="模型用量账单报告",
        status_label="账单 4.60 元",
        status_kind="ok",
        window_label="09-14 07:00 至 09-14 12:00",
        generated_at="2026-09-14 12:00:00",
        totals={
            "prompt_tokens": 128000,
            "cache_read_tokens": 46000,
            "cache_write_tokens": 12000,
            "completion_tokens": 18600,
            "total_tokens": 204600,
            "calls": 96,
            "cost_milli": 4600,
            "cost_text": "4.60",
            "unpriced_calls": 3,
        },
        model_rows=[
            {
                "model": "glm-4.7-plus",
                "prompt": 96000,
                "cache_read": 42000,
                "cache_write": 11000,
                "completion": 12400,
                "cost_text": "3.86",
                "priced": True,
                "channels": [
                    {"channel": "axonhub-main", "calls": 68, "cost_milli": 3400, "cost_text": "3.40"},
                    {"channel": "axonhub-backup", "calls": 9, "cost_milli": 460, "cost_text": "0.46"},
                ],
            },
            {
                "model": "deepseek-v4-pro",
                "prompt": 32000,
                "cache_read": 4000,
                "cache_write": 1000,
                "completion": 6200,
                "cost_text": "0.74",
                "priced": True,
            },
            {
                "model": "qwen3-vl-32b",
                "prompt": 0,
                "cache_read": 0,
                "cache_write": 0,
                "completion": 0,
                "cost_text": "未计价",
                "priced": False,
            },
        ],
        note="样张占位数据，非真实账单；上方未计价行由 totals.unpriced_calls 自动生成。",
        **_COMMON_FOOTER,
        feature_label="模型用量",
    )
    return {
        "html": html_text,
        "viewport": {"width": 950, "height": 1000},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


def build_media_archive() -> dict[str, Any]:
    """媒体归档结果卡（通用媒体卡壳；生产归档回执为纯文本，此为卡面形态参考）。"""
    from plugins.bot_unified_runtime.output.templates import render_media_card_html

    html_text = render_media_card_html(
        {
            "title": "媒体归档 · 收藏成功",
            "platform": "",
            "author": "cosplay · 原神",
            "cover_url": _gradient_png_data_uri(960, 400, "#8b5cf6", "#101826", "ARCHIVED"),
            "stats": {
                "类别": "cosplay",
                "作品": "原神",
                "角色": "甘雨",
                "大小": "3.4 MB",
            },
            "summary": "VLM 判定：二次元 cosplay 摄影，角色甘雨，置信度良好；"
            "已按 data/media_archive/cosplay/原神/ 落盘（sha256 去重）。\n"
            "〔样张占位数据；生产归档回执为纯文本，本卡供卡面验收参考〕",
            "footer": "",
            **_COMMON_FOOTER,
            "feature_label": "媒体归档",
            "platform_color": "#8b5cf6",
            "platform_color_dark": "#6d46c2",
            "platform_color_rgb": "139,92,246",
        }
    )
    return {
        "html": html_text,
        "device_scale_factor": 2,
        "wait_ms": 300,
    }


def build_help_index() -> dict[str, Any]:
    """帮助目录卡（/bot help 总览：masonry 双栏分区 + 分区内 topic 两栏）。

    payload 抄生产链路：echo.build_help_result 总览页同款——
    body=_help_index_body，sections=_help_index_sections（真实 72 topic），
    视口/缩放/等待与 _try_render_help_image 一致。accent 走本命色
    （生产传 config.bot_help_card_color，样张配置面同 usage 卡取 BRAND_THEME）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        _help_index_body,
        _help_index_sections,
        _help_mica_html,
    )

    is_admin = True  # 管理员视角 topic 最全（公开视角同壳、条目少一档）。
    html_text = _help_mica_html(
        _help_index_body(page=1, is_admin=is_admin),
        is_admin=is_admin,
        bot_name="守岸人",
        bot_avatar_url="",  # 空即走「守」字圆点兜底（同生产未配头像形态）。
        accent_color=BRAND_THEME.accent,
        sections=_help_index_sections(is_admin),
    )
    return {
        "html": html_text,
        "viewport": {"width": 1040, "height": 1200},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


# ---------------------------------------------------------------------------
# debug：LLM 接入检查卡（f-string 直拼卡，domains/ops/admin/debug.py）
# ---------------------------------------------------------------------------


class _SampleLLMSetupConfig:
    """debug LLM 接入检查卡配置面：只消费 _llm_setup_rows/_llm_setup_accent 读取的键。

    样张不装载真实 Config（真实 Config 读 .env，样张禁触）：七个必配键全部
    内置固定值；temperature=3.0 故意越界 → 恰一行标红 + warn 状态，
    卡面语义状态色（红点/黄标）与达标绿点同屏，形态覆盖最全。
    """

    bot_help_card_color = BRAND_THEME.accent
    bot_chat_provider = "openai_compatible"
    bot_chat_model = "gemini-3.8-flash"
    bot_chat_api_key = "env:BOT_AXONHUB_API_KEY"
    bot_chat_base_url = "http://127.0.0.1:8090/v1"
    bot_chat_temperature = 3.0
    bot_chat_max_tokens = 65536
    bot_chat_timeout_seconds = 30.0


def build_debug_llm_setup() -> dict[str, Any]:
    """debug · LLM 接入检查卡（走生产真函数 _llm_setup_rows + _llm_setup_mica_html）。

    相位由 payload_phase digest 钉帧（bridge 单一事实源）；生产本就排除
    config（repr 含内存地址不稳定）——stub 面字段全固定，HTML 逐字节确定。
    视口/缩放/等待与生产 _try_render_llm_setup_image 完全一致。
    """
    from plugins.bot_unified_runtime.domains.ops.admin.debug import (
        _LLM_SETUP_NEXT_ACTIONS,
        _LLM_SETUP_STATUS_LABELS,
        _llm_setup_mica_html,
        _llm_setup_rows,
    )

    config = _SampleLLMSetupConfig()
    status_label, status_kind = _LLM_SETUP_STATUS_LABELS["needs_env_edit"]
    html_text = _llm_setup_mica_html(
        {
            "config": config,
            "status_label": status_label,
            "status_kind": status_kind,
            "message": "守岸人对话链路样张：检测到 1 项超出取值范围（占位数据，非真实环境）。",
            "rows": _llm_setup_rows(config),
            "next_step": _LLM_SETUP_NEXT_ACTIONS["fix_config"],
        }
    )
    return {
        "html": html_text,
        "viewport": {"width": 940, "height": 1000},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


# ---------------------------------------------------------------------------
# error_card：运行异常诊断卡
# ---------------------------------------------------------------------------


def build_error_card() -> dict[str, Any]:
    """运行异常诊断卡（payload 抄 tests/test_error_card_contract.py 全量构造）。

    分区齐全形态：触发回显/栈摘录/触发方法/配置快照/版本与构建/平台与协议/
    IDs 与时间全量上卡；红强调由 ERROR_THEME 注入 --accent（非平台色）；
    bot_name/bot_avatar_url 走 _COMMON_FOOTER（与契约构造同值）。
    """
    html_text = bridge.render_error_card_html(
        {
            "card_title": "运行异常",
            "exc_type": "TimeoutError",
            "exc_message": "connect timeout after 6s",
            "human_text": "这条指令处理的时候出了岔子（TimeoutError），细节都在卡上了。",
            "trigger_echo": "天气 北京",
            "stack_lines": [
                "  weather.py:120 in fetch_city: requests.get(url)",
                "  pipeline.py:861 in handle: capability(prepared.message, ...)",
            ],
            "method_pairs": [
                {"label": "能力", "value": "bot.weather"},
                {"label": "函数", "value": "fetch_city"},
                {"label": "路由", "value": "RouteKind.WEATHER"},
            ],
            "config_pairs": [{"label": "bot_weather_api_key", "value": "***"}],
            "version_pairs": [
                {"label": "NoneBot", "value": "2.x.y"},
                {"label": "构建", "value": "abc1234 (2026-09-13)"},
            ],
            "env_pairs": [
                {"label": "平台", "value": "qq"},
                {"label": "协议", "value": "OneBot V11"},
                {"label": "通信", "value": "正向 WS"},
                {"label": "会话", "value": "群聊 123"},
            ],
            "id_pairs": [
                {"label": "触发时间", "value": "2026-09-14T12:00:00+08:00"},
                {"label": "message_id", "value": "m-9"},
            ],
            # 审查 Q-05：不点名创造者真名（澜汐/霞月），角色身份泛称即可——
            # 样张是人工验收素材，但文案口径与生产「不绑定真名」红线一致。
            "help_text": "把这张卡截图发给创造者即可，信息已齐备且脱敏。",
            **_COMMON_FOOTER,
        }
    )
    return {
        "html": html_text,
        # 视口同生产 render_error_card_png（error_report.py）。
        "viewport": {"width": 1160, "height": 1800},
        "device_scale_factor": 2,
        "wait_ms": 0,
    }


# ---------------------------------------------------------------------------
# 卡型登记表 / 渲染循环
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SampleCard:
    key: str
    label: str
    build: Callable[[], dict[str, Any]]


CARDS: tuple[SampleCard, ...] = (
    SampleCard("universal_bilibili_video", "universal · bilibili 视频", build_universal_bilibili_video),
    SampleCard("universal_bilibili_bgv", "universal · bilibili BGV(BGM)", build_universal_bilibili_bgv),
    SampleCard("universal_default_search", "universal · 未知默认 搜图", build_universal_default_search),
    SampleCard("universal_netease_music", "universal · netease 音乐", build_universal_netease_music),
    SampleCard("market_index", "market · 股指卡", build_market_index),
    SampleCard("market_commodities", "market · 大宗商品", build_market_commodities),
    SampleCard("market_bond", "market · 国债收益率", build_market_bond),
    SampleCard("market_northbound", "market · 北向资金", build_market_northbound),
    SampleCard("finance_stocks", "finance · 个股行情", build_finance_stocks),
    SampleCard("affinity_private", "affinity · 私聊正常", build_affinity_private),
    SampleCard("affinity_group", "affinity · 群聊正常", build_affinity_group),
    SampleCard("affinity_dirty", "affinity · 脏数据", build_affinity_dirty),
    SampleCard("song_candidates", "song_candidates · 点歌候选", build_song_candidates),
    SampleCard("mermaid_flow", "mermaid · 流程图", build_mermaid),
    SampleCard("help_index", "help · 帮助目录（两栏）", build_help_index),
    SampleCard("debug_llm_setup", "debug · LLM 接入检查", build_debug_llm_setup),
    SampleCard("usage_report", "usage · 模型账单(渠道子行)", build_usage_report),
    SampleCard("media_archive", "media_archive · 归档结果", build_media_archive),
    SampleCard("error_card", "error_card · 运行异常诊断", build_error_card),
)

_REGISTRY: dict[str, SampleCard] = {card.key: card for card in CARDS}


@dataclass
class SampleResult:
    key: str
    ok: bool
    path: Path | None = None
    size_bytes: int = 0
    dimensions: str = ""
    elapsed_ms: int = 0
    error: str = ""


def default_out_dir() -> Path:
    return Path(tempfile.gettempdir()) / "shorekeeper-samples" / "baseline-20260918"


def _json_default(obj: Any) -> dict[str, str]:
    """payload.json 兜底：运行时对象（debug 卡 config 面）以类型名占位。"""
    return {"__nonserializable__": type(obj).__name__}


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_baseline(
    out_dir: Path,
    *,
    keys: list[str] | None = None,
    backend: Any = None,
) -> tuple[list[SampleResult], dict[str, Any]]:
    """基线/对比取样：每面 payload.json + PNG + .sha256 旁车 + 双渲确定性自检。

    与 render_samples 的差异：同 payload 渲染两次比对字节，汇总写
    manifest.json（面→html/png sha256→毫秒→确定性）；PNG 字节不稳定如实
    记录不判失败——归因见 manifest["note"]（2026-09-19 ANIM 钉帧席起生产
    截图路径已 WAAPI 钉帧，双渲应全 STABLE，PNG 字节等值为验收判据）。
    注入后端归调用方管理，不代关。
    """
    owns_backend = backend is None
    if owns_backend:
        backend = build_render_backend("auto")
    if not getattr(backend, "available", False):
        raise RuntimeError(f"渲染后端不可用（name={getattr(backend, 'name', '?')}），无法出样张")
    selected = [card for card in CARDS if not keys or card.key in set(keys)]
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[SampleResult] = []
    entries: list[dict[str, Any]] = []
    try:
        for index, card in enumerate(selected, start=1):
            result = SampleResult(key=card.key, ok=False)
            entry: dict[str, Any] = {"index": index, "key": card.key, "label": card.label}
            started = time.monotonic()
            try:
                payload = card.build()
                html = str(payload.get("html", ""))
                entry["html_sha256"] = _sha256_hex(html.encode("utf-8"))
                entry["html_double_build_identical"] = card.build().get("html") == html
                (out_dir / f"{index:02d}_{card.key}.payload.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=1, default=_json_default),
                    encoding="utf-8",
                )
                png_first = backend.render_card(payload)
                entry["ms_first"] = int((time.monotonic() - started) * 1000)
                if not isinstance(png_first, bytes) or not png_first:
                    raise RuntimeError("后端返回空/None（首次渲染失败）")
                png_name = f"{index:02d}_{card.key}.png"
                target = out_dir / png_name
                target.write_bytes(png_first)
                (out_dir / f"{index:02d}_{card.key}.sha256").write_text(
                    f"{_sha256_hex(png_first)}  {png_name}\n", encoding="ascii"
                )
                result.path = target
                result.size_bytes = len(png_first)
                result.dimensions = _png_dimensions(png_first)
                entry["png_sha256"] = _sha256_hex(png_first)
                entry["png_bytes"] = len(png_first)
                entry["dimensions"] = result.dimensions
                result.ok = True
                # 双渲确定性：同 payload 第二次过生产后端，比对字节。
                second_started = time.monotonic()
                png_second = backend.render_card(payload)
                entry["ms_second"] = int((time.monotonic() - second_started) * 1000)
                if not isinstance(png_second, bytes) or not png_second:
                    entry["deterministic"] = False
                    entry["note"] = "第二次渲染返回空/None"
                else:
                    entry["png_sha256_second"] = _sha256_hex(png_second)
                    entry["deterministic"] = png_second == png_first
            except Exception as exc:  # noqa: BLE001 - 单面失败不中断其余面。
                result.error = f"{type(exc).__name__}: {exc}"
                entry["error"] = result.error
                entry["deterministic"] = False
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            results.append(result)
            entries.append(entry)
    finally:
        if owns_backend:
            close = getattr(backend, "close", None)
            if callable(close):
                close()
    manifest = {
        "mode": "samples",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "backend": str(getattr(backend, "name", "?")),
        "cards": entries,
        "note": (
            "2026-09-19 ANIM 钉帧席起：render_backends 截图前对 .card 子树动画 "
            "WAAPI 钉时（pause + currentTime=0，冻结在 --phase 负 delay 定义的"
            "相位位；与「加载即 animation-play-state:paused」参照帧逐字节一致，"
            "未用 animations=disabled——那会取消到基底位、丢钉帧姿态）。"
            "同 payload 双渲 PNG 逐字节确定，PNG 字节等值自本基线"
            "（baseline-20260919-paused）起为全部面的验收判据。"
            "旧基线 baseline-20260918 不稳根因：生产截图路径不冻结 CSS 循环动画，"
            "漂移色斑随墙钟采样（相位 digest 只钉动画初相不钉采样时刻），"
            "当时被迫以 html_sha256 为主判据——该降级口径自本基线起作废。"
        ),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return results, manifest


def print_determinism(manifest: dict[str, Any]) -> None:
    """打印双渲确定性自检表（STABLE/UNSTABLE + 归因尾注）。"""
    out = sys.stdout
    out.write("\n双渲确定性自检（同 payload 两次过生产后端比对字节）：\n")
    for entry in manifest["cards"]:
        if "error" in entry:
            out.write(f"  FAIL     {entry['key']:<34} 渲染失败未比对\n")
            continue
        mark = "STABLE  " if entry.get("deterministic") else "UNSTABLE"
        sha1 = str(entry.get("png_sha256", "-"))[:8]
        sha2 = str(entry.get("png_sha256_second", "-"))[:8]
        out.write(f"  {mark} {entry['key']:<34} png1={sha1} png2={sha2}\n")
    out.write(
        "  判据（2026-09-19 ANIM 钉帧席起）：render_backends 截图前 WAAPI 钉时\n"
        "  （pause+currentTime=0 冻结在 --phase 相位位），双渲 PNG 逐字节确定；\n"
        "  PNG 字节等值为全部面验收判据。出现 UNSTABLE 即逐面归因、不许假造稳定。\n"
    )


def render_samples(
    out_dir: Path,
    *,
    keys: list[str] | None = None,
    backend: Any = None,
) -> list[SampleResult]:
    """逐卡渲染落 PNG；单卡失败记录原因继续下一张。backend 可注入（测试）。

    内部创建的后端渲染完成后显式 ``close()``（finally 兜底）——playwright
    sync 后端不 close 会在调用线程残留 running-loop 状态（毒化同进程后续
    ``asyncio.run`` 用例，见 .superpowers/sdd/2026-09-13-six-domain-batch/
    xhs-leak-fix-report.md §一.1）；注入后端归调用方管理，不代关。
    """
    owns_backend = backend is None
    if owns_backend:
        backend = build_render_backend("auto")
    if not getattr(backend, "available", False):
        raise RuntimeError(f"渲染后端不可用（name={getattr(backend, 'name', '?')}），无法出样张")
    selected = [card for card in CARDS if not keys or card.key in set(keys)]
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[SampleResult] = []
    try:
        for index, card in enumerate(selected, start=1):
            result = SampleResult(key=card.key, ok=False)
            started = time.monotonic()
            try:
                payload = card.build()
                png = backend.render_card(payload)
                if not isinstance(png, bytes) or not png:
                    raise RuntimeError("后端返回空/None（渲染失败）")
                target = out_dir / f"{index:02d}_{card.key}.png"
                target.write_bytes(png)
                result.path = target
                result.size_bytes = len(png)
                result.dimensions = _png_dimensions(png)
                result.ok = True
            except Exception as exc:  # noqa: BLE001 - 单卡失败不中断其余卡。
                result.error = f"{type(exc).__name__}: {exc}"
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            results.append(result)
    finally:
        if owns_backend:
            close = getattr(backend, "close", None)
            if callable(close):
                close()
    return results


def _png_dimensions(png: bytes) -> str:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(png)) as image:
            return f"{image.width}x{image.height}"
    except Exception:  # noqa: BLE001 - 尺寸读取失败不影响出图。
        return "-"


def print_report(results: list[SampleResult], out_dir: Path) -> bool:
    """打印汇总表（卡型/文件/尺寸/大小/耗时）；返回是否全部成功。"""
    out = sys.stdout
    out.write(f"\n输出目录: {out_dir}\n")
    out.write(f"{'状态':<4} {'卡型':<34} {'文件':<36} {'尺寸':<14} {'大小':>9} {'耗时':>8}\n")
    all_ok = True
    for result in results:
        name = Path(result.path).name if result.path else "-"
        mark = "OK" if result.ok else "FAIL"
        out.write(
            f"{mark:<4} {result.key:<34} {name:<36} {result.dimensions:<14}"
            f" {result.size_bytes / 1024:>7.1f}KB {result.elapsed_ms:>6}ms\n"
        )
        if not result.ok:
            all_ok = False
    failures = [result for result in results if not result.ok]
    if failures:
        out.write("\n失败卡原因：\n")
        for result in failures:
            out.write(f"  - {result.key}: {result.error}\n")
    succeeded = len(results) - len(failures)
    out.write(f"\n合计 {succeeded}/{len(results)} 张成功。\n")
    return all_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线渲染全套卡面样张 PNG")
    parser.add_argument(
        "--out",
        default=str(default_out_dir()),
        help=f"输出目录（缺省 {default_out_dir()}）",
    )
    parser.add_argument(
        "--only",
        default="",
        help="只渲染指定卡型（逗号分隔 key；配合 --list 查看全部 key）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="只列出可渲染卡型清单，不渲染（离线快）",
    )
    args = parser.parse_args(argv)

    if args.list:
        print(f"可渲染卡型 {len(CARDS)} 个：")
        for card in CARDS:
            print(f"  {card.key:<34} {card.label}")
        return 0

    keys = [part.strip() for part in args.only.split(",") if part.strip()] or None
    unknown = [key for key in (keys or []) if key not in _REGISTRY]
    if unknown:
        print(f"未知卡型: {', '.join(unknown)}（用 --list 查看全部）", file=sys.stderr)
        return 2
    try:
        results, manifest = render_baseline(Path(args.out), keys=keys)
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    all_ok = print_report(results, Path(args.out))
    print_determinism(manifest)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
