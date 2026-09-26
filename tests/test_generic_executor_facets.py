"""统一接入波 · S-FACETS 席常驻门：根泛型执行器「逐条量尺」登记表只读活性锁。

一句话判据：生产里每一个走泛型执行器（``_run_simple_capability`` positional 位 +
``pipeline.handle_async`` 的 ``capability_id=`` 关键字位）的能力 id，都必须在本席
登记表 ``_FACETS`` 里恰好出现一次，adapter 判定与根 AST 可推导事实自洽；
新冒未登记 id ⇒ 红；登记而真树消失 ⇒ 也红（强制显式改账，不许糊）。

组合复用（铁律 7）：文件枚举复用 S-GAP 席扫描器 ``scripts/orchestration_wired_census.py``
的 ``_iter_sources``（它只读关键字位，positional 支路由本件补齐并反哺其盲区账）。
本件纯 AST + 只读数据表（capability_registry 经文件路径 spec 装载，零包 import 副作用、
零 nonebot、零网络）。注毒自证：三条合成输入用例，负样本必红。
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[0]
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(_REPO_ROOT))

# 与 S-GAP 台账同型：先把 v1 判据以顶层名请进 sys.modules，再载 census——
# census 内部 `import test_orchestration_callsite_single` 命中同一实例，
# pytest 收集该文件时亦复用之（否则同盘双实例、fixture 全炸——本席实跑踩过）。
import test_orchestration_callsite_single as _v1  # noqa: F401  （存在性即锁）

_SPEC = importlib.util.spec_from_file_location(
    "orchestration_wired_census", _REPO_ROOT / "scripts" / "orchestration_wired_census.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_census = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_census)

_ROOT_REL = "__init__.py"
_PKG_REL = "plugins/bot_unified_runtime/"


def _load_registry_by_path():
    """注册册零包内 import（Keystone 家规），故按文件 spec 装载，绕开插件装配。"""
    spec = importlib.util.spec_from_file_location(
        "capability_registry_facets",
        _REPO_ROOT
        / "plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses 惰性解析 `X | None` 注解要回查 sys.modules[cls.__module__]；
    # 不先登记则 exec_module 当场 AttributeError（本席实跑踩过）。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _call_cid(call: ast.Call) -> tuple[str, str] | None:
    """返回 (capability_id, 形态)；泛型执行器两族的字面量判据。"""
    func = call.func
    name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
    if name == "_run_simple_capability":
        # 位置参形态 (bot, event, factory, capability_id, matcher)——中央台账扫描器
        # 只读关键字位，这 21 处对它不可见；本件是 positional 支路的唯一判据。
        if len(call.args) >= 4:
            cid = call.args[3]
            factory = call.args[2]
            if isinstance(cid, ast.Constant) and isinstance(cid.value, str):
                return cid.value, f"simple:{type(factory).__name__}"
        return None
    if name == "handle_async":
        for kw in call.keywords:
            if kw.arg == "capability_id" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value, "handle_async"
    return None


def _scan_live_facets() -> dict[str, set[str]]:
    hits: dict[str, set[str]] = {}
    for rel, src in _census._iter_sources():
        if rel == "runtime/capability_protocols.py":
            continue  # 中央真源自构造不算生产调用点（与 S-GAP 台账同口径）
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:  # RF2-5 口径对齐：静默 continue=假绿温床，改当场炸（与 parity 门同判）
            raise AssertionError(f"泛型执行器量尺扫描到语法错误文件，拒绝静默跳过：{rel}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                found = _call_cid(node)
                if found:
                    hits.setdefault(found[0], set()).add(rel)
    return hits


#: S-FACETS 登记面（25 条，逐格证据见 .superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-FACETS.md §A；
#: 2026-09-27 S-SEAM-FOLLOW-b 跟随 P0-A 显式改账，留痕见下方迁移注记与 .superpowers/sdd/
#: 2026-09-27-fullload/logs/SEAT-SEAM-FOLLOW-b.md）。
#: 值=(adapter, 执行真身 `plugins/.../mod.py#symbol`)。command=builder 只吃 config，中央可自构；
#: prepared=执行体必须由调用方经 context 交来（根闭包/内联构造持有运行期依赖）。
#: ⚠ P0-A 迁出六枚（2026-09-27，本门判据头注「登记的泛型执行器 id 在真树消失⇒红（迁移须显式改账）」
#: 的设计情形兑现）：bot.content / bot.group_info / bot.image_search / bot.media_archive /
#: bot.meme_library / bot.music 的根站点已从 `pipeline.handle_async(...capability_id=字面)` 迁入
#: `_run_capability_through_pipeline` 中央汇缝，泛型执行器面上真树消失 ⇒ 自本表注销；
#: 其通电记账随同波迁入 tests/test_descriptor_wiredness_ledger.py 的 WIRED 桶（过渡臂），
#: 本门与台账两门各管一段、一枚不丢。consent/host_state 本就不在本表（迁缝前也不在泛型面登记）。
#: bot.subscribe/bot.today_history **保留**：命令腿虽已入缝（台账记 wired），push 腿
#: （根 :4761/:1864 `pipeline.handle_async` 字面）仍是泛型执行器真身，本量尺继续逐格钉住。
_FACETS: dict[str, tuple[str, str]] = {
    # ---- command 面（8）----
    "bot.wiki": ("command", _PKG_REL + "domains/location/capabilities/wiki.py#build_wiki_capability"),
    "bot.news": ("command", _PKG_REL + "domains/subscribe/capabilities/news.py#build_news_capability"),
    "bot.randpic": ("command", _PKG_REL + "domains/meme/capabilities/randpic.py#build_randpic_capability"),
    "bot.moegirl": ("command", _PKG_REL + "domains/location/capabilities/moegirl.py#build_moegirl_capability"),
    "bot.meme": ("command", _PKG_REL + "domains/meme/capabilities/meme.py#build_meme_capability"),
    "bot.reminder": ("command", _PKG_REL + "domains/schedule/capabilities/reminder.py#build_reminder_capability"),
    "bot.daily_assist": ("command", _PKG_REL + "domains/assistant/daily/capabilities/daily_assist.py#build_daily_assist_capability"),
    "bot.tts": ("command", _PKG_REL + "domains/media/capabilities/tts.py#build_tts_capability"),
    # （bot.image_search 已随 P0-A 入缝注销，见上方留痕。）
    # ---- prepared 面（17）----
    "bot.weather": ("prepared", _PKG_REL + "domains/weather/capabilities/weather.py#build_weather_capability"),
    "bot.market": ("prepared", _PKG_REL + "domains/finance/capabilities/market.py#build_market_capability"),
    "bot.stocks": ("prepared", _PKG_REL + "domains/finance/capabilities/stocks.py#build_stocks_capability"),
    "bot.fx": ("prepared", _PKG_REL + "domains/finance/capabilities/fx.py#build_fx_capability"),
    "bot.commodities": ("prepared", _PKG_REL + "domains/finance/capabilities/market.py#build_commodities_capability"),
    "bot.bond": ("prepared", _PKG_REL + "domains/finance/capabilities/market.py#build_bond_capability"),
    "bot.northbound": ("prepared", _PKG_REL + "domains/finance/capabilities/market.py#build_northbound_capability"),
    "bot.divination": ("prepared", _PKG_REL + "domains/divination/capabilities/divination.py#build_divination_capability"),
    "bot.epic": ("prepared", _PKG_REL + "domains/subscribe/capabilities/epic.py#build_epic_capability"),
    "bot.eat": ("prepared", _PKG_REL + "domains/food/capabilities/eat.py#build_eat_capability"),
    "bot.affinity": ("prepared", _PKG_REL + "domains/chat_reply/capabilities/affinity.py#build_affinity_capability"),
    "bot.emergency_info": ("prepared", _PKG_REL + "domains/emergency_info/capabilities/emergency_info.py#build_emergency_info_capability"),
    "bot.ignore": ("prepared", _PKG_REL + "domains/chat_reply/capabilities/echo.py#build_ignore_guide_result"),
    "bot.campus_forward": ("prepared", _PKG_REL + "domains/assistant/campus/campus.py#build_campus_source"),
    "bot.chat": ("prepared", _PKG_REL + "domains/chat_reply/capabilities/chat.py#build_chat_capability"),
    "bot.subscribe": ("prepared", _PKG_REL + "domains/subscribe/capabilities/subscribe_v2.py#build_subscribe_capability_v2"),
    "bot.today_history": ("prepared", _PKG_REL + "domains/subscribe/capabilities/today_history.py#build_today_history_capability"),
    # （bot.content / bot.group_info / bot.media_archive / bot.meme_library / bot.music
    #  已随 P0-A 入缝注销，见上方留痕。）
}


# ===========================================================================
# 判据谓词（纯函数，喂真树与喂合成皆可；注毒自证直接打这里）
# ===========================================================================
def _diff_ids(live: set[str], registered: set[str]) -> list[str]:
    added = live - registered
    gone = registered - live
    problems: list[str] = []
    if added:
        problems.append(f"[FACETS-COVER] 泛型执行器冒出未登记 id（先量尺再登记）：{sorted(added)}")
    if gone:
        problems.append(f"[FACETS-COVER] 登记的泛型执行器 id 在真树消失（迁移须显式改账）：{sorted(gone)}")
    return problems


def _derive_simple_adapter(factory_node: ast.expr) -> str:
    """simple 面 adapter 的**可推导**判据：裸 domain builder 名 ⇒ command；
    根 wrapper（``_build_*`` 闭包 render_backend）或 inline lambda ⇒ prepared。"""
    if isinstance(factory_node, ast.Name) and not factory_node.id.startswith("_build_"):
        return "command"
    return "prepared"


def _diff_simple_derivations(root_tree: ast.AST, facets: dict[str, tuple[str, str]]) -> list[str]:
    problems: list[str] = []
    for node in ast.walk(root_tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "_run_simple_capability") or len(node.args) < 4:
            continue
        cid_node = node.args[3]
        if not (isinstance(cid_node, ast.Constant) and isinstance(cid_node.value, str)):
            continue
        cid = cid_node.value
        if cid not in facets:
            continue  # 缺失由 _diff_ids 归因，不重复报
        derived = _derive_simple_adapter(node.args[2])
        if derived != facets[cid][0]:
            problems.append(f"[FACETS-ADAPTER] {cid} 登记 {facets[cid][0]} 与根 AST 推导 {derived} 打架")
    return problems


def _diff_command_signatures(trees: dict[str, ast.Module], facets: dict[str, tuple[str, str]]) -> list[str]:
    """command 面结构判据：builder 除首位 config 外不得有**必填**参数（`builder(config)` 必须可 call）。"""
    problems: list[str] = []
    for cid, (adapter, ref) in facets.items():
        if adapter != "command":
            continue
        file_part, _, symbol = ref.partition("#")
        rel = file_part.removeprefix(_PKG_REL)
        tree = trees.get(rel)
        if tree is None:
            problems.append(f"[FACETS-CMD] {cid} 真身文件未扫到：{rel}")
            continue
        fn = next(
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == symbol), None
        )
        if fn is None:
            problems.append(f"[FACETS-CMD] {cid} 真身符号不存在：{rel}#{symbol}")
            continue
        args = fn.args
        pos = args.posonlyargs + args.args
        required_kwonly = [
            kw.arg
            for kw, d in zip(args.kwonlyargs, [None] * (len(args.kwonlyargs) - len(args.kw_defaults)) + args.kw_defaults)
            if d is None
        ]
        required_positional = len(pos) - len(args.defaults)
        if required_positional > 1 or required_kwonly:
            problems.append(
                f"[FACETS-CMD] {cid}={symbol} 非 config-only（必填位参>1 或必填 kwonly={required_kwonly}），"
                "command 形中央自构必崩"
            )
    return problems


def _build_facet_trees(facets: dict[str, tuple[str, str]]) -> dict[str, ast.Module]:
    """按需解析全部 facet ref 指向的真身文件（rel→module AST），同一文件只解析一次；
    文件不存在的 rel 不进 trees，交 `_diff_ref_symbols` 归因（不在此崩）。"""
    trees: dict[str, ast.Module] = {}
    for _adapter, ref in facets.values():
        rel = ref.partition("#")[0].removeprefix(_PKG_REL)
        if rel in trees:
            continue
        path = _REPO_ROOT / "plugins/bot_unified_runtime" / rel
        if not path.exists():
            continue
        trees[rel] = ast.parse(path.read_text(encoding="utf-8"))
    return trees


def _module_level_symbols(tree: ast.Module) -> set[str]:
    """模块顶层 def / async def / class 的名字集合（ref 的 `#symbol` 必须命中其一）。"""
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _diff_ref_symbols(trees: dict[str, ast.Module], facets: dict[str, tuple[str, str]]) -> list[str]:
    """RF2-3 正向锁（command + prepared 全 31 条）：每条 ref 的 `mod.py#symbol` 必须真的在该模块顶层
    存在同名 def/class。堵死评审 P3——把 prepared 面指向不存在的符号，三条旧谓词仍全 []（无人查符号）。"""
    problems: list[str] = []
    for cid, (_adapter, ref) in facets.items():
        file_part, _, symbol = ref.partition("#")
        rel = file_part.removeprefix(_PKG_REL)
        if not symbol:
            problems.append(f"[FACETS-REF] {cid} ref 缺 `#symbol` 段：{ref!r}")
            continue
        tree = trees.get(rel)
        if tree is None:
            problems.append(f"[FACETS-REF] {cid} 真身文件未扫到/不存在：{rel}")
            continue
        if symbol not in _module_level_symbols(tree):
            problems.append(f"[FACETS-REF] {cid} 登记真身符号不存在于模块顶层：{rel}#{symbol}")
    return problems


def _command_factory_names_from_root(root_tree: ast.AST) -> dict[str, str]:
    """root 里以裸公共 builder 直呼的 `_run_simple_capability(bot, ev, <Name>, cid, grp)` → {cid: <Name>}。
    command 面"执行真身符号"的**独立 oracle**（与登记 ref 字符串非同一来源）。"""
    out: dict[str, str] = {}
    for node in ast.walk(root_tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
        if name != "_run_simple_capability" or len(node.args) < 4:
            continue
        factory, cid = node.args[2], node.args[3]
        if (
            isinstance(cid, ast.Constant)
            and isinstance(cid.value, str)
            and isinstance(factory, ast.Name)
            and not factory.id.startswith("_")
        ):
            out[cid.value] = factory.id
    return out


def _diff_command_facet_symbols_against_root(
    root_tree: ast.AST, facets: dict[str, tuple[str, str]]
) -> list[str]:
    """RF2-3 反向锁（command 面双向）：root 真身实际直呼的裸 builder 名 ⇔ 登记的 `#symbol` 必须同名。
    "真身里存在但没如实登记"→ 红。prepared 面的 builder 藏在 `_build_*` 闭包/lambda 里、root 无独立裸名
    oracle，故仅受 `_diff_ref_symbols` 正向存在锁约束（已在 docstring/日志报备）。"""
    problems: list[str] = []
    for cid, factory_name in sorted(_command_factory_names_from_root(root_tree).items()):
        if cid not in facets:
            continue  # cid 级缺失由 _diff_ids（FACETS-COVER 新增 id）归因，不重复报
        _adapter, ref = facets[cid]
        symbol = ref.partition("#")[2]
        if symbol != factory_name:
            problems.append(
                f"[FACETS-REF] {cid} 登记真身符号 {symbol!r} 与 root 直呼 builder {factory_name!r} 不一致"
            )
    return problems


# ===========================================================================
# ① 真树活性判据
# ===========================================================================
def test_live_generic_executor_ids_exactly_match_facet_registry() -> None:
    live = set(_scan_live_facets())
    assert live == set(_FACETS), "; ".join(_diff_ids(live, set(_FACETS))) or "集合相等却报红（不该发生）"


def test_simple_family_adapter_derivation_agrees_with_registry() -> None:
    root_src = (_REPO_ROOT / "plugins/bot_unified_runtime/__init__.py").read_text(encoding="utf-8")
    problems = _diff_simple_derivations(ast.parse(root_src), _FACETS)
    assert not problems, "; ".join(problems)


def test_command_facet_builders_are_config_only() -> None:
    trees: dict[str, ast.Module] = {}
    for adapter, ref in _FACETS.values():
        rel = ref.partition("#")[0].removeprefix(_PKG_REL)
        if rel in trees:
            continue
        path = _REPO_ROOT / "plugins/bot_unified_runtime" / rel
        trees[rel] = ast.parse(path.read_text(encoding="utf-8"))
    problems = _diff_command_signatures(trees, _FACETS)
    assert not problems, "; ".join(problems)


def test_all_facet_refs_point_to_existing_module_symbols() -> None:
    """RF2-3 正向活性：command + prepared 全 31 条 ref 的 `#symbol` 必须真在真身模块顶层存在
    （旧门只查 command 签名、prepared 面连符号都不查——评审 P3 定罪）。"""
    problems = _diff_ref_symbols(_build_facet_trees(_FACETS), _FACETS)
    assert not problems, "; ".join(problems)


def test_command_facet_symbols_match_root_direct_builders() -> None:
    """RF2-3 反向活性：root 以裸 builder 直呼的 command cid，登记的 `#symbol` 必须与 root 实际调用同名。"""
    root_src = (_REPO_ROOT / "plugins/bot_unified_runtime/__init__.py").read_text(encoding="utf-8")
    problems = _diff_command_facet_symbols_against_root(ast.parse(root_src), _FACETS)
    assert not problems, "; ".join(problems)


def test_every_facet_id_is_registered_in_capability_registry() -> None:
    """登记面不许漂出注册册在册集（route 行 ∪ 受控内部能力）——「中央补 floor 改可达性」
    报备的前提是 id 先在册，在册才有唯一表行可抄。"""
    registry = _load_registry_by_path()
    declared = {decl.capability_id for decl in registry.ROUTE_CAPABILITY_DECLARATIONS}
    declared |= set(registry.CONTROLLED_INTERNAL_CAPABILITIES)
    ghost = set(_FACETS) - declared
    assert not ghost, f"登记了未在册 id（先补 route/受控登记再来量尺）：{sorted(ghost)}"


# ===========================================================================
# ② 注毒自证（判据不是空转：负样本必红）
# ===========================================================================
def test_poison_new_id_is_red() -> None:
    assert _diff_ids(set(_FACETS) | {"bot.new_facet_probe"}, set(_FACETS))


def test_poison_vanished_id_is_red() -> None:
    assert _diff_ids(set(_FACETS) - {"bot.wiki"}, set(_FACETS))


def test_poison_adapter_and_signature_lies_are_red() -> None:
    # 谎 1：把 wrapper 闭包依赖的 id 登记成 command ⇒ 推导判据红
    lied = dict(_FACETS)
    lied["bot.weather"] = ("command", lied["bot.weather"][1])
    root_src = (_REPO_ROOT / "plugins/bot_unified_runtime/__init__.py").read_text(encoding="utf-8")
    assert _diff_simple_derivations(ast.parse(root_src), lied)
    # 谎 2：把带必填依赖的 builder 登记成 command ⇒ 签名判据红（拿 chat 真身喂 command）
    lied2 = {"bot.chat_probe": ("command", _FACETS["bot.chat"][1])}
    rel = _FACETS["bot.chat"][1].partition("#")[0].removeprefix(_PKG_REL)
    tree = ast.parse((_REPO_ROOT / "plugins/bot_unified_runtime" / rel).read_text(encoding="utf-8"))
    assert _diff_command_signatures({rel: tree}, lied2)


def test_poison_prepared_ref_to_missing_symbol_is_red() -> None:
    """RF2-3 正向注毒：把一条 prepared ref 指向不存在的符号 ⇒ 正向存在锁必红。
    修法前（评审 P3 实跑）三条旧谓词全 [] ——prepared 面符号存在性无人校验。"""
    lied = dict(_FACETS)
    adapter, ref = lied["bot.weather"]
    lied["bot.weather"] = (adapter, ref.partition("#")[0] + "#nonexistent_symbol_xyz")
    problems = _diff_ref_symbols(_build_facet_trees(lied), lied)
    assert any("nonexistent_symbol_xyz" in s for s in problems), f"prepared 指向虚符号未被拦：{problems}"


def test_poison_command_ref_symbol_mismatch_vs_root_is_red() -> None:
    """RF2-3 反向注毒（隔离反向判据）：把 bot.wiki 登记到另一文件里一个"存在"的 builder
    （正向锁因此不误伤），但它与 root 对 bot.wiki 实际直呼的 build_wiki_capability 不同名
    ⇒ 反向锁必红（"真身里存在但没如实登记"）。"""
    lied = dict(_FACETS)
    lied["bot.wiki"] = ("command", _PKG_REL + "domains/subscribe/capabilities/news.py#build_news_capability")
    # 正向不误伤：build_news_capability 确在 news.py 顶层 ⇒ 红只能来自反向"名不符"
    assert _diff_ref_symbols(_build_facet_trees(lied), lied) == [], "正向不该因这条毒而红（须隔离反向判据）"
    root_src = (_REPO_ROOT / "plugins/bot_unified_runtime/__init__.py").read_text(encoding="utf-8")
    problems = _diff_command_facet_symbols_against_root(ast.parse(root_src), lied)
    assert any("bot.wiki" in s for s in problems), f"反向锁未生效：{problems}"


# ===========================================================================
# ③ RF2-5：positional 泛型入口预筛盲区 + 语法错误不再静默
# ===========================================================================
def test_census_prefilter_covers_positional_generic_callsites() -> None:
    """结构锁（RF2-5）：census._iter_sources 的廉价预筛必须把两族泛型执行器入口子串并入——
    旧写法只认 `"capability_id="`，纯 positional 的 `_run_simple_capability(bot,ev,f,"cid",g)` 文件
    整份被滤掉，令 facets/descriptor 双门对这类调用点失明（评审 P3b）。"""
    census_src = (_REPO_ROOT / "scripts" / "orchestration_wired_census.py").read_text(encoding="utf-8")
    body = re.search(r"def _iter_sources\b.*?(?=\ndef |\Z)", census_src, re.DOTALL)
    assert body is not None, "找不到 _iter_sources 定义（被搬走？）"
    assert "_run_simple_capability(" in body.group(0), "预筛未并入 positional 泛型入口子串"
    assert "handle_async(" in body.group(0), "预筛未并入 handle_async 子串"


def test_poison_syntax_error_file_fails_loud_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒（RF2-5）：扫描到语法错误文件必须当场抛、不再静默 continue（旧=假绿温床，与 parity 门对齐）。
    隔离真树：把 `_iter_sources` 换成一份坏语法源，断言 `_scan_live_facets` 抛 AssertionError。"""
    monkeypatch.setattr(_census, "_iter_sources", lambda: [("domains/ghost/broken.py", "def (")])
    with pytest.raises(AssertionError, match="语法错误"):
        _scan_live_facets()
