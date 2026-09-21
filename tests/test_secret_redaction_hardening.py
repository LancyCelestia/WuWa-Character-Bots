"""出站脱敏与诊断卡密钥正则加固回归（审查 F-01/F-02，2026-09-14）。

F-01：output/plain_text.redact_local_secrets 原仅覆盖 BOT_XXX= 赋值 / sk-
key / 盘符路径三种形态，URL userinfo（https://user:pass@host）、Bearer
token、JWT 三段式、裸键值对（sendkey=x / key=值）全部漏网。
F-02：runtime/error_report._SECRET_KEY_RE 词表漏 sendkey/auth/credential/
proxy/webhook——bot_disconnect_notice_serverchan_sendkey、bot_download_proxy
等真实配置字段能进快照白名单但值打不掉。

每条新正则 ≥2 例：命中打码 + 相邻形态不误伤（author/authorization 词干、
普通 URL 无 userinfo、短值不打码等）。既有 plain_text/error_report 口径
（BOT_= / sk- / 盘符路径）由 test_sdd9_n3re.py 与 test_error_report.py 锁定。
"""
from __future__ import annotations

from plugins.bot_unified_runtime.domains.ops.monitor.error_report import _SECRET_KEY_RE
from plugins.bot_unified_runtime.output.plain_text import redact_local_secrets

_PLACEHOLDER = "<已隐藏>"


# ==================== F-01 ① URL userinfo ====================
def test_url_userinfo_masked_and_host_kept() -> None:
    leak = "数据库连 https://admin:SuperSecret9@db.example.com:5432/app 记得改密"
    out = redact_local_secrets(leak)
    assert "SuperSecret9" not in out
    assert "admin:" not in out
    # host:port/路径保留，仍能定位泄漏发生在哪个服务。
    assert f"https://{_PLACEHOLDER}@db.example.com:5432/app" in out


def test_url_without_userinfo_untouched() -> None:
    text = "文档在 https://example.com/a?b=1 没有凭据段。"
    assert redact_local_secrets(text) == text


# ==================== F-01 ② Bearer token ====================
def test_bearer_token_masked_prefix_kept() -> None:
    leak = "Authorization: Bearer abcdef123456XYZ 别外传"
    out = redact_local_secrets(leak)
    assert "abcdef123456XYZ" not in out
    assert f"Bearer {_PLACEHOLDER}" in out


def test_bearer_lowercase_and_short_token_not_masked() -> None:
    # 短 token（<8 字符）视为示例/占位，不打码。
    text = "bearer abc 与 Bearer xyz 都太短"
    assert redact_local_secrets(text) == text


# ==================== F-01 ③ JWT 三段式 ====================
def test_jwt_masked_as_a_whole() -> None:
    leak = (
        "token 是 eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c 收好"
    )
    out = redact_local_secrets(leak)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in out
    assert "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c" not in out
    assert _PLACEHOLDER in out


def test_jwt_two_segment_form_not_masked() -> None:
    # 两段式（无签名）不构成可重放 JWT，不误伤。
    text = "前缀 eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1 只是演示"
    assert redact_local_secrets(text) == text


# ==================== F-01 ④ 裸键值对 ====================
def test_bare_key_value_pairs_masked() -> None:
    leak = "Server酱 sendkey=SCT1234567890abcd；token=ghp_abcdef12345678；access_token=ea12b0c9d8f7a654"
    out = redact_local_secrets(leak)
    assert "SCT1234567890abcd" not in out
    assert "ghp_abcdef12345678" not in out
    assert "ea12b0c9d8f7a654" not in out
    assert f"sendkey={_PLACEHOLDER}" in out
    # _ 前缀复合键（access_token=）仍按 token 词干命中。
    assert f"access_token={_PLACEHOLDER}" in out


def test_bare_key_short_value_and_word_stems_not_masked() -> None:
    # 短值（<8 字符）不打；keyword= / monkey= 等词干相邻形态不误伤。
    text = "token=abc 很短；keyword=汉语词典；monkey=abcd1234 是变量名"
    assert redact_local_secrets(text) == text


# ==================== 幂等与既有口径共存 ====================
def test_new_forms_idempotent() -> None:
    leak = (
        "https://u:secretvalue88@h.example.com/x sendkey=abcdefgh1234 "
        "Bearer bbbbccccdddd1111 "
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c token=zzzz99998888"
    )
    once = redact_local_secrets(leak)
    assert redact_local_secrets(once) == once
    assert "secretvalue88" not in once and "abcdefgh1234" not in once
    assert "bbbbccccdddd1111" not in once and "zzzz99998888" not in once


# ==================== F-02：诊断卡密钥词表 ====================
def test_secret_key_re_covers_new_stems() -> None:
    for name in (
        "bot_disconnect_notice_serverchan_sendkey",
        "bot_download_proxy",
        "bot_meme_library_proxy",
        "bot_credentials_file",
        "bot_mail_webhook_url",  # 现无此字段，词表前瞻
        "bot_mail_auth",
        "bot_mail_auth_code",  # 下划线续接的 auth 仍命中
    ):
        assert _SECRET_KEY_RE.search(name), name


def test_secret_key_re_spares_author_stem() -> None:
    # author/authors/authorization 等**字母延展**词干不得命中——字母级
    # 边界防误伤（作者类字段、Authorization 头字段名），测试锁死；
    # oauth_ 中段的 auth 同理不命中（provider 名非密钥，凭据由
    # oauth_client_secret 等 secret 词干兜住）。
    for name in (
        "author",
        "bot_chat_author_name",
        "bot_quote_authors",
        "bot_search_authorization_header",
        "bot_chat_oauth_provider",
    ):
        assert _SECRET_KEY_RE.search(name) is None, name
