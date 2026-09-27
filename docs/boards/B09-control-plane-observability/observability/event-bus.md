# 日志·指标·Trace·审计 · 统一事件与 SSE

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.observability · 统一事件与 SSE

- 层级：一级 B09 → 二级 observability → 三级 `event-bus`
- 实现落点：`plugins/bot_unified_runtime/domains/ops/audit`、`plugins/bot_unified_runtime/domains/ops/collectors`、`plugins/bot_unified_runtime/domains/ops/monitor/__init__.py`、`plugins/bot_unified_runtime/domains/ops/monitor/alerts.py`、`plugins/bot_unified_runtime/domains/ops/monitor/disconnect_notice.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_service.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_store.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_card.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_status.py`、`plugins/bot_unified_runtime/domains/ops/monitor/intent_telemetry.py`、`plugins/bot_unified_runtime/domains/ops/monitor/loop_watchdog.py`、`plugins/bot_unified_runtime/domains/ops/monitor/result_unknown.py`、`plugins/bot_unified_runtime/domains/ops/monitor/runtime_event_log.py`、`plugins/bot_unified_runtime/domains/ops/monitor/usage_monitor.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把 bot 的运行过程变成可查询、可追随的事件流。记的不是聊天正文，而是「发生了什么」：
哪个来源、哪类事件、什么结果、耗时多少。查询与订阅走 REST + SSE，前端和管理侧只需
面对同一份持久化事件。

## 怎么调用

两层实现并存、概念命名沿用、实现独立：

- **控制面现行实现（已挂载）**：`control_plane/events.py` —— `RuntimeLogEvent` DTO +
  `RuntimeEventService`（SQLite 持久化 + keyset 分页查询，保留上限是构造参数
  `max_events`）+ `RuntimeEventBus`（有界队列 writer；`publish` 返回 `False` 必须视为
  未接收）。装配方显式创建、关闭时 `bus.close(timeout=…)` 排空。app 层在
  `control_plane/_app.py` lifespan 里按 `config.bot_control_plane_events_db` 建服务并
  `build_event_router(...)` 挂载。
- **V2.1 权威事件层（尚未接线）**：`domains/ops/monitor/event_service.py` +
  `event_store.py` —— `EventService`（发布面）/ `EventBroker`+`Subscription`（投递面）/
  `event_stream`（SSE 帧生成）/ `build_event_service`（集成工厂）。其 docstring 点名三处
  集成点（`_app.py` 换工厂、SSE 路由换挂、能力各出口 publish `EventDraft`），差异登记在
  `docs/design/v21-s5-events-log.md`。
- **HTTP/SSE 面**：`control_plane/api/events.py::build_event_router`，路由前缀
  `/api/v1/logs`：`GET ""`（分页查询）、`/sources`（来源枚举）、`/stream`
  （`text/event-stream`；`Last-Event-ID` 优先于 `after`，两者省略＝显式读当前保留窗口）、
  `/{event_id}`。
- **旁支的运行时事件文件**：`domains/ops/monitor/runtime_event_log.py` —— 单文件纯文本
  每行一条、自动轮转、线程安全，并带 logging 桥把 NoneBot 自身日志按同格式写进同一文件；
  键 `BOT_RUNTIME_LOG_*`（缺省值以该件与 `docs/config-catalog-full.md` 为准）。

## 开关与参数

合同要点（V2.1 层按 `docs/design/backend-v2-implementation-guide.md` §6-§8 钉死，逐条
住 `event_service.py`/`event_store.py` docstring，此处只点名不抄数值）：

- **先持久化后投递**：`EventStore.append` 的 COMMIT 即发布线性化点，订阅者看到的 seq
  严格单调且不早于落库。
- **publish best-effort**：有界队列 + 丢弃计数，永不上抛、永不阻塞调用方；
  accepted=已入队，不等于已持久化。
- **至少一次传递**：回放与实时重叠段按 seq 去重，跨重连仍可能重复，客户端必须按
  `event_id` 幂等去重。
- **游标过期显式 resync**：流内原因码 `cursor_expired` / `slow_consumer` /
  `store_unavailable`，禁止静默跳缺口；客户端应提示缺口并由用户选择重新订阅。
- **心跳与有界缓冲**：缓冲双上限（条数与字节）超限即 resync 并断流；心跳周期与上限
  数值以 `event_service.py` 构造参数为准。凭据只走请求头，权限撤销复查为 False 即断订阅。
- 枚举：`source` 与 `category`（与 severity 分离）以 `control_plane/events.py` 的
  `EVENT_SOURCES`/`EVENT_CATEGORIES` 现值为准，枚数不在本页手写。
- 本层没有业务开关：它是诊断事件底座，控制面开着才谈得上查询与订阅。

## 失败时看到什么

隐私防线在入口不在出口：`message` 只输出分类固定摘要、绝不保存调用方自由文本；
`details` 为递归白名单标量（操作标识、状态、计数/耗时），自由文本摘要一律丢弃；
字符串再过 `domains/render/plain_text.py::redact_local_secrets` 与
`domains/ops/audit/logger.py::redact_private_debug`，脱敏器抛错→该值丢弃（fail-closed）。
存储不可用：查询面 `EventStoreUnavailable` → 503 `retryable`；写队列满：事件被丢弃并计数，
牺牲可见性换主链路不卡。`bus.close` 返回 False 表示 writer 仍在退出，需再次等待。

## 测试与验收

`tests/test_control_plane_events.py`（envelope/游标/410/SSE 帧）、
`tests/test_event_idempotency.py`、`tests/test_event_service_v21.py`（V2.1 层合同）、
`tests/test_runtime_event_boundaries.py`。用例数以最近一次 `scripts/dev.ps1 -Task test`
实跑为准。真机（重启后、控制面开启时）：带 Bearer 拉 `/api/v1/logs/stream`，制造几条
能力动作，确认 seq 单调、断线带 `Last-Event-ID` 重连不重复消费；用过期游标确认收到显式
`cursor_expired` 而非空流。
