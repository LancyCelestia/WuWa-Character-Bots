"""E03 字体微雕第五要素：fmt_count 数字与单位间细空格（U+2009 THIN SPACE）。

锁定 universal_card.html ``fmt_count`` 宏的产出格式契约：
- 万/亿量级换算后，数字与单位之间插入窄空格 U+2009；
- 低于万位阈值整数与非数值字符串原样透传，不注入任何空格；
- ``.0`` 尾数收敛行为不变（5.0万 → 5\u2009万）。

设计口径：docs/design/visual-effects-catalog.md §2 E03「数字与单位间细空格」
未指定具体字符，本批取 U+2009（排版学标准窄空格；HTML 实体不用，保证
任何朴素文本提取路径不泄漏实体源码）。全离线 Jinja 渲染，无 playwright。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.domains.render.card_render import bridge

_THIN = "\u2009"

_VIDEO_BASE: dict[str, object] = {"page_type": "video", "name": "UP", "title": "标题"}


def _fmt(value: object) -> str:
    """渲染单瓦片 payload，抠出 fmt_count 产出字符串。"""
    html_text = bridge.render_universal_card_html(
        {
            **_VIDEO_BASE,
            "stats_bar_items": [
                {"key": "views", "label": "播放", "value": value, "icon_svg": "", "source": "none"},
            ],
        }
    )
    marker = '<span class="metric-value">'
    start = html_text.index(marker) + len(marker)
    end = html_text.index("</span>", start)
    return html_text[start:end]


# ==================== 窄空格注入 ====================
def test_wan_level_inserts_thin_space() -> None:
    assert _fmt(152000) == f"15.2{_THIN}万"


def test_yi_level_inserts_thin_space() -> None:
    assert _fmt(120000000) == f"1.2{_THIN}亿"


def test_trailing_zero_trim_keeps_thin_space() -> None:
    assert _fmt(50000) == f"5{_THIN}万"


def test_threshold_boundaries_get_thin_space() -> None:
    assert _fmt(10000) == f"1{_THIN}万"
    assert _fmt(100000000) == f"1{_THIN}亿"


# ==================== 透传不注入 ====================
def test_below_threshold_int_passthrough_no_space() -> None:
    assert _fmt(6555) == "6555"
    assert _fmt(9999) == "9999"
    assert _fmt(0) == "0"


def test_non_number_passthrough_untouched() -> None:
    # 已格式化字符串（解析器透传）不二次加工，也不补空格。
    assert _fmt("1.2万") == "1.2万"


# ==================== 卫生：无其他空白形态混入 ====================
def test_no_regular_space_or_nbsp_in_unit_output() -> None:
    out = _fmt(152000)
    assert out != "15.2万"  # 无空格旧格式必须绝迹
    assert "\u00a0" not in out  # 不用不换行空格
    assert " " not in out  # 不用半角空格
    assert out == "15.2\u2009万"  # 恰为 U+2009
