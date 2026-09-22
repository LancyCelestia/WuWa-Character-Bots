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
