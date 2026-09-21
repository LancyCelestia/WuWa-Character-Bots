# v21r2 REPAIR-001 席日志（REP 席 · 2026-09-18）

> 任务：V21-REPAIR-001 自修复现包/RED 测试/待审补丁（不自动部署）。
> 硬约束：RWOCc 在飞迁 domains/ops+core——本席**纯新建** `plugins/bot_unified_runtime/domains/ops/repair/**` + 新测试；零编辑既有文件；禁 git 写；禁 dev.ps1。

## §0 计划（动手前落盘）

### 域定位取证
- 本工作区树内无根级 `domains/`；协调页各席所称 `domains/ops` 在本树的真身 = `plugins/bot_unified_runtime/domains/ops/`（incident/recovery/audit/admin/features/monitor/smoke/integrations 在盘实读确认）。
- `domains/ops/repair/` 不存在（ls 实证）→ 纯新增零冲突。
- RWOCc 若后续在其迁移波落根级 `domains/`，与本子包（包内路径）无文件交集。

### 交付物（纯新增清单）
1. `plugins/bot_unified_runtime/domains/ops/repair/__init__.py` — 子包 re-export（同 incident/recovery init 形态）。
2. `plugins/bot_unified_runtime/domains/ops/repair/service.py` — RepairService：
   - 输入 = RepairRequest（test_id + error_summary + target_file + 可选补丁提案列表）。
   - 两轮预算（DEFAULT_MAX_ROUNDS=2）：每轮取一个提案 → difflib 生成 unified diff（落 `pending/<ticket>/round-N.patch`）→ **沙箱验证**（不写仓库）→ 过=VERIFIED_PENDING（仍不应用）；两轮未过=ABANDONED + `diagnostic.md` + `RED-RETAINED.md`（RED 不删声明）。
   - **越权防护**：`apply_to_target()` / `deploy_patch()` 一律 raise `UnauthorizedRepairOperation` + 审计事件 `repair_unauthorized_rejected`；唯一合法出口 = `request_application()`（只读返回待审件路径供人审）。
   - **脱敏**：懒加载复用 render 真身 `redact_local_secrets`（单一事实源，同 incident/service.py `_load_redactor` 形态；失败降级本地最小正则）；用户派生文本 `redact_user_text` 只留字数痕迹。补丁待审件/诊断报告/审计事件三面全过。
   - **幂等**：ticket key = sha256(test_id|target|归一化摘要) 截断；重复提交返回既有 ticket、零新产件。
   - **目录消毒**：ticket 目录名 = test_id 消毒 slug（仅 `[A-Za-z0-9._-]`，去 `..`/分隔符/首尾点，≤48 字符）+ key 段；解析后必须居 pending 根内。
   - **审计**：RepairAuditSink Protocol（emit(dict)），缺省 LoggingRepairAuditSink（stdlib log，同 LoggingIncidentSink 形态）；可注入列表收集器。
   - 验证器注入：`RepairVerifier` Protocol；缺省 `SandboxCopyVerifier`（整树拷贝沙箱排除 .git/ChatBot_Runtime/缓存 → 沙箱内应用补丁 → 子进程 `python -m pytest <node>`，PYTHONDONTWRITEBYTECODE=1/PYTHONUTF8=1/BOT_AUTOSYNC=0/-p no:cacheprovider/--basetemp 沙箱外）；`NoopVerifier` 显式诚实（无验证器=永不判过，留人审）。
   - 目标校验：拒绝绝对路径逃逸/`..`/`.env`/ChatBot_Runtime*/ChatBot_Archive*/pending 自身。
3. `tests/test_v21_repair_service.py` — 全离线：
   - 两轮预算耗尽→ABANDONED+RED 保留件在盘（且原失败测试文件内容+mtime 不变）。
   - 补丁不落目标文件（目标文件内容+mtime_ns 双断言不变）。
   - `apply_to_target`/`deploy_patch` 越权拒绝+审计事件+目标零触碰。
   - 脱敏断言（BOT_=/sk-/盘符路径三形态在 patch 件与 diagnostic 件中被打码）。
   - 目录消毒（`../`/`::`/中文/空格 → 安全目录名且 resolve 后居 pending 根内）。
   - 幂等（同坐标二次提交：同 ticket、产件数不变、manifest 不重写）。
   - 端到端迷你仓真跑（tmp 假仓+真 venv python 子进程一轮验证通过路径）。
4. 本日志 + COORDINATION.md 追加行（开工认领一行 + 收口一行）。

### 不做（边界）
- 不实现 LLM 生成提案（提案源为可注入 generator；缺省 StaticProposalGenerator 重放调用方提案——离线确定性，纪律面归本服务，智能面留给后续席位）。
- 不接生产装配（__init__/控制面接线归后续席）；不 commit；不部署。

## §1 四列状态（REPAIR-001）

| 列 | 状态 | 证据 |
|---|---|---|
| implementation | done(high) | `plugins/bot_unified_runtime/domains/ops/repair/{__init__,service}.py` 纯新增；合同七条款全部钉死（两轮预算钳制/绝不写目标/越权拒绝+审计/脱敏三面/幂等/目录消毒/RED 保留）；mypy 本包 0 错 |
| production_wiring | not_wired | 装配（__init__/控制面接线、生产 pending_root 注入 Runtime 路径）属后续席位；本席合同=待审补丁不部署，未 commit 未部署 |
| offline_validation | done(high) | `tests/test_v21_repair_service.py` **13 passed**（2.06s，实跑）；+邻接 S14 incident/recovery 合跑 **56 passed** 零回归；ruff 本席 4 文件 All checks passed |
| live_validation | unknown | 真机验收=人工审件流程（request_application → 人审 round-N.patch → 手动应用），本席无权执行；待部署后人工演练 |

## §2 实跑证据（2026-09-18）

```
解释器固定：ChatBot_Runtime/venv/Scripts/python.exe
env：PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0
pytest --basetemp=%TEMP%/v21r2-rep -p no:cacheprovider tests/test_v21_repair_service.py
→ 13 passed in 2.06s（首跑 12 passed 1 failed——失败系测试自身未接住 run_repair
  返回的新 ticket 对象，修测试后全绿；服务零改动）
合跑邻接回归：tests/test_v21_s14_incident.py + test_v21_s14_recovery.py + 本件
→ 56 passed（邻接零干扰）
ruff check repair/ + 测试件 → All checks passed（--fix 自收 5：RUF100×3/UP037×2；
  测试件 C401 手修 1）
mypy --explicit-package-bases --ignore-missing-imports repair/ → 本包 0 错
（全跑 2 错均在 control_plane/api/platform.py:79/:254=台账 #36 既有基线，非本席）
树卫生：repair/ 下仅 2 文件，0 缓存残留；源码树无 data/ 生成；
  测试全程注入 tmp_path，默认 pending_root（源码树待审区）零写入
足迹：git status --porcelain 限定路径 → 4 个未跟踪新路径
（repair/、测试件、本日志、COORDINATION.md 追加行），既有文件零修改
```

## §3 覆盖矩阵（13 例 → 合同条款）

| 合同条款 | 测试 |
|---|---|
| 两轮预算耗尽→放弃+RED 保留（内容+mtime 双断言）+终态重跑幂等 | test_two_round_budget_exhaustion_abandons_and_preserves_red |
| 补丁不落目标文件（mtime_ns 断言） | test_patch_never_writes_target_file |
| 验证通过仍不应用（verified_pending）+request_application 只读出口 | test_verified_patch_still_pending_never_applied |
| 越权应用拒绝（apply_to_target/deploy_patch 含 force kwargs）+审计 | test_unauthorized_apply_and_deploy_rejected_and_audited |
| 脱敏（BOT_=/sk-/盘符路径/Bearer；patch+diagnostic+审计事件三面） | test_sanitization_masks_secrets_in_patch_and_diagnostic |
| 验证 detail 截断+脱敏 | test_verifier_detail_truncated_and_sanitized |
| 待审目录消毒 | test_ticket_dir_name_sanitized |
| 目标禁触/越界提交期拒绝零落盘 | test_forbidden_or_escaping_targets_rejected_before_any_write |
| 幂等（同坐标零新产件+manifest 字节不变） | test_idempotent_resubmission_no_duplicate_artifacts |
| 两轮预算钳制（max_rounds=9 → 2） | test_max_rounds_clamped_to_contract_budget |
| NoopVerifier 诚实不谎报 | test_noop_verifier_honest_no_false_pass |
| diff 纯函数往返+失配拒绝 | test_apply_unified_diff_roundtrip_and_mismatch |
| SandboxCopyVerifier 迷你仓端到端真跑（真子进程 pytest，仓库零触碰） | test_sandbox_copy_verifier_end_to_end |

## §4 设计裁定与偏差登记

1. **提案源与纪律面分离**：离线无 LLM 无法凭错误摘要凭空合成修复；缺省
   `StaticProposalGenerator` 重放调用方预置提案，智能生成面留作可注入
   `PatchGenerator`（后续席位接 LLM）。本服务钉死的是预算/待审/验证/脱敏/
   审计/幂等等纪律面——合同验收点全部在此。
2. **沙箱验证形态**：`SandboxCopyVerifier`=整树拷贝（排除 .git/Runtime/缓存）
   +沙箱内应用补丁+子进程真跑 pytest；仓库本体零触碰由测试 mtime_ns 断言
   锁死。单模块 PYTHONPATH 遮蔽方案已论证不可行（regular package 绑定后
   兄弟模块断供），故取整树拷贝。
3. **脱敏保真取舍**：落盘待审件/报告/审计一律过 `redact_local_secrets`
   真身（懒加载+本地兜底，同 incident 形态）；沙箱验证用未脱敏原文（仅存
   于内存与一次性沙箱），防打码破坏补丁可应用性。
4. **目标禁触纵深**：提交期拒绝 `.env`/`ChatBot_Runtime*`/`ChatBot_Archive*`/
   `.git`/`personas`/绝对路径/`..`/pending 自身；补丁写入唯一通道是
   `_write_ticket_file`（pending 根内原子写）。
5. **偏差**：无越域、无既有文件修改。首跑 1 红为测试自身缺陷（ticket 对象
   未重接），非服务缺陷，已修并如实记录。
6. **未做（移交）**：生产装配接线（__init__/控制面）、生产 pending_root 注入
   Runtime 路径、LLM 提案生成器接入——均属后续席位/裁决。

