# docs/ 文档索引（2026-09-14 刷新）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](snowluma-setup.md)。

## 当前后端交接 V2.1（2026-09-17）

接手先读[HANDOFF-NEXT](../HANDOFF-NEXT.md)。目标设计与实现事实分开：本轮仅写文档，下方旧完成声明是历史记录，不能替代新门禁。

- [完整架构、协议、资源管理与S0—S16](design/backend-v2-implementation-guide.md)
- [计费/好感度/占卜/日程/搜索/自愈/管理员实战媒体验收](design/backend-v2-product-extensions.md)
- [需求与四列验收状态矩阵](design/backend-v2-acceptance-matrix.md)
- [本轮文档检查与文件清单](../progress.md)

以上是本次批准的设计规格；现行命令和参数仍以实际注册生成物为准，不能把规划接口宣传为已可用。

> **最新续接：动作API路由/错误码已修正，隔离工作区CRUD/预览/确认/模拟发送与默认生成装配已落地；真实会话生产发送、完整后端仍未完成。最新实跑及runtime-layout阻断见 `docs/design/COMPACT-CHECKPOINT.md` 顶部。**


> **最新串行增量：15个细分执行开关、Bot/NoneBot日志摘要采集、Telegram getUpdates网络韧性修复。详情与实跑结果见 `docs/design/COMPACT-CHECKPOINT.md` 顶部；协议见 `control-plane-registry.md`、`control-plane-events.md`。能用子代理就用子代理、并行满载（限流为唯一上限，撞墙落盘保进度、结束即补派、前台派完即收不卡输出）；未部署、完整后端未完成。**


> 单一入口是 [HANDBOOK.md](HANDBOOK.md)：交接总账、现行事实、权威正文、归档执行记录都在里面。
> 维护规矩：**不再新建带日期的交接文档**，一切增量直接更新 HANDBOOK.md；文档过时后按 [workspace-archive-policy.md](workspace-archive-policy.md)（压缩 → 验证 → 移出）处理。
> 历史文档（旧交接 / 期报 / 已实施计划共 26 份 + 合并前 MASTER/full 原件）已归档至 `ChatBot_Archive\2026-09-12\docs-archive-2026-09-12.zip`（内含 manifest.md 逐份缘由清单）；git 历史亦可 `git log --follow -- docs/<文件名>` 回溯。**09-12 收口批再折算删除 5 份**（final 全账 → HANDBOOK §18，review-fixes/bgroup-verify 增量 → §三），原件同 zip+git 可溯。

## 十板块功能树（2026-09-21 起为文档主结构）

实现这个 bot 的全部知识按**一级板块 → 二级功能 → 三级入口**归档在 [boards/](boards/README.md)，
共 10 个板块，逐板块/逐功能/逐入口一目录一页；板块树本体与三级清单由代码派生，**不手抄**。

- [boards/README.md](boards/README.md)：十板块总览与派生事实（总览页整页机器所有）
- [boards/_conventions.md](boards/_conventions.md)：统一规范本体——文件结构、命名、开发约束（先建模块与函数、只调用已登记件）、自动化变更契约、P0/P1/P2 分级、代码质量红线
- 权威声明源：`plugins/bot_unified_runtime/domains/core/board_taxonomy.py`（板块/功能/认领关系）
- 投影生成器：`python scripts/board_doc_sync.py --write`（体检 `--check`）
- 常驻门：`tests/test_board_taxonomy_gate.py`（结构自洽 + 活性覆盖 + 实现路径可解析 + 生成物同步，含三发变异注毒自证）
- 旧汇总文档退役依据：[boards/_meta/doc-classification-20260921.md](boards/_meta/doc-classification-20260921.md)（全量 md 分类账：现役性、归属板块、处置建议）
- 代码质量缺陷台账：[boards/_meta/code-quality-findings-20260921.md](boards/_meta/code-quality-findings-20260921.md)（P0/P1/P2 分级与最小修法）

## 交接与总账

| 文档 | 说明 |
|---|---|
| [design/control-plane-services.md](design/control-plane-services.md) | 控制动作公开Service/REST、确认/CAS/幂等/错误码与装配边界。 |
| [design/control-plane-workspaces.md](design/control-plane-workspaces.md) | 隔离工作区REST、短期保留、模拟发送、模型生成及真实会话待接端口。 |
| [design/COMPACT-CHECKPOINT.md](design/COMPACT-CHECKPOINT.md) | 控制面最新续接状态、实跑证据、未完成范围；能用子代理就用子代理、并行满载（限流为唯一上限，派完即收）。 |
| [design/control-plane-metrics.md](design/control-plane-metrics.md) | 资源与账本指标后端协议、DTO、unknown 语义、采样边界及前端适配说明。 |
| [HANDBOOK.md](HANDBOOK.md) | 单一活文档：Part 0（族谱终裁 / 现行事实 / 未完成总账 §三）+ Part II（权威正文 §1-§17 + §18-§34 批次全账）；**§34 最新：v21r5 三任务批（此前 §33 v21r4-B 后端并发波 / §32 渲染统一收口+AxonHub WebUI / §31 控制面续接）** |
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
| [../webui/](../webui/) | AxonHub 衍生前端（Vite+React+Tailwind4+singlefile）：源码骨架 + Apache-2.0 合规件（`THIRD_PARTY/`），构建产物 `dist/index.html` 单文件挂控制面 `/ui` |
| [../scripts/webui_mock_server.py](../scripts/webui_mock_server.py) | WebUI 离线确定性夹具后端（2026-09-18）：端点形状一一对照真实契约、固定假时刻输出逐字节一致，仅供前端开发/目验/截图对比；不读真实数据、不写文件、绝不接入生产链路 |
| [scripts/webui_acceptance.py](../scripts/webui_acceptance.py) | WebUI 真机端到端目验脚本（playwright 无头，file:// 直开 dist+localStorage 预置；9 页 data/graceful 自动归类+逐页截图+--json；验收口径=acceptance-manual §6.6.9/§6.6.10） |
| [scripts/tts_retcode_collect.py](../scripts/tts_retcode_collect.py) | SnowLuma `send_msg` 回执 retcode 分布采集（T55 §七 open 项的采集手段）：对真机验收窗（§6.6.11）后 nonebot 日志离线扫描，按码计数+首末时间+样例，与读码预判集对表；全离线零网络，证据采集器非门 |
| [scripts/tts_offline_selfcheck.py](../scripts/tts_offline_selfcheck.py) | TTS 真机验收前置三步一键自检编排（零业务断言，SKIP 不假红）：pre_restart_check 10 项 → verify_chatbot_env → 语料门 `test_tts_corpus_gate.py`；判定透传子工具，任一 FAIL 退出码 1，`--dry-run` 桩化演练 |

## 搭建与运维

| 文档 | 说明 |
|---|---|
| [snowluma-setup.md](snowluma-setup.md) | **现行协议端**：NoneBot + SnowLuma 连接 QQ 配置指南（注入方式差异 / 令牌 zxcvbn 规则 / 迁移与回滚 / 排查 / §6 语音出站与 silk 转码——TTS 语音出站的单点依赖面） |
| [napcat-setup.md](napcat-setup.md) | 旧协议端：NoneBot + NapCat 连接 QQ 配置指南（2026-09-18 起保留作回滚路径） |
| [acceptance-manual.md](acceptance-manual.md) | 验收与接入手册（人格对话 → SnowLuma → GsCore）；§6.6 重启验收清单 + §6.6.1 触发形态 + §6.6.2 媒体归档 + §6.6.3 金融扩容/账单渠道（2026-09-13/14 批次） |
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
| [db-owners.md](db-owners.md) | 数据库 owner 清单（库条目以该文件自身为准，并由 `tests/test_db_owners_coverage.py` 与 `config.py` 的 `*_db_path` 双向锁；owner → 建表迁移点 → 清理策略） |
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
| [design/v21r3-render-closing-spec.md](design/v21r3-render-closing-spec.md) | 渲染统一收口规格（2026-09-18 wave-2）：11 面数值收口 + 值册 C1-C13 + 机器门，渲染改动的唯一施工依据 |
| [design/webui-axonhub-adoption.md](design/webui-axonhub-adoption.md) | WebUI AxonHub 采纳规格（路线 B）：来源与许可证 / token 映射 / 版式宪法（版式宪法节由并行席 WEBUI-SPEC2 追加中） |
| [design/webui-pages2-spec.md](design/webui-pages2-spec.md) | WebUI 二期三页（知识库/插件/记忆图谱）施工工单+版式宪法+参照图对照表（§7） |
| [design/tts-contract-layer.md](design/tts-contract-layer.md) | TTS 统一性契约层设计规格（Wave G·G-1/T54）：触发边界与触发词/打码/内容闸/产物体检/失败码/概率门六面的现行锚点+目标契约；**规格件零施工**，落地宣称以施工席实跑为准 |
| [design/media-digest-layer.md](design/media-digest-layer.md) | 中央媒体摘要层蓝图（Wave H 预研·T107）：音频产物字节零摘要、出站键 M-64 未闭半的六流经点现状图+中央 digest 件方案；**方案件零施工** |

### 控制面续接入口

- `design/control-plane-core-status.md`：本轮实际协议、FeatureControlService和存储修正、审查定位、测试证据、尚未接Runtime的明确边界；配合根目录HANDOFF-NEXT.md §9使用。

## 波次文档（v21r4-B 后端协议波，2026-09-19）

| 文档 | 说明 |
|---|---|
| [design/v21r4-b-wave-snapshot.md](design/v21r4-b-wave-snapshot.md) | v21r4-B 后端波整合快照：交付总表 / 50+ 项用户裁决清单（§二 10 组可勾选）/ 口径差异 6 条 / 状态红线 |
| [design/v21r4-b-qa-probe-report.md](design/v21r4-b-qa-probe-report.md) | v21r4-B 波中回归快照（时点证据）：三族 1063 passed / 23 failed 全归前端域；门禁四件体检 |
| [design/v21r4-b-doc-sync-draft.md](design/v21r4-b-doc-sync-draft.md) | v21r4-B 波末文档增量草案（AGENTS.md #42 / HANDBOOK §33 / README·HANDOFF 增量 / 收尾清单） |
| [design/v21r4-l41-decision-memo.md](design/v21r4-l41-decision-memo.md) | L41 记忆库三案裁决材料（推荐 A 独立新库；未裁决不得接线） |
| [design/v21r4-l41-exec-runbook.md](design/v21r4-l41-exec-runbook.md) | L41 执行预案（A 案 12 步施工坐标+测试计划；预案≠授权≠裁决） |
| [design/v21r4-L60-立项书.md](design/v21r4-L60-立项书.md) / [L71](design/v21r4-L71-立项书.md) / [L74](design/v21r4-L74-立项书.md) | 好感误扣补偿 / 自修复链 / 验收产物 三立项书（纯提案，5/6/7 条待裁） |
| [design/v21r4-b2-port-wiring-plan.md](design/v21r4-b2-port-wiring-plan.md) | 真实发送端口组接线方案材料（15 项前置条件待用户勾选；不构成实施授权） |
| [design/v21r4-b2-direct-collect-plan.md](design/v21r4-b2-direct-collect-plan.md) | S0 直连点收编方案（5 处坐标+三形态缺省关设计；根 init 四点在飞执行中） |
| [design/v21r4-command-format-review.md](design/v21r4-command-format-review.md) | 命令格式评审材料（topic 数以机器册为准、评审当时为 77 topics 现状未动；14 领域 vs 20 域坐标系裁决点） |
| [design/v21r4-kb-drift-explainer.md](design/v21r4-kb-drift-explainer.md) | 知识库漂移三问说明（35341 vs 4611；重建与否用户亲办） |
| [design/v21r4-b6-ledger-memo.md](design/v21r4-b6-ledger-memo.md) | B6 五项调研 memo（搜索时效/合并转发/提醒残余/LLM 故障转移 live 清单/亲密话术指针） |
| [design/v21r4-b-restart-acceptance-checklist.md](design/v21r4-b-restart-acceptance-checklist.md) | v21r4-B 重启验收清单（波后真机验收口径） |
| design/v21r4-b-*-log.md（各席日志） | 席位日志族（断点续跑依据+交付清单+实跑证据） |

## 波次文档（v21r5 三任务批，2026-09-20）

| 文档 | 说明 |
|---|---|
| [design/v21r5-coordination.md](design/v21r5-coordination.md) | v21r5 波次协同登记：席位与文件域互斥表/关键缝/时间线全录（A 超时根治 / B 亲密模式 v3 / C 政策放宽 / 主会话收口 / campus+VERIF 在飞） |
| [design/r18-taxonomy-20260920.md](design/r18-taxonomy-20260920.md) | R-18 成人内容裁定清单 memo：硬线+待裁清单；**§六=用户 09-20 二轮裁定全量**（无条件放开 10 / 条件放开 4 / 维持禁止 3.1-3.5 / 硬线 5→6） |
| [design/v21r5-TIMEOUT-log.md](design/v21r5-TIMEOUT-log.md) | A 席 log：链级 fail-fast（连续 5 跳网络中止）+config_missing 重复冷却；改动行号区间+实跑输出原文 |
| [design/v21r5-INTIMACY-log.md](design/v21r5-INTIMACY-log.md) | B 席 log：亲密模式 v3 双开关/TTL 60min/四名单/成员派生键；改动文件行号区间+28 例证据 |
| [design/v21r5-POLICY-log.md](design/v21r5-POLICY-log.md) | C 席 log：六硬线 scope 化+放开面+memory_sanitize 收窄+人格四处；C-CONT 施工明细+前任件核验 |
| [design/v21r5-C-brief-final.md](design/v21r5-C-brief-final.md) | C 席终版简报（用户二轮裁定后的六硬线定稿） |
| design/v21r5-CAMPUS-log.md · v21r5-REVIEW-log.md · v21r5-RESTART-log.md · v21r5-DOCS-log.md | 在飞/收尾席日志族（campus 测试债 / 恶毒自攻评审 / 重启验收清单 / 落账席） |
| design/v21r5-restart-acceptance-checklist.md | v21r5 重启验收清单（**在飞产出**：RESTART-PREP 席落盘中，以其终稿为准；本行先占位不臆造内容） |
