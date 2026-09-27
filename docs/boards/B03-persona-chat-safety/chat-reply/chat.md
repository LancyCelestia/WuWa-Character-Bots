# 人格对话与回复 · 人格对话

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.chat-reply · 人格对话

- 层级：一级 B03 → 二级 chat-reply → 三级 `chat`
- 路由席位：`CHAT`（matcher `chat`，command=False）
- 判定优先级：50
- 能力 id：`bot.chat`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py`、`plugins/bot_unified_runtime/domains/chat_reply/capabilities/poke.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

自然语言对话主能力：把一条消息（含引用链、语音转写、转发记录等已由 B01 归一的上下文）
变成守岸人语气的一段回复。它不占斜杠命令席位（`command=False`），触发形态是 @ 她、
按昵称点名、白名单抽签式的主动接话，以及政策门放行的普通群聊/私聊消息。产出是一条
呈现契约结果（正文 + 可选卡片诉求），交回中央出站管线，不在本域直接发消息。
生效条件：会话准入通过、内容安全闸未拒、模型链至少一跳成功。

## 怎么调用

- `plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py:build_chat_capability`
  ——装配入口，注入人格上下文 provider、LLM provider/模型路由、联网与梗图检索、
  内容路由配置、管理名册文本、好感度 store、交互计数等依赖（全为构造期注入，运行期
  不再回头找全局）。
- 同文件 `build_chat_result` 是「拿到上下文 → 拼提示词 → 出结果」的可测内核；
  `build_chat_prompt` / `build_chat_prompt_with_diagnostics` 只负责产出 messages 与
  预算诊断，便于离线断言分区内容。
- `looks_like_chat_text` 是路由侧的判定谓词（由 `base_router` 的 `chat_match` 调用，
  命令形态、纯链接、其他能力触发词都会让路），`build_direct_vision_messages` 供
  「看图/看视频/听语音」形态把媒体直接喂给模型：既收图片 URL 列表，也收调用方拼好的
  `media_parts`（`input_audio` / `video_url` 线形，由
  `domains/media/ingest/transcribe.py:build_native_audio_part` 与
  `domains/media/ingest/video_understanding.py:build_native_video_part` 构造）。
  **能不能原生喂由渠道声明决定**（`model_router.supports_native_media`，标签
  `native-audio`/`native-video`/`native-animation`，缺省不放行）——不原生时回落 ASR /
  抽帧转译路，原生命中时那两条转译支路主动让路（禁止同一份媒体既转译又原生发两遍）。
  图片族内部按「能否整包原生」两轴取数：段类型归属住 `vision_describe.IMAGE_GROUPS`（唯一一份），
  动画与否住 `vision_describe.requires_native_animation()`（容器判据，两侧共用、禁调用点复制表）。
  纯图片与**静图形态的贴纸**任何视觉渠道直发；**动画容器（gif 与视频容器形态的表情包/动图）
  只在声明了 `native-animation` 的渠道直发**，未声明渠道交 VLM 转成文字
  （用户 2026-09-23 晚二裁：不能按段类型整组一刀切）。动图不给原生时被 PIL 拼成静态 JPEG 条（丢时序），
  给了原生才按 `image/gif` 原字节直发——依据是 2026-09-23 实跑：grok-4.6 的网关对
  `image_url` 里的 gif 直接 400（`not a valid JPG, PNG, WebP, or ICO image`）。
  **门问的是本跳真实首跳**（2026-09-24 分级亲密裁定收口）：INTIMATE 会话的音视频/动图能力问句
  带该会话键（`_media_gate_session_key` 经 `resolve_intimate_context` 单点推导），
  含**被亲密头插换掉的真实首跳**（L2 显式开/管理员钉 ⇒ grok 零声明）；ML 派生的 L1 档不换头插、
  门与真实首跳同一家。未声明 ⇒ **先转译（ASR/抽帧/静态化）而不是剥掉**；只有转译口装配缺席
  才落"部件仍挂体、被裁的跳留『未送达』说明、交给声明过的下一跳"的末档
  （判据=`_media_capability_before_pin`，静默丢失是裁定禁止的形态）。
- 慢回复先行回执不在本域发消息：`domains/chat_reply/runtime/progress_ack.py` 只负责
  选材与门禁，实际投递由 B08 的唯一主动出口在管线侧完成（见下「失败时看到什么」）。
- 出站整形依赖中央件：`domains/render/roleplay.py:normalize_paragraph_breaks` 与
  `strip_action_brackets`、`domains/render/plain_text.py:redact_local_secrets`、
  `domains/core/session_keys.py`（会话键唯一口径）。
- 依赖的跨板块中央件只经由参数传入：模型选择是 B02 的
  `domains/chat_reply/llm_engine/model_router.py:build_model_router`，出站是 B08 的统一管线。

## 开关与参数

人格与正文形态：`bot_persona_files`（生产指向 Runtime 人格副本，缺省空=不加载）、
`bot_persona_display_name`、`bot_persona_nicknames`（点名触发词）、
`bot_persona_action_brackets`（缺省 True：括号动作拆段；关闭则动作随正文走）、
`bot_persona_versioned_injection`（缺省 False：**分区版本化注入新路径代码已在、
开关默认关、线上零变更**）。
回复详略：`bot_reply_detail`（缺省 `auto`）。
历史与记忆注入：`bot_history_enabled`（缺省 False）、`bot_history_max_turns`/
`bot_history_max_chars`、`bot_memory_enabled`（缺省 False）、`bot_memory_max_items`/
`bot_memory_max_chars`——**这些缺省关的开关意味着默认线上只带近期对话，不带长期记忆**，
别在文档或沟通里把记忆说成现役默认。
预算与失败面：`bot_chat_max_input_tokens`/`bot_chat_max_output_tokens`（上下文钳制，
输出只封顶不托底）、`bot_chat_failover_max_seconds`、`bot_chat_failover_min_hop_seconds`、
`bot_chat_hedged_requests_enabled`（影子并发）、`bot_chat_channel_cooldown_seconds`。
慢回复先行回执：`bot_chat_progress_ack_*` 全族（总闸、判定"慢"的阈值、每会话冷却、
群/私聊各一对黑白名单；键名与缺省值以 `docs/config-catalog-full.md` 为准）。
**这一族是装配期快照**，七键全在 `runtime/settings.py:RESTART_REQUIRED_KEYS`——
`/bot runtime set` 会**硬拒写入**（实得文案是通用的「该配置尚无安全热更新路径，
请修改 .env 并重启」，逐键带原因的那条在生产走的控制面分支上不显示），
改 `.env` 后要重启才生效。
主动接话门在 `domains/chat_reply/policy/gate.py`（好感门、每小时上限、冷却），参数名与口径见 B02。
全部键的权威清单与可热改性以 `docs/config-catalog-full.md` 为准（由 `scripts/doc_sync.py`
生成，本文不手写数量），生产值只在 `.env`。

## 失败时看到什么

- 模型链失败转移后仍失败：私聊出一句守岸人语气的短句（人格失败池，会话内游标轮换，
  不是每次都同一句；池耗尽或无会话上下文时随机取）；绝不显示异常栈或错误码。
- 上下文/装配缺件：运维向提示「这次暂时没能稳定完成，请稍后再试。」，细节走日志与告警。
- 群里能力失败：管线补一句群聊降级池短句（带会话级节流），错误细节仍不进群内正文。
- 疑似提示注入：温和拒答池（见 [反注入包裹与指令剥离](../persona-context/anti-injection.md)）。
- 内部异常：统一错误诊断卡（`domains/ops/monitor/error_report.py`，冷却闸内降级为纯文本），
  归 B09 叙述，本板块只保证正文兜底可用。
- 超长回复：正文尾部附「平台单条消息长度限制」提示句，分片由 B08 发送队列负责。
- **回复慢但没失败**：超过阈值仍未出结果时，先落一句守岸人语气的等待短句（池子在
  `runtime/progress_ack.py`，会话内游标轮换、相邻不重复），真回复随后照常到达。
  三条口径是硬约束：**阈值内出结果什么都不发**（事后也不补一句）；**回执发出后真回复回来
  什么都不做**（QQ 收不回，所以回执自身要读得通，不写道歉句也不撤回）；
  等待短句绝不取消已在跑的真实任务。群聊缺省不开、白名单群才开、黑名单永远赢。
  投递走 B08 唯一主动出口 `submit_active_push`（命名空间申报为 `ack`），
  投递口抛异常（没有在线 bot、或终态不是 SENT/REDIRECTED）当场退还该会话的冷却额度——
  发送失败不该惩罚用户的下一次追问；而中央闸**拦下**或判**顺延**时额度保留不退
  （拦下=这条本就不该重投，顺延=队列稍后会补发）。

## 测试与验收

`tests/test_chat_provider_chain.py`（provider 链与降级）、`tests/test_persona_prompt_and_memory.py`
（分区内容与记忆注入）、`tests/test_chat_token_limit.py`（预算裁剪）、
`tests/test_bgroup_chat_pipeline.py`（群聊链路与 A-19 降级）、
`tests/test_persona_failure_messages.py`（话术池轮换与池外禁句）、
`tests/test_roleplay_paragraphs.py`（段间单换行）、
`tests/test_progress_ack.py`（等待短句的池/门禁/冷却/请求形状，含"慢→恰一条回执且真回复照到"
与"快→零额外消息"的行为锁）、`tests/test_native_av_input.py`（原生音频/视频线形与
能力门 fail-closed）。
真机：`docs/acceptance-manual.md` §6.6.1 触发形态、§6.6.7 内容感知路由、
§6.6.14 本夜改动（链跳数 / 原生音视频 / 先行回执 / 分段耗时）；
灰度中的分区注入以 `docs/design/v21r5-restart-acceptance-checklist.md` 观察点为准。
