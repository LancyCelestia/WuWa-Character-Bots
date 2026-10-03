# G58 工单 — GONE_ONLY 58 枚转绿归因（2026-10-02 下午窗 · 归因席 · 只读）

输入＝`%TEMP%/qoder-main/final-bucket.txt` GONE_ONLY 段（A 轴=`git archive HEAD` 仓外抽取、B 轴=工作树，函数级 58 枚）。手段＝测试文件状态依赖现读 + 在盘工单引证（ITX/OWN/DOL/IMG/FLR/BKT/MIG/D2F）+ 工作树抽验复跑。全程只读（本工单除外）。

## ① 58 枚清单（函数级）

affinity_v7 rehearsal_refuses_every_runtime_shape ｜ batch_cdf coalescing_window_off ｜ config_root external_reference_exclusions ｜ content_census census_md_carries_b_channel＋s156_pins_delivery_caliber ｜ contracts_v21 TestPackageImportProbe ｜ cross_validation doc_sync_auto_facts_in_sync ｜ datafix×5（guard_is_inert／lazy_leg_default_store／pytest_process_root／seam_redirects／seam_refuses）｜ dispatch_discipline public_readonly_face ｜ dispatch_saturation×3（floor_rows／seats_ceiling／shape_provenance）｜ doc_fact_discipline×3（body_only_strict／declared_keys_schema／poison_c_drop_key）｜ doc_link×2（coordinate_resolvable／inflight_not_explode）｜ doc_ownership×4（declaration_sync／s88_parse／s88_entry_clean／scan_floor）｜ doc_template×4（four_classes_reach／live_tree_floor／prewrite_refuses／registry_projected）｜ e2e dry_run_walks ｜ error_report payload_sections ｜ freeform report_current_state ｜ mail_ingress×2（f3_surrogate／f3_text_leg）｜ no_source_data ｜ outbound_v21 TestImportProbe ｜ ownership_map every_face_resolves ｜ persona_source_sync lockstep ｜ placement×3（baseline_roster／named_roster／poison_raised）｜ production_tree f3_declared_unenforceable ｜ randpic poison_breaks_lock[J9] ｜ reply_policy_super×3（collider_repin／single_roster_field／super_literal）｜ imagery×2（names_not_hardcoded／roster_exists_parses）｜ shim×2（ledger_matches／poison_1）｜ ssrf meme_listener_redirect ｜ static_hygiene no_cache_products ｜ sticker config_fields_remaps ｜ taxonomy×4（g_t5_category_set／r1_old_total／s119_orphan／s175_identity）｜ wave_ledger scan_surface_floor

## ② 归簇表

| 簇 | 枚 | 转绿机制 | 证据 |
|---|---|---|---|
| A1 席册/快照缺件 | 8＝dispatch_saturation 3＋dispatch_discipline 1＋wave_ledger 1＋placement 3 | **非修复**：门读 `.superpowers/`（ignore 目录，`git archive HEAD` 不带）＝SEAT-MAIN.md／DISPATCH-SNAPSHOT.json／BASELINE.md／波目录；A 轴缺件必红、工作树在盘即绿 | test_dispatch_saturation_gate.py:46-47、test_dispatch_discipline_gate.py:9、test_placement_snapshot_integrity_gate.py（BASELINE.md）、test_wave_ledger_content_floor.py:45-52（`_wave_dirs`）；`git ls-files .superpowers`＝0 |
| A2 CENSUS 席册缺件 | 14＝content_census 2＋doc_template 4＋taxonomy 4＋doc_fact_discipline 3＋freeform 1 | 同上：`scripts/spec_gates_census.py:53` 硬读 `.superpowers/sdd/2026-09-22-taxonomy/CENSUS.md`，缺件即 import/compute 期塌 | spec_gates_census.py:53,232-234；test_content_census_s116.py:34；test_doc_template_pipeline.py:368；g_t5 腿名即 census_section_one |
| B .env/.env.prod 缺件 | 8＝datafix 5＋batch_cdf 1＋config_root 1＋sticker 1 | 同上：dotenv 均 gitignored；`runtime_paths.py` 生产根读 `BOT_RUNTIME_DATA_DIR`(.env)（datafix 前提塌）；batch_cdf 直接 `dotenv_values(".env")`；config_root 载 (".env",".env.prod")；sticker `Config()` 读 .env | runtime_paths.py:31-42,74；test_batch_cdf_modules.py:42；test_config_root_registration.py:105；test_sticker_packs_pool.py:391-401 |
| C 相邻 Runtime 数据区缺件 | 1＝affinity_v7 rehearsal | A 轴抽取目录无相邻 `ChatBot_Runtime/`，前提断言 `production.parent.exists()` 必炸 | test_affinity_v7_structural_locks.py:889-890（自带前提行） |
| D 在飞/晨窗未入库改动修绿 | 18＝mail 2＋doc_ownership 4＋shim 2＋reply_policy_super 3＋ssrf 1＋doc_link 2＋e2e 1＋randpic 1＋imagery 2 | 工作树未提交 WIP（生产件＋测试件）直接修绿：nonebot.py F3 重投 hunk（ITX 实跑修绿账）；doc_ownership 晨窗增量（测试+207/生产+9，DOL 27P）；shim 台账+42/生产+36；reply_policy.py +231（中置信，TRG 未点名）；doc_link 测试+570；ssrf 测试+41；e2e 测试+60；randpic J9 腿+10；imagery 测试+2 | ITX §②②③、DOL ①④、`git diff --stat HEAD`（本席现算） |
| E 生成册重录 | 1＝auto_facts_in_sync | 17:24 `doc_sync --write` 重录 980→982（未入库 docs/auto-facts.md M） | ITX §②①、OWN ③（2 passed） |
| F 人格资产恢复 | 1＝persona_source_sync lockstep | `personas/shorekeeper/imagery_families.txt` 未跟踪件已恢复在盘（HEAD 无此件）；IMG 工单 12 族实读 | IMG §①③⑤、git status `??` |
| G 瞬态树面 | 2＝static_hygiene＋no_source_data | 缓存/`data/` 产物在盘与否翻板：本席复跑当场咬到 `.ruff_cache/`（某席 ruff 未带 --no-cache 所留）＝现在红；B 轴时刻干净＝绿；A 轴红同属瞬态产物 | 本席复跑读数（§③）；断言原文 "cache-class products present" |
| H 未知 | 5＝contracts_v21 探针＋outbound_v21 探针＋error_report payload＋ownership_map face＋production_tree f3_declared | 工作树已验真绿，A 轴红因未定位（嫌疑：子进程导入面/在飞 content_route 等关联；未深挖，超本席窗） | 本席复跑绿（§③）；无在盘工单点名 |

## ③ 复跑抽验读数（venv＋卫生前缀，2026-10-02 实跑）

- 批 1（7 件）：datafix＋batch_cdf＋config_root＋reply_policy_super＋freeform＋static_hygiene＋no_source_data ⇒ `1 failed, 63 passed`——唯一红＝static_hygiene（`.ruff_cache/` 在盘，瞬态实证）。
- 批 2（5 腿）：error_report payload＋contracts_v21 Probe＋outbound_v21 Probe＋sticker remaps＋affinity rehearsal ⇒ `5 passed in 22.44s`。
- 合计抽 13 件/腿：12 真绿确认、1 瞬态翻板（反证 G 簇机理）。

## ④ "未知"簇点名（5 枚）

`test_contracts_v21.py::TestPackageImportProbe::test_submodule_package_import_report`、`test_outbound_v21.py::TestImportProbe::test_module_importable_in_subprocess`、`test_error_report.py::test_report_payload_sections_complete`、`test_ownership_map_gate.py::test_every_face_resolves_in_repo`、`test_production_tree_has_no_poison_artifact.py::test_f3_classes_are_declared_unenforceable`。终局账若需铁账，建议按 NB4 法对 A 轴单腿复跑取红因原文。

## ⑤ 结论

58 枚 GONE_ONLY 中 **27 枚（A1/A2/B/C）＝A 轴 `git archive HEAD` 抽取缺 ignore 件的环境性红，不是任何修复的功劳**；真修复/在飞修绿＝20 枚（D 18＋E 1＋F 1）；瞬态 2；未知 5。另勘误：ITX 在册的 "s10 2＋datafix 5" 七枚，终桶里 s10 两腿已回 COMMON（B 轴复红，与 ITX 实跑时点漂移），GONE_ONLY 实存仅 datafix 5。终结报告引用"转绿"时不得把 A1/A2/B/C 记为本窗战果。
