# Telegram 适配器 · 媒体 file_id 取回

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.telegram · 媒体 file_id 取回

- 层级：一级 B01 → 二级 telegram → 三级 `media-download`
- 实现落点：`scripts/telegram_resilience.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把 Telegram 媒体段的 `file_id` 变成能消费的字节。TG 入站的 photo/sticker/animation/video_note/voice/audio 段里只有 `file_id`（适配器形态是 `data.file = file_id`，既不是 URL 也不是本地路径），三个取数口都解析不出来源，模型就只看得到「[图片]」「[语音]」这种标签。本件经 Bot API `get_file` 拿 `file_path`、下载字节、落到临时文件并把路径写回段里，让既有的「本机路径」链路照常消费。

落盘后缀决定这段字节**归哪条支路消费**：`photo`/`sticker`/gif 形态的 `animation` 走
`extract_image_urls`（图片族），而 `video_note` 与 mp4 形态的容器走 `extract_video_source`
（视频族，抽帧或原生 `video_url`）——`video_note` 恒为 mp4，图片支路的 PIL 打不开它，
2026-09-23 之前被误归图片族导致这类小视频画面**静默读不到**（两支路皆空、零日志），现已改归视频族。

可达性前提（2026-09-24 M2，用户裁定「彻底修复」）：本件的富化点在主聊天 handler 之内，
消息进不了 handler 就轮不到取字节。根文件放行谓词 `contains_visual_message_segments`
（`__init__.py:669` 的 `visual_types`）此前只认 OneBot 型名，TG 的 `photo`/`animation`/`video_note`
不在其列 ⇒ **裸发（无文案、不 @bot）的 TG 视觉消息整个进不了处理器**，媒体理解链路对其全瞎。
现该集合已同行扩入这三个 TG 段类型名（零插行，campus 坐标不变），活性锁
`tests/test_voice_media_routing.py::test_telegram_bare_visual_media_passes_the_admission_gate`
（段先过真归一层、断公共谓词输出）。

## 怎么调用

真身 `domains/media/ingest/telegram_media.py`：

- `enrich_telegram_file_segments(...)`：摄取层单点接线，由根 `__init__.py` 的主聊天 handler 在归一之后、进管线之前调用。
- 内部的 `file_id → file_path` 解析与下载走 Bot API；`file_path` 已是完整 URL 时直接下载（自定义 api server 会返回这种形态），否则拼 `{api_server}/file/bot<token>/<file_path>`。

这是入站富化件，不是登记能力（无 `capability_id`、无路由席位）；出站文件发送属 B08 的文件网关，与本页无关。

## 开关与参数

- 大小上限以 `DEFAULT_MAX_FILE_BYTES` 常量定义为准——对齐 Telegram `file/bot<token>` 端点的硬上限，超限返回 None（不是本地策略收紧）。
- `file_id → file_path` 有 TTL 缓存（`_FILE_PATH_TTL_SECONDS`，容量上限 `_FILE_PATH_CACHE_CAP`），防同一 file_id 反复 `get_file`；缓存值不含 token，无泄密面。
- 字节一律不缓存：临时文件是一次性交付物，到期清理。
- 超时 `_DEFAULT_TIMEOUT_SECONDS`；api base `_DEFAULT_API_BASE`。都是模块常量，改动属行为变更。

## 失败时看到什么

任何失败（`get_file` 异常、下载异常、超限、token 为空）都返回 None 并留 debug 日志，段保持原样——用户侧看到的仍是既有的「标签降级」行为（模型只知道有条图片，读不出内容），完全不变，也绝不抛异常打断这条消息。日志里只出现异常类型名与状态码，绝不落原文（异常消息可能带完整含 token 的 URL）。

## 测试与验收

`tests/test_telegram_media.py`（成功富化、失败保原样、超限、token 不入日志、缓存命中）。相关：`tests/test_telegram_parser_v2.py`。
真机：在 TG 发一张图问「这是什么」，读到内容即通过；`docs/acceptance-manual.md` §6.4/§6.5 对应条目。
