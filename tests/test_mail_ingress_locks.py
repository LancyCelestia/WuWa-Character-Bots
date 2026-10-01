r"""S-MAILINGRESS（50 号席）邮件入站/出站审计派生锁 ＋ S-FIX-MAILINGRESS-R（63 号席）修复锁
＋ 席 N1（2026-10-02）把 F2/F3 两包**从待叠变成已叠**（P3.12：挂着的 skip 不算覆盖）。

结构（全离线 mock，零外发）：
- F1（已修复·直改）：安静时间可覆盖 mail 会话（`quiet_hours.py` 枚收录 email，
  与 QQ 私聊同形制＝可收、opt-in）。下方为「修复后行为锁」。
- F2（**已叠**）：`mail_adapter.py` 的 `\Seen` 后置于派发成功（at-most-once →
  at-least-once）。真身＝
  `.superpowers/sdd/2026-09-27-fullload/patches/MAILINGRESS-F2-mailadapter.patch.md`
  格 A/B；配对锁＝本文件下方两枚顺序/失败路径行为锁 ＋
  `tests/test_mail_adapter_resilience.py` 格 D 的 IMAP 命令分组断言。
  两枚病态形现状锁（`\Seen` 先落定、构造失败静默丢信）同批**删除**——
  留着等于把修坏过一次的形制再钉一遍，下次改动会同时打红两把相反的尺。
- F3（**已叠**）：认领重投腿 `event=None` 的 mail 语义降级。真身＝
  `.superpowers/sdd/2026-09-27-fullload/patches/MAILINGRESS-F3-root.patch.md`
  格 A/B（root `__init__.py` 无需改格，修复落 `sender/nonebot.py`）；
  病态形现状锁 `test_f3_redrive_text_leg_degrades_to_plain_send_to` 同批删除，
  继任者＝`test_f3_redrive_text_leg_restores_thread_headers`。
  「直接调构造器传 None」的四枚契约锁逐字不动（替身只在 `send_nonebot_message` 内部立）。
- deny 面 / 幂等键：现状锁。幂等键那枚在 N1 波随 P3.10 洗段翻转（见该格注记）。

对应票号详见 logs/SEAT-MAILINGRESS.md 与 logs/SEAT-FIX-MAILINGRESS-R.md；
本波工单 patches/N1-NOTICE-ROLES-MAIL-20261002.md。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    PrivacyLevel,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.gate import evaluate_policy
from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
    QuietHoursChecker,
    QuietHoursSettings,
)
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import ROLE_BLOCKED
from plugins.bot_unified_runtime.domains.chat_reply.runtime.event_idempotency import (
    EventIdempotencyTable,
    build_event_dedupe_key,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    active_push_key_segment,
    is_legal_segment,
)
from plugins.bot_unified_runtime.domains.transport.mail import mail_adapter
from plugins.bot_unified_runtime.domains.transport.mail.mail_adapter import (
    ResilientMailAdapter,
)
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    FileTransferError,
    resolve_mail_recipient,
)
from plugins.bot_unified_runtime.domains.transport.sender.nonebot import (
    _build_mail_attachment_envelope,
    _build_mail_reply_message,
    send_nonebot_message,
)

# ---------------------------------------------------------------------------
# 辅助构造
# ---------------------------------------------------------------------------

#: 事件幂等键的连接符（`event_idempotency._KEY_SEPARATOR` 的测试侧镜像；段合法性一律
#: 回喂中央谓词 `is_legal_segment`，本文件不写第二套字符集）。
_SEG_SEPARATOR = "|"


def _email_message(**overrides: Any) -> IncomingMessage:
    base: dict[str, Any] = {
        "platform": "email",
        "adapter": "mail",
        "bot_id": "shorekeeper@foxmail.com",
        "session_id": "email:visitor@example.com",
        "session_type": SessionType.EMAIL,
        "sender_id": "visitor@example.com",
        "plain_text": "你好",
        "message_id": "<stable-1@example.com>",
    }
    base.update(overrides)
    return IncomingMessage(**base)


def _private_message(**overrides: Any) -> IncomingMessage:
    base: dict[str, Any] = {
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "bot-qq",
        "session_id": "private:u1",
        "session_type": SessionType.PRIVATE,
        "sender_id": "u1",
        "plain_text": "你好",
    }
    base.update(overrides)
    return IncomingMessage(**base)


# F1 用固定钟：2026-01-15 16:30 UTC = 00:30 亚洲/香港，落在 23:00–07:00 静窗内。
_QUIET_CLOCK = lambda: datetime(2026, 1, 15, 16, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# F1（已修复）：安静时间可覆盖 mail 会话——与 QQ 私聊同形制（可收、opt-in），
# 判定唯一真身仍是 QuietHoursChecker.check 的 session_type.value 比对。
# ---------------------------------------------------------------------------


def test_f1_quiet_hours_settings_can_cover_email() -> None:
    """修复行为锁①：session_types 枚收录 email（与运行时咽喉 _session_types_converter 对齐）。"""
    settings = QuietHoursSettings(session_types=["private", "group", "email"])
    assert settings.session_types == ["private", "group", "email"]
    # 枚举面之外仍拒（不是无条件放开）。
    with pytest.raises(ValidationError):
        QuietHoursSettings(session_types=["guild"])


def test_f1_validator_enum_matches_runtime_store_converter() -> None:
    """禁第二真身锁②：策略校验器与 /bot runtime set 咽喉对同一键的合法值面必须一致。

    病态形＝「store 收得进、policy 永不认」（email 落库后被旁路），这正是
    台账 #50/#56「改 .env/热改不生效」同族坑——两本枚举账逐值互认执法。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        _session_types_converter,
    )

    for value in ("private", "group", "email"):
        QuietHoursSettings(session_types=[value])  # 不炸＝policy 面收
        assert _session_types_converter(value) == [value]  # store 面同收
    for bad in ("guild", "channel"):
        with pytest.raises(ValidationError):
            QuietHoursSettings(session_types=[bad])
        with pytest.raises(ValueError):
            _session_types_converter(bad)


def test_f1_email_session_hits_quiet_gate_when_configured() -> None:
    """修复行为锁③：静窗内、email 收进 session_types ⇒ mail 与 private 一样被拦
    （中央判定同一条腿，audit tag 带 session:email）。"""
    checker = QuietHoursChecker(
        QuietHoursSettings(
            enabled=True,
            start_time="23:00",
            end_time="07:00",
            timezone_name="Asia/Hong_Kong",
            session_types=["private", "group", "email"],
            bypass_roles=[],
        ),
        clock=_QUIET_CLOCK,
    )
    blocked = checker.check(_private_message(), "bot.chat")
    assert blocked.allowed is False and blocked.reason == "quiet_hours"

    mail_decision = checker.check(_email_message(), "bot.chat")
    assert mail_decision.allowed is False
    assert mail_decision.reason == "quiet_hours"
    assert "quiet_hours:blocked" in mail_decision.audit_tags
    assert "quiet_hours:session:email" in mail_decision.audit_tags


def test_f1_email_still_opt_in_by_default() -> None:
    """形制锁④：缺省配置（不含 email）下 mail 照旧放行——和 QQ 私聊一样是
    「配置收编才进窗」的 opt-in，修复不改变未配置用户的行为面。"""
    checker = QuietHoursChecker(
        QuietHoursSettings(
            enabled=True,
            start_time="23:00",
            end_time="07:00",
            timezone_name="Asia/Hong_Kong",
            session_types=["private", "group"],
            bypass_roles=[],
        ),
        clock=_QUIET_CLOCK,
    )
    mail_decision = checker.check(_email_message(), "bot.chat")
    assert mail_decision.allowed is True
    assert mail_decision.reason == "session_type_excluded"


# ---------------------------------------------------------------------------
# deny 面：blocked 角色对邮箱地址生效；私聊维度有问必回（F4 判定证据）
# ---------------------------------------------------------------------------


def test_deny_surface_blocked_role_hits_email_sender() -> None:
    decision = evaluate_policy(
        _email_message(sender_roles=["user", ROLE_BLOCKED]), "bot.chat"
    )
    assert decision.allowed is False
    assert decision.reason == "sender_blocked"


def test_email_session_falls_to_direct_chat_allow() -> None:
    """普通邮箱来信走「私聊=有问必回」，群四档名单不参与（group_id=None）。"""
    decision = evaluate_policy(_email_message(), "bot.chat")
    assert decision.allowed is True and decision.reason == "allowed"


# ---------------------------------------------------------------------------
# 幂等键：mail|bot|Message-ID（F6 前置件；缺号则跳过去重）
#
# 【席 N1 2026-10-02 翻转】旧断言写的是**未洗段**的直拼形。连接符 `|` 不是段内合法字符，
# 而 mail 的 Message-ID 由发件方邮件服务器决定（`<…@…>`，可控文本）——不洗则含 `|` 的
# Message-ID 能与另一枚 bot_id 拼出同一串键＝两条不同来信共用一个幂等桶（静默吞第二条）。
# 现在逐段过中央洗段口（读侧谓词 `is_legal_segment`，台账 #46★ 同一把尺），键仍一一对应。
# 同批另见 tests/test_notice_event_dedupe_fallback.py::
#   test_separator_in_inbound_id_cannot_fold_two_events_into_one_bucket
# ---------------------------------------------------------------------------


def test_event_dedupe_key_stable_for_mail_and_blank_without_id() -> None:
    key = build_event_dedupe_key(_email_message())
    assert key == _SEG_SEPARATOR.join(
        active_push_key_segment(part)
        for part in ("mail", "shorekeeper@foxmail.com", "<stable-1@example.com>")
    ), key
    assert all(
        is_legal_segment(part) for part in key.split(_SEG_SEPARATOR)
    ), f"mail 键段未过中央谓词：{key!r}"
    # 缺 Message-ID 且带正文＝合成轮，幂等真身在出站队列 ⇒ 入站不建键（旧语义不动）。
    assert build_event_dedupe_key(_email_message(message_id=None)) == ""

    table = EventIdempotencyTable()
    assert table.claim(key, capability_id="bot.chat") is True
    assert table.claim(key, capability_id="bot.chat") is False


# ---------------------------------------------------------------------------
# F2：适配器 at-least-once 顺序锁（席 N1 2026-10-02 **已叠**
# `.superpowers/sdd/2026-09-27-fullload/patches/MAILINGRESS-F2-mailadapter.patch.md`
# 格 A/B，并按该包【配对锁】格 C 摘掉两枚桩锁的 skip、删除两枚病态形现状锁）
#
# 病态形（\Seen 落定在任何派发之前 ⇒ 构造失败/进程崩溃＝永久静默丢信）的继任者就是
# 下面第一枚；旧现状锁 `test_f2_seen_is_committed_before_dispatch` 与
# `test_f2_event_build_failure_drops_mail_silently_no_retry` 同 commit 删除——
# 留着它们等于把"已经修坏过一次的形制"再钉一遍，下一次改动会同时打红两把相反的尺。
# 同批配对锁的另一半在 tests/test_mail_adapter_resilience.py::格 D（IMAP 命令分组断言）。
# ---------------------------------------------------------------------------


class _AdapterHarness:
    """最小可行的 _fetch_new_mail 演练场：所有 IMAP 触点是模块级名字，可整体换假。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch, *, uids: str = "7") -> Any:
        adapter = ResilientMailAdapter.__new__(ResilientMailAdapter)
        adapter.driver = cast(Any, SimpleNamespace())
        adapter.bots = {}
        adapter.tasks = set()
        # F2 在飞门真身（补丁格 A 落进 `ResilientMailAdapter.__init__`）；
        # 本 harness 走 `__new__` 绕开 `__init__`，故显式补这枚属性。
        adapter._inflight_uids = set()

        async def _search(client: Any, **kwargs: Any) -> Any:
            self.calls.append("search")
            return SimpleNamespace(result="OK", lines=[uids.encode()])

        async def _fetch(client: Any, uid: str) -> Any:
            self.calls.append(f"fetch:{uid}")
            return SimpleNamespace(id=f"<{uid}@example.com>", message=None)

        async def _mark(client: Any, uid: str) -> None:
            self.calls.append(f"seen:{uid}")

        # 生产代码经 asyncio.to_thread 同步调用它（非协程），mock 必须同为普通函数。
        def _attach(message: Any, request_id: str = "") -> list[str]:
            return []

        monkeypatch.setattr(mail_adapter, "search_unseen_with_backoff", _search)
        monkeypatch.setattr(mail_adapter, "fetch_mail_by_uid", _fetch)
        monkeypatch.setattr(mail_adapter, "mark_mail_seen", _mark)
        monkeypatch.setattr(mail_adapter, "build_attachment_context", _attach)
        monkeypatch.setattr(
            mail_adapter,
            "model_dump",
            lambda obj: {"id": obj.id, "message": [{"type": "text", "data": {"text": "hi"}}]},
        )
        bot = SimpleNamespace(
            mailbox="INBOX",
            readonly=False,
            imap_client=SimpleNamespace(),
            self_id="bot@example.com",
        )

        async def _handle(event: Any) -> None:
            self.calls.append(f"handle:{event.id}")

        bot.handle_event = _handle  # type: ignore[method-assign]
        return adapter, bot

    async def drain(self, adapter: Any) -> None:
        pending = [task for task in list(adapter.tasks) if not task.done()]
        if pending:
            await asyncio.gather(*pending)


def _quiet_event_class(harness: _AdapterHarness) -> Any:
    class _Event:
        def __init__(self, **payload: Any) -> None:
            harness.calls.append(f"build:{payload.get('id')}")
            self.id = str(payload.get("id", ""))
            self.sender = SimpleNamespace(id="x@example.com")
            self.subject = ""

    return _Event


@pytest.mark.asyncio
async def test_f2_seen_committed_only_after_successful_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""目标序锁：search → fetch → build → handle → **seen**（\Seen 后置于派发成功）。"""
    harness = _AdapterHarness()
    adapter, bot = harness.install(monkeypatch)
    monkeypatch.setattr(mail_adapter, "QuietMailMessageEvent", _quiet_event_class(harness))

    await adapter._fetch_new_mail(bot)
    await harness.drain(adapter)

    assert harness.calls == [
        "search",
        "fetch:7",
        "build:<7@example.com>",
        "handle:<7@example.com>",
        "seen:7",
    ], "F2 修复：派发成功之后才回执 \\Seen（at-least-once）"


@pytest.mark.asyncio
async def test_f2_build_failure_leaves_mail_unseen_for_next_poll_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""目标行为锁：构造炸 ⇒ **不标 \Seen**（下轮 poll 重投），只留可读告警。"""
    harness = _AdapterHarness()
    adapter, bot = harness.install(monkeypatch, uids="7 8")

    def _boom(**payload: Any) -> Any:
        raise RuntimeError("event construction exploded")

    monkeypatch.setattr(mail_adapter, "QuietMailMessageEvent", _boom)
    await adapter._fetch_new_mail(bot)
    await harness.drain(adapter)

    assert [c for c in harness.calls if c.startswith("seen:")] == [], (
        "失败路径不得回执已读——静默丢信面（F2 病态形）就此关闭"
    )
    assert [c for c in harness.calls if c.startswith("handle:")] == []


# ---------------------------------------------------------------------------
# F3：SendQueue 认领重投腿 mail 语义（席 N1 2026-10-02 **已叠**
# `.superpowers/sdd/2026-09-27-fullload/patches/MAILINGRESS-F3-root.patch.md`：
# root `__init__.py` 无需改格，修复落 `sender/nonebot.py` 格 A/B。同批按该包【三】节
# 删除病态形现状锁 `test_f3_redrive_text_leg_degrades_to_plain_send_to`、摘两枚桩锁 skip）
#
# 保持不动的 F3 契约锁（直接调构造器传 None 的形制——替身只在 send_nonebot_message
# 内部立）：`test_f3_inline_text_leg_keeps_thread_headers_and_deterministic_id`／
# `test_f3_redrive_attachment_envelope_has_no_allowlisted_recipient`／
# `test_f3_empty_allowlist_is_hard_rejected`／`test_f3_mail_reply_message_requires_recipient_fact`。
# ---------------------------------------------------------------------------


class _FakeMailAdapter:
    def get_name(self) -> str:
        return "Mail"


class _FakeMailBot:
    def __init__(self) -> None:
        self.adapter = _FakeMailAdapter()
        self.self_id = "shorekeeper@foxmail.com"
        self.bot_info = SimpleNamespace(id=self.self_id, name="守岸人")
        self.send_to_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.send_mail_calls: list[Any] = []

    async def send_to(self, recipient: str, message: str, **kwargs: Any) -> dict[str, str]:
        self.send_to_calls.append((str(recipient), str(message), dict(kwargs)))
        return {"id": "direct-1"}

    async def send_mail(self, message: Any) -> dict[str, str]:
        self.send_mail_calls.append(message)
        return {"id": "mail-1"}


def _mail_send_request(
    request_id: str = "req-redrive-1",
    *,
    origin_message_id: str | None = None,
) -> SendRequest:
    return SendRequest(
        request_id=request_id,
        session_id="email:visitor@example.com",
        target_scope=SessionType.EMAIL,
        target_id="visitor@example.com",
        origin_message_id=origin_message_id,
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={},
            text_fallback="回信正文",
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.QUEUED,
        priority="normal",
        max_messages=1,
        dedupe_key=f"bot.chat:email:visitor:{request_id}",
        cooldown_key="email:visitor@example.com",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        adapter="mail",
        bot_id="shorekeeper@foxmail.com",
    )


@pytest.mark.asyncio
async def test_f3_redrive_text_leg_restores_thread_headers() -> None:
    """目标：event=None 的 mail 重投文本腿走 send_mail——线程头回填
    origin_message_id、同 request_id 重投同号（atkfix R3 语义在重投臂恢复成立）、
    不再降级 send_to。

    继任者身份：本枚取代旧病态形现状锁
    `test_f3_redrive_text_leg_degrades_to_plain_send_to`（同 commit 删除）。
    """
    bot = _FakeMailBot()
    request = _mail_send_request("req-redrive-2", origin_message_id="<orig-9@example.com>")

    await send_nonebot_message(bot, None, request)
    await send_nonebot_message(bot, None, request)

    assert bot.send_to_calls == [], "重投文本腿不再走 send_to 兜底"
    assert len(bot.send_mail_calls) == 2
    first, second = bot.send_mail_calls
    assert first["In-Reply-To"] == "<orig-9@example.com>"
    assert first["References"] == "<orig-9@example.com>"
    assert first["Message-ID"] == second["Message-ID"], "确定性 Message-ID 在重投臂成立"
    assert first["To"] == "visitor@example.com"


@pytest.mark.asyncio
async def test_f3_inline_text_leg_keeps_thread_headers_and_deterministic_id() -> None:
    """对照锁（F3 修复前后逐字仍真）：inline 腿（event 在场）必带 In-Reply-To=来信号，
    且同一 request_id 重投两次得同一 Message-ID（atkfix R3 去重保证）。"""
    bot = _FakeMailBot()
    event = SimpleNamespace(
        id="<incoming-42@example.com>",
        sender=SimpleNamespace(id="visitor@example.com"),
        subject="测试主题",
    )

    await send_nonebot_message(bot, event, _mail_send_request("req-inline-1"))
    await send_nonebot_message(bot, event, _mail_send_request("req-inline-1"))

    assert len(bot.send_mail_calls) == 2
    first, second = bot.send_mail_calls
    assert first["In-Reply-To"] == "<incoming-42@example.com>"
    assert first["References"] == "<incoming-42@example.com>"
    assert first["Message-ID"] == second["Message-ID"], "同 request_id 重投同号"
    assert bot.send_to_calls == []


def test_f3_redrive_surrogate_fills_attachment_roster() -> None:
    """目标：请求侧事实替身喂给附件信封 ⇒ 名册=(target_id,)，
    resolve_mail_recipient(target_id, 名册) 一致放行——附件重投不再恒 FAILED_FINAL。"""
    from plugins.bot_unified_runtime.domains.transport.sender.nonebot import (
        _MailRedriveEvent,
    )

    bot = _FakeMailBot()
    request = _mail_send_request("req-redrive-3", origin_message_id="<orig-10@example.com>")
    envelope = _build_mail_attachment_envelope(
        bot, _MailRedriveEvent(request), "正文", daily_count=0
    )
    assert envelope.recipients_allowlisted == ("visitor@example.com",)
    # 网关比对同闸同真身：target_id 与名册一致 ⇒ 放行且不抛。
    resolved = resolve_mail_recipient(request.target_id, envelope.recipients_allowlisted)
    assert str(resolved) == "visitor@example.com"


def test_f3_redrive_attachment_envelope_has_no_allowlisted_recipient() -> None:
    """event=None 时附件信封的收件名册恒空（地址只从事件取，绝不从正文扫）。"""
    bot = _FakeMailBot()
    envelope = _build_mail_attachment_envelope(bot, None, "正文", daily_count=0)
    assert envelope.recipients_allowlisted == ()


def test_f3_empty_allowlist_is_hard_rejected() -> None:
    """名册空 ⇒ resolve_mail_recipient 恒抛 mail_recipients_unconfigured：
    认领重投的附件腿在网关处**永远发不出去**（FAILED_FINAL 路径的根因锁）。"""
    with pytest.raises(FileTransferError) as exc:
        resolve_mail_recipient("visitor@example.com", ())
    assert exc.value.kind == "mail_recipients_unconfigured"
    # 名册不匹配同样硬拒（绝不静默改投）。
    with pytest.raises(FileTransferError) as exc2:
        resolve_mail_recipient("attacker@evil.com", ("visitor@example.com",))
    assert exc2.value.kind == "mail_recipient_not_allowlisted"


def test_f3_mail_reply_message_requires_recipient_fact() -> None:
    """无事件（无地址事实）连回复报文都构造不出来——与上面两条共同构成
    「重投腿附件必死」的完整证据链。"""
    bot = _FakeMailBot()
    with pytest.raises(ValueError):
        _build_mail_reply_message(bot, None, "正文", message_salt="req-x")
