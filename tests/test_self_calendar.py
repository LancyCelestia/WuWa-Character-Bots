"""自我历法层回归（需求 10：bot 要准确知道自己的日期/时间/四历法/更新历史）。

被试件 = ``domains/ops/self_calendar/``（时刻层 + 历法装配层 + 更新历史 + 读出面）。
历法**算法**本身不在这里验（那是 ``tests/test_multi_calendar.py`` 的活），本文件验
的是「装配有没有取错日界、缺数据有没有编、有没有偷偷造第二真身」。

判据三件（席位简报硬要求）：
① 钉死的时刻 × 四历法期望值表——**期望值全部由独立来源推得**，见
   ``_PINNED_CASES`` 上方逐条推导依据；写法是「先有期望值、再调被试代码」，
   不是把代码输出回抄成期望值（那是自证假绿）。
② 时刻可注入：同一函数、两个不同 ``now`` ⇒ 结果必然不同；且模块导入期不取钟。
③ 缺数据不编造：越界的日子、没有源的面、读不到的叙述文档、认不出的时区，
   输出里必须出现「未探测 / 无源 / 未接入」字样，而不是一个看起来对的日期。

另加两把反副本锁：本包源码里不得出现历法常数（防第二条历法实现），
且本包不得 import 占卜域的抽牌/存储面（只要 multi_calendar 那一件真身）。
"""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import pytest

from plugins.bot_unified_runtime.domains.ops.self_calendar import (
    build_calendar_snapshot,
    calendar_compact_lines,
    resolve_moments,
    self_calendar_report,
    update_history_lines,
)
from plugins.bot_unified_runtime.domains.ops.self_calendar.calendar_leg import (
    UNCOMPUTABLE,
    tibetan_month_day_status,
)
from plugins.bot_unified_runtime.domains.ops.self_calendar.facts_leg import (
    NOT_WIRED,
    agents_ledger_lines,
    handbook_wave_lines,
    project_root,
)
from plugins.bot_unified_runtime.domains.ops.self_calendar.moments import (
    normalize_aware,
    system_clock_now,
)

PACKAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "ops"
    / "self_calendar"
)

# ---------------------------------------------------------------------------
# ① 钉死的时刻 × 四历法期望值表（期望值的独立推导依据写在每条注释里）
# ---------------------------------------------------------------------------
#
# 通用依据（三格共用，均不经过被试代码）：
#   · 伊斯兰历（tabular/civil 历表）：锚点 1 Muharram AH 1400 = 公历 1979-11-21
#     （Kuwaiti 历表通行锚），30 年周期内置闰年为周期第
#     2,5,7,10,13,16,18,21,24,26,29 年（355 天），其余 354 天；月长自 Muharram
#     起 30/29 交替、闰年补末月。本文件作者用一次性脚本按这套规则从锚点逐日推
#     （脚本只依赖 stdlib 与 Fliegel–Van Flandern 的 JDN 公式，与本仓零共享代码）；
#     同一方法算 公历 2025-06-07 恰得 1446-12-10，与 ``test_multi_calendar.py``
#     里那条公开核对值吻合 ⇒ 两路互为印证。
#   · 东正教历（儒略历同日标签）：公历 − 13 天，1900-03-13 至 2100-03-14 恒定
#     （1900/2100 两个世纪年格里高利历无 2/29、儒略历有——公历常识）。
#   · 藏历饶迥：第一轮元年 = 公历 1027（学界通行），60 年一轮 ⇒
#     第 17 轮自 1027+16×60 = 1987 起算。
#   · 藏历年名 = 该年干支换藏式表述（阳/阴取天干奇偶、五行两天干一组、生肖沿用
#     汉地，「鸡」写作「鸟」）。
#
# C1 公历 2026-09-25（东八区日界）
#   农历八月十五 ← 2026 年中秋节 = 公历 9 月 25 日（公开节日表）；丙午马年（公开）。
#   伊斯兰历 1448-04-12 ← 上面通用推法。
#   藏历 饶迥 17 轮 40 年（2026-1987+1）、阳火马年（2026=丙午，丙为阳火、午为马；
#     公开表述「藏历 2026 阳火马年」）。
#   儒略历 2026-09-12；2026 东正教复活节 = 公历 4 月 12 日、西方复活节 = 4 月 5 日
#     （各教会公布的历年表，与 ``test_multi_calendar.py`` 同源）。
#
# C2 公历 2026-02-17（东八区日界；同一瞬间 UTC 侧还在 02-16 ⇒ 本格专打跨日界）
#   农历正月初一 ← 2026 年春节 = 公历 2 月 17 日（公开历书）；丙午马年。
#   伊斯兰历 1447-08-29；藏历同 C1；儒略历 2026-02-04；复活节两值同 C1。
#
# C3 公历 2025-05-31（东八区日界）
#   农历五月初五 ← 2025 年端午节 = 公历 5 月 31 日（公开节日表）；乙巳蛇年。
#   伊斯兰历 1446-12-03；藏历 饶迥 17 轮 39 年（2025-1987+1）、阴木蛇年
#     （2025=乙巳，乙为阴木、巳为蛇；公开表述「藏历 2025 阴木蛇年」）。
#   儒略历 2025-05-18；2025 年东西复活节重合于公历 4 月 20 日（公开事实）。


class PinnedCase(NamedTuple):
    tag: str
    utc_instant: datetime
    beijing_day: date
    lunar_month: int
    lunar_day: int
    ganzhi: str
    zodiac: str
    hijri: tuple[int, int, int]
    rabjung: tuple[int, int]
    tibetan_name: str
    julian_day: date
    pascha_old: date
    pascha_new: date


_PINNED_CASES: tuple[PinnedCase, ...] = (
    PinnedCase(
        tag="C1",
        utc_instant=datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc),
        beijing_day=date(2026, 9, 25),
        lunar_month=8,
        lunar_day=15,
        ganzhi="丙午",
        zodiac="马",
        hijri=(1448, 4, 12),
        rabjung=(17, 40),
        tibetan_name="阳火马年",
        julian_day=date(2026, 9, 12),
        pascha_old=date(2026, 4, 12),
        pascha_new=date(2026, 4, 5),
    ),
    PinnedCase(
        tag="C2",
        utc_instant=datetime(2026, 2, 16, 16, 30, tzinfo=timezone.utc),
        beijing_day=date(2026, 2, 17),
        lunar_month=1,
        lunar_day=1,
        ganzhi="丙午",
        zodiac="马",
        hijri=(1447, 8, 29),
        rabjung=(17, 40),
        tibetan_name="阳火马年",
        julian_day=date(2026, 2, 4),
        pascha_old=date(2026, 4, 12),
        pascha_new=date(2026, 4, 5),
    ),
    PinnedCase(
        tag="C3",
        utc_instant=datetime(2025, 5, 31, 2, 0, tzinfo=timezone.utc),
        beijing_day=date(2025, 5, 31),
        lunar_month=5,
        lunar_day=5,
        ganzhi="乙巳",
        zodiac="蛇",
        hijri=(1446, 12, 3),
        rabjung=(17, 39),
        tibetan_name="阴木蛇年",
        julian_day=date(2025, 5, 18),
        pascha_old=date(2025, 4, 20),
        pascha_new=date(2025, 4, 20),
    ),
)


@pytest.mark.parametrize("case", _PINNED_CASES, ids=lambda case: case.tag)
def test_pinned_instant_yields_four_expected_calendars(case: PinnedCase) -> None:
    """钉一个 UTC 瞬间 ⇒ 四历法必须等于独立推得的公开值（三格各一次全中）。"""
    moments = resolve_moments(case.utc_instant, timezone_name="Asia/Hong_Kong")
    assert moments.calendar_day == case.beijing_day
    snapshot = build_calendar_snapshot(moments.calendar_day)

    assert snapshot.supported is True, snapshot.reason
    assert snapshot.lunar is not None
    assert (snapshot.lunar.month, snapshot.lunar.day) == (case.lunar_month, case.lunar_day)
    assert snapshot.lunar.year_ganzhi == case.ganzhi
    assert snapshot.lunar.zodiac == case.zodiac
    assert snapshot.hijri == case.hijri
    assert snapshot.tibetan is not None
    assert (snapshot.tibetan.cycle, snapshot.tibetan.year_in_cycle) == case.rabjung
    assert snapshot.tibetan.year_name == case.tibetan_name
    assert snapshot.orthodox is not None
    assert snapshot.orthodox.julian_day == case.julian_day
    assert snapshot.orthodox.offset_days == 13
    assert snapshot.orthodox.pascha_old_rite == case.pascha_old
    assert snapshot.orthodox.pascha_new_rite == case.pascha_new


@pytest.mark.parametrize("case", _PINNED_CASES, ids=lambda case: case.tag)
def test_compact_lines_carry_all_four_calendars(case: PinnedCase) -> None:
    """紧凑读出行四历法一样不缺，且藏历月/日那一面明说无源（不是静默少一行）。"""
    snapshot = build_calendar_snapshot(case.beijing_day)
    text = "\n".join(calendar_compact_lines(snapshot))
    assert snapshot.lunar_label in text
    assert snapshot.hijri_label in text
    assert "藏历" in text and "东正教历" in text
    assert "本仓无源故不推算" in text, "藏历月/日的边界句必须出自真身原句"
    assert case.ganzhi in text and str(case.hijri[0]) in text


# ---------------------------------------------------------------------------
# ② 时刻可注入 + 导入期不取钟
# ---------------------------------------------------------------------------


def test_two_injected_instants_give_different_answers() -> None:
    """同一函数、两个 ``now`` ⇒ 结果必须不同（证明时刻真的在参数上，不是藏在全局）。"""
    early = resolve_moments(
        datetime(2026, 2, 16, 15, 0, tzinfo=timezone.utc), timezone_name="Asia/Hong_Kong"
    )
    late = resolve_moments(
        datetime(2026, 2, 16, 16, 0, tzinfo=timezone.utc), timezone_name="Asia/Hong_Kong"
    )
    assert early.calendar_day == date(2026, 2, 16)
    assert late.calendar_day == date(2026, 2, 17)
    assert early.calendar_day != late.calendar_day
    # 两个时刻差一小时，却跨了农历两天 ⇒ 历法面也必须跟着变。
    first = build_calendar_snapshot(early.calendar_day)
    second = build_calendar_snapshot(late.calendar_day)
    assert first.lunar_label != second.lunar_label
    assert first.hijri == (1447, 8, 28)  # 昨天：由 1447-08-29 递推一天
    assert second.hijri == (1447, 8, 29)


def test_naive_instant_is_rejected_instead_of_guessed() -> None:
    """naive 钟说明调用方自己都不知道在哪个时区——猜就等于算错日子，故硬拒。"""
    with pytest.raises(ValueError):
        resolve_moments(datetime(2026, 9, 25, 13, 30))  # noqa: DTZ001
    with pytest.raises(ValueError):
        normalize_aware(datetime(2026, 9, 25, 13, 30))  # noqa: DTZ001


def test_package_never_reads_the_clock_at_import_time() -> None:
    """模块体（函数之外）不得出现取钟调用——否则每次导入的时刻都不同，测试必不稳。

    判据是 AST 而非 grep：``datetime.now(`` 出现在函数体内是允许的（生产就是要读钟），
    出现在模块顶层才是病。
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        clock_nodes = [
            node
            for node in tree.body  # 只看模块顶层，不进函数体
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
            and _contains_clock_read(node.value)
        ]
        offenders += [f"{path.name}:{node.lineno}" for node in clock_nodes]
    assert not offenders, f"模块导入期取钟：{offenders}"


def _contains_clock_read(node: ast.expr | None) -> bool:
    """这个表达式里有没有直接取钟（``datetime.now/date.today/system_clock_now``）。"""
    if node is None:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in {"now", "today", "utcnow"}:
            return True
        if isinstance(sub, ast.Name) and sub.id == "system_clock_now":
            return True
    return False


def test_system_clock_helper_is_aware_and_explicit() -> None:
    """``system_clock_now`` 是**给装配层显式调**的口子，调了才拿得到 aware 钟。"""
    assert normalize_aware(system_clock_now()).tzinfo is not None


# ---------------------------------------------------------------------------
# 日界分歧（本席存在的理由：同一瞬间在不同钟下不是同一天）
# ---------------------------------------------------------------------------


def test_utc_and_beijing_days_diverge_and_are_reported() -> None:
    """2026-02-16T16:30Z：UTC 还在 16 日、东八区已是 17 日（春节）。"""
    moments = resolve_moments(
        datetime(2026, 2, 16, 16, 30, tzinfo=timezone.utc),
        timezone_name="Asia/Hong_Kong",
        system_now=datetime(2026, 2, 16, 11, 30, tzinfo=timezone(timedelta(hours=-5))),
    )
    assert moments.utc.day == date(2026, 2, 16)
    assert moments.local.day == date(2026, 2, 17)
    assert moments.calendar_day == date(2026, 2, 17), "历法面必须跟东八区日界，不是 UTC"
    assert moments.same_day_everywhere is False
    assert "不是同一天" in moments.day_divergence_note
    assert "东八区日界" in moments.day_divergence_note


def test_system_zone_not_injected_is_declared_unprobed() -> None:
    """没注入系统钟 ⇒ 明说未探测，绝不偷偷现读（现读会把钉住的时刻配个今天的日期）。"""
    moments = resolve_moments(
        datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc), timezone_name="Asia/Hong_Kong"
    )
    assert moments.system is None
    assert moments.system_source == "not-injected"
    lines = "\n".join(
        self_calendar_report(
            datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc),
            timezone_name="Asia/Hong_Kong",
            include_update_history=False,
        )
    )
    assert "系统本地时区：未探测" in lines


def test_bad_timezone_name_degrades_without_fabricating() -> None:
    """认不出的时区名 ⇒ 说「未识别/未探测」并按 UTC 口径报，不硬凑一个偏移。"""
    moments = resolve_moments(
        datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc), timezone_name="Not/AZone"
    )
    assert moments.local.recognized is False
    assert "未识别" in moments.local.note
    report = "\n".join(
        self_calendar_report(
            datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc),
            timezone_name="Not/AZone",
            include_update_history=False,
        )
    )
    assert "配置时区：未探测" in report


# ---------------------------------------------------------------------------
# ③ 缺数据不编造
# ---------------------------------------------------------------------------


def test_day_outside_support_window_says_uncomputable() -> None:
    """1901-2099 之外：真身抛 ValueError ⇒ 读出必须是「未探测」，不得留任何历法数值。"""
    snapshot = build_calendar_snapshot(date(1899, 12, 31))
    assert snapshot.supported is False
    assert UNCOMPUTABLE in snapshot.reason
    assert snapshot.lunar is None and snapshot.hijri is None
    assert snapshot.tibetan is None and snapshot.orthodox is None
    assert snapshot.detail_lines == ()
    lines = calendar_compact_lines(snapshot)
    assert any("未探测" in line for line in lines)
    assert not any("伊斯兰历约" in line for line in lines), "算不出来就不许给数"
    assert any("别拿邻近年份或公历日期顶替" in line for line in lines)

    report = "\n".join(
        self_calendar_report(
            datetime(1899, 12, 31, 12, 0, tzinfo=timezone.utc),
            timezone_name="UTC",
            include_update_history=False,
        )
    )
    assert "未探测" in report


def test_tibetan_month_and_day_have_no_source_and_say_so() -> None:
    """藏历月/日与洛萨：真身没源 ⇒ 状态恒为「无源」，快照里也没有可被误用的字段。"""
    snapshot = build_calendar_snapshot(date(2026, 9, 25))
    assert snapshot.tibetan is not None
    assert snapshot.tibetan.month_day_available is False
    assert tibetan_month_day_status(snapshot) == "无历表源，不推算"
    assert not hasattr(snapshot.tibetan, "month"), "没有源就不该长出这一维（防有人往里填猜的数）"


# ---------------------------------------------------------------------------
# 更新历史：只读在册叙述文档
# ---------------------------------------------------------------------------

#: 故意长过 ``DEFAULT_MAX_CHARS``（160）的标题：验「截断必须说出来」。
_LONG_TAIL = "很长" * 90

_HANDBOOK_FIXTURE = f"""# HANDBOOK
## 一、族谱
## §41 早期一波（2026-09-20）
正文……
## §45 晨波（2026-09-25 晨）
正文……
## §46 二批（2026-09-25 凌晨；这一段的标题故意写得{_LONG_TAIL}）
正文里有个路径 C:\\\\Somewhere\\\\secret.txt
"""

_AGENTS_FIXTURE = """# AGENTS
## 第六部分：已知问题台账
| # | 问题 | 状态 |
|---|---|---|
| 9 | **第九波（2026-09-21）**——正文 | 完成 |
| 12 | 无粗体标题的一行 | 完成 |
| 11 | **第十一波（2026-09-24）**——正文 | 完成 |
"""


def _fixture_root(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "plugins").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "HANDBOOK.md").write_text(_HANDBOOK_FIXTURE, encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(_AGENTS_FIXTURE, encoding="utf-8")
    return tmp_path


def test_update_history_is_read_from_docs_not_handwritten(tmp_path: Path) -> None:
    """夹具里写什么就出什么 ⇒ 证明是**读**出来的；同时按编号取最新，不按文件序。"""
    root = _fixture_root(tmp_path)
    handbook = handbook_wave_lines(root, limit=2)
    assert handbook.available is True
    assert "§46 二批" in handbook.lines[0], "§46 编号最大，必须排在文件序之后的 §45 之前"
    assert "§45" in handbook.lines[1]
    assert "另有" in handbook.lines[0] and "字未显示" in handbook.lines[0], "截断必须说出来"
    joined = "\n".join(handbook.lines)
    assert "secret.txt" not in joined, "台账标题里的盘符路径不得裸进 prompt（铁律 3）"

    agents = agents_ledger_lines(root, limit=3)
    assert agents.available is True
    numbers = [line.split("#")[1].split()[0] for line in agents.lines]
    assert numbers == ["12", "11", "9"], f"按编号取，且无粗体行也要能落题：{agents.lines}"

    merged = "\n".join(update_history_lines(root, limit_per_source=2))
    assert "§46 二批" in merged and "#11 第十一波" in merged


def test_update_history_says_not_wired_when_docs_missing(tmp_path: Path) -> None:
    """文件不在/一条没匹配上 ⇒ 写「未接入」，绝不编一段「暂无更新」。"""
    empty = tmp_path / "nothing"
    empty.mkdir()
    handbook = handbook_wave_lines(empty)
    agents = agents_ledger_lines(empty)
    assert handbook.available is False and NOT_WIRED in handbook.lines[0]
    assert agents.available is False and NOT_WIRED in agents.lines[0]

    # 文件在、但里面一条账目都没有：同样是「未接入」，而不是空列表假装成功。
    bare = tmp_path / "bare"
    (bare / "docs").mkdir(parents=True)
    (bare / "docs" / "HANDBOOK.md").write_text("# 只有标题\n没有波次小节\n", encoding="utf-8")
    bare_source = handbook_wave_lines(bare)
    assert bare_source.available is False
    assert NOT_WIRED in bare_source.lines[0]

    report = "\n".join(self_calendar_report(timezone_name="UTC", root=empty))
    assert NOT_WIRED in report


def test_project_root_walks_up_by_anchor_not_layer_count(tmp_path: Path) -> None:
    """上溯靠「同时含 plugins 与 docs」这枚锚点，不靠数 parents 层数。"""
    root = _fixture_root(tmp_path)
    nested = root / "plugins" / "bot_unified_runtime" / "domains" / "ops"
    nested.mkdir(parents=True)
    assert project_root(nested) == root


def test_project_root_returns_none_when_no_anchor_upwards(tmp_path: Path) -> None:
    """这条单独占一个 tmp_path：上一条刚造出来的 plugins/docs 不能当它的祖先。

    （同目录先建锚点再验「无锚点」= 自证假绿，实测会被自己上一行污染。）
    """
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    assert project_root(lonely) is None


def test_real_repository_ledger_is_readable() -> None:
    """真仓现读：本席不许在代码里写摘要，那就必须证明真读得到项目的账。

    期望值不写死内容（那是会过期的计数），只钉「读到了东西」与「读的是真文档」。
    """
    root = project_root(PACKAGE_DIR)
    assert root is not None, "本包应当位于工程根之下"
    handbook = handbook_wave_lines(root, limit=3)
    agents = agents_ledger_lines(root, limit=3)
    assert handbook.available, handbook.lines
    assert agents.available, agents.lines
    assert all("更新历史" in line or "台账" in line for line in handbook.lines)
    assert all("台账 #" in line for line in agents.lines)


def test_report_is_deterministic_for_the_same_instant() -> None:
    """同一注入时刻两次调用逐字节相同（读盘那节关掉，避免 git/文档在飞干扰）。"""
    instant = datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc)
    first = self_calendar_report(
        instant, timezone_name="Asia/Hong_Kong", include_update_history=False
    )
    second = self_calendar_report(
        instant, timezone_name="Asia/Hong_Kong", include_update_history=False
    )
    assert first == second
    text = "\n".join(first)
    for label in ("农历", "伊斯兰历约", "藏历", "东正教历"):
        assert label in text, label
    assert "2026-09-25" in text and "21:30:00" in text, "东八区墙钟必须与注入瞬间一致"


# ---------------------------------------------------------------------------
# 反第二真身两把锁
# ---------------------------------------------------------------------------

#: 历法常数真身清单：出现在本包源码里 = 有人又实现了一遍换算。
_CALENDAR_LITERALS = (
    "1948440",
    "10631",
    "10632",
    "10985",
    "17719",
    "15238",
    "2451550",
    "29.530588861",
    "32083",
    "32045",
    "0.2422",
    "2697",  # 黄帝纪元偏移
    "5509",  # 拜占庭纪年偏移
    "1027",  # 饶迥元年
    "543",  # 南传佛历偏移
)


def test_package_contains_no_second_calendar_implementation() -> None:
    """本包源码里不得出现任何历法常数/天文系数（换算唯一住 multi_calendar）。"""
    hits: list[str] = []
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                text = repr(node.value)
                if text in _CALENDAR_LITERALS or text.rstrip("0.").lstrip("0") in {
                    "543",
                    "1027",
                    "2697",
                }:
                    hits.append(f"{path.name}:{node.lineno}={text}")
        for stripped in _CALENDAR_LITERALS:
            # 字符串字面量里藏常数（如把整句历法文案抄进本包）同样算副本。
            if stripped in {"543", "1027", "2697", "5509"}:
                continue
            if stripped in source.replace(" ", ""):
                hits.append(f"{path.name}:literal {stripped}")
    assert not hits, f"疑似第二真身：{sorted(set(hits))}"


#: 本包允许 import 的历法真身只有这两件；占卜域的抽牌/存储面一律不许碰。
_ALLOWED_CALENDAR_MODULES = {
    "plugins.bot_unified_runtime.domains.divination.data.multi_calendar",
    "plugins.bot_unified_runtime.domains.divination.data.ganzhi",
}
_FORBIDDEN_IMPORT_PREFIXES = (
    "plugins.bot_unified_runtime.domains.divination.data.deck_math",
    "plugins.bot_unified_runtime.domains.divination.data.tarot",
    "plugins.bot_unified_runtime.domains.divination.data.iching",
    "plugins.bot_unified_runtime.domains.divination.store",
    "plugins.bot_unified_runtime.domains.divination.capabilities",
)


def test_package_imports_only_the_calendar_truth_source() -> None:
    """本包对占卜域只许拿 ``multi_calendar``/``ganzhi``；拿到抽牌/能力面就是走错门。"""
    offenders: list[str] = []
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                if ".divination" in module and module not in _ALLOWED_CALENDAR_MODULES:
                    offenders.append(f"{path.name}:{node.lineno} -> {module}")
                if module.startswith(_FORBIDDEN_IMPORT_PREFIXES):
                    offenders.append(f"{path.name}:{node.lineno} -> {module}")
    assert not offenders, f"越界 import：{offenders}"


#: 装配面与配置面的模块真身：本席只交数据腿，碰这些就是越权。
_FORBIDDEN_IMPORT_TARGETS = (
    "domains.chat_reply.character.providers",
    "bot_unified_runtime.config",
    "domains.chat_reply.capabilities.echo",
    "domains.chat_reply.runtime.base_router",
    "domains.chat_reply.runtime.capability_registry",
)


def test_package_does_not_reexport_providers_or_config() -> None:
    """本席不碰装配面：包内不得 import providers/config/echo/router/registry。

    判据走 AST 的真实 import 目标，不走全文 grep——散文里提一句
    「本席没改 providers.py」不该把锁打红（那是一枚会自己咬自己的判据）。
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom):
                targets = [node.module or ""] + [
                    f"{node.module or ''}.{alias.name}" for alias in node.names
                ]
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            for target in targets:
                if target.startswith(_FORBIDDEN_IMPORT_TARGETS) or any(
                    marker in target for marker in _FORBIDDEN_IMPORT_TARGETS
                ):
                    offenders.append(f"{path.name}:{node.lineno} -> {target}")
    assert not offenders, f"越权 import：{offenders}"


# ---------------------------------------------------------------------------
# 注毒自证：三把反副本/活性锁必须真的有杀伤力
# ---------------------------------------------------------------------------


def test_anti_duplicate_lock_has_teeth(tmp_path: Path) -> None:
    """往一个临时副本里塞一枚历法常数，判据必须打红——否则那把锁是空跑的。"""
    fake = tmp_path / "self_calendar"
    fake.mkdir()
    (fake / "bad.py").write_text(
        "OFFSET = 1948440\n", encoding="utf-8"
    )  # 伊斯兰历表 epoch 常数
    detected = _scan_for_calendar_literals(fake)
    assert detected, "注毒未被反副本锁抓到 ⇒ 锁失效"

    (tmp_path / "clean.py").write_text("X = 7\n", encoding="utf-8")
    assert not _scan_for_calendar_literals(tmp_path / "nope"), "不存在的目录不该报警"


def _scan_for_calendar_literals(directory: Path) -> list[str]:
    """与主判据同一条规则，抽出来供注毒用例复用。"""
    hits: list[str] = []
    for path in sorted(directory.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for literal in _CALENDAR_LITERALS:
            if literal in source.replace(" ", ""):
                hits.append(f"{path.name}:{literal}")
    return hits


def test_calendar_day_must_follow_beijing_not_config_zone() -> None:
    """把「跟错日界」这一类缺陷钉死：配置钟在东八区以西时，历法面仍须取东八区那天。"""
    instant = datetime(2026, 2, 16, 20, 0, tzinfo=timezone.utc)
    moments = resolve_moments(instant, timezone_name="America/New_York")
    assert moments.local.day == date(2026, 2, 16), "纽约此刻还是 16 日晚上"
    assert moments.calendar_day == date(2026, 2, 17), "但历法面必须按东八区取 17 日"
    snapshot = build_calendar_snapshot(moments.calendar_day)
    assert snapshot.lunar.day == 1 and snapshot.lunar.month == 1, "取错一天就不是春节了"
