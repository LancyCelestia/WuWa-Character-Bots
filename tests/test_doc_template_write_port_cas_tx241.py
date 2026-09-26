"""TX241：页面写口的跨进程丢更新 / 回滚覆写 / 半档 三形回归锁（新建件，只增不改既有测试件）。

判据真身三处：`scripts/doc_template_sync.py::write_page`（第一写口）、
`scripts/batch_frontmatter_convert.py::_commit_page`（挂头口）、
`scripts/board_doc_sync.py::_commit_rendered`（板块投影口）。三形由 TX213 实锤、TX226 在快照
sha `9a4d16b62e6bd4a3` 上逐字再现，本件把「修后必抛或必弃写」钉成机器腿：

- **L1 CAS**：三处写口在**紧邻落盘之前**重读盘上态、与本轮起点凭据比对，不等 ⇒ 弃写（临时名都
  不落）、用重读到的那份盘上态重跑渲染（有界），超限抛错/点名——绝不用陈旧派生值顶掉他席提交。
  凭据尺子唯一住 `shim_retirement_census._integrity_token`（用例①现算证明全树只有一枚定义、
  且三处写口都真的经过它）。
- **L0 条件回滚**：回滚前先重读；盘上仍是本席写值才抬回写前态，已是他人提交 ⇒ 只放弃不回滚，
  异常文案随之改口（旧三条腿一律 `write_bytes(original)`＝连别人一起吃，还谎称「盘上态原样保留」）。
- **原子写**：临时名 + `os.replace`；失败路径目标逐字节不动、不残留临时名（可见性原子）。
- **不静默**：落盘前被否决的页必须点名并非零退出（板块口 `BoardPageConflict`＋`write_tree` 收账；
  挂头口 `stale_refused`＋rc=1）。

真双进程那一发（用例⑤）用**信号文件**编排：子进程 A 停在渲染段内（旁路的只有渲染函数
`_apply_block`，采集/等值门/CAS/原子写/差分全走真实码——TX213 同款口径），主进程 B 在同一页上
真实提交后放行 A。**每发正向锁都配一发注毒反证**（把守卫旁路掉看这一发是否复活），因为
"绿但无牙"是本波反复抓过的型（TX179/TX242/TX251）。

复跑：
    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_doc_template_write_port_cas_tx241.py -p no:cacheprovider \\
      --basetemp=<私有> -q
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_SPEC = importlib.util.spec_from_file_location(
    "doc_template_sync", SCRIPTS / "doc_template_sync.py"
)
assert _SPEC and _SPEC.loader
dts = importlib.util.module_from_spec(_SPEC)
sys.modules["doc_template_sync"] = dts  # dataclasses 解注解需要模块在 sys.modules 内
_SPEC.loader.exec_module(dts)  # type: ignore[attr-defined]

import batch_frontmatter_convert as bfc  # 同目录兄弟件（其 dts 即上面那份模块对象）
import board_doc_sync as bds
import shim_retirement_census as src  # 完整性凭据唯一真身

B = dts.TPL_AUTO_BEGIN
TPL = "tx241-tpl"
_SCHEMA_TEXT = (
    "<!-- @schema:BEGIN\nsections: 交付 | 自报\nparams:\n"
    "- note | text | literal | req | nonempty\n"
    "@schema:END -->\n<!-- TEMPLATE-AUTO:BEGIN -->\n"
    "- {{fact:note}}\n<!-- TEMPLATE-AUTO:END -->\n"
)
SCHEMAS = {TPL: dts.parse_schema_text(_SCHEMA_TEXT, TPL)}
FM = "---\ntemplate: tx241-tpl\nparams:\n  note: N-241\n---\n"
BODY = "\n# 夹具\n\n## 交付\n\n- 事件一\n\n## 自报\n\n- 收尾\n"
NEEDLE = "- N-241"
INTERLOPER = "- 他席合法提交：这一行绝不该被陈旧派生值吃掉\n"
PAGE_PLAIN = FM + BODY


def _page(tmp_path: Path, name: str, mem_text: str) -> tuple[dts.PageInfo, Path]:  # type: ignore[name-defined]
    """落盘 `mem_text` 并造一个「内存态==盘上态」的采集快照（正常采集形状）。"""
    f = tmp_path / name
    f.write_text(mem_text, encoding="utf-8", newline="\n")
    pg = dts.PageInfo(rel=f".superpowers/sdd/2026-09-22-taxonomy/{name}",
                      path=f, text=mem_text, category="seat-report")
    pg.fm = dts.parse_front_matter(mem_text)
    assert pg.fm is not None
    return pg, f


def _neuter_cas(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒：把完整性凭据旁路成常量 ⇒ 三处写口的 CAS 一齐失明（只用于反证守卫的杀伤力）。"""
    monkeypatch.setattr(dts, "_integrity_token_of", lambda raw: (0, "0" * 16))


def _interloper_in_render(monkeypatch: pytest.MonkeyPatch, f: Path) -> None:
    """在**渲染段内**插一发他席真实提交（旁路 `_apply_block`，守卫本体照常执行）。"""
    real_apply = dts._apply_block
    state = {"n": 0}

    def apply_with_interloper(text: str, block: str) -> str:
        state["n"] += 1
        if state["n"] == 1:
            with f.open("ab") as fh:  # 真写盘，不伪造字节
                fh.write(INTERLOPER.encode("utf-8"))
        return real_apply(text, block)

    monkeypatch.setattr(dts, "_apply_block", apply_with_interloper)


# --------------------------------------------------------------------------
# ① 一把尺：凭据真身唯一 + 三处写口都从它取数；写口零非原子直写
# --------------------------------------------------------------------------
def test_integrity_token_has_one_home_and_all_ports_route_through_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全树 `scripts/*.py` 里 `_integrity_token` **只有一枚定义**，且各写口都真的经过它。

    不是 grep 串比：把真身换成哨函数再走一遍写口，看哨有没有被敲——任一写口私造第二把尺
    就敲不到（TX226 §4.2「禁另造第二把尺」的机器腿）。
    """
    defs = []
    for path in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defs += [path.name for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == "_integrity_token"]
    assert defs == ["shim_retirement_census.py"], f"完整性凭据出现第二真身：{defs}"

    hits: list[int] = []
    real = src._integrity_token

    def spy(raw: bytes) -> tuple[int, str]:
        hits.append(len(raw))
        return real(raw)

    monkeypatch.setattr(src, "_integrity_token", spy)
    pg, _f = _page(tmp_path, "SEAT-TX241R1.md", PAGE_PLAIN)
    assert dts.write_page(pg, SCHEMAS) is True
    bds._write_page(tmp_path / "board-r1.md", "T", "AUTO", "正文")
    assert len(hits) >= 2, f"写口未经在册凭据（敲哨 {len(hits)} 次）＝私造了第二把尺"


def test_three_write_ports_hold_no_non_atomic_direct_writer() -> None:
    """三处写口 AST 里 `write_text(` / `write_bytes(` 命中数 **== 0**（只准原子口落盘）。

    旧形 `write_bytes(written)` / `write_text(...)` 都是 truncate+write ⇒ 读者可见半档
    （TX226 §3 第三条附带事实）。本锁防"以后有人图省事把直写加回来"。
    """
    for name in ("doc_template_sync.py", "batch_frontmatter_convert.py", "board_doc_sync.py"):
        tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"), filename=name)
        bad = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"write_text", "write_bytes"}
        ]
        assert bad == [], f"{name} 仍有非原子直写，行号 {bad}"


# --------------------------------------------------------------------------
# ② L1 CAS（第一写口）：写盘中途他席提交 ⇒ 弃写/必抛，他席字节原样在盘
# --------------------------------------------------------------------------
def test_cas_refuses_stale_derived_write_and_keeps_midflight_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 在渲染段里时 B 真实提交 ⇒ A 的写前 CAS 必拦下（旧形在此双双成功、A 静默吃掉 B）。"""
    pg, f = _page(tmp_path, "SEAT-TX241A.md", PAGE_PLAIN)
    _interloper_in_render(monkeypatch, f)
    with pytest.raises(dts.PageConcurrentMutation) as caught:
        dts.write_page(pg, SCHEMAS)
    body = f.read_text(encoding="utf-8")
    assert INTERLOPER.strip() in body, "他席提交被吃掉＝CAS 没咬住"
    assert NEEDLE not in body, "弃写页却落了机器段"
    msg = str(caught.value)
    assert "并发竞写" in msg or "采集后" in msg, msg


def test_cas_leg_has_teeth_neutered_token_reproduces_lost_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """杀伤力反证：旁路凭据 ⇒ TX213 case1 当场复活（A 返回 True、B 蒸发）。

    删掉守卫而套件照绿＝假锁（TX179 抓过这型）。本用例专门钉「守卫可摘即红」。
    """
    pg, f = _page(tmp_path, "SEAT-TX241B.md", PAGE_PLAIN)
    _interloper_in_render(monkeypatch, f)
    _neuter_cas(monkeypatch)
    assert dts.write_page(pg, SCHEMAS) is True, "CAS 失明后仍拒写＝本席测的不是 CAS"
    body = f.read_text(encoding="utf-8")
    assert NEEDLE in body and INTERLOPER.strip() not in body, "丢更新形态没复现＝夹具或尺子变了"


# --------------------------------------------------------------------------
# ③ L0 回滚腿：他席已提交 ⇒ 只放弃不回滚；无人提交 ⇒ 照旧回滚
# --------------------------------------------------------------------------
def test_rollback_leg_abandons_instead_of_erasing_other_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """读回不等且盘上已是他人提交 ⇒ **不回滚**（旧腿在此把别人整页抬回去、还谎称原样保留）。"""
    pg, f = _page(tmp_path, "SEAT-TX241C.md", PAGE_PLAIN)
    real_rb = Path.read_bytes
    state = {"n": 0}

    def fake_rb(self: Path) -> bytes:
        if self == f:
            state["n"] += 1
            if state["n"] == 3:  # 恰在"本席刚落盘、正待读回"这一发上，B 真实提交
                with f.open("ab") as fh:
                    fh.write(INTERLOPER.encode("utf-8"))
        return real_rb(self)

    monkeypatch.setattr(Path, "read_bytes", fake_rb)
    with pytest.raises(dts.PageConcurrentMutation) as caught:
        dts.write_page(pg, SCHEMAS)
    monkeypatch.undo()
    body = f.read_text(encoding="utf-8")
    assert INTERLOPER.strip() in body, "回滚腿把他席提交抬回去了（L0 未生效）"
    assert state["n"] >= 4, "回滚腿没重读盘上态＝条件回滚没执行"
    msg = str(caught.value)
    assert "未回滚" in msg and "他席" in msg, msg
    assert "盘上态原样保留" not in msg, "文案仍在谎称原样保留"


def test_rollback_leg_still_rolls_back_when_disk_still_holds_our_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """对照组：只是"读回那一发被污染"、盘上仍是本席写值 ⇒ 条件回滚照旧执行到写前态。"""
    pg, f = _page(tmp_path, "SEAT-TX241D.md", PAGE_PLAIN)
    original = f.read_bytes()
    real_rb = Path.read_bytes
    state = {"n": 0}

    def fake_rb(self: Path) -> bytes:
        data = real_rb(self)
        if self == f:
            state["n"] += 1
            if state["n"] == 3:  # 只对读回那一发撒谎，回腿的重读走真实字节
                return data.replace("收尾".encode(), "尾收".encode())
        return data

    monkeypatch.setattr(Path, "read_bytes", fake_rb)
    with pytest.raises(dts.PageConcurrentMutation) as caught:
        dts.write_page(pg, SCHEMAS)
    monkeypatch.undo()
    assert f.read_bytes() == original, "无人提交时回滚腿被削弱了（不该顺手放宽）"
    assert "已回滚" in str(caught.value), "回滚发生却没点名＝文案失真"


# --------------------------------------------------------------------------
# ④ 原子写：失败不留半档、不残留临时名；读者永不见半档
# --------------------------------------------------------------------------
def test_atomic_write_failure_leaves_target_intact_and_no_temp_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`os.replace` 失败 ⇒ 目标逐字节不变、目录里不残留 `*.tmp`（临时名必被回收）。"""
    target = tmp_path / "SEAT-TX241E.md"
    target.write_text("旧版全文", encoding="utf-8", newline="\n")
    before = target.read_bytes()

    def boom(_src: str, _dst: str) -> None:
        raise OSError("simulated replace failure (file busy)")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        dts._atomic_write_bytes(target, b"NEW-FULL-TEXT")
    assert target.read_bytes() == before, "写失败却动了目标"
    assert list(tmp_path.glob("*.tmp")) == [], "临时名未回收"


def test_reader_never_observes_a_half_page_during_atomic_replace(tmp_path: Path) -> None:
    """读者只会看到「旧完整版」或「新完整版」——半档形态物理上不可观测（可见性原子）。

    旧形是 `write_bytes`（truncate 之后再写）⇒ 并发读者可读到 0 字节或前缀；本用例读的是
    现实形态的短读者（读完就撒手、间隔 0.2ms），不是占空比 100% 的热循环（那发另立用例）。
    """
    old = b"OLD" + b"." * 200_000
    new = b"NEW" + b"x" * 200_000
    target = tmp_path / "SEAT-TX241F.md"
    target.write_bytes(old)
    seen: list[bytes] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                seen.append(target.read_bytes())
            except FileNotFoundError:
                seen.append(b"MISSING")
            except PermissionError:
                pass  # Windows 实测残余①：顶替进行中的一发 open 可瞬态 EACCES（内容仍完整）
            time.sleep(0.0002)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        dts._atomic_write_bytes(target, new)
    finally:
        stop.set()
        t.join(timeout=5)
    assert len(seen) >= 5, f"读者样本太少（{len(seen)} 发）＝夹具没跑起来"
    bad = sorted({s[:8].decode("latin-1") for s in seen if s not in (old, new)})
    assert not bad, f"读到半档/瞬态 {bad[:3]}（共 {len(seen)} 发）"
    assert target.read_bytes() == new, "终态不是新版"


def test_replace_starvation_is_bounded_then_leaves_target_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """登记 Windows 残余②（本席热循环夹具实测撞出来的 livelock，不藏）：目标被读者长期占用时，
    `os.replace` 可一直 `PermissionError` ⇒ 本口**有界重试后抛错**、临时名回收、目标逐字节不变。

    判据用可数的桩（每次都拒）而不是真线程——真线程那一发是时序、会把套件变成 flaky；
    这里要钉的是"预算有限 + 失败必干净"这三件事本身。
    """
    old = b"OLD-PAGE"
    target = tmp_path / "SEAT-TX241G.md"
    target.write_bytes(old)
    calls = {"n": 0}

    def always_denied(_src: str, _dst: str) -> None:
        calls["n"] += 1
        raise PermissionError("simulated busy target (hot reader starves the replace)")

    monkeypatch.setattr(os, "replace", always_denied)
    monkeypatch.setattr(dts.time, "sleep", lambda _s: None)  # 不真等 200ms，只数次数
    with pytest.raises(PermissionError):
        dts._atomic_write_bytes(target, b"NEW-PAGE")
    assert calls["n"] == dts._REPLACE_RETRIES, f"重试预算未被遵守：{calls['n']}"
    assert target.read_bytes() == old, "写失败却动了目标"
    assert list(tmp_path.glob("*.tmp")) == [], "临时名未回收"


# --------------------------------------------------------------------------
# ⑤ 真双进程（信号文件编排）：修后必抛或必弃写
# --------------------------------------------------------------------------
_CHILD_SRC = '''
"""TX241 子进程 A：同一份采集快照驱动同一页，停在渲染段里等主进程放行。"""
import json, os, sys, time
import importlib.util
from pathlib import Path

SCRIPTS = Path("__SCRIPTS__")
BOX = Path("__BOX__")
TPL = "tx241-tpl"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("doc_template_sync", SCRIPTS / "doc_template_sync.py")
dts = importlib.util.module_from_spec(spec)
sys.modules["doc_template_sync"] = dts
spec.loader.exec_module(dts)

schemas = {TPL: dts.parse_schema_text(
    "<!-- @schema:BEGIN\\nsections: 交付 | 自报\\nparams:\\n"
    "- note | text | literal | req | nonempty\\n"
    "@schema:END -->\\n<!-- TEMPLATE-AUTO:BEGIN -->\\n"
    "- {{fact:note}}\\n<!-- TEMPLATE-AUTO:END -->\\n", TPL)}
page = "__FM__" + "\\n# 夹具\\n\\n## 交付\\n\\n- 事件一\\n\\n## 自报\\n\\n- 收尾\\n"
f = BOX / "SEAT-TX241DUAL.md"
pg = dts.PageInfo(rel=".superpowers/sdd/2026-09-22-taxonomy/SEAT-TX241DUAL.md",
                  path=f, text=page, category="seat-report")
pg.fm = dts.parse_front_matter(page)

real_apply = dts._apply_block


def apply_then_wait(text, block):
    (BOX / "A_in_render").write_text("1", encoding="utf-8")
    deadline = time.time() + 60
    while not (BOX / "A_go").exists():
        if time.time() > deadline:
            raise RuntimeError("等待放行超时")
        time.sleep(0.02)
    return real_apply(text, block)


dts._apply_block = apply_then_wait
if os.environ.get("TX241_NEUTER") == "1":
    dts._integrity_token_of = lambda raw: (0, "0" * 16)

out = {"outcome": "", "needle": False, "interloper": False}
try:
    out["outcome"] = "RETURN:" + repr(dts.write_page(pg, schemas))
except Exception as exc:  # 跨进程只回传类型名，不带对象
    out["outcome"] = type(exc).__name__
text = f.read_text(encoding="utf-8")
out["needle"] = "- N-241" in text
out["interloper"] = "他席合法提交" in text
(BOX / "A_result.json").write_text(json.dumps(out), encoding="utf-8")
print(json.dumps(out))
'''


def _run_dual_process(tmp_path: Path, *, neuter: bool) -> dict:
    """起子进程 A（真·另一枚 OS 进程）＋主进程 B 同写一页；返回 A 结局与盘上终态。"""
    box = tmp_path / "dual"
    box.mkdir()
    (box / "SEAT-TX241DUAL.md").write_text(PAGE_PLAIN, encoding="utf-8", newline="\n")
    child = tmp_path / "_tx241_child.py"
    child.write_text(
        _CHILD_SRC.replace("__SCRIPTS__", str(SCRIPTS).replace("\\", "\\\\"))
        .replace("__BOX__", str(box).replace("\\", "\\\\"))
        .replace("__FM__", FM.replace("\n", "\\n")),
        encoding="utf-8", newline="\n")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", BOT_AUTOSYNC="0",
               PYTHONIOENCODING="utf-8", PYTHONPYCACHEPREFIX=str(tmp_path / "cc-child"))
    env["TX241_NEUTER"] = "1" if neuter else "0"
    proc = subprocess.Popen([sys.executable, "-u", str(child)], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    page_file = box / "SEAT-TX241DUAL.md"
    deadline = time.time() + 60
    while not (box / "A_in_render").exists():  # 等 A 走进渲染段（此刻它已完成预读与等值门）
        if proc.poll() is not None or time.time() > deadline:
            raise AssertionError(f"子进程 A 未进入渲染段：{_drain(proc)}")
        time.sleep(0.02)
    with page_file.open("ab") as fh:  # B＝主进程这一发是"采集之后另一枚进程的真实提交"
        fh.write(INTERLOPER.encode("utf-8"))
    (box / "A_go").write_text("1", encoding="utf-8")
    result_file = box / "A_result.json"
    deadline = time.time() + 60
    while not result_file.exists():
        if proc.poll() is not None or time.time() > deadline:
            raise AssertionError(f"子进程 A 未交卷：{_drain(proc)}")
        time.sleep(0.02)
    proc.wait(timeout=30)
    return json.loads(result_file.read_text(encoding="utf-8"))


def _drain(proc: subprocess.Popen) -> str:  # type: ignore[type-arg]
    out = proc.stdout.read() if proc.stdout else ""
    return str(out)[-1500:]


def test_dual_process_second_writer_cannot_eat_the_first(tmp_path: Path) -> None:
    """真双进程：A 停在渲染段、B 真实提交后放行 ⇒ A 必抛，B 的字节原样在盘、机器段不落。"""
    verdict = _run_dual_process(tmp_path, neuter=False)
    assert verdict["outcome"].startswith("PageConcurrentMutation"), verdict
    assert verdict["interloper"], f"他席提交被吃掉：{verdict}"
    assert not verdict["needle"], f"弃写页却落了机器段：{verdict}"


def test_dual_process_poison_neutered_cas_reproduces_lost_update(tmp_path: Path) -> None:
    """同序、只旁路 CAS ⇒ 旧形当场复活（A 返回 True、B 蒸发）＝上面那发锁真有牙。"""
    verdict = _run_dual_process(tmp_path, neuter=True)
    assert verdict["outcome"].startswith("RETURN:True"), verdict
    assert not verdict["interloper"], f"注毒没杀动：他席提交居然活下来了 {verdict}"


# --------------------------------------------------------------------------
# ⑥ 第二写口：挂头口（batch_frontmatter_convert）
# --------------------------------------------------------------------------
CONVERT_REL = ".superpowers/sdd/2026-09-22-taxonomy/SEAT-TX241FIX.md"
CONVERT_BODY = "Status: DONE\n\n# 夹具\n\n## 交付\n\n- 一件事\n"
CONVERT_HEAD = ("---\ntemplate: seat-report\nparams:\n  seat_id: TX241FIX\n"
                "  wave: 2026-09-22-taxonomy\n  status: DONE\n  role: impl\n"
                "  report_class: auto:seat_class\n  ledger_events: auto:page_stat:ledger\n---\n")


def _convert_page(tmp_path: Path) -> tuple[Path, Path]:
    box = tmp_path / "box"
    page = box / CONVERT_REL
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(CONVERT_BODY, encoding="utf-8", newline="\n")
    return box, page


def _convert_argv(box: Path) -> list[str]:
    return ["--execute", "--confirm-execute", "--root", str(box),
            "--only", ".superpowers/**", "--set", "role=impl"]


def _interloper_in_zone(monkeypatch: pytest.MonkeyPatch, on_second: Callable[[], None]) -> None:
    """在挂头口**渲染段**的第 2 发（＝`_commit_page` 里那一发）之前注入他席真实提交动作。"""
    real_zone = bfc._apply_machine_zone
    state = {"n": 0}

    def zone_with_side_effect(text: str, block: str) -> str:
        state["n"] += 1
        if state["n"] == 2:
            on_second()
        return real_zone(text, block)

    monkeypatch.setattr(bfc, "_apply_machine_zone", zone_with_side_effect)


def test_convert_commit_keeps_interloper_body_and_still_hangs_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """挂头口：整批采集之后他席追加正文 ⇒ 写前 CAS 弃写重跑，他席那行活、头也挂上。"""
    box, page = _convert_page(tmp_path)

    def append() -> None:
        with page.open("ab") as fh:
            fh.write(INTERLOPER.encode("utf-8"))

    _interloper_in_zone(monkeypatch, append)
    rc = bfc.main(_convert_argv(box))
    out = capsys.readouterr().out
    body = page.read_text(encoding="utf-8")
    assert rc == 0, out
    assert INTERLOPER.strip() in body, f"他席正文被整页顶回：{body!r}"
    assert "template: seat-report" in body and B in body, "重跑后没把头挂上"
    assert "stale_refused=0" in out, out


def test_convert_port_has_teeth_neutered_cas_eats_interloper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """同序、旁路凭据 ⇒ TX226 §3 的 `LOST-UPDATE-REPRODUCED` 复活（written=1、他席行没了）。"""
    box, page = _convert_page(tmp_path)

    def append() -> None:
        with page.open("ab") as fh:
            fh.write(INTERLOPER.encode("utf-8"))

    _interloper_in_zone(monkeypatch, append)
    _neuter_cas(monkeypatch)
    rc = bfc.main(_convert_argv(box))
    out = capsys.readouterr().out
    body = page.read_text(encoding="utf-8")
    assert rc == 0 and "written=1" in out, out
    assert INTERLOPER.strip() not in body, "注毒没杀动：CAS 之外还有一道拦下了这一发"


def test_convert_stale_refusal_is_named_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """落盘前他席已挂好同一枚头 ⇒ 不覆盖、点名 `stale_refused` 并非零退出（绝不静默跳过）。"""
    box, page = _convert_page(tmp_path)

    def someone_else() -> None:
        page.write_text(CONVERT_HEAD + CONVERT_BODY, encoding="utf-8", newline="\n")

    _interloper_in_zone(monkeypatch, someone_else)
    rc = bfc.main(_convert_argv(box))
    got = capsys.readouterr()
    assert rc == 1, got.out + got.err
    assert "STALE-REFUSED" in got.err and "stale_refused=1" in got.out, got.out + got.err
    assert "already_has_header" in got.err, got.err


def test_convert_idempotent_second_run_writes_nothing(tmp_path: Path,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    """幂等自证（R3 边界②）：同一名册再跑一次变更数为 0，且不留非原子残留。"""
    box, page = _convert_page(tmp_path)
    assert bfc.main(_convert_argv(box)) == 0
    first = page.read_bytes()
    capsys.readouterr()
    assert bfc.main(_convert_argv(box)) == 0
    assert page.read_bytes() == first, "第二次执行改了字节＝幂等被破坏"
    assert list(page.parent.glob("*.tmp")) == [], "临时名残留"


# --------------------------------------------------------------------------
# ⑦ 第三写口：板块投影（board_doc_sync）
# --------------------------------------------------------------------------
def _board_page(tmp_path: Path) -> Path:
    p = tmp_path / "board-l3.md"
    p.write_text(
        f"# 标题\n\n{bds.AUTO_BEGIN}\n{bds.AUTO_NOTE}\n\n旧投影\n{bds.AUTO_END}\n\n"
        "## 人写正文\n\n- 我写的，别吃\n", encoding="utf-8", newline="\n")
    return p


def _interloper_on_cas_read(monkeypatch: pytest.MonkeyPatch, p: Path) -> dict:
    """在他席**写前 CAS 那一读**（第 2 读）之前，让第三方真实改一次人工区。"""
    real_rb = Path.read_bytes
    state = {"n": 0}

    def fake_rb(self: Path) -> bytes:
        if self == p:
            state["n"] += 1
            if state["n"] == 2:
                with p.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(INTERLOPER)
        return real_rb(self)

    monkeypatch.setattr(Path, "read_bytes", fake_rb)
    return state


def test_board_merge_preserves_midflight_human_edit(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """投影口：渲染期间他席改了人工区 ⇒ 写前 CAS 弃写重跑，人工区那行活、AUTO 段换新。"""
    p = _board_page(tmp_path)
    state = _interloper_on_cas_read(monkeypatch, p)
    bds._merge(p, "标题", "新投影", "骨架")
    monkeypatch.undo()
    body = p.read_text(encoding="utf-8")
    assert "新投影" in body, "AUTO 段没更新＝重跑没发生"
    assert INTERLOPER.strip() in body, f"他席人工区被整页顶回：{body!r}"
    assert "- 我写的，别吃" in body, "人工区原文丢了"
    assert state["n"] >= 3, "写口只读了一发＝没走 CAS"


def test_board_port_has_teeth_neutered_cas_eats_human_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同序、旁路凭据 ⇒ 旧「零等值门直写」形态复活（他席人工区没了）＝证明该锁有牙。"""
    p = _board_page(tmp_path)
    _interloper_on_cas_read(monkeypatch, p)
    _neuter_cas(monkeypatch)
    bds._merge(p, "标题", "新投影", "骨架")
    monkeypatch.undo()
    assert INTERLOPER.strip() not in p.read_text(encoding="utf-8"), "注毒没杀动：另有守卫拦下了"


def test_board_conflict_is_raised_and_accounted_by_write_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """冲突必抛 `BoardPageConflict`，且 `write_tree` 逐页收账（点名表进退出码，不静默）。"""
    box = tmp_path / "boards"
    box.mkdir()
    monkeypatch.setattr(bds, "BOARDS_DIR", box)
    monkeypatch.setattr(bds, "_commit_rendered", lambda path, render: "cas-conflict（模拟耗尽）")
    conflicts = bds.write_tree([], [], {}, {"boards": 0, "features": 0, "l3": 0,
                                            "kinds": 0, "topics": 0, "topics_total": 0})
    assert len(conflicts) == 1 and "cas-conflict" in conflicts[0], conflicts
    assert "README.md" in conflicts[0], conflicts
    assert not (box / "README.md").exists(), "被否决的那一发仍然落了盘"


def test_board_write_is_byte_identical_and_idempotent(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """同输入两次投影 ⇒ 字节相等、零临时名残留（生成物幂等是常驻门的地板）。"""
    box = tmp_path / "boards"
    box.mkdir()
    monkeypatch.setattr(bds, "BOARDS_DIR", box)
    facts = {"boards": 0, "features": 0, "l3": 0, "kinds": 0, "topics": 0, "topics_total": 0}
    assert bds.write_tree([], [], {}, facts) == []
    first = (box / "README.md").read_bytes()
    assert bds.write_tree([], [], {}, facts) == [], "第二次投影报了冲突"
    assert (box / "README.md").read_bytes() == first, "第二次投影改了字节＝幂等被破坏"
    assert list(box.glob("*.tmp")) == [], "临时名残留"


# --------------------------------------------------------------------------
# ⑧ 反第二真身：两枚后补写口必须复用中央三件套（AST 现算）
# --------------------------------------------------------------------------
def test_later_ports_reuse_the_central_write_primitives() -> None:
    """`batch_frontmatter_convert` 与 `board_doc_sync` 都调中央三件套，零自造尺。"""
    for name in ("batch_frontmatter_convert.py", "board_doc_sync.py"):
        tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"), filename=name)
        called = {
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "dts"
        }
        missing = {"_integrity_token_of", "_atomic_write_bytes", "_rollback_or_abandon"} - called
        assert not missing, f"{name} 未复用中央写口三件套，缺 {sorted(missing)}"
