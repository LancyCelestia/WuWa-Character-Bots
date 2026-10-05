"""重启前入口链门（第 15 项 ``entry_chain``）与 ``restart-check`` 接线的回归锁。

缺陷（2026-10-04 现算，实证见 ``ChatBot_Runtime/cache/seat-restartsafe/REPORT.md`` §6 B4；
假绿形态清单 245「修法在册≠修好在盘」）：09-27 立项的施工图 SDD
``.superpowers/sdd/2026-09-27-fullload/reports-m2/M2-44-ENTRY-PROBE-LANDING.md``
要的是「重启前必跑入口 import 链」，而盘上从来没有——

* ``scripts/pre_restart_check.py`` 的在册项里**没有** ``entry_chain``（探针真身
  ``scripts/import_chain_probe.py`` 自 09-27 就在库，运行面零消费者）；
* ``scripts/chatbot-tasks.json`` 里**没有** ``restart-check``，``run``/``run-watch``
  也没有任何一步指向预检 ⇒ 载体 ``ChatBot_Runtime\\restart_bot.ps1`` 先杀后起、中间零判据。

代价（本仓实撞过的形态，见探针真身 docstring 首段）：入口链上任一模块级求值抛错 ⇒
nonebot 只记一条 error、``bot.py`` 崩溃守卫 ``raise`` ⇒ 插件全体不注册；
``BOT_SUPERVISE=1`` 退避 5+15+60+60≈140 秒后永久 down，等人来救。

本件的判据形状（一条都不许松）：
  ① 在册且默认跑：``entry_chain`` 进声明侧清单，``run_all`` 默认全选；
  ② **只认探针自己的退出码**，绝不认它的回显（本仓被「宣布成功的回显」骗过多次）：
     rc≠0 时哪怕 stdout 通篇「放心重启」也必红；rc=0 时哪怕 stdout 危言耸听也必绿；
  ③ 探针「一格都没跑」不算绿：rc=0 + ``cells=[]`` 是探针自身 setup 失败的形态
     （现算：解释器没装 nonebot 时探针就报 rc=0「全链可导」）＝**没有证据**；
  ④ 真件真炸：``%TEMP%`` 的 HEAD 副本里给入口链第一格模块**行首**插一枚模块级
     ``re.compile(")")`` ⇒ 本项 FAIL 且 ``details["probe_rc"]`` 就是驱动它的那枚 rc；
     撤毒复跑转绿。（毒必须插行首：副本没有 ``.env``，配置形态的错会先抛、
     被探针折成 INCONCLUSIVE ⇒ 尾插的毒根本执行不到，那一条腿就是空腿。）
  ⑤ 「重启会带走谁」当**数据**交付：``plugins/**`` 下 tracked-modified 模块的点分名
     清单＋计数进 ``details``；git 读不到时 ``working_tree_known=False`` 并带原因，
     **绝不得宣称「没有改动」**（读不到＝没有证据，照第 14 项同一口径）；
  ⑥ ``restart-check`` 任务在册、``run``/``run-watch`` 在起 ``bot.py`` **之前**调它，
     且只按 ``entry_chain`` 这一格定红绿（``--only``）——旁格红（ruff/文档账）不该
     把「起得来」这条路一起堵死。
  ⑦ **结构地板四形**（2026-10-04 ``seat-gateverify`` 复核抓到的洞，假绿形态清单 249）：
     rc=0 只是**必要**条件，不再充分。同批钉四形——①stdout 空／②stdout 解析不出 JSON
     （空壳桩件正是本仓「退役＝留再导出垫片」的先例造得出的东西）／③``cells=[]``／
     ④``cells`` 里有 ``status=FAIL`` 的格——任一命中即 FAIL，且 PASS 那句
     「全无可导失败」绝不出现在这些读数里（判据加的是**结构化证据**要求，不采散文）。
  ⑧ git 缝不得抛穿 ``run_all``：``working_tree_plugin_modules`` 排在探针**之前**且原先
     无异常捕获 ⇒ 没装 git／``git status`` 挂住都能把整个 15 项预检炸掉，而在
     ``run-watch`` 里 throw 穿出 ``loop`` 步＝**看门狗自尽、永久 down**。现算＝git 调用
     带超时、异常一律折成既有的 ``working_tree_known=False`` 那一种表示（禁第二表示法），
     本项报「读不到」而不是「干净」，更不许把整格炸掉。

全离线：零网络、零进程信号、零 git 写（``git archive`` 只读）、不跑 ``bot.py``、
不碰生产数据根（探针自己把 ``BOT_RUNTIME_DATA_DIR`` 重映射进 ``%TEMP%``）。
副本一律落在 ``tmp_path_factory`` 的仓外临时区，源码树零写入（AGENTS.md 规则 6）。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import pre_restart_check as prc

PASS, SKIP, FAIL = prc.PASS, prc.SKIP, prc.FAIL

#: 模块级求值炸药（形状＝2026-09-29 那一次的真缺陷：re.compile 里多一个右括号）。
POISON_SRC = 'import re as _seat_poison_re\n_seat_poison_re.compile(")")\n'
#: 入口链缺省名单第一格（真身 ``scripts/import_chain_probe.py::CELL_MODULES``）。
POISON_TARGET = Path("plugins") / "bot_unified_runtime" / "config.py"

#: 探针报喜的原文（回显不参与判定，这条串出现在任何 rc≠0 的读数里都不许改判）。
GREEN_PROSE = "汇总: FAIL 0 / INCONCLUSIVE 0 / OK 12 → 全链可导（放心重启，一切正常）"


def probe_payload(cells: list[dict[str, object]]) -> str:
    """造探针的 ``--json`` 读数（只喂「回显不可信」那两条腿）。"""
    return json.dumps(
        {
            "root": "x",
            "setup": "nonebot.init OK（未 run、未绑端口）",
            "exit_code": 1 if any(c.get("status") == "FAIL" for c in cells) else 0,
            "plugins": {"status": "OK", "loaded": 9, "target_loaded": True, "failed": []},
            "cells": cells,
        },
        ensure_ascii=False,
    )


def make_run(payload: str, rc: int = -1, porcelain: str = "", git_rc: int = 0):
    """``run_cmd`` 替身：``git`` 走 porcelain，其余走探针 payload；rc<0 时按 payload 自算。"""

    def _run(args: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str, str]:
        if args and args[0] == "git":
            return git_rc, porcelain, ""
        effective = payload_rc(payload) if rc < 0 else rc
        return effective, payload, ""

    return _run


def payload_rc(payload: str) -> int:
    return int(json.loads(payload.splitlines()[0])["exit_code"])


def touch_probe(root: Path) -> Path:
    """假根里放一枚探针占位件（本项先核真身在不在，再谈跑不跑）."""
    probe = root / prc.ENTRY_CHAIN_PROBE_REL
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("# 占位件：真探针只在真根/副本里跑，本用例只验判定形状\n", encoding="utf-8")
    return probe


# ---------------------------------------------------------------------------
# ① 在册、默认跑
# ---------------------------------------------------------------------------

def test_entry_chain_is_declared_and_selected_by_default_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "entry_chain" in prc.declared_item_ids(), "第 15 项没进声明侧清单＝门读不到这把尺"
    root = tmp_path / "proj"
    (root / "plugins").mkdir(parents=True)
    touch_probe(root)
    monkeypatch.setattr(prc, "run_cmd", make_run(probe_payload([{"cell": "x", "status": "OK"}])))
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    ids = [r.id for r in prc.run_all(root)]
    assert ids == prc.declared_item_ids()  # 声明侧与注册面一对一（既有跟随锁同判据）
    assert "entry_chain" in ids
    # 旧句 `ids[-1] == "entry_chain" or "entry_chain" in ids` 的右侧是上一行的复述⇒恒真，
    # 整条断言永不失败＝什么都不钉（台账 #67★ 同族：恒真分支＝假绿）。改写＝把这条锁
    # **打算允许的两种形态各自显式钉住**：
    #   形态甲「entry_chain 占队尾」＝现役约定，由本件钉死（后续加项要占队尾须显式改这里）；
    #   形态乙「entry_chain 不在队尾」＝本件**不**放行，只放行「它在册且只在一处」这一事实，
    #         于是这里断的是枚数与唯一性，不再靠 or 蒙位置。
    assert ids.count("entry_chain") == 1, f"本项在注册面出现 {ids.count('entry_chain')} 次：{ids}"
    assert ids[-1] == "entry_chain", f"注册面队尾必须是 entry_chain（形态甲），实得 {ids[-1]}：{ids}"


# ---------------------------------------------------------------------------
# ②③ 只认退出码 + 探针没开火不算绿
# ---------------------------------------------------------------------------

def test_status_is_driven_by_probe_rc_not_by_prose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "proj"
    touch_probe(root)
    ok_cell = {"cell": "plugins.bot_unified_runtime.config", "status": "OK"}

    # rc=1 而回显通篇报喜 ⇒ 必红（被骗过的那一型）
    boom = probe_payload([{"cell": "plugins.bot_unified_runtime", "status": "FAIL", "kind": "MODULE_LEVEL_EVAL_FAIL"}])
    monkeypatch.setattr(prc, "run_cmd", make_run(boom + "\n" + GREEN_PROSE))
    res = prc.check_entry_chain(root)
    assert res.status == FAIL, res.message
    assert res.details["probe_rc"] == 1
    assert res.details["probe_cells_fail"] == ["plugins.bot_unified_runtime"]
    assert res.fix_hint

    # rc=0 且确有一格 OK：回显再吓人也不改判（stdout 的散文根本不进判定）
    monkeypatch.setattr(prc, "run_cmd", make_run(probe_payload([ok_cell]) + "\n全部塌了别重启"))
    res = prc.check_entry_chain(root)
    assert res.status == PASS, f"rc=0 被判红了（判据被回显带跑了？）：{res.message}"
    assert res.details["probe_rc"] == 0

    # rc=2 =「探针自身无从判定」——不是绿
    monkeypatch.setattr(prc, "run_cmd", make_run("探针无从判定", rc=2))
    assert prc.check_entry_chain(root).status == FAIL

    # rc=0 但一格没跑（setup 挂了／解释器没装 nonebot）⇒ 没有证据，不许洗成全链可导
    empty = probe_payload([])
    monkeypatch.setattr(prc, "run_cmd", make_run(empty))
    res = prc.check_entry_chain(root)
    assert res.status == FAIL, "探针没开火却放行＝本次要根治的假绿形态"
    assert res.details["probe_cells_total"] == 0


def test_probe_is_pointed_at_the_working_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """默认轴＝当前工作树：探针必须被 ``--root`` 指到被测根，且带 ``--json`` 只取结构读数."""
    root = tmp_path / "proj"
    touch_probe(root)
    seen: list[list[str]] = []

    def spy(args: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str, str]:
        seen.append(list(args))
        if args and args[0] == "git":
            return 0, "", ""
        return 0, probe_payload([{"cell": "x", "status": "OK"}]), ""

    monkeypatch.setattr(prc, "run_cmd", spy)
    prc.check_entry_chain(root)
    probe_calls = [a for a in seen if a and a[0] != "git"]
    assert probe_calls, "本项一次都没调探针真身"
    argv = probe_calls[0]
    assert prc.ENTRY_CHAIN_PROBE_REL in argv[1], argv
    assert f"--root={root}" in argv or ("--root" in argv and str(root) in argv), argv
    assert "--json" in argv, "不带 --json 就只能读散文——本项要的正是结构化读数"


def test_missing_probe_script_is_fail_not_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """探针真身缺席＝本项无从判定，判红不判 SKIP（载体没了不许当放行）."""
    root = tmp_path / "no-probe"
    (root / "scripts").mkdir(parents=True)
    monkeypatch.setattr(prc, "run_cmd", make_run(probe_payload([{"cell": "x", "status": "OK"}])))
    assert prc.check_entry_chain(root).status == FAIL


# ---------------------------------------------------------------------------
# ④ 真件真炸（%TEMP% HEAD 副本 + 真探针）
# ---------------------------------------------------------------------------

def _need_nonebot() -> None:
    if importlib.util.find_spec("nonebot") is None:
        pytest.skip("本腿要跑真探针：需要装了 nonebot 的解释器（项目 venv python）")


@pytest.fixture(scope="module")
def head_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``git archive HEAD`` 抽一份仓外副本（只读 git、内容确定、不吃在飞稿）."""
    _need_nonebot()
    dest = tmp_path_factory.mktemp("restartgate_head") / "head"
    dest.mkdir(parents=True, exist_ok=True)
    tar = tmp_path_factory.mktemp("restartgate_tar") / "head.tar"
    proc = subprocess.run(
        ["git", "archive", "HEAD", "-o", str(tar)],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert proc.returncode == 0, f"git archive 失败 rc={proc.returncode}：{proc.stderr[:200]}"
    with tarfile.open(tar) as handle:
        handle.extractall(dest)  # 只解本腿刚生成的 HEAD 归档，落点是仓外空目录
    assert (dest / POISON_TARGET).is_file(), "副本里没有入口链第一格，本腿前提塌了"
    return dest


def test_broken_module_in_copy_fails_then_restores_green(head_copy: Path) -> None:
    target = head_copy / POISON_TARGET
    original = target.read_bytes()
    try:
        before = prc.check_entry_chain(head_copy)
        assert before.status == PASS, f"HEAD 副本本该绿，实得 {before.status}／{before.message}"
        assert before.details["probe_rc"] == 0

        target.write_bytes(POISON_SRC.encode("utf-8") + original)
        poisoned = prc.check_entry_chain(head_copy)
        assert poisoned.status == FAIL, f"模块级 re.compile(\")\") 没让本项红：{poisoned.message}"
        assert poisoned.details["probe_rc"] == 1, "本项必须由探针自己的退出码驱动"
        assert any("config" in cell for cell in poisoned.details["probe_cells_fail"]), poisoned.details

        target.write_bytes(original)
        restored = prc.check_entry_chain(head_copy)
        assert restored.status == PASS, f"撤毒后没转绿（判据有惯性/缓存？）：{restored.message}"
        assert restored.details["probe_rc"] == 0
    finally:
        target.write_bytes(original)


def test_live_tree_probe_reports_without_writing_source_tree() -> None:
    """现网轴：默认工作树跑得动，且跑完源码树仍零缓存（规则 6 的自证腿）."""
    _need_nonebot()
    res = prc.check_entry_chain(PROJECT_ROOT)
    assert res.status in (PASS, FAIL), f"本项只产 PASS/FAIL，不产 SKIP：{res.status}"
    assert res.details["probe_root"] == str(PROJECT_ROOT.resolve())
    assert res.details["probe_cells_total"] > 0
    residue = [p for p in PROJECT_ROOT.rglob("__pycache__") if p.is_dir()]
    assert not residue, f"探针把字节码倒进了源码树（规则 6 破口）：{residue[:3]}"


# ---------------------------------------------------------------------------
# ⑤ 「重启会带走谁」当数据交付
# ---------------------------------------------------------------------------

PORCELAIN = """\
 M plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py
M  plugins/bot_unified_runtime/__init__.py
 M plugins/bot_unified_runtime/domains/chat_reply/character/__init__.py
 M docs/HANDBOOK.md
 D plugins/bot_unified_runtime/sources/gone.py
?? plugins/bot_unified_runtime/sources/unfinished.py
R  plugins/a/old.py -> plugins/b/new.py
 M scripts/pre_restart_check.py"""


def test_modified_plugin_modules_are_listed_as_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """tracked-modified、限 ``plugins/**``、点分名、排序去重；未跟踪/删除/文档/脚本都不进."""
    monkeypatch.setattr(prc, "run_cmd", make_run("", rc=0, porcelain=PORCELAIN))
    modules, note = prc.working_tree_plugin_modules(tmp_path)
    assert note == ""
    assert modules == (
        "plugins.bot_unified_runtime",
        "plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat",
        "plugins.bot_unified_runtime.domains.chat_reply.character",
    ), modules

    touch_probe(tmp_path)
    monkeypatch.setattr(
        prc, "run_cmd",
        make_run(probe_payload([{"cell": "x", "status": "OK"}]), porcelain=PORCELAIN),
    )
    res = prc.check_entry_chain(tmp_path)
    assert res.details["working_tree_known"] is True
    assert res.details["modified_plugin_count"] == 3
    assert res.details["modified_plugin_modules"][0] == "plugins.bot_unified_runtime"
    assert "x3" in res.message, res.message
    assert "unfinished" not in res.message and "gone" not in res.message


def test_unreadable_working_tree_never_claims_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """git 读不到＝没有证据：清单为空也必须自报「不知道」，不得写成「没有改动」."""
    monkeypatch.setattr(prc, "run_cmd", make_run("", rc=0, porcelain="", git_rc=128))
    modules, note = prc.working_tree_plugin_modules(tmp_path)
    assert modules == () and note and "git" in note
    touch_probe(tmp_path)
    monkeypatch.setattr(
        prc, "run_cmd",
        make_run(probe_payload([{"cell": "x", "status": "OK"}]), git_rc=128),
    )
    res = prc.check_entry_chain(tmp_path)
    assert res.details["working_tree_known"] is False
    assert res.details["modified_plugin_count"] == 0
    assert "读不到" in res.message, res.message


def test_head_copy_reports_unknown_not_clean(head_copy: Path) -> None:
    """HEAD 副本按定义零改动，但它不是 git 检出 ⇒ 本项报「读不到」而不是「干净」。

    与 ④ 互不掩盖：毒面判红靠探针 rc，「带走谁」靠 git 读数——两格各自诚实。
    """
    modules, note = prc.working_tree_plugin_modules(head_copy)
    assert modules == ()
    assert note != "", "读不到 git 却留空 note＝会被读成「这棵树没有改动」＝假绿"


def test_live_tree_reports_whats_actually_dirty() -> None:
    """现网面：清单必须与一次**独立的** porcelain 读数同形（不写死今天的枚数，规则 10）."""
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", "plugins"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
    )
    assert proc.returncode == 0, f"git status 不可用：{proc.stderr[:200]}"
    independent: set[str] = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4 or "?" in line[:2] or "M" not in line[:2]:
            continue
        path = line[3:].strip().strip('"').replace("\\", "/")
        if not path.startswith("plugins/") or not path.endswith(".py"):
            continue
        name = ".".join(path[:-3].split("/"))
        independent.add(name.removesuffix(".__init__"))

    modules, note = prc.working_tree_plugin_modules(PROJECT_ROOT)
    assert note == "", note
    assert set(modules) == independent, (
        f"与独立读数不符：只在本项 {sorted(set(modules) - independent)}｜只在独立尺 "
        f"{sorted(independent - set(modules))}"
    )
    assert modules == tuple(sorted(set(modules)))
    assert all(m.startswith("plugins.") and "/" not in m for m in modules)


# ---------------------------------------------------------------------------
# ⑥ 任务表接线 + 既有 task-driver 锁不破
# ---------------------------------------------------------------------------

TASKS_JSON = PROJECT_ROOT / "scripts" / "chatbot-tasks.json"


def _tasks() -> dict:
    return json.loads(TASKS_JSON.read_text(encoding="utf-8"))["tasks"]


def _walk_nodes(node: object, types: tuple[str, ...]):
    """按**文档序**产出指定步型节点（顺序即 dev.ps1 的执行序）."""
    if isinstance(node, dict):
        if node.get("type") in types:
            yield node
        for value in node.values():
            yield from _walk_nodes(value, types)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_nodes(item, types)


def test_restart_check_task_exists_and_points_at_the_check() -> None:
    tasks = _tasks()
    assert "restart-check" in tasks, "任务表里没有 restart-check＝重启流程一个门都没挂"
    body = tasks["restart-check"]
    assert body.get("push") is False and body.get("pythonTool") is True, body
    commands = list(_walk_nodes(body["steps"], ("command",)))
    assert commands and commands[-1].get("pythonScript") == prc.PRE_RESTART_CHECK_REL, commands
    rendered = json.dumps(commands[-1], ensure_ascii=False)
    assert "entry_chain" in rendered, "restart-check 没锁到 entry_chain 这一格"
    assert commands[-1].get("runner") == "external", "runner 必须非 soft：软失败＝红了也照样往下跑"


def test_run_and_run_watch_gate_before_bot_py() -> None:
    for task_name in ("run", "run-watch"):
        steps = list(_walk_nodes(_tasks()[task_name]["steps"], ("command", "subtask")))
        kinds = [s.get("pythonScript") or f"subtask:{s.get('task')}" for s in steps]
        assert "subtask:restart-check" in kinds, f"{task_name} 没有在起 bot 前过门：{kinds}"
        bot_at = [i for i, k in enumerate(kinds) if k == "bot.py"]
        gate_at = [i for i, k in enumerate(kinds) if k == "subtask:restart-check"]
        assert bot_at and max(gate_at) < min(bot_at), f"{task_name}：门排在 bot.py 之后＝形同虚设 {kinds}"


def test_only_flag_selects_rows_and_rejects_unknown_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--only`` 只交出一格、退出码只由它定；未知 id 大声失败（不静默少跑一项）."""
    root = tmp_path / "proj"
    root.mkdir()
    touch_probe(root)
    monkeypatch.setattr(prc, "run_cmd", make_run(probe_payload([{"cell": "x", "status": "OK"}])))
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    assert prc.main(["--only", "entry_chain", "--json", "--project-root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in payload["results"]] == ["entry_chain"]
    assert payload["exit_code"] == 0  # 旁格（假根的 env_paths 必红）不参与本次判定

    # 本项红的时候，--only 的退出码必须跟着红（restart-check 才有牙）
    monkeypatch.setattr(prc, "run_cmd", make_run(probe_payload([{"cell": "x", "status": "FAIL"}])))
    assert prc.main(["--only", "entry_chain", "--json", "--project-root", str(root)]) == 1
    capsys.readouterr()

    assert prc.main(["--only", "no_such_item", "--project-root", str(root)]) == 2
    assert "no_such_item" in capsys.readouterr().err


def test_human_table_carries_the_new_item(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """人读表格里这一格必须点名「探针 rc」与「带走几枚」——操作者按的是表格不是 JSON."""
    root = tmp_path / "proj"
    root.mkdir()
    touch_probe(root)
    monkeypatch.setattr(
        prc,
        "run_cmd",
        make_run(probe_payload([{"cell": "x", "status": "OK"}]), porcelain=PORCELAIN),
    )
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    assert prc.main(["--only", "entry_chain", "--project-root", str(root)]) == 0
    table = capsys.readouterr().out
    assert "entry_chain" in table and "x3" in table, table


# ---------------------------------------------------------------------------
# ⑦ 结构地板四形：rc=0 是必要条件，不再是充分条件
# ---------------------------------------------------------------------------

#: 三种「探针交不回结构化读数」的真形态（复核 §1 实测都能拿到 PASS）
SILENT_OR_LYING = (
    ("空壳桩件", "# 假根占位件（真探针在仓外副本里跑）\n"),
    ("一声不吭", ""),
    ("只有散文", "汇总: FAIL 0 / INCONCLUSIVE 0 / OK 12 → 全链可导（放心重启，一切正常）"),
)


@pytest.mark.parametrize("label,stdout", SILENT_OR_LYING, ids=[s[0] for s in SILENT_OR_LYING])
def test_rc_zero_without_structured_reading_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str, stdout: str
) -> None:
    """⑦形①②：探针被换成空壳／读数写到非 stdout／压根没输出 ⇒ 红，不许按 rc 放行."""
    root = tmp_path / "proj"
    touch_probe(root)
    monkeypatch.setattr(prc, "run_cmd", make_run(stdout, rc=0))
    res = prc.check_entry_chain(root)
    assert res.status == FAIL, f"{label}：rc=0 且零结构化证据却放行＝门能转绿且在撒谎"
    assert res.details["probe_payload_parsed"] is False
    assert res.details["probe_cells_total"] == 0
    assert "全无可导失败" not in res.message, res.message
    assert res.fix_hint


def test_rc_zero_with_empty_cells_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑦形③：可解析但 ``cells=[]``（探针自己 setup 没成）＝没有证据."""
    root = tmp_path / "proj"
    touch_probe(root)
    monkeypatch.setattr(prc, "run_cmd", make_run(probe_payload([]), rc=0))
    res = prc.check_entry_chain(root)
    assert res.status == FAIL, "探针没开火却放行＝本波要根治的假绿形态（既有③同判据）"
    assert res.details["probe_payload_parsed"] is True
    assert res.details["probe_cells_total"] == 0
    assert "全无可导失败" not in res.message, res.message


def test_rc_zero_that_disagrees_with_its_own_cells_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⑦形④：rc=0 却交回 status=FAIL 的格——退出码与自家读数矛盾时按红的记."""
    root = tmp_path / "proj"
    touch_probe(root)
    lying = probe_payload(
        [
            {"cell": "plugins.bot_unified_runtime.config", "status": "OK"},
            {
                "cell": "plugins.bot_unified_runtime.runtime.content_route",
                "status": "FAIL",
                "kind": "MODULE_LEVEL_EVAL_FAIL",
                "location": "plugins/bot_unified_runtime/runtime/content_route.py:1",
            },
        ]
    )
    monkeypatch.setattr(prc, "run_cmd", make_run(lying, rc=0))
    res = prc.check_entry_chain(root)
    assert res.status == FAIL, "rc=0 但自家 cells 里躺着 FAIL＝回显与数据相互矛盾（复核 §1 次因）"
    assert res.details["probe_cells_fail"] == ["plugins.bot_unified_runtime.runtime.content_route"]
    assert "content_route" in res.message, res.message
    assert "全无可导失败" not in res.message, res.message


def test_probe_passes_only_with_a_parseable_nonempty_all_ok_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """地板收紧后真形态仍要能绿：rc=0 + 可解析 + cells 非空 + 无 FAIL 格 = PASS."""
    root = tmp_path / "proj"
    touch_probe(root)
    monkeypatch.setattr(
        prc, "run_cmd", make_run(probe_payload([{"cell": "plugins.x", "status": "OK"}]), rc=0)
    )
    res = prc.check_entry_chain(root)
    assert res.status == PASS, res.message
    assert res.details["probe_payload_parsed"] is True
    assert res.details["probe_cells_total"] == 1
    assert res.details["probe_skipped_cells"] == []


def test_inconclusive_cells_are_named_loudly_on_the_pass_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """环境缺席的格不算红（离线/CI 不能被炸），但必须当**点名 SKIP**上屏，不许静默吞掉.

    取舍：SKIP 保持「不阻断」（否则没装 nonebot 的机器上重启门恒红＝门被绕过比被拦住更坏），
    代价是 PASS 那句满话必须让位——有名有姓的 SKIP x{N} 与点名单是操作者在表格里看得到的东西。
    """
    root = tmp_path / "proj"
    touch_probe(root)
    payload = probe_payload(
        [
            {"cell": "plugins.bot_unified_runtime.config", "status": "OK"},
            {"cell": "plugins.bot_unified_runtime.runtime.content_route", "status": "INCONCLUSIVE"},
        ]
    )
    monkeypatch.setattr(prc, "run_cmd", make_run(payload, rc=0))
    res = prc.check_entry_chain(root)
    assert res.status == PASS
    assert res.status != SKIP, "本项自身不产 SKIP：拦的就是按下重启那一下"
    assert res.details["probe_skipped_cells"] == ["plugins.bot_unified_runtime.runtime.content_route"]
    assert "SKIP" in res.message and "content_route" in res.message, res.message
    assert "全无可导失败" not in res.message, "有格没验到就不许说满话"


# ---------------------------------------------------------------------------
# ⑧ git 缝：读不到一律折成「unknown」，绝不外抛顶穿 run-watch 的 loop 步
# ---------------------------------------------------------------------------

def _run_cmd_git_blows_up(exc: BaseException, payload: str, seen: list[int] | None = None):
    """``run_cmd`` 替身：git 那一路抛出（没装 git／挂住），探针照常吃 payload."""

    def _run(args: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str, str]:
        if args and args[0] == "git":
            if seen is not None:
                seen.append(timeout)
            raise exc
        return 0, payload, ""

    return _run


def test_git_binary_missing_reports_unknown_instead_of_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "proj"
    touch_probe(root)
    stub = _run_cmd_git_blows_up(FileNotFoundError(2, "git not found"), probe_payload([{"cell": "x", "status": "OK"}]))
    monkeypatch.setattr(prc, "run_cmd", stub)
    modules, note = prc.working_tree_plugin_modules(root)
    assert modules == () and "读不到" in note and "git" in note, note
    res = prc.check_entry_chain(root)
    assert res.details["working_tree_known"] is False
    assert res.details["modified_plugin_count"] == 0
    assert "读不到" in res.message, res.message
    assert "无 tracked-modified" not in res.message and "同码" not in res.message, res.message


def test_hanging_git_is_bounded_and_reports_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``git status`` 挂住（复核实测 120s）⇒ 必须由超时兜住并折成 unknown，不得外抛."""
    root = tmp_path / "proj"
    touch_probe(root)
    seen: list[int] = []
    hang = subprocess.TimeoutExpired(cmd=["git", "status", "--porcelain"], timeout=1, output=b"", stderr=b"")
    monkeypatch.setattr(
        prc, "run_cmd", _run_cmd_git_blows_up(hang, probe_payload([{"cell": "x", "status": "OK"}]), seen)
    )
    modules, note = prc.working_tree_plugin_modules(root)
    assert modules == () and "读不到" in note, note
    assert seen and seen[0] == prc.ENTRY_CHAIN_GIT_TIMEOUT, f"git 读数没走有界超时：{seen}"
    assert prc.ENTRY_CHAIN_GIT_TIMEOUT < 120, "超时值必须严于复核量到的那次挂法"
    res = prc.check_entry_chain(root)
    assert res.details["working_tree_known"] is False and res.status == PASS


def test_collector_blowup_cannot_take_down_run_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run-watch`` 的 loop 一步被 throw 顶穿＝看门狗自尽、永久 down⇒采集面任何异常都不得外抛."""
    root = tmp_path / "proj"
    touch_probe(root)

    def _boom(_root: Path) -> tuple[tuple[str, ...], str]:
        raise RuntimeError("采集器内部炸了（git 之外的第二种失效形态）")

    monkeypatch.setattr(prc, "run_cmd", make_run(probe_payload([{"cell": "x", "status": "OK"}])))
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    monkeypatch.setattr(prc, "working_tree_plugin_modules", _boom)
    res = prc.check_entry_chain(root)  # 不得抛
    assert res.status in (PASS, FAIL)
    assert res.details["working_tree_known"] is False
    assert "读不到" in res.message, res.message
    ids = [r.id for r in prc.run_all(root)]  # 整张预检表也不许被顶穿
    assert ids == prc.declared_item_ids()
