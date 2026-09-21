# V2.1 S0 基线实测报告（A2 重派实例）

- 席位：A2（前一实例限流阵亡、无落盘；本实例从头执行）
- 工作区：`c:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`
- 基线 HEAD：`56d1461305e0dc8443c777f2eeb06d2f39da3ac9`
- 快照采集时刻：2026-09-17 03:03:57 +0800
- 实测纪律：禁用 scripts/dev.ps1；`BOT_AUTOSYNC=0`；`PYTHONDONTWRITEBYTECODE=1`；`PYTHONUTF8=1`；解释器固定 `C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe`；pytest `--basetemp` 置于 `%TEMP%` 专属目录 + `-p no:cacheprovider`；ruff `--no-cache`；mypy `--cache-dir` 置 `%TEMP%`——全部不写源码树缓存、不动 ChatBot_Runtime（venv 解释器调用除外）。
- **并发条件（解读结果前必读）**：本基线采集期间 A3（改 scripts/dev.ps1 + tests/conftest.py）、A4（改 character/affinity.py 与好感度测试）、A5（新增 tests/test_v21_risk_red_*.py）、A7（新增 plugins/bot_unified_runtime/supervisor/ 与测试）、A8（新增 contracts/ 子模块与测试）五个代理并行在飞。开始时快照已见部分在飞产物为 untracked：tests/test_affinity_v21.py、tests/test_affinity_v21_budget.py、tests/test_supervisor_isolation.py、tests/test_contracts_v21.py 等。pytest 启动收集完成后不受后续编辑影响；收集前/收集中途落盘的新文件可能进入或错过本轮收集，可能导致个别失败为"半成品文件被收集"的并发噪声。

## 环境快照（实跑）

| 项 | 版本 |
|---|---|
| Python | 3.12.10 |
| pytest | 9.1.1 |
| ruff | 0.16.4 |
| mypy | 2.3.1 (compiled: yes) |

## 步骤1 生成物哈希基线（只读 sha256sum 实跑，开始时）

| 文件 | SHA-256（开始时） | SHA-256（跑后复核） | 漂移 |
|---|---|---|---|
| tests/render_hashes.json | `62338fa57930f931dfb1ff2d66336c5cbc89ddffec7c4646ea1dfb54ce1bbdb7` | `62338fa57930f931dfb1ff2d66336c5cbc89ddffec7c4646ea1dfb54ce1bbdb7` | 无 |
| docs/command-catalog.md | `23f650138f0a0ec23c4be764158c82eee164efc575c500b75196f04e5aaa9c0a` | `23f650138f0a0ec23c4be764158c82eee164efc575c500b75196f04e5aaa9c0a` | 无 |
| docs/auto-facts.md | `280ef15576f4e13c2a3622994438b95b2f76aa74f6d9267c1d1e0222fd700634` | `280ef15576f4e13c2a3622994438b95b2f76aa74f6d9267c1d1e0222fd700634` | 无 |
| COMMANDS.md | `c6fab2bfa13127a77622c1fd32ffc487693c3c599a56860551fe9e0400bc185f` | `c6fab2bfa13127a77622c1fd32ffc487693c3c599a56860551fe9e0400bc185f` | 无 |
| docs/route-matrix.md | `a92f69e7ea24e33e363c73d81388eb53148989df1fef23b18745a73ceb3c0906` | `a92f69e7ea24e33e363c73d81388eb53148989df1fef23b18745a73ceb3c0906` | 无 |

命令（实跑）：
```
for f in tests/render_hashes.json docs/command-catalog.md docs/auto-facts.md COMMANDS.md docs/route-matrix.md; do if [ -f "$f" ]; then sha256sum "$f"; else echo "MISSING $f"; fi; done
```
退出码 0，5 文件全部存在。

## 步骤2 git status 快照（2026-09-17 03:03:57 +0800，HEAD 56d1461305e0dc8443c777f2eeb06d2f39da3ac9）

`git status --porcelain` 逐字（M=已跟踪改动，??=未跟踪）：

```
 M .env.example
 M AGENTS.md
 M COMMANDS.md
 M HANDOFF-NEXT.md
 M bot.py
 M docs/HANDBOOK.md
 M docs/HANDOVER-2026-09-15.md
 M docs/README.md
 M docs/acceptance-manual.md
 M docs/auto-facts.md
 M docs/command-catalog.md
 M docs/config-catalog-full.md
 M docs/db-owners.md
 M plugins/bot_unified_runtime/__init__.py
 M plugins/bot_unified_runtime/capabilities/chat.py
 M plugins/bot_unified_runtime/capabilities/divination.py
 M plugins/bot_unified_runtime/capabilities/echo.py
 M plugins/bot_unified_runtime/capabilities/poke.py
 M plugins/bot_unified_runtime/capabilities/runtime_admin.py
 M plugins/bot_unified_runtime/character/affinity.py
 M plugins/bot_unified_runtime/character/glossary.py
 M plugins/bot_unified_runtime/config.py
 M plugins/bot_unified_runtime/contracts/runtime.py
 M plugins/bot_unified_runtime/control_plane/__init__.py
 M plugins/bot_unified_runtime/control_plane/_app.py
 M plugins/bot_unified_runtime/llm/channel_health.py
 M plugins/bot_unified_runtime/llm/model_router.py
 M plugins/bot_unified_runtime/output/renderer.py
 M plugins/bot_unified_runtime/runtime/aliases.py
 M plugins/bot_unified_runtime/runtime/capability_registry.py
 M plugins/bot_unified_runtime/runtime/error_report.py
 M plugins/bot_unified_runtime/runtime/model_schedule.py
 M plugins/bot_unified_runtime/runtime/pipeline.py
 M plugins/bot_unified_runtime/runtime/reactions.py
 M plugins/bot_unified_runtime/runtime/settings.py
 M plugins/bot_unified_runtime/runtime/usage_monitor.py
 M plugins/bot_unified_runtime/sender/onebot.py
 M plugins/bot_unified_runtime/sender/worker.py
 M plugins/bot_unified_runtime/sources/file_reader.py
 M plugins/bot_unified_runtime/sources/meme_library_listener.py
 M plugins/bot_unified_runtime/sources/subscription_runtime_v2.py
 M scripts/dev.ps1
 M tests/conftest.py
 M tests/render_hashes.json
 M tests/test_a18_gate_idempotency_rollback.py
 M tests/test_affinity.py
 M tests/test_affinity_numerical.py
 M tests/test_affinity_query.py
 M tests/test_auditfix_llm_route.py
 M tests/test_autosync_hook.py
 M tests/test_capability_registry.py
 M tests/test_datafix_runtime_paths.py
 M tests/test_deadline_budget.py
 M tests/test_e2e_acceptance.py
 M tests/test_error_card_async.py
 M tests/test_error_report.py
 M tests/test_glossary_seed.py
 M tests/test_help_deep_teaching_n2re.py
 M tests/test_persona_prompt_and_memory.py
 M tests/test_pipeline_review_fixes.py
 M tests/test_trigger_bidirectional_gate.py
 M "审查结论与重构计划.md"
?? .cp-test-output.txt
?? .zcode/
?? docs/design/COMPACT-CHECKPOINT.md
?? docs/design/backend-v2-acceptance-matrix.md
?? docs/design/backend-v2-implementation-guide.md
?? docs/design/backend-v2-product-extensions.md
?? docs/design/control-plane-core-status.md
?? docs/design/control-plane-events.md
?? docs/design/control-plane-metrics.md
?? docs/design/control-plane-registry.md
?? docs/design/control-plane-services.md
?? docs/design/control-plane-workspaces.md
?? docs/design/v21-affinity-fix-log.md
?? docs/design/v21-autosync-fix-log.md
?? docs/design/v21-s0-inventory.md
?? "docs/核心要求.md"
?? findings.md
?? plugins/bot_unified_runtime/capabilities/campus.py
?? plugins/bot_unified_runtime/capabilities/feature_control.py
?? plugins/bot_unified_runtime/control_plane/actions.py
?? plugins/bot_unified_runtime/control_plane/api/actions.py
?? plugins/bot_unified_runtime/control_plane/api/events.py
?? plugins/bot_unified_runtime/control_plane/api/llm.py
?? plugins/bot_unified_runtime/control_plane/api/platform.py
?? plugins/bot_unified_runtime/control_plane/api/protocol.py
?? plugins/bot_unified_runtime/control_plane/api/v1.py
?? plugins/bot_unified_runtime/control_plane/api/workspaces.py
?? plugins/bot_unified_runtime/control_plane/config_service.py
?? plugins/bot_unified_runtime/control_plane/config_store.py
?? plugins/bot_unified_runtime/control_plane/dispatcher.py
?? plugins/bot_unified_runtime/control_plane/events.py
?? plugins/bot_unified_runtime/control_plane/factory.py
?? plugins/bot_unified_runtime/control_plane/features.py
?? plugins/bot_unified_runtime/control_plane/file_access.py
?? plugins/bot_unified_runtime/control_plane/lifecycle.py
?? plugins/bot_unified_runtime/control_plane/log_collectors.py
?? plugins/bot_unified_runtime/control_plane/metrics.py
?? plugins/bot_unified_runtime/control_plane/platform.py
?? plugins/bot_unified_runtime/control_plane/resources.py
?? plugins/bot_unified_runtime/control_plane/sandbox.py
?? plugins/bot_unified_runtime/control_plane/services.py
?? plugins/bot_unified_runtime/control_plane/sqlite_features.py
?? plugins/bot_unified_runtime/control_plane/workspaces.py
?? plugins/bot_unified_runtime/llm/usage_service.py
?? plugins/bot_unified_runtime/runtime/content_route.py
?? plugins/bot_unified_runtime/runtime/feature_catalog.py
?? plugins/bot_unified_runtime/runtime/feature_gate.py
?? plugins/bot_unified_runtime/sources/campus_store.py
?? plugins/bot_unified_runtime/sources/draw_store.py
?? plugins/bot_unified_runtime/sources/reaction_store.py
?? plugins/bot_unified_runtime/sources/search_service.py
?? plugins/bot_unified_runtime/supervisor/
?? progress.md
?? scripts/telegram_resilience.py
?? task_plan.md
?? tests/_autosync_fixture.py
?? tests/test_affinity_v21.py
?? tests/test_affinity_v21_budget.py
?? tests/test_autosync_gate.py
?? tests/test_campus_digest.py
?? tests/test_config_control_service.py
?? tests/test_content_route.py
?? tests/test_contracts_v21.py
?? tests/test_control_plane_actions.py
?? tests/test_control_plane_actions_api.py
?? tests/test_control_plane_events.py
?? tests/test_control_plane_lifecycle.py
?? tests/test_control_plane_log_collectors.py
?? tests/test_control_plane_metrics.py
?? tests/test_control_plane_resources.py
?? tests/test_control_plane_sandbox.py
?? tests/test_control_plane_services.py
?? tests/test_control_plane_v1.py
?? tests/test_control_plane_workspaces.py
?? tests/test_control_plane_workspaces_api.py
?? tests/test_divination_service_v21.py
?? tests/test_feature_store_integrity.py
?? tests/test_glossary_recall.py
?? tests/test_media_rejection_retry_and_fallback.py
?? tests/test_poke_notice_ingest.py
?? tests/test_poke_v2.py
?? tests/test_reaction_store.py
?? tests/test_runtime_feature_gate.py
?? tests/test_runtime_subfeatures.py
?? tests/test_search_service_v21.py
?? tests/test_sqlite_feature_store.py
?? tests/test_supervisor_isolation.py
?? tests/test_telegram_resilience.py
?? tests/test_usage_billing_v21.py
```

## 步骤3 全量 pytest 直跑（V2.1 口径：验收禁 autosync）

命令（实跑，工作区根目录）：
```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" -B -m pytest tests -q --basetemp="C:/Users/LancyCelestia/AppData/Local/Temp/v21-baseline-pytest" -p no:cacheprovider
```

结果：**一次跑完，未截断、未触发降级补跑**。PYTEST_START 2026-09-17 03:06:33 → PYTEST_END 2026-09-17 03:10:48，墙钟 252.80s（0:04:12），远低于 25 分钟截断线；`--basetemp` 正常工作，未出现 WinError 5（无需 `-p no:tmpdir` 重试）。

退出码：**1**

官方汇总行（逐字）：
```
41 failed, 7050 passed, 9 skipped, 3 xfailed, 1 warning, 28 errors in 252.80s (0:04:12)
```
（收集合计 7131 = 7050 passed + 41 failed + 28 errors + 9 skipped + 3 xfailed。）

### 失败全列表（short test summary 逐字，41 FAILED + 28 ERROR）

```
FAILED tests/test_affinity_v21_budget.py::test_duplicate_source_event_id_returns_existing_result
FAILED tests/test_affinity_v21_budget.py::test_duplicate_source_event_id_via_observe_is_idempotent
FAILED tests/test_affinity_v21_budget.py::test_interaction_cooldown_zeroes_rapid_repeat_scores
FAILED tests/test_affinity_v21_budget.py::test_budget_isolated_across_bots_for_same_principal
FAILED tests/test_affinity_v21_budget.py::test_gain_budget_isolated_across_bots
FAILED tests/test_affinity_v21_budget.py::test_absence_does_not_decay_score_by_default
FAILED tests/test_affinity_v21_budget.py::test_poke_gain_defaults_match_spec
FAILED tests/test_channel_health_v2.py::test_adaptive_timeout_tightens_by_ema[1000-expected0]
FAILED tests/test_control_plane_host_guard.py::test_whitelisted_hosts_pass
FAILED tests/test_control_plane_host_guard.py::test_host_case_insensitive
FAILED tests/test_control_plane_host_guard.py::test_foreign_host_rejected_400
FAILED tests/test_control_plane_host_guard.py::test_rebinding_bypass_blocked_even_with_valid_token
FAILED tests/test_control_plane_host_guard.py::test_host_without_port_rejected
FAILED tests/test_control_plane_host_guard.py::test_multiple_host_headers_rejected
FAILED tests/test_control_plane_host_guard.py::test_malformed_host_forms_rejected
FAILED tests/test_control_plane_host_guard.py::test_host_port_normalized_as_integer
FAILED tests/test_control_plane_host_guard.py::test_bearer_flow_unaffected_by_guard
FAILED tests/test_control_plane_host_guard.py::test_allowlist_extended_via_config
FAILED tests/test_control_plane_host_guard.py::test_allowlist_extended_via_env
FAILED tests/test_control_plane_host_guard.py::test_port_follows_settings_not_hardcoded
FAILED tests/test_control_plane_host_guard.py::test_invalid_allowlist_entries_fail_closed
FAILED tests/test_control_plane_host_guard.py::test_rejected_host_audited_with_400
FAILED tests/test_control_plane_log_collectors.py::test_app_lifespan_advertises_real_collector_status[True]
FAILED tests/test_control_plane_log_collectors.py::test_app_lifespan_advertises_real_collector_status[False]
FAILED tests/test_control_plane_m1.py::test_healthz_is_constant_no_auth
FAILED tests/test_control_plane_m1.py::test_api_503_when_token_not_provisioned
FAILED tests/test_control_plane_m1.py::test_bearer_token_flow
FAILED tests/test_control_plane_m1.py::test_failure_rate_limit_429_with_retry_after
FAILED tests/test_control_plane_m1.py::test_status_models_projection_masks_secrets
FAILED tests/test_control_plane_m1.py::test_status_models_store_failure_maps_to_503
FAILED tests/test_control_plane_m1.py::test_status_bot_fields
FAILED tests/test_control_plane_m1.py::test_audit_rows_written_and_query_redacted
FAILED tests/test_control_plane_m1.py::test_host_guard_rejects_testserver_default_host
FAILED tests/test_control_plane_resources.py::test_api_uses_shared_resource_service_and_declares_protocol
FAILED tests/test_control_plane_services.py::test_distinct_admin_tokens_are_required
FAILED tests/test_control_plane_v1.py::test_control_plane_v1_uses_common_envelope_and_super_admin_write
FAILED tests/test_control_plane_v1.py::test_control_plane_v1_config_preview_and_allowlisted_write
FAILED tests/test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync
FAILED tests/test_runtime_feature_gate.py::test_api_sqlite_change_controls_separate_runtime_instance
FAILED tests/test_runtime_feature_gate.py::test_app_mounts_event_service_and_shared_error_protocol
FAILED tests/test_runtime_feature_gate.py::test_config_api_and_command_share_live_consumers
ERROR tests/test_control_plane_actions_api.py::test_catalog_and_manifest_reflect_injected_service
ERROR tests/test_control_plane_actions_api.py::test_static_runs_route_is_not_shadowed
ERROR tests/test_control_plane_actions_api.py::test_confirmation_conflict_status_and_success_idempotency
ERROR tests/test_control_plane_actions_api.py::test_unconfirmed_low_risk_action_and_unknown_action
ERROR tests/test_control_plane_actions_api.py::test_readers_cannot_mutate_actions[preview]
ERROR tests/test_control_plane_actions_api.py::test_readers_cannot_mutate_actions[execute]
ERROR tests/test_control_plane_actions_api.py::test_strict_payloads_and_cancel_does_not_ignore_parameters
ERROR tests/test_control_plane_services.py::test_v1_envelope_and_request_id[/api/v1/features-reader-200]
ERROR tests/test_control_plane_services.py::test_v1_envelope_and_request_id[/api/v1/features-writer-200]
ERROR tests/test_control_plane_services.py::test_v1_envelope_and_request_id[/api/v1/features/does-not-exist-reader-404]
ERROR tests/test_control_plane_services.py::test_v1_envelope_and_request_id[/api/v1/features-invalid-401]
ERROR tests/test_control_plane_services.py::test_v1_envelope_and_request_id[/api/v1/does-not-exist-reader-404]
ERROR tests/test_control_plane_services.py::test_invalid_mutation_is_rejected_and_not_echoed[payload0]
ERROR tests/test_control_plane_services.py::test_invalid_mutation_is_rejected_and_not_echoed[payload1]
ERROR tests/test_control_plane_services.py::test_invalid_mutation_is_rejected_and_not_echoed[payload2]
ERROR tests/test_control_plane_services.py::test_invalid_mutation_is_rejected_and_not_echoed[payload3]
ERROR tests/test_control_plane_services.py::test_invalid_mutation_is_rejected_and_not_echoed[payload4]
ERROR tests/test_control_plane_services.py::test_reset_preserves_conflict_detection
ERROR tests/test_control_plane_services.py::test_preview_does_not_mutate
ERROR tests/test_control_plane_services.py::test_schema_is_authenticated_and_static_route_is_not_shadowed
ERROR tests/test_control_plane_services.py::test_unimplemented_workspace_does_not_claim_creation
ERROR tests/test_control_plane_services.py::test_v1_host_guard_and_method_errors_use_envelope
ERROR tests/test_control_plane_services.py::test_v1_mutation_audit_has_actor_and_same_request_id
ERROR tests/test_control_plane_services.py::test_openapi_declares_bearer_and_strict_feature_mutation
ERROR tests/test_control_plane_services.py::test_feature_openapi_includes_typed_response_contract
ERROR tests/test_control_plane_services.py::test_protocol_discovery_does_not_advertise_unimplemented_services
ERROR tests/test_control_plane_workspaces_api.py::test_sandbox_http_flow_and_schema
ERROR tests/test_control_plane_workspaces_api.py::test_workspace_http_permissions_and_validation
```
（注：日志中另有一行 `ERROR    plugins.bot_unified_runtime.control_plane._app:_app.py:276 control plane requires distinct read and super-admin tokens; writes disabled` 是运行期日志记录非测试错误，不计入 28 errors。）

关键栈证据（逐字摘录）：控制面 ERROR 族的 setup 阶段实锚——
```
plugins\bot_unified_runtime\control_plane\_app.py:425: UnboundLocalError
..\ChatBot_Runtime\venv\Lib\site-packages\fastapi\utils.py:75: FastAPIError
```
A4 域样例（test_poke_gain_defaults_match_spec）：
```
>       assert float(config.bot_poke_affinity_delta) == 0.1, "规格 §2.3 poke_gain_points=0.1 分"
```
doc_sync 门（test_doc_sync_auto_facts_in_sync）：`scripts/doc_sync.py --check` 返回非零（docs/auto-facts.md 在工作树为 M 状态，属并行文档编辑与机器事实册门禁漂移）。

## 步骤4 ruff check（实跑完成）

命令（实跑，工作区根目录；dev.ps1 同口径为 `ruff check --cache-dir <Runtime>\cache\ruff .`，本席改用 `--no-cache` 避免写任何缓存，目标同样为 `.`）：
```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" -B -m ruff check --no-cache --output-format=concise .
```
退出码：**1**。汇总（逐字）：`Found 26 errors.` / `[*] 18 fixable with the --fix option (3 hidden fixes can be enabled with the --unsafe-fixes option).`

失败全列表（concise 输出逐字）：
```
plugins\bot_unified_runtime\supervisor\acl_windows.py:21:11: RUF022 [*] `__all__` is not sorted
plugins\bot_unified_runtime\supervisor\acl_windows.py:142:33: UP037 [*] Remove quotes from type annotation
plugins\bot_unified_runtime\supervisor\acl_windows.py:239:12: PLW1510 `subprocess.run` without explicit `check` argument
plugins\bot_unified_runtime\supervisor\appcontainer_windows.py:26:11: RUF022 [*] `__all__` is not sorted
plugins\bot_unified_runtime\supervisor\appcontainer_windows.py:304:5: I001 [*] Import block is un-sorted or un-formatted
plugins\bot_unified_runtime\supervisor\appcontainer_windows.py:304:51: F401 [*] `.job_objects.SECURITY_ATTRIBUTES` imported but unused
plugins\bot_unified_runtime\supervisor\appcontainer_windows.py:304:86: F401 [*] `.job_objects.STARTF_USESTDHANDLES` imported but unused
plugins\bot_unified_runtime\supervisor\job_objects.py:26:11: RUF022 [*] `__all__` is not sorted
plugins\bot_unified_runtime\supervisor\job_objects.py:366:40: UP037 [*] Remove quotes from type annotation
plugins\bot_unified_runtime\supervisor\job_objects.py:374:35: UP037 [*] Remove quotes from type annotation
plugins\bot_unified_runtime\supervisor\job_objects.py:386:41: UP037 [*] Remove quotes from type annotation
plugins\bot_unified_runtime\supervisor\job_objects.py:429:9: PYI034 `__enter__` methods in classes like `JobObject` usually return `self` at runtime
plugins\bot_unified_runtime\supervisor\job_objects.py:429:28: UP037 [*] Remove quotes from type annotation
plugins\bot_unified_runtime\supervisor\sandbox_windows.py:22:1: I001 [*] Import block is un-sorted or un-formatted
plugins\bot_unified_runtime\supervisor\sandbox_windows.py:27:1: UP035 [*] Import from `collections.abc` instead: `Iterator`
plugins\bot_unified_runtime\supervisor\sandbox_windows.py:37:5: F401 [*] `.job_objects.current_process_handle_count` imported but unused
plugins\bot_unified_runtime\supervisor\sandbox_windows.py:38:5: F401 [*] `.job_objects.process_alive` imported but unused
plugins\bot_unified_runtime\supervisor\sandbox_windows.py:42:11: RUF022 [*] `__all__` is not sorted
tests\test_affinity_v21_budget.py:15:1: I001 [*] Import block is un-sorted or un-formatted
tests\test_affinity_v21_budget.py:18:8: F401 [*] `time` imported but unused
tests\test_affinity_v21_budget.py:97:5: F841 Local variable `db` is assigned to but never used
tests\test_contracts_v21.py:201:16: PLW1510 `subprocess.run` without explicit `check` argument
tests\test_contracts_v21.py:364:30: PERF102 When using only the values of a dict use the `values()` method
tests\test_contracts_v21.py:498:30: DTZ001 `datetime.datetime()` called without a `tzinfo` argument
tests\test_contracts_v21.py:593:27: DTZ001 `datetime.datetime()` called without a `tzinfo` argument
tests\test_contracts_v21.py:594:28: DTZ001 `datetime.datetime()` called without a `tzinfo` argument
```
初步归属：**26/26 全部落在在飞并行域**——A7 supervisor/ 18 条、A4 tests/test_affinity_v21_budget.py 3 条、A8 tests/test_contracts_v21.py 5 条。

## 步骤5 mypy（实跑完成，28 秒）

命令（实跑；与 dev.ps1 typecheck 同口径 `python -m mypy --cache-dir <Runtime>\cache\mypy --explicit-package-bases --ignore-missing-imports plugins`，仅 cache-dir 改置 %TEMP%；pyproject.toml 无 [tool.mypy] 段，配置口径=dev.ps1 显式参数）：
```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" -B -m mypy --cache-dir "C:/Users/LancyCelestia/AppData/Local/Temp/v21-baseline-mypy-cache" --explicit-package-bases --ignore-missing-imports plugins
```
退出码：**1**。耗时 03:06:35→03:07:03（28s，未触 15 分钟截断线）。汇总（逐字）：`Found 11 errors in 4 files (checked 310 source files)`。

错误全列表（逐字，剔除 6 条 annotation-unchecked note）：
```
plugins\bot_unified_runtime\supervisor\acl_windows.py:135: error: Argument 1 to "wstring_at" has incompatible type "str | None"; expected "_PointerLike | Array[Any] | _CArgObject | int | bytes"  [arg-type]
plugins\bot_unified_runtime\supervisor\acl_windows.py:162: error: Incompatible return value type (got "int | None", expected "_Pointer[Any]")  [return-value]
plugins\bot_unified_runtime\supervisor\job_objects.py:412: error: Argument 1 to "from_buffer_copy" of "_PyCSimpleType" has incompatible type "list[bytes]"; expected "Buffer"  [arg-type]
plugins\bot_unified_runtime\supervisor\job_objects.py:415: error: Argument 1 to "from_bytes" of "int" has incompatible type "list[bytes]"; expected "Iterable[SupportsIndex] | SupportsBytes | Buffer"  [arg-type]
plugins\bot_unified_runtime\supervisor\appcontainer_windows.py:200: error: Incompatible return value type (got "int | None", expected "int")  [return-value]
plugins\bot_unified_runtime\supervisor\appcontainer_windows.py:209: error: Incompatible return value type (got "int | None", expected "int")  [return-value]
plugins\bot_unified_runtime\supervisor\appcontainer_windows.py:269: error: Incompatible return value type (got "tuple[int | None, int | None]", expected "tuple[int, int]")  [return-value]
plugins\bot_unified_runtime\supervisor\appcontainer_windows.py:284: error: Incompatible return value type (got "int | None", expected "int")  [return-value]
plugins\bot_unified_runtime\supervisor\appcontainer_windows.py:427: error: Argument 1 to "wstring_at" has incompatible type "str | None"; expected "_PointerLike | Array[Any] | _CArgObject | int | bytes"  [arg-type]
plugins\bot_unified_runtime\control_plane\api\platform.py:187: error: Argument 1 to "int" has incompatible type "Any | None"; expected "str | Buffer | SupportsInt | SupportsIndex | SupportsTrunc"  [arg-type]
plugins\bot_unified_runtime\control_plane\api\platform.py:366: error: Incompatible types in assignment (expression has type "DynamicASRProvider | None", variable has type "DynamicVisionProvider | None")  [assignment]
```
初步归属：9/11 在 A7 supervisor/（在飞并行域）；2/11 在 control_plane/api/platform.py（工作树存量控制面批，untracked，非 A3-A8 域→需主会话裁决归属）。

## 步骤6 失败归类与跑后复核

### 失败初步归类（pytest 69 项失败面 = 41 failed + 28 errors；另 ruff 26、mypy 11）

| 归类 | 数量 | 明细与依据 |
|---|---|---|
| **在飞并行域 A4（character/affinity.py + 好感度测试）** | 7 failed | tests/test_affinity_v21_budget.py 全文件 7 例；A4 正在改 affinity.py 与规格默认值（样例断言 `bot_poke_affinity_delta == 0.1`），属在飞中间态，最终裁决归 A4 收口 |
| **控制面批（untracked 新测试 + M control_plane/_app.py 等；不在 A3-A8 委派清单内，为工作树并行控制面工作）** | 32 failed + 28 errors = 60 | host_guard 14、m1 9、log_collectors 2、resources 1、services 1+19E、v1 2、actions_api 7E、workspaces_api 2E、runtime_feature_gate 3；关键实锚 `_app.py:425 UnboundLocalError` + FastAPIError（setup 阶段）+ `_app.py:276`「requires distinct read and super-admin tokens」 |
| **工作树存量（需主会话裁决）** | 2 failed | ① test_channel_health_v2.py::test_adaptive_timeout_tightens_by_ema[1000-expected0]（M llm/channel_health.py，断言细节未逐帧取证，完整栈在日志）；② test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync（doc_sync --check 非零，auto-facts 漂移） |
| **ruff 26 全部在飞/并行域** | 26 | A7 supervisor/ 18、A4 tests/test_affinity_v21_budget.py 3、A8 tests/test_contracts_v21.py 5 |
| **mypy 11** | 11 | A7 supervisor/ 9（acl_windows 2、job_objects 2、appcontainer_windows 5）；控制面存量 control_plane/api/platform.py 2（需主会话裁决归属） |

未发现纯环境类失败（无 WinError 5、无缺依赖、无 tmpdir 问题）。

### 跑后复核

**生成物哈希（跑后 sha256sum 复跑，与步骤1 逐字节对比）：5/5 零漂移**——tests/render_hashes.json、docs/command-catalog.md、docs/auto-facts.md、COMMANDS.md、docs/route-matrix.md 全部一致。`BOT_AUTOSYNC=0` 生效，未发生 autosync 重录污染；注意 docs/auto-facts.md 与 tests/render_hashes.json 在步骤2 快照中本来就是 M（工作树在跑前已被并行批改动），本席仅保证「本席两次采样间无漂移」。

**树卫生（跑后）**：`ls -d data` 无输出；`git status --porcelain` 中 `?? data`、`__pycache__`、`.pytest_cache` 均零命中。直跑纪律（-B + PYTHONDONTWRITEBYTECODE + basetemp 外置 + no:cacheprovider + ruff --no-cache + mypy cache 外置）未对源码树留下任何缓存/生成物。

**并发条件残留影响（unknown 项如实声明）**：
- A5（tests/test_v21_risk_red_*.py）与 A8（contracts/ 部分测试）文件在 pytest 收集时可能尚未落盘，本轮 7131 收集**不代表收齐后的终态集合**；A3 对 tests/conftest.py 的编辑若发生在收集前，其影响已计入本轮。
- channel_health_v2 失败的具体断言行未逐帧摘录（完整 traceback 保留于临时日志 `C:/Users/LancyCelestia/AppData/Local/Temp/v21-baseline-pytest-run.log`，TEMP 可能被系统清理）。

### 基线一句话总账

- **pytest**：41 failed + 28 errors（7050 passed / 9 skipped / 3 xfailed，252.80s，exit 1）——A4 域 7、控制面域 60、工作树存量 2。
- **ruff**：26 errors（exit 1）——全落在 A4/A7/A8 在飞域。
- **mypy**：11 errors in 4 files / 310 checked（exit 1）——A7 9、控制面存量 2。
- **生成物哈希零漂移、树卫生零污染**；本席未修复任何失败、未做任何写操作（唯一写入=本报告）。
