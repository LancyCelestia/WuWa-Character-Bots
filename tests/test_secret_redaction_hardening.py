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
from pathlib import Path

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


# ==================== W3 收尾：`_KEYED_LONG_RUN_RE` 的左右边界 ====================
# 这枚尺原先只活在 `alerts._alert_token`（喂的是**清洗过的单代号**，词干天然在串首），
# 升为全局咽喉后没带边界 ⇒ 在自然行文里从词干**内部**起匹配、整段咬掉只剩首字母。
# 下列反向锁此前**无一条锁住**（票1 段那条 `kind=server-xsk-…` 实为嵌词腿代打），
# 现按实跑形态钉死：三形必须恒等。
@pytest.mark.parametrize(
    "text",
    (
        "session-1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d",  # 曾→ `s‹已隐藏密钥形态›`
        "feature-202609301234567890123",  # 曾→ `f‹…›`
        "anti-disestablishmentarianism 是个长词",  # 曾整词被吞
        "https://cdn.example.com/files-1a2b3c4d5e6f7a8b9c0d1e/app.js",  # URL 路径段
        "看 https://example.com/download/session-1a2b3c4d5e6f7a8b9c0d 这里",
        "构建号 build-20260930-1234 与 debug_id=dbg_a390ad114304 都得原样可 grep",
    ),
)
def test_keyed_long_run_leg_boundaries(text: str) -> None:
    assert redact_local_secrets(text) == text, text


def test_keyed_long_run_residual_risk_on_record() -> None:
    # **在册残留**（不藏）：≤6 字母词干 + ≥20 位含数字长段仍是本腿的靶形，
    # 与真 key 无法从词面区分 ⇒ 形如 `build-<20 位纯数字>` 的构建号仍会被吞。
    # 记成锁＝哪天有人把它「顺手修宽」或「顺手修窄」，这枚红会先叫。
    out = redact_local_secrets("构建号 build-20260930123456789012 结束")
    assert "build-20260930123456789012" not in out, out


@pytest.mark.parametrize(
    "secret",
    (
        "xproj-0123456789abcdef012345",  # 独立词干 + 数字混合长段：本腿的本职
        "svc-AbCdEf0123456789AbCdEf",  # 无数字但大小写混排长段
    ),
)
def test_keyed_long_run_leg_still_has_teeth(secret: str) -> None:
    out = redact_local_secrets(f"令牌 {secret} 收好")
    assert secret not in out, out
    assert "‹已隐藏密钥形态›" in out, out


def test_keyed_long_run_leg_poison_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    # 注毒自证：摘掉本腿后真形态必须回落成原样存活（正向锁有牙），
    # 而被边界挡住的三形仍**恒等**（证明「不吞」不靠别的腿顺手打掉）。
    leak = "令牌 xproj-0123456789abcdef012345 收好"
    assert "xproj-0123456789abcdef012345" not in redact_local_secrets(leak)
    monkeypatch.setattr(_pt, "_KEYED_LONG_RUN_RE", _neutralize(_pt._KEYED_LONG_RUN_RE))
    assert "xproj-0123456789abcdef012345" in redact_local_secrets(leak)
    assert redact_local_secrets("session-1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d") == (
        "session-1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
    )


# ==================== W3 收尾：AxonHub 网关 key 形态（`ah-` + 64 位十六进制）====
# 本机 `.env` 里三个模型/嵌入 key 的实际形态＝`ah-` 后接 64 位十六进制（总长 67，
# 键名 BOT_CHAT_API_KEY / BOT_EMBEDDING_API_KEY / BOT_EMBEDDING_LOCAL_API_KEY）。
# 值本体绝不进测试与报告：下面按**同形态合成**。
#: 32 位 hex × 2 运行时拼接＝本仓在册口径（测试件不许出现可被 F1 尺扫到的连续
#: 凭据字面量），形态与 `.env` 真值同构（`ah-` + 64 位十六进制，总长 67）。
_AH_BODY = "0a1b2c3d4e5f60718293a4b5c6d7e8f9" + "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
_AH_TOKEN = "ah-" + _AH_BODY


def test_axonhub_gateway_key_shape_masked() -> None:
    # 实测结论：**罩得住**——原先靠 `_KEYED_LONG_RUN_RE` 顺带（词干 ah + 长段），
    # 本席给那把尺补边界与混合性牙齿后改由**独立厂商前缀腿**接管，两形都得掉。
    assert len(_AH_BODY) == 64
    for probe in (
        f"网关 key 是 {_AH_TOKEN} 别贴出来",
        f"BOT_CHAT_API_KEY={_AH_TOKEN}",
        f"提示词里回显 ah: {_AH_TOKEN}",
        f"日志泄漏 https://gw.internal/status?k={_AH_TOKEN}",
    ):
        out = redact_local_secrets(probe)
        assert _AH_BODY not in out, probe
        assert _AH_TOKEN not in out, probe


def test_axonhub_key_masked_even_when_long_run_leg_is_neutralized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 关键取舍：不能挂在启发式长段尺上。摘掉 `_KEYED_LONG_RUN_RE` 与 hex/b64 两腿后，
    # `ah-` 仍必须被厂商腿打掉（注毒自证＝反过来说，摘厂商腿它就存活）。
    monkeypatch.setattr(_pt, "_KEYED_LONG_RUN_RE", _neutralize(_pt._KEYED_LONG_RUN_RE))
    monkeypatch.setattr(_pt, "_BARE_HEX_RE", _neutralize(_pt._BARE_HEX_RE))
    monkeypatch.setattr(_pt, "_BARE_B64_RE", _neutralize(_pt._BARE_B64_RE))
    assert _AH_BODY not in redact_local_secrets(f"key {_AH_TOKEN}"), "厂商腿没接管"
    monkeypatch.setattr(
        _pt, "_VENDOR_PREFIX_KEY_RE", _neutralize(_pt._VENDOR_PREFIX_KEY_RE)
    )
    assert _AH_BODY in redact_local_secrets(f"key {_AH_TOKEN}"), "厂商腿摘掉仍打码 ⇒ 有别的恒真尺"


def test_axonhub_stem_in_prose_not_masked() -> None:
    # 防误伤：`ah-` 只有接 ≥40 位十六进制才算 key；感叹词与常规连字符行文恒等。
    for text in (
        "ah- 这算什么写法",
        "ah-0a1b2c 太短是示例",
        "haha- 笑死",
        "sha-1 与 md5 都是旧摘要名",
    ):
        assert redact_local_secrets(text) == text, text


def test_ah_stem_registered_in_vendor_sentinels() -> None:
    # 哨兵名册与腿一一对应（漏登记＝静默不走慢路径的旧坑）。
    assert "ah-" in _pt._VENDOR_KEY_SENTINELS


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
# W3 收尾：本腿**必须带通话类上下文词**才动（原判据不可收敛，见 plain_text._CN_MOBILE_RE
# 注）。正向锁因此一律写成「通话词 + 号码」形；反向锁把主业务面的整数形钉死。
def test_cn_mobile_masked_keeps_head_and_tail() -> None:
    out = redact_local_secrets(f"我的手机号 {_MOBILE}，有事打")
    assert _MOBILE not in out
    assert "138***5678" in out, out
    # 上下文词逐字保留（掩的是号码，不是「这是谁的号码」这件事）。
    assert out.startswith("我的手机号 "), out


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


@pytest.mark.parametrize(
    "text",
    (
        # W3 收尾补的反向锁：整数形是原锁的**空洞**（旧锁只钉了带小数/带千分位形）。
        "市值 19550721080 元",  # 11 位整数：东财口径的「元」直送本腿
        "市值 13,550,721,080 元",  # 同值带千分位
        "群号：13800000000",  # 全角冒号形＝group_info.py 的 f"群号：{group_id}"
        "群号 13800000000",
        "群 13800000000 的白名单已更新",
        "本群 13800000000 与 1023456789 都在册",
        "hotel 13800138000 不是电话",  # 左邻字母：tel 认不到 hotel 的尾巴
        "13800138000 是别人直接贴出来的一串数字",  # 在册缺口：无通话上下文裸号不掩
    ),
)
def test_eleven_digit_integers_without_phone_context_survive(text: str) -> None:
    # 本腿收窄后**主动放弃**的那一半（无上下文裸号）在此登记成锁，不装成已覆盖。
    assert redact_local_secrets(text) == text, text


@pytest.mark.parametrize(
    "text",
    (
        "手机号：13800138000",
        "联系电话 13800138000",
        "我的号码是 13800138000",
        "call 13800138000 找我",
        "TEL=13800138000",
    ),
)
def test_phone_context_forms_masked(text: str) -> None:
    assert "13800138000" not in redact_local_secrets(text), text


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
        # IPv6 **整族有意不做**（W3 收尾在 plain_text 里补了注释记账，此处把现状钉住）：
        # ::1 与 127.0.0.1 同理＝回环；ULA/链路本地在本项目现网零出现；词面正则判
        # 不对零压缩与 zone id，误伤面却是一切含 `::` 的正常行文。
        "监听 [::1]:8080 与 fe80::1 与 fd00::1%eth0",
        "Rust 写法 Foo::new() 与 CSS 的 ::before 选择器",
    ),
)
def test_loopback_public_and_four_part_versions_survive(text: str) -> None:
    assert redact_local_secrets(text) == text, text


# ------------------------------------------------- POSIX / 相对 / UNC 路径
def test_posix_and_relative_and_unc_paths_masked() -> None:
    home = redact_local_secrets("配置在 /home/celestia/.config/app.yaml 里")
    assert "celestia" not in home
    assert "/home" in home and "app.yaml" in home and "***" in home
    # W3 收尾：名册补 `/Users`（macOS 家目录，补前实测**原样存活**），且掩码改成
    # 「留根段与末段、中间整段换 ***」——旧的定长留 5 字符会把 `/Users` `/media`
    # 这种六字母根名自己截断。
    users = redact_local_secrets("日志在 /Users/celestia/Library/App/state.db 里")
    assert "celestia" not in users and "Library" not in users
    assert "/Users" in users and "***" in users, users
    rel = redact_local_secrets("记忆库 data/chat_memory.sqlite3 涨到 800MB")
    assert "chat_memory" not in rel
    assert "data" in rel and "sqlite3" in rel and "***" in rel
    unc = redact_local_secrets(r"共享 \\nas01\c$\backup\notes.db 读不到")
    assert "nas01" not in unc and "backup" not in unc
    assert "\\\\" in unc and "notes.db" in unc and "***" in unc
    # 幂等：POSIX 腿的值类不收 `*` ⇒ 产物永不被自己二次吃掉。
    assert redact_local_secrets(users) == users


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
        f"联系 {_EMAIL_LEAK} 或 手机号 {_MOBILE}；内网 192.168.10.77 与 10.0.0.8；"
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
    ("_CN_MOBILE_RE", "手机号 13812345678", "13812345678"),
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


# ==================== W3 收尾：单源与「夹带件已退役」两把结构锁 ====================
_PLAIN_TEXT_TRUE_HOME = (
    "plugins/bot_unified_runtime/domains/render/plain_text.py"
)


def test_redact_local_secrets_definition_is_unique_in_tree() -> None:
    """全树只准有一处 ``def redact_local_secrets``（真身住 plain_text）。

    `output/plain_text.py` 是再导出垫片：它可以 import，不许自己定义第二份。
    扩谱波把这件从 18,670 B 撑到现在的体量，第二真身一旦冒出来，两边会各自
    长牙、且只有一边被测到（台账 #47 #68 同一族坑）。
    """
    repo_root = Path(__file__).resolve().parents[1]
    hits: list[str] = []
    for path in sorted((repo_root / "plugins").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^def redact_local_secrets\(", text, flags=re.MULTILINE):
            hits.append(str(path.relative_to(repo_root).as_posix()))
    assert hits == [_PLAIN_TEXT_TRUE_HOME], f"出站打码出现第二真身：{hits}"


# 本波从 humanize_reply 里拆出的夹带件（与打码无关、判据不可收敛）。
# 撤销理由与实测四类误伤写在 plain_text.py 的退役注释里；这里是随件的账本行：
# 反例锁随件同批撤、且**不许悄悄长回来**。
def test_flatten_article_scaffolding_is_retired() -> None:
    assert not hasattr(_pt, "flatten_article_scaffolding")
    for gone in ("_ARTICLE_INDEX_HEAD_RE", "_BULLET_HEAD_RE", "_BOLD_MD_RE"):
        assert not hasattr(_pt, gone), gone


@pytest.mark.parametrize(
    "text",
    (
        "一、身份\n\n她叫陈晖洁。",  # 空行必须活着（段间换行归 normalize_paragraph_breaks）
        "一切都会好的。",  # 曾→「切都会好的。」
        "一个眼神就说明她在听。",  # 曾→「个眼神就说明她在听。」
        "二十三日见。",  # 曾→「日见。」
        "1.5 倍速听着刚好。",  # 曾→「5 倍速听着刚好。」
        "排行榜\n1. 张三 12.34\n2. 李四 13.10",  # 行首名次必须留着
    ),
)
def test_humanize_reply_no_longer_eats_structure(text: str) -> None:
    assert _pt.humanize_reply(text) == text, text


def test_humanize_reply_still_strips_cliches_after_retirement() -> None:
    # 退役只拆骨架压平那一腿，客套剥离与内心数值打码一字不动。
    out = _pt.humanize_reply("好的！以下是干员资料：\n一、 身份与背景来历\n她叫陈晖洁。")
    assert out == "干员资料：\n一、 身份与背景来历\n她叫陈晖洁。", out
    inner = _pt.humanize_reply("其实你的好感度已经是 0.78 了哦")
    assert "0.78" not in inner and "好感度…保密" in inner, inner


def test_redact_cost_claim_is_not_zero_cost_wording() -> None:
    """docstring 不许再写「热路径零成本」：本波实测每条约 15-18µs（走慢路径时）。

    判据只查**措辞**（成本量级会随腿数漂，写成数就是假账——规则 10）。
    """
    doc = _pt.redact_local_secrets.__doc__ or ""
    assert "零成本" not in doc, doc
    assert "哨兵" in doc, "口径必须说清成本按什么算"
