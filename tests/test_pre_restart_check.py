"""pre_restart_check 离线回归：每类检查的 PASS/FAIL/SKIP 判定逻辑.

全部离线：tmp_path 构造假项目环境（.env / 假知识库副本 / 假 qx.json），
子进程与 TCP 探针经 monkeypatch 注入，不发真网络、不跑真 ruff。
"""

from __future__ import annotations

import json
import sqlite3
import sys
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
        qx_dir = root / "plugins" / "bot_unified_runtime" / "sources" / "data"
        qx_dir.mkdir(parents=True)
        (qx_dir / "qx.json").write_text("{}", encoding="utf-8")
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

    def fake_run(args, cwd, timeout=600):
        return 0, "[绿] OK", ""

    monkeypatch.setattr(prc, "run_cmd", fake_run)


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
    assert [r["id"] for r in payload["results"]] == [
        "env_paths", "persona_sync", "hash_ledger", "doc_sync", "kb_drift", "ruff", "napcat",
    ]
    assert all(r["status"] in (PASS, SKIP, FAIL) for r in payload["results"])

    # 注入一个 FAIL（ruff 挂）→ exit 1，且 JSON 里能定位到 FAIL 项与修复指引
    def ruff_fail(args, cwd, timeout=600):
        if "ruff" in args:
            return 1, "E501 line too long", ""
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
