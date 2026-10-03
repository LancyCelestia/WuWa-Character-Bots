# PRV 工单 · 本窗新/改测试件隐私扫描（2026-10-02 下午窗）

席 PRV，只读扫描；判据按简报四条（长数字≥9位 / `C:\Users\` 路径 / token·sk- 形态 / 生产库名进连接串）。敏感原文一律前3后2+长度打码。8 件全部未跟踪（`??`），整窗待提交。

## ① 逐件扫描计数

| 文件 | 长数字≥9 | 用户路径 | 密钥形态 | 库名/连接串 | hex/b64 附加扫 |
|---|---|---|---|---|---|
| test_db_backup.py | 9 | 0 | 0 | 0 | 0 |
| test_ab_red_bucket.py | 0 | 0 | 0 | 0 | 0 |
| test_intimate_group_switch_delivery.py | 27 | 0 | 0 | 0（`wuwa_audit` 叙述提及×1） | 0 |
| test_migration_status_assignment_gate.py | 0 | 0 | 0 | 0 | 0 |
| test_prompt_template_layer_w1.py | 0 | 0 | 0 | 0 | b64×1（PNG 头，假图） |
| test_store_write_trace_d2.py | 15 | 0 | 0 | 0 | 0 |
| test_claims_subset_implementation_gate.py | 0 | 0 | 0 | "cookie"×4＝`/bot cookie` 命令面测试，非凭据值 | 0 |
| test_seat_t1_persona_contract_20261002.py | 0 | 0 | 0 | 0 | 0 |

## ② 命中定性表

| 命中 | 位置 | 定性 |
|---|---|---|
| `202...03(len=14)` 等 12–14 位串 ×9 | test_db_backup.py:211-257 | **夹具假数（OK）**：日期戳形态，注释自标「12 位/13 位」，测文件名校验 |
| `700...11`～`700...23`、`888...99`、`777...88` 等 | test_intimate_*:122-133,737-738,583；test_store_write_trace_d2:166-178,208,314-338 | **夹具假数（OK）**：700 假号段惯例 + 重复数字假号 |
| `110...60(len=10)`＝`_G_ACK` | test_intimate_*:4（docstring）,120 | **真泄漏**（见③） |
| `631...29(len=9)`＝`_G_DEEP` | test_intimate_*:121 | **真泄漏**（见③） |
| `386...23`＝`_ADMIN`、`295...68`/`125...73`＝`_MEMBER_A/B`、`395...05`＝bot_id | test_intimate_*:135-137,201,218 | **灰区**（见④） |
| `386...23` 复用 + `172...02` 别名目标 | test_store_write_trace_d2.py:225-231 | **灰区**（同上） |
| b64 `iVB...==(len=96)` | test_prompt_template_layer_w1.py:227 | **夹具假数（OK）**：`iVBORw0KGgo`＝1x1 PNG 假图 |
| `wuwa_audit`（叙述提及，非连接串） | test_intimate_*:3 | **灰区**（见④） |

## ③ 真泄漏点名（2 枚，交主会话）

均在新件 `tests/test_intimate_group_switch_delivery.py`，且经历史记录核实为**生产 `.env` 群白名单真值**（`.superpowers/sdd/2026-09-21-unify-consolidation/line-5-log.md:47` 记 `BOT_CONTENT_ROUTE_GROUP_WHITELIST=[三群]`，两枚逐一比对命中）：

1. `_G_ACK = "110...60(len=10)"`（:120，注释自书「**现网真实群号**」；docstring :4 同值复述）
2. `_G_DEEP = "631...29(len=9)"`（:121，未自标但与生产白名单第二枚命中）

本窗其他 6 件均无真泄漏（预期零不成立，实数为 2）。

## ④ 灰区（列动点，裁定归主会话）

1. **真实形态人号/bot 号沿用**：`_ADMIN=386...23`（全树先例 322 处，HANDOFF-V21R4 曾作「具名指针」）、`_MEMBER_A/B`（先例＝`docs/design/v21r2-aff-replay-report.md` 生产重放报告）、`bot_id=395...05`（先例 26 件）、`172...02`（先例 24 件）。属全仓既有惯例而非本窗新泄漏；动点＝若要收口可统一换 700 假号段，但牵动面大，非本窗必清项。
2. **生产库名叙述提及**：`wuwa_audit`（test_intimate_*:3 docstring）——先例 24 处（SDD 审计报告在案），非连接串使用，不触判据 4；动点＝可改「生产审计库」泛称，低收益。

## ⑤ 结论

**须先清后提交（最小清法）**：`tests/test_intimate_group_switch_delivery.py` 两枚生产真群号换 700 假号段（夹具本就经 `_config()` 自喂白名单，不依赖真值；换后全文件无残留即可提交）。灰区两项不阻提交。
