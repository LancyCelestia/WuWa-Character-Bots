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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="打印两扇门的现算值")
    parser.add_argument("--json", metavar="OUT", help="把明细写成 JSON（写到指定路径，不落源码树默认位置）")
    args = parser.parse_args()
    data = compute()
    for line in report_lines(data):
        print(line)
    if args.json:
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"明细已写: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
