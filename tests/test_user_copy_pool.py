"""U12 公共话术常量池（capabilities/user_copy.py）快照回归。

话术真相源：`.superpowers/sdd/2026-09-12-shorekeeper-global-audit/fix-uxc-report.md`
（U6/U9/U11/U12 落地文案）。快照策略——纯重构零行为变化的逐字节锁定：
- 池常量按各引用点实参渲染的结果必须等于迁移前的完整文案；
- 每个迁移点在源文件中必须引用池常量的既定表达式（防引用参数被误改）。
"""

from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.capabilities import user_copy

_CAP_DIR = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "capabilities"
)


def _assert_site(filename: str, expression: str) -> None:
    source = (_CAP_DIR / filename).read_text(encoding="utf-8")
    assert expression in source, f"{filename} 缺少预期引用点表达式：{expression}"


def test_u12_datasource_temp_failure_snapshot() -> None:
    """U12 数据源临时失败：原因短语 +「稍后再试。」（fx / moegirl 两处）。"""
    assert (
        user_copy.DATASOURCE_TEMP_FAILURE.format(reason="汇率数据暂时拉不到")
        == "汇率数据暂时拉不到，稍后再试。"
    )
    assert (
        user_copy.DATASOURCE_TEMP_FAILURE.format(reason="萌娘百科暂时连不上")
        == "萌娘百科暂时连不上，稍后再试。"
    )
    _assert_site(
        "fx.py",
        'body=user_copy.DATASOURCE_TEMP_FAILURE.format(reason="汇率数据暂时拉不到")',
    )
    _assert_site(
        "moegirl.py",
        'body=user_copy.DATASOURCE_TEMP_FAILURE.format(reason="萌娘百科暂时连不上")',
    )


def test_u11_admin_gate_snapshot() -> None:
    """U11 管理员门禁统一模板：「要<动作>，找管理员来操作。」（9 处/7 文件）。"""
    expected = {
        "看运行时排障记录": "要看运行时排障记录，找管理员来操作。",  # debug.py
        "看运行时状态": "要看运行时状态，找管理员来操作。",  # echo.py
        "改点歌输出模式": "要改点歌输出模式，找管理员来操作。",  # music.py
        "查运行时日志": "要查运行时日志，找管理员来操作。",  # runtime_logs.py
        "把订阅推送到本群": "要把订阅推送到本群，找管理员来操作。",  # subscribe.py
        "看本群订阅": "要看本群订阅，找管理员来操作。",  # subscribe.py / subscribe_v2.py
        "取消群推送时间": "要取消群推送时间，找管理员来操作。",  # today_history.py
        "设置群推送时间": "要设置群推送时间，找管理员来操作。",  # today_history.py
    }
    for action, full in expected.items():
        assert user_copy.ADMIN_GATE_REQUIRED.format(action=action) == full

    sites = [
        ("debug.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="看运行时排障记录")'),
        ("echo.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="看运行时状态")'),
        ("music.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="改点歌输出模式")'),
        ("runtime_logs.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="查运行时日志")'),
        ("subscribe.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="把订阅推送到本群")'),
        ("subscribe.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="看本群订阅")'),
        ("subscribe_v2.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="看本群订阅")'),
        ("today_history.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="取消群推送时间")'),
        ("today_history.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="设置群推送时间")'),
    ]
    for filename, expression in sites:
        _assert_site(filename, expression)


def test_u9_push_save_failed_snapshot() -> None:
    """U9 推送表写盘失败：today_history 设置/取消两处同文案。"""
    assert user_copy.PUSH_SAVE_FAILED == (
        "推送时间的改动没保存成功（写盘出错，我已记下原因）。"
        "稍后再发一次；还不行就找管理员看运行日志。"
    )
    source = (_CAP_DIR / "today_history.py").read_text(encoding="utf-8")
    assert source.count("body=user_copy.PUSH_SAVE_FAILED") == 2


def test_u6_run_env_failure_advice_snapshot() -> None:
    """U6 运行环境异常共享尾段（file_exchange 两处）。"""
    assert user_copy.RUN_ENV_FAILURE_ADVICE == "稍后再试；还不行就找管理员看运行日志。"
    source = (_CAP_DIR / "file_exchange.py").read_text(encoding="utf-8")
    assert (
        'f"语法检查通过 ✓；本机没能启动 Python 跑这段代码，'
        '这次运行不了。{user_copy.RUN_ENV_FAILURE_ADVICE}"'
    ) in source
    assert (
        'f"本机没法准备运行用的临时目录，这次跑不了。'
        '{user_copy.RUN_ENV_FAILURE_ADVICE}"'
    ) in source


def test_debug_denied_body_renders_expected_copy() -> None:
    """行为级抽查：debug 模块常量渲染结果与迁移前逐字节一致。"""
    from plugins.bot_unified_runtime.capabilities import debug as debug_cap

    assert debug_cap._DENIED_BODY == "要看运行时排障记录，找管理员来操作。"
