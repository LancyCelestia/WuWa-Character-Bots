"""「历史上的今天」推送表健壮性回归（C组审查修复）：读失败必须拒绝改写，
写失败必须回错——此前读失败返回空表后被「设置/取消」整体覆写，丢掉其他会话订阅。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.capabilities.today_history import (
    _load_push_table_checked,
    _save_push_table,
)


def test_corrupt_push_table_is_reported_not_silently_emptied(tmp_path) -> None:
    push_file = tmp_path / "push.json"
    push_file.write_text("{corrupt json", encoding="utf-8")
    table, ok = _load_push_table_checked(str(push_file))
    assert ok is False
    assert table == {}


def test_missing_push_table_is_fresh_start(tmp_path) -> None:
    table, ok = _load_push_table_checked(str(tmp_path / "missing.json"))
    assert ok is True
    assert table == {}


def test_save_failure_reports_false(tmp_path) -> None:
    # 目录当文件写，触发 OSError
    blocker = tmp_path / "push.json"
    blocker.mkdir()
    assert _save_push_table(str(blocker), {"f_1": {"hour": 8, "minute": 0}}) is False


def test_save_roundtrip(tmp_path) -> None:
    push_file = tmp_path / "push.json"
    assert _save_push_table(str(push_file), {"f_1": {"hour": 8, "minute": 5}}) is True
    table, ok = _load_push_table_checked(str(push_file))
    assert ok is True
    assert table == {"f_1": {"hour": 8, "minute": 5}}


def test_capability_refuses_overwrite_on_corrupt_table(tmp_path) -> None:
    from plugins.bot_unified_runtime.capabilities.today_history import (
        build_today_history_capability,
    )
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    push_file = tmp_path / "push.json"
    push_file.write_text("[{broken", encoding="utf-8")
    capability = build_today_history_capability(push_file=str(push_file))
    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text="历史上的今天 设置 8:00",
    )
    from plugins.bot_unified_runtime.contracts import BotDecision

    decision = BotDecision(
        request_id="req-test",
        should_respond=True,
        mode="command",
        trigger="历史上的今天",
        capability_id="bot.today_history",
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )
    result = capability(message, decision)
    assert "拒绝改写" in result.body
    # 原始损坏文件保持原样（未被空表覆写）
    assert push_file.read_text(encoding="utf-8") == "[{broken"
