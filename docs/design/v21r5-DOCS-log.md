# v21r5 DOCS-LEDGER 席工作日志

任务：v21r5 波次落账（AGENTS.md #43 + HANDBOOK §34 + docs/README.md 索引 + HANDOFF-V21R4-20260918.md 顶部指针）。零代码改动，禁 git 写，禁子代理。

## 事实来源（全读后才落笔，verified）

- docs/design/v21r5-coordination.md（时间线全录：三席全灭重派→A/B/C 交付→主会话收口→campus/VERIF 补派）
- docs/design/v21r5-TIMEOUT-log.md（A-SEAT DONE：fail-fast 5 跳+config_missing ≥3→10×900s；8/8+204+89 passed；.env 实查 key=1）
- docs/design/v21r5-INTIMACY-log.md（B-SEAT DONE：成员派生键/activated_at TTL 60min/四名单/config 四键；v3 28 例+24 文件 298 passed）
- docs/design/v21r5-POLICY-log.md（C-SEAT DONE：六硬线 scope=all+放开面+memory_sanitize 收窄+人格四处 sync sha=f3de6189…；v3 18 例；8 文件 109 passed/31 文件 418 passed）
- docs/design/r18-taxonomy-20260920.md（§六=用户二轮裁定全量：无条件放开 10/条件放开 4/维持禁止 3.1-3.5/硬线 5→6）
- docs/design/v21r5-RESTART-log.md / v21r5-REVIEW-log.md / v21r5-CAMPUS-log.md（三席均在飞开场态，落账如实标「在飞」）

## 四文档插入位置与行数增量（wc 实测，改前→改后）

| 文档 | 插入位置 | 行数增量 |
|---|---|---|
| AGENTS.md（根） | 已知问题台账表，**#43 行插在 #42 行（L187）之后、空行+「## 第七部分」之前**（#43 现为 L188） | 197→198，**+1** |
| docs/HANDBOOK.md | **§34 整节追加在 §33 末行（原 L2302）之后、文件末尾**（§34 标题现为 L2304，§34.1-§34.7 至 EOF）；无目录结构需改 | 2302→2359，**+57** |
| docs/README.md | ①「交接与总账」表 HANDBOOK 行（L32）1:1 原地替换——「§31 最新：控制面续接」过期口径→「§34 最新：v21r5 三任务批（此前 §33/§32/§31）」，零行数变化；②文末 v21r4-B 波次节之后新增「## 波次文档（v21r5 三任务批，2026-09-20）」整节（L125 起，8 行表格） | 123→136，**+13** |
| HANDOFF-V21R4-20260918.md | 标题行（L1）之后插入：空行+三行 v21r5 指针 blockquote（L2-L5；原「时点」块顺移至 L7） | 348→352，**+4** |

注：HANDOFF-V21R4-20260918.md 在 git 中为未跟踪件（??），无 diff 可对照，增量以 wc 前后实测为准；插入区已 Read 回读核验（标题/空行/三指针/空行/原时点块，无重复无损伤）。git diff --stat 对其余三文件显示的数字含并行会话既有未提交改动，不代表本席增量——本席增量只认上表 wc 前后差。

## 诚实边界（本席落账遵守情况）

- 所有数字均出自上列席 log 的实跑输出原文，无臆造；未完成项一律写「在飞/待录/以其 log 为准」：合流终跑与门禁预检（VERIF）、重启验收清单（RESTART-PREP）、恶毒自攻评审（REVIEW）、campus 14 例修复（CAMPUS）均未预填终态。
- 未写「已 commit/已部署/已重启」；HANDBOOK §34.6 与 AGENTS #43 状态列均钉「未 commit；重启生效；真机验收清单产出中」。
- v21r5-restart-acceptance-checklist.md 落盘前只在 README 以「在飞产出」占位，未引其内容。
- 新增配置键计数：仅 B 席四键（来自 INTIMACY log 配置键全表），A 席零新 config 键（阈值/倍率为模块常量）——两处口径已对齐 log。

## 交付清单

- [x] 全读事实来源 8 份
- [x] AGENTS.md 台账新增 #43（L188）
- [x] HANDBOOK.md 追加 §34（L2304-2359，§34.1 承接/§34.2 席位表/§34.3 交付清单/§34.4 改动文件面/§34.5 用户裁定记录/§34.6 状态口径/§34.7 在飞与待录项）
- [x] docs/README.md 索引补行+HANDBOOK 行口径刷新
- [x] HANDOFF-V21R4-20260918.md 顶部三行指针
- [x] 本 log：插入位置+行数增量记录完毕

DOCS-SEAT DONE
