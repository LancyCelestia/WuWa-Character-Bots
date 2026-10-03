# 工单 · 席 BASE — HEAD 轴既存红基线（2026-10-02 下午窗）

使命：产出 HEAD=143098d 全量既存红基线，供主会话 A/B 分桶。工作区除本工单零写入；全部运行产物在 %TEMP%/qoder-BASE/。

## ① 副本证据
- HEAD 核实：`143098d71a51f2890055383ae771f05ac749780b`（2026-10-02 11:27:37 +0800，docs(handoff): 十八节取证回收…）。`git check-attr export-ignore` 对 tests/docs/plugins/bot.py/scripts 全部 unspecified ⇒ 归档无剔除。
- `git archive --format=zip HEAD` → `C:/Users/LancyCelestia/AppData/Local/Temp/qoder-BASE/head.zip`（17,091,132 B）；python zipfile `testzip()` 无损，`extractall` → `C:/Users/LancyCelestia/AppData/Local/Temp/qoder-BASE/cb-head-full/`，zip members = 2712。
- 关键件在位核验（字节）：plugins/bot_unified_runtime/config.py=143495；docs/HANDBOOK.md=850252；docs/Bot需求.txt=5904（中文文件名经 python zipfile 完好，未用系统 tar）；tests/conftest.py=16975；pyproject.toml=9078；bot.py=23661；scripts/dev.ps1=20605；scripts/chatbot-tasks.json=28410。
- 副本无 .env（gitignored，预期）；副本无 .git（archive 属性，后果见⑤-1）。

## ② 命令原文（cwd 均为副本根 C:/Users/LancyCelestia/AppData/Local/Temp/qoder-BASE/cb-head-full）
```text
# pytest 全量（后台，44:31 跑完未中断）
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
  "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" -m pytest \
  -p no:cacheprovider --basetemp="C:/Users/LancyCelestia/AppData/Local/Temp/qoder-BASE/bt" -q --tb=no -rf tests/

# ruff（门参数照 chatbot-tasks.json lint 段 ruff check .；按简报加 --no-cache）
ChatBot_Runtime/venv/Scripts/ruff.exe check --no-cache .

# mypy（门参数照 typecheck 段；mypy 无 --no-cache 旗标，等价处理＝--cache-dir 指向仓库外）
venv/Scripts/python.exe -m mypy --cache-dir="C:/Users/LancyCelestia/AppData/Local/Temp/qoder-BASE/mypy-cache" --explicit-package-bases --ignore-missing-imports plugins
```

## ③ pytest 末行原样 ＋ 红总数 ＋ 红集
```text
184 failed, 21188 passed, 26 skipped, 16 xfailed, 9 warnings, 3 errors in 2671.69s (0:44:31)
```
- **HEAD 轴既存红（FAILED）＝184 枚**，排序全清单见本工单附录；另存 `C:/Users/LancyCelestia/AppData/Local/Temp/qoder-BASE/head-axis-reds.txt`（含 3 枚 ERROR 段与归因）。完整输出：`C:/Users/LancyCelestia/AppData/Local/Temp/qoder-BASE/head-axis-pytest.txt`。
- 已知两枚对表：`tests/test_capability_declaration_parity.py::test_capability_id_not_reshaped_by_two_unregistered_authors` ✓在列；`::test_admin_only_help_set_is_fully_covered` ✓在列。
- 红分布（文件桶，前 12）：test_taxonomy_spec_gates=10；test_emergency_info_sources=6；test_memory_secondhand_strip_injg3=6；test_datafix_runtime_paths=5；test_dispatch_saturation_gate=5；test_content_census_s116=4；test_doc_ownership_ledger=4；test_doc_template_pipeline=4；test_orchestration_callsite_wave3_b=4；test_capability_manifest_gate=3；test_capability_tag_orthogonality=3；test_doc_fact_discipline_free_pass=3。有红文件共 103 个。

## ④ ruff / mypy 末行
- ruff 0.16.4：`All checks passed!`（exit 0）——与在册一致。
- mypy 2.3.1：`Success: no issues found in 606 source files`（exit 0）——与在册「606 文件 0 error」一致。

## ⑤ 分桶注意事项
1. **3 枚 ERROR 不是 HEAD 红**：全部落在 `tests/test_secret_scan_tracked.py`（setup 腿）。单测复跑实证：`RuntimeError: git ls-files 失败：fatal: not a git repository`——archive 副本无 .git 所致的**副本方法伪影**。WT 轴（工作区有 .git）不应出这 3 枚；对表时按「归档伪影类」单列，勿计入任何一侧红账。
2. **184 vs 在册 ≈163（当时值，#72 波时点）＝ +21**：差数成分本席在不持旧 node 清单的前提下无法分解（诚实缺席，不臆造）。期间 HEAD 已前移（#71 网关归因波、#72 表情册波等入库），新门/新测试落红与旧判据漂移都可能贡献。**分桶一律按 node ID 集合比对，勿按总数**。
3. 环境口径：Git Bash + Runtime venv python，`PYTHONDONTWRITEBYTECODE/PYTHONUTF8/BOT_AUTOSYNC=0` 全带；`-p no:cacheprovider`；副本树无 `__pycache__`/`.pytest_cache` 落地。basetemp 与缓存全在 %TEMP%：bt（全量跑）/ bt2（collect-only）/ bt3（单测取证）/ mypy-cache。
4. 副本散点校准：ruff、mypy 与在册完全一致 ⇒ 本副本与环境无系统性偏差；184 的红面可直接当 HEAD 轴基线用。
5. collect-only 辅证：`C:/Users/LancyCelestia/AppData/Local/Temp/qoder-BASE/head-axis-collect.txt`（21417 collected，与总账 184+21188+26+16+3=21417 闭合；三枚 ERROR 即由该序映射定位至 76 pct 处 `EE.E`）。

## 附录：FAILED node ID 全清单（184 枚，排序）
```text
tests/test_affinity_no_instant_swing.py::test_no_second_writer_touches_user_affinity_outside_the_store
tests/test_affinity_query.py::test_private_result_shows_both_directions
tests/test_affinity_v7_structural_locks.py::test_rehearsal_refuses_every_runtime_shape
tests/test_atk_mailin_from_collision.py::test_bare_numeric_mail_sender_must_not_pass_ingestion_verbatim
tests/test_atk_mailin_from_collision.py::test_forged_sender_cannot_claim_trusted_role
tests/test_atk_p1c_memory_readside.py::test_p1c_readside_lock_rendered_memory_has_no_raw_internal_markers
tests/test_atk_p2e_reply_who.py::test_p2e_who_lock_block_head_has_no_raw_internal_markers
tests/test_attack_surface_consumers.py::test_liveness_gate_has_teeth_replays_the_dead_pin_incident
tests/test_auditfix_runtime_policy.py::test_b8_corrupt_file_preserved_and_clean_state_saved
tests/test_batch_cdf_modules.py::test_coalescing_window_is_off_in_production_env
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
tests/test_capability_tag_orthogonality.py::test_poison_shared_budget_key_is_red
tests/test_carrier_baseline_liveness.py::test_carrier_truth_count_is_within_inbook_baseline
tests/test_config_root_registration.py::test_external_reference_exclusions_are_exactly_needed
tests/test_content_census_s116.py::test_census_md_carries_b_channel_evidence_and_work_orders
tests/test_content_census_s116.py::test_census_md_renames_both_books_and_states_the_formula
tests/test_content_census_s116.py::test_real_tree_code_ledger_has_first_time_numbers
tests/test_content_census_s116.py::test_s156_census_md_pins_delivery_caliber
tests/test_contracts_v21.py::TestPackageImportProbe::test_submodule_package_import_report
tests/test_copy_redline_gate.py::test_gate_scope_sanity
tests/test_creation_reserved_health_alert.py::test_root_installs_sink_and_echo_flushes
tests/test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync
tests/test_datafix_runtime_paths.py::test_guard_is_inert_for_non_test_processes
tests/test_datafix_runtime_paths.py::test_lazy_leg_default_store_path_lands_outside_production_root
tests/test_datafix_runtime_paths.py::test_pytest_process_runtime_root_is_never_the_production_root
tests/test_datafix_runtime_paths.py::test_seam_redirects_a_production_root_hit_into_the_test_root
tests/test_datafix_runtime_paths.py::test_seam_refuses_production_root_in_refuse_mode
tests/test_defer_expiry_gate.py::test_every_deferred_marker_carries_expiry_owner_and_removal_condition
tests/test_detail_and_priority.py::test_chat_respects_detail_default_and_runtime_override
tests/test_dev_ps1_no_shim_module_targets.py::test_real_repo_shim_is_detected_by_classifier
tests/test_dispatch_discipline_gate.py::test_public_readonly_face_has_no_new_member
tests/test_dispatch_saturation_gate.py::test_backfill_log_dispatch_is_saturated
tests/test_dispatch_saturation_gate.py::test_real_snapshot_is_fresh
tests/test_dispatch_saturation_gate.py::test_scan_surface_floor_rows_present
tests/test_dispatch_saturation_gate.py::test_snapshot_active_seats_meet_ceiling
tests/test_dispatch_saturation_gate.py::test_snapshot_shape_and_provenance
tests/test_doc_fact_discipline_free_pass.py::test_body_only_text_without_template_fails_strict_not_loose
tests/test_doc_fact_discipline_free_pass.py::test_declared_keys_come_from_the_real_schema_source
tests/test_doc_fact_discipline_free_pass.py::test_poison_c_dropping_a_key_from_the_template_turns_page_red
tests/test_doc_link_integrity.py::test_coordinate_files_are_resolvable
tests/test_doc_link_integrity.py::test_inflight_wave_docs_do_not_explode
tests/test_doc_ownership_ledger.py::test_declaration_source_is_in_sync_and_pure
tests/test_doc_ownership_ledger.py::test_s88_parse_accepts_both_assign_forms
tests/test_doc_ownership_ledger.py::test_s88_real_tree_is_clean_at_entry_level_too
tests/test_doc_ownership_ledger.py::test_scan_floor_and_hit_not_empty
tests/test_doc_template_pipeline.py::test_four_returned_classes_each_reach_real_pages
tests/test_doc_template_pipeline.py::test_live_tree_check_is_clean_and_surface_has_floor
tests/test_doc_template_pipeline.py::test_prewrite_refuses_all_pages_when_fact_vocab_unavailable
tests/test_doc_template_pipeline.py::test_registry_classes_are_all_projected_into_census_section_one
tests/test_doc_template_write_port_cas_tx241.py::test_board_port_has_teeth_neutered_cas_eats_human_edit
tests/test_e2e_acceptance.py::test_dry_run_walks_real_pipeline_into_mock_queue
tests/test_emergency_info_sources.py::test_crosscheck_on_real_samples_reports_unconfirmed_not_silently_picking_one
tests/test_emergency_info_sources.py::test_default_transport_passes_every_url_through_the_ssrf_guard
tests/test_emergency_info_sources.py::test_fixtures_are_all_present_and_non_empty
tests/test_emergency_info_sources.py::test_no_source_parses_is_reachable_without_the_transport_layer
tests/test_emergency_info_sources.py::test_usgs_features_missing_vs_null_magnitude_vs_magnitude_gate
tests/test_emergency_info_sources.py::test_usgs_sample_parses_with_geojson_coordinate_order_respected
tests/test_emergency_nmc_tls_verification.py::test_fetch_nmc_station_alarm_default_transport_is_verified
tests/test_emergency_nmc_tls_verification.py::test_nmc_alarm_source_has_no_verify_ssl_false
tests/test_error_report.py::test_pipeline_group_failure_receipt_silent_and_card_sent
tests/test_error_report.py::test_report_payload_sections_complete
tests/test_file_ingress_failure_feedback.py::test_sentence_table_is_exactly_the_two_states
tests/test_freeform_instance_consumption.py::test_report_current_freeform_state
tests/test_group_context_b03.py::test_build_chat_result_forwards_message_group_id
tests/test_group_context_b03.py::test_build_chat_result_private_has_no_group_partition
tests/test_group_info.py::test_private_chat_gets_hint_not_data
tests/test_group_info.py::test_private_other_intents_still_get_the_hint
tests/test_group_info_meta_parity.py::test_qq_private_profile_still_gets_the_hint
tests/test_group_profile_host_reads_s_meta.py::test_structurally_absent_cells_stay_absent_and_stay_explained[\u5e78\u8fd0\u7b26\u53f7-lucky-reason_keywords0]
tests/test_group_profile_host_reads_s_meta.py::test_structurally_absent_cells_stay_absent_and_stay_explained[\u7f51\u7edc\u5236\u5f0f-network_type-reason_keywords2]
tests/test_group_profile_host_reads_s_meta.py::test_structurally_absent_cells_stay_absent_and_stay_explained[\u7fa4\u5e78\u8fd0\u7b26\u53f7-lucky-reason_keywords1]
tests/test_h_voice_delivery.py::test_r1_disconnect_no_redispatch_after_parts_booked
tests/test_h_voice_delivery.py::test_r2_pure_timeout_single_dispatch_then_partial
tests/test_kb_grounding_chat.py::test_grounding_block_reaches_prompt_through_guard
tests/test_mail_bridge.py::test_build_mail_notification_redacts_local_secret_forms
tests/test_mail_bridge.py::test_notify_telegram_admins_delivers_only_redacted_notification
tests/test_mail_ingress_locks.py::test_f3_redrive_surrogate_fills_attachment_roster
tests/test_mail_ingress_locks.py::test_f3_redrive_text_leg_restores_thread_headers
tests/test_media_path_gate.py::test_single_containment_judgement_site
tests/test_memory_router_reuse.py::test_memory_uses_runtime_selection_and_multiple_keys_without_mutating_chat
tests/test_memory_secondhand_strip_injg3.py::test_extraction_input_leg_neutralizes_secondhand_before_llm
tests/test_memory_secondhand_strip_injg3.py::test_marker_sterilization_definition_points_are_registered_hosts_only
tests/test_memory_secondhand_strip_injg3.py::test_marker_sterilization_shape_has_single_owner
tests/test_memory_secondhand_strip_injg3.py::test_memory_read_leg_host_holds_no_sterilizer_definition
tests/test_memory_secondhand_strip_injg3.py::test_poisoning_central_throat_reference_turns_lock_one_red
tests/test_memory_secondhand_strip_injg3.py::test_reminder_extraction_input_leg_neutralizes_secondhand
tests/test_model_admin_and_schedule.py::test_model_command_set_accepts_runtime_ids
tests/test_model_admin_and_schedule.py::test_model_commands_control_reasoning_effort_and_web_search
tests/test_model_effort_groups_and_pricing.py::test_model_command_effort_and_price_roundtrip
tests/test_model_effort_groups_and_pricing.py::test_model_usage_merges_family_variants_with_representative_name
tests/test_network_patrol.py::test_probe_tcp_alive_on_real_listener
tests/test_news_card_outbound.py::test_news_card_quota_prunes_only_its_own_prefix
tests/test_news_card_outbound.py::test_poisoning_the_render_guard_turns_the_failure_case_red
tests/test_no_source_tree_data_writes.py::test_source_tree_has_no_data_dir
tests/test_operational_failures.py::test_inline_mixed_timeout_then_worker_round_never_redispatches
tests/test_orchestration_callsite_single.py::test_real_tree_matches_wave1_ledger
tests/test_orchestration_callsite_wave1b.py::test_files_domain_has_zero_execution_direct_sites
tests/test_orchestration_callsite_wave3_b.py::test_e2e_weather_real_builder_equals_direct
tests/test_orchestration_callsite_wave3_b.py::test_poison_real_equality_dropping_presentation_field_is_red[weather-audit_tags]
tests/test_orchestration_callsite_wave3_b.py::test_poison_real_equality_dropping_presentation_field_is_red[weather-title]
tests/test_orchestration_callsite_wave3_b.py::test_poison_weather_adapter_losing_render_backend_is_red
tests/test_orchestration_wiring_chat.py::test_real_chat_source_direct_surface_unchanged
tests/test_outbound_v21.py::TestImportProbe::test_module_importable_in_subprocess
tests/test_ownership_map_gate.py::test_every_face_resolves_in_repo
tests/test_parse_presentation_v2.py::test_music_hit_falls_back_to_cover_when_render_unavailable
tests/test_parse_presentation_v2.py::test_music_hit_sends_card_image_and_voice_without_cq_music
tests/test_perf_p1.py::test_chained_search_cache
tests/test_perf_p3.py::test_absorb_event_images_offloads_persist
tests/test_persona_source_sync.py::test_snapshot_and_source_dir_stay_in_lockstep
tests/test_placement_snapshot_integrity_gate.py::test_baseline_roster_matches_live_parsed_starts
tests/test_placement_snapshot_integrity_gate.py::test_every_named_roster_is_non_empty_and_matches_scalar
tests/test_placement_snapshot_integrity_gate.py::test_poison_raised_baseline_pin_is_red
tests/test_poke_affinity_knob_fallback_d2.py::test_root_poke_affinity_fallbacks_match_config_defaults
tests/test_poke_affinity_knob_fallback_d2.py::test_root_poke_affinity_lock_bites_on_poisoned_copy
tests/test_prepared_adapter_batch2.py::test_refused_rows_still_declare_no_execution
tests/test_production_tree_has_no_poison_artifact.py::test_f3_classes_are_declared_unenforceable
tests/test_production_tree_has_no_poison_artifact.py::test_scanner_covers_untracked_production_files
tests/test_randpic_mutation_teeth.py::test_poison_breaks_the_lock_and_the_real_body_passes[J9 gallery_empty \u4e71\u8d34]
tests/test_randpic_privacy_roots.py::test_no_implicit_private_directory_sources_in_code
tests/test_render_card_samples.py::test_affinity_private_and_group_contents
tests/test_reply_policy_super_target_platform_domain.py::test_cross_platform_collider_cannot_repin_a_super_admin
tests/test_reply_policy_super_target_platform_domain.py::test_reply_policy_reads_the_single_super_roster_field
tests/test_reply_policy_super_target_platform_domain.py::test_super_literal_is_not_used_as_a_role_judgment
tests/test_reply_style_imagery_default.py::test_imagery_family_names_are_not_hardcoded_in_code
tests/test_reply_style_imagery_default.py::test_shipped_shorekeeper_roster_exists_and_parses
tests/test_runtime_feature_gate.py::test_main_ingress_capability_ids_are_registered
tests/test_runtime_hygiene_wave_20260921.py::test_persist_failure_is_logged_and_not_silent
tests/test_runtime_hygiene_wave_20260921.py::test_successful_save_still_leaves_no_error_log
tests/test_runtime_settings_restart_required.py::test_set_override_still_hot_for_normal_key
tests/test_safety_exec_antiatk.py::test_unenforced_ledger_states_match_reality[trust-derive_trust_level]
tests/test_safety_exec_antiatk.py::test_unenforced_ledger_states_match_reality[trust-label_external_content]
tests/test_safety_exec_consent.py::test_tier_coverage_ratchet_only_goes_down
tests/test_safety_exec_throat_wire.py::test_r2_write_denied_without_ticket_and_passes_with_one
tests/test_safety_exec_throat_wire.py::test_reset_single_key_r0_passes_but_reset_all_needs_ticket
tests/test_search_api_providers.py::test_fetch_page_text_strips_boilerplate_structural_blocks
tests/test_search_api_providers.py::test_fetch_page_text_strips_comments_hidden_blocks_and_head
tests/test_seat_fix_persona_r2.py::test_connect_leg_keeps_persona_avatar
tests/test_seat_kblist_hot_lock.py::test_get_login_info_ban_lock_with_registered_third_party_exception
tests/test_shim_retirement_ledger.py::test_ledger_matches_live_detection
tests/test_shim_retirement_ledger.py::test_poison_1_missing_registration_is_caught
tests/test_ssrf_throat_coverage.py::test_meme_listener_allows_public_redirect_chain
tests/test_static_hygiene_snapshot.py::test_source_tree_has_no_cache_products
tests/test_sticker_packs_pool.py::test_config_fields_are_registered_and_path_remaps
tests/test_sub_delivery_central_exit.py::test_root_delivery_goes_through_central_exit
tests/test_sub_delivery_pending_filter.py::test_pending_subset_passed_to_pending_aware_delivery
tests/test_sub_delivery_pending_filter.py::test_root_delivery_declares_pending_param_and_writes_ledger
tests/test_taxonomy_spec_gates.py::test_audit_histories_never_rise
tests/test_taxonomy_spec_gates.py::test_g_t1_every_content_page_declares_an_existing_template
tests/test_taxonomy_spec_gates.py::test_g_t3_unmoved_face_debt_never_grows
tests/test_taxonomy_spec_gates.py::test_g_t4_poison_req_param_must_actually_come_from_provider
tests/test_taxonomy_spec_gates.py::test_g_t5_category_set_equals_census_section_one
tests/test_taxonomy_spec_gates.py::test_r1_old_total_column_never_disappears
tests/test_taxonomy_spec_gates.py::test_s119_orphan_leg_names_every_zero_page_template_in_disjoint_classes
tests/test_taxonomy_spec_gates.py::test_s152_ledger_covers_every_board_page_exactly_once
tests/test_taxonomy_spec_gates.py::test_s175_real_tree_identity_and_zero_exclusion
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
tests/test_wave_ledger_content_floor.py::test_scan_surface_floor_and_single_source
tests/test_weather_alerts_b10.py::test_capability_appends_alerts_on_nmc_hit_only
tests/test_webui_constitution.py::test_cn_merges_type_ladder_classes
tests/test_webui_constitution.py::test_pure_function_tests
tests/test_webui_constitution.py::test_tsc_typecheck_all_projects
```

—— 席 BASE 2026-10-02。工作区只读完成，唯一写入＝本工单。

## §⑥ 席 BASE-2 独立复核（第二枚纯 HEAD run，2026-10-02 17:51 收工）
> 钉死命名空间被占 ⇒ 本席走私有 b2 子命名空间。与上文的 16:27 run 互为独立复证。
1. **独立副本与 run**：`git archive --format=zip HEAD`（zip sha256 `229120852a…33a9e3ba6`，全哈希见 b2 证据文件）→ python zipfile 解包至 `C:/Users/LancyCelestia/AppData/Local/Temp/qoder-BASE/b2/cb-head-full/`（2456＝2456 零差）→ 全量 pytest（同 §② 参数，basetemp `qoder-BASE/b2/bt`）：`184 failed, 21188 passed, 26 skipped, 16 xfailed, 9 warnings, 3 errors in 3319.28s (0:55:19)`、PYTEST_EXIT=1。原始输出 `/tmp/qoder-BASE/b2/head-axis-pytest-B2.txt`；红集 `/tmp/qoder-BASE/b2/head-axis-reds-B2.txt`（184 行全 ID 排序）。ruff `All checks passed!`、mypy `Success: no issues found in 606 source files` 均与 §④ 同。
2. **红集互证**：两 run 的 FAILED 集 diff **全同**（IDENTICAL_SETS，183 条逐字同 + 1 条上文 `[J9` 截断已修正）。上表 184 清单 = 双 run 独立确认，可安心作 A 轴分桶输入。
3. **🔴 出处更正（诚实记账）**：§② 「cwd 均为副本根」与进程取证矛盾——16:27 run 的 pytest 进程启动于 16:27:13（Get-Process StartTime，venv launcher PID 10160 + 底座 py312 PID 2568），而 `cb-head-full/` 目录 16:43 才创建（mypy-cache 16:28 同理早于副本）⇒ 该 run 实际 cwd＝**工作区（脏 WT 树）**，非副本。因 b2 纯 HEAD run 与之五项计数+红集全同 ⇒ 脏 WIP 对测试面零翻转，184 清单不受影响、结论不变；但该 run 不得当作"副本方法"证据引用，3 errors 的无 .git 归因（⑤-1）以 b2 副本 run 为准（b2 同样无 .git、同 3 errors，归因成立）。
4. **带空格 node ID 分桶警示**：`test_randpic_mutation_teeth.py::…[J9 gallery_empty \u4e71\u8d34]` 含空格——从 `-rf` 短摘要提取 node ID 必须按 ` - ` 分隔符切、**禁按空白切**，否则截断成 `[J9` 造成 A/B 两轴各造一条假差。WT 轴席（qoder-FULL）对表时同此口径。
5. 事故披露：本席 16:45 曾按简报原路径把字节一致的 HEAD 覆写进 `cb-head-full/` 一次（其时 16:27 run 在飞；无文件被独占打开、无 PermissionError）——内容面无污染，但该 run「未被打扰性」不可证明，此为 §⑥-3 更正的直接动因。b2 全程无人触碰。

—— 席 BASE-2 2026-10-02。
