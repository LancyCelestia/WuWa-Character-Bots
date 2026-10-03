"""Mail 信头 RFC2047 显示名解码（席9R 续做）的判据锁。

锁四件事：

① 解码腿：``=?utf-8?B?..?=`` 与 ``=?gbk?B?..?=`` 编码显示名经摄取链
   （``fetch_mail_by_uid`` → ``sender.name``）解成人话，进 ``build_mail_header_block``
   的「发件人显示名」。
② 幂等：普通 ASCII / 已解出的非 ASCII 名逐字节不变（库侧对规范编码字本就能解，
   本解码是摄取链兜底，绝不能把好名改坏）。
③ 回退腿：畸形编码字（缺 ``?=``）、未知字符集（LookupError）→ 原值原样回，
   绝不抛出——不打断收信口径与头块腿一致。
④ 地址侧：编码字族地址本就正确、``sender.id`` 一字不改。裸非 ASCII（未编码）
   显示名曾被库侧 mailparser 整串塞进 id（name 落空串）——该族恢复已由席35
   落地（2026-10-03 用户授权，``restore_mail_sender_address``）：摄取链拆回
   「名+址」。席9R 时该恢复超出本席授权、登记为遗留，本件原「诚实跳过」
   现状锁由接任锁取代（``tests/test_mail_bare_sender_address_restore.py``）。

全部离线：假 IMAP 响应，零网络、零真实凭据、零 Runtime 写。
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.transport.mail.mail_adapter import (
    build_mail_header_block,
    decode_rfc2047_display_name,
    fetch_mail_by_uid,
)


def _b64_word(name: str, charset: str = "utf-8") -> str:
    """把显示名按 RFC2047 B 编码成单个编码字（测试内动态生成，免魔法常量）。"""
    payload = base64.b64encode(name.encode(charset)).decode("ascii")
    return f"=?{charset}?B?{payload}?="


# ---------------------------------------------------------------------------
# ①②③ 纯单元：decode_rfc2047_display_name
# ---------------------------------------------------------------------------


def test_decodes_utf8_b_encoded_word() -> None:
    assert decode_rfc2047_display_name(_b64_word("阿澜")) == "阿澜"


def test_decodes_gbk_b_encoded_word() -> None:
    assert decode_rfc2047_display_name(_b64_word("守岸人", "gbk")) == "守岸人"


def test_plain_and_already_decoded_names_are_verbatim() -> None:
    assert decode_rfc2047_display_name("Alan") == "Alan"
    assert decode_rfc2047_display_name("阿澜") == "阿澜"


def test_malformed_encoded_word_falls_back_to_raw() -> None:
    raw = "=?utf-8?B?6Zi/5r6c"  # 缺 ?= 收尾：不可解
    assert decode_rfc2047_display_name(raw) == raw


def test_unknown_charset_falls_back_to_raw() -> None:
    raw = "=?x-never-a-real-charset-9?B?6Zi/5r6c?="
    assert decode_rfc2047_display_name(raw) == raw


def test_empty_input_stays_empty() -> None:
    assert decode_rfc2047_display_name("") == ""


# ---------------------------------------------------------------------------
# ④ 摄取链接线：fetch_mail_by_uid → sender.name / 信头块
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, result: str = "OK", lines: list[bytes] | None = None) -> None:
        self.result = result
        self.lines = lines if lines is not None else []


def _raw_mail(from_header: str) -> bytes:
    mail = MIMEText("正文占位", "plain", "utf-8")
    mail["Subject"] = "季度报告"
    mail["From"] = from_header
    mail["To"] = "Shorekeeper <bot@example.com>"
    mail["Message-ID"] = "<rfc2047-seat9r@example.com>"
    mail["Date"] = formatdate(localtime=False)
    return mail.as_bytes()


class _ScriptedIMAP:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    async def uid(self, command: str, *criteria: str) -> Any:
        if command == "FETCH":
            return _Response(lines=[bytearray(b"* 1 FETCH (RFC822 {n}"), self.raw])
        return _Response()


@pytest.mark.asyncio
@pytest.mark.parametrize("charset", ["utf-8", "gbk"])
async def test_fetch_decodes_display_name_into_header_block(charset: str) -> None:
    name = "阿澜" if charset == "utf-8" else "守岸人"
    mail = await fetch_mail_by_uid(
        _ScriptedIMAP(_raw_mail(f"{_b64_word(name, charset)} <lan@example.com>")),
        "1",
    )
    assert mail is not None
    # ① 解码腿：显示名解出进 sender.name（信头块的唯一取用位）。
    assert mail.sender.name == name
    # ④ 地址不动：sender.id 一字不改。
    assert mail.sender.id == "lan@example.com"
    block = build_mail_header_block(mail)
    assert f"发件人显示名：{name}" in block
    assert "bot@example.com" in block


@pytest.mark.asyncio
async def test_fetch_restores_raw_non_ascii_display_name_and_address() -> None:
    """裸非 ASCII 显示名（未编码）：mailparser 整串塞进 id＝库侧既有行为，席35
    地址侧恢复（2026-10-03 用户授权）后摄取链拆回「名+址」——name 解出、
    id 恢复真实地址、信头块带上显示名（解不动时仍不炸摄取链）。"""
    mail = await fetch_mail_by_uid(
        _ScriptedIMAP(_raw_mail("阿澜 <lan@example.com>")),
        "1",
    )
    assert mail is not None
    assert mail.sender.name == "阿澜"
    assert mail.sender.id == "lan@example.com"
    block = build_mail_header_block(mail)
    assert "发件人显示名：阿澜" in block


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
