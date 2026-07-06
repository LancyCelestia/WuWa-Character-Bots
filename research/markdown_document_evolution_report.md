# Markdown 文档演进报告

## 1. 范围和证据

本文评估项目中的 Markdown、TXT 和说明类文件，回答三个问题：

1. 当前组织架构建议是否还有优化空间。
2. 当前算法和机制建议是否还能更精确、更可演进。
3. 当前需求实现命令是否足够清楚、可执行、可验证。

项目自有证据包括：

- `README.md`
- `COMMANDS.md`
- `pyproject.toml`
- `.env.prod`
- `task_plan.md`
- `findings.md`
- `progress.md`
- `docs/specs/*.md`
- `research/README.md`
- `research/architecture_report.md`
- `research/implementation_design_supplement.md`
- `research/bot_capability_backlog.md`
- `research/plugin_analysis_matrix.md`
- `research/astrbot_plugin_analysis_matrix.md`
- `research/official_registry_relevance_scan.md`
- `research/candidate_plugins.md`
- `research/downloaded_sources.md`
- `research/completion_audit.md`
- `research/astrbot_plugin_sources/inventory.md`

下载源码树里的第三方 Markdown/TXT 只作为参考证据，不直接当成本项目需求。

## 2. 总结结论

项目已经从“研究笔记”进化到“可实现规格”。当前最重要的优化不是继续扩展想法，而是用统一契约收束后续代码：

```text
IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord
```

主要改进已经落地：

- 根目录 `README.md` 说明了当前架构、命令入口、NoneBot/NapCat 边界和人格优先规则。
- `COMMANDS.md` 明确 `scripts/dev.ps1` 是统一开发和验证入口。
- `docs/specs/` 拆成五份核心规格：运行时参数流、输入输出、自动发送、人格/知识库、媒体来源流水线。
- `research/README.md` 说明文档权威顺序，避免未来文档漂移。
- `architecture_report.md` 从英文研究报告变成中文架构报告。
- `implementation_design_supplement.md` 从研究补充变成实现门禁说明。

人话版：项目现在知道自己要怎么长了。后续写代码时，不应该让每个插件各自决定怎么回、怎么发、怎么审计，而要让所有能力都通过统一运行时。

## 3. 当前文档组织

### 已形成的层级

| 层级 | 文件 | 职责 |
| --- | --- | --- |
| 入口 | `README.md` | 给人快速理解项目、命令、架构和下一步。 |
| 命令 | `COMMANDS.md` | 开发、启动、验证入口。 |
| 核心规格 | `docs/specs/*.md` | 字段、参数流、输入输出、验收测试。 |
| 架构报告 | `research/architecture_report.md` | 系统方向、模块划分、优先级。 |
| 实现补充 | `research/implementation_design_supplement.md` | 实现门禁、fetch/send/GsCore 选择。 |
| 证据矩阵 | `research/plugin_analysis_matrix.md` 等 | 插件来源和逐项证据。 |
| 计划/历史 | `task_plan.md`, `findings.md`, `progress.md` | 研究过程和当前结论。 |

### 权威顺序

如果文档冲突：

1. `docs/specs/*.md` 管字段和实现契约。
2. `research/implementation_design_supplement.md` 管实现门禁和来源选择。
3. `research/architecture_report.md` 管系统方向。
4. 插件矩阵和下载清单只作为证据。
5. `progress.md` 和 `findings.md` 是历史和研究笔记。

## 4. 架构建议

当前架构建议已经足够明确：

- 所有外部事件先归一化为 `IncomingMessage`。
- 策略门先检查权限、群/私聊、冷却、风险和隐私。
- 能力插件返回 `CapabilityResult`，不直接发送。
- 人格、记忆、知识库、情绪和安全审查一起塑造输出。
- 渲染层生成文本、卡片、图片、合并转发或 fallback。
- 发送层唯一负责具体 transport，并返回 `DeliveryReceipt`。
- 审计记录所有阻断、失败、转私聊、重试和发送结果。

可继续优化的点：

- Milestone 0/1 需要把 “不能直接发送” 写成自动测试。
- 每个模块都要声明输入、输出、依赖和失败模式。
- 后续新增插件时必须先实现 adapter，而不是让插件绕过运行时。

## 5. 算法和机制建议

当前文档已经把模式从“灵感”推进到了“契约”：

- Parser：`ParserRegistry`、keyword/regex、canonical URL、短链、share card、fallback。
- Source：`FetchRequest`、`FetchResult`、rate limit、retry、cache、robots。
- Subscription：`SubscriptionSpec`、cursor、jitter、task gap、digest、去重。
- Rendering：`CardRenderModel`、`RenderRequest`、`RenderArtifact`、三阶 fallback。
- Send：`SendRequest`、`DeliveryReceipt`、状态机、重试、幂等。
- Character：`PersonaProfile`、`ToneProfile`、`EmotionSignal`、`MemoryRetrievalResult`、`RetrievalResult`。
- Knowledge：`KnowledgeIngestionRequest`、`NormalizedDocument`、`KnowledgeChunk`、`IngestionReceipt`。

还应在实现期补的测试：

- parser 不支持链接时不 fetch。
- 失败 fetch 不推进 cursor。
- 群聊重复输出被 dedupe。
- 私密数据在群里被转私聊或阻断。
- LLM 不能决定发送。
- provider 不能创建 `SendRequest`。
- transport 失败必须生成 `failed_retryable` 或 `failed_final`。

## 6. 命令入口评估

当前统一入口：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 help
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 install
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 dev
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify
```

命令设计是合理的，因为它：

- 把文档检查、插件检查、测试、lint、typecheck 集中在一个入口。
- 当前阶段缺少插件/测试/ruff/mypy 时给出警告或明确失败，不假装通过。
- `docs-check` 会保留必要英文锚点，防止中文化破坏契约。

后续实现后应收紧：

- `plugin-check` 要求统一 runtime 插件存在。
- `smoke` 验证插件能被 NoneBot 加载。
- `verify` 强制运行契约测试。
- 有 ORM schema 后再加入迁移命令。

## 7. NoneBot / NapCat 规范建议

当前正确边界：

- NoneBot 负责插件加载、事件分发和 adapter 抽象。
- NapCat 作为 OneBot V11 实现，不是业务能力。
- 入站事件先转成 `IncomingMessage`。
- 出站内容先成为 `SendRequest`，再由 sender/transport adapter 转成 OneBot/NapCat 消息段。
- capability、parser、knowledge、memory provider 都不能直接调用 `event.send`、`bot.send_*` 或 NapCat API。

这能保证未来如果接入 Mail、Console、Telegram、Discord、Feishu，也不需要重写业务能力。

## 8. 人格和插件效果规则

普通自然语言回复：

- 依赖 `PersonaProfile`。
- 依赖 `ToneProfile`。
- 读取允许范围内的 memory。
- 检索知识库和来源。
- 用情绪信号调整语气。
- 输出后通过 OOC、安全、隐私、防刷屏审查。

插件效果：

- 链接解析、媒体卡、游戏/wiki 卡、订阅推送、音乐解析不让 LLM 直接生成。
- 走确定性 parser/source/render/send 流程。
- LLM 最多生成短说明或风格化 caption，不能替代事实来源。

## 9. 最终建议

下一步不要再扩大研究范围。应该按 Milestone 0/1 写代码：

1. 建立 `plugins/wuwa_unified_runtime`。
2. 写契约模型和测试。
3. 写 policy、audit、review、sender。
4. 接一个 LLM adapter。
5. 接一个 parser adapter。
6. 接一个低风险命令。
7. 用 `scripts/dev.ps1 verify` 做统一验证。

这条路线最小、可逆、可验证，也为未来插件和功能保留接口。
