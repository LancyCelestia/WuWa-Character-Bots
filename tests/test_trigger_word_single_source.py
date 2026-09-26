"""触发词单一真身·词面级加强锁（S53，2026-09-24 首账；中央调度收编波「真身册七腿·触发词无副本」）。

本腿执法判定（任务书第④问的答案，照实写）：本腿【已在执法】，出处两处——
  ① 指针腿：``tests/test_capability_manifest_gate.py::test_leg4_trigger_source_is_a_pointer``
     （在册命令面能力的 ``trigger_source`` 必须是可解析 ``路径#符号`` 指针；点名不点行号——该文件本窗被并发修改两次，行号是易碎引用）；
  ② 表级副本账：``tests/test_trigger_word_copy_ratchet.py``（S33 立账，集合全等重复 ruleA +
     整集⊆真身 ruleB，上限 65 零余量）。
故本件不另造第二本表级账，降为【加强锁】：只在「词面（word-form）级」记那本读不到的账，
与 S33 按构造互斥、不双计（其 ruleA 簇成员在本尺折成一枚声明单元；其 ruleB 收的
tests/scripts 侧副本根本不进本尺扫描面）。

本尺记债（词面级；逐词 = 独立声明单元数 − 1）：
  A 词表部分重合：同一词面被 ≥2 枚词集互不相等且互不包含的触发词表真身各抄一份
    （S33 只记全等与整集子集，部分重合两边都不记——这是两本账的真正差额主体）；
  B 别名字段的被遮蔽位：同一帮助条目 dict 里排在 ``triggers_nl``/``triggers_nickname``
    之前的 ``aliases`` 会吞掉 S33 的逐 dict 单字段扫描（实测 S33 收 116 个字段位、
    漏 9 个，本尺把每字段各记一位，补的是那 9 枚与全部部分重合账）；
  C 调度/matcher 内联字面量：``command_text == "…"`` / ``text.startswith((…))`` /
    ``removeprefix(…)`` / 规则工厂单串实参 / 混合容器字面量元素——S33 只读 ≥2 元素
    全字面量容器与含竖线正则串，比较运算与单串参数形态在它两桶里都不存在；
  D 隐藏真身形态：绑定名命中真身命名式而 S33 tier-1 不认的 ``re.compile`` 竖线词表、
    单元素容器、单词命名常量（实测今日树上为 0 枚，判据保留防再长；注毒①走同一口验牙）。
判据「真副本 vs 合法派生」：import / 裸名引用 / ``tuple(X)`` / 推导式＝派生，零字面量不记；
词面以字符串字面量再写一遍＝声明位，记。词汇表 V 只从真身位派生；内联字面量只有命中 V
才入账（防把 ``"wired"`` 这类普通状态串当触发词）。

归属写死（不算本尺的债）：繁简折叠→中央件口径（本尺按字面串比对，不折叠）；
词义冲突/劫持行为→``test_trigger_spec.py``；help↔route 双向覆盖→``test_trigger_bidirectional_gate.py``。

已知盲区（如实写，绿 ≠ 全）：
  ① 绑定名不命中真身命名式的具名竖线正则（如 affinity ``_COMMAND_RE``）两侧账本都不记，
    其词面只在该词面另有真身/内联出现时经 V 间接入账；
  ② docs/route-matrix.md 触发列是 markdown，AST 尺不读（归 doc_sync/双向门）；
  ③ tests/** 与 scripts/** 不进本尺（使用≠声明；测试重列归 S33 ruleB）；
  ④ 全等重复但成员含 S33 不可见形态（如盲区①）时 S33 记不上账、本尺按折叠口径也不重复记，
    这类「谁都没账」的全等对归 S33 识别器的修复方向，不在本尺加账。

账本纪律（照 S33/``test_legacy_shim_import_ratchet.py`` 先例）：上限＝手写字面量、与最近一次
现算核账值零余量相等（``test_zero_slack_ceiling_equals_latest_audit`` 有锁）；``AUDIT_HISTORY``
只准降；扫描面/真身锚点/账本非空/谓词自反塌陷锁；归一后降账＝改小上限＋追加一行
（``python tests/test_trigger_word_single_source.py --bless`` 打建议值、``--ledger`` 打逐条明细）。
注毒全部走「同一取数口吃内存虚拟源码」，不往树里写东西；本文件自身不含任何触发词字面量
（毒词从真身现算合成），对两本账自扫零贡献（self-clean 锁）。

尺身份三元组（首届核账，只作台账头、不设等值断言）：
  尺＝本文件 v1 词面级（A/B/C/D 四类声明单元，折叠口径见上）；
  时刻＝2026-09-24T00:15:39Z（``date -u``，与钉入 AUDIT_HISTORY 的 2026-09-24 值同源）；
  树指纹＝全部真身位 (file:line:label) 有序清单 sha256[:16]＝``e32a4e853ce80610``
  （当时值；现算随树漂移，随 --ledger 打印，不做断言——断言指纹＝把快照当门，见规则 10 教训）。

全离线、只读源码、不 import 任何插件模块、不写盘。
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import re
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Final, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
_S33_PATH = REPO_ROOT / "tests" / "test_trigger_word_copy_ratchet.py"
TEXT_BOUNDARY_REL: Final[str] = "plugins/bot_unified_runtime/domains/core/text_boundary.py"

#: 内联口：消息文本前后缀法与规则工厂（S33 的容器/竖线口读不到的调用形态）。
_PREFIX_CALLS: Final[frozenset[str]] = frozenset(
    {"startswith", "endswith", "removeprefix", "removesuffix"}
)
_RULE_FACTORIES: Final[frozenset[str]] = frozenset(
    {"Keyword", "Command", "CommandStart", "Regex", "Pattern", "RawCommand", "RawArg"}
)
#: 内联口「像消息文本」的接收者判据：防把任意英文串当触发词重列。
_TEXT_RECEIVER: Final[re.Pattern[str]] = re.compile(
    r"(plain_?text|command_?text|cmd_?text|msg_?text|message_?text|user_?text|inbound_?text"
    r"|raw_?text|text_?strip|\btext\b|\.text\b|\bquery\b|\brest\b|_rest\b|\barg\b)",
    re.IGNORECASE,
)

#: **手写字面量**上限（零余量＝等于最近一次现算核账值），只准降。
# 2026-09-24 S53 首账：判据定案后现算词面级债＝469（记债词面 297 枚），零余量钉死（明细 --ledger）。
WORD_SITE_CEILING: Final[int] = 469
#: 逐次核账记录（日期, 当时债数），必须单调不升，且末项＝当前上限（零余量锁）。
AUDIT_HISTORY: Final[tuple[tuple[str, int], ...]] = (("2026-09-24", 469),)

#: 扫描面地板（塌陷即红，不是「大家都干净了」）。
MIN_SCANNED_FILES: Final[int] = 1100
MIN_VOCAB_WORDS: Final[int] = 700
MIN_HOME_SITES: Final[int] = 140
#: 别名字段形态真身位地板（S33HOME 的 dict: 标签 + 本尺 ALIASFIELD，实测 125）。
MIN_ALIAS_FIELD_SITES: Final[int] = 100

#: 锚点真身（文件, 标签必含, 代表词面）：识别器瞎了本条先红。词面为触发词，
#  藏在嵌套 tuple 里——S33 记录集不递归、本尺不收 tests/，两本账都读不到（self-clean 锁实证）。
_ANCHOR_SITES: Final[tuple[tuple[str, str, str], ...]] = (
    ("plugins/bot_unified_runtime/domains/media/capabilities/tts.py", "DEFAULT_TRIGGER_WORDS", "语音合成"),
    ("plugins/bot_unified_runtime/domains/meme/capabilities/randpic.py", "DEFAULT_TRIGGER_WORDS", "随机图"),
    ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases", "语音"),
)


def _load_s33():
    key = "__s53_s33_gate__"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, _S33_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


_S33 = _load_s33()


class Site(NamedTuple):
    """一枚声明单元出现（词表真身位）。"""

    file: str
    line: int
    label: str
    words: frozenset[str]
    kind: str  # S33HOME / ALIASFIELD / EXT / SINGLEREGEX


def _unwrap_compile(node: ast.expr) -> ast.expr:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compile"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0]
    return node


def _named_home_words(node: ast.expr) -> frozenset[str] | None:
    """EXT 维度：S33 tier-1 读不到的真身形态（re.compile 竖线词表 / 单元素容器 / 单词常量）。"""
    items = _S33._str_items(node)
    if items is not None:
        ws = _S33._norm_set(items)
        if ws:
            return ws
        if len(items) == 1 and _S33._word_shape_ok(items[0].strip()):
            return frozenset({items[0].strip()})
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if "|" in node.value and len(node.value) <= 400:
            return _S33._norm_set(_S33._WORD_RUN_RE.findall(node.value))
        t = node.value.strip()
        if t and _S33._word_shape_ok(t):
            return frozenset({t})
    return None


def _scan_plugin_homes(rel: str, tree: ast.Module) -> tuple[list[Site], set[int]]:
    """一个 plugins 文件 → 本尺独有的真身位（ALIAS 第二字段 / EXT 隐藏形态）＋已认领节点集。"""
    sites: list[Site] = []
    claimed = _S33._docstring_constant_ids(tree)
    stmts: list[ast.stmt] = list(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            stmts.extend(node.body)
    for st in stmts:
        if not isinstance(st, (ast.Assign, ast.AnnAssign)) or st.value is None:
            continue
        targets = st.targets if isinstance(st, ast.Assign) else [st.target]
        named = [
            n
            for t in targets
            for n in _S33._target_names(t)
            if _S33.HOME_NAME_PAT.search(n)
        ]
        if not named:
            continue
        ws = _named_home_words(_unwrap_compile(st.value))
        if ws:
            sites.append(Site(rel, st.lineno, "ext:" + ",".join(sorted(named)), ws, "EXT"))
        for sub in ast.walk(st):
            claimed.add(id(sub))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict) or id(node) in claimed:
            continue
        hit = False
        for key, val in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value in _S33.ALIAS_FIELD_KEYS) or val is None:
                continue
            items = _S33._str_items(val)
            ws = _S33._norm_set(items) if items is not None else None
            if ws:
                sites.append(Site(rel, getattr(val, "lineno", node.lineno), f"alias:{key.value!s}", ws, "ALIASFIELD"))
            hit = True
        if hit:
            for sub in ast.walk(node):
                claimed.add(id(sub))
    return sites, claimed


def _scan_plugin_inline(rel: str, tree: ast.Module, claimed: set[int], vocab: frozenset[str]) -> set[str]:
    """C 维度：调度/matcher 内联字面量（比较运算、前后缀法、规则工厂、混合容器字面量元素）。"""
    out: set[str] = set()

    def add(node: ast.expr) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            w = node.value.strip()
            if w and w in vocab:
                out.add(w)

    def words_of(a: ast.expr) -> None:
        if isinstance(a, (ast.Tuple, ast.List, ast.Set)):
            for e in a.elts:
                add(e)
        else:
            add(a)

    for node in ast.walk(tree):
        if id(node) in claimed:
            continue
        if isinstance(node, ast.Compare):
            left = node.left
            if isinstance(left, (ast.Name, ast.Attribute, ast.Call)) and _receiver_is_text(left):
                for comp in node.comparators:
                    words_of(comp)
        elif isinstance(node, ast.Call):
            f = node.func
            attr = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
            if attr in _PREFIX_CALLS and isinstance(f, ast.Attribute) and _receiver_is_text(f.value):
                for a in node.args:
                    words_of(a)
            elif attr in _RULE_FACTORIES:
                for a in [*node.args, *(kw.value for kw in node.keywords)]:
                    words_of(a)
        elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            strs = [e for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if strs and len(strs) < len(node.elts):
                for e in strs:
                    add(e)
    return out


def _receiver_is_text(node: ast.expr) -> bool:
    try:
        return bool(_TEXT_RECEIVER.search(ast.unparse(node)))
    except (ValueError, TypeError, RecursionError):
        return False


# ---------------------------------------------------------------------------
# 取数与账
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _plugin_srcs() -> tuple[tuple[str, str], ...]:
    ok, bad = _S33.iter_tree_sources()
    assert not bad, f"扫描面有洞（前几个：{bad[:3]}）——不许带洞记账"
    return tuple((rel, src) for rel, src in ok if rel.startswith("plugins/") and rel != TEXT_BOUNDARY_REL)


def _home_sites(extra: tuple[tuple[str, str], ...]) -> tuple[list[Site], dict[str, tuple[ast.Module, set[int]]]]:
    """S33 真身册（照抄其缓存结果）＋本尺独有真身位；返回 (sites, 每文件树与认领集)。"""
    s33_homes = list(_S33.scan_tree()[1])
    sites: list[Site] = [Site(h.file, h.line, "t1:" + h.label, h.words, "S33HOME") for h in s33_homes]
    keys = {(h.file, h.words) for h in s33_homes}
    parsed: dict[str, tuple[ast.Module, set[int]]] = {}
    for rel, src in [*_plugin_srcs(), *extra]:
        tree = ast.parse(src, filename=rel)
        extra_sites, claimed = _scan_plugin_homes(rel, tree)
        parsed[rel] = (tree, claimed)
        for s in extra_sites:
            if (s.file, s.words) not in keys:
                sites.append(s)
                keys.add((s.file, s.words))
    return sites, parsed


def _rule_a_cluster_keys() -> frozenset[tuple[str, int, str]]:
    _b, rule_a = _S33.analyze(list(_S33.scan_tree()[1]), [])
    return frozenset((m.file, m.line, m.label) for c in rule_a for m in c.members)


@lru_cache(maxsize=1)
def _base_state() -> tuple[tuple[Site, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    """真树基态（不含虚拟源）：(真身位, 内联词表)。注毒走虚拟件短路，不重扫全树。"""
    sites, parsed = _home_sites(())
    home_sets = {s.words for s in sites}
    vocab = frozenset().union(*home_sets) if home_sets else frozenset()
    inline_files: dict[str, set[str]] = defaultdict(set)
    for rel, (tree, claimed) in parsed.items():
        for w in _scan_plugin_inline(rel, tree, claimed, vocab):
            inline_files[w].add(rel)
    return tuple(sites), tuple((w, tuple(fs)) for w, fs in sorted(inline_files.items()))


def compute_debt(
    extra: tuple[tuple[str, str], ...] = (),
) -> tuple[int, tuple[Site, ...], dict[str, frozenset[str]]]:
    """单一算账口：真树基态 + 虚拟注毒源（短路增量）→ (债数, 全部真身位, 每词的内联文件表)。"""
    sites0, inline0 = _base_state()
    sites = list(sites0)
    inline_files = defaultdict(set, {w: set(fs) for w, fs in inline0})
    if extra:
        known = {(s.file, s.words) for s in sites}
        extra_parsed: dict[str, tuple[ast.Module, set[int]]] = {}
        for rel, src in extra:
            tree = ast.parse(src, filename=rel)
            extra_sites, claimed = _scan_plugin_homes(rel, tree)
            extra_parsed[rel] = (tree, claimed)
            for s in extra_sites:
                if (s.file, s.words) not in known:
                    sites.append(s)
                    known.add((s.file, s.words))
        vocab = frozenset().union(*(s.words for s in sites))
        for rel, (tree, claimed) in extra_parsed.items():
            for w in _scan_plugin_inline(rel, tree, claimed, vocab):
                inline_files[w].add(rel)
    cluster_keys = _rule_a_cluster_keys()
    vocab = frozenset().union(*(s.words for s in sites)) if sites else frozenset()
    by_words: dict[frozenset[str], list[Site]] = defaultdict(list)
    for s in sites:
        by_words[s.words].append(s)
    debt = 0
    for w in sorted(vocab):
        n_units = 0
        for ws, members in by_words.items():
            if w not in ws:
                continue
            cluster_n = sum(1 for m in members if (m.file, m.line, m.label.replace("t1:", "", 1)) in cluster_keys)
            n_units += 1 + max(0, len(members) - max(cluster_n, 1)) if cluster_n >= 2 else len(members)
        n_units += len(inline_files.get(w, ()))
        if n_units >= 2:
            debt += n_units - 1
    return debt, tuple(sites), {w: frozenset(fs) for w, fs in inline_files.items()}


def current_debt() -> tuple[int, tuple[Site, ...], dict[str, frozenset[str]]]:
    return compute_debt()


def _synth_literal_table(name: str, words: frozenset[str]) -> str:
    body = ", ".join('"' + w + '"' for w in sorted(words))
    return f"{name} = ({body},)\n"


def _synth_derived_table(name: str, source: str) -> str:
    return f"{name} = tuple({source})\n"


def _synth_inline_redeclare(words: tuple[str, ...]) -> str:
    body = ", ".join('"' + w + '"' for w in words)
    return "def _s53_virtual_probe(command_text: str) -> bool:\n    return command_text.startswith((" + body + ",))\n"


# ---------------------------------------------------------------------------
# 账
# ---------------------------------------------------------------------------


def test_word_site_debt_within_ceiling() -> None:
    total, _sites, _inline = current_debt()
    assert total <= WORD_SITE_CEILING, (
        f"词面级独立声明债 {total} > 上限 {WORD_SITE_CEILING}＝有词面被第三处抄了。"
        "修法：让第二处引用真身/登记指针（部分重合→共享登记处）；明细跑 --ledger；"
        "全等/子集重复不归本尺，归 test_trigger_word_copy_ratchet"
    )


def test_zero_slack_ceiling_equals_latest_audit() -> None:
    assert WORD_SITE_CEILING == AUDIT_HISTORY[-1][1], (
        "上限≠最近核账值＝偷偷留了余量（或降了账没刷历史）"
    )


def test_ceiling_is_hand_written_literal() -> None:
    """结构锁：上限与核账历史必须是本文件里的手写字面量，不许与被检对象联动。"""
    assigned: dict[str, ast.expr | None] = {}
    for node in ast.walk(ast.parse(Path(__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned[t.id] = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
            assigned[node.target.id] = node.value
    ceiling = assigned.get("WORD_SITE_CEILING")
    assert isinstance(ceiling, ast.Constant) and isinstance(ceiling.value, int), (
        "WORD_SITE_CEILING 被改成派生表达式＝账跟着被检对象一起动，本门结构性失效"
    )
    history = assigned.get("AUDIT_HISTORY")
    assert isinstance(history, (ast.Tuple, ast.List)) and len(history.elts) >= 1, (
        "AUDIT_HISTORY 必须留在本文件且非空——它是「只准降」的对账凭据"
    )


def test_audit_history_never_rises() -> None:
    counts = [c for _, c in AUDIT_HISTORY]
    assert counts == sorted(counts, reverse=True), f"核账记录出现回升（方向锁）：{AUDIT_HISTORY}"
    assert WORD_SITE_CEILING <= counts[0], "上限超过首届核账值＝调大换绿，本门不允许"


def test_scan_surface_did_not_collapse() -> None:
    """塌陷锁：文件面/词汇表/真身位/别名字段位/内联面/锚点——六把攥住才许谈绿。"""
    files_total, _h, _c = _S33.scan_tree()
    assert files_total >= MIN_SCANNED_FILES, f"全树只扫到 {files_total} 个文件（地板 {MIN_SCANNED_FILES}）"
    total, sites, inline = current_debt()
    vocab = frozenset().union(*(s.words for s in sites))
    assert len(vocab) >= MIN_VOCAB_WORDS, f"词汇表只 {len(vocab)} 词（地板 {MIN_VOCAB_WORDS}）＝判据被改瞎"
    assert len(sites) >= MIN_HOME_SITES, f"真身位只 {len(sites)} 枚（地板 {MIN_HOME_SITES}）＝取数口塌了"
    alias_sites = [
        s for s in sites
        if s.kind == "ALIASFIELD" or (s.kind == "S33HOME" and "dict:" in s.label)
    ]
    assert len(alias_sites) >= MIN_ALIAS_FIELD_SITES, (
        f"别名字段形态位只 {len(alias_sites)}（地板 {MIN_ALIAS_FIELD_SITES}）——"
        "字段形态真身位（aliases/triggers_nl/triggers_nickname）塌了＝B 维度与 A 维度主体一起失明"
    )
    assert any(inline.values()), "一条内联重列都没抓到＝C 维度取数口坏了（不是全树干净）"
    for anchor_file, anchor_label, rep_word in _ANCHOR_SITES:
        hit = [s for s in sites if s.file == anchor_file and anchor_label in s.label and rep_word in s.words]
        assert hit, f"锚点真身没被认出：{anchor_file}:{anchor_label}（代表词 {rep_word!r}）"
    assert total > 0, "债务账为空——若真全部归一，请删本门并留说明，别留空转锁"
    # 谓词自反：每个记词条目，其声明单元数确 ≥2（由 debt 口径保证存在两处；抽一验一）
    dup_words = [w for w in sorted(vocab) if _units_of(w, sites, inline) >= 2]
    assert dup_words, "有债却没词面单元数≥2＝账目与判据分叉"


def _units_of(w: str, sites: tuple[Site, ...] | list[Site], inline: dict[str, frozenset[str]]) -> int:
    cluster_keys = _rule_a_cluster_keys()
    groups: dict[frozenset[str], list[Site]] = defaultdict(list)
    for s in sites:
        if w in s.words:
            groups[s.words].append(s)
    n = 0
    for members in groups.values():
        cluster_n = sum(1 for m in members if (m.file, m.line, m.label.replace("t1:", "", 1)) in cluster_keys)
        n += 1 + max(0, len(members) - cluster_n) if cluster_n >= 2 else len(members)
    return n + len(inline.get(w, ()))


# ---------------------------------------------------------------------------
# 注毒自证（内存虚拟源码喂同一取数口，绝不往树里写东西；逐发验牙）
# ---------------------------------------------------------------------------


def _owner_home() -> Site:
    """挑一枚可注毒靶：tts 真身表（锚点件同款搜索路径，词面全部现算、本文件零词面字面量）。"""
    _total, sites, _inline = current_debt()
    for s in sites:
        if s.file.endswith("domains/media/capabilities/tts.py") and "DEFAULT_TRIGGER_WORDS" in s.label:
            return s
    raise AssertionError("注毒前置：找不到 tts 真身靶（先查判据是否被改坏）")


def test_poison_handcopy_of_home_table_is_debt() -> None:
    """注毒①（判据「手抄才算」·正牙）：整表字面量重抄一枚真身 → 恰 +len(words) 笔。"""
    base, _s, _i = current_debt()
    owner = _owner_home()
    rel = "plugins/bot_unified_runtime/domains/ops/_s53_poison_virtual_a.py"
    got, _ss, _ii = compute_debt(extra=((rel, _synth_literal_table("S53_POISON_TRIGGER_WORDS", owner.words)),))
    assert got == base + len(owner.words), (
        f"手抄整表没按词面记满账（base={base} got={got} 词数={len(owner.words)}）＝判据对第二真身失明"
    )


def test_poison_derived_form_is_not_debt() -> None:
    """注毒②（判据「派生不罚」·反牙）：同一名义位置改成引用派生 → 恰 +0 笔（不罚对的）。"""
    base, _s, _i = current_debt()
    rel = "plugins/bot_unified_runtime/domains/ops/_s53_poison_virtual_b.py"
    src = _synth_derived_table("S53_POISON_TRIGGER_WORDS", "SOME_REGISTERED_HOME")
    got, _ss, _ii = compute_debt(extra=((rel, src),))
    assert got == base, f"派生形态被记了债（{base}→{got}）＝本尺在罚正确的引用写法"


def test_poison_inline_redeclaration_is_debt() -> None:
    """注毒③（C 维度）：调度式内联字面量重列三枚词面 → 恰 +3 笔（S33 读不到的形态）。"""
    base, _s, _i = current_debt()
    owner = _owner_home()
    subset3 = tuple(sorted(owner.words)[:3])
    rel = "plugins/bot_unified_runtime/domains/ops/_s53_poison_virtual_c.py"
    got, _ss, _ii = compute_debt(extra=((rel, _synth_inline_redeclare(subset3)),))
    assert got == base + len(subset3), (
        f"内联重列没进账（base={base} got={got}）＝matcher/调度字面量口失明"
    )


def test_poison_out_of_vocabulary_inline_ignored() -> None:
    """注毒④（负样本）：同结构换成查无此词的非词表串 → +0 笔（防把普通英文串当触发词）。"""
    base, _s, _i = current_debt()
    rel = "plugins/bot_unified_runtime/domains/ops/_s53_poison_virtual_d.py"
    src = _synth_inline_redeclare(("zzz查无此触发词甲zzz", "zzz查无此触发词乙zzz"))
    got, _ss, _ii = compute_debt(extra=((rel, src),))
    assert got == base, f"非词汇表串进了账（{base}→{got}）＝负样本无牙"


def test_copy_turned_into_reference_lowers_ledger_stays_green() -> None:
    """注毒⑤（判据方向）：同一虚拟件从手抄改成引用 → 债回落到基线且基线≤上限（修对了锁必绿）。"""
    base, _s, _i = current_debt()
    owner = _owner_home()
    rel = "plugins/bot_unified_runtime/domains/ops/_s53_poison_virtual_e.py"
    copy_debt, _, _ = compute_debt(extra=((rel, _synth_literal_table("S53_POISON_TRIGGER_WORDS", owner.words)),))
    ref_debt, _, _ = compute_debt(extra=((rel, _synth_derived_table("S53_POISON_TRIGGER_WORDS", "REGISTERED_HOME")),))
    assert copy_debt > ref_debt == base >= 0 and base <= WORD_SITE_CEILING, (
        f"方向锁失效：手抄={copy_debt} 引用={ref_debt} 基线={base} 上限={WORD_SITE_CEILING}"
    )


def test_own_file_contributes_no_debt_to_either_ledger() -> None:
    """自证：摘掉本门文件前后，S33 那本的债与本账各自分毫不动（候选可以有，债不许有）。"""
    rel = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
    _f, homes, copies = _S33.scan_tree()
    alt_b, alt_a = _S33.analyze([h for h in homes if h.file != rel], [c for c in copies if c.file != rel])
    on_b, on_a = _S33.analyze(list(homes), list(copies))
    assert _S33.debt_total(alt_b, alt_a) == _S33.debt_total(on_b, on_a), (
        "本门文件给 S33 那本添了债——毒词必须现算合成，不许留字面量在盘上"
    )
    # 本尺取数口结构性不收 tests/（防有人扩面而不自知）。
    assert all(r2.startswith("plugins/") for r2, _t in _home_sites(())[1].items()), (
        "扫描面被扩出 plugins/＝本尺与 S33 的互斥账被打破"
    )


def test_ledger_is_deterministic() -> None:
    a, sa, ia = current_debt()
    b, sb, ib = current_debt()
    assert (a, sa, ia) == (b, sb, ib), "两次现算不等＝账目不确定（排序/集合漂移），棘轮失去意义"


# ---------------------------------------------------------------------------
# CLI：--ledger 逐条明细（人读）／ --bless 打建议上限与历史行（归一后刷账用）
# ---------------------------------------------------------------------------


def ledger_stamp() -> str:
    """尺身份第三元：全部声明单元指纹（信息件，随 --ledger 打印，不参与断言）。"""
    _total, sites, _inline = current_debt()
    joined = "|".join(f"{s.file}:{s.line}:{s.label}" for s in sorted(sites))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def render_ledger(top: int = 60) -> list[str]:
    total, sites, inline = current_debt()
    vocab = frozenset().union(*(s.words for s in sites)) if sites else frozenset()
    rows = []
    for w in sorted(vocab):
        u = _units_of(w, list(sites), inline)
        if u >= 2:
            rows.append((u, w))
    rows.sort(key=lambda r: (-r[0], r[1]))
    lines = [
        f"词面级独立声明债总计 {total}（记债词面 {len(rows)} 枚；尺指纹 {ledger_stamp()}）",
        "全等重复与整集子集不归本账（归 test_trigger_word_copy_ratchet），下列为部分重合/别名第二字段/内联重列/隐藏真身。",
    ]
    for u, w in rows[:top]:
        home_lines = [f"{s.file}:{s.line}:{s.label}:{s.kind}" for s in sites if w in s.words]
        inline_lines = [f"inline:{f}" for f in sorted(inline.get(w, ()))]
        lines.append(f"  {w!r} units={u}")
        for h in home_lines[:6]:
            lines.append(f"      {h}")
        for h in inline_lines[:4]:
            lines.append(f"      {h}")
    return lines


def main(argv: list[str]) -> int:
    if "--ledger" in argv:
        for line in render_ledger(top=30):
            print(line)
        return 0
    total, _s, _i = current_debt()
    if "--bless" in argv:
        print(f"现算债数 = {total}")
        print(f'建议：WORD_SITE_CEILING = {total} 且 AUDIT_HISTORY 追加 ("<今日YYYY-MM-DD>", {total}),')
        print(f"尺指纹 = {ledger_stamp()}")
        return 0
    print(f"现算债数 = {total}（上限 {WORD_SITE_CEILING}）；--ledger 看明细，--bless 看刷账建议")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
