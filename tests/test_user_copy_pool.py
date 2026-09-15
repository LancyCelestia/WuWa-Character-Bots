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
    """U12+Q-01 数据源临时失败：原模板快照 + fx/moegirl 引用点已升级为变体池轮换。"""
    assert (
        user_copy.DATASOURCE_TEMP_FAILURE.format(reason="汇率数据暂时拉不到")
        == "汇率数据暂时拉不到，稍后再试。"
    )
    assert (
        user_copy.DATASOURCE_TEMP_FAILURE.format(reason="萌娘百科暂时连不上")
        == "萌娘百科暂时连不上，稍后再试。"
    )
    # Q-01（2026-09-15）：两处引用点从固定单句升级为 DATASOURCE_FAILURE_TEMPLATES
    # 轮换取句（池首条即原模板，语气零漂移）；锁定「池引用 + reason 实参」表达式。
    _assert_site("fx.py", "user_copy.DATASOURCE_FAILURE_TEMPLATES")
    _assert_site("fx.py", 'reason="汇率数据暂时拉不到"')
    _assert_site("moegirl.py", "user_copy.DATASOURCE_FAILURE_TEMPLATES")
    _assert_site("moegirl.py", 'reason="萌娘百科暂时连不上"')


def test_q01_datasource_pool_shape() -> None:
    """Q-01 池形态：3-5 条、首条=U12 原模板、{reason} 槽位齐全、无重复、可渲染。"""
    pool = user_copy.DATASOURCE_FAILURE_TEMPLATES
    assert 3 <= len(pool) <= 5
    assert pool[0] == user_copy.DATASOURCE_TEMP_FAILURE
    assert len(set(pool)) == len(pool)
    assert all("{reason}" in variant for variant in pool)
    for variant in pool:
        rendered = variant.format(reason="样例数据暂时拉不到")
        assert rendered.startswith("样例数据暂时拉不到，")
        # 守岸人语气底线：不出现机器腔/客套话术组合。
        assert "为您" not in rendered and "作为一个" not in rendered


def test_u11_admin_gate_snapshot() -> None:
    """U11+Q-02 管理员门禁：原模板快照（订阅族禁碰文件沿用）+ 域内 5 文件变体化。"""
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

    # 禁碰域（subscribe.py / subscribe_v2.py）保持 ADMIN_GATE_REQUIRED 原引用零改动。
    sites = [
        ("subscribe.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="把订阅推送到本群")'),
        ("subscribe.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="看本群订阅")'),
        ("subscribe_v2.py", 'user_copy.ADMIN_GATE_REQUIRED.format(action="看本群订阅")'),
    ]
    for filename, expression in sites:
        _assert_site(filename, expression)

    # Q-02（2026-09-15）：域内引用点升级为 ADMIN_GATE_TEMPLATES 轮换取句；
    # 锁定「池引用 + action 实参」表达式。
    variant_sites = [
        ("debug.py", "看运行时排障记录"),
        ("echo.py", "看运行时状态"),
        ("music.py", "改点歌输出模式"),
        ("runtime_logs.py", "查运行时日志"),
        ("today_history.py", "取消群推送时间"),
        ("today_history.py", "设置群推送时间"),
    ]
    for filename, action in variant_sites:
        source = (_CAP_DIR / filename).read_text(encoding="utf-8")
        assert "random.choice(user_copy.ADMIN_GATE_TEMPLATES)" in source, (
            f"{filename} 未引用权限拒绝变体池"
        )
        assert f'action="{action}"' in source, f"{filename} 缺 action 实参：{action}"


def test_q02_admin_gate_pool_shape() -> None:
    """Q-02 池形态：≥8 条（P2-4 同规则 4→12）、首条=U11 原模板、{action}
    槽位齐全、无重复、可渲染。"""
    pool = user_copy.ADMIN_GATE_TEMPLATES
    assert 8 <= len(pool) <= 16
    assert pool[0] == user_copy.ADMIN_GATE_REQUIRED
    assert len(set(pool)) == len(pool)
    assert all("{action}" in variant for variant in pool)
    for variant in pool:
        rendered = variant.format(action="样例操作")
        assert "样例操作" in rendered
        assert "管理员" in rendered  # 拒绝语义必须指明出路
        # 守岸人语气底线：不出现机器腔/客套话术组合。
        assert "为您" not in rendered and "作为一个" not in rendered


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
    """行为级抽查：debug 拒绝句随 Q-02 变体池轮换，输出必属池渲染集合。"""
    from plugins.bot_unified_runtime.capabilities import debug as debug_cap

    assert debug_cap._denied_body() in {
        variant.format(action="看运行时排障记录")
        for variant in user_copy.ADMIN_GATE_TEMPLATES
    }


def test_a19_group_failure_ack_pool_shape() -> None:
    """A-19 群聊能力失败降级池形态：≥8 条（P2-4 同规则 4→12）、固定句
    无槽位、无重复、守岸人语气。"""
    pool = user_copy.GROUP_FAILURE_ACK_TEMPLATES
    assert 8 <= len(pool) <= 16
    assert len(set(pool)) == len(pool)
    # 固定短句：不携带 {reason}/{action} 等槽位（错误细节绝不回群）。
    assert all("{reason}" not in variant and "{action}" not in variant for variant in pool)
    for variant in pool:
        # 守岸人语气底线：温和短句，不出现机器腔/客套话术组合，不拖尾「～」。
        assert "为您" not in variant and "作为一个" not in variant
        assert not variant.rstrip().endswith("～")
