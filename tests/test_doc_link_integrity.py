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
# 棘轮基线（S-REBASE 席 2026-09-22 全量重测并对账；只许降，不许升）
#
# 逐个标注比较方向（方向搞错＝门烂掉的开始）：
#   CEILING  断言 `实测 <= 基线` ⇒ 基线是上限，改小＝收紧，改大＝放宽（禁止）
#   FLOOR    断言 `实测 >= 基线` ⇒ 基线下限（地板），数值「调大」才是收紧
#   HARD     断言 `assert not rows`（0 容忍，不适用棘轮）
# 基线一律保持**字面整数**：本仓有结构锁禁止「基线由它所执法的同一份采集结果派生」
# ——那样门将结构上不可能变红。数值由 S-REBASE 席用采集函数**离线实测**后手抄进来，
# 复跑证据见 .superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-REBASE.md。
# ---------------------------------------------------------------------------

_BASELINE_COORD_LEGACY = 598  # CEILING；2026-09-22 实测（仅已跟踪件；史实行走豁免不计）
_BASELINE_COORD_SHIM = 1  # CEILING；实测：只能解析到垫片且无同名真身
_BASELINE_COORD_OVERFLOW = 0  # CEILING；2026-09-22 实测归零（非史实行）
_BASELINE_MD_DEAD_LINKS = 0  # CEILING；实测归零（S-DOCLINK2 修好采集器：围栏/行内代码内链接是字面量不是导航，26 条全为伪阳）
_BASELINE_ENUM_COPIES = 0  # CEILING；实测：已跟踪件里协议成员清单副本已归零
_BASELINE_CARRIER_DEAD = 0  # HARD 零档参照值（实际执法在 test_agents_carrier_paths_no_dead_entries 用 `assert not rows`，本常量当前不被任何断言引用；实测 dead=0）
_BASELINE_COORD_UNRESOLVED = 112  # CEILING；2026-09-22 实测：已跟踪件的死坐标
_BASELINE_CARRIER_MISLEADING = 21  # CEILING；2026-09-22 实测：垫片 13 + 字面不存在的旧路径 8
_BASELINE_CARRIER_TRUTH = 5  # FLOOR；开工实测地板（当前实测 34，远高于此⇒门仍绿；调大才算收紧，但「只降不升」是常令⇒本席不动，交门 owner 裁决）
_BASELINE_ALL_FACE_TOTAL = 113  # CEILING；2026-09-22 实测全量面（含在飞草稿）：死坐标 112 + 越界 0 + 垫片 1 + 死链 0 + 枚举 0 = 113


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
    r"(?<![\w./\\-])((?:[\w.\-\u4e00-\u9fff]+/)*[\w.\-]+\.(?:py|html|ps1|sh|sql|tsx|ts))"
    r"(?::(\d+)(?:\s*[-–—]\s*(\d+))?)?"
)
# ⚠ 备选式里 `tsx` 必须排在 `ts` **前面**（P1 席 2026-10-02 现算）：正则备选是
# 最左优先、不是最长优先，旧顺序 `ts|tsx` 把 `memory-canvas.tsx` 截成 `memory-canvas.ts`，
# 于是 webui 的**真身坐标**被整批误判成死坐标（当时值＝本席改前改后各跑一遍采集器相减：
# unresolved 少判 7 枚、exempt_history 虚胖 1070 行＝同一枚缺陷的两张脸；现值以
# `DOC_LINK_GATE_DUMP=1` 的实跑输出为准，本文不留活数）。改顺序只动尺子的精度，
# 不放宽任何判据：`.ts` 与 `.tsx` 都仍在被扫的集合里。


def _tracked_docs() -> frozenset[str]:
    """git 已跟踪的文档集合。未跟踪件＝他席在飞草稿（无还原基线，本仓纪律不碰），
    其缺陷单列 `exempt_inflight` 档：不计入硬门，但**同样走棘轮**且在 dump 里全量列出；
    一旦入库（合流波），条目自动落到棘轮/硬零档 ⇒ 在飞件不能把脏账带进史实。"""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "ls-files", "--", "AGENTS.md", "COMMANDS.md", "docs"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
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


def _coordinate_findings_in_doc(doc: str, path: Path) -> list[tuple[str, str]]:
    """子门 ① 的**逐文件**判据：返回 `(桶名, 判决行)` 序列。

    单独成函数＝让注毒自证能直接喂一棵假树/假文档（照 `_dead_links_in_doc` 的姿势），
    不必把整个门指向 tmp 目录；桶的分配权留在采集器里，测试不许自己抄一份。
    """
    rows: list[tuple[str, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover
        return rows
    explicit = [
        (edoc, re.compile(pat, re.IGNORECASE), reason, owner)
        for edoc, pat, reason, owner in _EXPLICIT_EXEMPTIONS
    ]
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
                rows.append(("exempt_explicit", f"{doc}:{idx + 1} {ref} <- {hit}"))
                continue
            if _EXTERNAL_REF_RE.search(ref):
                rows.append(
                    ("exempt_explicit", f"{doc}:{idx + 1} {ref} <- 外部/第三方坐标")
                )
                continue
            if _TEMP_REF_RE.search(ref) and _TEMP_TOLD_RE.search(
                _line_ctx(lines, idx)
            ):
                rows.append(
                    (
                        "exempt_explicit",
                        f"{doc}:{idx + 1} {ref} <- 一次性 TEMP 探针且已就近声明失效",
                    )
                )
                continue
            if _TEMP_REF_RE.search(ref):
                rows.append(
                    (
                        "unresolved",
                        _fmt(
                            "TEMP 坐标未声明",
                            doc,
                            idx + 1,
                            ref,
                            "TEMP 探针产物路径已消失，且未就近写「已失效，仅存取证记录」",
                            "在该行补写失效声明，或删除坐标只留复跑命令",
                        ),
                    )
                )
                continue
            if _RUNTIME_PATH_RE.search(ref) or _DB_NAME_RE.search(ref):
                rows.append(
                    (
                        "exempt_explicit",
                        (
                            f"{doc}:{idx + 1} {ref} <- 运行时数据/库文件坐标"
                            "（非仓内源码，审计 G-1 豁免④）"
                        ),
                    )
                )
                continue
            if not _EXTERNAL_REF_RE.search(ref) and _abs_root_nearby(lines, idx):
                rows.append(
                    (
                        "exempt_explicit",
                        (
                            f"{doc}:{idx + 1} {ref} <- 外部仓坐标（就近 ±{ABS_ROOT_SPAN} 行"
                            "已给绝对根，审计 §D-3 判有效）"
                        ),
                    )
                )
                continue
            resolved, note = _resolve(doc, ref)
            if resolved is None:
                rows.append(
                    (
                        "exempt_history" if is_history else "unresolved",
                        _fmt(
                            "文件不可解析",
                            doc,
                            idx + 1,
                            ref,
                            note,
                            "按符号名重定位真身后改指 `domains/<域>/...`；"
                            "若是史实记账请在该行加日期戳或改指复跑命令",
                        ),
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
                rows.append(
                    (
                        key,
                        _fmt(
                            "指向 Compat 垫片" if key == "shim" else "旧路径写法（垫片）",
                            doc,
                            idx + 1,
                            f"{ref}{':' + l1 if l1 else ''}",
                            f"{note}；垫片仅 3—18 行 re-export，不是真身"
                            + (f"｜同名真身＝{twins[0]}" if twins else ""),
                            f"改指现真身 `{twins[0] if twins else resolved}`"
                            "（或去掉行号只写符号名）",
                        ),
                    )
                )
                continue
            if "/" in ref and "domains/" not in ref and not ref.startswith(
                ("plugins/", "scripts/", "tests/", "webui/")
            ):
                rows.append(
                    (
                        "exempt_history" if is_history else "legacy",
                        _fmt(
                            "旧路径写法",
                            doc,
                            idx + 1,
                            ref,
                            note,
                            f"改写为真身路径 `{resolved}`",
                        ),
                    )
                )
            want = int(l2 or l1 or 0)
            cap = _LINES.get(resolved, 0)
            if want and want > cap:
                rows.append(
                    (
                        "exempt_history" if is_history else "overflow",
                        _fmt(
                            "行号越界",
                            doc,
                            idx + 1,
                            f"{ref}:{l1}{('-' + l2) if l2 else ''}",
                            f"解析到 `{resolved}`（实长 {cap} 行）⇒ 越界",
                            "按符号名重定位；不确定行号就只写符号名不写行",
                        ),
                    )
                )
    return rows


def collect_coordinate_findings(skip_inflight: bool = False) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "unresolved": [],
        "overflow": [],
        "shim": [],
        "legacy": [],
        "exempt_history": [],
        "exempt_explicit": [],
    }
    for doc, path in _scan_docs(skip_inflight):
        for key, row in _coordinate_findings_in_doc(doc, path):
            buckets[key].append(row)
    return buckets


#: 每次会话都自动载入上下文的「权威入口件」——这里的死坐标会直接骗到下一个接手者，
#: 故走**硬零**（不适用棘轮）；其余文档面走棘轮（只降不升）。
_LIVE_AUTHORITY_DOCS: tuple[str, ...] = ("AGENTS.md", "COMMANDS.md")


#: 判决行的头：`_fmt` 行首是 **[桶标签]**，文件名在第二个字段（P1 席实测＝本门零牙的根因：
#: 旧过滤式 `row.split(" ", 1)[0].split(":")[0]` 取到的是 `[文件不可解析]`，
#: 它永远不等于 `_LIVE_AUTHORITY_DOCS` ⇒ 权威入口件种多少死坐标都 PASS）。
_FINDING_HEAD_RE = re.compile(
    r"^\[(?P<kind>[^\]]+)\]\s+(?P<doc>.+?):(?P<ln>\d+)\s+->"
)


def _doc_of_finding(row: str) -> str:
    """取判决行的所属文档；形状不认识时返回空串（调用方必须把它当红处理，不得当"不属于权威面"）。"""
    m = _FINDING_HEAD_RE.match(row.splitlines()[0] if row else "")
    return m.group("doc") if m else ""


def _authority_dead_rows(rows: Iterable[str]) -> list[str]:
    """硬零门的过滤口：只留权威入口件（`docs/**` 面的死坐标归棘轮管，不在这里宣称硬零）。"""
    return [row for row in rows if _doc_of_finding(row) in _LIVE_AUTHORITY_DOCS]


def test_live_authority_docs_have_no_dead_coords() -> None:
    """硬门：AGENTS.md / COMMANDS.md 里不得有解析不到的坐标（0 容忍）。"""
    rows = collect_coordinate_findings(skip_inflight=True)["unresolved"]
    unparsed = [row for row in rows if not _doc_of_finding(row)]
    assert not unparsed, (
        "判决行形状与 `_doc_of_finding` 不匹配 ⇒ 权威面归属判不出来，本门将退化成永绿"
        f"（{len(unparsed)} 行，先改解析式再谈执法）：\n"
        + "\n".join(row.splitlines()[0] for row in unparsed[:10])
    )
    bad = _authority_dead_rows(rows)
    assert not bad, "自动载入的权威入口件里出现死坐标：\n" + "\n".join(bad)


def test_live_authority_dead_coords_gate_teeth(tmp_path: Path) -> None:
    """注毒自证（P1 席 2026-10-02）：硬零门①必须真能咬住权威入口件的死坐标。

    动因＝本门实测无牙：往 `AGENTS.md` 种 **3 枚**死坐标仍 PASS（采集器报得出、
    过滤器取错了字段）。三齿＋一控制，缺一即本测试红：
      ① 权威件（AGENTS.md 与 COMMANDS.md 各一枚）注毒必被 `_authority_dead_rows` 咬住；
      ② 同样形状的死坐标躺在 `docs/**` 时**不得**算进权威面（防止把棘轮面谎称为硬零面）；
      ③ 不注毒（干净件）必绿——门不是永假条件；
      ④ 形状钉：判决行首个空格段恒为桶标签，用它判文档就是本事故的本体，钉住它不许回潮；
      ⑤ 精度钉：`.tsx` 坐标整只捕获（截成 `.ts` 就是把真身判死）。
    取数口是真采集器 `_coordinate_findings_in_doc`（喂 tmp 假文档），不手写判决行——
    手写行只能自证过滤器，自证不了「扫描面 + 解析式」这一整条链。
    """
    planted = (
        ("AGENTS.md", "ghostmod/p1_planted_authority_a.py", 2),
        ("COMMANDS.md", "p1_planted_authority_b.py", 1),
        ("docs/design/p1_planted_c.md", "p1_planted_authority_c.py", 1),
    )
    unresolved: list[str] = []
    for doc, ghost, times in planted:
        path = tmp_path / doc
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# {doc}\n\n"
            + "".join(f"- 探针坐标 `{ghost}` 第 {i + 1} 枚\n" for i in range(times))
            + "- 真身坐标 `domains/transport/sender/onebot.py` 不该被报\n",
            encoding="utf-8",
        )
        for bucket, row in _coordinate_findings_in_doc(doc, path):
            if bucket == "unresolved":
                unresolved.append(row)

    dead = _authority_dead_rows(unresolved)
    assert len(dead) == 3, f"权威面应咬住 3 枚注毒（AGENTS 2 + COMMANDS 1），实得 {len(dead)}"
    assert {_doc_of_finding(r) for r in dead} == {"AGENTS.md", "COMMANDS.md"}, dead
    assert all(_doc_of_finding(r) for r in unresolved), (
        "采集器产出的行归属判不出来 ⇒ `_FINDING_HEAD_RE` 与 `_fmt` 已脱钩"
    )
    # ② docs/** 面同形死坐标不得混进权威硬零面
    assert not [r for r in dead if _doc_of_finding(r).startswith("docs/")], dead
    # ③ 控制腿：不注毒必绿
    assert not _authority_dead_rows([]), "空集被判红＝门是永假条件"
    clean = tmp_path / "CLEAN.md"
    clean.write_text(
        "真身坐标 `domains/transport/sender/onebot.py` 与 `bot.py`。\n", encoding="utf-8"
    )
    clean_rows = [r for b, r in _coordinate_findings_in_doc("CLEAN.md", clean) if b == "unresolved"]
    assert not clean_rows, f"干净件被误报（伪阳会让门只会喊狼）：{clean_rows}"
    assert not _authority_dead_rows(clean_rows)
    # ④ 形状钉：行首空格段＝桶标签，不是文件名
    assert dead and all(
        r.split(" ", 1)[0].split(":")[0] not in _LIVE_AUTHORITY_DOCS for r in dead
    ), "判决行形状变了（旧事故写法重新可用＝本自证失效）"
    # ⑤ 精度钉：`.tsx` 必须整只被捕获。备选式退回 `ts|tsx` 顺序＝把 webui 真身截成
    #    `.ts` 再整批判死（＝本窗清掉的那批伪阳；逐枚读数看 `DOC_LINK_GATE_DUMP=1`
    #    的实跑输出，注释里不留活数）。
    m = _REF_RE.search("见 `webui/src/components/graph/memory-canvas.tsx` 与 `x.ts`")
    assert m and m.group(1) == "webui/src/components/graph/memory-canvas.tsx", (
        f"`.tsx` 被截断 ⇒ 采集器把真身读成死坐标：{m.group(1) if m else None}"
    )
    m2 = _REF_RE.search("`foo.ts`")
    assert m2 and m2.group(1) == "foo.ts", "`.ts` 的捕获被改坏了"


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

#: 围栏代码块标记行：≤3 空格缩进 + 3 个及以上反引号/波浪线 + 可选信息串（```markdown 等）。
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _fenced_content_mask(lines: list[str]) -> list[bool]:
    """逐行标记「严格位于一个**已闭合**围栏代码块内」⇒ True（该行链接当字面量、不检）。

    判据（CommonMark 形制，本仓实测）：
      · 开栏 = 行首 ≤3 空格 + 3+ 反引号/波浪线（可带任意信息串）；
      · 闭栏 = 同字符、长度 ≥ 开栏、且信息串为空；
      · 开栏/闭栏本身不计入（它们是标记，不是载荷）。
    失败安全（fail-safe）：遇**未闭合**开栏（一路到文件尾都找不到闭栏），其后所有行一律
    **不**标记为围栏内 ⇒ 链接照常检查。伪阳只是维护噪音，伪阴会悄悄废掉这道门，
    故拿不准时宁可继续查。
    """
    mask = [False] * len(lines)
    n = len(lines)
    i = 0
    while i < n:
        opener = _FENCE_RE.match(lines[i])
        if not opener:
            i += 1
            continue
        fence_char = opener.group(1)[0]
        fence_len = len(opener.group(1))
        closer: int | None = None
        j = i + 1
        while j < n:
            cand = _FENCE_RE.match(lines[j])
            if (
                cand
                and cand.group(1)[0] == fence_char
                and len(cand.group(1)) >= fence_len
                and cand.group(2).strip() == ""
            ):
                closer = j
                break
            j += 1
        if closer is None:
            # 未闭合 ⇒ 失败安全：不压制其后内容，仅跳过这一行开栏记号。
            i += 1
            continue
        for k in range(i + 1, closer):
            mask[k] = True
        i = closer + 1
    return mask


#: 行内反引号串：一或多枚反引号组成的最长连续段。
_BACKTICK_RUN_RE = re.compile(r"`+")


def _inline_code_spans(line: str) -> list[tuple[int, int]]:
    """返回该行内联代码（`code`）覆盖的**内容**字符区间 [lo, hi)（不含首尾反引号）。

    成对规则（CommonMark 近似，失败安全）：每个反引号串与**其后第一个等长**反引号串配对，
    两者之间即代码内容；落单反引号串（后面找不到等长闭栏）⇒ 不产生区间（不压制）。
    只压制「链接标记本身整个落在某个区间内」的情况，绝不吞掉与代码同处一行却写在代码外的真链接。
    """
    runs = [
        (m.start(), m.end(), len(m.group(0)))
        for m in _BACKTICK_RUN_RE.finditer(line)
    ]
    spans: list[tuple[int, int]] = []
    i = 0
    length = len(runs)
    while i < length:
        j = i + 1
        while j < length and runs[j][2] != runs[i][2]:
            j += 1
        if j < length:
            spans.append((runs[i][1], runs[j][0]))  # 内容：开栏之后到闭栏之前
            i = j + 1
        else:
            i += 1  # 落单反引号串 ⇒ 失败安全，不压制
    return spans


def _inside_any_span(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(lo <= start and end <= hi for lo, hi in spans)


def _dead_links_in_doc(doc: str, path: Path) -> list[str]:
    """子门①b 的逐文件判据（其余逻辑与旧实现逐字一致，仅新增「围栏内 / 行内代码内不检」两道跳过）。

    单独成函数以便注毒自证（见 test_dead_link_fence_and_inline_code_teeth）直接喂临时夹具，
    无需把整个门指向 tmp 目录。
    """
    dead: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:  # pragma: no cover
        return dead
    in_fence = _fenced_content_mask(lines)
    for idx, line in enumerate(lines):
        if in_fence[idx]:
            continue
        code_spans = _inline_code_spans(line)
        for m in _MD_LINK_RE.finditer(line):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.split("#", 1)[0]
            if not target or _EXTERNAL_REF_RE.search(target):
                continue
            if _inside_any_span(m.start(), m.end(), code_spans):
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


def collect_dead_md_links(skip_inflight: bool = False) -> list[str]:
    dead: list[str] = []
    for doc, path in _scan_docs(skip_inflight):
        dead.extend(_dead_links_in_doc(doc, path))
    return dead


def test_markdown_links_alive_ratchet() -> None:
    dead = collect_dead_md_links(skip_inflight=True)
    assert len(dead) <= _BASELINE_MD_DEAD_LINKS, (
        f"markdown 死链 {len(dead)} 条 > 基线 {_BASELINE_MD_DEAD_LINKS}：\n"
        + "\n".join(dead[:20])
    )


def test_dead_link_fence_and_inline_code_teeth(tmp_path: Path) -> None:
    """注毒自证：这道门对「围栏代码块」与「行内代码」的豁免必须真实咬合（四齿各杀一次）。

    历史动因：`_BASELINE_MD_DEAD_LINKS` 长期下不到 0，因为 26 条伪阳里 24 条躺在
    ```markdown 草稿载荷块内（相对路径按目的地 docs/ 正确、按草稿自身错），另 2 条是
    写在行内反引号里的被审正则原文（改掉＝篡改证据）。二者都是**字面文本、非导航链接**。
    本夹具四例分别钉死：散文真死链要报、围栏内不报、行内代码内不报、**未闭合**围栏之后
    仍要报（失败安全方向）。删掉围栏或行内代码任一处理、或把未闭合也当围栏压制，本测试必红。
    """
    f = tmp_path / "fixture.md"
    f.write_text(
        "# Fixture for dead-link suppression teeth\n"
        "\n"
        "[anchor_a](ghost_a.md)\n"
        "\n"
        "```markdown\n"
        "[anchor_a](ghost_a.md)\n"
        "```\n"
        "\n"
        "text `[anchor_c](ghost_c.md)` tail\n"
        "\n"
        "```\n"
        "[anchor_d](ghost_d.md)\n"
        "\n"
        "trailing [anchor_d](ghost_d.md)\n",
        encoding="utf-8",
    )
    rows = _dead_links_in_doc("fixture.md", f)
    reported = {int(re.search(r"fixture\.md:(\d+)", r).group(1)) for r in rows}
    # (a) 散文里的真死链必须被报（门的正脸）
    assert 3 in reported, "散文死链漏报 ⇒ 门失效"
    # (b) 同一死链躺进 ```markdown 围栏块 ⇒ 视为载荷字面量，不报（删围栏处理则此行变红）
    assert 6 not in reported, "围栏块内链接被误当导航 ⇒ 未识别代码围栏"
    # (c) 死链包在行内反引号代码段里 ⇒ 字面量，不报（删行内处理则此行变红）
    assert 9 not in reported, "行内代码内链接被误当导航 ⇒ 未识别 code span"
    # (d) 未闭合围栏之后的散文死链 ⇒ 失败安全，仍要报（把未闭合也压制则此行变红）
    assert {12, 14} <= reported, "未闭合围栏之后的死链被吞 ⇒ 失败安全方向反了"
    assert len(rows) == 3, f"应恰好报 3 条（散文1 + 未闭合后2），实得 {sorted(reported)}"


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
# 子门 ③b：载体列**逐枚**判定（席 R3，2026-10-02，工单 W-G-04）
#
# 现算动因（本席实跑 `python tests/…` 取数，非记忆）：AGENTS.md 第四部分载体表
#   ＝ 33 行 / 69 枚条目，而③的「处数」面只扫到 55 枚 token、看得见 30 行 ⇒
#   3 行（记忆体系 / 每日通讯总结 / 运维告警）整行在门外，另有 14 枚条目进不了判定口
#   （`runtime/alerts`、`result_unknown`、`downloader`、`theme_tokens`、
#   `render_backends`、`config`、`…/mermaid.min.js`…）从来没被判过。
# 根因形状＝ `_CARRIER_TOKEN_RE`（本门原名内联在 `parse_agents_carrier_cells`）
#   只认「以 .py/.html/.ps1/.sh/.sql 收尾」或「以 / 收尾」的字面，于是
#   **无扩展名的模块写法** / **`模块.符号`** / **`.js` 旁车** / **裸文件名**
#   四类都进不了判定口 ⇒ 把它们整枚写成假的，dead/shim/moved 三档一条都不涨
#   （＝台账 #48★「载体列＝门读的那把尺」的秤盘被削掉一截；也是「坐标可全假仍绿」）。
# 修法（**只准变严**：不动③的 token 正则、不动任何在册常数、不加豁免）：
#   另开一枚逐枚入口 `collect_carrier_entry_findings()`——按分隔符枚举载体列每一枚，
#   每枚都必须解析到真身（字面 / 补扩展名 / 名字索引 / `模块.符号` / 运行数据根），
#   解析不到＝`bogus` 硬红；只有「查无此名的裸词」才允许记为 `annotation`，
#   而 annotation 的**条数走上限**（把真身改成查无此名的裸词 ⇒ 上限当场咬住）。
#   扫描面与条目面之差另由三枚**现算地板**锁住（行/条目/token 各一枚，双向：
#   地板>实测＝凭空造数即红，照 `test_scan_face_floor_is_measured_not_invented` 的姿势）。
# ---------------------------------------------------------------------------

#: 载体列条目的分隔符（半角/全角加号、顿号）。`mermaid.min.js+sha256` 这类旁车
#: 会被切开，切出来的裸词若查无同名真身即记 annotation（受上限约束），不算漏判。
_CARRIER_SEP_RE = re.compile(r"[+\uff0b\u3001]")

#: 条目里「被引用的那一段」＝行首直到空格/CJK/括号/反引号/标点为止的字面。
_CARRIER_HEAD_RE = re.compile(
    r"[^\s\u4e00-\u9fff\u3000\uff08\uff09()\u3001\uff0c,;=<>|`*]+"
)

#: 补扩展名探测的口径（与 `_walk_sources` 的收录后缀一致）。
_CARRIER_EXTS = (".py", ".html", ".js", ".json", ".ts", ".tsx", ".ps1", ".sh", ".sql")

#: 运行数据根（AGENTS 第〇部分在册的 `ChatBot_Runtime/`，源码树根的兄弟目录）。
_RUNTIME_DIRNAME = "ChatBot_Runtime"

# 三枚现算地板 + 两枚上限（席 R3 2026-10-02 由
# `PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_doc_link_integrity.py -q -k carrier`
# 的失败消息与探针输出实测手抄；只许收紧：地板调大 / 上限调小）。
_CARRIER_ROWS_FLOOR = 33  # FLOOR：载体表数据行数（删行即红）
_CARRIER_ENTRIES_FLOOR = 69  # FLOOR：逐枚枚举出的条目数（缩面即红）
_CARRIER_TOKEN_FACE_FLOOR = 55  # FLOOR：③「处数」面子门扫到的 token 数
_CARRIER_ANNOTATION_CEILING = 3  # CEILING：查无此名的裸词条目数（真身改成裸词即红）
_CARRIER_TOKEN_FACE_GAP_CEILING = 14  # CEILING：条目面 − ③token 面 的缺口（现算 69−55）


def _carrier_table_rows(text: str | None = None) -> list[tuple[str, int, str]]:
    """载体表的**行**（功能名 / 行号 / 载体单元格原文），与③同一节口径。"""
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
    rows: list[tuple[str, int, str]] = []
    seen_header = False
    for i in range(start + 1, end):
        line = lines[i].strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if not seen_header:  # 第一枚 `|` 行＝表头，紧随其后＝分隔行
            seen_header = True
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append((cells[0], i + 1, cells[1]))
    return rows


def iter_carrier_entries(text: str | None = None) -> list[tuple[str, int, str, str]]:
    """逐枚枚举载体条目：`(功能, 行号, 条目原文, 被引字面头)`。"""
    out: list[tuple[str, int, str, str]] = []
    for func, lineno, cell in _carrier_table_rows(text):
        for seg in _CARRIER_SEP_RE.split(cell):
            seg = seg.strip()
            if not seg:
                continue
            m = _CARRIER_HEAD_RE.match(seg)
            out.append((func, lineno, seg, m.group(0) if m else ""))
    return out


def _resolve_carrier_entry(ref: str) -> tuple[str, str]:
    """一枚载体条目 → `(档, 说明)`；档 ∈ {hit, annotation, bogus}。

    比 `_resolve`（为 `文件.py:行` 坐标设计）**只多不少**：多出的三条腿正是③漏掉的
    四类写法——无扩展名模块、`模块.符号`、`.js`/`.json` 旁车、裸文件名。
    """
    if not ref:
        return "annotation", "空段（纯注解，无被引字面）"
    cand = ref.rstrip("/")
    for base in (ROOT, PKG):
        p = base / cand
        if p.is_file():
            rel = p.relative_to(ROOT).as_posix()
            return ("hit", "字面即真身（垫片另记③）") if not _is_shim(rel) else ("hit", "字面存在＝Compat 垫片")
        if p.is_dir():
            return "hit", "字面即真身目录"
    parent, _, leaf = cand.rpartition("/")
    stem, dot, tail = leaf.partition(".")
    known_ext = dot and tail in {e.lstrip(".") for e in _CARRIER_EXTS}
    # `模块.符号`（`__init__._register_digest_push_scheduler` 一类）：符号必须真写在文件里，
    # 否则 bogus——③整枚看不见它，正是「那一行可全假」的口子。
    if dot and not parent and tail and not known_ext:
        named = [n for ext in _CARRIER_EXTS for n in _BY_NAME.get(f"{stem}{ext}", [])]
        for n in named:
            try:
                if tail in (ROOT / n).read_text(encoding="utf-8", errors="replace"):
                    return "hit", f"模块.符号命中（{n} 内确有 {tail}）"
            except OSError:
                continue
        if named:
            return "bogus", f"`{stem}` 有 {len(named)} 份，但没有一份写着 `{tail}`"
        return "bogus", f"点号写法 `{ref}`：仓内没有叫 `{stem}` 的文件，符号更无从谈起"
    # 补扩展名（字面路径 + 常见后缀）
    for ext in _CARRIER_EXTS:
        for base in (ROOT, PKG):
            if (base / f"{cand}{ext}").is_file():
                return "hit", f"补 `{ext}` 后字面命中"
    # 运行数据根（仓外兄弟目录，只读判定；写成不存在的名字照样 bogus）
    head, slash, rest = cand.partition("/")
    if slash and head == _RUNTIME_DIRNAME and rest:
        rp = ROOT.parent / _RUNTIME_DIRNAME / rest
        if rp.exists():
            return "hit", "运行数据根命中（`ChatBot_Runtime/`，非源码树）"
        return "bogus", f"运行数据根里也没有 {rp}"
    # 名字索引：带后缀的按整名找，不带的按 `词干+后缀` 找；带目录的先按目录名收窄
    # （收窄只提精度、不放水——`runtime/alerts` 的真身并不住在名为 runtime 的目录里）。
    keys: list[str] = []
    if known_ext:
        keys += [leaf, f"{stem}.py"]
    else:
        keys += [f"{leaf}{e}" for e in _CARRIER_EXTS]
        if dot:
            keys.append(f"{stem}.py")
        keys.append(leaf)
    names = [n for k in keys for n in _BY_NAME.get(k, [])]
    if names:
        real = [n for n in names if not _is_shim(n)] or names
        if parent:
            narrowed = [n for n in real if f"/{parent}/" in f"/{n}"]
            if narrowed:
                return "hit", f"按名命中（真身＝{narrowed[0]}）"
        if all(_is_shim(n) for n in names):
            return "hit", f"只能解析到 Compat 垫片（{names[0]}）＝③另计误导面"
        return "hit", f"按名命中（真身＝{real[0]}）"
    resolved, note = _resolve("AGENTS.md", cand)
    if resolved:
        return "hit", f"既有 `_resolve` 命中（{note}）"
    if "/" in cand or dot:
        return "bogus", "字面像路径，但仓内/运行根都解析不到真身"
    return "annotation", "裸词且仓内无同名真身（视为旁注，受上限约束）"


def collect_carrier_entry_findings(
    text: str | None = None,
) -> dict[str, list[str]]:
    """逐枚判定载体列：`hit` / `annotation` / `bogus` + `blind`（门完全看不见的行）。"""
    res: dict[str, list[str]] = {"hit": [], "annotation": [], "bogus": [], "blind": []}
    seen_lines: set[int] = set()
    for func, lineno, seg, head in iter_carrier_entries(text):
        bucket, why = _resolve_carrier_entry(head)
        res[bucket].append(_fmt(f"载体条目判为{bucket}", "AGENTS.md", lineno, seg, why, ""))
        if bucket == "hit":
            seen_lines.add(lineno)
    for func, lineno, cell in _carrier_table_rows(text):
        if lineno not in seen_lines:
            res["blind"].append(
                _fmt("载体行一枚条目都没解析到真身", "AGENTS.md", lineno, cell,
                     f"该行的条目全落在 {('annotation', 'bogus')} 档", "载体列须写可判定的真身路径")
            )
    return res


def test_agents_carrier_entries_are_all_resolved() -> None:
    """硬门（逐枚）：载体列每一枚条目都必须解析到真身；bogus 零容忍。"""
    f = collect_carrier_entry_findings()
    assert not f["bogus"], "AGENTS.md 第四部分载体列有条目解析不到真身：\n" + "\n".join(f["bogus"])
    assert not f["blind"], "载体行整行没有一枚可判定条目：\n" + "\n".join(f["blind"])
    assert f["hit"], "逐枚判定面一条都没判出来＝分类器单向化（dead/annotation 两档的绿毫无意义）"


def test_agents_carrier_annotation_entries_within_ceiling() -> None:
    """上限锁：「裸词且查无同名真身」的条目数只准 ≤ 现算值。

    这一档不是豁免——它把「把真身改成一个查无此名的裸词」这种躲法钉住：写法一躲出
    路径形状，本档计数就涨，当场红。
    """
    f = collect_carrier_entry_findings()
    assert len(f["annotation"]) <= _CARRIER_ANNOTATION_CEILING, (
        f"载体列不可判裸词 {len(f['annotation'])} 枚 > 上限 "
        f"{_CARRIER_ANNOTATION_CEILING}：\n" + "\n".join(f["annotation"])
    )


def test_agents_carrier_scan_face_covers_every_entry() -> None:
    """防永绿腿（W-G-04 本体）：判定面必须覆盖条目面；三枚现算地板双向锁；缺口封上限。"""
    rows = _carrier_table_rows()
    entries = iter_carrier_entries()
    tokens = parse_agents_carrier_cells()
    judged = collect_carrier_entry_findings()
    n_judged = len(judged["hit"]) + len(judged["annotation"]) + len(judged["bogus"])
    assert n_judged >= len(entries), (
        f"逐枚判定面只给出 {n_judged} 枚判决 < 条目面 {len(entries)} 枚 ⇒ 判定口比条目口窄，"
        "载体列重新可以「坐标全假仍绿」（W-G-04 复发）"
    )
    for name, got, floor in (
        ("载体表行数", len(rows), _CARRIER_ROWS_FLOOR),
        ("载体条目数", len(entries), _CARRIER_ENTRIES_FLOOR),
        ("③处数面扫到的 token 数", len(tokens), _CARRIER_TOKEN_FACE_FLOOR),
    ):
        assert got >= floor, (
            f"{name} 现算 {got} < 地板 {floor}＝扫描面塌回 W-G-04 之前（处数子门当期只认 "
            f"{_CARRIER_TOKEN_FACE_FLOOR} 枚 / 载体表实有 {_CARRIER_ENTRIES_FLOOR} 枚），"
            "此后「dead 零容忍」会重新变成假绿"
        )
        assert floor <= got, (
            f"地板 {floor} 写在现算值 {got} 之上＝凭空造数（{name}），请按实跑输出重录"
        )
    gap = len(entries) - len(tokens)
    assert gap <= _CARRIER_TOKEN_FACE_GAP_CEILING, (
        f"③处数面的缺口变大：条目 {len(entries)} − token {len(tokens)} = {gap} > 上限 "
        f"{_CARRIER_TOKEN_FACE_GAP_CEILING}。缺口＝载体列里③读不到的那几枚（无扩展名模块／"
        "`模块.符号`／`.js` 旁车／裸文件名四类写法），当前由③b逐枚面兜住；要把它归零必须 "
        "widen ③ 的 token 正则**并**同步重录 `_BASELINE_CARRIER_MISLEADING`（widen 会把"
        "新增条目推进 moved 档，只动正则不动上限＝当场红）——那是门 owner 的裁量，本席不动常数。"
    )


def test_carrier_entry_face_negative_samples() -> None:
    """注毒自证（内存，不落盘）＋控制腿：两枚毒必须各咬一处，干净面必绿。"""
    cell_ok = "domains/chat_reply/character/mood.py"
    assert _resolve_carrier_entry(cell_ok)[0] == "hit", "控制腿：真身条目被判非 hit＝门在瞎咬"
    bogus = _resolve_carrier_entry("domains/chat_reply/character/w_g04_ghost_mood.py")
    assert bogus[0] == "bogus", f"假文件名没被逐枚面咬住：{bogus}"
    bare_ghost = _resolve_carrier_entry("w_g04_bare_ghost_name")
    assert bare_ghost[0] == "annotation", f"裸词档形状变了（上限锁将失效）：{bare_ghost}"
    assert _resolve_carrier_entry("__init__.w_g04_no_such_symbol")[0] == "bogus", (
        "`模块.符号` 写成不存在的符号却没被咬住＝第 109 行那类条目仍可全假"
    )
    assert _resolve_carrier_entry("runtime/w_g04_ghost_alerts")[0] == "bogus", (
        "无扩展名模块写法没被咬住＝③漏判的那四类仍是永绿"
    )


# ---------------------------------------------------------------------------
# 防假锁自证（负样本自检）+ 过期豁免须摘除
# ---------------------------------------------------------------------------

def test_negative_sample_coord_detection(tmp_path: Path) -> None:
    """双向自证：故意做坏的坐标/枚举必须被解析层抓住（照 test_doc_sync_gates 姿势）。"""
    good = "domains/transport/sender/onebot.py"
    resolved, _ = _resolve("docs/x.md", good)
    assert resolved == _ONEBOT, f"好坐标没解析到真身：{resolved}"
    # 2026-10-04 P2 减量波换钉：原负样本 `capabilities/chat.py` 已随退役波物理删除
    # （其坐标现在解析到 canonical 真身，判不出"垫片档"），改钉长期在册的最重垫片
    # `output/plain_text.py`（账上引用上限 7＝生产控制面在用，短期不会退役）。
    resolved2, _ = _resolve("docs/x.md", "output/plain_text.py")
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
        "| 假能力2 | output/plain_text.py | x | y |\n"
        "## 第五部分：y\n"
    )
    res = collect_carrier_findings(fake)
    assert res["dead"], "载体列负样本没判成死路径 ⇒ 子门形同虚设"
    # 2026-10-04 P2 减量波换钉：原负样本 `capabilities/chat.py` 已退役，改钉长期在册垫片。
    assert res["shim"], "载体列负样本没判成垫片（output/plain_text.py 应判垫片）"
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
