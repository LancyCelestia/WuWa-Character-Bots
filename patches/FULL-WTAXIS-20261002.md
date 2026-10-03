# FULL-WTAXIS-20261002 — 工作树轴全量 pytest（Wave-2 · 席 FULL）

> 终门 A/B 分桶的 **B 轴输入**。对工作区只读（本工单除外）。BASICTEMP/venv 均在仓库外；`BOT_AUTOSYNC=0` 硬性。
> 在飞干扰声明：DBT/D2F 两席共享树在写 `tests/test_db_backup.py` / `tests/test_store_write_trace_d2.py`，若落入本窗口属预期（工作树轴如实记账）。

## ① 快照
- 开工时刻（UTC）：2026-10-02T08:49:21Z
- `git status --porcelain | wc -l` = **88**（开跑前读数；节选：AGENTS.md / docs/HANDBOOK.md / docs/auto-facts.md / 多份 board README / chat.py / echo.py / reply_policy.py / meme_library.py / tests/render_hashes*.json / tests/test_config_key_registration_ledger.py / tests/test_db_owners_coverage.py / tests/test_doc_link_integrity.py / tests/test_doc_ownership_ledger.py 等）
- venv python：`ChatBot_Runtime/venv/Scripts/python.exe` 存在（verified）

## ② 命令原文（实跑形态）
```
cd "c:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot" && \
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
c:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe \
  -m pytest -p no:cacheprovider --basetemp="C:/Users/LancyCelestia/AppData/Local/Temp/qoder-FULL/bt" \
  -q --tb=no -rf tests/ \
  > "$TEMP/qoder-FULL/wt-axis-pytest.txt" 2>&1
```
- 注：Git Bash `$TEMP=/tmp` → Windows 侧 `C:\Users\LancyCelestia\AppData\Local\Temp`（cygpath verified）；`--basetemp` 用显式 Windows 路径防 MSYS 换歧义。输出文件=`%TEMP%\qoder-FULL\wt-axis-pytest.txt`。

## ③ 结果
- **末行原样**：`131 failed, 21533 passed, 15 skipped, 18 xfailed, 8 warnings in 3038.33s (0:50:38)`
- 完整跑完的那次（第 2 次）：09:53Z 起跑，10:42:39Z 收（wrapper EXIT=1＝pytest 有红的正常退出码）。
- 红总数：**131**（FAILED 行计数与末行汇总一致，无重复 node ID）
- 红集指针：`%TEMP%\qoder-FULL\wt-axis-reds.txt`（Git Bash `/tmp/qoder-FULL/wt-axis-reds.txt`；131 行排序 node ID，已剥 ` - 原因` 尾巴）
- collection error：**无**（末行汇总无 error 项；输出中的 error 命中均为失败详情内 UnicodeDecodeError/Pydantic 弃用告警）
- 首 20 行红：
  ```
  tests/test_affinity_no_instant_swing.py::test_no_second_writer_touches_user_affinity_outside_the_store
  tests/test_affinity_query.py::test_private_result_shows_both_directions
  tests/test_atk_mailin_from_collision.py::test_bare_numeric_mail_sender_must_not_pass_ingestion_verbatim
  tests/test_atk_mailin_from_collision.py::test_forged_sender_cannot_claim_trusted_role
  tests/test_atk_p1c_memory_readside.py::test_p1c_readside_lock_rendered_memory_has_no_raw_internal_markers
  tests/test_atk_p2e_reply_who.py::test_p2e_who_lock_block_head_has_no_raw_internal_markers
  tests/test_attack_surface_consumers.py::test_liveness_gate_has_teeth_replays_the_dead_pin_incident
  tests/test_auditfix_runtime_policy.py::test_b8_corrupt_file_preserved_and_clean_state_saved
  tests/test_board_taxonomy_gate.py::test_r0_registered_columns_stay_wired_to_the_scan
  tests/test_capability_declaration_parity.py::test_admin_only_help_set_is_fully_covered
  tests/test_capability_declaration_parity.py::test_capability_id_not_reshaped_by_two_unregistered_authors
  tests/test_capability_manifest_gate.py::test_leg7_coverage_ratchet_never_rises
  tests/test_capability_manifest_gate.py::test_leg8_direct_callsites_declared_match_census
  tests/test_capability_manifest_gate.py::test_poison_callsite_new_site_not_followed_is_red
  tests/test_capability_manifest_ratchet_direction.py::test_ratchet_baselines_equal_live_measurement[ROSTER_SCAN_FLOOR]
  tests/test_capability_manifest_ratchet_direction.py::test_roster_side_shrink_is_caught_by_ceiling_or_blindness
  tests/test_capability_registry.py::test_help_public_visibility_derived_from_declaration
  tests/test_capability_registry.py::test_help_topics_equal_registry_book_order
  tests/test_capability_tag_orthogonality.py::test_leg1_family_switch_keys_are_disjoint
  tests/test_capability_tag_orthogonality.py::test_live_paths_read_the_real_tables
  ```
- 末 20 行红：
  ```
  tests/test_taxonomy_spec_gates.py::test_g_t3_unmoved_face_debt_never_grows
  tests/test_taxonomy_spec_gates.py::test_g_t4_poison_req_param_must_actually_come_from_provider
  tests/test_taxonomy_spec_gates.py::test_g_t4_poison_req_param_must_actually_come_from_provider
  tests/test_taxonomy_spec_gates.py::test_s152_ledger_covers_every_board_page_exactly_once
  tests/test_taxonomy_spec_gates.py::test_s20_root_md_now_enumerated
  tests/test_trigger_word_single_source.py::test_copy_turned_into_reference_lowers_ledger_stays_green
  tests/test_trigger_word_single_source.py::test_word_site_debt_within_ceiling
  tests/test_user_copy_unification_gate.py::test_current_tree_no_scattered_failure_copy
  tests/test_v21_f3_outbound_capability_registration.py::test_runtime_init_capability_id_literals_all_registered
  tests/test_v21_s10_protocols.py::TestMediaFamilyHonestBranches::test_anime_ip_unconfigured_key
  tests/test_v21_s10_protocols.py::TestSearchFamilyMockInvocations::test_reference_fetch_happy_path_with_fake_fetcher
  tests/test_v21_s11_timetable.py::TestRecognize::test_prior_overrides_ocr
  tests/test_v21r2_lifecycle_r2.py::test_p4_reaper_returns_cleanly_when_no_stuck_threads
  tests/test_video_ingest_ssrf_entry.py::test_audio_clip_rejects_internal_url_before_ffmpeg
  tests/test_voice_central_entry_gate.py::test_gate1_scan_set_is_exhaustive_over_plugins_tree
  tests/test_voice_hook_error_card_leg.py::test_gap_hook_structural_no_card_raise_would_kill_reply
  tests/test_voice_hook_error_card_leg.py::test_leg_egress_is_issue_only_card_hook_and_bubble_stay_zero
  tests/test_weather_alerts_b10.py::test_capability_appends_alerts_on_nmc_hit_only
  tests/test_webui_constitution.py::test_cn_merges_type_ladder_classes
  tests/test_webui_constitution.py::test_pure_function_tests
  tests/test_webui_constitution.py::test_tsc_typecheck_all_projects
  ```
- ⚠ **第 1 次运行被外部 SIGKILL 中断**：09:51:13Z 检获 exit 137（非本席操作；本席未做任何进程动作）。阵亡时进度 82%（约 62 分钟处），输出文件 20,178 字节。处置＝同命令整体重跑（进度文件覆盖重来），红集只认完整跑完的那次。
- pytest 末行原样：待填
- 红总数：待填；红集指针：`%TEMP%/qoder-FULL/wt-axis-reds.txt`（排序 FAILED node ID，首末各 20 行见下）
- collection error 处置：待填（如触发：等 120s 重跑该件，记录两次读数）

## ④ 与在册 run9 读数粗对照
- run9（当时值）：139 failed / 21479 passed
- 本次（B 轴，完整跑）：131 failed / 21533 passed / 15 skipped / 18 xfailed
- 粗差：红 **-8**，绿 **+54**。⚠ 仅粗对照不归因：本窗为共享树（快照 88 脏件，DBT/D2F 等席在飞写入 `test_db_backup.py` / `test_store_write_trace_d2.py` 及多份源码），且测试集本身会漂移；分桶定论以终门 A/B 对照为准。

## ⑤ 未尽事项
1. 第 1 次运行 09:51:13Z 被外部 SIGKILL（exit 137，82% 处），非本席所为；已整体重跑并以第 2 次为准。若调度方需追查杀手来源，本席无证据（无进程动作权限面）。
2. 红集/输出文件在 `%TEMP%\qoder-FULL\`（Git Bash `/tmp`＝`C:\Users\LancyCelestia\AppData\Local\Temp`，cygpath verified）；TEMP 清理会吃掉这两份，需留存请调度方另行归档。
3. DBT/D2F 两席若在本窗之后继续落盘，本读数即过时——以终门当时的 A/B 双轴为准。
4. 本席零 git 写、零进程动作（仅启动 pytest 进程本身）、零 .env 改、除本工单外未写任何工作区文件。
