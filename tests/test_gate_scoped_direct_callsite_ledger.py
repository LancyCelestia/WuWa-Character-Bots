"""常驻门：受门能力「直呼点名册」——`gate_feature_bindings() ∩ 绕过 pipeline 直呼 invoke() == ∅`。

背景（2026-09-23T23:33Z 主代理刚接上层 2 feature 门）：`CapabilityInvoker.invoke()`
（真身 `runtime/capability_protocols.py:609`）现在会读 `gate_feature_bindings()` 并对
**在册受门**能力执法（未受门＝pass-through）。S43 施工图 §1.3「行为中性」的实算依赖一条
前提：**全树绕过 pipeline 直呼 `invoke()` 的能力，今天全部未受门**。这条前提此前没有门守着
——哪天有人给一枚受门能力新增直呼点、或在受门能力的 handler 里再直呼 `invoke()` 造嵌套，
"行为中性"就悄悄变成真话的反面。本件即那道闸，**不是历史记录**。

════════════════════════════════════════════════════════════════════════════════
本门「直呼点」判据（口径自定并钉死，下游不得另写一套）
════════════════════════════════════════════════════════════════════════════════
一个直呼点 = 满足全部三条的 `ast.Call` 节点：
  ① `func` 是 `ast.Attribute` 且 `attr == "invoke"`（属性调用，非裸名 `invoke()`）；
  ② 命中层 2 语义二者之一：
       (a) 接收者本身是 `default_invoker()` 工厂调用（`Name` 尾缀 `default_invoker`
           或 `Attribute.attr == "default_invoker"`，覆盖 `default_invoker()` /
           `_default_invoker()` / `capability_protocols.default_invoker()`）；**或**
       (b) 该调用子树里出现关键字 `capability_id=`（把能力 id 交给一个叫 invoke 的东西，
           语义上就是一次能力执行，哪怕接收者被赋给了变量）；
  ③ 该调用的**外层函数名链不含** `orchestrated_command`——层 1→层 2 的汇合缝本身
     （`capability_protocols.py` 内 `orchestrated_command._step` 传**变量** cid）就是
     "走 pipeline"，**绝不算旁路直呼**（对齐相邻门 `test_orchestration_callsite_single`
     跳 `_SHELL_REL` 的先例，但本门按函数名链排除，更严：壳文件内新冒出的第二旁路照样红）。
  同名业务 `invoke`（如 `control_plane/actions.py` 局部 `async def invoke()` 以裸名 `invoke()`
  调用、无属性、无 `capability_id=`）天然不命中②。

cid 解析（诚实优先，绝不把不可证的当 0）：
  - 子树里恰有一枚 `capability_id=` 字面量字符串 → 取该字面量；
  - 出现任何非字面量的 `capability_id=`（变量/下标/表达式），或命中②a 却根本找不到
    `capability_id=` → 标 `_UNRESOLVED` 并**计入违规面**（"看不见"不等于"没受门"）。

判据自证（防"存在性糊过活性判据"式假门 / 防把分母掏空造假绿）：
  - 真树地板锁前先断 `gate_feature_bindings()` 非空（否则"交集为空"是空分母的假绿）；
  - 注毒：合成树把某直呼点 cid 换成一枚**真实受门** id → 地板锁必红；
  - 注毒：从名册删一条 → 名册锁必红。

全离线：仅 AST 扫源码，`gate_feature_bindings()` 只读；零网络、零消息发送、零生产文件写。
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from typing import NamedTuple

# 真身/中央件**延迟到用例内 import**：本门的纯扫描/注毒/名册锁不依赖中央模块能否
# 成功 import（以免被在飞波次的 collection-time 崩连坐）；只有地板锁需要 `gate_feature_bindings()`。
_PKG_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime"

#: 变量/动态传入、无法解析出字面量 id 的直呼点的哨兵值（**计入违规面**，不当 0）。
_UNRESOLVED = "<unresolved>"


class Site(NamedTuple):
    """一处直呼 `invoke()` 调用点：相对包根路径 + 行号 + 解析到的 capability_id。"""

    rel: str
    line: int
    cid: str  # 字面量 id，或 `_UNRESOLVED`

    @property
    def location(self) -> str:
        return f"{self.rel}:{self.line}"


# ---------------------------------------------------------------------------
# 直呼点扫描器（可喂真树或合成树，保证门"真会红"而非自证快照）
# ---------------------------------------------------------------------------
def _receiver_is_invoker_factory(func: ast.Attribute) -> bool:
    """`default_invoker().invoke(...)` 的接收者 = 一个 `*default_invoker()` 工厂调用。"""
    value = func.value
    if not isinstance(value, ast.Call):
        return False
    callee = value.func
    if isinstance(callee, ast.Name):
        return callee.id.endswith("default_invoker")
    if isinstance(callee, ast.Attribute):
        return callee.attr == "default_invoker"
    return False


def _capability_id_kwarg(node: ast.Call) -> ast.expr | None:
    """该 invoke 调用子树里的 `capability_id=` 值表达式（取首个出现者，覆盖内联 CapabilityRequest）。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.keyword) and sub.arg == "capability_id":
            return sub.value
    return None


def _enclosing_function_names(node: ast.Call, parents: dict[ast.AST, ast.AST]) -> set[str]:
    names: set[str] = set()
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(current.name)
        current = parents.get(current)
    return names


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def scan_direct_callsites(index: dict[str, str]) -> list[Site]:
    """index = {相对包根路径: 源码}。返回全部直呼点 Site（判定见文件头口径）。"""
    sites: list[Site] = []
    for rel, src in index.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        parents = _parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "invoke":  # ① 属性名必须是 invoke
                continue
            cid_expr = _capability_id_kwarg(node)
            hit_receiver = _receiver_is_invoker_factory(node.func)
            if not (hit_receiver or cid_expr is not None):  # ② 层 2 语义
                continue
            if "orchestrated_command" in _enclosing_function_names(node, parents):
                continue  # ③ 层 1→2 汇合缝不是旁路
            if cid_expr is None or not (
                isinstance(cid_expr, ast.Constant) and isinstance(cid_expr.value, str)
            ):
                cid = _UNRESOLVED  # 变量传入 / 无 id：诚实计入违规面
            else:
                cid = cid_expr.value
            sites.append(Site(rel=rel, line=node.lineno, cid=cid))
    return sorted(sites, key=lambda s: (s.rel, s.line, s.cid))


# ---------------------------------------------------------------------------
# 判据器（地板锁 / 名册锁）——纯函数，真树与合成树共用同一把尺
# ---------------------------------------------------------------------------
def check_floor_lock(sites: list[Site], gate_map: dict[str, str]) -> list[str]:
    """直呼点 ∩ 受门表必须为空；`_UNRESOLVED` 计入违规面。返回违规清单（空＝过）。"""
    v: list[str] = []
    for site in sites:
        if site.cid == _UNRESOLVED:
            v.append(
                f"[地板] {site.location} 直呼 invoke() 的 capability_id 无法静态解析"
                "（变量/动态传入）＝不可证明未受门，计入违规面"
            )
        elif site.cid in gate_map:
            v.append(
                f"[地板] {site.location} 直呼受门能力 cid={site.cid!r}"
                f"（受 feature={gate_map[site.cid]!r} 管）——绕过 pipeline 直呼会把"
                "『行为中性』前提变成反面：这条能力今天受层 2 kill-switch 执法"
            )
    return v


def check_roster_lock(sites: list[Site], known: list[tuple[str, str]]) -> list[str]:
    """直呼点 {(rel, cid)} 多重集必须与名册精确等值：少了红、多了也红（含同点重复）。"""
    scanned = Counter((s.rel, s.cid) for s in sites)
    expected = Counter(known)
    v: list[str] = []
    for key, cnt in scanned.items():
        exp = expected.get(key, 0)
        if cnt > exp:
            v.append(
                f"[名册] 出现未披露/新增的直呼点 {key[0]} cid={key[1]!r}"
                f"（实 {cnt} 处 / 册 {exp} 处）：新增第二旁路须先评审入册或改走 pipeline"
            )
    for key, exp in expected.items():
        got = scanned.get(key, 0)
        if got < exp:
            v.append(
                f"[名册] 已披露的直呼点消失 {key[0]} cid={key[1]!r}"
                f"（实 {got} 处 / 册 {exp} 处）：悄悄删披露＝名册失去活性"
            )
    return v


# ---------------------------------------------------------------------------
# 真树装载（廉价预筛 `invoke(` 才交 AST，避免解析全树）
# ---------------------------------------------------------------------------
def _load_real_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "invoke(" in text:
            index[path.relative_to(_PKG_ROOT).as_posix()] = text
    return index


# ---------------------------------------------------------------------------
# 名册（现算真值，2026-09-24 S48；2026-09-25 S220 补登两枚：S91 变换腿 + S221 绘画门面）——逐条 `(相对包根路径, cid)`。
# 行号只随扫描出现在违规消息里，不进等值键：本仓多波并发改动频繁、行号顶漂属常态
# （AGENTS 多处「坐标顶漂」前车之鉴），拿行号锁会把"门"退化成"天天误红的维护陷阱"，
# 而安全属性（受门 ∩ 直呼 == ∅、unresolved 计违规、旁路必披露）不依赖行号即可成立。
# ---------------------------------------------------------------------------
KNOWN_DIRECT_CALLSITES: list[tuple[str, str]] = [
    ("__init__.py", "search.web"),
    ("domains/creation/tts/routes.py", "creation.tts.synthesize"),
    ("domains/media/capabilities/image_search.py", "media.vision.anime_ip"),
    # S-SEAM-DEBT-b 2026-09-27 跟随 S270 归位：media.tts.autodub 的全树唯一字面 invoke 已由
    # voice_enricher 迁至唯一组合口 result_transform.dub_via_central（wave_media 台账 :98-100
    # 同源注记；真树现算=domains/media/tts/result_transform.py:217），本条改指活体落点。
    # **非新增第二旁路**：直呼点总数不变、cid 不变，只是住所跟随归位——该席（S270）漏刷本名册，
    # 补账为纯 HEAD 即红的跟随义务（SEAT-SEAM-FOLLOW-c §5 遗留欠账②）。
    ("domains/media/tts/result_transform.py", "media.tts.autodub"),
    # S220 补登披露（2026-09-25 现算；直呼点=voice_enricher.py:204-206 字面 cid）。**非新增第二旁路**：
    # 该"呈现结果→带音频呈现结果"变换此前是 hook 内联的第二真身，S91 按 mandate「TTS 也不例外」
    # 退役内联、改直呼中央第三形 ⇒ 本门要披露的"绕过 pipeline 的直呼 invoke()"新多一处，账须跟随。
    # 真身册同步在场（现算于 capability_protocols.py）：descriptor :1990 + 执行体注册 :2713，
    # 薄委派 domains/media/tts/result_transform.py::handle（S36 落件、S91 通电）。
    # 未受 feature 门 ⇒ 地板锁零影响（`test_gate_scoped_direct_callsite_intersection_is_empty`
    # 现算绿为证）；SEAT-MAIN 2026-09-24T01:42Z
    # 记 S91 三面跟随只覆盖 ledger/FACETS/三地板，漏了这本名册 ⇒ 本条是补账，非新债。
    ("domains/media/voice_enricher.py", "media.tts.autodub_transform"),
    # S220 补登披露（2026-09-25T16:2xZ 现算，**并发窗读数**：直呼点所在
    # `domains/creation/image/routes.py` 由 S221 席于 16:26Z 前后落盘，落账时刻该件仍在飞）。
    # 与上方 tts routes 线**严格同构**（该文件头自述）：HTTP 门面唯一入口 = 直呼
    # `default_invoker().invoke(capability_id="creation.image.generate")`，执行体已注册
    # （capability_protocols.py:2720 一带，P5「绘画协议预留收口」）；本门要披露的正是这类
    # "绕 pipeline 的直呼 invoke()"门面点。未受 feature 门 ⇒ 地板锁现算零违规。
    # ⚠ 若 S221 后续把该件改名/合并/改道，本条会以「已披露直呼点消失」方向红——那是本门
    # 的既设计随机制，届时由该席跟随刷新，不预填、不豁免。
    ("domains/creation/image/routes.py", "creation.image.generate"),
]


# ===========================================================================
# ① 判据自证（合成树）：口径四条腿真的会分
# ===========================================================================
_SRC_SEAM = '''
def orchestrated_command(capability_id, capability, config):
    def _step(message, decision):
        return default_invoker().invoke(
            CapabilityRequest(capability_id=capability_id, payload={"message": message})
        )
    return _step
'''

_SRC_LITERAL_BYPASS = '''
def handle():
    return default_invoker().invoke(
        CapabilityRequest(capability_id="some.bypass.cid", payload={})
    )
'''

_SRC_UNDERSCORE_FACTORY = '''
def handle(inv_cfg):
    from .runtime.capability_protocols import default_invoker as _default_invoker
    return _default_invoker().invoke(
        _Request(capability_id="underscore.factory.cid")
    )
'''

_SRC_VARIABLE_RECEIVER_WITH_KW = '''
def handle():
    inv = capability_protocols.default_invoker()
    return inv.invoke(CapabilityRequest(capability_id="var.receiver.cid"))
'''

_SRC_VARIABLE_CID = '''
def handle(which):
    return default_invoker().invoke(CapabilityRequest(capability_id=which))
'''

_SRC_NO_KWARG_BUT_FACTORY = '''
def handle():
    return default_invoker().invoke(prebuilt_request)
'''

_SRC_BUSINESS_INVOKE = '''
async def _f():
    async def invoke():
        return 1
    return await invoke()
'''


def test_seam_is_never_a_bypass() -> None:
    """层 1→2 汇合缝（orchestrated_command 内传变量 cid）必须被排除，绝不进直呼面。"""
    sites = scan_direct_callsites({"runtime/capability_protocols.py": _SRC_SEAM})
    assert sites == [], f"pipeline 汇合缝被误判为旁路：{sites}"


def test_literal_bypass_is_caught() -> None:
    sites = scan_direct_callsites({"m.py": _SRC_LITERAL_BYPASS})
    assert [s.cid for s in sites] == ["some.bypass.cid"], sites


def test_underscore_factory_is_caught() -> None:
    """`_default_invoker()`（根里 as 改名的写法）照样命中②a。"""
    sites = scan_direct_callsites({"m.py": _SRC_UNDERSCORE_FACTORY})
    assert [s.cid for s in sites] == ["underscore.factory.cid"], sites


def test_variable_receiver_still_caught_via_kwarg() -> None:
    """接收者赋给变量（`inv.invoke(...)`）但带 capability_id= ⇒ 经②b 命中（防旁路藏在变量后）。"""
    sites = scan_direct_callsites({"m.py": _SRC_VARIABLE_RECEIVER_WITH_KW})
    assert [s.cid for s in sites] == ["var.receiver.cid"], sites


def test_variable_cid_is_unresolved_and_counted() -> None:
    """capability_id 传变量 ⇒ 诚实标 _UNRESOLVED，不得当 0（不可证明未受门＝计入违规面）。"""
    sites = scan_direct_callsites({"m.py": _SRC_VARIABLE_CID})
    assert [s.cid for s in sites] == [_UNRESOLVED], sites


def test_factory_invoke_without_capability_id_is_unresolved() -> None:
    """default_invoker().invoke(成品 request) 看不到 id ⇒ _UNRESOLVED（宁计违规不放过）。"""
    sites = scan_direct_callsites({"m.py": _SRC_NO_KWARG_BUT_FACTORY})
    assert [s.cid for s in sites] == [_UNRESOLVED], sites


def test_business_invoke_not_matched() -> None:
    """同名业务 `invoke()`（裸名、无属性、无 capability_id=）天然不命中。"""
    sites = scan_direct_callsites({"m.py": _SRC_BUSINESS_INVOKE})
    assert sites == [], sites


# ===========================================================================
# ② 真树活性锁：本门存在的意义——今天过、未来有人乱来当场红
# ===========================================================================
def test_real_tree_has_no_unresolved_direct_callsites() -> None:
    """真树里今天不得有无法解析 cid 的直呼点（有＝违规，须改字面量或走 pipeline）。"""
    unresolved = [s for s in scan_direct_callsites(_load_real_index()) if s.cid == _UNRESOLVED]
    assert unresolved == [], f"直呼点存在不可证明未受门的动态 cid：{[s.location for s in unresolved]}"


def test_gate_scoped_direct_callsite_intersection_is_empty() -> None:
    """地板锁：`{直呼 cid} ∩ set(gate_feature_bindings()) == ∅`（S43 行为中性前提的常驻闸）。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        gate_feature_bindings,
    )

    gate_map = gate_feature_bindings()
    # 反空分母：交集为空的"绿"只有在受门表非空时才有意义。
    assert gate_map, "gate_feature_bindings() 为空＝地板锁无执法对象，本锁变假绿"
    sites = scan_direct_callsites(_load_real_index())
    assert check_floor_lock(sites, gate_map) == [], check_floor_lock(sites, gate_map)


def test_real_tree_roster_matches_ledger() -> None:
    """名册锁：真树直呼点 (rel,cid) 多重集 == KNOWN_DIRECT_CALLSITES，少了多了都红。"""
    sites = scan_direct_callsites(_load_real_index())
    violations = check_roster_lock(sites, KNOWN_DIRECT_CALLSITES)
    assert violations == [], "\n".join(violations)


# ===========================================================================
# ③ 注毒：证明两把锁真长牙（合成树 / 从真树删一条，均不写生产文件）
# ===========================================================================
def test_poison_gated_cid_trips_floor_lock() -> None:
    """注毒①：某直呼点 cid 换成一枚真实受门 id ⇒ 地板锁红（且不依赖记忆写受门名单）。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        gate_feature_bindings,
    )

    gate_map = gate_feature_bindings()
    victim = "bot.chat"
    assert victim in gate_map, f"{victim} 已不再受门？本毒样本失效，须换一枚真受门 id 或重评本锁"
    src = (
        "def handle(cfg):\n"
        "    return default_invoker().invoke(\n"
        f"        CapabilityRequest(capability_id={victim!r}, payload={{}})\n"
        "    )\n"
    )
    sites = scan_direct_callsites({"domains/poison/capabilities/sneaky.py": src})
    v = check_floor_lock(sites, gate_map)
    assert any(victim in s for s in v), f"直呼受门能力未被地板锁拦下：{v}"


def test_poison_remove_from_ledger_trips_roster_lock() -> None:
    """注毒②（多了红方向）：名册删一条、真树仍在 ⇒ 该直呼点变"未披露新增"，名册锁红。"""
    sites = scan_direct_callsites(_load_real_index())
    assert check_roster_lock(sites, KNOWN_DIRECT_CALLSITES) == [], "基线名册本就与真树不符"
    dropped = KNOWN_DIRECT_CALLSITES[0]
    truncated = KNOWN_DIRECT_CALLSITES[1:]  # 少披露一条（真树照旧）
    v = check_roster_lock(sites, truncated)
    assert any(dropped[1] in s for s in v), f"删披露未被名册锁发现（应报该 cid 未披露新增）：{v}"


def test_poison_deleted_callsite_trips_roster_lock() -> None:
    """注毒②'（少了红方向）：真树里某直呼点被删、名册仍列 ⇒ 名册锁报"消失"，防悄悄摘披露。"""
    sites = scan_direct_callsites(_load_real_index())
    assert check_roster_lock(sites, KNOWN_DIRECT_CALLSITES) == [], "基线名册本就与真树不符"
    dropped = KNOWN_DIRECT_CALLSITES[0]
    survivors = [s for s in sites if (s.rel, s.cid) != dropped]  # 模拟该旁路被改道/删除
    assert len(survivors) < len(sites), "注毒没真删掉一条＝本锁在空跑"
    v = check_roster_lock(survivors, KNOWN_DIRECT_CALLSITES)
    assert any("消失" in s and dropped[1] in s for s in v), f"删除直呼点未被名册锁发现：{v}"


def test_poison_add_second_callsite_trips_roster_lock() -> None:
    """注毒③（多余方向）：真树里同一 (rel,cid) 冒第二处 ⇒ 名册多重集锁红（防行号下藏第二旁路）。"""
    sites = scan_direct_callsites(_load_real_index())
    dup = [*sites, Site(rel="__init__.py", line=1, cid="search.web")]
    v = check_roster_lock(dup, KNOWN_DIRECT_CALLSITES)
    assert any("search.web" in s and "新增" in s for s in v), f"同点重复未被名册锁发现：{v}"
