# v21r4-B QA-PROBE 执行日志（断点续跑依据）

> 席位=QA-PROBE｜性质=纯只读回归快照（唯一产出=docs/design/v21r4-b-qa-probe-report.md）｜零代码改动、禁 git 写、禁子代理。
> 口径：本波多席在飞（REM-DAWN/REM-EVE/WIRE-DIRECT/RK5/WIRE-SVC），快照=时点证据「在飞中间态，非合流结论」。
> 开工时间：2026-09-19（协调表已追加 QA-PROBE 行）。

## 批次进度

- [x] B1 提醒族：**130 passed / 0 failed（7.04s）**——8 文件合跑：test_reminder.py、test_reminder_delivery.py、test_reminder_governance_receipt.py、test_reminder_tone.py、test_v21r2_reminder_guards.py、test_schedule_service_v21.py、test_model_admin_and_schedule.py、test_subscription_scheduler_v2.py（后两者为 schedule 族外围）。REM-DAWN/REM-EVE 两连修面全绿。
- [x] B2 V2.1 契约族：**662 passed / 23 failed / 1 skipped / 1 xfailed（46.95s）**——36 文件（test_v21*.py 全量单批合跑）。**失败全集中 tests/test_v21r3_visual_gates.py（23 例，前端域视觉门禁）**：gate01 边框半径登记×1（universal）、gate02 漂移斑三体×4（market/mermaid/finance/error）、gate03 行高阶梯×1（error）、gate06 壳宽登记×2（universal/echo_help）、gate07 字体栈×4（universal/mermaid/error/usage_report）、gate08 表外 hex 黑名单×11（universal/market/affinity/mermaid/song/finance/error/echo_help/debug_llm/usage_report/media_card，命中 #157347/#b07d1a/#b42334/#1a9e6c/#d64545 旧散值）。**其余 35 文件全绿，含 test_v21_wire_svc_assembly.py（WIRE-SVC）与 test_v21_wiredirect_unified_path.py（WIRE-DIRECT）**。
- [ ] B3 控制面族（test_controlplane*→实际文件名 test_control_plane*.py，14 文件）
- [x] B3 控制面族：**271 passed / 0 failed（55.44s）**——14 文件（test_control_plane*.py 全量）。RK5 在修域当前无红灯。观察项（非失败）：fastapi UserWarning——control_plane/api/v1.py 存在 Duplicate Operation ID `traces_api_v1_traces_get`（5 处测试触发）。
- [x] B4 门禁四件只读体检（全 --check/--write 禁用，未写任何文件）：
  - ruff check .（全树）：**11 errors（9 fixable），全部前端域归属**——mica_shell.py ISC004×2（191/193）、test_mica_shell.py I001×1+F541×5（349-353）、test_phase_determinism.py I001×1（13）、test_rendering_contract.py B009×1（730）、test_v21r3_visual_gates.py UP033×1（245）。零 WIRE-SVC/RK5/提醒域/根因不明。
  - doc_sync.py --check：**PASS（exit=0）**。
  - command_catalog.py --check：**PASS（"command catalog is current (77 topics)"）**。
  - verify_hashes.py --check：**FAIL（exit=1，8 项 DRIFT，未 --write）**——theme_tokens.py、rendering-contract.md、DESIGN-SPEC.md、bridge.py、ops/admin/debug.py、chat_reply/capabilities/echo.py、usage_cards.py、templates.py（逐项归属见报告）。
- [x] 交付：docs/design/v21r4-b-qa-probe-report.md 已落盘。快照性质=在飞中间态时点证据，非合流结论。
