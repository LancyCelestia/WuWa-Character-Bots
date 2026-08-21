from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime import smoke
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.smoke import run_queue_smoke


def test_queue_smoke_drains_temp_sqlite_queue_without_real_transport(tmp_path):
    result = run_queue_smoke(
        Config(),
        db_path=tmp_path / "queue-smoke.sqlite3",
    )

    assert result["ok"] is True
    assert result["checked"] == 2
    assert result["delivered"] == 1
    assert result["retryable_failed"] == 1
    assert result["final_failed"] == 0
    assert result["queued"] == 0
    assert result["sent"] == 1
    assert result["failed_retryable"] == 1
    assert result["failed_final"] == 0
    assert result["processing"] == 0
    assert result["receipts_recorded"] == 2
    assert result["audit_events"] >= 6
    assert result["transport"] == "fake_transport"
    assert result["real_transport_used"] is False
    assert "未连接 NapCat" in result["public_message"]


def test_queue_smoke_summary_does_not_leak_target_text_or_dedupe(tmp_path):
    result = run_queue_smoke(
        Config(),
        db_path=tmp_path / "queue-smoke.sqlite3",
    )

    rendered = repr(result)

    assert "secret-target" not in rendered
    assert "不应出现在" not in rendered
    assert "dedupe" not in rendered
    assert "private_debug" not in rendered
    assert "provider_message_id" not in rendered


def test_queue_smoke_cli_prints_safe_summary(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["smoke.py", "queue"])

    exit_code = smoke.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "ok=true" in output
    assert "checked=2" in output
    assert "delivered=1" in output
    assert "retryable_failed=1" in output
    assert "real_transport_used=false" in output
    assert "未连接 NapCat" in output
    assert "secret-target" not in output
    assert "不应出现在" not in output
    assert "dedupe" not in output
    assert "provider_message_id" not in output


def test_dev_script_exposes_queue_smoke_task():
    text = Path("scripts/dev.ps1").read_text(encoding="utf-8-sig")

    assert '"queue-smoke"' in text
    assert "Invoke-QueueSmoke" in text
    assert "plugins.bot_unified_runtime.smoke" in text
    assert '"queue"' in text
