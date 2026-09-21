# 邮件与控制台适配器 · 来信解析入链

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.mail-console · 来信解析入链

- 层级：一级 B01 → 二级 mail-console → 三级 `mail-inbound`
- 实现落点：`plugins/bot_unified_runtime/mail_adapter.py`、`plugins/bot_unified_runtime/mail_bridge.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把一封新邮件变成主链路的一条入站消息，并在获准时把回信送出去；同时承担「来信摘要转发给 TG 管理员」这条通知支路。生效条件：mail 适配器已连上、`bot_mail_bridge_enabled` 为真；自动回信还要 `bot_mail_auto_reply_enabled` 为真且桥未暂停。

## 怎么调用

真身两件（都是内部装配件，不是登记能力，无 `capability_id`）：

- `domains/transport/mail/mail_adapter.py`：`ResilientMailAdapter`（重写 `startup` / `run_bot` / `shutdown` / `_check_mailbox` / `_fetch_new_mail`）、`mail_retry_delay(attempt)`（有界退避表）、`describe_mail_error(exc, limit=160)`（一行可读摘要）、`QuietMailMessageEvent`（不把邮件正文刷进日志的事件类）。`bot.py` 经旧路径 `plugins.bot_unified_runtime.mail_adapter` 导入 `ResilientMailAdapter`，该路径是再导出垫片。
- `domains/transport/mail/mail_bridge.py`：`parse_mail_command(text) -> MailCommand`（`/mail` 命令族解析，邮箱地址经 `_email_address` 严格校验）、`MailBridgeState`（暂停态与通知去重，落 `bot_mail_bridge_state_file`）、`mail_event_dedupe_id(event)`、`connected_mail_accounts(...)`、`unresolved_mail_aliases(...)`、`build_mail_notification(...)`、`is_telegram_admin(event, admin_ids)`。

摄取与出站复用中央件：根 `__init__.py:_incoming_from_nonebot_event(event, bot_id=account, adapter_name="Mail")` 与统一管线；回信走 B08 的发送队列，不在本层直发。

## 开关与参数

- `bot_mail_bridge_enabled`（False）：整条桥的总闸。
- `bot_mail_auto_reply_enabled`（False）：来信自动回复。
- `bot_mail_notify_telegram_enabled`（True）：来信向 TG 管理员投递（仅在桥开启时有效）。
- `bot_mail_bridge_state_file`：暂停/已通知状态的持久化文件（相对路径经 `scripts/runtime_paths.py` 重映射到 Runtime）。
- `bot_mail_sender_aliases`：发件地址→称呼映射；`bot_mail_notify_preview_chars`：通知里的正文预览长度。
- driver 配置 `MAIL_BOTS`（IMAP/SMTP 账号）。改这些键都要重启；逐键语义以 `docs/config-catalog-full.md` 为准。
- 退避与超时是模块常量：连接重试 `_RETRY_DELAYS`（3→60 秒封顶），`UNSEEN` 搜索单次硬超时 15 秒 + 同连接一次 2 秒短重试；重试仍超时则抛回外层走整链重连。

## 失败时看到什么

- IMAP 断连/半开：外层按退避表重连，日志一行一条被稀疏化（1,2,4,8…），错误文本走 `describe_mail_error`——只截首行并限长，不会把整封邮件正文带进日志。
- 搜索挂死：短重试一次，仍超时即整链重连（重连路径会清掉「早退缓存」，保证真发 SELECT）。
- 非法地址（`/mail` 参数）：抛「必须是完整邮箱地址」的明确错误，不静默丢弃。
- 自动回复被关闭或桥被暂停：来信仍被摄取，只是不回，审计留痕。

## 测试与验收

`tests/test_mail_adapter_resilience.py`、`tests/test_mail_bridge.py`。
真机：手册检查表（§5）无邮件专项，按自发一封信验收——观察「被摄取 → 按开关决定是否回 → TG 管理员收到且只收到一条通知」，通知去重由 `MailBridgeState.claim_notification` 保证。
