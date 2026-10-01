"""热改面全量审计（2026-09-15，SETTABLE 回标）：白名单=真热改，冻结键=诚实拒绝。

C-09 只清了 2 个装配期冻结键；本审计把 SETTABLE_KEYS 逐键按消费点复核：
判据=键值在每次消费时现读 store / 合并层 config → 可热改；装配期快照进
调度器闭包 / PolicySettings / pipeline 快照字段 / 工厂闭包 → 写成功但行为
不变（死开关），移入 RESTART_REQUIRED_KEYS。实证手段：构造 store 覆盖后调
``_config_with_runtime_overrides``，观测合并结果（poke 覆盖零传播=死开关，
quiet 覆盖正常传播=活通路对照）。

审计总账：新增 SETTABLE 4 键（chat 能力每消息 get_or 现读、白名单此前漏登）；
移出 SETTABLE→RESTART_REQUIRED 28 键 + 半接线 1 键（BOT_DOWNLOAD_PROXY）；
维持不动 37 键。危险键（密钥/权限/发送面）本来就不在白名单，零新增。
"""

from __future__ import annotations

import json

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    RESTART_REQUIRED_KEYS,
    SETTABLE_KEYS,
    RuntimeSettingsStore,
)

# ---- ① 审计新增 SETTABLE 键（消费点：capabilities/chat.py 每消息 get_or）----
NEW_SETTABLE_KEYS: dict[str, tuple[str, object]] = {
    "BOT_CHAT_FAST_MAX_CANDIDATES": ("3", 3),
    "BOT_CHAT_FAST_CONTEXT_BUDGET": ("3000", 3000),
    "BOT_CHAT_FAST_WEB_MAX_QUERIES": ("2", 2),
    "BOT_CHAT_FAST_SKIP_WEB_PAGES": ("false", False),
}

# ---- ② 审计移出白名单的 28 键（原 SETTABLE → RESTART_REQUIRED）----
MOVED_TO_RESTART_KEYS: frozenset[str] = frozenset({
    # 群策略族
    "BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY",
    "BOT_GROUP_PROACTIVE_COOLDOWN_SECONDS",
    "BOT_GROUP_PROACTIVE_MAX_REPLIES_PER_HOUR",
    # 合并转发阈值（pipeline 装配期快照 int）
    "BOT_RENDER_FORWARD_MIN_NODES",
    "BOT_RENDER_FORWARD_MIN_CHARS",
    "BOT_RENDER_FORWARD_MAX_NODES",
    "BOT_RENDER_FORWARD_NODE_CHARS",
    # 群摘要名单（装配期烘进摘要过滤器）
    "BOT_GROUP_DIGEST_LIST_MODE",
    "BOT_GROUP_DIGEST_WHITELIST",
    "BOT_GROUP_DIGEST_BLACKLIST",
    # 模型分时段表（30s 任务闭包读裸 config）
    "BOT_MODEL_SCHEDULE",
    # 联网检索供应商链（装配期工厂闭包）
    "BOT_WEB_SEARCH_PROVIDER",
    "BOT_WEB_SEARCH_FALLBACK_PROVIDERS",
    # 视频理解族（装配期 media_config 裸 config）
    "BOT_VIDEO_MAX_FRAMES",
    "BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE",
    "BOT_VIDEO_PROGRESS_ACK_ENABLED",
    "BOT_VIDEO_FUZZY_FOLLOWUP",
    "BOT_VIDEO_DEEP_ENABLED",
    "BOT_VIDEO_NATIVE_INPUT",
    "BOT_CONTENT_VIDEO_AUTO_SEND",
    # 戳一戳族（合并表未登记 bot_poke_*，覆盖不可达）
    "BOT_POKE_ENABLED",
    "BOT_POKE_PRIVATE_COOLDOWN_SECONDS",
    "BOT_POKE_GROUP_COOLDOWN_SECONDS",
    "BOT_POKE_PROBABILITY",
    "BOT_POKE_REPLY_ENABLED",
    "BOT_POKE_POKE_BACK",
    "BOT_POKE_GROUP_TEXT",
    "BOT_POKE_PRIVATE_TEXT",
})

# ---- ③ 维持不动的代表键（防过度移除护栏；全量判定见各键消费点证据）----
KEEP_HOT_SAMPLE = (
    "BOT_CHAT_TEMPERATURE",
    "BOT_CHAT_MODEL",
    "BOT_CHAT_FAST_MODE",
    "BOT_MEMORY_EXTRACT_ENABLED",
    "BOT_TRANSPORT_TIMEOUT_SECONDS",
    "BOT_MODEL_PRIORITY_GROUPS",
    "BOT_MODEL_PRICES",
    "BOT_MEME_SEARCH_ENABLED",
    "BOT_WEB_SEARCH_ENABLED",
    "BOT_WEB_SEARCH_ADMIN_NOTICE",
    "BOT_PERSONA_ACTION_BRACKETS",
    "BOT_MUSIC_MODE",
    "BOT_REPLY_DETAIL",
    "BOT_VISION_ENABLED",
    "BOT_VISION_MODE",
    "BOT_ASR_ENABLED",
    "BOT_VIDEO_UNDERSTANDING_ENABLED",
    "BOT_GROUP_BLACK1",
    "BOT_GROUP_WHITE2",
    "BOT_QUIET_HOURS_ENABLED",
    "BOT_QUIET_HOURS_BYPASS_ROLES",
    "BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR",
    "BOT_RATE_LIMIT_EMOTION_EXEMPT",
)


@pytest.mark.parametrize("key", NEW_SETTABLE_KEYS)
def test_new_settable_keys_accepted_and_read_back(tmp_path, key: str) -> None:
    raw, converted = NEW_SETTABLE_KEYS[key]
    # allow_no_gate：本件审的是白名单成员与合并传播，不审档位执法（咽喉测试住在
    # test_safety_exec_throat_wire / test_safety_exec_session_throat）。摘门只为让
    # set_override 走通白名单腿；键的 SETTABLE 成员资格仍由下面的断言锁死。
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json", allow_no_gate=True)
    assert store.set_override(key, raw) == converted
    # 消费接口（store.get / get_or）必须读到覆盖值——chat 能力每消息即以此形态消费。
    assert store.get(key, object()) == converted
    assert store.get_or(key, "default") == converted
    # 覆盖持久化：重启后仍生效。
    reloaded = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    assert reloaded.get(key, object()) == converted


@pytest.mark.parametrize("key", NEW_SETTABLE_KEYS)
def test_consumer_get_or_falls_back_without_override(tmp_path, key: str) -> None:
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    assert store.get_or(key, "fallback-default") == "fallback-default"


@pytest.mark.parametrize(
    "key",
    [
        "BOT_POKE_ENABLED",
        "BOT_RENDER_FORWARD_MIN_NODES",
        "BOT_MODEL_SCHEDULE",
        "BOT_WEB_SEARCH_PROVIDER",
        "BOT_VIDEO_MAX_FRAMES",
        "BOT_GROUP_DIGEST_WHITELIST",
    ],
)
def test_moved_keys_rejected_with_restart_hint(tmp_path, key: str) -> None:
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    with pytest.raises(ValueError) as excinfo:
        store.set_override(key, "true")
    message = str(excinfo.value)
    assert key in message, "拒绝信息必须点名键"
    assert "重启" in message, "拒绝信息必须提示需重启（死开关不许骗人）"
    # 拒绝即零残留：内存不留覆盖，也不落设置文件。
    assert store.list_overrides() == {}
    assert not (tmp_path / "runtime_settings.json").exists()


def test_all_moved_keys_deregistered_with_reason() -> None:
    assert len(MOVED_TO_RESTART_KEYS) == 28
    for key in MOVED_TO_RESTART_KEYS:
        assert key not in SETTABLE_KEYS, f"{key} 是装配期冻结键，不得留在热改白名单"
        assert key in RESTART_REQUIRED_KEYS, f"{key} 必须登记进重启键清单"
        assert RESTART_REQUIRED_KEYS[key].strip(), "重启键必须附拒绝原因（供管理员阅读）"


def test_keep_hot_sample_still_registered() -> None:
    for key in KEEP_HOT_SAMPLE:
        assert key in SETTABLE_KEYS, f"{key} 消费点现读 store，必须维持热改白名单"
        assert key not in RESTART_REQUIRED_KEYS


def test_no_overlap_between_registries() -> None:
    overlap = set(SETTABLE_KEYS) & set(RESTART_REQUIRED_KEYS)
    assert not overlap, f"白名单与重启键清单不得交集：{sorted(overlap)}"


def test_merged_config_poke_dead_vs_quiet_live() -> None:
    """实跑实证：合并层对 poke 覆盖零传播（死开关实锤），对 quiet 正常传播。"""
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config

    config = Config()
    # allow_no_gate：本件实证合并层传播（poke 死开关 / quiet 活通路），不审档位执法
    # （咽喉测试住在 test_safety_exec_throat_wire）。此处的 set_override 只为造 quiet 覆盖。
    store = RuntimeSettingsStore(None, allow_no_gate=True)
    if "BOT_POKE_ENABLED" in SETTABLE_KEYS:
        pytest.skip("poke 键已回白名单（合并表接线后），本实证不再适用")
    # 直注内部覆盖（绕过 set_override 的白名单校验）：模拟审计前经 set 写入的
    # 遗留覆盖，观测合并层是否把它送进消费方 config。
    store._overrides["BOT_POKE_ENABLED"] = False
    store.set_override("BOT_QUIET_HOURS_ENABLED", "false")
    merged = _config_with_runtime_overrides(config, store)
    # 死开关：poke 覆盖穿不透合并层（合并表未登记 bot_poke_*）。
    assert getattr(merged, "bot_poke_enabled", None) is True
    # 活通路对照：quiet 覆盖正常传播（热改真生效的键长这样）。
    assert getattr(merged, "bot_quiet_hours_enabled", None) is False


def test_load_drops_legacy_persisted_override_for_moved_key(tmp_path) -> None:
    # 审计前经 /bot runtime set 写入的覆盖从未生效过（消费点装配期冻结），
    # 加载时必须自动丢弃，不留幽灵覆盖；仍热改键的覆盖照常保留。
    path = tmp_path / "runtime_settings.json"
    path.write_text(
        json.dumps(
            {
                "overrides": {
                    "BOT_POKE_ENABLED": False,
                    "BOT_RENDER_FORWARD_MIN_NODES": 2,
                    "BOT_CHAT_FAST_MODE": True,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = RuntimeSettingsStore(path)
    assert store.list_overrides() == {"BOT_CHAT_FAST_MODE": True}
