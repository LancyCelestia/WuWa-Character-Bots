"""人格切换 REST 段的行为锁。

钉的是什么
----
`BOT_PERSONA_PROFILE_ID` 是装配期主人格档，既不在 SETTABLE_KEYS 也不在
RESTART_REQUIRED_KEYS；人格切换的真身是 runtime settings 的 `persona_override`
（`/bot runtime persona switch` 同一落点）。本路由把它暴露给 WebUI，写面
只要求 super_admin。锁四件事：

① GET 如实报告 active_override / effective / 在册人格；
② POST 写入 override，下一轮生效（restart_required=False）；
③ expected_current 不符 ⇒ 409，不覆盖别人的切换；
④ 未在册的 id ⇒ 404；写依赖存在（读 token 不能切人格）。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane.api import ControlPlaneError
from plugins.bot_unified_runtime.control_plane.api.persona import build_persona_router


class _Store:
    def __init__(self) -> None:
        self.override = ""

    def get_persona_override(self) -> str:
        return self.override

    def set_persona_override(self, profile_id: str) -> None:
        self.override = profile_id


def _client(store: _Store, *, deny_write: bool = False) -> TestClient:
    def read_ok() -> None:
        return None

    def write_ok() -> None:
        return None

    def write_denied() -> None:
        from plugins.bot_unified_runtime.control_plane.api import ControlPlaneError

        raise ControlPlaneError(403, "forbidden", "此操作需要 super_admin 权限。")

    app = FastAPI()

    @app.exception_handler(ControlPlaneError)
    def _error(_request: Request, exc: ControlPlaneError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"data": None, "error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(
        build_persona_router(
            settings_store=store,
            config=None,
            read_dependency=read_ok,
            write_dependency=write_denied if deny_write else write_ok,
            prefix="/api/v1",
        )
    )
    return TestClient(app)


def test_get_reports_override_and_profiles() -> None:
    body = _client(_Store()).get("/api/v1/persona").json()
    data = body["data"]
    assert data["active_override"] == ""
    assert data["effective"]
    assert data["restart_required"] is False
    assert data["apply"] == "next_message"
    assert isinstance(data["items"], list)


def test_switch_persists_and_is_hot() -> None:
    store = _Store()
    client = _client(store)
    response = client.post(
        "/api/v1/persona/active",
        json={"profile_id": "shorekeeper", "expected_current": ""},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["active_override"] == "shorekeeper"
    assert data["effective"] == "shorekeeper"
    assert store.override == "shorekeeper"


def test_stale_expected_current_conflicts() -> None:
    store = _Store()
    store.override = "other"
    response = _client(store).post(
        "/api/v1/persona/active",
        json={"profile_id": "shorekeeper", "expected_current": ""},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "persona_version_conflict"
    assert store.override == "other"


def test_unknown_profile_is_404() -> None:
    store = _Store()
    response = _client(store).post(
        "/api/v1/persona/active",
        json={"profile_id": "no-such-persona", "expected_current": ""},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "persona_not_found"
    assert store.override == ""


def test_write_requires_super_admin_dependency() -> None:
    response = _client(_Store(), deny_write=True).post(
        "/api/v1/persona/active",
        json={"profile_id": "shorekeeper", "expected_current": ""},
    )
    assert response.status_code == 403
