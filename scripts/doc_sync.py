"""机器事实册自动同步（交叉验证机制·文档层，2026-09-13）。

`docs/auto-facts.md` 整册由本脚本从代码机械推导生成——**全册机器所有，
人工不要手改**（叙述类文档在 AGENTS/HANDBOOK，机器只管"数字和清单"类事实）。

用法：
    python scripts/doc_sync.py --write   # 从代码重生成整册
    python scripts/doc_sync.py --check   # 漂移检测（退出码非 0 = 不同步）
    python scripts/doc_sync.py           # 缺省 = --check

pytest 常驻门：tests/test_cross_validation_gates.py 以 subprocess --check 守门。
事实来源：RouteKind 注册表、帮助 topic 数、模板清单、测试文件数、
配置键数、哈希清单范围、**能力真身册的维清单与在册枚数**——全部可从代码/清单机械推导。

## 本件另兼任「声明源塌陷锁」的唯一真身（S246R，2026-09-25）
四支取数口（`doc_sync` / `board_doc_sync` / `command_catalog` / `ownership_project`）
都按**钉死的路径**去读声明源。本仓的归位家规是「旧路径留再导出垫片」（v21r2 已这么退役
`capabilities/`、`output/card_render/` 两批），而 AST/正则读取口对壳一律**解析不出条目**：
解析不出 ⇒ 旧写法回空列表 ⇒ 机器册把「读不到」记成「没有」（又一例空挂假绿）。
故塌陷锁只在这里定义一次，另外三支 `import doc_sync` 复用（尺身份锁见
`tests/test_doc_sync_gates.py::test_collapse_lock_has_a_single_home`）；
`ownership_project.SourceUnavailable` 是本教义在投影器侧的既有实现，同一条规矩、两种异常名。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "auto-facts.md"
#: 能力真身册（维清单与在册枚数的唯一声明源；本件只用 AST 读它，绝不 import 插件包）。
MANIFEST_PY = ROOT / "plugins/bot_unified_runtime/domains/core/capability_manifest.py"

_HEAD = (
    "# 自动事实册（机器所有 · 勿手改）\n\n"
    "> 本册由 `python scripts/doc_sync.py --write` 从代码整册重生成；\n"
    "> `--check` 漂移即红（tests/test_cross_validation_gates.py 常驻）。\n"
    "> 生成时间字段不在册（保证字节确定性，避免无意义漂移）。\n"
)


class DeclarationBlind(RuntimeError):
    """某支取数口把声明源读成空 ⇒ **拒绝**降级成「该源没有东西」。

    与 `ownership_project.SourceUnavailable` 同一条教义（起点即空＝读不动，不是零结果），
    差别只在异常名沿用本件的「眼睛瞎了」口径。抛错必点名：哪支口、哪件、以及
    「该件是不是已经降成再导出壳」——因为搬迁后读空是这条路径上最常见的死法，
    不点名就只会得到一句 "list is empty"，下一个人还得从头查。
    """


def module_surface(path: Path) -> tuple[set[str], set[str]]:
    """一件源码的「本地定义名」与「再导出名」两集合（纯 AST，零 import）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined: set[str] = set()
    reexported: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
            if (isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple))
                    and any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets)):
                reexported.update(
                    elt.value for elt in node.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    reexported.add("*")  # 星号形态：无法本地判定，交由调用方按「非本地定义」处理
                else:
                    reexported.add(alias.asname or alias.name)
    return defined, reexported


def declaration_blindness(path: Path, needed: Iterable[str]) -> str:
    """读空时的人话归因：点名「件已降为再导出壳」还是「件里根本没有这个符号」。"""
    names = [n for n in needed if n]
    rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
    if path.is_dir():
        return f"{rel} 目录读不出任何条目（目录被搬空／改名 ⇒ 本口的 glob 面塌了）"
    if not path.is_file():
        return f"{rel} 不在盘上"
    try:
        defined, reexported = module_surface(path)
    except SyntaxError as exc:  # 并发写坏／语法变了：也算读不动，绝不回空
        return f"{path.name} 语法不可解析（第 {exc.lineno} 行）——该件可能正被他席改写"
    if not names:
        return f"{rel} 内解析不出任何条目（声明源的写法变了？）"
    shells = [n for n in names if n not in defined and (n in reexported or "*" in reexported)]
    missing = [n for n in names if n not in defined and n not in shells]
    bits: list[str] = []
    if shells:
        bits.append(
            f"{shells} 在本件**无本地定义**、只见再导出 ⇒ 本件已降为再导出壳/垫片，"
            "本口必须改指真身（或在口内接追链），不许把壳读成空表")
    if missing:
        bits.append(f"{missing} 在本件既无定义也无再导出 ⇒ 声明源符号名变了")
    return "；".join(bits) or "件内解析不出预期条目"


_T = TypeVar("_T")


def require_surface(label: str, value: _T, path: Path, needed: Iterable[str] = ()) -> _T:
    """塌陷锁：取数为空 ⇒ 抛 `DeclarationBlind` 并点名原因（禁「空＝没有」）。"""
    if value:
        return value
    raise DeclarationBlind(
        f"{label} 取数为空 ⇒ 拒绝把「读不到」当成「没有」：{declaration_blindness(path, needed)}")


def manifest_facet_dims(path: Path | None = None) -> list[str]:
    """能力册的**维清单**（AST 现算声明序，含 `CapabilityArm` 的嵌套列）。

    为什么这支要跟着 AST 走而不是抄一份名单：抄名单＝第二真身，册里加一维（arms/board/line
    这一波已经加过三次）名字表就悄悄过期，正是本件要治的"一处变更不处处跟随"。
    两枚宿主类**固定按 CapabilityFacets → CapabilityArm 的顺序**取，与源码书写顺序无关
    （生成物要字节确定）。
    路径缺省在**函数体内**才读 `MANIFEST_PY`：写成默认参数＝定义期把路径冻死，
    常驻门就再也无法把它指到 `tmp_path` 的合成册上，注毒腿会退化成空跑。
    """
    target = path or MANIFEST_PY
    if not target.is_file():
        raise DeclarationBlind(f"能力真身册缺件：{declaration_blindness(target, ())}")
    tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
    columns: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in {"CapabilityFacets", "CapabilityArm"}:
            columns[node.name] = [
                stmt.target.id for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            ]
    facets = require_surface(
        "能力册维 CapabilityFacets", columns.get("CapabilityFacets", []), target, ("CapabilityFacets",))
    arms = require_surface(
        "能力册臂列 CapabilityArm", columns.get("CapabilityArm", []), target, ("CapabilityArm",))
    return [*facets, *(f"arms.{name}" for name in arms)]



def manifest_facet_rows(path: Path | None = None) -> int:
    """在册枚数＝`FACETS` 装配体里 `_f(...)` 调用的 AST 现算值（不 import、不 exec）。

    路径缺省同 `manifest_facet_dims`：在函数体内解析，常驻门才能把本口注毒到合成册上。
    """
    target = path or MANIFEST_PY
    tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
    facets: ast.AST | None = None
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == "FACETS" for t in targets):
            facets = getattr(node, "value", None)  # 三型赋值语句都带 value；类型面 `ast.stmt` 没有
    if facets is None:
        raise DeclarationBlind(declaration_blindness(target, ("FACETS",)))
    rows = sum(
        1 for n in ast.walk(facets)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_f"
    )
    require_surface("能力册在册枚数", rows, target, ("FACETS", "_f"))
    return rows


def manifest_facts_lines() -> list[str]:
    """机器册的能力册小节：**缺件时印「缺件」，绝不印 0**。

    为什么允许缺件分支：`tests/_autosync_fixture.py` 造的合成最小仓只复制三支生成脚本与其
    输入件，不含本册；那条路径下写「在册枚数 0」就是把"读不到"洗成"没有"，
    所以这里印的是"缺件"三个字——门与人都看得见它不是零。
    在册枚数＝`FACETS` 装配体里 `_f(...)` 调用的 AST 现算数；维清单＝`CapabilityFacets`
    字段序 ＋ `arms.<列>` 四列 ⇒ **册里加一维，本册自动长一行**，不需要任何人回头补文档
    （这一条就是"一处变更处处跟随"的落点，常驻锁见
    `tests/test_doc_sync_gates.py::test_machine_ledger_grows_with_a_new_manifest_dim`）。
    """
    if not MANIFEST_PY.is_file():
        return ["", f"- 能力真身册：缺件（{MANIFEST_PY.relative_to(ROOT).as_posix()} 不在盘上）"]
    return [
        "",
        f"- 能力真身册在册枚数：{manifest_facet_rows()}",
        f"- 能力真身册维清单（AST 现算，含臂列）：{', '.join(manifest_facet_dims())}",
    ]


#: 六支取数口的声明源（提到模块级＝让常驻门能把它们指到 `tmp_path` 合成件上，
#: 从而**实测**"壳/空件 ⇒ 必抛"，而不是只读源码字符串宣称有这道锁）。
BASE_ROUTER_PY = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py"
ECHO_PY = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py"
CONFIG_PY = ROOT / "plugins/bot_unified_runtime/config.py"
TEMPLATES_DIR = ROOT / "plugins/bot_unified_runtime/domains/render/card_render/templates"
TESTS_DIR = ROOT / "tests"
VERIFY_HASHES_PY = ROOT / "tests/verify_hashes.py"


def _tpl_list() -> list[str]:
    return require_surface(
        "模板清单取数口", sorted(p.name for p in TEMPLATES_DIR.glob("*.html")), TEMPLATES_DIR)


def _route_kinds() -> list[str]:
    text = BASE_ROUTER_PY.read_text(encoding="utf-8")
    block = re.search(r"class RouteKind\(str, Enum\):(.*?)\n\n", text, re.DOTALL)
    assert block, "RouteKind 枚举找不到"
    return require_surface(
        "RouteKind 取数口",
        re.findall(r"^    ([A-Z_]+) = ", block.group(1), re.MULTILINE),
        BASE_ROUTER_PY,
        ("RouteKind",),
    )


def _help_topics() -> list[str]:
    # v21r2 RWC3：echo 真身迁 domains/chat_reply/capabilities/（静态提取必指真身）。
    text = ECHO_PY.read_text(encoding="utf-8")
    return require_surface(
        "帮助 topic 取数口",
        re.findall(r'"topic":\s*[\'"]([^\'"]+)[\'"]', text),
        ECHO_PY,
        ("_HELP_ENTRIES",),
    )


def _test_file_count() -> int:
    return require_surface(
        "测试文件数取数口", len(list(TESTS_DIR.glob("test_*.py"))), TESTS_DIR)


def _config_key_count() -> int:
    text = CONFIG_PY.read_text(encoding="utf-8")
    return require_surface(
        "config 字段数取数口",
        len(re.findall(r"^    bot_[a-z0-9_]+:", text, re.MULTILINE)),
        CONFIG_PY,
        ("class Config",),
    )


def _tracked_files() -> list[str]:
    sys.path.insert(0, str(ROOT / "tests"))
    from verify_hashes import TRACKED_FILES

    return require_surface(
        "哈希清单范围取数口", list(TRACKED_FILES), VERIFY_HASHES_PY, ("TRACKED_FILES",))


def build_document() -> str:
    tpls = _tpl_list()
    kinds = _route_kinds()
    topics = _help_topics()
    tracked = _tracked_files()
    lines = [
        _HEAD,
        f"- 模板清单（{len(tpls)}）：{', '.join(tpls)}",
        "",
        f"- RouteKind（{len(kinds)}）：{', '.join(kinds)}",
        "",
        f"- 帮助 topic 数：{len(topics)}（重名 {len(topics) - len(set(topics))}）",
        f"- 测试文件数：{_test_file_count()}",
        f"- config.py bot_* 字段数：{_config_key_count()}",
        "",
        f"- 哈希清单范围（{len(tracked)}）：{', '.join(tracked)}",
        *manifest_facts_lines(),
        "",
    ]
    return "\n".join(lines)


def check() -> bool:
    current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
    expected = build_document()
    if current != expected:
        print(
            "doc_sync: docs/auto-facts.md 与代码推导结果不一致；"
            "跑 python scripts/doc_sync.py --write 重生成。",
            file=sys.stderr,
        )
        return False
    return True


def write() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(build_document(), encoding="utf-8", newline="\n")
    print(f"doc_sync: 已重生成 {TARGET.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="机器事实册同步门")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    return 0 if check() else 1


if __name__ == "__main__":
    raise SystemExit(main())
