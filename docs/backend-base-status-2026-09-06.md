# 后端真实运行底座状态与未完成清单

> 日期：2026-09-06
> 当前目标：先保证 NoneBot/NapCat/OneBot 的基础聊天底座可运行，再扩展 Prompt、世界观、记忆和工具系统。
> 约束：人格源文件、世界观源文件、Runtime 活动数据不自动改写、迁移或删除；Git 不推送。

## 1. 当前已经存在的主聊天链路

```text
NapCat / OneBot V11 WebSocket
  -> NoneBot OneBot Adapter
  -> NoneBot Event
  -> _incoming_from_nonebot_event()
  -> IncomingMessage
  -> RouteDecision
  -> PolicyEvaluation / BotDecision
  -> chat capability
  -> RuntimePipeline
  -> CapabilityResult
  -> SendRequest
  -> InMemory/SQLite SendQueue
  -> _deliver_transport_send_request()
  -> sender.onebot.send_onebot_v11()
  -> OneBot API
  -> NapCat / QQ
```

当前对应代码：

- NoneBot 初始化、适配器注册：`bot.py`
- 事件转换：`plugins/bot_unified_runtime/__init__.py:_incoming_from_nonebot_event`
- 策略和中央流水线：`plugins/bot_unified_runtime/runtime/pipeline.py`
- OneBot 消息段和发送：`plugins/bot_unified_runtime/sender/onebot.py`
- 发送队列：`plugins/bot_unified_runtime/sender/queue.py`
- 回执：`plugins/bot_unified_runtime/sender/receipts.py`
- 失败重试 worker：`plugins/bot_unified_runtime/sender/worker.py`

## 2. 已验证的底座能力

| 能力 | 状态 | 证据 |
|---|---|---|
| NoneBot 初始化 | 已验证 | `startup-smoke` |
| OneBot Adapter 注册 | 已验证 | `startup-smoke` |
| 统一插件加载 | 已验证 | `startup-smoke`，当前 20 个 matcher |
| 事件转 `IncomingMessage` | 已有实现 | `_incoming_from_nonebot_event` |
| 真实 LLM provider | 已验证 | `chat-smoke` 返回 `llm_status=ok` |
| 控制台真实聊天 | 已验证 | `console -Message` 返回真实模型回复 |
| RuntimePipeline | 已验证 | `backend-smoke` / `chat-smoke` |
| 人格和知识上下文读取 | 已验证 | `persona-smoke` / `context-smoke` |
| OneBot 消息段构造 | 已验证 | `transport-smoke` |
| Fake OneBot 投递 | 已验证 | `transport-smoke` |
| 真实 NapCat 连接 | 未验证 | 当前 `napcat_connected=false` |
| 真实 QQ 消息发送 | 未验证 | 当前没有实机测试群和在线 bot |

## 3. 当前尚未完成的底座工作

### 3.1 统一消息进入

- 不同 handler 仍然分散在大型 `__init__.py` 中。
- 还没有独立的 `IngressGateway` 类，事件标准化、去重、来源标记、幂等处理尚未形成单独合同。
- OneBot、Telegram、Mail 虽然都能转换为 `IncomingMessage`，但部分平台字段仍由 handler 内部自行判断。
- 没有统一的事件幂等表/去重服务覆盖所有适配器。
- 没有统一的入站原始事件审计快照；当前主要记录安全字段和运行日志。
- 没有统一的输入信任标签、污点标签和外部内容隔离层。

### 3.2 统一消息处理

- `RuntimePipeline` 已存在，但仍有部分业务能力绕过它或在 handler 内构造独立流程。
- 没有独立的中央 `DecisionEngine`，当前路由、权限、能力选择仍分散在 matcher 和路由函数中。
- 没有正式的 `ContextCompiler`。
- Prompt 仍然以现有人格原文和动态上下文拼装为主；结构化 FactCard/AnswerPlan 尚未接入。
- Prompt Preview 已实现，但 approved digest 尚未强制接入 live LLM。
- 人格 Prompt 重构尚未开始，且必须保持人格源文件只读。
- 世界观 claim graph、实体关系、事实冲突处理尚未实现。
- 长时记忆候选审核、冲突解决、回滚和删除闸门尚未实现。
- 群聊公共 SceneState、话题线程和重复短语检测尚未接入主回复链。

### 3.3 统一消息出发

- 正常聊天主要经过 `RuntimePipeline -> SendRequest -> sender`，但不是所有边缘能力都经过统一出口。
- 文件接收/调试/文档导出 handler 仍存在直接 `bot.send()`。
- 部分文件上传流程直接调用 `bot.call_api()`，没有统一的发送回执、幂等键和审计合同。
- 订阅推送有自己的投递分支，与普通聊天发送路径仍存在重复逻辑。
- 没有统一的 `UnifiedDeliveryGateway` 类，适配器选择和发送策略仍部分分散。
- 没有统一覆盖 text/image/json/mixed/file/forward 的出站 DTO 合同。
- “发送超时但服务端可能已成功”的 result-unknown 状态虽有局部处理，但还没有全局幂等恢复流程。
- 所有发送副作用还没有统一的用户/群/管理员确认策略。

### 3.4 NapCat/OneBot 实机运行

- 已有 OneBot V11 Adapter 配置和重连日志限流。
- 已有 fake transport smoke。
- 尚未完成：
  - 测试 QQ 和测试群；
  - NapCat WebSocket 实际连接；
  - 私聊真实发送；
  - 群聊真实发送；
  - 图片/JSON/合并转发真实发送；
  - NapCat 重启重连；
  - OneBot API 超时和 retcode 失败恢复；
  - 真实发送后的回执、审计和重复发送检查。

## 4. 尚未完成的知识、记忆和防御系统

- 世界观原始 Markdown 尚未离线编译为实体/关系/事件/事实图。
- 向量检索仍有部分直接片段注入行为。
- 尚未完成 Claim-based RAG。
- 尚未完成 EvidenceLedger。
- 尚未完成来源权威等级、时间有效期和事实冲突组。
- 尚未完成搜索结果到事实卡片的二次压缩。
- 尚未完成网页正文中的间接 Prompt Injection 隔离。
- 尚未完成用户输入、网页、搜索、记忆、群聊、工具输出的统一 TrustLevel/TaintFlag。
- 尚未完成输出声明校验，无法系统判断模型是否凭空新增世界观事实。
- 尚未完成记忆候选 `propose -> policy -> approve -> commit` 流程。
- 尚未完成记忆覆盖、删除、撤销和回滚审计。
- 尚未完成群聊公共话题状态与个人记忆的强隔离。
- 尚未完成“多人连续复读/起哄”识别与低成本 SceneBrief 生成。

## 5. 尚未完成的工具系统

项目已经有聊天、知识、搜索、天气、维基、Epic、音乐、文件、导出、视觉、订阅等能力，但尚未形成统一 ToolCatalog。

尚未完成：

- 工具名称和版本合同；
- JSON Schema 输入校验；
- 输出 Schema 校验；
- 工具权限矩阵；
- 只读/低风险/高风险分级；
- 网络预算、Token 预算、超时和重试；
- 幂等键；
- 工具结果信任标签；
- 工具调用审计；
- 副作用工具二次确认；
- 文件、配置、记忆、发送等危险操作隔离；
- 工具失败后的确定性降级策略。

## 6. 尚未完成的外部服务和控制面

- Tavily/You.com/LangSearch/TinyFish 适配已实现本地协议层，但真实账户 key、额度、区域 endpoint 和生产 SLA 尚未逐家实测。
- 没有正式 Control Plane API。
- 没有 Provider/Model/Usage/Balance API。
- 没有搜索 provider 健康状态 API。
- 没有 Prompt artifact 查询/批准 API。
- 没有 Web UI。
- 没有公网认证、审计、CSRF、设备撤销和危险操作确认。
- 没有结构化 LLMCallRecord 长期事实源。
- 没有统一余额查询 adapter。

## 7. 尚未完成的迁移和运维

- 源码区 `data/` 运行态残留尚未完成复制验证迁移。
- 没有自动生成 runtime migration manifest/hash 报告。
- 没有 SQLite integrity_check/foreign_key_check/schema/row-count 迁移脚本。
- 没有一次整合归档包和可恢复 README。
- Runtime 目录写权限尚未在当前受限环境验证；Prompt artifact 默认路径曾因权限拒绝。
- 没有数据库 owner/retention/backup policy 的可执行检查。
- 没有统一 Windows PowerShell、pwsh、Python 版本矩阵回归。
- 全量测试树、缓存和临时目录边界仍需治理。

## 8. 当前执行优先级

### P0：真实底座

1. NapCat/OneBot 实机连接和发送闭环。
2. 统一 IngressGateway。
3. UnifiedDeliveryGateway。
4. 真实消息幂等和回执。
5. `backend-base-smoke` 离线基座验收。

### P1：可靠上下文

1. Prompt artifact/preview 接入真实调用前审计。
2. Trust/Taint 合同。
3. Claim-based WorldModel/RAG。
4. Memory write gate。
5. Group PublicSceneState。

### P2：外部能力

1. ToolCatalog。
2. 搜索 EvidenceLedger。
3. 余额/用量/Control Plane API。
4. UI。
5. 长尾插件和完整订阅。

## 9. 本文维护规则

每完成一个底座合同，必须同步更新：

- 本文“已验证的底座能力”；
- 本文“尚未完成的底座工作”；
- `task_plan.md`；
- `findings.md`；
- `progress.md`；
- 对应 smoke 和测试命令。

不得只改代码不改文档。
## 10. 2026-09-06 网关增量

- 新增 `runtime/ingress.py:IngressGateway`，主能力路径通过统一事件标准化边界进入 `IncomingMessage`。
- 新增 `sender/gateway.py:UnifiedDeliveryGateway`，主能力路径统一选择 OneBot/NoneBot sender，并统一回执记录回调。
- `backend-base-smoke` 已验证 NoneBot/plugin、startup、fake OneBot transport、backend pipeline 全部通过。
- 本次真实控制台聊天出现一次约 30 秒后返回“暂时没能稳定完成”的 provider 瞬态失败；不能视为 NapCat 失败，也不能视为真实 provider 稳定性已完成验收，需继续做超时/重试/实机测试。
- 文件接收/文档导出 handler 仍有直接 `bot.send()`/`bot.call_api()`，尚未迁移到 UnifiedDeliveryGateway。

## 11. 2026-09-06 统一出站增量结果

- `IngressGateway` 已接入主能力处理函数 `_run_capability_through_pipeline`。
- `UnifiedDeliveryGateway` 已接入 `_deliver_transport_send_request`，统一选择 OneBot/NoneBot sender 并记录 transport receipt。
- 文件接收/文档导出 handler 的文本成功/失败提示已改走 `_send_text_through_unified_pipeline`，不再直接 `await bot.send()`。
- 文件下载和上传仍必须调用 OneBot `call_api(get_file/download_file/upload_*)`，这是平台文件副作用，不属于普通文本出站；后续需要独立 `FileTransferGateway`、幂等和审计。
- 文档生成 handler 当前仍有专用 LLM provider 调用，尚未纳入统一 Prompt audit/approved digest；人格 Prompt 不在本阶段修改。
- 真实 NapCat/QQ 仍未连接，必须由用户启动 NapCat 后执行实机验收。

## 12. 2026-09-06 图片/表情消息路由修复

- 实机日志确认 image 事件被 NoneBot 收到，但原 `_is_plain_chat_event` 只接受文本 RouteKind.CHAT，图片/表情只经过 `meme_absorb` 监听后结束，导致没有回复。
- 新增 `contains_visual_message_segments()`；`image/face/mface/marketface/sticker` 进入聊天 matcher。
- 图片/表情没有纯文本时，入站标准化会生成内部占位文本，继续执行视觉 provider 或普通 LLM 兜底，不再静默丢弃。
- 相关回归：图片/表情路由 2 项、事件适配/视觉/统一网关共 23 项通过。
- 图片视觉分析依赖当前 `BOT_VISION_ENABLED`、视觉模型 registry 和可访问图片 URL；没有视觉模型时仍会进入聊天链，但只能返回无法识别图像的安全兜底。

## 13. 2026-09-06 图片实机验证

- 用户已确认图片消息能够正常回复。
- 图片接收 -> visual/chat route -> 视觉处理或 LLM 兜底 -> RuntimePipeline -> UnifiedDeliveryGateway -> OneBot/NapCat 出站闭环完成实机验证。
- QQ 表情/贴纸路由已通过代码测试；后续继续观察不同类型表情包和无可读 URL 图片的实机表现。
