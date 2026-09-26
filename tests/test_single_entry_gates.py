"""入口唯一性机器门（席位 S-T-DUPE-1，2026-09-26 立；生产代码零改动）。

S-T-DUPE-1 阵亡于「门②归属账常量未落盘 + 门③反向锁与 finder 三形态设计打架」，
S-T-DUPE-1R 继承补全（账定义/接线/锁改判的逐条依据见本文件内注释与
`.superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-DUPE-1R.md`）。

本波实证出三处「同一个事实/同一处入口被写了两遍」：`poke.py` 双写者、
`character/reflection.py` 两席争、需求 5 宿主取数多套真身（全账见
`.superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-DUPE-1.md`）。前两件的本质是
**人的归属问题**（本席只在报告里登记，机检不了「谁该写」），第三件是可以机检的
事实重复。本门把「重复入口」一律变成机器可检的账，三扇门：

① 记忆类型的中文词表（**硬门 · 零容忍**）——类型真身
   ``memory_service.MemoryKind``（封闭枚举），显示名真身
   ``providers._MEMORY_KIND_DISPLAY_ZH``（键必须是枚举成员，故幽灵键在类型层写
   不进来）。词表字面量不许在**任何第三个文件**里再出现一份。
② 宿主机读数的取数口（**账门 · 只报现状**）——逐事实登记今天哪些文件在直接读
   psutil / 注册表 / nvidia-smi。存量收敛由 S-T-HOST-2 做：他们收敛后本账必须
   跟着改（账与实况不符当场红并点名 owner），而任何**新加入抄取数**的文件当场红。
③ ``domains/meme/`` 的主体判定与准入门——「谁是本命」的判定口只准一处真身
   （**硬门**）；「能不能入库」的 NSFW 准入阈值今天有抄件 ⇒ 逐处登记（**账门**）。

三条口径纪律（每条都是本波实锤过的坑，写进代码防回潮）：

- **一律 AST，绝不靠文本 grep 判归属**：注释与 docstring 里的名字既不是读点、
  也不是词表副本（本波实测：文本级 grep 会把 ``reflection.py`` 注释里的「偏好」
  算成第二真身）。每扇门各带一发「只有 docstring/注释提到 ⇒ 不算」的反向锁。
- **注毒走「同一取数函数吃一段内存源码」**（照 ``tests/test_legacy_shim_import_
  ratchet.py`` 的既有口径），绝不往 ``plugins/**`` 写一个字节。
- **扫描面不许塌陷**：文件数下限锁 + 全树可解析锁。解析失败＝扫描被静默截短、
  所有读数不可信，必须现红而不是当成「零违规」。本机已知 D-8 半写件
  （``domains/core/safety_exec/paths.py``）会让这一发短时红：等 60 秒重跑，
  **不许**为此放宽判据或加排除名单。
"""

from __future__ import annotations

import ast
import collections
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
PKG_REL = "plugins/bot_unified_runtime"

# ---------------------------------------------------------------------------
# 通用 AST 取数件（三扇门共用一把尺子；尺子本身只有一份，逐门另立=本门自打）
# ---------------------------------------------------------------------------


def _parse(source: str, filename: str = "<memory>") -> ast.Module:
    return ast.parse(source, filename=filename)


def _docstring_nodes(tree: ast.AST) -> frozenset[int]:
    """docstring 那几枚 Constant 节点的 id 集合（判归属时一律先摘掉）。

    注释本来就不进 AST，这一发只为把 **docstring/说明文字**里的字面量与代码里的
    字面量分开：本仓各件在 docstring 里大量转述真身名字与阈值语义（``host_metrics.py``
    开头十余行全是这种话），把它们算成读点就是 grep 的老错。
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return frozenset(out)


def _code_strings(tree: ast.AST) -> list[tuple[int, str]]:
    """非 docstring 的字符串字面量 (行号, 值)：代码里真正写下的字。"""
    skip = _docstring_nodes(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            out.append((node.lineno, node.value))
    return out


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _names_in(node: ast.AST) -> list[str]:
    """子树里出现过的标识符（小写）：用于「这个表达式在说 nsfw 吗」这类判定。"""
    out: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.append(sub.id.lower())
        elif isinstance(sub, ast.Attribute):
            out.append(sub.attr.lower())
    return out


def _mentions(node: ast.AST, hint: str) -> bool:
    """子树里任一标识符**含**该词（`float(nsfw_score)` 也算在说 nsfw）。

    精确等值会漏：写成 ``float(nsfw_score) >= 0.8`` 时子树里的名字是
    ``nsfw_score``，按等值找 "nsfw" 永远找不到——本门第一版就这么漏过两发真抄件。
    """
    return any(hint in name for name in _names_in(node))


def _py_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def extensionless_python_files(base: Path) -> list[str]:
    """没有 `.py` 后缀、但按 Python 语法能解析的件（`rglob("*.py")` 天然看不见它们）。"""
    out: list[str] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix:
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        out.append(path.relative_to(REPO_ROOT).as_posix())
    return out


def _load_tree(path: Path) -> ast.Module:
    return _parse(path.read_text(encoding="utf-8"), filename=str(path))


# ===========================================================================
# 门 ①：记忆类型中文词表只准一处真身（硬门）
# ===========================================================================

MEMORY_KIND_ENUM_FILE = f"{PKG_REL}/domains/chat_reply/character/memory_service.py"
MEMORY_KIND_LABEL_FILE = f"{PKG_REL}/domains/chat_reply/character/providers.py"
GATE1_SCAN_ROOT = PKG_ROOT
#: 扫描文件数下限：现算 591（2026-09-26）。留余量但不许塌：改 glob/加排除就会在这里现红。
GATE1_MIN_SCANNED_FILES = 550


@dataclass(frozen=True)
class KindLabelTable:
    """一处「记忆类型 → 中文显示名」的词表。"""

    file: str
    line: int
    keyed_on_enum: bool
    entries: tuple[tuple[str, str, int], ...]  # (key 形态, 中文标签, 行号)


def enum_members(source: str, *, enum_name: str = "MemoryKind") -> dict[str, str]:
    """封闭枚举的 ``成员名 → 值``（真身的形状，本门一切判据由它派生）。"""
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == enum_name:
            members: dict[str, str] = {}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target = stmt.targets[0]
                    if (
                        isinstance(target, ast.Name)
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)
                    ):
                        members[target.id] = stmt.value.value
            return members
    return {}


def kind_label_tables(tree: ast.AST, *, rel: str, kind_values: frozenset[str]) -> list[KindLabelTable]:
    """找出一段源码里的「类型 → 中文名」词表（≥2 项即算一处，单项不成表）。

    判定只看 AST 形状，不看变量名：键写成 ``MemoryKind.X``（在册枚举上派生）或
    写成枚举值字符串（``"preference"``——手抄的第二形态），值写成含中文的常量。
    """
    tables: list[KindLabelTable] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        entries: list[tuple[str, str, int]] = []
        all_keys_are_enum = True
        for key, value in zip(node.keys, node.values):
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            if not _has_cjk(value.value):
                continue
            if isinstance(key, ast.Attribute) and isinstance(key.value, ast.Name) and key.value.id == "MemoryKind":
                entries.append((f"MemoryKind.{key.attr}", value.value, value.lineno))
                continue
            all_keys_are_enum = False
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value in kind_values:
                entries.append((key.value, value.value, value.lineno))
        if len(entries) >= 2:
            tables.append(
                KindLabelTable(
                    file=rel,
                    line=node.lineno,
                    keyed_on_enum=all_keys_are_enum,
                    entries=tuple(entries),
                )
            )
    return tables


def kind_label_copies(
    tree: ast.AST, *, rel: str, canonical_file: str, labels: frozenset[str]
) -> list[tuple[int, str]]:
    """词表字面量在**表外文件**里又出现一次（=手抄第二真身）。

    判据取**子串**形而不是等值形：把标签焊进渲染模板（`"【爱好与偏好】"`）与整表手抄
    是同一件事——真身改字、模板不改，两处标签就开始漂移。本表现算：表外子串命中 0 处
    ⇒ 放宽到子串零代价，而多拦住的正是「焊进模板」那一种。
    """
    if rel == canonical_file:
        return []
    out: list[tuple[int, str]] = []
    for line, text in _code_strings(tree):
        for label in labels:
            if label in text:
                out.append((line, text))
                break
    return out


@lru_cache(maxsize=1)
def memory_kind_truth() -> tuple[dict[str, str], KindLabelTable, dict[str, str]]:
    """现算的三件真身事实：枚举成员 / 唯一显示名表 / ``kind 值 → 中文标签``。

    ⚠ 简报里写的「真身 = ``memory_store_v21.MemoryKind``」**坐标不符**：本表现算
    ``MemoryKind`` 住在 ``memory_service.py:32``（``memory_store_v21.py`` 里只有 SQL 的
    ``kind`` 列，没有这个枚举）。判据一律跟磁盘现算走，不跟转述走。
    """
    enum_source = (REPO_ROOT / MEMORY_KIND_ENUM_FILE).read_text(encoding="utf-8")
    members = enum_members(enum_source)
    if not members:
        raise AssertionError(f"枚举真身不在了：{MEMORY_KIND_ENUM_FILE} 里找不到 MemoryKind 成员")
    label_tree = _load_tree(REPO_ROOT / MEMORY_KIND_LABEL_FILE)
    tables = kind_label_tables(
        label_tree, rel=MEMORY_KIND_LABEL_FILE, kind_values=frozenset(members.values())
    )
    if len(tables) != 1:
        raise AssertionError(
            f"显示名表应为恰好一处（{MEMORY_KIND_LABEL_FILE}），现算 {len(tables)} 处："
            f"{[(t.file, t.line, len(t.entries)) for t in tables]}"
        )
    table = tables[0]
    by_member = {key_form.split(".")[-1]: label for key_form, label, _line in table.entries}
    # 表以枚举**成员名**为键 → 换算回枚举**值**（记忆行里存的是值），供跨文件比对用。
    by_kind = {members[name]: label for name, label in by_member.items() if name in members}
    return members, table, by_kind


@lru_cache(maxsize=1)
def scan_gate1() -> tuple[dict[str, list[KindLabelTable]], dict[str, list[tuple[int, str]]], int]:
    """全 ``plugins/`` 扫：词表出现在哪些文件 / 字面量抄到哪些文件 / 扫了几个文件。

    缓存的是**结果**（本机有 OOM 前科，不缓存 AST）；判据本身是纯函数。
    """
    members, _table, by_kind = memory_kind_truth()
    kind_values = frozenset(members.values())
    labels = frozenset(by_kind.values())
    tables: dict[str, list[KindLabelTable]] = {}
    copies: dict[str, list[tuple[int, str]]] = {}
    scanned = 0
    for path in _py_files(GATE1_SCAN_ROOT):
        scanned += 1
        rel = _rel(path)
        tree = _load_tree(path)
        found = kind_label_tables(tree, rel=rel, kind_values=kind_values)
        if found:
            tables[rel] = found
        hit = kind_label_copies(tree, rel=rel, canonical_file=MEMORY_KIND_LABEL_FILE, labels=labels)
        if hit:
            copies[rel] = hit
    return tables, copies, scanned


def test_gate1_truth_locations_are_what_the_ledger_claims() -> None:
    """类型真身是封闭枚举；显示名表只有一处且**只以枚举成员为键**（无幽灵键）。"""
    members, table, by_kind = memory_kind_truth()
    assert len(members) >= 4, f"MemoryKind 成员数骤减为 {len(members)}：枚举真身被动过，本门判据需重算"
    assert table.keyed_on_enum, (
        f"显示名表 {table.file}:{table.line} 出现了**字符串键**＝枚举之外的手抄项，"
        "这正是「第二真身」的开局形态（键型注解挡住幽灵键的那条口径被绕开了）"
    )
    assert len(by_kind) == len(table.entries), "表里出现了 MemoryKind 之外的键（幽灵类型标签）"


def test_gate1_no_kind_label_literal_outside_the_canonical_table() -> None:
    """词表字面量在第三个文件里再出现一份 ⇒ 红（本波的「第三份手抄」就是这个形状）。"""
    tables, copies, _scanned = scan_gate1()
    offenders = {rel: hits for rel, hits in copies.items() if rel != MEMORY_KIND_LABEL_FILE}
    extra_tables = {rel: t for rel, t in tables.items() if rel != MEMORY_KIND_LABEL_FILE}
    assert not offenders and not extra_tables, (
        f"记忆类型中文词表出现第二真身：抄件={ {k: v[:2] for k, v in offenders.items()} }"
        f"，额外词表={ [(f, t[0].line) for f, t in extra_tables.items()] }。"
        f"修法：只调 {MEMORY_KIND_LABEL_FILE}::_memory_kind_label，不另立词表"
    )


def test_gate1_poison_second_hand_copy_is_caught() -> None:
    """注毒：造一份字符串键的第二词表塞进第三个文件 ⇒ 同一把尺子必须现红。

    毒样**由真身派生**（本席自己不手写任何标签字面量）——我抄一份就成了第四份真身。
    """
    _members, _table, by_kind = memory_kind_truth()
    rows = ",\n".join(
        f'        "{kind}": "{label}"' for kind, label in sorted(by_kind.items())
    )
    poisoned = (
        "def _summarize(kind):\n"
        "    _KIND_LABELS = {\n"
        + rows
        + "\n    }\n"
        "    return _KIND_LABELS.get(kind, kind)\n"
    )
    rel = f"{PKG_REL}/domains/chat_reply/character/reflection.py"
    tree = _parse(poisoned)
    tables = kind_label_tables(tree, rel=rel, kind_values=frozenset(by_kind))
    copies = kind_label_copies(
        tree, rel=rel, canonical_file=MEMORY_KIND_LABEL_FILE, labels=frozenset(by_kind.values())
    )
    assert len(tables) == 1, "注毒未被打成第二词表：本门对「字符串键手抄」失明"
    assert not tables[0].keyed_on_enum, "注毒被打成了 enum 键表：键形态判定失效"
    assert len(copies) >= 2, f"注毒的字面量抄件没被抓到（现算 {copies}）"


def test_gate1_poison_single_stray_literal_is_caught() -> None:
    """注毒第二发：不抄整表、只把标签字面量焊进别处 ⇒ 等值形与子串形都要现红。"""
    _members, _table, by_kind = memory_kind_truth()
    one = min(by_kind.values())
    rel = f"{PKG_REL}/domains/chat_reply/capabilities/echo.py"
    labels = frozenset(by_kind.values())
    for source in (
        f'HEADINGS = ("{one}", "别的")',
        f'TEMPLATE = "【{one}】附说明"',
    ):
        hits = kind_label_copies(
            _parse(source), rel=rel, canonical_file=MEMORY_KIND_LABEL_FILE, labels=labels
        )
        assert hits, f"标签散抄未被抓到（形如 {source!r}）：门只拦整表＝门只覆盖被抓过的那一件"


def test_gate1_legit_derivation_and_prose_are_not_flagged() -> None:
    """反向锁：合法派生（引用枚举、调真身）与 docstring 转述都不得误报。"""
    _members, _table, by_kind = memory_kind_truth()
    one_label = min(by_kind.values())
    legit = f'''
"""渲染侧说明：类型标签形如「{one_label}」，词表派生自 MemoryKind，本层不另立名单。"""

from .memory_service import MemoryKind
from .providers import _memory_kind_label


def decorate(kind: str) -> str:
    # 注释里再提一次「{one_label}」也不算抄件
    return _memory_kind_label(MemoryKind(kind))
'''
    rel = f"{PKG_REL}/domains/chat_reply/character/persona_injection.py"
    tree = _parse(legit)
    assert kind_label_copies(
        tree, rel=rel, canonical_file=MEMORY_KIND_LABEL_FILE, labels=frozenset(by_kind.values())
    ) == [], "docstring/注释里的转述被判成词表抄件＝本门退回了 grep 口径"
    assert kind_label_tables(tree, rel=rel, kind_values=frozenset(by_kind)) == []


def test_gate1_scan_surface_has_not_collapsed() -> None:
    """扫描面塌陷锁：文件数与「全树可解析」两发都在，防「扫得少」被读成「没违规」。"""
    _tables, _copies, scanned = scan_gate1()
    assert scanned >= GATE1_MIN_SCANNED_FILES, (
        f"门 ① 只扫到 {scanned} 个文件（下限 {GATE1_MIN_SCANNED_FILES}）＝扫描面被改小，"
        "此时的零违规不可信"
    )


# ===========================================================================
# 门 ②：宿主机读数的取数口（账门 · 只报现状，修由 S-T-HOST-2 做）
# ===========================================================================

#: 事实名 → 读点标识符（只认属性访问与 ``getattr(obj, "字面量")``，见 `_host_metric_reads`）。
HOST_METRIC_READS: dict[str, frozenset[str]] = {
    "cpu_cores": frozenset({"cpu_count"}),
    "cpu_percent": frozenset({"cpu_percent", "getloadavg"}),
    "cpu_model": frozenset({"processor"}),
    "memory": frozenset({"virtual_memory"}),
    "swap": frozenset({"swap_memory"}),
    "disk": frozenset({"disk_usage", "disk_partitions"}),
    "boot_time": frozenset({"boot_time"}),
    "self_process": frozenset({"memory_info", "cpu_times"}),
}
#: 外部读法（注册表扫描 / 子进程命令）只能按字符串常量**子串**认——命令与键名本身就是
#: 字面量。与 reads 的区别另有两条：① 只看代码串（docstring 里「本件复用了谁」不算读点）；
#: ② 键名串**不算**（``source="psutil.cpu_count"`` 这类归因标签是给读数起的名字）。
#: ⚠ 这里刻意不放 "ProcessorNameString"/"DriverDesc" 之外的宽松词，也不放纯标签串：
#: 注册表读数已由 ``_cpu_label`` 的 ``winreg`` 调用与 ``platform.processor`` 覆盖，
#: 再加宽就会把「归因标签」读成「取数口」（本门第一版就是这样多算了 3 处）。
HOST_METRIC_MARKERS: dict[str, tuple[str, ...]] = {
    "gpu_smi": ("nvidia-smi",),
    "gpu_model_registry": ("DriverDesc",),
}
GATE2_SCAN_ROOT = PKG_ROOT
GATE2_MIN_SCANNED_FILES = 550

_HOSTS = f"{PKG_REL}/domains/ops/host_metrics.py"
_STATUS = f"{PKG_REL}/domains/ops/monitor/host_status.py"
_RESOURCES = f"{PKG_REL}/control_plane/resources.py"

#: 允许持有宿主读数的文件（**归属账**，不是「今天谁在读」的快照账）：
#: - ``host_metrics.py``＝需求 5 的新取数件（S-T-HOST-1 建，S-T-HOST-2 正在把读数并进来）；
#: - ``monitor/host_status.py``＝旧取数件（收敛中，读点会陆续消失）；
#: - ``control_plane/resources.py``＝控制面自己的进程资源采样口（另一条链的既成事实，
#:   与 WebUI 资源页同源，不属于本波要收的「宿主呈现读数」，先入账不拦）。
#: 第三家伸手读 psutil/注册表/nvidia-smi ⇒ 当场红。owner 在这两份真身之间**怎么搬都不撞
#: 本账**——搬读数不该被门的账逼着同步改判据（那是撞在飞席的账，本波实证过那种门会被删）。
HOST_METRIC_READER_ALLOWLIST: frozenset[str] = frozenset({_HOSTS, _STATUS, _RESOURCES})
#: 一枚事实最多允许几处真身各取一遍：今天实况是 2（新旧两份并行），第三份就是抄件。
GATE2_MAX_READERS_PER_FACT = 2
#: 手写字面量上限（不许写成 len(...) 派生）：2026-09-26 现算「被 ≥2 处取数的宿主事实」数。
#: S-T-DUPE-1 落笔时是 9（新旧两份并行）；S-T-HOST-2 把 host_status 读数收空后本席复算
#: 只剩 1（self_process）——按其用例 docstring 写明的跟随规程降账并追加核账行。
GATE2_MULTI_READER_FACT_CEILING = 1
#: 逐次核账（日期, 当时的数）：**必须单调不升**——想调大就得同时违反这条，当场红。
GATE2_AUDIT_LOG: tuple[tuple[str, int], ...] = (("2026-09-26 S-T-DUPE-1 初账", 9), ("2026-09-26 S-T-DUPE-1R 复算", 1))

#: fact → 允许取该数的身付（**归属账**）＝今日现算读数 ∪ 两份 owner 真身互搬余量。
#: S-T-DUPE-1 阵亡时两处用例（`test_gate2_no_module_reads_host_metrics_beyond_the_ledger` /
#: `test_gate2_poison_extra_reader_is_caught`）已写、本定义未落盘——S-T-DUPE-1R 按该文件
#: 写明的设计意图补全：把读数在 ``host_metrics.py`` ⇄ ``host_status.py`` 之间**怎么搬都不撞
#: 本账**（两份真身彼此都在对方读过的每个 fact 上被预先放行；控制面 ``resources.py`` 只进
#: 它今天真读的 ``self_process``，它扩读别家即点名）。第三个文件来抄取数 ⇒ 当场红。
#: 单向账（实况 ⊆ 账）：收敛（读数消失）不需要动本账；扩读/新文件/新 fact 未入账才红。
HOST_METRIC_READ_LEDGER: dict[str, frozenset[str]] = {
    "boot_time": frozenset({_HOSTS, _STATUS}),
    "cpu_cores": frozenset({_HOSTS, _STATUS}),
    "cpu_model": frozenset({_HOSTS, _STATUS}),
    "cpu_percent": frozenset({_HOSTS, _STATUS}),
    "disk": frozenset({_HOSTS, _STATUS}),
    "gpu_model_registry": frozenset({_HOSTS, _STATUS}),
    "gpu_smi": frozenset({_HOSTS, _STATUS}),
    "memory": frozenset({_HOSTS, _STATUS}),
    "self_process": frozenset({_HOSTS, _STATUS, _RESOURCES}),
    "swap": frozenset({_HOSTS, _STATUS}),
}

def _host_metric_reads(tree: ast.AST, *, rel: str) -> dict[str, list[int]]:
    """一段源码里真正的宿主读数点：``fact → 行号``。

    三形态才算读点：① ``x.virtual_memory()`` 这类属性访问；② ``getattr(psutil,
    "boot_time", …)`` 的字面量参数；③ 外部读法的命令/键名子串（非 docstring）。
    而 ``MetricSpec("cpu_percent", …)`` 的指标 id、``cpu_percent: float`` 的字段名、
    ``source="psutil.cpu_count"`` 的归因标签**都不算**——那是给读数起的名字，不是取数。
    """
    found: dict[str, set[int]] = collections.defaultdict(set)
    attr_tokens = {tok: fact for fact, toks in HOST_METRIC_READS.items() for tok in toks}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in attr_tokens:
            found[attr_tokens[node.attr]].add(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            arg = node.args[1] if len(node.args) >= 2 else None
            if (
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value in attr_tokens
            ):
                found[attr_tokens[arg.value]].add(node.lineno)
    for fact, markers in HOST_METRIC_MARKERS.items():
        for line, text in _code_strings(tree):
            if any(marker in text for marker in markers):
                found[fact].add(line)
    return {fact: sorted(lines) for fact, lines in sorted(found.items())}


def collect_host_metric_reads() -> dict[str, dict[str, list[int]]]:
    observed: dict[str, dict[str, list[int]]] = {}
    for path in _py_files(GATE2_SCAN_ROOT):
        rel = _rel(path)
        for fact, lines in _host_metric_reads(_load_tree(path), rel=rel).items():
            observed.setdefault(fact, {})[rel] = lines
    return observed


@lru_cache(maxsize=1)
def gate2_observed_by_file() -> dict[str, dict[str, list[int]]]:
    """现算的「fact → 正在读它的文件（排序）」。缓存结果不缓存 AST。"""
    return {fact: {mod: list(lines) for mod, lines in sorted(mods.items())} for fact, mods in sorted(collect_host_metric_reads().items())}


def _ledger_violations(
    observed: dict[str, set[str]], ledger: dict[str, frozenset[str]]
) -> dict[str, list[str]]:
    """账外新增：某 fact 的读点文件里出现了本门没登记的名字（=又长了一处抄取数）。"""
    return {
        fact: sorted(mods - ledger.get(fact, frozenset()))
        for fact, mods in observed.items()
        if mods - ledger.get(fact, frozenset())
    }


def test_gate2_no_module_reads_host_metrics_beyond_the_ledger() -> None:
    """新增抄取数当场红（这一发是本门对下游唯一的硬约束）。

    **刻意只做单向**：owner（S-T-HOST-2）正在把读数往一处收，收完 host_status 的读数
    会消失——那时本发照样绿（子集方向永远放行），要他们做的是把
    ``GATE2_MULTI_READER_FACT_CEILING`` 改小并在 ``GATE2_AUDIT_LOG`` 追加一行。
    双向对账会把「正在收敛」当成红，撞在飞 owner 的账，本波实证过那种门会被直接删。
    """
    observed = {fact: set(mods) for fact, mods in gate2_observed_by_file().items()}
    extra = _ledger_violations(observed, HOST_METRIC_READ_LEDGER)
    assert not extra, (
        f"又长了抄取数的文件：{extra}。修法：调已登记真身（`host_metrics` 或 "
        "`host_status.cached_host_snapshot`），不要自己再读一次 psutil/注册表/nvidia-smi"
    )


def test_gate2_ledger_is_self_consistent_and_reader_cap_is_live() -> None:
    """账自身不许长歪（两枚在册常量的执法腿，S-T-DUPE-1 定义了却没接线）。

    ① ``HOST_METRIC_READER_ALLOWLIST`` 必须是账的上界：账里冒出身付之外的文件
       ＝有人**改账放行**而不是改代码收敛，当场红；
    ② 今天被读到的 fact 必须都在账上有行：没行＝新取数形态绕过登记（`_ledger_violations`
       对缺行 fact 会把全部读点判成账外，这条锁先给出现象更好读的点名）；
    ③ ``GATE2_MAX_READERS_PER_FACT`` 执法：一枚事实被超过 2 处真身各取一遍＝第三份抄件。
    """
    observed = {fact: set(mods) for fact, mods in gate2_observed_by_file().items()}
    over = {
        fact: sorted(mods - HOST_METRIC_READER_ALLOWLIST)
        for fact, mods in HOST_METRIC_READ_LEDGER.items()
        if mods - HOST_METRIC_READER_ALLOWLIST
    }
    assert not over, f"归属账里出现允许身付之外的文件（改账≠收敛）：{over}"
    unledgered = sorted(set(observed) - set(HOST_METRIC_READ_LEDGER))
    assert not unledgered, (
        f"这些宿主事实今天有人读、账上却没有行：{unledgered}。新取数形态先入账再落地"
        "（登记时把真实读数与互搬余量一起写清楚，别只抄快照）"
    )
    fat = {
        fact: sorted(mods)
        for fact, mods in observed.items()
        if len(mods) > GATE2_MAX_READERS_PER_FACT
    }
    assert not fat, (
        f"一枚事实被 >{GATE2_MAX_READERS_PER_FACT} 处各取一遍：{fat}——第三份就是抄件，"
        "调已登记真身，别再加读者"
    )


def test_gate2_multi_reader_facts_do_not_grow() -> None:
    """棘轮只降不升：被 ≥2 个文件各读一遍的事实数量。"""
    observed = {fact: set(mods) for fact, mods in gate2_observed_by_file().items()}
    multi = sorted(fact for fact, mods in observed.items() if len(mods) >= 2)
    assert len(multi) <= GATE2_MULTI_READER_FACT_CEILING, (
        f"重复取数的事实从 {GATE2_MULTI_READER_FACT_CEILING} 涨到 {len(multi)}：{multi}。"
        "收敛方向是允许的，涨就是又长了抄件"
    )
    counts = [value for _date, value in GATE2_AUDIT_LOG]
    assert counts == sorted(counts, reverse=True), f"核账记录必须单调不升，现为 {GATE2_AUDIT_LOG}"
    assert len(multi) > 0 or GATE2_MULTI_READER_FACT_CEILING == 0, (
        "账门空跑：实况已零抄件却还留着上限——请把上限改成 0 并追加核账行"
    )


def test_gate2_poison_extra_reader_is_caught() -> None:
    """注毒：一个新文件自己读 psutil ⇒ 同一把尺子点名 + 账判成账外新增。"""
    poisoned = """
import psutil


def my_status():
    vm = psutil.virtual_memory()
    cores = psutil.cpu_count()
    return vm.total, cores
"""
    intruder = f"{PKG_REL}/domains/xxx/extra.py"
    found = _host_metric_reads(_parse(poisoned), rel=intruder)
    assert set(found) == {"cpu_cores", "memory"}, f"注毒读数失真：{found}"
    observed = {fact: set(mods) for fact, mods in gate2_observed_by_file().items()}
    for fact in found:
        observed.setdefault(fact, set()).add(intruder)
    extra = _ledger_violations(observed, HOST_METRIC_READ_LEDGER)
    assert "memory" in extra and intruder in extra["memory"], f"注毒未被账判成账外新增：{extra}"


def test_gate2_delegating_consumer_is_not_a_read_point() -> None:
    """反向锁：调真身 + 给读数起名字/写归因标签，都不算取数口。"""
    legit = """
from plugins.bot_unified_runtime.domains.ops import host_metrics
from plugins.bot_unified_runtime.domains.ops.monitor import host_status

SPEC_ID = "cpu_percent"          # 指标 id，不是读点
SOURCE_NOTE = "psutil.cpu_count"  # 归因标签，不是读点
boot_time: float | None = None    # 字段名，不是读点


def render():
    report = host_metrics.collect_host_metrics_sync()
    groups, taken_at = host_status.cached_host_snapshot(allow_blocking=False)
    return report, groups, taken_at, SPEC_ID, SOURCE_NOTE
"""
    found = _host_metric_reads(_parse(legit), rel="plugins/bot_unified_runtime/domains/yyy/consumer.py")
    assert found == {}, f"合法委托被判成取数口：{found}"


def test_gate2_metric_declaration_literals_are_not_reads() -> None:
    """反向锁（真树版）：真身文件里的 `MetricSpec("cpu_percent", …)` 与归因串不误判。

    这一发钉的是判据精度：`host_metrics.py` 的读数行号必须落在**调用行**上，
    不能因为文件里出现了 "cpu_percent" 这个词就把说明书那几行也算成读点。
    """
    observed = gate2_observed_by_file()
    lines = observed.get("cpu_percent", {}).get(_HOSTS) or []
    source = (REPO_ROOT / _HOSTS).read_text(encoding="utf-8").splitlines()
    for line_no in lines:
        text = source[line_no - 1]
        assert "cpu_percent" not in text or "MetricSpec" not in text, (
            f"{_HOSTS}:{line_no} 把指标声明算成了读点：{text!r}"
        )


def test_gate2_scan_surface_has_not_collapsed() -> None:
    scanned = len(_py_files(GATE2_SCAN_ROOT))
    uncovered = extensionless_python_files(GATE2_SCAN_ROOT)
    assert not uncovered, (
        f"扫描面里有**没有 .py 后缀却是 Python** 的件：{uncovered}——"
        "本波实锤过 `rglob('*.py')` 会把这类入口垫片整个看成「不存在」"
    )
    assert scanned >= GATE2_MIN_SCANNED_FILES, (
        f"门 ② 只扫到 {scanned} 个文件（下限 {GATE2_MIN_SCANNED_FILES}）＝扫描面被改小"
    )


def test_gate2_scanned_tree_is_fully_parseable() -> None:
    """全树可解析锁：解析失败＝扫描被静默截短，任何读数都不可信。

    本机已知 D-8（并发席半写 ``domains/core/safety_exec/paths.py``）会让这一发短时红：
    等 60 秒重跑即可，**不许**加排除名单或改成「跳过不可解析文件」。
    """
    bad: list[str] = []
    for path in _py_files(GATE1_SCAN_ROOT):
        try:
            _load_tree(path)
        except SyntaxError as exc:
            bad.append(f"{_rel(path)}: {type(exc).__name__} line {exc.lineno}")
    assert not bad, f"扫描面里有不可解析文件（受 D-8 影响则重跑）：{bad}"


# ===========================================================================
# 门 ③：domains/meme/ 的主体判定口与准入门
# ===========================================================================

MEME_SCAN_ROOT = PKG_ROOT / "domains" / "meme"
MEME_MIN_SCANNED_FILES = 12
#: 主体判定（「这张图是不是她」）的唯一真身。
MEME_SUBJECT_CANONICAL = f"{PKG_REL}/domains/meme/sources/shorekeeper_absorb.py"
#: 判定口的三枚件：词表来源 / 命中判定 / 别名边界。任何一枚出现第二份 def 就是第二真身。
MEME_SUBJECT_PREDICATES: tuple[str, ...] = ("persona_subject_terms", "subject_hit", "_alias_pattern")
#: 中央人格别名口：域内只准真身那一个模块去够它（其余人伸手=把中央件的形状抄进 meme 域）。
MEME_CENTRAL_ALIAS_SOURCE = "persona_alias_terms"


def _meme_subject_findings(tree: ast.AST, *, rel: str) -> list[tuple[str, str, int]]:
    """`meme` 域内与主体判定有关的痕迹：``(形态, 名字, 行号)``。

    三形态分开数：**definition**（自己写了一份判定件＝第二真身）、
    **central-source-call**（绕过真身自己去够中央人格别名口）、
    **reference**（引用真身的判定件＝合法消费侧，本门要看得见它，否则「零消费者」
    会被读成「没人抄了」）。
    """
    out: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in MEME_SUBJECT_PREDICATES:
            out.append(("definition", node.name, node.lineno))
        elif isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id == MEME_CENTRAL_ALIAS_SOURCE)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == MEME_CENTRAL_ALIAS_SOURCE)
        ):
            out.append(("central-source-call", MEME_CENTRAL_ALIAS_SOURCE, node.lineno))
        elif isinstance(node, ast.Name) and node.id in MEME_SUBJECT_PREDICATES:
            out.append(("reference", node.id, node.lineno))
        elif isinstance(node, ast.Attribute) and node.attr in MEME_SUBJECT_PREDICATES:
            out.append(("reference", node.attr, node.lineno))
    return sorted(set(out))


def collect_meme_subject_homes() -> dict[str, list[tuple[str, str, int]]]:
    found: dict[str, list[tuple[str, str, int]]] = {}
    for path in _py_files(MEME_SCAN_ROOT):
        hits = _meme_subject_findings(_load_tree(path), rel=_rel(path))
        if hits:
            found[_rel(path)] = hits
    return found


@lru_cache(maxsize=1)
def gate3_subject_homes() -> dict[str, tuple[tuple[str, str, int], ...]]:
    return {rel: tuple(hits) for rel, hits in collect_meme_subject_homes().items()}


def test_gate3_subject_determination_has_exactly_one_home() -> None:
    """每枚判定件全域恰好一处 def，且中央别名口全域只被真身够一次。"""
    homes = gate3_subject_homes()
    defs: dict[str, list[tuple[str, int]]] = collections.defaultdict(list)
    central: list[tuple[str, int]] = []
    for rel, hits in homes.items():
        for kind, name, line in hits:
            if kind == "definition":
                defs[name].append((rel, line))
            elif kind == "central-source-call":
                central.append((rel, line))
    dupes = {name: spots for name, spots in defs.items() if len(spots) > 1}
    assert not dupes, f"主体判定件出现第二处真身：{dupes}。修法：从 {MEME_SUBJECT_CANONICAL} 导入"
    misplaced = {
        name: spots for name, spots in defs.items() if any(rel != MEME_SUBJECT_CANONICAL for rel, _line in spots)
    }
    assert not misplaced, f"主体判定件不在唯一真身里：{misplaced}"
    assert len(central) == 1 and central[0][0] == MEME_SUBJECT_CANONICAL, (
        f"中央人格别名口 `persona_alias_terms` 的够取点应当恰好一枚且在真身里，现算 {central}。"
        "第二处够取＝把中央件的降级口径抄进 meme 域（「读不到时返回空表」这件事会有两种做法）"
    )


def test_gate3_subject_consumers_reach_the_home_by_import() -> None:
    """消费侧看得见且只准引用真身：引用判定件名字的模块不得自己 def 一份。"""
    homes = gate3_subject_homes()
    consumers: dict[str, list[str]] = {}
    for rel, hits in homes.items():
        if rel == MEME_SUBJECT_CANONICAL:
            continue
        names = sorted({name for kind, name, _line in hits if kind == "reference"})
        definitions = [name for kind, name, _line in hits if kind == "definition"]
        assert not definitions, f"{rel} 自己定义了主体判定件 {definitions}＝第二真身"
        if names:
            consumers[rel] = names
    assert consumers, (
        "meme 域里没有任何模块引用主体判定件——要么判定口被搬空（上一发会先红），"
        "要么扫描面被改小（另有塌陷锁）；这里挡的是「门自己变空跑」"
    )


def test_gate3_poison_second_subject_home_is_caught() -> None:
    """注毒：另一个 meme 模块自己写一份 `subject_hit` ⇒ 同一把尺子点名。"""
    poisoned = """
import re


def subject_hit(text: str, terms) -> str:
    for term in terms:
        if term in text:
            return term
    return ""
"""
    rel = f"{PKG_REL}/domains/meme/sources/meme_selection.py"
    hits = _meme_subject_findings(_parse(poisoned), rel=rel)
    assert ("definition", "subject_hit", 5) in hits, f"注毒未被抓到：{hits}"


def test_gate3_poison_second_central_reach_is_caught() -> None:
    """注毒第二发：另一个模块绕过真身、自己去够中央别名口。"""
    poisoned = """
from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import persona_alias_terms


def my_terms(config):
    return tuple(persona_alias_terms(config))
"""
    hits = _meme_subject_findings(_parse(poisoned), rel=f"{PKG_REL}/domains/meme/sources/meme_selection.py")
    assert any(kind == "central-source-call" for kind, _n, _l in hits), f"绕真身够中央件未被抓到：{hits}"


# ---- 准入阈值抄件账（NSFW：config.py 的两枚键才是真身，此处登记字面量抄在哪）----

MEME_CONFIG_FILE = f"{PKG_REL}/config.py"
#: 阈值形判定：比较式 / 具名参数缺省 / SQL 文本；**不**看防御性缺省（见反向锁）。
NSFW_NAME_HINTS = ("nsfw",)
_INTAKE_LEDGER_LIB = f"{PKG_REL}/domains/meme/sources/meme_library.py"
_INTAKE_LEDGER_ENGINE = f"{PKG_REL}/domains/meme/reactions/engine.py"
#: 2026-09-26 现算：``(文件, 形态, 值) → 处数``。
MEME_INTAKE_THRESHOLD_LEDGER: dict[tuple[str, str, float], int] = {
    (_INTAKE_LEDGER_LIB, "compare", 0.8): 1,
    (_INTAKE_LEDGER_LIB, "compare", 0.2): 1,
    (_INTAKE_LEDGER_LIB, "kw-default", 0.2): 2,
    (_INTAKE_LEDGER_LIB, "sql", 0.8): 1,
    (_INTAKE_LEDGER_ENGINE, "kw-default", 0.2): 1,
}


def config_float_defaults(source: str, *, prefixes: tuple[str, ...] = ("bot_meme_library_nsfw",)) -> dict[str, float]:
    """从 config 真身现算「哪几枚准入阈值、缺省是多少」（值不由本席手抄）。"""
    out: dict[str, float] = {}
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if (
                name.startswith(prefixes)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, (int, float))
            ):
                out[name] = float(node.value.value)
    return out


def _is_threshold_arg(arg_name: str) -> bool:
    lowered = arg_name.lower()
    return any(hint in lowered for hint in NSFW_NAME_HINTS) and not lowered.endswith("_score")


def meme_intake_threshold_copies(tree: ast.AST, *, rel: str) -> list[tuple[int, str, float]]:
    """准入门阈值的**字面量抄件**：比较式、参数缺省、SQL 文本三形态。"""
    out: list[tuple[int, str, float]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(_mentions(op, hint) for op in operands for hint in NSFW_NAME_HINTS):
                for op in operands:
                    if isinstance(op, ast.Constant) and isinstance(op.value, (int, float)):
                        out.append((node.lineno, "compare", float(op.value)))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg, default in zip(args.kwonlyargs, args.kw_defaults):
                if (
                    default is not None
                    and _is_threshold_arg(arg.arg)
                    and isinstance(default, ast.Constant)
                    and isinstance(default.value, (int, float))
                ):
                    out.append((arg.lineno, "kw-default", float(default.value)))
            n_defaults = len(args.defaults)
            positional = [*args.posonlyargs, *args.args]
            if n_defaults:
                for arg, default in zip(positional[len(positional) - n_defaults :], args.defaults):
                    if (
                        _is_threshold_arg(arg.arg)
                        and isinstance(default, ast.Constant)
                        and isinstance(default.value, (int, float))
                    ):
                        out.append((arg.lineno, "pos-default", float(default.value)))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for match in re.findall(r"nsfw\w*\s*(?:>=|<=|>|<|=)\s*([0-9]*\.?[0-9]+)", node.value):
                out.append((node.lineno, "sql", float(match)))
    return sorted(out)


def collect_meme_intake_threshold_copies() -> dict[tuple[str, str, float], int]:
    counts: dict[tuple[str, str, float], int] = collections.Counter()
    for path in _py_files(MEME_SCAN_ROOT):
        for _line, shape, value in meme_intake_threshold_copies(_load_tree(path), rel=_rel(path)):
            counts[(_rel(path), shape, value)] += 1
    return dict(counts)


@lru_cache(maxsize=1)
def gate3_intake_copies() -> dict[tuple[str, str, float], int]:
    return collect_meme_intake_threshold_copies()


def test_gate3_intake_threshold_copies_match_the_ledger() -> None:
    """存量抄件逐处登记：新增一处红（账门，只报现状 + 防回潮）。"""
    observed = gate3_intake_copies()
    extra = {
        key: n - MEME_INTAKE_THRESHOLD_LEDGER.get(key, 0)
        for key, n in observed.items()
        if n > MEME_INTAKE_THRESHOLD_LEDGER.get(key, 0)
    }
    assert not extra, (
        f"meme 准入门阈值又长了抄件：{extra}。\n"
        f"  实况：{ {k: v for k, v in sorted(observed.items())} }\n"
        f"  真身：config.py 的 bot_meme_library_nsfw_max / bot_meme_library_nsfw_delete"
        "——改成读配置，别在决策点写字面量"
    )


def test_gate3_intake_ledger_has_no_ghost_entries() -> None:
    """账里的每一条今天都还在（搬掉了却不降账＝幽灵条目，下一位读账的人会被骗）。"""
    observed = gate3_intake_copies()
    ghosts = {key: n for key, n in MEME_INTAKE_THRESHOLD_LEDGER.items() if observed.get(key, 0) < n}
    assert not ghosts, (
        f"抄件已被搬掉但账未跟随：{ghosts}。把 MEME_INTAKE_THRESHOLD_LEDGER 改小并在此文件"
        "注明日期与收敛者（这一发是「一处变更处处跟随」，不是拦收敛）"
    )


def test_gate3_threshold_copies_are_all_config_values() -> None:
    """抄件值必须仍是「配置缺省那两个数」：冒出第三个拍脑袋的阈值 ⇒ 当场红。

    这一发与上一发是两回事：账只保证「没长新抄件」，本发保证「抄的东西还没跑偏」。
    """
    truth = config_float_defaults((REPO_ROOT / MEME_CONFIG_FILE).read_text(encoding="utf-8"))
    assert len(truth) >= 2, f"config 真身里读不到 meme 的 NSFW 阈值键（现算 {truth}）＝判据失去锚点"
    allowed = set(truth.values())
    observed = collect_meme_intake_threshold_copies()
    strays = {key: n for key, n in observed.items() if key[2] not in allowed}
    assert not strays, f"出现了既不在配置真身里、也没登记过的准入阈值字面量：{strays}（配置现算 {truth}）"


def test_gate3_poison_new_intake_threshold_is_caught() -> None:
    """注毒：未登记的文件里写一条 nsfw 比较式 ⇒ 同一把尺子点名 + 账判成新增。"""
    poisoned = """
def decide(score: float) -> bool:
    nsfw = float(score)
    if nsfw >= 0.75:
        return True
    return False
"""
    rel = f"{PKG_REL}/domains/meme/capabilities/meme.py"
    hits = meme_intake_threshold_copies(_parse(poisoned), rel=rel)
    assert any(shape == "compare" and value == 0.75 for _line, shape, value in hits), (
        f"注毒阈值未被抓到：{hits}"
    )
    observed = dict(MEME_INTAKE_THRESHOLD_LEDGER)
    observed[(rel, "compare", 0.75)] = observed.get((rel, "compare", 0.75), 0) + 1
    assert observed != MEME_INTAKE_THRESHOLD_LEDGER, "注毒后的账与在册账相同＝账门形同虚设"
    extra = {k: n for k, n in observed.items() if n > MEME_INTAKE_THRESHOLD_LEDGER.get(k, 0)}
    assert extra == {(rel, "compare", 0.75): 1}, f"账门未把注毒判成账外新增：{extra}"


def test_gate3_defensive_config_read_is_not_a_copy() -> None:
    """反向锁：`float(getattr(config, "…nsfw_max", 0.2) or 0.2)` 是**读真身**，不算抄件。

    门只拦「决定性的字面量」（比较式/参数缺省/SQL），防御性缺省硬要拦就会把
    所有正常读配置的写法一起打死——那种门会被下一个席直接删掉。
    """
    legit = """
def pick(config):
    nsfw_max = float(getattr(config, "bot_meme_library_nsfw_max", 0.2) or 0.2)
    nsfw_score = float(row["nsfw_score"] or 0.0)
    return nsfw_max, nsfw_score
"""
    assert meme_intake_threshold_copies(_parse(legit), rel="memetest") == []


def test_gate3_subject_reference_without_definition_is_clean() -> None:
    """反向锁：从真身 import 判定件再调用，不得被判成**第二处真身**。

    S-T-DUPE-1R 改写判定（正路①·锁自身误报）：finder 的 docstring 把形态分成三种，
    `reference` 是**刻意要看得见**的合法消费侧痕迹——`test_gate3_subject_consumers_
    reach_the_home_by_import` 整个建立在它存在之上。旧断言 `hits == []` 要求 finder
    对自己的核心设计失明，在 finder 不坏的前提下永远不可能绿。真语义＝合法引用**只准**
    产出 `reference` 形态；`definition`（自己 def 一份判定件）与 `central-source-call`
    （绕真身够中央件）才是「第二真身」。本改写同时**加严**不放宽：断言两枚判定件名字
    都可见，防「消费痕迹看不见＝没问题」的另一种空跑。
    """
    legit = """
from plugins.bot_unified_runtime.domains.meme.sources.shorekeeper_absorb import (
    persona_subject_terms,
    subject_hit,
)


def needs(config):
    return subject_hit("任意文本", persona_subject_terms(config))
"""
    hits = _meme_subject_findings(_parse(legit), rel=f"{PKG_REL}/domains/meme/capabilities/meme.py")
    kinds = {kind for kind, _name, _line in hits}
    assert kinds <= {"reference"}, f"合法引用被判成判定件副本：{hits}"
    names = {name for kind, name, _line in hits if kind == "reference"}
    assert {"persona_subject_terms", "subject_hit"} <= names, (
        f"合法消费侧的引用痕迹应当可见（看不见消费者的门会把「被搬空」读成「没人抄了」）：{hits}"
    )


def test_gate3_scan_surface_has_not_collapsed() -> None:
    scanned = len(_py_files(MEME_SCAN_ROOT))
    assert scanned >= MEME_MIN_SCANNED_FILES, (
        f"门 ③ 只扫到 {scanned} 个 meme 域文件（下限 {MEME_MIN_SCANNED_FILES}）＝扫描面被改小"
    )


def test_gate3_canonical_homes_are_where_the_ledger_says() -> None:
    """真身位置锁：判定件搬家（改名/挪文件）时本门必须现红，而不是安静地看不见。"""
    homes = gate3_subject_homes()
    names_in_canonical = {name for rel, hits in homes.items() if rel == MEME_SUBJECT_CANONICAL for _k, name, _l in hits}
    assert set(MEME_SUBJECT_PREDICATES) <= names_in_canonical, (
        f"{MEME_SUBJECT_CANONICAL} 里缺判定件：{sorted(set(MEME_SUBJECT_PREDICATES) - names_in_canonical)}"
        "——搬家就改 MEME_SUBJECT_CANONICAL 与本账，别把判据改松"
    )
