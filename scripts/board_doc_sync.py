"""十板块文档树生成器（板块层单一投影口，2026-09-21）。

设计契约见 `docs/boards/_conventions.md` 第四节。要点：

- **不 import 插件包**（与 `doc_sync.py` 同理由：插件根 `__init__.py` 是重件），
  全部用 AST/正则静态解析三份声明源：
  `domains/core/board_taxonomy.py`（板块树）、
  `domains/chat_reply/runtime/capability_registry.py`（能力 keystone）、
  `domains/chat_reply/runtime/base_router.py`（RouteKind 枚举字面形态）。
- **人工正文永不覆盖**：每个文档里 `<!-- BOARD-AUTO:BEGIN -->…END` 之间由本脚本
  重写，标记之外（含首次生成的骨架正文）原样保留。
- **--check 即门禁**：覆盖缺口、重复认领、实现路径不存在、生成物漂移，任一命中
  退出码非 0。常驻门是 `tests/test_board_taxonomy_gate.py`。

用法：
    python scripts/board_doc_sync.py --write   # 生成/就地更新 docs/boards/**
    python scripts/board_doc_sync.py --check   # 只体检（缺省）
    python scripts/board_doc_sync.py --dump    # 打派生清单（排障用，不落盘）
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
BOARDS_DIR = ROOT / "docs" / "boards"
TAXONOMY_PY = ROOT / "plugins/bot_unified_runtime/domains/core/board_taxonomy.py"
KEYSTONE_PY = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py"
ROUTER_PY = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py"
CONFIG_PY = ROOT / "plugins/bot_unified_runtime/config.py"

AUTO_BEGIN = "<!-- BOARD-AUTO:BEGIN -->"
AUTO_END = "<!-- BOARD-AUTO:END -->"
AUTO_NOTE = "<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->"


# --------------------------------------------------------------------------
# 声明源静态解析
# --------------------------------------------------------------------------
def _kwargs_as_literal(node: ast.Call) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kw in node.keywords:
        if kw.arg is None:
            continue
        try:
            out[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            out[kw.arg] = None
    return out


def _collect_calls(tree: ast.AST, names: set[str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names:
            data = _kwargs_as_literal(node)
            data["_name"] = node.func.id
            found.append(data)
    return found


def _board_node(el: ast.Call) -> dict[str, Any]:
    """BoardNode 的 features 是嵌套 Call 元组，literal_eval 处理不了，单独展开。"""
    data = _kwargs_as_literal(el)
    features: list[dict[str, Any]] = []
    for kw in el.keywords:
        if kw.arg != "features" or not isinstance(kw.value, (ast.Tuple, ast.List)):
            continue
        for elt in kw.value.elts:
            if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name):
                features.append(_kwargs_as_literal(elt))
    data["features"] = features
    return data


def load_taxonomy() -> list[dict[str, Any]]:
    """板块树：[{board…}, …]，每个 board 带 features 列表。"""
    tree = ast.parse(TAXONOMY_PY.read_text(encoding="utf-8"))
    boards: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
        else:
            continue
        if not isinstance(value, ast.Tuple):
            continue
        for el in value.elts:
            if isinstance(el, ast.Call) and isinstance(el.func, ast.Name) and el.func.id == "BoardNode":
                boards.append(_board_node(el))
    boards.sort(key=lambda b: str(b.get("bid", "")))
    return boards


def load_route_index() -> dict[str, dict[str, object]]:
    """RouteKind 成员名 -> {capability_id, priority, label}（keystone 权威）。"""
    tree = ast.parse(KEYSTONE_PY.read_text(encoding="utf-8"))
    index: dict[str, dict[str, object]] = {}
    for call in _collect_calls(tree, {"RouteCapabilityDecl"}):
        kind = call.get("kind")
        if isinstance(kind, str):
            index[kind] = {
                "capability_id": call.get("capability_id", ""),
                "priority": call.get("priority"),
                "label": call.get("label", ""),
                "value": call.get("value", ""),
                "command": bool(call.get("command")),
            }
    return index


def load_route_kind_members() -> list[str]:
    text = ROUTER_PY.read_text(encoding="utf-8")
    body = text.split("class RouteKind(", 1)
    if len(body) < 2:
        return []
    seg = body[1].split("\n\n\n", 1)[0]
    return re.findall(r"^\s{4}([A-Z][A-Z0-9_]*)\s*=", seg, re.MULTILINE)


def load_help_topics() -> list[str]:
    tree = ast.parse(KEYSTONE_PY.read_text(encoding="utf-8"))
    return [
        str(c.get("topic", ""))
        for c in _collect_calls(tree, {"HelpTopicDecl"})
        if c.get("topic")
    ]


def load_config_fields() -> list[str]:
    text = CONFIG_PY.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"^\s{4}(bot_[a-z0-9_]+)\s*[:=]", text, re.MULTILINE)))


# --------------------------------------------------------------------------
# 树构建与体检
# --------------------------------------------------------------------------
@dataclass
class L3:
    slug: str
    label: str
    route_kind: str = ""
    capability_id: str = ""
    help_topics: tuple[str, ...] = ()
    priority: object = None


@dataclass
class Feature:
    node: dict[str, Any]
    bid: str
    l3: list[L3] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return str(self.node["slug"])

    @property
    def fid(self) -> str:
        return str(self.node["fid"])


@dataclass
class Board:
    node: dict[str, object]
    features: list[Feature]

    @property
    def bid(self) -> str:
        return str(self.node["bid"])

    @property
    def dir_name(self) -> str:
        return f"{self.bid}-{self.node['slug']}"


def build_tree() -> tuple[list[Board], list[str]]:
    """返回 (板块树, 体检问题清单)。三级入口在此派生。"""
    route_index = load_route_index()
    problems: list[str] = []

    boards: list[Board] = []
    seen_fid: dict[str, str] = {}
    claimed_kinds: dict[str, str] = {}
    claimed_topics: dict[str, str] = {}

    for bnode in load_taxonomy():
        bid = str(bnode.get("bid", "?"))
        feats: list[Feature] = []
        for fnode in bnode.get("features") or ():  # type: ignore[union-attr]
            fid = str(fnode.get("fid", ""))
            if fid in seen_fid:
                problems.append(f"fid 重复：{fid}（{seen_fid[fid]} 与 {bid}）")
            seen_fid[fid] = bid
            feature = Feature(node=fnode, bid=bid)
            for kind in fnode.get("route_kinds") or ():  # type: ignore[union-attr]
                if kind in claimed_kinds:
                    problems.append(
                        f"RouteKind 被两个二级功能抢：{kind} ⇒ {claimed_kinds[kind]} / {fid}"
                    )
                claimed_kinds[str(kind)] = fid
                info = route_index.get(str(kind))
                if info is None:
                    problems.append(f"代码里没有 RouteKind {kind}，但板块树 {fid} 认领了它")
                    continue
                feature.l3.append(
                    L3(
                        slug=_kebab(str(info["label"] or kind), fallback=str(kind).lower()),
                        label=str(info["label"] or kind),
                        route_kind=str(kind),
                        capability_id=str(info["capability_id"]),
                        priority=info["priority"],
                    )
                )
            for cap in fnode.get("capability_ids") or ():  # type: ignore[union-attr]
                if cap in {x.capability_id for x in feature.l3}:
                    continue
                known_caps = {str(v["capability_id"]) for v in route_index.values()}
                if cap not in known_caps and not _cap_declared_elsewhere(str(cap)):
                    problems.append(f"capability_id 未在 keystone 登记：{cap}（{fid}）")
                feature.l3.append(
                    L3(slug=_kebab(str(cap).split(".")[-1], fallback="cap"), label=str(cap), capability_id=str(cap))
                )
            for topic in fnode.get("help_topics") or ():  # type: ignore[union-attr]
                if topic in claimed_topics:
                    problems.append(f"帮助主题被两处认领：{topic} ⇒ {claimed_topics[topic]} / {fid}")
                claimed_topics[str(topic)] = fid
            for slug, label in fnode.get("extra_l3") or ():  # type: ignore[union-attr]
                feature.l3.append(L3(slug=str(slug), label=str(label)))
            for path in fnode.get("impl_paths") or ():  # type: ignore[union-attr]
                if not (ROOT / str(path)).exists():
                    problems.append(f"实现路径不存在：{path}（{fid}）")
            feats.append(feature)
        if not feats:
            problems.append(f"板块 {bid} 没有任何二级功能")
        boards.append(Board(node=bnode, features=feats))

    # 覆盖门（活性判据）：代码里有而没人认领 ⇒ 红
    for kind in load_route_kind_members():
        if kind not in claimed_kinds:
            problems.append(f"RouteKind {kind} 未被任何二级功能认领（板块树缺登记）")
    for topic in load_help_topics():
        if topic not in claimed_topics:
            problems.append(f"帮助主题「{topic}」未被任何二级功能认领（板块树缺登记）")
    return boards, problems


def _cap_declared_elsewhere(cap: str) -> bool:
    text = KEYSTONE_PY.read_text(encoding="utf-8")
    return f'"{cap}"' in text


def _kebab(text: str, fallback: str = "x") -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(ascii_part) >= 3:
        return ascii_part
    cjk = re.sub(r"[一-鿿]+", "", text)
    stem = re.sub(r"[^a-z0-9]+", "-", cjk.lower()).strip("-")
    return stem or re.sub(r"[^a-z0-9]+", "-", fallback.lower()).strip("-")


def owned_topics(feature: Feature, all_topics: list[str]) -> list[str]:
    return [t for t in feature.node.get("help_topics") or () if t in all_topics]


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------
def _page(title: str, auto: str, body: str) -> str:
    return (
        f"# {title}\n\n"
        f"{AUTO_BEGIN}\n{AUTO_NOTE}\n\n{auto.rstrip()}\n{AUTO_END}\n\n"
        f"{body.strip()}\n"
    )


L2_BODY = """## 这个功能解决什么

（待写：一到三段大白话，说清它替谁解决什么问题。）

## 处理流程

```mermaid
flowchart LR
  in[入口] --> core[处理] --> out[产出]
```

## 边界与降级

（待写：外部依赖挂了怎么办、无源时如何诚实、权限门与限额。）

## 测试与验收

（待写：离线用例件与真机验收条目指针。）

## 现行缺陷

（待写：已知未修的 P0/P1/P2 与本功能相关项，指真身台账。）
"""

L3_BODY = """## 这个入口做什么

（待写：一到五句，说清输入、产出、生效条件。）

## 怎么调用

（待写：入口函数签名与它依赖的中央件；只准列已登记的函数。）

## 开关与参数

（待写：配置键、缺省值、热更性、谁能改。）

## 失败时看到什么

（待写：失败面文案与降级路径。）

## 测试与验收

（待写：对应测试件与真机验收编号。）
"""

L1_BODY = """## 板块职责

（本板块的 responsibilities 已在上方自动生成；此处补写"为什么这样切"与与其他板块的边界。）

## 上下游

（待写：本板块的入站来自哪个板块、产出交给哪个板块，只画本段。）

## 退役与并入记录

（待写：本板块吸收了哪些旧文档；旧文档现在何处。）
"""

#: 板块树**索引页**（`docs/boards/README.md`）的人写区骨架真身（席 S83＝《S39》落地）。
#: 索引页与单板块页同判 `board-l1` 是 G-T2 唯一偏离件的根因（S35 取证）——它的真形是
#: 单节「怎么读这套文档」，硬改成 L1 骨架＝扭曲内容凑骨架的假绿，故另立 `board-index` 类，
#: 且**该类不建第二枚模板文件**：骨架唯一真身就是本常量（与 `board-l1/l2/l3` 同型——
#: 那三类也只有 `L1_BODY/L2_BODY/L3_BODY`、`docs/templates/` 下无对应文件）。
#: 消费点唯一＝下方 `write_tree()` 建索引页时；类别注册表以
#: `generated_by="scripts/board_doc_sync.py:INDEX_BODY"` 指回本符号（G-T5 AST 核验其存在），
#: G-T2 的 canon 由 `spec_gates_census.py` 侧 `canon_of_skeleton(bds.INDEX_BODY)` 派生（同支取数，
#: 交接见 SEAT-S83 报告——该件在 S78 面，本席不代改）。
INDEX_BODY = """## 怎么读这套文档

1. 先在上方十板块表里找到你关心的板块；
2. 进板块页看二级功能；
3. 进二级功能页看它拥有的三级入口与代码落点；
4. 规范与开发约束在 [_conventions.md](_conventions.md)，一律以它为准。
"""


def render_board_auto(board: Board, topics: list[str]) -> str:
    node = board.node
    lines = [
        f"## {node['bid']} {node['label']}",
        "",
        f"> {node['tagline']}",
        "",
        "职责：",
        "",
    ]
    for resp in cast("tuple[str, ...]", node.get("responsibilities") or ()):
        lines.append(f"- {resp}")
    lines += [
        "",
        "### 二级功能",
        "",
        "| 二级功能 | 一句话 | 三级入口 |",
        "|---|---|---|",
    ]
    for feature in board.features:
        links = "、".join(
            f"[{x.label}]({feature.slug}/{x.slug}.md)" for x in feature.l3
        ) or "—"
        lines.append(
            f"| [{feature.node['label']}]({feature.slug}/README.md) | {feature.node['summary']} | {links} |"
        )
    return "\n".join(lines)


def render_feature_auto(feature: Feature, topics: list[str]) -> str:
    node = feature.node
    lines = [
        f"## {feature.fid} {node['label']}",
        "",
        f"> {node['summary']}",
        "",
        f"- 归属板块：[{feature.bid}](../README.md)",
        f"- 实现落点：{_paths_md(node.get('impl_paths') or ())}",  # type: ignore[union-attr]
    ]
    kinds = list(node.get("route_kinds") or ())  # type: ignore[union-attr]
    if kinds:
        lines.append(f"- 路由席位：{', '.join(f'`{k}`' for k in kinds)}")
    cap_ids = list(node.get("capability_ids") or ())  # type: ignore[union-attr]
    if cap_ids:
        lines.append("- 能力 id：" + ", ".join(f"`{c}`" for c in cap_ids))
    own_topics = owned_topics(feature, topics)
    if own_topics:
        lines.append(f"- 帮助主题：{', '.join(own_topics)}")
    prefixes = list(node.get("config_prefixes") or ())  # type: ignore[union-attr]
    if prefixes:
        lines.append(f"- 配置键前缀：{', '.join(f'`{p}`' for p in prefixes)}（逐键以目录册为准）")
    lines += [
        "",
        "### 三级入口",
        "",
        "| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |",
        "|---|---|---|---|---|",
    ]
    for x in feature.l3:
        aliases = "、".join(_topics_for(x, own_topics)) or "—"
        lines.append(
            f"| [{x.label}]({x.slug}.md) | {x.route_kind or '—'} | {x.capability_id or '—'} "
            f"| {aliases} | {x.priority if x.priority is not None else '—'} |"
        )
    return "\n".join(lines)


def _topics_for(l3: L3, own_topics: list[str]) -> list[str]:
    label = l3.label
    route_label = str(l3.route_kind or "")
    hits = []
    for topic in own_topics:
        if topic == label or topic.lower() == route_label.lower():
            hits.append(topic)
    return hits


def render_l3_auto(feature: Feature, l3: L3, topics: list[str], route_index: dict) -> str:
    lines = [
        f"## {feature.fid} · {l3.label}",
        "",
        f"- 层级：一级 {feature.bid} → 二级 {feature.slug} → 三级 `{l3.slug}`",
    ]
    if l3.route_kind:
        info = route_index.get(l3.route_kind) or {}
        lines.append(f"- 路由席位：`{l3.route_kind}`（matcher `{info.get('value', '—')}`，command={info.get('command')}）")
        if info.get("priority") is not None:
            lines.append(f"- 判定优先级：{info['priority']}")
    if l3.capability_id:
        lines.append(f"- 能力 id：`{l3.capability_id}`")
    lines.append(f"- 实现落点：{_paths_md(feature.node.get('impl_paths') or ())}")  # type: ignore[union-attr]
    own = owned_topics(feature, topics)
    hits = _topics_for(l3, own)
    if hits:
        lines.append(f"- 帮助主题：{', '.join(hits)}")
    return "\n".join(lines)


def render_root_auto(boards: list[Board], facts: dict[str, int]) -> str:
    lines = [
        "## 十板块",
        "",
        "| 板块 | 名称 | 一句话 | 二级功能 |",
        "|---|---|---|---|",
    ]
    for board in boards:
        feats = "、".join(
            f"[{f.node['label']}]({board.dir_name}/{f.slug}/README.md)" for f in board.features
        )
        lines.append(
            f"| {board.bid} | [{board.node['label']}]({board.dir_name}/README.md) "
            f"| {board.node['tagline']} | {feats} |"
        )
    lines += [
        "",
        "## 派生事实",
        "",
        f"- 板块 / 二级功能 / 三级入口：{facts['boards']} / {facts['features']} / {facts['l3']}",
        f"- 已认领 RouteKind / 帮助主题：{facts['kinds']} / {facts['topics']}",
        "- 权威声明源：`plugins/bot_unified_runtime/domains/core/board_taxonomy.py`",
        "- 规范本体：[_conventions.md](_conventions.md)",
        "- 重算命令：`python scripts/board_doc_sync.py --write`（体检用 `--check`）",
    ]
    return "\n".join(lines)


def _paths_md(paths) -> str:
    out = []
    for p in paths or ():
        out.append(f"`{p}`")
    return "、".join(out) if out else "—"


# --------------------------------------------------------------------------
# 落盘
# --------------------------------------------------------------------------
def _write_page(path: Path, title: str, auto: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_page(title, auto, body), encoding="utf-8", newline="\n")


def _merge(path: Path, title: str, auto: str, skeleton_body: str) -> None:
    """就地更新 AUTO 段；文件不存在则用骨架正文新建（正文块由人后续填）。"""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if AUTO_BEGIN in text and AUTO_END in text:
            head, rest = text.split(AUTO_BEGIN, 1)
            _, tail = rest.split(AUTO_END, 1)
            new = f"{head}{AUTO_BEGIN}\n{AUTO_NOTE}\n\n{auto.rstrip()}\n{AUTO_END}{tail}"
            if new != text:
                path.write_text(new, encoding="utf-8", newline="\n")
            return
        # 无标记的老文件：前插 AUTO 段，不丢内容
        path.write_text(f"# {title}\n\n{AUTO_BEGIN}\n{AUTO_NOTE}\n\n{auto.rstrip()}\n{AUTO_END}\n\n{text.lstrip()}", encoding="utf-8", newline="\n")
        return
    _write_page(path, title, auto, skeleton_body)


_SKELETONS = {L1_BODY.strip(), L2_BODY.strip(), L3_BODY.strip()}


def prune_stale(live: set[Path]) -> list[Path]:
    """删除板块树不再认领、且正文仍是未动骨架的生成页（有人写过的保留并报告）。"""
    kept: list[Path] = []
    for path in sorted(BOARDS_DIR.rglob("*.md")):
        if path in live or "_meta" in path.parts or path.name == "_conventions.md":
            continue
        text = path.read_text(encoding="utf-8")
        if AUTO_END not in text or text.split(AUTO_END, 1)[1].strip() not in _SKELETONS:
            kept.append(path)
            continue
        path.unlink()
    return kept


def live_page_paths(boards: list[Board]) -> set[Path]:
    live = {BOARDS_DIR / "README.md"}
    for board in boards:
        bdir = BOARDS_DIR / board.dir_name
        live.add(bdir / "README.md")
        for feature in board.features:
            fdir = bdir / feature.slug
            live.add(fdir / "README.md")
            live.update(fdir / f"{l3.slug}.md" for l3 in feature.l3)
    return live


def write_tree(boards: list[Board], topics: list[str], route_index: dict, facts: dict[str, int]) -> None:
    pruned_kept = prune_stale(live_page_paths(boards))
    for path in pruned_kept:
        print(f"KEEP 正文已有人写、板块树不再认领，请手工归档：{path.relative_to(ROOT)}", file=sys.stderr)
    _write_page(
        BOARDS_DIR / "README.md",
        "守岸人 Bot · 十板块功能树",
        render_root_auto(boards, facts),
        INDEX_BODY,
    )
    for board in boards:
        bdir = BOARDS_DIR / board.dir_name
        _merge(
            bdir / "README.md",
            f"{board.bid} {board.node['label']}",
            render_board_auto(board, topics),
            L1_BODY,
        )
        for feature in board.features:
            fdir = bdir / feature.slug
            _merge(
                fdir / "README.md",
                f"{feature.fid} {feature.node['label']}",
                render_feature_auto(feature, topics),
                L2_BODY,
            )
            for l3 in feature.l3:
                _merge(
                    fdir / f"{l3.slug}.md",
                    f"{feature.node['label']} · {l3.label}",
                    render_l3_auto(feature, l3, topics, route_index),
                    L3_BODY,
                )


def check_tree(boards: list[Board], topics: list[str], route_index: dict) -> list[str]:
    """生成物漂移检测：AUTO 段与内存渲染结果必须逐字节一致。"""
    drift: list[str] = []
    for board in boards:
        bdir = BOARDS_DIR / board.dir_name
        expect = {
            bdir / "README.md": render_board_auto(board, topics),
        }
        for feature in board.features:
            fdir = bdir / feature.slug
            expect[fdir / "README.md"] = render_feature_auto(feature, topics)
            for l3 in feature.l3:
                expect[fdir / f"{l3.slug}.md"] = render_l3_auto(feature, l3, topics, route_index)
        for path, auto in expect.items():
            if not path.exists():
                drift.append(f"缺失文档：{path.relative_to(ROOT)}")
                continue
            text = path.read_text(encoding="utf-8")
            if AUTO_BEGIN not in text or AUTO_END not in text:
                drift.append(f"缺 AUTO 标记：{path.relative_to(ROOT)}")
                continue
            inner = text.split(AUTO_BEGIN, 1)[1].split(AUTO_END, 1)[0]
            inner = inner.replace(f"{AUTO_NOTE}\n\n", "").strip()
            if inner != auto.strip():
                drift.append(f"生成物漂移：{path.relative_to(ROOT)}")
    live = live_page_paths(boards)
    for path in BOARDS_DIR.rglob("*.md"):
        if path in live or "_meta" in path.parts or path.name == "_conventions.md":
            continue
        drift.append(f"陈旧文档（板块树已不再认领，须移出）：{path.relative_to(ROOT)}")
    return drift


def _facts(boards: list[Board], topics: list[str]) -> dict[str, int]:
    kinds = {k for b in boards for f in b.features for k in (f.node.get("route_kinds") or ())}
    claimed = {t for b in boards for f in b.features for t in (f.node.get("help_topics") or ())}
    return {
        "boards": len(boards),
        "features": sum(len(b.features) for b in boards),
        "l3": sum(len(f.l3) for b in boards for f in b.features),
        "kinds": len(kinds),
        "topics": len(claimed),
        "topics_total": len(topics),
        "route_kinds_total": len(load_route_kind_members()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--dump", action="store_true")
    args = parser.parse_args(argv)

    boards, problems = build_tree()
    topics = load_help_topics()
    route_index = load_route_index()
    facts = _facts(boards, topics)

    if args.dump:
        print(f"facts: {facts}")
        for b in boards:
            print(f"{b.bid} {b.node['label']}")
            for f in b.features:
                print(f"  {f.fid} {f.node['label']} :: " + ", ".join(f"{x.slug}[{x.route_kind or x.capability_id or '-'}]" for x in f.l3))
        for p in problems:
            print(f"PROBLEM {p}")
        return 1 if problems else 0

    if problems:
        for p in problems:
            print(f"PROBLEM {p}", file=sys.stderr)
        print(f"板块树体检未过：{len(problems)} 项", file=sys.stderr)
        return 1

    if args.write:
        write_tree(boards, topics, route_index, facts)
        print(f"已生成 docs/boards/**（{facts['boards']} 板块 / {facts['features']} 功能 / {facts['l3']} 入口）")
        return 0

    drift = check_tree(boards, topics, route_index)
    if drift:
        for d in drift:
            print(f"DRIFT {d}", file=sys.stderr)
        print(f"生成物漂移：{len(drift)} 项（跑 python scripts/board_doc_sync.py --write）", file=sys.stderr)
        return 1
    print(f"board-docs 同步正常（{facts['boards']} 板块 / {facts['features']} 功能 / {facts['l3']} 入口 / 主题 {facts['topics']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
