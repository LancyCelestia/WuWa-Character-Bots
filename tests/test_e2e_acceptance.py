"""E2E 验收脚本回归（离线）：矩阵构造 + DRY-RUN mock 队列 + 安全阀。

覆盖 scripts/e2e_acceptance.py 的可测内核，全程不联网、不真发：
- 验收矩阵覆盖任务要求的全部消息种类，且各能力构造函数离线可构建；
- DRY-RUN 路径走真实 RuntimePipeline（policy → capability → render →
  SendRequest → InMemorySendQueue.submit），验证入队产物与预览格式；
- 安全阀：--execute 无持久化队列拒绝、非 white1 群拒绝、black 名单拒绝。
- 群侧斜杠命令四枚（identity set/unset-name、decision-query admin/member）的**双形断言**
  与 DRY-RUN 库重定向（2026-10-06 重锚，见文件末尾 GROUP_COMMAND_KEYS 那一节）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.e2e_acceptance as e2e
from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    ReceiptState,
    SessionType,
)
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


# --------------------------------------------------------------------------
# 群侧斜杠命令的双形断言（2026-10-06 重锚）。
#
# 背景：门禁 ``policy/gate.py`` 自 ``f3f177a3``（2026-10-01）起要求「命令态的群必须在册」
# （reason=command_group_unlisted），旁边还有白名单2 的 group_white2_need_trigger。
# 这四项原先只断「该入队」，在未在册群上跑 DRY-RUN 就必然挂一枚与裁定无关的假红。
# 重锚后的形状＝与门禁同形：入队了验回执文本；按设计拦下验**门名在场**。
# 下面每个用例都带一条反例（注毒），证明这把尺**能变红**——不是把断言改成迁就实现。
# --------------------------------------------------------------------------

GROUP_COMMAND_KEYS = (
    "identity-set-name",
    "identity-unset-name",
    "decision-query-admin",
    "decision-query-member",
)


def _dummy_item(key: str = "identity-set-name") -> e2e.MatrixItem:
    return e2e.MatrixItem(
        key=key, label=key, capability_id="bot.identity", build=lambda rt: rt, text="/bot x"
    )


def _blocked_outcome(reasons: list[str] | None, *, transport: str = "policy") -> e2e.ItemOutcome:
    return e2e.ItemOutcome(
        item=_dummy_item(),
        request_id="poison-req",
        receipt=DeliveryReceipt(
            request_id="poison-req", state=ReceiptState.BLOCKED, transport=transport
        ),
        audit_reasons=reasons,
    )


def test_group_command_expectations_pass_when_gate_denies_by_design(tmp_path) -> None:
    """未在册群：四枚的期望值＝blocked＋审计留痕点名 command_group_unlisted。"""
    runtime = _runtime_stub(tmp_path)  # 四张名单皆空 ⇒ 群 999 未在册
    _queue, outcomes = _run_matrix_keys(
        runtime, sorted(GROUP_COMMAND_KEYS), "999"
    )
    assert len(outcomes) == len(GROUP_COMMAND_KEYS)
    for outcome in outcomes:
        assert outcome.error == "", outcome.error
        assert outcome.receipt is not None
        assert outcome.receipt.state == ReceiptState.BLOCKED, outcome.item.key
        assert outcome.receipt.transport == "policy", outcome.item.key
        assert outcome.send_request is None, outcome.item.key
        # 审计回查口本身也在锁里：读不到＝None，下面那句 expect 就该红而不是静默。
        assert outcome.audit_reasons is not None, outcome.item.key
        assert any(
            "command_group_unlisted" in reason for reason in outcome.audit_reasons
        ), (outcome.item.key, outcome.audit_reasons)
        assert outcome.item.expect is not None, outcome.item.key
        assert outcome.item.expect(outcome) == "", (
            outcome.item.key,
            outcome.item.expect(outcome),
        )


def _run_with_pipeline(
    runtime: e2e.E2eRuntime, pipeline, queue, keys: list[str], session: SessionType, target: str
) -> list:
    outcomes = []
    for seq, key in enumerate(keys, 1):
        item = next(entry for entry in e2e.build_matrix(runtime) if entry.key == key)
        outcomes.append(
            e2e.execute_item(
                pipeline=pipeline,
                send_queue=queue,
                item=item,
                runtime=runtime,
                session_type=session,
                target_id=target,
                seq=seq,
            )
        )
    return outcomes


def test_group_command_positive_leg_asserts_reply_shape_in_private(tmp_path) -> None:
    """正跑面（今天只有私聊够得着）：四枚入队后 positive 断言照常咬文本。

    这四枚的回执都自带 ``privacy_level=personal``，群侧会被 reviewer 改道，所以
    「真跑通」那一轨在 ``--target-user`` 私聊里验（同一能力体、同一断言，零放宽）。
    """
    runtime = _runtime_stub(tmp_path)
    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    pipeline = e2e.RuntimePipeline(
        queue,
        InMemoryAuditLogger(),
        group_command_prefix=runtime.config.bot_runtime_group_command_prefix,
    )
    outcomes = _run_with_pipeline(
        runtime,
        pipeline,
        queue,
        sorted(GROUP_COMMAND_KEYS),
        SessionType.PRIVATE,
        "10000",
    )
    by_key = {outcome.item.key: outcome for outcome in outcomes}
    for key in GROUP_COMMAND_KEYS:
        outcome = by_key[key]
        assert outcome.error == "", (key, outcome.error)
        assert outcome.send_request is not None, (key, outcome.audit_reasons)
        assert outcome.item.expect is not None
        assert outcome.item.expect(outcome) == "", (key, outcome.item.expect(outcome))
    # 入队态必须**委托** positive，而不是「blocked 之外的都放行」：
    # 塞一条注定失败的正向断言，包装器必须把它原样报出来。
    poisoned = e2e.expect_command_after_group_gate(lambda _o: "POSITIVE-RAN")
    assert poisoned(outcomes[0]) == "POSITIVE-RAN"


def test_listed_group_personal_output_redirect_stays_red(tmp_path) -> None:
    """已在册群里这四枚被 reviewer 判 move_private（转私聊消费侧未实装）＝留红不吞。

    这是现算出来的真形态，不是假红：群侧今天确实送不出这条回执。把它算进
    「按设计被拦」的白名单＝放宽判据，故本用例锁的反方向是**必须红**。
    """
    runtime = _runtime_stub(tmp_path)
    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    pipeline = e2e.RuntimePipeline(
        queue,
        InMemoryAuditLogger(),
        group_command_prefix=runtime.config.bot_runtime_group_command_prefix,
        group_white1=frozenset({"555"}),
    )
    outcomes = _run_with_pipeline(
        runtime,
        pipeline,
        queue,
        sorted(GROUP_COMMAND_KEYS),
        SessionType.GROUP,
        "555",
    )
    assert len(outcomes) == len(GROUP_COMMAND_KEYS)
    for outcome in outcomes:
        assert outcome.error == "", (outcome.item.key, outcome.error)
        assert outcome.send_request is None, outcome.item.key
        assert any("move_private" in r for r in outcome.audit_reasons or ()), (
            outcome.item.key,
            outcome.audit_reasons,
        )
        reason = outcome.item.expect(outcome) if outcome.item.expect else ""
        assert reason, (outcome.item.key, "个人输出改道被读成 PASS＝吞真问题")
        assert "reviewer" in reason, reason


def test_command_gate_expect_poison_reasonless_block_is_red() -> None:
    """注毒①：blocked/policy 却查不到在册门名（含零留痕）＝判红，不算「随便拦」。"""
    expect = e2e.expect_command_after_group_gate(lambda _o: "")
    assert expect(_blocked_outcome([]))
    assert expect(_blocked_outcome(["policy_denied", "sender_blocked"]))
    # 安静时间/限流都是**别的**设计拦点，不在本项的期望内：红，且回显原因可归因。
    reason = expect(_blocked_outcome(["policy_denied", "reason=quiet_hours_night"]))
    assert "quiet_hours_night" in reason, reason


def test_command_gate_expect_poison_audit_reader_blind_is_red() -> None:
    """注毒②：审计读口形变（None）＝判红——量具坏了不许读成「被测件清白」。"""
    expect = e2e.expect_command_after_group_gate(lambda _o: "")
    blind = _blocked_outcome(None)
    assert "读口形变" in expect(blind)
    # 注毒③：state/transport 不是 blocked/policy（例如被静默成 skipped）＝红。
    assert expect(_blocked_outcome(["command_group_unlisted"], transport="runtime"))
    assert expect(
        e2e.ItemOutcome(
            item=_dummy_item(),
            request_id="poison-2",
            receipt=DeliveryReceipt(
                request_id="poison-2", state=ReceiptState.SKIPPED, transport="policy"
            ),
            audit_reasons=["command_group_unlisted"],
        )
    )
    # 白名单2 那枚门名同样算「按设计拦」（同一条裁定的两格）。
    assert (
        expect(_blocked_outcome(["policy_denied", "group_white2_need_trigger"])) == ""
    )


def test_identity_dry_run_redirects_the_writable_store(tmp_path, monkeypatch) -> None:
    """DRY-RUN 的 set-name 必须把可写的称谓库改指临时根；--execute 保持真实库。

    这一条锁的是硬红线：验收脚本在「只验形状不发」的模式下绝不写她的生产偏好库。
    手法＝换掉能力体内的 ``build_identity_preference_result``，只记它收到的 config，
    零建库、零落盘（连临时库都不开），把「哪一本库被交出去」这一件事问清楚。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

    seen: list[object] = []

    def _spy(config: object, **_kwargs: object) -> SimpleNamespace:
        seen.append(config)
        return SimpleNamespace(body="spy", kind="text", request_id="x")

    monkeypatch.setattr(echo, "build_identity_preference_result", _spy)

    dry = _runtime_stub(tmp_path)
    assert dry.execute is False
    dry_capability = next(
        item for item in e2e.build_matrix(dry) if item.key == "identity-set-name"
    ).build(dry)
    message = e2e.synthesize_message(
        text="/bot identity set-name 岸友",
        session_type=SessionType.GROUP,
        target_id="555",
        sender_id="10000",
        bot_id="",
        seq=1,
    )
    dry_capability(message, None)
    staged = seen[-1]
    staged_path = str(getattr(staged, "bot_addressing_preferences_db_path", ""))
    assert "e2e-identity-dryrun" in staged_path.replace("\\", "/"), staged_path
    assert staged_path.startswith(str(Path(tempfile.gettempdir())))
    assert staged_path != str(
        getattr(dry.config, "bot_addressing_preferences_db_path", "")
    ), "DRY-RUN 没改指临时库＝会写真实库"

    live = _runtime_stub(tmp_path)
    live.execute = True
    live_capability = next(
        item for item in e2e.build_matrix(live) if item.key == "identity-set-name"
    ).build(live)
    live_capability(message, None)
    assert seen[-1] is live.config, "--execute 必须落真实库（真机验收的那一面）"


def test_harness_group_list_gap_is_declared_not_silently_blessed() -> None:
    """已知失真必须带字在盘上：本脚本没把群名单输入接给管线（生产接了）。

    现算证据：``--target-group`` 跑一枚确在 BOT_GROUP_WHITE1 的群，安全阀会打印
    「群 … 在 BOT_GROUP_WHITE1」，而同一轮群侧命令仍被 ``command_group_unlisted`` 拦。
    所以「按设计被拦」那一轨验的是**门禁形状**，不是「这群真的不在册」。
    这条用例是绊线：谁把五枚名单输入补进 ``build_pipeline``（＝改门禁输入，另一桩裁定），
    它就当场红，逼那次改动同步复核这四枚的期望轨，而不是让 PASS 悄悄换含义。
    """
    source = Path(e2e.__file__).read_text(encoding="utf-8")
    start = source.index("def build_pipeline(")
    block = source[start : source.index("def choose_send_queue(")]
    unwired = [
        name
        for name in (
            "group_lists_provider",
            "group_white1",
            "group_white2",
            "group_black1",
            "group_black2",
        )
        if name in block
    ]
    declared = "任何群都算未在册" in source
    if unwired:
        assert not declared, (
            f"build_pipeline 已接进群名单输入 {unwired}，脚本却仍自陈「验收面里任何群"
            "都算未在册」＝那段话在撒谎；补接线属改门禁输入，同批复核这四枚的期望轨"
            "（正跑面会露出 move_private 那格红）"
        )
    else:
        assert declared, (
            "群侧命令的「按设计被拦」这一轨依赖那条自陈（本脚本没把名单接给管线）；"
            "自陈没了＝PASS 的含义静默漂移，必须补回或改判据"
        )
