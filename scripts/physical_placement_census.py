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
def _read_literals(source: str, names: set[str]) -> dict[str, Any]:
    tree = ast.parse(source)
    out: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if target.id in names and node.value is not None:
                try:
                    out[target.id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    out[target.id] = None
    return out


def load_placement() -> dict[str, Any]:
    """物理归位门的声明数据（白名单前缀 + 枚举字面豁免清单）。"""
    names = {"DOMAINS_ROOT", "PACKAGE_ROOT", "BANNED_CLAIM_PATHS", "G_P1_EXEMPT", "G_P2_EXEMPT"}
    data = _read_literals(PLACEMENT_PY.read_text(encoding="utf-8"), names)
    missing = sorted(names - set(data))
    assert not missing, f"board_placement.py 缺声明 {missing}——取数口不接受静默补空值"
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
    """
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
            if path in exempt:
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
# 现算总账（--report 与门共用）
# --------------------------------------------------------------------------
def compute() -> dict[str, Any]:
    placement = load_placement()
    rows = feature_impl_paths()
    claims = flatten_claims(rows)
    universe = py_universe()
    domains = set(registered_domain_roots())
    g_p1_exempt = {(fid, path) for fid, path, _reason in placement["G_P1_EXEMPT"]}
    g_p2_exempt = {path for path, _reason in placement["G_P2_EXEMPT"]}
    p1 = gp1_findings(
        rows,
        domains_root=placement["DOMAINS_ROOT"],
        package_root=placement["PACKAGE_ROOT"],
        domain_roots=domains,
        exempt=g_p1_exempt,
    )
    p1["empty_dir_claims"] = empty_plugin_dir_claims(rows, universe, package_root=placement["PACKAGE_ROOT"])
    a = gp2_findings(claims, universe, g_p2_exempt, semantic="prefix")
    b = gp2_findings(claims, universe, g_p2_exempt, semantic="literal")
    return {
        "counts": {
            "claims": len(claims),
            "features": len(rows),
            "domain_roots": len(domains),
            "scanned_py": len(universe),
            "g_p2_exempt_entries": len(g_p2_exempt),
        },
        "g_p1": {k: v for k, v in p1.items()},
        "g_p1_size": {k: len(v) for k, v in p1.items()},
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
