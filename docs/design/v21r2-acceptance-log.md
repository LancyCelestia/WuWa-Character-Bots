# v21r2 ACCEPTANCE 席日志（V21-ACCEPTANCE-001·ACC 席）

> 席位：AcceptanceRunner 骨架（离线可交付部分）· 2026-09-18
> 占域：**新建** `plugins/bot_unified_runtime/domains/ops/acceptance/**` 子包 + `tests/test_v21_acceptance_runner.py`。
> 约束：RWOCc 在飞迁 ops 既有文件 → 本席**零编辑既有文件**（S14b recovery/incident/collectors 先例）；禁 git 写；不碰 Runtime；不读 .env 明文；personas 只读。

## 0. 占域与冲突声明

- `domains/ops/` 现状（实读）：admin/audit/collectors/features/incident/integrations/monitor/recovery/smoke——**无 acceptance/**，占域空闲。
- **与 PA 席重组方案 §8.3 G3 的冲突，brief 已裁决**：G3 曾标 V21-ACCEPTANCE-001/002「域外+无载体，二选一落 ops/smoke 或未来 acceptance 域，待用户裁决，本期不预设」。本席 brief 明确指定新建 `domains/ops/acceptance/` 独立子包（既不挤 smoke 也不混 recovery），按用户指令执行，此为对该开放项的单点裁决记录；矩阵行 L73 状态更新留主会话（本席不编辑既有文档）。

## 1. 合同锚点（实施前摘录）

- 扩展 §8.1：`AcceptanceAuthorization(id, principal, allowed_targets, allowed_scenarios, provider_allowlist, currency_budgets, max_requests, max_assets, valid_from/to, maintenance_actions, data_scope, revoke_version)`；**默认拒绝未列动作**；摘要可审计、绑定 run。
- 扩展 §8.2：Runner 串行执行注册 Scenario、禁扫联系人；层级 L0-L4 单独记录；**blocked/skipped/unknown 不得算 pass**；预算耗尽/授权过期撤销后不再新调用；取消保留已计费 attempt；重启续跑不重发成功 part；不把 fake 结果混入 live。
- 验收矩阵 L73：现状 partial（scripts/e2e_acceptance.py 手工触发）；本席交付 Runner 骨架的 implementation+offline 两列，production_wiring/live 不越权宣称。
- 本轮合同：**真实出站不接**——transport 全 mock 注入；真实 transport 留接口（`NotWiredTransport`→诚实 `not_wired`）；`live_validation=unknown`。

## 2. 验收标准（AC，动手前钉死）

| # | AC | 验证 |
|---|---|---|
| A1 | 无授权包 → 拒绝启动（抛 `AuthorizationRequired`，零步执行） | 单测 |
| A2 | 授权包字段齐：收件人/目标白名单/场景白名单/provider 白名单/金额+调用预算/时间窗/撤销（合同 §8.1 字段对齐含 max_assets/data_scope/revoke_version） | DTO 断言 |
| A3 | 默认拒绝：目标白名单空=禁一切发送；场景白名单空=禁一切场景；provider 白名单空=禁一切带 provider 调用；未列目标/provider → 步 `rejected_not_authorized` + run 停 | 单测 |
| A4 | 预算硬闸：调用次数超限或币种金额超限（含单项上限）→ 该步 `rejected_budget` 拒执行、run `budget_exhausted` 停、后续 skipped | 单测 |
| A5 | 时间窗闸：窗前/窗后/中途越窗 → `window_closed` 停，未跑步 skipped（clock 注入离线确定） | 单测 |
| A6 | 撤销：令牌置位 → **在途步骤完成后**停止（串行引擎=当前步跑完，不强杀已发出），后续不再分发；已计费 attempt 保留 | 单测（撤销发生在 mock deliver 内部） |
| A7 | 授权预置 revoked=True → 启动即 blocked `revoked` 零分发 | 单测 |
| A8 | mock transport 全流程：CALL→receipt accepted→ASSERT→PASSED；trace_id/receipt_id 关联到步与报告；预算如实扣减 | 单测 |
| A9 | 幂等：transport 按 idempotency_key 去重（duplicated=True、真实发送数不增）；同 run_id 重跑 → 返回缓存报告零重发 | 单测 |
| A10 | 报告脱敏：secret 形键→`***`；sk-/Bearer/BOT_X= 形值→打码（render 真身懒加载+本地兜底，incident 同构）；错误文本脱敏 | 单测 |
| A11 | not_wired 诚实：`NotWiredTransport` → 步 `not_wired`、run blocked `not_wired`，绝不伪称通过 | 单测 |
| A12 | 失败停：断言失败/脚本化失败 → `step_failed` 停、剩余 skipped；blocked/skipped 不算 pass（RunStatus 三态 passed/failed/blocked） | 单测 |
| A13 | 2-3 个离线示例场景演示引擎能力 | scenarios.py + 单测 |

## 3. 设计（骨架边界）

- **分层**（合同 §8.2 口径，报告逐 run 记录 `level`）：示例场景全为 L0（纯函数/预算闸演练）与 L1（本地 fake transport）；L2-L4 不在本轮。
- **串行引擎**：步依序执行；每步前过五道边界闸（撤销→时间窗→目标/provider 授权→预算）；CALL 经注入 transport，ASSERT 本地求值零成本零出站。
- **预算**：`BudgetLedger`（max_requests + 按币种 Decimal 金额 + per_call_max 单项上限）；**成本在真实 attempt 发生即扣**（失败/拒绝回执也计，合同「每真实 attempt 采集」「取消保留已计费 attempt」）；`TransportNotWired` 例外=未发生 attempt 不扣。
- **撤销**：`RevocationToken` 运行时句柄（可变）+ `AuthorizationPackage.revoked/revoke_version` 预置位；引擎只在分发边界检查，**绝不中断在途步**。
- **幂等**：transport 层按 `idempotency_key` 去重（mock 返回 `duplicated=True`）；runner 层同 `run_id` 重跑返回缓存报告（内存级；SQLite 持久化与「重启续跑不重发成功 part」属后续接线席，诚实登记）。
- **脱敏**：报告内 payload/detail/error 全走 `redact_mapping`/`redact_text`；render 真身 `redact_local_secrets` 懒加载失败→本地兜底正则（incident/service.py 同构，不跨席依赖）。
- **依赖隔离**：仅 stdlib + 惰性 render 真身；不 import incident/recovery（S14b 在飞域零耦合）；不新增 config 键（阈值全构造参数，recovery 先例）。
- **真实 transport**：`NotWiredTransport.deliver` 抛 `TransportNotWired` → 引擎诚实标 `not_wired`；`AcceptanceTransport` Protocol 即接线席的注入面。

## 4. 交付物（全新增）

| 文件 | 内容 |
|---|---|
| `plugins/bot_unified_runtime/domains/ops/acceptance/__init__.py` | 导出面 |
| `plugins/bot_unified_runtime/domains/ops/acceptance/runner.py` | DTO（AuthorizationPackage/ScenarioPlan/ScenarioStep）+ 引擎（AcceptanceRunner）+ transport Protocol + Mock/NotWired + 预算账 + 脱敏 |
| `plugins/bot_unified_runtime/domains/ops/acceptance/scenarios.py` | 3 个离线示例场景 + 断言工厂 + 场景注册表 |
| `tests/test_v21_acceptance_runner.py` | A1-A13 全离线单测（clock/transport/revocation 全注入） |

## 5. 直跑命令（固定口径）

```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
"C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" \
-m pytest tests/test_v21_acceptance_runner.py --basetemp="$TEMP/v21r2-acc" -p no:cacheprovider -q
```

## 6. 四列（ACCEPTANCE-001）

| 列 | 状态 | 依据 |
|---|---|---|
| implementation | **done(high)**（in-seat tested） | runner.py 引擎+DTO+传输协议 / scenarios.py 3 场景 / 28 例全绿 |
| production_wiring | **not_wired** | 装配/控制面 REST（§8.2 `/acceptance/*` 五端点）/报告持久化属后续接线席；`NotWiredTransport` 诚实占位 |
| offline_validation | **done(high)** | 28 passed（实跑证据见 §7） |
| live_validation | **unknown** | 本轮合同禁真实出站，transport 全 mock；如实不宣称 |

---

## 7. 执行记录（实跑证据）

### 7.1 交付物（全部全新增，`git status --porcelain` 实证仅 `??` 未跟踪项）

- `plugins/bot_unified_runtime/domains/ops/acceptance/__init__.py`（导出面）
- `plugins/bot_unified_runtime/domains/ops/acceptance/runner.py`（约 1100 行：AuthorizationPackage（合同 §8.1 字段一一落位）/RevocationToken/ScenarioPlan/ScenarioStep/StepKind|StepStatus|StopReason|RunStatus 四枚举/AcceptanceTransport Protocol/MockAcceptanceTransport（幂等键去重+脚本化失败+on_deliver 钩子）/NotWiredTransport/BudgetLedger（次数+按币种 Decimal+单项上限；attempt 发生即记账）/结构化脱敏（render 真身懒加载+本地兜底，incident 同构不跨席依赖）/AcceptanceRunner（五道边界闸：撤销→时间窗→目标授权→provider 授权→预算；串行；同 run_id 幂等缓存）/RunReport（逐步状态+预算快照+trace 关联+build_id/manifest_revision 透传+to_summary 摘要）
- `plugins/bot_unified_runtime/domains/ops/acceptance/scenarios.py`（3 场景+5 断言工厂+注册表：send_queue_roundtrip_mock（L1 往返+幂等重投）/divination_rest_idempotent（L1 同键同回执）/overbudget_drill（L0 设计性拒绝路径演练））
- `tests/test_v21_acceptance_runner.py`（28 例，§2 A1-A13 全覆盖）

### 7.2 实跑证据（解释器固定口径：ChatBot_Runtime venv python，PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0，--basetemp=%TEMP%/v21r2-acc -p no:cacheprovider）

```
pytest tests/test_v21_acceptance_runner.py
  → 28 passed in 1.34s
pytest tests/test_v21_acceptance_runner.py tests/test_v21_s14_recovery.py tests/test_v21_s14_incident.py
  → 71 passed in 1.51s（邻域 S14 零扰动）
ruff check plugins/.../ops/acceptance/ tests/test_v21_acceptance_runner.py
  → All checks passed!（首跑 9 错：UP035/RUF022/SIM103/UP037×3/RUF100/ISC004/FURB157，手修+--fix 后清零）
mypy --explicit-package-bases --ignore-missing-imports <acceptance 包+测试件>
  → Found 2 errors in 1 file = control_plane/api/platform.py:79/:254（台账 #36 既有基线），本席 4 文件 0 错
```

AC 对照：A1-A13 全部有对应通过用例（TestStartGates×6 / TestBudgetGate×5 / TestWindowGate×4 / TestRevocation×3 / TestMockTransportFlow×4 / TestRedaction×3 / TestHonestyPaths×3）。

### 7.3 诚实台账

- **mypy/ruff 检查曾在根目录落 `.mypy_cache`/`.ruff_cache`**：已用 venv python shutil 清除（本 shell 无 rm 命令，shutil 实证 remaining=[]）；尝试备份到 %TEMP/v21r2-acc-hygiene-20260918-063454 但 cp 静默失败、目录为空——**所删内容仅可再生 lint 缓存，无任何运行数据损失**，如实记录。
- acceptance 子包自身零 `__pycache__`/零 `.pyc`/零 data/ 写入（PYTHONDONTWRITEBYTECODE=1 + 纯内存引擎，find 实证 0）。
- 首轮实跑 2 红（`test_unlisted_provider_rejected`=测试自身场景 id 未入授权白名单先被场景闸拦；`test_scenario_registry`=frozen dataclass 等值含新建断言闭包按身份不等）——均测试缺陷非引擎缺陷，修正后全绿。
- 引擎首版漏闸一处自查自纠：NOT_WIRED 未纳入终局停机条件（会继续跑后续步致 stop_reason 失真），已修并有 `test_not_wired_transport_honest` 回归锁。

### 7.4 冲突/偏差/遗留

- **PA 席重组方案 §8.3 G3 裁决记录**：G3 曾标 ACCEPTANCE-001/002「域外+无载体待裁决」；本席 brief 明确指定新建 `domains/ops/acceptance/` 独立子包，按用户指令执行（见 §0）。
- **零编辑既有文件约束达成**：本席全部落盘为新增文件 + 本日志 + COORDINATION.md 追加一行（brief 点名要求）；`git status --porcelain` 实证 acceptance 相关仅 `??` 未跟踪项，无既有文件修改。
- 未 commit（禁 git 写，提交裁决权在用户）；未部署。
- **遗留（属后续席位，接口面已留）**：①真实 transport 实现 AcceptanceTransport 协议注入（本轮 mock-only，live_validation=unknown）；②控制面 REST `/acceptance/scenarios|runs` 五端点与 SSE（合同 §8.2）；③报告/资产 SQLite 持久化与「重启续跑不重发成功 part」（当前 run 注册表为内存级，同 run_id 幂等已锁）；④场景重试 attempt 历史保留；⑤L2-L4 场景；⑥验收矩阵 L73 行状态更新（本席不编辑既有文档，留主会话）。
