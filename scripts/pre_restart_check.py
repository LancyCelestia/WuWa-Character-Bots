"""pre_restart_check — 生产 bot 重启前置一键预检（10 项，全绿才动手重启）.

背景：用户提权重启生产 bot（先 SnowLuma 后 bot.py）前，把散落多处的重启前置项
收敛为一个脚本；exit 0 = 可以动手，exit 1 = 有 FAIL 项先修。

10 项检查（来源：A24 启动审计 / A45 wiki 健康 / A38 catalog 抽查 / 静态门 /
vector-audit 结论 / 2026-09-18 WebUI 能力面批 / T29 M-12 音色守望）：
  1. env_paths     .env 关键路径存在性：BOT_KB_WIKI_ROOT / BOT_PERSONA_FILES /
                   BOT_MEDIA_ARCHIVE_DB_PATH 父目录 / qx.json（内置资产铁律）
  2. persona_sync  人格副本与锚定一致（sync_persona_source.py --check，
                   副本缺失=SKIP 不算红）
  3. hash_ledger   交付物 SHA-256 台账（tests/verify_hashes.py --check）
  4. doc_sync      机器事实册（scripts/doc_sync.py --check）
  5. kb_drift      知识库三漂移只读复核：ANN 行数 == chunks 行数
                   （sqlite 只读连接 + backup API 拷到 %TEMP% 查，不锁库）
  6. ruff          静态门：ruff check . 全绿
  7. napcat        协议端 SnowLuma WS 127.0.0.1:3001 可达性探测（只提示不阻断）
  8. webui         WebUI 单文件壳资产 webui/dist/index.html：存在、体积
                   0<size<10MB、单文件特征（正文无外链 <script src= /
                   <link rel=stylesheet href=> 到 http(s) 与绝对路径；
                   W3C 命名空间等字符串不算）；缺失=SKIP（先在 webui/ 下
                   npm run build）不算红
  9. control_plane 控制面配置三键：BOT_CONTROL_PLANE_ENABLED /
                   BOT_CONTROL_PLANE_TOKEN_SHA256（读）/
                   BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256（写），
                   各自报 已配置/缺失（哈希键只查非空、绝不回显值）；
                   全缺=SKIP+启用指引，部分配置=PASS 带提示
  10. tts_voice    GPT-SoVITS 音色守望（M-12 bot 侧半，只读探针）：
                   tts_infer.yaml custom 段语义白名单（两权重路径含
                   shorekeeper）+ 权重文件按引擎根实存 + yaml sha256
                   对表 scripts/tts_voice_baseline.json；引擎目录缺失
                   或 BOT_TTS_ENABLED 未启用=SKIP 不算红

用法：
  venv python scripts/pre_restart_check.py            # 人读表格
  venv python scripts/pre_restart_check.py --json     # 结构化输出
  venv python scripts/pre_restart_check.py --project-root <path>   # 供测试注入

.exit code：0 = 无 FAIL（PASS/SKIP 均放行）；1 = 有 FAIL。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
QX_JSON_REL = "plugins/bot_unified_runtime/domains/weather/assets/qx.json"

WEBUI_INDEX_REL = "webui/dist/index.html"
WEBUI_MAX_BYTES = 10 * 1024 * 1024  # 单文件壳体积上限 10MB（现网实构建 ≈0.9MB）

# 控制面配置三键：第二列是人话标签；哈希键只查非空、绝不回显值
CONTROL_PLANE_KEYS: tuple[tuple[str, str], ...] = (
    ("BOT_CONTROL_PLANE_ENABLED", "开关"),
    ("BOT_CONTROL_PLANE_TOKEN_SHA256", "读 token 哈希"),
    ("BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256", "写(超管) token 哈希"),
)

# 单文件特征探测：只看 <script src=> 与 <link rel=stylesheet href=> 标签属性，
# 正文里的 W3C 命名空间（xmlns）/任意 URL 字符串天然不进判定（启发式，容忍 JS
# 字符串里出现标签字面量的极小误报面）。
_TAG_RE = re.compile(r"<(script|link)\b[^>]*>", re.IGNORECASE)
_SRC_ATTR_RE = re.compile(r"""\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
_HREF_ATTR_RE = re.compile(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
_REL_STYLESHEET_RE = re.compile(r"""\brel\s*=\s*["']?[^"'>\s]*stylesheet[^"'>\s]*["']?""", re.IGNORECASE)

# M-12 bot 侧音色守望：基线册=scripts/tts_voice_baseline.json（yaml sha256 字节锚
# + 守岸人权重路径白名单，T60 对引擎只读取证录制）；引擎目录全程只读。
TTS_BASELINE_REL = "scripts/tts_voice_baseline.json"
TTS_ENABLED_TRUTHY = {"true", "1", "yes", "on"}


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
    # 检查 id 仍叫 "napcat"（对外契约：文档/台账/前端按此 id 寻址），实体已是 SnowLuma。
    cid, name = "napcat", f"协议端 SnowLuma WS {host}:{port} 可达性（提示不阻断）"
    if probe_tcp(host, port):
        return CheckResult(cid, name, PASS, "端口可达（SnowLuma 在线）")
    return CheckResult(
        cid,
        name,
        SKIP,
        "端口不可达——若尚未启动 SnowLuma（或未在「进程注入」页点加载）属预期"
        "（bot 自带重连）；重启顺序：先 SnowLuma 后 bot.py",
        "装配指引见 docs/snowluma-setup.md（旧端回滚见 docs/napcat-setup.md）。",
    )


def _external_asset_refs(html: str) -> list[str]:
    """挑出单文件壳违规外链：script[src] 与 link[rel=stylesheet][href] 中
    指向 http(s):// 或绝对路径（/ 开头）的引用；data: URI 与相对路径不算."""
    violations: list[str] = []
    for match in _TAG_RE.finditer(html):
        tag = match.group(0)
        kind = match.group(1).lower()
        attr_re = _SRC_ATTR_RE if kind == "script" else _HREF_ATTR_RE
        attr = attr_re.search(tag)
        if attr is None:
            continue
        if kind == "link" and not _REL_STYLESHEET_RE.search(tag):
            continue  # 只有 rel=stylesheet 的 <link> 判外链（icon/preload 等不判）
        url = next((g for g in attr.groups() if g is not None), "").strip().strip("\"'")
        if not url or url.lower().startswith("data:"):
            continue
        lowered = url.lower()
        if lowered.startswith(("http://", "https://")) or url.startswith("/"):
            violations.append(f"<{kind} ...={url}>")
    return violations


def check_webui(project_root: Path) -> CheckResult:
    """第 8 项：WebUI 单文件壳资产（缺失=SKIP 不算红；坏资产才算 FAIL）."""
    cid, name = "webui", "WebUI 单文件壳资产"
    index_path = project_root / WEBUI_INDEX_REL
    if not index_path.is_file():
        return CheckResult(
            cid,
            name,
            SKIP,
            f"{WEBUI_INDEX_REL} 不存在——WebUI 控制台壳未构建（控制面 /ui 将 404，但不阻断重启）",
            "先在 webui/ 下 npm run build（vite-plugin-singlefile 产出 webui/dist/index.html），"
            "或确认本轮不需要 WebUI 控制台。",
        )
    size = index_path.stat().st_size
    if size == 0:
        return CheckResult(cid, name, FAIL, f"{index_path} 为空文件（0 字节）", "重新构建：webui/ 下 npm run build。")
    if size >= WEBUI_MAX_BYTES:
        return CheckResult(
            cid,
            name,
            FAIL,
            f"{index_path} 体积 {size / 1024 / 1024:.1f} MB ≥ 10MB 上限",
            "单文件壳异常膨胀：检查是否误把大资源打进构建（正常 ≈0.9MB）；重新构建核产物。",
        )
    try:
        html = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return CheckResult(cid, name, FAIL, f"index.html 不可读：{exc}", "检查文件权限/占用后重新构建。")
    violations = _external_asset_refs(html)
    if violations:
        shown = "; ".join(violations[:3]) + (f" 等 x{len(violations)}" if len(violations) > 3 else "")
        return CheckResult(
            cid,
            name,
            FAIL,
            f"单文件壳含外链资产（http(s)/绝对路径）x{len(violations)}: {shown}",
            "GET /ui 只回单文件壳，外链在离线/受限网会白屏：vite-plugin-singlefile 配置失效？"
            "webui/ 下 npm run build 重新构建。",
        )
    if size >= 1024 * 1024:
        human_size = f"{size / 1024 / 1024:.1f} MB"
    elif size >= 1024:
        human_size = f"{size / 1024:.0f} KB"
    else:
        human_size = f"{size} 字节"
    return CheckResult(cid, name, PASS, f"单文件壳 OK（{human_size}，内联无外链）")


def check_control_plane(env: dict[str, str]) -> CheckResult:
    """第 9 项：控制面配置三键 已配置/缺失（哈希键只查非空、不回显值）."""
    cid, name = "control_plane", "控制面配置三键"
    parts: list[str] = []
    missing: list[str] = []
    enabled_value = ""
    for key, label in CONTROL_PLANE_KEYS:
        value = env.get(key, "").strip()
        if not value:
            missing.append(key)
            parts.append(f"{key}({label}) 缺失")
            continue
        if key == "BOT_CONTROL_PLANE_ENABLED":
            enabled_value = value
            parts.append(f"{key} 已配置({value})")  # 开关键非敏感，值可见
        else:
            parts.append(f"{key}({label}) 已配置")  # 哈希键不回显
    if len(missing) == len(CONTROL_PLANE_KEYS):
        return CheckResult(
            cid,
            name,
            SKIP,
            "三键全部未配置——控制面/WebUI 未启用（不阻断重启）",
            "启用：.env 增加三行 BOT_CONTROL_PLANE_ENABLED=true、"
            "BOT_CONTROL_PLANE_TOKEN_SHA256=<读 token 的 sha256 十六进制>、"
            "BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256=<超管 token 的 sha256>，"
            "配置后重启 bot 生效。",
        )
    message = "；".join(parts)
    if missing:
        message += f"——部分缺失 x{len(missing)}，缺的键对应能力不生效"
    if enabled_value.lower() == "false":
        message += "（注意：ENABLED=false，控制面处于关闭状态）"
    return CheckResult(cid, name, PASS, message)


def _load_tts_yaml_custom(text: str) -> dict[str, str] | None:
    """从 tts_infer.yaml 提取 custom 段两个权重键（零依赖窄解析）.

    只认「顶层 `节:` 行」与「缩进 `键: 值` 行」两种形状——这是引擎 save_configs
    yaml.dump 的固定产物形态；任何形状偏离（半截文件/流式内联值/custom 缺段/缺键）
    一律返回 None，由调用方报「解析失败」，绝不静默放行（M-12 教训：假绿比红更糟）.
    """
    custom: dict[str, str] = {}
    wanted = ("t2s_weights_path", "vits_weights_path")
    in_custom = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line[0].isspace():  # 顶层行
            key = stripped.split(":", 1)[0].strip()
            has_inline_value = ":" in stripped and bool(stripped.split(":", 1)[1].strip())
            in_custom = key == "custom" and not has_inline_value
            if key == "custom" and has_inline_value:
                return None  # custom 后跟内联值=不是映射（含半截流式截断形态）
            continue
        if in_custom and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            if key in wanted:
                custom[key] = value.strip().strip('"').strip("'")
    if all(custom.get(k) for k in wanted):
        return custom
    return None


def check_tts_voice_identity(env: dict[str, str], project_root: Path) -> CheckResult:
    """第 10 项：GPT-SoVITS 音色守望（M-12 bot 侧半，只读探针）.

    治理点（T29 M-12）：错误 CWD 裸跑引擎 → 权重静默回退底模 → save_configs
    写回 tts_infer.yaml 永久中毒，bot 侧此前零身份断言。守望=读 yaml 断言
    custom 段两权重为守岸人基线路径且文件实存 + yaml sha256 对表基线册；
    引擎目录不存在或 TTS 未启用=SKIP（沿既有惯例，不假红）。
    """
    cid, name = "tts_voice", "GPT-SoVITS 音色守望（M-12 bot 侧半，只读探针）"
    enabled = env.get("BOT_TTS_ENABLED", "").strip().lower()
    if enabled not in TTS_ENABLED_TRUTHY:
        shown = env.get("BOT_TTS_ENABLED", "").strip() or "未配置"
        return CheckResult(
            cid,
            name,
            SKIP,
            f"BOT_TTS_ENABLED 未启用（当前值：{shown}）——TTS 链路关闭，音色守望不适用",
            "启用语音需 .env 配 BOT_TTS_ENABLED=true 与 BOT_TTS_GPTSOVITS_DIR=<引擎根>。",
        )
    engine_raw = env.get("BOT_TTS_GPTSOVITS_DIR", "").strip()
    engine_root = Path(engine_raw) if engine_raw else None
    if engine_root is None or not engine_root.is_dir():
        shown = engine_raw or "BOT_TTS_GPTSOVITS_DIR 未配置"
        return CheckResult(
            cid,
            name,
            SKIP,
            f"引擎目录不存在：{shown}——沿 pre_restart_check 惯例 SKIP（不假红）",
            "确认 BOT_TTS_GPTSOVITS_DIR 指向 GPT-SoVITS 引擎根（现网=C:/Software/GPT-SoVITS-V2Pro）。",
        )
    baseline_path = project_root / TTS_BASELINE_REL
    if not baseline_path.is_file():
        return CheckResult(
            cid,
            name,
            FAIL,
            f"基线册缺失：{TTS_BASELINE_REL} 不存在——音色守望失去对表锚",
            "从已知健康引擎根重录基线：核 tts_infer.yaml custom 两权重为 shorekeeper 且文件实存后，"
            "把 yaml_relative_path/yaml_sha256/gpt_weights_path/sovits_weights_path 写入基线册。",
        )
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return CheckResult(cid, name, FAIL, f"基线册解析失败：{TTS_BASELINE_REL}（{exc}）", "修复基线册 JSON 后重跑。")
    if not isinstance(baseline, dict):
        return CheckResult(cid, name, FAIL, f"基线册解析失败：{TTS_BASELINE_REL} 顶层不是 JSON 对象", "修复基线册 JSON 后重跑。")
    required_fields = ("yaml_relative_path", "yaml_sha256", "gpt_weights_path", "sovits_weights_path")
    missing_fields = [f for f in required_fields if not str(baseline.get(f, "")).strip()]
    if missing_fields:
        return CheckResult(
            cid,
            name,
            FAIL,
            f"基线册缺字段：{', '.join(missing_fields)}——基线不完整无法对表",
            "基线册四字段必填（yaml_relative_path/yaml_sha256/gpt_weights_path/sovits_weights_path），补齐后重跑。",
        )
    yaml_rel = str(baseline["yaml_relative_path"]).strip()
    yaml_path = engine_root / yaml_rel
    if not yaml_path.is_file():
        return CheckResult(
            cid,
            name,
            FAIL,
            f"yaml 丢失：{yaml_path} 不存在（引擎根={engine_root}）",
            "引擎配置文件被误删？从引擎发行版恢复 tts_infer.yaml 后按基线核 custom 段再重录哈希。",
        )
    yaml_bytes = yaml_path.read_bytes()
    try:
        yaml_text = yaml_bytes.decode("utf-8")
    except UnicodeDecodeError:
        yaml_text = ""
    custom = _load_tts_yaml_custom(yaml_text) if yaml_text else None
    if custom is None:
        return CheckResult(
            cid,
            name,
            FAIL,
            f"tts_infer.yaml 解析失败：custom 段缺失/被截断/无两权重键（{yaml_path}）——"
            "可能撞上 save_configs 非原子写回的半截文件（T53）",
            "重跑一次确认是否持续（瞬时半截写会自愈）；持续解析失败=人工核引擎 custom 段并恢复。",
        )
    gpt_rel = str(baseline["gpt_weights_path"]).strip()
    sovits_rel = str(baseline["sovits_weights_path"]).strip()
    actual_t2s = custom.get("t2s_weights_path", "")
    actual_vits = custom.get("vits_weights_path", "")
    if actual_t2s != gpt_rel or actual_vits != sovits_rel:
        if "shorekeeper" not in actual_t2s.lower() or "shorekeeper" not in actual_vits.lower():
            return CheckResult(
                cid,
                name,
                FAIL,
                f"custom 段权重已不是守岸人——疑似换底模/换音色（实际 t2s={actual_t2s}、vits={actual_vits}；"
                f"基线要求 t2s={gpt_rel}、vits={sovits_rel}）",
                "错误 CWD 裸跑会触发引擎 save_configs 写回 yaml 永久化（T53 六处调用点）："
                "只用钉 CWD 的启动面（start-shorekeeper.ps1/go-api.bat）重启引擎，"
                "人工把 custom 段两权重改回基线路径；勿再裸敲命令。",
            )
        return CheckResult(
            cid,
            name,
            FAIL,
            f"custom 段权重路径与基线不符（仍是 shorekeeper，疑似换了新训练权重）："
            f"实际 t2s={actual_t2s}、vits={actual_vits}；基线要求 t2s={gpt_rel}、vits={sovits_rel}",
            "若确为有意换新权重：先试听复核音色，再重录基线（更新基线册两路径与 yaml_sha256）。",
        )
    missing_weights = [w for w in (gpt_rel, sovits_rel) if not (engine_root / w).is_file()]
    if missing_weights:
        return CheckResult(
            cid,
            name,
            FAIL,
            f"权重文件丢失：{', '.join(missing_weights)}（按引擎根 {engine_root} 解析不存在）",
            "权重被移动/误删？恢复文件或确认新位置后重录基线。",
        )
    baseline_sha = str(baseline["yaml_sha256"]).strip().lower()
    actual_sha = hashlib.sha256(yaml_bytes).hexdigest()
    if actual_sha != baseline_sha:
        return CheckResult(
            cid,
            name,
            FAIL,
            f"yaml 被改：sha256 与基线漂移（现 {actual_sha[:12]}…，基线 {baseline_sha[:12]}…）——"
            "语义仍是守岸人（custom 两权重=shorekeeper 基线路径），多为 device/is_half 等合法回写（T53）",
            "先人工试听复核音色是否仍是守岸人；确属引擎合法回写后重录基线"
            "（更新 scripts/tts_voice_baseline.json 的 yaml_sha256），勿盲目重录掩盖真回退。",
        )
    return CheckResult(
        cid,
        name,
        PASS,
        f"音色正常：custom 两权重=守岸人基线（t2s={gpt_rel}、vits={sovits_rel}）且文件实存，"
        "yaml sha256 与基线一致",
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
        check_webui(project_root),
        check_control_plane(env),
        check_tts_voice_identity(env, project_root),
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
    verdict = "全绿，可以重启（先 SnowLuma 后 bot.py）" if n_fail == 0 else "存在 FAIL 项，先修再重启"
    lines.append(f"汇总: PASS {n_pass} / SKIP {n_skip} / FAIL {n_fail} → {verdict}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生产 bot 重启前置一键预检（10 项）")
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
