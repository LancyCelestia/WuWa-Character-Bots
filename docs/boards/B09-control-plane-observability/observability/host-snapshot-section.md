# 日志·指标·Trace·审计 · 宿主快照分区注记口

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.observability · 宿主快照分区注记口

- 层级：一级 B09 → 二级 observability → 三级 `host-snapshot-section`
- 实现落点：`plugins/bot_unified_runtime/domains/ops/audit`、`plugins/bot_unified_runtime/domains/ops/collectors`、`plugins/bot_unified_runtime/domains/ops/monitor/__init__.py`、`plugins/bot_unified_runtime/domains/ops/monitor/alerts.py`、`plugins/bot_unified_runtime/domains/ops/monitor/disconnect_notice.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_service.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_store.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_card.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_status.py`、`plugins/bot_unified_runtime/domains/ops/monitor/intent_telemetry.py`、`plugins/bot_unified_runtime/domains/ops/monitor/loop_watchdog.py`、`plugins/bot_unified_runtime/domains/ops/monitor/result_unknown.py`、`plugins/bot_unified_runtime/domains/ops/monitor/runtime_event_log.py`、`plugins/bot_unified_runtime/domains/ops/monitor/usage_monitor.py`、`plugins/bot_unified_runtime/domains/ops/host_snapshot.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

给人格上下文注记用的「宿主快照」**单行文本口**：一行「`【宿主快照】CPU 12% · 内存 46%（采样 12:03:05）`」。只取 CPU/内存两枚占用项，带 30s TTL 缓存（供每轮对话注记，比命令面 `cached_host_snapshot` 的 90s 更激进）；注入侧只认 admin/super_admin 角色才注入——本口自己不做权限门，只产文本、可见面由注入侧裁。

## 怎么调用

真身 `domains/ops/host_snapshot.py::host_snapshot_section_text(max_age_seconds: float = 30.0) -> str`（另有测试专用失效口 `invalidate_host_snapshot_for_tests()`）。采样**只复用** `domains/ops/host_metrics.py` 的在册采集器 `_collect_spec`（逐项调用而非整卡全指标采集——「轻量」且不绕判据；本文件体内零 psutil/注册表/磁盘直调，AST 自门锁在测试件）。生产消费点唯一：`domains/chat_reply/character/providers.py` 宿主快照分区——借 `quirks_section` 这个「裸渲染自题分区」槽注入（chat.py 对该槽整段原样输出、不加盖头），自题头 `SECTION_HEADER` 并进缓存文本、保证模型可分辨。**只准在工作线程里调**：缓存过期后的第一次调用要阻塞约 200ms（CPU 占用率必须带间隔窗采样，`interval=None` 的首采是自进程启动以来的平均值＝假数）。

## 开关与参数

**无配置键**：缓存窗是调用参数（生产消费点写死 `max_age_seconds=30`，当时值；≤0＝每次现采）；「这台机器有没有 psutil」由真身 `host_metrics.psutil_available()` 回答，本口只问不读。注入角色门＝providers.py 现算的 `{admin, super_admin}` 集合，非超管分区整块缺席、一个读数不采。采样两枚指标 id（`cpu_percent`/`memory`）以 `host_metrics.METRIC_SPECS` 在册项为准。

## 失败时看到什么

任何失败＝**空串（fail-open）**：psutil 缺席/真身采样异常/展示值解析不出 → 空串且**不占缓存**（下次还有机会重试）；两项全空＝空串，调用方整段缺席——绝不编数、绝不抛异常打断调用链。注入侧 ImportError（模块并行期缺席）静默、分区不出；其余异常 `logger.warning("host snapshot section failed …")` 后同样分区缺席，不炸对话。

## 测试与验收

`tests/test_host_snapshot_section.py`（锁四件事：文本形态与缓存口径——窗内同一份采样、过期重采、`max_age_seconds<=0` 每次现采；fail-open 空串且不占缓存；AST 自门锁——本文件长出取数直调即红）。真机验收无独立条目：属人格上下文验收面——超管对话里模型可引用宿主占用注记（带「采样 HH:MM:SS」），普通号注入面缺席。
