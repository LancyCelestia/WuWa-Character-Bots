# 人格对话与回复 · 人格提示词拼装

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.chat-reply · 人格提示词拼装

- 层级：一级 B03 → 二级 chat-reply → 三级 `prompt-assembly`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py`、`plugins/bot_unified_runtime/domains/chat_reply/capabilities/poke.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把「她现在该知道的事」压成一份模型能读、又不越权的提示词：一段 system（人格正文 +
若干【标签】分区）+ 归一后的近期对话 + 当前用户消息（包成不可信块）。分区之间互不
覆写，空分区整段不渲染，所以缺记忆、缺知识时提示词只是变短，不会长出「（无）」这种
占位噪音。同一函数还负责按预算裁剪：先保人格，再按分区优先级和轮次从最旧的对话削起。
生效条件：CHAT 主能力被触发且会话准入通过。

## 怎么调用

- `capabilities/chat.py:build_chat_prompt(context)` → messages 列表；需要看裁了什么、
  还剩多少字符时用 `build_chat_prompt_with_diagnostics(context)`，它返回
  `ChatPromptDiagnostics`（分区级取用与裁剪记录），供离线断言与 `/bot status` 类排查。
- 输入 `ContextBundle` 是**唯一契约**：定义在
  `domains/core/contracts/character.py`，由
  `character/providers.py:build_character_context_provider` 造出的
  `FileCharacterContextProvider` 现拼（人格正文、档位态度、心情描述、称谓指令、
  管理名册、记忆/知识/时梗/梗图检索片段）。
- 分区渲染的小函数都在 chat.py 内且**只服务这一个装配口**：`_memory_lines`、
  `_history_lines`、`_knowledge_lines`、`_trend_lines`、`_temporal_lines`、
  `_glossary_lines`、`_relationship_lines`、`_emotion_lines`、`_shared_group_lines`、
  `_meme_search_lines`、`_time_window_summary_section`。预算工具 `_budgeted_lines` /
  `_bullet_lines` / `_clip_text` 是唯一裁剪出口。
- 跨板块依赖只走参数：模型侧预算钳制在 B02 的 `model_router`（输入超限从最旧非 system
  轮丢起），人格正文来源见 [人格源与运行副本一致性](../persona-context/persona-sync.md)。
- 外部只准调 `build_*` 与 `resolve_*` 系函数；分区渲染私有函数不得跨文件引用
  （`_conventions` 第二节私有函数规则）。

## 开关与参数

- 决定「装什么」的键：`bot_persona_files`、`bot_knowledge_files` +
  `bot_knowledge_max_chunks`/`bot_knowledge_chunk_chars`/`bot_knowledge_top_k`、
  `bot_history_*`、`bot_memory_*`、`bot_trend_enabled`（时梗备注）、
  `bot_glossary_*`（梗/热词）、`bot_affinity_enabled`、`bot_mood_enabled`。
- 决定「怎么装」的键：`bot_persona_action_brackets`（动作括号规范是否进正文指令）、
  `bot_persona_versioned_injection`（缺省 False：人格版本库注入路径代码已在、
  开关默认关、线上仍走文件正文，零变更）。
- 决定「装多少」：`bot_chat_max_input_tokens` / `bot_chat_max_output_tokens`，
  以及模块内地板常量 `MIN_CHAT_PROMPT_BUDGET`（低于此预算直接走运维句而不是硬发）。
  裁剪提示句 = `TRUNCATION_NOTICE` / `USER_MESSAGE_TRUNCATION_NOTICE`，是常量不是配置。
- 全部键的权威口径与热改性见 `docs/config-catalog-full.md`（生成物）。

## 失败时看到什么

- 某一分区的 provider 抛异常：该分区留空 + 一行 warn 日志，其余分区照常渲染
  （人格自守优先于信息完整）。
- 人格正文整体读不到：不再拼提示词，直接走人格失败话术池（见
  [失败与降级话术池](failure-copy-pools.md)），不会出现「没有人设的空人格回复」。
- 预算不足：先裁分区再裁历史；裁到低于地板预算时整条降级为运维句，绝不为省字符
  删掉安全与称谓指令。
- 时间窗总结（「总结最近 N 分钟」形态）超字符上限：截断并附提示句，不静默丢内容。

## 测试与验收

`tests/test_persona_prompt_and_memory.py`（分区内容与记忆注入）、
`tests/test_chat_token_limit.py`（预算裁剪与地板）、`tests/test_persona_injection_v21.py`
（版本库注入胶水，含 fail-open 回退）、`tests/test_chat_provider_chain.py`（provider 链）、
`tests/test_v21r2_content_probe.py`（内容探针）。
真机：`docs/acceptance-manual.md` §6.6.1；空分区与分区顺序的肉眼核对可在
`/bot status` 与错误诊断卡的配置快照白名单段看到。
