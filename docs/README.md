# docs/ 文档索引（2026-09-14 刷新）

> 单一入口是 [HANDBOOK.md](HANDBOOK.md)：交接总账、现行事实、权威正文、归档执行记录都在里面。
> 维护规矩：**不再新建带日期的交接文档**，一切增量直接更新 HANDBOOK.md；文档过时后按 [workspace-archive-policy.md](workspace-archive-policy.md)（压缩 → 验证 → 移出）处理。
> 历史文档（旧交接 / 期报 / 已实施计划共 26 份 + 合并前 MASTER/full 原件）已归档至 `ChatBot_Archive\2026-09-12\docs-archive-2026-09-12.zip`（内含 manifest.md 逐份缘由清单）；git 历史亦可 `git log --follow -- docs/<文件名>` 回溯。**09-12 收口批再折算删除 5 份**（final 全账 → HANDBOOK §18，review-fixes/bgroup-verify 增量 → §三），原件同 zip+git 可溯。

## 交接与总账

| 文档 | 说明 |
|---|---|
| [HANDBOOK.md](HANDBOOK.md) | 单一活文档：Part 0（族谱终裁 / 现行事实 / 未完成总账 §三）+ Part II（权威正文 §1-§17 + §18-§27 批次全账）；**§27 最新：2026-09-15 日常助理批（此前 §24 六域批 / §25-§26 夜间审计批）** |
| [HANDOVER-2026-09-15.md](HANDOVER-2026-09-15.md) | **交接总报告（2026-09-15 用户 mandate 全量更正版，维护规矩的用户裁定例外件）**：统一架构文档 / 处理流程与流程图 / 九个统一（触发·自动回复·LLM 话术·参数·术语·权威链·门禁…）/ WebUI 需求与三阶段规格全量 / 当前真实状态快照。旧口径（26 渠道链/「17 条网关」/509 字段/72 topics）以此为准作废 |
| [handover-c-20260913.md](handover-c-20260913.md) | C 方向批次交接件（统一 UI/卡片主题 token/金融数据与图表/占卜历史卡适配）；本批 SDD 台账与评审报告存 `.superpowers/sdd/2026-09-12-shorekeeper-global-audit/`（git-ignored 工作台，不入库） |
| [issue-ledger-p2-p3.md](issue-ledger-p2-p3.md) | P2/P3 问题台账（2026-09-13 实战审计批）：AGENTS.md 第六部分是索引，本文件是逐条可执行详情（现象/位置/根因/修法/验收） |
| [perf-optimization-plan.md](perf-optimization-plan.md) | 性能优化全量档案：Phase 1 终态 + Phase 2 执行清单 + 五链路实测基线（渲染并发/等待预算等 Phase 2 的唯一执行依据） |
| [auto-facts.md](auto-facts.md) | 自动事实册（**机器所有 · 勿手改**）：`scripts/doc_sync.py --write` 从代码重生成，`--check` 漂移即红（交叉验证机制常驻门） |
| [superpowers/](superpowers/) | SDD 阶段计划与设计件存档：`plans/` 6 份（2026-08-30 → 2026-09-12 shorekeeper 全域审计总计划）+ `specs/` 3 份（社交音乐/防御上下文/视频理解设计） |

## 工作区根目录

| 文档 | 说明 |
|---|---|
| [../AGENTS.md](../AGENTS.md) | 工作区规则 + 项目全貌（架构图 / 功能×子模块清单 / 已知问题台账），LLM 接手自动加载的唯一入口 |
| [../HANDOFF-NEXT.md](../HANDOFF-NEXT.md) | 交接提示词（2026-09-15 午后全量更正版）：新接手 AI 唯一入口（一句话现状/硬规矩/自动同步铁律/在飞与未提交件/开工三步） |
| [../DESIGN-SPEC.md](../DESIGN-SPEC.md) | 设计/执行/验证三规范根部钉死版 v2（vis4 层次化升级；被 `tests/verify_hashes.py` SHA-256 清单钉住，改动须 `--write` 重录） |
| [../COMMANDS.md](../COMMANDS.md) | 命令手册人读版（逐参数，与 `/bot help` 同口径；模块/别名总数以自动目录实时统计为准，不手写） |
| [../REVIEW-WORKFLOW.md](../REVIEW-WORKFLOW.md) | 代码评审规范（固化增量评审流程；产出物统一存 `review/` 目录） |

## 搭建与运维

| 文档 | 说明 |
|---|---|
| [napcat-setup.md](napcat-setup.md) | NoneBot + NapCat 连接 QQ 配置指南 |
| [acceptance-manual.md](acceptance-manual.md) | 验收与接入手册（人格对话 → NapCat → GsCore）；§6.6 重启验收清单 + §6.6.1 触发形态 + §6.6.2 媒体归档 + §6.6.3 金融扩容/账单渠道（2026-09-13/14 批次） |
| [external-runtime-access.md](external-runtime-access.md) | 外部运行时访问与工作区边界（AGENTS.md 按路径引用） |
| [workspace-archive-policy.md](workspace-archive-policy.md) | 工作区与归档规范（AGENTS.md 按路径引用） |
| [ai-kb-operations-manual.md](ai-kb-operations-manual.md) | 运维知识手册（写入机器人向量知识库的投喂件） |

## 配置与路由

| 文档 | 说明 |
|---|---|
| [ai-setup-knowledge-pack.md](ai-setup-knowledge-pack.md) | AI 搭建与配置知识包（可整体喂给 AI） |
| [config-catalog-full.md](config-catalog-full.md) | 全量配置键目录（A1-A26 分域总表 + LLM 七必配 + 热更/校验规则；与 config.py 的同步由 `tests/test_doc_sync_gates.py` 门禁看守，新键必须登记 A26 增量区） |
| [route-matrix.md](route-matrix.md) | 全问法路由矩阵（base_router → capability 权威矩阵） |
| [command-catalog.md](command-catalog.md) | 从 `_HELP_ENTRIES` 与路由 manifest 自动生成的完整命令与教程目录（`python scripts/command_catalog.py --write` 重生成，含新用户教程） |
| [search-api-adapters-2026-09-06.md](search-api-adapters-2026-09-06.md) | 搜索 API 适配与本地配置（COMMANDS.md 引用；LangSearch 真实 key 验收仍开放） |

## 功能设计（现行）

| 文档 | 说明 |
|---|---|
| [affinity-design.md](affinity-design.md) | 好感度数值规范唯一权威描述（`affinity.py` 代码注释指向本文）；**注意**：正文停留在 v4 线性版（`572bfff`），代码已演进 v5 多因素线性步长（见 `affinity.py` §2 注释；v5 起算法说明一律定性、不展示固定加减数值） |
| [rendering-contract.md](rendering-contract.md) | 渲染契约：主题 token 单一来源（`theme_tokens.py`）+ 模板铁律，改卡片模板前必读 |
| [standard-parse-card-acceptance.md](standard-parse-card-acceptance.md) | 解析信息卡验收标准 |
| [db-owners.md](db-owners.md) | 数据库 owner 清单（26 库文件 → owner → 建表迁移点 → 清理策略） |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | 第三方出处与 MIT 许可声明唯一保留地（**勿删**） |
| [control-plane-provider-and-usage-requirements-2026-09-05.md](control-plane-provider-and-usage-requirements-2026-09-05.md) | Control Plane / Provider / 用量监控需求（HANDBOOK §三 B4/B5 未实现功能的需求源） |

## 架构规格（design/，先成文后实现）

> 对应 HANDBOOK §三 B2/B3/B4/B5 长线项；实现前开放问题需用户裁决（`2e0393d`/`b15241e`）。

| 文档 | 说明 |
|---|---|
| [design/central-decision-engine.md](design/central-decision-engine.md) | B2 中央决策引擎设计规格（38 matcher 拓扑 / IngressNormalizer-Engine-Dispatcher / 四阶段迁移） |
| [design/file-transfer-gateway.md](design/file-transfer-gateway.md) | B3 统一文件出站网关设计规格（FileSource → FileTicket → 四通道 deliver → 回执） |
| [design/control-plane-api.md](design/control-plane-api.md) | B4 控制面 API + SakuraFrp 公网设计规格（本机 8742 默认关 / Bearer / 五态断路器 / M1-M6） |
| [design/llm-billing-ledger.md](design/llm-billing-ledger.md) | B5 LLM 计费账本设计规格（三表 DDL / PricingService 双轨统一 / BalanceAdapter / M1-M5） |
| [design/fstring-card-dom-spec.md](design/fstring-card-dom-spec.md) | f-string 卡 DOM 层统一设计规格（共享 mica 卡壳 `mica_shell`；**未实施，待用户裁决**） |
| [design/render-pipeline-optimization-spec.md](design/render-pipeline-optimization-spec.md) | 渲染管线性能优化规格（等待预算/并发模型/渲染缓存/热点清理；独立核验报告 `.superpowers/sdd/2026-09-12-shorekeeper-global-audit/spec-verify-render.md` 七项全实；**未实施，待用户裁决**） |
| [design/visual-effects-catalog.md](design/visual-effects-catalog.md) | 视觉特效目录（11 候选按性价比排序，基于管线规格性能基线；**未实施，待用户裁决**） |
| [codebase-slim-plan.md](codebase-slim-plan.md) | 规模审计与精简提案（2026-09-13 实测 162k 行分布 + `__init__`/smoke/echo 三热点方案 + 主 Agent 执行提示词；**未实施，待用户裁决**） |
