"""中央调度收编「闭口」常驻门（席 C-D-01 · 2026-10-02 落）。

## 0 本门是什么、不是什么

2026-09-24 那波（S550/S574）把「中央调度收编完成」的复合判据④写成了一份**草案**，它只住在
gitignore 的 `.superpowers/` 树里、从没进 `tests/` ⇒ **文档宣称有门、盘上没有门**（本仓老毛病：
叙述≠真身）。本件把那扇**不存在的门换成真的**，并按本仓付过学费的规矩落地：
**地板＝今天真实覆盖面**（不是目标态），后续波次只准往上抬；抬的过程必须留字面痕迹。

它钉的四条账（全部现算，本文件不抄总数当判据）：

| 轴 | 今天为真的判据 | 腿 |
|---|---|---|
| 中央实管 | 在册 id 里真被 `orchestrated_command` 交给层 2 的那批，枚数与逐枚名册都不得低于手写地板 | ①②③ |
| 到缝≠实管 | 走到汇合缝、却因未登记执行形而回落旧路的那批 ⇒ 逐枚在册账内，账只准缩不许留幽灵 | ④ |
| 入口形 | 有中央汇缝的形不低于手写地板、缝名必须是盘上真身 def；没缝的形逐枚给理由 | ⑤ |
| 决策接管 | `engine_only` 仍躺保留位期间，受支持∩保留＝∅、运行期不落保留值、生产与 `.env` 零接管赋值 | ⑥⑦ |

外加三把元锁：⑧地板/上限必须是**手写字面整数**（派生地板结构上不可能红）、⑨**分母卫生**
（本门源码里不许出现等于当期在册总数的整数字面量）、⑩**只读自证**（读完输入字节不变、扫描面稳定）。

**本门不宣称**（越界即假账，逐条点名由谁管）：
- 不宣称「所有内容已走中央调度」。地板＝现状；`在册总数 − 地板` 那批今天仍不在管下（腿⑭把这句写成判据）。
- 不重复 `tests/test_descriptor_wiredness_ledger.py` 的**缺口账**：那一本第四臂数的是「根汇缝字面量站点」，
  凡到缝即记 wired；本尺数的是「执行形在册」。腿④专记两尺之差（今日恰 12 枚），不改对方判据。
- 不重复 `tests/test_orchestration_callsite_single.py`（直呼点唯一性）/
  `tests/test_prepared_adapter_canary.py`（多入口活性）/ `tests/test_five_entry_seam_lock.py`
  （主动投递+回执两形）/ `tests/test_offseam_wired_contradiction_gate.py`（wired∧直呼矛盾）/
  `tests/test_central_dispatch_matrix.py`（逐 id 执行行为矩阵）。
- 本件对 `default_invoker()` 单例**一个字节都不碰**（往它注册会让别的集合比对门当场假红——canary 同款纪律）。

## 1 取数口（唯一真身，全现算）

- 分母：`plugins/bot_unified_runtime/runtime/capability_protocols.py::CAPABILITY_DESCRIPTOR`
- 实管判据：同模块 `_route_execution_adapters()` × `_KNOWN_ADAPTERS`。为什么这就是「真交层 2」：
  `orchestrated_command` 里那一行「执行形不在已知形就原样跑旧路」⇒ 未登记 id 的权限/健康/限额/审计
  **一次都不过**（层 2 的 sink 与门谓词都只在 invoker 内部 emit）。
- 到缝面：AST 扫生产面交给三枚缝（`_run_simple_capability` / `_run_capability_through_pipeline` /
  `orchestrated_command`）的 `capability_id` **字面量**；变量携带那形另记 non-literal（腿⑪j 试牙）。
- 入口形：`domains/core/capability_manifest.py::EntryKind` × `ARM_FORM_SEAMS`
- 接管面：`domains/core/decision/shadow.py` 的 `SUPPORTED_MODES` / `RESERVED_FUTURE_MODES`
  / `normalize_decision_mode` / `resolve_decision_mode` ＋ AST 扫生产面与 `.env` / `.env.example`

## 2 注毒纪律

注毒全走**内存合成数据**（判据收参数），本门一个生产文件都不写：开工时根 `__init__.py` 与
`runtime/settings.py` 有他席在飞，写它＝撞车且可能把崩溃留在盘上。「还原后 cmp 字节相同」这一
纪律由腿⑩改成**每次运行都自证**（扫前扫后逐文件 sha256 等值），比一次性注毒更强。
每发注毒都喂给**真执法函数**并断言抛的是 `AssertionError`（不是 ImportError／不是 collection error），
断言里点名该腿自己的编号——红的归因不许靠猜。

全离线：只读源码树 + import 生产模块取表，零网络、零运行数据触点、零进程副作用。
"""

from __future__ import annotations

import ast
import hashlib
import random
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from plugins.bot_unified_runtime.domains.core import (
    capability_manifest as cm,
)
from plugins.bot_unified_runtime.domains.core.decision import (
    shadow as decision_shadow,
)
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

_PRODUCTION_SCOPES = ("plugins", "scripts", "bot.py")
_SEAM_FUNCS = frozenset(
    {"_run_simple_capability", "_run_capability_through_pipeline", "orchestrated_command"}
)
#: 决策模式的两张「可能被赋值」的名字表：env 键名与 Config 字段名（真身读 `shadow.py` / `config.py`）。
_DECISION_TARGET_NAMES = frozenset({"bot_decision_engine_mode", "DECISION_MODE_ENV", "DECISION_MODE_CONFIG_KEY"})
_DECISION_ENV_KEYS = frozenset({"BOT_DECISION_ENGINE_MODE"})


# ===========================================================================
# 取数口（纯函数：喂真树＝今值，喂合成源＝注毒）
# ===========================================================================


def descriptor_ids() -> frozenset[str]:
    """分母唯一真身（现算；本文件任何断言都不许抄它的总数，见腿⑨）。"""
    ids = frozenset(cp.CAPABILITY_DESCRIPTOR)
    assert ids, "在册表读空＝本门没有分母，绝不许绿（尺瞎与全员收编在两把尺上同形）"
    return ids


def adapter_map() -> dict[str, str]:
    return dict(cp._route_execution_adapters())


def known_adapters() -> frozenset[str]:
    return frozenset(cp._KNOWN_ADAPTERS)


def _live_descriptor() -> frozenset[str]:
    """主锁统一走这枚取数口（注毒靠 monkeypatch 别的口，分母本身永远现算）。"""
    return descriptor_ids()


def governed_from(
    descriptor: Iterable[str], adapters: Mapping[str, str], known: Iterable[str]
) -> frozenset[str]:
    """腿①②③的判据真身：在册 ∧ 执行形 ∈ 已知形 ⇒ `orchestrated_command` 真交层 2。"""
    reg = {str(c) for c in descriptor}
    kn = {str(k) for k in known}
    return frozenset(
        str(cid) for cid, adapter in adapters.items() if str(cid) in reg and str(adapter) in kn
    )


def _maybe_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _kw_str(node: ast.Call, keyword: str) -> str | None:
    for kw in node.keywords:
        if kw.arg == keyword and isinstance(kw.value, ast.Constant):
            return _maybe_str(kw.value.value)
    return None


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _digest_sources(sources: Mapping[str, str]) -> str:
    """输入内容指纹（键＝文件名 + 正文 sha256）。缓存键、不是判据。"""
    digest = hashlib.sha256()
    for name in sorted(sources):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(sources[name].encode("utf-8")).digest())
    return digest.hexdigest()


_RESULT_CACHE: dict[tuple[str, str], Any] = {}


def _cached(key: tuple[str, str], computer: Any) -> Any:
    """缓存的是**扫描结果**（不是 AST、不是判据）：同一输入指纹只算一次。

    这不是第二把尺：值由 `computer` 原样算出。真树整批腿共用一份结果（否则 11 次全树 AST
    往返＝一条腿两分半），注毒喂的是不同指纹的合成源 ⇒ 永不撞缓存。
    """
    if key not in _RESULT_CACHE:
        _RESULT_CACHE[key] = computer()
    return _RESULT_CACHE[key]


def memoized_on_inputs(tag: str, computer: Any) -> Any:
    def _wrapped(sources: Mapping[str, str]) -> Any:
        return _cached((tag, _digest_sources(sources)), lambda: computer(sources))

    return _wrapped


def _seam_callsite_rows_uncached(sources: Mapping[str, str]) -> list[dict[str, Any]]:
    """AST 现算「把 capability_id 交给缝」的落点。纯函数 ⇒ 注毒只喂内存串。

    字面量与非字面量**都**入册（`literal` 字段区分）：只认字面量的尺会把「变量携带 id 进缝」
    读成零落点（S81 那波的 `/bot` 派发表就是这么藏起来的）。
    """
    rows: list[dict[str, Any]] = []
    for name, text in sorted(sources.items()):
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            fname = _call_name(node.func)
            if fname not in _SEAM_FUNCS:
                continue
            cid: str | None = None
            if fname == "orchestrated_command":
                if node.args:
                    cid = _maybe_str(node.args[0].value) if isinstance(node.args[0], ast.Constant) else None
            elif fname == "_run_simple_capability":
                cid = None
                if len(node.args) >= 4 and isinstance(node.args[3], ast.Constant):
                    cid = _maybe_str(node.args[3].value)
                if cid is None:
                    cid = _kw_str(node, "capability_id")
            else:
                cid = _kw_str(node, "capability_id")
                if cid is None and node.args and isinstance(node.args[0], ast.Constant):
                    cid = _maybe_str(node.args[0].value)
            rows.append(
                {
                    "file": name,
                    "line": int(node.lineno),
                    "seam": fname,
                    "capability_id": cid,
                    "literal": cid is not None,
                }
            )
    return rows


#: 对外唯一取数口（判据同上，只多一层结果缓存）。
seam_callsite_rows = memoized_on_inputs("seam_rows", _seam_callsite_rows_uncached)


def _read_production_sources() -> Mapping[str, str]:
    """缓存盘上原文（只读）；对外一律发**副本**，防调用方就地改字典污染后续腿。"""
    cached = getattr(_read_production_sources, "_cache", None)
    if cached is None:
        found: dict[str, str] = {}
        for scope in _PRODUCTION_SCOPES:
            root = _REPO_ROOT / scope
            paths = sorted(root.rglob("*.py")) if root.is_dir() else ([root] if root.is_file() else [])
            for path in paths:
                if "__pycache__" in path.parts:
                    continue
                found[path.relative_to(_REPO_ROOT).as_posix()] = path.read_text(encoding="utf-8")
        assert found, "生产扫描面读空＝取数口塌陷（目录改名／scope 被放宽），不许当「无落点」判绿"
        _read_production_sources._cache = dict(found)  # type: ignore[attr-defined]
        cached = found
    return cached


def production_sources() -> dict[str, str]:
    return dict(_read_production_sources())


def seam_literal_cids(sources: Mapping[str, str] | None = None) -> frozenset[str]:
    rows = seam_callsite_rows(production_sources() if sources is None else sources)
    return frozenset(str(r["capability_id"]) for r in rows if r["literal"])


def seam_nonliteral_sites(sources: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    rows = seam_callsite_rows(production_sources() if sources is None else sources)
    return [r for r in rows if not r["literal"]]


def entry_forms() -> frozenset[str]:
    return frozenset(str(e.value) for e in cm.EntryKind)


def forms_with_seam() -> frozenset[str]:
    return frozenset(str(k) for k in cm.ARM_FORM_SEAMS)


def seam_hosts() -> dict[str, str]:
    return {str(k): str(v) for k, v in cm.ARM_FORM_SEAMS.items()}


def _defined_func_names_uncached(sources: Mapping[str, str]) -> set[str]:
    """全树任意层级的 `def`/`async def` 名（两枚根汇缝住在函数体里、不是模块级 ⇒ 必须全深度收）。"""
    names: set[str] = set()
    for text in sources.values():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                names.add(node.name)
    return names


defined_func_names = memoized_on_inputs("func_names", _defined_func_names_uncached)


# ===========================================================================
# 手写地板（只准抬）＋ 手写上限（只准缩）＋ 缺口账本
# ===========================================================================

#: 腿①地板：被中央实管（真交层 2）的在册 id **最少**枚数。
#: 现值＝2026-10-02 本席现算（`command` 8 ＋ `prepared` 14，逐枚见下面两份名册）。
#: 抬它＝有波次真把一枚能力接进层 2（好方向）；调低＝放宽判据，须点名授权。
#: ⚠ 手写整数，腿⑧ AST 锁不许写成 `len(...)` 派生（派生地板结构上不可能红）。
CENTRAL_HANDOFF_FLOOR: int = 22

#: 腿②分形地板：`command` 形与 `prepared` 形各不少于手写值。
#: 为什么要分形：总枚数拦不住「八枚命令形全被换成预备形」这种整面搬家（形态换了、层 2 语义也换了）。
COMMAND_ADAPTER_FLOOR: int = 8
PREPARED_ADAPTER_FLOOR: int = 14

#: 腿③逐枚地板：今天确被实管的那批 id 名册。防「枚数不变、换了一批」——把 `bot.weather` 摘掉、
#: 补两枚没主的能力进去＝地板①照绿、生产少一条真通路（本仓最阴的一形退化）。
CENTRAL_HANDOFF_ID_FLOOR: frozenset[str] = frozenset(
    {
        # adapter="command"（当时值 8 枚＝2026-10-02 本席现算）
        "bot.daily_assist",
        "bot.meme",
        "bot.moegirl",
        "bot.news",
        "bot.randpic",
        "bot.reminder",
        "bot.tts",
        "bot.wiki",
        # adapter="prepared"（当时值 14 枚＝同上）
        "bot.affinity",
        "bot.bond",
        "bot.commodities",
        "bot.divination",
        "bot.eat",
        "bot.emergency_info",
        "bot.epic",
        "bot.fx",
        "bot.ignore",
        "bot.market",
        "bot.music_mode",
        "bot.northbound",
        "bot.stocks",
        "bot.weather",
    }
)

#: 腿④上限：走到汇合缝、却因未登记执行形而回落旧路（＝层 2 权限/健康/限额/审计全不过）的
#: 在册 id 条数只准缩。现值＝2026-10-02 本席现算 12。
SEAM_UNGOVERNED_CEILING: int = 12

#: 腿④账本（id → 这笔债卡在哪）。这本账的**存在理由**：`tests/test_descriptor_wiredness_ledger.py`
#: 把下面 12 枚全记成 **wired**（它的第四臂数的是「根汇缝字面量站点」），而本尺数「执行形在册」。
#: 两尺之差正是「叙述≠真身」的藏身处：缺口账绿着说"接通了"，层 2 其实一眼都没看过这些能力。
#: （不改对方判据——两把尺各自合法，缺的只是有人把差集写下来并只准它缩。）
#: ⚠ 理由文本只准描述卡点，不许写成豁免券：账在＝债在，销账的唯一办法是补执行形申报后删行。
SEAM_UNGOVERNED_LEDGER: dict[str, str] = {
    "bot.auto_send.preview": "执行形未申报（主动投递族走 submit_active_push 出口，层 2 不经）",
    "bot.consent": "执行形未申报（同意卡门；根汇缝字面量在跑但无 adapter）",
    "bot.content": "执行形未申报（内容解析；根内联闭包成品）",
    "bot.group_info": "执行形未申报（群信息；根内联闭包成品）",
    "bot.host_state": "执行形未申报（宿主状态；根内联闭包成品）",
    "bot.image_search": "执行形未申报（以图搜图；根内联闭包成品，注册册无宿主行）",
    "bot.mail.control": "执行形未申报（邮件控制面；注册册无宿主行）",
    "bot.media_archive": "执行形未申报（媒体归档；根内联闭包成品）",
    "bot.meme_library": "执行形未申报（表情包库；根内联闭包成品）",
    "bot.music": "执行形未申报（点歌；根内联闭包成品）",
    "bot.subscribe": "执行形未申报（订阅；根内联闭包成品）",
    "bot.today_history": "执行形未申报（今日史；根内联闭包成品）",
}

#: 腿⑤地板：真经中央汇缝的入口形（形名↔缝由 `ARM_FORM_SEAMS` 单源，本册只钉「不许跌破」）。
#: ⚠ 「五入口同权」是叙述面最容易读歪的一句：入口形今天共 8 格，有缝的只有这 5 格。
FORM_SEAM_FLOOR: frozenset[str] = frozenset(
    {"command", "alias", "natural_language", "active_push", "voice_ack"}
)

#: 腿⑤账本：没有中央汇缝的入口形，逐枚给理由。新增 `EntryKind` 不归类＝本腿红——逼下一波
#: 要么给那形接缝并补活性件，要么在这里点名"它没缝"，不许含糊成"五入口同权"。
SEAMLESS_FORM_REASONS: dict[str, str] = {
    "scheduler": "定时/轮询装配期任务直调能力真身，无中央汇缝、无入口活性件",
    "control_plane": "控制面 HTTP 自带派发（api/v1 一类），不经根汇缝",
    "passive_matcher": "被动监听（campus 一类）只摄取不回复，无汇缝",
}

#: 腿⑥上限：决策引擎「接管态」枚数。现值 0——`engine_only` 躺在 `RESERVED_FUTURE_MODES`，
#: `normalize_decision_mode()` 把它一律回落 `legacy_only`（fail-closed），所以「engine_only 已可用」
#: 这句今天在代码面上为假。写成上限而非地板：真要接管属迁移阶段 1+ 的用户裁决，
#: 抬它必须连带动 `shadow.py` 本体；本门只拦「静默长出来」。
DECISION_TAKEOVER_CEILING: int = 0

#: 腿⑦上限：生产面（`plugins/**` + `scripts/**` + `bot.py` + `.env` + `.env.example`）里
#: 把决策模式**赋成保留值**的落点数。现值 0。`engine_only` 这个词今天只许出现在保留位声明、
#: 回落判据与注释里，不许出现在任何赋值/传参/env 行里。
TAKEOVER_ASSIGNMENT_CEILING: int = 0


# ===========================================================================
# 判据（返回违反清单，空＝绿）
# ===========================================================================


def _check_handoff_floor(
    descriptor: Iterable[str], adapters: Mapping[str, str], known: Iterable[str]
) -> list[str]:
    governed = governed_from(descriptor, adapters, known)
    violations: list[str] = []
    if len(governed) < CENTRAL_HANDOFF_FLOOR:
        violations.append(
            f"[①地板] 中央实管 {len(governed)} 枚 < 手写地板 {CENTRAL_HANDOFF_FLOOR}"
            "＝有能力的执行形被摘了（层 2 的权限/健康/限额/审计从此不看它）。"
            "确属迁移请先补 `_route_execution_adapters()` 侧申报，再谈动地板。"
        )
    lost = sorted(CENTRAL_HANDOFF_ID_FLOOR - governed)
    if lost:
        violations.append(f"[③逐枚] 地板名册里这些 id 今日不再被实管：{lost}＝枚数可靠新增掩盖，逐枚掩盖不了。")
    return violations


def _check_per_form_floors(
    descriptor: Iterable[str], adapters: Mapping[str, str], known: Iterable[str]
) -> list[str]:
    governed = governed_from(descriptor, adapters, known)
    histogram: dict[str, int] = {}
    for cid in governed:
        key = str(adapters[cid])
        histogram[key] = histogram.get(key, 0) + 1
    violations: list[str] = []
    for adapter_name, floor, chinese in (
        ("command", COMMAND_ADAPTER_FLOOR, "命令形"),
        ("prepared", PREPARED_ADAPTER_FLOOR, "预备形"),
    ):
        got = histogram.get(adapter_name, 0)
        if got < floor:
            violations.append(f"[②分形] {chinese}（adapter={adapter_name!r}）实管 {got} 枚 < 地板 {floor}")
    total = sum(histogram.get(str(k), 0) for k in known)
    if total != len(governed):
        violations.append(
            f"[②分形] 逐形之和 {total} ≠ 实管总数 {len(governed)}＝直方图与交集判据自相矛盾（判据漏风）"
        )
    return violations


def _check_seam_ungoverned(seam_cids: Iterable[str], governed: Iterable[str]) -> list[str]:
    gov = {str(c) for c in governed}
    at_seam = {str(c) for c in seam_cids}
    live = sorted(at_seam - gov)
    violations: list[str] = []
    unknown = sorted({c for c in live if c not in SEAM_UNGOVERNED_LEDGER})
    if unknown:
        violations.append(
            f"[④新债] 到缝却回落旧路、又无账本的 id：{unknown}"
            "＝层 2 一次都不过却没人记账（缺口账 wired 与实管之差就是这么被吞掉的）。"
            "补执行形申报＝销账；确要留债须在此点名理由并抬 `SEAM_UNGOVERNED_CEILING`（要评审）。"
        )
    if len(live) > SEAM_UNGOVERNED_CEILING:
        violations.append(
            f"[④新债] 到缝未实管 {len(live)} 枚 > 上限 {SEAM_UNGOVERNED_CEILING}＝总账在涨。"
        )
    ghosts = sorted({c for c in SEAM_UNGOVERNED_LEDGER if c in gov or c not in at_seam})
    if ghosts:
        violations.append(
            f"[④幽灵账] 账本里这些条目今日已不成立（已实管，或根本不再到缝）：{ghosts}"
            "＝欠账账本不是保险箱，销账要删行。"
        )
    return violations


def _check_entry_forms(
    forms: Iterable[str],
    with_seam: Iterable[str],
    hosts: Mapping[str, str],
    real_defs: Iterable[str],
) -> list[str]:
    all_forms = {str(f) for f in forms}
    seamed = {str(f) for f in with_seam}
    defined = {str(n) for n in real_defs}
    violations: list[str] = []
    lost = sorted(FORM_SEAM_FLOOR - seamed)
    if lost:
        violations.append(
            f"[⑤地板] 这些入口形今日没有中央汇缝了：{lost}＝`ARM_FORM_SEAMS` 被缩，"
            "依赖该形的活性件（三形锁/五形锁）会一起变成空话。"
        )
    if not seamed <= all_forms:
        violations.append(f"[⑤形集] 有缝形不是入口形全集的子集：{sorted(seamed - all_forms)}")
    seamless = all_forms - seamed
    unclassified = sorted({f for f in seamless if f not in SEAMLESS_FORM_REASONS})
    if unclassified:
        violations.append(
            f"[⑤含糊账] 这些入口形既没缝也没理由：{unclassified}"
            "＝新增 EntryKind 不归类，正是「五入口同权」那句话的诞生方式。"
        )
    stale = sorted({f for f in SEAMLESS_FORM_REASONS if f in seamed or f not in all_forms})
    if stale:
        violations.append(f"[⑤幽灵账] 无理由册里这些条目已不成立：{stale}")
    for form, host in sorted(hosts.items()):
        if host not in defined:
            violations.append(
                f"[⑤幻影缝] 形 {form!r} 声明的汇缝 {host!r} 在生产源码里找不到同名 def"
                "＝在册声明指向不存在的执法点（叙述≠真身的字面形态）。"
            )
    return violations


def _check_decision_takeover(
    supported: Iterable[str], reserved: Iterable[str], resolved: str, normalize: Mapping[str, str]
) -> list[str]:
    sup = {str(s) for s in supported}
    res = {str(r) for r in reserved}
    violations: list[str] = []
    takeover = sorted(sup & res)
    if len(takeover) > DECISION_TAKEOVER_CEILING:
        violations.append(
            f"[⑥接管] 同时「受支持」又属「未来保留位」的模式：{takeover}"
            f" > 上限 {DECISION_TAKEOVER_CEILING}＝接管在阶段 0 的门面上被偷偷启用。"
        )
    if str(resolved) in res:
        violations.append(f"[⑥接管] 运行期解析出保留模式 {resolved!r}＝影子链外多了一条真发送路。")
    for raw, got in sorted(normalize.items()):
        if str(raw) in res and str(got) not in sup:
            violations.append(
                f"[⑥接管] normalize_decision_mode({raw!r}) 返回 {got!r}，既非保留位也非受支持值＝回落改口了"
            )
    return violations


def _reserved_literals_in(node: ast.AST, res: set[str]) -> list[ast.Constant]:
    return [
        c
        for c in ast.walk(node)
        if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.strip().lower() in res
    ]


def takeover_assignment_sites(sources: Mapping[str, str], reserved: Iterable[str]) -> list[str]:
    """腿⑦判据：生产源里把决策模式**赋成**保留值的落点（只认形状，不认注释与比较式）。

    为什么必须只认形状：真树里 `engine_only` 合法出现在三处**形状**上——保留位声明集合、
    回落比较（`if mode != "engine_only"`）与注释/文档措辞。把这三处也当接管声明 ⇒ 门永红。
    拦的形态＝①目标名 ∈ 决策模式名集 的赋值（含 `x: str = ...` 注解赋值）
    ②`environ[<env 键>] = <保留值>` ③`setenv(<env 键>, <保留值>)`
    ④关键字 `mode=`/字段名= 传进保留值 ⑤`.env` 行。
    """
    res = {str(r).strip().lower() for r in reserved}
    key = ("takeover", _digest_sources(sources), "|".join(sorted(res)))
    return _cached(key, lambda: _takeover_sites_uncached(sources, res))


def _takeover_sites_uncached(sources: Mapping[str, str], res: set[str]) -> list[str]:
    hits: list[str] = []
    for name, text in sorted(sources.items()):
        if Path(name).suffix != ".py":
            # `.env` / `.env.example` 只走行判据，不许拿去 AST 解析（不是 Python）
            hits += _env_reserved_lines(name, text, res)
            continue
        hits += _env_reserved_lines(name, text, res)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            raise AssertionError(f"{name} 解析失败＝扫描面有半成品，不许静默跳过（规则 6/RF2-5 同口径）")
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign | ast.AnnAssign):
                targets = list(node.targets) if isinstance(node, ast.Assign) else [node.target]
                names = {
                    str(getattr(t, "id", "") or getattr(t, "attr", "")) for t in targets
                } | {_subscript_key(t) for t in targets}
                if not (names & _DECISION_TARGET_NAMES or names & _DECISION_ENV_KEYS):
                    continue
                if node.value is None:  # 纯注解（`x: str`）无赋值，不构成接管声明
                    continue
                for const in _reserved_literals_in(node.value, res):
                    hits.append(f"{name}:{node.lineno} [赋值目标 {sorted(names)}] -> {const.value!r}")
            elif isinstance(node, ast.Call):
                fname = _call_name(node.func)
                # setenv("BOT_DECISION_ENGINE_MODE", "engine_only") / environ.__setitem__(...)
                if fname in {"setenv", "putenv", "environ.__setitem__", "__setitem__"}:
                    keyed = any(
                        isinstance(a, ast.Constant) and isinstance(a.value, str)
                        and a.value.strip().upper() in _DECISION_ENV_KEYS
                        for a in node.args
                    )
                    if keyed:
                        for const in _reserved_literals_in(node, res):
                            hits.append(f"{name}:{node.lineno} [{fname} env 键] -> {const.value!r}")
                # 任意调用里 mode=<保留值> / bot_decision_engine_mode=<保留值>
                for kw in node.keywords:
                    if (
                        kw.arg in {"mode", *_DECISION_TARGET_NAMES}
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                        and kw.value.value.strip().lower() in res
                    ):
                        hits.append(f"{name}:{node.lineno} [关键字 {kw.arg}] -> {kw.value.value!r}")
    return hits


def _subscript_key(target: ast.expr) -> str:
    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
        value = target.slice.value
        return value if isinstance(value, str) else ""
    return ""


def _env_reserved_lines(rel_name: str, text: str, res: set[str]) -> list[str]:
    """.env / .env.example 里的 `BOT_DECISION_ENGINE_MODE=<保留值>`（键名大小写不敏感，注释行除外）。"""
    if Path(rel_name).name.lower() not in {".env", ".env.example"}:
        return []
    hits: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip().upper() not in _DECISION_ENV_KEYS:
            continue
        if value.strip().strip("'\"").lower() in res:
            hits.append(f"{rel_name}:{number} [env 行] -> {value.strip()!r}")
    return hits


def env_sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in (".env", ".env.example"):
        path = _REPO_ROOT / name
        if path.is_file():
            out[name] = path.read_text(encoding="utf-8", errors="replace")
    return out


# ===========================================================================
# 主锁
# ===========================================================================


def test_01_central_handoff_floor_holds() -> None:
    """①③中央实管的枚数与逐枚名册都不得低于手写地板（只准抬）。"""
    violations = _check_handoff_floor(_live_descriptor(), adapter_map(), known_adapters())
    assert violations == [], "中央实管面跌破地板：\n" + "\n".join(violations)


def test_02_per_form_floors_and_exact_partition() -> None:
    """②分形地板（命令形/预备形各自）＋ 逐形之和恰等于实管总数（漏形或掺未知形即红）。"""
    violations = _check_per_form_floors(_live_descriptor(), adapter_map(), known_adapters())
    assert violations == [], "分形账不平：\n" + "\n".join(violations)


def test_03_governed_ids_are_registered_and_adapted() -> None:
    """③补：实管集是分母子集、非空，且每枚的 adapter 真在 `_KNOWN_ADAPTERS` 里（防判据自证）。"""
    descriptor = _live_descriptor()
    adapters, known = adapter_map(), known_adapters()
    governed = governed_from(descriptor, adapters, known)
    assert governed <= descriptor, f"实管集越出在册表：{sorted(governed - descriptor)}"
    assert governed, "今日无一枚被中央实管＝本门地板腿失去意义，须复核 `_route_execution_adapters()`"
    for cid in sorted(governed):
        assert adapters[cid] in known, f"{cid} 被计入实管却 adapter={adapters[cid]!r} 不在已知形"


def test_04_seam_reached_without_governance_is_ledgered() -> None:
    """④「走到缝却没实管」那批必须逐枚在册账内、条数只准缩、账里不许留幽灵。"""
    governed = governed_from(_live_descriptor(), adapter_map(), known_adapters())
    violations = _check_seam_ungoverned(seam_literal_cids(), governed)
    assert violations == [], "到缝未实管的账红了：\n" + "\n".join(violations)


def test_05_entry_forms_seam_floor_and_no_phantom_host() -> None:
    """⑤有缝形不低于地板、缝名必是盘上真身 def、没缝的形逐枚有名有姓。"""
    violations = _check_entry_forms(
        entry_forms(), forms_with_seam(), seam_hosts(), defined_func_names(production_sources())
    )
    assert violations == [], "入口形账红了：\n" + "\n".join(violations)


def test_06_decision_takeover_stays_zero_while_reserved() -> None:
    """⑥接管态枚数 ≤ 0：受支持∩保留＝∅、运行期解析不落保留位、回落判据不改口。"""
    violations = _check_decision_takeover(
        decision_shadow.SUPPORTED_MODES,
        decision_shadow.RESERVED_FUTURE_MODES,
        decision_shadow.resolve_decision_mode(),
        _live_normalize_map(),
    )
    assert violations == [], "决策接管面动了：\n" + "\n".join(violations)
    if "engine_only" in decision_shadow.RESERVED_FUTURE_MODES:
        assert (
            decision_shadow.normalize_decision_mode("engine_only") == decision_shadow.LEGACY_MODE
        ), (
            "engine_only 仍在保留位却不再回落 legacy_only＝「阶段 0 零行为变化」那句自述过期，"
            "本门与 docs/boards/B02 的 decision-engine 页必须同批改"
        )


def test_07_no_site_claims_takeover_mode() -> None:
    """⑦生产面＋`.env`/`.env.example` 里不许出现「把决策模式赋成保留值」的落点。"""
    hits = takeover_assignment_sites(production_sources() | env_sources(), decision_shadow.RESERVED_FUTURE_MODES)
    assert len(hits) <= TAKEOVER_ASSIGNMENT_CEILING, (
        f"出现 {len(hits)} 处接管声明（上限 {TAKEOVER_ASSIGNMENT_CEILING}）：\n" + "\n".join(hits)
        + "\nshadow.py 仍把保留模式硬回落时，任何赋成保留值的落点都是「叙述≠真身」的实物形态。"
    )


def _live_normalize_map() -> dict[str, str]:
    probe = sorted({*decision_shadow.RESERVED_FUTURE_MODES, "shadow", "legacy_only", "nonsense"})
    return {mode: decision_shadow.normalize_decision_mode(mode) for mode in probe}


# ===========================================================================
# 元锁（常量形状 + 分母卫生 + 只读自证）
# ===========================================================================

_THRESHOLD_NAMES = (
    "CENTRAL_HANDOFF_FLOOR",
    "COMMAND_ADAPTER_FLOOR",
    "PREPARED_ADAPTER_FLOOR",
    "SEAM_UNGOVERNED_CEILING",
    "DECISION_TAKEOVER_CEILING",
    "TAKEOVER_ASSIGNMENT_CEILING",
)


def _module_ast() -> ast.Module:
    return ast.parse(Path(__file__).read_text(encoding="utf-8"))


def _literal_assigned_value(tree: ast.Module, name: str) -> ast.expr | None:
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node.value
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return node.value
    return None


def test_08_threshold_constants_are_handwritten_literals() -> None:
    """⑧结构锁：地板/上限＝模块顶层整数字面量；逐枚地板＝frozenset({字符串字面量…})。

    为什么必须有：写成 `FLOOR = len(governed())` 的门**结构上不可能红**——读起来像棘轮、
    实际是散文。先例＝`test_descriptor_wiredness_ledger.py` 的 `GAP_CEILING` 三锁成链。
    """
    tree = _module_ast()
    for name in _THRESHOLD_NAMES:
        value = _literal_assigned_value(tree, name)
        assert isinstance(value, ast.Constant) and isinstance(value.value, int) and not isinstance(
            value.value, bool
        ), (
            f"{name} 不再是模块顶层整数字面量（实得 "
            f"{ast.dump(value) if value is not None else None}"
            "）＝判据被改成派生式或搬走，本门的牙齿没了"
        )
    floor_set = _literal_assigned_value(tree, "CENTRAL_HANDOFF_ID_FLOOR")
    assert isinstance(floor_set, ast.Call) and _call_name(floor_set.func) == "frozenset", (
        "CENTRAL_HANDOFF_ID_FLOOR 不再写成 frozenset({...})"
    )
    assert floor_set.args, "CENTRAL_HANDOFF_ID_FLOOR 的 frozenset 没带实参"
    inner = floor_set.args[0]
    assert isinstance(inner, ast.Set | ast.List | ast.Tuple), "逐枚地板名册不是字面集合（派生式＝可偷偷变少）"
    elements = list(inner.elts)
    assert elements and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elements), (
        "逐枚地板名册里混进非字符串字面量或为空"
    )
    assert {str(e.value) for e in elements} == set(CENTRAL_HANDOFF_ID_FLOOR), (
        "AST 里的名册 ≠ 运行期常量（被别处覆写？）"
    )


def test_09_no_hardcoded_denominator_anywhere_in_this_gate() -> None:
    """⑨分母卫生：本门源码里不许出现**等于当期在册总数**的整数字面量。

    这条自己不会过期（分母现算）：哪天有人把「共 N 枚」抄进断言，N 与当期分母相等⇒当场红。
    AGENTS 规则 10（叙述面禁手写计数）的测试侧同病同药。
    """
    live = len(_live_descriptor())
    literals = {
        int(node.value)
        for node in ast.walk(_module_ast())
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool)
    }
    assert live not in literals, (
        f"本门源码里的整数字面量撞上当期在册总数 {live}＝分母被抄成判据，"
        "注册表一加一枚就永久假红。判据只准拿分母做现算比较。"
    )
    assert live > 0


def test_10_gate_reads_inputs_without_writing_them() -> None:
    """⑩只读自证：读两遍输入、逐文件 sha256 必须一致，且扫描面非空非根文件缺席。

    这条替代「改生产文件→跑红→还原→cmp」：开工时根 `__init__.py` 与 `runtime/settings.py`
    有他席在飞，写它们＝撞车且可能把崩溃留在盘上。字节级"没动过"改成**每次运行都自证**，
    比一次性注毒更强；注毒一律走内存合成源（腿⑪各发）。
    """
    first = production_sources()
    assert any(n.endswith("__init__.py") for n in first), "扫描面里竟没有根 __init__.py＝取数口窄了"
    digests = {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in sorted(first.items())}
    second = production_sources()
    assert sorted(second) == sorted(digests), (
        f"两次扫描的文件集合不同（{len(second)} vs {len(digests)}）＝扫描面不稳定或树在动"
    )
    for name, digest in sorted(digests.items()):
        assert hashlib.sha256(second[name].encode("utf-8")).hexdigest() == digest, (
            f"{name} 在两读之间字节变了＝本门写过生产文件（硬约束第 4 条禁止）"
        )
    assert digests, "读空"


# ===========================================================================
# 注毒自证（真执法函数必须红 / 打乱必须仍绿 / 红必须是 AssertionError）
# ===========================================================================


def _gate_module() -> Any:
    return sys.modules[__name__]


def _with_ruler(monkeypatch_name: str, replacement: Any, main: Any) -> str:
    """把某枚取数口换成合成版、跑**真主锁**、断言红是 `AssertionError`，随后还原并复绿。

    记法要点（本仓为此踩过假锁）：
    - 必须调 `main()` 本体，不能只调 `_check_*`——否则红来自辅助函数、主锁有没有牙无人验。
    - 必须 `monkeypatch`/try-finally 还原后**再跑一次主锁复绿**——红只能来自判据，不来自阈值噪声。
    """
    module = _gate_module()
    original = getattr(module, monkeypatch_name)
    try:
        setattr(module, monkeypatch_name, replacement)
        with pytest.raises(AssertionError) as excinfo:
            main()
    finally:
        setattr(module, monkeypatch_name, original)
    main()
    return str(excinfo.value)


def test_11a_poison_shrinking_a_covered_item_goes_red() -> None:
    """注毒 a（合法覆盖项缩一枚）：摘掉一枚真在实管的名册 id ⇒ 主锁①当场断言红。"""
    real = adapter_map()
    victim = "bot.affinity"
    assert victim in real, f"注毒点消失：{victim} 已不在执行形名册"
    poisoned = {cid: adapter for cid, adapter in real.items() if cid != victim}
    assert len(poisoned) == len(real) - 1, "注毒没正好摘掉一枚"
    message = _with_ruler("adapter_map", lambda: poisoned, test_01_central_handoff_floor_holds)
    assert "[①地板]" in message and victim in message, f"红没点名该点的东西：{message[:240]}"


def test_11b_poison_swapping_the_covered_set_goes_red() -> None:
    """注毒 b（换一批不换枚数）：摘一枚真能力、补两枚不在册 id ⇒ 总数照旧，逐枚腿必须红。"""
    real = adapter_map()
    victim = "bot.weather"
    swapped = {cid: adapter for cid, adapter in real.items() if cid != victim}
    swapped["cd01.fake.one"] = "command"
    swapped["cd01.fake.two"] = "prepared"
    message = _with_ruler("adapter_map", lambda: swapped, test_01_central_handoff_floor_holds)
    assert "[③逐枚]" in message and victim in message, f"换批没被逐枚腿抓到：{message[:240]}"


def test_11c_poison_adding_uncovered_callsite_goes_red() -> None:
    """注毒 c（新增未覆盖项）：合成一枚「到缝、未实管、无账本」的汇缝字面量 ⇒ 主锁④红。

    手法＝把真树原文加一份**内存合成文件**再跑判据（不写盘，见腿⑩的理由）。
    """
    governed = governed_from(_live_descriptor(), adapter_map(), known_adapters())
    candidates = sorted(
        {str(c) for c in _live_descriptor()}
        - set(governed)
        - set(seam_literal_cids())
        - set(SEAM_UNGOVERNED_LEDGER)
    )
    assert candidates, "找不到一枚可注毒的在册未接 id＝分母或账本坏了，须查取数口"
    host = candidates[0]
    poisoned_source = (
        "async def _cd01_probe(bot, event, factory, config):\n"
        f'    await _run_simple_capability(bot, event, factory, "{host}", bot)\n'
    )
    sources = production_sources()
    sources["plugins/cd01_poison_probe.py"] = poisoned_source
    violations = _check_seam_ungoverned(seam_literal_cids(sources), governed)
    assert any("[④新债]" in item and host in item for item in violations), (
        f"新增未登记的到缝落点 {host} 没被抓到＝尺无牙：{violations}"
    )
    assert _check_seam_ungoverned(seam_literal_cids(), governed) == [], "真树这一腿本身就不干净"


def test_11d_poison_dropping_a_form_seam_goes_red() -> None:
    """注毒 d：`ARM_FORM_SEAMS` 少一格形 ⇒ 主锁⑤的地板腿红。

    ⚠ 替换函数里**必须调 capture 住的原件**，不能调模块同名全局——后者调到自己＝套娃
    RecursionError（canary/矩阵件同款教训：按模块属性取自己会递归）。
    """
    module = _gate_module()
    original_forms_with_seam = module.forms_with_seam
    module.forms_with_seam = lambda: original_forms_with_seam() - {"voice_ack"}
    try:
        with pytest.raises(AssertionError) as excinfo:
            test_05_entry_forms_seam_floor_and_no_phantom_host()
    finally:
        module.forms_with_seam = original_forms_with_seam
    test_05_entry_forms_seam_floor_and_no_phantom_host()
    assert "[⑤地板]" in str(excinfo.value) and "voice_ack" in str(excinfo.value), str(excinfo.value)[:240]


def test_11e_poison_phantom_seam_host_goes_red() -> None:
    """注毒 e：形声明一枚盘上不存在的汇缝 ⇒ 主锁⑤红（幻影真身＝本仓定义级事故）。"""
    poisoned = dict(seam_hosts())
    poisoned["command"] = "_run_capability_through_pipeline_named_wrongly"
    message = _with_ruler("seam_hosts", lambda: poisoned, test_05_entry_forms_seam_floor_and_no_phantom_host)
    assert "[⑤幻影缝]" in message, f"幻影缝没被抓到：{message[:240]}"


def test_11f_poison_unclassified_new_entry_form_goes_red() -> None:
    """注毒 f：新长一枚入口形却不归类（不给缝也不给理由）⇒ 主锁⑤红。"""
    module = _gate_module()
    original_entry_forms = module.entry_forms
    module.entry_forms = lambda: original_entry_forms() | {"cd01_new_form"}
    try:
        with pytest.raises(AssertionError) as excinfo:
            test_05_entry_forms_seam_floor_and_no_phantom_host()
    finally:
        module.entry_forms = original_entry_forms
    test_05_entry_forms_seam_floor_and_no_phantom_host()
    assert "[⑤含糊账]" in str(excinfo.value) and "cd01_new_form" in str(excinfo.value), str(excinfo.value)[:240]


def test_11g_poison_engine_only_takeover_goes_red() -> None:
    """注毒 g：`engine_only` 被抬进受支持集却仍留保留位 ⇒ 主锁⑥红（静默接管）。"""
    poisoned_supported = set(decision_shadow.SUPPORTED_MODES) | {"engine_only"}
    violations = _check_decision_takeover(
        poisoned_supported,
        decision_shadow.RESERVED_FUTURE_MODES,
        "engine_only",
        {"engine_only": "engine_only", "shadow": "shadow", "legacy_only": "legacy_only"},
    )
    assert any("[⑥接管]" in item for item in violations), f"接管启用没被抓到＝假锁：{violations}"
    assert len(violations) >= 2, f"同一批注毒应同时抓到相交与运行期落点，实得 {violations}"
    assert _check_decision_takeover(
        decision_shadow.SUPPORTED_MODES,
        decision_shadow.RESERVED_FUTURE_MODES,
        decision_shadow.resolve_decision_mode(),
        _live_normalize_map(),
    ) == [], "真树这一腿就不干净"


def test_11h_poison_env_claims_takeover_goes_red() -> None:
    """注毒 h：`.env` 把模式写成保留值 ⇒ 腿⑦判据抓到，且真树读数为空。"""
    hits = takeover_assignment_sites(
        {".env": "BOT_DECISION_ENGINE_MODE=engine_only\nBOT_CHAT_MODEL=x\n# =engine_only\n"},
        decision_shadow.RESERVED_FUTURE_MODES,
    )
    assert len(hits) == 1, f"env 注毒应正好抓到 1 处（注释行那发是对照，不许误抓）：{hits}"
    assert len(hits) > TAKEOVER_ASSIGNMENT_CEILING, "抓到了却没超上限＝上限被写成宽松"
    real = takeover_assignment_sites(production_sources() | env_sources(), decision_shadow.RESERVED_FUTURE_MODES)
    assert real == [], f"真树已有接管声明落点：{real}"


def test_11i_poison_setenv_claims_takeover_goes_red() -> None:
    """注毒 i：生产源里 `setenv(BOT_DECISION_ENGINE_MODE, "engine_only")` 形状必须被抓；
    比较式（`mode != "engine_only"`）**不许**被抓——那是回落守卫本身。"""
    poison_src = (
        "import os\n" 'os.environ["BOT_DECISION_ENGINE_MODE"] = "engine_only"\n'
        'os.setenv("x") if False else None\n'
    )
    guard_src = (
        "def _f(mode):\n"
        '    if mode != "engine_only":\n'
        "        return 1\n"
        "    return 2\n"
    )
    decl_src = 'RESERVED = {"engine_only"}\nCONFIG: str = "legacy_only"\n'
    res = decision_shadow.RESERVED_FUTURE_MODES
    assert takeover_assignment_sites({"plugins/poison_i.py": poison_src}, res), "environ 赋值形状没被抓到"
    assert takeover_assignment_sites({"plugins/poison_i.py": guard_src}, res) == [], (
        "回落守卫的比较式被判成接管声明＝腿⑦会把真树判红（今天真树里就有这形）"
    )
    assert takeover_assignment_sites({"plugins/poison_i.py": decl_src}, res) == [], (
        "保留位声明集合被判成接管声明＝同上（config.py/shadow.py 都含这形）"
    )


def test_11j_poison_variable_carried_site_is_counted() -> None:
    """注毒 j：变量携带 id 进缝必须记成 non-literal 落点（不许"看不见"就当没有）。"""
    src = (
        "async def _f(bot, event, factory):\n"
        '    capability_id = "bot.weather"\n'
        "    await _run_capability_through_pipeline(bot=bot, event=event, capability=factory,\n"
        "        capability_id=capability_id)\n"
    )
    rows = seam_callsite_rows({"plugins/poison_j.py": src})
    assert len(rows) == 1, rows
    assert rows[0]["literal"] is False and rows[0]["capability_id"] is None, (
        f"变量携带那形被读成字面量或整个漏掉：{rows[0]}"
    )
    real_nonliteral = seam_nonliteral_sites()
    assert isinstance(real_nonliteral, list), "non-literal 读数口坏了"


def test_11k_poison_shrinking_the_ledger_goes_red() -> None:
    """注毒 k（删行当销账）：账本少一行而真债还在 ⇒ 主锁④红。"""
    module = _gate_module()
    original = module.SEAM_UNGOVERNED_LEDGER
    try:
        module.SEAM_UNGOVERNED_LEDGER = {k: v for k, v in original.items() if k != "bot.music"}
        with pytest.raises(AssertionError) as excinfo:
            test_04_seam_reached_without_governance_is_ledgered()
    finally:
        module.SEAM_UNGOVERNED_LEDGER = original
    test_04_seam_reached_without_governance_is_ledgered()
    assert "[④新债]" in str(excinfo.value) and "bot.music" in str(excinfo.value), str(excinfo.value)[:240]


def test_11l_poison_ghost_ledger_entry_goes_red() -> None:
    """注毒 l：给一枚**今日已被实管**的能力留着欠账行 ⇒ 主锁④的幽灵腿红。

    形状取自事故：豁免册写成"留着等下一次巧合"。判据不许只看"账本条数 ≤ 上限"，
    必须逐枚反查该枚今天是否真欠账——否则涨册与销账都会在账面隐身。
    """
    module = _gate_module()
    governed = governed_from(_live_descriptor(), adapter_map(), known_adapters())
    victim = min(governed)
    original = module.SEAM_UNGOVERNED_LEDGER
    poisoned = dict(original)
    poisoned[victim] = "注毒：已实管却仍留欠账行"
    try:
        module.SEAM_UNGOVERNED_LEDGER = poisoned
        with pytest.raises(AssertionError) as excinfo:
            test_04_seam_reached_without_governance_is_ledgered()
    finally:
        module.SEAM_UNGOVERNED_LEDGER = original
    test_04_seam_reached_without_governance_is_ledgered()
    assert "[④幽灵账]" in str(excinfo.value) and victim in str(excinfo.value), str(excinfo.value)[:240]


def test_12_derived_lists_are_order_insensitive() -> None:
    """⑫顺序无关：同一批输入换枚举顺序（倒序＋固定种子乱序）重算，采集与判定逐值不变。

    防的是"按序号记账"那类假锁：清单换个顺序就变红或变绿，都是把尺子写歪。
    """
    sources = production_sources()
    reversed_sources = {k: sources[k] for k in reversed(list(sources))}
    keys = list(sources)
    random.Random(20261002).shuffle(keys)
    shuffled_sources = {k: sources[k] for k in keys}

    base_rows = seam_callsite_rows(sources)
    governed = governed_from(_live_descriptor(), adapter_map(), known_adapters())
    base_seam = _check_seam_ungoverned(seam_literal_cids(sources), governed)
    base_forms = _check_entry_forms(
        entry_forms(), forms_with_seam(), seam_hosts(), defined_func_names(sources)
    )
    for label, variant in (("倒序", reversed_sources), ("乱序", shuffled_sources)):
        assert seam_callsite_rows(variant) == base_rows, f"{label} 之后采集结果变了＝扫描依赖枚举顺序"
        assert _check_seam_ungoverned(seam_literal_cids(variant), governed) == base_seam, (
            f"{label} 之后④判定变了"
        )
        assert _check_entry_forms(
            sorted(entry_forms(), reverse=True),
            sorted(forms_with_seam(), reverse=True),
            seam_hosts(),
            sorted(defined_func_names(variant), reverse=True),
        ) == base_forms, f"{label} 之后⑤判定变了"
    assert base_seam == [] and base_forms == [], "真树基线判定不干净"


def test_13_mains_are_callable_and_reds_are_assertions() -> None:
    """⑬红的形态锁：七把主锁全部可在进程内直跑（跑不起来＝ImportError/崩，会被读成「没跑」）。

    本仓为此栽过：判据改名后整件 ImportError，读数人把「没跑」当「没欠账」。
    """
    mains = (
        test_01_central_handoff_floor_holds,
        test_02_per_form_floors_and_exact_partition,
        test_03_governed_ids_are_registered_and_adapted,
        test_04_seam_reached_without_governance_is_ledgered,
        test_05_entry_forms_seam_floor_and_no_phantom_host,
        test_06_decision_takeover_stays_zero_while_reserved,
        test_07_no_site_claims_takeover_mode,
    )
    for fn in mains:
        assert callable(fn), f"主锁 {fn!r} 不在了＝执法面被摘，不许读成绿"
        assert fn.__name__.startswith("test_0"), f"{fn.__name__} 不在主锁编号段"
        fn()  # 真跑：抛任何异常（含非断言异常）都算本腿红
    governed = governed_from(_live_descriptor(), adapter_map(), known_adapters())
    assert _check_handoff_floor(_live_descriptor(), adapter_map(), known_adapters()) == []
    assert _check_per_form_floors(_live_descriptor(), adapter_map(), known_adapters()) == []
    assert _check_seam_ungoverned(seam_literal_cids(), governed) == []
    assert _check_entry_forms(
        entry_forms(), forms_with_seam(), seam_hosts(), defined_func_names(production_sources())
    ) == []


def test_14_honest_limits_are_derived_not_prose() -> None:
    """⑭反「本门自称已收编」：三句诚实边界写成判据，哪一条翻面都要求同批改叙述。

    ① 实管枚 < 在册总数；② 有缝形 < 入口形总数；③ 受支持集里没有接管态。
    今天三条都成立。哪一天某条不成立＝有人真推进了，本腿的红是"文案要跟着改"的信号，
    抬地板/改名册必须与生产改动同批，不许只改文案。
    """
    descriptor = _live_descriptor()
    governed = governed_from(descriptor, adapter_map(), known_adapters())
    assert len(governed) < len(descriptor), (
        f"实管 {len(governed)} 已追平在册总数——「尚未全部收编」这句叙述过期，"
        "本门与地板名册要整体复判（这是好事，但要同批改文案，别留半句话）"
    )
    assert not forms_with_seam() >= entry_forms(), (
        "所有入口形都有中央汇缝了＝「5/8 形有缝」那句已被取代，本门⑤的账与 B02 板块页要复判"
    )
    assert not set(decision_shadow.SUPPORTED_MODES) & set(decision_shadow.RESERVED_FUTURE_MODES), (
        "受支持集与保留集相交＝接管已启用，本门⑥要换成「接管活性锁」并同步 decision-engine 页"
    )
