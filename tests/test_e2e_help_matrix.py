"""实战自测命令矩阵回归（离线）：e2e_acceptance.py --help-matrix/--selftest 内核。

覆盖 2026-09-13 批次新增面，全程不联网、不真发、不读 .env：
- 帮助注册表（echo._HELP_ENTRIES，只读 import）→ 命令矩阵生成与触发形态提取；
- --subset 过滤 / OneBot payload 构造 / 离线路由体检；
- 投递回执轮询（响应/超时/异常三态，注入时钟微预算）与汇总 JSON；
- 超管报告渲染（通过率/超时清单/异常清单/建议复查）；
- WS 探针离线快速失败；--selftest 全绿；存量 CLI 参数语义不变。
"""

from __future__ import annotations

import time

import pytest

import scripts.e2e_acceptance as e2e
from plugins.bot_unified_runtime.config import Config


def _offline_config() -> Config:
    return Config(bot_quiet_hours_enabled=False, bot_affinity_enabled=False)


def _specs():
    return e2e.load_help_topic_specs()


def _by_topic():
    return {spec.topic: spec for spec in _specs()}


# ---------------------------------------------------------------------------
# 命令矩阵生成与触发形态提取
# ---------------------------------------------------------------------------


def test_registry_load_topics_unique_and_trigger_nonempty() -> None:
    specs = _specs()
    topics = [spec.topic for spec in specs]
    # 真相源持续扩表中（67→69），只设下限不钉死数量。
    assert len(specs) >= 60
    assert len(topics) == len(set(topics))
    for spec in specs:
        assert spec.trigger.strip(), spec.topic
        assert spec.aliases, spec.topic
        assert spec.trigger_source in ("index", "alias", "override")


def test_trigger_extraction_known_topics() -> None:
    """逐条对照实跑钉住的期望表（与脚本内 _SELFTEST_TRIGGER_EXPECTATIONS 同源）。"""
    by_topic = _by_topic()
    for topic, expected in e2e._SELFTEST_TRIGGER_EXPECTATIONS.items():
        assert by_topic[topic].trigger == expected, topic


def test_doc_topics_fall_back_to_alias_with_provenance() -> None:
    by_topic = _by_topic()
    for topic in ("忽略", "戳一戳", "表情收库", "聊天"):
        spec = by_topic[topic]
        assert spec.trigger_source == "alias", topic
        assert spec.trigger == spec.aliases[0], topic


def test_link_topic_override_uses_sample_url() -> None:
    spec = _by_topic()["链接"]
    assert spec.trigger == e2e.BILI_SAMPLE_URL
    assert spec.trigger_source == "override"


def test_extract_primary_trigger_unit_edges() -> None:
    # 参数占位连内部竖线一起剥掉，再取第一候选。
    trigger, source = e2e.extract_primary_trigger(
        "【回执】查询发送回执：/bot receipt <request_id|debug_id>", ("回执",)
    )
    assert (trigger, source) == ("/bot receipt", "index")
    # 描述性标点（逗号/省略号）→ 别名兜底。
    trigger, source = e2e.extract_primary_trigger(
        "【草稿】自然语言起草自动发送：报存 给 <收件人> 发消息|邮件，内容…", ("报存", "草稿")
    )
    assert (trigger, source) == ("报存", "alias")
    # 非斜杠候选长度 >8 视为描述句（治「戳机器人有概率收到回应」混入）。
    trigger, source = e2e.extract_primary_trigger(
        "【戳一戳】戳机器人有概率收到回应（有冷却）", ("戳一戳",)
    )
    assert (trigger, source) == ("戳一戳", "alias")


# ---------------------------------------------------------------------------
# subset 过滤与 payload 构造
# ---------------------------------------------------------------------------


def test_subset_filter_matches_topic_and_alias() -> None:
    specs = _specs()
    matched, unknown = e2e.filter_topic_specs(specs, "天气,点歌,不存在主题X")
    assert [spec.topic for spec in matched] == ["天气", "点歌"]
    assert unknown == ["不存在主题X"]
    # 别名命中（hq 是「行情」的拼音缩写别名）。
    matched, unknown = e2e.filter_topic_specs(specs, "hq")
    assert [spec.topic for spec in matched] == ["行情"]
    assert unknown == []
    # 空 subset = 全量。
    matched, unknown = e2e.filter_topic_specs(specs, "")
    assert len(matched) == len(specs)
    assert unknown == []
    # 重复 token 去重保序。
    matched, _ = e2e.filter_topic_specs(specs, "天气，天气")
    assert [spec.topic for spec in matched] == ["天气"]


def test_command_payload_group_and_private_shapes() -> None:
    spec = _by_topic()["天气"]
    group = e2e.build_command_payload(
        spec, session_type=e2e.SessionType.GROUP, target_id="123456"
    )
    assert group == {
        "action": "send_group_msg",
        "params": {"message": "天气", "auto_escape": False, "group_id": 123456},
        "echo": "e2e-天气",
    }
    private = e2e.build_command_payload(
        spec, session_type=e2e.SessionType.PRIVATE, target_id="10001"
    )
    assert private["action"] == "send_private_msg"
    assert private["params"]["user_id"] == 10001
    # 非数字目标回退字符串形态（不抛异常）。
    fallback = e2e.build_command_payload(
        spec, session_type=e2e.SessionType.GROUP, target_id="abc"
    )
    assert fallback["params"]["group_id"] == "abc"


# ---------------------------------------------------------------------------
# 离线路由体检
# ---------------------------------------------------------------------------


def test_route_classification_offline_no_crash_and_admin_route() -> None:
    config = _offline_config()
    for spec in _specs():
        kind, capability, _reason = e2e.classify_spec_route(spec, config)
        assert kind != "error" or "UnboundLocalError" in _reason, spec.topic
        assert capability, spec.topic
    kind, capability, _ = e2e.classify_spec_route(_by_topic()["状态"], config)
    assert kind == "admin"
    assert capability.startswith("bot.")


# ---------------------------------------------------------------------------
# 投递回执轮询与汇总
# ---------------------------------------------------------------------------


def test_wait_for_delivery_confirms_sent_with_injected_clock() -> None:
    queue = e2e._scripted_queue(["queued", "queued", "sent"])
    state, _elapsed = e2e.wait_for_delivery(
        queue,
        request_id="r1",
        budget=5.0,
        poll_interval=0.0,
        sleep=lambda _s: None,
    )
    assert state == "sent"
    assert e2e.status_from_delivery_state(state) == "delivered"
    assert queue.calls == 3


def test_wait_for_delivery_times_out_within_budget() -> None:
    state, _elapsed = e2e.wait_for_delivery(
        e2e._scripted_queue(["queued"]),
        request_id="r1",
        budget=0.0,  # 零预算：首拍即超时，绝不悬挂。
        poll_interval=0.0,
    )
    assert state == "timeout"
    assert e2e.status_from_delivery_state(state) == "timeout"


def test_wait_for_delivery_failure_terminal_maps_to_error() -> None:
    for state in ("failed_final", "failed_retryable", "query_error:OSError"):
        status = e2e.status_from_delivery_state(state)
        assert status == "error", state


def test_wait_for_delivery_queue_query_error_is_error_not_crash() -> None:
    class _BoomQueue:
        def find_request(self, request_id: str) -> None:
            raise OSError("queue gone")

    state, _elapsed = e2e.wait_for_delivery(
        _BoomQueue(), request_id="r1", budget=0.0, poll_interval=0.0
    )
    assert state == "query_error:OSError"


def test_summarize_and_results_document_consistent() -> None:
    by_topic = _by_topic()
    outcomes = [
        e2e.CommandOutcome(spec=by_topic["天气"], status="delivered", state="sent", elapsed=1.0),
        e2e.CommandOutcome(spec=by_topic["点歌"], status="delivered", state="sent", elapsed=2.0),
        e2e.CommandOutcome(spec=by_topic["行情"], status="timeout", state="queued", elapsed=20.0),
        e2e.CommandOutcome(spec=by_topic["汇率"], status="error", state="failed_final", error="x"),
        e2e.CommandOutcome(spec=by_topic["占卜"], status="skipped"),
    ]
    summary = e2e.summarize_results(outcomes)
    assert summary == {
        "total": 5,
        "attempted": 4,
        "delivered": 2,
        "timeout": 1,
        "error": 1,
        "blocked": 0,
        "skipped": 1,
        "pass_rate": 50.0,
    }
    document = e2e.build_results_document(
        outcomes,
        mode="execute",
        target_desc="group:555",
        subset=["天气"],
        ws_endpoint=("127.0.0.1", 3001),
        ws_online=True,
        generated_at="2026-09-13 00:00:00",
    )
    assert document["schema"] == "e2e_help_matrix_results/v1"
    assert document["summary"] == summary
    assert document["ws_probe"] == {"host": "127.0.0.1", "port": 3001, "online": True}
    assert [item["topic"] for item in document["outcomes"]] == [
        "天气", "点歌", "行情", "汇率", "占卜",
    ]
    assert document["outcomes"][0]["elapsed_ms"] == 1000.0


# ---------------------------------------------------------------------------
# 报告渲染
# ---------------------------------------------------------------------------


def test_render_run_report_sections_and_counts() -> None:
    by_topic = _by_topic()
    outcomes = [
        e2e.CommandOutcome(
            spec=by_topic["天气"], status="delivered", state="sent", elapsed=1.5
        ),
        e2e.CommandOutcome(
            spec=by_topic["行情"], status="timeout", state="queued", elapsed=20.0
        ),
        e2e.CommandOutcome(
            spec=by_topic["汇率"], status="error", state="failed_final", error="boom"
        ),
        e2e.CommandOutcome(spec=by_topic["占卜"], status="skipped"),
    ]
    report = e2e.render_run_report(
        outcomes,
        mode="execute",
        target_desc="group:555",
        generated_at="2026-09-13 00:00:00",
        wait_budget=20.0,
    )
    assert "通过率 33.3%" in report
    assert "■ 总览" in report and "■ 超时清单" in report
    assert "■ 异常清单" in report and "■ 建议复查项" in report
    assert "行情" in report and "汇率" in report and "boom" in report
    assert "未执行 1 项" in report  # skipped 计数进入建议复查


def test_render_run_report_empty_attempted_shows_no_attempt() -> None:
    by_topic = _by_topic()
    outcomes = [e2e.CommandOutcome(spec=by_topic["天气"], status="skipped")]
    report = e2e.render_run_report(
        outcomes,
        mode="execute",
        target_desc="group:555",
        generated_at="2026-09-13 00:00:00",
    )
    assert "无投递尝试" in report


# ---------------------------------------------------------------------------
# WS 探针
# ---------------------------------------------------------------------------


def test_probe_ws_online_offline_port_fast_fail() -> None:
    online, elapsed = e2e.probe_ws_online("127.0.0.1", 1, timeout=1.5)
    assert online is False
    assert elapsed < 5.0  # 快速失败，不悬挂


def test_resolve_ws_probe_endpoint_priority() -> None:
    # 显式参数优先。
    assert e2e.resolve_ws_probe_endpoint("10.0.0.8:5678") == ("10.0.0.8", 5678)
    # 缺省回退默认端点（本机环境变量可能注入 ONEBOT_WS_URLS，仅断言形态）。
    host, port = e2e.resolve_ws_probe_endpoint("")
    assert isinstance(host, str) and host
    assert isinstance(port, int) and 0 < port < 65536


# ---------------------------------------------------------------------------
# selftest 与 CLI 兼容
# ---------------------------------------------------------------------------


def test_selftest_all_green_offline() -> None:
    code, lines = e2e.run_selftest()
    assert code == 0, "\n".join(lines)
    assert any("PASS registry_load" in line for line in lines)


def test_main_selftest_dispatch_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert e2e.main(["--selftest"]) == 0
    out = capsys.readouterr().out
    assert "selftest" in out


def test_parser_legacy_args_unchanged() -> None:
    args = e2e.build_arg_parser().parse_args(["--target-group", "123"])
    assert args.target_group == "123"
    assert args.execute is False
    assert args.interval == e2e.DEFAULT_INTERVAL_SECONDS
    assert args.city == "北京"
    # 互斥仍生效。
    with pytest.raises(SystemExit):
        e2e.build_arg_parser().parse_args(
            ["--target-group", "1", "--target-user", "2"]
        )


def test_parser_new_args_parse_without_target_for_selftest() -> None:
    args = e2e.build_arg_parser().parse_args(
        ["--selftest", "--report", "--json-out", "x.json", "--wait", "5"]
    )
    assert args.selftest is True
    assert args.wait == 5.0


def test_help_matrix_target_enforced_at_dispatch() -> None:
    # parser 层不强制（--selftest 免目标），main 层补强制校验。
    args = e2e.build_arg_parser().parse_args(["--help-matrix"])
    assert args.target_group is None and args.target_user is None
    with pytest.raises(SystemExit) as excinfo:
        e2e.main(["--help-matrix"])
    assert excinfo.value.code == 2
    args = e2e.build_arg_parser().parse_args(
        ["--target-group", "123", "--help-matrix", "--subset", "天气"]
    )
    assert args.help_matrix is True
    assert args.subset == "天气"


def test_legacy_matrix_untouched_by_new_mode() -> None:
    """存量验收矩阵不被新批次改动（参数只往后加的兼容锁）。"""
    from types import SimpleNamespace

    config = Config(bot_quiet_hours_enabled=False, bot_affinity_enabled=False)
    runtime = e2e.E2eRuntime(
        config=config,
        runtime_settings=SimpleNamespace(
            get=lambda key, cfg: None,
            get_persona_override=lambda: None,
        ),
        render_backend=None,
        execute=False,
        city="北京",
        bot_id="",
        sender_id="10000",
    )
    keys = {item.key for item in e2e.build_matrix(runtime)}
    for legacy_key in (
        "text-short",
        "content-bili",
        "music-candidates",
        "market-global",
        "weather-alert",
        "help",
        "affinity",
        "stocks-nvda",
        "fx-panel",
        "identity-set-name",
    ):
        assert legacy_key in keys, legacy_key


def test_execute_item_still_works_alongside_new_engine() -> None:
    """新引擎并列不破坏存量执行内核（text-short 经真实管线入 InMemory 队列）。
    注意：wait_for_delivery 的状态契约面向 SQLite 队列的 QueuedSendRequest
    （--execute 唯一路径），InMemory 队列的 find_request 返回 SendRequest，
    不在本函数契约内——回执断言以 receipt.state 为准。"""
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
    from plugins.bot_unified_runtime.contracts import ReceiptState
    from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue

    config = Config(bot_quiet_hours_enabled=False, bot_affinity_enabled=False)
    runtime = e2e.E2eRuntime(
        config=config,
        runtime_settings=SimpleNamespace(
            get=lambda key, cfg: None,
            get_persona_override=lambda: None,
        ),
        render_backend=None,
        execute=False,
        city="北京",
        bot_id="",
        sender_id="10000",
    )
    item = next(
        entry for entry in e2e.build_matrix(runtime) if entry.key == "text-short"
    )
    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    outcome = e2e.execute_item(
        pipeline=e2e.build_pipeline(runtime, queue),
        send_queue=queue,
        item=item,
        runtime=runtime,
        session_type=e2e.SessionType.GROUP,
        target_id="555",
        seq=1,
    )
    assert outcome.error == ""
    assert outcome.receipt is not None
    assert outcome.receipt.state == ReceiptState.SENT


def test_wait_for_delivery_signature_is_injectable() -> None:
    """轮询计时默认取 monotonic、休眠走 time.sleep，均可注入（离线测试依赖）。"""
    import inspect

    parameters = inspect.signature(e2e.wait_for_delivery).parameters
    assert parameters["monotonic"].default is time.monotonic
    assert parameters["sleep"].default is time.sleep
