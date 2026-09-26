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

**CM-P-9（2026-09-24 S44，P2「降为再导出垫片」的前置）**：声明源日后可能改成
"从册再导出"的薄壳（``from X import Y as Y`` / ``from X import *`` + ``__all__``）。
本件因此会把再导出**顺链解析到真身文件**再取值；链不通 ⇒ 点名抛错。塌陷锁：
``CHANNEL_CAPABILITY_KINDS`` 空表 / ``NATIVE_MEDIA_KINDS`` 空集 / 前缀为空 ⇒
**当场抛错**（空表与"能力标签被抹光"同形——S28 事故正是抹光后静默报成功），
绝不返回空视图。锁的测试与注毒验牙见
``tests/test_declaration_readers_no_silent_empty.py``。
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

# 再导出链追层上限（CM-P-9）：壳→册→再壳也够；超限=失控或成环，停手点名报错。
_MAX_FOLLOW_HOPS = 8

# 剥一层就是字面量的容器壳：真身册惯用 MappingProxyType(...)/frozenset(...) 包表，
# 追到真身后取值要先剥这些壳；壳内仍必须是 ast.literal_eval 认得的纯字面量。
_WRAPPER_NAMES = frozenset({"dict", "tuple", "list", "set", "frozenset", "MappingProxyType"})


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


def _rel_to_root(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _unwrap_literal(node: ast.expr, *, path: Path, root: Path, name: str) -> Any:
    """常量节点 → 值：剥已知容器壳一层后必须仍是 ``ast.literal_eval`` 认得的字面量。"""
    while (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _WRAPPER_NAMES
        and len(node.args) == 1
        and not node.keywords
    ):
        node = node.args[0]
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise ValueError(
            f"声明源 {_rel_to_root(path, root)}::{name} 不是字面量形态（{exc}）——"
            "脚本侧读取口只认字面量（含 MappingProxyType/frozenset 等可剥壳形态），拒绝猜值"
        ) from exc


def _resolve_import_source(from_file: Path, module: str | None, level: int, root: Path) -> Path | None:
    """import 语句 → 仓内真实 .py 文件；解析不到返回 None（= 来源不在仓内，由调用方裁决）。

    相对导入（level≥1）沿 from_file 上跳；绝对导入依次尝试仓库根 / ``plugins/`` /
    包根三个锚点（本仓包内互引的实况形态是 ``from plugins.bot_unified_runtime.…``）。
    """
    if level >= 1:
        base = from_file.parent
        for _ in range(level - 1):
            base = base.parent
        target: Path | None = base.joinpath(*module.split(".")) if module else base
    else:
        if not module:
            return None
        parts = module.split(".")
        target = None
        for anchor in (root, root / "plugins", root / "plugins" / "bot_unified_runtime"):
            candidate = anchor.joinpath(*parts)
            if candidate.with_suffix(".py").is_file() or candidate.is_dir():
                target = candidate
                break
    if target is None:
        return None
    if target.is_dir():
        init = target / "__init__.py"
        return init if init.is_file() else None
    py = target.with_suffix(".py")
    return py if py.is_file() else None


def _collect_constants(
    path: Path,
    root: Path,
    *,
    wanted: tuple[str, ...],
    seen: frozenset[str],
    hops: int,
) -> dict[str, Any]:
    """解析一个文件、收 wanted 常量：就地字面量直取；缺的顺再导出链追到真身（CM-P-9）.

    支持的再导出形态（P2 垫片预告的写法）：
    ``from X import Y`` / ``from X import Y as Y`` / ``from X import *`` /
    它们的相对导入形（``from .x import Y`` / ``from ..pkg.x import Y``）。
    失败形态一律**点名抛错**、绝不静默给空：文件读不出、链成环、超 ``_MAX_FOLLOW_HOPS``、
    显式再导出的来源解析不到仓内文件、以及剥壳后非字面量。
    （``from *`` 的来源解析不到时允许跳过——仓外星号本来就不提供这些名字，
    最终"缺常量"判定由调用方的 missing 检查兜底报红，不存在漏网。）
    """
    if hops > _MAX_FOLLOW_HOPS:
        raise ValueError(
            f"再导出链超过 {_MAX_FOLLOW_HOPS} 层仍未见真身（末站 {_rel_to_root(path, root)}）——拒绝继续"
        )
    key = str(path.resolve()).lower()
    if key in seen:
        raise ValueError(f"再导出链绕回 {_rel_to_root(path, root)}（循环再导出）——拒绝继续")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(f"能力标签声明源读不出：{path}: {exc}") from exc
    except SyntaxError as exc:
        raise ValueError(f"能力标签声明源解析失败：{path}: {exc}") from exc

    literals: dict[str, ast.expr] = {}
    rebinds: dict[str, tuple[str, str | None, int]] = {}  # 本地名 -> (真名, 模块, level)
    star_sources: list[tuple[str | None, int]] = []
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and node.targets:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if target is not None and value is not None and isinstance(target, ast.Name) and target.id in wanted:
            literals[target.id] = value  # 同名多次赋值：后写覆盖（与旧实现同语义）
            continue
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    star_sources.append((node.module, node.level))
                    continue
                local = alias.asname or alias.name
                if local in wanted and local not in literals:
                    rebinds[local] = (alias.name, node.module, node.level)

    found: dict[str, Any] = {}
    for name, const_node in literals.items():
        found[name] = _unwrap_literal(const_node, path=path, root=root, name=name)
    chain = seen | {key}
    for name in wanted:
        if name in found or name not in rebinds:
            continue
        origin_name, module, level = rebinds[name]
        source = _resolve_import_source(path, module, level, root)
        if source is None:
            raise ValueError(
                f"{_rel_to_root(path, root)} 把 {name} 再导出自 {module or '<所在包>'}（level={level}），"
                "但仓内找不到真身文件——追再导出要求看得见真身，拒绝返回空"
            )
        found[name] = _collect_constants(
            source, root, wanted=(origin_name,), seen=chain, hops=hops + 1
        )[origin_name]
    still_missing = tuple(name for name in wanted if name not in found)
    if still_missing and star_sources:
        for module, level in star_sources:
            source = _resolve_import_source(path, module, level, root)
            if source is None:
                continue
            sub = _collect_constants(source, root, wanted=still_missing, seen=chain, hops=hops + 1)
            for name, value in sub.items():
                found.setdefault(name, value)
            if all(name in found for name in still_missing):
                break
    return found


def load_declaration(project_root: Path) -> ChannelCapabilityDeclaration:
    """读声明源（AST，不 import；再导出顺链到真身）。缺文件/缺常量/空表都抛错——宁可炸也不给空视图.

    抛而不是返回空：空视图会让"没有渠道需要能力标签"成为**默认绿**，那正是本波
    要根修的那类假绿（声明源被误删 ⇒ 体检静默放行；S28 抹标签事故同型）。
    """
    root = Path(project_root)
    path = declaration_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"能力标签声明源缺失：{path}")
    constants = _collect_constants(path, root, wanted=_WANTED, seen=frozenset(), hops=0)
    missing = [name for name in _WANTED if name not in constants]
    if missing:
        raise ValueError(f"能力标签声明源缺常量 {missing}：{path}")
    # ---- 塌陷锁（CM-P-9）：空表与"声明被抹光"同形 ⇒ 停手报，不出视图 ----
    kinds_raw = dict(constants["CHANNEL_CAPABILITY_KINDS"])
    if not kinds_raw:
        raise ValueError(
            f"塌陷锁：{_rel_to_root(path, root)}::CHANNEL_CAPABILITY_KINDS 为空表——"
            "空表与「能力标签被整批抹光」不可分辨（S28 事故形），拒绝产出空视图；"
            "确要清零请显式删除该声明并同步三处消费方"
        )
    known_kinds = tuple(sorted(str(kind) for kind in constants["NATIVE_MEDIA_KINDS"]))
    if not known_kinds:
        raise ValueError(
            f"塌陷锁：{_rel_to_root(path, root)}::NATIVE_MEDIA_KINDS 为空——已知 kind 登记面被抹，"
            "校验与体检会跟着失明"
        )
    native_prefix = str(constants["NATIVE_TAG_PREFIX"])
    if not native_prefix.strip():
        raise ValueError(
            f"塌陷锁：{_rel_to_root(path, root)}::NATIVE_TAG_PREFIX 为空——前缀为空则一切标签判据失效"
        )
    kinds_by_entry = {
        str(entry_id): tuple(sorted(str(kind) for kind in kinds))
        for entry_id, kinds in kinds_raw.items()
    }
    return ChannelCapabilityDeclaration(
        native_prefix=native_prefix,
        known_kinds=known_kinds,
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
