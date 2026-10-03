"""落盘点寿命清扫（``restricted_runner.sweep_expired_files``）回归——席6 供件。

锁六件事（与简报第 4 条逐条对应）：

① 只删登记根内的旧文件：TTL 内的新件、子目录里的件（不递归）一律不动；
② TTL <= 0 ＝清扫关闭：一枚都不删，绝不把 0 解释成「全删」；
③ 单次删除上限保险丝：候选超预算时到顶即停、如实上报 ``cap_reached``，
   多余的件留在盘上；
④ **删前计数**审计行在删除动作之前落日志（顺序不可颠倒）；
⑤ 逐根结论完整（scanned/candidates/deleted/failed/skipped），不存在的根折成
   空结论、绝不抛异常；
⑥ ``sweep_ttl_days_from_config``：键缺席/垃圾值回落缺省 7 天，显式 0 原样交回。

全部落点在 ``tmp_path``；mtime 用 ``os.utime`` 受控回拨，零真实等待。
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.files.sender import restricted_runner as rr

_NOW = 1_700_000_000.0


def _backdate(path: Path, *, age_days: float) -> None:
    stamp = _NOW - age_days * 86400.0
    os.utime(path, (stamp, stamp))


@pytest.fixture
def incoming(tmp_path: Path) -> Path:
    root = tmp_path / "incoming"
    root.mkdir()
    return root


def _sweep(root: Path, **kwargs: object) -> list[rr.SweepOutcome]:
    return rr.sweep_expired_files([root], now=_NOW, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ① 只删登记根内的旧文件
# ---------------------------------------------------------------------------


def test_old_file_deleted_and_fresh_file_kept(incoming: Path, caplog: pytest.LogCaptureFixture) -> None:
    old = incoming / "old_report.txt"
    old.write_text("旧的", encoding="utf-8")
    fresh = incoming / "fresh.txt"
    fresh.write_text("新的", encoding="utf-8")
    _backdate(old, age_days=8.0)
    _backdate(fresh, age_days=1.0)

    with caplog.at_level(logging.INFO, logger=rr.__name__):
        outcomes = _sweep(incoming, ttl_days=7.0)

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert (outcome.scanned, outcome.candidates, outcome.deleted) == (2, 1, 1)
    assert outcome.cap_reached is False
    assert not old.exists(), "超龄件应被删除"
    assert fresh.exists(), "TTL 内的新件不许动"
    # ④ 删前计数行必须在逐件删除行之前（顺序不可颠倒）。
    messages = [record.getMessage() for record in caplog.records]
    count_lines = [i for i, m in enumerate(messages) if "候选=1" in m and "删前计数" in m]
    delete_lines = [i for i, m in enumerate(messages) if "已删 old_report.txt" in m]
    assert count_lines and delete_lines, f"审计日志缺行：{messages}"
    assert max(count_lines) < min(delete_lines), "删前计数必须发生在删除之前"


def test_boundary_age_is_deleted_only_at_or_past_ttl(incoming: Path) -> None:
    exact = incoming / "exact.txt"
    within = incoming / "within.txt"
    exact.write_text("恰满", encoding="utf-8")
    within.write_text("差一点", encoding="utf-8")
    _backdate(exact, age_days=7.0)
    _backdate(within, age_days=6.999)
    _sweep(incoming, ttl_days=7.0)
    assert not exact.exists(), "恰满 TTL 的件按「≥ 才删」口径应被删除"
    assert within.exists()


def test_subdirectories_are_never_touched_non_recursive(incoming: Path) -> None:
    nested = incoming / "nested"
    nested.mkdir()
    deep_old = nested / "deep_old.txt"
    deep_old.write_text("子目录里的旧件", encoding="utf-8")
    _backdate(deep_old, age_days=30.0)
    outcomes = _sweep(incoming, ttl_days=7.0)
    assert nested.exists() and deep_old.exists(), "清扫不递归子目录"
    assert outcomes[0].skipped >= 1
    assert outcomes[0].deleted == 0


def test_forbidden_roster_entry_is_skipped_and_counted(incoming: Path) -> None:
    """Parity 腿（自被出账的 exchange 版移植）：禁触名册在册件跳过不删。

    禁触判定零副本，走 ``_forbidden_destination_reason``（唯一真身 ``paths.py``）；
    名册命中与年龄无关——在册件哪怕早过 TTL 也一枚不许动。
    """
    key = incoming / "server.key"
    key.write_text("密钥形态的在册件", encoding="utf-8")
    _backdate(key, age_days=30.0)
    normal = incoming / "old_report.txt"
    normal.write_text("普通过期件", encoding="utf-8")
    _backdate(normal, age_days=30.0)

    outcome = _sweep(incoming, ttl_days=7.0)[0]

    assert key.exists(), "禁触名册在册件不许被清扫"
    assert not normal.exists(), "普通过期件照常删除"
    assert outcome.skipped_forbidden == 1, "禁触跳过必须单独计数"
    assert (outcome.candidates, outcome.deleted) == (1, 1)


# ---------------------------------------------------------------------------
# ② 关闭语义 ③ 上限保险丝 ⑤ 空根
# ---------------------------------------------------------------------------


def test_non_positive_ttl_disables_the_sweep(incoming: Path) -> None:
    old = incoming / "old.txt"
    old.write_text("旧的", encoding="utf-8")
    _backdate(old, age_days=365.0)
    for ttl in (0.0, -1.0):
        assert rr.sweep_expired_files([incoming], ttl_days=ttl, now=_NOW) == []
    assert old.exists(), "TTL<=0 是关闭语义，一枚都不许删"


def test_deletion_cap_stops_with_cap_reached(incoming: Path) -> None:
    for index in range(3):
        item = incoming / f"old_{index}.txt"
        item.write_text("旧的", encoding="utf-8")
        _backdate(item, age_days=10.0)
    outcomes = _sweep(incoming, ttl_days=7.0, max_deletions=2)
    outcome = outcomes[0]
    assert (outcome.candidates, outcome.deleted) == (3, 2)
    assert outcome.cap_reached is True, "候选超预算必须如实上报"
    survivors = sorted(p.name for p in incoming.iterdir())
    assert len(survivors) == 1, f"上限之外应留下 1 件，现场 {survivors}"


def test_exact_budget_does_not_report_cap(incoming: Path) -> None:
    for index in range(2):
        item = incoming / f"old_{index}.txt"
        item.write_text("旧的", encoding="utf-8")
        _backdate(item, age_days=10.0)
    outcome = _sweep(incoming, ttl_days=7.0, max_deletions=2)[0]
    assert outcome.cap_reached is False, "候选恰等于预算＝删干净了，不是到顶"


def test_missing_root_yields_empty_outcome_without_raising(tmp_path: Path) -> None:
    ghost = tmp_path / "no_such_dir"
    outcomes = rr.sweep_expired_files([ghost, ""], now=_NOW)
    assert [o.root for o in outcomes] == [str(ghost)]
    assert (outcomes[0].scanned, outcomes[0].deleted) == (0, 0)


# ---------------------------------------------------------------------------
# ⑥ 配置现算口
# ---------------------------------------------------------------------------


def test_ttl_days_from_config_fallbacks() -> None:
    assert rr.sweep_ttl_days_from_config(
        SimpleNamespace(bot_files_incoming_ttl_days=3)
    ) == 3.0
    assert rr.sweep_ttl_days_from_config(SimpleNamespace()) == rr.DEFAULT_SWEEP_TTL_DAYS
    assert rr.sweep_ttl_days_from_config(
        SimpleNamespace(bot_files_incoming_ttl_days="垃圾")
    ) == rr.DEFAULT_SWEEP_TTL_DAYS
    assert rr.sweep_ttl_days_from_config(
        SimpleNamespace(bot_files_incoming_ttl_days=0)
    ) == 0.0, "显式 0 原样交回＝关闭，不许被缺省值吃掉"


def test_sweep_never_raises_on_undatable_file(incoming: Path) -> None:
    """stat 坏掉的件跳过不删（failed 计数），清扫整体照常交付。"""

    good = incoming / "good_old.txt"
    good.write_text("旧的", encoding="utf-8")
    _backdate(good, age_days=8.0)

    real_stat = Path.stat

    def flaky_stat(self: Path, **kwargs: object) -> os.stat_result:
        if self.name == "cursed.txt":
            raise OSError("注毒：stat 不可用")
        return real_stat(self, **kwargs)  # type: ignore[arg-type]

    cursed = incoming / "cursed.txt"
    cursed.write_text("读不出日期的件", encoding="utf-8")
    _backdate(cursed, age_days=8.0)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(Path, "stat", flaky_stat)
    try:
        outcomes = _sweep(incoming, ttl_days=7.0)
    finally:
        monkeypatch.undo()
    outcome = outcomes[0]
    assert outcome.deleted == 1 and outcome.failed == 1
    assert not good.exists() and cursed.exists(), "日期读不出的件不许删"


def test_default_ttl_constant_matches_briefing() -> None:
    assert rr.DEFAULT_SWEEP_TTL_DAYS == 7.0, "缺省寿命与简报口径（7 天）锁定"
    assert time.strftime("%Y") >= "2026"  # 环境哨兵：时钟没跑偏到不可信
