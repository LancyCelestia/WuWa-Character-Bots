"""文档归属账：未归属文档数棘轮（只准降，2026-09-22 规格统一波 · 席 T-JOIN 立）。

背景：`CENSUS.md` 报未归属 955，主会话复算确认根因是**口径 join 不上**——分类表
`docs/boards/_meta/doc-classification-20260921.md` 里 32 行裸文件名基目录只写在节标题里、
`.superpowers` 14 行目录级条目无法被文件路径命中，机器不可直读。本门把归属升成
**机器可读声明源**（`plugins/bot_unified_runtime/domains/core/board_doc_ownership.py`，由
`scripts/doc_ownership_sync.py` 机械投影生成），并对「未归属」立一本只准降的账。

判据口径（照抄本仓棘轮成熟形态，`test_legacy_shim_import_ratchet.py` 同族）：
- **上限是手写字面量**：与被检清单同表达式派生＝结构性假绿，故另有一把 AST 自锁
  （`ast.Assign` 与 `ast.AnnAssign` 两形态都认——本仓的门曾因只认 Assign 把自己盯的常量看漏）。
- **取数口只有一份**：violations、总数、`--report` 全部走 `compute_ownership()` 同一函数
  （本文件所有断言吃同一个 Ledger 对象；report 行数与 violations 长度互证，防"总数另算一套"）。
- **扫描面地板**：低于 `MIN_SCANNED_DOCS` 即红——改 glob 把账做没，判的是塌陷不是清零。
- **命中非空**：未归属清单为空要么全线归位（那就显式删本门并留说明），要么取数口坏了。
- **注毒自证走 tmp_path/内存**：往假 repo 造表造文件，零污染源码树。
- **终局要求是降**：本基线 158 是起点不是达标线；后续批次每归位一批，ceiling 与 AUDIT_HISTORY 同步降。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import doc_ownership_sync as dos  # scripts 直包先例：test_board_taxonomy_gate 同款

#: **手写字面量**上限，只准降。开工基线由本席（T-JOIN）现算并手抄：
#: 2026-09-22，命令 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8
#: ../ChatBot_Runtime/venv/Scripts/python.exe scripts/doc_ownership_sync.py --report`
#: → 立门当跑现算「未归属（violations）= 159」（扫描面 1286；对照 CENSUS 旧口径 955，
#: join 修复后未归属缩到 159：目录级认领吃掉 557、板块生成页路径直取 224、
#: 裸文件名/通配/数字系列机械补全在册 276 条）。首抄值 158 在两分钟内被并行板席的
#: 在飞席报顶到 159——**这就是本门要施的压**：新文档不进表就顶账，后续批次只准往下打。
UNOWNED_DOC_CEILING = 159

#: 逐次核账记录（日期, 当时未归属数）。**必须单调不升**——想调大上限就得违反这条，当场红。
#: 口径说明：CENSUS 的 955 是"md 查表无主"旧口径；159 是本门新口径（目录级认领+基目录补全后），
#: 首行起账即按新口径，**不许拿两把尺子相减冒功**。
UNOWNED_AUDIT_HISTORY: tuple[tuple[str, int], ...] = (("2026-09-22", 159),)

#: 扫描面文件数下限（现算 1285，留 ~7% 余量）：低于此＝扫描面塌陷，不是"文档都归位了"。
MIN_SCANNED_DOCS = 1200


def test_unowned_within_ceiling() -> None:
    ledger = dos.compute_ownership()
    by_dir: dict[str, int] = {}
    for rel in ledger.unowned:
        key = rel if "/" not in rel else "/".join(rel.split("/")[:2]) + "/…"
        by_dir[key] = by_dir.get(key, 0) + 1
    worst = sorted(by_dir.items(), key=lambda kv: -kv[1])[:5]
    assert len(ledger.unowned) <= UNOWNED_DOC_CEILING, (
        f"未归属文档 {len(ledger.unowned)} > 上限 {UNOWNED_DOC_CEILING}＝又添了没进分类表的文档。"
        f"修法：给 docs/boards/_meta/doc-classification-20260921.md 补行 → 跑 "
        f"scripts/doc_ownership_sync.py --generate → 降本上限并追加 AUDIT_HISTORY 一行（大户：{worst}）"
    )


def test_violations_and_totals_share_one_accessor() -> None:
    """取数口唯一锁：--report 打的数与 violations 断言吃的数必须是**同一个 Ledger** 派生。"""
    ledger = dos.compute_ownership()
    report = dos.report_text(ledger)
    assert f"未归属（violations）= {len(ledger.unowned)}" in report
    assert f"扫描面(内容文档) = {ledger.scanned}" in report
    assert ledger.scanned == len(dos.scan_surface())


def test_scan_floor_and_hit_not_empty() -> None:
    """非空转守卫：扫描面与命中面都须真实存在，否则"零红"只是没在看。"""
    ledger = dos.compute_ownership()
    assert ledger.scanned >= MIN_SCANNED_DOCS, (
        f"只扫到 {ledger.scanned} 份文档（地板 {MIN_SCANNED_DOCS}）＝扫描面塌陷（改 glob/加排除），账被做没"
    )
    assert ledger.unowned, (
        "未归属清单为空——若真全线归位，请显式删本门并在报告留说明；更可能是取数口坏了"
    )
    assert ledger.entries, "声明源零条目＝投影器或分类表读取断链"
    # 机械补全确实吃到东西（裸文件名行 join 修复的活性证明；回退成"只认全路径"会先在这红）
    assert ledger.completed_paths > 0 and ledger.dir_attributed > 0 and ledger.board_path_direct > 0


def test_ceiling_is_hand_written_literal() -> None:
    """结构锁：上限必须是字面量整数（AST 双形态：Assign 与 AnnAssign 都认），核账记录留在本文件。"""
    source = Path(__file__).read_text(encoding="utf-8")
    assigned: dict[str, ast.expr] = {}
    for node in ast.walk(ast.parse(source)):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assigned[target.id] = value
    ceiling = assigned.get("UNOWNED_DOC_CEILING")
    assert isinstance(ceiling, ast.Constant) and isinstance(ceiling.value, int), (
        "UNOWNED_DOC_CEILING 被改成派生表达式＝上限跟着被检对象一起动，本门结构性失效"
    )
    history = assigned.get("UNOWNED_AUDIT_HISTORY")
    assert isinstance(history, ast.Tuple) and len(history.elts) >= 1, (
        "UNOWNED_AUDIT_HISTORY 必须留在本文件且非空——它是'只准降'的对账凭据"
    )
    floor = assigned.get("MIN_SCANNED_DOCS")
    assert isinstance(floor, ast.Constant) and isinstance(floor.value, int), "地板同样必须是字面量"


def test_audit_history_never_rises() -> None:
    counts = [count for _, count in UNOWNED_AUDIT_HISTORY]
    assert counts == sorted(counts, reverse=True), f"核账记录出现回升（方向锁）：{UNOWNED_AUDIT_HISTORY}"
    assert UNOWNED_DOC_CEILING <= counts[0], (
        f"上限 {UNOWNED_DOC_CEILING} 超过首届核账值 {counts[0]}＝把账调大换绿，本门不允许"
    )


def test_declaration_source_is_in_sync_and_pure() -> None:
    """声明源逐字节 == 分类表投影（手改即红）；且守住"只声明数据"哲学。"""
    ledger = dos.compute_ownership()
    target = ROOT / dos.OWNERSHIP_REL
    assert target.exists(), "声明源不存在——跑 scripts/doc_ownership_sync.py --generate"
    assert target.read_text(encoding="utf-8") == dos.render_source(ledger), (
        "声明源与分类表投影不一致：改归属请改分类表再 --generate，**禁手改生成物**"
    )
    tree = ast.parse(target.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module in {"__future__", "dataclasses"}, f"声明源越界 import：{node.module}"
        elif isinstance(node, ast.Import):
            assert all(a.name == "dataclasses" for a in node.names), "声明源只准 dataclasses/__future__"
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "DocOwner"]
    assert calls, "声明源里一个 DocOwner 构造都没有＝投影器写空了"
    seen: set[str] = set()
    for call in calls:
        kw = {k.arg: ast.literal_eval(k.value) for k in call.keywords if k.arg}
        path, board = kw["path"], kw["board"]
        assert board == "" or (len(board) == 3 and board.startswith("B")), f"板块码非法：{board!r}（{path}）"
        assert path not in seen, f"同一路径两条目：{path}（双认领=归属含糊，投影器须先去重）"
        seen.add(path)
        if path.endswith("/"):
            assert (ROOT / Path(*path.rstrip('/').split('/'))).is_dir(), f"目录级条目不在盘：{path}"
        else:
            assert (ROOT / Path(*path.split('/'))).is_file(), f"在册条目路径不可解析：{path}（应在 ARCHIVE）"


_FAKE_TABLE = """# fake

## 1. 根目录 .md

| AGENTS.md | 1 | 现行 | B10 | NONE | 规则 | 保留 | 依据R |

## 2. docs/*.md（顶层件）

| 路径 | 字节 | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置 | 依据 |
|---|---|---|---|---|---|---|---|
| docs/full-path.md | 1 | 现行权威 | B01 | NONE | 接入 | 保留 | 依据A |
| bare-name.md | 1 | 现行 | B02 | NONE | 路由 | 保留 | 依据B |
| none-doc.md | 1 | 失效 | NONE | NONE | x | 归档 | 依据C |
| ghost-doc.md | 1 | 现行 | B03 | NONE | x | 保留 | 依据D |

### 3.2 docs/design —— 通配族

| 路径 | 字节 | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置 | 依据 |
|---|---|---|---|---|---|---|---|
| `d-*-spec.md`：alpha / beta | 2 | 规格 | B07 | NONE | x | 保留 | 依据E |

## 4. `.superpowers/sdd/**` —— 目录级判定

| 目录 | 文件数/字节 | 形态 | 主板块 | 次板块 | 已吸收？ | 处置建议 | 判定依据 |
|---|---|---|---|---|---|---|---|
| `…/fake-wave/` | 1 | 过程件 | B05 | NONE | 是 | 归档 | 依据F |

## 5. 收尾三节（本门不解析）

| # | 事实 | 互指 | 真身 | 冲突 |
|---|---|---|---|---|
| 1 | 不该被当归属行 | — | — | — |
"""


def _build_fake_repo(tmp_path: Path) -> Path:
    """造一座五脏俱全的小 repo：全路径行/裸名行/NONE 行/死行/目录行/通配行各一。"""
    table = tmp_path / dos.CLASSIFICATION_REL
    table.parent.mkdir(parents=True)
    table.write_text(_FAKE_TABLE, encoding="utf-8")
    files = {
        "AGENTS.md": "root rules",
        "docs/full-path.md": "a",
        "docs/bare-name.md": "b",
        "docs/none-doc.md": "c",
        "docs/design/d-alpha-spec.md": "e1",
        "docs/design/d-beta-spec.md": "e2",
        ".superpowers/sdd/fake-wave/notes.md": "f",
        "docs/unlisted.md": "u",  # 无任何表行 → 必须留在未归属
    }
    for rel, text in files.items():
        p = tmp_path / Path(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_projection_rules_on_fake_repo(tmp_path: Path) -> None:
    repo = _build_fake_repo(tmp_path)
    ledger = dos.compute_ownership(repo)
    boards = {e.path: e.board for e in ledger.entries}
    # ① 全路径行直接采信；② 裸文件名行经基目录补全（本轮要修的正是这种 join）
    assert boards.get("docs/full-path.md") == "B01"
    assert boards.get("docs/bare-name.md") == "B02"
    completed = {e.path for e in ledger.entries if e.completed}
    assert "docs/bare-name.md" in completed, "裸文件名没走补全＝基目录表被绕开"
    # ③ 通配模板展开（含重叠前缀裁剪 w*-log × w10 同型）
    assert boards.get("docs/design/d-alpha-spec.md") == "B07"
    assert boards.get("docs/design/d-beta-spec.md") == "B07"
    # ④ 目录行吃掉目录内文件（.superpowers 557 件的机制本身）
    assert ".superpowers/sdd/fake-wave/notes.md" not in ledger.unowned, "目录级认领失效"
    # ⑤ NONE 行 = 在册未归属（不发明归属）；查无此行 = 未归属；两者都进 violations。
    #    （假 repo 自己的分类表文件也在扫描面且无主——与真树同构的自反映射，不豁免）
    assert set(ledger.unowned) == {
        "docs/none-doc.md",
        "docs/unlisted.md",
        dos.CLASSIFICATION_REL,
    }
    # ⑥ 死行进 ARCHIVE 不丢信息；§5 台账面绝不被当归属行
    assert any("ghost-doc.md" in a.path for a in ledger.archive)
    assert not any(p.startswith("docs/") and "不该被当归属行" in p for p in boards)


def test_new_unowned_doc_is_caught(tmp_path: Path) -> None:
    """注毒（tmp_path，零污染真树）：新增一份没进表的文档，未归属账当场 +1 并点名它。"""
    repo = _build_fake_repo(tmp_path)
    before = dos.compute_ownership(repo)
    stray = repo / "docs" / "stray-20260922.md"
    stray.write_text("poison", encoding="utf-8")
    after = dos.compute_ownership(repo)
    assert len(after.unowned) == len(before.unowned) + 1, "新文档没把账顶起来＝取数口失明"
    assert "docs/stray-20260922.md" in after.unowned
    # 反向自证：给它补一行分类表 → 重投影即摘牌（账可降，机制自持）
    table = repo / dos.CLASSIFICATION_REL
    text = table.read_text(encoding="utf-8")
    table.write_text(
        text.replace(
            "| ghost-doc.md | 1 | 现行 | B03 | NONE | x | 保留 | 依据D |",
            "| ghost-doc.md | 1 | 现行 | B03 | NONE | x | 保留 | 依据D |\n"
            "| stray-20260922.md | 1 | 现行 | B01 | NONE | x | 保留 | 注毒归位 |",
        ),
        encoding="utf-8",
    )
    fixed = dos.compute_ownership(repo)
    assert "docs/stray-20260922.md" not in fixed.unowned, "补表后仍计未归属＝投影链断"
    assert len(fixed.unowned) == len(before.unowned)


def test_ambiguous_rows_do_not_invent_ownership(tmp_path: Path) -> None:
    """双板块歧义行（「B01 / B08」形）：不发明归属，文件留在未归属并记待裁。"""
    repo = _build_fake_repo(tmp_path)
    table = repo / dos.CLASSIFICATION_REL
    text = table.read_text(encoding="utf-8")
    table.write_text(
        text.replace("| docs/full-path.md | 1 | 现行权威 | B01 ", "| docs/full-path.md | 1 | 现行权威 | B01 / B08 "),
        encoding="utf-8",
    )
    ledger = dos.compute_ownership(repo)
    assert "docs/full-path.md" in ledger.unowned
    assert any("full-path" in row for row in ledger.ambiguous_rows)


# ════════════════════════════════════════════════════════════════════════════
# 席 S88 OWNERSHIP-GATE-TEETH —— 把 S76 的「七态诊断」接进门（P-S76-1）
#
# 本文件原有 `test_declaration_source_is_in_sync_and_pure` 只做**整文件逐字节**比对：
# 它只会说"不一样"，不会说**哪一态**、方向朝哪 ⇒ 脚本有牙、门没牙。
# 下面补的是**逐态**执法：每种断链都要被点名句、方向要分得开、且各带可执行下一步。
#
# 三条纪律写死在这里：
# 1. 注毒一律打在 `tmp_path` 假 repo 上，**零污染源码树**（真声明源一个字都不写）。
# 2. 取证只走**同一条真入口** `main(["--check"], repo=...)` + 它的 stdout ⇒
#    门钉的是"人能看到的那句诊断"，不是内部函数返回值（内部绿、出口瞎＝本波第 15 号形态）。
# 3. 每次注毒前先断言"打中的字面确实存在且唯一"、注毒后断言"文件真的变了" ⇒
#    杜绝「注毒打在空气上、测试却绿」（本波 F-15 同族）。
#
# 既有断言一字未改（§7 禁写面）；本节只新增。
# ════════════════════════════════════════════════════════════════════════════

#: 七态字面量（真身 = `scripts/doc_ownership_sync.py` 的 K_* 常量；此处只引用不复制值）。
ALL_STATES: tuple[str, ...] = (
    dos.K_ABSENT, dos.K_PARSE, dos.K_DUP, dos.K_MISSING, dos.K_EXTRA, dos.K_FIELD, dos.K_FORMAT,
)

#: 结构锁 (c) 用：一句「可执行下一步」至少要有这些动作之一，否则就是"看着办"式废话。
_ACTIONABLE_MARKERS = ("--generate", "回滚", "分类表")


def _decl_of(repo: Path) -> Path:
    return repo / dos.OWNERSHIP_REL


def _read_decl(repo: Path) -> str:
    return _decl_of(repo).read_text(encoding="utf-8")


def _write_decl(repo: Path, text: str) -> None:
    # 与 `--generate` 同形（newline="\n"）：注毒不得自带换行噪声，否则 K_FORMAT 会串进别的态。
    with _decl_of(repo).open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _fresh_repo(tmp_path: Path, capsys: Any, name: str = "repo") -> Path:
    """假 repo ＋ **用真入口**投影出的自洽声明源，并确认干净基线为 rc0。

    干净基线不成立就没必要往下注毒——那时任何红都可能是构造错，不是判据在执法。
    """
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    _build_fake_repo(repo)
    assert dos.main(["--generate"], repo=repo) == 0, "--generate 在假 repo 上失败＝注毒现场搭不起来"
    assert dos.main(["--check"], repo=repo) == 0, "干净基线不 CLEAN＝后面所有红都归因不明"
    capsys.readouterr()  # 排掉搭现场期间的输出，后面每次取证只看当发注毒
    return repo


def _add_table_row(repo: Path, anchor: str, new_row: str, path: str) -> None:
    """给假 repo 的分类表补一行（连同文件），供「两棵树」结构锁造差异。"""
    table = repo / dos.CLASSIFICATION_REL
    text = table.read_text(encoding="utf-8")
    assert text.count(anchor) == 1, f"表内锚点不唯一（{anchor!r}）＝注毒打在空气上"
    table.write_text(text.replace(anchor, anchor + "\n" + new_row), encoding="utf-8")
    created = repo / Path(*path.split("/"))
    created.parent.mkdir(parents=True, exist_ok=True)
    created.write_text("extra", encoding="utf-8")


def _check(repo: Path, capsys: Any) -> tuple[int, str]:
    """跑真入口，返回 (rc, stdout)。诊断是否点名只能从出口取证。"""
    rc = dos.main(["--check"], repo=repo)
    return rc, capsys.readouterr().out


def _assert_names_state(out: str, state: str, silent: tuple[str, ...] = ()) -> None:
    """该态必须被**点名**（不是只 rc≠0）；串态即红——方向可分辨才算七态各有一枚牙。"""
    assert f"[{state}]" in out, f"门没有点名「{state}」，只看到：\n{out}"
    for other in silent:
        assert f"[{other}]" not in out, f"串态：期望只报「{state}」却报了「{other}」：\n{out}"
    assert "下一步：" in out, f"「{state}」没有给可执行下一步（S69 立的要求）：\n{out}"


def _locate(lines: list[str], needle: str) -> int:
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    assert len(hits) == 1, f"注毒目标不存在或不唯一（{needle!r} 命中 {len(hits)} 行）"
    return hits[0]


def test_s88_poison_states_are_seven_and_next_step_covers_each() -> None:
    """结构锁 (c) 前半：态集合、诊断顺序表、下一步表**三者同源**，谁漏一格当场红。

    防的形态：将来加第八态却忘了给下一步 ⇒ 输出里那句"下一步"永远缺席，而门照样绿。
    """
    assert len(set(ALL_STATES)) == 7, f"七态口径漂移：{ALL_STATES}"
    assert set(dos._KIND_ORDER) == set(ALL_STATES), "诊断顺序表与七态常量不同源"
    assert set(dos._NEXT_STEP) == set(ALL_STATES), "有态没配「下一步」＝诊断只剩症状"
    for state in ALL_STATES:
        step = dos._NEXT_STEP[state].strip()
        assert step, f"{state} 的下一步是空话"
        assert any(marker in step for marker in _ACTIONABLE_MARKERS), (
            f"{state} 的下一步没有可执行动作（要含 {_ACTIONABLE_MARKERS} 之一）：{step[:80]}"
        )


def test_s88_state_absent_is_named_and_says_generate(tmp_path: Path, capsys: Any) -> None:
    """态 1/7 声明源不在盘：整文件比对的旧形状在这里同样红，但只有新腿能说出**为什么**红。"""
    repo = _fresh_repo(tmp_path, capsys)
    _decl_of(repo).unlink()
    rc, out = _check(repo, capsys)
    assert rc == 1
    _assert_names_state(out, dos.K_ABSENT, silent=(dos.K_PARSE, dos.K_MISSING, dos.K_EXTRA, dos.K_FIELD))
    assert "--generate" in out, f"该态的下一步必须就是重投影：\n{out}"


def test_s88_state_unparseable_named_syntax(tmp_path: Path, capsys: Any) -> None:
    """态 2a/7 声明源不可解析（语法崩形）：手改改崩到读不动。"""
    repo = _fresh_repo(tmp_path, capsys)
    _write_decl(repo, "这不是 python 语法 =(")
    rc, out = _check(repo, capsys)
    assert rc == 1
    # 崩到底时逐格比无意义 ⇒ 脚本早退回，只报这一态（其余各态**不该**同时冒出来）
    _assert_names_state(out, dos.K_PARSE,
                        silent=(dos.K_MISSING, dos.K_EXTRA, dos.K_FIELD, dos.K_DUP, dos.K_FORMAT))


def test_s88_state_unparseable_named_element_form(tmp_path: Path, capsys: Any) -> None:
    """态 2b/7 声明源不可解析（非法条目形）：文件读得动，但某一格不是 `DocOwner(...)`。"""
    repo = _fresh_repo(tmp_path, capsys)
    raw = _read_decl(repo)
    broken = raw.replace("DocOwner(path='docs/full-path.md'", "\"不是DocOwner构造\"(path='docs/full-path.md'", 1)
    assert broken != raw, "注毒没改动文件＝空跑"
    _write_decl(repo, broken)
    rc, out = _check(repo, capsys)
    assert rc == 1
    _assert_names_state(out, dos.K_PARSE,
                        silent=(dos.K_MISSING, dos.K_EXTRA, dos.K_FIELD, dos.K_DUP, dos.K_FORMAT))
    assert "条目形" in out, f"该点名「条目形」这一格：\n{out}"


def test_s88_state_missing_entry_names_the_path(tmp_path: Path, capsys: Any) -> None:
    """态 3/7 盘上缺条目（＝改了分类表没跑重投影）：方向必须是「上游有、盘上无」。"""
    repo = _fresh_repo(tmp_path, capsys)
    lines = _read_decl(repo).split("\n")
    idx = _locate(lines, "path='docs/full-path.md'")
    del lines[idx]
    _write_decl(repo, "\n".join(lines))
    rc, out = _check(repo, capsys)
    assert rc == 1
    _assert_names_state(out, dos.K_MISSING, silent=(dos.K_EXTRA, dos.K_FIELD, dos.K_DUP))
    assert "docs/full-path.md" in out, f"缺条目必须点名到具体 path：\n{out}"
    assert "上游有" in out and "盘上无" in out, f"方向措辞要能分辨「上游有/盘上无」：\n{out}"


def test_s88_state_extra_entry_names_the_path(tmp_path: Path, capsys: Any) -> None:
    """态 4/7 盘上多条目（＝手改生成物，或上游行被删）：方向必须是「盘上有、上游无」。"""
    repo = _fresh_repo(tmp_path, capsys)
    lines = _read_decl(repo).split("\n")
    idx = _locate(lines, "path='docs/full-path.md'")
    lines.insert(idx + 1, "    DocOwner(path='docs/hand-added.md', board='B06', fid='', "
                          "currency='现行', basis='盘上手加', completed=False),")
    _write_decl(repo, "\n".join(lines))
    rc, out = _check(repo, capsys)
    assert rc == 1
    _assert_names_state(out, dos.K_EXTRA, silent=(dos.K_MISSING, dos.K_FIELD, dos.K_DUP))
    assert "docs/hand-added.md" in out, f"多条目必须点名到具体 path：\n{out}"
    assert "盘上有" in out and "上游现算无" in out, f"方向措辞要能分辨「盘上有/上游无」：\n{out}"


def test_s88_field_drift_is_named_as_field_not_missing(tmp_path: Path, capsys: Any) -> None:
    """态 5/7 字段漂移（反向自测①）：改 basis 必须报**字段漂移**，不许退化成「缺条目」。

    这正是 S69 真咬到的那一条（清扫席改了依据列没随迁）。旧形状只说"不一致"，
    新腿必须把「哪一格、哪个字段、期望 vs 现值」三件事一起说出来。
    """
    repo = _fresh_repo(tmp_path, capsys)
    raw = _read_decl(repo)
    poisoned = raw.replace("basis='依据A'", "basis='依据A（被改过）'", 1)
    assert poisoned != raw, "注毒没改动文件＝空跑"
    _write_decl(repo, poisoned)
    rc, out = _check(repo, capsys)
    assert rc == 1
    _assert_names_state(out, dos.K_FIELD, silent=(dos.K_MISSING, dos.K_EXTRA, dos.K_DUP))
    assert ".basis" in out, f"要点到字段：\n{out}"
    assert "期望=" in out and "盘上=" in out, f"字段漂移必须给 期望/现值 两个值：\n{out}"
    assert "docs/full-path.md" in out, f"字段漂移要点名受害 path：\n{out}"


def test_s88_state_duplicate_path_named(tmp_path: Path, capsys: Any) -> None:
    """态 6/7 盘上重复路径（反向自测③）：投影器按 path 去重 ⇒ 重复只可能来自手改。"""
    repo = _fresh_repo(tmp_path, capsys)
    lines = _read_decl(repo).split("\n")
    idx = _locate(lines, "path='docs/full-path.md'")
    lines.insert(idx + 1, lines[idx])
    _write_decl(repo, "\n".join(lines))
    rc, out = _check(repo, capsys)
    assert rc == 1
    _assert_names_state(out, dos.K_DUP, silent=(dos.K_MISSING, dos.K_EXTRA, dos.K_FIELD))
    assert "docs/full-path.md" in out, f"重复态必须点名重复的 path：\n{out}"


def test_s88_state_format_only_drift_named(tmp_path: Path, capsys: Any) -> None:
    """态 7/7 非条目级漂移：条目级三态全平、只有注释/空白不一致。

    这态存在的意义＝**不许**把"字节不同"糊成"没问题"。旧形状在这红，但说不出只是排版。
    """
    repo = _fresh_repo(tmp_path, capsys)
    _write_decl(repo, _read_decl(repo) + "#: 只动注释的排版差异\n")
    rc, out = _check(repo, capsys)
    assert rc == 1
    _assert_names_state(out, dos.K_FORMAT, silent=(dos.K_MISSING, dos.K_EXTRA, dos.K_FIELD, dos.K_DUP))
    assert "字节" in out, f"排版态要给两边字节数：\n{out}"


def test_s88_direction_symmetry_across_two_trees(tmp_path: Path, capsys: Any) -> None:
    """反向自测②＋结构锁 (a)：造 A/B 两棵**不同**的树，把 A 的声明源塞进 B。

    期望两个方向同时成立且各点到对的 path：B 上游有而盘上没有 →「盘上缺条目」；
    A 独有而 B 上游没有 →「盘上多条目」。若 `repo` 参数其实没生效（旧写法 def 时绑死 REPO），
    这里要么两态都不出现、要么报的是真 REPO 的账 ⇒ 当场红。
    """
    repo_a = _fresh_repo(tmp_path, capsys, "repoA")
    _add_table_row(repo_a, "| docs/full-path.md | 1 | 现行权威 | B01 | NONE | 接入 | 保留 | 依据A |",
                   "| docs/a-only.md | 1 | 现行 | B04 | NONE | x | 保留 | 依据G |", "docs/a-only.md")
    assert dos.main(["--generate"], repo=repo_a) == 0
    repo_b = _fresh_repo(tmp_path, capsys, "repoB")
    _add_table_row(repo_b, "| docs/full-path.md | 1 | 现行权威 | B01 | NONE | 接入 | 保留 | 依据A |",
                   "| docs/b-only.md | 1 | 现行 | B04 | NONE | x | 保留 | 依据H |", "docs/b-only.md")
    assert dos.main(["--generate"], repo=repo_b) == 0
    capsys.readouterr()
    # 各扫各的树都是绿的（换树成立的第一半）
    assert dos.main(["--check"], repo=repo_a) == 0
    assert dos.main(["--check"], repo=repo_b) == 0
    capsys.readouterr()
    _write_decl(repo_b, _read_decl(repo_a))  # 只搬声明源，不搬分类表 ⇒ 账与文件必打架
    rc, out = _check(repo_b, capsys)
    assert rc == 1
    assert f"[{dos.K_MISSING}]" in out and f"[{dos.K_EXTRA}]" in out, f"两向都要点名：\n{out}"
    assert f"[{dos.K_FIELD}]" not in out, f"两边共有行的字段是一致的，不该冒出字段漂移：\n{out}"
    assert "docs/b-only.md" in out, f"B 独有行须记「盘上缺条目」：\n{out}"
    assert "docs/a-only.md" in out, f"A 独有行须记「盘上多条目」：\n{out}"


def test_s88_parse_accepts_both_assign_forms(tmp_path: Path, capsys: Any) -> None:
    """结构锁 (b)：`ast.Assign` 与 `ast.AnnAssign` **双形态都认**（防第 28 号形态复发）。

    S76 自曝的真事故：`parse_declaration` 只认 `Assign`，而声明源三张表全是
    `X: tuple[DocOwner, ...] = (...)`＝`AnnAssign` ⇒ 解析 0 条、三态方向整体说反，
    而门照样绿。所以这里既验 AnnAssign 腿（真声明源，计数>0 且 == 现算表数），
    也验 Assign 腿（内存改写成无标注形，计数不得归零），并现算证真身**确实**是 AnnAssign
    （否则"双形态"只是句口号——只有一条腿被踩过）。
    """
    target = ROOT / dos.OWNERSHIP_REL
    text = target.read_text(encoding="utf-8")
    ledger = dos.compute_ownership()
    want = dos.projection_records(ledger)
    records, drifts = dos.parse_declaration(text)
    assert not drifts, f"真声明源不该解析出漂移：{drifts[:3]}"
    assert len(records) > 0, "解析 0 条＝声明源形与解析器脱节（第 28 号形态）"
    assert len(records) == len(want), f"解析条数 {len(records)} ≠ 现算条数 {len(want)}＝两本账不同源"
    assert set(records) == set(want), "解析 path 全集与现算不等＝有段没被读到"
    forms = {
        type(node).__name__
        for node in ast.parse(text).body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and getattr(node.targets[0] if isinstance(node, ast.Assign) else node.target, "id", "")
        in dos._SOURCE_SECTIONS
    }
    assert forms == {"AnnAssign"}, f"真身三张表的赋值形态变了（{forms}）——本锁的前提要跟着改"
    # Assign 腿：把同一份声明源改写成「无类型标注」形，条数必须一字不减
    bare = text.replace("DOC_OWNERSHIP_DIRS: tuple[DocOwner, ...] = (", "DOC_OWNERSHIP_DIRS = (") \
               .replace("DOC_OWNERSHIP: tuple[DocOwner, ...] = (", "DOC_OWNERSHIP = (") \
               .replace("DOC_OWNERSHIP_ARCHIVE: tuple[DocOwner, ...] = (", "DOC_OWNERSHIP_ARCHIVE = (")
    assert bare != text, "改写没生效＝这条腿空跑"
    bare_records, bare_drifts = dos.parse_declaration(bare)
    assert not bare_drifts and len(bare_records) == len(records), (
        f"只认 AnnAssign＝第 28 号形态复发：bare={len(bare_records)} vs 真身={len(records)}"
    )


def test_s88_poison_then_follow_next_step_returns_green(tmp_path: Path, capsys: Any) -> None:
    """「下一步」不许是空话：字段漂移后照它跑 `--generate`，必须回 CLEAN。

    反向自测的还原半——只证"会红"不证"红得可修"，等于把判据写成抱怨。
    """
    repo = _fresh_repo(tmp_path, capsys)
    _write_decl(repo, _read_decl(repo).replace("basis='依据A'", "basis='依据A（被改过）'", 1))
    rc, out = _check(repo, capsys)
    assert rc == 1 and f"[{dos.K_FIELD}]" in out
    assert dos.main(["--generate"], repo=repo) == 0
    capsys.readouterr()  # 排掉 --generate 的横幅，否则"下一步"的输出会混进取证窗口
    rc2, out2 = _check(repo, capsys)
    assert rc2 == 0 and out2.strip() == "CLEAN", f"重投影后仍不绿＝下一步在骗人：\n{out2}"


#: ── 七态发毒表（本席「渲染出口唯一」矩阵用例复用；键＝态名，值＝只吃 repo 的动作）──
def _poison_absent(repo: Path) -> None:
    _decl_of(repo).unlink()


def _poison_parse(repo: Path) -> None:
    _write_decl(repo, "这不是 python 语法 =(")


def _poison_dup(repo: Path) -> None:
    lines = _read_decl(repo).split("\n")
    i = _locate(lines, "path='docs/full-path.md'")
    lines.insert(i + 1, lines[i])
    _write_decl(repo, "\n".join(lines))


def _poison_missing(repo: Path) -> None:
    lines = _read_decl(repo).split("\n")
    del lines[_locate(lines, "path='docs/full-path.md'")]
    _write_decl(repo, "\n".join(lines))


def _poison_extra(repo: Path) -> None:
    lines = _read_decl(repo).split("\n")
    i = _locate(lines, "path='docs/full-path.md'")
    lines.insert(i + 1, "    DocOwner(path='docs/hand-added.md', board='B06', fid='', "
                        "currency='现行', basis='盘上手加', completed=False),")
    _write_decl(repo, "\n".join(lines))


def _poison_field(repo: Path) -> None:
    raw = _read_decl(repo)
    out = raw.replace("basis='依据A'", "basis='依据A（被改过）'", 1)
    assert out != raw, "发毒打在空气上＝这条腿空跑"
    _write_decl(repo, out)


def _poison_format(repo: Path) -> None:
    _write_decl(repo, _read_decl(repo) + "#: 只动注释的排版差异\n")


ALL_POISONS: tuple[tuple[str, object], ...] = (
    (dos.K_ABSENT, _poison_absent), (dos.K_PARSE, _poison_parse), (dos.K_DUP, _poison_dup),
    (dos.K_MISSING, _poison_missing), (dos.K_EXTRA, _poison_extra), (dos.K_FIELD, _poison_field),
    (dos.K_FORMAT, _poison_format),
)


def test_s88_naming_comes_from_exactly_one_rendering_path(tmp_path: Path, capsys: Any) -> None:
    """结构锁：七态的「点名」只准出自**一条**渲染出口（禁两条码路）。

    本席变异探针实测到的真缺陷：`声明源不在盘` 这一态原先在 `check_sync` 里**手搓三行**输出，
    把渲染层拔掉它照样点名 ⇒ 七态里唯一「退化不失明」的格子。现已并回同一条 `drift_report`。
    判据形状＝拔掉出口后**每一态都失明、而 rc 仍为 1**（红照旧报、瞎话不许留），
    这比 grep AST 强：它钉的是行为，不是字面。
    """
    orig = dos.drift_report
    blind: list[str] = []
    rc_changed: list[str] = []
    try:
        for i, (state, poison) in enumerate(ALL_POISONS):
            repo = _fresh_repo(tmp_path, capsys, f"teeth{i}")
            poison(repo)  # type: ignore[operator]
            rc_t, out_t = _check(repo, capsys)
            assert rc_t == 1 and f"[{state}]" in out_t, f"有牙版自身已失效：{state}\n{out_t}"
            repo2 = _fresh_repo(tmp_path, capsys, f"neuter{i}")
            dos.drift_report = lambda drifts, ledger, current: ["OUT OF SYNC（渲染层退化版：不说哪一态）"]
            try:
                poison(repo2)  # type: ignore[operator]
                rc_n, out_n = _check(repo2, capsys)
            finally:
                dos.drift_report = orig
            if rc_n != 1:
                rc_changed.append(f"{state}:rc={rc_n}")
            if f"[{state}]" in out_n:
                blind.append(state)
    finally:
        dos.drift_report = orig
    assert not blind, f"这些态绕过渲染出口自己点名＝第二条码路，退化时不会失明：{blind}"
    assert not rc_changed, f"拔掉渲染层后 rc 语义被改（0/1 必须与旧版逐字一致）：{rc_changed}"


def test_s88_real_tree_is_clean_at_entry_level_too(tmp_path: Path, capsys: Any) -> None:
    """真树逐态全平（不是"没扫到"）：现算比对要真看见 386 量级条目后判全平。

    专防假绿形态：诊断腿扫 0 页也"全绿"。这里断言被看过的条目数与现算同源且远大于零。
    """
    ledger = dos.compute_ownership()
    rendered = dos.render_source(ledger)
    want = dos.projection_records(ledger)
    assert len(want) == len(ledger.entries) + len(ledger.archive), "投影记录数与 Ledger 不同源"
    assert len(want) > 300, f"只比对了 {len(want)} 条，量级不对＝扫描面塌陷"
    drifts = dos.compare_projection(ledger, rendered, rendered)
    structural = [d for d in drifts if d.kind != dos.K_FORMAT]
    assert structural == [], f"真树逐格比对不该有结构性漂移：{[d.render() for d in structural[:3]]}"
    # 函数契约如实钉住（本席读码＋实跑所得）：`compare_projection` 只在"字节已不等"后被调用，
    # 条目级全平时它**必然**补一枚 K_FORMAT 残差。喂同一份文本 ⇒ 残差是预期内，不是漏检。
    # 判"是否同步"的落点是 `check_sync`（下一条断言），不是这里。
    assert [d.kind for d in drifts] == [dos.K_FORMAT], f"残差形态漂移（判据口径变了）：{[d.kind for d in drifts]}"
    rc, lines = dos.check_sync(ledger, rendered, ROOT / dos.OWNERSHIP_REL)
    assert rc == 0 and lines == ["CLEAN"], f"真树 --check 现算不绿：{lines[:3]}"
    assert dos.main(["--check"], repo=ROOT) == 0
    capsys.readouterr()
