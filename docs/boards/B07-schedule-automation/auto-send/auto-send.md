# 自动发送与主动搭话 · 自动发送

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.auto-send · 自动发送

- 层级：一级 B07 → 二级 auto-send → 三级 `auto-send`
- 路由席位：`AUTO_SEND`（matcher `auto_send`，command=True）
- 判定优先级：13
- 能力 id：`bot.auto_send`
- 实现落点：—
<!-- BOARD-AUTO:END -->

## 这个入口做什么

自动发送/起草命令入口（`RouteKind.AUTO_SEND`，判定优先级 13，`capability_id=bot.auto_send`，命令型 matcher）。输入是一句「报存 给 <收件人> 发消息|邮件 [，主题：… 内容：…]」，产出是一张结构化草稿预览（通道、收件人、主题、正文要求）。生效条件：路由命中 `is_auto_send_command_text`（正则要求完整语法）。当前是 **M0 预览版：只生成草稿、不真实发送**。

## 怎么调用

- 真身：`domains/schedule/auto_send/parser.py` 的 `is_auto_send_command_text` / `parse_auto_send_command` / `build_auto_send_preview_result`（旧 `capabilities.auto_send` 与 `runtime` 路径为再导出垫片）。意图契约 `domains/core/contracts/auto_send.py:AutoSendIntent`。
- 装配：根 `__init__.py` 的 `auto_send` matcher（`priority=13, block=True`），handle 里调 `build_auto_send_preview_result(...)` 产出回执，`capability_id=bot.auto_send.preview`（受控内部能力，直调下限见 outbound_gate T6）。收件人段用 、,， 分隔多人，"主题：/内容"分别解析，繁体链（報存/發/郵件/訊息）同改可达。

## 开关与参数

- 无独立总闸；命令需精确语法，`requested_send_policy=confirm_required`、`personalization_mode=light`、`batch_mode=batch`，风险按通道取（email=MEDIUM、chat_message=LOW），隐私=PERSONAL。
- 帮助主题「草稿」（含别名 报存/autosend/自动发送/報存）；`/bot queue`（帮助主题「队列」）看的是发送队列状态，不是这条命令。配置键前缀 `bot_auto_send_` 逐键以 `docs/config-catalog-full.md` 为准。

## 失败时看到什么

语法不完整 → 路由不认领（回落到普通聊天判定，`looks_like_chat_text` 会因命中 auto_send 语法而让路）；解析抛 `ValueError`（unsupported）被能力层挡在门外、不外发。预览正文如实写「仅预览，M0 不会真实发送」，不给人已发出的错觉。

## 测试与验收

`tests/test_content_video_auto_send.py`（命令解析与预览结构、收件人/主题/正文拆分）。真实发送流程待后续版本落地后再补端到端验收。
