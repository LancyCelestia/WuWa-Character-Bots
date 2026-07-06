# WuWa-Character-Bots

这是一个面向鸣潮角色机器人、ACG/游戏助手、媒体解析和自动发送能力的统一 NoneBot 项目。

当前仓库已经进入 Milestone 0 实现阶段：研究和规格设计已经完成，`plugins/wuwa_unified_runtime` 提供了统一运行时插件骨架、契约模型、策略门、审查/渲染、内存发送回执、审计、人格/知识/provider 接口、parser registry 和 auto-send draft parser。

后续不要从单个插件文件直接开写，而是继续遵守统一命令入口、运行时契约、人格/记忆/知识约束和发送审计链路。

## 开发命令入口

本项目在 Windows 上统一使用 `scripts/dev.ps1`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 help
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 install
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify
```

完整命令矩阵见 [COMMANDS.md](COMMANDS.md)。

## 当前架构基线

高置信运行时链路如下，英文类型名是后续代码和测试要保留的锚点：

```text
IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord
```

人话解释：

1. `IncomingMessage` 把 NoneBot / OneBot / NapCat / Mail / Console 等适配器事件规整成统一输入。
2. `PolicyEvaluation` 先判断权限、群/私聊策略、冷却、隐私、风险和是否允许回复。
3. `BotDecision` 决定调用哪个能力、是否回复、最多发几条、走即时/队列/摘要/私聊回退/管理员确认。
4. 能力插件只返回 `CapabilityResult`，不能自己调用发送 API。
5. 人格、记忆、知识库、情绪感知和安全审查一起进入 `ReviewResult`。
6. `RenderedOutput` 把文本、卡片、图片、合并转发等输出准备好。
7. `SendRequest` 是唯一的发送入口。
8. `DeliveryReceipt` 记录是否排队、已发、跳过、失败、被拦截或转私聊。
9. `AuditRecord` 记录完整审计，方便以后修问题。

核心原则：能力适配器、来源适配器、解析器、知识库、人格服务和记忆服务都不能直接发送消息。它们只提供结构化结果，最终发送只能通过 `SendRequest -> DeliveryReceipt -> AuditRecord`。

## 核心规格文档

- [运行时参数流](docs/specs/runtime-parameter-flow.md)
- [输入输出契约](docs/specs/input-output-contracts.md)
- [自动发送能力](docs/specs/auto-send-capability.md)
- [人格智能与知识库](docs/specs/character-intelligence-and-knowledge.md)
- [媒体来源流水线](docs/specs/media-source-pipeline.md)

这些文档定义消息、策略、人格上下文、记忆读取、知识检索、媒体解析、能力结果、审查结果、渲染输出、发送请求、回执和审计如何在统一运行时里传递。

## 人格优先与插件例外

普通自然语言回复必须依靠已配置的人格设定、角色性格、说话方式、情绪感知、记忆数据库和知识库来生成。也就是说，机器人“怎么说话”和“记得什么”不是临场乱编，而是由 `PersonaProfile`、`ToneProfile`、`MemoryRetrievalResult` 和 `RetrievalResult` 明确传入。

但插件效果不能让大模型直接编。例如链接解析、媒体卡片、游戏/wiki 卡片、订阅推送、音乐平台解析等，必须走确定性流程：解析链接或命令，抓取来源数据，归一化为结构化模型，编译卡片，渲染图片或文本 fallback，然后发送。大模型最多生成安全的小标题或人格化短说明，不能替代解析器、渲染器和来源事实。

已参考的本地 parser 插件路径：

```text
C:\Users\LancyCelestia\.astrbot\data\plugins\astrbot_plugin_parser
```

该插件的可复用思想是：`BaseParser` 自动注册、`@handle` 关键词/正则匹配、`ParseResult` 归一化、订阅去重、卡片渲染、发送计划和 fallback。新项目会吸收这些分层，但最终发送会收口到统一 sender/receipt/audit。

## NoneBot 与 NapCat 边界

项目通过 `pyproject.toml` 配置 NoneBot：

- 本地插件目录：`plugins`
- 内置插件：`echo`
- 适配器：OneBot V11、Console、Mail
- 支撑插件：status、apscheduler、localstore、alconna、filehost、orm、htmlkit

NapCat 按 OneBot V11 实现接入时，建议使用数组消息段格式。Incoming 事件中的 `message`、`raw_message`、`user_id`、`group_id`、`message_type` 等字段先归一化到 `IncomingMessage`；Outgoing 的文字、图片、合并转发等由 `SendRequest.content` 转换为 OneBot/NapCat 消息段。发送 API 的 `retcode`、`message_id` 和异常必须映射到 `DeliveryReceipt`，不能只看能力执行是否成功。

## 研究索引

研究证据、插件分析矩阵、架构报告和实现建议见 [research/README.md](research/README.md)。

当前 M0 已完成一个很窄的统一运行时插件骨架。下一步建议补 SQLite repository、真实 OneBot/NapCat transport adapter、一个低风险媒体 source adapter、公共游戏/wiki 能力，以及更完整的 NoneBot 加载 smoke 检查。
