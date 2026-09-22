"""好感度八档态度文案单一真身常驻锁（SEAT-S-AFFCOPY，2026-09-21 统一波）。

钉死两件事，缺一条即红：

1. **全树只有一份八档态度文案真身** —— 真身 =
   `plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py` 的
   ``_ATTITUDE_TIERS``（注入 prompt 的档位基调；文档权威 docs/affinity-design.md §4）。
2. **展示面是投影、不是抄本** —— 算法卡档位表 ``_TIER_TABLE`` 的三列（档位名 /
   区间边界 / 态度句）与关系层 ``DEFAULT_ATTITUDE`` 的同句部分，一律由真身派生；
   派生面只许追加自己那一层的差异尾句（如「（初始 10 在此档）」）。

两路判据互相独立、都必须干净：
- **AST 判据**：`plugins/**.py` 里任何字符串字面量（隐式拼接由 AST 自带合并、`+` 拼接由
  本门展平）与某一档态度句**全等**——按文案普查器 `scripts/copy_duplication_census.py`
  的归一化口径（标点/全半角差异不算两样）——出现在真身之外 ⇒ 第二真身 ⇒ 红。
- **文本判据**：真身之外任何 .py 的源码文本里**出现**整句态度文案（注释与 docstring
  里再抄一份也算分叉起点）⇒ 红。

真身被删、被掏空、被换序、被掺进敌意措辞同样红（``_assert_valid_tier_shape``）。
行号一律不写死：定位靠名字与内容，改文件、挪行都不影响本门。

零用户可见回归的凭据：``_DISPLAY_TABLE_SHA256`` 钉在**收编之前**的展示表 JSON 摘要
（收编实跑复现同一摘要，逐行改前/改后见
.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-AFFCOPY.md）。日后谁改八档展示文案，
先撞这条红——有意改动就带理由重录摘要，不许顺手改判据。

红线自查（AGENTS 第 8 条 / docs §4）：任何一档（含最低档与负值档）不得出现敌意/攻击/
强硬措辞；展示文案不得出现固定加减数值（算法说明只许定性）。
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PKG = REPO_ROOT / "plugins" / "bot_unified_runtime"
HOME_REL = "plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py"
HOME_PATH = REPO_ROOT / HOME_REL
DISPLAY_REL = "plugins/bot_unified_runtime/domains/chat_reply/capabilities/affinity.py"
RELATIONSHIP_REL = "plugins/bot_unified_runtime/domains/chat_reply/character/relationship.py"
CENSUS_PATH = REPO_ROOT / "scripts" / "copy_duplication_census.py"

_TIER_IDS = list(range(-4, 4))
# 收编前的展示表快照（用户此刻看到的口径）：区间串是格式而非文案，逐条钉死。
_EXPECTED_RANGES = [
    "[-100, -75)", "[-75, -50)", "[-50, -25)", "[-25, 0)",
    "[0, +25)", "[+25, +50)", "[+50, +75)", "[+75, +100]",
]
# 收编实跑复现：sha256(json.dumps(_TIER_TABLE, ensure_ascii=False, sort_keys=True))。
_DISPLAY_TABLE_SHA256 = "14806016ad0c339506834bdedb5326aa2e0e679c10af54be65e53c3bfcfa8520"

# §4 红线 2：负向档位只写距离感；任何一档都不得出现敌意/攻击/强硬措辞。
_HOSTILE_WORDS = (
    "冷漠", "抗拒", "愤怒", "恶心", "肮脏", "低贱", "敌视", "厌恶",
    "强硬", "粗鲁", "贬低", "谴责", "攻击", "辱骂",
)
# 算法说明一律定性（F4 用户裁定）：展示文案不得写「加几减几」式固定数值。
_FIXED_DELTA_RE = re.compile(r"[加减]\s*\d+\s*分|[+\-]\d+\s*起|\d+\s*分的?\s*(?:加减|步长)")


def _load_census():
    """按路径加载文案普查器的归一化口径（折形判据只有一份，本门不另造一套）。"""
    assert CENSUS_PATH.exists(), f"普查器缺位，本门失去归一化口径：{CENSUS_PATH}"
    module_name = "copy_duplication_census_imported_by_affinity_tier_gate"
    spec = importlib.util.spec_from_file_location(module_name, CENSUS_PATH)
    assert spec is not None and spec.loader is not None, "普查器加载失败"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


_census = _load_census()


def _normalize(text: str) -> str:
    return str(_census.normalize(text))


def _key(path: Path) -> str:
    """仓库内文件用仓库相对路径做键；仓库外（注毒临时件）退回完整 posix 路径。"""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _flatten_constant(node: ast.AST) -> str | None:
    """字符串字面量 / 隐式拼接（AST 已合）/ `+` 拼接 → 展平成一条文本，否则 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _flatten_constant(node.left)
        right = _flatten_constant(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _ast_string_literals(root: Path) -> dict[str, list[tuple[int, str]]]:
    """root 下每个 .py 的字符串字面量：键（见 `_key`）→ [(行号, 文本)]。"""
    found: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rows: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Constant, ast.BinOp)):
                text = _flatten_constant(node)
                if text and text.strip():
                    rows.append((int(getattr(node, "lineno", 0)), text))
        if rows:
            found[_key(path)] = rows
    return found


def _source_texts(root: Path) -> dict[str, str]:
    """root 下每个 .py 的源码全文（注释与 docstring 一并算，文本判据要用）。"""
    texts: dict[str, str] = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            texts[_key(path)] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return texts


def _attitude_copy_hits_ast(
    literals_by_file: dict[str, list[tuple[int, str]]],
    instructions: list[str],
    *,
    home_rel: str = HOME_REL,
) -> list[str]:
    """AST 判据：真身之外与某一档态度句全等的字面量 ⇒ 第二真身。"""
    needles = {_normalize(text): text for text in instructions if text.strip()}
    hits: list[str] = []
    for rel, rows in sorted(literals_by_file.items()):
        if rel == home_rel:
            continue
        for lineno, literal in rows:
            stolen = needles.get(_normalize(literal))
            if stolen is not None:
                hits.append(f"{rel}:{lineno} 又抄了一份档态度句「{stolen}」")
    return hits


def _attitude_copy_hits_text(
    texts_by_file: dict[str, str],
    instructions: list[str],
    *,
    home_rel: str = HOME_REL,
) -> list[str]:
    """文本判据：真身之外源码里出现整句态度文案（含注释/docstring）⇒ 第二真身。"""
    hits: list[str] = []
    for rel, text in sorted(texts_by_file.items()):
        if rel == home_rel:
            continue
        folded = _normalize(text)
        for instruction in instructions:
            needle = _normalize(instruction)
            if not needle or needle not in folded:
                continue
            lineno = next(
                (
                    index
                    for index, line in enumerate(text.splitlines(), start=1)
                    if needle in _normalize(line)
                ),
                0,
            )
            hits.append(f"{rel}:{lineno} 源码里再现了档态度句「{instruction}」")
    return hits


def _int_literal(node: ast.AST) -> int | None:
    """整数字面量，含负号写法（`-4` 在 AST 里是 UnaryOp，不是 Constant）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return int(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
    ):
        return -int(node.operand.value)
    return None


def _tier_rows_from_source(path: Path) -> list[tuple[int, str, str]]:
    """读某个 .py 里 ``_ATTITUDE_TIERS`` 的字面八档（档 id、档位名、态度句）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None or not any(
            isinstance(target, ast.Name) and target.id == "_ATTITUDE_TIERS" for target in targets
        ):
            continue
        if not isinstance(value, ast.Tuple):
            raise TypeError("_ATTITUDE_TIERS 必须是档元组字面量（投影面按序取数）")
        rows: list[tuple[int, str, str]] = []
        for element in value.elts:
            if not isinstance(element, ast.Tuple) or len(element.elts) != 3:
                raise AssertionError("每档必须是 (档 id, 档位名, 态度句) 三元组")
            raw_id, raw_name, raw_instruction = element.elts
            tier_id = _int_literal(raw_id)
            if tier_id is None:
                raise TypeError(f"档 id 必须是整数字面量，实际 {ast.dump(raw_id)}")
            name = _flatten_constant(raw_name)
            instruction = _flatten_constant(raw_instruction)
            if not name or not instruction:
                raise AssertionError("档位名与态度句必须是字符串字面量（不许拼接出第二份口径）")
            rows.append((tier_id, name, instruction))
        return rows
    raise AssertionError(f"{path.name} 里找不到 _ATTITUDE_TIERS 真身")


def _assert_valid_tier_shape(rows: list[tuple[int, str, str]], *, where: str) -> None:
    if not rows:
        raise AssertionError(f"{where}：八档态度真身被删空了（投影面会静默塌成空表）")
    if [row[0] for row in rows] != _TIER_IDS:
        raise AssertionError(f"{where}：档 id 必须是连续的 {_TIER_IDS}，实际 {[row[0] for row in rows]}")
    for tier_id, name, instruction in rows:
        if not name.strip():
            raise AssertionError(f"{where}：档 {tier_id} 缺档位名")
        if len(instruction.strip()) < 8:
            raise AssertionError(f"{where}：档 {tier_id} 态度句短到不成句")
        for word in _HOSTILE_WORDS:
            if word in instruction:
                raise AssertionError(f"{where}：档 {tier_id} 态度句含敌意/强硬措辞「{word}」")


def live_tiers() -> tuple[tuple[int, str, str], ...]:
    from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
        attitude_tiers,
    )

    return attitude_tiers()


# ---------------------------------------------------------------------------
# 1. 真身在位、形状不变（home 被删＝红）
# ---------------------------------------------------------------------------


def test_home_declares_the_eight_tiers() -> None:
    rows = _tier_rows_from_source(HOME_PATH)
    _assert_valid_tier_shape(rows, where="真身 _ATTITUDE_TIERS")
    assert list(rows) == list(live_tiers()), "AST 读到的真身与运行时 attitude_tiers() 不一致（垫片吞了改动？）"
    assert len({_normalize(row[2]) for row in rows}) == 8, "八档态度句必须互不相同"


# ---------------------------------------------------------------------------
# 2. 展示面是投影（抄回去＝红，派生断了也红）
# ---------------------------------------------------------------------------


def test_display_table_is_projection_of_home() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
        affinity as display,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
        tier_display_range,
    )

    notes = dict(display._TIER_DISPLAY_NOTES)
    tier_ids = {row[0] for row in live_tiers()}
    assert set(notes) <= tier_ids, f"展示注脚挂在不存在的档：{set(notes) - tier_ids}"
    expected = [
        {
            "label": name,
            "range": tier_display_range(tier_id),
            "attitude": instruction + notes.get(tier_id, ""),
        }
        for tier_id, name, instruction in live_tiers()
    ]
    assert display._TIER_TABLE == expected, "算法卡档位表不再是真身的投影（抄回去了，或派生断了）"
    assert [row["range"] for row in display._TIER_TABLE] == _EXPECTED_RANGES, "档位区间与 §4 口径不符"
    for row, (tier_id, _name, instruction) in zip(display._TIER_TABLE, live_tiers()):
        assert row["attitude"].startswith(instruction), f"档「{row['label']}」展示文案与注入真身分叉"
        tail = row["attitude"][len(instruction):]
        assert tail == notes.get(tier_id, ""), f"档「{row['label']}」夹带了未登记的展示措辞"


def test_display_surface_unchanged_by_unification() -> None:
    """用户可见零回归：展示表摘要仍等于收编前快照（改八档文案必须先撞这条红）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
        _TIER_TABLE,
    )

    digest = hashlib.sha256(
        json.dumps(_TIER_TABLE, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert digest == _DISPLAY_TABLE_SHA256, "八档展示文案变了：确认有意改动后重录摘要，否则回滚"


def test_display_copy_carries_no_fixed_delta_numbers() -> None:
    """算法说明只许定性（F4 裁定）：八档展示文案与注脚都不得写固定加减数值。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
        _TIER_DISPLAY_NOTES,
        _TIER_TABLE,
    )

    for note in _TIER_DISPLAY_NOTES.values():
        assert not _FIXED_DELTA_RE.search(note), f"展示注脚写了固定加减数值：{note}"
    for row in _TIER_TABLE:
        assert not _FIXED_DELTA_RE.search(row["attitude"]), f"档「{row['label']}」文案含固定加减数值"


def test_algorithm_prose_tier_names_match_source() -> None:
    """算法说明手写的八档名必须仍是真身那八个（防「档位名称」这一维各自漂移）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.affinity import (
        ALGORITHM_TEXT,
    )

    line = next((row for row in ALGORITHM_TEXT.splitlines() if row.startswith("档位态度：")), "")
    assert line, "算法说明里的档位态度行不见了"
    listed = [
        token.strip()
        for token in line.split("：", 1)[1].split(" 共", 1)[0].split("/")
        if token.strip()
    ]
    bracket_suffix = re.compile(r"（[^）]*）$")
    names = [name for _tier_id, name, _instruction in live_tiers()]
    assert len(listed) == len(names), f"算法说明列了 {len(listed)} 档，真身有 {len(names)} 档"
    for shown, canonical in zip(listed, names):
        assert shown == bracket_suffix.sub("", canonical), f"档位名分叉：算法说明「{shown}」vs 真身「{canonical}」"


def test_relationship_attitudes_are_derived_where_identical() -> None:
    """关系层 familiar/close 与 §4 同句的部分取真身投影，只留自己的差异尾句。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.relationship import (
        DEFAULT_ATTITUDE,
    )

    by_id = {row[0]: row[2] for row in live_tiers()}
    assert DEFAULT_ATTITUDE["familiar"] == by_id[0], "familiar 与档 0 又分叉了"
    assert DEFAULT_ATTITUDE["close"].startswith(by_id[2]), "close 与档 +2 又分叉了"
    assert DEFAULT_ATTITUDE["close"] != by_id[2], "close 的关系层尾句被吞了（这是行为变更）"
    for key, text in DEFAULT_ATTITUDE.items():
        for word in _HOSTILE_WORDS:
            assert word not in text, f"relationship.{key} 含敌意/强硬措辞「{word}」"


# ---------------------------------------------------------------------------
# 3. 生产面只剩一份（双判据）
# ---------------------------------------------------------------------------


def test_no_second_copy_of_attitude_text_ast_scan() -> None:
    instructions = [row[2] for row in live_tiers()]
    hits = _attitude_copy_hits_ast(_ast_string_literals(RUNTIME_PKG), instructions)
    assert not hits, (
        "出现第二份八档态度文案真身（改回投影，或按 tests/test_copy_single_source.py 逐簇登记理由）：\n"
        + "\n".join(hits)
    )


def test_no_second_copy_of_attitude_text_source_scan() -> None:
    instructions = [row[2] for row in live_tiers()]
    hits = _attitude_copy_hits_text(_source_texts(RUNTIME_PKG), instructions)
    assert not hits, "源码文本再现了八档态度文案（注释里再抄一份也算分叉起点）：\n" + "\n".join(hits)


def test_gate_scan_surface_is_real() -> None:
    """判据输入自证：三处消费点在位、扫描面没塌（防空转绿——真身被搬走本门先红）。"""
    assert HOME_PATH.exists(), "八档态度真身文件不在了"
    assert (REPO_ROOT / DISPLAY_REL).exists(), "展示面文件不在了"
    assert (REPO_ROOT / RELATIONSHIP_REL).exists(), "关系层文件不在了"
    assert len(list(RUNTIME_PKG.rglob("*.py"))) >= 400, "生产面异常收缩，本门在扫一堆空目录"
    assert len(_ast_string_literals(RUNTIME_PKG)) >= 300, "AST 扫描面异常收缩"
    assert len(_source_texts(RUNTIME_PKG)) >= 400, "文本扫描面异常收缩"


# ---------------------------------------------------------------------------
# 4. 注毒自证：判据不是摆设
# ---------------------------------------------------------------------------


def test_poison_second_copy_reds_ast_judgment() -> None:
    """造一份第二副本喂判据 ⇒ 必红并点名文件行号。"""
    stolen = live_tiers()[3][2]
    poisoned = {
        HOME_REL: [(936, stolen)],
        "plugins/bot_unified_runtime/domains/ops/poison_tier_copy.py": [(7, stolen)],
    }
    hits = _attitude_copy_hits_ast(poisoned, [row[2] for row in live_tiers()])
    assert len(hits) == 1, f"注毒副本未被 AST 判据抓到（实际 {hits}）——判据已失效"
    assert "poison_tier_copy.py:7" in hits[0], hits[0]


def test_poison_punctuation_drift_still_red() -> None:
    """换标点/全半角想蒙混 ⇒ 归一化判据照样红（藏副本不许靠标点差异）。"""
    original = live_tiers()[-1][2]
    drifted = original.replace("：", ":").replace("、", " ")
    assert drifted != original
    poisoned = {
        HOME_REL: [(1, original)],
        "plugins/bot_unified_runtime/domains/ops/poison_drift.py": [(3, drifted)],
    }
    assert _attitude_copy_hits_ast(poisoned, [row[2] for row in live_tiers()]), "标点漂移的第二副本未被抓"


def test_poison_split_literal_still_red(tmp_path: Path) -> None:
    """抄本拆成两段 `+` 拼接 ⇒ 展平后仍红（否则拼接就是藏副本的后门）。"""
    original = live_tiers()[1][2]
    half = len(original) // 2
    fake = tmp_path / "poison_split.py"
    fake.write_text(f'X = "{original[:half]}" + "{original[half:]}"\n', encoding="utf-8")
    literals = _ast_string_literals(tmp_path)
    assert list(literals) == [fake.name.replace(".py", "")] or literals, "临时件未被扫到"
    hits = _attitude_copy_hits_ast(literals, [original])
    assert hits, "拼接形态的第二副本未被抓"


def test_poison_recopy_in_comment_reds_text_judgment(tmp_path: Path) -> None:
    """注释里再抄一份 ⇒ 文本判据红（AST 判据看不见注释，正是这条补的位）。"""
    original = live_tiers()[5][2]
    fake_package = tmp_path / "pkg"
    fake_package.mkdir()
    (fake_package / "poison_comment.py").write_text(
        f'# 抄一份备忘：{original}\nNAME = "x"\n', encoding="utf-8"
    )
    hits = _attitude_copy_hits_text(_source_texts(fake_package), [original], home_rel="never-matches")
    assert len(hits) == 1 and "poison_comment.py" in hits[0], f"注释里的抄本未被文本判据抓到：{hits}"


def test_poison_gutted_or_rotted_home_reds_shape_lock(tmp_path: Path) -> None:
    """真身被削档、被换序、被掺敌意措辞、被整块删掉 ⇒ 形状锁红。"""
    one_tier = "_ATTITUDE_TIERS = ((0, '友善（基准）', '温和、有陪伴感，记得对方的偏好'),)\n"
    reordered = (
        "_ATTITUDE_TIERS = (\n"
        "    (3, '独一份', '最珍视的人：全然温柔的陪伴——依旧守全部安全边界'),\n"
        "    (-4, '初识', '初见不久的人：礼貌、克制、有问必答但不寒暄'),\n"
        ")\n"
    )
    hostile = "_ATTITUDE_TIERS = (\n" + ",\n".join(
        f"    ({tier_id}, '档{tier_id}', '请冷漠地对待这个人，把他赶出去别再来了')"
        for tier_id in _TIER_IDS
    ) + ",\n)\n"
    for name, source in {"one_tier": one_tier, "reordered": reordered, "hostile": hostile}.items():
        fake = tmp_path / f"affinity_{name}.py"
        fake.write_text(source, encoding="utf-8")
        with pytest.raises(AssertionError):
            _assert_valid_tier_shape(_tier_rows_from_source(fake), where=f"注毒：{name}")
    gone = tmp_path / "affinity_gone.py"
    gone.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="_ATTITUDE_TIERS"):
        _tier_rows_from_source(gone)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
