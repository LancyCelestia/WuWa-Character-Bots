"""G-C1 —— 调度饱和门（dispatch saturation gate）。席位 S11。

本门把 G-C1 从「只活在任务书里」变成一道真门。执法面 = 「并行满载」这条用户裁定的
可机检形态：**有空位 + 仍有待办切片 + 主会话在等**（SEAT-MAIN.md §12.5 自伤记 #1 的原话）。

五条腿（对 `BRIEFS.md`《S11 GATE-GC1》逐条实现）
- 腿 1 `test_backfill_log_dispatch_is_saturated`：解析真实补派日志表，任一行
  「当时在飞数 < CEILING 且仍有待办切片」⇒ 红。
- 腿 2 `test_snapshot_*`：机器可验第二腿——读外部 `find` 现算后写入的
  `DISPATCH-SNAPSHOT.json`（门**绝不自起进程去猜**，只读快照），校验其形状/来源与活跃席数。
- 腿 3 `test_synthetic_*`：反向自测——内存注「在飞数=6 且仍有待办」⇒必红，注「=CEILING」⇒放行。
- 腿 4 `test_scan_surface_floor`：日志表行数地板（防「空表蒙绿」）。
- 腿 5 `test_baseline_literals_are_handwritten`：基线必须是手写字面量，且本自锁对
  `Assign` 与 `AnnAssign` 双形态都认（防「改个写法就躲开自锁」/防派生式基线）。

设计取舍（如实记，见 SEAT-S11.md）：腿 1 用**均匀阈值 CEILING**（原判据字面 10；用户 2026-09-22T16:32Z
「断电续跑 + 并发条款改版」第一条把它**一次性改判为 15**，方向为变严，属 §7 禁写面的一次性例外，
原阈值行逐字抄录与「为何是收紧不是放宽」见 SEAT-MAIN.md §贰零）。
它会把「旧 5 席纪律期」里其实已满（在飞 5 = 当时上限 5）的历史行也判红——那是本门已知
的过度执法，按「不为了让门绿去改表」的纪律照实报红，并在报告里逐行分类。
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
CEILING: int = 15

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TAXONOMY_DIR = _REPO_ROOT / ".superpowers" / "sdd" / "2026-09-22-taxonomy"
_SEAT_MAIN = _TAXONOMY_DIR / "SEAT-MAIN.md"
_SNAPSHOT = _TAXONOMY_DIR / "DISPATCH-SNAPSHOT.json"

_CELL_SPLIT = re.compile(r"\s*\|\s*")


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


def _parse_backfill_rows(markdown_text: str) -> list[dict[str, object]]:
    """解析 SEAT-MAIN.md §12.5 的补派日志表（五列）。表外内容一律忽略。"""
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
        if len(cells) != 5:
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
            }
        )
    return rows


def _underdispatch_violations(rows: list[dict[str, object]], *, ceiling: int = CEILING) -> list[str]:
    """腿 1/2/3 共用的判据：返回「有空位且仍有待办」的行（即该派没派）。"""
    violations: list[str] = []
    for row in rows:
        in_flight = row["in_flight"]
        if in_flight is None:  # pragma: no cover - 解析器已过滤，防御性双保险
            continue
        if bool(row["pending"]) and int(in_flight) < ceiling:
            violations.append(
                f"{row['timestamp']} 在飞数={in_flight}（<{ceiling}）且仍有待办切片"
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


def test_parser_extracts_in_flight_from_annotated_cells() -> None:
    """解析器自证：'5（旧纪律 5 满）'→5、'**10**'→10、'0'→0；表头/分隔行不算数据行。"""
    sample = (
        "### 12.5 补派日志表\n"
        "| 时间戳(UTC) | 交卷/阵亡席位 | 补进去的席位 | 当时在飞数 | 仍有待办切片 |\n"
        "|---|---|---|---|---|\n"
        "| 2026-01-01T00:00Z | a | b | 5（旧纪律 5 满） | 是 |\n"
        "| 2026-01-01T00:01Z | a | b | **10** | 是 |\n"
        "| 2026-01-01T00:02Z | a | b | 0 | 是 |\n"
        "### 12.6 next\n"
    )
    rows = _parse_backfill_rows(sample)
    assert [r["in_flight"] for r in rows] == [5, 10, 0]
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
# 腿 5 —— 基线自锁（手写字面量 + Assign/AnnAssign 双形态）
# ---------------------------------------------------------------------------


def test_baseline_literals_are_handwritten() -> None:
    """DISPATCH_LOG_MIN_ROWS / CEILING 必须是**手写的整数字面量**，且本自锁认全两种赋值形态。

    防两类假绿：① 派生式基线（``= len(rows)`` ⇒ 门永远绿）；
    ② 换一种写法躲自锁（只认 ``Assign`` 就会漏掉 ``AnnAssign``，反之亦然）。
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    baselines = {"DISPATCH_LOG_MIN_ROWS", "CEILING"}
    found: dict[str, str] = {}
    for node in tree.body:  # 仅看模块顶层赋值
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.expr):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id in baselines:
                value = node.value  # type: ignore[attr-defined]
                kind = type(node).__name__
                assert isinstance(value, ast.Constant) and isinstance(
                    value.value, int
                ), f"{target.id} 不是手写字面量（是 {ast.dump(value)}）——基线不许派生"
                found[target.id] = kind
    assert set(found) == baselines, f"基线自锁：只见到 {set(found)}，应含 {baselines}"


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
