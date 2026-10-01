"""好感度 v8 存量处置迁移脚本 `scripts/migrate_affinity_v8.py` 的行为锁（需求项 13 / 席位 SEAT-AFFINITY）。

对账：docs/affinity-design.md §E（A 案恒等 + 加列）与 §F「迁移幂等 + 守恒 + 可逆」判据。
本件把脚本的四条硬承诺钉成机器可查：
1. **缺省 DRY-RUN 零写入**：跑一遍 goodwill_anchor 全 NULL 不变、affinity 不动、rc=0；
2. **只写副本、拒生产**：目标路径落 ChatBot_Runtime ⇒ UnsafeTargetPath（不建库也能拦）；
3. **A 案恒等**：--execute 前后 (affinity, z_latent) 指纹逐字节相等、行数不变、切换零跳档；
4. **幂等 + 下界不变量 + 牙齿**：第二次 --execute 写 0 行；anchor 恒 ≤ z；
   注毒负样本（anchor>z、漏投、跳档/漂移）⇒ 守恒断言必红（§F「断言永不失败是 A 案的平凡，
   注毒负样本才是牙齿」）。

全部离线：tmp_path 裸建库，绝不落 ChatBot_Runtime、绝不写源码树 data/。
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import math
import sqlite3
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "migrate_affinity_v8.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("migrate_affinity_v8", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m8 = _load_module()


def _ts(days_ago: float) -> str:
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days_ago)).isoformat()


def _build_fixture(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE user_affinity(sender_id TEXT PRIMARY KEY, affinity REAL,"
        " z_latent REAL, created_at TEXT, goodwill_anchor REAL,"
        " v8_state TEXT NOT NULL DEFAULT '{}')"
    )
    rows = [
        ("u_base", 0.1, None, _ts(0)),
        ("u_mid", 0.5, None, _ts(30)),
        ("u_veteran", 0.72478, None, _ts(500)),   # 一年以上老用户（band 收窄端）
        ("u_neg", -0.04175, None, _ts(5)),
        ("u_withz", math.tanh(0.9), 0.9, _ts(100)),  # 已有 z_latent
        ("u_null", None, None, _ts(1)),           # 脏：affinity 为空
        ("u_nan", float("nan"), float("nan"), _ts(1)),  # 脏：非数
    ]
    conn.executemany(
        "INSERT INTO user_affinity(sender_id, affinity, z_latent, created_at) VALUES (?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def _anchors(path: Path) -> dict[str, float | None]:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    out = {str(r["sender_id"]): r["goodwill_anchor"]
           for r in conn.execute("SELECT sender_id, goodwill_anchor FROM user_affinity")}
    conn.close()
    return out


def test_dry_run_writes_nothing(tmp_path) -> None:
    db = tmp_path / "fixture.sqlite3"
    _build_fixture(db)
    before = _anchors(db)
    assert all(v is None for v in before.values())
    rc = m8.main(["--db", str(db), "--now", str(m8._epoch_seconds(_ts(0)) + 1)])
    assert rc == 0
    after = _anchors(db)
    assert after == before, "DRY-RUN 竟写入了 goodwill_anchor"


def test_plan_reports_zero_tier_jump_and_identity(tmp_path) -> None:
    db = tmp_path / "fixture.sqlite3"
    _build_fixture(db)
    now = m8._epoch_seconds(_ts(0)) + 1
    with m8.open_read_only(db) as conn:
        report = m8.plan(conn, now=now)
    c = report["counts"]
    assert c["rows_total"] == 7
    assert c["conserved"] == 5
    assert c["dirty"] == 2
    assert c["unexpected_drift"] == 0
    assert report["tier_changed"] == 0, "A 案恒等下切换瞬间不得跳档"
    assert report["max_display_shift_points"] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("flag", ["ChatBot_Runtime", "ChatBot_runtime", "ChatBot_Archive"])
def test_guard_refuses_runtime_paths(flag) -> None:
    fake = f"/somewhere/{flag}/data/user_affinity.sqlite3"
    with pytest.raises(m8.UnsafeTargetPath):
        m8.guard_target_path(fake)


def test_execute_is_identity_and_idempotent(tmp_path) -> None:
    db = tmp_path / "fixture.sqlite3"
    _build_fixture(db)
    now = m8._epoch_seconds(_ts(0)) + 1
    with m8.open_read_only(db) as conn:
        fp_before = m8.identity_fingerprint(conn)
        seeded = m8.plan(conn, now=now)["counts"]["anchor_seeded"]
    assert seeded == 5  # 五合法行 anchor 皆 NULL
    rc = m8.main(["--db", str(db), "--execute", "--now", str(now)])
    assert rc == 0
    anchors = _anchors(db)
    assert sum(1 for v in anchors.values() if v is not None) == 5
    assert anchors["u_null"] is None and anchors["u_nan"] is None, "脏行被误写"
    # 幂等：第二次 execute 写 0 行、rc 仍 0
    rc2 = m8.main(["--db", str(db), "--execute", "--now", str(now)])
    assert rc2 == 0
    # 恒等：affinity/z_latent 指纹一字未改
    with m8.open_read_only(db) as conn:
        fp_after = m8.identity_fingerprint(conn)
        anchor_problems = m8.check_anchors_are_lower_bound(conn)
    assert fp_after == fp_before, "A 案迁移竟改动了 affinity/z_latent"
    assert anchor_problems == [], f"anchor 越出下界不变量：{anchor_problems}"


def test_poison_anchor_above_z_is_caught(tmp_path) -> None:
    """注毒负样本（§F 牙齿）：手工把一行 anchor 写成 z+0.1 ⇒ 下界检查必红。"""
    db = tmp_path / "fixture.sqlite3"
    _build_fixture(db)
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE user_affinity SET goodwill_anchor=? WHERE sender_id='u_withz'",
                 (math.atanh(0.9) + 0.1,))
    conn.commit()
    problems = m8.check_anchors_are_lower_bound(conn)
    conn.close()
    assert problems, "守恒牙齿失效：anchor>z 未被抓住"


def test_poison_skip_and_tier_drift_break_conservation() -> None:
    """注毒：漏投（planned≠written）与档位漂移 ⇒ assert_conservation 必红。"""
    fp = (("u_withz", 0.5, math.atanh(0.5)),)
    report_skip = {"counts": {"rows_total": 1, "conserved": 1, "unexpected_drift": 0},
                   "tier_changed": 0}
    problems = m8.assert_conservation(report_skip, before_fp=fp, after_fp=fp,
                                      planned=3, written=1,
                                      anchor_check_problems=["1 行 goodwill_anchor 高于 z_latent（下界越界）"])
    assert any("计划写入" in p for p in problems)
    assert any("下界" in p for p in problems)
    report_tier = {"counts": {"rows_total": 1, "conserved": 0, "unexpected_drift": 1},
                   "tier_changed": 2}
    problems2 = m8.assert_conservation(report_tier, before_fp=fp, after_fp=fp,
                                       planned=0, written=0, anchor_check_problems=[])
    assert any("跳档" in p for p in problems2)
    assert any("漂移" in p for p in problems2)


def test_old_veteran_gets_narrower_anchor_than_newcomer(tmp_path) -> None:
    """善意底随相处时长收紧的迁移面证据：老用户 anchor₀ 比新人更接近其 z（band 更小）。"""
    db = tmp_path / "fixture.sqlite3"
    _build_fixture(db)
    now = m8._epoch_seconds(_ts(0)) + 1
    with m8.open_read_only(db) as conn:
        rows = {str(r["sender_id"]): r for r in conn.execute(
            "SELECT sender_id, affinity, z_latent, created_at FROM user_affinity")}
    seed_vet = m8.inspect_row(rows["u_veteran"]["affinity"], rows["u_veteran"]["z_latent"],
                              rows["u_veteran"]["created_at"], None, now=now)
    seed_base = m8.inspect_row(rows["u_base"]["affinity"], rows["u_base"]["z_latent"],
                               rows["u_base"]["created_at"], None, now=now)
    assert seed_vet["band"] < seed_base["band"], "老用户保护带未比新人收紧"
    # anchor 离 z 的距离＝band（z−anchor），老用户更贴 z
    vet_gap = seed_vet["z"] - seed_vet["anchor_seed"]
    base_gap = seed_base["z"] - seed_base["anchor_seed"]
    assert vet_gap < base_gap, "老用户 anchor₀ 未比新人更贴近其高度"
