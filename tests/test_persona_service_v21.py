"""V2.1 S7 V1 席测试——人格版本管理 + 世界书最小切片 + platform 哈希快照补口。

覆盖（任务书验收点，全离线 tmp_path/:memory: 隔离、零网络、零 personas/ 触碰）：
- persona 生命周期：draft→publish→activate→load/rollback 往返 + 哈希快照；
- CAS 冲突：draft/publish 的 expected_version 不一致必拒（并发发布只成功一个）；
- 损坏隔离：绕过服务直接改库内容 → 拒载+隔离留证+回退上一好版本，不抹证据；
- 权限门：普通 admin 不可 publish/activate/rollback 核心人格（仅超管）；
- 不可变性：直改已发布版本 → 触发器 ABORT；
- 注入防护：核心内容唯一出口 build_core_injection 只出已发布+复核内容；
- worldbook：结构校验/悬空引用/循环引用/Token 预算四类拒绝 + 正常发布；
- platform（V21-risk-3 补口回归）：publish 落 content_sha256 且 verify 一致、
  篡改可检出、setter 自报 False 时如实报 applied=False。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane.api import ControlPlaneError
from plugins.bot_unified_runtime.control_plane.api.platform import (
    build_platform_router,
)
from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.control_plane.platform import (
    PlatformService,
    PlatformStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_service import (
    PersonaNotFoundError,
    PersonaPermissionError,
    PersonaService,
    PersonaStoreUnavailable,
    PersonaValidationError,
    PersonaVersionConflict,
    VersionedResourceStore,
    sha256_text,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.worldbook_service import (
    WorldbookBudgetError,
    WorldbookCircularRefError,
    WorldbookDanglingRefError,
    WorldbookService,
    WorldbookStructureError,
    build_worldbook_service,
    estimate_tokens,
)

SUPER = ["super_admin"]
ADMIN = ["admin"]
USER = ["user"]

PERSONA_TEXT_V1 = "守岸人核心人格 v1：温和、克制、不越界。"
PERSONA_TEXT_V2 = "守岸人核心人格 v2：温和、克制、不越界（修订版）。"
TICK = iter(f"2026-09-17T00:00:{i:02d}" for i in range(10_000))


def tick() -> str:
    return next(TICK)


def make_service(tmp_path: Path, name: str = "persona_versions.sqlite3") -> PersonaService:
    return PersonaService(
        VersionedResourceStore(tmp_path / name, prefix="persona"), clock=tick
    )


# ==================== persona：生命周期 + 哈希快照 ====================


def test_persona_lifecycle_roundtrip(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    svc.draft("core", PERSONA_TEXT_V1, actor="rp", roles=ADMIN)
    published = svc.publish("core", actor="root", roles=SUPER, expected_version=0)
    assert published["version"] == 1
    assert published["content_sha256"] == sha256_text(PERSONA_TEXT_V1)
    activated = svc.activate("core", 1, actor="root", roles=SUPER)
    assert activated["persona_revision"] == 1
    load = svc.load_active("core")
    assert load.content == PERSONA_TEXT_V1
    assert load.version == 1
    assert load.degraded is False
    injection = svc.build_core_injection("core")
    assert injection["channel"] == "persona_core"
    assert injection["source"] == "version_store"
    assert injection["content"] == PERSONA_TEXT_V1
    assert injection["version"] == 1


def test_persona_rollback_creates_new_version(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    svc.draft("core", PERSONA_TEXT_V1, actor="rp", roles=ADMIN)
    svc.publish("core", actor="root", roles=SUPER, expected_version=0)
    svc.activate("core", 1, actor="root", roles=SUPER)
    svc.draft("core", PERSONA_TEXT_V2, actor="rp", roles=ADMIN, expected_version=1)
    svc.publish("core", actor="root", roles=SUPER, expected_version=1)
    svc.activate("core", 2, actor="root", roles=SUPER)
    # 回滚到 v1：创建新 v3（内容=v1），历史 v1/v2 不可变保留。
    rolled = svc.rollback("core", 1, actor="root", roles=SUPER)
    assert rolled["version"] == 3
    assert rolled["rolled_back_from"] == 1
    assert rolled["content_sha256"] == sha256_text(PERSONA_TEXT_V1)
    load = svc.load_active("core")
    assert load.content == PERSONA_TEXT_V1
    assert load.version == 3
    versions = svc.list_versions("core")
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert len(versions) == 3


def test_persona_publish_requires_draft(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    with pytest.raises(PersonaNotFoundError):
        svc.publish("ghost", actor="root", roles=SUPER, expected_version=0)


# ==================== persona：CAS 冲突 ====================


def test_persona_cas_conflict_on_stale_expected(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    svc.draft("core", PERSONA_TEXT_V1, actor="rp", roles=ADMIN)
    svc.publish("core", actor="root", roles=SUPER, expected_version=0)
    # draft 仍以 expected_version=0 提交 → CAS 拒绝（真实最新=1）。
    with pytest.raises(PersonaVersionConflict):
        svc.draft("core", PERSONA_TEXT_V2, actor="rp", roles=ADMIN, expected_version=0)
    # publish 侧同理：stale expected 必拒。
    svc.draft("core2", PERSONA_TEXT_V1, actor="rp", roles=ADMIN)
    with pytest.raises(PersonaVersionConflict):
        svc.publish("core2", actor="root", roles=SUPER, expected_version=5)


def test_persona_concurrent_publish_single_winner(tmp_path: Path) -> None:
    db = tmp_path / "race.sqlite3"
    svc = PersonaService(VersionedResourceStore(db, prefix="persona"), clock=tick)
    other = PersonaService(VersionedResourceStore(db, prefix="persona"), clock=tick)
    svc.draft("core", PERSONA_TEXT_V1, actor="rp", roles=ADMIN)
    # 两个实例对同一 draft/expected_version 并发发布 → 恰好一个成功落版本，
    # 输家显式报错（CAS 落空或草稿已被赢家消费），绝不产生双版本。
    first = svc.publish("core", actor="a", roles=SUPER, expected_version=0)
    with pytest.raises((PersonaVersionConflict, PersonaNotFoundError)):
        other.publish("core", actor="b", roles=SUPER, expected_version=0)
    assert first["version"] == 1
    versions = svc.list_versions("core")
    assert len(versions) == 1
    assert versions[0]["published_by"] == "a"


# ==================== persona：损坏隔离 ====================


def test_persona_corruption_quarantine_and_fallback(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    svc.draft("core", PERSONA_TEXT_V1, actor="rp", roles=ADMIN)
    svc.publish("core", actor="root", roles=SUPER, expected_version=0)
    svc.activate("core", 1, actor="root", roles=SUPER)
    svc.draft("core", PERSONA_TEXT_V2, actor="rp", roles=ADMIN, expected_version=1)
    svc.publish("core", actor="root", roles=SUPER, expected_version=1)
    svc.activate("core", 2, actor="root", roles=SUPER)

    # 模拟绕过 SQL 层的真损坏（磁盘/旁路直改）：先摘不可变触发器再改写内容
    # —— active v2 被篡改。
    db_path = tmp_path / "persona_versions.sqlite3"
    raw = sqlite3.connect(str(db_path))
    raw.execute("DROP TRIGGER IF EXISTS persona_versions_no_update")
    raw.execute("DROP TRIGGER IF EXISTS persona_versions_no_delete")
    raw.execute(
        "UPDATE persona_versions SET content=? WHERE resource_id=? AND version=2",
        ("被篡改的人格内容", "core"),
    )
    raw.commit()
    raw.close()

    load = svc.load_active("core")
    # 拒载损坏 v2 → 回退最近完好 v1；degraded 标记 + 证据不抹。
    assert load.version == 1
    assert load.content == PERSONA_TEXT_V1
    assert load.degraded is True
    assert len(load.quarantine) == 1
    assert load.quarantine[0]["version"] == 2
    assert load.quarantine[0]["actual_sha256"] == sha256_text("被篡改的人格内容")
    records = svc.quarantine_records("core")
    assert len(records) == 1
    assert records[0]["expected_sha256"] == sha256_text(PERSONA_TEXT_V2)
    # v2 行仍在库（不抹证据；触发器本就禁止删除）。
    assert svc.list_versions("core")[0]["version"] == 2


def test_persona_all_versions_corrupt_refuses_injection(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    svc.draft("core", PERSONA_TEXT_V1, actor="rp", roles=ADMIN)
    svc.publish("core", actor="root", roles=SUPER, expected_version=0)
    svc.activate("core", 1, actor="root", roles=SUPER)
    db_path = tmp_path / "persona_versions.sqlite3"
    raw = sqlite3.connect(str(db_path))
    raw.execute("DROP TRIGGER IF EXISTS persona_versions_no_update")
    raw.execute("DROP TRIGGER IF EXISTS persona_versions_no_delete")
    raw.execute("UPDATE persona_versions SET content='x' WHERE resource_id='core'")
    raw.commit()
    raw.close()
    with pytest.raises(PersonaStoreUnavailable):
        svc.load_active("core")
    with pytest.raises(PersonaStoreUnavailable):
        svc.build_core_injection("core")


def test_persona_activate_rejects_corrupted_version(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    svc.draft("core", PERSONA_TEXT_V1, actor="rp", roles=ADMIN)
    svc.publish("core", actor="root", roles=SUPER, expected_version=0)
    db_path = tmp_path / "persona_versions.sqlite3"
    raw = sqlite3.connect(str(db_path))
    raw.execute("DROP TRIGGER IF EXISTS persona_versions_no_update")
    raw.execute("DROP TRIGGER IF EXISTS persona_versions_no_delete")
    raw.execute("UPDATE persona_versions SET content='x' WHERE version=1")
    raw.commit()
    raw.close()
    with pytest.raises(PersonaValidationError):
        svc.activate("core", 1, actor="root", roles=SUPER)
    assert svc.quarantine_records("core"), "损坏证据必须落 quarantine 表"
    with pytest.raises(PersonaNotFoundError):
        svc.get_state("core")  # 未成功激活 → 无指针


# ==================== persona：权限门（仅超管发布核心人格） ====================


def test_persona_permission_gates(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    # admin 可起草，不可发布/激活/回滚核心人格（guide §9：仅超管发布人格）。
    svc.draft("core", PERSONA_TEXT_V1, actor="mod", roles=ADMIN)
    with pytest.raises(PersonaPermissionError):
        svc.publish("core", actor="mod", roles=ADMIN, expected_version=0)
    with pytest.raises(PersonaPermissionError):
        svc.publish("core", actor="who", roles=USER, expected_version=0)
    svc.publish("core", actor="root", roles=SUPER, expected_version=0)
    with pytest.raises(PersonaPermissionError):
        svc.activate("core", 1, actor="mod", roles=ADMIN)
    svc.activate("core", 1, actor="root", roles=SUPER)
    with pytest.raises(PersonaPermissionError):
        svc.rollback("core", 1, actor="mod", roles=ADMIN)
    # user 连起草都不行。
    with pytest.raises(PersonaPermissionError):
        svc.draft("core2", PERSONA_TEXT_V1, actor="who", roles=USER)


def test_persona_published_versions_immutable_by_trigger(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    svc.draft("core", PERSONA_TEXT_V1, actor="rp", roles=ADMIN)
    svc.publish("core", actor="root", roles=SUPER, expected_version=0)
    db_path = tmp_path / "persona_versions.sqlite3"
    raw = sqlite3.connect(str(db_path))
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(
            "UPDATE persona_versions SET content='篡改' WHERE resource_id='core'"
        )
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute("DELETE FROM persona_versions WHERE resource_id='core'")
    raw.close()


# ==================== worldbook：结构/悬空/循环/预算 ====================


def _wb_structure(
    resource_id: str,
    *,
    entries: list[dict[str, str]] | None = None,
    refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": f"世界书 {resource_id}",
        "entries": entries
        or [{"id": "e1", "title": "泰缇斯", "content": "漂浮在海上的巨大构造体。"}],
        "refs": refs or [],
    }


def test_worldbook_lifecycle_roundtrip(tmp_path: Path) -> None:
    svc = build_worldbook_service(tmp_path / "wb.sqlite3", clock=tick)
    svc.draft("world:main", _wb_structure("world:main"), actor="w", roles=ADMIN)
    published = svc.publish("world:main", actor="w", roles=ADMIN, expected_version=0)
    assert published["version"] == 1
    assert published["token_estimate"] > 0
    svc.activate("world:main", 1, actor="w", roles=ADMIN)
    injection = svc.build_injection("world:main")
    assert injection["channel"] == "worldbook_reference"
    assert injection["entries"][0]["untrusted"] is True
    assert "world:main@v1" in injection["entries"][0]["source"]
    # 草稿不污染：发布后草稿删除，draft 读取为空。
    assert svc._lifecycle.store.get_draft("world:main") is None


def test_worldbook_dangling_ref_rejected(tmp_path: Path) -> None:
    svc = build_worldbook_service(tmp_path / "wb.sqlite3", clock=tick)
    svc.draft(
        "world:a",
        _wb_structure("world:a", refs=["world:missing"]),
        actor="w",
        roles=ADMIN,
    )
    with pytest.raises(WorldbookDanglingRefError):
        svc.publish("world:a", actor="w", roles=ADMIN, expected_version=0)
    assert svc.list_versions("world:a") == []  # 校验失败不产生版本
    # external_ids 补上后可发布（跨库引用经注入解析）。
    svc2 = build_worldbook_service(
        tmp_path / "wb.sqlite3",
        external_ids=lambda: {"world:missing"},
        clock=tick,
    )
    assert svc2.publish("world:a", actor="w", roles=ADMIN, expected_version=0)


def test_worldbook_circular_ref_rejected(tmp_path: Path) -> None:
    svc = build_worldbook_service(tmp_path / "wb.sqlite3", clock=tick)
    # 先发布 a（无引用，v1）。
    svc.draft("wb:a", _wb_structure("wb:a"), actor="w", roles=ADMIN)
    svc.publish("wb:a", actor="w", roles=ADMIN, expected_version=0)
    svc.activate("wb:a", 1, actor="w", roles=ADMIN)
    # 自引用：a v2 引用自己（已发布 id，非悬空）→ 环检测拒绝。
    svc.draft(
        "wb:a",
        _wb_structure("wb:a", refs=["wb:a"]),
        actor="w",
        roles=ADMIN,
        expected_version=1,
    )
    with pytest.raises(WorldbookCircularRefError):
        svc.publish("wb:a", actor="w", roles=ADMIN, expected_version=1)
    assert svc.list_versions("wb:a")[0]["version"] == 1  # 失败未产生新版本
    # 双节点环：先合法发布 b（b→a，a 已发布，无环）。
    svc.draft(
        "wb:b",
        _wb_structure("wb:b", refs=["wb:a"]),
        actor="w",
        roles=ADMIN,
    )
    published_b = svc.publish("wb:b", actor="w", roles=ADMIN, expected_version=0)
    assert published_b["version"] == 1
    # a v2→b（b 已发布，非悬空）：a 经 b 可达自身（b→a）→ 环，拒绝。
    svc.draft(
        "wb:a",
        _wb_structure("wb:a", refs=["wb:b"]),
        actor="w",
        roles=ADMIN,
        expected_version=1,
    )
    with pytest.raises(WorldbookCircularRefError):
        svc.publish("wb:a", actor="w", roles=ADMIN, expected_version=1)
    # 只读校验不抛异常、给报告（合法结构 ok=True）。
    report = svc.validate(_wb_structure("wb:c", refs=["wb:a"]))
    assert report["ok"] is True
    assert report["issues"] == []


def test_worldbook_token_budget_rejected(tmp_path: Path) -> None:
    svc = build_worldbook_service(
        tmp_path / "wb.sqlite3", token_budget=16, clock=tick
    )
    fat = _wb_structure(
        "wb:fat",
        entries=[{"id": "e1", "title": "长文", "content": "字" * 100}],
    )
    svc.draft("wb:fat", fat, actor="w", roles=ADMIN)
    with pytest.raises(WorldbookBudgetError):
        svc.publish("wb:fat", actor="w", roles=ADMIN, expected_version=0)
    assert svc.list_versions("wb:fat") == []


def test_worldbook_shape_and_tokens() -> None:
    with pytest.raises(WorldbookStructureError):
        WorldbookService._check_shape({"entries": []})
    with pytest.raises(WorldbookStructureError):
        WorldbookService._check_shape({"entries": [{"id": "", "content": "x"}]})
    assert estimate_tokens("守岸人") == 3
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("守岸人abcd") == 4


# ==================== platform（V21-risk-3 补口回归） ====================


def test_platform_publish_lands_hash_snapshot() -> None:
    store = PlatformStore(":memory:")
    service = PlatformService(store)
    service.put_resource("persona_profiles", "p1", {"name": "守岸人"})
    current = service.get_resource("persona_profiles", "p1")
    assert current is not None
    result = service.apply_lifecycle(
        "persona_profiles", "p1", "publish", None, current
    )
    assert result["active"] is True
    assert result.get("content_sha256"), "publish 必须落哈希快照"
    verify = service.verify_resource("persona_profiles", "p1")
    assert verify["has_snapshot"] is True
    assert verify["intact"] is True


def test_platform_verify_detects_tamper(tmp_path: Path) -> None:
    db = tmp_path / "platform.sqlite3"
    store = PlatformStore(db)
    service = PlatformService(store)
    service.put_resource("worldbooks", "wb1", {"title": "x"})
    current = service.get_resource("worldbooks", "wb1")
    assert current is not None
    service.apply_lifecycle("worldbooks", "wb1", "publish", None, current)
    raw = sqlite3.connect(str(db))
    raw.execute("UPDATE resources SET data='{\"name\": \"旁路改写\"}'")
    raw.commit()
    raw.close()
    verify = service.verify_resource("worldbooks", "wb1")
    assert verify["has_snapshot"] is True
    assert verify["intact"] is False, "旁路篡改必须被哈希复核检出"


async def _read_dep() -> Principal:
    return Principal("test-read", ("admin",))


async def _write_dep() -> Principal:
    return Principal("test-root", ("super_admin", "admin"))


def _harness(log_level_setter: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_platform_router(
            store=PlatformStore(":memory:"),
            read_dependency=_read_dep,
            write_dependency=_write_dep,
            prefix="/api/v1",
            log_level_setter=log_level_setter,
        )
    )

    @app.exception_handler(ControlPlaneError)
    async def _handle(request: Request, exc: ControlPlaneError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"error": {"code": exc.code}}
        )

    return app


def test_platform_log_level_setter_false_reported_honestly() -> None:
    calls: list[str] = []

    def setter(level: str) -> bool:
        calls.append(level)
        return False  # setter 自报失败

    data = TestClient(_harness(setter)).post(
        "/api/v1/logs/level", json={"level": "debug"}
    ).json()["data"]
    assert calls == ["debug"]
    assert data["applied"] is False
    assert data["reason"] == "setter_reported_failure"


def test_platform_log_level_setter_success_still_applied() -> None:
    def setter(level: str) -> None:
        return None  # 既有契约：不返回值=调用成功

    data = TestClient(_harness(setter)).post(
        "/api/v1/logs/level", json={"level": "info"}
    ).json()["data"]
    assert data["applied"] is True
