# docs/ 文档索引（2026-09-12 整理后）

> 单一入口是 [HANDBOOK.md](HANDBOOK.md)：交接总账、现行事实、权威正文、归档执行记录都在里面。
> 维护规矩：**不再新建带日期的交接文档**，一切增量直接更新 HANDBOOK.md；文档过时后按 [workspace-archive-policy.md](workspace-archive-policy.md)（压缩 → 验证 → 移出）处理。
> 历史文档（旧交接 / 期报 / 已实施计划共 26 份 + 合并前 MASTER/full 原件）已归档至 `ChatBot_Archive\2026-09-12\docs-archive-2026-09-12.zip`（内含 manifest.md 逐份缘由清单）；git 历史亦可 `git log --follow -- docs/<文件名>` 回溯。**09-12 收口批再折算删除 5 份**（final 全账 → HANDBOOK §18，review-fixes/bgroup-verify 增量 → §三），原件同 zip+git 可溯。

## 交接与总账

| 文档 | 说明 |
|---|---|
| [HANDBOOK.md](HANDBOOK.md) | 单一活文档：Part 0（族谱终裁 / 现行事实 / 未完成总账 §三）+ Part II（权威正文 §1-§17 + §18 五波收尾全账） |

## 搭建与运维

| 文档 | 说明 |
|---|---|
| [napcat-setup.md](napcat-setup.md) | NoneBot + NapCat 连接 QQ 配置指南 |
| [acceptance-manual.md](acceptance-manual.md) | 验收与接入手册（人格对话 → NapCat → GsCore） |
| [external-runtime-access.md](external-runtime-access.md) | 外部运行时访问与工作区边界（AGENTS.md 按路径引用） |
| [workspace-archive-policy.md](workspace-archive-policy.md) | 工作区与归档规范（AGENTS.md 按路径引用） |
| [ai-kb-operations-manual.md](ai-kb-operations-manual.md) | 运维知识手册（写入机器人向量知识库的投喂件） |

## 配置与路由

| 文档 | 说明 |
|---|---|
| [ai-setup-knowledge-pack.md](ai-setup-knowledge-pack.md) | AI 搭建与配置知识包（可整体喂给 AI） |
| [config-catalog-full.md](config-catalog-full.md) | 全量配置键目录（上文的 §6 完整展开版） |
| [route-matrix.md](route-matrix.md) | 全问法路由矩阵（base_router → capability 权威矩阵） |
| [search-api-adapters-2026-09-06.md](search-api-adapters-2026-09-06.md) | 搜索 API 适配与本地配置（COMMANDS.md 引用；LangSearch 真实 key 验收仍开放） |

## 功能设计（现行）

| 文档 | 说明 |
|---|---|
| [affinity-design.md](affinity-design.md) | 好感度数值规范（`affinity.py` 代码注释指向的唯一权威描述；v4 线性改版权威规格，`572bfff` 重写） |
| [standard-parse-card-acceptance.md](standard-parse-card-acceptance.md) | 解析信息卡验收标准 |
| [db-owners.md](db-owners.md) | 数据库 owner 清单（26 库文件 → owner → 建表迁移点 → 清理策略） |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | 第三方出处与 MIT 许可声明唯一保留地（**勿删**） |
| [control-plane-provider-and-usage-requirements-2026-09-05.md](control-plane-provider-and-usage-requirements-2026-09-05.md) | Control Plane / Provider / 用量监控需求（HANDBOOK §三 B4/B5 未实现功能的需求源） |

## 架构规格（design/，先成文后实现）

> 对应 HANDBOOK §三 B2/B3/B4/B5 长线项；实现前开放问题需用户裁决（`2e0393d`/`b15241e`）。

| 文档 | 说明 |
|---|---|
| [design/central-decision-engine.md](design/central-decision-engine.md) | B2 中央决策引擎设计规格（35 matcher 拓扑 / IngressNormalizer-Engine-Dispatcher / 四阶段迁移） |
| [design/file-transfer-gateway.md](design/file-transfer-gateway.md) | B3 统一文件出站网关设计规格（FileSource → FileTicket → 四通道 deliver → 回执） |
| [design/control-plane-api.md](design/control-plane-api.md) | B4 控制面 API + SakuraFrp 公网设计规格（本机 8742 默认关 / Bearer / 五态断路器 / M1-M6） |
| [design/llm-billing-ledger.md](design/llm-billing-ledger.md) | B5 LLM 计费账本设计规格（三表 DDL / PricingService 双轨统一 / BalanceAdapter / M1-M5） |
