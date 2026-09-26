"""动作册反模式门（SAFE-EXEC 规格 §0 不变式① / §2 / §12 G-2 的机器面）。

执法对象是 ``plugins/bot_unified_runtime/domains/core/safety_exec/action_catalog.py``
（规格 §1 点名的「动作册」真身）。本门五件事：

1. **腿①（册外动作不得执行）** —— :func:`resolve_action` 对一切未在册形态**当场抛**：
   未知串、空前缀、大小写变体、``None``、以及**册内前缀加尾巴**（``file.read.only``）都要拒。
   缺省值一律不许是「放行」，也不许是「转人工评审」（后者会让"没人登记"变成"有人看着"）。
   同腿并执法规格 §12 **G-2**（每枚 ``ActionId`` 有档、有角色下限、有落点域）与
   枚举↔册**双射**（有成员无声明行、有声明行无成员，两个方向各自红）。

2. **腿①′（不变式① 的字面形态）** —— 全册派生出的裁决点集合大小**恒为 1**。
   动作册刻意不给逐枚 ``adjudication_point`` 字段：那张表结构上允许长出第二个裁决点。

3. **腿②（禁手抄动作清单，须从枚举派生）** —— 全树 AST 扫**精确等于**某枚 ``ActionId``
   字面值的字符串常量、以及成员**值域**与 ``ActionId`` 相交的第二个枚举。除真身自己那件外
   命中即红。

4. **腿③（禁第二份「动作→裁决」表）** —— ``ACTION_CATALOG`` 全树只准赋值一次；
   别的模块级 dict 字面量里键为动作 id 的≥2 枚即第二真身；``RiskTier`` 全树只准定义一次
   （真身住 ``config_risk.py``，动作册必须吃它而不是再长一套）。

5. **一发判据（规格 §2 末行）** —— 每枚 ``ActionId`` 各有一发专属用例把它四列值钉在规格 §2
   的原文期望上；**册里新增一枚而没有对应那一发，本门当场红**（用差集执法，不靠人记）。

判据形态的两处现算依据（写死在这里，防后来人把这两条"改进"回去）
------------------------------------------------------------------

* **不按类名找第二枚举**：本席位开工时现算全树含 18 个名字里带 ``Action`` 的类
  （``decision.ActionKind`` / ``control_plane.ControlActionDescriptor`` /
  ``schedule.llm_draft.DraftAction`` …），与 ``ActionId`` 值域**相交枚数全为 0**。
  按名字判红会把这 9 个无关件一并打红——那台门第一天就是假红机。现行判据只看**值域相交**。
* **不做子串匹配**：``file.read`` 作子串会命中 ``file.read_text(...)``、``file.send`` 会命中
  ``wfile.send(...)`` 一类属性调用。本仓实测：子串式 grep 在动作册之外命中 9 处全属此类误伤，
  精确字符串常量判据命中 **0** 处。所以腿② 走 AST 常量精确等值，不走文本 grep。

三条腿的**杀伤力自证**在本文件内各自带一发注毒（:class:`_ScanTarget` 让判据可喂合成源，
注毒只喂进内存/``tmp_path``，**绝不写真实树**——本波实测到有席位在真实树上注毒并振荡，
166 例全绿看不见污染）。全离线零网络，不在源码树留缓存。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.core.safety_exec import action_catalog as ac
from plugins.bot_unified_runtime.domains.core.safety_exec import config_risk
from plugins.bot_unified_runtime.domains.core.safety_exec.action_catalog import (
    ACTION_CATALOG,
    ADJUDICATION_POINT,
    REGISTERED_ROLE_FLOOR_EXCEPTIONS,
    ActionId,
    LandingDomain,
    UnregisteredActionError,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 🔴 本波实测到有席位**在真实树上注毒并振荡**（含 ``if False:`` 惰性形态，166 例全绿看不见污染）。
#: 本门的注毒因此一律打在 ``$TEMP`` 的副本树上：把扫描根指过去即可，**真实树一字节不动**。
#: 只有**文本扫描**类腿会读这里（腿②/腿③），行为类腿（resolve/双射/档位）永远吃真实模块——
#: 所以这个开关开不出"用假树糊住真身"的效果，只能用来证明判据会红。
#: 未设该环境变量时恒等于真实仓库根。
_SCAN_ROOT_OVERRIDE = "SEAT_POISON_ROOT"


def _scan_root() -> Path:
    import os

    raw = os.environ.get(_SCAN_ROOT_OVERRIDE, "").strip()
    return Path(raw).resolve() if raw else REPO_ROOT


def _relative_owner() -> Path:
    """真身文件在**当前扫描根**下的位置（注毒树里放一份被改过的副本用）。"""
    return _scan_root() / OWNER

#: 真身与它必须吃进的两枚既有件（相对仓库根的 POSIX 形）。
OWNER = "plugins/bot_unified_runtime/domains/core/safety_exec/action_catalog.py"
TIER_HOME = "plugins/bot_unified_runtime/domains/core/safety_exec/config_risk.py"
ROLE_HOME = "plugins/bot_unified_runtime/domains/chat_reply/policy/roles.py"

#: 腿② 字面量判据的射程＝**生产面**（`plugins/` + `scripts/` + `bot.py`）。
#:
#: 🔴 这个射程是**明写的**，不是偷偷放宽——理由有两条，缺一条就不该缩：
#: ① 第二真身的危害在于「被生产代码消费」，测试件里的期望值不会在任何调用路径上被读到；
#: ② 规格 §2 末行**要求**每枚动作配一发判据，本文件的 :data:`SPEC_2_ROWS` /
#: :data:`SPEC_2_ACTION_IDS` 因此**必然**逐枚写出动作 id——把腿② 铺到 `tests/`
#: 会立刻把这份"规格自己要求的期望锁"打红，那是一台假红机。
#: 缩了射程就得补一条等值锁，故本门另由
#: :func:`test_leg1_catalog_membership_matches_spec_2_exactly` 与
#: :func:`test_every_action_id_has_its_own_dedicated_case` 执法
#: 「期望表 == 册」——期望表一旦与册漂移就红，它不能变成第二套事实。
#: 「第二枚举」那一半判据**不缩**，仍铺全树（含 `tests/`）：测试件里再长一套
#: 值域相交的动作枚举同样是病。
PRODUCTION_DIRS = ("plugins", "scripts")
ALL_DIRS = ("plugins", "tests", "scripts")
SCAN_LOOSE_PY = ("bot.py",)

#: 规格 §2 表格第一列的原文顺序与枚数（本门用它钉「不增不减」）。
SPEC_2_ACTION_IDS: tuple[str, ...] = (
    "file.read",
    "file.write",
    "file.send",
    "code.run",
    "fs.delete",
    "config.write.safe",
    "config.write.risk",
    "config.write.danger",
    "config.write.forbidden",
    "net.fetch",
    "push.proactive",
    "peer.act",
)

#: 规格 §2 逐枚期望值（角色下限 / 同意档 / 落点域）。这是**测试侧的期望锁**，
#: 不是生产第二真身：生产只读 ACTION_CATALOG，本表只用来发现漂移。腿③ 的 AST 扫
#: 因此刻意不匹配本表——本表键是 ActionId 成员表达式而非字符串常量，见 §一发判据。
SPEC_2_ROWS: dict[ActionId, tuple[str, config_risk.RiskTier, LandingDomain]] = {
    ActionId.FILE_READ: ("user", config_risk.RiskTier.R0, LandingDomain.READABLE_ROOT),
    ActionId.FILE_WRITE: ("trusted", config_risk.RiskTier.R1, LandingDomain.WRITABLE_ROOT),
    ActionId.FILE_SEND: ("trusted", config_risk.RiskTier.R1, LandingDomain.WRITABLE_THEN_OUTBOUND),
    ActionId.CODE_RUN: (
        "super_admin",
        config_risk.RiskTier.R2,
        LandingDomain.EXECUTABLE_ROOT_ISOLATED,
    ),
    ActionId.FS_DELETE: (
        "super_admin",
        config_risk.RiskTier.R2,
        LandingDomain.INSIDE_WRITABLE_ROOT,
    ),
    ActionId.CONFIG_WRITE_SAFE: ("admin", config_risk.RiskTier.R0, LandingDomain.CONFIG_SURFACE),
    ActionId.CONFIG_WRITE_RISK: ("admin", config_risk.RiskTier.R1, LandingDomain.CONFIG_SURFACE),
    ActionId.CONFIG_WRITE_DANGER: (
        "super_admin",
        config_risk.RiskTier.R2,
        LandingDomain.CONFIG_SURFACE,
    ),
    ActionId.CONFIG_WRITE_FORBIDDEN: (
        ac.ROLE_FLOOR_NO_ROLE,
        config_risk.RiskTier.R3,
        LandingDomain.NONE,
    ),
    ActionId.NET_FETCH: ("trusted", config_risk.RiskTier.R0, LandingDomain.VIA_SSRF_GATEWAY),
    ActionId.PUSH_PROACTIVE: (
        ac.ROLE_FLOOR_INTERNAL,
        config_risk.RiskTier.R1,
        LandingDomain.SOLE_OUTBOUND,
    ),
    ActionId.PEER_ACT: (
        ac.ROLE_FLOOR_INTERNAL,
        config_risk.RiskTier.R0,
        LandingDomain.NONE,
    ),
}


# ---------------------------------------------------------------------------
# 扫描基础设施：判据写成可喂合成源的纯函数，注毒才不必碰真实树
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ScanTarget:
    """一个待扫源：(相对路径, 源码)。真实树与本文件内的合成注毒源共用同一判据。"""

    rel: str
    source: str


@cache
def _iter_scope_sources(dirs: tuple[str, ...], root: Path) -> tuple[_ScanTarget, ...]:
    """扫一码树的 ``*.py``。同一进程内多条腿共用一份读结果（全树解析实测 ~29s，别放大三遍）。"""
    out: list[_ScanTarget] = []
    for d in dirs:
        for path in sorted((root / d).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            out.append(_ScanTarget(path.relative_to(root).as_posix(), _safe_read(path)))
    for name in SCAN_LOOSE_PY:
        path = root / name
        if path.is_file():
            out.append(_ScanTarget(name, _safe_read(path)))
    return tuple(out)


def _iter_tree_sources(*, production_only: bool = False) -> list[_ScanTarget]:
    return list(_iter_scope_sources(PRODUCTION_DIRS if production_only else ALL_DIRS, _scan_root()))


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _parse(rel: str, source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        # 半写文件（本波 D-8 形态：paths.py 被写坏过）不属于本门的判定对象，
        # 它自有收集期红；这里跳过是为了让"第二真身"判据不被无关件的语法错糊住。
        return None


def _action_id_literals(tree: ast.Module) -> list[tuple[int, str]]:
    return [
        (n.lineno, n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in _ID_VALUES
    ]


_ID_VALUES = frozenset(a.value for a in ActionId)


def _enum_member_values(tree: ast.Module) -> dict[str, set[str]]:
    """类名 → 该类 ``Name = "str"`` 形态成员的字面值集合（Enum 声明的通用形态）。"""
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        vals: set[str] = set()
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign):
                target, value = stmt.target, stmt.value
            elif isinstance(stmt, ast.Assign):
                target, value = (stmt.targets[0] if stmt.targets else None), stmt.value
            else:
                continue
            if (
                isinstance(target, ast.Name)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                vals.add(value.value)
        if vals:
            found[node.name] = vals
    return found


def _module_level_dict_literals(tree: ast.Module) -> list[tuple[int, int]]:
    """模块级 dict 字面量：(行号, 键里动作 id 的枚数)。"""
    out: list[tuple[int, int]] = []
    for stmt in tree.body:
        nodes = [stmt] if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else []
        for nd in nodes:
            value = nd.value
            if not isinstance(value, ast.Dict):
                continue
            keys = sum(
                1
                for k in value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value in _ID_VALUES
            )
            out.append((getattr(value, "lineno", 0), keys))
    return out


def _assigned_names(tree: ast.Module) -> list[str]:
    out: list[str] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            out += [t.id for t in stmt.targets if isinstance(t, ast.Name)]
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            out.append(stmt.target.id)
    return out


def _class_names(tree: ast.Module) -> list[str]:
    return [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]


# ---------------------------------------------------------------------------
# 腿①：册外动作不得执行（fail-closed）
# ---------------------------------------------------------------------------


#: 一律必须被拒的形态。每发都是一条真实攻击/真实疏漏的形状，不是随手字符串。
UNREGISTERED_SHAPES: tuple[object, ...] = (
    "file.delete",          # 近似词：看着像 file.read/file.write 的合体
    "rm_rf",                # 完全无关
    "",                     # 空串：装配点忘传动作
    None,                   # 空对象：同上，另一种形态
    "FILE.READ",            # 大小写变体（id 是大小写敏感的）
    "file.read.only",       # 册内前缀 + 尾巴：子串判据会放行的那一类
    "code.run.sandboxed",   # 想给 code.run 开一个"看着更狠"的旁支 id
    "config.write",         # 册里有四枚 config.write.*，但没有这枚光杆
    "peer.act.bulk",        # 群发第三人动作的自造 id
    7,                      # 类型都不对的东西
)


@pytest.mark.parametrize("shape", UNREGISTERED_SHAPES, ids=lambda s: repr(s))
def test_leg1_unregistered_action_is_denied_fail_closed(shape: object) -> None:
    """册外动作必须**抛**，不得缺省放行、也不得缺省转人工评审。

    判据与注毒二发共用 :func:`_fail_closed_leaks`，不走两条各自成立的路。
    """
    assert _fail_closed_leaks(ac.resolve_action, (shape,)) == []


@pytest.mark.parametrize("shape", UNREGISTERED_SHAPES, ids=lambda s: repr(s))
def test_leg1_consent_and_never_auto_helpers_also_refuse_unknown(shape: object) -> None:
    """派生口不得给未知动作兜底出一个「不需要同意」。"""
    with pytest.raises(UnregisteredActionError):
        ac.consent_required(shape)
    with pytest.raises(UnregisteredActionError):
        ac.is_never_auto(shape)


def test_leg1_no_default_spec_path_exists() -> None:
    """册上**不得存在**任何"取不到就给缺省"的口子（防将来加 ``resolve(raw, default=…)``）。

    只查**本模块自己定义的**可调用件：``dir(ac)`` 里还挂着 ``dataclass`` / ``Final``
    这类被 import 进来的名字，它们天然带一堆缺省参数——第一版没过滤，被
    ``dataclass 带了缺省参数 ['cls','init','repr',…]`` 当场打红（自造红，非门的本意）。
    """
    import inspect

    checked = 0
    for name in dir(ac):
        if name.startswith("_"):
            continue
        obj = getattr(ac, name)
        if isinstance(obj, type) or not callable(obj):
            continue
        if getattr(obj, "__module__", None) != ac.__name__:
            continue  # 从别处 import 进来的可调用件不归本门管
        checked += 1
        try:
            params = inspect.signature(obj).parameters
        except (TypeError, ValueError):  # pragma: no cover - 取不到签名的件不判
            continue
        offending = [
            p for p, q in params.items() if q.default is not inspect.Parameter.empty
        ]
        assert not offending, f"{name} 带了缺省参数 {offending}＝缺省路径的破口"
    assert checked >= 4, f"只扫到 {checked} 枚本模块可调用件，判据射程可疑（近乎空跑）"
    for banned in ("default_spec", "fallback_spec", "DEFAULT_SPEC", "resolve_or_default"):
        assert banned not in {n for n in dir(ac) if not n.startswith("_")}


def _bijectivity_violations(
    enum_ids: set[object], catalog_ids: set[object]
) -> list[str]:
    """枚举↔册双向等值的判据（抽成纯函数，注毒才不必真去改枚举）。"""
    bad: list[str] = []
    only_enum = sorted({str(x) for x in enum_ids - catalog_ids})
    only_catalog = sorted({str(x) for x in catalog_ids - enum_ids})
    if only_enum:
        bad.append(f"有成员无声明行（新动作没登记档位就上路的形状）：{only_enum}")
    if only_catalog:
        bad.append(f"有声明行无成员（册与枚举漂移）：{only_catalog}")
    return bad


def test_leg1_enum_and_catalog_are_bijective() -> None:
    """枚与声明行**双向**等值：有成员无行 / 有行无成员，两个方向各自红。"""
    assert _bijectivity_violations(set(ActionId), set(ACTION_CATALOG)) == []


def test_leg1_catalog_membership_matches_spec_2_exactly() -> None:
    """规格 §2 首批十二枚：**不增不减不换序**。"""
    assert tuple(a.value for a in ActionId) == SPEC_2_ACTION_IDS


def test_leg1_source_row_count_matches_enum() -> None:
    """**源码级**双射：册文件里的 ``_spec(`` 调用枚数 == 枚举成员数 == 规格 §2 十二枚。

    行为腿（:func:`test_leg1_enum_and_catalog_are_bijective`）吃的是**已导入**的模块，
    删掉一行声明会同时改掉枚举可见结果；这一腿只**读文本**，所以注毒副本树上也能独立咬，
    且能抓到"改了源但导入的是旧 ``.pyc``"这一类本波实测过的形态（D-8）。
    """
    src = _relative_owner().read_text(encoding="utf-8")
    tree = _parse(OWNER, src)
    assert tree is not None, "动作册真身解析失败（半写形态）——本腿红，不去改那个文件"
    # `def _spec(` 自身含子串 `_spec(`，减掉它才是调用点枚数。
    rows = src.count("_spec(") - src.count("def _spec(")
    assert rows == len(list(ActionId)) == len(SPEC_2_ACTION_IDS), (
        f"册文件里声明行 {rows} 枚 / 枚举成员 {len(list(ActionId))} 枚 / "
        f"规格 §2 {len(SPEC_2_ACTION_IDS)} 枚，三者必须同数"
    )
    enum_vals = _enum_member_values(tree).get("ActionId", set())
    assert enum_vals == _ID_VALUES, f"文本里的 ActionId 值域与导入结果不一致：{sorted(enum_vals)}"


@pytest.mark.parametrize("action", list(ActionId), ids=lambda a: a.value)
def test_leg1_g2_completeness_per_action(action: ActionId) -> None:
    """规格 §12 G-2 逐枚：有档、有角色下限、有落点域，且类型正确。"""
    spec = ACTION_CATALOG[action]
    assert isinstance(spec.default_tier, config_risk.RiskTier), f"{action.value} 缺档"
    assert isinstance(spec.role_floor, str) and spec.role_floor, f"{action.value} 缺角色下限"
    assert isinstance(spec.landing_domain, LandingDomain), f"{action.value} 缺落点域"
    assert isinstance(spec.semantics, str) and spec.semantics, f"{action.value} 缺语义"
    assert spec.action is action


def test_leg1_role_floors_are_real_roles_or_registered_exceptions() -> None:
    """角色下限**合法性派生自** ``roles.ROLE_ORDER``——本门不吃手抄角色清单。

    动作册自己不含秩、不 import roles（见其 docstring 取向 3），秩的唯一来源在这里现取。
    """
    import importlib

    roles = importlib.import_module(
        "plugins.bot_unified_runtime.domains.chat_reply.policy.roles"
    )
    legal = frozenset(roles.ROLE_ORDER) | REGISTERED_ROLE_FLOOR_EXCEPTIONS
    for spec in ACTION_CATALOG.values():
        assert spec.role_floor in legal, (
            f"{spec.action.value} 的角色下限 {spec.role_floor!r} 既不在 ROLE_ORDER，"
            "也不是本席注册的两枚例外（none/internal）"
        )
    # 自证 ROLE_ORDER 真的在册外：门若退化成"恒真"，这一发立刻红。
    assert "definitely_not_a_role" not in legal


def test_leg1_catalog_declares_no_role_rank_table() -> None:
    """动作册不得自带角色秩（规格 §1：角色秩唯一来源是 roles.py，本件不自建第二套）。"""
    src = _relative_owner().read_text(encoding="utf-8")
    tree = _parse(OWNER, src)
    assert tree is not None
    for name in _assigned_names(tree):
        up = name.upper()
        assert "RANK" not in up and "ORDER" not in up, f"动作册长出了秩表 {name}"
    import importlib

    roles = importlib.import_module(
        "plugins.bot_unified_runtime.domains.chat_reply.policy.roles"
    )
    for member in vars(ac).values():
        assert member is not getattr(roles, "ROLE_ORDER", None), "动作册把 ROLE_ORDER 抄成了自己的常量"


# ---------------------------------------------------------------------------
# 腿①′：不变式① —— 一个动作只有一个裁决点
# ---------------------------------------------------------------------------


def test_leg1prime_single_adjudication_point() -> None:
    """全册派生出的裁决点集合大小恒为 1。"""
    points = {ac.adjudication_point() for _ in ACTION_CATALOG}
    assert points == {ADJUDICATION_POINT}
    assert len(ADJUDICATION_POINT) > 0


def test_leg1prime_no_per_action_adjudication_field() -> None:
    """``ActionSpec`` 上**不得**有逐枚裁决点字段——那等于允许一张表长出多个裁决点。"""
    field_names = set(ac.ActionSpec.__dataclass_fields__)
    assert field_names == {"action", "semantics", "role_floor", "default_tier", "landing_domain"}
    for name in field_names:
        assert "adjudicat" not in name.lower() and "decide" not in name.lower()


def test_leg1prime_catalog_is_declaration_data_only() -> None:
    """规格 §1：动作册是「声明数据，不 import 包内业务件」。

    放行的依赖只有 stdlib 与同包内同样纯声明的 ``config_risk``（档位真身）。
    """
    tree = _parse(OWNER, _relative_owner().read_text(encoding="utf-8"))
    assert tree is not None
    allowed_prefix = ("__future__", "dataclasses", "enum", "typing", "collections.abc")
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods = [node.module]
        for mod in mods:
            assert mod.startswith(allowed_prefix) or mod.endswith(
                ".safety_exec.config_risk"
            ), f"动作册 import 了业务件 {mod}"


# ---------------------------------------------------------------------------
# 腿②：禁手抄动作清单（须从枚举派生）
# ---------------------------------------------------------------------------


def _leg2_literal_violations(targets: list[_ScanTarget]) -> list[str]:
    """半①：精确等于某枚 ``ActionId`` 字面值的字符串常量（生产面射程）。"""
    bad: list[str] = []
    for t in targets:
        if t.rel == OWNER:
            continue
        tree = _parse(t.rel, t.source)
        if tree is None:
            continue
        for lineno, value in _action_id_literals(tree):
            bad.append(f"{t.rel}:{lineno} 手抄动作 id {value!r}")
    return bad


def _leg2_enum_violations(targets: list[_ScanTarget]) -> list[str]:
    """半②：成员**值域**与 ``ActionId`` 相交的第二个枚举（全树射程，含 `tests/`）。

    判据只看值域相交、**不看类名**——见文件头「按类名找第二枚举」那条现算依据。
    """
    bad: list[str] = []
    for t in targets:
        if t.rel == OWNER:
            continue
        tree = _parse(t.rel, t.source)
        if tree is None:
            continue
        for cls, vals in _enum_member_values(tree).items():
            overlap = vals & _ID_VALUES
            if overlap:
                bad.append(f"{t.rel} 第二枚举 {cls} 与 ActionId 值域相交 {sorted(overlap)}")
    return bad


def _leg2_violations(targets: list[_ScanTarget]) -> list[str]:
    """两半合起来（供注毒自证一发同时喂两种形状）。"""
    return _leg2_literal_violations(targets) + _leg2_enum_violations(targets)


def test_leg2_no_hand_copied_action_id_list_in_production() -> None:
    """生产面除真身外不得出现精确动作 id 字面量——新增动作必须从 ``ActionId`` 派生。"""
    assert _leg2_literal_violations(_iter_tree_sources(production_only=True)) == []


def test_leg2_no_second_action_enum_anywhere() -> None:
    """全树（含测试件）不得长出值域相交的第二套动作枚举。"""
    assert _leg2_enum_violations(_iter_tree_sources()) == []


def test_leg2_predicate_is_armed_against_both_poison_shapes() -> None:
    """判据杀伤力自证：手抄清单与第二枚举两种形状都必被同一条判据点名。"""
    hand_copy = _ScanTarget(
        "plugins/bot_unified_runtime/domains/whatever/impersonator.py",
        'ALLOWED = ["file.read", "code.run"]\n',
    )
    second_enum = _ScanTarget(
        "plugins/bot_unified_runtime/domains/whatever/second.py",
        "from enum import Enum\n\n"
        "class MyActionIds(str, Enum):\n"
        '    A = "file.read"\n'
        '    B = "peer.act"\n',
    )
    found = _leg2_violations([hand_copy, second_enum])
    assert len(found) >= 3, f"注毒未被点名：{found}"
    assert any("手抄动作 id" in x for x in found)
    assert any("第二枚举" in x for x in found)
    # 反向锁：不含动作 id 的普通源不得被点名（防门退化成一见列表就红）。
    innocent = _ScanTarget(
        "plugins/bot_unified_runtime/domains/whatever/ok.py",
        'COLORS = ["red", "blue"]\n\nclass OtherKind(str):\n    A = "red"\n',
    )
    assert _leg2_violations([innocent]) == []
    # 反向锁：带 Action 之名但值域无关的件不得被点名——本仓实测有 18 个这类类。
    lookalike = _ScanTarget(
        "plugins/bot_unified_runtime/domains/core/decision/engine.py",
        "from enum import Enum\n\n"
        "class ActionKind(str, Enum):\n"
        '    PASSIVE_ABSORB = "passive_absorb"\n'
        '    NOTICE_ACTION = "notice_action"\n',
    )
    assert _leg2_enum_violations([lookalike]) == [], "按类名误伤的形态又回来了"


# ---------------------------------------------------------------------------
# 腿③：禁第二份「动作→裁决」表
# ---------------------------------------------------------------------------


def _leg3_violations(targets: list[_ScanTarget]) -> list[str]:
    bad: list[str] = []
    catalog_defs = 0
    tier_defs = 0
    for t in targets:
        tree = _parse(t.rel, t.source)
        if tree is None:
            continue
        if "ACTION_CATALOG" in _assigned_names(tree):
            catalog_defs += 1
        if "RiskTier" in _class_names(tree):
            tier_defs += 1
            if t.rel != TIER_HOME:
                bad.append(f"{t.rel} 定义了第二套 RiskTier")
        if t.rel == OWNER:
            continue
        for lineno, n in _module_level_dict_literals(tree):
            if n >= 2:
                bad.append(f"{t.rel}:{lineno} 第二份以动作 id 为键的表（{n} 枚键）")
    if catalog_defs != 1:
        bad.append(f"ACTION_CATALOG 全树赋值 {catalog_defs} 次，应为 1")
    if tier_defs != 1:
        bad.append(f"RiskTier 全树定义 {tier_defs} 次，应为 1（真身 config_risk.py）")
    return bad


def test_leg3_no_second_action_decision_table() -> None:
    """全树只准存在一份动作册与一份风险档表。"""
    assert _leg3_violations(_iter_tree_sources()) == []


def test_leg3_catalog_consumes_tier_truth_and_does_not_redefine() -> None:
    """动作册必须**吃** ``config_risk.RiskTier``，自己不再长一套（正向复用锁）。

    第一版这条写成了 ``consent_required(...) is (tier := CONSENT_REQUIRED_TIERS)``——
    拿 ``bool`` 去 ``is`` 一个 frozenset，恒假，是我自己造的红（自造自见）。
    现行三句各查一件事：同一个类对象、册里没有再定义、派生口与真值集合逐枚同意。
    """
    assert ac.RiskTier is config_risk.RiskTier
    src = _relative_owner().read_text(encoding="utf-8")
    assert "class RiskTier" not in src, "动作册里长出了第二套 RiskTier"
    for action in ActionId:
        tier = ACTION_CATALOG[action].default_tier
        assert ac.consent_required(action) is (tier in config_risk.CONSENT_REQUIRED_TIERS), (
            f"{action.value}：册的同意结论与 config_risk 的档位集合不一致（长出第二本账了）"
        )
        assert ac.is_never_auto(action) is (tier in config_risk.NEVER_AUTO_TIERS), (
            f"{action.value}：永不自动结论与 config_risk.NEVER_AUTO_TIERS 不一致"
        )


def test_leg3_predicate_is_armed_against_second_table() -> None:
    """判据杀伤力自证：第二份「动作→裁决」表必红，且 ``ACTION_CATALOG`` 被搬走也必红。"""
    second_table = _ScanTarget(
        "plugins/bot_unified_runtime/domains/whatever/shadow.py",
        'DECISIONS = {"code.run": "allow", "fs.delete": "deny"}\n',
    )
    found = _leg3_violations([second_table])
    assert any("第二份以动作 id 为键" in x for x in found), found
    # 把真身从视野里摘掉 → 计数判据必须立刻点名"赋值 0 次"（防恒绿）。
    assert any("ACTION_CATALOG" in x for x in _leg3_violations([second_table]))


# ---------------------------------------------------------------------------
# 一发判据（规格 §2 末行）：新增动作没配用例 → 红
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", list(ActionId), ids=lambda a: a.value)
def test_one_case_per_action_against_spec_2_table(action: ActionId) -> None:
    """每枚动作各一发，四列值钉在规格 §2 原文期望上。"""
    expected_floor, expected_tier, expected_domain = SPEC_2_ROWS[action]
    spec = ACTION_CATALOG[action]
    assert spec.role_floor == expected_floor
    assert spec.default_tier is expected_tier
    assert spec.landing_domain is expected_domain


def test_every_action_id_has_its_own_dedicated_case() -> None:
    """规格 §2「新增 ActionId 必须同批配一发判据」的机器形态：差集必红。"""
    assert set(SPEC_2_ROWS) == set(ActionId), (
        f"有用例无枚={sorted(set(SPEC_2_ROWS) - set(ActionId), key=str)} "
        f"有枚无用例={sorted(set(ActionId) - set(SPEC_2_ROWS), key=str)}"
    )


# ---------------------------------------------------------------------------
# 注毒自证：三发（全在内存/合成源里，真实树一字节未动——见文件头纪律说明）
# ---------------------------------------------------------------------------


def _fail_closed_leaks(
    resolve_fn: object, shapes: tuple[object, ...]
) -> list[object]:
    """册外动作腿的**唯一判据**：返回"没被 fail-closed 拒掉"的形态清单。

    只有 :class:`UnregisteredActionError` 算拒。返回了东西、或抛了别的异常，
    都算漏——后者也算漏是因为调用方按统一异常捕，抛 ``TypeError`` 等于换个口子放行。
    真测试与注毒**共用这一个函数**，注毒才不是"另写一段看着像"的自证。
    """
    leaks: list[object] = []
    for shape in shapes:
        try:
            assert callable(resolve_fn)
            resolve_fn(shape)  # type: ignore[operator]
        except UnregisteredActionError:
            continue
        except Exception:  # noqa: BLE001 - 漏检面探测器：任何非「未登记」的逃逸都算一条漏，宽捕获是判据本身
            leaks.append(shape)
            continue
        leaks.append(shape)
    return leaks


def test_poison_1_registering_an_unlisted_action_turns_the_gate_red() -> None:
    """注毒一发「注册了一个册外动作」：两个方向各验一次。

    ① 只往枚举加成员、不配声明行 —— 双射腿必须点名；
    ② 只往册里加行、枚举里没有 —— 反方向也必须点名。
    这模拟的是「有人新加了个动作类别却忘了登记档位」：今天这条若不成红，
    新动作会静悄悄带着「无档、无角色下限、无落点域」上路。
    """
    enum_only = {ActionId.FILE_READ, ActionId.CODE_RUN, "shell.spawn"}
    catalog_only = {ActionId.FILE_READ, ActionId.CODE_RUN}
    hit = _bijectivity_violations(enum_only, catalog_only)
    assert len(hit) == 1 and "有成员无声明行" in hit[0] and "shell.spawn" in hit[0], hit

    hit2 = _bijectivity_violations(catalog_only, catalog_only | {"proc.kill"})
    assert len(hit2) == 1 and "有声明行无成员" in hit2[0], hit2

    # 反向锁：真实册子喂进去必须零命中，否则上面两发是"恒红"的假门。
    assert _bijectivity_violations(set(ActionId), set(ACTION_CATALOG)) == []
    # 行为面：册外 id 走真实 resolve 必须炸（注毒没漏进真身）。
    with pytest.raises(UnregisteredActionError):
        ac.resolve_action("shell.spawn")


def test_poison_2_defaulting_to_needs_review_turns_the_gate_red() -> None:
    """注毒二发：把 fail-closed 换成"缺省转人工评审" → 册外动作腿当场失守并被点名。

    这正是简报点名的"不得默认 ``needs_review`` 蒙混"那一条：看着像加了道评审，
    实际是给任意未登记动作开了后门（评审真身 ``policy.py`` 今天还不在盘）。
    """

    def _lenient(raw: object) -> object:  # 注毒体：刻意不碰真实树
        try:
            return ac.resolve_action(raw)
        except UnregisteredActionError:
            return ACTION_CATALOG[ActionId.FS_DELETE]  # 拿一枚"要 R2 同意"的当缺省

    leaked = _fail_closed_leaks(_lenient, UNREGISTERED_SHAPES)
    assert len(leaked) == len(UNREGISTERED_SHAPES), (
        f"注毒没生效或判据太松：只抓到 {len(leaked)}/{len(UNREGISTERED_SHAPES)} 发漏"
    )
    # 反向锁：同一判据喂真实实现必须全拒（否则该腿是一台恒红机）。
    assert _fail_closed_leaks(ac.resolve_action, UNREGISTERED_SHAPES) == []


def test_poison_3_hand_copied_list_and_second_table_turn_their_legs_red() -> None:
    """注毒三发：手抄枚举（腿②）与第二份「动作→裁决」表（腿③）各必被点名。

    两半合在一发里跑，是因为它们共用同一份扫描基础设施——分开写会各带一套
    合成源构造，反而看不清"同一台扫描器"这一件事。
    """
    copy = _ScanTarget(
        "plugins/bot_unified_runtime/domains/whatever/copied.py",
        'WHITELIST = ("file.read", "net.fetch", "peer.act")\n',
    )
    assert len(_leg2_literal_violations([copy])) == 3, "手抄枚举没被抓全"

    table = _ScanTarget(
        "plugins/bot_unified_runtime/domains/whatever/shadow2.py",
        'DECISIONS = {"code.run": "R2", "fs.delete": "R2", "file.read": "R0"}\n',
    )
    hit = _leg3_violations([table])
    assert any("第二份以动作 id 为键" in x and "3 枚键" in x for x in hit), hit

    # 反向锁：真实树两腿皆零命中（注毒若恒红，这两句先炸）。
    assert _leg2_literal_violations(_iter_tree_sources(production_only=True)) == []
    assert _leg3_violations(_iter_tree_sources(production_only=True)) == []
