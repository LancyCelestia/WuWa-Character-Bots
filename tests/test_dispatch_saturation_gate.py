"""G-C1 —— 调度饱和门（dispatch saturation gate）。席位 S11；P-59/P-99「A 案」改造（2026-10-13）。

本门把 G-C1 从「只活在任务书里」变成一道真门。执法面 = 「并行满载」这条用户裁定的
可机检形态：**有空位 + 仍有待办切片 + 主会话在等**（SEAT-MAIN.md §12.5 自伤记 #1 的原话）。

七条腿（对 `BRIEFS.md`《S11 GATE-GC1》逐条实现；腿 7 为 2026-10-13 P-59 A 案新增）
- 腿 1 `test_backfill_log_dispatch_is_saturated`：解析真实补派日志表，**按每行自己的「当时上限」**
  判（第 6 列，见 `_underdispatch_violations`）；任一行「当时在飞数 < 该行当时上限 且仍有待办切片」⇒ 红。
- 腿 2 `test_snapshot_*`：机器可验第二腿——读外部 `find` 现算后写入的
  `DISPATCH-SNAPSHOT.json`（门**绝不自起进程去猜**，只读快照），校验其形状/来源与活跃席数。
- 腿 3 `test_synthetic_*`：反向自测——内存注「在飞数=6 且仍有待办」⇒必红，注「=当时上限」⇒放行。
- 腿 4 `test_scan_surface_floor`：日志表行数地板（防「空表蒙绿」）。
- 腿 5 `test_baseline_literals_are_handwritten`：基线（含 `CEILING_EPOCHS`）必须是手写字面量，
  且本自锁对 `Assign` 与 `AnnAssign` 双形态都认（防「改个写法就躲开自锁」/防派生式基线）。
- 腿 6 `test_snapshot_freshness_*`：快照新鲜度锁（陈旧快照不得充当「当前顶满」证据）。
- 腿 7 `test_epoch_registry_*`：① 结构锁——§12.5 窗口内数据行**列数必须 ∈ {5,6}**、第 4 列必须取到
  整数，异形行**点名报错而非静默跳过**（治「账具形状错 ⇒ 门瞎」）；② 反洗锁——每行「当时上限」
  声明必须等于按行时间戳从 `CEILING_EPOCHS` 派生的值（防「被审计者自己把尺填小」洗掉真账）。

设计取舍（如实记，见 SEAT-S11.md / P59-A-PLAN.md / SEAT-MAIN.md §贰零）：
- 原设计用**单一均匀阈值 CEILING**（原判据字面 10；用户 2026-09-22T16:32Z「断电续跑 + 并发条款改版」
  第一条把它**一次性改判为 15**，方向＝变严，属 §7 禁写面的一次性例外）。均匀尺**回溯判历史**
  会把「旧 5 席／10 席纪律期」里其实已顶满当时上限的行也判红——那是**已知的过度执法**（P-59/P-14）。
- P-59 A 案（用户 2026-10-13 授权「判据结构加上去，采取最好的方法」）＝补派表加第 6 列「当时上限」、
  门按行阈值判（**缺列回退当前 `CEILING`**，故新行仍按 15 咬）。
- **本改造不会让腿 1 变绿，也不该变绿**：它把红从 23 条缩到 **6 条真账**
  （`04:27Z`×2 / `04:45Z` / `05:28Z` / `05:41Z` / `2026-09-23T16:30Z`），这 6 条是主会话自己记在
  §12.5「本席自伤记」与 §12.5b 里的**真实少派**，按纪律**必须留红**——消红只有两条路：
  伪造历史（禁）或缩小扫描面（禁）。P-59 A 案消掉 18 条「均匀尺过度执法」的假红
  （各行其实已顶满自己的当时上限：5/5、5/5、10×16）；
  另有 1 条（`16:30Z` 在飞 17 < 当时上限 20）此前被均匀尺（15）放过，本改造把它**捞回执法面**。
"""

from __future__ import annotations

import ast
import datetime as _dt
import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# 基线字面量（腿 4 / 腿 5）：必须手写字面量，绝不 `= len(...)` 派生（派生式基线＝门永远绿）。
# ---------------------------------------------------------------------------

#: 补派日志表**至少**应有的数据行数（防「删空表 ⇒ 蒙绿」）。
#: 本席开工时现算 §12.5 = 11 行；主代理只追加不删，故此为**地板**（只降触发红、不随手抬）。
DISPATCH_LOG_MIN_ROWS: int = 11

#: 调度饱和上限 = 用户 2026-09-22 改判的并发席位数：05:51Z 起十席同条消息派齐，
#: 16:32Z「断电续跑 + 并发条款改版」第一条把它**一次性提到 15**（方向＝变严，见本文件头注）。
#: 「有空位」＝在飞数 < 此值。腿 3 的反向自测即钉死这个阈值的语义。
#: **本值只作两用**：① 第 6 列「当时上限」缺列的**回退值**（新行仍按它咬）；② 快照腿（腿 2）的现役上限。
CEILING: int = 15

#: 纪元登记表（P-59 A 案 · 反洗锁，腿 7②）：`(生效起点 UTC, 该期满载上限)`，按行时间戳派生。
#: **手写字面量，禁派生**（与 `CEILING` 同受腿 5 自锁）——它把「当时上限」的真值钉在**门文件**里，
#: 而不是留在被审计者能改的补派表里，故补派表的第 6 列**不能自己把尺填小**来洗掉真账。
#: 证据（逐条可复跑，见 P59-A-PLAN.md §2 与 SEAT-MAIN.md 对应行）：
#:   5  —— §12.5 `03:37Z`/`03:41Z` 表内自注「（5 席，旧纪律上限 5）」「5（旧纪律 5 满）」
#:   10 —— §12.5 `04:45Z` 行内「M4-R3 ＋（**并发改判 10 席**）S1/S2/S3 三席」（切点乙，S260 推荐）
#:   15 —— §贰零 用户 2026-09-22T16:32Z 一次性授权（原阈值行逐字抄录在同节）
#:   10 —— §12.5a 第 50 批（`06:09:20Z`）「满载档由 15 降到 10＝用户改令，非本席少派」
#:   20 —— §12.5a 第 58 批（`11:48:49Z`）「本批起满载档 10→**20**＝用户 20 席令」
CEILING_EPOCHS: tuple[tuple[str, int], ...] = (
    ("2026-09-22T00:00:00Z", 5),
    ("2026-09-22T04:45:00Z", 10),
    ("2026-09-22T16:32:00Z", 15),
    ("2026-09-23T06:09:20Z", 10),
    ("2026-09-23T11:48:49Z", 20),
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TAXONOMY_DIR = _REPO_ROOT / ".superpowers" / "sdd" / "2026-09-22-taxonomy"
_SEAT_MAIN = _TAXONOMY_DIR / "SEAT-MAIN.md"
_SNAPSHOT = _TAXONOMY_DIR / "DISPATCH-SNAPSHOT.json"

_CELL_SPLIT = re.compile(r"\s*\|\s*")
#: 行首时间戳（``2026-09-22T03:37Z`` / ``2026-09-23T02:12:50Z`` 两形态）；秒缺省按 00 归一。
_TIMESTAMP_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?Z")


# ---------------------------------------------------------------------------
# 解析与判据（纯函数：真实表、合成表、快照共用同一把尺子）
# ---------------------------------------------------------------------------


def _leading_int(text: str) -> int | None:
    """取单元格里第一个整数（如 ``5（旧纪律 5 满）``→5、``**10**``→10、``0``→0）。"""
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def _has_pending(text: str) -> bool:
    """「仍有待办切片」列：以「是」开头即算有待办（含 ``是（队列 …）`` 这类带注解的写法）。"""
    return text.strip().startswith("是")


def _normalize_timestamp(text: str) -> str | None:
    """``…T03:37Z`` / ``…T02:12:50Z`` → ``YYYY-MM-DDTHH:MM:SSZ``（秒缺省补 00）；取不到即 ``None``。"""
    match = _TIMESTAMP_RE.search(text)
    if not match:
        return None
    year, month, day, hh, mm, ss = match.groups()
    return f"{year}-{month}-{day}T{hh}:{mm}:{ss or '00'}Z"


def _epoch_ceiling(timestamp: str) -> int | None:
    """按行时间戳从 `CEILING_EPOCHS` 派生「当时上限」（反洗锁腿 7② 的唯一标尺）。"""
    key = _normalize_timestamp(timestamp)
    if key is None:
        return None
    value: int | None = None
    for cut, ceiling in CEILING_EPOCHS:
        if cut <= key:
            value = ceiling
    return value


def _parse_backfill_rows(markdown_text: str) -> list[dict[str, object]]:
    """解析 SEAT-MAIN.md §12.5 的补派日志表（**五或六列**）。表外内容一律忽略。

    第 6 列「当时上限」存在时入 ``row["ceiling"]``；缺列 ⇒ ``None``（判据回退当前 `CEILING`）。
    """
    try:
        after = markdown_text.split("### 12.5", 1)[1]
    except IndexError as exc:  # pragma: no cover - 结构缺失属事故，必须显式暴露
        raise AssertionError("SEAT-MAIN.md 缺 §12.5 补派日志表标题，取数面塌了") from exc
    section = after.split("### 12.6", 1)[0]

    rows: list[dict[str, object]] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = _CELL_SPLIT.split(line.strip("|").strip())
        cells = [c.strip() for c in cells]
        if len(cells) not in (5, 6):
            continue
        first = cells[0]
        if first.startswith("时间戳"):  # 表头
            continue
        if first and set(first) <= set("-: "):  # 分隔行
            continue
        if _leading_int(cells[3]) is None:  # 无「在飞数」整数 ⇒ 非数据行
            continue
        rows.append(
            {
                "timestamp": first,
                "closed": cells[1],
                "dispatched": cells[2],
                "in_flight": _leading_int(cells[3]),
                "pending": _has_pending(cells[4]),
                "ceiling": _leading_int(cells[5]) if len(cells) == 6 else None,
            }
        )
    return rows


def _underdispatch_violations(rows: list[dict[str, object]], *, ceiling: int = CEILING) -> list[str]:
    """腿 1/2/3 共用的判据：返回「有空位且仍有待办」的行（即该派没派）。

    **按行判**（P-59 A 案）：`row["ceiling"]` 存在则用它当该行的「当时上限」，缺列回退 `ceiling`
    实参（真实表里即当前 `CEILING`，故新行仍按 15 咬；合成行不传 `ceiling` 键亦同）。
    """
    violations: list[str] = []
    for row in rows:
        in_flight = row["in_flight"]
        if in_flight is None:  # pragma: no cover - 解析器已过滤，防御性双保险
            continue
        row_ceiling = row.get("ceiling") or ceiling
        if bool(row["pending"]) and int(in_flight) < int(row_ceiling):
            violations.append(
                f"{row['timestamp']} 在飞数={in_flight}（<{row_ceiling}＝当时上限）且仍有待办切片"
            )
    return violations


def _read_backfill_rows() -> list[dict[str, object]]:
    return _parse_backfill_rows(_SEAT_MAIN.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 腿 4 —— 扫描面地板（先跑：空表 / 结构塌 直接红，别让后面的「零违规」是假绿）
# ---------------------------------------------------------------------------


def test_scan_surface_floor_rows_present() -> None:
    """补派日志表必须解析出「足够多」的数据行——防「把表删空⇒判红为零⇒蒙绿」。"""
    assert _SEAT_MAIN.exists(), f"取数面缺失：{_SEAT_MAIN}"
    rows = _read_backfill_rows()
    assert (
        len(rows) >= DISPATCH_LOG_MIN_ROWS
    ), f"§12.5 只解析出 {len(rows)} 行，低于地板 {DISPATCH_LOG_MIN_ROWS}——扫描面被缩小，拒绝放行"
    # 每行都必须真拿到整数在飞数与待办布尔，否则「地板达标」也是空壳。
    for row in rows:
        assert isinstance(row["in_flight"], int)
        assert isinstance(row["pending"], bool)


# ---------------------------------------------------------------------------
# 腿 1 —— 真实历史表执法（有空位 + 有待办 ⇒ 红）
# ---------------------------------------------------------------------------


def test_backfill_log_dispatch_is_saturated() -> None:
    """每一笔补派当时都必须「顶满到上限」或「确实没有待办了」。有例外即红。"""
    rows = _read_backfill_rows()
    violations = _underdispatch_violations(rows, ceiling=CEILING)
    assert not violations, (
        "G-C1：补派日志表存在「有空位 + 仍有待办 + 主会话在等」而未顶满的记录：\n  "
        + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# 腿 3 —— 反向自测（判据本身真的会红，也不误伤满员）
# ---------------------------------------------------------------------------


def test_synthetic_underdispatch_is_red() -> None:
    """注毒：在飞数=6 且仍有待办 ⇒ 判据必须抓到（否则本门形同虚设）。"""
    poison = [{"timestamp": "SYNTH", "closed": "x", "dispatched": "y", "in_flight": 6, "pending": True}]
    violations = _underdispatch_violations(poison, ceiling=CEILING)
    assert len(violations) == 1, f"在飞数=6+有待办应判红，实得 {violations}"


def test_synthetic_saturated_passes() -> None:
    """对照：在飞数=CEILING 且仍有待办 ⇒ 放行（判据不过度执法到「满员」）。

    这里**故意写 `CEILING` 而不是字面量**：本用例钉的是「判据用 `<` 而非 `<=`」这条语义，
    与阈值具体是 10 还是 15 无关；写死数字会在用户改判阈值时假红，且那种红不携带任何信息。
    阈值本身的手写字面量要求由腿 5 `test_baseline_literals_are_handwritten` 守。
    """
    ok = [{"timestamp": "SYNTH", "closed": "x", "dispatched": "y", "in_flight": CEILING, "pending": True}]
    assert _underdispatch_violations(ok, ceiling=CEILING) == []


def test_synthetic_no_pending_passes() -> None:
    """对照：在飞数=2 但确无待办 ⇒ 放行（本门只管「有空位却没派」，不管「无事可派」）。"""
    ok = [{"timestamp": "SYNTH", "closed": "x", "dispatched": "y", "in_flight": 2, "pending": False}]
    assert _underdispatch_violations(ok, ceiling=CEILING) == []


def test_synthetic_per_row_ceiling_is_honoured() -> None:
    """反向自测（P-59 A 案核心）：同一枚在飞数，按**行内**上限判 ⇒ 满员放行、缺一即红。

    ``in_flight=10, ceiling=10`` ⇒ 绿；``in_flight=9, ceiling=10`` ⇒ 红。
    这钉的是「判据读的是行内上限、不是全局 `CEILING`」——若判据仍用全局 `CEILING=15`，
    两枚都会判红，本用例即失败。
    """
    saturated = [
        {"timestamp": "SYNTH", "closed": "x", "dispatched": "y", "in_flight": 10, "pending": True, "ceiling": 10}
    ]
    assert _underdispatch_violations(saturated, ceiling=CEILING) == []
    short = [
        {"timestamp": "SYNTH", "closed": "x", "dispatched": "y", "in_flight": 9, "pending": True, "ceiling": 10}
    ]
    assert len(_underdispatch_violations(short, ceiling=CEILING)) == 1


def test_parser_extracts_in_flight_from_annotated_cells() -> None:
    """解析器自证：'5（旧纪律 5 满）'→5、'**10**'→10、'0'→0；表头/分隔行不算数据行；
    第 6 列「当时上限」存在 ⇒ 入 ``ceiling``，缺列 ⇒ ``None``（判据回退当前 `CEILING`）。"""
    sample = (
        "### 12.5 补派日志表\n"
        "| 时间戳(UTC) | 交卷/阵亡席位 | 补进去的席位 | 当时在飞数 | 仍有待办切片 | 当时上限 |\n"
        "|---|---|---|---|---|---|\n"
        "| 2026-01-01T00:00Z | a | b | 5（旧纪律 5 满） | 是 | 5 |\n"
        "| 2026-01-01T00:01Z | a | b | **10** | 是 | 10 |\n"
        "| 2026-01-01T00:02Z | a | b | 0 | 是 |\n"
        "### 12.6 next\n"
    )
    rows = _parse_backfill_rows(sample)
    assert [r["in_flight"] for r in rows] == [5, 10, 0]
    assert [r["ceiling"] for r in rows] == [5, 10, None]
    assert all(r["pending"] for r in rows)


# ---------------------------------------------------------------------------
# 腿 2 —— 机器可验第二腿（读快照，门绝不自起 find 去猜）
# ---------------------------------------------------------------------------


def _read_snapshot() -> dict[str, object]:
    assert _SNAPSHOT.exists(), (
        f"缺 G-C1 机器可验快照 {_SNAPSHOT.name}——第二腿没有数据源。"
        "须外部执行 find 现算活跃席数后写入，门只读不猜。"
    )
    return json.loads(_SNAPSHOT.read_text(encoding="utf-8"))


def test_snapshot_shape_and_provenance() -> None:
    """快照形状 + 来源可机检：必须点名 subagents + newermt，杜绝手写臆造一个数。"""
    snap = _read_snapshot()
    for key in ("captured_at_utc", "window_seconds", "active_seats", "source_command"):
        assert key in snap, f"快照缺字段 {key}"
    assert isinstance(snap["active_seats"], int) and snap["active_seats"] >= 0
    assert isinstance(snap["window_seconds"], int) and snap["window_seconds"] > 0
    src = str(snap["source_command"])
    assert "subagents" in src and "-newermt" in src and "find" in src, (
        "source_command 不像那条 find 现算命令（应含 find / subagents / -newermt），"
        "否则第二腿不是机器可验而是手抄"
    )
    # captured_at 必须是可解析的 UTC 时间戳（供审计新鲜度）。避开 strptime 裸构造（DTZ007）。
    stamp = str(snap["captured_at_utc"])
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$", stamp)
    assert m, f"captured_at_utc 非 YYYY-MM-DDTHH:MM:SSZ 形态：{stamp!r}"
    year, month, day, hh, mm, ss = (int(g) for g in m.groups())
    captured = _dt.datetime(year, month, day, hh, mm, ss, tzinfo=_dt.timezone.utc)
    assert captured <= _dt.datetime.now(_dt.timezone.utc), "快照 captured_at 在未来——时间戳造假"


def test_snapshot_active_seats_meet_ceiling() -> None:
    """现算活跃席数须顶满到上限——快照记录不足上限即红（诚实反映抓取时刻的真实现场）。"""
    snap = _read_snapshot()
    active = int(snap["active_seats"])
    violations = _underdispatch_violations(
        [{"timestamp": "SNAPSHOT", "closed": "", "dispatched": "", "in_flight": active, "pending": True}],
        ceiling=CEILING,
    )
    assert not violations, (
        f"G-C1 第二腿：快照现算活跃席数={active}（<{CEILING}）——"
        f"抓取时刻（{snap['captured_at_utc']}）未顶满，重跑 source_command 后更新快照"
    )


# ---------------------------------------------------------------------------
# 腿 7（P-59 A 案 · 2026-10-13 用户授权「判据结构加上去」）—— 结构锁 + 反洗锁
#
# 为什么这两条是 A 案的**必需件**、不是锦上添花（施工图 `P59-A-PLAN.md` §5.1）：
#   ① 加第 6 列时，旧解析器的 `if len(cells) != 5: continue` 会把**整表静默丢行**
#      （实跑：`rows_parsed` 16→0，地板腿才抓得住「全塌」、抓不住「塌一半」）。改造前盘上已有一行
#      （§12.5 的 `17:29Z` 行，列数畸形）因此**从未被解析**——本波已把它修回执法面（`rows_parsed` 65→66）。
#   ② 只加列不加反洗锁 ⇒ 判据变成「被审计者自己填的尺」：把某行的「当时上限」写成 ≤ 在飞数
#      即可把真账洗绿，而 `rows_parsed` 与地板腿**完全看不见**（`P59-A-PLAN.md` §5.1 命令③实证）。
# ---------------------------------------------------------------------------


def _malformed_data_lines(markdown_text: str) -> list[str]:
    """§12.5 窗口内「以 | 开头 + 首格像时间戳」的行里，列数 ∉ {5,6} 或第 4 列取不到整数的行。

    表头/分隔行（首格非时间戳形态）不在此列。
    """
    try:
        after = markdown_text.split("### 12.5", 1)[1]
    except IndexError as exc:  # pragma: no cover - 结构缺失属事故
        raise AssertionError("SEAT-MAIN.md 缺 §12.5 补派日志表标题，取数面塌了") from exc
    section = after.split("### 12.6", 1)[0]
    bad: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in _CELL_SPLIT.split(stripped.strip("|").strip())]
        if not cells or not _TIMESTAMP_RE.match(cells[0]):
            continue
        if len(cells) not in (5, 6) or _leading_int(cells[3]) is None:
            bad.append(stripped[:80])
    return bad


def test_backfill_rows_have_no_malformed_shape() -> None:
    """结构锁（腿 7①）：补派表数据行**不许有畸形列数**——畸形行要「点名报错」而非被静默跳过。

    红 = 账具形状错（如缺一枚 ASCII 竖线把两格粘成一格）。这不是「测试坏了」，是设计意图：
    被静默丢掉的整行等于**从执法面上消失**，而地板腿只看总行数，看不见「塌一行」。
    """
    bad = _malformed_data_lines(_SEAT_MAIN.read_text(encoding="utf-8"))
    assert not bad, (
        "G-C1 结构锁（腿 7①）：补派表存在列数畸形、会被静默丢行的数据行（应点名修复账具）：\n  "
        + "\n  ".join(bad)
    )


def test_declared_ceiling_matches_epoch_registry() -> None:
    """反洗锁（腿 7②）：每行「当时上限」声明必须等于按行时间戳从 `CEILING_EPOCHS` 派生的值。

    缺列的行走回退值 `CEILING`（＝新行仍按现役尺咬）。声明 ≠ 派生即点名——这是防「把尺填小
    洗掉真账」的唯一一道锁（地板腿与行数完全看不见这种洗法）。
    """
    rows = _read_backfill_rows()
    mismatches: list[str] = []
    for row in rows:
        declared = row.get("ceiling") or CEILING
        derived = _epoch_ceiling(str(row["timestamp"]))
        if declared != derived:
            mismatches.append(f"{row['timestamp']} 声明={declared} 登记表派生={derived}")
    assert not mismatches, (
        "G-C1 反洗锁（腿 7②）：补派表「当时上限」声明与纪元登记表不一致（疑似洗账或填错）：\n  "
        + "\n  ".join(mismatches)
    )


def test_malformed_row_is_caught_synthetic() -> None:
    """反向自测：注一枚 4 列数据行 ⇒ 结构锁必须点名（否则结构锁形同虚设）。"""
    sample = "### 12.5 x\n| 2026-01-01T00:00Z | a | b | 是 |\n### 12.6 next\n"
    assert _malformed_data_lines(sample), "4 列数据行必须被结构锁点名"


def test_ceiling_registry_derivation_synthetic() -> None:
    """反向自测：纪元派生在五个切点上正确（5→10→15→10→20 的阶跃），非时间戳 ⇒ None。"""
    assert _epoch_ceiling("2026-09-22T03:37Z") == 5
    assert _epoch_ceiling("2026-09-22T04:44:59Z") == 5
    assert _epoch_ceiling("2026-09-22T04:45Z") == 10
    assert _epoch_ceiling("2026-09-22T16:32Z") == 15
    assert _epoch_ceiling("2026-09-23T06:09:20Z") == 10
    assert _epoch_ceiling("2026-09-23T11:48:49Z") == 20
    assert _epoch_ceiling("not-a-timestamp") is None


# ---------------------------------------------------------------------------
# 腿 5 —— 基线自锁（手写字面量 + Assign/AnnAssign 双形态）
# ---------------------------------------------------------------------------


def test_baseline_literals_are_handwritten() -> None:
    """DISPATCH_LOG_MIN_ROWS / CEILING 必须是**手写的整数字面量**、`CEILING_EPOCHS` 必须是
    **手写的 (字符串, 整数) 元组**，且本自锁认全两种赋值形态。

    防三类假绿：① 派生式基线（``= len(rows)`` ⇒ 门永远绿）；
    ② 换一种写法躲自锁（只认 ``Assign`` 就会漏掉 ``AnnAssign``，反之亦然）；
    ③ 把纪元登记表算出来（``= tuple(...)``）⇒ 反洗锁的「真值」跟着被审计者走，锁即失效。
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    baselines = {"DISPATCH_LOG_MIN_ROWS", "CEILING"}
    found: dict[str, str] = {}
    epochs_found = False
    for node in tree.body:  # 仅看模块顶层赋值
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.expr):
            targets = [node.target]
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            value = node.value  # type: ignore[attr-defined]
            kind = type(node).__name__
            if target.id in baselines:
                assert isinstance(value, ast.Constant) and isinstance(
                    value.value, int
                ), f"{target.id} 不是手写字面量（是 {ast.dump(value)}）——基线不许派生"
                found[target.id] = kind
            elif target.id == "CEILING_EPOCHS":
                assert isinstance(value, ast.Tuple), (
                    f"CEILING_EPOCHS 必须是手写元组字面量（是 {ast.dump(value)}）——登记表不许派生"
                )
                assert value.elts, "CEILING_EPOCHS 不许为空"
                for elt in value.elts:
                    assert isinstance(elt, ast.Tuple) and len(elt.elts) == 2, (
                        f"CEILING_EPOCHS 每项须是 (起算时刻, 上限) 二元组：{ast.dump(elt)}"
                    )
                    cut, ceiling = elt.elts
                    assert isinstance(cut, ast.Constant) and isinstance(cut.value, str)
                    assert isinstance(ceiling, ast.Constant) and isinstance(ceiling.value, int)
                epochs_found = True
    assert set(found) == baselines, f"基线自锁：只见到 {set(found)}，应含 {baselines}"
    assert epochs_found, "基线自锁：未见到手写字面量 CEILING_EPOCHS"


# ---------------------------------------------------------------------------
# 腿 6（席位 S99 / P-52）—— 快照新鲜度锁：陈旧快照不得永久充当「当前顶满」证据
#
# S80 Q-1 实证：既有腿 2 `test_snapshot_shape_and_provenance` 只验形状与「不在未来」
# （:217-223），没有新鲜度上限 ⇒ 一枚昨天的快照仍能证明「今天顶满」。今日 9<10 恰好红
# 是运气不是执法。本腿把「可核验时长」钉成一档硬锁：
#     N = 快照自报的 window_seconds（**由窗口派生、绝不写死魔数**）
# 理由：窗口内活跃席数只在「距抓取 ≤ 窗口本身」时才自洽可复核；一旦快照比它声称测量的
# 窗口还老，那枚数不再代表现场。N 的唯一来源就是快照里的 window_seconds，故不新建第二本账、
# 不需要新的门常量（`test_baseline_literals_are_handwritten` 的字面量集合一字未动）。
# ---------------------------------------------------------------------------


def _utc_from_stamp(stamp: str) -> _dt.datetime:
    """``YYYY-MM-DDTHH:MM:SSZ`` → aware UTC。与腿 2 同尺（避开 strptime 裸构造 DTZ007）。"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$", stamp)
    assert m, f"captured_at_utc 非 YYYY-MM-DDTHH:MM:SSZ 形态：{stamp!r}"
    year, month, day, hh, mm, ss = (int(g) for g in m.groups())
    return _dt.datetime(year, month, day, hh, mm, ss, tzinfo=_dt.timezone.utc)


def _freshness_violation(
    captured: _dt.datetime, now: _dt.datetime, window_seconds: int
) -> str | None:
    """新鲜度判据的唯一标尺。返回 ``None``=放行；否则返回点名年龄的违例文案。

    上限 ``N = window_seconds``（派生，非魔数）：``age > N`` 或 ``age < 0``（未来）即不合格。
    边界 ``age == N`` 放行（「不超过」语义）。
    """
    assert window_seconds > 0, "window_seconds 必须为正（形状腿同样要求）"
    age_seconds = (now - captured).total_seconds()
    if age_seconds < 0:
        return f"快照 captured_at 在未来 {abs(age_seconds):.0f}s——时间戳造假，判不合格"
    if age_seconds > window_seconds:
        return (
            f"快照已过时 {age_seconds:.0f}s，超过新鲜度上限 N=window_seconds={window_seconds}s"
            "——陈旧快照不得充当「当前顶满」证据，请重跑 scripts/dispatch_saturation_snapshot.py --verify"
        )
    return None


def test_snapshot_freshness_derivation_synthetic() -> None:
    """反向自测三发（纯内存，不落盘）：未来⇒红、2×N⇒红且点名年龄、新鲜⇒绿。

    特意取 ``window_seconds=30``（非缺省 60）——若上限被写死成某个魔数，这枚用例就会因
    「换个窗口仍按 60 判」而露馅；只有真正从 window_seconds 派生才会 2×N=60s 判红。
    """
    window = 30
    now = _dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=_dt.timezone.utc)
    # (a) 未来时间戳 ⇒ 红
    future = now + _dt.timedelta(seconds=5)
    assert _freshness_violation(future, now, window) is not None, "未来时间戳必须判不合格"
    # (b) 过期 2×N ⇒ 红，且文案点名年龄（60s）
    stale = now - _dt.timedelta(seconds=2 * window)
    msg = _freshness_violation(stale, now, window)
    assert msg is not None, "过期 2×N 必须判不合格"
    assert "60" in msg, f"违例文案须点名年龄，实得 {msg!r}"
    # (c) 新鲜 ⇒ 绿（窗口内）
    fresh = now - _dt.timedelta(seconds=window - 1)
    assert _freshness_violation(fresh, now, window) is None, "窗口内应放行"
    # 边界：age == N 放行（「超过」才红，非「达到」）
    edge = now - _dt.timedelta(seconds=window)
    assert _freshness_violation(edge, now, window) is None, "边界 age==N 应放行"


def test_real_snapshot_is_fresh() -> None:
    """真值锁：盘上快照距 now 不得超过它自报的 window_seconds（P-52 收口 S80 Q-1）。

    红 = 快照已陈旧 ⇒ 这不是「测试坏了」，而是设计意图：陈旧证据不被静默采信，
    须由 scripts/dispatch_saturation_snapshot.py --verify 重拍后再判（判定必须伴随重拍）。
    """
    snap = _read_snapshot()
    window = snap["window_seconds"]
    assert isinstance(window, int) and window > 0, f"window_seconds 非正整数：{window!r}"
    captured = _utc_from_stamp(str(snap["captured_at_utc"]))
    violation = _freshness_violation(captured, _dt.datetime.now(_dt.timezone.utc), window)
    assert violation is None, f"G-C1 新鲜度锁（腿 6）：{violation}"
