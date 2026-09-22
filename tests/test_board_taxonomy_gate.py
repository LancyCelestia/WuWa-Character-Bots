"""十板块文档树常驻门（板块层一致性，2026-09-21 用户裁定「一处变更、处处跟随」）。

覆盖四件事，任一破坏即红：

1. **结构自洽**：板块数、id 唯一、二级 id 前缀、slug 命名、正文段完整。
2. **活性覆盖**：代码里每一个 RouteKind 席位与每一个帮助主题都必须**恰好**被一个
   二级功能认领；板块树认领了代码里不存在的席位同样红（存在性锁不算数）。
3. **实现路径可解析**：所有 `impl_paths` 指向的仓库路径必须真实存在。
4. **生成物同步**：`scripts/board_doc_sync.py --check` 退出码必须为 0
   （代码改了而 `docs/boards/**` 没重算 ⇒ 红）。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import board_doc_sync as bds
import doc_fact_discipline as dfd
import spec_gates_census as sc

BOARDS_DIR = ROOT / "docs" / "boards"
EXPECTED_BOARD_COUNT = 10
_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# --- G-T2 / G-T3 面 A 起点基线（席 T-GATES 2026-09-22 立，手写字面量、只准降）-----------
#: 复跑：`PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 python scripts/spec_gates_census.py --report`
T2_CEILING = 1
T3_MANAGED_CEILING = 226
#: G-T2 管辖面地板（现算比对页 228；塌陷＝门空跑）
MIN_T2_PAGES = 200
AUDIT_HISTORY_T2: tuple[tuple[str, int], ...] = (("2026-09-22", 1),)
AUDIT_HISTORY_T3_MANAGED: tuple[tuple[str, int], ...] = (("2026-09-22", 226),)
_SPEC = sc.compute()  # 与 tests/test_taxonomy_spec_gates.py 同一支取数口，全模块只现算一次
_VOLATILE_COUNT = re.compile(
    # 只抓独立成词的计数：前置排除 §9 / v21r2 / 1.4.3 这类章节号与版本号的粘连
    r"(?<![\w./§-])\d{1,5}\s*(?:个|条|枚|张|项|余)?\s*"
    r"(?:字段|主题|板块|入口|能力|模板|别名|路由席位)(?!\w)"
)


def _boards() -> list[bds.Board]:
    boards, _problems = bds.build_tree()
    return boards


def _problems() -> list[str]:
    _boards_result, problems = bds.build_tree()
    return problems


# ---------------------------------------------------------------- 结构自洽
def test_board_count_is_ten_and_ids_unique() -> None:
    boards = _boards()
    assert len(boards) == EXPECTED_BOARD_COUNT, f"一级板块必须恰为 10 个，实得 {len(boards)}"
    ids = [b.bid for b in boards]
    assert len(set(ids)) == len(ids), f"板块 id 重复：{ids}"
    assert ids == [f"B{i:02d}" for i in range(1, EXPECTED_BOARD_COUNT + 1)], f"板块编号断号或乱序：{ids}"


def test_feature_ids_match_owning_board_and_slugs_are_kebab() -> None:
    seen: set[str] = set()
    for board in _boards():
        assert _KEBAB.match(str(board.node["slug"])), f"板块 slug 非 kebab：{board.node['slug']}"
        for feature in board.features:
            fid = str(feature.node["fid"])
            assert fid.startswith(f"{board.bid}."), f"{fid} 前缀与所属板块 {board.bid} 不符"
            assert fid not in seen, f"二级功能 id 重复：{fid}"
            seen.add(fid)
            assert _KEBAB.match(feature.slug), f"二级 slug 非 kebab：{feature.slug}"
            for l3 in feature.l3:
                assert _KEBAB.match(l3.slug), f"三级 slug 非 kebab：{l3.slug}（{fid}）"
            for text in (feature.node["label"], feature.node["summary"]):
                assert str(text).strip(), f"{fid} 缺 label/summary"


def test_every_feature_declares_implementation_or_l3() -> None:
    """空壳功能不许存在（宁可不留，也不留占位让人误以为已有能力）。"""
    for board in _boards():
        for feature in board.features:
            has_impl = bool(feature.node.get("impl_paths"))
            assert feature.l3 or has_impl, f"{feature.fid} 既无三级入口也无实现落点，属空壳"


# ---------------------------------------------------------------- 活性覆盖
def test_every_route_kind_claimed_exactly_once() -> None:
    members = set(bds.load_route_kind_members())
    claims: dict[str, list[str]] = {}
    for board in _boards():
        for feature in board.features:
            for kind in feature.node.get("route_kinds") or ():
                claims.setdefault(str(kind), []).append(feature.fid)
    unknown = sorted(set(claims) - members)
    assert not unknown, f"板块树认领了代码里不存在的 RouteKind：{unknown}"
    orphan = sorted(members - set(claims))
    assert not orphan, f"代码里有 RouteKind 但无人认领（新增能力漏登板块树）：{orphan}"
    dup = {k: v for k, v in claims.items() if len(v) > 1}
    assert not dup, f"RouteKind 被多个二级功能抢：{dup}"


def test_every_help_topic_claimed_exactly_once() -> None:
    topics = set(bds.load_help_topics())
    claims: dict[str, list[str]] = {}
    for board in _boards():
        for feature in board.features:
            for topic in feature.node.get("help_topics") or ():
                claims.setdefault(str(topic), []).append(feature.fid)
    orphan = sorted(topics - set(claims))
    assert not orphan, f"帮助主题未归档到任何二级功能：{orphan}"
    ghost = sorted(set(claims) - topics)
    assert not ghost, f"板块树里挂着代码中不存在的帮助主题：{ghost}"
    dup = {k: v for k, v in claims.items() if len(v) > 1}
    assert not dup, f"帮助主题被两处认领：{dup}"


def _tamper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, needle: str, replacement: str) -> list[str]:
    """注毒复跑：把板块树里的一处改坏，返回体检报出的问题清单。"""
    src = bds.TAXONOMY_PY.read_text(encoding="utf-8")
    tampered = src.replace(needle, replacement, 1)
    assert tampered != src, f"注毒点未命中，本用例失去意义：{needle}"
    fake = tmp_path / "board_taxonomy.py"
    fake.write_text(tampered, encoding="utf-8")
    monkeypatch.setattr(bds, "TAXONOMY_PY", fake)
    _boards_out, problems = bds.build_tree()
    return problems


def test_gate_detects_unclaimed_route_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """自证一：新增席位漏登板块树，必须当场红。"""
    problems = _tamper(
        monkeypatch, tmp_path, 'route_kinds=("ALIAS", "NATURAL_COMMAND", "IGNORE")', 'route_kinds=("NATURAL_COMMAND", "IGNORE")'
    )
    assert any("ALIAS" in p and "未被" in p for p in problems), f"注毒后未报警：{problems[:5]}"


def test_gate_detects_duplicate_topic_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """自证二：一个帮助主题被两处认领，必须当场红。"""
    problems = _tamper(
        monkeypatch,
        tmp_path,
        'help_topics=("天气",)',
        'help_topics=("天气", "语音")',
    )
    assert any("重复" in p or "两处" in p for p in problems), f"注毒后未报警：{problems[:5]}"


def test_gate_detects_dead_impl_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """自证三：实现路径写成不存在的文件，必须当场红（防文档指空位）。"""
    problems = _tamper(
        monkeypatch,
        tmp_path,
        '"plugins/bot_unified_runtime/domains/core/session_keys.py"',
        '"plugins/bot_unified_runtime/domains/core/session_keys_typo.py"',
    )
    assert any("实现路径不存在" in p for p in problems), f"注毒后未报警：{problems[:5]}"


def test_all_impl_paths_exist() -> None:
    missing = []
    for board in _boards():
        for feature in board.features:
            for path in feature.node.get("impl_paths") or ():
                if not (ROOT / str(path)).exists():
                    missing.append(f"{feature.fid} -> {path}")
    assert not missing, f"实现路径不可解析：{missing}"


# ---------------------------------------------------------------- 生成物同步
def test_board_docs_are_in_sync_with_code() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "board_doc_sync.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, (
        "docs/boards 与代码漂移或未过体检，跑 python scripts/board_doc_sync.py --write\n"
        f"stdout={(proc.stdout or '')[-2000:]}\nstderr={(proc.stderr or '')[-2000:]}"
    )


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "_conventions.md",
    ],
)
def test_entry_pages_exist(relative: str) -> None:
    assert (BOARDS_DIR / relative).exists(), f"缺少板块入口件：docs/boards/{relative}"


def test_generated_pages_have_full_skeleton() -> None:
    """生成页骨架完整（旧判据）+ **G-T2 同类小节集合与顺序一致**（2026-09-22 席 T-GATES 扩展）。

    两条判据并存＝双保险：旧判据管「骨架没被动过」（AUTO 双标记 + 标记外 ≥20 字符），
    新判据管「人写区的小节集合与顺序同类一致」。管辖面 = `docs/boards/**` 的**人工区**
    （`<!-- BOARD-AUTO -->` 标记之外）+ 全部已迁移的模板驱动页；取数口是
    `scripts/spec_gates_census.py::compute()`（与 G-T1/T3/T4/T5 同一支，禁第二支扫描器）。

    起点基线（手写字面量，只准降）：本席 2026-09-22 现算 **1 页**偏离
    （`python scripts/spec_gates_census.py --report` ⇒ `G-T2 小节偏离页 = 1`，
    偏离件 = `docs/boards/README.md` 人写区「怎么读这套文档」不在 board-l1 骨架内）。
    任务书点名的起点 6 页已由席 M2 归一（见 `.superpowers/sdd/2026-09-22-taxonomy/SEAT-M2.md`），
    本席按「立门当跑值」取 1，未升、未缩面。
    """
    missing_auto: list[str] = []
    missing_sections: list[str] = []
    for path in sorted(BOARDS_DIR.rglob("*.md")):
        if "_meta" in path.parts:  # 过程账（旧文档分类台账）不是生成页
            continue
        text = path.read_text(encoding="utf-8")
        if bds.AUTO_BEGIN not in text or bds.AUTO_END not in text:
            missing_auto.append(str(path.relative_to(ROOT)))
            continue
        body = text.split(bds.AUTO_END, 1)[1]
        if path.parent.name == "boards" or path.name == "_conventions.md":
            continue
        if len(body.strip()) < 20:
            missing_sections.append(str(path.relative_to(ROOT)))
    assert not missing_auto, f"缺 AUTO 标记（无法被自动同步覆盖）：{missing_auto}"
    assert not missing_sections, f"缺正文骨架的小节：{missing_sections}"

    deviations = _SPEC["t2"]
    counts = [n for _d, n in AUDIT_HISTORY_T2]
    assert counts == sorted(counts, reverse=True), f"G-T2 核账记录出现回升（方向锁）：{counts}"
    assert T2_CEILING <= counts[0], f"上限 {T2_CEILING} 超过首届核账值 {counts[0]}＝调大换绿"
    assert _SPEC["t2_pages"] >= MIN_T2_PAGES, (
        f"G-T2 只比对了 {min(_SPEC['t2_pages'], 999999)} 页（地板 {MIN_T2_PAGES}）＝管辖面塌陷，"
        "不是大家都合规"
    )
    assert len(deviations) <= T2_CEILING, (
        f"同类小节集合/顺序偏离 {len(deviations)} 页 > 上限 {T2_CEILING}＝又长了异形页。"
        f"修法：把多出的 H2 降级为 H3 或改回骨架节名（结构零事实增删），"
        f"确属新形态则改骨架声明源并走模板升级。偏离件：{deviations[:6]}"
    )


def test_board_docs_do_not_handwrite_volatile_counts() -> None:
    """板块正文禁手写会漂移的计数（旧判据）+ **G-T3 禁裸写一次性事实**（2026-09-22 席 T-GATES 扩展）。

    判据真身 `scripts/doc_fact_discipline.py`（词表只住那一处，AST 锁在
    `tests/test_taxonomy_spec_gates.py`）：计数 / 阈值 / 枚举清单 / 运行数据路径四类，
    一律只准走 `{{fact:KEY}}` 参数引用或「以真身/生成物为准」的指针句。
    管辖面 = `docs/boards/**` 人工区 + 已迁移模板驱动页（`_meta`、`_conventions.md` 在内）。

    起点基线（手写字面量，只准降）：本席 2026-09-22 现算 **226 行**
    （`--report` ⇒ `G-T3 面 A 管辖 226 行`）。旧窄词表下这里是 0，宽尺（阈值/枚举/路径 +
    计数尾界不再被汉字挡住）是新执法，按「立门当跑值」记账，**不缩面、不加通配豁免**；
    未迁移页的债在
    `tests/test_taxonomy_spec_gates.py::test_g_t3_unmoved_face_debt_never_grows` 记第二本账。
    """
    violations = _SPEC["t3_managed"]
    counts = [n for _d, n in AUDIT_HISTORY_T3_MANAGED]
    assert counts == sorted(counts, reverse=True), f"G-T3 面 A 核账记录出现回升（方向锁）：{counts}"
    assert T3_MANAGED_CEILING <= counts[0], (
        f"上限 {T3_MANAGED_CEILING} 超过首届核账值 {counts[0]}＝调大换绿"
    )
    assert len(violations) <= T3_MANAGED_CEILING, (
        f"板块正文裸写一次性事实 {len(violations)} 行 > 上限 {T3_MANAGED_CEILING}。"
        f"修法：事实改 `{{fact:KEY}}` 参数（值走 auto: 现算）或写成"
        f"「以生成物/机器册/真身为准」指针句；违规大户：{violations[:8]}"
    )
    # 旧窄词表仍然单独执法（双保险：扩展判据不许把旧判据吃掉）
    offenders: list[str] = []
    for path in _board_body_pages():
        text = path.read_text(encoding="utf-8")
        human = re.sub(
            r"<!-- BOARD-AUTO:BEGIN -->.*?<!-- BOARD-AUTO:END -->", "", text, flags=re.DOTALL
        )
        for line in human.splitlines():
            if "以生成物为准" in line or "以机器册" in line or "当时值" in line:
                continue
            if _VOLATILE_COUNT.search(line):
                offenders.append(f"{path.relative_to(ROOT)}: {line.strip()[:80]}")
    assert not offenders, f"板块文档正文手写了会漂移的计数：{offenders}"


def _board_body_pages() -> list[Path]:
    """板块正文页（排除机器台账 _meta 与规范本体）。"""
    return [
        x for x in sorted(BOARDS_DIR.rglob("*.md"))
        if "_meta" not in x.parts and x.name != "_conventions.md"
    ]


def test_volatile_count_gate_detects_planted_line(tmp_path: Path) -> None:
    """自证四：门能杀行为——同一行注毒必红，带权威指针放行。"""
    page = tmp_path / "boards" / "B01-x" / "feat"
    page.mkdir(parents=True)
    bad = page / "bad.md"
    bad.write_text("本板块共 47 个能力入口，另有 12 条别名。\n", encoding="utf-8")
    good = page / "good.md"
    good.write_text("计数以生成物 docs/boards/README.md 为准。\n", encoding="utf-8")
    assert _VOLATILE_COUNT.search(bad.read_text(encoding="utf-8")), "注毒未被识别"
    assert not _VOLATILE_COUNT.search(good.read_text(encoding="utf-8")), "带指针行被误拦"
    for ref in ("§9 字段级契约", "zhconv 1.4.3 字段", "v21r2 主题"):
        assert not _VOLATILE_COUNT.search(ref), f"章节号/版本号被误判：{ref}"


# ---------------------------------------------------------------- G-T3 扩面（席 S3 2026-09-22，只加严）
# 治 F-3「放行词整行橡皮章」与 F-15「注毒只跑正则、不跑记账腿」。判据真身一律在
# `scripts/doc_fact_discipline.py`（词表唯一住所，此处只喂样本行，不抄第二套尺子）。

_G3_BARE_CLASSES = ("裸计数", "裸阈值", "裸路径", "裸枚举清单")


def test_g_t3_pointer_phrase_does_not_stamp_exempt_bare_facts() -> None:
    """自证四·补（F-3）：指针短语与裸事实同行混写仍须红——指针只豁免它自己承担的片段。

    放行判据是**分段**的：摘除 `以…为准` 整段/`{{fact:…}}`/指针词之后，残余文本照判四类。
    纯指针句与粘连负样本必须保持放行（误杀=逼作者往别处藏事实，同样是债）。
    """
    mixed = [
        "本板块共 47 个能力入口，真身在 board_taxonomy.py。",
        "单文件上限 100MB，超时 30 秒，共 5 个键（现值）。",
        "{{fact:count}} 条入口，另外 47 个能力，超时 30 秒。",
        "另有 12 条别名，计数以生成物 README 为准。",
    ]
    for line in mixed:
        hits = dfd.fact_findings([line], vocab=set())
        assert hits and any(h.startswith(c) for c in _G3_BARE_CLASSES for h in hits), (
            f"指针橡皮章仍整行放行混写句：{line!r} → {hits}"
        )
    for ok in (
        "计数以生成物 docs/boards/README.md 为准。",
        "字段数以机器册 docs/auto-facts.md 为准（当时值保留于台账）。",
        "{{fact:count}} 条入口（渲染期现算）。",
        "以最近一次 dev.ps1 -Task test 实跑输出为准。",
        "§9 字段级契约与 v21r2 主题、zhconv 1.4.3 版本无关。",
    ):
        assert dfd.fact_findings([ok], vocab=set()) == [], f"纯指针/粘连负样本被误杀：{ok!r}"


def test_g_t3_machine_local_paths_never_exempted() -> None:
    """机器本地路径（盘符/UNC//c/Users/家目录~/%VAR% 占位）在正文一律红，指针句不豁免。

    这是 AGENTS 规则 3 打码面之外的一层：隐私 + 可移植双重问题，只准住配置真身。
    `https://` 等 URL scheme 不算机器本地路径（负对照防误伤面失控）。
    """
    bs = chr(92)
    lines = [
        "归档落在 data/media_archive/ 与 C:/Users/x/Runtime/ 下，路径以 runtime_paths 为准。",
        "日志在 C:" + bs + "Software" + bs + "x 下（现值以巡检为准）。",
        "工作目录 /c/Users/x 以环境为准。",
        "临时件放 %TEMP%/x，口径以脚本为准。",
        "缓存 ~/x 以脚本为准。",
        "共享在 " + bs + bs + "server" + bs + "share 下，以配置为准。",
    ]
    for line in lines:
        hits = dfd.fact_findings([line], vocab=set())
        assert hits and hits[0].startswith("裸机器本地路径"), (
            f"机器本地路径被指针句放行：{line!r} → {hits}"
        )
    url_only = "上游端点 https://example.com/a/b（可用性以实测为准）。"
    assert not any(
        h.startswith("裸机器本地路径") for h in dfd.fact_findings([url_only], vocab=set())
    ), "URL scheme 被误判为机器本地盘符路径"


def test_g_t3_accounting_leg_detects_synthetic_poison_page(tmp_path: Path) -> None:
    """自证五（F-15 修腿）：记账腿走完整 `sc.compute(合成根)`——毒页不进真树也被抓到。

    旧「自证四」只跑 `_VOLATILE_COUNT` 正则，记账链（walk→human_lines→fact_findings→
    面 A/B 归类）整体改坏它照样绿。本用例把 bad/good 两页写进 tmp 合成树调**同一支**
    记账函数：bad 行必须出现在 `t3_managed`（面 A 归类腿活着），good 纯指针页不得进账
    （分段放行没被改疯）。`sc.compute(root)` 对合成根的支持是 census 自带契约。
    """
    boards = tmp_path / "docs" / "boards" / "B01-x"
    boards.mkdir(parents=True)
    (boards / "bad.md").write_text(
        "本板块共 47 个能力入口，真身在 board_taxonomy.py。\n", encoding="utf-8"
    )
    (boards / "good.md").write_text(
        "计数以生成物 docs/boards/README.md 为准。\n", encoding="utf-8"
    )
    res = sc.compute(tmp_path)
    managed = [str(v) for v in res["t3_managed"]]
    assert any("bad.md" in v and "裸计数：本板块共 47 个能力入口" in v for v in managed), (
        f"记账腿对合成毒页失明（该腿视为不存在）：{managed[:6]}"
    )
    assert not any("good.md" in v for v in managed), f"纯指针页被记账腿误记：{managed[:6]}"
