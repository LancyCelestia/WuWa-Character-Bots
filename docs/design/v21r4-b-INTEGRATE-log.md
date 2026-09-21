# v21r4-B INTEGRATE 席位日志（波次整合快照）

> 席位=INTEGRATE｜任务=只读汇总+一份整合文档（零代码）｜开工=2026-09-19
> 红线自查：零 git 写操作、零子代理、零改既有文件（仅追加 v21r4-b-coordination.md 认领行）、零真实 LLM 调用/发送/重启；在飞席位只标「在飞」未替其写结论；theme_tokens.py / render_hashes.json / domains/render/** / 验收矩阵 / 各席日志零触碰；本席未跑任何测试（快照内全部证据为转引并注明出处）。

## 进度

| 时间 | 进度 |
|---|---|
| 2026-09-19 开工 | 开工第一动作已做：`v21r4-b-coordination.md` 追加「INTEGRATE \| 波次整合快照 \| docs/design/v21r4-b-wave-snapshot.md（只读+文档）」。 |
| 2026-09-19 取证 | 逐份读完本波 9 份席位日志（MAT/PORT-PLAN/WIRE-DIRECT/CHARTER/DOCS/LEDGER/REM-DAWN/MEM-DEC/WIRE-SVC）+ 8 份交付文档（b2-port-wiring-plan、b6-ledger-memo、L41-decision-memo、L60/L71/L74 立项书、command-format-review、kb-drift-explainer）。只读核验三处坐标：`scripts/pre_restart_check.py` 在盘；`v21r4-b2-direct-collect-plan.md` 不在盘（DIRECT-PLAN 在飞实锤）；WIRE-SVC/WIRE-DIRECT 两个新测试文件与 `runtime/service_wiring.py` 在盘。 |
| 2026-09-19 交付 | `docs/design/v21r4-b-wave-snapshot.md` 落盘。 |

## 交付清单

1. **docs/design/v21r4-b-wave-snapshot.md**——波次整合快照，四节+附：
   - §一 交付总表：已落盘交付 8 包（B1 MAT 矩阵回填 / B2② PORT-PLAN 方案材料 / B2③ WIRE-DIRECT 改判+结构锁 / B3 三立项书 / B4 命令评审材料 / B5 kb_drift 解释 / B6 台账 memo / REM-DAWN「明早」修复=本波唯一代码交付）+ 在飞 5 席只标状态（WIRE-SVC 主体已落盘收尾中；MEM-DEC 材料已成稿；RK5/REM-EVE/DIRECT-PLAN 盘面零痕迹）+ 并发协调事实两条（根 __init__.py 行号漂移、outbound_registry 坐标陈旧移交）。
   - §二 统一裁决清单：总表 10 组按「裁决了就解锁什么」排序 + 逐组可勾选明细——PORT-PLAN 15 项前置条件（含 TTL 三处口径分歧）、L41 三案（A 推荐/B1/B2 不建议/暂不，含条件附加项）、搜索时效三方案+三子裁决点、「一会儿」默认值（提议 15 分钟）、DOCS B4 八项（14 领域 vs 20 域等）、L60 五条（补收编，含 48h 窗口时效注记）、L71 六条、L74 七条、kb_drift 一项、其他散落授权点（L56/L57/L58 真实投递授权、L65 解释端口、亲密话术三项指针）+ PORT-PLAN 5 项信息缺口备查。每项带出处文档路径。
   - §三 口径差异登记 6 条：MAT §三三条（not_wired 17vs18、live unknown 61=60+1 not_applicable、六行清单外按表落定）+ PORT-PLAN 行号漂移（矩阵头部批注致主表 +2，交接书 L=现文件行号−2）+ 整合新登记 2 条（PORT-PLAN 读时快照 vs MAT 终态时序差；在飞行号漂移连带）。
   - §四 状态红线声明：全波未 commit/未重启/未部署；全部离线证据不支撑生产生效；零真实对外动作；重启前置=`scripts/pre_restart_check.py`；渲染红线文件零触碰。
2. `docs/design/v21r4-b-coordination.md`——认领追加 1 行（唯一对既有文件的写入）。
3. 本日志。

## 完成判定

snapshot 落盘 ✓ + 本日志交付清单 ✓ → INTEGRATE 席任务完成。全批仍未 commit/未重启/未部署，快照全文不含任何生产生效主张。
