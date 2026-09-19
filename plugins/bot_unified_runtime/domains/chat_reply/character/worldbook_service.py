"""V2.1 S7 世界观/世界书/参考资料版本化服务（V21-WORLD-001 最小切片）。

合同来源：docs/design/backend-v2-implementation-guide.md §9——

    Persona/World/Worldbook/Reference：draft→validated→published→active 指针；
    正式版本不可变；rollback 创建新版本。……带来源的不可信资料。

+ 验收矩阵行 V21-WORLD-001（World/Worldbook/Reference 版本及预算引用；
悬空/循环引用、世界书 Token 预算、草稿不污染）。

复用边界（本模块刻意保持最小）：
- 生命周期内核（CAS/不可变触发器/损坏隔离/回退）**全部复用**
  ``persona_service.PersonaService``——同一套机制，仅两处差异：
  ①发布权限放宽到 admin（guide §9 仅「发布人格」限超管；世界书属参考资料，
  非核心人格）；②发布前追加资源专属校验（本模块 `_validate_structure`）。
- 世界书内容 = 不可信参考资料，注入定位为「带来源的不可信资料」区：
  ``build_injection`` 出站带 channel="worldbook_reference" + 逐条来源标注，
  结构上不携带 system/persona/permission 语义字段。
- 与 persona 服务的跨库引用：``external_ids`` 注入已知资源 id 集（装配席
  把 persona.published_ids 传入即可），世界书自身不读 persona 库。

校验三件（发布时强制，失败不产生版本）：
1. **悬空引用**：refs 里指向不存在资源（本库已发布集 ∪ external_ids）→ 拒发。
2. **循环引用**：worldbook→worldbook 引用图 DFS，候选资源可被自己可达 → 拒发
   （含自引用；跨库循环在本切片不可达，属已知边界，见日志）。
3. **Token 预算**：CJK≈1 token/字 + 其他 len/4 的粗估，全库 entries 总量
   超 ``token_budget`` → 拒发（防参考资料挤爆提示词预算）。
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.chat_reply.character.persona_service import (
    PersonaNotFoundError,
    PersonaService,
    PersonaValidationError,
    VersionedResourceStore,
    _utc_now,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import ROLE_ADMIN

logger = logging.getLogger(__name__)

__all__ = [
    "WorldbookBudgetError",
    "WorldbookCircularRefError",
    "WorldbookDanglingRefError",
    "WorldbookPermissionError",
    "WorldbookService",
    "WorldbookStructureError",
    "WorldbookValidationError",
    "build_worldbook_service",
    "estimate_tokens",
]

DEFAULT_WORLDBOOK_DB_PATH = "data/worldbook_versions.sqlite3"
DEFAULT_TOKEN_BUDGET = 8192

# CJK 表意区（含扩展A/平假名片假名/谚文/全形符号）：≈1 token/字（粗估口径，
# 与 model_router 的 CJK 上下文粗估同取向，不追求分词器精确值）。
_CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0x3040, 0x30FF),
    (0xAC00, 0xD7AF),
    (0xFF00, 0xFFEF),
)


class WorldbookPermissionError(PermissionError):
    """世界书角色不足（draft/publish/activate/rollback 需 admin+）。"""


class WorldbookValidationError(PersonaValidationError):
    """世界书发布校验失败（结构/引用/预算），不产生版本。"""


class WorldbookStructureError(WorldbookValidationError):
    """内容结构非法（entries/refs 形状）。"""


class WorldbookDanglingRefError(WorldbookValidationError):
    """悬空引用：refs 指向不存在的资源 id。"""


class WorldbookCircularRefError(WorldbookValidationError):
    """循环引用：候选资源经引用图可达自身。"""


class WorldbookBudgetError(WorldbookValidationError):
    """Token 预算超限。"""


def estimate_tokens(text: str) -> int:
    """CJK≈1 token/字 + 其他字符 len/4 的确定性粗估（无分词器依赖、全离线）。"""
    cjk = 0
    other = 0
    for ch in text:
        code = ord(ch)
        if any(lo <= code <= hi for lo, hi in _CJK_RANGES):
            cjk += 1
        else:
            other += 1
    return cjk + math.ceil(other / 4)


def canonical_text(structure: dict[str, Any]) -> str:
    """结构 → 确定性 JSON 文本（sort_keys；哈希与落库都以这份文本为准）。"""
    return json.dumps(structure, ensure_ascii=False, sort_keys=True)


def parse_structure(text: str) -> dict[str, Any]:
    try:
        structure = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorldbookStructureError(f"世界书内容不是合法 JSON：{exc}") from exc
    if not isinstance(structure, dict):
        raise WorldbookStructureError("世界书内容必须是 JSON 对象")
    return structure


class WorldbookLifecycle(PersonaService):
    """世界书生命周期：复用 persona 内核，发布权限放宽到 admin。"""

    permission_error = WorldbookPermissionError
    validation_error = WorldbookValidationError

    def __init__(
        self,
        store: VersionedResourceStore,
        *,
        validator: Callable[[str, str], None],
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        super().__init__(
            store,
            clock=clock,
            publish_role=ROLE_ADMIN,
            publish_validator=validator,
        )


class WorldbookService:
    """世界观/世界书/参考资料版本化最小切片（版本化+引用校验+预算）。"""

    def __init__(
        self,
        store: VersionedResourceStore,
        *,
        external_ids: Callable[[], set[str]] | None = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._external_ids = external_ids
        self.token_budget = int(token_budget)
        self._clock = clock
        self._lifecycle = WorldbookLifecycle(store, validator=self._validate_structure,
                                             clock=clock)

    # ------------------------------------------------------------------ 生命周期

    def draft(
        self,
        resource_id: str,
        structure: dict[str, Any],
        *,
        actor: str,
        roles: list[str],
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        self._check_shape(structure)
        return self._lifecycle.draft(
            resource_id,
            canonical_text(structure),
            actor=actor,
            roles=roles,
            expected_version=expected_version,
        )

    def publish(
        self,
        resource_id: str,
        *,
        actor: str,
        roles: list[str],
        expected_version: int,
    ) -> dict[str, Any]:
        result = self._lifecycle.publish(
            resource_id, actor=actor, roles=roles, expected_version=expected_version
        )
        row = self._lifecycle.store.get_version(resource_id, int(result["version"]))
        if row is None:  # pragma: no cover — publish 成功后版本行必然存在
            raise PersonaNotFoundError(resource_id)
        result["token_estimate"] = estimate_tokens(str(row["content"]))
        return result

    def activate(
        self, resource_id: str, version: int, *, actor: str, roles: list[str]
    ) -> dict[str, Any]:
        return self._lifecycle.activate(
            resource_id, version, actor=actor, roles=roles
        )

    def rollback(
        self,
        resource_id: str,
        to_version: int,
        *,
        actor: str,
        roles: list[str],
    ) -> dict[str, Any]:
        return self._lifecycle.rollback(
            resource_id, to_version, actor=actor, roles=roles
        )

    def list_versions(self, resource_id: str) -> list[dict[str, Any]]:
        return self._lifecycle.list_versions(resource_id)

    def quarantine_records(self, resource_id: str) -> list[dict[str, Any]]:
        return self._lifecycle.quarantine_records(resource_id)

    # ------------------------------------------------------------------ 读出/注入

    def load_active(self, resource_id: str) -> dict[str, Any]:
        """active 版本 → 结构 dict（损坏隔离/回退由内核 PersonaLoad 承担）。"""
        load = self._lifecycle.load_active(resource_id)
        structure = parse_structure(load.content)
        return {
            "resource_id": load.resource_id,
            "version": load.version,
            "persona_revision": load.persona_revision,
            "content_sha256": load.content_sha256,
            "degraded": load.degraded,
            "structure": structure,
        }

    def build_injection(self, resource_id: str) -> dict[str, Any]:
        """参考资料唯一出站路径：带来源标注的「不可信资料」区材料。"""
        loaded = self.load_active(resource_id)
        structure = loaded["structure"]
        entries = [
            {
                "id": str(entry["id"]),
                "title": str(entry.get("title", "")),
                "content": str(entry.get("content", "")),
                "source": f"worldbook:{loaded['resource_id']}@v{loaded['version']}",
                "untrusted": True,
            }
            for entry in structure.get("entries", [])
        ]
        return {
            "channel": "worldbook_reference",
            "source": "version_store",
            "resource_id": loaded["resource_id"],
            "version": loaded["version"],
            "revision": loaded["persona_revision"],
            "content_sha256": loaded["content_sha256"],
            "degraded": loaded["degraded"],
            "token_estimate": sum(
                estimate_tokens(str(e["title"]) + str(e["content"])) for e in entries
            ),
            "entries": entries,
        }

    # ------------------------------------------------------------------ 校验

    def validate(self, structure_or_id: str | dict[str, Any]) -> dict[str, Any]:
        """只读校验（不产生版本）：悬空/循环/预算三件 + 汇总判定。"""
        if isinstance(structure_or_id, str):
            state = self._lifecycle.get_state(structure_or_id)
            row = self._lifecycle.store.get_version(
                structure_or_id, int(state["active_version"])
            )
            if row is None:
                raise PersonaNotFoundError(structure_or_id)
            structure = parse_structure(str(row["content"]))
            resource_id = structure_or_id
        else:
            structure = structure_or_id
            resource_id = "<candidate>"
        return self._checks(resource_id, structure)

    def _validate_structure(self, resource_id: str, text: str) -> None:
        structure = parse_structure(text)
        report = self._checks(resource_id, structure)
        if report["ok"]:
            return
        # 按首类失败抛专属异常（发布期强制；失败不产生版本）。
        for kind, detail in report["issues"]:
            if kind == "dangling":
                raise WorldbookDanglingRefError(
                    f"{resource_id} 悬空引用：{detail}"
                )
            if kind == "circular":
                raise WorldbookCircularRefError(f"{resource_id} 循环引用：{detail}")
            if kind == "budget":
                raise WorldbookBudgetError(f"{resource_id} Token 预算超限：{detail}")
        raise WorldbookValidationError(
            f"{resource_id} 校验失败：{report['problems']}"
        )

    def _checks(self, resource_id: str, structure: dict[str, Any]) -> dict[str, Any]:
        self._check_shape(structure)
        issues: list[tuple[str, str]] = []
        refs = [str(r) for r in structure.get("refs", [])]

        # 1. 悬空引用。
        dangling = sorted(set(refs) - self._known_ids())
        if dangling:
            issues.append(("dangling", f"{dangling}（库内+外部已知集均无）"))

        # 2. 循环引用（worldbook→worldbook 引用图；含自引用）。
        edges = self._worldbook_edges()
        edges[resource_id] = [r for r in refs if r in self._own_ids()]
        cycle = self._find_cycle(resource_id, edges)
        if cycle is not None:
            issues.append(("circular", " -> ".join(cycle)))

        # 3. Token 预算。
        tokens = self.tokens_of_structure(structure)
        if tokens > self.token_budget:
            issues.append(("budget", f"{tokens} > {self.token_budget}"))

        return {
            "ok": not issues,
            "issues": issues,
            "problems": [f"{kind}: {detail}" for kind, detail in issues],
            "token_estimate": tokens,
            "token_budget": self.token_budget,
        }

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _check_shape(structure: dict[str, Any]) -> None:
        if not isinstance(structure, dict):
            raise WorldbookStructureError("世界书结构必须是对象")
        entries = structure.get("entries")
        if not isinstance(entries, list) or not entries:
            raise WorldbookStructureError("entries 必须是非空数组")
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise WorldbookStructureError("entry 必须是对象")
            entry_id = str(entry.get("id", "")).strip()
            if not entry_id:
                raise WorldbookStructureError("entry.id 不得为空")
            if entry_id in seen:
                raise WorldbookStructureError(f"entry.id 重复：{entry_id}")
            seen.add(entry_id)
            if not isinstance(entry.get("content", ""), str):
                raise WorldbookStructureError(f"entry.content 必须是文本：{entry_id}")
        refs = structure.get("refs", [])
        if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs):
            raise WorldbookStructureError("refs 必须是字符串数组")

    def _known_ids(self) -> set[str]:
        known = set(self._lifecycle.store.published_ids())
        if self._external_ids is not None:
            known |= set(self._external_ids())
        return known

    def _own_ids(self) -> set[str]:
        return set(self._lifecycle.store.published_ids())

    def _worldbook_edges(self) -> dict[str, list[str]]:
        """全部已发布世界书的最新版引用边（仅库内边，跨库边不参与环检测）。"""
        edges: dict[str, list[str]] = {}
        for resource_id in self._lifecycle.store.published_ids():
            versions = self._lifecycle.store.versions_desc(resource_id)
            if not versions:
                continue
            try:
                structure = parse_structure(str(versions[0]["content"]))
                refs = [str(r) for r in structure.get("refs", [])]
            except WorldbookStructureError:
                refs = []
            edges[resource_id] = [r for r in refs if r in self._own_ids()]
        return edges

    @staticmethod
    def _find_cycle(start: str, edges: dict[str, list[str]]) -> list[str] | None:
        """环检测：从 start 的直接引用出发 DFS，可达 start 自身即成环（含自引用）。"""
        stack: list[tuple[str, list[str]]] = [
            (nxt, [start, nxt]) for nxt in edges.get(start, [])
        ]
        seen: set[str] = set()
        while stack:
            node, path = stack.pop()
            if node == start:
                return path
            if node in seen:
                continue
            seen.add(node)
            for nxt in edges.get(node, []):
                if nxt not in seen:
                    stack.append((nxt, [*path, nxt]))
        return None

    def tokens_of_structure(self, structure: dict[str, Any]) -> int:
        title = str(structure.get("title", ""))
        body = "".join(
            str(entry.get("title", "")) + str(entry.get("content", ""))
            for entry in structure.get("entries", [])
        )
        return estimate_tokens(title + body)


def build_worldbook_service(
    db_path: str | Path | None = None,
    *,
    external_ids: Callable[[], set[str]] | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    clock: Callable[[], str] | None = None,
) -> WorldbookService:
    """装配入口：缺省路径经 runtime_path 重映射到 Runtime data/。"""
    if db_path is None:
        from scripts.runtime_paths import runtime_path

        db_path = runtime_path(DEFAULT_WORLDBOOK_DB_PATH)
    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    return WorldbookService(
        VersionedResourceStore(db_path, prefix="worldbook"),
        external_ids=external_ids,
        token_budget=token_budget,
        **kwargs,
    )
