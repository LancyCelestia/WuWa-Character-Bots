r"""S764 交付③——适配轴机器门判据原文（可粘贴：并入 `tests/test_workspace_manifest_gate.py`，
与 S727 件3 的 L-11 同门加腿，**禁另立第二件门**——DF 批在册条款）。

判据本体只吃**注入的取数口**（本文件不 import 生产件、不读盘 ⇒ 可被 %TEMP% 沙盒量具直接
exec 实测杀伤力；落仓时由门件提供真口）：

  decl            声明源真身的三面意图（dict 形态即可）：
                    EDGE_RANGE_POLICY   {"*": "same-major"} 之类的区间策略（键唯一 "*"＝缺省）
                    REQUIRE_OVERRIDES   tuple[dict]：{"consumer","provider","requires_min",
                                                      "requires_max_exclusive","why"}  pair 级例外
                    ADAPT_WAIVERS       tuple[dict]：{"consumer","provider","why","expires"}
                                                      显式「本边不钉」；expires=YYYY-MM-DD；只降不升
  ledger          仓内②指回账（docs/workspace-manifest.json 解析后的 dict）：
                    cross_library_edges = tuple/list[dict]，行含
                    {"consumer","provider","kind","requires_min","requires_max_exclusive","via"}
                    kind ∈ {"import-ast","protocol"}（S715 在册两值；import-ast 行手填＝门红，
                    由「账本行必须等于门内独立再派生」间接执法，见 p_adapt_ledger_matches_ast）
  one_manifests   {slug: 仓外① workspace-lib.manifest.json 解析 dict}（须含 "depends" 键，
                    行含 {"provider","requires_min","requires_max_exclusive"}；零依赖＝空列表，
                    **缺键＝投影脱漏，红**——fail-closed，禁把"没写"读成"没有"）
  computed_pairs  门内独立 AST 尺现算的 {(consumer_slug, provider_slug)}（口径逐字沿用 S744
                    §一：绝对 ImportFrom(level==0) 且目标可解析为仓内件；归属用板块声明源
                    最长前缀，解析口＝scripts/board_doc_sync.load_taxonomy，禁第二份板源扫描器；
                    双认领文件按无主处置、不计入——与 S744 fresh_walk 同判）
  now_date        注入的"今天"（datetime.date），豁免到期判定用它，禁读时钟（确定性）

两把反制腿（简报点名，缺一不可落）：
  ①「声明了但无人读」当场红 —— p_adapt_no_silent_fields（派生尺，S612 §5.3 L-11 同族，
     不另造机制：读点集＝判据函数体里的字符串下标与属性名，AST 现算，禁手抄名册）。
     另配一枚具体腿：REQUIRE_OVERRIDES 写了而账没照它落 ⇒ OVERRIDE-IGNORED（S612 注毒 C
     「kind 成对偷换全绿」那类病，按 pair 逐格堵死）。
  ②「删声明必须同批守恒」—— p_adapt_ledger_matches_ast 双向差集：
     盘上有边而账里无行且无有效豁免 ⇒ ADAPT-MISS；
     账里有行而盘上边已消失 ⇒ ADAPT-STALE（真断边要删行，悄悄删行必被 MISS 或 STALE 抓住）；
     行与豁免重叠 ⇒ ADAPT-DUP；豁免过期 ⇒ ADAPT-WAIVED-EXPIRED。
     恒等式显式打印（|computed| ＝ |行∩computed| ＋ |MISS|，豁免另账），沿用 S744 三账守恒
     与本仓棘轮「只降不升＋同批跟随」教训（台账 #49/#52 键形守恒先例）。

尺瞎自锁（S664「分母为 0 时判据不得恒真」＋ S744 SL-4 同型）：p_adapt_empty_roster_selflock。

环账（在册判定，不许升成常驻红门）：report_adapt_cycles 只产**进度读数**——本席实测
52 对构成单一巨型强连通（10 节点全入）、互为双向的库对 15 枚；判据权威＝S715 §四
「L-5 无环只能当拆库进度尺，不能当当前 HEAD 体检红门」。谁把环判升级成红门，等于
要求拆库先于声明，与本通道「先把账立起来」的 mandate 相反。
"""
from __future__ import annotations

import ast
import datetime
import inspect
from collections.abc import Callable, Iterable

KNOWN_POLICIES = frozenset({"same-major"})

#: 散文/溯源格豁免名册——**只准降不准升**（S612 §5.3 PROSE_KEYS 同族，新增豁免＝造新空转面）。
#: 边界申明（S612 §5.1 原样继承）：本尺只会假「有人读」、不会假「没人读」——结论只对 unread 集下。
PROSE_KEYS = frozenset({"notes", "statement", "generated_by", "why", "counterparty"})


def _next_major(version: str) -> str:
    a, _b, _c = version.split(".")
    return str(int(a) + 1) + ".0.0"


def _edge_rows(ledger: dict) -> list[dict]:
    rows = ledger.get("cross_library_edges")
    if rows is None:
        raise ValueError("账本畸形：②缺 cross_library_edges 键（生成器未填，拒绝当空集处理）")
    return list(rows)


def _policy_for(decl: dict, consumer: str, provider: str) -> tuple[str, dict | None]:
    pol = dict(decl.get("EDGE_RANGE_POLICY") or {})
    override = None
    for row in decl.get("REQUIRE_OVERRIDES") or ():
        if row.get("consumer") == consumer and row.get("provider") == provider:
            override = row
            break
    key = consumer + "->" + provider
    return pol.get(key, pol.get("*", "")), override


def expected_range(decl: dict, one_manifests: dict, consumer: str, provider: str) -> tuple[str, str, str]:
    """(requires_min, requires_max_exclusive, 依据)——策略与例外的唯一求值口（门与生成器同式，
    门侧独立复算：不同份抄写，同一份**语义**；落地时该函数收进声明源，门与生成器都 import 它，
    禁三处各写一份算法——那才是第二真身）。"""
    policy, override = _policy_for(decl, consumer, provider)
    if override is not None:
        return str(override["requires_min"]), str(override["requires_max_exclusive"]), "override"
    if policy not in KNOWN_POLICIES:
        raise ValueError("POLICY-UNKNOWN: " + repr(policy) + "（表外策略＝生成期拒，同 S727 RANGE_POLICY 教义）")
    f = one_manifests.get(provider)
    if f is None:
        raise ValueError("提供方①不在场: " + provider)
    vmin = str(f.get("version"))
    return vmin, _next_major(vmin), "policy:" + policy


# ────────────────────────── 腿②：删声明必须同批守恒 ──────────────────────────

def p_adapt_ledger_matches_ast(decl: dict, ledger: dict, computed_pairs: set,
                               one_manifests: dict, now_date: datetime.date) -> list[str]:
    problems: list[str] = []
    rows = _edge_rows(ledger)
    ast_pairs = {(str(r.get("consumer")), str(r.get("provider")))
                 for r in rows if str(r.get("kind")) == "import-ast"}
    proto_pairs = {(str(r.get("consumer")), str(r.get("provider")))
                   for r in rows if str(r.get("kind")) == "protocol"}
    bad_kind = sorted({str(r.get("kind")) for r in rows} - {"import-ast", "protocol"})
    for k in bad_kind:
        problems.append("ADAPT-BADKIND: kind=" + repr(k) + " 不在册（S715 两值之外＝伪造通道）")

    waivers: set = set()
    for w in decl.get("ADAPT_WAIVERS") or ():
        pair = (str(w.get("consumer")), str(w.get("provider")))
        waivers.add(pair)
        try:
            exp = datetime.date.fromisoformat(str(w.get("expires")))
        except ValueError:
            problems.append("ADAPT-WAIVER-NOEXPIRY " + pair[0] + "<-" + pair[1] + "：expires 非 ISO 日期（无理由到期的豁免＝永久假账）")
            continue
        if exp < now_date:
            problems.append("ADAPT-WAIVED-EXPIRED " + pair[0] + "<-" + pair[1] + "：豁免已到期 " + str(exp) + "（续期要同批补 why）")

    for pair in sorted(computed_pairs - ast_pairs - waivers):
        problems.append("ADAPT-MISS " + pair[0] + "<-" + pair[1] + "：盘上有边而账无行且无有效豁免（补行或补豁免，同批）")
    for pair in sorted(ast_pairs - computed_pairs):
        problems.append("ADAPT-STALE " + pair[0] + "<-" + pair[1] + "：账里有行而盘上边已消失（真断边要删行；悄悄删行必红在这）")
    for pair in sorted(ast_pairs & waivers):
        problems.append("ADAPT-DUP " + pair[0] + "<-" + pair[1] + "：行与豁免重叠（钉与不钉只能选一）")
    for pair in sorted(ast_pairs & proto_pairs):
        problems.append("ADAPT-DOUBLE-KIND " + pair[0] + "<-" + pair[1] + "：同对既有 import-ast 行又有 protocol 行")

    # 守恒恒等式：|computed| ＝ |行覆盖| ＋ |有效豁免| ＋ |MISS|（三分项互斥且穷尽）。
    # 本席首版漏了豁免项，被注毒台 T3a 当场打红（有效豁免被误判不平），照实记。
    covered = ast_pairs & computed_pairs
    waived_ct = len(waivers & computed_pairs)
    miss_ct = len(computed_pairs - ast_pairs - waivers)
    if len(covered) + waived_ct + miss_ct != len(computed_pairs):
        problems.append("ADAPT-IDENTITY: |覆盖" + str(len(covered)) + "|+|豁免" + str(waived_ct)
                        + "|+|MISS" + str(miss_ct) + "| ≠ |computed" + str(len(computed_pairs))
                        + "|——尺自身进不了三分互斥判定，报数")

    # 逐行区间复核（例外被无视＝"声明了但没人读"的最具体形态）
    for r in rows:
        if str(r.get("kind")) != "import-ast":
            continue
        c, p = str(r.get("consumer")), str(r.get("provider"))
        try:
            emin, emax, basis = expected_range(decl, one_manifests, c, p)
        except ValueError as exc:
            problems.append("ADAPT-RANGE-UNSAT " + c + "<-" + p + "：" + str(exc))
            continue
        if str(r.get("requires_min")) != emin or str(r.get("requires_max_exclusive")) != emax:
            problems.append("ADAPT-RANGE-DIVERGE " + c + "<-" + p + "：账记 [ "
                            + str(r.get("requires_min")) + " , " + str(r.get("requires_max_exclusive"))
                            + " ) ≠ 真身意图 [ " + emin + " , " + emax + " )（" + basis + "）")
    for ov in decl.get("REQUIRE_OVERRIDES") or ():
        c, p = str(ov.get("consumer")), str(ov.get("provider"))
        hit = [r for r in rows if str(r.get("consumer")) == c and str(r.get("provider")) == p
               and str(r.get("kind")) == "import-ast"]
        if not hit and (c, p) not in computed_pairs:
            problems.append("ADAPT-OVERRIDE-ORPHAN " + c + "<-" + p + "：例外指向不存在的边（删改不同批）")
        elif not str(ov.get("why", "")).strip():
            problems.append("ADAPT-OVERRIDE-NOWHY " + c + "<-" + p + "：偏离缺省却不写理由（S612 N-H 同族）")
    return problems


# ────────────────── 腿①·其一：①↔② 投影一致（manifest 侧有人真写） ──────────────────

def p_adapt_projections_agree(ledger: dict, one_manifests: dict) -> list[str]:
    problems: list[str] = []
    rows = [r for r in _edge_rows(ledger) if str(r.get("kind")) == "import-ast"]
    per_consumer: dict[str, set] = {}
    for r in rows:
        per_consumer.setdefault(str(r.get("consumer")), set()).add(
            (str(r.get("provider")), str(r.get("requires_min")), str(r.get("requires_max_exclusive"))))
    for slug, mf in sorted(one_manifests.items()):
        if "depends" not in mf:
            problems.append("ADAPT-DEPENDS-ABSENT " + slug + "：①无 depends 键（缺键≠零依赖；投影脱漏或被生成器覆盖回写丢）")
            continue
        seen = {(str(e.get("provider")), str(e.get("requires_min")), str(e.get("requires_max_exclusive")))
                for e in mf.get("depends") or ()}
        want = per_consumer.get(slug, set())
        for miss in sorted(want - seen):
            problems.append("ADAPT-PROJ-MISS " + slug + " → " + str(miss) + "：②有行而①自述缺（工厂未随批重刷）")
        for extra in sorted(seen - want):
            problems.append("ADAPT-PROJ-EXTRA " + slug + " → " + str(extra) + "：①自述有而②无（第二真身嫌疑）")
    return problems


# ────────────────── 腿①·其二：「在册无人读」派生尺（L-11 同族） ──────────────────

def _read_keys_from_sources(texts: Iterable[str]) -> set:
    """读点集＝判据源码里的字符串下标与属性名（AST 现算，禁手抄名册；S612 §5.1 尺 v2 原样）。
    已知上界松散：只会假「有人读」、不会假「没人读」——结论只对 unread 集下。
    读点形态两色都算：字符串下标 `d["k"]` 与 `.get("k")` 首参字符串常量——本门件通体用
    .get 形态，若只数下标会把所有键误判成「没人读」（本席首版栽在此处，自纠后记）。"""
    out: set = set()
    for src in texts:
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str):
                out.add(node.slice.value)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "get" and node.args \
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                out.add(node.args[0].value)
            elif isinstance(node, ast.Attribute):
                out.add(node.attr)
    return out


def p_adapt_no_silent_fields(schema_leaves: set, predicate_sources: Iterable[str]) -> list[str]:
    """声明面每一枚结构格都必须被某条判据读；读不到＝红（「填了＝假分母」）。"""
    read = _read_keys_from_sources(predicate_sources)
    return ["L11-SILENT " + str(k) + "：适配轴在册但没有任何判据读它（填了没人看＝假零）"
            for k in sorted(set(schema_leaves) - read - {"@schema"} - PROSE_KEYS)]


# ────────────────────────── 尺瞎自锁（空名册四态） ──────────────────────────

def p_adapt_empty_roster_selflock(ledger: dict, computed_pairs: set) -> list[str]:
    problems: list[str] = []
    rows = [r for r in _edge_rows(ledger) if str(r.get("kind")) == "import-ast"]
    if rows and not computed_pairs:
        problems.append("GATE-BLIND-AST：账里有行而现算边集为空——AST 尺瞎或树被搬空，禁放行")
    if computed_pairs and not rows:
        problems.append("PINS-DENOMINATOR-ZERO：现算有 " + str(len(computed_pairs))
                        + " 对边而声明为零——这是「没有声明面」，不是「没问题」（S744 同判上闸）")
    if not computed_pairs and not rows:
        problems.append("ADAPT-EMPTY-EMPTY：两本全零属尺瞎形状，禁止出漂亮空表")
    return problems


# ────────────────────────── 环账：进度尺，不是红门 ──────────────────────────

def report_adapt_cycles(ledger: dict) -> list[str]:
    pairs = {(str(r.get("consumer")), str(r.get("provider")))
             for r in _edge_rows(ledger) if str(r.get("kind")) == "import-ast"}
    nodes = sorted({n for e in pairs for n in e})
    adj = {n: [b for a, b in pairs if a == n] for n in nodes}
    index: dict = {}
    low: dict = {}
    onstack: dict = {}
    stack: list = []
    sccs: list = []
    counter = [0]

    def strong(v: str) -> None:  # 迭代式 Tarjan，防深递归
        work = [(v, 0)]
        while work:
            cur, i = work[-1]
            if i == 0:
                index[cur] = low[cur] = counter[0]
                counter[0] += 1
                stack.append(cur)
                onstack[cur] = True
            advanced = False
            for j in range(i, len(adj[cur])):
                w = adj[cur][j]
                if w not in index:
                    work[-1] = (cur, j + 1)
                    work.append((w, 0))
                    advanced = True
                    break
                if onstack.get(w):
                    low[cur] = min(low[cur], index[w])
            if advanced:
                continue
            if low[cur] == index[cur]:
                comp = []
                while True:
                    w = stack.pop()
                    onstack[w] = False
                    comp.append(w)
                    if w == cur:
                        break
                sccs.append(comp)
            work.pop()
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[cur])

    for n in nodes:
        if n not in index:
            strong(n)
    big = [c for c in sccs if len(c) > 1]
    mutual = sorted({(a, b) for (a, b) in pairs if (b, a) in pairs and a < b})
    lines = ["CYCLE-PROGRESS 非平凡SCC=" + str(len(big)) +
             " 覆盖节点=" + str(sum(len(c) for c in big)) + "/" + str(len(nodes)) +
             " 双向对=" + str(len(mutual)) + "（破环集是拆库次序问题，本读数只报进度、不作红门——S715 §四在册）"]
    return lines


# ────────────────────────── 落仓时的组装示例（门件内注释即可） ──────────────────────────

def assemble_predicate_sources() -> list:
    """落仓形态：读点尺吃「门件里全部判据与其 helper」的源码（inspect 现取，禁手维护名册）。
    不收 helper 会让只在 helper 里读的键被误判空转——与「只数下标」同型的尺瞎。"""
    mod = inspect.getmodule(inspect.currentframe())
    return [inspect.getsource(fn) for name, fn in vars(mod).items()
            if isinstance(fn, Callable) and getattr(fn, "__module__", None) == mod.__name__
            and name != "assemble_predicate_sources"]


SCHEMA_LEAVES_ADAPT = {
    "cross_library_edges", "consumer", "provider", "kind",
    "requires_min", "requires_max_exclusive",
    "depends",
    "EDGE_RANGE_POLICY", "REQUIRE_OVERRIDES", "ADAPT_WAIVERS", "expires",
}

if __name__ == "__main__":
    # 自检：本文件自身可 exec（沙盒量具 s764-teeth.py 走的就是这条路）。
    import sys
    print("gate-legs self-exec OK; policies=" + ",".join(sorted(KNOWN_POLICIES)))
    sys.exit(0)
