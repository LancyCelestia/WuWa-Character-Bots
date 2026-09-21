# v21r4-B 波中回归快照（QA-PROBE 席位报告）

> **性质声明（诚实红线）**：本报告是 2026-09-19 凌晨的**时点证据**，拍摄于多席在飞中间态（REM-DAWN/REM-EVE/WIRE-DIRECT/RK5/WIRE-SVC 均未合流）。**「在飞中间态，非合流结论」**——任何失败面在合流前都可能已被在飞席修复或继续演化。本席零代码改动、零 git 写操作、全部门禁仅 `--check`（未执行任何 `--write`）。
> 席位=QA-PROBE｜日志=`docs/design/v21r4-b-QA-PROBE-log.md`｜协调表已登记。
> 运行环境：`ChatBot_Runtime/venv/Scripts/python.exe`，`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1`，pytest `--basetemp=$TEMP/<批名> -p no:cacheprovider -q`（源码树零缓存纪律全程遵守）。

## 一、总览

| 批次 | 范围 | 结果 | 定性 |
|---|---|---|---|
| B1 提醒族 | 8 文件（test_reminder*×4 + test_v21r2_reminder_guards + test_schedule_service_v21 + test_model_admin_and_schedule + test_subscription_scheduler_v2） | **130 passed / 0 failed**（7.04s） | [绿] 全绿 |
| B2 V2.1 契约族 | 36 文件（test_v21*.py 全量，单批） | **662 passed / 23 failed / 1 skipped / 1 xfailed**（46.95s） | [红] 23 失败全部=前端域视觉门禁 |
| B3 控制面族 | 14 文件（test_control_plane*.py 全量） | **271 passed / 0 failed**（55.44s） | [绿] 全绿 |
| B4a ruff check . | 全树 | **11 errors**（9 fixable） | [红] 全部前端域 |
| B4b doc_sync.py --check | 全量 | **PASS**（exit=0） | [绿] |
| B4c command_catalog.py --check | 全量 | **PASS**（"command catalog is current (77 topics)"） | [绿] |
| B4d verify_hashes.py --check | 全量 | **FAIL：8 项 DRIFT**（exit=1，未 --write） | [红] 前端域为主 |

三族测试合计 **1063 passed / 23 failed**；唯一红灯域=**前端（渲染/视觉门禁）**，与 WIRE-SVC/RK5/提醒三席在飞面零交集。

## 二、B1 提醒族（REM-DAWN/REM-EVE 两连修面）——全绿

合跑文件：`tests/test_reminder.py`、`tests/test_reminder_delivery.py`、`tests/test_reminder_governance_receipt.py`、`tests/test_reminder_tone.py`、`tests/test_v21r2_reminder_guards.py`、`tests/test_schedule_service_v21.py`、`tests/test_model_admin_and_schedule.py`、`tests/test_subscription_scheduler_v2.py`（后两者为 schedule 族外围）。

**130 passed / 0 failed**。明早词表修复与明晚时段语义修复（两席共改 `domains/schedule/store/reminders.py`）在测试面无红灯、无互相踩踏迹象。

## 三、B2 V2.1 契约族——23 失败全部归属前端域

36 文件单批合跑（`tests/test_v21*.py` glob 全量）。

- **其余 35 文件全绿**，关键在飞席信号：
  - `tests/test_v21_wire_svc_assembly.py`（WIRE-SVC 装配 12 例）→ passed；
  - `tests/test_v21_wiredirect_unified_path.py`（WIRE-DIRECT 结构锁）→ passed。
- **23 failed 全部集中于 `tests/test_v21r3_visual_gates.py`**（视觉门禁，前端域），逐 gate 分解：

| Gate | 失败面 | 数 |
|---|---|---|
| gate01 边框半径登记 | universal | 1 |
| gate02 漂移斑三体 | market / mermaid / finance / error | 4 |
| gate03 行高阶梯 | error | 1 |
| gate06 壳宽登记 | universal / echo_help | 2 |
| gate07 字体栈 | universal / mermaid / error / usage_report | 4 |
| gate08 表外 hex 黑名单 | universal / market / affinity / mermaid / song / finance / error / echo_help / debug_llm / usage_report / media_card | 11 |

gate08 命中的表外散值：`#157347`（旧绿）、`#b07d1a`（旧状态琥珀）、`#b42334`（旧红）、`#1a9e6c`（旧状态绿）、`#d64545`（旧状态红）——豁免白名单仅覆盖 affinity 面两枚语义色。**失败模式跨 6 个 gate、11 个卡片面，是模板/token 层系统性变更的形态，不是单点笔误。**

## 四、B3 控制面族（RK5 在修域）——全绿

14 文件合跑：`test_control_plane_actions / actions_api / events / host_guard / lifecycle / log_collectors / m1 / metrics / resources / sandbox / services / v1 / workspaces / workspaces_api`。

**271 passed / 0 failed**。RK5 三小债在修域本时点无红灯。观察项（非失败，供 RK5 参考）：5 处测试触发 fastapi `UserWarning: Duplicate Operation ID traces_api_v1_traces_get`（`plugins/bot_unified_runtime/control_plane/api/v1.py`）。

## 五、B4 门禁四件（全只读）

### 5.1 ruff check .（全树）：11 errors，全部前端域

| 文件 | 错误 | 归属 |
|---|---|---|
| `plugins/bot_unified_runtime/domains/render/card_render/mica_shell.py:191,193` | ISC004 ×2（集合内未加括号隐式串接） | 前端域（mica_shell） |
| `tests/test_mica_shell.py:11` | I001（import 块未排序） | 前端域（test_mica*） |
| `tests/test_mica_shell.py:349-353` | F541 ×5（无占位 f-string） | 前端域 |
| `tests/test_phase_determinism.py:13` | I001 | 前端域（渲染确定性测试） |
| `tests/test_rendering_contract.py:730` | B009（getattr 常量） | 前端域（渲染契约） |
| `tests/test_v21r3_visual_gates.py:245` | UP033（lru_cache→cache） | 前端域（视觉门禁） |

**零错误**落在：WIRE-SVC 域（根 `__init__`/chat_reply/character/contracts/runtime 装配面）、RK5 域（control_plane）、提醒域、RET3 域、根因不明。9 处可 `--fix`（本席未动）。

### 5.2 doc_sync.py --check：PASS（exit=0，零漂移）

### 5.3 command_catalog.py --check：PASS（77 topics 与生成物一致）

### 5.4 verify_hashes.py --check：FAIL——8 项 DRIFT（已记录，未 --write）

| 漂移文件 | 归属 |
|---|---|
| `plugins/bot_unified_runtime/domains/render/card_render/theme_tokens.py` | **前端域**。注：theme_tokens 属波内禁改清单文件，哈希证实其字节在录像后被改且未重录——**如实记录，本席未触碰** |
| `docs/rendering-contract.md` | 前端域文档 |
| `DESIGN-SPEC.md` | 前端域文档（根部设计规范） |
| `plugins/bot_unified_runtime/domains/render/card_render/bridge.py` | 前端域 |
| `plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py` | 前端域 |
| `plugins/bot_unified_runtime/domains/render/templates.py` | 前端域 |
| `plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py` | 文件域=chat_reply（WIRE-SVC 装配面邻接）；漂移根因指向 `_help_mica_html` 渲染卡面内容变更（前端域根因） |
| `plugins/bot_unified_runtime/domains/ops/admin/debug.py` | 文件域=ops；同理为 `_llm_setup_mica_html` 渲染消费方（前端域根因） |

## 六、归属定性总表（任务⑤口径）

| 域 | 测试红灯 | 门禁红灯 | 定性 |
|---|---|---|---|
| **前端域**（domains/render/**、output/card_render/**、test_mica*、test_webui_*、视觉门禁族） | 23（B2 视觉门禁） | ruff 11 + hash 漂移 8 中 6 直接归属 | **在飞未定性**——唯一破坏面，详见 §七 |
| **WIRE-SVC 域**（根__init__/chat_reply/character/contracts/runtime 装配面） | 0（assembly 12 例全绿） | echo.py 1 项 hash 漂移（文件在 chat_reply，根因=渲染面） | [绿] 测试面健康；漂移件转告 WIRE-SVC 知悉 |
| **RK5 域**（control_plane/api+test_controlplane） | 0（271 全绿） | 0 | [绿] |
| **RET3 域**（旧路径垫片/测试消费方） | 本快照三族内无垫片路径红灯；epic/steam 垫片专项测试不在本席三族范围内（范围边界，如实声明） | 0 | [绿]（范围内）/ 未覆盖（范围外） |
| **提醒族**（REM-DAWN/REM-EVE） | 0（130 全绿） | 0 | [绿] |
| **无法归属** | 无——23 失败全部可归属前端域 | 无 | — |

## 七、交叉信号与合流前风险提示

三条独立证据链聚焦**同一前端在飞变更面**（theme_tokens / mica_shell / templates / usage_cards / bridge + echo/debug 两处渲染消费方）：

1. **B2 视觉门禁 23 红**：gate01/02/03/06/07/08 跨面系统性命中（半径/漂移斑/行高/壳宽/字体栈/表外 hex），说明 token 与模板层被整体改动；
2. **verify_hashes 8 漂移**：同一文件群字节变更未重录（含波内禁改件 theme_tokens.py）；
3. **ruff 11 错**：mica_shell.py 与 test_mica_shell.py（新增文件族）本身带未清 lint。

**判定**：前端域存在一波未收口的在飞改动（很可能是语义色/主题 token 改造），其视觉门禁与哈希登记均未随改——「在飞未定性」，合流前必须由该改动归属席收口（视觉门禁逐 gate 对齐 + verify_hashes 确认后重录 + lint 清零）。**本席一律未修任何文件。**
**次级风险**：chat_reply/echo.py 与 ops/debug.py 两处渲染消费方被卷入哈希漂移，若 WIRE-SVC 后续再动装配面，合流时序上需与前端收口互斥（同文件域冲突预防）。

## 八、复跑命令（可复现证据）

```bash
# B1 提醒族（130 passed）
cd ChatBot && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_reminder.py tests/test_reminder_delivery.py tests/test_reminder_governance_receipt.py tests/test_reminder_tone.py tests/test_v21r2_reminder_guards.py tests/test_schedule_service_v21.py tests/test_model_admin_and_schedule.py tests/test_subscription_scheduler_v2.py --basetemp="$TEMP/qa-probe-b1-reminders" -p no:cacheprovider -q

# B2 V2.1 契约族（662 passed / 23 failed / 1 skipped / 1 xfailed）
... -m pytest tests/test_v21*.py --basetemp="$TEMP/qa-probe-b2-v21" -p no:cacheprovider -q

# B3 控制面族（271 passed）
... -m pytest tests/test_control_plane_actions.py tests/test_control_plane_actions_api.py tests/test_control_plane_events.py tests/test_control_plane_host_guard.py tests/test_control_plane_lifecycle.py tests/test_control_plane_log_collectors.py tests/test_control_plane_m1.py tests/test_control_plane_metrics.py tests/test_control_plane_resources.py tests/test_control_plane_sandbox.py tests/test_control_plane_services.py tests/test_control_plane_v1.py tests/test_control_plane_workspaces.py tests/test_control_plane_workspaces_api.py --basetemp="$TEMP/qa-probe-b3-cp" -p no:cacheprovider -q

# B4 门禁（只读）
... -m ruff check .
... scripts/doc_sync.py --check          # PASS
... scripts/command_catalog.py --check   # PASS (77 topics)
... tests/verify_hashes.py --check       # FAIL 8 DRIFT（禁 --write，已遵守）
```

— QA-PROBE，2026-09-19，波中时点快照（在飞中间态，非合流结论）。
