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

import re

import pytest

from plugins.bot_unified_runtime.domains.ops.monitor.error_report import _SECRET_KEY_RE
from plugins.bot_unified_runtime.domains.render import plain_text as _pt
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
    assert "EMBEDDEDKEY56789" not in once
    assert "ABCDEFGH1234" not in once
    assert "AABCDEFGHIJKLMNOPQRSTU" not in once
    assert "a94a8fe5ccb19ba61c4c0873d391e9876f8f9e1c" not in once
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


# ==================== ATK-OUTB 票1/票6：嵌词·短密钥·裸高熵（2026-09-27 复查升格）====
# SEAT-ATK-OUTBOUND 探针 A 段的三个盲区形态（嵌词 visk- / sk- 后 <8 字符 /
# 裸高熵串）在修后必须被同一咽喉打掉（反向锁＝旧存活样本今翻绿），同时
# desk-/task- 一类「词+连字符+编号」日常形态必须恒等（防误伤锁）。
def test_embedded_word_key_masked() -> None:
    # 探针 A2/A10 与 D2 的嵌词形态：修前原样存活，修后必须无 key 体。
    a2 = redact_local_secrets("allowlist: visk-EMBEDDEDINSNAMES5678901234 ok")
    assert "EMBEDDEDINSNAMES5678901234" not in a2
    assert "sk-<已隐藏>" in a2
    a10 = redact_local_secrets("visk-EMBEDDEDKEY56789")
    assert "EMBEDDEDKEY56789" not in a10
    # D2：纯字母长段走「词干-长段」尺，键名与词干前缀保留（grep 契约面）。
    d2 = redact_local_secrets("kind=server-xsk-AABCDEFGHIJKLMNOPQRSTU")
    assert "AABCDEFGHIJKLMNOPQRSTU" not in d2
    assert d2.startswith("kind=server-")


def test_cjk_adjacent_and_short_key_masked() -> None:
    # 原 `\b` 视 CJK 为词字符：紧贴中文的 sk- 整段漏网；短密钥 {<8} 同样漏。
    cjk = redact_local_secrets("密钥是试sk-ABCDEFGH1234 收好")
    assert "ABCDEFGH1234" not in cjk
    assert "sk-<已隐藏>" in cjk
    short = redact_local_secrets("示例 sk-abc123 不算长")
    assert "sk-abc123" not in short
    # 阈值边界反向：sk- 后不足 4 位视为示例/占位，不误伤。
    assert redact_local_secrets("占位 sk-abc 不动") == "占位 sk-abc 不动"


def test_bare_high_entropy_masked_pure_digits_survive() -> None:
    hex40 = "指纹 a94a8fe5ccb19ba61c4c0873d391e9876f8f9e1c 结束"
    out = redact_local_secrets(hex40)
    assert "a94a8fe5ccb19ba61c4c0873d391e9876f8f9e1c" not in out
    assert "<已隐藏>" in out
    b64 = "载荷 dGhpcyBpcyBhIHRlc3QgcGF5bG9hZFNUUklORzEyMzQ1Ng== 结束"
    assert "dGhpcyBpcyBhIHRlc3QgcGF5bG9hZFNUUklORzEyMzQ1Ng" not in redact_local_secrets(b64)
    # 纯数字长编号（无字母）与纯大写字母串不满足字符类别混合——必须恒等。
    digits = "订单 2026092712345678901234567890123456789012 号"
    assert redact_local_secrets(digits) == digits
    shout = "好的" + "B" * 60 + "结束"
    assert redact_local_secrets(shout) == shout


def test_word_hyphen_number_forms_not_masked() -> None:
    # 防误伤回归（报告票1 点名的 desk-12345678 一族）：`sk-` 邻字母且值为
    # 纯数字/纯字母短段时，两把嵌词尺都不许动它。
    for text in (
        "desk-12345678",
        "task-123",
        "task-12345678",
        "risk-assessment",
        "mask-12345678",
        "husky-abcdefgh1234",
    ):
        assert redact_local_secrets(text) == text, text


def test_new_legs_idempotent() -> None:
    leak = (
        "visk-EMBEDDEDKEY56789 试sk-ABCDEFGH1234 "
        "kind=server-xsk-AABCDEFGHIJKLMNOPQRSTU "
        "a94a8fe5ccb19ba61c4c0873d391e9876f8f9e1c"
    )
    once = redact_local_secrets(leak)
    assert "EMBEDDEDKEY56789" not in once
    assert "ABCDEFGH1234" not in once
    assert "AABCDEFGHIJKLMNOPQRSTU" not in once
    assert "a94a8fe5ccb19ba61c4c0873d391e9876f8f9e1c" not in once
    assert redact_local_secrets(once) == once


def test_new_legs_keep_ops_grep_tokens_identity() -> None:
    # 运维 grep 契约样本族（技术行的键名/代号/编号）在新三尺下必须逐字恒等。
    line = (
        "[运行时告警] stage=llm kind=timeout detail=chain=3跳全败 "
        "last=axon-grok-46:timeout retryable=false attempts=3 "
        "debug_id=dbg_a390ad114304 session_type=private"
    )
    assert redact_local_secrets(line) == line


# ==================== M-2：厂商前缀 key 族（S-ATK-RENDER 2026-09-28）====
# 评审探针实锤三形态修前 PLAIN：ghp_+36（词干无连字符、尾段<40，五把旧尺
# 两头落空）、xoxp- 多段（每段<20，键值腿无上下文）、AKIA+16（无词干腿）。
# 修法在既有咽喉 plain_text.py 上扩腿（_VENDOR_PREFIX_KEY_RE），禁第二真身。
# ⚠ 合成令牌一律运行时拼接（本仓常驻门 test_secret_scan_tracked.py 的在册
# 口径：测试件禁止出现可被 F1 尺扫到的连续凭据字面量，点名册棘轮只降不升）。
_GHP_BODY = "aBcDeFgHiJkLmNoPqRsTuVwXyZ" + "0123456789"
_GHP_TOKEN = "ghp_" + _GHP_BODY
_XOXP_TOKEN = (
    "xoxp-" + "123456789012-123456789012" + "-34567890123-abcdef1234567890abcdef12"
)


def test_vendor_prefix_keys_masked() -> None:
    ghp = redact_local_secrets(f"仓库令牌 {_GHP_TOKEN} 收好")
    assert _GHP_BODY not in ghp
    assert _PLACEHOLDER in ghp
    slack = redact_local_secrets(f"slack={_XOXP_TOKEN}")
    assert "123456789012-34567890123" not in slack
    assert "abcdef1234567890abcdef12" not in slack
    aws = redact_local_secrets("AWS AKIA1234567890ABCDEF 别再贴了")
    assert "AKIA1234567890ABCDEF" not in aws
    assert _PLACEHOLDER in aws
    temp = redact_local_secrets("临时凭证 ASIA1234567890ABCDEF")
    assert "ASIA1234567890ABCDEF" not in temp
    fine = redact_local_secrets(
        "github_pat_11AABCD01abcdef0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    )
    assert "11AABCD01abcdef0123456789" not in fine


def test_vendor_digitless_forms_reach_scan_via_sentinel() -> None:
    # 快路径哨兵活性锁：纯字母 ghp 体与纯大写字母 AKIA 体**不含数字、不含
    # 连字符**，既有哨兵一条都不认——哨兵元组摘掉后这两条会原样穿过快路径
    # （注毒自证在 %TEMP% 副本上做，见本波席位报告）。
    pure_letters_body = "abcdefghijklmnopqrstuvwxyz" + "ABCDEFGHIJ"
    out = redact_local_secrets(f"令牌 ghp_{pure_letters_body} 收好")
    assert pure_letters_body not in out
    assert _PLACEHOLDER in out
    alpha_key = "AKIA" + "ABCDEFGHIJKLMNOPQRSTUVW"
    assert alpha_key not in redact_local_secrets(alpha_key)


def test_vendor_short_and_prose_forms_not_masked() -> None:
    # 防误伤：低于阈值（体段<16）视为示例/占位不动；日常行文不误伤。
    for text in (
        "ghp_abc123 太短是示例",
        "xoxo 抱抱",
        "patience 是美德",
        "GitHub 仓库（无下划线形态）",
        "Asia 区域部署",
        "AKIA 前缀本身不是 key",
        "deprecation_note 这个词含 pat_ 但不是令牌",
    ):
        assert redact_local_secrets(text) == text, text


def test_vendor_legs_idempotent() -> None:
    leak = (
        f"{_GHP_TOKEN} {_XOXP_TOKEN} "
        "AKIA1234567890ABCDEF"
    )
    once = redact_local_secrets(leak)
    assert _GHP_BODY not in once
    assert "123456789012-34567890123" not in once
    assert "AKIA1234567890ABCDEF" not in once
    assert redact_local_secrets(once) == once


def test_vendor_key_in_bare_pair_keeps_key_name() -> None:
    # 结构性腿先行口径不回退：token=ghp_… 先被厂商腿打掉 key 本体，
    # 输出仍保留键名可 grep（与 F-01 ④ 既有形态同形）。
    out = redact_local_secrets(f"token={_GHP_TOKEN} 收尾")
    assert _GHP_BODY not in out
    assert "token=" in out


# ==================== E-04 打码形态表缺口波（INCIDENT-20260930 §五「打码形态缺口」）====
# 事故卷宗点名、HEAD 与复原工作树都认不出的形态：邮箱 / 11 位手机号 / 内网 IP 字面量 /
# 无盘符 POSIX 与相对路径 / UNC / cookie= / 非 Bearer 的裸 Authorization: / 非 http 的
# URI userinfo（postgres://、mysql://）。**QQ 号形态主动放弃**：5-11 位纯数字与行情价、
# 国债期限、群号、message_id、时间戳同形，判据不可收敛（宁可不吞正常输出）。
# 新增形态一律**保守掩码**（留首尾若干字符 + 中间 ``***``），绝不整段吞。
# ⚠ 合成料按本仓在册口径：值取小写散文形或含 sample/testonly，绝不写可被 F1 尺扫到的
#   连续凭据字面量（常驻门 tests/test_secret_scan_tracked.py）。
_MOBILE = "138" + "123" + "45678"
_EMAIL_LEAK = "alice.zhang@example.com"


# --------------------------------------------------------------- 邮箱（PII）
def test_email_local_part_masked_domain_kept() -> None:
    out = redact_local_secrets(f"回信到 {_EMAIL_LEAK} 就行")
    assert "alice.zhang" not in out
    assert "alice" not in out
    # 域名整段保留 ⇒ 仍看得出是哪家；本地段只留首尾各一字符。
    assert "a***g@example.com" in out, out


@pytest.mark.parametrize(
    "text",
    (
        "@所有人 今晚八点开会",  # 群提及：无本地段无域名点
        "叫我 user@host 就行（没有顶级域）",
        "汇率 1 USD @ 7.18 CNY",  # 空格隔开，不构成地址
        "分数 a/b 与 c@d 两条线",
    ),
)
def test_email_lookalikes_survive(text: str) -> None:
    assert redact_local_secrets(text) == text, text


# ------------------------------------------------------------- 11 位手机号
def test_cn_mobile_masked_keeps_head_and_tail() -> None:
    out = redact_local_secrets(f"我的号 {_MOBILE}，有事打")
    assert _MOBILE not in out
    assert "138***5678" in out, out


@pytest.mark.parametrize(
    "text",
    (
        "群里 1023456789 记得加",  # 10 位群号
        "消息 7654321098765432109 撤回",  # 19 位 message_id
        "时间戳 1759219200000 与 1759219200",  # 13 位 / 10 位
        "市值 19550721080.0 亿元",  # 11 位整数带小数（行情面实料）
        "编号 1234567890123",
        "session=group:13800138000",  # 冒号后紧跟＝标识符位，不打
        "订单 20260930-1381234567",  # 连字符邻位
        "比例 1:3812345678",
    ),
)
def test_digit_runs_that_are_not_mobile_survive(text: str) -> None:
    assert redact_local_secrets(text) == text, text


# --------------------------------------------------------- 内网 IP 字面量
def test_private_ip_masked_keeps_network_and_last_octet() -> None:
    out = redact_local_secrets("网关 192.168.10.77，从 10.0.0.8 跳")
    assert "192.168.10.77" not in out
    assert "10.0.0.8" not in out
    # 网段与末段保留：人仍看得出是哪家内网，中间主机位抹掉。
    assert "192.168.***.77" in out, out
    assert "10.***.***.8" in out, out


@pytest.mark.parametrize(
    "text",
    (
        "本地网关 http://127.0.0.1:8090/v1 正常",  # 回环＝本项目运维面常驻地址，有意不打
        "公共 DNS 8.8.8.8 与 114.114.114.114",
        "版本 10.0.19045.2 与 10.0.150.999.1",  # 四段版本号（越界段非合法 octet）
        "超时 10.0 秒，重试 3 次",
        "收益 2.15% 对 3.99%",
        "子网 192.168.1.256 不合法",
    ),
)
def test_loopback_public_and_four_part_versions_survive(text: str) -> None:
    assert redact_local_secrets(text) == text, text


# ------------------------------------------------- POSIX / 相对 / UNC 路径
def test_posix_and_relative_and_unc_paths_masked() -> None:
    home = redact_local_secrets("配置在 /home/celestia/.config/app.yaml 里")
    assert "celestia" not in home
    assert "/home" in home and "app.yaml" in home and "***" in home
    rel = redact_local_secrets("记忆库 data/chat_memory.sqlite3 涨到 800MB")
    assert "chat_memory" not in rel
    assert "data" in rel and "sqlite3" in rel and "***" in rel
    unc = redact_local_secrets(r"共享 \\nas01\c$\backup\notes.db 读不到")
    assert "nas01" not in unc and "backup" not in unc
    assert "\\\\" in unc and "notes.db" in unc and "***" in unc


@pytest.mark.parametrize(
    "text",
    (
        "命令 /bot help 与 /bot reply 都能用",  # 触发词不是路径
        "细则见 docs/HANDBOOK.md 与 plugins/bot_unified_runtime/config.py",
        "接口 https://example.com/api/v1/users 正常",
        "比例 3/4，A/B 测试，路径分隔符用 /",
        "真 key 只在 .env，模板是 .env.example",
        "出图落 data/cards/ 目录（非在册敏感后缀）",
    ),
)
def test_non_local_paths_and_command_words_survive(text: str) -> None:
    assert redact_local_secrets(text) == text, text


# ------------------------------------------------------------------ cookie
def test_cookie_pair_masked_name_kept() -> None:
    out = redact_local_secrets("Set-Cookie: sid_ab=sample-login-cookie; Path=/")
    assert "sample-login-cookie" not in out
    assert "Set-Cookie:" in out, out
    bare = redact_local_secrets("cookie=sample-login-cookie")
    assert "sample-login-cookie" not in bare
    assert f"cookie={_PLACEHOLDER}" in bare, bare


@pytest.mark.parametrize(
    "text",
    (
        "Cookie 里存的是你的登录态，别乱贴给我",
        "cookie_header 与 cookie_file 都是变量名",
        "饼干 cookie 是巧克力味的",
        "册子在 domains/link_parse/parsers/cookies.py",
    ),
)
def test_cookie_prose_and_identifiers_survive(text: str) -> None:
    assert redact_local_secrets(text) == text, text


# ------------------------------------------------ 非 Bearer 的裸 Authorization
def test_non_bearer_authorization_masked_scheme_kept() -> None:
    out = redact_local_secrets("Authorization: Basic sample-login-value 也有问题")
    assert "sample-login-value" not in out
    assert "Authorization: Basic" in out, out
    bare = redact_local_secrets("authorization=sample-login-value")
    assert "sample-login-value" not in bare
    assert f"authorization={_PLACEHOLDER}" in bare, bare


@pytest.mark.parametrize(
    "text",
    (
        "Authorization 头必须带上，缺了会被网关拒",
        "authorization: 请管理员在控制台确认后再放行这条",  # 中文行文＝值类不认
        "authorization=AuthorizationPackage",  # 纯字母值＝类型名/标识符形（混合类牙齿放行）
        "author 与 authorization 两个词都别当成密钥名",
    ),
)
def test_authorization_prose_survive(text: str) -> None:
    assert redact_local_secrets(text) == text, text


def test_bearer_leg_still_first_for_authorization_bearer() -> None:
    # 既有 Bearer 形态行为零漂移（硬约束 1）：Bearer 腿先动，新 Authorization
    # 腿随后看到的是占位符，不叠第二层掩码。
    out = redact_local_secrets("Authorization: Bearer abcdef123456XYZ 别外传")
    assert f"Bearer {_PLACEHOLDER}" in out, out
    assert "abcdef123456XYZ" not in out
    assert "<已隐藏><已隐藏>" not in out


# ------------------------------------------------------- 非 http 的 URI userinfo
def test_non_http_uri_userinfo_masked_host_kept() -> None:
    out = redact_local_secrets("连的是 postgres://appuser:sample-db-pass@db.internal:5432/app")
    assert "sample-db-pass" not in out and "appuser" not in out
    assert f"postgres://{_PLACEHOLDER}@db.internal:5432/app" in out, out
    mysql = redact_local_secrets("mysql://root:sample-db-pass@10.0.0.9:3306/d")
    assert "sample-db-pass" not in mysql and "root:" not in mysql
    assert f"mysql://{_PLACEHOLDER}@" in mysql, mysql


@pytest.mark.parametrize(
    "text",
    (
        "连接串 postgres://appuser@db.internal:5432/app 没有密码段",
        "文档在 https://example.com/a?b=1 没有凭据段",
        "redis://db.internal:6379/0 只有主机",
    ),
)
def test_passwordless_dsn_survives(text: str) -> None:
    assert redact_local_secrets(text) == text, text


# --------------------------------------------------------------- 幂等与不吞正常输出
def test_new_form_legs_idempotent() -> None:
    leak = (
        f"联系 {_EMAIL_LEAK} 或 {_MOBILE}；内网 192.168.10.77 与 10.0.0.8；"
        "路径 /home/celestia/.config/app.yaml 与 data/chat_memory.sqlite3 与 "
        + r"\\nas01\c$\backup\notes.db"
        + "；Set-Cookie: sid_ab=sample-login-cookie; "
        "Authorization: Basic sample-login-value; "
        "postgres://appuser:sample-db-pass@db.internal:5432/app"
    )
    once = redact_local_secrets(leak)
    for secret in (
        "alice.zhang", _MOBILE, "192.168.10.77", "10.0.0.8", "celestia",
        "chat_memory", "nas01", "sample-login-cookie", "sample-login-value",
        "sample-db-pass", "appuser",
    ):
        assert secret not in once, secret
    assert redact_local_secrets(once) == once


def test_numeric_finance_and_ops_copy_byte_identical() -> None:
    # 数字面大锁（硬约束 2）：行情价、汇率、国债收益率、北向成交额、群号、
    # message_id、时间戳、四段版本号、微元账单——新增数字类腿之后必须逐字节不动。
    line = (
        "上证指数 3142.58 跌 0.42%，美元兑人民币 7.1853，10 年期国债收益率 2.15%，"
        "北向成交 8,341,000,000.00 元（成交额口径，净买入早已停止披露）；"
        "群 1023456789 消息 7654321098765432109 时间戳 1759219200000 "
        "版本 10.0.19045.2 市值 19550721080.0 成本 1234567 微元"
    )
    assert redact_local_secrets(line) == line


def test_alert_technical_line_still_survives_new_legs() -> None:
    # 既有 grep 契约锁的扩面（同 test_new_legs_keep_ops_grep_tokens_identity 一把尺）：
    # 新腿不许动键名、代号与 WS 回环地址。
    line = (
        "[运行时告警] stage=llm kind=timeout detail=chain=3跳全败 "
        "ws=ws://127.0.0.1:3001 last=axon-grok-46:timeout retryable=false "
        "debug_id=dbg_a390ad114304 session_type=private"
    )
    assert redact_local_secrets(line) == line


# ------------------------------------------------------------------ 注毒自证
# 每条新形态的正向锁都必须**有牙**：把对应腿摘成永不匹配的模式，泄漏原文必须原样
# 存活（证明判据真的在工作，而不是别腿顺手打掉、或恒真的掩码在自证）。
_POISON_CASES = (
    ("_EMAIL_RE", "alice.zhang@example.com", "alice.zhang"),
    ("_CN_MOBILE_RE", "我的号 13812345678", "13812345678"),
    ("_PRIVATE_IP_RE", "网关 192.168.10.77", "192.168.10.77"),
    ("_POSIX_PATH_RE", "在 /home/celestia/app.yaml 里", "celestia"),
    ("_REL_SENSITIVE_PATH_RE", "库 data/chat_memory.sqlite3", "chat_memory"),
    ("_UNC_PATH_RE", r"共享 \\nas01\c$\backup\notes.db", "nas01"),
    ("_COOKIE_PAIR_RE", "cookie=sample-login-cookie", "sample-login-cookie"),
    ("_AUTH_HEADER_RE", "Authorization: Basic sample-login-value", "sample-login-value"),
    ("_DB_URI_USERINFO_RE", "postgres://appuser:sample-db-pass@db.internal:5432", "sample-db-pass"),
)


def _neutralize(pattern: re.Pattern[str]) -> re.Pattern[str]:
    """把一条腿摘成「永不匹配」，但**保留组号与组名**——各腿的替换模板里写着
    ``\\1``/命名组，直接换成空模式会让 re.sub 先抛 ``invalid group reference``，
    那枚红是技术手段的红、不是判据的红。"""
    return re.compile(r"(?!)" + pattern.pattern, pattern.flags)


@pytest.mark.parametrize(("attr", "leak", "secret"), _POISON_CASES)
def test_each_new_leg_has_teeth(monkeypatch: pytest.MonkeyPatch, attr: str, leak: str, secret: str) -> None:
    # 正向锁先立（不打码＝红），再把该腿摘成永不匹配的模式复跑同一判据：
    # 泄漏必须**原样存活**，否则说明别的腿恒真、或这条锁是空的。
    assert secret not in redact_local_secrets(leak), leak
    monkeypatch.setattr(_pt, attr, _neutralize(getattr(_pt, attr)))
    assert secret in redact_local_secrets(leak), f"{attr} 被摘掉后仍打码 ⇒ 该腿没牙"


def test_new_leg_attributes_all_exist() -> None:
    # 名册锁：新腿一律住在同一咽喉（禁第二真身），名字不许被悄悄改名躲过上一条测试。
    for attr, _leak, _secret in _POISON_CASES:
        assert hasattr(_pt, attr), attr
        assert isinstance(getattr(_pt, attr), re.Pattern), attr


@pytest.mark.parametrize(
    ("leak", "secret"),
    (
        ("cookie=sample_login_value", "sample_login_value"),  # 除 "cookie" 外无任何旧哨兵
        ("Authorization: Basic sample_value_x", "sample_value_x"),  # 只靠 "authorization"
        ("配置 /home/celestia/x.yaml", "celestia"),  # 只靠 "/"
        ("库 data/chat_memory.sqlite3", "chat_memory"),  # 只靠 "/"
        (r"共享 \\nasserver\cshare\notes.db", "nasserver"),  # 只靠单个 "\"
        ("联系电话 13812345678", "13812345678"),  # 旧「含数字」哨兵
        ("邮箱 alice.zhang@example.com", "alice.zhang"),  # 旧 "@" 哨兵
        ("内网 192.168.10.77", "192.168.10.77"),  # 旧「含数字」哨兵
        ("postgres://appuser:sampledbpass@db.internal:5432", "sampledbpass"),  # 旧 ":/"
    ),
)
def test_fast_path_sentinels_reach_each_new_leg(leak: str, secret: str) -> None:
    # 哨兵活性锁：每条新形态都必须在**单行自料**里被打到——前五条除新增哨兵外
    # 不含任何旧标记，快路径一旦少了对应哨兵就原样返回（当场红）；后四条确认
    # 复用旧哨兵的那三形（数字 / @ :/）同样触达慢路径。
    assert secret not in redact_local_secrets(leak), leak


# ------------------------------------------------- 台账 #55★ 复测：嵌词 `sk-`
@pytest.mark.parametrize(
    "stem",
    ("visk-", "xsk-", "_sk-", "desk9sk-", "试sk-"),
)
def test_ledger_55_embedded_sk_prefix_now_recognised(stem: str) -> None:
    # #55★ 记账的「redact_local_secrets 不认嵌词 sk-」在 ATK-OUTB 票1 已解，
    # 本条是缺口波复跑的那一遍现算：`sk-` 前有字母/下划线、或紧贴中文，都必须打掉。
    body = "embed" + "key" + "99887766"
    out = redact_local_secrets(f"键是 {stem}{body}")
    assert body not in out, stem
    assert "sk-<已隐藏>" in out, out

