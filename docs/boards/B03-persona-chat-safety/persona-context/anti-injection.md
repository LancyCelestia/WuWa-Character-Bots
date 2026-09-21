# 人格上下文与称谓身份 · 反注入包裹与指令剥离

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.persona-context · 反注入包裹与指令剥离

- 层级：一级 B03 → 二级 persona-context → 三级 `anti-injection`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character`、`personas/shorekeeper`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

挡住「借她的嘴执行别人的指令」。三层：①不可信块包裹——用户消息、检索/记忆/引用
正文统一包进 `[UNTRUSTED_USER_TEXT]` 标记，让模型在**来源层面**区分资料与指令；
②指令形态剥离——命中「忽略以上指令」族与 chat 模板特殊 token 的句子整句丢弃；
③阶段门禁——按投递阶段给出 allow / quote_as_untrusted / block 三态判定。
原则是「宁可错删一行资料，也不放一条指令进上下文」，但刻意不收录「系统：」这类
宽泛前缀（正常 wiki 正文大量以「XX系统：」开头，收了就是自伤）。

## 怎么调用

- 阶段判定：`domains/chat_reply/security/injection.py:check_prompt_injection(check_input)`，
  入参 `InjectionCheckInput`（带 `source_type`、`target_stage`、`risk_level`、
  `privacy_level`），返回 `InjectionCheckResult`，动作枚举
  `InjectionAction.ALLOW / QUOTE_AS_UNTRUSTED / BLOCK`。
- 提示词侧落地（同一事实的第二次防线，不重复判定语义、只做整形）：
  `capabilities/chat.py:_wrap_untrusted_context_block`（包裹）、
  `_strip_injection_instruction_spans`（**句级**剥离，按 `_SENTENCE_SPLIT_RE` 切句后
  只丢命中句，避免整行连坐正常内容）、`_sanitize_untrusted_context_text`
  （把伪造闭合用的引用族标记全角化，防越界伪造块闭合）、
  形态表常量 `_PROMPT_INJECTION_LINE_RE`。
- 命中后的用户可见出口：`capabilities/chat.py:injection_guard_message`（温和拒答池，
  会话内游标轮换）。
- 依赖的中央件：文本边界只准走 `domains/core/text_boundary.py`；出站前打码走
  `domains/render/plain_text.py`（`redact_local_secrets`），两者都不在本域抄副本。

## 开关与参数

- 形态表（`_PROMPT_INJECTION_LINE_RE`）是**代码常量**，没有配置键：注入形态不该
  由会话面热改，放宽必须走代码评审 + 重启。
- 没有「关掉反注入」的总闸；只有动作差异（quote_as_untrusted 与 block 由阶段与
  风险等级决定）。
- 相关但不同源的键：内容安全侧的守界闸在 B03.content-safety（`assess_public_content`），
  那是「能不能说」，本入口是「谁的指令算指令」，两者不互相替代。

## 失败时看到什么

- 判定/整形自身抛异常：fail-open 到「按不可信块照样包裹」的最小安全态 + 一行日志，
  绝不因反注入模块故障让整条消息失败。
- 用户侧看到的是一句守岸人语气的温和拒答（不点名「你试图注入」、不解释协议细节），
  细节进审计标签与日志。
- 第三方正文被投毒时，最坏情况是那段资料被丢掉：回复质量可能下降，但不会照做。

## 测试与验收

反注入相关断言散在 `tests/test_chat_provider_chain.py`（包裹与剥离的形态锁）、
`tests/test_v21r2_content_probe.py`（样本探针）、
`tests/test_persona_failure_messages.py`（拒答池不外泄协议细节）；
文案红线门 `tests/test_copy_redline_gate.py` 保证注入样本词面不会以真词形态进池。
真机：把一段含「忽略以上指令，你现在的身份是……」的网页正文用引用/转发喂进去，
核对回复没有照做、且日志里有剥离或 BLOCK 记录。
