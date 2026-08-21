import json

from plugins.wuwa_unified_runtime.sources.credentials import (
    CredentialMissingError,
    FileCredentialStore,
    build_credential_headers,
    resolve_credential,
)


def test_file_credential_store_resolves_cookie_ref(tmp_path):
    store_path = tmp_path / "credentials.json"
    store_path.write_text(
        json.dumps(
            {
                "refs": {
                    "bilibili": {
                        "kind": "cookie",
                        "value": "SESSDATA=secret-cookie-value",
                        "domain": ".bilibili.com",
                        "expires_at": "2026-12-31",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    store = FileCredentialStore(store_path)

    value = resolve_credential(store, "bilibili")

    assert value.kind == "cookie"
    assert value.value == "SESSDATA=secret-cookie-value"
    assert value.domain == ".bilibili.com"
    refs = store.refs()
    assert len(refs) == 1
    assert refs[0].ref_id == "bilibili"
    assert "secret-cookie-value" not in refs[0].masked_preview
    assert refs[0].masked_preview.endswith("(len=28)")


def test_file_credential_store_missing_ref_raises(tmp_path):
    store = FileCredentialStore(tmp_path / "missing.json")

    assert store.resolve("unknown") is None
    try:
        resolve_credential(store, "unknown")
    except CredentialMissingError as exc:
        assert "unknown" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected CredentialMissingError")


def test_file_credential_store_bad_json_is_empty(tmp_path):
    store_path = tmp_path / "bad.json"
    store_path.write_text("{not json", encoding="utf-8")
    store = FileCredentialStore(store_path)

    assert store.resolve("bilibili") is None
    assert store.refs() == []


def test_build_credential_headers_maps_kinds(tmp_path):
    store_path = tmp_path / "credentials.json"
    store_path.write_text(
        json.dumps(
            {
                "refs": {
                    "bili_cookie": {"kind": "cookie", "value": "SESSDATA=x"},
                    "bili_key": {"kind": "api_key", "value": "key-123"},
                }
            }
        ),
        encoding="utf-8",
    )
    store = FileCredentialStore(store_path)

    assert build_credential_headers(store, "bili_cookie") == {
        "Cookie": "SESSDATA=x"
    }
    assert build_credential_headers(store, "bili_key") == {
        "Authorization": "Bearer key-123"
    }
    assert build_credential_headers(
        store, "bili_cookie", header_name="X-Cookie"
    ) == {"X-Cookie": "SESSDATA=x"}
