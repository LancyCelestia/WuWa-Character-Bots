"""A/B 红集分桶器（守岸人 ChatBot 修复波 2026-10-02，席 BKT）。

用途
----
读两份 pytest ``-q --tb=no -rf`` 输出文本，逐行提取 FAILED node ID，
按「函数级 / 参数级」两档归一（参数化尾巴 ``[xxx]`` 剥掉后比函数级键，
报告仍逐枚点名参数级原貌）后分三桶：

- ``NEW_ONLY``：只在 B 出现＝净新增红（退出码 1 的判据，逐枚点名）；
- ``GONE_ONLY``：只在 A 出现＝转绿；
- ``COMMON``：两边都有＝既存红。

退出码：NEW_ONLY 空 ⇒ 0；非空 ⇒ 1（终门机读口）。
只依赖标准库；node ID 提取抗折行：FAILED 行被折到下一行的连续段
（含折点在 FAILED 关键字后 / ``-`` 分隔符前 / node ID token 中段三种）
会归并回同一条目后再切；ID 取 ``FAILED `` 与首个 `` - `` 之间整段
（含空格的参数化尾巴不腰斩——2026-10-02 傍窗主会话修，SPC 实测三失效形态）。

两份输入的生成命令（A/B 必须同 venv 同尺；卫生前缀全文照抄）
---------------------------------------------------------------
B 轴（工作树，仓库内跑）::

    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
      ChatBot_Runtime/venv/Scripts/python.exe -m pytest -p no:cacheprovider \
      --basetemp=<仓库外路径>/bt-b -q --tb=no -rf \
      > <仓库外路径>/b_worktree.txt 2>&1

A 轴（HEAD 轴：``git archive HEAD`` 抽到仓库外同尺复跑，台账 #68）::

    mkdir <仓库外路径>/head-axis && git archive HEAD | tar -x -C <仓库外路径>/head-axis
    cd <仓库外路径>/head-axis && PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
      <绝对路径>/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
      -p no:cacheprovider --basetemp=<仓库外路径>/bt-a -q --tb=no -rf \
      > <仓库外路径>/a_head.txt 2>&1

用法
----
    python scripts/ab_red_bucket.py A_HEAD.txt B_WORKTREE.txt [--json OUT.json]

已知边界：真机 pytest 9.1.1（本仓 venv）在重定向下短摘要行**不折行**而是
超宽省略消息（``_format_trimmed``，probe 实证）；真折行发生在 CI 环境变量
在场或 ``-vv`` 时（多行 reprcrash message 整段接行后）。归并逻辑两种都能吃；
折点恰好把 node ID 尾段切在「数字开头 + 空格」处属于病态输入，不保证。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ANSI 色码（FORCE_COLOR / --color=yes 留下的痕迹）一律剥掉再判。
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# 条目关键字行（既是一条新条目，也是上一条目的硬终止符）。
_KEYWORD = re.compile(r"^(?:FAILED|ERROR|XFAIL|XPASS|SKIP|SKIPPED|PASSED|WARNING)\b")
# ``-q`` 模式的收尾计数行是裸行（probe 实证：``2 failed in 0.01s`` 不带横幅）。
_COUNT_LINE = re.compile(
    r"^\d+\s+(?:failed|passed|error|errors|skipped|xfailed|xpassed"
    r"|warning|warnings|deselected)\b"
)
# 分节横幅 / 分隔线（只由 = - ~ _ 组成的长串）。
_BANNER = re.compile(r"^[=\-~_]{4,}$")
# FAILED 条目起点：关键字后必须接行尾或空白。
_ENTRY = re.compile(r"^FAILED(?:\s|$)")
# 裸 node ID 清单行（无 FAILED 关键字的排序清单，如 BASE 轴交付物）：
# 以在册目录起头且含 ``::`` 即认条目（红集清单是本工具的合法第二输入形态）。
_BARE_NODEID = re.compile(r"^(?:tests|plugins|scripts)/.*::\S")
_SECTION_MARK = "short test summary info"
# 参数化尾巴：结尾一串 ``[...]`` 组（函数级键 = 整段剥掉）。
_PARAM_TAIL = re.compile(r"(?:\[[^\[\]]*\])+$")


@dataclass(frozen=True)
class Entry:
    """一个函数级键及其参数级原貌（保序去重）。"""

    function: str
    params: tuple[str, ...]


@dataclass(frozen=True)
class BucketResult:
    """三桶：new_only 只在 B（净新增红）、gone_only 只在 A、common 两边共有。"""

    new_only: tuple[Entry, ...]
    gone_only: tuple[Entry, ...]
    common: tuple[Entry, ...]


def _summary_scope(lines: list[str]) -> list[str]:
    """优先取 ``short test summary info`` 分节体；整份日志缺横幅时退回全文。"""
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if _SECTION_MARK in stripped and stripped.startswith("="):
            scope: list[str] = []
            for line in lines[i + 1 :]:
                if _BANNER.match(line.strip()):
                    break
                scope.append(line)
            return scope
    return lines


def _merge(prev: str, cont: str) -> str:
    """把折行续段并回条目。

    - 上一行只剩关键字（折点在 ``FAILED`` 后）⇒ 空格接，防止粘成 ``FAILEDxxx``；
    - 续行以 ``- `` 开头（折点在 `` - `` 分隔符前）⇒ 空格接；
    - 其余（折点在 node ID token 中段 / 消息内）⇒ 直接拼还原 token。
    消息侧 token 被粘连不影响结论：node ID 只取合并后的第 2 个空白分隔 token。
    """
    if len(prev.split()) <= 1 or cont.startswith("- "):
        return prev + " " + cont
    return prev + cont


def _flush(pending: str | None, found: list[str], seen: set[str]) -> None:
    if pending is None:
        return
    # node ID = ``FAILED `` 之后、首个 `` - `` 分隔符之前的整段（pytest 短摘要
    # 格式 ``FAILED <nodeid> - <crash message>``）。**不许按空白切第 2 个
    # token**：参数化尾巴可含空格（实测 HEAD 红集
    # ``…[J9 gallery_empty 乱贴]``），按空白切会把 ID 腰斩在首个空格——桶位
    # 碰巧不坏但原貌破，且同前缀异参数会塌成假 COMMON 吞真红（SPC 实测三失效形态）。
    # 消息缺席（裸 ``FAILED <nodeid>``）时整段即 ID。nodeid 内含 `` - `` 的
    # 病态输入不保证（与 pytest 自身摘要格式的歧义同界）。
    body = pending[len("FAILED"):].strip()
    nodeid = body.split(" - ", 1)[0].strip()
    if nodeid and nodeid not in seen:
        seen.add(nodeid)
        found.append(nodeid)


def extract_failed_nodeids(text: str) -> list[str]:
    """从一段 pytest 输出文本提取全部 FAILED node ID（参数级，保序去重）。"""
    found: list[str] = []
    seen: set[str] = set()
    pending: str | None = None
    for raw in _summary_scope(text.splitlines()):
        stripped = _ANSI.sub("", raw).strip()
        if not stripped:
            _flush(pending, found, seen)
            pending = None
            continue
        if _BANNER.match(stripped) or _COUNT_LINE.match(stripped) or _KEYWORD.match(
            stripped
        ):
            _flush(pending, found, seen)
            pending = None
            if _ENTRY.match(stripped):
                pending = stripped
            continue
        if pending is None:
            if _ENTRY.match(stripped):
                pending = stripped
            elif _BARE_NODEID.match(stripped):
                _flush("FAILED " + stripped, found, seen)
            continue
        pending = _merge(pending, stripped)
    _flush(pending, found, seen)
    return found


def function_level(nodeid: str) -> str:
    """参数级 → 函数级：剥掉结尾一串 ``[...]``（无尾巴则原样返回）。"""
    stripped = _PARAM_TAIL.sub("", nodeid)
    return stripped if stripped else nodeid


def _group(text: str) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for nodeid in extract_failed_nodeids(text):
        grouped.setdefault(function_level(nodeid), []).append(nodeid)
    return {k: tuple(dict.fromkeys(v)) for k, v in grouped.items()}


def bucket(a_text: str, b_text: str) -> BucketResult:
    """A/B 两份红集文本 → 三桶。匹配在函数级归一，点名在参数级原貌。"""
    a, b = _group(a_text), _group(b_text)
    new_only = tuple(Entry(k, b[k]) for k in b if k not in a)
    gone_only = tuple(Entry(k, a[k]) for k in a if k not in b)
    common = tuple(
        Entry(
            k,
            tuple(dict.fromkeys(list(b[k]) + [p for p in a[k] if p not in b[k]])),
        )
        for k in b
        if k in a
    )
    return BucketResult(new_only=new_only, gone_only=gone_only, common=common)


def render_report(result: BucketResult, a_label: str, b_label: str) -> str:
    """人读报告：三桶逐枚点名（参数级原貌），桶空标（空）。"""
    out: list[str] = [f"A 轴（HEAD）＝{a_label}", f"B 轴（工作树）＝{b_label}"]
    sections = (
        ("NEW_ONLY", "只在 B＝净新增红", result.new_only),
        ("GONE_ONLY", "只在 A＝转绿", result.gone_only),
        ("COMMON", "两边共有＝既存红", result.common),
    )
    for name, gloss, entries in sections:
        out.append(f"== {name}（{gloss}）n={len(entries)} ==")
        if not entries:
            out.append("  （空）")
        for entry in entries:
            out.append(f"  {entry.function}")
            for param in entry.params:
                out.append(f"    - {param}")
    verdict = 1 if result.new_only else 0
    out.append(f"== 判定：NEW_ONLY={len(result.new_only)} ⇒ 退出码 {verdict} ==")
    return "\n".join(out) + "\n"


def _payload(result: BucketResult, a_label: str, b_label: str) -> dict:
    def entry(e: Entry) -> dict:
        return {"function": e.function, "params": list(e.params)}

    return {
        "a_source": a_label,
        "b_source": b_label,
        "new_only": [entry(e) for e in result.new_only],
        "gone_only": [entry(e) for e in result.gone_only],
        "common": [entry(e) for e in result.common],
        "counts": {
            "new_only": len(result.new_only),
            "gone_only": len(result.gone_only),
            "common": len(result.common),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 入口；返回值即进程退出码（终门机读口）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # 非 TextIO 或句柄不可重配时静默降级
        pass
    parser = argparse.ArgumentParser(
        description="A/B 红集分桶器：HEAD 轴 vs 工作树轴 FAILED 集合三桶对比。",
        epilog="生成两份输入的命令（含卫生前缀全文）见本文件头部 docstring。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("a_head", help="A 轴红集文本（HEAD 轴 pytest -q --tb=no -rf 输出）")
    parser.add_argument("b_worktree", help="B 轴红集文本（工作树轴同尺输出）")
    parser.add_argument("--json", metavar="OUT", help="把三桶结构化结果写到 OUT（UTF-8 JSON）")
    args = parser.parse_args(argv)

    a_text = Path(args.a_head).read_text(encoding="utf-8", errors="replace")
    b_text = Path(args.b_worktree).read_text(encoding="utf-8", errors="replace")
    result = bucket(a_text, b_text)
    print(render_report(result, args.a_head, args.b_worktree), end="")
    if args.json:
        Path(args.json).write_text(
            json.dumps(_payload(result, args.a_head, args.b_worktree),
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON 已写出：{args.json}")
    return 1 if result.new_only else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
