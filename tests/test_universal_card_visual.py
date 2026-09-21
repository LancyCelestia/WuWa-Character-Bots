"""universal_card.html 解析卡视觉对标升级（vis1 2026-09-12）结构断言。

锁定对标落地后的结构契约（全离线 Jinja 渲染，无 playwright）：
- 统计瓦片数字用平台 accent（--accent-dark），图标仍为 --accent；
- fmt_count 宏：整型数量级格式化（亿/万，.0 尾数收敛，数字与单位间 U+2009 窄空格），非整型原样透传；
- 摘要块「内容摘要」小标 + 左侧 --accent 竖条（::before）；
- 媒体时长角标左下置位；清晰度角标 .quality-pill 仅为 bridge 字段预留钩子
  （video_quality 未入 RenderPayload 前元素永不渲染）；
- 页脚左侧媒体 ID（bvid 优先，av_id 兜底）；
- 标题引言框不再重复渲染认证徽章（徽章只保留在作者行）。

上游契约（铁律/阴影 token/wash/viewport/字重）由 tests/test_rendering_contract.py
锁定，本文件不重复。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.render.card_render import bridge

_TEMPLATES_DIR = Path(bridge.__file__).resolve().parent / "templates"
_TEMPLATE_NAME = "universal_card.html"

_VIDEO_BASE: dict[str, object] = {"page_type": "video", "name": "UP", "title": "标题"}


def _template_text() -> str:
    return (_TEMPLATES_DIR / _TEMPLATE_NAME).read_text(encoding="utf-8")


def _css() -> str:
    match = re.search(
        r"<style>(.*?)</style>", _template_text(), re.DOTALL
    )
    assert match, "universal_card.html 缺少 <style> 块"
    return match.group(1)


def _css_rule(selector: str) -> str:
    pattern = re.escape(selector) + r"\s*\{([^}]*)\}"
    match = re.search(pattern, _css())
    assert match, f"universal_card.html 缺少 CSS 规则: {selector}"
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _render(payload: dict[str, object]) -> str:
    return bridge.render_universal_card_html(payload)


# ==================== 统计瓦片 ====================
def test_metric_value_uses_platform_accent() -> None:
    assert "color:var(--accent-dark)" in _css_rule(".metric-value")


def test_metric_icon_keeps_primary_accent() -> None:
    assert "color:var(--accent)" in _css_rule(".metric-icon")


def test_fmt_count_macro_scales_wan_yi_and_passes_through() -> None:
    html_text = _render(
        {
            **_VIDEO_BASE,
            "stats_bar_items": [
                {"key": "views", "label": "播放", "value": 152000, "icon_svg": "", "source": "none"},
                {"key": "likes", "label": "点赞", "value": 49000, "icon_svg": "", "source": "none"},
                {"key": "favorites", "label": "收藏", "value": 120000000, "icon_svg": "", "source": "none"},
                {"key": "comments", "label": "评论", "value": 333, "icon_svg": "", "source": "none"},
                {"key": "shares", "label": "转发", "value": "1.2万", "icon_svg": "", "source": "none"},
            ],
        }
    )
    # E03 第五要素：数字与单位之间窄空格 U+2009。
    assert ">15.2\u2009万</span>" in html_text
    assert ">4.9\u2009万</span>" in html_text
    assert ">1.2\u2009亿</span>" in html_text
    assert ">333</span>" in html_text
    # 非整型（已格式化字符串）原样透传，不二次加工。
    assert ">1.2万</span>" in html_text


def test_fmt_count_macro_trims_trailing_zero() -> None:
    html_text = _render(
        {
            **_VIDEO_BASE,
            "stats_bar_items": [
                {"key": "views", "label": "播放", "value": 50000, "icon_svg": "", "source": "none"},
            ],
        }
    )
    assert ">5\u2009万</span>" in html_text


def test_author_stat_items_use_fmt_count() -> None:
    html_text = _render(
        {
            **_VIDEO_BASE,
            "author_stat_items": [
                {"key": "followers", "label": "粉丝", "value": 1287401},
            ],
        }
    )
    assert "粉丝 128.7\u2009万" in html_text


# ==================== 摘要块 ====================
def test_summary_block_has_tag_and_accent_bar() -> None:
    html_text = _render({**_VIDEO_BASE, "summary": "守岸人测试简介"})
    assert '<span class="summary-tag">内容摘要</span>' in html_text
    before = _css_rule(".video-card-summary::before")
    assert "background:var(--accent)" in before
    assert "content:&quot;&quot;" not in before  # 伪元素 content 正常声明
    assert 'content:""' in before


# ==================== 媒体角标 ====================
def test_duration_pill_sits_bottom_right_in_video_inset() -> None:
    """vis2r 用户裁定（2026-09-13）：时长移封面右下角并加大字号；清晰度角标让位左下。"""
    rule = _css_rule(".video-cover-inset .duration-pill")
    assert "right:12px" in rule
    assert "left:auto" in rule
    assert "font-size:15px" in rule
    quality_rule = _css_rule(".video-cover-inset .quality-pill")
    assert "left:12px" in quality_rule
    assert "right:auto" in quality_rule


def test_quality_pill_is_template_hook_only() -> None:
    # 钩子与样式就位，但 bridge 未提供 video_quality 字段前元素永不渲染。
    assert "{% if video_quality %}" in _template_text()
    assert _css_rule(".quality-pill")
    html_text = _render({**_VIDEO_BASE, "banner": "https://example.invalid/cover.jpg"})
    assert 'class="quality-pill"' not in html_text


# ==================== 页脚媒体 ID ====================
def test_footer_media_id_prefers_av_then_bvid() -> None:
    """vis2r 用户裁定（2026-09-13）：页脚优先展示 AV 号（更大字号），无 AV 回落 BV。"""
    av_only = _render({**_VIDEO_BASE, "av_id": "112874701"})
    assert '<span class="footer-media-id">AV 112874701</span>' in av_only
    both = _render({**_VIDEO_BASE, "bvid": "BV1uvbL6iE8z", "av_id": "112874701"})
    assert '<span class="footer-media-id">AV 112874701</span>' in both
    assert "BV1uvbL6iE8z" not in both.split("footer-bot-pill")[0]
    bvid_only = _render({**_VIDEO_BASE, "bvid": "BV1uvbL6iE8z"})
    assert '<span class="footer-media-id">BV1uvbL6iE8z</span>' in bvid_only
    neither = _render(dict(_VIDEO_BASE))
    assert '<span class="footer-media-id">' not in neither


# ==================== 标题徽章去重 ====================
def test_title_quote_no_longer_duplicates_official_badge() -> None:
    html_text = _render(
        {**_VIDEO_BASE, "title": "测试标题", "official_badge": "哔哩哔哩原创博主"}
    )
    assert '<span class="video-badge">' not in html_text
    # 作者行徽章保留。
    assert "哔哩哔哩原创博主" in html_text


@pytest.mark.parametrize(
    "payload",
    [
        {"page_type": "video"},
        {"page_type": "video", "summary": "简介", "stats_bar_items": []},
    ],
    ids=["bare", "empty_metric_items"],
)
def test_new_blocks_stay_hidden_without_data(payload: dict[str, object]) -> None:
    html_text = _render(payload)
    assert "守岸人" in html_text
    assert '<span class="summary-tag">' not in html_text
    assert '<span class="footer-media-id">' not in html_text
