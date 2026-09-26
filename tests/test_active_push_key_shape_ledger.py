r"""六族主动投递 `dedupe_key` 键形审计（席位 S62，出站闸灰度开闸的硬前置）。

背景（本波 PARKED CM-P-11）：出站闸 `bot_outbound_gate_enabled` 缺省关；关态
`decide` 早退 ⇒ 非法 dedupe 键今天照投不报错，开闸后同一条会被判
`skip, reason="dedupe_key_shape"` ＝ **静默丢投递**。本仓已为此咬过两次
（紧急域 `nmc:A1` 见 #46、慢回复回执直拼 `session_id` 见 #50）。CM-P-11 记的账是
「逐族键形审计今天只做过 ack 一族」，五族未逐条读构造代码验证——本件把六族补齐。

唯一合法判据（宪法件，禁在测试里抄第二份正则）：
`domains/emergency_info/service/dedupe.py:is_legal_segment`
（段集 `^[A-Za-z0-9_.\-]{1,120}$`，`:` 是段分隔符）。本件只**读**并**调用**它，
绝不重定义规则；闸侧的"整条键能否过形门"另用同一模块的公开谓词
`active_push_key_shape_ok`（非 `emg` 族）与 `is_emergency_dedupe_key`（`emg` 族）
作为"开闸后到底会不会 skip"的真值口——这两个函数正是 `outbound_gate.dedupe_key_shape_ok`
委托落到的同一处实现，故本件与生产闸逐字节同源。

六族现役键构造（逐条读码所得，构造点坐标见各族 builder docstring）：
- 提醒 reminder            `f"reminder:{reminder_id}"`            （once）
- cookie 到期 cookie-expiry `f"cookie-expiry:{admin_id}:{today}"`  （daily）
- 群摘要 digest_push       `f"digest_push:{group_id}:{today}"`     （daily）
- 日常助理 daily_assist    `f"daily_assist:{tag}:{user_id}:{today}"`（daily）
- 紧急信息 emg             `build_emergency_dedupe_key(...)`       （daily，构造即校验即抛）
- 慢回复回执 ack           `f"ack:chat:{wash(sid)}:{wash(mid)}:{digest}"`（once，已修：洗段）

审计结论的两种落法（不偷偷放宽、不加 skip/xfail）：
- 某族对**真实可达输入**今天确实会产出非法段（不经出口就会静默丢）⇒ 写"现状存在锁"
  断言"今天确实非法"，族修好后该锁当场翻红、逼修法与基线一起跟随；
- 某族对全部真实输入今天都合法 ⇒ 写"保绿锁"，回潮即红。

【2026-09-24 S184 口径更正（必读，覆盖上方与下方所有「开闸即静默丢」写法）】
中央唯一出口 `submit_active_push` 现在在 `gate.decide` **之前**把 `dedupe_key` 交给
`dedupe.py:wash_active_push_key` 规范一次（段级脏⇒洗；洗完退化⇒摘要兜底）。于是：

- 「构造侧脏段 ⇒ 开闸整族静默丢」这句**只对绕过出口的投递点成立**。走出口的现役族
  开闸也不会丢——脏段会被改写后放行（并留一行 WARNING）。⇒ 本件的名册不再叫
  "CURRENTLY_DROPPING"（曾用名，跨席日志按旧名可查），改叫
  `CURRENTLY_DIRTY_AT_CONSTRUCTION`：记的是**构造侧**这笔账，不是"开闸必丢"。
- 构造侧这笔账**不许抹零**，两个真理由（都有锁，不是修辞）：
  ① 绕过中央出口的直调点（`queue.submit` 一族）没有洗段保护——见
     `tests/test_outbound_gate.py::test_bypass_of_the_central_exit_ships_the_raw_dirty_key`；
  ② 出口洗段**不是单射**：`11 08838060` 与 `11_08838060` 会塌成同一段
     （见 `test_wash_residual_non_injective_punctuation_and_truncation`，同文件）。
     构造侧先按各族身份洗干净，才谈得上"同一身份恒同键"。
- 因此本件的地板拆成两枚：`_DIRTY_AT_CONSTRUCTION_BASELINE`（>0 是真欠账，此刻 6）与
  `_DROPPED_AT_EXIT_BASELINE`（经出口后仍被丢的条数，此刻 0；回潮即红）。
  后者不许写成 `>0`——那会是一句假话；它锁的是"名册内容与现算恒等 + 名册由现算派生"。
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

# —— 慢回复回执的洗段件（被注毒 A 拿掉即应露牙）——
from plugins.bot_unified_runtime.domains.chat_reply.runtime.progress_ack import (
    ACK_DEDUPE_NAMESPACE,
    ack_key_segment,
    build_progress_ack_request,
)

# —— 唯一规则真身（只读调用，禁复制判据）——
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    EMERGENCY_DEDUPE_PREFIX,
    active_push_key_shape_ok,
    build_emergency_dedupe_key,
    is_emergency_dedupe_key,
    is_legal_date_key,
    is_legal_segment,
    wash_active_push_key,
)

# ------------------------------------------------------------------ 各族键构造
# 下面每个 builder 是对生产拼键语句的逐字镜像（docstring 标注真身坐标）。
# 审计的是"构造"，所以必须照抄构造式；判合法性一律回喂中央谓词，不在此写规则。


def reminder_key(reminder_id: str) -> str:
    """镜像 `__init__.py:3005` `_deliver_due_reminders`：`f"reminder:{reminder.reminder_id}"`。

    `reminder_id` 真身 = `domains/schedule/store/reminders.py:446`
    `sha1(...).hexdigest()[:12]`，以及 :263 `f"gov-{digest}"`（治理回执），二者皆合法段。
    """
    return f"reminder:{reminder_id}"


def cookie_expiry_key(admin_id: str, today: str) -> str:
    """镜像 `__init__.py:3132` `_deliver_cookie_expiry_report_via_queue`。

    注意同函数 :3120 `target_id=str(int(admin_id))` 会先把非数字 admin 判崩
    （抛 ValueError 走 except 换下一个管理员），故本族的非法段风险面被这道 int() 闸挡在
    submit 之前——这是"崩"（响亮）不是"静默丢"，与键形审计不同类，见 roster 归属。
    """
    return f"cookie-expiry:{admin_id}:{today}"


def digest_push_key(group_id: str, today: str) -> str:
    """镜像 `__init__.py:3309` `_push_daily_group_digests`（group_id 取 whitelist 裸值，**未洗段**）。"""
    return f"digest_push:{group_id}:{today}"


def daily_assist_key(tag: str, user_id: str, today: str) -> str:
    """镜像 `__init__.py:3471` `_push_daily_assist_private`（user_id 取推送名单裸值，**未洗段**）。"""
    return f"daily_assist:{tag}:{user_id}:{today}"


def emergency_key(channel: str, item_id: str, target_id: str, date_key: str) -> str:
    """镜像 `domains/emergency_info/service/push.py:354` `deliver_emergency`。

    直接调中央 builder：它对非法入参**当场抛 ValueError**（`build_emergency_dedupe_key`
    逐段 `_SEGMENT_RE` 校验），从不产出一枚"看着像键却会被闸判 skip"的脏键——
    故紧急族的失败模式是响亮抛异常（push.py:331-333 明写"不吞"），不是静默丢。
    """
    return build_emergency_dedupe_key(
        channel, item_id, target_id, date_key=date_key
    )


def ack_key(session_id: str, origin: str, digest: str) -> str:
    """镜像 `progress_ack.py:313-316` `build_progress_ack_request`（**经洗段**，#50 已修）。"""
    return (
        f"{ACK_DEDUPE_NAMESPACE}:chat:"
        f"{ack_key_segment(session_id)}:{ack_key_segment(origin)}:{digest}"
    )


def ack_key_unwashed(session_id: str, origin: str, digest: str) -> str:
    """注毒 A 专用：把 `ack_key_segment()` 洗段**去掉**，直拼 session/origin。

    这不是现役代码，是"若有人删掉构造侧洗段"的反事实——用来验保绿锁有牙：现役 ack_key
    对脏 session 判合法，而本函数对同一脏 session 必判非法（⇒ 若生产真被改回裸拼，
    `test_poison_a_removing_ack_washing_breaks_legality` 的两侧断言当场分道）。

    S184 口径：构造侧回退今天**不再**等于「静默丢回执」（中央出口会兜住段级脏），但它
    等于「绕过出口的旁路面拿到脏键」+「同身份在出口前后两种键形」，所以这条锁仍然要留。
    """
    return (
        f"{ACK_DEDUPE_NAMESPACE}:chat:"
        f"{str(session_id).strip()}:{str(origin).strip()}:{digest}"
    )


# ---------------------------------------------------------------- 闸真值口
# family 与 gate 的映射照 `outbound_gate.dedupe_key_shape_ok`（:301 require_date_key
# = family == "daily"）；namespace 非 emg 走 active_push_key_shape_ok，emg 走紧急谓词。


def open_gate_would_skip(key: str, *, namespace: str, family: str) -> bool:
    """开闸态：这条键会不会被闸判 skip（True = 静默丢）。与生产闸同一份谓词。"""
    require_date = family == "daily"
    if namespace == EMERGENCY_DEDUPE_PREFIX:
        ok = is_emergency_dedupe_key(key, require_date_key=require_date)
    else:
        ok = active_push_key_shape_ok(
            key, namespace=namespace, require_date_key=require_date
        )
    return not ok


def key_as_it_arrives_at_the_gate(key: str) -> str:
    """中央出口交给闸的那一枚键 = 出口洗过之后的形态（`submit_active_push` 同口）。

    本件其余函数一律判「镜像构造出来的原始键」，那枚键在现役生产里**已经不再**直接进闸。
    两把尺分开用，才分得清「构造侧脏」与「投递会被丢」是两件事（S184 口径更正）。
    """
    return wash_active_push_key(key)


def first_illegal_segment(key: str) -> str | None:
    """逐段喂中央 `is_legal_segment`，返回第一段非法的原文（全合法则 None）。"""
    for segment in str(key).split(":"):
        if not is_legal_segment(segment):
            return segment
    return None


# ------------------------------------------------------------------- 最坏输入
# 每族一组"真实可达最坏输入"（含简报点名的：中文群号 / 带 `:` 的 session·群键 /
# 超长 id / 非数字管理员号 / `*` 通配 / 跨天 date_key）。
# 跨天 date_key 用昨日 ISO（`.date().isoformat()` 恒零填充，是合法段，用来证明"跨天不误杀"）。

_LEGAL_GROUP = "1108838060"
_LEGAL_USER = "3865067623"
_TODAY = "2026-09-24"
_YESTERDAY = "2026-09-23"
_LONG_ID = "9" * 121  # 121 位 > _SEGMENT_RE 上限 120


# (label, args) 的族登记表；输入用各族自己的坐标点构造。镜像的生产拼键式见各 builder。
FAMILIES_SAFE_TODAY: list[dict[str, object]] = [
    {
        "family": "reminder",
        "namespace": "reminder",
        "gate_family": "once",
        "builder": reminder_key,
        "worst_cases": [
            ("sha1 hex", ("1a2b3c4d5e6f",)),
            ("gov 回执", ("gov-9f8e7d6c",)),
            ("跨天不影响", ("a" * 12,)),
        ],
    },
    {
        "family": "cookie-expiry",
        "namespace": "cookie-expiry",
        "gate_family": "daily",
        "builder": cookie_expiry_key,
        # 数值型 admin：本族 int() 闸已挡非数字，故只列数值 + 跨天两类真实可达输入
        "worst_cases": [
            ("numeric admin", (_LEGAL_USER, _TODAY)),
            ("跨天 date_key", (_LEGAL_USER, _YESTERDAY)),
        ],
    },
    {
        "family": "daily-assist-tag",  # 只测 tag 维度（tag 为代码常量，恒合法）
        "namespace": "daily_assist",
        "gate_family": "daily",
        "builder": daily_assist_key,
        "worst_cases": [
            ("meal 正常", ("meal", _LEGAL_USER, _TODAY)),
            ("morning 跨天", ("morning", _LEGAL_USER, _YESTERDAY)),
        ],
    },
    {
        "family": "emergency",
        "namespace": EMERGENCY_DEDUPE_PREFIX,
        "gate_family": "daily",
        "builder": emergency_key,
        "worst_cases": [
            ("nmc 已修连字符", ("qq", "nmc-A1", _LEGAL_GROUP, _TODAY)),
            ("usgs 带日期段", ("group", "usgs-us600000ab", _LEGAL_GROUP, _YESTERDAY)),
        ],
    },
    {
        "family": "ack",
        "namespace": ACK_DEDUPE_NAMESPACE,
        "gate_family": "once",
        "builder": ack_key,
        "worst_cases": [
            ("脏 session 已洗", ("group_1108838060_3865067623", "42", "1a2b3c4d")),
            ("TG 带空格会话", ("chan nel:1", "a:b", "deadbeef")),
        ],
    },
]


# ------------------------------------------------------------------- 棘轮基线
# 两枚账（2026-09-24 S184 拆分，理由见模块头【口径更正】）：
#   `_DIRTY_AT_CONSTRUCTION_BASELINE` —— **构造侧**脏段行数（不经出口就会静默丢），
#       现算真值 6，是笔真实 > 0 的欠账（直调旁路面 + 洗段非单射 ⇒ 不许抹零）；
#   `_DROPPED_AT_EXIT_BASELINE` —— 同一批输入**经过中央出口**后仍会被键形判丢的条数，
#       现算真值 0。这一枚地板不许写成 `>0`（那是假话），它锁的是「名册与现算恒等 +
#       名册内容由现算派生」（见 `test_roster_content_is_derived_from_the_current_tree`）。
# 两者都由 `test_illegal_segment_construction_count_only_goes_down` 走「只准降不准升」。
_DIRTY_AT_CONSTRUCTION_BASELINE = 6  # 2026-09-24 S62 探针现算真值（digest 4 + daily_assist 2）
_DROPPED_AT_EXIT_BASELINE = 0  # 2026-09-24 S184 现算真值（出口洗段之后）


# 构造侧脏段名册（曾用名 `CURRENTLY_DROPPING`）：族名 + 脏输入 + 该键。
# 今天仍然脏 ⇒ 直调旁路面与「同身份恒同键」两件事都还立不住；
# 族在构造侧加洗段后 ⇒ 对应用例翻红 ⇒ 逼本表与棘轮一起降账。
CURRENTLY_DIRTY_AT_CONSTRUCTION: list[dict[str, object]] = [
    {
        "family": "digest_push",
        "namespace": "digest_push",
        "gate_family": "daily",
        "builder": digest_push_key,
        "case_label": "中文群号",
        "args": ("湘潭群", _TODAY),
    },
    {
        "family": "digest_push",
        "namespace": "digest_push",
        "gate_family": "daily",
        "builder": digest_push_key,
        "case_label": "超长长 id",
        "args": (_LONG_ID, _TODAY),
    },
    {
        "family": "digest_push",
        "namespace": "digest_push",
        "gate_family": "daily",
        "builder": digest_push_key,
        "case_label": "带空格群键",
        "args": ("11 08838060", _TODAY),
    },
    {
        "family": "digest_push",
        "namespace": "digest_push",
        "gate_family": "daily",
        "builder": digest_push_key,
        "case_label": "尾随冒号空段",
        "args": ("1108838060:", _TODAY),
    },
    {
        "family": "daily_assist",
        "namespace": "daily_assist",
        "gate_family": "daily",
        "builder": daily_assist_key,
        "case_label": "中文 user_id",
        "args": ("morning", "用户甲", _TODAY),
    },
    {
        "family": "daily_assist",
        "namespace": "daily_assist",
        "gate_family": "daily",
        "builder": daily_assist_key,
        "case_label": "带空格 user_id",
        "args": ("evening", "user one", _TODAY),
    },
]


# ====================================================================== 测试
def test_six_families_all_reachable_via_central_predicates() -> None:
    """元锁：六族至少各有一条构造被本件覆盖（防 roster 被掏空后审计空跑）。"""
    covered = {
        *[row["family"] for row in FAMILIES_SAFE_TODAY],  # type: ignore[misc]
        *[row["family"] for row in CURRENTLY_DIRTY_AT_CONSTRUCTION],  # type: ignore[misc]
    }
    assert covered >= {
        "reminder",
        "cookie-expiry",
        "daily-assist-tag",
        "emergency",
        "ack",
        "digest_push",
        "daily_assist",
    }, covered


@pytest.mark.parametrize(
    "row",
    FAMILIES_SAFE_TODAY,
    ids=lambda r: r["family"],  # type: ignore[index]
)
def test_safe_families_keys_are_legal_and_not_skipped_by_gate(row: dict) -> None:
    """保绿锁：真实可达输入下，键的每个段都合法、且开闸不会被判 skip。

    若哪天有人把某族的洗段/校验拿掉、或改拼键式，此锁当场红。
    """
    builder: Callable[..., str] = row["builder"]  # type: ignore[assignment]
    namespace: str = row["namespace"]  # type: ignore[assignment]
    gate_family: str = row["gate_family"]  # type: ignore[assignment]
    for case_label, args in row["worst_cases"]:  # type: ignore[misc]
        key = builder(*args)
        offending = first_illegal_segment(key)
        assert offending is None, (
            f"{row['family']}/{case_label}: 段 {offending!r} 非法，键={key!r}"
        )
        assert not open_gate_would_skip(
            key, namespace=namespace, family=gate_family
        ), f"{row['family']}/{case_label}: 开闸会 skip（静默丢），键={key!r}"


def test_daily_families_carry_legal_date_key_segment() -> None:
    """daily 族的末段必须是合法 YYYY-MM-DD（`is_legal_date_key`），跨天不误杀。"""
    for key in (
        cookie_expiry_key(_LEGAL_USER, _TODAY),
        cookie_expiry_key(_LEGAL_USER, _YESTERDAY),
        daily_assist_key("meal", _LEGAL_USER, _TODAY),
    ):
        last = str(key).split(":")[-1]
        assert is_legal_date_key(last), f"末段日期非法: {last!r} in {key!r}"


@pytest.mark.parametrize(
    "row",
    CURRENTLY_DIRTY_AT_CONSTRUCTION,
    ids=lambda r: f"{r['family']}:{r['case_label']}",  # type: ignore[index]
)
def test_dirty_at_construction_families_existence_lock(row: dict) -> None:
    """构造侧存在锁（不加 skip/xfail）：这六条输入今天在**构造点**仍产出非法段。

    2026-09-24 S184 起本锁只管构造侧，**不再宣称「开闸即静默丢」**——中央出口会先把
    段级脏规范成合法键（第二半断言钉的就是这件事）。两半同时成立才算这笔账如实：

    - 原始构造脏 ⇒ 绕过中央出口的直调点（`queue.submit` 一族）仍会把脏串送进队列；
    - 过完出口干净 ⇒ 现役各族不再有「因键形而生的静默 skip」。

    构造侧哪天加了洗段，第一半当场翻红 ⇒ 逼本表与棘轮一起降账，不许静默改判据。
    """
    builder: Callable[..., str] = row["builder"]  # type: ignore[assignment]
    key = builder(*row["args"])  # type: ignore[misc]
    namespace = str(row["namespace"])
    gate_family = str(row["gate_family"])
    assert first_illegal_segment(key) is not None, (
        f"{row['family']}/{row['case_label']} 本应今天构造侧非法，却全段合法：键={key!r}"
        "（说明族已加洗段——请删除此条目并降棘轮基线）"
    )
    assert open_gate_would_skip(
        key, namespace=namespace, family=gate_family
    ), f"{row['family']}/{row['case_label']} 原始键过了形门（读侧判据不该变）：{key!r}"

    arrived = key_as_it_arrives_at_the_gate(key)
    assert not open_gate_would_skip(
        arrived, namespace=namespace, family=gate_family
    ), (
        f"{row['family']}/{row['case_label']} 出口洗完仍会被闸判丢：{arrived!r}"
        "⇒ 中央出口的键形规范失手＝「开闸即静默丢」复发，本席旧账要重新挂红"
    )


def test_dirty_at_construction_baseline_is_recorded_nonzero() -> None:
    """自证：构造侧欠账基线必须是真实 > 0 的数（禁把基线填 0 假装干净）。

    这枚 `>0` **只属于构造侧**。「同一批输入经出口后仍会被键形丢掉」的条数此刻是 0，
    那一枚不许也写成 `>0`——那是假话；它改锁「名册与现算恒等 + 名册内容由现算派生」
    （见 `test_dropped_at_exit_count_is_zero` 与
    `test_roster_content_is_derived_from_the_current_tree`）。
    """
    assert _DIRTY_AT_CONSTRUCTION_BASELINE > 0, (
        "构造侧脏段基线为 0——要么探针未回填、要么把账抹平了"
    )


def test_dirty_at_construction_count_only_goes_down() -> None:
    """只降不升棘轮（构造侧）：现算脏段构造数 ≤ 基线。

    族修好后计数下降属预期（跟随降基线）；任何新增「未洗段的脏配置投递族」会把计数顶过
    基线 ⇒ 当场红。
    """
    current = _count_dirty_at_construction()
    assert current <= _DIRTY_AT_CONSTRUCTION_BASELINE, (
        f"构造侧脏段数回潮 {current} > 基线 {_DIRTY_AT_CONSTRUCTION_BASELINE}："
        "有新族产非法段或既有族洗段被移除——不得放宽，请修构造侧"
    )


def test_dropped_at_exit_count_is_zero() -> None:
    """经中央出口之后仍会被键形丢掉的条数：现算 0 且必须保持 0（回潮即红）。

    方向与上一条相反：那是「只准降」的欠账棘轮，这是「只准保持 0」的硬尺。理由＝这笔账
    确实已被出口结清，继续挂 `>0` 就是把旧欠账当成绩；反过来一旦有人把洗段挪走、
    改成条件执行或只覆盖某几族，这里当场顶红。
    """
    current = _count_dropped_at_exit()
    assert current == _DROPPED_AT_EXIT_BASELINE == 0, (
        f"经出口后仍被丢 {current} 条（基线 {_DROPPED_AT_EXIT_BASELINE}）："
        "中央出口的键形规范没盖住名册里的输入，现役族又开始静默丢投递"
    )


def _row_key(row: dict[str, object]) -> str:
    builder: Callable[..., str] = row["builder"]  # type: ignore[assignment]
    return builder(*row["args"])  # type: ignore[misc,operator]


def _row_identity(row: dict[str, object]) -> str:
    return f"{row['family']}::{row['case_label']}"


def _count_dirty_at_construction() -> int:
    """现算：名册里今天在**构造点**产出非法段（原始键过不了形门）的构造条数。"""
    return sum(
        1
        for row in CURRENTLY_DIRTY_AT_CONSTRUCTION
        if open_gate_would_skip(
            _row_key(row),
            namespace=str(row["namespace"]),
            family=str(row["gate_family"]),
        )
    )


def _count_dropped_at_exit() -> int:
    """现算：同一批输入**经过中央出口**之后仍会被键形判丢的条数（此刻应为 0）。"""
    return sum(
        1
        for row in CURRENTLY_DIRTY_AT_CONSTRUCTION
        if open_gate_would_skip(
            key_as_it_arrives_at_the_gate(_row_key(row)),
            namespace=str(row["namespace"]),
            family=str(row["gate_family"]),
        )
    )


def _all_construction_cases() -> list[dict[str, object]]:
    """两本名册摊平成同一形态：safe 族一行多例（`worst_cases`）、dirty 族一行一例。"""
    cases: list[dict[str, object]] = []
    for row in FAMILIES_SAFE_TODAY:
        shell = {k: v for k, v in row.items() if k != "worst_cases"}  # type: ignore[union-attr]
        worst_cases = row["worst_cases"]
        assert isinstance(worst_cases, list), f"{row['family']} 的 worst_cases 形态变了"
        for case_label, args in worst_cases:
            cases.append({**shell, "case_label": case_label, "args": args})
    cases.extend(dict(row) for row in CURRENTLY_DIRTY_AT_CONSTRUCTION)  # type: ignore[arg-type]
    return cases


def test_roster_content_is_derived_from_the_current_tree() -> None:
    """名册内容由现算派生：两本名册 = 全体用例按中央谓词划分的结果（成员资格不许手写）。

    为什么必须有这条（S184 降账的自证）：把某一行从「脏」名册里划掉，既能把
    `_count_dropped_at_exit` 凑成 0、又能把构造侧计数凑小——两头都「好看」，可账是抹出来的。
    本锁把成员资格交给谓词现算：判定为脏的行必须全在 dirty 册、判定为干净的必须全在
    safe 册，多一条少一条都红。于是「降账」只有一条路——真去修构造侧。
    """
    computed_dirty: set[str] = set()
    computed_clean: set[str] = set()
    for row in _all_construction_cases():
        identity = _row_identity(row)
        would_skip = open_gate_would_skip(
            _row_key(row),
            namespace=str(row["namespace"]),
            family=str(row["gate_family"]),
        )
        (computed_dirty if would_skip else computed_clean).add(identity)

    declared_dirty = {
        _row_identity(row) for row in CURRENTLY_DIRTY_AT_CONSTRUCTION
    }
    declared_safe = {_row_identity(row) for row in _all_construction_cases()} - declared_dirty
    assert computed_dirty == declared_dirty, (
        f"名册 dirty 侧与现算脱钩：现算={sorted(computed_dirty)} 名册={sorted(declared_dirty)}"
    )
    assert computed_clean == declared_safe, (
        f"名册 safe 侧与现算脱钩：现算={sorted(computed_clean)} 名册={sorted(declared_safe)}"
    )
    assert computed_clean and computed_dirty, (
        "两本名册有一本被掏空——本锁随即失去判别力，须先弄清是不是抹账"
    )


def test_ratchet_baseline_matches_probe_on_current_tree() -> None:
    """探针：两枚基线与现算**恒等**（任一侧脱钩即红）。

    钉的是"基线与此刻现算一致"——回填后若有人改 roster 让二者脱钩，此锁红。
    长期方向约束由「只准降」「只准保持 0」两条分别负责，本条只保证记账此刻自洽。
    """
    actual_dirty = _count_dirty_at_construction()
    assert actual_dirty == _DIRTY_AT_CONSTRUCTION_BASELINE, (
        f"回填探针：构造侧 actual={actual_dirty} ≠ baseline={_DIRTY_AT_CONSTRUCTION_BASELINE}"
    )
    actual_exit = _count_dropped_at_exit()
    assert actual_exit == _DROPPED_AT_EXIT_BASELINE, (
        f"回填探针：经出口 actual={actual_exit} ≠ baseline={_DROPPED_AT_EXIT_BASELINE}"
    )


# ------------------------------------------------------------------ 注毒自证
def test_poison_a_removing_ack_washing_breaks_legality() -> None:
    """注毒 A：把 ack 的**构造侧**洗段拿掉（反事实 `ack_key_unwashed`）后，同一枚脏
    session/origin 必从"合法"翻成"原始键过不了形门"——证明 #50 补的洗段有牙、
    `test_safe_families_keys_are_legal_and_not_skipped_by_gate[ack]` 不是空断言。

    S184 口径（别把这条读成"没它就开始静默丢"）：中央出口今天会把段级脏兜住，所以
    构造侧回退的**真实**后果是两件事，各有锁、都不是"回执消失"：
      · 绕过出口的直调点拿到的是脏串（`test_central_wash_scoping_leaves_bypass_points_dirty`）；
      · 同一身份在出口前后两种键形，幂等桶要靠出口改写才对齐（下面 idempotence 那条）。
    """
    dirty_session = "chan nel:1"  # 带空格 + 冒号：裸拼会毁段
    dirty_origin = "a:b"
    digest = "deadbeef"
    washed = ack_key(dirty_session, dirty_origin, digest)
    unwashed = ack_key_unwashed(dirty_session, dirty_origin, digest)
    # 现役（构造侧洗段）：全段合法、开闸不 skip
    assert first_illegal_segment(washed) is None, washed
    assert not open_gate_would_skip(
        washed, namespace=ACK_DEDUPE_NAMESPACE, family="once"
    )
    # 去构造侧洗段（反事实）：必现非法段、原始键过不了形门
    assert first_illegal_segment(unwashed) is not None, unwashed
    assert open_gate_would_skip(
        unwashed, namespace=ACK_DEDUPE_NAMESPACE, family="once"
    ), unwashed


def test_central_wash_is_idempotent_so_construction_washing_coexists_with_the_exit() -> None:
    """出口洗段幂等 ⇒ 构造侧先洗、出口再洗 = 同一枚键（两本账各自降，不互相顶替）。

    没有这条，「族里自己加洗段」与「只靠出口」看起来等价；实际一旦两侧不等，
    同一次投递就会因走的代码路径不同写出两条队列行＝重发。
    """
    for raw in (
        "digest_push:11 08838060:2026-09-14",
        "digest_push:湘潭群:2026-09-14",
        "digest_push:1108838060::2026-09-14",
        "emg:qq::target",
        "ack:chat:chan nel:1:deadbeef",
        "reminder:7c1f2a9b",  # 已经干净的键必须逐字节不变（现役各族行为零变化的根据）
    ):
        once = key_as_it_arrives_at_the_gate(raw)
        twice = key_as_it_arrives_at_the_gate(once)
        assert once == twice, f"洗段不幂等：{once!r} → {twice!r}"
        assert first_illegal_segment(once) is None, once


def test_central_wash_scoping_leaves_bypass_points_dirty() -> None:
    """出口的保证只覆盖走它的那一路：把**原始**键直接送队列，脏段照旧进库。

    这是构造侧名册不许抹零的第二条腿（第一条是洗段非单射）。本件不启进程，
    判据落在「同一枚键的两种形态」上：原始形态过不了形门、出口形态过得了，
    两者不等 ⇒ 谁绕开出口，谁就把过不了形的那一枚交了下去。
    """
    raw = "digest_push:11 08838060:2026-09-14"
    arrived = key_as_it_arrives_at_the_gate(raw)
    assert raw != arrived, (
        "出口对现役脏输入已不再改写任何东西——本锁与名册都要重新核，别默认安全"
    )
    assert open_gate_would_skip(raw, namespace="digest_push", family="daily"), raw
    assert not open_gate_would_skip(arrived, namespace="digest_push", family="daily")
    # 旁路面（不经出口）今天仍在生产里存在：由
    # `tests/test_outbound_gate_opening_preconditions.py::test_wash_has_exactly_one_production_call_site`
    # 按 AST 现算现役直调点数，本席不在此手写枚数。


def test_poison_b_delimiter_as_intra_segment_char_is_caught() -> None:
    """注毒 B：把分隔符 `:` 当段内字符（尾随冒号 → 空段；中文 → 非集字符）。
    `is_legal_segment` 必须逐条判 False——证明判据真在拦这两类，而非"恰好没测到"。
    这也是 digest_push 构造侧今天仍脏的两条具体成因（见
    `CURRENTLY_DIRTY_AT_CONSTRUCTION`，曾用名 `CURRENTLY_DROPPING`）。
    """
    assert is_legal_segment("1108838060") is True
    assert is_legal_segment("") is False, "空段（尾随冒号产物）必须非法"
    assert is_legal_segment("1108838060:") is False, "含分隔符的原文必须非法"
    assert is_legal_segment("湘潭群") is False, "非 ASCII 段必须非法"
    assert is_legal_segment("9" * 121) is False, "超 120 长段必须非法"
    assert is_legal_segment("*") is False, "`*` 通配不是合法段，绝不得漏进键"


def test_ack_family_real_request_builder_key_is_legal() -> None:
    """ack 族用**真身构造口** `build_progress_ack_request` 端到端验（非镜像）：
    脏 session（带空格 + 冒号）投出来的真实 dedupe_key 逐段合法、开闸不 skip。
    与镜像锁互补——镜像钉拼键式，本条钉"生产真拼出来的那一枚键"。
    """
    from types import SimpleNamespace

    message = SimpleNamespace(
        group_id="1108838060",
        sender_id="3865067623",
        session_id="chan nel:1",  # 空格 + 冒号：裸拼必毁段
        message_id="msg:42",  # 带分隔符的 origin
        request_id="req-1",
        session_type="group",
        adapter="onebot",
        bot_id="3958874605",
    )
    request = build_progress_ack_request(message, "这条我要想一想，答得准一点。")
    key = request.dedupe_key
    assert first_illegal_segment(key) is None, f"真身 ack 键含非法段：{key!r}"
    assert not open_gate_would_skip(
        key, namespace=ACK_DEDUPE_NAMESPACE, family="once"
    ), f"真身 ack 键开闸会 skip：{key!r}"

