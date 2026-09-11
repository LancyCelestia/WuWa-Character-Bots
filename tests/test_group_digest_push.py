"""夜间每日群通讯总结主动推送回归（G-DIGEST 收尾）。

离线验证（假 provider / 假 queue，不依赖 NoneBot 运行时）：

1. 白名单门：仅 whitelist 模式推送白名单群；模式空/黑名单一律零推送；
2. 无可用摘要（enabled=False 或空摘要）静默跳过；
3. 正文 = 一句守岸人引子 + 当日摘要（克制、单行引子）；
4. dedupe_key / request_id 日期化：同群同天不重发，跨天键不同；
5. SendRequest 结构照 reminder 样板（GROUP 作用域、QUEUED、text_fallback）；
6. ``bot_group_digest_push_time`` 的 HH:MM 严格校验与调度器解析回退。
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime import (
    _DIGEST_PUSH_INTRO,
    _build_digest_push_text,
    _parse_digest_push_clock,
    _push_daily_group_digests,
    _register_digest_push_scheduler,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import PrivacyLevel, SendPolicy, SessionType

_NOW = datetime(2026, 9, 12, 21, 30, tzinfo=timezone.utc)


class _FakeProvider:
    """group_id -> (enabled, summary) 的最小组投影；记录 load 调用。"""

    def __init__(self, summaries: dict[str, tuple[bool, str]]):
        self.summaries = summaries
        self.calls: list[tuple[str, str, str]] = []

    def load(self, request_id: str, group_id: str, sender_id: str = ""):
        self.calls.append((request_id, group_id, sender_id))
        enabled, summary = self.summaries.get(group_id, (False, ""))
        return SimpleNamespace(enabled=enabled, summary=summary)


class _FakeQueue:
    def __init__(self):
        self.requests = []

    def submit(self, request) -> None:
        self.requests.append(request)


def _list_config(mode: str, whitelist: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        bot_group_digest_list_mode=mode,
        bot_group_digest_whitelist=whitelist,
        bot_group_digest_blacklist=[],
        bot_persona_profile_id="default",
    )


def test_whitelist_mode_pushes_only_listed_groups() -> None:
    """whitelist 模式：只推白名单群，request 按 sorted 群号有序投递。"""
    queue = _FakeQueue()
    provider = _FakeProvider(
        {"222": (True, "222 的摘要"), "111": (True, "111 的摘要")}
    )

    pushed = _push_daily_group_digests(
        _list_config("whitelist", ["222", "111"]),
        queue,
        provider,
        now=_NOW,
    )

    assert pushed == ["111", "222"]
    assert [r.target_id for r in queue.requests] == ["111", "222"]
    # 每群合成 request_id 并传给 provider（sender_id 为空：非按人查询）。
    assert provider.calls[0] == (f"digest-push-111-{_NOW.date()}", "111", "")


@pytest.mark.parametrize("mode", ["", "off", "all", "blacklist", "bogus"])
def test_non_whitelist_modes_push_nothing(mode: str) -> None:
    """list_mode 非 whitelist 一律不推任何群（绝不猜群）。"""
    queue = _FakeQueue()
    provider = _FakeProvider({"111": (True, "有摘要")})

    pushed = _push_daily_group_digests(
        _list_config(mode, ["111"]),
        queue,
        provider,
        now=_NOW,
    )

    assert pushed == []
    assert queue.requests == []
    assert provider.calls == []  # 名单门在 provider 调用之前，不触任何群


def test_empty_whitelist_pushes_nothing() -> None:
    """白名单为空：无推送目标，零投递。"""
    queue = _FakeQueue()
    pushed = _push_daily_group_digests(
        _list_config("whitelist", []), queue, _FakeProvider({}), now=_NOW
    )

    assert pushed == []
    assert queue.requests == []


def test_missing_or_empty_digest_skipped() -> None:
    """enabled=False 或空摘要的群静默跳过；其余群正常推送。"""
    queue = _FakeQueue()
    provider = _FakeProvider(
        {"111": (False, ""), "222": (True, ""), "333": (True, "333 的摘要")}
    )

    pushed = _push_daily_group_digests(
        _list_config("whitelist", ["111", "222", "333"]),
        queue,
        provider,
        now=_NOW,
    )

    assert pushed == ["333"]
    assert len(queue.requests) == 1


def test_body_is_intro_line_plus_summary() -> None:
    """正文 = 单行守岸人引子 + 当日摘要；引子克制、不复述数值。"""
    text = _build_digest_push_text("222 的摘要")

    assert text == f"{_DIGEST_PUSH_INTRO}\n222 的摘要"
    lines = text.split("\n")
    assert len(lines) == 2  # 引子单独一行，摘要原样保留
    assert lines[0] == _DIGEST_PUSH_INTRO
    assert lines[1] == "222 的摘要"


def test_send_request_shape_and_dated_dedupe_key() -> None:
    """SendRequest 照 reminder 样板；dedupe_key/request_id 均日期化。"""
    queue = _FakeQueue()
    provider = _FakeProvider({"111": (True, "111 的摘要")})

    _push_daily_group_digests(
        _list_config("whitelist", ["111"]), queue, provider, now=_NOW
    )

    request = queue.requests[0]
    today = _NOW.date().isoformat()
    assert request.dedupe_key == f"digest_push:111:{today}"
    assert request.request_id == f"digest-push-111-{today}"
    assert request.session_id == "group:111"
    assert request.target_scope is SessionType.GROUP
    assert request.target_id == "111"
    assert request.capability_id == "bot.group_digest_push"
    assert request.send_policy is SendPolicy.QUEUED
    assert request.max_messages == 1
    assert request.privacy_level is PrivacyLevel.GROUP
    assert request.content.privacy_level is PrivacyLevel.GROUP
    assert request.content.text_fallback == (
        f"{_DIGEST_PUSH_INTRO}\n111 的摘要"
    )
    assert request.persona_profile_id == "default"


def test_dedupe_key_differs_across_days() -> None:
    """跨天 dedupe_key 不同：同群每天各允许推送一次。"""
    queue = _FakeQueue()
    provider = _FakeProvider({"111": (True, "111 的摘要")})
    config = _list_config("whitelist", ["111"])

    _push_daily_group_digests(
        config, queue, provider, now=datetime(2026, 9, 12, 21, 30, tzinfo=timezone.utc)
    )
    _push_daily_group_digests(
        config, queue, provider, now=datetime(2026, 9, 13, 21, 30, tzinfo=timezone.utc)
    )

    keys = [r.dedupe_key for r in queue.requests]
    assert keys == ["digest_push:111:2026-09-12", "digest_push:111:2026-09-13"]


class _FakeScheduler:
    def __init__(self):
        self.jobs: list[tuple[object, str, dict]] = []

    def add_job(self, func, trigger, **kwargs) -> None:
        self.jobs.append((func, trigger, kwargs))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("21:30", (21, 30)),
        ("00:00", (0, 0)),
        ("23:59", (23, 59)),
        (" 07:45 ", (7, 45)),  # 去空白后解析
        ("99:99", (21, 30)),  # 越界回退默认
        ("21", (21, 30)),  # 缺段回退默认
        ("ab:cd", (21, 30)),  # 非数字回退默认
        ("", (21, 30)),  # 空值回退默认
        (None, (21, 30)),  # None 回退默认
    ],
)
def test_parse_digest_push_clock(raw, expected) -> None:
    """HH:MM 解析：合法值成 (hour, minute)，非法一律回退默认 21:30。"""
    assert _parse_digest_push_clock(raw) == expected


def test_register_digest_push_scheduler_parses_time() -> None:
    """每日 cron 注册：时间取自 bot_group_digest_push_time，样板参数齐全。"""
    scheduler = _FakeScheduler()
    config = SimpleNamespace(bot_group_digest_push_time="07:45")

    info = _register_digest_push_scheduler(scheduler, config, _FakeQueue())

    assert info == {"hour": 7, "minute": 45}
    assert len(scheduler.jobs) == 1
    _, trigger, kwargs = scheduler.jobs[0]
    assert trigger == "cron"
    assert kwargs["id"] == "bot_group_digest_push_daily"
    assert kwargs["hour"] == 7
    assert kwargs["minute"] == 45
    assert kwargs["replace_existing"] is True
    assert kwargs["max_instances"] == 1
    assert kwargs["coalesce"] is True


@pytest.mark.parametrize("bad", ["99:99", "ab:cd", "21", "21:30:00", ""])
def test_register_digest_push_scheduler_bad_time_falls_back(bad: str) -> None:
    """非法时间回退默认 21:30（严格拒绝在 config 校验层，调度不炸）。"""
    scheduler = _FakeScheduler()

    info = _register_digest_push_scheduler(
        scheduler, SimpleNamespace(bot_group_digest_push_time=bad), _FakeQueue()
    )

    assert info == {"hour": 21, "minute": 30}
    assert scheduler.jobs[0][2]["hour"] == 21
    assert scheduler.jobs[0][2]["minute"] == 30


def test_config_default_and_valid_time_accepted() -> None:
    """config 默认 21:30；合法 HH:MM 通过校验并去空白。"""
    assert Config().bot_group_digest_push_enabled is True
    assert Config().bot_group_digest_push_time == "21:30"
    assert Config(bot_group_digest_push_time=" 06:05 ").bot_group_digest_push_time == "06:05"
    # 与安静时间键 _parse_hhmm 同为 int() 分段：非补零 "21:5" 宽容接受。
    assert Config(bot_group_digest_push_time="21:5").bot_group_digest_push_time == "21:5"


@pytest.mark.parametrize(
    "bad", ["24:00", "21:60", "-1:30", "2130", "abc", "", "21:30x"]
)
def test_config_rejects_invalid_time(bad: str) -> None:
    """HH:MM 严格校验（与安静时间键同款风格）：越界/非数字/缺段全拒绝。"""
    with pytest.raises(ValidationError):
        Config(bot_group_digest_push_time=bad)
