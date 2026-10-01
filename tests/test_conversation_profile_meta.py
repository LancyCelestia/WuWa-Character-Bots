"""需求 4 二批（2026-09-29 S-META）：统一会话画像采集层的**判据锁**。

与一期的分工：一期把「读得到」逐格接上了（群务、对端资料、三态答句），本批补的是
**结构化画像层**——每个格子自带 来源 / 状态 / 时间戳 / 可信度 / 缺失原因，并把权限与
隐私门从「各条腿各写一遍 if」收成一枚判据函数。锁面按四件事立：

① 每格三件一体：``state`` + ``source`` + ``fetched_at`` 必须由采集层写，展示层不许
   再自己判「这格算不算读到了」；六态分立（ok / empty / missing / failed / unprobed /
   absent / forbidden），任何两态都不许塌成一句万金油降级。
② 隐私门是**结构性的**：被拦下的格子在画像里就不带值（``value`` 恒空），所以注入侧
   与展示侧都没有可用的渲染支路——「泄露」在结构上写不出来，而不是靠每次记得写 if。
③ 跨会话零通路：问别的群/别的人 ⇒ 该域全部格子 ``forbidden`` 且**一次接口都不打**
   （锁用 ``_never_called`` 形态的读口，打了就抛）。
④ 缺席必须是「被看着的状态」：幸运符号/群幸运符号/网络制式/成员全量名单这些格以
   ``absent`` 出现在画像里并带核证理由——一期是散文+枚举锁，本批把它变成结构化事实。

全部离线：假 API（内存罐头载荷）+ 手造事件，零网络、零真实凭据、零 Runtime 写。
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import group_info as gi
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    conversation_profile as cp,
)

_CLOCK_VALUE = 1_700_000_000.0


def _clock() -> float:
    return _CLOCK_VALUE


# ---------------------------------------------------------------------------
# 罐头载荷与假读口
# ---------------------------------------------------------------------------

_QQ_GROUP_PAYLOAD: dict[str, Any] = {
    "get_group_info": {
        "group_name": "看海观测站",
        "group_memo": "只做观测，不催更。",
        "member_count": 48,
        "max_member_count": 200,
        "group_create_time": 1_600_000_000,
    },
    "get_group_member_list": [
        {"user_id": 101, "nickname": "站主", "card": "站主", "role": "owner"},
        {"user_id": 102, "nickname": "巡", "card": "", "role": "admin"},
        {"user_id": 3007, "nickname": "阿澜", "card": "澜汐", "title": "观测员", "role": "member"},
    ],
    "_get_group_notice": [{"sender_id": 101, "time": 1, "message": {"text": "本周五晚八点群直播"}}],
    "get_essence_msg_list": [{"message_id": 1}, {"message_id": 2}],
    "get_group_album_list": [{"name": "海", "picNum": 12}],
    "get_group_todo_list": [{"text": "补 9 月观测表"}],
    "get_stranger_info": {
        "nickname": "阿澜",
        "long_nick": "今天也在看海",
        "level": "12",
        "status": 1,
        "batteryStatus": 0,
    },
}


class _FakeFetch:
    """``(kind, key, action, **params) -> (ok, payload)`` 形态的读口（与一期同签名）。"""

    def __init__(self, payloads: dict[str, Any], *, fail: set[str] = frozenset()) -> None:
        self.payloads = payloads
        self.fail = set(fail)
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []

    def __call__(self, kind: str, key: str, action: str, **params: Any) -> tuple[bool, Any]:
        self.calls.append((kind, key, action, params))
        if action in self.fail:
            return False, None
        if action not in self.payloads:
            return False, None
        return True, self.payloads[action]

    @property
    def actions(self) -> list[str]:
        return [action for _k, _key, action, _p in self.calls]

    def kinds_for(self, kind: str) -> list[str]:
        return [key for _k, key, action, _p in self.calls if kind == _k and action not in ()]


def _never_fetch(*_a: Any, **_k: Any) -> tuple[bool, Any]:
    raise AssertionError("画像层在被拦下的路上一次接口都不许打")


def _qq_group_message(**over: Any) -> IncomingMessage:
    data: dict[str, Any] = {
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "10000",
        "session_id": "group_12345",
        "session_type": SessionType.GROUP,
        "sender_id": "3007",
        "group_id": "12345",
        "sender_display_name": "澜汐",
        "sender_nickname": "阿澜",
        "sender_card": "澜汐",
        "sender_title": "观测员",
        "sender_platform_role": "member",
        "sender_level": "12",
        "plain_text": "群资料",
    }
    data.update(over)
    return IncomingMessage(**data)


# ---------------------------------------------------------------------------
# ① 每格三件一体：状态 / 来源 / 时间戳
# ---------------------------------------------------------------------------


def test_every_cell_carries_state_source_and_timestamp() -> None:
    fetch = _FakeFetch(_QQ_GROUP_PAYLOAD)
    profile = cp.build_profile(_qq_group_message(), fetch, clock=_clock)
    by_key = {field.key: field for field in profile.fields}

    name = by_key["group_name"]
    assert (name.state, name.source) == (cp.FIELD_OK, cp.SOURCE_PROTOCOL)
    assert name.value == "看海观测站"
    assert name.fetched_at == _CLOCK_VALUE, "协议读数必须带采集时刻（缓存新鲜度要能算）"

    card = by_key["group_card"]
    assert (card.state, card.source) == (cp.FIELD_OK, cp.SOURCE_EVENT)
    assert card.value == "澜汐"
    # 事件格的「时间」就是这一轮的时间——不假称更早的采集时刻。
    assert card.fetched_at == _CLOCK_VALUE

    signature = by_key["signature"]
    assert (signature.state, signature.value) == (cp.FIELD_OK, "今天也在看海")
    assert signature.source == cp.SOURCE_PROTOCOL

    assert profile.platform == "qq"
    assert profile.scope == "group"
    assert profile.subject_user_id == "3007"
    assert profile.built_at == _CLOCK_VALUE


def test_confidence_ladder_is_derived_from_source_not_handwritten() -> None:
    fetch = _FakeFetch(_QQ_GROUP_PAYLOAD)
    profile = cp.build_profile(_qq_group_message(), fetch, clock=_clock)
    by_key = {field.key: field for field in profile.fields}
    assert by_key["group_name"].confidence == cp.CONFIDENCE_PROTOCOL
    assert by_key["group_card"].confidence == cp.CONFIDENCE_DIRECT
    # 记忆口径（参与者）是「我的记录」，不是协议事实——三档可信度必须分得开。
    assert by_key["participants"].confidence == cp.CONFIDENCE_MEMORY


# ---------------------------------------------------------------------------
# ② 六态分立：empty / missing / failed / unprobed / absent / forbidden
# ---------------------------------------------------------------------------


def test_empty_value_and_absent_field_are_two_different_states() -> None:
    """「回了空串」与「没回这个字段」是两个态——一期就吃过这个混淆。

    两条通道各锁一对判据：
    ① 协议通道——``get_group_info`` 回了 ``group_memo=""``（字段在、值空）＝``empty``，
       同一份载荷根本没带 ``member_count``＝``missing``。
    ② 事件通道——``sender_card=""``（事件带了、带的是空串）＝``empty``，
       ``sender_title`` 整个没带＝``missing``。
    自己问自己这一轮，名片/头衔**事件自带就是当场事实**（绿锁
    ``test_every_cell_carries_state_source_and_timestamp`` 钉着它们是 ``SOURCE_EVENT``），
    所以这两格的空/缺只能从事件位喂——改成员表打不到它们，那是「问别人」那条支路。
    """
    payloads = dict(_QQ_GROUP_PAYLOAD)
    payloads["get_group_info"] = {"group_name": "看海观测站", "group_memo": ""}
    payloads["get_group_member_list"] = [
        {"user_id": 3007, "nickname": "阿澜", "card": "", "role": "member"}
    ]
    profile = cp.build_profile(
        _qq_group_message(sender_card="", sender_title=None), _FakeFetch(payloads), clock=_clock
    )
    by_key = {field.key: field for field in profile.fields}
    assert by_key["group_memo"].state == cp.FIELD_EMPTY
    assert by_key["member_count"].state == cp.FIELD_MISSING
    assert by_key["group_card"].state == cp.FIELD_EMPTY
    assert by_key["group_title"].state == cp.FIELD_MISSING
    # 两态都不带值（非 ok 态值恒空是结构性的，不靠调用方记得清）。
    assert by_key["group_card"].value == "" and by_key["group_title"].value == ""
    # 缺席态的措辞不许写成「对方没有头衔」——那是一次替协议下结论。
    assert "没回" in by_key["group_title"].reason or "未回" in by_key["group_title"].reason
    assert "没有头衔" not in by_key["group_title"].reason


def test_api_failure_is_failed_and_never_claims_absence() -> None:
    fetch = _FakeFetch(_QQ_GROUP_PAYLOAD, fail={"get_group_info", "get_group_member_list"})
    profile = cp.build_profile(_qq_group_message(), fetch, clock=_clock)
    by_key = {field.key: field for field in profile.fields}
    assert by_key["group_name"].state == cp.FIELD_FAILED
    assert by_key["group_name"].value == ""
    # 失败态不许被投影成「这个群没有群名」，也不许假托「没去探测」。
    rendered = cp.answer_lines(profile, is_self=True, privileged=True)
    joined = "\n".join(rendered)
    assert "没有群名" not in joined
    assert cp.NOTE_UNPROBED_LINE not in joined


def test_unprobed_bridge_makes_protocol_cells_unprobed_and_calls_nothing() -> None:
    profile = cp.build_profile(
        _qq_group_message(), _never_fetch, api_available=False, clock=_clock
    )
    states = {field.key: field.state for field in profile.fields}
    assert states["group_name"] == cp.FIELD_UNPROBED
    assert states["signature"] == cp.FIELD_UNPROBED
    # 事件格与缺席格不受桥影响：当场事实照说，结构性没有照说。
    assert states["group_card"] == cp.FIELD_OK
    assert states["lucky_symbol"] == cp.FIELD_ABSENT


def test_structurally_absent_cells_are_present_in_the_profile_with_reasons() -> None:
    """缺席必须是画像里**看得见的状态**，不是「整格消失」——否则下次接手又当没做。"""
    profile = cp.build_profile(_qq_group_message(), _FakeFetch(_QQ_GROUP_PAYLOAD), clock=_clock)
    by_key = {field.key: field for field in profile.fields}
    for key, keyword in (
        ("lucky_symbol", "打卡"),
        ("group_lucky_symbol", "同上"),
        ("network_type", "动作册"),
        ("member_roster", "名单"),
    ):
        field = by_key[key]
        assert field.state == cp.FIELD_ABSENT, key
        assert field.value == ""
        assert keyword in field.reason, (key, field.reason)
    # 理由锁的是**核证线索**（点名缺席的是哪一格 + 指出在哪儿核过），不是整句措辞：
    # 出站文案改个标点就该转红的锁，不叫锁。
    network = by_key["network_type"]
    assert "网络制式" in network.reason, network.reason


# ---------------------------------------------------------------------------
# ③ 权限与隐私门（结构性，不靠每次记得写 if）
# ---------------------------------------------------------------------------


def test_peer_cells_are_forbidden_and_valueless_for_third_party() -> None:
    """问「别人」的资料：非授权者拿不到对端账号面，且**画像里根本不带值**。"""
    fetch = _FakeFetch(_QQ_GROUP_PAYLOAD)
    profile = cp.build_profile(
        _qq_group_message(sender_roles=["user"]),
        fetch,
        subject_user_id="102",
        clock=_clock,
    )
    by_key = {field.key: field for field in profile.fields}
    for key in ("signature", "online_status", "battery", "account_id"):
        assert by_key[key].state == cp.FIELD_FORBIDDEN, key
        assert by_key[key].value == "", key
    assert cp.NOTE_FORBIDDEN_LINE in " ".join(cp.answer_lines(profile, is_self=False, privileged=False))
    # 群务面不受这一门影响（群名是群内公开事实）。
    assert by_key["group_name"].state == cp.FIELD_OK


def test_privileged_cells_hidden_from_plain_member() -> None:
    fetch = _FakeFetch(_QQ_GROUP_PAYLOAD)
    member = cp.build_profile(_qq_group_message(sender_roles=["user"]), fetch, clock=_clock)
    admin = cp.build_profile(
        _qq_group_message(sender_roles=["admin"]), fetch, clock=_clock
    )
    by_key = {field.key: field for field in member.fields}
    assert by_key["group_notice"].state == cp.FIELD_FORBIDDEN
    assert by_key["essence_count"].state == cp.FIELD_FORBIDDEN
    admin_keys = {field.key: field for field in admin.fields}
    assert admin_keys["group_notice"].state == cp.FIELD_OK
    assert admin_keys["group_notice"].value == "本周五晚八点群直播"
    # 门在取数之前，不是取完再藏：整场只该出现一次公告取数（管理员那一次）。
    assert fetch.actions.count("_get_group_notice") == 1, fetch.actions
    assert fetch.actions.count("get_essence_msg_list") == 1, fetch.actions


def test_cross_session_group_query_is_refused_without_any_call() -> None:
    """拿别的群的号来问：群务协议域整片拒绝，一次接口都不打（跨会话泄露的根形态）。"""
    profile = cp.build_profile(
        _qq_group_message(), _never_fetch, target_group_id="99999", clock=_clock
    )
    by_key = {field.key: field for field in profile.fields}
    for key in (
        "group_id",
        "group_name",
        "group_memo",
        "member_count",
        "group_age",
        "owner",
        "admins_count",
        "group_notice",
        "essence_count",
        "album",
        "todo",
        "files",
    ):
        assert by_key[key].state == cp.FIELD_FORBIDDEN, key
        assert by_key[key].value == "", key
    # 结构性缺席格与跨会话无关：它本来就没有，不该被说成「拒绝」。
    assert by_key["group_lucky_symbol"].state == cp.FIELD_ABSENT
    assert profile.scope == "group"


def test_note_projection_drops_everything_not_ok() -> None:
    fetch = _FakeFetch(_QQ_GROUP_PAYLOAD)
    profile = cp.build_profile(_qq_group_message(), fetch, clock=_clock)
    note = cp.note_text(profile, is_self=True, privileged=False)
    assert "个性签名=今天也在看海" in note
    assert "群名片=澜汐" in note
    assert "在线状态=在线（状态码 1）" in note
    # 电量回 0＝无有效值：注入串里这一格连标签都不许出现（一期同口径的结构版）。
    assert "电量" not in note
    assert "公告" not in note and "精华" not in note, "非管理员的注入串不许带特权格"
    assert cp.NOTE_UNPROBED_LINE not in note


def test_note_whitelist_excludes_rosters_and_memory_surfaces() -> None:
    """注入面刻意不收参与者/名单/群文件概览——那是长期铺开别人痕迹的另一条隐私线。"""
    assert "participants" not in cp.NOTE_KEYS
    assert "member_roster" not in cp.NOTE_KEYS
    assert "files" not in cp.NOTE_KEYS
    assert "album" not in cp.NOTE_KEYS
    assert "todo" not in cp.NOTE_KEYS


def test_offline_status_is_a_value_while_battery_zero_is_not() -> None:
    payloads = dict(_QQ_GROUP_PAYLOAD)
    payloads["get_stranger_info"] = {"nickname": "阿澜", "status": 0, "batteryStatus": 0}
    profile = cp.build_profile(_qq_group_message(), _FakeFetch(payloads), clock=_clock)
    by_key = {field.key: field for field in profile.fields}
    assert (by_key["online_status"].state, by_key["online_status"].value) == (
        cp.FIELD_OK,
        "离线（状态码 0）",
    )
    assert by_key["battery"].state == cp.FIELD_MISSING


# ---------------------------------------------------------------------------
# ④ 参与者与群文件两腿：状态来自真身件，不自己判
# ---------------------------------------------------------------------------


class _Memory:
    def __init__(self, state: str, records: tuple[Any, ...] = (), total: int = 0) -> None:
        self.state = state
        self.records = records
        self.total_speakers = total
        self.window_exhausted = False
        self.row_window = 0


def test_participants_cell_maps_the_three_memory_states() -> None:
    def build(memory: Any) -> cp.ProfileField:
        profile = cp.build_profile(
            _qq_group_message(), _FakeFetch(_QQ_GROUP_PAYLOAD), participant_memory=memory, clock=_clock
        )
        return profile.get("participants")

    ok = build(_Memory(cp.STATE_OK, (type("R", (), {"display_name": "阿澜", "turns": 3})(),), 1))
    assert (ok.state, ok.source) == (cp.FIELD_OK, cp.SOURCE_MEMORY)
    assert "阿澜" in ok.value
    assert build(_Memory(cp.STATE_EMPTY)).state == cp.FIELD_EMPTY
    assert build(None).state == cp.FIELD_FAILED, "读不出既不是没人说话也不是没探测"


def test_group_files_cell_comes_from_the_local_ledger_only() -> None:
    profile = cp.build_profile(
        _qq_group_message(),
        _FakeFetch(_QQ_GROUP_PAYLOAD),
        group_file_summary="群文件：我见过 3 个上传",
        clock=_clock,
    )
    field = profile.get("files")
    assert (field.state, field.source) == (cp.FIELD_OK, cp.SOURCE_LEDGER)
    assert field.value == "群文件：我见过 3 个上传"
    empty = cp.build_profile(_qq_group_message(), _FakeFetch(_QQ_GROUP_PAYLOAD), clock=_clock)
    assert empty.get("files").state == cp.FIELD_MISSING, "没账本＝这一段缺行，不编数"


# ---------------------------------------------------------------------------
# ⑤ 缓存与一期共用同一批 kind（同一次问话不该打两遍协议）
# ---------------------------------------------------------------------------


class _FakeApi:
    """一期 ``api`` 桥的签名：``api(action, **params) -> payload``（失败回 ``None``）。"""

    def __init__(self, payloads: dict[str, Any], *, fail: set[str] = frozenset()) -> None:
        self.payloads = payloads
        self.fail = set(fail)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, action: str, **params: Any) -> Any:
        self.calls.append((action, params))
        if action in self.fail or action not in self.payloads:
            return None
        return self.payloads[action]


def test_profile_shares_the_cache_kinds_with_the_first_wave() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import group_cache as gc

    cache = cp.make_shared_cache(clock=_clock)
    api = _FakeApi(_QQ_GROUP_PAYLOAD)
    ok, payload = cp.fetch_through_cache(cache, api, gc.KIND_PROFILE, "12345", "get_group_info")
    assert ok and payload == _QQ_GROUP_PAYLOAD["get_group_info"]
    ok2, _ = cp.fetch_through_cache(cache, api, gc.KIND_PROFILE, "12345", "get_group_info")
    assert ok2
    assert len(api.calls) == 1, "同 kind 同键必须命中缓存——两期各打一遍是第二份账"


def test_failure_is_never_cached() -> None:
    """一期原则的结构版：失败不落缓存，否则「接口这会儿没回应」会被钉死十分钟。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import group_cache as gc

    cache = cp.make_shared_cache(clock=_clock)
    api = _FakeApi(_QQ_GROUP_PAYLOAD, fail={"get_group_info"})
    ok, _payload = cp.fetch_through_cache(cache, api, gc.KIND_PROFILE, "12345", "get_group_info")
    assert not ok
    live = _FakeApi(_QQ_GROUP_PAYLOAD)
    ok2, payload2 = cp.fetch_through_cache(cache, live, gc.KIND_PROFILE, "12345", "get_group_info")
    assert ok2 and payload2["group_name"] == "看海观测站"


def test_profile_builds_cells_through_the_same_cache() -> None:
    """缓存的尺子要量**协议口**：第二轮重建画像允许重走读口，但一次协议都不许再打。

    画像层每轮新建一个 ``_Ctx``——事件格与记忆格必须按轮重算，它的同轮去重记忆只在一轮
    之内有效；**跨轮**的「不重打」是 ``GroupInfoCache`` 的职责。所以本锁断言的是
    ``raw.calls``（真协议）在第二轮不再增长，而不是问话层的穿透次数。
    这条同时兜住「新 kind 忘了登记 TTL」：未登记＝TTL 0＝永不缓存＝第二轮必重打。
    """
    raw = _FakeApi(_QQ_GROUP_PAYLOAD)
    cache = cp.make_shared_cache(clock=_clock)
    probes: list[tuple[str, str, str]] = []

    def counting_fetch(kind: str, key: str, action: str, **params: Any) -> tuple[bool, Any]:
        probes.append((kind, key, action))
        return cp.fetch_through_cache(cache, raw, kind, key, action, **params)

    cp.build_profile(_qq_group_message(), counting_fetch, clock=_clock)
    first_round = list(probes)
    api_after_first = list(raw.calls)
    cp.build_profile(_qq_group_message(), counting_fetch, clock=_clock)
    replayed = raw.calls[len(api_after_first):]

    # ① 第一轮确实把协议格铺开了——否则 ② 会靠「一次都没打」空过。
    assert {action for _kind, _key, action in first_round} >= {
        "get_group_info",
        "get_group_member_list",
        gi.QQ_ACCOUNT_META_ACTION,
    }, first_round
    # ② 第二轮一格都没重打协议（重打清单非空即红，且点名是哪几枚）。
    assert replayed == [], f"同一份缓存里已落成的 kind 在第二轮重打了协议：{replayed}"
    assert raw.calls == api_after_first, "协议端调用数必须跨轮不变"
    assert raw.calls.count(("get_group_info", {"group_id": 12345})) == 1


# ---------------------------------------------------------------------------
# ⑥ Telegram / Mail 同权：缺席格要说清是「结构没有」还是「我没接」
# ---------------------------------------------------------------------------


def _tg_message(**over: Any) -> IncomingMessage:
    data: dict[str, Any] = {
        "platform": "telegram",
        "adapter": "telegram",
        "bot_id": "bot",
        "session_id": "group_-1001234567890",
        "session_type": SessionType.GROUP,
        "sender_id": "555",
        "group_id": "-1001234567890",
        "sender_display_name": "阿澜",
        "plain_text": "群资料",
    }
    data.update(over)
    return IncomingMessage(**data)


_TG_PAYLOAD: dict[str, Any] = {
    "get_chat": {"title": "观测站", "description": "看海", "pinned_message": {"text": "本周直播"}},
    "get_chat_member_count": {"result": 30},
    "get_chat_member": {"status": "member", "user": {"first_name": "阿澜", "id": 555}},
    "get_chat_administrators": [
        {"status": "creator", "user": {"first_name": "站主", "id": 1}, "custom_title": "站长"}
    ],
}


def test_telegram_group_profile_reads_what_the_bot_api_opens_and_absents_the_rest() -> None:
    fetch = _FakeFetch(_TG_PAYLOAD)
    profile = cp.build_profile(_tg_message(), fetch, clock=_clock)
    by_key = {field.key: field for field in profile.fields}
    assert by_key["group_name"].value == "观测站"
    assert by_key["group_memo"].value == "看海"
    assert by_key["owner"].state == cp.FIELD_OK and "站主" in by_key["owner"].value
    assert by_key["member_count"].value == "30"
    assert by_key["online_status"].state == cp.FIELD_ABSENT, "TG 在线态是结构没有，不是没去查"
    assert "Bot API" in by_key["online_status"].reason
    for key in ("essence_count", "album", "todo", "files"):
        assert by_key[key].state == cp.FIELD_ABSENT, key
    # 成员全量名单：Bot API 没有导出口 ⇒ absent，且理由与「按裁定不接」分得开。
    assert by_key["member_roster"].state == cp.FIELD_ABSENT
    assert "Bot API" in by_key["member_roster"].reason


def test_mail_profile_separates_structural_absence_from_unwired_ingest() -> None:
    message = IncomingMessage(
        platform="email",
        adapter="mail",
        bot_id="reader@example.com",
        session_id="lee@example.com",
        session_type=SessionType.EMAIL,
        sender_id="lee@example.com",
        plain_text="群资料",
    )
    profile = cp.build_profile(message, _never_fetch, clock=_clock)
    by_key = {field.key: field for field in profile.fields}
    assert by_key["account_id"].value == "lee@example.com"
    assert by_key["mail_recipients"].state == cp.FIELD_MISSING
    assert "T-META-INGEST-1" in by_key["mail_recipients"].reason, "可拿没接要留票号"
    assert by_key["mail_bcc"].state == cp.FIELD_ABSENT
    assert "投递语义" in by_key["mail_bcc"].reason
    assert by_key["group_name"].state == cp.FIELD_ABSENT
    group_name = by_key["group_name"]
    # 术语按本仓出站规矩用「」引起来：「群」是被点名的对象，不是话术里的一个子串。
    assert "邮件没有「群」" in group_name.reason, group_name.reason
    # 结构性缺席与「摄取未接」是两判：这一格的理由既不许带摄取票号，也不许说成没去查。
    assert "T-META-INGEST" not in group_name.reason, group_name.reason
    assert cp.NOTE_UNPROBED_LINE not in group_name.reason, group_name.reason
    assert by_key["online_status"].state == cp.FIELD_ABSENT


# ---------------------------------------------------------------------------
# ⑦ 一期真身收敛：读件只有一份，group_info 仍在原名下可解析
# ---------------------------------------------------------------------------


def test_group_info_still_exposes_the_moved_read_kit() -> None:
    """采集件搬进画像层后，一期的名字必须还能从 ``group_info`` 解析到**同一个对象**。

    锁的是「别搬出第二份实现」：搬成两份＝两处的状态表早晚打架，正是本仓忌的形态。
    """
    assert gi.read_qq_account_meta is cp.read_qq_account_meta
    assert gi.qq_meta_probe_state is cp.qq_meta_probe_state
    assert gi.QQ_ACCOUNT_META_ACTION == cp.QQ_ACCOUNT_META_ACTION
    assert gi.KIND_QQ_ACCOUNT_META == cp.KIND_QQ_ACCOUNT_META
    assert gi._QQ_META_LABELS is cp.QQ_META_LABELS
    assert gi.QQ_META_UNPROBED_ANSWER == cp.QQ_META_UNPROBED_ANSWER


def test_profile_signature_cell_uses_the_moved_kit_with_the_same_key() -> None:
    """画像层与一期打同一个缓存键（``qq:{uid}``），否则同一份资料会被问两遍。"""
    fetch = _FakeFetch(_QQ_GROUP_PAYLOAD)
    profile = cp.build_profile(_qq_group_message(), fetch, clock=_clock)
    assert profile.get("signature").value == "今天也在看海"
    keys = [key for _kind, key, action, _p in fetch.calls if action == gi.QQ_ACCOUNT_META_ACTION]
    assert len(keys) >= 1 and all(k == "qq:3007" for k in keys), keys
    assert fetch.actions.count(gi.QQ_ACCOUNT_META_ACTION) == 1, "同一次采集里对端资料只许问一遍"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
