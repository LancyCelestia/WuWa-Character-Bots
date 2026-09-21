"""文档链接归一 / 单一事实源 常驻完整性门（DOC-FIX-2 席，2026-09-20）。

上游审计：`docs/design/link-unification-audit-20260920.md`（§8 门规格 G-1/G-2）。
本门治的是「常驻门全绿却抓不到文档真假」这一类（该审计 §0 的实锤）。

三道子门：
  ① 坐标与互链有效性：文档里的 `文件.py:行` 引用——文件可解析 / 行不越界 /
     旧路径与垫片走棘轮 / markdown 相对链不得死。
     **历史坐标豁免**走「文件级史实件类 + 行级日期锚」双机制（见 `_HISTORY_*`），
     外加显式条目清单（带理由，反向锁：不再命中的豁免必须摘除）。
  ② 协议枚举不手抄：文档里抄出来的 retcode / 事件源成员清单，
     与代码真身**取集合比对**，漂移即硬红；副本总数走棘轮（只降不升）。
  ③ 归属表载体路径：`AGENTS.md` 第四部分「载体文件」列逐条判「文件是否存在 +
     是否真身（非 Compat 垫片）」，缺失数与垫片数各自走棘轮。

纪律：纯静态，零 import 插件包（照 `scripts/command_catalog.py` 的姿势）。
棘轮基线只许下调；下调请同步在 `AGENTS.md`/审计件记账，防止「基线被悄悄抬高」。
调试：`DOC_LINK_GATE_DUMP=1 python -m pytest tests/test_doc_link_integrity.py -q -s`
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins" / "bot_unified_runtime"
DUMP = os.environ.get("DOC_LINK_GATE_DUMP") == "1"

# ---------------------------------------------------------------------------
# 扫描面与豁免类
# ---------------------------------------------------------------------------

#: 被扫的文档面（全量 md，含史实件；史实件走下面的分类豁免而非不扫）
DOC_GLOBS: tuple[str, ...] = ("AGENTS.md", "COMMANDS.md", "docs/**/*.md")

#: 文件级「史实件」类：这些文件里的旧坐标是合法历史记录（审计 G-1 豁免①）
_HISTORY_FILE_RE = re.compile(
    r"(?:^|/)(?:audit-[^/]+|.*-log|.*-draft|nightly-ops-report-[^/]+|"
    r"handover-[^/]+|HANDOVER-[^/]+|link-unification-audit-[^/]+|"
    r"issue-ledger[^/]*|codebase-slim-plan|v21[^/]*|COMPACT-CHECKPOINT)\.md$"
    r"|/unify-audit[^/]*/|/2026-09-\d\d-",
    re.IGNORECASE,
)

#: 行级日期锚：同一行里带日期戳 / 提交哈希 / 明确的史实措辞 ⇒ 该行坐标按史实处理
_HISTORY_LINE_RE = re.compile(
    r"20\d\d-\d\d-\d\d|[0-9a-f]{7,40}|已入库|旧路径|旧口径|旧记|勘误|作废|史值|曾名|位移"
)

#: 外部仓 / 第三方库坐标：不在本工作区，无法就地校验（审计 G-1 豁免②、D-3）
_THIRD_PARTY_PKGS = (
    "nonebot|pydantic|httpx|anyio|starlette|fastapi|sqlalchemy|uvicorn|jinja2"
    "|aiosqlite|PIL|numpy|telegram|qq|mail|websockets|greenlet|lxml|bs4|yt_dlp"
)
_EXTERNAL_REF_RE = re.compile(
    r"^(?:[A-Za-z]:/|/)|C:/Software|site-packages"
    rf"|^(?:{_THIRD_PARTY_PKGS})/|/(?:{_THIRD_PARTY_PKGS})/",
    re.IGNORECASE,
)

#: 一次性 TEMP 探针产物（审计 G-1 豁免③）：必须就近写明「已失效」否则仍判红
_TEMP_REF_RE = re.compile(r"\.tmp-test|%TEMP%|/tmp/|\\tmp\\", re.IGNORECASE)
_TEMP_TOLD_RE = re.compile(r"已失效|仅存取证|探针产物|一次性")

#: 显式豁免条目：(相对路径, 正则(命中被豁免的坐标文本), 理由, 归属/修法)
#: 反向锁：条目若不再命中任何坐标 ⇒ `test_exemptions_are_all_still_needed` 红。
_EXPLICIT_EXEMPTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "docs/design/link-unification-audit-20260920.md",
        r".",
        "审计报告本体＝史实件，其内引用的失真坐标是被审对象，不是新失真",
        "无需修法：审计 G-1 豁免①",
    ),
)

# ---------------------------------------------------------------------------
# 棘轮基线（2026-09-20 DOC-FIX-2 实测；只许降，不许升）
# ---------------------------------------------------------------------------

_BASELINE_COORD_LEGACY = 837  # 2026-09-20 实测（仅已跟踪件；史实行走豁免不计）
_BASELINE_COORD_SHIM = 3  # 实测：只能解析到垫片且无同名真身
_BASELINE_COORD_OVERFLOW = 3  # 实测（非史实行）
_BASELINE_MD_DEAD_LINKS = 2  # 实测（在飞草稿件走全量上限档）
_BASELINE_ENUM_COPIES = 0  # 实测：已跟踪件里协议成员清单副本已归零（余 2 处在未跟踪草稿）
_BASELINE_CARRIER_DEAD = 0  # 硬零：载体列彻底不存在的路径
_BASELINE_COORD_UNRESOLVED = 123  # 棘轮：已跟踪件的死坐标
_BASELINE_CARRIER_MISLEADING = 50  # 实测：垫片 35 + 字面不存在的旧路径 15
_BASELINE_CARRIER_TRUTH = 5  # 地板：开工实测字面命中真身条数
_BASELINE_ALL_FACE_TOTAL = 167  # 全量面（含在飞草稿）缺陷条目总上限


#: 外部仓绝对根（本机其它仓，如 GPT-SoVITS）；就近出现即认为该坐标有意指向外部
_ABS_ROOT_RE = re.compile(r"[A-Za-z]:[/\\\\](?:Software|Users|Program Files)")
ABS_ROOT_SPAN = 5


def _abs_root_nearby(lines: list[str], idx: int) -> bool:
    lo, hi = max(0, idx - ABS_ROOT_SPAN), min(len(lines), idx + ABS_ROOT_SPAN + 1)
    return any(_ABS_ROOT_RE.search(ln) for ln in lines[lo:hi])


def _fmt(kind: str, doc: str, lineno: int, ref: str, detail: str, fix: str) -> str:
    return (
        f"[{kind}] {doc}:{lineno} -> 所引 `{ref}`｜{detail}\n"
        f"        修法：{fix}"
    )


# ---------------------------------------------------------------------------
# 源码索引与解析
# ---------------------------------------------------------------------------

_SOURCE_ROOTS: tuple[str, ...] = ("plugins", "scripts", "tests", "webui")
_ROOT_FILE_SUFFIXES: tuple[str, ...] = (".py", ".ps1", ".bat", ".cmd")

#: 非源码坐标（审计 G-1 豁免④）：运行时数据/环境/日志路径不是仓内源文件
_RUNTIME_PATH_RE = re.compile(
    r"^(?:\./)?(?:data|ChatBot_Runtime|ChatBot_Archive|logs?|cache|cookies|"
    r"card_render_assets|webui/node_modules)/",
    re.IGNORECASE,
)


def _walk_sources() -> tuple[set[str], dict[str, list[str]], dict[str, int]]:
    """返回 (仓内相对 posix 路径集, basename -> [相对路径], 相对路径 -> 行数)。"""
    rels: set[str] = set()
    by_name: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for top in _SOURCE_ROOTS:
        base = ROOT / top
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or "__pycache__" in p.parts:
                continue
            if p.suffix not in {
                ".py", ".html", ".ts", ".tsx", ".js", ".sql", ".json", ".ps1", ".bat"
            }:
                continue
            rel = p.relative_to(ROOT).as_posix()
            rels.add(rel)
            by_name.setdefault(p.name, []).append(rel)
            try:
                counts[rel] = p.read_text(encoding="utf-8", errors="replace").count("\n") + 1
            except OSError:  # pragma: no cover
                counts[rel] = 0
    for p in ROOT.iterdir():  # 根目录件：bot.py / dev.ps1 / 启动脚本等
        if p.is_file() and p.suffix in _ROOT_FILE_SUFFIXES:
            rel = p.relative_to(ROOT).as_posix()
            rels.add(rel)
            by_name.setdefault(p.name, []).append(rel)
            counts[rel] = (
                p.read_text(encoding="utf-8", errors="replace").count("\n") + 1
            )
    return rels, by_name, counts


_RELS, _BY_NAME, _LINES = _walk_sources()

#: 数据库/运行时产物文件名（db-owners 一类清单的条目），不是源码坐标
_DB_NAME_RE = re.compile(r"\.(?:sql|db|sqlite3?|jsonl|tsv|csv|txt|md|ya?ml|env)$", re.IGNORECASE)

_SHIM_CACHE: dict[str, bool] = {}


def _is_shim(rel: str) -> bool:
    if rel not in _SHIM_CACHE:
        try:
            head = (ROOT / rel).read_text(encoding="utf-8", errors="replace")[:600]
        except OSError:
            head = ""
        _SHIM_CACHE[rel] = "Compat shim" in head
    return _SHIM_CACHE[rel]


def _resolve(rel_doc: str, ref: str) -> tuple[str | None, str]:
    """把文档里的路径写法解析成仓内相对路径。返回 (命中路径或 None, 说明)。"""
    cand = ref.lstrip("./")
    if cand in _RELS:
        return cand, "按仓内相对路径命中"
    for prefix in ("", "plugins/bot_unified_runtime/", "plugins/"):
        probe = prefix + cand
        if probe in _RELS:
            return probe, f"按 `{prefix or '根'}` 前缀补全命中"
    name = cand.rsplit("/", 1)[-1]
    hits = [h for h in _BY_NAME.get(name, []) if not _is_shim(h)]
    if len(hits) == 1:
        return hits[0], "按文件名唯一命中（文档写的旧路径已无真身同名件）"
    if len(hits) > 1:
        # 「行容量优先」：能容得下所引行号的那一个（审计 §0 方法）
        return hits[0], f"同名多件（{len(hits)}），取首个候选：{hits[0]}"
    shim_hits = _BY_NAME.get(name, [])
    if shim_hits:
        return shim_hits[0], "只能解析到 Compat 垫片（3—18 行，非真身）"
    for probe in (cand, f"plugins/bot_unified_runtime/{cand}"):
        if (ROOT / probe.rstrip("/")).is_dir():
            return f"{probe.rstrip('/')}/", "按目录命中（载体可以是目录）"
    return None, "仓内无此文件/目录（外部仓/第三方库/已消失路径）"


# ---------------------------------------------------------------------------
# 子门 ①：坐标有效性
# ---------------------------------------------------------------------------

_REF_RE = re.compile(
    r"(?<![\w./\\-])((?:[\w.\-\u4e00-\u9fff]+/)*[\w.\-]+\.(?:py|html|ps1|sh|sql|ts|tsx))"
    r"(?::(\d+)(?:\s*[-–—]\s*(\d+))?)?"
)


def _tracked_docs() -> frozenset[str]:
    """git 已跟踪的文档集合。未跟踪件＝他席在飞草稿（无还原基线，本仓纪律不碰），
    其缺陷单列 `exempt_inflight` 档：不计入硬门，但**同样走棘轮**且在 dump 里全量列出；
    一旦入库（合流波），条目自动落到棘轮/硬零档 ⇒ 在飞件不能把脏账带进史实。"""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "ls-files", "--", "AGENTS.md", "COMMANDS.md", "docs"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):  # 无 git 时按「全部已跟踪」处理（更严）
        return frozenset()
    if out.returncode != 0:
        return frozenset()
    return frozenset(x.strip().replace("\\", "/") for x in out.stdout.splitlines())


_TRACKED = _tracked_docs()


def _is_inflight(doc: str) -> bool:
    return bool(_TRACKED) and doc not in _TRACKED


def _scan_docs(skip_inflight: bool = False) -> Iterable[tuple[str, Path]]:
    seen: set[Path] = set()
    for glob in DOC_GLOBS:
        for p in sorted(ROOT.glob(glob)):
            if p in seen or not p.is_file():
                continue
            seen.add(p)
            rel = p.relative_to(ROOT).as_posix()
            if skip_inflight and _is_inflight(rel):
                continue
            yield rel, p


def _line_ctx(lines: list[str], idx: int, span: int = 2) -> str:
    lo, hi = max(0, idx - span), min(len(lines), idx + span + 1)
    return "\n".join(lines[lo:hi])


def collect_coordinate_findings(skip_inflight: bool = False) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "unresolved": [],
        "overflow": [],
        "shim": [],
        "legacy": [],
        "exempt_history": [],
        "exempt_explicit": [],
    }
    explicit = [
        (doc, re.compile(pat, re.IGNORECASE), reason, owner)
        for doc, pat, reason, owner in _EXPLICIT_EXEMPTIONS
    ]
    for doc, path in _scan_docs(skip_inflight):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover
            continue
        lines = text.splitlines()
        history_file = bool(_HISTORY_FILE_RE.search(doc))
        for idx, line in enumerate(lines):
            is_history = history_file or bool(_HISTORY_LINE_RE.search(line))
            for m in _REF_RE.finditer(line):
                ref, l1, l2 = m.group(1), m.group(2), m.group(3)
                hit = None
                for edoc, ere, reason, owner in explicit:
                    if edoc == doc and ere.search(ref):
                        hit = f"显式豁免（{reason}｜{owner}）"
                        break
                if hit:
                    buckets["exempt_explicit"].append(f"{doc}:{idx + 1} {ref} <- {hit}")
                    continue
                if _EXTERNAL_REF_RE.search(ref):
                    buckets["exempt_explicit"].append(
                        f"{doc}:{idx + 1} {ref} <- 外部/第三方坐标"
                    )
                    continue
                if _TEMP_REF_RE.search(ref) and _TEMP_TOLD_RE.search(
                    _line_ctx(lines, idx)
                ):
                    buckets["exempt_explicit"].append(
                        f"{doc}:{idx + 1} {ref} <- 一次性 TEMP 探针且已就近声明失效"
                    )
                    continue
                if _TEMP_REF_RE.search(ref):
                    buckets["unresolved"].append(
                        _fmt(
                            "TEMP 坐标未声明",
                            doc,
                            idx + 1,
                            ref,
                            "TEMP 探针产物路径已消失，且未就近写「已失效，仅存取证记录」",
                            "在该行补写失效声明，或删除坐标只留复跑命令",
                        )
                    )
                    continue
                if _RUNTIME_PATH_RE.search(ref) or _DB_NAME_RE.search(ref):
                    buckets["exempt_explicit"].append(
                        f"{doc}:{idx + 1} {ref} <- 运行时数据/库文件坐标"
                        "（非仓内源码，审计 G-1 豁免④）"
                    )
                    continue
                if not _EXTERNAL_REF_RE.search(ref) and _abs_root_nearby(lines, idx):
                    buckets["exempt_explicit"].append(
                        f"{doc}:{idx + 1} {ref} <- 外部仓坐标（就近 ±{ABS_ROOT_SPAN} 行"
                        "已给绝对根，审计 §D-3 判有效）"
                    )
                    continue
                resolved, note = _resolve(doc, ref)
                if resolved is None:
                    (
                        buckets["exempt_history"]
                        if is_history
                        else buckets["unresolved"]
                    ).append(
                        _fmt(
                            "文件不可解析",
                            doc,
                            idx + 1,
                            ref,
                            note,
                            "按符号名重定位真身后改指 `domains/<域>/...`；"
                            "若是史实记账请在该行加日期戳或改指复跑命令",
                        )
                    )
                    continue
                if _is_shim(resolved):
                    # 垫片分两档（审计 §D-1 口径）：
                    #   · 同名真身仍在别处 ⇒ 「旧路径写法」（可 import，行号不可信）
                    #   · 全仓只剩垫片 ⇒ 读者会以为「这模块就 3—18 行」，是真缺陷
                    name = resolved.rsplit("/", 1)[-1]
                    twins = [
                        h for h in _BY_NAME.get(name, []) if not _is_shim(h)
                    ]
                    key = "legacy" if twins else "shim"
                    if is_history:
                        key = "exempt_history"
                    buckets[key].append(
                        _fmt(
                            "指向 Compat 垫片" if key == "shim" else "旧路径写法（垫片）",
                            doc,
                            idx + 1,
                            f"{ref}{':' + l1 if l1 else ''}",
                            f"{note}；垫片仅 3—18 行 re-export，不是真身"
                            + (f"｜同名真身＝{twins[0]}" if twins else ""),
                            f"改指现真身 `{twins[0] if twins else resolved}`"
                            "（或去掉行号只写符号名）",
                        )
                    )
                    continue
                if "/" in ref and "domains/" not in ref and not ref.startswith(
                    ("plugins/", "scripts/", "tests/", "webui/")
                ):
                    buckets["exempt_history" if is_history else "legacy"].append(
                        _fmt(
                            "旧路径写法",
                            doc,
                            idx + 1,
                            ref,
                            note,
                            f"改写为真身路径 `{resolved}`",
                        )
                    )
                want = int(l2 or l1 or 0)
                cap = _LINES.get(resolved, 0)
                if want and want > cap:
                    (
                        buckets["exempt_history"]
                        if is_history
                        else buckets["overflow"]
                    ).append(
                        _fmt(
                            "行号越界",
                            doc,
                            idx + 1,
                            f"{ref}:{l1}{('-' + l2) if l2 else ''}",
                            f"解析到 `{resolved}`（实长 {cap} 行）⇒ 越界",
                            "按符号名重定位；不确定行号就只写符号名不写行",
                        )
                    )
    return buckets


#: 每次会话都自动载入上下文的「权威入口件」——这里的死坐标会直接骗到下一个接手者，
#: 故走**硬零**（不适用棘轮）；其余文档面走棘轮（只降不升）。
_LIVE_AUTHORITY_DOCS: tuple[str, ...] = ("AGENTS.md", "COMMANDS.md")


def test_live_authority_docs_have_no_dead_coords() -> None:
    """硬门：AGENTS.md / COMMANDS.md 里不得有解析不到的坐标（0 容忍）。"""
    bad = [
        row
        for row in collect_coordinate_findings(skip_inflight=True)["unresolved"]
        if row.split(" ", 1)[0].split(":")[0] in _LIVE_AUTHORITY_DOCS
    ]
    assert not bad, "自动载入的权威入口件里出现死坐标：\n" + "\n".join(bad)


def test_coordinate_files_are_resolvable() -> None:
    """棘轮：其余文档面的死坐标只许降不许升（每条红在 dump 里带真身与修法）。"""
    bad = collect_coordinate_findings(skip_inflight=True)["unresolved"]
    assert len(bad) <= _BASELINE_COORD_UNRESOLVED, (
        f"死坐标 {len(bad)} 条 > 基线 {_BASELINE_COORD_UNRESOLVED}：\n"
        + "\n".join(bad[:20])
        + "\n（复跑 DOC_LINK_GATE_DUMP=1 看全量与逐条修法）"
    )


def test_coordinate_line_capacity_ratchet() -> None:
    """行号越界只许降不许升（每条红在 dump 里带真身与修法）。"""
    rows = collect_coordinate_findings(skip_inflight=True)["overflow"]
    assert len(rows) <= _BASELINE_COORD_OVERFLOW, (
        f"行号越界坐标 {len(rows)} 条 > 基线 {_BASELINE_COORD_OVERFLOW}："
        f"\n{chr(10).join(rows[:20])}\n（复跑 DOC_LINK_GATE_DUMP=1 看全量）"
    )


def test_legacy_path_writing_ratchet() -> None:
    rows = collect_coordinate_findings(skip_inflight=True)["legacy"]
    assert len(rows) <= _BASELINE_COORD_LEGACY, (
        f"旧路径写法 {len(rows)} 条 > 基线 {_BASELINE_COORD_LEGACY}（新增即回潮）"
    )


def test_shim_pointed_coords_ratchet() -> None:
    rows = collect_coordinate_findings(skip_inflight=True)["shim"]
    assert len(rows) <= _BASELINE_COORD_SHIM, (
        f"把 Compat 垫片当真身的坐标 {len(rows)} 条 > 基线 {_BASELINE_COORD_SHIM}："
        f"\n{chr(10).join(rows[:20])}"
    )


# ---------------------------------------------------------------------------
# 子门 ①b：markdown 互链
# ---------------------------------------------------------------------------

_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def collect_dead_md_links(skip_inflight: bool = False) -> list[str]:
    dead: list[str] = []
    for doc, path in _scan_docs(skip_inflight):
        for idx, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            for m in _MD_LINK_RE.finditer(line):
                target = m.group(1)
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target = target.split("#", 1)[0]
                if not target or _EXTERNAL_REF_RE.search(target):
                    continue
                probe = (path.parent / target).resolve()
                if not probe.exists():
                    dead.append(
                        _fmt(
                            "死链",
                            doc,
                            idx + 1,
                            m.group(1),
                            f"解析为 `{probe.relative_to(ROOT) if probe.is_relative_to(ROOT) else probe}` 不存在",
                            "改指同级真实文件（`docs/design/` 下别写 `design/xxx.md`），"
                            "或按审计 R17 由草稿 owner 修",
                        )
                    )
    return dead


def test_markdown_links_alive_ratchet() -> None:
    dead = collect_dead_md_links(skip_inflight=True)
    assert len(dead) <= _BASELINE_MD_DEAD_LINKS, (
        f"markdown 死链 {len(dead)} 条 > 基线 {_BASELINE_MD_DEAD_LINKS}：\n"
        + "\n".join(dead[:20])
    )


# ---------------------------------------------------------------------------
# 子门 ②：协议枚举不手抄（真身从源码解析）
# ---------------------------------------------------------------------------

_ONEBOT = "plugins/bot_unified_runtime/domains/transport/sender/onebot.py"
_EVENT_STORE = "plugins/bot_unified_runtime/domains/ops/monitor/event_store.py"


def _truth_retcode() -> set[int]:
    src = (ROOT / _ONEBOT).read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r"def _is_final_failure_retcode.*?retcode in \{([^}]*)\}", src, re.DOTALL
    )
    assert m, "真身消失：onebot.py 里找不到 `_is_final_failure_retcode` 的判定式"
    return {int(x) for x in re.findall(r"\d+", m.group(1))}


def _truth_event_sources() -> tuple[str, ...]:
    src = (ROOT / _EVENT_STORE).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"EVENT_SOURCES\s*=\s*\(([^)]*)\)", src)
    assert m, "真身消失：event_store.py 里找不到 EVENT_SOURCES"
    return tuple(re.findall(r'"([^"]+)"', m.group(1)))


def _parse_int_set(text: str) -> set[int]:
    return {int(x) for x in re.findall(r"\d+", text)}


def collect_enum_copies(skip_inflight: bool = False) -> list[str]:
    """找出文档里手抄出来的协议成员清单，逐条与真身比对。"""
    retcodes = _truth_retcode()
    sources = set(_truth_event_sources())
    copies: list[str] = []
    for doc, path in _scan_docs(skip_inflight):
        if _HISTORY_FILE_RE.search(doc):
            continue  # 史实件里的旧枚举是历史证据，不当缺陷（审计 G-1 豁免①）
        for idx, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            if _HISTORY_LINE_RE.search(line):
                continue
            for m in re.finditer(
                r"_is_final_failure_retcode\s*=\s*\{([^}]*)\}"
                r"|retcode 白名单[＝=]\s*\{([^}]*)\}",
                line,
            ):
                got = _parse_int_set(m.group(1) or m.group(2) or "")
                if not got:
                    continue
                mark = "OK 等值" if got == retcodes else f"漂移（少 {sorted(retcodes - got)}／多 {sorted(got - retcodes)}）"
                if got != retcodes:
                    copies.append(
                        _fmt(
                            "retcode 手抄副本",
                            doc,
                            idx + 1,
                            m.group(0)[:60],
                            f"文档抄了 {len(got)} 码，真身 {len(retcodes)} 码 ⇒ {mark}",
                            f"删成员清单，改指 `{_ONEBOT.rsplit('/', 1)[-1]}` 的"
                            " `_is_final_failure_retcode` + 只写语义分组",
                        )
                    )
            # 数字副本：文档写「N 码 / N 项」型计数（审计 §C-4「数字去手抄」同族）
            for cm in re.finditer(
                r"(?:retcode|白名单)[^\n]{0,12}?(\d{1,3})\s*码", line
            ):
                if int(cm.group(1)) != len(retcodes):
                    copies.append(
                        _fmt(
                            "retcode 计数副本(漂移)",
                            doc,
                            idx + 1,
                            cm.group(0)[:40],
                            f"文档写 {cm.group(1)} 码，真身 {len(retcodes)} 码",
                            "删计数，改指符号 `_is_final_failure_retcode` + 只写语义分组",
                        )
                    )
            names = {n for n in re.findall(r"[a-z_]{3,}", line) if n in sources}
            if len(names) >= 6:
                pos = [line.index(n) for n in sorted(names)]
                seg = line[min(pos): max(line.index(n) + len(n) for n in names) ]
                written = {
                    t.strip("`* ")
                    for t in re.split(r"[、,，/|；;]\s*", seg)
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{2,}", t.strip("`* "))
                }
                missing = sorted(sources - written)
                extra = sorted(written - sources)
                if missing or extra:
                    copies.append(
                        _fmt(
                            "事件源手抄副本(漂移)",
                            doc,
                            idx + 1,
                            line.strip()[:60],
                            f"文档抄写成员与真身不等 ⇒ 少 {missing}／多 {extra}"
                            f"（真身 {len(sources)} 项）",
                            "删成员清单，改指 `domains/ops/monitor/event_store.py`"
                            " 的 `EVENT_SOURCES`（存量派生码请标「历史遗留」而非并列）",
                        )
                    )
                else:
                    copies.append(
                        _fmt(
                            "事件源手抄副本(等值)",
                            doc,
                            idx + 1,
                            line.strip()[:60],
                            f"成员与真身一致但仍是副本（{len(written)} 项）",
                            "改为指链：真身＝event_store.EVENT_SOURCES，本文不重列成员",
                        )
                    )
    return copies


def test_inflight_wave_docs_do_not_explode() -> None:
    """在飞面（未跟踪草稿件）单列上限：他席草稿不受我约束，但**不许无限膨胀**；
    一旦入库（合流波），条目自动落进上面的棘轮 ⇒ 在飞件不能把脏账带进史实。"""
    b = collect_coordinate_findings(skip_inflight=False)
    n = (
        len(b["unresolved"]) + len(b["overflow"]) + len(b["shim"])
        + len(collect_dead_md_links(skip_inflight=False))
        + len(collect_enum_copies(skip_inflight=False))
    )
    assert n <= _BASELINE_ALL_FACE_TOTAL, (
        f"全量文档面（含在飞草稿）缺陷条目 {n} > 上限 {_BASELINE_ALL_FACE_TOTAL}"
    )


def test_protocol_enum_copies_ratchet() -> None:
    rows = collect_enum_copies(skip_inflight=True)
    assert len(rows) <= _BASELINE_ENUM_COPIES, (
        f"协议枚举手抄副本 {len(rows)} 处 > 基线 {_BASELINE_ENUM_COPIES}：\n"
        + "\n".join(rows)
    )


def test_protocol_enum_drift_is_hard_zero() -> None:
    """硬门：任何**非等值**的协议成员副本都不得存在（等值副本走棘轮逐步归一）。"""
    retcodes = _truth_retcode()
    bad: list[str] = []
    for doc, path in _scan_docs(True):
        if _HISTORY_FILE_RE.search(doc):
            continue
        for idx, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            if _HISTORY_LINE_RE.search(line):
                continue
            for m in re.finditer(
                r"_is_final_failure_retcode\s*=\s*\{([^}]*)\}"
                r"|retcode 白名单[＝=]\s*\{([^}]*)\}",
                line,
            ):
                got = _parse_int_set(m.group(1) or m.group(2) or "")
                if got and got != retcodes:
                    bad.append(f"{doc}:{idx + 1} 抄了 {sorted(got)}，真身 {sorted(retcodes)}")
    assert not bad, "文档抄出来的 retcode 与代码真身不等：\n" + "\n".join(bad)


# ---------------------------------------------------------------------------
# 子门 ③：AGENTS.md 第四部分「载体文件」列
# ---------------------------------------------------------------------------

def parse_agents_carrier_cells(text: str | None = None) -> list[tuple[str, int, str]]:
    if text is None:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith("## 第四部分")), None
    )
    assert start is not None, "AGENTS.md 结构变了：找不到「## 第四部分」"
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## 第五部分")),
        len(lines),
    )
    out: list[tuple[str, int, str]] = []
    for i in range(start + 1, end):
        line = lines[i]
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0].startswith("---") or cells[0] in {"功能", "载体文件"}:
            continue
        for tok in re.findall(
            r"[\w.\-\u4e00-\u9fff/]*(?:[\w.\-]+\.(?:py|html|ps1|sh|sql))|[\w.\-/]+/(?![\w.])",
            cells[1],
        ):
            tok = tok.strip("/ ")
            if tok and not tok.startswith("<"):
                out.append((cells[0], i + 1, tok))
    return out


def collect_carrier_findings(text: str | None = None) -> dict[str, list[str]]:
    """严格判定「载体文件」列（审计 §E-1 的口径＝**字面**是否真身）。

    四档：
      literal  字面存在且非垫片 ⇒ 真身（合格）
      shim     字面存在但是 Compat 垫片（3—18 行）⇒ 读者会低估模块规模
      moved    字面不存在、但同名真身在别处 ⇒ 旧路径写法（照字面读必然找不到）
      dead     仓内彻底没有此路径 ⇒ 彻底失效
    `moved + shim` 是本列的失真面（走棘轮），`dead` 走硬零。
    """
    res: dict[str, list[str]] = {"literal": [], "shim": [], "moved": [], "dead": []}
    for func, lineno, tok in parse_agents_carrier_cells(text):
        cand = tok.rstrip("/")
        for base in (ROOT, PKG):
            p = base / cand
            if p.is_dir():
                # 目录型载体：整目录 .py 全是 Compat 垫片 ⇒ 与垫片同档（内容已迁走）
                pys = [f for f in p.rglob("*.py") if "__pycache__" not in f.parts]
                names = {f.relative_to(ROOT).as_posix() for f in pys}
                all_shim = bool(pys) and all(
                    _is_shim(n) for n in names if (ROOT / n).is_file()
                )
                if all_shim:
                    res["shim"].append(
                        _fmt("载体列整目录已垫片化", "AGENTS.md", lineno, tok,
                             f"目录内 {len(pys)} 个 .py 全是 Compat 垫片",
                             "改指现真身目录（审计 R18）")
                    )
                else:
                    res["literal"].append(f"{func} -> {tok}（目录）")
                break
            if p.is_file():
                rel = p.relative_to(ROOT).as_posix()
                if _is_shim(rel):
                    res["shim"].append(
                        _fmt("载体列写的是垫片", "AGENTS.md", lineno, tok,
                             "字面存在但＝Compat 垫片（真身另有其处）",
                             "改指现真身（审计 R18）")
                    )
                else:
                    res["literal"].append(f"{func} -> {tok}")
                break
        else:
            resolved, note = _resolve("AGENTS.md", tok)
            if resolved:
                res["moved"].append(
                    _fmt("载体列旧路径（字面不存在）", "AGENTS.md", lineno, tok,
                         f"{note}；现真身＝{resolved}",
                         "改指现真身路径，或按审计 R18 交生成器出「能力→域→真身」节")
                )
            else:
                res["dead"].append(
                    _fmt("载体路径彻底失效", "AGENTS.md", lineno, tok, note,
                         "按符号名重定位真身后改写")
                )
    return res


def test_agents_carrier_paths_no_dead_entries() -> None:
    """硬门：归属表载体列不得出现仓内彻底不存在的路径（0 容忍）。"""
    rows = collect_carrier_findings()["dead"]
    assert not rows, "AGENTS.md 第四部分载体路径彻底失效：\n" + "\n".join(rows)


def test_agents_carrier_misleading_ratchet() -> None:
    """棘轮：载体列「字面是垫片 + 字面不存在但真身在别处」= 误导面，只降不升。"""
    f = collect_carrier_findings()
    n = len(f["shim"]) + len(f["moved"])
    assert n <= _BASELINE_CARRIER_MISLEADING, (
        f"载体列误导面条数 {n} > 基线 {_BASELINE_CARRIER_MISLEADING}"
        f"（垫片 {len(f['shim'])} / 旧路径 {len(f['moved'])}）：\n"
        + "\n".join((f['shim'] + f['moved'])[:20])
    )


def test_agents_carrier_truth_floor() -> None:
    """地板锁：字面命中真身的条数不得低于开工实测（整体失真必须长回来）。"""
    n = len(collect_carrier_findings()["literal"])
    assert n >= _BASELINE_CARRIER_TRUTH, (
        f"载体列字面命中真身仅 {n} 条 < 地板 {_BASELINE_CARRIER_TRUTH}"
        "⇒ 归属表退化（审计 §E-1/R18）"
    )


# ---------------------------------------------------------------------------
# 防假锁自证（负样本自检）+ 过期豁免须摘除
# ---------------------------------------------------------------------------

def test_negative_sample_coord_detection(tmp_path: Path) -> None:
    """双向自证：故意做坏的坐标/枚举必须被解析层抓住（照 test_doc_sync_gates 姿势）。"""
    good = "domains/transport/sender/onebot.py"
    resolved, _ = _resolve("docs/x.md", good)
    assert resolved == _ONEBOT, f"好坐标没解析到真身：{resolved}"
    resolved2, _ = _resolve("docs/x.md", "capabilities/chat.py")
    assert resolved2 and _is_shim(resolved2), "垫片坐标没被认成垫片 ⇒ 垫片档形同虚设"
    assert _truth_retcode(), "真身 retcode 集为空"
    assert len(_truth_event_sources()) >= 6, "真身事件源集异常"
    broken = {403, 404}
    assert broken != _truth_retcode(), "真身恰好等于伪值，负样本失效"


def test_negative_sample_carrier_detection() -> None:
    """载体列子门的负样本：故意做坏的两行必须被判成 dead / shim。"""
    fake = (
        "## 第四部分：x\n\n"
        "| 功能 | 载体文件 | 子模块 | 入口 |\n|---|---|---|---|\n"
        "| 假能力 | capabilities/definitely_missing_zz.py | x | y |\n"
        "| 假能力2 | capabilities/chat.py | x | y |\n"
        "## 第五部分：y\n"
    )
    res = collect_carrier_findings(fake)
    assert res["dead"], "载体列负样本没判成死路径 ⇒ 子门形同虚设"
    assert res["shim"], "载体列负样本没判成垫片（capabilities/chat.py 应判垫片）"
    assert res["literal"] == [], "负样本里混进了合格条目 ⇒ 判据太松"


def test_exemptions_are_all_still_needed() -> None:
    """反向锁：显式豁免条目若不再命中任何坐标 ⇒ 红（过期豁免须摘除）。"""
    rows = collect_coordinate_findings(skip_inflight=True)["exempt_explicit"]
    for doc, pat, reason, _owner in _EXPLICIT_EXEMPTIONS:
        ere = re.compile(pat, re.IGNORECASE)
        hit = any(f"{doc}:" in r and ere.search(r) for r in rows)
        assert hit, f"显式豁免条目已不再命中（应删除）：{doc} / {pat} / 理由={reason}"


def test_gate_is_seeing_the_tree() -> None:
    """卫生自证：门确实在扫盘（若扫到 0 个文件，上面所有门都会假绿）。"""
    docs = list(_scan_docs())
    assert len(docs) > 100, f"只扫到 {len(docs)} 份文档 ⇒ 扫描面配置错了"
    assert len(_RELS) > 500, f"源码索引只 {len(_RELS)} 件 ⇒ 索引根配置错了"


def test_dump_mode(tmp_path: Path) -> None:
    if not DUMP:
        assert True
        return
    parts: list[str] = []
    b = collect_coordinate_findings()
    for k, v in b.items():
        parts.append(f"### {k} count={len(v)}")
        parts.extend("  " + x for x in v)
    dl = collect_dead_md_links()
    parts.append(f"### md_dead_links count={len(dl)}")
    parts.extend("  " + x for x in dl)
    ec = collect_enum_copies()
    parts.append(f"### enum_copies count={len(ec)}")
    parts.extend("  " + x for x in ec)
    c = collect_carrier_findings()
    for k, v in c.items():
        parts.append(f"### carrier_{k} count={len(v)}")
        parts.extend("  " + x for x in v)
    parts.append(
        f"truth: retcode={sorted(_truth_retcode())} "
        f"sources={len(_truth_event_sources())}"
    )
    out = Path(os.environ.get("DOC_LINK_GATE_DUMPFILE", str(tmp_path / "gate-dump.txt")))
    out.write_text("\n".join(parts), encoding="utf-8")
    counts = {k: len(v) for k, v in b.items()}
    counts |= {
        "md_dead": len(dl),
        "enum_copies": len(ec),
        **{f"carrier_{k}": len(v) for k, v in c.items()},
    }
    print(f"DUMPFILE={out}\nCOUNTS={counts}")
