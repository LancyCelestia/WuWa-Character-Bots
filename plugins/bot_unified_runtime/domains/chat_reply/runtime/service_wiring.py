"""V2.1 服务装配组接线（B2①，WIRE-SVC 席，2026-09-18）。

合同行：V21-WORLD-001 / V21-KB-001 / V21-DB-001 / V21-TEACH-001
（docs/design/backend-v2-acceptance-matrix.md L39/L40/L42/L43）。
四个服务此前均已 ``implemented``（tests/test_persona_service_v21.py /
test_v21_knowledge_service.py / test_v21_database_broker.py /
test_v21_teaching_service.py 全离线绿）但**无生产调用点**（not_wired）；
本模块补装配与注册，不重写任何实现。

接线语义：
- **主门 ``bot_v21_service_wiring_enabled`` 缺省 False** → 全组缺省零装配
  零副作用，不改变现网任何行为（根 ``__init__.py`` 装配点同门）。
- 分门＝主门 ∧ 各服务门：worldbook/knowledge 用新增键（缺省 False）；
  teaching/database_broker 复用 S8 批既有键（``bot_teaching_enabled`` /
  ``bot_database_broker_enabled``，缺省 True——主门关时其 True 不生效）。
- 注册表：进程内 ``_SERVICES``（module 级），``get_v21_service(id)`` 是
  后续消费方（能力/控制面）的唯一取用口；本模块只装配+注册，不制造消费点。
- 装配 fail-open：单服务构建异常记 warning 并跳过该服务，绝不崩启动装配
  （与既有 ``_register_today_history_scheduler`` 等门控装配同风格）。

**L41（V21-MEM-001）刻意缺席**：记忆库走独立新库还是「同源同库」待用户
裁决（HANDOFF-V21R4-B-20260918.md §3.4/§七.2），裁决前不接线；本模块对
memory 相关模块零 import 零引用。

装配后调用链（重启生效后）：
  ``bot.py`` → 插件加载 → ``_register_nonebot_handlers``（根 ``__init__.py``，
  主门门控）→ ``register_v21_services(config)`` → ``build_v21_services``
  → 既有 ``build_worldbook_service`` / ``build_knowledge_service`` /
  ``build_database_broker`` / ``TeachingService`` → ``_SERVICES`` 注册表
  → 消费方经 ``get_v21_service("worldbook"|"knowledge"|"database_broker"|
  "teaching")`` 取用。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

__all__ = [
    "V21_SERVICE_WIRING_IDS",
    "build_v21_services",
    "get_v21_service",
    "register_v21_services",
    "reset_v21_services",
    "v21_service_gates",
    "v21_service_ids",
]

logger = logging.getLogger(__name__)

# 四个可装配服务 id（L41 memory 不在列——裁决前不接，见模块 docstring）。
V21_SERVICE_WIRING_IDS: tuple[str, ...] = (
    "worldbook",
    "knowledge",
    "database_broker",
    "teaching",
)

# 进程内服务注册表：仅 register_v21_services 写入（先清后填，幂等）。
_SERVICES: dict[str, Any] = {}


def v21_service_gates(config: object) -> dict[str, bool]:
    """生效门＝主门 ∧ 分门。主门缺省关 ⇒ 全组缺省零装配。"""
    master = bool(getattr(config, "bot_v21_service_wiring_enabled", False))
    return {
        "worldbook": master
        and bool(getattr(config, "bot_worldbook_enabled", False)),
        "knowledge": master
        and bool(getattr(config, "bot_knowledge_service_enabled", False)),
        # 既有 S8 分门键（缺省 True）：主门关时被 ∧ 短路，不改变现网行为。
        "database_broker": master
        and bool(getattr(config, "bot_database_broker_enabled", True)),
        "teaching": master
        and bool(getattr(config, "bot_teaching_enabled", True)),
    }


def build_v21_services(
    config: object,
    *,
    worldbook_db_path: str | Path | None = None,
    knowledge_stores: list[tuple[str, Any]] | None = None,
    broker_database_paths: dict[str, str | Path] | None = None,
    teaching_db_path: str | Path | None = None,
) -> dict[str, Any]:
    """按门装配各服务；单服务失败记 warning 跳过（fail-open），不崩装配。

    全部复用既有 builder（不重写实现）；显式路径/store 参数仅供测试注入
    （tmp_path），缺省走各 builder 既有 config 口径（runtime 重映射）。
    """
    gates = v21_service_gates(config)
    services: dict[str, Any] = {}

    def _assemble(service_id: str, builder: Any) -> None:
        if not gates.get(service_id):
            return
        try:
            services[service_id] = builder()
        except Exception as exc:  # noqa: BLE001 - 单服务失败不崩启动装配。
            logger.warning(
                "v21 service wiring: %s assembly failed: %s",
                service_id,
                type(exc).__name__,
            )

    if gates.get("worldbook"):
        from plugins.bot_unified_runtime.domains.chat_reply.character.worldbook_service import (
            build_worldbook_service,
        )

        _assemble(
            "worldbook", lambda: build_worldbook_service(worldbook_db_path)
        )
    if gates.get("knowledge"):
        from plugins.bot_unified_runtime.domains.chat_reply.character.knowledge_service import (
            build_knowledge_service,
        )

        _assemble(
            "knowledge",
            lambda: build_knowledge_service(config, stores=knowledge_stores),
        )
    if gates.get("database_broker"):
        from plugins.bot_unified_runtime.domains.chat_reply.runtime.database_broker import (
            build_database_broker,
        )

        _assemble(
            "database_broker",
            lambda: build_database_broker(
                config, database_paths=broker_database_paths
            ),
        )
    if gates.get("teaching"):

        def _build_teaching() -> Any:
            from plugins.bot_unified_runtime.domains.chat_reply.character.teaching_service import (
                TeachingService,
            )
            from scripts.runtime_paths import runtime_path

            path = (
                teaching_db_path
                if teaching_db_path is not None
                else runtime_path(
                    str(
                        getattr(
                            config,
                            "bot_teaching_db_path",
                            "data/teaching_knowledge.sqlite3",
                        )
                        or "data/teaching_knowledge.sqlite3"
                    )
                )
            )
            # L41 未裁决：memory_service 刻意不传（None），零 memory 依赖。
            return TeachingService(path)

        _assemble("teaching", _build_teaching)
    return services


def register_v21_services(config: object, **kwargs: Any) -> dict[str, Any]:
    """装配并写入进程内注册表（先清后填，幂等）；返回已注册 id→实例。"""
    built = build_v21_services(config, **kwargs)
    _SERVICES.clear()
    _SERVICES.update(built)
    return dict(_SERVICES)


def get_v21_service(service_id: str) -> Any:
    """消费方唯一取用口；未装配/未知 id 一律返回 None（绝不懒构建）。"""
    return _SERVICES.get(service_id)


def v21_service_ids() -> tuple[str, ...]:
    return tuple(sorted(_SERVICES))


def reset_v21_services() -> None:
    """清空注册表（测试隔离用；生产进程不调用）。"""
    _SERVICES.clear()
