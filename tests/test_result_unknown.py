from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.runtime.result_unknown import ResultUnknownLedger


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _ledger(tmp_path: Path, clock: _FakeClock) -> ResultUnknownLedger:
    return ResultUnknownLedger(
        tmp_path / "result_unknown.sqlite3",
        expire_seconds=3600.0,
        clock=clock,
    )


def test_record_deduplicates_by_request_id(tmp_path) -> None:
    clock = _FakeClock()
    ledger = _ledger(tmp_path, clock)

    assert ledger.record(request_id="r1", adapter="onebot", bot_id="10000") is True
    assert ledger.record(request_id="r1", adapter="onebot", bot_id="10000") is False
    assert ledger.pending_count() == 1


def test_reconcile_marks_expired_and_reports_pending(tmp_path) -> None:
    clock = _FakeClock()
    ledger = _ledger(tmp_path, clock)
    ledger.record(request_id="old", adapter="onebot", bot_id="10000")
    clock.advance(7200.0)
    ledger.record(request_id="fresh", adapter="onebot", bot_id="20000")

    summary = ledger.reconcile(bot_id="20000")

    assert summary.expired == 1
    assert summary.pending == 1
    assert summary.by_bot == {"20000": 1}
    assert ledger.pending_count() == 1


def test_record_ignores_blank_identifiers(tmp_path) -> None:
    ledger = _ledger(tmp_path, _FakeClock())
    assert ledger.record(request_id="", adapter="onebot", bot_id="b") is False
    assert ledger.record(request_id="r", adapter="", bot_id="b") is False
    assert ledger.pending_count() == 0
