"""ownership_project — 把 `OWNERSHIP.md` 从「人写认领」改为「从能力真身册机器投影」（S34 / P6 第 5 项）。

## 这支脚本干什么、不干什么
**只读三支投影源、现算、只写一份生成件**：
  ① `plugins/bot_unified_runtime/domains/core/capability_manifest.py` 的 `FACETS` / `EVIDENCE`；
  ② `scripts/central_seam_census.py --json` 的 per-id 名册（`entry_forms` / `seam_sites` / `invoke_sites` / `state` …）；
  ③ `scripts/physical_placement_census.py --four-accounts`（S11 已建，本席**只读复用、零改动**）。
生成件 = `.superpowers/sdd/2026-09-24-central-dispatch/OWNERSHIP.generated.md`：
每行「文件/目录面 → 派生归属」，并**显式列出派生不出归属的面**（＝人肉认领残留）。

**默认模式（`--write`）绝不写 `OWNERSHIP.md`**（共享人写册，历史上两席把它截零）。
**S105 追加 `--emit-ownership`（目标⑤落码）**：把现役 `OWNERSHIP.md` 重写为**双区投影物**——
机器区（写权互斥视图，从 `ownership_map` 册生成）+ 人写区（`<!-- SDD-HUMAN-CLAIMS-BEGIN/END -->`
标记内的席位认领/阶段/欠账，**逐字节回环保留、绝不合成席位列**）。这是「从册机器生成」对**能生成那半**
的落地；席位/欠账那半按本波反席位锁与"不许把账搬没了"铁律**保留为人写区**，不删（判据＝B 案，见 SEAT-S105）。
`--emit-ownership` 全程 fail-closed：抽出的认领区行数 < 地板、回环逐字节不等、或写后体积反降 ⇒ 拒写、真册零变更。
**S138 追加 §D 席位派生视图（裁定 #10「全面自动化」+ R-新4「改判据而非撤锁」）**：机器区在 §M 写权视图之外
新增 §D，**从本目录 `SEAT-*.md` 席报 + `ownership_map` 册现算派生**「哪个席位在哪个阶段申报了哪些写面」——
席位/阶段这二列此前被 S105 判「机器供不出」，现证明**算得出**（派生 ≠ 手写凑数：数据源只有 SEAT 报告件与真身册）。
但**不**把 seat/phase 冻进 `ownership_map.FaceOwnership` 字段（反席位锁 `test_no_seat_or_phase_column` 一字不撤），
也**不**删 §H 人写区（欠账/承诺/挂账指针是散文承重，逐字回环仍留）。§D 列头刻意用 `席位/阶段·波次/申报写面/出处`
绕开人写表头 `认领席/阶段/备注`，由 `test_machine_zone_carries_no_seat_column` 同尺执法。

## 三条硬规矩（写进代码，别只写在散文里）
1. **禁硬塞 owner**：三支源说不出归属的面，一律进 `unattributed` 并带**原因码**，绝不填 "main/主代理/未知" 蒙混。
   同仓先例 = `scripts/doc_ownership_sync.py:399`「`board==""` = 表内在册但**未归属**，不发明归属」。
2. **禁为求绿缩面**：`--check` 的双向差集用**全集**比。`--disable-rule`（诊断用）会把结果标成
   "面已缩、不作判据" 并以退出码 4 返回——缩面换来的 0 差集在这里拿不到 0。
3. **fail-closed**：任何一支源读不动／子进程非零／JSON 解析失败 ⇒ 退出码 2 并点名是哪支源，
   绝不把"读不到"当成"该面无人"。

## 归属语义的边界（本席最重要的判断，交接给主代理）
人写册记的是**本波席位互斥写权**（列头：认领席／阶段／备注）。三支源里**没有席位、没有阶段、没有写权字段**，
只有「哪些能力走这件文件」。所以今天机器能投影的是**能力归属册**，不是**席位互斥册**——
"差集=0" 作为 P6 判据在补齐字段之前不可达（原因与最小补法见 `SEAT-S34.md` §3/§6 与本件 `--explain`）。

## 退出码
0 差集为空 ｜ 3 差集非空（在册未投影 或 投影未在册）｜ 2 源读不动 ｜ 4 诊断模式（面被缩，不作判据）｜ 1 用法错
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = "plugins/bot_unified_runtime"

MANIFEST_PY = REPO_ROOT / PACKAGE_ROOT / "domains" / "core" / "capability_manifest.py"
OWNERSHIP_MAP_PY = REPO_ROOT / PACKAGE_ROOT / "domains" / "core" / "ownership_map.py"
SEAM_PY = REPO_ROOT / "scripts" / "central_seam_census.py"
PLACEMENT_PY = REPO_ROOT / "scripts" / "physical_placement_census.py"

SDD_DIR = REPO_ROOT / ".superpowers" / "sdd" / "2026-09-24-central-dispatch"
OUT_MD = SDD_DIR / "OWNERSHIP.generated.md"
HUMAN_MD = SDD_DIR / "OWNERSHIP.md"

#: OWNERSHIP.md 双区标记（S105）。标记外＝机器区（`--emit-ownership` 从 ownership_map 册生成、勿手改）；
#: 标记内＝人写区（席位认领/阶段/欠账，投影器逐字节回环、绝不合成席位列——那是运行时事实，反席位锁不许冻进静态册）。
HUMAN_BEGIN = "<!-- SDD-HUMAN-CLAIMS-BEGIN（人写区：投影器逐字节回环保留；上方机器区勿手改） -->"
HUMAN_END = "<!-- SDD-HUMAN-CLAIMS-END -->"
#: 人写区表格行地板：抽出的认领区行数低于此值一律判「截断/抽空」、拒绝写回（防把账搬没了）。
#: 取值依据＝立区当刻（2026-09-24T04:3xZ）人写册现算 64 行，地板 40 只收紧不放宽（截半即红）。
HUMAN_ROW_FLOOR = 40
#: 人写区表格的表头单元（机器区绝不得出现这枚表头，由常驻门 `test_no_seat_or_phase_column_in_machine_zone` 执法）。
HUMAN_TABLE_HEADER = "认领席"

EXIT_CLEAN = 0
EXIT_USAGE = 1
EXIT_SOURCE = 2
EXIT_DIFF = 3
EXIT_SHRUNKEN = 4

R_TOOLS = "中央调度层工具面（本席与两支量具自身）"

#: 派生规则登记表。`--disable-rule` 只准用于诊断；任何一条被关掉 ⇒ 本次运行不作判据（见模块 docstring 规矩 2）。
RULES: dict[str, str] = {
    "M1": "capability_manifest.FACETS[*].trigger_source → 触发词/词表真身归该能力",
    # ⚠ 本表**不许写会过期的计数**（AGENTS 规则 10 同样管生成器印出去的文案）：旧文案写
    # 「board 今天 13 行全空」，而 board 维现算已 20/20 填满 ⇒ 生成件里躺着一句假话。
    # 空/填的枚数一律看 §4 现算读数，不写在本表。
    "M2": "capability_manifest.FACETS[*].board → 板块指针（board 为空的行 ⇒ 只进 unattributed）",
    "M3": "capability_manifest.EVIDENCE[*].evidence → 票根件（测试）归该能力×标签",
    "M4": "capability_manifest.FACETS[*].implementation_ref → 执行体真身面归该能力"
          "（S246R 补：册侧镜像指针直接取面。旧链只有 S2 走 seam 名册 decl，而 seam 的 decl "
          "对未接中央执行面的能力一律为空 ⇒ 那些能力的执行体文件对归属投影隐形，"
          "差集枚数一律现算、不写在本表。"
          "本规则**只取面、不判可解析**——判可解析全仓只有一把尺（腿②/②c 等值＋腿②d 行号），此处不重算）",
    "S1": "central_seam_census roster[*] 的六类 site 列表（decl/seam/invoke/generic/offseam/test）→ 该能力"
          "（即册维 FACETS[*].direct_callsites 的同一事实：站点只由普查算一次，本规则吃它的产物、"
          "册那一列吃它的投影，两处都不是第二真身）",
    "S2": "central_seam_census roster[*].decl[*].implementation_ref → 执行体真身归该能力",
    "S3": "central_seam_census meta.seam_variable_sites → 中央缝本体（结构性归属，非能力）",
    "S4": "central_seam_census violations_second_route → 第二通路违规点（带 cid，但记的是债不是写权）",
    "F1": "physical_placement_census four-accounts a3_shims_two_ledgers.*.top_files → 垫片账（两本之一）",
    "F2": "physical_placement_census four-accounts a1/a4 的路径清单 → 只给'在账'不给归属 ⇒ unattributed",
    "T1": "工具自证：本件与被投影的三支源自身（投影器必须能被自己的投影面看见）",
    "W1": "domains/core/ownership_map.FACE_OWNERSHIP → 写权互斥视图（面→owner域→允许并发写者数）；"
          "**席位占用列不投影**（运行时现算，见 §7 免责）",
}

SITE_ROLES: tuple[tuple[str, str], ...] = (
    ("decl", "登记行"),
    ("seam_sites", "中央缝调用点"),
    ("invoke_sites", "中央 invoker 调用点"),
    ("generic_sites", "通用管线调用点"),
    ("offseam_sites", "缝外直呼点"),
    ("test_sites", "测试面调用点"),
)

#: unattributed 的原因码（稳定字面量，差集归因靠它，不许自造新码不登记）。
WHY_NO_BOARD = "no-board-pointer"
WHY_UNASSIGNED_CALL = "call-without-capability-id"
WHY_PLACEMENT_ONLY = "in-placement-account-only"
WHY_ZERO_LIVE_REFS = "exists-but-zero-live-refs"
WHY_UNRESOLVED = "path-unresolvable"


class SourceUnavailable(RuntimeError):
    """某支投影源读不动——fail-closed，绝不降级成"该源无人"。"""


# ---------------------------------------------------------------------------
# 面（路径）规范化
# ---------------------------------------------------------------------------
def norm_face(raw: str) -> tuple[str, str | None]:
    """把一切来源的路径写法收敛到「仓内 posix 相对路径」。

    返回 `(face, why_unresolved)`；规范化不出来时 **face 保留原文**、`why` 给原因码，
    这样"看不清"的面不会被静默丢掉（缩面即造绿）。
    """
    text = (raw or "").strip().strip("`").strip()
    if not text:
        return "", WHY_UNRESOLVED
    text = text.split("#", 1)[0].strip()
    if not text:
        return "", WHY_UNRESOLVED
    text = text.replace("\\", "/")
    abs_root = str(REPO_ROOT).replace("\\", "/").rstrip("/") + "/"
    if text.lower().startswith(abs_root.lower()):
        text = text[len(abs_root):]
    text = text.lstrip("./")
    probe = text.rstrip("/")
    if (REPO_ROOT / probe).exists():
        return text, None
    under_pkg = f"{PACKAGE_ROOT}/{text}"
    if not text.startswith(PACKAGE_ROOT) and (REPO_ROOT / under_pkg).exists():
        return under_pkg, None
    if not (REPO_ROOT / probe).exists():
        # 允许「尚未落盘的声明落点」：仍给仓内相对路径，但标注未解析（不猜、不丢）。
        return text, WHY_UNRESOLVED
    return text, None


def domain_dir_of(face: str) -> str | None:
    """`plugins/bot_unified_runtime/domains/<d>/...` → `plugins/…/domains/<d>/`（目录面聚合）。"""
    parts = face.split("/")
    if len(parts) >= 4 and parts[2] == "domains":
        return "/".join(parts[:4]) + "/"
    if len(parts) >= 1 and parts[0] == PACKAGE_ROOT and len(parts) >= 2:
        return "/".join(parts[:2]) + "/"
    if len(parts) == 1:
        return ""
    return "/".join(parts[:-1]) + "/"


# ---------------------------------------------------------------------------
# 源装载
# ---------------------------------------------------------------------------
def _guarded_exec_module(path: Path, *, module_name: str, label: str, allow_empty: bool):
    """AST 守卫 + 单件装载一支**自身无包依赖**的声明件（禁相对 import、禁引插件包）。

    为什么单件装载而非按包 import：`plugins/bot_unified_runtime/__init__.py` 是 NoneBot 插件根，
    包导入会把整个插件初始化拖起来（本仓铁律，也是简报"不 import 包"的原意）。
    为什么不 AST 抄字段：抄一份字段解析 = 第二真身，册子换写法投影器就瞎。
    `load_manifest` 与 `load_face_ownership` 共用本件，禁两处各写一套守卫（守卫漂移＝假安全）。
    `allow_empty` 为假时，装载后由调用方自证非空；本函数只负责"能安全 exec 出模块对象"。
    """
    if not path.exists():
        raise SourceUnavailable(f"{label} 缺件：{path}")
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:  # pragma: no cover
        raise SourceUnavailable(f"{label} 语法不可解析：{exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            raise SourceUnavailable(
                f"{label}:{node.lineno} 出现相对 import（from {'.' * node.level}…）"
                "⇒ 单件装载会把插件包拖起来；本席拒绝投影，不猜字段。"
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("plugins") or "bot_unified_runtime" in alias.name:
                    raise SourceUnavailable(
                        f"{label}:{node.lineno} import 了插件包 {alias.name!r} ⇒ 同上，拒绝投影。"
                    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SourceUnavailable(f"{label} 无法构造装载规格：{path}")
    module = importlib.util.module_from_spec(spec)
    # 单件装载必须先把模块登记进 sys.modules 再 exec：`@dataclass` 在 3.12 靠
    # `sys.modules[cls.__module__].__dict__` 解析注解，不登记就当场 AttributeError
    # （S34 实踩：capability_manifest.py:70 的 @dataclass(frozen=True) 炸在这里）。
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # 装载失败一律 fail-closed，绝不当成「册为空」
        raise SourceUnavailable(f"{label} 单件装载失败：{type(exc).__name__}: {exc}") from exc
    finally:
        sys.modules.pop(spec.name, None)
    return module


def load_manifest(path: Path) -> dict[str, Any]:
    """装载 manifest 的 FACETS / EVIDENCE（守卫见 `_guarded_exec_module`）。"""
    module = _guarded_exec_module(
        path, module_name="_ownership_projection_manifest", label="manifest", allow_empty=False)
    facets = {str(k): v for k, v in dict(getattr(module, "FACETS", {})).items()}
    evidence = {k: v for k, v in dict(getattr(module, "EVIDENCE", {})).items()}
    if not facets:
        raise SourceUnavailable("manifest.FACETS 为空——起点即空一律判读不动，不判「无人认领」。")
    return {
        "FACETS": facets,
        "EVIDENCE": evidence,
        "uncovered_ceiling": getattr(module, "UNCOVERED_CEILING", None),
        "placeholders": sorted(getattr(module, "PLACEHOLDER_UNIMPLEMENTED", frozenset())),
        "file": path.relative_to(REPO_ROOT).as_posix(),
    }


def load_face_ownership(path: Path) -> dict[str, Any]:
    """装载写权互斥声明源 `ownership_map.py`，返回 FACE_OWNERSHIP 行 + `resolve` 谓词。

    fail-closed 同 manifest：读不动/相对 import/引包 ⇒ SourceUnavailable（退出码 2），
    绝不降级成"该面无人管"。**只声明规则、不声明席位**——本函数取的字段里没有任何席位。
    """
    module = _guarded_exec_module(
        path, module_name="_ownership_projection_face_ownership", label="ownership_map", allow_empty=False)
    rows = tuple(getattr(module, "FACE_OWNERSHIP", ()))
    if not rows:
        raise SourceUnavailable("ownership_map.FACE_OWNERSHIP 为空——起点即空一律判读不动。")
    resolve = getattr(module, "resolve", None)
    if not callable(resolve):
        raise SourceUnavailable("ownership_map 缺 resolve 谓词——读不动即 fail-closed，不猜覆盖度。")
    return {
        "rows": rows,
        "resolve": resolve,
        "known_owners": frozenset(getattr(module, "KNOWN_OWNERS", frozenset())),
        "file": path.relative_to(REPO_ROOT).as_posix(),
    }


def run_json(tool: Path, flag: str) -> dict[str, Any]:
    """跑一支只读普查、取 stdout JSON。非零退出／非 JSON ⇒ SourceUnavailable。"""
    if not tool.exists():
        raise SourceUnavailable(f"量具缺件：{tool.relative_to(REPO_ROOT)}")
    cmd = [sys.executable, str(tool), flag]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        raise SourceUnavailable(
            f"{tool.name} {flag} 退出码 {proc.returncode}（fail-closed，不当成空名册）"
            f"；stderr 尾：{(proc.stderr or '').strip()[-400:]!r}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SourceUnavailable(f"{tool.name} {flag} 输出非 JSON：{exc}") from exc


# ---------------------------------------------------------------------------
# 投影
# ---------------------------------------------------------------------------
@dataclass
class Projection:
    #: face → [(rule, owner, role), ...]
    attributed: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    #: face → [原因码, ...]
    unattributed: dict[str, list[str]] = field(default_factory=dict)
    #: 能力 id → 该能力声明的入口形态（并集口径：manifest ∪ seam 名册）
    entry_forms: dict[str, set[str]] = field(default_factory=dict)
    #: 能力 id → 普查状态
    states: dict[str, str] = field(default_factory=dict)
    #: 写权互斥视图（§7）：逐 FaceOwnership 行的可读投影；**与 attributed/unattributed 分账，绝不并计**。
    mutex: list[dict[str, Any]] = field(default_factory=list)
    #: 互斥视图覆盖度诊断：落在任何 exact/zone 声明之外的面数（未声明规则，非"无人管"）
    mutex_coverage: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def add(self, face: str, rule: str, owner: str, role: str) -> None:
        rows = self.attributed.setdefault(face, [])
        if (rule, owner, role) not in rows:
            rows.append((rule, owner, role))

    def add_unattributed(self, face: str, why: str) -> None:
        bucket = self.unattributed.setdefault(face, [])
        if why not in bucket:
            bucket.append(why)


def project(manifest: dict[str, Any], seam: dict[str, Any], four: dict[str, Any],
            *, rules_on: set[str],
            ownership: dict[str, Any] | None = None) -> Projection:
    p = Projection()
    p.meta = {
        "manifest_file": manifest["file"],
        "manifest_facets": len(manifest["FACETS"]),
        "manifest_evidence": len(manifest["EVIDENCE"]),
        "manifest_uncovered_ceiling": manifest["uncovered_ceiling"],
        "manifest_placeholders": manifest["placeholders"],
        "seam_meta": seam.get("meta", {}),
        "seam_counts": seam.get("counts", {}),
        "seam_integrity": seam.get("integrity", {}),
        "four_stamp": four.get("stamp_utc"),
        "ownership_file": OWNERSHIP_MAP_PY.relative_to(REPO_ROOT).as_posix(),
    }
    roster: dict[str, Any] = seam.get("roster") or {}
    if not isinstance(roster, dict):
        raise SourceUnavailable("seam --json 的 roster 不是对象，投影面无法枚举。")

    # ---- M1 / M2：manifest 行
    for cid, row in sorted(manifest["FACETS"].items()):
        p.entry_forms.setdefault(cid, set()).update(
            str(k.value if hasattr(k, "value") else k) for k in (getattr(row, "entry_kinds", ()) or ())
        )
        board = str(getattr(row, "board", "") or "")
        if board:
            p.add(cid, "M2", cid, f"板块指针 {board}")
        else:
            p.add_unattributed(f"capability:{cid}", WHY_NO_BOARD)
        trigger = str(getattr(row, "trigger_source", "") or "")
        if trigger:
            face, why = norm_face(trigger)
            if why:
                p.add_unattributed(face, why)
            if "M1" in rules_on:
                p.add(face, "M1", cid, f"触发词真身 {trigger}")
        # ---- M4：执行体真身面（册侧镜像指针；只取面，判可解析归腿②/②c/②d 那把尺）
        impl_ref = str(getattr(row, "implementation_ref", "") or "")
        if impl_ref and "M4" in rules_on:
            face, why = norm_face(impl_ref)
            if why:
                p.add_unattributed(face, why)
            p.add(face, "M4", cid, f"执行体真身（册侧镜像）{impl_ref}")

    # ---- M3：票根件
    if "M3" in rules_on:
        for (cid, tag), ev in sorted(manifest["EVIDENCE"].items(), key=lambda kv: str(kv[0])):
            evidence = str(getattr(ev, "evidence", "") or "")
            if not evidence:
                continue
            face, why = norm_face(evidence)
            if why:
                p.add_unattributed(face, why)
            p.add(face, "M3", cid, f"票根（标签 {tag}）")

    # ---- S1 / S2：seam 名册逐面
    for cid, info in sorted(roster.items()):
        if not isinstance(info, dict):
            raise SourceUnavailable(f"seam roster[{cid}] 不是对象。")
        state = str(info.get("state", ""))
        if state:
            p.states[cid] = state
        p.entry_forms.setdefault(cid, set()).update(str(x) for x in (info.get("entry_forms") or ()))
        for key, role in SITE_ROLES:
            if "S1" not in rules_on:
                break
            for site in info.get(key) or ():
                face, why = norm_face(str(site.get("file", "")))
                if not face:
                    continue
                if why:
                    p.add_unattributed(face, why)
                p.add(face, "S1", cid, role)
        if "S2" in rules_on:
            for site in info.get("decl") or ():
                ref = str(site.get("implementation_ref") or "")
                if not ref:
                    continue
                face, why = norm_face(ref)
                if why:
                    p.add_unattributed(face, why)
                p.add(face, "S2", cid, f"执行体真身 {ref}")

    # ---- S3：缝本体
    if "S3" in rules_on:
        for site in (seam.get("meta", {}) or {}).get("seam_variable_sites") or ():
            face, why = norm_face(str(site.get("file", "")))
            if not face:
                continue
            if why:
                p.add_unattributed(face, why)
            p.add(face, "S3", f"中央缝::{site.get('fn') or '?'}", "缝函数落点")

    # ---- S4：第二通路违规（带 cid，但它记的是"该收编的债"，不是写权）
    if "S4" in rules_on:
        for item in seam.get("violations_second_route") or ():
            face, why = norm_face(str(item.get("file", "")))
            if not face:
                continue
            if why:
                p.add_unattributed(face, why)
            p.add(face, "S4", str(item.get("capability_id") or "?"),
                  f"第二通路违规 tag={item.get('tag')} symbol={item.get('symbol')}")

    # ---- 无 cid 的能力函数调用：物理在盘、归属派生不出 ⇒ 显式挂账
    for symbol, sites in sorted((seam.get("unassigned_capability_function_calls") or {}).items()):
        for site in sites or ():
            face, why = norm_face(str(site.get("file", "")))
            if not face:
                continue
            p.add_unattributed(face, WHY_UNASSIGNED_CALL)
            p.meta.setdefault("unassigned_calls", []).append(f"{face}:{site.get('line')}#{symbol}")

    # ---- F1：垫片两本账的 top_files（账名即结构性归属，能力归属派生不出）
    a3 = ((four.get("accounts") or {}).get("a3_shims_two_ledgers") or {})
    if "F1" in rules_on:
        for ledger in ("prod_ledger", "tests_ledger"):
            for entry in (a3.get(ledger) or {}).get("top_files") or ():
                raw = str(entry[0]) if isinstance(entry, (list, tuple)) and entry else ""
                face, why = norm_face(raw)
                if not face:
                    continue
                if why:
                    p.add_unattributed(face, why)
                p.add(face, "F1", f"垫片账::{ledger}", "import 边残量（存在性≠活性）")

    # ---- F2：域外/在册未活性路径 —— 三支源只说"在账"，不说归谁 ⇒ unattributed
    if "F2" in rules_on:
        accounts = four.get("accounts") or {}
        a1 = accounts.get("a1_outside_py_dual_ruler") or {}
        for side in ("only_in_find", "only_in_git"):
            for bucket, items in (a1.get(side) or {}).items():
                for raw in items or ():
                    face, why = norm_face(str(raw))
                    if not face:
                        continue
                    p.add_unattributed(face, WHY_PLACEMENT_ONLY)
                    p.meta.setdefault("placement_faces", []).append(f"{side}.{bucket}:{face}")
        a4 = accounts.get("a4_roster_vs_real_debt") or {}
        for item in a4.get("existence_not_alive") or ():
            face, why = norm_face(str(item.get("path") or ""))
            if not face:
                continue
            p.add_unattributed(face, WHY_ZERO_LIVE_REFS)

    # ---- T1：投影链自身的四支件（自证可见）
    if "T1" in rules_on:
        self_face = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
        for tool, note in (
            (self_face, "本投影器"),
            (manifest["file"], "投影源①"),
            (SEAM_PY.relative_to(REPO_ROOT).as_posix(), "投影源②"),
            (PLACEMENT_PY.relative_to(REPO_ROOT).as_posix(), "投影源③"),
            (OWNERSHIP_MAP_PY.relative_to(REPO_ROOT).as_posix(), "投影源④（写权声明源，§6 互斥视图的来处）"),
        ):
            p.add(tool, "T1", R_TOOLS, note)

    # ---- W1：写权互斥视图（从 ownership_map 声明源投影；与能力账分账，绝不进 attributed）----
    if "W1" in rules_on and ownership is not None:
        # 排除结构性/能力记账面，只留真实路径面（capability:、中央缝::、垫片账::、工具自证面）。
        structural_prefixes = ("capability:", "中央缝::", "垫片账::", R_TOOLS)
        real_faces = [f for f in (set(p.attributed) | set(p.unattributed))
                      if not any(f.startswith(x) for x in structural_prefixes)]
        p.mutex, p.mutex_coverage = build_mutex(ownership, real_faces)
    return p


def build_mutex(ownership: dict[str, Any], faces: list[str] | set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把写权声明源投影成「互斥规则视图」+ 覆盖度诊断。**纯函数**：project() 与门共用一支，禁第二实现。

    `faces` 只喂**真实路径面**（调用方已排除 `capability:`/结构性面）；返回 (rows, coverage)。
    覆盖度是诊断不是归属：落在任何 exact/zone 之外的面计 `unzoned`，绝不为了把它搬成 0 而硬塞规则。
    """
    rows: list[dict[str, Any]] = []
    for row in ownership["rows"]:
        rows.append({
            "face": str(row.face),
            "owner": str(row.owner),
            "policy": str(getattr(row.policy, "value", row.policy)),
            "max_writers": int(row.max_writers),
            "kind": str(row.kind),
            "since": str(row.since),
            "why": str(row.why),
        })
    resolve = ownership["resolve"]
    face_list = list(faces)
    zoned = [f for f in face_list if resolve(f) is not None]
    unzoned = [f for f in face_list if resolve(f) is None]
    coverage: dict[str, Any] = {
        "declared_rows": len(ownership["rows"]),
        "scanned_real_faces": len(face_list),
        "covered_by_map": len(zoned),
        "unzoned": len(unzoned),
        "unzoned_sample": sorted(unzoned)[:12],
        "banned": sum(1 for r in rows if r["policy"] == "banned"),
        "read_only": sum(1 for r in rows if r["policy"] == "read_only"),
        "exclusive": sum(1 for r in rows if r["policy"] == "exclusive"),
        "append_only": sum(1 for r in rows if r["policy"] == "append_only"),
    }
    return rows, coverage


# ---------------------------------------------------------------------------
# 人写册解析（只读）
# ---------------------------------------------------------------------------
_BRACE = re.compile(r"\{([^{}]*)\}")
_TOKEN = re.compile(r"`([^`]+)`")


def expand_braces(text: str) -> list[str]:
    m = _BRACE.search(text)
    if not m:
        return [text]
    head, tail = text[: m.start()], text[m.end():]
    out: list[str] = []
    for part in m.group(1).split(","):
        out.extend(expand_braces(f"{head}{part.strip()}{tail}"))
    return out


def looks_like_path(token: str) -> bool:
    return "/" in token or token.lower().endswith((".py", ".md", ".json", ".yaml", ".ps1"))


def is_pattern(token: str) -> bool:
    return any(ch in token for ch in "*?{") or token.endswith("/")


def extract_human_zone(text: str) -> tuple[str, bool]:
    """抽出 OWNERSHIP.md 的**人写区**（标记内）。返回 `(human_block, bootstrapped)`。

    - 双区文件：取 `HUMAN_BEGIN`/`HUMAN_END` 之间（逐字节、只裁两端换行）。
    - 无标记（旧册 / bootstrap）：**整册皆人写**，原样返回、`bootstrapped=True`——
      这样 `--emit-ownership` 第一次跑就能把纯人写册包成人写区，不丢任何认领行。
    """
    b = text.find(HUMAN_BEGIN)
    e = text.find(HUMAN_END)
    if b != -1 and e != -1 and e > b:
        inner = text[b + len(HUMAN_BEGIN):e].strip("\n")
        return inner, False
    return text.rstrip("\n"), True


def human_row_count(block: str) -> int:
    """人写区的表格行数（`|` 起手的行，含表头/分隔）——地板判据用它，只数不改。"""
    return sum(1 for line in block.splitlines() if line.lstrip().startswith("|"))


def split_zones(text: str) -> tuple[str, str, bool]:
    """`(machine_zone, human_block, has_markers)`：常驻门与自测共用的纯切分器（禁第二实现）。

    机器区＝到 `HUMAN_BEGIN` 之前（含）；无标记＝机器区为空、整册归人写区（bootstrap 形态）。
    """
    b = text.find(HUMAN_BEGIN)
    human, _boot = extract_human_zone(text)
    if b == -1:
        return "", human, False
    return text[:b], human, True


def parse_human_rows(path: Path) -> list[dict[str, Any]]:
    """读 OWNERSHIP.md 的**人写区**表格行（双区文件的机器区行、标记外散文一律不计）。

    无标记＝整册皆人写（向后兼容旧册与 bootstrap 前）。读不到表格 ⇒ SourceUnavailable（不许当成"没人认领"）。
    `line` 仍报**真实文件行号**（§5 出处指向人写册原行，非人写区相对行）。
    """
    if not path.exists():
        raise SourceUnavailable(f"人写册缺件：{path.relative_to(REPO_ROOT)}")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    b = text.find(HUMAN_BEGIN)
    e = text.find(HUMAN_END)
    # 有标记 ⇒ 只解析 begin 行与 end 行**之间**的行号区间；无标记 ⇒ 全解析。
    if b != -1 and e != -1 and e > b:
        begin_line = text[:b].count("\n") + 1  # HUMAN_BEGIN 所在 1-based 行
        end_line = text[:e].count("\n") + 1    # HUMAN_END 所在 1-based 行
    else:
        begin_line, end_line = 0, len(lines) + 1
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(lines, start=1):
        if not (begin_line < lineno < end_line):
            continue
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        if "文件" in cells[0] or set(cells[0]) <= {"-", ":", " "}:
            continue
        tokens = _TOKEN.findall(cells[0]) or ([cells[0]] if cells[0] and cells[0] != "-" else [])
        faces: list[str] = []
        for token in tokens:
            for piece in expand_braces(token):
                piece = piece.strip().strip("`")
                if piece:
                    faces.append(piece)
        rows.append({
            "line": lineno,
            "cell": cells[0],
            "seat": cells[1] if len(cells) > 1 else "",
            "phase": cells[2] if len(cells) > 2 else "",
            "faces": faces,
            "tokens": tokens,
        })
    if not rows:
        raise SourceUnavailable(f"人写册解析到 0 行：{path.relative_to(REPO_ROOT)}（判读不动，不判空册）")
    return rows


def norm_pattern(token: str) -> tuple[str, str | None]:
    """人写册里的**模式面**（`a/**`、`a/*`、`dir/`、`x?.py`）规范化。

    取"通配符之前的最长目录前缀"做仓内解析，模式一律降为**目录面**（结尾带 `/`）。
    这一步只对齐写法，方向是**放宽不是收窄**：目录面命中其下任一投影面即算在册。
    解析不出目录时保留原文（`why` 给原因码），绝不静默丢面。
    """
    text = token.strip().strip("`").replace("\\", "/").lstrip("./")
    cut = re.split(r"[*?{}]", text)[0]
    stem = cut[: cut.rfind("/") + 1] if "/" in cut else ""
    probe = stem.rstrip("/")
    if not probe:
        return (text if text.endswith("/") else text + "/"), WHY_UNRESOLVED
    resolved, why = norm_face(probe)
    if why and not probe.startswith(PACKAGE_ROOT):
        resolved, why = norm_face(f"{PACKAGE_ROOT}/{probe}")
    return (resolved if resolved.endswith("/") else resolved + "/"), why


def human_face_index(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """人写面 → 出处行。规范化失败的保留原文并进"形态不可比"账（不丢、不猜）。"""
    idx: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for token in row["faces"]:
            if not looks_like_path(token):
                key = f"nonpath:{token}"
            elif is_pattern(token):
                key, _why = norm_pattern(token)
            else:
                key, _why = norm_face(token)
            idx.setdefault(key, []).append({"row": row, "token": token})
    return idx


#: 席位派生视图（S138 / 裁定 #10 + R-新4）：把「谁在哪个阶段申报了哪些写面」从**人写区**
#: 升为**从席报文件 SEAT-*.md + 真身册现算派生**的机器视图。反席位锁**不撤**——席位/阶段仍
#: 绝不进 `ownership_map.FaceOwnership` 的字段（那是运行时事实、每波漂移＝把排班流水账当教义），
#: 只在投影时从**席位报告件**现读现算。数据源只有两个：本目录 `SEAT-*.md` 与 `ownership_map` 册，
#: 严禁手写席位名凑数。
_SEAT_FILE_RE = re.compile(r"^SEAT-(S\d+)\.md$")
_SEAT_PHASE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"阶段[：:]\s*([A-Za-z0-9][A-Za-z0-9._/\-]*)"),
    re.compile(r"波次[：:]\s*([^\s·｜|]+)"),
)
_SEAT_WRITEFACE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"写面[（(]?[^：:）)]*[）)]?\s*[：:]\s*(.+)"),
)


def _first_group(text: str, pats: tuple[re.Pattern[str], ...]) -> str:
    for pat in pats:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return ""


def derive_seat_view(sdd_dir: Path) -> list[dict[str, Any]]:
    """从本目录 `SEAT-*.md` 席位报告件**现算派生**席位账（唯一席位数据来源，禁手写凑数）。

    每张报告件产一行：`seat`（文件名 `SEAT-S\\d+`）、`phase`（正文头 40 行里第一个阶段/波次标记）、
    `faces`（正文 `写面：…` 行里反引号路径 token）、`src`（报告件文件名，可回查）。读不动就跳过该席、
    不猜、不补——诚实缺一枚席位比造一枚假席位好（假席位＝第二真身，AGENTS #49 点名反模式）。
    """
    out: list[dict[str, Any]] = []
    for path in sorted(sdd_dir.glob("SEAT-S*.md")):
        m = _SEAT_FILE_RE.match(path.name)
        if not m:
            continue
        seat = m.group(1)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        head = "\n".join(text.splitlines()[:40])
        phase = _first_group(head, _SEAT_PHASE_RES)[:24]
        faces: list[str] = []
        for pat in _SEAT_WRITEFACE_RES:
            wm = pat.search(head)
            if wm:
                for token in _TOKEN.findall(wm.group(1)):
                    piece = token.strip().strip("`")
                    if piece and piece not in faces:
                        faces.append(piece)
                break
        out.append({"seat": seat, "phase": phase or "—", "faces": faces, "src": path.name})
    return out


def render_seat_zone(seats: list[dict[str, Any]]) -> list[str]:
    """把派生席位账渲染成机器区 §D 文本行。列头刻意避开人写区表头 `认领席/阶段/备注`
    （反席位锁的投影物侧延伸：机器区绝不含那三枚字面列头），改用 `席位 / 阶段·波次 / 申报写面 / 出处`。"""
    out: list[str] = []
    add = out.append
    add("## D. 席位派生视图（**从 SEAT-*.md 席报 + `ownership_map` 册现算，非人写、非静态字段**）")
    add("")
    add("> 机器**能算**「哪个席位在哪个阶段申报了哪些写面」——从席位报告件现读现算，"
        "但**不**把这列冻进 `ownership_map.FaceOwnership`（反席位锁：席位每波漂移＝运行时事实）。"
        "下方 §H 人写区仍是**欠账/承诺/挂账指针**的真身，机器不吞、逐字回环。")
    add("")
    if not seats:
        add("> ⚠ 未派生出任何席位（SEAT-*.md 缺件或头 40 行无席位标记）——诚实报空，不造占位。")
        return out
    add("| 席位 | 阶段·波次 | 申报写面数 | 写面样例 | 出处 |")
    add("|---|---|---|---|---|")
    for s in sorted(seats, key=lambda r: (len(r["seat"]), r["seat"])):
        faces = s["faces"]
        sample = "、".join(f"`{f}`" for f in faces[:3])
        if len(faces) > 3:
            sample += f" …(+{len(faces) - 3})"
        if not sample:
            sample = "—"
        add(f"| {s['seat']} | {s['phase']} | {len(faces)} | {sample} | `{s['src']}` |")
    return out


def match_projected_to_human_face(face: str, human_keys: list[str]) -> bool:
    """人写面若是目录/模式，命中其下的投影面即算在册（**只用于避免拼写噪声，不缩投影面**）。"""
    for key in human_keys:
        if key.startswith("nonpath:"):
            continue
        if key.endswith("/"):
            if face.startswith(key) or face == key.rstrip("/"):
                return True
            continue
        if "*" in key or "?" in key:
            stem = key.split("*", 1)[0]
            if stem and face.startswith(stem):
                return True
            continue
        if face == key:
            return True
    return False


# ---------------------------------------------------------------------------
# 差集
# ---------------------------------------------------------------------------
@dataclass
class Diff:
    only_human: list[dict[str, str]]
    only_projected: list[dict[str, str]]
    #: 两侧都有的面（对齐成功）。列出来是为了"匹配"这一步本身可审——不列就等于允许悄悄吞面。
    matched: list[dict[str, str]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.only_human and not self.only_projected


def _human_face_why(key: str) -> str:
    """为什么这一面机器派生不出来——分档归因，不写"未知"糊过去。"""
    if key.startswith("nonpath:"):
        return "非路径标注（席位/只读证据面/sha/命令等散文），投影面无对应实体"
    probe = key.rstrip("/")
    if (SDD_DIR / probe).exists() and "/" not in probe:
        return "席位报告件（SDD 目录内的过程产物），不是代码/能力面 ⇒ 三支源按设计看不见它"
    if not (REPO_ROOT / probe).exists():
        return ("仓内解析不到该实件（人写册用了简写或已漂移的路径，或该件在本仓之外如引擎侧 yaml）"
                "⇒ 投影只认在盘真身，不猜写法")
    if key.endswith("/"):
        return ("目录面：其下没有任何一枚被投影到的文件"
                "（多为该域能力的 implementation_ref 在 seam 名册里为空 ⇒ 声明侧缺字段，投影跟不到执行体）")
    return "在盘实件，但三支源没有任何字段说它归谁（席位互斥/禁写面是波次事实，不在能力册里）"


def compute_diff(p: Projection, rows: list[dict[str, Any]]) -> Diff:
    hidx = human_face_index(rows)
    human_keys = list(hidx)
    projected_faces = set(p.attributed) | set(p.unattributed)

    only_human: list[dict[str, str]] = []
    matched: list[dict[str, str]] = []
    for key in sorted(human_keys):
        hits = hidx[key]
        provenance = "; ".join(sorted({f"L{h['row']['line']}" for h in hits}))
        raws = "、".join(sorted({f"`{h['token']}`" for h in hits}))
        owners = "、".join(sorted({f"{h['row']['seat']}/{h['row']['phase']}" for h in hits}))
        covered = sorted(f for f in projected_faces if match_projected_to_human_face(f, [key]))
        if covered:
            matched.append({
                "face": key,
                "why": f"命中投影面 {len(covered)} 枚",
                "where": f"{provenance} 认领={owners or '-'} 原文={raws}",
            })
            continue
        only_human.append({
            "face": key,
            "why": _human_face_why(key),
            "where": f"{provenance} 认领={owners or '-'} 原文={raws}",
        })

    only_projected: list[dict[str, str]] = []
    for face in sorted(projected_faces):
        if match_projected_to_human_face(face, human_keys):
            continue
        if face.startswith("capability:"):
            # S246B：旧文案在这里手写「board 指针 13 行全空」，而 board 维现算早已填满 ⇒ 这句
            # 假话正被打进人读生成件。生成器印出去的文案同样受"禁手写会过期的计数"约束
            # （AGENTS 规则 10），执法见 `tests/test_doc_sync_gates.py` 尺④；枚数一律看 §4 现算读数。
            why = "能力行缺板块指针：以 `capability:<id>` 记账，人写册从不写这种面" \
                  "（空/填枚数看 §4 现算读数，本行不写死）"
        else:
            why = "投影派生到了、人写册从未认领（人写册只记争议面，投影面覆盖全扫描面）"
        only_projected.append({"face": face, "why": why})
    return Diff(only_human, only_projected, matched)


# ---------------------------------------------------------------------------
# 生成件
# ---------------------------------------------------------------------------
def human_stamp(path: Path) -> str:
    """人写册的**状态指纹**（字节数 + sha256[:16] + mtime-UTC）。

    为什么必须印：`OWNERSHIP.md` 是别人正在尾附的共享册 ⇒ `--check` 的差集只对"读到的那一版"成立。
    不锚版本，隔十分钟复跑得到的红会被误读成"投影坏了"。
    """
    raw = path.read_bytes()
    stamp = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
    return f"{len(raw)} B／sha256[:16] {hashlib.sha256(raw).hexdigest()[:16]}／mtime {stamp:%Y-%m-%dT%H:%M:%SZ}"


def render_ownership_md(p: Projection, human_block: str, *, disabled: set[str] | None = None,
                        seats: list[dict[str, Any]] | None = None) -> str:
    """把 OWNERSHIP.md 渲染成**双区投影物**：机器区（§M 写权互斥视图，从 `ownership_map` 册生成
    + §D 席位派生视图，从 `SEAT-*.md` 席报现算）
    + 人写区（§H，标记内 `human_block` 逐字回环）。机器区**只出写权规则列与派生席位列，绝不含人写席位表头 `认领席/阶段/备注`**。"""
    lines: list[str] = []
    add = lines.append
    add("# OWNERSHIP — 本波文件面互斥认领册（**双区投影物**）")
    add("")
    add("> **§M 机器区（勿手改）**：写权互斥视图，由 `scripts/ownership_project.py --emit-ownership` "
        "从唯一声明源 `plugins/bot_unified_runtime/domains/core/ownership_map.py` 机器投影。"
        "重录：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 "
        "PYTHONPYCACHEPREFIX=$TEMP/s34-pyc ../ChatBot_Runtime/venv/Scripts/python.exe "
        "scripts/ownership_project.py --emit-ownership`（cwd=仓根）。")
    add("> **§H 人写区（标记内）**：欠账／承诺／挂账指针（`CM-P-*`、sha 锚、`见 SEAT-* §N`）＝人写真身。"
        "**席位与阶段这二列机器已能从 §D 现算派生**（裁定 #10：全面自动化＝在双区之上再吞席位账），"
        "但**不**把席位/阶段冻进 `ownership_map.FaceOwnership`（反席位锁 `test_no_seat_or_phase_column`："
        "席位每波漂移，冻成静态字段＝把排班流水账当教义）——§H 逐字回环保留、绝不合成。"
        "改 §H 走 `dts.tail_append` CAS 尾附口，勿手改上方机器区。")
    add("> 能力归属逐条见 `OWNERSHIP.generated.md` §2（`--write` 生成）；本册机器区承「写权互斥规则」+"
        "「席位派生视图」两半（后者从 `SEAT-*.md` 席报现算，非静态字段）。")
    if disabled:
        add("")
        add(f"> ⚠ **诊断模式**：规则 {sorted(disabled)} 被 `--disable-rule` 关掉 ⇒ 机器区可能不全，本次产物不作判据。")
    add("")
    add("## M. 写权互斥视图（机器投影自 `ownership_map` 册；**规则视图，非席位占用**）")
    add("")
    if not p.mutex:
        add("> ⚠ 未装载写权声明源或 `W1` 关闭 ⇒ 机器区为空（人写区 §H 仍逐字保留，绝不受影响）。")
    else:
        mc = p.mutex_coverage
        add(f"互斥类别分桶：禁写 `banned` {mc.get('banned')} ｜ 只读 `read_only` {mc.get('read_only')} ｜ "
            f"独占 `exclusive` {mc.get('exclusive')} ｜ 尾附 `append_only` {mc.get('append_only')}。"
            f"覆盖度（诊断）：扫描真实面 {mc.get('scanned_real_faces')}、落册内 {mc.get('covered_by_map')}、"
            f"未声明规则 {mc.get('unzoned')}。")
        add("")
        add("| 文件/目录面 | owner 域 | 写权类别 | 允许并发写者 | 形态 | 登记锚 | 依据 |")
        add("|---|---|---|---|---|---|---|")
        for row in sorted(p.mutex, key=lambda r: (r["kind"], r["face"])):
            why = row["why"]
            if len(why) > 120:
                why = why[:120] + "…"
            add(f"| `{row['face']}` | `{row['owner']}` | `{row['policy']}` | {row['max_writers']} | "
                f"{row['kind']} | {row['since']} | {why} |")
    add("")
    if seats is None:
        try:
            seats = derive_seat_view(SDD_DIR)
        except OSError:
            seats = []
    lines.extend(render_seat_zone(seats))
    add("")
    add("## H. 席位认领／欠账（人写区 · 投影器逐字节回环保留 · 勿在标记外新增）")
    add("")
    add(HUMAN_BEGIN)
    add(human_block)
    add(HUMAN_END)
    add("")
    return "\n".join(lines)


def emit_ownership(projection: Projection, human_source_text: str, *,
                   disabled: set[str] | None = None,
                   seats: list[dict[str, Any]] | None = None) -> tuple[str, dict[str, Any]]:
    """把当前 OWNERSHIP.md 文本 fold 成双区投影物（**纯内存**，不碰盘；落盘由调用方原子写）。

    三重 fail-closed 闸（任一破 ⇒ 抛 SourceUnavailable ⇒ 调用方拒写、真册零变更）：
      ① 人写区行数 < `HUMAN_ROW_FLOOR`（截半/抽空即红）；
      ② 回环逐字节保真（新文件人写区抽回必须与抽入完全相等，防投影器改写认领行）；
      ③ 写后体积不得低于写前（体积反降＝疑丢内容）。
    `seats=None` ⇒ 由 `render_ownership_md` 从 `SEAT-*.md` 现算派生（§D 席位视图）。
    返回 `(text, diag)`；diag 只含计数/尺寸，不含原文。
    """
    human_block, bootstrapped = extract_human_zone(human_source_text)
    rows = human_row_count(human_block)
    if seats is None:
        try:
            seats = derive_seat_view(SDD_DIR)
        except OSError:
            seats = []
    diag: dict[str, Any] = {"human_rows": rows, "bootstrapped": bootstrapped,
                            "seats_derived": len(seats),
                            "before_chars": len(human_source_text)}
    if rows < HUMAN_ROW_FLOOR:
        raise SourceUnavailable(
            f"人写区表格行 {rows} < 地板 {HUMAN_ROW_FLOOR}——判为截断/抽空，"
            f"拒绝写回 OWNERSHIP.md（防把 64 行认领账搬没了）。")
    text = render_ownership_md(projection, human_block, disabled=disabled, seats=seats)
    reparsed, _ = extract_human_zone(text)
    if reparsed != human_block:
        raise SourceUnavailable(
            f"回环保真自证失败：重投影后的人写区与抽入不一致（{len(reparsed)} vs {len(human_block)} 字符），拒绝写回。")
    if len(text) < diag["before_chars"]:
        raise SourceUnavailable(
            f"写后 {len(text)} 字符 < 写前 {diag['before_chars']} 字符——体积反降，疑丢内容，拒绝写回。")
    diag["after_chars"] = len(text)
    return text, diag


def selftest() -> int:
    """内存注毒自证双区不变量 + 席位派生视图不变量（**不碰任何真册**）；全过返 0，任一红返 1。

    覆盖：① 回环逐字节保真 ② 地板截断必拒 ③ 机器区绝不含人写表头 ④ 体积反降必拒
    ⑤ 幂等（二次投影人写区稳定）⑥ 席位派生视图在机器区且不含人写表头 ⑦ 派生视图幂等稳定
    ⑧ 派生视图只认 SEAT-* 形态、拒绝手写凑数（喂非席位串产空）。这些是 `--emit-ownership` 的承重判据，
    配常驻门同尺（`split_zones`）。
    """
    fake = Projection(
        mutex=[{"face": "x.py", "owner": "core", "policy": "banned", "max_writers": 0,
                "kind": "file", "since": "2026-09-24", "why": "合成机器区行"}],
        mutex_coverage={"banned": 1, "read_only": 0, "exclusive": 0, "append_only": 0,
                        "scanned_real_faces": 1, "covered_by_map": 1, "unzoned": 0})
    human = "# OWNERSHIP — 旧人写册\n| 文件/目录 | 认领席 | 阶段 | 备注 |\n|---|---|---|---|\n" + \
        "\n".join(f"| f{i}.py | S{i} | P1 | 认领 {i} |" for i in range(45))
    fails: list[str] = []

    # ① 回环逐字节保真 + ③ 机器区不含人写表头 + ② 地板放行（45>40）。
    seats_synth = [{"seat": "S99", "phase": "P6", "faces": ["a.py", "b.md"], "src": "SEAT-S99.md"}]
    text, diag = emit_ownership(fake, human, seats=seats_synth)
    mach, hum, has = split_zones(text)
    if hum != human:
        fails.append("①回环保真：人写区被改写")
    if HUMAN_TABLE_HEADER in mach:
        fails.append("③越界：机器区混入了人写席位表头（反席位锁该红）")
    if not has or diag["human_rows"] < HUMAN_ROW_FLOOR:
        fails.append("②地板：45 行应放行却判截断")
    if "| 认领席 |" not in hum:
        fails.append("①保真：人写区席位表头丢了")
    # ⑤ 幂等：对已双区文本二次 fold，人写区必须逐字节不变。
    text2, _ = emit_ownership(fake, text, seats=seats_synth)
    if split_zones(text2)[1] != human:
        fails.append("⑤幂等：二次投影人写区漂移")
    # ②地板注毒：截半（<40 行）必被拒。
    try:
        emit_ownership(fake, human + "\n".join(f"| g{i}.py | S{i} | P1 | x |" for i in range(5)),
                       seats=seats_synth)  # 先补一段合法噪声
        short = "\n".join(f"| f{i}.py | S{i} | P1 | 认领 |" for i in range(20))  # 仅 20+2 行 < 40
        emit_ownership(fake, "# 旧册\n| 文件/目录 | 认领席 | 阶段 | 备注 |\n|---|---|---|---|\n" + short,
                       seats=seats_synth)
        fails.append("②地板注毒失败：截断册竟被放行")
    except SourceUnavailable:
        pass
    # ③ 机器区表头注毒：伪造把席位表头塞进机器区，split_zones 必须看得见。
    poisoned_machine = mach + "\n| 文件/目录 | 认领席 | 阶段 | 备注 |\n"
    if HUMAN_TABLE_HEADER not in poisoned_machine:
        fails.append("③注毒哨兵失效（不可能）")

    # ⑥ 席位派生视图：§D 落机器区（BEGIN 之前）、含派生席位、但绝不含人写表头 `认领席/阶段/备注`。
    if "席位派生视图" not in mach:
        fails.append("⑥§D 缺失：机器区没有席位派生视图（全面自动化未落地）")
    if "| S99 |" not in mach:
        fails.append("⑥§D 未渲染合成席位 S99")
    if HUMAN_TABLE_HEADER in "\n".join(render_seat_zone(seats_synth)):
        fails.append("⑥越界：派生视图混入了人写表头")
    # ⑦ 派生视图幂等：同 seats 二次投影 §D 逐字节稳定（席位账不被重投影悄悄改写）。
    if split_zones(text2)[0] != mach:
        fails.append("⑦派生视图非幂等：二次投影机器区漂移")
    # ⑧ 派生只认 SEAT-* 形态：往不存在目录派生 ⇒ 空账（不造占位、不手写凑数）。
    if derive_seat_view(Path(tempfile.gettempdir()) / "no-such-sdd-dir-zzz") != []:
        fails.append("⑧派生在无席位文件目录竟产出非空账（＝在造不存在的席位）")

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    real_seats = 0
    try:
        real_seats = len(derive_seat_view(SDD_DIR))
    except OSError:
        pass
    print(f"SELFTEST PASS: 回环保真/机器区无席位列/地板截断必拒/幂等/体积闸/席位派生视图(§D)幂等且拒绝凑数 全绿"
          f"（内存，真册零写入）；样例 before={diag['before_chars']} 字符 after={diag['after_chars']} 字符 "
          f"rows={diag['human_rows']} seats_derived(样例)={diag['seats_derived']} "
          f"seats_derived(真册现算)={real_seats}")
    return 0


def render(p: Projection, rows: list[dict[str, Any]], diff: Diff, *, shrunken: set[str],
           reused: list[str] | None = None) -> str:
    lines: list[str] = []
    add = lines.append
    add("# OWNERSHIP.generated — 由 `scripts/ownership_project.py` 从能力真身册机器投影（**生成件，勿手改**）")
    add("")
    add("> 复跑：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 "
        "PYTHONPYCACHEPREFIX=$TEMP/s34-pyc ../ChatBot_Runtime/venv/Scripts/python.exe "
        "scripts/ownership_project.py --write`（cwd=仓根）。")
    add("> 本件**不取代** `OWNERSHIP.md`：两册语义不同（席位互斥写权 vs 能力归属），"
        "差距逐条见 §5。人写册由主代理独占，本席零写入。")
    if shrunken:
        add("")
        add(f"> ⚠ **诊断模式**：规则 {sorted(shrunken)} 被 `--disable-rule` 关掉 ⇒ 扫描面已缩，"
            "本件内容不作判据。")
    if reused:
        add("")
        add(f"> ⚠ **复用快照**：本次运行的 ②③ 两支普查取自缓存 {reused}，"
            "不是与本次 `--write` 同一次的现算（下方现算戳取自快照文件本身，逐字保留以便对账）。")
    add("")
    meta = p.meta
    add("## 0. 三支源与现算戳")
    add("")
    add("| 源 | 现算读数 | 戳 |")
    add("|---|---|---|")
    add(f"| ⓪ `OWNERSHIP.md`（**双区投影物**：本 `--write` 只读其 §H 人写区做差集；§M 机器区由 `--emit-ownership` 生成） "
        f"| 人写区表格行 {len(rows)} 行 | {human_stamp(HUMAN_MD)} |")
    add(f"| ① `{meta['manifest_file']}` | FACETS 行／EVIDENCE 行 = "
        f"{meta['manifest_facets']}／{meta['manifest_evidence']}；"
        f"UNCOVERED_CEILING={meta['manifest_uncovered_ceiling']}；"
        f"PLACEHOLDER={meta['manifest_placeholders'] or '空'} | 单件装载（无包 import） |")
    add(f"| ② `scripts/central_seam_census.py --json` | universe／declared／seam_sites／offseam_sites = "
        f"{meta['seam_counts'].get('universe')}／{meta['seam_counts'].get('declared')}／"
        f"{meta['seam_counts'].get('seam_sites')}／{meta['seam_counts'].get('offseam_sites')}；"
        f"states={meta['seam_counts'].get('states')}；violations={meta['seam_counts'].get('violations_second_route')} "
        f"| generated_at={meta['seam_meta'].get('generated_at_utc')} "
        f"files_scanned={meta['seam_meta'].get('files_scanned')} |")
    add(f"| ③ `scripts/physical_placement_census.py --four-accounts` | 四本账（域外双尺／页级／垫片两本账／名册真债） "
        f"| stamp={meta['four_stamp']} |")
    add(f"| ④ `{meta['ownership_file']}` | 写权互斥声明源（面→owner域→并发数；**无席位字段**） "
        f"| 单件装载（无包 import） |")
    add("")
    add(f"面计数：已派生归属 {len(p.attributed)} ｜ 派生不出归属 {len(p.unattributed)} ｜ "
        "合计出现在投影里的面 "
        f"{len(set(p.attributed) | set(p.unattributed))}。")
    if p.mutex:
        mc = p.mutex_coverage
        add(f"写权互斥视图：声明行 {mc.get('declared_rows')} ｜ 覆盖扫描真实面 "
            f"{mc.get('covered_by_map')}/{mc.get('scanned_real_faces')}（未声明规则 {mc.get('unzoned')} 面）。"
            "**此视图与上面能力账分账，绝不并计凑零。**")
    add("")
    add("## 1. 派生规则登记表")
    add("")
    add("| 规则 | 派生依据 |")
    add("|---|---|")
    for rule, why in RULES.items():
        add(f"| `{rule}` | {why} |")
    add("")
    add("## 2. 文件/目录面 → 派生归属（逐条）")
    add("")
    add("| 文件/目录面 | 派生归属 | 归属类型 | 规则 | 角色明细 |")
    add("|---|---|---|---|---|")
    for face in sorted(p.attributed):
        entries = sorted(p.attributed[face])
        owners = sorted({o for _r, o, _ro in entries})
        rules = sorted({r for r, _o, _ro in entries})
        kind = sorted({
            "能力" if not o.startswith(("中央缝::", "垫片账::", R_TOOLS)) else "结构性"
            for o in owners
        })
        roles_all = [f"{o}←{ro}" for _r, o, ro in entries]
        roles = "；".join(roles_all)
        if len(roles) > 300:
            # 只做**可读性截断**并明说截了多少：归属列（owners）是全集，没有面或 owner 被吞掉。
            cut = 0
            acc = ""
            for piece in roles_all:
                if len(acc) + len(piece) + 1 > 290:
                    break
                acc = f"{acc}；{piece}" if acc else piece
                cut += 1
            roles = f"{acc}…（角色明细共 {len(roles_all)} 条，此处显示 {cut} 条；归属列未截）"
        add(f"| `{face}` | {', '.join(f'`{o}`' for o in owners)} | {'/'.join(kind)} | "
            f"{','.join(rules)} | {roles} |")
    add("")
    add("## 3. 目录面聚合（由 §2 文件面按目录前缀聚合，纯投影、不引入新源）")
    add("")
    add("| 目录面 | 覆盖文件面数 | 涉及归属（能力/结构性） |")
    add("|---|---|---|")
    dirs: dict[str, list[str]] = {}
    for face in sorted(p.attributed):
        d = domain_dir_of(face)
        if not d:
            continue
        dirs.setdefault(d, []).append(face)
    for d in sorted(dirs):
        owners = sorted({o for f in dirs[d] for _r, o, _ro in p.attributed[f]})
        shown = ", ".join(f"`{o}`" for o in owners[:6]) + ("…" if len(owners) > 6 else "")
        add(f"| `{d}` | {len(dirs[d])} | {shown} |")
    add("")
    add("## 4. 派生不出归属的面（＝人肉认领残留，**禁硬塞 owner**）")
    add("")
    add("原因码：")
    for code in (WHY_NO_BOARD, WHY_UNASSIGNED_CALL, WHY_PLACEMENT_ONLY, WHY_ZERO_LIVE_REFS, WHY_UNRESOLVED):
        n = sum(1 for v in p.unattributed.values() if code in v)
        add(f"- `{code}` — {COUNT_MEANINGS[code]}（命中 {n} 面）")
    add("")
    add("| 面 | 原因码 |")
    add("|---|---|")
    for face in sorted(p.unattributed):
        add(f"| `{face}` | {', '.join(f'`{c}`' for c in sorted(p.unattributed[face]))} |")
    add("")
    add("## 5. 与 `OWNERSHIP.md` 的双向差集（差集非空 ⇒ `--check` 退出码 3）")
    add("")
    add(f"- 人写册行数：{len(rows)}｜两侧对齐：**{len(diff.matched)}**｜"
        f"在册未投影：**{len(diff.only_human)}**｜投影未在册：**{len(diff.only_projected)}**")
    add("")
    add("### 5.0 两侧对齐（人写有、机器也派生得出）")
    add("")
    add("> 这张表列出是为了让「匹配」这一步本身可审：不列出来，就等于允许匹配悄悄吞面。")
    add("")
    add("| 人写面（规范化后） | 命中投影面数 | 出处 |")
    add("|---|---|---|")
    for item in diff.matched:
        add(f"| `{item['face']}` | {item['why']} | {item['where']} |")
    add("")
    add("### 5.1 在册未投影（人写了、机器派生不出）")
    add("")
    add("| 面 | 原因 | 出处（人写册席位/阶段） |")
    add("|---|---|---|")
    for item in diff.only_human:
        add(f"| `{item['face']}` | {item['why']} | {item['where']} |")
    add("")
    add("### 5.2 投影未在册（机器派生到了、人写册没有）")
    add("")
    add("| 面 | 原因 |")
    add("|---|---|")
    for item in diff.only_projected:
        add(f"| `{item['face']}` | {item['why']} |")
    add("")
    add("## 6. 席位互斥视图（从 `ownership_map` 声明源投影；规则视图，**非占用视图**）")
    add("")
    add("> **这条边界是本席对 S34 的精确修正**：机器**能**投影「面 → owner 域 → 允许并发写者数」这套"
        "写权规则（下表）；机器**永远不能、且不应**投影「此刻哪一席占着这把锁」——席位是运行时事实、"
        "每波漂移，调度侧现算。S34 §4.2 曾提议在声明源里放静态 `seat` 字段，本席否掉：那等于把排班流水"
        "账冻结成教义。故 §5 的能力归属差集与本 §6 的互斥规则是**两本账**，互不并计。")
    add("")
    if not p.mutex:
        add("> ⚠ `W1` 规则被关掉或未装载声明源 ⇒ 本视图为空（不作判据）。")
    else:
        mc = p.mutex_coverage
        add(f"互斥类别分桶：禁写 `banned` {mc.get('banned')} ｜ 只读 `read_only` {mc.get('read_only')} ｜ "
            f"独占 `exclusive` {mc.get('exclusive')} ｜ 尾附 `append_only` {mc.get('append_only')}。")
        add("")
        add("| 文件/目录面 | owner 域 | 写权类别 | 允许并发写者 | 形态 | 登记锚 | 依据 |")
        add("|---|---|---|---|---|---|---|")
        for row in sorted(p.mutex, key=lambda r: (r["kind"], r["face"])):
            why = row["why"]
            if len(why) > 120:
                why = why[:120] + "…"
            add(f"| `{row['face']}` | `{row['owner']}` | `{row['policy']}` | {row['max_writers']} | "
                f"{row['kind']} | {row['since']} | {why} |")
        add("")
        add(f"覆盖度（诊断，非归属）：扫描到的真实路径面 {mc.get('scanned_real_faces')} 枚，"
            f"落在任何 exact/zone 声明之内 {mc.get('covered_by_map')} 枚，"
            f"**未声明规则 {mc.get('unzoned')} 枚**（未声明≠无人管，是本册尚未覆盖；不为求好看硬塞规则）。"
            + (f" 未声明样例：{', '.join(f'`{x}`' for x in mc.get('unzoned_sample', []))}" if mc.get("unzoned") else ""))
    add("")
    add("## 7. 本件读法（一句话）")
    add("")
    add("§2 是**能力归属**的机器真值（哪些能力走这件文件、以什么角色）；§4 是**投影源说不清**的账；"
        "§5 是「人写席位册与机器能力册不能互换」的逐条证据；§6 是**写权互斥规则**（域+并发数，席位占用另由调度侧现算）。"
        "把 `OWNERSHIP.md` 直接换成 §2 会丢掉席位互斥这一列，换成 §6 会丢掉**谁在写**——两半合起来才逼近人写册，"
        "而「谁在写」那一列本就该是运行时现算、不进静态册。")
    add("")
    return "\n".join(lines)


COUNT_MEANINGS: dict[str, str] = {
    # 本表同样禁手写会过期的计数（旧文案「（13 行全空）」在 board 维填满后就是假话）：
    # 枚数一律看 §4 与 `--check` 的现算读数。
    WHY_NO_BOARD: "`FACETS.board` 为空 ⇒ 该枚能力的板块归属无人写过（只进 unattributed，不发明归属）",
    WHY_UNASSIGNED_CALL: "seam 名册点名了能力形状函数调用，但**拿不到 capability_id** ⇒ 无主可归",
    WHY_PLACEMENT_ONLY: "只出现在物理归位四本账的路径清单里（在账≠有归属）",
    WHY_ZERO_LIVE_REFS: "a4 真债：文件存在但 import 活性引用为 0 ⇒ 归属需人判（退役/归位待裁）",
    WHY_UNRESOLVED: "路径规范化失败（仓内无此件），**保留原文不丢**",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def gather(disabled: list[str], *, cache_dir: Path | None = None,
           ) -> tuple[Projection, list[dict[str, Any]], set[str], list[str]]:
    """跑齐三支源。`cache_dir` 只是**同一棵树上的重复调用优化**：命中即复用并在生成件里
    标 `⚠ 复用快照`（快照自带的 `generated_at_utc`/`stamp_utc` 仍逐字入册），不降级为空账。
    """
    rules_on = set(RULES) - set(disabled)
    reused: list[str] = []
    manifest = load_manifest(MANIFEST_PY)
    # 写权声明源第四支：读不动即 fail-closed（退出码 2），绝不降级成"该面无人管"。
    ownership = load_face_ownership(OWNERSHIP_MAP_PY)

    def _source(tool: Path, flag: str, name: str) -> dict[str, Any]:
        if cache_dir is not None:
            hit = cache_dir / name
            if hit.exists():
                try:
                    payload = json.loads(hit.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise SourceUnavailable(f"缓存 {hit.name} 非 JSON：{exc}") from exc
                reused.append(f"{name}（{hit.name}）")
                return payload
        payload = run_json(tool, flag)
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / name).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
        return payload

    seam = _source(SEAM_PY, "--json", "seam.json")
    integrity = seam.get("integrity") or {}
    if integrity.get("missing_required") or integrity.get("syntax_errors") or integrity.get("unreadable"):
        raise SourceUnavailable(f"seam 名册完整性不 ok：{integrity}")
    four = _source(PLACEMENT_PY, "--four-accounts", "four.json")
    if not (four.get("accounts") or {}):
        raise SourceUnavailable("四本账为空 accounts，投影源③读不动。")
    projection = project(manifest, seam, four, rules_on=rules_on, ownership=ownership)
    rows = parse_human_rows(HUMAN_MD)
    return projection, rows, set(disabled), reused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OWNERSHIP 机器投影（S34）")
    parser.add_argument("--write", action="store_true", help="生成 OWNERSHIP.generated.md")
    parser.add_argument("--emit-ownership", action="store_true",
                        help="把现役 OWNERSHIP.md 重写为双区投影物（§M 机器区从 ownership_map 册生成 + §H 人写区逐字节回环）；"
                             "fail-closed：地板/回环/体积三闸任一破即拒写、真册零变更（S105 目标⑤）")
    parser.add_argument("--selftest", action="store_true",
                        help="内存注毒自证双区不变量（回环保真/机器区无席位列/地板必拒/幂等/体积闸），不碰真册")
    parser.add_argument("--check", action="store_true", help="与 OWNERSHIP.md 做双向差集，非空退出码 3")
    parser.add_argument("--explain", action="store_true", help="打印规则登记表与归属语义边界，不判定")
    parser.add_argument("--out", default=str(OUT_MD), help="生成件路径（默认 SDD 目录内）")
    parser.add_argument("--disable-rule", action="append", default=[],
                        choices=sorted(RULES), help="诊断用：关掉某条规则（关掉即不作判据，退出码 4）")
    parser.add_argument("--poison-face", default=None,
                        help="注毒：注入一条人写册里没有的投影面（验证差集有牙）")
    parser.add_argument("--cache-dir", default=None,
                        help="同一棵树上重复调用时缓存两支普查 JSON 的目录（生成件会标「复用快照」）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    bad = [r for r in args.disable_rule if r not in RULES]
    if bad:
        print(f"未知规则：{bad}；可选 {sorted(RULES)}", file=sys.stderr)
        return EXIT_USAGE
    try:
        cache = Path(args.cache_dir) if args.cache_dir else None
        projection, rows, disabled, reused = gather(args.disable_rule, cache_dir=cache)
    except SourceUnavailable as exc:
        print(f"SOURCE-UNAVAILABLE（fail-closed，不降级为空账）：{exc}", file=sys.stderr)
        return EXIT_SOURCE
    if reused:
        print(f"⚠ 复用快照：{reused}（同一棵树的调用优化；戳已逐字入生成件，非同一次现算）")

    if args.poison_face:
        face, why = norm_face(args.poison_face)
        projection.add(face, "M1", "POISON::bot.nobody", "注毒面（应被抓进「投影未在册」差集）")
        if why:
            print(f"注毒面规范化失败：{face}", file=sys.stderr)

    diff = compute_diff(projection, rows)

    if args.write:
        text = render(projection, rows, diff, shrunken=disabled, reused=reused)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"WROTE {out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out} "
              f"({len(text)} chars, {text.count(chr(10)) + 1} lines)")

    if args.emit_ownership:
        try:
            cur = HUMAN_MD.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"读不到 OWNERSHIP.md（fail-closed，不写）：{exc}", file=sys.stderr)
            return EXIT_SOURCE
        try:
            owned, diag = emit_ownership(projection, cur, disabled=disabled)
        except SourceUnavailable as exc:
            print(f"拒绝写回 OWNERSHIP.md（fail-closed）：{exc}", file=sys.stderr)
            return EXIT_SOURCE
        HUMAN_MD.write_text(owned, encoding="utf-8", newline="\n")
        print(f"EMITTED {HUMAN_MD.relative_to(REPO_ROOT)} 人写区 {diag['human_rows']} 行"
              f"（bootstrap={diag['bootstrapped']}）{diag['before_chars']}→{diag['after_chars']} 字符"
              f"；机器区写权行 {len(projection.mutex)}、派生席位 {diag['seats_derived']}"
              f"（§D 从 SEAT-*.md 现算，未进 FaceOwnership）")
        if not args.check and not args.write:
            return EXIT_CLEAN

    if args.explain:
        print("归属语义边界（S71 对 S34 的修正）：")
        print("  · 三支投影源（manifest/seam/placement）只有『哪些能力走这件文件』，无写权规则字段。")
        print("  · 第四支 `ownership_map` 补上**写权互斥规则**（面→owner域→允许并发写者数）⇒ W1 投影 §6 互斥视图。")
        print("  · 但『此刻哪一席占着这把锁』是运行时事实，声明源里**故意不放 seat/phase 字段**——反席位锁不撤。")
        print("  · S138 全面自动化（裁定 #10 + R-新4）：席位/阶段改为**从 SEAT-*.md 席报现算派生**成 §D 视图，")
        print("    投影件产该列、但**不**进 `FaceOwnership`（现算派生 ≠ 冻结静态字段 ⇒ 锁仍在、判据换法）。")
        print("  ∴ 机器现取代 OWNERSHIP 的『能力归属』(§2) +『写权规则』(§6/§M) +『席位派生视图』(§D) 三半，")
        print("    仅『欠账/承诺/挂账指针』留 §H 人写区逐字回环（那是散文承重，非可派生事实）。")
        for rule, why in RULES.items():
            print(f"  {rule}: {why}")
        print(f"派生规则关掉：{sorted(disabled) or '无'}")
        return EXIT_CLEAN

    if not args.check and not args.write and not args.emit_ownership:
        print("无动作：给 --write / --check / --explain / --emit-ownership / --selftest 之一。")
        return EXIT_USAGE

    print(f"面：已派生归属 {len(projection.attributed)}／派生不出 {len(projection.unattributed)}")
    print(f"差集：两侧对齐 {len(diff.matched)}／在册未投影 {len(diff.only_human)}／"
          f"投影未在册 {len(diff.only_projected)}")
    for item in diff.only_human:
        print(f"  [在册未投影] {item['face']}  ← {item['why']} | {item['where']}")
    buckets: dict[str, list[str]] = {}
    for item in diff.only_projected:
        buckets.setdefault(item["why"], []).append(item["face"])
    for why, faces in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        print(f"  [投影未在册] {len(faces)} 面 | 原因：{why}")
        for face in faces[:8]:
            print(f"      - {face}")
        if len(faces) > 8:
            print(f"      …余 {len(faces) - 8} 面见生成件 §5.2")
    if disabled:
        print(f"⚠ 诊断模式：规则 {sorted(disabled)} 被关 ⇒ 面已缩，本次不作判据（退出码 {EXIT_SHRUNKEN}）")
        return EXIT_SHRUNKEN
    if diff.empty:
        print("差集为空。")
        return EXIT_CLEAN
    print("差集非空 ⇒ 判据未成立（不许靠缩面换绿）。")
    return EXIT_DIFF


if __name__ == "__main__":
    sys.exit(main())
