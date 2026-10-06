"""已删垫片路径的 import 存在性锁（席 S-BLIND-REPOINT-b，2026-09-27）。

背景：垫片退役波 W1 已删除四枚 PEP562 转发垫片——

- ``plugins/bot_unified_runtime/llm/ledger.py``
- ``plugins/bot_unified_runtime/llm/providers.py``
- ``plugins/bot_unified_runtime/character/reminders.py``
- ``plugins/bot_unified_runtime/character/vector_knowledge.py``

（备份 ``%TEMP%\\shim-w1-backup-20260927-013104\\``。）任何**直连**这四条模块路径的
import 在垫片文件已物理消失的现在都必致 ImportError；而经 ``llm/``、``character/``
两个仍存活的壳包按属性形 import（如 ``from plugins.bot_unified_runtime.llm import
providers``）会被壳的 ``__getattr__`` 兜到 canonical——静态普查看不见、运行期却是活的，
退役台账收口判据会被它糊过去。本门把两种形态一并钉死：**全树不允许再有任何 import
指向这四条已删路径（含壳包属性形）**。

2026-10-04 P2 减量波续锁 9 枚（复活件二次清偿，`DELETED_MODULES` 追加 8 条 dotted
path ＋下方物理存在锁扩面），见各清单内注释。

2026-10-06 名单↔账对账波（本文件末段）：上面的 import 锁与物理锁都只读**本文件手抄的名单**，
全仓没有一处拿 `DELETED_MODULES` 与在册账 `domains/core/board_shim_ledger.py::SHIM_ROWS`（或算口
`scripts/shim_retirement_census.py` 的现算垫片集）对过账 ⇒ 名单与账漂了没人响，正是台账 #68★
「退役＝文件＋`SHIM_ROWS` 行＋只读面登记**同批动**」缺的那条执法腿，也同 #75/#76 那一族病
（修法在册≠修好在盘／手抄名单＝第二处真身）。本波补四把纯函数尺 + 一条总闸，成员级点名，
**取数一律走 census 唯一口**（`load_ledger_rows` 的拒读语义、`shim_target_dotted` 的点号尺），
禁在本文件写第二把；台账读不到／`SHIM_ROWS` 被清空／解析撕裂 ⇒ 判红，**绝不当空账放行**。

判据口径（防三型假绿）：
- **扫描面不许塌陷**：只数命中不数被检文件数，glob 一改就能把账做没，故设文件数地板。
- **注毒走内存源码**：判据函数吃字符串，不往树里写毒件；每形态一发、各杀各锁。
- **相对 import 也解析**：level>0 的 from-import 按所在包上下文折算绝对路径后再判，
  否则壳包内 ``from . import providers`` 就是尺的盲区。
- **对账只准变严**：新增的四把尺一律加判、不减既有严格度；名单内容不因对账而删（真漂了只报不删）。
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

# 在册账的唯一取数口（不 import 插件包，避免拖起 NoneBot 初始化；与
# `tests/test_shim_retirement_ledger.py` 同一路径注入写法）。
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import shim_retirement_census as s34

#: 本锁所在的文件自身不吃扫——它必须持有这四条路径的字符串常量才能执法。
SELF_FILE = Path(__file__).resolve()

#: 已删垫片模块的绝对 dotted 路径（唯一真身清单）。
DELETED_MODULES: frozenset[str] = frozenset(
    {
        "plugins.bot_unified_runtime.llm.ledger",
        "plugins.bot_unified_runtime.llm.providers",
        "plugins.bot_unified_runtime.character.reminders",
        "plugins.bot_unified_runtime.character.vector_knowledge",
        # ── 2026-10-04 P2 减量波（垫片三态退役·复活件二次清偿）追加 8 条：sender/security
        #    两包随退役**整目录消失**（前缀匹配连带其一切子模块）；capabilities/runtime/sources
        #    三父包仍在且是普通命名空间（无惰性 `__getattr__`），属性形 import 会响亮
        #    ImportError ⇒ 只锁子模块 dotted path、不进 SHELL_PACKAGES。
        #    逐枚退役前 census `reference_index` 现算引用边=0＋全仓精确 grep 零命中；
        #    字节备份 `%TEMP%/p2wave/shim-backup/`（路径镜像）。
        "plugins.bot_unified_runtime.capabilities.auto_send",
        "plugins.bot_unified_runtime.capabilities.chat",
        "plugins.bot_unified_runtime.capabilities.market",
        "plugins.bot_unified_runtime.runtime.settings",
        "plugins.bot_unified_runtime.security",
        "plugins.bot_unified_runtime.sender",
        "plugins.bot_unified_runtime.sources.fetchers",
        "plugins.bot_unified_runtime.sources.subscriptions",
    }
)

#: 仍存活的壳包 → 该包下已删的子模块名（属性形 ``from <壳包> import <子模块名>`` 判据）。
#: 2026-10-06 对账波加钉 `runtime`（**纯加面、不改任何既有判据严格度**）：上方 2026-10-04 那段
#: 注释声明「capabilities/runtime/sources 三父包……无惰性 `__getattr__`」，现算证其对 `runtime`
#: **说错了**——`plugins/bot_unified_runtime/runtime/__init__.py` 现算确有 `def __getattr__`
#: （尺按 AST 判壳，不钉行号：行号会漂）
#: （`_PIPELINE_NAMES` 白名单形），所以 `from plugins.bot_unified_runtime.runtime import settings`
#: 这形在旧尺上完全隐形。尺④（`_shell_form_vs_list`）按盘上现算的壳面执法，今日红一条⇒本钉补上。
#: `capabilities`（1 行 `__init__`）与 `sources`（8 行、无 `__getattr__`）经同一把尺现算确认无壳
#: ⇒ 其子模块只锁 dotted path，不进本表（`character` 现算亦无 `__getattr__`，此处保留原钉＝更严，
#: 尺④只朝多钉方向判，不逼名单缩面）。
SHELL_PACKAGES: dict[str, frozenset[str]] = {
    "plugins.bot_unified_runtime.llm": frozenset({"ledger", "providers"}),
    "plugins.bot_unified_runtime.character": frozenset({"reminders", "vector_knowledge"}),
    "plugins.bot_unified_runtime.runtime": frozenset({"settings"}),
}

#: 扫描根（生产 + 工具 + 测试全覆盖）。
SCAN_ROOTS: tuple[str, ...] = ("plugins", "scripts", "tests")
#: 扫描文件数地板：低于此＝扫描面塌了，不是"大家都迁完了"。
MIN_SCANNED_FILES = 900

# ------------------------------------------------------------------ 导出面（只加名字）
# D-DELSPEC-3 并轨波（2026-10-06）：`tests/test_copy_redline_gate.py` 那段手抄的「已退役路径」
# 断言改由本文件派生，它需要的是**同一个取数口**而不是第二把尺，故此处只把 census 的既有唯一口
# 转成本模块的公开名字——**没有新增、没有改动、也没有放宽任何一条判据**：
#   `deleted_target_dotted` ＝ census 唯一点号尺 `shim_target_dotted`（包垫片 `<pkg>/__init__.py`
#     折成父包点号名）；
#   `reference_index`      ＝ census 唯一全仓引用索引（坏读按其文档原样抛，调用方一律转判红）。
# 形态展开尺 `_absence_forms` 保持原名跨模块复用（本仓既有做法＝复用下划线判据，先例见
# `tests/test_render_orb_route_ssrf.py` / `tests/test_claims_subset_implementation_gate.py`）。
deleted_target_dotted = s34.shim_target_dotted
reference_index = s34.reference_index


def _package_context(rel_path: Path) -> str:
    """文件相对仓根的 dotted 模块上下文（__init__.py 归属其所在包本身）。"""
    parts = list(rel_path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_from_module(ctx: str, is_init: bool, node: ast.ImportFrom) -> str:
    """把 ImportFrom（含相对形）折成绝对 dotted 模块路径。"""
    if node.level == 0:
        return node.module or ""
    parts = ctx.split(".") if ctx else []
    if not parts:
        return node.module or ""
    if not is_init:
        # ctx 含模块名末段；level=1 的锚是其所在包。
        parts = parts[:-1]
    # level>=2 时每多一级再向上跳一层包。
    for _ in range(node.level - 1):
        if parts:
            parts = parts[:-1]
    joined = ".".join(parts)
    if node.module:
        joined = f"{joined}.{node.module}" if joined else node.module
    return joined


def _is_deleted_target(module_path: str, names: set[str]) -> bool:
    """模块路径本身、其子模块、或"壳包+已删子模块名"属性形，命中即真。"""
    for deleted in DELETED_MODULES:
        if module_path == deleted or module_path.startswith(deleted + "."):
            return True
    shell = SHELL_PACKAGES.get(module_path)
    return shell is not None and bool(names & shell)


def _iter_violations(source: str, rel_path: Path) -> list[str]:
    """扫一份源码，返回违规描述列表（空=干净）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [f"{rel_path}: 语法解析失败（跳过会把盲区洗成绿）"]
    is_init = rel_path.name == "__init__.py"
    ctx = _package_context(rel_path)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_deleted_target(alias.name, set()):
                    out.append(f"{rel_path}:{node.lineno}: import {alias.name} → 已删垫片路径")
        elif isinstance(node, ast.ImportFrom):
            module_path = _resolve_from_module(ctx, is_init, node)
            names = {alias.name for alias in node.names}
            if _is_deleted_target(module_path, names):
                out.append(
                    f"{rel_path}:{node.lineno}: from {module_path or '(包)'} import "
                    f"{sorted(names)} → 已删垫片路径（含壳包属性形）"
                )
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if fname in {"import_module", "__import__"} and node.args:
                first = node.args[0]
                if (
                    isinstance(first, ast.Constant)
                    and isinstance(first.value, str)
                    and _is_deleted_target(first.value, set())
                ):
                    out.append(f"{rel_path}:{node.lineno}: {fname}({first.value!r}) → 已删垫片路径")
    return out


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        files.extend(p for p in base.rglob("*.py") if p.resolve() != SELF_FILE)
    return sorted(files)


# ------------------------------------------------------------------ 真树锁


def test_scanned_surface_does_not_collapse() -> None:
    """扫描面地板：文件数掉下去＝glob/排除被改，不是迁完了。"""
    files = _iter_py_files()
    assert len(files) >= MIN_SCANNED_FILES, (
        f"扫描面塌陷：只扫到 {len(files)} 件（地板 {MIN_SCANNED_FILES}）"
    )


def test_no_import_targets_deleted_shims() -> None:
    """全树（plugins/scripts/tests）无任何 import 指向四条已删垫片路径。"""
    violations: list[str] = []
    unparsable: list[str] = []
    for path in _iter_py_files():
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(REPO_ROOT)
        for v in _iter_violations(source, rel):
            (unparsable if "语法解析失败" in v else violations).append(v)
    assert not unparsable, f"解析失败件（不许静默跳过）：{unparsable[:5]}"
    assert not violations, "发现指向已删垫片的 import：\n" + "\n".join(violations[:20])


def test_shell_packages_still_lazy_but_lock_targets_are_gone() -> None:
    """壳包与已退役垫片文件的现状对照：壳在（不许误删），垫片文件必须已物理消失。"""
    assert (PKG_ROOT / "llm" / "__init__.py").is_file()
    assert (PKG_ROOT / "character" / "__init__.py").is_file()
    for gone in (
        PKG_ROOT / "llm" / "ledger.py",
        PKG_ROOT / "llm" / "providers.py",
        PKG_ROOT / "character" / "reminders.py",
        PKG_ROOT / "character" / "vector_knowledge.py",
        # ── 2026-10-04 P2 减量波退役 9 件（复活件二次清偿，备份 %TEMP%/p2wave/shim-backup/）：
        #    本仓已两次实锤「外部 restore 把已退役 tracked 件连文件带账本行写回」（§68；
        #    HANDOFF-FIXWAVE-20261002 §⑨），物理存在锁与 DELETED_MODULES 同批扩面。
        PKG_ROOT / "capabilities" / "chat.py",
        PKG_ROOT / "capabilities" / "market.py",
        PKG_ROOT / "capabilities" / "auto_send" / "__init__.py",
        PKG_ROOT / "runtime" / "settings.py",
        PKG_ROOT / "security" / "memory_sanitize.py",
        PKG_ROOT / "sender" / "__init__.py",
        PKG_ROOT / "sender" / "onebot.py",
        PKG_ROOT / "sources" / "fetchers" / "__init__.py",
        PKG_ROOT / "sources" / "subscriptions" / "__init__.py",
    ):
        assert not gone.exists(), f"已删垫片又出现在盘上（谁还原的？）：{gone}"
    # 五个随退役消失的目录（防「空目录先回来」的中间态被当作正常盘面）。
    for gone_dir in (
        PKG_ROOT / "security",
        PKG_ROOT / "sender",
        PKG_ROOT / "capabilities" / "auto_send",
        PKG_ROOT / "sources" / "fetchers",
        PKG_ROOT / "sources" / "subscriptions",
    ):
        assert not gone_dir.exists(), f"已退役目录又出现在盘上（谁还原的？）：{gone_dir}"


# ------------------------------------------------------------------ 注毒自证（纯内存）

_POISON_SAMPLES: tuple[tuple[str, str, Path], ...] = (
    # (说明, 源码, 伪装路径)
    (
        "绝对 from-import 已删模块",
        "from plugins.bot_unified_runtime.llm.ledger import LedgerService\n",
        Path("x/y.py"),
    ),
    (
        "点号 import 已删模块",
        "import plugins.bot_unified_runtime.character.vector_knowledge\n",
        Path("x/y.py"),
    ),
    (
        "壳包属性形（PEP562 可解，但静态必须点名）",
        "from plugins.bot_unified_runtime.llm import providers\n",
        Path("x/y.py"),
    ),
    (
        "character 壳属性形 reminders",
        "from plugins.bot_unified_runtime.character import reminders\n",
        Path("x/y.py"),
    ),
    (
        "import_module 字符串形",
        (
            "from importlib import import_module\n"
            "m = import_module('plugins.bot_unified_runtime.llm.providers')\n"
        ),
        Path("x/y.py"),
    ),
    (
        "相对形（llm 壳包内 from . import providers）",
        "from . import providers\n",
        Path("plugins/bot_unified_runtime/llm/_poison_sample.py"),
    ),
    (
        "壳包子模块直连（from llm.providers import X）",
        "from plugins.bot_unified_runtime.llm.providers import LLMProviderError\n",
        Path("x/y.py"),
    ),
    # 2026-10-06 对账波加发：`runtime` 父包经盘上现算确有 `__getattr__`（尺④），旧尺看不见这形。
    (
        "runtime 壳属性形 settings（2026-10-06 加钉）",
        "from plugins.bot_unified_runtime.runtime import settings\n",
        Path("x/y.py"),
    ),
    (
        "runtime 壳内相对形（from . import settings）",
        "from . import settings\n",
        Path("plugins/bot_unified_runtime/runtime/_poison_sample.py"),
    ),
)


def test_poison_samples_are_all_caught() -> None:
    """每形态一发注毒，判据各杀各的——尺变瞎当场红。"""
    for label, src, rel in _POISON_SAMPLES:
        hits = _iter_violations(src, rel)
        assert hits, f"注毒未被抓住（{label}）：{src!r}"


def test_clean_sample_is_not_flagged() -> None:
    """反向锁：改线后的正确写法与合法壳属性名（契约名，非子模块）不得误伤。"""
    src = (
        "from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers "
        "import LLMProviderError\n"
        "from plugins.bot_unified_runtime.llm import LLMProvider  # 壳属性名=契约名，非子模块\n"
    )
    hits = _iter_violations(src, Path("x/y.py"))
    assert hits == [], hits


# ==========================================================================
# 名单 ↔ 在册账 对账锁（2026-10-06）
# ==========================================================================

#: 物理形态标签：单文件退役形（父包仍在，只少了这一枚 `.py`）。
MODULE_FORM = "module"
#: 物理形态标签：整目录随退役消失形（账侧那行的 path 是 `<pkg>/__init__.py`）。
PACKAGE_DIR_FORM = "package-dir"

#: 名单条目的物理形态（**显式映射 · 逐条注明理由 · 键集必须与 `DELETED_MODULES` 逐名相等**）。
#: 简报要求的「正当映射」就写在这里，不许用模糊前缀匹配蒙过去：
#: - 包形条目对得上账侧的原因＝census 唯一点号尺 `shim_target_dotted` 把包垫片
#:   （`<pkg>/__init__.py`）折成**父包点号名**，所以名单写父包名与账写 `__init__.py`
#:   落进同一 namespace，对账是**同名相等**、不是前缀包含。
#: - 「整目录消失」的五枚按**目录本体也不许存在**判：目录里任何一枚子件
#:   （`sender/onebot.py`、`security/memory_sanitize.py` 之流）被还原写回都会重建目录 ⇒ 当场红。
#:   这条把上面那段手抄子模块点名换成了尺——手抄清单会逐枚漂，目录存在性不会。
DELETED_MODULE_FORMS: dict[str, str] = {
    # ── 2026-09-27 垫片退役波 W1 四枚：`llm/`、`character/` 两父包至今存活 ⇒ 单文件形。
    "plugins.bot_unified_runtime.llm.ledger": MODULE_FORM,
    "plugins.bot_unified_runtime.llm.providers": MODULE_FORM,
    "plugins.bot_unified_runtime.character.reminders": MODULE_FORM,
    "plugins.bot_unified_runtime.character.vector_knowledge": MODULE_FORM,
    # ── 2026-10-04 P2 减量波：单文件形三枚（父包 `capabilities/`、`runtime/` 仍在，只少子模块）。
    "plugins.bot_unified_runtime.capabilities.chat": MODULE_FORM,
    "plugins.bot_unified_runtime.capabilities.market": MODULE_FORM,
    "plugins.bot_unified_runtime.runtime.settings": MODULE_FORM,
    # ── 2026-10-04 P2 减量波：整目录随退役消失五枚（目录本体见上方 `gone_dir` 那段既有锁）。
    "plugins.bot_unified_runtime.capabilities.auto_send": PACKAGE_DIR_FORM,
    "plugins.bot_unified_runtime.security": PACKAGE_DIR_FORM,
    "plugins.bot_unified_runtime.sender": PACKAGE_DIR_FORM,
    "plugins.bot_unified_runtime.sources.fetchers": PACKAGE_DIR_FORM,
    "plugins.bot_unified_runtime.sources.subscriptions": PACKAGE_DIR_FORM,
}


def _path_on_disk(rel: str) -> bool:
    """相对仓根的存在性判定（唯一落点）。绝对路径／`..` 段＝账或映射撕裂 ⇒ 拒判，不静默放行。"""
    pure = Path(rel)
    if pure.is_absolute() or ".." in pure.parts:
        raise AssertionError(f"对账取到越界路径 {rel!r}（在册账/形态映射撕裂）⇒ 本锁判红")
    return (REPO_ROOT / pure).exists()


def _absence_forms(dotted: str, form: str) -> tuple[str, ...]:
    """一条名单条目在盘上「一个都不许存在」的具体形态。"""
    if form not in (MODULE_FORM, PACKAGE_DIR_FORM):
        raise AssertionError(f"未知的物理形态标签 {form!r}（只许 {MODULE_FORM}/{PACKAGE_DIR_FORM}）")
    rel = Path(*dotted.split(".")).as_posix()
    forms = (f"{rel}.py", f"{rel}/__init__.py")
    return forms + ((rel,) if form == PACKAGE_DIR_FORM else ())


def _rows_to_targets(rows: list[dict[str, Any]]) -> dict[str, str]:
    """在册账 → `{点号目标: 账上 rel path}`；点号一律由 census 唯一尺折出（禁第二把）。"""
    targets: dict[str, str] = {}
    for row in rows:
        rel = str(row["path"])
        dotted = s34.shim_target_dotted(rel)
        if dotted in targets:
            raise AssertionError(
                f"在册账两枚行折出同一点号目标 {dotted!r}（{targets[dotted]} / {rel}）⇒ 账撕裂，拒判"
            )
        targets[dotted] = rel
    return targets


def _load_inregister_rows(ledger_source: str | None = None) -> list[dict[str, Any]]:
    """经 census 的**拒读口**取在册账。

    台账读不到（文件缺席）／`SHIM_ROWS` 被清成空账／撕裂截断／非纯字面量 ⇒ 一律判**红**，
    口径照抄算口那句「拒读≠空账放行」（`LedgerReadIncomplete` / `AssertionError`）：
    对账锁最怕的就是「账没了 ⇒ 差集为空 ⇒ 绿」，那正是还原波最响的静默形态。
    """
    try:
        rows = s34.load_ledger_rows(ledger_source)
    except (s34.LedgerReadIncomplete, AssertionError, OSError) as exc:
        raise AssertionError(
            "在册账 `board_shim_ledger.SHIM_ROWS` 本轮读不到 ⇒ 对账锁判红（不当空账放行）："
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if not rows:
        raise AssertionError("在册账解析出 0 行 ⇒ 对账锁判红（0 行＝读不到，不是「没有历史」）")
    return rows


def _lazy_shell_parents(deleted: Iterable[str]) -> frozenset[str]:
    """现算「名单条目的父包里，哪些是仍在盘、且 `__init__.py` 定义了 `__getattr__` 的惰性壳」。

    尺＝AST `FunctionDef` 名，**不信注释**：`DELETED_MODULES` 上方那段 2026-10-04 注释声明
    「capabilities/runtime/sources 三父包……无惰性 `__getattr__`」，2026-10-06 现算证它对
    `runtime` 说错了（`plugins/bot_unified_runtime/runtime/__init__.py` 现算确有
    `def __getattr__`，是 `_PIPELINE_NAMES` 白名单形）⇒ 该形当年就是尺的盲区，
    现由 `SHELL_PACKAGES` 加钉 + 本腿同批封死；`capabilities`/`sources` 经同一把尺复核确无壳。
    """
    out: set[str] = set()
    for dotted in deleted:
        parent, _, _leaf = dotted.rpartition(".")
        if not parent or parent in out:
            continue
        init = REPO_ROOT.joinpath(*parent.split(".")) / "__init__.py"
        if not init.is_file():
            continue
        try:
            tree = ast.parse(init.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise AssertionError(f"父包壳面解析失败 ⇒ 壳形判据拒判（不许当「没壳」放行）：{init}") from exc
        if any(isinstance(n, ast.FunctionDef) and n.name == "__getattr__" for n in ast.walk(tree)):
            out.add(parent)
    return frozenset(out)


# ---------------------------------------------------------------- 尺①名单↔映射自洽


def _forms_vs_list(deleted: frozenset[str], forms: Mapping[str, str]) -> list[str]:
    """键集**逐名**相等（多一条少一条都点名）＋标签合法＋条目名必须是本包 dotted。"""
    out: list[str] = []
    for extra in sorted(set(forms) - set(deleted)):
        out.append(f"形态映射里有名单没有的条目：{extra}（手抄了一条没出处理径的路径？）")
    for miss in sorted(set(deleted) - set(forms)):
        out.append(f"名单新增条目缺物理形态理由：{miss}（要写 module/package-dir 并注明批次）")
    for dotted in sorted(set(deleted) & set(forms)):
        _absence_forms(dotted, forms[dotted])
        if not dotted.startswith("plugins.bot_unified_runtime."):
            out.append(f"名单条目不在主包命名空间下：{dotted}")
    return out


# ---------------------------------------------------------------- 尺②名单↔在册账


def _ledger_vs_list(
    deleted: frozenset[str],
    ledger: Mapping[str, str],
    live_shims: Mapping[str, str],
    *,
    on_disk: Callable[[str], bool] = _path_on_disk,
) -> list[str]:
    """三腿：②a 交集必须空 · ②b 账上「行在件没」的滞后行必须已进名单 · ②c 与现算垫片不得同指。

    空账/零现算＝读点塌了，不是「大家都退役完了」——两条地板点名。
    """
    out: list[str] = []
    if not ledger:
        return ["在册账为空（`SHIM_ROWS` 零行/读不到）⇒ 对账拒判，不当空账放行"]
    if not live_shims:
        out.append("现算合格垫片 0 枚 ⇒ 判定口塌陷（census `_assert_no_detection_collapse` 同哲学）")
    for dotted in sorted(deleted & set(ledger)):
        out.append(
            f"名单条目仍在册：{dotted}（账上行 {ledger[dotted]}）⇒ 在册账与只读名单不在同一批"
        )
    for dotted, rel in sorted(ledger.items(), key=lambda kv: kv[1]):
        if not on_disk(rel) and dotted not in deleted:
            out.append(
                f"账上行 {rel} 的文件已不在盘＝已退役，却没进只读名单 ⇒ 退役要连文件带名单同批动"
            )
    for dotted in sorted(deleted & set(live_shims)):
        out.append(
            f"名单条目 {dotted} 与现算合格垫片同指一件（{live_shims[dotted]} 在盘且仍是垫片）"
        )
    return out


# ---------------------------------------------------------------- 尺③名单↔盘


def _physical_absence(
    deleted: frozenset[str],
    forms: Mapping[str, str],
    *,
    on_disk: Callable[[str], bool] = _path_on_disk,
) -> list[str]:
    """逐条按映射形态判「不得在盘」——从名单派生，不再依赖手抄的 `gone` 清单。"""
    out: list[str] = []
    for dotted in sorted(deleted):
        form = forms.get(dotted)
        if form is None:
            continue  # 缺席由尺①点名，这里不重复报
        for rel in _absence_forms(dotted, form):
            if on_disk(rel):
                out.append(f"已删垫片又出现在盘上（谁还原的？）：{rel}  ← 名单条目 {dotted}")
    return out


# ---------------------------------------------------------------- 尺④名单↔壳形（盘上现算）


def _shell_form_vs_list(
    deleted: frozenset[str],
    shell_packages: Mapping[str, frozenset[str]],
    ledger: Mapping[str, str],
    lazy_shells: frozenset[str],
    *,
    on_disk: Callable[[str], bool] = _path_on_disk,
) -> list[str]:
    """惰性壳是**盘上现算**的，不是注释里声明的。

    ④a 名单条目的父包若是惰性壳 ⇒ 该子模块名必须进 `SHELL_PACKAGES[父包]`，
       否则 `from <父包> import <子模块>` 这形对尺完全隐形（运行期却被 `__getattr__` 兜走）。
       只朝「多钉」方向判：`SHELL_PACKAGES` 多列（如父包其实没有惰性壳仍钉着）＝更严，不红。
    ④b `SHELL_PACKAGES` 点的每一枚都必须是名单成员（两集同批），且壳包本体仍在盘（误删即红），
       且不得是**在册活垫片**（那会把合法 import 面误伤成红，方向也反了）。
    """
    out: list[str] = []
    for dotted in sorted(deleted):
        parent, _, leaf = dotted.rpartition(".")
        if parent in lazy_shells and leaf not in shell_packages.get(parent, frozenset()):
            out.append(
                f"{dotted} 的父包 {parent} 在盘上是定义 `__getattr__` 的惰性壳，"
                f"属性形 `from {parent} import {leaf}` 会被静默兜到 canonical ⇒ "
                f"{leaf} 必须进 SHELL_PACKAGES['{parent}']"
            )
    for parent in sorted(shell_packages):
        if not on_disk(f"{parent.replace('.', '/')}/__init__.py"):
            out.append(f"壳包本体已不在盘（被误删？）：{parent}")
        for leaf in sorted(shell_packages[parent]):
            full = f"{parent}.{leaf}"
            if full not in deleted:
                out.append(f"SHELL_PACKAGES 点了 {full} 却不在名单 ⇒ 两集不同批")
            if full in ledger:
                out.append(f"SHELL_PACKAGES 把在册活垫片 {full}（账上 {ledger[full]}）钉成已删壳子")
    return out


# ---------------------------------------------------------------- 总闸 + 分腿常驻锁


def _mesh_state() -> tuple[frozenset[str], dict[str, str], dict[str, str], frozenset[str]]:
    """一次性把三侧真身取齐：名单 / 在册账 / 现算垫片 / 盘上现算惰性壳。"""
    ledger = _rows_to_targets(_load_inregister_rows())
    live = _rows_to_targets([{"path": rel} for rel in s34.detect_shims()])
    return DELETED_MODULES, ledger, live, _lazy_shell_parents(DELETED_MODULES)


def test_forms_map_is_the_same_batch_as_deleted_list() -> None:
    """尺①：名单与物理形态映射逐名同批（注毒①「塞一条假路径」就红在这里）。"""
    v = _forms_vs_list(DELETED_MODULES, DELETED_MODULE_FORMS)
    assert not v, "名单↔形态映射不同批：\n" + "\n".join(v)


def test_deleted_list_meshes_with_register_ledger() -> None:
    """尺②：名单与在册账／现算垫片互斥，滞后行必已入名单（空账与零现算一律红）。"""
    deleted, ledger, live, _lazy = _mesh_state()
    v = _ledger_vs_list(deleted, ledger, live)
    assert not v, "名单与在册账对不上（成员级点名）：\n" + "\n".join(v)


def test_deleted_list_is_physically_absent_derived_from_list() -> None:
    """尺③：盘上不得有名单任何一条的任一形态（从名单派生，比手抄 `gone` 清单更严）。"""
    v = _physical_absence(DELETED_MODULES, DELETED_MODULE_FORMS)
    assert not v, "已删垫片回到盘上：\n" + "\n".join(v)


def test_shell_form_matches_live_lazy_parents() -> None:
    """尺④：壳形判据跟**盘上现算**的惰性壳对死（注释说没壳不算，钉漏了属性形就是盲区）。"""
    deleted, ledger, _live, lazy = _mesh_state()
    v = _shell_form_vs_list(deleted, SHELL_PACKAGES, ledger, lazy)
    assert not v, "壳形与名单不同批：\n" + "\n".join(v)


def test_all_mesh_rulers_green_together() -> None:
    """总闸：四把尺同读一份真身，逐把点名——任何一把漂了就红，不允许「各扫各的」。"""
    deleted, ledger, live, lazy = _mesh_state()
    violations = [
        *_forms_vs_list(deleted, DELETED_MODULE_FORMS),
        *_ledger_vs_list(deleted, ledger, live),
        *_physical_absence(deleted, DELETED_MODULE_FORMS),
        *_shell_form_vs_list(deleted, SHELL_PACKAGES, ledger, lazy),
    ]
    assert not violations, "已删名单与在册账/盘/壳形对账失败：\n" + "\n".join(violations)


# --------------------------------------------------- 名单↔账对账的注毒自证（纯内存）
# 一律吃内存副本或合成源码；源码树一字不写。每形一发，各杀各尺。

#: 合成在册账源码（形状合法、非空，第二枚行的文件根本不在盘＝「已退役但行还挂着」）。
_SYNTH_LEDGER_WITH_LAGGING_ROW = '''
"""synthetic（注毒用，不落盘）。"""

SHIM_ROWS: tuple[tuple[str, str, int], ...] = (
    ("plugins/bot_unified_runtime/llm/model_router.py",
     "plugins/bot_unified_runtime/domains/chat_reply/llm_engine/model_router.py",
     5),
    ("plugins/bot_unified_runtime/runtime/ghost_retired.py",
     "plugins/bot_unified_runtime/domains/chat_reply/runtime/ghost_retired.py",
     0),
)
'''

#: 「台账读不到」的五种形态（与算口 `load_ledger_rows` 顶注的拒读口径逐一对应）。
_UNREADABLE_LEDGER_FORMS: tuple[tuple[str, str], ...] = (
    (
        "空账（SHIM_ROWS 被清成 ()）",
        'SHIM_ROWS: tuple[tuple[str, str, int], ...] = ()\n',
    ),
    (
        "只声明不赋值（AnnAssign.value is None）",
        "SHIM_ROWS: tuple[tuple[str, str, int], ...]\n",
    ),
    (
        "字面量 None（＝这张账没内容）",
        "SHIM_ROWS: tuple[tuple[str, str, int], ...] = None\n",
    ),
    (
        "非纯字面量（手抄加了计算）",
        "SHIM_ROWS: tuple[tuple[str, str, int], ...] = tuple(x for x in (('a', 'b', 1),))\n",
    ),
    (
        "撕裂截断（半截账，ast.parse 语法坏）",
        'SHIM_ROWS: tuple[tuple[str, str, int], ...] = (\n    ("plugins/a.py",\n',
    ),
)


def test_poison_fake_entry_added_to_deleted_list_reds() -> None:
    """注毒①：往名单副本多塞一条没出处的假路径 ⇒ 尺①红，且逐字点名它。"""
    ghost = "plugins.bot_unified_runtime.domains.this_module_never_existed"
    v = _forms_vs_list(DELETED_MODULES | {ghost}, DELETED_MODULE_FORMS)
    assert any(ghost in x for x in v), f"假路径未被点名（尺①瞎了）：{v}"


def test_poison_real_entry_dropped_from_deleted_list_reds() -> None:
    """注毒②：从名单副本摘掉一条真条目 ⇒ 尺①红并点名它（少一条也要报出是哪一条）。"""
    dropped = "plugins.bot_unified_runtime.llm.ledger"
    v = _forms_vs_list(DELETED_MODULES - {dropped}, DELETED_MODULE_FORMS)
    assert any(dropped in x for x in v), f"摘掉的条目未被点名（尺①瞎了）：{v}"


def test_poison_inregister_path_added_to_deleted_list_reds() -> None:
    """注毒②b：把一枚**真在册**活垫片的点号名塞进名单副本 ⇒ 尺②红（账与名单不同批）。"""
    _deleted, ledger, live, _lazy = _mesh_state()
    alive = min(set(ledger) - DELETED_MODULES)
    v = _ledger_vs_list(DELETED_MODULES | {alive}, ledger, live)
    assert any(alive in x for x in v), f"在册活垫片进名单未被点名（尺②瞎了）：{v}"


def test_poison_lagging_ledger_row_missing_from_list_reds() -> None:
    """注毒②c：账上一枚「行在、件已不在盘」的滞后行没进名单 ⇒ 尺②红并点名（同批动那条规矩）。

    走 census 真实解析口喂合成源码——真身账一字不动，也不往树里写毒件。
    """
    synth = _rows_to_targets(_load_inregister_rows(_SYNTH_LEDGER_WITH_LAGGING_ROW))
    ghost_dotted = "plugins.bot_unified_runtime.runtime.ghost_retired"
    assert ghost_dotted in synth, f"合成滞后行没被解析出来：{synth}"
    _deleted, _ledger, live, _lazy = _mesh_state()
    v = _ledger_vs_list(DELETED_MODULES, synth, live)
    assert any("ghost_retired" in x for x in v), f"滞后行未进名单却未被点名（尺②瞎了）：{v}"


def test_poison_unreadable_ledger_reds_never_skips() -> None:
    """注毒③：台账读不到的五种形态一律**判红**，不许退化成「空账 ⇒ 差集为空 ⇒ 绿」。

    这是本锁最容易写歪的一腿：只要有一形被当成「没有历史」放行，还原波清账的那一瞬间
    正好是尺最亮的时候（census 顶注 TX201 同判）。
    """
    for label, source in _UNREADABLE_LEDGER_FORMS:
        with pytest.raises(AssertionError) as caught:
            _load_inregister_rows(source)
        text = str(caught.value)
        assert ("读不到" in text) or ("0 行" in text), f"{label} ⇒ 报错文案不像拒读：{text!r}"


def test_poison_absent_ledger_file_reds_never_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒③b：账文件整个缺席（读都不到）⇒ 同一条腿判红。只改内存里的 LEDGER_PY 指向。"""
    monkeypatch.setattr(s34, "LEDGER_PY", tmp_path / "not-built" / "board_shim_ledger.py")
    with pytest.raises(AssertionError):
        _load_inregister_rows()


def test_poison_empty_ledger_dict_still_reds_ruler_directly() -> None:
    """注毒③c：就算毒绕过了取数口、直接把空账喂进尺②，尺②自己也得红（两道牙，不是一道的）。"""
    _deleted, _ledger, live, _lazy = _mesh_state()
    v = _ledger_vs_list(frozenset(), {}, live)
    assert any("为空" in x for x in v), f"空账喂进尺②没红：{v}"
    v2 = _ledger_vs_list(DELETED_MODULES, _rows_to_targets(_load_inregister_rows()), {})
    assert any("塌陷" in x for x in v2), f"零现算垫片喂进尺②没红：{v2}"


def test_poison_shell_child_missing_reds_and_stubbed_restore_reds() -> None:
    """注毒④：壳形少钉一枚 ⇒ 尺④红；桩一个「文件回到盘上」⇒ 尺③红（不写真件）。"""
    _deleted, ledger, _live, lazy = _mesh_state()
    thin = {k: frozenset(v) for k, v in SHELL_PACKAGES.items()}
    victim = min(lazy)
    assert victim in thin, f"盘上现算的惰性壳 {victim} 没被 SHELL_PACKAGES 覆盖（尺④该红才对）"
    stripped = {k: (frozenset() if k == victim else v) for k, v in thin.items()}
    v = _shell_form_vs_list(DELETED_MODULES, stripped, ledger, lazy)
    assert any(victim in x for x in v), f"壳形少钉未被点名（尺④瞎了）：{v}"
    restored = "plugins/bot_unified_runtime/sender/__init__.py"
    hits = _physical_absence(
        DELETED_MODULES, DELETED_MODULE_FORMS, on_disk=lambda rel: rel == restored
    )
    assert any(restored in x for x in hits), f"桩出来的复活件没被尺③抓住：{hits}"


def test_mesh_reports_every_offender_by_name_not_a_count() -> None:
    """成员级口径锁：一次毒里多塞三条、摘两条 ⇒ 五条**逐名**都得到点名，不许只报个数。"""
    ghosts = frozenset(
        f"plugins.bot_unified_runtime.domains.ghost_{i}" for i in (1, 2, 3)
    )
    dropped = frozenset(
        {"plugins.bot_unified_runtime.character.reminders", "plugins.bot_unified_runtime.sender"}
    )
    v = _forms_vs_list((DELETED_MODULES | ghosts) - dropped, DELETED_MODULE_FORMS)
    for g in sorted(ghosts):
        assert any(g in x for x in v), f"多塞的 {g} 没被点名：{v}"
    for d in sorted(dropped):
        assert any(d in x for x in v), f"摘掉的 {d} 没被点名：{v}"
    assert len(v) == len(ghosts) + len(dropped), f"逐名点名数不符：{v}"


# ==========================================================================
# 本波没动的缺口（在册债 · 2026-10-06 名单↔账对账波 · 待主会话＋用户裁）
# ==========================================================================
# 今日现算读数（尺①②③④实跑留档；枚数以尺现算或 census `--report` 为准，本注释不抄数——规则 10）：
#   名单 ∩ 在册账 = 空 · 名单 ∩ 现算垫片 = 空 · 账上「行在件没」滞后行 = 0 条
#   ⇒ **残余差集 0 条**，无需为「正当映射」开例外；唯一真漂是壳形那一处（`runtime` 父包其实是
#   惰性壳却没被 `SHELL_PACKAGES` 覆盖），已按「只准变严」加钉，**名单一条都没删没改**。
#
# 〔债 D-DELSPEC-1 · 2026-10-06 · 待裁〕`DELETED_MODULES` 是 **curated 子集**，不是全量退役镜像。
#   历史退役旧名（`…runtime.reactions`、`…output.templates`、`…runtime.aliases`、`…llm.channel_health`、
#   `…output.card_render.*`、`…policy.*` 若干批）都没进名单，而「已退役」集合**没有任何机器册可反查**
#   ——census 只算在盘垫片、`SHIM_ROWS` 退役即摘行 ⇒ 快照推不出历史，对账只能对「互斥」不能对「全覆盖」。
#   要裁的是：名单扩成全量镜像（代价＝别席在飞的 import 会当场被判红），还是继续只钉「旧名可静默解」
#   那一类。裁前本席不擅自扩面。
#
# 〔债 D-DELSPEC-2 · 2026-10-06 · 待裁〕`plugins.bot_unified_runtime.llm` 的壳面对**任意**子模块名
#   都兜 canonical（`import_module(_CANONICAL_PKG + "." + name)`）⇒ 尺④只能钉名单已有的名，
#   `from plugins.bot_unified_runtime.llm import channel_health` 这类「旧名静默可用」仍在面上。
#   census `--report` 的读点盲区把该 `__init__.py` 记为 `no-canonical-derived` 是同因（其顶注 S118
#   段自述「按硬界没落地的两件事①：`_CANONICAL_PKG` 形」）。正解＝给壳包加一层「可解析全名表」，
#   超出本席「只准动一枚测试文件」的边界，故只登记不修。
#
# 〔债 D-DELSPEC-3 · 2026-10-06 · ✅ 已并轨〕仓里那**第四处**手抄已删路径清单
#   ＝`tests/test_copy_redline_gate.py` 的 `test_gate_scope_sanity` 那段「退役断言」（逐枚
#   `assert not exists`），曾与 `DELETED_MODULES` / `DELETED_MODULE_FORMS` **零对账**
#   ⇒ 同一族病（手抄名单＝第二处真身；尺③已经证明「从名单派生」比逐枚点名更不会漂）。
#   并轨已落（主会话于同批补账，席位当时受「只准动一枚文件」的边界所限）：那段清单改由
#   `_derive_scope_retired_paths()` ＝**名单派生 ∪ 显式例外表**给出，该文件再无第二条入口，
#   并新常驻一枚咬合锁 `test_gate_scope_retirement_assertions_mesh_the_single_list`
#   （首跑点名 33 条：4 条"既非名单派生也未登记例外"＋29 条"名单已退役形态本门失明"）。
#   那 4 枚独有路径（`capabilities/echo.py`、`character/addressing.py`、`runtime/usage_monitor.py`、
#   `runtime/error_report.py`）**是否该并进名单**＝D-DELSPEC-1 的射程，仍待裁（M4 首腿已备好：
#   一并入即点名催摘例外）。名单本身一条未删未改。
