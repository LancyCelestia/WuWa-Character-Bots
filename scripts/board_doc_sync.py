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
- **写盘口（TX241 L1）＝`_commit_rendered` 一支**：现读＋完整性凭据 → 从**刚读到的那份盘上态**
  派生目标全文 → 写前再读比对凭据（不等 ⇒ 弃写、用它重跑，至多 `dts._CAS_ATTEMPTS` 次）→
  临时名 + `os.replace` 原子落盘 → 读回核对 → 必要时**条件回滚**（先重读，盘上已是他人提交
  ⇒ 只放弃、不把别人抬回去）。三件套真身住 `doc_template_sync`（凭据再往下唯一住
  `shim_retirement_census._integrity_token`），本件零自造尺。旧形两条腿都没守卫：
  `_write_page` 零重读直写整页、`_merge` 有重读但无等值门/读回/回滚且非原子。
  残余窗口（不写＝按未修记账）：CAS 仍是 check-then-act，「最后一次 `read_bytes` →
  `os.replace`」两发系统调用之间的竞写拦不住；且 AUTO 段本体来自更早的全树计算（投影器固有
  形状）。两者都要 L2「所有页面写者同一把持仓锁」才归零，本波不自装（见 `SEAT-TX241.md` §5）。

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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:  # 与 physical_placement_census 同形：同目录兄弟脚本直取
    sys.path.insert(0, str(ROOT / "scripts"))

import doc_sync as ds  # 塌陷锁唯一真身（`require_surface`）——本件不自造第二把「读空即抛」的尺
import doc_template_sync as dts  # 页面写口三件套唯一真身（CAS 凭据／原子写／条件回滚），禁第二把尺

BOARDS_DIR = ROOT / "docs" / "boards"
TAXONOMY_PY = ROOT / "plugins/bot_unified_runtime/domains/core/board_taxonomy.py"
KEYSTONE_PY = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py"
ROUTER_PY = ROOT / "plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py"
CONFIG_PY = ROOT / "plugins/bot_unified_runtime/config.py"

AUTO_BEGIN = "<!-- BOARD-AUTO:BEGIN -->"
AUTO_END = "<!-- BOARD-AUTO:END -->"
AUTO_NOTE = "<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->"


class BoardPageConflict(RuntimeError):
    """一页投影在**落盘前**被现读判据否决（TX241 L1）：CAS 重跑耗尽、或盘上态读不到。

    立这枚异常是为了堵「静默跳过」：旧版 `_write_page` 零重读直写、`_merge` 无等值门，
    并发下要么吃掉他席正文、要么把漂移留在盘上而 `--write` 仍报成功。现在冲突必须点名，
    `write_tree` 逐页收集、`main` 计入退出码——**不把红搬进「这页怎么没更新」那本账**
    （变绿六禁第⑥条，TX226 §4.2 L2 同口径）。
    """


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
    """板块树：[{board…}, …]，每个 board 带 features 列表。

    S246R 塌陷锁：读空一律抛（复用 `doc_sync.require_surface`，禁第二把尺）。
    旧形返回 `[]` 时，`build_tree`/`live_page_paths` 得到空 live 集，`prune_stale` 会按
    「板块树不再认领」去**删页**——声明源降成再导出壳这种"眼睛瞎了"的形态，
    在旧写法下表现为「生成页被静默清空」，而不是「读不到」。
    """
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
    return ds.require_surface("板块树取数口 load_taxonomy", boards, TAXONOMY_PY, ("BOARD_TAXONOMY",))


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
    return ds.require_surface(
        "路由索引取数口 load_route_index", index, KEYSTONE_PY, ("ROUTE_CAPABILITY_DECLARATIONS",))


def load_route_kind_members() -> list[str]:
    text = ROUTER_PY.read_text(encoding="utf-8")
    body = text.split("class RouteKind(", 1)
    if len(body) < 2:
        return ds.require_surface(
            "RouteKind 成员取数口 load_route_kind_members", [], ROUTER_PY, ("RouteKind",))
    seg = body[1].split("\n\n\n", 1)[0]
    return ds.require_surface(
        "RouteKind 成员取数口 load_route_kind_members",
        re.findall(r"^\s{4}([A-Z][A-Z0-9_]*)\s*=", seg, re.MULTILINE),
        ROUTER_PY,
        ("RouteKind",),
    )


def load_help_topics() -> list[str]:
    tree = ast.parse(KEYSTONE_PY.read_text(encoding="utf-8"))
    return ds.require_surface(
        "帮助主题取数口 load_help_topics",
        [
            str(c.get("topic", ""))
            for c in _collect_calls(tree, {"HelpTopicDecl"})
            if c.get("topic")
        ],
        KEYSTONE_PY,
        ("HELP_TOPIC_DECLARATIONS",),
    )


def load_config_fields() -> list[str]:
    text = CONFIG_PY.read_text(encoding="utf-8")
    return ds.require_surface(
        "配置字段取数口 load_config_fields",
        sorted(set(re.findall(r"^\s{4}(bot_[a-z0-9_]+)\s*[:=]", text, re.MULTILINE))),
        CONFIG_PY,
        ("class Config",),
    )


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
def _commit_rendered(path: Path, render: Callable[[str | None], str]) -> str:
    """本页唯一写盘序列（TX241 L1·第三写口）。

    旧形两枚都缺守卫：`_write_page` **零重读直写整页**（形 ① 的最大窗口——投影输入全来自
    更早的全树计算，盘上被人改过也照样整页顶掉），`_merge` 虽有重读却**无等值门、无读回、
    无回滚、非原子**（`write_text` 是 truncate+write）。现在统一成一支：

    1. `read_bytes`（不存在 ⇒ None）＋完整性凭据；
    2. `render(current_text)` 派生目标全文——**只从刚读到的那份盘上态派生**（人正文段取自
       这一发现读，绝不用更早的内存副本）；
    3. 目标文本 == 盘上文本 ⇒ 幂等命中，零写入返回 `unchanged`；
    4. 写前 CAS：再读一次、凭据与第 1 步比对，不等 ⇒ 弃写（临时名都不落）并用新读到的那份
       重跑 2–4，至多 `dts._CAS_ATTEMPTS` 次；仍未决 ⇒ `cas-conflict`（盘上留他席那份）；
    5. 相等才 `_atomic_write_bytes`（临时名 + `os.replace`）→ 读回核对 → 不等则
       `_rollback_or_abandon`（先重读，盘上已是他人提交 ⇒ 只放弃不回滚）。

    三件套真身全在 `doc_template_sync`（其凭据又唯一住 `shim_retirement_census._integrity_token`），
    本件**不自造尺**。残余窗口（不写＝按未修记账）：第 4 步 `read_bytes → os.replace` 之间仍是
    check-then-act ⇒ ①型丢更新概率极低但不为零；且第 2 步的 AUTO 段来自更早的全树计算（本投影器
    的固有形状，非本席引入），要归零只有 L2「所有页面写者同一把持仓锁」——本波不自装。

    返回 `written` / `unchanged` / `cas-conflict` / `unreadable`（调用方点名，绝不静默）。
    """
    for _attempt in range(1, dts._CAS_ATTEMPTS + 1):
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = None  # 新建页：本轮起点凭据取空字节（与「盘上什么都没有」同义）
        except OSError as exc:
            return f"unreadable（写前重读失败 {type(exc).__name__}: {exc}）"
        current = None if raw is None else dts._decode_universal_newlines(raw)
        token = dts._integrity_token_of(b"" if raw is None else raw)
        rendered = render(current)
        if current is not None and rendered == current:
            return "unchanged"  # 幂等命中：盘上已是目标文本，本轮零写入
        try:
            check = path.read_bytes()
        except FileNotFoundError:
            check = b""
        except OSError as exc:
            return f"unreadable（写前 CAS 重读失败 {type(exc).__name__}: {exc}）"
        if dts._integrity_token_of(check) != token:
            continue  # 弃写：他席在渲染期间提交过 ⇒ 用它那份重跑
        payload = rendered.encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        dts._atomic_write_bytes(path, payload)
        if path.read_bytes() != payload:
            # 读回不等 ⇒ 窗口内被竞写。有写前态才谈得上回滚（且仍先重读、只在盘上仍是本席
            # 写值时才抬回）；新建页无写前态可回，**不删**——别人可能刚在这条路径上落了东西。
            if raw is None:
                return "cas-conflict（写后读回≠本席落盘字节；新建页无写前态可回滚，保留盘上现值）"
            preserved = dts._rollback_or_abandon(path, raw, payload)
            return f"cas-conflict（写后读回≠本席落盘字节；{preserved}）"
        return "written"
    return f"cas-conflict（重跑 {dts._CAS_ATTEMPTS} 次仍有他席抢先落盘，本席陈旧投影不落地）"


def _rel_for_msg(path: Path) -> str:
    """点名用路径：仓内给相对形、仓外（`%TEMP%` 合成根、离线夹具）给原形。

    不是装饰：`write_tree` 与常驻门都在仓内跑，而 TX241 的并发用例在 `tmp_path` 合成根上跑——
    直接 `path.relative_to(ROOT)` 在仓外会抛 `ValueError`，把"拒写点名"变成"崩在点名那一行"。
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _write_page(path: Path, title: str, auto: str, body: str) -> None:
    """整页新建/重写（板块索引页那一发）。TX241：零重读直写已升为上面的 CAS 提交。"""

    def _render(_current: str | None) -> str:
        return _page(title, auto, body)

    outcome = _commit_rendered(path, _render)
    if outcome not in ("written", "unchanged"):
        raise BoardPageConflict(f"{_rel_for_msg(path)}：{outcome}")


def _merge(path: Path, title: str, auto: str, skeleton_body: str) -> None:
    """就地更新 AUTO 段；文件不存在则用骨架正文新建（正文块由人后续填）。

    TX241：目标文本的 head/tail 一律取自**本轮现读**的那份盘上态（旧版这一点已对，缺的是
    等值门/读回/原子写/条件回滚），并由 `_commit_rendered` 在写前重读比对凭据——人在标记外
    写的正文因此不会再被并发的一发投影吃掉。
    """

    def _render(current: str | None) -> str:
        if current is None:
            return _page(title, auto, skeleton_body)
        if AUTO_BEGIN in current and AUTO_END in current:
            head, rest = current.split(AUTO_BEGIN, 1)
            _, tail = rest.split(AUTO_END, 1)
            return f"{head}{AUTO_BEGIN}\n{AUTO_NOTE}\n\n{auto.rstrip()}\n{AUTO_END}{tail}"
        # 无标记的老文件：前插 AUTO 段，不丢内容
        return (
            f"# {title}\n\n{AUTO_BEGIN}\n{AUTO_NOTE}\n\n{auto.rstrip()}\n{AUTO_END}\n\n"
            f"{current.lstrip()}"
        )

    outcome = _commit_rendered(path, _render)
    if outcome not in ("written", "unchanged"):
        raise BoardPageConflict(f"{_rel_for_msg(path)}：{outcome}")


_SKELETONS = {L1_BODY.strip(), L2_BODY.strip(), L3_BODY.strip()}


def prune_stale(live: set[Path]) -> list[Path]:
    """删除板块树不再认领、且正文仍是未动骨架的生成页（有人写过的保留并报告）。

    TX261 ①④（9 枚名册里的 D1）：旧形是「读 → 判 → 删」三步裸走、删前不复查——判据成立与
    `unlink` 之间他席刚写入正文的页会被**静默删掉**（删件即半截契约，TX242 §3 点名洞）。
    现在：判据从**同一份现读字节**派生（decode 失败＝看不懂 ⇒ 保守保留），`unlink` 前再读一次、
    字节与判据所凭那份**逐字等值**才许删；不等（窗口内被人动过）⇒ 并入保留名册并 stderr 点名。
    残余窗口如实：重读到 unlink 之间仍有无锁微秒缝（L2 不自装，同 `doc_template_sync.write_page`
    诚实边界口径）；本腿买到的是「绝不删我看不懂或判据已过时的页」，不是「零竞态删除」。
    """
    kept: list[Path] = []
    for path in sorted(BOARDS_DIR.rglob("*.md")):
        if path in live or "_meta" in path.parts or path.name == "_conventions.md":
            continue
        try:
            raw = path.read_bytes()
            text = dts._decode_universal_newlines(raw)
        except (OSError, UnicodeDecodeError):
            kept.append(path)  # 读不懂/读不动的件一律不删（fail-closed）
            continue
        if AUTO_END not in text or text.split(AUTO_END, 1)[1].strip() not in _SKELETONS:
            kept.append(path)
            continue
        try:
            if path.read_bytes() != raw:  # 删前复查：判据与字节不同源的一刻绝不落刀
                kept.append(path)
                print(f"KEEP 判据后字节已变（窗口内他席写过）、不删：{path.relative_to(ROOT)}",
                      file=sys.stderr)
                continue
            path.unlink(missing_ok=True)
        except OSError as exc:
            kept.append(path)
            print(f"KEEP 删除腿异常（{type(exc).__name__}: {exc}）、保留待人工：{path}", file=sys.stderr)
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


def write_tree(
    boards: list[Board], topics: list[str], route_index: dict, facts: dict[str, int]
) -> list[str]:
    """投影整棵板块树，返回**逐页冲突点名**（空表＝本轮每一页都落成了）。

    TX241：旧版返回 `None`、写口零守卫 ⇒ 「跑成功」与「盘上是不是我这一份」两件事被混成一件。
    现在冲突逐页收进返回值、由 `main` 计入退出码——投影器仍**不**自动重试整棵树（那只会把
    同一份陈旧全树计算再压一遍），单页级的重跑已在 `_commit_rendered` 里做过。
    """
    conflicts: list[str] = []

    def _emit(path: Path, title: str, auto: str, body: str, *, merge: bool) -> None:
        try:
            if merge:
                _merge(path, title, auto, body)
            else:
                _write_page(path, title, auto, body)
        except BoardPageConflict as exc:
            conflicts.append(str(exc))

    pruned_kept = prune_stale(live_page_paths(boards))
    for path in pruned_kept:
        print(f"KEEP 正文已有人写、板块树不再认领，请手工归档：{path.relative_to(ROOT)}", file=sys.stderr)
    _emit(
        BOARDS_DIR / "README.md",
        "守岸人 Bot · 十板块功能树",
        render_root_auto(boards, facts),
        INDEX_BODY,
        merge=False,
    )
    for board in boards:
        bdir = BOARDS_DIR / board.dir_name
        _emit(
            bdir / "README.md",
            f"{board.bid} {board.node['label']}",
            render_board_auto(board, topics),
            L1_BODY,
            merge=True,
        )
        for feature in board.features:
            fdir = bdir / feature.slug
            _emit(
                fdir / "README.md",
                f"{feature.fid} {feature.node['label']}",
                render_feature_auto(feature, topics),
                L2_BODY,
                merge=True,
            )
            for l3 in feature.l3:
                _emit(
                    fdir / f"{l3.slug}.md",
                    f"{feature.node['label']} · {l3.label}",
                    render_l3_auto(feature, l3, topics, route_index),
                    L3_BODY,
                    merge=True,
                )
    return conflicts


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

    if args.write:
        # TX-S779：`--write` 的写盘不得被体检早退吃掉。
        # 旧形 `if problems: return 1` 排在 `if args.write:` **之前** ⇒ 体检只要有一项在案
        # （今日实拦：他波两枚未登记项 `RouteKind HOST_STATE`／帮助主题「宿主机状态」），
        # `--write` 就与 `--check` 一样在门口返回——`write_tree` 实到调用 0 次、生成物一个
        # 字节都不跟随，而板面看起来"跑过了"（S770 只读桩证死，`REGEN-RUNBOOK-POST-D5-S770.md`
        # §〇/E1）。这里先投影落盘，再照旧把体检问题如实报出来、退出码仍反映问题与冲突；
        # `--check` 侧的早退语义原样保留在下方——门只准变严，不许为凑绿放宽判据。
        conflicts = write_tree(boards, topics, route_index, facts)
        for line in conflicts:
            print(f"BOARD_PAGE_CONFLICT 本页投影被落盘前判据否决、盘上态归他席：{line}",
                  file=sys.stderr)
        print(
            f"已生成 docs/boards/**（{facts['boards']} 板块 / {facts['features']} 功能 / "
            f"{facts['l3']} 入口；冲突 {len(conflicts)} 页）"
        )
        if problems:
            for p in problems:
                print(f"PROBLEM {p}", file=sys.stderr)
            print(
                f"板块树体检未过：{len(problems)} 项"
                "（--write 已按当前声明源投影落盘，体检问题仍须由 owner 同批处理）",
                file=sys.stderr,
            )
        return 1 if (problems or conflicts) else 0

    # 缺省与 --check：体检未过仍旧早退（互斥组保证与 --write 不同屏）；语义一字未动。
    if problems:
        for p in problems:
            print(f"PROBLEM {p}", file=sys.stderr)
        print(f"板块树体检未过：{len(problems)} 项", file=sys.stderr)
        return 1

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
