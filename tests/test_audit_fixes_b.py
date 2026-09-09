"""B 组审计修复回归（docs/capability-audit-2026-09-10.md P1/P2/P3 B组项）。

命名对应审计编号：test_audit_p1_1_* / test_audit_p2_6_* / test_audit_p3_23_* …
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from plugins.bot_unified_runtime.capabilities import music as music_module
from plugins.bot_unified_runtime.capabilities import runtime_admin as ra
from plugins.bot_unified_runtime.capabilities.content_parser import (
    build_content_capability,
)
from plugins.bot_unified_runtime.capabilities.subscribe import (
    build_subscribe_capability,
    is_standalone_subscribe_command,
)
from plugins.bot_unified_runtime.capabilities.subscribe_v2 import (
    build_subscribe_capability_v2,
)
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SessionType,
    SubscriptionTarget,
    build_parsed_content,
)
from plugins.bot_unified_runtime.contracts.subscription import (
    SubscriptionCursor,
    SubscriptionDestination,
    SubscriptionSpec,
)
from plugins.bot_unified_runtime.runtime.settings import RuntimeSettingsStore
from plugins.bot_unified_runtime.sources.subscription_store import SubscriptionStore
from plugins.bot_unified_runtime.sources.subscription_store_v2 import (
    SubscriptionStoreV2,
)


def _message(
    text: str,
    *,
    sender_id: str = "u1",
    session_type: SessionType = SessionType.PRIVATE,
    group_id: str | None = None,
    roles: list[str] | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=f"{session_type.value}:{group_id or sender_id}",
        session_type=session_type,
        sender_id=sender_id,
        group_id=group_id,
        sender_roles=roles or ["user"],
        plain_text=text,
    )


# ---------------------------------------------------------------- P1 #1
def test_audit_p1_1_priority_move_keeps_env_refs_and_marks_source(tmp_path) -> None:
    """P1#1：priority 落盘只存 env: 引用原文并打 source 标记，明文/快照不烘焙。"""
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    raw_env = {
        "m1": {
            "model": "gpt-x",
            "base_url": "http://a",
            "api_key": "env:BOT_API_KEY_M1",
            "priority": 2,
        }
    }
    body = ra._handle_model_registry_command(store, raw_env, {}, "priority", ["m1", "1"])
    assert "槽位 1" in body
    persisted = store.list_model_registry()
    entry = persisted["m1"]
    assert entry["api_key"] == "env:BOT_API_KEY_M1"
    assert entry["source"] == "env"
    assert entry["priority"] == 1


def test_audit_p1_1_env_changes_not_shadowed_by_runtime_copy(tmp_path) -> None:
    """P1#1 硬约束2：.env 后续改动不被运行时旧副本遮蔽；管理员重排序仍生效。"""
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    raw_env = {
        "m1": {
            "model": "gpt-x",
            "base_url": "http://a",
            "api_key": "env:BOT_API_KEY_M1",
            "priority": 2,
        }
    }
    ra._handle_model_registry_command(store, raw_env, {}, "priority", ["m1", "1"])
    persisted = store.list_model_registry()
    # .env 修改了 base_url 和 key 引用：内容以 .env 为准，priority 保留管理员结果。
    new_env = {
        "m1": {
            "model": "gpt-x",
            "base_url": "http://NEW",
            "api_key": "env:BOT_API_KEY_M2",
            "priority": 5,
        }
    }
    merged = ra._merge_registry_entries(new_env, persisted)
    assert merged["m1"]["base_url"] == "http://NEW"
    assert merged["m1"]["api_key"] == "env:BOT_API_KEY_M2"
    assert merged["m1"]["priority"] == 1
    # .env 删除条目：旧运行时副本不再遮蔽（直接失效）。
    assert "m1" not in ra._merge_registry_entries({}, persisted)


def test_audit_p1_1_admin_update_persists_over_env(tmp_path) -> None:
    """P1#1 硬约束3：管理员 update 的字段持久生效，未改字段仍以 .env 为准。"""
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    raw_env = {
        "m1": {
            "model": "gpt-x",
            "base_url": "http://a",
            "api_key": "env:BOT_API_KEY_M1",
            "priority": 2,
        }
    }
    body = ra._handle_model_registry_command(
        store,
        raw_env,
        store.list_model_registry(),
        "update",
        ["m1", "base_url=http://b", "key=env:BOT_API_KEY_M9"],
    )
    assert "已更新模型" in body
    persisted = store.list_model_registry()["m1"]
    assert persisted["override_fields"] == ["api_key", "base_url"]
    raw_env_edited = {
        "m1": {**raw_env["m1"], "model": "gpt-x2", "base_url": "http://changed"}
    }
    merged = ra._merge_registry_entries(raw_env_edited, store.list_model_registry())
    # 管理员改过的字段生效；未改的 model 以 .env 新值为准。
    assert merged["m1"]["base_url"] == "http://b"
    assert merged["m1"]["api_key"] == "env:BOT_API_KEY_M9"
    assert merged["m1"]["model"] == "gpt-x2"


# ---------------------------------------------------------------- P1 #2
class _V2Adapter:
    """按脚本抛错或返回固定目标的假 resolve adapter。"""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    async def resolve_target(self, raw: str, ctx: dict) -> SubscriptionTarget:
        if self.error is not None:
            raise self.error
        now = datetime.now(timezone.utc)
        return SubscriptionTarget(
            id="test:kind:1",
            platform="test",
            target_kind="kind",
            target_key="1",
            display_name="Demo",
            created_at=now,
            updated_at=now,
        )


def _v2_capability(tmp_path, adapters):
    store = SubscriptionStoreV2(str(tmp_path / "sub.sqlite3"))
    config = SimpleNamespace(bot_admin_user_ids=["admin1"])
    return (
        build_subscribe_capability_v2(store=store, adapters=adapters, config=config),
        store,
    )


def test_audit_p1_2_v2_permissions_readd_and_list_filter(tmp_path) -> None:
    """P1#2：v2 pause/resume/remove 权限校验；list 不泄露；re-add 不改 enabled。"""
    capability, store = _v2_capability(tmp_path, [_V2Adapter()])

    added = capability(_message("订阅 add https://x", sender_id="admin1"), None)
    assert "订阅已添加" in added.body

    # 非目的地用户：操作被拒、list 不泄露。
    denied = capability(
        _message("订阅 pause test:kind:1", sender_id="rand"), None
    )
    assert "没有权限" in denied.body
    leaked = capability(_message("订阅 list", sender_id="rand"), None)
    assert "test:kind:1" not in leaked.body

    # 管理员（目的地本人）暂停后，重加不静默重启。
    paused = capability(_message("订阅 pause test:kind:1", sender_id="admin1"), None)
    assert "已暂停" in paused.body
    assert store.get_target("test:kind:1").enabled is False
    capability(_message("订阅 add https://x", sender_id="admin1"), None)
    assert store.get_target("test:kind:1").enabled is False

    resumed = capability(_message("订阅 resume test:kind:1", sender_id="admin1"), None)
    assert "已恢复" in resumed.body
    assert store.get_target("test:kind:1").enabled is True


# ---------------------------------------------------------------- P1 #3 / #4
def _seed_v1_spec(store: SubscriptionStore) -> str:
    spec_id = "bilibili:user:1"
    store.upsert_spec(
        SubscriptionSpec(
            id=spec_id,
            platform="bilibili",
            target_kind="user",
            target_id="1",
            target_name="UP主",
            destinations=[
                SubscriptionDestination(scope="group", target_id="gA"),
                SubscriptionDestination(scope="group", target_id="gB"),
                SubscriptionDestination(scope="private", target_id="creator"),
            ],
            created_by="creator",
        )
    )
    store.save_cursor(SubscriptionCursor(spec_id=spec_id, last_item_id="x"))
    return spec_id


def _v1_capability(tmp_path):
    registry = SimpleNamespace(
        resolve_target=lambda raw: {
            "platform": "bilibili",
            "target_kind": "user",
            "target_id": "1",
            "target_name": "UP主",
        },
        find=lambda platform: None,
    )
    store = SubscriptionStore(str(tmp_path / "sub.sqlite3"))
    return build_subscribe_capability(store=store, registry=registry, config=None), store


def test_audit_p1_3_v1_remove_pause_only_own_destination(tmp_path) -> None:
    """P1#3：remove/pause 按目的地粒度，最后一个目的地移除才删 spec/游标。"""
    capability, store = _v1_capability(tmp_path)
    spec_id = _seed_v1_spec(store)

    # 群 A 管理员删除：群 B 与私聊目的地保留，游标保留。
    body = capability(
        _message(
            f"/bot subscribe remove {spec_id}",
            sender_id="adminA",
            session_type=SessionType.GROUP,
            group_id="gA",
            roles=["admin"],
        ),
        None,
    )
    assert "已删除" in body.body
    spec = store.get_spec(spec_id)
    assert spec is not None
    remaining = {(d.scope, d.target_id) for d in spec.destinations}
    assert remaining == {("group", "gB"), ("private", "creator")}
    assert store.get_cursor(spec_id) is not None

    # 私聊创建者暂停：只摘自己的私聊目的地，群推送不受影响。
    capability(
        _message(f"/bot subscribe pause {spec_id}", sender_id="creator"), None
    )
    spec = store.get_spec(spec_id)
    assert [(d.scope, d.target_id) for d in spec.destinations] == [("group", "gB")]

    # 群 B 管理员删除最后一个目的地：spec 与游标才被删除。
    capability(
        _message(
            f"/bot subscribe remove {spec_id}",
            sender_id="adminB",
            session_type=SessionType.GROUP,
            group_id="gB",
            roles=["admin"],
        ),
        None,
    )
    assert store.get_spec(spec_id) is None
    assert store.get_cursor(spec_id) is None


def test_audit_p1_4_check_requires_permission(tmp_path) -> None:
    """P1#4：check 与 remove 同权，无关用户不能借 check 枚举他人订阅。"""
    capability, store = _v1_capability(tmp_path)
    spec_id = _seed_v1_spec(store)

    denied = capability(
        _message(f"/bot subscribe check {spec_id}", sender_id="rand"), None
    )
    assert "没有权限" in denied.body

    # 创建者通过权限门（后续因缺 adapter 报“不可用”，说明已过校验）。
    allowed = capability(
        _message(f"/bot subscribe check {spec_id}", sender_id="creator"), None
    )
    assert "没有权限" not in allowed.body


# ---------------------------------------------------------------- P2 #6/#7/#8
def _candidate_message(text: str) -> IncomingMessage:
    return _message(text, sender_id="u1")


def _seed_session(message: IncomingMessage, parser_id: str = "p") -> None:
    """同时按「带/不带 sender 后缀」两种会话键播种，兼容键格式演进。"""
    base = f"{message.session_type.value}:{message.session_id}"
    music_module.clear_music_candidate_sessions()
    for session_key in (base, f"{base}:{message.sender_id}"):
        music_module._CANDIDATE_SESSIONS[session_key] = (
            10_000.0,
            parser_id,
            [
                {"provider_track_id": "1", "name": "晴天", "artist": "周杰伦"},
                {"provider_track_id": "2", "name": "晴天翻唱", "artist": "路人"},
            ],
        )


def test_audit_p2_6_superscript_digit_does_not_crash() -> None:
    """P2#6：「点歌 ²」不再因 isdigit/isdecimal 差异触发 int() 崩溃。"""
    searches: list[str] = []

    def search_fn(query: str):
        searches.append(query)

    capability = music_module.build_music_capability(
        config=SimpleNamespace(bot_music_candidates_enabled=True),
        providers=[("p", "平台", search_fn)],
        candidate_providers={"p": (lambda q: [], lambda cand, query="": None)},
        audio_downloader=lambda url: None,
    )
    result = capability(_candidate_message("点歌 ²"), None)
    assert result is not None
    assert result.body


def test_audit_p2_7_detail_failure_never_searches_by_number() -> None:
    """P2#7：编号详情失败不把编号当歌名去普通搜索。"""
    searches: list[str] = []

    def search_fn(query: str):
        searches.append(query)

    def detail_fn(cand, query=""):
        raise RuntimeError("detail boom")

    capability = music_module.build_music_capability(
        config=SimpleNamespace(bot_music_candidates_enabled=True),
        providers=[("p", "平台", search_fn)],
        candidate_providers={"p": (lambda q: [], detail_fn)},
        audio_downloader=lambda url: None,
    )
    message = _candidate_message("点歌 1")
    _seed_session(message)
    result = capability(message, None)
    assert searches == []
    assert result.kind == "text"
    assert result.body


def test_audit_p2_8_missing_candidate_provider_no_keyerror() -> None:
    """P2#8：能力重建后 candidate_providers 缺平台不再 KeyError。"""
    searches: list[str] = []

    def search_fn(query: str):
        searches.append(query)

    capability = music_module.build_music_capability(
        config=SimpleNamespace(bot_music_candidates_enabled=True),
        providers=[("p", "平台", search_fn)],
        candidate_providers={"other": (lambda q: [], lambda cand, query="": None)},
        audio_downloader=lambda url: None,
    )
    message = _candidate_message("点歌 1")
    _seed_session(message, parser_id="p")
    result = capability(message, None)
    assert searches == []
    assert result.body


# ---------------------------------------------------------------- P2 #10
def _insert_target(store: SubscriptionStoreV2, target_id: str = "t") -> None:
    now = datetime.now(timezone.utc).isoformat()
    with store._lock, store._get_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO subscription_targets
                (id, platform, target_kind, target_key, display_name,
                 target_payload, source_mode, enabled, health_state,
                 base_interval_seconds, jitter_ratio, baseline_initialized,
                 next_poll_at, lease_until, failure_count, backoff_until,
                 created_at, updated_at)
            VALUES (?, 'test', 'kind', 'k', '', '{}', 'pull', 1, 'healthy',
                    300, 0.2, 0, NULL, NULL, 0, NULL, ?, ?)
            """,
            (target_id, now, now),
        )


def _insert_outbox(
    store: SubscriptionStoreV2,
    event_id: str,
    *,
    state: str,
    attempts: int,
    sent_at: datetime | None,
    created_at: datetime,
) -> None:
    with store._lock, store._get_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO subscription_outbox
                (event_id, target_id, item_kind, item_id, reason, payload,
                 state, attempts, next_attempt_at, created_at, sent_at)
            VALUES (?, 't', 'video', ?, 'new_item', ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_id,
                json.dumps(
                    {
                        "item_id": event_id,
                        "item_kind": "video",
                        "url": f"https://example/{event_id}",
                    }
                ),
                state,
                attempts,
                created_at.isoformat(),
                created_at.isoformat(),
                sent_at.isoformat() if sent_at else None,
            ),
        )


def _insert_seen(
    store: SubscriptionStoreV2, item_id: str, discovered_at: datetime
) -> None:
    with store._lock, store._get_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO subscription_seen_items
                (target_id, item_kind, item_id, published_at, discovered_at)
            VALUES ('t', 'video', ?, NULL, ?)
            """,
            (item_id, discovered_at.isoformat()),
        )


def test_audit_p2_10_outbox_sent_retention_seen_ttl_and_dead_letter(tmp_path) -> None:
    """P2#10：sent 行按期裁剪、seen 加 TTL、retry 超限进死信。"""
    store = SubscriptionStoreV2(
        str(tmp_path / "sub.sqlite3"),
        outbox_sent_retention_days=1,
        seen_retention_days=1,
        outbox_max_attempts=2,
    )
    _insert_target(store)
    now = datetime.now(timezone.utc)
    _insert_outbox(
        store, "old-sent", state="sent", attempts=1, sent_at=now - timedelta(days=5), created_at=now - timedelta(days=5)
    )
    _insert_outbox(
        store, "fresh-sent", state="sent", attempts=1, sent_at=now, created_at=now
    )
    _insert_seen(store, "old-seen", now - timedelta(days=5))
    _insert_seen(store, "fresh-seen", now)

    removed = store.prune_stale_rows(force=True)
    assert removed == 2
    with store._lock, store._get_connection() as connection:
        ids = {
            row["event_id"]
            for row in connection.execute("SELECT event_id FROM subscription_outbox")
        }
        seen_ids = {
            row["item_id"]
            for row in connection.execute(
                "SELECT item_id FROM subscription_seen_items"
            )
        }
    assert ids == {"fresh-sent"}
    assert seen_ids == {"fresh-seen"}

    # 死信：attempts 达上限转 dead，claim 不再捞起；未超限的正常重试。
    _insert_outbox(
        store, "dead-event", state="sending", attempts=2, sent_at=None, created_at=now
    )
    _insert_outbox(
        store, "retry-event", state="sending", attempts=1, sent_at=None, created_at=now
    )
    store.mark_outbox_retry("dead-event", now)
    store.mark_outbox_retry("retry-event", now)
    assert store.outbox_state("dead-event") == "dead"
    assert store.outbox_state("retry-event") == "retry"
    claimed = store.claim_outbox(now, limit=10)
    assert [event.event_id for event in claimed] == ["retry-event"]


# ---------------------------------------------------------------- P2 #20
def test_audit_p2_20_probe_reentry_guard(tmp_path) -> None:
    """P2#20：probe 进行中时再次调用只回执提示，不再叠加探针线程。"""
    assert ra._MODEL_PROBE_LOCK.acquire(blocking=False)
    try:
        body = ra._handle_model_command(
            RuntimeSettingsStore(tmp_path / "settings.json"),
            SimpleNamespace(),
            ["probe"],
        )
    finally:
        ra._MODEL_PROBE_LOCK.release()
    assert "进行中" in body


# ---------------------------------------------------------------- P2 #21
class _FakeDiagnosticsStore:
    def __init__(self, records: list) -> None:
        self._records = records

    def list_recent(self, limit: int = 5) -> list:
        return self._records[:limit]


def test_audit_p2_21_usage_pagination_and_bot_timezone(tmp_path) -> None:
    """P2#21：兜底账单分页取到尽头；naive created_at 按 bot 时区解释。"""
    zone = ZoneInfo("Asia/Hong_Kong")
    # naive 时刻：若按 UTC 解释再转 HKT 会跨到第二天，可区分两种行为。
    naive_evening = (
        datetime.now(zone)
        .replace(hour=23, minute=0, second=0, microsecond=0)
        .replace(tzinfo=None)
    )
    records = [
        SimpleNamespace(
            created_at=naive_evening,
            llm_usage_prompt_tokens=1,
            llm_usage_completion_tokens=1,
            llm_usage_total_tokens=2,
            llm_model="m",
        )
        for _ in range(1500)
    ]
    body = ra._handle_model_command(
        RuntimeSettingsStore(tmp_path / "settings.json"),
        SimpleNamespace(bot_timezone="Asia/Hong_Kong", bot_model_prices={}),
        ["usage"],
        diagnostics_store=_FakeDiagnosticsStore(records),
    )
    assert "1,500 次" in body


# ---------------------------------------------------------------- P3 #22
def test_audit_p3_22_candidate_eviction_by_expiry(monkeypatch) -> None:
    """P3#22：容量淘汰按过期时刻，最晚过期者不被误逐出。"""
    monkeypatch.setattr(music_module, "_CANDIDATE_MAX_SESSIONS", 2)
    music_module.clear_music_candidate_sessions()
    # 插入序 c, a, b；最早过期的是 a（插入序第二）。
    music_module._CANDIDATE_SESSIONS.update(
        {
            "c": (200.0, "p", []),
            "a": (100.0, "p", []),
            "b": (300.0, "p", []),
        }
    )
    music_module._prune_candidate_sessions(0.0)
    assert "a" not in music_module._CANDIDATE_SESSIONS
    assert {"c", "b"} == set(music_module._CANDIDATE_SESSIONS)
    music_module.clear_music_candidate_sessions()


# ---------------------------------------------------------------- P3 #23
def test_audit_p3_23_mode_alias_conflict_hint_and_escape() -> None:
    """P3#23：与模式别名同名的歌名给出冲突提示；「点歌 #歌名」可转义搜索。"""
    assert music_module.is_music_command("点歌 link")
    assert music_module.extract_music_query("点歌 #link") == "link"
    assert not music_module.is_music_mode_alias_query("点歌 #link")

    searches: list[str] = []
    item = build_parsed_content(
        platform="netease_music",
        item_id="t1",
        item_kind="music",
        title="link",
        author_name="歌手",
        canonical_url="https://music.example/t1",
    )

    def search_fn(query: str):
        searches.append(query)
        return item

    capability = music_module.build_music_capability(
        config=SimpleNamespace(bot_music_candidates_enabled=False),
        providers=[("netease_music", "网易云", search_fn)],
        audio_downloader=lambda url: None,
    )
    hint = capability(_candidate_message("点歌 link"), None)
    assert "保留词" in hint.body
    assert "点歌 #link" in hint.body
    assert searches == []

    hit = capability(_candidate_message("点歌 #link"), None)
    assert searches == ["link"]
    assert "link" in hit.body


# ---------------------------------------------------------------- P3 #24
def test_audit_p3_24_add_receipt_shows_actual_model_and_vision_effort(tmp_path) -> None:
    """P3#24：add 回执回显 actual_model_id；vision add effort 过 normalize。"""
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    body = ra._handle_model_registry_command(
        store,
        {},
        {},
        "add",
        ["m1", "model=visible-name", "actual_model_id=real-model", "base_url=http://x"],
    )
    assert "real-model" in body
    assert "visible-name" not in body
    assert store.list_model_registry()["m1"]["model"] == "real-model"

    vision_config = SimpleNamespace(
        bot_vision_model_registry={}, bot_vision_enabled=True, bot_vision_mode="relay"
    )
    bad = ra._handle_vision_command(
        store,
        vision_config,
        ["add", "v1", "model=vis", "base_url=http://x", "effort=ultra"],
    )
    assert "effort" in bad
    ok = ra._handle_vision_command(
        store,
        vision_config,
        [
            "add",
            "v1",
            "model=vis",
            "actual_model_id=real-vis",
            "base_url=http://x",
            "effort=high",
        ],
    )
    assert "real-vis" in ok
    assert store.list_vision_registry()["v1"]["effort"] == "high"


# ---------------------------------------------------------------- P3 #25
def test_audit_p3_25_standalone_router_gate() -> None:
    """P3#25：以「订阅」开头的普通句子不再被当订阅命令接管。"""
    assert not is_standalone_subscribe_command("订阅大家的支持")
    assert not is_standalone_subscribe_command("订阅 人数又涨了")
    assert is_standalone_subscribe_command("订阅")
    assert is_standalone_subscribe_command("订阅 list")
    assert is_standalone_subscribe_command("!订阅 添加 https://x")
    assert not is_standalone_subscribe_command("/bot subscribe list")


def test_audit_p3_25_digest_can_be_turned_off(tmp_path) -> None:
    """P3#25：--no-digest 可退出日报；不带开关时保持现状。"""
    capability, store = _v1_capability(tmp_path)

    capability(_message("/bot subscribe add x --digest"), None)
    assert store.get_spec("bilibili:user:1").digest_enabled is True

    # 不带开关：保持现状（仍为日报）。
    capability(_message("/bot subscribe add x"), None)
    assert store.get_spec("bilibili:user:1").digest_enabled is True

    # --no-digest：显式退出日报。
    capability(_message("/bot subscribe add x --no-digest"), None)
    assert store.get_spec("bilibili:user:1").digest_enabled is False


# ---------------------------------------------------------------- P3 #26
def test_audit_p3_26_v2_resolve_error_messages(tmp_path) -> None:
    """P3#26：resolve 失败区分解析错误与运行时错误，None 不再直出。"""
    capability, _store = _v2_capability(
        tmp_path, [_V2Adapter(error=ValueError("bad link"))]
    )
    body = capability(_message("订阅 add xyz"), None).body
    assert "解析失败" in body
    assert "bad link" in body

    capability2, _store2 = _v2_capability(
        tmp_path,
        [_V2Adapter(error=ValueError("a")), _V2Adapter(error=RuntimeError("loop"))],
    )
    body2 = capability2(_message("订阅 add xyz"), None).body
    assert "运行异常" in body2

    capability3, _store3 = _v2_capability(tmp_path, [])
    body3 = capability3(_message("订阅 add xyz"), None).body
    assert "无法识别订阅平台" in body3
    assert "None" not in body3


# ---------------------------------------------------------------- P3 #27
def test_audit_p3_27_content_none_platform_extra_guard() -> None:
    """P3#27：content 为 None 时字幕提取不再潜伏崩溃（同函数守卫样式）。"""

    def fake_parse(url: str):
        return SimpleNamespace(
            identity=SimpleNamespace(
                item_kind="note", item_id="i1", canonical_url=url, platform="fake"
            ),
            content=None,
            creator=None,
            engagement=None,
            provenance=SimpleNamespace(parse_depth="deep"),
            media=[],
            music=None,
        )

    registry = SimpleNamespace(
        match=lambda source_input: [
            SimpleNamespace(parser_id="fake", matched_keyword="fake.example")
        ]
    )
    capability = build_content_capability(
        SimpleNamespace(),
        registry={"registry": registry, "parsers": {"fake": fake_parse}},
        downloader=None,
        render_backend=None,
    )
    result = capability(
        _message("看这个 https://fake.example/abc"), None
    )
    assert result is not None
    assert result.audit_tags and result.audit_tags[0] == "content_parse"
