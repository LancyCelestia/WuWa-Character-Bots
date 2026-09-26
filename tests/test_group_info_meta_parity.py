"""S-META-PARITY 对等锁：TG 群主/管理员腿（getChatAdministrators）、TG 私聊账号腿、
邮件会话元信息腿——2026-09-26。

依据（写死在这里，防止后人再把「没接」读成「协议没有」）：

- Telegram Bot API（core.telegram.org/bots/api，2026-09-26 现取）方法表里与
  「谁/有多少/什么身份」相关的只有 getChat / getChatAdministrators /
  getChatMemberCount / getChatMember(单个)；**没有任何导出全量成员名单的动作**，
  也**没有任何在线/最近活跃口**。第二源＝本机实装
  ``nonebot-adapter-telegram``：``api.py:715-726`` 逐字对上，全表 grep
  online/last_seen 零命中。
- ChatFullInfo.bio＝私聊对端「个性签名」（returned only in getChat），实装
  ``model.py:1131`` 有该字段。
- Mail：``nonebot-adapter-mail/utils.py:108-113`` 逐封解出 To/Cc/Reply-To
  （=适配器**有**，摄取链没接＝票 T-META-INGEST-1）；Bcc 按 RFC 5321/5322
  投递语义在送出时被剥离（=结构**真没有**）。两格绝不混说。

全部离线：假 API 罐头 + 手造 IncomingMessage，零网络零真实凭据。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.group_info import (
    build_group_info_capability,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.group_cache import (
    GroupInfoCache,
)

# ---------------------------------------------------------------------------
# 假 API（与 tests/test_group_info.py 的 _TelegramApi 同哲学，各自独立可跑）
# ---------------------------------------------------------------------------


class _Api:
    def __init__(self, *, responses: dict[str, object], fail: set[str] = frozenset()) -> None:
        self.responses = responses
        self.fail = set(fail)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, action: str, **params: object) -> object:
        self.calls.append((action, dict(params)))
        if action in self.fail:
            raise RuntimeError("api down")
        if action in self.responses:
            return self.responses[action]
        raise AssertionError(f"不该打这个动作：{action}")

    def actions(self) -> list[str]:
        return [action for action, _ in self.calls]


class _Dump:
    """pydantic 形态替身：只有 model_dump()，没有 dict 接口。"""

    def __init__(self, body: dict) -> None:
        self._body = body

    def model_dump(self) -> dict:
        return self._body


def _group_message(**overrides: object) -> IncomingMessage:
    fields: dict[str, object] = {
        "platform": "telegram",
        "adapter": "telegram",
        "bot_id": "bot",
        "session_id": "group_-1001234567890_555",
        "session_type": SessionType.GROUP,
        "sender_id": "555",
        "sender_roles": ["user"],
        "group_id": "-1001234567890",
        "plain_text": "群主是谁",
        "raw_segments": [],
    }
    fields.update(overrides)
    return IncomingMessage(**fields)  # type: ignore[arg-type]


def _private_message(**overrides: object) -> IncomingMessage:
    fields: dict[str, object] = {
        "platform": "telegram",
        "adapter": "telegram",
        "bot_id": "bot",
        "session_id": "private_555",
        "session_type": SessionType.PRIVATE,
        "sender_id": "555",
        "sender_roles": ["user"],
        "group_id": None,
        "plain_text": "群信息",
        "raw_segments": [],
    }
    fields.update(overrides)
    return IncomingMessage(**fields)  # type: ignore[arg-type]


def _mail_message(**overrides: object) -> IncomingMessage:
    fields: dict[str, object] = {
        "platform": "email",
        "adapter": "mail",
        "bot_id": "shore@example.invalid",
        "session_id": "email:lan@example.invalid",
        "session_type": SessionType.EMAIL,
        "sender_id": "lan@example.invalid",
        "sender_roles": ["user"],
        "group_id": None,
        "plain_text": "群信息",
        "raw_segments": [],
    }
    fields.update(overrides)
    return IncomingMessage(**fields)  # type: ignore[arg-type]


def _cap(api: _Api) -> object:
    return build_group_info_capability(None, api=api, cache=GroupInfoCache())


_CREATOR = {
    "status": "creator",
    "user": {"id": 777, "first_name": "霞月", "username": "xiayue"},
}
_ADMIN = {
    "status": "administrator",
    "user": {"id": 555, "first_name": "澜汐"},
}


# ---------------------------------------------------------------------------
# ① TG 群：getChatAdministrators 已接（旧「答不了」判死的翻案正锁）
# ---------------------------------------------------------------------------


def test_tg_owner_intent_now_hits_administrators_api() -> None:
    api = _Api(responses={"get_chat_administrators": [_CREATOR, _ADMIN]})
    body = _cap(api)(_group_message(), None).body
    assert api.actions() == ["get_chat_administrators"]  # 不多打别的口
    assert "群主：霞月（@xiayue）" in body
    assert "管理员：1 人" in body
    # 名单这格依旧诚实缺失，且明说上面那份不含普通成员——防把管理员表读成全量表。
    assert "没有列出全部群成员" in body


def test_tg_unknown_status_never_inflates_privilege() -> None:
    """负锁：认不出的 status 不并进群主/管理员，也不被吞掉（未来加档必红）。"""
    weird = {"status": "supermoderator", "user": {"id": 999, "first_name": "怪"}}
    api = _Api(responses={"get_chat_administrators": [_CREATOR, weird]})
    body = _cap(api)(_group_message(), None).body
    assert "管理员：0 人" in body
    assert "另有 1 条成员记录的身份没认出来" in body
    assert "怪" not in body.replace("没认出来", "")  # 没认出的条目不冒充管理员被列出


def test_tg_missing_creator_row_says_so_without_naming_a_substitute() -> None:
    api = _Api(responses={"get_chat_administrators": [_ADMIN]})
    body = _cap(api)(_group_message(), None).body
    assert "先不硬指认" in body
    assert "群主：澜汐" not in body  # 管理员不许被顶上成群主


def test_tg_admin_list_truncation_names_the_omitted_count() -> None:
    staff = [
        {"status": "administrator", "user": {"id": 1000 + i, "first_name": f"管理{i}"}}
        for i in range(8)
    ]
    api = _Api(responses={"get_chat_administrators": [_CREATOR, *staff]})
    body = _cap(api)(_group_message(), None).body
    assert "管理员：8 人" in body
    assert "另有 3 位管理员未列出" in body


def test_tg_empty_administrators_list_is_not_rendered_as_failure() -> None:
    """接口真回了空列表（合法回包）≠「没答上」——两态分句。"""
    api = _Api(responses={"get_chat_administrators": []})
    body = _cap(api)(_group_message(), None).body
    assert "接口这次没答上" not in body
    assert "先不硬指认" in body  # 空列表里没有 creator，照实说


def test_tg_administrators_failure_line_does_not_claim_absence() -> None:
    api = _Api(responses={}, fail={"get_chat_administrators"})
    body = _cap(api)(_group_message(), None).body
    assert "拿不到（不等于本群没有群主）" in body
    assert "群主：没有" not in body and "管理员：0 人" not in body


def test_tg_administrators_pydantic_payload_still_reads() -> None:
    api = _Api(
        responses={
            "get_chat_administrators": [
                _Dump({"status": "creator", "user": {"id": 7, "first_name": "模型体"}})
            ]
        }
    )
    body = _cap(api)(_group_message(), None).body
    assert "群主：模型体" in body


def test_tg_administrators_cached_across_repeat_questions() -> None:
    api = _Api(responses={"get_chat_administrators": [_CREATOR]})
    cap = _cap(api)
    cap(_group_message(), None)
    cap(_group_message(), None)
    assert api.actions().count("get_chat_administrators") == 1


def test_tg_is_bot_marked_only_when_protocol_says_so() -> None:
    bot_admin = {"status": "administrator", "user": {"id": 8, "first_name": "助手", "is_bot": True}}
    api = _Api(responses={"get_chat_administrators": [_CREATOR, bot_admin]})
    body = _cap(api)(_group_message(plain_text="群信息"), None).body
    assert "助手（机器人）" in body
    assert "霞月（机器人）" not in body  # 无 is_bot 字段≠机器人


# ---------------------------------------------------------------------------
# ② TG 私聊：账号号/昵称/签名(bio) 接上 + 在线状态的结构缺失负锁
# ---------------------------------------------------------------------------


def _tg_private_api(**over: object) -> _Api:
    peer = {
        "id": 555,
        "first_name": "阿澜",
        "username": "alan_t",
        "bio": "白天摸鱼，晚上熬夜。",
    }
    peer.update({k: v for k, v in over.items() if k != "fail"})
    return _Api(responses={"get_chat": peer}, fail=over.get("fail", set()))  # type: ignore[arg-type]


def test_tg_private_profile_reads_id_name_bio() -> None:
    api = _tg_private_api()
    body = _cap(api)(_private_message(), None).body
    assert ("get_chat", {"chat_id": 555}) in api.calls
    assert "会话号（chat id）：555" in body
    assert "昵称：阿澜（@alan_t）" in body
    assert "个性签名：白天摸鱼，晚上熬夜。" in body


def test_tg_private_presence_is_structurally_absent_and_never_asserted() -> None:
    """负锁（全领域禁式口径）：结构性没有 ⇒ 明说没有；且任何情况下不得断言
    「对方在线/不在线」这类没发生的状态。"""
    body = _cap(_tg_private_api())(_private_message(), None).body
    assert "不向机器人开放在线/最近活跃" in body
    for forbidden in ("当前在线", "目前不在线", "最近活跃于"):
        assert forbidden not in body


def test_tg_private_bio_absent_vs_empty_are_two_states() -> None:
    with_key = _Api(responses={"get_chat": {"id": 5, "first_name": "A", "bio": ""}})
    body_empty = _cap(with_key)(_private_message(), None).body
    assert "接口回了空" in body_empty and "没设置" in body_empty
    without_key = _Api(responses={"get_chat": {"id": 5, "first_name": "A"}})
    body_missing = _cap(without_key)(_private_message(), None).body
    assert "这个字段这次没回" in body_missing
    assert "没设置" not in body_missing  # 未回≠没设置，不许替对方下结论


def test_tg_private_api_failure_keeps_presence_line_and_fabricates_nothing() -> None:
    api = _Api(responses={}, fail={"get_chat"})
    body = _cap(api)(_private_message(), None).body
    assert "没答上" in body and "不等于对方没设置" in body
    assert "个性签名：" not in body
    assert "会话号（chat id）：555" in body  # 会话号是事件自带事实，不因接口抖动而丢


def test_tg_private_unparseable_session_key_never_calls_api() -> None:
    api = _tg_private_api()
    body = _cap(api)(_private_message(session_id="weird"), None).body
    assert api.actions() == []  # 拿不到号就不打接口，不拿猜测值去查
    assert "不猜" in body


def test_tg_private_who_intent_unchanged_without_profile() -> None:
    """参与者腿（按记忆）与 meta 腿互不挟持：只问「跟谁聊过」不打 get_chat。"""
    api = _tg_private_api()
    _cap(api)(_private_message(plain_text="跟谁聊过"), None)
    assert api.actions() == []  # reader 未注入 → 参与者走「读不出」句，无 API 依赖


# ---------------------------------------------------------------------------
# ③ 邮件：会话元信息腿 + 「有/没接/真没有」三态分说
# ---------------------------------------------------------------------------


def test_mail_profile_declares_no_group_and_owns_unwired_cells() -> None:
    result = _cap(_Api(responses={}))(_mail_message(), None)
    body = result.body
    assert "邮件没有「群」这种对象" in body
    assert "收信账户：shore@example.invalid" in body
    assert "发件人地址：lan@example.invalid" in body
    # 昵称这格：适配器解得出（From 显示名），是摄取链没带——句子里必须点破，
    # 不许写成「邮件没有昵称概念」。
    assert "邮件头里有这个字段" in body
    assert "To/Cc" in body and "是我没接上，不是邮件协议没有" in body


def test_mail_profile_with_display_name_already_wired_shows_it() -> None:
    """摄取票 T-META-INGEST-1 落地后本行为自动跟随：字段在 ⇒ 直接报，无「没接」句。"""
    message = _mail_message(sender_display_name="阿澜")
    body = _cap(_Api(responses={})) (message, None).body
    assert "发件人昵称（From 显示名）：阿澜" in body
    assert "邮件头里有这个字段" not in body


def test_mail_bcc_is_the_only_structurally_absent_recipient_cell() -> None:
    body = _cap(_Api(responses={}))(_mail_message(), None).body
    assert "密送 Bcc 除外" in body and "那一格是真没有" in body
    # 且不许反向断言：没读到 Bcc ≠「对方没有密送任何人」。
    assert "没有密送任何人" not in body


def test_mail_partials_line_appears_once_for_profile_and_who() -> None:
    result = _cap(_Api(responses={}))(_mail_message(plain_text="群信息 跟谁聊过"), None)
    assert result.body.count("我只看得见发件人这一位") == 1


def test_mail_qq_style_intents_do_not_fabricate_group_rows() -> None:
    """负锁：邮件里问群资料，回答不得出现「群名：/群主：/人数：」任何编造行。"""
    for text in ("群信息", "群主是谁", "群人数", "群公告"):
        body = _cap(_Api(responses={}))(_mail_message(plain_text=text), None).body
        assert "群名：" not in body and "群主：" not in body and "人数：" not in body, text


# ---------------------------------------------------------------------------
# ④ QQ 行为零变更回归（本波只在非 group 分支加了平台判定，QQ 私聊必须原样）
# ---------------------------------------------------------------------------


def test_qq_private_profile_still_gets_the_hint() -> None:
    api = _Api(responses={})
    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot",
        session_id="123",
        session_type=SessionType.PRIVATE,
        sender_id="123",
        plain_text="群信息",
    )
    body = _cap(api)(message, None).body
    assert "群信息要在群里问才行" in body
    assert api.actions() == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
