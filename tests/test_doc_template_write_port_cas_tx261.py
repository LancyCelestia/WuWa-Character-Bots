"""TX261 写口补全回归（本席新建；既有测试件与断言一字未动）。

覆盖批 61《TX261》点死的形态：
- ①三腿分开定性（读回腿在真他席提交下只放弃不抬）——真双进程一发；
- ②合成凭据（页面+模板双输入）：ABA+第二输入换版必拦；注毒（旁路凭据尺）⇒ 旧丢更新形复活；
- ③行尾形必等值（CRLF 页驱动一轮不整篇翻 LF；原子写不发 \\r）；
- ④固定临时名 + 陈旧 `.tx-write.tmp` 自我回收；
- ⑥类型一致性锁（str 喂 bytes 口＝点名 TypeError，不再是 `AttributeError` 暗坑）；
- ⑦`tail_append`：CAS 尾附 + 行首格防重 + 注毒（旁路凭据）复现旧丢追加形。

**本件禁模块级 `import doc_template_sync`**（TX261 本席实咬的两件之一，如实入账）：
`test_doc_template_write_port_cas_tx241.py` 用 `importlib` 现场造一份 `doc_template_sync`
并覆写 `sys.modules` 作装载仪式；若本件先以普通 import 建出另一枚模块对象，
`load_schemas()`→`freeform_guard`→…链上的 `board_doc_sync` 会绑到**先手那份**，
tx241 板块注毒口（patch 它手里的 dts）就此旁路失效——表现为「teeth 用例被任意一枚
本件用例先跑顶红」（本席 2026-09-23 15:2xZ 用 bt-o5/o6 复现并逐格取证）。
故这里全部走 fixture 延迟取件（拿到的永远是当刻 `sys.modules` 的那份真身，不造第二对象）。
全部离线；夹具全在 tmp 合成根；模板真身在 `docs/templates/seat-report.md`（只读）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(scope="module")
def dts():
    """延迟取件：见文件头「禁模块级 import」段。"""
    import doc_template_sync as m

    return m


@pytest.fixture(scope="module")
def schemas(dts):
    s = dts.load_schemas()
    assert "seat-report" in s, "夹具前提：seat-report 模板在册"
    return s


FM = (
    "---\ntemplate: seat-report\nparams:\n  seat_id: TX261\n"
    "  wave: 2026-09-22-taxonomy\n  status: DONE\n  role: impl\n"
    "  report_class: auto:seat_class\n  ledger_events: auto:page_stat:ledger\n---\n"
)
BODY = "Status: DONE\n\n# 夹具\n\n## 交付\n\n- 事件一\n\n## 自报\n\n- 收尾\n"
PAGE = FM + "\n" + BODY
NEEDLE = "TEMPLATE-AUTO:BEGIN"


def _mkpage(dts, tmp_path: Path, name: str, raw: bytes | None = None):
    f = tmp_path / name
    f.write_bytes(raw if raw is not None else PAGE.encode("utf-8"))
    text = dts._page_text_from_bytes(f.read_bytes())
    pg = dts.PageInfo(
        rel=f".superpowers/sdd/2026-09-22-taxonomy/{name}",
        path=f, text=text, category="seat-report",
    )
    pg.fm = dts.parse_front_matter(text)
    assert pg.fm is not None
    return pg, f


# ---------------------------------------------------------------- ② 第二输入换版
def _flaky_template(dts, monkeypatch, flip_even_call: bool) -> None:
    real = dts.fresh_template_source

    def flaky(tid: str):
        flaky.n += 1  # type: ignore[attr-defined]
        src, sch, why = real(tid)
        if flip_even_call and src is not None and flaky.n % 2 == 0:
            src = src + "<!-- TX261 第二输入换版注毒 -->".encode()
        return src, sch, why

    flaky.n = 0  # type: ignore[attr-defined]
    monkeypatch.setattr(dts, "fresh_template_source", flaky)


def test_second_input_swap_is_caught_and_page_untouched(dts, schemas, tmp_path, monkeypatch) -> None:
    """页面字节一字没改（纯 ABA 放行面）、**模板换版** ⇒ 合成凭据必拦：抛、零落盘。"""
    pg, f = _mkpage(dts, tmp_path, "SEAT-TX261A.md")
    _flaky_template(dts, monkeypatch, flip_even_call=True)
    with pytest.raises(dts.PageConcurrentMutation):
        dts.write_page(pg, schemas)
    assert NEEDLE not in f.read_bytes().decode("utf-8"), "拦下了却仍落了机器段＝假拦"


def test_neutered_token_brings_back_the_stale_schema_write(dts, schemas, tmp_path, monkeypatch) -> None:
    """注毒反证：旁路凭据尺（全常量）⇒ 同一换版形当场退化成**按旧模板烤页落盘**＝锁真承重。"""
    pg, f = _mkpage(dts, tmp_path, "SEAT-TX261B.md")
    monkeypatch.setattr(dts, "_integrity_token_of", lambda raw: (0, "0" * 16))
    _flaky_template(dts, monkeypatch, flip_even_call=True)
    assert dts.write_page(pg, schemas) is True  # 毒尺下 CAS 永等值 ⇒ 写进去（旧病形）
    assert NEEDLE in f.read_bytes().decode("utf-8")


# ---------------------------------------------------------------- ③ 行尾形等值
def test_atomic_write_emits_no_crlf(dts, tmp_path) -> None:
    (tmp_path / "t.md").write_bytes(b"")
    dts._atomic_write_bytes(tmp_path / "t.md", b"a\nb\n")
    assert (tmp_path / "t.md").read_bytes() == b"a\nb\n", "原子写口翻出了 \\r＝台账 _atomic_write_text 同型病"


def test_crlf_page_write_keeps_crlf_shape(dts, schemas, tmp_path) -> None:
    """CRLF 在盘页驱动一轮：**行尾形原样**（TX252 E3-4 的整页静默翻行尾必须不在这支口复发）。"""
    crlf = PAGE.replace("\n", "\r\n").encode("utf-8")
    pg, f = _mkpage(dts, tmp_path, "SEAT-TX261C.md", raw=crlf)
    assert dts.write_page(pg, schemas) is True
    after = f.read_bytes()
    assert NEEDLE.encode("utf-8") in after, "CRLF 页没被驱动＝夹具白搭"
    assert after.count(b"\r\n") == after.count(b"\n"), "驱动把 CRLF 页整篇翻成了 LF（静默翻行尾）"


# ---------------------------------------------------------------- ④ 固定临时名+清扫
def test_stale_fixed_tmp_is_swept_and_no_residue(dts, tmp_path) -> None:
    target = tmp_path / "s.md"
    stale = tmp_path / ("s.md" + dts._TMP_SUFFIX)
    stale.write_bytes("上一轮崩溃留下的半档".encode())
    dts._atomic_write_bytes(target, b"NEW")
    assert target.read_bytes() == b"NEW"
    assert not list(tmp_path.glob("*" + dts._TMP_SUFFIX)), "固定名陈旧件没被进门口回收（TX252 E3-3 泄漏族）"


def test_replace_failure_leaves_target_and_no_residue(dts, tmp_path, monkeypatch) -> None:
    target = tmp_path / "r.md"
    target.write_bytes(b"OLD")

    def always_denied(a, b, **kw):
        raise PermissionError(5, "denied")

    monkeypatch.setattr(dts.os, "replace", always_denied)
    with pytest.raises(PermissionError):
        dts._atomic_write_bytes(target, b"NEW")
    assert target.read_bytes() == b"OLD"
    assert not list(tmp_path.glob("*" + dts._TMP_SUFFIX)), "replace 失败路径泄了临时名"


# ---------------------------------------------------------------- ⑥ 类型一致性锁
def test_bytes_ports_reject_str_by_name(dts) -> None:
    """TX253 那咬 12 枚写口测试的形：str 喂 bytes 口 ⇒ 点名 `TypeError`，不是 `AttributeError` 暗坑。"""
    with pytest.raises(TypeError, match="bytes"):
        dts._page_text_from_bytes("str 喂进来了")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="bytes"):
        dts._decode_universal_newlines("str 喂进来了")  # type: ignore[arg-type]


def test_write_ports_never_feed_memory_text_into_bytes_rulers() -> None:
    """文本锁顶住根形：**任何**写口文件里禁 `pg.text` 直喂三把字节尺（TX253 崩溃形态的根）。"""
    for rel in (
        "scripts/doc_template_sync.py",
        "scripts/batch_frontmatter_convert.py",
        "scripts/board_doc_sync.py",
    ):
        src = (ROOT / rel).read_text(encoding="utf-8")
        for ruler in (
            "_integrity_token_of(",
            "_page_text_from_bytes(",
            "_decode_universal_newlines(",
            "_render_inputs_token(",
        ):
            bad = [ln for ln in src.splitlines() if ruler in ln and "pg.text" in ln]
            assert not bad, f"{rel} 把内存 str 喂进了字节尺：{bad}"


# ---------------------------------------------------------------- ⑦ CAS 尾附口
def test_tail_append_idempotent_guard_and_shape(dts, tmp_path) -> None:
    ledger = tmp_path / "OWNERSHIP.md"
    ledger.write_bytes(b"| seat | face | t |\n| TX1 | a | x |\n")
    assert dts.tail_append(ledger, ["| TX2 | b | y |"]) == "appended"
    assert ledger.read_bytes().endswith(b"| TX2 | b | y |\n")
    before = ledger.read_bytes()
    assert dts.tail_append(ledger, ["| TX2 | 改 | 了 |"]).startswith("duplicate:"), "行首格防重失灵的形"
    assert ledger.read_bytes() == before, "防重拒写却动了字节"


def test_tail_append_neutered_token_reproduces_lost_append(dts, tmp_path, monkeypatch) -> None:
    """注毒反证⑦：旁路凭据尺 ⇒ 尾附退化成「读#1 陈旧整册盲写」旧形、他席刚落盘的整册行被抬掉
    ＝旧丢追加形当场复现 ⇒ 正锁（下一条）真有牙（TX242 §8.4：尾附口自身就是本族病）。"""
    ledger = tmp_path / "OWNERSHIP.md"
    ledger.write_bytes(b"| seat | face | t |\n")
    real_rb = Path.read_bytes
    state = {"n": 0}

    def racing_rb(self: Path) -> bytes:
        data = real_rb(self)
        state["n"] += 1
        if state["n"] == 2:  # 尾附 CAS 重读位：他席刚整册落盘——诚实尺会发现，毒尺装看不见
            fresh = data + "| 他席 | 整册 | 新行 |\n".encode()
            Path.write_bytes(self, fresh)
            return real_rb(self)
        return data

    monkeypatch.setattr(dts, "_integrity_token_of", lambda raw: (0, "0" * 16))
    monkeypatch.setattr(Path, "read_bytes", racing_rb)
    assert dts.tail_append(ledger, ["| TX12 | c | z |"]) == "appended"
    monkeypatch.undo()
    assert "| 他席 | 整册 | 新行 |" not in ledger.read_text(encoding="utf-8"), \
        "注毒没杀动＝这条复现锁是空跑"


def test_tail_append_picks_up_interloper_line_via_retry(dts, tmp_path, monkeypatch) -> None:
    """不注毒正锁：尾附窗口内他席整册落盘 ⇒ 终态**两行都在**（CAS 语义＝合并而不是覆盖）。"""
    ledger = tmp_path / "OWNERSHIP.md"
    ledger.write_bytes(b"| seat | face | t |\n")
    real_rb = Path.read_bytes
    state = {"flipped": False}

    def racing_rb(self: Path) -> bytes:
        data = real_rb(self)
        if not state["flipped"]:
            state["flipped"] = True
            fresh = data + "| 他席 | 整册 | 新行 |\n".encode()
            Path.write_bytes(self, fresh)
            return fresh
        return data

    monkeypatch.setattr(Path, "read_bytes", racing_rb)
    assert dts.tail_append(ledger, ["| TX11 | c | z |"]) == "appended"
    monkeypatch.undo()
    text = ledger.read_text(encoding="utf-8")
    assert "| 他席 | 整册 | 新行 |" in text, "CAS 尾附把他人整册吃了＝丢追加形复发"
    assert "| TX11 | c | z |" in text


# ---------------------------------------------------------------- ①/双进程读回腿
_CHILD = '''
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, r"__SCRIPTS__")
os.environ["BOT_AUTOSYNC"] = "0"
import doc_template_sync as dts

BOX = Path(sys.argv[1])
FM = ("---\\ntemplate: seat-report\\nparams:\\n  seat_id: TX261D\\n"
      "  wave: 2026-09-22-taxonomy\\n  status: DONE\\n  role: impl\\n"
      "  report_class: auto:seat_class\\n  ledger_events: auto:page_stat:ledger\\n---\\n")
PAGE = FM + "\\nStatus: DONE\\n\\n# 夹具\\n\\n## 交付\\n\\n- 事件一\\n\\n## 自报\\n\\n- 收尾\\n"
f = BOX / "SEAT-TX261D.md"
text = dts._page_text_from_bytes(f.read_bytes())
pg = dts.PageInfo(rel=".superpowers/sdd/2026-09-22-taxonomy/SEAT-TX261D.md",
                  path=f, text=text, category="seat-report")
pg.fm = dts.parse_front_matter(text)
schemas = dts.load_schemas()
real_aw = dts._atomic_write_bytes

def hooked(path, data):
    real_aw(path, data)
    (BOX / "A_committed").write_text("1")
    deadline = time.time() + 60
    while not (BOX / "A_go").exists():
        if time.time() > deadline:
            raise RuntimeError("放行超时")
        time.sleep(0.02)

dts._atomic_write_bytes = hooked
out = {"outcome": "", "needle": False, "interloper": False, "not_rolled_back": False}
try:
    out["outcome"] = "RETURN:" + repr(dts.write_page(pg, schemas))
except Exception as exc:
    out["outcome"] = type(exc).__name__ + "|" + str(exc)[:200]
t = f.read_text(encoding="utf-8")
out["needle"] = "TEMPLATE-AUTO:BEGIN" in t
out["interloper"] = "他席合法提交" in t
out["not_rolled_back"] = "未回滚" in out["outcome"]
(BOX / "A_result.json").write_text(json.dumps(out), encoding="utf-8")
'''


def _run_child(tmp_path: Path, box: Path) -> dict:
    child = tmp_path / "_tx261_child.py"
    child.write_text(_CHILD.replace("__SCRIPTS__", str(SCRIPTS)), encoding="utf-8")
    (box / "SEAT-TX261D.md").write_text(PAGE, encoding="utf-8", newline="\n")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", BOT_AUTOSYNC="0",
               PYTHONIOENCODING="utf-8", PYTHONPYCACHEPREFIX=str(tmp_path / "cc"))
    proc = subprocess.Popen([sys.executable, "-u", str(child), str(box)], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    page = box / "SEAT-TX261D.md"
    deadline = time.time() + 90
    while not (box / "A_committed").exists():
        if proc.poll() is not None or time.time() > deadline:
            raise AssertionError("子进程未进读回窗")
        time.sleep(0.02)
    with page.open("ab") as fh:  # B＝真第二进程在「本席已落盘、读回之前」提交一行正文
        fh.write("\n他席合法提交：这一行绝不该被回滚抬走\n".encode())
    (box / "A_go").write_text("1")
    while not (box / "A_result.json").exists():
        if proc.poll() is not None or time.time() > deadline:
            raise AssertionError("子进程未交卷")
        time.sleep(0.02)
    proc.wait(timeout=30)
    return json.loads((box / "A_result.json").read_text(encoding="utf-8"))


def test_dual_process_readback_leg_never_eats_other_commit(tmp_path) -> None:
    """真双进程·第五道读回腿：盘上那份不是我写的 ⇒ 必抛且**只放弃不抬**（TX242 §4.2 形闭合）。"""
    box = tmp_path / "dual"
    box.mkdir()
    verdict = _run_child(tmp_path, box)
    assert verdict["outcome"].startswith("PageConcurrentMutation"), verdict
    assert verdict["interloper"], f"他席提交被回滚抬走：{verdict}"
    assert verdict["not_rolled_back"], f"消息没如实写「未回滚」：{verdict}"
