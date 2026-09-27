# 长期记忆与反思 · 夜间反思回路

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.long-term-memory · 夜间反思回路

- 层级：一级 B04 → 二级 long-term-memory → 三级 `reflection-loop`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character/memory_bus_v2.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/memory_store_v21.py`、`plugins/bot_unified_runtime/domains/chat_reply/capabilities/memory.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

夜间反思回路（episodic memory consolidation，借鉴 Stanford generative_agents 思想、零代码复制）：周期性把近一天的原始对话轮次沉淀为两类更高层记忆——`reflection_digests`（每会话当天两句话摘要；同日重跑整行替换，并作废引用旧摘要的事实）与 `reflection_facts`（关于用户本人的稳定事实，类别+置信度；同 sender 归一化文本相同则 keep-newest，旧行置 superseded）。数据来源是 `domains/chat_reply/character/history.py` 的 `conversation_turns` 表，本件不改写 history。

## 怎么调用

- 任务入口 `domains/chat_reply/character/reflection.py::run_nightly_reflection(config, summarizer=None)`；按日取轮次 `gather_turns_by_date(history_db, scope_date)`（scope_date 取 UTC 日期，与 `created_at` 的 UTC isoformat 口径一致）。
- 归纳器两档：`HeuristicSummarizer`（零 LLM、确定性正则，缺省）与 `LLMSummarizer`（注入 OpenAI 兼容客户端，失败或未注入回退启发式）；`bot_reflection_llm_enabled` 决定装配哪档。
- 落库 `ReflectionStore`（库路径经 `providers.build_runtime_data_path` 解析到 Runtime 数据根——DATAFIX 根治过 CWD 相对路径写进源码树的事故）；文本归一单一来源：反思侧 `_normalize_fact_text` 从 `memory_bus_v2.canonical_fact_text` 派生，禁第二副本。
- 调度装配在根 `__init__.py::_register_reflection_scheduler`：每日 `bot_reflection_hour:minute`（时刻两键以 `config.py` 为准）定时任务 `bot_reflection_daily`，漏班有补跑判据 `_should_catch_up_reflection`。
- 旁路产出：`quirk_proposal_drafts` / `build_reflection_quirk_proposer` 把归纳事实投给怪癖审核面（propose→管理员 approve，见 B03）。
- 总线接通后归纳器降级为**写侧归纳器**：不再拥有存储，只在 `settings.enabled ∧ reflected_write_target=bus` 时把候选事实投进 `MemoryBus.absorb`（关态不建新库不开新连接）。

## 开关与参数

`bot_reflection_enabled`（缺省 True）、`bot_reflection_hour` / `bot_reflection_minute`、`bot_reflection_db_path`（库路径的缺省值以 `config.py` 该字段为准，进 path_fields 重映射）、`bot_reflection_max_sessions`、`bot_reflection_llm_enabled`（缺省 **False**，即缺省零 LLM 成本）、`bot_reflection_quirks_propose_enabled` 与 `bot_reflection_quirks_min_confidence`。依赖 `bot_history_enabled` 且历史库文件存在，否则整轮跳过。逐键现值以 `config.py` 为准。

## 失败时看到什么

对外零输出：所有跳过与失败都以 dict 返回原因、绝不上抛——调用方只记一行日志，主链路无感。可诊断的 skip 原因（件内实核）：`reflection_disabled` / `history_disabled` / `history_db_missing` / `no_turns`；归纳异常记 `reflection failed: <异常类型>`。落库约定与好感度 DynamicAffinityStore 一致：WAL 先于 DML、单连接 + threading.Lock、check_same_thread=False（件内自述，属结构约定非行为承诺）。

## 测试与验收

`tests/test_reflection.py`（离线：归纳、supersede、skip 契约）。真机：到点看日志里 `reflection: {…}` 的 dict 原因行；LLM 档需先开 `bot_reflection_llm_enabled` 再重启。
