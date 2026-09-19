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

# T148 修复分叉登记（2026-09-20）：transcribe_refs.py 已修 T24 P1-4 反向毒化缺陷
# （竖线/分号拒绝 + 【听写失败】拦截 + traceback 残迹过滤 + 守恒断言 + 有拦截退出码 1），
# 尾部自引擎原件分叉。引擎原件不动（仍带缺陷，sha 锚维持 ANCHORS 原值）；
# 分叉后尾部新锚=FORKED 值（防仓内手改漂移照拦）。分叉依据登记在副本溯源块与 report-T148.md。
FORKED: dict[str, str] = {
    "transcribe_refs.py": "9dbc150b24220bb84f20724222f02a19ac7f87a528959c6a392f928ccc116de8",
}


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
    # T148 分叉件锚定「分叉后新锚」，未分叉件维持原件 sha 锚
    assert _tail_sha(name) == FORKED.get(name, ANCHORS[name][1])


@pytest.mark.parametrize("name", sorted(ANCHORS))
def test_engine_original_no_drift(name: str) -> None:
    rel, sha = ANCHORS[name]
    orig = ENGINE_ROOT / rel
    if not orig.is_file():
        pytest.skip(f"引擎原件缺失（引擎目录不可达或已迁移）：{orig}")
    orig_sha = hashlib.sha256(orig.read_bytes()).hexdigest()
    assert orig_sha == sha, "引擎原件已改动：以仓内锚定值为准，回填 ANCHORS 并重录溯源块"
    if name in FORKED:
        # T148 已修复分叉：原件保持不动（仍带缺陷），副本尾部=分叉新锚（双向各自防漂移）
        assert _tail_sha(name) == FORKED[name], "分叉副本尾部与 FORKED 锚漂移"
    else:
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


# ---------------------------------------------------------------------------
# T148 防毒化行为锁（repo 副本修复分叉；离线合成行，零模型/零音频/零写盘）
# ---------------------------------------------------------------------------

def _load_transcribe_module():
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # import 不落 __pycache__（树卫生）
    try:
        spec = importlib.util.spec_from_file_location(
            "tts_corpus_transcribe_t148", CORPUS_DIR / "transcribe_refs.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


def test_t148_transcribe_fork_registered_in_provenance() -> None:
    """分叉登记锁：溯源块必须带 T148 已修复分叉说明与日期，防分叉件被当成原件。"""
    head = _header("transcribe_refs.py")
    assert "T148" in head
    assert "已修复" in head and "分叉" in head
    assert "2026-09-20" in head
    assert "reject_reason" in head or "拒绝" in head  # 竖线选拒绝的登记


def test_t148_reject_reason_covers_poison_shapes() -> None:
    mod = _load_transcribe_module()
    assert mod.reject_reason("前半句|后半句") is not None  # T24 ③ 同款竖线毒形
    assert mod.reject_reason("文本;含分号") is not None  # 原件注释警告面
    assert mod.reject_reason("今天的潮汐很安静") is None  # 干净文本放行
    # traceback 残迹（压平形态，无【听写失败】前缀也要拦）
    assert (
        mod.reject_reason("Traceback (most recent call last): File \"m.py\" RuntimeError: boom")
        is not None
    )


def test_t148_failed_text_never_passes() -> None:
    mod = _load_transcribe_module()
    flat = ("【听写失败】" + "Traceback (most recent call last): File \"m.py\", line 1 "
            "RuntimeError: boom")[:120]
    multi = "【听写失败】Traceback (most recent call last):\n  File \"m.py\", line 1\nRuntimeError: boom"
    for poisoned in (flat, multi):
        assert mod.is_failed_text(poisoned)
        assert mod.reject_reason(poisoned) is not None


def test_t148_classify_conservation_and_paste_shape() -> None:
    """守恒锁：放行+拦截==输入清单条数；粘贴块只含放行条目且字段数恒为 3。"""
    mod = _load_transcribe_module()
    rows = [
        (Path("x/ref_ok.flac"), 5.0, 16000, 1, "今天的潮汐很安静"),
        (Path("x/ref_pipe.flac"), 5.0, 16000, 1, "前半句|后半句"),
        (Path("x/ref_fail.flac"), 5.0, 16000, 1,
         "【听写失败】Traceback (most recent call last): File \"m.py\""),
    ]
    ok, excluded = mod.classify_rows(rows)
    assert len(ok) + len(excluded) == len(rows)  # 守恒：输出两桶之和==输入条数
    assert [(p.name, text) for p, text in ok] == [("ref_ok.flac", "今天的潮汐很安静")]
    assert {p.name for p, _t, _r in excluded} == {"ref_pipe.flac", "ref_fail.flac"}
    assert all(reason for _p, _t, reason in excluded)  # 拦截必带原因
    paste = [f"{p.as_posix()}|{text}|zh" for p, text in ok]
    assert all(line.count("|") == 2 for line in paste)  # 字段数恒 3（无竖线混入）


def test_t148_full_pipe_poison_shape_rejected() -> None:
    """T24 ③ 全链毒形：粘贴块行内文本携带竖线会把 lang 字段顶成碎片——必须拦。"""
    mod = _load_transcribe_module()
    poisoned_line_text = "前半句|后半句"
    reason = mod.reject_reason(poisoned_line_text)
    assert reason is not None
    assert "竖线" in reason
