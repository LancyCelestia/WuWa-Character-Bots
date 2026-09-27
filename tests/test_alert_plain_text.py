"""运行时告警的人话主句（2026-09-25 澜汐裁定：报错提示不得是纯英文键值串）。

她给的两条原文（"现在的报错实在是无法让人看懂"）：

    [运行时告警] stage=onebot kind=retcode_failure detail=retcode_failure retryable=false
    attempts=1 debug_id=dbg_a390ad114304 source_adapter=nonebot source_bot=3958874605 …
    [运行时告警] stage=llm kind=timeout detail=chain=2跳全败 last=axon-grok-46:timeout …

本件钉三件事：①第一句必须是中文人话；②**原来那行技术字段逐字保留**（既有测试与
运维 grep 都吃这行，改格式=拆既有契约）；③认不出的 stage/kind **不许编解释**，
只准点名代号——把没核过的原因写成断言是本仓反复记过的失效形态。
"""

from __future__ import annotations

import re

import pytest

import plugins.bot_unified_runtime.domains.core.contracts as _c
import plugins.bot_unified_runtime.domains.ops.monitor.alerts as plain
from plugins.bot_unified_runtime.domains.core.contracts import OperationalIssue
from plugins.bot_unified_runtime.domains.core.contracts.runtime import RiskLevel
from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
    build_operational_alert_text,
)

SessionType = _c.SessionType


def _text(issue: OperationalIssue, **kwargs: object) -> str:
    merged: dict[str, object] = {
        "source_adapter": "nonebot",
        "source_bot": "3958874605",
        "session_type": SessionType.PRIVATE,
    }
    merged.update(kwargs)
    return build_operational_alert_text(issue, **merged)  # type: ignore[arg-type]


def _head(text: str) -> str:
    """人话部分＝主句 + 逐行字段；最后一行是原样保留的技术原文，不参与判据。"""
    return "\n".join(text.splitlines()[:-1])


def _tech(text: str) -> str:
    return text.splitlines()[-1]


def _has_cjk(value: str) -> bool:
    return re.search(r"[\u4e00-\u9fff]", value) is not None


# ------------------------------------------------------------------ 她举的两例


def test_onebot_retcode_failure_reads_as_chinese() -> None:
    issue = OperationalIssue(
        stage="onebot", kind="retcode_failure", retryable=False, attempts=1,
        debug_id="dbg_a390ad114304", safe_summary="retcode_failure",
    )
    text = _text(issue)
    head = _head(text)
    assert head.startswith("[守岸人告警]"), head
    assert _has_cjk(head)
    assert "协议端拒收" in head
    # 她要看懂"要不要动手"：不可重试必须明说。
    assert "重试也没用" in head


def test_llm_chain_timeout_reads_as_chinese() -> None:
    issue = OperationalIssue(
        stage="llm", kind="timeout", retryable=True, attempts=2,
        debug_id="dbg_115984050c75",
        safe_summary="timeout chain=2 last=axon-grok-46:timeout",
    )
    head = _head(_text(issue, session_type=SessionType.PRIVATE))
    assert head.startswith("[守岸人告警]")
    assert "模型" in head or "想怎么回你" in head
    assert "试了几次：2" in head
    assert "还能重试，你不用管" in head
    assert "会话：私聊" in head


def test_headline_is_not_repeated_by_field_rows() -> None:
    """主句已经说清的事，不再拿同样的措辞占一行（她：一行一个值、别复读）。

    曾经「走哪一步 / 出的什么错」两行＝把主句那两截原样抄一遍，一条消息里
    同一件事出现两次；代号单独留一行给抄查用。
    """
    issue = OperationalIssue(stage="llm", kind="timeout", attempts=2)
    head = _head(_text(issue))
    assert head.count("等回话等超时了") == 1, head
    assert "走哪一步" not in head and "出的什么错" not in head
    assert "代号：llm/timeout" in head


def test_field_labels_are_all_chinese() -> None:
    """逐行字段行首必须是中文标签——「每值一行」不等于「换行版的英文键值串」。"""
    issue = OperationalIssue(stage="llm", kind="timeout", attempts=1, elapsed_ms=30.0)
    lines = _text(issue, source_adapter="onebot").splitlines()
    field_lines = lines[1:-1]  # 首行主句、末行技术原文（逐字保留）
    assert field_lines
    for line in field_lines:
        label, sep, value = line.partition("：")
        assert sep, line
        assert _has_cjk(label), line
        assert value.strip(), line


# ------------------------------------------------------- 技术行必须逐字保留


def test_technical_line_is_preserved_verbatim() -> None:
    issue = OperationalIssue(
        stage="llm", kind="timeout", retryable=True, attempts=2,
        debug_id="dbg_x1", safe_summary="upstream_timeout", elapsed_ms=12.5,
    )
    text = _text(issue, suppressed_count=3)
    tech = _tech(text)
    assert tech.startswith("[运行时告警] stage=llm kind=timeout")
    for token in (
        "detail=upstream_timeout",
        "retryable=true",
        "attempts=2",
        "elapsed_ms=12.5",
        "debug_id=dbg_x1",
        "source_adapter=nonebot",
        "source_bot=3958874605",
        "session_type=private",
        "suppressed_count=3",
    ):
        assert token in tech, token


def test_folded_kinds_still_carry_out() -> None:
    issue = OperationalIssue(stage="llm", kind="timeout", safe_summary="s")
    tech = _tech(_text(issue, folded_kinds=["timeout", "network"]))
    assert "llm_kinds=[timeout|network]" in tech


# --------------------------------------------------------- 认不出来的不许编


def test_unknown_stage_and_kind_names_the_token_instead_of_inventing() -> None:
    issue = OperationalIssue(stage="zephyr_gate", kind="frobnicated", attempts=1)
    head = _head(_text(issue))
    assert head.startswith("[守岸人告警]")
    assert plain.ALERT_UNREGISTERED_MARK in head
    # 代号必须原样点名，否则这行就成了看不懂的中文——两个方向都不许。
    assert "zephyr_gate/frobnicated" in head
    assert _has_cjk(head)


def test_unregistered_fallback_tells_who_acts_and_where_to_look() -> None:
    """兜底句不许只是"我没词"（2026-09-28 用户：太流水账）。

    认不出代号时，这一行是唯一出口，必须自带四要素里的三件：**不编原因**、
    **该谁动＋动哪**（往哪张表补登记）、**现场依据在哪**（detail／排查编号）。
    判据吃常量与去处字面，不抄整句——改措辞不必改测试，删掉出路必被红。
    """
    head = _head(_text(OperationalIssue(stage="zephyr_gate", kind="frobnicated")))
    assert "不猜" in head, f"兜底句丢了「不编原因」这一条：{head}"
    assert "_KIND_PLAIN" in head, f"兜底句没点名补登记的去处：{head}"
    assert "detail" in head and "排查编号" in head, f"兜底句没给现场依据去处：{head}"
    # 反向腿：去处字面必须真存在于生产表名，否则指了个不存在的门。
    assert hasattr(plain, "_KIND_PLAIN"), "去处表已改名，兜底句在指空门"


def test_unknown_kind_with_known_stage_keeps_stage_prose() -> None:
    issue = OperationalIssue(stage="tts", kind="brand_new_failure", attempts=1)
    head = _head(_text(issue))
    assert "语音" in head, "stage 认得就该用它的人话，别整句降级"
    assert "brand_new_failure" in head


# --------------------------------------------------------------- 时间与会话


def test_headline_carries_second_precision_timestamp_with_offset() -> None:
    head = _head(_text(OperationalIssue(stage="llm", kind="timeout")))
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC[+-]\d{2}:\d{2}", head), head


def test_session_wording_follows_session_type() -> None:
    issue = OperationalIssue(stage="llm", kind="timeout")
    assert "私聊" in _head(_text(issue, session_type=SessionType.PRIVATE))
    assert "群聊" in _head(_text(issue, session_type=SessionType.GROUP))


def test_unknown_session_type_falls_back_to_its_value_not_a_guess() -> None:
    issue = OperationalIssue(stage="llm", kind="timeout")
    head = _head(_text(issue, session_type=SessionType.CHANNEL))
    assert "频道" in head, head


# ------------------------------------------------------------------- 脱敏


def test_headline_is_redacted_too() -> None:
    """代号/safe_summary 里夹带的敏感形态不能因为"这是人话句"就绕过脱敏。"""
    issue = OperationalIssue(
        stage="llm",
        kind="timeout",
        safe_summary="sk-abcdefghijklmnopqrstuvwxyz123456 at C:\\\\Users\\\\x\\\\secrets",
    )
    text = _text(issue)
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in text
    assert "<已隐藏>" in text


def test_redaction_applies_to_unregistered_token_path() -> None:
    issue = OperationalIssue(
        stage="vault", kind="leak_sk-abcdefghijklmnopqrstuvwxyz123456"
    )
    head = _head(_text(issue))
    assert "abcdefghijklmnopqrstuvwxyz123456" not in head


# ------------------------------------------------------------- 语义红线回归


@pytest.mark.parametrize(
    ("retryable", "expected"),
    [(True, "还能重试"), (False, "重试也没用")],
)
def test_retryable_wording_is_binary_and_never_promise(
    retryable: bool, expected: str
) -> None:
    issue = OperationalIssue(stage="llm", kind="timeout", retryable=retryable)
    assert expected in _head(_text(issue))


def test_severity_does_not_change_the_headline_claim() -> None:
    """级别只影响路由，不许把"没核实的原因"升级成"确诊"。"""
    for level in (RiskLevel.LOW, RiskLevel.HIGH, RiskLevel.CRITICAL):
        issue = OperationalIssue(stage="llm", kind="timeout", severity=level)
        assert "已确诊" not in _head(_text(issue))


def test_session_plain_covers_every_session_type() -> None:
    """人话主句的「在哪」槽必须覆盖 ``SessionType`` 每一档。

    旧表写的是 ``"mail"``，而枚举值是 ``"email"`` ⇒ 邮件会话查不到，把英文
    代号 ``email`` 直接打进中文主句（违反「报错提示不得纯英文」，E1 P2-2）。
    枚举派生 + 这一把锁：加一档忘了填人话，当场红。
    """
    assert set(plain._SESSION_PLAIN) == {m.value for m in plain.SessionType}, plain._SESSION_PLAIN
    assert all(str(v).strip() and not _is_ascii_token(v) for v in plain._SESSION_PLAIN.values())


def test_mail_session_headline_has_no_english_code() -> None:
    text = plain.build_operational_alert_text(
        OperationalIssue(stage="llm", kind="timeout", safe_summary="x"),
        source_adapter="mail_bridge",
        source_bot="smtp-out",
        session_type=plain.SessionType.EMAIL,
    )
    # 2026-09-25 逐行化后「在哪」不在主句里，落在「会话」那一行；判据跟着移到
    # 人话块整体（技术行照旧带 session_type=email，不参与判据）。
    head = _head(text)
    assert "邮件" in head, head
    assert " email" not in head.lower(), head


def _is_ascii_token(value: object) -> bool:
    """纯 ASCII 的词＝没成人话（本文件只判形态，不判措辞好坏）。"""
    return bool(str(value).strip()) and str(value).isascii()


# ------------------------- queue / creation 观测 kind 全覆盖（席位 F，2026-09-28）
#
# 取证钉死的洞：上面那把锁只按 LLM 词表（`_SAFE_LLM_ERROR_KINDS`）执法，
# queue 观测族与 creation 巡检的 kind 全在册外裸奔——用户永远只能看到
# fallback「出了个我还没登记成人话的错（代号 send_queue_dormant_partial）」。
# 本段把分母换成**真身派生**：逐字清单不进测试（规则 10），kind 从真身模块
# 常量现算；将来谁加一枚观测 kind 忘了填人话，这把锁当场红。

#: 观测 kind 真身文件（模块级 `_XXX_KIND = "..."` 常量）。worker.py 是席位E
#: 领地且 import 链重——**只读源文件派生、绝不 import**，常量本身不动。
_OBSERVED_KIND_SOURCES: tuple[str, ...] = (
    "domains/transport/sender/worker.py",
    "domains/creation/reserved_health_alert.py",
)

_MODULE_KIND_CONST_RE = re.compile(r'^(_[A-Z0-9_]*_KIND)\s*=\s*"([a-z0-9_]+)"\s*$', re.MULTILINE)


def _observed_alert_kinds() -> dict[str, str]:
    """kind 字面量 → ``文件:常量名``（真身现算派生，不手抄清单）。"""
    root = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime"
    found: dict[str, str] = {}
    for rel in _OBSERVED_KIND_SOURCES:
        src = (root / rel).read_text(encoding="utf-8-sig")
        for const, literal in _MODULE_KIND_CONST_RE.findall(src):
            found[literal] = f"{rel}:{const}"
    return found


def test_every_observed_queue_and_creation_kind_has_a_plain_label() -> None:
    """worker/creation 投出的每一枚观测 kind 都必须**两面**在册（主句 + 卡「报错原因」）。

    只补一面＝另一面继续漏代号／落到「未归类」（:338-359 那条两面同锁纪律
    原样搬到这里）。
    """
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    provenance = _observed_alert_kinds()
    vocabulary = set(provenance)
    assert vocabulary >= {
        "send_queue_dormant_partial",
        "send_queue_inflight_saturated",
        "creation_not_configured",
    }, f"分母漂移（真身常量至少应含这三枚，取证席钉过）：{provenance}"
    for name, table in (
        ("alerts._KIND_PLAIN", plain._KIND_PLAIN),
        ("error_report._ISSUE_REASON_LABELS", error_report._ISSUE_REASON_LABELS),
    ):
        missing = _missing_labels(vocabulary, table)
        assert not missing, (
            f"{name} 里这些观测 kind 没有中文人话：{sorted(missing)}"
            f"（真身：{[provenance[k] for k in sorted(missing)]}）"
        )


def test_observed_kind_coverage_lock_bites_on_a_poisoned_vocabulary() -> None:
    """注毒自证：派生词表混进一枚没登记的假观测 kind ⇒ 判据必须当场点名它。

    永真条件的锁等于没锁（:366 同族教训）；这里只在测试进程里注毒，不碰真身。
    """
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    poisoned = set(_observed_alert_kinds()) | {"send_queue_never_registered"}
    assert _missing_labels(poisoned, plain._KIND_PLAIN) == {"send_queue_never_registered"}
    assert _missing_labels(poisoned, error_report._ISSUE_REASON_LABELS) == {
        "send_queue_never_registered"
    }
    # 反向腿：干净派生词表确实是绿的，且不是因为分母为空。
    assert len(_observed_alert_kinds()) >= 3
    assert _missing_labels(set(_observed_alert_kinds()), plain._KIND_PLAIN) == set()


@pytest.mark.parametrize(
    ("stage", "kind", "must_contain"),
    [
        ("queue", "send_queue_dormant_partial", "归档"),
        ("queue", "send_queue_inflight_saturated", "排队"),
        ("creation", "creation_not_configured", "预留位"),
    ],
)
def test_newly_registered_observed_kinds_read_as_chinese(
    stage: str, kind: str, must_contain: str
) -> None:
    """三枚补登记的 kind：主句必须说清「发生了什么 / 要不要紧 / 该谁管」，
    不许再落 fallback，也不许是纯英文代号。"""
    text = _text(
        OperationalIssue(stage=stage, kind=kind, safe_summary=f"{kind} count=1")
    )
    head = _head(text)
    assert plain.ALERT_UNREGISTERED_MARK not in head, head
    assert must_contain in head, head
    assert _has_cjk(head), head
    # 两面同步：卡「报错原因」格也不许「未归类」。
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    label = error_report._reason_label("", "", issue_kind=kind)
    assert "未归类" not in label and not _is_ascii_token(label), label


def test_dormant_keys_detail_is_cut_at_key_boundary_with_count_note() -> None:
    """「具体情况」行别从 keys 中间咬断（2026-09-28 用户：keys 列表被切半、
    读者不明所以）。超预算时按 `|` 边界整键裁、尾注 `…等 N 条`（N 取 count=
    的总数账）；技术行 detail= 切片照旧——那是运维 grep 契约，不在本改面。
    """
    keys = [f"bot.divination:group:1108838060:part:{i:02d}" for i in range(5)]
    summary = "send_queue_dormant_partial count=7 keys=" + "|".join(keys)
    text = _text(
        OperationalIssue(stage="queue", kind="send_queue_dormant_partial", safe_summary=summary)
    )
    rows = [ln for ln in text.splitlines() if ln.startswith("具体情况：")]
    assert rows, text
    value = rows[0][len("具体情况：") :]
    assert "等 7 条" in value, value
    head, sep, tail = value.partition("keys=")
    assert sep and head.startswith("send_queue_dormant_partial count=7 "), value
    shown_keys = tail.partition("…")[0].split("|")
    # 只许出现**完整**键，且必须是全清单的前缀（没被咬断、没跳序）。
    assert shown_keys and shown_keys == keys[: len(shown_keys)], shown_keys
    assert len(shown_keys) < len(keys), "本用例就该演'预算装不下全部键'那一支"
    assert "keys=" not in tail.partition("…")[2], value
    tech = _tech(text)
    assert "detail=send_queue_dormant_partial count=7 keys=" in tech, tech


def test_long_detail_without_keys_marks_truncation() -> None:
    """无 keys= 结构的超长 detail 也显式留省略号——静默掐半截与咬断 keys 同罪。"""
    text = _text(
        OperationalIssue(
            stage="queue", kind="send_queue_inflight_saturated", safe_summary="x" * 200
        )
    )
    rows = [ln for ln in text.splitlines() if ln.startswith("具体情况：")]
    assert rows and rows[0].endswith("…"), rows
    assert len(rows[0][len("具体情况：") :]) <= 121, rows
