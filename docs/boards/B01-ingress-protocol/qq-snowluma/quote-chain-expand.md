# QQ 协议端接入（SnowLuma / OneBot V11） · 引用与合并转发递归反查

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.qq-snowluma · 引用与合并转发递归反查

- 层级：一级 B01 → 二级 qq-snowluma → 三级 `quote-chain-expand`
- 实现落点：`plugins/bot_unified_runtime/sender`、`plugins/bot_unified_runtime/message_context.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

两条上下文反查：①引用（quote/reply）链沿 `get_msg` 逐层往上回溯，把被引用消息原文按 `[引用内容]` 块拼进文本；②合并转发（forward / chat_record）用 `get_forward_msg` 展开正文，并递归展开其中的子转发。作用是让用户「回复一条消息问它讲了什么」「存这条转发」这类用法真的能读到内容，而不是只看到一个 id。

## 怎么调用

公开件（`domains/chat_reply/ingest/message_context.py`）：

- `collect_reply_chain(event)`：只吃事件自带信息，同步返回 `ReplyChainItem` 列表。
- `collect_reply_chain_async(event, lookup)`：注入异步反查器以拿到事件里没有的更深层；反查器由根 `__init__.py:_make_onebot_reply_lookup(bot)` 构造（内部件，失败一律返回 None）。
- `format_reply_chain(chain)`：渲染成文本块；写入前经 `_neutralize_markers` 剥掉内部标记字面量，防止借引用内容注入人格指令。

合并转发在装配层：根 `__init__.py:_forward_message_text(bot, event, timeout_seconds=None)`（内部件），配套谓词 `contains_forward_message_segments`、子 id 收集 `_collect_nested_forward_ids`（保序去重）。

## 开关与参数

全部是常量，无配置键、不可热改：

| 项 | 真身 | 值语义 |
|---|---|---|
| 引用链深度 | `message_context.py:REPLY_CHAIN_MAX_DEPTH` | 递归回溯的最大层数，取值以该常量现算为准 |
| 每级/总字数钳制 | `REPLY_CHAIN_PER_LEVEL_CHARS` / `REPLY_CHAIN_TOTAL_CHARS` | 超长截断加省略号，取值以该常量现算为准 |
| 段归一嵌套止境 | `message_context.py:_flatten(depth=)` | 超过该件内置止境直接返回空，止境值以其为准 |
| 转发深度/节点/超时 | 根 `__init__.py:_FORWARD_NESTED_MAX_DEPTH` / `_FORWARD_NESTED_MAX_TOTAL` / `_FORWARD_MESSAGE_API_TIMEOUT_SECONDS` | 主+子共享一个总预算，取值以这些常量现算为准 |

## 失败时看到什么

- 反查器抛错或超时：该层返回 None，链少一环，不谎报内容。
- 传进去的 id 不是真合并转发（普通消息 id）：协议端会拒（历史上是「消息已过期或者为内层消息」），本层打一条 warning、正文空。
- 预算耗尽或撞到深度/节点上限：停在当前层，剩余子转发保留 `[合并转发:id]` 占位——宁可不完整，也不无限递归把这条消息的处理拖到分钟级。
- 环引用：同 id 只取一次（`seen` 集合），必然终止。
- 引用内容里出现 `[引用内容]`、`【` 之类内部标记：中和后再进文本，防注入。

## 测试与验收

`tests/test_forward_message_ingest.py`（含嵌套展开）、`tests/test_forward_and_mood.py`、`tests/test_parser_multipage_quote.py`（解析侧多页引用）、`tests/test_perf_forward.py`（预算与吞吐）、`tests/test_nonebot_event_adapters.py`。
真机：`docs/acceptance-manual.md` §6.4 的合并转发条目；媒体归档侧「回复合并转发存聊天记录」见 §6.6.2。
