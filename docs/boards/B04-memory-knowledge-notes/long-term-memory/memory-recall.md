# 长期记忆与反思 · 召回打分与冗余惩罚

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.long-term-memory · 召回打分与冗余惩罚

- 层级：一级 B04 → 二级 long-term-memory → 三级 `memory-recall`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character/memory_bus_v2.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/memory_store_v21.py`、`plugins/bot_unified_runtime/domains/chat_reply/capabilities/memory.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

长期记忆的召回打分面（WP6 记忆总线 v2）：显式事实与夜间归纳收进同一张表（`memory_entries_v21` + v2 列），按「证据累积」记账——同一槽位同极性是**确认**（计数+1、强度饱和上升），反极性是**矛盾**（双行并存、`supersedes` 留痕、双方降权，高确认方胜出）——「又说起」不等于「改了主意」。取用时按 `w_rel·relevance + w_str·strength + w_rec·recency − w_red·redundancy` 打分，同簇上限（MMR-lite）防止一件事占满预算，每次注入落一行审计、`/bot why` 可对用户解释。

## 怎么调用

- 主入口 `domains/chat_reply/character/memory_bus_v2.py::MemoryBus.recall(owner_id, session_id, query_text, …)` → `RecallOutcome`（`items: ScoredFact` + `dropped: DroppedFact` + 渲染文本）；构造口 `build_memory_bus`，装配开关判定读 `settings_from_config`。
- 注入管线适配：`MemoryBusProvider.retrieve` 满足 `plugins/bot_unified_runtime/domains/chat_reply/capabilities/memory.py` 的 MemoryProvider 协议（同名同参），对上游透明替换。
- 签名与槽位：`fact_signature`（槽位=类别前缀+残体+极性+词元集；写侧合并键窄、召回聚簇键宽一档）；相关性冗余用 `_token_set`（CJK 二元组+拉丁词）零依赖相似度，语义向量可用时补强（`bot_memory_semantic_recall_enabled`）。
- 作用域形状唯一来自中央件 `domains/core/session_keys.parse_session_key`（`derive_scope`）；跨会话召回非 global 行在 SQL 层结构性取不到。存储侧读候选经 `memory_store_v21.py::MemoryStoreV21.list_bus_candidates`。
- 解释面出口：`is_memory_why_command` + `render_memory_why`（根装配判据后一句 return）。

## 开关与参数

- 总闸 `bot_memory_bus_enabled`（缺省 **False**；关态不建新库不开新连接，走的还是旧召回面）。归纳落点 `bot_memory_reflected_write_target`（缺省 `legacy`，改 `bus` 才由反思写总线——见 reflection-loop 页）。
- 打分参数：`bot_memory_strength_k`（3.0）、半衰 `bot_memory_tau_stable/seasonal/episodic_days`（180/45/14）、`bot_memory_relevance_weights`（JSON 字符串；非法或不在位则按代码缺省并**点名一次**，不静默猜权重）、`bot_memory_per_category_max`（缺省 1）。逐键现值以 `config.py` 为准。

## 失败时看到什么

对模型侧是「少给/不给」，对用户侧是 `/bot why` 里一句人话。硬红线（件内自锁，逐条有测试）：`credentialed` 敏感级永不进召回；`requester != subject` 直接零结果；缺作用域只给 global（fail-closed，v1 的「忘了传=全会话」在此翻转）；episodic 类不参与画像召回（dropped 记 `episodic_not_profile`）；语义后端不可用时退回词元重叠、`semantic_available` 如实标注。显式来源永远压过归纳来源。

## 测试与验收

`tests/test_memory_bus_v2.py`（本件红线自锁所在）与 `tests/test_memory_bus_v2_migration.py`（存量迁移面，施工工具 `scripts/migrate_memory_bus_v2.py` 存在性已核；其幂等/守恒细节未经逐行复核，以该测试件断言为准）。真机：总线开启后说一件稳定事实、隔天再提，`/bot why` 看分数与来源。
