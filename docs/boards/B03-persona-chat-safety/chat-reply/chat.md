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
  「看图/看视频」形态把媒体直接喂给视觉模型。
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

## 测试与验收

`tests/test_chat_provider_chain.py`（provider 链与降级）、`tests/test_persona_prompt_and_memory.py`
（分区内容与记忆注入）、`tests/test_chat_token_limit.py`（预算裁剪）、
`tests/test_bgroup_chat_pipeline.py`（群聊链路与 A-19 降级）、
`tests/test_persona_failure_messages.py`（话术池轮换与池外禁句）、
`tests/test_roleplay_paragraphs.py`（段间单换行）。
真机：`docs/acceptance-manual.md` §6.6.1 触发形态、§6.6.7 内容感知路由；
灰度中的分区注入以 `docs/design/v21r5-restart-acceptance-checklist.md` 观察点为准。
