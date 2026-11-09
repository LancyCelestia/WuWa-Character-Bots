"""Write-only credential administration; transport alone resolves plaintext."""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import asdict
from typing import Any

from .auth import Principal
from .services import ControlServiceError


class CredentialControlService:
    def __init__(self, store: Any, *, clock=time.monotonic) -> None:
        self.store, self.clock = store, clock
        self._lock = threading.Lock()
        self._confirmations: OrderedDict[str, tuple[str, str, float]] = OrderedDict()

    @staticmethod
    def _authorize(principal: Principal) -> None:
        if "super_admin" not in principal.roles:
            raise ControlServiceError("forbidden", "凭据管理需要超管权限。", 403)

    @staticmethod
    def _binding(ref_id: str, change: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(
            [ref_id, change], sort_keys=True, ensure_ascii=False, allow_nan=False,
        ).encode()).hexdigest()

    def refs(self, principal: Principal) -> dict[str, Any]:
        self._authorize(principal)
        try:
            return {"items": [asdict(ref) for ref in self.store.refs()]}
        except (ValueError, OSError):
            raise ControlServiceError("credentials_unavailable", "凭据存储不可用。", 503) from None

    def preview(self, ref_id: str, change: dict[str, Any], principal: Principal) -> dict[str, Any]:
        self._authorize(principal)
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with self._lock:
            self._confirmations = OrderedDict(
                (key, value) for key, value in self._confirmations.items() if value[2] > now
            )
            while len(self._confirmations) >= 128:
                self._confirmations.popitem(last=False)
            self._confirmations[token] = (principal.subject, self._binding(ref_id, change), now + 300)
        return {"ref_id": ref_id, "action": change["action"], "expected_version": change["expected_version"],
                "confirmation_token": token, "expires_in_seconds": 300, "value": "[write-only]"}

    def apply(self, ref_id: str, change: dict[str, Any], token: str | None, principal: Principal) -> dict[str, Any]:
        self._authorize(principal)
        with self._lock:
            confirmation = self._confirmations.pop(token or "", None)
        expected = (principal.subject, self._binding(ref_id, change))
        if confirmation is None or confirmation[:2] != expected or confirmation[2] <= self.clock():
            raise ControlServiceError("confirmation_required", "请重新预览并确认此笔凭据变更。", 409)
        try:
            if change["action"] == "delete":
                self.store.delete(ref_id, expected_version=change["expected_version"])
                return {"ref_id": ref_id, "state": "deleted"}
            metadata = {key: change[key] for key in ("kind", "domain", "expires_at")}
            if change["expected_version"] == 0:
                version = self.store.add(ref_id, change["value"], **metadata)
            else:
                version = self.store.replace(ref_id, change["value"], expected_version=change["expected_version"], **metadata)
            return {"ref_id": ref_id, "state": "replaced", "version": version}
        except ValueError:
            raise ControlServiceError("credential_change_refused", "凭据变更未完成，请检查版本或密钥状态。", 409) from None
        except OSError:
            raise ControlServiceError("credentials_unavailable", "凭据未保存，存储不可用。", 503) from None
