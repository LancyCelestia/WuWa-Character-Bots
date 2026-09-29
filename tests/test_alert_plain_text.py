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
from pathlib import Path

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


# --------- ATK-OUTB 票2/票3（2026-09-27）：技术行两把尺并一把 + 截口不残密钥头
# SEAT-ATK-OUTBOUND 探针 D2 实锤：主句/代号行经 `_alert_token` 摘嵌词形态，
# 而技术行的 `kind=`/`detail=` 值段只过旧全局尺（嵌词不认）——两把尺不对称。
# 现在形态尺收进咽喉、代号腿同源，键名照旧逐字（运维 grep 契约不动）。


def test_technical_line_kind_embedded_shape_scrubbed_grep_contract_kept() -> None:
    issue = OperationalIssue(
        stage="llm", kind="server-xsk-AABCDEFGHIJKLMNOPQRSTU", safe_summary="x"
    )
    text = _text(issue)
    tech = _tech(text)
    # 主句与技术行同一把尺：嵌词长段两面都不许存活。
    assert "AABCDEFGHIJKLMNOPQRSTU" not in text
    # grep 契约：`kind=` 键名与词干前缀逐字保留，摘的只是值段。
    assert "kind=server-" in tech
    assert "detail=" in tech


def test_kind_embedded_key_shape_scrubbed_in_head_and_rows() -> None:
    issue = OperationalIssue(stage="campus", kind="visk-EMBEDDEDKEY56789")
    head = _head(_text(issue))
    assert "EMBEDDEDKEY56789" not in head
    assert "visk-<已隐藏>" in head, head  # 代号行可见地被裁过，不静默蒸发


def test_detail_embedded_scrubbed_in_both_legs() -> None:
    issue = OperationalIssue(
        stage="llm", kind="timeout",
        safe_summary="embedded=visk-INSIDETAIL99887766554455",
    )
    text = _text(issue)
    # 探针 2 的两处存活腿（技术行 detail= 与「具体情况」行）必须同净。
    assert "INSIDETAIL99887766554455" not in text
    assert "detail=" in _tech(text)


def test_detail_cut_leaves_no_key_head() -> None:
    # 先洗后截：旧写法 safe_detail[:60]/[:120] 在打码前切，截口残 `sk-MI`
    # 这样的密钥头部（探针 2 实锤 `sk-P`）。padding=55 + `sk-` + 2 字符恰在 60。
    issue = OperationalIssue(
        stage="llm", kind="timeout", safe_summary="B" * 55 + "sk-MISSHEADKEY0123456789"
    )
    text = _text(issue)
    tech = _tech(text)
    assert "MISSHEAD" not in text
    assert "sk-MI" not in tech
    detail_rows = [ln for ln in text.splitlines() if ln.startswith("具体情况：")]
    assert detail_rows and "sk-MI" not in detail_rows[0], detail_rows


def test_ops_grep_chain_token_survives_scrub() -> None:
    # 票3 的契约反面：chain 压缩串与末站归因是运维 grep 的对象，
    # 并尺之后必须仍逐字出技术行（洗的是密钥形态，不是键名与编号）。
    issue = OperationalIssue(
        stage="llm", kind="timeout", attempts=2,
        safe_summary="timeout chain=17 last=axon-grok-46:timeout",
    )
    tech = _tech(_text(issue))
    assert "detail=chain=17跳全败 last=axon-grok-46:timeout" in tech, tech


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


# ------------------------------------------------------- LLM 侧 kind 全覆盖（2026-09-27 实弹）


def _llm_kind_vocabulary() -> set[str]:
    """告警可能收到的 LLM kind 全集。

    真身 = chat 侧的在册词表 ``_SAFE_LLM_ERROR_KINDS``（凡是不在这 16 枚里的
    kind 都会被归一成 ``provider_error``，所以它就是完整的分母）；本件不手抄
    清单，词表加一档而人话表忘了填 ⇒ 这把锁当场红。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat

    return set(chat._SAFE_LLM_ERROR_KINDS)


def _missing_labels(vocabulary: set[str], table: dict[str, str]) -> set[str]:
    """返回词表里**没有**中文人话的那些 kind。"""
    return {kind for kind in vocabulary if kind not in table}


def test_every_llm_error_kind_has_a_plain_label() -> None:
    """LLM 的每一枚在册失败代号都必须有中文人话，**两面**都要有。

    生产实弹（2026-09-27 04:12 私聊「test」）：本机代理 DNS 挂死 → AxonHub 把
    grok/gemini 的渠道逐个试完全部 ``EOF`` → 对 bot 回 HTTP 502 → kind=``server``，
    而人话表当时只登记了 timeout / network / provider_error 一类 ⇒ 她读到的是
    「出了个我还没登记成人话的错（代号 server）」，既看不出是出网坏了，也看不出
    该去查哪一头。

    两面 = ①告警纯文本主句（``alerts._KIND_PLAIN``）②诊断卡「报错原因」格
    （``error_report._ISSUE_REASON_LABELS``）。同一条变更处处跟随：只补一面
    = 另一面继续漏代号／落到「未归类」。
    """
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    vocabulary = _llm_kind_vocabulary()
    for name, table in (
        ("alerts._KIND_PLAIN", plain._KIND_PLAIN),
        ("error_report._ISSUE_REASON_LABELS", error_report._ISSUE_REASON_LABELS),
    ):
        missing = _missing_labels(vocabulary, table)
        assert not missing, f"{name} 里这些 LLM kind 没有中文人话：{sorted(missing)}"
    assert all(
        str(value).strip() and not _is_ascii_token(value)
        for value in plain._KIND_PLAIN.values()
    ), plain._KIND_PLAIN


def test_kind_coverage_lock_bites_on_an_unregistered_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒自证：往词表加一枚没登记人话的 kind，这把判据必须当场点数它。

    永真条件的锁等于没锁（本仓反复记过的失效形态），所以覆盖判据本身也要被
    杀一次——这里只在测试进程里给词表注毒，不碰任何生产文件。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat

    poisoned = set(chat._SAFE_LLM_ERROR_KINDS) | {"somesynthetickind"}
    assert _missing_labels(poisoned, plain._KIND_PLAIN) == {"somesynthetickind"}
    # 反向腿：原判据在干净词表下确实是绿的，且不是因为分母为空。
    assert len(_llm_kind_vocabulary()) > 1
    assert _missing_labels(_llm_kind_vocabulary(), plain._KIND_PLAIN) == set()


def test_http_server_kind_headline_reads_as_chinese() -> None:
    """``server``（网关/上游回 5xx）这一例的主句必须是人话，且不许再出现"没登记"。"""
    text = _text(
        OperationalIssue(
            stage="llm",
            kind="server",
            safe_summary="server chain=2 last=axon-grok-46:server",
            attempts=2,
            retryable=True,
        )
    )
    head = _head(text)
    assert plain.ALERT_UNREGISTERED_MARK not in head, head
    assert " server" not in head, head
    assert _has_cjk(head), head
    # 技术行照旧逐字保留，运维 grep 不断。
    assert "kind=server" in _tech(text), _tech(text)


def test_diagnostic_card_reason_for_server_kind_is_not_unclassified() -> None:
    """卡上「报错原因」这一格：kind=server 必须给出归类，不许是「未归类」。

    异常名表对 ``stage/kind`` 代号串本来就失灵（卡上没有异常名可比），所以这条
    是判"归类在场"，而**不是**判它把原因说成什么——本仓的规矩是认不出就明说，
    不许编。
    """
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    label = error_report._reason_label("", "", issue_kind="server")
    assert label and "未归类" not in label, label
    assert not _is_ascii_token(label), label
    # 反向腿：不在这张词表里的代号仍走「认不出就明说」，没被顺手编一个原因。
    assert "未归类" in error_report._reason_label("", "", issue_kind="zzz_unlisted")


# --------- queue / creation / emergency_info 观测 kind 全覆盖（席位 F 2026-09-28，紧急域 2026-09-30 并入）
#
# 取证钉死的洞：上面那把锁只按 LLM 词表（`_SAFE_LLM_ERROR_KINDS`）执法，
# queue 观测族与 creation 巡检的 kind 全在册外裸奔——用户永远只能看到
# fallback「出了个我还没登记成人话的错（代号 send_queue_dormant_partial）」。
# 本段把分母换成**真身派生**：逐字清单不进测试（规则 10），kind 从真身模块
# 常量现算；将来谁加一枚观测 kind 忘了填人话，这把锁当场红。

#: 观测 kind 真身文件（模块级 `*_KIND*` 常量）。worker.py 是席位E
#: 领地且 import 链重——**只读源文件派生、绝不 import**，常量本身不动。
#: 2026-09-30 把分母扩到紧急预警域：投递侧时效腿（F-1）第一次把 `push_expired`
#: 推到台前，而采集侧 `collect_failed`（同一 stage）一直在册外裸奔——
#: 谁在紧急域再加一枚告警 kind 而忘了填人话，这把锁当场红。
_OBSERVED_KIND_SOURCES: tuple[str, ...] = (
    "domains/transport/sender/worker.py",
    "domains/creation/reserved_health_alert.py",
    "domains/emergency_info/service/collector.py",
    "domains/emergency_info/service/push.py",
)

# 常量名两支都收：下划线开头的 `_DORMANT_PARTIAL_KIND` 与公开的
# `ISSUE_KIND` / `ISSUE_KIND_PUSH_EXPIRED`。旧尺只认前一支（`^_…_KIND$`），
# 紧急域那两枚因此对本锁不可见＝分母缺一整域。
_MODULE_KIND_CONST_RE = re.compile(
    r'^(_?[A-Z0-9_]*KIND[A-Z0-9_]*)\s*=\s*"([a-z0-9_]+)"\s*$', re.MULTILINE
)


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
    """worker/creation/emergency_info 投出的每一枚观测 kind 都必须**两面**在册（主句 + 卡「报错原因」）。

    只补一面＝另一面继续漏代号／落到「未归类」（:338-359 那条两面同锁纪律
    原样搬到这里）。紧急域那两枚是 2026-09-30 并入的：时效丢弃腿把 `push_expired`
    推到台前，`collect_failed` 则早就在同一 stage 下裸奔——分母不扩，下一枚
    紧急域 kind 还会悄悄走兜底句。
    """
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    provenance = _observed_alert_kinds()
    vocabulary = set(provenance)
    assert vocabulary >= {
        "send_queue_dormant_partial",
        "send_queue_inflight_saturated",
        "creation_not_configured",
        "collect_failed",
        "push_expired",
    }, f"分母漂移（真身常量至少应含这五枚，取证席钉过＋本席补的紧急域两枚）：{provenance}"
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
        ("emergency_info", "collect_failed", "没采到数据"),
        ("emergency_info", "push_expired", "时效窗"),
    ],
)
def test_newly_registered_observed_kinds_read_as_chinese(
    stage: str, kind: str, must_contain: str
) -> None:
    """各段补登记的 kind（参数化＝分母跟随，加一枚就多一条）：主句必须说清
    「发生了什么 / 要不要紧 / 该谁管」，不许再落 fallback，也不许是纯英文代号。"""
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


def test_emergency_info_stage_is_humanized_and_owned() -> None:
    """紧急预警这条线的 **stage** 侧（上一把参数化锁只判 kind 面）：
    主句不许落「有一件事没做成」的兜底，卡面归属不许是「未归属」。

    为什么单独一条：`_STAGE_PLAIN` 与 `_ISSUE_STAGE_OWNERSHIP` 是同批的两把尺
    （异或锁 `test_alert_error_card.py::test_issue_stage_ownership_keys_track_alert_stage_plain`
    判键集同域），但键集齐了不代表值说得清——这里按事故原文那枚 stage 实跑一次，
    把「读得出人话 + 归得出子系统」钉成一条。
    """
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    text = _text(
        OperationalIssue(
            stage="emergency_info",
            kind="push_expired",
            safe_summary="reason=outside_validity_window item=nmc-x1 channel=qq",
        )
    )
    head = _head(text)
    assert plain.ALERT_UNREGISTERED_MARK not in head, head
    assert "有一件事没做成" not in head, head
    assert "我在照看紧急预警这条线" in head, head
    # 归属：告警常无能力 id，靠 stage 落到子系统，不许整卡「未归属」。
    owner = error_report._module_ownership("", stage="emergency_info")
    assert "域" in owner and "未归属" not in owner, owner
    assert "emergency_info" in owner, owner
    # 技术行照旧逐字保留（运维 grep 契约）。
    assert "stage=emergency_info" in _tech(text), _tech(text)


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
