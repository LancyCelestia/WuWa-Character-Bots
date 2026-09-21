# V2.1 S5 统一事件服务（V21-SSE-001）— 实现记录与集成点

> 状态：**代码+测试完成，未接线生产**。合同=`docs/design/backend-v2-implementation-guide.md` §6 SSE 段 + §8。
> 实现席位：S5（A9 第三次派遣；前两次 1302 阵亡零落盘，本席从零执行）。
> 证据：`tests/test_event_service_v21.py` 19 passed（实跑命令见文末）。

## 1. 模块清单

| 文件 | 内容 |
|---|---|
| `plugins/bot_unified_runtime/runtime/event_store.py` | 事件模型 + SQLite 持久化 + 稳定游标查询。`EventDraft`（发布侧 DTO，隐私净化内建）、`RuntimeEventV21`（权威 DTO：seq/event_id/occurred_at/source/category/severity/message/request_id/trace_id/session_id/capability_id/model_id/safe_details/privacy_level）、`EventQuery`（复用 `contracts/request.PaginationQuery`，追加全过滤器）、`EventPage`、`EventStore`（WAL+busy_timeout=1000ms、单调 seq AUTOINCREMENT、计数保留+水位缺口检测）、`CursorExpired`/`EventStoreUnavailable`/`parse_cursor` |
| `plugins/bot_unified_runtime/runtime/event_service.py` | `EventService`（有界队列+单写线程 best-effort 发布）、`EventBroker`+`Subscription`（每连接有界投递缓冲）、`event_stream`（SSE 帧生成器）、`create_event_stream_app`（ASGI 兼容工厂）、`build_event_service`（集成入口） |
| `tests/test_event_service_v21.py` | 19 例全离线回归（tmp_path + fake clock + 裸 ASGI scope） |
| 本文档 | 合同映射/隐私口径/集成点/遗留项 |

## 2. 合同逐条映射（§6 SSE 段）

| 合同原文 | 实现落点 | 测试 |
|---|---|---|
| 持久化单调序号 | `runtime_events_v21.seq INTEGER PRIMARY KEY AUTOINCREMENT` + watermark 表 | `test_restart_seq_continuity` |
| Last-Event-ID、至少一次传递与客户端去重 | SSE 帧 `id: <seq>`；跨重连可能重复（至少一次），客户端按 `event_id` 幂等去重；流内重叠段服务端先按 `seq>已发送` 去重 | `test_sse_last_event_id_resume`、`test_sse_overlap_dedupe_subscribe_before_replay` |
| 历史回放衔接实时 | 订阅先于回放建立；回放页+实时缓冲由 seq 去重衔接，无缺口 | `test_sse_replay_then_live_seamless`、重叠测试 |
| 游标过期明确 resync，不静默丢失 | 流内 `event: resync`（reason=cursor_expired，带 oldest_seq 与 hint，`id:` 推进到重同步落点防重连循环），随后从最老可用处继续回放 | `test_sse_cursor_expired_explicit_resync` |
| 心跳 15s | 空闲 ≥heartbeat_seconds（默认 15s）发 `: heartbeat`；clock/sleep 可注入 | `test_sse_heartbeat_fake_clock_and_revocation` |
| 有界缓冲、慢客户端断开并给重同步提示 | Subscription ≤128 条且 ≤256KiB（构造可收窄）；超限→`resync(slow_consumer, dropped_events)` 并终止流 | `test_sse_slow_consumer_bounded_then_resume`、`test_subscription_bytes_bound` |
| 凭据放请求头，不用 URL token | `create_event_stream_app(auth=...)` 只收 scope+headers（bytes 字典）；无任何 URL token 读取 | `test_asgi_factory_...`（401 路径） |
| 权限撤销后中断订阅 | `revocation(principal)->bool` 周期复查接口；False→`event: unsubscribed` 帧并断开 | 同上心跳测试 revocation 段 |
| 分页默认 50 最大 200，稳定游标 | `EventQuery(PaginationQuery)`（limit 1..200 默认 50）；keyset `seq>` 稳定分页 | `test_pagination_default_50_max_200_and_stable_cursor` |
| 先持久化后投递（提交=线性化点） | 写线程 `store.append`（COMMIT）返回后才 `broker.broadcast` | 架构保证 + 并发测试 |

§8 映射：source 十二枚举逐一落 `EVENT_SOURCES`（存量 control_plane 的 capability/renderer 两枚举**有意不收**，以 §8 为准）；category 七类与 severity 分离（`SEVERITY_BY_CATEGORY` 默认映射+显式覆盖）；「普通日志拥塞可丢弃并计数」= publish 队列满/写失败/生命周期拒绝三计数器（dropped/write_error/rejected），零阻塞零上抛。

## 3. 隐私与安全口径

- `message`/`safe_details` 字符串一律过 `output.plain_text.redact_local_secrets`；脱敏器抛错→丢弃该值（fail-closed）。message 脱敏后截断 500 字符。
- `safe_details` 仅收标量叶子（str/int/float/bool/None），字符串截 256、递归深 3、节点 128、顶层 32 条、序列化 ≤2048 字节，超限整体丢弃（宁缺毋泄）。调用方**不得**把聊天正文/prompt 编码进事件（§8 原文仅授权工作区短期保存）。
- 操作标识（request_id 等）须匹配 `[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}` 且脱敏不改写，否则置 None；查询过滤器同形态校验，非法值报错而非静默失效。
- `privacy_level`（public/internal/restricted）仅持久化+透传；**按等级裁剪可见性属集成席位**（认证 scope），本席位不做（见遗留项）。
- 与存量 `control_plane/events.py` 的差异：存量对 ID 键「脱敏即丢弃」，本模块保留脱敏产物（redact 输出按构造即安全）；存量 message 强制替换为分类固定摘要，本模块保留脱敏后原文。两条差异均为可诊断性与隐私的再权衡，红线（密钥/Cookie/Bearer/绝对路径不入公共日志）不变。

## 4. 与存量 control_plane 事件层的关系

存量 `control_plane/events.py`（RuntimeLogEvent/RuntimeEventService/RuntimeEventBus）与 `control_plane/api/events.py`（FastAPI SSE 路由）**保持原样运行**；本模块是 V2.1 权威实现，概念命名（CursorExpired/EventStoreUnavailable/EVENT_SOURCES/EVENT_CATEGORIES/水位+keyset）沿用以降低替换成本。两套并存期间库文件不同（存量 `data/control_plane_events.sqlite3`，本模块默认 `data/control_plane_events_v21.sqlite3`，经 `scripts/runtime_paths` 重映射）。

## 5. 集成点（本轮不接线，接线属后续席位）

1. **服务装配**：`control_plane/_app.py` lifespan（现 321-342 行构造 `RuntimeEventService(_path(events_path))` 处）→ 换 `build_event_service(path, ...)`（默认路径经 runtime_paths 重映射；建议新增配置键 `bot_control_plane_events_v21_db`，入 config.py+config-catalog+path_fields 重映射）。
2. **SSE 路由**：`control_plane/api/events.py` 的 `/api/v1/logs/stream` → 换挂 `create_event_stream_app(service, auth=..., revocation=...)`（裸 ASGI 可直接 `app.mount`/挂 route endpoint；注意本实现游标过期走 200 流内 resync，**不是**存量的 HTTP 410，前端须适配 `event: resync`）。
3. **事件出口**：能力失败/管线里程碑/模型故障转移等出口 `service.publish(EventDraft(source=..., category=..., request_id=..., ...))`；source 按出口从 §8 十二枚举取。
4. **查询 REST**：`GET /api/v1/logs/events`（query=EventQuery）与 `GET .../{event_id}`（store.get）直接包 envelope 即可（envelope 复用 `contracts/envelope.py`）。

## 6. 已知取舍与遗留项

| # | 事项 | 处置 |
|---|---|---|
| 1 | `privacy_level` 无可见性强制 | 集成席位在 auth scope 层裁剪；本席位只透传 |
| 2 | SSE 流过滤仅 source/category/severity；request_id 等深过滤走 REST 查询 | 有意收缩流参数面；如需扩展在 `event_stream` 加参即可 |
| 3 | live 投递为 0.25s 轮询缓冲（非 loop.call_soon_threadsafe 唤醒） | 诊断事件可接受；延迟敏感时换事件唤醒 |
| 4 | 存量/新库双轨并存，事件不同步 | 接线席位一次性切换并废弃存量 |
| 5 | 计数保留（10000 条默认）非时间保留；无 export 动作 | §6 `logs/events/export` 属 REST 装配席位 |
| 6 | 未接线 `_app.py`（任务书硬约束：集成只留工厂与文档） | 本文档 §5 即接线说明书 |

## 7. 实跑证据

```powershell
$env:PYTHONDONTWRITEBYTECODE=1; $env:PYTHONUTF8=1; $env:BOT_AUTOSYNC=0
C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe `
  -m pytest tests/test_event_service_v21.py --basetemp="$TEMP\v21-events3" -p no:cacheprovider -q
# 实跑输出：19 passed in 7.31s（2026-09-17，S5 席位）
```
