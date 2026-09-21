"""E2 组审计修复回归：订阅系统 + 能力层域（离线，monkeypatch 网络/时间）。

覆盖：
- E2-1 订阅 remove 的归属与管理员校验（非创建会话拒绝/创建会话成功）
- E2-2 scheduler 单目标异常不中止整轮轮询；租约兜底不回写 next_poll_at
- E2-3 outbox state='sending' 陈旧行被 claim 回收（投递崩溃自愈）
- E2-4 游标过滤数值化：上游删除游标条目后旧内容不再重复产出
- E2-5 Twitter 凭据发现拿齐即 break
- E2-6 点歌 ALL_PARTS 含音频文件部件
- E2-7 天气触发收窄：日常感慨不路由，真实城市仍路由；群聊查不到静默
- E2-8 吃什么触发收窄：无关句不路由，合法约束句路由
- E2-12 订阅 add 未支持参数显式拒绝
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.eat import is_eat_command
from plugins.bot_unified_runtime.capabilities.music import (
    ALL_PARTS,
    parse_music_mode_spec,
)
from plugins.bot_unified_runtime.capabilities.subscribe_v2 import (
    build_subscribe_capability_v2,
)
from plugins.bot_unified_runtime.capabilities.weather import (
    build_weather_capability,
    is_weather_command,
)
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SendPolicy,
    SessionType,
    SubscriptionDestinationV2,
)
from plugins.bot_unified_runtime.domains.core.contracts.subscription import (
    ContentReference,
    SubscriptionCursorV2,
    SubscriptionFetchResult,
    SubscriptionTarget,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_scheduler import (
    PlatformThrottle,
    SubscriptionScheduler,
)
from plugins.bot_unified_runtime.domains.subscribe.store.subscription_store_v2 import (
    SubscriptionStoreV2,
)
from plugins.bot_unified_runtime.sources.subscriptions.social_v2 import (
    TwitterGraphQLClient,
    WeiboSubscriptionAdapterV2,
    _reached_cursor,
)

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _target(target_id: str) -> SubscriptionTarget:
    return SubscriptionTarget(
        id=target_id,
        platform=target_id.split(":", 1)[0],
        target_kind="channel",
        target_key=target_id.rsplit(":", 1)[-1],
        base_interval_seconds=300,
        jitter_ratio=0.20,
        next_poll_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _group_message(
    text: str,
    *,
    group_id: str,
    sender_id: str,
    roles: list[str] | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=f"group:{group_id}",
        session_type=SessionType.GROUP,
        group_id=group_id,
        sender_id=sender_id,
        sender_roles=roles if roles is not None else ["user"],
        plain_text=text,
    )


def _private_message(text: str, *, sender_id: str = "user1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=f"private:{sender_id}",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
    )


# ---------------------------------------------------------------- E2-1


def test_e2_1_remove_denied_without_session_destination(tmp_path) -> None:
    """非创建会话（无本会话 destination）remove 被拒；目的地群管理员可删。"""
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    config = SimpleNamespace(bot_admin_user_ids=["999"])
    capability = build_subscribe_capability_v2(store=store, adapters=[], config=config)
    target_id = "youtube:channel:UC1"
    store.upsert_target(_target(target_id))
    store.add_destination(
        SubscriptionDestinationV2(
            id="",
            target_id=target_id,
            transport="onebot.v11",
            scope="group",
            destination_id="g1",
            bot_id="bot",
        )
    )

    # 其他群成员：即使身处订阅目的地群，也不是管理员 → 拒绝。
    denied_same_group = capability(
        _group_message(f"订阅 remove {target_id}", group_id="g1", sender_id="111"),
        None,
    )
    assert "没有权限" in denied_same_group.body
    assert store.get_target(target_id) is not None

    # 无关群（没有本会话 destination）→ 即使是管理员也拒绝。
    denied_other_group = capability(
        _group_message(f"订阅 remove {target_id}", group_id="g2", sender_id="111"),
        None,
    )
    assert "没有权限" in denied_other_group.body
    denied_admin_other_group = capability(
        _group_message(
            f"订阅 remove {target_id}",
            group_id="g2",
            sender_id="999",
            roles=["admin", "user"],
        ),
        None,
    )
    assert "没有权限" in denied_admin_other_group.body
    assert store.get_target(target_id) is not None

    # 目的地群内的管理员 → 删除成功。
    removed = capability(
        _group_message(
            f"订阅 remove {target_id}",
            group_id="g1",
            sender_id="999",
            roles=["admin", "user"],
        ),
        None,
    )
    assert "已删除" in removed.body
    assert store.get_target(target_id) is None
    store.close()


# ---------------------------------------------------------------- E2-2


class _BoomAdapter:
    platform = "boom"
    target_kinds = frozenset({"channel"})

    async def fetch_incremental(self, target, cursors, context):
        raise KeyError("escape-the-old-narrow-except")


class _OkAdapter:
    platform = "ok"
    target_kinds = frozenset({"channel"})

    def __init__(self) -> None:
        self.calls = 0

    async def fetch_incremental(self, target, cursors, context):
        self.calls += 1
        return SubscriptionFetchResult(
            items=[
                ContentReference(
                    item_id=f"v{self.calls}",
                    item_kind="video",
                    url=f"https://example.test/v{self.calls}",
                )
            ]
        )


def test_e2_2_key_error_in_one_target_does_not_block_rest_of_round(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    boom = _BoomAdapter()
    ok = _OkAdapter()
    # boom 的 id 排在 ok 前，确保异常发生在同一轮更早的位置。
    store.upsert_target(_target("boom:channel:1"))
    store.upsert_target(_target("ok:channel:2"))
    scheduler = SubscriptionScheduler(
        store,
        [boom, ok],
        random_fn=lambda: 0.0,
        clock=lambda: _NOW,
        throttle=PlatformThrottle(min_interval_seconds=0.0),
    )
    asyncio.run(scheduler.poll_due_once())

    # 同轮后续 target 仍被轮询（旧实现 KeyError 逃逸会中止整轮）。
    assert ok.calls == 1
    # 第二轮 ok 正常产出事件，说明其状态机未被 boom 的异常拖坏。
    store.release_target("ok:channel:2", next_poll_at=_NOW)
    events = asyncio.run(scheduler.poll_due_once())
    assert ok.calls == 2
    assert [event.item.item_id for event in events] == ["v2"]
    # 异常目标按 failure 记账：健康态、退避、租约清空。
    failed = store.get_target("boom:channel:1")
    assert failed is not None
    assert failed.failure_count == 1
    assert failed.health_state == "network_error"
    assert failed.lease_until is None
    assert failed.next_poll_at is not None and failed.next_poll_at > _NOW
    store.close()


def test_e2_2_fallback_lease_release_keeps_next_poll_at(tmp_path) -> None:
    """兜底释放只清租约，不回写 next_poll_at（退避不被过期时间重置）。"""
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    store.upsert_target(_target("boom:channel:1"))
    assert store.claim_due_target("boom:channel:1", _NOW, lease_seconds=120)
    held = store.get_target("boom:channel:1")
    assert held is not None and held.lease_until is not None
    original_next_poll = held.next_poll_at

    store.release_target_lease("boom:channel:1")
    released = store.get_target("boom:channel:1")
    assert released is not None
    assert released.lease_until is None
    assert released.next_poll_at == original_next_poll
    store.close()


# ---------------------------------------------------------------- E2-3


def test_e2_3_stale_sending_outbox_row_is_reclaimed(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    target = _target("ok:channel:9")
    store.upsert_target(target)
    baseline = store.save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id="1", item_kind="video", url="u1")]
        ),
        baseline=True,
    )
    assert baseline == []
    events = store.save_fetch_result(
        target,
        SubscriptionFetchResult(
            items=[ContentReference(item_id="2", item_kind="video", url="u2")]
        ),
        baseline=False,
    )
    assert len(events) == 1

    # save_fetch_result 用真实时钟写 next_attempt_at，claim 时刻取其后。
    moment = datetime.now(timezone.utc) + timedelta(seconds=1)
    claimed = store.claim_outbox(moment, limit=10)
    assert len(claimed) == 1
    event = claimed[0]
    assert store.outbox_state(event.event_id) == "sending"

    # 模拟投递中崩溃：不调用 mark_*。超过 stale 窗口后 claim 必须回收该行。
    reclaimed = store.claim_outbox(moment + timedelta(seconds=301), limit=10)
    assert [item.event_id for item in reclaimed] == [event.event_id]
    assert reclaimed[0].attempts == event.attempts + 1

    # 刚 claim 过的行在 stale 窗口内不会被重复回收（防双发）。
    assert store.claim_outbox(moment + timedelta(seconds=302), limit=10) == []
    store.close()


# ---------------------------------------------------------------- E2-4


def test_e2_4_numeric_cursor_stops_after_deletion() -> None:
    assert _reached_cursor("300", "200") is False
    assert _reached_cursor("200", "200") is True
    assert _reached_cursor("100", "200") is True
    # 非数值 id（BV 号等）保留相等语义。
    assert _reached_cursor("BV1abc", "200") is False
    assert _reached_cursor("BV1abc", "BV1abc") is True
    assert _reached_cursor("300", "") is False


def test_e2_4_weibo_deleted_cursor_item_does_not_reemit_old_page(
    tmp_path, monkeypatch
) -> None:
    """previous=200 且 200 已被上游删除：只剩 300/100 时不再重复产出 100。"""
    payload = {
        "data": {
            "cards": [
                {"mblog": {"id": "300", "text_raw": "new"}},
                {"mblog": {"id": "100", "text_raw": "old"}},
            ]
        }
    }
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.parsers.http_util.http_get_json",
        lambda *args, **kwargs: payload,
    )
    adapter = WeiboSubscriptionAdapterV2()
    target = _target("weibo:creator:42")
    cursors = {
        "status": SubscriptionCursorV2(
            target_id=target.id,
            stream="status",
            last_item_id="200",
            updated_at=_NOW,
        )
    }
    result = asyncio.run(adapter.fetch_incremental(target, cursors, {}))
    assert [item.item_id for item in result.items] == ["300"]
    assert result.cursors[0].last_item_id == "300"


# ---------------------------------------------------------------- E2-5


def test_e2_5_twitter_credential_discovery_stops_early() -> None:
    page = (
        "<html><script src='/a.js'></script>"
        "<script src='/b.js'></script><script src='/c.js'></script></html>"
    )
    bundle = (
        'queryId:"q-user",operationName:"UserByScreenName";'
        'queryId:"q-tweets",operationName:"UserTweets";'
        "AAAAabcdefghijklmnopqrstuvwxyz1234567890"
    )
    calls: list[str] = []

    def fake_text_getter(url, **kwargs):
        calls.append(url)
        if url == "https://x.com/":
            return "", page
        if url.endswith("/a.js"):
            return "", bundle
        return "", "irrelevant"

    client = TwitterGraphQLClient(
        json_getter=lambda *a, **k: {}, text_getter=fake_text_getter
    )
    bearer, operations = client._discover_web_credentials(
        proxy="", timeout=1.0, cookie=""
    )
    # 第一个 bundle 已拿齐 bearer + 两个 queryId：只下载 1 个 JS，不再串行全部。
    assert len(calls) == 2  # 首页 + 1 个 bundle
    assert bearer.startswith("AAAA")
    assert operations["UserByScreenName"] == "q-user"
    assert operations["UserTweets"] == "q-tweets"


# ---------------------------------------------------------------- E2-6


def test_e2_6_all_parts_includes_audio_file() -> None:
    assert "file" in ALL_PARTS
    parts = parse_music_mode_spec("全部")
    assert parts is not None
    assert {"card", "voice", "file", "link"} <= parts


# ---------------------------------------------------------------- E2-7


def test_e2_7_weather_colloquial_sentences_do_not_route() -> None:
    assert is_weather_command("天气真好") is False
    assert is_weather_command("天气 真好") is False
    assert is_weather_command("天气热死了") is False
    assert is_weather_command("天气怎么样") is False
    assert is_weather_command("天气" + "很" * 25) is False
    assert is_weather_command("天气不错啊") is False


def test_e2_7_weather_real_cities_still_route() -> None:
    assert is_weather_command("天气 上海") is True
    assert is_weather_command("天气 河北-大城") is True
    assert is_weather_command("天气 太原") is True
    assert is_weather_command("天气 那曲") is True
    assert is_weather_command("天气 哈尔滨") is True
    assert is_weather_command("weather Tokyo") is True


def test_e2_7_weather_not_found_silent_in_group_error_in_private(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.weather.capabilities.weather.nmc_weather_query",
        lambda query, proxy="": None,
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.domains.weather.capabilities.weather.open_meteo_query",
        lambda query, proxy="": None,
    )
    capability = build_weather_capability(config=None, render_backend=None)

    group_result = capability(
        _group_message("天气 nowhereland", group_id="g1", sender_id="u1"), None
    )
    assert group_result.send_policy is SendPolicy.SILENT_AUDIT
    assert group_result.body == ""

    private_result = capability(_private_message("天气 nowhereland"), None)
    assert "没有查到" in private_result.body


# ---------------------------------------------------------------- E2-8


def test_e2_8_eat_unrelated_sentences_do_not_route() -> None:
    assert is_eat_command("吃了吗") is False
    assert is_eat_command("吃火锅") is False
    assert is_eat_command("吃过饭再去") is False


def test_e2_8_eat_legitimate_requests_still_route() -> None:
    assert is_eat_command("吃什么") is True
    assert is_eat_command("吃啥") is True
    assert is_eat_command("今天吃什么 三选一") is True
    assert is_eat_command("吃什么 再来一道") is True
    assert is_eat_command("吃什么 不辣") is True
    assert is_eat_command("吃什么 不吃香菜 有鸡蛋") is True
    assert is_eat_command("吃什么啊") is True


# ---------------------------------------------------------------- E2-12


def test_e2_12_subscribe_add_rejects_unsupported_extra_options(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    config = SimpleNamespace(bot_admin_user_ids=[])
    capability = build_subscribe_capability_v2(store=store, adapters=[], config=config)
    result = capability(
        _private_message("订阅 add https://www.youtube.com/channel/UC1 私聊我 --digest"),
        None,
    )
    assert "暂不支持" in result.body
    assert "私聊我" in result.body
    assert store.get_target("youtube:channel:UC1") is None
    store.close()
