#!/usr/bin/env python
"""v21r4-B live 取证采集器（LIVE-TOOL 席）。

只读扫描 NoneBot 日志，按真身代码实测格式串统计 LEDGER-b memo §四 的九项
LLM live 证据（served_by 轨迹 / 逐跳失败 / chain 长度分布 / 90s 冷却降级 /
INTIMATE grok 命中与回落 / 严格优先级违例探针 / 时段切换命中 / axonhub 20s
掐断对照候选 / 告警折叠）。纯 stdlib、只读、不发请求、不写 Runtime。

诚实红线：本工具是采集器，不是生效证明——live 证据需重启后真实对话产生。
格式串证据坐标见 docs/design/v21r4-b-LIVE-TOOL-log.md 开工快照表。
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = REPO_ROOT.parent / "ChatBot_Runtime" / "logs"

HINT_TEXT = "live 证据需重启后真实对话产生，本工具只做采集统计"

DEFAULT_TIMEOUT_BAND = (18000, 25000)
DEFAULT_SEQUENCE_GAP_SECONDS = 300.0
DEFAULT_SAMPLE_SIZE = 20

# --- 真身日志格式串（逐字取证，禁臆造；坐标见席位日志快照表） ---

CONTENT_ROUTE_RE = re.compile(
    r"content_route:\s*has_session=(?P<has_session>\S+)\s+mode=(?P<mode>\S+)\s+"
    r"tag=(?P<tag>\S+)\s+served_by=(?P<served_by>\S+)\s+"
    r"refusal_boilerplate=(?P<refusal>\S+)\s+attempts=(?P<attempts>.+)$"
)
HOP_FAILED_RE = re.compile(
    r"llm route hop failed model=(?P<model>\S+)\s+family=(?P<family>\S+)\s+"
    r"kind=(?P<kind>\S+)\s+elapsed_ms=(?P<elapsed>\d+)"
    r"(?:\s+timeout=(?P<timeout>\S+))?(?:\s+intimate=(?P<intimate>\S+))?"
)
CHAIN_FOLDED_RE = re.compile(r"chain=(?P<hops>\d+)跳全败")
CHAIN_SUMMARY_RE = re.compile(r"chain=(?P<hops>\d+)\s+last=(?P<last>\S+)")
COOLDOWN_DEMOTE_RE = re.compile(
    r"llm route cooldown demote count=(?P<count>\d+)\s+ids=(?P<ids>.*)$"
)
GROK_FALLBACK_RE = re.compile(
    r"llm intimate grok fallback.*?head=(?P<head>\S+)\s+"
    r"demoted=(?P<demoted>\S+)\s+health_filtered=(?P<health>\S+)"
)
SCHEDULE_SWITCHED_RE = re.compile(
    r"model schedule switched override=(?P<target>\S+)\s+window active"
)
SCHEDULE_CLEARED_RE = re.compile(
    r"model schedule cleared override \((?P<reason>outside windows|schedule emptied)\)"
)
ALERT_LINE_RE = re.compile(r"\[运行时告警\]\s*stage=(?P<stage>\S+)\s+kind=(?P<kind>\S+)")
ALERT_FOLD_KINDS_RE = re.compile(r"llm_kinds=\[(?P<kinds>[^\]]*)\]")
SUPPRESSED_COUNT_RE = re.compile(r"suppressed_count=(?P<n>\d+)")
TIME_PREFIX_RE = re.compile(r"^\d{2}-\d{2}\s+(\d{2}):(\d{2}):(\d{2})")
ATTEMPT_ITEM_RE = re.compile(r"'([^']*)'")


def _default_log_paths() -> list[Path]:
    """默认输入：ChatBot_Runtime/logs 下两份 nonebot 现行日志（存在才收）。"""
    candidates = [
        DEFAULT_LOG_DIR / "nonebot.out.log",
        DEFAULT_LOG_DIR / "nonebot.err.log",
    ]
    return [path for path in candidates if path.is_file()]


def parse_attempts(raw: str) -> list[str]:
    """解析 attempts=%s 载荷：list repr → 元素列表；解析失败逐项引号兜底。"""
    text = str(raw or "").strip()
    if not text or text == "[]":
        return []
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        items = ATTEMPT_ITEM_RE.findall(text)
        return items if items else [text]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def time_seconds_of(line: str) -> int | None:
    """NoneBot 前缀 ``MM-DD HH:MM:SS`` → 当日秒数；无前缀返回 None。"""
    match = TIME_PREFIX_RE.match(str(line or ""))
    if match is None:
        return None
    hour, minute, second = (int(part) for part in match.groups())
    return hour * 3600 + minute * 60 + second


def _channel_of(item: str) -> str:
    """attempts 载荷形如 ``渠道id:结果``；剥掉结果段（无冒号原样返回）。"""
    return item.rsplit(":", 1)[0] if ":" in item else item


def strict_priority_violations(
    traces: list[list[str]],
    expected_order: list[str],
) -> list[dict[str, Any]]:
    """严格优先级违例探针（v21r2 R1：bot_chat_strict_priority 缺省开）。

    轨迹元素兼容裸渠道 id 与 ``渠道id:结果`` 两种形态。违例定义（保守）：
    一条轨迹里首个被试渠道之前，存在期望序更靠前、且整条轨迹从未被试过的
    高优渠道——即跳过无失败证据。冷却降级/健康过滤的合法重排需结合 demote
    日志另行判读（结果里附 note）。
    """
    rank = {str(name): index for index, name in enumerate(expected_order)}
    violations: list[dict[str, Any]] = []
    for trace in traces:
        tried = [
            _channel_of(str(item))
            for item in trace
            if _channel_of(str(item)) in rank
        ]
        if not tried:
            continue
        first_index = rank[tried[0]]
        tried_set = set(tried)
        skipped = [
            name
            for name in expected_order[:first_index]
            if str(name) not in tried_set
        ]
        if skipped:
            violations.append(
                {
                    "trace": [str(item) for item in trace],
                    "first_tried": tried[0],
                    "skipped_higher": skipped,
                }
            )
    return violations


def _empty_report(inputs: list[str] | None = None) -> dict[str, Any]:
    return {
        "meta": {
            "tool": "collect_v21r4_live_evidence",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "lines_scanned": 0,
            "inputs": list(inputs or []),
            "note": HINT_TEXT,
        },
        "served_by": {
            "total": 0,
            "intimate_total": 0,
            "refusal_boilerplate_true": 0,
            "by_served_by": {},
            "samples": [],
        },
        "hop_failures": {
            "total": 0,
            "by_kind": {},
            "by_model": {},
            "by_family": {},
            "intimate_true": 0,
            "events": [],
            "sequences": [],
            "max_sequence_len": 0,
        },
        "chain_length": {
            "histogram": {},
            "from_folded_alert": 0,
            "from_safe_summary": 0,
            "max": 0,
        },
        "cooldown_demote": {
            "events": 0,
            "channels_demoted_total": 0,
            "by_channel": {},
        },
        "intimate_grok": {
            "fallback_events": 0,
            "fallbacks": [],
            "intimate_total": 0,
            "intimate_served_grok_hits": 0,
        },
        "strict_priority": {
            "probe": "skipped",
            "expected_order": None,
            "violations": 0,
            "details": [],
            "note": "未提供 --expected-order，探针跳过（fail-open 计 0）",
        },
        "schedule_windows": {
            "switched": 0,
            "by_target": {},
            "cleared_outside_windows": 0,
            "cleared_schedule_emptied": 0,
            "priority_group_note": (
                "BOT_MODEL_PRIORITY_GROUPS 分组命中在真身代码中无独立日志行，"
                "本工具无法从日志直接计数；分组真生效的日志侧证据 = served_by/"
                "attempts 顺序与分组 order 一致（可用 --expected-order 探针核对）"
            ),
        },
        "axonhub_timeout_band": {
            "low_ms": DEFAULT_TIMEOUT_BAND[0],
            "high_ms": DEFAULT_TIMEOUT_BAND[1],
            "candidates": 0,
            "by_model": {},
            "note": (
                "bot 侧 20s 读超时掐断候选（kind=timeout 且 elapsed_ms 落在带内），"
                "与 axonhub 控制台「已取消」记录需人工对照"
            ),
        },
        "alert_fold": {
            "llm_alert_lines": 0,
            "folded_kind_lists": 0,
            "kinds_seen": {},
            "suppressed_total": 0,
        },
    }


def collect(
    lines: Any,
    *,
    expected_order: list[str] | None = None,
    timeout_band: tuple[int, int] = DEFAULT_TIMEOUT_BAND,
    sequence_gap_seconds: float = DEFAULT_SEQUENCE_GAP_SECONDS,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    inputs: list[str] | None = None,
) -> dict[str, Any]:
    """扫描日志行列表（fail-open：单行解析失败静默跳过，绝不抛异常）。

    逐行按族独立匹配（不互斥continue）：告警文本一行内同时携带 chain=压缩、
    suppressed_count 与 llm_kinds 随行，各统计族都应计入。
    """
    report = _empty_report(inputs=inputs)
    served_by_events: list[dict[str, Any]] = []
    hop_events: list[dict[str, Any]] = []
    chain_histogram: Counter[str] = Counter()
    demote_by_channel: Counter[str] = Counter()
    fallbacks: list[dict[str, str]] = []
    schedule_by_target: Counter[str] = Counter()
    band_by_model: Counter[str] = Counter()
    kinds_seen: Counter[str] = Counter()
    counters = {
        "folded_alert": 0,
        "safe_summary": 0,
        "demote_events": 0,
        "demoted_total": 0,
        "cleared_outside": 0,
        "cleared_emptied": 0,
        "alert_llm_lines": 0,
        "folded_kind_lists": 0,
        "suppressed_total": 0,
    }
    low_ms, high_ms = int(timeout_band[0]), int(timeout_band[1])
    report["axonhub_timeout_band"]["low_ms"] = low_ms
    report["axonhub_timeout_band"]["high_ms"] = high_ms

    raw_lines = [str(line) for line in (lines or [])]
    report["meta"]["lines_scanned"] = len(raw_lines)

    for line in raw_lines:
        with contextlib.suppress(Exception):  # 单行解析失败静默跳过（fail-open）。
            match = CONTENT_ROUTE_RE.search(line)
            if match is not None:
                served_by_events.append(
                    {
                        "has_session": match.group("has_session"),
                        "mode": match.group("mode"),
                        "tag": match.group("tag"),
                        "served_by": match.group("served_by"),
                        "refusal_boilerplate": match.group("refusal"),
                        "attempts": parse_attempts(match.group("attempts")),
                    }
                )
            match = HOP_FAILED_RE.search(line)
            if match is not None:
                elapsed = int(match.group("elapsed"))
                hop_events.append(
                    {
                        "model": match.group("model"),
                        "family": match.group("family"),
                        "kind": match.group("kind"),
                        "elapsed_ms": elapsed,
                        "timeout": match.group("timeout"),
                        "intimate": match.group("intimate"),
                        "time_seconds": time_seconds_of(line),
                    }
                )
                if match.group("kind") == "timeout" and low_ms <= elapsed <= high_ms:
                    band_by_model[match.group("model")] += 1
            match = CHAIN_FOLDED_RE.search(line)
            if match is not None:
                chain_histogram[match.group("hops")] += 1
                counters["folded_alert"] += 1
            match = CHAIN_SUMMARY_RE.search(line)
            if match is not None:
                chain_histogram[match.group("hops")] += 1
                counters["safe_summary"] += 1
            match = COOLDOWN_DEMOTE_RE.search(line)
            if match is not None:
                counters["demote_events"] += 1
                counters["demoted_total"] += int(match.group("count"))
                demote_by_channel.update(
                    item.strip()
                    for item in match.group("ids").split(",")
                    if item.strip() and item.strip() != "-"
                )
            match = GROK_FALLBACK_RE.search(line)
            if match is not None:
                fallbacks.append(
                    {
                        "head": match.group("head"),
                        "demoted": match.group("demoted"),
                        "health_filtered": match.group("health"),
                    }
                )
            match = SCHEDULE_SWITCHED_RE.search(line)
            if match is not None:
                schedule_by_target[match.group("target")] += 1
            match = SCHEDULE_CLEARED_RE.search(line)
            if match is not None:
                if match.group("reason") == "outside windows":
                    counters["cleared_outside"] += 1
                else:
                    counters["cleared_emptied"] += 1
            if ALERT_LINE_RE.search(line) is not None:
                counters["alert_llm_lines"] += 1
                suppressed = SUPPRESSED_COUNT_RE.search(line)
                if suppressed is not None:
                    counters["suppressed_total"] += int(suppressed.group("n"))
            for kinds_match in ALERT_FOLD_KINDS_RE.finditer(line):
                kinds = [
                    item.strip()
                    for item in kinds_match.group("kinds").split("|")
                    if item.strip()
                ]
                if len(kinds) > 1:
                    counters["folded_kind_lists"] += 1
                    kinds_seen.update(kinds)

    # [1] served_by 汇总
    section = report["served_by"]
    section["total"] = len(served_by_events)
    section["intimate_total"] = sum(
        1 for event in served_by_events if event["mode"] == "intimate"
    )
    section["refusal_boilerplate_true"] = sum(
        1 for event in served_by_events if event["refusal_boilerplate"] == "True"
    )
    section["by_served_by"] = dict(
        Counter(event["served_by"] for event in served_by_events)
    )
    section["samples"] = served_by_events[: max(0, sample_size)]

    # [2] 逐跳失败汇总 + 时序分组（间隔≤gap 归同链）
    section = report["hop_failures"]
    section["total"] = len(hop_events)
    section["by_kind"] = dict(Counter(event["kind"] for event in hop_events))
    section["by_model"] = dict(Counter(event["model"] for event in hop_events))
    section["by_family"] = dict(Counter(event["family"] for event in hop_events))
    section["intimate_true"] = sum(
        1 for event in hop_events if event["intimate"] == "True"
    )
    section["events"] = hop_events[: max(0, sample_size)]
    sequences: list[list[dict[str, Any]]] = []
    for event in hop_events:
        previous = sequences[-1][-1] if sequences and sequences[-1] else None
        merge = False
        if previous is not None:
            previous_time = previous["time_seconds"]
            current_time = event["time_seconds"]
            if (
                previous_time is not None
                and current_time is not None
                and 0 <= current_time - previous_time <= sequence_gap_seconds
            ):
                merge = True
        if merge:
            sequences[-1].append(event)
        else:
            sequences.append([event])
    section["sequences"] = sequences
    section["max_sequence_len"] = max((len(seq) for seq in sequences), default=0)

    # [3] chain 直方
    histogram = {key: chain_histogram[key] for key in sorted(chain_histogram, key=int)}
    report["chain_length"] = {
        "histogram": histogram,
        "from_folded_alert": counters["folded_alert"],
        "from_safe_summary": counters["safe_summary"],
        "max": max((int(key) for key in histogram), default=0),
    }

    # [4] 冷却降级
    report["cooldown_demote"] = {
        "events": counters["demote_events"],
        "channels_demoted_total": counters["demoted_total"],
        "by_channel": dict(demote_by_channel),
    }

    # [5] INTIMATE grok
    report["intimate_grok"] = {
        "fallback_events": len(fallbacks),
        "fallbacks": fallbacks,
        "intimate_total": report["served_by"]["intimate_total"],
        "intimate_served_grok_hits": sum(
            1
            for event in served_by_events
            if event["mode"] == "intimate"
            and "grok" in event["served_by"].lower()
        ),
    }

    # [6] 严格优先级探针（轨迹=attempts 序列 ∪ 逐跳失败序列）
    traces = [list(event["attempts"]) for event in served_by_events]
    traces.extend([[event["model"] for event in seq] for seq in sequences])
    if expected_order:
        violations = strict_priority_violations(
            traces, [str(item) for item in expected_order]
        )
        report["strict_priority"] = {
            "probe": "ran",
            "expected_order": [str(item) for item in expected_order],
            "violations": len(violations),
            "details": violations[: max(0, sample_size)],
            "note": (
                "探针只标记「高优渠道整条轨迹未被试」的跳过；冷却降级/健康过滤"
                "的合法重排请结合 cooldown demote 日志判读"
            ),
        }

    # [7] 时段切换
    report["schedule_windows"]["switched"] = sum(schedule_by_target.values())
    report["schedule_windows"]["by_target"] = dict(schedule_by_target)
    report["schedule_windows"]["cleared_outside_windows"] = counters["cleared_outside"]
    report["schedule_windows"]["cleared_schedule_emptied"] = counters[
        "cleared_emptied"
    ]

    # [8] axonhub 对照候选
    report["axonhub_timeout_band"]["candidates"] = sum(band_by_model.values())
    report["axonhub_timeout_band"]["by_model"] = dict(band_by_model)

    # [9] 告警折叠
    report["alert_fold"] = {
        "llm_alert_lines": counters["alert_llm_lines"],
        "folded_kind_lists": counters["folded_kind_lists"],
        "kinds_seen": dict(kinds_seen),
        "suppressed_total": counters["suppressed_total"],
    }
    return report


def collect_from_file(path: Path, **kwargs: Any) -> dict[str, Any]:
    """只读读取单个日志文件并采集；读取失败按空输入 fail-open。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return collect(text.splitlines(), inputs=[str(path)], **kwargs)


def render_report(report: dict[str, Any]) -> str:
    """人类可读报告（纯文本，中文分节）。"""
    meta = report["meta"]
    inputs_text = ", ".join(meta["inputs"]) if meta["inputs"] else "(无，零报告)"
    out: list[str] = ["=== v21r4-B LLM live 取证采集报告 ==="]
    out.append(f"扫描行数 {meta['lines_scanned']} ｜ 输入 {inputs_text}")

    sb = report["served_by"]
    out.append("")
    out.append(
        f"[1] served_by 轨迹：共 {sb['total']} 条（intimate "
        f"{sb['intimate_total']} ｜ 拒答模板命中 {sb['refusal_boilerplate_true']}）"
    )
    for name, count in sorted(sb["by_served_by"].items(), key=lambda kv: -kv[1]):
        out.append(f"    {name}: {count}")
    for sample in sb["samples"][:5]:
        out.append(
            f"    样本 mode={sample['mode']} served_by={sample['served_by']} "
            f"attempts={sample['attempts']}"
        )

    hf = report["hop_failures"]
    out.append("")
    out.append(
        f"[2] 逐跳失败：共 {hf['total']} 跳（by_kind {hf['by_kind']} ｜ "
        f"by_family {hf['by_family']} ｜ intimate {hf['intimate_true']}）"
    )
    shape = [len(seq) for seq in hf["sequences"]]
    out.append(
        f"    失败序列分组（间隔≤300s 归同链）：{shape} ｜ "
        f"最长链 {hf['max_sequence_len']}"
    )

    cl = report["chain_length"]
    out.append("")
    out.append(
        f"[3] chain 长度分布：{cl['histogram'] or '（无样本）'} ｜ 最长 {cl['max']}"
    )
    out.append(
        f"    来源：告警压缩形(chain=N跳全败) {cl['from_folded_alert']} ｜ "
        f"safe_summary 形(chain=N last=x) {cl['from_safe_summary']}"
    )

    cd = report["cooldown_demote"]
    out.append("")
    out.append(
        f"[4] 90s 冷却降级：事件 {cd['events']} 次 ｜ 降级渠道次 "
        f"{cd['channels_demoted_total']} ｜ by_channel {cd['by_channel'] or '（无）'}"
    )

    ig = report["intimate_grok"]
    out.append("")
    out.append(
        f"[5] INTIMATE grok：intimate 会话 {ig['intimate_total']} 条 ｜ "
        f"served_by=grok 命中 {ig['intimate_served_grok_hits']} ｜ "
        f"临时回落 {ig['fallback_events']} 次"
    )
    for item in ig["fallbacks"][:5]:
        out.append(
            f"    回落 head={item['head']} demoted={item['demoted']} "
            f"health_filtered={item['health_filtered']}"
        )

    sp = report["strict_priority"]
    out.append("")
    out.append(
        f"[6] 严格优先级探针：{sp['probe']} ｜ 违例 {sp['violations']} ｜ "
        f"期望序 {sp['expected_order'] or '（未提供）'}"
    )
    for detail in sp["details"][:5]:
        out.append(
            f"    违例 first_tried={detail['first_tried']} "
            f"skipped_higher={detail['skipped_higher']}"
        )

    sw = report["schedule_windows"]
    out.append("")
    out.append(
        f"[7] 时段切换命中：switched {sw['switched']}（by_target "
        f"{sw['by_target'] or '（无）'}）｜ 清除：窗外 "
        f"{sw['cleared_outside_windows']} / 表空 {sw['cleared_schedule_emptied']}"
    )
    out.append(f"    注：{sw['priority_group_note']}")

    ax = report["axonhub_timeout_band"]
    out.append("")
    out.append(
        f"[8] axonhub 对照候选（kind=timeout ∧ elapsed_ms∈"
        f"[{ax['low_ms']},{ax['high_ms']}]）：{ax['candidates']} 条 ｜ "
        f"by_model {ax['by_model'] or '（无）'}"
    )

    af = report["alert_fold"]
    out.append("")
    out.append(
        f"[9] 告警折叠：llm 告警 {af['llm_alert_lines']} 条 ｜ 折叠 kind 清单随行 "
        f"{af['folded_kind_lists']} 次（kinds {af['kinds_seen'] or '（无）'}）｜ "
        f"suppressed 累计 {af['suppressed_total']}"
    )
    out.append("")
    out.append(HINT_TEXT)
    return "\n".join(out)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="v21r4-B LLM live 取证采集器（只读日志统计，九项）"
    )
    parser.add_argument(
        "--log",
        action="append",
        default=None,
        metavar="PATH",
        help="日志文件路径（可重复；缺省=ChatBot_Runtime/logs/nonebot 两份现行日志）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="stdout 输出 JSON 报告（提示语转 stderr，不污染 JSON）",
    )
    parser.add_argument(
        "--expected-order",
        default=None,
        metavar="JSON",
        help='严格优先级探针期望渠道序，如 \'["axon-grok","aiprc-gemini"]\'',
    )
    parser.add_argument(
        "--timeout-band",
        nargs=2,
        type=int,
        default=list(DEFAULT_TIMEOUT_BAND),
        metavar=("LOW_MS", "HIGH_MS"),
        help="axonhub 对照候选的耗时带（缺省 18000 25000）",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help="轨迹抽样条数上限（缺省 20）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    expected_order: list[str] | None = None
    if args.expected_order:
        try:
            parsed = json.loads(args.expected_order)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            expected_order = [str(item) for item in parsed]

    inputs = [Path(item) for item in (args.log or [])] or _default_log_paths()
    all_lines: list[str] = []
    for path in inputs:
        try:
            all_lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
    report = collect(
        all_lines,
        expected_order=expected_order,
        timeout_band=(int(args.timeout_band[0]), int(args.timeout_band[1])),
        sample_size=int(args.sample),
        inputs=[str(item) for item in inputs],
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(HINT_TEXT, file=sys.stderr)
    else:
        print(render_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
