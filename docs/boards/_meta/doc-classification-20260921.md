Status: STARTED

# Markdown 全量分类账 (2026-09-21)

> **计数口径（AGENTS 第一部分规则 10）**：本册逐条「件数 / 字节数 / 域数」都是 **2026-09-21 判定时点值**，
> 只作「当时怎么判的」历史证据；现役数一律以 spec_gates_census 取数口现算与目录本身为准（docs/design 与 .superpowers/sdd 两面的页数在治理波里天天动）。原数字一律保留，不改写、不删。

约定: 条目字段 = 路径 | 体量(字节) | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置建议 | 判定依据

## 1. 根目录 .md

> 字段顺序: 路径 | 字节 | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置 | 依据
> 体量与日期实测: size=os.stat, 日期取 git log 末次提交日（untracked=未入库，日期取 mtime）。

| AGENTS.md | 115053 | 现行权威(2026-09-20 入库, 顶部横幅 09-21 指向 FIXWAVE) | B10 | B01/B02/B08 | 工作区铁律 / 目录地图 / 消息主链路 / 功能x子模块清单 / 门禁 / 已知问题台账 / 交接史权威链 | 保留原地只加指针(权威链头部指向 docs/boards/) | 顶部自带「接手必读」链, 是全局入口与规则源, 不是板块正文 |
| COMMANDS.md | 23854 | 现行权威(人读版命令手册, 09-20) | B02 | B05/B06/B03 | 命令口径 / bot help 主题 / 管理员开关 / 开发命令 | 并入 B02 正文(命令索引), 与 docs/command-catalog.md 去重后作为其人类视图 | 自述「与 /bot help 同一口径」, 且指向 command-catalog 全量目录 |
| COORDINATION.md | 9194 | 已失效(过程件, v21r2 并行批次席位登记, 09-20 untracked) | NONE | B10 | 席位登记 / 波次协调 | 归档到归档包（路径以归档规程真身为准） | 纯波次协调台账, 波次已收官; 权威链已转向 HANDOFF-FIXWAVE |
| DESIGN-SPEC.md | 14693 | 现行权威(自述唯一根部视觉/质量入口, 被 verify_hashes 钉) | B08 | B10 | 视觉铁律 v2 / 执行规范 / 验证门禁矩阵 | 保留原地 + B08/B10 双向指针, 禁移树 | 文件头自证被 tests/verify_hashes.py SHA-256 清单纳入 |
| HANDOFF-FIXWAVE-20260921.md | 14345 | 现行权威(09-21 冷启动第一入口, untracked) | B10 | B02/B09 | 十三项四态总表 / 门禁真值 / 待办 / 坑 / 证据地图 | 并入 B10「交接与门禁真值」小节, 或原地保留作入口 | AGENTS.md 顶部横幅点名「优先于下方各条」 |
| HANDOFF-NEXT.md | 23664 | 已失效(AGENTS.md 明示「已被上条取代为历史」; 09-15 首提交) | B10 | NONE | 旧交接提示词 / 自动同步铁律 / 在飞待办 | 归档到归档包（路径以归档规程真身为准） | 交接链已由 FIXWAVE/V21R6 接手, 顶部自带「下方属历史批次」声明 |
| HANDOFF-PROMPT-20260921.md | 9285 | 现行权威(09-21 贴给下一 AI 的提示词, untracked) | B10 | NONE | 开工必读顺序 / 硬约束 / 现役状态 | 保留原地(会话提示词, 非规格), 只加指针 | 自述「与 AGENTS/HANDBOOK 冲突以它们为准」 |
| HANDOFF-SESSIONS-unify-audit-20260919.md | 31266 | 历史证据(统一性审查三会话归档, 09-20 untracked) | NONE | B01/B06/B08 | 波A 后端统一审计21份 / 波B TTS专项31份 / 波C 补跑修复 | 归档(指向 docs/design/unify-audit-20260919/ 原件) | 自述为审查全量归档, 正文已蒸馏, 原件在 design 目录 |
| HANDOFF-V21R4-20260918.md | 34283 | 历史证据(v21r2→r4 收尾, 顶部有 v21r5 增量指针) | B10 | B02/B04 | 波次总览 / 需求全集复述 / 板块重组 domains/20 域 | 归档 | 自述「截至 r4, r5 改动未含」, 已被 R5/R6 交接取代 |
| HANDOFF-V21R4-B-20260918.md | 17565 | 历史证据(后端协议波交接) | B01 | B02/B10 | 后端协议工作包 / 环境纪律 / 门禁四件 | 归档 | 自述是 backend-protocol-plan.md 的交接版, 规格件已在 docs/design |
| HANDOFF-V21R4-F-20260918.md | 20561 | 历史证据(前端渲染扩展波交接) | B08 | B10 | mica_shell 外壳 / 渲染扩展工作包 | 归档 | 自述是 frontend-render-expansion-plan.md 的交接版 |
| HANDOFF-V21R5-20260920.md | 68273 | 历史证据但含现役改动清单(r4-B 波总交接) | B02 | B01/B09/B03 | 四服务生产装配 / S0 直连点收编 / 垫片退役（张数以退役账现算为准）/ policy 迁移 / 控制面三债 | 拆并入 B02/B01/B09 正文, 原文件归档 | 逐席证据在 docs/design/v2*.md, 本文件是其蒸馏 |
| HANDOFF-V21R6-TESTING.md | 27963 | 现行权威(测试验收 AI 入口, 09-21 untracked) | B10 | B03/B01 | LLM 超时根治 / 亲密模式 v3 / R-18 政策 / campus U17 收编 / 验收对账 | 并入 B10 验收章 + B03 内容安全章指针 | AGENTS.md 顶部「测试验收 AI 入口」点名此文件 |
| HANDOVER-TTS-GH-20260920.md | 24126 | 现行权威(TTS 统一波 G+H 契约/传输层, 09-21) | B06 | B01/B08 | TTS 契约层 / 传输层 / 六个 P0 / 三生成物重写陷阱 | 并入 B06 语音小节 + B01 段归一指针 | 自述「穷尽版 v2, HEAD=9d758a5 全在 git」 |
| README.md | 7866 | 现行权威(人类门面, 09-14 起) | B10 | NONE | 能力全景 / 快速上手 / dev.ps1 任务入口 / 目录导览 | 保留原地(门面), 板块正文引用即可 | 唯一面向人类的项目门面 |
| REVIEW-WORKFLOW.md | 8625 | 现行权威(评审规范, 09-15) | B10 | NONE | 评审五步流程 / 严重度定义 / 固定清单 / 报告模板 | 并入 B10「评审与归档规程」 | 流程规范, 未见他文取代 |
| V21-UPDATE-LOG.md | 31783 | 历史证据(V2.1 会话更新日志 09-17/18) | NONE | B02/B04 | 执行台账多批次多席位 / 尚未完善对账 / 断点续接 | 归档 | 波次日志, 待办已被 task_plan/FIXWAVE 换页声明取代 |
| WORKSPACE_GUIDE.md | 3839 | 现行权威(工作区引导, 09-15) | B10 | NONE | 三目录职责 / 启动与验证 / 归档入口 / 禁做事项 | 并入 B10 开头(与 README 部分重叠, 去重) | 与 README 存在「目录导览」重复 |
| findings.md | 4806 | 过程件(本轮交接发现, 09-21 有追加) | B10 | NONE | 失败形态集 / 证据等级 | 并入 B10「已知坑」或归档 | planning-with-files 会话产物, 内容已被 FIXWAVE §6 吸收 |
| progress.md | 9690 | 过程件(本轮进度, 09-21) | NONE | B10 | 会话日志终态 | 归档 | 同上, 与 FIXWAVE 重叠 |
| report-T116.md | 7088 | 过程件(席位报告, 09-20 untracked) | B06 | B10 | media_archive sha256 收编中央件 | 归档到归档包（路径以归档规程真身为准） | 单席施工报告, 结论已落 docs/design/media-digest-layer.md |
| report-T124.md | 4021 | 过程件(纯文档同步席, 09-20 untracked) | B10 | NONE | docs/README 索引补登 / tts-handover 勘误 | 直接删除或归档 | 已执行的文档同步动作, 无长期信息量 |
| task_plan.md | 11325 | 已失效(顶部自述「以下内容是历史计划, 不是现役进度」) | NONE | B10 | 旧 V2.1 任务计划 / v21r3 批次 | 归档 | 自带换页横幅, 指向 HANDOFF-FIXWAVE 与 sdd master-plan |
| 审查结论与重构计划.md | 39459 | 历史证据(09-17 untracked, HEAD=90274f5 基线) | NONE | B02/B08 | 17 仓对比裁定 / 九统一落地表 / 证据分级 | 归档(九统一表仍有引用价值, 并入 B10 决策记录) | 基线 commit 早于 v21 全部波次 |

## 2. docs/*.md（顶层件，数以本目录现算为准）

| 路径 | 字节 | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置 | 依据 |
|---|---|---|---|---|---|---|---|
| docs/CODE-MAP.md | 69958 | 现行权威(导航件, 09-20) | B10 | 全域 | domains/21 域清单 / 五条链路跳转表 / 症状定位 | 保留原地 + 作为各板块「代码落点」统一指针源 | 自述「导航件不复制正文」, audit-20260921 明确以它避免副本 |
| docs/HANDBOOK.md | 422129 | 现行权威(历史总账+单一活文档, 09-20) | B10 | 全域 | 文档族谱与权威链终裁 / 现行事实速查 / 全波次史 | 拆: 「现行事实速查」升为各板块正文母本, 史论部分归档保留 | 体量最大且自带权威链终裁, 与新 boards 存在双事实源风险 |
| docs/HANDOVER-2026-09-15.md | 26090 | 已失效(顶部有 09-17 指针横幅取代) | B01 | B02 | 五层架构图 / LLM 子链收敛口径 | 归档到归档包（路径以归档规程真身为准） | 自述「当前交接见 HANDOFF-NEXT」, 后者又已失效 |
| docs/README.md | 18091 | 现行权威(docs 索引, 09-21 由 T124 席补登) | B10 | NONE | 文档索引 / 分类目 | 保留原地, 新 boards 目录建好后必须在此登记 | 唯一 docs 索引, 且被链接完整性门覆盖 |
| docs/THIRD_PARTY_NOTICES.md | 3996 | 现行权威(09-21 追加 zhconv) | B08 | B10 | 卡片渲染子包借鉴声明 / AxonHub / zhconv | 保留原地不动 | 自述「第三方出处唯一记录」, 许可证合规件 |
| docs/acceptance-manual.md | 125814 | 现行权威(接入与验收手册, 09-21) | B10 | B01/B06/B05 | 依赖安装 / 控制台人格验收 / SnowLuma 接入 / GsCore | 拆并入 B01(接入) + B10(验收规程), 原地保留可执行手册 | 操作性手册, 与 snowluma-setup/napcat-setup 有重复 |
| docs/affinity-design.md | 19192 | 部分失效(v4 数值表被 v7 取代; 档位/红线仍权威) | B03 | B04 | 好感度八档 / 行为因子表 / 时间减退 / providers 映射 | 并入 B03 好感度小节, 与 docs/design/affinity-v7-design.md 合并为一份 | 文件头自带权威链: 「§2/§3 步长数值已被 affinity-v7-design.md 取代」 |
| docs/ai-kb-operations-manual.md | 22462 | 现行权威(知识库入库说明书, 09-09) | B09 | B03 | 七必配键 / 多供应商注册表与故障转移 / 热更 | 并入 B09 控制面正文; 注意它是 BOT_KNOWLEDGE_FILES 入库件 | 与 ai-setup-knowledge-pack 互为「说明书/全集」, 有内容重复 |
| docs/ai-setup-knowledge-pack.md | 62618 | 现行权威(搭建知识全集, 09-07 首提交 09-21 更新) | B09 | B10 | 目录数据地图 / 权限体系 / LLM 引擎接入与路由 | 并入 B09; §6 已由 config-catalog-full 展开, 去重 | 自述「本文档是 ai-kb-operations-manual 的完整展开源」 |
| docs/audit-20260921.md | 161974 | 现行权威但为审计结论件(09-21 untracked) | NONE | 全域 | 统一性审计 / 三条尺子 / 文件地图 / §9 定罪与 F-1..F-9 | 保留原地(审计档案) + 各板块引其结论行, 不并入正文 | 自约束「避免制造第 N 份副本」; §0.4/§9 才是现役结论 |
| docs/audit-20260921-decisions.md | 13997 | 现行(待拍板清单, 09-21 untracked) | B09 | B03/B05 | SSRF 18 平台凭据 / 繁体内硬线 / 紧急预警误报 / TTS 卡死 | 待用户裁定后逐条落进对应板块, 原文保留 | 面向用户的大白话裁决件, 技术细节指向 audit 主件 |
| docs/audit-20260921-commands.md | 12821 | 现行(真机验收清单, 09-21 untracked) | B10 | NONE | A-G 组真机验收 / 门禁复跑命令 | 并入 B10 验收章 | 配套 audit §9, 验收动作件 |
| docs/auto-facts.md | 2150 | 生成物(机器所有勿手改, 09-15) | B10 | B09 | doc_sync 生成的自动事实 | 保留原地, 禁止移树 | 被 tests/test_cross_validation_gates.py 常驻比对, 动它须先改门 |
| docs/codebase-slim-plan.md | 15552 | 已失效倾向(提案未实施, 09-13 数据) | NONE | B10 | 规模审计 / 精简方案 | 归档(若已被 v21 清理波实施则直接归档并注明) | 自述「本文件不含已执行改动, 待裁决后归档」 |
| docs/command-catalog.md | 171176 | 生成物(现行, scripts/command_catalog.py --write) | B02 | B05/B06 | 命令与教程全目录 / 帮助页 / 路由接口清单 | 保留原地, 禁止移树; 板块只引用不复制 | 文件头标注自动生成且被 doc_sync/哈希门禁钉住 |
| docs/config-catalog-full.md | 146778 | 生成物/半自动(09-20) | B09 | 全域 | 按域分组全量配置键目录(A1..An) | 保留原地, B09 引用 | 权威源声明为 config.py, 手写目录有漂移风险 |
| docs/control-plane-provider-and-usage-requirements-2026-09-05.md | 35298 | 历史需求件(09-05「尚未进入实现」) | B09 | NONE | 供应商/模型/用量监控需求合同 | 保留为需求溯源(已大部实现), 现役口径并入 B09 | 状态自述未实现, 但 control_plane 已建成 |
| docs/db-owners.md | 18225 | 现行权威(09-12 grep 登记, 09-21 更新) | B04 | B09 | SQLite 库 owner 清单 / 清理纪律 | 并入 B10 数据治理小节(跨域) | 「只登记不改迁移」, 与各域存储文档交叉 |
| docs/external-runtime-access.md | 10060 | 现行权威(09-20) | B10 | B04 | 外部运行时访问 / 工作区扫描边界 / AI 避扫 | 并入 B10 工作区边界章 | 与 workspace-archive-policy 主题重复, 需去重 |
| docs/handover-c-20260913.md | 20685 | 历史证据(09-13 C 方向交接) | B05 | B08 | 金融数据层 / 图表库 / 菜谱图片 / 卡片补全 | 归档 | 波次交接, 内容已由 domains/finance 与 rendering-contract 覆盖 |
| docs/issue-ledger-p2-p3.md | 33618 | 部分现役(P2/P3 台账, 09-14) | B10 | 全域 | 逐条可执行问题详情 / 根因 / 验收 | 保留原地作台账, 已闭项归档 | AGENTS.md 第六部分是索引, 本件是详情 |
| docs/napcat-setup.md | 6899 | 已失效(09-18 起协议端改 SnowLuma, 留作回滚) | B01 | NONE | NapCat QQ 接入 / token / 重启 | 归档到 ChatBot_Archive 或原地保留标注回滚 | 文件头自述「新接入不要再按本文操作」 |
| docs/nightly-ops-report-20260915.md | 14366 | 历史证据(09-15 夜间工程总报告) | NONE | B10 | 阶段完成总账 / BUG 分级 | 归档 | 提交哈希基线 90274f5..4608235, 已被 HANDBOOK 吸收 |
| docs/pending-decisions.md | 10113 | 历史(09-14 聚合, 多数已被 09-21 decisions 取代) | NONE | B09 | 待用户裁决四组清单 | 归档, 与 audit-20260921-decisions.md 去重 | 同源后继件为 audit-20260921-decisions.md |
| docs/perf-optimization-plan.md | 5474 | 已失效(自述「历史测量档案, 不再更新」) | NONE | B02 | 五条延迟链路 / Phase 2 | 归档 | 顶部状态注记直接宣布非现行 |
| docs/rendering-contract.md | 28795 | 生成/契约双身份(09-20) | B08 | B10 | 11 渲染面铁律 / 本命色 / PLATFORM_THEMES / Shell 常量 | 保留原地, 禁移树; B08 正文以它为契约 | 自述单一事实源 theme_tokens.py, 机器形态=tests/test_rendering_contract.py |
| docs/route-matrix.md | 20004 | 现行权威(09-20/09-21) | B02 | B06 | 全问法路由矩阵 / base_router 链路 / 表情包入口 / 世界观判定 | 并入 B02 路由正文 | 与 command-catalog 生成物有重叠, 需以代码为准 |
| docs/search-api-adapters-2026-09-06.md | 3657 | 现役偏旧(09-06, Tavily/You/LangSearch 链) | B05 | B09 | 搜索 API 适配与回退顺序 / 安全边界 | 并入 B05 检索小节, 与 config-catalog 去重 | 回退顺序等事实另有 config 键定义点 |
| docs/snowluma-setup.md | 16026 | 现行权威(09-20, 现役协议端) | B01 | NONE | SnowLuma 接入 / token 规则 / 与 NapCat 差异 / 能力边界 | 并入 B01 接入章正文 | 自述现行协议端; napcat-setup 的回滚件 |
| docs/standard-parse-card-acceptance.md | 11159 | 部分现役(09-01/09-07, 解析卡字段标准) | B05 | B08 | content 解析信息卡字段标准(博主/媒体/页面/跨平台) | 并入 B05 link_parse 小节 | 配套实现文档已换代, 字段标准仍需核对是否漂移 |
| docs/usage-cache-price-fix-2026-09-18.md | 8780 | 历史证据(09-18 一次性修复记录, untracked) | B09 | NONE | 缓存命中口径 / 价目写进模型注册表 | 归档 | 定点修复记录, 结论应在计费账本正文 |
| docs/workspace-archive-policy.md | 4267 | 现役但被取代倾向(08-28 起) | B10 | NONE | 目录布局 / 扫描边界 / 归档规则 / 敏感信息 | 与 external-runtime-access.md 合并为一份「工作区与归档规程」并入 B10 | 与后者主题高度重叠 |
| docs/核心要求.md | 21492 | 现行权威(用户 mandate 逐字, 09-20 untracked) | B10 | NONE | 用户核心要求全集 / 稳定契约标识符说明 | 保留原地, 是 boards 分类的裁定依据源 | 顶部指向 backend-v2-implementation-guide 为实施合同 |

## 3. docs/design/**（顶层 236 件 + unify-audit-20260919/ 58 件 + docs/superpowers/ 9 件；**09-21 时点值**，现数以目录与取数口现算为准）

> 采集方法: 一次性只读脚本遍历三处目录, 逐件取 `os.path.getsize` + `git log -1 --format=%ai` + `git ls-files` 在库判定(T=tracked/U=untracked) + 文件头前 2 非空行; 现役性由**文件头自述状态行**(如「规格稿(未实现)」「待用户过目」「已被 X 取代」) + 末次提交日 + 是否被 AGENTS/HANDBOOK/audit 点名 三信号合成。
> 日期列为 `-` 者 = untracked 从未入库, 无 git 日期可依, 只能按文件头自称日期记账(已在依据列注明)。
> 合并条目规则: 同波次同形态的席位日志合并为一行, **显式列出全部文件名**, 字节给区间与该组总量。

### 3.1 docs/design —— 规格件 / 现行权威件（逐条）

| 路径 | 字节 | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置 | 依据 |
|---|---|---|---|---|---|---|---|
| docs/design/affinity-v7-design.md | 10488 | 现行权威(U, 09-21 头注自证取代 v4/v5 数值) | B03 | B04 | 好感度 v7 潜变量 z/五子信号/三护栏 | 并入 B03 好感度小节, 与 docs/affinity-design.md 合成一份(v7 为数值权威, v4 只留档位与红线) | 首行「本文件取代 docs/affinity-design.md 的数值算法部分」 |
| docs/design/backend-v2-implementation-guide.md | 31422 | 现行权威(实施合同, U) | B02 | B09/B10 | V2.1 架构/执行/交接/装配 | 并入 B02 正文, B10 引其为实施合同 | AGENTS.md 顶部与 docs/核心要求.md 双点名为权威链 |
| docs/design/backend-v2-product-extensions.md | 41299 | 现行权威(合同补充件, U) | B03 | B02/B09 | 算法/参数/计费/恢复/实战验收 | 并入 B02/B03 各节, 与 implementation-guide 同批处置 | 自述「补充主规范, 对应验收矩阵」 |
| docs/design/backend-v2-acceptance-matrix.md | 37992 | 现役但**六列待回填**(U) | B10 | B02 | V21-* 需求·装配·验收矩阵 | 保留原地作矩阵母本, 板块只引用不复制 | v21r4-B B1 席(MAT)程序化回填（数以该席 §三.1 为准）, not_wired 口径见其 §三.1 |
| docs/design/capability-orchestration-adoption-spec.md | 29107 | 现行权威(规格, Wave 1–4 未做, U) | B02 | B10 | 中央能力调度层接入 7 维验收/O1–O7 | 并入 B02 调度层正文, 未做波次标挂账 | WP8-design 席位自述「只出文档, 本轮零代码改动」 |
| docs/design/emergency-alert-taxonomy-20260921.md | 16808 | 现行权威(唯一权威规格, U) | B05 | B07 | 预警全谱 9 族 31 类/定级/颜色/静默窗击穿 | 并入 B05 紧急信息小节正文 | 首行「本件是唯一权威: 代码从这里派生, 不反过来」 |
| docs/design/emergency-info-registration-runbook-20260920.md | 64433 | 历史施工图(口径已被 #46 覆盖, T 09-20) | B05 | B02/B10 | 紧急域注册九面施工单 | 保留作施工图档案, 板块正文以 AGENTS #46 + enablement §七 为准 | AGENTS #45 称其「施工图唯一权威」, #46 裁定 3.B 令其 §5-钉死②第三腿作废 |
| docs/design/emergency-info-unify-spec-20260920.md | 76781 | 现行规格(B11 统一规格, T 09-20) | B05 | B08 | 紧急聚合域形状/契约 | 并入 B05 紧急域正文 | 自述「只读现状 + 成文形状」, 未见后继取代 |
| docs/design/emergency-info-enablement-20260920.md | 9504 | 现行权威(上线操作单, U) | B05 | B10 | 群内订阅用法全表 / 装配门 | 并入 B05 + B10 上线章; §七 是订阅面唯一用户文档 | AGENTS #46 明文登记该节; 但其「三重门」旧口径需按 #46 改写 |
| docs/design/emergency-info-outbound-gate-spec-20260920.md | 29391 | 现行规格(不写码, T 09-20) | B08 | B05 | 中央出站防风暴闸 + 送达核验 | 并入 B08 出站正文(与 tests/test_outbound_gate.py 同读) | 首行「B4-spec … 规格, 不写码」 |
| docs/design/emergency-info-card-spec-20260920.md | 40629 | 历史施工图(T 09-20) | B08 | B05 | 紧急预警出卡 diff 原文 | 归档(实施后应并入 B08 卡片节) | 自述「本文是施工图 + diff 原文, 不是实施」 |
| docs/design/emergency-info-unify-summary-20260919.md | 36826 | 历史证据(A 波收尾, T 09-20) | B05 | NONE | A 波完成度汇总 | 归档 | 波次收尾件, 后继为 wave-final 终验 |
| docs/design/emergency-info-unify-wave-final-20260920.md | 21878 | 历史证据(INTG-1 独立终验, T 09-20) | B05 | B10 | B 波终验结论 | 归档 | 自述「给用户的独立判定」, 一次性裁决件 |
| docs/design/divination-consolidation-20260921.md | 5523 | 现行权威(收编判定, U) | B06 | B10 | 占卜双算法合并 / deck_math 真身 | 并入 B06 占卜小节 | 引用户裁定 11.C 为判据, WP9 实施依据 |
| docs/design/r18-taxonomy-20260920.md | 5460 | 现行权威(裁定清单 memo, U) | B03 | B10 | R-18 分类放开/硬线六条 | 并入 B03 内容安全正文; 保留「唯一不服从用户字面指令之处」注记 | AGENTS #43 点名此件为硬线唯一例外记录 |
| docs/design/memory-reflection-v2-design.md | 9630 | 现行权威(设计, U 09-21) | B04 | B03 | 记忆总线 v2 打分/同类槽 cap/迁移 | 并入 B04 记忆正文 | 首行绑定 WP6; marks 命中「已失效」是其引用旧键形所致, 非本文失效 |
| docs/design/media-digest-layer.md | 14925 | 现行规格(蓝图, T 09-20) | B08 | B06 | 中央媒体摘要层 / canonicalize 三冻结键 | 并入 B08 媒体小节; U-107-A/B/C 仍开放 | T107 自述「方案件零施工」 |
| docs/design/tts-contract-layer.md | 35480 | 现行权威(Wave G 契约层, T 09-20) | B06 | B08 | TTS 引擎 HTTP 中央表/预设表/0=不限+硬顶 | 并入 B06 语音正文, 与 HANDOVER-TTS-GH 去重(以本件为契约) | AGENTS #44 记其为规格真身且 T99 首次入库 |
| docs/design/tts-handover-20260919.md | 74588 | 历史证据为主(交接长文, T 09-20; 含现役坑) | B06 | B01/B08 | TTS 适配全程交接 | 拆: 现役坑(三生成物重写陷阱)并入 B10, 余归档 | 与 HANDOVER-TTS-GH-20260920.md(自称穷尽版 v2)构成新旧两份同事实源 |
| docs/design/tts-audit-20260919.md | 46675 | 历史证据(审计, T 09-19) | B06 | NONE | GPT-SoVITS 逐句可核验审计 | 归档 | 与 tts-handover 同期同域, 结论已入契约层 |
| docs/design/render-pipeline-optimization-spec.md | 21257 | **部分实施 + 被哈希钉** | B08 | B10 | 渲染管线并发/等待预算/缓存 | 禁移树; 现役口径以 .env 两键 + 代码为准 | `tests/verify_hashes.py` MANIFEST 含本件(改动须 `--write` 重录) |
| docs/design/visual-effects-catalog.md | 25240 | **部分实施 + 被哈希钉** | B08 | B10 | E 号特效记分实施态 | 禁移树; 逐 E 号状态回代码核实 | 同上 MANIFEST; 自述「逐 E 号实施态」=半程件 |
| docs/design/fstring-card-dom-spec.md | 24586 | **部分实施 + 被哈希钉** | B08 | B10 | mica_shell 共享卡壳 DOM 统一 | 禁移树; 值层已通水、DOM 层待裁 | 同上 MANIFEST + AGENTS #26 记为「未实施待裁决」 |
| docs/design/v21r2-reorg-plan.md | 81797 | 现行施工图(domains/ 重组, U) | B10 | 全域 | 板块重组波次表/映射/门禁网 | 保留作重组唯一母本, 完成后转历史 | 二十余份 `v21r2-reorg-w*-log.md` 一致以它为「施工图」 |
| docs/design/v21r2-shim-retirement-inventory.md | 90094 | 现行施工图(EP1 机核, U) | B10 | 全域 | 垫片退役梯队清单(全仓 AST 机核) | 保留; 退役完张数须回写此件 | 头注「只读产出·退役施工图」, RET1/2/3/RET2B-PREP 各席同引 |
| docs/design/v21r3-render-closing-spec.md | 31982 | 现行权威(wave-2 唯一施工规格, U) | B08 | B10 | 渲染统一收口 C1–C13 值册 | 并入 B08 正文(通水完成后可降历史) | 自述「唯一施工规格」 |
| docs/design/v21r4-b2-port-wiring-plan.md | 31268 | 待裁(方案材料, U) | B02 | B09 | B2② 端口装配组接线 | 保留待用户逐项勾选, 不得据此动码 | 头注「不构成实施授权; 未确认前不得动码」 |
| docs/design/v21r4-b2-direct-collect-plan.md | 27264 | 现行方案(DIRECT-PLAN, U) | B02 | B10 | S0 直连点收编 5 处三形态 | 并入 B02 直连收编节 | AGENTS #42 ⑨ 记其为收编设计真身 |
| docs/design/v21r5-restart-acceptance-checklist.md | 32510 | 现行验收清单(U, 九节全码核实) | B10 | NONE | 重启真机验收 | 并入 B10 验收章; 与 v21r4-b 版去重 | AGENTS #43 明文指此件为验收权威 |
| docs/design/v21r4-b-restart-acceptance-checklist.md | 15773 | 已失效倾向(被 r5 版取代, U) | B10 | NONE | r4-B 重启验收 | 归档, 保留与 r5 版差异行 | 后继件为 v21r5 同名录 |
| docs/design/v21r5-u17-implementation-runbook.md | 23705 | 历史施工图(U17 已实施) | B07 | B01 | campus 收编裁定卡 + runbook | 归档(实施完, 结论已在 AGENTS #43⑤/HANDBOOK §34) | 其下游 U17-IMPL-3 席已按单施工完毕 |
| docs/design/COMPACT-CHECKPOINT.md | 36458 | 现行(续接检查点, 顶部滚动) | B10 | B09 | 控制面/动作路由/日志采集串行增量 | 保留原地; 与 HANDOFF-FIXWAVE 合并为一份「交接真值」 | 首行「最新, 优先于旧交接正文」; AGENTS 控制面校正段点名它为唯一事实页 |

### 3.2 docs/design —— 控制面规格族（B4 系, 6 件；09-21 时点值，族内成员以本表逐条为准）

| 路径 | 字节 | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置 | 依据 |
|---|---|---|---|---|---|---|---|
| control-plane-core-status.md | 13575 | 现行权威(唯一事实页, U) | B09 | B10 | 核心切片接口契约/审查/接手状态 | 并入 B09 正文母本 | AGENTS「控制面接手校正」段点名 |
| control-plane-api.md | 29315 | 历史规格(B4, T 09-12 未实现) | B09 | NONE | /admin/api/v1 + SakuraFrp 公网接入 | 归档(现役 API 面以 core-status 为准) | 状态自述「设计规格, 本轮不含实现代码」 |
| control-plane-events.md | 5537 | 现行协议(U) | B09 | B02 | 日志与实时事件协议/当前实现边界 | 并入 B09 | 自述「当前实现边界」+ 指向 COMPACT-CHECKPOINT |
| control-plane-metrics.md | 5026 | 现行协议(U) | B09 | NONE | 指标协议与未接入边界 | 并入 B09 | 同上 |
| control-plane-registry.md | 6019 | 现行契约(U) | B09 | B02 | 产品注册与执行快照契约 | 并入 B09 | AGENTS 最新串行增量段点名 |
| control-plane-services.md / control-plane-workspaces.md | 3014 / 5374 | 现行边界件(U) | B09 | NONE | 控制动作与隔离工作区服务/适配契约 | 并入 B09; 「未完成」段需回写实况 | 自述「记录当前实现边界, 不能替代发布验收」 |
| docs/design/central-decision-engine.md | 29897 | 已失效(状态=规格稿未实现, T 09-13) | B02 | NONE | B2 中央决策层/统一事件入口 | 归档或原地标注「未实现」(decision/ 仅 shadow) | 文件头状态行自证未实现; BOT_DECISION_ENGINE_MODE 仍 legacy_only |
| docs/design/file-transfer-gateway.md | 20757 | 历史规格(B3 Phase-1, T 09-12) | B08 | B01 | 统一文件出站 FileSource→Ticket→deliver | 并入 B08 出站节 + 标注实施进度 | AGENTS 第四部分记 file_gateway 仅 Phase-1 |
| docs/design/llm-billing-ledger.md | 25273 | 历史规格(B5, T 09-12) | B09 | B02 | LLMCallRecord 计费表/Provider-Balance 适配 | 并入 B09 计费节(三表+generate sink 已落 M1) | 状态自述未实现, 实际 ledger.py 已建成 → 存在双源冲突 |

### 3.3 docs/design —— 席位过程件族（合并区间条目，全名已列）

> 共同判定: 本组全部为**波次席位日志/一次性报告**, 结论已由 `docs/HANDBOOK.md` 对应 § 与 AGENTS 台账吸收, 正文一律**不并入板块**; 板块只在「证据地图」小节给指针。处置默认 = 归档到归档包（路径以归档规程真身为准）。

| 覆盖文件（显式列出） | 件数/字节 | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置 | 依据 |
|---|---|---|---|---|---|---|---|
| `docs/design/audit-20260920-unify-*`：U1-invest / U2-proto / U3-outbound / U4-dispatch / U5-arch / U6-config / U7-command / U9-function / U10-gate / U11b-sec / U12-llm / U13-db / U15-output / U16-green / U17-campus-wire / U18-persona / U19-correct / U20-cp / U21-conc / U22-sandbox / U23-adapter / U24-decision / summary（全 23 件, U 未入库, 合计 946924 B） | 23 | 历史证据(只读审计席位日志) | B10 | 全域 | 统一性逐面取证（面名清单见该批席报首行自述） | 归档; **唯 summary 一件缓归档**——AGENTS #45/#46 与 audit-20260921 仍引其结论行 | 各件首行自述「席位性质: 只读审计, 唯一可写文件=本文件」; summary 自述「合并者汇编, 非新增审计」 |
| 同上 `audit-20260920-unify-U17-campus-wire.md`（单列: 它是 campus 收编规约出处, 被 AGENTS #43⑤ 与 XFAIL 摘牌指引点名「全文件搜 U17-CAMPUS-WIRE」） | 1 / 9536 | 历史证据但**被搜索引用** | B07 | B01/B08 | U17 收编规约 / audit §2§3 空判定 | **暂不归档**, 待 U17 已定稿的锚点改指 HANDBOOK §34 后再移 | AGENTS #43⑤ 明文以「搜 U17-CAMPUS-WIRE」为摘牌指令 |
| `docs/design/v21-seat`：v21-affinity-fix-log / v21-autosync-fix-log / v21-controlplane-fix-log / v21-risk-red-report / v21-risk678-fix-log / v21-s0-baseline / v21-s0-inventory / v21-s0-mapping / v21-s1-sandbox-log / v21-s11-schedule-log / v21-s2-contracts-log / v21-s5-billing-log / v21-s5-events-log（13 件, 173616 B, 全 U） | 13 | 过程件(V2.1 波 A1–A14 席) | B10 | B02/B09 | 基线/风险取证/沙箱/契约/计费/事件 席位日志 | 归档 | 每件首行标「席位: A*/S*」+ 波次已收官, 结论在 AGENTS #37–#40 草案与 HANDBOOK |
| `docs/design/v21r2-*` 施工日志：v21r2-acceptance-log / aff-replay-log / aff-replay-report / dispatch-log / ep1-log / r1-llmroute-log / r2-lifecycle-log / r3-stall-log / r4-affinity-log / r5-hotzone-log / r6-copy-log / r7-contentroute-log / r8-crash-log / repair-log / ret1-log / ret2-log / rk4-log / rp-style-log / s10-log / s11-log / s12-log / s14-log / s15-pregate-report / s8-kb-db-teach-log / s9-log / search-log / v1-persona-log / v2-memory-log / wire-log（29 件, 合计 322455 B, 全 U） | 29 | 过程件(v21r2 后端波席位日志) | B10 | B02/B03/B04/B09 | 各工作包实施记录 | 归档 | 首行一律「席位: X 席」; AGENTS #42 记「逐席报告」性质 |
| `docs/design/v21r2-reorg-w*-log.md`：w1a / w2 / w3 / w4 / w5 / w6 / w7 / w8 / w9 / w10 / w11 / w12 / w13 / w13b / w14 / w16 / wc1 / wc2 / wc3 / wc4 / wc5 / woc / wpa1（23 件, 228041 B, 全 U） | 23 | 过程件(板块重组 RW* 席, 一域一件) | B10 | 全域(每行对应一个 domains/ 域) | 各域搬迁施工记录（域数以现算为准） | 归档; 但**每件的「迁移前→后坐标表」是唯一可核对旧路径的清单**, 归档前抽成 B10 附表 | 各件首行「席位: RW*」且同引 v21r2-reorg-plan.md 为施工图 |
| `docs/design/v21r2-COORDINATION.md` | 97636 / U | 已失效(波次并发协调表, 顶部滚动) | B10 | NONE | 席位认领/在飞状态 | 归档 | 波次协调件, 后继为 v21r4-b-coordination / v21r5-coordination 同型件 |
| `docs/design/v21r2-command-spec.md` + `v21r2-command-spec-entries-1/2/3.md` + `v21r2-command-spec-inventory.md` | 5 / 142066 / U | 部分现役(命令格式统一规格 v1 + 附录A盘点) | B02 | B10 | 全 77 topics 九形态触发词/权限/路由坐标 | 并入 B02 命令格式节; inventory 的盘点数已过期→改指机器册 | 规格「文档先行零代码」; v21r4-command-format-review 是其评审后继 |
| `docs/design/v21r2-agents-ledger-draft.md` / `v21r2-handbook-sync-draft.md` / `v21r2-matrix-backfill-draft.md` / `v21r2-legacy-manifest-draft.md` | 4 / 158041 / U | 已失效(草案, 均已套用入正式台账) | B10 | NONE | AGENTS/HANDBOOK 行草案 / 矩阵四列回填 / 存量对照全表 | 归档(套用即完成使命; AGENTS #37-#40 编号仍留空指向 ledger-draft) | AGENTS 顶部明文「本文件 #37-#40 台账草案在 docs/design/v21r2-agents-ledger-draft.md」→ 归档前须先补该指针 |
| `docs/design/v21r3-core-chain-audit.md` / `v21r3-render-unification-plan.md` / `v21r3-render-shim-retirement.md` | 3 / 50675 / U | 历史证据(核心链路排查 + 渲染统一方案 + 垫片退役预研) | B08 | B02/B10 | 接收→处理→回发主链路 / HTML 模板统一 / 渲染垫片 | 归档(方案已由 v21r3-render-closing-spec 收口实施) | AGENTS #41 记 SHIMRET「本波次不执行」→ 预研件非施工件 |

### 3.4 docs/design —— v21r4-B / v21r5 波过程件 + 剩余规格（合并区间条目）

| 覆盖文件（显式列出） | 件数/字节 | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置 | 依据 |
|---|---|---|---|---|---|---|---|
| `v21r4-b-*-log.md` 席位日志 34 件: ACCEPT-PREP / CHARTER / DIRECT-PLAN / DOC-SYNC / DOCS / HANDBOOK-SYNC / INTEGRATE / L41-PLAN / LEDGER / LEGACY-FIX / LIVE-TOOL / MAT / MEM-DEC / MYPY-FIX / PORT-PLAN / QA-PROBE / REG-REFRESH / REM-DAWN / REM-EVE / RESTART-GATE / RET2B-PREP / RET2b-R / RET3 / RK5 / RWC5-b / RWC6-b / S0-COLLECT / S0-ROOT / SYNC-FINAL / TOKEN-AUDIT / WIRE-DIRECT / WIRE-SVC / 20260920-alert-triage + `v21r4-b-coordination.md` | 35 / 合计 219956 / 全 U | 过程件(v21r4-B 并发波断点续跑依据) | B10 | B01/B02/B08/B09 | 服务装配/端口方案/矩阵回填/垫片退役/直连收编/命令评审 | 归档; **RET2B-PREP / RET3 / RET2b-R / RWC5-b / RWC6-b 五件缓归档**(它们是三梯队退役的实际执行账, 与 shim-retirement-inventory 配对才有意义) | 首行「席位: X」+ 自述「断点续跑依据」; AGENTS #42 逐席引用 |
| `v21r4-L41-decision-memo.md` / `v21r4-l41-exec-runbook.md` / `v21r4-b-L41-PLAN-log.md` | 3 / 43001 / U | 已失效(L41 由 v21r4-B WIRE-SVC 明确「不接」, 预案≠授权) | B04 | B09/B10 | MEM-001 记忆服务生产接线裁决与预案 | 归档, 但**须先在 v21r4-l41-exec-runbook 顶部补「已被取代」横幅**再移 | 两文件头注自证「不构成实施授权」; AGENTS #42 ⑤ 记 L41 仍 not_wired |
| `v21r4-L60-立项书.md` / `v21r4-L71-立项书.md` / `v21r4-L74-立项书.md` | 3 / 44346 / U | 现役待裁(立项书, 开放 5/6/7 条待用户裁) | B04 | B03/B09/B10 | 历史误扣重放 / 自修复待审补丁 / admin 取验收产物 | 并入对应板块的「待裁」表(B04 / B10 / B09) | AGENTS #42 ⑤ 记三立项书各带开放裁决条 |
| `v21r4-b-doc-sync-draft.md` / `v21r4-b-wave-snapshot.md` / `v21r4-b-qa-probe-report.md` / `v21r4-b-restart-gate-snapshot.md` / `v21r4-b6-ledger-memo.md` / `v21r4-command-format-review.md` / `v21r4-kb-drift-explainer.md` | 7 / 122543 / U | 过程件(波末草案/快照/调研备忘/评审材料/科普说明) | B10 | B02/B09 | 文档增量草案 / 整合快照 / 回归快照 / 台账调研 / 命令格式评审 / kb_drift 说明 | 归档; wave-snapshot §二「50+ 项用户裁定点指针」须先并入 B10 决策索引 | 自述多为「只读汇总零结论新增」 |
| `v21r5-*-log.md` 席位日志 33 件: BACKFILL / CAMPUS / CAMPUSTH / CLEANUP / CRITFIX / DECISIONS / DOCS / DOCSCONSIST / DOSSIER / FIFTHR / FINALREVIEW / FIXN1 / FIXN1B / FIXU17 / HANDOFFADD / HELPSNAP / HYGIENE / INTIMACY / MINORSWEEP / POLICY / POLICYDOC / RENDERPROBE / RESTART / RESTARTCAMPUS / REVERIFY / REVIEW / TIMEOUT / U17CODE / U17DOCS / U17IMPL / U17PLAN / U17REVIEW / U17VERIFY / VERIF | 34 / 合计 246607 / 全 U | 过程件(v21r5 三任务波 + U17 收编链) | B10 | B03/B07/B02/B09 | 超时根治 / 亲密模式 v3 / R-18 放宽 / campus 收编 / 门禁预检 / 终审 | 归档; **REVIEW + FINALREVIEW + REVERIFY + CRITFIX + FIXN1(+B) 六件缓归档**——它们构成「未成年红线词面绕过」Critical 关闭链的完整证据, AGENTS #43⑦ 逐条引用 | 首行「席位」+ AGENTS #43 全段按席引用 |
| `v21r5-coordination.md` / `v21r5-C-brief-final.md` / `v21r5-external-failure-dossier.md` / `v21r5-frontend-handoff-package.md` / `v21r5-help-registry-snapshot.md` | 5 / 22560 / U | 过程件(协同登记 / 派遣简报 / 外部失败归因 / 跨会话交接包 / 对照基线快照) | B10 | NONE | 波次协同与外部失败归因 | 归档; external-failure-dossier 的归因表须并入 B10「已知外部失败」 | dossier 首行给出「9953 passed / 5 failed」实跑数, 属时点证据 |
| `audit-20260919-unify-wave.md` | 37289 / U | 历史证据(09-19 统一收尾波独立审计) | B10 | NONE | 渲染统一 + WebUI 路线 B 实况审计 | 归档 | 自述「独立第三方审计(非交付席自报)」, 后继为 09-20 U1–U24 波与 audit-20260921 |
| `link-unification-audit-20260920.md` | 63579 / T 09-20 | 历史证据(全仓链接归一审计) | B10 | NONE | 接口/模块/参数/文档六类归一取证 | 归档; 现役「真身优先路由」以 audit-20260921 §9 为准 | 时点快照件, 引用前须重定位行号(自述) |
| `outbound-template-unification-spec.md` | 11374 / T 09-20 | 现行规格(**待用户过目, 未开工**) | B08 | NONE | 统一出站模板层(邮件 HTML+卡片图附件) | 并入 B08 出站节并标「未实施」 | 状态行自述「待用户过目, 未开工」 |
| `backend-protocol-plan.md` / `frontend-render-expansion-plan.md` | 2 / 34003 / U | 已失效(两份 v21r4 自包含交接书, 波次已收官) | B01 / B08 | B10 | 后端协议工作包 / 前端渲染扩展工作包 | 归档; 与 HANDOFF-V21R4-B/F 同批处置 | 自述「交接文档」性质; `docs/design/backend-protocol-plan.md` 在 `_NARRATIVE_DOCS` 清单内 ⇒ **动它须先改门**(见 §6) |
| `webui-dashboard-spec.md` / `webui-pages2-spec.md` / `webui-axonhub-adoption.md` | 3 / 39997 | 现行规格(WebUI 一期/二期/采纳路线) | B09 | B08 | 仪表盘 / 知识库·插件·记忆图谱三页 / AxonHub 路线 B | 并入 B09 WebUI 节; 与 webui 前端代码实态核对后标未做项 | AGENTS #41 记二期三页真数据已全部交付（比例以该席记录为准） → 规格与实况需对账 |
| **小计**: docs/design 顶层 236 件全部覆盖(§3.1–3.2 逐条 42 件 + §3.3–3.4 合并 194 件) | 236 | — | — | — | — | — | 脚本 `os.listdir` 实数, 与 `find` 计数一致 |

### 3.5 docs/design/unify-audit-20260919/（58 件，前端统一审计波；09-21 时点值，现数以该目录现算为准）

> 全组共同事实: **58 件全部已入库(T)、末次提交日 2026-09-19/20**（件数与入库态为 09-21 判定时点值，现役以 `git log` 与该目录现算为准），性质=「前端 = WebUI + 卡片渲染」的审计与整改台账（用户 09-19 裁定口径）。它们与 `docs/audit-20260921.md`（全仓统一性审计）是**两波不同范围的审计**，不构成取代关系。板块归属集中说明: 本组以 **B08 渲染** 与 **B09 控制面/WebUI** 为主，B01/B06 为次。

| 覆盖文件（显式列出） | 件数/字节合计 | 现役性 | 主板块 | 次板块 | 一级/二级功能 | 处置 | 依据 |
|---|---|---|---|---|---|---|---|
| `F2-webui-api-contract` / `F3-webui-pages-a11y` / `F4-gates-and-dist` / `F5-card-render-tokens` / `F7-webui-security` / `F8-webui-performance` / `F9-webui-consistency` / `F10-webui-engineering` / `F11-contrast-visual` / `F12-routing-ia` / `F13-metric-semantics` / `F14-card-ia` / `F15-voice-chain` / `F16-class-conflicts` / `F20-localization` / `F22-render-rollout-plan` / `F23-frontend-testable-draft` / `F25-spec-gap` | 18 / 约 660000（区间 11956–119564 B） | 历史证据(F 系**只读快照审计**，逐件自述「快照声明 + date 实跑」) | B08 | B09/B06/B01 | WebUI 契约/无障碍/门禁产物/token 单一来源/安全/性能/一致性/工程底座/对比度/信息架构/指标口径/卡片 IA/语音链/类名冲突/本地化/渲染施工/可测性/规格差距 | 归档;**F14/F16/F22/F23 四件缓归档**——F14 卡面骨架与 F16 类名根治方案仍是未落地提案, F22 是渲染域施工真身 | 每件首行「快照声明」自证只读; 行号已随 09-20/21 改树漂移 |
| `F2b-memory-graph-degraded` / `F4b-gate-blindness-repro` / `F11b-contrast-measured` / `F12b-impl` / `F17-change-review` / `F18-gate-residency` / `F19-gate-teeth` / `F19-gate-teeth-prescan` / `F21-metric-recheck` / `F24-doc-reconciliation` / `DOC1b-impl` | 11 / 约 292000 | 历史证据(修复制品/实施台账/独立复算/对账单) | B08 | B09/B10 | 记忆图谱降级修复、验收门「无牙」实证、实测对比度账、移动导航抽屉、改动敌对复核、三门常驻化、宪法门补牙、指标复算、文档宣称↔实盘对账 | 归档; **F24 + DOC1b 两件保留**(它们是「文档宣称 vs 实盘」对账的原始底稿, audit-20260921 沿用其方法论) | F21/F17 自述「敌对性复核」= 二次审计件 |
| `COPY-V2-wave-plan` / `COPY-V2-voice-brief` / `COPY-V2-C2-C4` / `COPY-V2-C5` / `COPY-V2-C6-C7` / `COPY-V2-C8-C9` / `COPY-V2-C10-C12` / `COPY-V2-C13-C14` | 8 / 199352 | 半过程件(出站文案 v2 批次单 + 文风锚点册 + 六份变体稿) | B03 | B08 | user_copy 五池话术 / 错误卡人话区 / 群聊 ack / 管理员门 / 数据源失败 / Mail 文案 / 运营告警字段 | **voice-brief 升为 B03 正文**(自述「唯一语气基准」); 六份 C 号变体稿并入 `domains/chat_reply/capabilities/user_copy.py` 与 `error_report.py` 后归档 | 各件头注给出落地文件真身路径, 可直接核对是否已灌 |
| `OUTBOUND-COPY-AUDIT` / `OUTBOUND-TEMPLATES-FULL` | 2 / 102455 | 现役偏旧(出站文案全量审核 + 模板全量清单, 09-20 时点) | B08 | B03 | QQ/TG/Mail 出站文案与触发条件全表 | 并入 B08 出站节(与 outbound-template-unification-spec 合并为一份) | 自述「行号=当时快照, 引用前重定位」 |
| `PERF1-impl` / `PERF1-fix1` / `PERF1-fix2` | 3 / 59287 | 过程件(日志尾流页 + 记忆图 canvas 性能实做与两轮修复) | B09 | B08 | WebUI 前端性能 | 归档 | 首行「席别: PERF1* 实施席」 |
| `R5-impl` / `R5-fix1` / `R5-fix3` | 3 / 62125 | 过程件(**R5-fix2 编号缺件**, 全目录无该文件) | B08 | B10 | 版式宪法门 ⑧⑨ 族脱栅任意值收口 | 归档; R5 系结论应回写 `docs/rendering-contract.md` 机器门段 | 三件互相引用 fix round 1/5, 但 fix2 不在盘 ⇒ 波次未连续或该席零产出 |
| `UNI1-impl` / `UNI1-fix1` / `UNI1-fix2` | 3 / 47621 | 过程件(前端「同一判据四套实现」收口 + 对账门补强) | B08 | B10 | 跨语言对账门 `tests/test_webui_labels_backend_parity.py` | 归档; 其对账门本身属 B10 门禁件 | 各件头注指 `.superpowers/sdd/FRONTEND-AUDIT/review-UNI1-report.md` |
| `AVT1-impl` / `CAP1-impl` / `CAP2-impl` / `CAPFIX-impl` / `CAPFIX-B-impl` / `VIS1-impl` / `S8-render-webui` / `K1-knowledge-paths` | 8 / 约 136000 | 过程件(bot 身份可参数化 / 全站品牌胶囊三面 / 契约锁补真 / 视觉整改 / 渲染+前端敌对审计 / 知识路径调查) | B08 | B03/B09/B04 | bot_avatar 多 bot / 品牌胶囊 / 卡片视觉 / BOT_KNOWLEDGE_FILES 缺件 | 归档; **K1 缓归档**——它记录的 `BOT_KNOWLEDGE_FILES` 外部知识缺件仍未闭环, 结论要并入 B04 | AVT1/CAP1/CAP2/VIS1 首行 `Status: DONE` = 施工完; CAPFIX 首行 `Status: STARTED` = **未收口即停笔** |
| `FRONTEND-AUDIT` / `HANDOFF-PROMPT` | 2 / 25115 | 本波「唯一读数入口」总账 + 接手提示词(历史) | B10 | NONE | 前端统一审计总账 / 波次接手 | 归档; 归档前把总账指针改指 boards 目录 | HANDOFF-PROMPT 自述「先读 FRONTEND-AUDIT(唯一读数入口)」→ 两件互指, 移树须成对 |
| **小计** | 58 | 全部已入库, 与 `os.listdir` 计数一致 | — | — | — | — | 编号缺件报备: F1、F6、R5-fix2 三号在本目录不存在(只据文件名实盘, 不猜原因) |

### 3.6 docs/superpowers/（plans 6 件 + specs 3 件，全部已入库；09-21 时点值，现数以该目录现算为准）

| 路径 | 字节 | 现役性(末次提交) | 主板块 | 次板块 | 一级/二级功能 | 处置 | 依据 |
|---|---|---|---|---|---|---|---|
| docs/superpowers/plans/2026-08-30-media-contract-and-parsers-zh.md | 19761 | 历史实施计划(09-07; 解析器 34 件已建成) | B05 | B06 | 统一媒体契约与解析器迁移 | 归档 | 首行「供执行代理使用: 必须使用 superpowers:…」= 一次性驱动计划 |
| docs/superpowers/plans/2026-08-30-music-backend-v2-zh.md | 26708 | 历史实施计划(09-07; 点歌 5 供应商已上线) | B06 | B05 | 音乐元数据/点歌统计/订阅/榜单 | 归档 | 同上形态 |
| docs/superpowers/plans/2026-08-30-subscription-v2-and-social-adapters-zh.md | 30377 | 历史实施计划(09-07; subscribe_v2 已建成) | B05 | B07 | 订阅 V2 与社交平台 Adapter | 归档 | 同上 |
| docs/superpowers/plans/2026-09-05-backend-core-slice-zh.md | 8163 | 历史实施计划(09-07) | B09 | B02 | 后端核心回复执行单元 | 归档; 现役口径改指 `docs/design/control-plane-core-status.md` | 自述「REQUIRED SUB-SKILL: executing-plans」= 计划件 |
| docs/superpowers/plans/2026-09-06-defensive-context-compiler-plan.md | 4671 | 历史实施计划(09-06) | B03 | B04 | 防御型上下文编译 + Prompt 审计 | 归档(反注入包裹已在 chat 链落地) | 与同目录 spec 配对, 成对移树 |
| docs/superpowers/plans/2026-09-12-shorekeeper-global-audit.md | 14064 | 历史实施计划(09-13) | B10 | B03/B08/B05 | 全域人格/命令文档/统一卡片/金融能力 | 归档; 逐席证据链在 `.superpowers/sdd/2026-09-12-shorekeeper-global-audit/` | AGENTS 第七部分点名该 sdd 目录为 B 方向交接件 |
| docs/superpowers/specs/2026-08-29-social-music-backend-v2-design.md | 30754 | 历史设计规格(09-07) | B06 | B05 | 社媒解析/订阅/音乐后端 V2 设计 | 归档 | 三份 08-29/08-30 件是同波 plan/spec 成对件 |
| docs/superpowers/specs/2026-09-06-defensive-context-compiler-design.md | 3299 | 历史设计规格(09-06) | B03 | NONE | 防御型上下文编译设计 | 归档(与 plan 成对) | 同上 |
| docs/superpowers/specs/2026-09-09-video-understanding-design.md | 23454 | **现行待实施设计**(09-11; 视频理解 Media Registry) | B06 | B05/B08 | 视频理解前置管道 + 人格化守则 | 保留原地并挂「未实施」标; 并入 B06 待建节 | 头注「待裁」+ 全仓未见 media registry 实施文档承接 |

## 4. `.superpowers/sdd/**` —— 目录级判定（波次目录数、文件数与体量以该目录现算为准，本册不复制；下表为 09-21 时点判定）

> 全树共同事实（实测，非推断）: 根 `.gitignore:42` 写 `.superpowers/`，目录内另有 `.gitignore` 内容为 `*` ⇒ **整个 sdd 树不入库、git 不可溯**。它因此**既不是源码也不是文档资产**，而是「多代理施工的工作记忆」。
> 判定口径: 逐目录只读目录列表 + 计数，不逐文件读。
> 通用红线: 目录内被 **AGENTS.md 台账与 docs/HANDBOOK.md 明文点名**的文件（`master-plan.md`、`uncommitted-inventory.md`、`commit-checklist.md`、各 `progress-*.md`/`report-T*.md`）是那些叙述件的**证据指针落点**——**移出即令 AGENTS/HANDBOOK 的引用悬空**，属「动它须先改（改的是引用方）」。

| 目录 | 文件数/字节 | 形态 | 主板块 | 次板块 | 已被 HANDBOOK/AGENTS 吸收？ | 处置建议 | 判定依据 |
|---|---|---|---|---|---|---|---|
| `.superpowers/sdd/2026-09-12-shorekeeper-global-audit/` | 94 / 1136129 | 过程件为主(fix-*-report/brief 逐号 + final-review-report + baseline-perf + 2 份 .diff) | B10 | B03/B08/B05 | 是——AGENTS #26 与 HANDBOOK §21 直引该目录 | 归档为 zip（按归档规程压缩→验证→移出），**AGENTS #26/HANDBOOK §21 引用行需同步改为归档路径** | 文件命名全为「席位报告」形态；有 .diff 说明含施工原稿 |
| `…/2026-09-13-six-domain-batch/` | 77 / 639573 | 过程件(*-report 逐席 + FINAL-REPORT-draft + RESUME) | B10 | 全域 | 是——AGENTS #31 明文「各席报告实跑证据齐(…/2026-09-13-six-domain-batch/)」 | 归档; #31 指针同步改 | 目录内 76 份 .md 全为席报; 含 1 份 .py(取证脚本)随目录一起走 |
| `…/2026-09-18-unify-wave/` | 53 / 311689 | **规格件 + 过程件混合**(master-plan.md 为主计划, commit-checklist.md 为待提交清单, progress-*.md 45+ 份席账) | B08 | B09/B10 | 是——AGENTS #41 三处点名(master-plan / 逐席 progress / commit-checklist) | **暂缓全部**: `commit-checklist.md` 是「未提交逐文件显式 add 清单」的现役依据，qx.json 新家与 usage_cards 真身两要害置顶项未提交前不得移 | AGENTS #41 明文「未 commit——工作树逐文件显式 add 清单见 …/commit-checklist.md」 |
| `…/2026-09-19-emergency-info-unify/` | 71 / 1318150 | 过程件 + 数据件(planning-with-files 三件套 + 5 .json + 1 .geojson + 1 .sh + .diff) | B05 | NONE | 是——AGENTS #45 引 emergency 系列 | 归档; **.geojson 随包**（地名/坐标数据，重取成本高） | 顶层三件 findings/progress/task_plan 为 planning-with-files 会话产物形态 |
| `…/2026-09-19-unify-audit/` | 123 / 2218098 | **Wave G/H TTS 波档案**: plan-G-contract.md(规格真身之一) + briefs*.md + report-T10…T121 逐席 + closeout-manifest.md + 两份 -DRAFT | B06 | B01/B08/B10 | 是——AGENTS #44 全文按 T 号引用，并点名 plan-G-contract / closeout-manifest / report-T36 | **只 plan-G-contract.md 与 report-T36(§2 新版验收判据) 不可移**；其余 T 号席报可归档并改指针 | AGENTS #44 明文把这两件当现役验收/规格入口用 |
| `…/2026-09-20-spec-audit/` | 28 / 484208 | 过程件(audit-SA*/FIX*/IALERT/IGEN2/ISYNC 席 log) + 1 份 directive-capability-contract.md(指令件) | B02 | B10 | 部分（directive 与 AGENTS #47 WP8 相关） | 归档; `directive-capability-contract.md` 若仍是调度层采纳依据则并入 B02 附录 | 文件首行命名法为审计/修复席位；无 master-plan 即非波次总纲 |
| `…/2026-09-20-unify-fix-wave/` | 36 / 217729 | 过程件(master-plan.md + progress.md + 34 份席 log) | B10 | 全域 | 是（上一子波交接，AGENTS #47 提及「上子波」保留的两项） | 归档（#47 已把上子波两项结论接管） | 仅两件顶层总纲，席 log 为其拆解 |
| `…/2026-09-21-fix-wave/` | 13 / 333146 | **现役**: master-plan.md（§捌＝交接态四态表/禁碰面/证据地图/复跑命令簿）+ uncommitted-inventory.md + impl-WP1…WP11B 逐工作包 log | B10 | 全域 | 是——AGENTS 顶部横幅、#47 与本席任务简报三处点名 | **绝不可移/不可删**: 本波未 commit，`uncommitted-inventory.md` 是唯一「哪些改动还没进 git」的账；移树即丢失未提交全量清单 | AGENTS #47 明文「逐符号明细与未提交全量清单见 …/master-plan.md §捌 + uncommitted-inventory.md」 |
| `…/2026-09-21-unify-consolidation/` | 29 / 1162068 | 过程件(deep-D1…D6/E1…E6 + line-1…11 逐条线 log + findings.md) | B10 | 全域 | 待定——AGENTS/HANDBOOK 尚未见对本目录的直接点名（本席只在 #47 相邻波次语境中见到，缺独立确认） | **不动**，标「待定」；需补的证据=确认该波是否已收官并落 HANDBOOK 总账 | 单文件均值偏大（体量以现算为准，属最大目录之一），说明仍在写；无 master-plan 顶层件 |
| `…/FRONTEND-AUDIT/` | 15 / 425174 | 评审件(review-*-report + 6 份 .diff 复核原稿) | B08 | B10 | 是——`docs/design/unify-audit-20260919/R5-fix1.md` 等直引 `review-R5-report.md` | 与 §3.5 的 R5/PERF1/UNI1 系**同批处置**，单独移走会让那批席报引用悬空 | 目录名与那批席报的引用路径逐字对应 |
| `…/emergency-info-registration-runbook-20260920/` | 41 / 283883 | 过程件(progress.md 总账 + reports/ 十席 log + 14 .txt 探针输出) | B05 | B10 | 是——AGENTS #45 明文「详总账=…/progress.md + reports/ 十席 log」 | 归档前必须先把 #45 指针改到新落点；**.txt 是探针实跑原始输出，属证据不可重造，随包** | AGENTS #45 与施工图 §4 口径更正段两处引用本目录 |
| `…/v21-20260917-parallel/` | 6 / 27247 | 过程件(w1-affinity/w2-gates-baseline/w4-supervisor/w5-billing/w6-divination/w7-search 六席) | B10 | B03/B09/B06 | 是（V2.1 波，编号缺 w3，与 AGENTS #34 语境一致） | 归档 | 六件同名「w<号>-<域>.md」=并行席位分账 |
| `…/v21r6-audit/` | 6 / 76766 | 过程件(audit-A-v21r5 / B-frontend / C-external2 / D-newfailures / audit-report / progress) | B10 | NONE | **待定**——本席未在 AGENTS 顶部横幅与 HANDBOOK 检索到对 `v21r6-audit` 的直接点名（HANDOFF-V21R6-TESTING.md 是同名不同路径件） | 暂不动，标「待定」；缺的证据=确认 V21R6 验收入口是否已吸收本目录结论 | 目录名与根文件 HANDOFF-V21R6-TESTING.md 不同路径，易混为重复件但实非同一物 |
| **合计** | 文件数与字节合计见上方各行汇总 | — | — | — | — | 结论: **三处「绝不能动」= 2026-09-21-fix-wave（未提交账）+ 2026-09-18-unify-wave/commit-checklist.md（待提交清单）+ 2026-09-19-unify-audit/{plan-G-contract, report-T36}（现役规格与验收判据）** | 上表逐行判定汇总 |

## 5. 收尾三节

### 5.1 重复与冲突（同一事实在多份文档各写一遍，前 15 组＝当时取前 15 组、非总数；「真身」= 今后唯一可改处）

| # | 重复/冲突的事实 | 互指的多份文档 | 真身 | 冲突点与后果 |
|---|---|---|---|---|
| 1 | 「冷启动第一入口」是谁 | AGENTS.md 顶部多条横幅、HANDOFF-FIXWAVE-20260921.md、HANDOFF-V21R6-TESTING.md、HANDOFF-PROMPT-20260921.md、docs/design/COMPACT-CHECKPOINT.md、HANDOFF-NEXT.md | AGENTS.md 顶部横幅 | 横幅互相声明「优先于下方各条」，新 AI 无法定序；HANDOFF-NEXT 已失效但仍被 docs/README 与 HANDOVER-2026-09-15 指为入口 |
| 2 | 好感度步长算法 | docs/affinity-design.md(v4/v5+附录 v6) / docs/design/affinity-v7-design.md / AGENTS 第四部分好感度行 / docs/HANDBOOK.md 各 § | `character/affinity.py`(代码) + affinity-v7-design.md(规格) | affinity-design.md 头部虽声明让位，正文数值未删；AGENTS 仍写「v5 多因素线性步长」→ v7 已换 tanh 潜变量，文实相反 |
| 3 | TTS 契约与参数域 | docs/design/tts-contract-layer.md / tts-handover-20260919.md / tts-audit-20260919.md / HANDOVER-TTS-GH-20260920.md(自称穷尽版 v2) / AGENTS #44 | tts-contract-layer.md(规格) + domains/media/capabilities/tts.py | 四件各写一遍钳制域/硬顶/退避窗；改一处必漏三处 |
| 4 | 命令口径与帮助主题 | COMMANDS.md / docs/command-catalog.md(生成物) / `_HELP_ENTRIES`(真身) / docs/design/v21r2-command-spec.md + entries-1/2/3 + inventory / v21r4-command-format-review.md / docs/route-matrix.md | `capabilities/echo.py::_HELP_ENTRIES` → `scripts/command_catalog.py --write` | 手写的 spec-entries 三件与 inventory 冻结了旧计数(自述 77 topics)；review 件还在提议改名 ⇒ 三份"规范"并存 |
| 5 | 配置键目录 | docs/config-catalog-full.md / .env.example / config.py / docs/ai-setup-knowledge-pack.md §6 / ai-kb-operations-manual.md | `config.py` 单一 Config | config-catalog 已被 AGENTS #27⑦/#44⑨ 两次点出「截断失实/需补录」⇒ 手写目录必漂移 |
| 6 | 渲染 token 与铁律 | DESIGN-SPEC.md(根) / docs/rendering-contract.md / docs/boards 拟稿 / AGENTS 第三部分 / v21r3-render-closing-spec.md / .superpowers 09-18 unify-wave | `domains/render/card_render/theme_tokens.py` | 四份 md 全在 `verify_hashes` 哈希清单内 ⇒ 任一处「顺手改文案」即触发哈希门红，是最高频假红源 |
| 7 | QQ 协议端口径 | docs/napcat-setup.md / docs/snowluma-setup.md / docs/acceptance-manual.md / 全树 ~30 份复制的「术语说明(NapCat 指 09-18 之前)」横幅 | docs/snowluma-setup.md | 同一「术语说明」横幅被逐字复制进数十份 md（`test_doc_link_integrity` 的行级史实豁免正依赖它），删任一条会让对应坐标重新判红 |
| 8 | 紧急信息装配门 | docs/design/emergency-info-registration-runbook-20260920.md §5-钉死②(三重门) vs AGENTS #46 裁定 3.B(缩成两腿) vs emergency-info-enablement-20260920.md(仍按「没有名单则零行为变更」写) | 代码 `build_emergency_info_source` + AGENTS #46 | **现役互斥**：按 runbook 施工会重新加第三腿；enablement §七 用户面用法与 .env 旧注释互相矛盾 |
| 9 | 待用户裁决清单 | docs/pending-decisions.md(09-14) / docs/audit-20260921-decisions.md / v21r4-L41/L60/L71/L74 / r18-taxonomy-20260920.md / .superpowers/sdd/2026-09-21-fix-wave/master-plan.md §8.6 P-1…P-5 / docs/design/backend-v2-* 开放问题 | 各自独立，无聚合件 | 六处待裁并存且部分已裁未回写(L41 已在 #42 记 not_wired 但 memo 仍呈「待裁」) |
| 10 | 工作区边界与归档规则 | docs/workspace-archive-policy.md / docs/external-runtime-access.md / AGENTS 第一部分 1-2 条 / docs/README.md 导览 | AGENTS 第一部分 | 三件重复且其中两件对 Runtime 只读边界措辞不同，AI 避扫规则出现两个版本 |
| 11 | 四波「唯一读数入口」互相指认 | docs/audit-20260921.md / docs/design/audit-20260919-unify-wave.md / docs/design/audit-20260920-unify-summary.md / docs/design/unify-audit-20260919/FRONTEND-AUDIT.md | 无——四件范围不同但**都自称唯一入口** | 需要 B10 的「审计索引」消歧，否则下一 AI 会挑错基线 |
| 12 | 架构五层图与消息主链路 | docs/HANDOVER-2026-09-15.md / AGENTS 第三部分 / docs/design/backend-v2-implementation-guide.md / 审查结论与重构计划.md | AGENTS 第三部分 | 四份各画一图，域数/能力数(「29+ 能力」)不一致 |
| 13 | SQLite 库归属与计数 | docs/db-owners.md / AGENTS 旧口径 / config.py `*_db_path` / docs/HANDBOOK §三 | db-owners.md + `test_db_owners_coverage.py` 双向锁 | AGENTS 已明文「手写过的版本 32 已过期一次」，但 HANDOFF 系列仍留旧库数 |
| 14 | 出站/文案变体池 | unify-audit `COPY-V2-*` 六份稿 / `OUTBOUND-COPY-AUDIT.md` / `OUTBOUND-TEMPLATES-FULL.md` / `user_copy.py` / `error_report.py` / docs/design/outbound-template-unification-spec.md(待裁) | 代码两文件(池真身) | 文案变体同时存在于「稿」与「码」，改码不改稿 ⇒ 稿成为假需求源 |
| 15 | 会漂移的总数（字段/topics/别名/模板/域/库/测试数） | AGENTS.md / HANDBOOK / CODE-MAP / HANDOFF 系列 / v21r2-command-spec-inventory / audit-20260921 各处 | `docs/auto-facts.md`（由 `scripts/doc_sync.py` 推导） | 已由 `test_documentation_consistency.py::test_narrative_docs_defer_volatile_counts_to_machine_ledger` 执法**但执法面只覆盖 `_NARRATIVE_DOCS` 那批文件** ⇒ 其余 250+ 份 md 里的手写计数仍无人管，是本表最大的结构性风险 |
| 附注（对 §3.4 的勘误，只追加不改写） | `docs/design/link-unification-audit-20260920.md` 在 §3.4 被判「归档」**不成立** | — | — | 它同时被 `tests/test_doc_link_integrity.py:72` 的 `_EXPLICIT_EXEMPTIONS` 钉住，且该门有反向锁 `test_exemptions_are_all_still_needed` ⇒ 移出 `docs/**` 会让豁免不再命中而直接判红；另被 `tests/test_help_single_source.py:8` 指名。**处置改判 = 原地保留、禁移树** |

### 5.2 覆盖缺口 —— `plugins/bot_unified_runtime/domains/` 全部域逐个（现役域清单以 `domains/` 目录为准）

> 「现有落点」只列**该域专属**文档（不含席报里顺带提到的一句）；「缺」= 本席检索后确认无专属文档者。

| 域 | 一级/二级功能 | 现有文档落点 | 缺什么 | 板块 |
|---|---|---|---|---|
| core | session_keys / text_boundary 中央件 | AGENTS #44⑤(中央触发词边界谓词) + #47⑥(会话键全走 session_keys) | **无域级规格**：会话键格式契约与边界字符集只在 70 例测试里，跨域改键无文档约束 | B02 |
| chat_reply | 人格/对话/好感/内容安全/帮助注册表 | affinity-v7-design、r18-taxonomy、backend-v2-product-extensions、v21r2-command-spec 系、v21r2-rp-style-log | 缺「chat 链总览」：13 分区注入顺序、五池话术、称谓体系分散在 AGENTS/人格 md/席报三处 | B03 |
| render | 卡片渲染/模板/主题 token | rendering-contract、DESIGN-SPEC、fstring-card-dom-spec、render-pipeline-optimization-spec、visual-effects-catalog、v21r3-render-* | **不缺，反而重复**：五件钉哈希、两处声明「单一事实源」⇒ 需合并为一份契约 | B08 |
| media | TTS/图片/视频/识图/归档 | tts 三件、media-digest-layer、AGENTS #28(媒体归档) | 缺 media_archive 的**目录结构与 VLM 判类标签表**文档；digest 层未实施 | B06 |
| emergency_info | 预警聚合与订阅投递 | 7 件 design 文档 + sdd runbook 目录 | 不缺文档、**缺一致性**：见 5.1 #8；且「地名→坐标 resolver 未接」只在 AGENTS #46 诚实缺口里，规格件未改 | B05 |
| ops | 错误卡/告警/sync_drift 巡检 | AGENTS #47⑫、#14 台账、error_card 契约 | 缺 sync_drift 巡检器的规格件（该批键刚复活，消费面与告警面无人成文） | B09 |
| weather | 天气+预警双通道 | AGENTS 第四部分、#9(NMC 边界)、emergency-alert-taxonomy | 缺「weather 与 emergency_info 预警谱的对接边界」——同一预警两处出，谁是投递口未定 | B05 |
| finance | 个股/汇率/商品/债券/北向/股指 | AGENTS 第四部分金融行、docs/handover-c-20260913.md | 缺**数据源规格**：东财字段码(f47/f48/f84/f85)、必带 `end` 参数、MOEX history 口径都只在席报与代码注释 | B05 |
| link_parse | 37+ 平台解析 | 2026-08-30-media-contract plan、AGENTS #27④、WP1 凭证咽喉 | 缺**平台清单权威文档**（allowed_hosts/cookie 域名表在代码，「18 平台 cookie 已灌」无处核对） | B05 |
| subscribe | B站/YT/xhs/推特/微博订阅 | 2026-08-30-subscription-v2 plan、v21r2-reorg-w12-log | 缺 feeds 现役清单与降级态（xhs:live degraded、YT live consent）文档 | B05 |
| music | 点歌 5 供应商 + 榜单 | 2026-08-30-music-backend-v2 plan（已归档态） | 缺现役供应商可用性与榜单口径文档（plan 写的与实况差一年） | B06 |
| meme | 表情包库 + 主动发 | AGENTS #35②(reaction_store/双层表情) | 缺 meme_library 的 NSFW 降权与 VLM 标签体系文档；#17「主动发」明确待设计评审却无评审文档 | B06 |
| divination | 八字/塔罗/金钱卦 | divination-consolidation-20260921 | 缺算法规格（Meeus 节气、藏干权重、完整塔罗牌阵）——AGENTS 只给触发词 | B06 |
| schedule | 提醒/督促/每日摘要/快报调度 | v21-s11-schedule-log、v21r2-s11-log、backend-v2-product-extensions §4 | 缺**时区口径文档**：台账 #6(系统本地时区)与 #29⑤(UTC 混用致 13 点报 23 点)两处事故同一根因，无统一成文 | B07 |
| assistant | 收件箱/到点吃什么/早报晚报 | AGENTS #32 | 缺能力级规格与配置说明（该批键在 catalog，但推送名单为空即整链不注册的规则只在 AGENTS） | B07 |
| notes | 笔记 CRUD + 授时 | AGENTS 第四部分笔记行、v21r2-reorg-w9-log | 缺 timesync 规格（±1.5s 钳制、1970 解包门、mode=4-only、65s 首校时——全是行为约束却无文档） | B04 |
| files | 下载/文件网关 | file-transfer-gateway.md(B3 规格) + v21r2-reorg-w9-log | 缺 Phase-1 实况与规格差距对账（B3 尚有开放问题未裁） | B08 |
| food | 菜谱/图库 | AGENTS #30①(clean_food_gallery) | 缺域文档：图库预热 61 道、VLM 防污染黑名单、`food.md` 自定义格式全部无文 | B06 |
| location | 地理编码/城市别名 | v21r2-reorg-w16-log、AGENTS 天气行 F18 | 缺别名表与逐级拆解规则文档（60+ 别名是代码常量） | B05 |
| transport | 发送队列/出站适配器 | v21r2-reorg-w14-log、outbound-* 三件、U3-OUTBOUND 审计 | 缺 **send_queue 幂等协议**文档：part 级幂等/UNKNOWN 确认/PARTIAL 断点续发只在 AGENTS 一句 | B08 |
| creation | 生成域骨架 | v21r2-reorg-wpa1-log（骨架波，§9 字段级契约草案） | 缺功能本体：该域现为骨架，无用户可见能力，应显式标「占位域」避免新 AI 误当已实现（**2026-09-21 当时值，此判词已失效**：该域此后落成协议在册面——描述符与执行体都注册了，缺的是真实 provider 而不是协议，实况见 `docs/boards/B06-media-entertainment/creation/README.md`。"无用户可见入口"那半仍成立：板块生成区里本域没有路由席位也没有能力 id，所以它依然不是一个能被消息触发的功能） | B06 |

### 5.3 归档建议

#### A. 绝不能动 / 动它须先改门（本席实测的门钉清单）

| 被钉对象 | 钉它的门（可复跑证据） | 动它的前置动作 |
|---|---|---|
| **5 份 md 在哈希清单内**: `docs/rendering-contract.md`、`DESIGN-SPEC.md`、`docs/design/fstring-card-dom-spec.md`、`docs/design/render-pipeline-optimization-spec.md`、`docs/design/visual-effects-catalog.md` | `tests/verify_hashes.py` 的 `TRACKED_FILES`（逐条名列，配 `tests/render_hashes.json` 清单与 `test_verify_hashes_coverage.py`） | 改内容或换路径后必 `python tests/verify_hashes.py --write` 重录，且 `.gitattributes` 要求 LF（哈希前统一换行，见其 `sha256_of` 注） |
| `docs/auto-facts.md` | 生成物：`scripts/doc_sync.py`(`TARGET = ROOT/docs/auto-facts.md`) + 全量套件比对 + `scripts/pre_restart_check.py:317` 巡检项 | 改代码面后 `python scripts/doc_sync.py --write`；**禁止手改、禁止移树** |
| `docs/command-catalog.md` | 生成物：`scripts/command_catalog.py`(`DOC = ROOT/docs/command-catalog.md`) | `python scripts/command_catalog.py --write` 重录 |
| `docs/config-catalog-full.md`、`docs/route-matrix.md`、`docs/db-owners.md` | `tests/test_doc_sync_gates.py`(config_catalog 覆盖 + 批次键)、`test_db_owners_coverage.py`(与 config `*_db_path` 双向锁)、route-matrix 触发词覆盖门 | 先加/改键与路由，再同步这三份；移树=直接判红 |
| **`_NARRATIVE_DOCS` 全清单**: `AGENTS.md`、`HANDOFF-NEXT.md`、`HANDOFF-V21R6-TESTING.md`、`docs/README.md`、`docs/HANDBOOK.md`、`docs/CODE-MAP.md`、`docs/config-catalog-full.md`、`docs/acceptance-manual.md`、`docs/design/backend-protocol-plan.md` | `tests/test_documentation_consistency.py:570` 清单 + `test_narrative_docs_defer_volatile_counts_to_machine_ledger` | 改这批文件的**路径**须同步改清单；文件内写会漂移的计数须带「机器册/为准/当时值」指针，否则该门红 |
| `docs/design/link-unification-audit-20260920.md` | `tests/test_doc_link_integrity.py:72` `_EXPLICIT_EXEMPTIONS` **＋反向锁** `test_exemptions_are_all_still_needed`（豁免条目若不再命中任何坐标 ⇒ 红）；另被 `tests/test_help_single_source.py:8` 指名 | **不得移出 `docs/**`**（移出即令豁免失效而红）；§3.4 的「归档」判定据此作废（见 5.1 附注勘误行） |
| 全树 markdown 扫描面 | `tests/test_doc_link_integrity.py:37` `DOC_GLOBS = ("AGENTS.md","COMMANDS.md","docs/**/*.md")` + 棘轮：旧路径 837 / 垫片 3 / 越界 3 / **md 死链 2** / 死坐标 123 / 误导载体 50 / 全量面缺陷总上限 167 / **地板 CARRIER_TRUTH=5**（只许升不许降的那一条） | 移出任何被链接的 md 前先全树 grep 其路径并改指新落点；**死链上限只有 2** ⇒ 批量移树必炸；地板=不许批量删（真身命中低于地板同样红） |
| `.superpowers/sdd/2026-09-21-fix-wave/{master-plan.md, uncommitted-inventory.md}`、`.superpowers/sdd/2026-09-18-unify-wave/commit-checklist.md` | 无哈希门，但**未 commit 期间它们是唯一的「哪些改动还没进 git」账**（AGENTS #41/#47 点名） | 合流 commit 完成前禁止移/删；commit 后方可随该波档案一起归档 |
| `personas/**` 与 Runtime 人格副本、`domains/weather/assets/qx.json` | AGENTS 铁律 6/8 + `.gitignore` 否定规则 + 人格源-副本一致性门(a1cf739) | 一律不动 |

#### B. 可安全移出（按「一次一个目录」执行，附 manifest）

1. **第一批 · 纯席位日志（≈110 件，低风险）**：`docs/design/` 下 `v21-*-log` 13 件、`v21r2-*-log` 29 件、`v21r2-reorg-*-log` 23 件、`v21r4-b-*-log` 34 件、`v21r5-*-log` 33 件、`audit-20260920-unify-U*` 21 件。理由：文件名整体落在 `_HISTORY_FILE_RE` 的 `audit-*`/`*-log`/`v21*` 豁免形内，移出**只会降低**旧路径计数（安全方向）；先改 `docs/README.md` 索引即可。
2. **第二批 · 草案与快照（≈15 件）**：`v21r2-{agents-ledger,handbook-sync,matrix-backfill,legacy-manifest}-draft.md`、`v21r2-COORDINATION.md`、`v21r4-b-{coordination,doc-sync-draft,wave-snapshot,qa-probe-report,restart-gate-snapshot}.md`、`v21r5-{coordination,external-failure-dossier,frontend-handoff-package,help-registry-snapshot,C-brief-final}.md`。前置：AGENTS #42/#43 与 HANDOFF 系列对它们的引用要逐条改指归档包内路径。
3. **第三批 · 波次档案（.superpowers 与 docs/superpowers）**：`.superpowers/sdd/{2026-09-12-shorekeeper-global-audit, 2026-09-13-six-domain-batch, 2026-09-20-spec-audit, 2026-09-20-unify-fix-wave, v21-20260917-parallel, FRONTEND-AUDIT}` 与 `docs/superpowers/plans/*` 6 件 + `specs/2026-08-29`、`specs/2026-09-06`。前置：AGENTS #26/#31/#44⑨ 的目录指针同步；`FRONTEND-AUDIT` 必须与 §3.5 的 R5/PERF1/UNI1 席报**同批同包**（互相引用）。
4. **根目录一次性件**：`COORDINATION.md`、`HANDOFF-NEXT.md`、`HANDOFF-V21R4-20260918.md`、`HANDOFF-V21R4-B/F-20260918.md`、`V21-UPDATE-LOG.md`、`progress.md`、`report-T116.md`、`report-T124.md`、`审查结论与重构计划.md`。⚠ `HANDOFF-NEXT.md` 在 `_NARRATIVE_DOCS` 清单内 ⇒ 移它须先改那批元组；`docs/HANDOVER-2026-09-15.md` 同（HANDOVER-* 走文件级豁免但被 README 索引链接）。
5. **建议移出但须先加横幅**：`docs/design/COMPACT-CHECKPOINT.md`（现役滚动件，等 FIXWAVE 之后一次收官再移）、`docs/design/v21r2-*-log.md` 中被 AGENTS #42 直接引用的席（先补指针）、§3.5 表中列名的 12 件「缓归档」。
6. **归档规程**（AGENTS 铁律 9）：压缩 → `testzip` + 副本验证 → 移出 → 附 manifest；目标包为归档规程约定的归档 zip（命名与路径以归档规程真身为准）。**不得**重建嵌套 `_Archive` 路径，不得把 Runtime/Archive 设为工作区。
7. **每批移完的复跑集**（不跑 pytest 全量也要跑这三族）：`-Task runtime-layout`、`verify_hashes --check`、`doc_sync --check`、`command_catalog --check`，以及 `test_doc_link_integrity.py` + `test_documentation_consistency.py` + `test_cross_validation_gates.py` 三件。

#### C. 绝不能做的三件事

1. 不得为「让 boards 看起来干净」而删旧文档——本仓的现役事实散在席报里（如 5.1 #15 所述，叙述件执法面只覆盖 9 件），删了就没有第二手证据。
2. 不得在板块正文里复制 `AGENTS.md` / `HANDBOOK.md` 的台账行——只给指针；`_VOLATILE_COUNT_RE` 虽暂不覆盖 boards，但复制即造第 N 份副本（`docs/audit-20260921.md` 已自约束过一次，须沿用）。
3. 不得在共享工作树未 commit 期间搬动任何 `.superpowers/sdd/2026-09-2*` 目录（见 A 表对应行）。

---

Status: DONE — 本席（SEAT-META）续写完成：§3 覆盖 `docs/design` 顶层各件（逐条 + 合并区间，全名已列）+ `docs/design/unify-audit-20260919/` 全组（区间条目）+ `docs/superpowers/` 逐条；§4 覆盖 `.superpowers/sdd/` 各波次目录（目录级判定）；§5 三节（重复与冲突 / 门钉勘误 / 覆盖缺口逐域 / 归档建议 A-B-C）。全表合计新增条目数以脚本现算为准。采集与判定全部由一次性只读脚本完成，未在源码树留下 `__pycache__`/`.pytest_cache`，未跑 pytest，未做任何 git 写操作。


## 6. 2026-09-23 现算跟随（TX216 席，纯加法；§1–§5 原判条目一字未动）

**尺子与时刻**：退役依据册全表行现算，现役标记（现行/现役）行的文件 token 逐枚存在性核查
（首格分词 × 多候选根：repo 根 / `docs/` / `docs/design/` / `docs/design/unify-audit-20260919/`），
缺件者走 `git ls-files` + `git log --diff-filter=D` 取证；读数与逐枚名册以本席报告
`.superpowers/sdd/2026-09-22-taxonomy/SEAT-TX216.md` 与下方复算命令为准（AGENTS 规则 10，此处不手写会漂移的总数）。

**① 结论**：仍标「现役」而真身已删/已迁的条目 = `0` 枚（两遍现算一致，逐枚名册为空）。

**② 表形缺陷（登记不改写）**：§3.2 数行以裸文件名省略 `docs/design/` 前缀、§3.3–3.4 有合并名行
（「a / b / c」共写一格）。凡按「首格=字面全路径」做机器存在性核查者必误判为缺失——本席第一遍即被
此形顶出假缺失，第二遍多候选解析后归零。修法（补全路径 or 行级 token 化尺）交主会话/门 owner 裁，本席不代改历史条目。

**③ code-quality 台账对账**：域内代码锚按 `plugins/bot_unified_runtime/` 现算全命中；
不在盘的 `tests/` 名与 `domains/core/dispatch/` 均系该册自标「拟建·尚不存在」的计划锚而非死锚。

**④ B06–B10 面B**：普查（`spec_gates_census.compute()`，时刻见 SEAT-TX216）面B/面A 对 boards 均零命中，
板块门绿；本席以盲区尺（门词表外量词 + 限额/缺省/下限/钳制上下文）复扫人工区，将真裸默认值行逐行改写为
「以真身为准」指针句（守恒一行换一行、机器段 `BOARD-AUTO` 只字不碰、crlf 前后计数并报），
并顺带修出 B06 媒体归档页的一处默认值口径误称（详见 SEAT-TX216 §4）。

复算命令（只读）：见 SEAT-TX216 §7。


## 7. 2026-09-23 现算跟随（TX268 席，纯加法；§1–§6 原判条目一字未动）

**尺子与时刻**：现算取数时刻 2026-09-23（本会话内 `find` / `wc -c` 逐枚实测）。
尺子 = 用户四条「板块归属」新裁定（外部/半外部资产不占 bot 板块）× 本仓 `docs/`、`personas/`、`tests/`
三面的文件存在性核查。字节数为现算值，随树漂移，只作时点证据（AGENTS 规则 10）。
本册 §1–§6 采集面 = 根 `.md` / `docs/*.md` / `docs/design/**` / `.superpowers/sdd/**`；
`personas/**` 与 `tests/**` 非原采集面，本席按裁定补记并逐枚点名。参照 §6 的做法——**只追加、不改写历史条目**。

**四条裁定要点（依据源 = 用户消息）**：
- **裁定一（外部引擎）**：Crawl Wiki 引擎**设计文档**与其**部署 docs** → 主板块 NONE；若确是 bot 侧知识库**操作界面**则归 B09。
- **裁定二（半外部件）**：借鉴设计参考、第三方通告、官方文档快照、提示词合集、竞品调研 → 主板块 NONE、次板块 NONE。
- **裁定三（知识库素材）**：核心知识、身份、世界观、表达规范、偏好配置等人格设定材料 → 主板块 B03，次板块可留 B04。
- **裁定四（机器册与生成物）**：机器册、command-catalog、render_hashes、render_samples 等脚本派生的账/册 → 主板块 B10。

### 7.1 本仓**在册且需改对**的条目（历史行一字不动；下表为「现算改对值」，其效力取代对应历史行）

| 路径 | 字节(现算) | 现役性 | 裁定 | 主板块（历史行 → 改对） | 次板块（历史行 → 改对） | 判定依据 |
|---|---|---|---|---|---|---|
| `docs/THIRD_PARTY_NOTICES.md` | 3996 | 现行权威 | 二 | §2 表 `B08` → **NONE** | §2 表 `B10` → **NONE** | 第三方出处/许可合规件＝半外部资产，不占 bot 板块（外部/半外部不占板块的总则）；此件被 `tests/verify_hashes.py` 钉住＝「禁移树但主板块判 NONE」，与 §6 已确立口径一致 |
| `docs/command-catalog.md` | 171176 | 生成物(现行) | 四 | §2 表 `B02` → **B10** | §2 表 `B05/B06` → 不变 | 由 `scripts/command_catalog.py --write` 派生的生成物＝机器册族，与 `docs/auto-facts.md`（§2 已 B10）同族同归；本裁定只点名改主板块，次板块（内容确为命令口径）保持 |

### 7.2 本仓**在册但无需改**的条目（现算核对，列出以免下一席重判）

| 路径 | 裁定 | 现值 | 结论 | 依据 |
|---|---|---|---|---|
| `docs/auto-facts.md` | 四 | §2 已 `B10`（次 `B09`） | 无需改（任务亦明示别为它动门） | 生成物机器册，已正确归 B10 |
| `docs/ai-kb-operations-manual.md` | 一 | §2 已 `B09`（次 B03） | 无需改 | bot 侧知识库**操作界面**说明书，按裁定一末句正应归 B09，本就正确 |
| `docs/ai-setup-knowledge-pack.md` | 一 | §2 已 `B09`（次 B10） | 无需改 | 同上：知识库操作全集，归 B09 正确 |
| `docs/search-api-adapters-2026-09-06.md` | 一/二 | §2 已 `B05`（次 B09） | 无需改（**非**官方文档快照） | 它是 bot 实际调用 Tavily/You/LangSearch 的**适配与回退顺序**规格（B05 外接数据服务真身件），不是「LangSearch 官方文档快照」这类半外部拷贝，不适用裁定二 |

### 7.3 本仓**原账未覆盖、按裁定补记**的条目（rule 5：新增并逐枚点名；仅登记归属，不移文件、不改文件本体）

`personas/**`（人格设定材料本体）与 `tests/render_hashes.json`（哈希台账）不在 §1–§6 采集面内；
裁定三/四点名它们，本席补记现算归属。**`personas/**` 为 AGENTS 铁律 6/8 禁写面——本席只读其存在性，
绝不移动或改写任何 persona 文件**；此表只是给它一个板块归属记录。

| 路径 | 字节(现算) | 现役性 | 裁定 | 主板块 | 次板块 | 一级/二级功能 | 处置 | 判定依据 |
|---|---|---|---|---|---|---|---|---|
| `personas/shorekeeper/identity.md` | 16349 | 人格资产(禁写面) | 三 | B03 | B04 | 身份与称谓设定（人格素材） | 原地保留，仅登记归属 | 核心人格设定件 → 裁定三归 B03 |
| `personas/shorekeeper/knowledge/守岸人_核心知识.md` | 81749 | 人格资产(禁写面) | 三 | B03 | B04 | 核心知识（人格素材） | 同上 | 裁定三核心知识面本体 |
| `personas/shorekeeper/knowledge/守岸人_人格与表达规范.md` | 157651 | 人格资产(禁写面) | 三 | B03 | B04 | 人格与表达规范（人格素材） | 同上 | 裁定三表达规范/偏好配置本体 |
| `personas/shorekeeper/knowledge/worldview_glossary.md` | 4709 | 人格资产(禁写面) | 三 | B03 | B04 | 世界观术语表（人格素材） | 同上 | 裁定三世界观面本体 |
| `tests/render_hashes.json` | 2580 | 生成物台账 | 四 | B10 | NONE | 交付物哈希台账（生成物） | 原地保留 | `tests/verify_hashes.py` 派生哈希账＝机器册族，归 B10 |

### 7.4 裁定点名但**不在本仓**的对象（边界如实账，勿误当已处理）

- **裁定一「Crawl Wiki 引擎设计文档（6 份）与两份讲 Crawl Wiki 部署的 docs」**：`Crawl Wiki` 是外部仓
  （本仓只读集成，指针见 `docs/config-catalog-full.md` 的 `BOT_KB_WIKI_*` 节，及 `docs/HANDBOOK.md` 停摆根修段所指外部路径），
  **其引擎设计与部署文档不在 ChatBot 工作树内**，本册无从对其建行/改行。本仓与之相关的只有 bot 侧集成面
  （config-catalog B09、`domains/location/knowledge/kb_wiki.py`、板块页 `docs/boards/B07-schedule-automation/scheduled-jobs/kb-wiki-sync-scheduler.md`），
  均已正确落位，属「操作界面/集成」而非「引擎设计文档」，按裁定一末句正应留 B09/B04，无 NONE 可改。
- **裁定二「借鉴设计参考（`design-reference.md`）、提示词合集、竞品调研」**：本仓 `find` 对这三类**零命中**
  （属外部设计聚合仓资产）；本仓唯一实存的半外部件是 `docs/THIRD_PARTY_NOTICES.md`，已在 7.1 改对。
- **裁定四「`render_samples/*.md`（9）」**：本仓**无** `render_samples/` 目录（`find -type d -iname '*render_sample*'` 零命中），
  该样张册属外部设计仓；本仓 render 侧对应的哈希台账是 `tests/render_hashes.json`，已在 7.3 补记 B10。
- **裁定三点名的「`docs/design` 面人格素材文档、`personas/shorekeeper/*.md`、Runtime 人格副本」**：
  本仓 `docs/design/**` 经关键词核对，命中的都是**算法规格件**或**席位过程件**，均非「人格设定素材本体」，
  按各自主题留板块，不适用裁定三（个别件已在 §3.5 判为 B03/B08 语境，指针见彼处）。人格素材**实体**在本仓为
  `personas/shorekeeper/*.md`（枚数以本报告 §7.3 表为准），已在 7.3 补记。**Runtime 人格副本在运行数据根
  （工作区外，AGENTS 规则 1 不索引、不扫描、不处理）**。

### 7.5 门与规范核对（改法合规性）

- `tests/test_board_taxonomy_gate.py` 的**板块结构门**（结构自洽 / 活性覆盖 / `impl_paths` 可解析 / 生成物同步 /
  旧窄计数循环）**不解析本分类账**、也无「主板块取值合法集」校验——`_meta` 在 `_board_body_pages()` 旧窄循环、
  G-T2 骨架、投影器 `scripts/board_doc_sync.py`（两处按 `_meta` 目录名跳过）三面被显式排除 ⇒ 本席改此册 主板块 值不触那三面。
  ⚠ **但 G-T3 宽尺（`spec_gates_census` 面 A）并不排除 `_meta`**——本册正文照被它扫。本席 §7 初稿曾被它记若干行
  （裸计数/裸枚举/裸运行路径），已逐行改写为指针句，现该文件对此尺**净贡献归零**（复算 `sc.compute()` 过滤
  `doc-classification` 的读数见本席报告）。G-T3 现值仍高于其上限，逐条归属他件（`docs/design` 审计件等，
  属 TX265 面 A 指针化在办债），非本席、非本册 ⇒ 按纪律不降基线、不代他席改。
- `tests/test_doc_link_integrity.py`（扫描面含 `docs/**/*.md`，本册在内）：本席全用行内代码写路径、
  不加导航用的 markdown 链接、不带「文件加行号」式死坐标 ⇒ 不改「md 死链 HARD 零档」与「死坐标 CEILING」棘轮。
- 未动 `board_taxonomy.py` / `board_doc_sync.py` / 三件生成物 `--write` / `AGENTS.md #48` /
  `HANDOFF-BOARDS-20260921.md` / `docs/boards/_conventions.md`（禁写面与难逆面，越权归主会话）。

复算命令（只读）：`find personas -name '*.md'` · `find . -type d -iname '*render_sample*'` ·
`wc -c` 逐枚 · `ls tests/render_hashes.json` · 关键词 `grep` 见本席报告 `SEAT-TX268.md`。
