# v21r4-B 并发协调表

| 席位 | 包 | 交付物 |
|---|---|---|
| DOCS | B4+B5 | v21r4-command-format-review.md + v21r4-kb-drift-explainer.md ｜✅完成 |
CHARTER | B3 | docs/design/v21r4-L60-立项书.md, docs/design/v21r4-L71-立项书.md, docs/design/v21r4-L74-立项书.md ｜✅完成
MAT | B1 | docs/design/backend-v2-acceptance-matrix.md（独占写）｜✅完成
LEDGER | B6 | docs/design/v21r4-b6-ledger-memo.md（只读调研）｜✅完成
WIRE-SVC | B2① | 根__init__.py服务装配插入段(4124-4143), runtime/service_wiring.py(新), runtime/database_broker.py(只读复用), config.py(174-178三键追加), docs/config-catalog-full.md(S8区3行+2行措辞), .env.example(B2①块), docs/auto-facts.md(doc_sync --write), tests/test_v21_wire_svc_assembly.py(新增12例)｜注：character/三服务实现零改动（纯复用既有builder）｜✅完成
PORT-PLAN | B2②方案材料 | docs/design/v21r4-b2-port-wiring-plan.md（只读+文档）｜✅完成
WIRE-DIRECT | B2③（L56/L57/L58/L65） | docs/design/v21r4-b-WIRE-DIRECT-log.md（日志）、tests/test_v21_wiredirect_unified_path.py（新增离线测试）；只读取证面（不写）：domains/schedule/**、domains/divination/**、根__init__.py、domains/core/decision/outbound_registry.py | 让步记录：根__init__.py 服务装配段（L56-L58 课表/提醒生产装配+tick 调度注册=装配面）归 WIRE-SVC，本席零写入；L41 一行不动；L65 经核实属端口组性质（LLM 解释端口）→维持 503 not_wired 不实装（依据见本席日志）；矩阵四行零改动（禁改文件）｜✅完成
MEM-DEC | L41 裁决材料 | docs/design/v21r4-L41-decision-memo.md（只读+文档）｜✅完成
REM-DAWN | 提醒明早词表修复 | plugins/bot_unified_runtime/domains/schedule/store/reminders.py + tests/test_reminder.py ｜✅完成
| RK5 | 控制面三小债 | control_plane/api + tests/test_controlplane* ｜✅完成 |
| REM-EVE | 明晚时段语义修复 | domains/schedule/store/reminders.py + tests/test_reminder.py ｜✅完成 |
DIRECT-PLAN | S0 直连点收编方案 | docs/design/v21r4-b2-direct-collect-plan.md（只读+文档）｜✅完成
INTEGRATE | 波次整合快照 | docs/design/v21r4-b-wave-snapshot.md（只读+文档）｜✅完成
| RET3 | 垫片退役第三梯队 | epic/steam+仅测试消费 44 张（在飞冲突者挂起）；日志=docs/design/v21r4-b-RET3-log.md ｜✅完成 |
| QA-PROBE | 波中回归快照 | docs/design/v21r4-b-qa-probe-report.md（只读）｜✅完成 |
| RWC5-b | 根__init__惰性导入续切收尾 | plugins/bot_unified_runtime/__init__.py（独占写）｜✅完成 |

| RWC6-b | policy/security 迁移 domains/chat_reply | policy/* security/* → domains/chat_reply/{policy,security}/（垫片保旧路径）；日志=docs/design/v21r4-b-RWC6-b-log.md ｜✅完成：8真身+2__init__ 迁毕，10垫片，AST残余0，域测试394 passed/2 xfailed，verify_hashes红为预在飞（反演实证非本席，未--write） |
| S0-COLLECT | S0 直连收编非 root 件 | sender/file_gateway.py + domains/core/decision/outbound_registry.py + tests/test_v21_s0_collect.py；根内四处 pending-on-RWC5-b；日志=docs/design/v21r4-b-S0-COLLECT-log.md ｜✅完成 |
| DOC-SYNC | 波末文档草案 | docs/design/v21r4-b-doc-sync-draft.md（只读+新文档）｜✅完成 |
| ACCEPT-PREP | 重启验收清单 | docs/design/v21r4-b-restart-acceptance-checklist.md（只读+新文档）｜✅完成 |
| L41-PLAN | L41 执行预案 | docs/design/v21r4-l41-exec-runbook.md（只读+文档）｜✅完成 |
| LIVE-TOOL | live 取证采集脚本 | scripts/collect_v21r4_live_evidence.py + tests/test_v21_live_evidence_tool.py ｜✅完成 |
| RET2B-PREP | RWOC 55 张垫片冲突矩阵+安全子集退役 | docs/design/v21r4-b-RET2B-PREP-log.md（日志+矩阵）、%TEMP%/v21r4-ret2b-backup/（备份）；触碰面=RWOC 垫片本体删除+消费方（tests/ 及按矩阵放行的 src）改指 canonical；禁触面遵守波次硬约束（前端域/根__init__/policy·security/control_plane api/schedule reminders/config.py/sender file_gateway·core decision outbound_registry）｜✅完成：44 退役（40 本席+4 前席记账）+挂起 7+包垫片 supervisor/__init__ 同退；AST 零残余（v2 修正扫描器）+整树 collect 8531/0err+域回归 1756 passed/0 failed；doc_sync --write 收敛后 PASS、command_catalog 77 topics PASS、verify_hashes 15 漂移全前端在飞（零涉本席，未 --write）；dev.ps1 旧路径 30 处修复（含 RET3 遗留 2 种）；挂起 7 张移交清单在日志 §三 |
| SYNC-FINAL | 全量基线+文档收口 | tests/（只读）+AGENTS.md 三处+doc-sync-draft §五 ｜✅完成（SYNC-FINAL-b 续跑收口：前任已落盘五项盘面实证零重复编辑+六席日志核验吻合+两时点基线 8531P/1F→8528P/4F 逐条归属+§5.4 增补+终验四件在案） |
| S0-ROOT-c | 根init四处直连收编执行 | plugins/bot_unified_runtime/__init__.py（独占写）+ tests/（新增）+ config.py 四键 + config-catalog A26 四行 + .env.example 四行；接替阵亡 S0-ROOT/S0-ROOT-b（均零产出无断点），按 v21r4-b2-direct-collect-plan 执行序④②③①，TDD 门缺省关｜**✅完成（S0-ROOT-c 交付，根 `__init__.py` 已释放，TTS 席第二批可开工）**：四处全部收编（④files件/②文本管线/③mixed件/①SendQueue提醒范式+当日幂等），新测试 tests/test_v21_s0_root_collect.py 27 例（RED 16F/11P→GREEN 27P）；家族合跑 195 passed/1 failed（唯一红=verify_hashes 门 echo.py 漂移，TTS 席在飞窗口非本席触碰面，未 --write）；ruff 本席三文件 All checks passed；mypy 本席零错（余 3 错=tts.py×2+capability_protocols×1 均他席占域）；command_catalog 曾 current 77 topics（TTS echo.py 在飞后再 stale 归其窗口）；doc_sync 已预告后 --write 收敛（--check exit0）；顺带修复 _deliver_due_reminders else 分支 logger.warning 缩进缺陷（test_reminder_delivery 2 例由红转绿）；日志=docs/design/v21r4-b-S0-ROOT-log.md｜重启生效（四门缺省 False=行为零变更，True 才走统一路径） |
| RET2b-R2 | 挂起解除 4 张垫片退役（contracts.runtime、decision.outbound、sources.web_search、contracts.media；接替两任阵亡前任，均 5 秒内即死零产出） | docs/design/v21r4-b-RET2b-R-log.md（日志）、%TEMP%/v21r4-ret2b-r-backup/（备份）；触碰面=4 垫片本体+其消费方改指 canonical+挂起域测试；契约边界按退役实测再补记 |
| 主代理席 | RET2b 剩余 4 张垫片退役（接管 RET2b-R2 断点） | contracts.runtime / decision.outbound / sources.web_search / contracts.media 垫片 + 消费方改写 + 域测试 |
| 主代理席 | MYPY-FIX 吸收（model_router:439 mypy 修复，原席 7 秒即亡零产出） | domains/chat_reply/llm_engine/model_router.py |
| HANDBOOK-SYNC | 波末文档套用 | AGENTS.md #41+HANDBOOK 新节+README 索引+HANDOFF 三处 ｜✅完成（实落编号顺延：#41 被 v21r4 大波次占用→落 **#42**；§31/§32 均被占用→HANDBOOK 落 **§33**；四文件+日志=v21r4-b-HANDBOOK-SYNC-log.md，ruff 28 错零归因本席） |
LEGACY-FIX | RWC1 SKIP 四件+echo (44) 漂移 | tests/（skip 族）+ echo.py:785 一处
TOKEN-AUDIT | 缓存字段解析+输入口径审计 | llm_engine/providers.py + tests/新增
| 主代理席 | TOKEN-AUDIT 吸收（缓存字段解析+输入口径审计，原席两次阵亡零产出） | domains/chat_reply/llm_engine/providers.py + tests/新增 |
| LEGACY-FIX-b | RWC1 SKIP 四件+echo (44) 漂移 | tests/（skip 族）+ echo.py:785 一处 |
【v21r4-B 主代理席】TOKEN-AUDIT 关账
REG-REFRESH | outbound_registry BYPASS_SUSPECT 四条刷新 | domains/core/decision/outbound_registry.py + tests/test_outbound_v21.py
| LEGACY-FIX-c | RWC1 SKIP 四件+echo (44) 漂移 | tests/（skip 族）+ echo.py:785 一处 |**✅完成**：①SKIP 四件定性=非 pytest 标记，系 RWC1 台账登记（memory_service/memory_store_v21/knowledge_service/teaching_service 留守件），实证已全部收编 canonical+旧位垫片同对象 4/4 is+测试族 7 文件 **129 passed**，manifest 草案 #10 已注记转正；②echo「(44)」=echo.py 本体已被 TTS 窗口修至 46（base_router:584 实核），残留生成物 command-catalog.md:509 stale 已按预告 --write 单行收敛，--check **current 77 topics**，echo 测试族 **206 passed**；门禁=doc_sync --check PASS / verify_hashes 1 DRIFT=echo.py 归 TTS 窗口未代录 / ruff 29 错零归因本席；日志=docs/design/v21r4-b-LEGACY-FIX-log.md｜离线证据，未部署 |
REG-REFRESH ✅ | 四条 BYPASS_SUSPECT 已收编刷新+poke/reaction executor 面真身+delete_msg :4978+transport evidence 同批 | 115 passed(家族五文件)/ruff 0/catalog current 77 | 详见 docs/design/v21r4-b-REG-REFRESH-log.md
SNAPSHOT-R2 | 波次快照 §六 午后补录 | docs/design/v21r4-b-wave-snapshot.md（追加）
2026-09-19 13:44:43 | RESTART-GATE | 重启就绪快照 | tests/（只读）+门禁四件+pre_restart_check
【v21r4-B 主代理席】SNAPSHOT-R2 吸收关账（§六 补录落盘）
【v21r4-B 主代理席】RESTART-GATE 吸收关账（快照落盘，判定=能起）
