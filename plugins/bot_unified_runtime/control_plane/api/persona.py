"""人格切换 REST 段：当前生效人格的读取与运行时切换。

为什么单开一段而不是走 `/config/{key}`：
`BOT_PERSONA_PROFILE_ID` 是**装配期**主人格档，不登记在 SETTABLE_KEYS /
RESTART_REQUIRED_KEYS 任何一张表里；人格切换的真实落点是 runtime settings 的
`persona_override`（`/bot runtime persona switch` 同一落点），下一轮现读即生效。
把它塞进配置键会得到「写成功但行为不变」的死开关（台账 C-09），所以这里走
运行时覆盖，并明确不带重启语义。

写面只要求 super_admin（与 config 写同门槛）。不做二次同意卡：切换人格不写
.env、不动安全档，回退只需再切一次；这与既有 `bot runtime persona switch`
的管理命令同一风险档。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..api import ControlPlaneError
from .protocol import envelope


class PersonaSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(default="", max_length=128)
    expected_current: str = Field(default="", max_length=128)


def build_persona_router(
    *,
    settings_store: Any | None,
    config: object | None,
    read_dependency: Any,
    write_dependency: Any,
    prefix: str = "",
) -> APIRouter:
    r = APIRouter(prefix=prefix)

    def _store() -> Any:
        if settings_store is None:
            raise ControlPlaneError(
                503, "persona_unavailable", "运行时设置存储尚未装配，人格切换暂不可用。"
            )
        return settings_store

    def _state() -> dict[str, Any]:
        from ...domains.chat_reply.character.persona_profile import (  # type: ignore[import-not-found]
            get_shared_registry,
            main_persona_id,
        )

        store = _store()
        try:
            override = str(store.get_persona_override() or "").strip()
        except Exception:  # noqa: BLE001 - 读不到切换态按「未切换」申报，不编造
            override = ""
        registry = get_shared_registry()
        items = [
            {
                "profile_id": record.persona_id,
                "display_name": record.display_name or record.persona_id,
                "is_main": bool(record.is_main),
            }
            for record in registry.all().values()
        ]
        items.sort(key=lambda item: (not item["is_main"], item["profile_id"]))
        effective = override or main_persona_id(registry) or "default"
        return {
            "active_override": override,
            "effective": effective,
            "main": main_persona_id(registry),
            "items": items,
            "apply": "next_message",
            "restart_required": False,
        }

    @r.get("/persona", dependencies=[Depends(read_dependency)])
    def get_persona() -> dict[str, Any]:
        return envelope(_state())

    @r.post("/persona/active", dependencies=[Depends(write_dependency)])
    def set_persona(payload: PersonaSwitchRequest) -> dict[str, Any]:
        from ...domains.chat_reply.character.persona_profile import (  # type: ignore[import-not-found]
            get_shared_registry,
        )

        store = _store()
        wanted = payload.profile_id.strip()
        current = str(store.get_persona_override() or "").strip()
        if payload.expected_current.strip() != current:
            raise ControlPlaneError(
                409,
                "persona_version_conflict",
                "人格切换态已变化，请刷新后重试。",
            )
        if wanted and get_shared_registry().get(wanted) is None:
            raise ControlPlaneError(
                404,
                "persona_not_found",
                "人格册里没有这一格；请先登记 personas/registry/<id>.json。",
            )
        try:
            store.set_persona_override(wanted)
        except (OSError, ValueError) as exc:
            raise ControlPlaneError(
                503, "persona_store_unavailable", "人格切换没写下去，存储暂不可用。"
            ) from exc
        return envelope(_state())

    return r
