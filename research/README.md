# 研究索引

本目录保存统一 NoneBot 角色机器人项目的证据、分析矩阵和实现建议。当前研究/设计阶段已经完成；后续实现应遵守这些文档和 `docs/specs/`，不要从单个参考插件孤立开写。

## 主文档

| 文档 | 用途 |
| --- | --- |
| `architecture_report.md` | 主架构报告：可复用模式、统一运行时、优先级、防打扰规则和实现里程碑。 |
| `implementation_design_supplement.md` | 面向实现的补充：fetch/crawl 策略、投递反馈、GsCore 来源选择、运行时模型和实现门禁。 |
| `../docs/specs/runtime-parameter-flow.md` | 标准运行时参数流和阶段契约。 |
| `../docs/specs/input-output-contracts.md` | 外部输入、能力输入、LLM 上下文、fetch、输出、发送、回执、审计校验规则。 |
| `../docs/specs/auto-send-capability.md` | 自动消息/邮件发送的草稿、预览、确认、收件人解析、个性化、发送、回执和审计。 |
| `../docs/specs/character-intelligence-and-knowledge.md` | 情绪、记忆、人设稳定、说话方式、知识库/RAG 输入契约。 |
| `../docs/specs/media-source-pipeline.md` | 媒体 parser、订阅、卡片渲染、推送和 source-to-send 参数流。 |
| `plugin_analysis_matrix.md` | 下载的 NoneBot 插件、GsCore/GScore 仓库、AstrBot 参考和第二批候选的逐行分析。 |
| `astrbot_plugin_analysis_matrix.md` | 本地 24 个 AstrBot 插件目录的逐插件分析。 |
| `bot_capability_backlog.md` | 聊天、解析、总结、天气、生活工具、ACG 推荐、同人、网页编码、游戏能力 backlog。 |
| `official_registry_relevance_scan.md` | 2026-07-06 NoneBot 官方 registry 扫描和第二批候选理由。 |
| `candidate_plugins.md` | 第一批候选插件列表。 |
| `downloaded_sources.md` | 下载 wheel、解压源码、GsCore/GScore 仓库和 registry 快照的本地路径。 |
| `completion_audit.md` | 按需求逐项审计研究阶段状态，并区分后续实现工作。 |

## 来源清单

| 路径 | 内容 |
| --- | --- |
| `nonebot_plugin_sources/_downloads` | 第一批 NoneBot wheel。 |
| `nonebot_plugin_sources/extracted` | 第一批解压源码。 |
| `nonebot_plugin_sources/_downloads_second_batch` | 第二批官方商店 wheel。 |
| `nonebot_plugin_sources/extracted_second_batch` | 第二批解压源码。 |
| `nonebot_plugin_sources/structure_index.json` | 第一批结构索引。 |
| `nonebot_plugin_sources/second_batch_structure_index.json` | 第二批结构索引。 |
| `nonebot_plugin_sources/official_registry_plugins_2026-07-06.json` | 2026-07-06 官方 registry 快照，共 903 条。 |
| `gscore_sources` | GsCore/GScore 相关仓库的本地浅克隆。 |
| `gscore_sources/github_repo_status_2026-07-06.json` | 选定 GsCore/GScore 仓库的 GitHub 状态快照。 |
| `astrbot_plugin_sources/inventory.md` | 本地 AstrBot 插件结构清单。 |

## 高置信方向

构建统一运行时，而不是一堆独立插件抢着回复：

```text
IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord
```

关键规则：

- 能力适配器返回结构化结果，不直接发送。
- 群聊保守且 opt-in；私聊可以更温暖，但必须有同意和隐私边界。
- 抓取内容、记忆、搜索结果、聊天记录、桥接输出都是不可信事实。
- 所有输出经过人格、安全、隐私、防刷屏、渲染和最终发送检查。
- 情绪、记忆、人设、知识是上下文服务，不覆盖运行时策略，不直接发送。
- 媒体 parser 和订阅先归一化来源数据，再渲染；不能直接推送。
- 知识导入、parser registry、订阅命令、卡片编译、音乐 metadata、自动发送草稿、回执都在 `docs/specs/` 中定义。
- GsCore/GScore 作为相邻服务桥接，不直接并入自定义运行时。

## 文档权威顺序

如果文档之间发生漂移：

1. `docs/specs/*.md` 管字段、模型、参数流和验收测试。
2. `research/implementation_design_supplement.md` 管实现门禁和来源选择。
3. `research/architecture_report.md` 管系统方向和模块划分。
4. `plugin_analysis_matrix.md` 等矩阵只作为证据，不直接成为新需求。
5. `progress.md` 和 `findings.md` 是历史记录和研究笔记。

## 建议下一步

实现 Milestone 0/1：

1. 本地 NoneBot 运行时插件骨架。
2. 运行时契约模型。
3. 策略门、审计日志、输出收口。
4. 一个安全 LLM adapter。
5. 一个低风险 parser，一个总结命令，一个天气或公共游戏/wiki 命令。
