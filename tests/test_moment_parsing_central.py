r"""ISO 时刻解析中央件（S232）行为锁：`domains/core/moment_parsing.py` 唯一真身。

照 `tests/test_session_keys_central.py`（FIX5）与 `tests/test_text_boundary_central.py`
（T59）的形态做：**权威定义 + 例锁 + 可红性**。

本件存在的理由（详模块 docstring 与
`.superpowers/sdd/2026-09-24-central-dispatch/SEAT-S232.md` §0）：闸侧 G5 锁
`tests/test_outbound_gate.py::test_gate_reuses_quiet_hours_single_source` 一直禁闸
「自造时间解析」，但全仓**没有**一座 ISO 时刻解析真身可走（`plugins/` 下散落直调数十处、
其中一小半各写一遍 `replace("Z", "+00:00")` 兼容；**逐条清单与可复跑命令住该报告 §3**，
本文件不手写计数——AGENTS 规则 10）。⇒ 本件是那把锁**第一次**有一个可指向的家。

钉死的口径（逐条有例，缺一条即本文件未覆盖）：

1. `Z` / `z` 后缀 ⇒ UTC（本件自己做 `+00:00` 归一，不赌 Python 版本；
   `test_stdlib_cannot_absorb_the_zulu_forms_alone` 就是这条的可红性）。
2. 带偏移（`+08:00` / `-05:30`）⇒ 折算 UTC，返回值 `tzinfo` 恒为 `timezone.utc`。
3. 裸时刻 ⇒ **按 UTC 解释**（与闸 `_utc()` 逐字节同形；绝不按机器本地钟猜）。
4. 仅日期字面量 ⇒ 当日零点 UTC；**再挂 `Z`/`z` 同样当日零点、不抛**
   （S232 续跑席实测推翻旧文档的「抛」，见 `test_date_only_with_zulu_is_midnight_utc`）；
   `date` 对象 ⇒ 抛（不替它编一天中的哪一刻）。
5. 空值 / 空白 / `None` / 垃圾 / 非字符串类型 ⇒ **抛 `MomentParseError`**，
   **绝不返回 None**——「没配」是调用方的判断，不是解析器的（闸侧
   `TTL_STATE_INVALID` 的 fail-closed 全靠这条异常才成立）。
6. 幂等：解析结果再序列化回去、重解一次，值不变。
7. **已登记残余**（钉现状、不许无声改）：仅日期带偏移按 CPython 读法收下、纳秒折到微秒
   —— 见 `test_registered_residual_*` 两件，判据变更须先过 SEAT-S232.md §4 的待裁项。

全部离线：零 I/O、零网络、零 config、零时钟（不读 now，故永不 flaky）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from plugins.bot_unified_runtime.domains.core.moment_parsing import (
    MOMENT_FIELD_DEFAULT,
    ZULU_SUFFIXES,
    MomentParseError,
    parse_moment,
)

UTC = timezone.utc

# ------------------------------------------------------------------ 形态常量钉死


def test_public_shape_pinned() -> None:
    """三枚公开形态逐字钉死（换名/换形要让消费方与锁一起红，不许悄悄搬家）。"""
    assert MOMENT_FIELD_DEFAULT == "时刻字面量"
    assert ZULU_SUFFIXES == ("Z", "z")
    assert issubclass(MomentParseError, ValueError)


# ------------------------------------------------------- 判据 1/2：Z 与偏移 → UTC
# (字面量, 期望 UTC 时刻) —— 期望值全部手算，不吃被测件的回算
_TEXT_TO_UTC: list[tuple[str, datetime]] = [
    # 1) `Z` 大小写两式（配置面与日志面都真实出现过）
    ("2026-09-25T03:00:00Z", datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)),
    ("2026-09-25T03:00:00z", datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)),
    # 2) 裸时刻 ⇒ 按 UTC（第 3 条口径）
    ("2026-09-25T03:00:00", datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)),
    ("2026-09-25T03:00", datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)),
    ("2026-09-25 03:00:00", datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)),  # 空格分隔
    # 3) 仅日期 ⇒ 当日零点 UTC（第 4 条口径前半）
    ("2026-09-25", datetime(2026, 9, 25, 0, 0, 0, tzinfo=UTC)),
    # 4) 正负偏移 ⇒ 折算 UTC（偏移是输入形态，不是结果形态）
    ("2026-09-25T11:00:00+08:00", datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)),
    ("2026-09-25T00:30:00+05:30", datetime(2026, 9, 24, 19, 0, 0, tzinfo=UTC)),
    ("2026-09-24T22:00:00-05:00", datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)),
    ("2026-09-25T03:00:00+00:00", datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)),
    # 5) 亚秒精度不得被抹掉
    ("2026-09-25T03:00:00.123456Z", datetime(2026, 9, 25, 3, 0, 0, 123456, tzinfo=UTC)),
    # 6) 两端空白先剥（配置面手填常有尾空格）
    ("  2026-09-25T03:00:00Z  ", datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)),
]


@pytest.mark.parametrize(("text", "expected"), _TEXT_TO_UTC)
def test_text_literals_parse_to_aware_utc(text: str, expected: datetime) -> None:
    """字符串字面量 → aware UTC：值、tzinfo 形态、微秒三项都对得上。"""
    got = parse_moment(text)
    assert got == expected
    assert got.tzinfo is UTC, "返回值必须是 aware UTC（不保留原偏移、不返回 naive）"
    assert got.utcoffset() == timedelta(0)


def test_result_timezone_is_normalized_regardless_of_input_offset() -> None:
    """不同偏移解出的同一时刻，结果 `tzinfo` 必须是**同一个** UTC（比较不再漂移）。"""
    a = parse_moment("2026-09-25T11:00:00+08:00")
    b = parse_moment("2026-09-25T03:00:00Z")
    assert a == b and a.utcoffset() == b.utcoffset() == timedelta(0)
    assert a.isoformat() == b.isoformat() == "2026-09-25T03:00:00+00:00"


# ---------------------------------------------------- 判据 3：datetime 对象进得来
def test_naive_datetime_is_treated_as_utc() -> None:
    """naive `datetime` ⇒ 按 UTC 补（与闸 `_utc()` 同形；绝不按本地钟解释）。"""
    got = parse_moment(datetime(2026, 9, 25, 3, 0, 0))  # noqa: DTZ001 - 故意造 naive，验本件补 UTC
    assert got == datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)
    assert got.tzinfo is UTC


def test_aware_datetime_is_converted_not_relabelled() -> None:
    """aware `datetime` ⇒ 折算 UTC，**不是**把 tzinfo 抹掉换标签（会漂 8 小时那种）。"""
    source = datetime(2026, 9, 25, 11, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    got = parse_moment(source)
    assert got == datetime(2026, 9, 25, 3, 0, 0, tzinfo=UTC)
    assert got is not source  # 不改调用方手里的那个对象


# ------------------------------------------------------------ 判据 4：date 不补时刻
def test_date_object_is_rejected_not_invented() -> None:
    """`date`（非 datetime）⇒ 抛：替它编一个「零点」属于本件造事实。"""
    with pytest.raises(MomentParseError) as exc:
        parse_moment(date(2026, 9, 25), field="outbound_gate.enabled_until")
    assert "outbound_gate.enabled_until" in str(exc.value), "报错必须点名是哪枚字段"
    assert "日期而非时刻" in str(exc.value)


def test_date_only_with_zulu_is_midnight_utc() -> None:
    """仅日期再挂 `Z` ⇒ **当日零点 UTC，不抛**（本席 2026-09-24T18:38Z 实测钉死）。

    这条用例是**用来推翻文档的**：上一版模块 docstring 写「`2026-09-25Z` 抛（实测两遍
    都解不动）」，本席现算发现标准库第一遍确实解不动（`ValueError`），但本件的
    `Z` 归一支接着把它折成 `2026-09-25+00:00` 并解成当日零点 ⇒ **行为是接受**。
    处置＝留行为、改文档、补这条锁：它与判据 4 前半（裸日期按零点）同口径、满足幂等，
    且「配置面写了个能被归一读懂的 ISO 值却被拒」会比它要替代的散落实现更难预测。
    """
    got = parse_moment("2026-09-25Z")
    assert got == datetime(2026, 9, 25, 0, 0, 0, tzinfo=UTC)
    assert got.tzinfo is UTC
    # 小写 `z` 同形（本件自做的归一不赌大小写，也不赌标准库版本）
    assert parse_moment("2026-09-25z") == got
    # 幂等：这条形态也要过第 7 条口径
    assert parse_moment(got.isoformat()) == got


def test_stdlib_cannot_absorb_the_zulu_forms_alone() -> None:
    """真身存在的理由之一：标准库**不认**小写 `z`，也不认「仅日期 + `Z`/`z`」。

    本件若把这两形退回标准库（删掉归一支），这条当场红——它就是判据 2 的可红性。
    """
    for text in ("2026-09-25T03:00:00z", "2026-09-25Z", "2026-09-25z"):
        with pytest.raises(ValueError):
            datetime.fromisoformat(text)  # 标准库侧：解不动
        assert parse_moment(text).tzinfo is UTC  # 本件侧：一处做完


# ------------------------------------------- 已登记残余：钉现状（要改必须先过 §4 裁定）
def test_registered_residual_offset_on_bare_date_keeps_stdlib_reading() -> None:
    r"""**仅日期带偏移**（`2026-09-25+08:00`）今天按 CPython 的读法落 `08:00 UTC`。

    本席实测（3.12.10，2026-09-24T18:41Z）：`datetime.fromisoformat("2026-09-25+08:00")`
    ＝ naive `2026-09-25T08:00:00`——它把 `+08:00` 当成了**时刻**而不是偏移。本件第一遍
    就成功，于是照 CPython 的读法收下、按判据 4 补成 UTC ⇒ 结果 `08:00Z`，而不是
    语义上更合理的「当地零点＝前一日 `16:00Z`」。

    这条用例**不是认可该读法**，是把现状钉住、让它无法被无声改掉：
    要不要为这一形加拒绝腿（「仅日期不得带偏移，抛」）属**判据变更**，
    已登记 `SEAT-S232.md` §4 待裁（本席按简报「薄真身、只碰闸一处」不擅自扩权）。
    真要改，先让这条红、再连同 docstring 第 5 条一起改。
    """
    got = parse_moment("2026-09-25+08:00")
    assert got == datetime(2026, 9, 25, 8, 0, 0, tzinfo=UTC)
    # 同一形的基本写法（`20260925`）今天也被接受（ISO 基本型），一并钉住。
    assert parse_moment("20260925") == datetime(2026, 9, 25, 0, 0, 0, tzinfo=UTC)
    assert parse_moment("20260925Z") == datetime(2026, 9, 25, 0, 0, 0, tzinfo=UTC)


def test_registered_residual_sub_second_precision_is_truncated_not_rejected() -> None:
    """纳秒级小数被折到微秒（CPython 口径），不抛也不进位——一并钉现状。"""
    assert parse_moment("2026-09-25T03:00:00.123456789Z").microsecond == 123456



# ------------------------------------------------- 判据 5：缺失与垃圾一律响亮（核心教义）
_BAD_VALUES: list[object] = [
    None,  # 缺失
    "",  # 空串
    "   ",  # 只有空白
    "2026-13-45",  # 月日越界：既非「没配」也非「已过期」
    "2026-09-25T99:00:00Z",  # 时刻越界
    "tomorrow",  # 自然语言不属本件
    "1 hour",  # 相对时长不属本件
    "Wed Oct 10 20:19:24 +0000 2018",  # 英文日期归 media.py 的宽松强制口
    "1758812400",  # epoch 数字不属本件（那是另一件事，勿混）
    12345,  # int
    1758812400.0,  # float
    True,  # bool
    [],  # list
    {},  # dict
    "2026-09-25T03:00:00+00:00Z",  # 偏移与 Z 双写：形态冲突，不猜
]


@pytest.mark.parametrize("bad", _BAD_VALUES)
def test_unparseable_raises_and_never_returns_none(bad: object) -> None:
    """**绝不静默返回 None**：一旦静默，一枚写错的 TTL 会被当成「没写 TTL」＝永久开关。"""
    with pytest.raises(MomentParseError):
        parse_moment(bad)


def test_error_is_distinguishable_and_carries_nothing_but_the_literal() -> None:
    """异常可辨识（`MomentParseError`，同时是 `ValueError` 以接住既有兜底面）。"""
    with pytest.raises(MomentParseError) as exc:
        parse_moment("2026-13-45", field="outbound_gate.enabled_until")
    assert isinstance(exc.value, ValueError), "必须能被 except (TypeError, ValueError) 接住"
    assert type(exc.value) is MomentParseError, "必须可与别的 ValueError 分开记账"
    assert "2026-13-45" in str(exc.value), "报错要能让人看出是哪枚值坏了"


def test_existing_catch_sites_keep_working_without_edits() -> None:
    """闸的兜底面写的是 `except (TypeError, ValueError)`——真身必须原样被它接住。"""
    try:
        parse_moment("not-a-moment")
    except (TypeError, ValueError):
        return  # 既有兜底面无需改动即可覆盖
    pytest.fail("抛的不是 TypeError/ValueError 家族 ⇒ 闸侧 fail-closed 分支会漏接")


def test_overlong_garbage_is_truncated_in_message() -> None:
    """超长垃圾值不得把整串回显进报错（防日志行被一枚坏配置撑爆）。"""
    with pytest.raises(MomentParseError) as exc:
        parse_moment("x" * 5000)
    assert len(str(exc.value)) < 200, f"报错文案失控：{len(str(exc.value))} 字"


# ------------------------------------------------------------------ 判据 6：幂等
def test_parse_is_idempotent_through_serialization() -> None:
    """解析 → 序列化 → 再解析，值逐字节不动（闸侧往返比较依赖这条）。"""
    for text, _expected in _TEXT_TO_UTC:
        once = parse_moment(text)
        twice = parse_moment(once.isoformat())
        assert twice == once, f"{text!r} 往返不稳定"
        assert twice.isoformat() == once.isoformat()


# ------------------------------------------------------- 消费方契约：TTL 到期判据可用
def test_parsed_moment_supports_the_gate_comparator() -> None:
    """闸用 `_utc(now) >= until` 判到期 ⇒ 结果必须可直接与 aware UTC 比较（不抛 TypeError）。"""
    until = parse_moment("2026-09-25T03:00:00Z")
    assert datetime(2026, 9, 25, 2, 59, tzinfo=UTC) < until
    assert datetime(2026, 9, 25, 3, 0, tzinfo=UTC) >= until
    assert datetime(2026, 9, 25, 3, 1, tzinfo=UTC) >= until


def test_gate_ttl_delegates_to_the_source_behaviourally() -> None:
    """**行为锁**（不只 AST 形状）：闸的 `parse_gate_ttl` 必须与真身逐字同结果。

    闸侧那条 G5 锁只查「import 了真身 + 真的调用 + 件内无 `fromisoformat` 字样」，
    那是**结构**判据；本条补**语义**判据——三形各钉一手：

    - 未配（`None` / 空白）⇒ 闸折成「无 TTL」`None`（这条判断**属于闸**，真身对同值抛）；
    - 带小写 `z` ⇒ 与 `parse_moment` 同值（证明真走了归一支，而不是各自运气）；
    - 垃圾值 ⇒ 抛，且抛的是真身那个可辨识类型（`effective_gate_enabled` 的
      `TTL_STATE_INVALID` 才有得折）。

    放在本文件而不是 `tests/test_outbound_gate.py`：后者的写面在本席只放开「那条锁的判据形」。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        parse_gate_ttl,
    )

    # ① 未配＝闸自己的判断，两处都得是 None（真身自己不折，见判据 5）
    assert parse_gate_ttl(None) is None
    assert parse_gate_ttl("") is None
    assert parse_gate_ttl("   ") is None
    with pytest.raises(MomentParseError):
        parse_moment(None)  # 反向钉：这条折叠没漏进真身

    # ② 配了就得与真身逐字节同值（含小写 z 这种标准库不认的形）
    for text in ("2026-09-25T03:00:00z", "2026-09-25T11:00:00+08:00", "2026-09-25"):
        assert parse_gate_ttl(text) == parse_moment(text), f"{text!r} 闸与真身解得不一样"
        assert parse_gate_ttl(text).tzinfo is UTC

    # ③ 垃圾必须响亮，且类型可辨识
    with pytest.raises(MomentParseError):
        parse_gate_ttl("2026-13-45")


# ------------------------------------------------------------- 第二真身防回潮（结构锁）

#: `domains/core/` 里**已登记、尚未迁**的 ISO 时刻直调点（相对 core 的路径）。
#: 这条锁只准**变短**：任何新写的 core 内直调都会当场红；要留新条目必须同时
#: 在 `SEAT-S232.md` §3 说清「它为什么不需要解不出就响亮」。
_REGISTERED_CORE_UNMIGRATED: frozenset[str] = frozenset(
    {
        # 契约层宽松强制口：解不出＝该字段为空，语义与本件相反 ⇒ **有意不迁**
        # （迁了会把可选字段变成抛异常，见模块 docstring「与既有邻居的分工」表）。
        "contracts/media.py",
        # 真·重复，待迁：cookie 到期时刻（`expires_at`）——它恰恰需要
        # 「读不懂就响亮」，登记为 §3 队列 C-1。
        "credentials/credential_health.py",
        # 真·重复，待迁：决策 trace 的 `created_at` 读侧，登记为 §3 队列 C-2。
        "decision/trace.py",
    }
)


def test_no_second_iso_parser_in_core() -> None:
    """`domains/core/` **整棵子树**只准这一座 ISO 时刻真身，其余点位必须逐枚在册。

    口径解释（免被误读成「全仓已执法」）：本件模块 docstring 自称「全仓唯一权威」是
    **判据口径**上的权威；机器执法面只到 `domains/core/` 这一棵子树，`plugins/` 其余
    数十处存量直调本波一律不动（简报「薄真身、只碰闸一处」)，逐条清单住
    `SEAT-S232.md` §3。把锁放到全仓会当场红数十条 ⇒ 那是拿假绿换好看。
    """
    import ast
    from pathlib import Path

    core_root = (
        Path(__file__).resolve().parent.parent
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "core"
    )
    offenders: set[str] = set()
    for path in sorted(core_root.rglob("*.py")):  # 下钻子包：core 内部不许有第二间房
        if "__pycache__" in path.parts:
            continue
        if path.name == "moment_parsing.py":
            continue  # 真身本件
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "fromisoformat":
                offenders.add(path.relative_to(core_root).as_posix())
    unregistered = offenders - _REGISTERED_CORE_UNMIGRATED
    assert unregistered == set(), (
        f"domains/core/ 内新冒出未在册的 ISO 时刻直调：{sorted(unregistered)}"
        "——正解是 import 本件 parse_moment，不是再写一遍"
    )


def test_registered_core_debt_is_not_growing() -> None:
    """在册那三枚只能被迁走、不能被供养成新的「例外」。

    与上一条合起来才是完整的一条腿：`test_no_second_iso_parser_in_core` 拦新增，
    本条**点名存量**（一旦有人把某枚迁掉了却顺手把名字留在这里，本条红 ⇒ 逼他删名）。
    """
    import ast
    from pathlib import Path

    core_root = (
        Path(__file__).resolve().parent.parent
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "core"
    )
    present: set[str] = set()
    for rel in _REGISTERED_CORE_UNMIGRATED:
        path = core_root / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Attribute) and node.attr == "fromisoformat"
            for node in ast.walk(tree)
        ):
            present.add(rel)
    stale = _REGISTERED_CORE_UNMIGRATED - present
    assert stale == set(), f"这几枚已经不走直调了，请从在册集合删掉：{sorted(stale)}"
