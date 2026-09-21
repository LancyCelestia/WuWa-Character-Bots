# 图像与视频理解 · 抽帧与字幕链路

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.vision · 抽帧与字幕链路

- 层级：一级 B06 → 二级 vision → 三级 `video-frames`
- 实现落点：`plugins/bot_unified_runtime/domains/media`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把一段视频变成一份「材料式简报」：画面抽帧交视觉模型、音轨交 ASR、平台自带的 CC
字幕与元数据作为文本上下文一起送入，合成一份事实底稿供人格模型消化。同时负责两件
体验上的事——分析期间的进度回执（ack），以及把看过的视频登记进媒体档案库，让
「回复这条视频再追问」不必重跑一遍。

## 怎么调用

- `domains/media/ingest/video_understanding.py:build_video_brief`：编排口，返回
  `VideoBrief`。内部件：`detect_deep_video_request`（用户明确要「仔细看」时走深析
  档）、`_extract_audio_clip`（ffmpeg 截音轨）、`_call_vision`（一次请求）、
  `_compose_video_brief`（合成）。
- `domains/media/ingest/vision_describe.py:_extract_video_frames`：抽帧器，被媒体归档
  与识图共用，不留第二份。
- `domains/media/ingest/transcribe.py:build_asr_provider` / `transcribe_audio`：
  ASR 口，模型注册表 `bot_asr_model_registry`，与视觉同构的优先级故障转移。
- `domains/media/video/video_pipeline.py`：运行时编排——`_prepare_video_understanding_message`
  （回复视频时反查文件并准备上下文）、`_register_bot_sent_video_assets`（bot 发出的
  视频登记）、`_fetch_reply_video_file`（经协议端取被回复的视频文件）。
- `domains/media/registry/media_registry.py:build_media_registry`：档案库
  （`chat_message_id` ↔ 视频文件 ↔ 平台元数据 ↔ CC 字幕 ↔ 感知简报），命中即复用
  简报；写路径失败一律 warning 后吞掉，读路径未命中返回 `None`——媒体记忆缺失
  绝不阻断聊天。
- CC 字幕由链接解析侧在下载时一并抓取（中文优先，落盘 + 纯文本进
  `meta.subtitle_text`），追问链路天然可引用，不需要重下。

## 开关与参数

- `bot_video_understanding_enabled`（False，生产已 true）：总闸。
- `bot_video_max_frames`（6）普通档抽帧数；`bot_video_deep_enabled`（True）+
  `bot_video_deep_frames`（16）深析档。
- `bot_video_brief_deadline_seconds`（75）/`bot_video_deep_deadline_seconds`（150）：
  整次分析的时间预算；`bot_video_brief_max_chars`（1200）简报长度顶。
- `bot_video_asr_max_seconds`（600）/`bot_video_deep_asr_max_seconds`（1800）：
  音轨截取上限；`bot_video_skip_asr_with_subtitle`（True）：有字幕就不转写。
- `bot_video_progress_ack_enabled`（True）+ `bot_video_progress_ack_cooldown_seconds`
  （60）：进度回执与刷屏抑制；`bot_video_fuzzy_followup`（True）：模糊追问也走视频。
- `bot_video_native_input`（False）+ `bot_video_native_max_mb`（20）：原生视频直传
  仅部分供应商支持，开启且失败时自动回退抽帧路径。
- 依赖 ffmpeg：本机需可用（路径探测在 `vision_describe`/`transcribe` 内部）；
  协议端侧的语音/视频转码依赖见 `docs/snowluma-setup.md`。

## 失败时看到什么

- ffmpeg 不可用或抽帧失败：跳过画面维度，仍可用字幕/元数据出简报；全失败则返回
  空简报，表现为「她没看懂这段视频」而不是报错。
- 音轨过长或超时：按预算截断，超出部分不转写，简报如实标注覆盖范围。
- 回复的视频文件已过期取不到：直接说明取不到原始文件，建议重发，不拿旧缓存冒充。
- 任何单信号失败都继续：本入口没有「整体抛异常」这条路径，异常只在编排层被捕获
  并记录原文（禁止吞异常不留痕）。

## 测试与验收

`tests/test_video_understanding.py`（一次请求纪律、字幕优先跳 ASR、失败降级）、
`test_video_seam.py`（与聊天链的接缝）、`test_video_progress_ack.py`（回执与冷却）、
`test_video_reply_flow.py`（回复视频追问闭环）、`test_media_registry.py`（档案与
复用、写失败不抛）、`test_media_rejection_retry_and_fallback.py`（拒收与回退）、
`test_asr_transcribe.py`。真机：`docs/acceptance-manual.md` §6.6.5 视频条目 +
§6.4 的字幕必存复核。
