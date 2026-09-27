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
