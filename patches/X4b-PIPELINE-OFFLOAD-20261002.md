# X4b — 管线「能力正文无条件下放线程池」收尾工单（2026-10-02）

席：X4b（续 X4，X4 因平台排队阵亡，产物＝工作树里 +97 行的 pipeline 改动，但无锁、无工单）。
独占面：`domains/chat_reply/runtime/pipeline.py` + 新建 `tests/test_pipeline_offload_always.py`
+ 复跑 `tests/test_pipeline_hard_timeout.py` / `tests/test_render_pool_hygiene.py` + 本工单。
零 git 写、零进程动作、零外发、零配置改（`config.py`/`__init__.py` 未碰）。

## ① 现状核实（带 file:line）

X4 已落进工作树的改动（`git diff --stat` = **96 insertions / 1 deletion**，非虚报）：
- `pipeline.py:681` `is_native_async_callable`（协程函数 / `functools.partial` / `async def __call__` 三形都认，补了 3.14 起 `iscoroutinefunction` 不认 `__call__` 的那格）；
- `pipeline.py:696` `ensure_offloaded`（同步正文一律 `offload_capability` 下池；协程原样返回；幂等、绝不二次包装）；
- `pipeline.py:717` `_report_loop_thread_sync_call`（`handle` 落在事件循环线程时按 capability_id 记一次 WARNING，有界 128、fail-open）；
- `pipeline.py:1988`（`handle_async` 顶部）`capability = ensure_offloaded(capability)`——排在 `self._prepare` 之前；
- `pipeline.py:1796`（`handle` 顶部）插 `_report_loop_thread_sync_call(capability_id)`，行为面未动。

逐条核 X4 的关键承诺（**成立**）：
- **完成腿 `_complete` 留在循环上**：`handle_async` 默认分支 `pipeline.py:2006` 仍 `return self._complete(prepared, result)`（直呼，非下放）。`ensure_offloaded` 只作用在 `capability` 参数上，AST 锁断言全函数内 `ensure_offloaded` 仅出现一次且实参为 `capability`。A-22（`SendQueue.submit` 按 `current_task()` 记账）不被破坏。
- **超时抛法未动**：`CapabilityTimeout` 仍只在 `offload_capability.wrapped`（`pipeline.py:648`）抛，`handle_async` 的 `except → _internal_error → 出卡` 链路一字未改（`test_pipeline_hard_timeout.py` 复跑绿）。
- **幂等认领序 A-18 未动**：`ensure_offloaded` 排在 `_prepare` 之前只是给 callable 换装，claim（`pipeline.py:1247 self._claim_event`）仍在 `_prepare` 全部门禁之后（feature/runtime/role/policy/quiet/budget/rate-limit 之后）。

## ② 改法与理由

**判 X4 改法：正确、但对本波需求不完整。**
管线层已把「要不要下放」从名单决定改成「是不是协程」决定（`handle_async` 顶部无条件下放，函数体内不再引用 `OFFLOADED_CAPABILITY_IDS`）。但**名单真正失去执行路径决定权还差根汇口**：
- 根汇口 `__init__.py:2829 _run_capability_through_pipeline`（`async def`）在 `__init__.py:2864` 仍按 `offload_sync_capability` 二选一：
  - `True`（在名单内）→ `await pipeline.handle_async(..., offload_capability(capability), ...)`；
  - `False`（**名单外**）→ `pipeline.handle(...)`（`__init__.py:2873`，**同步、跑在事件循环线程上**）。
- `offload_sync_capability=capability_id in OFFLOADED_CAPABILITY_IDS`（`__init__.py:8255 / 9198 / 10627` 三处调用点传入）。
- `OFFLOADED_CAPABILITY_IDS`（`__init__.py:310-349`）**不含** `bot.recent` / `bot.queue` / `bot.logs` / `bot.setup.llm` / `bot.runtime` —— 正是 X4 注释里点名要救的低频阻塞命令。

⇒ **现网后果**：这些名单外命令仍走 `handle` 在循环线程同步跑完，正文里的 SQLite/文件/子进程仍会冻住整片会话；X4 只给它们加了一条 WARNING（`_report_loop_thread_sync_call`），**没改执行路径**。需求「能力正文无条件下放」在管线层成立、在系统层尚未成立。

**本席做了什么**：
1. 保留 X4 全部改动（无一处推翻——其内部设计正确且安全），仅补上它点名却缺失的判据锁 `tests/test_pipeline_offload_always.py`。
2. 锁只做**管线层**能诚实为真的判据；**不**假装名单已在系统层失去决定权（那要 `__init__.py` 收编，属别席，本席禁写）。

**收尾还需要的下一步（交主会话裁，本席无权动 `__init__.py`）**：把根汇口 `__init__.py:2864-2873` 的命令腿统一改走 `handle_async`（去掉 `offload_capability` 预包与同步 `handle` 分支；`ensure_offloaded` 幂等 ⇒ 预包本就可省）。落地后 `_report_loop_thread_sync_call` 在命令路径应恒不触发（保留作回归哨兵）。合法仍该用同步 `handle` 的只有**不在循环上**的调用者（`smoke.py`/`console_chat.py`/`route_demo.py`/`alerts.py`/`backend_unit.py`），不受影响。

## ③ 判据读数（实跑末行原样；卫生前缀：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 -p no:cacheprovider --basetemp=$TEMP/qoder-X4b/bt`）

- 新锁单跑：`tests/test_pipeline_offload_always.py` → **`10 passed in 2.31s`**
- 复跑两枚既有锁（工作树，含 X4 改动）：`test_pipeline_hard_timeout.py` + `test_render_pool_hygiene.py` → **`15 passed in 3.04s`**
- 三件同进程合跑（查跨用例线程/全局污染）：**`25 passed in 2.79s`**
- **注毒腿实跑（临时删 `handle_async:1988` 下放行，随即原样还原，`git diff --stat` 回到 96/1 且无残留标记）**：
  `2 failed, 8 passed in 8.80s` —— 红恰为 `test_handle_async_offloads_unconditionally_only_capability_never_complete`（`assert top_assign is not None`）与 `test_sync_command_body_runs_off_the_event_loop`（`assert obs["on_loop"] is False` → `True is False`）；其余 8 枚（协程不误伤 / 注毒翻证 / 执行器接线 / 单元分类 / 直呼腿可见面）仍绿 ⇒ 锁有牙且**精准定位**。

锁覆盖（双向自测）：正向=同步正文跑在非循环线程；反向不误伤=协程正文留在循环、绝不被多包一层（含 `ensure_offloaded` 幂等=只占一格许可）；注毒=合成直呼循环形态 ⇒ 同一观测翻到循环线程。**接线 AST 锁同认 `run_in_executor` 与 `to_thread` 两形**（在册教训：只认直呼形会把「在」读成「无人调用」）。

## ④ 净新增红 A/B（node ID 分桶，`git archive HEAD` 抽到 `$TEMP/qoder-X4b/head` 仓外副本同尺复跑）

- **A（HEAD 基线）**：`test_pipeline_offload_always.py` 不存在（0 node）；`test_pipeline_hard_timeout.py` + `test_render_pool_hygiene.py` = **`15 passed in 5.83s`**（全绿）。
- **B（工作树）**：新锁 10 绿 + 既有 15 绿（合跑 25 绿）。
- **净新增红 = ∅**；既有两文件的 15 枚 node A→B 无一由绿转红 ⇒ X4 改动 + 本席锁对既有超时/出卡/池卫生语义**零回归**。
- 只签「**本波域净新增红 0**」，**不签全绿**（HEAD 基线自身有既存红，#72★；且全仓 lint/typecheck/runtime-layout 属主会话在波收敛后统一跑）。
- 卫生：源码树无 `data/` 残留、无 `__pycache__`/`.pytest_cache` 落 `plugins/**` 或 `tests/`；本席 ruff 单文件 `All checks passed!`。

## ⑤ 未尽事项与原因

1. **根汇口未收编（本席禁写面）**：见 §② 末段。名单在系统层仍有执行路径决定权，须改 `__init__.py:2864-2873`。落地后建议同批改 `tests/test_three_entry_form_seam_liveness.py`（该件按 `OFFLOADED_CAPABILITY_IDS` 现算 offload 期望，收编后期望须改成「命令腿恒下放」），并由主会话把 `bot.recent/queue/logs/setup.llm/runtime` 的表现做成 e2e 观察项。
2. 未跑全仓 lint/typecheck/runtime-layout：波内多席 WIP 在飞（`addressing/reply_policy/shared_group/event_idempotency/queue/fx_data/tts/news_feeds/write_trace/...` 均 dirty），全仓门读数不属本席、也不该由本席触发（AGENTS 规则 7「代码补丁待审不自动部署」）。
3. 无 CONFIG-REQUEST：本波改动不需新键。

## 注入登记（AGENTS 规则 11）
本席未收到任何伪装指令形态的工具结果/文件正文；无执行面越界。工具结果若被伪造外壳的风险已按波次简报规避：关键读数先落 `$TEMP` 仓外文件再 `Read`/`cygpath` 核对，未采信任何未复核的回显。
