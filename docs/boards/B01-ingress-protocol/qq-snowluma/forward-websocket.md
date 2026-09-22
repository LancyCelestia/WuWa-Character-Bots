# QQ 协议端接入（SnowLuma / OneBot V11） · WS 连接与重连

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.qq-snowluma · WS 连接与重连

- 层级：一级 B01 → 二级 qq-snowluma → 三级 `forward-websocket`
- 实现落点：`plugins/bot_unified_runtime/sender`、`plugins/bot_unified_runtime/message_context.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

建立并维持 bot 与 QQ 协议端（SnowLuma）之间的正向 WebSocket 连接：入站事件流交给 NoneBot 分发，出站指令由 `call_api` 下发。生效条件是三件同时成立——driver 配了 WS 地址、协议端在听、`bot.py` 注册了 V11 适配器。它自己不做业务判定，也不决定发什么。

## 怎么调用

- 连接注册不是插件的公开函数，在根启动文件 `bot.py`：`driver.register_adapter(OneBotV11Adapter)`，地址读 NoneBot driver 配置 `onebot_ws_urls`（生产在 `.env.prod`），启动期把实际监听地址打进日志。
- 出站段构造（内部装配件，非登记能力）：`domains/transport/sender/onebot.py:build_onebot_message_segments(send_request)`。
- 出站校验开关（内部件）：同文件 `set_outbound_verify_provider(provider)`，注入「当前是否有在线 OneBot」的判定；没有在线端时挂起回执走 `bot_unavailable`。
- 主动消息一律不在此层直调 `call_api`：走 `domains/transport/sender/outbound_gate.py` 与发送队列（B08）。

## 开关与参数

- driver 配置：`DRIVER`、`ONEBOT_WS_URLS`（列表，本机 3001）。这两枚是 NoneBot driver 级配置，不在 `Config` 的 `bot_*` 字段里，逐键以 `docs/config-catalog-full.md` 与 `docs/snowluma-setup.md` 为准。
- 重连节奏由适配器自管（间隔以适配器的实现为准），本仓不覆盖。
- 日志稀疏化在 `bot.py` 的 logger filter：把 `Error while setup websocket` 归为重复重连压掉堆栈。改它属行为变更（会重新刷屏），不要顺手删。
- 以上都不可热改：driver 配置在进程启动时读定，改完必须重启。

## 失败时看到什么

- 连不上：每轮一条被限速的 ERROR，再按适配器自管的重连节奏重试（节奏以适配器实现为准）；用户侧表现为「消息石沉大海」，bot 进程本身不退出。
- 连上但发送结果不确定：记 `OperationalIssue(kind=result_unknown)` 并落 `ResultUnknownLedger`（落点库路径以 `config.py` 的路径键为准），重连后对账收敛；无在线端时队列回执记 `bot_unavailable`，挂起任务超过年龄上限自动清理（上限以该队列的实现为准）。
- retcode 非 0：按「最终失败 / 可重试」分流（`_is_final_failure_retcode`、`_exception_platform_rejection`），不无脑重放——重放会造成重复消息。

## 测试与验收

`tests/test_nonebot_sender.py`、`tests/test_onebot_chunk_budget_floor.py`、`tests/test_nonebot_startup_boundary.py`、`tests/test_v21_s14_snowluma_tail.py`、`tests/test_unified_delivery_routes.py`。
真机：`docs/acceptance-manual.md` §2（接 QQ，含 SnowLuma 起停与 token 对齐）、§6.5（已知边界）；重连与对账观察点同页 §6.5。
