"""T71 Wave H 棘轮：语音投递验收 R1-R9（xfail(strict) 棘轮）。

把 report-T65.md §三 的 R1-R8 配方（判据源=report-T55.md §五/§4.4、
report-T46.md §3.5）落成 8 例 xfail(strict) 棘轮 + 1 例正锁（R5）：
- 现期：Wave H 未施工 ⇒ 8 例 xfail、0 failed、0 xpass，套件绿；
- H 波施工（A 案：worker 计划门 mixed 分支 + sender 补 count/UNKNOWN 回报，
  progress.md G2-R1 已裁）落地后 xpass 触发 strict 失败 ⇒ 强制摘标记翻转；
- R5（retcode 1200）语义等用户裁决，现状即绿、不可 xfail（会立即 xpass），
  故落为**正锁**：H 波改动 1200 语义时本例必红，强制翻议（见其 docstring）。

翻转状态（2026-09-19，T85 席，判据冲突裁处——蓝本=report-T78 §三裁决选项）：
- T78 已摘标记转绿：R1（断连）、R2（超时）、R7（说 X 计划门）——断言体零改动；
- T78 已按自带协议改写：R5（1200 终态化裁决，见其 docstring 与回滚点）；
- T85 裁处转正锁（原五例 xfail 的判据冲突，逐例「原断言→新断言→依据」
  见各 docstring 改写记录与 report-T85.md）：
  R3/R4/R6/R9——`sent_texts == [_TEXT]`（「文字恰一次 delivered」意图）
  在仿真器 attempt 台账语义（tests/helpers 冻结件，统计全部调用含被拒
  attempt）下不可满足：原子 mixed 尝试与 -textfb 降级尝试各贡献一次
  text 段 ⇒ 实况 `[_TEXT, _TEXT]`；「文字部件 delivered」判据在 behavior
  均匀拒绝形态结构性不可观测（part 终态=failed_final、降级直调
  transport 不入 queue part 系统，delivered-only 语义下又是 `[]`）。
  裁决=钉 attempt 台账判据 `== [_TEXT, _TEXT]` + queue part 终态双判据
  （T78 §三 选项 b + 二选一裁定），与 `dispatch_count == 2` ∧
  `record_files == [record]` 联合锁「W1 降级恰好一次、record 不重发」；
  R8——CHANNEL 负样本在 sender 整发分支落 unsupported_target BLOCKED
  （零 API 调用，零投递=scope 门正确行为）⇒ `record_files` 恰两项不可
  满足；裁决=改查 CHANNEL 行终态 `failed_final` ∧ `dispatch_count == 1`
  ∧ `record_files == [_RECORD]`；正样本升级为段级键粒度精确断言
  （T78 C6 留白收口）。
- 至此本文件 9 例全绿正锁、零 xfail（棘轮闭合）。
- 2026-10-03（施工席30）：R1/R2 行终态断言 partial → failed_final——对齐
  Q-G7 休眠 PARTIAL 终态化现语义（queue.py `_finalize_dormant_partial_in`：
  UNKNOWN 零进展续轮宁终态不盲重发、part 账原样保留，探针实测
  round1=partial → round2=failed_final）；UNKNOWN 记账与「续轮零再投」
  锁不动。上文「9 例全绿」＝T85 当时值。

pytest 无全局 xfail_strict（pyproject.toml [tool.pytest.ini_options] 实查），
strict 必须逐标记显式声明。

离线运行（零网络零墙钟断言）：

    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_h_voice_delivery.py -q -p no:cacheprovider \\
      --basetemp="../ChatBot_Runtime/cache/t85"
"""

from __future__ import annotations

from datetime import datetime

import pytest
from helpers.voice_queue_sim import (
    PART_STATE_FAILED_FINAL,
    PART_STATE_SENT,
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
# 翻转记录（T78，2026-09-20）：xfail 标记已摘——A 案（worker mixed 段级计划门
# + 原子整发分支 UNKNOWN 喂入）落地后本例转绿，断言体零改动。


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

    对齐记账（2026-10-03，对齐 T55/T65/T85 判据链现语义）：行终态断言
    partial → failed_final。Q-G7 休眠 PARTIAL 收口（queue.py
    `_finalize_dormant_partial_in`，S-FIX-QPARK）现语义：首轮 UNKNOWN
    记账 + PARTIAL 断点（90s 补偿退避，探针实测 round1=partial），续轮
    补偿扫描零进展（UNKNOWN 无确认者、无 PENDING 可推进）⇒ 休眠终态化
    failed_final（宁漏不盲重发；part 明细账原样保留）。终态化后「续轮
    零再投」不变量更强（终态行不再认领）。

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

    assert unknown_part_indexes(queue, "r1") != []  # A 案：mixed 进 part 系统（UNKNOWN 记账）
    assert part_states(queue, "r1") != {}
    # 2026-10-03 对齐现语义：PARTIAL 断点后续轮零进展 ⇒ Q-G7 休眠终态化
    # failed_final（探针实测 round2 起，last_public_message='dormant_final
    # delivered=0/2'）；旧实现断连形态=failed_retryable 盲烧。
    assert queue_row(queue, "r1")["state"] == "failed_final"
    assert partial_rows(queue) == []  # 终态行离开 PARTIAL 断点面（不再可续发）
    # 旧实现 6 != 3（每有效轮 +3 内联；T55 §一.2 三有效轮上限=9）。
    assert dispatch_count(bot) == after_round1


# ==================== R2｜纯超时形态（1×3=3 发） ====================
# 翻转记录（T78，2026-09-20）：xfail 标记已摘，断言体零改动（同 R1）。


@pytest.mark.asyncio
async def test_r2_pure_timeout_single_dispatch_then_partial(tmp_path, monkeypatch) -> None:
    """R2｜纯超时 3 发分形态（判据：T55 §一.2 表/§五 R2；T65 §三 R2）。

    现状（RED 依据）：超时分支不内联重试（T55 §一.2）⇒ 每轮 1 dispatch、
    连烧 3 轮（issue=timeout_zero_part_delivered，onebot.py:901），每轮整发
    重投。本例断言转绿形态：首轮 1 发后 part 记 UNKNOWN、行置 PARTIAL，
    续轮零再投（SnowLuma 转码+波形+上传慢过预算的最现实路径，T46 §四 M-63）。

    对齐记账（2026-10-03，对齐 T55/T65/T85 判据链现语义）：行终态断言
    partial → failed_final（Q-G7 休眠 PARTIAL 终态化现语义，同 R1——
    UNKNOWN 零进展续轮宁终态不盲重发；UNKNOWN 记账与零再投锁不动）。

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

    assert dispatch_count(bot) == 1  # 首轮后零再投（旧实现每有效认领轮再整发 1 次）
    assert unknown_part_indexes(queue, "r2") != []  # A 案：UNKNOWN 记账
    # 2026-10-03 对齐现语义：PARTIAL 断点后续轮零进展 ⇒ Q-G7 休眠终态化
    # failed_final（同 R1）；旧实现=failed_retryable 盲烧。
    assert queue_row(queue, "r2")["state"] == "failed_final"


# ==================== R3/R4/R6/R9 共用骨架 ====================


async def _run_fatal_round1_case(
    tmp_path, monkeypatch, *, behavior, rid: str, record: str
) -> None:
    """R3/R4/R6/R9 共用骨架：断言「确定性拒绝第 1 轮即终态 + W1 文字降级
    恰好一次 + record 不重发 + part 全体终态」（判据：T55 §三 W1 行/§五
    R3/R6；T46 §3.5；T65 §三 R3/R6；判据冲突裁处=report-T85 §二）。

    改写记录（T85，2026-09-19；原判据冲突=report-T78 §三.1）：
    - 原断言 `sent_texts(bot) == [_TEXT]`（「文字恰一次 delivered」意图）
      → 新断言 `sent_texts(bot) == [_TEXT, _TEXT]`：仿真器台账是 attempt
      语义（tests/helpers 为冻结件，统计全部调用含被拒 attempt），原子
      mixed 尝试（被拒）与 -textfb 降级尝试（behavior 均匀注入同样被拒）
      各贡献一次 text 段；delivered 语义在该注入形态下两端皆不可满足
      （delivered-only ⇒ `[]`）。attempt 形态的 `[_TEXT, _TEXT]` 与
      `dispatch_count == 2` ∧ `record_files == [record]` 联合锁定：第 2 条
      dispatch 是纯文字降级、恰好一次、无第三次投递——杀伤力不低于原
      意图（恰一次语义由 dispatch 绝对值承载，text 段计数承载「降级文本
      =mixed 文字部件」）。
    - 增补 part 终态断言 `{0: failed_final, 1: failed_final}` + row1
      `parts_total == 2` + `retry_count == 0`：段级键粒度（T78 C6 已钉明）
      与「终态不经重试预算」一并钉死；「文字部件 delivered」判据在本
      形态结构性不可观测（part 终态=failed_final；降级直调 transport 不
      入 queue part 系统），二选一裁定=钉 queue part 状态侧。
    """
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    bot = SimulatedOneBotBot(behavior=behavior)
    transport = make_transport(bot)
    _submit_mixed(queue, rid, record=record)

    await run_queue_rounds(queue, transport, rounds=1, base_now=_BASE)
    row1 = queue_row(queue, rid)

    await run_queue_rounds(queue, transport, rounds=2, base_now=_BASE)

    # 第 1 轮即终态（旧实现 failed_retryable：白名单无 1400/100 ⇒ 盲烧 3 轮）。
    assert row1["state"] == "failed_final"
    assert row1["retry_count"] == 0  # 终态不经重试预算（旧实现 3）
    assert row1["parts_total"] == 2  # 段级键粒度（旧实现 mixed 无 part 行）
    row3 = queue_row(queue, rid)
    assert row3["state"] == "failed_final"
    assert row3["retry_count"] == row1["retry_count"]  # 续轮零烧
    # 台账恰 2 条 dispatch：1 条 fatal 整发（text+record，被拒）+ 1 条
    # -textfb 纯文字降级尝试（worker.py `_send_media_text_fallback_once`，
    # 幂等键防撞、失败只记审计不重试）。旧实现 3 发整发+第 3 轮末才降级。
    assert dispatch_count(bot) == 2
    # attempt 台账语义（见 docstring 改写记录）：两次 text 段 = 原子 mixed
    # 尝试 + 恰一次 W1 降级尝试；与 dispatch==2 联合排除第三次投递。
    assert sent_texts(bot) == [_TEXT, _TEXT]
    assert record_files(bot) == [record]  # record 不重发；旧实现 3 条
    # part 全体终态：原子同进退，零 UNKNOWN 残留、零 PENDING 重投面。
    assert part_states(queue, rid) == {
        0: PART_STATE_FAILED_FINAL,
        1: PART_STATE_FAILED_FINAL,
    }


@pytest.mark.asyncio
async def test_r3_retcode_1400_final_in_round_one(tmp_path, monkeypatch) -> None:
    """R3｜retcode 1400 首轮终态 + W1 文字保住（T46 §3.5 表行 1；T65 §三 R3）。

    SnowLuma 1400=BAD_REQUEST（段校验失败，重发必同败的确定性拒绝，
    config-GJCFWjtq.js:907-910）。1400 已入 `_is_final_failure_retcode`
    白名单（T46-N1），第 1 轮 FAILED_FINAL + W1 立即接住混排文字部件。

    改写记录（T85）：xfail 已摘转正锁；骨架断言按 report-T85 §二 改写
    （sent_texts attempt 台账判据 `[_TEXT, _TEXT]` + part 终态，见
    `_run_fatal_round1_case` docstring）。旧版取证：对 194a2ca^ 旧实现
    本例红（row1=failed_retryable、part 行缺失、第 3 轮末才降级）。
    烘焙耦合点：C1、C4；W1 降级是既有 worker 面（零新机制，T55 §三 W1 行）。
    """
    await _run_fatal_round1_case(
        tmp_path,
        monkeypatch,
        behavior=("action_failed", 1400),
        rid="r3",
        record=_RECORD,
    )


@pytest.mark.asyncio
async def test_r4_retcode_100_ruling_lock_whitelist_form(tmp_path, monkeypatch) -> None:
    """R4｜retcode 100 分码裁决锁（T46 §3.5 表行 2；T55 §二.1/§五 R4；T65 §三 R4）。

    裁决记账（T85）：T46-N1 已把 100=ACTION_FAILED 纳入白名单（已披露
    反向风险：100 词面通用可能裹暂态；接受理由=SnowLuma 唯一在役+重发
    同败+W1 保文字；回滚点=白名单摘 100，见 onebot.py
    `_is_final_failure_retcode` docstring）。故原二选一裁决落定
    「白名单化形态」：本例按与 R3 同判据转正锁；若未来回滚摘 100，本例
    即红 ⇒ 强制重开 100 分码裁决——原「两种裁决都必须显式过一次翻转
    动作」的棘轮语义保持。

    改写记录（T85）：xfail 已摘转正锁；骨架断言改写见
    `_run_fatal_round1_case` docstring（report-T85 §二）。旧版取证：对
    194a2ca^ 旧实现本例红（100 不在旧白名单）。
    烘焙耦合点：C1、C4。
    """
    await _run_fatal_round1_case(
        tmp_path,
        monkeypatch,
        behavior=("action_failed", 100),
        rid="r4",
        record=_RECORD,
    )


# ==================== R5｜retcode 1200 语义正锁（T78 终态化裁决后改写） ====================


@pytest.mark.asyncio
async def test_r5_retcode_1200_terminalized_positive_lock(tmp_path, monkeypatch) -> None:
    """R5｜retcode 1200 **终态化**语义正锁（原名
    test_r5_retcode_1200_hold_semantics_positive_lock；按本例原 docstring
    「H 波按裁决改 1200 语义时必红 ⇒ 强制翻议后随裁决改写断言」的翻转协议，
    随 T78 席 2026-09-20 终态化裁决改写）。

    裁决（T46-N1 连带，选型记录见 report-T78）：SnowLuma 的 1200 只在
    「stream action dispatched without a sink」发射（INTERNAL_ERROR，
    config-GJCFWjtq.js:1440，report-T46 §3.5 / report-T55 §二.1 实复核），
    与「适配器无连接」旧 NapCat 语义已漂移（常量历史由来=unknown，T55
    §二.2）；真断线走 NoneBot 异常（无 .info.retcode）路径。故废除 R2
    （2026-09-17）的 bot_unavailable 挂起 30 分钟语义，1200 经白名单第 1 轮
    FAILED_FINAL + W1 文本降级。**回滚点**：恢复
    `_ONEBOT_API_UNAVAILABLE_RETCODE=1200` 拦截分支 + `_bot_unavailable_receipt`
    （onebot.py，本裁决前 git 历史）+ 本例改回挂起判据。

    烘焙耦合点：C1（动作拒绝分支不内联重试）、C4（显式 now）。behavior 均匀
    注入使 W1 降级尝试同样被拒（attempt 台账仍记账），与 R3 骨架同形态。
    """
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path, bot_unavailable_max_age_seconds=10.0)
    bot = SimulatedOneBotBot(behavior=("action_failed", 1200))
    transport = make_transport(bot)
    _submit_mixed(queue, "r5", record=_RECORD)

    results = await run_queue_rounds(queue, transport, rounds=3, base_now=_BASE)

    row = queue_row(queue, "r5")
    # 终态化判据：白名单 retcode_failure 第 1 轮终态；bot_unavailable kind
    # 在 sender 侧已无生产者（queue._defer_for_bot_unavailable 保留为防御
    # 基建，但不再由 1200 触发）。
    assert any(
        issue.kind == "retcode_failure" for issue in results[0].operational_issues
    )
    assert not any(
        issue.kind == "bot_unavailable" for issue in results[0].operational_issues
    )
    assert row["state"] == "failed_final"  # 第 1 轮即终态：无挂起等待窗
    assert row["retry_count"] == 0  # 终态不经重试预算（零烧判据保留）
    # 恰 2 条 dispatch：1 条 fatal 整发 + 1 条 W1 文本降级尝试（-textfb；
    # behavior 均匀注入使其同样被拒，attempt 台账仍记账）。
    assert dispatch_count(bot) == 2
    assert record_files(bot) == [_RECORD]  # 零盲重投


# ==================== R6｜毒语音文字保全（SnowLuma fatal + W1） ====================


@pytest.mark.asyncio
async def test_r6_poison_record_text_preserved_in_round_one(tmp_path, monkeypatch) -> None:
    """R6｜毒语音文字保全负锁（判据：T46 §2.4/§2.6/§四；T55 §三 W1 行/§五 R6；
    T65 §三 R6）。

    毒语音（file 指向不存在路径：生产 _resolve_local_file_ref:315-323 原样
    返回照上送，我方不拦）⇒ SnowLuma loadPtt 抛 ⇒ 整条 text+record 原子失败
    （T46 §四「更危险」面）。1400 白名单化后第 1 轮终态、W1 立即补文字。

    改写记录（T85）：xfail 已摘转正锁；骨架断言按 report-T85 §二 改写
    （sent_texts attempt 台账判据 + part 终态，见
    `_run_fatal_round1_case` docstring）。旧版取证：对 194a2ca^ 旧实现
    本例红（毒件拖文字盲烧 3 轮才降级）。
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
# 翻转记录（T78，2026-09-20）：xfail 标记已摘，断言体零改动——单 record mixed
# 已进段级计划（计划门覆盖全体 mixed），R-16② 零自拼文案转为永久正锁。


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


@pytest.mark.asyncio
async def test_r8_mixed_part_planning_gate(tmp_path, monkeypatch) -> None:
    """R8｜mixed 进 part 计划 + scope 负样本门（判据：T55 §4.2/§4.4.1/§五 R8；
    T65 §三 R8/§四 C6；G2-R1 A 案；判据冲突裁处=report-T85 §二）。

    A 案已落地（T78）：worker 计划门 mixed 分支（`_chunk_part_plan` 为
    content_ref["parts"] 生成段级计划）+ sender 补 count/UNKNOWN 回报。
    键粒度裁决=T78 席钉明**段级键**（`_chunk_part_plan` docstring+报告双
    落），本例据此把原 C6 留白升级为精确粒度断言。

    改写记录（T85，2026-09-19；原判据冲突=report-T78 §三.2）：
    - 原断言 `sorted(record_files(bot)) == sorted([_RECORD,
      "voice-channel.wav"])`（「两者都整发达成」假设）→ 新断言
      `record_files(bot) == [_RECORD]` ∧ `dispatch_count(bot) == 1` ∧
      CHANNEL 行 `failed_final`：CHANNEL 负样本在 sender
      `_dispatch_onebot_send` 整发分支落 `unsupported_target` BLOCKED
      （onebot.py else 支路），**零 API 调用** ⇒ 其 record 永不入台账。
      零投递正是 scope 门的正确行为；BLOCKED → worker
      `_persist_receipt_state` → `mark_final_failure` ⇒ 行终态
      failed_final，改查行终态与 dispatch 绝对值。
    - 正样本升级：`part_states == {0: sent, 1: sent}`（原 `!= {}`）——
      段级粒度 + 原子同进退精确锁；并补 mixed 行态 `sent`。
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

    # 正样本：mixed 进段级计划，原子整发成功后全体 part 同记 SENT。
    assert part_states(queue, "r8-mixed") == {
        0: PART_STATE_SENT,
        1: PART_STATE_SENT,
    }
    assert queue_row(queue, "r8-mixed")["state"] == "sent"
    # 负样本：非 PRIVATE/GROUP（CHANNEL）不进计划（worker scope 门恒拦）。
    assert part_states(queue, "r8-channel") == {}
    # CHANNEL 整发分支即被 unsupported_target BLOCKED，零 API 调用：
    # 台账只有 PRIVATE mixed 的一次调用；语音零投递=scope 门正确行为。
    assert record_files(bot) == [_RECORD]
    assert dispatch_count(bot) == 1
    assert queue_row(queue, "r8-channel")["state"] == "failed_final"


# ==================== R9｜failed dict 形态（SnowLuma 主回执形态，配方外补充） ===


@pytest.mark.asyncio
async def test_r9_snowluma_failed_dict_1400_fatal_with_fallback(
    tmp_path, monkeypatch
) -> None:
    """R9｜SnowLuma failed dict 形态的 fatal→W1 链（判据：T46 §2.6/§3.5；
    T55 §五 R3；T65 §三 R3——本例是 T65 配方外的同链异形态补充）。

    T65 R3/R4/R5/R6 全部走 ActionFailed 异常形态（retcode 藏 .info）；
    SnowLuma 确定性拒绝的**主回执形态是结构化 failed dict**
    {status:"failed", retcode, data:null, wording}（T46 §2.6），走 onebot
    dict 分支（与异常分支不同代码路径）。M-63/T46-N1 两分支都入白名单
    （onebot 异常分支 :850 与 dict 分支 :963 同谓词），本例把同一判据
    （首轮终态 + W1 恰一次 + record 不重发 + part 全体终态）钉在 dict
    形态上，堵「修一半」缺口。

    改写记录（T85）：xfail 已摘转正锁；骨架断言按 report-T85 §二 改写
    （sent_texts attempt 台账判据 + part 终态，见
    `_run_fatal_round1_case` docstring）。旧版取证：对 194a2ca^ 旧实现
    本例红（dict 形态 1400 同样盲烧 3 轮）。
    烘焙耦合点：C1、C4；wording 字段我方现不消费（T46-N2，不在本例断言面）。
    """
    await _run_fatal_round1_case(
        tmp_path,
        monkeypatch,
        behavior=("retcode", 1400),
        rid="r9",
        record=_RECORD,
    )


# ==================== W1｜降级 happy-path 独立正锁（T85 §四.2 交接，T93 补锁） ====


@pytest.mark.asyncio
async def test_w1_text_fallback_happy_path_delivered_round_one(
    tmp_path, monkeypatch
) -> None:
    """W1｜降级 happy-path 独立正锁：文字部件第 1 轮真送达（T85 §四.2 交接）。

    R3/R4/R6/R9 骨架是 behavior 均匀拒绝形态——降级尝试同被拒，只锁
    attempt 台账；本例按 T85 给定形态 `script=[拒绝, "ok"]`：第 1 调用
    （原子 mixed）被 1400 确定拒绝、第 2 调用（W1 纯文字降级）成功回执
    ⇒ 补上「文字真送达一次」的 delivered 侧正锁。

    断言四 面（简报指定）：
    ① dispatch 序列——恰 2 条且都发生在第 1 轮：calls[0]=原子 mixed
      （text+record 两段一次上送），calls[1]=纯文字降级（单 text 段，
      onebot 对 content_type="text" 只产一个 text 段）；
    ② 文字内容——降级段正文 == 混排消息自有文字部件原文（零改写）；
    ③ 语音 part FAILED_FINAL——降级成功**不**翻转行终态（worker
      `_send_media_text_fallback_once`「best effort、不改原行终态」），
      两个 part 终态 failed_final、行 failed_final、零重试预算；
    ④ 无重复投递——record 全程只出现 1 次（降级不带 record），续 2 轮
      dispatch 零增长（终态行不再认领 ⇒ 降级每请求生命周期恰一次）。
    另锁审计侧 delivered 语义：`queue.audit_logger` 是
    SQLiteSendRequestQueue 公有属性（build_sqlite_queue 把
    InMemoryAuditLogger 存在队列对象上，T85「不外露」指构造参数不透出，
    读面无需改 tests/helpers）——经 drain_send_queue_once 的 audit_logger
    形参（run_queue_rounds **drain_kwargs 透传，worker 缺省 None 不落
    worker 级审计）注入同一 logger 后，`queue_worker_text_fallback_sent`
    恰 1 条、`..._failed` 零条，即降级文本**确实**走完 SENT 回执。
    烘焙耦合点：C1（拒绝分支不内联重试）、C4（显式 now）。
    """
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    bot = SimulatedOneBotBot(script=[("action_failed", 1400), "ok"])
    transport = make_transport(bot)
    _submit_mixed(queue, "w1-happy", record=_RECORD)

    results = await run_queue_rounds(
        queue,
        transport,
        rounds=1,
        base_now=_BASE,
        audit_logger=queue.audit_logger,
    )
    round1_dispatch = dispatch_count(bot)
    row1 = queue_row(queue, "w1-happy")

    await run_queue_rounds(queue, transport, rounds=2, base_now=_BASE)

    # ① dispatch 序列：第 1 轮内恰 2 条（原子 mixed + W1 降级），续轮零增长。
    assert any(
        issue.kind == "retcode_failure" for issue in results[0].operational_issues
    )  # W1 触发前提=平台明确拒绝（媒体确定未送达，降级零重复风险）
    assert round1_dispatch == 2
    assert dispatch_count(bot) == 2
    assert [seg["type"] for seg in bot.calls[0].segments] == ["text", "record"]
    assert len(bot.calls[1].segments) == 1
    fallback_segment = bot.calls[1].segments[0]
    assert fallback_segment["type"] == "text"
    # ② 文字内容 == 混排消息自有文字部件原文（零改写、零自拼）。
    assert fallback_segment["data"]["text"] == _TEXT
    # ③ 语音 part 与行均终态：降级成功不翻转原行终态、零重试预算。
    assert record_files(bot) == [_RECORD]  # ④ 降级不带 record，语音零重发
    assert part_states(queue, "w1-happy") == {
        0: PART_STATE_FAILED_FINAL,
        1: PART_STATE_FAILED_FINAL,
    }
    assert row1["state"] == "failed_final"
    assert row1["retry_count"] == 0
    assert queue_row(queue, "w1-happy")["state"] == "failed_final"
    # 审计侧 delivered 语义：降级文本拿到 SENT 回执，恰一次、零失败。
    fallback_events = [
        record.event
        for record in queue.audit_logger.list_records(request_id="w1-happy")
    ]
    assert fallback_events.count("queue_worker_text_fallback_sent") == 1
    assert fallback_events.count("queue_worker_text_fallback_failed") == 0


@pytest.mark.asyncio
async def test_w1_fallback_text_is_own_parts_only_r16_2(
    tmp_path, monkeypatch
) -> None:
    """W1 反向锁（R-16②）：降级发送内容 ⊆ 原消息自有文字部件，零自拼文案。

    R-16②（T55 §三共性边界①/T65 §三 R7）：失败告知归中央 A-19，传输层
    禁止自拼文案。R7 锁的是「无文字 ⇒ 零降级零反馈」；本例补正向构形：
    多文字部件混排（text A + record + text B）下，W1 降级内容必须**恰好
    等于**自有文字部件按原序的 "\\n" 连接（worker `_fallback_text_for_media`
    的规范推导），精确等值锁死任何前缀/后缀/润色/拼装——等值成立即 ⊆
    成立（每个字符都来自消息自身文字部件），任何自拼文案必破坏等值。

    形态：script=[1400 拒绝, "ok"]——断言对象是**实际发出**的内容而非
    仅 attempt（比均匀拒绝形态更严）；且与 R7（说 X 无文字）合起来构成
    R-16② 双向覆盖：无文字⇒不发，有文字⇒只发原文连接。
    烘焙耦合点：C1、C4。
    """
    text_a = "第一段文字。"
    text_b = "第二段文字。"
    freeze_inline_retries(monkeypatch)
    queue = build_sqlite_queue(tmp_path)
    bot = SimulatedOneBotBot(script=[("action_failed", 1400), "ok"])
    transport = make_transport(bot)
    request = build_mixed_request(
        "w1-own-parts",
        parts=[
            {"type": "text", "text": text_a},
            {"type": "record", "file": _RECORD},
            {"type": "text", "text": text_b},
        ],
    )
    queue.submit(request, now=_BASE)

    await run_queue_rounds(queue, transport, rounds=1, base_now=_BASE)

    # 恰 2 条 dispatch：原子 mixed（被拒）+ 恰一次 W1 降级（成功）。
    assert dispatch_count(bot) == 2
    # 降级调用是单 text 段，内容 == 自有文字部件原序 "\n" 连接（精确等值）。
    assert len(bot.calls[1].segments) == 1
    fallback_segment = bot.calls[1].segments[0]
    assert fallback_segment["type"] == "text"
    assert fallback_segment["data"]["text"] == f"{text_a}\n{text_b}"
    # 全生命周期发出的全部文字 ⊆ {自有部件原文} ∪ {规范连接}：原子尝试
    # 贡献 A、B 两段原文，降级贡献连接串——没有第五种内容出现过。
    assert set(sent_texts(bot)) <= {text_a, text_b, f"{text_a}\n{text_b}"}
    assert record_files(bot) == [_RECORD]  # 语音零重发
    # 三 part（含 record）原子同进退全体终态；降级成功不改行终态。
    assert part_states(queue, "w1-own-parts") == {
        0: PART_STATE_FAILED_FINAL,
        1: PART_STATE_FAILED_FINAL,
        2: PART_STATE_FAILED_FINAL,
    }
    assert queue_row(queue, "w1-own-parts")["state"] == "failed_final"
