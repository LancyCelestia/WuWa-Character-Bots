# v21r4-B ACCEPT-PREP 席位日志（重启真机验收清单）

- 席位：ACCEPT-PREP（v21r4-B 波次）｜性质：只读汇总+新文档，零代码
- 开工：2026-09-19。第一动作=协调表登记行已追加（`v21r4-b-coordination.md` 表尾「ACCEPT-PREP | 重启验收清单 | docs/design/v21r4-b-restart-acceptance-checklist.md（只读+新文档）」）。

## 数据源（全部只读）

- 各席日志：REM-DAWN / REM-EVE / WIRE-SVC / RK5 / RET3 / RWC6-b / LEDGER /（S0-COLLECT 日志未在盘=在飞实证）
- `v21r4-b-wave-snapshot.md`（INTEGRATE 终稿，含在飞名单与状态红线）
- `v21r4-b2-direct-collect-plan.md`（DIRECT-PLAN 终稿，S0 收编方案与真机验收行 §五.5）
- `v21r4-b6-ledger-memo.md` §四（LLM live 九项清单）+ §②（合并转发 live 观察点）
- `docs/acceptance-manual.md` §6.6 族（**只参照格式，未改该文件**）
- 源码核对（只读）：`scripts/pre_restart_check.py`（7 项检查口径）、`plugins/bot_unified_runtime/config.py:160-182`（三新键缺省 False + teaching/broker 既有键缺省 True）、`.env.example:682-688`（B2① 三键真实 env 名）

## 交付物

1. `docs/design/v21r4-b-restart-acceptance-checklist.md` —— 五段结构齐：
   - ① 重启前置：pre_restart_check.py 7 项全 PASS（含 hash_ledger 前端在飞漂移的处理口径注记）；提权先 SnowLuma 后 bot.py；门缺省关确认（关态观测点=启动日志**无** `v21 services wired:` 行）；WIRE-SVC 三键 .env 名与生效条件表（主门∧分门；teaching/broker 既有键缺省 True 的连带效应；Teaching 急切建库属预期；L41 memory 不在启用清单）。
   - ② 分功能验收项：A 提醒双修 6 项（明早=明天 08:00、明晚8点=明天 20:00 含 REM-DAWN→REM-EVE 口径取代的诚实注记、今晚8点、保守边界、提醒列表、投递冒烟）；B REM 回归对照（广告闸不进提醒+满 20/过期治理）；C WIRE-SVC 门开装配冒烟（含「门开也无用户可见功能变化」诚实预期）；D RK5 三债（details 可见/OpenAPI 无 Duplicate/mypy=静态不涉真机）；E S0-COLLECT 占位（以其日志终态为准，方案面 `*_via_queue` 键为提案非授权）；F RWC5-b/RWC6-b/RET3/DOC-SYNC 四席占位。
   - ③ live 观察项：引用 LEDGER-b memo §四九项清单（不展开）+ memo §② 合并转发三点。
   - ④ 回滚方式：各门拨回缺省关 + REM-DAWN/REM-EVE/RK5/RET3/RWC6-b 回滚指针（各日志节号；REM 同文件回滚须先读最新态的警示）。
   - ⑤ 诚实声明：预案非生效记录；离线证据不支撑生产生效主张；验收前不写「已生效」；在飞席不代写结论。
2. 本日志。

## 边界自查

- 零 git 写操作、零子代理、零真实 LLM 调用/真实发送、未重启。
- 未改任何既有文件（协调表登记行=任务书明令的第一动作追加；清单与日志均为新建）；禁改面（.py / theme_tokens.py / tests/render_hashes.json / domains/render/** / backend-v2-acceptance-matrix.md / acceptance-manual.md）零触碰。
- 清单中全部断言转引席位日志或本席只读实核（config.py / .env.example / pre_restart_check.py 三处 verified；其余=转引各席日志，已在清单标注来源）。

## 完成状态

- [x] 协调表登记行
- [x] 数据源只读取证
- [x] 清单落盘（五段齐）
- [x] 本日志写交付清单
—— ACCEPT-PREP 席收（2026-09-19）。
