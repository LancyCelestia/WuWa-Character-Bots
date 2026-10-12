"""第 14 项接线锁：库侧主题↔本地域词表那把**缺口尺必须真的被中央出口调用**.

钉的是「接线」这一件事。判据本体（两侧相减）今天已有真身
``plugins/bot_unified_runtime/domains/location/knowledge/kb_wiki.py``
::``topics_without_local_domain_anchor``，本窗之前全仓只有
``tests/test_kb_list_domain_gate.py`` 在读它、运行期零消费方 ⇒ 新补一个 KB 语料域
而没人往 ``question_intent`` 的本地域词表加锚点时，运行/发版前不会有任何人点名，
缺口静默存在（＝台账 #73「现实知识面」的复发机制）。本窗把它接进
``scripts/pre_restart_check.py`` 第 14 项，本件锁那条接线。

四条腿，一条比一条难糊：

① **AST 调用图**（不是「函数存在」，也不是「文件里搜得到这个名字」）：从 ``run_all``
   出发沿调用图走，``check_kb_domain_anchor`` 必须**真的以 Call 节点**调起五枚真身
   ——尺本体、库侧名单、kb_dir 真身、装载口、脱敏件。文本 grep 过不了这条腿：注毒
   副本里那些名字仍留在 docstring/注释里（字面可见），调用节点没了 ⇒ 判据即红。
② **注毒自证**：两发摘法（摘掉尺的调用／摘掉 ``run_all`` 注册行）⇒ ① 必红。全部打在
   tmp 副本上，真身文件前后 sha256 自证零接触。
③ **不许长出第二把尺**：中央出口不得直接加载锚点真身 ``DOMAIN_TERMS``（那是绕过尺
   自己相减），且 ``check_kb_domain_anchor`` 体内 ``not in`` 比较数与 ``FAIL`` 标识符
   加载数都为 0——结构上就产不出阻断态（报警不阻断，照第 7 项 napcat 口径）。
④ **实跑行为**：有缺口→SKIP 且逐域点名；无缺口→PASS；库根未配置/读不到语料→SKIP
   （读不到＝没有证据，不许说得像"没有缺口"）；读数不漏盘符路径（另配一发"摘掉脱敏
   必泄漏"的注毒腿自证这条锁有牙）；直载登记过的 sys.modules 条目用完必须摘干净。

⑤ **派生腿（2026-10-12 补锚波）**：缺口既然被中央出口点名了，就得有人真的被它拦住——
   本腿拿**库侧名册现算**判「在册语料域必须有本地域锚点」，域名一律来自取数口
   （``iter_corpus_topic_names``），锚点一律由唯一一把尺相减得出。🔴 这里**不写死
   「共 N 域／缺 M 枚」**（规则 10：名册一长就恒假红），只写集合关系。
   域可以按**主人在册裁定**点名豁免（``_LOCAL_ANCHOR_RULE_EXEMPTIONS``），但豁免不是
   一句注释就完事：①豁免名必须今天真在名册里、②必须真是尺报出的缺口（不许拿豁免
   掩盖"已经补好了却忘了删豁免"）、③每一枚豁免都要**现读出处文件里的判据原文还在**
   ——裁定一旦被撤，豁免自动过期、本腿立即红，逼人来真裁一道。
   为什么"有货"不能靠名字判：给一个空域打锚＝把本地门打开却永远检索不到，比缺锚更坏
   （本仓两种实锤形态＝「空分区不渲染⇒把没查到讲成不存在」与「开关 True 但那条路
   永远走不到」）。取数口读到空集合由 ``test_corpus_roster_fetch_port_is_not_vacuous``
   当场判红——「没有样本」不等于「通过」。

⑥ **禁词腿**：强档（命中即定罪的那一档，也是 ``DOMAIN_TERMS`` 的外部域唯一派生口）
   不得收通用词。判据按一份**点名禁词表**（``GENERIC_TERMS_BANNED_IN_STRONG``）判——
   禁词表写死是合法的，它不是会随代码漂的计数。同一腿自带反空转：强档整档为空
   ＝本腿无从判起，直接红。
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import load_runtime_config as lrc
from scripts import pre_restart_check as prc

PRC_FILE = PROJECT_ROOT / "scripts" / "pre_restart_check.py"
CHECK_ID = "kb_domain_anchor"
CHECK_FUNC = "check_kb_domain_anchor"
LOADER_FUNC = "kb_domain_anchor_ruler"
GAP_RULER = "topics_without_local_domain_anchor"
DRIVE_PATH_RE = re.compile(r"[A-Za-z]:[\\/]")

#: 本格必须真的调起的五枚真身符号（按末段名比对：``kb_wiki.topics_…`` 与
#: ``access.modules["plain_text"].redact_local_secrets`` 都算命中，改收件人/改名即红）。
REQUIRED_SYMBOLS: tuple[str, ...] = (
    GAP_RULER,          # 两侧相减的尺（唯一一把）
    "iter_corpus_topic_names",  # 库侧在册主题现算
    "kb_paths",         # kb_dir 相对段不在中央出口里复制一份
    LOADER_FUNC,        # 按文件路径直载尺的装载口
    "redact_local_secrets",  # 出格脱敏
)

GAP_TOPIC = "某新游戏域甲"  # 绝不在本地域词表里（与既有门同名用词，不新造）


# ---------------------------------------------------------------------------
# AST 判据本体（①与②共用同一把尺：注毒腿跑的就是这个函数，不是另一份实现）
# ---------------------------------------------------------------------------

def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):  # 链式调用取最左
        return _dotted(node.func)
    return ""


def _direct_callees(node: ast.AST) -> set[str]:
    """本函数体内的**直接调用**点分名集合.

    嵌套 def/lambda/class 的体另算，绝不「体内出现即归因」（facets_candidate_dump
    踩过的错归因形状）。
    """
    found: set[str] = set()

    def visit(current: ast.AST) -> None:
        for child in ast.iter_child_nodes(current):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
                continue
            if isinstance(child, ast.Call):
                dotted = _dotted(child.func)
                if dotted:
                    found.add(dotted)
            visit(child)

    visit(node)
    return found


def _reachable_from(tree: ast.Module, start: str = "run_all") -> dict[str, set[str]]:
    """从 ``run_all`` 出发沿调用图可达的顶层函数 → 各自的直接调用集合.

    可达性是这条腿的牙齿：尺的调用被搬进一个 ``run_all`` 走不到的函数、或注册行被摘，
    这里就查不出它——「写了但没接上」与「根本没写」同罪。
    """
    edges = {
        fn.name: _direct_callees(fn)
        for fn in tree.body
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    seen: set[str] = set()
    queue = [start]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        for callee in edges.get(current, set()):
            leaf = callee.rsplit(".", 1)[-1]
            if leaf in edges and leaf not in seen:
                queue.append(leaf)
    return {name: edges[name] for name in seen if name in edges}


def _wiring_evidence(source: str) -> dict[str, set[str]]:
    """现算「中央出口里哪些可达函数真的调起了哪几枚真身符号」——判据只此一份."""
    evidence: dict[str, set[str]] = {}
    for func, callees in _reachable_from(ast.parse(source)).items():
        leaves = {dotted.rsplit(".", 1)[-1] for dotted in callees}
        hit = {symbol for symbol in REQUIRED_SYMBOLS if symbol in leaves}
        if hit:
            evidence[func] = hit
    return evidence


def _assert_wired(evidence: dict[str, set[str]], *, where: str) -> None:
    if CHECK_FUNC not in evidence:
        raise AssertionError(
            f"{where}：run_all 可达面里没有任何函数调起缺口尺——接线不在（可达且被点到的函数"
            f"只有 {sorted(evidence) or '（无）'}）。本项要的是中央出口**真的调用**它，"
            "不是文件里搜得到这个名字。"
        )
    absent = [symbol for symbol in REQUIRED_SYMBOLS if symbol not in evidence[CHECK_FUNC]]
    if absent:
        raise AssertionError(f"{where}：{CHECK_FUNC} 少调了 {absent}（五枚真身符号必须全在这条链上）")


def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"中央出口里找不到函数 {name}（被改名或删掉了？）")


# ---------------------------------------------------------------------------
# ① 接线本体
# ---------------------------------------------------------------------------

def test_gap_ruler_is_really_called_from_the_central_exit() -> None:
    _assert_wired(_wiring_evidence(PRC_FILE.read_text(encoding="utf-8")), where="真身")


def test_check_is_declared_and_registered_in_order() -> None:
    """在册声明侧与 run_all 注册序一起跟着（派生式判据，不写死总项数）."""
    declared = prc.declared_item_ids()
    assert CHECK_ID in declared, f"{CHECK_ID} 没进 docstring 编号在册清单：{declared}"
    # 2026-10-04 跟随：原此处钉 `declared[-1] == CHECK_ID`（「本项排队尾」）——第 15 项
    # entry_chain 正确追加后队尾必然漂移，与本件 ① 的 AST 可达锁无关。整序仍由
    # tests/test_pre_restart_check.py::test_main_exit_code_and_json_structure
    # （run_all 交出的 id 序 == declared_item_ids()）与
    # tests/test_pre_restart_entry_chain.py（同一判据 + 新项在册）守住，不降标准。
    run_all_calls = _reachable_from(ast.parse(PRC_FILE.read_text(encoding="utf-8")), "run_all")["run_all"]
    assert any(call.rsplit(".", 1)[-1] == CHECK_FUNC for call in run_all_calls), (
        f"run_all 没把 {CHECK_FUNC} 注册进去（在册却不可达＝假接线）：{sorted(run_all_calls)}"
    )


# ---------------------------------------------------------------------------
# ② 注毒自证：摘掉接线 ⇒ ① 必红（全打在 tmp 副本上，真身零接触）
# ---------------------------------------------------------------------------

CALL_NEEDLE = "list(kb_wiki.topics_without_local_domain_anchor(topics))"
REGISTER_NEEDLE = "        check_kb_domain_anchor(env, project_root),\n"


def test_poison_dropping_the_wiring_turns_the_lock_red() -> None:
    before = hashlib.sha256(PRC_FILE.read_bytes()).hexdigest()
    source = PRC_FILE.read_text(encoding="utf-8")
    for label, needle in (("尺调用", CALL_NEEDLE), ("注册行", REGISTER_NEEDLE)):
        assert source.count(needle) == 1, f"注毒锚点失配（{label}）：中央出口已变形，请同步更新本锁"

    poison_a = source.replace(CALL_NEEDLE, "[]  # 注毒：尺的调用被摘掉")
    poison_b = source.replace(REGISTER_NEEDLE, "")
    # 两发都必须「名字还在文本里」，否则证不出 AST 腿比 grep 腿强（那才是本锁的形状）
    assert GAP_RULER in poison_a and CHECK_FUNC in poison_b

    for label, poisoned in (("A 摘掉尺调用", poison_a), ("B 摘掉注册行", poison_b)):
        ast.parse(poisoned)  # 注毒必须是合法源码，否则红在语法上、说明不了判据抓到了越权
        evidence = _wiring_evidence(poisoned)
        with pytest.raises(AssertionError) as boom:
            _assert_wired(evidence, where=f"注毒 {label}")
        print(f"[注毒自证 {label}] 锁即红：{str(boom.value).splitlines()[0]}")

    assert hashlib.sha256(PRC_FILE.read_bytes()).hexdigest() == before, "注毒腿碰到了真身文件"


# ---------------------------------------------------------------------------
# ③ 不许长出第二把尺 / 不许阻断
# ---------------------------------------------------------------------------

def test_central_exit_does_not_grow_a_second_gap_ruler() -> None:
    tree = ast.parse(PRC_FILE.read_text(encoding="utf-8"))
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "DOMAIN_TERMS" not in identifiers, (
        "中央出口直接加载了锚点真身 DOMAIN_TERMS＝在这里自己相减（第二把尺）。"
        "两侧相减只准走 kb_wiki.topics_without_local_domain_anchor。"
    )
    body = _function_node(tree, CHECK_FUNC)
    subtract = [
        node for node in ast.walk(body)
        if isinstance(node, ast.Compare) and any(isinstance(op, ast.NotIn) for op in node.ops)
    ]
    assert not subtract, f"{CHECK_FUNC} 体内 {len(subtract)} 处 `not in`＝本地重算了缺口判据"
    loads = {node.id for node in ast.walk(body) if isinstance(node, ast.Name)}
    assert "FAIL" not in loads, f"{CHECK_FUNC} 加载了 FAIL＝本项会阻断重启（口径＝报警/点名不阻断）"
    assert "SKIP" in loads and "PASS" in loads, "本格连 SKIP/PASS 都不加载了？不阻断的形态必须还在"


def test_corpus_roster_is_the_full_scan_not_a_bounded_window() -> None:
    """有界窗口会少报缺口＝假绿：全量读的口径必须显式在册（缺省 None＝不设窗口）."""
    source = PRC_FILE.read_text(encoding="utf-8")
    assert re.search(r"^KB_CORPUS_SCAN_LIMIT: int \| None = None$", source, re.MULTILINE), (
        "KB_CORPUS_SCAN_LIMIT 不见了或被改成有界窗口：documents.jsonl 按域聚簇、新域多在"
        "尾部，窗口读数会漏缺口（现算 20000 行窗口只报得出 1/5 枚）"
    )
    assert "scan_limit=KB_CORPUS_SCAN_LIMIT" in source, "主题名单没按在册口径取数（换成隐式缺省就没人知道为什么）"


# ---------------------------------------------------------------------------
# ④ 实跑行为
# ---------------------------------------------------------------------------

def _project(tmp_path: Path, *, wiki_root: Path | None) -> Path:
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    lines = [f"BOT_RUNTIME_DATA_DIR={root / 'rt'}"]
    if wiki_root is not None:
        lines.append(f"BOT_KB_WIKI_ROOT={wiki_root}")
    (root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _corpus(wiki_root: Path, topics: list[str]) -> Path:
    kb_dir = wiki_root / "crawl_output" / "knowledge_base"
    kb_dir.mkdir(parents=True, exist_ok=True)
    (kb_dir / "documents.jsonl").write_text(
        "".join(
            json.dumps({"id": f"{topic}/moegirl/条目__{i}", "topic": topic}, ensure_ascii=False) + "\n"
            for i, topic in enumerate(topics)
        ),
        encoding="utf-8",
    )
    return kb_dir


@pytest.fixture(scope="module")
def anchor_term() -> str:
    """一枚真在本地域词表里的锚点：现取自真身，不在测试里手抄游戏名（规则 10）."""
    with prc.kb_domain_anchor_ruler(prc.PROJECT_ROOT) as access:
        assert access.modules is not None, f"尺装不上：{access.unavailable}"
        terms = tuple(access.modules["kb_wiki"].local_domain_anchor_terms())
    assert terms, "本地域词表读不出来，本件前提不成立"
    return terms[0]


def test_gap_makes_the_central_exit_name_it_and_never_blocks(tmp_path: Path, anchor_term: str) -> None:
    wiki_root = tmp_path / "wiki"
    _corpus(wiki_root, [anchor_term, GAP_TOPIC])
    root = _project(tmp_path, wiki_root=wiki_root)
    result = prc.check_kb_domain_anchor(prc.load_env(root), root)
    assert result.status == prc.SKIP, f"缺口只准点名不准阻断（今天给了 {result.status}）"
    assert GAP_TOPIC in result.message, f"缺口没被点名：{result.message}"
    assert anchor_term not in result.message, f"有锚点的域被误点名：{result.message}"
    assert "不阻断" in result.message
    assert GAP_RULER in result.fix_hint, "修复指引没把唯一一把尺点名（有人会在别处再写一把）"


def test_full_coverage_passes(tmp_path: Path, anchor_term: str) -> None:
    _corpus(tmp_path / "wiki", [anchor_term, anchor_term])  # 重复域由尺自己收口
    root = _project(tmp_path, wiki_root=tmp_path / "wiki")
    result = prc.check_kb_domain_anchor(prc.load_env(root), root)
    assert result.status == prc.PASS, f"两侧对齐却给了非 PASS：{result.status}｜{result.message}"
    assert "全部有本地域锚点" in result.message
    assert GAP_TOPIC not in result.message


def test_absent_corpus_skips_instead_of_claiming_no_gap(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    root = _project(tmp_path, wiki_root=tmp_path / "wiki")
    result = prc.check_kb_domain_anchor(prc.load_env(root), root)
    assert result.status == prc.SKIP
    assert "没有证据" in result.message, f"读不到语料却没说「没有证据」＝在假绿：{result.message}"
    assert "全部有本地域锚点" not in result.message


def test_unconfigured_wiki_root_skips(tmp_path: Path) -> None:
    result = prc.check_kb_domain_anchor(prc.load_env(_project(tmp_path, wiki_root=None)), tmp_path)
    assert result.status == prc.SKIP
    assert "BOT_KB_WIKI_ROOT" in result.message


def test_readings_do_not_leak_drive_letter_paths(tmp_path: Path) -> None:
    """绝对路径真的进读数的那条腿（documents.jsonl 缺失时报 kb_dir）必须过脱敏."""
    wiki_root = tmp_path / "wiki root"
    (wiki_root / "crawl_output" / "knowledge_base").mkdir(parents=True)
    root = _project(tmp_path, wiki_root=wiki_root)
    result = prc.check_kb_domain_anchor(prc.load_env(root), root)
    assert result.status == prc.SKIP
    if not DRIVE_PATH_RE.search(str(tmp_path)):  # tmp 不带盘符时这条腿无从判起
        pytest.skip("本环境 tmp_path 不含盘符路径，泄漏判据不适用")
    leaked = [f for f in (result.name, result.message, result.fix_hint) if DRIVE_PATH_RE.search(f)]
    assert not leaked, f"读数漏出盘符路径（脱敏没在这条链上）：{leaked}"
    assert str(tmp_path) not in result.message


def test_poisoned_redactor_would_leak_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """上一条锁的注毒腿：把脱敏件换成直通函数 ⇒ 盘符必泄漏（证明那条锁有牙）."""
    wiki_root = tmp_path / "wiki"
    (wiki_root / "crawl_output" / "knowledge_base").mkdir(parents=True)
    root = _project(tmp_path, wiki_root=wiki_root)
    real_loader = prc.kb_domain_anchor_ruler

    @contextmanager
    def passthrough_loader(code_root: Path) -> Iterator[prc.KbDomainAnchorRuler]:
        with real_loader(code_root) as access:
            if access.modules is None:
                yield access
                return
            modules = dict(access.modules)
            modules["plain_text"] = type("Passthrough", (), {"redact_local_secrets": staticmethod(lambda t: t)})()
            yield prc.KbDomainAnchorRuler(modules, access.unavailable)

    if not DRIVE_PATH_RE.search(str(tmp_path)):
        pytest.skip("本环境 tmp_path 不含盘符路径，泄漏判据不适用")
    monkeypatch.setattr(prc, "kb_domain_anchor_ruler", passthrough_loader)
    result = prc.check_kb_domain_anchor(prc.load_env(root), root)
    assert DRIVE_PATH_RE.search(result.message), (
        f"摘掉脱敏后读数仍不含盘符＝那条盘符锁是假绿锁（或本格根本没把路径放进读数）：{result.message}"
    )


def test_loader_leaves_no_sys_modules_residue(tmp_path: Path) -> None:
    """直载登记过的名字必须逐枚摘干净（残留哑模块会被之后的真 import 当正品领走）."""
    wiki_root = tmp_path / "wiki"
    _corpus(wiki_root, [GAP_TOPIC])
    root = _project(tmp_path, wiki_root=wiki_root)
    before = set(sys.modules)
    result = prc.check_kb_domain_anchor(prc.load_env(root), root)
    added = sorted(set(sys.modules) - before)
    assert not added, f"直载往 sys.modules 留下了未摘除的条目：{added}"
    assert result.status == prc.SKIP and GAP_TOPIC in result.message


# ---------------------------------------------------------------------------
# ⑤ 派生腿：库侧在册语料域必须有本地域锚点（名册现算，绝不写死「共 N 域缺 M 枚」）
# ---------------------------------------------------------------------------

#: 按主人在册裁定点名豁免的域 → 该裁定的**出处**（文件 + 必须仍在册的判据原文片段）。
#: 豁免只按字面域名点名（不是通配、不是整域放行），且每枚都要能被现读复核：
#: 出处判据一旦被撤行，本表这行立即失去效力、派生腿转红，逼着人来真裁一道。
#:
#: 🔴 **下面这一枚不是「库里无货」那一型**（别记错成同一条纪律）：2026-10-12 现算两本名册
#: 都读得到它——语料导出侧（``documents.jsonl`` 逐行现算，取数口＝尺入参那本库侧 topic 名册）
#: 与仓侧接货台账侧（``knowledge_docs`` 按 topic 实读 GROUP BY）都点名该域成批在库、正文非空，
#: 逐域读数走 ``python scripts/knowledge_progress.py``（名册对榫腿）与体检格第 14 项现算，
#: 本件不抄数（规则 10）。它缺锚**纯粹因为主人点名排除**（「明日方舟·终末地」不随「明日方舟」
#: 扩面进本地域，出处即下面三条仍在册的判据原文），而这三条判据是**用户裁定的执法腿**、
#: 不在任何补锚席的写面里 ⇒ 补锚＝同批撤用户的裁定，只能由用户裁一道，不许席位借道静吃。
#: 因此本表把它按名点名、并把缺口继续如实挂在屏幕上；哪天裁定撤了，这三段原文一消失本腿即转红。
_LOCAL_ANCHOR_RULE_EXEMPTIONS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "明日方舟：终末地",
        (
            ("tests/test_question_intent.py", "def test_endminland_is_still_not_a_local_domain_term"),
            ('tests/test_question_intent.py', 'not any("终末地" in term for term in _qi.DOMAIN_TERMS)'),
            ("tests/test_sdd9_n3re.py", 'not any("终末地" in term for term in DOMAIN_TERMS)'),
        ),
    ),
)

#: 强档点名禁词表（写死合法：它是一份裁定口径，不是会随代码漂的计数）。
#: 收的是「命中即分流、会把别的域一起劫走」的通用汉语词——本仓的分档纪律把它们判在
#: medium/weak（见 ``search_intent`` 词表段注释「弱档永不单独成判」），因此它们出现在
#: 强档那一刻就是越权。`二游`/`二次元游戏` 这类**总称**不在此表：它们不劫走某一具体域的
#: 语料、且是已在册转正的条目，本表不去改已裁过的档。
GENERIC_TERMS_BANNED_IN_STRONG: frozenset[str] = frozenset(
    {
        "角色", "剧情", "更新", "攻略", "活动", "版本", "武器", "装备", "强度",
        "排名", "阵容", "攻略组", "声优", "抽卡", "卡池", "保底", "复刻", "前瞻",
        "深渊", "日常", "周本", "月卡", "公测", "开服", "怎么玩", "好玩", "好看",
        "什么时候", "厉害", "值得吗", "是谁",
    }
)


def _kb_wiki_root() -> str:
    """库根＝生产同构装载口现读（唯一被认可的取线上值的通道；本件不碰 .env 文本）。"""
    cfg = lrc.load_runtime_config(required=False)
    return str(getattr(cfg, "bot_kb_wiki_root", "") or "").strip()


def _corpus_roster_and_gaps() -> tuple[list[str], list[str]]:
    """现算「库侧在册语料域」与「其中缺锚的那几枚」——两侧都只从真身取。

    取数口＝尺本体（``iter_corpus_topic_names`` + ``topics_without_local_domain_anchor``），
    口径＝中央出口在册的 ``KB_CORPUS_SCAN_LIMIT``（None＝全量；有界窗口会少报缺口＝假绿，
    已由 ``test_corpus_roster_is_the_full_scan_not_a_bounded_window`` 钉住）。
    """
    wiki_root = _kb_wiki_root()
    if not wiki_root:
        pytest.fail(
            "线上库根取不到值（装载口回空）——本腿的派生判据没有名册可算，"
            "「没有样本」不等于「通过」，按反空转前置当场判红。"
        )
    with prc.kb_domain_anchor_ruler(prc.PROJECT_ROOT) as access:
        assert access.modules is not None, f"尺装不上：{access.unavailable}"
        kb_wiki = access.modules["kb_wiki"]
        kb_dir = kb_wiki.kb_paths(types.SimpleNamespace(bot_kb_wiki_root=wiki_root))[1]
        if not (kb_dir / "documents.jsonl").is_file():
            pytest.fail(
                f"取数口指不到语料（{kb_dir} 下没有 documents.jsonl）——本腿无从判起，"
                "判红而不是判过（台账 #51★「没检索禁写它没有」的同一条纪律用在门上）。"
            )
        roster = list(kb_wiki.iter_corpus_topic_names(kb_dir, scan_limit=prc.KB_CORPUS_SCAN_LIMIT))
        gaps = list(kb_wiki.topics_without_local_domain_anchor(roster))
    return roster, gaps


def test_corpus_roster_fetch_port_is_not_vacuous() -> None:
    """反空转前置：取数口读到空名册＝当场红（派生腿没有样本时最容易伪装成通过）。"""
    roster, _ = _corpus_roster_and_gaps()
    assert roster, "库侧在册语料域读出空集合：本件 ⑤ 的每一条派生判据都会退化成恒真"


def test_in_library_corpus_domains_carry_a_local_anchor() -> None:
    """库里确有货的域必须有本地域锚点——判据是集合关系，不含任何写死的总数。"""
    roster, gaps = _corpus_roster_and_gaps()
    assert roster, "取数口读出空名册＝本腿退化成恒真（反空转前置，与上一条腿同一纪律）"
    exempt = {name for name, _ in _LOCAL_ANCHOR_RULE_EXEMPTIONS}
    unexcused = [topic for topic in gaps if topic not in exempt]
    assert not unexcused, (
        f"{unexcused} 在库里躺着、本地域词表却认不出它 ⇒ 这些域的题既不判 LOCAL_KNOWLEDGE、"
        "也走不到「本地优先、低置信才补网」（资料明明躺着却被推去联网）。"
        "补锚只准进真身一处：外部域＝search_intent.ACG_DOMAIN_TERMS['game'][strong]"
        "（DOMAIN_TERMS 由它现取），自有设定＝question_intent._SHOREKEEPER_DOMAIN_TERMS。"
    )


def test_exemptions_are_ruled_not_convenient() -> None:
    """豁免册三查：今天在库里／今天真是缺口／出处判据原文仍在册——一条不满足即红。"""
    roster, gaps = _corpus_roster_and_gaps()
    for topic, citations in _LOCAL_ANCHOR_RULE_EXEMPTIONS:
        assert topic in roster, (
            f"豁免册里的 {topic} 今天不在库侧名册上：这条豁免已无主，请删（留着＝藏污处）"
        )
        assert topic in gaps, (
            f"豁免册里的 {topic} 已经有锚点却还挂在豁免上：豁免过期，请删（否则它会在"
            "锚点被摘掉的那一刻重新变成'合法缺口'）"
        )
        assert citations, f"{topic} 的豁免一条出处都没有＝拿豁免盖真缺口"
        for rel_path, needle in citations:
            path = PROJECT_ROOT / rel_path
            assert path.is_file(), f"{topic} 的豁免出处文件不见了：{rel_path}"
            assert needle in path.read_text(encoding="utf-8"), (
                f"{topic} 的豁免出处判据在 {rel_path} 里已查不到原文："
                "裁定一旦被撤，豁免就失去效力——要么补锚、要么重新落一道裁定，不许静默延续"
            )


def test_strong_tier_terms_are_not_generic_words() -> None:
    """强档词条不得含通用词（命中即分流会把别的域一起劫走）；禁词表点名、写死合法。"""
    with prc.kb_domain_anchor_ruler(prc.PROJECT_ROOT) as access:
        assert access.modules is not None, f"词表装不上：{access.unavailable}"
        registry = access.modules["search_intent"].ACG_DOMAIN_TERMS
        strong = {
            term
            for tiers in registry.values()
            for term in tiers[access.modules["search_intent"].ACG_TIER_STRONG]
        }
    assert strong, "强档整档为空＝本腿无从判起（反空转：档被搬空不是'通过'）"
    offenders = sorted(strong & GENERIC_TERMS_BANNED_IN_STRONG)
    assert not offenders, (
        f"通用词 {offenders} 进了强档：强档＝命中即定罪，且 game 强档还是 DOMAIN_TERMS 的"
        "外部域唯一派生口，通用词进这里会把「谁是最强的角色」这类题连别的域一起劫进本地门。"
    )
