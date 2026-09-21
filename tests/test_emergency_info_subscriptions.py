"""WIRE-SUB 订阅层回归：规则解析、命中判定、存储往返、命令面与权限门。

口径出处（2026-09-20 用户裁定，覆盖施工图 §5-钉死② 第三腿）：
1.C 语法=参数式主干 + 自然语序别名；2 权限=超管 ∨ 管理员 ∨ 本群群主；
3.B 投递目标由订阅表现读派生（.env 名单不再是装配门）；4.B 地点判定=文字 ∨ 半径、
缺省半径 200km；5.A 永久直到退订；6 私聊与群聊都能设。

全离线：不联网（地名认得出来靠随包码表 `qx.json`，坐标解析器一律注入假件）、
不碰生产库（一律 tmp_path）、不发任何对外消息。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.emergency_info.capabilities import (
    emergency_info as cap,
)
from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyLevel,
    EmergencyStatus,
    build_emergency_item,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import (
    subscriptions as sub,
)
from plugins.bot_unified_runtime.domains.emergency_info.sources.store import (
    EmergencyStore,
)

_NOW = datetime(2026, 9, 20, 6, 30, tzinfo=timezone.utc)


# ------------------------------------------------------------------ 夹具


def _rule(text: str = "area=湘潭", **kwargs: Any) -> sub.SubscriptionRule:
    options: dict[str, Any] = {"target_scope": "group", "target_id": "1108838060"}
    options.update(kwargs)
    return sub.parse_subscription(text, **options)


def _item(
    *,
    item_id: str = "nmc-e1",
    source_id: str = "nmc",
    title: str = "湘潭市暴雨红色预警",
    level: EmergencyLevel | None = EmergencyLevel.P0,
    latitude: float | None = None,
    longitude: float | None = None,
) -> EmergencyItem:
    payload: dict[str, Any] = {
        "item_id": item_id,
        "source_id": source_id,
        "external_id": item_id.split(":")[-1],
        "title": title,
        "occurred_at": _NOW,
        "fetched_at": _NOW,
        "level": level,
        "latitude": latitude,
        "longitude": longitude,
    }
    built = build_emergency_item(payload)
    assert built is not None, "夹具本身不合契约＝后面的断言全在自证"
    return built


def _store(tmp_path: Path) -> EmergencyStore:
    return EmergencyStore(tmp_path / "emergency_info.sqlite3")


def _message(
    text: str,
    *,
    platform: str = "qq",
    group_id: str | None = "1108838060",
    sender_id: str = "3865067623",
    roles: list[str] | None = None,
    platform_role: str | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        request_id="req-sub",
        platform=platform,
        adapter="onebot11",
        bot_id="10000",
        session_id=f"group_{group_id}_{sender_id}" if group_id else f"p_{sender_id}",
        session_type=SessionType.GROUP if group_id else SessionType.PRIVATE,
        sender_id=sender_id,
        group_id=group_id or "",
        plain_text=text,
        sender_roles=list(roles or ["user"]),
        sender_platform_role=platform_role,
    )


def _admin(text: str, **kwargs: Any) -> IncomingMessage:
    """非权限用例一律以群管身份走（权限矩阵由下面的 parametrize 单独钉）。"""
    kwargs.setdefault("roles", ["admin"])
    return _message(text, **kwargs)


# ------------------------------------------------------------------ 解析：参数式主干


def test_param_form_is_the_backbone() -> None:
    rule = _rule("area=湘潭 kinds=暴雨,台风 levels=P0,P1 radius=150")
    assert rule.area_name == "湘潭"
    assert rule.kinds == frozenset({"暴雨", "台风"})
    assert rule.levels == frozenset({"P0", "P1"})
    assert rule.radius_km == 150.0
    assert rule.target_key == "group:1108838060"


def test_param_names_are_case_insensitive_and_single_is_accepted() -> None:
    rule = _rule("AREA=湘潭 KIND=暴雨 LEVEL=p2")
    assert rule.area_name == "湘潭"
    assert rule.kinds == frozenset({"暴雨"})
    assert rule.levels == frozenset({"P2"})


def test_natural_word_order_is_the_alias() -> None:
    """裁定 1.C：不写参数名也要能用——「湘潭 暴雨 橙色以上」是用户会打的字。"""
    rule = _rule("湘潭 暴雨 橙色以上")
    assert rule.area_name == "湘潭"
    assert rule.kinds == frozenset({"暴雨"})
    assert rule.levels == frozenset({"P0", "P1"}), "橙色以上＝橙色与更高（P0/P1）"


def test_color_words_map_to_levels_and_ceiling_expands() -> None:
    assert sub.normalize_levels(["红色", "蓝色"]) == frozenset({"P0", "P3"})
    assert sub.levels_from_ceiling("橙色") == frozenset({"P0", "P1"})
    # 「以上/及以上」是话术层的事，从命令解析这条路验，不测私有切词函数。
    assert _rule("橙色以上").levels == frozenset({"P0", "P1"})
    assert _rule("橙色及以上").levels == frozenset({"P0", "P1"})


def test_unknown_level_is_rejected_with_candidates() -> None:
    with pytest.raises(sub.RuleError) as caught:
        _rule("levels=P9")
    assert caught.value.candidates == ("P0", "P1", "P2", "P3")


def test_unknown_area_is_rejected_and_near_miss_names_are_offered() -> None:
    """"认不出就报错给候选"是纪律 1：静默收下＝用户以为订上了、实际永远收不到。"""
    with pytest.raises(sub.RuleError) as caught:
        _rule("area=香潭")
    assert "湘潭" in caught.value.candidates
    assert _rule("area=湘潭").area_name == "湘潭", "反证：正例这条路是通的"


def test_kind_vocabulary_is_open_but_structural_junk_is_rejected() -> None:
    assert sub.normalize_kinds(["暴雨", "雷电"]) == frozenset({"暴雨", "雷电"})
    with pytest.raises(sub.RuleError):
        sub.normalize_kinds(["暴雨 雷电 大风 沙尘 高温 寒潮 台风 雷雨 冰雹"])  # 超 MAX_TERMS
    with pytest.raises(sub.RuleError):
        sub.normalize_kinds(["暴雨,雷电"])  # 逗号糊成一坨＝没拆开


def test_radius_bounds_and_unit_suffix() -> None:
    assert sub.parse_radius("150km") == 150.0
    assert sub.parse_radius("") == sub.DEFAULT_RADIUS_KM == 200.0
    for bad in ("5", "99999", "abc"):
        with pytest.raises(sub.RuleError):
            sub.parse_radius(bad)


def test_coord_must_be_a_pair_and_in_range() -> None:
    assert sub.parse_coord("27.87,112.94") == (27.87, 112.94)
    for bad in ("27.87", "27.87,", "95,112.94", "abc,def"):
        with pytest.raises(sub.RuleError):
            sub.parse_coord(bad)


def test_empty_target_is_refused_never_guessed() -> None:
    """「绝不猜群/绝不猜人」在新载体的落点：目标空=不成立，不拿上一次的群号凑。"""
    with pytest.raises(sub.RuleError):
        sub.parse_subscription("area=湘潭", target_scope="group", target_id="  ")
    with pytest.raises(sub.RuleError):
        sub.parse_subscription("area=湘潭", target_scope="channel", target_id="1")


def test_area_without_resolver_stays_text_only_and_says_so() -> None:
    rule = _rule("area=湘潭")
    assert not rule.has_point
    assert "按地名文字匹配" in rule.describe()


def test_resolver_supplies_the_point_and_only_the_assembly_layer_supplies_it() -> None:
    rule = _rule("area=湘潭", resolver=lambda name: (27.87, 112.94))
    assert (rule.latitude, rule.longitude) == (27.87, 112.94)
    assert rule.has_point and rule.coord_resolved
    assert "200km 内" in rule.describe()


def test_resolver_failure_degrades_to_text_match_not_a_broken_rule() -> None:
    rule = _rule("area=湘潭", resolver=lambda _name: None)
    assert rule.latitude is None and rule.area_name == "湘潭"


# ------------------------------------------------------------------ 命中判定（裁定 4.B）


def test_level_dimension_filters_and_ungraded_never_passes() -> None:
    rule = _rule("area=湘潭 levels=P0")
    assert sub.matches_subscription(_item(), rule)
    assert not sub.matches_subscription(_item(level=EmergencyLevel.P2), rule)
    assert not sub.matches_subscription(_item(level=None), rule), "未定级不投（D-1）"


def test_unfiltered_rule_still_refuses_ungraded() -> None:
    """等级维度留空＝"全部"，但"全部"不含未定级：没判过的不自称能推。"""
    assert not sub.matches_subscription(_item(level=None), _rule(""))


def test_kind_matches_against_title_and_body() -> None:
    rule = _rule("kinds=暴雨")
    assert sub.matches_subscription(_item(), rule)
    assert not sub.matches_subscription(_item(title="湘潭市高温橙色预警"), rule)


def test_area_matches_by_text_for_alarms() -> None:
    assert sub.matches_subscription(_item(), _rule("area=湘潭"))
    assert not sub.matches_subscription(_item(title="长沙市暴雨红色预警"), _rule("area=湘潭"))


def test_area_matches_by_radius_for_coordinate_sources() -> None:
    near = _rule("coord=27.9,113.0 radius=50")
    far = _rule("coord=39.9,116.4 radius=50")
    quake = _item(item_id="usgs-q1", source_id="usgs", title="地震", latitude=27.87, longitude=112.94)
    assert sub.matches_subscription(quake, near)
    assert not sub.matches_subscription(quake, far)


def test_text_only_area_never_passes_a_coordinate_only_item() -> None:
    """宁漏不误投：规则只有地名、条目只有坐标 ⇒ 判不命中（本域最不能花掉的用户信任）。"""
    quake = _item(item_id="usgs-q2", source_id="usgs", title="M6.0 earthquake", latitude=27.87, longitude=112.94)
    assert not sub.matches_subscription(quake, _rule("area=湘潭"))


def test_dimensions_are_anded() -> None:
    rule = _rule("area=湘潭 kinds=暴雨 levels=P0")
    assert sub.matches_subscription(_item(), rule)
    assert not sub.matches_subscription(_item(title="长沙市暴雨红色预警"), rule)
    assert not sub.matches_subscription(_item(title="湘潭市高温橙色预警", level=EmergencyLevel.P1), rule)


# ------------------------------------------------------------------ 存储往返


def test_subscription_round_trips_through_sqlite(tmp_path: Path) -> None:
    store = _store(tmp_path)
    rule = _rule("area=湘潭 kinds=暴雨 levels=P0,P1 radius=150")
    assert store.save_subscription(rule, at=_NOW) is True
    assert store.get_subscription(rule.target_key) == rule


def test_same_target_keeps_exactly_one_rule_and_reports_overwrite(tmp_path: Path) -> None:
    """裁定 5.A 的存储侧形态：再设一次＝改口，不是并存两条各自生效。"""
    store = _store(tmp_path)
    assert store.save_subscription(_rule("area=湘潭"), at=_NOW) is True
    assert store.save_subscription(_rule("area=长沙"), at=_NOW) is False
    rows = store.list_subscriptions()
    assert [rule.area_name for rule in rows] == ["长沙"]


def test_group_and_private_targets_do_not_collide(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_subscription(_rule("area=湘潭"), at=_NOW)
    store.save_subscription(_rule("area=长沙", target_scope="private"), at=_NOW)
    assert len(store.list_subscriptions()) == 2
    assert store.delete_subscription("private:1108838060") is True
    assert len(store.list_subscriptions()) == 1


def test_cancel_is_idempotent_and_returns_whether_anything_was_there(tmp_path: Path) -> None:
    store = _store(tmp_path)
    rule = _rule("area=湘潭")
    store.save_subscription(rule, at=_NOW)
    assert store.delete_subscription(rule.target_key) is True
    assert store.delete_subscription(rule.target_key) is False


def test_prune_never_touches_subscriptions(tmp_path: Path) -> None:
    """保留期裁的是条目；裁掉订阅＝某群一夜之间静默停止接收播报（违背裁定 5.A）。"""
    store = _store(tmp_path)
    store.save_subscription(_rule("area=湘潭"), at=_NOW)
    assert store.prune(keep_days=1, now=_NOW) == 0
    assert len(store.list_subscriptions()) == 1


def test_match_observability_is_written_and_read_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    rule = _rule("area=湘潭")
    store.save_subscription(rule, at=_NOW)
    assert store.get_subscription(rule.target_key).match_count == 0
    store.note_subscription_match(rule.target_key, at=_NOW)
    store.note_subscription_match(rule.target_key, at=_NOW)
    after = store.get_subscription(rule.target_key)
    assert after is not None and after.match_count == 2
    assert after.last_matched_at is not None


def test_half_coordinate_row_is_dropped_not_delivered(tmp_path: Path) -> None:
    """库里混进半个坐标（手工改库/旧写入路径）时：读回判 None，绝不拿它算距离。"""
    store = _store(tmp_path)
    store.save_subscription(_rule("area=湘潭"), at=_NOW)
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE emergency_subscriptions SET latitude = 27.87, longitude = NULL"
        )
    assert store.list_subscriptions() == []
    assert store.get_subscription("group:1108838060") is None


def test_existing_library_gains_the_new_table_and_columns(tmp_path: Path) -> None:
    """存量库（本波之前建过 items 表）必须自动补列 + 建新表。

    `_SCHEMA` 全是 `CREATE ... IF NOT EXISTS`：旧库不会加列，而 `_SELECT_COLUMNS`
    一旦点名 latitude 就会让**每次读**抛 `no such column`——生产库建过一次即永久废掉。
    """
    path = tmp_path / "emergency_info.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE emergency_items (
                item_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                source_kind TEXT NOT NULL DEFAULT '', external_id TEXT NOT NULL,
                title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '', color_label TEXT NOT NULL DEFAULT '',
                occurred_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
                expires_at TEXT, date_key TEXT NOT NULL, level TEXT,
                credibility REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_by TEXT NOT NULL DEFAULT '', reviewed_at TEXT
            )
            """
        )
    store = EmergencyStore(path)
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(emergency_items)")}
        tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"latitude", "longitude"} <= columns
    assert "emergency_subscriptions" in tables
    assert store.list_by_status(EmergencyStatus.APPROVED) == []
    assert store.save_subscription(_rule("area=湘潭"), at=_NOW) is True


# ------------------------------------------------------------------ 命令面与权限（裁定 2/6）


@pytest.mark.parametrize(
    ("kwargs", "allowed"),
    [
        ({"roles": ["user"], "platform_role": "member"}, False),
        ({"roles": ["trusted"], "platform_role": "owner"}, True),
        ({"roles": ["admin"]}, True),
        ({"roles": ["super_admin"]}, True),
        ({"roles": ["user"], "platform_role": "owner"}, True),
    ],
)
def test_group_subscription_permission(kwargs: dict[str, Any], allowed: bool) -> None:
    message = _message("紧急信息 订阅 area=湘潭", **kwargs)
    assert cap.allows_emergency_subscription(message, "group") is allowed


def test_platform_owner_leg_does_not_leak_into_private(tmp_path: Path) -> None:
    """群主是「这个群」的事实：私聊没有群主，不能让当过家主的人在私聊自设权限。"""
    owner = _message(
        "紧急信息 订阅 area=湘潭",
        group_id=None,
        platform_role="owner",
    )
    assert cap.subscription_target(owner) == ("private", "3865067623")
    assert cap.allows_emergency_subscription(owner, "private") is False


def test_non_qq_platform_is_refused_before_anything_is_stored(tmp_path: Path) -> None:
    """TG 用户号存进去会拿去过 QQ 投递：同号不同平台是误投，不是失败。"""
    store = _store(tmp_path)
    body = _run(store, _message("紧急信息 订阅 area=湘潭", platform="telegram"))
    assert "只能在 QQ" in body
    assert store.list_subscriptions() == []


def _run(store: EmergencyStore, message: IncomingMessage) -> str:
    capability = cap.build_emergency_info_capability(None)
    capability.wiring.store = store
    result = capability(message)
    return str(result.body)


def test_command_sets_then_shows_then_cancels(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert "湘潭" in _run(store, _admin("紧急信息 订阅 area=湘潭 kinds=暴雨 橙色以上"))
    shown = _run(store, _admin("紧急信息 订阅 看"))
    assert "暴雨" in shown and "P0" in shown
    assert "没收下" not in shown
    assert "退掉" in _run(store, _admin("紧急信息 退订"))
    assert store.list_subscriptions() == []


def test_bare_subscribe_shows_instead_of_ordering_everything() -> None:
    """裸一个动词＝查看：无过滤的全量推送不该由一次手滑设立。"""
    assert cap.subscription_subcommand("订阅") == ("view", "")
    assert cap.subscription_subcommand("订阅 看") == ("view", "")
    assert cap.subscription_subcommand("订阅 area=湘潭") == ("set", "area=湘潭")
    assert cap.subscription_subcommand("退订") == ("cancel", "")
    assert cap.subscription_subcommand("列表") is None
    assert cap.subscription_subcommand("地震") is None


def test_bare_view_on_fresh_target_shows_usage_not_an_error(tmp_path: Path) -> None:
    body = _run(_store(tmp_path), _admin("紧急信息 订阅"))
    assert "还没有" in body and "用法示例" in body


def test_bad_area_answers_with_candidates_in_chat(tmp_path: Path) -> None:
    """错地名不能只回一句"失败"：候选词直接进对话，用户下一条就能改对。"""
    body = _run(_store(tmp_path), _admin("紧急信息 订阅 area=香潭"))
    assert "没收下" in body and "湘潭" in body


def test_rejected_rule_writes_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store, _message("紧急信息 订阅 area=香潭"))
    assert store.list_subscriptions() == []


def test_denied_member_writes_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    body = _run(store, _message("紧急信息 订阅 area=湘潭", roles=["user"], platform_role="member"))
    assert "群主或管理员" in body
    assert store.list_subscriptions() == []


def test_group_command_targets_this_group_not_the_sender(tmp_path: Path) -> None:
    """群内设的是**这个群**的规则：目标取事件自带的群号，不是发送者 QQ 号。"""
    store = _store(tmp_path)
    _run(store, _message("紧急信息 订阅 area=湘潭", roles=["admin"]))
    rule = store.get_subscription("group:1108838060")
    assert rule is not None and rule.created_by == "3865067623"
    assert rule.target_scope == "group"


def test_private_chat_can_subscribe_too(tmp_path: Path) -> None:
    """裁定 6：私聊同面可用（目标是本人号）。"""
    store = _store(tmp_path)
    _run(store, _message("紧急信息 订阅 kinds=地震", group_id=None, roles=["super_admin"]))
    rule = store.get_subscription("private:3865067623")
    assert rule is not None and rule.target_scope == "private"


def test_fresh_rule_does_not_scold_but_stale_one_does(tmp_path: Path) -> None:
    """刚设完就说"从没命中过"是责备用户；查看旧规则时必须说。"""
    store = _store(tmp_path)
    set_body = _run(store, _message("紧急信息 订阅 area=湘潭", roles=["admin"]))
    assert "一次都没命中过" not in set_body
    assert "一次都没命中过" in _run(store, _admin("紧急信息 订阅 看"))


def test_subscription_works_behind_every_domain_trigger_word(tmp_path: Path) -> None:
    """订阅面复用既有触发词，没造第二套：`紧急信息 订阅…` 与 `预警 订阅…` 同一能力接。"""
    assert cap.is_emergency_info_command("紧急信息 订阅 area=湘潭")
    assert cap.is_emergency_info_command("预警 订阅 area=湘潭")
    store = _store(tmp_path)
    assert "湘潭" in _run(store, _message("预警 订阅 area=湘潭", roles=["admin"]))


# ------------------------------------------------------------------ 契约：条目坐标


def test_item_coordinates_must_arrive_as_a_pair() -> None:
    base: dict[str, Any] = {
        "item_id": "usgs-1",
        "source_id": "usgs",
        "external_id": "1",
        "title": "地震",
        "occurred_at": _NOW,
        "fetched_at": _NOW,
    }
    assert build_emergency_item({**base, "latitude": 27.87, "longitude": 112.94}) is not None
    assert build_emergency_item({**base, "latitude": 27.87}) is None, "半个坐标比没有更坏"
    assert build_emergency_item({**base, "latitude": 95.0, "longitude": 0.0}) is None
    assert build_emergency_item(base) is not None, "没给坐标是合法形态（气象预警就没有）"


# ------------------------------------------------ 端到端：设完当轮真的投（活性证明）
#
# 为什么必须有这一族：`test_emergency_info_reachability.py` 的 R1/订阅锁全是**静态**
# 判定（字符串/AST 在不在），本波已经烧过两回"结构在、装配落空"（D-8(a) 那回就是
# 机制存在但没人构造它）。订阅这件事的全部意义是「群里说完，下一轮只推对的群」，
# 所以正面跑真 job：假调度器接住 job 函数 → 真 `EmergencyInfoService` → 真投递触点
# → 关闸态的 `submit_active_push` 直通 → 记账队列。网络采集支路用 monkeypatch 摘掉。


class _FakeScheduler:
    """只接住 `add_job` 的调度器替身：job 函数拿来手动跑一轮。"""

    def __init__(self) -> None:
        self.job: Any = None

    def add_job(self, func: Any, *_args: Any, **_kwargs: Any) -> dict:
        self.job = func
        return {}


class _RecordingQueue:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def submit(self, request: Any, deliver_after: Any = None) -> Any:
        from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
            DeliveryReceipt,
            ReceiptState,
        )

        self.requests.append(request)
        return DeliveryReceipt(
            request_id=request.request_id,
            state=ReceiptState.QUEUED,
            transport="onebot",
        )


class _ConfigStub:
    """只钉紧急域配置面（生产由 pydantic Config 提供，形态逐键一致）。"""

    bot_emergency_info_enabled = True
    bot_emergency_info_poll_interval_seconds = 300
    bot_emergency_info_min_level = ""
    bot_emergency_info_keep_days = 90
    bot_persona_profile_id = "default"

    def __init__(self, db_path: str) -> None:
        self.bot_emergency_info_db_path = db_path
        self.bot_emergency_info_sources = ["nmc"]
        self.bot_emergency_info_auto_approve_sources: list[str] = []
        self.bot_emergency_info_push_group_whitelist: list[str] = []
        self.bot_emergency_info_push_user_ids: list[str] = []
        self.bot_emergency_info_reviewer_ids: list[str] = []


def _seed_approved(store: EmergencyStore, *, item_id: str, title: str, color: str) -> None:
    built = build_emergency_item(
        {
            "item_id": item_id,
            "source_id": "nmc",
            "external_id": item_id,
            "title": title,
            "color_label": color,
            "occurred_at": _NOW,
            "fetched_at": _NOW,
            "status": "approved",
        }
    )
    assert built is not None, "夹具不合契约＝后面的断言全在自证"
    assert store.upsert_item(built) is True


def _closed_gate() -> Any:
    """真 `OutboundGate`、`enabled=False`：中央闸关闭态按契约直通裸 submit。

    刻意不用 `gate=None`——那是"闸根本没装配"的另一回事（1.A 判定=一条都不投），
    拿它当夹具会让整族用例在"其实压根没投递"的假象下恒绿。
    """
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGate,
        OutboundGateSettings,
    )

    return OutboundGate(OutboundGateSettings(enabled=False))


def _round(tmp_path: Path, store: EmergencyStore, monkeypatch: pytest.MonkeyPatch) -> _RecordingQueue:
    from plugins.bot_unified_runtime import _register_emergency_info_scheduler
    from plugins.bot_unified_runtime.domains.emergency_info.service import collector

    # 采集支路摘网：本轮只验「已入库条目 → 订阅过滤 → 投递目标」这一段。
    monkeypatch.setattr(collector, "run_collection_once", lambda *a, **k: None)
    config = _ConfigStub(str(tmp_path / "emergency_info.sqlite3"))
    service = cap.EmergencyInfoService(
        store=store, source=cap.build_emergency_info_source(config), gate=object()
    )
    queue = _RecordingQueue()
    scheduler = _FakeScheduler()
    _register_emergency_info_scheduler(
        scheduler, config, service, queue, _closed_gate()
    )
    assert scheduler.job is not None, "调度器没接到 job ⇒ 自动采集整链其实没装配"
    scheduler.job()
    return queue


def _sessions(queue: _RecordingQueue) -> list[str]:
    return [str(request.session_id) for request in queue.requests]


def _targets_for(queue: _RecordingQueue, item_id: str) -> list[str]:
    """某条条目实际投给了谁（幂等键含 item_id，比按顺序数更耐仓储读序变化）。"""
    return [
        str(request.session_id)
        for request in queue.requests
        if item_id in str(request.dedupe_key)
    ]


def test_two_groups_with_different_rules_receive_only_their_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """用户要的那件事：A 群订湘潭、B 群订长沙 ⇒ 各自的预警只进各自的群。"""
    store = _store(tmp_path)
    store.save_subscription(_rule("area=湘潭 kinds=暴雨", target_id="1108838060"), at=_NOW)
    store.save_subscription(_rule("area=长沙 kinds=高温", target_id="631785829"), at=_NOW)
    _seed_approved(store, item_id="nmc-x1", title="湘潭市暴雨红色预警", color="红色")
    _seed_approved(store, item_id="nmc-c1", title="长沙市高温橙色预警", color="橙色")
    queue = _round(tmp_path, store, monkeypatch)
    assert _targets_for(queue, "nmc-x1") == ["group:1108838060"], (
        "湘潭那条越过了本群边界＝订阅过滤整链没接上"
    )
    assert _targets_for(queue, "nmc-c1") == ["group:631785829"]
    assert len(queue.requests) == 2, "两条条目各投一群，多出来的就是没被过滤掉的那条"


def test_delivered_request_carries_the_level_as_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """钉死① 的活性面：过筛之后还得把等级带上，否则夜里 P0 被当普通消息顺延＝漏报。"""
    store = _store(tmp_path)
    store.save_subscription(_rule("area=湘潭"), at=_NOW)
    _seed_approved(store, item_id="nmc-x2", title="湘潭市暴雨红色预警", color="红色")
    queue = _round(tmp_path, store, monkeypatch)
    assert len(queue.requests) == 1
    request = queue.requests[0]
    assert request.priority == "P0" and request.capability_id == "bot.emergency_info"


def test_no_subscription_and_no_env_list_delivers_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"绝不猜群/绝不猜人"在新载体的等价替换：没有目标行＝一条都不投。"""
    store = _store(tmp_path)
    _seed_approved(store, item_id="nmc-x3", title="湘潭市暴雨红色预警", color="红色")
    queue = _round(tmp_path, store, monkeypatch)
    assert queue.requests == []


def test_round_reads_subscriptions_set_after_assembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """装配之后再设的订阅必须当轮生效——这条是「不用重启」的正面证明。"""
    store = _store(tmp_path)
    _seed_approved(store, item_id="nmc-x4", title="湘潭市暴雨红色预警", color="红色")
    assert _round(tmp_path, store, monkeypatch).requests == []
    store.save_subscription(_rule("area=湘潭"), at=_NOW)
    queue = _round(tmp_path, store, monkeypatch)
    assert _sessions(queue) == ["group:1108838060"]
    assert store.get_subscription("group:1108838060").match_count == 1


def test_env_hardwired_list_still_delivers_without_a_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 硬推腿保留为可选腿（降级不删除）：它在位时不受订阅条件约束。"""
    from plugins.bot_unified_runtime import _register_emergency_info_scheduler
    from plugins.bot_unified_runtime.domains.emergency_info.service import collector

    store = _store(tmp_path)
    _seed_approved(store, item_id="nmc-x5", title="长沙市高温橙色预警", color="橙色")
    monkeypatch.setattr(collector, "run_collection_once", lambda *a, **k: None)
    config = _ConfigStub(str(tmp_path / "emergency_info.sqlite3"))
    config.bot_emergency_info_push_user_ids = ["3865067623"]
    service = cap.EmergencyInfoService(
        store=store, source=cap.build_emergency_info_source(config), gate=object()
    )
    queue = _RecordingQueue()
    scheduler = _FakeScheduler()
    _register_emergency_info_scheduler(
        scheduler, config, service, queue, _closed_gate()
    )
    scheduler.job()
    assert _sessions(queue) == ["private:3865067623"]
    assert queue.requests[0].target_scope is SessionType.PRIVATE
