"""慢回复先回执（ack-first）· 阈值量具（只读，离线，S-T-ACK-1 需求项 6 收尾）。

存在的理由：「15 秒算不算慢」此前只有直觉，没有分布。本件把判断换成实跑数据——
从运行事件日志读 `event=pipeline_result` 的 `duration_ms`（一条消息从进管线到出
终态的整轮耗时，正是回执阈值实际对照的那把尺），算 P50/P90/P95/max，再逐格换算
「候选阈值下这一窗会发几句回执」。

铁律：
- **只读**。不新增埋点、不改任何被测件；数据源只认既有日志与渠道健康库。
- 样本不足就如实说样本不足，**绝不编分布**（合成序列仅限 `--synthetic` 显式要求，
  且输出里逐字标注 SYNTHETIC）。
- 阈值属用户裁定面：本件只给换算表与建议值，不写回任何配置。

用法（在仓库根目录）::

    ../ChatBot_Runtime/venv/Scripts/python.exe scripts/probe_ack_threshold.py
    ... scripts/probe_ack_threshold.py --window-hours 6 --min-samples 50
    ... scripts/probe_ack_threshold.py --synthetic path/to/durations_ms.txt
    ... scripts/probe_ack_threshold.py --json          # 机器可读输出
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# 事件行形态（runtime/runtime_events 日志的既有格式，不改动）：
#   2026-09-25 22:59:15.053 [INFO] event=pipeline_result capability_id=bot.chat
#     receipt_state=ok transport=runtime duration_ms=20458.6 request_id=...
_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}) (?P<clock>\d{2}:\d{2}:\d{2}\.\d+) .*?\bevent=pipeline_result\b"
    r".*?\bcapability_id=(?P<cap>\S+).*?\breceipt_state=(?P<state>\S+)"
    r".*?\bduration_ms=(?P<ms>[0-9.]+)"
)

# 回执阈值判据的在册常量（真身住 progress_ack.py；此处只做换算展示，漂移由
# tests/test_progress_ack_thresholds.py 的 parity 锁管，本件不执法）。
FLOOR_SECONDS = 15.0
CAP_SECONDS = 90.0
MULTIPLIER = 2.0
COOLDOWN_SECONDS = 60.0

# 渠道健康库里现网在用的两条主链渠道（台账 #50：注册表收敛后全走 axonhub）。
PROBE_CHANNELS = ("axon-gemini-38-flash", "axon-grok-46")


def default_log_files(repo_root: Path) -> list[Path]:
    runtime = repo_root.parent / "ChatBot_Runtime" / "data"
    files = sorted(runtime.glob("runtime_events.log*"))
    return [f for f in files if f.is_file()]


def parse_events(files: list[Path], *, window_hours: float) -> list[dict[str, Any]]:
    """按「此刻起 N 小时」过滤（日志混着旧卷与启动前残行，全收会虚增窗口外样本）。"""
    cutoff = datetime.now().astimezone() - timedelta(hours=window_hours)
    rows: list[dict[str, Any]] = []
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = _LINE_RE.search(line)
                if match is None:
                    continue
                try:
                    # 日志时钟是机器本地时间（naive），astimezone 按本地时区补偏移。
                    stamp = datetime.strptime(
                        f"{match.group('ts')} {match.group('clock')}",
                        "%Y-%m-%d %H:%M:%S.%f",
                    ).astimezone()
                except ValueError:
                    continue
                if stamp < cutoff:
                    continue
                rows.append(
                    {
                        "date": match.group("ts"),
                        "clock": match.group("clock"),
                        "capability_id": match.group("cap"),
                        "receipt_state": match.group("state"),
                        "duration_ms": float(match.group("ms")),
                        "source": path.name,
                    }
                )
    return rows


def percentile(sorted_values: list[float], q: float) -> float:
    """最近秩法（对整数/毫秒序列足够，不插值——插值会给小样本装精度）。"""
    if not sorted_values:
        return float("nan")
    index = max(0, min(len(sorted_values) - 1, round(q * (len(sorted_values) - 1))))
    return sorted_values[index]


def read_channel_ema(runtime_data: Path) -> dict[str, float | None]:
    """渠道健康库 EWMA（只读）；库不在/读失败 ⇒ 该渠道 None（诚实缺测，不猜）。"""
    out: dict[str, float | None] = {name: None for name in PROBE_CHANNELS}
    db = runtime_data / "channel_health.sqlite3"
    if not db.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            for name in PROBE_CHANNELS:
                row = con.execute(
                    "SELECT ema_ms FROM channel_health WHERE model_id=?", (name,)
                ).fetchone()
                if row and row[0]:
                    out[name] = float(row[0])
        finally:
            con.close()
    except sqlite3.Error:
        pass  # 观测面坏了不得把量具一起带走——退化成缺测报告
    return out


def adaptive_bar(ema_ms: float | None) -> float:
    """现行自适应判据的静态换算：clamp(ema × 倍率, floor, cap)；缺测退 floor。"""
    if not ema_ms or ema_ms <= 0:
        return FLOOR_SECONDS
    derived = (ema_ms / 1000.0) * MULTIPLIER
    return min(CAP_SECONDS, max(FLOOR_SECONDS, derived))


def fire_table(durations_s: list[float], bars: dict[str, float]) -> list[tuple[str, float, int]]:
    """每一格阈值 ⇒ 这一窗里会发几句回执（冷却合并前，按轮计）。"""
    rows: list[tuple[str, float, int]] = []
    for label, bar in bars.items():
        hits = sum(1 for value in durations_s if value > bar)
        rows.append((label, bar, hits))
    return rows


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台缺省 GBK，表里必有中文与箭头——先把 stdout 钉成 UTF-8（只读工具，
    # 不改任何被测面；重定向到文件时同样成立）。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--logs", nargs="*", default=None, help="显式事件日志路径（缺省自动发现）")
    parser.add_argument("--window-hours", type=float, default=48.0,
                        help="只统计此刻起 N 小时内的行（日志按 ~2MB 轮转，缺省 48 覆盖现役+上一卷）")
    parser.add_argument("--min-samples", type=int, default=30,
                        help="低于此数如实报「样本不足」，不出结论")
    parser.add_argument("--synthetic", metavar="FILE", default=None,
                        help="用文件里的合成毫秒序列（一行一个），显式声明的合成评估")
    parser.add_argument("--extra-bars", metavar="S1,S2,...", default=None,
                        help="追加候选阈值（秒）一起进换算表——给裁定面试数用，不改任何配置")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    runtime_data = repo_root.parent / "ChatBot_Runtime" / "data"

    synthetic = False
    rows: list[dict[str, Any]] = []
    if args.synthetic:
        synthetic = True
        series = [
            float(line)
            for line in Path(args.synthetic).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rows = [
            {"capability_id": "bot.chat", "receipt_state": "queued", "duration_ms": ms}
            for ms in series
        ]
    else:
        files = [Path(f) for f in (args.logs or default_log_files(repo_root))]
        rows = parse_events(files, window_hours=args.window_hours)

    chat_rows = [r for r in rows if r["capability_id"] == "bot.chat"]
    # 实况词汇：本遥测里成功整轮的终态是 queued（进发送队列）；blocked/skipped 的轮次
    # 在 `_prepare` 就被政策门拦掉，**压根走不到能力等待**，回执结构上不可能发——
    # 混进分母会把触发率稀释成假低。`sent` 一并认作成功形态，向前兼容。
    ok_rows = [r for r in chat_rows if r["receipt_state"] in {"queued", "sent"}]
    all_ms = sorted(float(r["duration_ms"]) for r in chat_rows)
    ok_ms = sorted(float(r["duration_ms"]) for r in ok_rows)

    ema = read_channel_ema(runtime_data)
    bars: dict[str, float] = {"static_15s": FLOOR_SECONDS}
    for channel, value in ema.items():
        if value:
            bars[f"adaptive_{channel}"] = adaptive_bar(value)
    if args.extra_bars:
        for raw in args.extra_bars.split(","):
            try:
                seconds = float(raw)
            except ValueError:
                continue
            if seconds > 0:
                bars[f"candidate_{seconds:g}s"] = seconds

    def stats(ms: list[float]) -> dict[str, float]:
        return {
            "n": len(ms),
            "p50_s": round(percentile(ms, 0.50) / 1000.0, 2),
            "p90_s": round(percentile(ms, 0.90) / 1000.0, 2),
            "p95_s": round(percentile(ms, 0.95) / 1000.0, 2),
            "max_s": round((ms[-1] if ms else float("nan")) / 1000.0, 2),
        }

    result: dict[str, Any] = {
        "synthetic": synthetic,
        "window_hours": args.window_hours,
        "chat_turns": stats(all_ms),
        "ok_turns": stats(ok_ms),
        "channel_ema_ms": ema,
        "bars_s": {k: round(v, 2) for k, v in bars.items()},
    }
    n_for_table = len(ok_ms) if len(ok_ms) >= 10 else len(all_ms)
    table_ms = ok_ms if len(ok_ms) >= 10 else all_ms
    result["fire_table"] = [
        {"bar": label, "bar_s": round(bar, 2), "fires": hits,
         "per_turn_pct": round(100.0 * hits / n_for_table, 1) if n_for_table else None}
        for label, bar, hits in fire_table(
            [ms / 1000.0 for ms in table_ms], bars
        )
    ] if n_for_table else []

    sufficient = len(table_ms) >= args.min_samples
    result["sufficient"] = bool(sufficient)

    if args.json:
        result["ok_durations_s"] = [round(ms / 1000.0, 2) for ms in ok_ms]
        result["all_durations_s"] = [round(ms / 1000.0, 2) for ms in all_ms]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    tag = "SYNTHETIC（合成序列，非实跑）" if synthetic else "实测（pipeline_result.duration_ms）"
    blocked = len([r for r in chat_rows if r["receipt_state"] == "blocked"])
    print(f"数据形态：{tag}")
    print(f"窗口：近 {args.window_hours:g} 小时；bot.chat 整轮 {result['chat_turns']['n']} 条"
          f"（成功入队 {result['ok_turns']['n']} 条；被政策门拦截 {blocked} 条不计入触发分母）")
    for scope in ("chat_turns", "ok_turns"):
        s = result[scope]
        print(f"  {scope:10s} n={s['n']:5d}  P50={s['p50_s']}s  P90={s['p90_s']}s"
              f"  P95={s['p95_s']}s  max={s['max_s']}s")
    print("渠道 EWMA（channel_health.sqlite3 只读现值）：")
    for channel, value in ema.items():
        if value:
            print(f"  {channel}: {value:.0f}ms ⇒ 当前自适应阈值 {adaptive_bar(value):.1f}s")
        else:
            print(f"  {channel}: 缺测 ⇒ 自适应退固定值 {FLOOR_SECONDS:g}s")
    if not sufficient:
        print(f"⚠ 样本不足（有效 {len(table_ms)} < {args.min_samples}）——不出触发率结论。"
              "可等日志积累后复跑，或用 --synthetic 显式评估合成序列。")
        return 0
    print("换算表（按成功轮次；冷却合并前，60s/会话 冷却只会少发不会多发）：")
    for row in result["fire_table"]:
        print(f"  阈值 {row['bar']:>22s} = {row['bar_s']:5.1f}s"
              f" ⇒ 该窗发 {row['fires']} 句 / {n_for_table} 轮 = {row['per_turn_pct']}%")
    p95 = result["ok_turns"]["p95_s"] if result["ok_turns"]["n"] >= 10 else result["chat_turns"]["p95_s"]
    print(f"参考：P95={p95}s ⇒ 若用固定阈值，不低于 {p95}s 才谈得上「正常回复不误发」；"
          "现行自适应缺测退 15s、有测按 2×EMA 抬到 15–90s 区间。")
    print("限制条款：① 窗口受日志轮转（~2MB 一卷）约束，本表只覆盖窗口内流量形态；"
          "② duration_ms 是整轮（含排队/渲染），比 LLM 段本身宽；"
          "③ EWMA 取的是**此刻**健康库值，非逐轮对齐；"
          "④ 触发率为「按轮」口径，未再扣同会话 60 秒冷却的去重。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
