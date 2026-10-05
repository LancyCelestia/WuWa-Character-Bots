"""pre_restart_check — 生产 bot 重启前置一键预检（全绿才动手重启）.

背景：用户提权重启生产 bot（先 SnowLuma 后 bot.py）前，把散落多处的重启前置项
收敛为一个脚本；exit 0 = 可以动手，exit 1 = 有 FAIL 项先修。

检查项按下述编号在册（项数不另写死值：声明侧=本编号清单、机器侧=run_all 注册序，
两侧由 tests/test_pre_restart_check.py 与 tests/test_tts_identity_watch.py 的跟随锁
对账——写死过的总数每长一项红一片，历史 7→10→11→12→13 全部踩过这一雷）。
来源：A24 启动审计 / A45 wiki 健康 / A38 catalog 抽查 / 静态门 /
vector-audit 结论 / 2026-09-18 WebUI 能力面批 / T29 M-12 音色守望 /
T4 渠道能力标签保险 / T5 PX-1 MCP 模块保险 / S141 ANN 代际可用性）：
  1. env_paths     .env 关键路径存在性：BOT_KB_WIKI_ROOT / BOT_PERSONA_FILES /
                   BOT_MEDIA_ARCHIVE_DB_PATH 父目录 / qx.json（内置资产铁律）
  2. persona_sync  人格副本与锚定一致（sync_persona_source.py --check，
                   副本缺失=SKIP 不算红）+ 在册头像存在性点名（H-9d，同一格
                   第二判据）：只读扫 personas/registry/*.json 的非空
                   qq.avatar_path，按运行时数据根解析后核文件实存，缺件即
                   该格 FAIL 并点名确切路径（要落／按实申报未落两条出路）——
                   此前缺件要到下发腿才红（卡片腿 FileNotFoundError）
  3. hash_ledger   交付物 SHA-256 台账（tests/verify_hashes.py --check）
  4. doc_sync      机器事实册（scripts/doc_sync.py --check）
  5. kb_drift      知识库三漂移只读复核：ANN 行数 == chunks 行数
                   （sqlite 只读连接 + backup API 拷到 %TEMP% 查，不锁库）
  6. ruff          静态门：ruff check . 全绿
  7. napcat        协议端 SnowLuma WS 可达性探测：端点集合取自 .env 的
                   ONEBOT_WS_URLS（多账号=多端口，逐个探；只取 host:port，
                   令牌不进输出），解析不出时回落 127.0.0.1:3001
                   （只提示不阻断）
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
  11. channel_tags 渠道能力标签（native-audio/native-video/native-animation）
                   在册且在位：声明源 domains/core/channel_capability_tags.py
                   （AST 读，不 import 插件根）× 运行时注册表 JSON ×
                   .env BOT_MODEL_REGISTRY 三方对账，按「.env 同名条目遮蔽」
                   规则算出生效 tags。缺任一在册声明 = FAIL 并点名渠道与缺失
                   标签——能力标签消失既不报错也不写日志，只会让媒体理解静默
                   退回 ASR/抽帧（T4 路①②③的总闸）；
                   一处注册表都读不到=SKIP（开发/假环境不假红）。
  12. mcp_server_spec MCP stdio 服务端 `-m 目标` 模块在册且在位（PX-1 保险腿）：
                   只读 .env 的 MCP_SERVERS JSON（nonebot_plugin_mcpclient 直读、
                   不经 Config），对每条 type=stdio：args 含 -m <module> 时用
                   find_spec 探测（project_root 临时上 sys.path，不 import 插件根）；
                   缺件 = FAIL 并点名仓内同名真身建议改法。缺 command 也 FAIL
                   （client.py:76 运行期才 raise）。子进程 No module named 会被
                   chat.py 工具表负缓存静默吞掉 ⇒ 带工具退化成普通生成、不出诊断卡。
                   缺 .env / 键不在 / JSON 坏 / 空对象 = SKIP（诚实不假绿，也不假红）。
                   输出只报服务键名与模块名，绝不回显 command/env 里的凭据。
  13. ann_pair     ANN 这一代到底可不可用（S141 加，全只读、不 mmap 加载索引）：
                   按主键点查 ChatBot_Runtime/data/kb_wiki_embeddings.sqlite3 的
                   knowledge_meta 七行（完备性计数戳 ann_expected_vector_count /
                   代际证明 ann_pair_attestation(ntotal·count·signature·embed_generation) /
                   嵌入代次 ann_embed_generation /
                   ann_signature 与 embedding_signature / 内存门留痕
                   ann_build_last_memory_skip / 上一轮 kb_sync_last_summary），
                   照 load_ann_index 的查序（成对文件实存与体积 → 签名 → 计数戳短装
                   → 代次覆盖）比对得五态：PASS / REFUSED(missing=N / coverage) /
                   UNSTAMPED / MEMORY_SKIP(有内存门拒建留痕) / NOT_APPLICABLE(库或键缺失)。
                   键名与短装容差不在本文件另立一把尺（唯一真身=vector_knowledge.py，
                   由 tests/test_pre_restart_check_ann_pair.py 拿源码文本对账）。
                   零写库、零全表扫描、零 faiss；库/键不存在=SKIP，拒用=FAIL
                   （后果与第 5 项 kb_drift 同一条：每条消息回落暴力扫描）。
                   人话口径：结论一句 + 每个事实单独一行中文标签。
  14. kb_domain_anchor 库侧在册语料域 ↔ 本地域词表锚点（只点名不阻断）：两侧相减的
                   尺 ``kb_wiki.topics_without_local_domain_anchor`` 此前全仓只有
                   ``tests/test_kb_list_domain_gate.py`` 在读、运行期零消费方 ⇒ 新补
                   一个 KB 语料域而没人往本地域词表加锚点时没有任何人点名，缺口静默
                   存在（＝台账 #73「现实知识面」的复发机制）。本项把它接进中央出口，
                   **不新建第二把尺**：库侧主题（``iter_corpus_topic_names``）、
                   kb_dir（``kb_paths``）、相减、出格脱敏
                   （``plain_text.redact_local_secrets``）全走真身，本文件零集合运算；
                   尺按文件路径直载（插件根 ``__init__.py`` 是重件，第 11 项同一纪律），
                   临时登记的 sys.modules 条目在 finally 逐枚摘除。状态口径照第 7 项
                   napcat＝**报警不是阻断**（本项不产 FAIL、exit code 恒不变）：
                   无缺口=PASS；有缺口=SKIP 并逐域点名；库根未配置／尺装不上／
                   语料读不到主题=SKIP（读不到＝没有证据，绝不据此宣称没有缺口）。
                   接线由 ``tests/test_kb_domain_anchor_central_wiring.py`` 拿 AST
                   调用图锁住（含注毒自证：摘掉调用即红）。
  15. entry_chain 入口 import 链（重启到底「起不起得来」，SDD M2-44 的落地腿）：调
                   ``scripts/import_chain_probe.py``（缺省轴＝**当前工作树**，经
                   ``--root`` 指被测根）按**探针退出码＋结构化读数**定红绿——回显通篇报喜
                   也照 rc 判红、回显危言耸听也照 rc 判绿（本仓被骗过的那一型）；rc=0 只算
                   **必要**条件（2026-10-04 复核后收紧，失效形态 249）：读数解析不出 JSON
                   （空壳桩件／读数写到非 stdout）、``cells`` 一格没有（＝探针 setup 自己没
                   跑成；现算：解释器缺 nonebot 时它就报 rc=0「全链可导」）、或 ``cells`` 里
                   躺着 status=FAIL（退出码与自家读数相互矛盾）⇒ 一律属**没有证据**，判红
                   不判绿。缺件/超时/rc=2 同样 FAIL；本项自身不产 SKIP（拦的就是「按下重启」
                   那一下），但 INCONCLUSIVE＝环境缺席的格不改判红，只点名成「SKIP x{N}＋
                   格名」上屏——静默跳过证据的绿和放行的红是同一个谎。
                   同时把「这次重启会带走谁」当**数据**交付：``details`` 里给出
                   ``plugins/**`` 下 tracked-modified 模块的点分名清单与计数（porcelain
                   前两字符含 ``M`` 才算，未跟踪/删除/文档/脚本一概不进——它们不进运行时），
                   git 读不到时 ``working_tree_known=False`` 并写明原因，**绝不宣称
                   「没有改动」**（读不到＝没有证据，照第 7/14 项口径）。读不到含四形：
                   rc≠0／git 不在 PATH／``git status`` 挂过有界超时／采集面抛出——四形折成
                   **同一种**表示（禁第二表示法），且一律不外抛：本采集排在探针之前，
                   抛穿 ``run_all`` 就是顶穿 ``run-watch`` 的 loop 步＝看门狗自尽、永久 down。
                   为什么要这一格：入口链上任一**模块级求值**抛错 ⇒ nonebot 只记一条
                   error、``bot.py`` 崩溃守卫 ``raise`` ⇒ 插件全体不注册；
                   ``BOT_SUPERVISE=1`` 退避 5+15+60+60≈140 秒后永久 down。载体
                   （``ChatBot_Runtime\\restart_bot.ps1``）先杀后起、中间零判据，
                   本格＋任务表 ``restart-check`` 就是那道「杀之前先看一眼」的门。

用法：
  venv python scripts/pre_restart_check.py            # 人读表格
  venv python scripts/pre_restart_check.py --json     # 结构化输出
  venv python scripts/pre_restart_check.py --project-root <path>   # 供测试注入
  venv python scripts/pre_restart_check.py --only entry_chain      # 单格判定（restart-check 门）

.exit code：0 = 无 FAIL（PASS/SKIP 均放行）；1 = 有 FAIL；2 = 命令行本身不合法
（``--only`` 给了不在册的 id——静默少跑一项比红更糟）。
``--only`` 交出的表格/JSON 与退出码**只由被点名的在册项决定**：旁格红（ruff、文档账）
不该把「起得来」这条路一起堵死，反之亦然；全部项仍会跑一遍（注册面那几行的形状由
``tests/test_tts_identity_watch.py`` 与 ``tests/test_kb_domain_anchor_central_wiring.py``
的注毒锁钉住，改成惰性/闭包形状会让那两把锁的锚点静默失配＝锁变空腿）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import types
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NAPCAT_HOST = "127.0.0.1"
NAPCAT_PORT = 3001  # 仅回落值：现行端点集合由 ONEBOT_WS_URLS 决定（多账号=多端口）

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
    #: 结构化读数（``--json`` 消费方按这格现算，不参与判定）：历史上本文件只有一句话
    #: message，「这次重启会带走几枚在改模块」这类数只能靠人读字。第 15 项要把它当
    #: **数据**交付 ⇒ 加一枚默认空的字段，既有项一字不改（判定语义、退出码、表格形状全不动）。
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# .env 解析（M-68 收口：语义移交唯一入口 scripts/load_runtime_config.py——
# 生产同构 python-dotenv：行内注释剥离 + os.environ 优先 + 缺文件跳过。
# 本文件只保留 load_env 既有签名，作为值层消费方）
# ---------------------------------------------------------------------------

try:
    from scripts.load_runtime_config import load_runtime_env_values
except ImportError:  # 直跑态 sys.path[0]=scripts/：补仓库根后重试
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.load_runtime_config import load_runtime_env_values

# 渠道能力标签（T4）：声明源经 AST 读（插件根 __init__.py 是重件，体检不为几枚常量
# 去拉起 NoneBot），注册表只读取生效形态。取数口全在
# scripts/channel_capability_declaration.py，本文件不另立一份解析。
# 走到这里仓库根必已在 sys.path 上（上面那段 try/except 的两种结局都保证了这点），
# 故不再重复一遍兜底。
from scripts.channel_capability_declaration import (
    declaration_path,
    load_declaration,
    read_env_registry,
    read_registry_file,
    tags_of,
)


def load_env(project_root: Path) -> dict[str, str]:
    """读 .env / .env.prod 键值对（含 BOT_ 前缀配置），os.environ 优先.

    M-68 收口：解析语义移交唯一入口 scripts/load_runtime_config.py
    （与生产 bot.py:255 同构），本函数只适配既有签名（值层消费方：
    路径类键 / ONEBOT_WS_URLS / TTS 开关等原始字符串取值）。
    """
    return dict(
        load_runtime_env_values((".env", ".env.prod"), root=project_root).values
    )


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


def onebot_endpoints(env: dict[str, str]) -> list[tuple[str, int]]:
    """从 ONEBOT_WS_URLS 解析协议端点 host:port 全集（SnowLuma 多账号=多端口）.

    只取 host 与端口，access_token 一律不进结果与日志；解析不出任何端点时
    回落 (127.0.0.1, 3001)，保证单账号旧配置与新配置同口径。
    """
    raw = env.get("ONEBOT_WS_URLS", "").strip()
    items: list[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            items = [str(x) for x in parsed]
        else:
            items = [s.strip() for s in re.split(r"[;,]", raw) if s.strip()]
    endpoints: list[tuple[str, int]] = []
    for url in items:
        try:
            parts = urlparse(url)
            if parts.scheme not in {"ws", "wss"} or not parts.hostname:
                continue
            port = parts.port or (443 if parts.scheme == "wss" else 80)
        except ValueError:
            continue
        item = (parts.hostname, int(port))
        if item not in endpoints:
            endpoints.append(item)
    return endpoints or [(NAPCAT_HOST, NAPCAT_PORT)]


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
# 逐项检查（项数不在这里写死：在册清单＝本模块 docstring 的编号列表，见 declared_item_ids）
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


#: 人格册目录（在册格的唯一事实源；相对仓库根，与 persona_profile.DEFAULT_REGISTRY_DIR 同指）
PERSONA_REGISTRY_REL = Path("personas") / "registry"


def _persona_avatar_ledger(env: dict[str, str], project_root: Path) -> tuple[list[str], int, bool]:
    """只读点名「在册人格指向的头像文件」是否真实存在（H-9d 补牙）.

    返回 (问题行列表, 非空申报且已核的格数, 是否扫到册目录)。解析口径与下发腿同源：
    相对路径经运行时数据根（BOT_RUNTIME_DATA_DIR）重映射——见 resolve_data_path 与
    persona_profile 的头像解析函数，本函数不 import 插件根（本脚本既有纪律）。
    空 avatar_path＝「不切头像项」（§49.4-1），不算缺件；册目录读不到＝不假红。
    """
    registry = project_root / PERSONA_REGISTRY_REL
    if not registry.is_dir():
        return [], 0, False
    data_root = runtime_data_dir(env, project_root)
    problems: list[str] = []
    checked = 0
    for path in sorted(registry.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            problems.append(f"{path.name} 人格册不可读（{type(exc).__name__}）")
            continue
        if not isinstance(raw, dict):
            problems.append(f"{path.name} 人格册顶层不是对象")
            continue
        persona_id = str(raw.get("persona_id") or path.stem).strip() or path.stem
        qq = raw.get("qq")
        avatar_raw = str((qq.get("avatar_path") if isinstance(qq, dict) else "") or "").strip()
        if not avatar_raw:
            continue
        checked += 1
        target = resolve_data_path(avatar_raw, project_root, data_root)
        if not target.is_file():
            problems.append(f"{persona_id} 在册头像缺件: 册里 {avatar_raw} -> 盘上应有 {target}")
    return problems, checked, True


def check_persona_sync(env: dict[str, str], project_root: Path) -> CheckResult:
    cid, name = "persona_sync", "人格副本与锚定一致"
    rc, out, err = run_cmd(
        [sys.executable, "scripts/sync_persona_source.py", "--check"], project_root
    )
    sync_line = (out.strip() or err.strip()).splitlines()[-1] if (out.strip() or err.strip()) else ""
    avatar_problems, avatar_checked, registry_scanned = _persona_avatar_ledger(env, project_root)
    if not registry_scanned:
        avatar_note = "在册头像格未扫（人格册目录缺席，不假红）"
    elif avatar_problems:
        avatar_note = f"在册头像缺件 x{len(avatar_problems)}: " + " | ".join(avatar_problems)
    else:
        avatar_note = f"在册头像 x{avatar_checked} 实存（空 avatar_path＝不切头像项，不算缺件）"
    adopt_hint = (
        "人工审阅副本改动后 python scripts/sync_persona_source.py --adopt 重录锚定"
        "（误改先从备份恢复）；机制见 .superpowers/sdd/2026-09-13-six-domain-batch/"
        "persona-sync-report.md。"
    )
    avatar_hint = (
        "在册头像缺件两条出路（择一，不许悬空）：① 要落＝把真图放进上面点名的确切路径"
        "（相对路径按运行时数据根 BOT_RUNTIME_DATA_DIR 重映射，别只放源码树 data/）；"
        "② 按实申报未落＝把该格 qq.avatar_path 改回空串并在 _files_note 写明缺席，"
        "下发腿即跳过（不切头像、回执 skipped 而非 ok）。"
    )
    if rc == 0:
        skipped_copy = "[SKIP]" in out
        status = SKIP if skipped_copy else PASS
        detail = sync_line or ("副本缺失，门跳过" if skipped_copy else "副本与锚定一致")
        if avatar_problems:
            # 副本腿本身绿/跳过不掩盖头像缺件：这一格点名红
            return CheckResult(cid, name, FAIL, f"{detail} || {avatar_note}", avatar_hint)
        return CheckResult(cid, name, status, f"{detail}；{avatar_note}")
    detail = sync_line or f"exit {rc}"
    return CheckResult(
        cid,
        name,
        FAIL,
        f"{detail} || {avatar_note}" if avatar_problems else detail,
        f"{adopt_hint} {avatar_hint}" if avatar_problems else adopt_hint,
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
        "该任务（含 kb-sync 零变更夜）同时自愈 #47 完备性计数戳"
        "（certify_expected_vector_count，仅当无戳时补盖）；"
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
    # --no-cache（2026-10-02）：裸 ruff 每跑必往源码树根落 .ruff_cache/，把
    # runtime-layout 的 tool-cache 扫面打成 FAIL（当日两次假红实录）。门禁读数
    # 不需要缓存，直接禁掉。
    rc, out, err = run_cmd(
        [sys.executable, "-m", "ruff", "check", ".", "--no-cache"], project_root, timeout=600
    )
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


def check_napcat(endpoints: list[tuple[str, int]] | None = None) -> CheckResult:
    # 检查 id 仍叫 "napcat"（对外契约：文档/台账/前端按此 id 寻址），实体已是 SnowLuma。
    points = list(endpoints) if endpoints else [(NAPCAT_HOST, NAPCAT_PORT)]
    cid = "napcat"
    all_text = "、".join(f"{h}:{p}" for h, p in points)
    name = f"协议端 SnowLuma WS {all_text} 可达性（提示不阻断）"
    down = [f"{h}:{p}" for h, p in points if not probe_tcp(h, p)]
    if not down:
        return CheckResult(cid, name, PASS, f"{len(points)} 个端点全部可达（SnowLuma 在线）")
    return CheckResult(
        cid,
        name,
        SKIP,
        f"不可达: {'、'.join(down)}（共 {len(points)} 个端点）"
        "——若尚未启动 SnowLuma（或未在「进程注入」页点加载）属预期"
        "（bot 自带重连）；重启顺序：先 SnowLuma 后 bot.py",
        "装配指引见 docs/snowluma-setup.md（多账号每号一个 WS 端口，"
        "端口冲突处理见同文；旧端回滚见 docs/napcat-setup.md）。",
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
# 11. channel_tags：渠道能力标签（native-*）在册且在位
# ---------------------------------------------------------------------------

# 运行时注册表文件名形态（settings.py::InstanceSettingsManager._path_for 的口径）。
# 这里**不复制那份 _safe_name 正则**：实例名只用于拼文件名，含路径分隔符等可疑字符
# 时不拼、改走候选扫描——宁可少判也不越目录读人。
_SETTINGS_FILE_TEMPLATE = "runtime_settings_{instance}.json"
_SETTINGS_GLOB = "runtime_settings_*.json"
_INSTANCE_UNSAFE = ("/", "\\", "..", "*", "?", '"', "<", ">", "|", " ", "\n")


def effective_runtime_instance(env: dict[str, str]) -> tuple[str, str]:
    """本部署的运行时实例名：与 ``settings.effective_instance`` 同一条三级回落.

    ``BOT_RUNTIME_INSTANCE`` → ``BOT_PERSONA_PROFILE_ID``（人格 id 自举）→
    ``default``。**这条链不是可选项**：现网 ``BOT_RUNTIME_INSTANCE`` 就是空的，
    实例靠人格 id 自举成 ``shorekeeper``；只读第一级会去定位
    ``runtime_settings_default.json``（注册表为空）⇒ 本项在生产机上**假绿/假 SKIP**
    ——2026-09-24 真机只读跑第一版时就是这么暴露的。
    等价性由 ``tests/test_tag_presence_gate.py`` 与 ``effective_instance`` 互证锁住。
    """
    instance = str(env.get("BOT_RUNTIME_INSTANCE", "") or "").strip()
    if instance:
        return instance, "BOT_RUNTIME_INSTANCE"
    persona = str(env.get("BOT_PERSONA_PROFILE_ID", "") or "").strip()
    if persona:
        return persona, "BOT_PERSONA_PROFILE_ID（实例自举）"
    return "default", "缺省 default"


@dataclass(frozen=True)
class RegistryView:
    """三方对账所需的读取结果（全为只读取物，不含任何密钥值）."""

    live: dict[str, dict]          # 生效实例的注册表条目
    live_file: str                 # 生效文件名（"（未定位）" 时也有说明）
    note: str                      # 用了哪条定位规则
    env: dict[str, dict]           # .env BOT_MODEL_REGISTRY 条目
    siblings: dict[str, set[str]]  # 其它实例文件 -> 其中的条目 id（跨实例指认用）


def runtime_registry_view(env: dict[str, str], project_root: Path) -> RegistryView:
    """定位**生效实例**的注册表 JSON，并记下同目录其它实例（供指认）."""
    instance, rule = effective_runtime_instance(env)
    settings_raw = env.get("BOT_RUNTIME_SETTINGS_DIR", "").strip() or "data/settings"
    settings_dir = resolve_data_path(settings_raw, project_root, runtime_data_dir(env, project_root))
    if not settings_dir.is_dir():
        return RegistryView({}, "（无设置目录）", f"实例 {instance}（源:{rule}）；"
                            f"设置目录不存在（{settings_dir}）", {}, {})
    exact: Path | None = None
    if not any(bad in instance for bad in _INSTANCE_UNSAFE):
        candidate = settings_dir / _SETTINGS_FILE_TEMPLATE.format(instance=instance)
        exact = candidate if candidate.is_file() else None
    siblings: dict[str, set[str]] = {}
    for path in sorted(settings_dir.glob(_SETTINGS_GLOB)):
        if exact is not None and path == exact:
            continue
        siblings[path.name] = set(read_registry_file(path))
    if exact is not None:
        return RegistryView(
            read_registry_file(exact), exact.name, f"实例 {instance}（源:{rule}）",
            read_env_registry(env), siblings,
        )
    only = [path for path in sorted(settings_dir.glob(_SETTINGS_GLOB))]
    if len(only) == 1:  # 单实例部署：文件名不匹配也用唯一候选（并写明）
        return RegistryView(
            read_registry_file(only[0]), only[0].name,
            f"实例 {instance}（源:{rule}）无同名文件，回落唯一候选", read_env_registry(env), {},
        )
    return RegistryView(
        {}, "（未定位）", f"实例 {instance}（源:{rule}）推不出文件，"
        f"同目录候选 x{len(only)}：{('、'.join(p.name for p in only)) or '（无）'}",
        read_env_registry(env), siblings,
    )


def check_channel_capability_tags(env: dict[str, str], project_root: Path) -> CheckResult:
    """第 11 项：渠道能力标签在册且在位（T4 三条静默抹标签路的总闸）.

    判据（**PASS 只在每条在册能力声明都真的落在生效 tags 上时才给**）：
      · 声明源 = `domains/core/channel_capability_tags.py`（AST 读，不 import 插件根）；
      · 生效 tags 按「.env 同名条目遮蔽」规则算，与 `model_router`
        `_spec_from_dynamic_entry` / `runtime_admin._merge_registry_entries` 同语义：
        `.env` 有同名条目时，运行时 tags 只有被 `override_fields` 认领才存活；
      · 一处注册表都读不到（无文件、无 .env 条目）= SKIP（开发/假环境，不假红）；
        有注册表但在册渠道缺席 = FAIL。
    输出只出现渠道 id、标签字面量与 `env:` 槽名，绝不出现任何密钥值。
    """
    cid, name = "channel_tags", "渠道能力标签（native-*）在册且在位"
    # 声明源是**代码**，注册表是**部署数据**：`--project-root` 换的是后者。
    # 假项目根里没有源码 ⇒ 回落到本脚本所在的仓库根（真实部署下两者同一路径，
    # 回落永不触发；触发了也只是读到同一份声明，不会放行错的东西）。
    declaration_root = project_root if declaration_path(project_root).is_file() else PROJECT_ROOT
    try:
        declaration = load_declaration(declaration_root)
    except (OSError, ValueError) as exc:
        return CheckResult(
            cid, name, FAIL, f"能力标签声明源不可读：{exc}",
            "声明源=plugins/bot_unified_runtime/domains/core/channel_capability_tags.py；"
            "它读不出来时本项无从判定，宁可红也不放行。",
        )
    declared = {
        entry_id: declaration.required_tags_for(entry_id)
        for entry_id in declaration.declared_entry_ids()
    }
    declared = {entry_id: tags for entry_id, tags in declared.items() if tags}
    if not declared:
        return CheckResult(cid, name, SKIP, "声明源未在册任何能力标签——无可校验项")

    view = runtime_registry_view(env, project_root)
    env_registry = view.env
    if not view.live and not env_registry and not view.siblings:
        return CheckResult(
            cid,
            name,
            SKIP,
            f"运行时注册表与 BOT_MODEL_REGISTRY 都不存在——没有渠道可挂能力标签（{view.note}；"
            f"文件 {view.live_file}）",
            "确认 BOT_RUNTIME_SETTINGS_DIR / BOT_RUNTIME_INSTANCE / BOT_PERSONA_PROFILE_ID "
            "是否指向本部署；若渠道确已迁走，改那份声明源而不是放宽本项。",
        )

    problems: list[str] = []
    for entry_id, required in sorted(declared.items()):
        runtime_entry = view.live.get(entry_id)
        env_entry = env_registry.get(entry_id)
        if runtime_entry is None and env_entry is None:
            where = sorted(name for name, ids in view.siblings.items() if entry_id in ids)
            detail = (
                f"，但它在同目录这些实例文件里：{'、'.join(where)}"
                f"——本项按 {view.note} 判生效实例，读的是 {view.live_file}；"
                "指错了实例就等于对本部署完全瞎眼"
                if where
                else "（生效实例文件与 BOT_MODEL_REGISTRY 两侧都查过）"
            )
            problems.append(
                f"{entry_id} 在册要求 {'、'.join(required)}，但生效注册表里没有这条渠道{detail}"
            )
            continue
        if env_entry is not None:
            claimed = "tags" in {str(f) for f in (runtime_entry or {}).get("override_fields") or ()}
            effective = tags_of(runtime_entry) if claimed else tags_of(env_entry)
            origin = (
                f"{view.live_file} 的运行时覆盖（override_fields 已认领 tags）"
                if claimed
                else ".env BOT_MODEL_REGISTRY"
            )
            shadow_note = (
                ""
                if claimed
                else "；.env 同名条目正整条遮蔽运行时 tags（未被 override_fields 认领）"
            )
        else:
            effective = tags_of(runtime_entry)
            origin = view.live_file
            shadow_note = ""
        have = {str(tag).strip().lower() for tag in effective}
        missing = [tag for tag in required if tag.lower() not in have]
        if missing:
            problems.append(
                f"{entry_id} 生效 tags（源:{origin}）缺能力标签 {'、'.join(missing)}"
                f"——在册要求 {'、'.join(required)}{shadow_note}"
            )

    if problems:
        return CheckResult(
            cid,
            name,
            FAIL,
            "；".join(problems),
            "能力标签消失**不报错、不写日志**，只会让音视频/动图静默退回 ASR/抽帧/拼静态条。"
            "三条会抹掉它的路与各自修法：① 重跑 scripts/configure_axonhub_registry.py --apply"
            "（tags 列只写档位，能力标签由 tags_for() 合成，写回前有 capability_guard_problems() 闸）；"
            "② /bot model update <id> tags=…（整表替换只换档位，能力标签自动保留并在回复里点名）；"
            "③ .env 回填同名 BOT_MODEL_REGISTRY 条目（会整条遮蔽运行时 tags，除非该条目在运行时侧"
            "把 tags 写进 override_fields）。摘牌请改声明源 "
            "plugins/bot_unified_runtime/domains/core/channel_capability_tags.py，别改副本。",
        )
    ok = "；".join(f"{entry_id}={','.join(declared[entry_id])}" for entry_id in sorted(declared))
    source = f"{view.live_file}（{view.note}，运行时条目 x{len(view.live)}）"
    if env_registry:
        source += f"；BOT_MODEL_REGISTRY 条目 x{len(env_registry)}"
    return CheckResult(
        cid, name, PASS, f"{len(declared)} 条在册能力声明全部在位：{ok}（注册表源：{source}）"
    )


# ---------------------------------------------------------------------------
# 12. mcp_server_spec：MCP stdio 服务端的 `-m <模块>` 指向的模块是否还在
# ---------------------------------------------------------------------------

# MCP_SERVERS 由 nonebot_plugin_mcpclient 直读（不经 Config，`extra=ignore` 也管不到它），
# 是一张 JSON 表：{"<id>": {"type":"stdio","command":...,"args":[...],"env":{...}}}。
# 某条 stdio 服务端若以 `python -m <module>` 起、而 <module> 已从 tree 里消失，子进程会以
# "No module named" 退出 ⇒ 被 chat.py 的工具表负缓存（_mcp_tools_schema_negative_until）
# 静默吞掉 ⇒ 带工具的模型循环退化成普通生成，不出诊断卡、不告警。
# 2026-09-24 实锤：她的「存档」提交 ebb7130 把 `sources/mcp_web_search_server` 垫片从 tree
# 带走，而 .env 的 MCP_SERVERS 还指着 `plugins.bot_unified_runtime.sources.mcp_web_search_server`。
# 本项在重启前把它挑出来：只报服务键名与模块名、并点名仓内同名真身，绝不回显任何值里的凭据。
_MCP_SERVERS_ENV_KEY = "MCP_SERVERS"
_MCP_SCAN_DIRS: tuple[str, ...] = ("plugins", "scripts")


def _stdio_module_from_args(args: object) -> str | None:
    """从 stdio 的 args 里取出 `-m <module>` 形态的模块名；非该形态返回 None。"""
    if not isinstance(args, list):
        return None
    for i, tok in enumerate(args):
        if tok == "-m" and i + 1 < len(args):
            nxt = args[i + 1]
            if isinstance(nxt, str) and nxt.strip():
                return nxt.strip()
    return None


def _module_available(module: str, project_root: Path) -> bool:
    """find_spec 判模块能否解析——不执行 import、不拉起插件根。

    现网是 `python -m <module>`（子进程 cwd=仓库根），故把 project_root 临时上到 sys.path，
    让仓内 `plugins.*` 模块按同口径可解析。父包整体缺失时 find_spec 会抛 ModuleNotFoundError
    （实测：`find_spec('definitely.not.a.real.module')` → 抛；`find_spec('…sources.…')` 垫片缺失 → None），
    两种形态都归为「不可用」。
    """
    root_str = str(project_root)
    inserted = root_str not in sys.path
    if inserted:
        sys.path.insert(0, root_str)
    try:
        import importlib.util

        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
    finally:
        if inserted:
            try:
                sys.path.remove(root_str)
            except ValueError:
                pass


def _find_module_home(module: str, project_root: Path) -> str | None:
    """在仓内找同名真身：拿模块末段当文件名，在 plugins/ scripts/ 下搜 `<leaf>.py`
    或包目录 `<leaf>/__init__.py`，按相对路径反推点分模块名。允许命名空间包
    （本仓顶层 `plugins/` 就没有 `__init__.py`，靠隐式命名空间被 `python -m` 解析）。
    返回第一个非自身的候选，找不到 None。"""
    leaf = module.rsplit(".", 1)[-1]
    if not leaf or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", leaf):
        return None
    candidates: list[str] = []
    for sub in _MCP_SCAN_DIRS:
        base = project_root / sub
        if not base.is_dir():
            continue
        for hit in base.rglob(leaf + ".py"):
            candidates.append(".".join(hit.relative_to(project_root).with_suffix("").parts))
        for pkg in base.rglob(leaf):
            if pkg.is_dir() and (pkg / "__init__.py").is_file():
                candidates.append(".".join(pkg.relative_to(project_root).parts))
    real = [c for c in candidates if c and c != module]
    return min(real) if real else None


def check_mcp_server_spec(env: dict[str, str], project_root: Path) -> CheckResult:
    """第 12 项：MCP stdio 服务端的 `-m 目标` 模块是否还在（PX-1 的重启前保险腿）.

    判据（PASS 只在每条在册 stdio 的 `-m` 目标都可解析、且 command 非空时才给）：
      · 读 .env 的 MCP_SERVERS JSON（只读，绝不回显值里的凭据）；
      · 缺 `.env` / 键不在 / JSON 坏 / 空对象 = SKIP（开发/假环境不假红，也不假绿）；
      · `type=="stdio"` 且 args 含 `-m <module>`：find_spec 不到 = FAIL 并点名仓内同名真身；
      · `type=="stdio"` 缺 command = FAIL（client.py:76 运行期才 raise，提前挑出）。
    输出只出现服务键名与模块名，绝不出现 command / env / 任何密钥值。
    """
    cid, name = "mcp_server_spec", "MCP stdio 服务端 `-m 目标` 模块在册且在位"
    raw = env.get(_MCP_SERVERS_ENV_KEY)
    if raw is None or not str(raw).strip():
        return CheckResult(
            cid, name, SKIP,
            "未配置 MCP_SERVERS（.env.example 缺省 {}）——没有 stdio 服务端可校验",
        )
    try:
        servers = json.loads(str(raw))
    except (ValueError, TypeError):
        return CheckResult(
            cid, name, SKIP,
            "MCP_SERVERS 不是合法 JSON——本项读不出服务端清单，诚实跳过不假绿；请核对 .env 里该键的 JSON。",
        )
    if not isinstance(servers, dict) or not servers:
        return CheckResult(cid, name, SKIP, "MCP_SERVERS 为空对象——没有 stdio 服务端可校验")

    problems: list[str] = []
    for sid, cfg in sorted(servers.items(), key=lambda kv: str(kv[0])):
        if not isinstance(cfg, dict):
            continue
        if str(cfg.get("type", "")).strip().lower() != "stdio":
            continue
        command = cfg.get("command")
        if not (isinstance(command, str) and command.strip()):
            problems.append(f"{sid}：type=stdio 但缺 command（运行期 client.py:76 会 raise ValueError）")
            continue
        module = _stdio_module_from_args(cfg.get("args"))
        if module is None:
            continue
        if _module_available(module, project_root):
            continue
        home = _find_module_home(module, project_root)
        if home:
            problems.append(
                f"{sid}：python -m {module} 指向不存在的模块；"
                f"仓内同名真身疑似 {home}（把该条 args 的 -m 目标改成它——本项只点名不改，PX-1 待用户裁定）"
            )
        else:
            problems.append(f"{sid}：python -m {module} 指向不存在的模块（仓内未找到同名真身）")

    if problems:
        return CheckResult(
            cid, name, FAIL, "；".join(problems),
            "stdio 子进程会以 No module named 退出，被 chat.py 工具表负缓存静默吞掉 ⇒ "
            "带工具的模型循环退化成普通生成、不出诊断卡也不告警。改法：把 .env 的 MCP_SERVERS 里该条 "
            "args 的 -m 目标改成仓内真身模块名（本项只点名不改；PX-1 的 A/B/C 尚未裁定）。",
        )
    return CheckResult(cid, name, PASS, "所有在册 stdio MCP 服务端的 -m 目标模块都可解析")


# ---------------------------------------------------------------------------
# 13. ann_pair：ANN 这一代到底可不可用（S141，2026-09-26；全只读，不加载索引）
# ---------------------------------------------------------------------------
# 为什么要这一项：2026-09-22 那次停摆的根因就是「ANN 索引短装 ⇒ 每条消息回落
# numpy 暴力扫描」，而它**既不报错也不写日志**，只在重启后靠日志考古才发现。
# 本项把同一道判据搬到重启之前：只读 `knowledge_meta` 的七行（计数戳 / 代际证明 /
# 嵌入代次 / 上一轮 kb-sync 摘要）+ 内存门留痕 + 两枚签名行，比对得五态之一。
#
# 判据不许有第二把尺（AGENTS.md 规则：一处变更处处跟随）：
#   · 键名与短装容差逐字对住真身
#     `plugins/bot_unified_runtime/domains/chat_reply/character/vector_knowledge.py`
#     （`_EMBEDDED_COUNT_KEY` / `_ANN_ATTESTATION_KEY` / `_ANN_MEMORY_SKIP_META_KEY` /
#     `_ANN_COMPLETENESS_MAX_MISSING` / `_EMBED_GENERATION_KEY` /
#     `_ATTEST_EMBED_GENERATION_FIELD`）与 `domains/location/knowledge/kb_wiki.py`
#     （`SYNC_SUMMARY_META_KEY`），由
#     `tests/test_pre_restart_check_ann_pair.py::test_ann_pair_keys_and_threshold_match_single_source`
#     拿源码文本对账——任何一侧改名即红；
#   · 语义同真身：戳 = 「本代索引至少该装几条」的**上界**，`ntotal < 戳` 才是短装，
#     `ntotal > 戳`（发布中途被杀）不算（load_ann_index 同判）；
#   · 代次闸照 S159 真身判（load_ann_index 的代次终检）：当前嵌入代次
#     （`ann_embed_generation`）> 代际证明盖章代次（其 `embed_generation` 字段）
#     ⇒ 覆盖没跟上——删+嵌同轮会把标量戳拉回原值，戳判看不出这形 ⇒
#     REFUSED(coverage)，两个数字同屏点名。缺行/畸形/负值按 0 读，与真身
#     `_parse_embed_generation` 同口径；存量库两侧俱缺 ⇒ 0 对 0，既有放行语义
#     逐字节不变（设计形态，锁钉住，不许在这里改口）；
#   · 本项**不 mmap 读 `.index`**（那是重启后要付的 ≈1 秒），ntotal 取代际证明里的数，
#     并另 stat 两枚 ANN 文件核体积——「证明自洽而磁盘没东西」是假绿，必须挑出来。
# 零写库、零全表扫描：只按 PRIMARY KEY 点查 knowledge_meta，绝不碰 knowledge_chunks
# （那张表上 `COUNT(*) WHERE vector_json IS NOT NULL` 真身注释实测 23.8s）。

ANN_DB_ENV_KEY = "BOT_KB_WIKI_DB_PATH"
DEFAULT_KB_WIKI_DB = "data/kb_wiki_embeddings.sqlite3"
# ANN 两文件与库同目录同名（真身：kb_wiki.py::build_store 的 with_name 两行）
KB_WIKI_ANN_INDEX_NAME = "kb_wiki_faiss.index"
KB_WIKI_ANN_ORDER_NAME = "kb_wiki_faiss.order.json"

ANN_STAMP_META_KEY = "ann_expected_vector_count"
ANN_ATTESTATION_META_KEY = "ann_pair_attestation"
ANN_SIGNATURE_META_KEY = "ann_signature"
ANN_EMBEDDING_SIGNATURE_META_KEY = "embedding_signature"
ANN_MEMORY_SKIP_META_KEY = "ann_build_last_memory_skip"
ANN_SUMMARY_META_KEY = "kb_sync_last_summary"
ANN_EMBED_GENERATION_META_KEY = "ann_embed_generation"  # 真身 _EMBED_GENERATION_KEY
ANN_ATTEST_EMBED_GENERATION_FIELD = "embed_generation"  # 真身 _ATTEST_EMBED_GENERATION_FIELD

ANN_COMPLETENESS_MAX_MISSING = 0  # 真身 _ANN_COMPLETENESS_MAX_MISSING：一条都不许少

_ANN_META_KEYS: tuple[str, ...] = (
    ANN_STAMP_META_KEY,
    ANN_ATTESTATION_META_KEY,
    ANN_SIGNATURE_META_KEY,
    ANN_EMBEDDING_SIGNATURE_META_KEY,
    ANN_MEMORY_SKIP_META_KEY,
    ANN_SUMMARY_META_KEY,
    ANN_EMBED_GENERATION_META_KEY,
)

ANN_STATE_PASS = "PASS"
ANN_STATE_REFUSED = "REFUSED"
ANN_STATE_UNSTAMPED = "UNSTAMPED"
ANN_STATE_MEMORY_SKIP = "MEMORY_SKIP"
ANN_STATE_NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class AnnPairVerdict:
    """ANN 这一代的可用性判决（五态之一 + 逐行事实，呈现层不另算判据）."""

    state: str
    reason: str
    headline: str
    facts: tuple[str, ...]
    fix_hint: str
    missing: int | None = None


def _ann_meta_rows(db_path: Path) -> dict[str, str] | None:
    """按主键点查 knowledge_meta 的七行（只读 URI，不建库、不写、不抢写锁）.

    打不开 / 表不存在 ⇒ None（调用方按「无从判定」走 NOT_APPLICABLE，
    绝不猜默认值——猜 0 会把「无从证明完备」洗成「一行都不该有 ⇒ 完美」）。
    """
    try:
        con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        placeholders = ",".join("?" for _ in _ANN_META_KEYS)
        rows = con.execute(
            f"SELECT key, value FROM knowledge_meta WHERE key IN ({placeholders})",
            _ANN_META_KEYS,
        ).fetchall()
    except sqlite3.Error:  # 含 no such table: knowledge_meta
        return None
    finally:
        con.close()
    return {str(k): "" if v is None else str(v) for k, v in rows}


def _ann_json_row(raw: str) -> dict[str, object] | None:
    """meta 里的 JSON 行：缺/坏/非对象一律 None（不猜内容）."""
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _ann_int(value: object) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _ann_generation_value(value: object) -> int:
    """代次取数口径同真身 `_parse_embed_generation`：缺行/畸形/负值 ⇒ 0.

    与 `_ann_int`（计数戳口径）故意不同：戳缺行返回 None 是「无从判定」，
    代次缺行返回 0 是「从未证过任何提交批次」——方向更严，任何一批嵌入都会
    把它顶到 1 以上 ⇒ 守卫开火；存量库两侧同时缺行 ⇒ 0 对 0，与闸上线前
    逐字节同形（真身 `_EMBED_GENERATION_KEY` 参数块在册，不在这里改口）。
    取值先 `str()` 再解析，`True` 这类布尔垃圾只会折成 0，读不成「已证过一批」。
    """
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _ann_sig_head(value: str) -> str:
    """签名进输出时压短（它是端点+模型名拼接的长串，逐字上屏读不动）."""
    trimmed = value.strip()
    if not trimmed:
        return "（空）"
    return trimmed if len(trimmed) <= 40 else f"{trimmed[:36]}…（{len(trimmed)} 字）"


def inspect_ann_generation_pair(env: dict[str, str], project_root: Path) -> AnnPairVerdict:
    """读 knowledge_meta 七行 → 五态之一（PASS / REFUSED / UNSTAMPED / MEMORY_SKIP / NOT_APPLICABLE）.

    状态优先级（**根因赢，但被抢的状态一个字不藏**：短装数、戳、ntotal、代次全都进事实行）：
      1. NOT_APPLICABLE：库不存在 / 表不存在 / 戳与代际证明两行都没有 ⇒ 无从判定（SKIP）；
      2. 先算「这一代能不能用」的坏判据（按真身 load_ann_index 的查序）：
         两文件缺席或体积与证明不符 → 签名不符 → 无戳 → 短装（ntotal < 戳 − 容差）
         → 代次超前（当前代次 > 盖章覆盖，S159 代次终检同判）；
      3. 有坏判据 **且** 内存门留痕在位且未越门 ⇒ MEMORY_SKIP（这就是「为什么没重建」）；
      4. 否则坏判据本身 ⇒ REFUSED / UNSTAMPED；全部通过 ⇒ PASS。
    """
    raw_db = env.get(ANN_DB_ENV_KEY, "").strip() or DEFAULT_KB_WIKI_DB
    data_root = runtime_data_dir(env, project_root)
    db_path = resolve_data_path(raw_db, project_root, data_root)
    if not db_path.is_file():
        return AnnPairVerdict(
            ANN_STATE_NOT_APPLICABLE,
            "db_absent",
            f"ANN 这一代可用性不适用：wiki 向量库不存在（{db_path}）",
            ("库路径：" + str(db_path), "计数戳：无从判定", "代际证明：无从判定"),
            f"确要启用百科向量库：.env 配 {ANN_DB_ENV_KEY} 指向实存库，"
            "或先跑一次 knowledge-sync 建库（本项不建库、不写库）。",
        )
    rows = _ann_meta_rows(db_path)
    if rows is None:
        return AnnPairVerdict(
            ANN_STATE_NOT_APPLICABLE,
            "meta_unreadable",
            f"ANN 这一代可用性无从判定：{db_path.name} 的 knowledge_meta 读不出来",
            ("库路径：" + str(db_path), "计数戳：无从判定", "代际证明：无从判定"),
            "库被占用/损坏？只读方式人工确认一下（本项绝不写库、绝不建表）。",
        )

    stamp = _ann_int(rows.get(ANN_STAMP_META_KEY, ""))
    stamp_raw = rows.get(ANN_STAMP_META_KEY, "").strip()
    attestation = _ann_json_row(rows.get(ANN_ATTESTATION_META_KEY, ""))
    attested_sig = str((attestation or {}).get("signature") or "")
    stored_sig = rows.get(ANN_SIGNATURE_META_KEY, "").strip()
    embedding_sig = rows.get(ANN_EMBEDDING_SIGNATURE_META_KEY, "").strip()
    memory_skip = _ann_json_row(rows.get(ANN_MEMORY_SKIP_META_KEY, ""))
    summary = _ann_json_row(rows.get(ANN_SUMMARY_META_KEY, ""))
    ntotal = _ann_int((attestation or {}).get("ntotal")) if attestation else None
    attested_count = _ann_int((attestation or {}).get("count")) if attestation else None
    embed_generation = _ann_generation_value(rows.get(ANN_EMBED_GENERATION_META_KEY, ""))
    attested_generation = _ann_generation_value(
        (attestation or {}).get(ANN_ATTEST_EMBED_GENERATION_FIELD)
    )

    if stamp is None and attestation is None and not stamp_raw and not attested_sig:
        return AnnPairVerdict(
            ANN_STATE_NOT_APPLICABLE,
            "no_ann_generation_evidence",
            "ANN 这一代可用性不适用：库里既无计数戳也无代际证明（从未建过 ANN）",
            (
                "库路径：" + str(db_path),
                "计数戳：缺失",
                "代际证明：缺失",
            ),
            "跑一次 knowledge-sync（或 scripts/smoke 的建索引路径）建出第一代，"
            "本项从那一刻起才有账可对。",
        )

    # --- 事实行（每个事实单独一行中文标签，与运行时告警同口径）-------------
    facts: list[str] = [
        "计数戳：" + ("缺失（无从判定）" if stamp is None else str(stamp)),
        "代际证明 ntotal：" + ("缺失" if ntotal is None else str(ntotal)),
        "代际证明 count：" + ("缺失" if attested_count is None else str(attested_count)),
    ]
    missing: int | None = None
    if stamp is not None and ntotal is not None:
        missing = stamp - ntotal
        if missing > ANN_COMPLETENESS_MAX_MISSING:
            facts.append(f"短装行数：{missing}")
        elif missing == 0:
            facts.append("短装行数：0")
        else:
            # 反向多出向量不算短装（真身 load_ann_index 同判：那是发布中途被杀的
            # 残态，索引本身是完整的）——但仍要报出来，别让它看着像"刚好齐平"。
            facts.append(
                f"短装行数：0（ntotal 比戳多 {abs(missing)} 条：发布中途被杀的残态，"
                "索引本身完整，真身同判不算短装）"
            )

    bad_reason = ""
    if attestation is None:
        bad_reason = "no_attestation"
        facts.append("代际证明：缺失（无证明 = 无从证实这一代成对换入过）")
        facts.append(
            f"嵌入代次：当前 {embed_generation}（代际证明缺席，无从比对盖章代次；"
            "真身同格判据是「证明缺席且代次非零 ⇒ 照拒」，本项由 no_attestation 这发先红）"
        )
    else:
        index_path = db_path.parent / KB_WIKI_ANN_INDEX_NAME
        order_path = db_path.parent / KB_WIKI_ANN_ORDER_NAME
        index_size = index_path.stat().st_size if index_path.is_file() else None
        order_size = order_path.stat().st_size if order_path.is_file() else None
        attested_index = _ann_int(attestation.get("index_bytes"))
        attested_order = _ann_int(attestation.get("order_bytes"))
        if index_size is None or order_size is None:
            bad_reason = "pair_files_absent"
            facts.append(
                f"ANN 文件：缺席（{KB_WIKI_ANN_INDEX_NAME}="
                f"{'在位' if index_size is not None else '无'}、"
                f"{KB_WIKI_ANN_ORDER_NAME}={'在位' if order_size is not None else '无'}）"
                "⇒ 载入路径必然拒用（本项不 mmap 读索引，只看实存与体积）"
            )
        elif (
            attested_index is not None and index_size != attested_index
        ) or (attested_order is not None and order_size != attested_order):
            bad_reason = "pair_files_inconsistent"
            facts.append(
                f"ANN 文件：体积与代际证明不符（实测 index={index_size}、order={order_size}；"
                f"证明 index_bytes={attested_index}、order_bytes={attested_order}）⇒ 半写/换过代"
            )
        else:
            facts.append(
                f"ANN 文件：两枚在位且体积与代际证明相符（index={index_size} B、order={order_size} B）"
            )
        if not attested_sig:
            bad_reason = bad_reason or "attestation_without_signature"
            facts.append("代际签名：证明里没有签名字段（无从比对）")
        elif stored_sig and attested_sig != stored_sig:
            bad_reason = bad_reason or "signature_mismatch"
            facts.append(
                f"代际签名：与库内 {ANN_SIGNATURE_META_KEY} 不符"
                f"（证明 {_ann_sig_head(attested_sig)} ／ 库内 {_ann_sig_head(stored_sig)}）"
                "⇒ 这一代索引不是当前 embedding 模型建的"
            )
        elif stored_sig and embedding_sig and stored_sig != embedding_sig:
            bad_reason = bad_reason or "signature_mismatch"
            facts.append(
                f"代际签名：与库内 {ANN_SIGNATURE_META_KEY} 一致，但库内两枚签名行自相矛盾"
                f"（{ANN_EMBEDDING_SIGNATURE_META_KEY}={_ann_sig_head(embedding_sig)}）"
            )
        else:
            facts.append("代际签名：与库内 ann_signature 一致")

    if missing is not None and missing > ANN_COMPLETENESS_MAX_MISSING:
        bad_reason = bad_reason or "short_by_stamp"

    # 代次终检（S159，照真身 load_ann_index 的查序排在计数戳判之后）：删+嵌同轮
    # 会把标量戳拉回原值，戳追平了也可能根本没装下新那批——覆盖要按代次判：
    # 当前代次 > 证明盖章代次 ⇒ 载入必然拒用（coverage refused），预检不许假 PASS。
    # 证明缺席时本判 inert：`no_attestation` 在上面已判红（真身另有一发
    # 「证明缺席+代次非零即拒」同样落进那格红里，判据只严不松）。
    if attestation is not None:
        coverage_behind = embed_generation > attested_generation
        facts.append(
            f"嵌入代次：当前 {embed_generation} ／ 证明盖章代次 {attested_generation}"
            + ("（代次超前：盖章点之后又有嵌入批次提交，本代索引没装下）"
               if coverage_behind else "")
        )
        if coverage_behind:
            bad_reason = bad_reason or "coverage_behind_generation"

    # kb-sync 摘要行（收工判据：行数不是判据，看 ann_reason / embed_pending）
    if summary is None:
        facts.append("上一轮 kb-sync：无收工摘要（这一轮从未跑完过）")
    else:
        built = summary.get("ann_rebuilt")
        if built is None:
            built = summary.get("ann_built")  # 结果字典里的旧名，兼容读一眼
        facts.append(
            "上一轮 kb-sync："
            f"ann_reason={summary.get('ann_reason', '')}，ann_rebuilt={built}，"
            f"embed_pending={summary.get('embed_pending', '')}，"
            f"embedded_after={summary.get('embedded_after', '')}，"
            f"chunks_after={summary.get('chunks_after', '')}"
        )

    skip_forced = bool((memory_skip or {}).get("forced"))
    skip_reason = ""
    if memory_skip is None:
        facts.append("内存门留痕：无")
    else:
        skip_reason = (
            "memory_probe_unavailable"
            if memory_skip.get("probe_failed")
            else "insufficient_memory"
        )
        # S139 缺陷 1+3+4 跟随：①口径——floor 那枚是 S85 标定合价、不是绝对下限
        # （真身 _ANN_BUILD_MIN_AVAILABLE_BYTES 注释同口径）；②规模点名条数；
        # ③累计计数（consecutive/total）随行——S139 起由 `_record_ann_memory_skip`
        # 写入同一枚 meta，本行只读不算（第二把尺禁）。
        facts.append(
            "内存门留痕："
            + ("上一轮显式越门开火（--ann-force-low-memory）" if skip_forced else "上一轮 ANN 重建被挡（未越门）")
            + f"（可用 {memory_skip.get('available', '?')} < 需要 {memory_skip.get('required', '?')}"
            + f"，规模 {memory_skip.get('expected_vectors', '?')} 条 × "
            + f"dim={memory_skip.get('dim', '?')}，标定合价 {memory_skip.get('floor', '?')}"
            + "（S85 标定值、非绝对下限），"
            + f"连续被挡 {memory_skip.get('consecutive_skips', '?')} 轮"
            + f"/累计 {memory_skip.get('total_skips', '?')} 轮，"
            + f"阶段 stage={memory_skip.get('stage', '?')}，at_unix={memory_skip.get('at_unix', '?')}）"
        )

    # --- 定态 ---------------------------------------------------------------
    # 查序照 load_ann_index：签名/成对性在前，完备性戳与代次覆盖在最后 ⇒ 已判坏就不改口。
    if attestation is not None and stamp is None:
        bad_reason = bad_reason or "unstamped"
    if bad_reason == "":
        return AnnPairVerdict(
            ANN_STATE_PASS,
            "ok",
            "这一代 ANN 可用：索引装满了计数戳声明的向量数，签名与成对性都对得上"
            "（重启后走向量通道，不再逐条消息付暴力扫描）",
            tuple(facts),
            "",
            missing=missing,
        )
    if bad_reason == "unstamped":
        return AnnPairVerdict(
            ANN_STATE_UNSTAMPED,
            "unstamped",
            "这一代 ANN 不可用：有代际证明却没有完备性计数戳（无戳 ⇒ 无从证明装满了每一行）"
            "⇒ 载入路径拒用 ANN，每条消息回落暴力扫描",
            tuple(facts),
            "跑一次 knowledge-sync 的认证落戳路径（certify_expected_vector_count，"
            "无戳时才补盖）；判据与容差唯一真身见 vector_knowledge.py 的 "
            "_EMBEDDED_COUNT_KEY / _ANN_COMPLETENESS_MAX_MISSING（本项不另立一把尺）。",
        )
    if memory_skip is not None and not skip_forced and bad_reason != "":
        return AnnPairVerdict(
            ANN_STATE_MEMORY_SKIP,
            skip_reason or "insufficient_memory",
            "这一代 ANN 不可用，且原因有账：上一轮重建被内存门挡下没开火 ⇒ 新嵌入的行没进索引"
            "⇒ 载入路径拒用 ANN，每条消息回落暴力扫描",
            tuple(facts) + (f"不可用判据：{bad_reason}",),
            "内存门是刻意的（低内存硬跑会把 bot 连人带库压死）：先让空闲物理内存回到需求之上"
            "再跑 knowledge-sync 重建；确要低内存硬跑用 operator CLI 的 --ann-force-low-memory"
            "（越门本身另留痕）。闸语义与需求式唯一真身见 vector_knowledge.py 的 "
            "_ANN_BUILD_MIN_AVAILABLE_BYTES 参数块。",
            missing=missing,
        )
    if bad_reason == "short_by_stamp" and missing is not None:
        return AnnPairVerdict(
            ANN_STATE_REFUSED,
            "short_by_stamp",
            f"这一代 ANN 不可用：索引比计数戳短 {missing} 条 ⇒ 新嵌入的行对向量通道永久隐身，"
            "每条消息回落暴力扫描（2026-09-22 停摆同型）",
            tuple(facts),
            "跑一次 knowledge-sync 全链（补嵌 → build_ann_index 重建 → 提交点落戳）；"
            "判据容差唯一真身=_ANN_COMPLETENESS_MAX_MISSING（0 条都不许少），本项不放宽。",
            missing=missing,
        )
    if bad_reason == "coverage_behind_generation":
        return AnnPairVerdict(
            ANN_STATE_REFUSED,
            "coverage_behind_generation",
            f"这一代 ANN 不可用：当前嵌入代次 {embed_generation} > 证明盖章代次 {attested_generation}"
            " ⇒ 盖章点之后提交的嵌入批次没进本代索引（同轮删+嵌把标量戳拉回原值，戳判看不出这形，"
            "2026-09-26 生产假绿同型）⇒ 载入路径拒用 ANN，每条消息回落暴力扫描",
            tuple(facts),
            "跑一次 knowledge-sync 全链（补嵌 → build_ann_index 重建 → _publish_ann_pair 盖章新代次）；"
            "判据唯一真身见 vector_knowledge.py 的 _EMBED_GENERATION_KEY / "
            "_ATTEST_EMBED_GENERATION_FIELD 与 load_ann_index 代次终检（本项只搬判据、不放宽）。",
            missing=missing,
        )
    label = {
        "no_attestation": "库里没有代际证明（这一代从没成对发布过）",
        "pair_files_absent": f"ANN 两文件缺席（{KB_WIKI_ANN_INDEX_NAME} / {KB_WIKI_ANN_ORDER_NAME}）",
        "pair_files_inconsistent": "ANN 文件体积与代际证明不符（半写或被换过代）",
        "signature_mismatch": "代际签名与库内签名不符（换了 embedding 模型/端点，索引是旧模型的）",
        "attestation_without_signature": "代际证明里没有签名字段",
    }.get(bad_reason, bad_reason)
    return AnnPairVerdict(
        ANN_STATE_REFUSED,
        bad_reason,
        f"这一代 ANN 不可用：{label} ⇒ 载入路径拒用 ANN，每条消息回落暴力扫描",
        tuple(facts),
        "先定成因再动手：① 换过 embedding 模型/端点 ⇒ 必须整代重建（旧索引的邻居与新向量空间不同）；"
        "② 文件被动过 ⇒ 从上一次备份恢复或整代重建；③ 只是没重建 ⇒ 跑 knowledge-sync。"
        "判据唯一真身见 vector_knowledge.py 的 load_ann_index（本项只搬判据、不放宽）。",
        missing=missing,
    )


def check_ann_generation_pair(env: dict[str, str], project_root: Path) -> CheckResult:
    """第 13 项：ANN 这一代可不可用（重启前看见，而不是重启后靠日志考古）.

    状态映射沿用既有三项体检的口径（不新造一把尺）：可用=PASS；无从判定/没建过=SKIP
    （不假红）；REFUSED / UNSTAMPED / MEMORY_SKIP=FAIL——它们在生产里的后果是同一条
    （每条消息付暴力扫描），与第 5 项 kb_drift 判红同级同因。
    人话口径：结论一句 + 每个事实单独一行中文标签（与运行时告警同口径）。
    """
    cid, name = "ann_pair", "ANN 这一代可用性（只读 knowledge_meta，不加载索引）"
    verdict = inspect_ann_generation_pair(env, project_root)
    message = "\n".join((verdict.headline, *verdict.facts))
    status = {
        ANN_STATE_PASS: PASS,
        ANN_STATE_NOT_APPLICABLE: SKIP,
    }.get(verdict.state, FAIL)
    return CheckResult(cid, name, status, message, verdict.fix_hint)


# ---------------------------------------------------------------------------
# 14. kb_domain_anchor：库侧在册语料域 ↔ 本地域词表锚点（只点名、绝不阻断）
# ---------------------------------------------------------------------------
# 病根（P13 接线，2026-10-02）：两侧相减的判据 `kb_wiki.topics_without_local_domain_anchor`
# 今天**只有测试在读**（`tests/test_kb_list_domain_gate.py`），运行期零消费方 ⇒ 谁新补一个
# KB 语料域、却没人往 `question_intent` 的本地域词表加锚点词，运行/发版前**不会有任何人
# 点名**，缺口静默存在——正是本轮「现实知识面」（台账 #73）的复发机制。本项把这枚既有的尺
# 接到中央出口，判据是**报警不是阻断**（照第 7 项 napcat 的 SKIP 形态，exit code 恒不变：
# 缺口不拦重启，拦的是「没人知道」）。
#
# 「尺只有一把」是本项的硬口径：库侧主题名单、kb_dir、两侧相减、出格脱敏全部走真身函数，
# 本文件里出现任何 `not in` 集合运算或 `DOMAIN_TERMS` 字样＝第二把尺，由
# `tests/test_kb_domain_anchor_central_wiring.py` 的 AST 调用图锁（含注毒自证腿）钉住。
#
# 为什么不 import 插件根（沿第 11 项「插件根 __init__.py 是重件」同一纪律）：实测拉起
# NoneBot 与整张能力图 ≈4.4s（2026-10-02 当时值），且没装 nonebot 的环境直接
# ImportError ⇒ 体检不为几枚常量付这个代价。改走「按文件路径直载」：本项用到的四枚模块
# （search_intent ← question_intent ← kb_wiki，外加 plain_text）传递依赖全是标准库，
# 唯一的插件侧模块级边 kb_wiki → vector_knowledge（嵌入/faiss 重件，本项一个符号都不碰）
# 在装载期临时垫一枚哑模块。凡本席往 sys.modules 登记过的名字**必须在 finally 逐枚摘掉**：
# 残留哑模块会被之后的真 import 当正品领走（台账 #72★缺席哨兵同型事故）。
#
# 语料主题＝全量流式读（`scan_limit` 不设）：有界窗口会**少报缺口**——documents.jsonl 按域
# 聚簇、新域多在尾部，现算 20 000 行窗口只透出 4/16 域、5 枚缺口只报得出 1 枚＝假绿；
# 全量读实测 4.8s（2026-10-02 当时值，775MB），与本文件第 5 项读 faiss 同档 ⇒ 宁付秒级。

_PLUGIN_PKG = "plugins.bot_unified_runtime"
#: 直载名册 ``(透出名, 相对插件根的模块点路径)``——**顺序即依赖顺序**，重排会装不上。
_RULER_MODULES: tuple[tuple[str, str], ...] = (
    ("search_intent", "domains.core.search.search_intent"),
    ("question_intent", "domains.chat_reply.runtime.question_intent"),
    ("kb_wiki", "domains.location.knowledge.kb_wiki"),
    ("plain_text", "domains.render.plain_text"),
)
#: kb_wiki 模块级唯一的插件侧依赖：本项不碰嵌入/faiss，装载期把它垫住即可。
_RULER_STUB_MODULE = "domains.chat_reply.character.vector_knowledge"
_RULER_STUB_ATTRS: tuple[str, ...] = (
    "OpenAICompatibleEmbeddingProvider",
    "SqliteVectorKnowledgeStore",
    "_UnavailableVectorKnowledgeProvider",
)
#: kb_dir 相对段（``crawl_output/knowledge_base``）不在这里复制——由真身 kb_paths 现算。
_RULER_KB_WIKI_REL = "domains.location.knowledge.kb_wiki"
#: 点名上限：再多也只列这么多枚进一行读数，其余以计数带过（判据不因此变松）。
_RULER_GAPS_SHOWN = 12
KB_CORPUS_SCAN_LIMIT: int | None = None


@dataclass(frozen=True)
class KbDomainAnchorRuler:
    """缺口尺的取用面（全只读）：``modules`` 为 None 时 ``unavailable`` 说明为什么。"""

    modules: dict[str, Any] | None
    unavailable: str


def _plugin_module_by_path(rel_dotted: str, code_root: Path, registered: list[str]) -> Any:
    """按**文件路径**直载插件侧模块，绕开插件根 ``__init__.py`` 的 NoneBot 重件.

    已在 ``sys.modules`` 里（同进程真 import 过，如 pytest 全量跑）就复用那一枚——
    尺只有一把，绝不在这里造第二份。本函数新登记的名字追加进 ``registered``，
    由 ``kb_domain_anchor_ruler`` 在 finally 里摘除。
    """
    import importlib.util  # 延迟导入：与 _module_available 同一位置口径

    dotted = f"{_PLUGIN_PKG}.{rel_dotted}"
    cached = sys.modules.get(dotted)
    if cached is not None:
        return cached
    source = code_root.joinpath(*_PLUGIN_PKG.split("."))
    for part in rel_dotted.split("."):
        source = source / part
    spec = importlib.util.spec_from_file_location(dotted, source.with_suffix(".py"))
    if spec is None or spec.loader is None:
        # 只报相对点分名，不把绝对路径塞进读数（本项的失败分支手上没有脱敏件可用）
        raise ImportError(f"无法为 {rel_dotted} 构造模块规格")
    module = importlib.util.module_from_spec(spec)
    # 先登记再 exec：模块内 dataclass／延迟注解在 exec 期按 cls.__module__ 反查模块，
    # 不先登记会取到 None 而 AttributeError（S594 实测崩点，见
    # pins/2026-09-24-central-dispatch/PINS-DENOMINATOR-BUILD-S612.md）。
    sys.modules[dotted] = module
    registered.append(dotted)
    spec.loader.exec_module(module)
    return module


def _pad_vector_knowledge(registered: list[str]) -> None:
    """给 kb_wiki 的模块级 vector_knowledge 依赖垫一枚哑模块（本项一个符号都不消费）."""
    dotted = f"{_PLUGIN_PKG}.{_RULER_STUB_MODULE}"
    if dotted in sys.modules:
        return  # 真身已在：绝不拿哑模块顶掉正品
    stub = types.ModuleType(dotted)
    for attr in _RULER_STUB_ATTRS:
        setattr(stub, attr, type(attr, (), {}))
    sys.modules[dotted] = stub
    registered.append(dotted)


@contextmanager
def kb_domain_anchor_ruler(code_root: Path) -> Iterator[KbDomainAnchorRuler]:
    """直载本项的四枚真身；装不上给 ``modules=None`` ＋原因（调用方 SKIP，本项永不 FAIL）.

    退出时按「本席登记过的名字」逐枚摘除 sys.modules 条目。已交出去的模块对象仍被
    调用方引用着（摘登记只是不让别的 import 路径事后拿到这一枚隔离孪生）。
    """
    registered: list[str] = []
    ruler: dict[str, Any] | None = None
    unavailable = ""
    alias = _RULER_STUB_MODULE  # 装载还没开跑就出事时，指认到哑模块那一格
    try:
        if f"{_PLUGIN_PKG}.{_RULER_KB_WIKI_REL}" not in sys.modules:
            _pad_vector_knowledge(registered)
        modules: dict[str, Any] = {}
        for alias, rel_dotted in _RULER_MODULES:
            modules[alias] = _plugin_module_by_path(rel_dotted, code_root, registered)
        ruler = modules
    except (ImportError, OSError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
        # 只报异常类型与名册末段名：异常原文常带绝对路径，而这条分支手里没有脱敏件
        unavailable = f"{type(exc).__name__}：{alias} 这一枚装不上"
    try:
        yield KbDomainAnchorRuler(ruler, unavailable)
    finally:
        for dotted in reversed(registered):
            sys.modules.pop(dotted, None)


def check_kb_domain_anchor(env: dict[str, str], project_root: Path) -> CheckResult:
    """第 14 项：库里收着的语料域，本地域词表有没有对应锚点（只点名，不阻断）.

    判据全在尺那一侧（本函数零集合运算）：
      · 库侧在册主题＝真身 ``iter_corpus_topic_names(kb_dir)``，kb_dir 由真身
        ``kb_paths`` 现算（本处不复制 ``crawl_output/knowledge_base`` 那段相对路径）；
      · 缺口＝真身 ``topics_without_local_domain_anchor(topics)``，锚点侧默认取
        ``question_intent.DOMAIN_TERMS`` 本体；
      · 状态＝无缺口 PASS ／ 有缺口 SKIP 逐域点名 ／ 无从判定 SKIP（库根未配置、
        尺装不上、语料一行主题都读不到——真身 docstring 口径「读不到＝没有证据」，
        不许据此宣称没有缺口）。**本项不产 FAIL**（第 7 项「提示不阻断」形态）。
    尺是**代码**不是部署数据：``--project-root`` 只换数据侧，源码根在假项目根里
    找不到尺文件时回落到本脚本所在仓库根（与第 11 项 declaration_root 同一处置）。
    读数出格前整句过真身 ``redact_local_secrets``，不漏盘符路径。
    """
    cid, name = "kb_domain_anchor", "库侧在册语料域 ↔ 本地域词表锚点（只点名不阻断）"
    wiki_root = str(env.get("BOT_KB_WIKI_ROOT", "") or "").strip()
    if not wiki_root:
        return CheckResult(
            cid, name, SKIP,
            "BOT_KB_WIKI_ROOT 未配置——没有库可查，跳过（既不算缺口，也不算绿）",
        )
    code_root = project_root if (
        project_root.joinpath(*_PLUGIN_PKG.split("."))
        .joinpath(*_RULER_KB_WIKI_REL.split("."))
        .with_suffix(".py")
    ).is_file() else PROJECT_ROOT
    with kb_domain_anchor_ruler(code_root) as access:
        if access.modules is None:
            return CheckResult(
                cid, name, SKIP,
                f"缺口尺装载不出来（{access.unavailable}）——本项无从判定，诚实跳过不假绿；"
                "判据真身见 plugins/bot_unified_runtime/domains/location/knowledge/"
                "kb_wiki.py::topics_without_local_domain_anchor",
            )
        kb_wiki = access.modules["kb_wiki"]
        # 绑定名与真身函数同名：接线锁按调用节点的末段名认这条腿（别名会让它隐身）
        redact_local_secrets = access.modules["plain_text"].redact_local_secrets
        kb_dir = kb_wiki.kb_paths(types.SimpleNamespace(bot_kb_wiki_root=wiki_root))[1]
        topics = list(kb_wiki.iter_corpus_topic_names(kb_dir, scan_limit=KB_CORPUS_SCAN_LIMIT))
        gaps = list(kb_wiki.topics_without_local_domain_anchor(topics))
        if not topics:
            return CheckResult(
                cid, name, SKIP,
                redact_local_secrets(f"{kb_dir} 下读不到任何语料主题（documents.jsonl 缺失或不可读）——"
                       "读不到＝没有证据，绝不据此宣称「库里没有这一域」"),
                "确认 BOT_KB_WIKI_ROOT 指向爬虫导出根（第 1 项 env_paths 只管根存在，"
                "本项要的是 crawl_output/knowledge_base/documents.jsonl 里有行）。",
            )
        if gaps:
            shown = "、".join(gaps[:_RULER_GAPS_SHOWN])
            if len(gaps) > _RULER_GAPS_SHOWN:
                shown += f" …等共 {len(gaps)} 域"
            return CheckResult(
                cid, name, SKIP,
                redact_local_secrets(f"库侧在册语料域 x{len(topics)}，其中 {len(gaps)} 域在本地域词表缺锚点："
                       f"{shown}（查的是 {kb_dir}）——这些域的题既不判 LOCAL_KNOWLEDGE、"
                       "也走不到「本地优先、低置信才补网」：资料明明躺着，模型却被推去联网。"
                       "只点名不阻断，不拦本次重启。"),
                "补锚点＝在 plugins/bot_unified_runtime/domains/chat_reply/runtime/"
                "question_intent.py 的 _SHOREKEEPER_DOMAIN_TERMS（自有设定）或 "
                "plugins/bot_unified_runtime/domains/core/search/search_intent.py 的 "
                "ACG_DOMAIN_TERMS['game'][strong]（外部游戏域，DOMAIN_TERMS 由它现取，"
                "不许在别处手抄名单）加词，改后重启生效；两侧相减的尺只有一把="
                "plugins/bot_unified_runtime/domains/location/knowledge/kb_wiki.py"
                "::topics_without_local_domain_anchor（本项只点名、不代改、不放宽）。",
            )
        return CheckResult(
            cid, name, PASS,
            redact_local_secrets(f"库侧在册语料域 x{len(topics)} 全部有本地域锚点"
                   f"（缺口尺经中央出口第 14 项现算，不再是只有测试在读）"),
        )


# ---------------------------------------------------------------------------
# 15. entry_chain：入口 import 链（SDD M2-44 的落地腿，2026-10-04）
# ---------------------------------------------------------------------------
# 为什么这一格非有不可（现算，见 ChatBot_Runtime/cache/seat-restartsafe/REPORT.md §6 B4）：
# 探针真身 ``scripts/import_chain_probe.py`` 自 09-27 就在库、施工图也在册，但**没有任何
# 门指向它**——「修法在册≠修好在盘」。入口链上任一模块级求值抛错（2026-09-29 实撞的形态
# 是 ``re.compile`` 里多一枚右括号）⇒ nonebot 只记一条 error、``bot.py`` 崩溃守卫 ``raise``
# ⇒ 插件全体不注册；``BOT_SUPERVISE=1`` 退避 5+15+60+60≈140 秒后永久 down。而载体
# ``ChatBot_Runtime\restart_bot.ps1`` 先杀后起、中间零判据 ⇒ 坏在这里的代价是「杀掉那一棒
# 救不回」，本格拦的就是这一秒。
#
# 判据纪律（本格的命门）：取探针自己的退出码，**且**必须拿到与它一致的结构化读数——
# rc 是必要条件，不再是充分条件。绝不取回显：本项目被「宣布成功的回显」骗过不止一次
# （台账 #63★「批即落」从未实现、#75★溯源门）。rc 语义真身＝探针模块 docstring「退出码」
# 段：0=全链可导、1=至少一格 FAIL、2=探针自身无从判定。
# 结构地板（2026-10-04 ``seat-gateverify`` 复核后收紧，假绿形态清单 249）：rc=0 而
# ①stdout 解析不出 ``--json`` 对象／②``cells`` 一格没有／③``cells`` 里有 ``status=FAIL``
# ⇒ 一律 FAIL。旧写法「解析不出就按 rc 放行」把洞留在门最想防的那一格：一枚只写注释的
# 空壳桩件（本仓「退役＝留再导出垫片」的先例正好造得出这东西）或探针把读数写到非 stdout
# 的改版 ⇒ 门恒绿且自称「全链可导」，而它一行代码没验。加的都是**结构化字段**要求
# （payload/cells/status），照旧一个字也不采散文。
# 现算形态＝解释器没装 nonebot 时子进程 setup 抛 ModuleNotFoundError、父进程仍报 rc=0
# 「全链可导」，那是「没有证据」被洗成「绿」。
# 探针输出只按 ``--json`` 的结构化字段读（格名/状态/落点）。
# 本项不产 SKIP：拦的就是「按下重启」那一下；探针真身缺席、超时、rc=2 一律红。
# 「没验到」的格（INCONCLUSIVE＝环境缺席）不改判红（离线/CI 不许被门炸掉），但必须
# 当**点名 SKIP**上屏：一把静默跳过证据的绿门和一把放行的红门是同一个谎。
# git 采集缝（「重启会带走谁」那一半）不外抛：它在探针之前跑，抛穿 ``run_all`` 就等于
# 顶穿 ``run-watch`` 的 loop 步＝看门狗自尽、永久 down。读不到一律折成
# ``working_tree_known=False`` 那一种表示（禁第二表示法），报「unknown」而非「干净」。

ENTRY_CHAIN_PROBE_REL = "scripts/import_chain_probe.py"
PRE_RESTART_CHECK_REL = "scripts/pre_restart_check.py"
ENTRY_CHAIN_PROBE_TIMEOUT = 900  # 实测工作树 ≈10-30s（2026-10-04 当时值），留足冷启动余量
#: 工作树读数的有界超时：``git status`` 挂住（复核实测见过 120s 那一级）必须由这里兜住，
#: 兜不住的那一段时间本来就该换成「读不到」继续交付探针证据，而不是把整张预检炸掉
ENTRY_CHAIN_GIT_TIMEOUT = 60
_PROBE_RC_GREEN = 0
_PROBE_RC_UNJUDGED = 2
_PROBE_INCONCLUSIVE = "INCONCLUSIVE"
#: 探针 rc → 人话（只用于读数说明，判定不看这段文字）
_PROBE_RC_READING = {0: "全链可导", 1: "至少一格不可导", 2: "探针自身无从判定"}
#: 结构地板的缺证原因 → 人话（判定看的是 payload/cells/status 这些字段，不是这句话）
_PROBE_NO_EVIDENCE = {
    "unparseable": "探针 rc=0 却交不回可解析的 --json 读数（stdout 里没有一枚 JSON 对象）",
    "empty_cells": "探针 rc=0 却交回 0 格（它自己的 setup 没跑成，一格证据都没有）",
    "failed_cells": "探针 rc=0 却交回 {n} 格 status=FAIL（退出码与自家读数相互矛盾）",
}
_TREE_UNKNOWN_SUFFIX = "——在改模块清单无从现算，不宣称「没有改动」"
#: 在改模块点名上限（再多只报计数——判据不因此变松，全量清单在 ``details`` 里）
_ENTRY_CHAIN_MODULES_SHOWN = 8
#: 「没验到」的格点名上限（SKIP 要出声：操作者在表格里看得见名字，不是只见一个数）
_ENTRY_CHAIN_SKIPS_SHOWN = 5

_ENTRY_CHAIN_HINT = (
    f"入口链不过＝重启下去大概率是「插件全体不注册 + 140 秒熔断永久 down」，先修再按。"
    f"定位：{ENTRY_CHAIN_PROBE_REL} --json 的 cells[] 里 status=FAIL 那几格点名了模块、"
    "异常类型与落点（kind/error/location）；改完复跑本项。注意本探针按设计只 "
    "compile() bot.py（不执行），抓得到 SyntaxError 抓不到 bot.py 的 ImportError——"
    "已知边界见探针真身 docstring 纪律 2，不许拿本格的绿当 bot.py 的保证。"
    "机制全账见 .superpowers/sdd/2026-09-27-fullload/reports-m2/M2-44-ENTRY-PROBE-LANDING.md。"
)


def _module_dotted(rel_path: str) -> str:
    """仓内相对路径 → 点分模块名（``__init__.py`` 折成包名）."""
    parts = rel_path[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def working_tree_plugin_modules(project_root: Path) -> tuple[tuple[str, ...], str]:
    """列出「tracked 且已改」的 ``plugins/**`` Python 模块（点分名，排序）＋读不到的原因.

    这格要交付的是**数据**，不是那句口头警告：重启读的是盘，盘上有多少枚别人没收笔的
    运行时代码，操作者按之前就该看到一个数（口径同 ``seat-restartsafe`` 报告 §3 的
    「进运行时的只有 plugins/** 那几枚」）。

    取数＝``git status --porcelain``（cwd=``project_root``，经 ``run_cmd`` 这一唯一子进程
    缝，测试可注）。解析形状照既有采集器 ``scripts/physical_placement_census.py`` 的
    ``_s11_git_outside_sets``（前两字符=XY、第三字符起=路径、rename 取箭头右侧、剥引号
    与反斜杠）——复用它的**形状**而非它的尺：那把尺绑死在本仓 ``REPO_ROOT`` 与「域外 .py」
    判据上，指不了 ``--project-root`` 传进来的副本，且它 import 会牵起整张板块树。
    谓词差量：``XY`` 含 ``M``（tracked-modified）且路径在 ``plugins/`` 下、以 ``.py`` 结尾；
    ``??``（未跟踪）、``D``（删除）、``docs/``/``scripts/``（不进运行时）一概不入——
    未跟踪件确实也在盘上，但那属「谁的稿」之争，本格只报「重启会把已入库的哪几枚换掉」。
    **读不到＝没有证据**：``git`` 不可用（副本非检出、无权限、没装 git）、``git status``
    挂过超时、或这一路抛出任何异常时，返回空清单 + 非空原因（与 ``rc!=0`` 同一种表示，
    禁第二表示法），调用方必须带着原因上屏，绝不得据此宣称「这棵树没有改动」。
    本函数**一律不外抛**：它在入口链探针之前跑，抛穿 ``run_all`` 会顶穿 ``run-watch``
    的 loop 步＝看门狗自尽、永久 down（复核 §2(e)(f) 记的就是这一条）。
    """
    try:
        rc, out, _err = run_cmd(
            ["git", "status", "--porcelain"], project_root, timeout=ENTRY_CHAIN_GIT_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return (), (
            f"git status 读不到（{ENTRY_CHAIN_GIT_TIMEOUT}s 未回）{_TREE_UNKNOWN_SUFFIX}"
        )
    except OSError as exc:  # FileNotFoundError=没装 git/不在 PATH；PermissionError=无权限
        return (), f"git 读不到（调用失败 {type(exc).__name__}）{_TREE_UNKNOWN_SUFFIX}"
    if rc != 0:
        return (), f"git status 读不到（rc={rc}）{_TREE_UNKNOWN_SUFFIX}"
    modules: set[str] = set()
    for line in out.splitlines():
        if len(line) < 4:
            continue
        xy, pathspec = line[:2], line[3:]
        if " -> " in pathspec:  # rename：取箭头右侧（工作树形态）
            pathspec = pathspec.split(" -> ", 1)[1]
        pathspec = pathspec.strip().strip('"').replace("\\", "/")
        if "?" in xy or "M" not in xy:
            continue
        if not pathspec.startswith("plugins/") or not pathspec.endswith(".py"):
            continue
        modules.add(_module_dotted(pathspec))
    return tuple(sorted(modules)), ""


def _probe_payload(stdout: str) -> dict[str, Any] | None:
    """取探针 ``--json`` 的结构化读数（解析不出＝None，本项绝不猜内容也不因它改判）.

    探针真身的 ``--json`` 走 ``indent=2`` ⇒ 整个读数是一枚**跨行**对象，逐行扫必然只撞到
    ``{`` 这种半截串（第一版就是这么栽的：解析失败当场 ``return None``，真实读数全被
    当成「没跑过」⇒ 本项对真探针恒红）。所以先按行试（兼容单行 JSON 的直跑态），
    再把整串当一枚对象试；任何一片解析不了就**接着找**，不是提前收工。
    """
    text = stdout.strip()
    if not text:
        return None
    candidates: list[object] = [reversed(text.splitlines()), [text]]
    for group in candidates:
        for chunk in group:
            try:
                parsed = json.loads(str(chunk))
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def check_entry_chain(project_root: Path) -> CheckResult:
    """第 15 项：入口 import 链（缺省轴＝当前工作树）＋「这次重启会带走谁」."""
    cid, name = "entry_chain", "入口 import 链（重启到底起不起得来）"
    try:
        modules, tree_note = working_tree_plugin_modules(project_root)
    except Exception as exc:  # noqa: BLE001 — 采集面抛出（含桩件/替换实现）也不许顶穿 run-watch 的 loop 步
        modules, tree_note = (), f"在改模块采集抛穿（{type(exc).__name__}）{_TREE_UNKNOWN_SUFFIX}"
    if tree_note:
        tree_part = f"；在改模块读不到（{tree_note}）"
    elif modules:
        shown = "、".join(modules[:_ENTRY_CHAIN_MODULES_SHOWN])
        if len(modules) > _ENTRY_CHAIN_MODULES_SHOWN:
            shown += " …等"
        tree_part = f"；本次重启会带走 plugins/** 在改模块 x{len(modules)}：{shown}"
    else:
        tree_part = "；plugins/** 无 tracked-modified 模块（工作树与 HEAD 同码）"
    details: dict[str, Any] = {
        "probe_root": str(project_root),
        "probe_script": ENTRY_CHAIN_PROBE_REL,
        "probe_rc": None,
        "probe_cells_total": 0,
        "probe_cells_fail": [],
        "probe_inconclusive": 0,
        "probe_payload_parsed": False,
        "probe_skipped_cells": [],
        "probe_structural_floor": "",
        "probe_plugins_leg": {},
        "working_tree_known": not tree_note,
        "working_tree_note": tree_note,
        "modified_plugin_modules": list(modules),
        "modified_plugin_count": len(modules),
    }

    if not (project_root / ENTRY_CHAIN_PROBE_REL).is_file():
        return CheckResult(
            cid, name, FAIL,
            f"探针真身缺席：{ENTRY_CHAIN_PROBE_REL} 不在 {project_root}——本格无从判定，"
            "宁可红也不放行" + tree_part,
            _ENTRY_CHAIN_HINT,
            details,
        )
    argv = [
        sys.executable,
        ENTRY_CHAIN_PROBE_REL,
        "--root",
        str(project_root),
        "--json",
    ]
    try:
        rc, out, _err = run_cmd(argv, project_root, timeout=ENTRY_CHAIN_PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return CheckResult(
            cid, name, FAIL,
            f"探针 {ENTRY_CHAIN_PROBE_TIMEOUT}s 未回——没有证据，按红记账" + tree_part,
            _ENTRY_CHAIN_HINT,
            details,
        )
    payload = _probe_payload(out)
    cells = [c for c in (payload or {}).get("cells") or [] if isinstance(c, dict)]
    failed_cells = [c for c in cells if c.get("status") == FAIL]
    skipped_cells = [str(c.get("cell", "")) for c in cells if c.get("status") == _PROBE_INCONCLUSIVE]
    details.update(
        {
            "probe_rc": rc,
            "probe_cells_total": len(cells),
            "probe_cells_fail": [str(c.get("cell", "")) for c in failed_cells],
            "probe_inconclusive": len(skipped_cells),
            "probe_payload_parsed": payload is not None,
            "probe_skipped_cells": skipped_cells,
            "probe_plugins_leg": (payload or {}).get("plugins") or {},
        }
    )

    if rc != _PROBE_RC_GREEN:
        reading = _PROBE_RC_READING.get(rc, "未预期退出码")
        head = f"探针 rc={rc}（{_scrub_probe(reading)}）——本项判据＝退出码＋结构化读数，回显不参与判定"
        if payload is None:
            head += f"；{_PROBE_NO_EVIDENCE['unparseable']}"
        if failed_cells:
            picks = "、".join(
                f"{c.get('cell')}[{_scrub_probe(str(c.get('kind', '')))} @{c.get('location', '')}]"
                for c in failed_cells[:3]
            )
            head += f"；不可导格 x{len(failed_cells)}：{picks}" + (
                f"（余 {len(failed_cells) - 3} 枚见 --json）" if len(failed_cells) > 3 else ""
            )
        plugins_leg = details["probe_plugins_leg"]
        if isinstance(plugins_leg, dict) and plugins_leg:
            head += (
                f"；注册腿 loaded={plugins_leg.get('loaded')} "
                f"target_loaded={plugins_leg.get('target_loaded')} "
                f"failed={_scrub_probe(str(plugins_leg.get('failed')))}"
            )
        return CheckResult(cid, name, FAIL, head + tree_part, _ENTRY_CHAIN_HINT, details)

    # 结构地板：rc=0 只是必要条件——还必须有**与它一致**的结构化读数（三形任一即红）
    if payload is None:
        floor = "unparseable"
    elif not cells:
        floor = "empty_cells"
    elif failed_cells:
        floor = "failed_cells"
    else:
        floor = ""
    if floor:
        details["probe_structural_floor"] = floor
        why = _PROBE_NO_EVIDENCE[floor].format(n=len(failed_cells))
        picks = ""
        if failed_cells:
            picks = "：" + "、".join(
                f"{c.get('cell')}[{_scrub_probe(str(c.get('kind', '')))} @{c.get('location', '')}]"
                for c in failed_cells[:3]
            )
        return CheckResult(
            cid, name, FAIL,
            f"{why}——没有结构化证据，不算「全链可导」{picks}" + tree_part,
            _ENTRY_CHAIN_HINT, details,
        )

    # 到这里才是绿：rc=0 + 读得回 JSON + 至少一格 + 没有一格说 FAIL
    n_verified = len(cells) - len(skipped_cells)
    if skipped_cells:
        named = "、".join(skipped_cells[:_ENTRY_CHAIN_SKIPS_SHOWN]) + (
            f" …余 {len(skipped_cells) - _ENTRY_CHAIN_SKIPS_SHOWN} 枚见 --json"
            if len(skipped_cells) > _ENTRY_CHAIN_SKIPS_SHOWN
            else ""
        )
        proof = (
            f"探针 rc=0：{n_verified}/{len(cells)} 格可导；"
            f"⚠ SKIP x{len(skipped_cells)}（点名：{named}）＝这些格这一轮**没验到**"
            "（环境缺席，按设计不算红，但也不许当验过——本格的绿只覆盖其余格）"
        )
    else:
        proof = f"探针 rc=0：{len(cells)} 格全无可导失败（无一格 SKIP＝逐格都真验到了）"
    return CheckResult(cid, name, PASS, proof + tree_part, "", details)


def _scrub_probe(text: str) -> str:
    """探针落点/异常原文进读数前压平（防多行与超长串打崩表格，不截语义）."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= 200 else flat[:197] + "…"


# ---------------------------------------------------------------------------
# 汇总与输出
# ---------------------------------------------------------------------------

def run_all(project_root: Path, only: Sequence[str] = ()) -> list[CheckResult]:
    """跑齐在册项；``only`` 非空时只**交出**被点名那些格（顺序仍按声明侧）.

    全部项仍各跑一遍：注册面那几行的**行形状**被两把注毒锁当锚点钉着
    （``tests/test_tts_identity_watch.py`` 摘行/挪位必红、``tests/test_kb_domain_anchor_central_wiring.py``
    走 AST 调用图），改成惰性表或 ``add(...)`` 包装会让锚点静默失配＝把锁掏空。
    取舍＝多花几十秒读表，换两把锁继续有牙；判定与退出码只由 ``only`` 那几格说话。
    """
    env = load_env(project_root)
    results = [
        check_env_paths(env, project_root),
        check_persona_sync(env, project_root),
        check_hash_ledger(project_root),
        check_doc_sync(project_root),
        check_kb_drift(env, project_root),
        check_ruff(project_root),
        check_napcat(onebot_endpoints(env)),
        check_webui(project_root),
        check_control_plane(env),
        check_tts_voice_identity(env, project_root),
        check_channel_capability_tags(env, project_root),
        check_mcp_server_spec(env, project_root),
        check_ann_generation_pair(env, project_root),
        check_kb_domain_anchor(env, project_root),
        check_entry_chain(project_root),
    ]
    if not only:
        return results
    wanted = list(only)
    declared = declared_item_ids()
    unknown = [item for item in wanted if item not in declared]
    if unknown:
        raise ValueError(f"--only 给了不在册的体检项：{unknown}（在册＝{declared}）")
    return [r for r in results if r.id in wanted]



# 在册清单的唯一声明侧 = 本模块 docstring 的编号列表（`N. id …` 行，两空格缩进）。
# 不另立常量清单：那会变成第三抄本（docstring / run_all / 常量各一份），
# 本仓 link-unification-audit 的实证教训是抄本必漂移。一切消费方（跟随锁、
# argparse 帮助）经本函数现算，禁在任何一侧手写总数（AGENTS.md 铁律 10 同哲学）。
_CHECK_ITEM_RE = re.compile(r"^[ \t]*(\d+)\. ([a-z_][a-z0-9_]*)\b", re.MULTILINE)


def declared_item_ids() -> list[str]:
    """从本模块 docstring 的编号清单派生「在册体检项」的有序 id 列表.

    Raises:
        ValueError: 编号不从 1 连续递增、或 id 重复——声明侧被改坏时大声失败，
            绝不拿一份可疑清单继续判定（假绿比红更糟）。
    """
    pairs = _CHECK_ITEM_RE.findall(__doc__ or "")
    ids = [item_id for _, item_id in pairs]
    numbers = [int(num) for num, _ in pairs]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"docstring 编号清单不连续（应为 1..{len(numbers)}）：{numbers}")
    duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if duplicates:
        raise ValueError(f"docstring 编号清单出现重复 id：{duplicates}")
    return ids


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
    parser = argparse.ArgumentParser(
        description=(
            # 项数现算自声明侧清单（S146：旧版这里手写死「13 项」，长一项漂一次）
            f"生产 bot 重启前置一键预检（{len(declared_item_ids())} 项，全绿才动手重启）"
        )
    )
    parser.add_argument("--json", action="store_true", help="结构化 JSON 输出")
    parser.add_argument("--project-root", default=None, help="覆盖项目根（默认仓库根，供测试/异构部署）")
    parser.add_argument(
        "--only",
        default=None,
        help=(
            f"只交出任几格（逗号分隔在册 id，如 entry_chain）；退出码随之收窄——"
            f"restart-check 门用，旁格红不堵「起得来」这条路。在册项现算自声明侧："
            f"{','.join(declared_item_ids())}"
        ),
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve() if args.project_root else PROJECT_ROOT
    only = tuple(s.strip() for s in str(args.only).split(",") if s.strip()) if args.only else ()
    try:
        results = run_all(project_root, only)
    except ValueError as exc:  # --only 的 id 不在册：大声失败，绝不静默少跑一项
        print(f"[pre_restart_check] 命令行不合法：{exc}", file=sys.stderr)
        return 2

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
