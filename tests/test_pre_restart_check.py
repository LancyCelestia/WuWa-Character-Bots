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
        qx_dir = root / "plugins" / "bot_unified_runtime" / "domains" / "weather" / "assets"
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


# ---------------------------------------------------------------------------
# 8. webui：单文件壳资产（缺失=SKIP / 空·超限·外链=FAIL / 合格=PASS）
# ---------------------------------------------------------------------------

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


def write_webui(root: Path, content: bytes | str) -> Path:
    dist = root / "webui" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    index = dist / "index.html"
    index.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return index


def test_webui_missing_is_skip_with_build_hint(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    result = prc.check_webui(root)
    assert result.status == SKIP
    assert "npm run build" in result.fix_hint
    assert "webui/dist/index.html" in result.message


def test_webui_valid_single_file_pass(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    index = write_webui(root, SINGLE_FILE_HTML)
    result = prc.check_webui(root)
    assert result.status == PASS
    assert "单文件" in result.message
    assert str(index.stat().st_size) in result.message  # 体积信息可见


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


def test_webui_relative_src_not_flagged_per_spec(tmp_path: Path) -> None:
    """规格只把 http(s) 与绝对路径算外链；相对路径 src 不误伤（PASS）."""
    root = make_project(tmp_path)
    write_webui(root, '<html><head><script src="./assets/x.js"></script></head><body></body></html>')
    assert prc.check_webui(root).status == PASS


def test_webui_non_stylesheet_link_ignored(tmp_path: Path) -> None:
    """只有 rel=stylesheet 的 <link> 计外链；icon/preload 等不判."""
    root = make_project(tmp_path)
    write_webui(root, '<html><head><link rel="preload" href="https://x/y"></head><body></body></html>')
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
