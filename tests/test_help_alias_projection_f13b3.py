"""F-13 乙案批 3（2026-10-07）：帮助册「别名列＋镜像簇」与 yes/no 布尔字集收进单一真身。

批 2 收的是 `_HELP_ENTRY_META[*].triggers_nickname`（昵称列）。批 3 接着收三族：

**甲**：同一 topic 在 `_HELP_ENTRIES[*].aliases` 与 `_HELP_ENTRY_META[*].triggers_nickname`
  两处**逐字同集**地再抄一遍 `DEFAULT_VERB_MAP` 动词（S53 尺里 `_ECHO_MIRROR_CLUSTER` 那族
  在册镜像）——七簇（功能管理/记忆/为什么/配置/就绪/角色/人格）两列一起转述真身，外加决策一枚。
**乙**：帮助册 `aliases`/`triggers_nickname` 抄的是**能力自己的** `DEFAULT_TRIGGER_WORDS`
  （宿主机状态/媒体归档）——在能力件内加一条纯投影口（禁新建生产件），帮助侧只转述。
**丙**：`control_plane/__init__.py` 把布尔字集手打到第三遍 → 改引
  `domains/core/config/config_readiness.py::ENV_TRUE_WORDS/ENV_FALSE_WORDS`（批 1 落位的中央真身）。

判据（逐条有牙）：
① 形态锁：这些列的值节点必须是 `ast.Call` 指向在册投影口，不许是字符串元组字面量（AST 级，不吃行号）。
② **三本名册同批迁**（本批命门——只迁生产不迁名册＝把尺改瞎，不是把债修掉）：S53
   `INTENTIONAL_UNITS`（丙的 yes/no 署名位）、S33 `HOME_MIRROR_NOT_DEBT`（甲乙的在册镜像行）
   都必须无虚设；现算 stale 非空即红。
③ 债真降：`accounted_debt()` 逐字等于 `WORD_SITE_CEILING`，上限低于批 2 的 447；
   `AUDIT_HISTORY` 前缀逐字不动；四枚扫描面地板（1100/700/140/100）一枚不许下调。
④ 行为零变化：批前手抄词面＝本文件冻结快照（单串存放——容器形态会被 S33 ruleB 认作 tests 侧副本），
   断言 (a) 投影输出与快照**逐枚有序全等**（`aliases` 进 `docs/command-catalog.md`，顺序＝可见内容）、
   (b) `/bot help <词>` 落点不变、(c) 「守岸人<词>」经 `CommandAliasResolver` 解到的 capability 不变、
   (d) 静态 AST 取数口与运行时 import 取数口逐枚全等。
⑤ 注毒自证：把任一簇退回手抄（虚拟件喂 S53 同一取数口，绝不写盘）⇒ 计账必超新上限。

禁新建生产 .py（用户 2026-10-06 对批 1 越界的裁定延续）。全离线、只读、不写盘、不碰 git 写操作。
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any, Final

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ECHO_REL: Final[str] = "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py"
ALIASES_REL: Final[str] = "plugins/bot_unified_runtime/domains/chat_reply/runtime/aliases.py"
HOST_STATE_REL: Final[str] = "plugins/bot_unified_runtime/domains/ops/capabilities/host_state.py"
MEDIA_ARCHIVE_REL: Final[str] = "plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py"
CONTROL_PLANE_REL: Final[str] = "plugins/bot_unified_runtime/control_plane/__init__.py"
CONFIG_READINESS_REL: Final[str] = "plugins/bot_unified_runtime/domains/core/config/config_readiness.py"
S53_FILE: Final[str] = "tests/test_trigger_word_single_source.py"
S33_FILE: Final[str] = "tests/test_trigger_word_copy_ratchet.py"

#: 批 2 终账（2026-10-07，raw 522／计账 447）——本批对照基线，只做方向断言。
PRE_BATCH_CEILING: Final[int] = 447
PRE_BATCH_RAW: Final[int] = 522
PRE_BATCH_OFFSET: Final[int] = 75
#: 四枚扫描面地板的批 2 现值（降地板＝改瞎尺，不算修债）。
PRE_BATCH_FLOORS: Final[tuple[int, int, int, int]] = (1100, 700, 140, 100)

VERB_PROJECTION: Final[str] = "nickname_verbs_for"
HOST_PROJECTION: Final[str] = "host_state_trigger_words"
MEDIA_PROJECTION: Final[str] = "media_archive_trigger_words"

#: 甲族：(topic, capability, 批前手抄词面单串)——在册镜像簇，两列逐枚同串。
MIRROR_TOPICS: Final[tuple[tuple[str, str, str], ...]] = (
    ("记忆", "bot.memory", "记忆、memory"),
    ("为什么", "bot.why", "为什么、为啥、why"),
    ("配置", "bot.config", "配置、config"),
    ("就绪", "bot.readiness", "就绪、readiness"),
    ("角色", "bot.roles", "角色、roles"),
    ("人格", "bot.persona", "人格、persona"),
)
#: 逐列收编清单 (topic, 字段, 投影口, 参数, 批前手抄词面单串)——凭据＝改动前现算逐枚存证。
#: 功能管理只有 aliases 列（META 无昵称列）；决策只有昵称列（aliases 多一枚「决策引擎」，
#: 与动词表不同集，故本批不折它）；媒体归档只有 aliases 列（昵称列是 6 词子集，投影不出来）。
CONVERTED_COLUMNS: Final[tuple[tuple[str, str, str, str, str], ...]] = (
    ("功能管理", "aliases", VERB_PROJECTION, "bot.runtime", "功能管理、feature"),
    *[(t, "aliases", VERB_PROJECTION, c, s) for t, c, s in MIRROR_TOPICS],
    *[(t, "triggers_nickname", VERB_PROJECTION, c, s) for t, c, s in MIRROR_TOPICS],
    ("决策", "triggers_nickname", VERB_PROJECTION, "bot.decision", "决策、decision"),
    ("宿主机状态", "aliases", HOST_PROJECTION, "",
     "宿主机状态、机器状态、机器配置、宿主状态、宿主機狀態、機器狀態、hoststate、jiqizhuangtai、jizhuangtai、jiqipeizhi"),
    ("宿主机状态", "triggers_nickname", HOST_PROJECTION, "",
     "宿主机状态、机器状态、机器配置、宿主状态、宿主機狀態、機器狀態、hoststate、jiqizhuangtai、jizhuangtai、jiqipeizhi"),
    ("媒体归档", "aliases", MEDIA_PROJECTION, "",
     "收藏、归档、存图、收图、存聊天记录、存记录、archive、shoucang、guidang"),
)
#: 乙族（能力侧真身）——昵称列/别名列都转述同一枚 `DEFAULT_TRIGGER_WORDS`。
CAPABILITY_TOPICS: Final[tuple[tuple[str, str, str], ...]] = (
    ("宿主机状态", HOST_PROJECTION,
     "宿主机状态、机器状态、机器配置、宿主状态、宿主機狀態、機器狀態、hoststate、jiqizhuangtai、jizhuangtai、jiqipeizhi"),
    ("媒体归档", MEDIA_PROJECTION, "收藏、归档、存图、收图、存聊天记录、存记录、archive、shoucang、guidang"),
)
#: 「守岸人<词>」的改动前解析读数（现算存证）：动词表能力→该 id；能力自带触发词→None（不走动词册）。
VERB_MAP_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {arg for _t, _f, _fn, arg, _s in CONVERTED_COLUMNS if arg}
)
#: 丙族：布尔字集（批 1 把中央真身落进 config_readiness；本批折调用侧手打位之一）。
BOOL_TRUE_SNAPSHOT: Final[str] = "1、true、on、yes"
BOOL_FALSE_SNAPSHOT: Final[str] = "0、false、off、no"


def _load_by_path(name: str, rel: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def s53() -> Any:
    return _load_by_path("__f13b3_s53__", S53_FILE)


@pytest.fixture(scope="module")
def s33() -> Any:
    return _load_by_path("__f13b3_s33__", S33_FILE)


def _words(single: str) -> list[str]:
    return [item for item in single.split("、") if item]


def _tree(rel: str) -> ast.Module:
    return ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _assign_value(tree: ast.Module, name: str) -> ast.expr:
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            value = getattr(node, "value", None)
            assert value is not None, f"{name} 没有值节点"
            return value
    raise AssertionError(f"模块级定义 {name} 不在了")


def _meta_fields(tree: ast.Module) -> dict[str, dict[str, ast.expr]]:
    value = _assign_value(tree, "_HELP_ENTRY_META")
    assert isinstance(value, ast.Dict), "_HELP_ENTRY_META 定义形态变了（不是 dict 字面量）"
    return {
        key.value: {
            k.value: v
            for k, v in zip(entry.keys, entry.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        for key, entry in zip(value.keys, value.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(entry, ast.Dict)
    }


def _detail_aliases(tree: ast.Module) -> dict[str, ast.expr]:
    """`_HELP_ENTRIES`（list[dict]）里 topic → aliases 值节点。"""
    value = _assign_value(tree, "_HELP_ENTRIES")
    assert isinstance(value, ast.List), "_HELP_ENTRIES 定义形态变了（不是 list 字面量）"
    out: dict[str, ast.expr] = {}
    for item in value.elts:
        if not isinstance(item, ast.Dict):
            continue
        fields = {
            k.value: v
            for k, v in zip(item.keys, item.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        topic = fields.get("topic")
        if isinstance(topic, ast.Constant) and isinstance(topic.value, str) and "aliases" in fields:
            out[topic.value] = fields["aliases"]
    return out


def _call_name(node: ast.expr) -> str:
    return node.func.id if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) else ""


# ---------------------------------------------------------------------------
# ① 形态：这些列从此只转述、不手打
# ---------------------------------------------------------------------------


def test_alias_and_nickname_columns_are_projections() -> None:
    tree = _tree(ECHO_REL)
    meta = _meta_fields(tree)
    aliases = _detail_aliases(tree)
    bad: list[str] = []
    for topic, field, func, arg, _snap in CONVERTED_COLUMNS:
        node = aliases.get(topic) if field == "aliases" else meta.get(topic, {}).get(field)
        assert node is not None, f"{topic}.{field} 列不见了（取数口坏了，不是收编成功）"
        if _call_name(node) != func:
            bad.append(f"{topic}.{field}={_call_name(node) or type(node).__name__}")
            continue
        if arg:
            first = node.args[0] if node.args else None
            assert isinstance(first, ast.Constant) and first.value == arg, (
                f"{topic}.{field} 的投影参数不是 {arg}"
            )
        else:
            assert not node.args, f"{topic}.{field}：能力侧投影口不该吃参数"
    assert not bad, f"仍在手打词面的帮助册列：{bad}"


def test_projections_are_registered_in_the_catalog_channel() -> None:
    from scripts.command_catalog import HELP_LITERAL_PROJECTIONS

    for _t, _f, func, _a, _s in CONVERTED_COLUMNS:
        assert func in HELP_LITERAL_PROJECTIONS, f"{func} 未在册＝静态取数口看不见这一列"


@pytest.mark.parametrize(
    ("rel", "func"),
    [(HOST_STATE_REL, HOST_PROJECTION), (MEDIA_ARCHIVE_REL, MEDIA_PROJECTION)],
)
def test_capability_projection_household_is_existing_and_wordless(rel: str, func: str) -> None:
    """投影口住在**已存在**的能力件里，且函数体内零词面字面量（否则投影口自己变第二真身）。"""
    assert (REPO_ROOT / rel).is_file()
    source = (REPO_ROOT / rel).read_text(encoding="utf-8")
    fn = next((n for n in _tree(rel).body if isinstance(n, ast.FunctionDef) and n.name == func), None)
    assert fn is not None, f"{rel} 里找不到在册投影 {func}"
    doc_id = (
        id(fn.body[0].value)
        if isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant)
        else None
    )
    stray = [
        sub.value for sub in ast.walk(fn)
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and id(sub) != doc_id
    ]
    assert not stray, f"{rel}::{func} 体内出现字符串字面量 {stray}"
    assert ast.get_source_segment(source, fn) is not None


def test_no_new_production_module_was_created() -> None:
    """用户 10-06 裁定延续：真身与投影口都住在册旧件，本批零新增生产件。"""
    for rel in (ECHO_REL, ALIASES_REL, HOST_STATE_REL, MEDIA_ARCHIVE_REL, CONTROL_PLANE_REL, CONFIG_READINESS_REL):
        assert (REPO_ROOT / rel).is_file(), rel
    forbidden = {"env_flags.py", "nickname_verbs.py", "trigger_words.py", "f13b3_words.py"}
    created = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "plugins").rglob("*.py")
        if "__pycache__" not in p.parts and p.name in forbidden
    ]
    assert not created, f"出现了新建生产件：{created}"


# ---------------------------------------------------------------------------
# ② 三本名册同批迁：尺不能瞎
# ---------------------------------------------------------------------------


def test_s53_sees_no_echo_home_for_the_projected_clusters(s53: Any) -> None:
    """S53 取数口现算：echo 侧真身位里这些簇词集一枚都不许再在场。"""
    _raw, sites, _inline = s53.current_debt()
    projected = {frozenset(_words(snap)) for _t, _f, _fn, _a, snap in CONVERTED_COLUMNS}
    offenders = [
        f"{site.line}:{site.label}"
        for site in sites
        if site.file.endswith("capabilities/echo.py") and site.words in projected
    ]
    assert not offenders, f"echo 仍自带整簇投影词面：{offenders}"


def test_s33_register_has_no_stale_rows(s33: Any) -> None:
    """生产抄位收成引用后，S33 的在册镜像行必须同批摘掉（虚设豁免＝把红搬没）。"""
    acct = s33.accounted_debt()
    assert acct.stale_mirror_entries == (), "S33 HOME_MIRROR_NOT_DEBT 虚设：" + "、".join(
        f"{row.words_text}→{[f.split('/')[-1] for f, _l in row.sites]}" for row in acct.stale_mirror_entries
    )
    assert acct.stale_copy_entries == () and acct.stale_handoff_entries == ()


def test_s33_mirror_rows_for_converted_pairs_are_retired(s33: Any) -> None:
    live = {frozenset(s33._words_from_text(row.words_text)) for row in s33.HOME_MIRROR_NOT_DEBT}
    for topic, _cap, snap in MIRROR_TOPICS:
        assert frozenset(_words(snap)) not in live, f"「{topic}」镜像行还留着（生产已转述）"
    for topic, _func, snap in CAPABILITY_TOPICS:
        assert frozenset(_words(snap)) not in live, f"「{topic}」镜像行还留着（生产已转述）"


def test_s53_roster_has_no_stale_rows(s53: Any) -> None:
    """S53 名册逐枚活性（本锁单列一发＝丙族收编后 yes/no 那两枚抄位署名必须一起迁走）。"""
    _total, sites, inline = s53.current_debt()
    stale = [
        f"{entry.word} @ {entry.site}"
        for entry in s53.INTENTIONAL_UNITS
        if entry.site not in set(s53._fold_unit_keys(entry.word, sites, inline))
    ]
    assert not stale, f"S53 名册虚设：{stale}"


# ---------------------------------------------------------------------------
# ③ 债真降（不是搬家、不是降地板、不是加豁免）
# ---------------------------------------------------------------------------


def test_debt_actually_dropped_below_previous_ceiling(s53: Any) -> None:
    acct, raw, removed = s53.accounted_debt()
    assert s53.WORD_SITE_CEILING < PRE_BATCH_CEILING, (
        f"上限 {s53.WORD_SITE_CEILING} 没低于批 2 的 {PRE_BATCH_CEILING}＝本批没真降债"
    )
    assert acct == s53.WORD_SITE_CEILING, f"计账 {acct} ≠ 上限 {s53.WORD_SITE_CEILING}＝零余量没钉上"
    assert raw < PRE_BATCH_RAW, f"raw {raw} 没随收编下降（批 2 现算 {PRE_BATCH_RAW}）"
    assert removed <= PRE_BATCH_OFFSET, f"名册抵销 {removed} > 批 2 的 {PRE_BATCH_OFFSET}＝降账靠加豁免"


def test_audit_history_prefix_and_authorized_raises_untouched(s53: Any) -> None:
    prefix = (
        ("2026-09-24", 469), ("2026-09-27", 467), ("2026-09-27", 467),
        ("2026-10-05", 477), ("2026-10-06", 472), ("2026-10-07", 447),
    )
    assert tuple(s53.AUDIT_HISTORY[: len(prefix)]) == prefix, "核账历史前缀被改写＝对账凭据作废"
    assert s53.AUDIT_HISTORY[-1][1] == s53.WORD_SITE_CEILING, "尾项没钉上本批现算值"
    assert len(s53.AUTHORIZED_RAISES) == 1, "放宽方向的签字凭据不许增（本批是收口）"


def test_four_scan_floors_are_not_lowered(s53: Any) -> None:
    now = (
        s53.MIN_SCANNED_FILES,
        s53.MIN_VOCAB_WORDS,
        s53.MIN_HOME_SITES,
        s53.MIN_ALIAS_FIELD_SITES,
    )
    assert now == PRE_BATCH_FLOORS, f"四枚地板被下调（{PRE_BATCH_FLOORS}→{now}）＝改瞎尺，不算修债"
    files_total, _homes, _copies = s53._S33.scan_tree()
    _raw, sites, inline = s53.current_debt()
    vocab = frozenset().union(*(s.words for s in sites))
    alias_sites = [
        s for s in sites if s.kind == "ALIASFIELD" or (s.kind == "S33HOME" and "dict:" in s.label)
    ]
    assert files_total >= s53.MIN_SCANNED_FILES, f"文件面读数塌到 {files_total}"
    assert len(vocab) >= s53.MIN_VOCAB_WORDS, f"词汇表塌到 {len(vocab)}"
    assert len(sites) >= s53.MIN_HOME_SITES, f"真身位塌到 {len(sites)}"
    assert len(alias_sites) >= s53.MIN_ALIAS_FIELD_SITES, f"别名字段位塌到 {len(alias_sites)}"
    assert any(inline.values()), "内联面读空＝C 维度瞎了"


# ---------------------------------------------------------------------------
# ④ 行为零变化
# ---------------------------------------------------------------------------


def test_projection_reproduces_pre_batch_word_sets_in_order() -> None:
    """投影输出口与批前手抄快照**逐枚有序全等**（`aliases` 进目录，顺序＝可见内容）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
        nickname_verbs_for,
    )
    from plugins.bot_unified_runtime.domains.media.capabilities import media_archive
    from plugins.bot_unified_runtime.domains.ops.capabilities import host_state

    source = {
        VERB_PROJECTION: lambda arg: nickname_verbs_for(arg),
        HOST_PROJECTION: lambda _a: host_state.host_state_trigger_words(),
        MEDIA_PROJECTION: lambda _a: media_archive.media_archive_trigger_words(),
    }
    for topic, _field, func, arg, snap in CONVERTED_COLUMNS:
        got = list(source[func](arg))
        assert got == _words(snap), f"{topic}：投影输出 {got} ≠ 批前手抄 {_words(snap)}"


def test_static_and_runtime_extraction_agree() -> None:
    """两条取数口（生成器静态 AST / 运行时 import）解同一枚真身，只对一条有效即红。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo
    from scripts.command_catalog import _entries, _entry_meta

    meta_static = _entry_meta()
    static_entries = {
        str(e.get("topic")): e for e in _entries() if isinstance(e, dict)
    }
    runtime_entries = {
        str(e.get("topic")): e for e in echo._HELP_ENTRIES if isinstance(e, dict)
    }
    for topic, field, _func, _arg, snap in CONVERTED_COLUMNS:
        want = tuple(_words(snap))
        if field == "aliases":
            got_static = tuple(static_entries.get(topic, {}).get("aliases") or ())
            got_runtime = tuple(runtime_entries.get(topic, {}).get("aliases") or ())
            assert got_static == want, f"{topic}.aliases 静态口={got_static} ≠ 批前 {want}"
            assert got_runtime == want, f"{topic}.aliases 运行时口={got_runtime} ≠ 批前 {want}"
        else:
            got_static = tuple(meta_static.get(topic, {}).get("triggers_nickname") or ())
            got_runtime = tuple(echo._HELP_ENTRY_META.get(topic, {}).get("triggers_nickname") or ())
            assert got_static == want, f"{topic}.triggers_nickname 静态口={got_static} ≠ 批前 {want}"
            assert got_runtime == want, f"{topic}.triggers_nickname 运行时口={got_runtime} ≠ 批前 {want}"


def test_help_landing_and_route_resolution_are_unchanged() -> None:
    """快照里每枚词的 `/bot help <词>` 落点、检索面与「守岸人<词>」解析目标逐项不变。

    改前现算读数（凭据＝本文件注释）：甲族词由 `DEFAULT_VERB_MAP` 解到该能力；
    乙族（宿主机状态/媒体归档）走能力自带触发词、动词册解不出＝`None`，本批不许把它变成能解，
    也不许让它消失。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
        CommandAliasResolver,
    )

    resolver = CommandAliasResolver(nicknames=["守岸人"])
    seen: set[tuple[str, str]] = set()
    for topic, field, _func, arg, snap in CONVERTED_COLUMNS:
        for word in _words(snap):
            if (topic, word) in seen:
                continue
            seen.add((topic, word))
            assert echo.normalize_help_topic(word) == topic, (
                f"/bot help {word} 落到 {echo.normalize_help_topic(word)!r}（应为 {topic}）"
            )
            assert word.lower() in echo._HELP_ALIAS_MAP, f"「{word}」从帮助检索面消失"
            resolution = resolver.resolve(f"守岸人{word}")
            got = resolution.capability_id if resolution is not None else None
            want = arg if arg in VERB_MAP_CAPABILITIES else None
            assert got == want, f"守岸人{word} 解到 {got!r}（批前读数 {want!r}）"


def test_control_plane_boolean_folding_uses_the_central_register() -> None:
    """丙族：control_plane 的比较式不再手打字集，且三态读数与批前逐格一致。"""
    tree = _tree(CONTROL_PLANE_REL)
    flagged: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not any(isinstance(op, ast.In) for op in node.ops):
            continue
        right = node.comparators[0]
        if not isinstance(right, (ast.Set, ast.Tuple, ast.List)):
            continue
        items = [e.value for e in right.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if items and set(items) <= set(_words(BOOL_TRUE_SNAPSHOT)) | set(_words(BOOL_FALSE_SNAPSHOT)):
            flagged.append(items)
    assert not flagged, f"control_plane 仍在比较式里手打布尔字集：{flagged}"
    from plugins.bot_unified_runtime.domains.core.config import config_readiness

    assert config_readiness.ENV_TRUE_WORDS == frozenset(_words(BOOL_TRUE_SNAPSHOT))
    assert config_readiness.ENV_FALSE_WORDS == frozenset(_words(BOOL_FALSE_SNAPSHOT))


# ---------------------------------------------------------------------------
# ⑤ 注毒自证
# ---------------------------------------------------------------------------


def test_poison_hand_copy_back_breaks_the_new_ceiling(s53: Any) -> None:
    acct_base, raw_base, _removed = s53.accounted_debt()
    assert acct_base == s53.WORD_SITE_CEILING, "前置：本批零余量没钉上"
    targets = sorted({frozenset(_words(snap)) for _t, _f, _fn, _a, snap in CONVERTED_COLUMNS})
    for index, words in enumerate(targets):
        assert words, "注毒前提失效：投影词集为空"
        rel = f"plugins/bot_unified_runtime/domains/ops/_f13b3_virtual_{index}.py"
        acct, raw, _m = s53.accounted_debt(extra=((rel, s53._synth_literal_table("F13B3_WORDS", words)),))
        assert raw > raw_base, f"第 {index} 簇退回手抄没进 raw＝取数口对这一簇失明"
        assert acct > s53.WORD_SITE_CEILING, (
            f"第 {index} 簇退回手抄后计账 {acct} 仍 ≤ 上限 {s53.WORD_SITE_CEILING}"
            "＝本批降的账是靠余量糊的"
        )
