# 调度器族与定时推送 · 每日通讯摘要推送

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.scheduled-jobs · 每日通讯摘要推送

- 层级：一级 B07 → 二级 scheduled-jobs → 三级 `digest-push`
- 实现落点：`plugins/bot_unified_runtime/__init__.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

每日群通讯总结的主动推送：到点把白名单群当天的对话摘要，用一句守岸人引子 + 摘要正文，逐群发到群里。让群里的人不用问就能看到"今天都聊了些什么"。

## 怎么调用

真身 `__init__.py:_register_digest_push_scheduler`（消费点 `_push_daily_group_digests`）。注册一个 cron 任务（job id `bot_group_digest_push_daily`，时刻取 `bot_group_digest_push_time`），回调在 APScheduler 线程池跑。摘要由 `domains/chat_reply/character/shared_group.py:build_shared_group_context_provider` 产出（推送侧已注入 `_build_chat_llm_provider(config)` 作 llm_provider）。每群合成 `request_id=digest-push-<群>-<日期>`，正文=引子「今天群里的对话，我都悄悄记下了：」+ 摘要，投进发送队列。

## 开关与参数

- 装配门：`bot_group_digest_push_enabled`（缺省 True）∧ `bot_shared_group_context_enabled`。
- **目标只认白名单**：`bot_group_digest_list_mode` 必须是 `whitelist` 且 `bot_group_digest_whitelist` 非空，否则一律不推（绝不猜群）；`bot_group_digest_blacklist` 供排除。摘要口径键 `bot_group_digest_max_turns`/`_max_chars`/`_llm_enabled` 等。推送时刻 `bot_group_digest_push_time`（缺省 `21:30`）为**装配期快照**，改后需重启。
- 去重：`dedupe_key` 带当天日期（同群同天不重发）。

## 失败时看到什么

`list_mode` 非 whitelist 或名单为空 → 直接返回不推、零日志噪音；某群当日无可用摘要（provider 未 enabled 或摘要为空）→ 静默跳过该群。整轮失败只落一行 `group digest push failed` 日志，不影响主链路。

## 测试与验收

`tests/test_group_digest_push.py`（白名单门、按日去重、正文合成）、`tests/test_shared_group_digest_list.py`（名单过滤口径）。真机验收：白名单群在设定时刻收到一条摘要。
