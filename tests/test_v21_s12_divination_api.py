"""V2.1 S12 占卜/运势 REST 端点与渲染投影套件（A15 API 席，全离线）。

合同来源：docs/design/backend-v2-product-extensions.md §3 + 验收矩阵
V21-DIVINATION-001/002/003（API 轮）。

覆盖面：
- fortune/daily：同日幂等（跨幂等键/跨会话）、时区日界、密钥轮换不重抽、
  feature_disabled（密钥未配置诚实位）；
- tarot/draw：固定 seed 复现、无放回（card_id 唯一）、阵型白名单、正逆位、
  78 张牌库完整、draw_store 配额语义（冷却/每日上限 → 429 rate_limited）；
- bazi/preview：既有算法只读投影一致性（与 data/ganzhi 直算同源）、时区换
  东八区、越界 422、每主体固定窗限速；
- REST 协议：统一 envelope（data/error/meta.schema_version=v1）、
  Idempotency-Key 头、跨类幂等键复用 409、RBAC（管理面 user 403 /
  admin 200）、服务未装配 503、LLM 解释 503 not_wired（守岸人话术池）、
  审计钩子落库（fail-open，不记 question 正文）；
- 渲染投影：build_draw_projection 形状、render_draw_card 成功/失败回退
  （假后端，零 playwright）、话术池确定性轮换。

全部离线：tmp_path SQLite + SeededPrng + 注入 clock + 假渲染后端，
无网络、无真实 LLM、无源码树写入。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from plugins.bot_unified_runtime.control_plane.api import ControlPlaneError
from plugins.bot_unified_runtime.control_plane.api.protocol import envelope
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.domains.divination.api.errors import (
    InterpretationNotWiredError,
    project_draw_error,
)
from plugins.bot_unified_runtime.domains.divination.api.facet import (
    BaziRateLimiter,
    DivinationHttpFacade,
    principal_has_role,
)
from plugins.bot_unified_runtime.domains.divination.data.tarot import DECK
from plugins.bot_unified_runtime.domains.divination.projection import (
    INTERPRETATION_PENDING_LINES,
    build_draw_projection,
    build_tarot_title,
    pick_pending_line,
    render_draw_card,
)
from plugins.bot_unified_runtime.domains.divination.routes import (
    build_divination_router,
)
from plugins.bot_unified_runtime.domains.divination.service.divination_service import (
    DISCLAIMER_TEXT,
    DivinationService,
)
from plugins.bot_unified_runtime.domains.divination.service.fortune import SeededPrng
from plugins.bot_unified_runtime.domains.divination.service.tarot_draw import (
    SPREADS,
    build_card_index,
)
from plugins.bot_unified_runtime.domains.divination.store.draw_store import (
    DrawError,
    DrawStore,
)

# ---------------------------------------------------------------------------
# 离线夹具
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


class _MutableClock:
    """可拨时钟：时区边界/密钥轮换/限速窗口测试共用。"""

    def __init__(self, start: datetime = _BASE) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: Any) -> None:
        self.now = self.now + timedelta(**kwargs)


def _make_facade(
    tmp_path: Path,
    *,
    secret: bytes = b"s12-fortune-key",
    seed: int = 20260917,
    clock: _MutableClock | None = None,
    cooldown: int = 0,
    daily: int = 20,
    fortune_ready: bool = True,
    store_path: str | None = None,
    bazi_limiter: BaziRateLimiter | None = None,
) -> DivinationHttpFacade:
    store = DrawStore(store_path or tmp_path / "draws.sqlite3")
    service = DivinationService(
        store,
        secret=secret,
        prng_factory=lambda: SeededPrng(seed),
        tarot_cooldown_seconds=cooldown,
        tarot_daily_limit=daily,
        trace_factory=lambda: "trace_s12_test",
    )
    return DivinationHttpFacade(
        service,
        bot_id="s12-bot",
        clock=clock or _MutableClock(),
        fortune_ready=fortune_ready,
        bazi_limiter=bazi_limiter,
    )


def _make_app(
    facade: DivinationHttpFacade | None,
    *,
    principal: Principal | None = None,
    audit_store: ControlPlaneAuditStore | None = None,
) -> FastAPI:
    principal = principal or Principal("s12-user", ("user",))

    async def read_dependency() -> Principal:
        return principal

    app = FastAPI()
    app.include_router(
        build_divination_router(
            facade=facade,
            read_dependency=read_dependency,
            audit_store=audit_store,
        )
    )

    def _error_body(code: str, message: str, status: int) -> dict[str, Any]:
        return envelope(
            None,
            error={
                "code": code,
                "message": message,
                "debug_id": "dbg-s12-test",
                "request_id": "req-s12-test",
                "retryable": status in (429, 503),
                "field_errors": [],
            },
        )

    @app.exception_handler(ControlPlaneError)
    async def _cp_error(request: Request, exc: ControlPlaneError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.status_code),
            headers=dict(exc.headers or {}),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body("validation_error", "请求体校验未通过", 422),
        )

    return app


_HEADERS = {"Idempotency-Key": ""}


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:8742")


def _data(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["error"] is None
    meta = body["meta"]
    assert meta["schema_version"] == "v1"
    assert meta["request_id"].startswith("req_")
    assert meta["trace_id"].startswith("trace_")
    assert meta["generated_at"]
    return body["data"]


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    error = body["error"]
    assert error is not None
    assert error["code"] == code, error
    assert error["message"]
    assert body["meta"]["schema_version"] == "v1"
    return error


def _key(name: str) -> dict[str, str]:
    return {"Idempotency-Key": f"s12-{name}"}


def _fortune_post(client: TestClient, key: str, **payload: Any) -> Any:
    return client.post(
        "/api/v1/divination/fortune/daily", json=payload, headers=_key(key)
    )


def _tarot_post(client: TestClient, key: str, **payload: Any) -> Any:
    body = {"spread_id": "single", **payload}
    return client.post(
        "/api/v1/divination/tarot/draw", json=body, headers=_key(key)
    )


# ---------------------------------------------------------------------------
# V21-DIVINATION-001：运势（幂等/时区/密钥轮换/频控/诚实位）
# ---------------------------------------------------------------------------


def test_fortune_daily_same_day_idempotent_across_keys(tmp_path: Path) -> None:
    clock = _MutableClock()
    facade = _make_facade(tmp_path, clock=clock)
    with _client(_make_app(facade)) as client:
        first = _data(_fortune_post(client, "f1"))
        second = _data(_fortune_post(client, "f2"))
    assert first["draw_id"] == second["draw_id"]
    assert first["fortune_grade"] == second["fortune_grade"]
    assert first["kind"] == "fortune"
    assert first["disclaimer_id"]
    assert first["disclaimer_text"] == DISCLAIMER_TEXT
    assert any(DISCLAIMER_TEXT in line for line in first["interpretation_lines"])


def test_fortune_timezone_day_boundary_and_same_local_day(tmp_path: Path) -> None:
    clock = _MutableClock(datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc))
    facade = _make_facade(tmp_path, clock=clock)
    with _client(_make_app(facade)) as client:
        utc_draw = _data(
            client.post(
                "/api/v1/divination/fortune/daily",
                json={"timezone_id": "UTC"},
                headers=_key("tz-utc"),
            )
        )
        cst_draw = _data(
            client.post(
                "/api/v1/divination/fortune/daily",
                json={"timezone_id": "Asia/Shanghai"},
                headers=_key("tz-cst"),
            )
        )
        # 18:00Z 在上海仍是同一本地日（09-18）→ 命中既有行。
        clock.advance(hours=2)
        later_same_local_day = _data(
            client.post(
                "/api/v1/divination/fortune/daily",
                json={"timezone_id": "Asia/Shanghai"},
                headers=_key("tz-cst-later"),
            )
        )
    # 16:00Z：UTC=09-17 vs 上海=09-18 → 不同 day_key → 不同抽取。
    assert utc_draw["draw_id"] != cst_draw["draw_id"]
    assert later_same_local_day["draw_id"] == cst_draw["draw_id"]


def test_fortune_key_rotation_does_not_redraw_same_day(tmp_path: Path) -> None:
    clock = _MutableClock()
    shared_store = tmp_path / "shared.sqlite3"
    before = _make_facade(tmp_path, secret=b"key-before", clock=clock, store_path=shared_store)
    with _client(_make_app(before)) as client:
        original = _data(_fortune_post(client, "rot-1"))
    rotated = _make_facade(tmp_path, secret=b"key-after", clock=clock, store_path=shared_store)
    with _client(_make_app(rotated)) as client:
        after_rotation = _data(_fortune_post(client, "rot-2"))
        clock.advance(days=1)
        next_day = _data(_fortune_post(client, "rot-3"))
    # 密钥轮换不换 day_key → 当天原样返回，不重抽。
    assert after_rotation["draw_id"] == original["draw_id"]
    # 次日（新本地日）才按新密钥开新行。
    assert next_day["draw_id"] != original["draw_id"]


def test_fortune_without_secret_is_honest_feature_disabled(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path, fortune_ready=False)
    with _client(_make_app(facade)) as client:
        error = _error(
            _fortune_post(client, "nosecret"), 409, "feature_disabled"
        )
    assert "密钥" in error["message"]


def test_cross_kind_idempotency_key_conflict(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path)
    app = _make_app(facade)
    with _client(app) as client:
        payload = {"spread_id": "single"}
        assert (
            client.post(
                "/api/v1/divination/draws",
                json={"kind": "tarot", **payload},
                headers=_key("dup"),
            ).status_code
            == 200
        )
        _error(
            client.post(
                "/api/v1/divination/draws",
                json={"kind": "fortune"},
                headers=_key("dup"),
            ),
            409,
            "idempotency_conflict",
        )


def test_draw_endpoint_requires_idempotency_key_header(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path)
    with _client(_make_app(facade)) as client:
        _error(
            client.post(
                "/api/v1/divination/draws", json={"kind": "tarot"}
            ),
            422,
            "validation_error",
        )


def test_payload_dto_rejects_unknown_fields_and_principal_smuggling() -> None:
    from plugins.bot_unified_runtime.domains.divination.api.dto import (
        DivinationDrawPayload,
    )

    with pytest.raises(ValidationError):
        DivinationDrawPayload.model_validate(
            {"kind": "tarot", "principal_id": "spoofed"}
        )
    with pytest.raises(ValidationError):
        DivinationDrawPayload.model_validate({"kind": "bazi"})


# ---------------------------------------------------------------------------
# V21-DIVINATION-002：塔罗（seed 复现/无放回/阵型/78 张/配额/渲染回退）
# ---------------------------------------------------------------------------


def test_tarot_fixed_seed_reproducible_across_stores(tmp_path: Path) -> None:
    cards_a = _data(
        _tarot_post(_client(_make_app(_make_facade(tmp_path, seed=77))), "seed-a", spread_id="past_present_future")
    )["cards"]
    cards_b = _data(
        _tarot_post(
            _client(_make_app(_make_facade(tmp_path, seed=77, store_path=tmp_path / "b.sqlite3"))),
            "seed-b",
            spread_id="past_present_future",
        )
    )["cards"]
    assert cards_a == cards_b  # 固定 seed：同参数逐字节复现
    assert len(cards_a) == 3


def test_tarot_no_replacement_positions_and_orientations(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path, seed=42, daily=50)
    with _client(_make_app(facade)) as client:
        spread = _data(
            _tarot_post(client, "cc", spread_id="celtic_cross")
        )
    cards = spread["cards"]
    _count, positions = SPREADS["celtic_cross"]
    assert [card["position_id"] for card in cards] == list(positions)
    card_ids = [card["card_id"] for card in cards]
    assert len(set(card_ids)) == len(card_ids)  # 无放回：同一次抽取内零重复
    assert all(card["orientation"] in {"upright", "reversed"} for card in cards)
    single = _data(_tarot_post(_client(_make_app(_make_facade(tmp_path, seed=43, store_path=tmp_path / "s.sqlite3"))), "sg"))
    assert len(single["cards"]) == 1 and single["cards"][0]["position_id"] == ""


def test_deck_is_complete_78_cards_and_exposed(tmp_path: Path) -> None:
    index = build_card_index()
    assert len(DECK) == 78
    assert len(index) == 78
    facade = _make_facade(tmp_path)
    with _client(_make_app(facade)) as client:
        capabilities = _data(client.get("/api/v1/divination/capabilities"))
    assert capabilities["deck"]["size"] == 78
    assert capabilities["deck"]["revision"]
    assert set(capabilities["kinds"]["tarot"]["spreads"]) == set(SPREADS)


def test_tarot_invalid_spread_rejected(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path)
    with _client(_make_app(facade)) as client:
        _error(
            _tarot_post(client, "bad", spread_id="horseshoe"), 422, "invalid_spread"
        )


def test_tarot_quota_reuses_draw_store_semantics(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path, cooldown=0, daily=2, seed=1)
    app = _make_app(facade)
    with _client(app) as client:
        assert _tarot_post(client, "q1").status_code == 200
        assert _tarot_post(client, "q2").status_code == 200
        _error(_tarot_post(client, "q3"), 429, "rate_limited")
        # 运势不入抽取配额：塔罗限流后运势照常幂等可用。
        assert _fortune_post(client, "q4").status_code == 200


def test_prng_factory_reseeded_per_draw_keeps_replay_discipline(tmp_path: Path) -> None:
    """同 seed 工厂下每次抽取重放同序列（服务契约：测试注入 seed 可复现）。"""
    facade = _make_facade(tmp_path, seed=9, cooldown=0)
    with _client(_make_app(facade)) as client:
        first = _data(_tarot_post(client, "r1"))
        second = _data(_tarot_post(client, "r2"))
    assert first["cards"] == second["cards"]


# ---------------------------------------------------------------------------
# LLM 解释席位：503 not_wired 诚实位 + 守岸人话术池
# ---------------------------------------------------------------------------


def test_interpretation_endpoint_is_honest_not_wired(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path)
    with _client(_make_app(facade)) as client:
        draw = _data(_tarot_post(client, "iw", spread_id="single"))
        error = _error(
            client.post(f"/api/v1/divination/draws/{draw['draw_id']}/interpretation"),
            503,
            "not_wired",
        )
        assert pick_pending_line(draw["draw_id"]) in error["message"]
        # 未知的 draw：404 优先于 not_wired。
        _error(
            client.post("/api/v1/divination/draws/draw_missing/interpretation"),
            404,
            "resource_not_found",
        )
    assert len(INTERPRETATION_PENDING_LINES) >= 3


def test_pending_line_pool_is_deterministic(tmp_path: Path) -> None:
    assert pick_pending_line("draw_a") == pick_pending_line("draw_a")
    assert all(line for line in INTERPRETATION_PENDING_LINES)


def test_draw_error_projection_maps_registry_codes() -> None:
    assert project_draw_error(DrawError("invalid_spread")).status_code == 422
    assert project_draw_error(DrawError("rate_limited")).retryable is True
    not_wired = InterpretationNotWiredError("还没接线")
    assert (not_wired.status_code, not_wired.code) == (503, "not_wired")


# ---------------------------------------------------------------------------
# V21-DIVINATION-003：bazi 只读投影 + 限速
# ---------------------------------------------------------------------------


def test_bazi_preview_matches_existing_algorithm(tmp_path: Path) -> None:
    from zoneinfo import ZoneInfo

    from plugins.bot_unified_runtime.domains.divination.data.ganzhi import bazi_chart

    facade = _make_facade(tmp_path)
    payload = {
        "year": 2024,
        "month": 6,
        "day": 1,
        "hour": 12,
        "minute": 30,
        "timezone_id": "Asia/Shanghai",
    }
    with _client(_make_app(facade)) as client:
        data = _data(client.post("/api/v1/divination/bazi/preview", json=payload))
        again = _data(client.post("/api/v1/divination/bazi/preview", json=payload))
    assert data == again  # 只读投影：确定性
    chart = bazi_chart(
        datetime(2024, 6, 1, 12, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert data["day_master"] == chart.day_master
    assert data["pillars"][2]["pillar"] == chart.day_pillar.name
    assert data["element_counts"] == dict(chart.element_counts)
    assert data["body_text"]
    assert "仅供娱乐" in data["body_text"]
    assert data["disclaimer_text"] == DISCLAIMER_TEXT


def test_bazi_preview_converts_requested_timezone_to_cst(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path)
    with _client(_make_app(facade)) as client:
        data = _data(
            client.post(
                "/api/v1/divination/bazi/preview",
                json={
                    "year": 2024,
                    "month": 6,
                    "day": 1,
                    "hour": 16,
                    "timezone_id": "UTC",
                },
            )
        )
    # UTC 16:00 = 东八区次日 00:00：算法按北京时间口径落位。
    assert data["moment_cst"].startswith("2024-06-02")
    assert data["requested_timezone"] == "UTC"


def test_bazi_preview_out_of_range_is_validation_error(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path)
    with _client(_make_app(facade)) as client:
        _error(
            client.post(
                "/api/v1/divination/bazi/preview",
                json={"year": 1800, "month": 1, "day": 1, "hour": 0},
            ),
            422,
            "validation_error",
        )


def test_bazi_preview_rate_limited_per_principal(tmp_path: Path) -> None:
    ticker = {"now": 1_000_000.0}
    limiter = BaziRateLimiter(
        max_per_window=2, window_seconds=60.0, clock=lambda: ticker["now"]
    )
    facade = _make_facade(tmp_path, bazi_limiter=limiter)
    body = {"year": 2024, "month": 6, "day": 1, "hour": 12}
    with _client(_make_app(facade)) as client:
        assert client.post("/api/v1/divination/bazi/preview", json=body).status_code == 200
        assert client.post("/api/v1/divination/bazi/preview", json=body).status_code == 200
        _error(
            client.post("/api/v1/divination/bazi/preview", json=body),
            429,
            "rate_limited",
        )
        ticker["now"] += 61.0
        assert client.post("/api/v1/divination/bazi/preview", json=body).status_code == 200


# ---------------------------------------------------------------------------
# REST 协议面：RBAC / 未装配 503 / 审计钩子
# ---------------------------------------------------------------------------


def test_admin_face_requires_admin_role(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path)
    with _client(_make_app(facade, principal=Principal("u1", ("user",)))) as client:
        _error(client.get("/api/v1/divination/config"), 403, "permission_denied")
    with _client(_make_app(facade, principal=Principal("a1", ("admin",)))) as client:
        policy = _data(client.get("/api/v1/divination/config"))
    assert policy["fortune_rule_version"]
    assert policy["llm_interpretation"] == "not_wired"
    assert policy["side_effects"]


def test_role_hierarchy_helper() -> None:
    assert principal_has_role(("user",), "user")
    assert principal_has_role(("admin",), "user")
    assert principal_has_role(("super_admin",), "admin")
    assert not principal_has_role(("user",), "admin")
    assert not principal_has_role(("blocked",), "user")
    assert not principal_has_role((), "user")


def test_unprovisioned_service_is_honest_503(tmp_path: Path) -> None:
    with _client(_make_app(None)) as client:
        _error(client.get("/api/v1/divination/capabilities"), 503, "divination_unavailable")
        _error(
            client.post(
                "/api/v1/divination/draws",
                json={"kind": "tarot"},
                headers=_key("np"),
            ),
            503,
            "divination_unavailable",
        )


def test_real_control_plane_app_mounts_divination_end_to_end(tmp_path: Path) -> None:
    """真工厂装配冒烟：_app.py 挂接段 + 真读依赖（Principal.admin）+ 未配置诚实位。

    - 未配 ``bot_control_plane_divination_db`` → 真装配下 capabilities 503；
    - 配置后同一工厂重装 → 真依赖（bearer-admin ≥ user）下塔罗端到端可用。
    """
    from plugins.bot_unified_runtime.control_plane import create_control_plane_app
    from plugins.bot_unified_runtime.control_plane.auth import hash_token

    config = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("read-test-token"),
        bot_control_plane_super_admin_token_sha256=hash_token("root-test-token"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
    )
    audit_db = tmp_path / "audit.sqlite3"
    auth = {"Authorization": "Bearer read-test-token"}
    app = create_control_plane_app(
        config,
        audit_store=ControlPlaneAuditStore(str(audit_db)),
    )
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        error = _error(
            client.get("/api/v1/divination/capabilities", headers=auth),
            503,
            "divination_unavailable",
        )
        assert "装配" in error["message"]
    config.bot_control_plane_divination_db = str(tmp_path / "draws.sqlite3")
    app2 = create_control_plane_app(
        config,
        audit_store=ControlPlaneAuditStore(str(audit_db)),
    )
    with TestClient(app2, base_url="http://127.0.0.1:8742") as client:
        data = _data(
            client.post(
                "/api/v1/divination/tarot/draw",
                json={"spread_id": "single"},
                headers={**auth, **_key("s12-real-1")},
            )
        )
        assert data["kind"] == "tarot"
        assert len(data["cards"]) == 1


def test_audit_hook_records_without_question_body(tmp_path: Path) -> None:
    audit_db = tmp_path / "audit.sqlite3"
    audit_store = ControlPlaneAuditStore(str(audit_db))
    facade = _make_facade(tmp_path)
    with _client(_make_app(facade, audit_store=audit_store)) as client:
        _fortune_post(client, "audit-1", question="秘密心愿不该进审计")
        _tarot_post(client, "audit-2", spread_id="horseshoe")  # 422 失败也入审计
    with sqlite3.connect(audit_db) as connection:
        rows = connection.execute(
            "SELECT method, path, status_code, detail, query FROM control_plane_audit"
        ).fetchall()
    paths = {row[1] for row in rows}
    statuses = {row[2] for row in rows}
    assert any("fortune/daily" in path for path in paths)
    assert 200 in statuses and 422 in statuses
    blob = repr(rows)
    assert "秘密心愿" not in blob  # 审计不落用户正文


# ---------------------------------------------------------------------------
# 渲染投影：卡片模板零改动、失败回退纯文本
# ---------------------------------------------------------------------------


class _FakeBackend:
    def __init__(self, *, available: bool = True, fail: bool = False) -> None:
        self.available = available
        self.fail = fail


class _FakeRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, str]] = []

    def __call__(self, backend: Any, item: Any, *, config: Any, card_dir: str) -> dict[str, Any]:
        self.calls.append((item, card_dir))
        if backend.fail:
            raise RuntimeError("boom")
        return {"file": str(Path(card_dir) / "card.png")}


def _tarot_result(tmp_path: Path) -> Any:
    facade = _make_facade(tmp_path, seed=5, store_path=tmp_path / "p.sqlite3")
    with _client(_make_app(facade)) as client:
        return _data(_tarot_post(client, "rp", spread_id="past_present_future"))


def test_build_draw_projection_shape(tmp_path: Path) -> None:
    facade = _make_facade(tmp_path, seed=5)
    with _client(_make_app(facade)) as client:
        fortune = _data(_fortune_post(client, "proj-f"))
        tarot = _tarot_result(tmp_path)
    f_proj = build_draw_projection(_result_from(fortune))
    t_proj = build_draw_projection(_result_from(tarot))
    assert f_proj.title == "今日运势"
    assert f_proj.plain_text == f_proj.body_text
    assert DISCLAIMER_TEXT in f_proj.plain_text
    assert f_proj.card_payload is not None
    assert f_proj.card_payload.identity.platform == "divination"
    assert f_proj.card_payload.content.title == f_proj.title
    assert t_proj.title == build_tarot_title("past_present_future")
    assert len(t_proj.lines) >= 4  # 三张牌解读 + 娱乐声明


def test_render_draw_card_success_and_fallback(tmp_path: Path) -> None:
    tarot = _tarot_result(tmp_path)
    projection = build_draw_projection(_result_from(tarot))
    renderer = _FakeRenderer()
    config = SimpleNamespace(bot_card_render_dir=str(tmp_path / "cards"))
    backend_ok = _FakeBackend(available=True)
    path, plain = render_draw_card(
        projection,
        backend_ok,
        config,
        dedupe_key=projection_card_key(tarot),
        card_renderer=renderer,
    )
    assert path.endswith("card.png")
    assert plain == projection.plain_text
    item, card_dir = renderer.calls[0]
    assert item.content.title == projection.title
    assert "divination" in card_dir
    assert projection_card_key(tarot) in card_dir
    # 后端不可用 → 纯文本兜底（既有契约）。
    path2, plain2 = render_draw_card(
        projection,
        _FakeBackend(available=False),
        config,
        dedupe_key="k2",
        card_renderer=renderer,
    )
    assert path2 == "" and plain2 == projection.plain_text
    # 渲染异常 → 同一契约，绝不抛出。
    path3, plain3 = render_draw_card(
        projection,
        _FakeBackend(available=True, fail=True),
        config,
        dedupe_key="k3",
        card_renderer=renderer,
    )
    assert path3 == "" and plain3 == projection.plain_text


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _result_from(data: dict[str, Any]) -> Any:
    """REST 字形 → DrawResult（只回填投影所需字段；cards 元素补齐键）。"""
    from plugins.bot_unified_runtime.domains.divination.service.divination_service import (
        DrawResult,
    )

    cards = tuple(
        {
            "card_id": str(card.get("card_id", "")),
            "position_id": str(card.get("position_id", "")),
            "orientation": str(card.get("orientation", "upright")),
        }
        for card in data.get("cards", [])
    )
    return DrawResult(
        draw_id=str(data["draw_id"]),
        kind=str(data["kind"]),
        cards=cards,
        fortune_grade=str(data.get("fortune_grade", "")),
        interpretation_lines=tuple(data.get("interpretation_lines", [])),
        algorithm_revision=str(data.get("algorithm_revision", "")),
        deck_revision=str(data.get("deck_revision", "")),
        asset_ids=(),
        trace_id=str(data.get("trace_id", "")),
        disclaimer_id=str(data.get("disclaimer_id", "")),
    )


def projection_card_key(data: dict[str, Any]) -> str:
    return str(data["draw_id"])
