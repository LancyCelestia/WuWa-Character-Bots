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
import threading
from datetime import datetime, timezone

import pytest

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    HELP_ENTRIES,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.group_info import (
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
    KIND_PROFILE,
    MEMBER_TTL_SECONDS,
    NOTICE_TTL_SECONDS,
    PROFILE_TTL_SECONDS,
    GroupInfoCache,
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
