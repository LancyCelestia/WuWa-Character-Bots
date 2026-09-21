# v21r4-B 波末文档增量草案（DOC-SYNC 席，2026-09-19）

> **性质：只读汇总 + 一份草案文档，零代码。** 收尾主会话可按本文四节直接套用文档增量；本文不新增结论，一切内容转写自下列数据源，引用处注明来源文件。
> 数据源：`docs/design/v21r4-b-wave-snapshot.md`（INTEGRATE 交付总表/裁决清单/口径差异）、`docs/design/v21r4-b-qa-probe-report.md`（QA-PROBE 波中回归快照）、各席日志 `docs/design/v21r4-b-*-log.md` 交付清单节、`docs/design/v21r4-b2-direct-collect-plan.md`、`docs/design/v21r4-b-coordination.md`。
> **诚实红线**：全文零生效类断言（与验收矩阵禁语同口径）；波中时点计数一律标注来源与时点，收尾态计数一律占位「以收尾实跑为准」；在飞席位（RWC5-b / S0-COLLECT / RET3 / RWC6-b）只标「在飞」，其结果留空位待收尾补。全波未 commit（wave-snapshot §四.1），故**本草案全部条目无提交哈希可引**——哈希占位待收尾 commit 后补记。
> **本席红线自查**：零 git 写操作、零子代理、零 .py/渲染域/验收矩阵/HANDBOOK/README/HANDOFF 本体改动、零真实 LLM 调用；唯一写入=本文件 + `v21r4-b-DOC-SYNC-log.md` + 协调表登记 1 行。

---

## 〇、合入前必读的三处编号冲突提示（合入时须先裁决）

1. **HANDBOOK 节号**：任务书拟「§31 v21r4-B」，但 HANDBOOK **§31 已被占用**（`## §31 内容政策 v2 批（2026-09-17）`，含 §31.1-§31.4；另有历史重复 §30 两节、§31 控制面续接一节，见 `docs/HANDBOOK.md` 2115-2195 行区段）。本文草案按**下一空闲节号 §32** 拟写；合入时以 HANDBOOK 实际尾号取下一空闲号为准。
2. **AGENTS.md 台账行号**：第六部分现表止于 #36；#37-#40 为 v21r2 批草案（`docs/design/v21r2-agents-ledger-draft.md`，**尚未合入**）。本批取 **#41** 与任务书一致；合入时须与 #37-#40 草案同窗插入（先 37-40 后 41，顺序不可颠倒）。
3. **not_wired 17 vs 18**：HANDOFF-V21R4-20260918.md §5.3「核准数字」段记「not_wired=18 行按 18 行推进」，MAT 终态按草案行级表落定 **not_wired=17**（L65 wiring=partial，LLM 解释端口才是 not_wired 位）——口径差异已留档（wave-snapshot §三.1）。③ 节 HANDOFF 增量含对应更正句。

---

## ① AGENTS.md 台账新行草案（#41 v21r4-B 批）

### 1.1 一句话总账

> **v21r4-B 后端并发波（2026-09-18—09-19，多席满载）**：B1 矩阵 65 行回填、B2① 服务装配组落盘（主门缺省关）、B2② 真实发送端口组**方案材料**（非授权）、B2③ 四行改判「无直连点」+结构锁测试、B3 三立项书（L60/L71/L74）、B4 命令格式评审材料、B5 kb_drift 说明、B6 五项调研 memo、提醒「明早/明晚」双修（本波唯一生产代码面交付）、RK5 控制面三小债、S0 直连收编方案；全波未 commit/未重启/未部署，全部证据离线，50+ 项用户裁定点收齐于 wave-snapshot §二。

### 1.2 逐包结论（转写自各席日志交付清单节）

| 包 | 席 | 结论（含实跑计数，来源见行尾） | 状态 |
|---|---|---|---|
| B1 矩阵回填 | MAT | `docs/design/backend-v2-acceptance-matrix.md` 65 行四列回填，程序化比对 65/65 一致、四列零空缺；wiring=unknown 31/partial 17/not_wired 17、live=unknown 60/blocked 4/not_applicable 1/passed 0；生效类禁语 grep 零命中；ruff 全绿（`v21r4-b-MAT-log.md` §四/§五）。纯文档，无生产行为主张 | 完成 |
| B2① 服务装配组 | WIRE-SVC | 新件 `runtime/service_wiring.py`+根 `__init__.py:4124-4143` 主门门控插入+config 三新键（`bot_v21_service_wiring_enabled`/`bot_worldbook_enabled`/`bot_knowledge_service_enabled`，均缺省 False；teaching/broker 既有键作分门复用）+catalog/.env.example/auto-facts 同步+`tests/test_v21_wire_svc_assembly.py` 12 例；实跑 12/96/105 passed，全量时点 4 failed（1 基线 linux.do+3 并行席瞬态/哈希漂移）8185 passed（`v21r4-b-WIRE-SVC-log.md` 终稿）。L41 blocked=用户未裁决；事故一笔：测试 stub 笔误致 Runtime 一过性教导库文件，已备份 %TEMP% 后清除复跑确认（同日志） | 完成（日志终稿） |
| B2② 端口方案 | PORT-PLAN | `docs/design/v21r4-b2-port-wiring-plan.md`：**方案材料不构成实施授权**；real_session 三处 503 根因=`real_adapter` 从未注入（`control_plane/factory.py:105-106`）；15 项可勾选前置条件（§3.2）+三级回滚+行号双编号对照（`v21r4-b-PORT-PLAN-log.md` 交付清单） | 完成 |
| B2③ 改判+结构锁 | WIRE-DIRECT | L56/L57/L58/L65 逐一取证**均无「绕统一出站路径的直连点」**，不硬造收编：L56/L57/L58 改判 blocked（装配+授权双阻塞；存量提醒生产线已走统一路径，「并行未切」系误读纠正）、L65=端口组性质维持 503 not_wired；新 `tests/test_v21_wiredirect_unified_path.py` 4 例 passed+合跑 149 passed+ruff+catalog 77+mypy 单文件过（`v21r4-b-WIRE-DIRECT-log.md` §一/§三/§四） | 完成 |
| B3 立项书×3 | CHARTER/CHARTER-b | `v21r4-L60/L71/L74-立项书.md` 三份齐，纯提案零代码，基线逐条 file:line；三测试件合跑 61 passed（离线）；分别开放 5/6/7 条问题待用户裁（`v21r4-b-CHARTER-log.md` 交付清单） | 完成 |
| B4 命令评审材料 | DOCS | `v21r4-command-format-review.md`：现状 77 topics/501 别名/33 路由**原样未动**；最大裁决点=14 领域 vs 20 域坐标系分歧；77 条逐条归属+落码波及 14 文件+四阶段工作量（`v21r4-b-DOCS-log.md`；wave-snapshot §一 B4 行） | 完成 |
| B5 kb_drift 说明 | DOCS | `v21r4-kb-drift-explainer.md`：目录卡 35341 vs 原文 4611（4539 已配卡）；预检只读；重建与否=用户裁定，AI 不代改运行数据（`v21r4-b-DOCS-log.md`） | 完成 |
| B6 台账 memo | LEDGER/LEDGER-b | `v21r4-b6-ledger-memo.md` 五项调研全带真身坐标：①搜索时效三方案（待裁）②合并转发已闭环**待重启生效**+live 观察点（大图上限实为 25MB/25s，2026-09-18 用户裁定）③提醒残余五项（#1「明早」已被 REM-DAWN 修掉）④LLM 故障转移九项 live 证据采集清单（重启后）⑤亲密话术指针本波不动。零实装（`v21r4-b-LEDGER-log.md` 交付节） | 完成 |
| 提醒双修 | REM-DAWN+REM-EVE | 「明早」入 `_DAY_OFFSETS`/`_ABS_TIME_RE`/`_PERIOD_ONLY_RE`（RED 1 failed→GREEN 64 passed，`v21r4-b-REM-DAWN-log.md`）；「明晚8点」时段语义修为次日 20:00（RED 3 failed→GREEN 34 passed，提醒族 7 文件 125 passed，`v21r4-b-REM-EVE-log.md`）。**冲突裁决在案**：REM-DAWN 曾锁「明晚8点=08:00」，REM-EVE 按任务简报改写为 20:00 并注明取代关系，回滚点在其日志③——收尾主会话须认账此裁决 | 完成（重启后才生产生效） |
| 控制面三小债 | RK5 | ①动作明细消毒 xfail 转正（`_sanitize_action_details`，scoped 50 passed）②OpenAPI Duplicate OpID 清零（traces stub 显式 operation_id+回归锁）③platform.py mypy 两错清零（Coroutine 标注）；扩面 20 文件 436 passed；全树 ruff 余 2 错归前端在飞件、根 `__init__.py` 两处 mypy attr-defined 归 WIRE-SVC 域（`v21r4-b-RK5-log.md` 终稿） | 完成（日志自称收工；任务书列在飞——收尾以日志终态核对） |
| S0 直连收编方案 | DIRECT-PLAN | `v21r4-b2-direct-collect-plan.md`：5 处坐标全部核实为真实直连点（⑤=登记表陈旧非新点）；四处生产直连分属统一路径三形态可收编（A 管线/B 调度 job/D 文件网关），全部「配置门缺省关」渐进设计+旧路径锁测试；⑤登记表刷新现在即可动（`v21r4-b-DIRECT-PLAN-log.md` 交付节） | 完成 |
| 波次整合快照 | INTEGRATE | `v21r4-b-wave-snapshot.md`：交付总表+统一裁决清单 10 组+口径差异 6 条+状态红线 6 条（`v21r4-b-INTEGRATE-log.md`） | 完成 |
| 波中回归快照 | QA-PROBE | `v21r4-b-qa-probe-report.md`（2026-09-19 凌晨时点，在飞中间态）：提醒族 130 passed；V2.1 族 662 passed/23 failed（全部 test_v21r3_visual_gates.py=前端域视觉门禁）/1 skipped/1 xfailed；控制面族 271 passed；ruff 11 errors 全前端域；doc_sync/catalog 双 PASS；verify_hashes 8 项 DRIFT（前端域为主）。三族合计 1063 passed/23 failed，唯一红灯域=前端 | 完成（时点证据非合流结论） |
| 垫片退役第三梯队 | RET3 | 批 1 已落盘：11 张垫片退役（sources/parsers 5 张+xiaohongshu_adapter+character 5 张），13 测试文件消费方改 canonical，备份 %TEMP%/v21r4-ret3-backup，回归 148 passed（`v21r4-b-RET3-log.md` 批1 节）；**其余批次日志一/二/三节仍「待填」** | **在飞**（批1 完成） |
| policy/security 迁移 | RWC6-b | 实盘勘误：security 真身 3 件（非交接书 4 件）、policy 5 件，迁移总数 8 真身+2 包 `__init__`；消费方=插件内 14+测试 26+脚本 1；批次1（gate/quiet_hours/rate_limit）标记「进行中」（`v21r4-b-RWC6-b-log.md`） | **在飞** |
| 根 `__init__` 惰性导入续切 | RWC5-b | 无日志、无交付物在盘，零盘面证据（协调表认领行在案） | **在飞**（盘面零痕迹） |
| S0 直连收编非 root 件 | S0-COLLECT | 无日志在盘（协调表认领行在案；`domains/core/decision/outbound_registry.py` 登记表刷新+非 root 收编件为其面） | **在飞**（盘面零痕迹） |

### 1.3 台账三列表格行（合入时取此行，置于 #40 之后）

> 格式与 AGENTS.md 第六部分现表一致（`| 编号 | 内容 | 状态 |`，单行单元格）。哈希与全量计数为占位。

| #41 | **v21r4-B 后端并发波**（2026-09-18—09-19，多席满载，未 commit——共享工作树，提交裁决权在用户）：①B1 矩阵 65 行四列回填（MAT，程序化 65/65 核验，not_wired=17 口径，wave-snapshot §三.1 留档 17vs18 差异）；②B2① 服务装配组（WIRE-SVC：runtime/service_wiring.py+根 __init__.py:4124-4143 主门门控+config 三新键缺省 False+12 例装配测试；L41 blocked 等用户裁决）；③B2② 真实发送端口组方案材料（PORT-PLAN：15 项前置条件待用户逐项勾选，503 根因=factory.py real_adapter 从未注入）；④B2③ 四行改判无直连点+结构锁测试 4 例（WIRE-DIRECT：L56/L57/L58=blocked、L65=端口组维持 not_wired）；⑤B3 三立项书 L60/L71/L74（开放 5/6/7 条待裁）；⑥B4 命令格式评审材料（77 topics/501 别名/33 路由现状未动，14 领域 vs 20 域裁决点）+B5 kb_drift 说明（35341 vs 4611，重建与否用户裁）+B6 五项调研 memo；⑦提醒双修=本波唯一生产代码面（「明早」入词表+「明晚8点」修 20:00，REM-EVE 推翻 REM-DAWN 既有锁并留回滚点，重启后才生效）；⑧RK5 控制面三小债（xfail 转正+OpID 清零+mypy 清零，scoped 50 passed/扩面 436 passed）；⑨S0 直连收编方案（5 处直连点三形态缺省关收编设计，四处 pending-on-RWC5-b）；⑩QA-PROBE 波中快照：三族 1063 passed/23 failed 全归前端域视觉门禁、ruff 11 错+哈希 8 漂移全前端域归属。**在飞空位：RET3（批1 已落盘 11 张垫片退役 148 passed）、RWC6-b（policy/security 迁移批1 进行中）、RWC5-b、S0-COLLECT——终态以其日志为准待收尾补**。**哈希占位：全波未 commit，收尾 commit 后补**；**全量测试计数占位：以收尾实跑为准**；**50+ 项用户裁定点指针=docs/design/v21r4-b-wave-snapshot.md §二** | 代码+测试+文档完成（在飞四席除外）；未 commit；全部离线证据，重启后才生效；前端域红灯（视觉门禁 23/ruff 11/哈希 8）归前端波合流后收口 |

---

## ② docs/HANDBOOK.md 新节草案（拟 §32；任务书原拟 §31 已被「内容政策 v2 批」占用）

> 合入位置：HANDBOOK 末尾（现尾节=§31 内容政策 v2 批）。若合入时尾号已变，顺延取下一空闲号。以下为可直接粘贴的节文本。

```markdown
## §32 v21r4-B 后端并发波总账（2026-09-18—09-19，未提交——工作树多会话共享，提交裁决权在用户）

> 权威细节：交付总表/裁决清单/口径差异=docs/design/v21r4-b-wave-snapshot.md；回归时点=docs/design/v21r4-b-qa-probe-report.md；各席终态=docs/design/v21r4-b-*-log.md。本节为精简转写。

### §32.1 承接与定位（与 §30/§31 的衔接）
- 时序上承接 §31 内容政策 v2 批（2026-09-17）之后的 v21r2→v21r4 收尾窗口：v21r2 批台账草案=#37-#40（docs/design/v21r2-agents-ledger-draft.md，未合入），本节=v21r4 后端波（B1-B6）。与 §30/§31 同一工作树口径：**未 commit、共享工作树、提交裁决权在用户**；§30.1/§31 的「重启后才生效」清单在本波继续累积（本波新增：提醒双修、WIRE-SVC 装配链——主门缺省 False 故缺省零行为差）。
- 与前端波（v21r4-F）零交叉：本波唯一红灯域=前端（视觉门禁 23 红/ruff 11 错/verify_hashes 8 漂移，QA-PROBE 时点证据），合流后由前端归属席收口；渲染红线文件（theme_tokens.py/render_hashes.json/domains/render/**）后端各席零触碰（wave-snapshot §四.6）。

### §32.2 交付清单（逐包一句账，计数为各席日志实跑时点）
1. **B1 矩阵回填**（MAT）：验收矩阵 65 行四列程序化核验 65/65；not_wired=17（与交接书 18 行口径差留档）；生效类禁语零命中。
2. **B2① 服务装配组**（WIRE-SVC）：runtime/service_wiring.py 新件+根 __init__.py:4124-4143 主门门控+config 三新键（bot_v21_service_wiring_enabled/bot_worldbook_enabled/bot_knowledge_service_enabled 缺省 False）；12/96/105 passed；L39/L40/L42/L43 装配落盘、矩阵四行未动（升 wired 须重启后 live 证据）；L41 blocked=「独立新库 vs 同源同库」未裁决；事故一笔（stub 笔误一过性教导库文件，备份 %TEMP% 后清除）。
3. **B2② 端口组方案材料**（PORT-PLAN）：v21r4-b2-port-wiring-plan.md，不构成实施授权；real_session 503 根因=factory.py:105-106 real_adapter 从未注入；15 项前置条件待用户逐项勾选。
4. **B2③ 四行改判**（WIRE-DIRECT）：L56/L57/L58/L65 均无绕统一出站路径的直连点——L56/L57/L58 改判 blocked（装配+授权双阻塞），L65=端口组性质维持 503 not_wired；结构锁测试 4 例+合跑 149 passed。
5. **B3 三立项书**（CHARTER/CHARTER-b）：L60 好感误扣补偿（5 条待裁，48h 证据窗时效注记）/L71 自修复（6 条）/L74 验收产物（7 条）；三测试件合跑 61 passed。
6. **B4/B5/B6**（DOCS/LEDGER-b）：命令格式评审材料（77 topics 现状未动，14 领域 vs 20 域最大裁决点）+kb_drift 三问说明（35341 vs 4611，AI 不代改运行数据）+五项调研 memo（搜索时效三方案/合并转发 25MB 闭环待重启/提醒残余五项/LLM 故障转移九项 live 清单/亲密话术指针）。
7. **提醒双修=本波唯一生产代码面**（REM-DAWN+REM-EVE）：「明早」入三词表（RED→GREEN 64 passed）；「明晚8点」修为次日 20:00（34 passed，族 125 passed）；冲突裁决：REM-EVE 改写 REM-DAWN「明晚=08:00」既有锁，回滚点在 v21r4-b-REM-EVE-log.md §③。
8. **RK5 控制面三小债**：xfail 转正（_sanitize_action_details）+OpenAPI OpID 清零+platform.py mypy 清零；scoped 50 passed/扩面 436 passed。
9. **S0 直连收编方案**（DIRECT-PLAN）：5 处直连点核实（cookie 提醒/入群欢迎/二维码/文档导出+登记表陈旧），统一路径 A/B/D 三形态缺省关收编设计，根 __init__ 四点 pending-on-RWC5-b。

### §32.3 在飞空位（收尾补记）
RET3（垫片退役第三梯队：批1 已落盘 11 张+148 passed，余待填）/ RWC6-b（policy/security 迁移 8 真身+2 __init__，批1 进行中）/ RWC5-b（根 __init__ 惰性导入续切，无日志）/ S0-COLLECT（非 root 直连收编件，无日志）——终态以其日志为准，本节不预填。

### §32.4 状态口径（诚实红线）
全波未 commit/未重启/未部署；全部证据离线，离线绿不升 live passed、不升 wired；零真实对外动作（零真实发送/LLM 调用/子代理，各席自查）；50+ 项用户裁定点=docs/design/v21r4-b-wave-snapshot.md §二（10 组可勾选）；重启前置=scripts/pre_restart_check.py。全量测试计数以收尾实跑为准（波中参照：QA-PROBE 三族 1063 passed/23 failed；WIRE-SVC 时点全量 4 failed/8185 passed）。
```

---

## ③ docs/README.md / HANDOFF-V21R4-20260918.md 增量行草案

### 3.1 本波新交付物全列表（docs/design/v21r4-*，2026-09-19 在盘实核 `ls`）

**裁决/方案/评审材料（8 份）**：`v21r4-L41-decision-memo.md`、`v21r4-L60-立项书.md`、`v21r4-L71-立项书.md`、`v21r4-L74-立项书.md`、`v21r4-b2-port-wiring-plan.md`、`v21r4-b2-direct-collect-plan.md`、`v21r4-command-format-review.md`、`v21r4-kb-drift-explainer.md`、`v21r4-b6-ledger-memo.md`（9 份）
**波次文档（3 份）**：`v21r4-b-coordination.md`（协调表）、`v21r4-b-wave-snapshot.md`（整合快照）、`v21r4-b-qa-probe-report.md`（回归快照）、`v21r4-b-doc-sync-draft.md`（本文）
**席位日志（16 份在盘）**：`v21r4-b-{CHARTER,DIRECT-PLAN,DOCS,INTEGRATE,LEDGER,MAT,MEM-DEC,PORT-PLAN,QA-PROBE,REM-DAWN,REM-EVE,RET3,RK5,RWC6-b,WIRE-DIRECT,WIRE-SVC}-log.md` + `v21r4-b-DOC-SYNC-log.md`（本席）；**待落盘**：`v21r4-b-S0-COLLECT-log.md`、RWC5-b 日志（在飞）
**代码/测试/配置面交付**（非 docs，收尾 commit 清单用）：`runtime/service_wiring.py`（新）、根 `__init__.py`（装配插入段）、`config.py`（三键）、`domains/schedule/store/reminders.py`+`tests/test_reminder.py`（双修）、`control_plane/actions.py`/`api/v1.py`/`api/platform.py`（RK5）、`tests/test_v21_wire_svc_assembly.py`（新 12 例）、`tests/test_v21_wiredirect_unified_path.py`（新 4 例）、`tests/test_v21_risk_red_cp_app.py`/`tests/test_control_plane_v1.py`（RK5 改）、`docs/config-catalog-full.md`/`.env.example`/`docs/auto-facts.md`（同步）、`docs/design/backend-v2-acceptance-matrix.md`（MAT 独占写）；RET3 已删 11 张垫片+改 13 测试文件（清单见其日志批1 节）；RWC6-b 迁移件待其批次台账。

### 3.2 docs/README.md 增量（建议新增小节，置于「控制面续接入口」附近）

```markdown
## 波次文档（v21r4）

| 文档 | 说明 |
|---|---|
| [design/v21r4-b-wave-snapshot.md](design/v21r4-b-wave-snapshot.md) | v21r4-B 后端波整合快照：交付总表 / 50+ 项用户裁决清单（§二 10 组可勾选）/ 口径差异 6 条 / 状态红线 |
| [design/v21r4-b-qa-probe-report.md](design/v21r4-b-qa-probe-report.md) | v21r4-B 波中回归快照（时点证据）：三族 1063 passed / 23 failed 全归前端域；门禁四件体检 |
| [design/v21r4-b-doc-sync-draft.md](design/v21r4-b-doc-sync-draft.md) | v21r4-B 波末文档增量草案（AGENTS.md #41 / HANDBOOK §32 / README·HANDOFF 增量 / 收尾清单） |
| [design/v21r4-L41-decision-memo.md](design/v21r4-L41-decision-memo.md) | L41 记忆库三案裁决材料（推荐 A 独立新库；未裁决不得接线） |
| [design/v21r4-L60-立项书.md](design/v21r4-L60-立项书.md) / [L71](design/v21r4-L71-立项书.md) / [L74](design/v21r4-L74-立项书.md) | 好感误扣补偿 / 自修复链 / 验收产物 三立项书（纯提案，5/6/7 条待裁） |
| [design/v21r4-b2-port-wiring-plan.md](design/v21r4-b2-port-wiring-plan.md) | 真实发送端口组接线方案材料（15 项前置条件待用户勾选；不构成实施授权） |
| [design/v21r4-b2-direct-collect-plan.md](design/v21r4-b2-direct-collect-plan.md) | S0 直连点收编方案（5 处坐标+三形态缺省关设计；根 __init__ 四点 pending-on-RWC5-b） |
| [design/v21r4-command-format-review.md](design/v21r4-command-format-review.md) | 命令格式评审材料（77 topics 现状未动；14 领域 vs 20 域坐标系裁决点） |
| [design/v21r4-kb-drift-explainer.md](design/v21r4-kb-drift-explainer.md) | 知识库漂移三问说明（35341 vs 4611；重建与否用户亲办） |
| [design/v21r4-b6-ledger-memo.md](design/v21r4-b6-ledger-memo.md) | B6 五项调研 memo（搜索时效/合并转发/提醒残余/LLM 故障转移 live 清单/亲密话术指针） |
| design/v21r4-b-*-log.md（16+ 份） | 各席日志（断点续跑依据+交付清单+实跑证据） |
```

### 3.3 HANDOFF-V21R4-20260918.md 增量（三处）

1. **§5.1「交付物」表后追加一段**：
   > **v21r4-B 波交付（2026-09-19）**：B1-B6 全部有交付物在盘（清单与逐包结论=docs/design/v21r4-b-wave-snapshot.md §一；席位日志=docs/design/v21r4-b-*-log.md）。B2② 端口组为方案材料未实施；B2③ 四行经核实无直连点改判 blocked/not_wired；B2① 装配落盘（主门缺省关）；L41 等裁决未接线；提醒「明早/明晚」双修为本波唯一生产代码面，重启后才生效。全波未 commit。
2. **§5.3「核准数字」段后追加更正句**：
   > **更正（2026-09-19 MAT 落定）**：上文「not_wired=18 行按 18 行推进」与矩阵终态存在口径差——L65 wiring=partial（控制面 REST 已挂接，LLM 解释端口才是 not_wired 位），终态 not_wired=**17**；口径差异留档=docs/design/v21r4-b-wave-snapshot.md §三.1。
3. **§6.3「等你动作 / 裁决」追加一条**：
   > 5. **v21r4-B 波 50+ 项裁定点**——10 组可勾选清单=docs/design/v21r4-b-wave-snapshot.md §二（最省事路径：先裁 L41 三案与搜索时效方案 B，再按需勾 PORT-PLAN 15 项）。

---

## ④ 收尾执行清单（主会话按序）

### 4.1 合流前置：等在飞席收口
1. RET3（余批垫片退役，日志一/二/三节待填）、RWC6-b（policy/security 迁移批1-3）、RWC5-b（根 `__init__.py`，无日志）、S0-COLLECT（非 root 直连收编件，无日志）——终态以其日志为准。
2. 核对 RK5：任务书列在飞，但其日志终稿自称三项交付完成收工（`v21r4-b-RK5-log.md`）——收尾以日志与在盘测试核对后定「完成/在飞」。

### 4.2 门禁与全量测试（收尾实跑，计数以下列命令输出为准，本草案不预填）
按 AGENTS.md 第五部分 + QA-PROBE §八口径，按序：
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"           # 全量（占位：以收尾实跑为准）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"           # ruff
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"      # mypy（注意根 __init__.py 两处 attr-defined 归 WIRE-SVC 域，RK5 日志基线在案）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout"
# 一致性门禁四件（只读 --check）：
#   ruff check . / scripts/doc_sync.py --check / scripts/command_catalog.py --check / tests/verify_hashes.py --check
```
波中参照（QA-PROBE 2026-09-19 凌晨时点，非合流结论）：提醒族 130 passed；V2.1 族 662 passed/23 failed（全前端域视觉门禁）；控制面族 271 passed；doc_sync/catalog PASS；ruff 11 错+verify_hashes 8 漂移全前端域。收尾判定基线=以合流后实跑为准。

### 4.3 需前端波合流后才能做的项（后端各席禁 --write/禁越界，已在案）
| 项 | 数量（QA-PROBE 时点） | 收口动作 | 归属 |
|---|---|---|---|
| verify_hashes 漂移重录 | 8 项（theme_tokens.py/rendering-contract.md/DESIGN-SPEC.md/bridge.py/usage_cards.py/templates.py/echo.py/debug.py） | 前端收口后 `verify_hashes.py --write` 重录（theme_tokens 属波内禁改件字节漂移，QA-PROBE 已如实记录未触碰） | 前端波 |
| ruff 全树错误 | 11 errors（9 fixable；mica_shell/test_mica_shell/test_phase_determinism/test_rendering_contract/test_v21r3_visual_gates） | 前端域 lint 清零 | 前端波 |
| 视觉门禁红灯 | 23 failed（test_v21r3_visual_gates.py，gate01/02/03/06/07/08 跨 11 卡面） | 逐 gate 对齐 token/模板层后复跑 | 前端波 |
| doc_sync/auto-facts 再漂移 | 多席并发改树所致（WIRE-SVC 已两度 --write 收敛；REM-EVE 亦 --write 过一次） | 收尾合流后终跑 `doc_sync.py --write`+`--check` 收敛一次 | 收尾主会话 |

### 4.4 后端独占待办（不依赖前端）
| 项 | 内容 | 依据 |
|---|---|---|
| 根 `__init__.py` 四直连点收编 | cookie 到期提醒/入群欢迎/二维码图片/文档导出四处，按 direct-collect-plan §三形态 B/A/A/D 缺省关收编——**pending-on-RWC5-b**（根 `__init__.py` 惰性导入续切在飞独占写；行号必漂，实施席以符号 grep 重定位）；⑤登记表刷新（outbound_registry.py）现在即可动 | `v21r4-b2-direct-collect-plan.md` §四/§五 |
| RET2b 垫片梯队挂起 | 挂起原因=前端邻接（任务书口径；RET3 批1 已清「仅测试消费 44 张+epic/steam」，其余梯队待其日志终态与前端合流窗口） | DOC-SYNC 任务书；`v21r4-b-RET3-log.md` |
| 端口组 15 项前置条件 | 用户逐项勾选（第 1 项总闸）后才可实施 real_session 真实发送；未勾满维持 503 not_wired | `v21r4-b2-port-wiring-plan.md` §3.2；wave-snapshot §2.1 |
| L41 记忆库三案 | 用户单选 A/B1/B2/暂不（memo 推荐 A）；未裁决 L41 保持 not_wired，装配席留挂点 | `v21r4-L41-decision-memo.md` §⑤；wave-snapshot §2.2 |
| 其余裁决组 | 搜索时效三方案/「一会儿」默认值/DOCS B4 八项/L60 五条/L71 六条/L74 七条/kb_drift 重建/L56-L58 真实投递授权/L65 塔罗解释端口/亲密话术三项 | wave-snapshot §二（2.3-2.10） |
| 重启窗口 | 重启前置=`scripts/pre_restart_check.py`（含 kb_drift 体检第 5 项）；重启后 L39/L40/L42/L43 等矩阵行是否升 wired 由 live 证据决定；REM 双修/L60 合并转发等自此生效清单与 #37-#40 草案同窗记账 | wave-snapshot §四.5；MAT 日志偏差④ |

### 4.5 收尾 commit 备忘（哈希占位补记处）
全波未 commit（wave-snapshot §四.1；MEM-DEC 只读 git 实查 v21 记忆五文件 `??` 未跟踪）。按 AGENTS.md git 纪律逐文件显式 add（禁 `git add -A`），commit 后：①台账 #41 行哈希占位回填；②HANDBOOK §32 证据节补哈希；③本文件 3.1 代码/测试交付清单可作 add 逐文件底稿（RET3 已删 11 张垫片与 RWC6-b 迁移件以其批次台账为准）。

---

## 附：本草案边界

- 本文一切数字与结论均转写自文首数据源文件，未新增结论、未跑任何测试、未触碰任何禁改文件；在飞席位（RWC5-b/S0-COLLECT/RET3/RWC6-b）只标状态不预填结果。
- RK5/WIRE-SVC/DIRECT-PLAN 三席任务书列为在飞或在快照中标记在飞，但其日志已现终稿/交付清单——本文按日志事实转写并注明差异，收尾主会话核对后定稿。
- 合入时三处编号冲突（HANDBOOK §31 占用/台账 #37-#40 未合入/not_wired 17vs18）见 §〇。
—— DOC-SYNC 席，2026-09-19。

---

## §五 2026-09-20 午间终态补录（SYNC-FINAL 席）

> 性质：波末补录节。六席终态摘要逐条转写自各席日志（路径见表，只读取证）；基线为本席实跑时点证据。**诚实红线：基线含前端在飞中间态，非合流结论**；全波仍未 commit/未重启/未部署。协调表已交付席位 ✅ 补标（SYNC-FINAL 核验 24 份日志末态，RWC6-b/RET2B-PREP 原有 ✅ 不重复）。

### 5.1 六席终态摘要

| 席 | 终态 | 关键计数（转写自日志，时点=各席日志标注） | 日志路径 |
|---|---|---|---|
| RET3 | 垫片退役第三梯队完成 | 46 张退役（批1 11+批2 13+批3 10+批4 12；域回归 148/204/585+12/331 passed 合计零回归）；在飞冲突挂起 0；AST 零残余（三轨复验 46 张零 src 消费）；备份 %TEMP%/v21r4-ret3-backup；doc_sync --check 复跑 EXIT=0 | docs/design/v21r4-b-RET3-log.md |
| RET2B-PREP | RWOC 垫片冲突矩阵+安全子集退役完成 | 44 退役（40 本席+4 前席记账）+挂起 7（移交清单=日志 §三）+包垫片 supervisor/__init__ 同退；AST 零残余（v2 修正扫描器）；整树 collect 8531/0err；域回归 1756 passed/0 failed；dev.ps1 旧路径 30 处修复 | docs/design/v21r4-b-RET2B-PREP-log.md |
| RWC5-b | 根 __init__ 惰性导入续切收尾（旧路径清账） | 旧路径消费边 0 残余（PEP562 62+STATIC 31+RELAY 清零）；22 点真身未迁保留集（contracts/control_plane/policy·security/llm 包等）；test_v21 全族 38 文件+提醒族 781 passed/1 skipped；源文本锚五件+耦合十件 154 passed；ruff All checks | docs/design/v21r4-b-RWC5-b-log.md |
| S0-COLLECT | S0 直连收编非 root 件（数据面）完成 | outbound_registry.py 直发登记 3 条坐标刷新+1 条文档导出补登（BYPASS_SUSPECT）+file_gateway 条目改判 PENDING_RULING→CHANNEL_BODY；RED 4 failed→GREEN 64 passed（test_v21_s0_collect 5+test_outbound_v21 59）；根内四处读时快照移交（pending-on-RWC5-b） | docs/design/v21r4-b-S0-COLLECT-log.md |
| LIVE-TOOL | live 取证采集脚本交付 | scripts/collect_v21r4_live_evidence.py + tests/test_v21_live_evidence_tool.py：20 例 20 passed（0.12s，全离线）；九项统计口径按 LEDGER-b memo 对真身取证；160 万行历史日志全量扫描九项全 0（诚实结果，重启后见真值） | docs/design/v21r4-b-LIVE-TOOL-log.md |
| L41-PLAN | L41 执行预案落盘 | docs/design/v21r4-l41-exec-runbook.md（A 案 12 步施工坐标+代码草图+测试计划+B1 差异点与风险四条+B2 存目）；memo 坐标勘误三处；预案≠授权≠裁决，L41 仍 not_wired 待用户勾选 | docs/design/v21r4-b-L41-PLAN-log.md |

### 5.2 全量基线（SYNC-FINAL 实跑，2026-09-19 午间时点）

- 命令：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/ -q --basetemp=$TEMP/v21r4-b-final-baseline -p no:cacheprovider`（全量输出：`%TEMP%/v21r4-b-final-baseline-full.log`）
- 结果：**1 failed, 8531 passed, 12 skipped, 3 xfailed, 3 warnings in 444.89s (0:07:24)**
- 唯一失败：`tests/test_webui_http.py::test_stats_endpoints_require_bearer_and_use_common_envelope`——按文件域归属=**前端在飞面（test_webui*）**，与后端本波交付面零交集；前波已知基线项（linux.do 样本缺失）本次已绿。
- **诚实红线：本基线为时点证据，含前端在飞中间态，非合流结论**；合流判定以收尾主会话实跑为准。

### 5.3 剩余待办终表

| 项 | 内容 | 归属/依据 |
|---|---|---|
| 根 init 四处直连收编 | cookie 到期提醒/入群欢迎/二维码图片/文档导出四处行为收编（形态 B/A/A/D，配置门缺省关）——**S0-ROOT-c 席接替阵亡 S0-ROOT/S0-ROOT-b（均零产出无断点）在飞执行**（协调表现登记行，2026-09-19 SYNC-FINAL-b 核对修正席位代号；按 direct-collect-plan 执行序④②③①，TDD 门缺省关） | S0-ROOT-c；docs/design/v21r4-b2-direct-collect-plan.md §三/§四 |
| 挂起 3 张垫片（前端域） | config_readiness/decision.trace/capabilities.debug 三张前端域垫片=前端收口后退役；RET2B-PREP 挂起 7 张全量移交清单（含 contracts.media 35 src 面/contracts.runtime 9 src 面/decision.outbound+sources.web_search 待 S0-COLLECT·控制面收口）见其日志 §三 | 前端波合流后；docs/design/v21r4-b-RET2B-PREP-log.md §三 |
| 用户裁决项 | 50+ 项收齐于 wave-snapshot §二（10 组可勾选：PORT-PLAN 15 项前置/L41 三案/搜索时效三方案/「一会儿」默认值/DOCS B4 八项/L60 五条/L71 六条/L74 七条/kb_drift 一项/散落授权收口备查） | docs/design/v21r4-b-wave-snapshot.md §二 |

—— §五 完（SYNC-FINAL 席，2026-09-19 录）。

### 5.4 SYNC-FINAL-b 续跑核验与第二时点复跑（SYNC-FINAL-b 席，2026-09-19 午后）

> SYNC-FINAL 席因平台瞬时故障阵亡，SYNC-FINAL-b 接替续跑。实读盘面：其检查点所列「待做」五项（coordination ✅ 补标 / AGENTS.md 铁律 6 括注 / §五本体）**均已在其阵亡前落盘**——①coordination.md 23 行已交付席位全部已带「✅完成」；②AGENTS.md:45 铁律 6 括注「2026-09-19 v21r2 重组随 weather 域迁移」在盘（grep 实证）；③§五 1-3 节在盘。本席零重复编辑，只做核验+本节增补。

**核验结论**：①原基线日志 `%TEMP%/v21r4-b-final-baseline-full.log` 实读 14477 字节、尾部含完整总结行——「14KB 半程无效」预判被实盘推翻（pytest -q 输出紧凑），§5.2 数字 verified；②六席日志（RET3/RET2B-PREP/RWC5-b/S0-COLLECT/LIVE-TOOL/L41-PLAN）逐份实读，§5.1 转写逐项吻合。

**第二时点全量基线复跑**（SYNC-FINAL-b 实跑，命令同 §5.2、basetemp=v21r4-b-final-baseline-b，日志 `%TEMP%/v21r4-b-final-baseline-b.log`）：

- 结果：**4 failed, 8528 passed, 12 skipped, 3 xfailed, 3 warnings in 291.77s (0:04:51)**；collection 总数两时点一致（8547）。
- 4 失败逐条归属（只记录一律不修）：
  1. `test_webui_http.py::test_stats_endpoints_require_bearer_and_use_common_envelope`——两时点同在，归属**前端在飞面**，与后端交付面零交集；
  2. `test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync`——doc_sync 常驻门形态，与本席实测 `doc_sync.py --check` exit=1 互证，归属**多席并发改树机械事实漂移**（收尾合流后统一 --write 收敛）；
  3. `test_doc_sync_gates.py::test_config_catalog_covers_config_fields`——config catalog 覆盖门，归属 **TTS 席占域在飞面**（bot_tts_* 新键未登记 catalog）；
  4. `test_verify_hashes_coverage.py::test_builder_drift_gate_red_then_green`——verify_hashes 常驻门形态，与本席实测 1 项漂移（echo.py）互证，归属**echo.py 在飞面**未重录。
- 与第一时点差异定性：第一时点基线跑完之后，TTS 席与 echo.py 编辑席在飞改树，新增 3 失败全为门禁常驻门形态，非本波后端交付面回归。
- **诚实红线：两份基线均为时点证据，含在飞席位中间态，非合流结论**；合流判定以收尾主会话实跑为准。

**终验四件（SYNC-FINAL-b 实跑，只 --check 只归属不代修）**：①`ruff check .` Found 1 error=tests/test_tts.py:44 F401（归属 TTS 席占域）；②`verify_hashes.py --check` 1 项漂移=domains/chat_reply/capabilities/echo.py（归属他席在飞面；此前各席记录 15 项，前端波收口重录后仅余此项）；③`doc_sync.py --check` exit=1（归属同上第 2 条失败）；④`command_catalog.py --check` exit=1 stale（命令面在飞编辑后未再生成，TTS/echo 在飞域）。**移交**：四件残余 + 挂起 3 张垫片 + 根 init 四处（S0-ROOT-c 在飞）+ 用户裁决项（wave-snapshot §二），见 §5.3 终表。

—— §5.4 完（SYNC-FINAL-b 席续跑收口，2026-09-19）。
