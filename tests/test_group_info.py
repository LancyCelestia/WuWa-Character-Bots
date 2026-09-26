"""群信息能力回归锁（bot.group_info，审查 B-01/B-04，2026-09-14 新能力）。

覆盖（任务书六门）：
①缓存命中不打二次 API；②TTL 过期重拉（注入时钟）；
③全员/管理员分级（公告/精华仅管理员；私聊回提示）；
④API 失败降级不编造（失败不落缓存、可重试）；
⑤router 触发矩阵（≥8 命中 + ≥2 不命中）；
⑥帮助与 command-catalog 一致性。

诚实降级清单同锁：群链接/群分享、群等级/群标签、群相册——协议无标准 API，
不做不假装；成员名单不整列（隐私+防刷屏）。全离线 mock，零网络。
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    HELP_ENTRIES,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.group_info import (
    _INTENT_OF_WORD,
    _MAIL_PARTIAL_LINE,
    _PARTICIPANT_BASIS_LINE,
    _PARTICIPANT_EMPTY_LINE,
    _PARTICIPANT_UNNAMED,
    _PARTICIPANT_UNREADABLE_LINE,
    _SECTION_LINE_LIMIT,
    _TG_NO_SECTION_LINE,
    GROUP_INFO_TRIGGER_WORDS,
    build_group_info_capability,
    build_onebot_api_bridge,
    detect_group_info_intents,
    is_group_info_command,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
    RouteKind,
    classify_message_route,
    clear_route_decision_cache,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.group_cache import (
    ESSENCE_TTL_SECONDS,
    KIND_PARTICIPANTS,
    KIND_PROFILE,
    MEMBER_TTL_SECONDS,
    NOTICE_TTL_SECONDS,
    PARTICIPANT_TTL_SECONDS,
    PROFILE_TTL_SECONDS,
    GroupInfoCache,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.participant_memory import (
    REASON_DB_DISABLED,
    REASON_DB_MISSING,
    STATE_EMPTY,
    STATE_OK,
    HistoryParticipantReader,
    ParticipantMemory,
    ParticipantScope,
    build_participant_reader,
    group_participant_scope,
    session_participant_scope,
)

# ---------------------------------------------------------------------------
# 假件：可计数的群 API + 可调时钟
# ---------------------------------------------------------------------------


class _FakeGroupApi:
    """按 action 返回罐头载荷并计数；fail_actions 里的 action 直接抛错。"""

    def __init__(self, *, fail_actions: set[str] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_actions = fail_actions or set()

    def __call__(self, action: str, **params: object) -> object:
        self.calls.append((action, dict(params)))
        if action in self.fail_actions:
            raise RuntimeError("onebot bridge down")
        return self.payload(action)

    def payload(self, action: str) -> object:
        if action == "get_group_info":
            return {
                "group_id": 12345,
                "group_name": "泰缇斯观察站",
                "member_count": 48,
                "max_member_count": 200,
            }
        if action == "get_group_member_list":
            return [
                {"user_id": 111, "nickname": "群主大人", "card": "站主", "role": "owner"},
                {"user_id": 222, "nickname": "管理A", "card": "", "role": "admin"},
                {"user_id": 333, "nickname": "管理B", "card": "", "role": "admin"},
                {"user_id": 444, "nickname": "路人", "card": "潜水的", "role": "member"},
            ]
        if action == "get_group_notice":
            return [
                {
                    "notice_id": "n1",
                    "sender_id": 111,
                    "message": {"text": "本周五晚八点群直播，不见不散。\n第二条不要看。"},
                }
            ]
        if action == "get_essence_msg_list":
            return [{"message_id": i} for i in range(7)]
        raise AssertionError(f"unexpected action: {action}")


class _TickClock:
    """可手拨的单调钟（TTL 过期测试用）。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _message(**overrides: object) -> IncomingMessage:
    fields: dict[str, object] = {
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "bot",
        "session_id": "group_12345",
        "session_type": SessionType.GROUP,
        "sender_id": "444",
        "sender_roles": ["user"],
        "group_id": "12345",
        "plain_text": "群信息",
        "raw_segments": [],
    }
    fields.update(overrides)
    return IncomingMessage(**fields)  # type: ignore[arg-type]


def _capability(api: _FakeGroupApi, clock: _TickClock | None = None) -> object:
    cache = GroupInfoCache(clock=clock or _TickClock())
    return build_group_info_capability(api=api, cache=cache)


# ---------------------------------------------------------------------------
# ① 缓存命中不打二次 API
# ---------------------------------------------------------------------------


def test_cache_hit_no_second_api_call() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    first = cap(_message(plain_text="群人数"), None)
    second = cap(_message(plain_text="群人数"), None)
    assert len(api.calls) == 1  # 两次提问只打一次 get_group_info
    assert "人数：48/200" in first.body
    assert "人数：48/200" in second.body


def test_full_view_hits_each_kind_once() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    cap(_message(plain_text="群信息"), None)  # admin 视角另测；这里 user 视角
    actions = sorted(action for action, _ in api.calls)
    assert actions == ["get_group_info", "get_group_member_list"]  # user 无公告/精华


# ---------------------------------------------------------------------------
# ② TTL 过期重拉（注入时钟）
# ---------------------------------------------------------------------------


def test_ttl_constants_match_task_spec() -> None:
    assert PROFILE_TTL_SECONDS == 600.0
    assert MEMBER_TTL_SECONDS == 900.0
    assert NOTICE_TTL_SECONDS == 600.0
    assert ESSENCE_TTL_SECONDS == 600.0


def test_profile_ttl_expiry_refetches() -> None:
    api = _FakeGroupApi()
    clock = _TickClock()
    cache = GroupInfoCache(clock=clock)
    cap = build_group_info_capability(api=api, cache=cache)
    cap(_message(plain_text="群人数"), None)
    clock.advance(PROFILE_TTL_SECONDS - 1)
    cap(_message(plain_text="群人数"), None)
    assert len(api.calls) == 1  # 未到期：命中
    clock.advance(1)
    cap(_message(plain_text="群人数"), None)
    assert len(api.calls) == 2  # 恰好到期：重拉
    # 群号入键：不同群互不共享缓存。
    cap(_message(plain_text="群人数", group_id="999"), None)
    assert len(api.calls) == 3


def test_member_ttl_900s_window() -> None:
    api = _FakeGroupApi()
    clock = _TickClock()
    cache = GroupInfoCache(clock=clock)
    cap = build_group_info_capability(api=api, cache=cache)
    cap(_message(plain_text="群主是谁"), None)
    clock.advance(MEMBER_TTL_SECONDS - 1)
    cap(_message(plain_text="群主是谁"), None)
    assert len(api.calls) == 1
    clock.advance(1)
    cap(_message(plain_text="群主是谁"), None)
    assert len(api.calls) == 2


def test_failed_fetch_not_cached_so_retryable() -> None:
    api = _FakeGroupApi(fail_actions={"get_group_info"})
    cap = _capability(api)
    cap(_message(plain_text="群人数"), None)
    cap(_message(plain_text="群人数"), None)
    assert len(api.calls) == 2  # 失败不落缓存：每次都可重试，不被失败态钉死


# ---------------------------------------------------------------------------
# ③ 全员/管理员分级 + 私聊提示
# ---------------------------------------------------------------------------


def test_notice_requires_admin() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    result = cap(_message(plain_text="群公告", sender_roles=["user"]), None)
    assert "管理员" in result.body
    assert api.calls == []  # 越权直接被门拦下，不打协议
    assert "denied_role" in result.audit_tags


def test_essence_requires_admin() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    result = cap(_message(plain_text="群精华", sender_roles=["trusted"]), None)
    assert "管理员" in result.body
    assert api.calls == []


def test_admin_gets_notice_and_essence() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    result = cap(_message(plain_text="群公告", sender_roles=["admin"]), None)
    assert "本周五晚八点群直播，不见不散。" in result.body
    assert "第二条不要看" not in result.body  # 只给首段
    result2 = cap(_message(plain_text="群精华", sender_roles=["admin"]), None)
    assert "7 条" in result2.body


def test_full_view_admin_view_includes_privileged_lines() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    result = cap(_message(plain_text="群信息", sender_roles=["admin"]), None)
    assert "群名：泰缇斯观察站" in result.body
    assert "群主：站主（111）" in result.body
    assert "人数：48/200" in result.body
    assert "管理员：2 人" in result.body
    assert "公告：" in result.body
    assert "精华：一共收了 7 条。" in result.body


def test_full_view_user_view_omits_privileged_lines() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    result = cap(_message(plain_text="群信息", sender_roles=["user"]), None)
    assert "公告：" not in result.body
    assert "精华：" not in result.body
    assert "人数：48/200" in result.body  # 全员面照常


def test_private_chat_gets_hint_not_data() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    result = cap(
        _message(session_type=SessionType.PRIVATE, group_id=None, plain_text="群信息"),
        None,
    )
    assert "群里" in result.body
    assert "泰缇斯观察站" not in result.body
    assert api.calls == []


def test_member_list_never_dumped() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    result = cap(_message(plain_text="群信息", sender_roles=["admin"]), None)
    assert "路人" not in result.body  # 成员名单不整列（隐私红线）
    assert "管理A" not in result.body


# ---------------------------------------------------------------------------
# ④ API 失败降级不编造
# ---------------------------------------------------------------------------


def test_api_failure_degrades_without_fabrication() -> None:
    api = _FakeGroupApi(fail_actions={"get_group_info", "get_group_member_list"})
    cap = _capability(api)
    result = cap(_message(plain_text="群信息", sender_roles=["admin"]), None)
    assert "没回应" in result.body
    assert "泰缇斯观察站" not in result.body
    assert "48" not in result.body  # 不编人数
    assert "站主" not in result.body  # 不编群主


def test_notice_failure_vs_empty_distinguished() -> None:
    api = _FakeGroupApi(fail_actions={"get_group_notice"})
    cap = _capability(api)
    failed = cap(_message(plain_text="群公告", sender_roles=["admin"]), None)
    assert "没回应" in failed.body
    empty_api = _FakeGroupApi()
    empty_api.payload = lambda action: []  # type: ignore[method-assign]
    cap2 = _capability(empty_api)
    empty = cap2(_message(plain_text="群公告", sender_roles=["admin"]), None)
    assert "还没有公告" in empty.body  # 「为空」与「失败」分开说，不混


def test_group_age_honest_without_protocol_field() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    result = cap(_message(plain_text="本群多大了"), None)
    assert "答不了" in result.body  # 无建群时间字段：如实说，不编


def test_group_age_computed_when_field_present() -> None:
    api = _FakeGroupApi()
    original = api.payload

    def with_create_time(action: str) -> object:
        if action == "get_group_info":
            base = dict(original(action))  # type: ignore[arg-type]
            base["group_create_time"] = int(
                datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp()
            )
            return base
        return original(action)

    api.payload = with_create_time  # type: ignore[method-assign]
    cap = _capability(api)
    result = cap(
        _message(
            plain_text="本群多大了",
            timestamp=datetime(2026, 9, 14, tzinfo=timezone.utc),
        ),
        None,
    )
    assert "100 天" in result.body  # 2026-06-06 → 2026-09-14 = 100 天


def test_unwired_api_degrades_honestly() -> None:
    cap = build_group_info_capability(api=None, cache=GroupInfoCache())
    result = cap(_message(plain_text="群人数"), None)
    assert "没回应" in result.body  # 未接线与失败同路：诚实降级，不装


def test_notice_snippet_truncated() -> None:
    api = _FakeGroupApi()
    original = api.payload

    def long_notice(action: str) -> object:
        if action == "get_group_notice":
            return [
                {"message": {"text": "长" * 130 + "\n次段"}}
            ]
        return original(action)

    api.payload = long_notice  # type: ignore[method-assign]
    cap = _capability(api)
    result = cap(_message(plain_text="群公告", sender_roles=["admin"]), None)
    assert "…" in result.body
    assert "次段" not in result.body  # 首段之外不泄露


# ---------------------------------------------------------------------------
# ⑤ router 触发矩阵（≥8 命中 + ≥2 不命中）
# ---------------------------------------------------------------------------


class _DefaultConfig:
    """路由开关走 base_router 的 getattr 默认值（默认启用语义）。"""


def _route(text: str) -> object:
    clear_route_decision_cache()
    return classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)


@pytest.mark.parametrize(
    "text",
    [
        "群信息",
        "本群信息",
        "群资料",
        "群主是谁",
        "谁是群主",
        "群主",
        "群人数",
        "本群多少人",
        "本群多大了",
        "本群多大了呢",  # 语气助词边界
        "群公告",
        "群精华",
        "精华消息",
    ],
)
def test_router_hits(text: str) -> None:
    decision = _route(text)
    assert decision.kind is RouteKind.GROUP_INFO, text
    assert decision.capability_id == "bot.group_info"


@pytest.mark.parametrize(
    "text",
    [
        "群主管是谁",  # 胶合包含词：不触发（落 moegirl_question/聊天，不劫持）
        "群信息表整理好了",
        "收藏",
        "天气 杭州",
    ],
)
def test_router_misses(text: str) -> None:
    decision = _route(text)
    assert decision.kind is not RouteKind.GROUP_INFO, text


def test_trigger_word_registry_nonempty() -> None:
    assert len(GROUP_INFO_TRIGGER_WORDS) >= 10
    assert is_group_info_command("群公告！") is True
    assert is_group_info_command("查群人数") is False  # 前缀锚定，不中间命中


def test_intent_detection() -> None:
    assert detect_group_info_intents("群主是谁") == frozenset({"owner"})
    assert detect_group_info_intents("群人数") == frozenset({"count"})
    assert detect_group_info_intents("本群多大了") == frozenset({"age"})
    assert detect_group_info_intents("群公告") == frozenset({"notice"})
    assert detect_group_info_intents("群精华") == frozenset({"essence"})
    assert detect_group_info_intents("群信息") == frozenset({"profile"})


# ---------------------------------------------------------------------------
# ⑥ 帮助与 command-catalog 一致性
# ---------------------------------------------------------------------------


def test_help_topic_registered_and_merged() -> None:
    entries = {str(entry["topic"]): entry for entry in HELP_ENTRIES}
    entry = entries["群信息"]
    assert entry.get("capability") == "bot.group_info"  # META 已并入
    assert entry.get("admin_only") is False  # 群资料面全员
    assert "群主是谁" in entry["aliases"]


def test_commands_catalog_contains_group_info() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        build_commands_catalog_body,
    )

    body = build_commands_catalog_body(is_admin=True)
    assert "bot.group_info" in body
    assert "41 | group_info | bot.group_info" in body  # [routes] 行：priority|kind|capability
    assert "\n群信息 | " in body  # 命令清单行


def test_onebot_api_bridge_roundtrip() -> None:
    """跨线程桥接（主会话 __init__.py 装配将用此工具）。"""
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    ready.wait(5)

    class _Bot:
        async def call_api(self, action: str, **params: object) -> dict:
            await asyncio.sleep(0)
            return {"action": action, **params}

    try:
        bridge = build_onebot_api_bridge(_Bot(), loop, timeout=5.0)
        payload = bridge("get_group_info", group_id=12345)
        assert payload["action"] == "get_group_info"
        assert payload["group_id"] == 12345
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()


def test_cache_kind_constants_and_put_none_noop() -> None:
    clock = _TickClock()
    cache = GroupInfoCache(clock=clock)
    cache.put(KIND_PROFILE, "1", None)
    assert cache.get(KIND_PROFILE, "1") == (False, None)  # 失败载荷绝不落缓存
    cache.put(KIND_PROFILE, "1", {"ok": 1})
    assert cache.get(KIND_PROFILE, "1") == (True, {"ok": 1})
    cache.clear()
    assert cache.get(KIND_PROFILE, "1") == (False, None)


def test_capability_silent_skip_without_trigger() -> None:
    api = _FakeGroupApi()
    cap = _capability(api)
    result = cap(_message(plain_text="今天天气不错"), None)
    assert result.body == ""
    assert result.send_policy is SendPolicy.SILENT_AUDIT
    assert "skip_no_trigger" in result.audit_tags
    assert api.calls == []


# ---------------------------------------------------------------------------
# ⑥ 第 4 项（会话事实直答）：动作册真名、群号自带、群介绍落地
# ---------------------------------------------------------------------------


class _SnowLumaOnlyApi(_FakeGroupApi):
    """照 SnowLuma 1.14.19 的动作册办事：公告只有 ``_get_group_notice`` 这个真名。

    ``get_group_notice`` 在它注册的 189 枚动作里**不存在**——旧代码直译 V11 常见名
    过去，每问必失败再被兜成「接口这会儿没回应」，所以这里让旧名真的报错，
    锁的就是「先试真名」这一手（把它退回旧单名，本用例当场红）。
    """

    def payload(self, action: str) -> object:
        if action == "_get_group_notice":
            return super().payload("get_group_notice")
        if action == "get_group_notice":
            raise RuntimeError("action not registered")
        return super().payload(action)


def test_notice_uses_protocol_native_action_name() -> None:
    api = _SnowLumaOnlyApi()
    cap = _capability(api)
    result = cap(
        _message(plain_text="群公告", sender_roles=["admin"]), None
    )
    assert "公告：本周五晚八点群直播" in result.body, result.body
    called = [action for action, _params in api.calls]
    assert "_get_group_notice" in called


def test_notice_falls_back_to_v11_name_on_other_protocols() -> None:
    """别的协议端只认 V11 常见名时也要拿得到——真名失败必须退回旧名重试。"""
    api = _FakeGroupApi()  # 本 fake 只应答 get_group_notice
    cap = _capability(api)
    result = cap(_message(plain_text="群公告", sender_roles=["admin"]), None)
    assert "公告：本周五晚八点群直播" in result.body
    called = [action for action, _params in api.calls]
    assert called.count("_get_group_notice") == 1  # 试过真名
    assert called.count("get_group_notice") == 1  # 再退回常见名


def test_group_id_is_reported_even_when_profile_api_fails() -> None:
    """群号来自事件本身，不靠接口回显：接口挂了也答得出来自己在哪个群。"""
    api = _FakeGroupApi(fail_actions={"get_group_info"})
    cap = _capability(api)
    result = cap(_message(plain_text="群信息"), None)
    assert "群号：12345" in result.body


def test_group_memo_renders_as_introduction() -> None:
    class _MemoApi(_FakeGroupApi):
        def payload(self, action: str) -> object:
            data = super().payload(action)
            if action == "get_group_info" and isinstance(data, dict):
                return {**data, "group_memo": "守岸人剧情讨论与情报整理，禁止剧透。"}
            return data

    result = _capability(_MemoApi())(_message(plain_text="群信息"), None)
    assert "群介绍：守岸人剧情讨论与情报整理，禁止剧透。" in result.body


# ---------------------------------------------------------------------------
# 第 4 项二批：问话人身份（群昵称/群头衔/身份）与群文件本地账本
# ---------------------------------------------------------------------------


class _IdentityApi(_FakeGroupApi):
    """成员表按行覆写（验 title 缺字段、未知 role 两形态）。"""

    def __init__(self, member_overrides: list[dict[str, object]]) -> None:
        super().__init__()
        self._member_overrides = member_overrides

    def payload(self, action: str) -> object:
        if action == "get_group_member_list":
            return list(self._member_overrides)
        return super().payload(action)


def _cap_with_store(api: object, *, group_file_store: object | None = None) -> object:
    return build_group_info_capability(
        api=api,  # type: ignore[arg-type]
        cache=GroupInfoCache(clock=_TickClock()),
        group_file_store=group_file_store,
    )


class _StubFileStore:
    def __init__(self, *, body: str = "", raises: bool = False) -> None:
        self._body = body
        self._raises = raises
        self.seen: list[tuple[str, int]] = []

    def summary(self, group_id: str, *, limit: int = 10) -> str:
        self.seen.append((group_id, limit))
        if self._raises:
            raise RuntimeError("locked db")
        return self._body


def test_profile_reports_asker_identity_and_title() -> None:
    api = _IdentityApi(
        [
            {"user_id": 111, "nickname": "群主大人", "card": "站主", "role": "owner"},
            {"user_id": 444, "nickname": "路人", "card": "潜水的", "role": "member", "title": "巡海人"},
        ]
    )
    body = _cap_with_store(api)(_message(plain_text="群信息"), None).body
    assert "你在这里：潜水的（群成员）" in body
    assert "群头衔：巡海人" in body


def test_missing_title_field_says_not_returned_not_absent() -> None:
    """协议回空与未回是两件事：字段不在 ⇒ 说「没回这个字段」，不替用户下结论。"""
    body = _cap_with_store(_FakeGroupApi())(_message(plain_text="群信息"), None).body
    assert "群头衔：这次接口没回这个字段" in body
    assert "没有头衔" not in body


def test_unknown_role_never_claims_privilege() -> None:
    api = _IdentityApi([{"user_id": 444, "nickname": "游客", "card": "", "role": "visitor"}])
    body = _cap_with_store(api)(_message(plain_text="群信息"), None).body
    assert "你在这里：游客（群成员）" in body
    assert "（管理员）" not in body and "（群主）" not in body


def test_identity_block_does_not_dump_other_members() -> None:
    """隐私红线：加了身份段也不能把别人的昵称带出来。"""
    body = _cap_with_store(_FakeGroupApi())(_message(plain_text="群信息"), None).body
    assert "管理A" not in body and "管理B" not in body and "群主大人" not in body


def test_group_files_section_uses_local_ledger() -> None:
    store = _StubFileStore(body="群文件概览（共记录 3 个，最近 2 个）｜类型分布：文档×2\n· 攻略.md（12KB）")
    cap = _cap_with_store(_FakeGroupApi(), group_file_store=store)
    body = cap(_message(plain_text="群信息"), None).body
    assert "群文件概览（共记录 3 个" in body
    assert store.seen == [("12345", 5)]


def test_group_files_section_absent_when_store_not_injected() -> None:
    """缺数=缺行：没注入账本时这一段整段不出现，也不谎报「群文件读不到」。"""
    body = _cap_with_store(_FakeGroupApi())(_message(plain_text="群信息"), None).body
    assert "群文件" not in body


def test_group_files_ledger_failure_stays_honest_and_keeps_rest() -> None:
    store = _StubFileStore(raises=True)
    cap = _cap_with_store(_FakeGroupApi(), group_file_store=store)
    body = cap(_message(plain_text="群信息", sender_roles=["admin"]), None).body
    assert "群文件：账本读不出内容" in body
    assert "群名：泰缇斯观察站" in body  # 账本炸了不许带走整份群资料


def test_group_files_not_fetched_for_narrow_intents() -> None:
    store = _StubFileStore(body="不该出现")
    cap = _cap_with_store(_FakeGroupApi(), group_file_store=store)
    body = cap(_message(plain_text="群人数"), None).body
    assert "群文件" not in body and store.seen == []


# ---------------------------------------------------------------------------
# 第 4 项二批 · Telegram 侧同理（chat.id 为负数 + TG 动作名 + 结构差异诚实说）
# ---------------------------------------------------------------------------


class _TelegramApi:
    """按 TG Bot API 动作名回罐头；``calls`` 用来证明没拿 QQ 的动作名去打 TG。"""

    def __init__(self, *, chat: object = None, count: object = 42, member: object = None, fail: set[str] | None = None) -> None:
        self.chat = {"title": "潮汐观测组", "description": "剧情与情报整理。"} if chat is None else chat
        self.count = count
        self.member = {"status": "administrator", "custom_title": "观测站长", "user": {"first_name": "澜汐"}} if member is None else member
        self.fail = fail or set()
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, action: str, **params: object) -> object:
        self.calls.append((action, dict(params)))
        if action in self.fail:
            raise RuntimeError("telegram api down")
        if action == "get_chat":
            return self.chat
        if action == "get_chat_member_count":
            return self.count
        if action == "get_chat_member":
            return self.member
        raise AssertionError(f"TG 侧不该打这个动作：{action}")

    def actions(self) -> list[str]:
        return [action for action, _params in self.calls]


def _tg_message(**overrides: object) -> IncomingMessage:
    fields: dict[str, object] = {
        "platform": "telegram",
        "adapter": "telegram",
        "bot_id": "bot",
        "session_id": "group_-1001234567890_555",
        "session_type": SessionType.GROUP,
        "sender_id": "555",
        "sender_roles": ["user"],
        "group_id": "-1001234567890",
        "plain_text": "群信息",
        "raw_segments": [],
    }
    fields.update(overrides)
    return IncomingMessage(**fields)  # type: ignore[arg-type]


def _tg_cap(api: _TelegramApi) -> object:
    return build_group_info_capability(api=api, cache=GroupInfoCache(clock=_TickClock()))


def test_negative_telegram_chat_id_is_not_rejected() -> None:
    """旧判定 isdigit() 把负数 chat.id 判死 ⇒ TG 上这条能力永远「没拿到群号」。"""
    body = _tg_cap(_TelegramApi())(_tg_message(), None).body
    assert "群号：-1001234567890" in body
    assert "没拿到群号" not in body


def test_telegram_readout_maps_chat_fields_and_my_identity() -> None:
    api = _TelegramApi()
    body = _tg_cap(api)(_tg_message(), None).body
    assert "群名：潮汐观测组" in body
    assert "群介绍：剧情与情报整理。" in body
    assert "人数：42" in body
    assert "你在这里：澜汐（管理员）" in body
    assert "群头衔：观测站长" in body
    assert ("get_chat", {"chat_id": -1001234567890}) in api.calls
    assert ("get_chat_member", {"chat_id": -1001234567890, "user_id": 555}) in api.calls
    assert "get_group_info" not in api.actions()  # 绝不拿 QQ 动作名去打 TG


def test_telegram_pinned_message_is_the_notice_slot() -> None:
    api = _TelegramApi(chat={"title": "T", "pinned_message": {"text": "本周六晚八点连麦。\n别看第二条。"}})
    body = _tg_cap(api)(_tg_message(plain_text="群公告", sender_roles=["admin"]), None).body
    assert "置顶（本群公告位）：本周六晚八点连麦。" in body


def test_telegram_declares_structurally_missing_sections_without_guessing() -> None:
    body = _tg_cap(_TelegramApi())(_tg_message(), None).body
    assert "Telegram 的 Bot API 不开放成员名单" in body
    assert "精华 / 群文件 / 相册" in body
    assert "群主：" not in body and "精华：" not in body  # 不编数


def test_telegram_unknown_status_never_claims_privilege() -> None:
    api = _TelegramApi(member={"status": "sorcery", "user": {"first_name": "X"}})
    body = _tg_cap(api)(_tg_message(), None).body
    assert "你在这里：X（成员）" in body
    identity_line = next(line for line in body.splitlines() if line.startswith("你在这里"))
    assert "管理员" not in identity_line and "群主" not in identity_line


def test_telegram_pydantic_shaped_payload_still_reads() -> None:
    class _Model:
        def model_dump(self) -> dict[str, object]:
            return {"title": "模型形态", "description": "照读"}

    body = _tg_cap(_TelegramApi(chat=_Model()))(_tg_message(), None).body
    assert "群名：模型形态" in body and "群介绍：照读" in body


def test_telegram_api_failure_degrades_to_one_honest_line() -> None:
    api = _TelegramApi(fail={"get_chat", "get_chat_member_count", "get_chat_member"})
    result = _tg_cap(api)(_tg_message(), None)
    assert "群号：-1001234567890" in result.body
    assert "群资料接口这会儿没回应" in result.body
    assert "人数：0" not in result.body and "群名：" not in result.body


def test_telegram_uses_its_own_cache_kinds_and_hits_once_each() -> None:
    """三类载荷各占一个缓存 kind：与 QQ 的 members 混键会互相覆盖成假数据。"""
    api = _TelegramApi()
    cap = _tg_cap(api)
    cap(_tg_message(), None)
    cap(_tg_message(), None)
    assert api.actions().count("get_chat") == 1
    assert api.actions().count("get_chat_member_count") == 1
    assert api.actions().count("get_chat_member") == 1


def test_telegram_narrow_intent_skips_the_unasked_calls() -> None:
    api = _TelegramApi()
    _tg_cap(api)(_tg_message(plain_text="群人数"), None)
    assert api.actions() == ["get_chat_member_count"]


# ---------------------------------------------------------------------------
# ⑦ 群相册 / 群待办（第 4 项二批接线：动作在册、此前一直没接）
# ---------------------------------------------------------------------------


def _snowluma_album(name: str, pics: int) -> dict[str, object]:
    """按 SnowLuma 1.14.19 **实回形态**构造一条相册记录。

    字段名现算自协议端自带包体（证据全文见
    ``.superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-ALBUMNUM.md``）：
    ACTION_REGISTRY 里 ``get_group_album_list`` 的 returnsSchema 要求
    id/name/picNum/createTime/last_upload_time/cover/createuin/createnickname
    八枚必给，``toLegacyAlbum``（index.mjs）另回可选的 desc/owner。
    旧夹具用的 ``albumname``/``total_pic_count`` 是**猜名**——测试全绿而
    现网每条相册都渲染成「照片数这次没回」，根因就在这。主形夹具只准用真名。
    """
    return {
        "id": f"album-{pics}",
        "name": name,
        "picNum": pics,
        "createTime": 1_700_000_000,
        "last_upload_time": 1_720_000_000,
        "cover": None,
        "createuin": "10001",
        "createnickname": "守岸人",
        "desc": "",
        "owner": "10001",
    }


class _AlbumTodoApi(_FakeGroupApi):
    """在共享假件上补两类载荷；``underscore_only`` 用来验两试顺序。"""

    def __init__(
        self,
        *,
        albums: object = None,
        todos: object = None,
        fail_actions: set[str] | None = None,
    ) -> None:
        super().__init__(fail_actions=fail_actions)
        self._albums = [
            _snowluma_album("潮汐摄影", 12),
            _snowluma_album("剧情截图", 30),
            _snowluma_album("同人收集", 5),
        ] if albums is None else albums
        self._todos = [
            {"title": "周五晚八点直播", "sender_id": 111},
            {"title": "补齐舰桥值班表"},
        ] if todos is None else todos

    def payload(self, action: str) -> object:
        if action in {"get_group_album_list", "_get_group_album_list"}:
            return self._albums
        if action in {"get_group_todo_list", "_get_group_todo_list"}:
            return self._todos
        return super().payload(action)


def _album_cap(api: _AlbumTodoApi, text: str):
    cap = _capability(api)
    return cap(_message(plain_text=text), None)


def test_album_intent_names_each_album_without_photo_urls() -> None:
    body = _album_cap(_AlbumTodoApi(), "群相册").body
    assert "群相册：3 个相册" in body
    assert "潮汐摄影：12 张" in body
    # 隐私红线同成员名单：只到相册这一层，不落单张照片的地址
    assert "http" not in body.lower()
    assert "pic_url" not in body.lower()


def test_album_over_limit_says_remaining_count_explicitly() -> None:
    """静默截断＝谎报「本群就这些」，超出条数必须点名。"""
    albums = [_snowluma_album(f"相册{i}", i) for i in range(7)]
    body = _album_cap(_AlbumTodoApi(albums=albums), "群相册").body
    assert "群相册：7 个相册" in body
    assert "另有 2 个相册未列出" in body


def test_album_with_unreadable_fields_degrades_to_count_only() -> None:
    """字段名认不出来时只报条数，绝不编一个相册名或张数出来。"""
    albums = [{"mystery": "x"}, {"name": "认得出的那个"}]
    body = _album_cap(_AlbumTodoApi(albums=albums), "群相册").body
    assert "（这个相册名字段读不出）" in body
    assert "认得出的那个：照片数这次没回" in body


def test_album_snowluma_real_shape_photo_count_is_read() -> None:
    """反脆弱锁（2026-09-25 实锤缺陷的同型锁）：喂 SnowLuma **实回形态**的一条
    相册记录（``picNum``＝协议端 ACTION_REGISTRY 真名），产出文案里必须
    出现真实张数，且**不得**出现「照片数这次没回」。

    写这枚锁前的实况：候选表里整表没有 ``picNum``，而夹具用的是自猜键名
    （``total_pic_count`` 一族）——测试全绿、现网每条相册全部渲染成
    「照片数这次没回」，与 echo.py 帮助承诺的「哪个相册多少张」相反。
    把 ``picNum`` 从 _ALBUM_PIC_COUNT_KEYS 摘掉，这枚当场红（变异已实跑）；
    把主形夹具换回猜名，这枚也红——两条绿路只留真名这一条。
    """
    albums = [_snowluma_album("星图集锦", 42)]
    body = _album_cap(_AlbumTodoApi(albums=albums), "群相册").body
    assert "星图集锦：42 张" in body
    assert "照片数这次没回" not in body
    assert "（这个相册名字段读不出）" not in body


def test_album_legacy_guessed_keys_still_read_as_compat() -> None:
    """旧猜键名**降格保留**为「兼容旧形态」用例（不是主形，也不是死键）。

    真名进表首位后，``albumname``/``total_pic_count`` 这些历史兼容名仍在
    候选表里；这一枚锁住「旧形态数据依旧读得出」。SnowLuma 1.14.19 的实回
    里根本没有这组键——若后续波次要摘除兼容名，摘前这枚会红，逼它点名。
    主路径的行为判据**不**由本用例承担（那是上一枚真名脆锁的职责）。
    """
    albums = [{"albumname": "旧形态兼容", "total_pic_count": 7}]
    body = _album_cap(_AlbumTodoApi(albums=albums), "群相册").body
    assert "旧形态兼容：7 张" in body
    assert "照片数这次没回" not in body


def test_album_falls_back_to_underscore_action_name() -> None:
    """裸名不被协议端认得时退本名（``_get_group_notice`` 那次的同型教训）。"""
    api = _AlbumTodoApi(fail_actions={"get_group_album_list"})
    body = _album_cap(api, "群相册").body
    actions = [action for action, _ in api.calls]
    assert "get_group_album_list" in actions
    assert "_get_group_album_list" in actions
    assert "群相册：3 个相册" in body


def test_album_failure_says_not_answered_not_empty() -> None:
    """「没答上」与「没有相册」必须分得开——后者是对全群的一句断言。"""
    api = _AlbumTodoApi(
        fail_actions={"get_group_album_list", "_get_group_album_list"}
    )
    body = _album_cap(api, "群相册").body
    assert "没答上" in body
    assert "目前没有相册" not in body


def test_empty_album_list_says_none_now() -> None:
    body = _album_cap(_AlbumTodoApi(albums=[]), "群相册").body
    assert "这个群目前没有相册" in body


def test_todo_intent_lists_titles() -> None:
    body = _album_cap(_AlbumTodoApi(), "群待办").body
    assert "群待办：2 条" in body
    assert "周五晚八点直播" in body
    assert "补齐舰桥值班表" in body


def test_todo_item_without_readable_title_says_so() -> None:
    body = _album_cap(_AlbumTodoApi(todos=[{"opaque": 1}]), "群待办").body
    assert "这条待办的标题字段读不出" in body
    assert "只能报它还在" in body


def test_todo_over_limit_says_remaining_count() -> None:
    todos = [{"title": f"待办{i}"} for i in range(8)]
    body = _album_cap(_AlbumTodoApi(todos=todos), "群待办").body
    assert "群待办：8 条" in body
    assert "另有 3 条未列出" in body


def test_todo_cache_is_short_lived_by_design() -> None:
    """待办 TTL 刻意比群资料短：刚设好的待办不能被旧表盖住（那不是缓存是谎报）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.group_cache import (
        _DEFAULT_TTL_BY_KIND,
        KIND_ALBUM,
        KIND_TODO,
        TODO_TTL_SECONDS,
    )

    # 未登记 kind 的缺省 TTL 是 0（=永不缓存），漏登记会静默变成「每次现打协议」。
    assert _DEFAULT_TTL_BY_KIND[KIND_TODO] == TODO_TTL_SECONDS
    assert _DEFAULT_TTL_BY_KIND[KIND_ALBUM] > 0
    assert TODO_TTL_SECONDS < PROFILE_TTL_SECONDS


def test_album_and_todo_hit_the_protocol_once_each() -> None:
    api = _AlbumTodoApi()
    cap = _capability(api)
    cap(_message(plain_text="群相册"), None)
    cap(_message(plain_text="群相册"), None)
    assert [action for action, _ in api.calls] == ["get_group_album_list"]
    cap(_message(plain_text="群待办"), None)
    assert [action for action, _ in api.calls] == [
        "get_group_album_list",
        "get_group_todo_list",
    ]


def test_album_intent_does_not_pull_the_member_list() -> None:
    """窄意图只打它那一发——问相册不该顺带把成员表拖出来。"""
    api = _AlbumTodoApi()
    _album_cap(api, "群相册列表")
    assert [action for action, _ in api.calls] == ["get_group_album_list"]


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("群相册", "album"),
        ("本群相册", "album"),
        ("群相册列表", "album"),
        ("群待办", "todo"),
        ("本群待办", "todo"),
        ("群待办列表", "todo"),
    ],
)
def test_album_and_todo_words_route_to_group_info(text: str, intent: str) -> None:
    assert detect_group_info_intents(text) == frozenset({intent})
    assert is_group_info_command(text)
    assert text in GROUP_INFO_TRIGGER_WORDS


@pytest.mark.parametrize("text", ["相册", "待办", "我相册里那张图"])
def test_bare_album_or_todo_words_do_not_trigger(text: str) -> None:
    """裸「相册」「待办」不收——日常对话不该被群务查询劫持。"""
    assert not is_group_info_command(text)


def test_telegram_album_and_todo_say_there_is_no_api() -> None:
    api = _TelegramApi()
    body = _tg_cap(api)(_tg_message(plain_text="群相册"), None).body
    assert "Telegram" in body
    assert "答不了" in body
    assert "待办" in _TG_NO_SECTION_LINE  # 词表与实现同源，别一处改一处漏


# ---------------------------------------------------------------------------
# ⑦ 参与者腿（按记忆算，2026-09-26 S-T-GRP-2）
#
# 这批用例的真身判据：用户裁定「参与者按记忆算」⇒ 回答必须①自带依据句、
# ②自带「名单我没整份读过」的缺口声明、③空记录与读不出分两态（绝不把
# 「我不知道」写成「它没有」，见 commits cd0068c/21bdabf）、④截断必点名且
# 列出+未列=总数守恒、⑤名字只从在册唯一源取、取不到不拿用户号顶上。
# 全离线：SQLite 写在 ``tmp_path`` 里，零网络、零生产库。
# ---------------------------------------------------------------------------

_TURN_DDL = (
    "CREATE TABLE conversation_turns (request_id TEXT, platform TEXT, adapter TEXT,"
    " bot_id TEXT, session_id TEXT, sender_id TEXT, role TEXT, text TEXT,"
    " created_at TEXT, kind TEXT)"
)
_AFFINITY_DDL = (
    "CREATE TABLE group_affinity (group_id TEXT, sender_id TEXT, display_name TEXT,"
    " affinity REAL, interaction_count INTEGER, positive_count INTEGER,"
    " negative_count INTEGER, tease_count INTEGER, insult_count INTEGER,"
    " updated_at TEXT, PRIMARY KEY (group_id, sender_id))"
)


def _write_history(
    tmp_path: Path, rows: list[tuple[str, str, str, str, str]], *, tag: str = "h"
) -> str:
    """建一份临时历史库。``rows`` 每行 =（会话键, 说话人, role, 时刻, kind）。"""
    path = tmp_path / f"{tag}.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(_TURN_DDL)
        connection.executemany(
            "INSERT INTO conversation_turns VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                ("r", "qq", "onebot", "bot", session_id, sender_id, role, "内容", created_at, kind)
                for session_id, sender_id, role, created_at, kind in rows
            ],
        )
    return str(path)


def _write_affinity(
    tmp_path: Path, names: dict[str, str], *, group_id: str = "12345", tag: str = "a"
) -> str:
    """建一份临时好感库，只灌 ``group_affinity`` 的名字列（评分列留缺省）。"""
    path = tmp_path / f"{tag}.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(_AFFINITY_DDL)
        connection.executemany(
            "INSERT INTO group_affinity (group_id, sender_id, display_name, updated_at)"
            " VALUES (?,?,?,'')",
            [(group_id, sender_id, name) for sender_id, name in names.items()],
        )
    return str(path)


def _reader(
    tmp_path: Path,
    rows: list[tuple[str, str, str, str, str]],
    names: dict[str, str] | None = None,
    *,
    tag: str = "h",
    **kwargs: object,
) -> HistoryParticipantReader:
    affinity = (
        _write_affinity(tmp_path, names or {}, tag=f"{tag}a") if names is not None else ""
    )
    return HistoryParticipantReader(
        history_db_path=_write_history(tmp_path, rows, tag=tag),
        affinity_db_path=affinity,
        **kwargs,  # type: ignore[arg-type]
    )


class _CountingReader:
    """包一层真读数件，只为了数「打了几次库」（缓存判据要可观测才测得动）。"""

    def __init__(self, inner: HistoryParticipantReader) -> None:
        self.inner = inner
        self.reads = 0

    def read(self, scope: ParticipantScope | None) -> ParticipantMemory:
        self.reads += 1
        return self.inner.read(scope)


class _FakeHistoryConfig:
    """只带参与者腿用到的那三枚字段（与 ``config.py`` 同名同义）。"""

    def __init__(self, *, enabled: bool, history: str, affinity: str = "") -> None:
        self.bot_history_enabled = enabled
        self.bot_history_db_path = history
        self.bot_affinity_db_path = affinity


def _who_cap(
    reader: HistoryParticipantReader | _CountingReader | None = None,
    api: Callable[[str], Any] | None = None,
) -> Callable[[IncomingMessage, Any], CapabilityResult]:
    return build_group_info_capability(
        None,
        api=api,
        cache=GroupInfoCache(clock=_TickClock()),
        participant_reader=reader,  # type: ignore[arg-type]
    )


def _three_speaker_rows() -> list[tuple[str, str, str, str, str]]:
    return [
        ("group_12345_111", "111", "user", "2026-09-26T01:00:00Z", "chat"),
        ("group_12345_111", "111", "user", "2026-09-26T01:05:00Z", "chat"),
        ("group_12345_222", "222", "user", "2026-09-26T02:00:00Z", "chat"),
        ("group_12345_111", "111", "assistant", "2026-09-26T02:10:00Z", "chat"),
        ("group_12345_333", "333", "user", "2026-09-26T02:20:00Z", "command"),
        ("group_99999_888", "888", "user", "2026-09-26T02:30:00Z", "chat"),
    ]


def test_participants_derived_from_injected_history(tmp_path: Path) -> None:
    """派生集＝注入历史里真说过话的人，名字从好感库那唯一一枚列取。"""
    reader = _reader(
        tmp_path, _three_speaker_rows(), {"111": "阿澜", "222": "霞月"}
    )
    body = _who_cap(reader)(_message(plain_text="群参与者"), None).body
    assert "记到说过话的 2 位" in body
    assert "阿澜（说过 2 句）" in body
    assert "霞月（说过 1 句）" in body


def test_participants_statement_carries_basis_and_gap(tmp_path: Path) -> None:
    """依据句与缺口句必须在场——缺一句，「2 位」就会被当成群成员全量。"""
    body = _who_cap(_reader(tmp_path, _three_speaker_rows(), {"111": "阿澜"}))(
        _message(plain_text="群里都有谁"), None
    ).body
    assert _PARTICIPANT_BASIS_LINE in body
    assert "不是群成员名单" in body
    assert "名单我没整份读过" in body


def test_participants_exclude_bot_and_command_rows(tmp_path: Path) -> None:
    """机器人自己（assistant）与命令轮（kind=command）都不算「这个人说过话」。"""
    body = _who_cap(_reader(tmp_path, _three_speaker_rows(), {}))(
        _message(plain_text="群参与者"), None
    ).body
    assert "记到说过话的 2 位" in body  # 111 与 222，不是 4 行
    assert "888" not in body  # 别的群的人绝不串进来


def test_participants_do_not_leak_other_group_or_prefix_neighbor(tmp_path: Path) -> None:
    """串群即隐私事故：``group_123_`` 不得吞下 ``group_12345_`` 的人。"""
    reader = _reader(tmp_path, _three_speaker_rows(), {"111": "阿澜"})
    neighbor = reader.read(group_participant_scope("123"))
    assert neighbor.state == STATE_EMPTY and neighbor.total_speakers == 0
    whole = reader.read(group_participant_scope("12345"))
    assert whole.state == STATE_OK and whole.total_speakers == 2


def test_private_scope_never_widens_to_prefix_match(tmp_path: Path) -> None:
    """私聊走**等值**键：前缀形会把 ``386506762`` 的屋子并进 ``3865067623`` 的。

    这条锁守的是「读数件不许对私聊放宽」这一设计决定——放宽一次就是别人的私聊
    出现在我的参与者回答里，且不会有任何报错。
    """
    rows = [("3865067623", "3865067623", "user", "2026-09-26T01:00:00Z", "chat")]
    reader = _reader(tmp_path, rows, {}, tag="priv")
    assert reader.read(session_participant_scope("386506762")).total_speakers == 0
    exact = reader.read(session_participant_scope("3865067623"))
    assert exact.state == STATE_OK and exact.total_speakers == 1


def test_participant_cap_is_conserved_and_named(tmp_path: Path) -> None:
    """截断必点名「另有 N 位未列出」，且 已列 + 未列 == 实算总数。"""
    rows = [
        (f"group_12345_900{i}", f"900{i}", "user", f"2026-09-26T0{1 + i}:00:00Z", "chat")
        for i in range(8)
    ]
    reader = _reader(tmp_path, rows, {})
    body = _who_cap(reader)(_message(plain_text="群参与者"), None).body
    listed = [line for line in body.splitlines() if line.startswith("　· ")]
    assert len(listed) == _SECTION_LINE_LIMIT
    omitted = int(body.split("另有 ")[1].split(" 位未列出")[0])
    assert len(listed) + omitted == 8
    assert "记到说过话的 8 位" in body


def test_participant_names_never_fall_back_to_user_id(tmp_path: Path) -> None:
    """取不到名字就说取不到；群里贴一串 QQ 号既没用又伤人。"""
    body = _who_cap(_reader(tmp_path, _three_speaker_rows(), {}))(
        _message(plain_text="群参与者"), None
    ).body
    assert _PARTICIPANT_UNNAMED in body
    assert "111" not in body and "222" not in body


def test_participants_empty_says_no_record_not_that_group_is_empty(tmp_path: Path) -> None:
    """空态：说「我这儿还没有记录」，**不得**说「这个群没有人」。"""
    reader = _reader(tmp_path, [("group_77777_111", "111", "assistant", "2026-09-26T01:00:00Z", "chat")], {})
    result = _who_cap(reader)(_message(plain_text="群参与者", group_id="77777", session_id="group_77777_111"), None)
    assert STATE_EMPTY in result.audit_tags
    assert _PARTICIPANT_EMPTY_LINE in result.body
    assert "这个群没有人" not in result.body
    assert "群里现在没有" not in result.body


def test_participants_unavailable_is_not_empty(tmp_path: Path) -> None:
    """接口/账本没答上 ≠ 目前没有：两态各一句，且互相不得顶替。"""
    reader = HistoryParticipantReader(
        history_db_path=str(tmp_path / "not-there.sqlite3"), affinity_db_path=""
    )
    result = _who_cap(reader)(_message(plain_text="群参与者"), None)
    assert _PARTICIPANT_UNREADABLE_LINE in result.body
    assert _PARTICIPANT_EMPTY_LINE not in result.body
    assert REASON_DB_MISSING in result.audit_tags


def test_participants_reason_distinguishes_disabled_from_missing(tmp_path: Path) -> None:
    """「这台机器没开记忆」与「账本打不开」在审计面必须分家（运维动作不同）。"""
    off = HistoryParticipantReader(history_db_path="")
    assert off.read(group_participant_scope("12345")).reason == REASON_DB_DISABLED
    gone = HistoryParticipantReader(history_db_path=str(tmp_path / "gone.sqlite3"))
    assert gone.read(group_participant_scope("12345")).reason == REASON_DB_MISSING


def test_unreadable_participants_do_not_kill_other_legs(tmp_path: Path) -> None:
    """这条腿读不出只关这条腿——群号等既有腿照样答。"""
    result = _who_cap(None)(_message(plain_text="群参与者"), None)
    assert _PARTICIPANT_UNREADABLE_LINE in result.body
    assert "群号：12345" in result.body
    assert "reader_absent" in result.audit_tags


def test_participants_reader_self_builds_from_config(tmp_path: Path) -> None:
    """装配点早已按位置传 config ⇒ 不改根文件也能在生產取到数（本腿的上线判据）。"""
    rows = _three_speaker_rows()
    history = _write_history(tmp_path, rows)
    affinity = _write_affinity(tmp_path, {"111": "阿澜"})
    config = _FakeHistoryConfig(enabled=True, history=history, affinity=affinity)
    capability = build_group_info_capability(
        config, api=None, cache=GroupInfoCache(clock=_TickClock())
    )
    body = capability(_message(plain_text="群参与者"), None).body
    assert "阿澜" in body and "记到说过话的 2 位" in body


def test_build_participant_reader_respects_the_write_side_gate() -> None:
    """门与写侧同源：``bot_history_enabled`` 关 ⇒ 不给读数件（不是「屋里没人」）。"""
    assert build_participant_reader(_FakeHistoryConfig(enabled=False, history="x")) is None
    assert build_participant_reader(_FakeHistoryConfig(enabled=True, history="")) is None
    assert build_participant_reader(_FakeHistoryConfig(enabled=True, history="x")) is not None


def test_participants_ok_state_cached_but_empty_state_not(tmp_path: Path) -> None:
    """只缓存「这次真读到人了」：空态落缓存＝把刚开口的第一个人挡在 TTL 外。"""
    ok_counter = _CountingReader(
        _reader(tmp_path, _three_speaker_rows(), {"111": "阿澜"}, tag="ok")
    )
    ok_cap = _who_cap(ok_counter)
    message = _message(plain_text="群参与者")
    ok_cap(message, None)
    ok_cap(message, None)
    assert ok_counter.reads == 1

    empty_counter = _CountingReader(
        _reader(
            tmp_path,
            [("group_77777_111", "111", "assistant", "2026-09-26T01:00:00Z", "chat")],
            {},
            tag="empty",
        )
    )
    empty_cap = _who_cap(empty_counter)
    empty_message = _message(plain_text="群参与者", group_id="77777", session_id="group_77777_111")
    empty_cap(empty_message, None)
    empty_cap(empty_message, None)
    assert empty_counter.reads == 2


def test_participant_cache_kind_is_registered_with_a_ttl() -> None:
    """未登记的 kind 缺省 TTL=0＝永不缓存——新数据类忘了落一行会静默失去缓存。"""
    assert PARTICIPANT_TTL_SECONDS < 120.0  # 比待办还短：记忆每轮都在长
    clock = _TickClock()
    store = GroupInfoCache(clock=clock)
    store.put(KIND_PARTICIPANTS, "group_12345_", "载荷")
    hit, value = store.get(KIND_PARTICIPANTS, "group_12345_")
    assert hit and value == "载荷"
    clock.advance(PARTICIPANT_TTL_SECONDS)
    assert store.get(KIND_PARTICIPANTS, "group_12345_")[0] is False


def test_participants_window_exhaustion_is_declared(tmp_path: Path) -> None:
    """扫到窗口上限必须自报——有界不声明就是谎报「这就是所有人」。"""
    rows = [
        (f"group_12345_900{i}", f"900{i}", "user", f"2026-09-26T0{1 + i}:00:00Z", "chat")
        for i in range(6)
    ]
    reader = _reader(tmp_path, rows, {}, row_window=2)
    memory = reader.read(group_participant_scope("12345"))
    assert memory.window_exhausted is True
    # 窗口里只见到 2 个人 ≠「本群就 2 个人」——正文必须把「更早的没算进来」说出来。
    assert memory.total_speakers == 2
    body = _who_cap(reader)(_message(plain_text="群参与者"), None).body
    assert "只翻了最近 2 条记录" in body


def test_profile_view_does_not_dump_participants(tmp_path: Path) -> None:
    """``who`` 不并入 ``profile`` 全量档：泛问群资料不该顺带列出说话人。"""
    capability = _who_cap(_reader(tmp_path, _three_speaker_rows(), {"111": "阿澜"}), api=_FakeGroupApi())
    body = capability(_message(plain_text="群信息"), None).body
    assert "按记忆算" not in body
    assert _PARTICIPANT_BASIS_LINE not in body


def test_private_participants_are_answered_not_deflected(tmp_path: Path) -> None:
    """私聊等价腿：这条腿读的是我自己的记忆，不需要协议名单，所以不该被「去群里问」挡回。"""
    rows = [("3865067623", "3865067623", "user", "2026-09-26T01:00:00Z", "chat")]
    reader = _reader(tmp_path, rows, {})
    message = _message(
        plain_text="我都跟谁聊过",
        session_type=SessionType.PRIVATE,
        session_id="3865067623",
        group_id=None,
        sender_id="3865067623",
        sender_display_name="阿澜",
    )
    body = _who_cap(reader)(message, None).body
    assert "群信息要在群里问" not in body
    assert "记到说过话的 1 位" in body
    assert "阿澜" in body
    assert "就你一位" in body


def test_private_other_intents_still_get_the_hint() -> None:
    """只放开参与者这一腿：私聊问群资料仍回指路提示（旧行为逐字不变）。"""
    body = _who_cap(None)(_message(plain_text="群信息", session_type=SessionType.PRIVATE), None).body
    assert "群信息要在群里问" in body


def test_mail_participants_declare_structural_gap(tmp_path: Path) -> None:
    """邮件侧诚实降级：只看得见回信人，To/Cc 全集读不到 ⇒ 明说答不全，不假装有 parity。"""
    rows = [("email:lan@example.com", "lan@example.com", "user", "2026-09-26T01:00:00Z", "chat")]
    reader = _reader(tmp_path, rows, {})
    message = _message(
        plain_text="都有谁说过话",
        platform="email",
        adapter="mail",
        session_type=SessionType.EMAIL,
        session_id="email:lan@example.com",
        group_id=None,
        sender_id="lan@example.com",
        sender_display_name="阿澜",
    )
    body = _who_cap(reader)(message, None).body
    assert _MAIL_PARTIAL_LINE in body
    assert "答不全" in body and "不猜" in body
    assert "记到说过话的 1 位" in body


def test_telegram_participants_use_memory_and_reach_parity(tmp_path: Path) -> None:
    """TG 的成员名单 Bot API 不开放，而这条腿不依赖名单 ⇒ 与 QQ 真同权（不是抄答案）。"""
    rows = [("group_-1001234567890_555", "555", "user", "2026-09-26T01:00:00Z", "chat")]
    reader = HistoryParticipantReader(
        history_db_path=_write_history(tmp_path, rows), affinity_db_path=""
    )
    capability = build_group_info_capability(
        None,
        api=_TelegramApi(),
        cache=GroupInfoCache(clock=_TickClock()),
        participant_reader=reader,
    )
    result = capability(_tg_message(plain_text="群参与者"), None)
    assert "群号：-1001234567890" in result.body
    assert "记到说过话的 1 位" in result.body
    assert _PARTICIPANT_BASIS_LINE in result.body
    # 这一项答上了，就不该再出现「名单答不了」那类降级句。
    assert "不开放成员名单" not in result.body


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("群里都有谁", "who"),
        ("本群都有谁", "who"),
        ("群里谁说过话", "who"),
        ("本群谁说过话", "who"),
        ("群参与者", "who"),
        ("本群参与者", "who"),
        ("都有谁说过话", "who"),
        ("我都跟谁聊过", "who"),
        ("跟谁聊过", "who"),
    ],
)
def test_participant_words_route_to_group_info(text: str, intent: str) -> None:
    """新词全走既有谓词入口（``base_router.group_info_match`` 直接调它 ⇒ 零路由改动）。"""
    assert detect_group_info_intents(text) == frozenset({intent})
    assert is_group_info_command(text)
    assert text in GROUP_INFO_TRIGGER_WORDS
    clear_route_decision_cache()
    decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
    assert decision.kind is RouteKind.GROUP_INFO, text
    assert decision.capability_id == "bot.group_info"


@pytest.mark.parametrize(
    ("text",),
    [
        ("这话谁说过",),
        ("查群参与者",),
        ("群里都有谁说过话的吗",),
        ("谁说过话重要吗",),
    ],
)
def test_participant_words_do_not_hijack_ordinary_chat(text: str) -> None:
    """前缀锚定：词在句中/被前缀修饰都不触发（日常问句不该被群务查询劫走）。"""
    assert not is_group_info_command(text)
    clear_route_decision_cache()
    decision = classify_message_route(text, config=_DefaultConfig(), alias_resolver=None)
    assert decision.kind is not RouteKind.GROUP_INFO, text


def test_who_family_words_are_registered_in_the_home_tuple() -> None:
    """词表只在真身一处字面声明（本断言引用常量本身，不复制词集＝不给副本账添债）。"""
    who_words = [
        word for word, intent in _INTENT_OF_WORD.items() if intent == "who"
    ]
    assert len(who_words) == 9
    assert set(who_words).issubset(set(GROUP_INFO_TRIGGER_WORDS))
