"""生产树注毒残留门（S-T-POISON-GATE2 · 2026-09-25/26 需求 18 项修复波 · 横向治理席）。

本门守一件事：**席位做「注毒自证」时把毒落在了真实工作树上、且没能还原**。
起因两枚实证（一枚看护员取证、一枚本席 00:39 亲撞）：

1. ``progress_ack.py`` 18 秒内两度换身：毒版 ``:305 if False:`` ＋ ``:306 return False  # POISON``
   （sha ``795b1975646601e8``／20,037B），16 秒后回到干净版（sha ``5f8e154fb598d70b``／20,071B）。
   毒发当时该族测试 **166 passed / 2 xfailed 全绿**——``if False:`` 是惰性的，
   **树被污染时测试看不见**。
2. ``domains/core/safety_exec/config_risk.py:101`` 在本席 grep 里是
   ``"meta:settings.SETTABLE_KEYS",  # POISON-M12``，同批次 ``Read`` 已是干净小写规范形，
   该文件 mtime 恰落在两次读取之间（``00:39:36``）⇒ 别席此刻正在真实树上注毒并当场还原。

若那样的席位在「毒已落、未及还原」的窗口里猝死（本波已死 5 席，全是服务侧），
**一枚被改过的门会永久留在生产源码里**，且不改变行为、不被任何锁抓到。本门即把该纪律变成门。

三类形态与各自执法强度（**判不了的一律写明判不了，不假装拦得住**）
---------------------------------------------------------------------
``F1`` 行内注释形态的注毒标记（``# POISON`` / ``# poison``）——**执法**。
``F2`` 门被短路形态（``if False:`` / ``if True:`` 直跟 ``return``，含 ``if False and X:`` /
     ``if True or X:`` / ``if not True:`` 这类可常量化折叠）——**执法**。
``F3`` 与 ``HEAD`` 相比「只少不改」的改写——**只盘点、不执法**。

本门**拦不住**的三类（逐条与 :data:`UNENFORCEABLE_CLASSES` 名字对齐，
:func:`test_f3_classes_are_declared_unenforceable` 逐条比对；删掉任何一条本文档即红）：
  - 纯删除型改写
  - 改值型且不落 COMMENT / If 两种形状
  - 未跟踪件与 HEAD 无基线

另有一条通则拦不住且必须说在白纸上：**故意藏标记的注毒不在本门射程内**——
F1 认的是"忘了还原"，不是"存心灭迹"。真要用一句话概括本门的根除面：
**带标记或带短路形状的毒，在真实树里留不住；不带形状的就只能把作业面搬出真实树**
（对照组席位 ``S-T-ACK-1`` 全程只在 ``$TEMP`` 副本注毒并逐发比对"与真实树等值"，那种写法做得到）。

形态判别：不写正则去猜，用 ``tokenize`` 的 token 类型（唯一判据，不留第二真身）
--------------------------------------------------------------------------------
合法在册夹具用的是 ``POISONS:`` 标识符、``poisoned.`` 变量名、字符串字面量 ``"【注毒】"``／
``"POISON::bot.nobody"``（现算落点 ``scripts/capability_manifest_projection_check.py:2212/2230/2228``
与 ``scripts/ownership_project.py:1299``），**不是** ``# POISON`` 行内注释。这些形态分别落在
``NAME``/``OP``/``STRING`` token 上，永远不会成为 ``COMMENT`` token ⇒ **只看 ``COMMENT`` 即天然放行**；
"文档性说明"里出现"注毒"二字（``plugins/**`` 现算 18 处）不含 ASCII 词形，同样放行。
正反两向的证据都在 :func:`test_f1_forgers_comment_form_but_never_the_registered_forms`。

F1 词形刻意收在「注释体以 poison 开头」（``#+\\s*poison\\b``），不是"注释里含 poison"：
`scripts/central_seam_census.py` 那种 ``--poison FILE`` 的说明若哪天从 docstring 挪进行内注释，
按"含词即报"就会被误杀。含词但不以词开头的邻形并非丢弃——进 :data:`ScanReport.advisory`
现算盘点（今日 0 枚），但不执法，理由与 F3 同类。

非 ``.py`` 生产文件（``.html``/``.css``/``.json``/``.ps1``/``.toml``/``.md``）也扫注释形态：
现算全树 ``poison`` 命中 **0 枚** ⇒ 这条腿今天零误报风险，属白送的一层。

扫描一律**从磁盘读**（未跟踪新件也在内：现算 ``plugins/**``＋``scripts/**`` 未跟踪 ``.py`` 58 枚，
含 §2 那枚 ``config_risk.py``——它连 ``HEAD`` 基线都没有，F3 对它结构性无从下手）。

本门**纯静态、零 import 包内件**（硬纪律 5：``safety_exec/paths.py`` 一类半写文件会把整条
import 链在收集期打断，而 ``__pycache__`` 里存着编译成功的旧 ``.pyc``，同一命令两次可给相反读数）。

复跑
----
``export PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 PYTHONUTF8=1 BOT_AUTOSYNC=0``
``export PYTHONPYCACHEPREFIX="$(cygpath -w "$PWD/../ChatBot_Runtime/cache/pycache_seatPOISON2")"``
``../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_production_tree_has_no_poison_artifact.py -p no:cacheprovider --basetemp=<私有目录> -q``
印当前命中清单：``python tests/test_production_tree_has_no_poison_artifact.py``
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DIRS: tuple[str, ...] = ("plugins", "scripts")
PYTHON_SUFFIXES: tuple[str, ...] = (".py",)
OTHER_TEXT_SUFFIXES: tuple[str, ...] = (".html", ".css", ".json", ".ps1", ".toml", ".md")

#: 执法形：注释体以 ``poison`` 开头（``# POISON``、``##  poison: …``、``#POISON-M12``、
#: ``<!-- POISON … -->``）。``#*`` 让 .py 的 ``#`` 与非 .py 已剥掉 opener 的文本共用一支判据。
#: 词界用 ``\b`` 而非结尾匹配：``POISON-M12`` 的 ``-`` 不是词字符 ⇒ 命中（00:39 实况那发就是
#: 这种带后缀的形状）；``poison_paths`` 的 ``_`` 是词字符 ⇒ 不命中（合法入参名）。
POISON_COMMENT_RE = re.compile(r"^#*\s*poison\b", re.IGNORECASE)
#: 邻形（盘点不执法）：注释体里含独立词 ``poison`` 但不在句首。
POISON_ADVISORY_RE = re.compile(r"\bpoison\b", re.IGNORECASE)

#: 登记「拦不住」的三类，逐条带理由。谁要把它升成红门，先逐条推翻这里的理由。
UNENFORCEABLE_CLASSES: tuple[tuple[str, str], ...] = (
    (
        "纯删除型改写",
        (
            "无标记、无短路形状，与重构删除静态同形；现算在册合法纯删除 33 枚文件即反例，"
            "做成红门必常驻并被后来人降判据。"
        ),
    ),
    (
        "改值型且不落 COMMENT / If 两种形状",
        (
            "例：把 config_risk.py 的 settable_keys 换成规格原名 SETTABLE_KEYS 而不带尾注，"
            "改的是 STRING 里的值，F1/F2 双腿全绿。只能靠该件自有的逐键名等值锁，"
            "或把注毒作业面搬出真实树。"
        ),
    ),
    (
        "未跟踪件与 HEAD 无基线",
        (
            "现算 plugins/**＋scripts/** 未跟踪 .py 58 枚（含 config_risk.py 自身），"
            "git diff 对它们恒无输出，F3 结构性无从下手。"
        ),
    ),
)

#: F3 是否执法。**必须为 False**。
F3_ENFORCE = False


# ---------------------------------------------------------------------------
#  finding 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """一枚命中。``rel_path`` 相对仓库根，``form`` ∈ {F1, F2}。"""

    form: str
    rel_path: str
    line: int
    text: str
    how: str

    def locate(self) -> str:
        return f"{self.rel_path}:{self.line}"

    def render(self) -> str:
        return f"[{self.form}] {self.locate()}  {self.text}   ——{self.how}"


@dataclass(frozen=True)
class AllowedFinding:
    """**合法在册**的放行条目。条目必须"当场仍成立"（仍扫得到同 form 的命中、
    且该行文本仍含登记的特征串），否则该条目自身作废并打红——放行不许腐化成永久豁免。"""

    rel_path: str
    form: str
    must_still_contain: str
    reason: str


#: 现算为空：生产面 F1/F2 今日零命中。唯一一枚是 00:39 飞行中、被别席当场还原的那发，
#: 它已经不在盘上 ⇒ 不登记为放行项（登记它就是给一具尸体发永久通行证）。
ALLOWED_FINDINGS: tuple[AllowedFinding, ...] = ()


# ---------------------------------------------------------------------------
#  扫描面与读取
# ---------------------------------------------------------------------------


def production_files(root: Path = REPO_ROOT) -> list[Path]:
    """生产面全部待扫文件（磁盘现值，含未跟踪件），稳定排序。"""
    out: list[Path] = []
    for sub in PRODUCTION_DIRS:
        base = root / sub
        if not base.is_dir():  # pragma: no cover - 结构异常
            continue
        for path in base.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix in PYTHON_SUFFIXES or path.suffix in OTHER_TEXT_SUFFIXES:
                out.append(path)
    return sorted(out)


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    return raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


def rel_of(path: Path, root: Path = REPO_ROOT) -> str:
    """相对仓库根的正斜杠路径。先按原样比、再按 resolve 比——Windows 上 ``tempfile``
    常给 ``LANCYC~1`` 短名，只比 resolve 会让 ``relative_to`` 抛值错误、回落成整条绝对路径
    （本席第一次实跑就是这样，报告里的定位串会变得没法直接粘用）。"""
    for candidate in (path, path.resolve()):
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            continue
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:  # pragma: no cover - 真在树外（沙箱件）
        return path.name if root.name != REPO_ROOT.name else str(path)


# ---------------------------------------------------------------------------
#  F1：行内注释形态的注毒标记
# ---------------------------------------------------------------------------


def comment_tokens(text: str) -> list[tuple[int, str]] | None:
    """``COMMENT`` token 全家（行号, 原文）。返回 ``None`` 表示 tokenize 失败（半写文件）。"""
    found: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                found.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return None
    return found


@dataclass
class F1Result:
    violations: list[Finding] = field(default_factory=list)
    advisory: list[Finding] = field(default_factory=list)


def f1_python_findings(rel_path: str, text: str) -> F1Result:
    """扫 .py 的注释形态。执法只认句首形（``POISON_COMMENT_RE``），其余邻形进盘点。"""
    res = F1Result()
    comments = comment_tokens(text)
    lines = text.split("\n")
    if comments is not None:
        pairs: Iterable[tuple[int, str]] = comments
        degraded = False
    else:
        # 半写文件（tokenize 都跑不动）退到行级：这种文件不可能"合法在跑"，宁可从严。
        pairs = [(i + 1, ln[ln.index("#"):]) for i, ln in enumerate(lines) if "#" in ln]
        degraded = True
    for lineno, raw_comment in pairs:
        body = raw_comment.lstrip("#").lstrip()
        hit = POISON_COMMENT_RE.match(raw_comment)
        if hit:
            res.violations.append(
                Finding(
                    "F1",
                    rel_path,
                    lineno,
                    lines[lineno - 1].strip() if lineno - 1 < len(lines) else raw_comment,
                    "tokenize=COMMENT 且注释体以 poison 开头 ⇒ 注毒标记的行内注释形态"
                    + ("（tokenize 失败退行级）" if degraded else ""),
                )
            )
        elif POISON_ADVISORY_RE.search(body):
            res.advisory.append(
                Finding(
                    "F1-adv",
                    rel_path,
                    lineno,
                    lines[lineno - 1].strip() if lineno - 1 < len(lines) else raw_comment,
                    "注释含 poison 词但不在句首 ⇒ 只盘点（合法文档说明与藏标记同形，不执法）",
                )
            )
    return res


def f1_other_findings(rel_path: str, text: str) -> F1Result:
    """非 .py 生产文件没有 tokenize，只认行首注释符起手的段（opener 之后的文本交给同一支
    :data:`POISON_COMMENT_RE`，故 ``#``／``//``／``/*``／``<!--`` 四式共用一条判据）。"""
    res = F1Result()
    lines = text.split("\n")
    for idx, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        for opener in ("<!--", "#if", "//", "/*", "#"):
            if not stripped.startswith(opener):
                continue
            after = stripped[len(opener):]
            if POISON_COMMENT_RE.match(after):
                res.violations.append(
                    Finding(
                        "F1",
                        rel_path,
                        idx,
                        stripped,
                        f"非 .py 文件注释段（{opener}）以 poison 开头",
                    )
                )
            elif POISON_ADVISORY_RE.search(after):
                res.advisory.append(
                    Finding("F1-adv", rel_path, idx, stripped, "非 .py 注释邻形，只盘点")
                )
            break
    return res


# ---------------------------------------------------------------------------
#  F2：门被短路形态
# ---------------------------------------------------------------------------


def const_bool(node: ast.expr) -> bool | None:
    """条件是否可折叠成常量真/假（含 BoolOp / not 的短路折叠）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = const_bool(node.operand)
        return None if inner is None else (not inner)
    if isinstance(node, ast.BoolOp):
        parts = [const_bool(v) for v in node.values]
        if isinstance(node.op, ast.And):
            if any(v is False for v in parts):
                return False
            return True if all(v is True for v in parts) else None
        if any(v is True for v in parts):
            return True
        return False if all(v is False for v in parts) else None
    return None


#: ast 腿用的行文本缓存（避免每条 finding 重读文件）。扫描前填、扫完留作报告用。
LINE_CACHE: dict[str, list[str]] = {}


def cached_line(rel_path: str, lineno: int) -> str:
    lines = LINE_CACHE.get(rel_path) or []
    return lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""


def f2_ast_findings(rel_path: str, tree: ast.AST) -> list[Finding]:
    hits: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        folded = const_bool(node.test)
        if folded is None:
            continue
        stmts: Sequence[ast.stmt] = node.body
        if not stmts or not isinstance(stmts[0], ast.Return):
            continue
        shape = "真值恒假（守卫被摘死）" if folded is False else "真值恒真（分支被焊死）"
        hits.append(
            Finding(
                "F2",
                rel_path,
                getattr(node, "lineno", 0),
                cached_line(rel_path, getattr(node, "lineno", 0)),
                f"ast: if 条件可折叠且体首条语句即 Return ⇒ 门被短路（{shape}）",
            )
        )
    return hits


_TEXT_IF_RE = re.compile(r"^\s*if\s+(?:not\s+)?(?:True|False)\b[^:#]*(?::|#)")


def f2_text_findings(rel_path: str, text: str) -> list[Finding]:
    """ast 之外的独立回退腿：一行 ``if False:``/``if True:``（含 ``if False and X:``）之后
    下一非空行是更深缩进的 ``return``。半写文件 ast 解不开时这条仍抓得住——
    事发那一发正好就是这个两行形状。"""
    hits: list[Finding] = []
    lines = text.split("\n")
    for idx, raw in enumerate(lines):
        if not _TEXT_IF_RE.match(raw):
            continue
        own_indent = len(raw) - len(raw.lstrip())
        for nxt in lines[idx + 1:]:
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                continue
            if len(nxt) - len(nxt.lstrip()) <= own_indent:
                break
            if nxt.strip().startswith("return"):
                hits.append(
                    Finding(
                        "F2",
                        rel_path,
                        idx + 1,
                        raw.strip(),
                        "文本回退：`if False|True:` 直跟 `return`（ast 之外的第二腿）",
                    )
                )
            break
    return hits


# ---------------------------------------------------------------------------
#  整树扫描
# ---------------------------------------------------------------------------


@dataclass
class ScanReport:
    files_scanned: int
    findings: list[Finding]
    advisory: list[Finding]
    unparseable: list[str]

    @property
    def violations(self) -> list[Finding]:
        return [f for f in self.findings if not _is_allowed(f)]

    @property
    def stale_allows(self) -> list[AllowedFinding]:
        return stale_allowlist(self.findings)


def _matches(allow: AllowedFinding, finding: Finding) -> bool:
    """放行条目与命中的唯一比对式：**三件齐全**（路径＋形态＋该行仍含登记特征串）。
    少了第三件，豁免就会腐化成"该文件该形态永久免检"——那正是本门要拦的形状。"""
    return (
        allow.rel_path == finding.rel_path
        and allow.form == finding.form
        and allow.must_still_contain in finding.text
    )


def _is_allowed(finding: Finding) -> bool:
    return any(_matches(a, finding) for a in ALLOWED_FINDINGS)


def stale_allowlist(findings: Iterable[Finding]) -> list[AllowedFinding]:
    """登记过但现算已不成立的放行条目——必须点名，否则豁免会变永久豁免。
    判据只看现算命中集，不重读磁盘（避免与扫描器抢同一枚半写文件给出相反读数）。
    与 :func:`_is_allowed` 共用 :func:`_matches`，两条腿不可能互相打脸。"""
    return [a for a in ALLOWED_FINDINGS if not any(_matches(a, f) for f in findings)]


def scan_production_tree(root: Path = REPO_ROOT) -> ScanReport:
    files = production_files(root)
    findings: list[Finding] = []
    advisory: list[Finding] = []
    unparseable: list[str] = []
    for path in files:
        try:
            text = read_text(path)
        except OSError:  # pragma: no cover - 并发删除的瞬时件
            continue
        rel = rel_of(path, root)
        if path.suffix in PYTHON_SUFFIXES:
            LINE_CACHE[rel] = text.split("\n")
            r1 = f1_python_findings(rel, text)
            findings.extend(r1.violations)
            advisory.extend(r1.advisory)
            try:
                tree = ast.parse(text, filename=rel)
            except (SyntaxError, ValueError):
                unparseable.append(rel)
                findings.extend(f2_text_findings(rel, text))
                continue
            f2_hits = f2_ast_findings(rel, tree)
            seen = {h.line for h in f2_hits}
            findings.extend(f2_hits)
            findings.extend(h for h in f2_text_findings(rel, text) if h.line not in seen)
        elif path.suffix in OTHER_TEXT_SUFFIXES:
            r1 = f1_other_findings(rel, text)
            findings.extend(r1.violations)
            advisory.extend(r1.advisory)
    findings.sort(key=lambda f: (f.form, f.rel_path, f.line))
    advisory.sort(key=lambda f: (f.rel_path, f.line))
    return ScanReport(len(files), findings, advisory, unparseable)


# ---------------------------------------------------------------------------
#  F3：只盘点、不执法
# ---------------------------------------------------------------------------


def only_deletion_inventory(root: Path = REPO_ROOT) -> tuple[list[tuple[str, int]], str]:
    """``git diff --numstat HEAD -- plugins scripts`` 里 ``added==0 且 deleted>0`` 的 .py。

    **本函数不作红判据**（:data:`F3_ENFORCE` 为 False），理由见
    :data:`UNENFORCEABLE_CLASSES` 第一条：本仓「垫片退役波」的正常成品就是成片的纯删除
    （现算 33 枚），删 18 行垫片体和删 18 行守卫在静态面上长得一模一样。
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--numstat", "HEAD", "--", *PRODUCTION_DIRS],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:  # pragma: no cover
        return [], f"git 不可用：{exc}"
    if proc.returncode != 0:
        return [], f"git diff 退出码 {proc.returncode}（HEAD 不可读？）"
    rows: list[tuple[str, int]] = []
    for raw in proc.stdout.splitlines():
        parts = raw.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts[0], parts[1], parts[2]
        if added == "0" and deleted.isdigit() and int(deleted) > 0 and path.endswith(".py"):
            rows.append((path.replace("\\", "/"), int(deleted)))
    rows.sort()
    return rows, "ok"


# ---------------------------------------------------------------------------
#  合成样本（**只写进 pytest 的 tmp_path，绝不写进真实树**）
# ---------------------------------------------------------------------------

#: 事发形状的逐字复刻。行号硬编在断言里：第 6 行是短路的 if，第 7 行是带标记的 return。
INCIDENT_SAMPLE = '''"""事发形状的复刻（progress_ack.py 那一发）。"""


def gate(settings, group_id: str) -> bool:
    if settings.enabled:
        if False:
            return False  # POISON
        return group_id in settings.whitelist
    return False
'''

#: 前棒 §0 点名的三枚合法形态 ＋ 本席现算补的第四枚（``"POISON::bot.nobody"``，
#: 出自 scripts/ownership_project.py:1299 —— 大写 POISON 在字符串里，最凶的诱饵）。
REGISTERED_FIXTURE_SAMPLE = '''"""合法在册夹具的四种形态。"""

POISONS: tuple[tuple[str, str, str], ...] = (("title", "x", "y"),)


def _apply_poison(field_name: str, side_a: dict, extraction) -> str:
    row = {"gate_feature_id": ("poisoned." + str(field_name), "K"),
           "title": (str(field_name) + "【注毒】", "K"),
           "handler_ref": ("POISON::bot.nobody", "K")}
    poison_paths = list(side_a)  # 见 --poison FILE 的入参名
    # 注毒自证：证明本件真有牙（文档性说明，合法）
    return str(row) + str(poison_paths) + str(POISONS) + field_name
'''

SHORT_CIRCUIT_SAMPLES = {
    "bare_false": "def f(x):\n    if False:\n        return x\n    return 1\n",
    "bare_true": "def f(x):\n    if True:\n        return x\n",
    "and_false": "def f(x):\n    if False and x:\n        return x\n    return 1\n",
    "or_true": "def f(x):\n    if True or x:\n        return x\n    return 1\n",
    "not_true": "def f(x):\n    if not True:\n        return x\n    return 1\n",
    "const_if_no_return": "def f(x):\n    if True:\n        x = 1\n    return x\n",
    "real_condition": "def f(x):\n    if x and x.blacklist:\n        return False\n    return True\n",
}
MUST_HIT = {"bare_false", "bare_true", "and_false", "or_true", "not_true"}


def write_tmp(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
#  测试
# ---------------------------------------------------------------------------

_SCAN: ScanReport | None = None


def the_scan() -> ScanReport:
    global _SCAN
    if _SCAN is None:
        _SCAN = scan_production_tree()
    return _SCAN


def test_f1_forgers_comment_form_but_never_the_registered_forms(tmp_path: Path) -> None:
    """判据自证第一发（正反两向）：注释形态**必报**，§0 四枚合法形态**一律不误报**。"""
    incident = write_tmp(tmp_path, "incident_sample.py", INCIDENT_SAMPLE)
    res = f1_python_findings("incident_sample.py", read_text(incident))
    assert [(h.line, h.text) for h in res.violations] == [(7, "return False  # POISON")], [
        h.render() for h in res.violations
    ]

    fixture = write_tmp(tmp_path, "registered_sample.py", REGISTERED_FIXTURE_SAMPLE)
    text = read_text(fixture)
    reg = f1_python_findings("registered_sample.py", text)
    assert reg.violations == [], [h.render() for h in reg.violations]
    # 自证这条断言不是空跑：把文档性注释换成标记形，同一支扫描器必须立刻命中
    flipped = text.replace("# 注毒自证", "# POISON 自证")
    assert flipped != text and len(f1_python_findings("x.py", flipped).violations) == 1
    # 邻形（注释含词不在句首）走盘点、不走执法——central_seam_census 那类说明的保护
    assert len(reg.advisory) >= 1, [h.render() for h in reg.advisory]
    assert all(h.form == "F1-adv" for h in reg.advisory)

    for name, body in (
        ("dash_suffix.py", "x = 1  # POISON-M12\n"),
        ("lower.py", "# poison: 门被摘\ny = 2\n"),
        ("nosep.py", "z = 3  #POISON\n"),
        ("hash2.py", "w = 4  ## POISON gate 被短路\n"),
    ):
        path = write_tmp(tmp_path, name, body)
        got = f1_python_findings(name, read_text(path)).violations
        assert len(got) == 1, (name, [h.render() for h in got])


def test_f1_non_py_comment_form(tmp_path: Path) -> None:
    """.html/.css 一类也扫：注释段以 poison 开头必报，字符串里含词不报。"""
    body = "<!-- POISON marker -->\n<div>POISON in text node</div>\n"
    path = write_tmp(tmp_path, "card.html", body)
    res = f1_other_findings("card.html", read_text(path))
    assert [h.line for h in res.violations] == [1], [h.render() for h in res.violations]


def test_f2_flags_short_circuited_gates_only(tmp_path: Path) -> None:
    """判据自证第二发：门被短路形态必报（ast 与文本回退两条腿各自独立必报），
    真条件式与"体首不是 Return"不报。"""
    for name, body in SHORT_CIRCUIT_SAMPLES.items():
        path = write_tmp(tmp_path, f"{name}.py", body)
        text = read_text(path)
        LINE_CACHE[name] = text.split("\n")
        ast_hits = f2_ast_findings(name, ast.parse(text))
        text_hits = f2_text_findings(name, text)
        if name in MUST_HIT:
            assert len(ast_hits) == 1, (name, [h.render() for h in ast_hits])
            assert len(text_hits) == 1, (name, "文本回退腿必须能独立抓到（半写件靠它）")
        else:
            assert not ast_hits and not text_hits, (
                name,
                [h.render() for h in ast_hits + text_hits],
            )


def test_allowlist_mechanism_suppresses_only_what_is_still_true() -> None:
    """放行登记不许腐化：条目当场仍成立才压，失成立即点名；且不得顺带压掉别处同形毒。"""
    findings = [Finding("F1", "plugins/a.py", 3, "return False  # POISON", "t")]
    global ALLOWED_FINDINGS
    saved = ALLOWED_FINDINGS
    try:
        ALLOWED_FINDINGS = (
            AllowedFinding("plugins/a.py", "F1", "# POISON", "演示：当场仍成立"),
        )
        assert stale_allowlist(findings) == []
        assert [f.render() for f in _violations(findings)] == []
        # 同一枚毒改了写法 ⇒ 豁免当场作废，必须回到 violations 并被点名
        changed = [Finding("F1", "plugins/a.py", 3, "return False  # 改了", "t")]
        assert len(stale_allowlist(changed)) == 1
        assert len(_violations(changed)) == 1
        # 未登记的第二枚不得被上一条豁免顺带压掉
        two = findings + [Finding("F1", "plugins/b.py", 9, "x = 1  # POISON", "t")]
        assert len(_violations(two)) == 1
    finally:
        ALLOWED_FINDINGS = saved


def _violations(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if not _is_allowed(f)]


def test_production_surface_has_no_poison_artifact() -> None:
    """主判据：生产面 F1/F2 零命中（现算快照同时贴在 S-T-POISON-GATE2 报告里）。"""
    report = the_scan()
    assert report.files_scanned > 500, f"扫描面异常收窄：{report.files_scanned}"
    assert not report.violations, (
        "生产树存在注毒残留形态（file:line 逐条列出）：\n"
        + "\n".join(f.render() for f in report.violations)
    )
    assert not report.stale_allows, (
        "放行登记表已失成立，须撤销或补证据：\n"
        + "\n".join(f"{a.rel_path}  {a.reason}" for a in report.stale_allows)
    )


def test_scanner_covers_untracked_production_files() -> None:
    """扫描面必须含未跟踪新件——00:39 那枚飞行注毒正落在未跟踪的 config_risk.py 上。"""
    untracked = _git_untracked_py()
    assert len(untracked) >= 10, untracked[:5]
    scanned = {rel_of(p) for p in production_files()}
    missing = [p for p in untracked if p not in scanned]
    assert not missing, f"未跟踪生产件未被扫描：{missing[:5]}"
    assert "plugins/bot_unified_runtime/domains/core/safety_exec/config_risk.py" in scanned


def _git_untracked_py(root: Path = REPO_ROOT) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "--", *PRODUCTION_DIRS],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:  # pragma: no cover
        return []
    return sorted(
        x.replace("\\", "/")
        for x in proc.stdout.split()
        if x.endswith(".py") and "__pycache__" not in x
    )


def test_f3_classes_are_declared_unenforceable() -> None:
    """诚实锁：F3 不执法，且"拦不住哪一半"必须逐条留在模块文档里（删一条即红）。"""
    assert F3_ENFORCE is False
    assert len(UNENFORCEABLE_CLASSES) >= 3
    doc = __doc__ or ""
    for name, reason in UNENFORCEABLE_CLASSES:
        assert reason.strip(), name
        assert name in doc, f"登记了拦不住却没在模块文档写明：{name}"
    rows, status = only_deletion_inventory()
    assert status == "ok", status
    assert all(path.endswith(".py") and deleted > 0 for path, deleted in rows)


def _render_inventory() -> str:
    report = the_scan()
    rows, status = only_deletion_inventory()
    out = [
        f"扫描文件数：{report.files_scanned}",
        f"ast/tokenize 解不开的文件（半写件，如实点名）：{len(report.unparseable)}"
        + ("".join(f"\n  - {r}" for r in report.unparseable) or "（无）"),
        f"F1／F2 执法命中：{len(report.findings)}（violations {len(report.violations)}）",
        *[f"  {f.render()}" for f in report.findings],
        f"F1 邻形盘点（不执法）：{len(report.advisory)}",
        *[f"  {f.render()}" for f in report.advisory],
        f"F3 纯删除文件（不执法，git 状态={status}）：{len(rows)}",
        *[f"  {p} 0/{d}" for p, d in rows],
    ]
    return "\n".join(out)


if __name__ == "__main__":
    print(_render_inventory())
