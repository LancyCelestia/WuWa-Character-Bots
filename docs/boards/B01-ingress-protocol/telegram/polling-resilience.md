# Telegram 适配器 · 轮询韧性与退避

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.telegram · 轮询韧性与退避

- 层级：一级 B01 → 二级 telegram → 三级 `polling-resilience`
- 实现落点：`scripts/telegram_resilience.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

给 NoneBot 的 Telegram 适配器套一层网络恢复边界：只读性质的轮询请求失败时按指数退避重试，鉴权与实例冲突这类「重试也没用」的错误单独识别并停下，启动阶段的任何异常都不许逃逸到进程外。它不改上游类、不重复发消息、不接管 offset 与事件解析。

## 怎么调用

真身 `scripts/telegram_resilience.py`（不是插件包内模块，被 `bot.py` 在注册适配器时使用）：

- `build_resilient_telegram_adapter(adapter_type, *, network_error, logger, sleep=asyncio.sleep, retryable=None) -> type`：产出一个子类 `ResilientTelegramAdapter`，重写 `poll` 与 `_call_api`。
- `is_transient_telegram_error(exc) -> bool`：判定「值得重试」——传输层异常（`__cause__` 是 `httpx.RequestError`/`OSError`）、429、5xx。
- `permanent_telegram_status(exc) -> str | None`：从 `msg="Received unexpected NNN ..."` 前缀里取三位码，命中 401/403/409 返回该码，否则 None。

接线在 `bot.py`：`driver.register_adapter(ResilientTelegramAdapter)`。这是启动期装配，不是登记能力，没有 `capability_id`。

## 开关与参数

- driver 配置：`TELEGRAM_BOTS`（token 等），代理走系统/环境变量层；`.env` 里另有 `TELEGRAM_PROXY`、`TELEGRAM_WEBHOOK_URL` 键位（现役用长轮询，webhook 项属备用）。逐键以 `docs/config-catalog-full.md` 与 `.env.example` 为准。
- 管理员 TG 侧收件：`bot_telegram_admin_user_ids`、`bot_telegram_admin_chat_ids`（pydantic `Config` 字段，改后需重启）。
- 退避曲线写死在件内：起始 3 秒、倍增至 60 秒封顶。刻意不做成配置键——可调来调去只会掩盖网络事实。
- 不可热改。

## 失败时看到什么

- 断网/代理抖动：`Telegram <phase> 网络暂不可用；这是适配器重试，不是 NoneBot 启动失败。请检查代理与 Telegram 连通性；累计失败 N 次（<类型名>），Xs 后重试。`；恢复后一条 `已恢复，累计重试 N 次`。
- 401/403：`检测到非临时故障：HTTP 401，鉴权失败（token 无效或被吊销，暂停重试）… 已停止本层重试；请处理后重启进程。`
- 409：同上口径，理由写作「实例冲突（另一实例正在 getUpdates，停止争抢）」。
- 任何情况下日志都不落异常原文（可能含 token），只落类型名与状态码。

## 测试与验收

`tests/test_telegram_resilience.py`（可重试分类、永久码分流、catch-all 不逃逸、退避计数、出站不重放）、`tests/test_v21_risk_red_dispatch_and_telegram.py`。
真机：`docs/acceptance-manual.md` §6.5 已知边界；断网演练判据＝进程存活 + QQ 侧不受牵连 + 恢复后消息继续进。
