"""bot.subscribe 命令能力与订阅调度器注册测试。

命令测试全部走本地假 adapter / SQLite，不发网络；调度器测试用假
scheduler 捕获 add_job 调用，只验证注册参数。
"""
from __future__ import annotations

import os
import uuid

import pytest

from plugins.bot_unified_runtime.capabilities.subscribe import (
    build_subscribe_capability,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.contracts.subscription import (
    NormalizedSubscriptionItem,
    SourceFetchResult,
    SubscriptionCursor,
    SubscriptionDestination,
    SubscriptionSpec,
)
from plugins.bot_unified_runtime.sources.subscription_store import SubscriptionStore
from plugins.bot_unified_runtime.sources.subscriptions import SubscriptionRegistry


def _remove_db_files(path: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = path + suffix
        try:
            os.remove(candidate)
        except FileNotFoundError:
            pass


@pytest.fixture
def db_path():
    path = os.path.join("data", f"test_subscribe_command_{uuid.uuid4().hex}.sqlite3")
    try:
        yield path
    finally:
        _remove_db_files(path)


def _message(text: str, *, sender_id: str = "u1", group_id: str | None = None, roles=None) -> IncomingMessage:
    return IncomingMessage(
        platform="test",
        adapter="test",
        bot_id="bot",
        session_id=f"group:{group_id}" if group_id else f"private:{sender_id}",
        session_type=SessionType.GROUP if group_id else SessionType.PRIVATE,
        sender_id=sender_id,
        group_id=group_id,
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
        sender_roles=roles if roles is not None else ["user"],
    )


def _make_spec(spec_id: str, *, platform: str = "bilibili", destinations, target_name: str = "测试UP", **overrides):
    values = {
        "id": spec_id,
        "platform": platform,
        "target_kind": "user",
        "target_id": spec_id.rsplit(":", 1)[-1],
        "target_name": target_name,
        "destinations": destinations,
        "created_by": "u1",
    }
    values.update(overrides)
    return SubscriptionSpec(**values)


def _private_dest(user_id: str) -> SubscriptionDestination:
    return SubscriptionDestination(scope="private", target_id=user_id)


def _group_dest(group_id: str) -> SubscriptionDestination:
    return SubscriptionDestination(scope="group", target_id=group_id)


class FakeAdapter:
    platform = "bilibili"
    target_kinds = ("user",)

    def __init__(self, items=(), *, fail_with: str | None = None):
        self.items = [*items]
        self.resolved_urls = []
        self.fail_with = fail_with

    def resolve_target(self, url: str) -> dict:
        self.resolved_urls.append(url)
        if url.count(":") == 2 and not url.startswith(("http://", "https://")):
            platform, target_kind, target_id = url.split(":")
            return {
                "platform": platform,
                "target_kind": target_kind,
                "target_id": target_id,
                "target_name": f"名称-{target_id}",
            }
        if url.startswith(("http://", "https://")):
            target_id = url.rstrip("/").rsplit("/", 1)[-1]
            return {
                "platform": "bilibili",
                "target_kind": "user",
                "target_id": target_id,
                "target_name": "测试UP",
            }
        raise ValueError("无法识别的订阅目标")

    async def fetch_latest(self, spec, cursor, ctx):
        if self.fail_with is not None:
            raise RuntimeError(self.fail_with)
        return SourceFetchResult(
            items=self.items,
            new_cursor=SubscriptionCursor(spec_id=spec.id),
            health_state="healthy",
            error="",
        )


def _build_capability(db_path: str, *, admin_ids=None, adapter_items=()):
    store = SubscriptionStore(db_path)
    registry = SubscriptionRegistry([FakeAdapter(adapter_items)])
    config = Config(bot_admin_user_ids=admin_ids or [])
    capability = build_subscribe_capability(store=store, registry=registry, config=config)
    return store, registry, config, capability


def test_group_add_to_group_rejected_for_non_admin(db_path):
    store, _registry, _config, capability = _build_capability(
        db_path, admin_ids=["admin-1"]
    )

    result = capability(
        _message("/bot subscribe add https://bilibili.com/user/123 到本群", group_id="10001"),
        None,
    )

    assert result.kind == "text"
    assert "管理员" in result.body
    assert store.list_specs() == []
    assert "subscribe_add" in result.audit_tags
    store.close()


def test_group_add_to_group_allowed_for_admin(db_path):
    store, _registry, _config, capability = _build_capability(
        db_path, admin_ids=["admin-1"]
    )

    result = capability(
        _message(
            "/bot subscribe add https://bilibili.com/user/123 到本群",
            sender_id="admin-1",
            group_id="10001",
            roles=["admin"],
        ),
        None,
    )

    assert "群 10001" in result.body
    [spec] = store.list_specs()
    assert spec.id == "bilibili:user:123"
    assert spec.destinations == [_group_dest("10001")]
    assert "subscribe_add" in result.audit_tags
    store.close()


def test_private_add_builds_correct_spec(db_path):
    store, registry, _config, capability = _build_capability(db_path)

    result = capability(
        _message("/bot subscribe add https://bilibili.com/user/123 --digest"),
        None,
    )

    assert "订阅已添加" in result.body
    assert "私聊" in result.body
    spec = store.get_spec("bilibili:user:123")
    assert spec is not None
    assert spec.platform == "bilibili"
    assert spec.target_kind == "user"
    assert spec.target_id == "123"
    assert spec.target_name == "测试UP"
    assert spec.destinations == [_private_dest("u1")]
    assert spec.digest_enabled is True
    assert spec.created_by == "u1"
    assert registry.list_adapters()[0].resolved_urls == ["https://bilibili.com/user/123"]
    assert "subscribe_add" in result.audit_tags
    store.close()


def test_add_accepts_platform_kind_id_form(db_path):
    store, registry, _config, capability = _build_capability(db_path)

    capability(_message("/bot subscribe add bilibili:user:456"), None)

    spec = store.get_spec("bilibili:user:456")
    assert spec is not None
    assert spec.target_name == "名称-456"
    assert registry.list_adapters()[0].resolved_urls == ["bilibili:user:456"]
    store.close()


def test_private_list_only_shows_own_private_subscriptions(db_path):
    store, _registry, _config, capability = _build_capability(db_path)
    store.upsert_spec(_make_spec("bilibili:user:1", destinations=[_private_dest("u1")], target_name="自己"))
    store.upsert_spec(_make_spec("bilibili:user:2", destinations=[_private_dest("u2")], target_name="别人"))
    store.upsert_spec(_make_spec("bilibili:user:3", destinations=[_group_dest("10001")], target_name="群订阅"))

    result = capability(_message("/bot subscribe list", sender_id="u1"), None)

    assert "bilibili:user:1" in result.body
    assert "bilibili:user:2" not in result.body
    assert "bilibili:user:3" not in result.body
    assert "subscribe_list" in result.audit_tags
    store.close()


def test_group_list_requires_admin_and_filters_by_group(db_path):
    store, _registry, _config, capability = _build_capability(db_path, admin_ids=["admin-1"])
    store.upsert_spec(_make_spec("bilibili:user:1", destinations=[_private_dest("u1")], target_name="私聊订阅"))
    store.upsert_spec(_make_spec("bilibili:user:3", destinations=[_group_dest("10001")], target_name="本群订阅"))
    store.upsert_spec(_make_spec("bilibili:user:4", destinations=[_group_dest("20002")], target_name="别的群"))

    denied = capability(_message("/bot subscribe list", group_id="10001"), None)
    assert "管理员" in denied.body

    allowed = capability(
        _message("/bot subscribe list", sender_id="admin-1", group_id="10001", roles=["admin"]),
        None,
    )
    assert "bilibili:user:3" in allowed.body
    assert "bilibili:user:1" not in allowed.body
    assert "bilibili:user:4" not in allowed.body
    store.close()


def test_remove_requires_ownership(db_path):
    store, _registry, _config, capability = _build_capability(db_path)
    store.upsert_spec(
        _make_spec(
            "bilibili:user:2",
            destinations=[_private_dest("u2")],
            created_by="u2",
        )
    )

    denied = capability(_message("/bot subscribe remove bilibili:user:2", sender_id="u1"), None)
    assert "没有权限" in denied.body
    assert store.get_spec("bilibili:user:2") is not None
    assert "subscribe_remove" in denied.audit_tags

    allowed = capability(_message("/bot subscribe remove bilibili:user:2", sender_id="u2"), None)
    assert "已删除" in allowed.body or "已移除" in allowed.body
    assert store.get_spec("bilibili:user:2") is None
    store.close()


def test_pause_and_resume_private_subscription(db_path):
    store, _registry, _config, capability = _build_capability(db_path)
    store.upsert_spec(_make_spec("bilibili:user:1", destinations=[_private_dest("u1")], created_by="u1"))

    paused = capability(_message("/bot subscribe pause bilibili:user:1", sender_id="u1"), None)
    assert store.get_spec("bilibili:user:1").enabled is False
    assert "subscribe_pause" in paused.audit_tags

    resumed = capability(_message("/bot subscribe resume bilibili:user:1", sender_id="u1"), None)
    assert store.get_spec("bilibili:user:1").enabled is True
    assert "subscribe_resume" in resumed.audit_tags

    denied = capability(_message("/bot subscribe pause bilibili:user:1", sender_id="u2"), None)
    assert "没有权限" in denied.body
    assert store.get_spec("bilibili:user:1").enabled is True
    store.close()


def test_status_counts_total_and_platforms(db_path):
    store, _registry, _config, capability = _build_capability(db_path)
    store.upsert_spec(_make_spec("bilibili:user:1", destinations=[_private_dest("u1")]))
    store.upsert_spec(_make_spec("bilibili:user:2", destinations=[_private_dest("u1")]))
    store.upsert_spec(
        _make_spec("pixiv:user:9", platform="pixiv", destinations=[_private_dest("u1")])
    )

    result = capability(_message("/bot subscribe status"), None)

    assert "订阅总数：3" in result.body
    assert "bilibili：2" in result.body
    assert "pixiv：1" in result.body
    assert "subscribe_status" in result.audit_tags
    store.close()


def test_check_runs_fetch_and_reports_new_items_without_sending(db_path):
    items = [
        NormalizedSubscriptionItem(item_id="c1", kind="video", title="视频C"),
        NormalizedSubscriptionItem(item_id="c2", kind="dynamic", title="动态D"),
    ]
    store, _registry, _config, capability = _build_capability(db_path, adapter_items=items)
    store.upsert_spec(_make_spec("bilibili:user:1", destinations=[_private_dest("u1")]))

    result = capability(_message("/bot subscribe check bilibili:user:1"), None)

    assert "新增 2 条" in result.body
    assert "subscribe_check" in result.audit_tags
    # check 只读，不把条目标记为已推送。
    assert store.already_pushed("bilibili:user:1", "c1", "video") is False
    assert store.already_pushed("bilibili:user:1", "c2", "dynamic") is False
    store.close()


def test_check_reports_failure_reason(db_path):
    store = SubscriptionStore(db_path)
    registry = SubscriptionRegistry([FakeAdapter(fail_with="api down")])
    capability = build_subscribe_capability(store=store, registry=registry, config=Config())
    store.upsert_spec(_make_spec("bilibili:user:1", destinations=[_private_dest("u1")]))

    result = capability(_message("/bot subscribe check bilibili:user:1"), None)

    assert "api down" in result.body
    assert "subscribe_check" in result.audit_tags
    store.close()


def test_subscription_scheduler_registers_three_jobs(db_path):
    import plugins.bot_unified_runtime as plugin_entry

    class FakeScheduler:
        def __init__(self):
            self.jobs = []

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    fake = FakeScheduler()
    config = Config(
        bot_subscribe_enabled=True,
        bot_subscribe_db_path=db_path,
        bot_subscribe_poll_interval_seconds=123,
        bot_subscribe_live_poll_seconds=45,
        bot_subscribe_digest_hour=21,
        bot_subscribe_digest_minute=15,
        bot_subscribe_max_items_per_tick=7,
        bot_download_proxy="http://127.0.0.1:7890",
    )

    result = plugin_entry._register_subscription_scheduler(
        scheduler=fake,
        config=config,
        pipeline=None,
        send_queue=None,
        audit_logger=None,
        receipt_repository=None,
        bot_provider=lambda: None,
    )

    by_id = {job["id"]: job for job in fake.jobs}
    assert set(by_id) == {"sub_watch", "sub_live", "sub_digest"}

    watch = by_id["sub_watch"]
    assert watch["trigger"] == "interval"
    assert watch["seconds"] == 123
    assert watch["jitter"] == 60
    assert watch["coalesce"] is True
    assert watch["max_instances"] == 1
    assert watch["misfire_grace_time"] == 120

    live = by_id["sub_live"]
    assert live["trigger"] == "interval"
    assert live["seconds"] == 45
    assert live["jitter"] == 60

    digest = by_id["sub_digest"]
    assert digest["trigger"] == "cron"
    assert digest["hour"] == 21
    assert digest["minute"] == 15

    assert result["store"] is not None
    assert result["watcher"] is not None
    assert result["registry"] is not None


def test_subscription_scheduler_disabled_returns_empty(db_path):
    import plugins.bot_unified_runtime as plugin_entry

    class FakeScheduler:
        def __init__(self):
            self.jobs = []

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    fake = FakeScheduler()
    result = plugin_entry._register_subscription_scheduler(
        scheduler=fake,
        config=Config(bot_subscribe_enabled=False, bot_subscribe_db_path=db_path),
        pipeline=None,
        send_queue=None,
        audit_logger=None,
        receipt_repository=None,
        bot_provider=lambda: None,
    )

    assert result == {}
    assert fake.jobs == []
