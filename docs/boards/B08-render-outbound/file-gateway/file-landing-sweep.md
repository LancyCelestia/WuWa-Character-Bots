# 文件网关与受控下载 · 落盘点 TTL 清扫

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.file-gateway · 落盘点 TTL 清扫

- 层级：一级 B08 → 二级 file-gateway → 三级 `file-landing-sweep`
- 实现落点：`plugins/bot_unified_runtime/domains/files`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`incoming/` 落盘点的**寿命收口**（文件链路波 · 需求 16，2026-10-03）：管理员文件接收落盘后没有天然的删除时机，盘会 quietly 被吃掉。本入口按 TTL 只扫 `incoming/` 登记根，过龄件删除；禁触名册内的路径（`domains/core/safety_exec/paths.py` 唯一名册，缺省执法）跳过并计数，绝不越名册删件。调度注册面在 B07.scheduled-jobs（[落盘点 TTL 清扫调度](../../B07-schedule-automation/scheduled-jobs/file-sweep-scheduler.md)），本页管清扫判据本体。

## 怎么调用

真身 `domains/files/sender/restricted_runner.py`（受限写盘运行器同一件）：

- `sweep_expired_files(roots, *, ttl_days=…) -> list[...outcomes]`：逐根扫过龄件，产出逐件 outcome（删除数 / 禁触跳过数），同步函数、删放下线程池由调用方负责；
- `sweep_ttl_days_from_config(config)`：装配层现算口，读 `bot_files_incoming_ttl_days`，非法值回代码缺省。

只写不跑教义对清扫同样成立：本口只删不执行、不外发；只认装配层显式给的根，缺省策略零根＝零删除。

## 开关与参数

`bot_files_incoming_ttl_days`（`config.py` 声明，缺省值与逐键语义以该字段与 `docs/config-catalog-full.md` 为准）。**≤0 ＝ 关闭**：清扫对非正 TTL 一件不删（不是不注册——job 恒在，只是空转）。改动需重启（装配期快照，台账 #3 同族）。

## 失败时看到什么

fail-open：任何异常只落一行 `file sweep failed` 告警日志，绝不影响主链路；禁触命中不删只计数，日志汇总 `forbidden_skipped`。运行数据不可删铁律的边界：本口只碰 `incoming/` 登记根内的过龄件，SQLite/FAISS/cookie 等一律在名册与根白名单之外。

## 测试与验收

`tests/test_files_incoming_sweep.py`（TTL 边界、非正 TTL 零删除、禁触跳过、越界形态拒删）。真机：放一个过龄假件进 `incoming/`，等下一轮调度（或手动触发）确认删除且日志带计数；把 TTL 配成 0 确认零删除。
