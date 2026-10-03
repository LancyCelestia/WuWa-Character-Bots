"""E2E 验收脚本回归（离线）：矩阵构造 + DRY-RUN mock 队列 + 安全阀。

覆盖 scripts/e2e_acceptance.py 的可测内核，全程不联网、不真发：
- 验收矩阵覆盖任务要求的全部消息种类，且各能力构造函数离线可构建；
- DRY-RUN 路径走真实 RuntimePipeline（policy → capability → render →
  SendRequest → InMemorySendQueue.submit），验证入队产物与预览格式；
- 安全阀：--execute 无持久化队列拒绝、非 white1 群拒绝、black 名单拒绝。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import scripts.e2e_acceptance as e2e
from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import ReceiptState, SessionType
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue

EXPECTED_KEYS = {
    # ①文本/长文本/多段
    "text-short",
    "text-long",
    "text-parts",
    # ②解析卡 ③点歌候选卡
    "content-bili",
    "music-candidates",
    # ④全球股指全量 ⑤财经/科技快报全量
    "market-global",
    "news-finance",
    "news-tech",
    # ⑥天气+预警 ⑦随机图 ⑧占卜 ⑨help 卡 ⑩好感度卡 ⑪提醒
    "weather-alert",
    "randpic",
    "divination",
    "help",
    "affinity",
    "reminder-list",
}


def _runtime_stub(tmp_path, **config_kwargs) -> e2e.E2eRuntime:
    """离线替身运行面；``tmp_path`` **必需**——它当运行数据根用（AGENTS 规则 2/6）。

    为什么直呼 ``Config(...)`` 会往源码树落盘（2026-10-02 runtime-layout 门红实案）：
    ``Config`` 是普通 ``BaseModel``、**不读环境变量**，缺省 ``bot_runtime_data_dir="data"``
    经 ``config.Config._resolve_runtime_data_paths`` 折成「仓库根/data」＝源码树；
    ``PATH_REMAPPED_FIELDS`` 名单在这里是**生效**的，只是把 ``data/control_plane_config.sqlite3``
    折进源码树而不是 Runtime——**在册 ≠ 落点在 Runtime**。conftest 的 L1 隔离缝只挪
    ``BOT_RUNTIME_DATA_DIR`` 环境变量（罩 ``scripts/runtime_paths.py`` 的读者），管不到本构造点。
    后果链：``e2e.build_pipeline`` → ``e2e_acceptance._bot_self_name`` →
    ``persona_profile.active_persona_id`` → ``settings.build_runtime_settings_store`` →
    ``InstanceSettingsManager.get`` → ``config_store.SQLiteConfigStateStore.__init__``
    在源码树 ``data/`` mkdir + ``sqlite3.connect`` 建库（生产库另住 ``ChatBot_Runtime/data/``）。
    """
    city = str(config_kwargs.pop("city", "北京"))
    # bot_affinity_enabled=False：离线测试不得打开 Runtime 真实好感度库；
    # 能力层对 store=None 会走降级文案，构造路径依旧完整可测。
    config_kwargs.setdefault("bot_runtime_data_dir", str(tmp_path / "runtime-data"))
    config = Config(
        bot_quiet_hours_enabled=False,
        bot_affinity_enabled=False,
        **config_kwargs,
    )
    # P-G3 第二波（2026-09-29）把验收面的合并转发署名统一到唯一读法
    # e2e._bot_self_name → persona_profile.current_bot_nickname(active_persona_id(
    # override_provider=runtime.runtime_settings.get_persona_override))。真身方法＝
    # runtime/settings.py 的 ``get_persona_override(self) -> str``，调用面是**零参**
    # （active_persona_id 的 override_provider: Callable[[], object]）。替身要跟着长：
    # 离线不表态切换态 → 返回空串，回落 config 主人格档现读，与台账 #60★
    # 「禁读 get_login_info 认自身名」同一口径（生产侧本来就没读它）。
    settings = SimpleNamespace(get=lambda key, cfg: None, get_persona_override=lambda: "")
    return e2e.E2eRuntime(
        config=config,
        runtime_settings=settings,
        render_backend=None,
        execute=False,
        city=city,
        bot_id="",
        sender_id="10000",
    )


def test_matrix_covers_acceptance_matrix(tmp_path) -> None:
    matrix = e2e.build_matrix(_runtime_stub(tmp_path))
    keys = {item.key for item in matrix}
    missing = EXPECTED_KEYS - keys
    assert not missing, f"验收矩阵缺项: {missing}"
    # 每项都有非空触发文本与能力 id，且 key 不重复。
    all_keys = [item.key for item in matrix]
    assert len(all_keys) == len(set(all_keys))
    for item in matrix:
        assert item.capability_id, item.key
        assert item.trigger_text(_runtime_stub(tmp_path)).strip(), item.key


def test_matrix_capabilities_build_offline(tmp_path) -> None:
    """全部能力构造函数在离线 Config 下可构建（构造期不联网）。"""
    runtime = _runtime_stub(tmp_path)
    for item in e2e.build_matrix(runtime):
        capability = item.build(runtime)
        assert callable(capability), item.key


def test_weather_trigger_uses_city_argument(tmp_path) -> None:
    runtime = _runtime_stub(tmp_path, city="上海")
    item = next(
        entry for entry in e2e.build_matrix(runtime) if entry.key == "weather-alert"
    )
    assert item.trigger_text(runtime) == "天气 上海"


def test_synthesize_message_group_and_private_shapes() -> None:
    group_msg = e2e.synthesize_message(
        text="全球股市",
        session_type=SessionType.GROUP,
        target_id="123",
        sender_id="456",
        bot_id="789",
        seq=1,
    )
    assert group_msg.session_id == "group_123_456"
    assert group_msg.group_id == "123"
    assert group_msg.session_type is SessionType.GROUP
    assert group_msg.mentions_bot is True
    assert group_msg.plain_text == "全球股市"
    private_msg = e2e.synthesize_message(
        text="help",
        session_type=SessionType.PRIVATE,
        target_id="456",
        sender_id="456",
        bot_id="789",
        seq=2,
    )
    assert private_msg.group_id is None
    assert private_msg.session_id == "456"
    assert private_msg.session_type is SessionType.PRIVATE


def _run_matrix_keys(runtime: e2e.E2eRuntime, keys: list[str], group_id: str = "555"):
    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    pipeline = e2e.build_pipeline(runtime, queue)
    outcomes = []
    for seq, key in enumerate(keys, 1):
        item = next(entry for entry in e2e.build_matrix(runtime) if entry.key == key)
        outcomes.append(
            e2e.execute_item(
                pipeline=pipeline,
                send_queue=queue,
                item=item,
                runtime=runtime,
                session_type=SessionType.GROUP,
                target_id=group_id,
                seq=seq,
            )
        )
    return queue, outcomes


def test_dry_run_walks_real_pipeline_into_mock_queue(tmp_path) -> None:
    """DRY-RUN：真实管道产出 SendRequest 入 InMemory mock 队列，绝不外发。

    InMemorySendQueue.submit 即记 SENT（transport=memory，仅进程内登记）——
    这正是 DRY-RUN「不接 transport、零真实发送路径」的队列语义。
    """
    runtime = _runtime_stub(tmp_path)
    queue, outcomes = _run_matrix_keys(
        runtime, ["text-short", "text-parts", "text-long"]
    )
    assert queue.safe_summary()["sent"] == 3
    for outcome in outcomes:
        assert outcome.error == "", outcome.error
        assert outcome.receipt is not None
        assert outcome.receipt.state == ReceiptState.SENT
        assert outcome.receipt.transport == "memory"
        assert outcome.send_request is not None
        request = outcome.send_request
        assert request.target_scope is SessionType.GROUP
        assert request.target_id == "555"
        assert request.session_id == "group_555_10000"
        assert request.bot_id == "unknown"  # stub bot_id 为空 → 合成消息回退 unknown


def test_dry_run_preview_describes_content_types(tmp_path) -> None:
    runtime = _runtime_stub(tmp_path)
    _queue, outcomes = _run_matrix_keys(runtime, ["text-short", "text-parts"])
    by_key = {outcome.item.key: outcome for outcome in outcomes}
    short = e2e.format_preview(by_key["text-short"].send_request)
    assert short.startswith("content_type=text")
    assert "group:555" in short
    parts = e2e.format_preview(by_key["text-parts"].send_request)
    assert "content_type=chunks" in parts
    assert "⏎" in parts  # 多段文本被摊平成单行预览


def test_dry_run_find_request_returns_rendered_text(tmp_path) -> None:
    runtime = _runtime_stub(tmp_path)
    _queue, outcomes = _run_matrix_keys(runtime, ["text-short"])
    request = outcomes[0].send_request
    assert request is not None
    assert "E2E 验收" in request.content.text_fallback


def test_execute_item_reports_build_error_without_raising(tmp_path) -> None:
    runtime = _runtime_stub(tmp_path)

    def _boom(_rt: e2e.E2eRuntime):
        raise RuntimeError("boom")

    broken = e2e.MatrixItem(
        key="broken",
        label="坏项",
        capability_id="bot.broken",
        build=_boom,
        text="x",
    )
    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    outcome = e2e.execute_item(
        pipeline=e2e.build_pipeline(runtime, queue),
        send_queue=queue,
        item=broken,
        runtime=runtime,
        session_type=SessionType.GROUP,
        target_id="555",
        seq=1,
    )
    assert "boom" in outcome.error
    assert outcome.receipt is None


def test_execute_requires_persistent_sqlite_queue(tmp_path) -> None:
    runtime = _runtime_stub(tmp_path)
    runtime.execute = True
    with pytest.raises(e2e.E2eSafetyError):
        e2e.choose_send_queue(runtime, audit_logger=InMemoryAuditLogger())


def test_dry_run_always_uses_in_memory_queue(tmp_path) -> None:
    runtime = _runtime_stub(
        tmp_path,
        bot_send_queue_enabled=True,
        bot_send_queue_db_path="whatever.sqlite3",
    )
    queue, desc = e2e.choose_send_queue(runtime, audit_logger=InMemoryAuditLogger())
    assert isinstance(queue, InMemorySendQueue)
    assert desc.startswith("dry-run:")


def test_group_whitelist_gate_blocks_non_white1(tmp_path) -> None:
    runtime = _runtime_stub(tmp_path, bot_group_white1=["111"])
    allowed, reason = e2e.check_group_allowed(runtime, "111")
    assert allowed and "WHITE1" in reason
    allowed, reason = e2e.check_group_allowed(runtime, "999")
    assert not allowed and "WHITE1" in reason


def test_group_whitelist_gate_rejects_blacklists(tmp_path) -> None:
    runtime = _runtime_stub(
        tmp_path,
        bot_group_white1=["111"],
        bot_group_black1=["222"],
        bot_group_black2=["333"],
    )
    for gid in ("222", "333"):
        allowed, reason = e2e.check_group_allowed(runtime, gid)
        assert not allowed
        assert "BLACK" in reason


def test_long_text_body_is_long_enough_for_forward_threshold() -> None:
    body = e2e._long_text_body()
    assert len(body) >= 1500  # 默认 bot_render_forward_min_chars
