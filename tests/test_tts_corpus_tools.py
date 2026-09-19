"""T106 冒烟门：scripts/tts_corpus/ 四支仓外语料工具收编副本的完整性门。

治理对象=M-61「仓外交付物零版本零登记」工具链半：GPT-SoVITS 引擎目录散落的
语料扫描/选片/清单/听写四支脚本，收编为仓内版本保护副本（原样收编不修 bug，
已知缺陷见各副本溯源块与 report-T106.md）。

本门四层：
  1. 溯源块存在且字段齐全（原路径/原件 sha256/收编日期/缺陷指针）；
  2. 副本溯源块之后的字节流 sha256 == 台账锚定值（防仓内手改漂移）；
  3. 与引擎原件逐字节一致（双向防漂移；引擎目录缺失=SKIP 不假红）；
  4. 行为面冒烟：有 __main__ 护栏的两支可安全 import；transcribe_refs 的
     argparse --help 子进程可跑（解析在副作用之前，零写盘）。
     pick_refs / make_listening_checklist 为顶层执行脚本（import 即按硬编码
     绝对路径写引擎 refs/），结构上禁 import，只做语法与漂移门——该分类由
     test_toplevel_executors_stay_unimportable 锁定。
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "scripts" / "tts_corpus"
ENGINE_ROOT = Path(r"C:\Software\GPT-SoVITS-V2Pro")
SENTINEL = "# === T106 溯源块结束"

# 文件名 → (引擎相对路径, 原件 sha256 锚；同时落在各副本溯源块内)
ANCHORS: dict[str, tuple[str, str]] = {
    "scan_durations.py": (
        "tools/scan_durations.py",
        "d1ea0870b054aea4769ad30897c7e1dcd57996d6e25c2ca793980ed273e6bf8b",
    ),
    "pick_refs.py": (
        "tools/pick_refs.py",
        "0ed14796c763e2c0236b5e2a9b1e95cb9c3da2a836a67ccb8a876358128e5e9f",
    ),
    "make_listening_checklist.py": (
        "tools/make_listening_checklist.py",
        "076c5c64eda4da160f5449dc7d7b43d8a022ff6acd8ba6aa63e7515773b402f8",
    ),
    "transcribe_refs.py": (
        "tools/asr/transcribe_refs.py",
        "7d2e8962483ed6f7adcc58519d20856612ba878e5d5a6cd709540bed1d944306",
    ),
}
# 有 __main__ 护栏、import 无副作用的两支
MODULE_SAFE = ("scan_durations.py", "transcribe_refs.py")
# 顶层执行脚本：import 即按硬编码绝对路径写引擎 refs/，禁 import
TOPLEVEL = ("pick_refs.py", "make_listening_checklist.py")


def _header(name: str) -> str:
    raw = (CORPUS_DIR / name).read_bytes()
    idx = raw.find(SENTINEL.encode("utf-8"))
    assert idx != -1, f"{name}: 缺溯源块哨兵行"
    return raw[:idx].decode("utf-8", errors="replace")


def _tail_sha(name: str) -> str:
    """溯源块哨兵行行尾之后的字节流 sha256（=引擎原件逐字节内容）。"""
    raw = (CORPUS_DIR / name).read_bytes()
    idx = raw.find(SENTINEL.encode("utf-8"))
    assert idx != -1, f"{name}: 缺溯源块哨兵行"
    nl = raw.find(b"\n", idx)
    assert nl != -1, f"{name}: 哨兵行无行尾"
    return hashlib.sha256(raw[nl + 1 :]).hexdigest()


def test_corpus_dir_holds_exactly_the_four_copies() -> None:
    py = sorted(p.name for p in CORPUS_DIR.glob("*.py"))
    assert py == sorted(ANCHORS)
    assert sorted(p.name for p in CORPUS_DIR.iterdir()) == py


@pytest.mark.parametrize("name", sorted(ANCHORS))
def test_provenance_block_fields(name: str) -> None:
    head = _header(name)
    full = (CORPUS_DIR / name).read_bytes().decode("utf-8", errors="replace")
    rel, sha = ANCHORS[name]
    assert "原路径：C:\\Software\\GPT-SoVITS-V2Pro" in head
    assert rel.replace("/", "\\") in head
    assert f"原件 sha256：{sha}" in head
    assert "收编日期：2026-09-19" in head
    assert "缺陷指针" in head and "T24" in head
    assert full.count(SENTINEL) == 1


@pytest.mark.parametrize("name", sorted(ANCHORS))
def test_copy_tail_matches_anchored_sha(name: str) -> None:
    assert _tail_sha(name) == ANCHORS[name][1]


@pytest.mark.parametrize("name", sorted(ANCHORS))
def test_engine_original_no_drift(name: str) -> None:
    rel, sha = ANCHORS[name]
    orig = ENGINE_ROOT / rel
    if not orig.is_file():
        pytest.skip(f"引擎原件缺失（引擎目录不可达或已迁移）：{orig}")
    orig_sha = hashlib.sha256(orig.read_bytes()).hexdigest()
    assert orig_sha == sha, "引擎原件已改动：以仓内锚定值为准，回填 ANCHORS 并重录溯源块"
    assert _tail_sha(name) == orig_sha, "收编副本尾部与引擎原件漂移"


@pytest.mark.parametrize("name", MODULE_SAFE)
def test_module_safe_copies_import_cleanly(name: str) -> None:
    assert "if __name__" in (CORPUS_DIR / name).read_text(encoding="utf-8")
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # import 不落 __pycache__（树卫生）
    try:
        spec = importlib.util.spec_from_file_location(
            f"tts_corpus_{Path(name).stem}", CORPUS_DIR / name
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    assert callable(getattr(mod, "main", None))
    if name == "scan_durations.py":
        assert callable(mod.probe) and callable(mod.prefix_of)
    else:
        assert callable(mod.build_model) and callable(mod.collect) and callable(mod.probe)


@pytest.mark.parametrize("name", TOPLEVEL)
def test_toplevel_executors_stay_unimportable(name: str) -> None:
    """顶层执行脚本分类锁：若未来加了 __main__ 护栏，应移入 MODULE_SAFE 并补行为冒烟。"""
    src = (CORPUS_DIR / name).read_text(encoding="utf-8")
    assert "if __name__" not in src
    ast.parse(src)


def test_transcribe_refs_help_subprocess() -> None:
    """argparse --help 在任何副作用（collect/build_model）之前退出，零写盘。"""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, str(CORPUS_DIR / "transcribe_refs.py"), "--help"],
        capture_output=True,
        timeout=60,
        env=env,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    out = proc.stdout.decode("utf-8", errors="replace")
    assert "离线听写" in out
    for flag in ("-i", "-o", "--language", "--no-list"):
        assert flag in out
