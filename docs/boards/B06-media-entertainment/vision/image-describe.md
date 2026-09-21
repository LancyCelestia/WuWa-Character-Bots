# 图像与视频理解 · 识图与场景归属

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B06.vision · 识图与场景归属

- 层级：一级 B06 → 二级 vision → 三级 `image-describe`
- 实现落点：`plugins/bot_unified_runtime/domains/media`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把图片（含表情包、mface）变成一段紧凑文字：画面简述、可识别角色/作品、屏上文字
转写。结果作为**不可信上下文**注入当前消息，由人格模型消化后回答——本入口不生成
用户看到的那句话。

同一套识别件还服务订阅图文、媒体归档判类、表情库打标，因此模型注册表与失败处理
只在这里定义一次。

## 怎么调用

- `domains/media/ingest/vision_describe.py:describe_images`：主入口，吃归一后的
  原始段列表，返回描述文本。
- `extract_image_urls` / `extract_video_source`：从段里取图/取视频源。
- `prepare_vision_image_urls`：把本机路径、URL、GIF、超大图统一整成模型可收的
  data URL 列表（本机字节优先；GIF 取首帧重编 JPEG；长边超 2048 缩放）。
- `build_vision_provider` → `DynamicVisionProvider`：模型选择与故障转移。配置侧
  `bot_vision_model_registry`（支持 `id -> 条目` 与 `id -> [条目…]` 两种写法，
  条目内 `priority` 轮询）与运行时注册表（`/bot model vision add …`）合并，
  运行时条目覆盖其上且即时生效；调用失败按优先级转移，最多三个候选。
- 意图门控与「群最近图」：只有当消息确实想看图（总结/识别/看看/讲了什么这类信号）
  才触发；群里最近若干分钟的图片有环形缓存，别人发图 + 昵称为「看图」的诉求可读，
  不需要图在当前这条消息里。
- 反注入：识别文本进上下文前按中央不可信内容包裹规则处理（见
  [B03](../../B03-persona-chat-safety/README.md)），不让图里的文字变成指令。

## 开关与参数

- `bot_vision_enabled`（False）：总闸，关时整条链路零开销跳过。
- `bot_vision_mode`（`direct` | `relay`）：`direct`=图片直给模型；`relay`=先由视觉
  模型转写成文字再进人格上下文。
- `bot_vision_model_registry`（空）：模型与密钥，密钥只写 `env:变量名`。
- `bot_vision_timeout_seconds`（20）、`bot_vision_max_images`（2）、
  `bot_vision_max_chars`（500）、`bot_vision_reply_probability`（1.0，控制识图响应
  概率）。
- `bot_asr_*`（转写侧）：`bot_asr_enabled`、`bot_asr_model_registry`、
  `bot_asr_timeout_seconds`、`bot_asr_max_chars`。

谁能改：管理员经 `/bot runtime set` 与 `/bot model vision`；`.env` 改动需重启。

## 失败时看到什么

- 未启用或没配模型：不产生任何调用，也不产生任何提示——用户只看到她不认识这张图
  时的自然反应。
- 所有模型候选都失败：返回空描述，聊天继续；失败轨迹记在 provider 的
  `last_attempts`，管理员可在 `/bot model` 与日志看到，不打扰用户。
- 本机文件读不到、图片格式模型不收、体积过大：先尝试归一（缩放/首帧/重编码），
  归一失败即跳过该图并继续处理其余图片。
- 识别结果不可信（模型胡说）：设计上允许——它只是材料，最终由人格模型判断；
  因此描述文本要求「不确定就说不确定」。

## 测试与验收

`tests/test_vision_and_failover.py`（优先级转移、三候选上限）、
`test_vision_local_media.py`（本机字节优先、路径不可用回退）、
`test_vision_remote_data_url.py`（URL 透传与归一）、`test_group_recent_image.py`
（环形缓存与意图门控）、`test_media_quality.py`（质检闸）、
`test_reviewer_media_visibility.py`（识别文本进审核视野）。真机：
`docs/acceptance-manual.md` §6.6.5 的识图条目 + §6.6.1 的「群内发图 + 昵称看图」形态。
