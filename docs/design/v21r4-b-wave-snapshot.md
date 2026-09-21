# v21r4-B 波次整合快照（INTEGRATE 席，2026-09-19）

> **性质：只读汇总，零代码、零结论新增。** 本文把本波（v21r4-B）各席交付物与日志（`docs/design/v21r4-b-*-log.md` 及各交付文档）收拢成三样东西：①交付总表（交付了什么）、②统一裁决清单（要你裁什么，按「裁决了就解锁什么」排序）、③口径差异登记（各席记录打架的地方）+④状态红线。在飞席位只标「在飞」，不替它们写结论。一切内容转引出处文档，每条带路径。

---

## 〇、一分钟总览

- **交付了什么**：矩阵 65 行回填（B1）、真实发送端口组接线**方案材料**（B2②，不是授权）、直连点改判+结构锁测试（B2③）、三份立项书（B3：L60/L71/L74）、命令格式评审材料 + kb_drift 说明（B4/B5）、五域台账 memo（B6）、「明早」提醒词表修复（本波**唯一代码交付**）。
- **还差什么**：五席在飞（WIRE-SVC 主体已落盘收尾中；MEM-DEC 材料已成稿；RK5 / REM-EVE / DIRECT-PLAN 盘面零痕迹）；真实发送端口组整组等你勾选；**50+ 项用户裁定点**散落各文档——第二节一张表收齐。
- **要你裁决什么**：直接翻第二节。最省事路径：先裁 L41（单选一项就解锁记忆接线）和搜索时效方案 B（成本≈0），再按需逐组勾 PORT-PLAN 15 项。
- **状态红线**：全波**未 commit / 未重启 / 未部署**；全部证据为离线，不支撑任何生产生效主张；重启前先跑 `scripts/pre_restart_check.py`（已核实该文件在盘）。

---

## 一、交付总表

### 1.1 已落盘交付（席位日志自记完成）

| 包 | 席位 | 交付物 | 状态 | 证据要点（转引各席日志） |
|---|---|---|---|---|
| B1 矩阵回填 | MAT | `docs/design/backend-v2-acceptance-matrix.md`（独占写，65 行四列） | 完成 | 65/65 逐行程序化比对一致、四列零空缺；统计与草案吻合（wiring：unknown 31/partial 17/**not_wired 17**；live：unknown 60/blocked 4/not_applicable 1/passed 0）；「已生效/已上线」grep 零命中；ruff 全绿（`docs/design/v21r4-b-MAT-log.md` §四/§五）。纯文档：不含任何生产行为生效主张 |
| B2② 端口方案 | PORT-PLAN | `docs/design/v21r4-b2-port-wiring-plan.md` | 完成（**方案材料，不构成实施授权**，文首显著标注） | L46-L54 九行逐行取证；real_session 三处 503 根因钉死=`real_adapter` 从未注入（`control_plane/factory.py:105-106`）；确认协议五层防误触已有测试锁定；15 项可勾选前置条件（§3.2）+三级回滚；实施前提=用户逐项勾选 |
| B2③ 改判+结构锁 | WIRE-DIRECT | `tests/test_v21_wiredirect_unified_path.py`（新增 4 例）+ 席日志改判记录；**矩阵四行零改动**（禁改文件） | 完成 | 总裁定：L56/L57/L58/L65 经逐一取证**均无「绕过统一出站路径的直连点」**，规划期推测未落核实，不硬造收编。改判：L56/L57/L58=blocked（生产装配+出站授权双阻塞；存量提醒生产线已走统一路径，「并行未切」系误读纠正）、L65=端口组性质（LLM 解释端口）维持 503 not_wired。实跑：新 4 例 passed+相关存量合跑 149 passed+ruff+catalog 77 topics+mypy 单文件通过（`docs/design/v21r4-b-WIRE-DIRECT-log.md` §一/§三/§四） |
| B3 立项书×3 | CHARTER / CHARTER-b | `docs/design/v21r4-L60-立项书.md` / `docs/design/v21r4-L71-立项书.md` / `docs/design/v21r4-L74-立项书.md` | 完成 | 纯提案零代码，基线取证逐条 file:line；三测试件合跑 61 passed（CHARTER 席 2026-09-18 实跑，离线）；三份分别开放 5/6/7 条问题待用户裁（`docs/design/v21r4-b-CHARTER-log.md` 交付清单） |
| B4 命令评审材料 | DOCS | `docs/design/v21r4-command-format-review.md` | 完成 | 现状 77 topics/501 别名/33 路由**原样未动**；最大裁决点=14 领域（v21r2 提案）vs 20 域（代码目录）坐标系分歧；77 条逐条归属总表+落码波及 14 文件整链清单+四阶段工作量（评审通过后才动码） |
| B5 kb_drift 解释 | DOCS | `docs/design/v21r4-kb-drift-explainer.md` | 完成 | 说人话三问齐全：目录卡 35341 vs 原文 4611（4539 已配卡）；预检只读不改；重建与否=用户裁定，AI 不代改运行数据 |
| B6 台账 memo | LEDGER-b | `docs/design/v21r4-b6-ledger-memo.md` | 完成 | 五项调研全带真身坐标：①搜索时效三方案（待裁）、②合并转发**已闭环待重启**+live 观察点、③提醒残余五项（#1「明早」已被 REM-DAWN 修掉）、④LLM 故障转移九项 live 证据采集清单（重启后）、⑤亲密话术指针（本波不动）。零实装 |
| 提醒修复 | REM-DAWN | `plugins/bot_unified_runtime/domains/schedule/store/reminders.py` + `tests/test_reminder.py` | 完成（**本波唯一代码修复**） | RED→GREEN 两态实跑：「明早8点」上午场景错记今天 08:00 实锤（06:30 说→label=今天）→`_DAY_OFFSETS`/`_ABS_TIME_RE`/`_PERIOD_ONLY_RE` 三处补「明早」；存量 5 个提醒测试文件 64 passed+ruff 全树+catalog 77+doc_sync 零漂移（`docs/design/v21r4-b-REM-DAWN-log.md`）。**重启后才生产生效** |

### 1.2 在飞席位（只标状态与盘面事实，不写结论）

| 席位 | 认领包 | 盘面现状（只记事实） |
|---|---|---|
| WIRE-SVC | B2① 服务装配组（L39 WORLD/L40 KB/L42 DB/L43 TEACH；L41 明确不接） | **在飞（主体已落盘，收尾中）**：`runtime/service_wiring.py` 新件+根 `__init__.py` 装配插入段（~4124-4143）+config 三新键（缺省 False）+catalog/.env.example/auto-facts 同步+`tests/test_v21_wire_svc_assembly.py` 12 例；日志实跑 12/96/105 passed+ruff+catalog+doc_sync；日志自记余项=**全量回归一次+装配坐标终稿**（`docs/design/v21r4-b-WIRE-SVC-log.md` 检查点 3）。含一笔事故记录：测试 stub 门缺省笔误曾把空 schema 教导库写进 Runtime data，已备份 %TEMP% 后清除、复跑确认无残留（同日志事故记录） |
| MEM-DEC | L41 裁决材料 | `docs/design/v21r4-L41-decision-memo.md` **已在盘**，其日志自称「本席完成」；任务书将在飞名单含本席——交付物已成稿可直接引用（本快照 §2.2 已收编），终态以其席位记录为准（`docs/design/v21r4-b-MEM-DEC-log.md`） |
| RK5 | 控制面三小债（control_plane/api + tests/test_controlplane*） | **在飞**：协调表认领行在案；无日志、无交付物在盘，零盘面证据 |
| REM-EVE | 明晚时段语义修复（reminders.py + test_reminder.py） | **在飞**：协调表认领行在案；无日志在盘。事实提示：认领文件与 REM-DAWN 已交付为**同一文件**，续作前须读最新文件态（AGENTS.md 共享文件纪律） |
| DIRECT-PLAN | S0 直连点收编方案（`docs/design/v21r4-b2-direct-collect-plan.md`） | **在飞**：认领行在案；目标交付文件尚不存在（本席 ls 实核 2026-09-19） |

**并发协调事实**（登记备查）：WIRE-DIRECT 取证期间根 `__init__.py` 行号因 WIRE-SVC 在飞插入两度漂移，该席对该文件保持只读（`v21r4-b-WIRE-DIRECT-log.md` §〇）；`domains/core/decision/outbound_registry.py:590-600` 登记表坐标陈旧（4070/4878/5175）已由 WIRE-DIRECT 移交登记表 owner（同日志 §五.4）。

---

## 二、统一裁决清单（本波最大价值：散落各文档的裁定点一张表收齐）

### 2.0 总表（按「裁决了就解锁什么」排序）

| 序 | 裁决组 | 出处文档 | 影响 | 裁决后解锁 | 不裁决的后果 |
|---|---|---|---|---|---|
| 1 | **PORT-PLAN 15 项前置条件**（真实发送端口组） | `docs/design/v21r4-b2-port-wiring-plan.md` §3.2 | B2② 九行（L46 主角+L50/L51/L52 对外发送面） | real_session 真实发送实施波（7 步） | workspace real_session 保持 503 not_wired（create/preview/send 三处）；矩阵相关行保持 not_wired |
| 2 | **L41 记忆库三案** | `docs/design/v21r4-L41-decision-memo.md` §⑤ | 矩阵 L41（现文件第 43 行，−2 口径见 §三）；teaching 分支已留挂点 | 装配席照 teaching 模板接线（约 20 行级） | L41 永久 not_wired；v21 记忆实现（41 例测试在盘）上不了生产 |
| 3 | **搜索时效三方案** | `docs/design/v21r4-b6-ledger-memo.md` §① | web_search/acg_search/chat.py 注入行 | 方案 B 成本≈0 立即可做；A/C 按裁推进 | 「检索截至」缓存命中时继续说假话；latest 新内容继续被旧条目压底 |
| 4 | **「一会儿」默认时长** | 同上 §③#4 | `store/reminders.py` 解析面 | 提醒残余 #4 可实施 | 「一会儿提醒我」继续诚实拒绝（解析不出，非错记） |
| 5 | **DOCS B4 八项裁决点** | `docs/design/v21r4-command-format-review.md` §五 | 命令四段式整链（14 文件锁死数据链） | 命令统一实施波（中档，8-10 批启用） | 77 命令维持无分层平铺；14 领域 vs 20 域分歧继续悬置 |
| 6 | **L60 好感误扣五条** | `docs/design/v21r4-L60-立项书.md` §八 | 好感补偿线（Adjust 执行器+登记表+口径成文） | S 级补偿通道落地；早裁早止损（48h 证据窗） | 3865067623 聚合指针继续无结论；unknown 事件可核查性继续流失 |
| 7 | **L71 自修复六条** | `docs/design/v21r4-L71-立项书.md` §八 | repair 链（G1 提案源桥/G3 人工入口） | M 档立项实施（裁 a+REST 缓行可降 S） | repair 服务继续零生产调用方；PATCH_REQUIRED 上报链断在半路 |
| 8 | **L74 验收产物七条** | `docs/design/v21r4-L74-立项书.md` §八 | ArtifactStore/ReportService/admin 取件入口 | M 档立项实施（缓 REST/SSE 可降 S） | 产物四步断言永远缺后半；admin 无合法取件入口 |
| 9 | **kb_drift 重建与否** | `docs/design/v21r4-kb-drift-explainer.md` §4 | Runtime 知识库数据（AI 不代改，须你亲办/授权） | 三步链收拾（同步→补嵌→重建） | 废卡继续累积——不影响日常聊天，检索质量/速度打折 |
| 10 | **L56/L57/L58 生产启用授权**（装配后） | `docs/design/v21r4-b-WIRE-DIRECT-log.md` §一/§五 | 课表/事务链/提醒新引擎真实投递 | WIRE-SVC 装配完成后注入真实 SendQueue 即活 | 新引擎保持 queue=None 诚实干跑（`not_authorized`）；存量提醒生产线不受影响 |

### 2.1 组 1：PORT-PLAN 15 项前置条件（真实发送端口组，逐项勾选；未勾满不得动码）

出处：`docs/design/v21r4-b2-port-wiring-plan.md` §3.2。**第 1 项是总闸**：选「否」则 2-14 全部作废、全组维持 not_wired/503 现状。第 5 项内含三处 TTL 口径分歧裁定（§2.1.3-C：guide 通用 120s / workspace 合同与实现 300s / image 契约 120s）。

- [ ] 1. 本波是否实装 real_session 真实发送端口？（是/否——否则本组全部作废）
- [ ] 2. 确认总门键名 `bot_control_plane_workspace_real_session_enabled`，缺省 False（关）
- [ ] 3. 提供 session 白名单内容（留空=整链关闭；提供即视为授权向这些会话发送）
- [ ] 4. 确认每日全局发送上限数值（建议 10）
- [ ] 5. 确认 token 有效期：workspace 维持 300s 还是统一 120s（三处口径分歧裁定）
- [ ] 6. 确认确认主体=控制面超管 Bearer 写令牌持有者，无第二确认人
- [ ] 7. 回执增强（session 脱敏回显+SendQueue request_id 关联）：要/不要
- [ ] 8. send 受理/完成是否推控制面 SSE 事件（建议一期不做）
- [ ] 9. 安静时间豁免与否（建议豁免+审计显式记录）
- [ ] 10. L50（FILE-002 发送段）是否纳入同批确认（建议单独批次，待 L46 首证稳定后再议）
- [ ] 11. L51/L52（TTS/绘图）：先裁 provider 选型+`capabilities/tts.py` 归属（W-PA2），未裁前不做（live 维持 blocked）
- [ ] 12. L47/L48/L49/L53（中风险组）是否随控制面增量批次另排
- [ ] 13. 知悉回滚方式：配置门关/白名单清空/工厂单点摘除，三级均可回到 503 not_wired
- [ ] 14. 知悉生效条件：接线合入后需用户手动提权重启；重启+实跑证据前矩阵不得升 wired
- [ ] 15. （边界知悉）L41 记忆库裁决不在本方案（见组 2）

### 2.2 组 2：L41 记忆库（主裁定单选+条件附加项）

出处：`docs/design/v21r4-L41-decision-memo.md` §③④⑤。背景：任务书要求「同源同库」，在盘实现为独立新库，前提冲突待裁（`docs/design/v21r2-v2-memory-log.md` §5）；未裁决前 L41 不得接线（HANDOFF-V21R4-B:158）。

**主裁定（单选）**
- [ ] A. 独立新库 `data/memory_v21.sqlite3`（**memo 推荐**：零实现改动、隔离最优、可逆性高；41 例契约按 A 写就全绿）
- [ ] B1. 同源同库·同文件并存（四张 `*_v21` 表并入生产 wuwa_memory.sqlite3 与 memory_facts 并存；接受双连接并发回归+db-owners 改写）
- [ ] B2. 同源同库·改造 memory_facts 本体（生产表 schema 迁移——**memo 不建议**：五个消费点全回归+触碰「运行数据不可删」高危区）
- [ ] 暂不裁决，L41 继续保持 not_wired

**若选 A，附加**：新库路径键名（建议 `bot_memory_v21_db_path`）；分门形态（路径键非空即接 vs 另立 `bot_memory_v21_enabled` 更保守）；旧 memory_facts 存量不迁移（建议）vs 要求迁移。
**若选 B1，附加**：接受 db-owners 登记改写（v21 墓碑禁清语义）；旧栈连接补 WAL/busy_timeout 与否（建议补）。
后续归属：裁决后由装配席按 memo §2.4 框架接线，本 memo 不构成实施。

### 2.3 组 3：搜索时效三方案（可组合）

出处：`docs/design/v21r4-b6-ledger-memo.md` §1.2。memo 推荐口径：**B 立即可做（收益/成本比最高），A 轻量跟进（只做缓存键含档），C 挂起**（等 Tavily publishedDate 契约确认+计费裁定两个外部条件）。

- [ ] 方案 A：缓存 TTL 分档（latest 档跳过缓存或压到 60s+缓存键纳入时效档；代价=latest 计费外呼变多）
- [ ] 方案 B：标注层修正（缓存条目记墙钟+「检索截至」缓存命中时改措辞；成本≈0，纯诚实面）
- [ ] 方案 C：时效加权补全（按档自动填 Tavily time_range+web 命中回流日期；依赖 Tavily API 行为实证+计费确认）

附带三个子裁决点（memo §1.2 末）：①接受 latest 缓存变短的计费增量？②缓存命中时「检索截至」具体措辞；③time_range 只对 latest 档生效还是全局配置。

### 2.4 组 4：「一会儿/待会儿」默认值

出处：`docs/design/v21r4-b6-ledger-memo.md` §③#4。现状：模糊相对词解析不出→诚实拒绝（usage 兜底）。memo 提议默认 **15 分钟**，但明言涉及产品语义需用户裁定。

- [ ] 默认 15 分钟（memo 提议值）
- [ ] 其他：＿＿＿＿
- [ ] 维持不支持

### 2.5 组 5：DOCS B4 命令格式八项裁决点

出处：`docs/design/v21r4-command-format-review.md` §五（评审时逐个勾；全部为提案，77 topics/501 别名/33 路由现状未动）。

1. [ ] **一级功能名坐标系**：方案 A（14 领域口语词）/ 方案 B（20 域对齐代码目录）/ 折中（口语词定名+域序对齐 20 域）——**本材料最大裁决点**（§2.2）
2. [ ] §3.1 总表 8 条「两案择一/待裁决」行：帮助、语音、队列、群信息、解析、搜索、群策略/群摘要归属
3. [ ] 资讯族 5 条（快报/维基/萌百/历史上的今天/Epic）：挂 subscribe 兼任 vs 新设「资讯」域（20 域现无资讯域）
4. [ ] v21r2 §4.1 领域九形态定名逐个过目（含 `lt`/`bq`/`lj`/`jr` 等建议启用值）
5. [ ] v21r2 §5.3 建议新增 ≈60 个别名形态取舍
6. [ ] 「地点」能力是否借此立项（20 域已有 location 含 poi/，现无命令）
7. [ ] 配置型主题 8 个（限流/合并转发/群摘要/视频理解/运行开关/Telegram/供应商/忽略）只能做说明页形态，确认接受
8. [ ] 兼容层回收时机（不做默认裁定，观察期后再议）

### 2.6 组 6：L60 好感误扣补偿五条（补收编——任务书清单未列，但属散落裁定点，故并入）

出处：`docs/design/v21r4-L60-立项书.md` §八。时效注记：逐事件证据仅保留 48h 滚动窗（affinity.py:202），超窗永久缺失只能走人工路径——早裁早止损。

1. [ ] unknown 26 条要不要逐条人工回查（建议只对聚合指针显著者 3865067623 核查，其余归档不追）
2. [ ] 3865067623 聚合指针（-31.6 分/insult_count=10）处置：是否部分补偿、补多少（管理员具名裁决，机器不提议数额）
3. [ ] 补偿写法二选一：UPDATE 直改（不落账）vs delta_log 追加行（账实一致但占 24h 增益预算）
4. [ ] Adjust 执行器形态：本轮只立项登记 vs 立即实施（S 级）；是否要控制面 REST 入口
5. [ ] 误扣判定口径文档归属：留在立项书 vs 独立成文 `docs/design/affinity-misdeduction-policy.md`

### 2.7 组 7：L71 自修复六条

出处：`docs/design/v21r4-L71-立项书.md` §八。红线贯穿：人工审核通过也不自动部署（扩展 §7.2:243）；裁决前不动码。

1. [ ] 提案源形态三选一：a 事件桥+人工登记（S 级，建议先跑通全链）/ b 规则模板 / c LLM 辅助（需用户显式批准）
2. [ ] repair/ 与 recovery/ 域边界：维持两域单向桥接（默认零迁移）vs 合并单域（动 13 测试引用面）
3. [ ] REST/命令是否本轮接生产（不接则 G3 仅有命令面方案）
4. [ ] 审批角色（super_admin only？）与待审件保留期/上限
5. [ ] 「具名授权控制动作」边界：是否采纳保守口径（应用与部署均人工）
6. [ ] StaticProposalGenerator 占位生成器去留

### 2.8 组 8：L74 验收产物七条

出处：`docs/design/v21r4-L74-立项书.md` §八。核心红线：状态机无 viewed 档——平台无 read receipt 不能伪称已观看。

1. [ ] admin 白名单口径：super_admin 直通 vs 独立配置键
2. [ ] 产物存储根目录+登记形态：新 SQLite 库（须入 db-owners）vs 文件+索引 json
3. [ ] 「大资产」阈值数值（合同未定义 MB 数）
4. [ ] 直接附件上限 5 是否沿用（§8.2:281 默认值）
5. [ ] REST/命令/SSE 本轮是否接生产（不接则只落域内载体）
6. [ ] 与域外 `scripts/e2e_acceptance.py` 复用边界三选一：Runner 调脚本 / 脚本供数据 / 双轨并行
7. [ ] 授权包来源：真实 run 时由谁签发、走控制面哪个入口

### 2.9 组 9：kb_drift 一项

出处：`docs/design/v21r4-kb-drift-explainer.md` §4。两个选项选哪个都成立；重建会重写 Runtime 运行数据，按项目铁律 **AI 不代改**——由你自己决定、自己执行。

- [ ] 不管它（机器人照常跑；检索质量打折、废卡越积越多）
- [ ] 重建索引（三步链：同步→补嵌→重建；建议先备份）
- 复查方式：`python scripts/pre_restart_check.py` 第 5 项变绿（`ANN=4611 == chunks=4611`）即收拾干净

### 2.10 组 10：其他散落授权/裁决点（收口备查）

- [ ] **L56/L57/L58 真实投递授权**：WIRE-SVC 装配完成后，「注入真实 SendQueue=启用真实投递，须用户授权」；注入前新引擎保持 `not_authorized` 诚实干跑（出处：`docs/design/v21r4-b-WIRE-DIRECT-log.md` §一 L58/§五.2）
- [ ] **L65 塔罗解释端口**：接线=真实 LLM 外呼（成本+question 上下文外流），未获授权维持 503 not_wired；WIRE-DIRECT 建议并入端口组方案——事实：PORT-PLAN 现文档 §四.4 明确划界不越界、未纳 L65，是否补录归后续裁（出处：`v21r4-b-WIRE-DIRECT-log.md` §一 L65/§五.3）
- [ ] **亲密话术遗留三项**（本波不动，指针 `docs/design/v21r2-rp-style-log.md` §七；LEDGER memo §⑤ 转记）：输出侧硬保证（涉 `bot_persona_action_brackets` 默认语义，待用户裁决）/战斗语音负向示例（实测仍复读才加）/INTIMATE 会话态判定语义（既有裁定）
- 非裁决项的信息缺口 5 个（PORT-PLAN 附 A unknown 清单，实施前需补证）：矩阵 L46+ 回填现值（MAT 已完成收口，见 §三.5）、DNS rebinding 深防证据、九源真实可达性、SendQueue worker 对接细节、pypdf 装后行为升级面

---

## 三、口径差异登记（各席记录不一致处，留档待收口波核对）

| # | 差异 | 内容 | 出处 |
|---|---|---|---|
| 1 | not_wired 计数 17 vs 18 | HANDOFF §1.3 记「not_wired=18 行含 L65」vs 草案 §尾注记 17。MAT 按草案表落定：L65 wiring=partial（控制面 REST 已挂接），LLM 解释端口才是 not_wired 位；此计数口径差异留档待收口 | `docs/design/v21r4-b-MAT-log.md` §三.2；`v21r4-b2-port-wiring-plan.md` 附 A 数字口径注（draft:143 记 17，交接书按 18 推进） |
| 2 | live unknown 61 实为 60+1 | 草案 §四统计行「live unknown 61」按行级表实为 **60 unknown + 1 not_applicable**（L75 纯文档规格行）；矩阵按草案行级表落定 | `docs/design/v21r4-b-MAT-log.md` §三.3 |
| 3 | 六行清单外按表落定声明 | L13/L16/L32/**L37/L61**/L68 未列入草案 §〇.2「可直接覆盖」清单，但 §一表给出带证据明确值（conf=verified/high）→按表落定并在此声明；L70/L72 conf=unknown→四列维持现值仅并注记（符合 §〇.4） | `docs/design/v21r4-b-MAT-log.md` §三.1 |
| 4 | 矩阵行号整体 +2 | MAT 批注合入矩阵头部（现第 7 行）后主表整体 +2：**交接书/草案 L 编号 = 现矩阵文件行号 − 2**（L46→现 48、L51→现 53 等；旁证=`domains/creation/tts/contracts.py:3` 自引「矩阵 L51」→现文件第 53 行）。PORT-PLAN 方案全文双编号并列杜绝歧义 | `docs/design/v21r4-b2-port-wiring-plan.md` §〇；`docs/design/v21r4-b-PORT-PLAN-log.md` 开工段 |
| 5 | PORT-PLAN 读时快照 vs MAT 终态（时序差，非矛盾） | PORT-PLAN 取证时矩阵 L46+ 区间仍为回填前值、记「MAT 回填疑在飞」（其 §1.1b 如实登记 unknown）；MAT 终态=65/65 全量落定并程序化验证。以矩阵现文件为准；PORT-PLAN 方案引用草案 §一为状态基线不受影响 | `v21r4-b2-port-wiring-plan.md` §1.1(b)；`docs/design/v21r4-b-MAT-log.md` §四/§五 |
| 6 | （连带）在飞行号漂移 | 根 `__init__.py` 行号因 WIRE-SVC 在飞编辑两度漂移（WIRE-DIRECT 实测，故对该文件只读）；`outbound_registry.py` 登记表坐标陈旧（4070/4878/5175）已移交登记表 owner。行号类引用一律以符号名为准（LEDGER memo 同口径提醒） | `docs/design/v21r4-b-WIRE-DIRECT-log.md` §〇/§五.4；`docs/design/v21r4-b6-ledger-memo.md` 文首 |

---

## 四、状态红线声明（全波口径，各席自查一致）

1. **未 commit**：全波交付均在工作树（MEM-DEC 只读 git 实查 v21 记忆五文件全部 `??` 未跟踪在案；各席日志「未 commit」自查一致）。
2. **未重启、未部署**：生产 bot 未动。REM-DAWN 修复、合并转发根治、WIRE-SVC 装配等一切代码面改动均**重启后才生效**。
3. **全部证据=离线**：离线 mock passed / 源码直读 / 只读文档 ≠ 生产生效（MAT「不含任何生产行为生效主张」、REM-DAWN 诚实边界、LEDGER memo 诚实声明、三立项书诚实声明同口径）。离线绿不升 live passed、不升 wired。
4. **零真实对外动作**：全波零真实发送、零真实 LLM 调用、零子代理派遣（各席自查一致）；真实发送端口组在你勾满 15 项前保持 503 not_wired / 矩阵 not_wired（PORT-PLAN §四.2 静止态）。
5. **重启前置**：`scripts/pre_restart_check.py`（含第 5 项 kb_drift 体检，只读不改；本席已核实文件在盘）。
6. **渲染红线零触碰**：`theme_tokens.py` / `tests/render_hashes.json` / `domains/render/**` 本波零改动（各席自查；INTEGRATE 本席只读同守）。

---

## 附：本快照自身边界

INTEGRATE 席只读汇总：未跑任何测试、未改任何既有文件（仅新建本文件与席位日志）、零 git 写操作、零子代理、零 LLM 调用。一切结论转引出处文档；文内行号/坐标以各出处文档为准（行号漂移见第三节）。在飞席位（WIRE-SVC/RK5/REM-EVE/DIRECT-PLAN）终态以其后续日志为准。

---

## §六 2026-09-20 午后补录（主代理席整合，SNAPSHOT-R2 席阵亡后吸收）

### 6.1 交付补录总表（上午快照之后）

| 交付 | 席位 | 关键证据 |
|---|---|---|
| S0 非 root 件收编（outbound_registry 登记+5 测试） | S0-COLLECT | 125 passed 家族合跑 |
| S0 根内四处直连收编（形态 B/A/A/D，四配置门缺省关） | S0-ROOT-c | tests/test_v21_s0_root_collect.py 27 例；家族 195P |
| outbound_registry 登记表刷新（8 处+坐标棘轮 4440/5378/5730/5526） | REG-REFRESH | 家族 115 passed；门开分支锁定 |
| 垫片退役收尾 3 张（contracts.runtime/decision.outbound/sources.web_search，73 文件归 canonical+4 处包级盲区+dev.ps1 断言+探针串） | 主代理席 | AST 零残余；全量 8535P（2 处连带修复后归零）；contracts/media.py 挂起（bridge.py 前端独占） |
| 「RWC1 SKIP 四件」定性修正+闭环（实为四模块留守台账，均已迁真身） | LEGACY-FIX-c | 129 passed；echo (44) 已被 TTS 席修至 46，command-catalog 已收敛 77 topics |
| 波末文档四件套用（AGENTS #42/HANDBOOK §33/README 索引/HANDOFF 三处） | HANDBOOK-SYNC | 六 grep 锚点各 1 命中 |
| MYPY-FIX 关账（model_router:439 已净，Success 0 error） | 主代理席 | scoped mypy 复验 |
| 提醒双修（明早=次日上午；明晚8点=次日20:00）+守护家族 125P | REM-DAWN/REM-EVE | RED→GREEN 双态实证 |
| 09-19 三告警调试档案（外部网络中断+冷却实锤 15→6；**双实例+现役实例跑错解释器**待用户处置） | 主代理席 | docs/design/v21r4-b-20260920-alert-triage.md |
| Token/缓存审计结论（统计链路无缺陷；gemini 缓存 0=上游不回字段；账单量级相符） | 主代理席 | docs/design/v21r4-b-TOKEN-AUDIT-log.md |
| 控制面三债清零（xfail 转正+OpID 唯一+mypy 归零） | RK5 | 扩面 436 passed |
| 重启就绪快照 | RESTART-GATE | **在飞**（以日志终态为准） |

### 6.2 用户裁决/动作清单（更新版；原 §二 仍有效项不重复）

**新增动作项**：
1. **双实例处置（最高优先）**：现役 bot（PID 见调试档案）用系统 Python 而非 venv，另有 venv 僵尸实例——提权杀两进程→venv 单实例重启→netstat 验证。
2. **axonhub 控制台**：①「User-Agent 透传」不用开（与统计无关）；②「透传」仅在客户端与渠道格式一致时生效——bot 用 OpenAI 格式、渠道配 Gemini 格式故不生效；要 gemini 缓存命中可见，把该渠道 API 格式改 OpenAI（若上游支持）或先看 axonhub「用量统计」是否自己记到缓存字段；③核对恒星纪元-Gemini 渠道模型名（列表是 3.7 系，链里是 3.8）。
3. 可选：`BOT_LLM_BILLING_ENABLED=true` 落持久账本；报告「缓存 0」加注「上游未回字段」。

**原 §二 仍待裁决**：端口组 15 项前置、L41 两案（memo 推荐 A）、L60/L71/L74 开放问题、B4 命令评审 8 项、搜索时效三方案、「一会儿」默认值、kb_drift 重建。

### 6.3 剩余 blocked 终表

| 项 | 阻塞于 |
|---|---|
| contracts/media.py 等 4 张垫片退役 | 前端 echo/render 在飞收口（bridge.py 独占消费） |
| verify_hashes 15→1 项漂移重录 | 前端波收口（重录归前端，后端禁 --write） |
| 视觉门禁 23 红 + ruff 前端域残错 | 前端波收口 |
| 65 行 live_validation | 重启+真机验收（LIVE-TOOL 采集脚本已备） |
| 四直连门真机验收 | 重启+拨门 |
| .tmp-test 树卫生 | 占用进程（疑 TTS 跑测试）释放后清理（备份已在 %TEMP%） |

### 6.4 状态红线
全波未 commit/未重启/未部署；全部离线证据不支撑生产生效；重启前置=scripts/pre_restart_check.py + venv 单实例。
