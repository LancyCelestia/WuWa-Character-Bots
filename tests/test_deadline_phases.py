"""deadline_exceeded 回执自解释化（S-T-DEADLOG-1，2026-09-26）。

生产实弹（2026-09-26 01:07 私聊，超管原话「axonhub 里没有请求失败，为什么报错」）：

    event=pipeline_result capability_id=bot.chat receipt_state=queued
      transport=sqlite_queue duration_ms=333254.0 error_kind=deadline_exceeded

同族 00:53:51 的行有 ``route_attempts=...``；这一行什么都没有——300 秒预算
（bot_chat_failover_max_seconds / bot_request_budget_seconds）耗尽时，回执不
回答「时间花在哪」：LLM 跳？检索？识图/转写？渲染？队列？`phase_tags()` 上一
波已把相位刷成 `phase_<stage>_ms` 标签，但 deadline 两条出口（chat.py 的
before_llm / during_llm）不带尝试记录、不带在飞相位、不带剩余预算，且回执行
提取口（根 __init__ 的 `_runtime_tag_values`）根本不读这些标签。

本文件锁四件事（全部由 `runtime/deadline.py` 的
`deadline_receipt_tags` / `deadline_receipt_view` 兑现）：
1. 任何 deadline_exceeded 回执必须自带：相位拆分（复用 phase_tags，禁第二套
   格式化器）、尝试记录（空列表要明说，不许省字段）、预算到期时在飞的是哪一
   段、当时的剩余预算（可为负=超支）。
2. 稳定 grep 记号 `deadline_diag=1`，行内风格对齐 `route_attempts=`/`error_kind=`。
3. 诚实降级：没记到的写「未记账」，绝不编数（本仓铁律：「没测到」≠「没有」）。
4. 超时/预算数值零改动——本波是可诊断性，不是延迟调参。

2026-09-26 S-T-DEADLOG-2 接手补段（原席在 `deadline_receipt_tags` 落码前阵亡）：
本文件 §5 把上面那句「提取口根本不读这些标签」的病根**接上了**——根
`__init__.py::_runtime_tag_values` 现在真读，活性锁直接调根文件真身。
`chat.py` 两条 deadline 出口改用组装口（把逐跳轨迹与守卫名交进来）仍是 handoff
补丁单，见 logs/S-T-DEADLOG-2.md §6；未接线前 §盲区复现 与 §5 的真链路用例
都按「未记账」双态放行，接线落地后不必改判据。

全离线、无网络；真实链路用例用 60ms 睡眠 vs 20ms 预算钉死「超时必已发生」的
方向性（睡眠时长恒大于预算，任何调度抖动都只会更超），不涉及任何生产数值。
"""

from __future__ import annotations

import time

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline import (
    DEADLINE_RECEIPT_FIELDS,
    UNRECORDED_MARK,
    DeadlineBudget,
    DeadlineExceeded,
    deadline_receipt_tags,
    deadline_receipt_view,
    phase_tags,
)


def _formatter_tag(tags: list[str], prefix: str) -> str | None:
    for tag in tags:
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None


# ===================================================================== 盲区复现
# 真链路：预算被一个非 LLM 阶段（这里用「慢上下文装配」代理真实世界里的慢检索/
# 识图）吃光 → chat.py 走 before_llm 出口 → 回执必须自解释。
# RED（实施前）：deadline_receipt_view / deadline_receipt_tags 不存在，本文件
# 收集即红——这正是盲区本身：没有任何出口负责把这些信息放进回执。


def test_real_slow_nonllm_stage_receipt_is_self_explanatory(tmp_path) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_capability,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        NullCharacterContextProvider,
    )

    class _SlowRetrievalProvider(NullCharacterContextProvider):
        """慢非-LLM 阶段：上下文装配 60ms，预算只有 20ms ⇒ 进 LLM 前必已耗尽。"""

        def build_context(self, *args: object, **kwargs: object):
            time.sleep(0.06)
            return super().build_context(*args, **kwargs)  # type: ignore[misc,arg-type]

    class _MustNotBeCalledLLM:
        def generate(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("deadline exhausted: provider must not be called")

    capability = build_chat_capability(
        _SlowRetrievalProvider(),
        _MustNotBeCalledLLM(),
        generated_files_dir=str(tmp_path),
        request_budget_seconds=0.02,
    )
    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="private:u",
        session_type=SessionType.PRIVATE,
        sender_id="u",
        plain_text="帮我想想晚饭吃什么",
        mentions_bot=False,
    )
    decision = BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        context_budget=18000,
        max_messages=0,
        decision_reason="test",
    )

    result = capability(message, decision)
    tags = [str(tag) for tag in result.audit_tags]

    # 今天已成立的两枚事实（旧标签一字不动——test_diagnostic_llm_attribution 消费它们）。
    assert "llm_error:deadline_exceeded" in tags, tags
    assert "deadline_exceeded:before_llm" in tags, tags

    # 本波交付：回执提取口必须补齐全部四项要素（缺哪记哪，不许省略字段）。
    view = deadline_receipt_view(tags)
    assert view["deadline_diag"] == "1"
    assert view["deadline_in_flight"] in {"before_llm", "pre_llm_gates"}, (
        f"在飞相位必须至少报到闸口粒度：{view}"
    )
    assert view["deadline_attempts"] == "0", (
        f"before_llm 出口=一条 LLM 尝试都没发过，必须明说 0：{view}"
    )
    # 旧链路未携带精确剩余预算时只能写未记账（chat.py handoff 落地后变实数，两态都放行）。
    assert (
        view["deadline_remaining_ms"] == UNRECORDED_MARK
        or view["deadline_remaining_ms"].lstrip("-").isdecimal()
    ), view
    assert (
        view.get("deadline_phases") == UNRECORDED_MARK or "phase_total_ms" in view
    ), f"相位拆分要么有、要么明说未记账：{view}"


# ================================================================= 提取口零污染
# 非 deadline 回执必须原样不追加任何键——00:53:51 那类行的既有形状不许被本波
# 改动（棘轮：只加 deadline 面，不动成功/server-error 面的字节）。


def test_view_on_non_deadline_receipt_returns_nothing() -> None:
    assert deadline_receipt_view(
        ["llm_error", "llm_error:server", "model:axon-gemini-38-flash"]
    ) == {}
    assert deadline_receipt_view(["phase_llm_ms:120", "phase_total_ms:120"]) == {}
    assert deadline_receipt_view([]) == {}
    assert deadline_receipt_view(None) == {}


# ==================================================================== 组装口契约


def _expired_budget_with_slow_media_phases() -> DeadlineBudget:
    """10 秒预算、已经过期 1 秒；9.2 秒花在识图、0.4 秒花在转写——LLM 一跳没跑。"""
    budget = DeadlineBudget(10.0, started_at=time.monotonic() - 11.0)
    budget.phases_ms = {"vision": 9200.0, "asr": 400.0}
    return budget


def test_formatter_carries_all_four_required_facts() -> None:
    budget = _expired_budget_with_slow_media_phases()
    exc = None
    try:
        budget.ensure_available(stage="tools")
    except DeadlineExceeded as caught:
        exc = caught
    assert exc is not None

    tags = deadline_receipt_tags(budget, attempts=[], exc=exc)

    assert "deadline_diag:1" in tags
    # ① 相位拆分＝复用 phase_tags（逐字节同源，见下一用例）
    assert "phase_vision_ms:9200" in tags
    assert "phase_asr_ms:400" in tags
    assert "phase_total_ms:9600" in tags
    # ② 尝试记录：空列表明说 0，不省略
    assert _formatter_tag(tags, "deadline_attempts:") == "0"
    # ③ 预算到期时在飞的守卫：ensure_available 的 stage 就在异常 args 里
    assert _formatter_tag(tags, "deadline_in_flight:") == "tools"
    # ④ 当时剩余预算：负数=超支，不许被钳成 0 或省略
    remaining = _formatter_tag(tags, "deadline_remaining_ms:")
    assert remaining is not None and remaining.lstrip("-").isdecimal()
    assert int(remaining) < 0


def test_formatter_reuses_phase_tags_verbatim_no_second_formatter() -> None:
    budget = _expired_budget_with_slow_media_phases()
    phase_subset = set(phase_tags(budget))
    tags = set(deadline_receipt_tags(budget, attempts=None, exc=None))
    assert phase_subset <= tags, "相位拆分必须逐字节复用 phase_tags()，禁第二套格式化器"


def test_formatter_budget_none_says_unrecorded_and_never_invents() -> None:
    tags = deadline_receipt_tags(None)
    assert "deadline_diag:1" in tags
    assert _formatter_tag(tags, "deadline_in_flight:") == UNRECORDED_MARK
    assert _formatter_tag(tags, "deadline_remaining_ms:") == UNRECORDED_MARK
    assert _formatter_tag(tags, "deadline_attempts:") == UNRECORDED_MARK
    assert _formatter_tag(tags, "deadline_phases:") == UNRECORDED_MARK
    # 「未记账」之外不许出现任何编造的毫秒数
    assert not any(tag.startswith("phase_") for tag in tags)


def test_formatter_disabled_budget_remaining_is_unrecorded() -> None:
    # 预算未启用（total<=0）时 remaining 是 +inf——落进标签就成了谎报；必须未记账。
    budget = DeadlineBudget(0)
    tags = deadline_receipt_tags(budget, attempts=["axon-grok-46:server"])
    assert _formatter_tag(tags, "deadline_remaining_ms:") == UNRECORDED_MARK
    assert _formatter_tag(tags, "deadline_attempts:") == "1"
    assert "llm_route_attempt:axon-grok-46:server" in tags


def test_formatter_in_flight_priority_and_user_content_never_leaks() -> None:
    budget = DeadlineBudget(10.0, started_at=time.monotonic() - 11.0)
    exc = DeadlineExceeded("deadline_exceeded")  # 无守卫名的裸断——不许当相位名用

    tags = deadline_receipt_tags(budget, in_flight="llm", exc=exc)
    assert _formatter_tag(tags, "deadline_in_flight:") == "llm"

    # 显式名非法 → 退到异常携带名；异常也无名 → 未记账；任何形态的用户正文/换行
    # 都绝不允许出现在标签里（对齐 phase_tags 的同款卫生）。
    tags2 = deadline_receipt_tags(budget, in_flight="用户正文\n第二行", exc=DeadlineExceeded("tools"))
    assert _formatter_tag(tags2, "deadline_in_flight:") == "tools"
    assert not any("用户正文" in tag or "\n" in tag for tag in tags2)

    tags3 = deadline_receipt_tags(budget, in_flight="用户正文\n第二行", exc=exc)
    assert _formatter_tag(tags3, "deadline_in_flight:") == UNRECORDED_MARK
    assert not any("用户正文" in tag or "\n" in tag for tag in tags3)


def test_formatter_attempt_hops_are_sanitized_and_clamped() -> None:
    budget = _expired_budget_with_slow_media_phases()
    hops = ["axon-grok-46:server", "  failover:deadline  ", "换\n行", "", "x" * 400]
    tags = deadline_receipt_tags(budget, attempts=hops, exc=None)
    assert "llm_route_attempt:axon-grok-46:server" in tags
    assert "llm_route_attempt:failover:deadline" in tags  # 首尾空白折叠
    joined = "|".join(
        tag for tag in tags if tag.startswith("llm_route_attempt:")
    )
    assert "\n" not in joined
    # 计数与发出的 route 标签数严格一致（空 hop 不计数；折叠空白后的非空 hop
    # 一律算数——悄悄丢掉一枚再报"少了的那枚不存在"就是谎报）。
    assert _formatter_tag(tags, "deadline_attempts:") == str(
        sum(1 for tag in tags if tag.startswith("llm_route_attempt:"))
    ) == "4"


# =================================================================== 视图往返锁


def test_view_round_trip_surfaces_every_field_as_loggable_kwargs() -> None:
    budget = _expired_budget_with_slow_media_phases()
    exc = None
    try:
        budget.timeout_for(5.0)
    except DeadlineExceeded as caught:
        exc = caught
    tags = deadline_receipt_tags(budget, attempts=["axon-grok-46:server"], exc=exc)
    view = deadline_receipt_view(tags)

    assert view["deadline_diag"] == "1"
    assert view["deadline_in_flight"] == "timeout_for"
    assert view["deadline_attempts"] == "1"
    assert view["phase_vision_ms"] == "9200"
    assert view["phase_total_ms"] == "9600"
    assert "deadline_phases" not in view
    assert int(view["deadline_remaining_ms"]) < 0
    # 旧提取口（_runtime_tag_values）靠 llm_route_attempt: 前缀拼 route_attempts=；
    # 本波的尝试记录复用同一前缀 ⇒ 那把既有钥匙继续能开门。
    assert "llm_route_attempt:axon-grok-46:server" in tags
    # 回执行是 **kwargs 展开：键必须是合法标识符，值必须是字符串。
    for key, value in view.items():
        assert key.isidentifier(), key
        assert isinstance(value, str), (key, value)


# ============================================================ 旧回执的诚实降级
# chat.py 的两处 deadline 出口与根 __init__ 的提取口接线属 handoff 补丁单；
# 接线落地**之前**，视图也必须把既有标签里本来就有的事实读出来、把没有的写明
# 「未记账」——而不是像今天这样整字段缺席。


def test_view_legacy_before_llm_infers_zero_attempts_coarse_in_flight() -> None:
    legacy = ["llm_error", "llm_error:deadline_exceeded", "deadline_exceeded:before_llm"]
    view = deadline_receipt_view(legacy)
    assert view["deadline_diag"] == "1"
    assert view["deadline_in_flight"] == "before_llm"
    assert view["deadline_attempts"] == "0"  # 闸前断=一条没发过，这是既有事实不是猜测
    assert view["deadline_remaining_ms"] == UNRECORDED_MARK  # 旧标签没有的绝不补数
    assert view["deadline_phases"] == UNRECORDED_MARK


def test_view_legacy_during_llm_attempts_stay_unrecorded() -> None:
    legacy = ["llm_error:deadline_exceeded", "deadline_exceeded:during_llm"]
    view = deadline_receipt_view(legacy)
    assert view["deadline_in_flight"] == "during_llm"
    # during_llm 时路由可能已经跳过若干次，但标签里没有 ⇒ 不许写 0（那是说谎）。
    assert view["deadline_attempts"] == UNRECORDED_MARK


def test_view_legacy_with_recorded_phases_surfaces_them_directly() -> None:
    # 生产 01:12:57 那行的理想形态：慢识图已记了账（phase 标签本来就在 audit_tags 里，
    # 只是提取口从不读）。视图把它们 surfaced，总耗时 333s 里 330s 一眼可见。
    legacy = [
        "llm_error:deadline_exceeded",
        "deadline_exceeded:before_llm",
        "phase_vision_ms:330000",
        "phase_total_ms:330000",
    ]
    view = deadline_receipt_view(legacy)
    assert view["phase_vision_ms"] == "330000"
    assert view["phase_total_ms"] == "330000"
    assert "deadline_phases" not in view


# ================================================================ 在飞跟踪机制
# 供 chat.py handoff 之后细粒度标注用；今天无人调用也必须行为正确、可独立回归。


def test_mark_in_flight_tracks_until_record_phase_clears() -> None:
    budget = DeadlineBudget(10.0, started_at=time.monotonic() - 11.0)
    budget.mark_in_flight("vision")
    tags = deadline_receipt_tags(budget)
    assert _formatter_tag(tags, "deadline_in_flight:") == "vision"

    budget.record_phase("vision", time.monotonic() - 0.05)
    tags2 = deadline_receipt_tags(budget)
    assert _formatter_tag(tags2, "deadline_in_flight:") == UNRECORDED_MARK
    assert "phase_vision_ms:50" in tags2  # 归账照旧（record_phase 行为零改动）

    budget.mark_in_flight("用户正文\n第二行")  # 非法名不入状态
    tags3 = deadline_receipt_tags(budget)
    assert _formatter_tag(tags3, "deadline_in_flight:") == UNRECORDED_MARK


# ============================================= 回执行提取口活性锁（S-T-DEADLOG-2）
# 组装口与提取口都在 `runtime/deadline.py` 一个真身里，但**库存在 ≠ 回执行读得到**：
# 2026-09-26 01:12 那行的病根本质就是「audit_tags 里有账、根 __init__ 的提取口从不读」。
# 上面 13 例全绿也照样解释不了那条行——所以本段直接调根文件真身
# `_runtime_tag_values`（不是复刻一份判据），断言字段真的落到行上。
# 注毒判据（实测见 logs/S-T-DEADLOG-2.md §5）：把根那行的
# `return dict(result, **_deadline_diag.deadline_receipt_view(...))` 退回
# `return result` ⇒ 本段前三例当场红，第四例（非 deadline 行零污染）照绿。

#: 根回执行既有的字段名：新键必须与之不相交，否则 `**kwargs` 展开当场 TypeError
#: （=「加了可观测性、炸了发消息」这种最坏的连带损伤）。
_EXISTING_RUNTIME_LOG_FIELDS = {
    "route_attempts", "model", "error_kind",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "cache_read_tokens", "cache_write_tokens", "cost_milli",
}


def _send_request(audit_tags: list[str]):
    from plugins.bot_unified_runtime.contracts import (
        PrivacyLevel,
        RenderedOutput,
        SendPolicy,
        SendRequest,
    )

    return SendRequest(
        request_id="req-deadline",
        session_id="private:u",
        target_scope=SessionType.PRIVATE,
        target_id="u",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id="req-deadline",
            content_type="text",
            content_ref={},
            text_fallback="hi",
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="bot.chat-private:u",
        cooldown_key="private:u",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        audit_tags=audit_tags,
    )


def _root_runtime_tag_values(audit_tags: list[str]) -> dict[str, object]:
    """调根装配文件里的真提取口（回执行字段就是它产的），不复刻判据。"""
    from plugins.bot_unified_runtime import _runtime_tag_values

    return _runtime_tag_values(_send_request(audit_tags))


def test_root_log_line_carries_hops_and_phases_of_an_exhausted_budget() -> None:
    """生产 01:12 那行的理想形态：一行之内同时看到「走了哪几跳 / 各阶段多少毫秒 /
    还剩多少预算 / 哪一段在飞」，归因不到的部分显式「未记账」而不是缺席。"""
    budget = DeadlineBudget(300.0, started_at=time.monotonic() - 333.254)
    budget.phases_ms = {"vision": 2100.0, "asr": 300.0}
    hops = [
        "axon-gemini-38-flash:timeout",
        "axon-grok-46:network",
        "qian-gemini-38-flash-high:server",
        "failover:deadline",
    ]
    receipt = [
        "llm_error",
        "llm_error:deadline_exceeded",
        "deadline_exceeded:during_llm",
        *deadline_receipt_tags(budget, attempts=hops, exc=DeadlineExceeded("llm")),
    ]

    fields = _root_runtime_tag_values(receipt)

    # ① 逐跳：既有载体 route_attempts（"|".join）继续有效……
    assert str(fields["route_attempts"]).split("|") == hops, fields
    # ……并且计数与它严格一致，不是「1 跳全败」那种兜底假数。
    assert fields["deadline_attempts"] == "4", fields
    # ② 阶段耗时：每一段与合计都单独成字段（grep `phase_vision_ms=` 即可分段统计）。
    assert fields["phase_vision_ms"] == "2100", fields
    assert fields["phase_asr_ms"] == "300", fields
    assert fields["phase_total_ms"] == "2400", fields
    assert "deadline_phases" not in fields, fields  # 有账可查就不该出现「未记账」
    # 走过的时间里有 330.8 秒不属于任何记账阶段——这枚数字本身就是结论。
    elapsed = int(str(fields["deadline_elapsed_ms"]))
    unaccounted = int(str(fields["deadline_unaccounted_ms"]))
    assert elapsed >= 333000 and abs(unaccounted - (elapsed - 2400)) <= 1, fields
    # ③ 到期那一刻在飞的是哪一段 + 当时剩余预算（负=已超支）。
    assert fields["deadline_in_flight"] == "llm", fields
    assert int(str(fields["deadline_remaining_ms"])) < 0, fields
    assert fields["deadline_diag"] == "1", fields
    # 旧字段一字不动：error_kind 仍由既有载体给出。
    assert fields["error_kind"] == "deadline_exceeded", fields


def test_root_real_exhausted_request_receipt_is_self_explanatory(tmp_path) -> None:
    """真链路（慢上下文装配吃光 20ms 预算）→ 真 audit_tags → 真提取口。

    与 §「盲区复现」那例的分工：那一例证组装口给得全，本例证**行上也看得见**。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_capability,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
        NullCharacterContextProvider,
    )

    class _SlowRetrievalProvider(NullCharacterContextProvider):
        def build_context(self, *args: object, **kwargs: object):
            time.sleep(0.06)
            return super().build_context(*args, **kwargs)  # type: ignore[misc,arg-type]

    class _MustNotBeCalledLLM:
        def generate(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("deadline exhausted: provider must not be called")

    capability = build_chat_capability(
        _SlowRetrievalProvider(),
        _MustNotBeCalledLLM(),
        generated_files_dir=str(tmp_path),
        request_budget_seconds=0.02,
    )
    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="b",
        session_id="private:u",
        session_type=SessionType.PRIVATE,
        sender_id="u",
        plain_text="帮我想想晚饭吃什么",
        mentions_bot=False,
    )
    decision = BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        context_budget=18000,
        max_messages=0,
        decision_reason="test",
    )
    result = capability(message, decision)

    fields = _root_runtime_tag_values([str(tag) for tag in result.audit_tags])

    assert fields["deadline_diag"] == "1", fields
    # 在飞相位：既有 before_llm 记号在场 ⇒ 这格必须有名字，不许「未记账」。
    # 具体值随 chat.py 接线进度变粗或变细（before_llm / pre_llm_gates / context…），
    # 故本锁钉「有没有」而不是「是哪个」——是哪个由各相位自己的锁管。
    in_flight = str(fields["deadline_in_flight"])
    assert in_flight and in_flight != UNRECORDED_MARK, fields
    # 闸前断＝一条 LLM 尝试都没发过：这是既有的确定性事实，写 0 不是猜。
    assert fields["deadline_attempts"] == "0", fields
    assert str(fields["error_kind"]) == "deadline_exceeded", fields
    # 相位账要么有实数、要么明说「未记账」——两者必居其一且只居其一（缺席=本波的
    # 病根本身）。装配/检索段是否已记账取决于 chat.py 的 record_phase 进度，本锁
    # 两种状态都放行，只禁「字段整块消失」这一种形态。
    has_phase_tags = any(str(key).startswith("phase_") for key in fields)
    assert has_phase_tags != ("deadline_phases" in fields), fields
    if "deadline_phases" in fields:
        assert fields["deadline_phases"] == UNRECORDED_MARK, fields
    else:
        assert str(fields.get("phase_total_ms", "")).isdigit(), fields
    for key in (
        "deadline_remaining_ms",
        "deadline_elapsed_ms",
        "deadline_unaccounted_ms",
    ):
        value = str(fields[key])
        assert value == UNRECORDED_MARK or value.lstrip("-").isdecimal(), (key, fields)



def test_root_new_fields_never_collide_with_existing_log_fields() -> None:
    """回执行是 `**kwargs` 展开：新键与既有键同名 = 当场 TypeError（发不出消息）。"""
    tags = deadline_receipt_tags(
        DeadlineBudget(30.0, started_at=time.monotonic() - 31.0),
        attempts=["axon-grok-46:server"],
    ) + ["llm_error:deadline_exceeded", "model:grok-4.6"]

    view = deadline_receipt_view(tags)
    assert view, tags
    # 真判据：提取口新增的键与既有九枚字段名**不相交**（相交即覆盖=谎报旧字段）。
    assert set(view) & _EXISTING_RUNTIME_LOG_FIELDS == set(), sorted(view)

    fields = _root_runtime_tag_values(tags)
    assert all(key.isidentifier() for key in fields), sorted(fields)
    # 既有三枚载体在本波合并之后取值不变（合并只加键，不改旧键）。
    assert fields["route_attempts"] == "axon-grok-46:server", fields
    assert fields["model"] == "grok-4.6", fields
    assert fields["error_kind"] == "deadline_exceeded", fields



def test_root_non_deadline_lines_stay_byte_identical() -> None:
    """棘轮：本波只加 deadline 面。00:53 那类 `error_kind=server` 行的形状一个字节不动。"""
    server_line = _root_runtime_tag_values(
        [
            "llm_error",
            "llm_error:server",
            "model:axon-gemini-38-flash",
            "llm_route_attempt:axon-gemini-38-flash:server",
            "llm_usage_total_tokens:512",
        ]
    )
    assert server_line == {
        "route_attempts": "axon-gemini-38-flash:server",
        "model": "axon-gemini-38-flash",
        "error_kind": "server",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 512,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_milli": 0,
    }, server_line
    success_line = _root_runtime_tag_values(["model:axon-grok-46", "phase_llm_ms:1200"])
    assert "deadline_diag" not in success_line and "phase_llm_ms" not in success_line
    assert _root_runtime_tag_values([]) == {}


def test_view_declares_the_full_field_set_and_never_omits() -> None:
    """字段全集锁：declared 的每一步都必须出现在行上，读不到就写「未记账」。

    存在理由：「这条回执没有这个字段」和「这个字段记不到」在日志里长得一模一样，
    而后者才是 01:12 那次真正的病——缺席被读成「没有」。省略字段本身就是本波要
    根除的形态，所以把它钉成结构锁而不是靠每条分支各自记得写。
    """
    for receipt in (
        ["deadline_exceeded:during_llm"],
        ["deadline_exceeded:before_llm"],
        ["llm_error:deadline_exceeded"],
        deadline_receipt_tags(
            DeadlineBudget(30.0, started_at=time.monotonic() - 31.0), attempts=[]
        ),
    ):
        view = deadline_receipt_view(receipt)
        assert set(DEADLINE_RECEIPT_FIELDS) <= set(view), (receipt, view)
        assert all(str(value) for value in view.values()), (receipt, view)


