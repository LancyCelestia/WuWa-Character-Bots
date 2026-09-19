"""V2.1 WIRE 席：人格版本库 → chat 链注入装配胶水（V21-PERSONA-001 wiring）。

把 V1 席 persona_service（draft→publish→activate→rollback、CAS、不可变触发器、
损坏隔离、唯一注入出口 build_core_injection）接进 chat 链人格注入。设计全文=
docs/design/v21r2-wire-log.md §2。

红线：
1. **personas/ 目录零接触**：灌入内容取自 provider 已加载的 persona_text
   （persona_files 现行内容的生产镜像，经 service 灌库=装配许可操作），
   本模块不读写任何人格文件。
2. **fail-open 绝不阻塞消息链**：灌入失败/版本库空/存储不可用/全损隔离
   一律 warn 一行并回退旧注入路径（文件文本）；消息链零阻塞。
3. **损坏隔离不二次处理**：服务层 load_active 哈希不符时已 quarantine 留证
   +告警+自动回退最近完好版本；chat 侧照常服务回退后内容，不再叠加判断。
4. **托管库不抢指针**：store 已有 active 指针（超管手动生命周期在场）时
   baseline 灌入跳过，注入=active 版本内容。
5. 灌入幂等：已有同 sha 基线则跳过；首用中途崩溃（已发布未激活）续跑时
   只补激活，不重复产生版本。

配置：``bot_persona_versioned_injection``（默认 False=旧路径逐字节不变，
True 才切版本库注入；config.py/catalog A26/.env.example 三处同生）。
存储：``data/persona_versions.sqlite3``（无独立配置键，经 runtime_path
重映射——persona_service 既有口径）。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.character.persona_service import (
    PersonaService,
    sha256_text,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import ROLE_SUPER_ADMIN

logger = logging.getLogger(__name__)

__all__ = [
    "BASELINE_ACTOR",
    "ensure_persona_baseline",
    "get_shared_persona_service",
    "load_versioned_persona_core",
    "reset_shared_persona_service",
]

BASELINE_ACTOR = "system:baseline-ingest"
_BASELINE_ROLES = [ROLE_SUPER_ADMIN]

_PERSONA_SERVICES: dict[str, PersonaService] = {}
_PERSONA_SERVICES_LOCK = threading.Lock()
_PERSONA_SERVICE_WARNED = False


def get_shared_persona_service() -> PersonaService | None:
    """进程级共享 PersonaService（按 resolved db_path 缓存，懒构建）。

    构建失败（路径解析/SQLite 不可用）warn 一行并返回 None——调用方 fail-open
    回退文件注入路径。
    """
    global _PERSONA_SERVICE_WARNED
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.character.persona_service import (
            build_persona_service,
        )

        service = build_persona_service()
    except Exception as exc:  # noqa: BLE001 - 存储不可用时降级，不阻断对话链。
        if not _PERSONA_SERVICE_WARNED:
            _PERSONA_SERVICE_WARNED = True
            logger.warning(
                "persona version store unavailable (%s: %s) — "
                "版本库注入降级为文件直读路径",
                type(exc).__name__,
                exc,
            )
        return None
    key = str(service.store.db_path)
    with _PERSONA_SERVICES_LOCK:
        cached = _PERSONA_SERVICES.get(key)
        if cached is not None:
            return cached
        _PERSONA_SERVICES[key] = service
        return service


def reset_shared_persona_service() -> None:
    """清空进程级共享缓存（仅测试用）。"""
    with _PERSONA_SERVICES_LOCK:
        _PERSONA_SERVICES.clear()


def ensure_persona_baseline(
    service: PersonaService,
    resource_id: str,
    content: str,
    *,
    actor: str = BASELINE_ACTOR,
    roles: list[str] | None = None,
) -> str:
    """把现行人格内容幂等灌入版本库为 baseline（纯生命周期语义，可抛异常）。

    返回状态机：seeded / activated_existing / exists / skipped_managed /
    skipped_empty。幂等保证：同 sha 基线已存在则跳过；托管 active 指针在场
    则不抢；首用崩溃续跑只补激活不重复出版本。
    """
    roles = list(roles) if roles is not None else list(_BASELINE_ROLES)
    if not content.strip():
        return "skipped_empty"
    digest = sha256_text(content)
    # 同 sha 判定双保险：登记 sha 相等且实际内容复核相等（防登记行本身损坏）。
    matching = [
        int(row["version"])
        for row in service.store.versions_desc(resource_id)
        if str(row["content_sha256"]) == digest
        and sha256_text(str(row["content"])) == digest
    ]
    state = service.store.get_state(resource_id)
    if matching:
        if state is not None:
            return "exists"
        service.activate(resource_id, matching[0], actor=actor, roles=roles)
        return "activated_existing"
    if state is not None:
        # 超管手动生命周期在场（active 指针已拨、无同 sha 版本）：
        # 版本库内容由服务生命周期管理，baseline 不抢指针。
        return "skipped_managed"
    latest = service.store.latest_version(resource_id)
    service.draft(
        resource_id,
        content,
        actor=actor,
        roles=roles,
        expected_version=latest,
    )
    published = service.publish(
        resource_id, actor=actor, roles=roles, expected_version=latest
    )
    service.activate(
        resource_id, int(published["version"]), actor=actor, roles=roles
    )
    return "seeded"


def load_versioned_persona_core(
    service: PersonaService,
    resource_id: str,
    fallback_text: str,
) -> tuple[str, dict[str, Any] | None]:
    """灌入（幂等）→ build_core_injection 取核；任何失败 fail-open 文件文本。

    返回 (persona_core_text, provenance)；provenance=None 表示回退旧路径。
    provenance 带 version/persona_revision/content_sha256 溯源字段。
    """
    try:
        status = ensure_persona_baseline(service, resource_id, fallback_text)
        if status == "skipped_empty":
            logger.warning(
                "persona versioned injection: resource=%s 现行人格内容为空，"
                "跳过灌入并回退文件路径",
                resource_id,
            )
            return fallback_text, None
        if status == "skipped_managed":
            logger.debug(
                "persona versioned injection: resource=%s 托管 active 指针在场，"
                "baseline 跳过",
                resource_id,
            )
        injection = service.build_core_injection(resource_id)
    except Exception as exc:  # noqa: BLE001 - 版本库任何故障（含存储不可用、
        # NotFound、CAS 冲突、全损隔离）都回退文件路径，绝不阻塞消息链。
        logger.warning(
            "persona versioned injection failed (%s: %s) — resource=%s "
            "回退文件直读路径",
            type(exc).__name__,
            exc,
            resource_id,
        )
        return fallback_text, None
    return str(injection["content"]), {
        "resource_id": str(injection["resource_id"]),
        "version": int(injection["version"]),
        "persona_revision": int(injection["persona_revision"]),
        "content_sha256": str(injection["content_sha256"]),
        "degraded": bool(injection["degraded"]),
        "baseline_status": status,
    }
