# 日常助理与收件箱 · 收件箱速记

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.daily-assist · 收件箱速记

- 层级：一级 B07 → 二级 daily-assist → 三级 `daily-assist`
- 路由席位：`DAILY_ASSIST`（matcher `daily_assist`，command=True）
- 判定优先级：42
- 能力 id：`bot.daily_assist`
- 实现落点：`plugins/bot_unified_runtime/domains/assistant/daily`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

收件箱速记命令（`RouteKind.DAILY_ASSIST`，判定优先级 42，`capability_id=bot.daily_assist`）。发「收件箱 内容」就把一件事记进纯文本收件箱的待处理段（带内容=记一笔，不带内容=翻看攒着的）；记下的事在早报时由日常助理一并整理。生效条件：路由命中 `is_daily_assist_command`。

## 怎么调用

- 路由判定与能力真身：`domains/assistant/daily/capabilities/daily_assist.py`（`is_daily_assist_command`、`build_daily_assist_capability`）。触发正则前缀锚定 + 右边界防胶合，别名含 `inbox`/`shoujianxiang`。
- 它依赖的中央件：`domains/assistant/daily/store/daily_assist.py` 的 `append_inbox_line`/`read_pending_inbox`/`inbox_path`/`pick_variant`（文案轮换）。存储根目录由 `bot_daily_assist_dir` 经 runtime_paths 解析。

## 开关与参数

- `bot_daily_assist_enabled`（缺省 True）：总闸。`bot_daily_assist_dir`（缺省 `data/daily_assist`，进 path_fields 重映射，生产 `.env` 指向用户 Assistant 目录）。
- 速记命令本身不区分权限（谁的会话谁记），投递名单 `bot_daily_assist_push_user_ids` 与推送时刻 `bot_daily_assist_morning_time`/`_evening_time`/`_meal_times` 归调度器（见 scheduled-jobs 与二级页）；名单空则只记不推。配置键逐键以 `docs/config-catalog-full.md` 为准。

## 失败时看到什么

带内容 → 记一行并回"收好了…早报一并理给你"（多句轮换）；不带内容 → 回清单（空则"收件箱空着呢"）或用法。正文超 2000 字截断。落盘失败（OSError）读回空串，不谎报已记。回执 `SILENT_AUDIT` 落审计。

## 测试与验收

`tests/test_daily_assist.py`（记/看/截断/文案轮换/归档），真机验收：发一句「收件箱 买牛奶」后早报能读到该条。
