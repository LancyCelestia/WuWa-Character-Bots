# v21r4-B DOC-SYNC 席位日志（波末文档草案）

> 席位=DOC-SYNC｜性质=只读汇总+一份草案新文档（零代码）｜开工=2026-09-19
> 红线自查：零 git 写操作、零子代理、零真实 LLM 调用；未触碰 AGENTS.md / docs/HANDBOOK.md / docs/README.md / HANDOFF-V21R4-20260918.md / backend-v2-acceptance-matrix.md 本体及任何 .py / theme_tokens.py / tests/render_hashes.json / domains/render/**；对既有文件唯一写入=协调表登记 1 行。

## 进度

| 时间 | 进度 |
|---|---|
| 2026-09-19 开工 | 开工第一动作已做：`v21r4-b-coordination.md` 表尾追加「DOC-SYNC \| 波末文档草案 \| docs/design/v21r4-b-doc-sync-draft.md（只读+新文档）」。 |
| 2026-09-19 取证 | 读完 3 份主数据源（wave-snapshot / qa-probe-report / b2-direct-collect-plan）+ 16 份席位日志（CHARTER/DIRECT-PLAN/DOCS/INTEGRATE/LEDGER/MAT/MEM-DEC/PORT-PLAN/QA-PROBE/REM-DAWN/REM-EVE/RET3/RK5/RWC6-b/WIRE-DIRECT/WIRE-SVC）+ 协调表；核对合入目标格式：HANDOFF-V21R4-20260918.md §5.1/§5.3/§6.3、docs/README.md 尾部索引区、HANDBOOK 尾节（实核 **§31 已被「内容政策 v2 批」占用**→草案改拟 §32）、AGENTS.md 台账现表止于 #36（#37-#40 为 v21r2 草案未合入→本批取 #41）。 |
| 2026-09-19 交付 | `docs/design/v21r4-b-doc-sync-draft.md` 落盘；禁语校验实跑 `grep "已生效\|已上线\|已接线"` 于草案=零命中（唯一头部红线声明亦已中性化）。 |

## 交付清单

1. **docs/design/v21r4-b-doc-sync-draft.md**（唯一交付物，草案新文档）——四节+合入前置：
   - §〇 三处编号冲突提示（HANDBOOK §31 被占用→拟 §32；台账 #37-#40 草案未合入→本批 #41 须同窗插入；not_wired 17vs18 口径差）；
   - §① AGENTS.md 台账新行草案（#41）：一句话总账+逐包结论表（17 包，含实跑计数与来源文件）+可直接粘贴的三列台账行（哈希/全量计数占位「以收尾实跑为准」）+裁决清单指针→wave-snapshot §二；
   - ② docs/HANDBOOK.md 新节草案（拟 §32）：总账+承接 §30/§31 衔接+逐包精简交付清单+在飞空位（RET3/RWC6-b/RWC5-b/S0-COLLECT）+状态口径，整节 markdown 可粘贴；
   - §③ README/HANDOFF 增量行草案：v21r4-* 全交付物列表（9 方案材料+4 波次文档+16 日志+代码/测试/配置面清单）+README 新增「波次文档（v21r4）」索引表+HANDOFF 三处增量（§5.1 交付段/§5.3 not_wired 17 更正句/§6.3 裁决入口）；
   - §④ 收尾执行清单：在飞收口前置（含 RK5 日志自称完成与任务书在飞的差异核对）→dev.ps1 四门禁+一致性门禁四件+全量测试（占位不预填）→前端合流后四项（哈希 8 重录/ruff 11 错/视觉门禁 23 红/doc_sync 终收敛）→后端独占待办（根 __init__ 四直连点 pending-on-RWC5-b、RET2b 挂起=前端邻接、端口组 15 项/L41 等用户裁决项）→commit 备忘（哈希占位回填处）。
2. `docs/design/v21r4-b-coordination.md`——表尾登记 1 行（唯一对既有文件的写入）。
3. 本日志。

## 事实性备注（供收尾主会话核对）

- 任务书列在飞五席中：RK5 日志终稿自称「三项交付全部完成收工」（scoped 50 passed/扩面 436 passed）；DIRECT-PLAN 席终（方案已落盘）——草案按日志事实转写并注明差异，未替任务书改判。
- RET3 非零痕迹：批1 已落盘（11 张垫片退役+13 测试文件改写+回归 148 passed），余批待填→按「在飞（批1 完成）」标注。
- REM-EVE 与 REM-DAWN 存在一笔已裁决冲突（「明晚8点」08:00→20:00，回滚点在 REM-EVE 日志 §③），草案已登记为收尾须认账项。
- 全波未 commit，草案全部条目无哈希可引——占位待收尾 commit 后回填（草案 §4.5）。

## 完成判定

草案落盘 ✓ + 本日志交付清单 ✓ + 禁语校验零命中 ✓ + 禁改文件零触碰 ✓ → DOC-SYNC 席任务完成。
——DOC-SYNC 席，2026-09-19。
