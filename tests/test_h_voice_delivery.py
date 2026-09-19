"""T71 Wave H 棘轮：语音投递验收 R1-R9（xfail(strict) 棘轮，现期预期红）。

把 report-T65.md §三 的 R1-R8 配方（判据源=report-T55.md §五/§4.4、
report-T46.md §3.5）落成 8 例 xfail(strict) 棘轮 + 1 例正锁（R5）：
- 现期：Wave H 未施工 ⇒ 8 例 xfail、0 failed、0 xpass，套件绿；
- H 波施工（A 案：worker 计划门 mixed 分支 + sender 补 count/UNKNOWN 回报，
  progress.md G2-R1 已裁）落地后 xpass 触发 strict 失败 ⇒ 强制摘标记翻转；
- R5（retcode 1200）语义等用户裁决，现状即绿、不可 xfail（会立即 xpass），
  故落为**正锁**：H 波改动 1200 语义时本例必红，强制翻议（见其 docstring）。

pytest 无全局 xfail_strict（pyproject.toml [tool.pytest.ini_options] 实查），
strict 必须逐标记显式声明。

离线运行（零网络零墙钟断言）：

    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_h_voice_delivery.py -q -p no:cacheprovider \\
      --basetemp="../ChatBot_Runtime/cache/t71"
"""

from __future__ import annotations

from datetime import datetime

import pytest
from helpers.voice_queue_sim import (
    SimulatedOneBotBot,
    build_mixed_request,
    build_sqlite_queue,
    dispatch_count,
    freeze_inline_retries,
    make_transport,
    part_states,
    partial_rows,
    queue_row,
    record_files,
    run_queue_rounds,
    sent_texts,
    sim_utc_now,
    unknown_part_indexes,
)

from plugins.bot_unified_runtime.contracts import SessionType

_TEXT = "守岸人准备好了。"
_RECORD = "voice-ok.wav"
_RECORD_POISON = "voice-poison-missing.wav"
_RECORD_SAYX = "voice-sayx.wav"
# 全部用例共享的显式 now 基点（C4：禁止依赖墙钟，模块导入时固定一次）。
_BASE: datetime = sim_utc_now()


def _submit_mixed(queue, rid: str, *, record: str, text: str | None = _TEXT) -> None:
    request = build_mixed_request(rid, text=text, record_file=record)
    queue.submit(request, now=_BASE)


# ==================== R1｜断连形态负锁（M-63，P0） ====================


@pytest.mark.xfail(strict=True, reason="Wave H 未施工：mixed 无段级记账，断连盲重投")
@pytest.mark.asyncio
async def test_r1_disconnect_no_redispatch_after_parts_booked(
    tmp_path, monkeypatch
) -> None:
    """R1｜断连 9 发负锁（判据：T55 §一.1①-⑦/§五 R1；T65 §三 R1）。

    现状（RED 依据）：mixed 走整发分支且零 progress.count（onebot.py
    :614-642），「count==0 ⇒ 零副作用 ⇒ 可整发重投」恒真 ⇒ 断连形态
    3 内联 × 3 队列轮 = 9 次真实 dispatch、零 UNKNOWN part 行（T55 §一.2）。
    本例断言 A 案（G2-R1 已裁）转绿形态：首轮失败即记账 UNKNOWN + 行置
    PARTIAL 断点，续轮零再投（杜绝「语音真投 9 遍、账本零 SENT」）。

    flipped 条件：H 波落地 `_chunk_part_plan` mixed 分支 + sender 补
    count/UNKNOWN 回报（T55 §4.4.1/§4.4.2）→ 摘 xfail 标记 → 应绿。
    烘焙耦合点：C1（freeze patch 真身模块 domains.transport.sender.onebot）、
    C4（显式 now，首轮 >60s 认领宽限、步进 >90s PARTIAL 补偿退避）、
    C6（只断言 part 行存在 ∧ UNKNOWN 非空，不断言键粒度）。
    刻意不断言终轮 dispatch 绝对值（1 vs 3）：内联 3 连发在 A 案最小改造面
    下去留未裁（与 C6 同源的歧义），只锁「续轮零增长」这一形态无关不变量。
    """
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    bot = SimulatedOneBotBot(behavior="raise")
    transport = make_transport(bot)
    _submit_mixed(queue, "r1", record=_RECORD)

    await run_queue_rounds(queue, transport, rounds=1, base_now=_BASE)
    after_round1 = dispatch_count(bot)

    await run_queue_rounds(queue, transport, rounds=2, base_now=_BASE)

    assert unknown_part_indexes(queue, "r1") != []  # 现状 []：mixed 永不进 part 系统
    assert part_states(queue, "r1") != {}
    assert queue_row(queue, "r1")["state"] == "partial"  # 现状 failed_retryable
    assert partial_rows(queue) != []
    # 现状实测 6 != 3（每有效轮 +3 内联；T55 §一.2 三有效轮上限=9）。
    assert dispatch_count(bot) == after_round1


# ==================== R2｜纯超时形态（1×3=3 发） ====================


@pytest.mark.xfail(strict=True, reason="Wave H 未施工：超时形态零 UNKNOWN 记账，盲重投")
@pytest.mark.asyncio
async def test_r2_pure_timeout_single_dispatch_then_partial(tmp_path, monkeypatch) -> None:
    """R2｜纯超时 3 发分形态（判据：T55 §一.2 表/§五 R2；T65 §三 R2）。

    现状（RED 依据）：超时分支不内联重试（T55 §一.2）⇒ 每轮 1 dispatch、
    连烧 3 轮（issue=timeout_zero_part_delivered，onebot.py:901），每轮整发
    重投。本例断言转绿形态：首轮 1 发后 part 记 UNKNOWN、行置 PARTIAL，
    续轮零再投（SnowLuma 转码+波形+上传慢过预算的最现实路径，T46 §四 M-63）。

    flipped 条件：同 R1（A 案 worker 计划门 + sender UNKNOWN 回报）→ 摘标记。
    烘焙耦合点：C1、C4、C6（同 R1）。timeout 形态不涉内联连发歧义，
    故前后两段 dispatch 都钉绝对值 1。
    """
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    bot = SimulatedOneBotBot(behavior=("timeout", 1.0))
    transport = make_transport(bot, timeout_seconds=0.05)  # 15s 预算毫秒级仿真
    _submit_mixed(queue, "r2", record=_RECORD)

    results = await run_queue_rounds(queue, transport, rounds=1, base_now=_BASE)
    assert dispatch_count(bot) == 1  # 超时分支立即 return，无内联连发（今绿后绿）
    assert any(
        issue.kind == "timeout_zero_part_delivered"
        for issue in results[0].operational_issues
    )

    await run_queue_rounds(queue, transport, rounds=2, base_now=_BASE)

    assert dispatch_count(bot) == 1  # 现状实测 2：每个有效认领轮再整发 1 次
    assert unknown_part_indexes(queue, "r2") != []  # 现状 []
    assert queue_row(queue, "r2")["state"] == "partial"  # 现状 failed_retryable


# ==================== R3/R4/R6/R9 共用骨架 ====================


async def _run_fatal_round1_case(
    tmp_path, monkeypatch, *, behavior, rid: str, record: str
) -> None:
    """R3/R4/R6/R9 共用骨架：断言「确定性拒绝第 1 轮即终态 + W1 文字降级
    恰好一次 + record 不重发」（判据：T55 §三 W1 行/§五 R3/R6；T46 §3.5；
    T65 §三 R3/R6）。"""
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    bot = SimulatedOneBotBot(behavior=behavior)
    transport = make_transport(bot)
    _submit_mixed(queue, rid, record=record)

    await run_queue_rounds(queue, transport, rounds=1, base_now=_BASE)
    row1 = queue_row(queue, rid)

    await run_queue_rounds(queue, transport, rounds=2, base_now=_BASE)

    # 第 1 轮即终态（现状 failed_retryable：白名单 {403,404,1003,1200,1201,
    # 1401,1403,1404} 无 1400/100，onebot.py:119-122，T55 §二.1）。
    assert row1["state"] == "failed_final"
    row3 = queue_row(queue, rid)
    assert row3["state"] == "failed_final"
    assert row3["retry_count"] == row1["retry_count"]  # 现状 3 != 1：盲烧 3 轮
    # 台账恰 2 条 dispatch：1 条 fatal 整发（text+record）+ 1 条 -textfb 纯
    # 文字降级（worker.py:622-665，幂等键防撞）。现状 3 发整发+第 3 轮末才降级。
    assert dispatch_count(bot) == 2
    assert sent_texts(bot) == [_TEXT]  # 文字恰一次（降级只发一次）
    assert record_files(bot) == [record]  # record 不重发；现状 3 条


@pytest.mark.xfail(strict=True, reason="Wave H 未施工：1400 不在终态白名单，毒件盲烧 3 轮")
@pytest.mark.asyncio
async def test_r3_retcode_1400_final_in_round_one(tmp_path, monkeypatch) -> None:
    """R3｜retcode 1400 首轮终态 + W1 文字保住（T46 §3.5 表行 1；T65 §三 R3）。

    SnowLuma 1400=BAD_REQUEST（段校验失败，重发必同败的确定性拒绝，
    config-GJCFWjtq.js:907-910），我方白名单缺码 ⇒ FAILED_RETRYABLE 盲烧
    3 轮。转绿 = 白名单扩 1400（T55 §4.4.4 ①「1400 可白名单化」）。

    flipped 条件：H 波把 1400 纳入 `_is_final_failure_retcode` → 摘标记 → 应绿。
    烘焙耦合点：C1、C4；W1 降级是既有 worker 面（零新机制，T55 §三 W1 行）。
    """
    await _run_fatal_round1_case(
        tmp_path,
        monkeypatch,
        behavior=("action_failed", 1400),
        rid="r3",
        record=_RECORD,
    )


@pytest.mark.xfail(strict=True, reason="Wave H 未施工：100 分码未裁，按白名单形态先锁 RED")
@pytest.mark.asyncio
async def test_r4_retcode_100_ruling_lock_whitelist_form(tmp_path, monkeypatch) -> None:
    """R4｜retcode 100 分码裁决锁（T46 §3.5 表行 2；T55 §二.1/§五 R4；T65 §三 R4）。

    100=ACTION_FAILED（通用码，可能裹暂态上游错）：T55 §4.4.4 建议保持
    可重试（防误终态化暂态），T65 §三 R4 留二选一。本例按**白名单化形态**
    先锁 RED（与 R3 同判据）；若 H 波裁决「保持可重试」，翻转动作 =
    摘标记的同时把断言改写为「3 轮重试语义」正锁（T65 §三 R4 绿栏原文），
    而非直接删标记——两种裁决都必须显式过一次翻转动作，杜绝静默改语义。

    flipped 条件：H 波对 100 出分码裁决（白名单化 → 本例直接转绿；
    保持可重试 → 改写为正锁）。
    烘焙耦合点：C1、C4。
    """
    await _run_fatal_round1_case(
        tmp_path,
        monkeypatch,
        behavior=("action_failed", 100),
        rid="r4",
        record=_RECORD,
    )


# ==================== R5｜retcode 1200 挂起语义正锁（非 xfail） ====================


@pytest.mark.asyncio
async def test_r5_retcode_1200_hold_semantics_positive_lock(tmp_path, monkeypatch) -> None:
    """R5｜retcode 1200 挂起语义**正锁**（判据：T55 §二.1 表行 3/§六.2；T46 §3.5；
    T65 §三 R5；queue.py:802-851 _defer_for_bot_unavailable）。

    现状语义：1200 → bot_unavailable 挂起（不烧 retry_count 预算、零降级
    零重投），入队年龄超上限才终态。本例把现状锁成**正锁**而非 xfail：
    1200 处置语义等用户裁决（T55 §4.4.4 ②「1200 语义处置须与 A 案同波
    裁决」），现状即绿，标 xfail(strict) 会立即 xpass 炸套件——与
    「8 xfail/0 xpass」硬目标冲突。翻转方式：H 波按裁决改 1200 语义时本例
    必红 ⇒ 强制翻议后随裁决改写断言（它就是裁决的绊线，不是待绿项）。

    诚实注记：1200 在 SnowLuma 下只在「stream action dispatched without a
    sink」发射（INTERNAL_ERROR，config-GJCFWjtq.js:1440），与「适配器无连接」
    旧语义已漂移；其常量历史由来=unknown（T55 §二.2，零 git 历史可溯）。

    烘焙耦合点：C1（动作拒绝分支不内联重试）、C4（显式 now 跨年龄上限）、
    C5（bot_unavailable_max_age_seconds 透传收小到 10s；首轮 now 已在
    认领宽限外，年龄即刻超限 ⇒ 挂起形态以「零预算消耗 + 零降级」判据锁定）。
    """
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path, bot_unavailable_max_age_seconds=10.0)
    bot = SimulatedOneBotBot(behavior=("action_failed", 1200))
    transport = make_transport(bot)
    _submit_mixed(queue, "r5", record=_RECORD)

    results = await run_queue_rounds(queue, transport, rounds=3, base_now=_BASE)

    row = queue_row(queue, "r5")
    assert any(
        issue.kind == "bot_unavailable" for issue in results[0].operational_issues
    )
    assert row["state"] == "failed_final"  # 年龄超限的挂起到期终态
    assert row["retry_count"] == 0  # 挂起不烧重试预算（与 1400 盲烧的本质区别）
    assert dispatch_count(bot) == 1  # 拒绝分支不内联重试、终态前不再认领
    # 恰 1 条 dispatch ⇒ 零 W1 降级补发（bot_unavailable 非明确拒绝，不触发
    # worker.py:303-311 降级门）；文字段来自该 mixed 整发本身（text+record）。
    assert sent_texts(bot) == [_TEXT]
    assert record_files(bot) == [_RECORD]


# ==================== R6｜毒语音文字保全（SnowLuma fatal + W1） ====================


@pytest.mark.xfail(strict=True, reason="Wave H 未施工：毒语音拖文字盲烧 3 轮才降级")
@pytest.mark.asyncio
async def test_r6_poison_record_text_preserved_in_round_one(tmp_path, monkeypatch) -> None:
    """R6｜毒语音文字保全负锁（判据：T46 §2.4/§2.6/§四；T55 §三 W1 行/§五 R6；
    T65 §三 R6）。

    毒语音（file 指向不存在路径：生产 _resolve_local_file_ref:315-323 原样
    返回照上送，我方不拦）⇒ SnowLuma loadPtt 抛 ⇒ 整条 text+record 原子失败
    （T46 §四「更危险」面）。现状：整条盲烧 3 轮后 W1 才补文字；转绿 =
    1400 白名单化后第 1 轮终态、文字立即恰好一次。

    flipped 条件：同 R3（白名单扩 1400）→ 摘标记 → 应绿。
    烘焙耦合点：C1、C4；W1 既有降级面零新机制。
    """
    await _run_fatal_round1_case(
        tmp_path,
        monkeypatch,
        behavior=("action_failed", 1400),
        rid="r6",
        record=_RECORD_POISON,
    )


# ==================== R7｜说 X 单 record 回归锁（R-16②） ====================


@pytest.mark.xfail(strict=True, reason="Wave H 未施工：说 X mixed 不进 part 计划（现状无 part 行）")
@pytest.mark.asyncio
async def test_r7_say_x_no_text_negative_lock(tmp_path, monkeypatch) -> None:
    """R7｜`说 X` 单 record 回归锁（判据：T55 §三共性边界①/§六.4/§五 R7；
    T65 §三 R7；R-16②：失败告知归中央 A-19，传输层禁止自拼文案）。

    用 1404（已在现行白名单内）构造**真 FAILED_FINAL** 形态：无 text part
    ⇒ _fallback_text_for_media 返回 None ⇒ 零降级零反馈。断言两件事：
    ① sent_texts 恒空（传输层永不为说 X 拼文案——今绿后绿的永恒回归锁）；
    ② 说 X 的 mixed 也进 part 计划（A 案「保 mixed + 段级记账」对全体 mixed
    生效；现状无 part 行 ⇒ 唯一 RED 点，驱动本例 xfail）。

    flipped 条件：H 波 mixed 计划门覆盖单 record mixed → 摘标记 → 应绿
    （此后本例转为 R-16② 永久正锁）。
    烘焙耦合点：C1、C2（假 bot 不实现 forward 可选 API，mixed 走直发）、
    C4、C6（不断言 part 键粒度）。
    """
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    bot = SimulatedOneBotBot(behavior=("action_failed", 1404))
    transport = make_transport(bot)
    _submit_mixed(queue, "r7", record=_RECORD_SAYX, text=None)  # 说 X：无文字

    await run_queue_rounds(queue, transport, rounds=3, base_now=_BASE)

    assert sent_texts(bot) == []  # R-16②：零自拼文案（今绿后绿）
    assert queue_row(queue, "r7")["state"] == "failed_final"  # 1404 今即首轮终态
    assert dispatch_count(bot) == 1  # 拒绝分支无内联连发、终态后零补偿投递
    assert record_files(bot) == [_RECORD_SAYX]
    assert part_states(queue, "r7") != {}  # 现状 {}：唯一 RED 点（A 案计划门）


# ==================== R8｜mixed 段级记账计划门（A 案核心判据） ====================


@pytest.mark.xfail(strict=True, reason="Wave H 未施工：mixed 永不进 part 计划（worker.py:561-562）")
@pytest.mark.asyncio
async def test_r8_mixed_part_planning_gate(tmp_path, monkeypatch) -> None:
    """R8｜mixed 进 part 计划 + scope 负样本门（判据：T55 §4.2/§4.4.1/§五 R8；
    T65 §三 R8/§四 C6；G2-R1 A 案）。

    A 案最小改造面（本席钉明的假设形态）：**worker 计划门 mixed 分支**
    （_chunk_part_plan 为 mixed content_ref["parts"] 生成 part 计划）+
    **sender 补 count/UNKNOWN 回报**（onebot.py:614-642 成功计 count、
    结果未知回报 UNKNOWN；queue 层零 schema 改动，T55 §4.4.3）。
    键粒度（段级键 vs 整条单键）是 T55 §4.4 留给 H 波的裁决点（C6）：
    本例只断言「part 行存在」，不断言键数量/粒度，粒度断言待裁决后补。

    负样本：非 PRIVATE/GROUP（CHANNEL）的 mixed 不进计划、走整发——对齐
    worker.py:563 既有 scope 门（今绿后绿）。

    flipped 条件：H 波落地 mixed 计划分支 → 摘标记 → 应绿。
    烘焙耦合点：C1、C4、C6（如上，粒度零断言）。
    """
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    bot = SimulatedOneBotBot(behavior="ok")
    transport = make_transport(bot)
    _submit_mixed(queue, "r8-mixed", record=_RECORD)
    channel = build_mixed_request(
        "r8-channel",
        text=_TEXT,
        record_file="voice-channel.wav",
        target_scope=SessionType.CHANNEL,
    )
    queue.submit(channel, now=_BASE)

    await run_queue_rounds(queue, transport, rounds=1, base_now=_BASE)

    assert part_states(queue, "r8-mixed") != {}  # 现状 {}：mixed 永不计划（RED 点）
    assert part_states(queue, "r8-channel") == {}  # 负样本：scope 门恒拦
    # 两者都整发达成（序不敏感：认领序非本例判据）。
    assert sorted(record_files(bot)) == sorted([_RECORD, "voice-channel.wav"])


# ==================== R9｜failed dict 形态（SnowLuma 主回执形态，配方外补充） ===


@pytest.mark.xfail(strict=True, reason="Wave H 未施工：failed-dict 1400 同样盲烧 3 轮（配方外 R9）")
@pytest.mark.asyncio
async def test_r9_snowluma_failed_dict_1400_fatal_with_fallback(
    tmp_path, monkeypatch
) -> None:
    """R9｜SnowLuma failed dict 形态的 fatal→W1 链（判据：T46 §2.6/§3.5；
    T55 §五 R3；T65 §三 R3——本例是 T65 配方外的同链异形态补充）。

    T65 R3/R4/R5/R6 全部走 ActionFailed 异常形态（retcode 藏 .info）；
    SnowLuma 确定性拒绝的**主回执形态是结构化 failed dict**
    {status:"failed", retcode, data:null, wording}（T46 §2.6），走我方
    onebot.py:914+ 的 dict 分支（与 :842-888 异常分支不同代码路径，T55
    §一.1④「三处都读 count」）。M-63/T46-N1 若只修异常形态面，dict 面
    依旧盲烧——本例把同一转绿判据（首轮终态 + W1 文字恰一次 + record
    不重发）钉在 dict 形态上，堵「修一半」缺口。

    flipped 条件：同 R3（白名单扩 1400 须同时覆盖 dict 分支 :940-973 与
    异常分支 :842-860）→ 摘标记 → 应绿。
    烘焙耦合点：C1、C4；wording 字段我方现不消费（T46-N2，不在本例断言面）。
    """
    await _run_fatal_round1_case(
        tmp_path,
        monkeypatch,
        behavior=("retcode", 1400),
        rid="r9",
        record=_RECORD,
    )
