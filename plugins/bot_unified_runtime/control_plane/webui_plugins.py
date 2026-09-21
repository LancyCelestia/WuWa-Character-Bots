"""WebUI 插件目录只读服务（GET /api/v1/plugins → groups[]）。

数据源与口径（全部只读，绝不写）：

- ``builtins`` ← features store（既有 features API 的聚合视图）：
  id/name(label)/description/enabled(effective_enabled)/hot_reload
  （= descriptor.hot_toggle，真实 bool——项目铁律「改代码须重启」下，
  hot_toggle=False 即热载关闭的诚实值）；source=features_store。
- ``adapters`` ← pyproject.toml ``[tool.nonebot.adapters]`` 静态声明；
  source=static_config；pyproject 缺失/无适配器段 → 组级 reason=
  static_config_unavailable（诚实，不猜运行时实况）。
- ``event_matchers`` ← 无跨进程内省来源（matcher 活在 bot 宿主进程内），
  组级 not_available + cross_process_introspection_unavailable，绝不猜。
- ``migrated_modules`` ← ``domains/`` 目录清单（v21r2 板块重组 20 域）：
  域名/模块数(py 文件)/入口文件存在性（__init__.py）；source=filesystem。

每组条目统一含 name/description/source/hot_reload（bool 诚实值或 null）。

BACKEND3 增补（UIREF D3/D5/D6 后端供给，全部尽力来源、取不到=null/空表）：
- ``version``：adapters=注入 resolver 或默认链（importlib 发行版元数据 →
  pyproject ``[project] dependencies`` 的 ``==`` 精确钉；``>=`` 区间约束不是
  版本号，绝不冒充）；migrated=域 ``__init__.py`` 内 ``__version__`` 字面量
  （读文件不 import）；builtins=无版本来源 → null。
- ``trigger_hints``：builtins=features descriptor ``aliases``（能力别名，
  非聊天触发词全量——触发词注册表活在 bot 宿主进程内，跨进程不可内省）；
  空则 null。其余组无别名来源 → null。
- ``config_actions``：/actions 注册表映射（不新建动作端点）。规则=动作 id
  首段命名空间与条目键相等（builtins=feature id 末段、adapters=包名、
  migrated=域名）；注册表缺装配/读取失败 → 空表（诚实降级，不拖垮目录）。
失败面沿用 webui_stats 先例：``{status, reason, data: None}``，无效参数
先于任何 IO 校验；单个来源故障不拖垮整份目录（组级诚实降级）。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import tomllib

__all__ = [
    "PluginsCatalogService",
    "build_default_plugins_service",
]

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 版本字面量白名单形（发行版元数据/pyproject 钉/域 __init__ 同一护栏形）。
_VERSION_SAFE_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_!-]{0,31}\Z")
_MODULE_VERSION_RE = re.compile(
    r"^[ \t]*__version__[ \t]*=[ \t]*[\"']([^\"'\n]{1,32})[\"']",
    re.MULTILINE,
)
_DEP_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
_INIT_READ_BYTES = 65_536


def _failure(status: str, reason: str) -> dict[str, Any]:
    return {"status": status, "reason": reason, "data": None}


def _normalize_dist_key(name: str) -> str:
    """PEP 503 发行版名归一（``-``/``_``/``.`` 等价 + casefold）。"""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _module_version(init_path: Path) -> str | None:
    """域 ``__init__.py`` 的 ``__version__`` 字面量（读文件，绝不 import）。"""
    try:
        text = init_path.read_text(encoding="utf-8", errors="ignore")[
            :_INIT_READ_BYTES
        ]
    except OSError:
        return None
    found = _MODULE_VERSION_RE.search(text)
    return found.group(1) if found else None


def _pinned_dependency_version(project_root: Path, package_key: str) -> str | None:
    """pyproject ``[project] dependencies`` 的 ``==`` 精确钉；区间约束=None。"""
    try:
        data = tomllib.loads(
            (project_root / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return None
    dependencies = data.get("project", {}).get("dependencies")
    if not isinstance(dependencies, list):
        return None
    want = _normalize_dist_key(package_key)
    for dependency in dependencies:
        if not isinstance(dependency, str):
            continue
        name_match = _DEP_NAME_RE.match(dependency.strip())
        if name_match is None or _normalize_dist_key(name_match.group(1)) != want:
            continue
        spec = dependency.strip()[name_match.end() :].strip()
        if spec.startswith("=="):
            candidate = spec[2:].strip().strip("\"'")
            if _VERSION_SAFE_RE.fullmatch(candidate):
                return candidate
        return None  # 命中包名但非精确钉：区间约束不冒充版本。
    return None


def _default_package_version(project_root: Path, package_key: str) -> str | None:
    """默认版本链：importlib 发行版元数据（真实安装版）→ pyproject 精确钉。"""
    try:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as dist_version

        raw = dist_version(package_key)
    except (PackageNotFoundError, ImportError, OSError, ValueError):
        raw = None
    if isinstance(raw, str) and _VERSION_SAFE_RE.fullmatch(raw):
        return raw
    return _pinned_dependency_version(project_root, package_key)


class PluginsCatalogService:
    """插件目录聚合（features 聚合视图 + 静态适配器 + 域清单）。

    ``action_registry``/``version_resolver`` 均为可选只读回调：
    - ``action_registry`` → ``tuple[(action_id, label), ...]``（/actions 注册表
      投影，零 DB），缺省 None=全部条目 config_actions 空表；
    - ``version_resolver`` → ``(package_key) -> str | None``，缺省用默认链
      （importlib 元数据 → pyproject ``==`` 精确钉）。
    """

    def __init__(
        self,
        *,
        feature_service: Any,
        project_root: str | Path,
        action_registry: Callable[[], tuple[tuple[str, str], ...]] | None = None,
        version_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._feature_service = feature_service
        self._project_root = Path(project_root)
        self._action_registry = action_registry
        self._version_resolver = version_resolver

    def plugins_catalog(self) -> dict[str, Any]:
        pairs = self._action_pairs()
        return {
            "status": "ok",
            "source": "plugins_catalog",
            "data": {
                "groups": [
                    self._builtins_group(pairs),
                    self._adapters_group(pairs),
                    self._event_matchers_group(),
                    self._migrated_modules_group(pairs),
                ]
            },
        }

    # -- BACKEND3 映射辅助 ---------------------------------------------------

    def _action_pairs(self) -> tuple[tuple[str, str], ...]:
        """注册表只读投影；缺装配/读取失败 → 空表（诚实降级，不炸目录）。"""
        if self._action_registry is None:
            return ()
        try:
            raw = self._action_registry()
        except Exception:  # noqa: BLE001 - 目录面降级（webui 只读先例）。
            return ()
        pairs: set[tuple[str, str]] = set()
        for item in raw or ():
            try:
                action_id, label = str(item[0]), str(item[1])
            except (IndexError, TypeError, ValueError):
                continue
            if action_id:
                pairs.add((action_id, label))
        return tuple(sorted(pairs))

    @staticmethod
    def _config_actions(
        match_key: str, pairs: tuple[tuple[str, str], ...]
    ) -> list[dict[str, str]]:
        if not match_key:
            return []
        return [
            {"action_id": action_id, "name": label}
            for action_id, label in pairs
            if action_id.split(".", 1)[0] == match_key
        ]

    def _resolve_package_version(self, package_key: str) -> str | None:
        if self._version_resolver is not None:
            try:
                resolved = self._version_resolver(package_key)
            except Exception:  # noqa: BLE001 - 版本取不到=null，不炸目录。
                return None
            if isinstance(resolved, str) and resolved.strip():
                return resolved
            return None
        return _default_package_version(self._project_root, package_key)

    # -- builtins -----------------------------------------------------------

    def _builtins_group(
        self, pairs: tuple[tuple[str, str], ...]
    ) -> dict[str, Any]:
        group: dict[str, Any] = {
            "id": "builtins",
            "name": "内置功能",
            "description": "能力树/features store 聚合视图",
            "source": "features_store",
            "enabled": True,
            "reason": None,
            "items": [],
        }
        try:
            rows = list(self._feature_service.list_features())
        except Exception:  # noqa: BLE001 - 单源故障不拖垮整份目录。
            group["enabled"] = False
            group["reason"] = "features_store_unavailable"
            return group
        for row in rows:
            descriptor = row.get("descriptor") or {}
            state = row.get("state") or {}
            enabled = state.get("effective_enabled")
            hot_toggle = descriptor.get("hot_toggle")
            aliases = descriptor.get("aliases")
            hints: list[str] | None = None
            if isinstance(aliases, (list, tuple)):
                cleaned = [str(alias) for alias in aliases if str(alias).strip()]
                hints = cleaned or None
            feature_id = str(descriptor.get("id") or "")
            group["items"].append(
                {
                    "id": feature_id,
                    "name": str(descriptor.get("label") or descriptor.get("id") or ""),
                    "description": str(
                        descriptor.get("capability_id")
                        or descriptor.get("route_kind")
                        or ""
                    ),
                    "kind": str(descriptor.get("kind") or ""),
                    "enabled": bool(enabled) if enabled is not None else None,
                    "hot_reload": bool(hot_toggle) if hot_toggle is not None else None,
                    "source": "features_store",
                    # features descriptor 无版本字段 → null（不猜运行时模块版本）。
                    "version": None,
                    # 能力别名（非聊天触发词全量；触发词注册表跨进程不可内省）。
                    "trigger_hints": hints,
                    "config_actions": self._config_actions(
                        feature_id.rsplit(".", 1)[-1] if feature_id else "", pairs
                    ),
                }
            )
        return group

    # -- adapters -----------------------------------------------------------

    def _adapters_group(
        self, pairs: tuple[tuple[str, str], ...]
    ) -> dict[str, Any]:
        group: dict[str, Any] = {
            "id": "adapters",
            "name": "协议适配器",
            "description": "pyproject [tool.nonebot.adapters] 静态声明",
            "source": "static_config",
            "enabled": True,
            "reason": None,
            "items": [],
        }
        declared = self._declared_adapters()
        if declared is None:
            group["enabled"] = False
            group["reason"] = "static_config_unavailable"
            return group
        for package_key, adapters in declared:
            for adapter in adapters:
                name = str(adapter.get("name") or package_key)
                module = str(adapter.get("module_name") or "")
                group["items"].append(
                    {
                        "name": name,
                        "description": f"{package_key} ({module})" if module else package_key,
                        "enabled": True,  # 声明即启动装载（nonebot init 加载面）。
                        "hot_reload": False,  # 适配器注册在启动期，无热载。
                        "source": "static_config",
                        "version": self._resolve_package_version(package_key),
                        "trigger_hints": None,
                        "config_actions": self._config_actions(package_key, pairs),
                    }
                )
        return group

    def _declared_adapters(self) -> list[tuple[str, list[dict[str, Any]]]] | None:
        path = self._project_root / "pyproject.toml"
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            return None
        section = data.get("tool", {}).get("nonebot", {}).get("adapters")
        if not isinstance(section, Mapping):
            # 有 [tool.nonebot] 但无 adapters 段=声明为空；连 tool.nonebot 都
            # 没有=不是项目清单（读错文件），按不可用处理。
            nonebot_section = data.get("tool", {}).get("nonebot")
            return [] if isinstance(nonebot_section, Mapping) else None
        pairs: list[tuple[str, list[dict[str, Any]]]] = []
        for key in sorted(section):
            entries = section[key]
            if not isinstance(entries, list):
                continue
            pairs.append(
                (
                    str(key),
                    [dict(item) for item in entries if isinstance(item, Mapping)],
                )
            )
        return pairs

    # -- event_matchers -----------------------------------------------------

    def _event_matchers_group(self) -> dict[str, Any]:
        # matcher 注册表活在 bot 宿主进程内存里；控制面与之跨进程，无内省
        # 通道 → 如实 not_available（绝不从路由表反推一份假 matcher 清单）。
        return {
            "id": "event_matchers",
            "name": "事件 matcher",
            "description": "bot 宿主进程内的事件 matcher 注册表",
            "source": "none",
            "enabled": False,
            "reason": "cross_process_introspection_unavailable",
            "items": [],
        }

    # -- migrated_modules ---------------------------------------------------

    def _migrated_modules_group(
        self, pairs: tuple[tuple[str, str], ...]
    ) -> dict[str, Any]:
        group: dict[str, Any] = {
            "id": "migrated_modules",
            "name": "板块重组域清单",
            "description": "domains/ 目录清单（v21r2 板块重组）",
            "source": "filesystem",
            "enabled": True,
            "reason": None,
            "items": [],
        }
        domains_dir = self._project_root / "domains"
        if not domains_dir.is_dir():
            group["reason"] = "domains_dir_unavailable"
            return group
        try:
            entries = sorted(
                item
                for item in domains_dir.iterdir()
                if item.is_dir() and not item.name.startswith(("_", "."))
            )
        except OSError:
            group["reason"] = "domains_dir_unavailable"
            return group
        for domain_dir in entries:
            try:
                # 模块数口径：目录树下全部 .py 文件（含 __init__.py）。
                py_count = len(list(domain_dir.rglob("*.py")))
            except OSError:
                py_count = 0
            entry_file = domain_dir / "__init__.py"
            group["items"].append(
                {
                    "name": domain_dir.name,
                    "description": f"{py_count} 个模块",
                    "source": "filesystem",
                    "hot_reload": False,  # 项目铁律：改代码须重启进程。
                    "enabled": None,  # 目录存在≠启停状态：如实 unknown。
                    "module_count": py_count,
                    "entry_file_exists": entry_file.is_file(),
                    # 域包未声明 __version__ → null（读文件面，绝不 import）。
                    "version": _module_version(entry_file),
                    "trigger_hints": None,
                    "config_actions": self._config_actions(domain_dir.name, pairs),
                }
            )
        return group


def build_default_plugins_service(
    config: object | None,
    *,
    project_root: str | Path | None = None,
    feature_service: Any | None = None,
    action_registry: Callable[[], tuple[tuple[str, str], ...]] | None = None,
) -> PluginsCatalogService:
    """默认装配：features 服务复用 _app 同一实例（未传则按 config 构建）。"""
    root = Path(project_root) if project_root else _PROJECT_ROOT
    if feature_service is None and config is not None:
        from .factory import build_feature_service

        feature_service = build_feature_service(config)
    return PluginsCatalogService(
        feature_service=feature_service,
        project_root=root,
        action_registry=action_registry,
    )
