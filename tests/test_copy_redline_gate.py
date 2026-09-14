"""文案红线常驻门（2026-09-14，copy-audit + persona-trigger-audit 两席人工审计的固化）。

背景：文案审计席（.superpowers/sdd/2026-09-13-six-domain-batch/copy-audit-report.md）
与人格审计席（同目录 persona-trigger-audit.md）人工审计全净；用户铁律
「所有文本统一口径/风格/话术，前后不矛盾」+ 人格红线（不攻击/不强硬/不 R-18/
不愧疚话术）。本门把人工纪律固化为常驻 pytest 门，防未来批次回潮。

扫描范围（gate_scope()）：capabilities/*.py + capabilities/auto_send/ 子目录
（2026-09-14 主会话批准扩面；扩面前对 auto_send/ 预扫 0 命中）+
character/*.py + runtime/usage_monitor.py + runtime/error_report.py
（2026-09-14 二次扩面，A69-I1）+ personas/**/*.md + personas/**/*.txt +
生产人格副本 ChatBot_Runtime/data/persona/守岸人_核心人格.md
（2026-09-14 三次扩面，人格矛盾修复批 G-08；扩面纪律=先修人格文本
G-01/G-02/G-03 再扩门，门绿为验收；副本缺失时优雅跳过并注明）。

扫描器：Python 文件走纯 AST + 字符串字面量（零 import 被扫模块）；人格资产
md/txt 无 AST，按「非空行 = 一个用户可见单元」逐行过同一套规则。用户可见字符串单元 =
普通串（解析器已合并相邻隐式拼接）+ f-string 字面量块（合并为单元）+ 纯常量
``+`` 链（合并为单元）。排除：注释（AST 天然排除）、日志调用（logger/log/
logging 及 getLogger 链的常见级别方法）、``audit_tags=`` 关键字、URL 串、
``re.*`` 正则模式（位置 0 参与任意调用的 ``pattern=`` 关键字；re.sub 的
repl/原文仍属用户可见面，不豁免）、docstring。

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
CREATOR_NAME_BUILTIN_EXEMPT: frozenset[str] = frozenset(
    {
        "plugins/bot_unified_runtime/character/addressing.py",
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
    """任务口径扫描面：capabilities/*.py（含 capabilities/auto_send/ 子目录，
    2026-09-14 扩面）+ character/*.py + runtime/usage_monitor.py +
    runtime/error_report.py（2026-09-14 二次扩面，A69-I1）+
    personas/**/*.md + personas/**/*.txt + 生产人格副本（2026-09-14 三次扩面，
    G-08；扩面前已完成 G-01/G-02/G-03 人格文本修复；副本缺失优雅跳过）。"""
    files = (
        sorted(RUNTIME_PKG.glob("capabilities/*.py"))
        + sorted(RUNTIME_PKG.glob("capabilities/auto_send/**/*.py"))
        + sorted(RUNTIME_PKG.glob("character/*.py"))
    )
    files.append(RUNTIME_PKG / "runtime" / "usage_monitor.py")
    files.append(RUNTIME_PKG / "runtime" / "error_report.py")
    # 人格资产入扫描面：仓库内源（personas/**）+ 仓库外生产副本（存在才扫）。
    files.extend(sorted(REPO_ROOT.glob("personas/**/*.md")))
    files.extend(sorted(REPO_ROOT.glob("personas/**/*.txt")))
    files.append(RUNTIME_COPY_PATH)
    return [f for f in files if f.exists()]


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
    assert (RUNTIME_PKG / "capabilities" / "echo.py") in scope
    assert (RUNTIME_PKG / "character" / "addressing.py") in scope
    assert (RUNTIME_PKG / "runtime" / "usage_monitor.py") in scope
    # 2026-09-14 扩面：capabilities/auto_send/ 子目录入扫描面。
    assert (RUNTIME_PKG / "capabilities" / "auto_send" / "__init__.py") in scope
    assert (RUNTIME_PKG / "capabilities" / "auto_send" / "parser.py") in scope
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
    # 内建豁免：addressing.py 路径语义下不红。
    criticals_exempt, _ = scan_file(file, rel_path="plugins/bot_unified_runtime/character/addressing.py")
    assert not criticals_exempt


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
    """真绿：扩面后现网 auto_send/ 两文件零 Critical（扩面前预扫亦 0 命中）。"""
    auto_files = sorted((RUNTIME_PKG / "capabilities" / "auto_send").glob("*.py"))
    assert len(auto_files) >= 2, "auto_send/ 目录文件数异常，扫描面或已漂移"
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
