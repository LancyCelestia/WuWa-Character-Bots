"""运行异常诊断卡（error_card.html / render_error_card_html）契约回归。

与 tests/test_rendering_contract.py 互补：那里锁模板静态门（viewport/阴影/
gap/宽度等），这里锁渲染函数的运行时行为——脏 payload 不抛异常、分区按数据
显隐、脱敏文本直出、系统主题不入平台注册表。全离线字符串断言。
"""

from __future__ import annotations

import re
from typing import Any

from plugins.bot_unified_runtime.output.card_render import bridge
from plugins.bot_unified_runtime.output.card_render.theme_tokens import (
    CARD_SHELL_WIDTHS,
    ERROR_ACCENT,
    ERROR_THEME,
    PLATFORM_THEMES,
)


def _full_payload() -> dict[str, Any]:
    return {
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
        "help_text": "把这张卡截图发给创造者即可，信息已齐备且脱敏。",
        "bot_name": "守岸人",
        "bot_avatar_url": "",
    }


def _body_of(html: str) -> str:
    return html.split("<body>", 1)[-1]


def test_full_payload_renders_all_sections() -> None:
    html = bridge.render_error_card_html(_full_payload())
    for marker in (
        "运行异常",
        "RUNTIME DIAGNOSTIC",
        "触发回显",
        "栈摘录",
        "触发方法",
        "配置快照",
        "版本与构建",
        "平台与协议",
        "IDs 与时间",
        "TimeoutError",
        "weather.py:120",
        "bot_weather_api_key",
        "RouteKind.WEATHER",
        "守岸人",
    ):
        assert marker in html, f"缺分区/内容: {marker}"
    # 红色强调色（ERROR_THEME accent）注入 --pc。
    assert f"--pc: {ERROR_ACCENT}" in html
    # A69-C1：创造者真名不得入卡（群广播隐私级）。
    assert "澜汐" not in html and "霞月" not in html


def test_empty_and_dirty_payload_never_raises() -> None:
    for payload in (
        None,
        {},
        {
            "stack_lines": [None, 3, {"x": 1}, "  a.py:1 in f: ok"],
            "method_pairs": ["bad", {"label": "能力"}, {"value": "orphan"}, None],
            "config_pairs": [{"label": "k", "value": None}],
            "exc_message": None,
            "human_text": None,
            "bot_avatar_url": None,
        },
    ):
        html = bridge.render_error_card_html(payload)
        assert isinstance(html, str) and html.strip()
        assert "守岸人" in html
        # 缺省值归一：不出现 Python None 字样（占位文本除外）。
        body = _body_of(html)
        assert "None" not in body
        # 根元素带 .card（元素截图契约）。
        assert re.search(r'class="shell card"', html)


def test_sections_hidden_when_data_missing() -> None:
    html = bridge.render_error_card_html({})
    for section in ("触发回显", "栈摘录", "触发方法", "配置快照"):
        assert section not in _body_of(html)
    # 页脚求助缺省文案仍在。
    assert "把这张卡截图发给创造者" in html


def test_payload_escaping_is_auto() -> None:
    html = bridge.render_error_card_html(
        {"trigger_echo": "<script>alert(1)</script>", "exc_message": "<b>x</b>"}
    )
    assert "<script>" not in _body_of(html)
    assert "&lt;script&gt;" in html


def test_error_theme_is_system_theme_not_platform() -> None:
    # 独立系统主题：不进平台注册表（不污染平台命名空间）。
    assert ERROR_THEME.key not in PLATFORM_THEMES
    assert all(theme is not ERROR_THEME for theme in PLATFORM_THEMES.values())
    assert ERROR_THEME.accent == ERROR_ACCENT == "#d54941"
    # 云母洗仍由红 accent 派生，mist 保持守岸人本命打底。
    assert ERROR_THEME.wash_mist == PLATFORM_THEMES["bilibili"].wash_mist


def test_error_card_shell_width_registered() -> None:
    assert CARD_SHELL_WIDTHS["error"] == 1080
    from pathlib import Path

    template_path = (
        Path(bridge.__file__).parent / "templates" / "error_card.html"
    )
    text = template_path.read_text(encoding="utf-8")
    assert "width: 1080px" in text


def test_cooldown_line_tone_and_content() -> None:
    """P2-4 同规则：冷却句池化（≥10），每句带 exc、指回卡、无未填槽。"""
    from plugins.bot_unified_runtime.runtime import error_report as er
    from plugins.bot_unified_runtime.runtime.error_report import cooldown_line

    assert len(er._COOLDOWN_LINES) >= 10
    assert len(set(er._COOLDOWN_LINES)) == len(er._COOLDOWN_LINES)
    text = cooldown_line("TimeoutError")
    assert text in {variant.format(exc="TimeoutError") for variant in er._COOLDOWN_LINES}
    assert "{" not in text and "}" not in text
    assert "卡" in text
    for variant in er._COOLDOWN_LINES:
        assert "卡" in variant  # 语义红线：每句都指回刚才那张诊断卡。
