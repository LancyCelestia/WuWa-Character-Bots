"""TX191 续跑席的注毒自证 —— 引用索引「撕裂读完整性判据」的四发反向锁。

任务书：`BRIEFS-BATCH57.md`《TX191》。共享前言＝批 50《共享前言》逐字 +
`ADDENDUM-USER-RULINGS-20260923.md`（R0–R8/三边界/两纪律）。独占写面＝
`scripts/shim_retirement_census.py`（算口）+ 本件（新建测试）；**不碰任何既有测试断言**。

被锁的根因（TX183 未落码、TX179/TX182 复现并加重）：
- 撕裂读（并发写者把某 `.py` 截成一个仍能 `ast.parse` 的前缀）零异常 ⇒ **半截索引进 `lru_cache`**；
  文件修好后同进程复调仍半索引（键 1 vs 5）；
- 更狠的是 `render_ledger` 的 `ceiling = min(既有, 现算)` ⇒ 一次撕裂读把某枚 refs 上限钉成 0
  并**写进退役台账**，以「合法棘轮只降不升」形态持久化，清缓存也撤不回。

修法（本件逐发验证，全在内存/tmp 树注毒，绝不写源码树）：
① 双读比对 `(len, sha256[:16])`，不一致 ⇒ `ReferenceIndexUnstable` 且**不入缓存**（lru 异常不入缓存）；
② 台账写入侧 `_require_complete_reference_index()` 取「完整读凭据」，拿不到就在算 `ceiling` 前抛 ⇒ 拒写、留旧值；
③ `reference_index()` 返回**新构造 dict 浅拷贝**（值是不可变 frozenset）⇒ 改返回值改不动缓存。

四发对应任务书：首读截断必抛／不写入台账／修好后二次调用拿全键／返回值改不动缓存。
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import shim_retirement_census as s34


# --------------------------------------------------------------------------
# 公共夹具：搭一棵极小的 tmp 引用树，避免遍历真树 1205 枚文件（快、可控）。
# 三枚文件各贡献一个不同的顶层引用根，"全键"= {os, os.path, json} 可核对。
# --------------------------------------------------------------------------
def _tiny_tree(tmp_path: Path) -> Path:
    pkg = tmp_path / "plugins" / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "mod_a.py").write_text("import os\n", encoding="utf-8")
    (pkg / "target.py").write_text("from os import path\n", encoding="utf-8")
    (pkg / "mod_b.py").write_text("import json\n", encoding="utf-8")
    return tmp_path


def _tear_reader(tear_name: str) -> tuple[Callable[[Path], bytes], dict[str, bool]]:
    """造一个「对目标文件名首轮返回空字节(撕裂)、次轮返回真字节」的读缝替身。

    真实撕裂＝另一进程在两次读之间改了文件；这里用「同一路径两次 `read_bytes()` 结果不同」确定性地
    复现它 —— 被测的**比对逻辑本身**（`_read_source_with_integrity` 的 size+sha256 核对）走真实码路，
    注毒只是把喂进去的字节做成不一致。`switch["on"]` 关掉后一律返回真字节（模拟文件稳定后）。
    """
    calls: dict[str, int] = {}
    switch = {"on": True}

    def fake_read(path: Path) -> bytes:
        real = path.read_bytes()
        key = path.name
        calls[key] = calls.get(key, 0) + 1
        if switch["on"] and key == tear_name and calls[key] == 1:
            return b""  # 首轮截断成空（仍能 parse ⇒ 旧版就是在这里静默半索引）
        return real  # 次轮与其余文件：真字节

    return fake_read, switch


# ==========================================================================
# ① 首读截断必抛 —— 撕裂读 ⇒ ReferenceIndexUnstable 且点名文件
# ==========================================================================
def test_tx191_1_truncated_first_read_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = _tiny_tree(tmp_path)
    fake, _switch = _tear_reader("target.py")
    monkeypatch.setattr(s34, "REPO_ROOT", tree)
    monkeypatch.setattr(s34, "_read_file_bytes", fake)
    s34._build_reference_index.cache_clear()
    try:
        with pytest.raises(s34.ReferenceIndexUnstable) as excinfo:
            s34.reference_index()
        assert "target.py" in str(excinfo.value), f"未点名撕裂文件＝fail-closed 不完整: {excinfo.value}"
        assert "撕裂读" in str(excinfo.value), f"文案未点明撕裂形态: {excinfo.value}"
    finally:
        s34._build_reference_index.cache_clear()


# 反向自证：撕裂判据不能是「无条件红」——两读一致（文件稳定）时必须正常建索引、不抛。
def test_tx191_1b_stable_read_builds_normally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = _tiny_tree(tmp_path)
    monkeypatch.setattr(s34, "REPO_ROOT", tree)
    # 不注毒：用真实 _read_file_bytes（两次读同一稳定文件必然一致）⇒ 不抛、返回全键。
    s34._build_reference_index.cache_clear()
    try:
        index = s34.reference_index()
        assert {"os", "os.path", "json"} <= set(index), f"稳定读建出的索引缺键: keys={sorted(index)}"
    finally:
        s34._build_reference_index.cache_clear()


# ==========================================================================
# ② 不写入台账 —— 撕裂读时 render_ledger 在算 ceiling 前抛；main 拒写、不落盘
# ==========================================================================
def test_tx191_2a_render_ledger_refuses_on_unstable_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _tiny_tree(tmp_path)
    fake, _switch = _tear_reader("target.py")
    monkeypatch.setattr(s34, "REPO_ROOT", tree)
    monkeypatch.setattr(s34, "_read_file_bytes", fake)
    s34._build_reference_index.cache_clear()
    states = {
        "outside": 3,
        "retire_shims": [],
        "relocate": [],
        "classified": ["plugins/pkg/mod_a.py"],
        "counts": {"retire_shims": 0, "relocate": 0, "classified": 1},
    }
    try:
        # _require_complete_reference_index 是 render_ledger 第一句 ⇒ 撕裂读先抛，
        # 绝不产出一份把某枚上限钉成 0 的账体（哪怕这里 states 根本没有垫片也不该返回文本）。
        with pytest.raises(s34.ReferenceIndexUnstable):
            s34.render_ledger(states)
    finally:
        s34._build_reference_index.cache_clear()


def test_tx191_2b_write_ledger_main_does_not_touch_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _tiny_tree(tmp_path)
    ledger = tree / "board_shim_ledger.py"  # 故意指向不存在的路径：一旦被写＝防线失效
    fake, _switch = _tear_reader("target.py")
    monkeypatch.setattr(s34, "REPO_ROOT", tree)
    monkeypatch.setattr(s34, "LEDGER_PY", ledger)
    monkeypatch.setattr(s34, "_read_file_bytes", fake)
    # three_states 依赖 ppc 真实取数口，与 tmp REPO_ROOT 解耦困难 ⇒ 直接喂一份合成 states，
    # 让控制流走到「render_ledger 内部 _require_complete_reference_index 抛」这一防线（本发要测的就是它）。
    monkeypatch.setattr(
        s34, "three_states",
        lambda: {
            "outside": 3,
            "retire_shims": [],
            "relocate": [],
            "classified": ["plugins/pkg/mod_a.py"],
            "counts": {"retire_shims": 0, "relocate": 0, "classified": 3},
        },
    )
    monkeypatch.setattr(sys, "argv", ["shim_retirement_census.py", "--write-ledger"])
    s34._build_reference_index.cache_clear()
    try:
        rc = s34.main()
        assert rc == 1, f"撕裂读下 --write-ledger 返回 {rc}（应 1＝拒写）"
        assert not ledger.exists(), "撕裂读竟把台账写了出来＝min() 防线被绕过（钉 0 会持久化）"
    finally:
        s34._build_reference_index.cache_clear()


# ==========================================================================
# ③ 修好后二次调用拿全键 —— 撕裂读不入缓存 ⇒ 同进程、不清缓存即恢复
# ==========================================================================
def test_tx191_3_recovers_full_keys_after_stabilizing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _tiny_tree(tmp_path)
    fake, switch = _tear_reader("target.py")
    monkeypatch.setattr(s34, "REPO_ROOT", tree)
    monkeypatch.setattr(s34, "_read_file_bytes", fake)
    s34._build_reference_index.cache_clear()
    try:
        # 第一跳：撕裂 ⇒ 抛，且断言什么都没进缓存（半截索引没被钉死）。
        with pytest.raises(s34.ReferenceIndexUnstable):
            s34.reference_index()
        assert s34._build_reference_index.cache_info().currsize == 0, (
            f"撕裂读后缓存里却有 {s34._build_reference_index.cache_info().currsize} 项＝半截索引被缓存钉死"
        )
        # 文件「修好」（关掉撕裂开关）——**不清缓存**，第二跳必须靠「异常不入缓存」自身恢复。
        switch["on"] = False
        index = s34.reference_index()
        assert {"os", "os.path", "json"} <= set(index), f"修好后仍半索引（键没拿全）: keys={sorted(index)}"
        assert "plugins/pkg/target.py" in index["os.path"], "target 的点号引用没被重新数到＝旧半索引残留"
    finally:
        s34._build_reference_index.cache_clear()


# ==========================================================================
# ④ 返回值改不动缓存 —— reference_index 给的是新拷贝，不是被缓存钉住的那一份
# ==========================================================================
def test_tx191_4_returned_index_is_a_projection() -> None:
    s34._build_reference_index.cache_clear()  # 现算真树，隔离先跑用例的缓存
    try:
        first = s34.reference_index()
        assert first, "真树索引为空＝取数口或本发前提坏了"
        a_key = next(iter(first))
        # 往返回值里加一枚哨兵键、并删掉一枚真键：这是对**调用方手里对象**的破坏。
        first["__tx191_canary__"] = frozenset()
        first.pop(a_key)
        # 再取一次：缓存本体不该被上面的破坏污染（旧版返回同一对象 ⇒ canary 会串进来、a_key 会消失）。
        second = s34.reference_index()
        assert "__tx191_canary__" not in second, "改返回值渗进了缓存＝reference_index 返回的是同一对象"
        assert a_key in second, f"从返回值删一枚键把缓存也削薄了＝无只读投影: 缺 {a_key}"
        assert first is not second, "两次调用返回同一对象＝浅拷贝没生效"
    finally:
        s34._build_reference_index.cache_clear()  # 交还干净缓存给同文件/同进程后续真树用例
