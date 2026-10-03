# 工单 IVF-INTIMATE-BLAST-RADIUS-20261002（席 IVF · 更宽爆炸半径回归族）

> 使命：复核席 INT 改动（`content_route.py::explicit_allowed_for_session` 群分支人腿 ＋ `tts.py` 补传 sender_id）的更宽爆炸半径回归。全程只读（本工单除外），pytest 卫生前缀齐备（`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 -p no:cacheprovider --basetemp=$TEMP/qoder-IVF/bt`）。
> 时间：2026-10-02 下午窗 · 第三派（前两席被并发墙弹回零产出）。

## ① 引用面圈定证据

- `git grep -l "explicit_allowed_for_session" -- tests/` → 6 件：`test_content_route_v3.py`、`test_trigger_bidirectional_gate.py`、`test_tts_contract_layer.py`、`test_tts_speech_gate.py`、`test_tts_t75.py`、`test_v21r2_content_probe.py`。
- `git grep -l "tts" -- tests/` → 102 项（含 `tests/conftest.py`，非测试件剔除）。
- `git grep -lE "speech_block_reason|voice_enricher" -- tests/` → 17 件，**全部**已含于 tts 组，无增量。
- **三组并集去重＝100 件**（清单存 `$TEMP/qoder-IVF/list_union.txt`），另加工单第 4 项 `tests/test_intimate_group_switch_delivery.py`（预期 16 passed）＝**101 件全跑**。

## INT 改动只读取证（工作区在飞未入库）

- `git status --porcelain`：`M plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`、`M plugins/bot_unified_runtime/domains/media/capabilities/tts.py`（另有大量他席在飞 WIP：chat.py、echo.py、aliases.py、voice_enricher.py 等）。
- content_route.py diff＝群分支重排（①群黑名单永远赢→②群白名单命中即放行→③人腿：`sid` 命中 `bot_content_route_private_whitelist` 且不在私聊黑名单⇒放行→④不放行；空 sender_id 行为与旧版逐字节一致）。
- tts.py diff 除 INT 的 sender_id 补传外**另含席 B1 的 `_quota_bound` 配额形态闸**（与 INT 无关的他席在飞面）⇒ 红分桶时须区分。


## ② 逐件读数（代码=pytest 退出码；末行原样）

| 件 | code | 末行 |
|---|---|---|
| tests/test_content_route_v3.py | 0 | 41 passed in 5.98s |
| tests/test_trigger_bidirectional_gate.py | 0 | 16 passed in 6.78s |
| tests/test_tts_contract_layer.py | 0 | 32 passed in 4.11s |
| tests/test_tts_speech_gate.py | 0 | 10 passed in 5.86s |
| tests/test_tts_t75.py | 0 | 27 passed in 5.49s |
| tests/test_v21r2_content_probe.py | 0 | 14 passed in 4.99s |
| tests/test_intimate_group_switch_delivery.py | 0 | 16 passed in 8.42s |
| tests/test_alert_error_card.py | 0 | 28 passed in 4.20s |
| tests/test_alert_plain_text.py | 0 | 38 passed in 3.20s |
| tests/test_billing_service_v21.py | 0 | 58 passed in 7.66s |
| tests/test_capability_health_readout.py | 0 | 17 passed in 2.34s |
| tests/test_capability_manifest_gate.py | 1 | 3 failed, 73 passed in 18.78s |
RED-NODES tests/test_capability_manifest_gate.py:
FAILED tests/test_capability_manifest_gate.py::test_leg7_coverage_ratchet_never_rises
FAILED tests/test_capability_manifest_gate.py::test_leg8_direct_callsites_declared_match_census
FAILED tests/test_capability_manifest_gate.py::test_poison_callsite_new_site_not_followed_is_red
| tests/test_capability_manifest_ratchet_direction.py | 1 | 2 failed, 29 passed in 12.31s |
RED-NODES tests/test_capability_manifest_ratchet_direction.py:
FAILED tests/test_capability_manifest_ratchet_direction.py::test_ratchet_baselines_equal_live_measurement[ROSTER_SCAN_FLOOR]
FAILED tests/test_capability_manifest_ratchet_direction.py::test_roster_side_shrink_is_caught_by_ceiling_or_blindness
| tests/test_capability_registry.py | 1 | 2 failed, 16 passed in 4.19s |
RED-NODES tests/test_capability_registry.py:
FAILED tests/test_capability_registry.py::test_help_topics_equal_registry_book_order
FAILED tests/test_capability_registry.py::test_help_public_visibility_derived_from_declaration
| tests/test_capability_single_registration.py | 0 | 12 passed in 12.67s |
| tests/test_capability_tag_orthogonality.py | 1 | 3 failed, 36 passed in 30.25s |
RED-NODES tests/test_capability_tag_orthogonality.py:
FAILED tests/test_capability_tag_orthogonality.py::test_leg1_family_switch_keys_are_disjoint
FAILED tests/test_capability_tag_orthogonality.py::test_live_paths_read_the_real_tables
FAILED tests/test_capability_tag_orthogonality.py::test_poison_shared_budget_key_is_red
| tests/test_central_seam_census_offseam_tag_consistency.py | 0 | 10 passed in 11.51s |

| tests/test_config_key_registration_ledger.py | TIMEOUT>300s | killed by driver (hang; recorded, continuing) |
| tests/test_config_keys_single_source.py | 0 | 17 passed in 4.88s |
| tests/test_config_root_registration.py | 0 | 5 passed in 2.28s |
| tests/test_control_plane_image_api.py | 0 | 17 passed in 12.48s |
| tests/test_control_plane_tts_api.py | 0 | 16 passed in 20.04s |
| tests/test_copy_single_source.py | 0 | 12 passed in 27.79s |
| tests/test_creation_job_protocol.py | 0 | 25 passed in 4.39s |
| tests/test_creation_job_store.py | 0 | 70 passed in 10.05s |
| tests/test_creation_protocol_parity.py | 0 | 63 passed in 4.80s |
| tests/test_creation_reserved_gap_ledger.py | 0 | 13 passed in 5.75s |
| tests/test_creation_reserved_health_alert.py | 1 | 1 failed, 31 passed, 1 xfailed in 5.46s |
RED-NODES tests/test_creation_reserved_health_alert.py:
FAILED tests/test_creation_reserved_health_alert.py::test_root_installs_sink_and_echo_flushes
| tests/test_creation_tts_drift_gate.py | 0 | 23 passed in 15.29s |
| tests/test_creation_tts_engine_provider.py | 0 | 17 passed in 3.18s |
| tests/test_datafix_runtime_paths.py | 0 | 20 passed in 13.21s |
| tests/test_descriptor_wiredness_ledger.py | 0 | 21 passed in 44.43s |
| tests/test_doc_sync_gates.py | 0 | 27 passed in 7.67s |
| tests/test_env_verifier.py | 0 | 20 passed in 16.24s |
| tests/test_error_report.py | 1 | 1 failed, 59 passed, 1 skipped in 4.32s |
RED-NODES tests/test_error_report.py:
FAILED tests/test_error_report.py::test_pipeline_group_failure_receipt_silent_and_card_sent
| tests/test_feature_gate_layer2.py | 0 | 14 passed in 4.73s |
| tests/test_file_send_receive_parity.py | 0 | 18 passed in 4.35s |
| tests/test_gate_scoped_direct_callsite_ledger.py | 0 | 14 passed in 5.32s |
| tests/test_generic_executor_facets.py | 0 | 13 passed in 4.79s |
| tests/test_h_dedupe_content_key.py | 0 | 10 passed in 2.99s |
| tests/test_help_entries_coverage.py | 0 | 12 passed in 3.04s |
| tests/test_manifest_tag_evidence.py | 0 | 14 passed in 2.55s |
| tests/test_media_digest.py | 0 | 8 passed in 2.30s |
| tests/test_media_orchestration_wiring.py | 0 | 9 passed in 2.27s |
| tests/test_media_tts_autodub_central.py | 0 | 7 passed in 2.35s |
| tests/test_offseam_wired_contradiction_gate.py | 0 | 8 passed in 11.62s |
| tests/test_orchestration_callsite_single.py | 1 | 1 failed, 29 passed in 4.86s |
RED-NODES tests/test_orchestration_callsite_single.py:
FAILED tests/test_orchestration_callsite_single.py::test_real_tree_matches_wave1_ledger
| tests/test_orchestration_callsite_wave3_d.py | 0 | 20 passed in 16.94s |
| tests/test_orchestration_callsite_wave_media.py | 0 | 12 passed in 6.58s |
| tests/test_ownership_map_gate.py | 0 | 24 passed in 4.71s |
| tests/test_pipeline_review_fixes.py | 0 | 22 passed in 5.33s |
| tests/test_poke_arms_v3.py | 0 | 28 passed in 4.68s |
| tests/test_poke_five_way_matrix.py | 0 | 38 passed in 4.18s |
| tests/test_poke_three_line_routing.py | 0 | 37 passed in 3.57s |
| tests/test_pre_restart_check.py | 0 | 30 passed in 4.11s |
| tests/test_redrive_window_exhaustion.py | 0 | 18 passed in 2.41s |
| tests/test_reviewer_media_visibility.py | 0 | 9 passed in 2.33s |
| tests/test_runtime_config_loader.py | 0 | 14 passed in 2.69s |
| tests/test_seat_feat_persona_prof.py | 0 | 7 passed in 4.31s |
| tests/test_silent_skip_ratchet.py | 0 | 9 passed in 35.70s |
| tests/test_sync_drift_activation.py | 0 | 38 passed in 4.26s |
| tests/test_text_boundary_central.py | 0 | 81 passed in 2.69s |
| tests/test_trigger_word_copy_ratchet.py | 0 | 18 passed in 43.17s |
| tests/test_trigger_word_single_source.py | 1 | 2 failed, 16 passed in 94.92s (0:01:34) |
RED-NODES tests/test_trigger_word_single_source.py:
FAILED tests/test_trigger_word_single_source.py::test_word_site_debt_within_ceiling
FAILED tests/test_trigger_word_single_source.py::test_copy_turned_into_reference_lowers_ledger_stays_green
| tests/test_tts.py | 0 | 64 passed in 3.55s |
| tests/test_tts_audio_gate.py | 0 | 7 passed in 2.83s |
| tests/test_tts_autodub_split.py | 0 | 10 passed in 2.66s |
| tests/test_tts_backoff_commit_point.py | 0 | 8 passed in 2.86s |
| tests/test_tts_cache_identity.py | 0 | 6 passed in 2.58s |
| tests/test_tts_config_gates.py | 0 | 37 passed in 2.61s |
| tests/test_tts_corpus_gate.py | 0 | 5 passed, 3 xfailed in 2.75s |
| tests/test_tts_corpus_tools.py | 0 | 23 passed in 3.02s |
| tests/test_tts_creation_gate_reality.py | 0 | 9 passed in 3.66s |
| tests/test_tts_error_surface.py | 0 | 26 passed in 3.95s |
| tests/test_tts_failure_visibility.py | 0 | 9 passed in 3.16s |
| tests/test_tts_filename_privacy.py | 0 | 4 passed in 3.54s |
| tests/test_tts_health_backoff.py | 0 | 4 passed in 2.59s |
| tests/test_tts_hijack_guard.py | 0 | 89 passed in 3.26s |
| tests/test_tts_identity_watch.py | 0 | 15 passed in 2.78s |
| tests/test_tts_item8_dual_send.py | 0 | 13 passed in 2.48s |
| tests/test_tts_media_digest.py | 0 | 8 passed in 2.78s |
| tests/test_tts_outbound_chain.py | 0 | 23 passed in 2.45s |
| tests/test_tts_presets.py | 0 | 18 passed in 2.28s |
| tests/test_tts_probability_lock.py | 0 | 22 passed in 7.08s |
| tests/test_tts_result_transform.py | 0 | 29 passed in 2.35s |
| tests/test_tts_t127.py | 0 | 4 passed in 2.36s |
| tests/test_two_column_alignment.py | 0 | 8 passed in 2.53s |
| tests/test_usage_billing_v21.py | 0 | 28 passed in 4.47s |
| tests/test_v21_creation_skeleton.py | 0 | 39 passed in 6.49s |
| tests/test_v21_s10_protocols.py | 0 | 62 passed in 3.39s |
| tests/test_voice_boundary_central_gate.py | 0 | 11 passed in 2.47s |
| tests/test_voice_central_entry_gate.py | 1 | 1 failed, 41 passed in 6.23s |
RED-NODES tests/test_voice_central_entry_gate.py:
FAILED tests/test_voice_central_entry_gate.py::test_gate1_scan_set_is_exhaustive_over_plugins_tree
| tests/test_voice_enricher_central_dispatch.py | 0 | 12 passed in 2.92s |
| tests/test_voice_health_alert_sink.py | 0 | 9 passed in 3.79s |
| tests/test_voice_health_probe.py | 0 | 17 passed in 2.60s |
| tests/test_voice_hook_assembly.py | 0 | 11 passed, 1 xfailed in 2.78s |
| tests/test_voice_hook_error_card_leg.py | 1 | 2 failed, 6 passed in 2.35s |
RED-NODES tests/test_voice_hook_error_card_leg.py:
FAILED tests/test_voice_hook_error_card_leg.py::test_leg_egress_is_issue_only_card_hook_and_bubble_stay_zero
FAILED tests/test_voice_hook_error_card_leg.py::test_gap_hook_structural_no_card_raise_would_kill_reply
| tests/test_voice_offline_selfcheck.py | 0 | 8 passed in 2.59s |
| tests/test_voice_outbound_contract.py | 0 | 24 passed in 2.65s |
| tests/test_voice_queue_sim.py | 0 | 14 passed in 3.14s |
| tests/test_voice_retcode_collect.py | 0 | 10 passed in 2.93s |

## ③ 红与 HEAD 对照（终稿：11 处红面全覆盖）

> 对照法＝台账 #68 正道：`git archive HEAD -o head.tar` 解包到仓库外 `$TEMP/qoder-IVF/headrepo`（零工作树写入），同 venv 解释器、同卫生前缀、独立 basetemp `bt-head` 复跑红件。工作树红节点以②段 RED-NODES 为准，HEAD 副本按同件复跑对节点。

- `tests/test_capability_manifest_gate.py`：工作树 3 failed/73 passed，HEAD 副本 3 failed/73 passed——**同 3 节点同数复红** ⇒ HEAD 级红：`test_leg7_coverage_ratchet_never_rises`（`assert 105 <= 101` 未申报枚数超上限 :992）、`test_leg8_direct_callsites_declared_match_census`（普查有直呼点而册未申报 :1011）、`test_poison_callsite_new_site_not_followed_is_red`（:1110 真数据两向腿已红，注毒无从自证）。
- `tests/test_capability_manifest_ratchet_direction.py`：两面同 2 节点（2 failed/29 passed）⇒ HEAD 级红：`test_ratchet_baselines_equal_live_measurement[ROSTER_SCAN_FLOOR]`（`assert 104 == 105`，账与实况脱钩 :361）、`test_roster_side_shrink_is_caught_by_ceiling_or_blindness`（`assert 104 == (104 - 1)` :498）。
- `tests/test_capability_registry.py`：两面同 2 节点（2 failed/16 passed）⇒ HEAD 级红：`test_help_topics_equal_registry_book_order`（`assert 83 == 82` :414）、`test_help_public_visibility_derived_from_declaration`（`assert (39 == 39 and 44 == 43)` :440）。
- `tests/test_capability_tag_orthogonality.py`：两面同 3 节点（3 failed/36 passed）⇒ HEAD 级红：`test_leg1_family_switch_keys_are_disjoint`（两族共用 `bot_request_budget_seconds` :406）、`test_live_paths_read_the_real_tables`（`assert 57 == 58` :624）、`test_poison_shared_budget_key_is_red`（:636 真数据已红，注毒样本无法自证）。

### 新 6 红 HEAD 对照（同法 headrepo 复跑）

- `test_creation_reserved_health_alert.py`：HEAD 同节点复红（1 failed/31 passed）⇒ HEAD 级红。断言首行：`assert (True and '_push_creation_patrol_issue' == '_push_probe_issue'`（:166）。
- `test_error_report.py`：工作树 1 failed/59 passed/1 skipped（红节点＝`test_pipeline_group_failure_receipt_silent_and_card_sent`，断言首行 `assert <ReceiptState.BLOCKED> is <ReceiptState.FAILED_FINAL>` :570）；HEAD 副本 **2 failed**/58 passed——同节点复红之外**另红 1 枚** `test_report_payload_sections_complete`。该枚工作树已绿＝在飞面他席已修（缩小非扩大）；工作树这枚红仍归 HEAD 级。
- `test_orchestration_callsite_single.py`：HEAD 同节点复红 ⇒ HEAD 级红。断言首行：`直呼面漂移：实得 {...} ≠ 登记 {...}`（:418）。
- `test_trigger_word_single_source.py`：HEAD 同 2 节点复红 ⇒ HEAD 级红。断言首行：`词面级独立声明债（计账）475 > 上限 467`（:696）／`方向锁失效：手抄=565 引用=549 基线=549`（:839）。
- `test_voice_central_entry_gate.py`：HEAD 同节点复红 ⇒ HEAD 级红。断言首行：`出现未归类的音频出站点：['__init__.py']`（:897）。
- `test_voice_hook_error_card_leg.py`：HEAD 同 2 节点复红 ⇒ HEAD 级红。断言首行：`AttributeError: 'tuple' object has no attribute 'handle_async'`（:360/:393）。

### 挂死件专项（test_config_key_registration_ledger.py）

- 工作区：驱动两次处决（600s、300s 均超时）。HEAD 副本：**36 passed in 532.28s**＝固有极慢（约 9 分钟）非挂死。工作区 600s 窗终跑见⑤。
- 该件断言面＝config 键登记册（`bot.tts.*` 等键普查）；INT 两改动不触及 config 键册。

- **终跑定论**：工作区 600s 窗复跑＝`39 passed in 593.81s` ⇒ **绿**（固有慢跑 ≈9 分钟；两次被处决系驱动 300s 帽过紧，非测试红）。HEAD 副本 `36 passed in 532.28s`；36→39 差额＝在飞面他席新增 3 枚键测试，属预期演化非红。

## ④ 净新增红判定（本席轴＝INT 改动引入与否）

**净新增红＝0 枚。** 证据链：

1. 全轴 101 件（三组 grep 并集 100 ＋ 复核件）逐件实跑：90 绿＋10 红＋1 慢跑（终跑绿）。
2. 10 红全部在 `git archive HEAD` 仓外副本同尺复跑（#68 正道，非保险 zip 捷径）：9 件**节点 ID 逐一相同复红**；`test_error_report.py` 工作树红节点是 HEAD 红节点的**子集**（HEAD 另多 1 枚、工作树已绿＝在飞修复，非新增）。⇒ 全部为 HEAD 级既有红，工作树无一枚新红，与任何在飞 WIP（含 INT）无关。
3. 红面内容普查：10 红全是**普查/棘轮账面类**（能力册普查 105>101、触发词债 475>467、语音出站点未归类、直呼面漂移、ReceiptState 枚举、tag 正交账、注毒自证腿），**无一触及** `explicit_allowed_for_session` 语义或 `tts.py` sender_id 调用面。
4. INT 改动最近邻锁全绿：`test_content_route_v3` 41p、`test_trigger_bidirectional_gate` 16p、`test_v21r2_content_probe` 14p、`test_intimate_group_switch_delivery` **16 passed（符合预期值）**；`test_tts_*` 族 22 件全绿（含 `test_tts_contract_layer` 32p、`test_tts_speech_gate` 10p、`test_tts_t75` 27p）。

## ⑤ 未尽事项

1. **解释器坑**：全局 Python 缺 nonebot（初跑 7 件 code=2 收集错，已作废重跑）；本席正式跑钉 `../ChatBot_Runtime/venv/Scripts/python.exe`（3.12.10）。接手席直跑 pytest 勿用全局解释器。
2. `tests/conftest.py` 命中 tts grep（夹具含 tts 字样）非测试件，已剔除不计。
3. 慢跑件现实：`test_config_key_registration_ledger.py`（≈10 分钟）、`test_trigger_word_single_source.py`（≈95s）、`test_capability_tag_orthogonality.py`（≈37s）——全量批跑须放宽单件帽至 ≥600s。
4. 10 枚 HEAD 级红的修复归属不在本席轴（账面/普查类棘轮，牵动多席在飞面），未动、未修；详见③段节点与断言首行。
5. `test_v21r2_content_probe.py` 等 6 件 explicit_allowed_for_session 命中件未覆盖"人腿"新分支的专项断言（INT 自测 4 件邻域锁之外，本轴未见他人补人腿锁）——人腿专项锁是否要立，留主会话裁量。
6. 工作区在飞面含多席 WIP（chat.py/echo.py/aliases.py/voice_enricher.py/config_store.py 等），本工单红绿读数为**盘面即时值**，不承诺可复现性（他席续写即漂）。
