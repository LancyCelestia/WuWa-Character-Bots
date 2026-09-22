# B01.telegram Telegram 适配器

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.telegram Telegram 适配器

> getUpdates 网络韧性、file_id 取字节、嵌套块级元素降级。

- 归属板块：[B01](../README.md)
- 实现落点：`scripts/telegram_resilience.py`
- 帮助主题：Telegram
- 配置键前缀：`bot_telegram_`, `bot_tg_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [轮询韧性与退避](polling-resilience.md) | — | — | — | — |
| [媒体 file_id 取回](media-download.md) | — | — | — | — |
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

Telegram 是 QQ 之外的第二条真人通道：管理员自己在 TG 上跟守岸人说话、收运维通知。它的网络路径经代理，抖动是常态而不是异常——断网、代理半开、另一实例抢同一个 token，都会把「轮询」这一件事打出各种形态的错误。这一簇要解决的是：这些故障不许把整个进程带下水，也不许把鉴权失败伪装成网络问题去无限重试。

第二件事是媒体：TG 的 photo/sticker/animation/video_note/voice/audio 段只带 `file_id`，既不是 URL 也不是本地路径，识图与转写拿不到来源就只能看到「[图片]」这种标签。这一簇负责把 `file_id` 变成可读字节。

## 处理流程

```mermaid
flowchart LR
  api[Telegram Bot API] --> poll[ResilientTelegramAdapter.poll]
  poll --> retry[重试边界 只覆盖 getUpdates]
  retry --> ev[上游事件解析与 offset]
  ev --> ing["_incoming_from_nonebot_event()"]
  ing --> enrich["enrich_telegram_file_segments()"]
  enrich --> msg[IncomingMessage]
  msg --> B02.route-table
```

## 边界与降级

- 重试范围刻意收窄：只有轮询读取（`getUpdates`）可以无限退避；`sendMessage` 等出站调用的结果可能是 UNKNOWN，必须留给统一发送队列与回执去判定，绝不在这层偷偷重放（重放=重复消息）。
- 不可重试的状态码：401/403（鉴权失败）与 409（实例冲突，重试会变成两个实例互踢 token）单独分类，记一条定向告警后停止本层轮询，不当作「网络暂不可用」。
- 启动阶段的异常一律不许逃逸：代理抖动时 `setup` 抛错曾在实测里连带把整个进程炸掉，QQ 侧一并吞消息。现在 poll 外层带 catch-all 兜住。
- 日志纪律：退避期前几次每次都记、之后按比例抽样记一条、恢复时记一条（次数与比例以该件的日志分支实现为准）；只记异常类型名，因为错误文本可能含 token。
- 贴纸回应：TG 侧没有对应事件键，识别留着接口、如实降级。
- 已登记的残余：TG 正文里嵌套块级元素会早停（`docs/issue-ledger-p2-p3.md`，AGENTS 台账 #2）。

## 测试与验收

`tests/test_telegram_resilience.py`、`tests/test_telegram_media.py`、`tests/test_telegram_parser_v2.py`、`tests/test_v21_risk_red_dispatch_and_telegram.py`、`tests/test_nonebot_event_adapters.py`。
真机：`docs/acceptance-manual.md` §1.1（离线控制台）之后按 §5 检查表跑一遍；断网演练观察点是「进程不退出 + 恢复后消息继续进」；帮助主题 `邮件`/`Telegram` 属配置说明项，无独立命令面（`docs/audit-20260921.md` V1-10）。

## 现行缺陷

- `docs/design/central-decision-engine.md` 之外，TG 通道未纳入中央调度层描述符表：`runtime/capability_protocols.py` 生产零 import（审计 V1-1），Wave 1–4 未做。
- TG 正文嵌套块级元素早停、`social_v2` 同函数 channel_title/bio 未改（台账 #2，纯文本无实据，登记不修）。
- 出站侧 M-63 一类「终态宣称 ≠ 实际投递」的历史教训源自语音与传输层，TG 侧的段级记账仍属 Wave H 的收编范围，见 `docs/HANDBOOK.md` §35。
