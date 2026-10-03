# 知识库与检索 · 来源配额与检索预算

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.knowledge · 来源配额与检索预算

- 层级：一级 B04 → 二级 knowledge → 三级 `kb-quota`
- 实现落点：`plugins/bot_unified_runtime/domains/core/search`、`plugins/bot_unified_runtime/domains/chat_reply/character/teaching_service.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/question_intent.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

管两件事：一次检索允许占多少槽位（预算），以及这些槽位按来源怎么分（配额）。它不改变候选的生成与排序，只在融合排序之后做**选择层**约束。

动机是真实的生产事故：人格库里百科转储源的块数远多于人格本体，向量通道补嵌完成之后，每一轮的槽位都可能被同一个百科源洗满，于是"问她自己的设定"召不回设定。修法是归族 + 族上限 + 人格保留位，而不是把百科源踢出库。

## 怎么调用

真身是 `domains/chat_reply/character/vector_knowledge.py` 的配额段（不在上方生成头落点清单里——那两处管联网检索与教学注入；配额与预算的真身按本段为准）：`_source_family(source_id)` 把来源归族（`th-数字` 并为 on-this-day 族、以人格本体文件名前缀起头的并为 persona 族、其余每源自成一族），`_quota_family_cap(limit)` 与 `_quota_persona_reserved(limit)` 由槽位预算派生族上限与人格保留位，`_select_within_source_quota(...)` 在融合序上做三段式选择并返回仍按融合序排列的选中结果。槽位预算即 `bot_knowledge_top_k`；候选生成侧还有向量候选地板与关键词候选倍数两个模块常量，未命中判定见同文件的余弦阈值常量。

族上限是**软顶**：非人格族在 cap 内填不满槽位时按融合序溢出回填，保证纯百科查询零退化。唯一的硬顶族是 on-this-day——它由多个同语料的独立 source_id 并成，早期实测证明"各自限量"合并后仍能占满全部槽位，所以对它即使溢出也不越 cap。人格保留位只在候选池里确实存在人格块时生效，且补位只提升有相关性证据的块（关键词/词条通道命中，或向量余弦过本库低置信阈值），避免大块语料里偶然零相关的人格块被硬塞进每一次查询。

## 开关与参数

源族配额不是配置键，而是**构造参数**：`SqliteVectorKnowledgeStore(source_quota_enabled=...)` 缺省 False，只有人格库的 provider 构造点显式打开，其余库（百科/维基等）保持原行为。所以"配额生效了吗"取决于查的是哪个库，不看 `.env`。联网检索侧另有一套来源约束：`bot_search_acg_max_per_source`（每源条数上限）与 `bot_search_acg_timeout_seconds`，总开关 `bot_search_acg_enabled` 缺省 False，即休眠态。教学知识注入面另有自己的字符预算裁剪（`domains/chat_reply/character/teaching_service.py`，按预算逐行累加、超预算即停），与检索槽位预算是两回事。

## 失败时看到什么

配额层本身不抛业务异常：候选池里没有人格块时保留位自然不生效（返回少于预期的槽位），族内候选稀少时走溢出回填。真正会看到的是结果构成变化——某一族不再独占全部槽位。若配额逻辑被改坏，表现是"人格向问题又召不回设定"，由语料级锁点名（见下节）。

## 测试与验收

`tests/test_knowledge_source_quota.py`（族归并、软顶溢出回填、人格保留位与只提升有证据块、`th-*` 硬顶族的语料级锁）。真机侧无独立条目：以人格向问题能召回到人格本体块为准，属 `docs/acceptance-manual.md` 的人格上下文验收面。

### 现行缺陷

族上限与保留位都是**由 `top_k` 派生的公式**，不是可调参数表；要按来源精细调权需要另立配置面，目前未做。配额只作用于人格库构造路径，其他共库写入方不受约束——这是刻意保留的现状，不是漏配。
