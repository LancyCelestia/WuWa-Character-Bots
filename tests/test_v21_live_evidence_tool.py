"""v21r4-B LIVE-TOOL：live 取证采集脚本离线回归（TDD）。

被测对象：``scripts/collect_v21r4_live_evidence.py``（纯 stdlib 采集器，
只读日志、不发请求、不写 Runtime）。

fixture 日志行一律按**真身代码实测格式串**构造（禁臆造），坐标见
``docs/design/v21r4-b-LIVE-TOOL-log.md`` 开工快照表：
- served_by：domains/chat_reply/capabilities/chat.py:2003-2008
- 逐跳失败：domains/chat_reply/llm_engine/model_router.py:2204-2236
- chain 压缩：domains/ops/monitor/alerts.py:326；safe_summary：chat.py:2495-2497
- 冷却降级：model_router.py:1982-1986（缺省 90s=channel_health.py:41）
- grok 回落：model_router.py:1998-2004
- 时段切换：domains/chat_reply/llm_engine/model_schedule.py:114-129
- 告警折叠：alerts.py:332-362（llm_kinds=[a|b] 随行）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import collect_v21r4_live_evidence as tool

# ---------------------------------------------------------------------------
# fixture 构造（按真身格式串逐字拼装）
# ---------------------------------------------------------------------------

PFX_INFO = "09-18 10:00:00 [INFO] bot_unified_runtime.domains | "
PFX_WARN = "09-18 10:00:00 [WARNING] bot_unified_runtime.domains | "


def _served_by_line(
    mode: str = "normal",
    served_by: str = "axon-gemini",
    attempts: str = "['axon-gemini:success']",
    ts: str = "09-18 10:00:00",
) -> str:
    return (
        f"{ts} [INFO] bot_unified_runtime.domains.chat_reply.capabilities.chat | "
        f"content_route: has_session=True mode={mode} tag=- served_by={served_by} "
        f"refusal_boilerplate=False attempts={attempts}"
    )


def _hop_failed_line(
    model: str = "axon-grok",
    family: str = "grok",
    kind: str = "timeout",
    elapsed_ms: int = 20123,
    timeout: str | None = "20",
    intimate: str = "False",
    ts: str = "09-18 10:00:00",
) -> str:
    body = (
        f"llm route hop failed model={model} family={family} kind={kind} "
        f"elapsed_ms={elapsed_ms}"
    )
    if timeout is not None:
        body += f" timeout={timeout} intimate={intimate}"
    else:
        body += f" intimate={intimate}"
    return f"{ts} [WARNING] bot_unified_runtime.domains.chat_reply.llm_engine | {body}"


# ---------------------------------------------------------------------------
# 1. served_by 轨迹
# ---------------------------------------------------------------------------


def test_served_by_trace_parsed_and_counted() -> None:
    text = "\n".join(
        [
            _served_by_line(
                mode="intimate",
                served_by="aiprc-grok",
                attempts="['axon-grok:timeout', 'aiprc-grok:success']",
            ),
            _served_by_line(served_by="axon-gemini"),
            "garbage line without markers",
        ]
    )
    report = tool.collect(text.splitlines())
    section = report["served_by"]
    assert section["total"] == 2
    assert section["by_served_by"] == {"aiprc-grok": 1, "axon-gemini": 1}
    assert section["intimate_total"] == 1
    sample = section["samples"][0]
    assert sample["mode"] == "intimate"
    assert sample["served_by"] == "aiprc-grok"
    assert sample["attempts"] == ["axon-grok:timeout", "aiprc-grok:success"]


# ---------------------------------------------------------------------------
# 2. 逐跳失败（两种变体 + 序列分组）
# ---------------------------------------------------------------------------


def test_hop_failed_primary_variant_with_timeout_field() -> None:
    report = tool.collect([_hop_failed_line()])
    section = report["hop_failures"]
    assert section["total"] == 1
    assert section["by_kind"] == {"timeout": 1}
    assert section["by_model"] == {"axon-grok": 1}
    assert section["by_family"] == {"grok": 1}
    event = section["events"][0]
    assert event["elapsed_ms"] == 20123
    assert event["timeout"] == "20"
    assert event["intimate"] == "False"


def test_hop_failed_provider_error_variant_without_timeout() -> None:
    line = _hop_failed_line(
        model="qian-gemini",
        family="gemini",
        kind="provider_error",
        elapsed_ms=55,
        timeout=None,
    )
    report = tool.collect([line])
    event = report["hop_failures"]["events"][0]
    assert event["kind"] == "provider_error"
    assert event["timeout"] is None
    assert event["elapsed_ms"] == 55


def test_hop_failed_sequences_grouped_by_time_gap() -> None:
    lines = [
        _hop_failed_line(model="a", ts="09-18 10:00:00"),
        _hop_failed_line(model="b", ts="09-18 10:02:00"),
        _hop_failed_line(model="c", ts="09-18 10:20:00"),
    ]
    report = tool.collect(lines)
    section = report["hop_failures"]
    assert [len(seq) for seq in section["sequences"]] == [2, 1]
    assert section["max_sequence_len"] == 2


# ---------------------------------------------------------------------------
# 3. chain 长度分布
# ---------------------------------------------------------------------------


def test_chain_histogram_from_alert_compressed_and_safe_summary() -> None:
    lines = [
        (
            "[运行时告警] stage=llm kind=network detail=chain=17跳全败 last=umi-x "
            "retryable=true attempts=17 debug_id=d1 source_adapter=onebot "
            "source_bot=qq session_type=private suppressed_count=0"
        ),
        PFX_WARN
        + "capability failed stage=llm detail=timeout chain=3 last=aiprc-gemini",
    ]
    report = tool.collect(lines)
    section = report["chain_length"]
    assert section["histogram"] == {"17": 1, "3": 1}
    assert section["from_folded_alert"] == 1
    assert section["from_safe_summary"] == 1
    assert section["max"] == 17


# ---------------------------------------------------------------------------
# 4. 90s 冷却降级事件
# ---------------------------------------------------------------------------


def test_cooldown_demote_counted_per_channel() -> None:
    line = (
        PFX_INFO
        + "llm route cooldown demote count=2 ids=aiprc-grok,qian-night-grok"
    )
    report = tool.collect([line])
    section = report["cooldown_demote"]
    assert section["events"] == 1
    assert section["channels_demoted_total"] == 2
    assert section["by_channel"] == {"aiprc-grok": 1, "qian-night-grok": 1}


# ---------------------------------------------------------------------------
# 5. INTIMATE grok 命中 / 回落
# ---------------------------------------------------------------------------


def test_intimate_grok_fallback_and_hit() -> None:
    lines = [
        (
            "09-18 23:10:00 [WARNING] x | llm intimate grok fallback: grok 熔断冷却/"
            "不可用中，临时回落 head=aiprc-gemini demoted=axon-grok health_filtered=-"
        ),
        _served_by_line(mode="intimate", served_by="aiprc-grok"),
        _served_by_line(mode="normal", served_by="axon-gemini"),
    ]
    report = tool.collect(lines)
    section = report["intimate_grok"]
    assert section["fallback_events"] == 1
    assert section["fallbacks"][0]["head"] == "aiprc-gemini"
    assert section["fallbacks"][0]["demoted"] == "axon-grok"
    assert section["intimate_total"] == 1  # 一条 content_route mode=intimate
    assert section["intimate_served_grok_hits"] == 1


# ---------------------------------------------------------------------------
# 6. 严格优先级违例探针
# ---------------------------------------------------------------------------


def test_strict_priority_violation_detected() -> None:
    order = ["axon-grok", "aiprc-grok", "aiprc-gemini"]
    traces = [
        ["aiprc-gemini:success"],  # 两高优渠道全程未试 → 违例
        ["axon-grok:timeout", "aiprc-grok:success"],  # 高优试过 → 不违例
    ]
    violations = tool.strict_priority_violations(traces, order)
    assert len(violations) == 1
    assert violations[0]["first_tried"] == "aiprc-gemini"
    assert violations[0]["skipped_higher"] == ["axon-grok", "aiprc-grok"]


def test_strict_priority_probe_skipped_without_expected_order() -> None:
    report = tool.collect([_served_by_line(served_by="aiprc-gemini")])
    section = report["strict_priority"]
    assert section["probe"] == "skipped"
    assert section["violations"] == 0


def test_strict_priority_probe_runs_with_expected_order() -> None:
    text = _served_by_line(
        served_by="aiprc-gemini", attempts="['aiprc-gemini:success']"
    )
    report = tool.collect(
        text.splitlines(),
        expected_order=["axon-grok", "aiprc-gemini"],
    )
    section = report["strict_priority"]
    assert section["probe"] == "ran"
    assert section["violations"] == 1


# ---------------------------------------------------------------------------
# 7. 时段切换命中
# ---------------------------------------------------------------------------


def test_schedule_switched_and_cleared_counted() -> None:
    lines = [
        PFX_INFO + "model schedule switched override=luna window active",
        "09-18 23:30:00 [INFO] x | model schedule switched override=luna window active",
        PFX_INFO + "model schedule cleared override (outside windows)",
        PFX_INFO + "model schedule cleared override (schedule emptied)",
    ]
    report = tool.collect(lines)
    section = report["schedule_windows"]
    assert section["switched"] == 2
    assert section["by_target"] == {"luna": 2}
    assert section["cleared_outside_windows"] == 1
    assert section["cleared_schedule_emptied"] == 1
    # 诚实注记：BOT_MODEL_PRIORITY_GROUPS 命中无独立日志行。
    assert "BOT_MODEL_PRIORITY_GROUPS" in section["priority_group_note"]


# ---------------------------------------------------------------------------
# 8. axonhub 20s 掐断对照候选
# ---------------------------------------------------------------------------


def test_axonhub_timeout_band_candidates() -> None:
    lines = [
        _hop_failed_line(kind="timeout", elapsed_ms=20123),  # 带内
        _hop_failed_line(model="b", kind="timeout", elapsed_ms=9000),  # 带外
        _hop_failed_line(model="c", kind="network", elapsed_ms=20000),  # 非 timeout
    ]
    report = tool.collect(lines)
    section = report["axonhub_timeout_band"]
    assert section["candidates"] == 1
    assert section["by_model"] == {"axon-grok": 1}


def test_axonhub_timeout_band_custom_bounds() -> None:
    lines = [_hop_failed_line(kind="timeout", elapsed_ms=9000)]
    report = tool.collect(lines, timeout_band=(8000, 10000))
    assert report["axonhub_timeout_band"]["candidates"] == 1


# ---------------------------------------------------------------------------
# 9. 告警折叠
# ---------------------------------------------------------------------------


def test_alert_fold_kinds_and_suppressed_counted() -> None:
    line = (
        "[运行时告警] stage=llm kind=network detail=chain=4跳全败 last=aiprc-gemini "
        "retryable=true attempts=4 debug_id=d2 source_adapter=onebot source_bot=qq "
        "session_type=private suppressed_count=2 llm_kinds=[network|timeout]"
    )
    report = tool.collect([line])
    section = report["alert_fold"]
    assert section["llm_alert_lines"] == 1
    assert section["folded_kind_lists"] == 1
    assert section["kinds_seen"] == {"network": 1, "timeout": 1}
    assert section["suppressed_total"] == 2


# ---------------------------------------------------------------------------
# fail-open：空日志 / 乱格式 不抛异常
# ---------------------------------------------------------------------------


def test_empty_log_yields_zero_report_without_exception() -> None:
    report = tool.collect([])
    assert report["served_by"]["total"] == 0
    assert report["hop_failures"]["total"] == 0
    assert report["chain_length"]["histogram"] == {}
    assert report["cooldown_demote"]["events"] == 0
    assert report["intimate_grok"]["fallback_events"] == 0
    assert report["schedule_windows"]["switched"] == 0
    assert report["axonhub_timeout_band"]["candidates"] == 0
    assert report["alert_fold"]["llm_alert_lines"] == 0
    assert json.dumps(report, ensure_ascii=False)  # 可 JSON 化


def test_garbage_lines_fail_open() -> None:
    garbage = [
        "",
        "",
        "not a log line at all",
        "content_route: has_session=",
        "llm route hop failed model=only-model",
        "chain=跳全败",
        "llm_kinds=[",
    ]
    report = tool.collect(garbage)
    assert report["served_by"]["total"] == 0
    assert report["hop_failures"]["total"] == 0
    assert report["chain_length"]["histogram"] == {}


# ---------------------------------------------------------------------------
# CLI 端到端（临时文件，只读打开；--json 可解析；末尾提示语）
# ---------------------------------------------------------------------------


def _write_log(tmp_path: Path, lines: list[str]) -> Path:
    log = tmp_path / "nonebot.out.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


def test_cli_human_report_and_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = _write_log(tmp_path, [_served_by_line(served_by="axon-gemini")])
    rc = tool.main(["--log", str(log)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "served_by" in out
    assert "live 证据需重启后真实对话产生，本工具只做采集统计" in out


def test_cli_json_output_parseable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = _write_log(
        tmp_path,
        [_hop_failed_line(kind="timeout", elapsed_ms=20123)],
    )
    rc = tool.main(["--log", str(log), "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["hop_failures"]["total"] == 1
    # JSON 模式下提示语走 stderr，不污染 stdout JSON。
    assert "live 证据需重启后真实对话产生" in captured.err


def test_cli_missing_default_paths_fail_open(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_dir = tmp_path / "logs"
    empty_dir.mkdir()
    monkeypatch.setattr(tool, "_default_log_paths", lambda: [empty_dir])
    rc = tool.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "live 证据需重启后真实对话产生，本工具只做采集统计" in out


def test_collect_from_file_read_only(tmp_path: Path) -> None:
    log = _write_log(
        tmp_path,
        [
            _served_by_line(served_by="axon-gemini"),
            _hop_failed_line(kind="timeout", elapsed_ms=20123),
        ],
    )
    before = log.read_text(encoding="utf-8")
    report = tool.collect_from_file(log)
    assert log.read_text(encoding="utf-8") == before  # 只读：字节不变
    assert report["served_by"]["total"] == 1
    assert report["hop_failures"]["total"] == 1
