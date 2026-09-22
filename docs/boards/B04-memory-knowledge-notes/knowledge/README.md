# B04.knowledge 知识库与检索

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.knowledge 知识库与检索

> 知识源、分块、索引与配额；来源可信度约束。

- 归属板块：[B04](../README.md)
- 实现落点：`plugins/bot_unified_runtime/domains/core/search`、`plugins/bot_unified_runtime/domains/chat_reply/character/teaching_service.py`
- 帮助主题：搜索
- 配置键前缀：`bot_knowledge_`, `bot_search_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [分块与索引状态](kb-indexing.md) | — | — | — | — |
| [来源配额与检索预算](kb-quota.md) | — | — | — | — |
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

她的世界观、设定、玩家资料、你教过她的知识，都要在回答时被"翻到"，但语料体量远塞不进一次请求。这一块管的就是**把资料切成能查的小块、给每块配检索卡、按问题把最相关的几块捞回来**，同时保证三件事：来源可追、检索有预算、捞不到时诚实说不知道而不是硬凑。

现役有**三套互不共用的语料库**，各自的写入者与信任级别不同，混表会出事（人格库的同步以"文件清单为全集"删除旧块，若与文档级 wiki 库共表，一次 wiki 同步就能把人格块洗掉——所以刻意分库）：

| 语料 | 真身与库 | 写入方式 | 现役开关 |
|---|---|---|---|
| 人格知识库 | `domains/chat_reply/character/vector_knowledge.py` → 库路径以 `config.py` 的知识库路径键为准 | `sync_chunks`，以 `bot_knowledge_files` 清单为全集 | 向量通道要 `bot_embedding_enabled` |
| Crawl Wiki 外部知识库 | `domains/location/knowledge/kb_wiki.py` → 库路径以 `config.py` 的对应路径键为准 | `sync_documents`，hash 幂等增量 + 每日定时 | `bot_kb_wiki_enabled` 缺省 False |
| 教导知识库（用户提议→管理员审核） | `domains/chat_reply/character/teaching_service.py` → 库路径以 `config.py` 的对应路径键为准 | 审核制，撤改即时失效 | `bot_teaching_enabled` True，但受 V2.1 装配主门约束，**生产零接线** |

检索底座 `domains/core/search/`（统一多平台搜索协议与网络 provider）也在本功能名下登记，但它的真实网络出口与 `/search/*` 路由属 B05 外部数据面，这里只写它作为"知识来源约束"的那一半。

## 处理流程

```mermaid
flowchart LR
  files[语料文件/审核通过的教导条目] --> chunk[分块 chunk_chars]
  chunk --> emb[嵌入链 本地 Ollama 优先 失败回退远程]
  emb --> ann[ANN 索引 + FTS + 原文块]
  q[当轮查询] --> ret[关键词通道 + 向量通道 + RRF 融合]
  ann --> ret
  ret --> quota[来源族配额与人格保留位]
  quota --> ctx[B03 persona 注入知识分区]
  ret -->|服务故障| honest[不注入静态兜底块，点名降级]
```

装配口：`build_vector_knowledge_provider`（嵌入未配齐 ⇒ 返回不可用态，调用方退回关键词检索）、`build_keyword_knowledge_provider`。消费点唯一：`domains/chat_reply/character/providers.py` 构建 `ContextBundle.knowledge_results`。

## 边界与降级

- **向量通道默认不参与**：`bot_embedding_enabled` 缺省 False ⇒ 走 `KeywordKnowledgeRetriever`；即使开了，本地 Ollama 与远程任一未配也直接判不可用，不猜。numpy / faiss 都是可选依赖，缺失时分别退回纯 Python 余弦与暴力检索（慢但正确）。
- **fast 模式的限时策略**：`bot_chat_fast_mode` 缺省 True，fast 态给嵌入一个更短的超时（`bot_chat_fast_embedding_timeout_seconds`，缺省值以 `config.py` 该字段为准）；`bot_chat_fast_disable_vector_knowledge` 缺省 False（即 fast 模式**不**禁向量，只压超时）。
- **故障不伪装成"没查到"**：检索服务抛异常时 `retrieval_failed=True`，此时**不**再注入静态文件前几块——静态注入既掩盖故障又污染 prompt；只有"正常无命中"才保留静态兜底。降级只记一行 warning。
- **索引覆写要拿跨进程闸**：ANN 重建是分钟级，`_AnnBuildGate` 用同目录 OS 文件锁（非阻塞退避，拿不到就让路并如实报告），不用 SQLite 写事务——后者会把运行中 bot 的知识库写入全憋死。写库与换索引走"临时位构建→校验→原子替换"，半成品不切换。
- **只读边界**：教导库与 wiki 库对 bot 都是只读消费，写入分别经审核与外部导出流程；知识库检索结构性不可达权限/路由面，只能作为"背景知识供理解"，禁止复述。
- **管理员检索面**：`/bot search` 是 admin_only 帮助主题（`capability="/bot search"`），不占 `RouteKind` 席位。

## 测试与验收

- `tests/test_knowledge_source_quota.py`：来源族配额与人格保留位（含"纯百科查询零退化"的语料级锁）。
- `tests/test_knowledge_empty_manifest_wipe_guard.py`：空清单不得洗库。
- `tests/test_knowledge_mtime_cache.py`：文件签名缓存与增量判定。
- `tests/test_kb_wiki_sync.py`、`tests/test_kb_wiki_metadata_sync.py`、`tests/test_kb_wiki_retriever_wiring.py`、`tests/test_kb_topic_name_contract.py`、`tests/test_kb_metadata_probe_*`：wiki 增量同步、元数据探针与 topic 名契约。
- `tests/test_v21_knowledge_service.py`、`tests/test_v21_teaching_service.py`、`tests/test_v21r2_stall_kbsync.py`：V2.1 三通道检索与原子重建、教导服务、同步停摆面。
- 真机：重启前体检的 `kb_drift` 项（只读）；`/bot status` 的人格与知识文件缺失数行。

## 现行缺陷

1. **索引与原文数量对不上（待用户裁决，不得宣称已重建）**：`scripts/pre_restart_check.py` 的 `kb_drift` 项实测到"目录卡远多于原文块"（两值以体检实跑输出为准，当时值已过期），成因是目录只加不减 + 换过嵌入模型 + 删除不同步。后果是检索质量与耗时打折，日常聊天不受致命影响。**两条路线（重建 vs 不建）都在 `docs/design/v21r4-kb-drift-explainer.md` 里，选择权在用户**；本波只如实登记，不执行任何生产库重建。数字属会漂移量，以体检实跑输出为准。
2. **V2.1 的知识/教导/世界书服务在生产路径上是零接线**：`bot_v21_service_wiring_enabled` 缺省 False，`bot_knowledge_service_enabled`、`bot_worldbook_enabled` 同缺省 False，`bot_teaching_enabled` 虽为 True 也被主门挡住 ⇒ 「审核过的教导条目会进 prompt」目前只是**代码与离线测试事实**，线上不成立。`docs/db-owners.md` 对这两个库的标注也是"待生成/零生产接线"，别读成已生效。
3. **人格库的"全集删除"语义是双刃**（P1 风险，非现行故障）：`sync_chunks` 以 `bot_knowledge_files` 为全集清理缺席文件；清单配错（路径写错、`.env` 少一项）就会静默删掉对应语料块。已有"空清单不洗库"的守卫，但**非空而缺项**的情形只靠人审配置。
4. **统一搜索服务的活体验收仍 blocked**：`domains/core/search/search_service.py` 自述"真实网络验收与 REST 路由（/search/*）不在本席范围（live=blocked 登记）"，provider 一律注入、自身零网络 ⇒ 预算/并发/缓存参数目前只有离线证据。
