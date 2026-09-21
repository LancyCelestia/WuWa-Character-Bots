"""WebUI 插件目录端点（/api/v1/plugins）服务层契约：离线、只读、诚实来源。

- groups[].builtins ← features store（能力树聚合视图：id/name/description/
  enabled/hot_reload=descriptor.hot_toggle），source=features_store；
- groups[].adapters ← pyproject.toml [tool.nonebot.adapters] 静态声明，
  source=static_config；
- groups[].event_matchers ← 无跨进程内省来源 → not_available+
  cross_process_introspection_unavailable，绝不猜；
- groups[].migrated_modules ← domains/ 目录清单（域名/模块数/入口文件
  存在性），source=filesystem。

每组条目统一含 name/description/source/hot_reload（bool 诚实值或 null）。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.control_plane.webui_plugins import (
    PluginsCatalogService,
    build_default_plugins_service,
)


class _FakeFeatureService:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def list_features(self, **kwargs):
        del kwargs
        return self._rows


def _feature_row(fid: str, label: str, *, enabled: bool, hot: bool = True) -> dict:
    return {
        "descriptor": {
            "id": fid,
            "parent_id": "bot",
            "kind": "plugin",
            "label": label,
            "aliases": (fid.split(".")[-1],),
            "capability_id": fid.replace("bot.plugin.", "bot.") + ".cap",
            "hot_toggle": hot,
        },
        "state": {"effective_enabled": enabled},
    }


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "domains" / "notes").mkdir(parents=True)
    (root / "domains" / "notes" / "__init__.py").write_text("", encoding="utf-8")
    (root / "domains" / "notes" / "capabilities.py").write_text("", encoding="utf-8")
    (root / "domains" / "meme").mkdir(parents=True)
    # meme 域无 __init__.py：入口文件存在性=如实 False。
    (root / "pyproject.toml").write_text(
        "[tool.nonebot.adapters]\n"
        "nonebot-adapter-onebot = [{ name = \"OneBot V11\","
        " module_name = \"nonebot.adapters.onebot.v11\" }]\n"
        "nonebot-adapter-telegram = [{ name = \"Telegram\","
        " module_name = \"nonebot.adapters.telegram\" }]\n",
        encoding="utf-8",
    )
    return root


def _service(project_root: Path, rows: list[dict] | None = None) -> PluginsCatalogService:
    return PluginsCatalogService(
        feature_service=_FakeFeatureService(
            rows
            if rows is not None
            else [
                _feature_row("bot.plugin.chat", "人格对话", enabled=True),
                _feature_row("bot.plugin.weather", "天气", enabled=False, hot=False),
            ]
        ),
        project_root=project_root,
    )


def _groups(result: dict) -> dict[str, dict]:
    assert result["status"] == "ok"
    assert result["source"] == "plugins_catalog"
    return {group["id"]: group for group in result["data"]["groups"]}


def test_groups_all_four_present_with_required_item_shape(
    project_root: Path,
) -> None:
    groups = _groups(_service(project_root).plugins_catalog())
    assert set(groups) == {"builtins", "adapters", "event_matchers", "migrated_modules"}
    for group in groups.values():
        for item in group["items"]:
            assert {"name", "description", "source", "hot_reload"} <= set(item)


def test_builtins_aggregates_features_store(project_root: Path) -> None:
    groups = _groups(_service(project_root).plugins_catalog())
    builtins = groups["builtins"]
    assert builtins["source"] == "features_store"
    by_name = {item["name"]: item for item in builtins["items"]}
    chat = by_name["人格对话"]
    assert chat["enabled"] is True
    assert chat["hot_reload"] is True
    assert chat["source"] == "features_store"
    weather = by_name["天气"]
    assert weather["enabled"] is False
    assert weather["hot_reload"] is False


# ---------------------------------------------------------------------------
# BACKEND3 增补：version / trigger_hints / config_actions（UIREF D3/D6/D5）
# ---------------------------------------------------------------------------


def test_all_items_carry_version_trigger_hints_config_actions(
    project_root: Path,
) -> None:
    groups = _groups(_service(project_root).plugins_catalog())
    for group in groups.values():
        for item in group["items"]:
            assert "version" in item and (item["version"] is None or isinstance(item["version"], str))
            assert "trigger_hints" in item and (
                item["trigger_hints"] is None or isinstance(item["trigger_hints"], list)
            )
            assert isinstance(item["config_actions"], list)
            for action in item["config_actions"]:
                assert set(action) == {"action_id", "name"}


def test_builtins_trigger_hints_from_descriptor_aliases(project_root: Path) -> None:
    custom = {
        "descriptor": {
            "id": "bot.plugin.weather",
            "kind": "plugin",
            "label": "天气",
            "aliases": ("weather", "天气插件"),
            "hot_toggle": True,
        },
        "state": {"effective_enabled": True},
    }
    bare = {
        "descriptor": {
            "id": "bot.plugin.bare",
            "kind": "plugin",
            "label": "无别名",
            "hot_toggle": True,
        },
        "state": {"effective_enabled": True},
    }
    groups = _groups(
        _service(project_root, rows=[custom, bare]).plugins_catalog()
    )
    by_name = {item["name"]: item for item in groups["builtins"]["items"]}
    # descriptor aliases 非空 → 数组带出（features 别名口径，非聊天触发词全量）。
    assert by_name["天气"]["trigger_hints"] == ["weather", "天气插件"]
    # 无 aliases 字段 → null（不造触发词）。
    assert by_name["无别名"]["trigger_hints"] is None
    # builtins 无版本来源 → version=null（诚实）。
    assert by_name["天气"]["version"] is None


def test_builtins_config_actions_match_feature_short_name(project_root: Path) -> None:
    def registry():
        return (
            ("memory.maintenance", "记忆维护"),
            ("chat.compact", "会话压缩"),
            ("runtime.reload", "运行时重载"),
        )

    service = PluginsCatalogService(
        feature_service=_FakeFeatureService(
            [_feature_row("bot.plugin.chat", "人格对话", enabled=True)]
        ),
        project_root=project_root,
        action_registry=registry,
    )
    groups = _groups(service.plugins_catalog())
    chat = groups["builtins"]["items"][0]
    assert chat["config_actions"] == [{"action_id": "chat.compact", "name": "会话压缩"}]


def test_migrated_modules_config_actions_by_domain_name(project_root: Path) -> None:
    def registry():
        return (
            ("notes.compact", "笔记压缩"),
            ("runtime.reload", "运行时重载"),
        )

    service = PluginsCatalogService(
        feature_service=_FakeFeatureService([]),
        project_root=project_root,
        action_registry=registry,
    )
    groups = _groups(service.plugins_catalog())
    by_name = {item["name"]: item for item in groups["migrated_modules"]["items"]}
    assert by_name["notes"]["config_actions"] == [
        {"action_id": "notes.compact", "name": "笔记压缩"}
    ]
    assert by_name["meme"]["config_actions"] == []


def test_config_actions_none_or_broken_registry_degrades_to_empty(
    project_root: Path,
) -> None:
    def broken():
        raise RuntimeError("registry offline")

    for registry in (None, broken):
        service = PluginsCatalogService(
            feature_service=_FakeFeatureService(
                [_feature_row("bot.plugin.chat", "人格对话", enabled=True)]
            ),
            project_root=project_root,
            action_registry=registry,
        )
        result = service.plugins_catalog()
        assert result["status"] == "ok"  # 注册表故障不拖垮整份目录。
        groups = {group["id"]: group for group in result["data"]["groups"]}
        assert groups["builtins"]["items"][0]["config_actions"] == []


def test_adapters_version_from_injected_resolver(project_root: Path) -> None:
    found = PluginsCatalogService(
        feature_service=_FakeFeatureService([]),
        project_root=project_root,
        version_resolver=lambda package: "9.9.9",
    )
    groups = _groups(found.plugins_catalog())
    assert {item["version"] for item in groups["adapters"]["items"]} == {"9.9.9"}
    assert all(item["trigger_hints"] is None for item in groups["adapters"]["items"])

    missing = PluginsCatalogService(
        feature_service=_FakeFeatureService([]),
        project_root=project_root,
        version_resolver=lambda package: None,
    )
    groups = _groups(missing.plugins_catalog())
    assert all(item["version"] is None for item in groups["adapters"]["items"])

    boom = PluginsCatalogService(
        feature_service=_FakeFeatureService([]),
        project_root=project_root,
        version_resolver=lambda package: (_ for _ in ()).throw(RuntimeError("meta")),
    )
    groups = _groups(boom.plugins_catalog())
    assert all(item["version"] is None for item in groups["adapters"]["items"])


def test_adapters_version_default_resolver_pyproject_exact_pin(tmp_path: Path) -> None:
    # 默认解析器：importlib 元数据（测试环境必无此包）→ pyproject == 精确钉。
    # >= 区间约束不是版本号：如实 null，不把约束冒充版本。
    (tmp_path / "pyproject.toml").write_text(
        '[project]\n'
        'name = "fixture"\n'
        'version = "0.1.0"\n'
        'dependencies = [\n'
        '  "backend3-exact-pkg==1.2.3",\n'
        '  "backend3-range-pkg>=2.0",\n'
        ']\n'
        '[tool.nonebot.adapters]\n'
        'backend3-exact-pkg = [{ name = "Exact", module_name = "exact.mod" }]\n'
        'backend3-range-pkg = [{ name = "Range", module_name = "range.mod" }]\n',
        encoding="utf-8",
    )
    service = PluginsCatalogService(
        feature_service=_FakeFeatureService([]), project_root=tmp_path
    )
    groups = _groups(service.plugins_catalog())
    by_name = {item["name"]: item for item in groups["adapters"]["items"]}
    assert by_name["Exact"]["version"] == "1.2.3"
    assert by_name["Range"]["version"] is None


def test_migrated_modules_version_from_init_dunder(tmp_path: Path) -> None:
    versioned = tmp_path / "domains" / "versioned"
    versioned.mkdir(parents=True)
    (versioned / "__init__.py").write_text(
        '"""域包。"""\n\n__version__ = "1.2.3"\n', encoding="utf-8"
    )
    unversioned = tmp_path / "domains" / "unversioned"
    unversioned.mkdir(parents=True)
    (unversioned / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    service = PluginsCatalogService(
        feature_service=_FakeFeatureService([]), project_root=tmp_path
    )
    groups = _groups(service.plugins_catalog())
    by_name = {item["name"]: item for item in groups["migrated_modules"]["items"]}
    assert by_name["versioned"]["version"] == "1.2.3"
    assert by_name["unversioned"]["version"] is None


def test_adapters_from_static_pyproject(project_root: Path) -> None:
    groups = _groups(_service(project_root).plugins_catalog())
    adapters = groups["adapters"]
    assert adapters["source"] == "static_config"
    names = {item["name"] for item in adapters["items"]}
    assert names == {"OneBot V11", "Telegram"}
    for item in adapters["items"]:
        assert item["hot_reload"] is False
        assert item["source"] == "static_config"


def test_event_matchers_not_available_never_guessed(project_root: Path) -> None:
    groups = _groups(_service(project_root).plugins_catalog())
    matchers = groups["event_matchers"]
    assert matchers["enabled"] is False
    assert matchers["reason"] == "cross_process_introspection_unavailable"
    assert matchers["items"] == []


def test_migrated_modules_from_filesystem(project_root: Path) -> None:
    groups = _groups(_service(project_root).plugins_catalog())
    migrated = groups["migrated_modules"]
    assert migrated["source"] == "filesystem"
    by_name = {item["name"]: item for item in migrated["items"]}
    assert by_name["notes"]["module_count"] == 2
    assert by_name["notes"]["entry_file_exists"] is True
    assert by_name["meme"]["module_count"] == 0
    assert by_name["meme"]["entry_file_exists"] is False
    names = [item["name"] for item in migrated["items"]]
    assert names == sorted(names)  # 确定性：域名升序


def test_missing_pyproject_is_honest(tmp_path: Path) -> None:
    service = PluginsCatalogService(
        feature_service=_FakeFeatureService([]), project_root=tmp_path
    )
    groups = _groups(service.plugins_catalog())
    assert groups["adapters"]["items"] == []
    assert groups["adapters"]["reason"] == "static_config_unavailable"
    dumped = json.dumps(groups, ensure_ascii=False)
    assert str(tmp_path) not in dumped


def test_no_domains_dir_is_empty_group(tmp_path: Path) -> None:
    service = PluginsCatalogService(
        feature_service=_FakeFeatureService([]), project_root=tmp_path
    )
    groups = _groups(service.plugins_catalog())
    assert groups["migrated_modules"]["items"] == []


def test_broken_feature_service_is_contained(project_root: Path) -> None:
    class Broken:
        def list_features(self, **kwargs):
            raise RuntimeError("boom")

    service = PluginsCatalogService(feature_service=Broken(), project_root=project_root)
    groups = _groups(service.plugins_catalog())
    assert groups["builtins"]["enabled"] is False
    assert groups["builtins"]["reason"] == "features_store_unavailable"


def test_build_default_service_from_config(tmp_path: Path, project_root: Path) -> None:
    config = SimpleNamespace(
        bot_control_plane_features_file=str(tmp_path / "features.json"),
    )
    service = build_default_plugins_service(config, project_root=project_root)
    assert service.plugins_catalog()["status"] == "ok"


# ---------------------------------------------------------------------------
# HTTP 投影：统一信封 / 认证（挂 _app 装配）
# ---------------------------------------------------------------------------


def test_plugins_http_envelope_and_auth(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from plugins.bot_unified_runtime.control_plane import create_control_plane_app
    from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
    from plugins.bot_unified_runtime.control_plane.auth import hash_token

    config = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("admin-token"),
        bot_control_plane_super_admin_token_sha256=hash_token("root-token"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
    )
    app = create_control_plane_app(
        config,
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp-audit.sqlite3")),
        channel_health_store=object(),
        webui_dist_dir=str(tmp_path / "dist"),
    )
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        assert client.get("/api/v1/plugins").status_code == 401
        response = client.get("/api/v1/plugins", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["error"] is None
        assert payload["data"]["status"] == "ok"
        group_ids = {group["id"] for group in payload["data"]["data"]["groups"]}
        assert group_ids == {
            "builtins",
            "adapters",
            "event_matchers",
            "migrated_modules",
        }
        # BACKEND3：装配态条目带齐 version/trigger_hints/config_actions 形状
        # （值域按真实环境断言形状不断言具体值）。
        for group in payload["data"]["data"]["groups"]:
            for item in group["items"]:
                assert item["version"] is None or isinstance(item["version"], str)
                assert item["trigger_hints"] is None or isinstance(
                    item["trigger_hints"], list
                )
                assert isinstance(item["config_actions"], list)
