"""文案同构普查器（只读，只打 stdout；SEAT-S-COPY 交付物 B 的扫描真身）。

被 tests/test_copy_single_source.py 以 importlib 按路径加载——扫描逻辑只有一份。
判据：AST 收「像人话」的字符串单元（剪枝口径同 tests/test_copy_redline_gate.py：
docstring / 日志调用 / 正则 pattern / URL 不算），归一化（NFKC 收全半角、
占位符折成 {}、去标点空白、小写）后，同一形态出现在 >=2 个文件即成一簇。

用法：python scripts/copy_duplication_census.py [--min-len N] [--forks]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

# 入簇门槛：归一化后 >=12 字（短句级），或带句末标点且 >=6 字。
CLUSTER_MIN_NORM_LEN = 12
SENTENCE_MIN_NORM_LEN = 6

# 与 tests/test_copy_redline_gate.py 同一套「什么算用户可见单元」的剪枝口径。
_LOG_ATTRS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "fatal"}
)
_LOG_BASES = frozenset({"logger", "log", "logging", "LOGGER", "LOG"})
_REGEX_FUNCS = frozenset(
    {"compile", "match", "search", "fullmatch", "split", "findall", "finditer", "sub", "subn"}
)
_URL_PREFIXES = ("http://", "https://", "file://", "ftp://", "ws://", "wss://", "data:", "www.")
_SKIP_KEYWORDS = frozenset({"audit_tags", "tags", "extra", "exc_info"})
_SENTENCE_ENDINGS = ("。", "！", "？", "!", "?", "；", ";")

_PUNCT_RE = re.compile(r"[，,。.、；;：:！!？?\"'“”‘’（）()【】\[\]《》<>…—\-~～_+/|*`@#^\s]+")
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")
_CJK_RE = re.compile(r"[㐀-䶿一-鿿]")


def normalize(text: str) -> str:
    """归一化：NFKC（收全半角）→ 占位符折成 {} → 去标点空白 → 小写。"""
    folded = unicodedata.normalize("NFKC", text)
    folded = _PLACEHOLDER_RE.sub("\x00", folded)
    folded = _PUNCT_RE.sub("", folded)
    return folded.replace("\x00", "{}").lower()


def looks_like_user_copy(text: str) -> bool:
    """含汉字、非 URL、非纯占位符——才算一句人话（其余是标识符/键名）。"""
    if not _CJK_RE.search(text):
        return False
    if text.startswith(_URL_PREFIXES):
        return False
    return not _PLACEHOLDER_RE.fullmatch(text.strip())


@dataclass(frozen=True)
class Unit:
    path: str
    lineno: int
    raw: str
    norm: str

    @property
    def is_sentence(self) -> bool:
        return self.raw.rstrip().endswith(_SENTENCE_ENDINGS)


@dataclass
class Cluster:
    norm: str
    units: list[Unit] = field(default_factory=list)

    @property
    def key(self) -> str:
        return hashlib.sha256(self.norm.encode("utf-8")).hexdigest()[:12]

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(sorted({u.path for u in self.units}))

    def render_sample(self, width: int = 34) -> str:
        longest = max(self.units, key=lambda u: len(u.raw))
        return " ".join(longest.raw.split())[:width]


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _skip_subtree_ids(tree: ast.AST) -> set[int]:
    """日志调用整棵 / re.<函数> 的 pattern 实参 / 审计标签关键字实参剪掉。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            base = func.value
            is_logger = func.attr in _LOG_ATTRS and (
                (isinstance(base, ast.Name) and base.id in _LOG_BASES)
                or (isinstance(base, ast.Attribute) and base.attr in {"logger", "log"})
            )
            is_regex = isinstance(base, ast.Name) and base.id == "re" and func.attr in _REGEX_FUNCS
            if is_logger:
                ids.add(id(node))
                continue
            if is_regex:
                # 只剪 pattern 位（sub/subn 的 repl 仍是用户可见面）。
                if node.args:
                    ids.add(id(node.args[0]))
                for kw in node.keywords:
                    if kw.arg == "pattern":
                        ids.add(id(kw.value))
        for kw in node.keywords:
            if kw.arg in _SKIP_KEYWORDS:
                ids.add(id(kw.value))
    return ids


def _flatten_concat(node: ast.AST) -> str | None:
    """纯字符串常量 + 链合并为单单元（口径同 test_copy_redline_gate）。"""
    parts: list[str] = []

    def walk(cur: ast.AST) -> bool:
        if isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Add):
            return walk(cur.left) and walk(cur.right)
        if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
            parts.append(cur.value)
            return True
        return False

    return "".join(parts) if walk(node) and len(parts) > 1 else None


class _Collector(ast.NodeVisitor):
    """收集用户可见字符串单元：普通串 + f-string 字面量块 + 常量 + 链。"""

    def __init__(self, skips: set[int], docstrings: set[int], path: str) -> None:
        self._skips = skips
        self._docs = docstrings
        self._path = path
        self.units: list[Unit] = []

    def _emit(self, text: str, lineno: int) -> None:
        if not looks_like_user_copy(text):
            return
        norm = normalize(text)
        if len(norm) >= SENTENCE_MIN_NORM_LEN:
            self.units.append(Unit(self._path, lineno, text, norm))

    def _skipped(self, node: ast.AST) -> bool:
        return id(node) in self._skips

    def generic_visit(self, node: ast.AST) -> None:
        if self._skipped(node):
            return
        super().generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and id(node) not in self._docs and not self._skipped(node):
            self._emit(node.value, node.lineno)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        if self._skipped(node):
            return
        chunks = [
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        ]
        if chunks:
            self._emit("".join(chunks), node.lineno)
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                self.visit(value.value)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if self._skipped(node):
            return
        joined = _flatten_concat(node)
        if joined is not None:
            self._emit(joined, node.lineno)
            return
        self.generic_visit(node)


def qualifies(unit: Unit, min_len: int = CLUSTER_MIN_NORM_LEN) -> bool:
    """够长的短语，或带句末标点的短句（短标签的重复用是词汇复用，非文案同构）。"""
    return len(unit.norm) >= min_len or (
        unit.is_sentence and len(unit.norm) >= SENTENCE_MIN_NORM_LEN
    )


def scan_tree() -> list[Unit]:
    units: list[Unit] = []
    for path in sorted(SCAN_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - 语法错归静态门管
            continue
        rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        collector = _Collector(_skip_subtree_ids(tree), _docstring_ids(tree), rel)
        collector.visit(tree)
        units.extend(collector.units)
    return units


def cluster_units(units: list[Unit], min_len: int = CLUSTER_MIN_NORM_LEN) -> list[Cluster]:
    buckets: dict[str, list[Unit]] = defaultdict(list)
    for unit in units:
        if qualifies(unit, min_len):
            buckets[unit.norm].append(unit)
    clusters = [
        Cluster(norm=norm, units=members)
        for norm, members in buckets.items()
        if len({m.path for m in members}) >= 2
    ]
    return sorted(clusters, key=lambda c: (-len(c.files), c.norm))


def fork_pairs(clusters: list[Cluster], min_prefix: int = 10) -> list[tuple[Cluster, Cluster]]:
    """口径分叉：一簇文案是另一簇的前缀、且两簇共享文件——同一处两套措辞。"""
    forks: list[tuple[Cluster, Cluster]] = []
    for short in clusters:
        if len(short.norm) < min_prefix:
            continue
        for long in clusters:
            if long.norm == short.norm or not long.norm.startswith(short.norm):
                continue
            if set(long.files) & set(short.files):
                forks.append((short, long))
    return sorted(forks, key=lambda pair: (pair[0].norm, pair[1].norm))


def render_census(min_len: int = CLUSTER_MIN_NORM_LEN) -> str:
    units = scan_tree()
    clusters = cluster_units(units, min_len)
    lines = [
        f"扫描根：{SCAN_ROOT.relative_to(REPO_ROOT).as_posix()}/**.py",
        (
            f"候选用户可见单元（归一化 >= {SENTENCE_MIN_NORM_LEN} 字）：{len(units)}；"
            f"入簇门槛：>= {min_len} 字或带句末标点"
        ),
        f"跨模块近重复簇（同归一化文案 >=2 文件）：{len(clusters)}",
        "",
    ]
    for idx, cluster in enumerate(clusters, 1):
        lines.append(
            f"[{idx:03d}] key={cluster.key} files={len(cluster.files)} "
            f"units={len(cluster.units)} | {cluster.render_sample()!r}"
        )
        for unit in sorted(cluster.units, key=lambda u: (u.path, u.lineno)):
            lines.append(f"      - {unit.path}:{unit.lineno}  {unit.raw[:78]!r}")
        lines.append("")
    return "\n".join(lines)


def render_forks(min_len: int = CLUSTER_MIN_NORM_LEN) -> str:
    clusters = cluster_units(scan_tree(), min_len)
    forks = fork_pairs(clusters)
    lines = [f"口径分叉对（同前缀 + 共享文件 + 两套措辞）：{len(forks)}", ""]
    for short, long in forks:
        lines.append(f"- 短 key={short.key} {short.render_sample(46)!r}")
        lines.append(f"  长 key={long.key} {long.render_sample(46)!r}")
        for unit in sorted(short.units, key=lambda u: (u.path, u.lineno)):
            lines.append(f"    短 {unit.path}:{unit.lineno}")
        for unit in sorted(long.units, key=lambda u: (u.path, u.lineno)):
            lines.append(f"    长 {unit.path}:{unit.lineno}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-len", type=int, default=CLUSTER_MIN_NORM_LEN)
    parser.add_argument("--forks", action="store_true", help="只打口径分叉对")
    args = parser.parse_args(argv)
    print(render_forks(args.min_len) if args.forks else render_census(args.min_len))
    return 0


if __name__ == "__main__":
    sys.exit(main())
