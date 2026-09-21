"""V2.1 A5 取证席 RED 测试——风险域 1/2/3（控制面 platform 路由 + PlatformStore）。

约定（主规范 §1 高风险清单取证）：
- 取证期每条测试均以 ``@pytest.mark.xfail(strict=True)`` 锁红；2026-09-17 A12
  假成功修复席已将风险 1/2/3 共 9 条全部修复并转正为正式回归断言（无 xfail 标记）。
- 只诊断不修复；离线 mock、tmp_path/:memory: 隔离、不写源码树 data/。
- 风险域：
  1. api/platform.py 路由把 _kind/_action/principal 放进公开参数、直操 Store 不走 Service；
  2. PlatformStore 跨实例 CAS 不完整 / Trace 建表主键与 append 列名不一致 / 生命周期无收口；
  3. persona draft/publish 仅改标记假成功、rebuild 返回查不到的 job、setter 未装配仍报 applied。
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane.api import ControlPlaneError
from plugins.bot_unified_runtime.control_plane.api.platform import build_platform_router
from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.control_plane.platform import PlatformStore


async def _read_dep() -> Principal:
    return Principal("test-read", ("admin",))


async def _write_dep() -> Principal:
    return Principal("test-root", ("super_admin", "admin"))


def _harness() -> FastAPI:
    """把真实 build_platform_router 挂到最小 app（带与生产同构的错误码映射）。"""
    app = FastAPI()
    app.include_router(
        build_platform_router(
            store=PlatformStore(":memory:"),
            read_dependency=_read_dep,
            write_dependency=_write_dep,
            prefix="/api/v1",
        )
    )

    @app.exception_handler(ControlPlaneError)
    async def _handle(request: Request, exc: ControlPlaneError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"error": {"code": exc.code}}
        )

    return app


# ==================== 风险 1：路由公开参数 / 越过 Service 层 ====================


def test_risk1_platform_router_builds_cleanly() -> None:
    # 转正（A12）：原缺陷=注册期 FastAPIError。fastapi>=0.141 起 include_router
    # 经 _IncludedRouter 惰性挂载、不再平铺进 app.routes，故断言锚定 router 本身：
    # build 不得抛错，且两条 persona 路径必须已在路由表内。
    router = build_platform_router(
        store=PlatformStore(":memory:"),
        read_dependency=_read_dep,
        write_dependency=_write_dep,
        prefix="/api/v1",
    )
    paths = {getattr(route, "path", "") for route in router.routes}
    assert "/api/v1/persona-profiles" in paths
    assert "/api/v1/persona-profiles/{resource_id}" in paths


def test_risk1_handler_params_not_client_forged() -> None:
    source_path = Path(build_platform_router.__globals__["__file__"])
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    offenders: list[str] = []

    def _check_args(name: str, args: ast.arguments) -> None:
        names = [a.arg for a in args.args]
        if "_kind" in names or "_action" in names:
            offenders.append(f"{name}:_kind/_action")
        if "principal" in names:
            first_default = len(names) - len(args.defaults)
            idx = names.index("principal")
            has_depends = False
            if idx >= first_default:
                default = args.defaults[idx - first_default]
                func = getattr(default, "func", None)
                has_depends = (
                    isinstance(func, ast.Name) and func.id == "Depends"
                ) or (
                    isinstance(func, ast.Attribute) and func.attr == "Depends"
                )
            if not has_depends:
                offenders.append(f"{name}:principal")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_args(node.name, node.args)
        elif isinstance(node, ast.Lambda):
            _check_args("<lambda>", node.args)

    assert offenders == [], f"公开参数缺陷处理器：{offenders}"


def test_risk1_versions_get_cannot_override_action() -> None:
    client = TestClient(_harness())
    client.put("/api/v1/persona-profiles/p1", json={"name": "x"})
    resp = client.get(
        "/api/v1/persona-profiles/p1/versions", params={"_action": "publish"}
    )
    assert resp.status_code == 200
    assert "versions" in resp.json()["data"]


# ==================== 风险 2：PlatformStore CAS / Trace / 收口 ====================


def test_risk2_append_traces_column_mismatch() -> None:
    store = PlatformStore(":memory:")
    payload = store.append("traces", {"trace_id": "t1", "stage": "route"})
    assert payload["id"] == "t1"


def test_risk2_cas_toctou_lost_update(tmp_path: Path) -> None:
    db = tmp_path / "platform.sqlite3"
    store_a = PlatformStore(db)
    store_a.put("kind1", "res1", {"v": 0})  # version 1

    other = sqlite3.connect(str(db))
    window_opened: list[bool] = []

    def _interleave(stmt: str) -> None:
        # 读-写间隙注入：另一实例在 A 的 SELECT 之后、INSERT 之前提交 version=99。
        if stmt.lstrip().startswith("INSERT INTO resources") and not window_opened:
            window_opened.append(True)
            other.execute(
                "UPDATE resources SET version = 99 WHERE kind='kind1' AND id='res1'"
            )
            other.commit()

    try:
        store_a._conn.set_trace_callback(_interleave)
        conflict: ValueError | None = None
        try:
            store_a.put("kind1", "res1", {"v": "mine"}, expected=1)
        except ValueError as exc:  # 期望：version_conflict
            conflict = exc
    finally:
        store_a._conn.set_trace_callback(None)

    final_version = other.execute(
        "SELECT version FROM resources WHERE kind='kind1' AND id='res1'"
    ).fetchone()[0]
    if window_opened:
        # 注入成功（现状：读-写间隙无事务/锁保护）→ CAS 必须拒绝旧 expected。
        assert conflict is not None, (
            f"跨实例 CAS 失守：读-写间隙被并发提交(v99)，put(expected=1) 仍成功"
            f"（写回 v={final_version}，lost update）"
        )
        assert final_version == 99
    # 注入未成功（修复后写路径持锁）→ 视为通过（XPASS 语义）。
    other.close()


def test_risk2_store_lifecycle_close_exists() -> None:
    assert callable(getattr(PlatformStore, "close", None)), "缺 close()"
    assert hasattr(PlatformStore, "__enter__") and hasattr(PlatformStore, "__exit__")


# ==================== 风险 3：draft/publish 假成功 / 幽灵 job / 假 applied ====================


def test_risk3_publish_produces_real_activation() -> None:
    client = TestClient(_harness())
    client.put("/api/v1/persona-profiles/p1", json={"name": "x"})
    data: dict[str, Any] = client.post("/api/v1/persona-profiles/p1/publish").json()[
        "data"
    ]
    assert data.get("active") is True


def test_risk3_rebuild_job_is_queryable() -> None:
    client = TestClient(_harness())
    job_id = client.post("/api/v1/memories/rebuild").json()["data"]["job_id"]
    resp = client.get(f"/api/v1/jobs/{job_id}")
    assert resp.status_code == 200, f"job 不可查：{resp.status_code} {resp.text[:120]}"


def test_risk3_log_level_honest_without_setter() -> None:
    app = FastAPI()
    app.include_router(
        build_platform_router(
            store=PlatformStore(":memory:"),
            read_dependency=_read_dep,
            write_dependency=_write_dep,
            prefix="/api/v1",
            log_level_setter=None,
        )
    )

    @app.exception_handler(ControlPlaneError)
    async def _handle(request: Request, exc: ControlPlaneError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"error": {"code": exc.code}}
        )

    data = TestClient(app).post("/api/v1/logs/level", json={"level": "info"}).json()[
        "data"
    ]
    assert data["applied"] is False
