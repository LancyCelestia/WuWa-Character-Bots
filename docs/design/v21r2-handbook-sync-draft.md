# v21r2 权威文档链同步增量·草案（DOC2 席，2026-09-18）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。

> **用途**：本波（2026-09-17 晚—09-18，v21r2 系列）向权威文档链（HANDBOOK/docs/README/AGENTS 口径）的同步增量草案，供主会话终局**一次合入**。DOC2 席禁改 HANDBOOK.md / docs/README.md / AGENTS.md 本体，本文件为唯一产出。
> **数据源（全部只读）**：`docs/design/` 全部 v21r2-*.md（60 份，ls 实数）+ 根目录 `V21-UPDATE-LOG.md`（2026-09-18 刷新版）+ `v21r2-agents-ledger-draft.md`（DOC 席台账行草案）+ `v21r2-matrix-backfill-draft.md`（MAT 席 65 行回填草案）+ `docs/HANDBOOK.md` §30/§31 结构（仅取格式）。数字全部来自日志原文，零编造。
> **总口径（合入后必须保持）**：两波（v21 前批+v21r2 本波）零 commit/push、零生产重启、零模型真实调用（R7 探针 --live 未扣扳机）、零真实出站；全部改动在工作树待审，提交裁决权在用户（V21-UPDATE-LOG §六）。在飞席位（RWC5/RET1/RET2/ACC/LEGb）不预填终态；not_wired 不美化；离线限定面 passed 不上移为行级/live passed。
> **序号冲突预警**：HANDBOOK 现存重复 §30（Compact检查点 / 戳一戳 v2 批）与重复 §31（控制面续接 / 内容政策 v2 批）。本草案按任务指定使用 §32/§33 追加；主会话合入时可顺带裁定是否为旧两节去重改号（改号仅需换标题行，正文零影响）。

---

## 一、HANDBOOK 新增 §32 正文草稿（v21r2 生产问题九连修 + LLM 故障转移链 + 亲密路由批）

> 以下整块为 HANDBOOK 追加正文（插于现 §31 内容政策 v2 批之后）。格式对齐 §30/§31 先例：粗体分条 + 坐标 + 状态收尾。

```markdown
## §32 v21r2 生产问题九连修批：吞消息根修 + LLM 故障转移链 + 亲密路由与体验面（2026-09-17 晚—09-18，多席并行，未 commit——工作树多会话共享，提交裁决权在用户）

本批为 v21r2 多席并行的修复族（总账=根目录 V21-UPDATE-LOG.md §3.1.A，席位记账=design/v21r2-COORDINATION.md，逐席日志=design/v21r2-r1~r8 等）。生产四问题（吞消息/慢回复/poke ERROR/安静时间自发言）+ 闪退定性一次收口；全部待提权重启生效（并入台账 #10 窗口）。

**1. 吞消息根因源码级闭合（R3，design/v21r2-r3-stall-log.md §一/§二/§四/§五）**：kb_wiki 同步 job 走 apscheduler AsyncIOExecutor→loop 默认线程池（runtime/pipeline.py:76-83 点名共享池）；23.8 万块/5.67GB 知识库在检索锁内全表 fetchall 同时物化 vector_json+vector_blob→聊天池 8+闸 16 堆满→pipeline_busy SILENT_AUDIT 静默吞消息；零变更夜 ANN 全量重建实测 8.5 分钟占默认池（生产 log 00:20:11 启动→00:28:47 done）。修四处=vector_knowledge.py（_load_vector_cache 流式 fetchmany+blob 优先+_vector_cache_build_lock 单飞+_prewarm_vector_cache 锁外预热挂 retrieve/search_scored 入口+世代号防过期换入）+kb_wiki.py（_SYNC_TASK_MUTEX 互斥 busy 跳过+KbSyncCancelled(BaseException) 协作取消批边界穿透+零变更夜跳过 ANN 重建）。测试 test_v21r2_stall_{timesync_http,watchdog,kbsync}.py 26 例+受影响存量 106=132 passed，ruff 七文件全绿+mypy 本域 0 错。遗留：_pending_rows() 仍 fetchall ~0.5GB（同步线程内非消息链）、检索热路径 ~976MB 矩阵常驻（r3 §五）。

**2. LLM 故障转移链收口（R1 二轮续跑，design/v21r2-r1-llmroute-log.md §二/§三/§四/§六）**：model_router 严格优先级（bot_chat_strict_priority 缺省开）/90s 冷却降级 SQLite 落盘/3s 链止损/INTIMATE grok 钉一+回落日志/告警 kind 折叠+chain 压缩；**BOT_MODEL_PRIORITY_GROUPS 恒 no-op 根修**（分组 order 只存 id 被当模型名发注定失败→_auto_route_ids 扩收模型名/别名按注册表序展开，4 例回归锁）；自适应超时与 latency_first 解耦（防改缺省连带关闭快失败）。实跑本文件 23 passed+回归 16 文件 253 passed 1 failed（唯一红=R2 WIP，已由 FIX 收口）+FIX2 补收价格聚合旧语义断言 15 passed。治 §30.1 所记「17 连跳烧到 umi-claude」类慢回复的链路面。

**3. poke 摄取 ERROR（R5 第 4 次派遣 A 项，design/v21r2-r5-hotzone-log.md）**：根因=notice 族 matcher→IngressGateway.from_event→get_plaintext() 对 OB11 NoticeEvent（无 message 字段）抛 ValueError("Event has no message!")；摄取守卫已在 09-16 批工作树 WIP（不重复改动），本席全链路审计 notice 族 7 个 handler 零 get_plaintext 直调+AST 棘轮钉死+假 PokeNoticeEvent 过真实 RuntimePipeline 产出戳一戳回复回归锁（test_v21r2_hotzone_notice_chain.py 3 例）。

**4. 安静时间自发言（R5 B 项，design/v21r2-r5-hotzone-log.md；test_v21r2_hotzone_quiet_silence.py 4 例注入时钟）**：根因=runtime/pipeline.py 旧版 BLOCKED 回执带 public_message="当前处于安静时间，已暂停非必要回复。"且被投递（HEAD 与 docs/ai-kb-operations-manual.md 旧口径，git log -S 证实）；工作树 WIP 已置空，本席锁死「非交互 BLOCKED 双路（handle/handle_async）零入队+@/指令直通」回归门。**待重启生效**。

**5. 适配器韧性族（R2 续跑，design/v21r2-r2-lifecycle-log.md §一/§三/§四；FIX 收口见 §六）**：TG 降噪+401/403/409 定向分类停轮询/retcode=1200 三失败形态改 bot_unavailable 挂起（FAILED_RETRYABLE+90s 重探不烧预算，不再终态丢消息）/mail 15s 硬超时+2s 退避/Ctrl+C _reap_background_threads 10s 宽限/misfire_grace_time=30/早停钩子。实跑 R2 21 passed+域内 111 passed 3 xfailed+核心合跑 66 passed；FIX 席收口 worker bot_unavailable 静默化孤儿红（worker.py 零改动仅同步测试期望）40+71 passed。

**6. 好感度 v6 平滑层（R4，design/v21r2-r4-affinity-log.md）**：smoothstep 饱和响应曲线（带宽=1 档宽 25 分，中段六档与 v5 字节级一致/极端档单调收窄/边界归零）+同日同类信号 0.6^n 边际递减（下限 0.2 跨日重置）+日节奏帽（复用 V2.1 滚动预算正负分账）；override/poke 权威通道不饱和不递减；算法卡保持全定性。tests/test_affinity_v6_smoothing.py 24 例+全 affinity 族+poke+消费方 151 passed；docs/affinity-design.md 追加 v6 附录；无新增 config 键。

**7. 授时兜底（R3，design/v21r2-r3-stall-log.md §二.4）**：timesync.py HTTPS Date 头兜底链（NTP 全败→https HEAD 取 RFC7231 Date θ=server+0.5−(t0+t3)/2 量化居中、仅收 https、复用 ±1.5s 钳制/RTT 上限、失败链每级一行日志）；bot_time_sync_http_enabled/url 两键三处同生，字段缺失=不启用保离线测试零网络（测试含第 1 条 26 例）。

**8. 闪退定性+兜底（R8，design/v21r2-r8-crash-log.md §二/§三/§五/§六）**：2026-09-17 23:24 闪退定性=外部 TerminateProcess(0xFFFFFFFF) 击杀非代码崩溃（事件日志/WER/faulthandler.log/crash.log 四面全空+exit -1 签名+回执库钉死死亡于 23:24:32.603 发送回执落盘后静默期）；击杀者 unknown（火绒 HIPS/代理 shell kill 候选，已排除 Defender/计划任务/火绒隔离/代码内退出）。兜底加固 scripts/crash_trap.py（存活心跳+退出标记+faulthandler 兜底）7 passed；装配坐标=bot.py:260 _install_crash_guards 之后 install_crash_trap(...)（已由 INT/R2b 落地）。附带发现双 bot.py 进程并存（PID 25720/53584）移交用户收敛。

**9. 文案池化（R6+R5 C②，design/v21r2-r6-copy-log.md）**：daily_assist 全部用户可见文案 11 池×每池 ≥6 变体+pick_variant 确定性轮换（与五池同构）+语气守卫常驻 tests/test_daily_assist.py 21 passed；两餐开场 _MEAL_OPENERS 6 变体池（__init__.py:3026-3032，R6 草案逐字落地）由 R5 代落+4 例 test_v21r2_hotzone_meal_variants.py。遗留：R6 第三人称自称 vs 人格第一人称口径冲突待用户裁决（r6 §七）。

**10. 亲密路由批复核与文风面（R7/RP，design/v21r2-r7-contentroute-log.md + design/v21r2-rp-style-log.md）**：R7 content_route 检测链端到端复核零缺陷零改动+explicit_allowed_for_session 补 6 例零覆盖+离线探针 scripts/probe_intimate_route.py（--live 需 BOT_PROBE_LIVE=1 用户扣扳机）14 例（三文件 44 passed）；RP 复读三连根因=chat.py 两处静态示例+表达规范.md MaiBot 旧节/固定模板+「2-4 句」无条件——persona 源四处改写（变体池 9 条+节奏场景条件+五形态指引，sync --adopt 绿，副本 sha=d13a7ada… 零变更）+chat.py 10 条安抚句池+INTIMATE/normal 文风指令按 route_verdict.mode 二选一互斥注入（新 7 passed+回归 13 文件 190 passed）。

**11. 附带收口**：INT 席两挂接（loop_watchdog 挂 @driver.on_startup __init__.py:3364-3384+kb 停机取消 bot.py:389-407）84 passed（r3 §六）；SEARCH 席 ACG 时效检索三竖源（Bangumi/萌百/B站+检索截至诚实句+config 六键默认关）79 passed+存量 257 passed（design/v21r2-search-log.md §二/§三）；FIX/FIX2 三笔孤儿红逐一取证收口、涉事源码零改动（r2 §六/search §五/rp §八/r1 §六 各收口记录）。

**证据与状态**：R5 合计 166 passed（新增 11+域内 155）；本批全部离线实跑、ruff/mypy 本域零错（各席日志 §实跑节）；全部改动待提权重启生效；未 commit（共享工作树）。台账行=AGENTS.md #37（DOC 席草案）。
```

---

## 二、HANDBOOK 新增 §33 正文草稿（V2.1 合同 S7-S16 交付批 + 板块重组 19 域 + creation 预留）

> 以下整块为 HANDBOOK 追加正文（紧随 §32）。四列口径=implementation/production_wiring/offline_validation/live_validation；**65 行回填权威=design/v21r2-matrix-backfill-draft.md**（本节不重复逐行，只记批级事实）。

```markdown
## §33 V2.1 合同交付批（S7-S16）+ 板块重组 19 域 + creation 预留（2026-09-18，多席并行，未 commit——提交裁决权在用户）

**A. 合同服务交付（S/V 系；逐席日志=design/v21r2-{s8,s9,s10,s11,s12,s14,v1,v2,wire}-*.md）**

- **S7 人格/世界书版本管理（V1+WIRE 重跑席）**：character/persona_service.py（draft→publish→activate→rollback 全链+CAS BEGIN IMMEDIATE 原子比对+SQL 触发器锁死正式版本不可变+quarantine 损坏隔离留证+权限门+build_core_injection 唯一出口，personas/ 零接触）+worldbook_service.py（悬空/循环引用 DFS+Token 预算 CJK≈1 字+untrusted 出站标注）；两新库 persona_versions/worldbook_versions.sqlite3 入 db-owners。19 passed+风险红 4 文件 74 passed 5 xfailed+控制面存量 234 passed（v1 §3.1）。接线已由 WIRE 重跑席收口：persona_injection.py+providers.py 切换点+config 键 bot_persona_versioned_injection=False 三处同生，14 passed+引用面 315+chat 域扫 182+邻接 52 passed（wire §3.3/§4）——默认 False 灰度、未部署。
- **S8 知识库/DB Broker/Teaching（S8 席）+记忆服务补全（V2 席）**：knowledge_service.py（跨库 RRF 分数来源透出+SQLite backup API 原子重建[Windows os.replace 实证不可行后的设计修正]+embedding 版本变更）+runtime/database_broker.py（query_id 白名单+模板静态校验+命名参数+mode=ro+2s 超时+200 行限额，5 预注册查询）+teaching_service.py（封闭三值类目+红线扫描不入库+注入面结构隔离+版本回滚）；65 例（kb 14/db 22/teach 29）+合并回归 143 passed；config 三键三处同生。V2 记忆：修 4 真 bug（幂等 UNIQUE 索引/touch_used 缓存失效/初始版本虚高/归因候选面不含墓碑）+补 5 缺失，修前 12 failed/25 passed→修后 41 passed+存量 33 passed；**前提冲突待用户裁决：独立新库 vs「同源同库」（v2 §5）**。两席 production_wiring 均 not_wired（build_* 就绪零接线）。
- **S9 模型控制 REST（S9 席）**：control_plane/llm_admin.py LLMControlService（只读投影+credentials fingerprint+routes/preview 消费 R1 管线+config 逐键 CAS 链）+api/llm.py 13 端点+workspace send 确认前诚实 503 not_wired（不烧确认）+envelope meta 增 trace_id；12 passed+控制面存量 365 passed；s9 §三自认 L44 保持 partial 勿升。
- **S10 媒体/文件/搜索协议化（S10 席）**：runtime/capability_protocols.py 22 描述符（media 8+files 8+search 4+creation 2+CapabilityInvoker 权限门→限额→超时→降级→审计+九源逐源诚实状态面）+file_reader 补 .tex；59 passed 1 skipped+相邻 240 passed。矩阵 L48「ASR 无」旧括注已过时（transcribe.py/build_asr_provider 已在盘）。
- **S11 全场景日程提醒（S11 席）**：llm_draft.py（NL→草稿缺日期低置信→澄清禁猜）+timetable.py（课表截图→结构草稿缺学期缺节次表拒发布）+delivery.py（claim→安静门→风暴门→SendQueue.submit→receipt 诚实落账+not_authorized 干跑）+例外表空模板 unknown 不猜；config 7 键三处同生；54 passed（21+16+17）+W10 显式域合跑 574 passed；wiring 全 not_wired（三装配助手就位留接线席，s11 §四.1）。
- **S12 占卜/运势 REST（S12 续跑席）**：8 端点+域 api/{dto,errors,facet}+渲染投影+_app.py:478-491 真装配挂接；27 passed（含真装配端到端冒烟：未配 db→503 divination_unavailable/配置后真 Bearer tarot/draw 200）+W5 存量 743 passed 1 skipped 逐位吻合+合并 770+控制面族 274；生产启用键 bot_control_plane_divination_db 未配未部署。
- **S14 自愈三件（S14b 落盘+S14c 断点续收实跑）**：domains/ops/recovery（FailureKind 6 可恢复+4 不可重试含 PATCH_REQUIRED/每资源 10min≤3 次/full-jitter 1s~30s/稳定窗 60s/风暴熔断）+incident（结构化事件+脱敏懒加载复用 render 真身单一事实源+聚合+防递归）+collectors/napcat_tail.py（tail 轮转/半行缓冲/二进制偏移/背压丢弃/4MiB 跳跃追赶，pull 式零线程）；59 passed（recovery 20+incident 21+napcat_tail 18，s14 §五）；wiring not_wired（坐标 s14 §三留接线席）。
- **风险 4 收口（RK4 重跑席）**：A 项 _path 装配地雷取证已被并行批修复（误报结案零改动）/B config+log_level 注入缺口修复/C 工厂增 send_queue 形参+生产 :3451 实例装配/D napcat.status 改 runtime_state_probe 实时三态探针；10 passed 1 xfailed+控制面族 15 文件 197 passed；取证新增 actions.py:238 _safe_details 消毒丢动作明细 xfail(strict) 台账钉死待立项（design/v21r2-rk4-log.md §四列/§实跑）。
- **Dispatcher/风险 5 转正（DSP 续跑席）**：control_plane/dispatcher.py OutboundSideEffectExecutor（取消闸→准入复验→PermitLease 线性化→mark_irreversible→TransportRegistry→call_api 同通道本体绝非第二出站通道）+decision dispatch 阶段 1 真实派发周期（shadow 绝不发送语义保持）+poke 回戳/贴表情两组生产直连点收编门面+3 条 strict xfail 摘标转回归锁；152 passed+全仓扫掠 221+复核 47；能力派发接管仍阶段 2+（design/v21r2-dispatch-log.md §四.2）。
- **沙箱终验（SBX 席）**：唯一红点 test_appcontainer_strong_isolation_or_explicit_block 根因两处测试布线缺陷（AC 探针管道背压死锁/禁网 accept 布线被控制组消费）非隔离能力缺陷，loopback 独立取证实证零 capability 容器确实被拒；11 passed+相邻 40 passed（**design/v21-s1-sandbox-log.md 为最终态，推翻 V21-UPDATE-LOG §四.A.6「1 红未收口」旧口径**）；production_wiring not done（spawn_isolated_worker/WindowsSandbox 生产消费方为零，插件仍进程内运行）。
- **误扣重放/补偿 L60（AFF 席）**：affinity_replay.py 重放引擎（政策差额层+账本重放层 mode=ro+补偿提案层指纹幂等）+scripts/affinity_replay_report.py（**无 --apply**，补偿只出提案绝不自动落库）；20 passed+存量 130 passed；生产库只读实跑×4 前后 SHA-256=89f0c7b9… 不变；结论=当前账本 27 行零已证误扣→零提案零恢复；一晚 40+ 分事故逐事件证据物理缺失，聚合指针 sender 3865067623 insult_count=10/现 -31.6 分供管理员人工核查（**design/v21r2-aff-replay-log.md 为最终态，推翻 V21-UPDATE-LOG §四.A.2「无席位认领」旧口径**）。
- **REPAIR-001 自修复（REP 席）**：domains/ops/repair/{__init__,service}.py：两轮预算（DEFAULT_MAX_ROUNDS=2）待审补丁编排/unified diff 落 pending/SandboxCopyVerifier 整树拷贝+子进程真 pytest 仓库零触碰/apply_to_target 与 deploy_patch 越权一律 raise；13 passed（2.06s）+邻接 S14 合跑 56 passed；wiring not_wired（design/v21r2-repair-log.md §4）。
- **验收 Runner V21-ACCEPTANCE-001（ACC 席）——在飞，终态以其日志为准**（占域 domains/ops/acceptance/ 骨架+13 条 AC 计划已落盘 design/v21r2-acceptance-log.md，执行记录待填，不预填）。

**B. 板块重组批（组织面零行为改动；施工图=design/v21r2-reorg-plan.md[RO §0-§7+PA §8-§10 合同对齐/未来预留/波次增补三章；PA 席记 523→761 行，DOC2 席合入前实测 759 行，2 行差为在飞期并行触碰零内容影响]；逐波日志=design/v21r2-reorg-w*.md）**

- **域与波次**：link_parse/music/weather/food/divination/meme/finance/notes/files/schedule/media/subscribe/assistant/render/transport/location+chat_reply（四子波 RWC1-4：character 23 件/llm_engine 11 件/capabilities 本体 chat 155KB+echo 278KB 等 7 件/runtime 核心 18+ingest/pipeline 2）+ops+core 尾声波（RWOC 59 件）+creation 生成域骨架（见 D）≈200+ 件真身迁移；垫片同一性 is 断言冒烟+monkeypatch/文本锚 AST 名字级终验清零+verify_hashes/doc_sync/契约门/log_collectors._SUBSYSTEMS 同波改锚。代表回归实跑：w1a 698+225、w2 432、w3 259+139、w4 214、w5 743+538、w6 439+413、w7 780+857+契约 171、w8 316+1204、w9 261+75、w10 653+332、w11 275+424、w12 629、w13b 181+867、w14 281+233、wc1 755+289、wc2 739+391、wc3 1241+46+234、wc4 3186+644+215、woc 292+348+229、wpa1 39+45（各波日志回归节）。qx.json 唯一真身 domains/weather/assets/ sha256=e8285e77 多席复验完好（旧径 sources/data/ 已随 W3 整体消失）。
- **垫片技术**：PEP 562 活转发垫片（__getattr__ 实时解析 canonical，治「调用期旧路 import×测试 canonical 补丁」时序分裂，W11 首创后成波标准）+包垫片+re-export 显式私名转出（AST 名字级全量扫描；人工核对漏检被域测试红抓出的教训入 w6 §六）。方法论四条入各波日志：AST 清单机读直驱禁人工转录（w14）/垫片私有名必须名字级全量扫描（w6）/「read_text+旧路径」文本锚是系统性盲区逐域清点（w6/w12）/mypy 必须带 --explicit-package-bases 权威口径（w16）。
- **EP 尾声清账（EP1 席）**：extract_trigger_words 旧路锚关账（判定=垫片对源码文本 AST 提取不透明必须直读 canonical，实跑 exit 0 出 1252 行 JSON：33 rules/77 topics/412 verified）+触发族 1317 passed 2 skipped 1 xfailed 收集零错；树卫生清扫 7 缓存目录备份 %TEMP%/v21r2-ep1-hygiene-backup-20260918-053848 后全清（design/v21r2-ep1-log.md）。
- **RET 垫片退役梯队**：design/v21r2-shim-retirement-inventory.md 全仓 AST 机核 1155 py 零人工转录：275 张垫片/1591 消费边（形态=静态 139/PEP562 活转发 131/包 5；判定梯队=可直接退役 41/仅测试消费方 44/需先改写 135/在飞 RWOC 55），波次归因 275/275 与各波声明张数逐一吻合；**RET1/RET2 退役执行波在飞，终态以其日志为准**。

**C. 文档三件套（CMD/MAT/LEG，纯文档零代码）**

- **CMD 命令格式统一规格**：五件套 design/v21r2-command-spec.md（四段式语法/14 领域×77 主题归属总表/九形态规范/落地路径 §8）+-inventory.md（77 topics/501 别名逐条 echo.py 行号坐标）+-entries-1/2/3.md（81 条条目正文覆盖 77 主题）；冲突让位表（bz/sm 永不启用、dl/hl/jx/zt/huifu/wj 跨域撞车）；发现文档漂移 2 处未动码：echo.py:785「二次元问句(44)」实值 46、AGENTS.md「79 topics」实值 77；**待用户评审 §4.1 领域定名+§5.3 建议别名后才进 §8 落地批**。
- **MAT 验收矩阵四列回填草案**：design/v21r2-matrix-backfill-draft.md：65/65 行四列+confidence+证据指针；统计=implemented 14/partial 47/unknown 4；production_wiring wired 0/partial 17/not_wired 17/unknown 31；offline passed 全部限定面（行级 passed=0）；live 0 passed（blocked 4）；confidence verified 39；共享矩阵 backend-v2-acceptance-matrix.md 本批零改动，套用规则见草案 §〇（L7 词表收编 not_wired 裁决、L40「RRF 无」/L48「ASR 无」两处旧括注修正、L51/L52 折中值 vs wpa1 异议待主会话终裁）。
- **LEG 行为对照表——LEGb 席在飞**：草案 v21r2-legacy-manifest-draft.md 已落盘（19 域存量业务清单+对照表框架+Plugin manifests 骨架+缺口清单，四件产出；real 值未填齐、零测试套件实跑）；行为对照全表属 LEGACY-001 行级验收件，**终态以其日志/草案更新为准，不预填**。

**D. creation 生成域预留（W-PA1 波，纯新增零改动既有文件）**：domains/creation/{tts,image,extensions,_common} 8 文件 reserved docstring+TTS/绘图字段级 DTO 契约草案（任务状态机/取消/多单位计费/资产/出站标签/安全检查逐字段；UsageLine 不变量 Decimal 禁浮点）+注册面三道 dormant 门（未注册→Unregistered/step<4→GateClosed/无工厂→NotImplemented，禁冒充已生效）；门禁 tests/test_v21_creation_skeleton.py 39 passed+-k creation 45 passed+import 探针零副作用；L51/L52 四列维持矩阵待终裁（design/v21r2-reorg-wpa1-log.md §4/§5）。

**E. 门禁与收口状态**：S15 GATE 全量门禁预检报告（design/v21r2-s15-pregate-report.md，只读快照）——绿 3（verify_hashes PASS/command_catalog PASS 77 topics/插件导入冒烟 1.218s）+环境项 1（BOT_KNOWLEDGE_FILES 用户外部目录缺失，RW5-RW16 七席同款）；红 4 全部根因收敛在飞 WIP（doc_sync 2 行漂移/ruff 36 错 100% 在飞域文件/mypy 被 S14b 在飞 SyntaxError 阻断后经 S14c 核验已自愈/collect 8002+2 errors 同根因）；**全量 pytest 留 S16 收口席统跑（尚未派遣），在飞期间任何红绿数字不可用于收口判定**。

**遗留（四列口径集中列）**：production_wiring not_wired 17 行=L39-L43/L46-L50/L51/L52/L53/L54/L56-L58（接线坐标各席已移交：s8 §6.1/s11 §四.1/s9 §六.1/s10 §六/s12 §三）；live_validation 全线 0 passed（blocked 仅 L32/L46/L51/L52），等提权重启+真机验收+外部授权；L74 ACCEPTANCE-002/L77 RELEASE-002 整行 unknown 无载体（plan §8.3 G3/G4）；LEGACY-001 行级验收未动（行为对照全表+Plugin manifests+S13 沙箱迁移三件全未做，plan §8.3 G10/G12 正交声明：重组≠沙箱迁移≠LEGACY 验收）；根 __init__ 装配收敛（import 拉起 nonebot +1074 模块）仍未动。台账行=AGENTS.md #38/#39/#40（DOC 席草案）。
```

---

## 三、docs/README.md 索引增量草案（v21r2 文件群分类索引段落）

> 合入位置：`docs/README.md`「交接与总账」表之后新增一节（或在「架构规格（design/…）」节前），标题与正文如下。文件数以合入当日 `ls docs/design/v21r2-*.md | wc -l` 实数复核为准（本草案落盘时 60 份，含本草案为 61 份；在飞席位可能续增）。

```markdown
## v21r2 文件群（2026-09-17 晚—09-18 多席批，design/ 下 60 份）

> 两波（v21 前批+v21r2）总账在根目录 [V21-UPDATE-LOG.md](../V21-UPDATE-LOG.md)（§三已完成/§四未完善/§五断点续接）；全部未 commit，在飞席位终态以其日志为准。

**交接与协调**
- [design/v21r2-COORDINATION.md](design/v21r2-COORDINATION.md) — 席位记账（认领+完成双记，57 条）；接手先读
- [design/v21r2-agents-ledger-draft.md](design/v21r2-agents-ledger-draft.md) — AGENTS.md 第六部分台账行 #37-#40 草案+合入操作手册
- [design/v21r2-handbook-sync-draft.md](design/v21r2-handbook-sync-draft.md) — HANDBOOK §32/§33 与口径修正同步草案（DOC2 席，合入后本行可删）

**规格与方案**
- [design/v21r2-reorg-plan.md](design/v21r2-reorg-plan.md) — 板块重组施工图（§0-§7 域结构/波模板/门禁网 + §8 合同对齐矩阵 + §9 未来预留[creation 域] + §10 波次增补）
- [design/v21r2-command-spec.md](design/v21r2-command-spec.md) + -inventory/-entries-1/2/3 — 命令格式统一规格五件套（77 topics/501 别名/81 条条目；**落地批待用户评审**）
- [design/v21r2-shim-retirement-inventory.md](design/v21r2-shim-retirement-inventory.md) — 垫片退役清单（275 张/1591 消费边 AST 机核+判定梯队+施工纪律）
- [design/v21r2-s15-pregate-report.md](design/v21r2-s15-pregate-report.md) — S15 全量门禁预检报告（只读快照，全量 pytest 留 S16）
- [design/v21r2-aff-replay-report.md](design/v21r2-aff-replay-report.md) — 好感度误扣重放报告（零已证误扣结论）

**席位日志（47 份）**
- 修复族：v21r2-r1-llmroute / r2-lifecycle / r3-stall / r4-affinity / r5-hotzone / r6-copy / r7-contentroute / r8-crash（各 -log.md）
- 服务族：v21r2-v1-persona / v2-memory / s8-kb-db-teach / s9 / s10 / s11 / s12 / s14（各 -log.md）
- 收口与专项：v21r2-dispatch / search / rp-style / wire / rk4 / repair / ep1 / acceptance / aff-replay（各 -log.md；acceptance 在飞）
- 重组波：v21r2-reorg-w1a~w16、w13b、wc1-4、woc、wpa1（各 -log.md）

**清单与回填草案**
- [design/v21r2-matrix-backfill-draft.md](design/v21r2-matrix-backfill-draft.md) — 验收矩阵 65 行四列回填草案+套用规则（§〇）+缺口清单（§三）；主会话套入共享矩阵的唯一依据
- [design/v21r2-legacy-manifest-draft.md](design/v21r2-legacy-manifest-draft.md) — LEGACY-001 存量业务行为对照全表草案（LEGb 席在飞，real 值未填齐）
```

---

## 四、四处口径修正清单（合入时同步执行；源=v21r2-agents-ledger-draft.md §二.3 搬运+补全）

| # | 位置 | 修正内容 | 依据坐标 |
|---|---|---|---|
| 1 | **AGENTS.md 第六部分工作区规则第 6 条**（铁律） | qx.json 豁免路径改口径：`plugins/bot_unified_runtime/sources/data/qx.json` → **`plugins/bot_unified_runtime/domains/weather/assets/qx.json`**；保留「2026-09-13 曾被误清致 NMC 路径整体塌向 open-meteo」教训原文，补一句「旧径 sources/data/ 已随 2026-09-18 板块重组 W3 整体消失，清理波按新径豁免」 | EP1 席登记（v21r2-ep1-log.md）；W3 迁移 sha256=e8285e77 多席复验（v21r2-reorg-w3-log.md；w10/w11/w13/w14/wc2 等波日志复验记录） |
| 2 | **AGENTS.md 第四部分「/bot help」口径** | 「79 topics」→ **77 topics**（只改现行口径处；台账 #34 内「72→79」为历史记录不改）。同段「topic 数以 command_catalog.py --write 生成物为准」表述保留。附带登记（不动码）：echo.py:785「二次元问句(44)」实值 46，待 CMD 落地批顺带修 | CMD 席 grep+`command_catalog --check` 双实证（v21r2-command-spec.md §295 漂移登记、-inventory.md §A；COORDINATION CMD 条） |
| 3 | **AGENTS.md 第七部分权威链 + 顶部横幅 + HANDOFF-NEXT.md + 台账 #10** | ①第七部分补一行：V2.1 两波（v21 前批+v21r2）总账=根目录 `V21-UPDATE-LOG.md`；席位记账=`docs/design/v21r2-COORDINATION.md`（57 条）；验收四列权威=`docs/design/v21r2-matrix-backfill-draft.md`；重组施工图=`docs/design/v21r2-reorg-plan.md`；垫片退役=`docs/design/v21r2-shim-retirement-inventory.md`。②顶部横幅「当前交接入口」日期更新为 2026-09-18，续接入口指向 V21-UPDATE-LOG §五断点续接指南（先读在飞席位日志尾部）+COORDINATION。③HANDOFF-NEXT.md 顶部续接指针更新：在飞五席收官→尾声波清账（V21-UPDATE-LOG §四.C.3）→主会话 dev.ps1 四门禁全量实跑→17 行 not_wired 接线席→L74/L77 立项+沙箱 wiring 立项+授权窗口向用户一次汇总。④台账 #10 状态列补「+2026-09-17 晚—09-18 v21r2 全批 WIP（#37-#40）同窗口待生效」 | v21r2-agents-ledger-draft.md §二.3 同款条目；V21-UPDATE-LOG §五 |
| 4 | **旧口径推翻声明（两处，合入 §32/§33 时以括注形式存在，此处集中登记）** | ①沙箱：V21-UPDATE-LOG §四.A.6「1 红未收口」为旧口径，最终态=design/v21-s1-sandbox-log.md（红点已收口 11 passed，根因=测试布线缺陷非隔离缺陷）；两文档并存以日志为准。②误扣重放：V21-UPDATE-LOG §四.A.2「无席位认领」为旧口径，最终态=design/v21r2-aff-replay-log.md（已闭环零提案零恢复） | v21-s1-sandbox-log.md §修复后单测；v21r2-aff-replay-log.md（agents-ledger-draft §五.3/§五.4 同款纪律） |

> 补充（非独立修正项，随 #3 顺带）：`docs/README.md` 的 HANDBOOK 行「**§31 最新：控制面续接**」随本草案 §三 合入时改为「§32/§33 最新：v21r2 九连修+合同交付+板块重组」。`docs/design/COMPACT-CHECKPOINT.md`、`docs/codebase-slim-plan.md`、`docs/design/v21-autosync-fix-log.md` 中的 `sources/data/qx.json` 出现为历史证据件，**不改原文**；如需可各加一行「路径已迁 domains/weather/assets/」指针注（可选，主会话裁定）。

---

## 五、「待在飞席位终态回填」占位清单（五处；在飞不预填，收官后按本表落点补记）

| # | 席位 | 当前在飞内容 | §32/§33 占位落点 | 回填条件与现状证据 |
|---|---|---|---|---|
| 1 | **RWC5** | 根 `__init__` 惰性导入切换子波（chat_reply 第 5 子波）——垫片退役硬前置（EP1 机核 108 张垫片被根 `__init__` 消费） | §33 B「域与波次」末尾补一句 RWC5 回归数字+收官日期；§33 B「RET 梯队」的「108 张硬前置」改为已解除 | 无日志落盘（docs/design/ 无 v21r2-reorg-wc5-*.md）；等其日志+COORDINATION 补记后回填 |
| 2 | **RET1** | 垫片退役执行波第 1 批（按 shim-retirement-inventory 梯队施工） | §33 B「RET 垫片退役梯队」句尾：补「RET1 已退役 N 张（判定梯队 X），余量 M」 | 无日志落盘；等其日志实跑数字（collect 0 错+受影响域回归）回填 |
| 3 | **RET2** | 垫片退役执行波第 2 批 | 同上，与 RET1 同一落点续记 | 无日志落盘；同上 |
| 4 | **ACC** | 验收 Runner V21-ACCEPTANCE-001（domains/ops/acceptance/ 骨架+13 条 AC 计划已落盘） | §33 A 末条已写「在飞，终态以其日志为准」；收官后改为四列终值+实跑数字 | 日志已存在：design/v21r2-acceptance-log.md（112 行，§0 占域/§2 AC 表）；执行记录节待填——以日志更新为准 |
| 5 | **LEGb** | LEGACY-001 存量业务行为对照全表（19 域清单+对照框架+manifests 骨架草案已落盘） | §33 C「LEG 行为对照表」句：收官后把「草案/real 值未填齐」改为终态（覆盖 77 topics 分配封账+行为对照结论）；LEGACY-001 行级验收判定仍归主会话/MAT | 草案已存在：design/v21r2-legacy-manifest-draft.md（387 行，§〇 口径/§四 77/77 封账框架）；零测试实跑、real 值未填——不预填 |

> 合入纪律：上表五处在 §32/§33 正文中的既有措辞（「在飞，终态以其日志为准」）合入时原样保留；仅当对应席位收官并补记 COORDINATION 后，才按其日志替换占位句。在飞期间**禁止**按计划文本预填任何数字或状态（MAT §〇.8 同款口径）。

---

## 六、合入顺序与自查清单（主会话操作，DOC2 席不执行）

1. **顺序**：①在飞五席收官（或明确等回填）→②HANDBOOK 追加 §32/§33（本文档 §一/§二 整块抄入，序号按「序号冲突预警」裁定）→③docs/README.md 加 §三 索引节+改 HANDBOOK 行「最新」指针→④执行 §四 四处口径修正→⑤§五 占位句保留待回填。
2. **自查**（合入后逐条过）：全部新正文保持「未 commit（共享工作树）」表述，零「已生效/已部署」措辞（生产未重启）；not_wired 不美化、离线限定面 passed 不上移为行级/live passed；每个数字可回溯到席位日志坐标；在飞五席无预填；S16 未跑全量——任何红绿数字不得写作收口判定；沙箱/误扣重放两处旧口径推翻声明已在 §33 括注（§四.4 集中登记）。
3. **禁止事项提醒**：本草案为纯文档增量的暂存件；合入动作（改 HANDBOOK/README/AGENTS/HANDOFF-NEXT）属主会话职权；全部合入不产生 git 写操作（提交裁决权在用户）。
