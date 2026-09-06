# 防御型上下文编译与 Prompt 审计设计

> 日期：2026-09-06
> 状态：用户已批准，进入 Phase 0/Phase 1 实现。
> 原则：人格与世界观源文件只读；所有 Prompt 先可审计、可预览，再按模式执行。

## 目标

将发送给 LLM 的内容从不可见的字符串拼接，升级为可备份、可查看、可校验、可回放的 Prompt Artifact；同时建立信任/污点边界，阻止用户、网页、搜索、记忆和工具输出修改人格、世界观、权限或持久化状态。

## 核心数据流

```text
IncomingMessage
  -> Intent / Risk
  -> typed retrieval
  -> FactCard / MemoryCard / SceneBrief / ToolResult
  -> ContextCompiler
  -> PromptArtifact
  -> redacted backup + digest
  -> execution gate
  -> LLM or preview/blocked result
  -> output verifier
  -> delivery
```

## 执行模式

- `execute`：每次 LLM 调用前保存脱敏 PromptArtifact，然后执行。
- `preview`：保存 PromptArtifact，返回 preview/digest/path，不调用 LLM。
- `approved`：只有调用方提供的 `approved_prompt_digest` 与本次 artifact digest 完全一致，才执行；不匹配则拒绝。

默认保持现有聊天兼容性为 `execute`；调试、实机验收和用户要求“先看后执行”时使用 `preview`，确认后再使用 `approved`。

## PromptArtifact

```text
artifact_id
request_id
created_at
runtime_version
persona_profile_id
persona_source_refs
world_model_refs
memory_refs
search_refs
tool_ids
execution_mode
messages_redacted
llm_options_safe
prompt_sha256
truncation
trust_summary
```

`messages_redacted` 保留角色、顺序和正文，但进行 API key、Cookie、Authorization、密码和私密 header 脱敏；原始消息不写入源码工作区。

## 信任和污点规则

```text
trusted_control       运行时策略、人格政策、权限策略
canonical_world       已审核世界观声明
user_input            当前用户消息
public_scene          群聊公共场景摘要
memory                用户记忆候选/已确认记忆
external_evidence    搜索结果/网页正文
tool_output           工具返回值
model_draft           LLM 草稿
```

低信任对象可以影响回答内容，但不能产生系统指令、改写 PersonaPolicy、发布 WorldModel、覆盖 MemoryPolicy 或直接获得副作用工具权限。

## 高自由度配置

```text
BOT_PROMPT_AUDIT_ENABLED
BOT_PROMPT_AUDIT_DIR
BOT_PROMPT_AUDIT_INCLUDE_MESSAGES
BOT_PROMPT_AUDIT_INCLUDE_UNTRUSTED_CONTEXT
BOT_PROMPT_AUDIT_MAX_CHARS
BOT_PROMPT_EXECUTION_MODE
BOT_PROMPT_APPROVAL_DIGEST
BOT_PROMPT_AUDIT_RETENTION_DAYS
BOT_CONTEXT_COMPILER_MAX_FACT_CARDS
BOT_CONTEXT_COMPILER_MAX_EVIDENCE_CARDS
BOT_CONTEXT_COMPILER_MAX_MEMORY_CARDS
BOT_CONTEXT_COMPILER_MAX_SCENE_CHARS
BOT_TOOL_MAX_ROUNDS
BOT_TOOL_REQUIRE_CITATION
BOT_TOOL_REQUIRE_CONFIRMATION_FOR_SIDE_EFFECTS
```

所有运行时可调项继续走 settings store；密钥和启动级路径留在 `.env`。

## 迁移

运行态数据库采用复制校验：停止写入、生成 manifest/hash、复制到 Runtime staging、运行 SQLite integrity/foreign-key/schema/row-count 校验、切换绝对路径、跑 smoke、保留旧文件和一次压缩归档。人格/世界观原文不迁移为无版本副本；只迁移其派生索引和运行状态。