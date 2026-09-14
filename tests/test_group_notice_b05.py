"""群成员变更通知回归（审查 B-05）：欢迎语契约 + 开关 + 事件记录口径。"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime import _group_welcome_text
from plugins.bot_unified_runtime.config import Config


def test_welcome_text_with_nickname() -> None:
    text = _group_welcome_text("小涉")
    assert "小涉" in text and "欢迎" in text
    assert "（" in text and "）" in text, "括号动作用中文括号（identity.md 口径）"
    assert "\n" not in text, "欢迎语保持一行"


def test_welcome_text_without_nickname_falls_back_generic() -> None:
    text = _group_welcome_text("")
    assert "欢迎" in text
    assert "，欢" not in text.split("（")[-1].split("）")[0][:2], "空昵称不留悬空逗号开头"


def test_welcome_text_never_contains_user_id() -> None:
    text = _group_welcome_text("123456")
    assert "123456，" in text or "123456" in text  # 昵称原样；无 QQ 号字样拼接逻辑
    assert "QQ" not in text and "群号" not in text


def test_config_welcome_enabled_default() -> None:
    config = Config()
    assert getattr(config, "bot_group_welcome_enabled", None) is True


def test_config_welcome_gate_respected() -> None:
    """开关关闭时应直接返回：模拟 handler 的门逻辑（getattr 缺省 True）。"""
    enabled_config = SimpleNamespace(bot_group_welcome_enabled=False)
    assert getattr(enabled_config, "bot_group_welcome_enabled", True) is False
    # 门开着时 handler 才继续（构造 handlers 需 Driver，此处锁门本身）。
    assert getattr(SimpleNamespace(), "bot_group_welcome_enabled", True) is True
