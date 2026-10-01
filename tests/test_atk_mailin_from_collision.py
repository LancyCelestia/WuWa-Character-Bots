"""S-ATK-MAILINGRESS #21：邮件 From 头是**未认证身份**，裸号形态必须不得穿透摄取咽喉。

病根（结构性无防，非行号坐标）：``nonebot.adapters.mail`` 用 ``mailparser`` 解
From 头，``parse_byte_mail`` 取 ``mail.from_[0][1]`` 原样作 ``sender.id``；
``From: 123456789``（无 @ 的裸 token，RFC 2822 显示名形态，任意互联网寄件方
可写）解析实测返回 ``('', '123456789')`` ⇒ 邮件事件的 ``get_user_id()`` ＝
逐字的 QQ 号形态字符串。根摄取 ``_incoming_from_nonebot_event`` 邮件分支把该
值**原样**填进 ``IncomingMessage.sender_id``；而盘上三族按裸 ``sender_id`` 建键
的存储不分区平台：

- ``policy/roles.py::resolve_roles`` 的 trusted/enterprise/blocked 三腿
  （F-A 只把 admin/super_admin 收进平台域，这三腿仍是裸比）；
- ``character/affinity.py`` 用户好感表（``sender_id TEXT PRIMARY KEY``）；
- ``character/memory_bus_v2.py::_owner_id_for``（owner＝裸 sender）。

即：一枚伪造 From 就能以另一平台某号码的身份写好感、写记忆、领 trusted 脸。
本锁两枚腿：

① 行为腿：无 @ 的邮件 sender 不得逐字穿透摄取咽喉（HEAD 下必红＝攻击成立；
   打上 ATK-MAILIN-01 隔离补丁后绿）；
② 组合腿：同一伪造身份在 ``resolve_roles`` 处领不到 trusted（HEAD 下必红）。

对照腿（HEAD 即绿，防补丁矫枉过正）：带 @ 的正常邮件地址键形逐字不变。

同文件卫生：全部构造走内存对象，不触网、不落库、不写 data/。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from plugins.bot_unified_runtime import _incoming_from_nonebot_event
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    build_role_settings,
)

# 一个"受害者"QQ 号形态：攻击者在 From 头里逐字写它。
VICTIM_QQ = "123456789"


class _FakeMailEvent:
    """最小邮件事件替身（形态对齐 QuietMailMessageEvent 被摄取读取的面）。

    类名与模块名刻意不含 ``.mail`` 子串，适配器判定一律靠显式
    ``adapter_name="mail"`` 入参，不依赖 __module__ 考古。
    """

    def __init__(self, sender_id: str, *, subject: str, body: str) -> None:
        self.sender = SimpleNamespace(id=sender_id, name="")
        self.id = "<fake-message-id@test>"
        self.subject = subject
        self._body = body

    def get_plaintext(self) -> str:
        return self._body

    def get_session_id(self) -> str:
        return f"mail_{self.sender.id}"

    def get_user_id(self) -> str:
        return str(self.sender.id)


def _ingest_mail(sender_id: str) -> Any:
    event = _FakeMailEvent(sender_id, subject="测试主题", body="测试正文")
    return _incoming_from_nonebot_event(
        event,
        bot_id="shorekeeper@example.com",
        adapter_name="mail",
    )


def _role_settings() -> Any:
    config = SimpleNamespace(
        bot_admin_user_ids=[],
        bot_telegram_admin_user_ids=[],
        bot_super_admin_user_ids=[],
        bot_enterprise_user_ids=[],
        bot_trusted_user_ids=[VICTIM_QQ],
        bot_blocked_user_ids=[],
    )
    return build_role_settings(config)


def test_bare_numeric_mail_sender_must_not_pass_ingestion_verbatim() -> None:
    """注毒腿：From 无 @（裸 QQ 号形态）时，sender_id 不得逐字进内部键空间。"""
    message = _ingest_mail(VICTIM_QQ)
    assert message.sender_id != VICTIM_QQ, (
        "伪造 From 的裸号逐字穿透了摄取咽喉：好感/记忆/角色三族裸键存储"
        "全部可被冒名读写（SEAT-ATK-MAILINGRESS 票 Mail-1）"
    )
    assert not message.sender_id.isdigit(), (
        "邮件 sender_id 仍是纯数字形态＝与 QQ 号同键空间，隔离未生效"
    )


def test_forged_sender_cannot_claim_trusted_role() -> None:
    """组合腿：摄取产物直接喂 resolve_roles，trusted 名单不得吃到裸号冒充。"""
    message = _ingest_mail(VICTIM_QQ)
    roles = _role_settings().resolve_roles(message)
    assert "trusted" not in roles, (
        "无认证 From 领到了 trusted——F-A 平台域收口只护了 admin 两腿，"
        "trusted/enterprise/blocked 仍裸比 sender_id，邮件面把这条缺口做实"
    )


def test_well_formed_email_sender_key_is_unchanged() -> None:
    """对照腿：带 @ 的正常地址键形与 session_id 逐字不变（防补丁误伤存量）。"""
    address = "lee@example.com"
    message = _ingest_mail(address)
    assert message.sender_id == address
    assert message.session_id == f"email:{address}"
    assert message.platform == "email"
