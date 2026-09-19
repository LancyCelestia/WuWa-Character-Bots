# 后端 V2.1 会话更新日志（2026-09-17 凌晨 — 09-18，两波：v21 主会话批 + v21r2 多席批）

> 本文件是本轮实施会话的收尾日志：记录用户要求、已完成工作（全部带实跑证据与日志坐标）、尚未完善部分与断点续接指南。 HEAD=`56d1461`，分支 `v0.0.1-alpha.2`，**全部改动留在工作树未 commit**（共享工作树纪律，提交裁决权在用户）。
> **2026-09-18 刷新**：并入 v21r2 波（R1-R8+V1/V2+S8-S14+RW1-RW16/WC1-4+CMD/SEARCH/RP/PA/RO/INT/FIX/FIX2/MAT/EP1+各续跑席）真实交付；原 A/B/C 未完善清单已逐项对账（见 §四）。数据源=docs/design/ 下 52 份 v21r2-*.md（席位日志 44 + 协调/方案/矩阵草案/命令规格 8），全部只读采集；**在飞 5 席（RWOCb/S14b/WIREb/RK4b/EP1）终态以其日志为准，本页按 2026-09-18 05:4x 快照记账**。

---

## 一、你的要求（本轮会话指令全集）

1. **接手并实际完成后端 V2.1**——实施任务不是重新规划；前端页面不做，但前端所需后端协议（REST/SSE/DTO/权限/错误/状态/资产/实时事件）必须完整；禁止演示 API/占位处理器/局部即收工。
2. **执行方式**：时刻保持子代理满载并发（先 7 席、后按你指令定为 6 席）；一个结束立即补派直至任务全部完成；以限流（1302）为唯一上限，撞墙先落盘保进度、指数退避、只补未完成；主会话不占前台，派完即收；每 15 分钟自动巡检（本条为阶段性指令，收尾时按你最新指令停止并已删除巡检自动化）。
3. **已定决策不再询问**：保留全部 WIP，不 reset/clean/覆盖他人，不擅自 commit/push；复用现有 Service/RuntimePipeline/SendQueue/ledger/检索/牌组，不建平行实现；所有业务插件最终 Windows AppContainer＋Job Objects 强隔离，隔离不可用必须明确阻断；自愈可恢复运行，代码补丁只出待审件不自动部署；运行数据/人格资产/凭据/代理受保护；人格与权限不可被任何输入篡改；grok 主题路由与关系评分分离，拒答≠辱骂。
4. **首要真实风险必须先复现再修**：好感度（refuse 归 insult/单位 100 倍/override 绕额度/一晚掉 40 多分历史因果 unknown）、dev.ps1 强制 autosync 污染基线、主规范 §1 控制面八项风险。
5. **验收纪律**：每需求分别记录 implementation/production_wiring/offline_validation/live_validation；源码存在、mock 通过、HTTP 200 都不单独证明业务可用；测试必须实跑，禁编造；未闭环不称完成。
6. **收尾指令（前批）**：所有子代理结束后不再派出新子代理，收尾，新建本 md 记录更新日志，写明你的要求与尚未完善的部分。
7. **本波（v21r2）延续上述 1-5 全部纪律**；新增执行面：板块重组按 `docs/design/v21r2-reorg-plan.md` 施工图（§2 域结构/§5 波模板/§6 门禁网）执行，PA 席 §8-§10 合同对齐与预留随后补齐；每席四列自记 + `v21r2-COORDINATION.md` 记账 + 席位日志落盘；「未闭环不称完成」由 MAT 席回填草案（`v21r2-matrix-backfill-draft.md`）机器化执行。

---

## 二、执行台账（前批 19 批次 + 本波 51 席）

- **前批（2026-09-17 凌晨—上午）**：共派遣 **19 个子代理批次**（含限流阵亡重派与会话挂起后断点续跑）；限流 1302 阵亡 6 次、会话挂起静默阵亡 6 席（03:17-07:43 全军静默一次），全部按「断点续跑、只补未完成」恢复，零重复劳动。15 分钟巡检自动化在收尾时按你指令**已删除**。
- **本波 v21r2（2026-09-17 晚—09-18）**：共派遣 **51 个席位标签**（R1-R8×8、V1/V2×2、S8-S14×6、DSP/SEARCH/RP/PA/RO/INT/FIX/FIX2/MAT/CMD×10、RW1a-RW16×16、RWC1-4×4、RWPA1×1、在飞 WIRE/RK4/EP1/RWOC/S14×5）；**收官 46 席、在飞 5 席**。
- **阵亡与续跑（有日志实证）**：限流 1302 阵亡 3 席次——R1 前任（15 分钟撞墙未落盘，r1 log 卷首）、R2 前任（23:24 撞墙未写日志，r2 log 卷首）、RW14 前任（1302 阵亡零改动，COORDINATION）；静默阵亡 4 席次——V1 前任（零落盘阵亡，v1 log 卷首）、S12 前任（04:24-04:30 计划期后静默死亡但在盘留产，s12 §〇）、RK4 前任（静默死亡零落盘，rk4 log 卷首）、DSP 前任（存活至 ~04:34「写完未验」死亡，dsp log §二〇）。全部按「断点续收取证→只补未完成」恢复，零重做；另有 R5 第 4 次派遣、RW15 简报偏差改派（W15→W14，rw14/15 日志记）。
- **记账形态**：`v21r2-COORDINATION.md` 52 条席位记账（认领+完成双记）；席位工作日志 44 份 + 矩阵回填草案/重组方案书/命令规格五件套落盘 `docs/design/v21r2-*.md`（共 52 份，ls 实数）。
- 主会话每轮派完即收，前台留空；**当前无常驻自动化在跑**（前批巡检已删除，本波日志无重新启用证据）；**在飞 5 席：RWOCb（ops+core 尾声波回归验收）、S14b（自愈三子包实跑）、WIREb（人格注入接线实跑）、RK4b（风险 4 四项）、EP1（尾声清账，首项已闭环）**——终态以其日志为准。

## 三、已完成工作

### 3.0 前批基线（2026-09-17 凌晨—上午，14 领域，原表保持为历史证据）

| # | 领域 | 产物 | 实跑证据 |
|---|---|---|---|
| 1 | S0 冻结 | `docs/design/v21-s0-inventory.md` | 入口全量：50 matcher/12 调度族/62 控制面路由；绕 SendQueue 直发嫌疑 3 组（`__init__.py:4071/4879/5175`）；工作树 84M+60 未跟踪归属清 |
| 2 | 真实基线 | `docs/design/v21-s0-baseline.md` | BOT_AUTOSYNC=0 直跑全量：7050 passed/41 failed+28 errors（252.8s）；ruff 26E/mypy 11E；**5 生成物哈希零漂移（基线无污染）** |
| 3 | autosync 门禁修复 | `tests/conftest.py`（is_autosync_enabled）+`tests/test_autosync_gate.py` 36 例 | 显式 0/false/no/off 全禁用、默认行为字节级兼容；verify_hashes --check EXIT=0 |
| 4 | S2 DTO/错误协议 | `contracts/envelope.py`+`errors.py`（41 码单一注册源）+`request.py` | 151 passed；import 探针：新模块零副作用，父包 `__init__` 拉起 nonebot（+1074 模块）已如实记录 |
| 5 | 好感度修复 | `character/affinity.py`（score_relationship_signal+policy_revision v21.1）+滚动预算 SQLite+poke 0.1 分 | affinity/poke 全域 **110 passed**；拒答/七族非关系事件零计分；预算 6h≤2/24h≤4/增益≤3/冷却 60s 幂等 |
| 6 | 八项风险 RED 取证 | `docs/design/v21-risk-red-report.md`+4 测试文件 22 条 strict-xfail | 22 xfailed/0 failed/0 xpassed，八项全 verified（含 `_app.py:425`、CAS TOCTOU、Persona 假成功三件套、TG catch-all、节日表跨年、.xls/.ppt） |
| 7 | 控制面收绿 | `control_plane/_app.py`+`api/platform.py` 等 | 60 红收敛 3 根因全灭，控制面域 **457 passed/0 failed** |
| 8 | 需求映射 | `docs/design/v21-s0-mapping.md` 65 行全 | 矩阵 55 行 implementation→partial（附证据路径），10 行整项缺席保持 unknown |
| 9 | 风险6/7/8 修复 | `scripts/telegram_resilience.py`+`temporal.py`+`character/reminders.py`+`sources/file_reader.py` | 6/6 xfail 转正，相关域 355 passed/0 failed；TG 401/403/409 定向分类、节日表年份维度、提醒配置时区、旧 Office 诚实降级 |
| 10 | S5 事件服务 | `runtime/event_store.py`+`event_service.py` | 19 passed×3 轮；Last-Event-ID 续传/游标过期 resync/15s 心跳/慢消费者有界断开/先持久化后投递；集成点已写清（`_app.py:321-342`） |
| 11 | S11 日程核心 | `runtime/schedule_dag/rrule/store/service.py` | **49 passed**（两独立席位交叉验证）；DST fold/单双周/租约 BEGIN IMMEDIATE/防风暴 3/min·20/h |
| 12 | 假成功修复 | `control_plane/platform.py`+persona 相关 | 前批仅风险 1/2 落地；**风险 3 已由本波前置批 A12 假成功修复席转正（v1 log §0：cp_platform 9 passed 实证），欠账清** |
| 13 | S5 计费 | `llm/billing_service.py`+`tests/test_billing_service_v21.py` | 模块与测试已落盘（51KB+24KB）；本波 RWC2 迁移随迁+ledger 族回归绿（r1 §四 253 passed 含 ledger）；**仍无独立席位完成报告** |
| 14 | S12 占卜 / S6 出站地基 / S8 记忆 | `character/draw_store.py`+`runtime/divination_service.py`；`decision/outbound.py`；`character/memory_service.py` | 模块落盘；**记忆测试缺失欠账已由本波 V2 席收口（41 passed）；出站接线已由本波 DSP 席阶段 1 落地（见下表 18）** |

前批终态实跑（2026-09-17 09:1x，主会话亲跑，历史证据）：

```text
命令：固定 venv 解释器 -B -m pytest <14 个新增域测试文件> -q --basetemp=%TEMP%\v21-final3 -p no:cacheprovider
（env：PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0）
结果：453 passed, 5 xfailed, 1 failed（77.18s）
5 xfailed = Persona 假成功（风险3）2 条 + Dispatcher 收编（风险5）3 条（当时按设计保持 RED 取证态；
           两者均已由本波 V1 取证/A12 转正、DSP 转正收口，见下表 10/18）
1 failed = tests/test_sandbox_windows.py::test_appcontainer_strong_isolation_or_explicit_block（仍未收口，见 §四.A.6）
```

### 3.1 本波交付（v21r2，全部实跑取证；坐标=docs/design/v21r2-*.md 节号）

**A. 修复与风险收口族**

| # | 领域 | 产物 | 实跑证据（数字+坐标） |
|---|---|---|---|
| 1 | LLM 故障转移链收口（R1，二轮续跑） | model_router 严格优先级（`bot_chat_strict_priority` 缺省开）/90s 冷却降级 SQLite/3s 链止损/INTIMATE grok 钉一+回落日志/告警 kind 折叠+chain 压缩/BOT_MODEL_PRIORITY_GROUPS 恒 no-op 根修（分组 order 扩收模型名）/自适应超时与 latency_first 解耦 | 本文件 23 passed+回归 16 文件 253 passed 1 failed（唯一红=R2 WIP，已由 FIX 收口）；FIX2 补收 15 passed；doc_sync 4 passed；ruff 全绿+mypy 本域 0 错（r1 §二/§四/§六） |
| 2 | 进程生命周期+适配器韧性（R2 续跑） | TG 降噪+401/403/409 分类停轮询/retcode=1200 三形态改 bot_unavailable 挂起（FAILED_RETRYABLE+90s 重探不烧预算）/mail 15s 硬超时+2s 退避/Ctrl+C `_reap_background_threads` 10s 宽限/misfire_grace_time=30/早停钩子 | R2 21 passed+域内回归 111 passed 3 xfailed+核心合跑 66 passed；ruff 全绿；mypy 仅 control_plane 2 既有（r2 §三/§四）；FIX 席收口孤儿红 40+71 passed（r2 §六） |
| 3 | 停摆/吞消息根治+授时兜底（R3） | vector_knowledge 流式 fetchmany+blob 优先+锁外预热+世代号；kb_wiki 互斥+协作取消+零变更夜跳过 ANN 重建（治 8.5 分钟默认池占用）；新建 `runtime/loop_watchdog.py`；timesync HTTPS Date 头兜底（仅收 https，±1.5s 钳制，2 新键三处同生） | 新 26 例+存量 106=**132 passed**；ruff 七文件全绿；mypy 本域 0 错；根因链源码级闭合（5.67GB 库锁内全表 fetchall→聊天池堆满→SILENT_AUDIT 吞消息，r3 §一/§四）；INT 席两挂接（watchdog on_startup 修正坐标+kb 停机取消）84 passed（r3 §六） |
| 4 | 好感度 v6 平滑层（R4） | smoothstep 饱和曲线（带宽 1 档 25 分，中段 v5 字节级一致/边界归零）+同日同类 0.6^n 边际递减（下限 0.2）+日节奏帽（复用 V2.1 预算正负分账）；override/poke 权威通道不饱和不递减；算法卡保持全定性 | 新 24 例+全 affinity 族+poke+消费方 **151 passed**；并发异常风暴 1 passed；ruff 全绿+mypy 本域 0 错；docs/affinity-design.md v6 附录（r4 §实跑） |
| 5 | 热区审计+静默锁死（R5，第 4 次派遣） | notice 族 7 handler 全链路审计+AST 棘轮；安静时间非交互 BLOCKED 双路零入队+@/指令直通回归门；kb _sync_job CancelledError 优雅退出；两餐开场 6 变体 pick_variant 轮换（R6 草案逐字落地） | 新 11 例+域内 155=**166 passed**；ruff 全绿；mypy 本域零错（r5 实跑节） |
| 6 | daily_assist 文案池化（R6） | 11 池×每池 ≥6 变体+pick_variant 确定性轮换；语气守卫常驻（违禁词/第三人称自称/轮换确定性）；行为零改动 | 21 passed；ruff/mypy 本域零错（r6 §五；第三人称口径冲突披露见 r6 §七） |
| 7 | content_route 复核+实弹探针（R7） | 检测链端到端健康复核**零缺陷零改动**；`explicit_allowed_for_session` 补 6 例零覆盖；新建 `scripts/probe_intimate_route.py`（离线默认/`BOT_PROBE_LIVE=1` 门禁实弹/密钥零解析）+14 例探针测试 | 44 passed；探针离线实测候选序（强词→grok 第一）全符合；--live 无扳机 exit=2；ruff 全绿+mypy 0 错（r7 §四） |
| 8 | 生产闪退定性+兜底（R8） | 2026-09-17 23:24 闪退定性=**外部 TerminateProcess(0xFFFFFFFF) 击杀，非代码崩溃**（事件日志/WER/faulthandler/crash.log 四面全空+exit -1 签名+回执库钉死 23:24:32.603）；击杀者 unknown（火绒 HIPS/代理 shell kill 候选）；`scripts/crash_trap.py` 心跳+退出标记+faulthandler 兜底 | crash_trap **7 passed**+ruff/mypy 全绿；bot.py 装配坐标移交 INT/R2b 落地（r8 §五/§六）；双 bot.py 进程并存移交用户（§四.B） |
| 9 | 出站统一执行器+风险5 转正（DSP 续跑） | `control_plane/dispatcher.py` OutboundSideEffectExecutor（取消闸→准入复验→PermitLease 线性化→mark_irreversible→TransportRegistry→call_api 同通道本体）；decision dispatch 阶段 1 真实派发周期（shadow 绝不发送语义保持）；poke 回戳/贴表情两组生产直连点收编门面；3 条 strict xfail 摘标转回归锁 | risk-red+wiring+outbound+poke/reactions 全族 **152 passed**（前任代码零修即过）+全仓扫掠 221 passed+复核 47 passed；ruff 全绿+mypy 本域 0 错（dispatch log §三） |
| 10 | Persona 假成功收口（V1 席取证+A12 前置批） | 风险 3 三件套（publish 真落版本/rebuild 幽灵 job/setter 假 applied）已由 A12 转正；V1 补齐哈希快照（content_digest/verify_resource）+setter 自报失败如实报 applied=False | cp_platform **9 passed**（v1 log §0 实证）；platform 补口后 11 passed 2 xfailed（xfail=风险 5，随后 DSP 转正） |
| 11 | 孤儿红三席移交收口（FIX/FIX2） | FIX：worker bot_unavailable 静默化测试期望同步（worker.py 零改动）；FIX2 三笔——error_report 掩码白名单（runtime 零改动）、video 9 红靶位漂移（chat.py 零改动）、价格聚合旧语义断言（model_router 零改动） | FIX：修前红点 @:985 实证→修后 40 passed+71 passed；FIX2：44 passed/1 skipped+12 passed+15 passed+三笔相邻回归 207 passed；ruff 全绿（r2 §六/search §五/rp §八/r1 §六 各收口记录） |

**B. 服务交付族（S/V 系）**

| # | 领域 | 产物 | 实跑证据（数字+坐标） |
|---|---|---|---|
| 12 | S7 人格/世界书版本管理（V1） | `character/persona_service.py`（draft→publish→activate→rollback+CAS BEGIN IMMEDIATE+SQL 不可变触发器+quarantine 损坏隔离留证+权限门+build_core_injection 唯一出口）+`character/worldbook_service.py`（悬空/循环引用 DFS+Token 预算+untrusted 出站标注）；两新库入 db-owners | 新 19 passed+风险红 4 文件回归 74 passed 5 xfailed+控制面存量 234 passed；冒烟抓出并修 activate/rollback 权限不一致（v1 §2/§3.1） |
| 13 | S8 记忆服务补全（V2） | 修 4 真 bug（幂等 partial UNIQUE 索引缺失/touch_used 缓存不失效/初始版本虚高/归因候选面不含墓碑）+补 5 缺失（forget 权限/空白校验/sensitivity 真引用/恢复保绑定/反思实证）；build_memory_service_v21 就绪 | 修前 12 failed/25 passed→修后 **41 passed**+存量 33 passed（合跑 74）；ruff 全绿+mypy 本域 0 错；**前提冲突报告待用户裁决**（独立新库 vs 同源同库，v2 §5） |
| 14 | S8 知识库/DB Broker/Teaching（S8） | `character/knowledge_service.py`（跨库 RRF+分数来源透出+SQLite backup API 原子重建[Windows os.replace 实证不可行后的设计修正]+embedding 版本变更）+`runtime/database_broker.py`（query_id 白名单四层纵深+5 预注册查询）+`character/teaching_service.py`（封闭三值类目+红线扫描不入库+注入面结构隔离+版本回滚） | 新 65 例（kb 14/db 22/teach 29）全绿+合并回归 **143 passed**；ruff 七文件全绿；doc_sync 4 passed；config 三键三处同生（s8 §2/§3） |
| 15 | S9 模型控制 REST 全量+Workspace（S9） | `control_plane/llm_admin.py` LLMControlService（投影/fingerprint/routes preview 消费 R1 管线/config 逐键 CAS 链）+api/llm.py 13 端点+workspace send 确认前诚实 503 not_wired（不烧确认）+envelope meta 增 trace_id | 新 12 passed+控制面存量 **365 passed**；ruff 8 文件全绿；mypy 本域 0 错；两诚实码 not_configured/not_wired 登记（s9 §四/§五） |
| 16 | S10 媒体/文件/搜索协议化（S10） | `runtime/capability_protocols.py`（22 描述符=media 8+files 8+search 4+creation 2+CapabilityInvoker 权限门→限额→超时→降级链→审计+九源逐源诚实状态面）+file_reader 补 `.tex` | 新 **59 passed 1 skipped**（pypdf 缺诚实跳过）+相邻回归 240 passed 2 skipped；ruff 全绿；mypy 0 新增（s10 §四/§五） |
| 17 | S11 日程余量（S11） | `domains/schedule/llm_draft.py`（NL→草稿，缺日期低置信→澄清禁猜）+`timetable.py`（课表截图→结构草稿，缺学期缺节次表拒发布）+`delivery.py`（claim→安静门→风暴门→SendQueue.submit→receipt 诚实落账+not_authorized 干跑）+例外表空模板（unknown 不猜）；config 7 键三处同生 | 新 **54 passed**（21+16+17 全离线）+W10 显式域合跑 574 passed（唯一红=copy_redline_gate，RWC4 当波收口）；doc_sync 19 passed；verify_hashes exit0（s11 §三） |
| 18 | S12 占卜/运势 REST（S12 续跑） | 8 端点（capabilities/config/draws/draws{id}/interpretation/fortune/tarot/bazi）+域 api/{dto,errors,facet}+渲染投影+`_app.py:478-491` 真装配挂接；LLM 解释=503 not_wired 诚实位+话术池 | 新 **27 passed**（含真装配端到端冒烟：未配 db→503 divination_unavailable；配置后真 Bearer 下 tarot/draw 200）+W5 存量 743 passed 1 skipped 逐位吻合+合并 770 passed+控制面族 274 passed（s12 §〇/§二） |

**C. 体验增强与文档族**

| # | 领域 | 产物 | 实跑证据（数字+坐标） |
|---|---|---|---|
| 19 | ACG 时效检索（SEARCH） | `sources/search_intent.py`（6 域词表+5 正则+8 NEVER 红线门）+`sources/acg_search.py`（Bangumi/萌百/B站三竖源+时效加权融合）+chat 链 4 坐标最小接线+「检索截至」诚实句；config 六键默认关 | 新 79 passed+存量回归终态合并 **257 passed**；ruff 全绿；B 站无 cookie/-412 诚实降级（search §二/§三） |
| 20 | R-18 文风多样化+复读三连治理（RP） | persona 源四处改写（变体池 9 条+节奏场景条件+五形态指引，sync --adopt/--check 绿）；chat.py 10 条安抚句池+INTIMATE/normal 文风指令按 route_verdict.mode 二选一互斥注入 | 新 7 passed+回归 13 文件 **190 passed** 0 failed；providers 零改动；FIX2 收口 video 9 红（rp §六/§八） |
| 21 | 命令格式统一规格（CMD，纯文档） | 五件套 `v21r2-command-spec*.md`：四段式语法/14 领域×77 主题归属/九形态规范/81 条条目正文/77 topics+501 别名逐条 echo.py 行号盘点；bz/sm 永不启用等冲突让位表 | grep 实证（cmd-inventory）；发现文档漂移 2 处未动码（echo.py:785「44」实值 46、AGENTS.md「79 topics」实值 77）；落地批待用户评审 §4.1/§5.3（cmd §8） |
| 22 | 合同对齐矩阵+未来预留（PA，纯文档） | reorg-plan 追加三章（523→761 行）：§8 正反向覆盖表（19 域↔65 行双向）+缺口 G1-G12+§9 creation 域 TTS/绘图字段级契约草案（全 reserved）+§10 波次增补 6 项 | 全部断言带矩阵/指南行号坐标；关键文件 ls 实证（COORDINATION 条目+plan §8-§10） |
| 23 | 验收矩阵四列回填草案（MAT，纯文档） | `v21r2-matrix-backfill-draft.md`：65/65 行四列+confidence+证据指针；统计=implemented 14/partial 47/unknown 4；not_wired 17/partial 17；离线行级 passed=0（全部限定面）；**live 0 passed**（blocked 4）；verified 39 | 通读 52 份文档+根目录本文件（draft §〇-§四）；共享矩阵零改动（席位禁令），套用规则见 draft §〇 |

**D. 板块重组族（组织面，零行为改动）**

| # | 领域 | 产物 | 实跑证据（数字+坐标） |
|---|---|---|---|
| 24 | 19 域迁移 18 波收官（RW1a-RW16+RWC1-4+RW14重派/W13b） | link_parse/music/weather/food/divination/meme/finance/notes/files/schedule/media/subscribe/assistant/render/transport/location+chat_reply 四子波+creation 骨架；真身迁移 ≈200 件；旧位全部 PEP 562 活转发/re-export 垫片（同一性 is 断言冒烟）；monkeypatch/文本锚 AST 名字级终验清零；verify_hashes/doc_sync/契约门同波改锚 | 代表面：w1a 698+225、w2 432、w3 259+139、w4 214、w5 743+538、w6 439+413、w7 780+857+契约 171、w8 316+1204、w9 261+75、w10 653+332、w11 275+424、w12 629、w13b 181+867、w14 281+233、wc1 755+289、wc2 739+391、wc3 1241+46+234、wc4 3186+644+215；qx.json e8285e77 多席复验完好；各波日志回归节 |
| 25 | creation 生成域骨架（RWPA1/W-PA1） | `domains/creation/{tts,image,extensions,_common}` 纯新增 8 文件：reserved docstring+TTS/绘图字段级 DTO 契约+注册面三道 dormant 门（禁冒充已生效） | 门禁 **39 passed**+-k creation 45 passed；import 探针零副作用（零 nonebot/线程/socket/open）；ruff 全绿；L51/L52 维持矩阵待终裁（wpa1 §4/§5） |
| 26 | 尾声清账首批（EP1，在飞中首项闭环） | `scripts/extract_trigger_words.py` 旧路径锚复核（判定=必须直读 canonical，垫片对源码文本解析不透明）零改动关账 | 实跑 exit 0（1252 行 JSON：route_rule_count=33/help_topic_count=77 等）+触发族 **1317 passed 2 skipped 1 xfailed**，收集期 StopIteration 消失（ep1 §任务1；S11 移交红点关闭） |

## 四、尚未完善部分（原 A/B/C 清单逐项对账后重写；坐标=MAT 草案行号/席位日志节）

### A. 仍缺（有精确坐标）

1. **生产接线面（17 行 not_wired，最大缺口）**：L39 世界书/L40 知识库/L41 记忆/L42 DB Broker/L43 Teaching/L46 Workspace 真实发送/L47-L50 媒体文件协议面/L51 TTS/L52 绘图/L53-L54 搜索/L56-L58 日程三行——全部新载体零生产接线（`build_*` 服务就绪、无 matcher/装配/控制面调用点）。接线坐标已由各席移交：s8 §6.1、s11 §四.1（三装配助手就位）、s9 §六.1（两端口删 503 短路即可）、s10 §六、s12 §三。**禁把 not_wired 写成 wired**（MAT §〇.5）。
2. **L60 AFFINITY-002 误扣重放/补偿**：整行 unknown，本波无席位认领（MAT L60；前批 §四.C 债转本波，需补偿席+历史证据）。
3. **L71 REPAIR-001 自修复待审补丁**：整行 unknown；S14 仅 PATCH_REQUIRED 分类设计（s14 §一.1）；plan §8.3 G8 建议落 ops/recovery 立项。
4. **L74 ACCEPTANCE-002 admin 取产物**：整行 unknown，无载体无认领（plan §8.3 G3）。
5. **L77 RELEASE-002 授权部署/live 验收**：整行 unknown，等用户授权窗口（plan §8.3 G4）；S15/S16 未开工。
6. **L14 沙箱 AppContainer 终验 1 红（前批遗留原样）**：`test_appcontainer_strong_isolation_or_explicit_block` failed；纯 Python 路线未收口或显式阻断未裁决；`v21-s1-sandbox-log.md` 仍无（MAT L14；本波 woc 仅做 supervisor 域迁移零行为改动）。
7. **L67 LEGACY-001 行级验收未动**：重组只完成组织面（19 域+垫片+AST 终验）；行为对照全表（不能只测天气代表全插件，矩阵 L98）+Plugin manifests+S13 沙箱迁移三件全未做（plan §8.3 G10/G12；MAT L67）。
8. **live_validation 全线空白**：65 行 live 无一 passed（blocked 仅 L32/L46/L51/L52）；等用户提权重启（台账 #10 存量+本批全部 WIP）+真机验收（acceptance-manual §6.6 族）+外部授权一次性汇总（MAT 缺口 1）。
9. **RK4b 风险 4 四项在飞**：_path 装配地雷/config 注入缺口/send_queue RuntimePorts/runtime_attached 冻结——前任静默死亡零落盘，本席从零做，四列全 pending（rk4 log §坐标重定位/§1 待填）。**在飞，终态以其日志为准**。
10. **S14b 自愈三子包在飞**：RecoveryService/IncidentService/NapcatTailCollector 计划已落盘（s14 §二），§五实跑节待填——四列不回填（MAT §〇.8）。**在飞，终态以其日志为准**。
11. **WIREb 人格注入接线在飞**：接线件在盘（persona_injection.py+providers.py 切换点+`bot_persona_versioned_injection` 三处同生，s12 §二 mypy 佐证），但 wire log §3 实跑证据未落盘——只可记 partial，**禁记 wired**（MAT L38/缺口 3）。**在飞，终态以其日志为准**。
12. **RWOCb 尾声波（ops+core 59 件）在飞**：迁移+垫片已落（woc §三/§四），§六回归/§七偏差未补记。**在飞，终态以其日志为准**。
13. **L76 全量门禁未跑**：本波所有席位因禁令+多席在飞均未跑 dev.ps1 四门禁（多席明记「跑之无判定力」）；收口需主会话全量实跑后回填（MAT L76/缺口 6）。

### B. 待用户裁决/外部条件（代码就绪，等裁定或等环境）

1. V2 记忆库前提冲突：独立新库 vs「同源同库」，需 schema 迁移裁决（v2 §5）。
2. W-PA2 tts.py 归属：留 media vs 迁 creation/tts（plan §10，推荐 a 案零改动）。
3. L51/L52 折中值（partial+blocked）vs wpa1 §5 主张（维持 unknown）分歧，主会话终裁（MAT 行内注）。
4. S9 两诚实码 not_configured/not_wired 是否收编 contracts/errors.py 41 注册表（s9 遗留 2）。
5. CMD 命令规格落地批：待评审 §4.1 领域定名+§5.3 建议别名（cmd §8）。
6. RP normal 态 strip_action_brackets 硬保证（涉 bot_persona_action_brackets 默认语义，rp §七）。
7. R6 第三人称自称 vs 人格规范第一人称口径冲突（r6 §七，改回只换池文本+放宽守卫）。
8. R7 实弹探针：`BOT_PROBE_LIVE=1` + `probe_intimate_route.py --live` 由用户扣扳机（r7 §三）。
9. R8 双 bot.py 进程并存（PID 25720/53584）需用户收敛单实例；击杀者排查（火绒信任区+界面日志，r8 §五）。
10. 环境面：BOT_KNOWLEDGE_FILES 指向的用户外部目录缺失（RW5/RW9/RW10/RW11/RW13/RW16 六席 layout FAIL 同款）需归位或改 .env。
11. S12 生产启用键 `bot_control_plane_divination_db` 未配未部署（s12 遗留 2）；S11 例外表空表待管理员按官方公告补录（s11 §四.4）。

### C. 零散技术债与尾声波清账

1. L23 traces Duplicate Operation ID 告警（platform.py vs v1.py，s9 §六.3 建议 V1 席收口）；L28 trace_id 无生产写入方；L49 pypdf 未装（PDF 整类诚实降级）；L55 例外表空；L58 投递重试计数进程内存；L63 TG set_message_reaction 无触发接线（诚实保持）（MAT 缺口 7）。
2. 日程两本地错误码 `plan_limit_exceeded`/`unknown_edge_endpoint` 仍未入全局注册表（s11 §四.5）；billing 席仍无独立完成报告（前批 §四.C 欠账，回归绿佐证 r1 §四；divination/outbound 两份已由 s12/dsp 日志补齐）。
3. 尾声波清账项：多席在飞 `__pycache__` 累积（s12 遗留 1+RWC1 移交 creation 10 处）；W3 weather Q03 文本锚遗留移交尾声波（w6/w12）；subscription_watcher 孤儿模块登记（w12）；command_catalog:201 生成物 header 装饰行（wc4 留尾声波）；FIX2 basetemp 并行父目录竞态教训（后续席勿共用）。
4. R3 遗留：`_pending_rows()` 仍 fetchall ~0.5GB（同步线程内非消息链）；检索热路径 ~976MB 矩阵常驻（r3 §五）。
5. 前批 §四.C 对账结果：smoothstep 档位插值→**已由 R4 完成**（v6 饱和曲线，r4）；channel_health_v2 存量 1 红→**已由 R1 修复①收口**（自适应超时解耦，r1 §二.3）；auto-facts 漂移→**多波 doc_sync --write 已对齐**；父包 `__init__` 装配收敛（import 拉起 nonebot +1074 模块）→**仍未动**。
6. DSP 遗留：能力派发（文本/卡片走 pipeline）接管仍阶段 2+；engine_only 触发点生产侧无调用方；`domains/core/decision/dispatcher.py` 计入 DSP 席改动待 git 认账对账（dsp §四）。

## 五、断点续接指南（下一会话直接照此开工）

1. **先读在飞五席日志尾部定基线**：`v21r2-reorg-woc-log.md`（§六/§七）→ `v21r2-s14-log.md`（§五）→ `v21r2-wire-log.md`（§3）→ `v21r2-rk4-log.md`（§1）→ `v21r2-ep1-log.md`——终态以其日志为准，勿按本页快照重复派工。
2. 再读 `HANDOFF-NEXT.md` 顶部 → 本文件 → `docs/design/v21r2-COORDINATION.md`（52 条席位记账）→ `docs/design/v21r2-matrix-backfill-draft.md`（65 行回填值+§三缺口清单+§〇套用规则）→ `docs/design/v21r2-reorg-plan.md` §8.3（G1-G12）。
3. 收口顺序建议：①等在飞 5 席收官并补记 COORDINATION；②尾声波清账（§四.C.3 清单：pycache 备份后清/Q03 锚/孤儿模块/header 装饰行）；③主会话全量 dev.ps1 四门禁实跑（唯一判定力来源）→ 按 MAT §〇 规则把回填草案套入共享矩阵（含 L7 词表收编 not_wired 裁决、L40「RRF 无」/L48「ASR 无」两处旧括注修正）；④17 行 not_wired 按各席移交坐标开接线席（§四.A.1）；⑤L60/L71/L74 立项裁决 + L14 沙箱收口 + S15/S16 授权窗口向用户一次汇总。
4. 纪律不变：固定解释器直跑（禁 dev.ps1，或先确认 autosync 尊重显式 0——前批已修并有 36 例锁）；子代理按文件域互斥+COORDINATION 认领占域；每阶段落盘；未实跑不称完成；垫片期「新路径 import 须旧路径先行」已随 W1b 收官解除（双向安全，w8）；mypy 必须带 `--explicit-package-bases` 权威口径（w16 教训）。

## 六、纪律声明

- 两波累计 **零 commit/push、零生产重启、零模型真实调用（R7 探针 --live 未扣扳机）、零真实出站、未触碰 ChatBot_Runtime 生产数据与 .env 明文**（R8 取证全部先拷 %TEMP% 读副本）；全部改动在工作树待审，提交裁决权在用户。
- 板块重组 18 波零行为改动：垫片同一性 is 断言冒烟+AST 名字级终验清零+verify_hashes/doc_sync/契约门全绿；重组≠沙箱迁移≠LEGACY-001 验收（plan §8.3 G10 正交性）。
- 自动化实况：前批 15 分钟巡检已按你指令删除；本波无常驻自动化在跑（日志无新增证据）；当前在飞子代理 5 席（RWOCb/S14b/WIREb/RK4b/EP1）。
- 源码树零缓存由各席自查+树卫生门维持；`domains/weather/assets/qx.json`（原 sources/data/qx.json 随包资产）多席 sha256=e8285e77 复验完好；多席在飞 `__pycache__` 残留已登记尾声波清理（§四.C.3）。
- 口径纪律：本页全部数字来自各席日志原文；在飞席位状态不回填、not_wired 不美化、离线限定面 passed 不上移为行级/live passed（MAT §〇.6/7/8 同款口径）。
