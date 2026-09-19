"""tts_retcode_collect — send_msg 回执 retcode 分布采集（真机验收窗证据工具）.

背景（report-T55 §七唯一 open 项）：「SnowLuma 实回 1400/100」未真机复现——
读码预判实集={100,1200,1400,1404}（SnowLuma config-GJCFWjtq.js:907-910：
ACTION_FAILED:100 / INTERNAL_ERROR:1200 / BAD_REQUEST:1400 / UNKNOWN_ACTION:1404）
置信度 high 非 verified。本工具对真机验收窗（acceptance-manual §6.6.11，
30 项版）后的 nonebot stdout/stderr 日志做**离线扫描**，提取 retcode 分布
（计数+首末时间+样例），与读码预判集对表：
  实测码集 ⊆ 预判集        → T55 §七 open 项闭合证据 +1；
  出现预判集外码           → 新形态提示：留痕（截图+--json 输出）后另案复核；
  我方终态白名单（现状）    → 10 码 {403,404,100,1003,1200,1201,1400,1401,
                              1403,1404}（domains/transport/sender/onebot.py
                              `_is_final_failure_retcode`，T78 裁决：1400/100
                              已入名单、1200 挂起例外已删改终态化）。
判定提示按码给一句话人话（1200 语义漂移、-1=NapCat 旧口径等，出处=T55 §二）。

全离线：只对日志文本做正则解析——零网络、不连 SnowLuma、不启引擎。
日志行格式=nonebot default_format（bot.py：`MM-DD HH:mm:ss [LEVEL] name | message`）；
不匹配该格式的行（异常回溯等）仍扫 retcode= 计数，仅首末时间为空（不丢证据）。

用法：
  venv python scripts/tts_retcode_collect.py                 # 缺省扫 Runtime 日志位
  venv python scripts/tts_retcode_collect.py <log> [log...]  # 指定日志文件
  venv python scripts/tts_retcode_collect.py <log> --json    # 结构化输出
  venv python scripts/tts_retcode_collect.py --samples 5     # 每码样例上限

退出码：0 = 采集完成（有无 retcode 记录均属正常）；1 = 无一文件可读
（缺省位缺失时提示 §6.6.11 P-6：stdout 必须重定向落盘，否则取证链断）。
本工具是证据采集器，不是门：不因「出现失败码」而非零退出。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LOGS = Path("ChatBot_Runtime") / "logs"

# nonebot default_format（nonebot/log.py:78）："{time:MM-DD HH:mm:ss} [{level}] {name} | {message}"
LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[(?P<level>\w+)\]\s+(?P<name>.+?)\s+\|\s+(?P<msg>.*)$"
)
RETCODE_RE = re.compile(r"retcode=(?P<code>-?\d+)")
# retcode= 后没跟可选负号+数字 → 乱码形态（None/空/非数字）
MALFORMED_RE = re.compile(r"retcode=(?!\s*-?\d)")

# 读码预判实集（T46/T55：SnowLuma config-GJCFWjtq.js:907-910）——判定基准
SNOWLUMA_PREDICTED: tuple[int, ...] = (100, 1200, 1400, 1404)
# 已知遗留码（T55 §二记档在案：NapCat 旧口径）——不并入「新形态」判定
LEGACY_KNOWN: frozenset[int] = frozenset({-1})
# 我方终态白名单现状（onebot.py `_is_final_failure_retcode`，T78 裁决后 10 码）
WHITELIST: frozenset[int] = frozenset(
    {403, 404, 100, 1003, 1200, 1201, 1400, 1401, 1403, 1404}
)

# 每码一句话判定提示（出处=report-T55 §二证据分级表；「白名单内」=现状终态化）
CODE_HINTS: dict[int, str] = {
    0: "成功回执——健康信号，不参与失败判定",
    100: "SnowLuma ACTION_FAILED（通用动作失败）——已入白名单：确定性失败第 1 轮即终态，"
    "mixed 文本部件走 W1 降级；通用码可能裹暂态上游错，真机分布用于复核该占比（T55 §二）",
    1200: "SnowLuma INTERNAL_ERROR——语义已漂移（内部错误≠适配器无连接）；已终态化"
    "（T46-N1 裁决删除挂起例外）；码的历史由来 unknown（T55 §二.2）",
    1400: "SnowLuma BAD_REQUEST（段校验失败/参数缺）——已入白名单：确定性失败，"
    "应伴随 mixed 文本部件 W1 降级出现；若反复出现查语音段构造面",
    1404: "SnowLuma UNKNOWN_ACTION（动作名不存在）——白名单内；出现=代码 bug 面（查 API action 拼写）",
    -1: "NapCat 旧口径（rich media transfer failed）——SnowLuma 枚举无 -1："
    "出现=旧端回滚或历史日志（T55 §二）",
    403: "白名单内；历史由来 unknown（T55 §七）",
    404: "白名单内；历史由来 unknown（T55 §七）",
    1003: "白名单内；历史由来 unknown（T55 §七）",
    1201: "白名单内；历史由来 unknown（T55 §七）",
    1401: "白名单内；历史由来 unknown（T55 §七）",
    1403: "白名单内；历史由来 unknown（T55 §七）",
}

_SAMPLE_MAX_CHARS = 200
_DEFAULT_SAMPLES = 3


@dataclass
class CodeStat:
    """单码分布：计数+首末时间+样例（样例=截断后原文行）."""

    retcode: int
    count: int = 0
    first: str | None = None
    last: str | None = None
    samples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "retcode": self.retcode,
            "count": self.count,
            "first": self.first,
            "last": self.last,
            "in_snowluma_set": self.retcode in SNOWLUMA_PREDICTED,
            "in_whitelist": self.retcode in WHITELIST,
            "hint": CODE_HINTS.get(
                self.retcode,
                "未收录码=新形态提示：对照 SnowLuma 枚举 {100,1200,1400,1404} 与"
                "白名单 10 码复核，留痕后另案",
            ),
            "samples": self.samples,
        }


@dataclass
class Report:
    """采集结果：供人话摘要与 --json 共用."""

    files: list[str]
    missing_files: list[str]
    lines_scanned: int
    malformed_hits: int
    malformed_samples: list[str]
    stats: dict[int, CodeStat] = field(default_factory=dict)

    @property
    def retcode_hits(self) -> int:
        return sum(s.count for s in self.stats.values())

    def sorted_codes(self) -> list[CodeStat]:
        return sorted(self.stats.values(), key=lambda s: (-s.count, s.retcode))

    def new_codes(self) -> list[int]:
        """预判集/已知遗留码/0 成功码之外的新形态码，按计数降序."""
        known = set(SNOWLUMA_PREDICTED) | {0} | set(LEGACY_KNOWN)
        return [s.retcode for s in self.sorted_codes() if s.retcode not in known]

    def verdict(self) -> str:
        if not self.stats and not self.malformed_hits:
            return (
                "日志中零 retcode 记录——健康面；若期望取证（R1/R13），"
                "先核 §6.6.11 P-6 stdout 重定向是否开启"
            )
        observed = {s.retcode for s in self.stats.values()} - {0}
        new = set(self.new_codes())
        if not observed and self.malformed_hits:
            return f"仅 {self.malformed_hits} 处乱码 retcode 形态（无数值）——不参与判定，样例留痕备查"
        if new:
            shown = "、".join(str(c) for c in sorted(new))
            return (
                f"实测出现读码预判集外码 [{shown}] ——新形态：保留本工具 --json 输出与日志截图，"
                "对照 SnowLuma 枚举 {100,1200,1400,1404} 与白名单 10 码复核后另案（勿凭单条归因）"
            )
        return (
            f"实测码集 {sorted(observed)} ⊆ 读码预判集 {list(SNOWLUMA_PREDICTED)} ——"
            "T55 §七 open 项（实回集取证）闭合证据 +1；分布计数供 §6.6.11 R 段归因"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "files": self.files,
            "missing_files": self.missing_files,
            "scanned_files": len(self.files) - len(self.missing_files),
            "lines_scanned": self.lines_scanned,
            "retcode_hits": self.retcode_hits,
            "malformed_hits": self.malformed_hits,
            "malformed_samples": self.malformed_samples,
            "predicted_snowluma_set": list(SNOWLUMA_PREDICTED),
            "whitelist": sorted(WHITELIST),
            "codes": [s.as_dict() for s in self.sorted_codes()],
            "new_codes": self.new_codes(),
            "verdict": self.verdict(),
        }


def default_log_paths(project_root: Path = PROJECT_ROOT) -> list[Path]:
    """缺省 Runtime 日志位：nonebot stdout + stderr（P-6 取证主面）."""
    logs = project_root.parent / RUNTIME_LOGS
    return [logs / "nonebot.out.log", logs / "nonebot.err.log"]


def _feed(stat: CodeStat, ts: str | None, raw_line: str, max_samples: int) -> None:
    stat.count += 1
    if ts:
        if stat.first is None:
            stat.first = ts
        stat.last = ts
    if len(stat.samples) < max_samples:
        stat.samples.append(raw_line.strip()[:_SAMPLE_MAX_CHARS])


def _collect_report(paths: list[Path], max_samples: int = _DEFAULT_SAMPLES) -> Report:
    """扫描日志文件集，产出 retcode 分布 Report（全离线文本解析）."""
    report = Report(
        files=[str(p) for p in paths],
        missing_files=[],
        lines_scanned=0,
        malformed_hits=0,
        malformed_samples=[],
    )
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            report.missing_files.append(str(path))
            continue
        for raw_line in text.splitlines():
            if "retcode" not in raw_line:
                continue
            report.lines_scanned += 1
            ts_match = LOG_LINE_RE.match(raw_line)
            ts = ts_match.group("ts") if ts_match else None
            for match in RETCODE_RE.finditer(raw_line):
                code = int(match.group("code"))
                stat = report.stats.setdefault(code, CodeStat(retcode=code))
                _feed(stat, ts, raw_line, max_samples)
            for _ in MALFORMED_RE.finditer(raw_line):
                report.malformed_hits += 1
                if len(report.malformed_samples) < max_samples:
                    report.malformed_samples.append(raw_line.strip()[:_SAMPLE_MAX_CHARS])
    return report


def collect(paths: list[Path], max_samples: int = _DEFAULT_SAMPLES) -> dict[str, object]:
    """``_collect_report`` 的结构化出口（测试/外部调用面）."""
    return _collect_report(paths, max_samples=max_samples).as_dict()


def render_summary(report: Report) -> str:
    """人话摘要：逐码一行（计数+首末时间+提示）+ 判定结论."""
    lines: list[str] = []
    scanned = len(report.files) - len(report.missing_files)
    lines.append(
        f"retcode 分布采集：文件 {scanned}/{len(report.files)} 可读，"
        f"含 retcode 行 {report.lines_scanned}（其中乱码形态 {report.malformed_hits} 处）"
    )
    for missing in report.missing_files:
        lines.append(f"  缺失：{missing}")
    if not report.stats:
        lines.append("  （无 retcode 数值记录）")
    for stat in report.sorted_codes():
        where = f"首发 {stat.first}" if stat.first else "无时间戳行"
        end = f"｜末见 {stat.last}" if stat.last else ""
        info = stat.as_dict()
        lines.append(
            f"  retcode={stat.retcode:<5} 计数 {stat.count:<4} {where}{end}"
            f"｜白名单={'是' if info['in_whitelist'] else '否'}｜预判集={'是' if info['in_snowluma_set'] else '否'}"
        )
        lines.append(f"    提示：{info['hint']}")
        for sample in stat.samples[:2]:
            lines.append(f"    样例：{sample}")
    if report.malformed_samples:
        lines.append("  乱码形态样例：")
        for sample in report.malformed_samples[:2]:
            lines.append(f"    {sample}")
    lines.append("")
    lines.append(f"判定：{report.verdict()}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="send_msg 回执 retcode 分布采集（离线日志扫描，T55 §七取证工具）"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=None,
        help="日志文件路径（缺省=Runtime 日志位 nonebot.out.log/nonebot.err.log）",
    )
    parser.add_argument("--json", action="store_true", help="结构化 JSON 输出")
    parser.add_argument(
        "--samples", type=int, default=_DEFAULT_SAMPLES, help=f"每码样例上限（默认 {_DEFAULT_SAMPLES}）"
    )
    args = parser.parse_args(argv)

    try:  # Windows 控制台中文输出防 mojibake
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

    paths = [Path(p) for p in args.paths] if args.paths else default_log_paths()
    report = _collect_report(paths, max_samples=max(0, args.samples))

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_summary(report))

    if len(report.missing_files) == len(paths):
        print()
        print("无一文件可读——若为真机验收窗取证：先按 §6.6.11 P-6 把 stdout 重定向落盘再复跑。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
