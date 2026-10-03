# 守岸人修复波 2026-10-02 下午窗 — 用户下一步一页卡（席 UNO 汇编；源＝CM 单＋CMV 勘误＋RST 单＋pre_restart 终值）
> 三步＝提交 → 重启 → 真机验证；提交/重启/验证全由用户亲手执行（常令：代理零 git 写、零进程动作）。汇编时只读核对：HEAD=143098d 未动、分支 v0.0.1-alpha.3、status 116 行（别席工单持续落盘，属预期——故每批动手前必须重跑 status）。

## 第一步 提交（七批 A→B→D→C→E→F→G，合计 64 枚＝CMV 口径 62＋RST 补收 TRG/M17；批C 依赖批A/批D 真身先行，勿按字母序）

每批通用防吞口诀（台账 #70★ pathspec 曾静默少提；批批必念）：
    一、动手前重跑 git status --porcelain：新 ?? 先按 CM 单③／CMV ②④归类，不识的不收；只准 git add -- 逐枚显式路径，禁 -A／.／-u／commit -a。
    二、add 后 git diff --cached --name-only：与本卡命令（含你现场归类补入件）逐字一致，多一枚少一枚停手；git diff --cached --stat 再对行数量级。
    三、消息正文先存 patches/CM-COMMIT-MSG-<批号>.txt，再裸 git commit -F 该文件（禁 -m 内联、消息禁反引号）；提交后 git show --stat HEAD 核对枚数，夹带 ⇒ git reset --soft HEAD~1 重来。

### 批A 挪家批（3 枚）
    git add -- plugins/bot_unified_runtime/domains/ops/db_backup.py plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py patches/DOC-DBBACKUP-REFS-20261002.md
    fix(ops): db_backup 挪家 domains/ops＋runtime_admin 唯一消费者同批接线（席 X1b P4.1＋DOC 指针普查）
    - runtime/db_backup.py 挪家 domains/ops/db_backup.py；旧路径未跟踪，git 无删除记录，status 缺位即正确形态
    - runtime_admin.py 唯一 import 消费者同批改新家；backup 命令面＋_BACKUP_WRITE_ACTIONS 门同批
    - 附 DOC 工单：全树残余指针普查（唯一真实 import 已是新路径；docs 侧残余另账）
    - 测试件 tests/test_db_backup.py 随批C入库（依赖本批真身）
### 批B 亲密人员门批（7 枚＝CM 6＋CMV 补 IVF）
    git add -- plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py plugins/bot_unified_runtime/domains/media/capabilities/tts.py tests/test_intimate_group_switch_delivery.py tests/test_tts_cache_quota_shape_guard.py patches/INT-INTIMATE-PERSON-GATE-20261002.md patches/REV-INTIMATE-ADVERSARIAL-20261002.md patches/IVF-INTIMATE-BLAST-RADIUS-20261002.md
    fix(content-route): 亲密模式群侧人腿——人在私聊白名单即任何群放行（2026-10-02 用户裁定）
    - content_route.py 群分支改四步顺序：群黑名单永远赢、群白名单次之、人腿再次、其余不放行；空 sender_id 与旧版逐字节一致
    - tts.py M-17 自动配音消费者补传 sender_id 第四参；同文件另含席 B1 的 _quota_bound 配额形态闸（防布尔混入把配额变清空），一并入库
    - 附 INT 实施工单＋REV 对抗复核工单＋IVF 爆炸半径取证工单（CMV 补收）；test_intimate_group_switch_delivery 16 腿、test_tts_cache_quota_shape_guard 同批
### 批D 生产件收编批（12 枚；先于批C；write_trace.py 必在——reply_policy/quirks/config_store 三 store import 依赖）
    git add -- plugins/bot_unified_runtime/domains/core/write_trace.py plugins/bot_unified_runtime/domains/chat_reply/llm_engine/prompt_template.py plugins/bot_unified_runtime/domains/files/capabilities/file_exchange.py plugins/bot_unified_runtime/domains/chat_reply/character/quirks.py plugins/bot_unified_runtime/control_plane/config_store.py plugins/bot_unified_runtime/domains/chat_reply/character/reply_policy.py tests/test_reply_policy_permanent.py tests/test_reply_policy_preset_command.py plugins/bot_unified_runtime/domains/chat_reply/runtime/deadline.py plugins/bot_unified_runtime/runtime/capability_protocols.py plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py plugins/bot_unified_runtime/domains/files/capabilities/download.py
    fix(core): 写路径留痕原语＋W1 模板层＋timeout-umbrella 族＋P3.11 死判据根修生产面收编
    - write_trace.py 新件；reply_policy/quirks/config_store 三 store 留痕接线（席 D2）
    - reply_policy.py P3.11 两刀（席 N1）：真身角色名替换死串 super、超管身份只认中央角色面（摘跨平台裸号冒名腿）；两枚伴随测试同批翻转
    - capability_protocols＋deadline：timeout-umbrella 预算族（席 V1；capability_protocols 另含 L2 一枚 RUF100 lint）
    - prompt_template 新件＋file_exchange W1 接线；chat.py D1 缺口（manual ack 隐私档只认会话档）；download.py P3.9 yt-dlp 落盘名消毒（席 B1）
    - nonebot.py 未入库：主 hunk 属他波 F3 邮件重投，随该波整批
### 批C 测试件收编批（23 枚；必须在批A/批D 之后）
    git add -- tests/test_claims_subset_implementation_gate.py tests/test_store_write_trace_d2.py tests/test_prompt_template_layer_w1.py tests/test_seat_t1_persona_contract_20261002.py tests/test_migration_status_assignment_gate.py tests/test_db_backup.py tests/test_command_admin_gate_registration.py tests/test_timeout_umbrella_remaining_legs.py tests/test_ab_red_bucket.py tests/test_central_dispatch_closure_gate.py tests/test_download_artifact_container_gate.py tests/test_ssrf_throat_coverage.py scripts/ab_red_bucket.py docs/boards/B02-routing-dispatch/README.md docs/boards/B02-routing-dispatch/capability-registry/README.md docs/boards/B02-routing-dispatch/decision-engine/README.md docs/design/capability-orchestration-adoption-spec.md patches/L1-TESTLINT-20261002.md patches/D2F-WRITETRACE-POISON-20261002.md patches/DBT-DBBACKUP-TESTS-20261002.md patches/MIG-STATUS-GATE-PREDICATE-20261002.md patches/BKT-AB-BUCKET-20261002.md patches/P3A-ROUTE-GATE-PROPOSAL-20261002.md
    test(wave): 本窗测试件收编——db_backup 六腿＋留痕注毒自证＋w1 门＋A/B 分桶器＋中央调度闭口常驻门
    - 新测试件十二枚：db_backup（DBT）、store_write_trace_d2 注毒双腿同抹（D2F）、prompt_template_layer_w1＋seat_t1（L1）、migration_status 量具收窄（MIG）、command_admin 门注册（P3a）、timeout_umbrella（V1 族）、download 落点门＋tts 配额形状随批B已收、claims_subset
    - ab_red_bucket 分桶器＋9 腿自证（席 BKT）：终门 A/B 红集分桶 NEW_ONLY 空才放行
    - 中央调度闭口常驻门（席 C-D-01）＋B02 三页说明＋orchestration spec 同批
    - test_ssrf_throat_coverage 夹具改喂真 PNG 魔数（对已入库收库守卫的红修复）
    - 依赖批A（db_backup 真身）与批D（write_trace/prompt_template/umbrella 族）先行入库
### 批E 工单/文档批（17 枚＝CMV 口径 15＋RST 补收 TRG/M17；其后仍会落新工单，动手前按现场 status 归类）
    git add -- patches/B1-CONFIG-REQUEST.md patches/B1-TTS-CACHE-OUTTMPL-20261002.md patches/BASE-HEADAXIS-BUCKET-20261002.md patches/CHK-LOCKFAMILY-20261002.md patches/FULL-WTAXIS-20261002.md patches/GATE-TYPECHECK-LINT-20261002.md patches/IMG-IMAGERY-AUDIT-20261002.md patches/R1-RUNTIME-LAYOUT-SCAN-20261002.md docs/HANDOFF-FIXWAVE-20261002.md patches/L2-PRODLINT-20261002.md patches/CM-COMMIT-PLAN-20261002.md patches/AUD-TICKET-RECON-20261002.md patches/PENDING-DECISIONS-20261002b.md patches/DER-DERIVED-LEDGER-20261002.md patches/DRAFT-HANDBOOK-MERGE-20261002.md patches/TRG-HOTFACE-LOCKS-20261002.md patches/M17-TTS-SPILLOVER-20261002.md
    docs(wave): 修复波工单与交接档落库（B1/BASE/CHK/FULL/GATE/IMG/R1＋CMV 补收 L2/CMPLAN/AUD/PEND/DER/DRAFT＋TRG/M17）
    - 七枚新工单：B1 配额缺省需求＋TTS 缓存/落盘名、BASE HEAD 轴基线、CHK 锁族普查、FULL 工作树轴全量、GATE 门禁盘点、IMG 意象族取证
    - CMV 补收六枚：L2 lint 出处工单（capability_protocols RUF100／nonebot RUF023／db-owners PIE810）、CM-COMMIT-PLAN 提交单自收、AUD 工单对账、PENDING 待裁清单、DER 派生册、DRAFT HANDBOOK 并账稿（正文落点 HANDBOOK §73）
    - TRG 热写面锁族核验＋M17 自动配音 sender_id 外溢面分析随批（RST 指向批E）；R1 布局扫描工单增补（缓存自报＋注入处置登记）；HANDOFF-FIXWAVE 交接档增量
### 批F ledger 地板复录批（1 枚；收前确认席 Z1 已收笔，同文件禁 hunk 拆分）
    git add -- tests/test_config_key_registration_ledger.py
    test(ledger): config 键注册册地板复录＋Z1 双向边界腿
    - 地板现算复录 (784,1606,3,684)→(784,1612,3,688)（主会话 2026-10-02；含 INT 两读点＋DBT 新测试件差数点名）；地板升＝尺更利非放宽；预估 diff +133/−1
    - 同文件含席 Z1 assert_floor_two_sided 双向边界腿追加（约 132 行，严格只追加未动旧行）；整文件同批不拆 hunk（#70★ 部分暂存漂移坑）
### 批G 生成册批（1 枚）
    git add -- docs/auto-facts.md
    docs(ledger): auto-facts 机器册重录入库（生成器 --write 收笔后一次性重录）
    - 依 HANDOFF R6 先例；干净单 hunk 2+/2−；单独成批不并 E（机器册＝规则 10，与工单性质不同）

## 第二步 重启（前置＝七批全部提交完，半成品不留盘；台账 #10★：改码不重启不生效）
    一道门（exit 0 才动手）：..\ChatBot_Runtime\venv\Scripts\python.exe scripts\pre_restart_check.py（仓库根跑）。本窗终值＝PASS 9／SKIP 4／FAIL 0 rc=0，ann_pair＋kb_drift 双 PASS；隔日重跑以当时值为准——ann_pair／kb_drift／ruff／doc_sync／hash_ledger 五枚必须 PASS，napcat SKIP 不阻断。
    顺序：先 SnowLuma 后 bot.py；bot 生产进程管理员权限启动、杀它需提权。
    提示：BOT_GATE_COMMAND_REQUIRES_LISTED_GROUP 缺省 True ⇒ 未在册群里 /bot 命令面静默，不想要此行为就置 false 再重启；TTS 三闸（BOT_TTS_ENABLED／BOT_TTS_AUTO_REPLY_ENABLED／BOT_TTS_VOICE_HOOK_ENABLED）现为 false，本次重启使三闸关真正生效。

## 第三步 真机验证（观察点＝回执/日志真出门，界面打勾不算数）
    ① ANN 提速：任一知识问题响应无暴力扫描级时延；日志无 knowledge ANN pair refused 告警；重跑 pre_restart_check 看 ann_pair 仍 PASS。
    ② 亲密人腿三步：白名单人在任意非黑群说「亲密模式 开」→ 受理回执可见；同群换名单外人发同样指令 → 不受理无回执；群黑白双挂的群 → 人再白也不受理（群黑名单永远赢）。
    ③ grok-4.6 超时腿：作为对话组第 2 顺位曾观测 1024 token 预算 60s 超时——看告警/失败面日志该腿是否复现超时与降级轮转。
    ④ TTS 三闸：.env 三闸仍为 false 且 bot 零自动语音输出（含私聊 10% 自动配音腿）。

## 别做（红线）
    不动 .wip-* 尸块；不手改生成册（command-catalog／render_hashes×2 仍禁入；auto-facts 只走生成器 --write，不手编辑）。
    不回退旧 ANN 索引——已被新代原子顶替；确要回退＝按 HANDOFF §十六 runbook 指回旧嵌入端点整代重建（n≈740k 时 ≈7 GiB 空闲起步、全链跑完才收工），先想清楚。
    禁入/暂缓面维持 CM 单③／CMV ④：AGENTS／HANDBOOK／echo.py／meme_library.py／.zcodeignore／personas imagery_families.txt 等本窗不收；暂缓 30 件等所属波次整批。

> 【更正 2026-10-02T10:46Z·席 RECN 现算，主会话落笔】本卡「合计 64 枚」已过期：64＝CMV 62＋RST 补收 TRG/M17，
> 未含 CMV2 增量。数字权威＝patches/CMV2-FINAL-DELTA-20261002.md（口径 81）；RECN 现算 status=136 行，
> 批E 实收 49＝CMV2 列 34＋CMV2 自身 1＋其后新落工单 14，七批合计 96（A3 B7 C23 D12 E49 F1 G1）。
> 账平：136＝96＋禁入 8＋待裁 3＋暂缓 29（禁入/待裁/暂缓三面与 CMV2 ③ 零变化）。
> 批E 新落 14 枚＝DBK/DOL/ENV/HDN/INJ2/ITX/MG2/NAP/OUT/PRV/SPC/SST/WIP-ANN-DISKFACTS/ZIG
> （均 patches/*-20261002.md，按 CMV2 ④ 随批E）；每批动手前仍以当时重跑 status 为准。
