"""V2.1 WIRE 席测试——人格版本库 → chat 链注入装配接线（V21-PERSONA-001）。

覆盖（docs/design/v21r2-wire-log.md §2.6 测试计划，全离线 tmp_path 隔离、
零网络、零 personas/ 触碰、零 ChatBot_Runtime 触碰——版本库一律直注
PersonaService(VersionedResourceStore(tmp_path))，共享单例用 monkeypatch 拦截）：
- 默认 False：raw_text 与文件文本逐字节一致 + 零版本库触碰（回归锁）；
- True：baseline 幂等灌入 seeded + 注入内容与溯源（version/sha256）正确；
- 灌入幂等：重复 build_context / ensure 不重复产生版本；
- fail-open：存储不可用/共享单例构建失败 → 回退文件文本 + warn 一行；
- 损坏隔离：旁路篡改 active 版本 → 服务回退最近完好版本（degraded），
  全损 → 回退文件文本；quarantine 留证；
- 托管库不抢指针：active 版本内容优先于文件文本（skipped_managed）；
- 空人格文本：不入库 fail-open（旧兜底分支不变）；
- 装配工厂：build_character_context_provider 消费 bot_persona_versioned_injection
  （getattr 缺省 False，config stub 缺键不炸）。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    persona_injection as persona_injection_mod,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    providers as providers_mod,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_injection import (
    BASELINE_ACTOR,
    ensure_persona_baseline,
    get_shared_persona_service,
    load_versioned_persona_core,
    reset_shared_persona_service,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_service import (
    PersonaService,
    VersionedResourceStore,
    sha256_text,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    FileCharacterContextProvider,
    build_character_context_provider,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import ROLE_SUPER_ADMIN

PERSONA_TEXT_V1 = "守岸人核心人格 v1：温和、克制、不越界。"
PERSONA_TEXT_V2 = "守岸人核心人格 v2：温和、克制、不越界（托管修订版）。"
RESOURCE_ID = "shorekeeper"
SUPER = [ROLE_SUPER_ADMIN]

_LOG_TARGETS = ("persona versioned injection", "persona version store")


def _make_service(tmp_path: Path, name: str = "persona_versions.sqlite3") -> PersonaService:
    return PersonaService(VersionedResourceStore(tmp_path / name, prefix="persona"))


def _persona_file(tmp_path: Path, text: str = PERSONA_TEXT_V1) -> Path:
    path = tmp_path / "守岸人_核心人格.md"
    path.write_text(text, encoding="utf-8")
    return path


def _provider(
    persona_file: Path,
    *,
    versioned: bool = False,
    service: PersonaService | None = None,
) -> FileCharacterContextProvider:
    return FileCharacterContextProvider(
        persona_profile_id=RESOURCE_ID,
        persona_display_name="守岸人",
        persona_version="1",
        persona_files=[persona_file],
        knowledge_files=[],
        persona_versioned_injection=versioned,
        persona_version_service=service,
    )


def _build(provider: FileCharacterContextProvider):
    return provider.build_context(
        request_id="req-1",
        sender_id="user-1",
        session_id="private:user-1",
        query_text="你好",
    )


def _injection_log(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        rec.getMessage()
        for rec in caplog.records
        if any(t in rec.getMessage() for t in _LOG_TARGETS)
    ]


# ==================== ① 默认 False：旧路径回归锁 ====================


def test_factory_default_off_and_explicit_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """装配工厂消费 bot_persona_versioned_injection：缺键 getattr 缺省 False。"""
    captured: dict[str, object] = {}

    class _Capture:  # 拦截 provider 构造，捕获装配 kwargs
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(providers_mod, "FileCharacterContextProvider", _Capture)
    monkeypatch.setattr(providers_mod, "_shared_affinity_store", lambda config: None)
    monkeypatch.setattr(providers_mod, "_shared_addressing_preferences", lambda config: None)
    monkeypatch.setattr(providers_mod, "build_memory_provider", lambda config: None)
    monkeypatch.setattr(providers_mod, "build_reflection_memory_provider", lambda config: None)
    monkeypatch.setattr(providers_mod, "build_conversation_history_provider", lambda config: None)
    monkeypatch.setattr(providers_mod, "build_emotion_provider", lambda config: None)
    monkeypatch.setattr(providers_mod, "build_trend_provider", lambda config: None)
    monkeypatch.setattr(providers_mod, "build_temporal_provider", lambda config: None)
    monkeypatch.setattr(providers_mod, "build_glossary_provider", lambda config: None)
    monkeypatch.setattr(
        providers_mod,
        "build_relationship_provider",
        lambda config, interaction_counts=None: None,
    )
    monkeypatch.setattr(
        providers_mod,
        "build_shared_group_context_provider",
        lambda config, llm_provider=None: None,
    )
    monkeypatch.setattr(
        providers_mod,
        "build_keyword_knowledge_provider",
        lambda config: SimpleNamespace(available=False),
    )
    # config stub 缺键（旧测试兼容面）→ False。
    build_character_context_provider(SimpleNamespace(bot_affinity_enabled=False))
    assert captured["persona_versioned_injection"] is False
    # 显式 True → 透传 True。
    build_character_context_provider(
        SimpleNamespace(
            bot_affinity_enabled=False,
            bot_persona_versioned_injection=True,
        )
    )
    assert captured["persona_versioned_injection"] is True


def test_default_off_matches_legacy_path(tmp_path: Path) -> None:
    """默认 False：raw_text 与文件文本逐字节一致，零版本库触碰（回归锁）。"""
    persona_file = _persona_file(tmp_path)
    provider = _provider(persona_file, versioned=False)
    bundle = _build(provider)
    assert bundle.persona.raw_text == PERSONA_TEXT_V1
    # 全程未触碰任何版本库（tmp_path 下除人格文件外零新增 sqlite）。
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix in {".sqlite3", ".db"}]
    assert leftovers == []


# ==================== ② True：灌入 + 溯源注入 ====================


def test_versioned_enabled_seeds_and_injects_with_provenance(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service = _make_service(tmp_path)
    persona_file = _persona_file(tmp_path)
    caplog.set_level(logging.DEBUG)
    bundle = _build(_provider(persona_file, versioned=True, service=service))
    # 注入内容=灌入后的库内容（首用灌入=文件文本，两者全等）。
    assert bundle.persona.raw_text == PERSONA_TEXT_V1
    versions = service.list_versions(RESOURCE_ID)
    assert [v["version"] for v in versions] == [1]
    assert versions[0]["content_sha256"] == sha256_text(PERSONA_TEXT_V1)
    state = service.store.get_state(RESOURCE_ID)
    assert state is not None and int(state["active_version"]) == 1
    # 溯源 info 一行（version+sha256 可观测）。
    info = [
        msg
        for msg in _injection_log(caplog)
        if "version=1" in msg and sha256_text(PERSONA_TEXT_V1) in msg
    ]
    assert info, f"缺溯源 info 日志：{_injection_log(caplog)}"


# ==================== ③ 灌入幂等 ====================


def test_baseline_ingest_idempotent(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    persona_file = _persona_file(tmp_path)
    assert ensure_persona_baseline(service, RESOURCE_ID, PERSONA_TEXT_V1) == "seeded"
    assert ensure_persona_baseline(service, RESOURCE_ID, PERSONA_TEXT_V1) == "exists"
    # 经 provider 二次 build_context：版本数不增。
    _build(_provider(persona_file, versioned=True, service=service))
    _build(_provider(persona_file, versioned=True, service=service))
    assert [v["version"] for v in service.list_versions(RESOURCE_ID)] == [1]


def test_baseline_state_machine(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    # 空文本不入库。
    assert ensure_persona_baseline(service, RESOURCE_ID, "   \n") == "skipped_empty"
    assert service.list_versions(RESOURCE_ID) == []
    # 首用中途崩溃续跑（已发布未激活）→ 只补激活不重复出版本。
    service.draft(RESOURCE_ID, PERSONA_TEXT_V1, actor="rp", roles=SUPER)
    service.publish(RESOURCE_ID, actor="root", roles=SUPER, expected_version=0)
    assert (
        ensure_persona_baseline(service, RESOURCE_ID, PERSONA_TEXT_V1)
        == "activated_existing"
    )
    state = service.store.get_state(RESOURCE_ID)
    assert state is not None and int(state["active_version"]) == 1
    # 托管：active 指针在场且无同 sha 版本 → 不抢指针。
    assert (
        ensure_persona_baseline(service, RESOURCE_ID, "另一份现行文本")
        == "skipped_managed"
    )
    assert [v["version"] for v in service.list_versions(RESOURCE_ID)] == [1]


# ==================== ④ fail-open：存储不可用 ====================


class _BrokenStoreService:
    """任何方法都炸的服务桩（模拟存储损坏/权限异常）。"""

    store = property(lambda self: (_ for _ in ()).throw(RuntimeError("store boom")))

    def build_core_injection(self, resource_id: str):
        raise RuntimeError("store boom")


def test_fail_open_when_service_broken(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    persona_file = _persona_file(tmp_path)
    caplog.set_level(logging.WARNING)
    provider = _provider(
        persona_file, versioned=True, service=_BrokenStoreService()  # type: ignore[arg-type]
    )
    bundle = _build(provider)
    assert bundle.persona.raw_text == PERSONA_TEXT_V1
    warnings = [m for m in _injection_log(caplog) if "回退文件直读路径" in m]
    assert warnings, f"缺 fail-open 告警：{_injection_log(caplog)}"


def test_fail_open_when_shared_service_unbuildable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    persona_file = _persona_file(tmp_path)
    caplog.set_level(logging.WARNING)
    reset_shared_persona_service()
    # 告警闩锁复位（进程级 once-latch，测试需确定性）。
    monkeypatch.setattr(persona_injection_mod, "_PERSONA_SERVICE_WARNED", False)

    def _boom() -> PersonaService:
        raise RuntimeError("no sqlite available")

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.chat_reply.character.persona_service."
        "build_persona_service",
        _boom,
    )
    assert get_shared_persona_service() is None
    provider = _provider(persona_file, versioned=True, service=None)
    bundle = _build(provider)
    assert bundle.persona.raw_text == PERSONA_TEXT_V1
    assert any("版本库注入降级" in m for m in _injection_log(caplog))
    reset_shared_persona_service()


def test_shared_service_singleton_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_shared_persona_service()
    service = _make_service(tmp_path)
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.chat_reply.character.persona_service."
        "build_persona_service",
        lambda: service,
    )
    assert get_shared_persona_service() is service
    assert get_shared_persona_service() is service  # 按 db_path 缓存同一实例
    reset_shared_persona_service()
    assert get_shared_persona_service() is service  # 清缓存后重建（同 builder）
    reset_shared_persona_service()


def test_load_versioned_persona_core_provenance_shape(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    text, provenance = load_versioned_persona_core(
        service, RESOURCE_ID, PERSONA_TEXT_V1
    )
    assert text == PERSONA_TEXT_V1
    assert provenance is not None
    assert provenance["version"] == 1
    assert provenance["content_sha256"] == sha256_text(PERSONA_TEXT_V1)
    assert provenance["degraded"] is False
    assert provenance["baseline_status"] == "seeded"
    assert provenance["resource_id"] == RESOURCE_ID


# ==================== ⑤ 损坏隔离 ====================


def _corrupt_version(db_path: Path, version: int, content: str, resource: str) -> None:
    """模拟旁路直改（摘不可变触发器再改写——同 V1 席 test 手法）。"""
    raw = sqlite3.connect(str(db_path))
    raw.execute("DROP TRIGGER IF EXISTS persona_versions_no_update")
    raw.execute("DROP TRIGGER IF EXISTS persona_versions_no_delete")
    raw.execute(
        "UPDATE persona_versions SET content=? WHERE resource_id=? AND version=?",
        (content, resource, version),
    )
    raw.commit()
    raw.close()


def test_corrupt_active_falls_back_to_last_good(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db_path = tmp_path / "persona_versions.sqlite3"
    service = _make_service(tmp_path)
    persona_file = _persona_file(tmp_path)
    caplog.set_level(logging.DEBUG)
    _build(_provider(persona_file, versioned=True, service=service))  # seeded v1
    service.draft(RESOURCE_ID, PERSONA_TEXT_V2, actor="rp", roles=SUPER)
    service.publish(RESOURCE_ID, actor="root", roles=SUPER, expected_version=1)
    service.activate(RESOURCE_ID, 2, actor="root", roles=SUPER)
    _corrupt_version(db_path, 2, "被篡改的人格内容", RESOURCE_ID)
    # 新 provider 实例（绕过进程内文本缓存）走完整链路：v2 损坏 → 服务回退 v1。
    bundle = _build(_provider(persona_file, versioned=True, service=service))
    assert bundle.persona.raw_text == PERSONA_TEXT_V1
    assert len(service.quarantine_records(RESOURCE_ID)) == 1
    degraded = [m for m in _injection_log(caplog) if "degraded=True" in m]
    assert degraded, f"缺 degraded 溯源日志：{_injection_log(caplog)}"


def test_all_versions_corrupt_falls_open_to_file_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db_path = tmp_path / "persona_versions.sqlite3"
    service = _make_service(tmp_path)
    persona_file = _persona_file(tmp_path)
    caplog.set_level(logging.WARNING)
    _build(_provider(persona_file, versioned=True, service=service))  # seeded v1
    _corrupt_version(db_path, 1, "全损篡改", RESOURCE_ID)
    bundle = _build(_provider(persona_file, versioned=True, service=service))
    # 全损：服务拒注入（PersonaStoreUnavailable）→ chat 侧 fail-open 文件文本。
    assert bundle.persona.raw_text == PERSONA_TEXT_V1
    assert any("回退文件直读路径" in m for m in _injection_log(caplog))
    assert len(service.quarantine_records(RESOURCE_ID)) >= 1


# ==================== ⑥ 托管库不抢指针 / 空文本 ====================


def test_managed_active_version_wins_over_file_text(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    persona_file = _persona_file(tmp_path)  # 文件=v1
    assert ensure_persona_baseline(service, RESOURCE_ID, PERSONA_TEXT_V2) == "seeded"
    # 超管手动把 active 拨到 v2（内容≠文件文本）→ 注入以库为准。
    bundle = _build(_provider(persona_file, versioned=True, service=service))
    assert bundle.persona.raw_text == PERSONA_TEXT_V2
    assert [v["version"] for v in service.list_versions(RESOURCE_ID)] == [1]


def test_empty_persona_text_skips_seed_and_keeps_legacy_branch(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    persona_file = _persona_file(tmp_path, text="")
    bundle = _build(_provider(persona_file, versioned=True, service=service))
    # 空文本不入库；raw_text 保持空 → chat 链字段重组兜底分支照旧。
    assert bundle.persona.raw_text == ""
    assert service.list_versions(RESOURCE_ID) == []
    assert service.store.get_state(RESOURCE_ID) is None


# ==================== 灌入身份 ====================


def test_baseline_actor_identity(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    ensure_persona_baseline(service, RESOURCE_ID, PERSONA_TEXT_V1)
    version = service.list_versions(RESOURCE_ID)[0]
    assert version["published_by"] == BASELINE_ACTOR
