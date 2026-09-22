# 长期记忆与反思 · 抽取与提示词硬化

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.long-term-memory · 抽取与提示词硬化

- 层级：一级 B04 → 二级 long-term-memory → 三级 `memory-extract`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character/memory_bus_v2.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/memory_store_v21.py`、`plugins/bot_unified_runtime/domains/chat_reply/capabilities/memory.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

回复完成后的后台事实抽取：拿用户消息与 bot 回复问一次轻量 LLM，提取「值得长期记住的、关于用户本人的事实」（身份/偏好/约定/重要经历/稳定情感倾向），每行一条、去重后写记忆库。提示词硬规则（F16 实弹反馈后的口径）：不记寒暄与一次性话题、不记对 AI 工具/模型的评价吐槽、不记临时情绪玩笑抽象观点，没有就只输出「无」。任何失败都只影响这一环，不动主回复链路。

## 怎么调用

- `domains/chat_reply/character/memory_extract.py::extract_memory_texts(llm_provider, …)` 产事实文本，`store_extracted_memories(repository, subject_user_id=…, …)` 落库（fact id 由 `plugins/bot_unified_runtime/domains/chat_reply/capabilities/memory.py::build_fact_id` 派生）。
- 装配与触发在根 `__init__.py`：回复后台线程内调用上述两函数，按 per-sender 归属写入。
- 确定性闸门在入库前：`_is_trivial_fact`（工具谈资词表）与 `_is_reminder_noise` 双拦——命中一律不入库，「宁可漏记，不可记琐事」；单条长度有 `_MAX_FACT_CHARS` 上限，超出截断。
- 同文件还有提醒草稿抽取（`extract_reminder_drafts` / `store_extracted_reminders`），属提醒域自然语言入口，登记在 B07，本卡只留指针。
- 记忆总线 v2 启用时（见 memory-recall 页），沉淀面复用 `security/memory_sanitize` 的单一词表来源做清洗，本件不另建第二套词表。

## 开关与参数

- 总闸 `bot_memory_enabled`（缺省 **False**——不联网不写库）；`bot_memory_extract_enabled`（缺省 True，语义是「总闸开着就抽」，依赖前者）。
- 成本与韧性键：`bot_memory_extract_timeout_seconds`（缺省 15）、`bot_memory_extract_max_tokens`（缺省 200）、`bot_memory_extract_error_cooldown_seconds`（缺省 300，出错后冷却不再逐消息重试）；库路径 `bot_memory_db_path`、召回预算 `bot_memory_max_items` / `bot_memory_max_chars`。逐键现值以 `config.py` 为准。

## 失败时看到什么

用户无感：抽取超时、LLM 报错、输出不合形态（非「无」但解析不出条目）都只落日志并进入冷却窗口；主回复早已发出，不存在「抽取失败导致不回话」。写入失败不阻塞（fail-open 于链路、fail-closed 于脏数据——琐事闸拦下的一律不入库）。

## 测试与验收

抽取与清洗相关用例见 `tests/test_memory_service_v21.py` 与 `tests/test_persona_prompt_and_memory.py`（离线 mock，零网络）。真机：开启总闸后正常聊几句，用 `/bot why` 或记忆清单确认落库——本件未逐条核对验收手册编号，未确认项以 `docs/acceptance-manual.md` 现文为准。
