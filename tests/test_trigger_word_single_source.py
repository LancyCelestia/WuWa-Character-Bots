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

**名册通道（K-3 乙，用户裁定 2026-09-26，S-TRIG-ROSTER 落码）**：本尺原无登记面——任何真实
增量都会把账顶红而无路可走（对照 S33 早有 ``COPY_NOT_DEBT`` 三册）。现补一枚 ``INTENTIONAL_UNITS``
名册：**每条目＝一枚「词面×声明位」的有意在场**（word+site+owner+reason 逐枚点名），
记账数＝raw 债 − 名册命中（每词兜底至少留一枚声明位，绝不减成负债）。四把牙照 S33 纪律：
①零缺省豁免——名册不含通配，未登记的新副本照常记账（注毒⑥专验此牙；把登记表清空即回到
raw 的红）；②逐枚活性锁——条目在本日现算里找不到对应声明位即红（防名册变永久垃圾场）；
③逐枚干活的锁——摘掉任意一条，计账数必 +1；④禁条款化——word 单词面、site 前缀合法且路径
在盘、reason 互不相同且 ≥20 字。**上限 469 与 AUDIT_HISTORY 一个字没动**：门没有变松，
只是「第二处抄」从此必须署名为「有意」才过关。首届登记 42 枚逐枚现算归因（对照基线提交
``5cc6832`` 树现算重建恰为 469，逐词正增量合计 42＝本册条数：群信息帮助镜像位 15 ＋
consent 同意门波命令面位 12 ＋ yes/no 布尔解析内联 4 ＋ web 检索脚手架词 5 ＋ temporal
今日 1 ＋ 来源标识/审计标签/根标签/人话映射等结构串内联 4 ＋ steam 免費帮助昵称位 1）。
计账落点 467 比上限少 2 格——差额来自另两枚词面随他波改写自然回落，不是名册多抵销
（抵销数由 ``accounted_debt`` 第三读数与逐枚干活锁看着）。

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
# 2026-09-27 R8 甲·S-R8-TRIGGER-c 核账 469 → 467：日程板在飞波（未跟踪 schedule_board.py＋echo.py
# 工作树 diff「日程」帮助条目）三态现算归因 +8 单元，其中 8 枚帮助册双列镜像位经逐枚点名进
# INTENTIONAL_UNITS 第二批次（凭据见该批批注与 .superpowers/sdd/2026-09-27-fullload/logs/
# SEAT-R8-TRIGGER-c.md）；现算 467＝raw 517 − 名册抵销 50，零余量钉死。**判据、扫描面一字未动。**
# 2026-09-27 ROSTER-467-b 第三批复账：上限数字一字不动（467 仍是棘轮=真值），复账改的是树侧漂移
# ——第 9 项三条定稿在飞件 message_merge.py（未跟踪）新表 DUAL_TRIGGER_COMMAND_HEADS 把 raw 517→527
# 顶出十枚新增第二声明位（status/queue/readiness/llm/config/pause/resume/persona/roles/history
# clear，逐枚现算 diff 归因＝HEAD 树 509 vs 现树 527 逐词清单，全部指向该波），十枚逐枚点名进
# INTENTIONAL_UNITS 第三批（凭据＝该批批注与 SEAT-MERGE9-AUDIT.md §2 裁定③——该节逐一点名十头并
# 论证「只收无参数坠 help 兜底的头」）；现算 467＝raw 527 − 名册抵销 60，零余量复钉。
# 今日门形先红 477>467（raw 527/抵销 50），归因全干净走 K-3乙名册通道后回绿；「43-44>42」旧红系
# S33 表级尺（另一维度，R8 甲已收口），与本尺无涉。**判据、扫描面、上限数值一字未动。**
WORD_SITE_CEILING: Final[int] = 467
#: 逐次核账记录（日期, 当时债数），必须单调不升，且末项＝当前上限（零余量锁）。
AUDIT_HISTORY: Final[tuple[tuple[str, int], ...]] = (
    ("2026-09-24", 469), ("2026-09-27", 467), ("2026-09-27", 467),
)

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


# ---------------------------------------------------------------------------
# 名册通道（K-3 乙）：词面×声明位 的逐枚「有意」登记
# ---------------------------------------------------------------------------


class DeclaredUnit(NamedTuple):
    """一枚显式登记的「词面 word 出现在声明位 site」＝有意在场。

    site 键与 ``_fold_unit_keys`` 的产出一一对应：真身位 ``<rel>#<Site.label>``、
    内联 ``inline:<rel>``、S33 ruleA 折叠簇 ``CLUSTER|<成员键以|分隔、已排序>``。
    键不含行号（行号随任何编辑漂移）；换词、换位、簇多一员 ⇒ 不再命中 ⇒ 恢复记账。
    """

    word: str
    site: str
    owner: str
    reason: str


#: 「帮助册 aliases ≡ triggers_nickname」这对在册镜像簇的声明位键（群信息族共用）。
_ECHO_MIRROR_CLUSTER: Final[str] = (
    "CLUSTER|plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#t1:dict:aliases"
    "|plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#t1:dict:triggers_nickname"
)
_CONSENT_ADMIN: Final[str] = "plugins/bot_unified_runtime/domains/ops/capabilities/consent_admin.py"
_WS: Final[str] = "plugins/bot_unified_runtime/domains/core/search/web_search.py"
_MERGE_HEADS: Final[str] = (
    "plugins/bot_unified_runtime/domains/chat_reply/runtime/message_merge.py#t1:DUAL_TRIGGER_COMMAND_HEADS"
)

#: **首届登记 42 枚（2026-09-26，S-TRIG-ROSTER，对照基线提交 5cc6832 逐词现算归因）**。
#: 零缺省豁免：无通配、无「凡 X 类不计」条款；新增副本不进本册 ⇒ 照常记红。
INTENTIONAL_UNITS: Final[tuple[DeclaredUnit, ...]] = (
    # ── 群信息「参与者/相册/待办」腿（S-T-GRP-2 等，2026-09-25/26）：登记帮助侧镜像位，
    #    路由真身 group_info._INTENT_* 留账——第三处再抄这枚词面仍会记债。
    DeclaredUnit("群参与者", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "帮助册双位镜像（双向覆盖门要求能力词同面在场，见 test_trigger_bidirectional_gate 第 108 行台账注释）；真身为 group_info._INTENT_WHO_WORDS"),
    DeclaredUnit("本群参与者", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "同一参与者腿的帮助侧词面，真身 group_info._INTENT_WHO_WORDS；本波（S-T-GRP-2）逐词点名第二枚"),
    DeclaredUnit("我都跟谁聊过", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "同一参与者腿的帮助侧词面，真身 group_info._INTENT_WHO_WORDS；本波逐词点名第三枚"),
    DeclaredUnit("跟谁聊过", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "同一参与者腿的帮助侧词面，真身 group_info._INTENT_WHO_WORDS；本波逐词点名第四枚"),
    DeclaredUnit("群里谁说过话", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "同一参与者腿的帮助侧词面，真身 group_info._INTENT_WHO_WORDS；本波逐词点名第五枚"),
    DeclaredUnit("本群谁说过话", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "同一参与者腿的帮助侧词面，真身 group_info._INTENT_WHO_WORDS；本波逐词点名第六枚"),
    DeclaredUnit("都有谁说过话", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "同一参与者腿的帮助侧词面，真身 group_info._INTENT_WHO_WORDS；本波逐词点名第七枚"),
    DeclaredUnit("本群都有谁", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "同一参与者腿的帮助侧词面，真身 group_info._INTENT_WHO_WORDS；本波逐词点名第八枚"),
    DeclaredUnit("群里都有谁", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "同一参与者腿的帮助侧词面，真身 group_info._INTENT_WHO_WORDS；本波逐词点名第九枚"),
    DeclaredUnit("群相册", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "群相册腿（2026-09-25 接线批）帮助侧词面，真身 group_info._INTENT_ALBUM_WORDS；帮助闭合门要求同面在场"),
    DeclaredUnit("群相册列表", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "群相册腿帮助侧词面（列表变体），真身 group_info._INTENT_ALBUM_WORDS；本批逐词点名第二枚"),
    DeclaredUnit("本群相册", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "群相册腿帮助侧词面（本群变体），真身 group_info._INTENT_ALBUM_WORDS；本批逐词点名第三枚"),
    DeclaredUnit("群待办", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "群待办腿帮助侧词面，真身 group_info._INTENT_TODO_WORDS；与相册腿同批接线、逐词点名"),
    DeclaredUnit("群待办列表", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "群待办腿帮助侧词面（列表变体），真身 group_info._INTENT_TODO_WORDS；本批逐词点名第二枚"),
    DeclaredUnit("本群待办", _ECHO_MIRROR_CLUSTER, "bot.group_info",
                 "群待办腿帮助侧词面（本群变体），真身 group_info._INTENT_TODO_WORDS；本批逐词点名第三枚"),
    # ── 同意门波（18 项收尾波 #56，2026-09-26）：登记命令面侧抄位，核心引擎真身留账。
    DeclaredUnit("approve", _CONSENT_ADMIN + "#t1:_APPROVE_VERBS", "bot.consent",
                 "管理员命令面动词表与核心引擎 domains/core/safety_exec/consent.py 判定表部分重合（同型双写系同意门波有意分层，核心表只四词、命令面多出单字与口语形）"),
    DeclaredUnit("同意", _CONSENT_ADMIN + "#t1:_APPROVE_VERBS", "bot.consent",
                 "同上命令面表：中文批语动词的第二声明位，核心引擎表为判据真身"),
    DeclaredUnit("批准", _CONSENT_ADMIN + "#t1:_APPROVE_VERBS", "bot.consent",
                 "同上命令面表：中文批语动词第三枚，核心引擎表为判据真身"),
    DeclaredUnit("deny", _CONSENT_ADMIN + "#t1:_DENY_VERBS", "bot.consent",
                 "命令面否向动词表与核心引擎 _DENY_VERBS 重合枚，同意门波分层设计的第二声明位"),
    DeclaredUnit("拒绝", _CONSENT_ADMIN + "#t1:_DENY_VERBS", "bot.consent",
                 "命令面否向动词中文枚，核心引擎表为真身；本波逐词点名第二枚"),
    DeclaredUnit("驳回", _CONSENT_ADMIN + "#t1:_DENY_VERBS", "bot.consent",
                 "命令面否向动词中文枚，核心引擎表为真身；本波逐词点名第三枚"),
    DeclaredUnit("list", _CONSENT_ADMIN + "#t1:_LIST_VERBS", "bot.consent",
                 "跨能力撞词（通用列表词已被 emergency_info._LIST_WORDS/meme._LIST_VERBS 各持）：同意卡待批子命令复用同词面属命名空间设计内，路由按能力前缀分离"),
    DeclaredUnit("列表", _CONSENT_ADMIN + "#t1:_LIST_VERBS", "bot.consent",
                 "同 list 的中文形跨能力撞词：consent/紧急/meme 三家各持一枚子命令动词，无共同上级册"),
    DeclaredUnit("pending", _CONSENT_ADMIN + "#t1:_LIST_VERBS", "bot.consent",
                 "跨能力撞词（emergency_info._PENDING_WORDS/runtime_admin 内联已在先）：同意面把「待批」钉在同一子命令动词表里"),
    DeclaredUnit("view", _CONSENT_ADMIN + "#t1:_SHOW_VERBS", "bot.consent",
                 "跨能力撞词（emergency_info._VIEW_WORDS 已在先）：同意面看单动词，语义各自封闭在能力前缀后"),
    DeclaredUnit("看", _CONSENT_ADMIN + "#t1:_SHOW_VERBS", "bot.consent",
                 "同 view 的中文单字形跨能力撞词：命令面子动词，路由靠「同意卡/书面同意」前缀让路"),
    DeclaredUnit("详情", _CONSENT_ADMIN + "#t1:_SHOW_VERBS", "bot.consent",
                 "同 view 的中文详情形跨能力撞词：命令面子动词第三枚"),
    DeclaredUnit("yes", "inline:plugins/bot_unified_runtime/control_plane/__init__.py", "control_plane",
                 "布尔字面量解析（1/true/on/yes 归真）：词面撞上同意动词表纯属通用布尔别名巧合，不驱动任何路由，非触发面"),
    DeclaredUnit("yes", "inline:plugins/bot_unified_runtime/domains/chat_reply/llm_engine/channel_health.py", "llm_engine",
                 "同上布尔解析的第二实现位（str(raw).strip().lower() 判 1/true/on/yes）：结构串不是触发词抄写"),
    DeclaredUnit("no", "inline:plugins/bot_unified_runtime/control_plane/__init__.py", "control_plane",
                 "布尔字面量解析（0/false/off/no 归假）：与 yes 同位的反向枚，不是触发面"),
    DeclaredUnit("no", "inline:plugins/bot_unified_runtime/domains/chat_reply/llm_engine/channel_health.py", "llm_engine",
                 "同上布尔解析第二实现位的反向枚：结构串与触发词表零关系"),
    # ── web 检索脚手架词表（检索查询拼装用，非命令触发面）：词面与触发词汇表 V 重合。
    DeclaredUnit("一下", _WS + "#t1:_CJK_SCAFFOLD_QUERY_WORDS", "domains/core/search",
                 "检索查询脚手架助词表：用于把口语改写成可搜查询，不进路由判据；命中的是「查询好感一下」这类句子里的动词尾缀"),
    DeclaredUnit("介绍一下", _WS + "#t1:_CJK_SCAFFOLD_QUERY_WORDS", "domains/core/search",
                 "同表介绍脚手架枚：检索意图词与触发词表部分重合，判据不消费"),
    DeclaredUnit("为什么", _WS + "#t1:_CJK_SCAFFOLD_QUERY_WORDS", "domains/core/search",
                 "同表疑问脚手架枚：chat.help 主题词「为什么/为啥」在先，本表是检索侧独立语义"),
    DeclaredUnit("最新", _WS + "#t1:_CJK_SCAFFOLD_TIME_WORDS", "domains/core/search",
                 "检索时间脚手架表首枚：钉「搜最新信息」的查询后缀，不驱动任何 RouteKind"),
    DeclaredUnit("最近", _WS + "#t1:_CJK_SCAFFOLD_TIME_WORDS", "domains/core/search",
                 "同表时间枚第二格：与快订/历史类触发词面重合属词义借用非同源抄写"),
    # ── temporal 中枢表与帮助词面重合（时间副词真身，非命令触发）。
    DeclaredUnit("今日", "plugins/bot_unified_runtime/domains/core/temporal_words.py#t1:TODAY_ADVERB_WORDS", "domains/core/temporal",
                 "时间副词中央表：为提醒/笔记解析「今日/明天」服务，「历史上的今天」帮助词在先，两表语义正交"),
    # ── 结构串内联（审计标签/来源 id/根标签/人话映射）：词面命中 V 但用途与触发无关。
    DeclaredUnit("moegirl", "inline:plugins/bot_unified_runtime/domains/core/search/search_service.py", "domains/core/search",
                 "知识来源阶梯/权重表按来源 id「moegirl」键值：结构数据不是第二处触发词（S33 名册同型判例——键撞词面）"),
    DeclaredUnit("randpic", "inline:plugins/bot_unified_runtime/domains/meme/capabilities/randpic.py", "bot.randpic",
                 "本能力自报家门的 capability_id/审计标签/seed 前缀里出现 randpic 字面：使用自家真身词的标识串，非第二声明位"),
    DeclaredUnit("runtime", "inline:plugins/bot_unified_runtime/domains/core/safety_exec/paths.py", "domains/core/safety_exec",
                 "可读根登记标签「runtime」（readable.append 元组字面）撞 /bot runtime 命令词面：路径域标识，非触发面"),
    DeclaredUnit("邮件", "inline:plugins/bot_unified_runtime/domains/ops/monitor/alerts.py", "domains/ops/monitor",
                 "告警人话映射表（SessionType.EMAIL→邮件，2026-09-25 澜汐硬约束件）：展示标签撞帮助主题词面"),
    # ── steam 免費帮助位：该 topic 的 aliases 与 triggers_nickname 两列词集互不相等（故不折叠成簇），
    #    昵称位一枚为本波新增词面的第二声明位（双向门要求帮助册两列各自闭合）。
    DeclaredUnit("steam 免費",
                 "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#t1:dict:triggers_nickname",
                 "bot.subscribe",
                 "steam 资讯订阅帮助条目：aliases 列与昵称触发列词集不等（「免费」两形分居两列），帮助闭合门要求两列同时在场，本条登记昵称位"),
    # ── 第二批次 8 枚（R8 甲·S-R8-TRIGGER-c，2026-09-27 逐枚归因）：日程板在飞波（未跟踪新件
    #    domains/schedule/capabilities/schedule_board.py ＋ echo.py 工作树 diff「日程」帮助条目）。
    #    三态现算（HEAD(b0172ee) 树 → 现树，同判据）证得 raw 509→517 的 +8 全部来自本波新增词面
    #    （kebiao/rclb/richeng/richengliebiao/日程/日程板/schedule），逐枚点名如下；路由真身在
    #    schedule_board 能力侧，帮助册两列为别名闭合/双向覆盖门要求的镜像位（照首届 steam 免費、
    #    群信息簇同判例）。⚠ 在飞件词集若再编辑，本批按四把牙由件 owner 重登记。
    DeclaredUnit("kebiao",
                 "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#alias:triggers_nickname",
                 "bot.schedule",
                 "「日程」帮助条目双列镜像：课表罗马音 kebiao 在 aliases 列与触发昵称列各一枚（词集不全等故不折叠成簇），帮助闭合门要求两列同面在场，真身位记在 aliases 列"),
    DeclaredUnit("rclb",
                 "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#alias:triggers_nickname",
                 "bot.schedule",
                 "同条目双列镜像第二枚：日程列表缩写 rclb 之昵称列位，与 kebiao 枚同波同判例（R8 甲三态现算归因）"),
    DeclaredUnit("richeng",
                 "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#alias:triggers_nickname",
                 "bot.schedule",
                 "同条目双列镜像第三枚：日程罗马音 richeng 之昵称列位，路由消费面在 schedule_board 能力件，本列仅帮助册镜像"),
    DeclaredUnit("richengliebiao",
                 "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#alias:triggers_nickname",
                 "bot.schedule",
                 "同条目双列镜像第四枚：日程列表罗马音 richengliebiao 之昵称列位，与上三枚同一未跟踪新件波次"),
    DeclaredUnit("schedule",
                 "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#t1:dict:aliases",
                 "bot.schedule",
                 "schedule 英文帮助词：本位为帮助册 aliases 列镜像位，命令面真身＝schedule_board.py 内联判据（该 inline 位保留在册），双列+能力面三单元中登记本镜像一枚"),
    DeclaredUnit("schedule",
                 "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#alias:triggers_nickname",
                 "bot.schedule",
                 "schedule 之昵称列第二镜像位：与上一条同词双列点名，抵尽后本词只剩能力侧真身一格（每词兜底留一枚声明位由 accounted_debt 强制）"),
    DeclaredUnit("日程",
                 "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#alias:triggers_nickname",
                 "bot.schedule",
                 "中文主题词「日程」双列镜像之昵称位：帮助册两列词集不等不折叠成簇，主题词双列在场系别名闭合门形态（归因凭据见本批批注）"),
    DeclaredUnit("日程板",
                 "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#alias:triggers_nickname",
                 "bot.schedule",
                 "「日程板」之昵称列镜像位：本批逐词点名第八枚，判据同「日程」枚；未跟踪件 schedule_board 波落地后此两列形态即定"),
    # ── 第三批次 10 枚（ROSTER-467-b，2026-09-27 逐枚归因）：第 9 项三条睡前定稿在飞波——未跟踪
    #    判据件 domains/chat_reply/runtime/message_merge.py 的 DUAL_TRIGGER_COMMAND_HEADS 新表 +
    #    根 __init__.py 108 行纯追加装配（审计凭据 .superpowers/sdd/2026-09-27-fullload/logs/
    #    SEAT-MERGE9-AUDIT.md §2 裁定③：该节逐一点名十头 status/queue/readiness/llm/config/pause/
    #    resume/persona/roles/history clear 并论证「只收整条无参数、尾随文字今天坠 help 兜底的头」）。
    #    三态现算（HEAD 树 509 vs 现树 527 逐词声明位清单 diff）证得 raw 517→527 的 +10 全部来自
    #    本表一枚新声明位对十枚词面的第二抄；路由真身＝根 _handle_status elif 链既有内联记账位、
    #    帮助册位与他位照旧留账——本册只抵表这一枚声明位，第三处再抄仍记债。
    #    ⚠ 第 9 项波若按审计简报 §3.1 收口或头集再编辑，本批按四把牙由件 owner 重登记。
    DeclaredUnit("status", _MERGE_HEADS, "bot.message_merge",
                 "第9项定稿③双触发头表 status 枚：头面字面重列供判据识尾随余文，命令真身＝根 _handle_status 的兜底分支与帮助册记账位照旧留账，本名册仅抵表这一枚声明位"),
    DeclaredUnit("queue", _MERGE_HEADS, "bot.message_merge",
                 "第9项定稿③双触发头表 queue 枚：该头第二声明位在表侧，根精确相等分支为路由真身；头集只收无参数坠 help 兜底的头，带参数头文本语义逐字节不变"),
    DeclaredUnit("readiness", _MERGE_HEADS, "bot.message_merge",
                 "第9项定稿③双触发头表 readiness 枚：判据的头面第二声明位，路由真身与帮助册既有记账位未动；分层按审计简报——判据住 message_merge、通路住根装配，不长第二判据亦不长第二通路"),
    DeclaredUnit("llm", _MERGE_HEADS, "bot.message_merge",
                 "第9项定稿③双触发头表 llm 枚：本表按精确相等分支从根 elif 链现算取头（非第二权威）故登记为镜像位；带参数子命令头一律不入集，命令面语义零变化"),
    DeclaredUnit("config", _MERGE_HEADS, "bot.message_merge",
                 "第9项定稿③双触发头表 config 枚：config 子命令头之表侧第二声明位，根内联精确相等分支与 runtime/aliases 词表位照旧各记其账，本批逐词点名不多吃一格"),
    DeclaredUnit("pause", _MERGE_HEADS, "bot.message_merge",
                 "第9项定稿③双触发头表 pause 枚：与 resume 成对的暂停头在表侧重列，判据 command_natural_remainder 只对精确相等头返回尾余文，不驱动任何 RouteKind"),
    DeclaredUnit("resume", _MERGE_HEADS, "bot.message_merge",
                 "第9项定稿③双触发头表 resume 枚：成对头的第二枚逐词点名，表按最长头优先排序消费该集合；此登记不豁免帮助册与根内联的既有记账单元"),
    DeclaredUnit("persona", _MERGE_HEADS, "bot.message_merge",
                 "第9项定稿③双触发头表 persona 枚：人格子命令头之表侧镜像第二声明位，根内联分支与 ops/smoke/console_chat 内联位原有记账两格分毫未动；波次凭据见 SEAT-MERGE9-AUDIT"),
    DeclaredUnit("roles", _MERGE_HEADS, "bot.message_merge",
                 "第9项定稿③双触发头表 roles 枚：判据所需头面字面镜像，根 elif 链精确相等比较是唯一路由消费点；头集扩量须逐枚点名并同步反例清单锁，本条不为未来新头预留通配"),
    DeclaredUnit("history clear", _MERGE_HEADS, "bot.message_merge",
                 "第9项定稿③双触发头表 history clear 枚：双 token 头此前仅根内联一格记 1 单元不成债，表侧新格使其达两格入账，最长头优先匹配护其不被单 token 头抢占；波次凭据同审计简报裁定③"),
    # ── 第四批次 3 枚（S-FIX-11B-TRIG，2026-09-27 逐枚归因）：日程板在飞波于当日 08:35 前后在
    #    domains/schedule/capabilities/schedule_board.py（工作树 diff，HEAD 无此表）新增第一人称
    #    头词正则表 _QUESTION_FIRST_PERSON_HEAD_WORDS（词面含「我」「自己」），使 HEAD 树既有、
    #    此前不记债的两处**语法自指比较**重新被内联口认作第二声明位。三态现算（HEAD 树 519 词面
    #    清单 vs 现树逐词 diff）证得本 3 枚全部由该新表在场触发；affinity 自指参数解析与
    #    reflection「事实须以『我』开头」的沉淀判据都是**人称代词语法用法**、不驱动任何
    #    RouteKind——路由真身在 schedule_board 侧照旧留账，本批只抵这两枚旧位。
    #    ⚠ 在飞件约定同第三批次：该第一人称表词集若再编辑（摘「我」或「自己」）、或这两处旧位
    #    被改写为引用真身形态，本批对应条即虚设转红，由件 owner 按四把牙重登记/摘牌。
    #    有效期至 2026-10-04：到期由核账席逐枚复验词形在场，不在即摘牌，不自动续期。
    #    2026-09-29 S-BASE 基线席提前复验：现算该位清单为空（'我' @ inline:affinity 已不在场，
    #    活性锁当场点名）⇒ 按本注「不在即摘牌」摘此一枚；同比较式「自己」一枚今仍在场、照留。
    #    同日复验第二枚：'我' @ inline:reflection 亦虚设（批⑰ ae2e7c1 重写反思消毒腿后
    #    startswith 判据换形，现算清单为空、活性锁点名）⇒ 同批摘牌；抵销 60→58 如实入账。
    DeclaredUnit("自己", "inline:plugins/bot_unified_runtime/domains/chat_reply/capabilities/affinity.py", "bot.affinity",
                 "同枚自指参数集的第二词面「自己」：与上「我」同一比较式逐词点名，参数语义为「查我自己」，跨能力撞代词非同源抄表"),
    # ── 表情册审批面（T25，2026-10-01）：双向门方向 1（路由有词、help 册须有落点）要求
    #    bot.meme_library 的路由词「待审」在帮助册在场，落点取
    #    ``echo._HELP_ENTRY_META["表情册"].triggers_nl``（走 META 不走 aliases＝保住
    #    「待审」的检索主落点仍归「紧急信息」，别名表按 aliases 先建、META 后 setdefault）。
    #    路由真身 meme_library 的审批正则照旧留账；同批新位上的「审批」一枚现算只有
    #    一处声明（len(keys)<2 不记债），按「逐枚干活锁」不进本册。
    #    ⚠ 失效约定同前三批：表情册 triggers_nl 摘掉这枚词面、或紧急信息那两位收敛成
    #    引用真身形态 ⇒ 本条虚设转红，由件 owner 按四把牙复登记/摘牌，不自动续期。
    DeclaredUnit("待审", "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#t1:dict:triggers_nl", "bot.meme_library",
                 "表情册审批面的帮助册镜像位（双向门方向 1 的落点），真身是 meme_library 审批正则；紧急信息侧 aliases 与 alias:triggers_nl 两处属另一能力词表，不作同源抵销"),
    # ── 第五批（S-ALBUM 表情册波，2026-10-02；凭据＝docs/HANDBOOK.md §58.9–58.16 与本件同族的
    #    表情册四动作锁）：本波新增的声明位逐枚点名，只登记本波这一格，别家能力的账分毫不动。
    #    真改引用在本波不可行——帮助册的字面投影由帮助闭合门与双向触发门两头同时要求，
    #    跨域 import 他域词表违插件强隔离常令。
    #    ⚠ 失效约定同前四批：摘掉本波任一处的词面、或把真身收敛成引用形态 ⇒ 本条虚设转红，
    #    由件 owner 按四把牙复登记/摘牌，不自动续期。
    DeclaredUnit("approve", "plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py#t1:_REVIEW_APPROVE_WORDS", "bot.meme_library",
                 "表情册审批面的「批」动词表：与同意门 core/safety_exec/consent.py 判定表部分重合，本表另收 通过/准入/收/收下/admit 五枚册面口语形；批的是图不是授权，两判据互不消费，只登记本表这一枚声明位"),
    DeclaredUnit("同意", "plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py#t1:_REVIEW_APPROVE_WORDS", "bot.meme_library",
                 "同上审批动词表的中文枚：判定真身为 consent.py（首册已点名核心表与命令面表两格），本枚是表情册审核面的第三声明位，摘掉本条即恢复记账"),
    DeclaredUnit("批准", "plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py#t1:_REVIEW_APPROVE_WORDS", "bot.meme_library",
                 "同上审批动词表第二中文枚：管理员在待审队列里敲的词，消费点为 set_review_state(ADMIT)，与同意门的批准动词无共享判据，逐词点名不多吃一格"),
    DeclaredUnit("admit", "inline:plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py", "bot.meme_library",
                 "入册回执的审计标签字面 audit=[\"meme_library\", \"album\", \"admit\", status]：结构串撞自家动词词面，与同文件审批表是两种形态，本枚只抵内联标签这一格（真身留表侧）"),
    DeclaredUnit("deny", "plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py#t1:_REVIEW_REJECT_WORDS", "bot.meme_library",
                 "表情册审批面的「拒」动词表：与同意门 _DENY_VERBS 部分重合（同型双写系分层设计），本表另收 不收/reject 两形，删行删文件走 reject_review 而非同意门否决通路"),
    DeclaredUnit("拒绝", "plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py#t1:_REVIEW_REJECT_WORDS", "bot.meme_library",
                 "同上拒动词表中文枚：审核面的人话动词，消费点在本件 reject_review；consent 与 consent_admin 两位各照旧记自己的账，本册不替它们抵销"),
    DeclaredUnit("驳回", "plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py#t1:_REVIEW_REJECT_WORDS", "bot.meme_library",
                 "同上拒动词表第二中文枚：与同意门驳回同字不同事（此处落内容级墓碑、同图重发不复活，口径同 NSFW 删除），词面重合属审批语汇自然共用"),
    DeclaredUnit("reject", "plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py#t1:_REVIEW_REJECT_WORDS", "bot.meme_library",
                 "本词面此前只在 ops/capabilities/consent_admin.py 命令面一格、不成债；表情册拒表在场后达两格入账，登记表侧这一枚、命令面格照旧留账"),
    DeclaredUnit("review", "inline:plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py", "bot.meme_library",
                 "审批子命令的分支返回值与审计串里的 review 字面（return \"review\", ...）：路由判据是 _REVIEW_RE 正则而非这枚字面，真身留 emergency_info 待审词表那一格"),
    DeclaredUnit("list", "inline:plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py", "bot.meme_library",
                 "待审队列回执审计标签里的 list 字面（跨能力通用子命令动词，emergency/meme/consent 三家在先）：本枚只抵 meme_library 内联这一格，其余三家各自的账分毫不动"),
    DeclaredUnit("表情册", "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#t1:dict:aliases", "bot.meme_library",
                 "「表情册」帮助条目 aliases 列镜像位：别名→能力的路由真身为 runtime/aliases.py 的 DEFAULT_VERB_MAP（S-ALBUM 同批补的两键，缺则「守岸人 表情册」坠 help 兜底），帮助闭合门要求帮助册同面在场，故登记帮助侧"),
    DeclaredUnit("表情相冊", "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py#t1:dict:aliases", "bot.meme_library",
                 "同条目繁体形的帮助侧镜像位：简繁成对口径同 隨機/随机 判例，消费点在别名册而非帮助册，本批逐词点名第二枚，摘掉即恢复记账"),
    # ── 席 S6（2026-10-08 `/bot intimate` 命令面接线波）第五批：**只登记本席新增的这一枚**。
    #    现算读数＝raw 551→552、抵销 74→75、计账 477 一字不动；同波另有人登记的 10 枚超载
    #    （477 与上限 467 的差额）系他席在飞件，与本席无涉，本条既不承担也不顺抵。
    #    ⚠ 上限 467 与 AUDIT_HISTORY 一字未动（调大换绿是本门明令禁止的修法）。
    DeclaredUnit("intimate", "inline:plugins/bot_unified_runtime/__init__.py", "bot.chat",
                 "根分派链 _handle_status 新增 elif 的手打分支字面量（== 与 startswith/removeprefix 三处同文件折成一格）：档位值真身住 content_route.MODE_INTIMATE、子命令词表真身住 _INTIMATE_SUBCOMMAND_TABLE，帮助册 echo 的「亲密模式」aliases 持该词面做主题检索；分派位按既有 38 支同形写法只能字面打，本枚只抵根链这一格"),
)


def _fold_unit_keys(
    w: str,
    sites: tuple[Site, ...] | list[Site],
    inline: dict[str, frozenset[str]],
) -> list[str]:
    """把 ``_units_of`` 的折叠口径展开成**声明位键清单**（长度必等于单元数；两口分叉由锁执法）。"""
    cluster_keys = _rule_a_cluster_keys()
    groups: dict[frozenset[str], list[Site]] = defaultdict(list)
    for s in sites:
        if w in s.words:
            groups[s.words].append(s)
    out: list[str] = []
    for members in groups.values():
        clustered = [m for m in members if (m.file, m.line, m.label.replace("t1:", "", 1)) in cluster_keys]
        plain = [m for m in members if m not in clustered]
        if len(clustered) >= 2:
            out.append("CLUSTER|" + "|".join(sorted(f"{m.file}#{m.label}" for m in clustered)))
            out.extend(f"{m.file}#{m.label}" for m in plain)
        else:
            out.extend(f"{m.file}#{m.label}" for m in members)
    out.extend(f"inline:{f}" for f in sorted(inline.get(w, ())))
    return out


def accounted_debt(
    extra: tuple[tuple[str, str], ...] = (),
    *,
    register: tuple[DeclaredUnit, ...] = INTENTIONAL_UNITS,
) -> tuple[int, int, int]:
    """(计账, raw, 名册抵销数)：raw 债 − 逐枚命中的登记（每词兜底留一枚声明位）。"""
    raw, sites, inline = compute_debt(extra)
    vocab = frozenset().union(*(s.words for s in sites)) if sites else frozenset()
    removed = 0
    for w in sorted(vocab):
        keys = _fold_unit_keys(w, sites, inline)
        if len(keys) < 2:
            continue
        keyset = set(keys)
        hits: set[str] = set()
        for entry in register:
            if entry.word == w and entry.site in keyset:
                hits.add(entry.site)
        removed += min(len(hits), len(keys) - 1)
    return raw - removed, raw, removed


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
    acct, raw, removed = accounted_debt()
    assert acct <= WORD_SITE_CEILING, (
        f"词面级独立声明债（计账）{acct} > 上限 {WORD_SITE_CEILING}（raw {raw}，名册抵销 {removed}）"
        "＝又长了未登记的抄位。修法三选一：①让第二处引用真身/登记指针（部分重合→共享登记处）；"
        "②确属有意——进 INTENTIONAL_UNITS 逐枚登记（word+site+owner+reason，通配与条款一律拒收）；"
        "③明细跑 --ledger；全等/子集重复不归本尺，归 test_trigger_word_copy_ratchet"
    )
    assert raw >= acct >= 0, f"名册抵销算出越界数（raw {raw} acct {acct}）＝口径坏"


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
    acct_base, _raw, _rem = accounted_debt()
    owner = _owner_home()
    rel = "plugins/bot_unified_runtime/domains/ops/_s53_poison_virtual_e.py"
    copy_debt, _, _ = compute_debt(extra=((rel, _synth_literal_table("S53_POISON_TRIGGER_WORDS", owner.words)),))
    ref_debt, _, _ = compute_debt(extra=((rel, _synth_derived_table("S53_POISON_TRIGGER_WORDS", "REGISTERED_HOME")),))
    assert copy_debt > ref_debt == base >= 0 and acct_base <= WORD_SITE_CEILING, (
        f"方向锁失效：手抄={copy_debt} 引用={ref_debt} 基线={base} 计账基线={acct_base} 上限={WORD_SITE_CEILING}"
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
# 名册四把牙（K-3 乙）：活性 / 逐枚干活 / 禁条款化 / 零缺省豁免
# ---------------------------------------------------------------------------


def test_fold_agrees_with_units_of() -> None:
    """两口径分叉锁：逐词声明位清单的长度必须恒等于 ``_units_of`` 的单元数。"""
    _raw, sites, inline = compute_debt()
    vocab = frozenset().union(*(s.words for s in sites)) if sites else frozenset()
    for w in sorted(vocab):
        assert len(_fold_unit_keys(w, sites, inline)) == _units_of(w, sites, inline), (
            f"词面 {w!r} 的折叠清单与单元数分叉＝名册键与账目两口径打架"
        )


def test_intentional_units_register_is_live_and_unique() -> None:
    """活性锁：每条登记必须命中本日现算里一枚真实声明位；虚设（已被归一/换了位置）即红。

    这是防「名册变永久垃圾场」的那把牙——债没了条目还占着格，下一枚同形新副本就会被
    静默放行，所以必须当场红，而不是留着当保险。
    """
    _raw, sites, inline = compute_debt()
    vocab = frozenset().union(*(s.words for s in sites)) if sites else frozenset()
    keys_by_word = {w: set(_fold_unit_keys(w, sites, inline)) for w in vocab}
    seen: set[tuple[str, str]] = set()
    for entry in INTENTIONAL_UNITS:
        pair = (entry.word, entry.site)
        assert pair not in seen, f"登记重复（一条词面×声明位最多登记一次）：{pair}"
        seen.add(pair)
        unit_keys = keys_by_word.get(entry.word, set())
        assert entry.site in unit_keys, (
            f"名册虚设：{entry.word!r} @ {entry.site} 不在本日现算的声明位清单里"
            f"（该位现存清单={sorted(unit_keys)[:6]}）——要么归一后忘了摘牌，要么键被换形态"
        )


def test_intentional_units_each_pulls_its_own_weight() -> None:
    """逐枚干活的锁：摘掉任意一条登记 ⇒ 计账数必 +1（无一装饰件，也不许多吃）。"""
    base_acct, _raw, _rem = accounted_debt()
    for index in range(len(INTENTIONAL_UNITS)):
        trimmed = INTENTIONAL_UNITS[:index] + INTENTIONAL_UNITS[index + 1 :]
        acct, _r, _m = accounted_debt(register=trimmed)
        assert acct == base_acct + 1, (
            f"摘掉第 {index} 条登记（{INTENTIONAL_UNITS[index].word!r}@..."
            f"）计账没动或动了不止一格＝该条没在干活或多消费了别的声明位"
        )


def test_intentional_units_are_not_blanket_clauses() -> None:
    """禁条款化锁：word 必须是单个词面、site 前缀合法且路径在盘、owner/reason 各写各的。"""
    reasons: list[str] = []
    for entry in INTENTIONAL_UNITS:
        assert entry.word and entry.word.strip() == entry.word, f"word 含空首尾或为空：{entry}"
        assert "|" not in entry.word and "、" not in entry.word and "," not in entry.word, (
            f"word 复数形态＝条款化雏形：{entry.word!r}"
        )
        if entry.site.startswith("CLUSTER|"):
            members = entry.site.removeprefix("CLUSTER|").split("|")
            assert len(members) >= 2, f"簇键成员不足两枚：{entry.site}"
            rels = [m.partition("#")[0] for m in members]
        elif entry.site.startswith("inline:"):
            rels = [entry.site.removeprefix("inline:")]
        elif "#" in entry.site:
            rels = [entry.site.partition("#")[0]]
        else:
            raise AssertionError(f"site 前缀不合法（真身位/内联/簇之外一律拒收）：{entry.site}")
        for rel in rels:
            assert (REPO_ROOT / rel).is_file(), f"登记指向不存在的文件：{rel}（{entry.word}）"
        assert entry.owner.strip(), f"owner 为空＝不知道谁的债不许登记：{entry.word}"
        assert len(entry.reason) >= 20, f"reason 短于 20 字符＝没写判据：{entry.word}"
        reasons.append(entry.reason)
    assert len(set(reasons)) == len(reasons), "两条登记共用一句判据＝这就是被禁的 blanket 条款"
    assert INTENTIONAL_UNITS, "首届登记不应为空——为空即 raw 债必须另找解释"


def test_poison_unregistered_copy_still_accounted() -> None:
    """注毒⑥（零缺省豁免）：手抄整表的虚拟新副本**不在名册里** ⇒ raw 与计账同步 +len(words)，
    名册不许顺着「词面眼熟」把未登记的新抄位一起放行。"""
    base_acct, base_raw, _rem = accounted_debt()
    owner = _owner_home()
    rel = "plugins/bot_unified_runtime/domains/ops/_s53_poison_virtual_f.py"
    src = _synth_literal_table("S53_POISON_TRIGGER_WORDS", owner.words)
    acct, raw, _m = accounted_debt(extra=((rel, src),))
    assert raw == base_raw + len(owner.words), "虚拟整表没进 raw＝取数口坏（与注毒①同前提）"
    assert acct == base_acct + len(owner.words), (
        f"未登记的新抄位被名册顺带豁免（计账 {base_acct}→{acct}，应 {base_acct + len(owner.words)}）"
        "＝逐枚登记退化成词面通配"
    )


def test_empty_register_reverts_to_raw_debt() -> None:
    """零缺省豁免的反证：把登记表清空 ⇒ 计账必回到 raw（今日的红原样可见，豁免不藏在判据里）。"""
    acct, raw, _rem = accounted_debt(register=())
    assert acct == raw, "空表仍降账＝豁免不在名册里、藏在判据中"


# ---------------------------------------------------------------------------
# CLI：--ledger 逐条明细（人读）／ --bless 打建议上限与历史行（归一后刷账用）
# ---------------------------------------------------------------------------


def ledger_stamp() -> str:
    """尺身份第三元：全部声明单元指纹（信息件，随 --ledger 打印，不参与断言）。"""
    _total, sites, _inline = current_debt()
    joined = "|".join(f"{s.file}:{s.line}:{s.label}" for s in sorted(sites))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def render_ledger(top: int = 60) -> list[str]:
    _total, sites, inline = current_debt()
    acct, raw, removed = accounted_debt()
    vocab = frozenset().union(*(s.words for s in sites)) if sites else frozenset()
    rows = []
    for w in sorted(vocab):
        u = _units_of(w, list(sites), inline)
        if u >= 2:
            rows.append((u, w))
    rows.sort(key=lambda r: (-r[0], r[1]))
    lines = [
        (
            f"词面级独立声明债：raw {raw}（记债词面 {len(rows)} 枚）｜计账 {acct}"
            f"（名册逐枚抵销 {removed}／登记 {len(INTENTIONAL_UNITS)} 条）｜上限 {WORD_SITE_CEILING}"
            f"；尺指纹 {ledger_stamp()}"
        ),
        "全等重复与整集子集不归本账（归 test_trigger_word_copy_ratchet），下列为部分重合/别名第二字段/内联重列/隐藏真身。",
    ]
    registered_by_word = defaultdict(list)
    for entry in INTENTIONAL_UNITS:
        registered_by_word[entry.word].append(entry.site)
    for u, w in rows[:top]:
        home_lines = [f"{s.file}:{s.line}:{s.label}:{s.kind}" for s in sites if w in s.words]
        inline_lines = [f"inline:{f}" for f in sorted(inline.get(w, ()))]
        lines.append(f"  {w!r} units={u}" + (f" 名册抵销={len(registered_by_word.get(w, ()))}" if registered_by_word.get(w) else ""))
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
    acct, raw, removed = accounted_debt()
    if "--bless" in argv:
        print(f"现算 raw = {raw}；计账 = {acct}（名册抵销 {removed}，登记 {len(INTENTIONAL_UNITS)} 条）")
        print(f'建议：WORD_SITE_CEILING = {acct} 且 AUDIT_HISTORY 追加 ("<今日YYYY-MM-DD>", {acct}),')
        print(f"尺指纹 = {ledger_stamp()}")
        print("⚠ 刷账前先看 --ledger：抵销数变了就是有枚登记位被换了形态或摘了牌，逐枚改判据、别改条款。")
        return 0
    print(
        f"计账债数 = {acct}（现算 raw {raw}，名册抵销 {removed}；上限 {WORD_SITE_CEILING}）；"
        "--ledger 看明细，--bless 看刷账建议"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
