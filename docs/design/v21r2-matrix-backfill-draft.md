# v21r2 验收矩阵四列回填·草案（MAT 席，2026-09-18）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。

> 性质：**回填草案**，供主会话 S15/16 收口时一次性套用。共享矩阵 `backend-v2-acceptance-matrix.md` 本批零改动（席位禁令）。
> 数据源：`docs/design/` 全部 v21r2 席位日志（约 30 份）+ 根目录 `V21-UPDATE-LOG.md` + `v21r2-COORDINATION.md`，全部只读通读。无证据处如实记 unknown/维持现值，禁美化。
> 窗口：本草案只覆盖 **v21r2 本会话增量**（2026-09-17 晚—09-18）；前批（V21-UPDATE-LOG，2026-09-17 凌晨—上午）成果已体现在矩阵现值 partial 括注内，本草案不重复记账、只在其上叠加。

## 〇、套用说明（主会话合入共享矩阵的操作规则）

1. **引用缩写**（证据指针列）：`s8`=v21r2-s8-kb-db-teach-log、`s9`=…-s9-log、`s10`、`s11`、`s12`、`s14`、`v1`=…-v1-persona-log、`v2`=…-v2-memory-log、`r1`…`r8`（r8=crash-log）、`dsp`=dispatch-log、`search`、`wire`、`rp`=rp-style-log、`int`=r3 §六（INT 席无独立日志，记于 r3-stall-log §六）、`fix`=r2 §六、`fix2`=search §五/rp §八/r1 §六、`cmd`=command-spec.md、`wpa1`、`woc`、`w1a`…`w16`/`wc1`…`wc4`/`w13b`=reorg 各波日志、`plan §8`=v21r2-reorg-plan.md §8.2 反向覆盖表、`COORD`=v21r2-COORDINATION.md、`UPDATE`=根目录 V21-UPDATE-LOG.md。`§n` 指该日志节号，行号指矩阵行号（L13–L77）。
2. **可直接覆盖的行**（席位自记四列 + 日志含实跑命令与输出）：L38–L43、L45–L59、L62–L66、L69、L34–L36（增量面）。主会话按本草案四列值+括注逐行抄入即可，confidence 按第 4 条规则取。
3. **需人工复核后再定值的行**：L21/L23/L27/L28（消费方/端点增量，行级验收未全）；L51/L52（s10 提 partial 与 wpa1 §5 主张维持 unknown 有分歧，本草案折中值见行内注）；L44（s9 §三明确建议保持 partial，勿升 implemented）；L67/L75/L76（组织面/文档面/门禁面增量不构成行级验收）。
4. **confidence 取值规则**：`verified`=该日志含真实命令+输出直接支撑该值；`high`=源码/跨席回归佐证但无该值直接命令输出；`low`=间接推断；`unknown`=本会话零证据（四列维持矩阵现值，草案不改动）。矩阵 L7「源码推断最多 high」继续有效。
5. **`not_wired` 词汇处置**：矩阵 L7 词表 production_wiring=unknown/partial/wired，本会话各席普遍自报 `not_wired`。主会话二选一：①矩阵 L7 扩词表收编 `not_wired`（推荐，信息量最大）；②映射为 `unknown（已声明未接线：…）` 括注形态。**禁把 not_wired 写成 wired 或去掉括注的 partial**。
6. **离线 passed 全部是「限定面 passed」**：括注内写明覆盖子面。行级 offline=passed 只能在该行「必须证据」全项覆盖后由主会话授予；本草案无一行授予行级 passed。
7. **live_validation 本会话零 passed**：全部 65 行 live=unknown 或 blocked。禁把离线 passed 上移为 live passed（矩阵 L94「mock 断言不给真实平台标 passed」）。
8. **在飞席禁按计划回填**：S14（s14 §二为交付**计划**，§五实跑待填）与 WIRE（wire §3 施工中，COORD 记施工中）的代码是否收口以实跑证据为准；其计划值不得回填。
9. **重组波的证据边界**：W1a–W16/WC1–WC4/WOC/W13b 只支撑两条判断——①「组织面迁移完成且零行为改动」（各波回归数字）；②垫片同一性。**不支撑**任何行为验收升级（plan §8.3 G10：重组≠沙箱迁移≠LEGACY-001 验收）。
10. **两处矩阵旧证据已被本会话证伪，合入时顺带修正括注**：L40「RRF 无」已过时（s8 §0：存量 retrieve 已有三通道 RRF）；L48「ASR 无」已过时（s10 §一：transcribe.py/build_asr_provider 已在盘）。
11. 全批未 commit（共享工作树）、未重启、未部署；合入矩阵不改变该事实，矩阵内勿出现任何「已生效」表述。

## 一、逐行回填草案表（65 行 × 四列 + confidence + 证据指针）

> 列值口径：implementation=implemented/partial/unknown；production_wiring=wired/partial/not_wired/unknown；offline_validation=passed/failed/unknown（括注=限定面）；live_validation=passed/blocked/unknown。括号内为与本会话增量对应的括注建议。**全部为未 commit/未重启状态的代码面证据。**

| 行 | 需求（简称） | implementation | production_wiring | offline_validation | live_validation | conf | 证据指针（本会话增量） |
|---|---|---|---|---|---|---|---|
| L13 | BASE-001 冻结/WIP/归属 | partial（现值保持；增量=变更归属面强化：COORDINATION 54 条席位记账+各席日志文件域声明） | unknown | unknown | unknown | high | COORD 全文；r8 §二/§三（回执库钉死死亡时刻、生产数据只读取证）；UPDATE §六 |
| L14 | ISO-001 AppContainer 隔离 | partial（现值保持；本会话零行为改动，仅 supervisor 域迁移） | unknown | unknown | unknown | unknown | woc §一/§五（supervisor 7 件迁 core、monkeypatch 改写）；前批 1 红未动见 UPDATE §四.A.1 |
| L15 | ISO-002 Job 限制/回收 | partial（现值保持；同上零行为改动） | unknown | unknown | unknown | unknown | woc §一/§五 |
| L16 | CORE-001 DTO 零副作用 | partial（现值保持；增量=import 探针先例：creation 子进程真包探针零 nonebot/线程/socket/open 增量，可作全量探针形态参考） | unknown | unknown | unknown | high | wpa1 §4（import 探针零副作用行）；woc §二（contracts/__init__ 纯聚合无副作用注册） |
| L17 | AUTH-001 凭据/scope/撤销 | partial（现值保持，本会话无席位认领） | unknown | unknown | unknown | unknown | 无（s9 §一.5 仅只读复用既有读/写依赖） |
| L18 | AUTH-002 跨主体授权 | partial（现值保持，无席位认领） | unknown | unknown | unknown | unknown | 无 |
| L19 | REG-001 全类型注册 | partial（现值保持；feature_catalog/gate 域迁移零行为改动） | unknown | unknown | unknown | unknown | woc §一（features 归 ops/features） |
| L20 | REG-002 父子开关/CAS | partial（现值保持；执行门仍未接） | unknown | unknown | unknown | unknown | v1 §3.1（services 回归 74 passed 非回归佐证） |
| L21 | CFG-001 严格参数/CAS/消费者 | partial（增量=首个真实消费者贯通：S9 LLM 键面 config preview/apply 复用 ConfigControlService 逐键 CAS 链推进+非 LLM 键 422） | unknown（bot 进程热改仍属台账 #3 既有取舍） | unknown（行级全项未核；S9 12 例覆盖 CAS 链/422/RBAC） | unknown | verified | s9 §二/§四.1/§五 |
| L22 | RELOAD-001 生命周期五段 | partial（现值保持，无席位认领） | unknown | unknown | unknown | unknown | v1 §3.1（lifecycle 回归 74 passed 非回归佐证） |
| L23 | API-001 envelope/DTO/RBAC 一致 | partial（增量=v1 28 路由→+13 LLM 端点[s9]+8 占卜端点[s12]，全 envelope/RBAC/错误码注册表+envelope meta 增 trace_id） | partial（控制面 REST 已挂接[_app.py:478-491 真装配冒烟]；生产启用键未配未部署） | unknown（已交付端点契约测试 passed；Duplicate Operation ID 告警未收口） | unknown | verified | s9 §二/§四.1；s12 §〇/§二；s9 §六.3 |
| L24 | SSE-001 事件持久/续传 | partial（现值保持，无席位认领） | unknown | unknown | unknown | unknown | v1 §3.1（events 回归 74 passed 佐证） |
| L25 | RESOURCE-001 资源治理 | partial（现值保持；「仅指标无治理」未动） | unknown | unknown | unknown | unknown | v1 §3.1（resources 回归佐证） |
| L26 | TASK-001 租约/幂等/对账 | partial（现值保持，无席位认领） | unknown | unknown | unknown | unknown | 无 |
| L27 | AUDIT-001 审计可靠关联 | partial（增量=两新消费方：S9 RuntimeLogEvent 审计事件、S12 ControlPlaneAuditStore.record fail-open 不记 question 正文） | unknown | unknown（消费方测试 passed；行级「缺审计不得继续新副作用」未核） | unknown | verified | s9 §二/§四.1；s12 §一.7 |
| L28 | TRACE-001 全局 Trace 链 | partial（增量=envelope meta trace_id[s9]；「无生产写入方」保持） | unknown | unknown（S9 workspace 测试断言 trace_id；跨进程 part 关联未核） | unknown | verified | s9 §一.6/§四.1；s9 §六.3（traces Duplicate ID 移交 V1 席） |
| L29 | LOG-001 七类日志/实时采集 | partial（现值保持；增量=在飞 S14 NapcatTailCollector **计划面**，实跑未记录，勿回填） | unknown | unknown | unknown | unknown | s14 §二.3/§五（待填）；COORD L53（施工中） |
| L30 | METRIC-001 低基数指标 | partial（现值保持，无席位认领） | unknown | unknown | unknown | unknown | 无 |
| L31 | BILL-001 LLM 计费语义 | partial（现值保持；回归含 ledger 面零红） | unknown | unknown | unknown | unknown | r1 §四（253 passed 含 ledger 族）；r1 §六/fix2（207 passed） |
| L32 | BILL-002 TTS/绘图多单位计价 | partial（增量=creation 契约草案多单位计费字段落盘（characters/audio_seconds/requests、Token 不伪造、Decimal 禁浮点），全部 reserved 未实现；TTS/绘图实现体仍缺） | unknown | unknown（协议形态测试 39 passed 非行级验收） | blocked（外部 provider 未配置） | high | wpa1 §2/§4；s10 §一 TTS 段 |
| L33 | BILL-003 预算预留/结算 | partial（现值保持，无席位认领） | unknown | unknown | unknown | unknown | r1 §四（pricing 族回归佐证） |
| L34 | DISPATCH-001 中央 Dispatcher | partial（阶段 1 落地：OutboundSideEffectExecutor 统一出站执行器+decision dispatch 真实派发周期（shadow 绝不发送语义保持）；能力派发接管仍阶段 2+） | partial（poke 回戳/贴表情两组生产直连点已收编门面，重启生效；engine_only 触发点生产侧无调用方） | passed（限定面：152 全族+221 扫掠+3 条 xfail 转正） | unknown（待重启） | verified | dsp §一/§二/§三/§四.2 |
| L35 | DELIVERY-001 统一 Queue | partial（增量=poke/表情直连点收编统一出站路径（Intent→准入→租约→TransportRegistry→call_api 同通道本体）；S0 所记 3 组绕队列的全量收编清单复核归接线席） | partial（收编已落生产码，待重启） | passed（限定面：dsp §三+r2 §三） | unknown | verified | dsp §一坐标复核表；r2 §一（retcode=1200 挂起） |
| L36 | DELIVERY-002 UNKNOWN/部分成功 | partial（增量=retcode=1200 三失败形态改 bot_unavailable 挂起（FAILED_RETRYABLE+90s 重探+不烧预算），不再终态丢消息；PARTIAL 补偿既有） | partial（生产码已落，待重启） | passed（限定面：r2 §三 21+111+66；fix §实跑 40+71） | unknown | verified | r2 §一/§三/§四；r2 §六 |
| L37 | REPLY-001 无空行/字素切分 | partial（现值保持；「字素切分无」仍缺；增量=FIX2 九红收口+roleplay 段落既有语义随 W13 零内容迁移） | unknown | unknown | unknown | verified | rp §八（12 passed）；w13b §1/§4（render 域迁移+契约族 181 passed） |
| L38 | PERSONA-001 人格版本生命周期 | implemented（V1：draft/publish/activate/rollback 全链+CAS BEGIN IMMEDIATE+SQL 不可变触发器+损坏隔离 quarantine+权限门+build_core_injection 唯一出口） | partial（WIRE 接线件在盘[providers.py 切换点+persona_injection.py+bot_persona_versioned_injection 三处同生；s12 §二 mypy providers.py×2 佐证在盘]，默认 False 灰度；**实跑证据未落盘[wire §3 施工中]，不得记 wired**） | passed（限定服务面：v1 §3.1 19 passed+234 回归；接线面测试计划 7 例未证实） | unknown | verified | v1 §2/§3.1/§4；wire §2/§4；s12 §二；COORD L2 |
| L39 | WORLD-001 世界书版本/预算引用 | implemented（最小切片：版本化+悬空/循环引用 DFS 校验+Token 预算+untrusted 出站标注；跨库环检测边界已在 docstring 声明不可达） | not_wired（build_worldbook_service 零生产接线） | passed（限定面：悬空/预算/环/结构/往返 5 例） | unknown | verified | v1 §2/§3.1/§4/§5.3 |
| L40 | KB-001 检索/RRF/原子重建 | implemented（S8：分数/来源透出、跨库融合、SQLite backup API 原子重建、embedding 版本变更、脱敏预览；**矩阵「RRF 无」括注已过时应删**；R3：检索锁外预热+流式 fetchmany+世代号） | not_wired（build_knowledge_service 零生产接线） | passed（s8 §2：14+143 合并；r3 §四：17/55/106） | unknown | verified | s8 §0/§1/§2/§5；r3 §二.1/§四 |
| L41 | MEM-001 审核/遗忘/墓碑 | implemented（V2 修 4 真 bug[幂等 UNIQUE 索引/touch_used 缓存/版本虚高/归因候选面]+补 5 缺失[forget 权限/空白校验/sensitivity 真引用/恢复保绑定/反思实证]） | not_wired（零生产接线；build_memory_service_v21 就绪） | passed（41 passed+存量 74 passed） | unknown | verified | v2 §1/§2/§3/§4；**前提冲突待用户裁决：独立新库 vs「同源同库」（v2 §5）** |
| L42 | DB-001 query_id 安全查询 | implemented（unknown→implemented：DatabaseBroker 四层纵深[白名单+静态校验+命名参数+ro+2s 超时+200 行限]+5 预注册查询） | not_wired（无任何能力/控制面调用点） | passed（22 例：注入矩阵/行限/超时/只读/排序枚举） | unknown（未对生产库实查） | verified | s8 §1/§5（plan §8.3 G6「无载体」状态因本席解除） |
| L43 | TEACH-001 教导不提升人格权限 | implemented（unknown→implemented：封闭三值类目+内容红线扫描不入库+注入面结构隔离[background_knowledge 禁复述]+全生命周期+版本回滚） | not_wired（无命令入口/无 __init__ 接线） | passed（29 例） | unknown | verified | s8 §1/§5 |
| L44 | ROUTE-001 模型控制/路由预览一致 | partial（**s9 §三明确建议保持 partial**：API 投影面全量[13 端点+routes/preview 消费 R1 管线]+R1 路由健壮性收口[严格优先级/90s 冷却 SQLite 降级/3s 链止损/INTIMATE grok 钉一/告警折叠/逐跳日志/PRIORITY_GROUPS 恒 no-op 修复]；控制面执行门未接） | partial（路由/冷却/止损在生产 bot 链已接待重启；llm live 测试与真实发送两端口 503 短路待装配[s9 §六.1]） | passed（限定面：r1 §四 23+253；s9 §四 12+365） | unknown | verified | r1 §二/§三/§四；s9 §〇—§五 |
| L45 | ROUTE-002 grok 解耦/拒答不绕过 | implemented（R7 逐项复核检测链端到端健康零缺陷+explicit_allowed_for_session 零覆盖缺口补 6 例+探针 14 例；R1 INTIMATE 钉一守卫+熔断回落 warning；RP 文风指令按 route_verdict.mode 二选一互斥注入） | partial（生产链已接待重启；探针已按生产注册表快照实测候选序） | passed（r7 §四 44 passed+探针离线实测） | unknown（--live 探针就绪，待用户 BOT_PROBE_LIVE=1 实弹） | verified | r7 §一/§二/§三/§四；r1 §二(d)；rp §五.2/§六 |
| L46 | WORKSPACE-001 sandbox/确认摘要 | partial（sandbox 隔离/确认协议/审计/trace 齐；real_session 真实发送端口合同内不实装，确认消费前诚实 503 not_wired 不烧确认） | not_wired（真实发送端口待装配席[s9 §六.1]） | passed（s9 §四.1 6 例） | blocked（端口未实装） | verified | s9 §〇.1/§二/§四.1/§五 |
| L47 | MEDIA-001 图片/OCR/证据 | partial（协议面 closed：8 描述符+受控调用面+权限/限额/降级；**OCR=VLM 代位诚实 degraded，真 OCR 引擎仍缺**） | not_wired（协议面未接 control_plane[s10 §六.1]；媒体归档未纳 descriptor[s10 §六.2]） | passed（s10 §四 59 passed） | unknown | verified | s10 §一/§三/§四/§五 |
| L48 | MEDIA-002 ASR/视频/字幕/抽帧 | partial（四能力协议化+抽帧上限 24；**矩阵「ASR 无」括注已过时应删：transcribe.py/build_asr_provider 已在盘[s10 §一]**） | not_wired（同上） | passed（s10 §四） | unknown | verified | s10 §一/§五 |
| L49 | FILE-001 Office/PDF/代码读取 | partial（7 读通道+`.tex` 补文本路；.ppt/.xls 诚实 parser_unavailable 锁死；pypdf 未装=PDF 整类诚实降级[环境注记]） | not_wired（协议面） | passed（真实文件实调 .py/.md/.tex/.docx/.xlsx/伪 OLE2[s10 §四]） | unknown | verified | s10 §一/§三/§四/§六.6 |
| L50 | FILE-002 生成资产不执行 | partial（域内侧：build_generated_file 入协议面 admin 门+禁冒充 Office 实测；transport/FileGateway 侧未动） | not_wired | passed（限定域内侧[s10 §四]） | unknown | verified | s10 §一/§五 |
| L51 | TTS-001 TTS 协议/任务/出站 | partial（unknown→partial：协议对接点 descriptor+limits[s10]+字段级契约草案 reserved[wpa1]；invoke=unavailable 不假成功；**实现体缺**。注：wpa1 §5 主张整行维持 unknown[协议≠可用]，本草案折中为 partial+live blocked，主会话终裁） | not_wired | passed（限定协议面：s10 §四 unavailable 分支+wpa1 §4 39 例） | blocked（无 provider 配置；capabilities/tts.py 归属=W-PA2 待裁决） | verified | s10 §五；wpa1 §2/§4/§5 |
| L52 | IMAGE-001 绘图协议/资产/安全 | partial（unknown→partial：零现载体如实登记+SafetyCheckHook/资产/ConfirmToken 契约草案 reserved+注册面 dormant 三道门；同 wpa1 异议注记） | not_wired | passed（限定协议面[wpa1 §4]） | blocked（无 provider） | verified | s10 §五；wpa1 §2/§5 |
| L53 | SEARCH-001 九源检索 | partial（九源逐源诚实状态面 closed[available/not_configured/degraded/unknown 禁假 available]；xhs/YT/X/LinuxDo 实现仍缺；本会话另落 ACG 竖源三源[Bangumi/萌百/B站]——chat 链时效检索，非九源 SearchService 本体） | not_wired（search_service provider 生产装配未接[s10 §一]） | passed（限定协议/意图/融合面：s10 §四+search §三 79 passed） | unknown（九源真实可达性未实测[s10 §六.4]） | verified | s10 §一/§三/§五；search §二/§三 |
| L54 | SEARCH-002 注入/SSRF 防护 | partial（协议面 URL 入口强制 check_download_url+guard_user_url 沿用不绕过；DNS rebinding 深防仍无证据保持） | not_wired（协议面） | passed（限定拒绝分支[s10 §四]） | unknown | verified | s10 §一/§三/§五 |
| L55 | TIME-001 可信时间/节假日 | partial（增量=HTTPS Date 头授时兜底链[NTP 全败→https HEAD→系统钟，仅收 https，±1.5s 钳制，2 新键三处同生]+例外表未知年份=unknown 不猜语义） | partial（timesync 生产链已接待重启；新键缺省 enabled） | passed（r3 §四 26 例含 timesync_http+存量 106；s11 例外表 unknown 语义） | unknown（真机 NTP/HTTPS 网络环境） | verified | r3 §二.4/§四；s11 §一 |
| L56 | SCHEDULE-001 课表→草稿→提醒 | implemented（unknown→implemented：timetable.py 行列合并/单双周/节次映射/指纹去重/缺学期缺节次表拒发布+llm_draft 草稿面） | not_wired（无 matcher/装配；三装配助手就位[s11 §四.1]） | passed（16 例全离线） | unknown（需真机截图+识图 registry+出站授权） | verified | s11 §一/§三/§五 |
| L57 | SCHEDULE-002 事务链/不擅自购买 | implemented（unknown→implemented：W10 引擎 DAG/硬冲突/diff+七模板链种子→draft_to_plan_payload；无 pay/purchase/auto_buy 语义测试断言） | not_wired（同上） | passed（21 例+W10 653 面保持） | unknown | verified | s11 §一/§三/§五 |
| L58 | SCHEDULE-003 恢复/晚点/防风暴 | implemented（claim 精确一次/quiet/storm/reconcile 引擎+delivery submit 面+退避重试+receipt 诚实落账+not_authorized 干跑不伪装） | not_wired（tick 无调度装配；SendQueue 协议就绪，真实出站端口未授权；**存量 reminders.py 生产线并行未切**） | passed（17 例：安静不出站/风暴 digest/退避/超限终态/干跑/跨年 unknown） | unknown | verified | s11 §一/§三/§五 |
| L59 | AFFINITY-001 拒答≠辱骂/预算 | implemented（拒答/七族非关系零计分+滚动预算=v21.1 批[UPDATE §三.5]；R4 v6 饱和曲线/同日递减/日节奏帽+边界归零不击穿） | partial（生产码在位，重启生效[r4 §遗留]） | passed（r4 §实跑 151 passed 含七类零计分/帽/幂等回归） | unknown | verified | r4 §算法/§实跑；UPDATE §三.5 |
| L60 | AFFINITY-002 误扣重放/补偿 | unknown（**本会话无席位认领，整行维持 unknown**；UPDATE §四.C 列为收尾债） | unknown | unknown | unknown | unknown | 无（债登记：UPDATE §四.C） |
| L61 | AFFINITY-003 平滑/称谓/策略 | partial（R4 平滑/阈值边界强化[饱和带外恒等/边界归零/方向不对称]；称谓/主动互动面沿用既有，本会话未新增证据） | partial（待重启） | unknown（行级全项未核；r4 151 例覆盖平滑/帽面） | unknown | verified | r4 §算法/§实跑 |
| L62 | POKE-001 回戳/防环/额度 | partial（#35 五件套既有；本会话增量=同键在途租约防环[dsp]+notice 摄取链全链路回归锁[r5 §A]+poke 权威通道不饱和不递减[r4]） | partial（回戳/贴表情收编统一出站待重启[dsp §二]） | passed（dsp §三 152 含 poke_v2 13 例；r5 §实跑 166） | unknown | verified | dsp §一/§二/§三；r5 §A；r4 §遗留 |
| L63 | EXPRESSION-001 表情标准化 | partial（既有 store/engine；增量=QQ/TG reaction 出站经统一执行器+签名/coercion 逐字节断言；**TG set_message_reaction 仍无触发接线[诚实保持]**） | partial（待重启） | passed（dsp §三 wiring 断言+w6 回归 439/413） | unknown | verified | dsp §一/§二.二；w6 §三/回归 |
| L64 | DIVINATION-001 运势幂等/防刷 | implemented（同日幂等跨幂等键/时区日界/密钥轮换不重抽+频控；REST 8 端点+DTO/errors/facet+渲染投影+真装配端到端冒烟[in-seat tested]） | partial（控制面 REST 已挂接[_app.py:478-491]；生产 bot 启用留 bot_control_plane_divination_db 键未配未部署[s12 §三.2]） | passed（27 passed+W5 743 面零回归+控制面 274） | unknown | verified | s12 §〇/§二/§三/§四 |
| L65 | DIVINATION-002 塔罗无放回 | implemented（固定 seed/无放回/78 张/阵型白名单/429/渲染回退纯文本；LLM 解释=503 not_wired 诚实位+话术池） | partial（同上；解释端口待接线[s12 §三.3]） | passed（27 例） | unknown | verified | s12 §一/§二/§四 |
| L66 | DIVINATION-003 八字语义保持 | implemented（bazi preview 只读投影与 data/ganzhi 直算同源断言+时区东八区+越界 422+每主体固定窗限速；原算法回归=W5 743 面 743 passed 1 skipped；S13 共有列不代答） | partial（同 L64） | passed（743 面零回归+27 例内 bazi 段） | unknown | verified | s12 §〇/§四 |
| L67 | LEGACY-001 存量逐个迁移 | partial（**重组组织面完成**：19 域+留守、~200 件真身迁移、全部旧位 PEP 562/re-export 垫片、monkeypatch/文本锚 AST 终验清零、verify_hashes/doc_sync/契约门全绿；**Plugin manifests 与行为对照全表仍无，沙箱迁移正交未动[plan §8.3 G10]**） | partial（生产 import 经垫片行为等同，待重启；零行为改动多波实证） | unknown（行级验收未做；各域非回归佐证 passed：w5 §3 743、w10 §六 653、wc1 §四 755、wc3 §5 1241、wc4 §四 3186、w8 §五 1204、w12 §五 629） | unknown | verified（限「重组零回归」判断） | 各波日志回归节；plan §8.2 L67 行/§8.3 G10/G12 |
| L68 | ACTION-001 真实 executor | partial（现值保持；增量=出站侧统一执行器先例在盘[dsp]——非控制面 ControlActionRegistry executor；S14 RecoveryService executor 协议**计划面**在飞） | unknown | unknown | unknown | high | dsp §一；s14 §二（计划，未实跑） |
| L69 | STARTUP-001 启动/鉴权/实例分类 | partial（R2 六项闭合：TG 降噪/1200 挂起/mail 退避/Ctrl+C 上限/misfire 30s/早停钩子+resilience 401/403/409 分类停轮询+startup catch_all 不逃逸；R8 crash_trap 心跳+退出标记兜底+闪退定性=外部 TerminateProcess；INT 两挂接[watchdog on_startup+停机 cancel_kb_sync]） | partial（bot.py/scripts 生产码已落，待重启；R8 §六 验收点已列） | passed（r2 §三 21+111+66；r8 §六 7 passed；r3 §6.3 84 passed） | unknown（真机验收点：R2 §五/R8 §六） | verified | r2 §一/§三/§四/§五；r8 §五/§六；r3 §六；fix §六 |
| L70 | HEAL-001 统一自愈/预算/稳定窗 | partial（现值保持；增量=在飞 S14 RecoveryService **计划面**[s14 §二，测试未实跑勿回填 done]；邻接已验组件=R3 loop_watchdog[r3 §二.3，挂接已验 r3 §6.1]+kb 零变更夜跳过 ANN 重建+协作取消[r3 §二.2]） | unknown | unknown | unknown | unknown | s14 §二/§四/§五（待填）；r3 §二/§六 |
| L71 | REPAIR-001 自修复待审补丁 | unknown（**整行维持 unknown**；S14 仅 PATCH_REQUIRED 分类设计[s14 §一.1]，无实现；plan §8.3 G8 建议落 ops/recovery 待立项） | unknown | unknown | unknown | unknown | s14 §一.1；plan §8.3 G8 |
| L72 | INCIDENT-001 结构化故障/恢复通知 | partial（现值保持；增量=在飞 S14 IncidentService **计划面**[结构化字段/脱敏复用 redact_local_secrets 单一事实源/聚合/防递归]，测试未实跑勿回填；邻接=error_report 脱敏面回归 44 passed） | unknown | unknown | unknown | unknown | s14 §二/§五（待填）；search §五（fix2 44 passed） |
| L73 | ACCEPTANCE-001 自动全流程 | partial（现值保持，无席位认领） | unknown | unknown | unknown | unknown | 无（域外 G3） |
| L74 | ACCEPTANCE-002 admin 取产物 | unknown（**整行维持 unknown**，无载体无认领，plan §8.3 G3） | unknown | unknown | unknown | unknown | plan §8.3 G3 |
| L75 | DOC-001 统一投影 | partial（增量=命令格式统一规格文档层全量：77 主题真值盘点[逐条 echo.py 行号]+四段式语法+14 领域×77 主题归属+九形态矩阵+81 条条目正文；**零代码，落地批待用户评审 §4.1/§5.3**；doc_sync 门禁多波 passed 佐证投影未破） | unknown（规格未落码） | unknown（行级验收不变；doc_sync 4 passed 多波：w13b §4、s11 §三 19 passed） | not_applicable（纯文档规格交付；落地后按行级验收） | verified | cmd §1/§4/§5/§8；cmd-inventory；各波 doc_sync |
| L76 | RELEASE-001 全门禁/浸泡 | partial（现值保持；**本会话全量门禁未跑**[席位禁令+多席在飞无判定力]；收口需主会话全量实跑后回填 offline 列） | unknown | unknown | unknown | high | r2 §五；dsp §四.3；本席通读：无任何席位跑 dev.ps1 四门禁 |
| L77 | RELEASE-002 授权部署/live 验收 | unknown（**整行维持 unknown**；域外 G4，等用户授权窗口） | unknown | unknown | unknown | unknown | plan §8.3 G4；UPDATE §四.B |

## 二、本会话交付映射（席位 → 行 → 推进程度）

> 推进口径：**done**=席位自记四列且日志含实跑命令+输出；**partial**=行级验收未全但增量有实跑证据；**wiring-in-flight**=接线件在盘、实跑证据未落盘（不得记 done）；**not_wired**=服务/载体就绪零生产接线；**blocked**=外部条件（provider/授权/重启）未满足；**in-flight(计划)**=仅计划落盘。禁把 not_wired/in-flight 美化为 done。

| 席位 | 推进的行 | 推进程度与要点 |
|---|---|---|
| S8 | L40/L42/L43 | done（implementation+offline）：KB 原子重建/DB Broker/Teaching 三服务+65 例离线；三行 production_wiring=not_wired；顺带修正矩阵 L40「RRF 无」旧括注（s8 §0/§5） |
| S9 | L44/L46；增量 L21/L23/L27/L28 | partial（s9 §三 自认 L44 保持 partial）；L46 wiring=not_wired+live=blocked；L21 首个真实消费者贯通；L23 +13 端点；两诚实错误码 not_configured/not_wired（s9 §五） |
| S10 | L47/L48/L49/L50/L51/L52/L53/L54 | partial（协议面 closed 8 行）；L51/L52 从 unknown 拉到 partial+live blocked；修正 L48「ASR 无」旧括注（s10 §一） |
| S11 | L56/L57/L58；增量 L55 | done（implementation+offline）：三行 unknown→implemented，wiring 全 not_wired（s11 §四.1/§五） |
| S12 | L64/L65/L66 | done（in-seat tested）：三行 implemented+真装配冒烟；wiring=partial（REST 挂接，生产键未配未部署） |
| V1 | L38/L39；增量 L28 | done（implementation+offline）：人格/世界书两服务+19 例；wiring 移交 WIRE |
| V2 | L41 | done（implementation+offline）：修 4 bug 补 5 缺失+41 例；**前提冲突报告**（独立新库 vs 同源同库，v2 §5）待用户裁决 |
| WIRE | L38（wiring 面） | **wiring-in-flight**：接线件在盘（s12 §二 mypy 佐证）但 §3 实跑证据未落盘、COORD 记施工中——只可记 partial，禁记 wired |
| S14 | L70/L72；关联 L29/L68/L71 | **in-flight(计划)**：三子包+三测试件为交付计划，实跑节待填——四列全部不回填；PATCH_REQUIRED 分类设计涉 L71 |
| DSP | L34/L35；增量 L62/L63/L68 | partial→关键推进：阶段 1 出站统一执行器+decision dispatch 派发周期+两组直连点收编+3 xfail 转正；能力派发接管仍阶段 2+（dsp §四.2） |
| R1 | L44；增量 L45 | partial：路由健壮性六件收口+PRIORITY_GROUPS 恒 no-op 修复（4 例回归锁） |
| R2 | L69；增量 L35/L36 | partial：六项闭合；retcode=1200 挂起语义；fix 席收口孤儿红（r2 §六） |
| R3 | L40/L55；邻接 L70 | partial：检索停摆根治四处+HTTPS 授时兜底+loop_watchdog；INT 席两挂接记 r3 §六 |
| R4 | L59；增量 L61/L62 | done（L59）/partial（L61）：v6 平滑层+151 passed；poke 权威通道边界 |
| R5 | L62；增量 L35 邻接 | partial：notice 摄取链回归锁+安静时间静默锁死+两餐开场池化收编（r5 §C②） |
| R6 | L67（assistant 域文案） | done（域内）：daily_assist 11 池池化+语气守卫；越域两餐开场由 R5 代落 |
| R7 | L45 | done（复核+探针）：域内零缺陷零改动+explicit_allowed 6 例+14 例探针 |
| R8 | L69；L13 纪律面 | partial：闪退定性（外部 TerminateProcess，击杀者 unknown）+crash_trap 兜底 7 passed+双实例风险移交用户 |
| SEARCH | L53/L54 增量 | partial：ACG 竖源三源+时效诚实句+六键；FIX2 收口 error_report 白名单红（search §五） |
| RP | L45 增量；L37 邻接 | partial：文风互斥注入+复读三连治理（persona 源四处+chat.py 池化）+FIX2 收口 9 红（rp §八） |
| INT | L69 增量；L40 邻接 | partial：watchdog on_startup 挂接（修正 R3b 首选坐标）+kb 停机取消钩子，84 passed（r3 §六） |
| FIX/FIX2 | L36/L37/L44 债收口 | partial：三笔孤儿红逐一取证收口，涉事源码零改动（r2 §六/search §五/rp §八/r1 §六） |
| CMD | L75 | done（文档规格面，零代码）：落地批待用户评审（cmd §8） |
| PA | 全表归属映射 | done（纯文档）：plan §8 正反向覆盖表+G1–G12 缺口清单——本草案行→域归属直接沿用 |
| W-PA1 | L51/L52 | partial（契约草案 reserved）：39 例协议形态测试；主张 L51/L52 整行维持 unknown（wpa1 §5，与本草案折中值并存待主会话终裁） |
| RW1a–W16/WC1–WC4/WOC/W13b | L67；L16 先例 | partial（组织面 done、行级验收未动）：19 域迁移+垫片+AST 终验+各域回归全绿；W-PA1 波 creation 骨架 |

## 三、缺口清单（仍 unknown / not_wired / blocked / 在飞的行 + 缺什么）

| # | 缺口 | 涉及行 | 缺什么 / 谁能补 |
|---|---|---|---|
| 1 | **live_validation 全线空白**：65 行 live 无一 passed（blocked 仅 L46/L51/L52） | 全部 | 用户提权重启（台账 #10 存量+本批全部 WIP）+真机验收（acceptance-manual §6.6 族）+S15/S16 外部授权（admin 收件人/白名单/预算/部署窗口，UPDATE §四.B）——主会话一次性汇总授权 |
| 2 | **production_wiring=not_wired 面最大**：新载体全部零接线 | L39–L43、L46–L50、L53/L54、L56–L58 | 接线席/装配波：`__init__.py` 装配+matcher/命令面+帮助 topic+控制面动作注册（s8 §6.1、s11 §四.1、s9 §六.1、s10 §六 各移交节已给坐标） |
| 3 | **两席在飞未验收** | L38（WIRE）、L70/L72/L29（S14） | WIRE 补 §3 实跑证据（接线面 7 例测试计划）；S14 补实跑节（s14 §五待填）——收口波补跑后本草案 L38 partial→可升、S14 三行从计划转实测 |
| 4 | **整行 unknown 未动（无载体/无认领）** | L60（误扣重放）、L71（REPAIR）、L74（ACCEPTANCE-002）、L77（RELEASE-002）；另有 L14（沙箱 1 红，UPDATE §四.A.1 前批遗留） | 立项裁决：L60 需补偿席+历史证据；L71 落 ops/recovery（G8）；L74 落 ops/smoke 或独立 acceptance 域（G3）；L77 等用户授权；L14 需 AppContainer 纯 Python 路线收口或显式阻断 |
| 5 | **LEGACY-001 行级验收未动** | L67 | 行为对照全表（逐业务，不能只测天气代表全插件，矩阵 L98）+Plugin manifests+S13 沙箱迁移——重组只完成组织面（G10/G12） |
| 6 | 全量门禁未跑 | L76 及全部行的 offline 行级授予 | 主会话收口时 dev.ps1 四门禁全量实跑（本会话各席因禁令+多席在飞均未跑全量） |
| 7 | 零散技术债 | L23（Duplicate Operation ID）、L28（无生产写入方）、L44（两端口 503 短路）、L49（pypdf 未装）、L55（例外表空表待管理员补录）、L58（重试计数进程内存）、L63（TG reaction 无触发点）、L67（W3 weather Q03 锚遗留移交 W15d/尾声波） | 各行括注内已给坐标，归对应接线席/收尾波 |
| 8 | 环境面（非代码） | 多席 layout FAIL 同款 | BOT_KNOWLEDGE_FILES 指向的用户外部目录缺失需用户归位或改 .env；双 bot.py 进程并存（r8 §五）需用户收敛单实例 |

## 四、本草案统计（2026-09-18 MAT 席实读口径）

- 覆盖：65/65 行全部给出回填值或「维持现值」判定；有本会话增量证据行=47，维持现值行=18（L14/L15/L17/L18/L19/L20/L22/L24/L25/L26/L30/L31/L33/L60/L71/L73/L74/L77）。
- implementation 提案：implemented 14（L38/L39/L40/L41/L42/L43/L45/L56/L57/L58/L59/L64/L65/L66）· partial 47 · unknown 4（L60/L71/L74/L77）。
- production_wiring 提案：wired 0 · partial 17（L23/L34/L35/L36/L38/L44/L45/L55/L59/L61/L62/L63/L64/L65/L66/L67/L69）· not_wired 17（L39–L43/L46–L50/L51/L52/L53/L54/L56/L57/L58）· unknown 31。
- offline_validation 提案：passed（全部为限定面/子面，行级 passed=0）31 · failed 0 · unknown 34。
- live_validation 提案：passed 0 · blocked 4（L32/L46/L51/L52）· unknown 61。
- confidence：verified 39 · high 5（L13/L16/L32/L68/L76）· unknown 21（维持现值行+在飞无实跑行 L29/L70/L72）。
