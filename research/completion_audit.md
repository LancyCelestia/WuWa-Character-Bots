# 研究完成审计

## 审计范围

目标：下载合适的 NoneBot 插件，分析它们和相关 AstrBot/GsCore 代码的架构，研究解析、抓取、返回、提交、输入、输出等元素，决定结构、组织和算法，并提出额外能力，包括网页编码、ACG 推荐、总结、同人推荐和 GScore 游戏查询。

本审计只覆盖研究/设计目标，不声称自定义 NoneBot 插件已经实现。

## 证据摘要

| 证据 | 当前状态 |
| --- | --- |
| NoneBot 源码 | 第一批和第二批共 70 个 wheel、70 个解压源码目录。 |
| 官方商店快照 | 2026-07-06 从 `https://registry.nonebot.dev/plugins.json` 保存 903 条。 |
| GsCore/GScore 源码 | 加入 `ZZZeroUID_ZZZure` 后共 12 个本地仓库。 |
| AstrBot 本地插件 | 24 个本地插件目录已做结构清单和矩阵分析。 |
| 主报告 | 架构报告、插件矩阵、AstrBot 矩阵、能力 backlog、实现补充、来源路径索引、registry 扫描。 |

## 需求审计

| 需求 | 状态 | 证据 | 说明 |
| --- | --- | --- | --- |
| 从官方商店和相关来源识别合适 NoneBot 插件 | 完成 | `research/candidate_plugins.md`, `research/official_registry_relevance_scan.md` | 按需求类别筛选，不下载全部 903 条。 |
| 下载合适插件源码 | 完成 | `research/downloaded_sources.md` | 70 个 wheel 和 70 个源码目录已记录。 |
| 逐个分析下载的 NoneBot 插件 | 完成 | `research/plugin_analysis_matrix.md` | 证据深度有 deep/sampled/structural，适合架构研究。 |
| 检查本地 AstrBot 插件 | 完成 | `research/astrbot_plugin_sources/inventory.md`, `research/astrbot_plugin_analysis_matrix.md` | 24 个非缓存/非备份目录均有分析。 |
| 对比插件结构、组织、算法 | 完成 | `research/architecture_report.md`, `research/implementation_design_supplement.md` | 已形成统一运行时规则和实现门禁。 |
| 分析解析/输入/输出/返回流 | 完成 | `docs/specs/*.md`, `architecture_report.md` | 明确 capability 返回结构化结果，不直接发送。 |
| 分析 fetch/crawl/subscription | 完成 | `implementation_design_supplement.md`, `media-source-pipeline.md` | 大规模同人和重托管按风险后置。 |
| 分析提交/反馈/错误语义 | 完成 | `input-output-contracts.md`, `runtime-parameter-flow.md` | 定义 queued、private fallback、blocked、retry、final failure。 |
| 决定结构和组织 | 完成 | `architecture_report.md` | 第一实现应从统一 runtime shell 开始。 |
| 决定关键算法/模式 | 完成 | parser registry、Bison scheduler、OutputPro、AntiPromptInjector、ai_groupmate、GsCore bridge | 已转为核心 specs。 |
| 提出额外能力 | 完成 | `bot_capability_backlog.md` | 覆盖网页编码、ACG、总结、同人、游戏、生活工具。 |
| 覆盖网页编码 | 完成，作为设计/backlog | `bot_capability_backlog.md` | 放在私聊/管理员和工具门禁后。 |
| 覆盖 ACG 推荐 | 完成 | `bot_capability_backlog.md`, `plugin_analysis_matrix.md` | 推荐依靠来源和排名，不靠纯 LLM。 |
| 覆盖聊天/新闻/视频/文章总结 | 完成，作为架构/backlog | `summary_group`, `chatrecorder`, parser/search 参考 | 具体实现依赖 adapter。 |
| 覆盖同人推荐 | 完成，作为策略/backlog | `bot_capability_backlog.md` | 默认私聊和命令触发。 |
| 覆盖 GScore/GsCore 游戏查询 | 完成 | `implementation_design_supplement.md`, `gscore_sources` | 首个 bridge 只允许公共 allowlist。 |
| 给出第一实现范围 | 完成 | `architecture_report.md`, `implementation_design_supplement.md` | 实现本身是下一阶段。 |

## 最终研究决策

目标架构：

```text
IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord
```

第一个自定义 NoneBot 插件应是统一运行时和策略壳，而不是巨型功能包。它只需要证明一个 LLM adapter、一个 parser、一个手动总结命令、一个天气/公共告警、一个公共游戏/wiki 命令、集中渲染和集中输出安全能跑通。

## 剩余工作属于实现阶段

- 编写运行时契约模型和测试。
- 搭建本地 NoneBot 插件骨架。
- 选择第一个 LLM provider 和 persona profile。
- 明确 OneBot/NapCat/QQ 部署假设。
- 实现第一批低风险 adapter。
- 账号、QZone、旅行、同人自动化前先做加密密钥存储。
- 将 GsCore 公共 allowlist 写成代码。
