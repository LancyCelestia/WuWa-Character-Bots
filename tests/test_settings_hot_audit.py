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


# ===========================================================================
# 席 F（2026-10-10）· 热合并层轮内省三刀
# ---------------------------------------------------------------------------
# 实测盘面（只读席 C 定位、本席同尺复算）：私聊 bot.chat 一次 check_and_record
# 触发 ``_config_with_runtime_overrides`` 15 次，旧形态 **434.27 ms/条**（本机复算
# 读数，两次分别 434.27 / 436.86 ms），全部跑在事件循环线程上。构成＝
#   ① 22 枚热键逐枚 ``store.get()`` × 每次 get 重跑一趟 ``list_overrides()``
#     （SQL backend 无覆盖缓存 ⇒ 每枚一趟 ``sqlite3.connect``+``BEGIN``+两条 SELECT）
#   ② 同一轮输入完全相同却合并 15 次
#   ③ 差集为空时仍整扫路径名册做重映射
# 修法三腿同批：快照一次 / 轮内 memo（版本尺＝backend 现成的 CAS ``revision`` 列）/
# 重映射只按 ``updates`` 与路径名册的差集。**一个数值都不改**（天花板、窗口、句数帽、
# 折句窗一律不动）⇒ 这里的判据全是「调用次数 / 输出一字不变 / 热改即时」，不含任何阈值。
# ===========================================================================

MEMO_ATTR = "_bot_hot_override_merge_memo"


class _ProbeSettings:
    """合并层探针替身：三种读面各记各的账，缺席面按开关摘掉（复刻假 store 的形状）。"""

    def __init__(
        self,
        mapping: dict[str, object],
        *,
        with_list_overrides: bool = True,
        with_revision: bool = False,
        revision_raises: bool = False,
        snapshot_raises: bool = False,
    ) -> None:
        self.mapping = dict(mapping)
        self.calls: dict[str, int] = {"get": 0, "list_overrides": 0, "revision": 0}
        self._with_list_overrides = with_list_overrides
        self._with_revision = with_revision
        self._revision_raises = revision_raises
        self._snapshot_raises = snapshot_raises
        if with_list_overrides:
            def _list() -> dict[str, object]:
                self.calls["list_overrides"] += 1
                if self._snapshot_raises:
                    raise RuntimeError("snapshot blown")
                return dict(self.mapping)

            self.list_overrides = _list  # type: ignore[method-assign]
        if with_revision:
            def _revision() -> int:
                self.calls["revision"] += 1
                if self._revision_raises:
                    raise RuntimeError("db locked")
                return self.revision_value

            self.revision = _revision  # type: ignore[method-assign]
        self.revision_value = 1

    def get(self, key: str, default: object = None) -> object:
        self.calls["get"] += 1
        if self._snapshot_raises:
            # 真 store 的 get 内部就是 list_overrides()：整表炸了它必然一起炸（复刻那一形）。
            raise RuntimeError("snapshot blown")
        return self.mapping.get(key.strip().upper(), default)


def _hot_key() -> tuple[str, str]:
    """挑一枚「在册可热改 + 在合并名册里 + 值是 int」的键做即时性靶子（现算，不抄）。"""
    from plugins.bot_unified_runtime.config import Config

    for env_key, field_name in _bot_root_module()._RUNTIME_HOT_OVERRIDE_FIELDS:
        if env_key not in SETTABLE_KEYS or env_key in RESTART_REQUIRED_KEYS:
            continue
        if isinstance(getattr(Config(), field_name, None), int) and not isinstance(
            getattr(Config(), field_name, None), bool
        ):
            return env_key, field_name
    raise AssertionError("合并名册里没有一枚 int 型可热改键＝靶子没了，别把锁删了")


def _bot_root_module():  # pragma: no cover - 只是把导入收在一处
    import plugins.bot_unified_runtime as pkg

    return pkg


class _PassThroughShell:
    """薄壳代理：``hidden`` 里点名的面**取不到**（AttributeError），其余逐方法透传真身。

    存在的理由（席 K，2026-10-10）＝公平 A/B 不许改工作树：对照组必须复刻**改前语义**，
    而改前形态是「逐枚 ``store.get()``、无轮内 memo」。把生产代码改回旧形态做对照会污染
    工作树（本席禁写生产件），所以用壳摘面：
      - 藏 ``revision``        ⇒ 版本尺取不到 ⇒ ``_remember`` 不挂 memo（省掉 ②）
      - 再藏 ``list_overrides`` ⇒ 快照面取不到 ⇒ 走「退回逐枚 ``get()``」那条腿
                                 （``RuntimeSettingsStore.get`` 内部就是 ``list_overrides()``）
                                 ⇒ **每枚热键一趟全新 SQLite 事务** ＝ 改前形态
    """

    def __init__(self, inner: object, hidden: tuple[str, ...] = ()) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_hidden", frozenset(hidden))

    def __getattr__(self, name: str) -> object:
        if name in object.__getattribute__(self, "_hidden"):
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_inner"), name)


def _clear_memo(store: object) -> None:
    if MEMO_ATTR in vars(store):
        delattr(store, MEMO_ATTR)


def _backend_store(tmp_path, instance: str = "default") -> RuntimeSettingsStore:
    """接 SQL backend 的 store（tmp_path 里的**新建**库，绝不碰生产 SQLite）。"""
    from plugins.bot_unified_runtime.control_plane.config_store import (
        SQLiteConfigStateStore,
    )

    backend = SQLiteConfigStateStore(tmp_path / "control_plane_config.probe.sqlite3",
                                     instance=instance)
    return RuntimeSettingsStore(
        tmp_path / f"runtime_settings_{instance}.json",
        instance=instance,
        backend=backend,
        allow_no_gate=True,
    )


# ---- ① 快照一次 -------------------------------------------------------------


def test_probe_harness_uses_one_snapshot_per_merge() -> None:
    """(a) 腿：一次合并**只取一次整表快照**，一枚 ``store.get()`` 都不许再发生。"""
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config

    roster = _bot_root_module()._RUNTIME_HOT_OVERRIDE_FIELDS
    assert len(roster) >= 20, f"合并名册缩到 {len(roster)} 枚＝本尺靶子迁移，同步尺"
    probe = _ProbeSettings({"BOT_QUIET_HOURS_ENABLED": False})
    merged = _config_with_runtime_overrides(Config(), probe)
    assert probe.calls["get"] == 0, f"仍在逐枚 store.get() 读热键：{probe.calls}"
    assert probe.calls["list_overrides"] == 1, f"整表快照次数≠1：{probe.calls}"
    assert merged.bot_quiet_hours_enabled is False, "覆盖必须照旧进视图"


def test_probe_harness_falls_back_for_duck_store_without_snapshot() -> None:
    """假 store 没有 ``list_overrides`` ⇒ 退回旧的逐枚 get 形态，读数一字不变。"""
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config

    probe = _ProbeSettings({"BOT_QUIET_HOURS_ENABLED": False}, with_list_overrides=False)
    merged = _config_with_runtime_overrides(Config(), probe)
    assert merged.bot_quiet_hours_enabled is False
    assert probe.calls["get"] == len(_bot_root_module()._RUNTIME_HOT_OVERRIDE_FIELDS)
    assert probe.calls["list_overrides"] == 0


def test_probe_harness_survives_a_blown_snapshot() -> None:
    """整表读炸（真 store 的 get 同一条腿，必然一起炸）⇒ 按「无覆盖」处理，绝不把异常抛进判定链。"""
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config

    config = Config()
    probe = _ProbeSettings({"BOT_QUIET_HOURS_ENABLED": False}, snapshot_raises=True)
    assert _config_with_runtime_overrides(config, probe) is config


# ---- ② 轮内 memo：输出不变 + 热改即时 --------------------------------------


def test_memo_output_is_field_by_field_identical_to_naive_recompute(tmp_path) -> None:
    """走 memo 与每次重算，产出的 config 视图与限流设置**逐字段相等**（同一条输入对象）。"""
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
        build_rate_limit_settings,
    )

    config = Config()
    store = _backend_store(tmp_path)
    env_key, field_name = _hot_key()
    want = int(getattr(config, field_name)) + 1
    store.set_override(env_key, str(want))
    store.set_override("BOT_QUIET_HOURS_ENABLED", "false")

    warm = _config_with_runtime_overrides(config, store)  # 冷算一次并落 memo
    warm_again = _config_with_runtime_overrides(config, store)  # memo 命中
    if hasattr(store, MEMO_ATTR):
        delattr(store, MEMO_ATTR)
    naive = _config_with_runtime_overrides(config, store)  # 同一对象、清掉 memo ⇒ 每次重算

    assert warm_again is warm, "memo 没命中＝(config 身份, revision) 尺没接上"
    assert warm is not config, "有覆盖却复用原对象＝污染生产 Config"
    assert warm.model_dump() == naive.model_dump(), "memo 路径与重算路径的视图字段不同＝输出变了"
    assert getattr(warm, field_name) == getattr(naive, field_name) == want
    assert (
        build_rate_limit_settings(warm).model_dump()
        == build_rate_limit_settings(naive).model_dump()
    ), "限流设置对象逐字段比对不等＝memo 改了判据"



def test_memo_is_busted_by_a_written_override(tmp_path) -> None:
    """即时性锁：写一条新覆盖 ⇒ backend ``revision`` 必 bump ⇒ 下一轮判定立刻读到新值。"""
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config

    config = Config()
    store = _backend_store(tmp_path)
    env_key, field_name = _hot_key()

    first = _config_with_runtime_overrides(config, store)
    assert getattr(first, field_name) == getattr(config, field_name)
    assert store.revision() is not None, "SQL backend 没给版本尺＝本锁靶子迁移，别删锁"
    before_revision = store.revision()
    # 先造一轮 memo（同一条覆盖写两次才看得出「命中旧的」还是「读到新的」）。
    store.set_override(env_key, "5")
    warmed = _config_with_runtime_overrides(config, store)
    assert getattr(warmed, field_name) == 5

    store.set_override(env_key, "9")
    after_revision = store.revision()
    assert after_revision != before_revision, "写侧没 bump revision＝热改即时性无尺可依"
    fresh = _config_with_runtime_overrides(config, store)
    assert getattr(fresh, field_name) == 9, (
        f"memo 把新覆盖吃掉了：读到 {getattr(fresh, field_name)!r}，期望 9"
        f"（revision {before_revision}→{after_revision}）"
    )
    assert fresh is not warmed, "memo 键没随 revision 失效＝还端着上一轮的旧视图"


def test_reset_override_also_busts_the_memo(tmp_path) -> None:
    """撤销覆盖（reset）同样 bump 版本尺 ⇒ 回落 Config 现值，不端着被撤掉的那一格。"""
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config

    config = Config()
    store = _backend_store(tmp_path)
    env_key, field_name = _hot_key()
    store.set_override(env_key, "11")
    assert getattr(_config_with_runtime_overrides(config, store), field_name) == 11
    store.reset_override(env_key)
    merged = _config_with_runtime_overrides(config, store)
    assert getattr(merged, field_name) == getattr(config, field_name), "reset 后必须回落 Config 现值"
    assert merged is config, "覆盖清空后应原对象返回（旧语义：无覆盖＝复用原件）"


def test_memo_degrades_when_the_store_has_no_version_scale(tmp_path) -> None:
    """假 store（无 ``revision``）/ 版本尺炸了 ⇒ 退化到不缓存：照样每轮现算、绝不抛。"""
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config

    config = Config()
    probe = _ProbeSettings({"BOT_QUIET_HOURS_ENABLED": False})  # 无 revision ⇒ 不缓存
    first = _config_with_runtime_overrides(config, probe)
    second = _config_with_runtime_overrides(config, probe)
    assert not hasattr(probe, MEMO_ATTR), "没有版本尺还挂 memo＝stale 风险的来源"
    assert first is not second, "无 revision 面必须每次现算（不许假缓存）"
    assert first.model_dump() == second.model_dump()

    broken = _ProbeSettings(
        {"BOT_QUIET_HOURS_ENABLED": False}, with_revision=True, revision_raises=True
    )
    merged = _config_with_runtime_overrides(config, broken)
    assert merged.bot_quiet_hours_enabled is False, "版本尺炸了也要照旧合并"
    assert not hasattr(broken, MEMO_ATTR), "读不到版本却落了 memo＝把异常吞成了 stale"


def test_memo_does_not_leak_across_config_objects(tmp_path) -> None:
    """memo 键含 config 身份：换一条 config（不同装配快照）不得端出上一轮的视图。"""
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config

    env_key, field_name = _hot_key()
    store = _backend_store(tmp_path)
    store.set_override(env_key, "4")
    config_a = Config()
    config_b = Config(**{field_name: 0})
    merged_a = _config_with_runtime_overrides(config_a, store)
    merged_b = _config_with_runtime_overrides(config_b, store)  # 同 store、同版本、不同 config
    assert merged_b is not merged_a, "memo 只认 (config 身份, 版本)＝两条装配快照必须各算各的"
    assert getattr(merged_b, field_name) == 4
    # 回到 a：仍然拿到 a 的视图（重算，不是拿 b 的）。
    back_to_a = _config_with_runtime_overrides(config_a, store)
    assert getattr(back_to_a, field_name) == getattr(merged_a, field_name)


# ---- ③ 重映射只按差集：绕开面照样堵死 --------------------------------------


def test_remap_runs_only_on_the_difference_between_updates_and_path_roster(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(c) 腿：差集为空＝恒等变换（不重扫名册）；差集非空＝一刀都不能少（裸 data/ 值必被折叠）。"""
    import plugins.bot_unified_runtime as bot_root
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import (
        PATH_REMAPPED_FIELDS,
        Config,
        path_typed_fields_in,
    )

    calls: list[int] = []
    real_remap = bot_root.remap_runtime_data_paths

    def _spy(target):  # 替身只记账再原样转发
        calls.append(1)
        return real_remap(target)

    monkeypatch.setattr(bot_root, "remap_runtime_data_paths", _spy)

    # 现算前提：热表与路径名册交集为零（这格红了说明盘面变了，(c) 的账要重算）。
    assert path_typed_fields_in(
        [field for _env, field in bot_root._RUNTIME_HOT_OVERRIDE_FIELDS]
    ) == ()
    assert PATH_REMAPPED_FIELDS, "路径名册读空＝本尺瞎"

    env_key, field_name = _hot_key()
    store = _backend_store(tmp_path)
    store.set_override(env_key, "6")
    config = Config(bot_runtime_data_dir=str(tmp_path / "runtime_data"))
    merged = _config_with_runtime_overrides(config, store)
    assert calls == [], "差集为空却整扫了路径名册＝(c) 那刀没省下来"
    assert getattr(merged, field_name) == 6
    # 名册里其余每条读数逐字不变（不重映射≠改映射，两侧必须给同一个落点）。
    for name in PATH_REMAPPED_FIELDS:
        assert getattr(merged, name) == getattr(config, name), f"{name} 被差集尺动了"

    # 毒表：有人把一枚真路径键登记进热表 ⇒ 差集非空 ⇒ 折叠照旧发生。
    raw_relative = "data/sneaky_meme_library"
    path_field = "bot_meme_library_dir"
    assert path_field in PATH_REMAPPED_FIELDS
    monkeypatch.setattr(
        bot_root,
        "_RUNTIME_HOT_OVERRIDE_FIELDS",
        bot_root._RUNTIME_HOT_OVERRIDE_FIELDS + (("BOT_SNEAKY_MEME_DIR", path_field),),
    )
    poison_store = _ProbeSettings({"BOT_SNEAKY_MEME_DIR": raw_relative})
    poisoned = _config_with_runtime_overrides(config, poison_store)
    assert calls, "热表出现路径键却没调重映射助手＝铁律 6 的绕开面重开"
    resolved = getattr(poisoned, path_field)
    assert resolved == str(tmp_path / "runtime_data" / "sneaky_meme_library"), resolved
    assert not resolved.replace("\\", "/").lower().startswith("data/"), resolved


# ===========================================================================
# ④ 改前/改后**同一把尺**：两把尺输出逐字段相等 ＋ memo 命中次数可观测
#    （席 K，2026-10-10；本波缺的是「没人交过改前/改后读数」，不是缺代码）
#
# 公平 A/B 的做法（🔴 绝不把生产代码改回旧形态做对照组——那会污染工作树）：
#   A 尺 = 真 store（``revision`` 面在）              ⇒ ②轮内 memo 通
#   B 尺 = 薄壳刻意摘掉 ``revision`` 与 ``list_overrides``
#         ⇒ 版本尺取不到 ⇒ 按 ``_remember`` 那条退路**不缓存**；
#         ⇒ 快照面取不到 ⇒ 按注释那条退路**逐枚 ``store.get()``**，而
#           ``RuntimeSettingsStore.get`` 内部就是 ``list_overrides()``
#           ⇒ 每枚热键一趟全新 SQLite 事务 ＝ **改前语义**
# 判据只管「输出相等」与「刀数（调用次数）」，不含任何耗时阈值。
# ===========================================================================


def _spied_store(store: RuntimeSettingsStore) -> dict[str, int]:
    """在**真 store 的实例属性**上装三只计数器（计数挂在薄壳上数不到真身内部那条腿）。

    B 尺走的是 ``RuntimeSettingsStore.get`` 内部的 ``self.list_overrides()``，
    只有把计数器装到被包的那个真对象身上才看得见它到底跑了几趟 SQLite。
    """
    calls: dict[str, int] = {"get": 0, "list_overrides": 0, "revision": 0}
    real_get = store.get
    real_list = store.list_overrides
    real_rev = store.revision

    def _get(key: str, config: object) -> object:
        calls["get"] += 1
        return real_get(key, config)

    def _list() -> dict[str, object]:
        calls["list_overrides"] += 1
        return real_list()

    def _rev() -> int | None:
        calls["revision"] += 1
        return real_rev()

    store.get = _get  # type: ignore[method-assign]
    store.list_overrides = _list  # type: ignore[method-assign]
    store.revision = _rev  # type: ignore[method-assign]
    return calls


def test_two_rulers_produce_field_by_field_identical_views(tmp_path) -> None:
    """两把尺（A＝memo 通／B＝退回逐枚现算）同库同输入 ⇒ config 视图与限流设置逐字段相等。"""
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
        build_rate_limit_settings,
    )

    config = Config()
    store = _backend_store(tmp_path)
    env_key, field_name = _hot_key()
    want = int(getattr(config, field_name)) + 1
    store.set_override(env_key, str(want))

    ruler_a = _PassThroughShell(store)
    ruler_b = _PassThroughShell(store, hidden=("revision", "list_overrides"))
    assert callable(getattr(ruler_a, "revision", None)), "A 尺没版本尺＝两把尺同形，本锁空转"
    assert not hasattr(ruler_b, "revision") and not hasattr(ruler_b, "list_overrides"), (
        "B 尺摘面失败＝对照组不是改前语义，本锁空转"
    )

    cold_a = _config_with_runtime_overrides(config, ruler_a)
    out_b = _config_with_runtime_overrides(config, ruler_b)
    assert cold_a is not config and out_b is not config, "有覆盖却没造新视图＝合并层被短路"
    assert cold_a.model_dump() == out_b.model_dump(), "两把尺的 config 视图字段不同＝memo 改了输出"
    assert (
        build_rate_limit_settings(cold_a).model_dump()
        == build_rate_limit_settings(out_b).model_dump()
    ), "两把尺的限流设置逐字段比对不等＝②那一刀动了判据"
    assert getattr(cold_a, field_name) == getattr(out_b, field_name) == want

    # 第二轮：A 命中 memo（同一对象），B 照旧每轮现算（新对象）⇒ 输出仍逐字段相等。
    warm_a = _config_with_runtime_overrides(config, ruler_a)
    again_b = _config_with_runtime_overrides(config, ruler_b)
    assert warm_a is cold_a, "A 尺第二轮没命中 memo＝②那一刀断了"
    assert again_b is not out_b, "B 尺被 memo 串到了＝对照组偷偷享用了 A 的缓存，A/B 不公平"
    assert warm_a.model_dump() == again_b.model_dump()
    assert (
        build_rate_limit_settings(warm_a).model_dump()
        == build_rate_limit_settings(again_b).model_dump()
    )


def test_memo_hit_count_is_observable_per_round(tmp_path) -> None:
    """memo 命中次数可观测：同一条 (config, revision) 上 N 轮合并＝1 趟整表快照 + N 次版本尺。

    对照腿（B 尺）在同 N 轮里要付 **N × 名册长度** 趟整表快照（每枚热键一趟全新 SQLite
    事务）且一次版本尺都读不到——这一格就是「改前/改后差的到底是哪几刀」的账。
    """
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config

    roster_len = len(_bot_root_module()._RUNTIME_HOT_OVERRIDE_FIELDS)
    assert roster_len >= 20, f"名册缩到 {roster_len} 枚＝本尺靶子迁移，同步尺"
    config = Config()
    store = _backend_store(tmp_path)
    env_key, field_name = _hot_key()
    store.set_override(env_key, str(int(getattr(config, field_name)) + 1))
    calls = _spied_store(store)
    rounds = 20

    ruler_b = _PassThroughShell(store, hidden=("revision", "list_overrides"))
    for _ in range(rounds):
        _config_with_runtime_overrides(config, ruler_b)
    assert calls["revision"] == 0, "B 尺读到了版本尺＝对照组不再是改前语义"
    assert calls["get"] == rounds * roster_len, f"改前形态该逐枚现算：{calls}"
    assert calls["list_overrides"] == rounds * roster_len, f"改前每枚热键一趟整表快照：{calls}"

    _clear_memo(store)
    mark = dict(calls)
    for _ in range(rounds):
        _config_with_runtime_overrides(config, store)  # A 尺＝真身，memo 槽就挂在它身上
    snaps = calls["list_overrides"] - mark["list_overrides"]
    revisions = calls["revision"] - mark["revision"]
    assert calls["get"] - mark["get"] == 0, f"A 尺仍在逐枚 store.get() 读热键：{calls}"
    assert revisions == rounds, f"每轮都得读一次版本尺（新鲜度尺不许省）：{revisions}!={rounds}"
    assert snaps == 1, f"N 轮只准冷算一次整表快照：{snaps}!={rounds}"
    assert revisions - snaps == rounds - 1, (
        f"memo 命中次数＝轮数-1 这一格断了：命中 {revisions - snaps}／应为 {rounds - 1}"
    )
    assert snaps < roster_len, "快照刀没省下来＝①那一刀退回逐枚形态"




# ===========================================================================
# 席 Q（2026-10-11 延迟收尾波）：**一条消息一把尺**——限流器合并视图的判定作用域
#
# 改前现算账：一条消息进判定 ⇒ ``limiter.settings`` 被读 **19** 次 ⇒ 19 趟合并解析
# （每趟读一次 CAS ``revision``，实测单趟 0.402–0.439ms）＝ P50 8.119ms／P95
# 20.171ms（台架 ``ab_bench.py`` 240 轮，A 尺＝生产同构）。本波折成 **1 趟**。
#
# 判据全是「解析次数／输出一字不变／热改两轴即时」，**不含任何阈值**：限流窗口、
# 句数帽、超时、退避、折句窗 3.0s、引用链 5 层一律未动；无新配置键、``Config``
# 字段不加不减（``test_config_field_registration_ledger`` 那把尺不受本波牵动）。
# ===========================================================================

_SETTINGS_READ_FLOOR = 8  # 判定体内 ``self.settings`` 读点下限（实测 19）：掉下去＝改动退化成删读点


def _scope_group_message(index: int):
    """组聊消息靶子（与真链路同形：非 @、非交互、非主动搭话＝走全套窗帽判定）。"""
    from plugins.bot_unified_runtime import contracts

    return contracts.IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="scope-probe",
        session_id=f"group_scope_{index}",
        session_type=contracts.SessionType.GROUP,
        sender_id=f"sender_{index}",
        group_id=str(960000000 + index),
        plain_text=f"作用域台架第 {index} 条",
    )


def _scope_rig(tmp_path, base, *, tag: str = "ruler"):
    """把限流器接到**真 store**（SQL backend）上，两把账各记各的：
    ``resolutions``＝合并视图被解析了几次（provider 那一趟），``property_reads``＝
    判定体里的 ``settings`` 读点次数（子类只加计数器，判定体逐字吃真身）。
    """
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
        build_rate_limit_settings,
    )

    config = Config()
    store = _backend_store(tmp_path)
    ledger: dict[str, object] = {"resolutions": 0, "views": [], "snapshots": []}

    def _provider():
        # 与装配口那条 lambda 同形（根 __init__.py 的 settings_provider）。
        ledger["resolutions"] += 1
        view = _config_with_runtime_overrides(config, store)
        built = build_rate_limit_settings(view)
        ledger["views"].append(view)  # type: ignore[index]
        ledger["snapshots"].append(built)  # type: ignore[index]
        return built

    class _Counted(base):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.property_reads = 0

        @property
        def settings(self):
            self.property_reads += 1
            return base.settings.fget(self)

    _Counted.__name__ = f"Counted{base.__name__}"
    if base.__name__ == "SQLiteRateLimiter":
        limiter = _Counted(tmp_path / f"scope_rate_limit_{tag}.db", settings=_provider)
    else:
        limiter = _Counted(_provider)
    return limiter, store, config, ledger


def _reads_and_resolutions(ledger: dict[str, object]) -> tuple[int, int]:
    return int(ledger["resolutions"]), len(ledger["snapshots"])


# ---- ① 一条消息＝一趟解析（两把尺同权）--------------------------------------


@pytest.mark.parametrize("ruler", ["in_memory", "sqlite"])
def test_one_merged_snapshot_per_message_on_both_rulers(tmp_path, ruler: str) -> None:
    """``check_and_record`` 一条消息只解析**一次**合并视图（改前 19 次），第二条消息第二趟。

    读点次数照旧（≥8，实测 19）＝证明折起来的是**解析**、不是把读点删了：删读点会
    让判定中途换尺（本波禁止的形状），而快照交接让一条判定从头到尾吃同一把尺。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
        InMemoryRateLimiter,
        SQLiteRateLimiter,
    )

    base = InMemoryRateLimiter if ruler == "in_memory" else SQLiteRateLimiter
    limiter, store, _config, ledger = _scope_rig(tmp_path, base, tag=ruler)
    env_key, field_name = _hot_key()
    store.set_override(env_key, "7")
    _clear_memo(store)

    decision = limiter.check_and_record(_scope_group_message(1), "bot.chat", amount=1)
    assert isinstance(decision.allowed, bool)
    assert getattr(ledger["views"][-1], field_name) == 7, "覆盖没进合并视图＝靶子空转，本锁无的放矢"
    assert limiter.property_reads >= _SETTINGS_READ_FLOOR, (
        f"判定体只读了 {limiter.property_reads} 次 settings＝读点被删了，折的不是解析次数"
    )
    assert _reads_and_resolutions(ledger)[0] == 1, (
        f"一条消息解析了 {ledger['resolutions']} 趟合并视图（改前 19，本波判据 1）"
    )

    reads_before = limiter.property_reads
    limiter.check_and_record(_scope_group_message(2), "bot.chat", amount=1)
    assert limiter.property_reads > reads_before, "第二条消息没再走判定＝上一条的账被复用"
    assert ledger["resolutions"] == 2, "作用域跨消息不失效＝热改永远读不到新值（本锁的另一发毒靶）"

    limiter.rollback(_scope_group_message(2), "bot.chat", amount=1, reason="allowed")
    assert ledger["resolutions"] == 3, f"rollback 这条公开入口又散开现算了：{ledger['resolutions']}!3"


# ---- ② 输出逐字段相等（作用域快照 vs 每次现算，同一输入对象）----------------


@pytest.mark.parametrize("ruler", ["in_memory", "sqlite"])
def test_scoped_snapshot_is_field_by_field_identical_to_fresh_recompute(
    tmp_path, ruler: str
) -> None:
    """同一条 config + 同一个 store（**不许各造一份**，自动生成 id 会假失败）：
    作用域里那份快照与「摘掉 memo 每次现算」的快照，config 视图与限流设置逐字段相等。
    """
    from plugins.bot_unified_runtime import _config_with_runtime_overrides
    from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
        InMemoryRateLimiter,
        SQLiteRateLimiter,
        build_rate_limit_settings,
    )

    base = InMemoryRateLimiter if ruler == "in_memory" else SQLiteRateLimiter
    limiter, store, config, ledger = _scope_rig(tmp_path, base, tag=ruler)
    env_key, field_name = _hot_key()
    store.set_override(env_key, "11")
    _clear_memo(store)

    limiter.check_and_record(_scope_group_message(1), "bot.chat", amount=1)
    scoped_view = ledger["views"][-1]
    scoped_snapshot = ledger["snapshots"][-1]

    # 对照腿：memo 摘掉再走一趟「每次现算」，输入对象与上面逐字同一个。
    _clear_memo(store)
    cold_view = _config_with_runtime_overrides(config, store)
    cold_snapshot = build_rate_limit_settings(cold_view)

    assert scoped_view is not config and cold_view is not config, "有覆盖却回原对象＝合并层被短路"
    assert getattr(scoped_view, field_name) == getattr(cold_view, field_name) == 11
    view_a, view_b = scoped_view.model_dump(), cold_view.model_dump()
    assert set(view_a) == set(view_b), "config 视图字段集不同＝②那一刀改了形状"
    view_diff = sorted(k for k in view_a if view_a[k] != view_b[k])
    assert not view_diff, f"config 视图字段级差集非空（比了 {len(view_a)} 枚）：{view_diff}"
    snap_a, snap_b = scoped_snapshot.model_dump(), cold_snapshot.model_dump()
    assert set(snap_a) == set(snap_b), "限流设置字段集不同＝本波动了 RateLimitSettings 形状"
    snap_diff = sorted(k for k in snap_a if snap_a[k] != snap_b[k])
    assert not snap_diff, f"限流设置字段级差集非空（比了 {len(snap_a)} 枚）：{snap_diff}"


# ---- ③ 热改即时性两轴：同进程写／跨进程写，都必须在**下一条目**可见 ----------


@pytest.mark.parametrize("ruler", ["in_memory", "sqlite"])
def test_in_process_override_reaches_the_next_message(tmp_path, ruler: str) -> None:
    """轴一：同进程 ``set_override``（``/bot runtime set`` 落的那条腿）⇒ 下一条目读到新值。"""
    from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
        InMemoryRateLimiter,
        SQLiteRateLimiter,
    )

    base = InMemoryRateLimiter if ruler == "in_memory" else SQLiteRateLimiter
    limiter, store, _config, ledger = _scope_rig(tmp_path, base, tag=ruler)
    env_key, field_name = _hot_key()

    limiter.check_and_record(_scope_group_message(1), "bot.chat", amount=1)
    used_before = getattr(ledger["views"][-1], field_name)
    revision_before = store.revision()
    want = int(used_before) + 3
    store.set_override(env_key, str(want))
    assert store.revision() != revision_before, "写侧没 bump revision＝版本尺失效，别把锁删了"

    limiter.check_and_record(_scope_group_message(2), "bot.chat", amount=1)
    used_after = getattr(ledger["views"][-1], field_name)
    assert ledger["resolutions"] == 2, f"下一条目没重新解析：{ledger['resolutions']}"
    assert used_after == want, f"作用域把同进程新覆盖吃掉了：{used_before}→{used_after}，应为 {want}"


def test_cross_process_override_reaches_the_next_message(tmp_path) -> None:
    """轴二：**另一进程真写库**（生产＝CLI 写、bot 读）⇒ 本进程下一条目读到新值。

    作用域缓存若做成进程级（路线 ②那枚禁走的形状），这一腿必红：版本尺只有现读
    才看得见别人写的 revision。
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
        InMemoryRateLimiter,
    )

    repo_root = Path(__file__).resolve().parents[1]
    limiter, _store, _config, ledger = _scope_rig(tmp_path, InMemoryRateLimiter, tag="xproc")
    env_key, field_name = _hot_key()
    probe_db = tmp_path / "control_plane_config.probe.sqlite3"

    limiter.check_and_record(_scope_group_message(1), "bot.chat", amount=1)
    before_value = getattr(ledger["views"][-1], field_name)
    want = int(before_value) + 5

    writer = tmp_path / "seatq_cross_writer.py"
    writer.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(repo_root)!r})\n"
        "from plugins.bot_unified_runtime.control_plane.config_store import (\n"
        "    SQLiteConfigStateStore,\n"
        ")\n"
        f"b = SQLiteConfigStateStore({str(probe_db)!r}, instance='default')\n"
        "snap = b.snapshot()\n"
        f"b.set_override({env_key!r}, {want!r}, expected_version=snap.version,\n"
        "                 actor='seatQ-child', request_id='cross-proc')\n"
        "print(b.revision())\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(writer)],
        capture_output=True,
        text=True,
        check=False,  # 子进程返回值由下一条断言判（判红要带 stderr 原文，不让 CalledProcessError 抢先）
        encoding="utf-8",  # 台账 #47★：subprocess.run 不钉 encoding 必崩
        cwd=str(repo_root),
        timeout=180,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(tmp_path / "pyc-child"),
            "BOT_AUTOSYNC": "0",
        },
    )
    assert proc.returncode == 0, f"子进程写库失败：{proc.stderr[-400:]}"

    try:
        limiter.check_and_record(_scope_group_message(2), "bot.chat", amount=1)
        after_value = getattr(ledger["views"][-1], field_name)
        assert ledger["resolutions"] == 2, f"下一条目没重新解析：{ledger['resolutions']}"
        assert after_value == want, (
            f"跨进程写被作用域缓存吃掉：读到 {after_value!r}，应为 {want!r}"
            f"（子进程 revision={proc.stdout.strip()}）"
        )
    finally:
        # 复位：别把这枚覆盖留给同库的另一席当生产值。
        _store.set_override(env_key, str(before_value))


# ---- ④ 作用域形状：只属于本尺、进出必成对、没开作用域逐字照旧 ---------------


def test_scope_belongs_to_one_ruler_only(tmp_path, monkeypatch) -> None:
    """A 尺的作用域绝不外借给 B 尺（同进程多把尺：主管道 + 各 smoke/控制面构造点）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.policy import rate_limit as rl

    limiter_a, _sa, _ca, ledger_a = _scope_rig(tmp_path, rl.InMemoryRateLimiter, tag="a")
    limiter_b, _sb, _cb, ledger_b = _scope_rig(tmp_path, rl.InMemoryRateLimiter, tag="b")
    real_proactive = rl.InMemoryRateLimiter._check_proactive
    seen: dict[str, object] = {}

    def _spy(self, message, capability_id):
        seen["a_pin"] = rl._pinned_settings_for(limiter_a)
        seen["b_pin"] = rl._pinned_settings_for(limiter_b)
        seen["b_before"] = ledger_b["resolutions"]
        _unused = limiter_b.settings  # B 尺在别人的作用域里读自己 ⇒ 必须现算，不吃 A 的快照
        assert _unused is not seen["a_pin"]
        seen["b_after"] = ledger_b["resolutions"]
        return real_proactive(self, message, capability_id)

    monkeypatch.setattr(rl.InMemoryRateLimiter, "_check_proactive", _spy)
    limiter_a.check_and_record(_scope_group_message(1), "bot.chat", proactive=True)

    assert seen["a_pin"] is not None, "A 尺入口没装作用域＝本波那一刀断了"
    assert seen["b_pin"] is None, "B 尺吃到了 A 尺的快照＝作用域串尺"
    assert seen["b_after"] == int(seen["b_before"]) + 1, f"B 尺没现算：{seen}"
    assert ledger_a["resolutions"] == 1
    assert rl._pinned_settings_for(limiter_a) is None, "出块没解装＝会跨消息漏到新作用域外"


def test_scope_unwinds_when_the_entry_raises(tmp_path, monkeypatch) -> None:
    """判定中途抛异常（含限流器自身出错）也必须解装：残留的 pin 会污染下一条消息。"""
    from plugins.bot_unified_runtime.domains.chat_reply.policy import rate_limit as rl

    limiter, _store, _config, ledger = _scope_rig(tmp_path, rl.InMemoryRateLimiter, tag="boom")

    def _blow(self, message, capability_id):
        raise RuntimeError("scope poison: entry raised")

    monkeypatch.setattr(rl.InMemoryRateLimiter, "_check_proactive", _blow)
    with pytest.raises(RuntimeError, match="scope poison"):
        limiter.check_and_record(_scope_group_message(1), "bot.chat", proactive=True)
    assert rl._pinned_settings_for(limiter) is None, "异常路径没解装＝pin 漏到下一条消息"

    limiter.check_and_record(_scope_group_message(2), "bot.chat", amount=1)
    assert ledger["resolutions"] == 2, f"炸过一条后解析次数不对：{ledger['resolutions']}"


def test_settings_property_outside_any_scope_still_resolves_every_read(tmp_path) -> None:
    """没开判定作用域（直接读 ``.settings`` 的老用法）＝逐字照旧每读一趟现算。

    这一腿是「别把缓存偷偷做成进程级」的反证：把 pin 做成跨消息不失效，读点就再也
    不解析 ⇒ 这里必红。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.policy.rate_limit import (
        InMemoryRateLimiter,
    )

    limiter, _store, _config, ledger = _scope_rig(tmp_path, InMemoryRateLimiter, tag="noscope")
    first = limiter.settings
    second = limiter.settings
    assert ledger["resolutions"] == 2, f"作用域外仍在缓存：{ledger['resolutions']}!=2"
    assert first.model_dump() == second.model_dump(), "同库同输入两次现算输出不同＝尺不干净"
    assert first.group_hourly_max_requests == second.group_hourly_max_requests
