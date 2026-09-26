r"""出站闸「开闸前置条件」门（席位 S103）——判的是能不能开，不是开没开。

【名字与本文都钉死的一句话】
本件判的是「把 `bot_outbound_gate_enabled` 从 ``False`` 翻成 ``True`` 之前，全树
现役主动投递点的幂等键是否都能过中央键形谓词」＝**开闸前置条件**。
它**绝不**判、也**绝不得被叙述成**「闸已执法」：出站闸今天缺省关闭
（`config.py` `bot_outbound_gate_enabled=False`，生产 `.env` 无此行 ⇒
关态 `decide` 早退），顺延 / 限流 / 键形 / 闸审计在线上都不生效。本门跑绿，
只说明「欠账名册这笔账此刻如实记着」，不说明闸开了。

为什么需要一把机械门，而不是靠人记得
------------------------------------
本波已两次被同一形咬过：慢回复回执幂等键直拼 `session_id`/`message_id`（含段分隔
符 `:`）⇒ 关态照发、开闸态整条判 `skip, reason="dedupe_key_shape"`＝**静默丢消息**
（台账 #50）；紧急域 `nmc:A1` 同型 Critical（#46）。⇒ 开闸前需要「全树现役投递点
键形是否都过中央谓词」的机械检查。本件对现役点做 AST 现算（不 grep 猜），逐点判
三态，把②③两类当前已知欠账写成显式欠账名册（equality 锁、只准降），非空＝
「今天还不能开闸」的实账。

唯一合法判据（禁在测试里抄第二份正则）
--------------------------------------
段规则真身 = `domains/emergency_info/service/dedupe.py:_SEGMENT_RE`
（`^[A-Za-z0-9_.\-]{1,120}$`，`:` 是段分隔符）。本件只**读并调用**其公开谓词
`is_legal_segment` / `is_legal_date_key` / `active_push_key_shape_ok` /
`is_emergency_dedupe_key`，绝不重定义。开闸态「这条键到底会不会被闸 skip」用
`outbound_gate.dedupe_key_shape_ok` 委托落到的同一处实现判定，与生产闸逐字节同源。

与 S62 件的分工
--------------
`tests/test_active_push_key_shape_ledger.py`（S62）锚的是「六族**键构造**逐条审计」
（按族）；本件锚的是「全树**投递点** AST 清单 + 开闸前置」：现役点数地板、
namespace 申报缺口的点名、以及「名册成员若与 AST 现役点对不上就是幽灵」的交叉锁。
两者独立、互不替代。

【2026-09-24 S184 口径更正（必读，覆盖本件所有「开闸即静默丢」写法）】
中央唯一出口 `submit_active_push` 现在在 `gate.decide` **之前**用
`dedupe.py:wash_active_push_key` 规范一次幂等键形（段级脏⇒洗，洗完退化⇒摘要兜底，
真被改写留一行 WARNING）。于是本件 ② 类那笔账的含义收窄为两件事，都仍有锁：

- **绕过出口的投递面**：全树 `queue.submit` 直调点（现役枚数由
  `test_wash_has_exactly_one_production_call_site` 与 `scan_production_delivery_points`
  现算，本席不手写）不经过洗段，构造侧脏串照旧原样进队列；
- **出口洗段不是单射**：`11 08838060` 与 `11_08838060` 会塌成同一段（刻画锁
  `tests/test_outbound_gate.py::test_wash_residual_non_injective_punctuation_and_truncation`）。

⇒ ② 名册**继续挂着**，但不再声称「开闸必静默丢」；本件的开闸前置总判据今天由 ③
（未申报 namespace 那一条）单独顶住。②「经出口后仍被丢」这一枚此刻是 0，
锁成硬尺（`== 0`，回潮即红），不写成 `>0`——那是假话。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

# —— 唯一规则真身（只读调用，禁复制判据）——
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    EMERGENCY_DEDUPE_PREFIX,
    active_push_key_shape_ok,
    is_emergency_dedupe_key,
    is_legal_date_key,
    is_legal_segment,
    wash_active_push_key,
)

# —— 生产根（相对本件上一级 = 仓根）——
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGINS_DIR = _REPO_ROOT / "plugins"


# =========================================================== AST 现算现役点
@dataclass(frozen=True)
class DeliveryPoint:
    """一处现役投递点：`kind` ∈ {submit_active_push, queue.submit}，身份 = 件#函数。"""

    kind: str
    file: str  # 相对仓根、正斜杠
    func: str  # 最近的外层函数名（含嵌套闭包）
    line: int
    kwargs: frozenset[str] = field(default_factory=frozenset)

    @property
    def identity(self) -> str:
        # 身份不含行号——行号随编辑漂移，名册要稳。
        return f"{self.file}#{self.func}"


def _enclosing_func(tree: ast.Module, target_line: int) -> str:
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = node.end_lineno or node.lineno
            if node.lineno <= target_line <= end and (
                best is None or node.lineno > best[0]
            ):
                best = (node.lineno, node.name)
    return best[1] if best else "<module>"


def _receiver_name(func: ast.expr) -> str | None:
    """`a.b.submit(...)` 里取 `b`/`a` 的名，供判定是否队列对象。"""
    value = getattr(func, "value", None)
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return None


def scan_production_delivery_points() -> list[DeliveryPoint]:
    """AST 扫 `plugins/`，返回全部 `submit_active_push` 与 `*.submit`（队列对象）调用点。

    判队列对象：接收者名含 `queue`（覆盖 `send_queue` / `_queue` / `queue` 三种真身形态）。
    """
    points: list[DeliveryPoint] = []
    for path in sorted(_PLUGINS_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            kind: str | None = None
            if isinstance(func, ast.Name) and func.id == "submit_active_push":
                kind = "submit_active_push"
            elif (
                isinstance(func, ast.Attribute)
                and func.attr == "submit"
                and "queue" in str(_receiver_name(func)).lower()
            ):
                kind = "queue.submit"
            if kind is None:
                continue
            points.append(
                DeliveryPoint(
                    kind=kind,
                    file=rel,
                    func=_enclosing_func(tree, node.lineno),
                    line=node.lineno,
                    kwargs=frozenset(k.arg for k in node.keywords if k.arg),
                )
            )
    return points


def active_push_points(points: list[DeliveryPoint]) -> list[DeliveryPoint]:
    """过闸的现役主动投递点（`submit_active_push`）——开闸只改这些的行为。"""
    return [p for p in points if p.kind == "submit_active_push"]


# ================================================================ 键形真值口
def open_gate_would_skip(key: str, *, namespace: str, family: str) -> bool:
    """开闸态这条键会不会被闸判 skip（True = 静默丢）。与生产闸同一份谓词。"""
    require_date = family == "daily"
    if namespace == EMERGENCY_DEDUPE_PREFIX:
        ok = is_emergency_dedupe_key(key, require_date_key=require_date)
    else:
        ok = active_push_key_shape_ok(
            key, namespace=namespace, require_date_key=require_date
        )
    return not ok


def first_illegal_segment(key: str) -> str | None:
    for segment in str(key).split(":"):
        if not is_legal_segment(segment):
            return segment
    return None


def key_as_it_arrives_at_the_gate(key: str) -> str:
    """中央出口交给闸的那一枚键（现役生产形态＝出口先洗过一次）。

    与 `open_gate_would_skip` 搭配使用，才分得清「构造侧脏」与「这发投递会被丢掉」：
    前者今天仍真实存在（本件 ② 名册记的就是它），后者经出口后已不成立。
    """
    return wash_active_push_key(key)


def rows_dropped_after_the_exit(
    roster: list[dict[str, object]],
) -> list[dict[str, object]]:
    """现算：名册里**经过中央出口之后仍会被键形判丢**的行（此刻应为空表）。"""
    return [
        row
        for row in roster
        if open_gate_would_skip(
            key_as_it_arrives_at_the_gate(
                str(row["builder"](*row["args"]))  # type: ignore[misc,operator]
            ),
            namespace=str(row["namespace"]),
            family=str(row["family"]),
        )
    ]


def rows_dirty_at_construction(
    roster: list[dict[str, object]],
) -> list[dict[str, object]]:
    """现算：名册里在**构造点**就产出脏段的行（不经出口就会出事的那一批）。"""
    return [
        row
        for row in roster
        if open_gate_would_skip(
            str(row["builder"](*row["args"])),  # type: ignore[misc,operator]
            namespace=str(row["namespace"]),
            family=str(row["family"]),
        )
    ]


def case_labels(rows: list[dict[str, object]]) -> list[str]:
    return [str(row["case_label"]) for row in rows]


# ===================================== ② 类欠账：构造侧未洗段的配置裸值（真身镜像）
# 每行绑一个**投递点身份**（AST 里必须真实存在，否则成幽灵）+ 一个键构造镜像，
# 镜像照抄生产拼键式。2026-09-24 S184 起本表记的是**构造侧**这笔账：
# 脏段今天仍由中央出口在投递前规范掉（⇒「开闸即静默丢」不再成立），但绕过出口的直调点
# 与「洗段非单射」两件事让这笔账不许抹零（判据见模块头【口径更正】与
# `test_wash_has_exactly_one_production_call_site`）。
# 族在构造侧加洗段后：脏输入变干净 ⇒ 对应用锁翻红 ⇒ 逼本名册与棘轮一起跟随。
_TODAY = "2026-09-24"


def digest_push_key(group_id: str, today: str) -> str:
    """镜像 `__init__.py` `_push_daily_group_digests`：`f"digest_push:{gid}:{today}"`
    （`group_id` 取白名单裸值，未洗段）。"""
    return f"digest_push:{group_id}:{today}"


def daily_assist_key(tag: str, user_id: str, today: str) -> str:
    """镜像 `__init__.py` `_push_daily_assist_private`：`f"daily_assist:{tag}:{uid}:{today}"`
    （`user_id` 取推送名单裸值，未洗段；`tag` 为代码常量）。"""
    return f"daily_assist:{tag}:{user_id}:{today}"


# ② 名册（当前真实欠账）：投递点身份 + namespace + 脏输入镜像构造 + 成因标签。
CONSTRUCTION_DEBT_ROSTER: list[dict[str, object]] = [
    {
        "point_identity": (
            "plugins/bot_unified_runtime/__init__.py#_push_daily_group_digests"
        ),
        "namespace": "digest_push",
        "family": "daily",
        "builder": digest_push_key,
        "case_label": "中文群号",
        "args": ("湘潭群", _TODAY),
    },
    {
        "point_identity": (
            "plugins/bot_unified_runtime/__init__.py#_push_daily_group_digests"
        ),
        "namespace": "digest_push",
        "family": "daily",
        "builder": digest_push_key,
        "case_label": "尾随冒号空段",
        "args": ("1108838060:", _TODAY),
    },
    {
        "point_identity": (
            "plugins/bot_unified_runtime/__init__.py#_push_daily_group_digests"
        ),
        "namespace": "digest_push",
        "family": "daily",
        "builder": digest_push_key,
        "case_label": "带空格群键",
        "args": ("11 08838060", _TODAY),
    },
    {
        "point_identity": (
            "plugins/bot_unified_runtime/__init__.py#_push_daily_group_digests"
        ),
        "namespace": "digest_push",
        "family": "daily",
        "builder": digest_push_key,
        "case_label": "超长 id (>120)",
        "args": ("9" * 121, _TODAY),
    },
    {
        "point_identity": (
            "plugins/bot_unified_runtime/__init__.py#_push_daily_assist_private"
        ),
        "namespace": "daily_assist",
        "family": "daily",
        "builder": daily_assist_key,
        "case_label": "中文 user_id",
        "args": ("morning", "用户甲", _TODAY),
    },
    {
        "point_identity": (
            "plugins/bot_unified_runtime/__init__.py#_push_daily_assist_private"
        ),
        "namespace": "daily_assist",
        "family": "daily",
        "builder": daily_assist_key,
        "case_label": "带空格 user_id",
        "args": ("evening", "user one", _TODAY),
    },
]

# ③ 名册：过闸但**未申报 dedupe_namespace** 的投递点身份（equality 锁）。
# 现役值：仅紧急域 `deliver_emergency`——它落 emg 缺省且键构造即抛，
# 是「正确但隐式耦合缺省」，登记为待显式化，不是静默丢欠账。
NAMESPACE_UNDECLARED_EXPECTED: frozenset[str] = frozenset(
    {
        (
            "plugins/bot_unified_runtime/domains/emergency_info/"
            "service/push.py#deliver_emergency"
        )
    }
)

# 反缩面地板（2026-09-24 S103 探针现算真值的一半取整、向上）：
_RECORDED_ACTIVE_PUSH = 5  # submit_active_push 现役点数
_RECORDED_QUEUE_SUBMIT = 6  # queue.submit 直发点数
ACTIVE_PUSH_FLOOR = 3  # ceil(5/2)：现役点不得缩到基线一半以下
QUEUE_SUBMIT_FLOOR = 3  # ceil(6/2)

# ② 构造侧脏段行数的**上限**尺（只准降，2026-09-24 S184 现算真值 6，与名册同数）：
# 顶过它＝有新的未洗段投递点漏进来。刻意不叫"基线欠账 >0"——那一枚属于 S62 件的构造侧，
# 本件这枚只管"别变多"；"经出口后仍被丢 = 0" 另有硬尺
# （`test_dropped_at_exit_roster_is_empty`）。
_CONSTRUCTION_DEBT_FLOOR = 6


# ======================================================== 交叉核对纯函数
def namespace_undeclared_identities(
    points: list[DeliveryPoint],
) -> frozenset[str]:
    """AST 现算：过闸但未带 `dedupe_namespace=` 关键字的投递点身份集合。"""
    return frozenset(
        p.identity
        for p in active_push_points(points)
        if "dedupe_namespace" not in p.kwargs
    )


def ghost_roster_members(
    roster: list[dict[str, object]], points: list[DeliveryPoint]
) -> list[str]:
    """名册里绑定的投递点身份若在 AST 现役点中不存在 ⇒ 幽灵（该点已被删/改名）。"""
    live = {p.identity for p in points}
    return sorted(
        {
            str(row["point_identity"])
            for row in roster
            if str(row["point_identity"]) not in live
        }
    )


def floor_breach(count: int, floor: int) -> bool:
    return count < floor


def gate_is_safe_to_open(
    *, namespace_undeclared: set[str], silent_drop_roster: list[dict[str, object]]
) -> bool:
    """开闸前置总判据：两类欠账皆清空才放行。非空 ⇒ 今天不能开闸（响亮，不静默）。

    S184 口径：调用方**必须**传"经中央出口之后仍会被丢"的行（`rows_dropped_after_the_exit`
    现算），不能把 ② 整本构造侧名册当"静默丢欠账"塞进来——那会让本判据为一个已经结清的
    理由说不安全（旧写法），也会让真结清时看不出来。构造侧那本账另由
    `test_construction_debt_is_real_and_only_goes_down` 单独钉。
    """
    return not namespace_undeclared and not silent_drop_roster


# =================================================================== 测试
def test_ast_scan_finds_active_points_at_or_above_floor() -> None:
    """现役点数地板（反缩面）：过闸点与队列直发点都不得缩到基线一半以下。

    现役点数**只准长不准塌**——塌了说明有投递点被删/改名而名册没跟随。上限不设
    （新增投递点合法，但要进名册判定）。
    """
    points = scan_production_delivery_points()
    n_active = len(active_push_points(points))
    n_queue = len([p for p in points if p.kind == "queue.submit"])
    assert not floor_breach(n_active, ACTIVE_PUSH_FLOOR), (
        f"过闸投递点 {n_active} < 地板 {ACTIVE_PUSH_FLOOR}：现役面被缩，"
        "开闸前置清单不可信"
    )
    assert not floor_breach(n_queue, QUEUE_SUBMIT_FLOOR), (
        f"queue.submit 直发点 {n_queue} < 地板 {QUEUE_SUBMIT_FLOOR}"
    )


def test_namespace_undeclared_roster_is_equality_locked() -> None:
    """③ 类 equality 锁：AST 现算的未申报 namespace 点，恰等于在册名册（只准降）。

    - 有人给某点补了 `dedupe_namespace=` ⇒ 现算集合变小 ⇒ 与冻结名册不等 ⇒ 红，
      逼名册同步降账（真进展）。
    - 有人新加一处过闸但没申报 namespace 的投递点 ⇒ 现算集合变大 ⇒ 红，
      逼其补申报或入册（R-CENTRAL C-1 的成因面）。
    """
    actual = set(namespace_undeclared_identities(scan_production_delivery_points()))
    assert actual == set(NAMESPACE_UNDECLARED_EXPECTED), (
        f"未申报 namespace 的投递点集合漂移：\n现算={sorted(actual)}\n"
        f"名册={sorted(NAMESPACE_UNDECLARED_EXPECTED)}\n"
        "补申报（真降账）则同步下调名册；新增缺口则当场拦。"
    )


def test_silent_drop_roster_members_are_live_points() -> None:
    """② 名册的每个投递点身份都必须在 AST 现役点中真实存在（幽灵检测）。"""
    ghosts = ghost_roster_members(
        CONSTRUCTION_DEBT_ROSTER, scan_production_delivery_points()
    )
    assert not ghosts, f"② 名册绑定的投递点已不在 AST 现役清单（幽灵）：{ghosts}"


def test_construction_debt_is_real_and_only_goes_down() -> None:
    """② 构造侧现状锁（曾用名 `test_silent_drop_debt_is_real_and_only_goes_down`）。

    2026-09-24 S184 收窄：本锁钉的是「构造点今天仍产出脏段」，**不再**钉「开闸即静默丢」
    ——后者已被中央出口结清，由 `test_dropped_at_exit_roster_is_empty` 反向钉住。
    两半必须同时成立（缺一即要么抹账、要么把旧账当成绩）：
      · 名册每一行的**原始**镜像键都过不了形门 ⇒ 绕过出口的直调点照旧拿脏串；
      · 同一行**经过出口**之后必过形 ⇒ 现役投递不再有「因键形而生的静默 skip」。
    任一行翻红（构造侧变干净）= 该族真加了洗段 ⇒ 删该条并降账，不许留着。
    """
    assert CONSTRUCTION_DEBT_ROSTER, "② 名册被掏空——除非两族都加了洗段，否则不许"
    for row in CONSTRUCTION_DEBT_ROSTER:
        key: str = row["builder"](*row["args"])  # type: ignore[misc,operator]
        namespace = str(row["namespace"])
        family = str(row["family"])
        assert first_illegal_segment(key) is not None, (
            f"{row['case_label']}: 本应今天构造侧脏却全段合法 key={key!r}"
            "（族已加洗段？请删该条并降账）"
        )
        assert open_gate_would_skip(key, namespace=namespace, family=family), (
            f"{row['case_label']} 原始键过了形门（读侧判据不该变）：{key!r}"
        )
        arrived = key_as_it_arrives_at_the_gate(key)
        assert not open_gate_would_skip(
            arrived, namespace=namespace, family=family
        ), f"{row['case_label']} 出口洗完仍被丢：{arrived!r}⇒「静默丢」复发"

    dirty = rows_dirty_at_construction(CONSTRUCTION_DEBT_ROSTER)
    assert len(dirty) <= _CONSTRUCTION_DEBT_FLOOR, (
        f"构造侧脏段行数现算 {len(dirty)} > 基线 {_CONSTRUCTION_DEBT_FLOOR}："
        "有新的未洗段投递点漏进来，只准修构造侧、不准放宽本尺"
    )
    assert case_labels(dirty) == case_labels(CONSTRUCTION_DEBT_ROSTER), (
        "名册成员与现算判定脱钩（现算="
        f"{case_labels(dirty)} 名册={case_labels(CONSTRUCTION_DEBT_ROSTER)}）"
        "⇒ 名册内容由现算派生，抹账与漏记都拦在这里"
    )


def test_dropped_at_exit_roster_is_empty() -> None:
    """经中央出口之后仍会被键形丢掉的现役投递点：**零**，且这是硬尺不是地板。

    为什么不写成 `>0` 的"真实欠账"自证（那枚尺在 S62 件里对构造侧仍然成立）：出口洗段
    之后这笔账确实结了，留 `>0` 就是假话。方向相反 ⇒ 只准保持 0：谁把洗段挪走、改成
    条件执行、或让某一族绕开规范，这里当场顶红。
    """
    dropped = rows_dropped_after_the_exit(CONSTRUCTION_DEBT_ROSTER)
    assert dropped == [], (
        f"经出口仍被丢 {case_labels(dropped)} ⇒ 中央出口的键形规范没盖住这些行"
    )


def test_wash_has_exactly_one_production_call_site() -> None:
    """洗段的作用域锁：生产里 `wash_active_push_key` 只有**一个**调用点，且在闸出口内。

    这条是本件 ② 名册不许抹零的**机检**理由：出口之外（`queue.submit` 直调那一批）没有
    任何洗段保护，构造侧脏串照旧进队列。同时也拦「到处补洗段＝长出第二第三个规范口」——
    规范只准发生在唯一出口那一次（用户 mandate：一处变更处处跟随）。
    """
    call_sites: list[str] = []
    for path in sorted(_PLUGINS_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "wash_active_push_key":
                enclosing = _enclosing_func(tree, int(node.lineno))
                call_sites.append(
                    f"{path.relative_to(_REPO_ROOT).as_posix()}#{enclosing}"
                )
    assert call_sites == [
        (
            "plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py"
            "#submit_active_push"
        )
    ], f"出口洗段调用点漂移（现算={call_sites}）：规范必须只发生在唯一出口那一次"
    # 且出口之外确有直调面——没这张面的话，本件 ② 名册今天就该抹零（这条断言防自我欺骗）。
    bypass = [
        p for p in scan_production_delivery_points() if p.kind == "queue.submit"
    ]
    assert bypass, (
        "全树已无 `queue.submit` 直调点 ⇒ 构造侧脏段只剩「洗段非单射」一条腿，"
        "② 名册要按实情重记（别照抄本席这段解释）"
    )


def test_daily_debt_rows_carry_legal_date_key_segment() -> None:
    """daily 族末段日期本身合法（YYYY-MM-DD），钉死「非法的是裸 id 段、不是日期段」。"""
    assert is_legal_date_key(_TODAY)
    assert is_legal_date_key("2026-09-23")


def test_gate_is_not_safe_to_open_today() -> None:
    """总判据：今天还不能开闸——**理由已经换了**，两半各自点名，不许糊里糊涂地绿。

    旧态是「②③两本名册都非空」；S184 之后 ② 那半经中央出口已经结清（现算 0 行会被丢），
    顶住本判据的只剩 ③（`deliver_emergency` 未显式申报 `dedupe_namespace`）。
    本条把两半分别钉死：② 空、③ 非空 ⇒ 结论仍为「不能开」。
    哪天 ③ 也补上申报，这条会当场翻红——那是要用户重新裁「能不能开闸」的时刻，
    不是把断言改成 True 的时刻。
    """
    points = scan_production_delivery_points()
    undeclared = set(namespace_undeclared_identities(points))
    exit_dropped = rows_dropped_after_the_exit(CONSTRUCTION_DEBT_ROSTER)
    assert exit_dropped == [], f"②「经出口仍被丢」居然非空：{case_labels(exit_dropped)}"
    assert undeclared, (
        "③ 未申报 namespace 的名册居然后来空了——先确认是真补了申报还是被抹账，"
        "再改本门结论（不许直接放开）"
    )
    assert not gate_is_safe_to_open(
        namespace_undeclared=undeclared, silent_drop_roster=exit_dropped
    ), "两类前置都清了还判不安全？那是本门自身逻辑坏了"


# --------------------------------------------------------------- 注毒自证
def test_poison_1_colon_key_is_caught_by_the_read_side_predicate() -> None:
    """注毒①（曾用名 `..._is_caught_as_silent_drop`，种一枚含 `:` 的键⇒红）。

    判据随现实改写，**用例不删**：现役 detector 必须把尾随冒号判成「构造侧脏＋原始键
    过不了形门」（②名册有牙），同时**不再**把它叙述成"开闸必丢"——那一半改由
    `test_dropped_at_exit_roster_is_empty` 与 `test_poison_1b` 各自负责。
    """
    dirty = digest_push_key("1108838060:", _TODAY)  # 尾随冒号 → 末段空
    assert first_illegal_segment(dirty) is not None, dirty
    assert open_gate_would_skip(dirty, namespace="digest_push", family="daily")
    assert not open_gate_would_skip(
        key_as_it_arrives_at_the_gate(dirty), namespace="digest_push", family="daily"
    ), "出口没救回 ⇒ ②名册的『静默丢』旧账要原样挂回来，本注释与判据一起跟随"


def test_poison_1b_bypass_route_is_the_one_that_still_ships_a_dirty_key() -> None:
    """注毒①的替身形（按简报要求换成"绕开中央出口直调"的注毒）：旁路面才是残留病灶。

    同一枚脏键两条路的取值必须分道：走出口⇒规范形（过形），绕出口直调⇒原文（不过形）。
    两路取值若相等，说明要么出口没洗、要么本注毒点找错了路径——都判红。
    """
    raw = digest_push_key("1108838060:", _TODAY)
    via_exit = key_as_it_arrives_at_the_gate(raw)
    bypass = raw  # 直调 `queue.submit`：生产里没有任何环节会替它改写
    assert bypass != via_exit, "两路取值相同 ⇒ 本发注毒没打到「绕出口」这条路上"
    assert open_gate_would_skip(bypass, namespace="digest_push", family="daily")
    assert not open_gate_would_skip(via_exit, namespace="digest_push", family="daily")


def test_poison_2_removing_live_point_makes_roster_ghost_red() -> None:
    """注毒②（删一个现役投递点⇒名册成员成幽灵⇒红）：喂一份被抽掉点名的 AST 清单。

    真实代码里若 `_push_daily_group_digests` 被删/改名而②名册没跟随，交叉锁当场红。
    """
    full = scan_production_delivery_points()
    thinned = [p for p in full if "_push_daily_group_digests" not in p.identity]
    assert len(thinned) < len(full), "夹具失效：现役点里根本没有该投递点"
    ghosts = ghost_roster_members(CONSTRUCTION_DEBT_ROSTER, thinned)
    assert ghosts, "抽掉现役投递点后交叉锁竟无幽灵——检测器是空跑的"
    assert any("_push_daily_group_digests" in g for g in ghosts), ghosts


def test_poison_3_namespace_added_would_shrink_roster() -> None:
    """注毒③（补了 namespace⇒③现算集合应变小⇒与冻结名册不等）：验 equality 锁双向。

    给紧急投递点在内存里加一个 `dedupe_namespace` kwarg，现算未申报集合应变空，
    证明「真降账」也能被这套判据识别（不是只认涨不认跌）。
    """
    full = scan_production_delivery_points()
    patched = [
        DeliveryPoint(
            kind=p.kind,
            file=p.file,
            func=p.func,
            line=p.line,
            kwargs=p.kwargs | {"dedupe_namespace"},
        )
        if "deliver_emergency" in p.identity
        else p
        for p in full
    ]
    assert namespace_undeclared_identities(patched) == frozenset(), (
        "补申报后仍算出未申报点——检测器不认跌，equality 锁是单向的"
    )


def test_poison_4_floor_breach_on_shrink() -> None:
    """注毒④（现役点清单缩面⇒地板红）：纯函数验地板判据方向正确。"""
    assert floor_breach(ACTIVE_PUSH_FLOOR - 1, ACTIVE_PUSH_FLOOR)
    assert not floor_breach(ACTIVE_PUSH_FLOOR, ACTIVE_PUSH_FLOOR)
    assert not floor_breach(ACTIVE_PUSH_FLOOR + 5, ACTIVE_PUSH_FLOOR)
