"""pre_restart_check 离线回归：每类检查的 PASS/FAIL/SKIP 判定逻辑.

全部离线：tmp_path 构造假项目环境（.env / 假知识库副本 / 假 qx.json），
子进程与 TCP 探针经 monkeypatch 注入，不发真网络、不跑真 ruff。
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import pre_restart_check as prc

PASS, SKIP, FAIL = prc.PASS, prc.SKIP, prc.FAIL


# ---------------------------------------------------------------------------
# 假环境构造
# ---------------------------------------------------------------------------

def make_project(tmp_path: Path, *, with_qx: bool = True) -> Path:
    """造一个最小假项目根：.env 四键齐全且指向 tmp 内真实存在的路径."""
    root = tmp_path / "proj"
    root.mkdir()
    data_root = tmp_path / "rt_data"
    data_root.mkdir()
    wiki_root = tmp_path / "crawl_wiki"
    wiki_root.mkdir()
    persona = data_root / "persona"
    persona.mkdir()
    persona_file = persona / "守岸人_核心人格.md"
    persona_file.write_text("人格正文", encoding="utf-8")
    if with_qx:
        qx_dir = root / "plugins" / "bot_unified_runtime" / "domains" / "weather" / "assets"
        qx_dir.mkdir(parents=True)
        (qx_dir / "qx.json").write_text("{}", encoding="utf-8")
    # 2026-10-04 第 15 项 entry_chain：本件的假根必须供得起那一格的「真身在不在」前提——
    # 探针真身缺席＝该项判红＝整份预检 exit 1，会把「其余项全绿」的既有判据一并带走。
    # 占位件足够：本件全程把 run_cmd 注掉，真探针由 tests/test_pre_restart_entry_chain.py
    # 在仓外副本里真跑。
    probe_dir = root / "scripts"
    probe_dir.mkdir(parents=True, exist_ok=True)
    (probe_dir / "import_chain_probe.py").write_text("# 假根占位件（真探针在仓外副本里跑）\n", encoding="utf-8")
    (root / ".env").write_text(
        "\n".join(
            [
                f"BOT_RUNTIME_DATA_DIR={data_root}",
                f"BOT_KB_WIKI_ROOT={wiki_root}",
                f'BOT_PERSONA_FILES=["{persona_file.as_posix()}"]',
                f"BOT_KNOWLEDGE_DB_PATH={data_root / 'knowledge_embeddings.sqlite3'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def make_kb(db_path: Path, *, chunks: int, embedded: int) -> None:
    """造假知识库：knowledge_chunks 表 + order.json（ANN 行数回退通道）."""
    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE knowledge_chunks (chunk_id TEXT PRIMARY KEY, vector_blob BLOB)"
    )
    for i in range(chunks):
        blob = b"v" * 4 if i < embedded else None
        con.execute(
            "INSERT INTO knowledge_chunks (chunk_id, vector_blob) VALUES (?, ?)",
            (f"c{i}", blob),
        )
    con.commit()
    con.close()
    order = [f"c{i}" for i in range(chunks)]
    db_path.with_name("knowledge_faiss.order.json").write_text(
        json.dumps(order), encoding="utf-8"
    )
    # 故意不创建 knowledge_faiss.index：faiss.read_index 找不到文件会抛异常，
    # 脚本按设计回退 order.json 行数——正好覆盖回退通道。


def all_subproc_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """三个子进程检查（persona/hash/docsync/ruff）全部注入为 exit 0."""

    monkeypatch.setattr(prc, "run_cmd", _honest_run)


#: 探针 ``--json`` 的真身形状（格名取自 scripts/import_chain_probe.py 的 CELL_MODULES，
#: status 取值照该文件的 ``OK = "OK"``）——第 15 项 entry_chain 读的就是这些字段。
_ENTRY_CHAIN_PROBE_JSON = json.dumps(
    {
        "root": "",
        "setup": "",
        "cells": [
            {"cell": "plugins.bot_unified_runtime.config", "status": "OK"},
            {"cell": "plugins.bot_unified_runtime", "status": "OK"},
        ],
        "plugins": None,
    },
    ensure_ascii=False,
)


def _honest_run(args: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str, str]:
    """子进程替身：判它绿之前，先交得出真身会给得出的读数。

    2026-10-04 ``seat-gatefix`` 洞1 把 entry_chain 的判据收成「rc=0 **且**有结构化读数」
    （rc=0 只算必要条件）：散文 ``"[绿] OK"`` 从此＝``unparseable``＝红。这正是门要防的形态
    （一把只会宣称成功的回显），所以该改的是**替身**、不是地板。两路各自照实：
    ①探针那路交回可解析 --json + 两格 ``status=OK``（本件全离线，真探针只在仓外副本跑，
    见 tests/test_pre_restart_entry_chain.py）；②``git status`` 在 tmp_path 假根上按定义
    就是 rc=128（不是 git 检出），替身不再把它洗成 rc=0——否则 entry_chain 会谎报
    「plugins/** 无 tracked-modified 模块（工作树与 HEAD 同码）」。
    """
    if "import_chain_probe" in " ".join(args):
        return 0, _ENTRY_CHAIN_PROBE_JSON, ""
    if args[:2] == ["git", "status"]:
        return 128, "", "fatal: not a git repository（假根按定义不是检出）"
    return 0, "[绿] OK", ""


@pytest.fixture(autouse=True)
def _drop_ambient_runtime_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """本件的假项目根完全由 ``tmp_path`` 构造 ⇒ 宿主进程 env 里的数据根必须摘掉。

    读数器 ``prc.load_env`` 经 ``load_runtime_env_values``＝「os.environ 优先于文件」，
    而 ``tests/conftest.py`` 的 L1 装配（2026-09-30，Runtime 根隔离缝）会把一枚**隔离
    根**放进进程 env ⇒ 夹具 ``.env`` 里那枚 ``BOT_RUNTIME_DATA_DIR=<tmp>/rt_data`` 被顶掉，
    检查面转去看空隔离根 ⇒ 五枚用例由 PASS 飘成 FAIL/SKIP（现算见席位报告
    S-FIX-RTPATH-L1）。摘掉后回到本件的设计不变量：落点只由夹具 ``.env`` 决定。
    本件只做**只读存在性**检查（``pre_restart_check`` 不 import scripts.runtime_paths、
    自己那枚 ``runtime_data_dir(env, root)`` 是纯函数），因此不碰生产根、也不触发隔离判定。
    """
    monkeypatch.delenv("BOT_RUNTIME_DATA_DIR", raising=False)


# ---------------------------------------------------------------------------
# 1. env_paths：PASS / 各类 FAIL
# ---------------------------------------------------------------------------

def test_env_paths_all_pass(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    env = prc.load_env(root)
    result = prc.check_env_paths(env, root)
    assert result.status == PASS
    assert "wiki 根 OK" in result.message
    assert "人格副本 x1 OK" in result.message
    assert "qx.json OK" in result.message


def test_env_paths_fail_missing_wiki_root(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    (Path(prc.load_env(root)["BOT_KB_WIKI_ROOT"])).rmdir()
    result = prc.check_env_paths(prc.load_env(root), root)
    assert result.status == FAIL
    assert "BOT_KB_WIKI_ROOT" in result.message
    assert "startup-audit-report.md" in result.fix_hint


def test_env_paths_fail_missing_persona_file(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    env = prc.load_env(root)
    persona_file = Path(json.loads(env["BOT_PERSONA_FILES"])[0])
    persona_file.unlink()
    result = prc.check_env_paths(prc.load_env(root), root)
    assert result.status == FAIL
    assert "BOT_PERSONA_FILES 缺失" in result.message


def test_env_paths_fail_missing_qx_json(tmp_path: Path) -> None:
    root = make_project(tmp_path, with_qx=False)
    result = prc.check_env_paths(prc.load_env(root), root)
    assert result.status == FAIL
    assert "qx.json" in result.message
    assert "AGENTS.md" in result.fix_hint


def test_env_paths_fail_missing_media_parent(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    # 把运行时数据根指到不存在的目录 → media_archive DB 父目录缺失
    env = dict(prc.load_env(root))
    env["BOT_RUNTIME_DATA_DIR"] = str(tmp_path / "no_such_dir")
    result = prc.check_env_paths(env, root)
    assert result.status == FAIL
    assert "BOT_MEDIA_ARCHIVE_DB_PATH 父目录不存在" in result.message


def test_env_parse_inline_comment_and_quotes(tmp_path: Path) -> None:
    """行内注释/引号剥离与 runtime_paths 语义对齐."""
    root = tmp_path / "proj2"
    root.mkdir()
    (root / ".env").write_text(
        'BOT_KB_WIKI_ROOT="D:/some dir" # 行内注释\n'
        "BOT_RUNTIME_DATA_DIR=data # trailing\n",
        encoding="utf-8",
    )
    env = prc.load_env(root)
    assert env["BOT_KB_WIKI_ROOT"] == "D:/some dir"
    assert env["BOT_RUNTIME_DATA_DIR"] == "data"


# ---------------------------------------------------------------------------
# 2/3/4. 子进程族检查：rc + 输出决定 PASS/SKIP/FAIL
# ---------------------------------------------------------------------------

def test_persona_sync_status_mapping(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cases = [
        (0, "[SKIP] 生产人格副本不存在", "", SKIP),
        (0, "[绿] 副本与锚定一致 sha256=ab12", "", PASS),
        (1, "[红] 生产人格副本被单方面改动", "", FAIL),
        (1, "", "traceback", FAIL),
    ]
    for rc, out, err, expected in cases:
        monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600, rc=rc, out=out, err=err: (rc, out, err))
        result = prc.check_persona_sync({}, tmp_path)
        assert result.status == expected, (rc, out, expected)
    # FAIL 必须带 --adopt 修复指引
    monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600: (1, "[红] DRIFT", ""))
    result = prc.check_persona_sync({}, tmp_path)
    assert "--adopt" in result.fix_hint


def test_hash_ledger_and_doc_sync_mapping(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600: (0, "ok", ""))
    assert prc.check_hash_ledger(tmp_path).status == PASS
    assert prc.check_doc_sync(tmp_path).status == PASS
    monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600: (1, "drift: DESIGN-SPEC.md", ""))
    hash_res = prc.check_hash_ledger(tmp_path)
    doc_res = prc.check_doc_sync(tmp_path)
    assert hash_res.status == FAIL and "drift" in hash_res.message
    assert "--write" in hash_res.fix_hint
    assert doc_res.status == FAIL and "--write" in doc_res.fix_hint


# ---------------------------------------------------------------------------
# 5. kb_drift：PASS / FAIL / SKIP（副本上查，不碰真库）
# ---------------------------------------------------------------------------

def test_kb_drift_pass_fail_skip(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    env = prc.load_env(root)
    db_path = Path(env["BOT_KNOWLEDGE_DB_PATH"])

    # SKIP：库未构建
    result = prc.check_kb_drift(env, root)
    assert result.status == SKIP

    # PASS：ANN(order.json) == chunks == embedded
    make_kb(db_path, chunks=3, embedded=3)
    result = prc.check_kb_drift(env, root)
    assert result.status == PASS
    assert "ANN=3 == chunks=3" in result.message

    # FAIL：ANN 落后（order.json 只登记 2 行）
    db_path.with_name("knowledge_faiss.order.json").write_text(
        json.dumps(["c0", "c1"]), encoding="utf-8"
    )
    result = prc.check_kb_drift(env, root)
    assert result.status == FAIL
    assert "ANN=2 vs chunks=3" in result.message
    assert "vector-audit.md" in result.fix_hint

    # FAIL：待嵌入（embedded < chunks）
    db_path.unlink()
    make_kb(db_path, chunks=3, embedded=2)
    result = prc.check_kb_drift(env, root)
    assert result.status == FAIL


# ---------------------------------------------------------------------------
# 6/7. ruff 映射 + napcat 提示不阻断
# ---------------------------------------------------------------------------

def test_ruff_mapping(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600: (0, "All checks passed!", ""))
    result = prc.check_ruff(tmp_path)
    assert result.status == PASS
    monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600: (1, "F401 unused import (x2)", ""))
    result = prc.check_ruff(tmp_path)
    assert result.status == FAIL
    assert "staticgate-final.md" in result.fix_hint


def test_napcat_probe_and_non_blocking(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = make_project(tmp_path)
    all_subproc_ok(monkeypatch)
    make_kb(Path(prc.load_env(root)["BOT_KNOWLEDGE_DB_PATH"]), chunks=2, embedded=2)

    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: False)
    results = prc.run_all(root)
    napcat = next(r for r in results if r.id == "napcat")
    assert napcat.status == SKIP  # 不可达 → SKIP（提示不阻断）
    assert prc.main(["--json", "--project-root", str(root)]) == 0  # exit 仍为 0

    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    results = prc.run_all(root)
    assert next(r for r in results if r.id == "napcat").status == PASS


def test_onebot_endpoints_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """多账号 = 多端口：探测集合由 ONEBOT_WS_URLS 决定，且令牌不外泄."""
    env = {
        "ONEBOT_WS_URLS": (
            '["ws://127.0.0.1:3001/?access_token=SECRET_ABC","ws://127.0.0.1:3002/?access_token=SECRET_XYZ"]'
        )
    }
    assert prc.onebot_endpoints(env) == [("127.0.0.1", 3001), ("127.0.0.1", 3002)]

    probed: list[tuple[str, int]] = []
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: probed.append((host, port)) or True)
    result = prc.check_napcat(prc.onebot_endpoints(env))
    assert probed == [("127.0.0.1", 3001), ("127.0.0.1", 3002)]
    assert result.status == PASS
    assert "SECRET_ABC" not in f"{result.name}{result.message}{result.fix_hint}"


def test_onebot_endpoints_fallback_and_separators() -> None:
    assert prc.onebot_endpoints({}) == [(prc.NAPCAT_HOST, prc.NAPCAT_PORT)]
    assert prc.onebot_endpoints({"ONEBOT_WS_URLS": ""}) == [(prc.NAPCAT_HOST, prc.NAPCAT_PORT)]
    assert prc.onebot_endpoints({"ONEBOT_WS_URLS": "bad json ["}) == [(prc.NAPCAT_HOST, 3001)]
    # 分号裸串写法等效；重复端点去重；非 ws 协议与坏端口跳过
    assert prc.onebot_endpoints(
        {
            "ONEBOT_WS_URLS": "ws://127.0.0.1:3002;ws://127.0.0.1:3002;"
            "http://127.0.0.1:9999;ws://127.0.0.1:notaport"
        }
    ) == [("127.0.0.1", 3002)]


def test_napcat_partial_down_reports_missing_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """学校号节点掉了必须点名，不能因为主号可达就全绿过去."""
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: port == 3001)
    env = {"ONEBOT_WS_URLS": '["ws://127.0.0.1:3001","ws://127.0.0.1:3002"]'}
    result = prc.check_napcat(prc.onebot_endpoints(env))
    assert result.status == SKIP  # 仍不阻断
    assert "127.0.0.1:3002" in result.message
    assert "127.0.0.1:3001" not in result.message  # 详情只点名掉线的那个
    assert "127.0.0.1:3001" in result.name  # 说明里列全部探测端点


# ---------------------------------------------------------------------------
# 汇总：exit code 与 --json 结构
# ---------------------------------------------------------------------------

def test_main_exit_code_and_json_structure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_project(tmp_path)
    all_subproc_ok(monkeypatch)
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    make_kb(Path(prc.load_env(root)["BOT_KNOWLEDGE_DB_PATH"]), chunks=2, embedded=2)

    assert prc.main(["--json", "--project-root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 0
    # 项数与逐项 id 序现算自真身声明侧（S146）：这里曾手写死 10→11→12→13 枚
    # 字面量清单，每长一项就要来跟一次账；改为 declared_item_ids()（= docstring
    # 编号清单派生）后，正确加项零跟随成本，文档与代码漂移则当场红。
    assert [r["id"] for r in payload["results"]] == prc.declared_item_ids()
    # 状态词汇表 2026-10-12 由三值扩到四值（第四态 UNDECIDABLE＝「尺量不了」）。放宽这条腿
    # 同批配的替代锁在下面三行：第四态只准带码出场、只准点名在册格、且这一轮唯一的产出者
    # 还是第 14 项——它不许变成「说不清就往里扔」的新筐（第 14 项假无缺口根修）。
    assert all(r["status"] in (PASS, SKIP, FAIL, prc.UNDECIDABLE) for r in payload["results"])
    declared_ids = set(prc.declared_item_ids())
    for row in payload["results"]:
        if row["status"] == prc.UNDECIDABLE:
            assert row["message"].startswith("UNDECIDABLE(") and ":" in row["message"], row
            assert row["details"].get("verdict") == prc.UNDECIDABLE, row
            assert row["id"] == "kb_domain_anchor", f"第四态扩面未经登记：{row['id']}"
            assert row["id"] in declared_ids, row

    # 注入一个 FAIL（ruff 挂）→ exit 1，且 JSON 里能定位到 FAIL 项与修复指引
    def ruff_fail(args, cwd, timeout=600):
        if "ruff" in args:
            return 1, "E501 line too long", ""
        if "import_chain_probe" in " ".join(args):
            # 2026-10-04 第 15 项 entry_chain 落地：本件的「只有 ruff 该红」前提要求入口链
            # 报绿。替身给不出真链证据（本件全离线），所以交回**可解析的空 cells**——
            # 该项自己的纪律是「一格都没跑＝没有证据＝红」，故这里必须给一格真读数。
            return 0, json.dumps({"cells": [{"cell": "plugins.bot_unified_runtime", "status": "OK"}]}), ""
        return 0, "[绿] OK", ""

    monkeypatch.setattr(prc, "run_cmd", ruff_fail)
    assert prc.main(["--json", "--project-root", str(root)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 1
    failed = [r for r in payload["results"] if r["status"] == FAIL]
    assert [r["id"] for r in failed] == ["ruff"]
    assert failed[0]["fix_hint"]

    # 人读表格路径：exit 1 且输出含修复指引段
    assert prc.main(["--project-root", str(root)]) == 1
    table = capsys.readouterr().out
    assert "FAIL 修复指引" in table and "汇总: " in table


# ---------------------------------------------------------------------------
# 8. webui：多文件壳资产（缺失=SKIP / 空·超限·外链·穿越·缺件·纯内联=FAIL / 合格=PASS）
# ---------------------------------------------------------------------------

# 纯内联占位（零本地资产引用）：多文件产物不该是这个形态 ⇒ 现在属反例（FAIL）。
SINGLE_FILE_HTML = (
    "<!doctype html><html><head>"
    '<meta charset="utf-8">'
    "<title>守岸人控制台</title>"
    "<style>body{margin:0}</style>"
    "</head><body>"
    '<div id="app"></div>'
    '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    # W3C 命名空间等正文 URL 字符串不算外链；script 正文中出现的 https 字符串同样不算
    '<script type="module">const u="https://example.com/not-a-tag";</script>'
    '<link rel="icon" href="data:image/svg+xml,%3Csvg%3E">'
    "</body></html>"
)

# 多文件壳（vite base '/ui/'）：stylesheet + module 脚本均指向本地 /ui/assets 资产。
MULTI_FILE_HTML = (
    "<!doctype html><html><head>"
    '<meta charset="utf-8">'
    '<link rel="stylesheet" href="/ui/assets/index-abc123.css">'
    "</head><body>"
    '<div id="app"></div>'
    '<link rel="icon" href="data:image/svg+xml,%3Csvg%3E">'
    '<script type="module" src="/ui/assets/index-abc123.js"></script>'
    "</body></html>"
)


def write_webui(root: Path, content: bytes | str) -> Path:
    dist = root / "webui" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    index = dist / "index.html"
    index.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return index


def write_webui_asset(root: Path, rel: str, content: bytes | str = b"/*asset*/") -> Path:
    """在 webui/dist/<rel> 落一枚资产（缺省非空）；rel 例：assets/index-abc123.js。"""
    target = root / "webui" / "dist" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return target


def test_webui_missing_is_skip_with_build_hint(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    result = prc.check_webui(root)
    assert result.status == SKIP
    assert "npm run build" in result.fix_hint
    assert "webui/dist/index.html" in result.message


def test_webui_valid_multi_file_pass(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    index = write_webui(root, MULTI_FILE_HTML)
    write_webui_asset(root, "assets/index-abc123.js")
    write_webui_asset(root, "assets/index-abc123.css")
    result = prc.check_webui(root)
    assert result.status == PASS
    assert "多文件" in result.message
    assert str(index.stat().st_size) in result.message  # 体积信息可见


def test_webui_inline_only_shell_fail(tmp_path: Path) -> None:
    """纯内联占位（零本地资产引用）＝多文件产物不该有的形态 ⇒ FAIL."""
    root = make_project(tmp_path)
    write_webui(root, SINGLE_FILE_HTML)
    result = prc.check_webui(root)
    assert result.status == FAIL
    assert "内联" in result.message


def test_webui_empty_file_fail(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    write_webui(root, "")
    result = prc.check_webui(root)
    assert result.status == FAIL
    assert "空" in result.message


def test_webui_oversize_fail(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    write_webui(root, b"x" * (prc.WEBUI_MAX_BYTES + 1))
    result = prc.check_webui(root)
    assert result.status == FAIL
    assert "10MB" in result.fix_hint or "10 MB" in result.fix_hint or "10MB" in result.message


@pytest.mark.parametrize(
    "fragment",
    [
        '<script src="https://cdn.example.com/app.js"></script>',
        "<script src='/assets/index-abc123.js'></script>",
        '<link rel="stylesheet" href="https://fonts.example.com/css">',
        "<link rel='stylesheet' href='/assets/index.css'>",
    ],
)
def test_webui_external_ref_fail(tmp_path: Path, fragment: str) -> None:
    root = make_project(tmp_path)
    write_webui(root, "<html><head>" + fragment + "</head><body>hi</body></html>")
    result = prc.check_webui(root)
    assert result.status == FAIL
    assert "外链" in result.message


def test_webui_relative_local_asset_is_ok(tmp_path: Path) -> None:
    """相对路径（./assets/）不是外链；解析到实存非空资产 ⇒ PASS（旧「不误伤」语义保留）."""
    root = make_project(tmp_path)
    write_webui(root, '<html><head><script src="./assets/x.js"></script></head><body></body></html>')
    write_webui_asset(root, "assets/x.js")
    assert prc.check_webui(root).status == PASS


def test_webui_non_stylesheet_link_ignored(tmp_path: Path) -> None:
    """icon/prefetch/普通 preload 等非 stylesheet/modulepreload 的 <link> 不进判定.

    本用例另配一枚合法本地引用以满足「非纯内联」新规；反向腿证明那枚网络 preload
    本身不被当外链（只带它时红的原因是「零本地资产引用」，不是它）。
    """
    root = make_project(tmp_path)
    write_webui(
        root,
        '<html><head><link rel="preload" href="https://x/y">'
        '<script src="/ui/assets/app-abc123.js"></script></head><body></body></html>',
    )
    write_webui_asset(root, "assets/app-abc123.js")
    assert prc.check_webui(root).status == PASS

    # 反向腿：只带这枚被忽略的 link ⇒ 红只能是「零本地资产引用」，不得报外链。
    write_webui(root, '<html><head><link rel="preload" href="https://x/y"></head><body></body></html>')
    only = prc.check_webui(root)
    assert only.status == FAIL
    assert "外链" not in only.message


def test_webui_local_asset_missing_fails(tmp_path: Path) -> None:
    """index 引用的本地资产必须在 webui/dist/assets 内实存 ⇒ 缺件 FAIL（不许假绿）."""
    root = make_project(tmp_path)
    write_webui(root, '<html><head><script src="/ui/assets/index-abc123.js"></script></head><body></body></html>')
    result = prc.check_webui(root)
    assert result.status == FAIL
    assert "缺件" in result.message


def test_webui_local_asset_empty_fails(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    write_webui(root, '<html><head><script src="/ui/assets/index-abc123.js"></script></head><body></body></html>')
    write_webui_asset(root, "assets/index-abc123.js", b"")
    result = prc.check_webui(root)
    assert result.status == FAIL
    assert "空" in result.message


@pytest.mark.parametrize(
    ("fragment", "token"),
    [
        ('<script src="/ui/assets/%2e%2e%2fsecret.js"></script>', "穿越"),
        ('<script src="../secret.js"></script>', "穿越"),
        ('<script src="//evil.example.com/app.js"></script>', "外链"),
        ('<link rel="stylesheet" href="file:///etc/passwd">', "外链"),
        ('<script src="javascript:alert(1)"></script>', "外链"),
    ],
)
def test_webui_traversal_host_and_protocol_refs_fail(
    tmp_path: Path, fragment: str, token: str
) -> None:
    """编码穿越 / 上跳相对路径 / 协议相对 host / 非 http(s) 协议一律拒绝."""
    root = make_project(tmp_path)
    write_webui(root, "<html><head>" + fragment + "</head><body></body></html>")
    result = prc.check_webui(root)
    assert result.status == FAIL
    assert token in result.message


def test_webui_local_ref_with_query_and_fragment_is_ok(tmp_path: Path) -> None:
    """带 query/fragment 的本地引用只取 path 解析（合法形态，不该被当缺件）."""
    root = make_project(tmp_path)
    write_webui(
        root,
        "<html><head>"
        '<link rel="stylesheet" href="/ui/assets/index-abc123.css?v=1">'
        "</head><body>"
        '<script type="module" src="/ui/assets/index-abc123.js?v=1#frag"></script>'
        "</body></html>",
    )
    write_webui_asset(root, "assets/index-abc123.js")
    write_webui_asset(root, "assets/index-abc123.css")
    assert prc.check_webui(root).status == PASS


@pytest.mark.parametrize("case", ["outside", "equal"])
def test_webui_asset_root_escaping_dist_is_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """资产根必须是产物根的**严格子目录**：外部目录顶替（outside）与 `assets→dist`
    本身（equal，等于把产物根散件一起纳入服务面）都 ⇒ FAIL.

    本机不保证能建 symlink/junction，故用**限定 Path.resolve 替身**（只对
    `webui/dist/assets` 这一枚改解析结果，其余走真身），不 skip、不伪造 git。
    两腿都让「文件实存」成立 ⇒ 红只能出在根越界这一问上。
    """
    root = make_project(tmp_path)
    write_webui(root, '<html><head><script src="/ui/assets/x.js"></script></head><body></body></html>')
    write_webui_asset(root, "assets/x.js")
    dist_assets = root / "webui" / "dist" / "assets"
    if case == "outside":
        target_root = tmp_path / "outside_assets"
        target_root.mkdir(parents=True, exist_ok=True)
        (target_root / "x.js").write_bytes(b"/*real but outside*/")
    else:
        target_root = root / "webui" / "dist"
    real_resolve = Path.resolve

    def fake_resolve(self: Path, *args: object, **kwargs: object) -> Path:
        if self == dist_assets:
            return real_resolve(target_root)
        return real_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    result = prc.check_webui(root)
    assert result.status == FAIL
    assert "产物根" in result.message


def test_webui_modulepreload_local_asset_validated(tmp_path: Path) -> None:
    """modulepreload 是本地资产引用：按实际构建读取，缺件 FAIL、实存非空 PASS."""
    root = make_project(tmp_path)
    html = (
        '<html><head><link rel="modulepreload" '
        'href="/ui/assets/vendor-abc123.js"></head><body></body></html>'
    )
    write_webui(root, html)
    assert prc.check_webui(root).status == FAIL  # 缺件
    write_webui_asset(root, "assets/vendor-abc123.js")
    assert prc.check_webui(root).status == PASS

    # 多 token 的合法 rel（keyword 不在首段）不得被吞：rel 按 token 判。
    write_webui(
        root,
        '<html><head><link rel="preload modulepreload" '
        'href="/ui/assets/late-abc123.js"></head><body></body></html>',
    )
    assert prc.check_webui(root).status == FAIL  # 缺件（说明这一枚确实进了判定面）
    write_webui_asset(root, "assets/late-abc123.js")
    assert prc.check_webui(root).status == PASS


# ---------------------------------------------------------------------------
# 9. control_plane：控制面配置三键（只报已配置/缺失，哈希值绝不回显）
# ---------------------------------------------------------------------------

def _env_append(root: Path, *lines: str) -> None:
    env_path = root / ".env"
    env_path.write_text(env_path.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8")


def test_control_plane_all_missing_skip_with_enable_hint(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    result = prc.check_control_plane(prc.load_env(root))
    assert result.status == SKIP
    for key in (
        "BOT_CONTROL_PLANE_ENABLED",
        "BOT_CONTROL_PLANE_TOKEN_SHA256",
        "BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256",
    ):
        assert key in result.fix_hint
    assert "重启" in result.fix_hint  # 启用指引含重启提醒


def test_control_plane_all_set_pass_and_never_echo_hash(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    token = "deadbeef" * 8
    _env_append(
        root,
        "BOT_CONTROL_PLANE_ENABLED=true",
        f"BOT_CONTROL_PLANE_TOKEN_SHA256={token}",
        "BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256=cafebabe",
    )
    result = prc.check_control_plane(prc.load_env(root))
    assert result.status == PASS
    assert result.message.count("已配置") == 3
    assert token not in result.message  # 哈希键只查非空，绝不回显值
    assert "cafebabe" not in result.message
    assert "缺失" not in result.message


def test_control_plane_partial_pass_with_missing_hint(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    _env_append(root, "BOT_CONTROL_PLANE_TOKEN_SHA256=abc123")
    result = prc.check_control_plane(prc.load_env(root))
    assert result.status == PASS
    assert "BOT_CONTROL_PLANE_TOKEN_SHA256" in result.message
    assert "已配置" in result.message
    assert "BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256" in result.message
    assert "BOT_CONTROL_PLANE_ENABLED" in result.message
    assert "缺失" in result.message and "部分缺失 x2" in result.message  # 逐键点名缺失项


def test_control_plane_enabled_false_value_visible_and_noted(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    _env_append(root, "BOT_CONTROL_PLANE_ENABLED=false")
    result = prc.check_control_plane(prc.load_env(root))
    assert result.status == PASS  # 非空=已配置（false 非缺失）
    assert "false" in result.message  # 开关键值非敏感，可见
    assert "关闭" in result.message  # 但要提示控制面处于关闭状态


# ---------------------------------------------------------------------------
# 汇总（项数以 prc.declared_item_ids() 派生）：run_all 顺序、缺资产/缺配置=SKIP
# 不致 fail（向后兼容）
# （函数名留 eleven 系历史命名，账实以真身声明侧派生为准、不再手抄 id 清单——
#  S146 把本处的 13 枚字面量清单换成派生式；改名会变更节点 id，非必需不动，
#  残留命名债记 SEAT-S206 §4。）
# ---------------------------------------------------------------------------

def test_run_all_eleven_checks_and_new_items_skip_keeps_exit_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = make_project(tmp_path)  # 无 webui/dist、无控制面三键、无 TTS 配置、无注册表、无 MCP_SERVERS
    all_subproc_ok(monkeypatch)
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    results = prc.run_all(root)
    ids = [r.id for r in results]
    assert ids == prc.declared_item_ids()
    assert next(r for r in results if r.id == "webui").status == SKIP
    assert next(r for r in results if r.id == "control_plane").status == SKIP
    assert next(r for r in results if r.id == "tts_voice").status == SKIP
    assert next(r for r in results if r.id == "channel_tags").status == SKIP
    assert next(r for r in results if r.id == "mcp_server_spec").status == SKIP
    # ann_pair：假环境没有 wiki 库 ⇒ NOT_APPLICABLE → SKIP（没建过库不算红）
    assert next(r for r in results if r.id == "ann_pair").status == SKIP
    # 在册各项行为不变：SKIP 不致 fail，exit 仍为 0
    assert prc.main(["--json", "--project-root", str(root)]) == 0


# ---------------------------------------------------------------------------
# 16/17. structure_readiness + library_roster（工单 W-1：结构体检与分库就绪进中央出口）
#
# 这两把新格是**转贴型**的格子：判据住在别处的尺与名册里，本文件只准搬运、不准自算。
# 于是本节的锁全围绕「它有没有偷偷长出判据」：
#   ① 在册且默认跑（假根上必 SKIP 且 exit 0——与既有新格同形，SKIP 放行不等于绿）；
#   ② 零写面锁（argv 表摊平 + 源码 AST 双路，另带注毒腿自证不空转）；
#   ③ 量纲锁（新格函数体内不得出现 len() 参与比较、不得两处 len() 相加减＝聚合器不许自己判绿）；
#   ④ 失明锁（仓外盘面读不到＝SKIP + 字面量 UNTRACKED_GATE，绝不产 PASS/绝不产 FAIL）
#      ＋三形判据各钉一枚（差集为空型，判据全在名册与盘面的形状里，不写枚数）。
# 全离线：不碰真仓外目录（一律 tmp_path 造），真尺只在被测根上有文件时才会被调，
# 本节的假根都没有那些文件 ⇒ 零子进程、零写盘。
# ---------------------------------------------------------------------------

#: 🔴 写盘/外呼开关黑名单：聚合器一面都不准开（这些 token 连本子串都不许出现在 argv 形状里）。
FORBIDDEN_ARGV_TOKENS = (
    "--write",
    "--adopt",
    "--apply",
    "--execute",
    "--poison",
    "--baseline-json",
    "--four-accounts-out",
    "--dump",
)
#: 本格新落的函数名——量纲锁与零写面 AST 腿的作用域（改名必失配，故下方先自证它们都在册）。
W1_FUNCTIONS = (
    "check_structure_readiness",
    "_run_structure_face",
    "_structure_fold",
    "_enforcement_flag_declared",
    "_ruler_names",
    "check_library_roster",
    "_release_roster_axes",
    "_manifest_disk_slugs",
)
PRC_FILE = PROJECT_ROOT / "scripts" / "pre_restart_check.py"
_FACES_ANCHOR = "STRUCTURE_FACES: tuple[StructureFace, ...] = (\n"
#: 注毒面：argv 里塞进写盘开关与裸路径（只活在内存里的源码字符串上，真文件零接触）。
_POISON_FACE = (
    "    StructureFace(\n"
    '        "注毒面",\n'
    '        "scripts/physical_placement_census.py",\n'
    '        ("--four-accounts", "--four-accounts-out", "out/four.json"),\n'
    '        "--fail-on-violations",\n'
    "        ((0, STRUCTURE_LABEL_PASS),),\n"
    "    ),\n"
)


def _w1_function_nodes(tree: ast.Module, *, require_roster: bool = True) -> list[ast.FunctionDef]:
    """本格新落的那些函数节点（一个都没找到＝锁空转，故缺名时当场红）."""
    found = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in W1_FUNCTIONS
    ]
    if require_roster:
        missing = sorted(set(W1_FUNCTIONS) - {node.name for node in found})
        assert not missing, f"W1 函数名册与真身失配（改名要同批改本锁）：缺 {missing}"
    return found


def _argv_shape_literals(source: str) -> list[str]:
    """摊平「会进 subprocess 的字面量」三处：STRUCTURE_FACES 赋值、run_cmd 调用、本格函数体.

    STRUCTURE_FACES 是**带注解的赋值**（AnnAssign）——只认 ast.Assign 会整块扫不到，
    注毒腿当场变空腿（本波实撞过一次，两条腿都得先自证抓得到东西才算有牙）。
    """
    tree = ast.parse(source)
    subtree_nodes: list[ast.AST] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "STRUCTURE_FACES" for target in node.targets
        )) or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "STRUCTURE_FACES"
        ):
            subtree_nodes.append(node)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "run_cmd":
            subtree_nodes.append(node)
    subtree_nodes.extend(_w1_function_nodes(tree))
    literals: list[str] = []
    for root_node in subtree_nodes:
        for item in ast.walk(root_node):
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                literals.append(item.value)
    return literals


def test_w1_items_are_declared_and_skip_on_unconfigured_fake_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """① 两枚新 id 进声明侧、默认跑；无配置假根上必 SKIP 且 exit 0（SKIP 放行＝同既有新格形）."""
    declared = prc.declared_item_ids()
    assert "structure_readiness" in declared and "library_roster" in declared, declared
    root = make_project(tmp_path)
    all_subproc_ok(monkeypatch)
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)
    results = prc.run_all(root)
    ids = [r.id for r in results]
    assert ids == declared, "注册面与声明侧漂移"
    assert ids[-3:] == ["entry_chain", "structure_readiness", "library_roster"], ids
    structure = next(r for r in results if r.id == "structure_readiness")
    roster = next(r for r in results if r.id == "library_roster")
    assert structure.status == SKIP, f"假根上没有尺，本格只许 SKIP（没有证据）：{structure.message}"
    assert roster.status == SKIP and "UNTRACKED_GATE" in roster.message, roster.message
    assert prc.main(["--json", "--project-root", str(root)]) == 0, "两枚新格的 SKIP 不许把 exit 码顶成 1"
    # 无尺那一格已按裁定 4 甲换成真尺（`scripts/root_hygiene_census.py`）：不许退回空面，
    # 也不许私自改它的 rc 语义（0＝根层干净 PASS／1＝债未清 FAIL）。
    hygiene = next(f for f in prc.STRUCTURE_FACES if f.key == "仓根卫生")
    assert hygiene.script_rel == "scripts/root_hygiene_census.py", hygiene
    assert hygiene.enforce_flag == "--check" and "--json" in hygiene.argv, hygiene.argv
    assert tuple(hygiene.rc_verdicts) == (
        (0, prc.STRUCTURE_LABEL_PASS),
        (1, prc.STRUCTURE_LABEL_FAIL),
    ), hygiene.rc_verdicts
    label, line, _details = prc._run_structure_face(hygiene, root)
    assert label == prc.STRUCTURE_LABEL_UNDECIDABLE and "RULER_ABSENT" in line, (
        f"假根上没有那把尺＝没有证据，既不产 PASS 也不产 FAIL：{line}"
    )


# 「每次 push 都要更新」＝主人常令，执法面＝分库远端同步（尺真身 scripts/sync_all_repositories.py）。
# 为什么不靠上面那几枚通用循环罩住：通用循环只判「argv 干净」「执法口在尺的 argparse 名册里」，
# 判不到**注册本身**——把 StructureFace 整块删掉，循环照样绿（它就是从那张表里取的）。
# 名册/实体在盘 ≠ 远端已更新：`library_roster` 那格判前者，这一面判后者，两格不许互替。
_SYNC_RULER_SOURCE = "scripts/sync_all_repositories.py"


def _sync_stub_script(root: Path) -> None:
    """假根上放一把**只声明执法口**的尺：AST 读 add_argument 要过得去，判定全交给替身子进程."""
    script = root / _SYNC_RULER_SOURCE
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--json')\n"
        "p.add_argument('--check')\n",
        encoding="utf-8",
    )


def test_sync_face_is_registered_and_maps_its_own_three_rc_book(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """注册锁 + rc 三态各归各位：0=PASS／1=FAIL／2=UNDECIDABLE，名册外退出码禁折成绿."""
    sync = next((face for face in prc.STRUCTURE_FACES if face.key == "分库远端同步"), None)
    assert sync is not None, "「分库远端同步」这面被删＝常令「每次 push 都要更新」失去执法口"
    assert sync.script_rel == _SYNC_RULER_SOURCE, sync
    assert sync.enforce_flag == "--check" and "--json" in sync.argv, sync.argv
    assert tuple(sync.rc_verdicts) == (
        (0, prc.STRUCTURE_LABEL_PASS),
        (1, prc.STRUCTURE_LABEL_FAIL),
        (2, prc.STRUCTURE_LABEL_UNDECIDABLE),
    ), sync.rc_verdicts
    assert sync.json_fields == ("counts", "reds"), sync.json_fields

    # 转贴型格子的病＝贴了 rc 却没读尺自己交回的字段；这里反查尺**真 emit** 这两个键。
    source = (PROJECT_ROOT / _SYNC_RULER_SOURCE).read_text(encoding="utf-8")
    for field in sync.json_fields:
        assert f'"{field}"' in source, f"尺的 --json 里找不到 {field}＝这面转的是不存在的读数"

    root = make_project(tmp_path)
    _sync_stub_script(root)
    payload = json.dumps({"counts": {"libs": 15, "reds": 0}, "reds": []}, ensure_ascii=False)

    def _stub(rc: int, out: str = payload):
        def _run(args: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str, str]:
            return rc, out, ""
        return _run

    for rc, want in (
        (0, prc.STRUCTURE_LABEL_PASS),
        (1, prc.STRUCTURE_LABEL_FAIL),
        (2, prc.STRUCTURE_LABEL_UNDECIDABLE),
    ):
        monkeypatch.setattr(prc, "run_cmd", _stub(rc))
        label, line, details = prc._run_structure_face(sync, root)
        assert label == want, f"rc={rc} 该转贴成 {want}，实得 {label}：{line}"
        assert details["ruler_rc"] == rc and "counts" in details.get("ruler_fields", {}), details

    # 名册外的退出码（尺坏了）＝不可判，既不折绿也不折红
    monkeypatch.setattr(prc, "run_cmd", _stub(3))
    label, line, _d = prc._run_structure_face(sync, root)
    assert label == prc.STRUCTURE_LABEL_UNDECIDABLE and "RULER_EXIT_UNMAPPED" in line, line

    # rc=1 却交不回结构化读数＝门瞎，不许把 rc 当证据洗成 FAIL 更不许当绿
    monkeypatch.setattr(prc, "run_cmd", _stub(1, out="库全都同步好了（散文，无 JSON）"))
    label, line, _d = prc._run_structure_face(sync, root)
    assert label == prc.STRUCTURE_LABEL_UNDECIDABLE and "RULER_READING_UNPARSEABLE" in line, line

    # 尺不在被测根上（HEAD 轴副本／干净 checkout）＝RULER_ABSENT，绝不读成「远端已更新」
    monkeypatch.setattr(prc, "run_cmd", _stub(0))
    bare_parent = tmp_path / "bare"
    bare_parent.mkdir()
    label, line, _d = prc._run_structure_face(sync, make_project(bare_parent))
    assert label == prc.STRUCTURE_LABEL_UNDECIDABLE and "RULER_ABSENT" in line, line


# ---------------------------------------------------------------------------
# 尺**自己**的判据面（不是转贴面）：ahead/dirty 两枚都判不了「库的内容是不是旧的」——
# 一座库把自己的旧内容提交得干干净净，ahead=0／dirty=0 照样全绿，而主仓早已前进。
# 所以 `_content_drift` 是这条常令的另一半，它必须有腿；否则又是一枚"只落字段没落判据"的半死件。
# ---------------------------------------------------------------------------

_REL = "plugins/bot_unified_runtime/domains/core/session_keys.py"


def _drift_fixture(tmp_path: Path, *, mode: str) -> tuple[dict[str, str], Path]:
    """造「主仓 HEAD 那棵树 ＋ 一座库的副本」两方，返回 (HEAD blob 名册, 库目录)。

    🔴 轴是 **HEAD**，不是工作树：库实体是工厂按名册从主仓取的派生物，拿未提交的在飞改动
    当基准＝把"别人正在写这枚文件"读成"这座库是旧的"（本席 2026-10-11 首跑就误点名过一枚
    `news_feeds.py`，实为别席半件）。所以名册在这里**直接构造**，不读盘上的工作树。
    """
    from scripts import sync_all_repositories as sync

    libs_root = tmp_path / "ChatBot_Libs"
    lib = libs_root / "ingress-protocol"
    copy = lib / _REL
    copy.parent.mkdir(parents=True, exist_ok=True)
    if mode == "shell":
        shell_lib = libs_root / "adapter-telegram"
        (shell_lib / "plugins").mkdir(parents=True, exist_ok=True)
        return {"plugins/anything.py": "0" * 40}, shell_lib
    content = {"same": b"VALUE-NOW\n", "differ": b"VALUE-OLD\n", "orphan": b"ONLY-IN-LIB\n"}[mode]
    copy.write_bytes(content)
    if mode in ("same", "differ"):
        return {_REL: sync._git_blob_sha(b"VALUE-NOW\n")}, lib
    return {"plugins/bot_unified_runtime/other.py": "0" * 40}, lib  # orphan：HEAD 里根本没这枚路径


@pytest.mark.parametrize("mode", ["same", "differ", "orphan", "shell"])
def test_content_drift_leg_sees_stale_library(tmp_path: Path, mode: str) -> None:
    """实体新旧轴四形：同＝不判；改＝点名；HEAD 已无＝点名；壳库＝只登记证据缺席（禁判红）。"""
    from scripts import sync_all_repositories as sync

    head_blobs, lib = _drift_fixture(tmp_path, mode=mode)
    reading = sync._content_drift(lib, head_blobs)
    assert reading["axis"] == "HEAD" and "blind" not in reading, reading
    if mode == "same":
        assert reading["mirrored"] == 1 and reading["differing_count"] == 0 == reading["absent_count"], reading
    elif mode == "differ":
        assert reading["differing_count"] == 1 and reading["differing"] == [_REL], reading
        assert reading["absent_count"] == 0, reading
    elif mode == "orphan":
        assert reading["absent_count"] == 1 and reading["differing_count"] == 0, reading
    else:
        assert reading["mirrored"] == 0 == reading["differing_count"] == reading["absent_count"], reading


def test_content_drift_axis_is_head_not_worktree(tmp_path: Path) -> None:
    """反"在飞半件被读成旧库"那一形：库副本与 HEAD 一致，而盘上工作树那枚文件正被人改着 ⇒ 不判红。

    这一枚锁的是本席**实犯过**的误报形态（首跑把别席在写的 `news_feeds.py` 报成库旧），
    所以它比的不是"函数返回什么"，而是"取数口读的是哪棵树"。
    """
    from scripts import sync_all_repositories as sync

    lib = tmp_path / "ChatBot_Libs" / "contracts"
    copy = lib / _REL
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(b"AT-HEAD\n")
    head_blobs = sync._head_blobs(tmp_path)
    assert head_blobs is None, "假根按定义不是 git 检出，这里要的就是它读不出"
    blind = sync._content_drift(lib, None)
    assert blind.get("blind") and "differing_count" not in blind, (
        f"读不出 HEAD 树时必须失明、不许默认一致：{blind}")
    matched = sync._content_drift(lib, {_REL: sync._git_blob_sha(b"AT-HEAD\n")})
    assert matched["differing_count"] == 0 == matched["absent_count"], matched
    dirty_elsewhere = sync._git_blob_sha(b"WORKTREE-WIP-BY-ANOTHER-SEAT\n")
    assert dirty_elsewhere != sync._git_blob_sha(b"AT-HEAD\n"), "blob 哈希自身坏了（两向同值＝尺无牙）"


def test_content_drift_leg_ignores_line_ending_shape(tmp_path: Path) -> None:
    """同一份内容、库副本是 CRLF 而 HEAD blob 是 LF ⇒ **不许**判成旧库（本席首跑整面误报的实犯形）。

    机理：主仓工作树里根 `__init__.py` 这类文件带 12006 枚 `\\r`，而 HEAD 的 blob 由
    `.gitattributes` 归一成 LF ⇒ 逐字节比会点名**每一座**库。本锁钉的是"比的是内容、不是换行形态"。
    """
    from scripts import sync_all_repositories as sync

    rel = "plugins/bot_unified_runtime/__init__.py"
    lf = b"line-one\nline-two\n"
    lib = tmp_path / "lib"
    copy = lib / rel
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(lf.replace(b"\n", b"\r\n"))
    reading = sync._content_drift(lib, {rel: sync._git_blob_sha(lf)})
    assert reading["differing_count"] == 0 == reading["absent_count"], (
        f"换行符差异被判成库旧＝本面在 Windows 上恒红：{reading}")
    copy.write_bytes(b"line-one\r\nline-two\r\n# real content change\r\n")
    moved = sync._content_drift(lib, {rel: sync._git_blob_sha(lf)})
    assert moved["differing_count"] == 1, "真改了内容也不报＝上一条成了假锁"
    assert sync._git_blob_sha(lf) == sync._git_blob_sha(lf.replace(b"\n", b"\r\n")), (
        "折形没生效：同一份内容两种换行给出不同 sha＝本面在 Windows 上会点名每一座库（首跑的实犯形态）")
    assert sync._git_blob_sha(lf) != sync._git_blob_sha(lf + b"x"), (
        "内容变了 sha 都不变＝这把哈希是常数，整面读数无意义")


def test_content_drift_leg_has_teeth_on_the_real_root(tmp_path: Path) -> None:
    """反"永远绿"腿：拿**真主仓**当比对源，把一枚副本改一个字节 ⇒ 必须点名（现算，不靠假根自证自）。

    为什么还要这一条：上一条全在 tmp_path 里自造对照，判不到"真树的 `plugins/**` 形状是不是
    都被这函数看见"（rglob 漏一层目录时，四形夹具照样全绿＝空腿）。这里用真仓根当源，
    只读不写主仓，写盘只落 tmp。
    """
    import subprocess  # 局部 import：本件顶部 import 面不许动（只追加用例的写面纪律）

    from scripts import sync_all_repositories as sync

    rel = "plugins/bot_unified_runtime/domains/core/session_keys.py"
    head_blobs = sync._head_blobs(PROJECT_ROOT)
    assert head_blobs and rel in head_blobs, (
        f"取数口读不出真仓 HEAD 那棵树（对榫源变了要同批改本锁）：{rel}")
    head_bytes = subprocess.run(
        ["git", "-c", "core.quotePath=false", "show", f"HEAD:{rel}"],
        cwd=str(PROJECT_ROOT), capture_output=True, check=True).stdout
    assert sync._git_blob_sha(head_bytes) == head_blobs[rel], "blob 哈希与 ls-tree 那列不同形＝尺的轴坏了"

    lib = tmp_path / "lib"
    copy = lib / rel
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(head_bytes)
    clean = sync._content_drift(lib, head_blobs)
    assert clean["differing_count"] == 0 == clean["absent_count"] and clean["mirrored"] == 1, clean
    copy.write_bytes(head_bytes + b"# drift\n")
    poisoned = sync._content_drift(lib, head_blobs)
    assert poisoned["differing_count"] == 1, f"改一个字节都没抓到＝这把腿是空腿：{poisoned}"
    assert sync.SNAPSHOT_SOURCE_ROOT in poisoned["differing"][0], poisoned["differing"]


def test_structure_faces_argv_are_read_only_and_the_lock_has_teeth(monkeypatch: pytest.MonkeyPatch) -> None:
    """② 零写面锁：argv 表摊平 + 源码 AST 双路；注毒腿（纯内存）自证上一条真的在拦事."""
    # 腿 A：运行时把在册面表摊平——禁串连子串都不许出现，且不许出现裸路径
    for face in prc.STRUCTURE_FACES:
        joined = " ".join(face.argv)
        for token in FORBIDDEN_ARGV_TOKENS:
            assert token not in joined, f"{face.key} 的 argv 里出现了写盘/外呼开关 {token}：{face.argv}"
        for token in face.argv:
            assert not any(sep in token for sep in ("/", "\\", ":")), f"{face.key} 的 argv 里有裸路径 {token}"
        if "--json" in face.argv:
            at = face.argv.index("--json")
            after = face.argv[at + 1 :]
            assert all(item.startswith("-") for item in after), (
                f"{face.key} 的 --json 后面跟了取值（{after}）＝带路径的 --json 是写盘口"
            )
    # 腿 B：源码层——STRUCTURE_FACES 赋值 / run_cmd 调用 / 本格函数体里都不许藏着禁串
    source = PRC_FILE.read_text(encoding="utf-8")
    literals = _argv_shape_literals(source)
    assert literals, "AST 腿一个面级字面量都没摊到＝本锁已在空转（函数改名或表形变了）"
    hits = [f"{token} <- {text}" for text in literals for token in FORBIDDEN_ARGV_TOKENS if token in text]
    assert not hits, "聚合器里有写盘/外呼开关进 argv 形状的字面量：" + " | ".join(hits[:5])

    # 注毒腿：内存里加一枚带 --four-accounts-out 的毒面 ⇒ 腿 B 必红（真文件零接触）
    assert source.count(_FACES_ANCHOR) == 1, "注毒锚点失配：STRUCTURE_FACES 的声明形状变了"
    poisoned = source.replace(_FACES_ANCHOR, _FACES_ANCHOR + _POISON_FACE, 1)
    ast.parse(poisoned)  # 毒必须是合法源码，否则红在语法上说明不了本锁抓到了越权
    poisoned_hits = [
        f"{token} <- {text}"
        for text in _argv_shape_literals(poisoned)
        for token in FORBIDDEN_ARGV_TOKENS
        if token in text
    ]
    assert "--four-accounts-out" in " ".join(poisoned_hits), (
        f"注毒没让零写面锁变红＝这把锁是空腿：{poisoned_hits[:5]}"
    )
    before = PRC_FILE.read_bytes()
    monkeypatch.setattr(prc, "run_cmd", _honest_run)
    assert PRC_FILE.read_bytes() == before, "真身在零写面锁的过程中被改动——立即停手排查"


def test_w1_aggregator_does_not_grow_its_own_denominator() -> None:
    """③ 量纲锁：本格函数体内不许出现 len() 参与比较、也不许两处 len() 相加减.

    为什么钉这一条：转贴型格子的病就是「转着转着自己算了一个数、然后按那个数判绿」。
    判据一旦落到聚合器自己的数值比较上，尺改了上限、改了口径，这里全都不知道——
    本格只准说「尺自己判了什么」，不准替尺算。
    """
    source = PRC_FILE.read_text(encoding="utf-8")

    def _len_calls(node: ast.AST) -> list[ast.Call]:
        return [
            item
            for item in ast.walk(node)
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "len"
        ]

    hits: list[str] = []
    for func in _w1_function_nodes(ast.parse(source)):
        for node in ast.walk(func):
            if isinstance(node, ast.Compare) and _len_calls(node):
                hits.append(f"{func.name}：len() 参与比较（替尺算了数）")
            if isinstance(node, ast.BinOp) and _len_calls(node.left) and _len_calls(node.right):
                hits.append(f"{func.name}：两处 len() 相加减（聚合器自己造了判据）")
    assert not hits, "；".join(sorted(set(hits)))

    # 自证不空转：同一把尺量一枚合成的「越权函数」必须报红
    poison = "def check_structure_readiness(env, project_root):\n    return len(env) > len(str(project_root))\n"
    assert _len_calls(ast.parse(poison)), "len 探针本身失效（连明显的都看不见）"
    poisoned_hits: list[str] = []
    for func in _w1_function_nodes(ast.parse(poison), require_roster=False):
        for node in ast.walk(func):
            if isinstance(node, ast.Compare) and _len_calls(node):
                poisoned_hits.append("len 参与比较")
            if isinstance(node, ast.BinOp) and _len_calls(node.left) and _len_calls(node.right):
                poisoned_hits.append("两处 len 相加减")
    assert poisoned_hits, "注毒没让量纲锁变红＝空腿"


def test_library_roster_is_blind_not_green_when_disk_is_unreadable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """④ 失明锁：仓外盘面不在／读不出／抓不到成员行 ⇒ SKIP + UNTRACKED_GATE，绝不产 PASS/FAIL.

    HEAD 轴副本按定义没有 ``<仓根>/../ChatBot_Libs``——那是「没有证据」，不是「有人没干活」。
    聚合器只有 PASS/FAIL/SKIP 三态，所以这里必须是 SKIP（不许往测试件塞 xfail 机制）。
    """
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    all_subproc_ok(monkeypatch)
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)

    res = prc.check_library_roster({}, root)
    assert res.status == SKIP, f"盘面缺席却产了 {res.status}：{res.message}"
    assert "UNTRACKED_GATE" in res.message, res.message
    assert "PASS" not in res.message, f"失明态里不许出现 PASS：{res.message}"
    assert prc.main(["--only", "library_roster", "--json", "--project-root", str(root)]) == 0

    # 盘面在、但一行成员都抓不到（表形变了/确实空盘）＝同样失明
    manifest = root.parent / prc.LIBS_ROOT_DIRNAME / "MANIFEST.md"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("# 发行库盘面\n\n| 板块/名册 | slug | 成员 |\n|---|---|---|\n", encoding="utf-8")
    empty_rows = prc.check_library_roster({}, root)
    assert empty_rows.status == SKIP and "UNTRACKED_GATE" in empty_rows.message, empty_rows.message
    assert "PASS" not in empty_rows.message, empty_rows.message


def _roster_root(tmp_path: Path, *, pollute_axis: bool = False) -> Path:
    """把真声明源**复制**进假根（只读真身、零写入源码树），可选把手抄污染打进发行库轴."""
    text = (PROJECT_ROOT / prc.LIBRARY_TAXONOMY_REL).read_text(encoding="utf-8")
    if pollute_axis:
        # 注毒：发行库里 L0 的 slug 改成板块库那一枚 ⇒ 两轴交集非空（派生轴被手抄污染）
        assert "slug='contracts'" in text, "注毒锚点失配：名册真身形状变了"
        text = text.replace("slug='contracts'", "slug='ingress-protocol'", 1)
    root = tmp_path / "proj"
    target = root / prc.LIBRARY_TAXONOMY_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return root


def _write_manifest(root: Path, slugs: list[str], header: str = "| 库 | kebab | 成员 |") -> Path:
    """造盘面成员表（表头字样**故意与真身不同**：本格抓行只认第二列的形状）."""
    manifest = root.parent / prc.LIBS_ROOT_DIRNAME / "MANIFEST.md"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    lines = [header, "|---|---|---|"]
    for index, slug in enumerate(slugs):
        lines.append(f"| X{index:02d} | `{slug}` | 0 |")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


@pytest.mark.parametrize("case", ["pass", "ghost", "unbuilt", "polluted"])
def test_library_roster_verdicts(tmp_path: Path, case: str) -> None:
    """三形判据各钉一枚 + 表头独立性（盘面夹具的表头字样**故意与真身不同**）.

    真身那张表的表头改过名，靠表头取列的消费者当场瞎过——本锁的夹具表头写成
    ``随便叫什么 / name / n``，判据仍要成立，这才叫「只认第二列的形状」。
    """
    board, library, note = prc._release_roster_axes(PROJECT_ROOT / prc.LIBRARY_TAXONOMY_REL)
    assert note == ""
    assert "ingress-protocol" in set(board.values()), "板块库派生轴读不出——夹具前提塌了"
    assert "contracts" in set(library.values()), "发行库名册轴读不出——夹具前提塌了"
    roster = sorted(set(board.values()) | set(library.values()))
    root = _roster_root(tmp_path, pollute_axis=(case == "polluted"))
    if case == "pass":
        _write_manifest(root, roster, header="| 随便叫什么 | name | n |")
        res = prc.check_library_roster({}, root)
        assert res.status == PASS, res.message
        assert str(root) not in res.message and ":\\" not in res.message, "输出只准出现相对名"
    elif case == "ghost":
        _write_manifest(root, [*roster, "ghost-library"])
        res = prc.check_library_roster({}, root)
        assert res.status == FAIL and "ghost-library" in res.message, res.message
        assert "幽灵" in res.message
    elif case == "unbuilt":
        _write_manifest(root, roster[1:])
        res = prc.check_library_roster({}, root)
        assert res.status == FAIL, res.message
        assert roster[0] in res.message, f"名册有而盘面无必须**逐枚点名**：{res.message}"
        assert "待用户裁" in res.fix_hint, "这一向是未裁的设计选择，fix_hint 必须明写"
    else:
        _write_manifest(root, roster)
        res = prc.check_library_roster({}, root)
        assert res.status == FAIL and "派生轴被手抄污染" in res.message, res.message
        assert "ingress-protocol" in res.message, res.message


def test_structure_faces_are_all_read_only_and_fold_to_skip(tmp_path: Path) -> None:
    """尺缺席时逐面 UNDECIDABLE ⇒ 格级 SKIP；面级标签恰三种，格级绝不产 PASS 也不产 FAIL."""
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    labels: list[str] = []
    lines: list[str] = []
    for face in prc.STRUCTURE_FACES:
        label, line, _details = prc._run_structure_face(face, root)
        labels.append(label)
        lines.append(line)
    assert set(labels) == {prc.STRUCTURE_LABEL_UNDECIDABLE}, lines
    assert prc._structure_fold(labels) == SKIP
    assert prc._structure_fold([prc.STRUCTURE_LABEL_PASS, prc.STRUCTURE_LABEL_UNDECIDABLE]) == SKIP
    assert prc._structure_fold([prc.STRUCTURE_LABEL_PASS, prc.STRUCTURE_LABEL_FAIL]) == FAIL
    assert prc._structure_fold([prc.STRUCTURE_LABEL_PASS]) == PASS
    res = prc.check_structure_readiness({}, root)
    assert res.status == SKIP and res.details["face_labels"] == labels
    for line in lines:
        assert "RULER_ABSENT" in line or "NO_RULER_ON_CALL" in line, line


# ---------------------------------------------------------------------------
# 17 腿C（可导入三档）＋ 附账（成员账）——六发注毒，全部活在 tmp_path
#
# 🔴 真身仓外目录 ``../ChatBot_Libs`` 一字节不碰：夹具的 libs 根永远是 ``tmp_path/ChatBot_Libs``
# （``_roster_root`` 造的假根是 ``tmp_path/proj``，其 parent 正是 tmp_path）。
# 注毒面照真身形状抄：那张表的「独立导入」列是**截断视图**（模块名被切短），全称只活在
# ``FACTORY-REPORT.md`` ⇒ 两本册靠「前缀等值」互相咬住，只改一本当场红。
# 🔴 正例（IMPORTABLE 一座库）今天真机上**一座都没有**：下面 (d) 腿是**合成正例**，
# 只证明判据认绿，不证明现网就绪（现网读数看脚本的实跑输出）。
# ---------------------------------------------------------------------------

#: 注毒用的报错模块末段（改它＝「只改了一本册」的那把刀）。
_POISON_LEAF = "poison_leaf"


def _roster_slugs() -> list[str]:
    """真声明源现读两轴并集（枚数现算、不写死；名册差集为空才照得见另两腿）."""
    board, library, note = prc._release_roster_axes(PROJECT_ROOT / prc.LIBRARY_TAXONOMY_REL)
    assert note == "", f"名册真身读不出，夹具前提塌了：{note}"
    return sorted(set(board.values()) | set(library.values()))


def _import_tail(
    tag: str, module: str, *, keep: int | None = None, segments: int | None = 13
) -> str:
    """可导入段（不含 ``rc=``）；``keep``＝模块名只留前 keep 枚——真身那一列就是这么被截断的.

    裁定①之后 ``IMPORTABLE`` 必须带 `组合N段`（合并证据），缺省就按在册形状给；
    ``segments=None`` 是给注毒腿用的开关（造一枚"自称可导入却没写段数"的行）。
    """
    if tag == "NO-SAMPLE":
        return "NO-SAMPLE（本库无成员模块可测）"
    if tag == "IMPORTABLE":
        if segments is None:
            return "IMPORTABLE / OK"
        return f"IMPORTABLE 组合{segments}段/库侧装载4枚共4枚 / OK"
    tail = f"{tag} / FAIL ModuleNotFoundError:{module}"
    if keep is None or not module:
        return tail
    return tail[: len(tail) - len(module) + keep]


def _source_package_init_bytes() -> bytes:
    """主仓插件根 init 的字节＝桥接件形状腿的基准（夹具须与之逐字节相同才许算「形状对」）."""
    return (PROJECT_ROOT / prc.LIBRARY_SOURCE_PACKAGE_INIT_REL).read_bytes()


def _lib_snapshot(
    libs_root: Path, slug: str, *, members: int, facade: bool, shape: str = "match"
) -> None:
    """造一枚库快照：只建包桥接件与那枚成员账文件（🔴 不建报错点名的模块＝「成员缺」的实况）.

    ``shape``：``match``＝与主仓真身逐字节相同（在册形状）；``facade-line``＝只写一行 extend
    （第二种 init＝遮蔽源，形状腿必红）。默认走 match，摘掉它才见牙。
    """
    lib_dir = libs_root / slug
    (lib_dir / "plugins" / "bot_unified_runtime").mkdir(parents=True, exist_ok=True)
    if facade:
        if shape == "facade-line":
            body = '__path__ = __import__("pkgutil").extend_path(__path__, __name__)\n'
        else:
            # 🔴 按字节写：文本模式在 Windows 会把 `\n` 翻成 `\r\n`，夹具就永远"形状不对"
            # （本机实犯：底例一上来 15 座全红，看着像判据疯了，其实是夹具自己改了行尾）。
            body = None
        target = lib_dir / prc.LIBRARY_PACKAGE_FACADE_REL
        if body is None:
            target.write_bytes(_source_package_init_bytes())
        else:
            target.write_text(body, encoding="utf-8")
    ledger = {
        "@schema": "chatbot.workspace-lib-manifest/1",
        "members": [
            {"path": f"plugins/bot_unified_runtime/m{i}.py", "bytes": 1, "sha256_16": "0"}
            for i in range(members)
        ],
    }
    (lib_dir / prc.LIBRARY_MEMBER_LEDGER_NAME).write_text(
        json.dumps(ledger, ensure_ascii=False), encoding="utf-8"
    )


def _roster_spec(
    roster: list[str], overrides: dict[str, dict[str, object]] | None = None
) -> list[dict[str, object]]:
    """逐枚默认「NO-SAMPLE／零成员」（最干净的底）；谁被点名谁按 override 走."""
    spec: list[dict[str, object]] = []
    for index, slug in enumerate(roster):
        entry: dict[str, object] = {"label": f"X{index:02d}", "slug": slug, "tag": "NO-SAMPLE", "members": 0}
        entry.update((overrides or {}).get(slug, {}))
        spec.append(entry)
    return spec


def _write_roster_books(root: Path, spec: list[dict[str, object]]) -> Path:
    """写那两本册 + 每库快照；表头字样**故意与真身不同**（三腿都只认形状、不认表头）."""
    libs_root = root.parent / prc.LIBS_ROOT_DIRNAME
    libs_root.mkdir(parents=True, exist_ok=True)
    lines = ["| lib | kebab-slug | member-count | ver | gap | importable |", "|---|---|---|---|---|---|"]
    report = ["# 库工厂实体（注毒夹具，全在 tmp_path）"]
    for entry in spec:
        slug = str(entry["slug"])
        tag = str(entry["tag"])
        members = int(str(entry["members"]))
        module = str(
            entry.get("module", f"plugins.bot_unified_runtime.domains.{slug.replace('-', '_')}.{_POISON_LEAF}")
        )
        keep_raw = entry.get("keep")
        keep = None if keep_raw is None else int(str(keep_raw))
        rc = int(str(entry.get("rc", -1 if tag == "NO-SAMPLE" else (0 if tag == "IMPORTABLE" else 1))))
        facade = bool(entry.get("facade", tag in ("HAS-INIT", "IMPORTABLE")))
        segments = entry.get("segments", 13)
        lines.append(
            f"| {entry['label']} | `{slug}` | {members} | 0.0.1 | 0 "
            f"| rc={rc} {_import_tail(tag, module, keep=keep, segments=None if segments is None else int(str(segments)))} |"
        )
        report.append(f"## {entry['label']} `{slug}`")
        report.append(f"- 成员 {members} 枚")
        report.append(f"- 组合可导入性：rc={rc}｜{_import_tail(tag, module, segments=None if segments is None else int(str(segments)))}")
        _lib_snapshot(libs_root, slug, members=members, facade=facade, shape=str(entry.get("shape", "match")))
    (libs_root / "FACTORY-REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    manifest = libs_root / "MANIFEST.md"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def _leg_reds(res: prc.CheckResult) -> tuple[list[str], list[str]]:
    """``(腿C 红, 附账红)``——按 details 的结构读，不从 message 里抠字."""
    import_leg: dict[str, object] = res.details["import_leg"]
    member_leg: dict[str, object] = res.details["member_leg"]
    return list(import_leg["reds"]), list(member_leg["reds"])


def _bare_call_names(func_name: str) -> set[str]:
    """某函数体里出现的裸函数调用名（求和锁：这条腿一旦开始 ``sum()`` 就当场失配）."""
    tree = ast.parse(PRC_FILE.read_text(encoding="utf-8"))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == func_name)
    return {call.func.id for call in ast.walk(fn) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}


def test_import_leg_buckets_missing_init_and_has_init_apart(tmp_path: Path) -> None:
    """注毒①：两枚假库——一枚有包门面、一枚没有 ⇒ HAS-INIT 与 MISSING-INIT **不同桶**、各给各的修法."""
    root = _roster_root(tmp_path)
    roster = _roster_slugs()
    _write_roster_books(
        root,
        _roster_spec(
            roster,
            {
                "contracts": {"tag": "HAS-INIT", "members": 3},
                "ingress-protocol": {"tag": "MISSING-INIT", "members": 5},
            },
        ),
    )
    res = prc.check_library_roster({}, root)
    buckets: dict[str, list[str]] = res.details["import_leg"]["buckets"]
    assert buckets["HAS-INIT"] == ["contracts"], buckets
    assert buckets["MISSING-INIT"] == ["ingress-protocol"], buckets
    assert not set(buckets["HAS-INIT"]) & set(buckets["MISSING-INIT"]), "两档混进同一桶＝分档没牙"
    assert buckets["IMPORTABLE"] == [], "夹具里没有可导入的库，这一档必须空"
    assert _leg_reds(res)[0] == [], f"分档本身不该产红：{_leg_reds(res)[0]}"
    assert res.status == FAIL and res.details["leg_verdicts"]["import"] == FAIL
    assert "NO-SAMPLE 永不进通过" in res.message, res.message
    for bucket in ("MISSING-INIT", "HAS-INIT", "NO-SAMPLE"):
        assert bucket in res.fix_hint, f"{bucket} 的唯一修法没进 fix_hint"
    assert "只补桥接件" in res.fix_hint and "补桥接件无效" in res.fix_hint, res.fix_hint
    assert str(root) not in res.message and ":\\" not in res.message, "输出只准出现相对名"


def test_import_leg_no_sample_over_library_with_members_is_a_lie(tmp_path: Path) -> None:
    """注毒②：把 NO-SAMPLE 贴在「其实有成员」的库上 ⇒ 必产 ``NO_SAMPLE_LIE``（诚实空仓不许免测）."""
    root = _roster_root(tmp_path)
    roster = _roster_slugs()
    _write_roster_books(root, _roster_spec(roster, {"adapter-qq": {"tag": "NO-SAMPLE", "members": 4}}))
    res = prc.check_library_roster({}, root)
    import_reds, _ = _leg_reds(res)
    assert any(red.startswith("NO_SAMPLE_LIE:adapter-qq") for red in import_reds), import_reds
    assert res.status == FAIL and "NO_SAMPLE_LIE" in res.message, res.message
    assert "不许用来免测" in res.fix_hint, res.fix_hint

    # 对照腿：同一枚库改回零成员（诚实空仓）⇒ 同一枚码不许再出现（红来自撒谎，不是来自档名）
    _write_roster_books(root, _roster_spec(roster))
    honest = prc.check_library_roster({}, root)
    honest_reds, _ = _leg_reds(honest)
    assert not any(red.startswith("NO_SAMPLE_LIE") for red in honest_reds), honest_reds
    not_passing = honest.details["import_leg"]["not_passing"]
    assert not_passing["NO-SAMPLE"], "NO-SAMPLE 必须留在未通过那一侧"
    assert "IMPORTABLE" not in not_passing, "通过档永远不许出现在未通过账里"


def test_import_leg_tag_and_disk_readings_swapped_is_drift(tmp_path: Path) -> None:
    """注毒③：标签与两枚独立盘读数对调 ⇒ 必产 ``INIT-TAG-DRIFT``（册说一套、盘面说另一套）."""
    root = _roster_root(tmp_path)
    roster = _roster_slugs()
    _write_roster_books(
        root,
        _roster_spec(
            roster,
            {
                "contracts": {"tag": "HAS-INIT", "members": 3, "facade": False},
                "ingress-protocol": {"tag": "MISSING-INIT", "members": 5, "facade": True},
            },
        ),
    )
    res = prc.check_library_roster({}, root)
    drift = [red for red in _leg_reds(res)[0] if red.startswith("INIT-TAG-DRIFT")]
    assert any("contracts" in red for red in drift) and any("ingress-protocol" in red for red in drift), drift
    assert len(drift) == 2, f"两枚对调各点一枚，不许合成一锅：{drift}"
    assert res.status == FAIL and "迁就标签" in res.fix_hint, res.fix_hint

    # 第二枚盘读数也有牙：门面在场＋报错点名的模块也在场却仍报 FAIL ＝同一枚码的另一条腿
    other_root = tmp_path / "swap2" / "proj"
    other = _roster_root(other_root)
    _write_roster_books(other, _roster_spec(roster, {"media-entertainment": {"tag": "HAS-INIT", "members": 2}}))
    leaf_path = (
        other.parent
        / prc.LIBS_ROOT_DIRNAME
        / "media-entertainment"
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "media_entertainment"
        / f"{_POISON_LEAF}.py"
    )
    leaf_path.parent.mkdir(parents=True, exist_ok=True)
    leaf_path.write_text("# 注毒：报错点名的成员其实已在快照里\n", encoding="utf-8")
    leaf_reds, _ = _leg_reds(prc.check_library_roster({}, other))
    assert any(
        red.startswith("INIT-TAG-DRIFT:media-entertainment") and "都在场" in red for red in leaf_reds
    ), leaf_reds


def test_import_leg_two_books_module_divergence_is_red(tmp_path: Path) -> None:
    """注毒④：只改第二本册的模块名 ⇒ 必产前缀等值红；缺那一节＝分叉红而不是失明.

    🔴 已知的可见范围：MANIFEST 那一列是截断视图，前缀等值只看得见**截断窗口之内**的分叉
    （窗口之外的靠两枚盘读数兜：报错点名的模块在不在该库快照里）。本发注毒把被改那一行留成
    全称视图，另一行留成 30 字符截断视图——同一枚判据下「截断却不红、改名就红」两面都照到。
    """
    root = _roster_root(tmp_path)
    roster = _roster_slugs()
    manifest = _write_roster_books(
        root,
        _roster_spec(
            roster,
            {
                "contracts": {"tag": "MISSING-INIT", "members": 7},
                "ingress-protocol": {"tag": "MISSING-INIT", "members": 4, "keep": 30},
            },
        ),
    )
    report = root.parent / prc.LIBS_ROOT_DIRNAME / "FACTORY-REPORT.md"
    base_reds, _ = _leg_reds(prc.check_library_roster({}, root))
    assert not any(red.startswith("BOOK_PREFIX_DIVERGENCE") for red in base_reds), (
        f"截断视图 ⇄ 全称视图本该互相咬合：{base_reds}"
    )

    text = report.read_text(encoding="utf-8")
    assert text.count(_POISON_LEAF) >= 2, "注毒锚点失配：第二本册里没有那枚模块末段"
    report.write_text(text.replace(_POISON_LEAF, "renamed_leaf", 1), encoding="utf-8")
    diverged = [red for red in _leg_reds(prc.check_library_roster({}, root))[0] if red.startswith("BOOK_PREFIX_DIVERGENCE")]
    assert len(diverged) == 1 and "contracts" in diverged[0], f"只改一本 ⇒ 只点被改的那一枚：{diverged}"
    assert "起分叉" in diverged[0] and "renamed_leaf" in diverged[0], f"证据要看得见分叉点：{diverged}"
    assert "renamed_leaf" not in diverged[0].split("⇄")[0], f"分叉前缀侧不许带上新名：{diverged}"
    assert "只活在" in prc.check_library_roster({}, root).fix_hint

    # 反向腿：整节被删（不是整本册缺席）＝两本册分叉 ⇒ 判红，不许混进失明
    kept: list[str] = []
    skipping = False
    for line in report.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            skipping = "`contracts`" in line
        if not skipping:
            kept.append(line)
    report.write_text("\n".join(kept) + "\n", encoding="utf-8")
    absent_reds, _ = _leg_reds(prc.check_library_roster({}, root))
    assert any(red.startswith("FACTORY_ROW_ABSENT:contracts") for red in absent_reds), absent_reds
    assert not any(red.startswith("BOOK_PREFIX_DIVERGENCE:contracts") for red in absent_reds), absent_reds
    assert manifest.is_file()


def test_member_ledger_leg_is_row_by_row_never_summed(tmp_path: Path) -> None:
    """注毒⑤：成员列与那枚库自己的成员账改一枚不等 ⇒ 附账必红、两枚读数都点名（禁求和）."""
    root = _roster_root(tmp_path)
    roster = _roster_slugs()
    manifest = _write_roster_books(
        root,
        _roster_spec(
            roster,
            {
                "contracts": {"tag": "MISSING-INIT", "members": 7},
                "ingress-protocol": {"tag": "MISSING-INIT", "members": 4},
            },
        ),
    )
    ok = prc.check_library_roster({}, root)
    assert ok.details["leg_verdicts"]["member"] == PASS, ok.details["member_leg"]
    assert _leg_reds(ok)[1] == [], ok.details["member_leg"]

    text = manifest.read_text(encoding="utf-8")
    anchor = "| `contracts` | 7 |"
    assert text.count(anchor) == 1, f"注毒锚点失配（成员列形状变了）：{anchor}"
    manifest.write_text(text.replace(anchor, "| `contracts` | 8 |", 1), encoding="utf-8")
    res = prc.check_library_roster({}, root)
    _, member_reds = _leg_reds(res)
    assert len(member_reds) == 1 and member_reds[0].startswith("MEMBER_ACCOUNT_MISMATCH:contracts"), member_reds
    assert "MANIFEST 成员列=8" in member_reds[0] and "该库成员账=7" in member_reds[0], member_reds[0]
    assert "ingress-protocol" not in "".join(member_reds), f"逐行等值却牵连他行＝求和形：{member_reds}"
    assert res.status == FAIL and "逐行等值" in res.message, res.message
    assert "相加去凑" in res.fix_hint, res.fix_hint

    # 形状锁：附账这条腿与本格里都不许出现 sum()——「禁求和」钉进判据形，不只写在注释里
    assert "sum" not in _bare_call_names("_library_member_leg"), "附账腿里出现了 sum()＝求和"
    assert "sum" not in _bare_call_names("check_library_roster"), "本格出现了 sum()＝跨行聚合"


def test_legs_are_blind_not_green_or_red_when_out_of_repo_faces_absent(tmp_path: Path) -> None:
    """注毒⑥：仓外面缺席 ⇒ 相关腿 SKIP + ``UNTRACKED_GATE``，绝不产 PASS、绝不产 FAIL."""
    root = _roster_root(tmp_path)
    roster = _roster_slugs()

    # (a) MANIFEST.md 指向不存在的路径（连 ChatBot_Libs 都没建）＝整格失明：SKIP＋无 PASS 字样＋rc 放行
    res = prc.check_library_roster({}, root)
    assert res.status == SKIP, f"仓外盘面缺席却产了 {res.status}"
    assert "UNTRACKED_GATE" in res.message and "PASS" not in res.message, res.message
    assert res.details["import_leg"]["blind"] == "UNTRACKED_GATE", res.details["import_leg"]
    assert res.details["member_leg"]["verdict"] == SKIP, res.details["member_leg"]
    assert prc.main(["--only", "library_roster", "--json", "--project-root", str(root)]) == 0

    # (b) 只有第二本册不在场 ⇒ 腿C 失明（不产 FAIL 也不自产 PASS），名册轴的绿照旧并当场披露
    _write_roster_books(root, _roster_spec(roster, {"contracts": {"tag": "IMPORTABLE", "members": 2}}))
    (root.parent / prc.LIBS_ROOT_DIRNAME / "FACTORY-REPORT.md").unlink()
    no_report = prc.check_library_roster({}, root)
    assert no_report.details["import_leg"]["blind"] == "UNTRACKED_GATE:FACTORY_REPORT_ABSENT"
    assert no_report.details["leg_verdicts"]["import"] == SKIP, no_report.details["leg_verdicts"]
    assert no_report.status != FAIL, no_report.message
    assert "UNTRACKED_GATE" in no_report.message, no_report.message

    # (c) 某库目录不在场 ⇒ 两枚盘读数与那枚成员账都无从复核＝腿级 SKIP，绝不许读成「可导入」
    import shutil  # 局部 import：本件顶部 import 面不许动（只追加用例的写面纪律）

    all_green = {slug: {"tag": "IMPORTABLE", "members": 1} for slug in roster}
    _write_roster_books(root, _roster_spec(roster, all_green))
    shutil.rmtree(root.parent / prc.LIBS_ROOT_DIRNAME / roster[0])
    blind = prc.check_library_roster({}, root)
    import_leg, member_leg = blind.details["import_leg"], blind.details["member_leg"]
    assert list(import_leg["reds"]) == [] and list(member_leg["reds"]) == []
    assert import_leg["verdict"] == SKIP and member_leg["verdict"] == SKIP
    assert any(f"SNAPSHOT_DIR_ABSENT:{roster[0]}" in item for item in import_leg["unverifiable"])
    assert "UNTRACKED_GATE" in " ".join(str(item) for item in member_leg["unverifiable"])

    # (d) 目录补回来、两本册齐、每行都 IMPORTABLE 且 rc=0 ⇒ 三腿同绿（**合成正例**，真机今天零座）
    _write_roster_books(root, _roster_spec(roster, all_green))
    green = prc.check_library_roster({}, root)
    assert green.details["leg_verdicts"] == {"roster": PASS, "import": PASS, "member": PASS, "fold": PASS}
    assert green.status == PASS and "UNTRACKED_GATE" not in green.message, green.message


# ---------------------------------------------------------------------------
# 裁定①（组合可导入）两条新腿：桥接件形状 ⇄ `组合N段` 合并证据
#
# 病根（本波实犯，两形都真出现过）：一行 `extend_path` 门面是**第二种 init**，它按装载序把
# 别座那枚带 re-export 正文的真身整段盖掉（`cannot import name 'InjectionAction'`），而册上
# 读数那时照样"绿"；另一形是"import 没抛"被当成"共装成功"——单一目录自转也不抛，那种绿
# 与分库这件事无关 ⇒ 合并证据（段数 ≥2）必须由读数自己带出来，门只认它。
# ---------------------------------------------------------------------------


def test_import_leg_compose_shape_and_segment_legs_bite(tmp_path: Path) -> None:
    """三形注毒各咬一次 ＋ 在册形状不误伤（全部走 tmp_path 夹具，真身 `../ChatBot_Libs` 零接触）."""
    roster = _roster_slugs()
    root = _roster_root(tmp_path)
    base = {slug: {"tag": "IMPORTABLE", "members": 1} for slug in roster}

    # 底：在册形状（桥接件＝与主仓逐字节相同 ＋ `组合13段`）⇒ 两腿都不该出声
    _write_roster_books(root, _roster_spec(roster, base))
    clean = prc.check_library_roster({}, root)
    assert list(clean.details["import_leg"]["reds"]) == [], clean.details["import_leg"]["reds"]
    assert clean.status == PASS, clean.message

    # 注毒一：快照插件根 init 写成一行门面（第二种形状）⇒ 点名该座
    one_shape = dict(base)
    one_shape["contracts"] = {**one_shape["contracts"], "shape": "facade-line"}
    _write_roster_books(root, _roster_spec(roster, one_shape))
    drifted = prc.check_library_roster({}, root)
    assert any(
        item.startswith("BRIDGE-SHAPE-DRIFT:contracts") for item in drifted.details["import_leg"]["reds"]
    ), drifted.details["import_leg"]["reds"]
    assert drifted.status == FAIL, drifted.message

    # 注毒二：段数写 1（同名包根本没跨座合并）⇒ SPLIT_NOT_MERGED
    one_seg = dict(base)
    one_seg["adapter-qq"] = {**one_seg["adapter-qq"], "segments": 1}
    _write_roster_books(root, _roster_spec(roster, one_seg))
    merged = prc.check_library_roster({}, root)
    assert any(
        item.startswith("SPLIT_NOT_MERGED:adapter-qq") for item in merged.details["import_leg"]["reds"]
    ), merged.details["import_leg"]["reds"]

    # 注毒三：自称 IMPORTABLE 却不写段数 ⇒ 合并证据缺席（"没写"不许当"没问题"）
    no_seg = dict(base)
    no_seg["render-outbound"] = {**no_seg["render-outbound"], "segments": None}
    _write_roster_books(root, _roster_spec(roster, no_seg))
    blind_cell = prc.check_library_roster({}, root)
    assert any(
        item.startswith("IMPORTABLE_WITHOUT_SEGMENT_EVIDENCE:render-outbound")
        for item in blind_cell.details["import_leg"]["reds"]
    ), blind_cell.details["import_leg"]["reds"]


# ---------------------------------------------------------------------------
# --json 的 stdout 是**机器读点**（投递路径三把锁，2026-10-08 尾追加；既有用例一字未改）
# ---------------------------------------------------------------------------
# 病根：读数消费者 ``scripts/tts_offline_selfcheck.py`` 拿
# ``json.loads(stdout.strip())`` **整串**读本脚本的 --json。stdout 上混进一枚警告
# ＝门当场失明、把「读不到」报成「读得出」（本仓反复踩的「量具自己坏了却读成正常」那一族）。
# 现算（插桩实跑，三态：空假根／HEAD 副本根／真根，逐笔登记 stdout 写入与调用栈）：
# 盘上「缺 .env ⇒ 打警告」那枚写手**今天不存在**——--json 全程只有 2 笔 stdout 写入，
# 两笔都来自 ``main`` 的 JSON 那一口。⇒ 本格钉的是**投递路径的形状**而不是某一行警告码：
#   腿甲＝警告真混进来时 stdout 仍整串可解析（污染＝红）；
#   腿乙＝警告没被摘掉可见性（改投既有的 stderr，禁「为了不污染 stdout 干脆不打」）；
#   形状锁＝判据面按**符号名**判（main 之外一枚 stdout 写手都不许有，禁裸行号坐标）。
# 🔴 三把锁全在投递路径上：判据、退出码、项数、``_library_import_leg`` 的方向一概不碰。

_JSON_WARNING_MARK = "[警告] 项目根缺 .env ⇒ 全键回落缺省（注毒面）"
_LOAD_ENV_ANCHOR = (
    "    return dict(\n"
    '        load_runtime_env_values((".env", ".env.prod"), root=project_root).values\n'
    "    )\n"
)


def _no_env_root(tmp_path: Path) -> Path:
    """构造「项目根缺 ``.env``」那态：拿 ``make_project`` 的骨架、只把 .env 剥掉.

    🔴 只碰 tmp_path 里这一份副本——真 ``.env`` 零接触，也绝不把真 .env 复制进副本
    （AGENTS.md 第一部分规则 3：真实 key 只在那一个文件里）。
    """
    root = make_project(tmp_path)
    root.joinpath(".env").unlink()
    assert not root.joinpath(".env").is_file()
    assert not root.joinpath(".env.prod").is_file(), "副本里留了第二枚 env ⇒ 本态不是「缺 .env」"
    return root


def _stub_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """离线桩：子进程交回真身给得出的读数 + TCP 可达（本件既有纪律）."""
    all_subproc_ok(monkeypatch)
    monkeypatch.setattr(prc, "probe_tcp", lambda host, port, timeout=2.0: True)


def _inject_stdout_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """把「缺 .env ⇒ 往 stdout 打警告」这枚写手注进判据面（装载判据一字不动）.

    注的形状与真身会犯的一模一样：装载完成、``return`` 之前一枚不带 ``file=`` 的
    ``print`` ⇒ 默认落 stdout。守卫一旦失效它就直接压在 JSON 头上。
    """
    real_load_env = prc.load_env

    def _load_env_and_warn(project_root: Path) -> dict[str, str]:
        values = real_load_env(project_root)
        print(_JSON_WARNING_MARK)
        return values

    monkeypatch.setattr(prc, "load_env", _load_env_and_warn)


def _parse_machine_stdout(text: str) -> dict[str, object]:
    """整串 ``json.loads``；读不出折成**断言失败**（红原文里看得见污染行，不许飘成 ERROR）."""
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise AssertionError(
            f"--json 的 stdout 不是纯 JSON（{type(exc).__name__}: {exc}）；"
            f"前 240 字＝{text[:240]!r}"
        ) from None
    assert isinstance(payload, dict), f"--json 读数顶层不是对象：{text[:120]!r}"
    return payload


def _stdout_writes_outside_main(source: str) -> list[str]:
    """按符号名摊「往 stdout 写的那一口」：``main`` 之外一枚都不许有（禁裸行号坐标）.

    四种形态同判：①不带 ``file=`` 的 ``print``（默认 stdout）②``file=`` 指向的不是
    告警出口 ③``sys.stdout.write`` ④``redirect_stdout`` 的目标不是告警出口。
    ``main`` 豁免＝它是终端呈现层，两笔出口（--json 的 JSON / 人读表格）本就该在 stdout；
    豁免由 ``test_machine_read_point_has_no_stdout_writer_in_the_judgment_face``
    里「main 必须继续包守卫 + 守卫必须指向 stderr」两条钉死，不是敞口。
    """
    hits: list[str] = []
    tree = ast.parse(source)
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name != "main"]:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "write":
                stream = func.value
                if (
                    isinstance(stream, ast.Attribute)
                    and stream.attr == "stdout"
                    and isinstance(stream.value, ast.Name)
                    and stream.value.id == "sys"
                ):
                    hits.append(f"{fn.name}: sys.stdout.write")
                continue
            if not (isinstance(func, ast.Name) and func.id in {"print", "redirect_stdout"}):
                continue
            if func.id == "print":
                file_kw = next((kw for kw in node.keywords if kw.arg == "file"), None)
                if file_kw is None:
                    hits.append(f"{fn.name}: print 不带 file=（默认落 stdout）")
                elif "stderr" not in ast.dump(file_kw.value):
                    hits.append(f"{fn.name}: print 的 file= 不是既有告警出口")
            else:
                target = node.args[0] if node.args else None
                if target is None or "stderr" not in ast.dump(target):
                    hits.append(f"{fn.name}: redirect_stdout 的目标不是既有告警出口")
    return hits


def test_json_stdout_is_pure_machine_reading_when_the_env_warning_fires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """腿甲：缺 .env 且警告真打出来时，``--json`` 的 stdout 仍必须整串 json.loads 得回来."""
    root = _no_env_root(tmp_path)
    _stub_offline(monkeypatch)
    _inject_stdout_warning(monkeypatch)

    rc = prc.main(["--json", "--project-root", str(root)])
    captured = capsys.readouterr()

    payload = _parse_machine_stdout(captured.out)
    assert _JSON_WARNING_MARK not in captured.out, "警告混进了 stdout＝机器读点当场失明"
    assert rc == 1 and payload["exit_code"] == 1, (rc, payload["exit_code"])
    assert payload["project_root"] == str(root), payload["project_root"]
    results = payload["results"]
    assert isinstance(results, list), results
    ids = [str(item["id"]) for item in results]
    assert ids == prc.declared_item_ids(), f"整串可解析≠内容齐：少一格就是读了个寂寞：{ids}"
    env_cell = next(item for item in results if item["id"] == "env_paths")
    assert env_cell["status"] == FAIL, f"缺 .env 那一格必须照实红（改投递不改判据）：{env_cell}"


def test_the_env_warning_is_delivered_to_stderr_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """腿乙：警告没被摘掉可见性——--json 那一路整句落 stderr；人读那一路原样落 stdout."""
    root = _no_env_root(tmp_path)
    _stub_offline(monkeypatch)
    _inject_stdout_warning(monkeypatch)

    assert prc.main(["--json", "--project-root", str(root)]) == 1
    json_run = capsys.readouterr()
    assert _JSON_WARNING_MARK in json_run.err, (
        "警告没落在 stderr＝被「为了不污染 stdout 干脆不打」吞了：摘可见性不是修法"
    )
    # 两条腿同态并查：改投递路径不许把读数一起带走
    _parse_machine_stdout(json_run.out)

    assert prc.main(["--project-root", str(root)]) == 1
    table_run = capsys.readouterr()
    assert _JSON_WARNING_MARK in table_run.out, (
        "人读表格那一路是现状原样：守卫只包 --json，扩到这里＝偷改人读面"
    )
    assert "汇总: " in table_run.out, table_run.out[-200:]


def test_machine_read_point_has_no_stdout_writer_in_the_judgment_face() -> None:
    """形状锁（按符号名，禁裸行号）：判据面里不许存在往 stdout 写的那一口，守卫不许被悄悄摘掉."""
    before = PRC_FILE.read_bytes()
    source = PRC_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "_machine_stdout_guard" in names, (
        "守卫函数不在了（改名/删除要同批改本锁）：--json 的 stdout 又没人守"
    )

    hits = _stdout_writes_outside_main(source)
    assert not hits, "判据面里出现了往 stdout 写的一口：" + " | ".join(hits[:6])

    main_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    assert any(
        isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_machine_stdout_guard"
        for call in ast.walk(main_fn)
    ), "main 不再调用 _machine_stdout_guard ⇒ main 的豁免成了敞口"
    guard_fn = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_machine_stdout_guard"
    )
    assert any(
        isinstance(call, ast.Call) and getattr(call.func, "id", "") == "redirect_stdout"
        for call in ast.walk(guard_fn)
    ), "守卫里不再有 redirect_stdout＝它可能已改成「干脆不打」那一种假修法"

    # 注毒自证（纯内存，真文件零接触）：往 load_env 体内塞一枚不带 file= 的 print
    assert source.count(_LOAD_ENV_ANCHOR) == 1, (
        f"注毒锚点失配（load_env 的形状变了）：{_LOAD_ENV_ANCHOR!r}"
    )
    poisoned = source.replace(
        _LOAD_ENV_ANCHOR, '    print("注毒：缺 .env 的警告")\n' + _LOAD_ENV_ANCHOR, 1
    )
    ast.parse(poisoned)  # 毒必须是合法源码，否则红在语法上说明不了本锁抓到了越权
    poison_hits = _stdout_writes_outside_main(poisoned)
    assert any("load_env" in item for item in poison_hits), (
        f"注毒没让形状锁变红＝这把锁是空腿：{poison_hits[:6]}"
    )
    assert PRC_FILE.read_bytes() == before, "形状锁过程中真身被改动——立即停手排查"


# ---------------------------------------------------------------------------
# 16-bis. 执法口在册锁（工单 W-2 同族，2026-10-08）
#
# `structure_readiness` 是**转贴型**格子：它靠 `_enforcement_flag_declared` 去问每把尺自己的
# argparse 名册「这枚 `--fail-on-violations` declare 了没有」，判不到就落
# `UNDECIDABLE(RULER_PARAM_MISSING:…)`——不参与判定、也不许洗成绿。那条纪律是对的，但它有个
# 静默面：**尺把参数删掉时，体检只会少一面判词，没人报警**（③「物理归类」这一面就是这样空转的）。
# 本锁把这枚参数升成硬前置：凡在 `STRUCTURE_FACES` 里挂着它当执法口的尺（现算＝命名与规格／
# 中央调度／物理归类三面），源码里必须真 declare 它——将来谁删参数或尺改名，本锁当场红。
# 注毒一律走 tmp_path 副本（真文件零接触），证明这把尺不是恒真。
# ---------------------------------------------------------------------------

_ENFORCE_FLAG = "--fail-on-violations"
#: 这枚执法口的两把**规格尺**（缺任一枚＝本锁盯的对象被摘走，不许静默缩面）。
_ENFORCE_RULERS = ("spec_gates_census.py", "physical_placement_census.py")


def _faces_with_enforce_flag() -> list[prc.StructureFace]:
    return [face for face in prc.STRUCTURE_FACES if face.enforce_flag == _ENFORCE_FLAG]


def test_every_structure_face_enforcement_port_is_declared_by_its_ruler() -> None:
    """两把（实为三面）执法尺**都**认 `--fail-on-violations`，且 rc 名册三态齐全（0/2/3）。"""
    faces = _faces_with_enforce_flag()
    assert len(faces) >= 2, f"挂这枚执法口的面不足两面＝面表被静默缩面：{[f.key for f in faces]}"
    scripts = " ".join(face.script_rel for face in faces)
    for name in _ENFORCE_RULERS:
        assert name in scripts, f"{name} 那面不再用 {_ENFORCE_FLAG} 执法＝本锁盯的对象被摘走（要同批改本锁并给替代判据）"
    for face in faces:
        script = PROJECT_ROOT / face.script_rel
        assert script.is_file(), f"{face.key} 的尺不在册：{face.script_rel}"
        assert _ENFORCE_FLAG in face.argv, f"{face.key} 的 argv 没把这枚执法口传进去：{face.argv}"
        codes = {int(code) for code, _label in face.rc_verdicts}
        assert codes >= {0, 2, 3}, f"{face.key} 的 rc 名册缺三态之一（转贴侧不许只认绿）：{face.rc_verdicts}"
        declared = prc._enforcement_flag_declared(script, _ENFORCE_FLAG)
        assert declared is True, (
            f"{face.script_rel} 的 argparse 名册里没有了 {_ENFORCE_FLAG} ⇒ {face.key} 这一面会退回"
            "无牙态（体检只报 RULER_PARAM_MISSING、不报警）。要么把参数补回来，"
            "要么改这面的执法判据并**同批**把 rc 语义与聚合侧一起换掉"
        )


def test_enforcement_port_lock_is_not_evergreen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒自证：把物理归类那把尺的参数名改掉（只在 tmp 副本上）⇒ 同一判据必回 False、该面必 UNDECIDABLE.

    两腿各证一件事：①`_enforcement_flag_declared` 不是恒真（删参数看得见）；
    ②聚合器对着「没 declare」的尺**只落 UNDECIDABLE**，绝不产 PASS、绝不产 FAIL
    （把 rc=2 的用法错误读成红＝假红，读成绿＝假绿，两头都不许）。
    """
    face = next(f for f in _faces_with_enforce_flag() if "physical_placement_census" in f.script_rel)
    source_path = PROJECT_ROOT / face.script_rel
    before = source_path.read_bytes()
    source = before.decode("utf-8")
    anchor = f'"{_ENFORCE_FLAG}",\n'
    assert source.count(anchor) == 1, f"注毒锚点失配（命中 {source.count(anchor)} 次）：毒腿会打空"
    poisoned = source.replace(anchor, '"--fail-on-violations-retired",\n', 1)
    ast.parse(poisoned)  # 毒必须是合法源码，否则红在语法上说明不了本锁抓到了退参数

    fake_root = tmp_path / "proj"
    (fake_root / "scripts").mkdir(parents=True)
    victim = fake_root / face.script_rel
    victim.write_text(poisoned, encoding="utf-8")
    assert prc._enforcement_flag_declared(victim, _ENFORCE_FLAG) is False, (
        "注毒后仍判「有执法口」＝这把形状锁恒真，将来删参数无人报警")

    monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600: (2, "", "error: unrecognized arguments"))
    label, line, details = prc._run_structure_face(face, fake_root)
    assert label == prc.STRUCTURE_LABEL_UNDECIDABLE, f"无牙的尺不许产 {label}（既不许假绿也不许假红）"
    assert "RULER_PARAM_MISSING" in line, line
    assert details["flag_declared"] is False and details["ruler_rc"] == 2, details
    assert source_path.read_bytes() == before, "注毒过程中尺的真身被改动——立即停手排查"


# ---------------------------------------------------------------------------
# 14. kb_domain_anchor：尺装不上＝UNDECIDABLE(码)，绝不许冒充「没有缺口」（2026-10-12 根修）
# ---------------------------------------------------------------------------
# 复现的缺陷：中央出口一次直载在册四枚，``plain_text`` 在**没预导插件根**的进程里必
# ImportError（它模块级的绝对 import 拉起插件根 ``__init__``，根再 import campus，campus
# 回头 from plain_text import redact_local_secrets——循环吃到半只的自己）。旧读数把这一形
# 折成 SKIP，而汇总在 n_fail==0 时一律说「全绿，可以重启」＝体检面把「我量不了」报成
# 「没问题」。下面三腿分别钉：装载失败→第四态、被装载的符号被摘→同样第四态（且不许抛
# AttributeError 炸掉整份预检）、汇总行→第四态单独点名且不许说全绿。
# 🔴 两腿都**不换装载口**：一腿让真身 ``_plugin_module_by_path`` 对着一个真缺文件的根去装，
# 一腿只摘它装回来的那枚符号——换掉装载口的注毒证不出「中央出口自己怎么读数」。

DRIVE_PATH_RE = re.compile(r"[A-Za-z]:[\\/]")


def _ruler_dotted(alias: str) -> str:
    """在册枚名 → 它在 sys.modules 上的绝对名（名册与包名都从真身现推，本件不写死路径）."""
    rel = dict(prc._RULER_MODULES)[alias]
    return f"{prc._PLUGIN_PKG}.{rel}"


def _bare_project(tmp_path: Path) -> Path:
    """假项目根（make_project 已备好 .env 的 BOT_KB_WIKI_ROOT），且只在册 kb_wiki 那一枚文件.

    ``check_kb_domain_anchor`` 选源码根的判据就是「kb_wiki 那枚在不在被测根上」，摆上它
    ⇒ 装载口真的对着这个根去找其余各枚（其余各枚在这里就是不在）。
    """
    root = make_project(tmp_path)
    victim = root.joinpath("plugins", "bot_unified_runtime", *prc._RULER_KB_WIKI_REL.split(".")).with_suffix(".py")
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_text("# 假根占位件：只让它**在场**（本腿不消费它的任何符号）\n", encoding="utf-8")
    return root


def _ask_the_grid(root: Path) -> prc.CheckResult:
    """问一次读数；异常冒头＝本件 FAILED（不是 ERROR）——run_all 不兜异常，一冒整份预检炸."""
    try:
        return prc.check_kb_domain_anchor(prc.load_env(root), root)
    # 判据要的就是「任何异常都不许逃出体检格」：冒头即判本件红（FAILED），不许退化成 ERROR。
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"装载失败被折成异常抛给体检面（{type(exc).__name__}: {exc}）——"
            "本项要求三态读数 UNDECIDABLE(码)，读数不许靠崩掉来表态"
        )


def test_ruler_load_failure_reports_undecidable_not_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _bare_project(tmp_path)
    # 模拟「独立直跑」的进程形态：这一枚今天就是没被预导过（真身装载口于是走文件路径去装，
    # 而假根上没有那文件 ⇒ 真装不上）。用 delitem 而不是换装载口，判据面全程是真的。
    monkeypatch.delitem(sys.modules, _ruler_dotted("plain_text"), raising=False)

    result = _ask_the_grid(root)
    assert result.status == prc.UNDECIDABLE, (
        f"尺装不上却报 {result.status}＝「我量不了」又被写成读数：{result.message}"
    )
    assert result.status not in (PASS, SKIP, FAIL)
    assert result.message.startswith("UNDECIDABLE(RULER_ABSENT:"), result.message
    assert result.details.get("verdict") == prc.UNDECIDABLE, result.details
    assert str(result.details.get("code", "")).startswith("RULER_ABSENT:"), result.details
    failed_aliases = {name for name, _ in result.details.get("failed", ())}
    assert "plain_text" in failed_aliases, f"逐枚失败名册没点到真装不上的那枚：{failed_aliases}"
    assert "全部有本地域锚点" not in result.message, "装不上却在宣称无缺口＝假无缺口复发"
    assert result.status != FAIL, "本项口径＝报警不阻断，第四态不许顺手变成阻断"
    # 这条分支手上没有脱敏件（plain_text 正是装不上那一枚）⇒ 读数必须**天生**不含盘符路径
    for field_name in ("message", "fix_hint"):
        text = getattr(result, field_name)
        assert not DRIVE_PATH_RE.search(text), f"{field_name} 漏出盘符路径（无脱敏件的分支不许带路径）：{text}"


def test_removed_symbol_of_loaded_module_reports_undecidable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """摘掉**被装载回来的那枚符号**（redact_local_secrets）⇒ 同一形第四态，绝不 AttributeError."""
    root = make_project(tmp_path)  # 假根没有 kb_wiki 文件 ⇒ 源码根回落真仓库，其余各枚装得上
    real_loader = prc._plugin_module_by_path
    plain_text_rel = dict(prc._RULER_MODULES)["plain_text"]

    def hollowed(rel_dotted: str, code_root: Path, registered: list[str]) -> types.ModuleType:
        if rel_dotted == plain_text_rel:
            return types.ModuleType("hollowed_by_test")  # 装上了，但它没有那枚符号
        return real_loader(rel_dotted, code_root, registered)

    monkeypatch.setattr(prc, "_plugin_module_by_path", hollowed)
    result = _ask_the_grid(root)
    assert result.status == prc.UNDECIDABLE, (
        f"符号被摘却报 {result.status}＝「装上了个空壳」被当成量到了：{result.message}"
    )
    assert result.details.get("code") == "RULER_ABSENT:plain_text", result.details
    assert any(
        "SymbolAbsent:redact_local_secrets" in reason for _name, reason in result.details.get("failed", ())
    ), result.details


def test_summary_names_undecidable_and_never_calls_it_green() -> None:
    """汇总行本身：第四态单独计数、单独点名，且它在场时那句「全绿，可以重启」必须闭嘴."""
    rows = [
        prc.CheckResult("alpha", "甲格", PASS, "真验到了"),
        prc.CheckResult("bravo", "乙格", SKIP, "环境里本来就没有"),
        prc.CheckResult("kb_domain_anchor", "丙格", prc.UNDECIDABLE, "UNDECIDABLE(RULER_ABSENT:plain_text）"),
    ]
    tail = prc.render_table(rows).splitlines()[-1]
    assert "PASS 1 / SKIP 1 / UNDECIDABLE 1 / FAIL 0" in tail, tail
    assert "kb_domain_anchor" in tail, f"量不了的格没被点名：{tail}"
    assert "全绿" not in tail, f"有格量不了却仍在说全绿＝假无缺口的读数面：{tail}"
    # 反空转：四值之外的状态不许被折进 PASS 计数（旧算式 len-n_fail-n_skip 正会这么干）
    only_undecidable = prc.render_table([rows[2]]).splitlines()[-1]
    assert "PASS 0" in only_undecidable, only_undecidable

