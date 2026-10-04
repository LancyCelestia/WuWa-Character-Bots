# 调度器族与定时推送 · 落盘点 TTL 清扫调度

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.scheduled-jobs · 落盘点 TTL 清扫调度

- 层级：一级 B07 → 二级 scheduled-jobs → 三级 `file-sweep-scheduler`
- 实现落点：`plugins/bot_unified_runtime/__init__.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

落盘点寿命清扫（需求16 收口）：每天一次扫下载登记根（`bot_download_dir` 下的 `incoming/`），把 mtime 超过 TTL 的普通文件删掉，防文件落盘无限堆积。只删「登记根内、普通文件、非禁触名册、超龄」四条件齐备的件，不递归子目录；TTL≤0＝整面关闭（一枚不删，绝不把 0 解释成「立即全删」——清扫口错配的方向必须是「不删」）。

## 怎么调用

删除真身 `domains/files/sender/restricted_runner.py::sweep_expired_files(roots, *, ttl_days, now=None, max_deletions=...) -> list[SweepOutcome]`；配置现算口 `sweep_ttl_days_from_config(config)`（真身件不读 config，值由装配层传入）。注册在 `__init__.py::_register_reminder_scheduler` 体内的 `_file_sweep_job`：cron `hour=4, minute=50`（当时值，以装配处 add_job 为准）、job id `bot_file_sweep_tick`、`max_instances=1`/`coalesce=True`/`misfire_grace_time=600`、`replace_existing=True`；同步删放下 `asyncio.to_thread`（绝不上事件循环）。⚠ 注册门搭的是提醒调度器：`bot_reminder_enabled`（缺省 True）为 False 时本清扫任务同样不注册。

## 开关与参数

- `bot_files_incoming_ttl_days`：float，缺省 7.0 天；显式 ≤0＝关闭；键缺席/不可解析回落缺省（「每次调用现取」回避装配期快照坑）。
- `bot_download_dir`（缺省 `data/downloads`）：登记根＝该目录下的 `incoming/`。
- 删除上限保险丝＝真身模块常量 `DEFAULT_SWEEP_MAX_DELETIONS`（当时值 200）：候选超预算到顶即停、`cap_reached` 如实上报，误配超大 TTL 或目录被塞爆时损失有界；缺省 TTL 以 `DEFAULT_SWEEP_TTL_DAYS` 与 `config.py` 字段声明为真身。
- 无独立 enabled 键：关闭语义全走 TTL≤0。

## 失败时看到什么

单根失败折成该根空结论、单件删不动计 `failed` 继续、禁触名册命中跳过计 `skipped_forbidden`（判定件抛错＝fail-closed 拦下）——清扫绝不变成禁触名册的绕道。整体异常只 `logger.warning("file sweep failed: <异常型名>")`，fail-open 不影响主链路。正常轮日志：删前计数行 `files sweep: root=… ttl=… 扫描=… 候选=… 禁触跳过=…`、逐件删除行、装配层汇总 `file sweep done: deleted=N forbidden_skipped=N`。

## 测试与验收

`tests/test_files_incoming_sweep.py`（锁六件事：只删登记根内旧件、TTL≤0 全关、删除上限保险丝与 `cap_reached`、禁触跳过、删前计数审计、绝不抛异常）。真机验收无独立条目：重启后以「每日 04:50 前后日志出现 `file sweep done`/`file sweep failed`」为观察点。
