"""Wave 3-D 席常驻门：location / finance / meme / subscribe 四域调用点活性账。

权威：``docs/design/capability-orchestration-adoption-spec.md`` §1 D-b / §4 Wave3 / §7。
本件**不复制** Wave 1 门的扫描器——按文件路径装载 ``test_orchestration_callsite_single``
并把本席四域的追踪面并进去，再复用它的 ``scan`` / ``check_invariants``（组合非复制）。

三层执法：
① 活性 ledger：真树直呼/invoker 两面必须恰好等于本席评审过的登记；任一侧漂移当场红。
② 端到端逐字段等值：五种**真实签名形态**各建一枚局部 invoker + 转发型 adapter，
   ``data[PRESENTATION_DATA_KEY]`` 与直呼 builder 产出的呈现契约 ``model_dump()`` 逐字段相等，
   并锁死「运行期依赖忠实透传」（缺依赖诚实 DENIED，绝不静默丢卡图）。
③ 注毒自证：新增直呼 / 第二 invoker 点 / 半迁移 / 摘 descriptor 四态各杀各锁。

本席另钉一条别处没有的锁族（泛型执行器两面）：四域多数生产执行点走 root 泛型执行器
``_run_simple_capability``，builder 符号只作位置实参传入、不落 ``ast.Call`` ⇒ **结构门对这条路
天然看不见**（``test_generic_executor_path_is_structurally_invisible`` 继续钉这个盲区本身）。
Wave 4.1 已在该执行器落下主缝 ``offload_capability(_orchestrated(capability_id, factory, config))``
⇒ 原「诚实锁」自陈的退役条件成立，按简报**改写为正向锁**
``test_generic_executor_capability_step_goes_through_orchestration_seam``：装配点的执行步确实
经过 ``orchestrated_command`` 接缝（AST 判据 + ``test_seam_lock_is_not_toothless`` 杀伤力自证）。

全离线：零网络、零真实数据源、零消息发送、零真实订阅轮询。
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# 复用 Wave 1 门扫描器（tests/ 非包 ⇒ 按文件路径装载）
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent
_WAVE1_GATE = _TESTS_DIR / "test_orchestration_callsite_single.py"
_spec = importlib.util.spec_from_file_location("_wave1_callsite_gate", _WAVE1_GATE)
assert _spec is not None and _spec.loader is not None
v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v1)

_PKG_ROOT = v1._PKG_ROOT  # …/plugins/bot_unified_runtime

# ---------------------------------------------------------------------------
# 本席四域追踪面（16 枚 builder 真身 → 15 个 capability id；实测 2026-09-22）
# ---------------------------------------------------------------------------
_CAP_WIKI = "bot.wiki"
_CAP_MOE = "bot.moegirl"
_CAP_RANDPIC = "bot.randpic"
_CAP_MEME = "bot.meme"
_CAP_MEME_LIB = "bot.meme_library"
_CAP_NEWS = "bot.news"
_CAP_EPIC = "bot.epic"
_CAP_HISTORY = "bot.today_history"
_CAP_SUBSCRIBE = "bot.subscribe"

_CAPS_D = frozenset({
    _CAP_WIKI, _CAP_MOE, _CAP_RANDPIC, _CAP_MEME, _CAP_MEME_LIB,
    _CAP_NEWS, _CAP_EPIC, _CAP_HISTORY, _CAP_SUBSCRIBE,
    "bot.fx", "bot.market", "bot.stocks", "bot.commodities", "bot.bond", "bot.northbound",
})

_TRACKED_D: dict[str, str] = {
    # location
    "build_wiki_capability": _CAP_WIKI,
    "build_moegirl_capability": _CAP_MOE,
    # finance（六条全部只有泛型执行器一条路，见 §test_generic_executor…）
    "build_fx_capability": "bot.fx",
    "build_market_capability": "bot.market",
    "build_stocks_capability": "bot.stocks",
    "build_commodities_capability": "bot.commodities",
    "build_bond_capability": "bot.bond",
    "build_northbound_capability": "bot.northbound",
    # meme
    "build_randpic_capability": _CAP_RANDPIC,
    "build_meme_capability": _CAP_MEME,
    "build_meme_library_capability": _CAP_MEME_LIB,
    # subscribe
    "build_news_capability": _CAP_NEWS,
    "build_epic_capability": _CAP_EPIC,
    "build_today_history_capability": _CAP_HISTORY,
    "build_subscribe_capability": _CAP_SUBSCRIBE,
    "build_subscribe_capability_v2": _CAP_SUBSCRIBE,
}

_DEF_FILES_D: dict[str, set[str]] = {
    "build_wiki_capability": {"domains/location/capabilities/wiki.py"},
    "build_moegirl_capability": {"domains/location/capabilities/moegirl.py"},
    "build_fx_capability": {"domains/finance/capabilities/fx.py"},
    "build_market_capability": {"domains/finance/capabilities/market.py"},
    "build_commodities_capability": {"domains/finance/capabilities/market.py"},
    "build_bond_capability": {"domains/finance/capabilities/market.py"},
    "build_northbound_capability": {"domains/finance/capabilities/market.py"},
    "build_stocks_capability": {"domains/finance/capabilities/stocks.py"},
    "build_randpic_capability": {"domains/meme/capabilities/randpic.py"},
    "build_meme_capability": {"domains/meme/capabilities/meme.py"},
    "build_meme_library_capability": {"domains/meme/capabilities/meme_library.py"},
    "build_news_capability": {"domains/subscribe/capabilities/news.py"},
    "build_epic_capability": {"domains/subscribe/capabilities/epic.py"},
    "build_today_history_capability": {"domains/subscribe/capabilities/today_history.py"},
    "build_subscribe_capability": {"domains/subscribe/capabilities/subscribe.py"},
    "build_subscribe_capability_v2": {"domains/subscribe/capabilities/subscribe_v2.py"},
}

_CID_TO_CAP_D: dict[str, str] = {cap: cap for cap in _CAPS_D}

_ROOT = "__init__.py"
_SMOKE_CONSOLE = "domains/ops/smoke/console_chat.py"
_SMOKE_DEMO = "domains/ops/smoke/route_demo.py"

# ---------------------------------------------------------------------------
# ① 活性 ledger（坐标实测见 SEAT-S-W3D §1；本席禁碰 root ⇒ 全部直呼点原样登记）
# ---------------------------------------------------------------------------
# root 直呼点（可见）：wiki 6498/8607、news 6508/8622、epic 6513/8627、
#   today_history 6539/8672/8182、subscribe(v2) 6577/6737/7312、meme_library 6606/8513/8644；
#   finance 六条来自 :4138-4155 薄闭包 `return build_x_capability(config_, render_backend=…)`
#   ——return 位置的调用**不属注入豁免**，故可见（本席首轮把 finance 记成「零可见」是错的，已按实跑改）。
# smoke 直呼点（演示链，非生产消息路径，但结构上确是执行直呼 ⇒ 必须登记而非豁免）
KNOWN_DIRECT_ALLOWLIST_D: dict[str, set[str]] = {
    _CAP_WIKI: {_ROOT, _SMOKE_CONSOLE, _SMOKE_DEMO},
    _CAP_MOE: set(),
    _CAP_RANDPIC: set(),
    _CAP_MEME: {_SMOKE_DEMO},
    _CAP_MEME_LIB: {_ROOT},
    _CAP_NEWS: {_ROOT},
    _CAP_EPIC: {_ROOT, _SMOKE_CONSOLE, _SMOKE_DEMO},
    _CAP_HISTORY: {_ROOT, _SMOKE_CONSOLE, _SMOKE_DEMO},
    _CAP_SUBSCRIBE: {_ROOT},
    "bot.fx": {_ROOT},
    "bot.market": {_ROOT},
    "bot.stocks": {_ROOT},
    "bot.commodities": {_ROOT},
    "bot.bond": {_ROOT},
    "bot.northbound": {_ROOT},
}
# root 生产消息路径内**零可见直呼**的 id：它们的唯一生产执行点是 :8216 泛型执行器
# （builder 只作位置实参交出）⇒ 结构门对它们 entirely 盲。Wave 4.1 必须点名这三个，
# 否则「这三个已接入」会是无法被任何机器门证伪的说法。
BLIND_IN_ROOT: frozenset[str] = frozenset({_CAP_MOE, _CAP_RANDPIC, _CAP_MEME})
# 四域**尚未通电**（descriptor 未在册、root 未改 invoke）⇒ invoker 面必为空。
# 主会话落 §2-C 原子批后，把对应 id 的承载模块从这里挪进 KNOWN_INVOKER_SITES_D 并加进 WIRED_D。
KNOWN_INVOKER_SITES_D: dict[str, set[str]] = {}
WIRED_D: set[str] = set()


def _patch_wave1_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 Wave 1 门的追踪面并上本席四域（改模块全局，让 scan/_cid_to_cap 认得新符号/id）。"""
    orig_cid_to_cap = v1._cid_to_cap

    def _cid_to_cap(cid: str) -> str | None:
        return _CID_TO_CAP_D.get(cid) or orig_cid_to_cap(cid)

    monkeypatch.setattr(v1, "_TRACKED", {**v1._TRACKED, **_TRACKED_D}, raising=False)
    monkeypatch.setattr(v1, "_DEF_FILES", {**v1._DEF_FILES, **_DEF_FILES_D}, raising=False)
    monkeypatch.setattr(v1, "_cid_to_cap", _cid_to_cap, raising=False)


def _load_d_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        rel = v1._rel(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(sym in text for sym in _TRACKED_D) or "capability_id=" in text:
            index[rel] = text
    return index


def _d_scan(monkeypatch: pytest.MonkeyPatch,
            index: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """返回四域 (直呼全集, invoker 全集)——两字典都以 15 个 id 键满，缺项=空集。

    键满是有意的：``check_invariants`` 直接 ``invoker[cap]`` 取值，且「键不存在」与
    「存在但为空」在断言里长得一样，会让自证测试假绿（本席首轮就踩了一次）。
    """
    _patch_wave1_scope(monkeypatch)
    direct, invoker = v1.scan(index)
    mine = {cap: direct.get(cap, set()) for cap in _CAPS_D}
    inv = {cap: invoker.get(cap, set()) for cap in _CAPS_D}
    assert set(mine) == set(inv) == set(_CAPS_D), "扫描面未覆盖四域全部 id"
    return mine, inv


def test_real_tree_matches_wave3d_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    """真树直呼/invoker 两面必须恰好等于四域登记——任一侧漂移当场红。"""
    direct, invoker = _d_scan(monkeypatch, _load_d_index())
    assert direct == KNOWN_DIRECT_ALLOWLIST_D, f"直呼面漂移：实得 {direct} ≠ 登记 {KNOWN_DIRECT_ALLOWLIST_D}"
    invoker_nonempty = {cap: mods for cap, mods in invoker.items() if mods}
    assert invoker_nonempty == KNOWN_INVOKER_SITES_D, (
        f"invoker 面漂移：实得 {invoker_nonempty} ≠ 登记 {KNOWN_INVOKER_SITES_D}"
    )
    merged_allow = {**v1.KNOWN_DIRECT_ALLOWLIST, **KNOWN_DIRECT_ALLOWLIST_D}
    assert v1.check_invariants(
        direct, invoker, wired=WIRED_D, allowlist=merged_allow,
    ) == []


def test_wave3d_symbols_are_actually_tracked(monkeypatch: pytest.MonkeyPatch) -> None:
    """分类面自证：16 真身全在追踪表、定义文件存在且被豁免（漏登记=直呼永不红=门变哑）。"""
    assert len(_TRACKED_D) == 16
    assert set(_TRACKED_D.values()) == _CAPS_D
    for symbol, def_files in _DEF_FILES_D.items():
        assert symbol in _TRACKED_D
        for df in def_files:
            assert (_PKG_ROOT / df).exists(), f"{symbol} 定义文件坐标漂移：{df}"
    # 真身同文件内部自用 ⇒ 豁免；**换一份别的文件必须立刻算直呼**（否则豁免面就是漏判洞）
    same_file, _ = _d_scan(monkeypatch, {
        "domains/finance/capabilities/market.py":
        "def build_bond_capability(cfg=None, *, render_backend=None):\n    return 1\n"
        "def _x():\n    return build_bond_capability(1)\n"
    })
    assert same_file["bot.bond"] == set(), "真身同文件内部组合被误判为直呼点"
    other_file, _ = _d_scan(monkeypatch, {
        "domains/finance/data/_elsewhere.py":
        "def _x():\n    return build_bond_capability(1)\n"
    })
    assert other_file["bot.bond"] == {"domains/finance/data/_elsewhere.py"}, (
        "定义文件豁免面外扩：别处直呼竟不红"
    )


# ---------------------------------------------------------------------------
# ①′ Wave 4.1 主缝落位锁（S-W3D2 席：原「诚实锁」自陈退役条件达成，改写为正向锁）
# ---------------------------------------------------------------------------
#: 接缝真身 = ``runtime/capability_protocols.py::orchestrated_command``；root 侧以
#: ``from .runtime.capability_protocols import orchestrated_command as _orchestrated`` 的
#: **函数体内别名**接入（函数体内 import 是设计意图：顶置会顶漂下方被门钉住的 live 坐标）。
#:
#: 与 Wave 1 件的 ``test_wave41_seam_routes_command_facet_through_central_gate`` **判据不同、
#: 不是第二真身**：那条钉「缝本身行为对不对」（在册走中央门 / blocked 温和短句 / 未在册回落旧路），
#: 本件钉「root 装配点到底有没有把执行步交给这道缝」——行为对而调用点没翻，生产仍走旧路。
#:
#: 行号一律不进断言（本仓口径见 ``test_orchestration_callsite_wave3_c.py`` 里
#: 「行号钉法是本仓反复漂移的病根 / 行号只进失败信息供定位」那条注释）。
_SEAM_SYMBOL = "orchestrated_command"
_SEAM_HOST_MODULE = "capability_protocols"
_EXECUTOR_FUNCTION = "_run_simple_capability"
_OFFLOAD_FUNCTION = "offload_capability"
_FACTORY_PARAMETER = "capability_factory"


def _seam_bindings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """壳模块来路的名字绑定：(指向 ``orchestrated_command`` 的本地名, 指向壳模块的本地名)。

    只认从 ``…capability_protocols`` import 进来的名字 ⇒ 谁在本地另写一个同名函数冒充，
    判据不认（"名字对上了但真身不是它"正是要防的那种假接入）。
    """
    symbols: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").rpartition(".")[2] == _SEAM_HOST_MODULE:
                for alias in node.names:
                    if alias.name == _SEAM_SYMBOL:
                        symbols.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.rpartition(".")[2] == _SEAM_HOST_MODULE:
                    modules.add(alias.asname or alias.name.split(".", 1)[0])
    return symbols, modules


def _seam_calls(scope: ast.AST, symbols: set[str], modules: set[str]) -> list[ast.Call]:
    """``scope`` 子树内的接缝调用（裸名 / 别名 / ``模块.名字`` 三形态都认）。"""
    found: list[ast.Call] = []
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        by_local_name = isinstance(target, ast.Name) and target.id in symbols
        by_module_attr = (isinstance(target, ast.Attribute)
                          and target.attr == _SEAM_SYMBOL
                          and isinstance(target.value, ast.Name)
                          and target.value.id in modules)
        if by_local_name or by_module_attr:
            found.append(node)
    return found


def _forwards_factory_product(executor: ast.AST, seam: ast.Call) -> bool:
    """接缝交出的执行体须源自 ``capability_factory(…)``：直调，或先落本地名再交出。

    两种形态都放行是刻意的——把 ``capability_factory(config)`` 提成局部变量是同义改写；
    但"执行体不再来自工厂"意味着命令形能力的真身来源变了，那种必须红。
    """
    preassigned: set[str] = set()
    for node in ast.walk(executor):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id == _FACTORY_PARAMETER:
                targets: list[ast.expr] = (
                    list(node.targets) if isinstance(node, ast.Assign) else [node.target]
                )
                for target in targets:
                    if isinstance(target, ast.Name):
                        preassigned.add(target.id)
    arguments = list(seam.args) + [keyword.value for keyword in seam.keywords]
    for argument in arguments:
        if (isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Name)
                and argument.func.id == _FACTORY_PARAMETER):
            return True
        if isinstance(argument, ast.Name) and argument.id in preassigned:
            return True
    return False


def _executor_seam_facts(src: str) -> tuple[bool, bool]:
    """判据：``(执行步经过接缝, 接缝交出的是工厂产物)``。

    纯函数——吃源码字符串、吐两个布尔、不抛异常（语法垃圾也诚实判 False）。
    同一把尺子既量真树（正向锁），也量合成源码（注毒自证），这才是"有杀伤力"的形态：
    Wave 4.1 之前的真树喂进来必得 ``(False, False)``，现役真树必得 ``(True, True)``。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return (False, False)
    executors = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name == _EXECUTOR_FUNCTION
    ]
    # 恰一个执行器：零个=执行器改名/搬走，两个=长出第二真身，两种都不许静默放行
    if len(executors) != 1:
        return (False, False)
    symbols, modules = _seam_bindings(tree)
    if not symbols and not modules:
        return (False, False)
    executor = executors[0]
    for node in ast.walk(executor):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == _OFFLOAD_FUNCTION):
            continue
        seams = _seam_calls(node, symbols, modules)
        if not seams:
            continue
        return (True, _forwards_factory_product(executor, seams[0]))
    return (False, False)


def test_generic_executor_capability_step_goes_through_orchestration_seam() -> None:
    """正向锁：root 泛型执行器的「能力执行步」**已经**经过 ``orchestrated_command`` 接缝。

    本条取代原 ``test_generic_executor_path_is_structurally_invisible`` 里那条整串子串断言
    （``"offload_capability(capability_factory(config))" in src``）。该锁的注释自陈退役条件：
    「若将来有人给门加了泛型执行器识别而让它红，那是好事——连同本注释一起删掉即可」，
    Wave 4.1 落主缝即触发它。按简报要求**改写、不删除、不放宽**：判据从「旧字面量还在」
    翻成「新接缝在位」，方向相反、力度更强（AST 结构判定，不是子串嗅探）。

    语义边界（不在本锁执法面内）：走 invoker 之后**失败/超时语义与错误卡旁路是否变化**
    由主会话另案核实，本条只钉装配点的静态可达性，不替那条结论背书。
    """
    src = (_PKG_ROOT / _ROOT).read_text(encoding="utf-8")
    uses_seam, forwards_factory = _executor_seam_facts(src)
    assert uses_seam, (
        "root 泛型执行器 ``_run_simple_capability`` 的能力执行步**没有**经过 "
        "orchestrated_command 接缝 ⇒ Wave 4.1 主缝被摘掉/改名/挪出 offload_capability/"
        "长出第二个同名执行器，四种情形都会打到这条（届时在册命令形能力又回到裸直呼）"
    )
    assert forwards_factory, (
        "接缝在位但交出的执行体不是 ``capability_factory(…)`` 的产物 ⇒ 命令形能力的真身来源已变，"
        "本席四域的接入账（_ADAPTER_SHAPES / KNOWN_* 面）需重判"
    )


def test_seam_lock_is_not_toothless() -> None:
    """杀伤力自证：九型合成源码逐一把判据钉在它该红的地方，正例证明它不是一碰就碎。

    每条负样本各杀一个不同的执法面（旧形态/缝不在 offload 内/缝在别的函数/执行器缺失/
    第二真身/冒牌同名缝/实参不是工厂产物），正样本各证明一种**同义改写不该红**
    （别名或直名、函数体内或模块顶层 import、工厂直调或先落变量）。
    """
    imported = (
        "from x.runtime.capability_protocols import orchestrated_command as _orchestrated\n"
    )
    imported_plain = "from x.runtime.capability_protocols import orchestrated_command\n"
    executor_head = (
        "async def _run_simple_capability(bot, event, capability_factory, capability_id, matcher):\n"
    )
    legacy_body = (
        "    return await pipeline.handle_async(\n"
        "        message,\n"
        "        offload_capability(capability_factory(config)),\n"
        "    )\n"
    )
    seams_in_offload = (
        "    return await pipeline.handle_async(message, offload_capability(\n"
        "        _orchestrated(capability_id, capability_factory(config), config)))\n"
    )
    cases: dict[str, tuple[str, tuple[bool, bool]]] = {
        # ① Wave 4.1 **之前**的真树形态（=被退役那条锁钉的整串）：判据必须 False，
        #    否则本锁对"没接入"和"接入了"分不清 = 假锁。
        "retired_legacy_form": (imported + executor_head + legacy_body, (False, False)),
        # ② 缝存在但**没包在 offload_capability 里**（先落变量再交）：钉住的是现役形态，
        #    这种挪位=结构变更，判红并要求重估（诚实写明：本锁对该形态同样敏感）。
        "seam_outside_offload": (imported + executor_head + (
            "    step = _orchestrated(capability_id, capability_factory(config), config)\n"
            "    return await pipeline.handle_async(message, offload_capability(step))\n"),
            (False, False)),
        # ③ 缝只活在**别的函数**里：scope 面（不证明执行器这条路已通电）。
        "seam_in_other_function": (imported + (
            "async def _decoy_runner(capability_factory, capability_id):\n"
            "    return offload_capability("
            "_orchestrated(capability_id, capability_factory(config), config))\n"
        ) + executor_head + legacy_body, (False, False)),
        # ④ 执行器整个不见了（改名/搬走）：判据不得靠"别处有缝"糊过去。
        "executor_missing": (imported + (
            "async def _run_something_else(capability_factory, capability_id):\n"
            "    return offload_capability("
            "_orchestrated(capability_id, capability_factory(config), config))\n"),
            (False, False)),
        # ⑤ 长出第二个同名执行器：真身唯一性（第二真身藏旧路也不许绿）。
        "second_executor_identity": (imported + executor_head + seams_in_offload
                                     + executor_head + legacy_body, (False, False)),
        # ⑥ 本地另写同名函数冒充（无壳模块来路）：真身归属面。
        "locally_defined_fake_seam": (
            "def orchestrated_command(capability_id, capability, config):\n"
            "    return capability\n"
            + executor_head
            + "    return await pipeline.handle_async(message, offload_capability(\n"
              "        orchestrated_command(capability_id, capability_factory(config), config)))\n",
            (False, False)),
        # ⑦ 缝在位但实参不是工厂产物：第二判据单独有牙。
        "seam_without_factory_product": (imported + executor_head + (
            "    return await pipeline.handle_async(message, offload_capability(\n"
            "        _orchestrated(capability_id, None, config)))\n"), (True, False)),
        # ⑧ 同义改写**不该红**：直名 import + 工厂先落变量再交出。
        "plain_name_with_preassigned_product": (imported_plain + executor_head + (
            "    built = capability_factory(config)\n"
            "    return await pipeline.handle_async(message, offload_capability(\n"
            "        orchestrated_command(capability_id, built, config)))\n"), (True, True)),
        # ⑨ 语法垃圾：诚实 False 且不抛（判据不许把红变成 collection 崩）。
        "syntax_garbage": ("async def _run_simple_capability(:\n", (False, False)),
    }
    for name, (source, expected) in cases.items():
        assert _executor_seam_facts(source) == expected, (
            f"{name}：判据实得 {_executor_seam_facts(source)} ≠ 预期 {expected}"
            "（正例判红=一碰就碎的假锁；负例判绿=永不碎的假锁）"
        )
    # 决定性一条：真树与退役形态**判据结果不同** ⇒ 本锁能分辨 Wave 4.1 前后两个世界。
    root_src = (_PKG_ROOT / _ROOT).read_text(encoding="utf-8")
    assert _executor_seam_facts(root_src) == (True, True)
    assert _executor_seam_facts(imported + executor_head + legacy_body) == (False, False)
    assert _executor_seam_facts(imported + executor_head + seams_in_offload) == (True, True)


def test_generic_executor_path_is_structurally_invisible(monkeypatch: pytest.MonkeyPatch) -> None:
    """诚实盲区锁（**原样保留**）：结构门扫不到泛型执行器这条路。

    Wave 4.1 之前，这条连同它的字面量断言是「moegirl/randpic 已接入」唯一不被证伪的反证；
    接缝落位后它继续钉三件事，一件都没放宽：①root 生产路径内这三个 id 仍**零可见直呼**
    （盲区没被门"看见"，只是不再等于未接入）；②把 builder 作位置实参交出的形态，门判为无直呼；
    ③同一符号真被当场直呼执行，门必须立刻看见。「已接入」这一半改由
    ``test_generic_executor_capability_step_goes_through_orchestration_seam`` 执法——
    它读 AST 结构、不依赖门的眼力。
    """
    # 真树复核：root 生产路径内直呼面必须恰好等于登记 ⇒ 这三个 id 在 root 内一条可见直呼都没有
    direct, _inv = _d_scan(monkeypatch, _load_d_index())
    blind = {cap for cap, mods in direct.items() if _ROOT not in mods}
    assert blind == set(BLIND_IN_ROOT), (
        f"root 盲区面漂移：实得 {sorted(blind)} ≠ 登记 {sorted(BLIND_IN_ROOT)}"
        "（多出来=有新 id 掉进盲区；少了=盲区收窄，四域账需更新）"
    )
    # 泛型执行器的真实形态（照抄 root:8801-8802）：builder 作位置实参 ⇒ 判为「无直呼」
    passed_as_argument = (
        "def _h(bot, event):\n"
        "    return _run_simple_capability(bot, event, build_randpic_capability, 'bot.randpic', pic)\n"
    )
    direct2, _inv2 = _d_scan(monkeypatch, {"m.py": passed_as_argument})
    assert direct2["bot.randpic"] == set(), "泛型执行器点竟被识别为直呼：门的盲区已收窄，请更新四域账"
    # 同一符号一旦真被当场直呼执行，门必须立刻看见（盲区只针对「交出去」这一种形态）
    executed, _inv3 = _d_scan(monkeypatch, {
        "m2.py": "def _h(cfg):\n    return build_randpic_capability(cfg)(None, None)\n"
    })
    assert executed["bot.randpic"] == {"m2.py"}, "执行直呼漏判：门真的瞎了"


# ---------------------------------------------------------------------------
# ② 端到端逐字段等值（五种真实签名形态；局部 invoker，不碰 default_invoker 单例）
# ---------------------------------------------------------------------------
# 本席核过的签名差异 ⇒ 一枚 adapter 罩不住四域，交接块按形态分三型（见 SEAT-S-W3D §2-B）：
#   型 A 纯 config 工厂（wiki/moegirl/randpic/news）：positional=() keyword=()
#   型 B config + render_backend（finance×6 / epic / today_history）
#   型 C 装配对象前置（meme_library / subscribe / subscribe_v2）：store/registry/adapters 必给
_ADAPTER_SHAPES: dict[str, dict[str, tuple[str, ...]]] = {
    _CAP_WIKI: {"positional": (), "keyword": ()},
    _CAP_MOE: {"positional": (), "keyword": ()},
    _CAP_RANDPIC: {"positional": (), "keyword": ()},
    _CAP_NEWS: {"positional": (), "keyword": ()},
    "bot.fx": {"positional": (), "keyword": ("render_backend",)},
    _CAP_EPIC: {"positional": (), "keyword": ("render_backend",)},
    _CAP_HISTORY: {"positional": (), "keyword": ("render_backend", "on_subscriptions_changed")},
    _CAP_MEME_LIB: {"positional": ("store",), "keyword": ("mood_valence_fn",)},
    _CAP_SUBSCRIBE: {"positional": ("store", "registry"), "keyword": ()},
}


def _make_forwarding_adapter(builder, shape: dict[str, tuple[str, ...]], family: str):
    """转发型信封适配器（与交接块 §2-B 同形态的参考实现）。

    缺失的运行期依赖一律诚实 DENIED——绝不「只传 config」蒙混过关（那会静默丢卡图=行为变更）。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        InvocationStatus,
        _result,
    )

    positional, keyword = shape["positional"], shape["keyword"]

    def _handle(request):
        message = request.payload.get("message")
        if message is None:
            return _result(request, InvocationStatus.DENIED, detail="payload.message 缺失")
        context = request.context
        args = []
        for key in positional:
            if key not in context:
                return _result(request, InvocationStatus.DENIED,
                               detail=f"位置依赖缺失：context.{key}")
            args.append(context[key])
        kwargs = {}
        for key in keyword:
            if key not in context:
                return _result(request, InvocationStatus.DENIED,
                               detail=f"运行期依赖缺失：context.{key}")
            kwargs[key] = context[key]
        capability = builder(context.get("config"), *args, **kwargs)
        presented = capability(message, context.get("decision"))
        return _result(
            request, InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: presented.model_dump()},
            via=family,
        )

    return _handle


def _local_invoker(cap_id: str, shape: dict[str, tuple[str, ...]], builder):
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityDescriptor,
        CapabilityFamily,
        CapabilityInvoker,
        CapabilityRegistry,
        HandlerRegistry,
    )
    # family 借用 MEDIA：壳的 CapabilityFamily 是闭合四值枚举（MEDIA/FILES/SEARCH/CREATION），
    # 本四域**无对应族**且枚举所在文件禁碰 ⇒ 已在 §2-A 请主会话新增 APP 族。
    # fixture 只为跑通信封链路，不代表 descriptor 落册时的最终值。
    descriptor = CapabilityDescriptor(
        capability_id=cap_id, family=CapabilityFamily.MEDIA, title=cap_id,
        input_protocol="payload.message; context.config + 运行期依赖",
        output_protocol="data[presentation_result]: CapabilityResult.model_dump()",
        required_roles=("user",), implementation_ref="tests/_wave3d_fixture",
        fallback_chain=("honest_degrade:依赖缺失或取数失败=诚实说明",),
    )
    registry = CapabilityRegistry()
    registry.register(descriptor)
    handlers = HandlerRegistry()
    handlers.register(cap_id, _make_forwarding_adapter(builder, shape, cap_id.rsplit(".", 1)[-1]))
    return CapabilityInvoker(registry=registry, handlers=handlers)


class _FakeCapabilityResultFactory:
    """呈现契约替身：字段够真（media/actions/audit_tags 齐全），逐字段比对才有意义。

    ``debug_id``/``request_id`` 显式钉值——否则两次构造各摇一个 uuid，等值断言恒红且毫无信息量。
    """

    @staticmethod
    def make(marker: str):
        from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
            CapabilityResult,
        )
        return CapabilityResult(
            request_id="req-wave3d-fixed", capability_id=marker, kind="card",
            title=f"四域卡 {marker}", summary="摘要", body=f"正文 {marker}",
            images=[{"url": f"file:///tmp/{marker}.png", "title": marker}],
            actions=[{"type": "none"}], audit_tags=["seat:S-W3D"],
            confidence=0.5, debug_id="dbg-wave3d-fixed",
        )


def _recording_builder(marker: str, calls: list[tuple]):
    def _build(config, *args, **kwargs):
        calls.append((config, args, tuple(sorted(kwargs))))
        presented = _FakeCapabilityResultFactory.make(marker)

        def _capability(message, decision):
            calls.append(("invoke", message, decision))
            return presented
        return _capability
    return _build


@pytest.mark.parametrize("cap_id", sorted(_ADAPTER_SHAPES))
def test_e2e_wave3d_equals_direct(cap_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """经 invoker 通电 == 直呼 builder：呈现载荷逐字段相等 + 依赖忠实透传。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        CapabilityRequest,
        InvocationStatus,
    )
    shape = _ADAPTER_SHAPES[cap_id]
    required = list(shape["positional"]) + list(shape["keyword"])
    context: dict[str, object] = {"config": SimpleNamespace(bot_x=True), "decision": None,
                                  "message": SimpleNamespace(plain_text="你好")}
    for key in required:
        context[key] = SimpleNamespace(name=key)
    calls: list[tuple] = []
    invoker = _local_invoker(cap_id, shape, _recording_builder(cap_id, calls))

    result = invoker.invoke(CapabilityRequest(
        capability_id=cap_id, payload={"message": context["message"]},
        principal="u", roles=("user",), context=context,
    ))
    assert result.status is InvocationStatus.OK
    presented = _FakeCapabilityResultFactory.make(cap_id).model_dump()
    assert result.data[PRESENTATION_DATA_KEY] == presented, "呈现契约被 invoker 增删/改写=行为变更"
    # 依赖忠实透传：builder 收到的位置/关键字实参与 context 同源对象
    build_call = calls[0]
    assert build_call[0] is context["config"]
    assert list(build_call[1]) == [context[k] for k in shape["positional"]]
    assert set(build_call[2]) == set(shape["keyword"])

    # 缺任一必需依赖 ⇒ 诚实 DENIED 且不带呈现载荷（绝不静默丢卡图）
    for key in required:
        stripped = {k: v for k, v in context.items() if k != key}
        calls2: list[tuple] = []
        inv2 = _local_invoker(cap_id, shape, _recording_builder(cap_id, calls2))
        bad = inv2.invoke(CapabilityRequest(
            capability_id=cap_id, payload={"message": context["message"]},
            principal="u", roles=("user",), context=stripped,
        ))
        assert bad.status is InvocationStatus.DENIED, f"缺 {key} 竟然放行"
        assert PRESENTATION_DATA_KEY not in bad.data
        assert bad.detail.strip(), "DENIED 必须给诚实说明"
        assert calls2 == [], "依赖缺失时不该把 builder 叫起来"


def test_e2e_blocked_role_denied_without_payload() -> None:
    """中央权限门（旧直呼没有的**新增**执法面）：blocked 角色无条件拒、不带载荷。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        CapabilityRequest,
        InvocationStatus,
    )
    calls: list[tuple] = []
    shape = _ADAPTER_SHAPES[_CAP_WIKI]
    invoker = _local_invoker(_CAP_WIKI, shape, _recording_builder(_CAP_WIKI, calls))
    result = invoker.invoke(CapabilityRequest(
        capability_id=_CAP_WIKI, payload={"message": SimpleNamespace()},
        principal="u", roles=("blocked",), context={"config": SimpleNamespace()},
    ))
    assert result.status is InvocationStatus.DENIED
    assert PRESENTATION_DATA_KEY not in result.data
    assert calls == []


# ---------------------------------------------------------------------------
# ③ 注毒自证（四态各杀各锁）
# ---------------------------------------------------------------------------
def _poison_direct_src(module: str, symbol: str) -> dict[str, str]:
    return {module: f"from x import {symbol}\ndef f(cfg):\n    return {symbol}(cfg)(None, None)\n"}


def test_poison_new_direct_site_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒①：allowlist 之外新增一处执行直呼 ⇒ 「未登记直呼点」红。"""
    index = {**_load_d_index(), **_poison_direct_src("domains/finance/capabilities/sneaky.py",
                                                    "build_stocks_capability")}
    direct, invoker = _d_scan(monkeypatch, index)
    merged = {**v1.KNOWN_DIRECT_ALLOWLIST, **KNOWN_DIRECT_ALLOWLIST_D}
    violations = v1.check_invariants(direct, invoker, wired=WIRED_D, allowlist=merged)
    assert any("未登记直呼点" in s and "bot.stocks" in s for s in violations), f"注毒未被拦：{violations}"


def test_poison_second_invoker_site_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒②：两个模块各 invoke bot.fx ⇒ 「第二调用点」红（全树每能力恰一处）。"""
    src = ("def f():\n    default_invoker().invoke("
           "CapabilityRequest(capability_id='bot.fx'))\n")
    direct, invoker = _d_scan(monkeypatch, {"m1.py": src, "m2.py": src})
    merged = {**v1.KNOWN_DIRECT_ALLOWLIST, **KNOWN_DIRECT_ALLOWLIST_D}
    violations = v1.check_invariants(direct, invoker, wired=WIRED_D, allowlist=merged)
    assert any("第二调用点" in s and "bot.fx" in s for s in violations), f"第二 invoker 点未被拦：{violations}"


def test_poison_half_migration_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒③：同模块既直呼 build_news_capability 又 invoke bot.news ⇒ 半迁移红。"""
    src = (
        "from plugins.bot_unified_runtime.domains.subscribe.capabilities.news import "
        "build_news_capability\n"
        "def f(cfg):\n"
        "    build_news_capability(cfg)(None, None)\n"
        "    default_invoker().invoke(CapabilityRequest(capability_id='bot.news'))\n"
    )
    direct, invoker = _d_scan(monkeypatch, {"domains/subscribe/capabilities/sneaky.py": src})
    merged = {**v1.KNOWN_DIRECT_ALLOWLIST, **KNOWN_DIRECT_ALLOWLIST_D}
    violations = v1.check_invariants(direct, invoker, wired=WIRED_D, allowlist=merged)
    assert any("半迁移" in s and "bot.news" in s for s in violations), f"半迁移未被拦：{violations}"


def test_poison_wired_capability_still_direct_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒③′：某能力一旦登记为 WIRED，任何直呼当场红（比「未登记」更狠，防走回头路）。

    注毒落在**真实 root 文本尾部**（替换会连带抹掉别的 id 的直呼、让本锁失去针对性）。
    """
    index = _load_d_index()
    index[_ROOT] = index[_ROOT] + (
        "\nasync def _s_w3d_poison(bot, event):\n"
        "    return build_moegirl_capability(None)(None, None)\n"
    )
    direct, invoker = _d_scan(monkeypatch, index)
    merged = {**v1.KNOWN_DIRECT_ALLOWLIST, **KNOWN_DIRECT_ALLOWLIST_D}
    violations = v1.check_invariants(direct, invoker, wired={_CAP_MOE}, allowlist=merged)
    assert any("已通电却仍直呼" in s and _CAP_MOE in s for s in violations), (
        f"通电后走回头路未被拦：{violations}"
    )
    # 同一次注毒不该波及其它 id 的账（证明注毒是加法而非替换）
    assert direct[_CAP_WIKI] == KNOWN_DIRECT_ALLOWLIST_D[_CAP_WIKI]


def test_descriptor_missing_fails_honestly_and_direct_path_still_works() -> None:
    """注毒④：descriptor 不在册 ⇒ invoke 诚实 UNAVAILABLE 不崩，且旧直呼路照样走得通。

    这正是「descriptor 先落、调用点后翻」的安全序：主会话落 §2-A 那笔时线上零风险；
    反过来（先翻调用点、descriptor 未在册）才会当场打断现网指令面。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityInvoker,
        CapabilityRegistry,
        CapabilityRequest,
        HandlerRegistry,
        InvocationStatus,
    )
    empty = CapabilityInvoker(registry=CapabilityRegistry(), handlers=HandlerRegistry())
    result = empty.invoke(CapabilityRequest(
        capability_id="bot.market", payload={"query": "上证"}, principal="u", roles=("user",),
    ))
    # 实测两种「不在册」形态：id 完全没进注册表 ⇒ FAILED（detail=未登记能力）；
    # descriptor 在册但 handler 未注册 ⇒ UNAVAILABLE（见 creation.tts.synthesize 先例）。
    # 两者都是诚实降级、都不携带呈现载荷、都不抛异常 ⇒ 生产据此回落旧直调。
    assert result.status in {InvocationStatus.FAILED, InvocationStatus.UNAVAILABLE}
    assert result.detail.strip(), "未在册必须给诚实说明，不许静默"
    assert "presentation_result" not in result.data
    # 旧直呼路不依赖壳：真身模块仍可定位（本席禁改 ⇒ 只验可达，不调用）
    for symbol, def_files in _DEF_FILES_D.items():
        assert def_files, f"{symbol} 无定义文件坐标 ⇒ 直呼路不可达"
