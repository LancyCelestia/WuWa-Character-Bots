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
    python scripts/render_card_samples.py --serve         # 只读预览已渲好的样张（不重渲、不写盘）
    python scripts/render_card_samples.py --serve --out <dir> --serve-port 8751

--serve 的用途边界（工单 W-5，D-2/Q-2 裁定：**只做只读预览，不做可视化编辑器**）：
- 只列**已经渲好**的产物：不 mkdir、不调渲染、不写任何字节、不建目录；目录里没有
  样张就明说「还没有产物」并给出该跑的命令，**绝不顺手替使用者渲一份**（那会把出图
  副作用与内存开销塞进一个预览入口）。
- 只绑 127.0.0.1（无 --host 开关，0.0.0.0 在代码里根本没有通路），缺省端口 8750——
  避开 5174（webui dev）/8080（bot webhook）/8090（网关）/8742（控制面）/8743（mock）。
- 零第三方依赖（stdlib http.server，形状照 scripts/webui_mock_server.py）。
- 泄露面：产物目录可能落在运行数据根下，**绝对路径本身就是泄露面**，而
  domains/render/plain_text.py 的 redact_local_secrets 只守 bot 文本出口、管不到
  HTTP 响应体——所以预览面**从源头上就不产出绝对路径**：列表只给相对文件名，目录根
  只给脱敏标记（RUNTIME_ROOT / TMP_ROOT / SAMPLES_ROOT），对外文本再过一次
  redact_local_secrets 兜底。
- 🔴 预览看过 ≠ 渲染契约通过：判据是三把视觉锁
  tests/test_rendering_contract.py、tests/test_mica_builders_contract.py、
  tests/test_template_visual_audit.py 与 python tests/verify_hashes.py --check，
  --serve 一律不判它们，也不把任何卡标成「改好了」。

退出码：0 = 全部成功；1 = 有卡失败（其余照常出图）；2 = 渲染后端不可用／未知卡型／
        --serve 无产物可预览或端口不可用。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from html import escape as _html_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

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
from plugins.bot_unified_runtime.domains.render.plain_text import (
    redact_local_secrets,
)
from plugins.bot_unified_runtime.domains.render.render_backends import (
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
    from plugins.bot_unified_runtime.domains.finance.data.finance_chart import (
        line_chart_svg,
    )

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
            "subtitle": "与 漂泊者 的相处记录",
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
                {"sender_id": "u_a", "display_name": "群友·阿波", "score": 78.6, "tier": "亲近"},
                {"sender_id": "u_b", "display_name": "群友·小柚", "score": 71.2, "tier": "亲近"},
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
    from plugins.bot_unified_runtime.domains.render.templates import (
        render_media_card_html,
    )

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
            "self_review_pairs": [
                {"label": "我的推测", "value": "像是上游没在预算内回话（推测，不作为结论）。"},
                {"label": "依据", "value": "四跳全部同一异常，且失败集中在读超时一侧。"},
            ],
            "contact_pairs": [{"label": "超管 1 位", "value": "私聊任一管理员并把本卡发过去"}],
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


#: 告警样张专用头像：46×46 纯色 PNG 内联成 data URI（字节固定，样张可复现；
#: 生产走 `_card_avatar_uri` 读 `avatar/bot_<qq>.png`，随机器状态变，不进样张）。
_SAMPLE_AVATAR_URI = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAC4AAAAuCAIAAADY27xg"
    "AAAAOElEQVR42u3OMQ0AAAgDsAlDHRJRhAgejiYV0FTPE1FRUVFRUVFRUVFRUVFR"
    "UVFRUVFRUVFRUblZFfTq9XNgjJcAAAAASUVORK5CYII="
)


def build_alert_card() -> dict[str, Any]:
    """运维告警卡（``card_variant=alert`` → 蓝→红洗色）。

    与诊断卡同模板、不同洗色与标题：2026-09-25 澜汐点名「背景釉瑚渐变现在是
    灰色的，告警要用蓝色到红色的渐变」，本样张就是那一档的验收素材；头像走
    ``<img>`` 分支（不是「守」字圆点），核的是"平台头像真的能显示出来"。
    """
    html_text = bridge.render_error_card_html(
        {
            "card_variant": "alert",
            "card_title": "运行时告警",
            "exc_type": "llm/timeout",
            "exc_message": "chain=4跳全败 last=axon-grok-46:timeout",
            "human_text": "[守岸人告警] 我在想怎么回你这句话（模型那一跳）：等回话等超时了。",
            "trigger_echo": "",
            "stack_lines": [],
            "method_pairs": [
                {"label": "能力", "value": "bot.chat"},
                {"label": "归类", "value": "上游超时"},
                {"label": "归属", "value": "聊天回复域（chat_reply）"},
            ],
            "self_review_pairs": [
                {"label": "我的推测", "value": "像是网关侧四跳全挂在上游（推测，不作为结论）。"},
            ],
            "contact_pairs": [{"label": "超管 1 位", "value": "私聊任一管理员并把本卡发过去"}],
            "config_pairs": [{"label": "bot_chat_failover_max_seconds", "value": "300"}],
            "version_pairs": [
                {"label": "NoneBot", "value": "2.x.y"},
                {"label": "协议端", "value": "SnowLuma 1.14.19"},
            ],
            "env_pairs": [
                {"label": "平台", "value": "qq"},
                {"label": "会话", "value": "私聊"},
            ],
            "id_pairs": [
                {"label": "何时", "value": "2026-09-25 13:47:02 UTC+08:00"},
                {"label": "排查编号", "value": "dbg_7c115984050c"},
            ],
            "help_text": "把这张卡发给创造者即可，信息已齐备且脱敏。",
            "bot_name": "守岸人",
            "bot_avatar_url": _SAMPLE_AVATAR_URI,
        }
    )
    return {
        "html": html_text,
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
    SampleCard("alert_card", "alert_card · 运行时告警（蓝→红）", build_alert_card),
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


# ---------------------------------------------------------------------------
# --serve：只读预览（列已渲好的产物；不重渲、不写盘、不建目录、只绑回环）
# ---------------------------------------------------------------------------

#: 铁律：--serve 只准绑回环。CLI 里没有 --host 开关，0.0.0.0 在代码中不存在通路。
_SERVE_HOST = "127.0.0.1"
#: 缺省端口：避开 5174（webui dev）/ 8080（bot webhook）/ 8090（网关）/
#: 8742（控制面）/ 8743（webui_mock_server，其文档另举 8744）。
_SERVE_DEFAULT_PORT = 8750

_ROOT_MARK_RUNTIME = "RUNTIME_ROOT"
_ROOT_MARK_TMP = "TMP_ROOT"
_ROOT_MARK_PLAIN = "SAMPLES_ROOT"

#: 产物文件名的唯一合法形态（render_baseline 的落盘命名 NN_<key>.png）。
#: 目录穿越、绝对路径、盘符、单层以上的一切形态在这里先被拒。
_PNG_NAME_RE = re.compile(r"\A[0-9]{2}_[a-z0-9_]+\.png\Z")
_LEAF_NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

#: 契约提醒（同一份文案同时进启动行、stdout 报告与预览页，见工单 W-5 第 5 条）。
_CONTRACT_NOTE = (
    "预览看过 ≠ 渲染契约通过：判据是三把视觉锁 tests/test_rendering_contract.py、"
    "tests/test_mica_builders_contract.py、tests/test_template_visual_audit.py，"
    "外加 python tests/verify_hashes.py --check。本预览入口不判它们，"
    "也不把任何一张卡说成「改好了」。"
)


@dataclass(frozen=True)
class SampleArtifact:
    """一张已渲好的样张。**只带相对文件名**，绝对路径不进这个结构。"""

    rel_name: str
    card_key: str
    size_bytes: int


@dataclass(frozen=True)
class SampleListing:
    root_mark: str
    dir_exists: bool
    artifacts: tuple[SampleArtifact, ...]
    present_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]
    expected_keys: tuple[str, ...]
    illegal_count: int

    @property
    def complete(self) -> bool:
        """假绿判据（四条同时成立，缺一律按「预览不成立」报）：
        ① 列表非空；② 列出的卡型张数 == --list 现算值（expected_keys 同源 CARDS）；
        ③ 逐图都报得出所属卡型（文件名对不上在册卡型＝归属缺失）；
        ④ 逐图文件名形态本身在册（有人往列表里塞目录外路径时，这条把它拦在判据外）。
        """
        return (
            bool(self.artifacts)
            and not self.missing_keys
            and not self.illegal_count
            and all(
                item.card_key and _PNG_NAME_RE.fullmatch(item.rel_name) for item in self.artifacts
            )
        )


def _redact_text(text: str) -> str:
    """出口兜底：复用既有脱敏真身（按符号名引用，不抄它的实现造第二套）。

    注意它只守 bot 文本出口、管不到 HTTP 响应体，所以预览面的主防线是
    「根本不产出绝对路径」（root_mark_for / collect_samples），这里只是第二层。
    """
    return redact_local_secrets(text)


def root_mark_for(out_dir: Path) -> str:
    """产物根的**脱敏标记**：``RUNTIME_ROOT/<末段>`` / ``TMP_ROOT/<末段>`` / ``SAMPLES_ROOT``。

    绝对路径本身是泄露面（运行数据根带着盘符与用户名），预览面一律不输出，
    只输出这枚相对标记；判定失败时退回中性标记，绝不因此改吐绝对路径。
    """
    prefix = _ROOT_MARK_PLAIN
    try:
        from scripts import runtime_paths

        resolved = out_dir.resolve()
        if any(resolved == root or root in resolved.parents for root in runtime_paths.production_runtime_data_dirs()):
            prefix = _ROOT_MARK_RUNTIME
        else:
            tmp_root = Path(tempfile.gettempdir()).resolve()
            if tmp_root == resolved or tmp_root in resolved.parents:
                prefix = _ROOT_MARK_TMP
    except Exception:  # noqa: BLE001 - 标记判不出来就退回中性名，不升级为路径外泄
        prefix = _ROOT_MARK_PLAIN
    leaf = out_dir.name
    if leaf and _LEAF_NAME_RE.fullmatch(leaf):
        return _redact_text(f"{prefix}/{leaf}")
    return prefix


def collect_samples(out_dir: Path) -> SampleListing:
    """列举已渲好的样张 PNG。**纯只读**：不 mkdir、不渲染、不写任何字节。

    返回体里没有任何绝对路径（只有 ``path.name`` 这一层相对名），分母 ``expected_keys``
    与 ``--list`` 同源于 ``CARDS`` 现算，不写死枚数。
    """
    dir_exists = out_dir.is_dir()
    try:
        files = sorted(out_dir.iterdir()) if dir_exists else []
    except OSError:  # 权限/竞态：如实当空目录处理，不猜、不建、不修
        files, dir_exists = [], False
    artifacts: list[SampleArtifact] = []
    illegal = 0
    for path in files:
        if not path.is_file() or not path.name.lower().endswith(".png"):
            continue
        if not _PNG_NAME_RE.fullmatch(path.name):
            illegal += 1
            continue
        key = path.name[3:-4]
        artifacts.append(
            SampleArtifact(
                rel_name=path.name,
                card_key=key if key in _REGISTRY else "",
                size_bytes=path.stat().st_size,
            )
        )
    expected = tuple(card.key for card in CARDS)
    present = sorted({item.card_key for item in artifacts if item.card_key})
    missing = tuple(key for key in expected if key not in set(present))
    return SampleListing(
        root_mark=root_mark_for(out_dir),
        dir_exists=dir_exists,
        artifacts=tuple(artifacts),
        present_keys=tuple(present),
        missing_keys=missing,
        expected_keys=expected,
        illegal_count=illegal,
    )


def resolve_sample_file(root: Path, rel_name: str) -> Path | None:
    """把请求里的相对名换成盘上真身；任何越界形态一律 ``None``（拒收，不解释）。

    锁的是 ``http.server`` 的既有目录穿越风险：只认产物根下的单层 ``NN_<key>.png``，
    ``..``／绝对路径／盘符／反斜杠／子目录／NUL 全拒；符号链接跑出根也拒。
    """
    if not isinstance(rel_name, str) or not rel_name or "\x00" in rel_name:
        return None
    if ":" in rel_name or "\\" in rel_name:  # 盘符、UNC、Windows 绝对形态
        return None
    if rel_name.startswith("/"):  # 绝对 POSIX 与 //协议相对 一并拒
        return None
    parts = [part for part in rel_name.split("/") if part]
    if len(parts) != 1 or any(part in (".", "..") for part in parts):
        return None
    if not _PNG_NAME_RE.fullmatch(parts[0]):
        return None
    candidate = root / parts[0]
    try:
        real, real_root = candidate.resolve(), root.resolve()
    except OSError:
        return None
    if real.parent != real_root or not real.is_file():
        return None
    return real


def listing_summary(listing: SampleListing) -> str:
    """判据读数（含空目录的诚实说法，绝不产出「可用」这类词）。"""
    total = len(listing.expected_keys)  # 尺＝--list 现算值（同源 CARDS）
    if not listing.artifacts:
        return (
            f"还没有产物：{listing.root_mark} 下零张样张"
            f"{'（目录不存在）' if not listing.dir_exists else ''}。\n"
            "先跑 --only <卡型> --out <目录> 渲一份，再回来看图"
            "（本预览入口绝不代渲）。"
        )
    lines = [
        (
            f"已列 {len(listing.artifacts)} 张 PNG，卡型归属 {len(listing.present_keys)}/{total}"
            "（分母＝--list 现算值，非写死）。"
        )
    ]
    if listing.complete:
        lines.append(
            "判据四条齐：列表非空 ∧ 卡型张数==现算值 ∧ 逐图有文件名与所属卡型 ∧ 逐图形态在册。"
            "这只说明图齐、能看，不说明任何一张改好了。"
        )
        return "\n".join(lines)
    problems = []
    if listing.missing_keys:
        problems.append("缺卡型 " + "、".join(listing.missing_keys))
    unattributed = sum(1 for item in listing.artifacts if not item.card_key)
    if unattributed:
        problems.append(f"{unattributed} 张文件名对不上在册卡型（所属卡型报不出）")
    rejected = listing.illegal_count + sum(
        1 for item in listing.artifacts if not _PNG_NAME_RE.fullmatch(item.rel_name)
    )
    if rejected:
        problems.append(f"{rejected} 条条目形态不在产物命名册内（预览面拒收，不给换成图）")
    lines.append("判据未过 → 预览不成立：" + "；".join(problems))
    return "\n".join(lines)


def format_listing(listing: SampleListing) -> str:
    """stdout 报告：根标记 + 逐图（相对名 · 卡型 · 大小）+ 判据 + 契约提醒。"""
    lines = [f"样张根（脱敏标记，非路径）：{listing.root_mark}", listing_summary(listing)]
    for item in listing.artifacts:
        lines.append(f"  {item.rel_name:<36} {item.card_key or '<未归属>':<24} {item.size_bytes / 1024:>7.1f}KB")
    lines.append(_CONTRACT_NOTE)
    return _redact_text("\n".join(lines))


def preview_page_html(listing: SampleListing) -> str:
    """预览页（纯函数，只吃 listing）：每张图**必须**同屏带文件名与所属卡型。

    页内只出现相对名与脱敏标记；形态不合法的条目二次拒收（双保险），
    即便有人往 listing 里塞了目录外路径，也换不成 ``<img src>``。
    """
    figures: list[str] = []
    for item in listing.artifacts:
        if not _PNG_NAME_RE.fullmatch(item.rel_name):
            continue
        name = _html_escape(item.rel_name)
        key = _html_escape(item.card_key or "未归属")
        figures.append(
            '<figure class="shot">'
            f'<img src="/img/{quote(item.rel_name, safe="")}" alt="{name}">'
            f"<figcaption><b>{name}</b><span>卡型 {key}</span>"
            f"<span>{item.size_bytes / 1024:.1f}KB</span></figcaption>"
            "</figure>"
        )
    summary = _html_escape(listing_summary(listing)).replace("\n", "<br>")
    note = _html_escape(_CONTRACT_NOTE)
    body = "\n".join(figures) or '<p class="empty">没有可显示的样张（本页面不代渲）。</p>'
    return _redact_text(
        "<!DOCTYPE html>\n<html lang=\"zh-CN\"><head><meta charset=\"UTF-8\">"
        "<title>卡面样张预览（只读）</title><style>"
        "body{margin:0;padding:24px;background:#101826;color:#e9eef5;"
        "font-family:system-ui,'Microsoft YaHei',sans-serif}"
        "h1{font-size:18px;font-weight:600;margin:0 0 8px}"
        ".meta{font-size:13px;line-height:1.7;margin-bottom:16px;max-width:900px}"
        ".note{border-left:3px solid #fb7299;padding:8px 12px;background:#182238;"
        "font-size:13px;line-height:1.7;margin-bottom:20px;max-width:900px}"
        ".grid{display:flex;flex-wrap:wrap;gap:20px;align-items:flex-start}"
        ".shot{margin:0;background:#182238;padding:10px;border-radius:10px}"
        ".shot img{display:block;max-width:520px;height:auto;border-radius:6px}"
        "figcaption{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;margin-top:6px}"
        "figcaption b{font-weight:600}figcaption span{opacity:.75}"
        ".empty{color:#f7b6c2}"
        f"</style></head><body><h1>卡面样张预览 · 只读（不重渲、不写盘）</h1>"
        f"<div class=\"meta\">{summary}</div><div class=\"note\">{note}</div>"
        f"<div class=\"grid\">{body}</div></body></html>"
    )


class _SamplePreviewServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], *, root: Path) -> None:
        super().__init__(address, handler)
        self.root = root


class _SamplePreviewHandler(BaseHTTPRequestHandler):
    server_version = "ShorekeeperSamplePreview/1.0"
    sys_version = ""

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        root = getattr(self.server, "root", Path())
        if path in ("/", "/index.html"):
            # 每次现算：她重渲完刷新即见，本服务自己不碰渲染与写盘。
            page = preview_page_html(collect_samples(root)).encode("utf-8")
            self._send_bytes(200, page, "text/html; charset=utf-8")
            return
        if path == "/listing.json":
            listing = collect_samples(root)
            payload = {
                "root_mark": listing.root_mark,  # 脱敏标记，非路径
                "complete": listing.complete,
                "expected_total": len(listing.expected_keys),
                "present_keys": list(listing.present_keys),
                "missing_keys": list(listing.missing_keys),
                "illegal_count": listing.illegal_count,
                "items": [
                    {"rel_name": item.rel_name, "card_key": item.card_key, "size_bytes": item.size_bytes}
                    for item in listing.artifacts
                ],
                "contract": _CONTRACT_NOTE,
            }
            body = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
            self._send_bytes(200, body, "application/json; charset=utf-8")
            return
        if path.startswith("/img/"):
            target = resolve_sample_file(root, path[len("/img/"):])
            if target is None:
                self._send_bytes(404, b"rejected\n", "text/plain; charset=utf-8")
                return
            try:
                data = target.read_bytes()
            except OSError:
                self._send_bytes(404, b"unreadable\n", "text/plain; charset=utf-8")
                return
            self._send_bytes(200, data, "image/png")
            return
        self._send_bytes(404, b"not found\n", "text/plain; charset=utf-8")

    def do_HEAD(self) -> None:
        self.do_GET()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(_redact_text(fmt % args) + "\n")


def serve_samples(out_dir: Path, port: int = _SERVE_DEFAULT_PORT) -> int:
    """起只读预览服务。无产物 ⇒ 明说并退出码 2，**绝不代渲**；端口只绑 127.0.0.1。"""
    listing = collect_samples(out_dir)
    print(format_listing(listing), flush=True)
    if not listing.artifacts:
        print("未起服务：产物目录里没有样张，本入口不代渲（上面已给出该跑的命令）。", file=sys.stderr)
        return 2
    if not 1 <= port <= 65535:
        print("端口不在 1-65535，未起服务。", file=sys.stderr)
        return 2
    try:
        server = _SamplePreviewServer((_SERVE_HOST, port), _SamplePreviewHandler, root=out_dir)
    except OSError:
        print(f"端口 {port} 起不来（多半被占用），换 --serve-port；未起服务，也没渲任何东西。", file=sys.stderr)
        return 2
    if server.server_address[0] != _SERVE_HOST:  # 绑定后复核：绝不接受回环以外的落点
        server.server_close()
        print("绑定地址非 127.0.0.1，已拒绝启动。", file=sys.stderr)
        return 2
    print(
        _redact_text(
            f"预览已就绪：http://{_SERVE_HOST}:{port}/  （图片在 /img/<相对名>，清单在 /listing.json）\n"
            f"只监听本机 {_SERVE_HOST}，Ctrl-C 退出；本服务不重渲、不写盘、不建目录。\n"
            + _CONTRACT_NOTE
        ),
        flush=True,  # 重定向到文件时也让她第一时间看到启动行（缓冲会把它吃到退出才吐）
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


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
    parser.add_argument(
        "--serve",
        action="store_true",
        help="只读预览 --out 目录里已渲好的样张（只绑 127.0.0.1；不重渲、不写盘、不建目录，"
        "预览看过 ≠ 渲染契约通过）",
    )
    parser.add_argument(
        "--serve-port",
        type=int,
        default=_SERVE_DEFAULT_PORT,
        help=f"--serve 的监听端口（缺省 {_SERVE_DEFAULT_PORT}，只准绑 127.0.0.1，无 --host 开关）",
    )
    args = parser.parse_args(argv)

    if args.list:
        print(f"可渲染卡型 {len(CARDS)} 个：")
        for card in CARDS:
            print(f"  {card.key:<34} {card.label}")
        return 0

    if args.serve:
        return serve_samples(Path(args.out), args.serve_port)

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
