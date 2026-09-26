#!/usr/bin/env python
"""好感度 v7 存量数值处置**演练**脚本（需求项 13 / 席位 S-T-AFF-1）。

干什么
------
把「存量分数经 `z=atanh(score/100)` 惰性映射」这件事，从"运行时每条消息各推一次"
变成"可以先离线看一遍、看清楚了再决定"：读一份好感度库 → 对每一行算出映射后的
目标潜变量 `z` 与它回投的展示值 → 分类统计（逐点守恒 / 域钳位 / 脏值 / 待补齐 /
已漂移）→ **缺省只打印、一个字节都不写**。

三条硬约束（都写进代码，也写进 tests/test_affinity_v7_structural_locks.py）
------------------------------------------------------------------------
1. **绝不碰生产真库**：目标路径解析后只要落在任何名为 `ChatBot_Runtime` 的目录里
   （Windows 大小写不敏感），或落在 `scripts/runtime_paths.py` 解析出的运行数据根
   里，一律**拒绝并退出**（exit 2）。生产 `bot_affinity_db_path` 缺省正是被
   runtime_paths 重映射到 `ChatBot_Runtime/data/` 下的 —— 所以"什么都不传"= 拒绝，
   要演练必须先复制一份到临时路径。这是刻意设计成难用的安全面，不是没做完。
2. **映射算式只有真身**：本脚本不自写 `atanh`/`tanh`，一律调
   `affinity.v7_display_fraction_to_z` / `v7_z_to_display_fraction` /
   `coerce_affinity_fraction`。有一条 AST 锁盯着这里（禁第二真身）。
3. **写回只写 `z_latent`**：`--execute` 也只把"缺失或非有限"的 `z_latent` 补齐成
   由 `affinity` 列派生的值；`affinity` 列**永不改动**（改了就是重置人，违反
   规格 §三.1「绝不重置存量」）。因此本脚本对现网行为的可见影响为零 —— 运行时
   本来就会惰性推出同一个数，这里只是提前把它写下来并让它可核对。

幂等性
------
第二次运行必然报 `z_latent_filled=0`、分类计数逐字段不变；`--execute` 后再跑
DRY-RUN 亦为全 `no_op`。这条既是脚本性质，也是本席的验收判据之一。

用法
----
    python scripts/migrate_affinity_v7_rehearsal.py --db <副本路径>            # DRY-RUN
    python scripts/migrate_affinity_v7_rehearsal.py --db <副本路径> --execute   # 写副本
    python scripts/migrate_affinity_v7_rehearsal.py --db <副本> --json          # 机读输出
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# 让脚本在未经安装的状态下也能 import 包内真身（scripts/ 的上一级=仓库根）。
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _AFFINITY_BASE,
    _V7_DEFAULT_Z_HARD_BOUND,
    coerce_affinity_fraction,
    v7_display_fraction_to_z,
    v7_z_to_display_fraction,
)

# 展示值与派生 z 的往返比对容差：float64 下 atanh/tanh 复合的实测噪声远小于此。
ROUND_TRIP_TOLERANCE = 1e-12
# 被禁写的运行数据根目录名（Windows 文件系统大小写不敏感 ⇒ 比对一律 casefold）。
FORBIDDEN_DIRECTORY_NAMES = frozenset({"chatbot_runtime", "chatbot_archive"})


class UnsafeTargetPath(ValueError):
    """目标路径指向运行数据/归档区 —— 演练脚本拒绝执行。"""


class UnsafeTargetError(UnsafeTargetPath):
    """带人话原因的路径拒绝异常（`str()` 即为可直接贴给用户的一行）。"""

    def __init__(self, *, path: str, reason: str) -> None:
        super().__init__(f"拒绝访问 {path}：{reason}")
        self.path = path
        self.reason = reason


def guard_target_path(raw: str | Path, *, repo_root: Path | None = None) -> Path:
    """把用户给的库路径解析成绝对路径，并**拒绝**任何位于运行数据区内的路径。

    判据两层：①路径的任一段命中 `FORBIDDEN_DIRECTORY_NAMES`（含 `..` 归一之后的
    每一段，故 `../ChatBot_Runtime/data/x` 这种相对写法照样拦）；②与
    `scripts/runtime_paths.runtime_data_dir()` 比对前缀（运行数据根可被
    `BOT_RUNTIME_DATA_DIR` 改到任意位置，只按目录名拦会漏）。第二层 import 失败
    不致命：第一层已在，且本函数的缺省姿态是"拦得比需要的多"。
    """
    root = (repo_root or _REPO_ROOT).resolve()
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        resolved = Path(str(path).replace("\\", "/")).resolve()
    except OSError:  # 极端形态（非法字符/权限）：拒绝而不是猜
        raise UnsafeTargetError(path=str(raw), reason="路径无法解析为绝对路径") from None
    lowered = {part.lower() for part in resolved.parts}
    hit = lowered & FORBIDDEN_DIRECTORY_NAMES
    if hit:
        raise UnsafeTargetError(
            path=str(resolved),
            reason=f"位于运行数据/归档目录 {sorted(hit)} 内 —— 演练脚本绝不写生产库",
        )
    try:
        if str(_REPO_ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        from runtime_paths import runtime_data_dir  # type: ignore[import-not-found]

        data_root = Path(str(runtime_data_dir()).replace("\\", "/")).resolve()
    except UnsafeTargetError:
        raise
    except Exception as probe_error:  # noqa: BLE001 - 兜底：拿不准就只靠第一层判据
        print(f"[提示] runtime_paths 探测不可用，仅凭目录名判据执法：{probe_error!r}", file=sys.stderr)
        return resolved
    if resolved == data_root or data_root in resolved.parents:
        raise UnsafeTargetError(
            path=str(resolved),
            reason=f"位于 runtime_paths 解析出的运行数据根 {data_root} 内",
        )
    return resolved


def inspect_row(affinity_raw: Any, z_latent_raw: Any, *, bound: float = _V7_DEFAULT_Z_HARD_BOUND) -> dict[str, Any]:
    """算一行存量数据的映射结果并分类（纯函数，零 I/O，供测试逐类注毒）。

    分类互斥且穷尽，取值写进 `category`：
    - `conserved`      合法值在域内 ⇒ 回投展示值与原值逐点相等（**不重置任何人**）；
    - `domain_clamped` 合法但越界（|a|>bound）⇒ 钳到 ±bound，这是设计写明的域上界；
    - `dirty`          脏值（None/非数/NaN/±inf）⇒ **只点名不写回**，写回会掩盖问题；
    - 另有两条形而不同的旗标：`z_latent_missing`（该列没值，本次可补）、
      `z_latent_drift`（该列已有值且与派生值不符 ⇒ 报出来交人判，脚本不自作主张改）。
    """
    fraction = coerce_affinity_fraction(affinity_raw, default=_AFFINITY_BASE)
    dirty = affinity_raw is None or not _is_finite_number(affinity_raw)
    derived_z = v7_display_fraction_to_z(fraction, bound)
    projected = v7_z_to_display_fraction(derived_z)
    gap = projected - fraction
    if abs(fraction) > bound + ROUND_TRIP_TOLERANCE:
        category = "domain_clamped"
    elif dirty:
        category = "dirty"
    elif abs(gap) <= ROUND_TRIP_TOLERANCE:
        category = "conserved"
    else:
        category = "unexpected_drift"  # 数学上不该存在：出现即说明真身变了，须人看
    existing_z = _finite_or_none(z_latent_raw)
    return {
        "category": category,
        "stored_affinity": affinity_raw,
        "normalized_fraction": fraction,
        "derived_z": derived_z,
        "projected_fraction": projected,
        "abs_display_shift": abs(gap) * 100.0,  # 展示分口径的位移（×100）
        "z_latent_present": existing_z is not None,
        "z_latent_missing": existing_z is None and not dirty,
        "z_latent_drift": (
            existing_z is not None and abs(existing_z - derived_z) > 1e-9
        ),
        "would_write": existing_z is None and not dirty,
    }


def _is_finite_number(raw: Any) -> bool:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    # NaN 与任何比较恒 False ⇒ 双端开区间一条判住 NaN 与 ±inf 三态。
    return float("-inf") < value < float("inf")


def _finite_or_none(raw: Any) -> float | None:
    if not _is_finite_number(raw):
        return None
    return float(raw)  # type: ignore[arg-type]


def rehearsal_columns(connection: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in connection.execute("PRAGMA table_info(user_affinity)")}


def require_affinity_table(connection: sqlite3.Connection) -> None:
    """开跑前先确认"这确实是好感度库"，否则给一句人话而不是抛 `no such table`。

    旧顺序是先算指纹后判表 —— 指针对着不存在的表直接 OperationalError 崩栈，
    把"你给错文件了"这种最容易发生的误用变成最难读的一种失败。
    """
    columns = rehearsal_columns(connection)
    if "affinity" not in columns:
        raise SystemExit("目标库没有 user_affinity.affinity 列 —— 这不是好感度库，拒绝继续")


def plan(conn: sqlite3.Connection) -> dict[str, Any]:
    """遍历全表出账（只读）。返回统计 + 逐类样本，供 DRY-RUN 打印与守恒断言。"""
    # 本函数按列名取值（row["affinity"]），而 row_factory 是**连接**属性不是库属性：
    # 调用方若用自己裸 connect 出来的连接就会拿到元组。在这里设一次，谁传什么连接
    # 都不会再以 "tuple indices must be integers" 这种最难读的方式失败。
    conn.row_factory = sqlite3.Row
    columns = rehearsal_columns(conn)
    require_affinity_table(conn)
    has_z = "z_latent" in columns
    rows = conn.execute(
        "SELECT sender_id, affinity, z_latent FROM user_affinity"
        if has_z
        else "SELECT sender_id, affinity, NULL FROM user_affinity"
    ).fetchall()
    counts: dict[str, int] = {
        "rows_total": 0, "conserved": 0, "domain_clamped": 0, "dirty": 0,
        "unexpected_drift": 0, "z_latent_filled": 0, "z_latent_drift": 0,
    }
    max_shift = 0.0
    samples: dict[str, list[dict[str, Any]]] = {"domain_clamped": [], "dirty": [], "unexpected_drift": []}
    signed_shift_sum = 0.0
    for row in rows:
        result = inspect_row(row["affinity"], row["z_latent"] if has_z else None)
        counts["rows_total"] += 1
        counts[result["category"]] = counts.get(result["category"], 0) + 1
        if result["z_latent_missing"]:
            counts["z_latent_filled"] += 1
        if result["z_latent_drift"]:
            counts["z_latent_drift"] += 1
        max_shift = max(max_shift, result["abs_display_shift"])
        signed_shift_sum += result["projected_fraction"] - result["normalized_fraction"]
        bucket = samples.get(result["category"])
        if bucket is not None and len(bucket) < 5:
            bucket.append({
                "sender_id": str(row["sender_id"]),
                "stored": result["stored_affinity"],
                "projected": round(result["projected_fraction"], 6),
                "display_shift_points": round(result["abs_display_shift"], 6),
            })
    return {"counts": counts, "max_display_shift_points": max_shift,
            "net_fraction_shift": signed_shift_sum, "samples": samples, "has_z_column": has_z}


def assert_conservation(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """守恒断言：返回**违规清单**（空表 = 通过）。

    在册判据：①行数不变（绝不增删行）；②`unexpected_drift` 类必须为 0 —— 出现即
    说明"映射后回投的展示值 ≠ 原值"却又不属于设计写明的域钳位，等于有人在重置人。
    `affinity` 列逐行不变这一条不在这里判（它要读库），由 `main()` 用前后指纹判。
    """
    problems: list[str] = []
    if before["rows_total"] != after["rows_total"]:
        problems.append(f"行数变化 {before['rows_total']} → {after['rows_total']}")
    if after.get("unexpected_drift", 0):
        problems.append(f"非预期漂移 {after['unexpected_drift']} 行：映射不该改变展示值")
    return problems


def plan_warnings(report: dict[str, Any]) -> list[str]:
    """脏值只点名不处置 —— 这不是脚本报错，是它要交给人的话。"""
    dirty = report["counts"].get("dirty", 0)
    drift = report["counts"].get("z_latent_drift", 0)
    notes: list[str] = []
    if dirty:
        notes.append(f"{dirty} 行的 affinity 列非数/为空：演练只点名不写回，须人工核对来源")
    if drift:
        notes.append(f"{drift} 行的 z_latent 与派生值不符（多为 v7 flag 来回切换期的历史形）："
                     "运行时按 affinity 列为权威现推，脚本不自作主张覆盖")
    return notes


def affinity_column_fingerprint(conn: sqlite3.Connection) -> tuple[tuple[str, float | None], ...]:
    """`affinity` 列的可比对指纹（守恒判据用；非有限值归 None 以免 NaN 比不自等）。"""
    conn.row_factory = sqlite3.Row
    out: list[tuple[str, float | None]] = []
    for row in conn.execute("SELECT sender_id, affinity FROM user_affinity ORDER BY sender_id"):
        value = row["affinity"]
        out.append((str(row["sender_id"]), value if _is_finite_number(value) else None))
    return tuple(out)


def execute_plan(conn: sqlite3.Connection, report: dict[str, Any]) -> int:
    """真正写回：**只补 `z_latent` 缺失行**，返回被写的行数（幂等：第二次 0）。"""
    if not report["has_z_column"]:
        raise SystemExit("目标库无 z_latent 列（未经 _ensure_schema 建表）—— 不猜结构，拒绝写")
    conn.row_factory = sqlite3.Row
    written = 0
    rows = conn.execute("SELECT sender_id, affinity, z_latent FROM user_affinity").fetchall()
    for row in rows:
        result = inspect_row(row["affinity"], row["z_latent"])
        if not result["would_write"]:
            continue
        conn.execute(
            "UPDATE user_affinity SET z_latent=? WHERE sender_id=?",
            (result["derived_z"], row["sender_id"]),
        )
        written += 1
    return written


def open_read_only(path: Path) -> sqlite3.Connection:
    """开一个**物理上写不进**的连接（DRY-RUN 与只读体检都走这里）。

    为什么不用 `file:...?mode=ro`：好感度库是 WAL 库（`affinity._ensure_schema`
    显式 `PRAGMA journal_mode=WAL`），只读 URI 打开 WAL 库时 SQLite 拿不到
    `-shm`/`-wal` 的写权限，实测报 `no such table: main.user_affinity` —— 表明明
    在（换一种打开方式就看得见）。拿这个假象去判"这不是好感度库"就是误诊。
    改用 `PRAGMA query_only = ON`：读路径完全正常，任何写语句当场
    `attempt to write a readonly database`，保证强度不低于只读 URI 且不受 WAL 侧车影响。
    """
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def open_read_write(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def render(
    report: dict[str, Any],
    *,
    mode: str,
    written: int | None,
    problems: list[str],
    warnings: list[str] | None = None,
) -> str:
    counts = report["counts"]
    lines = [
        "好感度 v7 存量映射演练 —— " + ("EXECUTE（已写副本）" if mode == "execute" else "DRY-RUN（未写任何字节）"),
        f"  行数            : {counts['rows_total']}",
        f"  逐点守恒        : {counts['conserved']}   （映射后展示值与原值相等，无人被重置）",
        f"  域钳位          : {counts['domain_clamped']}   （|a|>bound 的极端存量，钳到 ±{round(_V7_DEFAULT_Z_HARD_BOUND * 100, 1)} 展示分）",
        f"  脏值（只点名）  : {counts['dirty']}",
        f"  非预期漂移      : {counts['unexpected_drift']}   （数学上不该存在，出现即须人看）",
        f"  z_latent 待补齐 : {counts['z_latent_filled']}   已漂移(只报不改): {counts['z_latent_drift']}",
        f"  最大展示分位移  : {report['max_display_shift_points']:.12f}   （只发生在域钳位行：|a|>bound 的极端存量）",
        (
            f"  映射净位移      : {report['net_fraction_shift']:+.15f}   （展示值口径；"
            "域钳位行的既有域上界效应，与『本脚本是否改写 affinity 列』是两件事——后者由指纹判，恒为零）"
        ),
    ]
    if written is not None:
        lines.append(f"  本次实际写回行数: {written}")
    for category, items in report["samples"].items():
        for item in items:
            lines.append(f"    [{category}] {item['sender_id']} stored={item['stored']!r} "
                          f"projected={item['projected']} shift={item['display_shift_points']}")
    if problems:
        lines.append("  守恒断言: 未通过")
        lines.extend(f"    - {problem}" for problem in problems)
    else:
        lines.append("  守恒断言: 通过（行数不变 / affinity 列零改动 / 只补 z_latent）")
    for note in warnings or []:
        lines.append(f"  待人判: {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="好感度 v7 存量数值处置演练（缺省 DRY-RUN 只打印，绝不写生产库）")
    parser.add_argument("--db", required=True, help="好感度 SQLite 路径（必须是生产库的**副本**）")
    parser.add_argument("--execute", action="store_true",
                        help="写回缺失的 z_latent（只写副本；生产路径一律拒绝）")
    parser.add_argument("--json", action="store_true", help="输出机读 JSON")
    parser.add_argument("--limit-samples", type=int, default=5, help="每类样本打印条数")
    args = parser.parse_args(argv)

    try:
        target = guard_target_path(args.db)
    except UnsafeTargetPath as error:
        print(f"[拒绝] {error}", file=sys.stderr)
        return 2
    if not target.exists():
        print(f"[拒绝] 目标库不存在：{target}", file=sys.stderr)
        return 2

    with open_read_only(target) as conn:
        require_affinity_table(conn)
        before = affinity_column_fingerprint(conn)
        report = plan(conn)
    report["samples"] = {k: v[: max(0, args.limit_samples)] for k, v in report["samples"].items()}

    written: int | None = None
    problems: list[str] = []
    if args.execute:
        with open_read_write(target) as conn:
            fingerprint_before = affinity_column_fingerprint(conn)
            written = execute_plan(conn, report)
            conn.commit()
            after_report = plan(conn)
            fingerprint_after = affinity_column_fingerprint(conn)
        if fingerprint_before != fingerprint_after:
            problems.append("affinity 列在写回前后不一致 —— 演练脚本本不该动它")
        if fingerprint_after != tuple(before):
            problems.append("affinity 列与只读阶段的指纹不一致")
        problems.extend(assert_conservation(report["counts"], after_report["counts"]))
        # 幂等自证：写完立刻再计划一次，待补齐数必须归零。
        if after_report["counts"]["z_latent_filled"] != 0:
            problems.append(f"写回后仍报待补齐 {after_report['counts']['z_latent_filled']} 行（非幂等）")
        report = after_report
    else:
        problems.extend(assert_conservation(report["counts"], report["counts"]))
    warnings = plan_warnings(report)

    if args.json:
        print(json.dumps({"mode": "execute" if args.execute else "dry_run",
                          "path": str(target), "report": report,
                          "written": written, "problems": problems,
                          "warnings": warnings}, ensure_ascii=False, indent=2))
    else:
        print(render(report, mode="execute" if args.execute else "dry_run",
                     written=written, problems=problems, warnings=warnings))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
