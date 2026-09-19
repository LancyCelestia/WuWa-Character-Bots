"""紧急信息域内核回归（B1R3 席：契约/定级/去重键/审核门/存储，全离线）。

零网络、零 NoneBot、零 LLM：SQLite 一律写 `tmp_path`（台账 #1 卫生 + conftest
源码树 `data/` 守卫）。每条用例都带「为什么会失败」的反证性，见 report §4。

坐标口径（被钉死的裁定）：
- D-3 单一等级枚举 + 颜色文案：`domains/weather/capabilities/weather.py:112`
  `_ALARM_COLOR_RANK`（AST 收编锁，见
  `test_level_color_labels_absorb_weather_alarm_vocabulary`）。
- D-2 仅 P0/P1 紧急面 + 过期不得冒充紧急：`contracts.is_urgent_level` /
  `service/grading.py::grade`。
- D-6 定级=纯规则（无网络/无 LLM/时钟注入）：AST 纯净锁
  `test_grading_is_a_pure_rule_function` + `test_domain_never_imports_llm_or_network`。
- D-8 入库即 pending、过审才定级与投递：`service/review.py::ReviewGate`
  （形态抄 `domains/chat_reply/character/quirks.py:202-300`）。
- D-1 无源诚实不接：`contracts.build_emergency_item` 返回 None、
  `dedupe.build_emergency_dedupe_key` 抛 ValueError、`level=None` 不冒充已定级。
- 去重键规范 `emg:{channel}:{item_id}:{target_id}[:{date_key}]`：
  `specs/B4-outbound-gate-and-delivery-verification.md` §1.3-3 +
  `reports/E5-report.md` §4.3。
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.core.contracts.runtime import RiskLevel
from plugins.bot_unified_runtime.domains.emergency_info import contracts
from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    LEVEL_COLOR_LABEL,
    URGENT_LEVELS,
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
    build_emergency_item,
    can_transition,
    highest_level,
    is_urgent_level,
    level_from_color_label,
    to_risk_level,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    EMERGENCY_DEDUPE_PREFIX,
    build_emergency_dedupe_key,
    date_key_of,
    is_emergency_dedupe_key,
    is_within_validity,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.grading import (
    FALLBACK_LEVEL,
    GradingRule,
    grade,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.review import (
    ReviewGate,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.store import (
    DEFAULT_DB_PATH,
    EmergencyStore,
    build_emergency_store,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = (
    REPO_ROOT / "plugins" / "bot_unified_runtime" / "domains" / "emergency_info"
)
WEATHER_CAPABILITY = (
    REPO_ROOT / "plugins" / "bot_unified_runtime" / "domains" / "weather"
    / "capabilities" / "weather.py"
)

_NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _payload(**overrides: Any) -> dict[str, Any]:
    """一条「什么都有」的最小合法条目 payload；用例只覆盖自己要验的字段。"""
    data: dict[str, Any] = {
        "item_id": "emg-1",
        "source_id": "nmc",
        "source_kind": "nmc_alarm",
        "external_id": "alarm-001",
        "title": "某市气象台发布暴雨橙色预警信号",
        "body": "预计 6 小时内降雨量达 100 毫米以上。",
        "url": "",
        "color_label": "橙色",
        "occurred_at": _NOW,
        "fetched_at": _NOW,
        "expires_at": _NOW + timedelta(hours=6),
        "credibility": 0.9,
    }
    data.update(overrides)
    return data


def _item(**overrides: Any) -> EmergencyItem:
    built = build_emergency_item(_payload(**overrides))
    assert built is not None, "测试夹具自身不合法，用例结论无意义"
    return built


def _neutral(**overrides: Any) -> EmergencyItem:
    """一条「除被测字段外什么都不命中」的条目：定级用例只留自己要验的信号。"""
    data: dict[str, Any] = {"title": "某区政务信息更新", "body": "详见门户公告。", "color_label": ""}
    data.update(overrides)
    return _item(**data)


class _FakeStore:
    """内存假存储：只实现 ReviewGate 依赖的最小面（ReviewStore 协议）。"""

    def __init__(self) -> None:
        self.rows: dict[str, EmergencyItem] = {}

    def upsert_item(self, item: EmergencyItem) -> bool:
        if item.item_id in self.rows:
            return False
        self.rows[item.item_id] = item
        return True

    def get(self, item_id: str) -> EmergencyItem | None:
        return self.rows.get(str(item_id or "").strip())

    def list_by_status(
        self, status: EmergencyStatus, *, limit: int = 50
    ) -> list[EmergencyItem]:
        rows = [row for row in self.rows.values() if row.status is status]
        return rows[: int(limit)]

    def apply_review(
        self,
        item_id: str,
        *,
        target: EmergencyStatus,
        reviewer_id: str,
        at: datetime,
    ) -> bool:
        row = self.rows.get(item_id)
        if row is None or row.status is not EmergencyStatus.PENDING:
            return False
        self.rows[item_id] = row.model_copy(
            update={"status": target, "reviewed_by": reviewer_id, "reviewed_at": at}
        )
        return True


def _gate(**kwargs: Any) -> tuple[ReviewGate, _FakeStore]:
    store = _FakeStore()
    return ReviewGate(store, **kwargs), store


# ---------------------------------------------------------------- §A 契约与等级


def test_level_enum_is_the_single_four_member_scale() -> None:
    """D-3：等级只有 P0/P1/P2/P3 四枚，序位红=4…蓝=1。"""
    assert [level.value for level in EmergencyLevel] == ["P0", "P1", "P2", "P3"]
    assert [level.rank for level in EmergencyLevel] == [4, 3, 2, 1]
    # 单一枚举：模块里不得再存在第二个等级词表（severity 一名属公共告警面）。
    second_scale = [
        name
        for name in vars(contracts)
        if name.endswith(("Severity", "SeverityLevel")) and isinstance(
            getattr(contracts, name), type
        )
    ]
    assert second_scale == []


def test_level_color_labels_absorb_weather_alarm_vocabulary() -> None:
    """收编锁：颜色词与序位必须与气象预警既有 `_ALARM_COLOR_RANK` 同表同序。

    不 import weather 能力模块（那会把取数面拖进纯数据层），改用 AST 直读常量；
    任何人改其中一侧，本用例即红。
    """
    tree = ast.parse(WEATHER_CAPABILITY.read_text(encoding="utf-8"))
    weather_rank: dict[str, int] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_ALARM_COLOR_RANK"
            for target in node.targets
        ):
            weather_rank = ast.literal_eval(node.value)
    assert weather_rank is not None, "weather 侧 _ALARM_COLOR_RANK 已被搬走，需同步本锁"

    mine = {level.color_label: level.rank for level in EmergencyLevel}
    assert mine == weather_rank
    assert {label for label in weather_rank} == set(LEVEL_COLOR_LABEL.values())


@pytest.mark.parametrize(
    ("level", "urgent"),
    [
        (EmergencyLevel.P0, True),
        (EmergencyLevel.P1, True),
        (EmergencyLevel.P2, False),
        (EmergencyLevel.P3, False),
    ],
)
def test_only_p0_p1_are_urgent(level: EmergencyLevel, urgent: bool) -> None:
    """D-2：仅 P0/P1 穿安静时间；紧急集合与判定口必须同源。"""
    assert is_urgent_level(level) is urgent
    assert URGENT_LEVELS == {EmergencyLevel.P0, EmergencyLevel.P1}


def test_to_risk_level_maps_onto_core_enum_without_second_scale() -> None:
    """跨面只经单点映射：目标类型必须是 core 契约的 RiskLevel（不造第二套）。"""
    mapping = {level: to_risk_level(level) for level in EmergencyLevel}
    assert mapping == {
        EmergencyLevel.P0: RiskLevel.CRITICAL,
        EmergencyLevel.P1: RiskLevel.HIGH,
        EmergencyLevel.P2: RiskLevel.MEDIUM,
        EmergencyLevel.P3: RiskLevel.LOW,
    }
    assert all(isinstance(value, RiskLevel) for value in mapping.values())


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("红色", EmergencyLevel.P0),
        ("橙色", EmergencyLevel.P1),
        ("黄色", EmergencyLevel.P2),
        ("蓝色", EmergencyLevel.P3),
        ("紫色", None),
        ("", None),
        ("  ", None),
    ],
)
def test_level_from_color_label_never_guesses(
    label: str, expected: EmergencyLevel | None
) -> None:
    """D-1：不认识的颜色不映射、不上抬，一律 None。"""
    assert level_from_color_label(label) is expected


def test_highest_level_picks_max_rank_and_rejects_empty() -> None:
    assert highest_level([EmergencyLevel.P3, EmergencyLevel.P1, EmergencyLevel.P2]) is (
        EmergencyLevel.P1
    )
    with pytest.raises(ValueError):
        highest_level([])


def test_item_requires_non_blank_source_fields() -> None:
    """D-1：缺必需字段的 payload 一律 None（无源诚实不接），绝不填假值。"""
    for missing in ("item_id", "source_id", "external_id", "title", "occurred_at"):
        payload = _payload()
        payload[missing] = "   " if missing != "occurred_at" else None
        assert build_emergency_item(payload) is None, missing


def test_item_rejects_unknown_keys_and_out_of_range_credibility() -> None:
    """extra=forbid（StrictBaseModel）+ 可信度区间：脏字段/越界值都不成立。"""
    assert build_emergency_item(_payload(severity="P0")) is None
    assert build_emergency_item(_payload(credibility=1.5)) is None
    assert build_emergency_item(_payload(credibility=-0.1)) is None
    assert build_emergency_item("not-a-mapping") is None  # type: ignore[arg-type]


def test_item_rejects_contradictory_validity_window() -> None:
    """源侧给了「有效期早于发生时间」⇒ 整条不成立（不猜、不洗数据）。"""
    assert build_emergency_item(
        _payload(expires_at=_NOW - timedelta(hours=1))
    ) is None


def test_naive_datetimes_are_normalised_to_utc() -> None:
    """时区口径写死：naive 按 UTC 解释（防提醒族那种 UTC 混用老坑）。"""
    naive = datetime(2026, 9, 19, 12, 0)  # noqa: DTZ001 - 本用例就是要造一个 naive 输入验归一。
    item = _item(occurred_at=naive, fetched_at=naive, expires_at=None)
    assert item.occurred_at.tzinfo is not None
    assert item.occurred_at.utcoffset() == timedelta(0)
    assert item.expires_at is None


def test_ungraded_item_claims_nothing() -> None:
    """未定级：color_text 空、is_urgent False——不拿缺省档冒充「已判为最低」。"""
    item = _item()
    assert item.level is None
    assert item.color_text == ""
    assert item.is_urgent is False
    graded = item.model_copy(update={"level": EmergencyLevel.P3})
    assert graded.color_text == "蓝色"
    assert graded.is_urgent is False


def test_status_default_is_pending_and_transitions_are_one_way() -> None:
    """D-8：缺省态 pending；只允许 pending→approved/rejected，终态不可回退。"""
    assert _item().status is EmergencyStatus.PENDING
    assert can_transition(EmergencyStatus.PENDING, EmergencyStatus.APPROVED)
    assert can_transition(EmergencyStatus.PENDING, EmergencyStatus.REJECTED)
    assert not can_transition(EmergencyStatus.APPROVED, EmergencyStatus.PENDING)
    assert not can_transition(EmergencyStatus.REJECTED, EmergencyStatus.APPROVED)
    assert not can_transition(EmergencyStatus.PENDING, EmergencyStatus.PENDING)


# ---------------------------------------------------------------- §B 规则定级


def _module_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_grading_is_a_pure_rule_function() -> None:
    """D-6 反证锁：定级模块只许 stdlib + 本域契约，且绝不读墙钟。

    一旦有人把 `datetime.now()`（不可测）或 httpx/llm（越层）塞进规则层即红。
    """
    path = DOMAIN_DIR / "service" / "grading.py"
    allowed_prefixes = (
        "__future__",
        "collections.abc",
        "dataclasses",
        "datetime",
        "typing",
        "plugins.bot_unified_runtime.domains.emergency_info.contracts",
    )
    offenders = [
        module
        for module in _module_imports(path)
        if not module.startswith(allowed_prefixes)
    ]
    assert offenders == []

    tree = ast.parse(path.read_text(encoding="utf-8"))
    wall_clock = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"now", "today", "utcnow", "time"}
    ]
    assert wall_clock == []


def test_grade_uses_source_color_label() -> None:
    assert grade(_neutral(color_label="红色"), now=_NOW) is EmergencyLevel.P0
    assert grade(_neutral(color_label="蓝色"), now=_NOW) is EmergencyLevel.P3


def test_grade_reads_color_words_out_of_title() -> None:
    """源侧没单独给颜色字段、颜色词长在标题里时同样命中（气象预警的真实形态）。"""
    item = _item(
        title="某市气象台发布大雾橙色预警信号",
        body="",
        color_label="",
    )
    assert grade(item, now=_NOW) is EmergencyLevel.P1


def test_grade_takes_highest_keyword_hit() -> None:
    item = _item(title="暴雨橙色预警", body="已发生山体滑坡，请撤离", color_label="")
    assert grade(item, now=_NOW) is EmergencyLevel.P0


def test_grade_without_any_signal_falls_back_to_lowest() -> None:
    item = _item(title="某区政务信息更新", body="详见门户公告", color_label="")
    assert grade(item, now=_NOW) is FALLBACK_LEVEL
    assert FALLBACK_LEVEL is EmergencyLevel.P3


def test_expired_item_cannot_claim_urgent() -> None:
    """过期条目压到最低档：时效窗被绕过时也不得穿安静时间（D-2 兜底）。"""
    stale = _item(color_label="红色", expires_at=_NOW + timedelta(minutes=5))
    assert grade(stale, now=_NOW) is EmergencyLevel.P0  # 仍在有效期内
    assert grade(stale, now=_NOW + timedelta(hours=2)) is EmergencyLevel.P3
    assert (
        is_urgent_level(grade(stale, now=_NOW + timedelta(hours=2))) is False
    )


def test_grade_is_deterministic_and_clock_injected() -> None:
    """同输入同输出；未过期区间内换 `now` 不改结论（时间只经参数进入）。"""
    item = _item()
    first = grade(item, now=_NOW)
    second = grade(item, now=_NOW)
    assert first == second
    assert grade(item, now=_NOW + timedelta(minutes=1)) == first
    assert isinstance(first, EmergencyLevel)


def test_grade_rules_are_injectable() -> None:
    """规则表是数据：管理侧可换词表而不动代码（新词「特急」→P0）。"""
    custom = (GradingRule(level=EmergencyLevel.P0, keywords=("特急",), note="测试表"),)
    item = _item(title="特急通行提示", body="", color_label="")
    assert grade(item, now=_NOW, rules=custom) is EmergencyLevel.P0
    # 不注入时该条目什么也不命中 ⇒ 最低档（证明 rules 参数真的参与了判定）。
    assert grade(item, now=_NOW) is FALLBACK_LEVEL


# ---------------------------------------------------------------- §C 去重键与时效


def test_dedupe_key_matches_b4_spec_shape() -> None:
    """键规范原文抄 B4 规格 §1.3-3：`emg:{channel}:{item_id}:{target_id}[:{date_key}]`。"""
    plain = build_emergency_dedupe_key("qq", "alarm-001", "1108838060")
    assert plain == "emg:qq:alarm-001:1108838060"
    dated = build_emergency_dedupe_key("qq", "alarm-001", "1108838060", "2026-09-19")
    assert dated == "emg:qq:alarm-001:1108838060:2026-09-19"
    assert plain.count(":") == 3 and dated.count(":") == 4
    assert EMERGENCY_DEDUPE_PREFIX == "emg"
    # 段内不得出现分隔符：`private:3865067623` 这类目标写法必须先消毒再进键。
    with pytest.raises(ValueError):
        build_emergency_dedupe_key("qq", "alarm-001", "private:3865067623")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"channel": "", "item_id": "a", "target_id": "b"},
        {"channel": "qq", "item_id": "  ", "target_id": "b"},
        {"channel": "qq", "item_id": "a", "target_id": ""},
        {"channel": "qq:x", "item_id": "a", "target_id": "b"},
        {"channel": "qq", "item_id": "冒号:非法", "target_id": "b"},
        {"channel": "qq", "item_id": "a", "target_id": "带 空格"},
        {"channel": "qq", "item_id": "a", "target_id": "b", "date_key": "2026-9-1"},
        {"channel": "qq", "item_id": "a", "target_id": "b", "date_key": ""},
    ],
)
def test_dedupe_key_rejects_illegal_parts(kwargs: dict[str, str]) -> None:
    """D-1：拼不出合法键就抛 ValueError，绝不返回一个「看起来能用」的假键。"""
    with pytest.raises(ValueError):
        build_emergency_dedupe_key(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("key", "require_date", "expected"),
    [
        ("emg:qq:item-1:target-1", False, True),
        ("emg:qq:item-1:target-1", True, False),
        ("emg:qq:item-1:target-1:2026-09-19", True, True),
        ("emg:qq:item-1:target-1:2026-9-19", False, False),
        ("emg:qq:item-1", False, False),
        ("emg:qq:item-1:target-1:2026-09-19:extra", False, False),
        ("emergency:qq:item-1:target-1", False, False),
        ("campus_fwd:12345", False, False),
        ("daily_assist:morning:3865067623:2026-09-19", False, False),
        ("digest_push:1108838060:2026-09-19", False, False),
        ("", False, False),
        ("  ", False, False),
    ],
)
def test_dedupe_key_shape_check(key: str, require_date: bool, expected: bool) -> None:
    """中央闸（B4a 席）可直接 import 本判定口做 `reason="dedupe_key_shape"`。"""
    assert is_emergency_dedupe_key(key, require_date_key=require_date) is expected


def test_dedupe_key_roundtrip_passes_shape_check() -> None:
    plain = build_emergency_dedupe_key("telegram", "gov-9", "chat.123")
    dated = build_emergency_dedupe_key("telegram", "gov-9", "chat.123", "2026-09-19")
    assert is_emergency_dedupe_key(plain) is True
    assert is_emergency_dedupe_key(plain, require_date_key=True) is False
    assert is_emergency_dedupe_key(dated, require_date_key=True) is True


# ---- 往返自洽锁（D1-FIX 任务一：原缺陷=校验用 strip 后的值、拼键却用原始入参）----


@pytest.mark.parametrize(
    ("channel", "item_id", "target_id", "date_key"),
    [
        (" nmc ", "alarm-001", "1108838060", None),
        ("nmc", " alarm-001 ", "1108838060", None),
        ("nmc", "alarm-001", " 1108838060", None),
        ("nmc", "alarm-001", "1108838060 ", None),
        ("\tnmc\n", "alarm-001", "1108838060", None),
        (" nmc ", " alarm-001 ", " 1108838060 ", " 2026-09-19 "),
        # 真实可达形态：配置里的 "3865067623, 1722380002" 按逗号切开不 strip。
        ("qq", "emg-1", " 3865067623", None),
    ],
)
def test_dedupe_key_normalises_parts_before_joining(
    channel: str, item_id: str, target_id: str, date_key: str | None
) -> None:
    """过校验的值必须就是进键的值：带空白的入参只能产出「归一后的合法键」。

    反证性（这条锁要咬的原缺陷）：`build_emergency_dedupe_key` 拿 `strip()` 后的值
    过 `_SEGMENT_RE`，却用**原始入参**拼键 ⇒ 带空白的段过了校验、进了键，而同模块的
    `is_emergency_dedupe_key`（段字符集不含空白）判它 False。按 `dedupe.py` 模块注释
    的口径，键规范核验正是拿该谓词做的 ⇒ 结论 `skip, reason="dedupe_key_shape"`，
    紧急信息**静默不发**（漏报方向，无异常无告警）。
    """
    key = build_emergency_dedupe_key(channel, item_id, target_id, date_key)
    # ① 往返成立：自己造的键必须过自己的谓词。
    assert is_emergency_dedupe_key(key) is True
    if date_key is not None:
        assert is_emergency_dedupe_key(key, require_date_key=True) is True
    # ② 与去空白入参产出同一条键：队列 `ON CONFLICT(dedupe_key)`（queue.py:444-476）
    #    是幂等唯一执行点，两个形态各存一行＝同一推送重发。
    assert key == build_emergency_dedupe_key(
        channel.strip(),
        item_id.strip(),
        target_id.strip(),
        None if date_key is None else date_key.strip(),
    )
    # ③ 键体不残留任何空白（段字符集与 B4 规格 §1.3-3 同口径）。
    assert not re.search(r"\s", key), key


def test_dedupe_key_normalised_parts_take_the_canonical_form() -> None:
    """归一后拼出的就是规范键本身，不是「保留原样再加一段」的第三种写法。"""
    assert (
        build_emergency_dedupe_key(" nmc ", " alarm-001 ", " 1108838060 ")
        == "emg:nmc:alarm-001:1108838060"
    )
    assert (
        build_emergency_dedupe_key(" qq ", "emg-1", "1108838060", " 2026-09-19 ")
        == "emg:qq:emg-1:1108838060:2026-09-19"
    )


@pytest.mark.parametrize(
    ("channel", "item_id", "target_id", "date_key"),
    [
        ("  ", "a", "b", None),  # 纯空白=空段，不得被归一"洗白"成合法
        ("qq", "\t\t", "b", None),
        ("qq", "a", "   ", None),
        ("qq", " alarm 001 ", "b", None),  # strip 两端后仍含内部空白 ⇒ 依旧非法
        ("q q", "a", "b", None),
        ("qq:x", "a", "b", None),  # 分隔符进段 ⇒ 段数歧义
        ("qq", "冒号:非法", "b", None),
        ("qq", "a\nb", "b", None),  # 换行属空白
        ("qq", "a", "b\x00", None),  # NUL：队列/日志面的经典注入位
        ("qq", "a", "目标 id", None),
        ("qq", "a", "b", " 2026-1-9 "),  # 日期段形态不合规，strip 也救不回来
    ],
)
def test_normalising_does_not_weaken_the_illegal_part_gate(
    channel: str, item_id: str, target_id: str, date_key: str | None
) -> None:
    """D-1 门不得被弱化：拼不出合法键就抛 ValueError，绝不返回「看着能用」的假键。

    与 `test_dedupe_key_rejects_illegal_parts` 同族，专防「归一化顺手改成
    过滤/替换非法字符」这类越修越松的走偏（把 skip 漏报换成静默错键重发）。
    """
    with pytest.raises(ValueError):
        build_emergency_dedupe_key(channel, item_id, target_id, date_key)


@pytest.mark.parametrize(
    ("overrides", "kwargs", "expected"),
    [
        # 发生时间在未来：时间不可信 ⇒ fail-closed 不投。
        ({"occurred_at": _NOW + timedelta(hours=1), "expires_at": None}, {}, False),
        # 已到/已过失效时刻：False（含恰好等于 now 的边界）。
        ({"expires_at": _NOW}, {"now": _NOW}, False),
        ({"expires_at": _NOW + timedelta(seconds=1)}, {"now": _NOW}, True),
        # 源未给有效期：不因「信息缺失」误杀，也不替它编一个到期时间。
        ({"expires_at": None}, {}, True),
        # 年龄超窗 False；恰好等于窗长 True（判定是严格大于）。
        (
            {"occurred_at": _NOW - timedelta(hours=2), "expires_at": None},
            {"max_age": timedelta(hours=1)},
            False,
        ),
        (
            {"occurred_at": _NOW - timedelta(hours=1), "expires_at": None},
            {"max_age": timedelta(hours=1)},
            True,
        ),
    ],
)
def test_validity_window_matrix(
    overrides: dict[str, Any], kwargs: dict[str, Any], expected: bool
) -> None:
    item = _item(**overrides)
    assert is_within_validity(item, now=kwargs.pop("now", _NOW), **kwargs) is expected


def test_date_key_of_uses_local_calendar_day() -> None:
    """日期键=本地日历日（现役按日 dedupe 同族），跨日必换键。"""
    local_noon = datetime.now().astimezone().replace(hour=12, minute=0, second=0)
    today = date_key_of(local_noon)
    tomorrow = date_key_of(local_noon + timedelta(hours=14))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today)
    assert today == local_noon.date().isoformat()
    assert tomorrow != today


# ---------------------------------------------------------------- §D 审核门


def test_submit_forces_pending_and_strips_level_and_review_marks() -> None:
    """D-8 结构锁：报料方自带 approved+level 也被钉回 pending、等级清空。"""
    gate, store = _gate()
    smuggled = _item(
        item_id="emg-sneak",
    ).model_copy(
        update={
            "status": EmergencyStatus.APPROVED,
            "level": EmergencyLevel.P0,
            "reviewed_by": "reporter-himself",
            "reviewed_at": _NOW,
        }
    )
    stored = gate.submit(smuggled)
    assert stored.status is EmergencyStatus.PENDING
    assert stored.level is None
    assert stored.reviewed_by == "" and stored.reviewed_at is None
    assert store.rows["emg-sneak"].status is EmergencyStatus.PENDING


def test_pending_item_cannot_be_delivered_or_graded() -> None:
    gate, store = _gate()
    gate.submit(_item())
    pending = store.rows["emg-1"]
    assert ReviewGate.publishable(pending) is False
    assert ReviewGate.publishable_level(pending, now=_NOW) is None


def test_approve_is_closed_until_an_authorizer_is_injected() -> None:
    """缺省=功能关闭：未注入 authorizer 一律拒绝，且状态零变化。"""
    gate, store = _gate()
    gate.submit(_item())
    outcome = gate.approve("emg-1", reviewer_id="3865067623", at=_NOW)
    assert (outcome.ok, outcome.reason) == (False, "authorizer_not_configured")
    assert store.rows["emg-1"].status is EmergencyStatus.PENDING


def test_approve_rejects_unauthorized_and_blank_reviewer() -> None:
    gate, store = _gate(authorizer=lambda reviewer: reviewer == "3865067623")
    gate.submit(_item())
    denied = gate.approve("emg-1", reviewer_id="1722380002", at=_NOW)
    assert (denied.ok, denied.reason) == (False, "reviewer_not_authorized")
    blank = gate.approve("emg-1", reviewer_id="   ", at=_NOW)
    assert (blank.ok, blank.reason) == (False, "blank_reviewer")
    assert store.rows["emg-1"].status is EmergencyStatus.PENDING


def test_approve_then_item_becomes_publishable_with_level() -> None:
    gate, store = _gate(authorizer=lambda reviewer: True)
    gate.submit(_item())
    outcome = gate.approve("emg-1", reviewer_id="3865067623", at=_NOW)
    assert (outcome.ok, outcome.status) == (True, EmergencyStatus.APPROVED)
    approved = store.rows["emg-1"]
    assert approved.reviewed_by == "3865067623"
    assert ReviewGate.publishable(approved) is True
    level = ReviewGate.publishable_level(approved, now=_NOW)
    assert level is EmergencyLevel.P1  # 夹具是「橙色 + 暴雨」
    assert is_urgent_level(level) is True  # D-2：P1 属紧急面，可穿安静时间
    # 过了有效期再问一次：仍是「可投递」但等级被压到最低档，紧急面自动关闭。
    stale_level = ReviewGate.publishable_level(approved, now=_NOW + timedelta(days=1))
    assert stale_level is EmergencyLevel.P3
    assert is_urgent_level(stale_level) is False


def test_double_approve_and_approve_after_reject_are_refused() -> None:
    """只能从 pending 出裁一次（并发第二人拿到 not_pending_anymore/illegal）。"""
    gate, store = _gate(authorizer=lambda reviewer: True)
    gate.submit(_item(item_id="emg-a"))
    assert gate.approve("emg-a", reviewer_id="admin", at=_NOW).ok is True
    again = gate.approve("emg-a", reviewer_id="admin", at=_NOW)
    assert (again.ok, again.reason) == (False, "illegal_transition")

    gate.submit(_item(item_id="emg-b"))
    assert gate.reject("emg-b", reviewer_id="admin", at=_NOW, reason="重复报料").ok
    revived = gate.approve("emg-b", reviewer_id="admin", at=_NOW)
    assert (revived.ok, revived.reason) == (False, "illegal_transition")
    assert store.rows["emg-b"].status is EmergencyStatus.REJECTED


def test_rejected_item_never_participates_in_delivery() -> None:
    gate, store = _gate(authorizer=lambda reviewer: True)
    gate.submit(_item())
    gate.reject("emg-1", reviewer_id="admin", at=_NOW)
    rejected = store.rows["emg-1"]
    assert ReviewGate.publishable(rejected) is False
    assert ReviewGate.publishable_level(rejected, now=_NOW) is None


def test_approve_unknown_item_and_blank_id_are_refused() -> None:
    gate, _store = _gate(authorizer=lambda reviewer: True)
    missing = gate.approve("emg-nope", reviewer_id="admin", at=_NOW)
    assert (missing.ok, missing.reason) == (False, "unknown_item")
    blank = gate.approve("  ", reviewer_id="admin", at=_NOW)
    assert (blank.ok, blank.reason) == (False, "blank_item_id")


def test_pending_items_lists_only_the_review_queue() -> None:
    gate, _store = _gate(authorizer=lambda reviewer: True)
    gate.submit(_item(item_id="emg-1"))
    gate.submit(_item(item_id="emg-2", external_id="alarm-002"))
    gate.approve("emg-1", reviewer_id="admin", at=_NOW)
    assert [item.item_id for item in gate.pending_items()] == ["emg-2"]


# ---------------------------------------------------------------- §E SQLite 存储


def _store(tmp_path: Path) -> EmergencyStore:
    return EmergencyStore(str(tmp_path / "emergency.sqlite3"))


def test_store_roundtrip_preserves_contract(tmp_path: Path) -> None:
    """写库→读回必须逐字段等值（含 aware 时间与「未定级」的 None）。"""
    store = _store(tmp_path)
    item = _item()
    assert store.upsert_item(item) is True
    assert store.get("emg-1") == item
    assert store.get("emg-1").level is None
    assert store.get("nope") is None


def test_store_is_idempotent_by_source_and_external_id(tmp_path: Path) -> None:
    """重跑采集：同 (source_id, external_id) 换 item_id 也只落一条（E5 §4.3）。"""
    store = _store(tmp_path)
    assert store.upsert_item(_item(item_id="emg-first")) is True
    assert store.upsert_item(_item(item_id="emg-second")) is False
    assert [item.item_id for item in store.list_by_status(EmergencyStatus.PENDING)] == [
        "emg-first"
    ]
    # 同 item_id 重复插入同样拒（PRIMARY KEY 守卫）。
    assert store.upsert_item(_item(item_id="emg-first")) is False


def test_store_survives_reopen(tmp_path: Path) -> None:
    """重启即新连接：库内容必须持久（铁律：运行数据在 Runtime 根，不在内存）。"""
    path = tmp_path / "emergency.sqlite3"
    EmergencyStore(str(path)).upsert_item(_item())
    reopened = EmergencyStore(str(path))
    assert reopened.get("emg-1") == _item()


def test_store_apply_review_only_touches_pending(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_item(_item())
    assert store.get("emg-1").status is EmergencyStatus.PENDING
    assert (
        store.apply_review(
            "emg-1",
            target=EmergencyStatus.PENDING,
            reviewer_id="admin",
            at=_NOW,
        )
        is False
    )
    assert (
        store.apply_review(
            "emg-1", target=EmergencyStatus.APPROVED, reviewer_id="", at=_NOW
        )
        is False
    )
    assert (
        store.apply_review(
            "emg-1",
            target=EmergencyStatus.APPROVED,
            reviewer_id="admin",
            at=_NOW,
        )
        is True
    )
    approved = store.get("emg-1")
    assert approved.status is EmergencyStatus.APPROVED
    assert approved.reviewed_by == "admin"
    assert approved.reviewed_at == _NOW
    # 终态之后不得再被裁决（SQL 守卫与 can_transition 同源）。
    assert (
        store.apply_review(
            "emg-1", target=EmergencyStatus.REJECTED, reviewer_id="admin", at=_NOW
        )
        is False
    )


def test_store_set_level_requires_approved(tmp_path: Path) -> None:
    """D-8 的存储侧锁：没过审的条目连等级都写不进去。"""
    store = _store(tmp_path)
    store.upsert_item(_item())
    assert store.set_level("emg-1", level=EmergencyLevel.P0) is False
    assert store.get("emg-1").level is None
    store.apply_review(
        "emg-1", target=EmergencyStatus.APPROVED, reviewer_id="admin", at=_NOW
    )
    assert store.set_level("emg-1", level=EmergencyLevel.P0) is True
    stored = store.get("emg-1")
    assert stored.level is EmergencyLevel.P0
    assert stored.is_urgent is True


def test_store_lists_by_status_and_bounds_growth(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for index in range(4):
        store.upsert_item(
            _item(
                item_id=f"emg-{index}",
                external_id=f"alarm-{index}",
                occurred_at=_NOW - timedelta(days=index * 40),
            )
        )
    assert len(store.list_by_status(EmergencyStatus.PENDING)) == 4
    assert len(store.list_by_status(EmergencyStatus.PENDING, limit=2)) == 2
    assert store.list_by_status(EmergencyStatus.PENDING, limit=0) == []
    assert store.prune(keep_days=90, now=_NOW) == 1  # 120 天前那条被裁
    assert len(store.list_by_status(EmergencyStatus.PENDING)) == 3


def test_build_store_default_path_goes_through_runtime_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """铁律 6：缺省路径是相对 `data/`，装配必须经 runtime_paths 重映射出源码树。"""
    assert DEFAULT_DB_PATH.startswith("data/")
    calls: list[str] = []

    def fake_runtime_path(value: Any) -> Path:
        calls.append(str(value))
        return tmp_path / "remapped" / "emergency_info.sqlite3"

    monkeypatch.setattr("scripts.runtime_paths.runtime_path", fake_runtime_path)
    store = build_emergency_store()
    assert calls == [DEFAULT_DB_PATH]
    assert str(store.db_path).startswith(str(tmp_path / "remapped"))
    assert store.upsert_item(_item()) is True  # 重映射后的目录能真建库

    explicit = build_emergency_store(tmp_path / "given.sqlite3")
    assert explicit.db_path == tmp_path / "given.sqlite3"
    assert calls == [DEFAULT_DB_PATH]  # 显式给路径时不再触碰重映射


def test_review_gate_end_to_end_on_sqlite(tmp_path: Path) -> None:
    """全链路（入库→过审→定级→出键→时效判定）在真 SQLite 上跑通。"""
    store = _store(tmp_path)
    gate = ReviewGate(store, authorizer=lambda reviewer: reviewer == "admin")
    submitted = gate.submit(_item())
    assert store.get(submitted.item_id).status is EmergencyStatus.PENDING
    assert gate.approve("emg-1", reviewer_id="admin", at=_NOW).ok is True
    approved = store.get("emg-1")
    level = ReviewGate.publishable_level(approved, now=_NOW)
    assert level is EmergencyLevel.P1
    assert store.set_level("emg-1", level=level) is True
    key = build_emergency_dedupe_key(
        "qq", "emg-1", "1108838060", date_key_of(_NOW)
    )
    assert is_emergency_dedupe_key(key, require_date_key=True) is True
    assert is_within_validity(store.get("emg-1"), now=_NOW) is True
    assert is_within_validity(store.get("emg-1"), now=_NOW + timedelta(days=1)) is False


# ---------------------------------------------------------------- §F 域边界锁


def _kernel_python_files() -> list[Path]:
    """B1R3 席交付的内核面（本席独占）；采集器/投递属其他席位，不在本锁口径内。"""
    kernel = [
        DOMAIN_DIR / "__init__.py",
        DOMAIN_DIR / "contracts.py",
        DOMAIN_DIR / "sources" / "store.py",
    ]
    kernel.extend(sorted((DOMAIN_DIR / "service").glob("*.py")))
    return [path for path in kernel if path.is_file()]


def test_kernel_never_imports_network_or_llm() -> None:
    """D-6/G5：本席内核（契约/定级/去重/审核/存储）零网络零 LLM 零框架依赖。

    一旦有人把取数或模型调用塞进规则层（而不是采集器席位自己的 `sources/`），
    本用例即红——这是「纯函数可离线测」这条裁定的结构护栏。
    """
    forbidden = (
        "httpx",
        "requests",
        "urllib",
        "socket",
        "nonebot",
        "llm",
        "model_router",
        "openai",
        "providers",
        "transport",
    )
    kernel_files = _kernel_python_files()
    assert len(kernel_files) >= 6, "内核面文件缺失，锁不得空转"
    offenders: list[str] = []
    for path in kernel_files:
        for module in _module_imports(path):
            if any(token in module for token in forbidden):
                offenders.append(f"{path.name}:{module}")
    assert offenders == []


def test_rule_layer_never_builds_a_second_llm_entry() -> None:
    """D-6/G5 定向锁：`service/`（判定层）与契约层永不含 LLM/模型路由入口。

    口径刻意只管「判定面」，不宣称全域零网络——采集器（`sources/` 其余文件）
    合法需要取数，且必须走既有中央 http 面（已由该席自证：
    `domains/link_parse/parsers/http_util` + `ssrf_guard`）。
    谁来把「让模型判等级」塞回规则层，本用例即红。
    """
    forbidden = (
        "llm",
        "model_router",
        "openai",
        "providers",
        "capabilities.chat",
        "character.providers",
    )
    scanned = [DOMAIN_DIR / "contracts.py"]
    scanned.extend(sorted((DOMAIN_DIR / "service").glob("*.py")))
    offenders: list[str] = []
    for path in scanned:
        for module in _module_imports(path):
            if any(token in module for token in forbidden):
                offenders.append(f"{path.name}:{module}")
    assert len(scanned) >= 4 and offenders == []


def test_domain_kernel_touches_no_config_module() -> None:
    """缺省行为=功能关闭由装配期注入决定：内核不 import config、不读 .env。"""
    offenders = [
        f"{path.name}:{module}"
        for path in sorted(DOMAIN_DIR.rglob("*.py"))
        for module in _module_imports(path)
        if module.endswith("config") or "bot_unified_runtime.config" in module
    ]
    assert offenders == []


def test_brief_mandated_modules_and_symbols_are_in_place() -> None:
    """骨架落地锁：简报点名的五件 + 各自关键符号都在，缺一即红。

    防「文件建了但内核是空的」——后续席位（B4a 投递闸/B8 注册）就是按这些
    公开口 import 的，名字漂了会在自己域里炸，本用例提前一步拦住。
    """
    required = {
        "contracts.py": ("EmergencyLevel", "EmergencyItem", "build_emergency_item"),
        "service/grading.py": ("grade", "GradingRule", "DEFAULT_GRADING_RULES"),
        "service/dedupe.py": (
            "build_emergency_dedupe_key",
            "is_emergency_dedupe_key",
            "is_within_validity",
            "date_key_of",
        ),
        "service/review.py": ("ReviewGate", "ReviewOutcome", "ReviewStore"),
        "sources/store.py": ("EmergencyStore", "build_emergency_store"),
    }
    for relative, symbols in required.items():
        path = DOMAIN_DIR / relative
        assert path.is_file(), f"缺文件 {relative}"
        source = path.read_text(encoding="utf-8")
        for symbol in symbols:
            assert f"{symbol}" in source, f"{relative} 缺公开符号 {symbol}"


# ------------------------------------------------ §G 接缝契约锁（规格 §8.1 锁 A–E）

"""本域唯一写路径（规格 §8.1「强制经过路径」）目前是**半空**的：内核四件已落地，
采集器与中央闸之间零接缝（`to_payload` / `build_emergency_send_request` /
`fanout_emergency_push` 全仓 0 命中）。旧局面是一条**文本锁**把「源件不 import 内核」
钉死，保护的恰恰是「接缝不存在」本身——真缝合时没有任何测试会因为绕过
`build_emergency_item` / `ReviewGate.submit` 而变红。

本节的处置（与 `tests/test_emergency_info_sources.py` §接缝锁配对）：
- **锁 A/B/E 现在就生效**（默认拒绝式：旁路一旦出现即红，且各自带「锚点」防空转）；
- **锁 C/D 的前提是尚未存在的代码**，按纪律写成 `xfail(strict=True)`，**不为此造实现**；
  落地即 XPASS 转红，删标记即转正（report §落地请求 已登记）。
"""

PLUGIN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
DOMAIN_REL = "domains/emergency_info"
GATE_MODULE_REL = "domains/transport/sender/outbound_gate.py"
REVIEW_FILE_REL = f"{DOMAIN_REL}/service/review.py"
STORE_FILE_REL = f"{DOMAIN_REL}/sources/store.py"
CONTRACTS_FILE_REL = f"{DOMAIN_REL}/contracts.py"
GATE_TEST_FILE = REPO_ROOT / "tests" / "test_outbound_gate.py"
NMC_ALARM_FILE = DOMAIN_DIR / "sources" / "nmc_alarm.py"
KEY_BUILDER = "build_emergency_dedupe_key"
GATE_T6_TEST = "test_submit_active_push_production_importers_are_allowlisted"

_MISSING = object()


def _production_python_files(root: Path) -> list[Path]:
    """生产面（`plugins/**`）全部 .py。**测试面刻意排除**：测试直连 store/谓词属正当，
    把它们算进「旁路计数」会让锁变成没人敢碰的石头。"""
    return sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and path.is_file()
    )


def _rel_to_plugin(path: Path) -> str:
    return path.relative_to(PLUGIN_ROOT).as_posix()


def _called_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _named_calls(root: Path, name: str) -> list[tuple[Path, int, ast.Call]]:
    """生产面里 `name(...)` / `x.name(...)` 的调用点（先按字节筛再 AST，635 文件实测 0.1s）。"""
    found: list[tuple[Path, int, ast.Call]] = []
    for path in _production_python_files(root):
        text = path.read_text(encoding="utf-8")
        if name not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and _called_name(node) == name:
                found.append((path, node.lineno, node))
    return found


def _domain_functions_calling(name: str) -> list[tuple[Path, ast.FunctionDef]]:
    """本域内「函数体里出现了 `name(...)` 调用」的函数（锁 D 按函数作用域判定同源）。"""
    hits: list[tuple[Path, ast.FunctionDef]] = []
    for path in _production_python_files(DOMAIN_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if any(
                isinstance(sub, ast.Call) and _called_name(sub) == name
                for sub in ast.walk(node)
            ):
                hits.append((path, node))
    return hits


def _module_constant(path: Path, name: str) -> Any:
    """AST 取模块级常量字面量（不 import 采集器：那会把取数面拖进本测试）。"""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return ast.literal_eval(node.value) if node.value is not None else _MISSING
    return _MISSING


def _find_domain_function(name: str) -> Any:
    """在本域生产面按名字找函数真身并 import；找不到抛 LookupError（供 xfail 锁用）。"""
    for path in _production_python_files(DOMAIN_DIR):
        if f"def {name}(" not in path.read_text(encoding="utf-8"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
            for node in tree.body
        ):
            continue
        module_name = path.relative_to(REPO_ROOT).as_posix()[: -len(".py")].replace("/", ".")
        return getattr(importlib.import_module(module_name), name)
    raise LookupError(f"{name} 在本域生产面不存在")


# ---- 锁 A｜唯一入库口 ----------------------------------------------------------


def test_only_the_review_gate_can_write_items_into_the_store() -> None:
    """锁 A：条目标库只能经 `ReviewGate.submit`（规格 §8.1 锁 A、裁定 D-8）。

    绕过的具体后果（规格 §8.1 表第 2 行）：报料方自带 `approved + P0` 直接
    `upsert_item` 入池就参与投递——`submit` 的「钉回 pending、清空
    level/reviewed_by/reviewed_at」被跳过；`store.set_level` 的 SQL 守卫还在，
    但状态已被绕过，**审核门只剩一半**。
    """
    sites = _named_calls(PLUGIN_ROOT, "upsert_item")
    sanctioned = [line for path, line, _call in sites if _rel_to_plugin(path) == REVIEW_FILE_REL]
    assert sanctioned, (
        f"{REVIEW_FILE_REL} 里已无 `upsert_item` 调用＝唯一入库口被搬走："
        "本锁不许空转，请与本域一起改口径，不要删锁"
    )
    allowed_files = {REVIEW_FILE_REL, STORE_FILE_REL}  # 定义处 + 审核门，别无分店
    offenders = [
        f"{_rel_to_plugin(path)}:{line}"
        for path, line, _call in sites
        if _rel_to_plugin(path) not in allowed_files
    ]
    assert offenders == [], f"绕过审核门直接落库的调用点：{offenders}"


# ---- 锁 B｜唯一触闸口 + 域内零直调队列 + 与闸侧白名单双向对齐 ------------------


def _gate_t6_allowed_roots() -> list[Path]:
    """从闸席的 T6 结构锁里提取**它自己的**允许前缀（双向对齐，不 import 它的私有名）。"""
    tree = ast.parse(GATE_TEST_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != GATE_T6_TEST:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and "allowed" in target.id.lower()
                for target in sub.targets
            ):
                continue
            roots: list[Path] = []
            for element in getattr(sub.value, "elts", []):
                for inner in getattr(element, "elts", [element]):
                    segments = [constant.value for constant in _descend_constants(inner)]
                    if segments:
                        roots.append(PLUGIN_ROOT.joinpath(*segments))
            return roots
    return []


def _descend_constants(node: ast.AST) -> list[ast.Constant]:
    """按源码顺序取出该表达式里的字符串常量（`PLUGIN_ROOT / "domains" / "transport"`）。"""
    out: list[ast.Constant] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            out.append(child)
        else:
            out.extend(_descend_constants(child))
    return out


def test_domain_reaches_the_queue_only_through_the_central_gate() -> None:
    """锁 B：主动投递只能经 `submit_active_push`，且必须过审核门（规格 §8.1 锁 B）。

    三段各有分工：
    ① 引用面白名单（transport 本体 + 本域）——现役 6 族今天根本不过闸，破的是闸规格
       §1.2「唯一插入点」，静默窗与每主体限流双双失效；
    ② **与闸席 T6 白名单双向对齐**（规格点名的防漂移条款）：两侧各写一份允许前缀，
       谁改了目录名（裁决点 §8.2-① `emergency` vs `emergency_info`）而另一侧没跟上，
       就在这里红；
    ③ 本域内零 `*queue.submit(...)` 直调（旁路守卫：命中即红，缺省 0 命中是设计终态，
       不是空转——真正防空转的是下面那条「闸侧触点确实存在」的锚点）。
    """
    # ① 闸侧唯一入口的生产引用面。
    referrers = [
        path
        for path in _production_python_files(PLUGIN_ROOT)
        if "submit_active_push" in path.read_text(encoding="utf-8")
    ]
    offenders = [
        _rel_to_plugin(path)
        for path in referrers
        if _rel_to_plugin(path) != GATE_MODULE_REL
        and not _rel_to_plugin(path).startswith(DOMAIN_REL + "/")
    ]
    assert offenders == [], f"`submit_active_push` 被闸与紧急域之外的生产件引用：{offenders}"

    # ② 双向对齐闸席的 T6 白名单。
    gate_roots = _gate_t6_allowed_roots()
    assert gate_roots, (
        f"从 tests/test_outbound_gate.py::{GATE_T6_TEST} 提取白名单失败＝两侧对齐失效"
        "（该测试结构变了要同步这里，不许默默放宽）"
    )
    covered = [str(root) for root in gate_roots if str(DOMAIN_DIR).startswith(str(root))]
    assert covered, (
        f"闸侧白名单 {gate_roots} 已不覆盖本域目录 {DOMAIN_DIR}——"
        "目录改名（§8.2-①）须两侧同改"
    )
    assert any(
        str(PLUGIN_ROOT / GATE_MODULE_REL).startswith(str(root)) for root in gate_roots
    ), "闸侧白名单把自己也排除了，T6 已失去意义"

    # ③ 域内零直调队列（绕闸）。
    bypass: list[str] = []
    for path in _production_python_files(DOMAIN_DIR):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "submit":
                receiver = ast.unparse(func.value)
                if "queue" in receiver.lower():
                    bypass.append(f"{_rel_to_plugin(path)}:{node.lineno} {receiver}.submit")
    assert bypass == [], f"本域绕过中央闸直调发送队列：{bypass}"

    # 锚点：闸侧触点确实存在，且带 `dedupe_family` 关键字（锁 D 的前提）。
    gate_defs = {
        node.name: [a.arg for a in node.args.args + node.args.kwonlyargs]
        for node in ast.walk(ast.parse((PLUGIN_ROOT / GATE_MODULE_REL).read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef)
    }
    assert "submit_active_push" in gate_defs, "中央闸的唯一触点已消失"
    assert "dedupe_family" in gate_defs["submit_active_push"], (
        "闸侧 `dedupe_family` 形参被删＝锁 D 的判定对象不存在，须两侧同改"
    )


# ---- 锁 C｜priority 载体一致（依赖未落地代码：xfail，不为此造实现）------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "锁 C 的前提 `build_emergency_send_request` 全仓 0 命中（规格 §8.1 锁 C、§8.4）。"
        "接线席落地后删掉本标记即转正——转正后它就是「P0 被静默顺延＝漏报」的唯一回归锁。"
    ),
)
def test_send_request_priority_carries_the_emergency_level() -> None:
    """锁 C：`SendRequest.priority` 必须是 `str(item.level.value)`，不是现族字面量。

    机制（规格 §8.4）：`outbound_gate.py:248 _severity_of` 吃 `priority` → `:252 _is_urgent`
    → `:554 _quiet_verdict` 决定是否顺延。写成 `"normal"` 之类 ⇒ 安静时间窗内 P0 被当
    非紧急推到窗尾，**不抛、不记 degraded、不进告警**＝漏报。`level=None` 不得成请求。
    """
    try:
        builder = _find_domain_function("build_emergency_send_request")
    except LookupError as exc:
        pytest.fail(str(exc))

    for level in EmergencyLevel:
        graded = _item().model_copy(
            update={"status": EmergencyStatus.APPROVED, "level": level}
        )
        request = _call_with_candidate_kwargs(builder, graded)
        assert request is not None, f"{level.value} 竟然出不了请求"
        assert request.priority == str(level.value), (
            f"{level.value} 的载体不是字面量 {level.value}：实得 {request.priority!r}"
        )

    ungraded = _item().model_copy(update={"status": EmergencyStatus.APPROVED})
    assert ungraded.level is None
    try:
        produced = _call_with_candidate_kwargs(builder, ungraded)
    except ValueError:
        produced = None  # 「未定级不可投」以抛异常表达也算通过
    assert produced is None, (
        "level=None 也能产出 SendRequest ⇒ 未定级条目会带着空/假 priority 进闸"
    )


def _call_with_candidate_kwargs(builder: Any, item: EmergencyItem) -> Any:
    """按**形参名**喂本锁能想到的实参；缺哪个必需形参就点名判红（绝不静默跳过）。

    刻意不锁签名（签名归接线席），只钉 priority 这一条不变式；候选表覆盖不到时
    本锁会红在断言里并写出缺的名字，落地时照名字补齐即可转正。
    """
    candidates: dict[str, Any] = {
        "item": item,
        "now": _NOW,
        "channel": "qq",
        "target_id": "1108838060",
        "session_id": "1108838060",
        "group_id": "1108838060",
        "date_key": date_key_of(_NOW),
    }
    signature = inspect.signature(builder)
    kwargs: dict[str, Any] = {}
    unknown: list[str] = []
    for name, parameter in signature.parameters.items():
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if name in candidates:
            kwargs[name] = candidates[name]
        elif parameter.default is inspect.Parameter.empty:
            unknown.append(name)
    assert not unknown, (
        f"{getattr(builder, '__name__', builder)} 的必需形参 {unknown} 不在本锁候选表内"
        "——落地时补齐候选名并删 xfail 标记"
    )
    return builder(**kwargs)


# ---- 锁 D｜键族与键构造同源（依赖未落地代码：xfail）--------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "锁 D 的前提是生产面出现 `submit_active_push` 触闸点（今日 0 命中，规格 §8.1 锁 D"
        "的最小实现对象=装配面唯一 fan-out 函数）。接线席落地后删标记转正。"
    ),
)
def test_daily_family_and_date_key_are_declared_from_the_same_truth() -> None:
    """锁 D：报 `dedupe_family="daily"` 的地方必须真的带了 `date_key`（同真同假）。

    错配的具体后果（B4a §R2-3「会错的③」）：daily 报成 once ⇒ 跨日不再重投＝**漏发**；
    once 报成 daily ⇒ 闸侧五段强校验把一次性键判死＝**静默不发**。
    """
    functions = _domain_functions_calling("submit_active_push")
    assert functions, (
        "本域生产面还没有任何 `submit_active_push` 触闸点＝本锁无判定对象（等接线席落地）"
    )
    problems: list[str] = []
    for path, function in functions:
        families: list[str] = []
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or _called_name(node) != "submit_active_push":
                continue
            keyword = next((kw for kw in node.keywords if kw.arg == "dedupe_family"), None)
            if keyword is None:
                families.append("once")  # 闸侧缺省值（outbound_gate.py:645）
            elif isinstance(keyword.value, ast.Constant):
                families.append(str(keyword.value.value))
            else:
                families.append("<非字面量>")
        builders = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and _called_name(node) == KEY_BUILDER
        ]
        if not builders or "<非字面量>" in families:
            problems.append(
                f"{_rel_to_plugin(path)}:{function.name} 静态判不出 family↔date_key 关系"
                f"（families={families} 键构造点={len(builders)}）：请在本锁内补该形态，别放行"
            )
            continue
        wants_daily = "daily" in families
        has_dated = any(_passes_date_key(call) for call in builders)
        if wants_daily != has_dated:
            problems.append(
                f"{_rel_to_plugin(path)}:{function.name} family={families} 与 "
                f"date_key={has_dated} 不同真同假"
            )
    assert not problems, "；".join(problems)


def _passes_date_key(call: ast.Call) -> bool:
    """`build_emergency_dedupe_key(...)` 是否真的传了第四个参与量（日期段）。"""
    positional = len(call.args) >= 4
    keyword = next((kw for kw in call.keywords if kw.arg == "date_key"), None)
    if keyword is None:
        return positional
    if isinstance(keyword.value, ast.Constant):
        return bool(keyword.value) and keyword.value.value is not None
    return True  # 表达式（如 `date_key_of(now)`）：非 None 字面量一律按「传了」算


# ---- 锁 E｜颜色序位收敛（第三份表纳入锁）--------------------------------------


def test_the_third_color_rank_table_stays_in_lockstep() -> None:
    """锁 E：全仓第三份颜色→序位表 `sources/nmc_alarm.py:66` 必须与本域同表同序。

    既有收编锁 `test_level_color_labels_absorb_weather_alarm_vocabulary` 只管
    weather 与本域两处（规格 §8.5-B）；采集器为了「不 import 内核」自造了一份，
    漂移面＝有人改了 `contracts.py` 的颜色词或序位，采集器照旧出条目、
    `grade()` 却按新表判级（或反之）。要么同表，要么由 B2 席删掉它改吃
    `level_from_color_label()`。
    """
    mine = {level.color_label: level.rank for level in EmergencyLevel}
    collector = _module_constant(NMC_ALARM_FILE, "ALARM_COLOR_RANK")
    assert collector is not _MISSING, (
        "nmc_alarm.py 的 ALARM_COLOR_RANK 已被删除/搬走＝本锁的判定对象消失："
        "请与规格 §8.5-B 一起退役本锁，不要留下空锁"
    )
    assert collector == mine, f"采集器色序表与本域枚举漂移：{collector} != {mine}"
    weather = _module_constant(WEATHER_CAPABILITY, "_ALARM_COLOR_RANK")
    assert weather is not _MISSING, "weather 侧 _ALARM_COLOR_RANK 已搬走，需同步本锁"
    assert weather == mine == collector, "三份表必须是一份表"
    assert set(collector) == set(LEVEL_COLOR_LABEL.values())
