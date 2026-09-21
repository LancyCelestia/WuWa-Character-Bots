# 快讯与历史上的今天 · 历史上的今天

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.news · 历史上的今天

- 层级：一级 B05 → 二级 news → 三级 `today-history`
- 路由席位：`TODAY_HISTORY`（matcher `today_history`，command=True）
- 判定优先级：41
- 能力 id：`bot.today_history`
- 实现落点：`plugins/bot_unified_runtime/domains/subscribe/feeds`
- 帮助主题：历史上的今天
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`历史上的今天` 出当天条目；`历史上的今天 设置 8:00` / `状态` / `取消` 让**本会话**（私聊或某个群）订阅一个每日推送时点。渲染后端可用时合成 Mica 信息卡，文本作 caption 与兜底，文字版与卡片版内容一致。

## 怎么调用

- 席位 `TODAY_HISTORY`、能力 id `bot.today_history`；闭包 `domains/subscribe/capabilities/today_history.py:build_today_history_capability(config, *, provider, push_file, on_subscription_change)`，谓词 `is_today_history_command`。
- 数据真身：`domains/subscribe/feeds/today_history.py` —— `TodayHistoryProvider`（每日一次的文件缓存 + 进程内锁）、`fetch_today_history(*, proxy, timeout)`（失败抛 `ParseHttpError` 由上层收敛）、`_parse_history_json`、`format_history_text`。
- 定时面：根装配 `_register_today_history_scheduler`（`plugins/bot_unified_runtime/__init__.py`）在启动/bot 连接时按推送表注册调度任务；投递按会话键，属 B07 调度与 B08 出站的交界，本入口只负责"表 + 内容"。
- 卡片：`build_history_card_content(body, month_day=...)` 纯构造（无 IO，能力层与测试共用）；目录名消毒 `_card_dir_token`，`_prune_card_dirs(keep=…)` 按 mtime 淘汰旧卡目录。

## 开关与参数

- `bot_today_history_enabled`（缺省 True）。
- `bot_today_history_push_file`（缺省 `data/today_history_push.json`）、`bot_today_history_cache_file`（缺省 `data/today_history_cache.json`）——两者都经 `scripts/runtime_paths.py` 重映射进 Runtime 数据根，属 `path_fields`，**不进源码树、不进 git**。
- 定时时点是会话态（按 `f_<用户号>` / `g_<群号>` 分键），不是配置键；改推送框架的时间窗口径看 B07。

## 失败时看到什么

- 上游不可达或结构变：回一句取数失败人话，**不用模型记忆补历史事件**。
- 推送表损坏/不可读：`_load_push_table_checked` 返回"不可改写"，调用方**拒绝写入**（宁可拒绝设置也不静默覆盖用户既有订阅）；保存失败明确回错，不吞。
- 渲染失败：出纯文字版，内容与卡片版逐字一致。
- 到点没推送：先查调度注册（装配期快照，改键要重启）与该会话键是否在表里，再怀疑内容层。

## 测试与验收

离线：`tests/test_today_history_robustness.py`（缓存与锁、坏 JSON、拒绝改写、卡片构造确定性、目录 prune）、`tests/test_multi_calendar.py`（同批卡片的多历法行）。
真机：`历史上的今天`；`历史上的今天 设置 8:00` → `状态` → 次日到点收到一条 → `取消` 后不再收到；在 A 群设置后在 B 群查询应看到"本群未设置"。
