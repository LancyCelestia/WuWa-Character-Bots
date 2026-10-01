# QQ 协议端接入（SnowLuma / OneBot V11） · 入站摄取与段归一

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.qq-snowluma · 入站摄取与段归一

- 层级：一级 B01 → 二级 qq-snowluma → 三级 `incoming-ingest`
- 实现落点：`plugins/bot_unified_runtime/domains/transport/sender/onebot.py`、`plugins/bot_unified_runtime/domains/transport/sender/nonebot.py`、`plugins/bot_unified_runtime/message_context.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把一条 NoneBot 事件变成主链路认识的 `IncomingMessage`：段归一、适配器与平台判定、会话/群/发送者字段、发送者显示名与平台角色、引用链与合并转发正文、语音段预转码、Telegram 媒体富化。跨过这条线之后，下游不再关心它是 QQ 还是 TG。

## 怎么调用

归一层公开件（可被任意域直接调用，全离线纯函数）：

- `domains/chat_reply/ingest/message_context.py:normalize_message_segments(raw_segments)` → `NormalizedMessage(plain_text, segments, quoted_text, forwarded_text)`
- 同文件 `collect_reply_chain(event)` / `collect_reply_chain_async(event, lookup)` / `format_reply_chain(chain)`
- `domains/media/ingest/telegram_media.py:enrich_telegram_file_segments(...)`

装配点在根 `__init__.py`，均为下划线私有件、未登记为能力，只由主 matcher 调用：`_incoming_from_nonebot_event(...)`（总装配）、`_onebot_segments_from_message_payload`、`_extract_onebot_raw_segments`、`_transcode_record_segments`、`_make_onebot_reply_lookup`、`_forward_message_text`。需要「这条消息有没有图片/语音/转发」这类判定时用同文件的在册谓词 `contains_visual_message_segments` / `contains_audio_message_segments` / `contains_forward_message_segments`，不要自己再扫一遍段列表。

## 开关与参数

没有配置键，全是模块常量——改它们就是行为变更，要走评审：

- 转发反查：单次超时 `_FORWARD_MESSAGE_API_TIMEOUT_SECONDS`、嵌套深度 `_FORWARD_NESTED_MAX_DEPTH`、子节点总上限 `_FORWARD_NESTED_MAX_TOTAL`（三个数值以该件常量定义为准），主/子反查共享同一总预算。
- 语音可解码后缀表 `_RECORD_CONVERTIBLE_SUFFIXES`（成员以该常量为准），不在表内才去转码；`get_record` 的硬超时以该调用的常量为准。
- 音频段类型 `AUDIO_SEGMENT_TYPES = {record, voice, audio}`：OneBot 与 Telegram 三种写法都要认，历史上漏认 `voice/audio` 导致 TG 语音被当普通文本。
- 适配器名归一 `_normalize_adapter_name`：事件模块名推不出时按 `onebot v11` 兜底。

## 失败时看到什么

- 转发反查失败：一条 warning + 正文为空，用户看到的是一句诚实的「没读出来」，不是崩。
- 引用链某一环拿不到：反查器返回 None，链上少一环，绝不拿猜测填。
- 语音转码失败：段保持原样，ASR 链路按自身降级面回话（不谎称听懂）。
- NoticeEvent 族（戳一戳等）没有 message 字段：`event.get_plaintext()` 抛 ValueError 时按空文本摄取，话术由 handler 侧入参提供。
- 空文本 + 纯媒体：正常入链，由 B02 的 IGNORE 兜底席决定是否静默。

## 测试与验收

`tests/test_forward_message_ingest.py`、`tests/test_forward_and_mood.py`、`tests/test_poke_notice_ingest.py`、`tests/test_b07_sender_level_ingest.py`、`tests/test_text_at_mention.py`、`tests/test_nonebot_event_adapters.py`、`tests/test_telegram_media.py`、`tests/test_perf_forward.py`。
真机：`docs/acceptance-manual.md` §6.4（回复合并转发问内容）、§6.6.1（触发形态抽样）。
