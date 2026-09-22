#!/usr/bin/env python
"""G-C1 调度饱和门·第二腿快照取数件（席位 S71，2026-09-22；活性口径由席位 S181 修准）。

`DISPATCH-SNAPSHOT.json` 的机器可读契约**只准本脚本写**，人不手写。
本轮根因实证（S57 Critical-3）：主代理手写快照用了 `generated_at_utc` /
`active_seats_lives_60s` / `method` / `seats_in_flight` 这套键名，而门
`tests/test_dispatch_saturation_gate.py:208` 逐字要求四键
`captured_at_utc / window_seconds / active_seats / source_command`
⇒ 键名不合＝真顶满也 KeyError。人不该手写机器可读契约，故立此取数件。

**两栏并列（S181 起的形态，旧口径不摘）**
- `active_seats`（**第一栏 = 被度量对象**）＝ **在飞席数**，算法 `start − (finish ∪ error)`：
  扫 `~/.qoder-cn/logs/runs/*/qodercli.log` 里 harness 自己打的
  `[SubagentRun] start|finish|error agentId=… sessionId=…` 生命周期事件，
  按「本项目会话目录」限定 sessionId，取已开始、尚未 finish 也未 error 的 agentId 集合。
  终态含 `error` 这一种（服务侧掐死席），只减 `finish` 会把死席算成长活。
- `active_seats_mtime_window`（**第二栏 = 代理指标，原样保留**）＝ 窗口内写过字节的席位
  transcript 枚数，即本件旧算法。**它不是「在飞席数」**：席位卡在长工具调用里就不写
  transcript，60 秒窗对长调用系统性虚低（S170 五次实测 10/9/8/7/9 而十席全活在册）。
  保留第二栏＝不摘掉旧扫描面，两栏差异本身就是器具诊断（假绿形态册第 2 类：
  代理指标当被度量对象）。

四键判据（与门 :205-237 逐字对齐；门本体与秒数本件一字不动）：
- `captured_at_utc`  `YYYY-MM-DDTHH:MM:SSZ`（UTC 秒级截断，天然不会落在未来）。
- `window_seconds`   `int > 0`，缺省 **60**；只允许用参数**显式加大**
  （＝如实记录更宽窗口），不许为让门变绿去调——判据本身在本件零改动。
  该值同时是门腿 6 新鲜度上限 N 的唯一派生来源，也是**第二栏**的窗口。
- `active_seats`     `int >= 0`，＝**在飞席数**（第一栏，`start − (finish ∪ error)`）。
- `source_command`   可复跑的现算命令字面量，**同时**含 `find` / `subagents` / `-newermt`
  （门的形状锁逐字要这三枚）与活性腿的 `[SubagentRun]` 取数说明。

安全边界（BRIEFS《S71》+《S181》逐字）：
- 对 `~/.qoder-cn/projects/<proj>/*/subagents` 会话记录面与 `logs/runs/**` 台账面**只读**，
  绝不写、绝不删。
- **fail-closed**：台账目录缺失 / 无 `qodercli.log` / 逐文件不可读 / 一条生命周期事件都没采到
  ⇒ 显式报错退出且**不写快照**（宁缺不造，**绝不退回 mtime 猜**）。
- 写盘＝临时件 + `os.replace` 一次原子替换；任何一步失败 ⇒ 旧件原样不损坏。
- 找不到 GNU findutils / 会话记录目录缺失 ⇒ 显式报错退出且**不写**（宁缺不造）。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

#: 缺省活性窗口（秒）。第二栏（mtime 腿）的窗口，也是门腿 6 新鲜度上限 N 的派生来源。
#: S181 硬线：**不许为了让 C8 好看去改这个秒数**。
DEFAULT_WINDOW_SECONDS = 60

#: 第一栏 `active_seats` 的算法标识（写进快照，供审计与门的来源核对）。
ACTIVE_SEATS_BASIS = "liveness:start_minus_finish_union_error"

#: harness 自己打的席位生命周期事件（终态两支：finish 与 error）。
_SUBAGENT_EVENT_RE = re.compile(r"\[SubagentRun\] (start|finish|error)\b")
#: 事件行的 `key=value` 载荷（start 行 sessionId 在 agentType 之后，故逐键取，不锚位置）。
_KV_RE = re.compile(r"(\w+)=(\S+)")
#: 行首带偏移的时间戳（`2026-09-22T21:03:47.110+08:00`）。
_LINE_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2})")
_SESSION_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = (
    _REPO_ROOT / ".superpowers" / "sdd" / "2026-09-22-taxonomy" / "DISPATCH-SNAPSHOT.json"
)
_SUBAGENTS_PATH_PREDICATE = "*/subagents/*"


def _project_slug(repo_root: Path) -> str:
    """仓库根绝对路径 → qoder 会话记录的项目目录名。

    实测映射（本机）：`C:\\Users\\...\\ChatBot\\ChatBot` →
    `C--Users-...-ChatBot-ChatBot`，即 `:`→`-` 且 `\\`→`-`。
    """
    return str(repo_root).replace(":", "-").replace("\\", "-")


def _posix_path(path: Path) -> str:
    """Windows 路径 → Git Bash 风格（`C:/x` → `/c/x`），供 find 现算与复跑命令用。"""
    text = str(path).replace("\\", "/")
    if len(text) > 1 and text[1] == ":":
        text = "/" + text[0].lower() + text[2:]
    return text


def _locate_gnu_find() -> str:
    """定位**真正的 GNU findutils**（Windows 自带 FIND.EXE 是同名不同物，绝不误用）。"""
    candidates: list[str | None] = [shutil.which("find")]
    for fixed in (
        r"C:\Program Files\Git\usr\bin\find.exe",
        r"C:\Program Files\Git\bin\find.exe",
    ):
        candidates.append(fixed if os.path.exists(fixed) else None)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            probe = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,  # 版本探针允许非零退出，逐候选继续
            )
        except OSError:
            continue
        if "findutils" in probe.stdout:
            return candidate
    raise SystemExit(
        "未找到 GNU findutils（PATH 无 find 或命中非 findutils 实现）——"
        "第二腿必须 find 现算，宁缺不造，本次不写快照。"
    )


def capture_active_seats(window_seconds: int, projects_root: Path, repo_root: Path) -> tuple[int, str]:
    """实跑那条 find 现算**第二栏**（窗口内写过字节的 transcript 枚数），返回 (枚数, 命令字面量)。

    ⚠ 这一支是**代理指标**：S170 实证它对长工具调用系统性虚低（十席全活时 60 秒窗只数到 7–9）。
    它留在账上是为了「两栏并列可诊断」，**不充当在飞席数**。
    """
    project_dir = projects_root / _project_slug(repo_root)
    if not project_dir.is_dir():
        raise SystemExit(f"会话记录目录不存在：{project_dir}——不造数，本次不写快照。")
    find_exe = _locate_gnu_find()
    newermt = f"-{window_seconds} seconds"
    target = _posix_path(project_dir)
    argv = [
        find_exe,
        target,
        "-path",
        _SUBAGENTS_PATH_PREDICATE,
        "-name",
        "*.jsonl",
        "-newermt",
        newermt,
    ]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,  # 下方显式核对 returncode，非零即停且不写快照
        )
    except OSError as exc:  # 可执行文件中途消失等
        raise SystemExit(f"find 现算无法执行：{exc}——本次不写快照。") from exc
    if proc.returncode != 0:
        raise SystemExit(
            f"find 现算失败 rc={proc.returncode}：{proc.stderr.strip()}——本次不写快照。"
        )
    active = sum(1 for line in proc.stdout.splitlines() if line.strip())
    source_command = (
        " ".join(
            [
                "find",
                shlex.quote(target),
                "-path",
                shlex.quote(_SUBAGENTS_PATH_PREDICATE),
                "-name",
                "'*.jsonl'",
                "-newermt",
                shlex.quote(newermt),
            ]
        )
        + " | wc -l"
    )
    return active, source_command


# ---------------------------------------------------------------------------
# 第一栏：在飞席数 `start − (finish ∪ error)`（S181 修准的活性口径）
# ---------------------------------------------------------------------------


class LivenessScan:
    """一次台账扫描的结果集：已开始席位、已终态席位，以及扫描面自证。"""

    def __init__(self) -> None:
        self.started: dict[str, _dt.datetime] = {}
        self.terminated: dict[str, tuple[str, _dt.datetime]] = {}
        self.log_files: int = 0
        self.scanned_bytes: int = 0
        self.scoped_sessions: frozenset[str] = frozenset()
        self.in_flight_ids: list[str] = []

    def as_dict(self) -> dict[str, object]:
        return {
            "algorithm": ACTIVE_SEATS_BASIS,
            "started_seats": len(self.started),
            "terminated_seats": len(self.terminated),
            "in_flight_seats": len(self.in_flight_ids),
            "in_flight_agent_ids": list(self.in_flight_ids),
            "log_files_scanned": self.log_files,
            "log_bytes_scanned": self.scanned_bytes,
            "scoped_session_ids": sorted(self.scoped_sessions),
        }


def project_session_ids(projects_root: Path, repo_root: Path) -> frozenset[str]:
    """本项目的会话 uuid 集合（＝sessionId 限定域）。目录缺失 ⇒ fail-closed。"""
    project_dir = projects_root / _project_slug(repo_root)
    if not project_dir.is_dir():
        raise SystemExit(f"会话记录目录不存在：{project_dir}——活性口径无法限定作用域，本次不写快照。")
    try:
        entries = list(project_dir.iterdir())
    except OSError as exc:
        raise SystemExit(f"会话记录目录不可读：{project_dir}（{exc}）——fail-closed，不退回 mtime 猜。") from exc
    return frozenset(
        entry.name for entry in entries if entry.is_dir() and _SESSION_UUID_RE.fullmatch(entry.name)
    )


def _aware_from_line(line: str) -> _dt.datetime | None:
    """取行首带偏移的时间戳；形态不合 ⇒ None（宁缺不猜）。"""
    match = _LINE_TS_RE.match(line)
    if not match:
        return None
    try:
        return _dt.datetime.fromisoformat(match.group(1))
    except ValueError:  # pragma: no cover - 正则已限形，防御性双保险
        return None


def scan_liveness(logs_root: Path, projects_root: Path, repo_root: Path) -> LivenessScan:
    """扫 `logs_root/*/qodercli.log` 的 `[SubagentRun]` 生命周期事件，现算在飞席集合。

    四条 fail-closed（S181 必做③c）：台账根不存在 / 没有任何 `qodercli.log` /
    逐文件不可读 / 一条生命周期事件都没采到 ⇒ **点名报错且不写快照**，
    绝不「采不到就退回 mtime 窗猜」。
    """
    sessions = project_session_ids(projects_root, repo_root)
    if not sessions:
        raise SystemExit(
            f"{projects_root} 下没有本项目任何会话目录——活性口径没有作用域，fail-closed。"
        )
    if not logs_root.is_dir():
        raise SystemExit(f"席位台账根不存在：{logs_root}——fail-closed，不退回 mtime 猜。")
    log_files = sorted(logs_root.glob("*/qodercli.log"))
    if not log_files:
        raise SystemExit(
            f"席位台账根下没有 qodercli.log：{logs_root}——fail-closed，不退回 mtime 猜。"
        )
    scan = LivenessScan()
    scan.scoped_sessions = sessions
    unreadable: list[str] = []
    for log in log_files:
        try:
            with log.open("rb") as handle:
                for raw in handle:
                    scan.scanned_bytes += len(raw)
                    if b"[SubagentRun] " not in raw:
                        continue
                    line = raw.decode("utf-8", "replace")
                    event = _SUBAGENT_EVENT_RE.search(line)
                    if event is None:
                        continue
                    payload = dict(_KV_RE.findall(line))
                    if payload.get("sessionId") not in sessions:
                        continue
                    stamp = _aware_from_line(line)
                    agent_id = payload.get("agentId")
                    if stamp is None or not agent_id:
                        continue
                    if event.group(1) == "start":
                        scan.started[agent_id] = stamp
                    else:
                        scan.terminated[agent_id] = (event.group(1), stamp)
        except OSError as exc:
            unreadable.append(f"{log}（{exc}）")
        scan.log_files += 1
    if unreadable:
        raise SystemExit(
            "席位台账不可读 ⇒ fail-closed（不退回 mtime 猜）：\n  " + "\n  ".join(unreadable)
        )
    if not scan.started and not scan.terminated:
        raise SystemExit(
            f"扫了 {len(log_files)} 枚 qodercli.log（{scan.scanned_bytes // 2**20} MiB）"
            "，一条 `[SubagentRun] start|finish|error` 都没采到 ⇒ **器具失效**（事件形态变了？"
            "sessionId 限定域对不上？）——宁缺不造，本次不写快照。"
        )
    scan.in_flight_ids = in_flight_at(scan, _dt.datetime.now(_dt.timezone.utc))
    return scan


def in_flight_at(scan: LivenessScan, at: _dt.datetime) -> list[str]:
    """在飞席＝在 `at` 之前已 start、且（无终态 或 终态晚于 `at`）的 agentId。"""
    moment = at if at.tzinfo is not None else at.astimezone()
    open_ids: list[str] = []
    for agent_id, start in scan.started.items():
        if start > moment:
            continue
        term = scan.terminated.get(agent_id)
        if term is not None and term[1] <= moment:
            continue
        open_ids.append(agent_id)
    return sorted(open_ids)


def build_snapshot(
    window_seconds: int,
    projects_root: Path,
    repo_root: Path,
    logs_root: Path,
) -> dict[str, object]:
    mtime_active, mtime_command = capture_active_seats(window_seconds, projects_root, repo_root)
    scan = scan_liveness(logs_root, projects_root, repo_root)
    captured_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    liveness_command = (
        f"python scripts/dispatch_saturation_snapshot.py --dry-run"
        f"  # 在飞 = [SubagentRun] start − (finish ∪ error)，"
        f"取数面 {shlex.quote(_posix_path(logs_root))}/*/qodercli.log"
        f"，按 sessionId ∈ {shlex.quote(_posix_path(projects_root))}"
        f"/{shlex.quote(_project_slug(repo_root))}/* 限定"
    )
    source_command = (
        f"active_seats ← {liveness_command}；"
        f"active_seats_mtime_window ← {mtime_command}"
    )
    return {
        "captured_at_utc": captured_at,
        "window_seconds": int(window_seconds),
        "active_seats": len(scan.in_flight_ids),
        "source_command": source_command,
        "active_seats_basis": ACTIVE_SEATS_BASIS,
        "active_seats_mtime_window": int(mtime_active),
        "mtime_window_source_command": mtime_command,
        "liveness_source_command": liveness_command,
        "liveness": scan.as_dict(),
        "generated_by": "scripts/dispatch_saturation_snapshot.py",
        "note": "G-C1 第二腿机器可读快照——只准本脚本写；键名逐字对齐 "
        "tests/test_dispatch_saturation_gate.py:205-237；人不手写。"
        "两栏并列：active_seats＝在飞席数（start−(finish∪error)），"
        "active_seats_mtime_window＝窗口内写过字节的 transcript 枚数（旧口径，代理指标，只留不摘）。",
    }


def judge_snapshot(snapshot: dict[str, object], now: _dt.datetime) -> list[str]:
    """对「刚重拍」的新鲜快照做自洽判定，返回违例清单（空=合格）。

    仅判形状/来源/新鲜度 + 两栏自证，且刻意**不**复制门的顶满阈值 ——
    `active_seats >= CEILING` 是门 ``test_snapshot_active_seats_meet_ceiling`` 的专属判据，
    本件不建第二本账：
    - 形状/来源可机检（四键齐 + ``source_command`` 含 find/subagents/-newermt）
    - 两栏都在账上（第一栏活性口径、第二栏旧 mtime 口径），且口径标识逐字等于常量
    - 新鲜度：``captured_at`` 距 ``now`` 不得超过快照自报 ``window_seconds``
      （上限 N 由窗口派生、非魔数，P-52）。

    「跳过重拍直接判旧件」这条路 = 判到一份 ``age > window_seconds`` 的快照 ⇒ 本函数
    点名其为违例、``--verify`` 据此非零退出，绝不静默采信旧件（不是「默默用旧文件」）。
    """
    problems: list[str] = []
    for key in ("captured_at_utc", "window_seconds", "active_seats", "source_command"):
        if key not in snapshot:
            problems.append(f"缺字段 {key}")
    if problems:
        return problems
    src = str(snapshot["source_command"])
    if not ("subagents" in src and "-newermt" in src and "find" in src):
        problems.append("source_command 不像那条 find 现算命令（缺 find/subagents/-newermt）")
    if "[SubagentRun]" not in src:
        problems.append("source_command 缺第一栏活性腿的 [SubagentRun] 取数说明（两栏必须并列）")
    if snapshot.get("active_seats_basis") != ACTIVE_SEATS_BASIS:
        problems.append(
            f"active_seats_basis 不是 {ACTIVE_SEATS_BASIS}：{snapshot.get('active_seats_basis')!r}"
        )
    mtime_leg = snapshot.get("active_seats_mtime_window")
    if not (isinstance(mtime_leg, int) and mtime_leg >= 0):
        problems.append(f"active_seats_mtime_window 非非负整数（旧口径不许摘）：{mtime_leg!r}")
    active = snapshot["active_seats"]
    if not (isinstance(active, int) and active >= 0):
        problems.append(f"active_seats 非非负整数：{active!r}")
    window = snapshot["window_seconds"]
    if not (isinstance(window, int) and window > 0):
        problems.append(f"window_seconds 非正整数：{window!r}")
        return problems
    m = re.match(
        r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$", str(snapshot["captured_at_utc"])
    )
    if not m:
        problems.append("captured_at_utc 非 YYYY-MM-DDTHH:MM:SSZ 形态")
        return problems
    year, month, day, hh, mm, ss = (int(g) for g in m.groups())
    captured = _dt.datetime(year, month, day, hh, mm, ss, tzinfo=_dt.timezone.utc)
    age = (now - captured).total_seconds()
    if age < 0:
        problems.append(f"captured_at 在未来 {abs(age):.0f}s（时间戳造假）")
    elif age > window:
        problems.append(
            f"快照已过时 {age:.0f}s > 新鲜度上限 N=window_seconds={window}s"
            "（陈旧件不得充当当前证据——判定必须伴随重拍）"
        )
    return problems


def atomic_write(output: Path, text: str) -> None:
    """临时件 + os.replace 一次原子替换；失败留旧件不损坏。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f"{output.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, output)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _default_logs_root() -> Path:
    return Path.home() / ".qoder-cn" / "logs" / "runs"


def _parse_moment(raw: str) -> _dt.datetime:
    """`--liveness-at` 入参：带偏移的 ISO 直解；裸时间按本机时区补偏移。"""
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SystemExit(f"--liveness-at 不是可解析的 ISO 时间戳：{raw!r}") from exc
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--window-seconds",
        type=int,
        default=DEFAULT_WINDOW_SECONDS,
        help=f"第二栏（mtime 腿）窗口秒数（缺省 {DEFAULT_WINDOW_SECONDS}；"
        "只准显式加大＝如实记录更宽窗口；也是门腿 6 新鲜度上限 N）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="快照写盘路径（缺省 .superpowers/sdd/2026-09-22-taxonomy/DISPATCH-SNAPSHOT.json）",
    )
    parser.add_argument(
        "--projects-root",
        type=Path,
        default=None,
        help="qoder 会话记录根（缺省 ~/.qoder-cn/projects）",
    )
    parser.add_argument(
        "--logs-root",
        type=Path,
        default=None,
        help="qoder 席位台账根（缺省 ~/.qoder-cn/logs/runs；第一栏活性口径的取数面）",
    )
    parser.add_argument(
        "--liveness-at",
        default=None,
        metavar="ISO8601",
        help="只取证不写盘：按台账现算「该时刻在飞几席」（两栏并列打印，供历史对拍）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只现算并打印 JSON，不写盘（自证用；与门无关）",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="同一次调用内先重拍再判定（capture→write→judge），输出「拍的刻＋判的论」。"
        "不提供任何「跳过重拍、直接判旧件」的路径（P-52）。",
    )
    args = parser.parse_args(argv)
    if args.window_seconds <= 0:
        parser.error("--window-seconds 必须是正整数（门的形状腿同样要求 >0）")
    if args.verify and args.dry_run:
        parser.error(
            "--verify 与 --dry-run 冲突：验证必须写一份新鲜快照后判定，"
            "只算不写就只能退回判旧件（正被 P-52 禁止）"
        )
    projects_root = args.projects_root or (Path.home() / ".qoder-cn" / "projects")
    logs_root = args.logs_root or _default_logs_root()
    if args.liveness_at is not None:
        moment = _parse_moment(args.liveness_at)
        scan = scan_liveness(logs_root, projects_root, _REPO_ROOT)
        in_flight = in_flight_at(scan, moment)
        print(
            f"[liveness-at] 时刻={moment.isoformat()} 在飞席数={len(in_flight)}"
            f"（口径 {ACTIVE_SEATS_BASIS}；台账 {scan.log_files} 枚 qodercli.log）"
        )
        for agent_id in in_flight:
            print(f"[liveness-at]   在飞 agentId={agent_id} start={scan.started[agent_id].isoformat()}")
        return 0
    snapshot = build_snapshot(args.window_seconds, projects_root, _REPO_ROOT, logs_root)
    text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        sys.stdout.write(text)
        return 0
    atomic_write(args.output, text)
    if args.verify:
        now = _dt.datetime.now(_dt.timezone.utc)
        verdict = judge_snapshot(snapshot, now)
        print(
            f"[verify] 拍的刻 captured_at_utc={snapshot['captured_at_utc']} "
            f"window_seconds={snapshot['window_seconds']} "
            f"active_seats={snapshot['active_seats']}（在飞）"
            f" active_seats_mtime_window={snapshot['active_seats_mtime_window']}（旧口径） "
            f"-> {args.output}"
        )
        if verdict:
            for line in verdict:
                print(f"[verify] 判定=不合格：{line}")
            return 1
        print(
            "[verify] 判定=合格（形状 + 两栏并列 + 新鲜度；顶满与否由门 "
            "test_snapshot_active_seats_meet_ceiling 专属裁定，此处不建第二本账）"
        )
        return 0
    print(
        f"snapshot written: {args.output}\n"
        f"captured_at_utc={snapshot['captured_at_utc']} "
        f"window_seconds={snapshot['window_seconds']} "
        f"active_seats={snapshot['active_seats']}（在飞口径） "
        f"active_seats_mtime_window={snapshot['active_seats_mtime_window']}（旧 mtime 口径）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
