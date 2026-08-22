from plugins.bot_unified_runtime.capabilities.today_history import (
    _load_push_table,
    _save_push_table,
    build_today_history_capability,
    is_today_history_command,
)
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.sources.today_history import (
    HistoryEvent,
    TodayHistoryProvider,
    _parse_history_json,
    format_history_text,
)


def _message(text: str, *, group_id: str = "") -> IncomingMessage:
    return IncomingMessage(
        platform="test",
        adapter="test",
        bot_id="bot",
        session_id=f"group:{group_id}" if group_id else "s1",
        session_type=SessionType.GROUP if group_id else SessionType.PRIVATE,
        sender_id="u1",
        group_id=group_id,
        plain_text=text,
        raw_segments=[{"type": "text", "data": {"text": text}}],
        mentions_bot=True,
    )


class FakeProvider:
    def __init__(self, events):
        self._events = events
        self.force_calls = 0

    def get_events(self, *, force=False):
        if force:
            self.force_calls += 1
        return self._events


def test_parse_history_json_with_html_links():
    data = _parse_history_json(
        '{"08": {"0822": [{"year": "1350", "title": "法国国王<a target=\\"_blank\\" href=\\"https://baike.baidu.com\\">腓力六世</a>逝世"}]}}'
    )
    assert data["08"]["0822"][0]["year"] == "1350"


def test_fetch_format():
    text = format_history_text([HistoryEvent(year="1350", title="法国国王腓力六世逝世")])
    assert "1350 法国国王腓力六世逝世" in text


def test_today_history_query_result():
    provider = FakeProvider([HistoryEvent(year="1904", title="邓小平出生")])
    capability = build_today_history_capability(provider=provider)

    result = capability(_message("历史上的今天"), None)

    assert result.capability_id == "bot.today_history"
    assert "1904 邓小平出生" in result.body
    assert "today_history_events:1" in result.audit_tags


def test_today_history_subscribe_and_cancel(tmp_path):
    provider = FakeProvider([HistoryEvent(year="1904", title="x")])
    push_file = str(tmp_path / "push.json")
    resync_calls = []
    capability = build_today_history_capability(
        provider=provider,
        push_file=push_file,
        on_subscriptions_changed=lambda: resync_calls.append(1),
    )

    result = capability(_message("历史上的今天 设置 8:30", group_id="10001"), None)
    assert "08:30" in result.body
    assert _load_push_table(push_file) == {"g_10001": {"hour": 8, "minute": 30}}
    assert resync_calls == [1]

    status = capability(_message("历史上的今天 状态", group_id="10001"), None)
    assert "08:30" in status.body

    cancelled = capability(_message("历史上的今天 取消", group_id="10001"), None)
    assert "已取消" in cancelled.body
    assert _load_push_table(push_file) == {}


def test_today_history_bad_time_format(tmp_path):
    capability = build_today_history_capability(
        provider=FakeProvider([]),
        push_file=str(tmp_path / "push.json"),
    )

    result = capability(_message("历史上的今天 设置 明天", group_id="1"), None)

    assert "用法" in result.body


def test_command_detection():
    assert is_today_history_command("历史上的今天")
    assert is_today_history_command("历史上的今天 设置 8:00")
    assert not is_today_history_command("历史上的明天")


def test_provider_cache(tmp_path, monkeypatch):
    from plugins.bot_unified_runtime.sources.today_history import fetch_today_history

    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.sources.today_history.fetch_today_history",
        lambda **kwargs: [HistoryEvent(year="1904", title="邓小平出生")],
    )
    provider = TodayHistoryProvider(cache_file=str(cache_file))

    events = provider.get_events()
    assert events[0].title == "邓小平出生"
    # 第二次命中缓存，不再拉取。
    events2 = provider.get_events()
    assert events2[0].year == "1904"
    assert cache_file.exists()
