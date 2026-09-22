# 调度器族与定时推送 · 历史上的今天推送

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.scheduled-jobs · 历史上的今天推送

- 层级：一级 B07 → 二级 scheduled-jobs → 三级 `today-history-scheduler`
- 实现落点：`plugins/bot_unified_runtime/__init__.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

「历史上的今天」每日推送：按订阅表给每个订阅目标各挂一个 cron，到点把当天历史事件推给对应群/私聊。查询能力本身（交互出卡）在 B05.news，本卡只管"到点主动推"这条腿。

## 怎么调用

真身 `__init__.py:_register_today_history_scheduler`。它构造两个能力闭包共享同一 provider/推送表：定时推送用 `render_backend=None`（评审 C1 产品裁定：推送运行在调度线程、保持纯文字，不依赖 Playwright），交互 matcher 用注入后端的 `interactive_capability`（分流互不影响）。按 `_load_push_table` 逐条 `scheduler.add_job`（job id `history_push_<目标键>`，时刻取订阅项、缺省 8:00），并另挂每日 00:30 的缓存强制刷新任务 `history_cache_refresh`。目标键 `g_` 前缀走群、否则走私聊；订阅变更时 `_resync_jobs` 先清 `history_push_*` 再重挂。

## 开关与参数

- 装配门：`bot_today_history_enabled`（缺省 True）；apscheduler 缺失等注册异常被 try 吞掉，命令仍走无推送的直查路径。
- 推送表 `bot_today_history_push_file`（缺省路径以 `config.py` 该字段为准）、缓存 `bot_today_history_cache_file`；代理沿用 `bot_download_proxy`。
- cron 用系统本地时区（台账 #6）；订阅表的 hour/minute 落库即装配期快照，改动经订阅重挂生效。

## 失败时看到什么

无在线 bot 时该目标本轮直接返回（不发不报错）；`_resync_jobs` 整体失败静默 return，不影响主链路。诚实边界：某日无历史事件或数据源缺时由 B05 的 today_history 能力如实呈现，推送侧同样不编造。

## 测试与验收

`tests/test_today_history_robustness.py`（健壮性/无源），订阅重挂与推送门控由装配/能力测试覆盖。真机验收：订阅目标在设定时刻收到一条纯文字历史上的今天。
