"""波次 ledger 内容地板（G-K1 同族锁·席 S74·2026-09-24）。

`test_dispatch_discipline_gate.py` 的 ledger 腿只看两件事——存在（:145）与 mtime 不比
BRIEFS 旧（:148），**一个字节都不读账本内容**。于是「建一枚空壳 `ledger` + touch」
可以全绿那两条腿＝账建了但没人往里记（本波教义点名的空转门形态）。

本锁在**不触碰该门任何判据**的前提下补一层实体地板，对同一批执法对象生效：

- ① 字节数 ≥ ``LEDGER_MIN_BYTES``（防 1 字节占位）；
- ② 至少一枚一级标题 ``# ``（账要有名分）；
- ③ ``## `` 二级节 ≥ ``LEDGER_MIN_SECTIONS``（防只有标题与散文）；
- ④ 含 ``YYYY-MM-DD`` 时刻锚（无时刻的账不算账）。

扫描面唯一来源＝被对照门的 ``_wave_dirs()``（同谓词 import 复用，禁第二本波目录名册）；
另设一致性腿：若该门的圈定与本锁现算不一致 ⇒ 本锁红（**只会更严不会更绿**的方向）。
地板字面量手写在册 + AST 自锁 + 「只准升不准降」下限锁（仿 ``test_baseline_literals_are_handwritten``
族规）。反向自测：空账 / 仅标题 / 短账 / 缺时刻锚各须被咬；形状良好的合成账须放行。
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_LEDGER_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# 手写字面量地板（腿 test_floor_literals_are_handwritten 执法"不许派生、不许降"）。
# 取值依据＝立门当刻（2026-09-24T00:3xZ）三枚在册波账的现算最小形状，只收紧不放宽。
LEDGER_MIN_BYTES: int = 512
LEDGER_MIN_SECTIONS: int = 2
SCOPE_MIN_WAVES: int = 1

#: 上述三个常量的"只准升不准降"下限（等于立门当日现值；改小任何一个 ⇒ 本锁当场红）。
_FLOOR_NOT_BELOW = {
    "LEDGER_MIN_BYTES": 512,
    "LEDGER_MIN_SECTIONS": 2,
    "SCOPE_MIN_WAVES": 1,
}


def _discipline_gate_module():
    """以文件路径装载 G-K1 门模块本体（单一来源取波目录名册，绝不复制判据）。"""
    path = _TESTS_DIR / "test_dispatch_discipline_gate.py"
    spec = importlib.util.spec_from_file_location("_gk1_discipline_src_for_floor", path)
    assert spec is not None and spec.loader is not None, f"装载 {path} 失败，扫描面失去唯一来源"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _in_scope_waves() -> list[Path]:
    module = _discipline_gate_module()
    wave_dirs = module.__dict__["_wave_dirs"]  # dict 取用＝同函数、非复制，也避开私有名歧义
    return list(wave_dirs())


def _content_findings(name: str, text: str, size: int) -> list[str]:
    """单枚 ledger 的实体地板判据（纯函数：真树与合成注毒共用同一把尺子）。"""
    findings: list[str] = []
    if size < LEDGER_MIN_BYTES:
        findings.append(f"{name}: 字节数 {size} 低于地板 {LEDGER_MIN_BYTES}（占位空壳）")
    if not any(line.startswith("# ") for line in text.splitlines()):
        findings.append(f"{name}: 无一级标题，账没有名分")
    if sum(1 for line in text.splitlines() if line.startswith("## ")) < LEDGER_MIN_SECTIONS:
        findings.append(f"{name}: `## ` 二级节不足 {LEDGER_MIN_SECTIONS} 枚（标题与散文撑不起账目）")
    if not _LEDGER_DATE.search(text):
        findings.append(f"{name}: 无 YYYY-MM-DD 时刻锚（没记时刻的账不算账）")
    return findings


def _scope_findings(waves: list[Path]) -> list[str]:
    """扫描面地板：在场波数为零＝「把面缩到空 ⇒ 全绿」那一型，必须红。"""
    if len(waves) < SCOPE_MIN_WAVES:
        return [f"执法波目录数 {len(waves)} 低于地板 {SCOPE_MIN_WAVES}——缩面蒙绿保护触发"]
    return []


def test_scan_surface_floor_and_single_source() -> None:
    waves = _in_scope_waves()
    assert not _scope_findings(waves), "；".join(_scope_findings(waves))
    # 一致性腿：本锁现算 == G-K1 门现算（同一函数同一时刻两次求值，防装载出第二个世界）。
    assert waves == _in_scope_waves(), "波目录名册两次现算不等＝取数面不稳定，本锁拒判绿"
    # 反向自证：空面必须被抓，否则地板腿是空跑。
    assert _scope_findings([]), "空扫描面必须判红（反向自测）"


def test_real_wave_ledgers_have_body() -> None:
    findings: list[str] = []
    for wave in _in_scope_waves():
        ledger = wave / "ledger"
        if not ledger.is_file():
            findings.append(f"{wave.name}: ledger 不在盘（存在腿归 G-K1，本锁同样不许空转）")
            continue
        text = ledger.read_text(encoding="utf-8", errors="replace")
        findings.extend(_content_findings(wave.name, text, ledger.stat().st_size))
    assert not findings, "波次 ledger 实体地板被破：\n  " + "\n  ".join(findings)


def test_synthetic_hollow_ledgers_are_caught() -> None:
    """注毒自证（纯内存不落盘）：四条腿逐腿咬合，正向对照放行。"""
    # 空账：四腿全中。
    empty = _content_findings("x", "", 0)
    assert len(empty) == 4, f"空账应四条全红，实得 {empty}"
    # 仅标题：名分腿放行、其余三条抓（证明不是恒红门）。
    title_only = _content_findings("x", "# ledger\n", len("# ledger\n"))
    assert len(title_only) == 3 and not any("名分" in f for f in title_only), (
        f"仅标题账应放过标题腿、咬住其余三腿，实得 {title_only}"
    )
    # 形状齐全但缺时刻锚：只被时刻腿咬。
    no_date = "x" * 600 + "\n# ledger\n## 进度\n内容\n## 账目\n内容\n"
    only_date = _content_findings("x", no_date, len(no_date))
    assert len(only_date) == 1 and "时刻锚" in only_date[0], f"缺锚账应恰被时刻腿咬，实得 {only_date}"
    # 形状齐全但薄于字节地板：只被字节腿咬。
    thin = "# ledger\n## 进度 2026-09-24\na\n## 账目\nb\n"
    only_thin = _content_findings("x", thin, len(thin))
    assert len(only_thin) == 1 and "字节数" in only_thin[0], f"薄账应恰被字节腿咬，实得 {only_thin}"
    # 正向对照：一枚达标合成账 ⇒ 放行（防恒红假执法）。
    good = "# ledger — demo\n" + ("## 进度（2026-09-24）\n" + ("内容行" * 40 + "\n") * 8) + "## 账目（2026-09-24）\n略\n"
    assert _content_findings("x", good, len(good)) == [], "达标合成账被误咬＝判据过度执法"


def test_floor_literals_are_handwritten() -> None:
    """三个地板常量必须是**模块顶层手写字面整数**（防派生式基线永远绿），且只准升不准降。"""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.expr):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id in _FLOOR_NOT_BELOW:
                value = node.value  # type: ignore[attr-defined]
                assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
                    f"{target.id} 不是手写字面量——地板不许派生"
                )
                seen[target.id] = value.value
    assert set(seen) == set(_FLOOR_NOT_BELOW), f"自锁只见到 {set(seen)}，应含 {set(_FLOOR_NOT_BELOW)}"
    for name, floor in _FLOOR_NOT_BELOW.items():
        assert seen[name] >= floor, f"{name} 被从 {floor} 降到 {seen[name]}——地板只准升"
