# 调度器族与定时推送 · 夜间反思窗口

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.scheduled-jobs · 夜间反思窗口

- 层级：一级 B07 → 二级 scheduled-jobs → 三级 `reflection-scheduler`
- 实现落点：`plugins/bot_unified_runtime/__init__.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

夜间反思回路：每天把当天的对话轮次（conversation_turns）归纳成用户事实与会话摘要，喂回记忆体系与怪癖演化。这是"睡前整理今天聊过什么"的自动任务，不面向用户直接调用。

## 怎么调用

真身 `__init__.py:_register_reflection_scheduler`。注册一个 cron 任务（job id `bot_reflection_daily`，缺省 04:30，`misfire_grace_time=3600`、`max_instances=1`、`coalesce=True`），回调 `run_nightly_reflection`（真身 `domains/chat_reply/character/reflection.py`）跑在 APScheduler 线程池、不阻塞事件循环。若 `bot_reflection_llm_enabled` 开着，会带 `LLMSummarizer(build_model_router(config))` 做 LLM 归纳，否则走规则路径。无轮次库/无轮次时返回 skipped 静默跳过。

**启动补偿**：只挂 04:30 有个真实漏洞——进程在那一刻不在运行（重启/维护/崩溃）当天的反思就永久丢失、要等一整天。故启动时若"今天还没有 digest"（`_should_catch_up_reflection` 读 reflection 库判定），立刻用 date job（`bot_reflection_catch_up`）补跑一次；判断失败按不补处理，避免重复跑。

## 开关与参数

- 装配门：`bot_history_enabled ∧ bot_reflection_enabled`（后者缺省 True）才注册。
- `bot_reflection_hour`（缺省 4）、`bot_reflection_minute`（缺省 30）、`bot_reflection_db_path`（库路径的缺省值以 `config.py` 该字段为准）、`bot_reflection_max_sessions`（缺省 50）、`bot_reflection_llm_enabled`（缺省 False，开则每轮起 LLM，有成本）。怪癖提案相关键见反思域。

## 失败时看到什么

job 抛异常只落一行 `reflection failed: <异常类型>` 日志，主链路无感；补偿任务挂不上也不影响 cron 本身。反思是"锦上添花"的记忆加工，失败不会丢原始对话历史。

## 测试与验收

`tests/test_reflection.py`（归纳/去噪/会话归属），启动补偿判定由该族覆盖。真机验收：重启后看运行日志 `reflection: {...}` 行是否按日出现。
