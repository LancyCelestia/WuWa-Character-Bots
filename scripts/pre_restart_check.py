"""pre_restart_check — 生产 bot 重启前置一键预检（7 项，全绿才动手重启）.

背景：用户提权重启生产 bot（先 NapCat 后 bot.py）前，把散落多处的重启前置项
收敛为一个脚本；exit 0 = 可以动手，exit 1 = 有 FAIL 项先修。

7 项检查（来源：A24 启动审计 / A45 wiki 健康 / A38 catalog 抽查 / 静态门 /
vector-audit 结论）：
  1. env_paths     .env 关键路径存在性：BOT_KB_WIKI_ROOT / BOT_PERSONA_FILES /
                   BOT_MEDIA_ARCHIVE_DB_PATH 父目录 / qx.json（内置资产铁律）
  2. persona_sync  人格副本与锚定一致（sync_persona_source.py --check，
                   副本缺失=SKIP 不算红）
  3. hash_ledger   交付物 SHA-256 台账（tests/verify_hashes.py --check）
  4. doc_sync      机器事实册（scripts/doc_sync.py --check）
  5. kb_drift      知识库三漂移只读复核：ANN 行数 == chunks 行数
                   （sqlite 只读连接 + backup API 拷到 %TEMP% 查，不锁库）
  6. ruff          静态门：ruff check . 全绿
  7. napcat        NapCat WS 127.0.0.1:3001 可达性探测（只提示不阻断）

用法：
  venv python scripts/pre_restart_check.py            # 人读表格
  venv python scripts/pre_restart_check.py --json     # 结构化输出
  venv python scripts/pre_restart_check.py --project-root <path>   # 供测试注入

.exit code：0 = 无 FAIL（PASS/SKIP 均放行）；1 = 有 FAIL。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NAPCAT_HOST = "127.0.0.1"
NAPCAT_PORT = 3001

PASS = "PASS"
SKIP = "SKIP"
FAIL = "FAIL"

DEFAULT_MEDIA_DB = "data/media_archive.sqlite3"
DEFAULT_KB_DB = "data/knowledge_embeddings.sqlite3"
QX_JSON_REL = "plugins/bot_unified_runtime/sources/data/qx.json"


@dataclass(frozen=True)
class CheckResult:
    """单项检查结果：PASS/SKIP/FAIL + 一句话 + FAIL 时的修复指引."""

    id: str
    name: str
    status: str
    message: str
    fix_hint: str = ""


# ---------------------------------------------------------------------------
# .env 解析（对齐 scripts/runtime_paths.py 语义：.env → .env.prod 后者覆盖，
# 行内注释引号感知，os.environ 覆盖文件值；只取路径类键，不打印值）
# ---------------------------------------------------------------------------

def _strip_inline_comment(raw_value: str) -> str:
    quote = ""
    for index, char in enumerate(raw_value):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and index > 0 and raw_value[index - 1] in " \t":
            return raw_value[:index].rstrip()
    return raw_value


def load_env(project_root: Path) -> dict[str, str]:
    """读 .env / .env.prod 键值对（含 BOT_ 前缀配置），os.environ 优先."""
    values: dict[str, str] = {}
    for filename in (".env", ".env.prod"):
        path = project_root / filename
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, raw_value = line.split("=", 1)
            values[name.strip()] = _strip_inline_comment(raw_value).strip().strip('"').strip("'")
    for key in list(values):
        env_val = os.environ.get(key)
        if env_val is not None:
            values[key] = env_val.strip()
    return values


def resolve_data_path(raw: str, project_root: Path, data_root: Path) -> Path:
    """与 runtime_paths.runtime_path 同语义：data/ 前缀重映射到运行时数据根."""
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    normalized = str(path).replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.lower() == "data":
        return data_root
    if normalized.lower().startswith("data/"):
        return (data_root / normalized[5:]).resolve()
    return (project_root / path).resolve()


def runtime_data_dir(env: dict[str, str], project_root: Path) -> Path:
    raw = env.get("BOT_RUNTIME_DATA_DIR", "") or "data"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


# ---------------------------------------------------------------------------
# 可注入的副作用封装（测试 monkeypatch 点）
# ---------------------------------------------------------------------------

def run_cmd(args: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str, str]:
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,  # 返回码交给调用方判定（预检本就要区分红绿）
    )
    return proc.returncode, proc.stdout, proc.stderr


def probe_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 7 项检查
# ---------------------------------------------------------------------------

def check_env_paths(env: dict[str, str], project_root: Path) -> CheckResult:
    cid, name = "env_paths", ".env 关键路径存在性"
    data_root = runtime_data_dir(env, project_root)
    problems: list[str] = []
    notes: list[str] = []

    # 1a. BOT_KB_WIKI_ROOT：wiki 知识库根目录（A45 wiki 健康前置）
    wiki_root = env.get("BOT_KB_WIKI_ROOT", "").strip()
    if not wiki_root:
        problems.append("BOT_KB_WIKI_ROOT 未配置")
    elif not Path(wiki_root).expanduser().is_dir():
        problems.append(f"BOT_KB_WIKI_ROOT 目录不存在: {wiki_root}")
    else:
        notes.append(f"wiki 根 OK ({wiki_root})")

    # 1b. BOT_PERSONA_FILES：人格副本文件存在
    persona_raw = env.get("BOT_PERSONA_FILES", "").strip()
    persona_files: list[str] = []
    if persona_raw:
        try:
            parsed = json.loads(persona_raw)
            if isinstance(parsed, list):
                persona_files = [str(item) for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            problems.append("BOT_PERSONA_FILES 不是合法 JSON 列表")
    if persona_raw and not persona_files:
        problems.append("BOT_PERSONA_FILES 为空列表")
    missing_persona = [p for p in persona_files if not Path(p).expanduser().is_file()]
    if missing_persona:
        problems.append("BOT_PERSONA_FILES 缺失: " + "; ".join(missing_persona))
    elif persona_files:
        notes.append(f"人格副本 x{len(persona_files)} OK")

    # 1c. BOT_MEDIA_ARCHIVE_DB_PATH 父目录（缺省 data/media_archive.sqlite3）
    media_db_raw = env.get("BOT_MEDIA_ARCHIVE_DB_PATH", "").strip() or DEFAULT_MEDIA_DB
    media_db = resolve_data_path(media_db_raw, project_root, data_root)
    if media_db.parent.is_dir():
        notes.append("media_archive DB 父目录 OK")
    else:
        problems.append(f"BOT_MEDIA_ARCHIVE_DB_PATH 父目录不存在: {media_db.parent}")

    # 1d. qx.json 内置资产（AGENTS.md 规则 6：随包内置，清理波不得误删）
    qx = project_root / QX_JSON_REL
    if qx.is_file():
        notes.append("qx.json OK")
    else:
        problems.append(f"qx.json 内置资产缺失: {qx}")

    if problems:
        return CheckResult(
            cid,
            name,
            FAIL,
            "; ".join(problems),
            "路径字段改 .env（键含义见 docs/config-catalog-full A26；"
            "wiki 根修正先例见 .superpowers/sdd/2026-09-13-six-domain-batch/"
            "startup-audit-report.md A24）；qx.json 属内置资产铁律"
            "（AGENTS.md 第一部分规则 6），误删从 git 恢复。",
        )
    return CheckResult(cid, name, PASS, "; ".join(notes))


def check_persona_sync(env: dict[str, str], project_root: Path) -> CheckResult:
    cid, name = "persona_sync", "人格副本与锚定一致"
    rc, out, err = run_cmd(
        [sys.executable, "scripts/sync_persona_source.py", "--check"], project_root
    )
    if rc == 0 and "[SKIP]" in out:
        return CheckResult(cid, name, SKIP, out.strip().splitlines()[-1] if out.strip() else "副本缺失，门跳过")
    if rc == 0:
        return CheckResult(cid, name, PASS, out.strip().splitlines()[-1] if out.strip() else "副本与锚定一致")
    detail = (out.strip() or err.strip()).splitlines()[-1] if (out.strip() or err.strip()) else f"exit {rc}"
    return CheckResult(
        cid,
        name,
        FAIL,
        detail,
        "人工审阅副本改动后 python scripts/sync_persona_source.py --adopt 重录锚定"
        "（误改先从备份恢复）；机制见 .superpowers/sdd/2026-09-13-six-domain-batch/"
        "persona-sync-report.md。",
    )


def check_hash_ledger(project_root: Path) -> CheckResult:
    cid, name = "hash_ledger", "交付物 SHA-256 台账"
    rc, out, err = run_cmd([sys.executable, "tests/verify_hashes.py", "--check"], project_root)
    if rc == 0:
        return CheckResult(cid, name, PASS, "哈希台账无漂移")
    detail = (out.strip() or err.strip()).splitlines()[-1] if (out.strip() or err.strip()) else f"exit {rc}"
    return CheckResult(
        cid,
        name,
        FAIL,
        detail,
        "先核对漂移来源（人工改动须 python tests/verify_hashes.py --write 重录基线，"
        "意外改动先查因）；常驻门口径见 tests/test_cross_validation_gates.py。",
    )


def check_doc_sync(project_root: Path) -> CheckResult:
    cid, name = "doc_sync", "机器事实册 docs/auto-facts.md"
    rc, out, err = run_cmd([sys.executable, "scripts/doc_sync.py", "--check"], project_root)
    if rc == 0:
        return CheckResult(cid, name, PASS, "机器事实册同步")
    detail = (out.strip() or err.strip()).splitlines()[-1] if (out.strip() or err.strip()) else f"exit {rc}"
    return CheckResult(
        cid,
        name,
        FAIL,
        detail,
        "核对漂移后 python scripts/doc_sync.py --write 重录 docs/auto-facts.md"
        "（机器管文件，--write 输出字节确定、幂等）。",
    )


def check_kb_drift(env: dict[str, str], project_root: Path) -> CheckResult:
    """知识库三漂移只读复核：ANN 行数 == chunks 行数（且无待嵌入行）.

    sqlite 只读连接 + backup API 拷到 %TEMP% 后再查，不锁生产库；
    ANN 行数优先 faiss.read_index 读 ntotal，失败回退 order.json 长度。
    """
    cid, name = "kb_drift", "知识库 ANN==chunks 无漂移"
    data_root = runtime_data_dir(env, project_root)
    kb_raw = env.get("BOT_KNOWLEDGE_DB_PATH", "").strip() or DEFAULT_KB_DB
    db_path = resolve_data_path(kb_raw, project_root, data_root)
    if not db_path.is_file():
        return CheckResult(cid, name, SKIP, f"知识库未构建（{db_path} 不存在），跳过")

    index_path = db_path.parent / "knowledge_faiss.index"
    order_path = db_path.parent / "knowledge_faiss.order.json"

    ann_count: int | None = None
    ann_source = ""
    if index_path.is_file():
        try:
            import faiss  # 延迟导入：仅在需要读 ANN 行数时

            ann_count = int(faiss.read_index(str(index_path)).ntotal)
            ann_source = "faiss ntotal"
        except Exception:  # noqa: BLE001 — faiss 不可用/索引损坏时降级
            ann_count = None
    if ann_count is None and order_path.is_file():
        try:
            order = json.loads(order_path.read_text(encoding="utf-8"))
            ann_count = len(order)
            ann_source = "order.json"
        except (OSError, json.JSONDecodeError):
            ann_count = None
    if ann_count is None:
        return CheckResult(cid, name, SKIP, "无法读取 ANN 行数（faiss 与 order.json 均不可用）")

    chunks = embedded = -1
    try:
        with tempfile.TemporaryDirectory(prefix="prechk_kb_") as tmp_dir:
            copy_path = Path(tmp_dir) / "kb_copy.sqlite3"
            src = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
            try:
                dst = sqlite3.connect(str(copy_path))
                try:
                    src.backup(dst)  # backup API：含 WAL 内容，读源不加写锁
                finally:
                    dst.close()
            finally:
                src.close()
            chunks, embedded = _count_kb_rows(copy_path)
    except (OSError, sqlite3.Error) as exc:
        return CheckResult(cid, name, SKIP, f"知识库只读拷贝失败（{exc}），跳过")

    if ann_count == chunks and embedded == chunks:
        return CheckResult(
            cid, name, PASS, f"ANN={ann_count} == chunks={chunks}（待嵌入 0；ANN 行数源: {ann_source}）"
        )
    return CheckResult(
        cid,
        name,
        FAIL,
        f"ANN={ann_count} vs chunks={chunks}（已嵌入 {embedded}）——存在向量通道漂移",
        "跑一次 knowledge-sync 全链（同步 → embed_pending 补嵌 → build_ann_index 重建）；"
        "漂移定性见 .superpowers/sdd/2026-09-13-six-domain-batch/vector-audit.md。",
    )


def _count_kb_rows(copy_path: Path) -> tuple[int, int]:
    """在临时副本上统计 chunks 总行数与已嵌入行数（只读，副本随临时目录回收）."""
    con = sqlite3.connect(str(copy_path))
    try:
        chunks = int(con.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0])
        embedded = int(
            con.execute(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE vector_blob IS NOT NULL"
            ).fetchone()[0]
        )
    finally:
        con.close()
    return chunks, embedded


def check_ruff(project_root: Path) -> CheckResult:
    cid, name = "ruff", "静态门 ruff check ."
    rc, out, err = run_cmd([sys.executable, "-m", "ruff", "check", "."], project_root, timeout=600)
    if rc == 0:
        return CheckResult(cid, name, PASS, "All checks passed")
    detail = (out.strip() or err.strip()).splitlines()[-1] if (out.strip() or err.strip()) else f"exit {rc}"
    return CheckResult(
        cid,
        name,
        FAIL,
        detail,
        "ruff check <file> 定位逐条修复；门禁口径见 "
        ".superpowers/sdd/2026-09-13-six-domain-batch/staticgate-final.md。",
    )


def check_napcat(host: str = NAPCAT_HOST, port: int = NAPCAT_PORT) -> CheckResult:
    cid, name = "napcat", f"NapCat WS {host}:{port} 可达性（提示不阻断）"
    if probe_tcp(host, port):
        return CheckResult(cid, name, PASS, "端口可达（NapCat 在线）")
    return CheckResult(
        cid,
        name,
        SKIP,
        "端口不可达——若尚未启动 NapCat 属预期（bot 自带重连）；重启顺序：先 NapCat 后 bot.py",
        "装配指引见 docs/napcat-setup.md。",
    )


# ---------------------------------------------------------------------------
# 汇总与输出
# ---------------------------------------------------------------------------

def run_all(project_root: Path) -> list[CheckResult]:
    env = load_env(project_root)
    return [
        check_env_paths(env, project_root),
        check_persona_sync(env, project_root),
        check_hash_ledger(project_root),
        check_doc_sync(project_root),
        check_kb_drift(env, project_root),
        check_ruff(project_root),
        check_napcat(),
    ]


def render_table(results: list[CheckResult]) -> str:
    id_w = max(len(r.id) for r in results)
    name_w = max(len(r.name) for r in results)
    lines = [f"{'检查项':<{id_w}}  {'说明':<{name_w}}  状态  详情", "-" * 72]
    for r in results:
        lines.append(f"{r.id:<{id_w}}  {r.name:<{name_w}}  {r.status}  {r.message}")
    fails = [r for r in results if r.status == FAIL]
    if fails:
        lines.append("")
        lines.append("FAIL 修复指引：")
        for r in fails:
            lines.append(f"  [{r.id}] {r.fix_hint}")
    n_fail = len(fails)
    n_skip = sum(1 for r in results if r.status == SKIP)
    n_pass = len(results) - n_fail - n_skip
    lines.append("")
    verdict = "全绿，可以重启（先 NapCat 后 bot.py）" if n_fail == 0 else "存在 FAIL 项，先修再重启"
    lines.append(f"汇总: PASS {n_pass} / SKIP {n_skip} / FAIL {n_fail} → {verdict}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生产 bot 重启前置一键预检（7 项）")
    parser.add_argument("--json", action="store_true", help="结构化 JSON 输出")
    parser.add_argument("--project-root", default=None, help="覆盖项目根（默认仓库根，供测试/异构部署）")
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve() if args.project_root else PROJECT_ROOT
    results = run_all(project_root)

    try:  # Windows 控制台中文输出防 mojibake/编码异常
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

    if args.json:
        print(
            json.dumps(
                {
                    "project_root": str(project_root),
                    "exit_code": 1 if any(r.status == FAIL for r in results) else 0,
                    "results": [asdict(r) for r in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_table(results))
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
