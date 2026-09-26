"""物理归位普查（G-P1 / G-P2 的**唯一取数口**）。

本文件同时服务三件事，且三件事**共用同一批函数**（本仓抓到过"总数另算一套"的假绿）：
① 常驻门 `tests/test_physical_placement_gate.py` 的全树判定；
② 注毒自证（判据收参数化的合成数据，走内存/`tmp_path`，绝不往源码树写）；
③ `--report` 打印的现算值（本轮终局"三列表"的取数口）。

口径（写死，别让下游猜；出处=`.superpowers/sdd/2026-09-22-taxonomy/ORPHAN-MAP.md` §1 与
`GATE-PLAN.md` §三 G-P1/G-P2）：
- **语义 A（目录前缀认领，门的判据口径）**：`impl_path P` 认领文件 `F` ⇔ `F == P` 或 `F` 以 `P + "/"` 开头。
- **语义 B（字面文件认领）**：`impl_path P` 只认领 `F == P`。两种语义都实现成参数，门断言二者
  之差有限并打印——防止将来用"改判据"的方式把账做小。
- 扫描面 = `plugins/**/*.py`（递归，跳编译/环境目录）+ 仓库根 `*.py`（仅一层）；
  `tests/`、`scripts/`、`docs/` **不在** G-P2 范围（本门只管生产面，测试面如要账是第二本账）。
- 声明源读取**复用** `scripts/board_doc_sync.load_taxonomy`（同一支 AST 解析，禁第二份扫描器）；
  豁免清单用 AST 静态字面量读取 `domains/core/board_placement.py`（不 import 插件包，
  否则会把 NoneBot 的包初始化拖起来）。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from board_doc_sync import load_taxonomy  # 复用唯一 AST 解析口（禁第二份扫描器）

PLACEMENT_PY = REPO_ROOT / "plugins/bot_unified_runtime/domains/core/board_placement.py"
DOMAINS_DIR = REPO_ROOT / "plugins/bot_unified_runtime/domains"

#: 与 ORPHAN-MAP §1 写死的跳过表一致（只跳编译/环境目录，不跳业务目录）。
SKIP_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".git",
    }
)


# --------------------------------------------------------------------------
# 声明源装载
# --------------------------------------------------------------------------
class PlacementDeclarationError(RuntimeError):
    """声明源读不动——取数口 **fail-closed**，绝不把"读不到"当成"缺键/空集合"放行。

    旧版用裸 `except (ValueError, SyntaxError): out[name] = None` 把非法字面量静默变成 `None`，
    而键仍在 ⇒ `load_placement` 的"缺声明"断言抓不到，下游要么崩在别处、要么把一枚本该有内容的
    清单当成空来算，计数看起来"少认领"其实是**账具失明**（本仓 21/24 号失效形态同型）。
    """


def _read_literals(source: str, names: set[str], *, source_label: str = "<source>") -> dict[str, Any]:
    """静态读取声明源里的顶层字面量清单，**读不到即判红拒算**（fail-closed，P-S60-2）。

    认三种形态：`Assign`（`X = (...)`）、`AnnAssign`（`X: tuple = (...)`）、以及值为**嵌套容器**
    （tuple-of-tuple 等）的声明——`ast.literal_eval` 会把整棵嵌套字面量一次性求出来，故条数不丢。
    三态分别处理，杜绝旧版"读不到＝静默补 None"：
    - 命中名字且值是合法字面量 ⇒ 收进结果；
    - 命中名字但值不可静态求值（如 `frozenset(...)`／派生表达式）⇒ 立即抛 `PlacementDeclarationError`
      并点名 `文件:行`（绝不返回 `None`、绝不继续算）；
    - 名字从未出现 ⇒ 不写进结果，交由 `load_placement` 的"缺声明"断言判红。
    """
    tree = ast.parse(source)
    out: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        else:
            continue
        if node.value is None:  # 裸注解（`X: tuple`，无赋值）＝从未出现，交给缺声明断言处理
            continue
        for target in targets:
            if target.id not in names:
                continue
            try:
                out[target.id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError) as exc:  # fail-closed：读不到即拒算，绝不静默补 None
                raise PlacementDeclarationError(
                    f"{source_label}:{node.lineno} 声明 {target.id!r} 的值不是可静态求值的字面量"
                    f"——读不到＝判红拒算，不按\u201c缺键/空集合\u201d继续算：{exc}"
                ) from exc
    return out


def load_placement(*, source: str | None = None, source_label: str | None = None) -> dict[str, Any]:
    """物理归位门的声明数据（白名单前缀 + 枚举字面豁免清单）。

    默认读取真身 `board_placement.py`；`source`/`source_label` 仅供注毒自证在内存/临时副本喂料，
    绝不往源码树写一个字。三把 fail-closed 闸：读不动 ⇒ 抛错；从未出现 ⇒ 缺声明断言；被读成 `None`
    ⇒ 拒算（防任何未来把值写成 `X = None` 的静默失效形状）。
    """
    names = {"DOMAINS_ROOT", "PACKAGE_ROOT", "BANNED_CLAIM_PATHS", "G_P1_EXEMPT", "G_P2_EXEMPT"}
    label = source_label or PLACEMENT_PY.relative_to(REPO_ROOT).as_posix()
    text = PLACEMENT_PY.read_text(encoding="utf-8") if source is None else source
    data = _read_literals(text, names, source_label=label)
    missing = sorted(names - set(data))
    assert not missing, f"{label} 缺声明 {missing}——取数口不接受静默补空值（读不到＝判红）"
    nulled = sorted(k for k, v in data.items() if v is None)
    assert not nulled, f"{label} 声明被读成 None（读不到却不报错＝账具失明）：{nulled}"
    return data


def feature_impl_paths() -> list[tuple[str, tuple[str, ...]]]:
    """现役板块树：[(fid, impl_paths), ...]，按 fid 排序（枚举序无语义）。"""
    rows: list[tuple[str, tuple[str, ...]]] = []
    for board in load_taxonomy():
        for feature in board.get("features") or ():
            fid = str(feature.get("fid", ""))
            paths = tuple(str(p) for p in (feature.get("impl_paths") or ()))
            rows.append((fid, paths))
    return sorted(rows)


# --------------------------------------------------------------------------
# 扫描面（universe）
# --------------------------------------------------------------------------
def py_universe(repo: Path = REPO_ROOT) -> list[str]:
    files: set[str] = set()
    for path in (repo / "plugins").rglob("*.py"):
        rel = path.relative_to(repo).as_posix()
        if set(rel.split("/")) & SKIP_DIR_NAMES:
            continue
        files.add(rel)
    for path in repo.glob("*.py"):
        files.add(path.name)
    return sorted(files)


def registered_domain_roots(domains_dir: Path = DOMAINS_DIR) -> list[str]:
    """现役 `domains/<d>` 清单——**从目录派生，不手抄**（GATE-PLAN §G-P1 板卡）。"""
    return sorted(p.name for p in domains_dir.iterdir() if p.is_dir() and p.name not in SKIP_DIR_NAMES)


# --------------------------------------------------------------------------
# 认领谓词（单一实现，语义 A / 语义 B 都是参数）
# --------------------------------------------------------------------------
def claiming_fids(rel: str, claims: list[tuple[str, str]], *, semantic: str = "prefix") -> set[str]:
    """哪些 fid 认领了这个相对路径。`semantic`: `prefix`=语义 A（目录前缀）/ `literal`=语义 B。"""
    hit: set[str] = set()
    for fid, path in claims:
        if rel == path or (semantic == "prefix" and rel.startswith(path + "/")):
            hit.add(fid)
    return hit


def flatten_claims(rows: list[tuple[str, tuple[str, ...]]]) -> list[tuple[str, str]]:
    return [(fid, path) for fid, paths in rows for path in paths]


# --------------------------------------------------------------------------
# relocate 桶的三态判据（S165 · 拆「待搬迁」里的基础设施假阳，S160 方案 A）
# --------------------------------------------------------------------------
#: 一枚「域外 + 被某 fid 认领」的文件在搬迁账里的三种形态。旧判据只问这两条，于是把
#: 「有家的基础设施」也当成待归位件（S160 现算：46 枚里真可搬 0）。语义钉死：
#:   - `movable`        真可搬：认领它的 fid 声明了**落进 domains 白名单**的落点，且该落点在盘上还不存在。
#:   - `landing_exists` 声明的 domains 落点已存在 ⇒ 再搬＝覆盖真身（禁第二真身），不是搬迁对象。
#:   - `infrastructure` 无任何落进 domains 白名单的声明落点（fid 把 `control_plane` 这类子系统目录
#:                      本身声明为家）⇒「在家」而非「错配」，同样不是搬迁对象。
#: 「落点是否落 domains 白名单」与 G-P1 **同一支判据**（`_domain_of` + `registered_domain_roots`），
#: 禁第二套表：白名单改宽 ⇒ 本分桶必然跟着变（同源证明，见 S165 注毒 c）。
RELOCATE_STATES: tuple[str, ...] = ("movable", "landing_exists", "infrastructure")

#: 状态 → 派单可读的中文标签（报告/巡检面同源，禁各处手抄第二份口径）。
RELOCATE_STATE_LABELS: dict[str, str] = {
    "movable": "真可搬",
    "landing_exists": "落点已存在·禁覆盖",
    "infrastructure": "落点本来在 domains 外·基础设施常驻原地",
}


def domains_landing_points(
    rel: str,
    *,
    claims_by_fid: list[tuple[str, tuple[str, ...]]] | None = None,
    domains_root: str | None = None,
    domain_roots: set[str] | None = None,
    path_exists: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    """一枚域外文件的**声明落点**全表（只回 domains 白名单内的），逐条 `{fid, path, exists}`。

    单一取数口：`claims_by_fid` 默认 `feature_impl_paths()`（板块树声明）、白名单默认
    `registered_domain_roots()`（从 `domains/` 目录派生，与 G-P1 同源）、落点存在性默认查真树。
    三个入参只为**注毒自证在内存里喂料**而开（S94/S100 同哲学），默认路径与真账逐字一致。
    """
    placement = load_placement()
    rows = feature_impl_paths() if claims_by_fid is None else claims_by_fid
    domains_root = placement["DOMAINS_ROOT"] if domains_root is None else domains_root
    domain_roots = (
        set(registered_domain_roots()) if domain_roots is None else set(domain_roots)
    )
    checker = (lambda p: (REPO_ROOT / p).exists()) if path_exists is None else path_exists
    by_fid = dict(rows)
    fids = sorted(claiming_fids(rel, flatten_claims(rows), semantic="prefix"))
    out: list[dict[str, Any]] = []
    for fid in fids:
        for path in by_fid.get(fid, ()):
            domain = _domain_of(path, domains_root)
            if not domain or domain not in domain_roots:
                continue  # 落点本来不在 domains 白名单 ⇒ 非本桶对象（基础设施形态的成因）
            out.append({"fid": fid, "path": path, "exists": bool(checker(path))})
    return out


def relocate_state_of(
    rel: str,
    *,
    claims_by_fid: list[tuple[str, tuple[str, ...]]] | None = None,
    domains_root: str | None = None,
    domain_roots: set[str] | None = None,
    path_exists: Callable[[str], bool] | None = None,
) -> str:
    """搬迁三态判定（返回 `RELOCATE_STATES` 之一）。fail-closed：未知形态直接抛错，绝不静默归位。

    判序（只准加严，方向自查见 S165 §三）：有 domains 落点且**至少一枚不存在** ⇒ `movable`；
    有 domains 落点且**全部已存在** ⇒ `landing_exists`；压根没有 domains 落点 ⇒ `infrastructure`。
    """
    lands = domains_landing_points(
        rel,
        claims_by_fid=claims_by_fid,
        domains_root=domains_root,
        domain_roots=domain_roots,
        path_exists=path_exists,
    )
    if not lands:
        return "infrastructure"
    if any(not land["exists"] for land in lands):
        return "movable"
    if all(land["exists"] for land in lands):
        return "landing_exists"
    raise AssertionError(f"relocate 三态判定不合逻辑（既有缺又有全？）: {rel}")


def relocate_split(
    relocate: list[str],
    *,
    claims_by_fid: list[tuple[str, tuple[str, ...]]] | None = None,
    domains_root: str | None = None,
    domain_roots: set[str] | None = None,
    path_exists: Callable[[str], bool] | None = None,
) -> dict[str, list[str]]:
    """把 relocate 清单拆成三态（键恒为 `RELOCATE_STATES` 三枚，**含 0 也留空表**）。"""
    buckets: dict[str, list[str]] = {state: [] for state in RELOCATE_STATES}
    for rel in relocate:
        buckets[relocate_state_of(
            rel,
            claims_by_fid=claims_by_fid,
            domains_root=domains_root,
            domain_roots=domain_roots,
            path_exists=path_exists,
        )].append(rel)
    return {state: sorted(paths) for state, paths in buckets.items()}



# --------------------------------------------------------------------------
# G-P1：impl_paths 必须落在自己声明的 domains/<domain>/** 白名单内
# --------------------------------------------------------------------------
def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _domain_of(path: str, domains_root: str) -> str | None:
    """`plugins/bot_unified_runtime/domains/<d>/...` → `<d>`；否则 None。"""
    if not _under(path, domains_root):
        return None
    rest = path[len(domains_root) + 1 :]
    return rest.split("/")[0] if rest else None


def gp1_findings(
    rows: list[tuple[str, tuple[str, ...]]],
    *,
    domains_root: str,
    package_root: str,
    domain_roots: set[str],
    exempt: set[tuple[str, str]],
) -> dict[str, list[Any]]:
    """四桶 + 附账，全部只依赖声明面（可注毒，不碰真树）。

    每个功能的"自己声明的白名单"= 它自己的 `impl_paths` 落进的那些 `domains/<d>`（跨域功能天然
    得到多枚白名单，无需新增字段）。白名单之外又仍在插件包内的声明 = ①越界。
    `exempt` 是 `(fid, impl_path)` 对的集合（唯一构造口 `g_p1_exempt_keys`）；豁免以 **fid 精度**
     bypass ①越界/未登记域——不做"只按路径就全认领放行"，字面双认领等附账不受豁免影响。
    """
    _validate_gp1_exempt(exempt)
    outside: list[tuple[str, str]] = []      # ① 越界（含 pkg-root 与 docs/scripts/tests 等工程面）
    unknown_domain: list[tuple[str, str]] = []  # ① 的子类：指向未登记域根
    dup_literal: list[tuple[str, str]] = []     # ③ 同一字面路径被两个 fid 认领
    dup_within: list[tuple[str, str]] = []      # ④ 同一功能内重复声明
    banned: list[str] = []                      # 弱锁：包根当认领（一把吞全仓＝门自毁）
    claims_by_path: dict[str, set[str]] = {}
    banned_paths = set(load_placement()["BANNED_CLAIM_PATHS"])
    for fid, paths in rows:
        if len(set(paths)) != len(paths):
            dup_within.extend((fid, p) for p in {x for x in paths if paths.count(x) > 1})
        homes = {d for d in (_domain_of(p, domains_root) for p in paths) if d}
        for path in paths:
            claims_by_path.setdefault(path, set()).add(fid)
            if path in banned_paths:
                banned.append(path)
                continue
            if (fid, path) in exempt:  # 键形＝(fid, impl_path)，与 g_p1_exempt_keys 同源（P-S70-4 根修）
                continue
            domain = _domain_of(path, domains_root)
            if domain is None:
                outside.append((fid, path))
            elif domain not in domain_roots:
                unknown_domain.append((fid, path))
            elif domain not in homes:  # homes 由同一条声明推出，恒真；留着防未来改坏白名单口径
                outside.append((fid, path))
    for path, fids in claims_by_path.items():
        if len(fids) > 1:
            dup_literal.extend((fid, path) for fid in sorted(fids))
    # 包含形重叠（目录认领套住别的 fid 的认领）：按 GATE-PLAN 用"最长前缀归属唯一"归因，
    # 不算双认领，但**逐对记账**（棘轮只降），影子认领＝归属含糊正是本波要清算的东西。
    contain: list[tuple[str, str, str, str]] = []
    all_paths = sorted(claims_by_path)
    for outer in all_paths:
        for inner in all_paths:
            if outer is inner or not inner.startswith(outer + "/"):
                continue
            if _is_dir_like(outer) and claims_by_path[outer] != claims_by_path[inner]:
                contain.append((outer, ",".join(sorted(claims_by_path[outer])), inner, ",".join(sorted(claims_by_path[inner]))))
    return {
        "outside_domain": sorted(outside),
        "unknown_domain": sorted(unknown_domain),
        "double_claim": sorted(dup_literal),
        "duplicate_within": sorted(dup_within),
        "banned_claims": sorted(set(banned)),
        "contain_pairs": sorted(contain),
    }


def _is_dir_like(path: str) -> bool:
    return not path.endswith(".py") and not path.endswith(".md")


def empty_plugin_dir_claims(
    rows: list[tuple[str, tuple[str, ...]]],
    universe: list[str],
    *,
    package_root: str,
) -> list[tuple[str, str]]:
    """包内目录形声明必须至少覆盖 1 个 py（ORPHAN-MAP §3.1 弱锁：防"空认领"把账做没）。"""
    out: list[tuple[str, str]] = []
    for fid, paths in rows:
        for path in paths:
            if not _under(path, package_root) or not _is_dir_like(path):
                continue
            if not any(u == path or u.startswith(path + "/") for u in universe):
                out.append((fid, path))
    return sorted(out)


# --------------------------------------------------------------------------
# G-P2：plugins/** 与根 py 未被任何 impl_paths 认领 ⇒ 红
# --------------------------------------------------------------------------
def gp2_findings(
    claims: list[tuple[str, str]],
    universe: list[str],
    exempt: set[str],
    *,
    semantic: str = "prefix",
) -> dict[str, list[str]]:
    unclaimed = [rel for rel in universe if not claiming_fids(rel, claims, semantic=semantic)]
    violations = [rel for rel in unclaimed if rel not in exempt]
    stale = sorted(rel for rel in exempt if rel not in universe)
    dead = sorted(rel for rel in exempt if rel in universe and rel not in unclaimed)
    return {
        "unclaimed": unclaimed,
        "violations": violations,
        "stale_exempts": stale,
        "dead_exempts": dead,
    }


def exemption_shape_errors(entries: list[Any] | tuple[Any, ...]) -> list[tuple[str, str]]:
    """豁免清单的形状校验：必须是**字面相对路径**，禁通配符 / 正则 / 目录兜底 / 绝对路径。

    用户原话："不许用通配否则等于没门"。本函数只判形状，存在性与必要性由门的
    stale/dead 两把锁管（同一取数口的另外两支）。
    """
    problems: list[tuple[str, str]] = []
    for entry in entries:
        path = str(entry[0])
        if any(ch in path for ch in "*?[]\\"):
            problems.append((path, "含通配符/正则/反斜杠"))
        elif path.startswith("/") or ":" in path:
            problems.append((path, "绝对路径"))
        elif path.endswith("/"):
            problems.append((path, "目录兜底"))
        elif not path.endswith((".py", ".md")):
            problems.append((path, "非字面文件路径"))
    return problems


# --------------------------------------------------------------------------
# G-P1 豁免通道：单一构造口 + 形状裁判 + 查侧类型锁（P-S70-4 根修，2026-09-22 席 S100）
# 历史形状：`compute()` 装 (fid, path) 元组、`gp1_findings()` 拿裸 `path` 查表——形状不合
# 不报错、只是**永远匹配不上** ⇒ 门报错文案里"把它加进 G_P1_EXEMPT"这条路按下去无效（现值 0 盖住）。
# 此后：声明条目只准经 `g_p1_exempt_keys` 进通道；查侧 `_validate_gp1_exempt` isinstance 硬校验。
# --------------------------------------------------------------------------
def g_p1_exempt_entry_literal(fid: str, path: str, reason: str = "<理由>") -> str:
    """报错文案里可执行的「下一步」字面量——与查侧键**同源**（前两枚即 `(fid, impl_path)`）。

    它给的那一行就是应当原样加进 `board_placement.G_P1_EXEMPT` 的条目；加完下一跑该条**确实**
    从违规集消失（门 `test_g_p1_exempt_channel_is_alive_end_to_end` 端到端自证）。
    """
    return f"({fid!r}, {path!r}, {reason!r})"


def gp1_exemption_shape_errors(entries: list[Any] | tuple[Any, ...]) -> list[tuple[str, str]]:
    """`G_P1_EXEMPT` 条目级形状裁判：必须是 `(fid, impl_path, 理由)` 三元、三枚皆非空 str、路径字面。

    裸路径（只给 path 不给 fid）／二元／四元／非字符串成员／空理由／通配符／绝对路径／目录兜底
    ⇒ 逐条列问题。**只当尺子不抛错**；抛错拒算的职责在唯一构造口 `g_p1_exempt_keys`。
    """
    problems: list[tuple[str, str]] = []
    for entry in entries:
        if isinstance(entry, str):
            problems.append((entry, "裸路径（G-P1 豁免必须带 fid：(fid, impl_path, 理由) 三元，禁只按路径放行）"))
            continue
        if not isinstance(entry, (tuple, list)) or len(entry) != 3:
            problems.append((str(entry), "不是 (fid, impl_path, 理由) 三元组"))
            continue
        fid, path, reason = entry
        if not all(isinstance(x, str) for x in (fid, path, reason)):
            problems.append((str(entry), "三元组含非字符串成员"))
            continue
        if not fid.strip() or not path.strip():
            problems.append((path, "fid 或 impl_path 为空"))
            continue
        if not reason.strip():
            problems.append((path, "缺理由"))
            continue
        if any(ch in path for ch in "*?[]\\") or path.startswith("/") or ":" in path or path.endswith("/"):
            problems.append((path, "非字面相对路径（禁通配符/绝对路径/目录兜底）"))
    return problems


def g_p1_exempt_keys(entries: list[Any] | tuple[Any, ...]) -> set[tuple[str, str]]:
    """**唯一构造口**：`G_P1_EXEMPT` 声明条目 → 查表键 `(fid, impl_path)` 集合。

    形状不合（`gp1_exemption_shape_errors` 那把尺子）⇒ 立即抛 `PlacementDeclarationError` 拒算
    （fail-closed），坏条目绝不静默流进查侧；错误里给出的修法用
    `g_p1_exempt_entry_literal` 生成，与查侧键同源——照做就真能豁免（简报②）。
    """
    shape = gp1_exemption_shape_errors(entries)
    if shape:
        victim, why = shape[0]
        raise PlacementDeclarationError(
            f"G_P1_EXEMPT 有 {len(shape)} 枚形状不合——唯一构造口拒算（fail-closed）。"
            f"首枚问题：{victim!r} ⇒ {why}。正确形状（原样加进 board_placement.G_P1_EXEMPT 即生效）："
            f"{g_p1_exempt_entry_literal('<fid>', '<impl_path>')}"
        )
    return {(entry[0], entry[1]) for entry in entries}


def _validate_gp1_exempt(exempt: Any) -> None:
    """查侧类型锁（③a 形状锁的运行时腿，不靠运气）：通道只认 `(str, str)` 对的集合。

    形状漂移（裸路径集／列表／含坏键）⇒ 当场抛错点名受害键与唯一构造口——绝不再出现
    "错了不报错、只是永远匹配不上"的死通道（P-S70-4）。
    """
    bad = sorted(
        {repr(k) for k in exempt if not (isinstance(k, tuple) and len(k) == 2 and all(isinstance(x, str) for x in k))}
    )
    if not isinstance(exempt, (set, frozenset)) or bad:
        raise PlacementDeclarationError(
            "G-P1 豁免通道查侧形状不合（应为 (fid, impl_path) 对的集合；裸路径永远匹配不上＝通道无牙）。"
            f"不合键形: {bad[:6]}。唯一构造口: g_p1_exempt_keys；"
            f"修法: 按 {g_p1_exempt_entry_literal('<fid>', '<impl_path>')} 形状把条目加进 board_placement.G_P1_EXEMPT"
        )


# --------------------------------------------------------------------------
# 现算总账（--report 与门共用）
# --------------------------------------------------------------------------
def compute() -> dict[str, Any]:
    placement = load_placement()
    rows = feature_impl_paths()
    claims = flatten_claims(rows)
    universe = py_universe()
    domains = set(registered_domain_roots())
    g_p1_exempt = g_p1_exempt_keys(placement["G_P1_EXEMPT"])  # 唯一构造口，禁第二处 inline（AST 结构锁在门）
    g_p2_exempt = {path for path, _reason in placement["G_P2_EXEMPT"]}
    p1 = gp1_findings(
        rows,
        domains_root=placement["DOMAINS_ROOT"],
        package_root=placement["PACKAGE_ROOT"],
        domain_roots=domains,
        exempt=g_p1_exempt,
    )
    p1["empty_dir_claims"] = empty_plugin_dir_claims(rows, universe, package_root=placement["PACKAGE_ROOT"])
    # 豁免"活得着"附账（G-P2 死豁免锁同型）：每条 G-P1 豁免今天必须真的正吞掉一条越界/未登记域违规，
    # 否则就是死豁免（该摘并降账）。被禁声明 bypass 的条目（先于豁免 continue）不计死。
    banned_now = set(placement["BANNED_CLAIM_PATHS"])
    current_violations = set(p1["outside_domain"]) | set(p1["unknown_domain"])
    g_p1_dead_exempts = sorted(
        f"{fid}|{path}" for fid, path in g_p1_exempt if (fid, path) not in current_violations and path not in banned_now
    )
    a = gp2_findings(claims, universe, g_p2_exempt, semantic="prefix")
    b = gp2_findings(claims, universe, g_p2_exempt, semantic="literal")
    return {
        "counts": {
            "claims": len(claims),
            "features": len(rows),
            "domain_roots": len(domains),
            "scanned_py": len(universe),
            "g_p1_exempt_entries": len(g_p1_exempt),
            "g_p2_exempt_entries": len(g_p2_exempt),
        },
        "g_p1": {k: v for k, v in p1.items()},
        "g_p1_size": {k: len(v) for k, v in p1.items()},
        "g_p1_dead_exempts": g_p1_dead_exempts,
        "g_p2_semantic_a": {"unclaimed": len(a["unclaimed"]), "violations": len(a["violations"])},
        "g_p2_semantic_b": {"unclaimed": len(b["unclaimed"]), "violations": len(b["violations"])},
        "unclaimed_gap_a_b": len(b["unclaimed"]) - len(a["unclaimed"]),
        "exempt_shape_errors": exemption_shape_errors(placement["G_P2_EXEMPT"]),
        "a_unclaimed_list": a["unclaimed"],
        "a_violation_list": a["violations"],
        "stale_exempts": a["stale_exempts"],
        "dead_exempts": a["dead_exempts"],
    }


def report_lines(data: dict[str, Any]) -> list[str]:
    """把现算值排成打印行——**门与 `--report` 共用这一支**（本仓抓到过"总数另算一套"的假绿）。"""
    size = data["g_p1_size"]
    counts = data["counts"]
    a, b = data["g_p2_semantic_a"], data["g_p2_semantic_b"]
    return [
        f"域根（从目录派生）: {counts['domain_roots']}",
        f"扫描 py（plugins/** + 根）: {counts['scanned_py']}",
        f"声明点/二级功能: {counts['claims']} / {counts['features']}",
        (
            "G-P1 违规: "
            f"①越界 {size['outside_domain']} | ①未登记域 {size['unknown_domain']} | "
            f"③字面双认领 {size['double_claim']} | ④同功能重复 {size['duplicate_within']} | "
            f"包内空目录认领 {size['empty_dir_claims']} | 包根禁声明 {size['banned_claims']} | "
            f"附账:包含对 {size['contain_pairs']}"
        ),
        (
            f"G-P1 豁免: {counts['g_p1_exempt_entries']}"
            f"（死豁免 {len(data['g_p1_dead_exempts'])}；构造唯一口 g_p1_exempt_keys，形状不合即拒算，"
            f"修法字面量与查侧键同源）"
        ),
        f"G-P2 语义A: 未认领 {a['unclaimed']} / 违规 {a['violations']}",
        f"G-P2 语义B: 未认领 {b['unclaimed']} / 违规 {b['violations']}",
        f"两语义未认领之差（有限数）: {data['unclaimed_gap_a_b']}",
        (
            f"豁免条数: {counts['g_p2_exempt_entries']}"
            f"（stale {len(data['stale_exempts'])} / 死豁免 {len(data['dead_exempts'])}）"
        ),
        f"豁免形状问题: {len(data['exempt_shape_errors'])}",
    ]


# ==========================================================================
# S11 四本账（物理归位）——一次跑完「域外 py／页级未归位／垫片／名册真债」
# --------------------------------------------------------------------------
# 纪律（本席硬边界＝只读只量、零生产改动）：
#   ① 判据一律**复用既有单一取数口**（`c_table_measure` 的 m_c3/m_c3_git/m_c0c、
#      `spec_gates_census.compute`、`shim_retirement_census.{outside_py,detect_shims,three_states,
#      load_ledger_rows,computed_refs}`、`tests/test_legacy_shim_import_ratchet` 的两本账），
#      本块**绝不复制判定逻辑**（禁第二真身）。上面 G-P1/G-P2/compute/relocate_* 一字未动，
#      三把常驻门（`test_physical_placement_gate` / `test_placement_relocate_split_lock` /
#      `test_file_package_dotted_vs_stdlib`）对本件的 import 与 AST 形状锁全部照旧成立。
#   ② 每本账给「起点值／现算值／带符号差」，起点值一律**现解析**自本波 BASELINE.md（回贴行号）或
#      各棘轮件的在册常数，实测值一律调真身现算——脚本绝不把字面数字写进实测列。
#   ③ 域外 py 强制双尺交叉：磁盘尺（rglob/find）∥ git 尺（`git ls-files` + `git status --porcelain`
#      复原工作树口径），两尺不一致**必须显式报不一致数与逐条差集**，并按 untracked / deleted /
#      大小写归一 分形归因（历史上「NTFS 大小写」「未跟踪件」「gitfile 指向 Runtime」皆造过单尺假账）。
#   ④ 全表禁「达标」二字；起点数值==实测数值一律判「未做」；方向 down（越小越好），
#      带符号差＝实测−起点，负数记「较起点改善」、正数记「较起点退步」。
#   ⑤ 任一真身读不出来 ⇒ 该格降级「不可判（缺证据/读失败）」并点名原因，绝不折零、绝不崩。
#   复现（与本仓 c_table_measure 同一环境咒语）：
#     PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
#       ../ChatBot_Runtime/venv/Scripts/python.exe scripts/physical_placement_census.py --four-accounts
# ==========================================================================
_WAVE_DIR = REPO_ROOT / ".superpowers" / "sdd" / "2026-09-24-central-dispatch"
_S11_BASELINE = _WAVE_DIR / "BASELINE.md"
_S11_SHIM_RATCHET = REPO_ROOT / "tests/test_legacy_shim_import_ratchet.py"


def _s11_board_ledger_path() -> Path:
    """台账路径**唯一取自真身声明** `shim_retirement_census.LEDGER_PY`（S118：不再抄第二份字面量）。

    旧写法在本件里另写死一遍 `plugins/.../domains/core/board_shim_ledger.py`。真身搬家（P2 退役/物理
    归位正是干这个的）时，取数口跟着改、这本抄件不跟 ⇒ 第④本账会去读一枚**不存在或已废弃**的旧路径，
    读失败被 a4 的兜底 except 压成一行"取数失败"，而账面看起来只是"这格不可判"——又一例路径读点各说各话。
    延迟 import（本件被 `shim_retirement_census` 反向 import，模块级 import 会成环）。
    """
    import shim_retirement_census as src

    return src.LEDGER_PY


def _s11_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _s11_run_git(args: list[str], timeout: int = 90) -> Any:
    # cwd=REPO_ROOT：本仓 .git 是 gitfile 指向 ../ChatBot_Runtime/git，显式钉 cwd 防目录漂移
    import subprocess

    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, cwd=str(REPO_ROOT), check=False,
    )


def _s11_load_test_ruler(name: str, path: Path):
    """内存加载既有门件取判据（同 c_table_measure::m_c9_gate 手法），不 import 插件包。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"取不到判据真身：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _s11_start_from_baseline(*patterns: str) -> dict[str, Any]:
    """现解析本波 BASELINE.md 的起点数（回贴行号）；命中失败 → (None, 原因)。"""
    import re

    if not _S11_BASELINE.exists():
        return {"found": False, "why": f"起点册不存在：{_S11_BASELINE}"}
    lines = _s11_read(_S11_BASELINE).splitlines()
    for idx, line in enumerate(lines):
        for rx in patterns:
            m = re.search(rx, line)
            if m:
                nums = [int(g) for g in m.groups() if g is not None and g.isdigit()]
                return {"found": True, "line": idx + 1, "raw": line.strip()[:90], "nums": nums}
    return {"found": False, "why": f"起点册内未锚到（样式 {patterns}）"}


def _s11_literal_from_ledger(names: set[str]) -> dict[str, Any]:
    """AST 静态读 `board_shim_ledger.py` 顶层整数字面量（不 import 包，防拖起 NoneBot 初始化）。"""
    import ast

    out: dict[str, Any] = {}
    tree = ast.parse(_s11_read(_s11_board_ledger_path()))
    for node in tree.body:
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for t in targets:
            if isinstance(t, ast.Name) and t.id in names and isinstance(node.value, ast.Constant):
                out[t.id] = node.value.value
    return out


def _s11_find_outside_set() -> set[str]:
    import shim_retirement_census as src

    return set(src.outside_py())  # 唯一域外尺：plugins/** 不在 domains/ 下（与 m_c3 同判据）


def _s11_git_outside_sets() -> tuple[set[str], set[str], set[str]]:
    """git 尺三集合：tracked(ls-files) / untracked(porcelain `??`) / deleted(porcelain `D`)，
    一律只取 `plugins/` 下、`.py`、且在**声明的** `DOMAINS_ROOT` 前缀之外（与磁盘尺同判据谓词）。"""
    import re

    # 域外判据与磁盘尺（`shim_retirement_census.outside_py`）**同源**：都用 `board_placement.DOMAINS_ROOT`
    # 这一枚声明前缀走 `_under`。旧写法在这里另抄了一份**路径形状**规则 `"/domains/" not in "/"+rel`——
    # 声明一改（域根搬家/改名）或仓里出现第二处 `…/domains/…` 目录（如 `plugins/x/domains/`、
    # `plugins/bot_unified_runtime/domains_backup/`），两把尺就会各数各的，而这本账要报的恰恰是两尺之差。
    domains_root = str(load_placement()["DOMAINS_ROOT"])

    def _is_outside_py(rel: str) -> bool:
        return rel.startswith("plugins/") and rel.endswith(".py") and not _under(rel, domains_root)

    ls = _s11_run_git(["ls-files", "plugins"], 90)
    tracked = {f for f in ls.stdout.splitlines() if _is_outside_py(f)}
    untracked: set[str] = set()
    deleted: set[str] = set()
    st = _s11_run_git(["status", "--porcelain"], 90)
    for line in st.stdout.splitlines():
        if len(line) < 4:
            continue
        xy, pathspec = line[:2], line[3:]
        if " -> " in pathspec:  # rename：取箭头右侧（工作树形态）
            pathspec = pathspec.split(" -> ", 1)[1]
        pathspec = pathspec.strip().strip('"').replace("\\", "/")
        if not _is_outside_py(pathspec):
            continue
        if "?" in xy:
            untracked.add(pathspec)
        if re.search(r"[D]", xy) or "U" in xy:
            deleted.add(pathspec)
    # 工作树口径 = tracked − deleted + untracked（present-on-disk 的 git 视图）
    worktree = (tracked - deleted) | untracked
    return tracked, worktree, deleted | untracked


def _s11_classify_diff(only: set[str], other_ci: dict[str, str], untracked: set[str]) -> dict[str, list[str]]:
    """把「只在此尺、不在彼尺」的差集按成因分形：未跟踪 / 大小写归一伪差 / 其它（含已删仍被跟踪、被移走）。"""
    buckets: dict[str, list[str]] = {"case_only": [], "untracked": [], "other": []}
    for item in sorted(only):
        low = item.lower()
        if low in other_ci and other_ci[low] != item:
            buckets["case_only"].append(item)
        elif item in untracked:
            buckets["untracked"].append(item)
        else:
            buckets["other"].append(item)
    return buckets


def _named_snapshot(items: Any, *, scalar: Any, display_limit: int | None = None) -> dict[str, Any]:
    """把一份账的**具名全集**编成可逐枚点名的快照，落进既有 JSON 结构（不另起第二本账本文件）。

    反截断教义（S96，承 S87 Q-A：面B 160→170 的 +10「看得见数看不见名」根因＝账只存 `len()`）：
    - `items` 一律**全量入册**——取证不截断；`count` 恒等全集长度，`matches_scalar` 断言快照与标量账
      逐值对得上（不等＝要么动到了判据、要么快照漏抄，两种都该红）。
    - `display_limit` 只截**展示**用的 `head`；截了一定标 `truncated=True`。`items` 永远是全集，
      `truncated` 只描述 `head`，绝不用它去糊 `count`（"截断只准截展示，不准截取证"）。
    - `items is None`（尺取数失败）→ 诚实 `available=False`，绝不以空清单冒充"零成员"（P-S60-2 同族：
      把"读不到"当"空"是账具失明，不是零）。
    """
    if items is None:
        return {"available": False, "count": None, "matches_scalar": None, "items": None,
                "note": "尺取数失败，具名快照不可得（诚实降级，不以空清单冒充无成员）"}
    ordered = sorted(str(x) for x in items)
    snap: dict[str, Any] = {
        "available": True,
        "count": len(ordered),
        "matches_scalar": (len(ordered) == scalar),
        "scalar": scalar,
        "items": ordered,
    }
    if display_limit is not None:
        snap["head"] = ordered[:display_limit]
        snap["truncated"] = len(ordered) > display_limit
    return snap


def _edge_snapshot(edges: dict[str, int]) -> dict[str, Any]:
    """垫片两本账的具名快照：边是 `{文件: 条数}`，标量账是 `sum(条数)`。
    全量入册（取证不截断），并额外报**成员名**（谁还挂着垫片边）——`top_files` 的 `[:5]` 降为纯展示。"""
    ordered = sorted(edges.items())
    return {
        "available": True,
        "members": len(ordered),          # 挂着边的文件数（成员）
        "sum_edges": sum(edges.values()),  # 边总数（== 该账 current 标量）
        "edges": [[k, v] for k, v in ordered],
    }


def _snapshot_integrity(acct: dict[str, Any]) -> dict[str, Any]:
    """反截断 / 反空账的**可执法判据**：逐本账核具名快照与标量账是否逐值对得上、展示截断是否显式标注、
    取证全集是否被裁。任一不符即列入 `problems`（消费方/门据此判红；本函数只报不修，绝不为过门改标量）。

    牙齿三形（对应 S96 注毒三发）：
    ① 快照被清空/截断到少数 → `len(items) != count` 或 `count != scalar`；
    ② 净增里塞一枚不存在的名字 → `count != scalar`（多出来）；
    ③ 快照出口退回只存标量 → 该账 `names`/`edges_full` 槽位缺失。
    """
    problems: list[str] = []

    def _check_named(tag: str, snap: Any, scalar: Any) -> None:
        if not isinstance(snap, dict):
            problems.append(f"{tag}: 具名快照槽缺失（只存标量的旧形态复辟）")
            return
        if not snap.get("available"):
            return  # 尺取数失败已诚实标 available=False，非快照造假
        items = snap.get("items")
        if not isinstance(items, list):
            problems.append(f"{tag}: items 非全集数组")
            return
        if snap.get("count") != len(items):
            problems.append(f"{tag}: count={snap.get('count')} ≠ len(items)={len(items)}（取证被裁）")
        if snap.get("count") != scalar:
            problems.append(f"{tag}: count={snap.get('count')} ≠ 标量账={scalar}（快照与账不符）")
        if snap.get("truncated") and len(items) != snap.get("count"):
            problems.append(f"{tag}: 标了 truncated 但全集 items 也被裁（截断只准截展示 head）")

    a1 = acct.get("a1_outside_py_dual_ruler") or {}
    cur1 = a1.get("current")
    for slot in ("find_disk", "git_ls_files", "git_worktree_reconciled"):
        # find_disk 须等 current；其余两尺各自的 count 已在 rulers 里，快照 scalar 用 len 自证。
        _check_named(f"a1.names.{slot}", (a1.get("names") or {}).get(slot),
                     cur1 if slot == "find_disk" else (a1.get("rulers", {}).get(slot, {}) or {}).get("count"))

    a2 = acct.get("a2_page_unplaced") or {}
    cur2 = a2.get("current") or {}
    a2n = a2.get("names") or {}
    _check_named("a2.names.t3_managed", a2n.get("t3_managed"), cur2.get("面A_managed"))
    _check_named("a2.names.t3_unmoved", a2n.get("t3_unmoved"), cur2.get("面B_unmoved"))

    a3 = acct.get("a3_shims_two_ledgers") or {}
    for led in ("prod_ledger", "tests_ledger"):
        L = a3.get(led) or {}
        ef = L.get("edges_full")
        if not isinstance(ef, dict):
            problems.append(f"a3.{led}.edges_full: 具名快照槽缺失（垫片边只报 top_files[:5] 的旧形态复辟）")
            continue
        if ef.get("sum_edges") != L.get("current"):
            problems.append(f"a3.{led}.edges_full.sum_edges={ef.get('sum_edges')} ≠ current={L.get('current')}")
        if len(ef.get("edges") or []) != ef.get("members"):
            problems.append(f"a3.{led}.edges_full: edges 全集长度 ≠ members（边取证被裁）")
        if ef.get("members", 0) > 5 and not L.get("top_files_truncated"):
            problems.append(f"a3.{led}: top_files 截到 5 却没标 top_files_truncated（展示截断未显式化）")

    a4 = acct.get("a4_roster_vs_real_debt") or {}
    a4n = a4.get("names") or {}
    _check_named("a4.names.roster", a4n.get("roster"), a4.get("roster_count"))
    _check_named("a4.names.real_debt", a4n.get("real_debt"), a4.get("real_count"))

    return {"ok": not problems, "problems": problems}


def compute_four_accounts() -> dict[str, Any]:
    """四本账一次跑完（起点／现算／带符号差；①双尺交叉；④名册真债双向差集）。"""
    import datetime

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    acct: dict[str, Any] = {}

    def _verdict(start: int | None, measured: int | None) -> tuple[str, int | None]:
        if start is None or measured is None:
            return ("不可判（缺证据/读失败）", None)
        if measured == start:
            return ("未做（起点==实测）", 0)
        delta = measured - start
        word = "改善" if delta < 0 else "退步"
        sign = f"{'−' if delta < 0 else '+'}{abs(delta)}"
        return (f"较起点{word} {sign}（{start}→{measured}）", delta)

    # ---------------------------------------------------------------- ① 域外 py（双尺）
    try:
        start1 = _s11_start_from_baseline(r"域外 py.*?\|\s*(\d+)", r"域外.*?(\d+)\s*∥")
        s1 = start1["nums"][0] if start1.get("found") and start1["nums"] else None
    except Exception as exc:  # noqa: BLE001
        start1, s1 = {"found": False, "why": f"{type(exc).__name__}: {exc}"}, None
    find_set: set[str] | None = None
    git_tracked: set[str] | None = None
    git_worktree: set[str] | None = None
    git_reconcile: set[str] | None = None
    acct_error_1: Any = None
    m_c3: Any = None
    m_c3_git: Any = None
    try:
        import c_table_measure as c

        m_c3, m_c3_git = int(c.m_c3()), int(c.m_c3_git())
    except Exception as exc:  # noqa: BLE001
        m_c3 = f"读失败 {type(exc).__name__}: {exc}"
    try:
        find_set = _s11_find_outside_set()
        git_tracked, git_worktree, git_reconcile = _s11_git_outside_sets()
    except Exception as exc:  # noqa: BLE001
        acct_error_1 = f"{type(exc).__name__}: {exc}"
    else:
        acct_error_1 = None

    a1: dict[str, Any] = {
        "start": s1,
        "start_anchor": start1,
        "rulers": {
            "find_disk": {"count": None if find_set is None else len(find_set),
                           "crosscheck_c_table_m_c3": m_c3,
                           "command": "find plugins -name '*.py' -not -path '*/domains/*' | wc -l  # 尺＝scripts/c_table_measure.py::m_c3"},
            "git_ls_files": {"count": None if git_tracked is None else len(git_tracked),
                             "crosscheck_c_table_m_c3_git": m_c3_git,
                             "command": "git ls-files plugins | grep '\\.py$' | grep -v '/domains/' | wc -l  # 尺＝c_table_measure.py::m_c3_git"},
            "git_worktree_reconciled": {"count": None if git_worktree is None else len(git_worktree),
                                        "command": "git ls-files ∪ (git status --porcelain ??) − deleted"},
        },
        "dual_ruler_error": acct_error_1,
        "note_gitdir": "本仓 .git 为 gitfile→../ChatBot_Runtime/git；命令一律钉 cwd=REPO_ROOT",
    }
    if find_set is not None and git_tracked is not None:
        only_find = find_set - git_tracked
        only_git = git_tracked - find_set
        ci_git = {p.lower(): p for p in git_tracked}
        ci_find = {p.lower(): p for p in find_set}
        a1["mismatch_count"] = len(only_find) + len(only_git)
        a1["consistent"] = not only_find and not only_git
        a1["only_in_find"] = _s11_classify_diff(only_find, ci_git, git_reconcile or set())
        a1["only_in_git"] = _s11_classify_diff(only_git, ci_find, set())
        primary = len(find_set)
        v, d = _verdict(s1, primary)
        a1["current"] = primary
        a1["signed_delta_vs_start"] = d
        a1["verdict"] = v
        # 具名快照（S96）：三把尺各存全集，使「今值−基线」净增项可逐枚点名；标量口径一律不动。
        a1["names"] = {
            "find_disk": _named_snapshot(find_set, scalar=primary),
            "git_ls_files": _named_snapshot(git_tracked, scalar=len(git_tracked)),
            "git_worktree_reconciled": _named_snapshot(git_worktree, scalar=len(git_worktree or ())),
        }
    else:
        a1["current"] = None
        a1["verdict"] = "不可判（双尺至少一把取不到）"
        a1["names"] = {k: _named_snapshot(v, scalar=None) for k, v in
                       (("find_disk", find_set), ("git_ls_files", git_tracked),
                        ("git_worktree_reconciled", git_worktree))}
    acct["a1_outside_py_dual_ruler"] = a1

    # ---------------------------------------------------------------- ② 页级未归位（面A/面B）
    try:
        start2 = _s11_start_from_baseline(r"面A／面B\s*\|\s*(\d+).*?／(\d+)")
        s2a = start2["nums"][0] if start2.get("found") and len(start2["nums"]) >= 1 else None
        s2b = start2["nums"][1] if start2.get("found") and len(start2["nums"]) >= 2 else None
    except Exception as exc:  # noqa: BLE001
        start2, s2a, s2b = {"found": False, "why": str(exc)}, None, None
    a2: dict[str, Any] = {"start": {"面A_managed": s2a, "面B_unmoved": s2b}, "start_anchor": start2}
    try:
        import spec_gates_census as sgc

        res = sgc.compute(REPO_ROOT)
        cur_a = len(res["t3_managed"])
        cur_b = len(res["t3_unmoved"])
        a2["current"] = {"面A_managed": cur_a, "面B_unmoved": cur_b}
        va, da = _verdict(s2a, cur_a)
        vb, db = _verdict(s2b, cur_b)
        a2["signed_delta_vs_start"] = {"面A_managed": da, "面B_unmoved": db}
        a2["verdict"] = {"面A_managed": va, "面B_unmoved": vb}
        a2["ruler"] = "scripts/spec_gates_census.py::compute()['t3_managed'/'t3_unmoved']（与 BASELINE 同行）"
        # 具名快照（S96，承 S87 Q-A）：面A 逐行、面B 逐页都全量入册，令"+N/−N"可逐枚 diff；
        # 底层 res 本就产全名，旧账只存 len() 才致面B +10 到名不可判。计数仍走 current，此处不改标量。
        a2["names"] = {
            "t3_managed": _named_snapshot(res["t3_managed"], scalar=cur_a),
            "t3_unmoved": _named_snapshot(res["t3_unmoved"], scalar=cur_b),
        }
    except Exception as exc:  # noqa: BLE001
        a2["current"] = None
        a2["verdict"] = f"不可判（spec_gates_census 读失败 {type(exc).__name__}: {exc}）"
        a2["names"] = {"t3_managed": _named_snapshot(None, scalar=None),
                       "t3_unmoved": _named_snapshot(None, scalar=None)}
    # 附尺（另一把「页级」尺，如实并列、不与面A/面B混算）：G-P2 未认领 py
    try:
        gp2 = compute()["g_p2_semantic_a"]
        a2["adjacent_ruler_gp2_unclaimed_py"] = {"unclaimed": gp2["unclaimed"], "violations": gp2["violations"]}
    except Exception as exc:  # noqa: BLE001
        a2["adjacent_ruler_gp2_unclaimed_py"] = f"读失败 {type(exc).__name__}: {exc}"
    acct["a2_page_unplaced"] = a2

    # ---------------------------------------------------------------- ③ 垫片（两本独立账，各只准降）
    a3: dict[str, Any] = {}
    try:
        ratch = _s11_load_test_ruler("tsr", _S11_SHIM_RATCHET)
        prod_edges = ratch.collect_legacy_shim_edges()
        tests_edges = ratch.collect_tests_legacy_shim_edges()
        prod_cur = sum(prod_edges.values())
        tests_cur = sum(tests_edges.values())
        prod_start = int(ratch.SHIM_EDGE_CEILING)
        tests_start = int(ratch.TESTS_SHIM_EDGE_CEILING)
        prod_last = int(ratch.AUDIT_HISTORY[-1][1])
        tests_last = int(ratch.TESTS_AUDIT_HISTORY[-1][1])
        vp, dp = _verdict(prod_start, prod_cur)
        vt, dt = _verdict(tests_start, tests_cur)
        a3["prod_ledger"] = {"start_ceiling": prod_start, "last_audit": prod_last,
                             "current": prod_cur, "signed_delta_vs_ceiling": dp, "verdict": vp,
                             "top_files": sorted(prod_edges.items(), key=lambda kv: -kv[1])[:5]}
        a3["tests_ledger"] = {"start_ceiling": tests_start, "last_audit": tests_last,
                              "current": tests_cur, "signed_delta_vs_ceiling": dt, "verdict": vt,
                              "top_files": sorted(tests_edges.items(), key=lambda kv: -kv[1])[:5]}
        # 反截断（S96）：top_files 的 [:5] 只是展示，取证全量另入 edges_full；
        # 一旦成员多于 5 就显式标 truncated=True，杜绝"数看得见、名看不见"。标量 current 不动。
        a3["prod_ledger"]["edges_full"] = _edge_snapshot(prod_edges)
        a3["prod_ledger"]["top_files_truncated"] = len(prod_edges) > 5
        a3["tests_ledger"]["edges_full"] = _edge_snapshot(tests_edges)
        a3["tests_ledger"]["top_files_truncated"] = len(tests_edges) > 5
        overlap = sorted(set(prod_edges) & set(tests_edges))
        a3["separation_lock"] = {"disjoint": not overlap, "overlap": overlap,
                                 "note": "两本账扫描根必须互斥（斥离锁 test_two_ledgers_are_disjoint）"}
        # 代理指标尺（存在≠活性）：在册待退役清单长度 / 磁盘上真存在的活垫片叶 / 五目录标记文件数
        markers: Any = None
        try:
            import c_table_measure as c

            markers = int(c.m_c0c())
        except Exception as exc:  # noqa: BLE001
            markers = f"读失败 {exc}"
        a3["proxy_indicators"] = {
            "shim_marker_files_m_c0c": markers,
            "live_shim_leaves": len(ratch.live_shim_leaves()),
            "ruler": "c_table_measure.py::m_c0c（标记 py 数）与 live_shim_leaves（磁盘存在垫片叶名数）——均**存在性代理**，非活性结论",
            "warning": (
                "禁把「标记文件还在」当「垫片边还在」；import-edge 账才是活性判据"
                f"（现 prod={prod_cur}/tests={tests_cur}）"
            ),
        }
        try:
            mstart = _s11_start_from_baseline(r"垫片标记 py（五目录）\s*\|\s*(\d+)")
            a3["m_c0c_start"] = mstart["nums"][0] if mstart.get("found") and mstart["nums"] else None
        except Exception:  # noqa: BLE001
            a3["m_c0c_start"] = None
    except Exception as exc:  # noqa: BLE001
        a3["error"] = f"垫片两本账取数失败 {type(exc).__name__}: {exc}"
        a3["verdict"] = "不可判（缺证据）"
    acct["a3_shims_two_ledgers"] = a3

    # ---------------------------------------------------------------- ④ 名册与真债差集（双向）
    a4: dict[str, Any] = {}
    try:
        import shim_retirement_census as src

        roster_rows = src.load_ledger_rows()  # 在册名册（SHIM_ROWS：垫片 path 全集）
        roster = {str(r["path"]) for r in roster_rows}
        real = set(src.three_states()["retire_shims"])  # 本轮实测真债（磁盘上合格的活垫片）
        paid_off = sorted(roster - real)     # (a) 在册已还清 → 该降基线
        blind = sorted(real - roster)        # (b) 不在册却是真债 → 门瞎
        a4["roster_count"] = len(roster)
        a4["real_count"] = len(real)
        a4["in_roster_paid_off"] = paid_off
        a4["real_not_in_roster"] = blind
        # (c) 代理指标型：真债里「存在但零活性」的（computed_refs==0 ⇒ 没人 import，不是活跃债）
        not_alive = []
        for p in sorted(real):
            try:
                refs = src.computed_refs(p)
            except Exception as exc:  # noqa: BLE001
                not_alive.append({"path": p, "refs": f"读失败 {type(exc).__name__}"})
                continue
            if refs == 0:
                not_alive.append({"path": p, "refs": 0})
        a4["existence_not_alive"] = not_alive
        a4["register_baselines"] = _s11_literal_from_ledger({"OUTSIDE_BASELINE", "SHIM_RETIRE_BASELINE"})
        # 具名快照（S96）：名册与真债两套全量入册，使在册/真债的净增项可逐枚点名（差集账本就有名，
        # 但 roster_count/real_count 两标量此前无名册可对）。计数仍走既有 *_count，此处不改标量。
        a4["names"] = {"roster": _named_snapshot(roster, scalar=len(roster)),
                       "real_debt": _named_snapshot(real, scalar=len(real))}
        a4["verdict"] = {
            "paid_off_count": len(paid_off),
            "blind_count": len(blind),
            "not_alive_count": len(not_alive),
            "summary": "在册−真债=已还清(该降基线)；真债−在册=门瞎；真债∧零活性=存在≠活性(代理)",
        }
    except Exception as exc:  # noqa: BLE001
        a4["error"] = f"名册真债差集取数失败 {type(exc).__name__}: {exc}"
        a4["verdict"] = "不可判（缺证据）"
    acct["a4_roster_vs_real_debt"] = a4

    return {"stamp_utc": stamp, "baseline_source": _S11_BASELINE.relative_to(REPO_ROOT).as_posix(),
            "accounts": acct, "snapshot_integrity": _snapshot_integrity(acct)}


def _s11_four_lines(data: dict[str, Any]) -> list[str]:
    """把四本账排成人读行（机读走 --four-accounts 的 JSON）。"""
    out: list[str] = [f"取数时刻(UTC)：{data['stamp_utc']}  起点册：{data['baseline_source']}"]
    acc = data["accounts"]
    a1 = acc["a1_outside_py_dual_ruler"]
    r = a1["rulers"]
    out.append(
        f"① 域外 py：起点={a1.get('start')} 磁盘尺={r['find_disk']['count']} git-tracked尺={r['git_ls_files']['count']} "
        f"git-工作树尺={r['git_worktree_reconciled']['count']} 判定={a1.get('verdict')}"
    )
    if a1.get("dual_ruler_error"):
        out.append(f"   ⚠ 双尺取数异常：{a1['dual_ruler_error']}")
    else:
        out.append(f"   双尺一致={a1.get('consistent')} 不一致数={a1.get('mismatch_count')}")
        for tag, key in (("只在磁盘(未跟踪/大小写/被移走)", "only_in_find"), ("只在git(已删仍跟踪/大小写/移动未记)", "only_in_git")):
            b = a1.get(key) or {}
            out.append(f"   {tag}：case_only={len(b.get('case_only',[]))} untracked={len(b.get('untracked',[]))} other={len(b.get('other',[]))}")
    a2 = acc["a2_page_unplaced"]
    cur2 = a2.get("current")
    out.append(f"② 页级未归位：起点 面A={a2['start']['面A_managed']} 面B={a2['start']['面B_unmoved']} 现算 {cur2} 判定 {a2.get('verdict')}")
    a3 = acc["a3_shims_two_ledgers"]
    if "prod_ledger" in a3:
        out.append(
            f"③ 垫片（两本独立账·各只准降）：生产侧 上限{a3['prod_ledger']['start_ceiling']}/末记{a3['prod_ledger']['last_audit']} "
            f"→现算 {a3['prod_ledger']['current']}（{a3['prod_ledger']['verdict']}）；"
            f"测试侧 上限{a3['tests_ledger']['start_ceiling']}/末记{a3['tests_ledger']['last_audit']} →现算 {a3['tests_ledger']['current']}（{a3['tests_ledger']['verdict']}）"
        )
        out.append(f"   斥离锁 disjoint={a3['separation_lock']['disjoint']} 交集={a3['separation_lock']['overlap']}")
        px = a3.get("proxy_indicators", {})
        out.append(f"   代理指标（存在≠活性，禁当结论）：标记文件={px.get('shim_marker_files_m_c0c')} 活垫片叶={px.get('live_shim_leaves')}")
    else:
        out.append(f"③ 垫片：{a3.get('verdict','不可判')} {a3.get('error','')}")
    a4 = acc["a4_roster_vs_real_debt"]
    if "roster_count" in a4:
        v = a4["verdict"]
        out.append(
            f"④ 名册真债差集：名册={a4['roster_count']} 真债={a4['real_count']} "
            f"(a)在册已还清={v['paid_off_count']} (b)门瞎={v['blind_count']} (c)存在零活性={v['not_alive_count']}  在册基线={a4.get('register_baselines')}"
        )
    else:
        out.append(f"④ 名册真债：{a4.get('verdict','不可判')} {a4.get('error','')}")
    integ = data.get("snapshot_integrity") or {}
    if integ.get("ok"):
        out.append("⑤ 具名快照体检（S96）：OK —— 四本账快照逐值对上标量、展示截断已显式标、取证全集未被裁")
    else:
        out.append(f"⑤ 具名快照体检（S96）：DIRTY —— {integ.get('problems')}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="打印两扇门的现算值")
    parser.add_argument("--json", metavar="OUT", help="把明细写成 JSON（写到指定路径，不落源码树默认位置）")
    parser.add_argument("--four-accounts", action="store_true",
                        help="S11 四本账（域外py双尺／页级未归位／垫片两本账／名册真债差集）——JSON 打到 stdout")
    parser.add_argument("--four-accounts-out", metavar="OUT", help="四本账 JSON 落盘到指定路径（不落源码树默认位置）")
    parser.add_argument("--four-accounts-human", action="store_true", help="四本账打印成人读行（配合 --four-accounts 时并入 stderr 前）")
    args = parser.parse_args()
    if args.four_accounts or args.four_accounts_out:
        four = compute_four_accounts()
        if args.four_accounts_human or args.four_accounts_out:
            for line in _s11_four_lines(four):
                print(line, file=sys.stderr)
        if args.four_accounts:
            print(json.dumps(four, ensure_ascii=False, indent=1))
        if args.four_accounts_out:
            Path(args.four_accounts_out).write_text(json.dumps(four, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"四本账明细已写: {args.four_accounts_out}", file=sys.stderr)
        return 0
    data = compute()
    for line in report_lines(data):
        print(line)
    if args.json:
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"明细已写: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
