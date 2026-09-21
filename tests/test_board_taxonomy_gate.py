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

BOARDS_DIR = ROOT / "docs" / "boards"
EXPECTED_BOARD_COUNT = 10
_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
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
    """每张生成页必须同时有 AUTO 段与统一正文小节（统一规范的可执行形态）。"""
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


def test_board_docs_do_not_handwrite_volatile_counts() -> None:
    """标记外的人写正文同样不许手写会漂移的计数（与叙述文档同一口径）。"""
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
