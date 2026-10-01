"""运行异常诊断卡（error_card.html / render_error_card_html）契约回归。

与 tests/test_rendering_contract.py 互补：那里锁模板静态门（viewport/阴影/
gap/宽度等），这里锁渲染函数的运行时行为——脏 payload 不抛异常、分区按数据
显隐、脱敏文本直出、系统主题不入平台注册表。全离线字符串断言。
"""

from __future__ import annotations

import re
from typing import Any

from plugins.bot_unified_runtime.domains.render.card_render import bridge
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
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
        "self_review_pairs": [
            {"label": "推测原因", "value": "推测是对端回话太慢，不像是我算错了"},
            {"label": "建议", "value": "看看网关那几跳是不是都超时了"},
        ],
        "contact_pairs": [{"label": "管理员", "value": "QQ 10001"}],
        "help_text": "把这张卡截图发给创造者即可，信息已齐备且脱敏。",
        "bot_name": "守岸人",
        "bot_avatar_url": "",
    }


def _body_of(html: str) -> str:
    return html.split("<body>", 1)[-1]


# 分区标题的单一事实来源是 `_CARD_TEXT` 登记表（模板只引键名）。测试从登记表取值，
# 不再手抄中文串——历史上「触发方法」改名「定位与原因」就让手抄的期望值当场假红。
_SECTION_LOCATE = bridge._CARD_TEXT["static_err_22"]
_SECTION_SELF_REVIEW = bridge._CARD_TEXT["static_err_28"]
_SECTION_CONTACT = bridge._CARD_TEXT["static_err_29"]


def test_full_payload_renders_all_sections() -> None:
    html = bridge.render_error_card_html(_full_payload())
    for marker in (
        "运行异常",
        "运行诊断",  # goal-7 说人话波（2026-09-25）：旧英文机读标签 RUNTIME DIAGNOSTIC 中文化
        "触发回显",
        "栈摘录",
        _SECTION_LOCATE,
        _SECTION_SELF_REVIEW,
        _SECTION_CONTACT,
        "配置快照",
        "版本与构建",
        "平台与协议",
        "标识与时间",  # goal-7 说人话波：旧 'IDs 与时间' 机读节题中文化（纯文本兜底侧旧串在 error_report，已跟齐）
        "TimeoutError",
        "weather.py:120",
        "bot_weather_api_key",
        "RouteKind.WEATHER",
        "守岸人",
    ):
        assert marker in html, f"缺分区/内容: {marker}"
    # 红色强调色（ERROR_THEME accent）注入 --accent。
    assert f"--accent:{ERROR_ACCENT}" in html
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
    for section in ("触发回显", "栈摘录", _SECTION_LOCATE, "配置快照",
                    _SECTION_SELF_REVIEW, _SECTION_CONTACT):
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
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report as er
    from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
        cooldown_line,
    )

    assert len(er._COOLDOWN_LINES) >= 10
    assert len(set(er._COOLDOWN_LINES)) == len(er._COOLDOWN_LINES)
    text = cooldown_line("TimeoutError")
    assert text in {variant.format(exc="TimeoutError") for variant in er._COOLDOWN_LINES}
    assert "{" not in text and "}" not in text
    assert "卡" in text
    for variant in er._COOLDOWN_LINES:
        assert "卡" in variant  # 语义红线：每句都指回刚才那张诊断卡。


# ==================== W9 受众分级：渲染产物面（2026-10-01）====================
# 分级门落在**载荷唯一组装口**（`error_report.build_error_report`），本件保持纯渲染：
# 什么档位的数据进来就照画什么，不在渲染口养第二把尺（"卡裁了而文本兜底没裁"这类
# 双通路缺陷就是这么来的）。上面 `test_full_payload_renders_all_sections` 已经证明
# "喂全量载荷照样全画"，下面两把锁补上 audience 的两端：群态画不出内部结构、
# 管理员私聊态必须还画得出栈帧。
def _audience_payload(*, group: bool) -> dict[str, Any]:
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    def _msg() -> IncomingMessage:
        return IncomingMessage(
            platform="qq",
            adapter="onebot",
            bot_id="10000",
            session_id="group:g1" if group else "private:u1",
            session_type=SessionType.GROUP if group else SessionType.PRIVATE,
            group_id="g1" if group else "",
            sender_id="u1",
            plain_text="/bot 天气 北京",
            message_id="m-1",
            sender_roles=["user"] if group else ["admin"],
        )

    try:
        raise KeyError("bot_market_timeout_seconds 不在 C:/Users/LancyCelestia/Runtime/x")
    except KeyError as exc:
        caught = exc
    return error_report.build_error_report(
        _msg(),
        "bot.market",
        caught,
        config_getter=lambda name: {
            "bot_admin_user_ids": ["u1"],
            "bot_super_admin_user_ids": ["999"],
            "bot_admin_profiles": {"999": "澜汐"},
            "bot_market_timeout_seconds": 6.0,
        }.get(name),
    )


def test_group_audience_card_html_carries_no_internal_structure() -> None:
    html = bridge.render_error_card_html(_audience_payload(group=True))
    body = _body_of(html)
    for marker in (".py:", "def ", "BOT_", "bot_", "C:/", "C:\\", "/home/", "澜汐", "999"):
        assert marker not in body, f"群态卡面带出内部结构 {marker!r}"
    for section in ("栈摘录", "配置快照", "版本与构建", "平台与协议"):
        assert section not in body, f"该整节消失的还在：{section}"
    # 该留的两格仍在（否则这张卡就退化成一句"出错了"，用户无从向管理员转述）。
    assert "触发回显" in body and "/bot 天气 北京" in body
    assert "标识与时间" in body and "触发时刻" in body
    assert "不对外公开" in body, "联系方式格要诚实说明不给号"
    # 契约零破坏：模板根元素/透明度/宽度那套静态门由 test_rendering_contract 执法。
    assert 'class="shell card"' in html


def test_admin_audience_card_html_still_draws_the_stack() -> None:
    """反向锁（渲染产物面）：管理员私聊那张卡必须还画得出栈帧与配置键名。"""
    html = bridge.render_error_card_html(_audience_payload(group=False))
    body = _body_of(html)
    assert "栈摘录" in body, "把管理员档也裁了＝下次线上出问题查不了"
    assert ".py:" in body and "test_error_card_contract.py" in body
    assert "配置快照" in body and "bot_market_timeout_seconds" in body
    assert "版本与构建" in body and "平台与协议" in body
    assert "澜汐" in body and "999" in body, "管理员档联系方式本就该给"
