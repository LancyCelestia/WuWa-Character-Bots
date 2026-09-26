"""S152 · CM-P-43「A 收口」——配置键声明面（六处跨五文件）对唯一在册册的等值账。

真身＝`domains/core/capability_manifest.py::FACETS[*].config_keys`（读侧 `config_keys_for`）。
其余五处声明面凡与本册同 id 者，**键集合**必须逐枚相等；此外四本账各自点名、只准降不准升：

  · `ORDER_DRIFT_ROSTER` —— 集合相等但**序列**不同的 (面, id)；
  · `LITERAL_DEBT_ROSTER` —— 该面源码里仍**自己手写** `config_keys=(字面量)` 的 (面, id)
    （＝尚未降为读册的枚数；A 收口每落一枚摘一行，凭空摘牌＝红）；
  · `NOT_YET_IN_MANIFEST_ROSTER` —— 带着键却还没进册的 id（P2 整表迁移那一半）；
  · `UNATTRIBUTED_LITERAL_KEYS` —— AST 归不出 id 的字面量的**键组合**（尺的盲区必须点名，
    且其键组合不得与任何在册行的键集合重合 ⇒ 藏不住一枚在册枚的手抄）。

`FOLLOWS_MANIFEST` 是"已降为读册"的名册：填一枚必须同时过**替换活性锁**（内存里改册 ⇒
该面重新现算的读数跟着变），所以它填不进嘴——硬抄一份字面全等的副本会被活性锁判否
（`test_poison_hardcoded_copy_does_not_follow_manifest` 就是这发的常驻自证）。

⚠ 与 S130 腿⑨的分工：腿⑨比「册 ⇔ 编排侧描述符」的集合（含零值名册、双向）；本件比
「册 ⇔ **六处全部**」的集合，外加顺序 / 手写字面量 / 装饰位 / 未进册四本账，并管"谁还自己写一份"。
两把尺读同一份真身、判据不重叠。
"""

from __future__ import annotations

import ast
import importlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- 六处声明面（尺身份）
_SURFACE_FILES: dict[str, str] = {
    "route_registry": "plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py",
    "pipeline_managed": "plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py",
    "descriptor": "plugins/bot_unified_runtime/runtime/capability_protocols.py",
    "feature": "plugins/bot_unified_runtime/control_plane/features.py",
    "modality": "plugins/bot_unified_runtime/domains/vision/capabilities/modality_preprocessing.py",
    "creation": "plugins/bot_unified_runtime/domains/creation/__init__.py",
}
ALL_SURFACES = tuple(_SURFACE_FILES)
# 两面一体（同文件的两个数据类），AST 账按文件计。
AST_SURFACES = ("route_registry", "descriptor", "feature", "modality", "creation")
DECORATIVE_SURFACES = ("feature", "creation")  # CM-P-43：③ 全零填充零读取、⑥ 契约占位

# 首届核账＝2026-09-24T07:08:47Z 现算（尺＝本件 `_surface_rows`，另一次独立采集＝探针
# `$TEMP/s152_probe.py` → `s152-before.json`，两份读数一致）。
# S180（2026-09-24T07:46Z 现算，改后）：② 的 5 枚**自身字面量**序漂移格降为读册后天然同序 ⇒ 已摘，
# 剩 4 格（①/② 的 bot.daily_assist + bot.reminder）属 P2（① 整表迁移）地盘。
# S186（2026-09-24T08:21Z 现算，P2 落码后）：① 的 7 枚在册字面量降为 `config_keys_for(id)` ⇒
# route 与 pipeline 两表读册同序，② 的 daily_assist/reminder 经 `_route_execution_rows` 从 route
# 派生随之同序 ⇒ 四格全消，本账现空。**枚数以本账现算为准，勿在叙述里手写。**
ORDER_DRIFT_ROSTER: frozenset[tuple[str, str]] = frozenset()

# 「仍在本面源码里手写一份 config_keys 字面量」且**在册**的 (面, id)。
# 首届核账＝2026-09-24T07:13:40Z 现算（尺＝本件 `_literal_sites`）：①7 枚 + ②13 枚 = 20 枚。
# S180（2026-09-24T07:46Z 现算）：② 的 13 枚降为读册 ⇒ 剩 ① 7 枚。
# S186（2026-09-24T08:21Z 现算，P2 落码后）：① 的 7 枚在册字面量（bot.chat/moegirl/randpic/
# reminder/daily_assist/subscribe/tts）已降为 `config_keys=config_keys_for("<id>")`（5 枚嵌套
# `execution=CapabilityExecution`、2 枚管线管理形 `PipelineManagedExecution`）并逐枚摘牌，
# 键集合逐枚等值（canonical keyset SHA16 前后 `e887f3bb9a3a8b1b` 未变）⇒ 本账现空。
# 剩余手抄字面量仅未进册的 id（见 NOT_YET_IN_MANIFEST_ROSTER），非合流债。枚数以本账现算为准。
LITERAL_DEBT_ROSTER: frozenset[tuple[str, str]] = frozenset()

# 在册外但确实带着键的 id（P2 那一半）。首届核账＝同刻现算：①14 + ①B1 + ②25 + ⑤3 = 43 枚。
NOT_YET_IN_MANIFEST_ROSTER: frozenset[tuple[str, str]] = frozenset({
    ("route_registry", cid)
    for cid in (
        "bot.affinity", "bot.bond", "bot.commodities", "bot.divination", "bot.eat",
        "bot.emergency_info", "bot.epic", "bot.fx", "bot.market", "bot.meme", "bot.news",
        "bot.northbound", "bot.stocks", "bot.weather",
    )
} | {
    ("pipeline_managed", "bot.campus_forward"),
    ("modality", "creation.audio.transcribe"),
    ("modality", "creation.image.upscale"),
    ("modality", "creation.video.understand"),
} | {
    ("descriptor", cid)
    for cid in (
        "bot.affinity", "bot.bond", "bot.campus_forward", "bot.commodities", "bot.divination",
        "bot.eat", "bot.emergency_info", "bot.epic", "bot.fx", "bot.market", "bot.meme",
        "bot.news", "bot.northbound", "bot.stocks", "bot.weather",
        "files.artifact.generate", "files.read.code", "files.read.excel", "files.read.latex",
        "files.read.markdown", "files.read.pdf", "files.read.ppt", "files.read.word",
        "search.acg", "search.unified",
    )
})

# AST 归不出 id 的字面量键组合（尺盲区点名）。首届核账＝同刻现算：② 的 `_files_descriptors()`
# 用形参承载 capability_id ⇒ 归不到 id，两枚各一组键。
# **负样本约束**：这些键组合不得与任何在册行的键集合相等 ⇒ 盲区里藏不下一枚在册枚的手抄。
UNATTRIBUTED_LITERAL_KEYS: frozenset[frozenset[str]] = frozenset({
    frozenset({"bot_file_read_max_chars"}),
})

#: 「已降为读册」的名册（源码里以 `config_keys=config_keys_for("<id>")` 形态读册的 id）。
#: 首届核账（S152）＝空。S180（2026-09-24T07:46Z 现算）落 §3-P1 后填入 ② 的 13 枚在册描述符。
#: S186（2026-09-24T08:21Z 现算）落 P2 后再填 ① 的 7 枚在册字面量（bot.chat/daily_assist/moegirl/
#: randpic/reminder/subscribe/tts）⇒ 现共 20 枚。
#: `descriptor` 面有注册副作用、非 `RELOAD_SAFE_SURFACES` ⇒ 其活性只由源码形态证据
#: `_read_from_manifest_calls` 认账、不做 reload 替换活性验证（reload 支只对 route_registry/pipeline_managed，
#: 而二者同文件 ⇒ S186 起 `config_keys_for` 的管线管理形枚 bot.chat/bot.subscribe 经 sibling 账核活性）。
FOLLOWS_MANIFEST: frozenset[str] = frozenset({
    "bot.chat",
    "bot.daily_assist",
    "bot.moegirl",
    "bot.randpic",
    "bot.reminder",
    "bot.subscribe",
    "bot.tts",
    "creation.image.generate",
    "creation.tts.synthesize",
    "media.asr.audio_file",
    "media.asr.speech",
    "media.tts.autodub",
    "media.tts.autodub_transform",
    "media.video.frame_extract",
    "media.video.recognize",
    "media.video.subtitle",
    "media.vision.anime_ip",
    "media.vision.image",
    "media.vision.ocr",
    "search.web",
})

#: 允许用「改册 + reload」做真·活性验证的面（纯数据、无包内 import ⇒ reload 安全）。
#: `descriptor` 有注册副作用，未列入＝那一面的活性验证仍走源码形态证据 + 合成判据。
RELOAD_SAFE_SURFACES: tuple[str, ...] = ("route_registry", "pipeline_managed")

_SENTINEL = ("s152-sentinel-key",)


# ---------------------------------------------------------------- 取数口（全只读现算）
def manifest_keys() -> dict[str, tuple[str, ...]]:
    from plugins.bot_unified_runtime.domains.core import capability_manifest as cm

    return {str(cid): tuple(row.config_keys) for cid, row in cm.FACETS.items()}


def _surface_rows(surface: str) -> dict[str, tuple[str, ...]]:
    """一面 → {capability_id: 原样 tuple}；该面不含的 id 不出现在返回值里。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as reg,
    )

    if surface == "route_registry":
        return {
            str(d.capability_id): tuple(d.execution.config_keys)
            for d in reg.ROUTE_CAPABILITY_DECLARATIONS
            if d.execution is not None
        }
    if surface == "pipeline_managed":
        return {
            str(d.capability_id): tuple(d.config_keys)
            for d in reg.PIPELINE_MANAGED_CAPABILITY_DECLARATIONS
        }
    if surface == "descriptor":
        from plugins.bot_unified_runtime.runtime import (
            capability_protocols as protocols,
        )

        order: dict[str, list[str]] = {}
        for desc in protocols._ORCHESTRATION_DESCRIPTORS:
            order.setdefault(str(desc.capability_id), []).extend(str(k) for k in desc.config_keys)
        return {cid: tuple(dict.fromkeys(ks)) for cid, ks in order.items()}
    if surface == "feature":
        from plugins.bot_unified_runtime.control_plane import features

        return {str(f.id): tuple(f.config_keys) for f in features.default_feature_descriptors()}
    if surface == "modality":
        from plugins.bot_unified_runtime.domains.vision.capabilities import (
            modality_preprocessing as mp,
        )

        return {str(s.capability_id): tuple(s.config_keys) for s in mp.modality_capability_specs()}
    if surface == "creation":
        from plugins.bot_unified_runtime.domains import creation

        return {str(e.stable_id): tuple(e.config_keys) for e in creation.RESERVED_REGISTRY.entries()}
    raise AssertionError(f"未知声明面 {surface}＝尺自己写错，不是数据问题")


# ---------------------------------------------------------------- AST 尺：谁还自己写一份
def _tree(surface: str) -> ast.Module:
    path = REPO_ROOT / _SURFACE_FILES[surface]
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _parents(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _string_consts(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            out[node.targets[0].id] = node.value.value
    return out


def _owner_id(node: ast.Call, parents: Mapping[ast.AST, ast.AST], consts: Mapping[str, str]) -> str | None:
    """归属哪一枚能力：本调用 → 往上 3 层宿主（① 的 execution 嵌在 RouteCapabilityDecl 里）；
    `capability_id=NAME` 时查模块/函数级字符串常量。"""
    cur: ast.AST = node
    for _ in range(4):
        if isinstance(cur, ast.Call):
            for kw in cur.keywords:
                if kw.arg != "capability_id":
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    return kw.value.value
                if isinstance(kw.value, ast.Name) and kw.value.id in consts:
                    return consts[kw.value.id]
        parent = parents.get(cur)
        if parent is None:
            break
        cur = parent
    return None


def _config_key_kwargs(tree: ast.Module) -> list[tuple[ast.Call, ast.keyword]]:
    out: list[tuple[ast.Call, ast.keyword]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "config_keys":
                    out.append((node, kw))
    return out


def _literal_sites(surface: str) -> list[tuple[str | None, tuple[str, ...]]]:
    """该面源码里逐枚**手写**的字面量 → [(归属 id 或 None, 键)]；含动态元素即不算手写。"""
    tree = _tree(surface)
    consts = _string_consts(tree)
    parents = _parents(tree)
    sites: list[tuple[str | None, tuple[str, ...]]] = []
    for node, kw in _config_key_kwargs(tree):
        value = kw.value
        if not isinstance(value, ast.Tuple) or not value.elts:
            continue
        keys: list[str] = []
        for element in value.elts:
            if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
                keys = []  # 含动态元素（读册/推导）⇒ 不是手写账
                break
            keys.append(element.value)
        if keys:
            sites.append((_owner_id(node, parents, consts), tuple(keys)))
    return sites


def _read_from_manifest_calls(surface: str) -> set[str]:
    """该面里以 `config_keys=config_keys_for("id")` 形态读册的 id（源码证据）。"""
    tree = _tree(surface)
    consts = _string_consts(tree)
    parents = _parents(tree)
    found: set[str] = set()
    for node, kw in _config_key_kwargs(tree):
        value = kw.value
        if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "config_keys_for":
            cid = _owner_id(node, parents, consts)
            if cid:
                found.add(cid)
    return found


# ---------------------------------------------------------------- 判据真身（纯谓词）
def _divergence(
    declared: Mapping[str, tuple[str, ...]],
    rows: Mapping[str, tuple[str, ...]],
) -> dict[str, list[str]]:
    """册 ⇔ 一面，四本互不重叠的账（合一本"mismatch"就分不清多了/少了/只是序不同）。"""
    accounts: dict[str, list[str]] = {"missing": [], "stale": [], "order_only": [], "absent": []}
    for cid, keys in sorted(declared.items()):
        if cid not in rows:
            continue
        got, want = tuple(rows[cid]), tuple(keys)
        if set(got) != set(want):
            accounts["missing"] += [f"{cid}: 面多 {k}" for k in sorted(set(got) - set(want))]
            accounts["stale"] += [f"{cid}: 面缺 {k}" for k in sorted(set(want) - set(got))]
        elif got != want:
            accounts["order_only"].append(cid)
    return accounts


def _assert_surface_non_vacuous(rows: Mapping[str, Any], surface: str) -> None:
    """空面＝尺失明，不许被读成「这一面没差异」。独立成函数，注毒直接打靶。"""
    if not rows:
        raise AssertionError(f"声明面 {surface} 现算零行＝尺失明，不是合流完成")


def _follows_manifest(
    read: Callable[[Mapping[str, tuple[str, ...]]], tuple[str, ...]],
    base: Mapping[str, tuple[str, ...]],
    cid: str,
) -> bool:
    """替换活性：内存里改册 ⇒ 读数必须跟着变（字面全等的硬抄副本判 False）。"""
    if base.get(cid) == _SENTINEL:
        return False
    overlaid = {**base, cid: _SENTINEL}
    try:
        return tuple(read(overlaid)) == _SENTINEL and tuple(read(base)) != _SENTINEL
    except Exception:  # noqa: BLE001 - 抛异常＝不跟动
        return False


def _live_read_follows_surface(surface: str, cid: str) -> bool:
    """真模块活性：内存里把该枚的册值改成哨兵 → reload 该面 → 读数必须变成哨兵。

    只用于 `RELOAD_SAFE_SURFACES`（纯数据面、无包内 import ⇒ reload 不外溢）。
    `finally` 必还原并二次 reload，防污染同会话其他件。

    S186（P2）：`route_registry` 与 `pipeline_managed` 同处一份文件、同一次 reload 生效
    （AST 账按文件计，源码形态判据把两张表的读册都归到 route_registry 面）。故活性检查须覆盖
    **该文件派生的两本运行时账**（ROUTE 执行形 + 管线管理形），否则只在管线管理形表里的在册枚
    （bot.chat/bot.subscribe）会被 route 视图读到空 ⇒ 假红。判据强度只增不减：字面硬抄在两本账里
    都不会随哨兵而动，仍判 False。"""
    from dataclasses import fields

    from plugins.bot_unified_runtime.domains.core import capability_manifest as cm

    if surface not in RELOAD_SAFE_SURFACES or cid not in FOLLOWS_MANIFEST:
        return False
    module_name = _SURFACE_FILES[surface][: -len(".py")].replace("/", ".")
    sibling_surfaces = (
        ("route_registry", "pipeline_managed")
        if surface in ("route_registry", "pipeline_managed")
        else (surface,)
    )
    original = cm.FACETS
    patched = {
        key: (
            type(row)(
                **{
                    **{f.name: getattr(row, f.name) for f in fields(row)},
                    "config_keys": _SENTINEL,
                }
            )
            if key == cid
            else row
        )
        for key, row in original.items()
    }
    try:
        cm.FACETS = patched  # type: ignore[assignment]
        importlib.reload(importlib.import_module(module_name))
        rows = {s: _surface_rows(s) for s in sibling_surfaces}
        return any(_SENTINEL[0] in rows[s].get(cid, ()) for s in sibling_surfaces)
    finally:
        cm.FACETS = original  # type: ignore[assignment]
        importlib.reload(importlib.import_module(module_name))


def _dataclass_fields(row: Any) -> tuple[Any, ...]:
    import dataclasses

    return dataclasses.fields(row)


def _roster_accounts(
    live: set[tuple[str, str]], roster: frozenset[tuple[str, str]]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """名册核对的唯一谓词：`(新增未点名, 消失未跟随)` 两本账，必须都是空。

    抽成函数是为了让注毒能**打同一个靶**——不是另写一遍近似逻辑（那样绿的是夹具）。"""
    return sorted(live - set(roster)), sorted(set(roster) - live)


def _literal_debt_live() -> set[tuple[str, str]]:
    declared = set(manifest_keys())
    return {
        (surface, cid)
        for surface in AST_SURFACES
        for cid, _keys in _literal_sites(surface)
        if cid in declared
    }


# ---------------------------------------------------------------- 常驻腿
def test_six_surfaces_are_locatable_and_non_vacuous() -> None:
    """尺自己在场腿（六面各有行 + 五个源文件源码确有 `config_keys` 字样 + 册非空）。"""
    for surface in ALL_SURFACES:
        _assert_surface_non_vacuous(_surface_rows(surface), surface)
    for surface in AST_SURFACES:
        text = (REPO_ROOT / _SURFACE_FILES[surface]).read_text(encoding="utf-8")
        assert "config_keys" in text, f"{surface} 源码已无 config_keys 字样＝该面已消失，账须改判据"
    assert manifest_keys(), "册现算零行＝尺失明"


def test_key_sets_agree_with_manifest_everywhere() -> None:
    declared = manifest_keys()
    bad: list[str] = []
    for surface in ALL_SURFACES:
        accounts = _divergence(declared, _surface_rows(surface))
        bad += [f"{surface} {line}" for line in accounts["missing"] + accounts["stale"]]
    assert not bad, "配置键六处与本册不等值：\n" + "\n".join(bad)


def test_order_drift_is_exactly_the_named_roster() -> None:
    declared = manifest_keys()
    live = {
        (surface, cid)
        for surface in ALL_SURFACES
        for cid in _divergence(declared, _surface_rows(surface))["order_only"]
    }
    extra, gone = _roster_accounts(live, ORDER_DRIFT_ROSTER)
    assert (extra, gone) == ([], []), (
        f"序漂移账不符｜新增＝{extra}｜消失＝{gone}（改码修好才可摘牌）"
    )


def test_literal_debt_is_exactly_the_named_roster() -> None:
    extra, gone = _roster_accounts(_literal_debt_live(), LITERAL_DEBT_ROSTER)
    assert (extra, gone) == ([], []), (
        f"手写字面量账不符｜新增＝{extra}｜消失＝{gone}（已降为读册就摘牌并登记席位报告）"
    )


def test_unattributed_literals_cannot_hide_a_declared_row() -> None:
    """AST 归不出 id 的字面量必须逐组点名，且不得与任何在册行的键集合重合。"""
    live: set[frozenset[str]] = set()
    for surface in AST_SURFACES:
        for cid, keys in _literal_sites(surface):
            if cid is None:
                live.add(frozenset(keys))
    assert live == set(UNATTRIBUTED_LITERAL_KEYS), (
        f"未归属字面量账不符｜新增＝{sorted(map(sorted, live - set(UNATTRIBUTED_LITERAL_KEYS)))}｜"
        f"消失＝{sorted(map(sorted, set(UNATTRIBUTED_LITERAL_KEYS) - live))}"
    )
    declared_sets = {frozenset(keys) for keys in manifest_keys().values()}
    clash = sorted(map(sorted, live & declared_sets))
    assert not clash, f"盲区里出现与在册行同键组合的手抄（归属尺需修）：{clash}"


def test_decorative_faces_must_not_grow_data() -> None:
    for surface in DECORATIVE_SURFACES:
        filled = {cid: keys for cid, keys in _surface_rows(surface).items() if keys}
        assert not filled, (
            f"{surface} 装饰位长出实数据 {sorted(filled)}：配置键只准由 capability_manifest 供出"
        )
        assert not _literal_sites(surface), f"{surface} 出现手写 config_keys 字面量"


def test_ids_carrying_keys_but_not_yet_in_manifest_are_named() -> None:
    declared = set(manifest_keys())
    live = {
        (surface, cid)
        for surface in ALL_SURFACES
        if surface not in DECORATIVE_SURFACES
        for cid, keys in _surface_rows(surface).items()
        if keys and cid not in declared
    }
    extra, gone = _roster_accounts(live, NOT_YET_IN_MANIFEST_ROSTER)
    assert (extra, gone) == ([], []), f"未进册账不符｜新增＝{extra}｜消失＝{gone}"


def test_projection_roster_cannot_be_claimed_by_mouth() -> None:
    """源码已在读册的 (面,id) 必须逐枚在名册里；在册者还须过真模块替换活性（reload）。"""
    claimed = {(surface, cid) for surface in AST_SURFACES for cid in _read_from_manifest_calls(surface)}
    assert claimed <= {(s, c) for s in AST_SURFACES for c in FOLLOWS_MANIFEST}, (
        f"源码已在读册却未入名册＝账没跟随：{sorted(claimed)}"
    )
    for cid in sorted(FOLLOWS_MANIFEST):
        for surface in AST_SURFACES:
            if cid in _read_from_manifest_calls(surface) and surface in RELOAD_SAFE_SURFACES:
                assert _live_read_follows_surface(surface, cid), f"{surface}:{cid} 自称读册却不跟册动"


# S180（2026-09-24）：`test_zero_convergence_is_reported_honestly` 已删——该腿的**存在性判据**是
# "② 尚未降为读册"（它断言 `_read_from_manifest_calls` 全空 + FOLLOWS 全空）。P1 落地后该前提失效，
# 若留着它，它就成了"把新实况锁回旧叙述"的反向假绿。改由下面两腿共同钉实况：
#   · `test_projection_roster_cannot_be_claimed_by_mouth`（源码读册者必入 FOLLOWS + reload-safe 支活性）；
#   · `test_literal_debt_is_exactly_the_named_roster`（在册手抄枚数逐枚点名；**合流是否完成以该腿的
#     `LITERAL_DEBT_ROSTER` 现算为准，勿在此手写枚数**——S186 落 P2 后① 已全降为读册、该账现空，
#     但③/⑤/⑥ 等未进册面仍在别的名册，整册六处是否全归一不由本注释下结论）。


# ---------------------------------------------------------------- 注毒自证（常驻，合成数据）
def test_poison_extra_key_in_surface_is_missing_not_order() -> None:
    accounts = _divergence({"bot.x": ("a", "b")}, {"bot.x": ("a", "b", "c")})
    assert accounts["missing"] == ["bot.x: 面多 c"] and not accounts["stale"]


def test_poison_key_dropped_from_surface_is_stale() -> None:
    accounts = _divergence({"bot.x": ("a", "b")}, {"bot.x": ("a",)})
    assert accounts["stale"] == ["bot.x: 面缺 b"] and not accounts["missing"]


def test_poison_renamed_key_is_two_accounts_never_order_only() -> None:
    accounts = _divergence({"bot.x": ("a",)}, {"bot.x": ("zzz",)})
    assert accounts["missing"] and accounts["stale"] and not accounts["order_only"]


def test_poison_order_only_is_named_not_silently_equal() -> None:
    accounts = _divergence({"bot.x": ("a", "b")}, {"bot.x": ("b", "a")})
    assert accounts["order_only"] == ["bot.x"] and not accounts["missing"]


def test_poison_hardcoded_copy_does_not_follow_manifest() -> None:
    """**假等值正解**：副本字面全等，但改册不跟动 ⇒ 活性判据判否。"""
    base = {"bot.x": ("a", "b")}
    hardcoded: Callable[[Mapping[str, tuple[str, ...]]], tuple[str, ...]] = lambda _o: ("a", "b")
    genuine = lambda overlay: overlay["bot.x"]
    assert tuple(hardcoded(base)) == tuple(genuine(base)) == base["bot.x"]  # 字面全等
    assert _follows_manifest(hardcoded, base, "bot.x") is False            # 但被判否
    assert _follows_manifest(genuine, base, "bot.x") is True


def test_poison_literal_disguised_as_projection_is_still_counted() -> None:
    """AST 腿的牙：读册形态不记账、字面量必记账；嵌套宿主（① 的真实形状）也要归到 id。"""
    projection = "R(capability_id='bot.x', execution=E(config_keys=config_keys_for('bot.x')))"
    literal = "R(capability_id='bot.x', execution=E(config_keys=('a',)))"

    def sites(src: str) -> list[tuple[str | None, tuple[str, ...]]]:
        tree = ast.parse(src)
        parents = _parents(tree)
        found: list[tuple[str | None, tuple[str, ...]]] = []
        for node, kw in _config_key_kwargs(tree):
            value = kw.value
            if not isinstance(value, ast.Tuple):
                continue
            keys = [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(keys) == len(value.elts) and keys:
                found.append((_owner_id(node, parents, {}), tuple(keys)))
        return found

    assert sites(literal) == [("bot.x", ("a",))]
    assert sites(projection) == []


def test_poison_empty_surface_is_not_read_as_converged() -> None:
    with pytest.raises(AssertionError):
        _assert_surface_non_vacuous({}, "route_registry")


def test_poison_roster_entry_removed_without_fixing_code_is_red() -> None:
    """凭空摘牌（不修码）必红：注毒打的是**同一条腿的谓词** `_roster_accounts`，不是另写近似逻辑。

    P2（S186）落码后真账 `LITERAL_DEBT_ROSTER` 已空——① 的 7 枚在册字面量全降为读册 ⇒ 原
    "从真账 `live` 里摘一枚、码仍手抄"的手法失去活体前提（该枚今天确实已不手抄，`live` 里没有它）。
    为**不删这条自证**（禁删断言），改以合成活体喂同一条谓词：假设某枚仍是手抄（`live` 出现它）而名册
    已把它摘掉（`roster` 空）⇒ `_roster_accounts` 必报 extra＝红。与常驻腿
    `test_literal_debt_is_exactly_the_named_roster` 共用 `_roster_accounts` 靶。"""
    synthetic_live: set[tuple[str, str]] = {("route_registry", "bot.moegirl")}  # 假装这枚仍手抄
    shrunk_roster: frozenset[tuple[str, str]] = frozenset()  # 名册却已摘牌（＝当前真账）
    extra, gone = _roster_accounts(synthetic_live, shrunk_roster)
    assert extra == [("route_registry", "bot.moegirl")] and gone == []
    # 反向自证：真账确已空（P2 落码生效），否则本毒的合成前提就不等价于现状。
    assert _literal_debt_live() == set(), "① 仍有在册手抄字面量＝P2 未落全，本毒前提与真账都要重估"


def test_rosters_are_self_consistent() -> None:
    declared = set(manifest_keys())
    assert {cid for _, cid in ORDER_DRIFT_ROSTER} <= declared
    assert {cid for _, cid in LITERAL_DEBT_ROSTER} <= declared
    assert not ({cid for _, cid in NOT_YET_IN_MANIFEST_ROSTER} & declared)
    surfaces = set(ALL_SURFACES)
    assert {s for s, _ in ORDER_DRIFT_ROSTER | LITERAL_DEBT_ROSTER | NOT_YET_IN_MANIFEST_ROSTER} <= surfaces
