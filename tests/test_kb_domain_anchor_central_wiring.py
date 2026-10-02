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
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import pre_restart_check as prc  # noqa: E402

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
    assert declared[-1] == CHECK_ID, f"本项应排在在册清单队尾：{declared}"
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
