# 调度器族与定时推送 · 知识库同步

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.scheduled-jobs · 知识库同步

- 层级：一级 B07 → 二级 scheduled-jobs → 三级 `kb-wiki-sync-scheduler`
- 实现落点：`plugins/bot_unified_runtime/__init__.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

Crawl Wiki 知识库的每日增量同步：把源 wiki 目录的变更同步进嵌入库、重建 ANN/FTS 索引，让检索侧及时看到新内容。日常无变更时零开销。检索能力本身归 B05.knowledge，本卡只讲这条定时同步腿。

## 怎么调用

真身 `__init__.py:_register_kb_wiki_sync_scheduler`。注册一个 cron 任务（job id `kb_wiki_sync_daily`，时刻取 `bot_kb_wiki_sync_hour`/`_minute`，排在每日导出之后），若 `bot_kb_wiki_sync_on_startup`（缺省 True）再挂一个启动后延时补偿的 date 任务 `kb_wiki_sync_startup`（延时长以该件常量为准；错过的夜间增量补跑一次，首轮未灌库也只是空 updates、不触发全量）。回调 `run_kb_sync_task(config, full=False, store=_get_shared_store(config))` 在 job 线程串行执行同步→嵌入→索引重建，与共享 store 协作（同步完成后进程内检索即时可见）。

## 开关与参数

- 装配门：`bot_kb_wiki_enabled`（缺省 False）且 `bot_kb_wiki_root` 非空才注册。
- `bot_kb_wiki_sync_hour`（缺省 23）、`bot_kb_wiki_sync_minute`（缺省 40）、`bot_kb_wiki_sync_on_startup`（缺省 True）；库路径 `bot_kb_wiki_db_path`。全量重建（`kb_drift`）不在本任务里自动做，是用户裁定的独立动作。

## 失败时看到什么

同步成功打 `kb_wiki_sync done: <public_message>` info，失败按 `error_kind` 打 warning；抛异常只 `kb_wiki_sync failed: <类型>` 一行、不影响主链路。停机竞态专门兜住 `asyncio.CancelledError`（早停钩子先 cancel job 时安静退出，绝不向停机日志刷栈）。

## 测试与验收

`tests/test_kb_wiki_sync.py`（增量同步）、`tests/test_kb_wiki_metadata_sync.py`、`tests/test_kb_wiki_retriever_wiring.py`。真机验收：改一条源 wiki，下一同步周期检索命中更新。
