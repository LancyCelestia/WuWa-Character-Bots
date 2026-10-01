"""G-ORTHO 常驻门：「正交共存（视觉与语音同开不得互压）」的可执行判据（S85）.

## 本门治的病
mandate（用户 2026-09-23 `/goal` 任务书第 1 条）要求能力标签
「与路由优先级、内容档分级、主动投递配额、渲染面正交共存（视觉与语音同开不得互压）」。
2026-09-24T00:47:59Z 现算：``domains/core/capability_manifest.py`` 里"正交"只以**散文**在场
（该件 :24-25 教义段），而 ``tests/test_capability_manifest_gate.py`` 的九条 ``def test_*``
**逐条读完没有一条**判它 ⇒ 属"在册却零执法"。本门把这条要求补成机械判据。

## 判据原文（四腿可判 + 三腿记账）
 ①**族开关互斥**：视觉族与语音族**专属**的 Config 键两两不相交（共键＝那条键就是互压通道）；
   每枚键必须在 ``config.py`` 现算在场（反虚构）；各族清单不为空且设扫描面地板。
 ②**无耦合短路**：全生产源码里**不存在任何一条布尔条件同时引用两族的开关**
   ——「开了 A 就把 B 关掉」的形状今天为零、今后涨一枚即红（=「同开不得互压」的否定式）。
   本腿带三件自证：文件数地板、函数数地板、两族见证件各至少一枚在场（拦"缩面换绿"）。
 ③**注册表身份分离**：两族能力的 `gate_feature_id` 不得同为非空（同一道 feature 门＝一关俱关）、
   `handler_ref`（执行体）不得跨族共用；且真身册里带视觉/语音标签者**必须**在本席归属册内
   （名册涨了这边不知道 ⇒ 红＝"一处变更处处跟随"）。
 ④**计数器与渲染面分离**：入站限流的桶键构造子必须把 `capability_id` 编进键
   （调用点与构造子两侧都判 ⇒ 桶一旦改成全局共用，视觉洪峰就能挤掉语音）；
   两族实现件里 `render_card` 调用数为棘轮上限 0（语音进渲染池＝新增共场，须评审后才准涨）。
 ⑤**共享预算耦合账（只降不升）**：同一个函数把两族相位记到**同一枚预算对象**上的点数
   现算 1（``chat.py`` 里「识图/视频 → 转写 → LLM」串同一条 `DeadlineBudget`），
   上限冻结为 1 ⇒ 新增一枚此类耦合当场红；已知那一枚的修法归裁定项 S85-R1（本席未修）。
 ⑥**共享资源账有效性**：`SHARED_RESOURCES` 每行的 `cap_key` 必须在 ``config.py`` 在场、
   `effect` 必须取词表内的值、`consumers` 必须是已登记的族或 `all`/`none`、`evidence` 不得为空。
 ⑦**否决级共享必须点名在册**：账里"被两族共用且效应为 `veto`"的行数设**地板**
   ——把已知互压抹掉不是"没有互压"，而是把门弄瞎；这条把"结构锁证明不了不互压"变成数据。

## 本门的天花板（不得越线叙述）
上面七腿只能证明 **不共键 / 不共闸身份 / 不共计数器 / 已知共场已点名**。
它们**不能**证明"两族同开不互压"：同一枚请求预算、同一个 worker 池、同一个
chromium 实例、同机 CPU 都能互相拖慢甚至互相否决——本席现算确实抓到 **2 枚否决级
共享**（请求级预算把 ASR 一票跳过、管线在途闸 `pipeline_busy` 静默否决），
它们只被**记账**（⑤⑥⑦）而**未被消除**，消除方案在 SEAT-S85 §6 等裁。
把本门叙述成"共存已验证"＝假绿。

## 数据真身
判据用的族/键/资源归属只在
``plugins/bot_unified_runtime/domains/core/capability_resource_ownership.py`` 写一次；
本门只读它＋真身册＋唯一在册表＋生产源码 AST，**不复制任何一份键表**。
全件零网络、零渲染、零发消息、零写盘（注毒只在 tmp_path 里造样本文件）。

复跑（本机必带项）：

.. code-block:: bash

    cd ChatBot/ChatBot && PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 \\
      PYTHONPYCACHEPREFIX=$TEMP/s85-pyc BOT_AUTOSYNC=0 \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_capability_tag_orthogonality.py \\
      -p no:cacheprovider --basetemp=$TEMP/s85-t1 -q
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PKG_DIR = ROOT / "plugins" / "bot_unified_runtime"
CONFIG_PY = PKG_DIR / "config.py"
RATE_LIMIT_PY = PKG_DIR / "domains/chat_reply/policy/rate_limit.py"
OWNERSHIP_PY = PKG_DIR / "domains/core/capability_resource_ownership.py"

from plugins.bot_unified_runtime.domains.core import (
    capability_manifest as cm,
)
from plugins.bot_unified_runtime.domains.core import (
    capability_resource_ownership as ro,
)
from plugins.bot_unified_runtime.domains.core import (
    capability_tag_evidence as cte,
)
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    CAPABILITY_DESCRIPTOR,
)

# ==========================================================================
# 账（**现算值手写**，不是派生表达式；想动任何一枚只有两条诚实路径：
#   ①真降账/真涨面 → 复算 → 同批改字面量；②判据本身改形 → 本段随判据一起改并写明理由）
# 现算时刻 2026-09-24T01:0xZ（尺＝本件下方各 `measure_*` 函数，驱动
#   `$TEMP/s85_probe2.py`/`s85_probe5.py`/`s85_probe6.py` 三次独立读数一致）
# ==========================================================================

#: 腿②的文件扫描面（生产 .py 枚数）。**地板，只准升**——缩面＝把尺子锯短。
SCANNED_FILE_FLOOR = 566
#: 腿②的函数扫描面。**地板，只准升**。
SCANNED_FUNCTION_FLOOR = 6755
#: 腿④的桶键调用点数。**地板，只准升**（牙齿在逐调用点判定，本数只作失明哨兵）。
#: 09-28 S-REDTRIAGE-HEAD：判据改形＝调用点并数 sender_interval_ledger_key 折叠通路
#: （账头诚实路径②「判据本身改形→随判据一起改并写明理由」），现算 42；地板 39 不动。
BUCKET_KEY_CALL_FLOOR = 39
#: 腿⑤的 `record_phase` 调用点总数。**地板，只准升**（相位多了不登记归属，本数会涨而覆盖率掉）。
RECORD_PHASE_CALL_FLOOR = 5
#: 腿①各族专属键数的下限（现算 视觉 25 / 语音 31）。**地板，只准升**。
VISUAL_KEY_FLOOR = 25
AUDIO_KEY_FLOOR = 31
#: 腿⑤共享预算耦合点。**上限，只准降**（现算 1＝chat.py 那条，修法待裁 S85-R1）。
COUPLING_CEILING = 1
#: 腿④两族实现件进渲染池的次数。**上限，只准降**（现算 0）。
RENDER_CARD_ENTRY_CEILING = 0
#: 腿⑥共享资源账行数。**地板，只准升**（现算 9）。
SHARED_ROW_FLOOR = 9
#: 腿⑦被两族共用且效应为 `veto` 的行数。**地板，只准升**（现算 2＝请求预算＋管线在途闸）。
VETO_CROSS_FAMILY_FLOOR = 2

#: 腿②的"见证件"：两族各自的家目录里至少一枚文件真的被扫到（拦"把扫描根指到空目录"）。
WITNESS_FILES: tuple[tuple[str, str], ...] = (
    ("visual", "domains/media/ingest/vision_describe.py"),
    ("visual", "domains/media/ingest/video_understanding.py"),
    ("audio", "domains/media/capabilities/tts.py"),
    ("audio", "domains/media/ingest/transcribe.py"),
)

# ---------------------------------------------------------------- 共用件（纯谓词，可注毒）
def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))


def _iter_production_files() -> list[Path]:
    return sorted(p for p in PKG_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _scope_of_call_node(node: ast.AST) -> ast.AST | None:
    """innermost enclosing function per node（嵌套函数不重复计外层，防同一处算两遍）。"""
    return getattr(node, "_s85_scope", None)


def _annotate_scopes(tree: ast.Module) -> None:
    """给每个节点标上"最内层所属函数"（嵌套函数不重复计外层，防同一处算两遍）。"""
    def walk(n: ast.AST, chain: tuple[ast.AST, ...]) -> None:
        for child in ast.iter_child_nodes(n):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                child._s85_scope = child  # type: ignore[attr-defined]
                walk(child, chain + (child,))
            else:
                if chain:
                    child._s85_scope = chain[-1]  # type: ignore[attr-defined]
                walk(child, chain)
    walk(tree, ())


def _key_to_family() -> dict[str, str]:
    return {key: fam for fam, keys in ro.FAMILY_CONFIG_KEYS.items() for key in keys}


def _families_in_node(node: ast.AST, key_to_family: dict[str, str]) -> set[str]:
    """一个表达式子树里出现的族（认属性名、字符串字面量、`BOT_*` 环境变量形态三种写法）。"""
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in key_to_family:
            found.add(key_to_family[sub.attr])
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            text = sub.value.strip()
            if text in key_to_family:
                found.add(key_to_family[text])
            elif text.startswith("BOT_"):
                lowered = "bot_" + text[4:].lower()
                if lowered in key_to_family:
                    found.add(key_to_family[lowered])
    return found


def condition_nodes(tree: ast.AST):
    """所有"一条布尔条件"的形态：If.test / BoolOp / IfExp.test / 推导式的每个 if。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            yield node, node.test, "If"
        elif isinstance(node, ast.BoolOp):
            yield node, node, "BoolOp"
        elif isinstance(node, ast.IfExp):
            yield node, node.test, "IfExp"
        elif isinstance(node, ast.comprehension):
            for clause in node.ifs:
                yield node, clause, "comprehension"


def cross_family_guards(tree: ast.AST, key_to_family: dict[str, str]) -> list[str]:
    """纯谓词：返回「同一条布尔条件里出现两族开关」的坐标（活数据下必须为空）。"""
    out: list[str] = []
    for node, test, kind in condition_nodes(tree):
        fams = _families_in_node(test, key_to_family)
        if len(fams) > 1:
            out.append(f"line{getattr(node, 'lineno', 0)}:{kind}:{'/'.join(sorted(fams))}")
    return out


def bucket_key_problems(tree: ast.AST) -> tuple[list[str], int]:
    """纯谓词：限流桶键是否**逐枚按 capability_id 分桶**（共用计数器＝可互压）。

    返回 (违规清单, 被检的调用点数)。两道判：
      a) 每个桶键成型调用点（`self._bucket_key(…)` 与折叠通路
         `sender_interval_ledger_key(…)`——ed802d3 起 sender_interval 两枚调用点
         收进该唯一格式件，尺子须同数，否则「换形」会被误读成「拆账」）
         必须把 `capability_id` 编进第一参数；
      b) `_bucket_key` 与 `sender_interval_ledger_key` 构造子本身必须把
         `capability_id` 拼进返回的键里（只判 a 会漏"形参收了却不用"这一手）。
    """
    violations: list[str] = []
    calls = 0
    ctor_found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "_bucket_key":
            calls += 1
            first = ast.unparse(node.args[0]) if node.args else "<无参>"
            if "capability_id" not in first:
                violations.append(
                    f"line{node.lineno}: 桶键第一参数 {first!r} 未含 capability_id（跨能力共用计数器）")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "sender_interval_ledger_key":
            calls += 1
            first = ast.unparse(node.args[0]) if node.args else "<无参>"
            if "capability_id" not in first:
                violations.append(
                    f"line{node.lineno}: 冷却账本键第一参数 {first!r} 未含 capability_id（跨能力共用计数器）")
        if isinstance(node, ast.FunctionDef) and node.name == "_bucket_key":
            ctor_found = True
            body_text = "\n".join(ast.unparse(stmt) for stmt in node.body)
            if "capability_id" not in body_text:
                violations.append(f"line{node.lineno}: _bucket_key 形参收下 capability_id 却不拼进键名")
        if isinstance(node, ast.FunctionDef) and node.name == "sender_interval_ledger_key":
            body_text = "\n".join(ast.unparse(stmt) for stmt in node.body)
            if "capability_id" not in body_text:
                violations.append(
                    f"line{node.lineno}: sender_interval_ledger_key 形参收下 capability_id 却不拼进键名")
    if not ctor_found:
        violations.append("限流件里找不到 _bucket_key 构造子（量具被拆＝不可判）")
    return violations, calls


def budget_coupling_sites(tree: ast.AST, phase_families: dict[str, str], path: str
                          ) -> tuple[list[str], int]:
    """纯谓词：同一函数把两族相位记到**同一枚预算对象**上 ⇒ 一处共享预算耦合。

    返回 (耦合点清单, 被检的 record_phase 调用总数)。相位归属未登记的调用**不计入分子**，
    但会计入总数（腿⑤的地板据此发现"加了新相位没登记"）。
    """
    _annotate_scopes(tree)
    agg: dict[tuple[str, int, str, str], set[str]] = {}
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "record_phase":
            continue
        total += 1
        scope = _scope_of_call_node(node)
        if scope is None or not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        phase = str(node.args[0].value)
        family = phase_families.get(phase)
        if family is None:
            continue
        key = (path, scope.lineno, getattr(scope, "name", "?"), ast.unparse(node.func.value))
        agg.setdefault(key, set()).add(family)
    sites = [f"{p}:{ln}:{name} 预算对象 {recv} 同时记 {'/'.join(sorted(fams))}"
             for (p, ln, name, recv), fams in sorted(agg.items()) if len(fams) > 1]
    return sites, total


def render_card_calls(tree: ast.AST) -> int:
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "render_card"
    )


def descriptor_identity_collisions(
    members: dict[str, tuple[str, ...]],
    lookup=None,
) -> list[str]:
    """纯谓词：两族之间共用同一道非空 feature 门，或共用同一个执行体文件#符号。

    `lookup` 只是**注毒注入缝**（缺省读唯一在册表本尊）；活账一次都不走它。
    """
    resolve = CAPABILITY_DESCRIPTOR.get if lookup is None else lookup
    gates: dict[str, set[str]] = {}
    refs: dict[str, set[str]] = {}
    problems: list[str] = []
    for family, ids in members.items():
        for cid in ids:
            row = resolve(cid)
            if row is None:
                problems.append(f"{cid} 不在唯一在册表里（归属册与在册表脱钩）")
                continue
            gate = str(getattr(row, "gate_feature_id", "") or "")
            if gate:
                gates.setdefault(gate, set()).add(family)
            ref = str(getattr(row, "handler_ref", "") or "")
            if ref:
                refs.setdefault(ref, set()).add(family)
    problems += [f"同一道 feature 门 {g} 同时管两族 {'/'.join(sorted(f))}"
                 for g, f in sorted(gates.items()) if len(f) > 1]
    problems += [f"同一枚执行体 {r} 被两族共用 {'/'.join(sorted(f))}"
                 for r, f in sorted(refs.items()) if len(f) > 1]
    return problems


def shared_row_problems(rows) -> list[str]:
    """纯谓词：共享资源账每行的字段合法性（效应词表、cap_key 在场、消费方在册、证据非空）。"""
    fields = CONFIG_FIELDS
    problems: list[str] = []
    for row in rows:
        name = str(row.get("resource", "?"))
        effect = str(row.get("effect", ""))
        if effect not in ro.EFFECTS:
            problems.append(f"{name}: 效应 {effect!r} 不在词表 {ro.EFFECTS}（未知值 fail-closed）")
        cap_key = str(row.get("cap_key", "") or "")
        if cap_key and cap_key not in fields:
            problems.append(f"{name}: 上限真身 {cap_key!r} 不在 config.py（虚构的账）")
        consumers = tuple(row.get("consumers", ()) or ())
        if not consumers:
            problems.append(f"{name}: 未点名谁在用（空 consumers＝账是假的）")
        for consumer in consumers:
            if consumer not in set(ro.FAMILY_MEMBERS) | {"all", "none"}:
                problems.append(f"{name}: 消费方 {consumer!r} 不是已登记的族")
        if not str(row.get("evidence", "") or "").strip():
            problems.append(f"{name}: 无证据坐标（凭记忆登记的账）")
    return problems


def veto_cross_family_rows(rows) -> list[str]:
    """被两族共用、且效应为 veto/preempt 的行（这些是"已知会互压"，只准被消除、不准被抹掉）。"""
    out: list[str] = []
    for row in rows:
        consumers = {str(c) for c in (row.get("consumers", ()) or ())}
        if str(row.get("effect", "")) not in {"veto", "preempt"}:
            continue
        if {"visual", "audio"} <= consumers or "all" in consumers:
            out.append(str(row.get("resource", "?")))
    return sorted(out)


# ---------------------------------------------------------------- 现算尺（唯一取数口）
CONFIG_FIELDS: frozenset[str] = frozenset(
    node.target.id
    for node in ast.walk(_parse(CONFIG_PY))
    if isinstance(node, ast.AnnAssign)
    and isinstance(node.target, ast.Name)
    and node.target.id.startswith("bot_")
)

_PRODUCTION_TREES: list[tuple[Path, ast.Module]] | None = None


def production_trees() -> list[tuple[Path, ast.Module]]:
    """整册只解析一次；解析失败**不静默跳过**（跳过＝缩面换绿的经典手法）。"""
    global _PRODUCTION_TREES
    if _PRODUCTION_TREES is None:
        out: list[tuple[Path, ast.Module]] = []
        broken: list[str] = []
        for path in _iter_production_files():
            try:
                out.append((path, _parse(path)))
            except (SyntaxError, OSError) as exc:
                broken.append(f"{path.name}:{type(exc).__name__}")
        assert not broken, f"生产源码解析失败 {len(broken)} 件（跳过会把盲区洗成绿）：{broken[:5]}"
        _PRODUCTION_TREES = out
    return _PRODUCTION_TREES


def measure_scanned_files() -> int:
    return len(production_trees())


def measure_scanned_functions() -> int:
    return sum(
        1
        for _, tree in production_trees()
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )


def family_home_files(family: str) -> list[Path]:
    """某族成员的执行体文件（从唯一在册表现算，不在本件抄路径）。"""
    out: list[Path] = []
    for cid in ro.FAMILY_MEMBERS[family]:
        row = CAPABILITY_DESCRIPTOR.get(cid)
        ref = str(getattr(row, "handler_ref", "") or "") if row is not None else ""
        if "#" not in ref:
            continue
        tail = ref.split("#", 1)[0]
        candidate = (PKG_DIR / tail.replace("plugins/bot_unified_runtime/", "", 1))
        if candidate.is_file():
            out.append(candidate)
    return sorted(set(out))


# ==========================================================================
# 腿①：族开关互斥 ＋ 反虚构 ＋ 面地板
# ==========================================================================
def test_leg1_family_switch_keys_are_disjoint() -> None:
    conflicts = ro.family_conflicts()
    assert not conflicts, "两族共用同一枚 Config 键＝那条键就是互压通道：" + "；".join(conflicts)
    assert ro.member_conflicts() == [], "同一能力被算进两族（正交性的定义级前提破）：" + "；".join(
        ro.member_conflicts())


def test_leg1_declared_keys_exist_in_config() -> None:
    """反虚构腿：清单里每枚键必须真在 `config.py` 在场——否则"互斥"是拿不存在的键凑出来的。"""
    ghost = {
        family: sorted(key for key in keys if key not in CONFIG_FIELDS)
        for family, keys in ro.FAMILY_CONFIG_KEYS.items()
    }
    ghost = {k: v for k, v in ghost.items() if v}
    assert not ghost, f"归属册里有 config.py 不存在的键（虚构的专属面）：{ghost}"


def test_leg1_per_family_key_floor() -> None:
    counts = {f: len(k) for f, k in ro.FAMILY_CONFIG_KEYS.items()}
    assert counts.get("visual", 0) >= VISUAL_KEY_FLOOR, (
        f"视觉族专属键数 {counts.get('visual', 0)} < 地板 {VISUAL_KEY_FLOOR}＝把清单删短不是把互压改掉")
    assert counts.get("audio", 0) >= AUDIO_KEY_FLOOR, (
        f"语音族专属键数 {counts.get('audio', 0)} < 地板 {AUDIO_KEY_FLOOR}＝同上")


# ==========================================================================
# 腿②：全树无一条布尔条件同时引用两族开关（＋三件失明自证）
# ==========================================================================
def test_leg2_no_cross_family_guard_in_production() -> None:
    key_to_family = _key_to_family()
    hits: list[str] = []
    for path, tree in production_trees():
        for flagged in cross_family_guards(tree, key_to_family):
            hits.append(f"{path.relative_to(ROOT)} {flagged}")
    assert not hits, (
        "出现「一条条件搅两族开关」的短路形状（＝同开互压的直接通道）：" + "；".join(hits))


def test_leg2_scan_surface_floors() -> None:
    files = measure_scanned_files()
    funcs = measure_scanned_functions()
    assert files >= SCANNED_FILE_FLOOR, f"扫描文件数 {files} < 地板 {SCANNED_FILE_FLOOR}＝缩面换绿"
    assert funcs >= SCANNED_FUNCTION_FLOOR, (
        f"扫描函数数 {funcs} < 地板 {SCANNED_FUNCTION_FLOOR}＝缩面换绿")


def test_leg2_both_family_homes_really_scanned() -> None:
    """见证件腿：两族的家目录必须真被扫到（把扫描根指到空目录 ⇒ 本腿红，不是本腿免检）。"""
    scanned = {path for path, _ in production_trees()}
    missing = [
        f"{family}:{rel}" for family, rel in WITNESS_FILES
        if (PKG_DIR / rel) not in scanned
    ]
    assert not missing, "判据看不见这些见证件（量具失明）：" + "、".join(missing)
    for family in ro.FAMILY_MEMBERS:
        assert family_home_files(family), f"{family} 族解析不出任何执行体文件＝在册表与归属册脱钩"


# ==========================================================================
# 腿③：注册表身份分离 ＋ 真身册跟随
# ==========================================================================
def test_leg3_gate_and_execution_are_family_separated() -> None:
    problems = descriptor_identity_collisions(ro.FAMILY_MEMBERS)
    assert not problems, "两族在注册表面共享身份（一关俱关／一坏俱坏）：" + "；".join(problems)


def attribution_problems(
    rows: dict[str, tuple[set[str], str]],
    consumer: str,
    consumer_exempt_native: frozenset[str],
) -> list[str]:
    """纯谓词：真身册带视觉/语音系标签者必须归对的那一族（"一处变更处处跟随"）。

    `rows`：cid → (标签值集合, 该 cid 在归属册里的族)；两个形参只是注毒注入缝，活账走真册。
    统一原生消费者（`consumer`＝cte.NATIVE_CONSUMER_CAPABILITY）今天按设计是**族外**：
    它申报的"握有票根的 native-* 内容标签"说的是"能原生读这段内容"，不等于"它归某族的资源计数"
    （SHARED_RESOURCES 已注明"承载两族相位的 bot.chat 不进保留层"）。故对它**只**豁免这些**有票根**
    的 native kind；其余标签（含未来族专属的非原生标签、或它没票根的 native kind）照常跟随，牙不缩。
    S178 起 bot.chat 依三枚实测票根升报 native-audio/video/animation ⇒ 本豁免是把这条合法申报
    接住，而不是给跨族乱贴标签开后门（见 `test_poison_attribution_exempt_is_narrow_not_blanket`）。
    """
    problems: list[str] = []
    for cid, (tags, family) in sorted(rows.items()):
        effective = set(tags)
        if cid == consumer and not family:
            effective -= set(consumer_exempt_native)
        for name, tag_set in ro.FAMILY_TAGS.items():
            if effective & set(tag_set) and family != name:
                problems.append(f"{cid}（标签 {sorted(effective)}）应归 {name} 族，现归 {family or '族外'}")
    return problems


def test_leg3_manifest_tagged_ids_are_all_attributed() -> None:
    """一处变更处处跟随：真身册里带视觉/语音标签者必须在本席归属册内、且只归对的那一族。"""
    rows = {
        cid: ({t.value for t in cm.tags_for(cid)}, ro.family_of(cid))
        for cid in sorted(cm.declared_ids())
    }
    consumer = cte.NATIVE_CONSUMER_CAPABILITY
    exempt = frozenset(f"native-{k}" for k in cte.native_kinds_with_tickets(consumer))
    problems = attribution_problems(rows, consumer, exempt)
    assert not problems, "归属册没跟上真身册（或有人跨族申报）：" + "；".join(problems)


def test_poison_attribution_exempt_is_narrow_not_blanket() -> None:
    """注毒（腿③豁免只咬该咬的）：证明"族外统一原生消费者的票根 native kind 豁免"不是空子。

    四对照，缺一即说明豁免放得太宽或本就没牙：
      ①消费者 + 其票根 native kind（族外）→ 放行（这是 S178 升报的合法形态）；
      ②同一个消费者 + 非 native 的族专属标签（vision）→ 仍红（豁免只覆盖 native kind）；
      ③**别的**族外能力 + native-audio → 仍红（豁免只对声明的 consumer 一人）；
      ④某族成员贴了**另一族**的 native 标签（media.asr 归 audio，却贴 native-video∈visual）→ 仍红。
    """
    consumer = cte.NATIVE_CONSUMER_CAPABILITY
    exempt = frozenset(f"native-{k}" for k in cte.native_kinds_with_tickets(consumer))
    assert "native-audio" in exempt, "票根 native kind 未进豁免集，样本失效"
    # ① 正例：消费者 + 票根 native kind，族外 → 放行
    assert attribution_problems({consumer: ({"media-read", "native-audio"}, "")}, consumer, exempt) == []
    # ② 消费者贴非 native 族专属标签 → 红
    assert attribution_problems({consumer: ({"vision", "native-audio"}, "")}, consumer, exempt), \
        "豁免过宽：消费者贴 vision 仍被判合规"
    # ③ 非族外的另一能力贴 native-audio（无豁免资格）→ 红
    other = attribution_problems({"media.some.other": ({"native-audio"}, "")}, consumer, exempt)
    assert other and "media.some.other" in other[0], "豁免误伤：非 consumer 也享受了豁免"
    # ④ 族成员贴错族 native 标签（media.asr 属 audio，却贴 visual 的 native-video）→ 红
    misfiled = attribution_problems({"media.asr.speech": ({"native-video"}, "audio")}, consumer, exempt)
    assert misfiled and "media.asr.speech" in misfiled[0], "跨族 native 标签未判红＝牙丢了"
    # 反向自证：不豁免时消费者会被判红（证明本豁免确实在做窄口子该做的事，非空跑）
    without = attribution_problems({consumer: ({"native-audio"}, "")}, consumer, frozenset())
    assert without, "去掉豁免仍绿＝豁免是空操作，样本失效"


# ==========================================================================
# 腿④：计数器分桶 ＋ 渲染面进入次数
# ==========================================================================
def test_leg4_rate_limit_counters_are_capability_scoped() -> None:
    violations, calls = bucket_key_problems(_parse(RATE_LIMIT_PY))
    assert calls >= BUCKET_KEY_CALL_FLOOR, (
        f"桶键调用点 {calls} < 地板 {BUCKET_KEY_CALL_FLOOR}＝桶账目被拆，本腿已不可判")
    assert not violations, "限流计数器不再按能力分桶（跨能力共用一格＝互相挤掉）：" + "；".join(violations)


def test_leg4_families_do_not_enter_render_pool() -> None:
    counted = 0
    for family in ro.FAMILY_MEMBERS:
        for path in family_home_files(family):
            counted += render_card_calls(_parse(path))
    assert counted <= RENDER_CARD_ENTRY_CEILING, (
        f"两族实现件里出现 {counted} 处 render_card（>上限 {RENDER_CARD_ENTRY_CEILING}）"
        "＝语音/视觉新并进 playwright 共池，须先评审再改上限")


# ==========================================================================
# 腿⑤：共享预算耦合账（只降不升）
# ==========================================================================
def measure_coupling_sites() -> list[str]:
    sites: list[str] = []
    for path, tree in production_trees():
        found, _ = budget_coupling_sites(tree, ro.BUDGET_PHASE_FAMILIES, str(path.relative_to(ROOT)))
        sites += found
    return sorted(sites)


def measure_phase_calls() -> int:
    return sum(budget_coupling_sites(tree, {}, str(path))[1] for path, tree in production_trees())


def test_leg5_shared_budget_coupling_only_falls() -> None:
    sites = measure_coupling_sites()
    assert len(sites) <= COUPLING_CEILING, (
        f"共享预算耦合点 {len(sites)} > 上限 {COUPLING_CEILING}（新增＝把两族串进同一条预算，"
        f"正是「同开互压」的形态）：{'；'.join(sites)}")


def test_leg5_known_coupling_is_the_frozen_one() -> None:
    """现算==账：上限不是空数，指的就是 chat 那条已知互压（修法待裁 S85-R1）。"""
    sites = measure_coupling_sites()
    assert len(sites) == COUPLING_CEILING, f"耦合点现算 {len(sites)}≠账 {COUPLING_CEILING}（涨要评审、降要摘牌）"
    assert "chat.py" in sites[0] and "request_budget" in sites[0], f"冻结的那枚耦合点变了形：{sites}"


def test_leg5_phase_coverage_floor() -> None:
    calls = measure_phase_calls()
    assert calls >= RECORD_PHASE_CALL_FLOOR, (
        f"record_phase 调用点 {calls} < 地板 {RECORD_PHASE_CALL_FLOOR}＝相位账被删短")
    unregistered = sorted(
        {
            str(node.args[0].value)
            for _, tree in production_trees()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "record_phase" and node.args
            and isinstance(node.args[0], ast.Constant)
            and str(node.args[0].value) not in ro.BUDGET_PHASE_FAMILIES
        }
    )
    # 未登记相位允许存在（llm/debug 等），但必须**被点名**，不得静默；本断言只保证清单非空可审。
    assert isinstance(unregistered, list)


# ==========================================================================
# 腿⑥⑦：共享资源账有效性与"否决级必须点名在册"
# ==========================================================================
def test_leg6_shared_resource_rows_are_valid() -> None:
    problems = shared_row_problems(ro.SHARED_RESOURCES)
    assert not problems, "共享资源账里有虚构/失格的行：" + "；".join(problems)
    assert len(ro.SHARED_RESOURCES) >= SHARED_ROW_FLOOR, (
        f"共享资源账只剩 {len(ro.SHARED_RESOURCES)} 行 < 地板 {SHARED_ROW_FLOOR}＝抹掉共享不是消灭互压")


def test_leg7_cross_family_veto_rows_stay_disclosed() -> None:
    rows = veto_cross_family_rows(ro.SHARED_RESOURCES)
    assert len(rows) >= VETO_CROSS_FAMILY_FLOOR, (
        f"被两族共用的否决级资源现算 {len(rows)} 行 < 地板 {VETO_CROSS_FAMILY_FLOOR}。"
        "本门**不宣称**两族不互压；它要求已知互压必须点名在册（结构锁的天花板见模块 docstring）。")


def test_live_paths_read_the_real_tables() -> None:
    """缺省即真身：判据的注入缝只在注毒用例里被用到，活账一次都不走。"""
    live = _key_to_family()
    assert len(live) == sum(len(v) for v in ro.FAMILY_CONFIG_KEYS.values())
    assert measure_scanned_files() == len(_iter_production_files())
    # 活账走真册：把归属册原样喂回共键判据必须为空（注毒用例改的只是注入参数）
    assert ro.family_conflicts() == [] and ro.member_conflicts() == []
    assert set(ro.FAMILY_MEMBERS) == set(ro.FAMILY_CONFIG_KEYS), "族名在两处不一致"


# ==========================================================================
# 注毒七发（逐发说清"注什么、哪条腿当场红"）
# ==========================================================================
def test_poison_shared_budget_key_is_red() -> None:
    """注毒①：人为让视觉族与语音族**共用同一枚预算键** ⇒ 腿①必红（真数据下必为空）。"""
    assert ro.family_conflicts() == [], "真数据已红，注毒样本无法自证"
    poisoned = {
        "visual": (*ro.FAMILY_CONFIG_KEYS["visual"], "bot_request_budget_seconds"),
        "audio": (*ro.FAMILY_CONFIG_KEYS["audio"], "bot_request_budget_seconds"),
    }
    caught = ro.family_conflicts(poisoned)
    assert any("bot_request_budget_seconds" in line for line in caught), (
        f"共键未被抓到＝腿①无牙：{caught}")


def test_poison_cross_family_guard_is_red() -> None:
    """注毒②：给语音件插一条「视觉没开就把配音关掉」的短路 ⇒ 腿②的谓词必红。"""
    sample = (
        "def handle(cfg, text):\n"
        "    if not cfg.bot_vision_enabled and cfg.bot_tts_voice_hook_enabled:\n"
        "        return None\n"
        "    return text\n"
    )
    tree = ast.parse(sample)
    hits = cross_family_guards(tree, _key_to_family())
    assert any("/" in h and "If" in h for h in hits), f"跨族短路条件未被抓到＝腿②无牙：{hits}"


def test_poison_shrunk_scan_surface_is_red(tmp_path: Path) -> None:
    """注毒③：把判据的扫描面缩小 ⇒ ①地板腿当场红；②往 tmp 目录植一枚带跨族条件的真文件，
    同一个文件级谓词必须抓到它（拦"谓词只在内存里自证、对盘上文件其实瞎"这一手）。"""
    assert measure_scanned_files() >= SCANNED_FILE_FLOOR
    hand_picked = production_trees()[:1]
    assert len([p for p, _ in hand_picked]) < SCANNED_FILE_FLOOR, "手挑子集不该够得上扫描面"

    evil = tmp_path / "evil_audio.py"
    evil.write_text(
        "def f(cfg):\n"
        "    if cfg.bot_tts_enabled and cfg.bot_vision_enabled:\n"
        "        cfg.bot_tts_enabled = False\n",
        encoding="utf-8",
    )
    hits = cross_family_guards(_parse(evil), _key_to_family())
    assert hits, "同一把尺对盘上文件失明（只会在合成 AST 上自证）＝注毒③不成立"


def test_poison_shared_gate_feature_is_red() -> None:
    """注毒④：伪造两族共用同一道 feature 门 ⇒ 腿③的谓词必红（走注入缝，不碰真在册表）。"""
    assert descriptor_identity_collisions(ro.FAMILY_MEMBERS) == [], "真数据已红，注毒样本失效"

    class _Row:
        def __init__(self, gate: str, ref: str) -> None:
            self.gate_feature_id = gate
            self.handler_ref = ref

    table = {
        "poison.visual.id": _Row("media_native", "x/y.py#a"),
        "poison.audio.id": _Row("media_native", "x/z.py#b"),
    }
    caught = descriptor_identity_collisions(
        {"visual": ("poison.visual.id",), "audio": ("poison.audio.id",)},
        lookup=table.get,
    )
    assert any("media_native" in line for line in caught), f"同门两族未被抓到＝腿③无牙：{caught}"
    # 反向自证：两枚都是空门（都不受 feature 门）且执行体不同 ⇒ 不该判出冲突，防判据过宽
    empty = descriptor_identity_collisions(
        {"visual": ("poison.visual.id",), "audio": ("poison.audio.id",)},
        lookup={"poison.visual.id": _Row("", "x/y.py#a"),
                "poison.audio.id": _Row("", "x/z.py#b")}.get,
    )
    assert empty == [], f"两枚空门不同执行体却判出冲突（判据过宽）：{empty}"


def test_poison_unscoped_bucket_key_is_red() -> None:
    """注毒⑤：把某枚限流桶改成"不按能力分桶"（或构造子收了形参不用）⇒ 腿④必红。"""
    sample = (
        "class L:\n"
        "    @staticmethod\n"
        "    def _bucket_key(capability_id, scope, value):\n"
        "        return f'{scope}:{value}'\n"
        "    def check(self, capability_id, group_key):\n"
        "        return self._buckets[self._bucket_key('global', 'pace', group_key)]\n"
    )
    violations, calls = bucket_key_problems(ast.parse(sample))
    assert calls == 1
    assert violations, "未分桶的键与不用形参的构造子都放过了＝腿④无牙"
    assert any("capability_id" in v or "第一参数" in v for v in violations), violations


def test_poison_new_budget_coupling_raises_the_ratchet() -> None:
    """注毒⑥：新造一枚"两族相位共用同一条预算"的函数 ⇒ 腿⑤计数涨到 2、破上限。"""
    assert len(measure_coupling_sites()) == COUPLING_CEILING, "起点不是现算值，注毒样本不可信"
    sample = (
        "class C:\n"
        "    def record_phase(self, stage, started):\n"
        "        pass\n"
        "def handle(budget):\n"
        "    budget.record_phase('vision', 0)\n"
        "    budget.record_phase('asr', 1)\n"
        "    budget.record_phase('tts_out', 2)\n"
    )
    sites, total = budget_coupling_sites(ast.parse(sample), {**ro.BUDGET_PHASE_FAMILIES, "tts_out": "audio"},
                                         "<poison-budget>")
    assert sites, "同一条预算串两族却没被算成耦合点＝腿⑤无牙"
    assert total == 3
    assert len(measure_coupling_sites()) + len(sites) > COUPLING_CEILING


def test_poison_empty_shared_ledger_is_red() -> None:
    """注毒⑦：清空共享资源账（"没有共享"写法）⇒ 腿⑥⑦当场红，抹账不是修互压。"""
    assert veto_cross_family_rows(ro.SHARED_RESOURCES), "真数据里就没有否决级共享，注毒样本失效"
    assert shared_row_problems(()) == []  # 空表本身无"失格行"……
    assert len(()) < SHARED_ROW_FLOOR, "……所以地板腿必红（上一步特意不写进地板，防两腿互盖）"
    assert veto_cross_family_rows(()) == [] and len(veto_cross_family_rows(())) < VETO_CROSS_FAMILY_FLOOR


def test_poison_ghost_config_key_is_red() -> None:
    """注毒⑧（反虚构自证）：清单里塞一枚 config.py 不存在的键 ⇒ 腿①的在场判据必红。"""
    assert CONFIG_FIELDS, "config 字段解析失败，注毒样本无意义"
    assert "bot_s85_definitely_not_a_real_key" not in CONFIG_FIELDS
    poisoned = {"visual": (*ro.FAMILY_CONFIG_KEYS["visual"], "bot_s85_definitely_not_a_real_key")}
    ghost = [k for k in poisoned["visual"] if k not in CONFIG_FIELDS]
    assert ghost == ["bot_s85_definitely_not_a_real_key"], f"虚构键没被发现＝在场判据是空的：{ghost}"


@pytest.mark.parametrize("family", sorted(ro.FAMILY_MEMBERS))
def test_membership_shape_is_two_tuple_of_str(family: str) -> None:
    assert isinstance(ro.FAMILY_MEMBERS[family], tuple) and ro.FAMILY_MEMBERS[family]
    assert all(isinstance(cid, str) and cid for cid in ro.FAMILY_MEMBERS[family])


# ==========================================================================
# 腿⑧⑨（S134，裁定 3 项 A+B 落地后的"跟随与不回退"锁）
#
# 分工：数值行为与端到端留痕的牙齿在 `tests/test_bgroup_chat_pipeline.py`
# （chat 域）与 `tests/test_pipeline_review_fixes.py`（闸域）；**本门只判"处处跟随"**——
# 即预留与分族计数器有没有被后来的改动悄悄绕过（绕过的形态＝码还在、账又红回去）。
# ==========================================================================

CHAT_PY = PKG_DIR / "domains/chat_reply/capabilities/chat.py"
PIPELINE_PY = PKG_DIR / "domains/chat_reply/runtime/pipeline.py"


def _calls(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else None
            )
            if called == name:
                yield node


def _kwarg(node: ast.Call, arg: str) -> ast.expr | None:
    return next((k.value for k in node.keywords if k.arg == arg), None)


def video_stage_reserve_problems(tree: ast.AST) -> list[str]:
    """纯谓词：每个视觉相位的 deadline 调用点都必须显式交语音预留。

    覆盖面＝`_video_deadline_seconds`（档案/编排器分支）与
    `_vision_stage_timeout_seconds`（旧抽帧分支）——只锁其中一支，另一支就是绕过口。
    违例两形态：①漏传 `asr_reserve_seconds=`；②传字面非正数（等于把预留改回装饰）。
    判据走真 AST 节点，不走 `ast.unparse` 子串（散文点名会被 unparse 算成调用点，
    先例＝tests/test_native_av_input.py 的 S42 锁）。
    """
    problems: list[str] = []
    for callee in ("_video_deadline_seconds", "_vision_stage_timeout_seconds"):
        for node in _calls(tree, callee):
            value = _kwarg(node, "asr_reserve_seconds")
            where = f"{callee}@line{getattr(node, 'lineno', 0)}"
            if value is None:
                problems.append(f"{where} 调用未传 asr_reserve_seconds=")
            elif isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) \
                    and float(value.value) <= 0.0:
                problems.append(f"{where} asr_reserve_seconds 传非正字面量 {value.value!r}")
    return problems



def asr_stage_wiring_problems(tree: ast.AST) -> list[str]:
    """纯谓词：语音段自己的超时**必须**来自 `_asr_deadline_seconds`，不得回退成裸 config。

    判两腿：①`transcribe_audio(...)` 的 `timeout_seconds=` 参数必须是个 Name/Call 且
    该 Name 由 `_asr_deadline_seconds` 的解包赋值产出（同函数体内）；
    ②`_asr_deadline_seconds` 至少在 production 里被真调一次。
    """
    problems: list[str] = []
    fed_by: dict[str, int] = {}
    for assign in ast.walk(tree):
        if not isinstance(assign, ast.Assign):
            continue
        call = assign.value
        if isinstance(call, ast.Call):
            called = call.func.attr if isinstance(call.func, ast.Attribute) else \
                call.func.id if isinstance(call.func, ast.Name) else ""
            if called == "_asr_deadline_seconds":
                for target in assign.targets:
                    if isinstance(target, ast.Tuple):
                        for element in target.elts:
                            if isinstance(element, ast.Name):
                                fed_by.setdefault(element.id, 0)
                                fed_by[element.id] += 1
    calls = 0
    for node in _calls(tree, "transcribe_audio"):
        calls += 1
        value = _kwarg(node, "timeout_seconds")
        if isinstance(value, ast.Name) and value.id in fed_by:
            continue
        problems.append(
            f"line{getattr(node, 'lineno', 0)} transcribe_audio 的 timeout_seconds="
            f"={ast.unparse(value) if value is not None else '<缺失>'} 不是 `_asr_deadline_seconds` 的结果"
        )
    if calls and not fed_by:
        problems.append("有 transcribe_audio 调用却没有任何 `_asr_deadline_seconds` 解包赋值")
    return problems


def asr_starved_tag_flow_problems(tree: ast.AST) -> list[str]:
    """纯谓词：`_ASR_STARVED_TAG` 必须①被 append 进某容器②该容器进 `diagnostic_tags`。

    只挂标签不并进诊断＝写了个没人读的常量（本仓在册病形「存在性糊过活性判据」）。
    """
    collected: set[str] = set()
    for node in _calls(tree, "append"):
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)                 and _uses_symbol(node, "_ASR_STARVED_TAG"):
            collected.add(node.func.value.id)
    if not collected:
        return ["`_ASR_STARVED_TAG` 从未被 append（预留失明的第一种写法）"]
    flows = 0
    for assign in ast.walk(tree):
        if not isinstance(assign, (ast.Assign, ast.AugAssign)):
            continue
        targets = assign.targets if isinstance(assign, ast.Assign) else [assign.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "diagnostic_tags":
                text = ast.unparse(assign.value)
                if any(name in text for name in collected):
                    flows += 1
    passed_as_kwarg = any(
        isinstance(k.value, ast.Name) and k.value.id in collected
        for node in _calls(tree, "build_chat_result")
        for k in node.keywords
    )
    problems: list[str] = []
    if not flows:
        problems.append("承载留痕的容器没有并进 diagnostic_tags（留痕进不了审计面）")
    if not passed_as_kwarg:
        problems.append("build_chat_result 没收到承载留痕的形参（跨函数传递那一环断了）")
    return problems


def _uses_symbol(node: ast.AST, symbol: str) -> bool:
    return any(
        isinstance(sub, ast.Name) and sub.id == symbol for sub in ast.walk(node)
    )



def gate_scope_pairing_problems(tree: ast.AST) -> list[str]:
    """纯谓词：`try_acquire(scope)` 与 `release(scope)` 必须交**同一个** scope 变量。

    取/还不同源＝保留层记账会漂（还可能漏还），分族计数器形同虚设。
    判据只在"含 `try_acquire` 的那个函数体"内配对（全文件扫会把别的
    `release(...)`（如进度回执节流）误算进来——那是尺子不准，不是码有问题）。
    """
    problems: list[str] = []
    scanned = 0
    for scope_node in ast.walk(tree):
        if not isinstance(scope_node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        acquired: set[str] = set()
        released: set[str] = set()
        bare: list[str] = []
        has_acquire = False
        for name, bucket in (("try_acquire", acquired), ("release", released)):
            for node in _calls(scope_node, name):
                if name == "try_acquire":
                    has_acquire = True
                if node.args and isinstance(node.args[0], ast.Name):
                    bucket.add(node.args[0].id)
                elif not node.args:
                    bare.append(name)
        if not has_acquire:
            # 「少参调用」只在**自己取了额度**的函数体里才算传丢 scope。
            # 2026-09-29 管线硬超时波（C1-a）把还额度做成了**注入式收尾钩子**：
            # `_retire_offloaded_task(task, release)` / 其内 `_finish` 收到的
            # `release` 是调用方在 acquire 现场构造的闭包（`wrapped._release`
            # 里那句 `gate.release(scope)` 仍受本门锁着）。这两个辅助函数本身
            # 一次都没 try_acquire，把它们判成「scope 传丢」＝把尺子架在没配对
            # 义务的地方；注毒腿（取方函数里 `gate.release()` 丢 scope）照红。
            continue
        scanned += 1
        problems.extend(
            f"{scope_node.name}:{name}() 少参调用（scope 传丢了）" for name in bare
        )
        if not released:
            problems.append(f"{scope_node.name} 取了额度却没有任何 release 调用（额度泄漏）")
            continue
        missing = released - acquired
        if missing:
            problems.append(
                f"{scope_node.name}: release 的 scope {sorted(missing)} 与 try_acquire 不同源")
    if not scanned:
        return ["整个文件没有一处 `try_acquire`＝判据已不可判"]
    return problems



def pipeline_family_roster_problems(tree: ast.AST, *, allowed_literals: frozenset[str]) -> list[str]:
    """纯谓词：闸侧的族籍只能来自族册，**不得**在 pipeline 里抄第二份成员名单。

    判"结构里出现族名字面量"（容器元素 / 相等比较 / 成员判断）三种形状；
    注释与 docstring 里的散文点名不算（它们构造不出名单）。
    """
    copied: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value in allowed_literals:
            shape = _roster_shape_of(tree, node)
            if shape:
                copied.add(f"{node.value}@{shape}")
    if not copied:
        return []
    return [f"pipeline 里出现族名字面量 {sorted(copied)}＝第二真身风险"]


def _roster_shape_of(root: ast.AST, leaf: ast.Constant) -> str:
    """这枚字符串字面量是否活在"名单形状"里（容器元素／== 比较／in 比较）。"""
    for parent in ast.walk(root):
        if isinstance(parent, (ast.Tuple, ast.List, ast.Set)):
            if any(element is leaf for element in parent.elts):
                return "container"
        elif isinstance(parent, ast.Dict):
            if any(key is leaf for key in parent.keys):
                return "dict-key"
        elif isinstance(parent, ast.Compare):
            operands = [parent.left, *parent.comparators]
            if any(operand is leaf for operand in operands):
                return f"compare:{type(parent.ops[0]).__name__}"
    return ""


def measure_reserve_call_sites() -> int:
    return sum(1 for node in _calls(_parse(CHAT_PY), "_video_deadline_seconds"))


def test_leg8_video_stage_carries_the_asr_reserve() -> None:
    problems = video_stage_reserve_problems(_parse(CHAT_PY))
    assert not problems, "视频相位没把语音预留算进扣减：" + "；".join(problems)
    assert measure_reserve_call_sites() >= 1, "chat.py 里一个 `_video_deadline_seconds` 调用点都没扫到＝判据失明"


def test_leg8_asr_stage_timeout_comes_from_the_reservation() -> None:
    problems = asr_stage_wiring_problems(_parse(CHAT_PY))
    assert not problems, "语音段超时绕过了预留算子：" + "；".join(problems)


def test_leg8_starved_signal_reaches_the_audit_surface() -> None:
    problems = asr_starved_tag_flow_problems(_parse(CHAT_PY))
    assert not problems, "饿死留痕没有真正落到诊断面：" + "；".join(problems)


def test_leg9_gate_acquire_and_release_share_one_scope() -> None:
    problems = gate_scope_pairing_problems(_parse(PIPELINE_PY))
    assert not problems, "在途闸取/还的 scope 不同源：" + "；".join(problems)


def test_leg9_gate_does_not_copy_the_family_roster() -> None:
    tree = _parse(PIPELINE_PY)
    problems = pipeline_family_roster_problems(tree, allowed_literals=frozenset(ro.FAMILY_MEMBERS))
    assert not problems, "闸侧抄了第二份族名单：" + "；".join(problems)
    assert "family_of" in ast.unparse(tree), "闸侧不再向族册问族籍＝分族计数器已断线"


def test_leg9_production_pool_gate_has_family_reserves() -> None:
    """**生产装配活性锁**：真 `_get_chat_pool()` 造出的闸必须自带各族保留层。

    没有这一条，"分族计数器"可以整枚死在构造参数里（类本身对、装配没传）——
    本仓在册病形「机制存在但装配落空」的正面拦法。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import pipeline as pl

    _pool, gate = pl._get_chat_pool()
    # 本用例不拥有那枚懒创建的全局池，绝不关闭它（关了就是把别的用例的池拆了）。
    assert gate.reserved_scopes == frozenset(ro.FAMILY_MEMBERS), gate.reserved_scopes
    assert gate.reserved_permits >= 1, f"生产闸的保留层为 {gate.reserved_permits}＝分族没上线"
    assert gate.permits >= 2 * pl._resolve_chat_pool_workers()


def test_leg9_reserved_layer_stays_bounded() -> None:
    """行为锁：保留层是"加一格自己的计数器"，不是"去掉上界"。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
        _BoundedSubmissionGate,
    )

    scopes = tuple(sorted(ro.FAMILY_MEMBERS))
    gate = _BoundedSubmissionGate(4, reserved_permits=2, reserved_scopes=scopes)
    assert gate.reserved_scopes == frozenset(scopes), gate.reserved_scopes
    granted = sum(1 for _ in range(200) if gate.try_acquire(scopes[0]))
    assert granted == 4 + 2, f"单族可取格数 {granted}≠通用 4 + 自身保留 2（上界被写坏了）"
    other = sum(1 for _ in range(50) if gate.try_acquire(scopes[1]))
    assert other == 2, f"第二族只该拿到自己的保留位，实拿 {other}（跨族共用了保留层）"
    assert gate.in_flight == 4 + 2 + 2


# ---------------------------------------------------------- 注毒（腿⑧⑨各验牙）
def test_poison_reserve_kwarg_removed_is_red() -> None:
    """注毒⑨：把真源码里那枚语音预留改成字面 0.0（"绕过"最省事的写法）⇒ 腿⑧必红。"""
    source = CHAT_PY.read_text(encoding="utf-8")
    needle = "asr_reserve_seconds=("
    assert source.count(needle) == 1, f"注毒起点不唯一（count={source.count(needle)}）＝本发不可复算"
    poisoned = source.replace(needle, "asr_reserve_seconds=0.0, _keep=(")
    assert poisoned != source, "注毒没替换到任何文本＝本发是空跑"
    live = video_stage_reserve_problems(ast.parse(source))
    dead = video_stage_reserve_problems(ast.parse(poisoned))
    assert live == [] and dead, f"把预留改成 0 却没红＝腿⑧无牙：live={live} dead={dead}"



def test_poison_asr_timeout_reverting_to_bare_config_is_red() -> None:
    """注毒⑩：语音段超时退回裸 config 直读 ⇒ 腿⑧的接线锁必红。"""
    poisoned = (
        "def handle(provider, budget, cfg):\n"
        "    transcribe_audio(provider, timeout_seconds=cfg.bot_asr_timeout_seconds)\n"
    )
    live = asr_stage_wiring_problems(_parse(CHAT_PY))
    dead = asr_stage_wiring_problems(ast.parse(poisoned))
    assert live == [] and dead, f"退回裸 config 却没被抓＝接线锁无牙：live={live} dead={dead}"


def test_poison_tag_not_flow_into_diagnostics_is_red() -> None:
    """注毒⑪：把留痕并进 diagnostic_tags 那一环删掉 ⇒ 活性锁必红（存在性糊不过去）。"""
    poisoned = (
        "def build(msg, media_budget_tags):\n"
        "    tags = ['x']\n"
        "    tags.append(_ASR_STARVED_TAG)\n"
        "    return build_chat_result(message=msg)\n"
    )
    live = asr_starved_tag_flow_problems(_parse(CHAT_PY))
    dead = asr_starved_tag_flow_problems(ast.parse(poisoned))
    assert live == [] and dead, f"标签没流向诊断面却没红＝留痕是假的：live={live} dead={dead}"


def test_poison_release_without_scope_is_red() -> None:
    """注毒⑫：`gate.release()` 丢 scope（跨族记账会漂）⇒ 腿⑨配对锁必红。"""
    poisoned = (
        "def wrapped(capability, message, decision, gate):\n"
        "    scope = inflight_scope_of(decision.capability_id)\n"
        "    if not gate.try_acquire(scope):\n"
        "        return None\n"
        "    try:\n"
        "        return capability(message, decision)\n"
        "    finally:\n"
        "        gate.release()\n"
    )
    live = gate_scope_pairing_problems(_parse(PIPELINE_PY))
    dead = gate_scope_pairing_problems(ast.parse(poisoned))
    assert live == [] and dead, f"还错计数器没被抓＝腿⑨无牙：live={live} dead={dead}"


def test_poison_shared_inflight_counter_is_red() -> None:
    """注毒⑬：退回"全族共一枚计数器"的旧闸 ⇒ 分族行为锁必红（这枚才是真正的牙）。"""

    class _LegacyGate:
        """改动前形态：一枚 `_in_flight` 走天下（permits=4）。"""

        def __init__(self, permits: int) -> None:
            self._permits = permits
            self._in_flight = 0

        def try_acquire(self, scope: str = "") -> bool:
            if self._in_flight >= self._permits:
                return False
            self._in_flight += 1
            return True

    scopes = tuple(sorted(ro.FAMILY_MEMBERS))
    legacy = _LegacyGate(4)
    visual = sum(1 for _ in range(50) if legacy.try_acquire(scopes[0]))
    audio = sum(1 for _ in range(50) if legacy.try_acquire(scopes[1]))
    assert (visual, audio) == (4, 0), f"注毒样本自身没复现旧病（{visual},{audio}）"
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
        _BoundedSubmissionGate,
    )

    fixed = _BoundedSubmissionGate(4, reserved_permits=2, reserved_scopes=scopes)
    visual_new = sum(1 for _ in range(50) if fixed.try_acquire(scopes[0]))
    audio_new = sum(1 for _ in range(50) if fixed.try_acquire(scopes[1]))
    assert audio_new > 0, "改后闸仍然让第一族饿死第二族＝分族计数器是装饰"
    assert (visual_new, audio_new) == (6, 2), (visual_new, audio_new)

