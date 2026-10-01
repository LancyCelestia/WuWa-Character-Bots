"""渲染哈希册旁车自签锁（LEDGER_TAMPER）注毒自证（2026-09-27，S-HASH-TAMPERPROOF-b）。

病灶（ECHO-WRITEBACK-FORENSIC §2/§3，09-26 18:12 事故）：``tests/render_hashes.json``
被**工具外单行直改**（echo 行烙成在飞中间态 ``82a6ddd…``），而 ``--write`` 只有全量
单发 ``write_text``——工具产不出"HEAD 原册+恰好一行变更"的册态。册体自身没有
"谁/何时全量重录"的自证元数据，机器无法区分「工具全量产出」与「手改同形产物」。

修法（本锁所钉）：``write()`` 全量写册成功后另落旁车 ``render_hashes.meta.json``
= {full_write_at, entry_count, body_sha256}；``--check`` 独立腿校验自签，命中报
``LEDGER_TAMPER``，与 DRIFT 分账不混报。

纪律：
- 全离线；一切演练在 tmp_path 假树上做，monkeypatch 模块级 MANIFEST/META/ROOT
  三个全局名（实现按全局名运行期查找，故 monkeypatch 生效）；
- **禁碰真册真旁车**：本文件不调用任何面向仓库真路径的 --write，
  test_real_paths_untouched 自证真册真旁车在演练前后字节不变；
- 今日真实现状（meta 从未由新码落过）＝ ``--check`` 报 LEDGER_TAMPER(missing)，
  属设计内诚实红——不做"meta 不存在就跳过"的宽松腿。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import verify_hashes as vh

REAL_MANIFEST = ROOT / "tests" / "render_hashes.json"
REAL_META = ROOT / "tests" / "render_hashes.meta.json"

TAMPER = "LEDGER_TAMPER"


def _split(problems: list[str]) -> tuple[list[str], list[str]]:
    """按代号分账：篡改腿 vs 漂移腿（含 MISSING/NEW/DRIFT/STALE）。"""
    tamper = [p for p in problems if p.startswith(TAMPER)]
    drift = [p for p in problems if not p.startswith(TAMPER)]
    return tamper, drift


@pytest.fixture()
def fake_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """假树（ROOT 重定向）+ 假册/假旁车路径；真树零接触。"""
    tree = tmp_path / "tree"
    for name in vh.TRACKED_FILES:
        p = tree / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"deliverable body: {name}\n", encoding="utf-8", newline="\n")
    manifest = tmp_path / "render_hashes.json"
    meta = tmp_path / "render_hashes.meta.json"
    monkeypatch.setattr(vh, "ROOT", tree)
    monkeypatch.setattr(vh, "MANIFEST", manifest)
    monkeypatch.setattr(vh, "META", meta)
    return tree, manifest, meta


def _tamper_manifest(manifest: Path, mutate) -> None:
    """模拟工具外改册：load→改→dump 直写，绕过 write()。"""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    mutate(data)
    manifest.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_d_write_then_check_all_green(fake_tree) -> None:
    """注毒台基线（d）：正常全量 write → check 全绿，旁车在位且自签可重算。"""
    _tree, manifest, meta = fake_tree
    vh.write()
    assert vh.check(quiet=True) == []
    recorded = json.loads(manifest.read_text(encoding="utf-8"))
    # 旁车落盘而**册内零加键**：键集恒等 TRACKED_FILES（coverage 门 :111 同判据）。
    assert set(recorded) == set(vh.TRACKED_FILES)
    body = json.loads(meta.read_text(encoding="utf-8"))
    assert set(body) == {"full_write_at", "entry_count", "body_sha256"}
    assert body["entry_count"] == len(vh.TRACKED_FILES)
    assert body["body_sha256"] == hashlib.sha256(vh.canonical_manifest_bytes()).hexdigest()


def test_a_external_single_line_edit_is_ledger_tamper(fake_tree) -> None:
    """注毒（a，09-26 事故形态复现）：工具外改任一行 → LEDGER_TAMPER 必响，
    且与 DRIFT 可判别——两腿各报各的代号，篡改账不并进漂移账，也不因
    "改的行值恰好等于盘上现值"（DRIFT 全绿）而漏报（见 value-agnostic 腿）。"""
    _tree, manifest, _meta = fake_tree
    vh.write()
    assert vh.check(quiet=True) == []

    def _mutate(data: dict[str, str]) -> None:
        victim = vh.TRACKED_FILES[0]
        data[victim] = "f" * 64  # 烙一个不属于任何版本的墓碑值，同 82a6ddd

    _tamper_manifest(manifest, _mutate)
    problems = vh.check(quiet=True)
    tamper, drift = _split(problems)
    assert tamper, "工具外改册未触发旁车自签腿（09-26 事故可重演）"
    assert any(TAMPER in p and manifest.name in p for p in tamper)
    assert drift  # 该文件盘上字节≠册值，DRIFT 腿同时报——但两账分立
    assert all(p.startswith(("MISSING", "NEW", "DRIFT", "STALE")) for p in drift)
    assert not any(TAMPER in p for p in drift), "篡改账混进了漂移账"
    assert not any("DRIFT" in p for p in tamper), (
        "LEDGER_TAMPER 行含 'DRIFT' 子串会污染 coverage 门的 _drift_files 解析"
    )


def test_a2_format_only_tamper_detected_with_zero_drift(fake_tree) -> None:
    """注毒（a 补强）：值一字不改、只把缩进 2→4 重排（json 解析后全等，
    DRIFT/NEW/STALE 全绿）——自签仍断 ⇒ 证明篡改腿不依附漂移腿，独立成立。"""
    _tree, manifest, _meta = fake_tree
    vh.write()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(
        json.dumps(data, ensure_ascii=False, indent=4, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    problems = vh.check(quiet=True)
    tamper, drift = _split(problems)
    assert drift == [], f"值未变不应有漂移账：{drift}"
    assert any("重算哈希" in p for p in tamper), "同形重排册体必须被自签腿抓住"


def test_b_meta_missing_is_ledger_tamper_missing(fake_tree) -> None:
    """注毒（b）：删旁车 → LEDGER_TAMPER(missing)；删前全绿自证红由删除造成。"""
    _tree, _manifest, meta = fake_tree
    vh.write()
    assert vh.check(quiet=True) == []
    meta.unlink()
    problems = vh.check(quiet=True)
    tamper, _drift = _split(problems)
    assert len(tamper) == 1
    assert tamper[0].startswith(TAMPER) and "旁车缺失" in tamper[0]


def test_c_entry_count_drift_detected(fake_tree) -> None:
    """注毒（c）：册内条目数漂移（加一行假条目）→ entry_count 腿点名报数。"""
    _tree, manifest, _meta = fake_tree
    vh.write()

    def _mutate(data: dict[str, str]) -> None:
        data["bogus/entry.html"] = "0" * 64

    _tamper_manifest(manifest, _mutate)
    problems = vh.check(quiet=True)
    tamper, drift = _split(problems)
    assert any("条目数漂移" in p for p in tamper), f"entry_count 腿未响：{tamper}"
    assert any(p.startswith("STALE") for p in drift), "假条目应同时被在册跟踪集腿点名"


def test_write_never_adds_keys_into_manifest(fake_tree) -> None:
    """旁车在**册外**：write() 后册体键集与 TRACKED_FILES 严格全等，
    不塞 meta 键（coverage 门 :111 键集全等断言的tmp树镜像锁）。"""
    _tree, manifest, _meta = fake_tree
    vh.write()
    recorded = json.loads(manifest.read_text(encoding="utf-8"))
    assert set(recorded) == set(vh.TRACKED_FILES)
    assert "full_write_at" not in recorded and "body_sha256" not in recorded


def test_real_paths_untouched() -> None:
    """斥离锁：本文件全部演练只写 tmp_path；真册与真旁车不被任何用例改写。
    （真旁车今日不存在＝设计内诚实红的第一态，这里只做存在性快照比对，
    不创建、不删除。）"""
    before = (
        REAL_MANIFEST.read_bytes(),
        REAL_META.read_bytes() if REAL_META.is_file() else None,
    )
    vh.check(quiet=True)  # 只读入口在真路径上跑一次，不得写盘
    after = (
        REAL_MANIFEST.read_bytes(),
        REAL_META.read_bytes() if REAL_META.is_file() else None,
    )
    assert after == before
