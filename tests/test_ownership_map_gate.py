"""S71 常驻门：`domains/core/ownership_map.py` 写权声明源的结构自洽 + 反席位锁 + 投影一致性。

判据与投影器 `scripts/ownership_project.py` 同源（复用它的 `_guarded_exec_module` 单件装载与
`build_mutex` 纯函数，禁第二实现）；每条负例都以**合成坏行喂进真身判据**证明锁有牙（注毒必红）。

跑：
    PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=<私有> PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 \
      python -m pytest tests/test_ownership_map_gate.py -p no:cacheprovider --basetemp=<私有> -q
"""

from __future__ import annotations

import ast
import sys
import types
from dataclasses import fields, make_dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ownership_project as op  # (复用投影器唯一装载器与 build_mutex，禁第二真身；E402 本仓未启用)

# 单件装载声明源（与投影器同法，禁 import 插件包）。
_MAP_MOD = op._guarded_exec_module(
    op.OWNERSHIP_MAP_PY, module_name="_s71_gate_ownership_map", label="ownership_map", allow_empty=False)
FACE_OWNERSHIP = _MAP_MOD.FACE_OWNERSHIP
WritePolicy = _MAP_MOD.WritePolicy
FaceOwnership = _MAP_MOD.FaceOwnership
KNOWN_OWNERS = frozenset(_MAP_MOD.KNOWN_OWNERS)
VALID_POLICIES = {p.value for p in WritePolicy}


# --------------------------------------------------------------------------
# 纯判据（返回问题清单）；对真身跑一遍=正向绿，对合成坏行跑=负向红（有牙）
# --------------------------------------------------------------------------
def _literal_path_problems(rows: list[Any]) -> list[str]:
    bad: list[str] = []
    for r in rows:
        if any(ch in r.face for ch in "*?{}\\"):
            bad.append(f"{r.face}: 面含通配/大括号/反斜杠（禁豁免兜底）")
        if r.kind not in ("file", "zone"):
            bad.append(f"{r.face}: kind={r.kind!r} 非 file/zone")
        if r.kind == "file" and r.face.endswith("/"):
            bad.append(f"{r.face}: file 面不得以 / 结尾")
        if r.kind == "zone" and not r.face.endswith("/"):
            bad.append(f"{r.face}: zone 面须以 / 结尾")
    return bad


def _existence_problems(rows: list[Any]) -> list[str]:
    bad: list[str] = []
    for r in rows:
        target = ROOT / r.face
        if r.kind == "zone" and not target.is_dir():
            bad.append(f"{r.face}: zone 目录不在盘")
        if r.kind == "file" and not target.is_file():
            bad.append(f"{r.face}: 声明面在仓内解析不到实件（写到机器段之外/漂移即红）")
    return bad


def _owner_problems(rows: list[Any]) -> list[str]:
    return [f"{r.face}: owner={r.owner!r} 不在 KNOWN_OWNERS" for r in rows if r.owner not in KNOWN_OWNERS]


def _why_problems(rows: list[Any]) -> list[str]:
    return [f"{r.face}: why 空或过短（无因写权不可审）" for r in rows if len((r.why or "").strip()) < 6]


def _policy_writer_problems(rows: list[Any]) -> list[str]:
    bad: list[str] = []
    for r in rows:
        policy = str(getattr(r.policy, "value", r.policy))
        if policy not in VALID_POLICIES:
            bad.append(f"{r.face}: policy={policy!r} 非法")
            continue
        if policy in ("banned", "read_only") and r.max_writers != 0:
            bad.append(f"{r.face}: {policy} 必须 max_writers==0，实为 {r.max_writers}")
        if policy in ("exclusive", "append_only") and r.max_writers < 1:
            bad.append(f"{r.face}: {policy} 允许并发须 ≥1，实为 {r.max_writers}")
    return bad


def _duplicate_face_problems(rows: list[Any]) -> list[str]:
    seen: set[str] = set()
    dup: set[str] = set()
    for r in rows:
        if r.face in seen:
            dup.add(r.face)
        seen.add(r.face)
    return [f"{f}: 一面被两条规则声明（并发预算歧义）" for f in sorted(dup)]


def _anti_seat_problems(module: Any) -> list[str]:
    """反席位锁：声明源的 FaceOwnership 字段里不得出现席位/阶段——那是运行时事实、会漂移。"""
    forbidden = {"seat", "phase", "owner_seat", "claim_seat", "claimant", "occupied_by", "wave_phase"}
    names = {f.name for f in _dataclass_fields(module.FaceOwnership)}
    hits = sorted(names & forbidden)
    if hits:
        return [f"FaceOwnership 出现席位/阶段字段 {hits}——违反『只声明规则、不声明占用』"]
    return []


def _dataclass_fields(cls: Any) -> list[Any]:
    return list(fields(cls))


def _row(face: str, *, owner: str = "core", policy: Any = None, writers: int = 1,
         kind: str = "file", why: str = "合成负例用的充分理由", since: str = "2026-09-24") -> Any:
    return FaceOwnership(
        face=face, owner=owner, policy=policy or WritePolicy.EXCLUSIVE,
        max_writers=writers, kind=kind, why=why, since=since)


#: 保护核心：这几枚硬禁写面一旦从册里消失、或被降级为可写 ⇒ 门红。
#: 基线只能往**更安全**方向动（往册里加保护面永远绿），摘保护必红——即"抬/降基线注毒必红"这一腿。
PROTECTED_CORE: tuple[str, ...] = (
    "plugins/bot_unified_runtime/__init__.py",
    "plugins/bot_unified_runtime/config.py",
    "plugins/bot_unified_runtime/runtime/capability_protocols.py",
    "plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py",
    "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py",
)


def _protected_core_problems(rows: list[Any]) -> list[str]:
    by_face = {r.face: r for r in rows}
    bad: list[str] = []
    for face in PROTECTED_CORE:
        r = by_face.get(face)
        if r is None:
            bad.append(f"{face}: 禁写核心从册中消失（基线只准更安全，不许抬）")
        elif str(getattr(r.policy, "value", r.policy)) != "banned" or r.max_writers != 0:
            bad.append(f"{face}: 禁写核心被降级为可写")
    return bad


# --------------------------------------------------------------------------
# 正向：真身过每一条判据
# --------------------------------------------------------------------------
def test_map_nonempty_and_types() -> None:
    assert FACE_OWNERSHIP, "FACE_OWNERSHIP 起点即空一律判读不动"
    assert all(isinstance(r, FaceOwnership) for r in FACE_OWNERSHIP)


def test_literal_paths() -> None:
    assert _literal_path_problems(list(FACE_OWNERSHIP)) == []


def test_every_face_resolves_in_repo() -> None:
    assert _existence_problems(list(FACE_OWNERSHIP)) == []


def test_owner_in_known_set() -> None:
    assert _owner_problems(list(FACE_OWNERSHIP)) == []


def test_why_present() -> None:
    assert _why_problems(list(FACE_OWNERSHIP)) == []


def test_policy_matches_writers() -> None:
    assert _policy_writer_problems(list(FACE_OWNERSHIP)) == []


def test_no_duplicate_faces() -> None:
    assert _duplicate_face_problems(list(FACE_OWNERSHIP)) == []


def test_no_seat_or_phase_column() -> None:
    assert _anti_seat_problems(_MAP_MOD) == []


def test_protected_core_still_banned() -> None:
    assert _protected_core_problems(list(FACE_OWNERSHIP)) == []


# --------------------------------------------------------------------------
# 投影一致性：resolve 语义 + build_mutex 覆盖度
# --------------------------------------------------------------------------
def test_resolve_exact_beats_zone_and_unknown_is_none() -> None:
    own = op.load_face_ownership(op.OWNERSHIP_MAP_PY)
    resolve = own["resolve"]
    exact = resolve("plugins/bot_unified_runtime/config.py")
    assert exact is not None and exact.policy.value == "banned", "精确禁写面须胜过任何包含它的 zone"
    zone = resolve("plugins/bot_unified_runtime/domains/creation/image/engine_provider.py")
    assert zone is not None and zone.owner == "creation", "子树内文件应落到 creation zone"
    assert resolve("totally/unknown/nobody.py") is None, "未声明面诚实回 None，不猜"


def test_build_mutex_coverage_counts_are_additive() -> None:
    own = op.load_face_ownership(op.OWNERSHIP_MAP_PY)
    faces = [
        "plugins/bot_unified_runtime/config.py",          # 命中 exact
        "plugins/bot_unified_runtime/domains/media/tts.py",  # 命中 media zone
        "plugins/bot_unified_runtime/capabilities/never_declared.py",  # unzoned
    ]
    rows, cov = op.build_mutex(own, faces)
    assert cov["declared_rows"] == len(FACE_OWNERSHIP)
    assert cov["scanned_real_faces"] == 3
    assert cov["covered_by_map"] == 2
    assert cov["unzoned"] == 1
    assert cov["covered_by_map"] + cov["unzoned"] == cov["scanned_real_faces"]
    # 分账：build_mutex 只回 rows/coverage，绝不把互斥面塞回能力账
    assert {r["face"] for r in rows} == {x.face for x in FACE_OWNERSHIP}


def test_mutex_view_is_separate_from_capability_account() -> None:
    # build_mutex 的 rows 全部来自 FACE_OWNERSHIP，与外部传入的 faces 无交叉污染
    own = op.load_face_ownership(op.OWNERSHIP_MAP_PY)
    _, cov = op.build_mutex(own, [])
    assert cov["scanned_real_faces"] == 0
    assert cov["covered_by_map"] == 0 and cov["unzoned"] == 0
    assert cov["declared_rows"] == len(FACE_OWNERSHIP)  # 声明行独立于扫描面


# --------------------------------------------------------------------------
# 注毒负例：每条判据喂一枚合成坏行必须抓到（锁有牙）
# --------------------------------------------------------------------------
def test_poison_wildcard_face_caught() -> None:
    assert _literal_path_problems([_row("plugins/**/x.py")]) != []


def test_poison_unresolvable_face_caught() -> None:
    # 认领行写到机器段之外/漂移 ⇒ 存在性锁必红
    assert _existence_problems([_row("plugins/bot_unified_runtime/domains/does_not_exist_zzz.py")]) != []


def test_poison_seat_field_shape_caught() -> None:
    poisoned = make_dataclass(
        "FaceOwnership",
        [("face", str), ("owner", str), ("policy", str), ("seat", str),
         ("max_writers", int), ("kind", str), ("why", str), ("since", str)],
        frozen=True)
    fake = types.SimpleNamespace(FaceOwnership=poisoned)
    assert _anti_seat_problems(fake) != [], "带 seat 字段的声明形态必须被反席位锁点名"


def test_poison_owner_out_of_set_caught() -> None:
    assert _owner_problems([_row("bot.py", owner="some_random_seat_name")]) != []


def test_poison_banned_with_writers_caught() -> None:
    assert _policy_writer_problems(
        [_row("bot.py", policy=WritePolicy.BANNED, writers=3)]) != []


def test_poison_empty_why_caught() -> None:
    assert _why_problems([_row("bot.py", why="")]) != []


def test_poison_duplicate_face_caught() -> None:
    rows = [_row("bot.py"), _row("bot.py")]
    assert _duplicate_face_problems(rows) != []


def test_poison_lower_protection_caught() -> None:
    # 降保护注毒必红：摘掉一枚禁写核心
    rows = [r for r in FACE_OWNERSHIP if r.face != "plugins/bot_unified_runtime/config.py"]
    assert _protected_core_problems(rows) != []
    # 或把它降级成可写（exclusive）也必红
    demoted = [
        _row(r.face, owner=r.owner, policy=r.policy, writers=r.max_writers, kind=r.kind,
             why=r.why, since=r.since) if r.face != "plugins/bot_unified_runtime/config.py"
        else _row(r.face, owner="config", policy=WritePolicy.EXCLUSIVE, writers=2,
                  kind=r.kind, why=r.why, since=r.since)
        for r in FACE_OWNERSHIP
    ]
    assert _protected_core_problems(demoted) != []


# --------------------------------------------------------------------------
# S105 双区投影锁：OWNERSHIP.md 改为「机器区(从 ownership_map 册) + 人写区(逐字回环)」投影物。
# 全部走投影器 op 的纯函数（split_zones/emit_ownership/render_ownership_md），**注毒只用内存合成串、真册零写入**。
# 判据：① 机器区绝不含人写席位表头（反席位锁的投影物侧延伸）② 人写区地板不足必拒写 ③ 回环逐字节保真。
# --------------------------------------------------------------------------
def _synth_projection() -> Any:
    proj = op.Projection()
    proj.mutex = [{
        "face": "plugins/bot_unified_runtime/config.py", "owner": "config", "policy": "banned",
        "max_writers": 0, "kind": "file", "since": "2026-09-24", "why": "合成机器区行（写权规则）",
    }]
    proj.mutex_coverage = {"banned": 1, "read_only": 0, "exclusive": 0, "append_only": 0,
                           "scanned_real_faces": 1, "covered_by_map": 1, "unzoned": 0}
    return proj


def _synth_human(n_rows: int) -> str:
    body = "\n".join(f"| f{i}.py | S{i} | P1 | 认领 {i}（含欠账 sha 锚 abc{i:013d}）|" for i in range(n_rows))
    return "# OWNERSHIP — 旧人写册\n| 文件/目录 | 认领席 | 阶段 | 备注 |\n|---|---|---|---|\n" + body


def test_machine_zone_carries_no_seat_column() -> None:
    """正向 + 注毒①：投影物的**机器区**（BEGIN 之前）绝不含人写席位表头；
    若有人把席位表头混进机器区，split_zones 当场看得见（锁有牙）。"""
    text, _diag = op.emit_ownership(_synth_projection(), _synth_human(op.HUMAN_ROW_FLOOR + 3))
    machine, human, has_markers = op.split_zones(text)
    assert has_markers, "双区标记必须成对在场"
    assert op.HUMAN_TABLE_HEADER not in machine, "机器区混入了人写席位表头 ⇒ 反席位锁应红"
    assert "| 阶段 |" not in machine and "| 备注 |" not in machine, "机器区混入了人写列"
    assert op.HUMAN_TABLE_HEADER in human, "人写区席位表头必须在（否则＝搬没认领账）"
    # 注毒：伪造把席位表头塞到机器区，判据必须能区分两段。
    doctored = machine + f"| 文件/目录 | {op.HUMAN_TABLE_HEADER} | 阶段 | 备注 |\n" + text[len(machine):]
    assert op.HUMAN_TABLE_HEADER in op.split_zones(doctored)[0], "注毒哨兵失效（不可能，若红说明切分器错）"


def test_emit_failclosed_on_truncated_human_zone() -> None:
    """注毒②：人写区被截到地板以下 ⇒ emit_ownership 必抛、拒写（防把账搬没了）。"""
    with pytest.raises(op.SourceUnavailable):
        op.emit_ownership(_synth_projection(), _synth_human(op.HUMAN_ROW_FLOOR - 5))
    with pytest.raises(op.SourceUnavailable):
        op.emit_ownership(_synth_projection(), "完全无表格行的散文册\n就一句话\n")
    # 反向对照：达标册放行（防恒红假执法）。
    _text, diag = op.emit_ownership(_synth_projection(), _synth_human(op.HUMAN_ROW_FLOOR + 1))
    assert diag["human_rows"] >= op.HUMAN_ROW_FLOOR


def test_emit_roundtrip_preserves_human_verbatim_and_is_idempotent() -> None:
    """注毒③：人写区**逐字节回环保真** + 二次投影幂等（投影器绝不改写认领行）。"""
    human = _synth_human(op.HUMAN_ROW_FLOOR + 4)
    text, _ = op.emit_ownership(_synth_projection(), human)
    assert op.split_zones(text)[1] == human, "回环保真失败：人写区被投影器动了"
    text2, _ = op.emit_ownership(_synth_projection(), text)  # 幂等：对已双区文本再投影
    assert op.split_zones(text2)[1] == human, "二次投影人写区漂移（＝席位账会被重投影悄悄改写）"


def test_floor_literal_is_handwritten_and_not_lowered() -> None:
    """地板 `HUMAN_ROW_FLOOR` 必须是投影器模块顶层手写字面整数（防派生式基线永远绿），只准升不准降。"""
    src = Path(op.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    found: int | None = None
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "HUMAN_ROW_FLOOR" and isinstance(node, (ast.Assign, ast.AnnAssign)):
                val = node.value
                assert isinstance(val, ast.Constant) and isinstance(val.value, int), "地板不许派生"
                found = val.value
    assert found is not None and found >= 40, f"HUMAN_ROW_FLOOR 被从 40 降到 {found}——地板只准升"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
