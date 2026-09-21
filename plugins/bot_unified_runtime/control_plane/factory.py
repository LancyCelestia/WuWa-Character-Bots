"""受控存储装配；HTTP 与 Bot 使用相同路径规则，不写 .env。"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from ..domains.ops.features.feature_catalog import build_product_descriptors
from .features import FeatureRegistry, FeatureState, FeatureStateStore
from .services import FeatureControlService


def _path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    from scripts.runtime_paths import runtime_path
    return Path(runtime_path(value))


class LazySQLiteFeatureStore:
    """装配不触碰数据库；损坏状态只阻断业务，保留控制恢复入口。"""
    supports_graph_revision = True

    def __init__(self, path: Path, legacy: Path | None) -> None:
        self.registry = FeatureRegistry(build_product_descriptors())
        self.path, self.legacy = path, legacy
        self._instance: Any = None
        self._lock = threading.Lock()

    def _get(self):
        with self._lock:
            if self._instance is None:
                from .sqlite_features import SQLiteFeatureStateStore
                store = SQLiteFeatureStateStore(self.path, descriptors=self.registry.descriptors)
                if self.legacy is not None and self.legacy.is_file():
                    store.import_legacy(self.legacy)
                self._instance = store
            return self._instance

    def get(self, feature_id: str) -> FeatureState:
        return self._get().get(feature_id)

    def list_states(self) -> tuple[FeatureState, ...]:
        return self._get().list_states()

    def audit(self, feature_id: str | None = None) -> tuple[dict[str, Any], ...]:
        return self._get().audit(feature_id)

    def preview(self, feature_id: str, enabled: bool | None, expected_version: int, **kwargs: Any) -> dict[str, Any]:
        return self._get().preview(feature_id, enabled, expected_version, **kwargs)

    def set_enabled(self, feature_id: str, enabled: bool, **kwargs: Any) -> dict[str, Any]:
        return self._get().set_enabled(feature_id, enabled, **kwargs)

    def reset(self, feature_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._get().reset(feature_id, **kwargs)


def build_feature_service(config: object | None = None) -> FeatureControlService:
    db = (os.environ.get("BOT_CONTROL_PLANE_FEATURES_DB") or "data/control_plane_features.sqlite3") if config is None else getattr(config, "bot_control_plane_features_db", "")
    if db:
        legacy_value = "data/control_plane_features.json" if config is None else getattr(config, "bot_control_plane_features_file", "")
        return FeatureControlService(LazySQLiteFeatureStore(_path(str(db)), _path(str(legacy_value)) if legacy_value else None))
    # 兼容旧测试/工具的显式JSON配置。正式Config配置了SQLite路径。
    legacy = getattr(config, "bot_control_plane_features_file", "") or "data/control_plane_features.json"
    return FeatureControlService(FeatureStateStore(_path(str(legacy)), descriptors=build_product_descriptors()))

def build_workspace_service(config: object | None = None):
    """只装配独立工作区；首次预览才读取人格/建立模型客户端，绝不自动调用模型。"""
    from .workspaces import WorkspaceService
    value = getattr(config, "bot_control_plane_workspaces_db", "")
    if not value:
        return None

    async def sandbox_generate(scope: dict[str, Any]) -> dict[str, Any]:
        from ..character.documents import load_character_document
        from ..llm.model_router import _resolve_api_key
        from ..llm.providers import OpenAICompatibleLLMProvider, StaticLLMProvider
        from .sandbox import SandboxConversationAdapter, SandboxModel
        from .services import ControlServiceError
        persona_files = tuple(Path(path).expanduser() for path in getattr(config, "bot_persona_files", ()))
        def load_persona() -> str:
            if not persona_files or any(path.stat().st_size > 256000 for path in persona_files):
                raise ControlServiceError("persona_unavailable", "工作区人格源未配置或超过大小限制。", 503)
            return "\n\n".join(load_character_document(path) for path in persona_files)
        protocol = str(getattr(config, "bot_chat_provider", "static"))
        model_id = str(getattr(config, "bot_chat_model", "static"))
        if protocol == "static":
            provider: Any = StaticLLMProvider(model=model_id)
        elif protocol in {"openai", "openai_compatible"}:
            provider = OpenAICompatibleLLMProvider(
                api_key=_resolve_api_key(str(getattr(config, "bot_chat_api_key", "")), config),
                model=model_id, base_url=str(getattr(config, "bot_chat_base_url", "")),
                timeout_seconds=min(float(getattr(config, "bot_chat_timeout_seconds", 20)), 60))
        else:
            raise ControlServiceError("workspace_provider_unsupported", "当前模型协议尚无隔离适配器。", 503)
        # default_provider/default_channel 是显式本地注册ID，不根据模型名猜供应商。
        adapter = SandboxConversationAdapter(
            personas={str(getattr(config, "bot_persona_profile_id", "shorekeeper")): load_persona},
            models=(SandboxModel("default_provider", "default_channel", model_id, provider),))
        return await adapter(scope)

    return WorkspaceService(_path(str(value)), sandbox_generator=sandbox_generate,
        default_persona_profile_id=str(getattr(config, "bot_persona_profile_id", "shorekeeper")))
