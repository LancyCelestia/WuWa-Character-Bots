"""``domains/core/channel_capability_tags.py`` 的脚本侧读取口（T4，一处真身的第二半）.

为什么不是直接 ``import``：插件根 ``plugins/bot_unified_runtime/__init__.py`` 是重件
（NoneBot 插件入口，import 即注册 matcher、拉起全家），重启前体检与写回脚本都不该为
了一组常量把它整个拽起来。沿 ``scripts/board_doc_sync.py`` 读 ``board_taxonomy.py``
的既有哲学——**AST 静态解析声明源**，不 import 包内模块。

本件只做两件事：
1. ``load_declaration(project_root)``——把能力标签声明读成结构化视图；
2. ``read_registry_file(path)``——只读运行时注册表 JSON，坏文件/缺文件一律返回空
   （由调用方判 SKIP 还是 FAIL，本件不裁决）。

⚠ 活性锁在 ``tests/test_tag_presence_gate.py``：AST 视图与运行时 import 视图必须
逐字段相等。声明源若被改成非字面量形态（加了函数调用、推导式），那条锁会当场红——
这是本文件存在的唯一前提，别用放宽它的方式"修"它。
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DECLARATION_REL = "plugins/bot_unified_runtime/domains/core/channel_capability_tags.py"

# 只读这三枚模块级常量；别的名字一律不认（认多了=把实现细节当契约）
_WANTED = ("NATIVE_TAG_PREFIX", "NATIVE_MEDIA_KINDS", "CHANNEL_CAPABILITY_KINDS")


@dataclass(frozen=True)
class ChannelCapabilityDeclaration:
    """能力标签声明的脚本侧视图（全部来自声明源，本件不发明任何值）."""

    native_prefix: str
    known_kinds: tuple[str, ...]
    kinds_by_entry: dict[str, tuple[str, ...]]

    def declared_entry_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.kinds_by_entry))

    def required_tags_for(self, entry_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(f"{self.native_prefix}{kind}" for kind in self.kinds_by_entry.get(entry_id, ()))
        )


def declaration_path(project_root: Path) -> Path:
    return Path(project_root) / _DECLARATION_REL


def _module_constants(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    found: dict[str, Any] = {}
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and node.targets:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if target is None or value is None or not isinstance(target, ast.Name):
            continue
        if target.id in _WANTED:
            found[target.id] = ast.literal_eval(value)
    return found


def load_declaration(project_root: Path) -> ChannelCapabilityDeclaration:
    """读声明源（AST，不 import）。缺文件/缺常量都抛错——宁可炸也不给空视图.

    抛而不是返回空：空视图会让"没有渠道需要能力标签"成为**默认绿**，那正是本波
    要根修的那类假绿（声明源被误删 ⇒ 体检静默放行）。
    """
    path = declaration_path(project_root)
    if not path.is_file():
        raise FileNotFoundError(f"能力标签声明源缺失：{path}")
    constants = _module_constants(path.read_text(encoding="utf-8"))
    missing = [name for name in _WANTED if name not in constants]
    if missing:
        raise ValueError(f"能力标签声明源缺常量 {missing}：{path}")
    kinds_by_entry = {
        str(entry_id): tuple(sorted(str(kind) for kind in kinds))
        for entry_id, kinds in dict(constants["CHANNEL_CAPABILITY_KINDS"]).items()
    }
    return ChannelCapabilityDeclaration(
        native_prefix=str(constants["NATIVE_TAG_PREFIX"]),
        known_kinds=tuple(sorted(str(kind) for kind in constants["NATIVE_MEDIA_KINDS"])),
        kinds_by_entry=kinds_by_entry,
    )


def read_registry_file(path: Path) -> dict[str, dict]:
    """只读运行时注册表条目；文件缺失/非 JSON/顶层或 model_registry 非对象 ⇒ 空 dict."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    registry = payload.get("model_registry")
    if not isinstance(registry, dict):
        return {}
    return {str(key): dict(value) for key, value in registry.items() if isinstance(value, dict)}


def read_env_registry(env: dict[str, str]) -> dict[str, dict]:
    """读 ``BOT_MODEL_REGISTRY``（.env 侧）；未配置/非对象 ⇒ 空 dict（不裁决）."""
    raw = str(env.get("BOT_MODEL_REGISTRY", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): dict(value) for key, value in parsed.items() if isinstance(value, dict)}


def tags_of(entry: dict | None) -> list[str]:
    """条目 tags 的取值口（list / 逗号串两形都吃，与 model_router 装载口径一致）.

    收 None：调用方常见形态是「两侧注册表各查一次，可能都没这条」，None 就是
    "这条不存在" ⇒ 空列表，让"缺席"与"在册但标签被抹"走同一条 FAIL 判据。
    """
    if not entry:
        return []
    raw = entry.get("tags")
    if isinstance(raw, list):
        return [str(tag) for tag in raw]
    if isinstance(raw, str):
        return [tag.strip() for tag in raw.split(",") if tag.strip()]
    return []
