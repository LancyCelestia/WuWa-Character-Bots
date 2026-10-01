#!/usr/bin/env python
"""好感度 v8 存量数值处置**演练 + A 案恒等迁移**脚本（需求项 13 / 席位 SEAT-AFFINITY）。

对应规格：docs/affinity-design.md §E（存量数值处置方案）。她点名要的第二件交付物——
「如何处置现好感度数值」——落成一个**缺省只读、显式 --execute 才写、且绝不碰生产库**的脚本。

它干什么（A 案「恒等 + 加列」，§E.1 推荐案）
--------------------------------------------
v8 的表示面沿用 v7 潜变量 z（`s=100·tanh(z)`），**存量 z 与展示 affinity 一个字节都不改**；
新增列 `goodwill_anchor`（善意底水位）与 `v8_state`（环境基线/在场连续/复读指纹）由运行时
`_ensure_schema` 的 ALTER-if-missing 家规自动补齐（先例＝z_latent 那批）。本脚本只做两件事：

1. **DRY-RUN 演练（缺省，零写入）**：逐行现推 `z`（列 NULL 时按 affinity 惰性派生，绝不重置）、
   按 `created_at` 算相处天数 → `band(days)` → 播种 `anchor₀ = z − band`；报告
   「切换瞬间档位是否变化」`（A 案恒等 ⇒ 展示分不变 ⇒ 档不变 ⇒ 结构上不可能跳档）`、
   anchor 分布、脏行清单。**先看清楚再决定**。
2. **--execute（只写副本）**：仅把 `goodwill_anchor IS NULL` 的行补成上面现推的 anchor₀，
   `affinity`/`z_latent` **永不改动**；`v8_state` 留空由运行时自填。幂等：第二次必然 `seeded=0`。

为什么这是"安全难用"的面，不是没做完
------------------------------------
- 目标路径解析后只要落在任何 `ChatBot_Runtime` / `ChatBot_archive` 目录、或落在
  `runtime_paths` 解析的运行数据根内 ⇒ **拒绝退出（exit 2）**。生产 `bot_affinity_db_path`
  缺省正被重映射进 `ChatBot_Runtime/data/` ⇒ 什么都不传＝拒绝；要演练必须先复制一份到临时路径。
- 守恒断言（§E.2）：迁移前后 `(sender_id→affinity, z_latent)` 逐字节相等、行数不变、
  计划写入数 == 实际写入数、新增 `goodwill_anchor` 无一行 > 该行 `z_latent`（只作下界）；
  任一失败 ⇒ 整事务回滚 + 非零退出。A 案恒等让"永不失败"看似平凡，故附**负样本注毒**（§F）：
  故意把 anchor 写成 `z+0.1`、故意漏投一行 ⇒ 断言必红。

灰度与回滚（§E.4，脚本之外、交给她的开关）
------------------------------------------
1. 本脚本 DRY-RUN 看分布 → 2. `--execute` 于副本验证守恒与幂等 → 3. 生产只开
`bot_affinity_v8_enabled` 跑**影子记账**（写日志不改 z，观察一周）→ 4. 她过目影子报告
→ 5. 正式开 + 提权重启（重启权在她）→ 6. 真机验收。**回滚＝关 flag**：v8 分支不执行、
v7/v5 逐字节续跑；本脚本从未改写 affinity/z_latent ⇒ 回滚零数据损失。全程不动生产 `.env`。

用法
----
    python scripts/migrate_affinity_v8.py --db <副本路径>              # DRY-RUN（缺省，零写）
    python scripts/migrate_affinity_v8.py --db <副本> --execute        # 只补 anchor（只写副本）
    python scripts/migrate_affinity_v8.py --db <副本> --json           # 机读输出
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _AFFINITY_BASE,
    _V8_DISPLAY_DOMAIN_BOUND,
    coerce_affinity_fraction,
    tier_for_affinity,
    v7_display_fraction_to_z,
    v7_z_to_display_fraction,
    v8_goodwill_anchor,
    v8_goodwill_band,
)

ROUND_TRIP_TOLERANCE = 1e-12
FORBIDDEN_DIRECTORY_NAMES = frozenset({"chatbot_runtime", "chatbot_archive"})
_DAY_SECONDS = 86400.0


class UnsafeTargetPath(ValueError):
    """目标路径指向运行数据/归档区 —— 演练脚本拒绝执行。"""


class UnsafeTargetError(UnsafeTargetPath):
    def __init__(self, *, path: str, reason: str) -> None:
        super().__init__(f"拒绝访问 {path}：{reason}")
        self.path = path
        self.reason = reason


def guard_target_path(raw: str | Path, *, repo_root: Path | None = None) -> Path:
    """解析库路径并**拒绝**任何位于运行数据区内的路径（先例＝migrate_affinity_v7_rehearsal）。"""
    root = (repo_root or _REPO_ROOT).resolve()
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        resolved = Path(str(path).replace("\\", "/")).resolve()
    except OSError:
        raise UnsafeTargetError(path=str(raw), reason="路径无法解析为绝对路径") from None
    hit = {p.lower() for p in resolved.parts} & FORBIDDEN_DIRECTORY_NAMES
    if hit:
        raise UnsafeTargetError(
            path=str(resolved),
            reason=f"位于运行数据/归档目录 {sorted(hit)} 内 —— 迁移脚本绝不写生产库",
        )
    try:
        if str(_REPO_ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        from runtime_paths import runtime_data_dir  # type: ignore[import-not-found]

        data_root = Path(str(runtime_data_dir()).replace("\\", "/")).resolve()
    except UnsafeTargetError:
        raise
    except Exception as probe_error:  # noqa: BLE001
        print(f"[提示] runtime_paths 探测不可用，仅凭目录名判据执法：{probe_error!r}", file=sys.stderr)
        return resolved
    if resolved == data_root or data_root in resolved.parents:
        raise UnsafeTargetError(
            path=str(resolved),
            reason=f"位于 runtime_paths 解析出的运行数据根 {data_root} 内",
        )
    return resolved


def _is_finite_number(raw: Any) -> bool:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return float("-inf") < value < float("inf")


def _finite_or_none(raw: Any) -> float | None:
    return float(raw) if _is_finite_number(raw) else None  # type: ignore[arg-type]


def _epoch_seconds(raw: Any) -> float | None:
    """解析 created_at/updated_at（ISO8601 带偏移，_format_utc 写入形制）为 epoch 秒；脏⇒None。"""
    from datetime import datetime, timezone

    text = str(raw or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def inspect_row(
    affinity_raw: Any,
    z_latent_raw: Any,
    created_at_raw: Any,
    anchor_raw: Any,
    *,
    now: float,
) -> dict[str, Any]:
    """一行存量的 v8 A 案处置结果（纯函数、零 I/O，供注毒）。

    category 互斥穷尽：
      conserved      合法值 ⇒ z 由现推/既有列得到、anchor₀=z−band 仅新增、affinity 不变；
      dirty          affinity/z 脏（None/非数/NaN/±inf）⇒ 只点名不写；
      unexpected_drift 数学上不该存在的展示漂移（真身变了）⇒ 交人看。
    would_anchor：goodwill_anchor 现为 NULL 且行合法 ⇒ 本次可补 anchor₀。
    """
    dirty = affinity_raw is None or not _is_finite_number(affinity_raw)
    fraction = coerce_affinity_fraction(affinity_raw, default=_AFFINITY_BASE)
    existing_z = _finite_or_none(z_latent_raw)
    derived_z = (
        existing_z
        if existing_z is not None
        else v7_display_fraction_to_z(fraction, _V8_DISPLAY_DOMAIN_BOUND)
    )
    projected = v7_z_to_display_fraction(derived_z)
    stored_tier = tier_for_affinity(fraction)
    projected_tier = tier_for_affinity(projected)
    if dirty:
        category = "dirty"
    elif abs(projected - fraction) <= ROUND_TRIP_TOLERANCE and stored_tier == projected_tier:
        category = "conserved"
    else:
        category = "unexpected_drift"
    created = _epoch_seconds(created_at_raw)
    days = max(0.0, (now - created) / _DAY_SECONDS) if created is not None else None
    band = v8_goodwill_band(days)  # days=None ⇒ fail-open 回 band_min
    anchor_seed = v8_goodwill_anchor(None, derived_z, band)  # = z − band
    existing_anchor = _finite_or_none(anchor_raw)
    return {
        "category": category,
        "affinity": affinity_raw,
        "z": derived_z,
        "z_was_null": existing_z is None,
        "display_after_tanh": projected,
        "abs_display_shift_points": abs(projected - fraction) * 100.0,
        "tier_stable": stored_tier == projected_tier,
        "companion_days": days,
        "band": band,
        "anchor_seed": anchor_seed,
        "anchor_below_z": anchor_seed <= derived_z + 1e-9,
        "existing_anchor": existing_anchor,
        "would_anchor": existing_anchor is None and not dirty,
    }


def plan(conn: sqlite3.Connection, *, now: float) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    columns = {r[1] for r in conn.execute("PRAGMA table_info(user_affinity)")}
    if "affinity" not in columns:
        raise SystemExit("目标库没有 user_affinity.affinity 列 —— 这不是好感度库，拒绝继续")
    has_anchor = "goodwill_anchor" in columns
    has_z = "z_latent" in columns
    rows = conn.execute(
        "SELECT sender_id, affinity, z_latent, created_at, goodwill_anchor FROM user_affinity"
        if (has_anchor and has_z)
        else "SELECT sender_id, affinity, NULL AS z_latent, created_at, NULL AS goodwill_anchor"
             " FROM user_affinity"
    ).fetchall()
    counts = {"rows_total": 0, "conserved": 0, "dirty": 0, "unexpected_drift": 0,
              "z_latent_missing": 0, "anchor_seeded": 0}
    tier_changed = 0
    max_shift = 0.0
    anchor_min = anchor_max = None
    samples: dict[str, list[dict[str, Any]]] = {"dirty": [], "unexpected_drift": []}
    for row in rows:
        r = inspect_row(
            row["affinity"], row["z_latent"], row["created_at"],
            row["goodwill_anchor"] if has_anchor else None, now=now,
        )
        counts["rows_total"] += 1
        counts[r["category"]] = counts.get(r["category"], 0) + 1
        if r["z_was_null"] and r["category"] != "dirty":
            counts["z_latent_missing"] += 1
        if r["would_anchor"]:
            counts["anchor_seeded"] += 1
            lo = r["anchor_seed"]
            anchor_min = lo if anchor_min is None else min(anchor_min, lo)
            anchor_max = lo if anchor_max is None else max(anchor_max, lo)
        if not r["tier_stable"]:
            tier_changed += 1
        max_shift = max(max_shift, r["abs_display_shift_points"])
        bucket = samples.get(r["category"])
        if bucket is not None and len(bucket) < 5:
            bucket.append({"sender_id": str(row["sender_id"]), "affinity": r["affinity"],
                           "band": round(r["band"], 6), "anchor_seed": round(r["anchor_seed"], 6)})
    return {"counts": counts, "max_display_shift_points": max_shift,
            "tier_changed": tier_changed, "anchor_min": anchor_min, "anchor_max": anchor_max,
            "samples": samples, "has_anchor_column": has_anchor, "has_z_column": has_z}


def identity_fingerprint(conn: sqlite3.Connection) -> tuple[tuple[str, float | None, float | None], ...]:
    """(sender_id, affinity, z_latent) 的可比对指纹——A 案守恒：迁移前后必须逐字节相等。"""
    conn.row_factory = sqlite3.Row
    columns = {r[1] for r in conn.execute("PRAGMA table_info(user_affinity)")}
    has_z = "z_latent" in columns
    out = []
    for row in conn.execute("SELECT sender_id, affinity, z_latent FROM user_affinity"
                             if has_z else "SELECT sender_id, affinity, NULL AS z_latent FROM user_affinity"
                            ):
        a = row["affinity"]
        z = row["z_latent"] if has_z else None
        out.append((str(row["sender_id"]), a if _is_finite_number(a) else None,
                    z if _is_finite_number(z) else None))
    return tuple(out)


def assert_conservation(
    report: dict[str, Any],
    *,
    before_fp: tuple,
    after_fp: tuple,
    planned: int,
    written: int,
    anchor_check_problems: list[str],
) -> list[str]:
    """守恒断言（§E.2）：返回**违规清单**（空＝通过）。"""
    problems: list[str] = []
    if report["counts"]["rows_total"] != 0 and before_fp != after_fp:
        problems.append("affinity/z_latent 指纹在写回前后不一致 —— A 案是恒等迁移，任何数值变动都是事故")
    if report["counts"].get("unexpected_drift", 0):
        problems.append(f"非预期漂移 {report['counts']['unexpected_drift']} 行：映射不该改变展示值")
    if report["tier_changed"]:
        problems.append(f"切换瞬间有 {report['tier_changed']} 行档位会变化 —— A 案恒等下应为 0（跳档红线）")
    if planned != written:
        problems.append(f"计划写入 {planned} != 实际写入 {written}（漏一人即事故）")
    problems.extend(anchor_check_problems)
    return problems


def check_anchors_are_lower_bound(conn: sqlite3.Connection) -> list[str]:
    """新增列不变量：goodwill_anchor 无一行 > 该行 z_latent（anchor 只能作下界）。"""
    conn.row_factory = sqlite3.Row
    columns = {r[1] for r in conn.execute("PRAGMA table_info(user_affinity)")}
    if "goodwill_anchor" not in columns or "z_latent" not in columns:
        return []
    bad = conn.execute(
        "SELECT COUNT(*) FROM user_affinity WHERE goodwill_anchor IS NOT NULL"
        " AND z_latent IS NOT NULL AND goodwill_anchor > z_latent + 1e-9"
    ).fetchone()[0]
    return [f"{int(bad)} 行 goodwill_anchor 高于 z_latent（下界越界）"] if bad else []


def execute_plan(conn: sqlite3.Connection, report: dict[str, Any], *, now: float) -> int:
    """只补 `goodwill_anchor` 为 NULL 的合法行（幂等：第二次 0）。affinity/z_latent 永不改。"""
    if not report["has_anchor_column"]:
        raise SystemExit("目标库无 goodwill_anchor 列（未经 _ensure_schema 建表）—— 不猜结构，拒绝写")
    conn.row_factory = sqlite3.Row
    written = 0
    rows = conn.execute(
        "SELECT sender_id, affinity, z_latent, created_at, goodwill_anchor FROM user_affinity"
    ).fetchall()
    for row in rows:
        r = inspect_row(row["affinity"], row["z_latent"], row["created_at"],
                        row["goodwill_anchor"], now=now)
        if not r["would_anchor"]:
            continue
        conn.execute("UPDATE user_affinity SET goodwill_anchor=? WHERE sender_id=?",
                     (r["anchor_seed"], row["sender_id"]))
        written += 1
    return written


def open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def open_read_write(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def render(report: dict[str, Any], *, mode: str, written: int | None,
           problems: list[str], warnings: list[str] | None = None) -> str:
    c = report["counts"]
    amin = "无" if report["anchor_min"] is None else f"{report['anchor_min']:.6f}"
    amax = "无" if report["anchor_max"] is None else f"{report['anchor_max']:.6f}"
    lines = [
        "好感度 v8 存量处置（A 案恒等 + 加列）—— " + ("EXECUTE（已写副本）" if mode == "execute" else "DRY-RUN（未写任何字节）"),
        f"  行数            : {c['rows_total']}",
        f"  逐点守恒        : {c['conserved']}   （z 派生后回投展示值==原值，无人被重置）",
        f"  脏值（只点名）  : {c['dirty']}",
        f"  非预期漂移      : {c['unexpected_drift']}   （数学上不该存在，出现即须人看）",
        f"  z_latent 现推   : {c['z_latent_missing']}   （列 NULL 由 affinity 惰性派生，A 案不写它）",
        f"  待补 anchor     : {c['anchor_seeded']}   （goodwill_anchor IS NULL 的合法行）",
        f"  anchor 分布     : [{amin}, {amax}]（z 域）",
        f"  切换瞬间跳档行数: {report['tier_changed']}   （A 案恒等⇒应为 0，非 0 即红线）",
        f"  最大展示位移    : {report['max_display_shift_points']:.12f} 分",
    ]
    if written is not None:
        lines.append(f"  本次实际写回行数: {written}")
    for category, items in report["samples"].items():
        for item in items:
            lines.append(f"    [{category}] {item['sender_id']} affinity={item['affinity']!r} "
                          f"band={item['band']} anchor_seed={item['anchor_seed']}")
    if problems:
        lines.append("  守恒断言: 未通过")
        lines.extend(f"    - {p}" for p in problems)
    else:
        lines.append("  守恒断言: 通过（affinity/z_latent 零改动 / 行数不变 / 无跳档 / anchor 仅作下界）")
    for note in warnings or []:
        lines.append(f"  待人判: {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台缺省 cp936（GBK），中文/箭头字符会 UnicodeEncodeError；演练输出强制 UTF-8。
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001, S110 - 无法重配置（例如非 tty）时退回原编码，不致命。
        pass
    parser = argparse.ArgumentParser(
        description="好感度 v8 存量数值处置（缺省 DRY-RUN，绝不写生产库）")
    parser.add_argument("--db", required=True, help="好感度 SQLite 路径（必须是生产库的**副本**）")
    parser.add_argument("--execute", action="store_true", help="补写 goodwill_anchor（只写副本）")
    parser.add_argument("--json", action="store_true", help="输出机读 JSON")
    parser.add_argument("--now", type=float, default=None, help="注入的当前 epoch 秒（演练用；缺省取真实时间）")
    args = parser.parse_args(argv)

    try:
        target = guard_target_path(args.db)
    except UnsafeTargetPath as error:
        print(f"[拒绝] {error}", file=sys.stderr)
        return 2
    if not target.exists():
        print(f"[拒绝] 目标库不存在：{target}", file=sys.stderr)
        return 2

    import time as _time
    now = args.now if args.now is not None else _time.time()

    with open_read_only(target) as conn:
        before_fp = identity_fingerprint(conn)
        report = plan(conn, now=now)
    report["samples"] = {k: v[:5] for k, v in report["samples"].items()}

    written: int | None = None
    problems: list[str] = []
    planned = report["counts"]["anchor_seeded"]
    if args.execute:
        with open_read_write(target) as conn:
            fp_before = identity_fingerprint(conn)
            written = execute_plan(conn, report, now=now)
            conn.commit()
            fp_after = identity_fingerprint(conn)
            anchor_problems = check_anchors_are_lower_bound(conn)
            after_report = plan(conn, now=now)
        if fp_before != fp_after:
            problems.append("affinity/z_latent 在写回前后不一致 —— A 案绝不该动它们")
        if fp_after != before_fp:
            problems.append("affinity/z_latent 与只读阶段指纹不一致")
        problems.extend(assert_conservation(after_report, before_fp=fp_before, after_fp=fp_after,
                                             planned=planned, written=written,
                                             anchor_check_problems=anchor_problems))
        if after_report["counts"]["anchor_seeded"] != 0:
            problems.append(f"写回后仍报待补 anchor {after_report['counts']['anchor_seeded']} 行（非幂等）")
        report = after_report
    else:
        problems.extend(assert_conservation(report, before_fp=before_fp, after_fp=before_fp,
                                             planned=0, written=0, anchor_check_problems=[]))

    warnings: list[str] = []
    if report["counts"].get("dirty", 0):
        warnings.append(f"{report['counts']['dirty']} 行 affinity 非数/为空：演练只点名不写回，须人工核对来源")
    warnings.append("下一步（本脚本不替她决定）：影子记账一周→过目→正式开 bot_affinity_v8_enabled+重启")

    if args.json:
        print(json.dumps({"mode": "execute" if args.execute else "dry_run", "path": str(target),
                          "report": report, "written": written, "problems": problems,
                          "warnings": warnings}, ensure_ascii=False, indent=2, default=str))
    else:
        print(render(report, mode="execute" if args.execute else "dry_run",
                     written=written, problems=problems, warnings=warnings))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
