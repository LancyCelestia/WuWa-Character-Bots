"""审查 C-09（死开关治理）：装配期冻结键不得伪热改。

背景（A 方审计 C-09，原锚点 runtime/settings.py 392/400 行）：
``BOT_GROUP_CHAT_AUTO_REPLY_ENABLED`` 与 ``BOT_SHARED_GROUP_CONTEXT_ENABLED``
曾列入 SETTABLE_KEYS，``/bot runtime set`` 写入成功并持久化——但消费点在
进程装配期把值冻结（前者冻进 RuntimePipeline→PolicySettings 布尔快照，
policy/gate.py 抽签读的是字段；后者烘进 character/shared_group.py 的
群摘要 provider 实例），运行时写入行为零变化 = 死开关骗人。

处置（诚实优先）：两键移出白名单、登记进 RESTART_REQUIRED_KEYS——
``set_override`` 明确拒绝并提示「改 .env + 重启」；C-09 修复前遗留的
持久化覆盖在加载时自动丢弃。消费点未来接入合并层实时求值后才可回白名单。
"""

from __future__ import annotations

import json

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RESTART_REQUIRED_KEYS,
    SETTABLE_KEYS,
    RuntimeSettingsStore,
)

_RESTART_KEYS = (
    "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED",
    "BOT_SHARED_GROUP_CONTEXT_ENABLED",
)


def test_restart_keys_removed_from_settable_and_registered() -> None:
    for key in _RESTART_KEYS:
        assert key not in SETTABLE_KEYS, f"{key} 是装配期冻结键，不得留在热改白名单"
        assert key in RESTART_REQUIRED_KEYS, f"{key} 必须登记进重启键清单"
        assert RESTART_REQUIRED_KEYS[key].strip(), "重启键必须附拒绝原因（供管理员阅读）"


@pytest.mark.parametrize("key", _RESTART_KEYS)
def test_set_override_rejects_with_restart_hint(tmp_path, key: str) -> None:
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    with pytest.raises(ValueError) as excinfo:
        store.set_override(key, "true")
    message = str(excinfo.value)
    assert key in message, "拒绝信息必须点名键"
    assert "重启" in message, "拒绝信息必须提示需重启（死开关不许骗人）"
    # 拒绝即零残留：内存不留覆盖，也不落设置文件。
    assert store.list_overrides() == {}
    assert not (tmp_path / "runtime_settings.json").exists()


def test_set_override_still_hot_for_normal_key(tmp_path) -> None:
    # 白名单键的热改通路不受 C-09 治理影响（回归护栏）。
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    converted = store.set_override("BOT_CHAT_FAST_MODE", "true")
    assert converted is True
    assert store.list_overrides() == {"BOT_CHAT_FAST_MODE": True}
    assert store.get("BOT_CHAT_FAST_MODE", object()) is True


def test_load_drops_legacy_persisted_overrides(tmp_path) -> None:
    # C-09 修复前写入的覆盖从未生效过（消费点装配期冻结），加载时必须
    # 自动丢弃，不留幽灵覆盖；白名单键的覆盖照常保留。
    path = tmp_path / "runtime_settings.json"
    path.write_text(
        json.dumps(
            {
                "overrides": {
                    "BOT_GROUP_CHAT_AUTO_REPLY_ENABLED": True,
                    "BOT_SHARED_GROUP_CONTEXT_ENABLED": True,
                    "BOT_CHAT_FAST_MODE": True,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = RuntimeSettingsStore(path)
    assert store.list_overrides() == {"BOT_CHAT_FAST_MODE": True}
