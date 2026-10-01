"""文案红线常驻门（2026-09-14，copy-audit + persona-trigger-audit 两席人工审计的固化）。

背景：文案审计席（.superpowers/sdd/2026-09-13-six-domain-batch/copy-audit-report.md）
与人格审计席（同目录 persona-trigger-audit.md）人工审计全净；用户铁律
「所有文本统一口径/风格/话术，前后不矛盾」+ 人格红线（不攻击/不强硬/不 R-18/
不愧疚话术）。本门把人工纪律固化为常驻 pytest 门，防未来批次回潮。

扫描范围：由「扫描面坐标」三组常量唯一派生（SCOPE_PY_GLOBS / SCOPE_ANCHOR_FILES /
SCOPE_PERSONA_GLOBS，逐条来历与 2026-09-25 S263 根修说明见其上方注释）——
capabilities 族（auto_send/ 子目录族已随 2026-09-28 垫片退役摘除，见下方退役断言）+ character 族 +
monitor 族锚点（2026-09-14 二次扩面，A69-I1）+ 已点名跟进的
domains/{schedule,chat_reply,ops} 三域 + 2026-09-25 S263 起按族派生的
domains/*/{capabilities,character,monitor} 真身族（其余 17 域的能力真身此前
整批不在面上）+ personas/**/*.md + personas/**/*.txt +
生产人格副本 ChatBot_Runtime/data/persona/守岸人_核心人格.md
（2026-09-14 三次扩面，人格矛盾修复批 G-08；扩面纪律=先修人格文本
G-01/G-02/G-03 再扩门，门绿为验收；副本缺失时优雅跳过并注明）。
面的只增不减由 test_gate_scope_coordinates_are_live + test_scan_surface_floor_is_live
执法；坐标失效不再被 exists() 静默吞掉。

扫描器：Python 文件走纯 AST + 字符串字面量（零 import 被扫模块）；人格资产
md/txt 无 AST，按「非空行 = 一个用户可见单元」逐行过同一套规则。用户可见字符串单元 =
普通串（解析器已合并相邻隐式拼接）+ f-string 字面量块（合并为单元）+ 纯常量
``+`` 链（合并为单元）。排除：注释（AST 天然排除）、日志调用（logger/log/
logging 及 getLogger 链的常见级别方法）、``audit_tags=`` 关键字、URL 串、
``re.*`` 正则模式（位置 0 参与任意调用的 ``pattern=`` 关键字；re.sub 的
repl/原文仍属用户可见面，不豁免）、docstring。面上任何一件读不动（语法破损等）
= 它等于没被扫过，由 test_scan_surface_is_parseable 点名执法，不在本门内做容忍。

规则分级：
- Critical（命中即红）：
  - banned_self_intro    「作为一个」AI 自述
  - banned_inconvenience 「给您带来不便」
                         （「您」单字维持组合词口径不入门，裁定注释见 BANNED_TERMS 上方）
  - banned_formal_apology「深表歉意」
  - apology_combo        「抱歉」+「为您」同单元组合（单独「抱歉」不红）
  - r18_terms            R-18 精确词表（10 词，见 R18_TERMS）
  - creator_name         「澜汐」/「霞月」在非豁免文件的用户可见文案出现
                         （addressing.py 内建豁免；其余按白名单豁免）
- Important（提示清单，warning 形态输出，不打红、不 flaky）：
  - emission_style       用户可见串以「拿不到/查不到/没找到」结尾的降级句尾
                         模式（暂无族统一口径之外的新句式，启发式）

白名单：tests/_redline_allowlist.py，按「规则 ID → 文件 → 理由」登记；
门测试校验白名单不腐化（规则 ID 存在、文件存在且在扫描范围内、理由非空）。
"""

from __future__ import annotations

import ast
import importlib.util
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PKG = REPO_ROOT / "plugins" / "bot_unified_runtime"
ALLOWLIST_PATH = Path(__file__).resolve().parent / "_redline_allowlist.py"
# 生产人格副本（仓库树外运行数据）：与 scripts/sync_persona_source.py 的
# DEFAULT_COPY_FALLBACK 同一口径——相对仓库上一级的确定性路径，不读 .env，
# 保证门在 CI（无 Runtime）下行为可预测：存在则入扫描面，缺失优雅跳过。
RUNTIME_COPY_PATH = (
    REPO_ROOT.parent / "ChatBot_Runtime" / "data" / "persona" / "守岸人_核心人格.md"
)
# 人格资产是 md/txt（无 AST），走按行扫描的文本路径。
_TEXT_SUFFIXES = frozenset({".md", ".txt"})

# ---------------------------------------------------------------------------
# 扫描面坐标（唯一真身：gate_scope() 与「坐标活性锁」共用同一份，不建第二本账）
#
# 2026-09-25 S263 根修说明（必读）：本波之前这道门的坐标里钉着四枚**盘上不存在**的
# 旧路径——capabilities/echo.py、character/addressing.py（断言侧两枚 pin）与
# runtime/usage_monitor.py、runtime/error_report.py（构造侧两枚 append）。构造侧那两枚
# 被 gate_scope() 末尾的 exists() 过滤**静默丢掉**，断言侧那两枚里只有恰好在跑的那条
# 会红，另一条与它同族的失效一概不响。真实代价不是「一行红」，而是 v21r2 域重组把
# 能力/人格/监控三族搬进 domains/<域>/ 之后，除当时点过名的 schedule / chat_reply /
# ops 三个域以外，其余 17 个域的能力真身（现算 41 个文件）**整批不在这道门的扫描面上**
# 而门照旧绿——文案红线（不攻击口径 / 守岸人语气 / R-18 词表 / 创造者双名）正是它守的。
#
# 三件事一起做的次序：①坐标改指真身；②族按 `domains/<域>/<层>` **派生**而不是逐域
# 点名（逐域点名必然随下一次重组过期，那正是本条红今天的来历）；③补一把活性锁
# test_gate_scope_coordinates_are_live——今后再钉一枚不存在的路径 / 匹配不到任何文件的
# 族，当场红，不再静默缩面。扫描面只增不减：旧路径的退役语义改到断言侧作证（不删）。
# ---------------------------------------------------------------------------

# RUNTIME_PKG 下的 Python 族（glob 形态，相对 RUNTIME_PKG）。
SCOPE_PY_GLOBS: tuple[str, ...] = (
    # 旧布局层：v21r2 重组后只余再导出垫片，仍留在面上（垫片文案同样用户可见）。
    "capabilities/*.py",
    # 2026-09-28 S-SHIM-WAVE1 T5：capabilities/auto_send/ 唯一垫片摘除、空目录随删，
    # 本族匹配 0 文件＝坐标活性锁红，故整族摘出；退役语义改到下方「退役断言」作证。
    "character/*.py",
    # 2026-09-18 起逐域点过名的三个域（覆盖面比单层族更宽：store/ data/ runtime/ 全含）。
    "domains/schedule/**/*.py",
    "domains/chat_reply/**/*.py",
    "domains/ops/**/*.py",
    # 2026-09-25 S263：按「族」派生补齐其余域的真身，杜绝逐域点名随重组再失效。
    "domains/*/capabilities/**/*.py",
    "domains/*/character/**/*.py",
    "domains/*/monitor/**/*.py",
)

# 必须真实存在且必须被扫到的锚点文件（相对 RUNTIME_PKG）。
SCOPE_ANCHOR_FILES: tuple[str, ...] = (
    # 2026-09-14 二次扩面原钉 runtime/usage_monitor.py 与 runtime/error_report.py，
    # 二者真身已迁 domains/ops/monitor/（S263 把坐标改指真身；旧路径退役在断言侧作证）。
    "domains/ops/monitor/usage_monitor.py",
    "domains/ops/monitor/error_report.py",
)

# 人格资产族（glob 形态，相对 REPO_ROOT）。
SCOPE_PERSONA_GLOBS: tuple[str, ...] = ("personas/**/*.md", "personas/**/*.txt")

# 能力族贡献下限：S263 扩面后现算 `domains/*/capabilities/**/*.py` 匹配 51（当时值）。
# 地板取 40 是刻意留出「垫片退役/模块合并」的正常波动，但整族从面上消失必红。
# 只准上调；确需下调由主会话裁定并在提交信息里写明理由，勿在本门内悄悄改小。
_CAPABILITY_FAMILY_FLOOR = 40

# ---------------------------------------------------------------------------
# 规则常量
# ---------------------------------------------------------------------------

# 「您」单字口径裁定（主会话 2026-09-14，裁定依据：persona 允许守岸人对陌生
# 用户使用敬称，属人格资产内的礼貌距离感而非违规客套话术）：敬称「您」不入
# 红线单字扫描——单字命中会大面积误伤正常敬语文案；红线只收组合词形态
# （现「给您带来不便」）。未来若要收紧须重新过审计席/主会话裁定，勿在本门
# 内悄悄改口径。
BANNED_TERMS: dict[str, tuple[str, ...]] = {
    "banned_self_intro": ("作为一个",),
    "banned_inconvenience": ("给您带来不便",),
    "banned_formal_apology": ("深表歉意",),
}

# R-18 精确词表（常用 10 词，故意 limited：宁漏勿误，扩词须过审计席）。
R18_TERMS: tuple[str, ...] = (
    "裸体",
    "做爱",
    "性爱",
    "口交",
    "肛交",
    "自慰",
    "乳交",
    "乱伦",
    "强奸",
    "内射",
)

CREATOR_NAMES: tuple[str, ...] = ("澜汐", "霞月")

# 创造者单名规则的内建豁免：称谓权威模块（规则定义即豁免，不占白名单）。
# 2026-09-18 v21r2 W15a 随真身扩面：addressing.py 真身迁 domains/chat_reply/character/，
# 旧路径标签保留（垫片期语义完整），canonical 标签同波新增。
CREATOR_NAME_BUILTIN_EXEMPT: frozenset[str] = frozenset(
    {
        "plugins/bot_unified_runtime/character/addressing.py",
        "plugins/bot_unified_runtime/domains/chat_reply/character/addressing.py",
    }
)

# Important 启发式：降级句尾新模式（允许集 = 「暂无…」「先不…数字」族之外）。
HEURISTIC_ENDINGS: tuple[str, ...] = ("拿不到", "查不到", "没找到")
# 句尾允许携带的收尾标点（rstrip 后再比对）。
_TAIL_PUNCT = "。！？!?\n\t …；;，,、」』）)"

KNOWN_RULES: frozenset[str] = frozenset(
    {
        *BANNED_TERMS.keys(),
        "apology_combo",
        "r18_terms",
        "creator_name",
        "emission_style",
    }
)

_URL_PREFIXES: tuple[str, ...] = (
    "http://",
    "https://",
    "file://",
    "ftp://",
    "ws://",
    "wss://",
    "data:",
    "www.",
)

_LOG_ATTRS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "fatal"}
)
_LOG_BASES = frozenset({"logger", "log", "logging", "LOGGER", "LOG"})
_REGEX_FUNCS = frozenset(
    {
        "compile",
        "match",
        "search",
        "fullmatch",
        "findall",
        "finditer",
        "sub",
        "subn",
        "split",
        "escape",
    }
)

# ---------------------------------------------------------------------------
# 扫描器（纯 AST，零 import 被扫模块）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    rule: str
    rel_path: str
    lineno: int
    excerpt: str
    level: str  # "critical" | "warning"

    def render(self) -> str:
        return f"[{self.level}] {self.rule} @ {self.rel_path}:{self.lineno}  {self.excerpt!r}"


@dataclass(frozen=True)
class _Unit:
    text: str
    lineno: int


def _is_logger_call(node: ast.Call) -> bool:
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in _LOG_ATTRS):
        return False
    base = func.value
    if isinstance(base, ast.Name) and base.id in _LOG_BASES:
        return True
    if isinstance(base, ast.Attribute) and base.attr in {"logger", "log"}:
        return True
    return (
        isinstance(base, ast.Call)
        and isinstance(base.func, ast.Attribute)
        and base.func.attr == "getLogger"
    )


def _excluded_subtree_roots(tree: ast.AST) -> set[int]:
    """需要整棵跳过的节点 id（日志调用、audit_tags/pattern 值、re.* 模式参）。"""
    excluded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _is_logger_call(node):
                excluded.add(id(node))
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "re"
                and func.attr in _REGEX_FUNCS
                and node.args
            ):
                # 只排除模式串本身（位置 0）；re.sub 的 repl/原文仍是用户可见面。
                excluded.add(id(node.args[0]))
            for kw in node.keywords:
                if kw.arg in {"audit_tags", "pattern"} and kw.value is not None:
                    excluded.add(id(kw.value))
    return excluded


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _flatten_static_concat(node: ast.AST) -> list[ast.AST] | None:
    """纯常量 ``+`` 链展开为叶子列表；链上含任何非静态节点则返回 None。"""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _flatten_static_concat(node.left)
        right = _flatten_static_concat(node.right)
        if left is None or right is None:
            return None
        return [*left, *right]
    if isinstance(node, (ast.Constant, ast.JoinedStr)):
        return [node]
    return None


class _UnitCollector(ast.NodeVisitor):
    """收集用户可见字符串单元；跳过排除子树与 docstring。"""

    def __init__(self, excluded: set[int], docstrings: set[int]) -> None:
        self._excluded = excluded
        self._docstrings = docstrings
        self.units: list[_Unit] = []

    def generic_visit(self, node: ast.AST) -> None:
        if id(node) in self._excluded:
            return
        super().generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        if id(node) in self._excluded:
            return
        chunks = [
            value.value
            for value in node.values
            if isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and id(value) not in self._docstrings
        ]
        if chunks:
            self.units.append(_Unit(text="".join(chunks), lineno=node.lineno))
        # FormattedValue 内嵌表达式继续下探（嵌套 f-string 属用户可见面）。
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                self.visit(value.value)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if id(node) in self._excluded:
            return
        if isinstance(node.op, ast.Add):
            leaves = _flatten_static_concat(node)
            if leaves is not None:
                texts = [
                    leaf.value
                    for leaf in leaves
                    if isinstance(leaf, ast.Constant)
                    and isinstance(leaf.value, str)
                    and id(leaf) not in self._docstrings
                ]
                # ≥2 段合并为一个 user-visible 单元；单段也照常登记。
                for text in texts:
                    self.units.append(_Unit(text="".join(texts) if len(texts) >= 2 else text, lineno=node.lineno))
                    if len(texts) >= 2:
                        break
                # f-string 叶子仍需下探其内嵌表达式。
                for leaf in leaves:
                    if isinstance(leaf, ast.JoinedStr):
                        self.visit(leaf)
                return
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if id(node) in self._excluded:
            return
        if isinstance(node.value, str) and id(node) not in self._docstrings:
            self.units.append(_Unit(text=node.value, lineno=node.lineno))


def _user_visible_units(path: Path) -> list[_Unit]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    collector = _UnitCollector(_excluded_subtree_roots(tree), _docstring_node_ids(tree))
    collector.visit(tree)
    return [u for u in collector.units if not u.text.lstrip().lower().startswith(_URL_PREFIXES)]


def _persona_text_units(path: Path) -> list[_Unit]:
    """人格资产（md/txt）无 AST：一行 = 一个用户可见单元，逐行过同一套规则。

    行号必须对齐原文（违例定位依赖它）；坏字节按 replace 容错——门只做
    红线检测，不承担人格资产的编码校验。
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [
        _Unit(text=line, lineno=idx)
        for idx, line in enumerate(lines, 1)
        if line.strip() and not line.lstrip().lower().startswith(_URL_PREFIXES)
    ]


def _excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:48] + ("…" if len(collapsed) > 48 else "")


def scan_file(path: Path, *, rel_path: str | None = None) -> tuple[list[Finding], list[Finding]]:
    """扫描单文件，返回 (critical 命中, warning 命中)。"""
    if rel_path is None:
        try:
            rel_path = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel_path = path.name
    assert rel_path is not None
    criticals: list[Finding] = []
    warns: list[Finding] = []

    def _mk(rule: str, level: str, text: str, lineno: int) -> Finding:
        return Finding(
            rule=rule,
            rel_path=rel_path or "",
            lineno=lineno,
            excerpt=_excerpt(text),
            level=level,
        )

    units = (
        _persona_text_units(path)
        if path.suffix.lower() in _TEXT_SUFFIXES
        else _user_visible_units(path)
    )
    for unit in units:
        text, lineno = unit.text, unit.lineno
        for rule, terms in BANNED_TERMS.items():
            if any(term in text for term in terms):
                criticals.append(_mk(rule, "critical", text, lineno))
        if "抱歉" in text and "为您" in text:
            criticals.append(_mk("apology_combo", "critical", text, lineno))
        if any(term in text for term in R18_TERMS):
            criticals.append(_mk("r18_terms", "critical", text, lineno))
        if any(name in text for name in CREATOR_NAMES) and rel_path not in CREATOR_NAME_BUILTIN_EXEMPT:
            criticals.append(_mk("creator_name", "critical", text, lineno))
        if text.strip(_TAIL_PUNCT).endswith(HEURISTIC_ENDINGS):
            warns.append(_mk("emission_style", "warning", text, lineno))
    return criticals, warns


def _load_allowlist() -> dict[str, dict[str, str]]:
    spec = importlib.util.spec_from_file_location("_redline_allowlist", ALLOWLIST_PATH)
    assert spec is not None and spec.loader is not None, f"白名单模块加载失败：{ALLOWLIST_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    allowlist = module.ALLOWLIST
    assert isinstance(allowlist, dict), "白名单必须为 dict"
    return cast("dict[str, dict[str, str]]", allowlist)


def _apply_allowlist(findings: list[Finding], allowlist: dict[str, dict[str, str]]) -> list[Finding]:
    kept: list[Finding] = []
    for finding in findings:
        exemptions = allowlist.get(finding.rule, {})
        if isinstance(exemptions, dict) and finding.rel_path in exemptions:
            continue
        kept.append(finding)
    return kept


def _scope_rel_paths(paths: list[Path]) -> set[str]:
    """扫描面的仓库相对路径集；仓库外文件（生产副本）不在白名单键域，跳过。"""
    rel: set[str] = set()
    for p in paths:
        try:
            rel.add(p.resolve().relative_to(REPO_ROOT).as_posix())
        except ValueError:
            continue
    return rel


def allowlist_problems(allowlist: dict[str, dict[str, str]], scope_rel_paths: set[str]) -> list[str]:
    """白名单腐化校验：未知规则 / 文件不存在 / 不在扫描范围 / 理由为空。"""
    problems: list[str] = []
    for rule, exemptions in allowlist.items():
        if rule not in KNOWN_RULES:
            problems.append(f"未知规则 ID：{rule}")
        if not isinstance(exemptions, dict):
            problems.append(f"规则 {rule} 的豁免表必须是 dict")
            continue
        for rel, reason in exemptions.items():
            if not (REPO_ROOT / rel).exists():
                problems.append(f"白名单指向不存在的文件：{rule} -> {rel}")
            elif rel not in scope_rel_paths:
                problems.append(f"白名单文件不在扫描范围内（假豁免）：{rule} -> {rel}")
            if not str(reason).strip():
                problems.append(f"白名单缺豁免理由：{rule} -> {rel}")
    return problems


def gate_scope() -> list[Path]:
    """任务口径扫描面：由 SCOPE_PY_GLOBS / SCOPE_ANCHOR_FILES / SCOPE_PERSONA_GLOBS
    三份坐标唯一派生（族与锚点的来历见文件头「扫描面坐标」注释）。

    personas/**/*.md + personas/**/*.txt（2026-09-14 三次扩面，G-08；扩面前已完成
    G-01/G-02/G-03 人格文本修复）+ 生产人格副本 RUNTIME_COPY_PATH（仓库外运行数据，
    缺失时按 CI 语义优雅跳过，由 test_gate_scope_sanity 显式注明）。

    末尾的 exists() 过滤只为「生产副本这一枚可选件」服务；锚点与族一旦失效**不该**
    在这里被静默吞掉——那份工由 test_gate_scope_coordinates_are_live 执法，
    本函数不重复做判断（判断有两处，就有一处会说谎）。"""
    files: list[Path] = []
    for pattern in SCOPE_PY_GLOBS:
        files.extend(sorted(RUNTIME_PKG.glob(pattern)))
    for rel in SCOPE_ANCHOR_FILES:
        files.append(RUNTIME_PKG / rel)
    for pattern in SCOPE_PERSONA_GLOBS:
        files.extend(sorted(REPO_ROOT.glob(pattern)))
    files.append(RUNTIME_COPY_PATH)
    return [f for f in files if f.exists()]


def scope_coordinate_problems(
    py_globs: tuple[str, ...],
    anchors: tuple[str, ...],
    persona_globs: tuple[str, ...],
) -> list[str]:
    """坐标活性体检（纯函数，返回问题清单不抛异常，便于注毒自证复用同一判据）。

    两种「钉了不存在的东西」都算问题，且都必须响：
    - 锚点文件不在盘上 → 该件今天根本没被扫（本波真实病灶）。
    - 族 glob 匹配 0 个文件 → 整族从面上消失（下一次重组就会踩到）。
    """
    problems: list[str] = []
    for pattern in (*py_globs, *persona_globs):
        anchor = RUNTIME_PKG if pattern in py_globs else REPO_ROOT
        if not any(anchor.glob(pattern)):
            problems.append(f"族坐标匹配 0 个文件（扫描面已静默缩没）：{pattern}")
    for rel in anchors:
        if not (RUNTIME_PKG / rel).exists():
            problems.append(f"锚点坐标指向不存在的文件：plugins/bot_unified_runtime/{rel}")
    return problems


def scan_scope(
    paths: list[Path], allowlist: dict[str, dict[str, str]] | None = None
) -> tuple[list[Finding], list[Finding]]:
    criticals: list[Finding] = []
    warns: list[Finding] = []
    for path in paths:
        c, w = scan_file(path)
        criticals.extend(c)
        warns.extend(w)
    if allowlist is not None:
        criticals = _apply_allowlist(criticals, allowlist)
        warns = _apply_allowlist(warns, allowlist)
    return criticals, warns


# ---------------------------------------------------------------------------
# 门测试：现网必须全绿
# ---------------------------------------------------------------------------


def test_gate_scope_sanity() -> None:
    scope = gate_scope()
    assert len(scope) >= 60, f"扫描面异常收缩：仅 {len(scope)} 个文件"
    # --- 2026-09-25 S263：两枚失效坐标改指真身（pin 数不减，只把路径换到盘上真有的件） ---
    # echo 真身在 domains/chat_reply/capabilities/（旧 capabilities/echo.py 已随域重组退役，
    # 其退役事实在下方「退役断言」里作证，不靠钉一条不存在的路径来记）。
    assert (RUNTIME_PKG / "domains" / "chat_reply" / "capabilities" / "echo.py") in scope
    assert (
        RUNTIME_PKG / "domains" / "chat_reply" / "character" / "addressing.py"
    ) in scope
    # 2026-09-18 v21r2 RWOC 随真身迁移：usage_monitor 真身迁 domains/ops/monitor/，
    # 旧路径 runtime/usage_monitor.py 已不存在（gate_scope 的 exists() 过滤即退役），pin 随迁。
    assert (RUNTIME_PKG / "domains" / "ops" / "monitor" / "usage_monitor.py") in scope
    assert (RUNTIME_PKG / "domains" / "ops" / "monitor" / "error_report.py") in scope
    # 2026-09-14 扩面的 capabilities/auto_send/__init__.py 垫片已于 2026-09-28
    # S-SHIM-WAVE1 T5 退役（存在 pin 随摘，退役断言在下方「退役断言」族作证）。
    # 2026-09-19：legacy capabilities/auto_send/parser.py 已随 v21r2 迁 schedule 域
    # （下方 schedule 域真身 pin 覆盖），旧路径 pin 退役。
    # 2026-09-18 v21r2 W10 随真身扩面：schedule 域真身在扫描面内（垫片不算数）。
    assert (RUNTIME_PKG / "domains" / "schedule" / "capabilities" / "reminder.py") in scope
    assert (RUNTIME_PKG / "domains" / "schedule" / "store" / "reminders.py") in scope
    assert (RUNTIME_PKG / "domains" / "schedule" / "auto_send" / "parser.py") in scope
    # 2026-09-18 v21r2 W15a 随真身扩面：chat_reply/character 真身在扫描面内（垫片不算数）。
    assert (
        RUNTIME_PKG / "domains" / "chat_reply" / "character" / "providers.py"
    ) in scope
    # --- 2026-09-25 S263 新纳入的「其余域能力真身族」必须有 pin，否则这一族又只是一句承诺 ---
    for newly_covered in (
        "domains/weather/capabilities/weather.py",
        "domains/finance/capabilities/fx.py",
        "domains/notes/capabilities/notes.py",
        "domains/media/capabilities/media_archive.py",
        "domains/emergency_info/capabilities/emergency_info.py",
    ):
        assert (RUNTIME_PKG / newly_covered) in scope, f"S263 扩面后新纳入的真身不在面上：{newly_covered}"
    # --- 退役断言（原为「钉住不存在路径」的 scope pin，按简报③挪到断言侧作证） ---
    # 语义：这些旧坐标是**历史路径**，钉在扫描面上只会造成静默缩面（见文件头注释）；
    # 它们该证明的是「旧布局确实不再有余留件」，那是断言侧的活，不是面上的活。
    for retired in (
        RUNTIME_PKG / "capabilities" / "echo.py",
        RUNTIME_PKG / "capabilities" / "auto_send" / "__init__.py",
        RUNTIME_PKG / "character" / "addressing.py",
        RUNTIME_PKG / "runtime" / "usage_monitor.py",
        RUNTIME_PKG / "runtime" / "error_report.py",
    ):
        assert not retired.exists(), f"旧布局路径复活（退役断言被打破，先查是谁把它写回来）：{retired}"
    # 2026-09-14 三次扩面（G-08）：人格资产入扫描面。
    assert (REPO_ROOT / "personas" / "shorekeeper" / "identity.md") in scope
    assert (
        REPO_ROOT / "personas" / "shorekeeper" / "knowledge" / "守岸人_核心知识.md"
    ) in scope
    if RUNTIME_COPY_PATH.exists():
        assert RUNTIME_COPY_PATH in scope
    else:
        warnings.warn(
            "生产人格副本不存在（CI 无 Runtime），副本扫描面优雅跳过并注明",
            stacklevel=1,
        )


def test_gate_scope_coordinates_are_live() -> None:
    """坐标活性锁（2026-09-25 S263 立）：钉不存在的路径＝静默缩面，从此当场红。

    本波根因不是「少扫了一个文件」而是「门不知道自己少扫了」——旧坐标被
    gate_scope() 的 exists() 过滤吞掉，主门照样绿。这条腿把「坐标必须真实可达」
    升成判据，并带两发注毒自证（失效锚点、空转族各一发），否则锁本身可能是假的。
    """
    problems = scope_coordinate_problems(SCOPE_PY_GLOBS, SCOPE_ANCHOR_FILES, SCOPE_PERSONA_GLOBS)
    assert not problems, "扫描面坐标失效（改指真身，别把判据放宽）：\n" + "\n".join(problems)

    # 注毒①：塞一枚不存在的锚点 → 必被点名（本波真实病灶的形态）。
    poisoned_anchor = scope_coordinate_problems(
        SCOPE_PY_GLOBS, (*SCOPE_ANCHOR_FILES, "runtime/usage_monitor.py"), SCOPE_PERSONA_GLOBS
    )
    assert len(poisoned_anchor) == 1 and "runtime/usage_monitor.py" in poisoned_anchor[0], (
        f"注毒未被抓住=锁是空跑：{poisoned_anchor}"
    )
    # 注毒②：塞一枚匹配不到任何文件的族 → 必被点名（整族静默消失的形态）。
    poisoned_glob = scope_coordinate_problems(
        (*SCOPE_PY_GLOBS, "domains/no_such_domain/**/*.py"), SCOPE_ANCHOR_FILES, SCOPE_PERSONA_GLOBS
    )
    assert len(poisoned_glob) == 1 and "no_such_domain" in poisoned_glob[0], (
        f"注毒未被抓住=锁是空跑：{poisoned_glob}"
    )


def test_scan_surface_floor_is_live() -> None:
    """只增不减的一腿：新纳入的能力真身族一旦整族掉出扫描面，本条红。

    地板值 _CAPABILITY_FAMILY_FLOOR 的含义与余量见其定义处注释。
    """
    scope = set(gate_scope())
    family = sorted(RUNTIME_PKG.glob("domains/*/capabilities/**/*.py"))
    on_surface = [p for p in family if p in scope]
    assert len(on_surface) >= _CAPABILITY_FAMILY_FLOOR, (
        f"能力真身族在扫描面上的贡献只剩 {len(on_surface)}（地板 {_CAPABILITY_FAMILY_FLOOR}）"
    )


def test_scan_surface_is_parseable() -> None:
    """面上每一件都必须真的读得动（2026-09-25 S263 立）。

    扩面把 41 枚新件拉进来，面越宽越可能被别席在飞的语法破损件顶到——先例见
    docs/design/v21r2-reorg-woc-log.md §七①（domains/ops/incident/service.py 硬
    SyntaxError 顶红当时新扩的 ops 面）。那条腿的做法是「让主门崩」，本条把它变成
    点名的断言：读不动=这件压根没被扫过=与「钉不存在路径」同一类假绿，必须红且报清是谁。
    """
    broken: list[str] = []
    for path in gate_scope():
        try:
            scan_file(path)
        except Exception as exc:  # noqa: BLE001 - 这里要的就是把任何读取失败点名收集
            broken.append(f"{path} → {type(exc).__name__}: {exc}")
    assert not broken, "扫描面存在读不动的件（它等于不在面上）：\n" + "\n".join(broken)


def test_newly_covered_family_is_actually_caught(tmp_path: Path) -> None:
    """杀伤力证明（只读生产件）：新纳入真身的**原文**加一条踩红线文案，门必红。

    写生产件不在本门的权限内，所以按「真身原文 + 注入行 → tmp 副本 + 真身 rel_path」
    过同一套扫描器：内容与语义路径都是真身的那一份，唯一变量是「有没有这一条」。
    再叠一条面上事实（真身确在 gate_scope() 里），两件事同时成立才等于「门会红」。
    注毒在 finally 之外（只写 tmp），因此不需要还原；生产件一次都没有被打开写过。
    """
    target_rel = "domains/weather/capabilities/weather.py"
    real = RUNTIME_PKG / target_rel
    assert real.exists() and real in set(gate_scope()), f"前置不成立：{target_rel} 不在扫描面上"
    rel_path = f"plugins/bot_unified_runtime/{target_rel}"
    # 先证现状干净（否则下面「命中」是既有的，不是注毒造成的）。
    base_criticals, _ = scan_file(real, rel_path=rel_path)
    assert not base_criticals, "真身现网已有命中，注毒证据会被既有红混淆：\n" + "\n".join(
        f.render() for f in base_criticals
    )
    poisoned = tmp_path / "weather_poisoned.py"
    poisoned.write_text(
        real.read_text(encoding="utf-8") + '\nS263_PROBE = "作为一个AI助手，对此深表歉意。"\n',
        encoding="utf-8",
    )
    criticals, _ = scan_file(poisoned, rel_path=rel_path)
    hit_rules = {f.rule for f in criticals}
    assert {"banned_self_intro", "banned_formal_apology"} <= hit_rules, (
        f"注毒未被抓住=新纳入的族只是名义在面上：{hit_rules}"
    )
    assert all(f.rel_path == rel_path for f in criticals)


def test_current_tree_no_critical_redline() -> None:
    """主门：现网树 Critical 红线必须零命中（白名单豁免后）。"""
    allowlist = _load_allowlist()
    criticals, _ = scan_scope(gate_scope(), allowlist)
    assert not criticals, "文案红线 Critical 命中（逐条核实：真违例派修/误报修规则）：\n" + "\n".join(
        f.render() for f in criticals
    )


def test_allowlist_integrity() -> None:
    """白名单不腐化：规则 ID 存在、文件存在且在扫描范围、理由非空。"""
    problems = allowlist_problems(_load_allowlist(), _scope_rel_paths(gate_scope()))
    assert not problems, "白名单腐化（失效豁免要清，不得留假豁免）：\n" + "\n".join(problems)


def test_emission_style_heuristic_is_warning_only() -> None:
    """Important 口径启发式：命中只出 warning 提示清单，不打红（防 flaky）。"""
    allowlist = _load_allowlist()
    criticals, warns = scan_scope(gate_scope(), allowlist)
    assert all(f.level == "critical" for f in criticals)
    assert all(f.rule == "emission_style" for f in warns)
    if warns:
        listing = "\n".join(f.render() for f in warns)
        warnings.warn(
            "文案口径 Important 提示清单（降级句尾新模式，人工复核后统一口径或登记白名单）：\n" + listing,
            stacklevel=1,
        )


# ---------------------------------------------------------------------------
# 扫描器负样本/正样本自测（tmp_path，构造假文件验证门真红/真绿/真豁免）
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, content: str, name: str = "sample.py") -> Path:
    target = tmp_path / name
    target.write_text(content, encoding="utf-8")
    return target


def test_dirty_self_intro_flagged(tmp_path: Path) -> None:
    file = _write(tmp_path, 'MSG = "作为一个AI助手，我很乐意帮您解决问题。"\n')
    criticals, _ = scan_file(file)
    assert "banned_self_intro" in {f.rule for f in criticals}


def test_dirty_inconvenience_flagged(tmp_path: Path) -> None:
    file = _write(tmp_path, 'MSG = "给您带来不便，敬请谅解。"\n')
    criticals, _ = scan_file(file)
    assert "banned_inconvenience" in {f.rule for f in criticals}


def test_dirty_formal_apology_flagged(tmp_path: Path) -> None:
    file = _write(tmp_path, 'MSG = "对此深表歉意。"\n')
    criticals, _ = scan_file(file)
    assert "banned_formal_apology" in {f.rule for f in criticals}


def test_apology_combo_flagged_same_literal_and_static_concat(tmp_path: Path) -> None:
    same = _write(tmp_path, 'MSG = "很抱歉，为您添麻烦了。"\n', name="same.py")
    assert "apology_combo" in {f.rule for f in scan_file(same)[0]}
    # 静态 ``+`` 拼接两段分写也要命中（同一 user-visible 单元）。
    split = _write(tmp_path, 'MSG = "很抱歉，" + "为您带来困扰。"\n', name="split.py")
    assert "apology_combo" in {f.rule for f in scan_file(split)[0]}
    # 反例：单独「抱歉」无「为您」不红（现网 chat.py 兜底话术族即此形态）。
    alone = _write(tmp_path, 'MSG = "抱歉，这次回应超时了。再发一次好吗。"\n', name="alone.py")
    assert not scan_file(alone)[0]


def test_apology_combo_flagged_in_fstring(tmp_path: Path) -> None:
    file = _write(tmp_path, 'def f(name):\n    return f"抱歉，{name}，为您带来了困扰。"\n')
    assert "apology_combo" in {finding.rule for finding in scan_file(file)[0]}


def test_r18_term_flagged(tmp_path: Path) -> None:
    file = _write(tmp_path, 'MSG = "口交事件调查进展。"\n')
    assert "r18_terms" in {f.rule for f in scan_file(file)[0]}


def test_creator_name_flagged_and_builtin_exempt(tmp_path: Path) -> None:
    file = _write(tmp_path, 'MSG = "这幅画是澜汐画的。"\n')
    criticals, _ = scan_file(file)
    assert "creator_name" in {f.rule for f in criticals}
    # 内建豁免：addressing.py 路径语义下不红（旧路径标签 + canonical 标签）。
    criticals_exempt, _ = scan_file(file, rel_path="plugins/bot_unified_runtime/character/addressing.py")
    assert not criticals_exempt
    criticals_canonical, _ = scan_file(
        file, rel_path="plugins/bot_unified_runtime/domains/chat_reply/character/addressing.py"
    )
    assert not criticals_canonical


def test_clean_file_zero_findings(tmp_path: Path) -> None:
    file = _write(
        tmp_path,
        '"""\n模块 docstring：即使提到 作为一个、深表歉意 也不算用户可见文案。\n"""\n'
        "import re\n\n"
        'PATTERN = re.compile(r"作为一个|深表歉意")\n'
        'MSG = "数据暂时拉不到，晚点再试试？"\n'
        'FALLBACK = "抱歉，这次回应超时了。再发一次好吗。"\n',
        name="clean.py",
    )
    criticals, warns = scan_file(file)
    assert not criticals
    assert not warns


def test_excluded_contexts_not_flagged(tmp_path: Path) -> None:
    file = _write(
        tmp_path,
        "import logging, re\n"
        "logger = logging.getLogger(__name__)\n"
        "\n"
        "def go(url):\n"
        '    logger.warning("深表歉意：作为一个 %s", url)  # 日志不属用户可见面\n'
        '    tags = build(audit_tags=["作为一个", "给您带来不便", "澜汐"])  # 审计标签\n'
        '    pat = re.compile(r"作为一个|给您带来不便|澜汐")  # 正则模式串\n'
        '    pat2 = re.compile(pattern=r"深表歉意")  # pattern 关键字形态\n'
        "    u = 'https://example.com/作为一个'  # URL\n"
        "    return u\n"
        "\n"
        "def build(**kw):\n"
        "    return kw\n",
        name="excluded.py",
    )
    criticals, warns = scan_file(file)
    assert not criticals, "\n".join(f.render() for f in criticals)
    assert not warns


def test_regex_sub_repl_still_scanned(tmp_path: Path) -> None:
    """re.sub 只豁免模式参，repl/原文仍是用户可见面（防豁免面过宽）。"""
    file = _write(tmp_path, 'import re\nOUT = re.sub(r"x", "深表歉意", "abc")\n')
    criticals, _ = scan_file(file)
    assert "banned_formal_apology" in {f.rule for f in criticals}


def test_heuristic_emission_style_warns(tmp_path: Path) -> None:
    file = _write(tmp_path, 'MSG = "金价数据查不到。"\n')
    criticals, warns = scan_file(file)
    assert not criticals, "启发式命中不许打红（Important 提示清单形态）"
    assert any(f.rule == "emission_style" for f in warns)
    # 句中提及不算句尾模式（image_search.py 等现网句中用法不误报）。
    mid = _write(tmp_path, 'MSG = "引用消息里的原图链接拿不到，把图片和『搜图』发在同一条消息里再试一次。"\n')
    _, warns_mid = scan_file(mid)
    assert not warns_mid


def test_allowlist_suppression_and_stale_entry(tmp_path: Path) -> None:
    file = _write(tmp_path, 'MSG = "这幅画是霞月画的。"\n')
    # scan_file 对 REPO_ROOT 外的 tmp 文件回退用文件名作 rel_path，白名单按它登记。
    rel = "sample.py"
    # 白名单生效：登记后豁免。
    suppressed, _ = scan_scope([file], {"creator_name": {rel: "测试豁免"}})
    assert not suppressed
    # 未登记则真红。
    raw, _ = scan_scope([file], {})
    assert [f.rule for f in raw] == ["creator_name"]
    # 白名单腐化：指向不存在文件必须红（与 test_allowlist_integrity 同源逻辑）。
    problems = allowlist_problems(
        {"creator_name": {"plugins/bot_unified_runtime/no_such_file.py": "过期豁免"}},
        _scope_rel_paths(gate_scope()),
    )
    assert len(problems) == 1 and "不存在" in problems[0]


# ---------------------------------------------------------------------------
# 2026-09-14 扩面：capabilities/auto_send/ 子目录（假文件样本挂该目录语义
# rel_path，验证门在新目录下同样真红/真绿；现网该目录实际 0 命中）
# ---------------------------------------------------------------------------

_AUTO_SEND_REL = "plugins/bot_unified_runtime/capabilities/auto_send/parser.py"


def test_auto_send_scope_expanded_current_tree_green() -> None:
    """真绿：扩面后现网 auto_send/ 全家（垫片+schedule 域真身）零 Critical
    （扩面前预扫亦 0 命中；2026-09-19 真身迁 domains/schedule/auto_send/ 后
    扫描面=垫片目录+真身目录并集）。"""
    auto_files = sorted((RUNTIME_PKG / "capabilities" / "auto_send").glob("*.py")) + sorted(
        (RUNTIME_PKG / "domains" / "schedule" / "auto_send").glob("*.py")
    )
    assert len(auto_files) >= 2, "auto_send/ 扫描面异常收缩，真身或已漂移"
    criticals, _ = scan_scope(auto_files, _load_allowlist())
    assert not criticals


def test_auto_send_dirty_samples_flagged(tmp_path: Path) -> None:
    """真红：违例藏在 auto_send 语义路径下同样命中，不因扩面产生新豁免区。"""
    banned = _write(tmp_path, 'MSG = "作为一个AI助手，给您带来不便，敬请谅解。"\n')
    rules = {f.rule for f in scan_file(banned, rel_path=_AUTO_SEND_REL)[0]}
    assert {"banned_self_intro", "banned_inconvenience"} <= rules
    combo = _write(tmp_path, 'def f(u):\n    return f"很抱歉，{u}，为您添麻烦了。"\n', name="combo.py")
    assert "apology_combo" in {f.rule for f in scan_file(combo, rel_path=_AUTO_SEND_REL)[0]}
    creator = _write(tmp_path, 'MSG = "这件事由澜汐安排。"\n', name="creator.py")
    assert "creator_name" in {f.rule for f in scan_file(creator, rel_path=_AUTO_SEND_REL)[0]}


def test_auto_send_clean_sample_zero_findings(tmp_path: Path) -> None:
    """真绿：豁免面（指令正则/audit_tags/日志/docstring）在 auto_send 语义下不误报。"""
    file = _write(
        tmp_path,
        '"""\ndocstring 提到 作为一个、澜汐 不算用户可见文案。\n"""\n'
        "import logging, re\n"
        "logger = logging.getLogger(__name__)\n"
        '_RE = re.compile(r"报存|報存|作为一个|澜汐")  # 指令正则模式串\n'
        'TAGS = build(audit_tags=["auto_send_preview"])  # 审计标签\n'
        'logger.info("深表歉意：重试 %s", 1)  # 日志面\n'
        'MSG = "草稿预览（仅预览，不会真实发送）"\n'
        "\n"
        "def build(**kw):\n"
        "    return kw\n",
        name="clean_auto.py",
    )
    criticals, warns = scan_file(file, rel_path=_AUTO_SEND_REL)
    assert not criticals, "\n".join(f.render() for f in criticals)
    assert not warns


# ---------------------------------------------------------------------------
# 2026-09-14 三次扩面（G-08）：人格资产（personas/** + 生产副本）入扫描面。
# 人格文件是 md/txt（无 AST），按行扫描的文本路径需独立真红/真绿验证；
# 扩面纪律=先修人格文本（G-01/G-02/G-03）再扩门，门绿为验收。
# ---------------------------------------------------------------------------

_PERSONA_MD_REL = "personas/shorekeeper/identity.md"


def test_persona_text_dirty_lines_flagged(tmp_path: Path) -> None:
    """真红：人格 md 里的违例行按行命中（文本路径与 AST 路径同一套规则）。"""
    banned = _write(tmp_path, "# 守岸人\n\n作为一个AI助手，我来帮你。", name="persona.md")
    criticals, _ = scan_file(banned)
    assert "banned_self_intro" in {f.rule for f in criticals}
    combo = _write(tmp_path, "很抱歉，为您添麻烦了。", name="combo.md")
    assert "apology_combo" in {f.rule for f in scan_file(combo)[0]}
    r18 = _write(tmp_path, "这段内容包含内射描写。", name="r18.md")
    assert "r18_terms" in {f.rule for f in scan_file(r18)[0]}


def test_persona_text_dirty_hit_reports_source_lineno(tmp_path: Path) -> None:
    """行号必须对齐原文：人格违例定位靠它，错行号=门不可用。"""
    file = _write(tmp_path, "第一行\n第二行\n作为一个AI助手，不该出现。\n", name="lineno.md")
    criticals, _ = scan_file(file)
    assert len(criticals) == 1 and criticals[0].lineno == 3


def test_persona_text_clean_lines_zero_findings(tmp_path: Path) -> None:
    """真绿：人格 md 正常话术（含边界说明例句）零命中，不误伤守岸人语气。"""
    file = _write(
        tmp_path,
        "# 守岸人\n\n海潮正平稳。这句先不继续了，我们说点别的，好吗？\n",
        name="clean.md",
    )
    criticals, warns = scan_file(file)
    assert not criticals
    assert not warns


def test_persona_semantic_path_dirty_sample_flagged(tmp_path: Path) -> None:
    """真红：违例藏在人格语义路径下同样命中，不因扩面产生新豁免区。"""
    banned = _write(tmp_path, "作为一个AI助手，给您带来不便，敬请谅解。", name="dirty.md")
    rules = {f.rule for f in scan_file(banned, rel_path=_PERSONA_MD_REL)[0]}
    assert {"banned_self_intro", "banned_inconvenience"} <= rules


def test_persona_scope_expanded_current_tree_green() -> None:
    """真绿：扩面后 personas/** 全量 Critical 零命中（白名单豁免后）。

    创造者双名（澜汐/霞月）是 identity.md §1.3 稳定世界观事实，属人格档案
    本体而非用户可见文案泄漏，按白名单登记豁免（理由见 _redline_allowlist.py）。
    """
    persona_files = sorted(REPO_ROOT.glob("personas/**/*.md")) + sorted(
        REPO_ROOT.glob("personas/**/*.txt")
    )
    assert len(persona_files) >= 4, "personas/ 扫描面异常收缩"
    criticals, _ = scan_scope(persona_files, _load_allowlist())
    assert not criticals, "人格源 Critical 红线命中：\n" + "\n".join(
        f.render() for f in criticals
    )


def test_runtime_copy_scanned_when_present() -> None:
    """真绿 + 跳过语义：副本存在则必扫且零 Critical；缺失（CI 无 Runtime）跳过并注明。"""
    if not RUNTIME_COPY_PATH.exists():
        pytest.skip("生产人格副本不存在（CI 无 Runtime），优雅跳过并注明")
    criticals, _ = scan_scope([RUNTIME_COPY_PATH], _load_allowlist())
    assert not criticals, "生产人格副本 Critical 红线命中：\n" + "\n".join(
        f.render() for f in criticals
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
