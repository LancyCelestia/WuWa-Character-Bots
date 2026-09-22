# 知识库与检索 · 分块与索引状态

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.knowledge · 分块与索引状态

- 层级：一级 B04 → 二级 knowledge → 三级 `kb-indexing`
- 实现落点：`plugins/bot_unified_runtime/domains/core/search`、`plugins/bot_unified_runtime/domains/chat_reply/character/teaching_service.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把清单里的 Markdown 知识文件变成可检索的东西：按段落贪心切块入库、把未向量化的块补嵌、给关键词通道建 FTS5 trigram 索引、给向量通道建 faiss HNSW 索引。产出是一份 SQLite 库（`knowledge_chunks` 表 + 向量 + `knowledge_meta` 状态）与磁盘上的 ANN 索引文件，检索时向量与关键词两路结果做 RRF 融合。

生效条件：`domains/chat_reply/character/vector_knowledge.py::build_vector_knowledge_provider` 要求嵌入总开关打开且远端或本地嵌入通道至少一路可用；不满足时返回诚实的"不可用 provider"（恒返回空结果），不抛异常、不冒充有知识。

## 怎么调用

真身是 `domains/chat_reply/character/vector_knowledge.py::SqliteVectorKnowledgeStore`（本卡片主题不在上方生成头的落点清单里，那两处管联网检索与教学注入，切块/索引的真身按本段为准）。公开入口：`sync_chunks(files)` 按文件清单同步块、`sync_documents(docs)` 供非文件写入方落库、`embed_pending(files)` 补嵌（返回本次成功数与处理前待嵌数，可断点续跑）、`ensure_fts_index(force=...)` 幂等建关键词索引、`build_ann_index()` / `load_ann_index()` 建与载向量索引、`stats()` 给出总块数与已向量化块数、`certify_expected_vector_count()` 落完备性计数戳。消费侧只走 `retrieve()`，装配在 `plugins/bot_unified_runtime/runtime/service_wiring.py`（受 `bot_knowledge_service_enabled` 等服务装配门门控）。

## 开关与参数

`bot_knowledge_files`（清单，`list[str]`）、`bot_knowledge_chunk_chars`（缺省 900）、`bot_knowledge_max_chunks`（人格上下文注入侧每文件块数上限，`plugins/bot_unified_runtime/domains/chat_reply/character/providers.py` 读）、`bot_knowledge_top_k`（检索槽位预算，缺省 4）、`bot_knowledge_db_path`（进路径重映射）。嵌入侧的模型、端点、维度、本地通道由 `bot_embedding_*` 决定；换模型或端点会让指纹变化并触发"清空旧向量重嵌"。这些都是装配期读取，改 `.env` 要重启才生效（索引代际本身除外：另一进程原子换入新索引后，本进程下一次检索即感知，不需重启）。

## 失败时看到什么

- 嵌入失败：补嵌中途停止、保留已完成的行，下次续跑；检索侧向量通道不可用就退回关键词与降级路径，对话不中断（`retrieve` 外层异常按无结果处理）。
- 索引不可信就不用：`load_ann_index()` 在签名不符、`.index` 与 `.order.json` 不同代、短装或无计数戳时一律返回 False，回落暴力扫描（慢，但绝不返回错位的邻居）。
- 并发重建不互踩：整场重建持同目录 OS 文件锁（`_AnnBuildGate`，最长退避后如实返回 `built=False, reason=locked_by_other_process`），绝不覆写别人正在写的文件。
- 清单变小不等于清空：`sync_chunks` 只按台账精确删除"本库此前同步过且已不在清单"的源，清单外别的写入方刚落库的块不会被带走（空清单护住全库）。
- 请求路径绝不做分钟级内联重建（人格库与百科库都关掉了 FTS 自动重建）：重建归维护任务。

维护入口：`domains/ops/smoke/smoke.py::run_knowledge_sync`（以 `knowledge-sync` 任务跑同步 → 补嵌 → 重建全链），重启预检 `scripts/pre_restart_check.py` 在索引不完备时会点名让你先跑它。

## 测试与验收

`tests/test_knowledge_empty_manifest_wipe_guard.py`（空/小清单不得清库）、`tests/test_knowledge_mtime_cache.py`（文件签名缓存）、`tests/test_ann_completeness_gate.py`（短装拒用）、`tests/test_ann_atomic_publish.py`（原子换入与不同代拒载）、`tests/test_ann_certify_prewarm.py`（计数戳与预热）、`tests/test_embed_adaptive_batch.py`、`tests/test_embed_cold_start_guard.py`（嵌入批大小与冷启动护栏）、`tests/test_v21_knowledge_service.py`（服务装配面）。

### 现行缺陷

块数、已向量化数这类实况一律读 `stats()` 与机器册，本文不写。ANN 重建在请求线程外由维护任务承担，索引落后于语料属可预期状态（表现为回退暴力扫描或向量通道缺席，而不是报错）。
