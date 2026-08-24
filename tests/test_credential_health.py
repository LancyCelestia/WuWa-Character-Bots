import json
from datetime import UTC, datetime, timedelta

from plugins.bot_unified_runtime.sources.credential_health import (
    STATE_EXPIRED,
    STATE_EXPIRING_SOON,
    STATE_OK,
    STATE_UNKNOWN,
    CredentialHealthChecker,
)
from plugins.bot_unified_runtime.sources.credentials import FileCredentialStore


def _make_store(tmp_path, expires_at: str) -> FileCredentialStore:
    store_path = tmp_path / "credentials.json"
    store_path.write_text(
        json.dumps(
            {
                "refs": {
                    "bilibili": {
                        "kind": "cookie",
                        "value": "SESSDATA=x",
                        "expires_at": expires_at,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return FileCredentialStore(store_path)


def test_health_check_expired(tmp_path):
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    store = _make_store(tmp_path, past)
    checker = CredentialHealthChecker(store, warn_days=7)

    reports = checker.check()

    assert len(reports) == 1
    assert reports[0].state == STATE_EXPIRED
    assert reports[0].needs_reauth is True
    assert "重新登录" in reports[0].detail
    assert "SESSDATA=x" not in reports[0].detail


def test_health_check_expiring_soon(tmp_path):
    soon = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    store = _make_store(tmp_path, soon)
    checker = CredentialHealthChecker(store, warn_days=7)

    report = checker.check()[0]

    assert report.state == STATE_EXPIRING_SOON
    assert report.needs_reauth is False


def test_health_check_ok(tmp_path):
    later = (datetime.now(UTC) + timedelta(days=90)).isoformat()
    store = _make_store(tmp_path, later)
    checker = CredentialHealthChecker(store, warn_days=7)

    report = checker.check()[0]

    assert report.state == STATE_OK
    assert report.needs_reauth is False


def test_health_check_unknown_when_no_expiry(tmp_path):
    store = _make_store(tmp_path, "")
    checker = CredentialHealthChecker(store, warn_days=7)

    report = checker.check()[0]

    assert report.state == STATE_UNKNOWN
    assert "expires_at" in report.detail


def test_health_check_empty_store():
    class EmptyStore:
        def resolve(self, ref_id: str):
            return None

        def refs(self):
            return []

    checker = CredentialHealthChecker(EmptyStore())

    assert checker.check() == []
