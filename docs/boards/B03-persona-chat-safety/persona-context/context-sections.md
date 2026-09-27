# 人格上下文与称谓身份 · 上下文分区渲染

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.persona-context · 上下文分区渲染

- 层级：一级 B03 → 二级 persona-context → 三级 `context-sections`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character/__init__.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/addressing.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/documents.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/emotion.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/glossary.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/knowledge_service.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/memory.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/memory_extract.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/memory_service.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/persona_injection.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/persona_service.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/persona_set.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/providers.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/reflection.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/relationship.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/relationships.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/session_identity.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/shared_export.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/shared_group.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/source_summary.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/temporal.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/trend.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/vector_knowledge.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/worldbook_service.py`、`personas/shorekeeper`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把上下文切成一块块带【标签】的分区喂给模型：人格正文、世界观、实时感知、当前心情、
称谓边界、记忆、知识、时梗、梗检索、联网结果、管理团队、共同会话……**空分区整段不渲染**，
所以没开记忆时提示词只是短一截，不会出现「（无）」这种既占字符又诱导模型编造的占位。
产出是一份纯文本块序列（供 chat 拼装），生效条件是对应数据源真的取到了内容。

## 怎么调用

- 装配出口：`domains/chat_reply/capabilities/chat.py:build_chat_prompt` /
  `build_chat_prompt_with_diagnostics`（后者附分区级取用与裁剪诊断）。
- 数据来源：`domains/chat_reply/character/providers.py:build_character_context_provider`
  造出 `FileCharacterContextProvider`，产出契约对象 `ContextBundle`
  （定义在 `domains/core/contracts/character.py`）。**分区内容的所有口径都在这两处**，
  别处不准再拼一份第二人设。
- 各分区的渲染小函数（chat.py 私有，只服务装配口）：`_memory_lines`、`_history_lines`、
  `_knowledge_lines`、`_trend_lines`、`_temporal_lines`、`_glossary_lines`、
  `_relationship_lines`、`_emotion_lines`、`_shared_group_lines`、`_meme_search_lines`、
  `_time_window_summary_section`。
- 依赖的中央件：会话键 `domains/core/session_keys.py`、文本边界
  `domains/core/text_boundary.py`、出站打码 `domains/render/plain_text.py`。
- 分区清单与顺序以代码派生为准（`build_chat_prompt` 内的拼装序列），本文不手写数量；
  需要核对就用 `build_chat_prompt_with_diagnostics` 打印实际分区段。

## 开关与参数

分区级开关（关掉=该分区整段不出现，不是出现空壳）：
`bot_memory_enabled`（缺省 False）、`bot_history_enabled`（缺省 False）、
`bot_knowledge_service_enabled`（缺省 False）与 `bot_knowledge_files`/`bot_knowledge_top_k`、
`bot_trend_enabled`（时梗备注）、`bot_glossary_*`（世界观/热词）、`bot_affinity_enabled`、
`bot_mood_enabled`、`bot_reactions_enabled`（表情回应分区）、
`bot_persona_files`（人格正文唯一来源）、`bot_super_admin_user_ids` 与
`bot_admin_profiles`（管理团队分区）、`bot_persona_versioned_injection`
（缺省 False：分区版本化注入代码已在、线上仍走文件正文）。
预算：`bot_chat_max_input_tokens` 与模块内地板常量 `MIN_CHAT_PROMPT_BUDGET`。
权威键表在 `docs/config-catalog-full.md`（生成物）。改这些键须重启（装配期读取）。

## 失败时看到什么

- provider 抛异常 → 该分区留空 + 一行 warn（fail-open 到「少一段信息」，不 fail 到整条失败）。
- 记忆读不到时有**诚实句**（例如「未读取到可用记忆」），但只在确实调用过记忆源时出现；
  功能未启用不会伪装成「查过了没有」。
- 检索/知识/联网分区里的正文一律先过不可信处理（见
  [反注入包裹与指令剥离](anti-injection.md)），命中注入形态的句子会被丢掉而不是照做。
- 预算吃紧：按分区优先级从最旧历史与低价值长文削起，尾部附裁剪提示句；
  人格正文与称谓/安全指令不参与裁剪。

## 测试与验收

`tests/test_persona_prompt_and_memory.py`（分区内容与非空条件）、
`tests/test_chat_token_limit.py`（裁剪顺序与地板）、
`tests/test_persona_injection_v21.py`（版本库路径的等价性）、
`tests/test_persona_service_v21.py`（人格版本库生命周期）。
真机：发一条会让记忆/知识分区出场的消息，再关掉对应键复跑，核对
「关掉的分区整段消失」而不是留下空标题。
